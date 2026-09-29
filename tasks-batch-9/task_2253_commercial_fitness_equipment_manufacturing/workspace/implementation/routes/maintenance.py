"""Preventive maintenance programs and visits (PRD 3.8)."""

from flask import Blueprint, g, request

import calc
from auth import (
    check_facility_filter,
    check_facility_scope,
    check_partner_filter,
    check_partner_scope,
    get_asset,
    get_facility,
    get_partner,
    get_program,
    get_visit,
    require,
)
from constants import ANY_ROLE, PM_STATUSES, PM_TIERS, VISIT_STATUSES
from envelope import created, ok, ok_list
from errors import ApiError
from store import mutate, new_entity, store
from validation import (
    field_datetime,
    field_decimal,
    field_id,
    field_int,
    field_str,
    field_enum,
    get_body,
    paginate,
    paging,
    query_enum,
    query_str,
)

bp = Blueprint("maintenance", __name__)


def _training_current(partner):
    """Ladder rung 17."""
    expiry = calc.dt(partner["training_current_until"])
    if expiry is None or expiry <= store.now():
        raise ApiError(
            "ERR_PARTNER_TRAINING_EXPIRED",
            "The service partner's training currency has lapsed.",
        )


def _categories_covered(partner, facility_id):
    """Ladder rung 18 — the facility's in-service categories."""
    for category in sorted(calc.facility_categories(facility_id)):
        if category not in partner["certified_categories"]:
            raise ApiError(
                "ERR_PARTNER_NOT_CERTIFIED_FOR_CATEGORY",
                "The partner is not certified for category %s." % category,
            )


# ---------------------------------------------------------------------------
# programs
# ---------------------------------------------------------------------------
@bp.post("/pm-programs")
@require("ServiceOpsAdmin", "FacilityManager")
def create_pm_program():
    body = get_body()

    # rung 4 — facility scope on the body-borne target
    target = body.get("facility_id")
    if isinstance(target, str):
        check_facility_scope(target)

    facility_id = field_id(body, "facility_id")
    service_partner_id = field_id(body, "service_partner_id")
    tier = field_enum(body, "tier", PM_TIERS)
    visit_interval_days = field_int(
        body, "visit_interval_days", minimum=30, maximum=365
    )

    # rung 9
    facility = get_facility(facility_id)
    partner = get_partner(service_partner_id)

    program = new_entity(
        {
            "facility_id": facility["id"],
            "service_partner_id": partner["id"],
            "tier": tier,
            "visit_interval_days": visit_interval_days,
            "status": "DRAFT",
            "covered_asset_count": 0,
            "annual_labor_hours_committed": 0,
            "needs_revision_reason": None,
            "last_revised_at": None,
        }
    )
    store.pm_programs[program["id"]] = program
    return created(program)


@bp.get("/pm-programs")
@require(*ANY_ROLE)
def list_pm_programs():
    limit, offset = paging()
    check_facility_filter()
    check_partner_filter()
    facility_id = query_str("facility_id")
    service_partner_id = query_str("service_partner_id")
    status = query_enum("status", PM_STATUSES)

    rows = list(store.pm_programs.values())
    if facility_id is not None:
        rows = [r for r in rows if r["facility_id"] == facility_id]
    if service_partner_id is not None:
        rows = [r for r in rows if r["service_partner_id"] == service_partner_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = paginate(rows, limit, offset)
    return ok_list(page, limit, offset, total)


@bp.get("/pm-programs/<program_id>")
@require(*ANY_ROLE)
def read_pm_program(program_id):
    program = get_program(program_id)
    check_facility_scope(program["facility_id"])
    check_partner_scope(program["service_partner_id"])
    return ok(program)


@bp.post("/pm-programs/<program_id>/activate")
@require("ServiceOpsAdmin")
def activate_pm_program(program_id):
    program = get_program(program_id)
    get_body()

    # rung 11
    if program["status"] != "DRAFT":
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION", "Only a DRAFT program may be activated."
        )

    partner = store.service_partners[program["service_partner_id"]]
    facility = store.facilities[program["facility_id"]]

    # rung 17
    _training_current(partner)
    # rung 18
    _categories_covered(partner, facility["id"])
    # rung 28
    if facility["status"] != "ACTIVE":
        raise ApiError("ERR_FACILITY_SUSPENDED", "The facility account is suspended.")
    # rung 34
    _, hours = calc.program_rollup(
        facility["id"], program["tier"], program["visit_interval_days"]
    )
    if calc.partner_committed_hours(partner) + hours > calc.dec(
        partner["certified_hours_capacity"]
    ):
        raise ApiError(
            "ERR_PARTNER_CAPACITY_EXCEEDED",
            "The program would exceed the partner's certified hours capacity.",
        )

    with mutate(program):
        program["status"] = "ACTIVE"
    calc.recompute_program(program)
    calc.recompute_partner(partner)
    return ok(program)


