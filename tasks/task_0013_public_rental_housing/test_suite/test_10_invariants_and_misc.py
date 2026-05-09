"""Conserved-quantity invariants, optimistic concurrency, and audit/log behavior.

Covers PRD §2.4 (optimistic concurrency, version field), §2.6 (sync-event log), §2.9
(concurrency rules), and supports SCAFFOLD_DIFFICULTY_DESIGN instances:
- housing_unit_availability_invariant (compensating_invariant)
- applicant_active_application_count_invariant (compensating_invariant)

# difficulty: compensating_invariant/housing_unit_availability_invariant
# difficulty: compensating_invariant/applicant_active_application_count_invariant
"""

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    OFFICER_HEADERS,
    advance_clock_by,
    api_client as api,
    create_allocation_payload,
    create_application_payload,
    create_housing_unit,
    create_housing_unit_payload,
    create_program,
    create_published_allocation,
    create_queued_application,
    fresh_applicant_id,
    make_applicant_headers,
    setup_application_in_exit_pending,
    validate_error,
    validate_paginated,
    validate_success,
)


# ──────────────────────────────────────────────────────────
# Difficulty: compensating_invariant/housing_unit_availability_invariant
# ──────────────────────────────────────────────────────────


def _count_units_in_status(program_id: str, status: str) -> int:
    units, meta = validate_paginated(
        api.list_housing_units(program_id, OFFICER_HEADERS, params={"limit": 100})
    )
    # Some implementations support a `status` filter; we collect ourselves regardless.
    return sum(1 for u in units if u.get("status") == status)


def test_unit_availability_invariant_after_allocate_then_reject():
    """PRD §3.5: "the applicant may instead reject the offered allocation while it is
    PUBLISHED; rejection transitions the allocation to REVERTED, returns the application
    from ALLOCATED to QUEUED, returns the housing unit from RESERVED to AVAILABLE".

    The conserved quantity 'count(units in AVAILABLE)' must round-trip across an
    allocate-then-reject sequence on the same unit.

    # difficulty: compensating_invariant/housing_unit_availability_invariant
    """
    program = create_program(notice_period_length=2)
    # Create 5 units, all AVAILABLE.
    for i in range(5):
        validate_success(
            api.create_housing_unit(
                program["id"],
                create_housing_unit_payload(unit_code=f"U-{i}", apartment_type="ONE_BEDROOM",
                                            bedroom_count=1),
                {"X-User-ID": "test-director-1", "X-User-Role": "HousingDirector"},
            ),
            expected_status=201,
        )
    available_before = _count_units_in_status(program["id"], "AVAILABLE")
    assert available_before == 5
    # Queue an applicant and allocate.
    application, applicant_id = create_queued_application(program["id"])
    units, _ = validate_paginated(
        api.list_housing_units(program["id"], OFFICER_HEADERS, params={"limit": 100})
    )
    target_unit = next(u for u in units if u.get("status") == "AVAILABLE")
    allocation = validate_success(
        api.create_allocation(
            program["id"], create_allocation_payload(target_unit["id"]), OFFICER_HEADERS
        ),
        expected_status=201,
    )
    # Compensating action: applicant rejects.
    validate_success(
        api.reject_allocation(program["id"], allocation["id"], make_applicant_headers(applicant_id))
    )
    available_after = _count_units_in_status(program["id"], "AVAILABLE")
    assert available_after == available_before, (
        f"PRD §3.5: rejection returns unit to AVAILABLE; conserved-quantity invariant "
        f"violated (before={available_before}, after={available_after})"
    )


