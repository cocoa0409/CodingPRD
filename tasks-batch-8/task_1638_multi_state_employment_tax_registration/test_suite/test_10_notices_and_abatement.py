"""Agency notices and penalty abatement: severity, response tracking, resolve
guards, eligibility math, the sixty-day window, and the full-abatement waiver."""
from test_helpers import (
    ApiErrorId,
    create_abatement_request_payload,
    create_penalty_notice,
    get_employer,
    get_obligations,
    get_success_data,
    make_payroll_compliance_lead_headers,
    make_tax_director_headers,
    set_clock,
    setup_monthly_or_with_late_deposit,
    setup_withholding_registration_active,
    validate_error,
    validate_success,
)

PCL1 = "pcl-1"
DIR1 = "dir-1"


def _setup_registration_with_notice(penalty=500_000, received="2026-08-10T00:00:00Z",
                                    due="2026-09-10T00:00:00Z"):
    """QUARTERLY OR registration ACTIVE + a manual PENALTY_ASSESSMENT notice."""
    out = setup_withholding_registration_active(
        projected=200_000, account_number="OR-00000014", employee_wages=(3_000_000,),
    )
    notice = create_penalty_notice(
        penalty, received_date=received, response_due_date=due,
        registration_id=out["registration"]["id"], user_id=PCL1,
    )
    out["notice"] = notice
    return out


class TestNoticeSeverityAndResponseTracking:
    def test_notice_severity_high_at_500000_threshold(self, api):
        """PRD §3.9: "The computed `severity` is `HIGH` when the notice is an `AUDIT`
        or its penalty reaches at least 500,000 cents (five thousand dollars), `MEDIUM`
        when the penalty reaches at least 50,000 cents (five hundred dollars), and
        `LOW` otherwise."

        Design: Corner/validations/notice_resolve_blocked_by_pending_abatement
        """
        out = _setup_registration_with_notice(penalty=500_000)
        assert out["notice"]["severity"] == "HIGH", (
            "500,000 cents reaches the HIGH threshold (>= comparison)"
        )

    def test_abatement_draft_moves_notice_to_response_in_progress(self, api):
        """PRD §3.9: "Drafting an abatement request that references the notice moves
        it — from `RECEIVED` or `TRIAGED` alike — to `RESPONSE_IN_PROGRESS`."

        Design: Corner/validations/notice_resolve_blocked_by_pending_abatement
        """
        out = _setup_registration_with_notice(penalty=500_000)
        pcl = make_payroll_compliance_lead_headers(PCL1)
        get_success_data(api.triage_notice(out["notice"]["id"], pcl))
        draft = validate_success(
            api.create_abatement_request(
                create_abatement_request_payload(out["notice"]["id"]), pcl,
            ),
            201,
        )
        assert draft["status"] == "DRAFT"
        notice = get_success_data(api.get_agency_notice(out["notice"]["id"], pcl))
        assert notice["status"] == "RESPONSE_IN_PROGRESS"

    def test_notice_resolve_blocked_then_unblocked_by_withdraw(self, api):
        """PRD §3.9: "Resolution — a `PayrollComplianceLead` supplying
        `resolution_notes`, copied onto the notice — moves `TRIAGED`,
        `RESPONSE_IN_PROGRESS`, or `ESCALATED` to `RESOLVED`, but only while no linked
        AbatementRequest remains in `DRAFT`, `SUBMITTED`, or `UNDER_REVIEW`; a pending
        abatement blocks resolution with `ERR_ABATEMENT_PENDING`."

        Design: Corner/validations/notice_resolve_blocked_by_pending_abatement
        """
        out = _setup_registration_with_notice(penalty=500_000)
        notice = out["notice"]
        pcl = make_payroll_compliance_lead_headers(PCL1)
        get_success_data(api.triage_notice(notice["id"], pcl))
        draft = validate_success(
            api.create_abatement_request(
                create_abatement_request_payload(notice["id"]), pcl,
            ),
            201,
        )
        blocked = api.resolve_notice(
            notice["id"], {"resolution_notes": "Trying to close early"}, pcl,
        )
        validate_error(blocked, ApiErrorId.ERR_ABATEMENT_PENDING)
        get_success_data(api.withdraw_abatement_request(draft["id"], pcl))
        resolved = validate_success(
            api.resolve_notice(
                notice["id"],
                {"resolution_notes": "Abatement withdrawn; paid in full"},
                pcl,
            ),
            200,
        )
        assert resolved["status"] == "RESOLVED"
        assert resolved["resolution_notes"] == "Abatement withdrawn; paid in full"


