"""Settlement endpoints."""

from flask import Blueprint, request

from db import db, new_id
from clock import now_iso
from middleware import (
    require_roles,
    get_auth,
    parse_json_body,
    require_fields,
    require_str,
    require_enum,
)
from response import success_object, success_array
from errors import (
    ERR_NOT_FOUND,
    ERR_REFERENCED_ENTITY_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_SHOWTIME_NOT_COMPLETED,
    ERR_BAD_REQUEST,
    raise_error,
)
from services.audit import append_audit
from services.calculations import compute_settlement_split
from services.pagination import parse_pagination, paginate, sort_by_created_at_asc
from services.version_check import check_version, check_idempotent_action

bp = Blueprint("settlements", __name__)


SETTLEMENT_KINDS = {"POSTING", "REVERSAL"}
SETTLEMENT_STATUSES = {"DRAFT", "POSTED", "REVERSED"}


def _serialize(s):
    return dict(s)


@bp.route("/settlements", methods=["POST"])
@require_roles({"FinanceOps"})
def create_settlement():
    role, user_id = get_auth()
    body = parse_json_body()
    require_fields(body, ["showtime_id", "cycle_label"])
    showtime_id = require_str(body.get("showtime_id"), "showtime_id")
    cycle_label = require_str(body.get("cycle_label"), "cycle_label")

    # FK existence
    showtime = db.showtimes.get(showtime_id)
    if not showtime:
        raise_error(ERR_REFERENCED_ENTITY_NOT_FOUND, "showtime not found")
    distributor = db.distributors.get(showtime["distributor_id"])
    if not distributor:
        raise_error(ERR_REFERENCED_ENTITY_NOT_FOUND, "distributor not found")

    # Evaluation set: all VALID tickets for the showtime at evaluation time
    valid_tickets = [t for t in db.tickets.values() if t["showtime_id"] == showtime_id and t["status"] == "VALID"]
    split = compute_settlement_split(valid_tickets, distributor["default_split_ratio_bps"])

    now = now_iso()
    settlement = {
        "id": new_id(),
        "showtime_id": showtime_id,
        "cycle_label": cycle_label,
        "kind": "POSTING",
        "status": "DRAFT",
        "gross_cents": split["gross_cents"],
        "platform_commission_cents": split["platform_commission_cents"],
        "tax_cents": split["tax_cents"],
        "distributor_amount_cents": split["distributor_amount_cents"],
        "cinema_amount_cents": split["cinema_amount_cents"],
        "parent_settlement_id": None,
        "created_at": now,
    }
    db.settlements[settlement["id"]] = settlement
    return success_object(_serialize(settlement), http_status=201)


@bp.route("/settlements/<settlement_id>/post", methods=["POST"])
@require_roles({"FinanceOps"})
def post_settlement(settlement_id):
    role, user_id = get_auth()
    settlement = db.settlements.get(settlement_id)
    if not settlement:
        raise_error(ERR_NOT_FOUND, "settlement not found")
    body = parse_json_body()
    requested_version = body.get("version")
    if requested_version is not None and (isinstance(requested_version, bool) or not isinstance(requested_version, int)):
        raise_error(ERR_BAD_REQUEST, "version must be integer")

    # State: POSTING + DRAFT
    if settlement["kind"] != "POSTING":
        raise_error(ERR_INVALID_STATE, "only POSTING settlements may be posted")

    # Cross-entity: showtime must be COMPLETED
    showtime = db.showtimes.get(settlement["showtime_id"])
    if not showtime:
        raise_error(ERR_REFERENCED_ENTITY_NOT_FOUND, "showtime not found")

    if settlement["status"] != "DRAFT":
        # Idempotency: if already POSTED and caller is retrying with a stale version
        from errors import ERR_DUPLICATE_OPERATION
        if requested_version is not None and isinstance(requested_version, int) and not isinstance(requested_version, bool):
            if settlement["status"] in ("POSTED", "REVERSED"):
                raise_error(ERR_DUPLICATE_OPERATION, "settlement already posted")
        raise_error(ERR_INVALID_STATE, "settlement not in DRAFT")

    if showtime["lifecycle_status"] != "COMPLETED":
        raise_error(ERR_SHOWTIME_NOT_COMPLETED, "showtime not COMPLETED")

    # Spec §3.9: "A settlement post that races against a ticket refund for the same showtime is
    # serialized by optimistic concurrency on the showtime's version".
    # The post action accepts a version field — interpret as showtime.version match.
    check_version(showtime["version"], requested_version)

    # Apply
    settlement["status"] = "POSTED"
    append_audit(role, user_id, "SETTLEMENT_POST", "Settlement", settlement["id"], {"status": "POSTED"})
    return success_object(_serialize(settlement))


@bp.route("/settlements/<settlement_id>", methods=["GET"])
@require_roles({"PlatformAdmin", "DistributorOps", "CinemaOps", "FinanceOps", "Auditor"})
def get_settlement(settlement_id):
    s = db.settlements.get(settlement_id)
    if not s:
        raise_error(ERR_NOT_FOUND, "settlement not found")
    return success_object(_serialize(s))


@bp.route("/settlements", methods=["GET"])
@require_roles({"PlatformAdmin", "DistributorOps", "CinemaOps", "FinanceOps", "Auditor"})
def list_settlements():
    limit, offset = parse_pagination()
    cycle_label = request.args.get("cycle_label")
    showtime_id = request.args.get("showtime_id")
    kind = request.args.get("kind")
    status = request.args.get("status")
    if kind is not None and kind not in SETTLEMENT_KINDS:
        raise_error(ERR_BAD_REQUEST, "invalid kind filter")
    if status is not None and status not in SETTLEMENT_STATUSES:
        raise_error(ERR_BAD_REQUEST, "invalid status filter")
    items = []
    for s in db.settlements.values():
        if cycle_label is not None and s["cycle_label"] != cycle_label:
            continue
        if showtime_id is not None and s["showtime_id"] != showtime_id:
            continue
        if kind is not None and s["kind"] != kind:
            continue
        if status is not None and s["status"] != status:
            continue
        items.append(_serialize(s))
    items = sort_by_created_at_asc(items)
    page, total = paginate(items, limit, offset)
    return success_array(page, limit, offset, total)
