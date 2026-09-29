"""
Composite state builders for the Valve Manufacturing & Product Certification API.

The harness starts every test against an empty database, so every precondition has
to be built through declared endpoints. The builders here climb the traceability
chain the PRD describes — foundry, qualification, heat lot, component, design,
monogram license, serialised unit, test programme, certification, engineered order —
and each one returns the resource payload the API reported, so callers can thread
identifiers and observed ``version`` values onward.

All setup calls go through the lenient ``get_success_data`` validator: a setup step
that fails should read as a setup failure, not as the assertion under test.
"""

from typing import Any, Dict, Iterable, List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import ApiClient
from .constants import FRESH_CLOCK_UTC
from .test_users import (
    make_field_service_coordinator_headers,
    make_monogram_auditor_headers,
    make_procurement_specialist_headers,
    make_product_engineer_headers,
    make_quality_manager_headers,
    make_test_technician_headers,
)
from .types import Headers, Payload

Entity = Dict[str, Any]


# ─── Tier 1: the logical works clock ──────────────────


def set_logical_clock(api: ApiClient, instant: str, headers: Optional[Headers] = None) -> Entity:
    """Move the logical clock every date-dependent rule reads."""
    return get_success_data(api.set_clock(instant, headers or make_quality_manager_headers()))


# ─── Tier 2: foundries, qualifications, material ──────


def create_foundry(
    api: ApiClient,
    foundry_code: str = "FDY-01",
    name: str = "Alpha Castings",
    country_code: str = "IN",
    headers: Optional[Headers] = None,
) -> Entity:
    return get_success_data(
        api.create_foundry(
            f.foundry_payload(foundry_code, name, country_code),
            headers or make_procurement_specialist_headers(),
        )
    )


def create_qualification(
    api: ApiClient,
    foundry_id: str,
    process: str = "CASTING",
    material_grade: str = "CF8M",
    max_pressure_class: int = 600,
    valid_from: str = "2026-01-01T00:00:00Z",
    valid_until: str = "2026-12-31T00:00:00Z",
    headers: Optional[Headers] = None,
) -> Entity:
    """Open a scoped process/material qualification; the row opens at PENDING."""
    return get_success_data(
        api.create_foundry_qualification(
            f.foundry_qualification_payload(
                foundry_id, process, material_grade, max_pressure_class, valid_from, valid_until
            ),
            headers or make_procurement_specialist_headers(),
        )
    )


def qualify(
    api: ApiClient, qualification_id: str, headers: Optional[Headers] = None
) -> Entity:
    """Move PENDING to QUALIFIED — reserved to a QualityManager."""
    return get_success_data(
        api.foundry_qualification_action(
            qualification_id,
            f.qualification_action_payload("QUALIFY"),
            headers or make_quality_manager_headers(),
        )
    )


def create_qualified_foundry(
    api: ApiClient,
    foundry_code: str = "FDY-01",
    name: str = "Alpha Castings",
    country_code: str = "IN",
    process: str = "CASTING",
    material_grade: str = "CF8M",
    max_pressure_class: int = 600,
    valid_from: str = "2026-01-01T00:00:00Z",
    valid_until: str = "2026-12-31T00:00:00Z",
) -> Dict[str, Entity]:
    """A registered foundry carrying one QUALIFIED process/material qualification."""
    foundry = create_foundry(api, foundry_code, name, country_code)
    qualification = create_qualification(
        api,
        foundry["id"],
        process=process,
        material_grade=material_grade,
        max_pressure_class=max_pressure_class,
        valid_from=valid_from,
        valid_until=valid_until,
    )
    qualification = qualify(api, qualification["id"])
    return {"foundry": foundry, "qualification": qualification}


