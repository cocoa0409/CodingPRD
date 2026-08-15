"""PullListEntry endpoints: pull lifecycle with asset cascades and billing."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_INVALID_REQUEST,
    ERR_RESOURCE_NOT_FOUND,
    ERR_ASSET_NOT_AVAILABLE,
    ERR_SCHEDULE_NOT_AUTHORIZED,
)
from middleware import require_roles
from response import success_object, success_list
from services import calculations as calc
from services.domain import (
    check_declared,
    check_terminal,
    check_transition_owner,
    parse_to,
)
from util import (
    get_json_body,
    paginate,
    parse_iso8601,
    parse_pagination,
    require_string,
    require_ts,
    serialize,
    serialize_list,
    sort_by_created_at,
)

bp = Blueprint("pull_list_entries", __name__)

ENTRY_STATES = {
    "REQUESTED",
    "RESERVED",
    "PREPPED",
    "OUT",
    "RETURNED",
    "DAMAGED",
    "LOST",
    "CANCELLED",
}
ENTRY_TERMINAL = {"RETURNED", "DAMAGED", "LOST", "CANCELLED"}
ENTRY_TO_OWNERS = {
    "RESERVED": {"WarehouseChief"},
    "PREPPED": {"WarehouseChief"},
    "OUT": {"WarehouseChief"},
    "RETURNED": {"WarehouseChief"},
    "CANCELLED": {"WarehouseChief"},
    # DAMAGED / LOST are system-driven via damage assessment.
}
ENTRY_DECLARED = {
    "REQUESTED": {"RESERVED", "CANCELLED"},
    "RESERVED": {"PREPPED", "CANCELLED"},
    "PREPPED": {"OUT"},
    "OUT": {"RETURNED"},
}


def get_entry_or_404(entry_id: str) -> dict:
    entry = db.pull_list_entries.get(entry_id)
    if entry is None:
        raise_err(ERR_RESOURCE_NOT_FOUND, "PullListEntry id does not exist")
    return entry


def _free_asset_and_promote(asset: dict) -> None:
    """Return an asset to AVAILABLE and run the waitlist promotion scan."""
    asset["status"] = "AVAILABLE"
    db.touch(asset)
    calc.run_waitlist_promotion(asset)


@bp.route("/pull-list-entries/<entry_id>", methods=["GET"])
@require_roles("Any")
def get_entry(entry_id: str, _user_id: str, _role: str):
    return success_object(serialize(get_entry_or_404(entry_id)))


@bp.route("/pull-list-entries/<entry_id>/damage-reports", methods=["GET"])
@require_roles("Any")
def list_entry_damage_reports(entry_id: str, _user_id: str, _role: str):
    get_entry_or_404(entry_id)
    limit, offset = parse_pagination()
    items = [r for r in db.damage_reports.values() if r["pull_list_entry_id"] == entry_id]
    items = sort_by_created_at(items)
    page, total = paginate(items, limit, offset)
    return success_list(serialize_list(page), limit, offset, total)


@bp.route("/pull-list-entries/<entry_id>/transition", methods=["POST"])
@require_roles("WarehouseChief")
def transition_entry(entry_id: str, _user_id: str, _role: str):
    body = get_json_body()
    to = parse_to(body, ENTRY_STATES)
    check_transition_owner(to, ENTRY_TO_OWNERS, _role)

    # Entity-independent payload schema (400) before existence.
    prep_start = None
    prep_end = None
    load_schedule_id = None
    if to == "PREPPED":
        prep_start = require_ts(body, "prep_window_start")
        prep_end = require_ts(body, "prep_window_end")
        if not (parse_iso8601(prep_end, "prep_window_end") > parse_iso8601(prep_start, "prep_window_start")):
            raise_err(ERR_INVALID_REQUEST, "prep_window_end must be strictly after prep_window_start")
    if to == "OUT":
        load_schedule_id = require_string(body, "load_schedule_id")

    entry = get_entry_or_404(entry_id)

    # Body-FK existence resolves before state checks (left-to-right, path first).
    schedule = None
    if to == "OUT":
        schedule = db.load_schedules.get(load_schedule_id)
        if schedule is None:
            raise_err(ERR_RESOURCE_NOT_FOUND, "LoadSchedule id does not exist")

    check_terminal(entry, ENTRY_TERMINAL, to, ENTRY_DECLARED)
    check_declared(entry, to, ENTRY_DECLARED)

    production = db.productions.get(entry["production_id"])
    asset = db.assets.get(entry["asset_id"])

    if to == "RESERVED":
        if asset is None or asset["status"] != "AVAILABLE":
            raise_err(ERR_ASSET_NOT_AVAILABLE, "Asset is not AVAILABLE")
        asset["status"] = "RESERVED"
        db.touch(asset)
        entry["status"] = "RESERVED"
        db.touch(entry)
        calc.refresh_posture(production)
        return success_object(serialize(entry))

    if to == "PREPPED":
        entry["prep_window_start"] = prep_start
        entry["prep_window_end"] = prep_end
        asset["status"] = "PREPPED"
        db.touch(asset)
        entry["status"] = "PREPPED"
        db.touch(entry)
        calc.refresh_posture(production)
        return success_object(serialize(entry))

    if to == "OUT":
        # The truck-capacity verdict surfaces ahead of schedule authorization.
        calc.check_truck_capacity(schedule, entry)
        if schedule["status"] != "AUTHORIZED" or schedule["direction"] != "LOAD_IN":
            raise_err(ERR_SCHEDULE_NOT_AUTHORIZED, "Check-out requires an AUTHORIZED LOAD_IN schedule")
        entry["out_at"] = db.get_current_utc()
        entry["load_schedule_id"] = load_schedule_id
        asset["status"] = "DEPLOYED"
        db.touch(asset)
        entry["status"] = "OUT"
        db.touch(entry)
        # Persist the recomputed pack weight on the schedule (derived-field
        # change bumps the schedule's version).
        new_pack = float(calc.compute_pack_weight(schedule))
        if schedule["pack_weight_kg"] != new_pack:
            schedule["pack_weight_kg"] = new_pack
            db.touch(schedule)
        else:
            schedule["pack_weight_kg"] = new_pack
        calc.refresh_posture(production)
        return success_object(serialize(entry))

    if to == "RETURNED":
        entry["returned_at"] = db.get_current_utc()
        entry["rental_charge_cents"] = calc.compute_rental_charge(
            entry["out_at"], entry["returned_at"], asset["daily_rate_cents"]
        )
        entry["status"] = "RETURNED"
        db.touch(entry)
        _free_asset_and_promote(asset)
        calc.refresh_posture(production)
        return success_object(serialize(entry))

    # to == "CANCELLED"
    if entry["status"] == "RESERVED":
        entry["status"] = "CANCELLED"
        db.touch(entry)
        _free_asset_and_promote(asset)
    else:  # REQUESTED — no asset held
        entry["status"] = "CANCELLED"
        db.touch(entry)
    calc.refresh_posture(production)
    return success_object(serialize(entry))
