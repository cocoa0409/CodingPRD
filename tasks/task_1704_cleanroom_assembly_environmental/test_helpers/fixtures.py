"""Composite setup helpers.

Every test starts against an empty database (the harness restarts the server
before each test), so these helpers build complete precondition chains out of
PRD-declared endpoints only.

Identity threading: all four roles are opaque (X-User-ID is never compared to
an entity id). Segregation-sensitive flows therefore take explicit user ids
with distinct defaults — the QA who opens an investigation is never the QA who
approves it, and the technician who records a cleaning cycle is never the QA
who verifies it. Traveler start calls thread the qualified personnel record's
id as the operator's X-User-ID so the gowning-qualification gate is satisfied
under any faithful reading of the entry/start qualification rules.
"""
from prd_bench_local_runner.testing import get_success_data, validate_success

from .api_client import api_client
from .factories import (
    create_audit_finding_payload,
    create_audit_payload,
    create_batch_payload,
    create_certification_payload,
    create_cleaning_cycle_payload,
    create_cleaning_program_payload,
    create_gowning_qualification_payload,
    create_investigation_payload,
    create_material_transfer_payload,
    create_personnel_payload,
    create_room_payload,
    create_sample_payload,
    create_sampling_point_payload,
    create_traveler_payload,
)
from .test_users import (
    TEST_USERS,
    make_environment_tech_headers,
    make_production_operator_headers,
    make_qa_headers,
)

QA = TEST_USERS["qa_headers"]
ENV_TECH = TEST_USERS["environment_tech_headers"]
PROD_OP = TEST_USERS["production_operator_headers"]
MAT_HANDLER = TEST_USERS["material_handler_headers"]

# Distinct opaque identities for segregated pairs.
INVESTIGATOR_ID = "qa-investigator-1"
APPROVER_ID = "qa-approver-2"
RELEASER_ID = "qa-releaser-1"
SAMPLER_ID = "tech-sampler-1"


# ---------------------------------------------------------------------------
# Tier 0: logical clock
# ---------------------------------------------------------------------------

def set_clock(to_iso8601):
    """Advance the server logical clock (QualityAssurance only)."""
    return get_success_data(api_client.set_clock(to_iso8601, QA))


# ---------------------------------------------------------------------------
# Tier 1: single-resource creation
# ---------------------------------------------------------------------------

def create_room(room_code="CR-100", iso_class="ISO_7",
                particle_alert_limit=300000, particle_action_limit=352000,
                viable_alert_limit=50, viable_action_limit=100,
                recert_interval_days=180):
    """Register a cleanroom (born UNCERTIFIED / IN_CONTROL / ACTIVE, version 1)."""
    payload = create_room_payload(
        room_code=room_code, iso_class=iso_class,
        particle_alert_limit=particle_alert_limit,
        particle_action_limit=particle_action_limit,
        viable_alert_limit=viable_alert_limit,
        viable_action_limit=viable_action_limit,
        recert_interval_days=recert_interval_days,
    )
    return get_success_data(api_client.create_room(payload, QA))


def get_room(room_id):
    return get_success_data(api_client.get_room(room_id, QA))


def add_sampling_point(room_id, point_code="SP-01", metric="PARTICLE",
                       zone_iso_class=None):
    """Define a sampling point; zone defaults to the room's own iso_class."""
    if zone_iso_class is None:
        zone_iso_class = get_room(room_id)["iso_class"]
    payload = create_sampling_point_payload(
        point_code=point_code, metric=metric, zone_iso_class=zone_iso_class)
    return get_success_data(api_client.create_sampling_point(room_id, payload, QA))


def create_personnel(employee_code="EMP-100", full_name="Test Operator",
                     role_title="Assembler"):
    payload = create_personnel_payload(
        employee_code=employee_code, full_name=full_name, role_title=role_title)
    return get_success_data(api_client.create_personnel(payload, QA))


