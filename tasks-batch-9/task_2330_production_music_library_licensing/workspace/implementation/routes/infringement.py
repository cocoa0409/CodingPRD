"""FingerprintMatch ingest and InfringementClaim lifecycle (PRD §3.8)."""

from decimal import Decimal

from flask import Blueprint, request

from db import DB
from errors import fail
from middleware import (
    body,
    opt_int,
    req_bool,
    req_enum,
    req_int,
    req_number,
    req_string,
    require_role,
)
from response import object_response, page_response, pagination
from routes.common import PREFIX, require_state
from services import calc
from services.cascade import append_ledger, bump_once, unblock_composition
from services.derive import lookup, rows, serialize_claim, serialize_match

bp = Blueprint("infringement", __name__)

PLATFORMS = ("UGC_VIDEO", "BROADCAST", "THEATRICAL", "PODCAST")
BASES = ("STATUTORY", "NEGOTIATED")


@bp.post(PREFIX + "/fingerprint-matches")
def create_match():
    data = body()
    composition_id = req_string(data, "composition_id")
    platform = req_enum(data, "source_platform", PLATFORMS)
    reference = req_string(data, "source_reference", allow_empty=False)
    matched_seconds = req_int(data, "matched_seconds", 1, 7200)
    confidence = req_number(data, "confidence_pct", 0, 100)

    composition = lookup("compositions", composition_id)             # 3
    require_role("CatalogAdmin")                                     # 4

    row = DB.new_row(versioned=False)
    row.update(
        {
            "composition_id": composition["id"],
            "source_platform": platform,
            "source_reference": reference,
            "matched_seconds": matched_seconds,
            "_confidence_pct": calc.dp1(confidence),
            "detected_at": DB.now_iso,
        }
    )
    DB.matches[row["id"]] = row
    return object_response(serialize_match(row), 201)


@bp.get(PREFIX + "/fingerprint-matches/<match_id>")
def get_match(match_id):
    row = lookup("matches", match_id)
    require_role("CatalogAdmin", "RightsManager")
    return object_response(serialize_match(row))


@bp.get(PREFIX + "/fingerprint-matches")
def list_matches():
    limit, offset = pagination(request.args)
    require_role("CatalogAdmin", "RightsManager")
    result = rows("matches")
    for name in ("composition_id", "source_platform"):
        wanted = request.args.get(name)
        if wanted not in (None, ""):
            result = [r for r in result if r[name] == wanted]
    return page_response(result, limit, offset, serialize_match)


@bp.post(PREFIX + "/infringement-claims")
def create_claim():
    data = body()
    match_id = req_string(data, "fingerprint_match_id")
    match = lookup("matches", match_id)                              # 3
    require_role("RightsManager")                                    # 4

    if match["_confidence_pct"] < calc.CLAIM_CONFIDENCE_MIN_PCT:      # 41
        fail(
            "ERR_CONFIDENCE_BELOW_CLAIM_THRESHOLD",
            "fingerprint confidence is below the claim threshold.",
        )
    for other in rows("claims"):                                     # 42
        if other["fingerprint_match_id"] == match["id"]:
            fail("ERR_MATCH_ALREADY_CLAIMED", "this detection is already claimed.")

    statutory = calc.statutory_amount(
        match["matched_seconds"], match["source_platform"], match["_confidence_pct"]
    )
    row = DB.new_row()
    row.update(
        {
            "composition_id": match["composition_id"],
            "fingerprint_match_id": match["id"],
            "status": "DETECTED",
            "statutory_amount_cents": statutory,
            "settlement_floor_cents": calc.settlement_floor(statutory),
            "settlement_amount_cents": None,
            "settlement_basis": None,
            "settlement_collected": False,
            "composer_share_cents": None,
            "notice_channel": None,
            "dispute_note": None,
            "escalation_note": None,
            "noticed_at": None,
            "settled_at": None,
        }
    )
    DB.claims[row["id"]] = row
    return object_response(serialize_claim(row), 201)


@bp.get(PREFIX + "/infringement-claims/<claim_id>")
def get_claim(claim_id):
    row = lookup("claims", claim_id)
    require_role("RightsManager", "CatalogAdmin", "RoyaltyAccountant")
    return object_response(serialize_claim(row))


