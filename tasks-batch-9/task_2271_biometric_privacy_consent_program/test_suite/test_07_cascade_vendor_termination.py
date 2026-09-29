"""The vendor-exit chain fired by terminating an executed contract.

Terminating the processor's contract gates its collection point, expires the
consent collected there, spawns the alternative process the employee is owed and
restricts the program.
"""

from test_helpers import (
    HR_ADMIN,
    VENDOR_MANAGER,
    assert_asset_state,
    assert_instant_equals,
    assert_pagination,
    assert_program_state,
    create_consent,
    create_data_subject,
    read_asset,
    read_consent,
    read_program,
    validate_paginated,
    validate_success,
    vendor_operated_active_asset,
)

CLOCKPOINT = {
    "name": "ClockPoint Systems",
    "sells_biometric_data": False,
    "subprocessor_count": 0,
    "deletion_sla_days": 15,
    "subprocessor_disclosure_complete": True,
}


def _vendor_point_with_one_enrolled_employee(api):
    ctx = vendor_operated_active_asset(
        api,
        vendor_overrides=CLOCKPOINT,
        attestation_status="RECEIVED",
        contract_status="EXECUTED",
        activation_clock="2026-08-15T00:00:00Z",
    )
    subject = create_data_subject(api, ctx["program_id"], ctx["jurisdiction_id"], "EMP-0001")
    consent = create_consent(
        api,
        subject["id"],
        ctx["asset_id"],
        target_status="GRANTED",
        written_release_acknowledged=True,
        signature_ref="sig-emp1-r1",
    )
    ctx["subject_id"] = subject["id"]
    ctx["consent_id"] = consent["id"]
    return ctx


def test_termination_gates_the_point_and_expires_the_consent_collected_there(api):
    """Hops one through three of the vendor-exit chain.

    PRD §3.2: "**Hop 2**: every collection point operated by that vendor whose
    status is `ACTIVE` transitions `ACTIVE` → `GATED`, processed in `created_at`
    ascending order."

    Termination stamps the contract's own deadline at 2026-08-15 plus its 30
    contractual days, gates the point without disturbing the original start of
    collection, and expires the granted consent so the point carries nobody.

    Design: Difficulty/transitive_cascade/contract_termination_gates_asset_expires_consent_spawns_accommodation_restricts_program
    """
    ctx = _vendor_point_with_one_enrolled_employee(api)

    terminated = validate_success(
        api.transition_vendor_contract(ctx["contract_id"], {"to_status": "TERMINATED"}, VENDOR_MANAGER)
    )

    assert terminated["status"] == "TERMINATED"
    assert_instant_equals(terminated["terminated_at"], "2026-08-15T00:00:00.000Z", "terminated_at")
    assert_instant_equals(
        terminated["deletion_deadline_at"], "2026-09-14T00:00:00.000Z", "deletion_deadline_at"
    )
    assert terminated["deletion_certificate_ref"] is None

    asset = read_asset(api, ctx["asset_id"])
    assert_asset_state(
        asset,
        status="GATED",
        collection_started_at="2026-08-15T00:00:00.000Z",
        enrolled_subject_count=0,
    )

    consent = read_consent(api, ctx["consent_id"])
    assert consent["status"] == "EXPIRED"


def test_termination_spawns_exactly_one_auto_consent_expiry_accommodation(api):
    """Hop four of the vendor-exit chain compensates the employee.

    PRD §3.2: "**Hop 4**: because those consents expired, each expired consent
    whose data subject has a `subject_type` of `EMPLOYEE` spawns one alternative
    accommodation in `REQUESTED` status with `origin` set to
    `AUTO_CONSENT_EXPIRY`."

    The timekeeping surface maps to a manual timesheet, and the five-day
    provisioning deadline runs from the 2026-08-15 clock.

    Design: Difficulty/transitive_cascade/contract_termination_gates_asset_expires_consent_spawns_accommodation_restricts_program
    """
    ctx = _vendor_point_with_one_enrolled_employee(api)

    validate_success(
        api.transition_vendor_contract(ctx["contract_id"], {"to_status": "TERMINATED"}, VENDOR_MANAGER)
    )

    rows, meta = validate_paginated(
        api.list_accommodations(HR_ADMIN, {"data_subject_id": ctx["subject_id"]})
    )

    assert_pagination(meta, total_count=1, has_more=False, limit=10, offset=0)
    assert len(rows) == 1
    accommodation = rows[0]
    assert accommodation["origin"] == "AUTO_CONSENT_EXPIRY"
    assert accommodation["status"] == "REQUESTED"
    assert accommodation["created_from_consent_id"] == ctx["consent_id"]
    assert accommodation["method"] == "MANUAL_TIMESHEET"
    assert accommodation["asset_id"] == ctx["asset_id"]
    assert_instant_equals(accommodation["sla_due_at"], "2026-08-20T00:00:00.000Z", "sla_due_at")


def test_termination_restricts_the_program_through_its_recomputed_counters(api):
    """Hop five of the vendor-exit chain moves the master gate.

    PRD §3.2: "**Hop 5**: because points became gated and consent gaps opened,
    the program's `gated_asset_count`, `consent_gap_count` and
    `open_deletion_obligation_count` are recomputed together with `posture`."

    Design: Difficulty/transitive_cascade/contract_termination_gates_asset_expires_consent_spawns_accommodation_restricts_program
    """
    ctx = _vendor_point_with_one_enrolled_employee(api)

    before = read_program(api, ctx["program_id"])
    assert_program_state(
        before,
        posture="OPEN",
        gated_asset_count=0,
        consent_gap_count=0,
        open_deletion_obligation_count=0,
    )

    validate_success(
        api.transition_vendor_contract(ctx["contract_id"], {"to_status": "TERMINATED"}, VENDOR_MANAGER)
    )

    after = read_program(api, ctx["program_id"])
    assert_program_state(
        after,
        posture="RESTRICTED",
        gated_asset_count=1,
        consent_gap_count=1,
        open_deletion_obligation_count=1,
    )
