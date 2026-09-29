"""Booking a sealing run: the wiring checks, the OCC guard and the schedule rules."""

from test_helpers import (
    ADMIN_HEADERS,
    ELIGIBILITY_EXCLUDED,
    ERR_ASBESTOS_SCREENING_REQUIRED,
    ERR_DUCT_SYSTEM_EXCLUDED,
    ERR_INVALID_REQUEST,
    ERR_PRE_TEST_SYSTEM_MISMATCH,
    ERR_RETEST_TARGET_INVALID,
    ERR_SEAL_JOB_INVALID_STATE,
    ERR_STALE_DUCT_SYSTEM_VERSION,
    ERR_TECHNICIAN_NOT_CERTIFIED,
    ERR_TECHNICIAN_SCHEDULE_CONFLICT,
    ERR_TEST_PHASE_MISMATCH,
    EXCLUSION_INACCESSIBLE,
    EXCLUSION_MATERIAL_NOT_SEALABLE,
    EXCLUSION_STRUCTURAL_DAMAGE,
    JOB_ABORTED_MANUAL,
    JOB_ABORTED_SUPERSEDED,
    JOB_MASKING,
    JOB_SCHEDULED,
    PHASE_POST,
    PHASE_PRE,
    QA_HEADERS,
    SCREENING_SUSPECT,
    SEAL_STATUS_SEAL_PENDING,
    TEST_ACCEPTED,
    factories as f,
    fixtures as fx,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_booking_against_an_excluded_duct_system_is_refused(api):
    """An excluded system is unbookable and the refusal leaves no trace behind it.

    PRD 3.2: "Once a system is `EXCLUDED` no new sealing run may be booked against
    it — that attempt is `ERR_DUCT_SYSTEM_EXCLUDED`".

    Design: Difficulty/cross_entity_state_dependency/seal_job_create_blocked_by_excluded_duct_system
    """
    sc = fx.scenario_ready_to_inject(api)
    excluded = validate_success(
        api.exclude_duct_system(
            sc.duct_system_id,
            f.exclude_payload(exclusion_reason=EXCLUSION_STRUCTURAL_DAMAGE),
            ADMIN_HEADERS,
        )
    )
    assert excluded["eligibility_status"] == ELIGIBILITY_EXCLUDED
    assert excluded["seal_status"] == SEAL_STATUS_SEAL_PENDING

    payload = f.seal_job_payload(
        sc.duct_system_id,
        sc.pre_test["id"],
        sc.technician_id,
        sc.duct_system_version(),
    )
    validate_error(
        api.create_seal_job(payload, sc.tech_headers), ERR_DUCT_SYSTEM_EXCLUDED, 422
    )

    after = sc.read_duct_system()
    assert after["seal_status"] == SEAL_STATUS_SEAL_PENDING
    assert after["active_seal_job_id"] is None
    _, meta = validate_paginated(
        api.list_seal_jobs(ADMIN_HEADERS, duct_system_id=sc.duct_system_id)
    )
    assert meta["total_count"] == 0
    assert sc.read_technician()["open_seal_job_count"] == 0


def test_every_exclusion_reason_blocks_booking_with_the_same_referential_error(api):
    """The refusal keys off `EXCLUDED`, not off which reason produced it.

    PRD 2.8 rung 9: "**Cross-entity coherence** — the artefacts being wired
    together actually belong together, all HTTP 422 ... `ERR_DUCT_SYSTEM_EXCLUDED`".

    Design: Difficulty/cross_entity_state_dependency/seal_job_create_blocked_by_excluded_duct_system
    """
    sc = fx.scenario_with_baseline(api)
    sibling = fx.add_duct_system(sc, system_label="AHU-2", lab_reference="LAB-1002")
    fx.add_accepted_leakage_test(sc, duct_system=sibling)

    validate_success(
        api.exclude_duct_system(
            sc.duct_system_id,
            f.exclude_payload(exclusion_reason=EXCLUSION_MATERIAL_NOT_SEALABLE),
            ADMIN_HEADERS,
        )
    )
    validate_success(
        api.exclude_duct_system(
            sibling["id"],
            f.exclude_payload(exclusion_reason=EXCLUSION_INACCESSIBLE),
            ADMIN_HEADERS,
        )
    )

    for duct_system in (sc.duct_system, sibling):
        payload = f.seal_job_payload(
            duct_system["id"],
            sc.pre_tests[duct_system["id"]]["id"],
            sc.technician_id,
            sc.duct_system_version(duct_system["id"]),
        )
        validate_error(
            api.create_seal_job(payload, sc.tech_headers), ERR_DUCT_SYSTEM_EXCLUDED, 422
        )

    assert sc.read_technician()["open_seal_job_count"] == 0
    assert sc.read_project()["eligible_duct_system_count"] == 0


def test_adjacent_technician_slots_are_allowed_and_overlapping_ones_are_not(api):
    """Booked slots are half-open, so touching at an instant is not an overlap.

    PRD 3.5: "Booking is refused with `ERR_TECHNICIAN_SCHEDULE_CONFLICT` when the
    named technician already owns a non-terminal run whose booked slot overlaps the
    requested one, where each slot is treated as **half-open** — it includes its
    start instant and excludes its end instant. Two runs that merely share an
    endpoint instant, one ending exactly when the next begins, therefore do **not**
    conflict."

    Design: Difficulty/resource_temporal_overlap/technician_schedule_half_open_adjacent_allowed_overlap_rejected
    """
    sc = fx.scenario_with_baseline(api)
    second = fx.add_duct_system(sc, system_label="AHU-2", lab_reference="LAB-1002")
    third = fx.add_duct_system(sc, system_label="AHU-3", lab_reference="LAB-1003")
    fx.add_accepted_leakage_test(sc, duct_system=second)
    fx.add_accepted_leakage_test(sc, duct_system=third)

    job_a = fx.schedule_seal_job(
        sc,
        scheduled_start_at=f.utc(2026, 8, 2, 13, 0),
        scheduled_end_at=f.utc(2026, 8, 2, 18, 0),
    )
    job_b = fx.schedule_seal_job(
        sc,
        duct_system=second,
        scheduled_start_at=f.utc(2026, 8, 2, 18, 0),
        scheduled_end_at=f.utc(2026, 8, 2, 21, 0),
    )
    assert job_b["status"] == JOB_SCHEDULED

    conflicting = f.seal_job_payload(
        third["id"],
        sc.pre_tests[third["id"]]["id"],
        sc.technician_id,
        sc.duct_system_version(third["id"]),
        scheduled_start_at=f.utc(2026, 8, 2, 17, 0),
        scheduled_end_at=f.utc(2026, 8, 2, 19, 0),
    )
    validate_error(
        api.create_seal_job(conflicting, sc.tech_headers),
        ERR_TECHNICIAN_SCHEDULE_CONFLICT,
        409,
    )

    assert sc.read_technician()["open_seal_job_count"] == 2
    rows, meta = validate_paginated(
        api.list_seal_jobs(ADMIN_HEADERS, technician_id=sc.technician_id)
    )
    assert meta["total_count"] == 2
    assert {row["id"] for row in rows} == {job_a["id"], job_b["id"]}

    third_view = sc.read_duct_system(third["id"])
    assert third_view["active_seal_job_id"] is None
    assert third_view["seal_status"] == SEAL_STATUS_SEAL_PENDING


def test_the_schedule_guard_only_looks_at_the_named_technicians_live_runs(api):
    """A different technician, or a run already aborted, frees the same slot.

    PRD 3.5: "Booking is refused with `ERR_TECHNICIAN_SCHEDULE_CONFLICT` when the
    named technician already owns a non-terminal run whose booked slot overlaps the
    requested one".

    Design: Difficulty/resource_temporal_overlap/technician_schedule_half_open_adjacent_allowed_overlap_rejected
    """
    sc = fx.scenario_with_baseline(api)
    second = fx.add_duct_system(sc, system_label="AHU-2", lab_reference="LAB-1002")
    third = fx.add_duct_system(sc, system_label="AHU-3", lab_reference="LAB-1003")
    fx.add_accepted_leakage_test(sc, duct_system=second)
    fx.add_accepted_leakage_test(sc, duct_system=third)
    other_technician = fx.add_technician(
        sc, full_name="Sam Okafor", license_number="AS-5590"
    )

    job_a = fx.schedule_seal_job(
        sc,
        scheduled_start_at=f.utc(2026, 8, 2, 13, 0),
        scheduled_end_at=f.utc(2026, 8, 2, 18, 0),
    )

    # A second technician may hold the very same hours.
    overlapping_for_other = fx.schedule_seal_job(
        sc,
        duct_system=second,
        technician=other_technician,
        scheduled_start_at=f.utc(2026, 8, 2, 17, 0),
        scheduled_end_at=f.utc(2026, 8, 2, 19, 0),
    )
    assert overlapping_for_other["technician_id"] == other_technician["id"]

    # Once the first run is terminal its slot no longer blocks its own technician.
    aborted = validate_success(
        api.abort_seal_job(job_a["id"], f.abort_payload(), sc.tech_headers)
    )
    assert aborted["status"] == JOB_ABORTED_MANUAL

    reused = fx.schedule_seal_job(
        sc,
        duct_system=third,
        scheduled_start_at=f.utc(2026, 8, 2, 17, 0),
        scheduled_end_at=f.utc(2026, 8, 2, 19, 0),
    )
    assert reused["status"] == JOB_SCHEDULED
    assert sc.read_technician()["open_seal_job_count"] == 1


def test_a_newer_booking_supersedes_the_still_scheduled_run(api):
    """The older booking is aborted, its technician's open count nets out and the
    dead run accepts nothing further.

    PRD 3.5: "Booking is also a **supersede**: any pre-existing run on the same duct
    system whose status is still `SCHEDULED` is moved to `ABORTED_SUPERSEDED` with
    `abort_reason` recorded as `superseded by a newer scheduled job`, and that
    superseded run's technician has their `open_seal_job_count` reduced by 1."

    Design: Corner/state_machines/newer_seal_job_supersedes_the_still_scheduled_one
    """
    sc = fx.scenario_with_baseline(api)
    first = fx.schedule_seal_job(
        sc,
        scheduled_start_at=f.utc(2026, 8, 2, 13, 0),
        scheduled_end_at=f.utc(2026, 8, 2, 18, 0),
    )
    assert sc.read_technician()["open_seal_job_count"] == 1

    second = fx.schedule_seal_job(
        sc,
        scheduled_start_at=f.utc(2026, 8, 2, 18, 0),
        scheduled_end_at=f.utc(2026, 8, 2, 21, 0),
    )

    superseded = sc.read_seal_job(first["id"])
    assert superseded["status"] == JOB_ABORTED_SUPERSEDED
    assert superseded["abort_reason"] == "superseded by a newer scheduled job"
    assert sc.read_seal_job(second["id"])["status"] == JOB_SCHEDULED
    assert sc.read_technician()["open_seal_job_count"] == 1
    assert sc.read_duct_system()["active_seal_job_id"] == second["id"]

    validate_error(
        api.mask_registers(first["id"], f.masks_payload(["R1"]), sc.tech_headers),
        ERR_SEAL_JOB_INVALID_STATE,
        409,
    )


def test_a_booking_made_from_a_stale_read_cannot_discard_a_colleagues_run(api):
    """The version guard fires before the supersede, so the stale writer loses.

    PRD 3.5: "This is precisely why the operation is guarded by the stale-version
    check of §2.7 — without it a client working from a stale read would silently
    discard a colleague's booking."

    Design: Corner/cross_cutting_complexity_layers/stale_duct_system_version_loses_the_supersede_race
    """
    sc = fx.scenario_with_baseline(api)
    stale_version = sc.duct_system_version()

    first = fx.schedule_seal_job(
        sc,
        scheduled_start_at=f.utc(2026, 8, 2, 13, 0),
        scheduled_end_at=f.utc(2026, 8, 2, 18, 0),
    )
    fresh_version = sc.duct_system_version()
    assert fresh_version == stale_version + 1

    adjacent = dict(
        scheduled_start_at=f.utc(2026, 8, 2, 18, 0),
        scheduled_end_at=f.utc(2026, 8, 2, 21, 0),
    )
    stale_attempt = f.seal_job_payload(
        sc.duct_system_id,
        sc.pre_test["id"],
        sc.technician_id,
        stale_version,
        **adjacent,
    )
    validate_error(
        api.create_seal_job(stale_attempt, sc.tech_headers),
        ERR_STALE_DUCT_SYSTEM_VERSION,
        412,
    )
    assert sc.duct_system_version() == fresh_version
    assert sc.read_seal_job(first["id"])["status"] == JOB_SCHEDULED

    second = validate_success(
        api.create_seal_job(
            f.seal_job_payload(
                sc.duct_system_id,
                sc.pre_test["id"],
                sc.technician_id,
                fresh_version,
                **adjacent,
            ),
            sc.tech_headers,
        ),
        201,
    )
    assert sc.read_seal_job(first["id"])["status"] == JOB_ABORTED_SUPERSEDED
    assert sc.read_duct_system()["active_seal_job_id"] == second["id"]
    assert sc.read_technician()["open_seal_job_count"] == 1


def test_the_version_guard_outranks_the_exclusion_check_on_the_same_request(api):
    """A stale read is reported as stale even when the parent is also unbookable.

    PRD 2.8 orders rung 7 "**Concurrency** — when the endpoint declares an
    expected-version input, it equals the named parent's current `version`, else the
    matching stale-version error (412)." ahead of rung 9 "**Cross-entity
    coherence** — the artefacts being wired together actually belong together, all
    HTTP 422: ... `ERR_DUCT_SYSTEM_EXCLUDED`".

    Design: Corner/validations/stale_parent_version_beats_the_exclusion_referential_check
    """
    sc = fx.scenario_with_baseline(api)
    stale_version = sc.duct_system_version()
    validate_success(
        api.exclude_duct_system(
            sc.duct_system_id,
            f.exclude_payload(exclusion_reason=EXCLUSION_INACCESSIBLE),
            ADMIN_HEADERS,
        )
    )
    fresh_version = sc.duct_system_version()
    assert fresh_version == stale_version + 1

    validate_error(
        api.create_seal_job(
            f.seal_job_payload(
                sc.duct_system_id, sc.pre_test["id"], sc.technician_id, stale_version
            ),
            sc.tech_headers,
        ),
        ERR_STALE_DUCT_SYSTEM_VERSION,
        412,
    )
    validate_error(
        api.create_seal_job(
            f.seal_job_payload(
                sc.duct_system_id, sc.pre_test["id"], sc.technician_id, fresh_version
            ),
            sc.tech_headers,
        ),
        ERR_DUCT_SYSTEM_EXCLUDED,
        422,
    )
    assert sc.duct_system_version() == fresh_version


def test_an_unscreened_or_suspect_system_is_unbookable_until_it_clears(api):
    """`PENDING_SCREENING` blocks booking, and a `SUSPECT` result leaves it there.

    PRD 3.2: "a system still sitting at `PENDING_SCREENING` is equally unbookable,
    reported as `ERR_ASBESTOS_SCREENING_REQUIRED`" and "A result of `SUSPECT` stamps
    the result and the reference but leaves `eligibility_status` at
    `PENDING_SCREENING`, so the system stays unsealable".

    Design: Corner/validations/pending_and_suspect_screening_both_block_seal_job_creation
    """
    sc = fx.scenario_base(api)
    duct_system = fx.add_duct_system(sc, clear_screening=False)
    pre_test = fx.add_accepted_leakage_test(sc, duct_system=duct_system)

    def attempt():
        return api.create_seal_job(
            f.seal_job_payload(
                duct_system["id"],
                pre_test["id"],
                sc.technician_id,
                sc.duct_system_version(duct_system["id"]),
            ),
            sc.tech_headers,
        )

    validate_error(attempt(), ERR_ASBESTOS_SCREENING_REQUIRED, 422)

    suspect = validate_success(
        api.record_asbestos_screening(
            duct_system["id"],
            f.asbestos_screening_payload(
                asbestos_screening_result=SCREENING_SUSPECT, lab_reference="LAB-2002"
            ),
            QA_HEADERS,
        )
    )
    assert suspect["asbestos_screening_result"] == SCREENING_SUSPECT
    validate_error(attempt(), ERR_ASBESTOS_SCREENING_REQUIRED, 422)

    validate_success(
        api.record_asbestos_screening(
            duct_system["id"],
            f.asbestos_screening_payload(lab_reference="LAB-2003"),
            QA_HEADERS,
        )
    )
    booked = validate_success(attempt(), 201)
    assert booked["status"] == JOB_SCHEDULED


def test_a_baseline_taken_on_a_sibling_system_cannot_back_this_run(api):
    """The measurement must belong to the very system being sealed.

    PRD 3.5: "`pre_test_id` names the measurement that establishes its baseline and
    must be an `ACCEPTED`, `PRE`-phase measurement on that very same duct system: a
    measurement belonging to a different system is rejected with
    `ERR_PRE_TEST_SYSTEM_MISMATCH`".

    Design: Corner/validations/pre_test_belonging_to_a_sibling_duct_system_is_refused
    """
    sc = fx.scenario_with_baseline(api)
    sibling = fx.add_duct_system(sc, system_label="AHU-2", lab_reference="LAB-1002")
    sibling_test = fx.add_accepted_leakage_test(sc, duct_system=sibling)

    version_before = sc.duct_system_version()
    validate_error(
        api.create_seal_job(
            f.seal_job_payload(
                sc.duct_system_id,
                sibling_test["id"],
                sc.technician_id,
                version_before,
            ),
            sc.tech_headers,
        ),
        ERR_PRE_TEST_SYSTEM_MISMATCH,
        422,
    )
    assert sc.duct_system_version() == version_before

    booked = validate_success(
        api.create_seal_job(
            f.seal_job_payload(
                sc.duct_system_id,
                sc.pre_test["id"],
                sc.technician_id,
                version_before,
            ),
            sc.tech_headers,
        ),
        201,
    )
    assert booked["pre_test_id"] == sc.pre_test["id"]


def test_an_unreviewed_baseline_and_a_post_measurement_share_one_refusal(api):
    """Wrong phase and wrong status collapse into the same coherence error.

    PRD 3.5: "a measurement of the wrong phase or one that is not in status
    `ACCEPTED` is rejected with `ERR_TEST_PHASE_MISMATCH`".

    Design: Corner/validations/unaccepted_and_wrong_phase_tests_share_one_phase_mismatch_error
    """
    sc = fx.scenario_with_baseline(api)

    # A second PRE measurement stopped at RECORDED, never reviewed.
    unreviewed = validate_success(
        api.create_leakage_test(
            f.leakage_test_payload(
                sc.duct_system_id,
                window_start_at=f.utc(2026, 8, 1, 16, 1),
                window_end_at=f.utc(2026, 8, 1, 17, 0),
            ),
            sc.tech_headers,
        ),
        201,
    )
    validate_success(
        api.pressurize_leakage_test(
            unreviewed["id"], f.pressurize_payload(), sc.tech_headers
        )
    )
    recorded = validate_success(
        api.record_leakage_test(unreviewed["id"], f.record_payload(), sc.tech_headers)
    )
    assert recorded["phase"] == PHASE_PRE

    accepted_post = fx.add_accepted_leakage_test(sc, phase=PHASE_POST)
    assert accepted_post["status"] == TEST_ACCEPTED
    assert accepted_post["phase"] == PHASE_POST

    for wrong_test in (recorded, accepted_post):
        validate_error(
            api.create_seal_job(
                f.seal_job_payload(
                    sc.duct_system_id,
                    wrong_test["id"],
                    sc.technician_id,
                    sc.duct_system_version(),
                ),
                sc.tech_headers,
            ),
            ERR_TEST_PHASE_MISMATCH,
            422,
        )

    booked = validate_success(
        api.create_seal_job(
            f.seal_job_payload(
                sc.duct_system_id,
                sc.pre_test["id"],
                sc.technician_id,
                sc.duct_system_version(),
            ),
            sc.tech_headers,
        ),
        201,
    )
    assert booked["status"] == JOB_SCHEDULED


def test_a_retest_may_only_follow_a_verified_or_retest_required_run(api):
    """A live run, or a verified run on another system, is not a legal parent.

    PRD 3.5: "`retest_of_job_id` ... when present it must point at a run on the
    **same** duct system whose status is `VERIFIED` or `RETEST_REQUIRED`, and
    anything else is `ERR_RETEST_TARGET_INVALID`".

    Design: Corner/validations/retest_target_must_be_verified_or_retest_required
    """
    sc = fx.scenario_issued_report(api)
    verified_job = sc.read_seal_job()
    sibling = fx.add_duct_system(sc, system_label="AHU-2", lab_reference="LAB-1002")
    sibling_test = fx.add_accepted_leakage_test(sc, duct_system=sibling)

    live_on_sibling = fx.schedule_seal_job(
        sc,
        duct_system=sibling,
        scheduled_start_at=f.utc(2026, 8, 3, 9, 0),
        scheduled_end_at=f.utc(2026, 8, 3, 12, 0),
    )

    def retest_attempt(duct_system_id, pre_test_id, parent_id, start_hour):
        payload = f.seal_job_payload(
            duct_system_id,
            pre_test_id,
            sc.technician_id,
            sc.duct_system_version(duct_system_id),
            scheduled_start_at=f.utc(2026, 8, 3, start_hour, 0),
            scheduled_end_at=f.utc(2026, 8, 3, start_hour + 2, 0),
        )
        payload["retest_of_job_id"] = parent_id
        return api.create_seal_job(payload, sc.tech_headers)

    validate_error(
        retest_attempt(sibling["id"], sibling_test["id"], live_on_sibling["id"], 13),
        ERR_RETEST_TARGET_INVALID,
        422,
    )
    validate_error(
        retest_attempt(sibling["id"], sibling_test["id"], verified_job["id"], 13),
        ERR_RETEST_TARGET_INVALID,
        422,
    )
    assert sc.read_seal_job(live_on_sibling["id"])["status"] == JOB_SCHEDULED

    retest = validate_success(
        retest_attempt(sc.duct_system_id, sc.pre_test["id"], verified_job["id"], 16), 201
    )
    assert retest["retest_of_job_id"] == verified_job["id"]
    assert retest["status"] == JOB_SCHEDULED


def test_a_technician_awaiting_certification_cannot_be_assigned_a_run(api):
    """Certification is enforced at booking, and activating it unblocks the booking.

    PRD 3.5: "Certification is enforced here as well as at injection: a technician
    whose `certification_status` is not `ACTIVE` yields
    `ERR_TECHNICIAN_NOT_CERTIFIED`".

    Design: Corner/validations/pending_certification_blocks_assignment_until_it_is_activated
    """
    sc = fx.scenario_base(api, technician={"certification_status": "PENDING"})
    duct_system = fx.add_duct_system(sc)
    pre_test = fx.add_accepted_leakage_test(sc, duct_system=duct_system)
    assert sc.technician["certification_status"] == "PENDING"

    def attempt():
        return api.create_seal_job(
            f.seal_job_payload(
                duct_system["id"],
                pre_test["id"],
                sc.technician_id,
                sc.duct_system_version(duct_system["id"]),
            ),
            sc.tech_headers,
        )

    validate_error(attempt(), ERR_TECHNICIAN_NOT_CERTIFIED, 422)

    activated = validate_success(
        api.record_certification(
            sc.technician_id, f.certification_payload(), ADMIN_HEADERS
        )
    )
    assert activated["certification_status"] == "ACTIVE"
    assert validate_success(attempt(), 201)["status"] == JOB_SCHEDULED


def test_seal_job_filters_intersect_and_the_page_window_is_validated(api):
    """Several filters narrow the same population, and `total_count` follows.

    PRD 2.5: "Seal jobs are listed at the top level and can be filtered by
    `duct_system_id`, `pre_test_id`, `technician_id`, `retest_of_job_id` and
    `status`" — a list PRD 2.3 pages. PRD 2.3: "`total_count` is the size of the filtered population, not
    the size of the returned page" and "A `limit` outside the 1-to-100 range or a
    negative `offset` is a malformed request and is rejected with
    `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/endpoints/seal_job_list_filters_compose_with_offset_pagination
    """
    sc = fx.scenario_with_baseline(api)
    second = fx.add_duct_system(sc, system_label="AHU-2", lab_reference="LAB-1002")
    third = fx.add_duct_system(sc, system_label="AHU-3", lab_reference="LAB-1003")
    fx.add_accepted_leakage_test(sc, duct_system=second)
    fx.add_accepted_leakage_test(sc, duct_system=third)
    other_technician = fx.add_technician(
        sc, full_name="Sam Okafor", license_number="AS-5590"
    )

    job_a = fx.schedule_seal_job(
        sc,
        scheduled_start_at=f.utc(2026, 8, 2, 13, 0),
        scheduled_end_at=f.utc(2026, 8, 2, 18, 0),
    )
    fx.mask_all_registers(sc, seal_job=job_a)
    job_b = fx.schedule_seal_job(
        sc,
        duct_system=second,
        scheduled_start_at=f.utc(2026, 8, 2, 18, 0),
        scheduled_end_at=f.utc(2026, 8, 2, 21, 0),
    )
    job_c = fx.schedule_seal_job(
        sc,
        duct_system=third,
        technician=other_technician,
        scheduled_start_at=f.utc(2026, 8, 2, 13, 0),
        scheduled_end_at=f.utc(2026, 8, 2, 18, 0),
    )

    rows, meta = validate_paginated(api.list_seal_jobs(ADMIN_HEADERS))
    assert meta["limit"] == 10 and meta["offset"] == 0
    assert meta["total_count"] == 3 and meta["has_more"] is False
    assert [row["id"] for row in rows] == [job_a["id"], job_b["id"], job_c["id"]]

    rows, meta = validate_paginated(
        api.list_seal_jobs(ADMIN_HEADERS, status=JOB_SCHEDULED)
    )
    assert meta["total_count"] == 2
    assert {row["id"] for row in rows} == {job_b["id"], job_c["id"]}

    rows, meta = validate_paginated(
        api.list_seal_jobs(
            ADMIN_HEADERS, status=JOB_SCHEDULED, technician_id=sc.technician_id
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == job_b["id"]

    rows, meta = validate_paginated(
        api.list_seal_jobs(ADMIN_HEADERS, duct_system_id=sc.duct_system_id)
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == job_a["id"]
    assert rows[0]["status"] == JOB_MASKING

    rows, meta = validate_paginated(
        api.list_seal_jobs(ADMIN_HEADERS, pre_test_id=sc.pre_test["id"])
    )
    assert meta["total_count"] == 1 and rows[0]["id"] == job_a["id"]

    rows, meta = validate_paginated(api.list_seal_jobs(ADMIN_HEADERS, limit=2))
    assert len(rows) == 2 and meta["total_count"] == 3 and meta["has_more"] is True
    rows, meta = validate_paginated(api.list_seal_jobs(ADMIN_HEADERS, limit=2, offset=2))
    assert len(rows) == 1 and meta["offset"] == 2 and meta["has_more"] is False

    validate_error(api.list_seal_jobs(ADMIN_HEADERS, limit=0), ERR_INVALID_REQUEST, 400)
    validate_error(
        api.list_seal_jobs(ADMIN_HEADERS, limit=101), ERR_INVALID_REQUEST, 400
    )
    validate_error(api.list_seal_jobs(ADMIN_HEADERS, offset=-1), ERR_INVALID_REQUEST, 400)


def test_nested_collections_return_only_their_own_parents_rows(api):
    """A parent-scoped listing never leaks a sibling parent's rows, and its filters
    narrow the population it does return.

    PRD 2.5: "A project's duct systems are listed under the project and can be
    narrowed by `eligibility_status` and by `seal_status`. A duct system's leakage
    tests are listed under the duct system and can be narrowed by `phase` and by
    `status`."

    Design: Corner/endpoints/nested_collections_are_scoped_to_their_parent_and_filterable
    """
    sc = fx.scenario_with_baseline(api)
    second = fx.add_duct_system(sc, system_label="AHU-2", lab_reference="LAB-1002")
    validate_success(
        api.exclude_duct_system(
            second["id"],
            f.exclude_payload(exclusion_reason=EXCLUSION_INACCESSIBLE),
            ADMIN_HEADERS,
        )
    )
    fx.add_accepted_leakage_test(sc, phase=PHASE_POST)

    other_project = validate_success(
        api.create_project(
            f.project_payload(
                utility_program_id=sc.program_id, address_line="41 Cedar Row"
            ),
            ADMIN_HEADERS,
        ),
        201,
    )
    foreign_system = validate_success(
        api.create_duct_system(
            other_project["id"], f.duct_system_payload(system_label="AHU-9"), ADMIN_HEADERS
        ),
        201,
    )

    rows, meta = validate_paginated(api.list_duct_systems(sc.project_id, ADMIN_HEADERS))
    assert meta["total_count"] == 2
    assert {row["id"] for row in rows} == {sc.duct_system_id, second["id"]}
    assert foreign_system["id"] not in {row["id"] for row in rows}

    rows, meta = validate_paginated(
        api.list_duct_systems(
            sc.project_id, ADMIN_HEADERS, eligibility_status=ELIGIBILITY_EXCLUDED
        )
    )
    assert meta["total_count"] == 1 and rows[0]["id"] == second["id"]

    rows, meta = validate_paginated(
        api.list_duct_systems(
            sc.project_id, ADMIN_HEADERS, seal_status=SEAL_STATUS_SEAL_PENDING
        )
    )
    assert meta["total_count"] == 2

    rows, meta = validate_paginated(
        api.list_duct_systems(other_project["id"], ADMIN_HEADERS)
    )
    assert meta["total_count"] == 1 and rows[0]["id"] == foreign_system["id"]

    project_view = sc.read_project()
    assert project_view["duct_system_count"] == 2
    assert project_view["eligible_duct_system_count"] == 1

    rows, meta = validate_paginated(
        api.list_leakage_tests(sc.duct_system_id, ADMIN_HEADERS)
    )
    assert meta["total_count"] == 2
    rows, meta = validate_paginated(
        api.list_leakage_tests(sc.duct_system_id, ADMIN_HEADERS, phase=PHASE_PRE)
    )
    assert meta["total_count"] == 1 and rows[0]["phase"] == PHASE_PRE
    _, meta = validate_paginated(api.list_leakage_tests(second["id"], ADMIN_HEADERS))
    assert meta["total_count"] == 0
