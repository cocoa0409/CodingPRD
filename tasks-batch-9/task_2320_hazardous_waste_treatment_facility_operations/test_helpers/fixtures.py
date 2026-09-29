"""Composite setup helpers for multi-step test prerequisites.

The database is empty and the logical clock reads 2026-08-01T00:00:00Z at the
start of every test, so every precondition here is built from scratch through
the documented endpoints. Setup calls use the lenient `get_success_data()` so a
broken precondition reports itself as a setup failure rather than as a confusing
assertion failure inside the test body.

Reading conventions
-------------------
`read_*` helpers re-read a row through its GET endpoint, which is how derived
and clock-dependent fields (posture, accumulation days, assurance figures) are
observed after a mutation elsewhere.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_START
from .factories import (
    air_monitoring_payload,
    batch_operation_payload,
    certify_payload,
    clock_payload,
    complete_batch_payload,
    compliance_payload,
    container_payload,
    custody_payload,
    discrepancy_resolution_payload,
    facility_payload,
    finding_payload,
    finding_status_payload,
    generator_payload,
    generator_status_payload,
    inspection_payload,
    instrument_payload,
    ldr_verification_payload,
    manifest_line_payload,
    manifest_payload,
    profile_decision_payload,
    profile_status_payload,
    receipt_line,
    receive_payload,
    sample_payload,
    storage_unit_payload,
    storage_unit_status_payload,
    tank_unit_payload,
    treatment_batch_payload,
    waste_profile_payload,
)
from .test_users import TEST_USERS, make_generator_headers


class Scenario(dict):
    """A bag of the rows a composite setup created, with attribute access."""

    def __getattr__(self, item):
        try:
            return self[item]
        except KeyError as exc:  # pragma: no cover - developer error
            raise AttributeError(item) from exc

    def __setattr__(self, key, value):
        self[key] = value


# ═══ Tier 0: clock and reads ══════════════════════════════════════════════════


def set_clock(current_utc: str = CLOCK_START) -> Dict[str, Any]:
    """Move the logical clock. Every role may do this; it mutates no row."""
    return get_success_data(api_client.set_clock(clock_payload(current_utc), TEST_USERS["admin"]))


advance_clock = set_clock


def read_facility(facility_id: str, headers=None) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_facility(facility_id, headers or TEST_USERS["compliance_manager"])
    )


def read_assurance_summary(facility_id: str, headers=None) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_financial_assurance_summary(
            facility_id, headers or TEST_USERS["compliance_manager"]
        )
    )


def read_instrument(instrument_id: str, headers=None) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_instrument(instrument_id, headers or TEST_USERS["compliance_manager"])
    )


def read_generator(generator_id: str, headers=None) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_generator(generator_id, headers or TEST_USERS["compliance_manager"])
    )


def read_reliability(generator_id: str, headers=None) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_reliability_score(generator_id, headers or TEST_USERS["compliance_manager"])
    )


def read_profile(profile_id: str, headers=None) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_waste_profile(profile_id, headers or TEST_USERS["compliance_manager"])
    )


def read_unit(unit_id: str, headers=None) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_storage_unit(unit_id, headers or TEST_USERS["compliance_manager"])
    )


def read_container(container_id: str, headers=None) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_container(container_id, headers or TEST_USERS["compliance_manager"])
    )


def read_manifest(manifest_id: str, headers=None) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_manifest(manifest_id, headers or TEST_USERS["clerk"])
    )


def read_lines(manifest_id: str, headers=None) -> List[Dict[str, Any]]:
    """All lines of a manifest, always ordered by line_number ascending."""
    return get_success_data(
        api_client.list_manifest_lines(manifest_id, headers or TEST_USERS["clerk"])
    )


def read_line(manifest_id: str, line_number: int = 1, headers=None) -> Dict[str, Any]:
    for line in read_lines(manifest_id, headers):
        if line["line_number"] == line_number:
            return line
    raise AssertionError(f"manifest {manifest_id} has no line {line_number}")


def read_batch(batch_id: str, headers=None) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_treatment_batch(batch_id, headers or TEST_USERS["operator"])
    )


def read_repair_order(order_id: str, headers=None) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_repair_order(order_id, headers or TEST_USERS["compliance_manager"])
    )


def read_repair_orders_for_unit(unit_id: str, headers=None) -> List[Dict[str, Any]]:
    return get_success_data(
        api_client.list_repair_orders(
            headers or TEST_USERS["compliance_manager"], params={"storage_unit_id": unit_id}
        )
    )


def read_finding(finding_id: str, headers=None) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_compliance_finding(finding_id, headers or TEST_USERS["compliance_manager"])
    )


# ═══ Tier 1: state progression ════════════════════════════════════════════════


def create_facility(**overrides) -> Dict[str, Any]:
    """A facility opens with an ACTIVE permit and no assurance posted."""
    return get_success_data(
        api_client.create_facility(facility_payload(**overrides), TEST_USERS["admin"])
    )


def post_instrument(
    facility_id: str,
    face_amount_cents: int = 90_000_000,
    expected_facility_version: Optional[int] = None,
    instrument_type: str = "TRUST_FUND",
    effective_on: str = "2026-07-01",
    headers=None,
) -> Dict[str, Any]:
    """Post an assurance instrument, guarded by the facility's version."""
    version = (
        expected_facility_version
        if expected_facility_version is not None
        else read_facility(facility_id)["version"]
    )
    return get_success_data(
        api_client.create_instrument(
            instrument_payload(
                facility_id,
                version,
                face_amount_cents=face_amount_cents,
                instrument_type=instrument_type,
                effective_on=effective_on,
            ),
            headers or TEST_USERS["compliance_manager"],
        ),
        expected_status=201,
    )


