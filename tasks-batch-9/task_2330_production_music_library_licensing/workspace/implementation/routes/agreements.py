"""ComposerAgreement endpoints (PRD §3.1)."""

from decimal import Decimal

from flask import Blueprint, request

from db import DB
from errors import fail
from middleware import (
    body,
    is_role,
    opt_bool,
    opt_int,
    opt_number,
    req_enum,
    req_int,
    req_number,
    req_string,
    require_role,
    user_id,
)
from response import object_response, page_response, pagination
from routes.common import PREFIX, guard_composer, require_state
from services import calc
from services.cascade import append_ledger, bump_once, terminate_agreement
from services.derive import lookup, rows, serialize_agreement

bp = Blueprint("agreements", __name__)

AGREEMENT_TYPES = ("WORK_FOR_HIRE", "ROYALTY_SPLIT")
EXCLUSIVITY = ("EXCLUSIVE", "NON_EXCLUSIVE")
HUNDRED = Decimal("100.00")


@bp.post(PREFIX + "/composer-agreements")
def create_agreement():
    data = body()
    composer_id = req_string(data, "composer_id")
    agreement_type = req_enum(data, "agreement_type", AGREEMENT_TYPES)
    writer = req_number(data, "writer_share_pct", 0, 100)
    publisher = req_number(data, "publisher_share_pct", 0, 100)
    sync_share = req_number(data, "sync_fee_share_pct", 0, 100)
    buyout = opt_int(data, "buyout_fee_cents", 0, None, 0)
    exclusivity = req_enum(data, "exclusivity", EXCLUSIVITY)
    holdback = opt_int(data, "holdback_days", 0, 365, 0)
    advance = opt_int(data, "advance_cents", 0, None, 0)
    blanket_opt_in = opt_bool(data, "blanket_opt_in", True)

    composer = lookup("composers", composer_id)                    # 3 body FK
    require_role("RightsManager")                                  # 4 role

    if calc.dp2(writer) + calc.dp2(publisher) != HUNDRED:           # 11
        fail("ERR_SHARE_SPLIT_NOT_100", "writer plus publisher share must be 100.00.")
    if agreement_type == "WORK_FOR_HIRE":                           # 12
        if calc.dp2(sync_share) != Decimal("0.00") or buyout == 0:
            fail(
                "ERR_WORK_FOR_HIRE_TERMS_INVALID",
                "work-for-hire needs a buyout and no sync-fee share.",
            )
    elif buyout != 0:
        fail("ERR_WORK_FOR_HIRE_TERMS_INVALID", "a royalty split may not carry a buyout.")

    row = DB.new_row()
    row.update(
        {
            "composer_id": composer["id"],
            "agreement_type": agreement_type,
            "status": "DRAFT",
            "_writer_share_pct": calc.dp2(writer),
            "_publisher_share_pct": calc.dp2(publisher),
            "_sync_fee_share_pct": calc.dp2(sync_share),
            "buyout_fee_cents": buyout,
            "exclusivity": exclusivity,
            "holdback_days": holdback,
            "advance_cents": advance,
            "blanket_opt_in": blanket_opt_in,
            "_pending_writer_share_pct": None,
            "_pending_publisher_share_pct": None,
            "_pending_sync_fee_share_pct": None,
            "pending_holdback_days": None,
            "amendment_round": 0,
            "signed_at": None,
            "terminated_at": None,
        }
    )
    DB.agreements[row["id"]] = row
    return object_response(serialize_agreement(row), 201)


@bp.get(PREFIX + "/composer-agreements/<agreement_id>")
def get_agreement(agreement_id):
    row = lookup("agreements", agreement_id)
    require_role("CatalogAdmin", "RightsManager", "RoyaltyAccountant", "Composer")
    guard_composer(row["composer_id"])
    return object_response(serialize_agreement(row))


@bp.get(PREFIX + "/composer-agreements")
def list_agreements():
    limit, offset = pagination(request.args)
    require_role("CatalogAdmin", "RightsManager", "RoyaltyAccountant", "Composer")
    args = request.args
    if is_role("Composer"):
        wanted = args.get("composer_id")
        if wanted not in (None, "") and wanted != user_id():
            fail("ERR_COMPOSER_IDENTITY_MISMATCH", "Composers may list only their own rows.")
    result = rows("agreements")
    if is_role("Composer"):
        result = [r for r in result if r["composer_id"] == user_id()]
    for name in ("composer_id", "status", "agreement_type"):
        wanted = args.get(name)
        if wanted not in (None, ""):
            result = [r for r in result if r[name] == wanted]
    return page_response(result, limit, offset, serialize_agreement)