def grant_gowning(personnel_id, cleanroom_id):
    """Grant a per-room gowning qualification (valid 365 days from grant)."""
    payload = create_gowning_qualification_payload(personnel_id, cleanroom_id)
    return get_success_data(api_client.create_gowning_qualification(payload, QA))


def create_qualified_personnel(cleanroom_id, employee_code="EMP-100",
                               full_name="Test Operator"):
    """Personnel + QUALIFIED gowning qualification for the room."""
    personnel = create_personnel(employee_code=employee_code, full_name=full_name)
    qualification = grant_gowning(personnel["id"], cleanroom_id)
    return personnel, qualification


def record_sample(sampling_point_id, result_value, sampled_at="2026-08-01T09:00:00Z",
                  tech_headers=None, recurrence_of_excursion_id=None):
    """Record an environmental sample; returns the created sample."""
    payload = create_sample_payload(
        sampling_point_id, result_value=result_value, sampled_at=sampled_at)
    if recurrence_of_excursion_id is not None:
        payload["recurrence_of_excursion_id"] = recurrence_of_excursion_id
    return get_success_data(
        api_client.create_sample(payload, tech_headers or ENV_TECH))


def stage_transfer(cleanroom_id, material_lot="LOT-100",
                   item_description="Sealed component tray", dwell_minutes=0,
                   wiped_down=True):
    """Stage a material transfer into the airlock (born STAGED)."""
    payload = create_material_transfer_payload(
        cleanroom_id, material_lot=material_lot, item_description=item_description,
        dwell_minutes=dwell_minutes, wiped_down=wiped_down)
    return get_success_data(api_client.create_material_transfer(payload, MAT_HANDLER))


def create_batch(cleanroom_id, batch_number="B-100", product_code="PWB-1",
                 op_headers=None):
    payload = create_batch_payload(
        cleanroom_id, batch_number=batch_number, product_code=product_code)
    return get_success_data(api_client.create_batch(payload, op_headers or PROD_OP))


def add_traveler(batch_id, step_sequence=1, step_description="Assemble component",
                 op_headers=None):
    payload = create_traveler_payload(
        step_sequence=step_sequence, step_description=step_description)
    return get_success_data(
        api_client.create_traveler(batch_id, payload, op_headers or PROD_OP))


def start_traveler(traveler_id, operator_user_id):
    """Start a traveler step as the given operator identity."""
    return get_success_data(api_client.start_traveler(
        traveler_id, make_production_operator_headers(operator_user_id)))


def complete_traveler(traveler_id, operator_user_id):
    """Complete a traveler step as the same operator who started it."""
    return get_success_data(api_client.complete_traveler(
        traveler_id, make_production_operator_headers(operator_user_id)))


def create_audit(cleanroom_id, customer_code="CUST-100",
                 window_start="2026-08-01T00:00:00Z",
                 window_end="2026-08-02T00:00:00Z"):
    payload = create_audit_payload(
        cleanroom_id, customer_code=customer_code,
        window_start=window_start, window_end=window_end)
    return get_success_data(api_client.create_audit(payload, QA))


def open_audit(audit_id):
    return get_success_data(api_client.open_audit(audit_id, QA))


def add_audit_finding(audit_id, severity="MINOR", description="Audit finding narrative"):
    payload = create_audit_finding_payload(severity=severity, description=description)
    return get_success_data(api_client.create_audit_finding(audit_id, payload, QA))


# ---------------------------------------------------------------------------
# Tier 2: cleaning validation
# ---------------------------------------------------------------------------

def create_cleaning_program(cleanroom_id, method_code="MOP-STD",
                            required_consecutive_passes=None):
    """Create a cleaning validation program (born DRAFT, count 0)."""
    payload = create_cleaning_program_payload(cleanroom_id, method_code=method_code)
    if required_consecutive_passes is not None:
        payload["required_consecutive_passes"] = required_consecutive_passes
    return get_success_data(api_client.create_cleaning_program(payload, QA))