def test_unit_availability_invariant_after_allocate_then_sustain_objection():
    """PRD §3.4: "A sustain transitions the objection from PENDING_REVIEW to SUSTAINED
    and cascades the parent allocation from UNDER_OBJECTION (or PUBLISHED) to REVERTED;
    the cascade returns the application from ALLOCATED to QUEUED, returns the housing
    unit from RESERVED to AVAILABLE".

    The same conserved quantity must hold under the sustained-objection path as well.

    # difficulty: compensating_invariant/housing_unit_availability_invariant
    """
    program = create_program(notice_period_length=10)
    for i in range(3):
        validate_success(
            api.create_housing_unit(
                program["id"],
                create_housing_unit_payload(unit_code=f"V-{i}", apartment_type="ONE_BEDROOM",
                                            bedroom_count=1),
                {"X-User-ID": "test-director-1", "X-User-Role": "HousingDirector"},
            ),
            expected_status=201,
        )
    # Create the published allocation (this creates its own additional unit and reserves
    # it). Capture the AVAILABLE count AFTER the allocation has reserved its unit, then
    # assert that sustain restores that conserved count by +1 (the unit goes back to
    # AVAILABLE per PRD §3.4).
    allocation, application, unit, _ = create_published_allocation(program["id"])
    available_after_allocate = _count_units_in_status(program["id"], "AVAILABLE")
    # File and sustain an objection.
    from test_helpers import (
        CITIZEN_HEADERS,
        create_objection_payload,
    )

    objection = validate_success(
        api.create_objection(
            program["id"], allocation["id"], create_objection_payload(), CITIZEN_HEADERS
        ),
        expected_status=201,
    )
    validate_success(
        api.sustain_objection(program["id"], allocation["id"], objection["id"], OFFICER_HEADERS)
    )
    available_after_sustain = _count_units_in_status(program["id"], "AVAILABLE")
    assert available_after_sustain == available_after_allocate + 1, (
        f"PRD §3.4: sustain returns unit from RESERVED to AVAILABLE; conserved-quantity "
        f"invariant violated (after_allocate={available_after_allocate}, "
        f"after_sustain={available_after_sustain})"
    )


# ──────────────────────────────────────────────────────────
# Difficulty: compensating_invariant/applicant_active_application_count_invariant
# ──────────────────────────────────────────────────────────


def test_active_application_count_zero_after_exit_then_reapply_succeeds():
    """PRD §3.7: "The application's EXITED and REJECTED states are terminal — they
    release the per-program-per-applicant uniqueness slot, allowing the same X-User-ID
    to apply again under a fresh application if circumstances change."

    The conserved quantity 'active applications per (program, applicant_user_id)'
    drains to 0 after EXITED, then the same X-User-ID can submit a fresh application.

    # difficulty: compensating_invariant/applicant_active_application_count_invariant
    """
    program = create_program(notice_period_length=1, grace_period_length=1)
    application, contract, _review, applicant_id = setup_application_in_exit_pending(
        program["id"], notice_period_length=1
    )
    # Drive grace -> EXITED.
    advance_clock_by(program["id"], program["grace_period_length"] + 1)
    application_after = validate_success(
        api.get_application(program["id"], application["id"], OFFICER_HEADERS)
    )
    assert application_after["status"] == "EXITED"
    # Now reuse applicant_id.
    res = api.create_application(
        program["id"], create_application_payload(), make_applicant_headers(applicant_id)
    )
    new_app = validate_success(res, expected_status=201)
    assert new_app["applicant_user_id"] == applicant_id
    assert new_app["status"] == "DRAFT"


def test_active_application_count_zero_after_rejected_then_reapply_succeeds():
    """PRD §3.7: "The application's EXITED and REJECTED states are terminal — they
    release the per-program-per-applicant uniqueness slot, allowing the same X-User-ID
    to apply again under a fresh application if circumstances change".

    Second instance: REJECTED branch.

    # difficulty: compensating_invariant/applicant_active_application_count_invariant
    """
    program = create_program(per_capita_income_threshold_cents=10)  # near-zero so anyone fails
    applicant_id = fresh_applicant_id("reject-loop")
    headers = make_applicant_headers(applicant_id)
    # Submit and force a REJECTED outcome.
    application = validate_success(
        api.create_application(program["id"], create_application_payload(), headers),
        expected_status=201,
    )
    from test_helpers import emit_full_passing_sync_events

    emit_full_passing_sync_events(
        program["id"], application,
        monthly_income_cents=200_000, total_assets_cents=0
    )
    validate_success(api.submit_application(program["id"], application["id"], headers))
    res = api.cross_check_application(program["id"], application["id"], OFFICER_HEADERS)
    # The income greatly exceeds threshold 10 -> ERR_INCOME_OVER_THRESHOLD.
    validate_error(res, "ERR_INCOME_OVER_THRESHOLD")
    application_after = validate_success(
        api.get_application(program["id"], application["id"], OFFICER_HEADERS)
    )
    assert application_after["status"] == "REJECTED"
    # Same X-User-ID can now create a new application.
    new_app = validate_success(
        api.create_application(program["id"], create_application_payload(), headers),
        expected_status=201,
    )
    assert new_app["status"] == "DRAFT"


# ──────────────────────────────────────────────────────────
# Optimistic concurrency (PRD §2.4)
# ──────────────────────────────────────────────────────────


