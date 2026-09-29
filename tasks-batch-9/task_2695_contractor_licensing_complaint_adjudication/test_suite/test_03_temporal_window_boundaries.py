"""Three interval conventions that must not be confused with one another.

Coverage periods are half-open, designation windows are closed at both ends, and
a hearing block is half-open in timestamps. Each convention is exercised at the
exact boundary instant where the two readings disagree.
"""

from test_helpers import (
    BOARD_ADMIN_HEADERS,
    HEARING_OFFICER_USER_ID,
    LICENSING_ANALYST_HEADERS,
    ApiErrorId,
    AssignmentStatus,
    CitationStatus,
    CompliancePosture,
    CoverageStatus,
    CoverageType,
    HearingStatus,
    RelationshipType,
    assert_fields,
    assert_posture,
    assert_qualification_count,
    assert_qualifier_assignment,
    constants as K,
    factories as F,
    fixtures as FX,
    get_success_data,
    validate_error,
    validate_success,
)

INCUMBENT_PERIOD = {"effective_date": "2026-08-01", "expiration_date": "2027-08-01"}


def _licence_with_incumbent_bond(api):
    """A licence whose only verified bond runs the whole first term."""
    FX.set_clock(api, K.DEFAULT_CLOCK_UTC)
    ctx = FX.mint_active_license(api)
    incumbent = FX.file_coverage(
        api,
        ctx.license_id,
        coverage_type=CoverageType.BOND,
        carrier_name="Surety One",
        policy_number="BND-A",
        amount_cents=K.C10["required_bond_amount_cents"],
        **INCUMBENT_PERIOD,
    )
    FX.verify_coverage(api, incumbent["id"])
    return ctx, incumbent


def test_01_a_successor_bond_starting_on_the_incumbent_expiry_verifies(api):
    """Half-open periods that merely meet at a boundary do not overlap.

    PRD: "First, a record beginning exactly on another's `expiration_date` does
    not overlap it, so such a pair may both be `VERIFIED`. Second, two half-open
    periods that meet at a boundary are *adjacent* and leave no uncovered day
    between them."

    Design: Difficulty/resource_temporal_overlap/bond_coverage_intervals_are_half_open_so_adjacent_periods_stack
    """
    ctx, incumbent = _licence_with_incumbent_bond(api)

    successor = FX.file_coverage(
        api,
        ctx.license_id,
        coverage_type=CoverageType.BOND,
        carrier_name="Surety One",
        policy_number="BND-B",
        amount_cents=K.C10["required_bond_amount_cents"],
        effective_date="2027-08-01",
        expiration_date="2028-08-01",
    )
    verified = FX.verify_coverage(api, successor["id"])

    assert_fields(
        verified,
        {
            "status": CoverageStatus.VERIFIED,
            "verified_on": "2026-08-01",
            "effective_date": "2027-08-01",
        },
    )
    assert_fields(
        validate_success(
            api.get_coverage_record(incumbent["id"], LICENSING_ANALYST_HEADERS)
        ),
        {"status": CoverageStatus.VERIFIED},
    )


def test_02_a_successor_bond_starting_one_day_early_is_refused(api):
    """A single day of genuine overlap is a conflict on the same coverage type.

    PRD: "Because the periods are half-open, a record starting exactly on
    another's `expiration_date` does *not* overlap and may be verified; a genuine
    overlap draws `ERR_COVERAGE_PERIOD_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/bond_coverage_intervals_are_half_open_so_adjacent_periods_stack
    """
    ctx, _incumbent = _licence_with_incumbent_bond(api)
    overlapping = FX.file_coverage(
        api,
        ctx.license_id,
        coverage_type=CoverageType.BOND,
        carrier_name="Surety Two",
        policy_number="BND-C",
        amount_cents=K.C10["required_bond_amount_cents"],
        effective_date="2027-07-31",
        expiration_date="2028-01-01",
    )

    validate_error(
        api.verify_coverage_record(
            overlapping["id"],
            F.verification_payload("VERIFY"),
            LICENSING_ANALYST_HEADERS,
        ),
        ApiErrorId.COVERAGE_PERIOD_OVERLAP,
    )

    assert_fields(
        validate_success(
            api.get_coverage_record(overlapping["id"], LICENSING_ANALYST_HEADERS)
        ),
        {"status": CoverageStatus.PENDING_VERIFICATION, "verified_on": None},
    )


