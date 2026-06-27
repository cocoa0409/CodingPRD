"""ComplicationCase routes: open / open-touchup / touchup-failed / resolve
(PRD §3.7)."""
from flask import Blueprint, request

from db import db, new_id, now_iso
from errors import ApiError
from middleware import require_roles
from helpers import get_json_body, require_string, require_enum, paginate
from response import success_object, success_array
import domain

bp = Blueprint("complications", __name__)

SEVERITIES = {"MINOR", "MODERATE", "SEVERE"}
RESOLUTION_MODES = {"REFUND", "CLINICAL"}


def _base_common():
    ts = now_iso()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }


# --------------------------------------------------------------------------
# Open a complication on a committed session.
# --------------------------------------------------------------------------
@bp.route("/aesthetics/complication-cases", methods=["POST"])
@require_roles("Provider")
def open_complication():
    body = get_json_body()
    treatment_session_id = require_string(body, "treatment_session_id")
    severity = require_enum(body, "severity", SEVERITIES)

    session = db.treatment_sessions.get(treatment_session_id)
    if session is None:
        raise ApiError("ERR_SESSION_NOT_FOUND", "Treatment session not found")
    if session["status"] != "COMMITTED":
        raise ApiError("ERR_SESSION_NOT_COMMITTED", "Session not COMMITTED")

    case = _base_common()
    case.update({
        "treatment_session_id": treatment_session_id,
        "injector_provider_id": session["injector_provider_id"],
        "severity": severity,
        "touchup_rounds": 0,
        "refund_cents": 0,
        "status": "OPEN",
    })
    db.complication_cases[case["id"]] = case

    # Session -> COMPLICATION_OPEN.
    session["status"] = "COMPLICATION_OPEN"
    domain.touch(session)

    # Provider open_complication_count recompute.
    injector = db.providers.get(session["injector_provider_id"])
    if injector is not None:
        domain.recompute_provider_counts(injector)
        domain.touch(injector)

    return success_object(domain.serialize(case, "ComplicationCase"), 201)


@bp.route("/aesthetics/complication-cases", methods=["GET"])
@require_roles("ClinicAdmin", "Provider")
def list_complications():
    f = request.args
    records = list(db.complication_cases.values())
    for key in ("treatment_session_id", "injector_provider_id", "status"):
        val = f.get(key)
        if val is not None:
            records = [r for r in records if r[key] == val]
    page, limit, offset, total = paginate(records)
    return success_array([domain.serialize(r, "ComplicationCase") for r in page],
                         limit, offset, total)


@bp.route("/aesthetics/complication-cases/<cid>", methods=["GET"])
@require_roles("ClinicAdmin", "Provider")
def get_complication(cid):
    case = db.complication_cases.get(cid)
    if case is None:
        raise ApiError("ERR_CASE_NOT_FOUND", "Complication case not found")
    return success_object(domain.serialize(case, "ComplicationCase"))


@bp.route("/aesthetics/complication-cases/<cid>/open-touchup", methods=["POST"])
@require_roles("Provider")
def open_touchup(cid):
    case = db.complication_cases.get(cid)
    if case is None:
        raise ApiError("ERR_CASE_NOT_FOUND", "Complication case not found")
    if case["status"] != "OPEN":
        raise ApiError("ERR_CASE_NOT_OPEN", "Case not OPEN")
    if case["severity"] not in ("MINOR", "MODERATE"):
        raise ApiError("ERR_SEVERE_NO_TOUCHUP", "SEVERE complication is refund-only")
    if case["touchup_rounds"] >= domain.MAX_TOUCHUP_ROUNDS:
        raise ApiError("ERR_TOUCHUP_LIMIT_REACHED", "Touch-up round limit reached")
    session = db.treatment_sessions.get(case["treatment_session_id"])
    order = db.standing_orders.get(session["standing_order_id"]) if session else None
    if order is None or not domain.standing_order_active(order):
        raise ApiError("ERR_STANDING_ORDER_INACTIVE", "Standing order inactive")

    case["touchup_rounds"] += 1
    case["status"] = "IN_TOUCHUP"
    domain.touch(case)
    return success_object(domain.serialize(case, "ComplicationCase"))


@bp.route("/aesthetics/complication-cases/<cid>/touchup-failed", methods=["POST"])
@require_roles("Provider")
def touchup_failed(cid):
    case = db.complication_cases.get(cid)
    if case is None:
        raise ApiError("ERR_CASE_NOT_FOUND", "Complication case not found")
    if case["status"] != "IN_TOUCHUP":
        raise ApiError("ERR_CASE_NOT_IN_TOUCHUP", "Case not IN_TOUCHUP")
    case["status"] = "OPEN"
    domain.touch(case)
    return success_object(domain.serialize(case, "ComplicationCase"))


@bp.route("/aesthetics/complication-cases/<cid>/resolve", methods=["POST"])
@require_roles("Provider")
def resolve_complication(cid):
    case = db.complication_cases.get(cid)
    if case is None:
        raise ApiError("ERR_CASE_NOT_FOUND", "Complication case not found")
    body = get_json_body()
    resolution_mode = require_enum(body, "resolution_mode", RESOLUTION_MODES)

    # Both OPEN and IN_TOUCHUP can resolve; both invalid-source map to
    # ERR_CASE_NOT_OPEN per scaffold.
    if case["status"] not in ("OPEN", "IN_TOUCHUP"):
        raise ApiError("ERR_CASE_NOT_OPEN", "Case not in a resolvable state")

    session = db.treatment_sessions.get(case["treatment_session_id"])

    if resolution_mode == "REFUND":
        case["refund_cents"] = session["final_charge_cents"]
        # Reverse loyalty.
        plan = db.treatment_plans.get(session["treatment_plan_id"])
        account = domain.loyalty_account_for_patient(plan["patient_id"]) if plan else None
        if account is not None:
            account["points_earned"] -= session["points_earned_cents_basis"]
            account["points_redeemed"] -= session["loyalty_points_redeemed"]
            domain.recompute_loyalty_balance(account)
            domain.touch(account)
        # Subtract from plan finalized ledger.
        if plan is not None:
            plan["finalized_series_cost_cents"] -= session["final_charge_cents"]
            domain.touch(plan)
    # CLINICAL: refund_cents stays 0, no ledger change.

    case["status"] = "RESOLVED"
    domain.touch(case)

    # Recompute provider counts.
    injector = db.providers.get(case["injector_provider_id"])
    if injector is not None:
        domain.recompute_provider_counts(injector)
        domain.touch(injector)

    return success_object(domain.serialize(case, "ComplicationCase"))
