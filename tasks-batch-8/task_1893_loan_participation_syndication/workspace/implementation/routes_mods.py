"""Modification requests and consent votes."""
from datetime import timedelta

from flask import Blueprint

import errors
from auth import require_roles, body, req_str, req_enum, is_int
from domain import get_or_404, paginate, apply_filters
from responses import ok, ok_list
from store import db, new_entity, touch, now_ts, clock_dt, parse_date
from calc import (
    facility_participants,
    facility_draws,
    recompute_mod_tally,
    recompute_shares,
    apply_principal_reduction,
    facility_outstanding,
    SOLICITATION_BUFFER_HOURS,
    UNANIMOUS_THRESHOLD_BPS,
    draw_order,
)

bp = Blueprint("mods", __name__, url_prefix="/api")

READ_ROLES = ("AgentBank", "Borrower", "ParticipantLender")

MOD_TYPES = (
    "RATE_CHANGE",
    "MATURITY_EXTENSION",
    "COMMITMENT_INCREASE",
    "COVENANT_WAIVER",
    "PRINCIPAL_WRITE_DOWN",
    "BORROWER_SUBSTITUTION",
)

TERMS_KEY = {
    "RATE_CHANGE": "new_interest_rate_bps",
    "MATURITY_EXTENSION": "new_maturity_date",
    "COMMITMENT_INCREASE": "commitment_increase_cents",
    "COVENANT_WAIVER": "waiver_text",
    "PRINCIPAL_WRITE_DOWN": "write_down_cents",
    "BORROWER_SUBSTITUTION": "new_borrower_id",
}

CONSENT_CLASS = {
    "COMMITMENT_INCREASE": "MAJORITY",
    "COVENANT_WAIVER": "MAJORITY",
    "RATE_CHANGE": "SUPERMAJORITY",
    "MATURITY_EXTENSION": "SUPERMAJORITY",
    "PRINCIPAL_WRITE_DOWN": "UNANIMOUS",
    "BORROWER_SUBSTITUTION": "UNANIMOUS",
}

VOTE_VALUES = ("APPROVE", "REJECT", "ABSTAIN")


def pub(ent):
    return {k: v for k, v in ent.items() if not k.startswith("_")}


def _required_threshold(facility, consent_class):
    if consent_class == "MAJORITY":
        return facility["majority_threshold_bps"]
    if consent_class == "SUPERMAJORITY":
        return facility["supermajority_threshold_bps"]
    return UNANIMOUS_THRESHOLD_BPS


# ---------------------------------------------------------------------------
# modification requests
# ---------------------------------------------------------------------------

@bp.post("/modification_requests")
@require_roles("Borrower")
def mod_create(uid, role):
    data = body()
    facility_id = data.get("facility_id")
    if not isinstance(facility_id, str) or not facility_id.strip():
        raise errors.invalid_request("facility_id is required")
    fac = db["facilities"].get(facility_id)
    if fac is None:
        raise errors.not_found("facility_id does not resolve")
    mtype = req_enum(data, "modification_type", MOD_TYPES)
    terms = data.get("terms")
    if not isinstance(terms, dict):
        raise errors.invalid_request("terms must be an object")
    key = TERMS_KEY[mtype]
    if set(terms.keys()) != {key}:
        raise errors.invalid_request(f"terms must contain exactly '{key}'")
    val = terms[key]
    if key in ("new_interest_rate_bps",):
        if not is_int(val) or val < 0:
            raise errors.invalid_request(f"terms.{key} must be a non-negative integer")
    elif key in ("commitment_increase_cents", "write_down_cents"):
        if not is_int(val) or val <= 0:
            raise errors.invalid_request(f"terms.{key} must be a positive integer")
    elif key == "new_maturity_date":
        try:
            parse_date(val)
        except (ValueError, TypeError):
            raise errors.invalid_request(f"terms.{key} must be an ISO date")
    else:
        if not isinstance(val, str) or not val.strip():
            raise errors.invalid_request(f"terms.{key} must be a non-empty string")
    consent = CONSENT_CLASS[mtype]
    ent = new_entity()
    ent.update(
        {
            "facility_id": fac["id"],
            "requested_by_borrower_id": uid,
            "modification_type": mtype,
            "terms": terms,
            "required_consent_class": consent,
            "required_threshold_bps": _required_threshold(fac, consent),
            "voting_open_at": None,
            "voting_close_at": None,
            "voting_base_cents": None,
            "approving_commitment_cents": 0,
            "cast_commitment_cents": 0,
            "approving_share_bps": 0,
            "cast_share_bps": 0,
            "status": "DRAFT",
        }
    )
    db["modifications"][ent["id"]] = ent
    return ok(pub(ent), 201)


@bp.get("/modification_requests/<modificationId>")
@require_roles(*READ_ROLES)
def mod_get(uid, role, modificationId):
    return ok(pub(get_or_404("modifications", modificationId)))


