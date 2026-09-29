"""The verification report: two reduction bases, the guarantee comparison, the
warranty it opens and the re-test that closes it."""

from test_helpers import (
    ADMIN_HEADERS,
    ERR_GUARANTEE_NOT_MET,
    ERR_RETEST_WINDOW_ELAPSED,
    ERR_STALE_SEAL_JOB_VERSION,
    EXCLUSION_INACCESSIBLE,
    JOB_RETEST_CLOSED,
    JOB_RETEST_REQUIRED,
    JOB_SEALED,
    JOB_VERIFIED,
    MATERIAL_FLEX,
    PHASE_POST,
    QA_HEADERS,
    REPORT_DRAFT,
    REPORT_ISSUED,
    SEAL_STATUS_SEAL_PENDING,
    SEAL_STATUS_SEALED,
    SEAL_STATUS_VERIFIED,
    WARRANTY_LAPSED,
    WARRANTY_NOT_REGISTERED,
    WARRANTY_REGISTERED,
    factories as f,
    fixtures as fx,
    reduction_pct,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_the_two_reduction_bases_diverge_when_a_sibling_system_is_unsealed(api):
    """The guarantee basis sees one system; the rebate basis charges the whole house.

    PRD 3.7: "This basis looks only at the one system that was sealed and ignores
    every sibling system, sealed or not." And: "when a candidate has no accepted post
    measurement at all, of that system's own `baseline_leakage_cfm25`, which is to say
    an unsealed sibling is charged at its full original leakage ... a dealer who seals
    only one of two air handlers will meet the guarantee while failing the rebate
    minimum."

    Design: Difficulty/dual_variant_calc/whole_house_vs_system_basis_reduction_divergence
    """
    sc = fx.scenario_post_verified(api)
    sibling = fx.add_duct_system(
        sc,
        system_label="AHU-2",
        total_register_count=6,
        design_cfm=800.0,
        duct_material=MATERIAL_FLEX,
        lab_reference="LAB-1002",
    )
    fx.add_accepted_leakage_test(sc, duct_system=sibling, measured_leakage_cfm=200.0)
    assert sc.read_duct_system(sibling["id"])["baseline_leakage_cfm25"] == 200.00

    report = fx.draft_report(sc)
    assert report["pre_leakage_cfm25"] == 300.00
    assert report["post_leakage_cfm25"] == 55.00
    assert report["reduction_pct_system_basis"] == reduction_pct(300.00, 55.00)
    assert report["reduction_pct_system_basis"] == 81.67

    # Pre side 300.00 + 200.00; post side 55.00 + the sibling's own baseline 200.00.
    assert report["cfm_reduced_whole_house"] == 245.00
    assert report["reduction_pct_whole_house_basis"] == reduction_pct(500.00, 255.00)
    assert report["reduction_pct_whole_house_basis"] == 49.00
    assert report["guarantee_threshold_pct"] == 80.00
    assert report["guarantee_met"] is True
    assert (
        report["reduction_pct_system_basis"] - report["reduction_pct_whole_house_basis"]
        == 32.67
    )


def test_excluding_the_sibling_removes_it_from_both_sides_of_the_aggregation(api):
    """An `EXCLUDED` system leaves the candidate set entirely, so the bases converge.

    PRD 3.7: "aggregated over a candidate set consisting of every duct system
    belonging to the report's project whose `eligibility_status` is `ELIGIBLE` **and**
    whose `baseline_leakage_cfm25` is not null ... Systems whose `eligibility_status`
    is `EXCLUDED` are omitted from both sides of the aggregation."

    Design: Difficulty/dual_variant_calc/whole_house_vs_system_basis_reduction_divergence
    """
    sc = fx.scenario_post_verified(api)
    sibling = fx.add_duct_system(
        sc, system_label="AHU-2", lab_reference="LAB-1002"
    )
    fx.add_accepted_leakage_test(sc, duct_system=sibling, measured_leakage_cfm=200.0)
    validate_success(
        api.exclude_duct_system(
            sibling["id"],
            f.exclude_payload(exclusion_reason=EXCLUSION_INACCESSIBLE),
            ADMIN_HEADERS,
        )
    )

    report = fx.draft_report(sc)
    assert report["reduction_pct_system_basis"] == 81.67
    assert report["reduction_pct_whole_house_basis"] == 81.67
    assert report["cfm_reduced_whole_house"] == 245.00
    assert report["guarantee_met"] is True


def test_a_reduction_exactly_on_the_threshold_meets_the_guarantee(api):
    """The guarantee comparison is inclusive at the threshold.

    PRD 3.7: "`guarantee_met` is true exactly when `reduction_pct_system_basis` is
    greater than or equal to `guarantee_threshold_pct` — the comparison is inclusive,
    so a reduction exactly equal to the threshold meets the guarantee."

    Design: Difficulty/boundary_precision_check/guarantee_threshold_exact_equality_met
    """
    sc = fx.scenario_post_verified(
        api,
        samples=(
            (1, 300.0, 0, 700.0),
            (2, 200.0, 240, 710.0),
            (3, 60.0, 480, 720.0),
        ),
        post={"measured_leakage_cfm": 60.0},
    )
    report = fx.draft_report(sc)
    assert report["post_leakage_cfm25"] == 60.00
    assert report["reduction_pct_system_basis"] == 80.00
    assert report["guarantee_threshold_pct"] == 80.00
    assert report["guarantee_met"] is True
    assert report["status"] == REPORT_DRAFT

    issued = fx.issue_report(sc)
    assert issued["status"] == REPORT_ISSUED
    assert sc.read_seal_job()["status"] == JOB_VERIFIED
    assert sc.read_duct_system()["seal_status"] == SEAL_STATUS_VERIFIED


def test_a_reduction_one_hundredth_below_the_threshold_is_refused(api):
    """79.99 is not 80.00, and the shortfall stops issuance.

    PRD 3.7: "`guarantee_met` must read true, or the issuance is refused with
    `ERR_GUARANTEE_NOT_MET`."

    Design: Difficulty/boundary_precision_check/guarantee_threshold_exact_equality_met
    """
    sc = fx.scenario_post_verified(
        api,
        job={"target_leakage_cfm": 61.0},
        samples=(
            (1, 300.0, 0, 700.0),
            (2, 200.0, 240, 710.0),
            (3, 60.03, 480, 720.0),
        ),
        post={"measured_leakage_cfm": 60.03},
    )
    report = fx.draft_report(sc)
    assert report["post_leakage_cfm25"] == 60.03
    assert report["reduction_pct_system_basis"] == reduction_pct(300.00, 60.03)
    assert report["reduction_pct_system_basis"] == 79.99
    assert report["guarantee_met"] is False

    validate_error(
        api.issue_verification_report(report["id"], f.issue_payload(), QA_HEADERS),
        ERR_GUARANTEE_NOT_MET,
        422,
    )
    assert sc.read_report(report["id"])["status"] == REPORT_DRAFT
    assert sc.read_seal_job()["status"] == JOB_SEALED


def test_a_guarantee_shortfall_leaves_the_report_untouched_in_draft(api):
    """The refusal changes nothing: no signature, no verification, no seal_status move.

    PRD 3.7: "`guarantee_met` must read true, or the issuance is refused with
    `ERR_GUARANTEE_NOT_MET`", and a successful issuance is what "moves the report to
    `ISSUED`, stamps `issued_by_user_id` with the verifier's `X-User-ID`, stamps
    `issued_at` with the logical clock".

    Design: Corner/validations/guarantee_shortfall_blocks_report_issuance_and_leaves_it_draft
    """
    sc = fx.scenario_draft_report(api, post={"measured_leakage_cfm": 90.0})
    report = sc.report
    assert report["post_leakage_cfm25"] == 90.00
    assert report["reduction_pct_system_basis"] == 70.00
    assert report["guarantee_met"] is False
    assert report["issued_by_user_id"] is None
    assert report["issued_at"] is None

    validate_error(
        api.issue_verification_report(report["id"], f.issue_payload(), QA_HEADERS),
        ERR_GUARANTEE_NOT_MET,
        422,
    )

    after = sc.read_report(report["id"])
    assert after["status"] == REPORT_DRAFT
    assert after["issued_by_user_id"] is None
    assert after["issued_at"] is None
    assert after["signature_note"] is None
    assert after["version"] == report["version"]
    assert sc.read_seal_job()["status"] == JOB_SEALED
    assert sc.read_duct_system()["seal_status"] == SEAL_STATUS_SEALED


def test_a_run_version_read_before_close_out_is_stale_at_drafting(api):
    """Closing out the run bumps its version, so the earlier read no longer matches.

    PRD 2.7: "Drafting a verification report requires a non-optional
    `expected_seal_job_version` field, carrying the `version` of the target seal job as
    the client last observed it. If that value does not equal the seal job's current
    `version`, the request is rejected with `ERR_STALE_SEAL_JOB_VERSION` and HTTP 412."

    Design: Corner/errors/a_seal_job_version_read_before_close_out_is_stale_at_report_creation
    """
    sc = fx.scenario_injecting_job(api)
    fx.stream_samples(sc)
    stale_version = sc.seal_job_version()
    fx.complete_seal(sc)
    fresh_version = sc.seal_job_version()
    assert fresh_version == stale_version + 1

    post_test = fx.add_accepted_leakage_test(
        sc, phase=PHASE_POST, measured_leakage_cfm=55.0
    )
    fx.add_combustion_test(sc, phase=PHASE_POST)

    validate_error(
        api.create_verification_report(
            f.verification_report_payload(
                sc.seal_job_id, post_test["id"], stale_version
            ),
            QA_HEADERS,
        ),
        ERR_STALE_SEAL_JOB_VERSION,
        412,
    )
    assert sc.seal_job_version() == fresh_version
    assert sc.read_seal_job()["status"] == JOB_SEALED

    report = validate_success(
        api.create_verification_report(
            f.verification_report_payload(
                sc.seal_job_id, post_test["id"], fresh_version
            ),
            QA_HEADERS,
        ),
        201,
    )
    assert report["status"] == REPORT_DRAFT
    assert report["correction_round"] == 0


def test_the_report_is_reachable_from_the_run_and_from_the_measurement(api):
    """The report carries both foreign keys and both are filter keys on the listing.

    PRD 2.5: "Verification reports can be filtered by `seal_job_id`, `post_test_id`
    and `status`." PRD 2.5 also frames why: "every relationship is discoverable in the
    reverse direction through a filtered list."

    Design: Corner/endpoints/verification_report_is_findable_from_both_ends_of_the_link_it_creates
    """
    sc = fx.scenario_issued_report(api)
    report = sc.report
    assert report["seal_job_id"] == sc.seal_job_id
    assert report["post_test_id"] == sc.post_test["id"]

    direct = validate_success(api.get_verification_report(report["id"], QA_HEADERS))
    assert direct["id"] == report["id"]
    assert direct["status"] == REPORT_ISSUED

    rows, meta = validate_paginated(
        api.list_verification_reports(QA_HEADERS, seal_job_id=sc.seal_job_id)
    )
    assert meta["total_count"] == 1 and rows[0]["id"] == report["id"]

    rows, meta = validate_paginated(
        api.list_verification_reports(QA_HEADERS, post_test_id=sc.post_test["id"])
    )
    assert meta["total_count"] == 1 and rows[0]["id"] == report["id"]

    rows, meta = validate_paginated(
        api.list_verification_reports(QA_HEADERS, status=REPORT_ISSUED)
    )
    assert meta["total_count"] == 1 and rows[0]["id"] == report["id"]

    _, meta = validate_paginated(
        api.list_verification_reports(QA_HEADERS, status=REPORT_DRAFT)
    )
    assert meta["total_count"] == 0


def test_registering_the_warranty_projects_the_retest_date_a_year_out(api):
    """The due date is 365 whole days out, and the status only lapses past it.

    PRD 3.9: "stamps `warranty_registered_at` with the logical clock, sets
    `retest_due_at` to one year — 365 whole days — after `warranty_registered_at`".
    And: "Otherwise it reads `LAPSED` when the logical clock is strictly past
    `retest_due_at`
    **and** no follow-up run pointing at this run through `retest_of_job_id` has
    reached a status of `VERIFIED` or `RETEST_CLOSED`."

    Design: Corner/calculations/warranty_registration_projects_retest_due_one_year_out_then_lapses
    """
    sc = fx.scenario_issued_report(api)
    before = sc.read_seal_job()
    assert before["warranty_status"] == WARRANTY_NOT_REGISTERED
    assert before["retest_due_at"] is None
    assert before["warranty_registered_at"] is None
    assert before["homeowner_name"] is None

    registered = validate_success(
        api.register_warranty(
            sc.seal_job_id, f.warranty_registration_payload(), ADMIN_HEADERS
        )
    )
    assert registered["homeowner_name"] == "Priya Raman"
    assert registered["warranty_registered_at"] == f.stamp(2026, 8, 1)
    assert registered["retest_due_at"] == f.stamp(2027, 8, 1)
    assert registered["warranty_status"] == WARRANTY_REGISTERED
    assert registered["warranty_suspended"] is False

    fx.set_clock(api, f.utc(2027, 8, 1))
    assert sc.read_seal_job()["warranty_status"] == WARRANTY_REGISTERED

    fx.set_clock(api, f.utc(2027, 8, 2))
    assert sc.read_seal_job()["warranty_status"] == WARRANTY_LAPSED


def test_a_retest_may_be_booked_on_the_due_date_but_not_after_it(api):
    """The re-test deadline is strict, so the due instant itself is still in time.

    PRD 3.5: "A follow-up re-test carries one further deadline: if the logical clock is
    strictly past the parent run's `retest_due_at`, the re-test can no longer be booked
    and the attempt is rejected with `ERR_RETEST_WINDOW_ELAPSED`."

    Design: Corner/validations/retest_created_after_the_warranty_window_is_refused_at_the_exact_boundary
    """
    sc = fx.scenario_issued_report(
        api, technician={"certification_expires_at": f.utc(2028, 12, 31)}
    )
    parent = sc.read_seal_job()
    registered = validate_success(
        api.register_warranty(
            parent["id"], f.warranty_registration_payload(), ADMIN_HEADERS
        )
    )
    assert registered["retest_due_at"] == f.stamp(2027, 8, 1)

    def book_retest(day, hour=9):
        payload = f.seal_job_payload(
            sc.duct_system_id,
            sc.pre_test["id"],
            sc.technician_id,
            sc.duct_system_version(),
            scheduled_start_at=f.utc(2027, 8, day, hour, 0),
            scheduled_end_at=f.utc(2027, 8, day, hour + 3, 0),
        )
        payload["retest_of_job_id"] = parent["id"]
        return api.create_seal_job(payload, sc.tech_headers)

    fx.set_clock(api, f.utc(2027, 8, 1))
    on_time = validate_success(book_retest(1), 201)
    assert on_time["retest_of_job_id"] == parent["id"]

    fx.set_clock(api, f.utc(2027, 8, 2))
    validate_error(book_retest(3), ERR_RETEST_WINDOW_ELAPSED, 409)


def test_verifying_the_retest_closes_the_parent_run_and_its_suspension(api):
    """Issuing the re-test's report reaches back through `retest_of_job_id`.

    PRD 3.7: "When the run being verified is itself a follow-up re-test — that is, when
    its `retest_of_job_id` is not null — the parent run it re-tests is moved from
    `RETEST_REQUIRED` to `RETEST_CLOSED` and that parent's `warranty_suspended` is
    cleared to false, closing the warranty loop through the self-referential link."

    Design: Corner/state_machines/retest_job_verification_bubbles_parent_job_to_retest_closed
    """
    sc = fx.scenario_submitted_claim(api)
    parent = sc.read_seal_job()
    assert parent["status"] == JOB_VERIFIED

    fx.record_spot_check(sc, spot_check_leakage_cfm=61.0)
    failed_parent = sc.read_seal_job(parent["id"])
    assert failed_parent["status"] == JOB_RETEST_REQUIRED
    assert failed_parent["warranty_suspended"] is True

    retest_payload = f.seal_job_payload(
        sc.duct_system_id,
        sc.pre_test["id"],
        sc.technician_id,
        sc.duct_system_version(),
        scheduled_start_at=f.utc(2026, 8, 5, 9, 0),
        scheduled_end_at=f.utc(2026, 8, 5, 14, 0),
    )
    retest_payload["retest_of_job_id"] = parent["id"]
    retest = validate_success(api.create_seal_job(retest_payload, sc.tech_headers), 201)

    reopened = sc.read_duct_system()
    assert reopened["seal_status"] == SEAL_STATUS_SEAL_PENDING
    assert reopened["working_leakage_cfm25"] == reopened["baseline_leakage_cfm25"]
    assert reopened["active_seal_job_id"] == retest["id"]

    fx.mask_all_registers(sc, seal_job=retest)
    fx.begin_injection(sc, seal_job=retest)
    fx.stream_samples(sc, seal_job=retest)
    sealed = fx.complete_seal(sc, seal_job=retest)
    assert sealed["status"] == JOB_SEALED

    retest_report = fx.draft_report(sc, seal_job=retest)
    issued = fx.issue_report(sc, report=retest_report)
    assert issued["status"] == REPORT_ISSUED

    assert sc.read_seal_job(retest["id"])["status"] == JOB_VERIFIED
    closed_parent = sc.read_seal_job(parent["id"])
    assert closed_parent["status"] == JOB_RETEST_CLOSED
    assert closed_parent["warranty_suspended"] is False
    assert sc.read_duct_system()["seal_status"] == SEAL_STATUS_VERIFIED
