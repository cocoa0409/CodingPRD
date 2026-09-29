"""Domain services: lookups, lazy refreshes, derived fields, cascades, serializers."""

from datetime import timedelta

import calcs
from calcs import dec, fnum, rhu
from db import clock_iso, clock_now, db, iso_ms, sort_rows, touch
from errors import api_error
from validation import SPECIAL_SERVICES


# ------------------------------------------------------------------ lookups ---
def find_model(model_id):
    row = db.valve_models.get(model_id)
    if row is None:
        raise api_error("ERR_MODEL_NOT_FOUND", "valve model '%s' not found" % model_id)
    return row


def find_foundry(foundry_id):
    row = db.foundries.get(foundry_id)
    if row is None:
        raise api_error("ERR_FOUNDRY_NOT_FOUND", "foundry '%s' not found" % foundry_id)
    return row


def find_qualification(qual_id):
    row = db.qualifications.get(qual_id)
    if row is None:
        raise api_error(
            "ERR_QUALIFICATION_NOT_FOUND", "qualification '%s' not found" % qual_id
        )
    refresh_qualification(row)
    return row


def find_heat_lot(lot_id):
    row = db.heat_lots.get(lot_id)
    if row is None:
        raise api_error("ERR_HEAT_LOT_NOT_FOUND", "heat lot '%s' not found" % lot_id)
    return row


def find_component(component_id):
    row = db.components.get(component_id)
    if row is None:
        raise api_error(
            "ERR_COMPONENT_NOT_FOUND", "component '%s' not found" % component_id
        )
    return row


def find_unit(unit_id):
    row = db.valve_units.get(unit_id)
    if row is None:
        raise api_error("ERR_UNIT_NOT_FOUND", "valve unit '%s' not found" % unit_id)
    refresh_unit(row)
    return row


def find_actuator(actuator_id):
    row = db.actuator_packages.get(actuator_id)
    if row is None:
        raise api_error(
            "ERR_ACTUATOR_NOT_FOUND", "actuator package '%s' not found" % actuator_id
        )
    return row


def find_license(license_id):
    row = db.licenses.get(license_id)
    if row is None:
        raise api_error(
            "ERR_LICENSE_NOT_FOUND", "monogram license '%s' not found" % license_id
        )
    refresh_license(row)
    return row


def find_order(order_id):
    row = db.orders.get(order_id)
    if row is None:
        raise api_error(
            "ERR_ORDER_NOT_FOUND", "engineered order '%s' not found" % order_id
        )
    return row


# ------------------------------------------------------------- collections ---
def units_of_model(model_id):
    return [u for u in db.valve_units.values() if u.get("model_id") == model_id]


def units_of_license(license_id):
    return [u for u in db.valve_units.values() if u.get("monogram_license_id") == license_id]


def units_of_order(order_id):
    return [u for u in db.valve_units.values() if u.get("engineered_order_id") == order_id]


def components_of_lot(lot_id):
    return [c for c in db.components.values() if c.get("heat_lot_id") == lot_id]


def lots_of_foundry(foundry_id):
    return [l for l in db.heat_lots.values() if l.get("foundry_id") == foundry_id]


def qualifications_of_foundry(foundry_id):
    return [q for q in db.qualifications.values() if q.get("foundry_id") == foundry_id]


def records_of_unit(unit_id):
    return sort_rows([r for r in db.test_records.values() if r.get("valve_unit_id") == unit_id])


def packages_of_unit(unit_id):
    return sort_rows(
        [p for p in db.actuator_packages.values() if p.get("valve_unit_id") == unit_id]
    )


# --------------------------------------------------------- foundry derived ---
def foundry_derived(foundry):
    lots = lots_of_foundry(foundry["id"])
    total = len(lots)
    rejected = len([l for l in lots if l.get("status") in ("QUARANTINED", "REJECTED")])
    revoked = len(
        [
            q
            for q in qualifications_of_foundry(foundry["id"])
            if q.get("status") == "REVOKED"
        ]
    )
    index = calcs.foundry_quality_index(total, rejected, revoked)
    return {
        "total_lot_count": total,
        "rejected_lot_count": rejected,
        "revoked_qualification_count": revoked,
        "quality_index": index,
        "status": calcs.foundry_status_band(index),
    }


