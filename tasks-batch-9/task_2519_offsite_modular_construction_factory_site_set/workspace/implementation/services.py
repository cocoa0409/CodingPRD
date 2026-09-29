"""Cross-aggregate derivations, conserved ledgers and the multi-link cascades.

Every derived field is recomputed by a FULL RE-SCAN of the children, never by
incrementing a counter, so the derivation walks backwards when a child regresses.
"""

import calc
from errors import ApiError
from store import db, now, sorted_rows, touch

# ---------------------------------------------------------------------------
# existence resolution (ladder ranks 4 and 5)
# ---------------------------------------------------------------------------
_NOT_FOUND = {
    "factories": "ERR_FACTORY_NOT_FOUND",
    "agencies": "ERR_AGENCY_NOT_FOUND",
    "projects": "ERR_PROJECT_NOT_FOUND",
    "design_packages": "ERR_DESIGN_PACKAGE_NOT_FOUND",
    "modules": "ERR_MODULE_NOT_FOUND",
    "permits": "ERR_PERMIT_NOT_FOUND",
    "inspections": "ERR_INSPECTION_NOT_FOUND",
    "shipments": "ERR_SHIPMENT_NOT_FOUND",
    "defect_claims": "ERR_DEFECT_CLAIM_NOT_FOUND",
    "draws": "ERR_DRAW_NOT_FOUND",
}


def _fetch(collection, row_id):
    table = getattr(db, collection)
    row = table.get(row_id)
    if row is None:
        raise ApiError(_NOT_FOUND[collection], "%s does not exist" % row_id)
    return row


def get_factory(row_id):
    return _fetch("factories", row_id)


def get_agency(row_id):
    return _fetch("agencies", row_id)


def get_project(row_id):
    return _fetch("projects", row_id)


def get_package(row_id):
    return _fetch("design_packages", row_id)


def get_module(row_id):
    return _fetch("modules", row_id)


def get_permit(row_id):
    return _fetch("permits", row_id)


def get_inspection(row_id):
    return _fetch("inspections", row_id)


def get_shipment(row_id):
    return _fetch("shipments", row_id)


def get_claim(row_id):
    return _fetch("defect_claims", row_id)


def get_draw(row_id):
    return _fetch("draws", row_id)


# ---------------------------------------------------------------------------
# child accessors — always created_at ascending
# ---------------------------------------------------------------------------
def _children(table, key, value):
    return sorted_rows([r for r in table.values() if r[key] == value])


def modules_of_project(project_id):
    return _children(db.modules, "project_id", project_id)


def packages_of_project(project_id):
    return _children(db.design_packages, "project_id", project_id)


def shipments_of_project(project_id):
    return _children(db.shipments, "project_id", project_id)


def permits_of_project(project_id):
    return _children(db.permits, "project_id", project_id)


def draws_of_project(project_id):
    return _children(db.draws, "project_id", project_id)


def modules_of_shipment(shipment_id):
    return _children(db.modules, "shipment_id", shipment_id)


def inspections_of_module(module_id):
    return _children(db.inspections, "module_id", module_id)


def claims_of_module(module_id):
    return _children(db.defect_claims, "module_id", module_id)


def factory_of_project(project):
    return db.factories.get(project["factory_id"])


def modules_of_factory(factory_id):
    project_ids = set(
        p["id"] for p in db.projects.values() if p["factory_id"] == factory_id
    )
    return sorted_rows(
        [m for m in db.modules.values() if m["project_id"] in project_ids]
    )


# ---------------------------------------------------------------------------
# calculations.permit_posture_derivation
# ---------------------------------------------------------------------------
def _live(project_id, track, scope):
    instant = now()
    for permit in db.permits.values():
        if permit["project_id"] != project_id:
            continue
        if permit["track"] != track or permit["scope"] != scope:
            continue
        if permit["status"] != "APPROVED":
            continue
        expires = permit["expires_at"]
        if expires is None or expires > instant:
            return permit
    return None