def create_heat_lot(
    api: ApiClient,
    foundry_id: str,
    heat_number: str = "H-1001",
    material_grade: str = "CF8M",
    process: str = "CASTING",
    qty_received_kg: float = 500.000,
    mtr_document_ref: str = "MTR-1001",
    carbon_equivalent_pct: float = 0.35,
    impact_energy_j: float = 40,
    headers: Optional[Headers] = None,
) -> Entity:
    """Declare a received lot; it opens at RECEIVED with its full mass available."""
    return get_success_data(
        api.create_heat_lot(
            f.heat_lot_payload(
                foundry_id,
                heat_number,
                material_grade,
                process,
                qty_received_kg,
                mtr_document_ref,
                carbon_equivalent_pct,
                impact_energy_j,
            ),
            headers or make_procurement_specialist_headers(),
        )
    )


def dispose_lot(
    api: ApiClient,
    lot_id: str,
    action: str,
    quarantine_reason: Optional[str] = None,
    headers: Optional[Headers] = None,
) -> Entity:
    return get_success_data(
        api.heat_lot_disposition(
            lot_id,
            f.lot_disposition_payload(action, quarantine_reason),
            headers or make_quality_manager_headers(),
        )
    )


def create_released_lot(api: ApiClient, foundry_id: str, **kwargs) -> Entity:
    """RECEIVED to VERIFIED to RELEASED — the only status in which a lot may serve
    as a component's traceability parent."""
    lot = create_heat_lot(api, foundry_id, **kwargs)
    dispose_lot(api, lot["id"], "VERIFY")
    return dispose_lot(api, lot["id"], "RELEASE")


def draw_component(
    api: ApiClient,
    heat_lot_id: str,
    target_model_id: str,
    component_type: str = "BODY",
    net_weight_kg: float = 120.500,
    headers: Optional[Headers] = None,
) -> Entity:
    return get_success_data(
        api.create_component(
            f.component_payload(heat_lot_id, target_model_id, component_type, net_weight_kg),
            headers or make_procurement_specialist_headers(),
        )
    )


def dispose_component(
    api: ApiClient, component_id: str, action: str, headers: Optional[Headers] = None
) -> Entity:
    return get_success_data(
        api.component_disposition(
            component_id,
            f.component_disposition_payload(action),
            headers or make_procurement_specialist_headers(),
        )
    )


# ─── Tier 2: product-line designs ─────────────────────


def create_model(
    api: ApiClient,
    model_code: str = "BV-300-CF8M",
    valve_type: str = "BALL",
    pressure_class: int = 300,
    body_material_grade: str = "CF8M",
    bore_size_mm: float = 100,
    seat_type: str = "METAL",
    base_break_torque_nm: float = 420.0,
    required_special_services: Optional[List[str]] = None,
    repair_kit_stock_qty: Optional[int] = None,
    supersedes_model_id: Optional[str] = None,
    headers: Optional[Headers] = None,
) -> Entity:
    """Open a product-line design; it opens at DRAFT with spec_revision 1."""
    return get_success_data(
        api.create_valve_model(
            f.valve_model_payload(
                model_code,
                valve_type,
                pressure_class,
                body_material_grade,
                bore_size_mm,
                seat_type,
                base_break_torque_nm,
                required_special_services=required_special_services,
                repair_kit_stock_qty=repair_kit_stock_qty,
                supersedes_model_id=supersedes_model_id,
            ),
            headers or make_product_engineer_headers(),
        )
    )


def model_action(
    api: ApiClient, model_id: str, action: str, headers: Optional[Headers] = None
) -> Entity:
    default = (
        make_product_engineer_headers()
        if action in ("SUBMIT_REVIEW",)
        else make_quality_manager_headers()
    )
    return get_success_data(
        api.valve_model_action(model_id, f.model_action_payload(action), headers or default)
    )


def submit_model_for_review(api: ApiClient, model_id: str) -> Entity:
    return model_action(api, model_id, "SUBMIT_REVIEW")


def release_model(api: ApiClient, model_id: str) -> Entity:
    """DRAFT to IN_REVIEW to RELEASED."""
    submit_model_for_review(api, model_id)
    return model_action(api, model_id, "RELEASE")


