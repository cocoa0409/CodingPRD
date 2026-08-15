"""Default cases and default votes."""
from flask import Blueprint

import errors
from auth import require_roles, body, req_enum
from domain import (
    get_or_404,
    paginate,
    apply_filters,
    restore_borrower_if_clear,
    facility_close_status,
)
from responses import ok, ok_list
from store import db, new_entity, touch, now_ts, clock_dt
from calc import (
    materialize_facility,
    rerate_retroactive_base,
    recompute_default_tally,
    facility_draws,
    facility_accrued,
)

bp = Blueprint("defaults", __name__, url_prefix="/api")

READ_ROLES = ("AgentBank", "Borrower", "ParticipantLender")
DEFAULT_TYPES = ("PAYMENT_DEFAULT", "COVENANT_DEFAULT", "INSOLVENCY", "REPRESENTATION_BREACH")
DEFAULT_VOTES = ("ACCELERATE", "WAIVE", "REJECT")


def pub(ent):
    return {k: v for k, v in ent.items() if not k.startswith("_")}


def _resolve_case(case, new_status, re_rate_mode):
    """Shared resolution cascade for cure / waive / accelerate."""
    fac = db["facilities"][case["facility_id"]]
    case["status"] = new_status
    case["resolved_at"] = now_ts()
    touch(case)
    as_of = clock_dt().date()
    if re_rate_mode == "waive":
        # status already flipped: the case no longer contributes an addon
        # window, so replaying the ledgers removes the addon retroactively
        rerate_retroactive_base(fac)
    materialize_facility(fac, as_of)
    fac["accrued_interest_cents"] = facility_accrued(fac)
    touch(fac)
    if new_status in ("CURED", "WAIVED"):
        if fac["status"] == "IN_DEFAULT":
            fac["status"] = facility_close_status(fac, "ACTIVE")
            touch(fac)
        borrower = db["borrowers"].get(fac["borrower_id"])
        if borrower is not None:
            restore_borrower_if_clear(borrower)
    elif new_status == "ACCELERATED":
        if fac["status"] == "IN_DEFAULT":
            fac["status"] = "ACCELERATED"
            touch(fac)


# ---------------------------------------------------------------------------
# default cases
# ---------------------------------------------------------------------------

@bp.post("/default_cases")
@require_roles("AgentBank")
def case_create(uid, role):
    data = body()
    facility_id = data.get("facility_id")
    if not isinstance(facility_id, str) or not facility_id.strip():
        raise errors.invalid_request("facility_id is required")
    fac = db["facilities"].get(facility_id)
    if fac is None:
        raise errors.not_found("facility_id does not resolve")
    dtype = req_enum(data, "default_type", DEFAULT_TYPES)
    if fac["status"] != "ACTIVE":
        raise errors.invalid_state("Default declaration requires an ACTIVE facility")
    if any(
        c["facility_id"] == fac["id"] and c["status"] == "DECLARED"
        for c in db["default_cases"].values()
    ):
        raise errors.default_already_active()

    ent = new_entity()
    ent.update(
        {
            "facility_id": fac["id"],
            "default_type": dtype,
            "declared_at": now_ts(),
            "voting_base_cents": fac["committed_cents"],
            "accelerate_commitment_cents": 0,
            "waive_commitment_cents": 0,
            "accelerate_share_bps": 0,
            "waive_share_bps": 0,
            "status": "DECLARED",
            "resolved_at": None,
        }
    )
    db["default_cases"][ent["id"]] = ent

    # hop 1: facility ACTIVE -> IN_DEFAULT
    fac["status"] = "IN_DEFAULT"
    touch(fac)
    # hop 2a: withdraw open solicitations (votes voided)
    for mod in db["modifications"].values():
        if mod["facility_id"] == fac["id"] and mod["status"] == "SOLICITING":
            for v in db["consent_votes"].values():
                if v["modification_id"] == mod["id"] and v["status"] in ("CAST", "RECAST"):
                    v["status"] = "VOIDED"
                    touch(v)
            mod["status"] = "WITHDRAWN"
            touch(mod)
    # hop 2b: re-rate draws — materialize to the declared date; the new
    # default window applies the addon from that date forward
    materialize_facility(fac, clock_dt().date())
    # hop 3: borrower marking
    borrower = db["borrowers"].get(fac["borrower_id"])
    if borrower is not None:
        if dtype == "INSOLVENCY":
            if borrower["status"] != "INSOLVENT":
                borrower["status"] = "INSOLVENT"
                touch(borrower)
        elif borrower["status"] == "ACTIVE":
            borrower["status"] = "DELINQUENT"
            touch(borrower)
    return ok(pub(ent), 201)


@bp.get("/default_cases/<caseId>")
@require_roles(*READ_ROLES)
def case_get(uid, role, caseId):
    return ok(pub(get_or_404("default_cases", caseId)))


