"""Provider endpoints + the four-hop revocation cascade (PRD §3.1, §3.2)."""

from flask import Blueprint, g

import clock
import errors
import serialize
import services.cycle as cycle_service
from common import (
    get_json_body,
    require_string,
    require_field,
    optional_field,
    parse_pagination,
    paginate,
)
from db import db
from middleware import require_roles
from models import new_full_record, bump
from response import success_object, success_list
from routes.license_boards import get_board_or_404
from util import parse_iso

bp = Blueprint("providers", __name__)


def get_provider_or_404(provider_id):
    p = db.providers.get(provider_id)
    if p is None:
        raise errors.not_found(f"Provider '{provider_id}' not found.")
    return p


@bp.route("/providers", methods=["POST"])
@require_roles("BoardAdmin")
def create_provider():
    body = get_json_body()
    name = require_string(body, "name")
    board_id = require_string(body, "board_id")
    get_board_or_404(board_id)

    with db.lock:
        rec = new_full_record()
        rec.update({
            "name": name,
            "board_id": board_id,
            "status": "APPLIED",
            "accredited_from": None,
            "accredited_until": None,
        })
        db.providers[rec["id"]] = rec

    return success_object(serialize.provider(rec), status=201)


@bp.route("/providers/<provider_id>", methods=["GET"])
@require_roles("BoardAdmin", "Provider", "Licensee", "Auditor")
def get_provider(provider_id):
    p = get_provider_or_404(provider_id)
    return success_object(serialize.provider(p), status=200)


@bp.route("/providers", methods=["GET"])
@require_roles("BoardAdmin", "Provider", "Licensee", "Auditor")
def list_providers():
    limit, offset = parse_pagination()
    from flask import request
    board_id = request.args.get("board_id")
    items = list(db.providers.values())
    if board_id is not None:
        items = [p for p in items if p["board_id"] == board_id]
    items.sort(key=lambda r: r["created_at"])
    total = len(items)
    page = paginate(items, limit, offset)
    return success_list(
        [serialize.provider(p) for p in page], limit, offset, total, status=200,
    )


@bp.route("/providers/<provider_id>/accredit", methods=["POST"])
@require_roles("BoardAdmin")
def accredit_provider(provider_id):
    p = get_provider_or_404(provider_id)
    body = get_json_body()
    accredited_until_raw = require_field(body, "accredited_until")
    accredited_until = parse_iso(accredited_until_raw, field="accredited_until")

    with db.lock:
        if p["status"] != "APPLIED":
            raise errors.invalid_state(
                "Provider must be APPLIED to be accredited."
            )
        now = clock.now()
        if not (accredited_until > now):
            raise errors.validation_range(
                "accredited_until must be strictly later than the current clock."
            )
        p["status"] = "ACCREDITED"
        p["accredited_from"] = now
        p["accredited_until"] = accredited_until
        bump(p)

    return success_object(serialize.provider(p), status=200)


@bp.route("/providers/<provider_id>/suspend", methods=["POST"])
@require_roles("BoardAdmin")
def suspend_provider(provider_id):
    p = get_provider_or_404(provider_id)
    with db.lock:
        if p["status"] != "ACCREDITED":
            raise errors.invalid_state("Provider must be ACCREDITED to be suspended.")
        p["status"] = "SUSPENDED"
        bump(p)
    return success_object(serialize.provider(p), status=200)


@bp.route("/providers/<provider_id>/reinstate", methods=["POST"])
@require_roles("BoardAdmin")
def reinstate_provider(provider_id):
    p = get_provider_or_404(provider_id)
    with db.lock:
        if p["status"] != "SUSPENDED":
            raise errors.invalid_state("Provider must be SUSPENDED to be reinstated.")
        p["status"] = "ACCREDITED"
        bump(p)
    return success_object(serialize.provider(p), status=200)


@bp.route("/providers/<provider_id>/revoke", methods=["POST"])
@require_roles("BoardAdmin")
def revoke_provider(provider_id):
    p = get_provider_or_404(provider_id)
    with db.lock:
        if p["status"] not in ("ACCREDITED", "SUSPENDED"):
            raise errors.invalid_state(
                "Provider must be ACCREDITED or SUSPENDED to be revoked."
            )

        # Transition itself: -> REVOKED, version bump.
        p["status"] = "REVOKED"
        bump(p)

        # Four-hop cascade (PRD §3.2), atomic within the lock.
        affected_cycle_ids = set()

        # Hop 1: deactivate every ACTIVE course of this provider.
        for course in db.courses.values():
            if course["provider_id"] != provider_id:
                continue
            if course["status"] != "ACTIVE":
                continue
            course["status"] = "DEACTIVATED"
            bump(course)

            # Hop 2: invalidate every VERIFIED completion on that course.
            for comp in db.completions.values():
                if comp["course_id"] != course["id"]:
                    continue
                if comp["status"] != "VERIFIED":
                    continue
                comp["status"] = "INVALIDATED"
                bump(comp)
                affected_cycle_ids.add(comp["cycle_id"])

        # Hop 3: recompute each touched cycle's earned hours.
        # Hop 4: revert REQUIREMENTS_MET -> OPEN where requirement no longer met.
        for cycle_id in affected_cycle_ids:
            cycle = db.renewal_cycles.get(cycle_id)
            if cycle is None:
                continue
            cycle_service.recompute_credit_tally(cycle)
            bump(cycle)
            if cycle["status"] == "REQUIREMENTS_MET":
                if not cycle_service.requirement_met(cycle):
                    cycle["status"] = "OPEN"
                    cycle["carryover_out_hours"] = 0
                    # bump already applied above for this recompute.

    return success_object(serialize.provider(p), status=200)