@bp.post(PREFIX + "/composer-agreements/<agreement_id>/submit-for-signature")
def submit_for_signature(agreement_id):
    row = lookup("agreements", agreement_id)
    require_role("RightsManager")
    require_state(row, "status", ("DRAFT",), "agreement")
    row["status"] = "PENDING_SIGNATURE"
    bump_once(row)
    return object_response(serialize_agreement(row))


@bp.post(PREFIX + "/composer-agreements/<agreement_id>/sign")
def sign_agreement(agreement_id):
    data = body()
    req_string(data, "signature_name", allow_empty=False)
    row = lookup("agreements", agreement_id)
    require_role("Composer")
    guard_composer(row["composer_id"])
    require_state(row, "status", ("PENDING_SIGNATURE",), "agreement")

    row["status"] = "ACTIVE"
    row["signed_at"] = DB.now_iso
    bump_once(row)
    if row["advance_cents"] > 0:
        append_ledger(
            row["composer_id"],
            "ADVANCE",
            row["id"],
            -row["advance_cents"],
            "SIGNING_ADVANCE",
            cash=True,
        )
    if row["agreement_type"] == "WORK_FOR_HIRE" and row["buyout_fee_cents"] > 0:
        append_ledger(
            row["composer_id"],
            "ADJUSTMENT",
            None,
            row["buyout_fee_cents"],
            "WORK_FOR_HIRE_BUYOUT",
            cash=True,
        )
    return object_response(serialize_agreement(row))


@bp.post(PREFIX + "/composer-agreements/<agreement_id>/amendments")
def propose_amendment(agreement_id):
    data = body()
    writer = req_number(data, "proposed_writer_share_pct", 0, 100)
    publisher = req_number(data, "proposed_publisher_share_pct", 0, 100)
    sync_share = req_number(data, "proposed_sync_fee_share_pct", 0, 100)
    holdback = opt_int(data, "proposed_holdback_days", 0, 365)
    row = lookup("agreements", agreement_id)
    require_role("RightsManager")
    require_state(row, "status", ("ACTIVE",), "agreement")
    if calc.dp2(writer) + calc.dp2(publisher) != HUNDRED:            # 11
        fail("ERR_SHARE_SPLIT_NOT_100", "proposed shares must sum to 100.00.")
    if row["amendment_round"] >= 3:                                  # 31
        fail("ERR_AMENDMENT_LIMIT_REACHED", "three amendments have already been accepted.")

    row["status"] = "AMENDMENT_PENDING"
    row["_pending_writer_share_pct"] = calc.dp2(writer)
    row["_pending_publisher_share_pct"] = calc.dp2(publisher)
    row["_pending_sync_fee_share_pct"] = calc.dp2(sync_share)
    row["pending_holdback_days"] = holdback
    bump_once(row)
    return object_response(serialize_agreement(row))


@bp.post(PREFIX + "/composer-agreements/<agreement_id>/amendment-decision")
def amendment_decision(agreement_id):
    data = body()
    decision = req_enum(data, "decision", ("ACCEPT", "REJECT"))
    row = lookup("agreements", agreement_id)
    require_role("Composer")
    guard_composer(row["composer_id"])
    require_state(row, "status", ("AMENDMENT_PENDING",), "agreement")

    if decision == "ACCEPT":
        if row["_pending_writer_share_pct"] is not None:
            row["_writer_share_pct"] = row["_pending_writer_share_pct"]
        if row["_pending_publisher_share_pct"] is not None:
            row["_publisher_share_pct"] = row["_pending_publisher_share_pct"]
        if row["_pending_sync_fee_share_pct"] is not None:
            row["_sync_fee_share_pct"] = row["_pending_sync_fee_share_pct"]
        if row["pending_holdback_days"] is not None:
            row["holdback_days"] = row["pending_holdback_days"]
        row["amendment_round"] = row["amendment_round"] + 1
    row["_pending_writer_share_pct"] = None
    row["_pending_publisher_share_pct"] = None
    row["_pending_sync_fee_share_pct"] = None
    row["pending_holdback_days"] = None
    row["status"] = "ACTIVE"
    bump_once(row)
    return object_response(serialize_agreement(row))


@bp.post(PREFIX + "/composer-agreements/<agreement_id>/terminate")
def terminate(agreement_id):
    data = body()
    reason = req_string(data, "reason", allow_empty=False)
    row = lookup("agreements", agreement_id)
    require_role("RightsManager")
    require_state(row, "status", ("ACTIVE", "AMENDMENT_PENDING"), "agreement")
    terminate_agreement(row, reason)
    return object_response(serialize_agreement(row))
