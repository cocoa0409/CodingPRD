"""Running the visit, recording the assessment, and the completion cascade."""

import pytest

from test_helpers import (
    ApiErrorId,
    assert_assessment,
    bootstrap_registry,
    file_complaint,
    make_inspector_headers,
    make_supervisor_headers,
    record_assessment,
    schedule_visit,
    set_clock,
    setup_certification_expiring_officer,
    setup_in_progress_visit,
    setup_repeat_offender_parcel,
    setup_triaged_complaint,
    start_visit,
    TEST_USERS,
    triage,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["program_admin_headers"]
CLERK = TEST_USERS["intake_clerk_headers"]

SEVERE_SCORES = {
    "harborage_score": 8, "attractant_score": 7,
    "sanitation_score": 6, "burrow_count": 4,
}


def test_starting_an_already_started_visit_is_rejected(api):
    """PRD §3.3: "The visit must be in `SCHEDULED` — a second start attempt, or a
    start on a completed visit, is `ERR_INVALID_STATE` — and the officer's
    `certification_expires_at` must be strictly later than the current logical
    clock, failing which the start is refused with `ERR_CERTIFICATION_EXPIRED`."
    PRD §3.3: "A successful start stamps `started_at` with the current logical
    clock and moves the visit `SCHEDULED → IN_PROGRESS`."

    Design: Corner/state_machines/corner_start_inspection_twice_rejected
    """
    env, _complaint, visit = setup_in_progress_visit(bootstrap_kwargs={"inspectors": 1})
    set_clock("2026-05-05T09:20:00Z")

    resp = api.start_inspection(visit["id"], make_inspector_headers(env["insp1_id"]))
    assert resp.status_code == 409
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    after = validate_success(
        api.get_inspection(visit["id"], make_supervisor_headers(env["sup_id"]))
    )
    assert after["status"] == "IN_PROGRESS"
    assert after["started_at"] == "2026-05-05T09:00:00.000Z"


def test_completing_a_visit_that_never_started_is_rejected(api):
    """PRD §3.5: "The assigned officer supplies the `result` and optional
    `notes`; the visit must be `IN_PROGRESS`, else `ERR_INVALID_STATE`, and
    `X-User-ID` must equal the visit's `officer_id`."
    PRD §3.3: "Booking one moves the complaint `TRIAGED → INSPECTION_SCHEDULED`."

    Design: Corner/state_machines/corner_complete_before_start_rejected
    """
    env, complaint = setup_triaged_complaint(bootstrap_kwargs={"inspectors": 1})
    visit = schedule_visit(
        env["sup_id"], "INITIAL", env["insp1_id"],
        "2026-05-05T09:00:00Z", "2026-05-05T10:00:00Z", complaint_id=complaint["id"],
    )

    resp = api.complete_inspection(
        visit["id"], {"result": "NO_VIOLATION"},
        make_inspector_headers(env["insp1_id"]),
    )
    assert resp.status_code == 409
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    after = validate_success(
        api.get_inspection(visit["id"], make_supervisor_headers(env["sup_id"]))
    )
    assert after["status"] == "SCHEDULED"
    assert after["completed_at"] is None
    complaint_after = validate_success(api.get_complaint(complaint["id"], CLERK))
    assert complaint_after["status"] == "INSPECTION_SCHEDULED"


def test_no_access_visit_returns_the_case_to_the_scheduling_queue(api):
    """PRD §3.5: "**`INITIAL` ending `NO_ACCESS`** returns the case to the queue:
    the linked complaint moves `INSPECTION_SCHEDULED → TRIAGED` so that a further
    visit can be booked against it. The zone's `open_complaint_count` is
    unchanged, because the case is still open."
    PRD §3.4: "The parcel's authoritative `chronic_score` is written only when an
    `INITIAL` visit completes with the result `VIOLATION_FOUND`, and it is a
    decayed weighted mean over the parcel's confirmed violation history."

    Design: Corner/state_machines/corner_no_access_visit_returns_complaint_to_triaged
    """
    env, complaint, visit = setup_in_progress_visit(bootstrap_kwargs={"inspectors": 1})
    completed = validate_success(
        api.complete_inspection(
            visit["id"],
            {"result": "NO_ACCESS", "notes": "Locked gate, no responsible party on site"},
            make_inspector_headers(env["insp1_id"]),
        )
    )
    assert completed["status"] == "COMPLETED"
    assert completed["result"] == "NO_ACCESS"

    back_in_queue = validate_success(api.get_complaint(complaint["id"], CLERK))
    assert back_in_queue["status"] == "TRIAGED"

    rebooked = schedule_visit(
        env["sup_id"], "INITIAL", env["insp1_id"],
        "2026-05-06T09:00:00Z", "2026-05-06T10:00:00Z", complaint_id=complaint["id"],
    )
    assert rebooked["status"] == "SCHEDULED"
    rescheduled = validate_success(api.get_complaint(complaint["id"], CLERK))
    assert rescheduled["status"] == "INSPECTION_SCHEDULED"

    zone = validate_success(api.get_zone(env["zone_id"], ADMIN))
    assert zone["open_complaint_count"] == 1
    prop = validate_success(
        api.get_property(env["prop_id"], make_supervisor_headers(env["sup_id"]))
    )
    assert prop["chronic_score"] == pytest.approx(0.00, abs=0.001)


def test_no_violation_completion_closes_the_complaint(api):
    """PRD §3.5: "**`INITIAL` ending `NO_VIOLATION`** closes the case: the linked
    complaint moves `INSPECTION_SCHEDULED → CLOSED_NO_VIOLATION` with
    `closure_reason` `NO_VIOLATION` and `closed_at` stamped, the zone's
    `open_complaint_count` falls by one, and the zone's `rodent_index` and
    `posture` are recomputed. The parcel's `chronic_score` is explicitly *not*
    recomputed, because no violation was confirmed."
    PRD §3.5: "Whichever result is recorded, four things always happen:
    `completed_at` is stamped from the logical clock and the `result` stored, the
    visit moves `IN_PROGRESS → COMPLETED`, the officer's
    `active_assignment_count` falls by one, and the parcel's `last_inspection_at`
    is set to that `completed_at`."

    Design: Corner/state_machines/corner_no_violation_completion_closes_complaint
    """
    env, complaint, visit = setup_in_progress_visit(
        bootstrap_kwargs={"inspectors": 1},
        complaint_type="RODENT_SIGHTING", reported_severity="ROUTINE",
    )
    set_clock("2026-05-05T09:30:00Z")
    validate_success(
        api.complete_inspection(
            visit["id"], {"result": "NO_VIOLATION", "notes": "No evidence of activity"},
            make_inspector_headers(env["insp1_id"]),
        )
    )

    closed = validate_success(api.get_complaint(complaint["id"], CLERK))
    assert closed["status"] == "CLOSED_NO_VIOLATION"
    assert closed["closure_reason"] == "NO_VIOLATION"
    assert closed["closed_at"] == "2026-05-05T09:30:00.000Z"

    zone = validate_success(api.get_zone(env["zone_id"], ADMIN))
    assert zone["open_complaint_count"] == 0
    assert zone["rodent_index"] == pytest.approx(0.00, abs=0.001)

    prop = validate_success(
        api.get_property(env["prop_id"], make_supervisor_headers(env["sup_id"]))
    )
    assert prop["chronic_score"] == pytest.approx(0.00, abs=0.001)
    assert prop["chronic_flag"] is False
    assert prop["last_inspection_at"] == "2026-05-05T09:30:00.000Z"


def test_lapsed_certification_blocks_the_start_of_a_visit(api):
    """PRD §2.8: "An officer may only begin a field visit while their
    `certification_expires_at` instant is strictly later than the current logical
    clock; a clock reading exactly equal to `certification_expires_at`, or later,
    means the pesticide-applicator certification is void and the start is
    rejected with `ERR_CERTIFICATION_EXPIRED` (422)."
    PRD §3.3: "A successful start stamps `started_at` with the current logical
    clock and moves the visit `SCHEDULED → IN_PROGRESS`."

    Design: Corner/validations/corner_expired_certification_blocks_inspection_start
    """
    env = setup_certification_expiring_officer(expires_at="2026-05-05T09:00:00Z")
    resp = api.start_inspection(
        env["visit_id"], make_inspector_headers(env["insp_id"])
    )
    assert resp.status_code == 422
    validate_error(resp, ApiErrorId.ERR_CERTIFICATION_EXPIRED.value)

    after = validate_success(api.get_inspection(env["visit_id"], env["sup_headers"]))
    assert after["status"] == "SCHEDULED"
    assert after["started_at"] is None


def test_second_assessment_and_unevidenced_violation_are_both_refused(api):
    """PRD §3.4: "At most one assessment may exist per visit. A second attempt is
    refused with `ERR_ASSESSMENT_ALREADY_EXISTS`, and an attempt to record one
    against a visit that is not `IN_PROGRESS` is `ERR_INVALID_STATE`."
    PRD §3.5: "A completion claiming `VIOLATION_FOUND` additionally requires that
    exactly one assessment already exists for the visit; without one, the
    completion is refused with `ERR_ASSESSMENT_REQUIRED`."
    PRD §3.4: "The moment an assessment is created, the parcel's
    `provisional_chronic_score` is overwritten with that single assessment's
    `infestation_index`, verbatim: no time decay, no repeat-offence surcharge, no
    history."

    Design: Corner/validations/corner_second_assessment_and_missing_assessment_rejected
    """
    env = bootstrap_registry(inspectors=2, parcels=2)
    first = file_complaint(env["prop1_id"], complaint_type="HARBORAGE",
                           reported_severity="HIGH")
    triage(first["id"], env["sup_id"], "HIGH")
    second = file_complaint(
        env["prop2_id"], complaint_type="HARBORAGE", reported_severity="HIGH",
        description="Woodpile against the fence",
    )
    triage(second["id"], env["sup_id"], "HIGH")
    visit_a = schedule_visit(
        env["sup_id"], "INITIAL", env["insp1_id"],
        "2026-05-05T09:00:00Z", "2026-05-05T10:00:00Z", complaint_id=first["id"],
    )
    visit_b = schedule_visit(
        env["sup_id"], "INITIAL", env["insp2_id"],
        "2026-05-05T09:00:00Z", "2026-05-05T10:00:00Z", complaint_id=second["id"],
    )
    set_clock("2026-05-05T09:00:00Z")
    start_visit(visit_a["id"], env["insp1_id"])
    start_visit(visit_b["id"], env["insp2_id"])
    record_assessment(
        visit_a["id"], env["insp1_id"], harborage_score=4, attractant_score=4,
        sanitation_score=3, burrow_count=0,
    )

    duplicate = api.create_assessment(
        visit_a["id"],
        {"harborage_score": 9, "attractant_score": 9, "sanitation_score": 9,
         "burrow_count": 9},
        make_inspector_headers(env["insp1_id"]),
    )
    assert duplicate.status_code == 409
    validate_error(duplicate, ApiErrorId.ERR_ASSESSMENT_ALREADY_EXISTS.value)

    rows, meta = validate_paginated(
        api.list_assessments(visit_a["id"], make_supervisor_headers(env["sup_id"]))
    )
    assert meta["total_count"] == 1
    assert rows[0]["infestation_index"] == pytest.approx(37.50, abs=0.001)
    prop_one = validate_success(
        api.get_property(env["prop1_id"], make_supervisor_headers(env["sup_id"]))
    )
    assert prop_one["provisional_chronic_score"] == pytest.approx(37.50, abs=0.001)

    unevidenced = api.complete_inspection(
        visit_b["id"], {"result": "VIOLATION_FOUND"},
        make_inspector_headers(env["insp2_id"]),
    )
    assert unevidenced.status_code == 422
    validate_error(unevidenced, ApiErrorId.ERR_ASSESSMENT_REQUIRED.value)

    visit_b_after = validate_success(
        api.get_inspection(visit_b["id"], make_supervisor_headers(env["sup_id"]))
    )
    assert visit_b_after["status"] == "IN_PROGRESS"
    assert visit_b_after["result"] is None


def test_result_must_match_the_visit_kind(api):
    """PRD §3.5: "An `INITIAL` visit may end `VIOLATION_FOUND`, `NO_VIOLATION` or
    `NO_ACCESS`. A `REINSPECTION` may end `COMPLIANT`, `NON_COMPLIANT` or
    `NO_ACCESS`. Any other pairing — `VIOLATION_FOUND` or `NO_VIOLATION`
    reported on a re-inspection, `COMPLIANT` or `NON_COMPLIANT` reported on an
    initial visit — is rejected with `ERR_RESULT_KIND_MISMATCH`."
    PRD §3.5: "**`INITIAL` ending `VIOLATION_FOUND`** starts a four-hop cascade.
    The linked complaint moves `INSPECTION_SCHEDULED → INSPECTED`, recording the
    confirmed violation."

    Design: Corner/validations/corner_result_enum_must_match_inspection_kind
    """
    env, complaint, visit = setup_in_progress_visit(
        bootstrap_kwargs={"inspectors": 1}, with_assessment=True,
        scores=SEVERE_SCORES,
    )
    inspector = make_inspector_headers(env["insp1_id"])

    mismatched = api.complete_inspection(visit["id"], {"result": "COMPLIANT"}, inspector)
    assert mismatched.status_code == 422
    validate_error(mismatched, ApiErrorId.ERR_RESULT_KIND_MISMATCH.value)
    still_open = validate_success(
        api.get_inspection(visit["id"], make_supervisor_headers(env["sup_id"]))
    )
    assert still_open["status"] == "IN_PROGRESS"

    accepted = validate_success(
        api.complete_inspection(visit["id"], {"result": "VIOLATION_FOUND"}, inspector)
    )
    assert accepted["result"] == "VIOLATION_FOUND"
    assert accepted["status"] == "COMPLETED"
    complaint_after = validate_success(api.get_complaint(complaint["id"], CLERK))
    assert complaint_after["status"] == "INSPECTED"


def test_assessment_row_exposes_no_version_and_no_updated_at(api):
    """PRD §2.4: "Two record types are exceptions and carry only `id` and
    `created_at`: the harborage/attractant **assessment** attached to an
    inspection, and the **surveillance reading** attached to a bait station.
    Neither of those two has an `updated_at` and neither has a `version` — they
    are append-only observations, never edited."
    PRD §3.4: "From the index follows the `infestation_tier`: `SEVERE` when the
    index is at least 65.00, otherwise `MODERATE` when it is at least 35.00,
    otherwise `LOW`."

    Design: Corner/entities/corner_assessment_carries_no_version_field
    """
    env, _complaint, visit = setup_in_progress_visit(
        bootstrap_kwargs={"inspectors": 1}, with_assessment=True,
        scores={"harborage_score": 4, "attractant_score": 4,
                "sanitation_score": 3, "burrow_count": 0},
    )
    rows, meta = validate_paginated(
        api.list_assessments(visit["id"], make_supervisor_headers(env["sup_id"]))
    )
    assert meta["total_count"] == 1
    assert len(rows) == 1
    assessment = rows[0]
    assert_assessment(assessment)
    assert assessment["infestation_index"] == pytest.approx(37.50, abs=0.001)
    assert assessment["infestation_tier"] == "MODERATE"
    assert "version" not in assessment
    assert "updated_at" not in assessment


def test_infestation_index_at_exactly_sixty_five_is_severe(api):
    """PRD §3.4: "A burrow surcharge is then computed as 3.0 points for each
    active burrow counted, capped so that it never contributes more than 15.0
    points however many burrows were found."
    PRD §3.4: "From the index follows the `infestation_tier`: `SEVERE` when the
    index is at least 65.00, otherwise `MODERATE` when it is at least 35.00,
    otherwise `LOW`."

    Design: Difficulty/boundary_precision_check/infestation_tier_exactly_at_severe_threshold
    """
    env, _complaint, visit = setup_in_progress_visit(bootstrap_kwargs={"inspectors": 1})
    resp = api.create_assessment(
        visit["id"],
        {"harborage_score": 5, "attractant_score": 5, "sanitation_score": 5,
         "burrow_count": 5, "evidence_photo_count": 1},
        make_inspector_headers(env["insp1_id"]),
    )
    assessment = validate_success(resp, 201)
    assert_assessment(assessment)
    assert assessment["infestation_index"] == pytest.approx(65.00, abs=0.001)
    assert assessment["infestation_tier"] == "SEVERE"


def test_provisional_score_never_raises_the_chronic_flag(api):
    """PRD §3.4: "The moment an assessment is created, the parcel's
    `provisional_chronic_score` is overwritten with that single assessment's
    `infestation_index`, verbatim: no time decay, no repeat-offence surcharge, no
    history. The provisional figure is a single-observation working view for the
    officer in the field; it gates nothing, and it never sets `chronic_flag`."
    PRD §3.4: "Finally, `chronic_flag` becomes true when `chronic_score` is at
    least 60.00 and false otherwise."

    Design: Difficulty/boundary_precision_check/infestation_tier_exactly_at_severe_threshold
    """
    env, _complaint, visit = setup_in_progress_visit(bootstrap_kwargs={"inspectors": 1})
    validate_success(
        api.create_assessment(
            visit["id"],
            {"harborage_score": 5, "attractant_score": 5, "sanitation_score": 5,
             "burrow_count": 5, "evidence_photo_count": 1},
            make_inspector_headers(env["insp1_id"]),
        ),
        201,
    )
    prop = validate_success(
        api.get_property(env["prop_id"], make_supervisor_headers(env["sup_id"]))
    )
    assert prop["provisional_chronic_score"] == pytest.approx(65.00, abs=0.001)
    assert prop["chronic_flag"] is False
    assert prop["chronic_score"] == pytest.approx(0.00, abs=0.001)


def test_provisional_score_copies_the_new_assessment_verbatim(api):
    """PRD §3.4: "The moment an assessment is created, the parcel's
    `provisional_chronic_score` is overwritten with that single assessment's
    `infestation_index`, verbatim: no time decay, no repeat-offence surcharge, no
    history. The provisional figure is a single-observation working view for the
    officer in the field; it gates nothing, and it never sets `chronic_flag`."
    PRD §3.4: "From the index follows the `infestation_tier`: `SEVERE` when the
    index is at least 65.00, otherwise `MODERATE` when it is at least 35.00,
    otherwise `LOW`."

    Design: Difficulty/dual_variant_calc/property_chronic_score_provisional_vs_reviewed
    """
    env = setup_repeat_offender_parcel()
    assessment = validate_success(
        api.create_assessment(
            env["visit_id"],
            {"harborage_score": 6, "attractant_score": 6, "sanitation_score": 5,
             "burrow_count": 3, "evidence_photo_count": 4},
            make_inspector_headers(env["insp_id"]),
        ),
        201,
    )
    assert assessment["infestation_index"] == pytest.approx(66.50, abs=0.001)
    assert assessment["infestation_tier"] == "SEVERE"

    prop = validate_success(
        api.get_property(env["prop_id"], make_supervisor_headers(env["sup_id"]))
    )
    assert prop["provisional_chronic_score"] == pytest.approx(66.50, abs=0.001)
    assert prop["chronic_flag"] is False


def test_reviewed_score_decays_history_and_adds_the_repeat_surcharge(api):
    """PRD §3.4: "Each qualifying assessment is weighted by its age. Its age in
    whole days is the elapsed time from its parent visit's `completed_at` to the
    current logical clock, truncated downwards to a whole number of days. That
    day count is then divided by 30 and truncated downwards to a whole number of
    completed 30-day blocks, and the weight is 1.0 less 0.10 for each such block,
    floored at 0.0 so that no assessment ever contributes negatively."
    PRD §3.4: "A repeat-offence surcharge of 8.0 points is then added for every
    qualifying assessment beyond the first — with three qualifying assessments
    the surcharge is 16.0, and with one it is 0.0."
    PRD §3.4: "Because the two computations see different inputs, the same
    underlying assessment routinely leaves `provisional_chronic_score` and
    `chronic_score` holding different numbers on the same parcel, and both remain
    observable."

    Design: Difficulty/dual_variant_calc/property_chronic_score_provisional_vs_reviewed
    """
    env = setup_repeat_offender_parcel()
    record_assessment(
        env["visit_id"], env["insp_id"], harborage_score=6, attractant_score=6,
        sanitation_score=5, burrow_count=3, evidence_photo_count=4,
    )
    set_clock("2026-05-05T10:00:00Z")
    validate_success(
        api.complete_inspection(
            env["visit_id"], {"result": "VIOLATION_FOUND"},
            make_inspector_headers(env["insp_id"]),
        )
    )

    prop = validate_success(
        api.get_property(env["prop_id"], make_supervisor_headers(env["sup_id"]))
    )
    assert prop["chronic_score"] == pytest.approx(65.03, abs=0.001)
    assert prop["chronic_flag"] is True
    assert prop["provisional_chronic_score"] == pytest.approx(66.50, abs=0.001)


def test_violation_completion_drives_complaint_and_parcel(api):
    """PRD §3.5: "**`INITIAL` ending `VIOLATION_FOUND`** starts a four-hop
    cascade. The linked complaint moves `INSPECTION_SCHEDULED → INSPECTED`,
    recording the confirmed violation. That transition in turn triggers the
    reviewed chronic recomputation of §3.4: the parcel's `chronic_score` is
    rewritten, `chronic_flag` is set according to whether that score reached
    60.00, and the parcel's `version` is incremented by one."
    PRD §3.5: "Whichever result is recorded, four things always happen:
    `completed_at` is stamped from the logical clock and the `result` stored, the
    visit moves `IN_PROGRESS → COMPLETED`, the officer's
    `active_assignment_count` falls by one, and the parcel's `last_inspection_at`
    is set to that `completed_at`."

    Design: Difficulty/transitive_cascade/inspection_completion_chain_inspection_complaint_property_zone
    """
    env, complaint, visit = setup_in_progress_visit(
        bootstrap_kwargs={"inspectors": 1}, with_assessment=True,
        scores=SEVERE_SCORES,
    )
    set_clock("2026-05-05T09:45:00Z")
    completed = validate_success(
        api.complete_inspection(
            visit["id"],
            {"result": "VIOLATION_FOUND", "notes": "Active burrows confirmed"},
            make_inspector_headers(env["insp1_id"]),
        )
    )
    assert completed["status"] == "COMPLETED"
    assert completed["completed_at"] == "2026-05-05T09:45:00.000Z"

    complaint_after = validate_success(api.get_complaint(complaint["id"], CLERK))
    assert complaint_after["status"] == "INSPECTED"

    prop = validate_success(
        api.get_property(env["prop_id"], make_supervisor_headers(env["sup_id"]))
    )
    assert prop["chronic_score"] == pytest.approx(83.50, abs=0.001)
    assert prop["chronic_flag"] is True
    assert prop["last_inspection_at"] == "2026-05-05T09:45:00.000Z"


def test_chronic_flag_flip_raises_the_zone_chronic_property_count(api):
    """PRD §3.5: "If and only if `chronic_flag` flipped from false to true on
    that recomputation, a fourth hop fires: the zone's `chronic_property_count`
    rises by one, the zone's `rodent_index` and `posture` are recomputed, and the
    zone's `version` is incremented by one."
    PRD §3.8: "`chronic_property_count` is the number of parcels in the zone
    whose `chronic_flag` is true."

    Design: Difficulty/transitive_cascade/inspection_completion_chain_inspection_complaint_property_zone
    """
    env, _complaint, visit = setup_in_progress_visit(
        bootstrap_kwargs={"inspectors": 1}, with_assessment=True,
        scores=SEVERE_SCORES,
    )
    before = validate_success(api.get_zone(env["zone_id"], ADMIN))
    assert before["chronic_property_count"] == 0

    set_clock("2026-05-05T09:45:00Z")
    validate_success(
        api.complete_inspection(
            visit["id"],
            {"result": "VIOLATION_FOUND", "notes": "Active burrows confirmed"},
            make_inspector_headers(env["insp1_id"]),
        )
    )

    zone = validate_success(api.get_zone(env["zone_id"], ADMIN))
    assert zone["chronic_property_count"] == 1
    assert zone["open_complaint_count"] == 1
    assert zone["rodent_index"] == pytest.approx(4.00, abs=0.001)


def test_completion_cascade_is_visible_on_the_very_first_read(api):
    """PRD §3.5: "**`INITIAL` ending `VIOLATION_FOUND`** starts a four-hop
    cascade. The linked complaint moves `INSPECTION_SCHEDULED → INSPECTED`,
    recording the confirmed violation. That transition in turn triggers the
    reviewed chronic recomputation of §3.4: the parcel's `chronic_score` is
    rewritten, `chronic_flag` is set according to whether that score reached
    60.00, and the parcel's `version` is incremented by one. If and only if
    `chronic_flag` flipped from false to true on that recomputation, a fourth hop
    fires: the zone's `chronic_property_count` rises by one, the zone's
    `rodent_index` and `posture` are recomputed, and the zone's `version` is
    incremented by one."

    Design: Corner/consistency_model/corner_cascade_visible_in_the_same_response
    """
    env, complaint, visit = setup_in_progress_visit(
        bootstrap_kwargs={"inspectors": 1}, with_assessment=True,
        scores=SEVERE_SCORES,
    )
    set_clock("2026-05-05T09:45:00Z")
    validate_success(
        api.complete_inspection(
            visit["id"], {"result": "VIOLATION_FOUND"},
            make_inspector_headers(env["insp1_id"]),
        )
    )
    sup = make_supervisor_headers(env["sup_id"])

    first_complaint_read = validate_success(api.get_complaint(complaint["id"], CLERK))
    first_property_read = validate_success(api.get_property(env["prop_id"], sup))
    first_zone_read = validate_success(api.get_zone(env["zone_id"], ADMIN))

    assert first_complaint_read["status"] == "INSPECTED"
    assert first_property_read["chronic_flag"] is True
    assert first_property_read["chronic_score"] == pytest.approx(83.50, abs=0.001)
    assert first_zone_read["chronic_property_count"] == 1

    second_complaint_read = validate_success(api.get_complaint(complaint["id"], CLERK))
    second_property_read = validate_success(api.get_property(env["prop_id"], sup))
    second_zone_read = validate_success(api.get_zone(env["zone_id"], ADMIN))
    assert second_complaint_read["status"] == first_complaint_read["status"]
    assert second_property_read["chronic_score"] == first_property_read["chronic_score"]
    assert second_zone_read["chronic_property_count"] == first_zone_read["chronic_property_count"]