def test_03_the_non_overlap_test_is_scoped_to_one_coverage_type(api):
    """A liability policy sharing the bond's exact dates is not an overlap at all.

    PRD: "First, **non-overlap**: no other coverage record on the same licence
    with the same `coverage_type` and `status` of `VERIFIED` may overlap the
    candidate's half-open `[effective_date, expiration_date)` period."

    Design: Difficulty/resource_temporal_overlap/bond_coverage_intervals_are_half_open_so_adjacent_periods_stack
    """
    ctx, _incumbent = _licence_with_incumbent_bond(api)

    liability = FX.file_coverage(
        api,
        ctx.license_id,
        coverage_type=CoverageType.GENERAL_LIABILITY,
        carrier_name="Casualty Mutual",
        policy_number="GL-A",
        amount_cents=1000000,
        **INCUMBENT_PERIOD,
    )
    verified = FX.verify_coverage(api, liability["id"])

    assert_fields(verified, {"status": CoverageStatus.VERIFIED})
    assert_posture(FX.read_license(api, ctx.license_id), CompliancePosture.COMPLIANT)


def _shared_qualifier_at_capacity(api):
    """One person holding two designations whose closed windows end 2026-12-31."""
    FX.set_clock(api, K.DEFAULT_CLOCK_UTC)
    classification = FX.create_c10_classification(api)
    anchored = [
        FX.mint_active_license(
            api,
            classification,
            legal_name=name,
            contact_email=email,
            full_name=qualifier,
        )
        for name, email, qualifier in (
            ("Cap A Electric LLC", "capa@x.test", "Ada Anchor"),
            ("Cap B Electric LLC", "capb@x.test", "Ben Anchor"),
            ("Cap C Electric LLC", "capc@x.test", "Cid Anchor"),
        )
    ]
    shared = FX.register_qualifying_individual(
        api, full_name="Shirl Shared", verified_experience_months=60
    )
    for ctx in anchored[:2]:
        current = FX.read_license(api, ctx.license_id)
        get_success_data(
            FX.designate_qualifier(
                api,
                ctx.license_id,
                shared["id"],
                current["version"],
                effective_from="2026-08-01",
                effective_to="2026-12-31",
            )
        )
    return anchored[2], shared


def test_04_a_designation_window_still_occupies_its_own_end_date(api):
    """A third designation beginning on the incumbent end date exceeds the cap.

    PRD: "A **designation window** on a qualifier assignment is closed at both
    ends: `[effective_from, effective_to]`. The designation occupies the qualifier
    on `effective_from` and on `effective_to` itself."

    Design: Difficulty/resource_temporal_overlap/qualifier_designation_windows_are_closed_so_the_end_date_is_still_occupied
    """
    ctx_c, shared = _shared_qualifier_at_capacity(api)
    licence_c = FX.read_license(api, ctx_c.license_id)

    validate_error(
        FX.designate_qualifier(
            api,
            ctx_c.license_id,
            shared["id"],
            licence_c["version"],
            effective_from="2026-12-31",
        ),
        ApiErrorId.QUALIFIER_CAPACITY_EXCEEDED,
    )

    assert_qualification_count(
        validate_success(
            api.get_qualifying_individual(shared["id"], LICENSING_ANALYST_HEADERS)
        ),
        2,
    )


def test_05_the_day_after_a_closed_window_ends_is_free_again(api):
    """Beginning one day later clears the cap and the count reaches three.

    PRD: "Then the **concurrent-qualification cap**: a single person may hold at
    most two live designations covering any given date, so the system counts the
    designations already held by the offered person whose `status` is `ACTIVE` and
    whose window — from `effective_from` through `effective_to` inclusive, or
    open-ended when `effective_to` is null — contains the new designation's
    `effective_from`."

    Design: Difficulty/resource_temporal_overlap/qualifier_designation_windows_are_closed_so_the_end_date_is_still_occupied
    """
    ctx_c, shared = _shared_qualifier_at_capacity(api)
    licence_c = FX.read_license(api, ctx_c.license_id)

    assignment = get_success_data(
        FX.designate_qualifier(
            api,
            ctx_c.license_id,
            shared["id"],
            licence_c["version"],
            effective_from="2027-01-01",
        )
    )

    assert_qualifier_assignment(
        assignment,
        status=AssignmentStatus.ACTIVE,
        effective_from="2027-01-01",
        effective_to=None,
        relationship_type=RelationshipType.RESPONSIBLE_MANAGING_EMPLOYEE,
    )
    assert_qualification_count(
        validate_success(
            api.get_qualifying_individual(shared["id"], LICENSING_ANALYST_HEADERS)
        ),
        3,
    )
    assert_qualification_count(
        validate_success(
            api.get_qualifying_individual(
                ctx_c.individual_id, LICENSING_ANALYST_HEADERS
            )
        ),
        0,
    )
    assert_fields(
        FX.read_license(api, ctx_c.license_id),
        {"qualifying_individual_id": shared["id"]},
    )