def live_plan_review(project_id):
    """The project's live STATE_MODULAR_PROGRAM / PLAN_REVIEW approval, or None."""
    return _live(project_id, "STATE_MODULAR_PROGRAM", "PLAN_REVIEW")


def derive_permit_posture(project):
    project_id = project["id"]
    state_ok = live_plan_review(project_id) is not None
    insignia_ok = _live(project_id, "STATE_MODULAR_PROGRAM", "INSIGNIA") is not None
    foundation_ok = _live(project_id, "LOCAL_AHJ", "FOUNDATION") is not None
    set_ok = _live(project_id, "LOCAL_AHJ", "SET") is not None
    occ_ok = _live(project_id, "LOCAL_AHJ", "OCCUPANCY") is not None
    site_ok = foundation_ok or set_ok

    if occ_ok and set_ok and state_ok and insignia_ok:
        return "OCCUPANCY_CLEARED"
    if set_ok and state_ok and insignia_ok:
        return "SET_CLEARED"
    if state_ok and not site_ok:
        return "STATE_CLEARED_ONLY"
    if site_ok and not state_ok:
        return "SITE_CLEARED_ONLY"
    if state_ok and site_ok:
        # bifurcation tie-break: the state track releases factory production
        return "STATE_CLEARED_ONLY"
    return "DUAL_BLOCKED"


# ---------------------------------------------------------------------------
# calculations.project_phase_derivation  (full re-scan, walks backwards)
# ---------------------------------------------------------------------------
def derive_phase(project):
    modules = modules_of_project(project["id"])
    connected = sum(1 for m in modules if m["site_status"] == "CONNECTED")
    if project["planned_module_count"] > 0 and connected >= project["planned_module_count"]:
        return "CLOSEOUT"
    if any(m["site_status"] in ("SET", "CONNECTED") for m in modules):
        return "SETTING"
    if any(
        s["status"] in ("DISPATCHED", "DELIVERED")
        for s in shipments_of_project(project["id"])
    ):
        return "SHIPPING"
    if any(m["production_status"] in ("IN_LINE", "LINE_COMPLETE") for m in modules):
        return "IN_PRODUCTION"
    if any(
        p["freeze_state"] in ("FROZEN", "SUPERSEDED")
        for p in packages_of_project(project["id"])
    ):
        return "DESIGN_FROZEN"
    return "PRECONSTRUCTION"


def recount_modules(project):
    modules = modules_of_project(project["id"])
    project["modules_set_count"] = sum(
        1 for m in modules if m["site_status"] in ("SET", "CONNECTED")
    )
    project["modules_connected_count"] = sum(
        1 for m in modules if m["site_status"] == "CONNECTED"
    )


def refresh_project(project):
    """Recompute every pure derivation on the project row WITHOUT bumping version."""
    recount_modules(project)
    project["phase"] = derive_phase(project)
    project["permit_posture"] = derive_permit_posture(project)


# ---------------------------------------------------------------------------
# calculations.module_exposure_hours / module_wip_earned_cents
# ---------------------------------------------------------------------------
def refresh_exposure(module):
    module["exposure_open_hours"] = calc.exposure_hours(module, now())
    return module["exposure_open_hours"]


def recompute_wip(module):
    project = db.projects.get(module["project_id"])
    factory = factory_of_project(project) if project else None
    if factory is None:
        module["wip_earned_cents"] = 0
    else:
        module["wip_earned_cents"] = calc.wip_station_progress(module, factory)
    return module["wip_earned_cents"]