# --------------------------------------------------- qualification lifecycle ---
def refresh_qualification(qual):
    """Lazy expiry: a QUALIFIED window that the clock has passed reads EXPIRED."""
    if qual.get("status") == "QUALIFIED" and clock_now() > qual["_valid_until_dt"]:
        qual["status"] = "EXPIRED"
    return qual


def qualification_covers(qual, process, material_grade, pressure_class):
    if qual.get("status") != "QUALIFIED":
        return False
    if qual.get("process") != process or qual.get("material_grade") != material_grade:
        return False
    if int(qual.get("max_pressure_class")) < int(pressure_class):
        return False
    now = clock_now()
    return qual["_valid_from_dt"] <= now <= qual["_valid_until_dt"]


# --------------------------------------------------------- heat lot derived ---
def lot_mass_balance(lot):
    components = components_of_lot(lot["id"])
    committed = dec(0)
    scrapped = dec(0)
    for component in components:
        weight = dec(component.get("net_weight_kg"))
        status = component.get("status")
        if status in ("CREATED", "ISSUED_TO_MACHINING", "CONSUMED", "HOLD"):
            committed += weight
        elif status == "SCRAPPED":
            scrapped += weight
    received = dec(lot.get("qty_received_kg"))
    available = received - committed - scrapped
    return (
        float(rhu(committed, 3)),
        float(rhu(scrapped, 3)),
        float(rhu(available, 3)),
    )


# ------------------------------------------------------------- model derived ---
def model_qualified_special_services(model):
    qualified = []
    unit_ids = [u["id"] for u in units_of_model(model["id"])]
    records = [
        r
        for r in db.test_records.values()
        if r.get("valve_unit_id") in unit_ids and r.get("result") == "PASS"
    ]
    today = clock_now().date()
    for service in SPECIAL_SERVICES:
        for record in records:
            if record.get("test_type") != service:
                continue
            ended = record.get("_ended_at_dt")
            if ended is None:
                continue
            if (ended.date() + timedelta(days=calcs.TYPE_TEST_VALIDITY_DAYS)) >= today:
                qualified.append(service)
                break
    return qualified


# ---------------------------------------------------------- license derived ---
def license_counts(lic):
    open_major = (
        lic.get("total_major_raised", 0)
        - lic.get("closed_major_finding_count", 0)
        - lic.get("waived_major_finding_count", 0)
    )
    open_minor = lic.get("total_minor_raised", 0) - lic.get("_closed_minor_count", 0)
    return open_major, open_minor


def license_posture(lic):
    open_major, open_minor = license_counts(lic)
    status = lic.get("license_status")
    if open_major >= calcs.MAJOR_FINDING_FREEZE_THRESHOLD or status in (
        "SUSPENDED",
        "DENIED",
        "REVOKED",
    ):
        return "FROZEN"
    if (
        open_major == 1
        or open_minor >= calcs.MINOR_FINDING_CONDITIONAL_THRESHOLD
        or status == "CONDITIONAL"
    ):
        return "CONDITIONAL"
    return "COMPLIANT"


def refresh_license(lic):
    """Lazy automatic revocation of an expired conditional license (PRD 3.6)."""
    if lic.get("license_status") != "CONDITIONAL":
        return lic
    expires = lic.get("_conditional_expires_dt")
    if expires is None or clock_now() <= expires:
        return lic
    open_major, _ = license_counts(lic)
    if open_major < 1:
        return lic
    lic["license_status"] = "REVOKED"
    touch(lic)
    for unit in sort_rows(units_of_license(lic["id"])):
        if unit.get("cert_status") == "CERTIFIED":
            decertify_unit(unit, "LICENSE_DENIED")
    return lic


# ------------------------------------------------------------- unit derived ---
def required_test_set(unit):
    model = db.valve_models.get(unit.get("model_id"))
    required = ["SHELL", "SEAT"]
    needs_functional = False
    if model is not None and model.get("valve_type") == "CONTROL":
        needs_functional = True
    for package in packages_of_unit(unit["id"]):
        if package.get("sizing_status") == "APPROVED":
            needs_functional = True
    if needs_functional:
        required.append("FUNCTIONAL")
    for service in unit.get("special_services") or []:
        if service not in required:
            required.append(service)
    return required


def deciding_records(unit):
    """The deciding record per test type is the one with the greatest created_at."""
    deciding = {}
    for record in records_of_unit(unit["id"]):
        deciding[record["test_type"]] = record
    return deciding


