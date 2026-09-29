"""Serializers, derived reads, ledger moves and the ordered cascade hops."""

from decimal import Decimal

import calc
from store import ordered, public, store

D0 = Decimal("0")

# work orders whose reservation is still open (a cancel/scrap must write it off)
OPEN_RESERVATION_STATES = {
    "BLANKS_RESERVED", "GRINDING", "POLISHING", "FIGURING",
    "FIGURE_ACCEPTED", "COATING", "COATED", "HELD",
}
# work orders the glass-lot block cascade holds
LOT_BLOCK_HOLD_STATES = [
    "BLANKS_RESERVED", "GRINDING", "POLISHING", "FIGURING",
    "FIGURE_ACCEPTED", "COATING", "COATED",
]
OPEN_RUN_STATES = {"SCHEDULED", "IN_PROCESS"}
STATION_OCCUPYING_RUN_STATES = {"SCHEDULED", "IN_PROCESS", "AWAITING_METROLOGY"}
CHAMBER_OCCUPYING_STATES = {"LOADED", "DEPOSITED", "VERIFIED_FAIL"}
SUPPRESS_PROCESS_ADVANCE = {"SCRAPPED", "CANCELLED", "HELD"}


# --------------------------------------------------------------- collections
def runs_of_work_order(wo_id):
    return ordered([r for r in store.runs.values() if r["work_order_id"] == wo_id])


def active_components(assembly_id):
    return ordered([c for c in store.components.values()
                    if c["assembly_id"] == assembly_id
                    and c["component_status"] == "ACTIVE"])


def components_of_work_order(wo_id, status=None):
    rows = [c for c in store.components.values() if c["work_order_id"] == wo_id
            and (status is None or c["component_status"] == status)]
    return ordered(rows)


def work_orders_of_design(design_id):
    return ordered([w for w in store.work_orders.values()
                    if w["design_id"] == design_id])


def work_orders_of_lot(lot_id):
    return ordered([w for w in store.work_orders.values()
                    if w["glass_lot_id"] == lot_id])


def inspections_of_assembly(assembly_id):
    return ordered([i for i in store.inspections.values()
                    if i["assembly_id"] == assembly_id])


def packages_of_assembly(assembly_id):
    return ordered([p for p in store.packages.values()
                    if p["assembly_id"] == assembly_id])


def governing_classification(design_id):
    rows = ordered([c for c in store.classifications.values()
                    if c["design_id"] == design_id
                    and c["classification_status"] != "LICENSE_DENIED"])
    return rows[0] if rows else None


# ------------------------------------------------------------- derived reads
def instrument_derived(inst):
    days = calc.days_since(store.now_dt(), inst.get("_last_calibrated_dt"))
    eff = calc.effective_uncertainty(inst["base_uncertainty_waves"], days)
    status = "OVERDUE" if days > int(inst["calibration_interval_days"]) else "CALIBRATED"
    return days, eff, status


def required_document_types(assembly_id):
    required = set(calc.BASE_DOCUMENT_TYPES)
    active = active_components(assembly_id)
    wo_ids = {c["work_order_id"] for c in active}
    if wo_ids:
        for cr in store.coating_runs.values():
            if cr["coating_status"] == "VERIFIED_PASS" and cr["work_order_id"] in wo_ids:
                required.add("COATING_SPECTRAL_DATA")
                break
    assembly = store.assemblies.get(assembly_id)
    if assembly is not None:
        gov = governing_classification(assembly["design_id"])
        if gov is not None and gov["license_required"]:
            required.add("EXPORT_LICENSE")
    for ir in store.inspections.values():
        if ir["assembly_id"] == assembly_id and ir["inspection_status"] == "WAIVED":
            required.add("INSPECTION_WAIVER")
            break
    return sorted(required)


def package_view(pkg):
    required = required_document_types(pkg["assembly_id"])
    present = [d["document_type"] for d in pkg["attached_documents"]]
    missing = sorted([t for t in required if t not in set(present)])
    pct = calc.completeness_pct(required, present)
    return required, present, missing, pct


# ------------------------------------------------------------- serializers
def ser_design(row):
    return public(row)


def ser_allocation(row):
    return public(row)


def ser_lot(row):
    return public(row)


def ser_work_order(row):
    return public(row)


def ser_instrument(row):
    out = public(row)
    days, eff, status = instrument_derived(row)
    out["days_since_calibration"] = days
    out["effective_uncertainty_waves"] = float(eff)
    out["instrument_status"] = status
    return out


def ser_run(row):
    return public(row)


def ser_report(row):
    return public(row)


def ser_chamber(row):
    return public(row)


def ser_coating_run(row):
    return public(row)


def ser_assembly(row):
    return public(row)


def ser_component(row):
    return public(row)


def ser_inspection(row):
    return public(row)


def ser_classification(row):
    return public(row)


