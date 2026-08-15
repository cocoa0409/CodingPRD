"""Cross-entity cascades and season reporting: the depth-3 site-suspension
cascade, the provisional-vs-final refund divergence, first-pass vs
final-resolution report rates, the goal_met threshold, and the close guard."""
from test_helpers import (
    DAY2_END,
    DAY2_START,
    DAY3_END,
    DAY3_START,
    ApiErrorId,
    accept_return,
    api_client,
    assert_tax_return,
    begin_preparation,
    create_intake_return,
    create_verified_taxpayer,
    drive_return_to_accepted,
    drive_return_to_qr_passed,
    generate_report,
    get_return,
    list_referrals,
    offer_referral,
    patch_return,
    reject_return,
    resolve_rejection,
    review_pass,
    rework_rejected_return,
    schedule_appointment,
    setup_staffed_site,
    submit_for_review,
    transition_site,
    transmit_return,
    validate_error,
    validate_success,
)


def _suspend_scenario(ctx):
    """Return R in INTAKE_STARTED (origin appointment CHECKED_IN) with an
    OFFERED referral, plus a second SCHEDULED appointment for another
    taxpayer. Returns (appt1, ret1, referral, appt2)."""
    tp1 = create_verified_taxpayer(ctx.scr_headers, full_name="Tp One",
                                   ssn_token="SSN-101", phone="555-1101")
    appt1, ret1 = create_intake_return(ctx, tp1["id"],
                                       appt_kwargs={"purpose": "INTAKE"})
    referral = offer_referral(ret1["id"], ctx.prep_headers, "CREDIT_COUNSELING")
    tp2 = create_verified_taxpayer(ctx.scr_headers, full_name="Tp Two",
                                   ssn_token="SSN-102", phone="555-1102",
                                   id_document_type="PASSPORT")
    appt2 = schedule_appointment(ctx, tp2["id"], ctx.preparer["id"],
                                 start_at=DAY2_START, end_at=DAY2_END,
                                 purpose="INTAKE")
    return appt1, ret1, referral, appt2


class TestSiteSuspendCascade:
    def test_suspend_cancels_appointments_and_withdraws_return(self, api):
        """PRD §3.1: "Suspending an `OPEN` site is always permitted and
        carries the system's deepest cascade, in three links. Link one: every
        appointment of the site in `SCHEDULED` or `CHECKED_IN` status is
        cancelled. Link two: each appointment cancelled by link one that
        originated a tax return still in `INTAKE_STARTED` causes that return
        to be withdrawn, with `withdrawal_reason` recorded as
        `SITE_SUSPENDED`."

        Design: Difficulty/transitive_cascade/site_suspend_cascade_depth3
        """
        ctx = setup_staffed_site()
        appt1, ret1, referral, appt2 = _suspend_scenario(ctx)

        site = transition_site(ctx.site_id, "SUSPENDED", ctx.coord_headers)
        assert site["status"] == "SUSPENDED"

        appt1 = validate_success(api.get_appointment(appt1["id"], ctx.coord_headers))
        assert appt1["status"] == "CANCELLED", "link 1: CHECKED_IN -> CANCELLED"
        appt2 = validate_success(api.get_appointment(appt2["id"], ctx.coord_headers))
        assert appt2["status"] == "CANCELLED", "link 1: SCHEDULED -> CANCELLED"

        ret1 = get_return(ret1["id"], ctx.coord_headers)
        assert_tax_return(ret1)
        assert ret1["status"] == "WITHDRAWN", "link 2: the INTAKE_STARTED return"
        assert ret1["withdrawal_reason"] == "SITE_SUSPENDED"

    def test_suspend_voids_referral(self, api):
        """PRD §3.1: "Link three: each return withdrawn by link two voids its
        financial-service referrals still in `OFFERED` or `ACCEPTED`, moving
        them to `VOID`."

        Design: Difficulty/transitive_cascade/site_suspend_cascade_depth3
        """
        ctx = setup_staffed_site()
        appt1, ret1, referral, appt2 = _suspend_scenario(ctx)
        assert referral["status"] == "OFFERED"

        transition_site(ctx.site_id, "SUSPENDED", ctx.coord_headers)

        referrals = list_referrals(ret1["id"], ctx.coord_headers)
        assert len(referrals) == 1
        assert referrals[0]["id"] == referral["id"]
        assert referrals[0]["status"] == "VOID", "link 3: referral voided"


