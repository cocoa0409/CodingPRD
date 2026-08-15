"""WeeklyEntry endpoints (SCAFFOLD 1.5, PRD 3.6)."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error, ERR_ZONE_NOT_FOUND, ERR_WEEKLY_ENTRY_NOT_FOUND,
    ERR_ENTRY_INVALID_TRANSITION, ERR_NOT_RESOURCE_OWNER, ERR_ZONE_NOT_ACTIVE,
    ERR_ZONE_AUDIT_HOLD, ERR_WEEK_WINDOW_OVERLAP, ERR_ENTRY_NO_LINE_ITEMS,
)
from middleware import authorized
from response import success_object, success_list
from serializers import entry_view
from services import (
    new_common, touch, recompute_entry_totals, entry_week_end,
)
from util import parse_dt
from validate import (
    get_body, reject_unknown_fields, req_str, req_enum, req_datetime,
    require_path, require_body_fk, parse_pagination,
)

bp = Blueprint("weekly_entries", __name__)

ALL_ROLES = ["ZoneOperator", "Importer", "CustomsOfficer", "GateOfficer"]


@bp.route("/zones/weekly-entries", methods=["POST"])
def create_entry():
    caller = authorized(["Importer"])
    body = get_body()
    reject_unknown_fields(body, {"zone_id", "week_start_date"})
    zone_id = req_str(body, "zone_id")
    zone = require_body_fk("zones", zone_id, ERR_ZONE_NOT_FOUND, "zone_id")
    week_start = parse_dt(req_datetime(body, "week_start_date"))
    week_end = entry_week_end(week_start)

    # Temporal (priority 8): half-open [start, end) window overlap on same zone;
    # adjacency (start == existing end) is permitted.
    for other in db["weekly_entries"].values():
        if other["zone_id"] != zone["id"]:
            continue
        if week_start < other["week_end_date"] and other["week_start_date"] < week_end:
            raise_error(ERR_WEEK_WINDOW_OVERLAP,
                        "weekly entry window overlaps an existing entry on this zone")

    entry = new_common()
    entry.update({
        "zone_id": zone["id"],
        "importer_ref": caller.user_id,
        "week_start_date": week_start,
        "week_end_date": week_end,
        "entered_value_cents": 0,
        "duty_total_cents": 0,
        "mpf_uncapped_cents": 0,
        "mpf_cents": 0,
        "per_shipment_mpf_cents": 0,
        "mpf_savings_cents": 0,
        "status": "OPEN",
    })
    db["weekly_entries"][entry["id"]] = entry
    return success_object(entry_view(entry), status=201)


@bp.route("/zones/weekly-entries", methods=["GET"])
def list_entries():
    authorized(ALL_ROLES)
    limit, offset = parse_pagination()
    zone_id = request.args.get("zone_id")
    status = request.args.get("status")
    items = sorted(db["weekly_entries"].values(), key=lambda e: (e["created_at"], e["id"]))
    if zone_id is not None:
        items = [e for e in items if e["zone_id"] == zone_id]
    if status is not None:
        items = [e for e in items if e["status"] == status]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([entry_view(e) for e in page], total, limit, offset)


@bp.route("/zones/weekly-entries/<entryId>", methods=["GET"])
def get_entry(entryId):
    authorized(ALL_ROLES)
    entry = require_path("weekly_entries", entryId, ERR_WEEKLY_ENTRY_NOT_FOUND)
    return success_object(entry_view(entry))


@bp.route("/zones/weekly-entries/<entryId>/file", methods=["POST"])
def file_entry(entryId):
    caller = authorized(["Importer"])
    entry = require_path("weekly_entries", entryId, ERR_WEEKLY_ENTRY_NOT_FOUND)
    get_body()
    if caller.user_id != entry["importer_ref"]:
        raise_error(ERR_NOT_RESOURCE_OWNER, "caller does not own this entry")
    if entry["status"] != "OPEN":
        raise_error(ERR_ENTRY_INVALID_TRANSITION,
                    f"entry cannot be filed from {entry['status']}")
    zone = db["zones"][entry["zone_id"]]
    if zone["status"] != "ACTIVE":
        raise_error(ERR_ZONE_NOT_ACTIVE, "operation requires zone.status == ACTIVE")
    if zone["compliance_posture"] != "NORMAL":
        raise_error(ERR_ZONE_AUDIT_HOLD, "operation requires zone.compliance_posture == NORMAL")
    # Resource constraint (priority 9): at least one qualifying member line.
    members = [
        w for w in db["withdrawals"].values()
        if w["weekly_entry_id"] == entry["id"]
        and w["withdrawal_type"] == "CONSUMPTION"
        and w["status"] in ("FILED", "DUTY_PAID")
    ]
    if not members:
        raise_error(ERR_ENTRY_NO_LINE_ITEMS,
                    "weekly entry filing requires at least one qualifying member line")

    recompute_entry_totals(entry)  # settlement computed and stored at filing
    entry["status"] = "FILED"
    touch(entry)
    return success_object(entry_view(entry))


@bp.route("/zones/weekly-entries/<entryId>/transition", methods=["POST"])
def transition_entry(entryId):
    caller = authorized(["CustomsOfficer"])
    entry = require_path("weekly_entries", entryId, ERR_WEEKLY_ENTRY_NOT_FOUND)
    body = get_body()
    reject_unknown_fields(body, {"to_status"})
    to_status = req_enum(body, "to_status", {"ACCEPTED", "OPEN"})

    # Only FILED -> ACCEPTED and FILED -> OPEN are reachable via client action
    # (FROZEN arises only from the audit-hold cascade).
    if entry["status"] != "FILED":
        raise_error(ERR_ENTRY_INVALID_TRANSITION,
                    f"entry cannot transition to {to_status} from {entry['status']}")
    entry["status"] = to_status
    touch(entry)
    return success_object(entry_view(entry))