class TestAbatementEligibilityGuards:
    def test_abatement_amount_exceeds_outstanding_rejected(self, api):
        """PRD §3.9: "a `requested_amount_cents` greater than zero and no more than the
        notice's outstanding penalty — `penalty_amount_cents` minus
        `abated_amount_cents` — with an excess rejected as `ERR_AMOUNT_EXCEEDS_PENALTY`"

        Design: Corner/validations/abatement_amount_exceeds_outstanding_rejected
        """
        out = _setup_registration_with_notice(penalty=500_000)
        res = api.create_abatement_request(
            create_abatement_request_payload(
                out["notice"]["id"], requested_amount_cents=500_001,
                reason="Amount deliberately one cent over",
            ),
            make_payroll_compliance_lead_headers(PCL1),
        )
        validate_error(res, ApiErrorId.ERR_AMOUNT_EXCEEDS_PENALTY)

    def test_abatement_first_time_ineligible_with_prior_penalty(self, api):
        """PRD §3.9: "`prior_penalty_count_3yr` counts `PENALTY_ASSESSMENT` notices
        whose `received_date` falls within the three years ending strictly before this
        notice's `received_date` and whose outstanding penalty is positive, examined in
        ascending `received_date` then `created_at` order."
        PRD §3.9: "`eligible_amount_cents` then depends on type: `FIRST_TIME` yields
        the full outstanding amount when that count is zero and nothing otherwise;
        `REASONABLE_CAUSE` yields the full outstanding amount; `STATUTORY` yields half
        the outstanding amount rounded down."
        PRD §3.9: "and only while `eligible_amount_cents` is greater than zero, else
        `ERR_ABATEMENT_NOT_ELIGIBLE` (a `FIRST_TIME` request with prior penalties in
        the three-year lookback is the canonical ineligible case)."

        Design: Corner/validations/abatement_first_time_ineligible_with_prior_penalty
        """
        out = setup_withholding_registration_active(
            projected=200_000, account_number="OR-00000016", employee_wages=(3_000_000,),
        )
        registration_id = out["registration"]["id"]
        create_penalty_notice(
            100_000, received_date="2026-08-10T00:00:00Z",
            response_due_date="2026-09-10T00:00:00Z",
            registration_id=registration_id, user_id=PCL1,
        )
        set_clock("2026-09-01T00:00:00Z")
        notice_a = create_penalty_notice(
            50_000, received_date="2026-09-01T00:00:00Z",
            response_due_date="2026-10-01T00:00:00Z",
            registration_id=registration_id, user_id=PCL1,
        )
        pcl = make_payroll_compliance_lead_headers(PCL1)
        draft = validate_success(
            api.create_abatement_request(
                create_abatement_request_payload(
                    notice_a["id"], abatement_type="FIRST_TIME",
                    requested_amount_cents=50_000,
                    reason="First-time abatement request",
                ),
                pcl,
            ),
            201,
        )
        assert draft["prior_penalty_count_3yr"] == 1, (
            "the 2026-08-10 notice (outstanding 100,000) falls in the 3-year lookback"
        )
        assert draft["eligible_amount_cents"] == 0
        res = api.submit_abatement_request(draft["id"], pcl)
        validate_error(res, ApiErrorId.ERR_ABATEMENT_NOT_ELIGIBLE)

    def test_abatement_submit_day_61_window_closed(self, api):
        """PRD §3.9: "Submission is windowed: a `PayrollComplianceLead` submits a
        `DRAFT` request while the current date is no later than sixty days after the
        notice's `received_date` — day sixty is allowed, day sixty-one is rejected
        with `ERR_ABATEMENT_WINDOW_CLOSED`"

        Design: Corner/validations/abatement_submit_day_61_window_closed
        """
        out = setup_monthly_or_with_late_deposit(account_number="OR-00000018")
        notice = out["notice"]  # cascade-created with received_date = 2026-09-16
        set_clock("2026-11-16T00:00:00Z")  # 2026-09-16 + 61 days
        pcl = make_payroll_compliance_lead_headers(PCL1)
        draft = validate_success(
            api.create_abatement_request(
                create_abatement_request_payload(
                    notice["id"], abatement_type="FIRST_TIME",
                    requested_amount_cents=2_500,
                    reason="First penalty in three years",
                ),
                pcl,
            ),
            201,
        )
        assert draft["eligible_amount_cents"] == 2_500, (
            "drafting is outside the window guard; eligibility is still computed"
        )
        res = api.submit_abatement_request(draft["id"], pcl)
        validate_error(res, ApiErrorId.ERR_ABATEMENT_WINDOW_CLOSED)