def ser_package(row):
    out = public(row)
    required, present, missing, pct = package_view(row)
    out["present_document_types"] = present
    out["required_document_types"] = required
    out["missing_document_types"] = missing
    out["completeness_pct"] = float(pct)
    return out


# --------------------------------------------------------- blank ledger moves
def lot_recompute_available(lot):
    lot["available_blank_count"] = (
        int(lot["total_blank_count"])
        - int(lot["reserved_blank_count"])
        - int(lot["consumed_blank_count"])
        - int(lot["scrapped_blank_count"])
    )


def lot_check_depletion(lot):
    if (lot["lot_status"] == "RELEASED"
            and int(lot["available_blank_count"]) == 0
            and int(lot["reserved_blank_count"]) == 0):
        lot["lot_status"] = "DEPLETED"


def lot_reserve(lot, wo):
    lot["reserved_blank_count"] = int(lot["reserved_blank_count"]) + int(
        wo["reserved_blank_count"])
    lot_recompute_available(lot)
    lot_check_depletion(lot)
    store.touch(lot)


def lot_release(lot, wo):
    lot["reserved_blank_count"] = int(lot["reserved_blank_count"]) - int(
        wo["reserved_blank_count"])
    lot_recompute_available(lot)
    lot_check_depletion(lot)
    store.touch(lot)


def lot_consume(lot, wo):
    lot["reserved_blank_count"] = int(lot["reserved_blank_count"]) - int(
        wo["reserved_blank_count"])
    lot["consumed_blank_count"] = int(lot["consumed_blank_count"]) + int(
        wo["element_count"])
    lot_recompute_available(lot)
    lot_check_depletion(lot)
    store.touch(lot)


def lot_write_off_reservation(lot, wo):
    lot["reserved_blank_count"] = int(lot["reserved_blank_count"]) - int(
        wo["reserved_blank_count"])
    lot["scrapped_blank_count"] = int(lot["scrapped_blank_count"]) + int(
        wo["reserved_blank_count"])
    lot_recompute_available(lot)
    lot_check_depletion(lot)
    store.touch(lot)


def lot_write_off_consumed(lot, wo):
    lot["consumed_blank_count"] = int(lot["consumed_blank_count"]) - int(
        wo["element_count"])
    lot["scrapped_blank_count"] = int(lot["scrapped_blank_count"]) + int(
        wo["element_count"])
    lot_recompute_available(lot)
    lot_check_depletion(lot)
    store.touch(lot)


# ---------------------------------------------------- instrument minutes ledger
def instrument_book(inst, minutes):
    inst["booked_minutes_total"] = int(inst["booked_minutes_total"]) + int(minutes)
    store.touch(inst)


def instrument_release(run):
    inst = store.instruments.get(run["metrology_instrument_id"])
    if inst is None:
        return
    inst["booked_minutes_total"] = int(inst["booked_minutes_total"]) - int(
        run["window_minutes"])
    store.touch(inst)


def cancel_run(run, reason):
    run["run_status"] = "CANCELLED"
    run["cancel_reason"] = reason
    store.touch(run)
    instrument_release(run)


# ------------------------------------------------------------ removal ledger
def recompute_removal_ledger(wo):
    rows = [r for r in store.runs.values()
            if r["work_order_id"] == wo["id"]
            and r["run_status"] in ("ACCEPTED", "REWORK_REQUIRED")
            and r["material_removed_nm"] is not None]
    rows.sort(key=lambda r: (r.get("_started_sort") or "", r["_seq"]))
    total = sum((Decimal(r["material_removed_nm"]) for r in rows), D0)
    wo["cumulative_removal_nm"] = total
    wo["remaining_center_thickness_um"] = calc.rhu(
        Decimal(wo["blank_center_thickness_um"]) - total / calc.NM_PER_UM,
        calc.THICKNESS_DECIMALS)


# ------------------------------------------------------- assembly recompute
def recompute_assembly(assembly):
    comps = active_components(assembly["id"])
    el, cen, sub, der, tot = calc.assembly_wavefront(comps)
    assembly["element_rss_waves"] = el
    assembly["centration_error_waves"] = cen
    assembly["subtotal_waves"] = sub
    assembly["cement_derate_waves"] = der
    assembly["total_transmitted_wavefront_waves"] = tot
    return tot


def void_components_and_repair(wo):
    """Hops 3 and 4 of every WorkOrder -> SCRAPPED cascade."""
    victims = components_of_work_order(wo["id"], status="ACTIVE")
    for comp in victims:
        comp["component_status"] = "VOIDED"
        store.touch(comp)
    seen = []
    for comp in victims:
        assembly = store.assemblies.get(comp["assembly_id"])
        if assembly is None or assembly["id"] in seen:
            continue
        seen.append(assembly["id"])
        recompute_assembly(assembly)
        if assembly["assembly_status"] in ("ALIGNED", "SEALED"):
            assembly["assembly_status"] = "MOUNTED"
        store.touch(assembly)