def record_cycle(program_id, result="PASS", tech_headers=None):
    """EnvironmentTech records a cleaning cycle under the program."""
    payload = create_cleaning_cycle_payload(result=result)
    return get_success_data(
        api_client.create_cleaning_cycle(program_id, payload, tech_headers or ENV_TECH))


def verify_cycle(cycle_id, qa_headers=None):
    """QA verifies a passing RECORDED cycle (verifier != performer)."""
    return get_success_data(
        api_client.verify_cleaning_cycle(cycle_id, qa_headers or QA))


def setup_validated_cleaning_program(cleanroom_id, required_consecutive_passes=1,
                                     method_code="MOP-STD"):
    """Create + activate a program and accumulate enough verified PASS cycles
    to reach VALIDATED. Returns the program."""
    program = create_cleaning_program(
        cleanroom_id, method_code=method_code,
        required_consecutive_passes=required_consecutive_passes)
    get_success_data(api_client.activate_cleaning_program(program["id"], QA))
    for _ in range(required_consecutive_passes):
        cycle = record_cycle(program["id"], result="PASS")
        verify_cycle(cycle["id"])
    return get_success_data(api_client.get_cleaning_program(program["id"], QA))


# ---------------------------------------------------------------------------
# Tier 3: room certification (OCC-guarded) and the certified-room composite
# ---------------------------------------------------------------------------

def certify_room(room_id, executed_at="2026-08-01T00:00:00Z",
                 location_mean_values=None, supersedes_certification_id=None,
                 qa_headers=None):
    """Record a PASS certification: reads the room's current version first so
    the optimistic-concurrency guard observes a fresh expected_room_version."""
    room = get_room(room_id)
    payload = create_certification_payload(
        room["version"], executed_at=executed_at,
        location_mean_values=location_mean_values or [10, 20])
    if supersedes_certification_id is not None:
        payload["supersedes_certification_id"] = supersedes_certification_id
    return get_success_data(
        api_client.create_certification(room_id, payload, qa_headers or QA))


def setup_certified_room(room_code="CR-100", iso_class="ISO_7",
                         particle_alert_limit=300000, particle_action_limit=352000,
                         viable_alert_limit=50, viable_action_limit=100,
                         recert_interval_days=180, required_consecutive_passes=1,
                         executed_at="2026-08-01T00:00:00Z", cert_means=None):
    """Room + VALIDATED cleaning program + PASS certification. Returns the
    refreshed room (CERTIFIED, IN_CONTROL)."""
    room = create_room(
        room_code=room_code, iso_class=iso_class,
        particle_alert_limit=particle_alert_limit,
        particle_action_limit=particle_action_limit,
        viable_alert_limit=viable_alert_limit, viable_action_limit=viable_action_limit,
        recert_interval_days=recert_interval_days)
    setup_validated_cleaning_program(
        room["id"], required_consecutive_passes=required_consecutive_passes)
    certify_room(room["id"], executed_at=executed_at,
                 location_mean_values=cert_means)
    return get_room(room["id"])


# ---------------------------------------------------------------------------
# Tier 4: excursions and investigations
# ---------------------------------------------------------------------------

def record_excursion_sample(sampling_point_id, result_value,
                            sampled_at="2026-08-01T09:00:00Z", tech_user_id=None):
    """Record a sample that exceeds a limit; returns (sample, excursion_id)."""
    headers = ENV_TECH if tech_user_id is None else make_environment_tech_headers(
        tech_user_id)
    sample = record_sample(sampling_point_id, result_value, sampled_at=sampled_at,
                           tech_headers=headers)
    excursion_id = sample["triggered_excursion_id"]
    assert excursion_id, (
        f"Expected an excursion for result {result_value}, got none: {sample!r}")
    return sample, excursion_id