class TestRefundVariantDivergence:
    def _patched_return(self, ctx):
        tp = create_verified_taxpayer(ctx.scr_headers, full_name="Taxpayer One",
                                      ssn_token="SSN-001", phone="555-0101")
        appt, ret = create_intake_return(ctx, tp["id"])
        ret = patch_return(
            ret, ctx.prep_headers,
            documents_received=["PHOTO_ID", "SSN_CARD", "W2", "BANK_INFO"],
            interview_confirmed=True,
            wages_cents=2000000, other_income_cents=0,
            earned_income_cents=2000000, qualifying_children=1,
            withholding_reported_cents=150000,
            withholding_verified_cents=150000,
            refund_method="DIRECT_DEPOSIT",
        )
        return ret

    def test_estimate_uses_provisional_variant(self, api):
        """PRD §3.4: "The provisional estimate shown at intake deliberately
        assumes zero tax liability and trusts self-reported withholding:
        `estimated_refund_cents` is the taxpayer-reported
        `withholding_reported_cents` plus an estimated earned-income credit
        equal to the lesser of 15 percent of `earned_income_cents` — the
        multiplication rounded half-up to whole cents — and $6,000."

        Design: Difficulty/dual_variant_calc/refund_estimate_vs_final_diverge
        """
        ctx = setup_staffed_site()
        ret = self._patched_return(ctx)
        # 150000 + min(round_half_up(0.15 * 2000000) = 300000, 600000)
        assert ret["estimated_refund_cents"] == 450000

    def test_final_variant_diverges_on_identical_inputs(self, api):
        """PRD §3.5: "First, tier selection on `qualifying_children`: with no
        qualifying children the credit rate is 10 percent and its cap is
        $600; with one qualifying child the rate is 20 percent and the cap is
        $4,000; with two or more the rate is 25 percent and the cap is
        $6,500. Second, the final earned-income credit is the lesser of the
        tier rate multiplied by `earned_income_cents` — the multiplication
        rounded half-up to whole cents — and the tier cap. Third, the tax
        liability is 12 percent of the sum of `wages_cents` and
        `other_income_cents`, rounded half-up to whole cents. Finally,
        `final_refund_cents` is the verified withholding plus the final
        credit minus the liability, floored at zero. Because the rate
        structure and the liability treatment differ from the provisional
        variant, identical inputs generally produce a different figure than
        the intake estimate."
        PRD §3.5: "Each entry into `PENDING_QR` computes the binding
        `final_refund_cents`; before the first submission the field is null."

        Design: Difficulty/dual_variant_calc/refund_estimate_vs_final_diverge
        """
        ctx = setup_staffed_site()
        ret = self._patched_return(ctx)
        assert ret["estimated_refund_cents"] == 450000
        assert ret["final_refund_cents"] is None

        ret = begin_preparation(ret)
        ret = submit_for_review(ret)
        # eitc = min(round(0.20 * 2000000) = 400000, 400000); liability =
        # round(0.12 * 2000000) = 240000; refund = 150000 + 400000 - 240000
        assert ret["final_refund_cents"] == 310000
        assert ret["final_refund_cents"] != ret["estimated_refund_cents"], (
            "identical inputs produce a different figure under the final variant"
        )


