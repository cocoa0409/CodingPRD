"""Derived-field computation and row projections.

Every clock-dependent or aggregate value is recomputed on demand -- on reads and
on mutations alike -- so no derived value ever lags the logical clock.
"""

from decimal import Decimal

from db import db, now
from util import D, add_days, iso, q, q1, q3, q4, qd
from services import calc


# ---------------------------------------------------------------------------
# lookups
# ---------------------------------------------------------------------------

def facility(fid):
    return db.facilities.get(fid)


def generator(gid):
    return db.generators.get(gid)


def profile(pid):
    return db.profiles.get(pid)


def unit(uid):
    return db.units.get(uid)


def manifest(mid):
    return db.manifests.get(mid)


def line(lid):
    return db.lines.get(lid)


def container(cid):
    return db.containers.get(cid)


def batch(bid):
    return db.batches.get(bid)


def lines_of(manifest_id):
    return sorted([r for r in db.lines.values() if r["manifest_id"] == manifest_id],
                  key=lambda r: r["line_number"])


def containers_of_line(line_id):
    return [c for c in db.containers.values() if c["manifest_line_id"] == line_id]


def containers_of_unit(unit_id):
    return [c for c in db.containers.values() if c["storage_unit_id"] == unit_id]


def containers_of_profile(profile_id):
    return [c for c in db.containers.values() if c["waste_profile_id"] == profile_id]


def batches_of_unit(unit_id):
    return [b for b in db.batches.values() if b["storage_unit_id"] == unit_id]


def batches_of_facility(facility_id):
    return [b for b in db.batches.values() if b["facility_id"] == facility_id]


def units_of_facility(facility_id):
    return [u for u in db.units.values() if u["facility_id"] == facility_id]


def manifests_of_facility(facility_id):
    return [m for m in db.manifests.values() if m["facility_id"] == facility_id]


def manifests_of_generator(generator_id):
    return [m for m in db.manifests.values() if m["generator_id"] == generator_id]


def profiles_of_generator(generator_id):
    return [p for p in db.profiles.values() if p["generator_id"] == generator_id]


def instruments_of_facility(facility_id):
    return [i for i in db.instruments.values() if i["facility_id"] == facility_id]


def findings_of_facility(facility_id):
    return [f for f in db.findings.values() if f["facility_id"] == facility_id]


def repair_orders_of_unit(unit_id):
    return [o for o in db.repair_orders.values() if o["storage_unit_id"] == unit_id]


def batch_containers(b):
    return [db.containers[cid] for cid in b["container_ids"] if cid in db.containers]


# ---------------------------------------------------------------------------
# lazily derived lifecycle statuses (PRD 2.5 / 3.1 / 3.3)
# ---------------------------------------------------------------------------

def permit_status(f):
    stored = f["permit_status"]
    if stored in ("ACTIVE", "RENEWAL_PENDING") and f["permit_expires_at"] is not None:
        if now() > f["permit_expires_at"]:
            return "EXPIRED"
    return stored


def profile_status(p):
    if p["status"] == "APPROVED" and p["recertification_due_at"] is not None:
        if now() > p["recertification_due_at"]:
            return "EXPIRED"
    return p["status"]


def profile_recertification_lapsed(p):
    return p["recertification_due_at"] is not None and now() > p["recertification_due_at"]


# ---------------------------------------------------------------------------
# Container
# ---------------------------------------------------------------------------

def container_fill_ratio(c):
    return qd(D(c["net_weight_kg"]) / D(c["capacity_kg"]), 4)