def create_released_model(api: ApiClient, **kwargs) -> Entity:
    model = create_model(api, **kwargs)
    return release_model(api, model["id"])


# ─── Tier 2: monogram licenses ────────────────────────


def apply_for_license(
    api: ApiClient,
    license_code: str = "MON-01",
    facility_code: str = "FAC-1",
    scope_valve_types: Optional[List[str]] = None,
    lead_auditor_user_id: str = "aud-1",
    audit_window_start: str = "2026-07-01T00:00:00Z",
    audit_window_end: str = "2026-07-31T00:00:00Z",
    headers: Optional[Headers] = None,
) -> Entity:
    """Apply for a monogram license; the application opens at APPLIED / SCHEDULED / COMPLIANT."""
    return get_success_data(
        api.create_monogram_license(
            f.monogram_license_payload(
                license_code,
                facility_code,
                scope_valve_types if scope_valve_types is not None else ["BALL"],
                lead_auditor_user_id,
                audit_window_start,
                audit_window_end,
            ),
            headers or make_quality_manager_headers(),
        )
    )


def license_action(
    api: ApiClient,
    license_id: str,
    action: str,
    auditor_user_id: str = "aud-1",
    audit_window_start: Optional[str] = None,
    audit_window_end: Optional[str] = None,
) -> Entity:
    return get_success_data(
        api.monogram_license_action(
            license_id,
            f.license_action_payload(action, audit_window_start, audit_window_end),
            make_monogram_auditor_headers(auditor_user_id),
        )
    )


def raise_findings(
    api: ApiClient,
    license_id: str,
    severity: str,
    count: int,
    auditor_user_id: str = "aud-1",
) -> Entity:
    """Raise ``count`` findings of one severity, each incrementing the lifetime counter."""
    last: Entity = {}
    for _ in range(count):
        last = get_success_data(
            api.create_finding_entry(
                license_id,
                f.finding_entry_payload("RAISE", severity),
                make_monogram_auditor_headers(auditor_user_id),
            )
        )
    return last


def create_granted_license(
    api: ApiClient,
    license_code: str = "MON-01",
    facility_code: str = "FAC-1",
    scope_valve_types: Optional[List[str]] = None,
    lead_auditor_user_id: str = "aud-1",
    audit_window_start: str = "2026-07-01T00:00:00Z",
    audit_window_end: str = "2026-07-31T00:00:00Z",
) -> Entity:
    """Apply, run the audit to CLOSED, and grant — a COMPLIANT license under which
    a nameplate may be struck."""
    lic = apply_for_license(
        api,
        license_code=license_code,
        facility_code=facility_code,
        scope_valve_types=scope_valve_types,
        lead_auditor_user_id=lead_auditor_user_id,
        audit_window_start=audit_window_start,
        audit_window_end=audit_window_end,
    )
    license_action(api, lic["id"], "START_AUDIT", lead_auditor_user_id)
    license_action(api, lic["id"], "CLOSE_AUDIT", lead_auditor_user_id)
    return license_action(api, lic["id"], "GRANT", lead_auditor_user_id)


# ─── Tier 3: the traceable production line ────────────