# ---------------------------------------------------------------------------
# calculations.draw_certification_amount — the basis
# ---------------------------------------------------------------------------
def draw_basis(project, basis_mode):
    """(basis_module_count, basis_earned_cents) with per-module rounding FIRST.

    Modules are enumerated created_at ascending; ordering by id is forbidden.
    """
    factory = factory_of_project(project)
    modules = modules_of_project(project["id"])
    if basis_mode == "WIP_DEPOSIT":
        selected = [
            m
            for m in modules
            if m["production_status"] in ("SLOTTED", "IN_LINE", "LINE_COMPLETE")
            and m["qc_status"] != "HOLD"
        ]
        per_module = [
            calc.wip_station_progress(m, factory) if factory else 0 for m in selected
        ]
    else:
        selected = [
            m for m in modules if m["site_status"] in ("DELIVERED", "SET", "CONNECTED")
        ]
        per_module = [
            calc.wip_milestone_delivered(m, factory) if factory else 0 for m in selected
        ]
    return len(selected), sum(per_module)


def requested_from_basis(project, basis_mode, basis_earned_cents):
    if basis_mode == "WIP_DEPOSIT":
        return calc.rhu_cents(
            calc.dec(basis_earned_cents) * calc.dec(project["deposit_pct"])
        )
    return int(basis_earned_cents)


def recompute_draft_draws(project):
    """DRAFT draws track live module state; they are provisional, so no version bump."""
    for draw in draws_of_project(project["id"]):
        if draw["status"] != "DRAFT":
            continue
        count, earned = draw_basis(project, draw["basis_mode"])
        draw["basis_module_count"] = count
        draw["basis_earned_cents"] = earned
        draw["requested_cents"] = requested_from_basis(
            project, draw["basis_mode"], earned
        )


# ---------------------------------------------------------------------------
# calculations.shipment_permit_fee_and_escort
# ---------------------------------------------------------------------------
def recompute_shipment_aggregates(shipment):
    """Re-derive the whole transport envelope from the modules actually aboard."""
    modules = modules_of_shipment(shipment["id"])
    shipment["loaded_module_count"] = len(modules)
    new_class = calc.widest_envelope([m["envelope_class"] for m in modules])
    shipment["max_envelope_class"] = new_class
    state_count = len(shipment["route_state_codes"])

    if shipment["route_survey_state"] == "NOT_REQUIRED" and new_class in (
        "OVERWIDTH",
        "SUPERLOAD",
    ):
        shipment["route_survey_state"] = "REQUIRED"
        if shipment["status"] == "DRAFT":
            shipment["status"] = "SURVEY_REQUIRED"
    elif shipment["route_survey_state"] == "REQUIRED" and new_class == "STANDARD":
        # the survey axis is independent — the obligation can be lost again
        shipment["route_survey_state"] = "NOT_REQUIRED"
        shipment["escort_required"] = False
        shipment["escort_confirmed"] = False
        shipment["permit_fee_cents"] = 0
        shipment["permit_expires_at"] = None
        shipment["survey_completed_at"] = None
        return

    shipment["permit_fee_cents"] = calc.permit_fee_cents(new_class, state_count)
    required = calc.escort_required(new_class, state_count)
    shipment["escort_required"] = required
    if not required:
        shipment["escort_confirmed"] = False


# ---------------------------------------------------------------------------
# conserved capacity ledger on Factory.committed_line_minutes
# ---------------------------------------------------------------------------
def release_slot(module, factory):
    """Give the takt window back; the ledger returns to its pre-schedule value."""
    minutes = module["line_slot_minutes"] or 0
    if factory is not None and minutes:
        factory["committed_line_minutes"] -= minutes
        if factory["committed_line_minutes"] < 0:
            factory["committed_line_minutes"] = 0
        return True
    return False


def reset_shipment_transport(shipment):
    """Wholesale transport reset used by the compensating paths (QC hold, cancel)."""
    modules = modules_of_shipment(shipment["id"])
    shipment["loaded_module_count"] = len(modules)
    new_class = calc.widest_envelope([m["envelope_class"] for m in modules])
    shipment["max_envelope_class"] = new_class
    state_count = len(shipment["route_state_codes"])
    shipment["route_survey_state"] = (
        "REQUIRED" if new_class in ("OVERWIDTH", "SUPERLOAD") else "NOT_REQUIRED"
    )
    shipment["permit_fee_cents"] = calc.permit_fee_cents(new_class, state_count)
    shipment["escort_required"] = calc.escort_required(new_class, state_count)
    shipment["escort_confirmed"] = False
    shipment["permit_expires_at"] = None
    shipment["survey_completed_at"] = None