def open_investigation(excursion_id, root_cause=None, product_impact="NONE",
                       disposition="RELEASE", investigator_id=INVESTIGATOR_ID):
    """QA opens an investigation (excursion OPEN -> UNDER_INVESTIGATION)."""
    payload = create_investigation_payload(
        product_impact=product_impact, disposition=disposition)
    if root_cause is not None:
        payload["root_cause"] = root_cause
    return get_success_data(api_client.open_investigation(
        excursion_id, payload, make_qa_headers(investigator_id)))


def approve_investigation(investigation_id, approver_id=APPROVER_ID):
    """QA approves a DRAFT investigation (approver != investigator)."""
    return get_success_data(api_client.approve_investigation(
        investigation_id, make_qa_headers(approver_id)))


def close_excursion(excursion_id, product_impact="NONE", disposition="RELEASE",
                    root_cause=None, investigator_id=INVESTIGATOR_ID,
                    approver_id=APPROVER_ID):
    """Open + approve an investigation; the excursion ends CLOSED."""
    investigation = open_investigation(
        excursion_id, root_cause=root_cause, product_impact=product_impact,
        disposition=disposition, investigator_id=investigator_id)
    approve_investigation(investigation["id"], approver_id=approver_id)
    return get_success_data(api_client.get_investigation(investigation["id"], QA))


# ---------------------------------------------------------------------------
# Tier 5: batch / traveler composites
# ---------------------------------------------------------------------------

def setup_batch_with_travelers(room_id, personnel, num_steps=1,
                               batch_number="B-100", product_code="PWB-1"):
    """OPEN batch with `num_steps` PENDING travelers. The operator identity for
    batch/traveler creation threads the qualified personnel record's id so the
    gowning gate is satisfied. Returns (batch, travelers)."""
    op_headers = make_production_operator_headers(personnel["id"])
    batch = create_batch(room_id, batch_number=batch_number,
                         product_code=product_code, op_headers=op_headers)
    travelers = [
        add_traveler(batch["id"], step_sequence=i + 1, op_headers=op_headers)
        for i in range(num_steps)
    ]
    return batch, travelers


def setup_in_progress_batch(room_id, personnel, batch_number="B-100"):
    """Batch with one traveler started (batch IN_PROGRESS)."""
    batch, travelers = setup_batch_with_travelers(
        room_id, personnel, num_steps=1, batch_number=batch_number)
    start_traveler(travelers[0]["id"], personnel["id"])
    return get_success_data(api_client.get_batch(batch["id"], QA)), travelers[0]


def setup_complete_batch(room_id, personnel, batch_number="B-100"):
    """Batch walked to COMPLETE: one traveler started and completed by the
    qualified operator. Returns the refreshed batch."""
    batch, traveler = setup_in_progress_batch(room_id, personnel,
                                              batch_number=batch_number)
    complete_traveler(traveler["id"], personnel["id"])
    return get_success_data(api_client.get_batch(batch["id"], QA))


def release_batch(batch, releaser_id=RELEASER_ID):
    """QA releases a COMPLETE batch with a fresh OCC version read."""
    current = get_success_data(api_client.get_batch(batch["id"], QA))
    return validate_success(api_client.release_batch(
        batch["id"], {"expected_batch_version": current["version"]},
        make_qa_headers(releaser_id)), 200)


# ---------------------------------------------------------------------------
# Tier 6: audit composites
# ---------------------------------------------------------------------------

def setup_audit_in_progress(room_id, customer_code="CUST-100",
                            window_start="2026-08-01T00:00:00Z",
                            window_end="2026-08-02T00:00:00Z"):
    """Schedule + open an audit (default clock reaches the default window)."""
    audit = create_audit(room_id, customer_code=customer_code,
                         window_start=window_start, window_end=window_end)
    open_audit(audit["id"])
    return get_success_data(api_client.get_audit(audit["id"], QA))
