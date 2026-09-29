"""Facility replacement, shared facilities, construction staging and maintenance."""

from flask import Blueprint

import authz
import calc
import common
import enums
import envelope
import shape
import store
from errors import fail

bp = Blueprint("ops", __name__)

STAGING_TAIL_DAYS = 180

# The only legal requested transitions of a facility replacement (PRD 3.9).
LEGAL_REPLACEMENT_TRANSITIONS = {
    ("PLANNED", "INTERIM_IN_PLACE"),
    ("INTERIM_IN_PLACE", "COMPLETE"),
    ("INTERIM_IN_PLACE", "DEFICIENT"),
    ("DEFICIENT", "COMPLETE"),
}


def _deficit(original, replacement):
    return max(0, int(original) - int(replacement))


# ------------------------------------------------------- facility replacement ---
@bp.post("/jda/agreements/<agreement_id>/facility-replacements")
def create_replacement(agreement_id):
    authz.authorize("TransitOperationsManager")
    body = shape.body()
    facility_type = shape.as_enum(body, "facility_type", enums.REPLACEMENT_FACILITY_TYPE)
    original_capacity = shape.as_int(body, "original_capacity", minimum=1)
    replacement_capacity = shape.as_int(body, "replacement_capacity", minimum=0)
    interim_capacity = shape.as_int(body, "interim_capacity", minimum=0)
    milestone_date = shape.as_date(body, "milestone_date")
    store.require("agreement", agreement_id)
    replacement = store.create("facility_replacement", {
        "jda_id": agreement_id,
        "facility_type": facility_type,
        "original_capacity": original_capacity,
        "replacement_capacity": replacement_capacity,
        "interim_capacity": interim_capacity,
        "milestone_date": milestone_date,
        "capacity_deficit": _deficit(original_capacity, replacement_capacity),
        "status": "PLANNED",
    })
    return envelope.created(common.public(replacement))


@bp.post("/jda/facility-replacements/<replacement_id>/status")
def report_replacement_status(replacement_id):
    authz.authorize("TransitOperationsManager")
    body = shape.body()
    requested = shape.as_enum(body, "status", enums.REPLACEMENT_STATUS_INPUT)
    interim_capacity = shape.as_int(body, "interim_capacity", required=False,
                                   default=None, minimum=0)
    replacement_capacity = shape.as_int(body, "replacement_capacity", required=False,
                                        default=None, minimum=0)
    replacement = store.require("facility_replacement", replacement_id)
    if (replacement["status"], requested) not in LEGAL_REPLACEMENT_TRANSITIONS:
        fail("ERR_INVALID_REQUEST",
             "A facility replacement in %s cannot be reported as %s"
             % (replacement["status"], requested))
    if requested == "INTERIM_IN_PLACE":
        effective_interim = (interim_capacity if interim_capacity is not None
                             else replacement["interim_capacity"])
        if int(effective_interim) < 1:
            fail("ERR_INVALID_REQUEST",
                 "Reporting the interim stage requires an interim_capacity of at least 1")
    # Corrections are applied and the deficit recomputed BEFORE the state decision.
    if interim_capacity is not None:
        replacement["interim_capacity"] = interim_capacity
    if replacement_capacity is not None:
        replacement["replacement_capacity"] = replacement_capacity
    replacement["capacity_deficit"] = _deficit(replacement["original_capacity"],
                                               replacement["replacement_capacity"])
    if requested == "COMPLETE" and replacement["capacity_deficit"] > 0:
        # Completion branches on the arithmetic, not on the caller's word.
        replacement["status"] = "DEFICIENT"
    else:
        replacement["status"] = requested
    store.touch(replacement)
    return envelope.ok(common.public(replacement))