class TestFullAbatementConservesOutstandingPenalty:
    def test_full_abatement_grant_amounts_and_obligation_waived(self, api):
        """PRD §3.9: "Granting pins the granted amount to `eligible_amount_cents`, so
        the `granted_amount_cents` input must be omitted — supplying it draws
        `ERR_INVALID_REQUEST`."
        PRD §3.9: "Granted amounts, full or partial, are added to the notice's
        `abated_amount_cents`; when the notice links a filing obligation and the
        abatement leaves the notice's outstanding penalty at zero while that obligation
        is `LATE`, the obligation moves to `WAIVED` per §3.8; and the Employer's
        counters recompute."

        Design: Difficulty/compensating_invariant/assess_then_full_abate_conserves_outstanding_penalty
        """
        out = setup_monthly_or_with_late_deposit(account_number="OR-00000006")
        notice = out["notice"]
        pcl = make_payroll_compliance_lead_headers(PCL1)
        draft = validate_success(
            api.create_abatement_request(
                create_abatement_request_payload(
                    notice["id"], abatement_type="FIRST_TIME",
                    requested_amount_cents=2_500,
                    reason="First penalty in three years",
                ),
                pcl,
            ),
            201,
        )
        assert draft["prior_penalty_count_3yr"] == 0
        assert draft["eligible_amount_cents"] == 2_500
        get_success_data(api.submit_abatement_request(draft["id"], pcl))
        get_success_data(
            api.review_abatement_request(draft["id"], make_tax_director_headers(DIR1))
        )
        decided = validate_success(
            api.decide_abatement_request(
                draft["id"], {"decision": "GRANTED"}, make_tax_director_headers(DIR1),
            ),
            200,
        )
        assert decided["status"] == "GRANTED"
        assert decided["granted_amount_cents"] == 2_500, "pinned to eligible amount"
        notice_after = get_success_data(api.get_agency_notice(notice["id"], pcl))
        assert notice_after["abated_amount_cents"] == 2_500
        waived = get_obligations(out["registration"]["id"], status="WAIVED")
        assert len(waived) == 1
        assert waived[0]["id"] == out["late_obligation"]["id"]
        assert waived[0]["amount_due_cents"] == 38_750

    def test_full_abatement_restores_employer_outstanding_to_zero(self, api):
        """PRD §2.7: "`outstanding_penalty_cents` sums, over those open notices, each
        notice's `penalty_amount_cents` minus its `abated_amount_cents`."
        PRD §3.9: "Granted amounts, full or partial, are added to the notice's
        `abated_amount_cents`"

        Design: Difficulty/compensating_invariant/assess_then_full_abate_conserves_outstanding_penalty
        """
        out = setup_monthly_or_with_late_deposit(account_number="OR-00000006")
        employer = get_employer(out["employer"]["id"])
        assert employer["outstanding_penalty_cents"] == 2_500, (
            "the LATE cascade added the 2,500-cent provisional penalty"
        )
        notice = out["notice"]
        pcl = make_payroll_compliance_lead_headers(PCL1)
        draft = validate_success(
            api.create_abatement_request(
                create_abatement_request_payload(
                    notice["id"], abatement_type="FIRST_TIME",
                    requested_amount_cents=2_500,
                    reason="First penalty in three years",
                ),
                pcl,
            ),
            201,
        )
        get_success_data(api.submit_abatement_request(draft["id"], pcl))
        get_success_data(
            api.review_abatement_request(draft["id"], make_tax_director_headers(DIR1))
        )
        get_success_data(
            api.decide_abatement_request(
                draft["id"], {"decision": "GRANTED"}, make_tax_director_headers(DIR1),
            )
        )
        employer = get_employer(out["employer"]["id"])
        assert employer["outstanding_penalty_cents"] == 0, (
            "assess 2,500 + abate 2,500 conserves the pre-penalty baseline of zero"
        )