def scrap_work_order(wo, reason):
    """Hops 1..4 of the WorkOrder -> SCRAPPED cascade, in pinned order."""
    prior = wo["process_status"]
    wo["process_status"] = "SCRAPPED"
    wo["scrap_reason"] = reason
    store.touch(wo)

    lot = store.lots.get(wo["glass_lot_id"])
    if lot is not None:
        if prior == "RELEASED_TO_ASSEMBLY":
            lot_write_off_consumed(lot, wo)
        else:
            lot_write_off_reservation(lot, wo)

    void_components_and_repair(wo)


# ------------------------------------------------------- glass lot block hops
def block_lot_cascade(lot, reason):
    lot["lot_status"] = "BLOCKED"
    lot["block_reason"] = reason
    store.touch(lot)

    for wo in work_orders_of_lot(lot["id"]):
        if wo["process_status"] not in LOT_BLOCK_HOLD_STATES:
            continue
        wo["process_status"] = "HELD"
        wo["hold_reason"] = "GLASS_LOT_BLOCKED"
        store.touch(wo)
        for run in runs_of_work_order(wo["id"]):
            if run["run_status"] in OPEN_RUN_STATES:
                cancel_run(run, "WORK_ORDER_HELD")


# -------------------------------------------------- work order cancel hops
def cancel_work_order_cascade(wo, reason):
    wo["process_status"] = "CANCELLED"
    wo["cancel_reason"] = reason
    store.touch(wo)

    lot = store.lots.get(wo["glass_lot_id"])
    if lot is not None:
        lot_release(lot, wo)

    for run in runs_of_work_order(wo["id"]):
        if run["run_status"] in OPEN_RUN_STATES:
            cancel_run(run, "WORK_ORDER_CANCELLED")


# ------------------------------------------- export denial / revocation hops
def export_block_cascade(design_id):
    """Hops 2 and 3 shared by the DENIED decision and the revocation."""
    blocked = []
    for wo in work_orders_of_design(design_id):
        if wo["compliance_status"] in ("UNCLASSIFIED", "SCREENED", "CLEARED"):
            wo["compliance_status"] = "BLOCKED"
            store.touch(wo)
            blocked.append(wo)
    for wo in blocked:
        for comp in components_of_work_order(wo["id"], status="ACTIVE"):
            assembly = store.assemblies.get(comp["assembly_id"])
            if assembly is None:
                continue
            if assembly["assembly_status"] in ("ALIGNED", "SEALED"):
                assembly["assembly_status"] = "EXPORT_BLOCKED"
                store.touch(assembly)


# ------------------------------------------------------- release readiness
def latest_inspection(assembly_id):
    rows = inspections_of_assembly(assembly_id)
    return rows[-1] if rows else None


def inspection_ok(assembly_id):
    latest = latest_inspection(assembly_id)
    return latest is not None and latest["inspection_status"] in ("PASSED", "WAIVED")


def release_gate(assembly):
    """Returns (blocking_error_id, facts) for both release and release-readiness."""
    gov = governing_classification(assembly["design_id"])
    export_ok = gov is not None and gov["classification_status"] in (
        "EXEMPT_CLEARED", "LICENSE_APPROVED")
    insp_ok = inspection_ok(assembly["id"])
    pkgs = packages_of_assembly(assembly["id"])
    pkg = pkgs[0] if pkgs else None
    documentation_ok = pkg is not None and pkg["package_status"] == "APPROVED"

    design = store.designs.get(assembly["design_id"])
    budget = design["transmitted_wavefront_budget_waves"] if design else None
    total = assembly["total_transmitted_wavefront_waves"]
    wavefront_ok = (total is not None and budget is not None
                    and Decimal(total) <= Decimal(budget))

    blocking = None
    if assembly["assembly_status"] != "SEALED":
        blocking = "ERR_INVALID_STATE_TRANSITION"
    elif gov is None:
        blocking = "ERR_EXPORT_CLASSIFICATION_MISSING"
    elif not export_ok:
        blocking = "ERR_EXPORT_LICENSE_NOT_APPROVED"
    elif not insp_ok:
        blocking = "ERR_INSPECTION_NOT_PASSED"
    elif pkg is None:
        blocking = "ERR_DOCUMENTATION_PACKAGE_NOT_FOUND"
    elif not documentation_ok:
        blocking = "ERR_DOCUMENTATION_NOT_APPROVED"

    facts = {
        "gov": gov,
        "export_ok": export_ok,
        "inspection_ok": insp_ok,
        "package": pkg,
        "documentation_ok": documentation_ok,
        "wavefront_ok": wavefront_ok,
        "budget": budget,
        "total": total,
    }
    return blocking, facts