@bp.get(PREFIX + "/infringement-claims")
def list_claims():
    limit, offset = pagination(request.args)
    require_role("RightsManager", "CatalogAdmin", "RoyaltyAccountant")
    result = rows("claims")
    for name in ("composition_id", "fingerprint_match_id", "status"):
        wanted = request.args.get(name)
        if wanted not in (None, ""):
            result = [r for r in result if r[name] == wanted]
    return page_response(result, limit, offset, serialize_claim)


@bp.post(PREFIX + "/infringement-claims/<claim_id>/notice")
def notice(claim_id):
    data = body()
    channel = req_string(data, "notice_channel", allow_empty=False)
    row = lookup("claims", claim_id)
    require_role("RightsManager")
    require_state(row, "status", ("DETECTED",), "claim")
    match = DB.matches[row["fingerprint_match_id"]]
    if match["_confidence_pct"] < calc.NOTICE_CONFIDENCE_MIN_PCT:      # 43
        fail(
            "ERR_CONFIDENCE_BELOW_NOTICE_THRESHOLD",
            "fingerprint confidence is below the notice threshold.",
        )
    row["status"] = "NOTICED"
    row["notice_channel"] = channel
    row["noticed_at"] = DB.now_iso
    bump_once(row)
    composition = DB.compositions.get(row["composition_id"])
    if composition is not None and composition["availability_status"] == "AVAILABLE":
        composition["availability_status"] = "RESTRICTED"
        bump_once(composition)
    return object_response(serialize_claim(row))


@bp.post(PREFIX + "/infringement-claims/<claim_id>/dispute")
def dispute(claim_id):
    data = body()
    note = req_string(data, "dispute_note", allow_empty=False)
    row = lookup("claims", claim_id)
    require_role("RightsManager")
    require_state(row, "status", ("NOTICED",), "claim")
    row["status"] = "DISPUTED"
    row["dispute_note"] = note
    bump_once(row)
    return object_response(serialize_claim(row))


@bp.post(PREFIX + "/infringement-claims/<claim_id>/settle")
def settle(claim_id):
    data = body()
    basis = req_enum(data, "settlement_basis", BASES)
    payment_received = req_bool(data, "payment_received")
    negotiated = opt_int(data, "negotiated_amount_cents", 0, None)
    row = lookup("claims", claim_id)
    require_role("RightsManager")
    require_state(row, "status", ("NOTICED", "DISPUTED"), "claim")

    if basis == "NEGOTIATED":                                          # 44
        if negotiated is None or negotiated < row["settlement_floor_cents"]:
            fail(
                "ERR_SETTLEMENT_BELOW_FLOOR",
                "a negotiated settlement may not fall below the floor.",
            )
        amount = negotiated
    else:
        amount = row["statutory_amount_cents"]

    composition = DB.compositions.get(row["composition_id"])
    agreement = (
        DB.agreements.get(composition["agreement_id"]) if composition is not None else None
    )
    share_pct = agreement["_sync_fee_share_pct"] if agreement is not None else Decimal("0")
    composer_share = calc.cents(Decimal(amount) * share_pct / Decimal(100))

    row["status"] = "SETTLED"
    row["settlement_basis"] = basis
    row["settlement_amount_cents"] = amount
    row["settlement_collected"] = payment_received
    row["composer_share_cents"] = composer_share
    row["settled_at"] = DB.now_iso
    bump_once(row)

    if composition is not None:
        append_ledger(
            composition["composer_id"],
            "SETTLEMENT",
            row["id"],
            composer_share,
            "INFRINGEMENT_SETTLEMENT",
            cash=bool(payment_received),
        )
    unblock_composition(row)
    return object_response(serialize_claim(row))


@bp.post(PREFIX + "/infringement-claims/<claim_id>/escalate")
def escalate(claim_id):
    data = body()
    note = req_string(data, "escalation_note", allow_empty=False)
    row = lookup("claims", claim_id)
    require_role("RightsManager")
    require_state(row, "status", ("DISPUTED",), "claim")
    row["status"] = "ESCALATED"
    row["escalation_note"] = note
    bump_once(row)
    unblock_composition(row)
    return object_response(serialize_claim(row))