def refresh_unit(unit):
    """Recompute the certification dimension from the (never cached) coverage rule."""
    status = unit.get("cert_status")
    if status not in ("TESTS_IN_PROGRESS", "TESTS_PASSED", "TESTS_FAILED"):
        return unit
    required = required_test_set(unit)
    deciding = deciding_records(unit)
    failed = False
    covered = True
    for test_type in required:
        record = deciding.get(test_type)
        if record is None:
            covered = False
            continue
        if record.get("result") == "FAIL":
            failed = True
    if failed:
        unit["cert_status"] = "TESTS_FAILED"
    elif covered:
        unit["cert_status"] = "TESTS_PASSED"
    else:
        unit["cert_status"] = "TESTS_IN_PROGRESS"
    return unit


def fugitive_records(unit):
    return [
        r
        for r in records_of_unit(unit["id"])
        if r.get("test_type") == "FUGITIVE_EMISSION"
    ]


def provisional_leak_class(unit):
    return calcs.peak_reading_class(fugitive_records(unit))


def time_weighted_leak_class(unit):
    return calcs.time_weighted_class(fugitive_records(unit))


# ------------------------------------------------------------ order derived ---
def order_certified_unit_count(order):
    count = 0
    for unit in units_of_order(order["id"]):
        refresh_unit(unit)
        if unit.get("cert_status") == "CERTIFIED":
            count += 1
    return count


def order_has_approved_actuator(order):
    for unit in units_of_order(order["id"]):
        for package in packages_of_unit(unit["id"]):
            if package.get("sizing_status") == "APPROVED":
                return True
    return False


def order_documentation_completeness(order):
    return calcs.documentation_completeness(
        order.get("documents") or [],
        order.get("ordered_qty") or 0,
        order_has_approved_actuator(order),
    )


def order_spec_stale(order):
    pinned_id = order.get("pinned_model_id")
    pinned_revision = order.get("pinned_model_spec_revision")
    if pinned_id is None or pinned_revision is None:
        return False
    model = db.valve_models.get(pinned_id)
    if model is None:
        return True
    if model.get("spec_revision") != pinned_revision:
        return True
    return model.get("status") in ("SUPERSEDED", "WITHDRAWN")


# ---------------------------------------------------------------- cascades ---
def decertify_unit(unit, reason):
    """The full decertification tail (PRD 3.7)."""
    unit["cert_status"] = "DECERTIFIED"
    unit["certified_by_user_id"] = None
    unit["certified_at"] = None
    unit["decertification_reason"] = reason
    if unit.get("build_status") in ("ASSEMBLED", "PACKAGED"):
        unit["build_status"] = "REWORK"
    touch(unit)

    order_id = unit.get("engineered_order_id")
    if not order_id:
        return
    order = db.orders.get(order_id)
    if order is None:
        return
    if order.get("doc_package_status") == "ISSUED":
        order["doc_package_status"] = "VOIDED"
        order["held_reason"] = "DOC_PACKAGE_VOIDED"
    if order.get("status") == "IN_PRODUCTION":
        order["status"] = "HELD"
        order["held_reason"] = "UNIT_DECERTIFIED"
    elif order.get("status") == "CLOSED":
        order["status"] = "IN_PRODUCTION"
        order["held_reason"] = "UNIT_DECERTIFIED"
    touch(order)


def decertify_units_of_license(lic, reason):
    for unit in sort_rows(units_of_license(lic["id"])):
        refresh_unit(unit)
        if unit.get("cert_status") == "CERTIFIED":
            decertify_unit(unit, reason)


def mark_pinned_orders_stale(model_id):
    """Orders pinned to a model recompute spec_stale; the recompute is a mutation."""
    for order in sort_rows(list(db.orders.values())):
        if order.get("pinned_model_id") == model_id:
            touch(order)


# -------------------------------------------------------------- serializers ---
def serialize_model(model):
    return {
        "id": model["id"],
        "model_code": model["model_code"],
        "valve_type": model["valve_type"],
        "pressure_class": model["pressure_class"],
        "body_material_grade": model["body_material_grade"],
        "bore_size_mm": model["bore_size_mm"],
        "seat_type": model["seat_type"],
        "base_break_torque_nm": model["base_break_torque_nm"],
        "required_special_services": list(model.get("required_special_services") or []),
        "repair_kit_stock_qty": model["repair_kit_stock_qty"],
        "supersedes_model_id": model.get("supersedes_model_id"),
        "spec_revision": model["spec_revision"],
        "qualified_special_services": model_qualified_special_services(model),
        "status": model["status"],
        "authored_by_user_id": model.get("authored_by_user_id"),
        "released_at": model.get("released_at"),
        "created_at": model["created_at"],
        "updated_at": model["updated_at"],
        "version": model["version"],
    }


