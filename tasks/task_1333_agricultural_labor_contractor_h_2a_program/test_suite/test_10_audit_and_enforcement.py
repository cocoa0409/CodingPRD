"""Audit cases and enforcement: provisional vs final penalty variants, the
pinned cap-before-sum order, the debarment cascade, and grower reinstatement."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_application,
    create_audit_case,
    create_grower,
    create_job_order,
    create_petition,
    create_recruiting_order,
    create_wage_determination,
    create_worker,
    finding,
    get_success_data,
    issue_findings,
    link_worker,
    set_clock,
    setup_case_with_findings,
    submit_order,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["contractor_admin_headers"]
AUDITOR = TEST_USERS["wage_auditor_headers"]


class TestPenaltyVariants:
    def test_provisional_exposure_ignores_multiplier_cap_discount(self, api):
        """PRD 3.9: "Once findings are stored, the case's
        `provisional_exposure_cents` is computed as the sum over findings of each
        violation's base amount multiplied by its count: $1,500.00 (150,000 cents)
        per count of wage underpayment, $1,200.00 (120,000 cents) per count of
        substandard housing, $900.00 (90,000 cents) per count of transportation
        violation, $1,100.00 (110,000 cents) per count of recruitment violation,
        and $600.00 (60,000 cents) per count of recordkeeping. The provisional
        figure deliberately ignores the willful multiplier, the per-kind cap, and
        any discount."

        Design: Difficulty/dual_variant_calc/audit_exposure_provisional_vs_final_divergence
        """
        s = setup_case_with_findings(
            [finding("WAGE_UNDERPAYMENT", 3, True), finding("RECORDKEEPING", 2, False)]
        )
        case = s["case"]
        assert case["status"] == "FINDINGS_ISSUED"
        # 150000*3 + 60000*2; no willful multiplier, no cap, no discount.
        assert case["provisional_exposure_cents"] == 570000

    def test_final_penalty_applies_multiplier_cap_discount(self, api):
        """PRD 3.9: "Assessing a penalty takes a `good_faith` input and computes
        `final_penalty_cents` in a pinned evaluation order: for each violation kind
        present, the base amount is multiplied by the count and doubled when the
        finding is willful, and that per-kind total is then capped at $10,000.00
        (1,000,000 cents) before any summation; the capped kind totals are summed;
        and only then, when `good_faith` is true, the sum is reduced by ten percent
        with the result rounded half-up to a whole cent, while a non-good-faith
        assessment keeps the sum unchanged."
        PRD 3.9: "Assessment moves the case to `RESOLVED_PENALTY`, stamps
        `closed_on`, and suspends the grower: an `ACTIVE` grower moves to
        `SUSPENDED` with its `version` incremented, while a grower already
        `DEBARRED` remains `DEBARRED`."

        Design: Difficulty/dual_variant_calc/audit_exposure_provisional_vs_final_divergence
        """
        s = setup_case_with_findings(
            [finding("WAGE_UNDERPAYMENT", 3, True), finding("RECORDKEEPING", 2, False)]
        )
        assessed = validate_success(
            api.assess_penalty(s["case"]["id"], {"good_faith": True}, AUDITOR), 200
        )
        # WU kind: min(150000*3*2, 1000000) = 900000; RK kind: min(60000*2, 1000000)
        # = 120000; sum 1020000; good faith: round_half_up(1020000*90/100) = 918000.
        assert assessed["final_penalty_cents"] == 918000
        assert assessed["status"] == "RESOLVED_PENALTY"
        assert assessed["closed_on"] == "2026-08-01"  # default clock (PRD 2.4)

        grower = get_success_data(api.list_growers(AUDITOR))
        assert grower[0]["id"] == s["grower"]["id"]
        assert grower[0]["status"] == "SUSPENDED"

    def test_per_kind_cap_applies_before_summation(self, api):
        """PRD 3.9: "Any other evaluation order — discounting before capping, or
        capping after summation — yields different cents and is non-conformant."

        Design: Difficulty/combinatorial_formula/audit_penalty_per_kind_cap_order_mode_b
        """
        s = setup_case_with_findings(
            [finding("WAGE_UNDERPAYMENT", 8, True), finding("HOUSING_SUBSTANDARD", 10, True)],
            trigger_source="WAGE_DISCREPANCY",
        )
        # Provisional: 150000*8 + 120000*10, no cap.
        assert s["case"]["provisional_exposure_cents"] == 2400000

        assessed = validate_success(
            api.assess_penalty(s["case"]["id"], {"good_faith": False}, AUDITOR), 200
        )
        # Each kind capped at 1000000 BEFORE summation; cap-after-sum would give
        # 1000000 and is non-conformant.
        assert assessed["final_penalty_cents"] == 2000000

    def test_per_kind_cap_boundary_not_triggered_below_cap(self, api):
        """PRD 3.9: "Assessing a penalty takes a `good_faith` input and computes
        `final_penalty_cents` in a pinned evaluation order: for each violation kind
        present, the base amount is multiplied by the count and doubled when the
        finding is willful, and that per-kind total is then capped at $10,000.00
        (1,000,000 cents) before any summation; the capped kind totals are summed;
        and only then, when `good_faith` is true, the sum is reduced by ten percent
        with the result rounded half-up to a whole cent, while a non-good-faith
        assessment keeps the sum unchanged."

        Design: Difficulty/combinatorial_formula/audit_penalty_per_kind_cap_order_mode_b
        """
        s = setup_case_with_findings(
            [finding("RECORDKEEPING", 3, True)], trigger_source="WAGE_DISCREPANCY"
        )
        assessed = validate_success(
            api.assess_penalty(s["case"]["id"], {"good_faith": False}, AUDITOR), 200
        )
        # min(60000*3*2, 1000000) = 360000 — under the cap, so uncapped math shows.
        assert assessed["final_penalty_cents"] == 360000


class TestAuditCaseGuards:
    def test_audit_case_guard_battery_rejected(self, api):
        """PRD 3.9: "Issuing findings moves a case from `OPEN` to
        `FINDINGS_ISSUED` (from any other status, `ERR_AUDIT_CASE_INVALID_STATE`).
        The `findings` payload is a non-empty list in which every entry carries a
        `violation_code`, a `count` of at least 1, and a `willful` flag; the
        recognized violation codes are `WAGE_UNDERPAYMENT`, `HOUSING_SUBSTANDARD`,
        `TRANSPORT_VIOLATION`, `RECRUITMENT_VIOLATION`, and `RECORDKEEPING`, and an
        empty list, an unknown code, or a count below 1 is rejected with
        `ERR_INVALID_FINDINGS`."
        PRD 3.9: "Debarring a `FINDINGS_ISSUED` case requires a `debarment_years`
        term of one, two, or three years — anything outside that range is rejected
        with `ERR_INVALID_DEBARMENT_TERM` — and moves the case to
        `RESOLVED_DEBARMENT` with the term recorded and `closed_on` stamped."
        PRD 3.9: "Closing with no action moves it to `CLOSED_NO_ACTION` and stamps
        `closed_on` with the clock date."

        Design: Corner/errors/audit_case_guard_battery_rejected
        """
        grower = create_grower()
        case = create_audit_case(grower["id"], "MANUAL")

        # assess-penalty requires FINDINGS_ISSUED; the case is OPEN.
        resp = api.assess_penalty(case["id"], {"good_faith": False}, AUDITOR)
        validate_error(resp, ApiErrorId.ERR_AUDIT_CASE_INVALID_STATE)

        # Unknown violation code.
        resp = api.issue_findings(
            case["id"], {"findings": [finding("BOGUS_CODE", 1, False)]}, AUDITOR
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_FINDINGS)

        issued = issue_findings(case["id"], [finding("RECORDKEEPING", 1, False)])
        assert issued["provisional_exposure_cents"] == 60000

        # Debarment term outside 1..3.
        resp = api.debar_grower(case["id"], {"debarment_years": 5}, AUDITOR)
        validate_error(resp, ApiErrorId.ERR_INVALID_DEBARMENT_TERM)

        closed = validate_success(api.close_audit_case_no_action(case["id"], AUDITOR), 200)
        assert closed["status"] == "CLOSED_NO_ACTION"
        assert closed["closed_on"] == "2026-08-01"

        # Terminal lockdown.
        resp = api.issue_findings(
            case["id"], {"findings": [finding("RECORDKEEPING", 1, False)]}, AUDITOR
        )
        validate_error(resp, ApiErrorId.ERR_AUDIT_CASE_INVALID_STATE)


class TestDebarment:
    def _debarment_cascade_setup(self, api):
        """G1 with J3 (2026-09-01..2026-09-20) in RECRUITING: one APPLIED
        application, one DRAFT petition with a linked (PETITIONED) worker, and a
        FINDINGS_ISSUED audit case; clock parked at 2026-08-10."""
        grower = create_grower()
        wd = create_wage_determination()
        jo3 = create_recruiting_order(
            grower["id"], wd["id"], title="J3 short harvest",
            work_end_date="2026-09-20", workers_requested=8,
        )
        app = create_application(jo3["id"])
        pet3 = create_petition(jo3["id"], receipt_code="RCPT-3", requested_worker_count=1)
        wp = create_worker(passport_number="P0010", full_name="Worker P")
        link_worker(pet3["id"], wp["id"])
        case = create_audit_case(grower["id"], "HOUSING")
        issue_findings(case["id"], [finding("HOUSING_SUBSTANDARD", 2, False)])
        set_clock("2026-08-10T00:00:00Z")
        return {"grower": grower, "jo3": jo3, "app": app, "pet3": pet3, "wp": wp, "case": case}

    def test_debarment_sets_grower_status_and_term(self, api):
        """PRD 3.9: "The grower then becomes `DEBARRED`, whether it stood at
        `ACTIVE` or `SUSPENDED`, with `debarment_ends_on` set to the clock date
        plus the debarment term at 365 days per year."
        PRD 3.9: "Debarring a `FINDINGS_ISSUED` case requires a `debarment_years`
        term of one, two, or three years — anything outside that range is rejected
        with `ERR_INVALID_DEBARMENT_TERM` — and moves the case to
        `RESOLVED_DEBARMENT` with the term recorded and `closed_on` stamped."

        Design: Difficulty/transitive_cascade/debarment_four_hop_withdrawal_cascade
        """
        s = self._debarment_cascade_setup(api)

        resolved = validate_success(
            api.debar_grower(s["case"]["id"], {"debarment_years": 1}, AUDITOR), 200
        )
        assert resolved["status"] == "RESOLVED_DEBARMENT"
        assert resolved["debarment_years"] == 1
        assert resolved["closed_on"] == "2026-08-10"

        rows, meta = validate_paginated(api.list_growers(AUDITOR))
        assert meta["total_count"] == 1
        assert rows[0]["status"] == "DEBARRED"
        # clock 2026-08-10 + 1 year * 365 days.
        assert rows[0]["debarment_ends_on"] == "2027-08-10"

    def test_debarment_withdrawal_cascade_reaches_worker_and_application(self, api):
        """PRD 3.9: "Debarment cascades through the grower's book of business:
        every job order of the grower in `DRAFT`, `SUBMITTED`, `DEFICIENCY`,
        `CERTIFIED`, or `RECRUITING` moves to `WITHDRAWN`, and each such withdrawal
        cascades exactly as a manual withdrawal does — the order's petitions in
        `DRAFT` move to `WITHDRAWN`, workers linked to those petitions in
        `PETITIONED` status revert to `REGISTERED` with `petition_id` cleared to
        null, and the order's domestic applications still in `APPLIED` move to
        `WITHDRAWN`."

        Design: Difficulty/transitive_cascade/debarment_four_hop_withdrawal_cascade
        """
        s = self._debarment_cascade_setup(api)
        validate_success(api.debar_grower(s["case"]["id"], {"debarment_years": 1}, AUDITOR), 200)

        assert get_success_data(api.get_job_order(s["jo3"]["id"], AUDITOR))["status"] == "WITHDRAWN"

        petitions, _ = validate_paginated(api.list_visa_petitions(s["jo3"]["id"], AUDITOR))
        assert petitions[0]["status"] == "WITHDRAWN"

        worker = get_success_data(api.get_worker(s["wp"]["id"], AUDITOR))
        assert worker["status"] == "REGISTERED"
        assert worker["petition_id"] is None

        apps, _ = validate_paginated(api.list_domestic_applications(s["jo3"]["id"], AUDITOR))
        assert apps[0]["status"] == "WITHDRAWN"

    def test_debarred_grower_submit_rejected_then_reinstated(self, api):
        """PRD 3.2: "Three further preconditions guard submission, in the priority
        order of §2.9: the grower must be `ACTIVE` (else `ERR_GROWER_NOT_ACTIVE`),
        the referenced wage determination must still be `PUBLISHED` (else
        `ERR_WAGE_DETERMINATION_NOT_PUBLISHED` — a real risk after a supersession),
        and `work_end_date` must not fall before `work_start_date` (else
        `ERR_INVALID_DATE_RANGE`)."
        PRD 3.1: "a `SUSPENDED` grower returns to `ACTIVE` once no audit case for
        that grower remains in `OPEN` or `FINDINGS_ISSUED`, and a `DEBARRED` grower
        returns to `ACTIVE` once the clock date has reached `debarment_ends_on` —
        reaching it exactly is sufficient — with `debarment_ends_on` cleared back
        to null. If neither rule applies, the refresh simply returns the grower
        unchanged with a 200 response."

        Design: Corner/errors/debarred_grower_submit_rejected_then_reinstated
        """
        grower = create_grower()
        case = create_audit_case(grower["id"], "MANUAL")
        issue_findings(case["id"], [finding("WAGE_UNDERPAYMENT", 1, True)])
        # Default clock 2026-08-01; one year -> debarment_ends_on 2027-08-01.
        validate_success(api.debar_grower(case["id"], {"debarment_years": 1}, AUDITOR), 200)

        wd = create_wage_determination()
        jo9 = create_job_order(grower["id"], wd["id"], title="J9 next season", workers_requested=1)

        resp = api.submit_job_order(jo9["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_GROWER_NOT_ACTIVE)

        # Refresh before the term ends is a no-op 200.
        unchanged = validate_success(api.refresh_grower_status(grower["id"], AUDITOR), 200)
        assert unchanged["status"] == "DEBARRED"

        # At exactly debarment_ends_on (inclusive) the grower reinstates.
        set_clock("2027-08-01T00:00:00Z")
        reinstated = validate_success(api.refresh_grower_status(grower["id"], AUDITOR), 200)
        assert reinstated["status"] == "ACTIVE"
        assert reinstated["debarment_ends_on"] is None

        submitted = validate_success(api.submit_job_order(jo9["id"], ADMIN), 200)
        assert submitted["status"] == "SUBMITTED"