@bp.get("/modification_requests")
@require_roles(*READ_ROLES)
def mod_list(uid, role):
    items = apply_filters(
        list(db["modifications"].values()),
        [
            ("facility_id", "facility_id"),
            ("borrower_id", "requested_by_borrower_id"),
            ("requested_by_borrower_id", "requested_by_borrower_id"),
            ("status", "status"),
        ],
    )
    page, limit, offset, total = paginate(items)
    return ok_list([pub(e) for e in page], limit, offset, total)


@bp.post("/modification_requests/<modificationId>/solicit")
@require_roles("AgentBank")
def mod_solicit(uid, role, modificationId):
    mod = get_or_404("modifications", modificationId)
    if mod["status"] not in ("DRAFT", "FAILED", "EXPIRED"):
        raise errors.invalid_state("Request cannot be solicited from its state")
    fac = db["facilities"][mod["facility_id"]]
    if fac["status"] in ("IN_DEFAULT", "ACCELERATED"):
        raise errors.facility_in_default()
    if fac["status"] in ("CLOSED", "TERMINATED"):
        raise errors.invalid_state("Facility is wound down")
    now = clock_dt()
    close = now + timedelta(days=fac["voting_window_days"])
    buffer = timedelta(hours=SOLICITATION_BUFFER_HOURS)
    for other in db["modifications"].values():
        if other["id"] == mod["id"] or other["facility_id"] != fac["id"]:
            continue
        if other["status"] != "SOLICITING" or not other.get("voting_open_at"):
            continue
        from store import _parse_dt

        o_open = _parse_dt(other["voting_open_at"])
        o_close = _parse_dt(other["voting_close_at"])
        if now < o_close + buffer and o_open < close + buffer:
            raise errors.solicitation_overlap()
    # re-solicitation: void the prior round's votes
    if mod["status"] in ("FAILED", "EXPIRED"):
        for v in db["consent_votes"].values():
            if v["modification_id"] == mod["id"] and v["status"] in ("CAST", "RECAST"):
                v["status"] = "VOIDED"
                touch(v)
    mod["voting_open_at"] = now_ts()
    mod["voting_close_at"] = (
        close.strftime("%Y-%m-%dT%H:%M:%S.") + f"{close.microsecond // 1000:03d}Z"
    )
    mod["voting_base_cents"] = fac["committed_cents"]
    mod["approving_commitment_cents"] = 0
    mod["cast_commitment_cents"] = 0
    mod["approving_share_bps"] = 0
    mod["cast_share_bps"] = 0
    mod["status"] = "SOLICITING"
    touch(mod)
    return ok(pub(mod))


@bp.post("/modification_requests/<modificationId>/votes")
@require_roles("ParticipantLender")
def vote_cast(uid, role, modificationId):
    mod = get_or_404("modifications", modificationId)
    data = body()
    vote_val = req_enum(data, "vote", VOTE_VALUES)
    if mod["status"] != "SOLICITING":
        raise errors.voting_closed("Solicitation is not open for voting")
    existing = [
        v
        for v in db["consent_votes"].values()
        if v["modification_id"] == mod["id"]
        and v["participant_id"] == uid
        and v["status"] in ("CAST", "RECAST")
    ]
    if existing:
        raise errors.duplicate_vote()
    p = db["participants"].get(uid)
    if p is None or p["facility_id"] != mod["facility_id"] or p["status"] != "FUNDED":
        raise errors.participant_not_eligible("Voter must be a FUNDED participant of the facility")
    from store import _parse_dt

    if clock_dt() > _parse_dt(mod["voting_close_at"]):
        raise errors.voting_closed("Voting window has closed")
    ent = new_entity()
    ent.update(
        {
            "modification_id": mod["id"],
            "participant_id": uid,
            "vote": vote_val,
            "voted_share_bps": p["share_bps"],
            "cast_at": now_ts(),
            "recast_count": 0,
            "status": "CAST",
        }
    )
    db["consent_votes"][ent["id"]] = ent
    recompute_mod_tally(mod)
    return ok(pub(ent), 201)


@bp.post("/modification_requests/<modificationId>/tally_close")
@require_roles("AgentBank")
def mod_tally_close(uid, role, modificationId):
    mod = get_or_404("modifications", modificationId)
    if mod["status"] != "SOLICITING":
        raise errors.invalid_state("Only a SOLICITING request can be tallied")
    from store import _parse_dt

    if clock_dt() <= _parse_dt(mod["voting_close_at"]):
        raise errors.voting_still_open()
    fac = db["facilities"][mod["facility_id"]]
    recompute_mod_tally(mod)
    if mod["cast_share_bps"] < fac["quorum_bps"]:
        mod["status"] = "EXPIRED"
    elif mod["approving_share_bps"] >= mod["required_threshold_bps"]:
        mod["status"] = "PASSED"
    else:
        mod["status"] = "FAILED"
    touch(mod)
    return ok(pub(mod))


