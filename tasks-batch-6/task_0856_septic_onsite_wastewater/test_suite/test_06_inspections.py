"""Field visits: the contractor calendar, sequencing, the licence gate and four eyes."""

from test_helpers import (
    ApiErrorId,
    assert_inspection,
    refresh_construction_permit,
    refresh_contractor,
    refresh_inspection,
    refresh_system_design,
    schedule_inspection,
    setup_permitted_parcel,
    unique_apn,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_cover_pass_is_refused_while_the_installer_licence_is_suspended(
    api, applicant_headers, ehs_field_headers, health_officer_headers
):
    """PRD §3.6: "**Licence:** the permit's contractor must have an `effective_status`
    of `ACTIVE`, else `ERR_CONTRACTOR_NOT_ACTIVE` — a firm suspended, revoked or simply
    lapsed since the permit was issued cannot have its work signed off."
    PRD §3.5: "Suspension moves `ACTIVE → SUSPENDED`; reinstatement moves `SUSPENDED →
    ACTIVE`; revocation moves either `ACTIVE → REVOKED` or `SUSPENDED → REVOKED` and is
    terminal."

    Design: Difficulty/cross_entity_state_dependency/cover_inspection_pass_gated_on_contractor_effective_status_active
    """
    ctx = setup_permitted_parcel(
        api,
        applicant_headers=applicant_headers,
        apn=unique_apn("0856-CE1"),
        site_address="14 Licence Loop",
    )
    inspection = schedule_inspection(api, ctx["construction_permit_id"])
    validate_success(
        api.set_license_status(ctx["contractor_id"], {"action": "SUSPEND"}, health_officer_headers),
        200,
    )
    assert refresh_contractor(api, ctx["contractor_id"])["effective_status"] == "SUSPENDED"

    refused = api.record_inspection_result(inspection["id"], {"result": "PASS"}, ehs_field_headers)
    validate_error(refused, ApiErrorId.ERR_CONTRACTOR_NOT_ACTIVE.value, 409)

    assert refresh_inspection(api, inspection["id"])["status"] == "SCHEDULED"
    assert (
        refresh_construction_permit(api, ctx["construction_permit_id"])["status"]
        == "UNDER_CONSTRUCTION"
    )


def test_reinstating_the_licence_lets_the_identical_cover_pass_succeed(
    api, applicant_headers, ehs_field_headers, health_officer_headers
):
    """PRD §3.6: "A pass moves the visit `SCHEDULED → PASSED`, which is terminal, and
    stamps `result_recorded_at` with the logical clock. A `COVER` pass additionally
    moves its permit `UNDER_CONSTRUCTION → COVER_PASSED` and stamps the permit's
    `cover_inspection_passed_at` with the same logical-clock instant."
    PRD §3.5: "Only a firm that is administratively active and not yet lapsed has an
    `effective_status` of `ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/cover_inspection_pass_gated_on_contractor_effective_status_active
    """
    ctx = setup_permitted_parcel(
        api,
        applicant_headers=applicant_headers,
        apn=unique_apn("0856-CE1B"),
        site_address="14 Licence Loop",
    )
    inspection = schedule_inspection(api, ctx["construction_permit_id"])
    validate_success(
        api.set_license_status(ctx["contractor_id"], {"action": "SUSPEND"}, health_officer_headers),
        200,
    )
    validate_error(
        api.record_inspection_result(inspection["id"], {"result": "PASS"}, ehs_field_headers),
        ApiErrorId.ERR_CONTRACTOR_NOT_ACTIVE.value,
        409,
    )

    reinstated = validate_success(
        api.set_license_status(
            ctx["contractor_id"], {"action": "REINSTATE"}, health_officer_headers
        ),
        200,
    )
    assert reinstated["status"] == "ACTIVE"
    assert reinstated["effective_status"] == "ACTIVE"

    passed = validate_success(
        api.record_inspection_result(inspection["id"], {"result": "PASS"}, ehs_field_headers), 200
    )
    assert passed["status"] == "PASSED"

    permit = refresh_construction_permit(api, ctx["construction_permit_id"])
    assert permit["status"] == "COVER_PASSED"
    assert permit["cover_inspection_passed_at"] == "2026-05-01T00:00:00.000Z"


def test_visit_one_minute_inside_the_travel_buffer_is_refused(api, applicant_headers, ehs_field_headers):
    """PRD §3.6: "A proposed window collides with an existing one when the proposed
    start falls strictly before the existing end plus 45 minutes *and* the existing
    start falls strictly before the proposed end plus 45 minutes. Any collision is
    refused with `ERR_CONTRACTOR_SCHEDULE_CONFLICT`."
    PRD §3.6: "The strictness matters: a new visit beginning exactly 45 minutes after
    an existing visit ends does *not* conflict, while one beginning a single minute
    earlier does."

    Design: Difficulty/resource_temporal_overlap/contractor_calendar_half_open_window_with_trailing_travel_buffer
    """
    ctx = setup_permitted_parcel(
        api,
        applicant_headers=applicant_headers,
        apn=unique_apn("0856-TO1"),
        site_address="16 Calendar Close",
    )
    schedule_inspection(
        api,
        ctx["construction_permit_id"],
        inspection_type="COMPLAINT",
        scheduled_start="2026-06-01T09:00:00Z",
        scheduled_end="2026-06-01T10:00:00Z",
    )

    refused = api.create_inspection(
        {
            "construction_permit_id": ctx["construction_permit_id"],
            "inspection_type": "COMPLAINT",
            "scheduled_start": "2026-06-01T10:44:00Z",
            "scheduled_end": "2026-06-01T11:44:00Z",
        },
        ehs_field_headers,
    )
    validate_error(refused, ApiErrorId.ERR_CONTRACTOR_SCHEDULE_CONFLICT.value, 409)


def test_visit_starting_exactly_at_the_buffered_boundary_is_accepted(api, applicant_headers, ehs_field_headers):
    """PRD §3.6: "The strictness matters: a new visit beginning exactly 45 minutes after
    an existing visit ends does *not* conflict, while one beginning a single minute
    earlier does."
    PRD §3.6: "The register snapshots the permit's `contractor_id` onto the inspection,
    because the firm must be on site, and stamps `inspector_user_id` from the acting
    `X-User-ID`."

    Design: Difficulty/resource_temporal_overlap/contractor_calendar_half_open_window_with_trailing_travel_buffer
    """
    ctx = setup_permitted_parcel(
        api,
        applicant_headers=applicant_headers,
        apn=unique_apn("0856-TO1B"),
        site_address="16 Calendar Close",
    )
    schedule_inspection(
        api,
        ctx["construction_permit_id"],
        inspection_type="COMPLAINT",
        scheduled_start="2026-06-01T09:00:00Z",
        scheduled_end="2026-06-01T10:00:00Z",
    )

    accepted = validate_success(
        api.create_inspection(
            {
                "construction_permit_id": ctx["construction_permit_id"],
                "inspection_type": "COMPLAINT",
                "scheduled_start": "2026-06-01T10:45:00Z",
                "scheduled_end": "2026-06-01T11:45:00Z",
            },
            ehs_field_headers,
        ),
        201,
    )
    assert_inspection(accepted)
    assert accepted["status"] == "SCHEDULED"
    assert accepted["scheduled_start"] == "2026-06-01T10:45:00.000Z"
    assert accepted["contractor_id"] == ctx["contractor_id"]

    _, meta = validate_paginated(
        api.list_inspections(
            ehs_field_headers,
            params={"construction_permit_id": ctx["construction_permit_id"]},
        )
    )
    assert meta["total_count"] == 2


def test_failed_visit_rebooks_into_a_fresh_window(api, applicant_headers, ehs_field_headers):
    """PRD §3.6: "A failure moves the visit `SCHEDULED → FAILED`, stamps
    `result_recorded_at`, stores the supplied `deficiency_codes`, and leaves the parent
    permit's status exactly where it was."
    PRD §3.6: "Failure is not terminal: the specialist re-books the visit into a fresh
    window by supplying a new `scheduled_start` and `scheduled_end`, which moves it
    `FAILED → SCHEDULED`, increments `reinspection_round` by 1 and clears both
    `result_recorded_at` and `deficiency_codes`."

    Design: Corner/state_machines/corner_failed_inspection_rescheduled_increments_reinspection_round_and_clears_deficiencies
    """
    ctx = setup_permitted_parcel(
        api,
        applicant_headers=applicant_headers,
        apn=unique_apn("0856-S8"),
        site_address="39 Reinspect Ridge",
    )
    inspection = schedule_inspection(api, ctx["construction_permit_id"])

    failed = validate_success(
        api.record_inspection_result(
            inspection["id"],
            {"result": "FAIL", "deficiency_codes": ["D-TANK-SEAL", "D-BEDDING"]},
            ehs_field_headers,
        ),
        200,
    )
    assert failed["status"] == "FAILED"
    assert failed["deficiency_codes"] == ["D-TANK-SEAL", "D-BEDDING"]
    assert (
        refresh_construction_permit(api, ctx["construction_permit_id"])["status"]
        == "UNDER_CONSTRUCTION"
    )

    rebooked = validate_success(
        api.reschedule_inspection(
            inspection["id"],
            {
                "scheduled_start": "2026-05-08T09:00:00Z",
                "scheduled_end": "2026-05-08T10:00:00Z",
            },
            ehs_field_headers,
        ),
        200,
    )
    assert rebooked["status"] == "SCHEDULED"
    assert rebooked["reinspection_round"] == 1
    assert rebooked["deficiency_codes"] == []
    assert rebooked["result_recorded_at"] is None
    assert rebooked["scheduled_start"] == "2026-05-08T09:00:00.000Z"


def test_final_verdict_before_the_cover_pass_is_out_of_sequence(api, applicant_headers, ehs_field_headers):
    """PRD §3.6: "**Sequencing:** a `COVER` verdict may only be recorded while its permit
    is `UNDER_CONSTRUCTION`, and a `FINAL` verdict only while its permit is
    `COVER_PASSED`; recording out of sequence is `ERR_INSPECTION_SEQUENCE`."
    PRD §3.6: "A `FINAL` pass moves its permit `COVER_PASSED → COMPLETED`, which is
    terminal for the permit and is the state that makes it eligible for an operating
    permit."

    Design: Corner/state_machines/corner_final_inspection_result_before_cover_pass_returns_inspection_sequence
    """
    ctx = setup_permitted_parcel(
        api,
        applicant_headers=applicant_headers,
        apn=unique_apn("0856-S9"),
        site_address="40 Sequence Square",
    )
    final_visit = schedule_inspection(
        api, ctx["construction_permit_id"], inspection_type="FINAL"
    )

    refused = api.record_inspection_result(final_visit["id"], {"result": "PASS"}, ehs_field_headers)
    validate_error(refused, ApiErrorId.ERR_INSPECTION_SEQUENCE.value, 409)

    assert refresh_inspection(api, final_visit["id"])["status"] == "SCHEDULED"
    permit = refresh_construction_permit(api, ctx["construction_permit_id"])
    assert permit["status"] == "UNDER_CONSTRUCTION"
    assert permit["cover_inspection_passed_at"] is None


def test_booking_outside_the_construction_window_is_refused(api, applicant_headers, ehs_field_headers):
    """PRD §3.6: "Booking is barred unless the logical clock currently lies inside the
    permit's closed construction window, at or after `valid_from` and at or before
    `valid_until`; outside it the request is refused with `ERR_PERMIT_NOT_IN_WINDOW`."
    PRD §3.6: "Scheduling the *first* inspection on a permit also moves that permit
    `ISSUED → UNDER_CONSTRUCTION`; subsequent bookings leave the permit's status alone."

    Design: Corner/validations/corner_inspection_scheduled_outside_permit_window_returns_permit_not_in_window
    """
    ctx = setup_permitted_parcel(
        api,
        applicant_headers=applicant_headers,
        apn=unique_apn("0856-V6"),
        site_address="59 Early Entry",
        permit_valid_from="2026-06-01T00:00:00Z",
        permit_valid_until="2026-12-01T00:00:00Z",
    )

    refused = api.create_inspection(
        {
            "construction_permit_id": ctx["construction_permit_id"],
            "inspection_type": "COVER",
            "scheduled_start": "2026-06-10T09:00:00Z",
            "scheduled_end": "2026-06-10T10:00:00Z",
        },
        ehs_field_headers,
    )
    validate_error(refused, ApiErrorId.ERR_PERMIT_NOT_IN_WINDOW.value, 409)

    assert refresh_construction_permit(api, ctx["construction_permit_id"])["status"] == "ISSUED"
    _, meta = validate_paginated(
        api.list_inspections(
            ehs_field_headers,
            params={"construction_permit_id": ctx["construction_permit_id"]},
        )
    )
    assert meta["total_count"] == 0


def test_design_approver_may_not_sign_off_the_cover_inspection(
    api, applicant_headers, ehs_reviewer_headers, ehs_field_headers
):
    """PRD §3.6: "**Segregation of duties:** for a `COVER` verdict only, the `X-User-ID`
    recording the pass must differ from the `review_ehs_user_id` stored on the permit's
    system design when that design was approved."
    PRD §3.6: "a match is refused with `ERR_SEGREGATION_OF_DUTIES`. The rule binds
    `COVER` verdicts alone: a `FINAL` or `COMPLAINT` verdict may be recorded by the
    approving specialist."

    Design: Corner/validations/corner_segregation_of_duties_blocks_design_approver_from_passing_cover_inspection
    """
    ctx = setup_permitted_parcel(
        api,
        applicant_headers=applicant_headers,
        apn=unique_apn("0856-V8"),
        site_address="61 Four Eyes Field",
        reviewer_headers=ehs_reviewer_headers,
    )
    assert refresh_system_design(api, ctx["system_design_id"])["review_ehs_user_id"] == "u-ehs-review"

    inspection = schedule_inspection(
        api, ctx["construction_permit_id"], inspector_headers=ehs_reviewer_headers
    )

    refused = api.record_inspection_result(
        inspection["id"], {"result": "PASS"}, ehs_reviewer_headers
    )
    validate_error(refused, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)
    assert refresh_inspection(api, inspection["id"])["status"] == "SCHEDULED"

    passed = validate_success(
        api.record_inspection_result(inspection["id"], {"result": "PASS"}, ehs_field_headers), 200
    )
    assert passed["status"] == "PASSED"
    assert (
        refresh_construction_permit(api, ctx["construction_permit_id"])["status"] == "COVER_PASSED"
    )