def build_traceable_line(
    api: ApiClient,
    *,
    foundry_code: str = "FDY-01",
    foundry_name: str = "Alpha Castings",
    country_code: str = "IN",
    process: str = "CASTING",
    material_grade: str = "CF8M",
    max_pressure_class: int = 600,
    valid_from: str = "2026-01-01T00:00:00Z",
    valid_until: str = "2026-12-31T00:00:00Z",
    heat_number: str = "H-1001",
    mtr_document_ref: str = "MTR-1001",
    qty_received_kg: float = 500.000,
    carbon_equivalent_pct: float = 0.35,
    impact_energy_j: float = 40,
    model_code: str = "BV-300-CF8M",
    valve_type: str = "BALL",
    pressure_class: int = 300,
    bore_size_mm: float = 100,
    seat_type: str = "METAL",
    base_break_torque_nm: float = 420.0,
    required_special_services: Optional[List[str]] = None,
    repair_kit_stock_qty: Optional[int] = None,
    release_design: bool = True,
    component_type: str = "BODY",
    net_weight_kg: float = 120.500,
    license_code: str = "MON-01",
    facility_code: str = "FAC-1",
    scope_valve_types: Optional[List[str]] = None,
    lead_auditor_user_id: str = "aud-1",
    audit_window_start: str = "2026-07-01T00:00:00Z",
    audit_window_end: str = "2026-07-31T00:00:00Z",
    grant_license: bool = True,
) -> Dict[str, Entity]:
    """A qualified foundry, a released heat lot, a body component drawn from it, a
    product-line design, and a monogram license — everything a serialised unit needs.
    """
    qualified = create_qualified_foundry(
        api,
        foundry_code=foundry_code,
        name=foundry_name,
        country_code=country_code,
        process=process,
        material_grade=material_grade,
        max_pressure_class=max_pressure_class,
        valid_from=valid_from,
        valid_until=valid_until,
    )
    model = create_model(
        api,
        model_code=model_code,
        valve_type=valve_type,
        pressure_class=pressure_class,
        body_material_grade=material_grade,
        bore_size_mm=bore_size_mm,
        seat_type=seat_type,
        base_break_torque_nm=base_break_torque_nm,
        required_special_services=required_special_services,
        repair_kit_stock_qty=repair_kit_stock_qty,
    )
    if release_design:
        model = release_model(api, model["id"])
    lot = create_released_lot(
        api,
        qualified["foundry"]["id"],
        heat_number=heat_number,
        material_grade=material_grade,
        process=process,
        qty_received_kg=qty_received_kg,
        mtr_document_ref=mtr_document_ref,
        carbon_equivalent_pct=carbon_equivalent_pct,
        impact_energy_j=impact_energy_j,
    )
    component = draw_component(
        api, lot["id"], model["id"], component_type=component_type, net_weight_kg=net_weight_kg
    )
    if grant_license:
        lic = create_granted_license(
            api,
            license_code=license_code,
            facility_code=facility_code,
            scope_valve_types=scope_valve_types
            if scope_valve_types is not None
            else [valve_type],
            lead_auditor_user_id=lead_auditor_user_id,
            audit_window_start=audit_window_start,
            audit_window_end=audit_window_end,
        )
    else:
        lic = apply_for_license(
            api,
            license_code=license_code,
            facility_code=facility_code,
            scope_valve_types=scope_valve_types
            if scope_valve_types is not None
            else [valve_type],
            lead_auditor_user_id=lead_auditor_user_id,
            audit_window_start=audit_window_start,
            audit_window_end=audit_window_end,
        )
    return {
        "foundry": qualified["foundry"],
        "qualification": qualified["qualification"],
        "model": model,
        "lot": lot,
        "component": component,
        "license": lic,
    }


# ─── Tier 3: serialised units and the build dimension ──


def open_unit(
    api: ApiClient,
    model_id: str,
    body_component_id: str,
    monogram_license_id: str,
    serial_number: str = "SN-0001",
    special_services: Optional[List[str]] = None,
    engineered_order_id: Optional[str] = None,
    headers: Optional[Headers] = None,
) -> Entity:
    """Open a serialised unit; it opens BLANK / UNCERTIFIED / NONE."""
    return get_success_data(
        api.create_valve_unit(
            f.valve_unit_payload(
                model_id,
                body_component_id,
                monogram_license_id,
                serial_number,
                special_services=special_services,
                engineered_order_id=engineered_order_id,
            ),
            headers or make_product_engineer_headers(),
        )
    )


def advance_build(
    api: ApiClient, unit_id: str, to_build_status: str, technician_user_id: str = "tech-1"
) -> Entity:
    return get_success_data(
        api.valve_unit_build_action(
            unit_id,
            f.advance_build_payload(to_build_status),
            make_test_technician_headers(technician_user_id),
        )
    )


