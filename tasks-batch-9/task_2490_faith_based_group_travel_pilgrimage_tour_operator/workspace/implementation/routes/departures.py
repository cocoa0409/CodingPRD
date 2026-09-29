"""Departures (PRD sections 3.1, 3.9)."""

from flask import Blueprint

import core
import response
from db import db, lock
from errors import err
from middleware import (OPERATOR_ROLES, ROLE_FINANCE_CONTROLLER, ROLE_PROGRAM_MANAGER,
                        ROLE_RISK_OFFICER, authorize)
from validate import (apply_filters, body_of, opt_bool, pagination, req_date, req_id,
                      req_int, req_str)

bp = Blueprint("departures", __name__)


def _load(departure_id):
    row = db.departures.get(departure_id)
    if row is None:
        err("ERR_DEPARTURE_NOT_FOUND", "Departure %s does not exist." % departure_id)
    return row


@bp.route("/departures", methods=["POST"])
def create_departure():
    authorize((ROLE_PROGRAM_MANAGER,))
    body = body_of()
    with lock:
        program_id = req_id(body, "program_id")
        departure_date = req_date(body, "departure_date")
        return_date = req_date(body, "return_date")
        min_pax = req_int(body, "min_pax", 1)
        max_pax = req_int(body, "max_pax", 1)
        deposit_due_date = req_date(body, "deposit_due_date")
        final_payment_due_date = req_date(body, "final_payment_due_date")
        mobility_accessible_coach = opt_bool(body, "mobility_accessible_coach", False)

        if max_pax < min_pax:
            err("ERR_INVALID_REQUEST", "max_pax must be >= min_pax.")
        if departure_date <= core.clock_date():
            err("ERR_INVALID_REQUEST",
                "departure_date must be strictly after the current logical date.")
        if return_date <= departure_date:
            err("ERR_INVALID_REQUEST", "return_date must be strictly after departure_date.")
        if final_payment_due_date <= deposit_due_date:
            err("ERR_INVALID_REQUEST",
                "final_payment_due_date must be strictly after deposit_due_date.")
        if final_payment_due_date >= departure_date:
            err("ERR_INVALID_REQUEST",
                "final_payment_due_date must be strictly before departure_date.")

        program = db.programs.get(program_id)
        if program is None:
            err("ERR_PROGRAM_NOT_FOUND", "Program %s does not exist." % program_id)

        row = core.base_row()
        row.update({
            "program_id": program_id,
            "departure_date": core.date_str(departure_date),
            "return_date": core.date_str(return_date),
            "min_pax": min_pax,
            "max_pax": max_pax,
            "deposit_due_date": core.date_str(deposit_due_date),
            "final_payment_due_date": core.date_str(final_payment_due_date),
            "mobility_accessible_coach": mobility_accessible_coach,
            "status": "PLANNING",
            "risk_posture": "OPEN",
            "governing_advisory_id": None,
            "paying_pax_count": 0,
            "provisional_tier_code": None,
            "provisional_per_pax_price_cents": 0,
            "provisional_single_supplement_cents": 0,
            "provisional_deposit_cents": 0,
            "final_tier_code": None,
            "final_per_pax_price_cents": 0,
            "land_cost_total_cents": 0,
            "itinerary_cost_delta_cents": 0,
            "service_coverage_ok": True,
            "pending_modification_required": False,
            "pending_modification_reason": None,
            "pending_modification_proposed_by_user_id": None,
            "pending_modification_cost_delta_cents": 0,
            "ratified_modification_count": 0,
            "sweep_run_count": 0,
            "last_sweep_at": None,
        })
        db.departures[row["id"]] = row
        core.refresh_posture(row)

        program["departure_count"] = program["departure_count"] + 1
        core.touch(program)

        return response.ok(core.serialize(row), 201)