def create_funded_facility(face_amount_cents: int = 90_000_000, **facility_overrides):
    """Facility plus one ACTIVE instrument large enough to clear the requirement.

    Returns (facility_row_after_the_post, instrument_row).
    """
    facility = create_facility(**facility_overrides)
    instrument = post_instrument(
        facility["id"],
        face_amount_cents=face_amount_cents,
        expected_facility_version=facility["version"],
    )
    return read_facility(facility["id"]), instrument


def create_generator(**overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_generator(generator_payload(**overrides), TEST_USERS["admin"])
    )


def set_generator_status(generator_id: str, to_status: str, reason_code: Optional[str] = None):
    return get_success_data(
        api_client.set_generator_status(
            generator_id,
            generator_status_payload(to_status, reason_code),
            TEST_USERS["compliance_manager"],
        )
    )


def create_storage_unit(facility_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_storage_unit(
            storage_unit_payload(facility_id, **overrides), TEST_USERS["admin"]
        ),
        expected_status=201,
    )


def create_tank_unit(facility_id: str, **overrides) -> Dict[str, Any]:
    """A LEVEL_2 TANK_SYSTEM: leak definition 250.0 ppm, daily inspection."""
    return get_success_data(
        api_client.create_storage_unit(
            tank_unit_payload(facility_id, **overrides), TEST_USERS["admin"]
        ),
        expected_status=201,
    )


def set_unit_status(unit_id: str, to_status: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.set_storage_unit_status(
            unit_id,
            storage_unit_status_payload(to_status, **overrides),
            TEST_USERS["compliance_manager"],
        )
    )


def create_draft_profile(generator_id: str, facility_id: str, **overrides) -> Dict[str, Any]:
    """Filed by the generator itself, so the identity is entity backed."""
    return get_success_data(
        api_client.create_waste_profile(
            waste_profile_payload(generator_id, facility_id, **overrides),
            make_generator_headers(generator_id),
        ),
        expected_status=201,
    )


def submit_profile(profile_id: str, generator_id: str, payload=None) -> Dict[str, Any]:
    """Submission for characterisation is the Generator's exclusive act."""
    return get_success_data(
        api_client.submit_waste_profile(
            profile_id, make_generator_headers(generator_id), payload=payload
        )
    )


def record_sample(
    profile_id: str,
    expected_waste_profile_version: Optional[int] = None,
    headers=None,
    **sample_overrides,
) -> Dict[str, Any]:
    """Record one laboratory run against the profile's current version."""
    version = (
        expected_waste_profile_version
        if expected_waste_profile_version is not None
        else read_profile(profile_id)["version"]
    )
    return get_success_data(
        api_client.create_profile_sample(
            profile_id,
            sample_payload(version, **sample_overrides),
            headers or TEST_USERS["chemist"],
        ),
        expected_status=201,
    )


def sign_profile_decision(
    profile_id: str,
    decision: str = "APPROVE",
    approved_treatment_method: str = "INCINERATION",
    headers=None,
    **overrides,
) -> Dict[str, Any]:
    """Signed by a chemist other than the sample recorder."""
    return get_success_data(
        api_client.decide_waste_profile(
            profile_id,
            profile_decision_payload(decision, approved_treatment_method, **overrides),
            headers or TEST_USERS["chemist_2"],
        )
    )


