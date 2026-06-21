"""DefermentRequest lifecycle with ordered preconditions (PRD §3.10)."""
from datetime import timedelta

from flask import Blueprint

import errors
from db import db, stamp_create, touch
from middleware import require_role
from response import success
from services import serialize
from services.common import get_json_body, lookup, require_fields, as_enum
from services.derive import latest_income_report, recompute_isa_ledger
from services.timeutil import parse_dt

bp = Blueprint("deferments", __name__)

REASONS = {"UNEMPLOYMENT", "INCOME_FLOOR"}


@bp.post("/deferment-requests")
def create_deferment():
    require_role("ServicingOfficer", "Student")
    body = get_json_body()
    require_fields(body, ["isa_contract_id", "reason", "period_start", "period_end"])
    contract_id = body["isa_contract_id"]
    if not isinstance(contract_id, str):
        raise errors.invalid_request("isa_contract_id must be a string")
    lookup(db.isa_contracts, contract_id)  # existence first
    reason = as_enum(body, "reason", REASONS)
    p_start = parse_dt(body["period_start"], "period_start")
    p_end = parse_dt(body["period_end"], "period_end")

    d = {
        "isa_contract_id": contract_id,
        "reason": reason,
        "period_start": body["period_start"],
        "period_end": body["period_end"],
        "_period_start_dt": p_start,
        "_period_end_dt": p_end,
        "status": "REQUESTED",
    }
    stamp_create(d)
    db.deferment_requests[d["id"]] = d
    return success(serialize.deferment_view(d), status=201)


@bp.get("/deferment-requests/<did>")
def get_deferment(did):
    require_role("ServicingOfficer", "ComplianceOfficer", "Student")
    d = lookup(db.deferment_requests, did)
    return success(serialize.deferment_view(d))


def _closed_overlap_with_buffer(a_start, a_end, b_start, b_end):
    """Closed intervals with a 1-day buffer on each side reserved around b."""
    buf = timedelta(days=1)
    return a_start <= (b_end + buf) and (b_start - buf) <= a_end


@bp.post("/deferment-requests/<did>/approve")
def approve_deferment(did):
    require_role("ServicingOfficer")
    d = lookup(db.deferment_requests, did)
    if d["status"] != "REQUESTED":
        raise errors.invalid_state(f"Deferment is {d['status']}, expected REQUESTED")
    contract = db.isa_contracts.get(d["isa_contract_id"])
    # precondition order (PRD §3.10): contract ACTIVE -> eligibility -> overlap
    if contract is None or contract["status"] != "ACTIVE":
        raise errors.invalid_state("Linked ISA contract is not ACTIVE")

    latest = latest_income_report(contract["id"])
    if d["reason"] == "UNEMPLOYMENT":
        if latest is None or latest["employment_status"] != "UNEMPLOYED":
            raise errors.ApiError(errors.ERR_DEFERMENT_INELIGIBLE, 409,
                                  "Latest income report is not UNEMPLOYED")
    else:  # INCOME_FLOOR
        if latest is None or latest["gross_income_cents"] > contract["income_threshold_cents"]:
            raise errors.ApiError(errors.ERR_DEFERMENT_INELIGIBLE, 409,
                                  "Latest income above the threshold")

    # overlap vs prior APPROVED-or-ENDED deferments for the same contract
    for other in db.deferment_requests.values():
        if other["id"] == d["id"]:
            continue
        if other["isa_contract_id"] != contract["id"]:
            continue
        if other["status"] not in ("APPROVED", "ENDED"):
            continue
        if _closed_overlap_with_buffer(
            d["_period_start_dt"], d["_period_end_dt"],
            other["_period_start_dt"], other["_period_end_dt"],
        ):
            raise errors.ApiError(errors.ERR_DEFERMENT_OVERLAP, 409,
                                  "Deferment window overlaps a prior deferment")

    d["status"] = "APPROVED"
    touch(d)
    contract["status"] = "DEFERRED"
    recompute_isa_ledger(contract)
    touch(contract)
    return success(serialize.deferment_view(d))


@bp.post("/deferment-requests/<did>/deny")
def deny_deferment(did):
    require_role("ServicingOfficer")
    d = lookup(db.deferment_requests, did)
    if d["status"] != "REQUESTED":
        raise errors.invalid_state(f"Deferment is {d['status']}, expected REQUESTED")
    d["status"] = "DENIED"
    touch(d)
    return success(serialize.deferment_view(d))


@bp.post("/deferment-requests/<did>/end")
def end_deferment(did):
    require_role("ServicingOfficer")
    d = lookup(db.deferment_requests, did)
    if d["status"] != "APPROVED":
        raise errors.invalid_state(f"Deferment is {d['status']}, expected APPROVED")
    contract = db.isa_contracts.get(d["isa_contract_id"])
    if contract is None or contract["status"] != "DEFERRED":
        raise errors.invalid_state("Linked ISA contract is not DEFERRED")
    d["status"] = "ENDED"
    touch(d)
    contract["status"] = "ACTIVE"
    recompute_isa_ledger(contract)
    touch(contract)
    return success(serialize.deferment_view(d))
