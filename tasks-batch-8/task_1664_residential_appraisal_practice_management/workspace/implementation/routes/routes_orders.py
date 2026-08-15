"""AppraisalOrder endpoints (PRD 3.3, 3.4, 3.9)."""

from datetime import timedelta
from decimal import Decimal

from flask import request

import webbase as base
import services
import store
from errors import ApiError
from timeutil import clock, render_instant


def _require_own_client_order(order):
    """ClientUser ownership: the order's client_id must equal X-User-ID."""
    if base.auth.role == "ClientUser" and order["client_id"] != base.auth.user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")


def register(app):
    @app.route("/appraisal/orders", methods=["POST"])
    def create_order():
        base.auth.require_roles("ClientUser", "FirmAdmin")
        body = base.read_body()
        services.require_fields(
            body,
            ["client_id", "property_address", "property_type",
             "estimated_value_cents", "loan_type", "requested_turn_days"],
        )
        property_address = services.require_string(body, "property_address")
        property_type = services.require_enum(body, "property_type", services.PROPERTY_TYPES)
        estimated_value = services.require_int(body, "estimated_value_cents", strictly_positive=True)
        loan_type = services.require_enum(body, "loan_type", services.LOAN_TYPES)
        turn_days = services.require_int(body, "requested_turn_days", minimum=1)
        client_id = body["client_id"]
        if not isinstance(client_id, str) or not client_id.strip():
            raise ApiError("ERR_VALIDATION", "client_id must be a non-empty string.")

        # Ownership precedes reference resolution in the ladder: a ClientUser
        # quoting another client's id is a 403, not a 404.
        if base.auth.role == "ClientUser" and client_id != base.auth.user_id:
            raise ApiError("ERR_NOT_RESOURCE_OWNER")
        client = services.get_client(client_id)
        if client["status"] != "ACTIVE":
            raise ApiError("ERR_CLIENT_NOT_ACTIVE")
        row = store.new_row(
            store.orders,
            client_id=client["id"],
            property_address=property_address,
            property_type=property_type,
            estimated_value_cents=estimated_value,
            loan_type=loan_type,
            requested_turn_days=turn_days,
            complexity_tier=None,
            requires_inspection=True,
            assigned_appraiser_id=None,
            requires_supervisor_cosign=False,
            fee_quoted_cents=None,
            fee_current_cents=None,
            surcharge_total_cents=0,
            waived_total_cents=0,
            revision_fees_collected_cents=0,
            cancellation_fee_cents=None,
            status="RECEIVED",
            accepted_at=None,
            due_at=None,
            first_delivered_at=None,
            inspection_completed_at=None,
            open_complaint_count=0,
            completed_at=None,
            _accepted_dt=None,
            _due_at_dt=None,
            _first_delivered_dt=None,
        )
        return base.obj(row, 201)

    @app.route("/appraisal/orders/<order_id>", methods=["GET"])
    def get_order(order_id):
        base.auth.require_roles("FirmAdmin", "ClientUser", "Appraiser", "QCReviewer")
        row = services.get_order(order_id)
        _require_own_client_order(row)
        return base.obj(row)

    @app.route("/appraisal/orders", methods=["GET"])
    def list_orders():
        base.auth.require_roles("FirmAdmin")
        client_id = request.args.get("client_id")
        appraiser_id = request.args.get("assigned_appraiser_id")
        status = request.args.get("status")
        rows = store.orders.values()
        if client_id is not None:
            rows = [r for r in rows if r["client_id"] == client_id]
        if appraiser_id is not None:
            rows = [r for r in rows if r["assigned_appraiser_id"] == appraiser_id]
        if status is not None:
            rows = [r for r in rows if r["status"] == status]
        return base.listing(rows, request.args)

    @app.route("/appraisal/orders/<order_id>/determine-scope", methods=["POST"])
    def determine_scope(order_id):
        base.auth.require_roles("FirmAdmin")
        order = services.get_order(order_id)
        if order["status"] != "RECEIVED":
            raise ApiError("ERR_INVALID_STATE")
        body = base.read_body()
        override = None
        if "complexity_tier_override" in body and body["complexity_tier_override"] is not None:
            override = services.require_enum(body, "complexity_tier_override", services.TIERS)
        requires_inspection = True
        if "requires_inspection" in body and body["requires_inspection"] is not None:
            requires_inspection = services.require_bool(body, "requires_inspection")
        client = services.get_client(order["client_id"])
        if client["status"] != "ACTIVE":
            raise ApiError("ERR_CLIENT_NOT_ACTIVE")
        tier = services.resolve_tier_override(order, override)
        if requires_inspection is False and tier != "STANDARD":
            raise ApiError("ERR_DESKTOP_NOT_ALLOWED")
        order["complexity_tier"] = tier
        order["requires_inspection"] = requires_inspection
        # fee_quote provisional variant: as-of the logical clock now.
        order["fee_quoted_cents"] = services.fee_quote(order, client, tier, clock.now)
        order["status"] = "SCOPE_DETERMINED"
        store.touch(order)
        return base.obj(order)

    @app.route("/appraisal/orders/<order_id>/accept", methods=["POST"])
    def accept_order(order_id):
        base.auth.require_roles("FirmAdmin")
        order = services.get_order(order_id)
        if order["status"] != "SCOPE_DETERMINED":
            raise ApiError("ERR_INVALID_STATE")
        client = services.get_client(order["client_id"])
        if client["status"] != "ACTIVE":
            raise ApiError("ERR_CLIENT_NOT_ACTIVE")
        # fee_quote final variant: as-of the acceptance timestamp.
        order["fee_current_cents"] = services.fee_quote(order, client, order["complexity_tier"], clock.now)
        order["accepted_at"] = store.now_string()
        order["_accepted_dt"] = clock.now
        due = clock.now + timedelta(days=order["requested_turn_days"])
        order["due_at"] = render_instant(due)
        order["_due_at_dt"] = due
        order["status"] = "ACCEPTED"
        store.touch(order)
        services.file_workfile(order, "ORDER_FORM")
        return base.obj(order)

    @app.route("/appraisal/orders/<order_id>/assign", methods=["POST"])
    def assign_order(order_id):
        base.auth.require_roles("FirmAdmin")
        order = services.get_order(order_id)
        if order["status"] != "ACCEPTED":
            raise ApiError("ERR_INVALID_STATE")
        body = base.read_body()
        appraiser_id = body.get("appraiser_id")
        tier = order["complexity_tier"]

        def gates(appraiser):
            """The four assignment gates of PRD 3.4, in ladder order."""
            if (
                appraiser["status"] != "ACTIVE"
                or appraiser["sanction_override"]
                or services.compute_standing(appraiser) == "PANEL_SUSPENDED"
            ):
                raise ApiError("ERR_APPRAISER_NOT_ASSIGNABLE")
            on_panel = any(
                m["client_id"] == order["client_id"]
                and m["appraiser_id"] == appraiser["id"]
                and m["status"] == "ACTIVE"
                for m in store.panel_memberships.values()
            )
            if not on_panel:
                raise ApiError("ERR_APPRAISER_NOT_ON_PANEL")
            level = appraiser["license_level"]
            if tier == "HIGH_VALUE" and level != "CERTIFIED_RESIDENTIAL":
                raise ApiError("ERR_LICENSE_LEVEL_INSUFFICIENT")
            if tier == "COMPLEX" and level not in ("LICENSED", "CERTIFIED_RESIDENTIAL"):
                raise ApiError("ERR_LICENSE_LEVEL_INSUFFICIENT")
            from timeutil import parse_date
            expiry = parse_date(appraiser["license_expiry"])
            if expiry is None or not (expiry > clock.today):
                raise ApiError("ERR_LICENSE_EXPIRED")

        if appraiser_id is not None:
            appraiser = services.get_appraiser(appraiser_id)
            gates(appraiser)
        else:
            # Deterministic panel selector: on_time_rate DESC (null -> 1.0000),
            # in-flight load ASC, appraiser created_at ASC.
            candidates = []
            for candidate in store.appraisers.values():
                try:
                    gates(candidate)
                except ApiError:
                    continue
                candidates.append(candidate)
            if not candidates:
                raise ApiError("ERR_NO_ELIGIBLE_APPRAISER")

            def rank(candidate):
                rate = services.on_time_rate(candidate)
                rate_key = rate if rate is not None else Decimal("1.0000")
                return (
                    -rate_key,
                    services.inflight_count(candidate["id"]),
                    store.order_key(candidate),
                )

            candidates.sort(key=rank)
            appraiser = candidates[0]

        order["assigned_appraiser_id"] = appraiser["id"]
        order["requires_supervisor_cosign"] = appraiser["license_level"] == "TRAINEE"
        order["status"] = "ASSIGNED"
        store.touch(order)
        return base.obj(order)

    @app.route("/appraisal/orders/<order_id>/cancel", methods=["POST"])
    def cancel_order(order_id):
        base.auth.require_roles("FirmAdmin", "ClientUser")
        order = services.get_order(order_id)
        _require_own_client_order(order)
        cancellable = ("RECEIVED", "SCOPE_DETERMINED", "ACCEPTED", "ASSIGNED")
        if base.auth.role == "ClientUser":
            cancellable = ("RECEIVED", "SCOPE_DETERMINED")
        if order["status"] not in cancellable:
            raise ApiError("ERR_INVALID_STATE")
        # cancellation_fee (PRD 3.9): 0 before ACCEPTED, else half the current fee.
        if order["status"] in ("ACCEPTED", "ASSIGNED"):
            fee = services._rhup(Decimal(order["fee_current_cents"]) * Decimal("0.5"))
            order["cancellation_fee_cents"] = fee
        else:
            order["cancellation_fee_cents"] = 0
        order["status"] = "CANCELLED"
        store.touch(order)
        for appt in store.appointments.values():
            if appt["order_id"] == order["id"] and appt["status"] in ("PROPOSED", "CONFIRMED"):
                appt["status"] = "CANCELLED"
                store.touch(appt)
        return base.obj(order)

    @app.route("/appraisal/orders/<order_id>/start-analysis", methods=["POST"])
    def start_analysis(order_id):
        base.auth.require_roles("Appraiser")
        order = services.get_order(order_id)
        if order["status"] == "ASSIGNED" and order["requires_inspection"] is False:
            pass  # desktop orders move ASSIGNED -> IN_ANALYSIS directly
        elif order["status"] == "INSPECTED":
            pass
        else:
            raise ApiError("ERR_INVALID_STATE")
        if base.auth.user_id != order["assigned_appraiser_id"]:
            raise ApiError("ERR_NOT_ASSIGNED_APPRAISER")
        order["status"] = "IN_ANALYSIS"
        store.touch(order)
        return base.obj(order)

    @app.route("/appraisal/orders/<order_id>/complete", methods=["POST"])
    def complete_order(order_id):
        base.auth.require_roles("FirmAdmin")
        order = services.get_order(order_id)
        if order["status"] != "DELIVERED":
            raise ApiError("ERR_INVALID_STATE")
        for req in store.revision_requests.values():
            if req["order_id"] == order["id"] and req["status"] in ("OPEN", "ACCEPTED"):
                raise ApiError("ERR_INVALID_STATE")
        if order["open_complaint_count"] != 0:
            raise ApiError("ERR_COMPLIANCE_HOLD_ACTIVE")
        required = {"ORDER_FORM", "COMP_DATA", "REPORT_PDF", "CERTIFICATION"}
        if order["requires_inspection"]:
            required.add("INSPECTION_NOTES")
        covered = {
            r["snapshot_type"]
            for r in store.workfile_records.values()
            if r["order_id"] == order["id"] and r["status"] != "PURGED"
        }
        if not required.issubset(covered):
            raise ApiError("ERR_WORKFILE_INCOMPLETE")
        order["status"] = "COMPLETED"
        order["completed_at"] = store.now_string()
        store.touch(order)
        return base.obj(order)

    @app.route("/appraisal/orders/<order_id>/fee-adjustments", methods=["POST"])
    def fee_adjustment(order_id):
        base.auth.require_roles("FirmAdmin")
        order = services.get_order(order_id)
        if order["status"] in ("CANCELLED", "COMPLETED"):
            raise ApiError("ERR_INVALID_STATE")
        body = base.read_body()
        services.require_fields(body, ["kind", "amount_cents", "reason"])
        kind = services.require_enum(body, "kind", services.ADJUSTMENT_KINDS)
        amount = services.require_int(body, "amount_cents", strictly_positive=True)
        services.require_string(body, "reason")
        if kind == "WAIVER":
            current = order["fee_current_cents"] or 0
            if amount > current:
                raise ApiError("ERR_FEE_WAIVER_EXCEEDS_BALANCE")
            order["fee_current_cents"] = current - amount
            order["waived_total_cents"] += amount
        else:
            order["fee_current_cents"] = (order["fee_current_cents"] or 0) + amount
            order["surcharge_total_cents"] += amount
        store.touch(order)
        return base.obj(order)
