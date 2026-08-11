"""LienRelease endpoints."""

from datetime import date

from flask import Blueprint

import db
from db import (
    lien_store, lien_release_store, escrow_file_store, make_common_fields, touch,
    get_logical_now,
)
from errors import (
    ApiError, ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_INVALID_TRANSITION,
    ERR_QUOTE_WINDOW_OPEN, ERR_FORBIDDEN_IDENTITY, ERR_FILE_ON_HOLD, ERR_ALREADY_TERMINAL,
)
from middleware import require_roles, require_lender_identity, ALL_ROLES
from response import success_object, success_list
from services.calculations import compute_effective_payoff
from services.escrow import (
    recompute_posture, try_bubble_cleared, try_bubble_funded, lien_return_to_discovered_if_orphaned,
)
from validators import get_body, require_fields, require_positive_int, require_enum, require_date_string

bp = Blueprint("releases", __name__)

TERMINAL_STATUSES = {"CANCELLED", "VERIFIED"}
VALID_PAYOFF_BASES = ["FLAT", "PER_DIEM"]


def _get_release_checked(id):
    r = lien_release_store.get(id)
    if not r:
        raise ApiError(ERR_NOT_FOUND, "LienRelease not found.", 404)
    return r


def _check_parent_mutable_via_lien(release):
    lien = lien_store.get(release["lien_id"])
    if lien:
        ef = escrow_file_store.get(lien["escrow_file_id"])
        if ef:
            if ef["status"] == "ON_HOLD":
                raise ApiError(ERR_FILE_ON_HOLD, "EscrowFile is ON_HOLD.", 409)
            if ef["status"] in TERMINAL_STATUSES:
                raise ApiError(ERR_ALREADY_TERMINAL, f"EscrowFile is {ef['status']}.", 409)


@bp.route("/api/liens/<id>/releases", methods=["POST"])
def create_release(id):
    user_id, role = require_roles(["EscrowOfficer"])
    ln = lien_store.get(id)
    if not ln:
        raise ApiError(ERR_NOT_FOUND, "Lien not found.", 404)

    # Check parent escrow file state
    ef = escrow_file_store.get(ln["escrow_file_id"])
    if ef:
        if ef["status"] == "ON_HOLD":
            raise ApiError(ERR_FILE_ON_HOLD, "EscrowFile is ON_HOLD.", 409)
        if ef["status"] in TERMINAL_STATUSES:
            raise ApiError(ERR_ALREADY_TERMINAL, f"EscrowFile is {ef['status']}.", 409)

    # Quote window check first (PRD §3.4): a QUOTED release with an open window
    # implies the lien is RELEASE_PENDING, so this named rejection must be
    # evaluated before the lien-state gate or it could never fire.
    today = get_logical_now().date()
    for r in lien_release_store.values():
        if r["lien_id"] == id and r["status"] == "QUOTED":
            qd = date.fromisoformat(r["quote_date"])
            gtd = date.fromisoformat(r["good_through_date"])
            if qd <= today <= gtd:
                raise ApiError(ERR_QUOTE_WINDOW_OPEN, "Another QUOTED release window covers today.", 409)

    if ln["status"] != "DISCOVERED":
        raise ApiError(ERR_INVALID_TRANSITION, f"Cannot request release on lien in status {ln['status']}.", 409)

    fields = make_common_fields()
    release = {
        **fields,
        "lien_id": id,
        "status": "REQUESTED",
        "payoff_basis": None,
        "quoted_payoff_cents": None,
        "per_diem_cents": None,
        "quote_date": None,
        "good_through_date": None,
    }
    lien_release_store[release["id"]] = release

    # Lien DISCOVERED -> RELEASE_PENDING
    ln["status"] = "RELEASE_PENDING"
    touch(ln)

    # Posture recompute
    if ef:
        recompute_posture(ef)
        touch(ef)

    return success_object(release, 201)


@bp.route("/api/liens/<id>/releases", methods=["GET"])
def list_releases(id):
    user_id, role = require_roles(ALL_ROLES)
    ln = lien_store.get(id)
    if not ln:
        raise ApiError(ERR_NOT_FOUND, "Lien not found.", 404)

    items = [r for r in lien_release_store.values() if r["lien_id"] == id]
    items.sort(key=lambda x: x["created_at"])

    from flask import request
    try:
        limit = max(1, min(100, int(request.args.get("limit", 10))))
    except (ValueError, TypeError):
        limit = 10
    try:
        offset = max(0, int(request.args.get("offset", 0)))
    except (ValueError, TypeError):
        offset = 0
    total = len(items)
    items = items[offset:offset + limit]
    return success_list(items, limit, offset, total)