def test_version_mismatch_when_stale_version_supplied():
    """PRD §2.4: "When the client includes version, the server compares it to the
    current entity's version and rejects the request with ERR_VERSION_MISMATCH at HTTP
    409 if the two do not match, leaving the entity unchanged".
    """
    program = create_program()
    applicant_id = fresh_applicant_id()
    headers = make_applicant_headers(applicant_id)
    application = validate_success(
        api.create_application(program["id"], create_application_payload(), headers),
        expected_status=201,
    )
    stale_version = application["version"]
    # Submit (mutates).
    submitted = validate_success(api.submit_application(program["id"], application["id"], headers))
    assert submitted["version"] >= stale_version + 1
    # Now retry submit with the stale version supplied — but we are also in the wrong
    # state, so we instead trigger the version check via a re-submission attempt that
    # would have succeeded if version matched.
    res = api.submit_application(
        program["id"], application["id"], headers, payload={"version": stale_version}
    )
    # The state error and version error are both candidate failures; PRD §2.9 places
    # version (priority 4) ABOVE state (priority 5–8). So the version mismatch must win
    # when version is provided and stale.
    validate_error(res, "ERR_VERSION_MISMATCH")


# ──────────────────────────────────────────────────────────
# Sync event log (PRD §2.6, §2.4 append-only)
# ──────────────────────────────────────────────────────────


def test_sync_event_listing_returns_immutable_records_without_updated_at():
    """PRD §2.4: "the SyncEvent log: because sync events are an immutable append-only
    journal, a SyncEvent carries only id and created_at — both updated_at and version
    are absent".
    """
    program = create_program()
    # Emit a TAX_INCOME_ASSETS event referencing a placeholder application id; the log
    # is append-only and validates only the envelope, not the subject's existence.
    from test_helpers import (
        INTEGRATION_HEADERS,
        create_sync_event_payload,
        tax_income_assets_payload,
    )

    sub_id = NON_EXISTENT_UUID  # log accepts any subject_id; PRD says append-only.
    try:
        validate_success(
            api.emit_sync_event(
                program["id"],
                create_sync_event_payload(
                    "TAX_INCOME_ASSETS", "APPLICATION", sub_id,
                    tax_income_assets_payload(100_000, 100_000),
                ),
                INTEGRATION_HEADERS,
            ),
            expected_status=201,
        )
    except AssertionError:
        # If the implementation requires an existing subject, fall back: emit against a
        # real application id by creating one first.
        applicant_id = fresh_applicant_id()
        application = validate_success(
            api.create_application(
                program["id"], create_application_payload(),
                make_applicant_headers(applicant_id),
            ),
            expected_status=201,
        )
        validate_success(
            api.emit_sync_event(
                program["id"],
                create_sync_event_payload(
                    "TAX_INCOME_ASSETS", "APPLICATION", application["id"],
                    tax_income_assets_payload(100_000, 100_000),
                ),
                INTEGRATION_HEADERS,
            ),
            expected_status=201,
        )
    events, meta = validate_paginated(api.list_sync_events(program["id"], OFFICER_HEADERS))
    assert len(events) >= 1
    for ev in events:
        assert "updated_at" not in ev, (
            "PRD §2.4: SyncEvent is append-only and must not carry updated_at"
        )
        assert "version" not in ev, (
            "PRD §2.4: SyncEvent is append-only and must not carry version"
        )
        assert "id" in ev and "created_at" in ev


# ──────────────────────────────────────────────────────────
# Path resolution / NOT_FOUND family (PRD §2.8)
# ──────────────────────────────────────────────────────────


def test_path_resolution_program_not_found_first():
    """PRD §2.8: "the program is resolved first, and if it does not exist the request
    is rejected with ERR_PROGRAM_NOT_FOUND".
    """
    res = api.get_application(
        NON_EXISTENT_UUID, NON_EXISTENT_UUID, OFFICER_HEADERS
    )
    validate_error(res, "ERR_PROGRAM_NOT_FOUND")


def test_path_resolution_application_not_found_second():
    """PRD §2.8: ERR_APPLICATION_NOT_FOUND is returned for the missing app segment when
    the program resolves successfully.
    """
    program = create_program()
    res = api.get_application(program["id"], NON_EXISTENT_UUID, OFFICER_HEADERS)
    validate_error(res, "ERR_APPLICATION_NOT_FOUND")