def set_profile_status(profile_id: str, to_status: str, reason_code: Optional[str] = None):
    return get_success_data(
        api_client.set_waste_profile_status(
            profile_id,
            profile_status_payload(to_status, reason_code),
            TEST_USERS["compliance_manager"],
        )
    )


def create_approved_profile(
    generator_id: str,
    facility_id: str,
    profile_overrides: Optional[Dict[str, Any]] = None,
    sample_overrides: Optional[Dict[str, Any]] = None,
    approved_treatment_method: str = "INCINERATION",
) -> Dict[str, Any]:
    """DRAFT -> SUBMITTED -> passing sample -> APPROVED, honouring the
    separation of duties between the sample recorder and the decision signer."""
    profile = create_draft_profile(generator_id, facility_id, **(profile_overrides or {}))
    submitted = submit_profile(profile["id"], generator_id)
    record_sample(
        profile["id"], submitted["version"], **(sample_overrides or {})
    )
    return sign_profile_decision(
        profile["id"], "APPROVE", approved_treatment_method
    )


# ═══ Tier 2: entity hierarchy ═════════════════════════════════════════════════


def create_manifest(
    generator_id: str,
    facility_id: str,
    lines: Optional[List[Dict[str, Any]]] = None,
    headers=None,
    **overrides,
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_manifest(
            manifest_payload(generator_id, facility_id, lines=lines, **overrides),
            headers or TEST_USERS["clerk"],
        ),
        expected_status=201,
    )


def receive_manifest(manifest_id: str, received_lines: List[Dict[str, Any]]) -> Dict[str, Any]:
    return get_success_data(
        api_client.receive_manifest(
            manifest_id, receive_payload(received_lines), TEST_USERS["clerk"]
        )
    )


def resolve_discrepancy(manifest_id: str, resolution_type: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.resolve_manifest_discrepancy(
            manifest_id,
            discrepancy_resolution_payload(resolution_type, **overrides),
            TEST_USERS["compliance_manager"],
        )
    )


def certify_manifest(manifest_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.certify_manifest(manifest_id, certify_payload(**overrides), TEST_USERS["clerk"])
    )


def place_container(manifest_line_id: str, storage_unit_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_container(
            container_payload(manifest_line_id, storage_unit_id, **overrides),
            TEST_USERS["clerk"],
        ),
        expected_status=201,
    )


def seal_container(container_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.set_container_custody_state(
            container_id, custody_payload("SEALED"), TEST_USERS["clerk"]
        )
    )


def void_container(container_id: str, reason_code: str = "REPACK_ERROR") -> Dict[str, Any]:
    return get_success_data(
        api_client.set_container_custody_state(
            container_id, custody_payload("VOIDED", reason_code), TEST_USERS["clerk"]
        )
    )


def set_container_compliance(
    container_id: str, to_compliance_state: str, finding_code: Optional[str] = None
) -> Dict[str, Any]:
    return get_success_data(
        api_client.set_container_compliance_state(
            container_id,
            compliance_payload(to_compliance_state, finding_code),
            TEST_USERS["compliance_manager"],
        )
    )


# ═══ Tier 3: lifecycle shortcuts ══════════════════════════════════════════════


def setup_received_manifest(
    *,
    facility_overrides: Optional[Dict[str, Any]] = None,
    unit_overrides: Optional[Dict[str, Any]] = None,
    profile_overrides: Optional[Dict[str, Any]] = None,
    sample_overrides: Optional[Dict[str, Any]] = None,
    generator_overrides: Optional[Dict[str, Any]] = None,
    approved_treatment_method: str = "INCINERATION",
    declared_quantity_kg: float = 1000.0,
    declared_container_count: int = 4,
    is_bulk: bool = False,
    received_quantity_kg: Optional[float] = None,
    received_container_count: Optional[int] = None,
    face_amount_cents: int = 90_000_000,
    with_unit: bool = True,
) -> Scenario:
    """The canonical intake chain: funded facility, generator, optional storage
    unit, APPROVED profile, one-line manifest, and the receipt at the dock.

    Returns a Scenario carrying facility, instrument, generator, unit, profile,
    manifest, lines and line (line 1).
    """
    set_clock()
    facility, instrument = create_funded_facility(
        face_amount_cents=face_amount_cents, **(facility_overrides or {})
    )
    generator = create_generator(**(generator_overrides or {}))
    unit = create_storage_unit(facility["id"], **(unit_overrides or {})) if with_unit else None
    profile = create_approved_profile(
        generator["id"],
        facility["id"],
        profile_overrides=profile_overrides,
        sample_overrides=sample_overrides,
        approved_treatment_method=approved_treatment_method,
    )
    manifest = create_manifest(
        generator["id"],
        facility["id"],
        lines=[
            manifest_line_payload(
                profile["id"], declared_quantity_kg, declared_container_count, is_bulk
            )
        ],
    )
    received = receive_manifest(
        manifest["id"],
        [
            receipt_line(
                1,
                declared_quantity_kg if received_quantity_kg is None else received_quantity_kg,
                declared_container_count
                if received_container_count is None
                else received_container_count,
            )
        ],
    )
    lines = read_lines(manifest["id"])
    return Scenario(
        facility=read_facility(facility["id"]),
        instrument=instrument,
        generator=read_generator(generator["id"]),
        unit=read_unit(unit["id"]) if unit else None,
        profile=profile,
        manifest=received,
        lines=lines,
        line=lines[0],
    )