@bp.route("/api/releases/<id>/quote", methods=["POST"])
def quote_release(id):
    r = _get_release_checked(id)
    _check_parent_mutable_via_lien(r)

    # LenderRep identity check
    lien = lien_store.get(r["lien_id"])
    user_id, role = require_lender_identity(lien["lienor_party_id"])

    if r["status"] != "REQUESTED":
        raise ApiError(ERR_INVALID_TRANSITION, f"Cannot quote release in status {r['status']}.", 409)

    body = get_body()
    require_fields(body, ["payoff_basis", "quoted_payoff_cents", "good_through_date"], ["per_diem_cents"])

    payoff_basis = require_enum(body["payoff_basis"], "payoff_basis", VALID_PAYOFF_BASES)
    quoted_payoff = require_positive_int(body["quoted_payoff_cents"], "quoted_payoff_cents")
    good_through_date = require_date_string(body["good_through_date"], "good_through_date")
    per_diem = body.get("per_diem_cents")

    if payoff_basis == "PER_DIEM":
        if per_diem is None:
            raise ApiError(ERR_INVALID_REQUEST, "per_diem_cents is required for PER_DIEM.", 400)
        require_positive_int(per_diem, "per_diem_cents")
    else:
        if per_diem is not None:
            raise ApiError(ERR_INVALID_REQUEST, "per_diem_cents must be omitted for FLAT.", 400)

    r["payoff_basis"] = payoff_basis
    r["quoted_payoff_cents"] = quoted_payoff
    r["per_diem_cents"] = per_diem if payoff_basis == "PER_DIEM" else None
    r["quote_date"] = get_logical_now().strftime("%Y-%m-%d")
    r["good_through_date"] = good_through_date
    r["status"] = "QUOTED"
    touch(r)

    return success_object(r)


@bp.route("/api/releases/<id>/receive-release", methods=["POST"])
def receive_release(id):
    r = _get_release_checked(id)
    _check_parent_mutable_via_lien(r)

    lien = lien_store.get(r["lien_id"])
    user_id, role = require_lender_identity(lien["lienor_party_id"])

    if r["status"] != "QUOTED":
        raise ApiError(ERR_INVALID_TRANSITION, f"Cannot receive release in status {r['status']}.", 409)

    r["status"] = "RELEASE_RECEIVED"
    touch(r)
    return success_object(r)


@bp.route("/api/releases/<id>/file", methods=["POST"])
def file_release(id):
    user_id, role = require_roles(["EscrowOfficer"])
    r = _get_release_checked(id)
    _check_parent_mutable_via_lien(r)

    if r["status"] != "RELEASE_RECEIVED":
        raise ApiError(ERR_INVALID_TRANSITION, f"Cannot file release in status {r['status']}.", 409)

    r["status"] = "FILED"
    touch(r)
    return success_object(r)


@bp.route("/api/releases/<id>/record", methods=["POST"])
def record_release(id):
    user_id, role = require_roles(["EscrowOfficer"])
    r = _get_release_checked(id)
    _check_parent_mutable_via_lien(r)

    if r["status"] != "FILED":
        raise ApiError(ERR_INVALID_TRANSITION, f"Cannot record release in status {r['status']}.", 409)

    # Check record_date <= good_through_date
    today = get_logical_now().date()
    gtd = date.fromisoformat(r["good_through_date"])
    if today > gtd:
        raise ApiError(ERR_INVALID_TRANSITION, "Quote has expired.", 409)

    # Compute effective payoff
    effective_payoff = compute_effective_payoff(r, today)

    r["status"] = "RECORDED"
    touch(r)

    # Freeze payoff onto lien
    lien = lien_store.get(r["lien_id"])
    if lien:
        lien["amount_paid_cents"] = effective_payoff
        lien["outstanding_cents"] = lien["original_amount_cents"] - effective_payoff
        lien["status"] = "RELEASED"
        touch(lien)

        # Posture recompute + bubble
        ef = escrow_file_store.get(lien["escrow_file_id"])
        if ef:
            recompute_posture(ef)
            touch(ef)
            try_bubble_cleared(ef)
            try_bubble_funded(ef)

    return success_object(r)


@bp.route("/api/releases/<id>/void", methods=["POST"])
def void_release(id):
    user_id, role = require_roles(["EscrowOfficer"])
    r = _get_release_checked(id)
    _check_parent_mutable_via_lien(r)

    if r["status"] not in ("REQUESTED", "QUOTED", "RELEASE_RECEIVED", "FILED"):
        raise ApiError(ERR_INVALID_TRANSITION, f"Cannot void release in status {r['status']}.", 409)

    r["status"] = "VOIDED"
    touch(r)

    # Check if lien should return to DISCOVERED
    lien_return_to_discovered_if_orphaned(r["lien_id"])

    return success_object(r)
