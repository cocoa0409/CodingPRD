"""Enrollment side effects, attendance/progress computed fields, and the
ACTIVE-state branching to divergent terminals (graduate vs dismiss).

Translates corner-design `entities` (computed/immutable) instances, the
`consistency_model` instance, and the `non_linear_state_machine` branching
difficulty instance.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    create_attendance_record_payload,
    assert_attendance_record,
    assert_enrollment,
    setup_active_enrollment,
    setup_graduated_isa,
    get_isa_for_enrollment,
)

ADMIN = TEST_USERS["admissions_officer_headers"]
SERVICING = TEST_USERS["servicing_officer_headers"]


def test_attendance_record_is_immutable_no_version_field():
    """PRD §2.4: "An AttendanceRecord carries only `id` and `created_at`; it has neither an `updated_at` field nor a `version` field, because once written it is never modified."

    Design: Corner/entities/attendance_record_is_immutable_no_version_field
    """
    cohort, applicant, enrollment = setup_active_enrollment(
        "UPFRONT", email="att@example.com", progress_pct=50
    )
    # The setup already recorded one attendance event; record another and inspect it.
    resp = api_client.create_attendance_record(
        create_attendance_record_payload(enrollment["id"], present=True, cumulative_progress_pct=60), ADMIN
    )
    data = validate_success(resp, 201)
    assert "id" in data and data["id"]
    assert "created_at" in data and data["created_at"]
    assert "version" not in data, "AttendanceRecord must not carry a version field"
    assert "updated_at" not in data, "AttendanceRecord must not carry an updated_at field"
    assert_attendance_record(data)


def test_enrollment_attendance_progress_computed_from_records():
    """PRD §3.4: "The `attendance_pct` is one hundred times the number of present sessions divided by the total number of recorded sessions, and is zero when no sessions have been recorded. The `progress_pct` is the `cumulative_progress_pct` of the most recently created attendance record, again zero when none exist."

    Design: Corner/entities/enrollment_attendance_progress_computed_from_records
    """
    # Fresh ACTIVE enrollment; record 2 present + 2 absent, latest progress 75.
    cohort, applicant, enrollment = setup_active_enrollment(
        "UPFRONT", email="cmp@example.com", present=True, progress_pct=25
    )
    enr_id = enrollment["id"]
    # setup recorded one present@25; add three more to reach 2 present, 2 absent.
    get_success_data(api_client.create_attendance_record(
        create_attendance_record_payload(enr_id, present=False, cumulative_progress_pct=50,
                                          session_date="2026-02-03T00:00:00Z"), ADMIN))
    get_success_data(api_client.create_attendance_record(
        create_attendance_record_payload(enr_id, present=True, cumulative_progress_pct=60,
                                          session_date="2026-02-04T00:00:00Z"), ADMIN))
    get_success_data(api_client.create_attendance_record(
        create_attendance_record_payload(enr_id, present=False, cumulative_progress_pct=75,
                                          session_date="2026-02-05T00:00:00Z"), ADMIN))
    data = get_success_data(api_client.get_enrollment(enr_id, ADMIN))
    assert data["attendance_pct"] == 50, f"expected 50, got {data['attendance_pct']}"
    assert data["progress_pct"] == 75, f"expected 75, got {data['progress_pct']}"


def test_graduate_cascade_visible_in_same_response():
    """PRD §3.4: "graduating an ISA-financed enrollment activates its linked `PENDING` ISA contract to `ACTIVE` as a cross-entity cascade — the moment at which income reporting and payment collection become possible and the contract's `remaining_cap_cents` is set equal to its `cap_cents`."
    PRD §2.5: "These derived fields are reconciled immediately as the underlying payment ledger changes — the system never serves a contract whose ledger fields disagree with its payment rows."

    Design: Corner/consistency_model/graduate_cascade_visible_in_same_response
    """
    cohort, applicant, enrollment = setup_active_enrollment("ISA", email="im@example.com", progress_pct=100)
    isa = get_isa_for_enrollment(enrollment["id"], SERVICING)
    assert isa["status"] == "PENDING"
    grad = validate_success(api_client.graduate_enrollment(enrollment["id"], ADMIN), 200)
    assert grad["status"] == "GRADUATED"
    isa_after = validate_success(api_client.get_isa_contract(isa["id"], SERVICING), 200)
    assert isa_after["status"] == "ACTIVE", "ISA activation must be visible immediately"


def test_enrollment_active_branches_to_graduated():
    """PRD §3.4: "the `AdmissionsOfficer` may directly graduate a single `ACTIVE` enrollment, moving it `ACTIVE → GRADUATED`; this direct route is guarded by the requirement that the enrollment's `progress_pct` has reached 100 or more, and an attempt below that bar is rejected with `ERR_PROGRESS_INCOMPLETE`."
    PRD §3.4: "A graduate still counts toward `seats_committed`."

    Design: Difficulty/non_linear_state_machine/enrollment_active_branches_to_divergent_terminals
    """
    cohort, applicant, enrollment, isa = setup_graduated_isa(email="grad@example.com")
    assert enrollment["status"] == "GRADUATED"
    assert isa["status"] == "ACTIVE", "graduate activates the linked ISA"
    coh = get_success_data(api_client.get_cohort(cohort["id"], ADMIN))
    assert coh["seats_committed"] == 1, "graduate keeps the seat committed"


def test_enrollment_active_branches_to_dismissed_forfeits_deposit_and_releases_seat():
    """PRD §3.4: "A dismissal releases the seat (decrementing the cohort's `seats_committed` by one), voids any linked `PENDING` ISA contract to `VOIDED`, and forfeits the deposit by moving it `HELD → FORFEITED`."

    Design: Difficulty/non_linear_state_machine/enrollment_active_branches_to_divergent_terminals
    """
    cohort, applicant, enrollment = setup_active_enrollment(
        "ISA", email="dis@example.com", present=False, progress_pct=10
    )
    coh_id = cohort["id"]
    isa = get_isa_for_enrollment(enrollment["id"], SERVICING)
    dismissed = validate_success(api_client.dismiss_enrollment(enrollment["id"], ADMIN), 200)
    assert dismissed["status"] == "DISMISSED"
    # Deposit forfeited.
    deposits = get_success_data(api_client.list_deposits(ADMIN, params={"enrollment_id": enrollment["id"]}))
    dep = deposits[0] if isinstance(deposits, list) else deposits["data"][0]
    assert dep["status"] == "FORFEITED", "dismiss forfeits the deposit"
    # Seat released.
    coh = get_success_data(api_client.get_cohort(coh_id, ADMIN))
    assert coh["seats_committed"] == 0, "dismiss releases the seat"
    # Linked PENDING ISA voided.
    isa_after = get_success_data(api_client.get_isa_contract(isa["id"], SERVICING))
    assert isa_after["status"] == "VOIDED", "dismiss voids the linked PENDING ISA"


def test_isa_activation_requires_enrollment_graduated():
    """PRD §3.4: "the `AdmissionsOfficer` may directly graduate a single `ACTIVE` enrollment, moving it `ACTIVE → GRADUATED`; this direct route is guarded by the requirement that the enrollment's `progress_pct` has reached 100 or more, and an attempt below that bar is rejected with `ERR_PROGRESS_INCOMPLETE`."
    PRD §3.4: "graduating an ISA-financed enrollment activates its linked `PENDING` ISA contract to `ACTIVE` as a cross-entity cascade — the moment at which income reporting and payment collection become possible and the contract's `remaining_cap_cents` is set equal to its `cap_cents`."

    Design: Difficulty/cross_entity_state_dependency/isa_activation_requires_enrollment_graduated
    """
    cohort, applicant, enrollment = setup_active_enrollment(
        "ISA", email="xen@example.com", present=True, progress_pct=80
    )
    isa = get_isa_for_enrollment(enrollment["id"], SERVICING)
    resp = api_client.graduate_enrollment(enrollment["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_PROGRESS_INCOMPLETE.value)
    isa_after = get_success_data(api_client.get_isa_contract(isa["id"], SERVICING))
    assert isa_after["status"] == "PENDING", "ISA never activates without graduation"


def test_isa_stays_pending_until_enrollment_graduates():
    """PRD §3.4: "graduating an ISA-financed enrollment activates its linked `PENDING` ISA contract to `ACTIVE` as a cross-entity cascade — the moment at which income reporting and payment collection become possible and the contract's `remaining_cap_cents` is set equal to its `cap_cents`."

    Design: Difficulty/cross_entity_state_dependency/isa_activation_requires_enrollment_graduated
    """
    # ACTIVE enrollment whose progress has not yet reached 100; the ISA must remain
    # PENDING because activation is gated on the enrollment graduating.
    cohort, applicant, enrollment = setup_active_enrollment(
        "ISA", email="stillpending@example.com", present=True, progress_pct=50
    )
    assert enrollment["status"] == "ACTIVE"
    isa = get_isa_for_enrollment(enrollment["id"], SERVICING)
    assert isa["status"] == "PENDING", "ISA stays PENDING until its enrollment graduates"


def test_dismissal_at_or_above_50_attendance_rejected():
    """PRD §3.4: "Dismissing an enrollment for poor attendance moves it `ACTIVE → DISMISSED`, but is justified only when the enrollment's `attendance_pct` is below 50; a dismissal attempted at or above 50 percent attendance is rejected with `ERR_DISMISSAL_NOT_JUSTIFIED`."

    Design: Difficulty/non_linear_state_machine/enrollment_active_branches_to_divergent_terminals
    """
    cohort, applicant, enrollment = setup_active_enrollment(
        "UPFRONT", email="just@example.com", present=True, progress_pct=60
    )
    # Single present session -> attendance_pct == 100 (>= 50).
    resp = api_client.dismiss_enrollment(enrollment["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_DISMISSAL_NOT_JUSTIFIED.value)