# ----------------------------------------------------------- shared facilities ---
@bp.post("/jda/sites/<site_id>/shared-facilities")
def register_facility(site_id):
    authz.authorize("TransitOperationsManager")
    body = shape.body()
    facility_type = shape.as_enum(body, "facility_type", enums.SHARED_FACILITY_TYPE)
    total_bay_capacity = shape.as_int(body, "total_bay_capacity", minimum=1)
    responsibility = shape.as_enum(body, "maintenance_responsibility",
                                   enums.MAINTENANCE_RESPONSIBILITY)
    cost_share = shape.as_num(body, "cost_share_pct_developer", required=False,
                              default=0, minimum=0, maximum=1)
    store.require("site", site_id)
    facility = store.create("shared_facility", {
        "site_id": site_id,
        "facility_type": facility_type,
        "total_bay_capacity": total_bay_capacity,
        "maintenance_responsibility": responsibility,
        "cost_share_pct_developer": cost_share,
        "available_bay_capacity": total_bay_capacity,
    })
    return envelope.created(common.public(facility))


# ------------------------------------------------------------ staging windows ---
def _staging_envelope(agreement):
    """[ENP.start_date T00:00:00Z, (ENP.end_date + 180 days) T00:00:00Z) for the
    period whose proposal matches the agreement's proposal."""
    period = common.any_period_for(agreement["proposal_id"])
    if period is None:
        return None, None
    opens = store.midnight(store.parse_date(period["start_date"]))
    closes = store.midnight(store.date_plus(store.parse_date(period["end_date"]),
                                            STAGING_TAIL_DAYS))
    return opens, closes


@bp.post("/jda/staging-windows")
def request_window():
    user_id, _role = authz.authorize("Developer")
    body = shape.body()
    jda_id = shape.as_str(body, "jda_id")
    facility_id = shape.as_str(body, "shared_facility_id")
    start_at = shape.as_datetime(body, "start_at")
    end_at = shape.as_datetime(body, "end_at")
    bays_occupied = shape.as_int(body, "bays_occupied", minimum=0)
    purpose = shape.as_str(body, "purpose")
    expected_version = shape.as_int(body, "expected_facility_version")
    # Body foreign keys in declaration order: jda_id then shared_facility_id.
    agreement = store.require("agreement", jda_id)
    facility = store.require("shared_facility", facility_id)
    if agreement["developer_id"] != user_id:
        fail("ERR_NOT_RESOURCE_OWNER",
             "The referenced agreement belongs to another developer")
    if int(expected_version) != int(facility["version"]):
        fail("ERR_STALE_FACILITY_VERSION",
             "expected_facility_version %d does not match the facility's current version %d"
             % (int(expected_version), int(facility["version"])))
    start = store.parse_dt(start_at)
    end = store.parse_dt(end_at)
    if end <= start:
        fail("ERR_INVALID_INTERVAL", "end_at must be strictly after start_at")
    opens, closes = _staging_envelope(agreement)
    if opens is None or start < opens or end > closes:
        fail("ERR_STAGING_WINDOW_OUTSIDE_TERM",
             "The staging interval is not contained in the agreement's staging envelope")
    # A non-occupying window never conflicts with anything.
    if bays_occupied > 0:
        peak = common.peak_for(facility_id, start, end, bays_occupied)
        if peak > int(facility["total_bay_capacity"]):
            fail("ERR_STAGING_CAPACITY_EXCEEDED",
                 "Peak occupancy %d exceeds the facility's total bay capacity %d"
                 % (peak, int(facility["total_bay_capacity"])))
    window = store.create("staging_window", {
        "jda_id": jda_id,
        "shared_facility_id": facility_id,
        "start_at": start_at,
        "end_at": end_at,
        "bays_occupied": bays_occupied,
        "purpose": purpose,
        "status": "REQUESTED",
        "capacity_released": False,
        "rejection_reason": None,
    })
    # The request itself moves the facility, which is why the next requester must
    # re-read it (PRD 2.10).
    store.touch(facility)
    return envelope.created(common.public(window))