@bp.get("/default_cases")
@require_roles(*READ_ROLES)
def case_list(uid, role):
    items = apply_filters(
        list(db["default_cases"].values()),
        [("facility_id", "facility_id"), ("status", "status")],
    )
    page, limit, offset, total = paginate(items)
    return ok_list([pub(e) for e in page], limit, offset, total)


@bp.post("/default_cases/<caseId>/votes")
@require_roles("ParticipantLender")
def default_vote_cast(uid, role, caseId):
    case = get_or_404("default_cases", caseId)
    data = body()
    vote_val = req_enum(data, "vote", DEFAULT_VOTES)
    if case["status"] != "DECLARED":
        raise errors.invalid_state("Default case is not open for voting")
    existing = [
        v
        for v in db["default_votes"].values()
        if v["default_case_id"] == case["id"]
        and v["participant_id"] == uid
        and v["status"] in ("CAST", "RECAST")
    ]
    if existing:
        raise errors.duplicate_vote()
    p = db["participants"].get(uid)
    if p is None or p["facility_id"] != case["facility_id"] or p["status"] != "FUNDED":
        raise errors.participant_not_eligible("Voter must be a FUNDED participant of the facility")
    ent = new_entity()
    ent.update(
        {
            "default_case_id": case["id"],
            "participant_id": uid,
            "vote": vote_val,
            "voted_share_bps": p["share_bps"],
            "cast_at": now_ts(),
            "recast_count": 0,
            "status": "CAST",
        }
    )
    db["default_votes"][ent["id"]] = ent
    recompute_default_tally(case)
    return ok(pub(ent), 201)


@bp.post("/default_cases/<caseId>/cure")
@require_roles("AgentBank")
def case_cure(uid, role, caseId):
    case = get_or_404("default_cases", caseId)
    if case["status"] != "DECLARED":
        raise errors.invalid_state("Only a DECLARED case can be cured")
    _resolve_case(case, "CURED", "cure")
    return ok(pub(case))


@bp.post("/default_cases/<caseId>/accelerate")
@require_roles("AgentBank")
def case_accelerate(uid, role, caseId):
    case = get_or_404("default_cases", caseId)
    if case["status"] != "DECLARED":
        raise errors.invalid_state("Only a DECLARED case can be accelerated")
    fac = db["facilities"][case["facility_id"]]
    recompute_default_tally(case)
    if case["accelerate_share_bps"] < fac["supermajority_threshold_bps"]:
        raise errors.acceleration_threshold()
    _resolve_case(case, "ACCELERATED", "accelerate")
    return ok(pub(case))


@bp.post("/default_cases/<caseId>/waive")
@require_roles("AgentBank")
def case_waive(uid, role, caseId):
    case = get_or_404("default_cases", caseId)
    if case["status"] != "DECLARED":
        raise errors.invalid_state("Only a DECLARED case can be waived")
    fac = db["facilities"][case["facility_id"]]
    recompute_default_tally(case)
    if case["waive_share_bps"] < fac["majority_threshold_bps"]:
        raise errors.waiver_threshold()
    _resolve_case(case, "WAIVED", "waive")
    return ok(pub(case))


# ---------------------------------------------------------------------------
# default votes
# ---------------------------------------------------------------------------

@bp.post("/default_votes/<voteId>/recast")
@require_roles("ParticipantLender")
def default_vote_recast(uid, role, voteId):
    v = get_or_404("default_votes", voteId)
    if v["participant_id"] != uid:
        raise errors.not_owner("A participant may only recast its own vote")
    data = body()
    vote_val = req_enum(data, "vote", DEFAULT_VOTES)
    if v["status"] not in ("CAST", "RECAST"):
        raise errors.invalid_state("A voided vote cannot be recast")
    case = db["default_cases"][v["default_case_id"]]
    if case["status"] != "DECLARED":
        raise errors.invalid_state("Default case is no longer open")
    p = db["participants"].get(uid)
    if p is None or p["status"] != "FUNDED":
        raise errors.participant_not_eligible("Voter must be FUNDED")
    v["vote"] = vote_val
    v["recast_count"] += 1
    v["cast_at"] = now_ts()
    v["voted_share_bps"] = p["share_bps"]
    v["status"] = "RECAST"
    touch(v)
    recompute_default_tally(case)
    return ok(pub(v))


@bp.get("/default_votes/<voteId>")
@require_roles(*READ_ROLES)
def default_vote_get(uid, role, voteId):
    return ok(pub(get_or_404("default_votes", voteId)))


@bp.get("/default_votes")
@require_roles(*READ_ROLES)
def default_vote_list(uid, role):
    items = apply_filters(
        list(db["default_votes"].values()),
        [
            ("default_case_id", "default_case_id"),
            ("participant_id", "participant_id"),
            ("status", "status"),
        ],
    )
    page, limit, offset, total = paginate(items)
    return ok_list([pub(e) for e in page], limit, offset, total)