def advance_to_assembled(
    api: ApiClient, unit_id: str, technician_user_id: str = "tech-1"
) -> Entity:
    """BLANK to MACHINED to ASSEMBLED, one adjacent forward step at a time."""
    advance_build(api, unit_id, "MACHINED", technician_user_id)
    return advance_build(api, unit_id, "ASSEMBLED", technician_user_id)


def record_test(
    api: ApiClient,
    unit_id: str,
    test_type: str,
    test_bench_code: str = "BENCH-1",
    started_at: str = "2026-08-01T08:00:00Z",
    ended_at: str = "2026-08-01T09:00:00Z",
    test_pressure_bar: float = 700.0,
    hold_seconds: int = 300,
    result: str = "PASS",
    leak_rate_ppm: Optional[float] = None,
    leak_drops: Optional[int] = None,
    standard_ref: Optional[str] = None,
    technician_user_id: str = "tech-1",
) -> Entity:
    return get_success_data(
        api.create_test_record(
            unit_id,
            f.test_record_payload(
                test_type,
                test_bench_code,
                started_at,
                ended_at,
                test_pressure_bar,
                hold_seconds,
                result,
                leak_rate_ppm=leak_rate_ppm,
                leak_drops=leak_drops,
                standard_ref=standard_ref,
            ),
            make_test_technician_headers(technician_user_id),
        )
    )


_BENCH_SLOTS = [
    ("2026-08-01T08:00:00Z", "2026-08-01T09:00:00Z"),
    ("2026-08-01T09:00:00Z", "2026-08-01T10:00:00Z"),
    ("2026-08-01T10:00:00Z", "2026-08-01T11:00:00Z"),
    ("2026-08-01T11:00:00Z", "2026-08-01T12:00:00Z"),
    ("2026-08-01T12:00:00Z", "2026-08-01T13:00:00Z"),
    ("2026-08-01T13:00:00Z", "2026-08-01T14:00:00Z"),
]


def record_pass_run(
    api: ApiClient,
    unit_id: str,
    test_types: Iterable[str] = ("SHELL", "SEAT"),
    test_bench_code: str = "BENCH-1",
    test_pressure_bar: float = 700.0,
    hold_seconds: int = 300,
    technician_user_id: str = "tech-1",
    leak_rate_ppm: Optional[float] = None,
) -> List[Entity]:
    """Write one passing record per required test type on consecutive bench slots.

    Bench occupancy is a half-open interval, so consecutive slots that merely touch
    are accepted on the same bench.
    """
    records: List[Entity] = []
    for index, test_type in enumerate(test_types):
        started_at, ended_at = _BENCH_SLOTS[index]
        records.append(
            record_test(
                api,
                unit_id,
                test_type,
                test_bench_code=test_bench_code,
                started_at=started_at,
                ended_at=ended_at,
                test_pressure_bar=test_pressure_bar,
                hold_seconds=hold_seconds,
                result="PASS",
                leak_rate_ppm=leak_rate_ppm,
                technician_user_id=technician_user_id,
            )
        )
    return records


def certify_unit(
    api: ApiClient, unit_id: str, quality_manager_user_id: str = "qm-1"
) -> Entity:
    """TESTS_PASSED to CERTIFIED, by a QualityManager who witnessed no test on the unit."""
    return get_success_data(
        api.valve_unit_cert_action(
            unit_id,
            f.cert_action_payload("CERTIFY"),
            make_quality_manager_headers(quality_manager_user_id),
        )
    )


def service_action(
    api: ApiClient,
    unit_id: str,
    action: str,
    engineer_user_id: Optional[str] = None,
    kit_qty: Optional[int] = None,
    coordinator_user_id: str = "fsc-1",
) -> Entity:
    return get_success_data(
        api.valve_unit_service_action(
            unit_id,
            f.service_action_payload(action, engineer_user_id, kit_qty),
            make_field_service_coordinator_headers(coordinator_user_id),
        )
    )


# ─── Tier 4: a certified unit ready to package ────────


