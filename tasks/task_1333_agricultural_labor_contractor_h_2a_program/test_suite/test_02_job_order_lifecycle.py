"""Job-order lifecycle: certification gates, wage-determination supersession
and snapshot pinning, deficiency cure cycle, and OCC-guarded updates."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_job_order,
    create_application,
    create_grower,
    create_housing_unit,
    create_job_order,
    create_petition,
    create_petitioning_order,
    create_recruiting_order,
    create_wage_determination,
    create_wage_determination_payload,
    create_worker,
    approve_petition_with_workers,
    file_petition,
    get_success_data,
    link_worker,
    patch_job_order_payload,
    record_inspection,
    set_clock,
    submit_order,
    validate_error,
    validate_paginated,
    validate_success,
)

INSPECTOR = TEST_USERS["housing_inspector_headers"]

ADMIN = TEST_USERS["contractor_admin_headers"]
REVIEWER = TEST_USERS["program_reviewer_headers"]


class TestCertificationGates:
    def test_certify_from_draft_rejected(self, api):
        """PRD 3.2: "A `ProgramReviewer` may instead certify a `SUBMITTED` order,
        but only with adequate lead time: the clock date must be at least thirty
        days before `work_start_date` — a clock date exactly thirty days prior
        qualifies, one day later does not — otherwise the certification is
        rejected with `ERR_CERTIFICATION_LEAD_TIME`."
        PRD 2.9: "Fifth, the target entity must be in a state that permits the
        operation — the `ERR_JOB_ORDER_INVALID_STATE`, `ERR_PETITION_INVALID_STATE`,
        `ERR_WORKER_INVALID_STATE`, `ERR_ASSIGNMENT_INVALID_STATE`,
        `ERR_APPLICATION_INVALID_STATE`, `ERR_APPOINTMENT_INVALID_STATE`,
        `ERR_TRANSFER_INVALID_STATE`, `ERR_AUDIT_CASE_INVALID_STATE`,
        `ERR_RECONCILIATION_INVALID_STATE`, `ERR_HOUSING_UNIT_INVALID_STATE`, and
        `ERR_HOUSING_ASSIGNMENT_INVALID_STATE` family, together with
        `ERR_GROWER_NOT_ACTIVE` and `ERR_WAGE_DETERMINATION_NOT_PUBLISHED`."

        Design: Corner/state_machines/certify_from_draft_rejected
        """
        grower = create_grower()
        wd = create_wage_determination()
        jo = create_job_order(grower["id"], wd["id"])

        resp = api.certify_job_order(jo["id"], REVIEWER)
        validate_error(resp, ApiErrorId.ERR_JOB_ORDER_INVALID_STATE)
        assert get_success_data(api.get_job_order(jo["id"], ADMIN))["status"] == "DRAFT"

    def test_certify_exactly_at_lead_time_boundary(self, api):
        """PRD 3.2: "A `ProgramReviewer` may instead certify a `SUBMITTED` order,
        but only with adequate lead time: the clock date must be at least thirty
        days before `work_start_date` — a clock date exactly thirty days prior
        qualifies, one day later does not — otherwise the certification is
        rejected with `ERR_CERTIFICATION_LEAD_TIME`."

        Design: Corner/validations/certify_exactly_at_lead_time_boundary
        """
        grower = create_grower()
        wd = create_wage_determination()
        jo5 = create_job_order(grower["id"], wd["id"], title="J5", workers_requested=1)
        jo6 = create_job_order(grower["id"], wd["id"], title="J6", workers_requested=1)
        submit_order(jo5["id"])
        submit_order(jo6["id"])

        # Exactly start - 30 days (2026-09-01 - 30d = 2026-08-02): qualifies.
        set_clock("2026-08-02T00:00:00Z")
        certified = validate_success(api.certify_job_order(jo6["id"], REVIEWER), 200)
        assert certified["status"] == "CERTIFIED"

        # One day later: rejected, order stays SUBMITTED.
        set_clock("2026-08-03T00:00:00Z")
        resp = api.certify_job_order(jo5["id"], REVIEWER)
        validate_error(resp, ApiErrorId.ERR_CERTIFICATION_LEAD_TIME)
        assert get_success_data(api.get_job_order(jo5["id"], ADMIN))["status"] == "SUBMITTED"


class TestDeterminationSupersession:
    def test_superseded_determination_blocks_new_submit(self, api):
        """PRD 3.1: "Publishing a determination whose combination of state, crop,
        activity, and year matches an existing `PUBLISHED` row — with the crop
        compared case-insensitively — automatically flips the older row to
        `SUPERSEDED` and increments that row's `version`, so at most one
        determination per combination is ever `PUBLISHED`."
        PRD 3.2: "the referenced wage determination must still be `PUBLISHED` (else
        `ERR_WAGE_DETERMINATION_NOT_PUBLISHED` — a real risk after a supersession)"

        Design: Corner/validations/superseded_determination_blocks_new_submit
        """
        grower = create_grower()
        wd1 = create_wage_determination()
        jo = create_job_order(grower["id"], wd1["id"])
        wd2 = create_wage_determination(aewr_hourly_cents=1975)

        resp = api.submit_job_order(jo["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_WAGE_DETERMINATION_NOT_PUBLISHED)

        superseded, meta = validate_paginated(
            api.list_wage_determinations(REVIEWER, params={"status": "SUPERSEDED"})
        )
        assert meta["total_count"] == 1
        assert superseded[0]["id"] == wd1["id"]
        assert wd2["status"] == "PUBLISHED"

    def test_submitted_order_immune_to_determination_supersede(self, api):
        """PRD 3.2: "Once the order has been submitted at least once, the terms
        read the locked snapshots taken at submission, and superseding the
        determination afterwards leaves the order's terms unchanged."
        PRD 3.2: "While the order has never been submitted (still `DRAFT`, or in
        `DEFICIENCY` before its first submission), the wage-based terms read the
        live wage determination, so a superseding determination changes them."

        Design: Corner/validations/submitted_order_immune_to_determination_supersede
        """
        grower = create_grower()
        wd1 = create_wage_determination()
        jo0 = create_job_order(grower["id"], wd1["id"], title="J0 early")
        submit_order(jo0["id"])

        wd2 = create_wage_determination(aewr_hourly_cents=1975)
        jo2 = create_job_order(grower["id"], wd2["id"], title="J2 late")

        j0 = validate_success(api.get_job_order(jo0["id"], ADMIN), 200)
        assert j0["locked_aewr_hourly_cents"] == 1850
        assert j0["required_hourly_floor_cents"] == 1850, "submitted order is pinned to its locked snapshots"

        j2 = validate_success(api.get_job_order(jo2["id"], ADMIN), 200)
        assert j2["required_hourly_floor_cents"] == 1975, "DRAFT order reads the live determination"


class TestPatchAndOcc:
    def test_job_order_patch_occ_stale_version_rejected(self, api):
        """PRD 2.8: "Exactly one write operation in this API is version-guarded:
        updating a job order (`PATCH /h2a/job-orders/{jobOrderId}`) requires a
        non-optional `expected_job_order_version` field carrying the client's last
        observed `version` of that job order. If another writer has advanced the
        order's version since the client last read it — for instance, re-dating the
        contract period during a deficiency cure — the update is rejected with
        `ERR_STALE_JOB_ORDER_VERSION` (HTTP 412), so the client cannot overwrite an
        order it has not observed."
        PRD 3.2: "A successful update increments the order's `version` by exactly
        one and recomputes the derived terms under the live-or-locked rule above."
        PRD 3.2: "While an order is in `DRAFT` or `DEFICIENCY`, a `ContractorAdmin`
        may update it; any other status makes the update inadmissible and is
        rejected with `ERR_JOB_ORDER_INVALID_STATE`."

        Design: Corner/cross_cutting_layers/job_order_patch_occ_stale_version_rejected
        """
        grower = create_grower()
        wd = create_wage_determination()
        jo = create_job_order(grower["id"], wd["id"])
        v1 = jo["version"]

        # First patch at the observed version succeeds; floor recomputed live.
        patched = validate_success(
            api.patch_job_order(jo["id"], patch_job_order_payload(v1, offered_hourly_cents=1900), ADMIN),
            200,
        )
        assert patched["version"] == v1 + 1
        assert patched["required_hourly_floor_cents"] == 1900  # max(1850, 1775, 1900, 725)

        # Replaying the stale expected version is rejected and changes nothing.
        resp = api.patch_job_order(jo["id"], patch_job_order_payload(v1, offered_hourly_cents=2000), ADMIN)
        validate_error(resp, ApiErrorId.ERR_STALE_JOB_ORDER_VERSION)

        # After submit, PATCH is inadmissible regardless of version currency.
        submit_order(jo["id"])
        resp = api.patch_job_order(jo["id"], patch_job_order_payload(v1 + 1), ADMIN)
        validate_error(resp, ApiErrorId.ERR_JOB_ORDER_INVALID_STATE)

        current = get_success_data(api.get_job_order(jo["id"], ADMIN))
        assert current["offered_hourly_cents"] == 1900


class TestDeficiencyCureCycle:
    def test_cure_resubmit_clears_note_and_retakes_snapshots(self, api):
        """PRD 3.2: "Submitting the order moves it from `DRAFT` to `SUBMITTED`, and
        the same submission is also the cure leg of the deficiency cycle, moving a
        `DEFICIENCY` order back to `SUBMITTED`; from any other status the attempt
        is rejected with `ERR_JOB_ORDER_INVALID_STATE`."
        PRD 3.2: "On success the order snapshots `locked_aewr_hourly_cents`,
        `locked_prevailing_hourly_cents`, and
        `locked_prevailing_piece_rate_cents_per_unit` from the determination —
        re-taken fresh on every cure resubmission — and clears `deficiency_note`
        to null."

        Design: Difficulty/non_linear_state_machine/job_order_deficiency_cure_cycle
        """
        grower = create_grower()
        wd = create_wage_determination()
        jo = create_job_order(grower["id"], wd["id"])
        submit_order(jo["id"])
        flagged = validate_success(
            api.flag_job_order_deficiency(jo["id"], {"note": "missing housing addendum"}, REVIEWER), 200
        )
        assert flagged["status"] == "DEFICIENCY"
        assert flagged["deficiency_note"] == "missing housing addendum"

        cured = validate_success(api.submit_job_order(jo["id"], ADMIN), 200)
        assert_job_order(cured)
        assert cured["status"] == "SUBMITTED"
        assert cured["deficiency_note"] is None
        assert cured["locked_aewr_hourly_cents"] == 1850
        assert cured["locked_prevailing_hourly_cents"] == 1775
        assert cured["locked_prevailing_piece_rate_cents_per_unit"] == 450

    def test_cure_cycle_exits_forward_and_versions_increment(self, api):
        """PRD 3.2: "Certification moves the order to `CERTIFIED`."
        PRD 2.5: "`version` is a system-managed integer that increments with every
        modification, including modifications performed as side effects — when a
        penalty assessment suspends a grower, when a newly published wage
        determination flips its predecessor to `SUPERSEDED`, or when a withdrawal
        cascade touches dependent records, each mutated resource's `updated_at`
        refreshes and its `version` increments."

        Design: Difficulty/non_linear_state_machine/job_order_deficiency_cure_cycle
        """
        grower = create_grower()
        wd = create_wage_determination()
        jo = create_job_order(grower["id"], wd["id"])
        versions = [jo["version"]]

        versions.append(submit_order(jo["id"])["version"])
        versions.append(
            validate_success(
                api.flag_job_order_deficiency(jo["id"], {"note": "missing housing addendum"}, REVIEWER), 200
            )["version"]
        )
        versions.append(validate_success(api.submit_job_order(jo["id"], ADMIN), 200)["version"])
        certified = validate_success(api.certify_job_order(jo["id"], REVIEWER), 200)
        versions.append(certified["version"])

        assert certified["status"] == "CERTIFIED", "cycle exits forward after the cure leg"
        for before, after in zip(versions, versions[1:]):
            assert after == before + 1, f"each mutation increments version by exactly one ({before} -> {after})"


class TestTemporalGuards:
    def test_temporal_guards_dates_and_windows_rejected(self, api):
        """PRD 3.5: "An `inspected_on` later than the clock date is rejected with
        `ERR_INSPECTION_DATE_IN_FUTURE` (HTTP 400)."
        PRD 3.3: "Every application must be decided first — if any application for
        the order is still `APPLIED`, the close is rejected with
        `ERR_UNDECIDED_APPLICATIONS_REMAIN`."
        PRD 3.4: "Once at least one petition for the order is `APPROVED` (else
        `ERR_NO_APPROVED_PETITION`) and the clock date has reached
        `work_start_date` (else `ERR_ORDER_NOT_YET_STARTED`), a `ContractorAdmin`
        activates the order, moving it from `PETITIONING` to `ACTIVE`."

        Design: Corner/errors/temporal_guards_dates_and_windows_rejected
        """
        # Default clock 2026-08-01 throughout (PRD 2.4).
        grower = create_grower()
        wd = create_wage_determination()
        jo1 = create_recruiting_order(grower["id"], wd["id"], title="J1")
        create_application(jo1["id"])

        jo2 = create_petitioning_order(
            grower["id"], wd["id"], title="J2",
            work_start_date="2026-09-15", work_end_date="2026-11-03", workers_requested=2,
        )
        pet2 = create_petition(jo2["id"], receipt_code="RCPT-2", requested_worker_count=1)
        wh = create_worker(passport_number="P0009", full_name="Worker H")
        approve_petition_with_workers(pet2["id"], [wh["id"]])

        unit = create_housing_unit(grower["id"], name="U1", capacity=4)

        # Inspection dated after the clock date.
        resp = api.record_housing_inspection(
            unit["id"], {"inspected_on": "2026-08-05", "result": "PASS"}, INSPECTOR
        )
        validate_error(resp, ApiErrorId.ERR_INSPECTION_DATE_IN_FUTURE)

        # Recruitment cannot close while an application is still APPLIED.
        resp = api.close_recruitment(jo1["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_UNDECIDED_APPLICATIONS_REMAIN)
        assert get_success_data(api.get_job_order(jo1["id"], ADMIN))["status"] == "RECRUITING"

        # Activation before work_start_date even with an APPROVED petition.
        resp = api.activate_job_order(jo2["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_ORDER_NOT_YET_STARTED)
        assert get_success_data(api.get_job_order(jo2["id"], ADMIN))["status"] == "PETITIONING"
