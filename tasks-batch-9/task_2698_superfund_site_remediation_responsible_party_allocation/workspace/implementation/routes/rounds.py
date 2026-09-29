"""Allocation rounds: Gore-factor weighting, balloting, adoption, reopening."""

from decimal import Decimal
from fractions import Fraction

from flask import Blueprint

import constants as K
import derive
import logical_clock
import serialize
import shape
import store
import txn
from authz import require
from errors import ApiError
from numeric import frac
from routes import common

bp = Blueprint("rounds", __name__)

ZERO = Decimal("0.00")


def _candidates(site):
    """Every party of the site whose status is anything other than IDENTIFIED,
    enumerated in created_at ascending order, never by id."""
    return [p for p in derive.site_prps(site["id"]) if p["status"] != "IDENTIFIED"]


def _has_basis(site, candidates):
    """The same three site-wide totals the provisional variant uses, computed
    before any share exists."""
    ids = {p["id"] for p in candidates}
    volume = Fraction(0)
    toxicity = Fraction(0)
    for record in derive.site_waste(site["id"]):
        if record["prp_id"] not in ids or record["status"] not in ("SUBMITTED", "VERIFIED"):
            continue
        value = frac(record["effective_volume_tons"])
        volume += value
        toxicity += value * K.TOXICITY_MULTIPLIER[record["toxicity_class"]]
    ownership = sum(p["ownership_days_total"] for p in candidates)
    return volume > 0 or toxicity > 0 or ownership > 0


def _mint_share(round_, prp):
    share = common.new_record(
        {
            "allocation_round_id": round_["id"],
            "prp_id": prp["id"],
            "provisional_pct": ZERO,
            "final_pct": None,
            "pre_settlement_final_pct": None,
            "disposition": "PENDING",
            "ballot": None,
            "ballot_rationale": None,
            "ballot_cast_at": None,
        }
    )
    store.allocation_shares[share["id"]] = share
    return share


@bp.post("/sites/<site_id>/allocation-rounds")
def create_round(site_id):
    actor = require(K.ROLE_FACILITATOR)
    body = shape.get_body()
    wv = shape.int_field(body, "weight_volume_bp", lo=0, hi=K.WEIGHT_SUM_BP)
    wt = shape.int_field(body, "weight_toxicity_bp", lo=0, hi=K.WEIGHT_SUM_BP)
    wo = shape.int_field(body, "weight_ownership_bp", lo=0, hi=K.WEIGHT_SUM_BP)
    expected = shape.int_field(body, "expected_site_version", lo=0)
    site = common.get_site(site_id)
    if expected != site["version"]:
        raise ApiError("ERR_STALE_SITE_VERSION")
    common.deny_frozen(site)
    common.deny_restricted(site)
    common.require_phase(site, K.PHASE_RIFS_OR_LATER)
    if wv + wt + wo != K.WEIGHT_SUM_BP:
        raise ApiError("ERR_WEIGHTS_NOT_NORMALIZED")
    candidates = _candidates(site)
    if not _has_basis(site, candidates):
        raise ApiError("ERR_NO_ALLOCATION_BASIS")

    existing = derive.site_rounds(site["id"])
    number = max([r["round_number"] for r in existing], default=0) + 1
    round_ = common.new_record(
        {
            "site_id": site["id"],
            "round_number": number,
            "weight_volume_bp": wv,
            "weight_toxicity_bp": wt,
            "weight_ownership_bp": wo,
            "status": "DRAFTING",
            "facilitator_user_id": actor.user_id,
            "allocated_share_total_pct": ZERO,
            "orphan_share_pct": ZERO,
            "settled_share_pct": ZERO,
            "accept_share_pct": ZERO,
            "share_count": 0,
            "balloted_count": 0,
            "adopted_at": None,
            "revision_note": None,
        }
    )
    store.allocation_rounds[round_["id"]] = round_
    # A new round supersedes whatever open round the site already had.
    for other in existing:
        if other["status"] in ("DRAFTING", "BALLOTING", "FAILED"):
            txn.watch(other)
            other["status"] = "SUPERSEDED"
    for prp in candidates:
        _mint_share(round_, prp)
    derive.recompute_provisional(site, round_)
    # Opening a round increments the site's own version even though no field of
    # the site changes (PRD 2.7/3.6).
    txn.force(site)
    return common.respond(round_, serialize.allocation_round, 201)


@bp.post("/allocation-rounds/<round_id>/balloting")
def open_balloting(round_id):
    require(K.ROLE_FACILITATOR)
    shape.get_body()
    round_ = common.get_round(round_id)
    site = store.sites[round_["site_id"]]
    # A single-party allocation is not a negotiation.
    common.state(round_["status"] == "DRAFTING" and round_["share_count"] >= 2)
    common.deny_deleted(site)
    if not derive.has_allocation_basis(site, round_):
        raise ApiError("ERR_NO_ALLOCATION_BASIS")

    txn.watch(round_)
    round_["status"] = "BALLOTING"
    return common.respond(round_, serialize.allocation_round)


@bp.post("/allocation-rounds/<round_id>/ballots")
def cast_ballot(round_id):
    actor = require(K.ROLE_PRP)
    body = shape.get_body()
    ballot = shape.enum_field(body, "ballot", K.BALLOTS)
    rationale = shape.str_field(body, "ballot_rationale", required=False)
    round_ = common.get_round(round_id)
    site = store.sites[round_["site_id"]]
    share = derive.share_for(round_["id"], actor.user_id)
    if share is None:
        raise ApiError("ERR_ACTOR_IDENTITY_MISMATCH")
    prp = store.prps[share["prp_id"]]
    common.state(round_["status"] == "BALLOTING")
    common.deny_deleted(site)
    if prp["status"] not in ("PARTICIPATING", "RECALCITRANT"):
        raise ApiError("ERR_PARTY_NOT_PARTICIPATING")
    if share["ballot"] is not None:
        raise ApiError("ERR_BALLOT_ALREADY_CAST")

    txn.watch(share)
    share["ballot"] = ballot
    share["ballot_rationale"] = rationale
    share["ballot_cast_at"] = logical_clock.now()
    derive.recompute_round_counters(round_)

    if round_["balloted_count"] == round_["share_count"]:
        threshold = frac(Decimal(K.ADOPTION_THRESHOLD_PCT))
        if frac(round_["accept_share_pct"]) >= threshold:
            derive.adopt_round(site, round_)
        else:
            txn.watch(round_)
            round_["status"] = "FAILED"
    return common.respond(share, serialize.allocation_share)


@bp.post("/allocation-rounds/<round_id>/reopening")
def reopen_round(round_id):
    require(K.ROLE_FACILITATOR)
    body = shape.get_body()
    note = shape.str_field(body, "revision_note")
    round_ = common.get_round(round_id)
    site = store.sites[round_["site_id"]]
    common.state(round_["status"] in ("BALLOTING", "FAILED"))
    common.deny_deleted(site)

    for share in derive.round_shares(round_["id"]):
        txn.watch(share)
        share["ballot"] = None
        share["ballot_rationale"] = None
        share["ballot_cast_at"] = None
    # Parties that entered the candidate set since the round opened join now.
    held = {s["prp_id"] for s in derive.round_shares(round_["id"])}
    for prp in _candidates(site):
        if prp["id"] not in held:
            _mint_share(round_, prp)
    txn.watch(round_)
    round_["status"] = "DRAFTING"
    round_["revision_note"] = note
    derive.recompute_provisional(site, round_)
    return common.respond(round_, serialize.allocation_round)