def build_certified_unit(
    api: ApiClient,
    *,
    serial_number: str = "SN-0001",
    special_services: Optional[List[str]] = None,
    engineered_order_id: Optional[str] = None,
    test_types: Iterable[str] = ("SHELL", "SEAT"),
    test_bench_code: str = "BENCH-1",
    technician_user_id: str = "tech-1",
    quality_manager_user_id: str = "qm-1",
    leak_rate_ppm: Optional[float] = None,
    line: Optional[Dict[str, Entity]] = None,
    **line_kwargs,
) -> Dict[str, Entity]:
    """A traceable line plus a serialised unit taken all the way to CERTIFIED.

    Returns the line entities alongside the certified ``unit`` payload.
    """
    scenario = line if line is not None else build_traceable_line(api, **line_kwargs)
    unit = open_unit(
        api,
        scenario["model"]["id"],
        scenario["component"]["id"],
        scenario["license"]["id"],
        serial_number=serial_number,
        special_services=special_services,
        engineered_order_id=engineered_order_id,
    )
    advance_to_assembled(api, unit["id"], technician_user_id)
    record_pass_run(
        api,
        unit["id"],
        test_types=test_types,
        test_bench_code=test_bench_code,
        technician_user_id=technician_user_id,
        leak_rate_ppm=leak_rate_ppm,
    )
    unit = certify_unit(api, unit["id"], quality_manager_user_id)
    result = dict(scenario)
    result["unit"] = unit
    return result


# ─── Tier 4/5: engineered orders ──────────────────────


def create_order(
    api: ApiClient,
    model_id: str,
    order_code: str = "ETO-01",
    ordered_qty: int = 1,
    unit_price_cents: int = 1_000_000,
    customer_credit_limit_cents: int = 5_000_000,
    datasheet_break_torque_nm: float = 420.0,
    datasheet_torque_source: str = "VENDOR_MEASURED",
    requested_special_services: Optional[List[str]] = None,
    expedite_requested: Optional[bool] = None,
    headers: Optional[Headers] = None,
) -> Entity:
    """Open an engineered order; it opens at DRAFT with doc_package_status ASSEMBLING."""
    return get_success_data(
        api.create_engineered_order(
            f.engineered_order_payload(
                order_code,
                model_id,
                ordered_qty,
                unit_price_cents,
                customer_credit_limit_cents,
                datasheet_break_torque_nm,
                datasheet_torque_source,
                requested_special_services=requested_special_services,
                expedite_requested=expedite_requested,
            ),
            headers or make_product_engineer_headers(),
        )
    )


def review_action(
    api: ApiClient, order_id: str, action: str, headers: Optional[Headers] = None
) -> Entity:
    default = (
        make_product_engineer_headers()
        if action == "SUBMIT_REVIEW"
        else make_quality_manager_headers()
    )
    return get_success_data(
        api.engineered_order_review_action(
            order_id, f.review_action_payload(action), headers or default
        )
    )


def lifecycle_action(
    api: ApiClient, order_id: str, action: str, headers: Optional[Headers] = None
) -> Entity:
    default = (
        make_quality_manager_headers()
        if action in ("CLOSE", "ISSUE_DOC_PACKAGE", "VOID_DOC_PACKAGE")
        else make_product_engineer_headers()
    )
    return get_success_data(
        api.engineered_order_lifecycle_action(
            order_id, f.lifecycle_action_payload(action), headers or default
        )
    )


def approve_order(api: ApiClient, order_id: str) -> Entity:
    """DRAFT to UNDER_REVIEW to APPROVED — approval pins the specification and
    freezes the quote."""
    review_action(api, order_id, "SUBMIT_REVIEW")
    return review_action(api, order_id, "APPROVE")


def release_order_to_production(api: ApiClient, order_id: str) -> Entity:
    return lifecycle_action(api, order_id, "RELEASE_TO_PRODUCTION")