@bp.post("/pm-programs/<program_id>/revise")
@require("ServiceOpsAdmin")
def revise_pm_program(program_id):
    program = get_program(program_id)
    body = get_body()
    visit_interval_days = field_int(
        body, "visit_interval_days", required=False, minimum=30, maximum=365
    )
    service_partner_id = field_id(body, "service_partner_id", required=False)

    # rung 9
    new_partner = None
    if service_partner_id is not None:
        new_partner = get_partner(service_partner_id)

    # rung 11
    if program["status"] != "NEEDS_REVISION":
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION",
            "Only a NEEDS_REVISION program may be revised.",
        )

    old_partner_id = program["service_partner_id"]
    partner = new_partner or store.service_partners[old_partner_id]
    interval = (
        visit_interval_days
        if visit_interval_days is not None
        else program["visit_interval_days"]
    )

    # rung 17
    _training_current(partner)
    # rung 18
    _categories_covered(partner, program["facility_id"])
    # rung 34
    _, hours = calc.program_rollup(program["facility_id"], program["tier"], interval)
    if calc.dec(partner["committed_hours"]) + hours > calc.dec(
        partner["certified_hours_capacity"]
    ):
        raise ApiError(
            "ERR_PARTNER_CAPACITY_EXCEEDED",
            "The revision would exceed the partner's certified hours capacity.",
        )

    # rung 35 — every held visit must be able to re-reserve its units
    held = [
        visit
        for visit in calc.program_visits(program["id"])
        if visit["status"] == "ON_HOLD"
    ]
    available = partner["spare_stock_on_hand_units"]
    for visit in held:
        if visit["reserved_units"] > available:
            raise ApiError(
                "ERR_INSUFFICIENT_PART_STOCK",
                "The partner cannot re-reserve the held visits' spare units.",
            )
        available -= visit["reserved_units"]

    with mutate(program):
        program["status"] = "ACTIVE"
        program["service_partner_id"] = partner["id"]
        program["visit_interval_days"] = interval
        program["needs_revision_reason"] = None
        program["last_revised_at"] = store.now_iso()

    for visit in held:
        with mutate(visit):
            visit["status"] = "SCHEDULED"
            visit["held_reason"] = None

    calc.recompute_program(program)
    calc.recompute_partners({partner["id"], old_partner_id})
    return ok(program)


@bp.post("/pm-programs/<program_id>/terminate")
@require("ServiceOpsAdmin")
def terminate_pm_program(program_id):
    program = get_program(program_id)
    body = get_body()
    field_str(body, "terminate_reason", min_len=1)

    if program["status"] not in ("DRAFT", "ACTIVE", "NEEDS_REVISION"):
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION",
            "Only a DRAFT, ACTIVE or NEEDS_REVISION program may be terminated.",
        )

    had_commitment = program["status"] in ("ACTIVE", "NEEDS_REVISION")
    with mutate(program):
        program["status"] = "TERMINATED"

    if had_commitment:
        for visit in calc.program_visits(program["id"]):
            if visit["status"] in ("SCHEDULED", "ON_HOLD"):
                with mutate(visit):
                    visit["status"] = "CANCELLED"
        calc.recompute_partner(store.service_partners[program["service_partner_id"]])
    return ok(program)