@bp.route("/departures/<departure_id>", methods=["GET"])
def get_departure(departure_id):
    authorize(OPERATOR_ROLES)
    with lock:
        row = _load(departure_id)
        return response.ok(core.serialize(row))


@bp.route("/departures", methods=["GET"])
def list_departures():
    authorize(OPERATOR_ROLES)
    with lock:
        limit, offset = pagination()
        rows = core.order_rows(list(db.departures.values()))
        rows = apply_filters(rows, {
            "program_id": "program_id",
            "governing_advisory_id": "governing_advisory_id",
            "status": "status",
            "risk_posture": "risk_posture",
        })
        page, total = core.paginate(rows, limit, offset)
        return response.ok_list([core.serialize(r) for r in page], limit, offset, total)


@bp.route("/departures/<departure_id>/open-sales", methods=["POST"])
def open_sales(departure_id):
    authorize((ROLE_PROGRAM_MANAGER,))
    with lock:
        departure = _load(departure_id)
        core.refresh_posture(departure)
        if departure["status"] not in ("PLANNING", "SALES_CLOSED"):
            err("ERR_DEPARTURE_INVALID_STATE",
                "Sales can only be opened from PLANNING or SALES_CLOSED.")
        live_services = [sb for sb in core.service_bookings_of_departure(departure_id)
                         if sb["status"] != "CANCELLED"]
        if not live_services:
            err("ERR_DEPARTURE_INVALID_STATE",
                "A departure with an empty itinerary cannot open for sale.")
        if departure["risk_posture"] == "SUSPENDED":
            err("ERR_DEPARTURE_SUSPENDED_NO_NEW_BOOKINGS",
                "A suspended departure cannot accept new bookings.")

        departure["status"] = "OPEN_FOR_SALE"
        departure["final_tier_code"] = None
        departure["final_per_pax_price_cents"] = 0
        core.recompute_provisional_tier(departure)
        core.refresh_posture(departure)
        core.touch(departure)
        return response.ok(core.serialize(departure))


@bp.route("/departures/<departure_id>/close-sales", methods=["POST"])
def close_sales(departure_id):
    authorize((ROLE_PROGRAM_MANAGER,))
    with lock:
        departure = _load(departure_id)
        core.refresh_posture(departure)
        if departure["status"] != "OPEN_FOR_SALE":
            err("ERR_DEPARTURE_INVALID_STATE", "Sales can only be closed from OPEN_FOR_SALE.")

        count, tier = core.compute_final_tier(departure)
        if tier is None:
            err("ERR_NO_APPLICABLE_PRICE_TIER",
                "No price tier covers a fully-paid confirmed count of %d." % count)
        if count < departure["min_pax"]:
            err("ERR_MIN_PAX_NOT_MET",
                "Only %d fully-paid confirmed travelers; min_pax is %d."
                % (count, departure["min_pax"]))
        if departure["pending_modification_required"]:
            err("ERR_PENDING_MODIFICATION_UNRATIFIED",
                "An itinerary modification is awaiting ratification.")

        departure["status"] = "SALES_CLOSED"
        departure["final_tier_code"] = tier["tier_code"]
        departure["final_per_pax_price_cents"] = tier["per_pax_price_cents"]

        for pilgrim in core.pilgrims_of_departure(departure_id):
            if pilgrim["booking_status"] != "CONFIRMED":
                continue
            before = core.snap(pilgrim)
            pilgrim["price_locked_cents"] = departure["final_per_pax_price_cents"]
            core.recompute_invoice(pilgrim)
            core.touch_if_changed(pilgrim, before)
            core.requote_quoted_protections(pilgrim)

        core.recompute_land_rollup(departure, touch_departure=False)
        core.recompute_service_coverage(departure, touch_departure=False)
        core.touch(departure)
        return response.ok(core.serialize(departure))


