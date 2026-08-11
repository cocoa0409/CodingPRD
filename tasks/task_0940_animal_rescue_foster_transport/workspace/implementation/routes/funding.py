"""Contributions and the partner-commitment slot ledger."""

from flask import Blueprint, request

import auth
import clock
import derive
import envelope
import gates
from errors import ApiError
from routing import listing, must, must_fk, query_filters
from store import DB, ordered, touch
from validation import Field, parse_body

bp = Blueprint("funding", __name__)


# =====================================================================
#  Contributions
# =====================================================================

@bp.post("/rescue/contributions")
def record_contribution():
    auth.authenticate(["PlatformAdmin", "FinanceOfficer"])
    body = parse_body(request, [
        Field("donor_person_id", "string", required=True),
        Field("amount_cents", "integer", required=True, fmt="gt0"),
        Field("donor_reference", "string", required=True),
        Field("designated_animal_id", "string", default=None),
        Field("designated_program", "string", default="NONE", enum="designated_program"),
        Field("restriction_category", "string", default="UNRESTRICTED", enum="restriction_category"),
    ])
    must("Person", body["donor_person_id"])
    designated = must_fk("Animal", body["designated_animal_id"])
    gates.check_gate1(gates.gate1_org_id(animal=designated))
    contribution = DB.insert("Contribution", {
        "donor_person_id": body["donor_person_id"],
        "designated_animal_id": body["designated_animal_id"],
        "designated_program": body["designated_program"],
        "restriction_category": body["restriction_category"],
        "donor_reference": body["donor_reference"],
        "amount_cents": body["amount_cents"],
        "applied_cents": 0,
        "released_cents": 0,
        "status": "RECEIVED",
        "redesignation_count": 0,
    })
    # The organization's two money figures are derived, never stored
    # independently (PRD 3.9), so recording the gift moves them by derivation.
    return envelope.created(derive.contribution(contribution))


@bp.get("/rescue/contributions/<contribution_id>")
def read_contribution(contribution_id):
    auth.authenticate(["PlatformAdmin", "FinanceOfficer"])
    return envelope.ok(derive.contribution(must("Contribution", contribution_id)))


@bp.get("/rescue/contributions")
def list_contributions():
    auth.authenticate(["PlatformAdmin", "FinanceOfficer"])
    return listing("Contribution", DB.all("Contribution"),
                   query_filters(["donor_person_id", "designated_animal_id",
                                  "designated_program", "restriction_category", "status"]))


@bp.post("/rescue/contributions/<contribution_id>/redesignate")
def redesignate(contribution_id):
    auth.authenticate(["PlatformAdmin", "FinanceOfficer"])
    body = parse_body(request, [
        Field("designated_animal_id", "string", default=None),
        Field("designated_program", "string", default="NONE", enum="designated_program"),
        Field("restriction_category", "string", default="UNRESTRICTED",
              enum="restriction_category"),
    ])
    contribution = must("Contribution", contribution_id)
    must_fk("Animal", body["designated_animal_id"])
    current_animal = DB.get("Animal", contribution["designated_animal_id"]) \
        if contribution["designated_animal_id"] else None
    gates.check_gate1(gates.gate1_org_id(animal=current_animal))
    # A self-loop on RECEIVED, legal only before a single cent has been applied.
    if contribution["status"] != "RECEIVED" or contribution["applied_cents"] != 0:
        raise ApiError("ERR_INVALID_STATE",
                       "A gift that has already been drawn against cannot be redesignated.")
    contribution["designated_animal_id"] = body["designated_animal_id"]
    contribution["designated_program"] = body["designated_program"]
    contribution["restriction_category"] = body["restriction_category"]
    contribution["redesignation_count"] += 1
    touch(contribution)
    return envelope.ok(derive.contribution(contribution))


# =====================================================================
#  Partner commitments
# =====================================================================

@bp.post("/rescue/partner-commitments")
def create_commitment():
    auth.authenticate(["PlatformAdmin", "TransportDispatcher"])
    body = parse_body(request, [
        Field("organization_id", "string", required=True),
        Field("species", "string", required=True, enum="species"),
        Field("slots_total", "integer", required=True, fmt="gte1"),
        Field("expires_at", "datetime", required=True),
    ])
    must("Organization", body["organization_id"])
    gates.check_gate1(body["organization_id"])
    commitment = DB.insert("PartnerCommitment", {
        "organization_id": body["organization_id"],
        "species": body["species"],
        "slots_total": body["slots_total"],
        "expires_at": body["expires_at"],              # (b) echoed byte-verbatim
        "slots_drawn": 0,
        "slots_released": 0,
        "slots_open": body["slots_total"],
        "status": "OPEN",
    })
    return envelope.created(derive.partner_commitment(commitment))


@bp.get("/rescue/partner-commitments/<commitment_id>")
def read_commitment(commitment_id):
    ctx = auth.authenticate(["PlatformAdmin", "TransportDispatcher", "PartnerRescue"])
    commitment = DB.get("PartnerCommitment", commitment_id)
    if commitment is not None:
        auth.own_if(ctx, "PartnerRescue", commitment["organization_id"])
    return envelope.ok(derive.partner_commitment(must("PartnerCommitment", commitment_id)))


@bp.get("/rescue/partner-commitments")
def list_commitments():
    ctx = auth.authenticate(["PlatformAdmin", "TransportDispatcher", "PartnerRescue"])
    rows = DB.all("PartnerCommitment")
    if ctx.role == "PartnerRescue":
        rows = [c for c in rows if c["organization_id"] == ctx.user_id]
    return listing("PartnerCommitment", rows,
                   query_filters(["organization_id", "species", "status"]))


@bp.post("/rescue/partner-commitments/expire-sweep")
def expire_sweep():
    auth.authenticate(["PlatformAdmin", "TransportDispatcher"])
    parse_body(request, [])
    # Gate 1: the sweep names no single target organization, so it is ungated.
    expired_ids = []
    forfeited = 0
    for commitment in ordered(DB.all("PartnerCommitment")):
        if commitment["status"] not in ("OPEN", "PARTIALLY_DRAWN"):
            continue
        # The sweep visits every commitment whose expires_at the clock has
        # STRICTLY passed.
        if not clock.now() > clock.parse(commitment["expires_at"]):
            continue
        remaining = commitment["slots_open"]
        commitment["slots_released"] += remaining
        commitment["slots_open"] = 0
        commitment["status"] = "EXPIRED"
        touch(commitment)
        expired_ids.append(commitment["id"])
        forfeited += remaining
    return envelope.ok({
        "expired_count": len(expired_ids),
        "expired_commitment_ids": expired_ids,
        "slots_forfeited": forfeited,
    })