# ---------------------------------------------------------------------------
# visits
# ---------------------------------------------------------------------------
@bp.post("/maintenance-visits")
@require("ServicePartnerTech")
def create_maintenance_visit():
    body = get_body()

    # rung 5 — partner scope through the referenced program, when it resolves
    target = body.get("pm_program_id")
    if isinstance(target, str):
        existing = store.pm_programs.get(target)
        if existing is not None:
            check_partner_scope(existing["service_partner_id"])

    pm_program_id = field_id(body, "pm_program_id")
    serialized_asset_id = field_id(body, "serialized_asset_id")
    scheduled_date, _ = field_datetime(body, "scheduled_date")
    reserved_units = field_int(
        body, "reserved_units", required=False, minimum=0, maximum=50, default=0
    )

    # rung 9
    program = get_program(pm_program_id)
    asset = get_asset(serialized_asset_id)

    # rung 11
    if program["status"] != "ACTIVE":
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION",
            "Only an ACTIVE program may book a preventive visit.",
        )

    partner = store.service_partners[program["service_partner_id"]]
    # rung 17
    _training_current(partner)

    # rung 27
    if (
        asset["facility_id"] != program["facility_id"]
        or asset["status"] != "IN_SERVICE"
    ):
        raise ApiError(
            "ERR_ASSET_NOT_COVERED", "The asset is not covered by this program."
        )

    # rung 35
    if partner["spare_stock_on_hand_units"] < reserved_units:
        raise ApiError(
            "ERR_INSUFFICIENT_PART_STOCK",
            "The partner does not hold enough spare units.",
        )

    visit = new_entity(
        {
            "pm_program_id": program["id"],
            "serialized_asset_id": asset["id"],
            "scheduled_date": scheduled_date,
            "reserved_units": reserved_units,
            "labor_hours": None,
            "status": "SCHEDULED",
            "held_reason": None,
        }
    )
    store.maintenance_visits[visit["id"]] = visit
    calc.recompute_partner(partner)
    return created(visit)


@bp.get("/maintenance-visits")
@require(*ANY_ROLE)
def list_maintenance_visits():
    limit, offset = paging()
    pm_program_id = query_str("pm_program_id")
    serialized_asset_id = query_str("serialized_asset_id")
    status = query_enum("status", VISIT_STATUSES)

    rows = list(store.maintenance_visits.values())
    if pm_program_id is not None:
        rows = [r for r in rows if r["pm_program_id"] == pm_program_id]
    if serialized_asset_id is not None:
        rows = [r for r in rows if r["serialized_asset_id"] == serialized_asset_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = paginate(rows, limit, offset)
    return ok_list(page, limit, offset, total)


@bp.get("/maintenance-visits/<visit_id>")
@require(*ANY_ROLE)
def read_maintenance_visit(visit_id):
    visit = get_visit(visit_id)
    program = store.pm_programs.get(visit["pm_program_id"])
    if program is not None:
        check_partner_scope(program["service_partner_id"])
    return ok(visit)


@bp.post("/maintenance-visits/<visit_id>/complete")
@require("ServicePartnerTech")
def complete_maintenance_visit(visit_id):
    visit = get_visit(visit_id)
    program = store.pm_programs[visit["pm_program_id"]]
    check_partner_scope(program["service_partner_id"])
    body = get_body()
    labor_hours = field_decimal(body, "labor_hours", exclusive_min=0)

    if visit["status"] != "SCHEDULED":
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION", "Only a SCHEDULED visit may be completed."
        )
    if program["status"] != "ACTIVE":
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION", "The owning program must be ACTIVE."
        )

    partner = store.service_partners[program["service_partner_id"]]
    # rung 17
    _training_current(partner)

    with mutate(visit):
        visit["status"] = "COMPLETED"
        visit["labor_hours"] = labor_hours

    calc.recompute_partner(partner)
    asset = store.serialized_assets.get(visit["serialized_asset_id"])
    if asset is not None:
        calc.recompute_asset_service_history(asset)
    return ok(visit)


@bp.post("/maintenance-visits/<visit_id>/cancel")
@require("ServicePartnerTech", "ServiceOpsAdmin")
def cancel_maintenance_visit(visit_id):
    visit = get_visit(visit_id)
    program = store.pm_programs[visit["pm_program_id"]]
    check_partner_scope(program["service_partner_id"])
    body = get_body()
    field_str(body, "cancel_reason", min_len=1)

    if visit["status"] not in ("SCHEDULED", "ON_HOLD"):
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION",
            "Only a SCHEDULED or ON_HOLD visit may be cancelled.",
        )

    with mutate(visit):
        visit["status"] = "CANCELLED"
    calc.recompute_partner(store.service_partners[program["service_partner_id"]])
    return ok(visit)