def setup_container_in_storage(
    *, net_weight_kg: float = 200.0, container_overrides: Optional[Dict[str, Any]] = None, **kwargs
) -> Scenario:
    """The intake chain plus one FILLING container placed in the storage unit."""
    scenario = setup_received_manifest(**kwargs)
    scenario.container = place_container(
        scenario.line["id"],
        scenario.unit["id"],
        net_weight_kg=net_weight_kg,
        **(container_overrides or {}),
    )
    scenario.unit = read_unit(scenario.unit["id"])
    scenario.facility = read_facility(scenario.facility["id"])
    # Placement moves the receipt line's allocated_container_mass_kg, so the
    # pre-placement line snapshot is stale; re-read it alongside unit/facility.
    scenario.lines = read_lines(scenario.manifest["id"])
    scenario.line = read_line(scenario.manifest["id"])
    return scenario


def setup_sealed_container(**kwargs) -> Scenario:
    """The intake chain plus one SEALED container ready to be staged."""
    scenario = setup_container_in_storage(**kwargs)
    scenario.container = seal_container(scenario.container["id"])
    return scenario


def create_batch(
    facility_id: str,
    storage_unit_id: str,
    container_ids: List[str],
    treatment_method: str = "INCINERATION",
    window_start: str = "2026-08-01T00:00:00Z",
    window_end: str = "2026-08-01T12:00:00Z",
    headers=None,
    **overrides,
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_treatment_batch(
            treatment_batch_payload(
                facility_id,
                storage_unit_id,
                container_ids,
                treatment_method=treatment_method,
                window_start=window_start,
                window_end=window_end,
                **overrides,
            ),
            headers or TEST_USERS["operator"],
        ),
        expected_status=201,
    )


def setup_planned_batch(
    *,
    treatment_method: str = "INCINERATION",
    window_start: str = "2026-08-01T00:00:00Z",
    window_end: str = "2026-08-01T12:00:00Z",
    **kwargs,
) -> Scenario:
    """The intake chain plus a PLANNED batch that has staged the container."""
    scenario = setup_sealed_container(**kwargs)
    scenario.batch = create_batch(
        scenario.facility["id"],
        scenario.unit["id"],
        [scenario.container["id"]],
        treatment_method=treatment_method,
        window_start=window_start,
        window_end=window_end,
    )
    scenario.container = read_container(scenario.container["id"])
    scenario.unit = read_unit(scenario.unit["id"])
    scenario.facility = read_facility(scenario.facility["id"])
    return scenario


def start_batch(batch_id: str, headers=None) -> Dict[str, Any]:
    return get_success_data(
        api_client.batch_operation(
            batch_id, batch_operation_payload("START"), headers or TEST_USERS["operator"]
        )
    )


def complete_batch(
    batch_id: str,
    residue_mass_kg: float,
    residue_constituent_ppm: float,
    residue_flash_point_c: Optional[float] = None,
    headers=None,
) -> Dict[str, Any]:
    return get_success_data(
        api_client.batch_operation(
            batch_id,
            complete_batch_payload(
                residue_mass_kg, residue_constituent_ppm, residue_flash_point_c
            ),
            headers or TEST_USERS["operator"],
        )
    )


def abort_batch(batch_id: str, reason_code: str = "FEED_SYSTEM_FAULT", headers=None):
    return get_success_data(
        api_client.batch_operation(
            batch_id,
            batch_operation_payload("ABORT", reason_code=reason_code),
            headers or TEST_USERS["operator"],
        )
    )


