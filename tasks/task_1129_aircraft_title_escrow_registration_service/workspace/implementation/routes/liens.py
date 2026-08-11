"""Lien endpoints."""

from flask import Blueprint, request

from db import lien_store, lien_release_store, escrow_file_store, make_common_fields, touch
from errors import (
    ApiError, ERR_NOT_FOUND, ERR_INVALID_TRANSITION, ERR_FILE_ON_HOLD, ERR_ALREADY_TERMINAL,
)
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list
from services.escrow import recompute_posture

bp = Blueprint("liens", __name__)

TERMINAL_STATUSES = {"CANCELLED", "VERIFIED"}


def _parse_limit():
    try:
        v = int(request.args.get("limit", 10))
    except (ValueError, TypeError):
        v = 10
    return max(1, min(100, v))


def _parse_offset():
    try:
        v = int(request.args.get("offset", 0))
    except (ValueError, TypeError):
        v = 0
    return max(0, v)


def _get_lien_checked(id):
    ln = lien_store.get(id)
    if not ln:
        raise ApiError(ERR_NOT_FOUND, "Lien not found.", 404)
    return ln


def _check_parent_mutable(ln):
    ef = escrow_file_store.get(ln["escrow_file_id"])
    if ef:
        if ef["status"] == "ON_HOLD":
            raise ApiError(ERR_FILE_ON_HOLD, "EscrowFile is ON_HOLD.", 409)
        if ef["status"] in TERMINAL_STATUSES:
            raise ApiError(ERR_ALREADY_TERMINAL, f"EscrowFile is {ef['status']}.", 409)


@bp.route("/api/liens", methods=["GET"])
def list_liens():
    user_id, role = require_roles(ALL_ROLES)
    items = list(lien_store.values())

    escrow_file_id = request.args.get("escrow_file_id")
    aircraft_id = request.args.get("aircraft_id")
    title_search_id = request.args.get("title_search_id")
    lienor_party_id = request.args.get("lienor_party_id")
    status = request.args.get("status")

    if escrow_file_id:
        items = [l for l in items if l["escrow_file_id"] == escrow_file_id]
    if aircraft_id:
        items = [l for l in items if l["aircraft_id"] == aircraft_id]
    if title_search_id:
        items = [l for l in items if l["title_search_id"] == title_search_id]
    if lienor_party_id:
        items = [l for l in items if l["lienor_party_id"] == lienor_party_id]
    if status:
        items = [l for l in items if l["status"] == status]

    items.sort(key=lambda x: x["created_at"])
    limit = _parse_limit()
    offset = _parse_offset()
    total = len(items)
    items = items[offset:offset + limit]
    return success_list(items, limit, offset, total)


@bp.route("/api/liens/<id>", methods=["GET"])
def get_lien(id):
    user_id, role = require_roles(ALL_ROLES)
    ln = _get_lien_checked(id)
    return success_object(ln)


@bp.route("/api/liens/<id>/dispute", methods=["POST"])
def dispute_lien(id):
    user_id, role = require_roles(["EscrowOfficer"])
    ln = _get_lien_checked(id)
    _check_parent_mutable(ln)

    if ln["status"] != "DISCOVERED":
        raise ApiError(ERR_INVALID_TRANSITION, f"Cannot dispute lien in status {ln['status']}.", 409)

    ln["status"] = "DISPUTED"
    touch(ln)

    ef = escrow_file_store.get(ln["escrow_file_id"])
    if ef:
        recompute_posture(ef)
        touch(ef)

    return success_object(ln)


@bp.route("/api/liens/<id>/resolve-dispute", methods=["POST"])
def resolve_dispute(id):
    user_id, role = require_roles(["EscrowOfficer"])
    ln = _get_lien_checked(id)
    _check_parent_mutable(ln)

    if ln["status"] != "DISPUTED":
        raise ApiError(ERR_INVALID_TRANSITION, f"Cannot resolve dispute on lien in status {ln['status']}.", 409)

    ln["status"] = "DISCOVERED"
    touch(ln)

    ef = escrow_file_store.get(ln["escrow_file_id"])
    if ef:
        recompute_posture(ef)
        touch(ef)

    return success_object(ln)