@bp.post("/jda/staging-windows/<window_id>/decision")
def decide_window(window_id):
    authz.authorize("TransitOperationsManager")
    body = shape.body()
    decision = shape.as_enum(body, "decision", enums.DECISION)
    rejection_reason = shape.as_str(body, "rejection_reason", required=False, default=None)
    if decision == "REJECT" and (rejection_reason is None or not rejection_reason.strip()):
        fail("ERR_INVALID_REQUEST", "rejection_reason is mandatory on the reject branch")
    window = store.require("staging_window", window_id)
    # Both branches require REQUESTED; the approve-only gates follow.
    if window["status"] != "REQUESTED":
        fail("ERR_STAGING_WINDOW_NOT_REQUESTED",
             "This staging window is already %s" % window["status"])
    facility = store.require("shared_facility", window["shared_facility_id"])
    if decision == "REJECT":
        window["status"] = "REJECTED"
        window["rejection_reason"] = rejection_reason
        store.touch(window)
        return envelope.ok(common.public(window))
    agreement = store.get("agreement", window["jda_id"])
    if agreement is None or agreement["negotiation_status"] != "BOARD_APPROVED":
        fail("ERR_AGREEMENT_NOT_BOARD_APPROVED",
             "The parent agreement is not BOARD_APPROVED")
    site = store.get("site", agreement["site_id"])
    if site is not None and site["transit_facility_present"]:
        replacements = common.replacements_of(agreement["id"])
        if not any(r["status"] in ("INTERIM_IN_PLACE", "COMPLETE") for r in replacements):
            fail("ERR_FACILITY_REPLACEMENT_INCOMPLETE",
                 "No transit facility replacement has reached INTERIM_IN_PLACE or COMPLETE")
    start = store.parse_dt(window["start_at"])
    end = store.parse_dt(window["end_at"])
    bays = int(window["bays_occupied"])
    if bays > 0:
        peak = common.peak_for(facility["id"], start, end, bays, exclude_id=window["id"])
        if peak > int(facility["total_bay_capacity"]):
            fail("ERR_STAGING_CAPACITY_EXCEEDED",
                 "Peak occupancy %d exceeds the facility's total bay capacity %d"
                 % (peak, int(facility["total_bay_capacity"])))
    window["status"] = "APPROVED"
    store.touch(window)
    common.refresh_available_bays(facility)
    store.touch(facility)
    return envelope.ok(common.public(window))


@bp.post("/jda/staging-windows/<window_id>/close")
def close_window(window_id):
    authz.authorize("TransitOperationsManager")
    window = store.require("staging_window", window_id)
    if window["status"] not in ("APPROVED", "SUSPENDED"):
        fail("ERR_STAGING_WINDOW_NOT_CLOSABLE",
             "A staging window in %s cannot be closed" % window["status"])
    was_released = bool(window["capacity_released"])
    window["status"] = "CLOSED"
    window["capacity_released"] = True
    store.touch(window)
    if not was_released:
        # The bays come back exactly once, however the window reached closure.
        facility = store.get("shared_facility", window["shared_facility_id"])
        if facility is not None:
            common.refresh_available_bays(facility)
            store.touch(facility)
    return envelope.ok(common.public(window))


# -------------------------------------------------------- maintenance charges ---
@bp.post("/jda/shared-facilities/<facility_id>/maintenance-charges")
def post_maintenance_charge(facility_id):
    authz.authorize("TransitOperationsManager")
    body = shape.body()
    jda_id = shape.as_str(body, "jda_id")
    period_start = shape.as_date(body, "period_start")
    period_end = shape.as_date(body, "period_end")
    items = shape.line_items(body, "line_items")
    facility = store.require("shared_facility", facility_id)
    store.require("agreement", jda_id)
    if store.parse_date(period_end) <= store.parse_date(period_start):
        fail("ERR_INVALID_INTERVAL", "period_end must be strictly later than period_start")
    if not items:
        fail("ERR_EMPTY_LINE_ITEMS", "line_items must contain at least one entry")
    share, total, developer_share, agency_share = calc.maintenance_allocation(facility, items)
    charge = store.create("maintenance_charge", {
        "shared_facility_id": facility_id,
        "jda_id": jda_id,
        "period_start": period_start,
        "period_end": period_end,
        "line_items": items,
        "effective_share_applied": share,
        "total_cost_cents": total,
        "developer_share_cents": developer_share,
        "agency_share_cents": agency_share,
    }, versioned=False)
    return envelope.created(common.public(charge))
