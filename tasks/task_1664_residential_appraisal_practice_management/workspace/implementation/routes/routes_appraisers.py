"""Appraiser endpoints (PRD 3.2): roster, supervision, standing scorecard."""

from decimal import Decimal

from flask import request

import webbase as base
import envelope
import services
import store
from errors import ApiError
from timeutil import business_days_between, clock, parse_date


def _completed_orders(appraiser_id):
    return store.ordered(
        o for o in store.orders.values()
        if o["assigned_appraiser_id"] == appraiser_id and o["first_delivered_at"] is not None
    )


def register(app):
    @app.route("/appraisal/appraisers", methods=["POST"])
    def create_appraiser():
        base.auth.require_roles("FirmAdmin")
        body = base.read_body()
        services.require_fields(body, ["full_name", "license_level", "license_number", "license_expiry"])
        full_name = services.require_string(body, "full_name")
        license_level = services.require_enum(body, "license_level", services.LICENSE_LEVELS)
        license_number = services.require_string(body, "license_number")
        license_expiry = services.require_date(body, "license_expiry")
        # supervisor_id: required iff TRAINEE, forbidden otherwise (PRD 3.2).
        supervisor_id = body.get("supervisor_id")
        supervisor = None
        if license_level == "TRAINEE":
            if supervisor_id is None:
                raise ApiError("ERR_VALIDATION", "supervisor_id is required for TRAINEE appraisers.")
            if not isinstance(supervisor_id, str) or not supervisor_id.strip():
                raise ApiError("ERR_VALIDATION", "supervisor_id must be a non-empty string.")
            supervisor = services.get_appraiser(supervisor_id)
            if supervisor["license_level"] != "CERTIFIED_RESIDENTIAL":
                raise ApiError("ERR_SUPERVISOR_NOT_CERTIFIED")
        else:
            if "supervisor_id" in body and body.get("supervisor_id") is not None:
                raise ApiError("ERR_VALIDATION", "supervisor_id is forbidden for non-TRAINEE appraisers.")
            supervisor_id = None
        row = store.new_row(
            store.appraisers,
            full_name=full_name,
            license_level=license_level,
            license_number=license_number,
            license_expiry=license_expiry,
            supervisor_id=supervisor_id,
            status="ACTIVE",
            sanction_override=False,
        )
        return base.obj(row, 201)

    @app.route("/appraisal/appraisers/<appraiser_id>", methods=["GET"])
    def get_appraiser(appraiser_id):
        base.auth.require_roles("FirmAdmin", "Appraiser", "QCReviewer")
        row = services.get_appraiser(appraiser_id)
        # PRD 3.2: an Appraiser-role caller may read only their own record.
        if base.auth.role == "Appraiser" and base.auth.user_id != row["id"]:
            raise ApiError("ERR_NOT_RESOURCE_OWNER")
        return base.obj(row)

    @app.route("/appraisal/appraisers", methods=["GET"])
    def list_appraisers():
        base.auth.require_roles("FirmAdmin")
        level = request.args.get("license_level")
        status = request.args.get("status")
        supervisor_id = request.args.get("supervisor_id")
        rows = store.appraisers.values()
        if level is not None:
            rows = [r for r in rows if r["license_level"] == level]
        if status is not None:
            rows = [r for r in rows if r["status"] == status]
        if supervisor_id is not None:
            rows = [r for r in rows if r["supervisor_id"] == supervisor_id]
        return base.listing(rows, request.args)

    @app.route("/appraisal/appraisers/<appraiser_id>/deactivate", methods=["POST"])
    def deactivate_appraiser(appraiser_id):
        base.auth.require_roles("FirmAdmin")
        row = services.get_appraiser(appraiser_id)
        if row["status"] != "ACTIVE":
            raise ApiError("ERR_INVALID_STATE")
        if services.inflight_count(row["id"]) > 0:
            raise ApiError("ERR_APPRAISER_HAS_OPEN_ASSIGNMENTS")
        row["status"] = "INACTIVE"
        store.touch(row)
        return base.obj(row)

    @app.route("/appraisal/appraisers/<appraiser_id>/reactivate", methods=["POST"])
    def reactivate_appraiser(appraiser_id):
        base.auth.require_roles("FirmAdmin")
        row = services.get_appraiser(appraiser_id)
        if row["status"] != "INACTIVE":
            raise ApiError("ERR_INVALID_STATE")
        expiry = parse_date(row["license_expiry"])
        if expiry is None or not (expiry > clock.today):
            raise ApiError("ERR_LICENSE_EXPIRED")
        row["status"] = "ACTIVE"
        store.touch(row)
        return base.obj(row)

    @app.route("/appraisal/appraisers/<appraiser_id>/clear-sanction", methods=["POST"])
    def clear_sanction(appraiser_id):
        base.auth.require_roles("FirmAdmin")
        row = services.get_appraiser(appraiser_id)
        # PRD 3.2: flips sanction_override off; nothing the cascade took is
        # restored.  standing is recomputed on read.
        if row["sanction_override"]:
            row["sanction_override"] = False
            store.touch(row)
        return base.obj(row)

    @app.route("/appraisal/appraisers/<appraiser_id>/scorecard", methods=["GET"])
    def scorecard(appraiser_id):
        base.auth.require_roles("FirmAdmin", "Appraiser")
        row = services.get_appraiser(appraiser_id)
        if base.auth.role == "Appraiser" and base.auth.user_id != row["id"]:
            raise ApiError("ERR_NOT_RESOURCE_OWNER")
        completed = _completed_orders(row["id"])
        completed_count = len(completed)
        on_time = [o for o in completed if o["_first_delivered_dt"] <= o["_due_at_dt"]]
        on_time_count = len(on_time)
        if completed_count == 0:
            rate = None
            avg_calendar = None
            avg_business = None
        else:
            rate = float(
                Decimal(services._rhup(Decimal(on_time_count) * 10000 / Decimal(completed_count)))
                / Decimal(10000)
            )
            total_calendar = sum(
                (o["_first_delivered_dt"] - o["_accepted_dt"]).total_seconds() / 86400.0
                for o in completed
            )
            avg_calendar = float(
                Decimal(services._rhup(Decimal(str(total_calendar / completed_count)) * 100)) / Decimal(100)
            )
            total_business = sum(
                business_days_between(o["_accepted_dt"], o["_first_delivered_dt"]) for o in completed
            )
            avg_business = float(
                Decimal(services._rhup(Decimal(total_business) * 100 / Decimal(completed_count))) / Decimal(100)
            )
        confirmed_minutes = 0
        for appt in store.appointments.values():
            if appt["appraiser_id"] == row["id"] and appt["status"] == "CONFIRMED":
                delta = appt["_window_end_dt"] - appt["_window_start_dt"]
                confirmed_minutes += int(delta.total_seconds() // 60)
        no_show_count = sum(
            1 for a in store.appointments.values()
            if a["appraiser_id"] == row["id"] and a["status"] == "NO_SHOW"
        )
        payload = {
            "appraiser_id": row["id"],
            "completed_count": completed_count,
            "on_time_count": on_time_count,
            "on_time_rate": rate,
            "avg_calendar_turn_days": avg_calendar,
            "avg_business_turn_days": avg_business,
            "confirmed_minutes": confirmed_minutes,
            "no_show_count": no_show_count,
            "standing": services.compute_standing(row),
            "sanction_override": row["sanction_override"],
        }
        return envelope.object_response(payload)
