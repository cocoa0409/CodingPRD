"""Agreement enrollment, FMV review, cooling-off, freshness, cap, and SoD."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_physician_agreement,
    create_active_plan,
    create_agreement,
    create_fmv_approved_agreement,
    create_fmv_approved_plan,
    fmv_review_payload,
    get_success_data,
    make_compliance_officer_headers,
    register_physician,
    set_clock,
    setup_active_plan_with_effective_agreement,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["system_admin_headers"]
ANALYST = TEST_USERS["analyst_headers"]
OFFICER = TEST_USERS["compliance_officer_headers"]
COMMITTEE = TEST_USERS["committee_headers"]


class TestAgreementCreation:
    def test_computed_fields_ignored_and_pin_snapshot(self, api):
        """PRD §3.3: "At creation the agreement snapshots the plan's current `version` into `pinned_plan_version` — version-pinning on approval — and records the caller's `X-User-ID` as `created_by_user_id` for later segregation-of-duties checks."
        PRD §3.3: "A new agreement sits in `DRAFT`."
        PRD §3.4: "the owning agreement's `ytd_wrvu_credited` (the running sum of `credited_wrvu` over the agreement's `CREDITED` captures, kept at 2 decimal places)"
        PRD §3.7: "The pending field is 0 from agreement creation until a true-up run posts over it"

        Design: Corner/entities/agreement_computed_ytd_input_ignored
        """
        set_clock()
        physician = register_physician(npi="1000000203", full_name="Dr Computed")
        plan, _ = create_active_plan(name="Snap Plan")
        agreement = create_agreement(
            physician["id"], plan["id"], extra_fields={"ytd_wrvu_credited": 999.99}
        )
        assert_physician_agreement(agreement)
        assert float(agreement["ytd_wrvu_credited"]) == 0.00, (
            "no CREDITED captures exist at creation, so the running sum is 0 — a "
            "client-supplied computed value must not take effect"
        )
        assert agreement["pinned_plan_version"] == plan["version"], (
            "creation snapshots the plan's current version"
        )
        assert agreement["status"] == "DRAFT"
        assert agreement["lifetime_paid_cents"] == 0
        assert agreement["pending_trueup_adjustment_cents"] == 0
        assert plan["version"] > 1, "plan version advanced through review and activation"

    def test_duplicate_agreement_rejected(self, api):
        """PRD §3.3: "Only one non-terminal agreement may exist per physician-and-plan pair, so a duplicate enrollment for the same `physician_id` and `plan_id` while an earlier agreement is still `DRAFT`, `PENDING_FMV`, `FMV_APPROVED`, `EFFECTIVE`, or `AMENDMENT_REQUIRED` is rejected with `ERR_DUPLICATE_RESOURCE`."

        Design: Corner/validations/duplicate_agreement_rejected
        """
        set_clock()
        physician = register_physician(npi="1000000232", full_name="Dr Dup")
        plan, _ = create_active_plan(name="Dup Plan")
        first = create_agreement(physician["id"], plan["id"])
        assert first["status"] == "DRAFT"
        resp = api.create_agreement(
            {
                "physician_id": physician["id"],
                "plan_id": plan["id"],
                "base_salary_cents": 25000000,
                "period_draw_cents": 1100000,
                "effective_date": "2026-01-01",
            },
            ANALYST,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_RESOURCE)


class TestAgreementActivationGates:
    def test_activation_blocked_until_plan_active(self, api):
        """PRD §3.3: "Activation moves an `FMV_APPROVED` agreement to `EFFECTIVE` and is guarded by four checks in ladder order after existence and state: the referenced plan must be `ACTIVE` (`ERR_PLAN_NOT_ACTIVE`)"

        Design: Difficulty/cross_entity_state_dependency/agreement_activation_requires_plan_active
        """
        set_clock()
        physician = register_physician(npi="1000000080", full_name="Dr Gate")
        plan, _ = create_fmv_approved_plan(name="Gate Plan")
        agreement = create_fmv_approved_agreement(physician["id"], plan["id"])
        resp = api.activate_agreement(agreement["id"], COMMITTEE)
        validate_error(resp, ApiErrorId.ERR_PLAN_NOT_ACTIVE)

    def test_activation_succeeds_once_plan_active(self, api):
        """PRD §3.3: "The referenced plan must be `FMV_APPROVED` or `ACTIVE`; enrolling against a plan in any other status is rejected with `ERR_PLAN_NOT_ACTIVE`."
        PRD §3.3: "Activation moves an `FMV_APPROVED` agreement to `EFFECTIVE`"

        Design: Difficulty/cross_entity_state_dependency/agreement_activation_requires_plan_active
        """
        set_clock()
        physician = register_physician(npi="1000000080", full_name="Dr Gate")
        plan, _ = create_fmv_approved_plan(name="Gate Plan")
        agreement = create_fmv_approved_agreement(physician["id"], plan["id"])
        resp_blocked = api.activate_agreement(agreement["id"], COMMITTEE)
        validate_error(resp_blocked, ApiErrorId.ERR_PLAN_NOT_ACTIVE)
        get_success_data(api.activate_plan(plan["id"], COMMITTEE))
        activated = validate_success(api.activate_agreement(agreement["id"], COMMITTEE), 200)
        assert activated["status"] == "EFFECTIVE"

    def test_state_check_beats_fiscal_cap(self, api):
        """PRD §3.3: "Activation moves an `FMV_APPROVED` agreement to `EFFECTIVE` and is guarded by four checks in ladder order after existence and state: the referenced plan must be `ACTIVE` (`ERR_PLAN_NOT_ACTIVE`); the FMV review must still be fresh, meaning the logical clock is no later than twelve months after `fmv_reviewed_at`, otherwise `ERR_FMV_STALE`; and the FMV cap must hold — the agreement's `base_salary_cents` plus its projected annual productivity at the current year-to-date pace must not exceed the plan's `fmv_cap_cents`, otherwise `ERR_FMV_CAP_EXCEEDED`."
        PRD §2.9: "The fiscal FMV cap (`ERR_FMV_CAP_EXCEEDED`) is evaluated last."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_agreement_activation
        """
        set_clock()
        physician = register_physician(npi="1000000050", full_name="Dr Pricy",
                                       specialty="cards")
        plan, _ = create_fmv_approved_plan(name="Cap Plan")
        agreement = create_fmv_approved_agreement(
            physician["id"], plan["id"], benchmark_percentile=90, base_salary_cents=95000000
        )
        resp = api.activate_agreement(agreement["id"], COMMITTEE)
        err = validate_error(resp, ApiErrorId.ERR_PLAN_NOT_ACTIVE)
        assert resp.status_code == 409
        assert err["error_id"] != "ERR_FMV_CAP_EXCEEDED", (
            "base_salary 95000000 > fmv_cap 90000000 also holds, but the state rule "
            "sits earlier on the validation ladder"
        )

    def test_state_check_leaves_agreement_unchanged(self, api):
        """PRD §3.3: "the referenced plan must be `ACTIVE` (`ERR_PLAN_NOT_ACTIVE`)"
        PRD §2.9: "The fiscal FMV cap (`ERR_FMV_CAP_EXCEEDED`) is evaluated last."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_agreement_activation
        """
        set_clock()
        physician = register_physician(npi="1000000050", full_name="Dr Pricy",
                                       specialty="cards")
        plan, _ = create_fmv_approved_plan(name="Cap Plan")
        agreement = create_fmv_approved_agreement(
            physician["id"], plan["id"], benchmark_percentile=90, base_salary_cents=95000000
        )
        validate_error(
            api.activate_agreement(agreement["id"], COMMITTEE),
            ApiErrorId.ERR_PLAN_NOT_ACTIVE,
        )
        after = get_success_data(api.get_agreement(agreement["id"], ANALYST))
        assert after["status"] == "FMV_APPROVED", "a rejected activation changes nothing"

    def test_fmv_cap_exceeded_at_activation(self, api):
        """PRD §3.3: "the FMV cap must hold — the agreement's `base_salary_cents` plus its projected annual productivity at the current year-to-date pace must not exceed the plan's `fmv_cap_cents`, otherwise `ERR_FMV_CAP_EXCEEDED`."

        Design: Corner/validations/fmv_cap_exceeded_at_activation
        """
        set_clock()
        physician = register_physician(npi="1000000245", full_name="Dr CapX",
                                       specialty="cards")
        plan, _ = create_active_plan(name="CapX Plan")
        agreement = create_fmv_approved_agreement(
            physician["id"], plan["id"], benchmark_percentile=95, base_salary_cents=95000000
        )
        resp = api.activate_agreement(agreement["id"], COMMITTEE)
        validate_error(resp, ApiErrorId.ERR_FMV_CAP_EXCEEDED)
        after = get_success_data(api.get_agreement(agreement["id"], ANALYST))
        assert after["status"] == "FMV_APPROVED"

    def test_fmv_stale_blocks_activation(self, api):
        """PRD §3.3: "the FMV review must still be fresh, meaning the logical clock is no later than twelve months after `fmv_reviewed_at`, otherwise `ERR_FMV_STALE`"

        Design: Corner/validations/fmv_stale_blocks_activation
        """
        set_clock()
        physician = register_physician(npi="1000000246", full_name="Dr StaleA")
        plan, _ = create_active_plan(name="StaleA Plan", rates=[{
            "cpt_code": "99213", "wrvu_value": 0.97,
            "effective_from": "2026-01-01", "effective_to": "2028-01-01",
        }])
        agreement = create_fmv_approved_agreement(physician["id"], plan["id"])
        set_clock("2027-02-01T00:00:00Z")
        resp = api.activate_agreement(agreement["id"], COMMITTEE)
        validate_error(resp, ApiErrorId.ERR_FMV_STALE)


class TestFmvReviewCycle:
    def test_rejection_starts_thirty_day_cooling_off(self, api):
        """PRD §3.3: "A `REJECTED` decision returns the agreement to `DRAFT` and stamps `last_fmv_rejected_at`, starting the thirty-day cooling-off window."
        PRD §3.3: "if the agreement's `last_fmv_rejected_at` is set and the logical-clock date falls within thirty days after it, the submission is rejected with `ERR_FMV_COOLING_OFF`; once the clock date is at least thirty days past the rejection — or no rejection was ever recorded — the submission proceeds and increments the agreement's `version`."

        Design: Corner/state_machines/agreement_fmv_reject_then_cooling_off
        """
        set_clock()
        physician = register_physician(npi="1000000213", full_name="Dr Cool")
        plan, _ = create_active_plan(name="Cool Plan")
        agreement = create_agreement(physician["id"], plan["id"])
        get_success_data(api.submit_fmv(agreement["id"], ANALYST))
        rejected = validate_success(
            api.fmv_review(agreement["id"], fmv_review_payload("REJECTED", 97), OFFICER), 200
        )
        assert rejected["status"] == "DRAFT", "rejection reverts the agreement to DRAFT"
        set_clock("2026-01-20T00:00:00Z")
        resp_early = api.submit_fmv(agreement["id"], ANALYST)
        validate_error(resp_early, ApiErrorId.ERR_FMV_COOLING_OFF)
        set_clock("2026-02-01T00:00:00Z")
        resubmitted = validate_success(api.submit_fmv(agreement["id"], ANALYST), 200)
        assert resubmitted["status"] == "PENDING_FMV", (
            "31 days after the rejection the cooling-off window has passed"
        )

    def test_reviewer_must_differ_from_creator(self, api):
        """PRD §3.3: "The reviewer's `X-User-ID` must differ from the agreement's `created_by_user_id`; a same-user decision is rejected with `ERR_SEGREGATION_OF_DUTIES`, and on this operation the state guard is evaluated before the segregation check."
        PRD §2.8: "the `ComplianceOfficer` recording an FMV decision on an agreement must not be the `CompAnalyst` whose `X-User-ID` was recorded as the agreement's `created_by_user_id`."

        Design: Corner/validations/fmv_segregation_of_duties_rejected
        """
        set_clock()
        physician = register_physician(npi="1000000242", full_name="Dr Sod")
        plan, _ = create_active_plan(name="SoD Plan")
        agreement = create_agreement(physician["id"], plan["id"])
        get_success_data(api.submit_fmv(agreement["id"], ANALYST))
        resp_same_user = api.fmv_review(
            agreement["id"], fmv_review_payload("APPROVED", 55),
            make_compliance_officer_headers("an_1"),  # same id as the creating analyst
        )
        validate_error(resp_same_user, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        approved = validate_success(
            api.fmv_review(agreement["id"], fmv_review_payload("APPROVED", 55), OFFICER), 200
        )
        assert approved["status"] == "FMV_APPROVED"

    def test_effective_agreement_reenters_fmv_review(self, api):
        """PRD §3.3: "To cure the hold, an analyst re-submits the agreement for FMV review: the re-review cycle moves an `EFFECTIVE` agreement back to `PENDING_FMV` (subject to the same cooling-off rule), and while it sits in `PENDING_FMV` it cannot accept new production captures, because posting requires `EFFECTIVE` status."

        Design: Difficulty/non_linear_state_machine/agreement_rereview_cycle
        """
        scenario = setup_active_plan_with_effective_agreement(
            npi="1000000032", plan_name="RR Plan"
        )
        agreement = scenario["agreement"]
        assert agreement["status"] == "EFFECTIVE"
        resp = api.submit_fmv(agreement["id"], ANALYST)
        pending = validate_success(resp, 200)
        assert pending["status"] == "PENDING_FMV", (
            "the re-review cycle is a loop, not a terminal lockout"
        )

    def test_rereview_loop_closes_back_to_effective(self, api):
        """PRD §3.3: "the re-review cycle moves an `EFFECTIVE` agreement back to `PENDING_FMV`"
        PRD §3.3: "An `APPROVED` decision moves the agreement `PENDING_FMV → FMV_APPROVED` and stamps `fmv_reviewed_at` with the clock timestamp, `fmv_reviewer_user_id` with the reviewer, and `fmv_benchmark_percentile` with the submitted percentile"
        PRD §3.3: "Activation moves an `FMV_APPROVED` agreement to `EFFECTIVE`"

        Design: Difficulty/non_linear_state_machine/agreement_rereview_cycle
        """
        scenario = setup_active_plan_with_effective_agreement(
            npi="1000000032", plan_name="RR Plan"
        )
        agreement = scenario["agreement"]
        get_success_data(api.submit_fmv(agreement["id"], ANALYST))
        reapproved = validate_success(
            api.fmv_review(agreement["id"], fmv_review_payload("APPROVED", 60), OFFICER), 200
        )
        assert reapproved["status"] == "FMV_APPROVED"
        assert reapproved["fmv_benchmark_percentile"] == 60, "the latest review is recorded"
        reactivated = validate_success(api.activate_agreement(agreement["id"], COMMITTEE), 200)
        assert reactivated["status"] == "EFFECTIVE", "the loop closes back to EFFECTIVE"
