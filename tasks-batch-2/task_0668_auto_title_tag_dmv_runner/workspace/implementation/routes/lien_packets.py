"""LienPacket endpoints (PRD §3.8; scaffold §1.5)."""

from flask import Blueprint, g, request

import errors
import repo
from db import db
from domain import submissions_for_transaction
from helpers import get_json_body, require_str, require_int, parse_pagination, paginate
from middleware import require_roles
from response import success, list_success
from serializers import lien_packet_out

bp = Blueprint("lien_packets", __name__)


@bp.route("/dmv/lien-packets", methods=["POST"])
@require_roles("LienOfficer", "IntakeClerk")
def create_lien_packet():
    body = get_json_body()
    transaction_id = require_str(body, "transaction_id")
    lender_name = require_str(body, "lender_name")
    lien_amount_cents = require_int(body, "lien_amount_cents")

    txn = db.transactions.get(transaction_id)
    if txn is None:
        raise errors.not_found("transaction not found")

    # lien_amount_cents >= 1 is a typed constraint -> ERR_VALIDATION.
    if lien_amount_cents < 1:
        raise errors.validation("lien_amount_cents must be >= 1")

    rec = repo.make_lien_packet(transaction_id, lender_name, lien_amount_cents)
    return success(lien_packet_out(rec), 201)


@bp.route("/dmv/lien-packets/<pid>", methods=["GET"])
@require_roles("PlatformAdmin", "LienOfficer", "FeeAnalyst", "AccountHolder")
def get_lien_packet(pid):
    p = db.lien_packets.get(pid)
    if p is None:
        raise errors.not_found("lien packet not found")
    if g.user_role == "AccountHolder":
        txn = db.transactions.get(p["transaction_id"])
        if txn is None or txn["account_id"] != g.user_id:
            raise errors.not_resource_owner("AccountHolder may only read own packets")
    return success(lien_packet_out(p), 200)


@bp.route("/dmv/lien-packets/<pid>/perfect", methods=["POST"])
@require_roles("LienOfficer")
def perfect_lien_packet(pid):
    p = db.lien_packets.get(pid)
    if p is None:
        raise errors.not_found("lien packet not found")

    # State eligibility (priority 5): packet must be DRAFT, owning transaction
    # APPROVED, and its submission ACCEPTED.
    if p["packet_status"] != "DRAFT":
        raise errors.invalid_state("lien packet must be DRAFT to perfect")

    txn = db.transactions.get(p["transaction_id"])
    if txn is None:
        raise errors.not_found("owning transaction not found")
    if txn["lifecycle_status"] != "APPROVED":
        raise errors.invalid_state("owning transaction must be APPROVED to perfect")
    if not any(s["submission_status"] == "ACCEPTED"
               for s in submissions_for_transaction(txn["id"])):
        raise errors.invalid_state("owning transaction's submission must be ACCEPTED")

    # Segregation of duties (priority 7): acting X-User-ID must differ from the
    # transaction's submitted_by_user_id.
    if g.user_id == txn["submitted_by_user_id"]:
        raise errors.segregation_of_duties(
            "perfecting officer must not be the submitting user"
        )

    p["packet_status"] = "PERFECTED"
    p["perfected_by_user_id"] = g.user_id
    repo.bump(p)
    return success(lien_packet_out(p), 200)


@bp.route("/dmv/lien-packets", methods=["GET"])
@require_roles("PlatformAdmin", "LienOfficer", "FeeAnalyst", "AccountHolder")
def list_lien_packets():
    limit, offset = parse_pagination()
    transaction_id = request.args.get("transaction_id")
    packet_status = request.args.get("packet_status")
    items = list(db.lien_packets.values())
    if transaction_id is not None:
        items = [p for p in items if p["transaction_id"] == transaction_id]
    if packet_status is not None:
        items = [p for p in items if p["packet_status"] == packet_status]
    if g.user_role == "AccountHolder":
        def owns(p):
            txn = db.transactions.get(p["transaction_id"])
            return txn is not None and txn["account_id"] == g.user_id
        items = [p for p in items if owns(p)]
    page, total = paginate(items, limit, offset)
    return list_success([lien_packet_out(p) for p in page], limit, offset, total)
