"""Fee waivers."""
from flask import Blueprint, request

import db
import errors
from middleware import get_actor, require_role
from response import success
from services import domain, validate, calc

bp = Blueprint("fee_waivers", __name__)


@bp.post("/fee-waivers")
def create_waiver():
    _, role = get_actor()
    require_role(role, {"Attorney"})
    data = validate.body(request)
    case_id = validate.require_str(data, "case_id")
    filing_id = validate.require_str(data, "filing_id")
    requesting_party_id = validate.require_str(data, "requesting_party_id")

    # Existence (priority 3) before remaining body validation (priority 4).
    case = domain.get_or_404(db.cases, case_id)
    filing = domain.get_or_404(db.filings, filing_id)
    party = domain.get_or_404(db.parties, requesting_party_id)

    monthly_income_cents = validate.non_negative_int(data, "monthly_income_cents", required=True)
    household_size = validate.positive_int(data, "household_size", required=True)

    if filing["case_id"] != case_id or party["case_id"] != case_id:
        raise errors.err(errors.ERR_CROSS_CASE_REFERENCE, "FK belongs to a different case")

    rec = db.base_record()
    rec.update({
        "case_id": case_id,
        "filing_id": filing_id,
        "requesting_party_id": requesting_party_id,
        "monthly_income_cents": monthly_income_cents,
        "household_size": household_size,
        "status": "PENDING",
        "eligibility_ratio": calc.fee_waiver_eligibility(monthly_income_cents, household_size),
        "decided_at": None,
    })
    db.fee_waivers[rec["id"]] = rec
    return success(domain._clean(rec), status=201)


@bp.get("/fee-waivers/<waiver_id>")
def get_waiver(waiver_id):
    get_actor()
    rec = domain.get_or_404(db.fee_waivers, waiver_id)
    return success(domain._clean(rec), status=200)


@bp.get("/fee-waivers")
def list_waivers():
    get_actor()
    args = request.args
    items = list(db.fee_waivers.values())
    for field in ("case_id", "filing_id", "requesting_party_id", "status"):
        val = args.get(field)
        if val is not None:
            items = [w for w in items if w.get(field) == val]
    window, pagination = domain.paginate(items, args)
    return success([domain._clean(w) for w in window], status=200, pagination=pagination)


@bp.post("/fee-waivers/<waiver_id>/request-info")
def request_info(waiver_id):
    _, role = get_actor()
    require_role(role, {"Clerk"})
    w = domain.get_or_404(db.fee_waivers, waiver_id)
    if w["status"] != "PENDING":
        raise errors.err(errors.ERR_INVALID_STATE, "Waiver is not PENDING")
    w["status"] = "NEEDS_INFO"
    db.touch(w)
    return success(domain._clean(w), status=200)


@bp.post("/fee-waivers/<waiver_id>/resubmit")
def resubmit(waiver_id):
    user_id, role = get_actor()
    require_role(role, {"Attorney"})
    data = validate.body(request)
    w = domain.get_or_404(db.fee_waivers, waiver_id)
    if w["status"] != "NEEDS_INFO":
        raise errors.err(errors.ERR_INVALID_STATE, "Waiver is not NEEDS_INFO")
    party = db.parties[w["requesting_party_id"]]
    if party["attorney_user_id"] != user_id:
        raise errors.err(errors.ERR_NOT_REQUESTING_PARTY, "Not the requesting party's counsel")

    if "monthly_income_cents" in data and data["monthly_income_cents"] is not None:
        w["monthly_income_cents"] = validate.non_negative_int(data, "monthly_income_cents", required=True)
    if "household_size" in data and data["household_size"] is not None:
        w["household_size"] = validate.positive_int(data, "household_size", required=True)

    w["status"] = "PENDING"
    w["eligibility_ratio"] = calc.fee_waiver_eligibility(w["monthly_income_cents"], w["household_size"])
    db.touch(w)
    return success(domain._clean(w), status=200)


@bp.post("/fee-waivers/<waiver_id>/approve")
def approve(waiver_id):
    _, role = get_actor()
    require_role(role, {"Clerk"})
    w = domain.get_or_404(db.fee_waivers, waiver_id)
    if w["status"] not in ("PENDING", "NEEDS_INFO"):
        raise errors.err(errors.ERR_INVALID_STATE, "Waiver cannot be approved from its state")
    filing = db.filings[w["filing_id"]]
    if filing["fee_status"] != "ASSESSED":
        raise errors.err(errors.ERR_FEE_NOT_ASSESSED, "Target filing fee is not ASSESSED")

    w["status"] = "APPROVED"
    w["decided_at"] = _clock_iso()
    db.touch(w)

    # Cascade hop 1: filing fee -> WAIVED.
    filing["fee_status"] = "WAIVED"
    db.touch(filing)
    # Cascade hop 2: recompute case aggregates + version bump.
    case = db.cases[w["case_id"]]
    domain.bump_case(case)
    return success(domain._clean(w), status=200)


@bp.post("/fee-waivers/<waiver_id>/deny")
def deny(waiver_id):
    _, role = get_actor()
    require_role(role, {"Clerk"})
    w = domain.get_or_404(db.fee_waivers, waiver_id)
    if w["status"] not in ("PENDING", "NEEDS_INFO"):
        raise errors.err(errors.ERR_INVALID_STATE, "Waiver cannot be denied from its state")
    w["status"] = "DENIED"
    w["decided_at"] = _clock_iso()
    db.touch(w)
    return success(domain._clean(w), status=200)


def _clock_iso():
    dt = db.now_clock()
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
