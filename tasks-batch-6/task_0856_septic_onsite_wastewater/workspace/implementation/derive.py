"""Derived state and the cascade engine (PRD 2.9)."""
import calc
import store
from store import ordered, touch
from util import now

QUALIFYING_WELL_TYPES = ("DOMESTIC", "IRRIGATION")
SETBACK_STICKY = ("VARIANCE_GRANTED", "VARIANCE_DENIED")
DESIGN_GEOMETRY_STATES = ("DRAFT", "UNDER_REVIEW", "REVISIONS_REQUIRED", "APPROVED")


# ------------------------------------------------------------------ selectors
def wells_of_parcel(parcel_id):
    return [w for w in ordered(store.wells.values()) if w["parcel_id"] == parcel_id]


def operating_permits_of_parcel(parcel_id):
    return [p for p in ordered(store.operating_permits.values())
            if p["parcel_id"] == parcel_id]


def repair_orders_of_parcel(parcel_id):
    return [r for r in ordered(store.repair_orders.values())
            if r["parcel_id"] == parcel_id]


def construction_permits_of_parcel(parcel_id):
    return [p for p in ordered(store.construction_permits.values())
            if p["parcel_id"] == parcel_id]


def inspections_of_permit(permit_id):
    return [i for i in ordered(store.inspections.values())
            if i["construction_permit_id"] == permit_id]


def transfer_inspections_of_permit(operating_permit_id):
    return [t for t in ordered(store.transfer_inspections.values())
            if t["operating_permit_id"] == operating_permit_id]


def designs_of_evaluation(evaluation_id):
    return [d for d in ordered(store.system_designs.values())
            if d["site_evaluation_id"] == evaluation_id]


def parcel_of_design(design):
    evaluation = store.site_evaluations.get(design["site_evaluation_id"])
    if evaluation is None:
        return None
    return store.parcels.get(evaluation["parcel_id"])


def designs_of_parcel(parcel_id):
    out = []
    for design in ordered(store.system_designs.values()):
        evaluation = store.site_evaluations.get(design["site_evaluation_id"])
        if evaluation is not None and evaluation["parcel_id"] == parcel_id:
            out.append(design)
    return out


# ------------------------------------------------------------ site evaluation
def recompute_evaluation_rates(evaluation):
    preliminary, certified = calc.perc_rate_evaluation(evaluation["perc_holes"])
    evaluation["preliminary_perc_rate_min_per_in"] = preliminary
    evaluation["certified_perc_rate_min_per_in"] = certified
    evaluation["soil_loading_rate_gpd_per_sqft"] = calc.soil_loading_rate(certified)


# ------------------------------------------------------------- system design
def recompute_design_sizing(design):
    evaluation = store.site_evaluations[design["site_evaluation_id"]]
    design["design_flow_gpd"] = calc.design_flow(design["bedrooms"])
    design["required_drainfield_sqft"] = calc.required_drainfield_area(
        design["design_flow_gpd"], design["system_type"],
        evaluation["soil_loading_rate_gpd_per_sqft"],
        evaluation["depth_to_limiting_layer_in"])


def recompute_design_setback(design, clear_sticky=False):
    evaluation = store.site_evaluations[design["site_evaluation_id"]]
    qualifying = [w for w in wells_of_parcel(evaluation["parcel_id"])
                  if w["well_type"] in QUALIFYING_WELL_TYPES]
    nearest, setback, status = calc.well_setback_evaluation(
        qualifying, design["drainfield_x_ft"], design["drainfield_y_ft"],
        design["system_type"], evaluation["soil_group"])
    design["nearest_well_distance_ft"] = nearest
    design["required_setback_ft"] = setback
    if clear_sticky or design["setback_status"] not in SETBACK_STICKY:
        design["setback_status"] = status


def recompute_design(design, clear_sticky=False):
    recompute_design_sizing(design)
    recompute_design_setback(design, clear_sticky=clear_sticky)


def supersede_designs_of_evaluation(evaluation_id):
    for design in designs_of_evaluation(evaluation_id):
        if design["status"] in DESIGN_GEOMETRY_STATES:
            design["status"] = "SUPERSEDED"
            touch(design)