def container_accumulation_days(c):
    delta = now() - c["accumulation_start_date"]
    return int(delta.total_seconds() // 86400)


def container_ten_day_overdue(c):
    u = unit(c["storage_unit_id"])
    if u is None or u["unit_type"] != "TEN_DAY_TRANSFER":
        return False
    return container_accumulation_days(c) > calc.TEN_DAY_LIMIT_DAYS


# ---------------------------------------------------------------------------
# ManifestLine
# ---------------------------------------------------------------------------

def allocated_container_mass(line_id):
    total = Decimal(0)
    for c in containers_of_line(line_id):
        if c["custody_state"] != "VOIDED":
            total += D(c["net_weight_kg"])
    return qd(total, 3)


def line_remaining_mass(ln):
    return D(ln["accepted_quantity_kg"] or 0) - allocated_container_mass(ln["id"])


# ---------------------------------------------------------------------------
# StorageUnit
# ---------------------------------------------------------------------------

OCCUPYING_STATES = ("FILLING", "SEALED", "STAGED")


def unit_container_count(u):
    return sum(1 for c in containers_of_unit(u["id"]) if c["custody_state"] in OCCUPYING_STATES)


def unit_stored_kg(u):
    total = Decimal(0)
    for c in containers_of_unit(u["id"]):
        if c["custody_state"] in OCCUPYING_STATES:
            total += D(c["net_weight_kg"])
    return qd(total, 3)


def unit_reserved_kg(u):
    total = Decimal(0)
    for b in batches_of_unit(u["id"]):
        if b["status"] in ("PLANNED", "IN_TREATMENT"):
            total += D(b["input_mass_kg"])
    return qd(total, 3)


def unit_utilization(u):
    return qd((unit_stored_kg(u) + unit_reserved_kg(u)) / D(u["permitted_capacity_kg"]), 4)


def unit_effective_aisle(u):
    return qd(calc.effective_aisle_width(u["aisle_width_cm"], unit_container_count(u),
                                         u["aisle_free_container_capacity"]), 1)


def unit_inspection_overdue(u):
    return now() > add_days(u["last_inspection_at"], u["inspection_frequency_days"])


def unit_posture(u):
    """calculations.storage_unit_posture -- inspection_overdue is deliberately
    NOT part of the posture ladder."""
    if u["status"] in ("CLOSING", "CLOSED"):
        return "CLOSED"
    residents = containers_of_unit(u["id"])
    if any(c["compliance_state"] == "CONDEMNED" for c in residents):
        return "SUSPENDED"
    if any(repair_order_overdue(o) for o in repair_orders_of_unit(u["id"])):
        return "SUSPENDED"
    if any(c["compliance_state"] == "DEFICIENT" for c in residents):
        return "RESTRICTED"
    if unit_utilization(u) >= D(calc.UTILIZATION_RESTRICT_THRESHOLD):
        return "RESTRICTED"
    return "OPEN"


# ---------------------------------------------------------------------------
# EmissionRepairOrder / ComplianceFinding
# ---------------------------------------------------------------------------

def repair_order_overdue(o):
    if o["status"] == "REPAIRED":
        return False
    deadline = o["delayed_due_at"] if o["status"] == "DELAYED" and o["delayed_due_at"] else o["repair_due_at"]
    return now() > deadline


def finding_overdue(f):
    if f["status"] not in ("OPEN", "REOPENED"):
        return False
    return now() > f["corrective_action_due_at"]


def corrective_action_status(facility_id):
    rows = findings_of_facility(facility_id)
    if not rows:
        return "NONE"
    if any(f["status"] in ("OPEN", "REOPENED") for f in rows):
        return "OPEN"
    if any(f["status"] == "RESPONDED" for f in rows):
        return "IN_PROGRESS"
    return "COMPLETED"


def open_snc_finding_count(facility_id):
    return sum(1 for f in findings_of_facility(facility_id)
               if f["finding_class"] == "SNC" and f["status"] in ("OPEN", "RESPONDED", "REOPENED"))


# ---------------------------------------------------------------------------
# Facility mass ledger and financial assurance
# ---------------------------------------------------------------------------

def facility_ledger_lines(facility_id):
    out = []
    for m in manifests_of_facility(facility_id):
        if m["status"] in calc.LEDGER_MANIFEST_STATUSES:
            out.extend(lines_of(m["id"]))
    return out


def facility_all_lines(facility_id):
    out = []
    for m in manifests_of_facility(facility_id):
        out.extend(lines_of(m["id"]))
    return out


def facility_metrics(f):
    fid = f["id"]
    ledger_lines = facility_ledger_lines(fid)
    all_lines = facility_all_lines(fid)

    received = sum((D(ln["received_quantity_kg"] or 0) for ln in ledger_lines), Decimal(0))
    held = sum((unit_stored_kg(u) for u in units_of_facility(fid)), Decimal(0))
    unallocated = sum((D(ln["accepted_quantity_kg"] or 0) - allocated_container_mass(ln["id"])
                       for ln in all_lines), Decimal(0))
    returned = sum((D(ln["returned_quantity_kg"] or 0) for ln in all_lines), Decimal(0))

    residue = Decimal(0)
    destroyed = Decimal(0)
    liability = 0
    for b in batches_of_facility(fid):
        if b["status"] in calc.RESIDUE_BATCH_STATUSES:
            residue += D(b["residue_mass_kg"] or 0)
            destroyed += D(b["input_mass_kg"]) - D(b["residue_mass_kg"] or 0)
        if b["status"] in ("PLANNED", "IN_TREATMENT"):
            liability += int(b["estimated_treatment_liability_cents"])

    held_q = qd(held, 3)
    unallocated_q = qd(unallocated, 3)
    returned_q = qd(returned, 3)
    residue_q = qd(residue, 3)
    destroyed_q = qd(destroyed, 3)

    posted = sum(int(i["face_amount_cents"]) for i in instruments_of_facility(fid)
                 if i["status"] == "ACTIVE")
    snc = open_snc_finding_count(fid)
    figures = calc.assurance_figures(held_q, f["post_closure_cost_cents"], snc, liability, posted)

    metrics = {
        "open_snc_finding_count": snc,
        "corrective_action_status": corrective_action_status(fid),
        "received_mass_kg": q(qd(received, 3), 3),
        "held_mass_kg": q(held_q, 3),
        "unallocated_receipt_kg": q(unallocated_q, 3),
        "returned_mass_kg": q(returned_q, 3),
        "treated_residue_kg": q(residue_q, 3),
        "destroyed_mass_kg": q(destroyed_q, 3),
        "mass_ledger_kg": q(held_q + unallocated_q + returned_q + residue_q + destroyed_q, 3),
        "active_treatment_liability_cents": liability,
        "posted_assurance_cents": posted,
    }
    metrics.update(figures)
    return metrics


def facility_shortfall(f):
    return facility_metrics(f)["assurance_shortfall_cents"]


def facility_required_assurance(f):
    return facility_metrics(f)["required_assurance_cents"]


# ---------------------------------------------------------------------------
# Generator reliability
# ---------------------------------------------------------------------------

def closed_manifests_of_generator(generator_id):
    rows = [m for m in manifests_of_generator(generator_id)
            if m["status"] in calc.CLOSED_MANIFEST_STATUSES]
    rows.sort(key=lambda m: (m["arrived_at"] or m["created_at"], m["created_at"], m["_seq"]), reverse=True)
    return rows


def generator_scores(g):
    closed = closed_manifests_of_generator(g["id"])
    statuses = [profile_status(p) for p in profiles_of_generator(g["id"])]
    rolling = calc.reliability_score(closed[:calc.ROLLING_WINDOW_SIZE], statuses)
    lifetime = calc.reliability_score(closed, statuses)
    return rolling, lifetime


# ---------------------------------------------------------------------------
# LDR family selection (shared by dominant_compatibility_class)
# ---------------------------------------------------------------------------

def dominant_container(b):
    """The staged container with the greatest net_weight_kg; ties broken by the
    lowest Container.created_at."""
    members = batch_containers(b)
    if not members:
        return None
    return sorted(members, key=lambda c: (-D(c["net_weight_kg"]), c["created_at"], c["_seq"]))[0]


def dominant_profile(b):
    c = dominant_container(b)
    if c is None:
        return None
    return profile(c["waste_profile_id"])


# ---------------------------------------------------------------------------
# Projections
# ---------------------------------------------------------------------------

def project_facility(f):
    out = {
        "id": f["id"],
        "name": f["name"],
        "epa_id": f["epa_id"],
        "permit_number": f["permit_number"],
        "permit_expires_at": iso(f["permit_expires_at"]),
        "permitted_methods": list(f["permitted_methods"]),
        "max_concurrent_treatment_batches": f["max_concurrent_treatment_batches"],
        "post_closure_cost_cents": f["post_closure_cost_cents"],
        "permit_status": permit_status(f),
        "renewal_requested_at": iso(f["renewal_requested_at"]),
        "requested_permit_expires_at": iso(f["requested_permit_expires_at"]),
    }
    metrics = facility_metrics(f)
    for key in ("open_snc_finding_count", "corrective_action_status", "received_mass_kg",
                "held_mass_kg", "unallocated_receipt_kg", "returned_mass_kg",
                "treated_residue_kg", "destroyed_mass_kg", "mass_ledger_kg",
                "closure_base_cost_cents", "assurance_tier", "closure_cost_estimate_cents",
                "corrective_action_reserve_cents", "active_treatment_liability_cents",
                "required_assurance_cents", "posted_assurance_cents", "assurance_shortfall_cents"):
        out[key] = metrics[key]
    out["created_at"] = iso(f["created_at"])
    out["updated_at"] = iso(f["updated_at"])
    out["version"] = f["version"]
    return out


def project_generator(g):
    rolling, lifetime = generator_scores(g)
    return {
        "id": g["id"],
        "epa_id": g["epa_id"],
        "name": g["name"],
        "generator_category": g["generator_category"],
        "state_code": g["state_code"],
        "status": g["status"],
        "suspension_reason_code": g["suspension_reason_code"],
        "open_charge_cents": g["open_charge_cents"],
        "settled_charge_cents": g["settled_charge_cents"],
        "voided_charge_cents": g["voided_charge_cents"],
        "charge_adjustment_cents": g["charge_adjustment_cents"],
        "reliability_score_rolling": rolling,
        "reliability_score_lifetime": lifetime,
        "created_at": iso(g["created_at"]),
        "updated_at": iso(g["updated_at"]),
        "version": g["version"],
    }


def project_instrument(i):
    return {
        "id": i["id"],
        "facility_id": i["facility_id"],
        "instrument_type": i["instrument_type"],
        "face_amount_cents": i["face_amount_cents"],
        "effective_on": i["effective_on"],
        "status": i["status"],
        "superseded_by_instrument_id": i["superseded_by_instrument_id"],
        "superseded_at": iso(i["superseded_at"]),
        "created_at": iso(i["created_at"]),
        "updated_at": iso(i["updated_at"]),
        "version": i["version"],
    }


def project_profile(p):
    return {
        "id": p["id"],
        "generator_id": p["generator_id"],
        "facility_id": p["facility_id"],
        "waste_codes": list(p["waste_codes"]),
        "physical_form": p["physical_form"],
        "compatibility_class": p["compatibility_class"],
        "ldr_subcategory": p["ldr_subcategory"],
        "declared_constituent_ppm": q1(p["declared_constituent_ppm"]),
        "declared_flash_point_c": q1(p["declared_flash_point_c"]),
        "declared_ph": q1(p["declared_ph"]),
        "requested_treatment_method": p["requested_treatment_method"],
        "recertification_months": p["recertification_months"],
        "status": profile_status(p),
        "required_sample_type": p["required_sample_type"],
        "sample_attempt_count": p["sample_attempt_count"],
        "latest_sample_result": p["latest_sample_result"],
        "approved_treatment_method": p["approved_treatment_method"],
        "approved_at": iso(p["approved_at"]),
        "approved_by_user_id": p["approved_by_user_id"],
        "recertification_due_at": iso(p["recertification_due_at"]),
        "suspension_reason_code": p["suspension_reason_code"],
        "created_at": iso(p["created_at"]),
        "updated_at": iso(p["updated_at"]),
        "version": p["version"],
    }


def project_sample(s):
    return {
        "id": s["id"],
        "waste_profile_id": s["waste_profile_id"],
        "sample_type": s["sample_type"],
        "measured_constituent_ppm": q1(s["measured_constituent_ppm"]),
        "measured_flash_point_c": q1(s["measured_flash_point_c"]),
        "measured_ph": q1(s["measured_ph"]),
        "recorded_by_user_id": s["recorded_by_user_id"],
        "recorded_at": iso(s["recorded_at"]),
        "applied_tolerance_type": s["applied_tolerance_type"],
        "constituent_deviation_pct": q4(s["constituent_deviation_pct"]),
        "result": s["result"],
        "failure_reason_code": s["failure_reason_code"],
        "created_at": iso(s["created_at"]),
    }


def project_unit(u):
    return {
        "id": u["id"],
        "facility_id": u["facility_id"],
        "unit_code": u["unit_code"],
        "unit_type": u["unit_type"],
        "permitted_capacity_kg": q3(u["permitted_capacity_kg"]),
        "aisle_width_cm": q1(u["aisle_width_cm"]),
        "aisle_free_container_capacity": u["aisle_free_container_capacity"],
        "inspection_frequency_days": u["inspection_frequency_days"],
        "allowed_compatibility_classes": list(u["allowed_compatibility_classes"]),
        "air_emission_control_level": u["air_emission_control_level"],
        "containment_volume_l": q3(u["containment_volume_l"]),
        "status": u["status"],
        "closure_plan_ref": u["closure_plan_ref"],
        "last_inspection_at": iso(u["last_inspection_at"]),
        "container_count": unit_container_count(u),
        "stored_kg": q(unit_stored_kg(u), 3),
        "reserved_kg": q(unit_reserved_kg(u), 3),
        "utilization_pct": q(unit_utilization(u), 4),
        "effective_aisle_width_cm": q(unit_effective_aisle(u), 1),
        "inspection_overdue": unit_inspection_overdue(u),
        "posture": unit_posture(u),
        "created_at": iso(u["created_at"]),
        "updated_at": iso(u["updated_at"]),
        "version": u["version"],
    }


def project_manifest(m):
    rows = lines_of(m["id"])
    received = sum((D(ln["received_quantity_kg"] or 0) for ln in rows), Decimal(0))
    return {
        "id": m["id"],
        "generator_id": m["generator_id"],
        "facility_id": m["facility_id"],
        "manifest_tracking_number": m["manifest_tracking_number"],
        "transporter_epa_id": m["transporter_epa_id"],
        "shipped_on": m["shipped_on"],
        "status": m["status"],
        "arrived_at": iso(m["arrived_at"]),
        "discrepancy_type": m["discrepancy_type"],
        "discrepancy_report_due_at": iso(m["discrepancy_report_due_at"]),
        "discrepancy_report_filed": m["discrepancy_report_filed"],
        "discrepancy_resolved_at": iso(m["discrepancy_resolved_at"]),
        "resolution_type": m["resolution_type"],
        "provisional_charge_cents": m["provisional_charge_cents"],
        "final_charge_cents": m["final_charge_cents"],
        "line_count": len(rows),
        "received_mass_kg": q(qd(received, 3), 3),
        "created_at": iso(m["created_at"]),
        "updated_at": iso(m["updated_at"]),
        "version": m["version"],
    }


def project_line(ln):
    return {
        "id": ln["id"],
        "manifest_id": ln["manifest_id"],
        "waste_profile_id": ln["waste_profile_id"],
        "line_number": ln["line_number"],
        "declared_quantity_kg": q3(ln["declared_quantity_kg"]),
        "declared_container_count": ln["declared_container_count"],
        "is_bulk": ln["is_bulk"],
        "received_quantity_kg": q3(ln["received_quantity_kg"]),
        "received_container_count": ln["received_container_count"],
        "accepted_quantity_kg": q3(ln["accepted_quantity_kg"]),
        "returned_quantity_kg": q3(ln["returned_quantity_kg"]),
        "line_status": ln["line_status"],
        "variance_pct": q4(ln["variance_pct"]),
        "significance": ln["significance"],
        "provisional_line_charge_cents": ln["provisional_line_charge_cents"],
        "final_line_charge_cents": ln["final_line_charge_cents"],
        "allocated_container_mass_kg": q(allocated_container_mass(ln["id"]), 3),
        "created_at": iso(ln["created_at"]),
        "updated_at": iso(ln["updated_at"]),
        "version": ln["version"],
    }


def project_container(c):
    return {
        "id": c["id"],
        "manifest_line_id": c["manifest_line_id"],
        "waste_profile_id": c["waste_profile_id"],
        "storage_unit_id": c["storage_unit_id"],
        "treatment_batch_id": c["treatment_batch_id"],
        "container_type": c["container_type"],
        "capacity_kg": q3(c["capacity_kg"]),
        "net_weight_kg": q3(c["net_weight_kg"]),
        "accumulation_start_date": iso(c["accumulation_start_date"]),
        "label_waste_codes": list(c["label_waste_codes"]),
        "label_hazard_class": c["label_hazard_class"],
        "label_accumulation_start_marked": c["label_accumulation_start_marked"],
        "custody_state": c["custody_state"],
        "compliance_state": c["compliance_state"],
        "last_finding_code": c["last_finding_code"],
        "fill_ratio": q(container_fill_ratio(c), 4),
        "accumulation_days": container_accumulation_days(c),
        "ten_day_overdue": container_ten_day_overdue(c),
        "created_at": iso(c["created_at"]),
        "updated_at": iso(c["updated_at"]),
        "version": c["version"],
    }


def project_batch(b):
    return {
        "id": b["id"],
        "facility_id": b["facility_id"],
        "storage_unit_id": b["storage_unit_id"],
        "treatment_method": b["treatment_method"],
        "container_ids": list(b["container_ids"]),
        "window_start": iso(b["window_start"]),
        "window_end": iso(b["window_end"]),
        "dominant_compatibility_class": b["dominant_compatibility_class"],
        "input_mass_kg": q3(b["input_mass_kg"]),
        "estimated_treatment_liability_cents": b["estimated_treatment_liability_cents"],
        "status": b["status"],
        "residue_constituent_ppm": q1(b["residue_constituent_ppm"]),
        "residue_flash_point_c": q1(b["residue_flash_point_c"]),
        "residue_mass_kg": q3(b["residue_mass_kg"]),
        "verification_sample_ppm": q1(b["verification_sample_ppm"]),
        "ldr_standard_ppm": q1(b["ldr_standard_ppm"]),
        "ldr_result": b["ldr_result"],
        "completed_by_user_id": b["completed_by_user_id"],
        "verified_by_user_id": b["verified_by_user_id"],
        "retreat_count": b["retreat_count"],
        "held_reason_code": b["held_reason_code"],
        "created_at": iso(b["created_at"]),
        "updated_at": iso(b["updated_at"]),
        "version": b["version"],
    }


def project_inspection(e):
    return {
        "id": e["id"],
        "storage_unit_id": e["storage_unit_id"],
        "container_id": e["container_id"],
        "inspection_type": e["inspection_type"],
        "finding_code": e["finding_code"],
        "measured_organic_vapor_ppm": q1(e["measured_organic_vapor_ppm"]),
        "measured_aisle_width_cm": q1(e["measured_aisle_width_cm"]),
        "performed_by_user_id": e["performed_by_user_id"],
        "inspected_at": iso(e["inspected_at"]),
        "leak_detected": e["leak_detected"],
        "aisle_compliant": e["aisle_compliant"],
        "created_at": iso(e["created_at"]),
    }


def project_repair_order(o):
    return {
        "id": o["id"],
        "storage_unit_id": o["storage_unit_id"],
        "container_id": o["container_id"],
        "source_inspection_event_id": o["source_inspection_event_id"],
        "leak_type": o["leak_type"],
        "detected_at": iso(o["detected_at"]),
        "detected_ppm": q1(o["detected_ppm"]),
        "leak_definition_ppm": q1(o["leak_definition_ppm"]),
        "first_attempt_due_at": iso(o["first_attempt_due_at"]),
        "repair_due_at": iso(o["repair_due_at"]),
        "delayed_due_at": iso(o["delayed_due_at"]),
        "justification_code": o["justification_code"],
        "status": o["status"],
        "attempt_count": o["attempt_count"],
        "last_monitored_ppm": q1(o["last_monitored_ppm"]),
        "is_overdue": repair_order_overdue(o),
        "created_at": iso(o["created_at"]),
        "updated_at": iso(o["updated_at"]),
        "version": o["version"],
    }


def project_finding(f):
    return {
        "id": f["id"],
        "facility_id": f["facility_id"],
        "storage_unit_id": f["storage_unit_id"],
        "finding_class": f["finding_class"],
        "citation_code": f["citation_code"],
        "corrective_action_due_at": iso(f["corrective_action_due_at"]),
        "is_prior_release": f["is_prior_release"],
        "status": f["status"],
        "cited_at": iso(f["cited_at"]),
        "response_submitted_at": iso(f["response_submitted_at"]),
        "corrective_action_completed_on": f["corrective_action_completed_on"],
        "reopen_count": f["reopen_count"],
        "is_overdue": finding_overdue(f),
        "created_at": iso(f["created_at"]),
        "updated_at": iso(f["updated_at"]),
        "version": f["version"],
    }


PROJECTORS = {
    "facilities": project_facility,
    "generators": project_generator,
    "instruments": project_instrument,
    "profiles": project_profile,
    "samples": project_sample,
    "units": project_unit,
    "manifests": project_manifest,
    "lines": project_line,
    "containers": project_container,
    "batches": project_batch,
    "inspections": project_inspection,
    "repair_orders": project_repair_order,
    "findings": project_finding,
}
