"""ReciprocityGrant endpoints (PRD §3.7)."""

from flask import Blueprint, g, request

import errors
import serialize
import services.cycle as cycle_service
from common import (
    get_json_body,
    require_string,
    require_number,
    enum_field,
    optional_field,
    parse_pagination,
    paginate,
)
from db import db
from middleware import require_roles
from models import new_full_record, bump
from response import success_object, success_list
from routes.renewal_cycles import get_cycle_or_404
from routes.licensees import get_licensee_or_404
from util import round_half_up_1, as_decimal

bp = Blueprint("reciprocity_grants", __name__)

CATEGORIES = {"ETHICS", "SUBSTANCE", "GENERAL"}


def get_grant_or_404(grant_id):
    g_ = db.reciprocity_grants.get(grant_id)
    if g_ is None:
        raise errors.not_found(f"ReciprocityGrant '{grant_id}' not found.")
    return g_


@bp.route("/reciprocity-grants", methods=["POST"])
@require_roles("Licensee", "BoardAdmin")
def request_grant():
    body = get_json_body()
    licensee_id = require_string(body, "licensee_id")
    target_cycle_id = require_string(body, "target_cycle_id")
    source_jurisdiction_code = require_string(body, "source_jurisdiction_code")
    category = enum_field(body, "category", CATEGORIES)
    credit_hours = require_number(body, "credit_hours")
    if credit_hours <= 0:
        raise errors.invalid_request("credit_hours must be greater than 0.")
    credit_hours = round_half_up_1(credit_hours)

    # Existence (404).
    licensee = get_licensee_or_404(licensee_id)
    cycle = get_cycle_or_404(target_cycle_id)

    # Ownership: a Licensee may only request for its own licensee_id.
    if g.user_role == "Licensee" and g.user_id != licensee_id:
        raise errors.not_resource_owner(
            "Licensee may only request reciprocity for its own licensee_id."
        )

    # Same-jurisdiction check at request time (priority 12).
    board = db.license_boards[cycle["board_id"]]
    if source_jurisdiction_code == board["jurisdiction_code"]:
        raise errors.same_jurisdiction(
            "source_jurisdiction_code must differ from the target cycle's board."
        )

    with db.lock:
        rec = new_full_record()
        rec.update({
            "licensee_id": licensee_id,
            "target_cycle_id": target_cycle_id,
            "source_jurisdiction_code": source_jurisdiction_code,
            "category": category,
            "credit_hours": credit_hours,
            "status": "REQUESTED",
        })
        db.reciprocity_grants[rec["id"]] = rec

    return success_object(serialize.reciprocity_grant(rec), status=201)


@bp.route("/reciprocity-grants/<grant_id>", methods=["GET"])
@require_roles("BoardAdmin", "Licensee", "Auditor")
def get_grant(grant_id):
    g_ = get_grant_or_404(grant_id)
    return success_object(serialize.reciprocity_grant(g_), status=200)


@bp.route("/reciprocity-grants", methods=["GET"])
@require_roles("BoardAdmin", "Licensee", "Auditor")
def list_grants():
    limit, offset = parse_pagination()
    licensee_id = request.args.get("licensee_id")
    items = list(db.reciprocity_grants.values())
    if licensee_id is not None:
        items = [x for x in items if x["licensee_id"] == licensee_id]
    items.sort(key=lambda r: r["created_at"])
    total = len(items)
    page = paginate(items, limit, offset)
    return success_list(
        [serialize.reciprocity_grant(x) for x in page], limit, offset, total, status=200,
    )


@bp.route("/renewal-cycles/<cycle_id>/reciprocity-grants", methods=["GET"])
@require_roles("BoardAdmin", "Licensee", "Auditor")
def list_cycle_grants(cycle_id):
    get_cycle_or_404(cycle_id)
    limit, offset = parse_pagination()
    items = [
        x for x in db.reciprocity_grants.values() if x["target_cycle_id"] == cycle_id
    ]
    items.sort(key=lambda r: r["created_at"])
    total = len(items)
    page = paginate(items, limit, offset)
    return success_list(
        [serialize.reciprocity_grant(x) for x in page], limit, offset, total, status=200,
    )


@bp.route("/reciprocity-grants/<grant_id>/approve", methods=["POST"])
@require_roles("BoardAdmin")
def approve_grant(grant_id):
    grant = get_grant_or_404(grant_id)
    with db.lock:
        if grant["status"] != "REQUESTED":
            raise errors.invalid_state("Grant must be REQUESTED to approve.")

        cycle = db.renewal_cycles[grant["target_cycle_id"]]
        if cycle["status"] not in ("OPEN", "REQUIREMENTS_MET"):
            raise errors.invalid_state(
                "Target cycle must be OPEN or REQUIREMENTS_MET to approve."
            )

        # Same-jurisdiction re-check at approval time (priority 12).
        board = db.license_boards[cycle["board_id"]]
        if grant["source_jurisdiction_code"] == board["jurisdiction_code"]:
            raise errors.same_jurisdiction(
                "source_jurisdiction_code must differ from the target cycle's board."
            )

        grant["status"] = "APPROVED"
        bump(grant)

        # Add reciprocity_hours, recompute, possible bubble-up.
        cycle["reciprocity_hours"] = round_half_up_1(
            as_decimal(cycle["reciprocity_hours"]) + as_decimal(grant["credit_hours"])
        )
        cycle_service.recompute_credit_tally(cycle)
        bump(cycle)
        cycle_service.reconcile_after_recompute(cycle, bump)

    return success_object(serialize.reciprocity_grant(grant), status=200)


@bp.route("/reciprocity-grants/<grant_id>/deny", methods=["POST"])
@require_roles("BoardAdmin")
def deny_grant(grant_id):
    grant = get_grant_or_404(grant_id)
    body = get_json_body()
    _reason = optional_field(body, "reason", default=None, types=str)
    with db.lock:
        if grant["status"] != "REQUESTED":
            raise errors.invalid_state("Grant must be REQUESTED to deny.")
        grant["status"] = "DENIED"
        bump(grant)
    return success_object(serialize.reciprocity_grant(grant), status=200)


@bp.route("/reciprocity-grants/<grant_id>/revoke", methods=["POST"])
@require_roles("BoardAdmin")
def revoke_grant(grant_id):
    grant = get_grant_or_404(grant_id)
    with db.lock:
        if grant["status"] != "APPROVED":
            raise errors.invalid_state("Grant must be APPROVED to revoke.")

        cycle = db.renewal_cycles[grant["target_cycle_id"]]
        if cycle["status"] not in ("OPEN", "REQUIREMENTS_MET"):
            raise errors.invalid_state(
                "Target cycle must be OPEN or REQUIREMENTS_MET to revoke."
            )

        grant["status"] = "DENIED"
        bump(grant)

        # Compensation: subtract reciprocity_hours (exact inverse of approve).
        cycle["reciprocity_hours"] = round_half_up_1(
            as_decimal(cycle["reciprocity_hours"]) - as_decimal(grant["credit_hours"])
        )
        cycle_service.recompute_credit_tally(cycle)
        bump(cycle)
        cycle_service.reconcile_after_recompute(cycle, bump)

    return success_object(serialize.reciprocity_grant(grant), status=200)