@bp.post("/modification_requests/<modificationId>/implement")
@require_roles("AgentBank")
def mod_implement(uid, role, modificationId):
    mod = get_or_404("modifications", modificationId)
    if mod["status"] != "PASSED":
        raise errors.modification_not_passed()
    fac = db["facilities"][mod["facility_id"]]
    terms = mod["terms"]
    mtype = mod["modification_type"]
    if mtype == "RATE_CHANGE":
        new_rate = terms["new_interest_rate_bps"]
        fac.setdefault("_rate_history", [])
        fac["_rate_history"].append((clock_dt().date(), new_rate))
        fac["interest_rate_bps"] = new_rate
        touch(fac)
    elif mtype == "MATURITY_EXTENSION":
        fac["maturity_date"] = terms["new_maturity_date"]
        touch(fac)
    elif mtype == "COMMITMENT_INCREASE":
        fac["total_commitment_cents"] += terms["commitment_increase_cents"]
        if fac["status"] == "COMMITTED":
            fac["status"] = "SYNDICATING"
        touch(fac)
        recompute_shares(fac)
    elif mtype == "COVENANT_WAIVER":
        pass  # waiver_text already recorded in terms
    elif mtype == "PRINCIPAL_WRITE_DOWN":
        amount = terms["write_down_cents"]
        outstanding = facility_outstanding(fac)
        if amount > outstanding:
            raise errors.writedown_exceeds()
        apply_principal_reduction(fac, amount)
        fac["outstanding_principal_cents"] = facility_outstanding(fac)
        touch(fac)
    elif mtype == "BORROWER_SUBSTITUTION":
        new_borrower = db["borrowers"].get(terms["new_borrower_id"])
        if new_borrower is None:
            raise errors.not_found("terms.new_borrower_id does not resolve")
        fac["borrower_id"] = new_borrower["id"]
        touch(fac)
    mod["status"] = "IMPLEMENTED"
    touch(mod)
    return ok(pub(mod))


@bp.post("/modification_requests/<modificationId>/withdraw")
@require_roles("AgentBank", "Borrower")
def mod_withdraw(uid, role, modificationId):
    mod = get_or_404("modifications", modificationId)
    if role == "Borrower" and mod["requested_by_borrower_id"] != uid:
        raise errors.not_owner("A borrower may only withdraw its own request")
    if mod["status"] not in ("DRAFT", "SOLICITING"):
        raise errors.invalid_state("Only DRAFT or SOLICITING requests can be withdrawn")
    if mod["status"] == "SOLICITING":
        for v in db["consent_votes"].values():
            if v["modification_id"] == mod["id"] and v["status"] in ("CAST", "RECAST"):
                v["status"] = "VOIDED"
                touch(v)
    mod["status"] = "WITHDRAWN"
    touch(mod)
    return ok(pub(mod))


# ---------------------------------------------------------------------------
# consent votes
# ---------------------------------------------------------------------------

@bp.post("/consent_votes/<voteId>/recast")
@require_roles("ParticipantLender")
def vote_recast(uid, role, voteId):
    v = get_or_404("consent_votes", voteId)
    if v["participant_id"] != uid:
        raise errors.not_owner("A participant may only recast its own vote")
    data = body()
    vote_val = req_enum(data, "vote", VOTE_VALUES)
    if v["status"] not in ("CAST", "RECAST"):
        raise errors.invalid_state("A voided vote cannot be recast")
    mod = db["modifications"][v["modification_id"]]
    if mod["status"] != "SOLICITING":
        raise errors.voting_closed("Solicitation is not open for voting")
    p = db["participants"].get(uid)
    if p is None or p["status"] != "FUNDED":
        raise errors.participant_not_eligible("Voter must be FUNDED")
    from store import _parse_dt

    if clock_dt() > _parse_dt(mod["voting_close_at"]):
        raise errors.voting_closed("Voting window has closed")
    v["vote"] = vote_val
    v["recast_count"] += 1
    v["cast_at"] = now_ts()
    v["voted_share_bps"] = p["share_bps"]
    v["status"] = "RECAST"
    touch(v)
    recompute_mod_tally(mod)
    return ok(pub(v))


@bp.get("/consent_votes/<voteId>")
@require_roles(*READ_ROLES)
def vote_get(uid, role, voteId):
    return ok(pub(get_or_404("consent_votes", voteId)))


@bp.get("/consent_votes")
@require_roles(*READ_ROLES)
def vote_list(uid, role):
    items = apply_filters(
        list(db["consent_votes"].values()),
        [
            ("modification_id", "modification_id"),
            ("participant_id", "participant_id"),
            ("status", "status"),
        ],
    )
    page, limit, offset, total = paginate(items)
    return ok_list([pub(e) for e in page], limit, offset, total)
