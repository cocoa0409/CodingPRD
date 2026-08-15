"""Clock, borrowers, facilities, participants."""
from flask import Blueprint

import errors
from auth import require_roles, body, req_str, req_int, opt_int, req_enum, req_date
from domain import get_or_404, paginate, apply_filters
from responses import ok, ok_list
from store import db, new_entity, touch, now_ts, clock_raw, set_clock
from calc import recompute_committed, recompute_shares, facility_participants

bp = Blueprint("core", __name__, url_prefix="/api")

READ_ROLES = ("AgentBank", "Borrower", "ParticipantLender")

SECTORS = ("INDUSTRIAL", "ENERGY", "REAL_ESTATE", "HEALTHCARE", "TECHNOLOGY", "FINANCIAL", "OTHER")
RISK_RATINGS = ("INVESTMENT_GRADE", "CROSSOVER", "SPECULATIVE", "DISTRESSED")
DAY_COUNT_BASES = ("ACT_360", "ACT_365", "BASIS_30_360")


# ---------------------------------------------------------------------------
# clock
# ---------------------------------------------------------------------------

@bp.post("/_clock/set_current_utc")
@require_roles("AgentBank")
def clock_set(uid, role):
    data = body()
    raw = data.get("to_iso8601")
    if not isinstance(raw, str) or not raw.strip():
        raise errors.invalid_request("to_iso8601 is required")
    try:
        set_clock(raw)
    except ValueError:
        raise errors.invalid_request("to_iso8601 must be an ISO 8601 datetime")
    return ok({"current_utc": clock_raw()})


# ---------------------------------------------------------------------------
# borrowers
# ---------------------------------------------------------------------------

@bp.post("/borrowers")
@require_roles("AgentBank")
def borrower_create(uid, role):
    data = body()
    ent = new_entity()
    ent.update(
        {
            "legal_name": req_str(data, "legal_name"),
            "sector": req_enum(data, "sector", SECTORS),
            "risk_rating": req_enum(data, "risk_rating", RISK_RATINGS),
            "status": "ACTIVE",
        }
    )
    db["borrowers"][ent["id"]] = ent
    return ok({k: v for k, v in ent.items() if not k.startswith("_")}, 201)


@bp.get("/borrowers/<borrowerId>")
@require_roles(*READ_ROLES)
def borrower_get(uid, role, borrowerId):
    ent = get_or_404("borrowers", borrowerId)
    return ok({k: v for k, v in ent.items() if not k.startswith("_")})


@bp.get("/borrowers/<borrowerId>/facilities")
@require_roles(*READ_ROLES)
def borrower_facilities(uid, role, borrowerId):
    get_or_404("borrowers", borrowerId)
    items = [f for f in db["facilities"].values() if f["borrower_id"] == borrowerId]
    page, limit, offset, total = paginate(items)
    return ok_list([{k: v for k, v in f.items() if not k.startswith("_")} for f in page], limit, offset, total)


# ---------------------------------------------------------------------------
# facilities
# ---------------------------------------------------------------------------

@bp.post("/facilities")
@require_roles("AgentBank")
def facility_create(uid, role):
    data = body()
    borrower_id = data.get("borrower_id")
    if not isinstance(borrower_id, str) or not borrower_id.strip():
        raise errors.invalid_request("borrower_id is required")
    borrower = db["borrowers"].get(borrower_id)
    if borrower is None:
        raise errors.not_found("borrower_id does not resolve")
    ent = new_entity()
    total = req_int(data, "total_commitment_cents", minimum=1)
    rate = req_int(data, "interest_rate_bps", minimum=0)
    maturity_raw, _m = req_date(data, "maturity_date")
    ent.update(
        {
            "borrower_id": borrower_id,
            "facility_name": req_str(data, "facility_name"),
            "total_commitment_cents": total,
            "currency": req_str(data, "currency"),
            "interest_rate_bps": rate,
            "day_count_basis": req_enum(data, "day_count_basis", DAY_COUNT_BASES),
            "servicing_fee_bps": req_int(data, "servicing_fee_bps", minimum=0),
            "default_interest_addon_bps": req_int(data, "default_interest_addon_bps", minimum=0),
            "maturity_date": maturity_raw,
            "majority_threshold_bps": opt_int(data, "majority_threshold_bps", 5001),
            "supermajority_threshold_bps": opt_int(data, "supermajority_threshold_bps", 6667),
            "quorum_bps": opt_int(data, "quorum_bps", 5000),
            "voting_window_days": opt_int(data, "voting_window_days", 15),
            "min_transfer_cents": opt_int(data, "min_transfer_cents", 1000000),
            "status": "STRUCTURING",
            "committed_cents": 0,
            "funded_principal_cents": 0,
            "outstanding_principal_cents": 0,
            "accrued_interest_cents": 0,
            "undistributed_cash_cents": 0,
            "last_distribution_value_date": None,
            "_rate_history": [(None, rate)],
        }
    )
    db["facilities"][ent["id"]] = ent
    return ok({k: v for k, v in ent.items() if not k.startswith("_")}, 201)


@bp.get("/facilities/<facilityId>")
@require_roles(*READ_ROLES)
def facility_get(uid, role, facilityId):
    ent = get_or_404("facilities", facilityId)
    return ok({k: v for k, v in ent.items() if not k.startswith("_")})


@bp.get("/facilities")
@require_roles(*READ_ROLES)
def facility_list(uid, role):
    items = apply_filters(list(db["facilities"].values()), [("borrower_id", "borrower_id"), ("status", "status")])
    page, limit, offset, total = paginate(items)
    return ok_list([{k: v for k, v in f.items() if not k.startswith("_")} for f in page], limit, offset, total)