# -------------------------------------------------------------------- parcel
def recompute_parcel(parcel, force_bump=False):
    """Re-derive every parcel roll-up from scratch; bump only on real change."""
    parcel_id = parcel["id"]
    before = (parcel["permitted_design_flow_gpd"], parcel["fee_balance_cents"],
              parcel["open_repair_order_count"], parcel["water_quality_flag"],
              parcel["transfer_hold"], parcel["risk_tier"],
              parcel["max_design_flow_gpd"])

    permitted = 0
    for permit in construction_permits_of_parcel(parcel_id):
        if permit["status"] in calc.LIVE_PERMIT_STATES:
            permitted += permit["design_flow_gpd"]

    open_orders = sum(1 for r in repair_orders_of_parcel(parcel_id)
                      if r["status"] in calc.OPEN_REPAIR_STATES)

    parcel_wells = wells_of_parcel(parcel_id)
    water_flag = any(w["advisory_status"] in ("ADVISORY", "CONDEMNED")
                     for w in parcel_wells)
    any_condemned = any(w["advisory_status"] == "CONDEMNED" for w in parcel_wells)

    permits = operating_permits_of_parcel(parcel_id)
    any_revoked = any(p["status"] == "REVOKED" for p in permits)
    any_delinquent = any(p["compliance_status"] == "DELINQUENT" for p in permits)

    parcel["permitted_design_flow_gpd"] = permitted
    parcel["fee_balance_cents"] = (parcel["fees_assessed_cents"]
                                   - parcel["fees_paid_cents"]
                                   - parcel["fees_credited_cents"])
    parcel["open_repair_order_count"] = open_orders
    parcel["water_quality_flag"] = water_flag
    parcel["transfer_hold"] = bool(open_orders > 0 or any_revoked or any_condemned)
    parcel["risk_tier"] = calc.parcel_risk_tier(water_flag, open_orders,
                                                any_delinquent, any_revoked)
    parcel["max_design_flow_gpd"] = calc.parcel_max_design_flow(
        parcel["lot_size_sqft"])

    after = (parcel["permitted_design_flow_gpd"], parcel["fee_balance_cents"],
             parcel["open_repair_order_count"], parcel["water_quality_flag"],
             parcel["transfer_hold"], parcel["risk_tier"],
             parcel["max_design_flow_gpd"])
    if force_bump or before != after:
        touch(parcel)
    return parcel


# ---------------------------------------------------------- operating permit
def recompute_schedule_fields(permit):
    """Re-derive interval, deadline and compliance posture WITHOUT bumping."""
    anchor = permit["last_pumped_on"] or permit["issued_on"]
    months, due = calc.pumping_interval(permit["tank_capacity_gal"],
                                        permit["household_size"],
                                        permit["monitoring_required"], anchor)
    permit["pumping_interval_months"] = months
    permit["next_pumping_due_on"] = due
    permit["compliance_status"] = calc.pumping_compliance_status(now(), due)


def recompute_operating_permit_schedule(permit):
    """Re-derive the servicing schedule; bump once when anything moved."""
    before = (permit["pumping_interval_months"], permit["next_pumping_due_on"],
              permit["compliance_status"])
    recompute_schedule_fields(permit)
    after = (permit["pumping_interval_months"], permit["next_pumping_due_on"],
             permit["compliance_status"])
    if before != after:
        touch(permit)
    return before != after


def recompute_operating_permit_compliance(permit):
    before = permit["compliance_status"]
    permit["compliance_status"] = calc.pumping_compliance_status(
        now(), permit["next_pumping_due_on"])
    if before != permit["compliance_status"]:
        touch(permit)
        return True
    return False


def block_transfer_inspections(operating_permit_id):
    for req in transfer_inspections_of_permit(operating_permit_id):
        if req["status"] == "REQUESTED":
            req["status"] = "BLOCKED"
            touch(req)


def unblock_transfer_inspections(operating_permit_id):
    for req in transfer_inspections_of_permit(operating_permit_id):
        if req["status"] == "BLOCKED":
            req["status"] = "REQUESTED"
            touch(req)


def deny_transfer_inspections(operating_permit_id):
    for req in transfer_inspections_of_permit(operating_permit_id):
        if req["status"] in ("REQUESTED", "BLOCKED"):
            req["status"] = "DENIED"
            req["certificate_grade"] = "UNSATISFACTORY"
            touch(req)


def set_operating_permit_status(permit, new_status):
    """Move the administrative dimension and run its transfer-certificate cascade.

    The compliance dimension is never rewritten here -- the two dimensions of
    the operating permit evolve independently (PRD 3.7).
    """
    if permit["status"] == new_status:
        return
    permit["status"] = new_status
    touch(permit)
    if new_status == "SUSPENDED":
        block_transfer_inspections(permit["id"])
    elif new_status == "ACTIVE":
        unblock_transfer_inspections(permit["id"])
    elif new_status == "REVOKED":
        deny_transfer_inspections(permit["id"])


# ------------------------------------------------- groundwater advisory cascade
def water_quality_cascade(parcel):
    """Cascade steps 2-4 of PRD 3.2, completed inside the triggering request."""
    recompute_parcel(parcel)
    if parcel["water_quality_flag"]:
        for permit in operating_permits_of_parcel(parcel["id"]):
            if permit["status"] == "ACTIVE" and not permit["monitoring_required"]:
                permit["monitoring_required"] = True
                recompute_schedule_fields(permit)
                touch(permit)
    recompute_parcel(parcel)


# ----------------------------------------------------- construction permit end
def release_permit(permit, cancel_failed):
    """Shared tail of VOID (cancel_failed=True) and EXPIRY (cancel_failed=False)."""
    targets = ("SCHEDULED", "FAILED") if cancel_failed else ("SCHEDULED",)
    for inspection in inspections_of_permit(permit["id"]):
        if inspection["status"] in targets:
            inspection["status"] = "CANCELLED"
            touch(inspection)