class TestReportRateDivergence:
    def _three_ack_outcomes(self, ctx):
        """Return A accepted on first acknowledgement; return B rejected,
        resolved, reworked, re-transmitted, accepted; return C transmitted
        then rejected and left open. All PAPER_CHECK."""
        tp_a = create_verified_taxpayer(ctx.scr_headers, full_name="Tp A",
                                        ssn_token="SSN-A", phone="555-1001",
                                        id_document_type="PASSPORT")
        drive_return_to_accepted(ctx, tp_a["id"])

        tp_b = create_verified_taxpayer(ctx.scr_headers, full_name="Tp B",
                                        ssn_token="SSN-B", phone="555-1002",
                                        id_document_type="STATE_ID")
        appt_b, ret_b = drive_return_to_qr_passed(
            ctx, tp_b["id"], appt_kwargs={"start_at": DAY2_START, "end_at": DAY2_END}
        )
        ret_b = transmit_return(ret_b, ctx.coord_headers)
        ret_b = reject_return(ret_b, ctx.coord_headers,
                              "R0000-503", "Spouse SSN mismatch")
        rejections = validate_success(
            api_client.list_efile_rejections(ret_b["id"], ctx.rev_headers)
        )
        resolve_rejection(rejections[0]["id"], ctx.rev_headers,
                          resolution_note="Taxpayer confirmed SSN; corrected")
        ret_b = rework_rejected_return(ret_b)
        ret_b = submit_for_review(ret_b)
        ret_b = review_pass(ret_b, ctx.reviewer["id"])
        ret_b = transmit_return(ret_b, ctx.coord_headers)
        ret_b = accept_return(ret_b, ctx.coord_headers)
        assert ret_b["status"] == "ACCEPTED"

        tp_c = create_verified_taxpayer(ctx.scr_headers, full_name="Tp C",
                                        ssn_token="SSN-C", phone="555-1003",
                                        id_document_type="MILITARY_ID")
        appt_c, ret_c = drive_return_to_qr_passed(
            ctx, tp_c["id"],
            appt_kwargs={"start_at": DAY3_START, "end_at": DAY3_END},
            return_overrides={"filing_status": "HEAD_OF_HOUSEHOLD"},
            patch_overrides={"wages_cents": 800000, "earned_income_cents": 800000,
                             "withholding_reported_cents": 50000,
                             "withholding_verified_cents": 50000},
        )
        ret_c = transmit_return(ret_c, ctx.coord_headers)
        ret_c = reject_return(ret_c, ctx.coord_headers,
                              "IND-507", "Dependent already claimed")
        assert ret_c["status"] == "REJECTED"

    def test_report_counts_three_transmission_outcomes(self, api):
        """PRD §3.9: "`returns_prepared_count` counts returns whose
        `reached_preparation` is true; `returns_transmitted_count` counts
        returns with a `submission_count` of at least one;
        `returns_accepted_count` counts returns in `ACCEPTED` or `COMPLETED`"
        PRD §3.9: "and `first_pass_accepted_count` counts returns whose
        `first_ack_outcome` is `ACCEPTED`."

        Design: Difficulty/dual_variant_calc/report_first_pass_vs_final_resolution_diverge
        """
        ctx = setup_staffed_site()
        self._three_ack_outcomes(ctx)

        report = generate_report(ctx.site_id, ctx.coord_headers)
        assert report["returns_transmitted_count"] == 3
        assert report["first_pass_accepted_count"] == 1, (
            "only return A's first acknowledgement was an acceptance"
        )
        assert report["returns_accepted_count"] == 2, "returns A and B"

    def test_report_rates_diverge_on_identical_data(self, api):
        """PRD §3.9: "Two acceptance rates, reported in basis points as
        integers rounded half-up, measure e-file quality from different
        angles; both are null when no return of the site has ever been
        transmitted. `first_pass_acceptance_rate_bp` is the first-pass
        accepted count multiplied by ten thousand and divided by the
        transmitted count: its numerator credits only returns whose first
        acknowledgement was an acceptance, so a return rejected on first
        acknowledgement and later accepted contributes nothing here.
        `final_resolution_rate_bp` divides the accepted-or-completed count by
        the same denominator, crediting eventual success regardless of
        first-pass history"

        Design: Difficulty/dual_variant_calc/report_first_pass_vs_final_resolution_diverge
        """
        ctx = setup_staffed_site()
        self._three_ack_outcomes(ctx)

        report = generate_report(ctx.site_id, ctx.coord_headers)
        # round_half_up(1 * 10000 / 3) and round_half_up(2 * 10000 / 3)
        assert report["first_pass_acceptance_rate_bp"] == 3333
        assert report["final_resolution_rate_bp"] == 6667
        assert report["first_pass_acceptance_rate_bp"] != report["final_resolution_rate_bp"]


class TestGoalMetThreshold:
    def test_goal_met_threshold(self, api, sponsor_admin_headers):
        """PRD §3.1: "Throughout the season the site tracks its progress
        live: its `accepted_count` is the number of its tax returns currently
        in `ACCEPTED` or `COMPLETED` status, and its `goal_met` flag turns
        true once `accepted_count` reaches `goal_returns`."

        Design: Corner/cross_cutting_complexity_layers/goal_met_threshold
        """
        ctx = setup_staffed_site(goal_returns=1)
        tp = create_verified_taxpayer(ctx.scr_headers, full_name="Tp GM",
                                      ssn_token="SSN-GM1", phone="555-2035")
        appt, ret = drive_return_to_qr_passed(ctx, tp["id"])

        site = validate_success(api.get_site(ctx.site_id, sponsor_admin_headers))
        assert site["accepted_count"] == 0
        assert site["goal_met"] is False

        ret = transmit_return(ret, ctx.coord_headers)
        ret = accept_return(ret, ctx.coord_headers)

        site = validate_success(api.get_site(ctx.site_id, sponsor_admin_headers))
        assert site["accepted_count"] == 1
        assert site["goal_met"] is True, "inclusive threshold: 1 >= 1"


class TestCloseGuard:
    def test_close_site_with_open_work_rejected(self, api):
        """PRD §3.1: "Closing a site, from either `OPEN` or `SUSPENDED`, is
        guarded by an open-work check: the site must have no appointments in
        `SCHEDULED` or `CHECKED_IN`, and no tax returns in `INTAKE_STARTED`,
        `IN_PREPARATION`, `PENDING_QR`, `QR_FAILED`, `QR_PASSED`,
        `TRANSMITTED`, or `REJECTED`. Any such open work blocks closure with
        `ERR_SITE_HAS_OPEN_WORK`."

        Design: Corner/validations/close_site_with_open_work_rejected
        """
        ctx = setup_staffed_site()
        tp = create_verified_taxpayer(ctx.scr_headers, full_name="Tp CW",
                                      ssn_token="SSN-CW1", phone="555-2020")
        appt, ret = create_intake_return(ctx, tp["id"],
                                         appt_kwargs={"purpose": "INTAKE"})

        resp = api.transition_site(ctx.site_id, "CLOSED", ctx.coord_headers)
        validate_error(resp, ApiErrorId.ERR_SITE_HAS_OPEN_WORK)
        site = validate_success(api.get_site(ctx.site_id, ctx.coord_headers))
        assert site["status"] == "OPEN"