# ---------------------------------------------------------------------------
# CASCADE A — five links, fired by a review-decision of FREEZE
# ---------------------------------------------------------------------------
def supersession_cascade(package, project):
    predecessor_id = package["supersedes_package_id"]
    if not predecessor_id:
        return
    predecessor = db.design_packages.get(predecessor_id)
    if predecessor is None or predecessor["freeze_state"] != "FROZEN":
        return

    # LINK 2 — the predecessor leaves FROZEN for good
    predecessor["freeze_state"] = "SUPERSEDED"
    touch(predecessor)

    # LINK 3 — every APPROVED permit pinned to it drops back to CONDITIONS_ISSUED
    demoted = []
    for permit in permits_of_project(project["id"]):
        if (
            permit["pinned_package_id"] == predecessor_id
            and permit["status"] == "APPROVED"
        ):
            permit["status"] = "CONDITIONS_ISSUED"
            permit["conditions_count"] += 1
            permit["decided_at"] = now()
            touch(permit)
            demoted.append(permit)

    if not demoted:
        return

    # LINK 4 — the plan-review approval left APPROVED, so slotted work is released
    factory = factory_of_project(project)
    factory_dirty = False
    for module in modules_of_project(project["id"]):
        if module["production_status"] != "SLOTTED":
            continue
        if release_slot(module, factory):
            factory_dirty = True
        module["production_status"] = "PLANNED"
        module["line_slot_start"] = None
        module["line_slot_end"] = None
        module["line_slot_minutes"] = 0
        recompute_wip(module)
        touch(module)
    if factory_dirty:
        touch(factory)


# ---------------------------------------------------------------------------
# CASCADE B — three links, fired by a FAIL that places an agency hold
# ---------------------------------------------------------------------------
def qc_hold_cascade(module, project):
    """Returns the Shipment the module was pulled off, or None."""
    unloaded = None
    shipment_id = module["shipment_id"]
    if shipment_id:
        shipment = db.shipments.get(shipment_id)
        if shipment is not None and shipment["status"] in (
            "DRAFT",
            "SURVEY_REQUIRED",
            "PERMITTED",
        ):
            # LINK B2 — the module comes off the load and returns to the plant
            module["shipment_id"] = None
            if module["site_status"] == "LOADED":
                module["site_status"] = "AT_FACTORY"
            # LINK B3 — the load's envelope, fee, escort and survey are re-derived
            reset_shipment_transport(shipment)
            shipment["status"] = "DRAFT"
            touch(shipment)
            unloaded = shipment
    recompute_wip(module)
    if project is not None:
        recompute_draft_draws(project)
    return unloaded


# ---------------------------------------------------------------------------
# logical-clock advance sweep
# ---------------------------------------------------------------------------
def sweep_clock(instant):
    """Expire approvals, re-derive affected postures, age weather exposure."""
    affected_projects = set()
    for permit in sorted_rows(list(db.permits.values())):
        if permit["status"] != "APPROVED":
            continue
        expires = permit["expires_at"]
        if expires is not None and expires <= instant:
            permit["status"] = "EXPIRED"
            touch(permit)
            affected_projects.add(permit["project_id"])

    for project_id in sorted(affected_projects):
        project = db.projects.get(project_id)
        if project is None:
            continue
        refresh_project(project)
        touch(project)

    # exposure is a pure read-time derivation — it never bumps a module version
    for module in db.modules.values():
        if module["site_status"] == "SET" and module["connected_at"] is None:
            refresh_exposure(module)