def _two_appealed_citations_with_one_booked_slot(api):
    """One officer already sitting 14:00-16:00, and a second appeal awaiting a slot."""
    FX.set_clock(api, K.DEFAULT_CLOCK_UTC)
    classification = FX.create_c20_classification(api)
    ctx_one = FX.mint_active_license(
        api,
        classification,
        legal_name="Slot One HVAC LLC",
        contact_email="one@slot.test",
        full_name="Sam One",
    )
    ctx_two = FX.mint_active_license(
        api,
        classification,
        legal_name="Slot Two HVAC LLC",
        contact_email="two@slot.test",
        full_name="Sam Two",
    )
    consumer_one = FX.register_consumer(
        api, full_name="Cara One", contact_email="cara@slot.test"
    )
    consumer_two = FX.register_consumer(
        api, full_name="Cody Two", contact_email="cody@slot.test"
    )
    FX.set_clock(api, "2026-09-01T00:00:00Z")
    _c1, _i1, citation_one = FX.substantiated_citation(
        api, ctx_one, consumer_one["id"], correction_due_date="2026-10-15"
    )
    _c2, _i2, citation_two = FX.substantiated_citation(
        api, ctx_two, consumer_two["id"], correction_due_date="2026-10-15"
    )
    FX.appeal_citation(api, citation_one["id"], ctx_one.licensee_id)
    FX.appeal_citation(api, citation_two["id"], ctx_two.licensee_id)
    booked = FX.calendar_hearing(
        api,
        citation_one["id"],
        "2026-09-10T14:00:00Z",
        "2026-09-10T16:00:00Z",
    )
    return citation_two, booked


def test_06_a_slot_starting_inside_a_booked_block_is_refused(api):
    """The officer's calendar rejects a hearing that straddles the sitting one.

    PRD: "Then the calendar check: no other hearing in `SCHEDULED` status for the
    same presiding officer may overlap the half-open block, though a hearing
    beginning at the exact instant another ends is fine; a genuine overlap draws
    `ERR_HEARING_SLOT_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/hearing_officer_calendar_rejects_a_straddling_slot_but_accepts_a_touching_one
    """
    citation_two, _booked = _two_appealed_citations_with_one_booked_slot(api)

    validate_error(
        api.create_hearing(
            F.hearing_payload(
                citation_two["id"],
                HEARING_OFFICER_USER_ID,
                "2026-09-10T15:30:00Z",
                "2026-09-10T17:00:00Z",
            ),
            BOARD_ADMIN_HEADERS,
        ),
        ApiErrorId.HEARING_SLOT_CONFLICT,
    )

    assert_fields(
        validate_success(
            api.get_citation(citation_two["id"], LICENSING_ANALYST_HEADERS)
        ),
        {"status": CitationStatus.APPEAL_REQUESTED},
    )


def test_07_a_slot_beginning_the_instant_another_ends_is_accepted(api):
    """A touching block is free, and calendaring advances the citation.

    PRD: "A **hearing block** is half-open: `[scheduled_start_utc,
    scheduled_end_utc)`. A hearing beginning at the exact instant another ends does
    not conflict with it."

    Design: Difficulty/resource_temporal_overlap/hearing_officer_calendar_rejects_a_straddling_slot_but_accepts_a_touching_one
    """
    citation_two, booked = _two_appealed_citations_with_one_booked_slot(api)

    touching = FX.calendar_hearing(
        api,
        citation_two["id"],
        "2026-09-10T16:00:00Z",
        "2026-09-10T17:00:00Z",
    )

    assert_fields(
        touching,
        {
            "status": HearingStatus.SCHEDULED,
            "scheduled_start_utc": "2026-09-10T16:00:00Z",
            "presiding_officer_user_id": HEARING_OFFICER_USER_ID,
        },
    )
    assert_fields(
        validate_success(api.get_hearing(booked["id"], LICENSING_ANALYST_HEADERS)),
        {"status": HearingStatus.SCHEDULED},
    )
    assert_fields(
        validate_success(
            api.get_citation(citation_two["id"], LICENSING_ANALYST_HEADERS)
        ),
        {"status": CitationStatus.HEARING_SCHEDULED},
    )