def verify_batch_ldr(
    batch_id: str, verification_sample_ppm: float, headers=None, **overrides
) -> Dict[str, Any]:
    """Signed by a user other than the one who completed the batch."""
    return get_success_data(
        api_client.verify_batch_ldr(
            batch_id,
            ldr_verification_payload(verification_sample_ppm, **overrides),
            headers or TEST_USERS["compliance_manager"],
        )
    )


def setup_treated_batch(
    *,
    residue_mass_kg: float = 150.0,
    residue_constituent_ppm: float = 400.0,
    residue_flash_point_c: Optional[float] = None,
    **kwargs,
) -> Scenario:
    """A batch carried through START and COMPLETE, awaiting LDR verification."""
    scenario = setup_planned_batch(**kwargs)
    start_batch(scenario.batch["id"])
    scenario.batch = complete_batch(
        scenario.batch["id"], residue_mass_kg, residue_constituent_ppm, residue_flash_point_c
    )
    scenario.facility = read_facility(scenario.facility["id"])
    return scenario


# ═══ Tier 4: inspections, repair orders and findings ══════════════════════════


def record_inspection(unit_id: str, headers=None, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_inspection_event(
            inspection_payload(unit_id, **overrides),
            headers or TEST_USERS["compliance_manager"],
        ),
        expected_status=201,
    )


def condemn_container_by_inspection(unit_id: str, container_id: str, headers=None):
    """A CONTAINER_LEAK finding fires the condemnation cascade."""
    return get_success_data(
        api_client.create_inspection_event(
            inspection_payload(
                unit_id,
                inspection_type="WEEKLY_CONTAINER_AREA",
                finding_code="CONTAINER_LEAK",
                container_id=container_id,
            ),
            headers or TEST_USERS["compliance_manager"],
        ),
        expected_status=201,
    )


def setup_tank_with_repair_order(
    *,
    measured_organic_vapor_ppm: float = 300.0,
    funded: bool = False,
    facility_overrides: Optional[Dict[str, Any]] = None,
    unit_overrides: Optional[Dict[str, Any]] = None,
) -> Scenario:
    """A LEVEL_2 tank whose air-monitoring reading auto-opened a repair order."""
    set_clock()
    if funded:
        facility, instrument = create_funded_facility(**(facility_overrides or {}))
    else:
        facility, instrument = create_facility(**(facility_overrides or {})), None
    unit = create_tank_unit(facility["id"], **(unit_overrides or {}))
    inspection = get_success_data(
        api_client.create_inspection_event(
            air_monitoring_payload(unit["id"], measured_organic_vapor_ppm),
            TEST_USERS["compliance_manager"],
        ),
        expected_status=201,
    )
    orders = read_repair_orders_for_unit(unit["id"])
    return Scenario(
        facility=read_facility(facility["id"]),
        instrument=instrument,
        unit=read_unit(unit["id"]),
        inspection=inspection,
        order=orders[0] if orders else None,
        orders=orders,
    )


def repair_action(order_id: str, action: str, headers=None, **overrides) -> Dict[str, Any]:
    from .factories import repair_action_payload

    return get_success_data(
        api_client.repair_order_action(
            order_id,
            repair_action_payload(action, **overrides),
            headers or TEST_USERS["operator"],
        )
    )


def file_finding(facility_id: str, headers=None, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_compliance_finding(
            finding_payload(facility_id, **overrides), headers or TEST_USERS["inspector"]
        ),
        expected_status=201,
    )


def set_finding_status(finding_id: str, to_status: str, headers=None, **overrides):
    """RESPONDED is the ComplianceManager's move; CLOSED and REOPENED belong to
    the RegulatoryInspector."""
    if headers is None:
        headers = (
            TEST_USERS["compliance_manager"]
            if to_status == "RESPONDED"
            else TEST_USERS["inspector"]
        )
    return get_success_data(
        api_client.set_compliance_finding_status(
            finding_id, finding_status_payload(to_status, **overrides), headers
        )
    )


def setup_snc_finding(
    *,
    corrective_action_due_at: str = "2026-08-31T00:00:00Z",
    funded: bool = True,
    facility_overrides: Optional[Dict[str, Any]] = None,
) -> Scenario:
    """A facility carrying one OPEN SNC finding and its 5,000,000-cent reserve."""
    set_clock()
    if funded:
        facility, instrument = create_funded_facility(**(facility_overrides or {}))
    else:
        facility, instrument = create_facility(**(facility_overrides or {})), None
    finding = file_finding(
        facility["id"],
        finding_class="SNC",
        corrective_action_due_at=corrective_action_due_at,
    )
    return Scenario(
        facility=read_facility(facility["id"]),
        instrument=instrument,
        finding=read_finding(finding["id"]),
    )