@bp.route("/departures/<departure_id>/cancel", methods=["POST"])
def cancel_departure(departure_id):
    authorize((ROLE_PROGRAM_MANAGER,))
    body = body_of()
    with lock:
        departure = _load(departure_id)
        core.refresh_posture(departure)
        req_str(body, "cancellation_reason", 1, None)
        if departure["status"] not in ("PLANNING", "OPEN_FOR_SALE", "SALES_CLOSED"):
            err("ERR_DEPARTURE_INVALID_STATE",
                "Only a PLANNING, OPEN_FOR_SALE or SALES_CLOSED departure can be cancelled.")

        departure["status"] = "CANCELLED"

        # Hop one and two: travellers, their plans and their protections.
        for pilgrim in core.pilgrims_of_departure(departure_id):
            if pilgrim["booking_status"] == "CANCELLED":
                continue
            core.cancel_pilgrim(pilgrim, force_zero_penalty=True, cascade_departure=False)

        # Hop three: services, land lines, seat blocks and leader agreements.
        for booking in core.service_bookings_of_departure(departure_id):
            if booking["status"] == "CANCELLED":
                continue
            booking["status"] = "CANCELLED"
            booking["cancelled_by_risk"] = False
            core.touch(booking)

        for line in core.land_assignments_of_departure(departure_id):
            if line["status"] not in ("DRAFT", "COUNTERSIGNED"):
                continue
            resource = db.land_resources[line["land_resource_id"]]
            notice_days = core.whole_days(core.as_date(line["date_from"]), core.clock_date())
            line["status"] = "TERMINATED"
            line["terminated_penalty_free"] = \
                notice_days >= resource["force_majeure_notice_days"]
            core.touch(line)

        for block in core.air_blocks_of_departure(departure_id):
            if block["status"] in ("DRAFT", "OFFERED", "COUNTERED"):
                block["status"] = "EXPIRED"
                core.touch(block)
            elif block["status"] == "CONFIRMED":
                block["status"] = "RELEASED"
                core.touch(block)

        for agreement in core.agreements_of_departure(departure_id):
            if agreement["status"] not in ("PENDING_COUNTERSIGN", "ACTIVE"):
                continue
            agreement["status"] = "TERMINATED"
            agreement["recruited_paying_count"] = 0
            agreement["earned_free_seats"] = 0
            agreement["commission_payable_cents"] = 0
            core.touch(agreement)

        core.recompute_paying_pax_count(departure)
        core.recompute_land_rollup(departure, touch_departure=False)
        core.touch(departure)
        return response.ok(core.serialize(departure))


@bp.route("/departures/<departure_id>/payment-sweep", methods=["POST"])
def payment_sweep(departure_id):
    authorize((ROLE_FINANCE_CONTROLLER,))
    with lock:
        departure = _load(departure_id)
        core.refresh_posture(departure)
        if departure["status"] not in ("OPEN_FOR_SALE", "SALES_CLOSED"):
            err("ERR_DEPARTURE_INVALID_STATE",
                "The payment sweep requires OPEN_FOR_SALE or SALES_CLOSED.")

        today = core.clock_date()
        touched_agreements = []
        any_default = False
        for pilgrim in core.pilgrims_of_departure(departure_id):
            if pilgrim["booking_status"] == "CANCELLED":
                continue
            for plan in core.plans_of_pilgrim(pilgrim["id"]):
                if plan["status"] != "ACTIVE":
                    continue
                plan_before = core.snap(plan)
                for installment in plan["installments"]:
                    if installment["status"] in ("SCHEDULED", "PARTIALLY_PAID") and \
                            core.as_date(installment["due_date"]) < today:
                        installment["status"] = "PAST_DUE"
                core.refresh_past_due_count(plan)
                if plan["past_due_count"] >= core.PLAN_DEFAULT_PAST_DUE_COUNT:
                    plan["status"] = "DEFAULTED"
                    pilgrim_before = core.snap(pilgrim)
                    pilgrim["payment_status"] = "IN_DEFAULT"
                    pilgrim["ticketed_name"] = None
                    if pilgrim["booking_status"] == "CONFIRMED":
                        pilgrim["booking_status"] = "DEPOSITED"
                    core.touch_if_changed(pilgrim, pilgrim_before)
                    any_default = True
                    if pilgrim["recruited_by_agreement_id"]:
                        touched_agreements.append(pilgrim["recruited_by_agreement_id"])
                core.touch_if_changed(plan, plan_before)

        if any_default:
            core.recompute_provisional_tier(departure)
            for agreement_id in dict.fromkeys(touched_agreements):
                agreement = db.agreements.get(agreement_id)
                if agreement is None:
                    continue
                before = core.snap(agreement)
                core.recompute_accrual_snapshot(agreement)
                core.touch_if_changed(agreement, before)

        departure["sweep_run_count"] = departure["sweep_run_count"] + 1
        departure["last_sweep_at"] = response.iso_ms(core.clock_now())
        if today >= core.as_date(departure["departure_date"]) and \
                departure["status"] == "SALES_CLOSED":
            departure["status"] = "OPERATED"
        core.touch(departure)
        return response.ok(core.serialize(departure))