@bp.post("/facilities/<facilityId>/terminate")
@require_roles("AgentBank")
def facility_terminate(uid, role, facilityId):
    fac = get_or_404("facilities", facilityId)
    if fac["status"] not in ("STRUCTURING", "SYNDICATING", "COMMITTED"):
        raise errors.invalid_state("Facility cannot be terminated from its state")
    if any(d["status"] != "CANCELLED" for d in db["draws"].values() if d["facility_id"] == fac["id"]):
        raise errors.invalid_state("Facility has non-cancelled draws")
    for p in facility_participants(fac["id"]):
        if p["status"] in ("PROPOSED", "COMMITTED"):
            p["status"] = "WITHDRAWN"
            if p["share_bps"] != 0:
                p["share_bps"] = 0
            touch(p)
    fac["status"] = "TERMINATED"
    fac["committed_cents"] = 0
    touch(fac)
    return ok({k: v for k, v in fac.items() if not k.startswith("_")})


def _facility_children(facilityId, collection, extra_filters=None):
    get_or_404("facilities", facilityId)
    items = [e for e in db[collection].values() if e.get("facility_id") == facilityId]
    if extra_filters:
        items = apply_filters(items, extra_filters)
    page, limit, offset, total = paginate(items)
    return ok_list([{k: v for k, v in e.items() if not k.startswith("_")} for e in page], limit, offset, total)


@bp.get("/facilities/<facilityId>/participants")
@require_roles(*READ_ROLES)
def facility_participants_list(uid, role, facilityId):
    return _facility_children(facilityId, "participants", [("status", "status")])


@bp.get("/facilities/<facilityId>/draws")
@require_roles(*READ_ROLES)
def facility_draws_list(uid, role, facilityId):
    return _facility_children(facilityId, "draws", [("status", "status")])


@bp.get("/facilities/<facilityId>/payments")
@require_roles(*READ_ROLES)
def facility_payments_list(uid, role, facilityId):
    return _facility_children(facilityId, "payments", [("status", "status")])


@bp.get("/facilities/<facilityId>/modification_requests")
@require_roles(*READ_ROLES)
def facility_mods_list(uid, role, facilityId):
    return _facility_children(facilityId, "modifications", [("status", "status")])


@bp.get("/facilities/<facilityId>/default_cases")
@require_roles(*READ_ROLES)
def facility_cases_list(uid, role, facilityId):
    return _facility_children(facilityId, "default_cases", [("status", "status")])


# ---------------------------------------------------------------------------
# participants
# ---------------------------------------------------------------------------

@bp.post("/participants")
@require_roles("AgentBank")
def participant_create(uid, role):
    data = body()
    facility_id = data.get("facility_id")
    if not isinstance(facility_id, str) or not facility_id.strip():
        raise errors.invalid_request("facility_id is required")
    if db["facilities"].get(facility_id) is None:
        raise errors.not_found("facility_id does not resolve")
    ent = new_entity()
    ent.update(
        {
            "facility_id": facility_id,
            "participant_name": req_str(data, "participant_name"),
            "commitment_cents": req_int(data, "commitment_cents", minimum=1),
            "status": "PROPOSED",
            "share_bps": 0,
            "funded_cents": 0,
            "cumulative_interest_cents": 0,
            "cumulative_principal_cents": 0,
        }
    )
    db["participants"][ent["id"]] = ent
    return ok({k: v for k, v in ent.items() if not k.startswith("_")}, 201)


@bp.get("/participants/<participantId>")
@require_roles(*READ_ROLES)
def participant_get(uid, role, participantId):
    ent = get_or_404("participants", participantId)
    return ok({k: v for k, v in ent.items() if not k.startswith("_")})


@bp.get("/participants")
@require_roles(*READ_ROLES)
def participant_list(uid, role):
    items = apply_filters(
        list(db["participants"].values()),
        [("facility_id", "facility_id"), ("status", "status")],
    )
    page, limit, offset, total = paginate(items)
    return ok_list([{k: v for k, v in e.items() if not k.startswith("_")} for e in page], limit, offset, total)


@bp.post("/participants/<participantId>/commit")
@require_roles("AgentBank")
def participant_commit(uid, role, participantId):
    p = get_or_404("participants", participantId)
    if p["status"] != "PROPOSED":
        raise errors.invalid_state("Only a PROPOSED participant can be committed")
    fac = db["facilities"][p["facility_id"]]
    if fac["status"] not in ("STRUCTURING", "SYNDICATING", "COMMITTED"):
        raise errors.invalid_state("Facility is no longer accepting commitments")
    if fac["committed_cents"] + p["commitment_cents"] > fac["total_commitment_cents"]:
        raise errors.commitment_exceeds_total()
    p["status"] = "COMMITTED"
    touch(p)
    recompute_committed(fac)
    recompute_shares(fac)
    return ok({k: v for k, v in p.items() if not k.startswith("_")})


@bp.post("/participants/<participantId>/withdraw")
@require_roles("AgentBank")
def participant_withdraw(uid, role, participantId):
    p = get_or_404("participants", participantId)
    if p["status"] not in ("PROPOSED", "COMMITTED"):
        raise errors.invalid_state("Only PROPOSED or COMMITTED participants can withdraw")
    fac = db["facilities"][p["facility_id"]]
    was_committed = p["status"] == "COMMITTED"
    if was_committed and fac["status"] not in ("STRUCTURING", "SYNDICATING", "COMMITTED"):
        raise errors.invalid_state("Withdrawal is pre-funding only")
    p["status"] = "WITHDRAWN"
    touch(p)
    if was_committed:
        recompute_committed(fac)
        recompute_shares(fac)
    elif p["share_bps"] != 0:
        p["share_bps"] = 0
        touch(p)
    return ok({k: v for k, v in p.items() if not k.startswith("_")})