def build_order_in_production(api: ApiClient, model_id: str, **kwargs) -> Entity:
    order = create_order(api, model_id, **kwargs)
    approve_order(api, order["id"])
    return release_order_to_production(api, order["id"])


def append_document(
    api: ApiClient,
    order_id: str,
    doc_type: str,
    doc_ref: Optional[str] = None,
    headers: Optional[Headers] = None,
) -> Entity:
    return get_success_data(
        api.append_order_document(
            order_id,
            f.order_document_payload(doc_type, doc_ref or f"DOC-{doc_type}"),
            headers or make_quality_manager_headers(),
        )
    )


def append_documents(api: ApiClient, order_id: str, doc_types: Iterable[str]) -> Entity:
    last: Entity = {}
    for doc_type in doc_types:
        last = append_document(api, order_id, doc_type)
    return last


def append_datasheet_revision(
    api: ApiClient,
    order_id: str,
    datasheet_break_torque_nm: float,
    datasheet_torque_source: str,
    expected_engineered_order_version: int,
    headers: Optional[Headers] = None,
) -> Entity:
    return get_success_data(
        api.create_datasheet_revision(
            order_id,
            f.datasheet_revision_payload(
                datasheet_break_torque_nm,
                datasheet_torque_source,
                expected_engineered_order_version,
            ),
            headers or make_product_engineer_headers(),
        )
    )


def propose_actuator_package(
    api: ApiClient,
    valve_unit_id: str,
    expected_valve_unit_version: int,
    actuator_type: str = "PNEUMATIC",
    output_torque_nm: float = 1000.0,
    sizing_basis: str = "CATALOG",
    supply_pressure_bar: Optional[float] = 6.0,
    headers: Optional[Headers] = None,
) -> Entity:
    return get_success_data(
        api.create_actuator_package(
            f.actuator_package_payload(
                valve_unit_id,
                actuator_type,
                output_torque_nm,
                sizing_basis,
                expected_valve_unit_version,
                supply_pressure_bar=supply_pressure_bar,
            ),
            headers or make_product_engineer_headers(),
        )
    )


# ─── Read-through helpers ─────────────────────────────


def read_model(api: ApiClient, model_id: str, headers: Optional[Headers] = None) -> Entity:
    return get_success_data(api.get_valve_model(model_id, headers or make_quality_manager_headers()))


def read_foundry(api: ApiClient, foundry_id: str, headers: Optional[Headers] = None) -> Entity:
    return get_success_data(api.get_foundry(foundry_id, headers or make_quality_manager_headers()))


def read_qualification(
    api: ApiClient, qualification_id: str, headers: Optional[Headers] = None
) -> Entity:
    return get_success_data(
        api.get_foundry_qualification(qualification_id, headers or make_quality_manager_headers())
    )


def read_lot(api: ApiClient, lot_id: str, headers: Optional[Headers] = None) -> Entity:
    return get_success_data(api.get_heat_lot(lot_id, headers or make_quality_manager_headers()))


def read_component(api: ApiClient, component_id: str, headers: Optional[Headers] = None) -> Entity:
    return get_success_data(api.get_component(component_id, headers or make_quality_manager_headers()))


def read_unit(api: ApiClient, unit_id: str, headers: Optional[Headers] = None) -> Entity:
    return get_success_data(api.get_valve_unit(unit_id, headers or make_quality_manager_headers()))


def read_package(api: ApiClient, package_id: str, headers: Optional[Headers] = None) -> Entity:
    return get_success_data(
        api.get_actuator_package(package_id, headers or make_quality_manager_headers())
    )


def read_license(api: ApiClient, license_id: str, headers: Optional[Headers] = None) -> Entity:
    return get_success_data(
        api.get_monogram_license(license_id, headers or make_quality_manager_headers())
    )


def read_order(api: ApiClient, order_id: str, headers: Optional[Headers] = None) -> Entity:
    return get_success_data(
        api.get_engineered_order(order_id, headers or make_quality_manager_headers())
    )


FRESH_CLOCK = FRESH_CLOCK_UTC
Payloads = Payload
