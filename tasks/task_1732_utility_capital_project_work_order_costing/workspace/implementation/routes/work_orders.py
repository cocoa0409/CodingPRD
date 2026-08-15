"""WorkOrder endpoints (PRD 3.3, 3.7, 3.8): origination, the authorization
pipeline, execution transitions, cancellation cascades, and closeout with the
unitization waterfall."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error, ERR_VALIDATION, ERR_NOT_FOUND, ERR_INVALID_STATE, ERR_PROGRAM_CLOSED,
    ERR_APPROVAL_TIER_REQUIRED, ERR_SEGREGATION_OF_DUTIES, ERR_NO_APPROVED_ESTIMATE,
    ERR_PROGRAM_BUDGET_EXCEEDED, ERR_IN_SERVICE_PERIOD_NOT_OPEN,
    ERR_WRITEOFF_DISPOSITION_REQUIRED, ERR_CIAC_PLEDGED_OUTSTANDING,
    ERR_UNITIZATION_EMPTY, ERR_UNITIZATION_ZERO_TARGET,
    ERR_CLOSEOUT_VARIANCE_EXCEEDS_TOLERANCE, ERR_REGULATORY_COVERAGE_INSUFFICIENT,
)
from middleware import authorized
from response import success_object
from services.core import (
    new_record, touch, serialize_work_order, serialize_estimate,
    wo_approved_estimate_cents, wo_cwip_cents, wo_actual_direct_cents,
    wo_ciac_agreements, current_open_period, program_available_cents,
    AUTHORIZE_CONTROLLER_THRESHOLD_CENTS, CLOSEOUT_TOLERANCE_PCT, CIAC_FORFEIT_PCT,
)
from util import parse_date, rhu_div
from validate import (
    get_body, req_str, req_int, req_enum, opt_enum, opt_int, req_date,
    require_path_resource, require_body_ref,
)
from routes.helpers import list_response, get_one

bp = Blueprint("work_orders", __name__)


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

@bp.route("/ucp/work-orders", methods=["POST"])
def create_work_order():
    caller = authorized(["ProjectEngineer"])
    body = get_body()
    # Priority 3 — body FK existence before the remaining shape checks.
    program = require_body_ref(body, "program_id", "capital_programs")
    # Priority 4 — shape.
    order_type = req_enum(body, "order_type", ["CAPITAL", "EXPENSE"])
    title = req_str(body, "title")
    initial_estimated_cost_cents = req_int(body, "initial_estimated_cost_cents", positive=True)
    # Priority 7 — program must be OPEN.
    if program["status"] != "OPEN":
        raise_error(ERR_PROGRAM_CLOSED, "program is CLOSED")

    rec = new_record()
    rec.update({
        "program_id": program["id"],
        "order_type": order_type,
        "title": title,
        "status": "DRAFT",
        "in_service_date": None,
        "in_service_period_id": None,
        "gross_cwip_cents": None,
        "ciac_applied_cents": 0,
        "capitalizable_total_cents": None,
        "cancel_writeoff_disposition": None,
        "created_by_user_id": caller.user_id,
        "authorized_by_user_id": None,
        "completed_by_user_id": None,
        "closed_by_user_id": None,
    })
    db["work_orders"][rec["id"]] = rec

    # Creation seeds estimate #1 (PROPOSED) from initial_estimated_cost_cents.
    est = new_record()
    est.update({
        "work_order_id": rec["id"],
        "estimate_seq": 1,
        "estimated_cost_cents": initial_estimated_cost_cents,
        "notes": None,
        "status": "PROPOSED",
        "supersedes_estimate_id": None,
        "submitted_by_user_id": caller.user_id,
        "decided_by_user_id": None,
        "routing_tier": None,
    })
    db["estimates"][est["id"]] = est
    return success_object(serialize_work_order(rec), status=201)


@bp.route("/ucp/work-orders/<work_order_id>", methods=["GET"])
def get_work_order(work_order_id):
    return get_one("work_orders", serialize_work_order, work_order_id)


@bp.route("/ucp/work-orders", methods=["GET"])
def list_work_orders():
    filters = {
        "program_id": request.args.get("program_id"),
        "status": request.args.get("status"),
        "order_type": request.args.get("order_type"),
    }
    return list_response("work_orders", serialize_work_order, filters)


# ---------------------------------------------------------------------------
# Transitions
# ---------------------------------------------------------------------------

def _transition(work_order_id, roles, from_states, mutate):
    authorized(roles)
    wo = require_path_resource("work_orders", work_order_id)
    if wo["status"] not in from_states:
        raise_error(ERR_INVALID_STATE, f"work order is {wo['status']}")
    mutate(wo)
    touch(wo)
    return success_object(serialize_work_order(wo))


@bp.route("/ucp/work-orders/<work_order_id>/submit", methods=["POST"])
def submit_work_order(work_order_id):
    # DRAFT -> SUBMITTED and the RETURNED -> SUBMITTED resubmission loop.
    return _transition(work_order_id, ["ProjectEngineer"], ("DRAFT", "RETURNED"),
                       lambda wo: wo.update({"status": "SUBMITTED"}))


@bp.route("/ucp/work-orders/<work_order_id>/return", methods=["POST"])
def return_work_order(work_order_id):
    authorized(["WorkOrderSupervisor"])
    wo = require_path_resource("work_orders", work_order_id)
    body = get_body()
    req_str(body, "reason")
    if wo["status"] != "SUBMITTED":
        raise_error(ERR_INVALID_STATE, f"work order is {wo['status']}")
    wo["status"] = "RETURNED"
    touch(wo)
    return success_object(serialize_work_order(wo))


@bp.route("/ucp/work-orders/<work_order_id>/authorize", methods=["POST"])
def authorize_work_order(work_order_id):
    caller = authorized(["WorkOrderSupervisor", "Controller"])
    wo = require_path_resource("work_orders", work_order_id)
    program = db["capital_programs"][wo["program_id"]]
    approved = wo_approved_estimate_cents(wo["id"])
    # Priority 5 — authorization tier: strictly below 10,000,000c a Supervisor
    # may authorize; at or above, Controller only (boundary belongs to Controller).
    if (
        approved is not None
        and approved >= AUTHORIZE_CONTROLLER_THRESHOLD_CENTS
        and caller.role != "Controller"
    ):
        raise_error(ERR_APPROVAL_TIER_REQUIRED, "amount requires Controller authorization")
    # Priority 7 — from-state.
    if wo["status"] != "SUBMITTED":
        raise_error(ERR_INVALID_STATE, f"work order is {wo['status']}")
    # Priority 8 — segregation of duties vs the creator.
    if caller.user_id == wo["created_by_user_id"]:
        raise_error(ERR_SEGREGATION_OF_DUTIES, "authorizer must differ from creator")
    # Priority 10 — an APPROVED estimate must exist.
    if approved is None:
        raise_error(ERR_NO_APPROVED_ESTIMATE, "no APPROVED estimate exists")
    # Priority 11 — budget.
    if program_available_cents(program) < approved:
        raise_error(ERR_PROGRAM_BUDGET_EXCEEDED, "program available amount is below the approved estimate")

    wo["status"] = "AUTHORIZED"
    wo["authorized_by_user_id"] = caller.user_id
    touch(wo)
    touch(program)  # committed_amount_cents increased by the approved estimate
    return success_object(serialize_work_order(wo))


@bp.route("/ucp/work-orders/<work_order_id>/start", methods=["POST"])
def start_work_order(work_order_id):
    return _transition(work_order_id, ["WorkOrderSupervisor"], ("AUTHORIZED",),
                       lambda wo: wo.update({"status": "IN_PROGRESS"}))


@bp.route("/ucp/work-orders/<work_order_id>/suspend", methods=["POST"])
def suspend_work_order(work_order_id):
    return _transition(work_order_id, ["WorkOrderSupervisor"], ("IN_PROGRESS",),
                       lambda wo: wo.update({"status": "SUSPENDED"}))


@bp.route("/ucp/work-orders/<work_order_id>/resume", methods=["POST"])
def resume_work_order(work_order_id):
    return _transition(work_order_id, ["WorkOrderSupervisor"], ("SUSPENDED",),
                       lambda wo: wo.update({"status": "IN_PROGRESS"}))


@bp.route("/ucp/work-orders/<work_order_id>/complete", methods=["POST"])
def complete_work_order(work_order_id):
    caller = authorized(["WorkOrderSupervisor"])
    wo = require_path_resource("work_orders", work_order_id)
    body = get_body()
    in_service_date = req_date(body, "in_service_date")
    if wo["status"] != "IN_PROGRESS":
        raise_error(ERR_INVALID_STATE, f"work order is {wo['status']}")
    # Priority 9 — the date must fall inside the single OPEN/REOPENED period.
    d = parse_date(in_service_date)
    period = current_open_period()
    if period is None or not (period["_start"] <= d <= period["_end"]):
        raise_error(ERR_IN_SERVICE_PERIOD_NOT_OPEN, "in_service_date is not inside the current OPEN or REOPENED period")
    wo["status"] = "COMPLETED"
    wo["in_service_date"] = in_service_date
    wo["in_service_period_id"] = period["id"]
    wo["completed_by_user_id"] = caller.user_id
    touch(wo)
    return success_object(serialize_work_order(wo))


# ---------------------------------------------------------------------------
# Cancellation
# ---------------------------------------------------------------------------

@bp.route("/ucp/work-orders/<work_order_id>/cancel", methods=["POST"])
def cancel_work_order(work_order_id):
    caller = authorized(["WorkOrderSupervisor"])
    wo = require_path_resource("work_orders", work_order_id)
    body = get_body()
    # Priority 4 — shape of the optional write-off fields.
    disposition = opt_enum(body, "writeoff_disposition", ["EXPENSE", "REGULATORY_DEFERRAL"])
    months = opt_int(body, "writeoff_amortization_months", minimum=1)
    # Priority 7 — legal from-states.
    from_state = wo["status"]
    if from_state not in ("DRAFT", "SUBMITTED", "RETURNED", "AUTHORIZED", "IN_PROGRESS", "SUSPENDED"):
        raise_error(ERR_INVALID_STATE, f"work order is {from_state}")
    # Priority 11 — write-off disposition requirement.
    cwip = wo_cwip_cents(wo["id"])
    if cwip > 0:
        if disposition is None:
            raise_error(ERR_WRITEOFF_DISPOSITION_REQUIRED, "writeoff_disposition is required when cwip_cents > 0")
        if disposition == "REGULATORY_DEFERRAL" and months is None:
            raise_error(ERR_WRITEOFF_DISPOSITION_REQUIRED, "writeoff_amortization_months is required for REGULATORY_DEFERRAL")

    program = db["capital_programs"][wo["program_id"]]
    program_touched = False

    if from_state in ("AUTHORIZED", "IN_PROGRESS", "SUSPENDED"):
        # Budget release is automatic via the derived committed balance.
        if cwip > 0:
            wo["cancel_writeoff_disposition"] = disposition
            if disposition == "EXPENSE":
                program["expense_writeoff_cents"] += cwip
            else:  # REGULATORY_DEFERRAL
                ra = new_record()
                ra.update({
                    "description": f"Cancelled work order write-off: {wo['title']}",
                    "source_work_order_id": wo["id"],
                    "original_cents": cwip,
                    "amortization_months": months,
                    "status": "PROPOSED",
                    "proposed_by_user_id": caller.user_id,
                    "approved_by_user_id": None,
                })
                db["regulatory_assets"][ra["id"]] = ra
        program_touched = True
        # CIAC settlement: RECEIVED -> REFUNDED (0% forfeiture from AUTHORIZED —
        # never reached IN_PROGRESS; 10% from IN_PROGRESS/SUSPENDED);
        # PLEDGED -> CANCELLED.
        forfeiture_pct = 0 if from_state == "AUTHORIZED" else CIAC_FORFEIT_PCT
        for a in wo_ciac_agreements(wo["id"]):
            if a["status"] == "RECEIVED":
                forfeited = rhu_div(a["received_cents"] * forfeiture_pct, 100)
                a["forfeited_cents"] = forfeited
                a["refunded_cents"] = a["received_cents"] - forfeited
                a["status"] = "REFUNDED"
                touch(a)
            elif a["status"] == "PLEDGED":
                a["status"] = "CANCELLED"
                touch(a)
    elif from_state in ("SUBMITTED", "RETURNED"):
        for e in db["estimates"].values():
            if e["work_order_id"] == wo["id"] and e["status"] == "PROPOSED":
                e["status"] = "WITHDRAWN"
                touch(e)
        for a in wo_ciac_agreements(wo["id"]):
            if a["status"] == "PLEDGED":
                a["status"] = "CANCELLED"
                touch(a)
    else:  # DRAFT
        for a in wo_ciac_agreements(wo["id"]):
            if a["status"] == "PLEDGED":
                a["status"] = "CANCELLED"
                touch(a)

    wo["status"] = "CANCELLED"
    touch(wo)
    if program_touched:
        touch(program)
    return success_object(serialize_work_order(wo))


# ---------------------------------------------------------------------------
# Closeout — variance gate, CIAC application, unitization waterfall, rollup
# ---------------------------------------------------------------------------

def _waterfall_allocations(total, targets, std_costs, classes):
    """Pinned rounding order: per-line round-half-up first, then the remainder
    (possibly negative) lands on the line with the greatest target; ties break
    toward the greatest standard_cost_cents, then asset_class lexicographically
    ascending."""
    s = sum(targets)
    allocations = [rhu_div(total * t, s) for t in targets]
    remainder = total - sum(allocations)
    if remainder != 0:
        best = 0
        for i in range(1, len(targets)):
            if (
                targets[i] > targets[best]
                or (targets[i] == targets[best] and std_costs[i] > std_costs[best])
                or (
                    targets[i] == targets[best]
                    and std_costs[i] == std_costs[best]
                    and classes[i] < classes[best]
                )
            ):
                best = i
        allocations[best] += remainder
    return allocations


@bp.route("/ucp/work-orders/<work_order_id>/closeout", methods=["POST"])
def closeout_work_order(work_order_id):
    caller = authorized(["Controller"])
    wo = require_path_resource("work_orders", work_order_id)
    body = get_body()

    # Priority 3 — body FK existence (each unit_catalog_id, left to right).
    raw_lines = body.get("unitization_lines")
    if isinstance(raw_lines, list):
        for ln in raw_lines:
            if isinstance(ln, dict):
                ucid = ln.get("unit_catalog_id")
                if isinstance(ucid, str) and ucid not in db["unit_catalog"]:
                    raise_error(ERR_NOT_FOUND, f"unit_catalog_id does not resolve: {ucid}")

    # Priority 4 — line shape.
    if raw_lines is None:
        lines = []
    elif not isinstance(raw_lines, list):
        raise_error(ERR_VALIDATION, "unitization_lines must be an array")
    else:
        lines = raw_lines
        for ln in lines:
            if not isinstance(ln, dict):
                raise_error(ERR_VALIDATION, "unitization line must be an object")
            ucid = ln.get("unit_catalog_id")
            if not isinstance(ucid, str) or ucid.strip() == "":
                raise_error(ERR_VALIDATION, "unitization line requires unit_catalog_id")
            qty = ln.get("quantity")
            if qty is None or isinstance(qty, bool) or not isinstance(qty, int) or qty < 1:
                raise_error(ERR_VALIDATION, "unitization line quantity must be >= 1")

    # Priority 7 — from-state.
    if wo["status"] != "COMPLETED":
        raise_error(ERR_INVALID_STATE, f"work order is {wo['status']}")
    # Priority 8 — segregation of duties vs the completer.
    if caller.user_id == wo["completed_by_user_id"]:
        raise_error(ERR_SEGREGATION_OF_DUTIES, "closer must differ from completer")

    # Priority 10 — referential checks, in PRD 3.8 order.
    agreements = wo_ciac_agreements(wo["id"])
    if any(a["status"] == "PLEDGED" for a in agreements):
        raise_error(ERR_CIAC_PLEDGED_OUTSTANDING, "a CIAC agreement is still PLEDGED")
    if wo["order_type"] == "CAPITAL" and len(lines) == 0:
        raise_error(ERR_UNITIZATION_EMPTY, "CAPITAL closeout requires unitization lines")
    if wo["order_type"] == "EXPENSE" and len(lines) > 0:
        raise_error(ERR_UNITIZATION_EMPTY, "EXPENSE closeout requires empty unitization lines")
    targets, std_costs, classes = [], [], []
    for ln in lines:
        cat = db["unit_catalog"][ln["unit_catalog_id"]]
        targets.append(ln["quantity"] * cat["standard_cost_cents"])
        std_costs.append(cat["standard_cost_cents"])
        classes.append(cat["asset_class"])
    if lines and sum(targets) <= 0:
        raise_error(ERR_UNITIZATION_ZERO_TARGET, "unitization lines weight to zero")

    # Priority 11 — the closeout variance gate, evaluated last.
    approved = wo_approved_estimate_cents(wo["id"])
    actual = wo_actual_direct_cents(wo["id"])
    overrun = actual - approved
    if overrun * 100 > approved * CLOSEOUT_TOLERANCE_PCT:
        tolerance = (approved * CLOSEOUT_TOLERANCE_PCT) // 100  # integer floor
        coverage_needed = overrun - tolerance
        coverage = sum(
            ra["original_cents"]
            for ra in db["regulatory_assets"].values()
            if ra["source_work_order_id"] == wo["id"]
            and ra["status"] in ("APPROVED", "AMORTIZING", "FULLY_AMORTIZED")
        )
        if coverage == 0:
            raise_error(ERR_CLOSEOUT_VARIANCE_EXCEEDS_TOLERANCE, "overrun beyond 15% with no regulatory coverage")
        if coverage < coverage_needed:
            raise_error(ERR_REGULATORY_COVERAGE_INSUFFICIENT, "regulatory coverage below the needed amount")

    # --- side effects, atomic ---
    program = db["capital_programs"][wo["program_id"]]
    gross = wo_cwip_cents(wo["id"])
    wo["gross_cwip_cents"] = gross

    # CIAC application: total applied = min(total received, gross); each
    # RECEIVED agreement applies against the remaining gross CWIP share in
    # creation order; the excess is refunded with no forfeiture.
    received = [a for a in agreements if a["status"] == "RECEIVED"]
    total_received = sum(a["received_cents"] for a in received)
    wo["ciac_applied_cents"] = min(total_received, gross)
    remaining_gross = gross
    for a in received:
        applied = min(a["received_cents"], max(0, remaining_gross))
        a["applied_cents"] = applied
        a["refunded_cents"] = a["received_cents"] - applied
        a["status"] = "APPLIED"
        touch(a)
        remaining_gross -= applied

    if program["ciac_method"] == "NET_OF_CIAC":
        wo["capitalizable_total_cents"] = gross - wo["ciac_applied_cents"]
    else:  # GROSS_WITH_CONTRA
        wo["capitalizable_total_cents"] = gross

    # Unitization waterfall — one FixedAssetUnit per line.
    if lines:
        allocations = _waterfall_allocations(wo["capitalizable_total_cents"], targets, std_costs, classes)
        for i, ln in enumerate(lines):
            unit = new_record()
            unit.update({
                "work_order_id": wo["id"],
                "unit_catalog_id": ln["unit_catalog_id"],
                "quantity": ln["quantity"],
                "line_no": i,
                "allocated_cost_cents": allocations[i],
                "in_service_period_id": wo["in_service_period_id"],
                "retirement_period_id": None,
                "retirement_nbv_cents": None,
                "status": "IN_SERVICE",
            })
            db["fixed_asset_units"][unit["id"]] = unit

    wo["status"] = "CLOSED"
    wo["closed_by_user_id"] = caller.user_id
    touch(wo)
    touch(program)  # committed released, capitalized/contra accumulated
    return success_object(serialize_work_order(wo))
