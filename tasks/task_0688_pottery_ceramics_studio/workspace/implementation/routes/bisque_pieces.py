"""BisquePiece routes (PRD §3.3; SCAFFOLD §1.5).

RBAC:
  GET  /bisque-pieces/{id}              StudioStaff, StudioManager, LoyaltyMember(own via visit)
  GET  /bisque-pieces                   StudioStaff, StudioManager
  POST /bisque-pieces/{id}/unload       StudioStaff, StudioManager
  POST /bisque-pieces/{id}/pickup       StudioStaff, StudioManager
  GET  /bisque-pieces/{id}/notification StudioStaff, StudioManager, LoyaltyMember(own via visit)
"""

from flask import Blueprint, request

from db import db, touch
from errors import invalid_state
from middleware import get_caller, require_roles
from response import success, list_success, parse_pagination, paginate
from services import serializers
from services.lookup import get_piece, get_visit, assert_member_owns

bp = Blueprint("bisque_pieces", __name__)

STAFF_MANAGER = {"StudioStaff", "StudioManager"}
STAFF_MANAGER_MEMBER = {"StudioStaff", "StudioManager", "LoyaltyMember"}


def _owning_member_id(piece):
    """A piece's owning member is the member_id of its studio visit (may be
    None for an anonymous walk-in)."""
    visit = db.studio_visits.get(piece["studio_visit_id"])
    return visit["member_id"] if visit else None


@bp.route("/bisque-pieces/<piece_id>", methods=["GET"])
def fetch_piece(piece_id):
    caller = get_caller()
    require_roles(caller, STAFF_MANAGER_MEMBER)
    piece = get_piece(piece_id)
    assert_member_owns(caller, _owning_member_id(piece))
    return success(serializers.bisque_piece(piece))


@bp.route("/bisque-pieces", methods=["GET"])
def list_pieces():
    caller = get_caller()
    require_roles(caller, STAFF_MANAGER)
    limit, offset = parse_pagination(request.args)
    records = list(db.bisque_pieces.values())
    studio_visit_id = request.args.get("studio_visit_id")
    if studio_visit_id is not None:
        records = [r for r in records if r["studio_visit_id"] == studio_visit_id]
    kiln_batch_id = request.args.get("kiln_batch_id")
    if kiln_batch_id is not None:
        records = [r for r in records if r["kiln_batch_id"] == kiln_batch_id]
    status = request.args.get("status")
    if status is not None:
        records = [r for r in records if r["status"] == status]
    window, total = paginate(records, limit, offset)
    return list_success([serializers.bisque_piece(r) for r in window], limit, offset, total)


@bp.route("/bisque-pieces/<piece_id>/unload", methods=["POST"])
def unload_piece(piece_id):
    caller = get_caller()
    require_roles(caller, STAFF_MANAGER)
    piece = get_piece(piece_id)

    # Un-loading is permitted only while the piece is LOADED and its batch is
    # still LOADING (PRD §3.3).
    if piece["status"] != "LOADED":
        raise invalid_state("Piece is not LOADED")
    batch = db.kiln_batches.get(piece["kiln_batch_id"])
    if batch is None or batch["status"] != "LOADING":
        raise invalid_state("Batch is not LOADING")

    # Compensate the earlier load: occupied_slots -= 1; batch.version += 1.
    batch["occupied_slots"] -= 1
    touch(batch)

    piece["kiln_batch_id"] = None
    piece["status"] = "PAINTED"
    touch(piece)
    return success(serializers.bisque_piece(piece))


@bp.route("/bisque-pieces/<piece_id>/pickup", methods=["POST"])
def pickup_piece(piece_id):
    caller = get_caller()
    require_roles(caller, STAFF_MANAGER)
    piece = get_piece(piece_id)
    # Permitted only from READY (PRD §3.3).
    if piece["status"] != "READY":
        raise invalid_state("Piece is not READY")
    piece["status"] = "PICKED_UP"
    touch(piece)
    return success(serializers.bisque_piece(piece))


@bp.route("/bisque-pieces/<piece_id>/notification", methods=["GET"])
def notification(piece_id):
    caller = get_caller()
    require_roles(caller, STAFF_MANAGER_MEMBER)
    piece = get_piece(piece_id)
    assert_member_owns(caller, _owning_member_id(piece))

    # Available only for a READY or PICKED_UP piece (PRD §3.3).
    if piece["status"] not in ("READY", "PICKED_UP"):
        raise invalid_state("Piece is not READY or PICKED_UP")

    out = serializers.bisque_piece(piece)
    # Expose owning member's contact details alongside the piece (PRD §3.3).
    member = None
    visit = db.studio_visits.get(piece["studio_visit_id"])
    if visit and visit["member_id"]:
        member = db.loyalty_members.get(visit["member_id"])
    out["member_contact"] = {
        "member_id": member["id"] if member else None,
        "full_name": member["full_name"] if member else None,
        "phone": member["phone"] if member else None,
        "email": member["email"] if member else None,
    }
    return success(out)