def serialize_foundry(foundry):
    derived = foundry_derived(foundry)
    return {
        "id": foundry["id"],
        "foundry_code": foundry["foundry_code"],
        "name": foundry["name"],
        "country_code": foundry["country_code"],
        "total_lot_count": derived["total_lot_count"],
        "rejected_lot_count": derived["rejected_lot_count"],
        "revoked_qualification_count": derived["revoked_qualification_count"],
        "quality_index": derived["quality_index"],
        "status": derived["status"],
        "created_at": foundry["created_at"],
        "updated_at": foundry["updated_at"],
        "version": foundry["version"],
    }


def serialize_qualification(qual):
    refresh_qualification(qual)
    return {
        "id": qual["id"],
        "foundry_id": qual["foundry_id"],
        "process": qual["process"],
        "material_grade": qual["material_grade"],
        "max_pressure_class": qual["max_pressure_class"],
        "valid_from": qual["valid_from"],
        "valid_until": qual["valid_until"],
        "status": qual["status"],
        "qualified_by_user_id": qual.get("qualified_by_user_id"),
        "requalification_count": qual.get("requalification_count", 0),
        "created_at": qual["created_at"],
        "updated_at": qual["updated_at"],
        "version": qual["version"],
    }


def serialize_heat_lot(lot):
    committed, scrapped, available = lot_mass_balance(lot)
    return {
        "id": lot["id"],
        "foundry_id": lot["foundry_id"],
        "heat_number": lot["heat_number"],
        "material_grade": lot["material_grade"],
        "process": lot["process"],
        "qty_received_kg": fnum(lot["qty_received_kg"], 3),
        "mtr_document_ref": lot["mtr_document_ref"],
        "carbon_equivalent_pct": fnum(lot["carbon_equivalent_pct"], 3),
        "impact_energy_j": fnum(lot["impact_energy_j"], 1),
        "qty_committed_kg": committed,
        "qty_scrapped_kg": scrapped,
        "qty_available_kg": available,
        "status": lot["status"],
        "verified_by_user_id": lot.get("verified_by_user_id"),
        "quarantine_reason": lot.get("quarantine_reason"),
        "created_at": lot["created_at"],
        "updated_at": lot["updated_at"],
        "version": lot["version"],
    }


def serialize_component(component):
    return {
        "id": component["id"],
        "heat_lot_id": component["heat_lot_id"],
        "target_model_id": component["target_model_id"],
        "component_type": component["component_type"],
        "net_weight_kg": fnum(component["net_weight_kg"], 3),
        "status": component["status"],
        "pre_hold_status": component.get("pre_hold_status"),
        "created_at": component["created_at"],
        "updated_at": component["updated_at"],
        "version": component["version"],
    }


def serialize_unit(unit):
    refresh_unit(unit)
    return {
        "id": unit["id"],
        "model_id": unit["model_id"],
        "body_component_id": unit["body_component_id"],
        "monogram_license_id": unit["monogram_license_id"],
        "engineered_order_id": unit.get("engineered_order_id"),
        "serial_number": unit["serial_number"],
        "special_services": list(unit.get("special_services") or []),
        "build_status": unit["build_status"],
        "cert_status": unit["cert_status"],
        "service_status": unit["service_status"],
        "reserved_kit_qty": unit.get("reserved_kit_qty", 0),
        "service_engineer_user_id": unit.get("service_engineer_user_id"),
        "provisional_emission_leak_class": provisional_leak_class(unit),
        "final_emission_leak_class": unit.get("final_emission_leak_class"),
        "certified_by_user_id": unit.get("certified_by_user_id"),
        "certified_at": unit.get("certified_at"),
        "decertification_reason": unit.get("decertification_reason"),
        "created_at": unit["created_at"],
        "updated_at": unit["updated_at"],
        "version": unit["version"],
    }