@bp.route("/departures/<departure_id>/itinerary-modification", methods=["POST"])
def propose_modification(departure_id):
    caller = authorize((ROLE_PROGRAM_MANAGER, ROLE_RISK_OFFICER))
    body = body_of()
    with lock:
        departure = _load(departure_id)
        core.refresh_posture(departure)
        modification_reason = req_str(body, "modification_reason", 1, None)
        cost_delta_cents = req_int(body, "cost_delta_cents")
        if departure["status"] not in ("PLANNING", "OPEN_FOR_SALE", "SALES_CLOSED"):
            err("ERR_DEPARTURE_INVALID_STATE",
                "An itinerary modification requires PLANNING, OPEN_FOR_SALE or SALES_CLOSED.")
        if departure["pending_modification_required"]:
            err("ERR_DEPARTURE_INVALID_STATE",
                "A modification is already awaiting ratification.")

        departure["pending_modification_required"] = True
        departure["pending_modification_reason"] = modification_reason
        departure["pending_modification_proposed_by_user_id"] = caller.user_id
        departure["pending_modification_cost_delta_cents"] = cost_delta_cents
        core.touch(departure)
        return response.ok(core.serialize(departure))


@bp.route("/departures/<departure_id>/ratify-modification", methods=["POST"])
def ratify_modification(departure_id):
    caller = authorize((ROLE_PROGRAM_MANAGER, ROLE_RISK_OFFICER))
    with lock:
        departure = _load(departure_id)
        proposer = departure["pending_modification_proposed_by_user_id"]
        if proposer is not None and proposer == caller.user_id:
            err("ERR_SEGREGATION_OF_DUTIES",
                "The proposer of an itinerary modification may not ratify it.")
        core.refresh_posture(departure)
        if departure["status"] not in ("PLANNING", "OPEN_FOR_SALE", "SALES_CLOSED"):
            err("ERR_DEPARTURE_INVALID_STATE",
                "Ratification requires PLANNING, OPEN_FOR_SALE or SALES_CLOSED.")
        if not departure["pending_modification_required"]:
            err("ERR_NO_PENDING_MODIFICATION", "No itinerary modification is pending.")

        departure["itinerary_cost_delta_cents"] = (
            departure["itinerary_cost_delta_cents"]
            + departure["pending_modification_cost_delta_cents"])
        departure["ratified_modification_count"] = departure["ratified_modification_count"] + 1
        departure["pending_modification_required"] = False
        departure["pending_modification_reason"] = None
        departure["pending_modification_proposed_by_user_id"] = None
        departure["pending_modification_cost_delta_cents"] = 0
        core.recompute_land_rollup(departure, touch_departure=False)
        core.touch(departure)
        return response.ok(core.serialize(departure))