def serialize_test_record(record):
    return {
        "id": record["id"],
        "valve_unit_id": record["valve_unit_id"],
        "test_type": record["test_type"],
        "test_bench_code": record["test_bench_code"],
        "started_at": record["started_at"],
        "ended_at": record["ended_at"],
        "test_pressure_bar": fnum(record["test_pressure_bar"], 1),
        "hold_seconds": record["hold_seconds"],
        "leak_rate_ppm": record.get("leak_rate_ppm"),
        "leak_drops": record.get("leak_drops"),
        "result": record["result"],
        "standard_ref": record["standard_ref"],
        "performed_by_user_id": record["performed_by_user_id"],
        "required_pressure_bar": record["required_pressure_bar"],
        "required_hold_seconds": record["required_hold_seconds"],
        "created_at": record["created_at"],
    }


def serialize_actuator(package):
    return {
        "id": package["id"],
        "valve_unit_id": package["valve_unit_id"],
        "actuator_type": package["actuator_type"],
        "supply_pressure_bar": fnum(package["supply_pressure_bar"], 1),
        "output_torque_nm": fnum(package["output_torque_nm"], 1),
        "sizing_basis": package["sizing_basis"],
        "required_torque_nm": package["required_torque_nm"],
        "safety_margin_pct": package["safety_margin_pct"],
        "sized_torque_nm": package["sized_torque_nm"],
        "sizing_status": package["sizing_status"],
        "approved_by_user_id": package.get("approved_by_user_id"),
        "created_at": package["created_at"],
        "updated_at": package["updated_at"],
        "version": package["version"],
    }


def serialize_license(lic):
    refresh_license(lic)
    open_major, open_minor = license_counts(lic)
    return {
        "id": lic["id"],
        "license_code": lic["license_code"],
        "facility_code": lic["facility_code"],
        "scope_valve_types": list(lic.get("scope_valve_types") or []),
        "lead_auditor_user_id": lic["lead_auditor_user_id"],
        "audit_window_start": lic["audit_window_start"],
        "audit_window_end": lic["audit_window_end"],
        "license_status": lic["license_status"],
        "audit_state": lic["audit_state"],
        "compliance_posture": license_posture(lic),
        "total_major_raised": lic.get("total_major_raised", 0),
        "total_minor_raised": lic.get("total_minor_raised", 0),
        "open_major_finding_count": open_major,
        "open_minor_finding_count": open_minor,
        "closed_major_finding_count": lic.get("closed_major_finding_count", 0),
        "waived_major_finding_count": lic.get("waived_major_finding_count", 0),
        "last_audit_closed_at": lic.get("last_audit_closed_at"),
        "granted_at": lic.get("granted_at"),
        "conditional_expires_at": lic.get("conditional_expires_at"),
        "created_at": lic["created_at"],
        "updated_at": lic["updated_at"],
        "version": lic["version"],
    }


def serialize_order(order):
    return {
        "id": order["id"],
        "order_code": order["order_code"],
        "model_id": order["model_id"],
        "ordered_qty": order["ordered_qty"],
        "unit_price_cents": order["unit_price_cents"],
        "requested_special_services": list(order.get("requested_special_services") or []),
        "expedite_requested": order.get("expedite_requested", False),
        "customer_credit_limit_cents": order["customer_credit_limit_cents"],
        "datasheet_break_torque_nm": order.get("datasheet_break_torque_nm"),
        "datasheet_torque_source": order.get("datasheet_torque_source"),
        "datasheet_revision_no": order.get("datasheet_revision_no", 1),
        "clarification_round_count": order.get("clarification_round_count", 0),
        "status": order["status"],
        "pinned_model_id": order.get("pinned_model_id"),
        "pinned_model_spec_revision": order.get("pinned_model_spec_revision"),
        "spec_stale": order_spec_stale(order),
        "gross_quoted_cents": order.get("gross_quoted_cents"),
        "net_billable_cents": order.get("net_billable_cents"),
        "credit_issued_cents": order.get("credit_issued_cents", 0),
        "documents": [dict(d) for d in (order.get("documents") or [])],
        "doc_package_status": order["doc_package_status"],
        "documentation_completeness_pct": order_documentation_completeness(order),
        "certified_unit_count": order_certified_unit_count(order),
        "held_reason": order.get("held_reason"),
        "created_at": order["created_at"],
        "updated_at": order["updated_at"],
        "version": order["version"],
    }
