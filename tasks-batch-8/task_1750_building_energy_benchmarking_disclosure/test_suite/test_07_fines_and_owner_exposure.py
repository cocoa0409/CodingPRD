"""Fine assessments, dual late-fine variants, owner standing and exposure (PRD §3.5, §3.7)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assign_verifier,
    create_and_open_cycle,
    create_owner,
    get_owner,
    make_owner_headers,
    notice_fine,
    pay_fine,
    set_clock,
    setup_late_fine_scenario,
    setup_report_scenario,
    sign_off_verification,
    create_verifier,
    submit_report,
    validate_error,
    validate_success,
    waive_fine,
)

OFFICER = TEST_USERS["officer_headers"]


class TestLateFineVariants:
    def test_late_fine_provisional_frozen_at_submission(self, api):
        """PRD §3.7: "The provisional variant, frozen onto the fine at assessment,
        measures days from the effective deadline to submission: the fine's
        `days_late` records the report's uncapped days late at that moment (for
        `NON_COMPLIANCE` and `PERFORMANCE_SHORTFALL` fines, `days_late` is always
        zero), and `provisional_amount_cents` is the smaller of `days_late` and the
        cycle's `late_fine_cap_days`, multiplied by the cycle's
        `late_fine_daily_rate_cents`."

        Submission lands 2.5 days after the deadline: 2 whole days -> 10000 cents.

        Design: Difficulty/dual_variant_calc/late_fine_provisional_vs_final_recompute
        """
        ctx = setup_late_fine_scenario(submit_clock="2027-06-03T12:00:00Z")
        fine = ctx["fine"]
        assert fine["fine_type"] == "LATE_SUBMISSION"
        assert fine["status"] == "ASSESSED"
        assert fine["days_late"] == 2
        assert fine["provisional_amount_cents"] == 10000
        assert fine["final_amount_cents"] is None, "final stays null while ASSESSED"

    def test_late_fine_final_recomputed_at_notice(self, api):
        """PRD §3.7: "The final variant is computed when the fine is noticed: it
        measures whole 86,400-second days from the effective deadline to the report's
        `verified_at` — or, when the report is still unverified at notice time, to
        the fine's `noticed_at` — never below zero, applies the same day cap, and
        multiplies by the same daily rate."
        PRD §3.7: "Because the final variant measures to verification rather than
        submission, identical inputs produce a larger amount whenever verification
        lands after submission."

        The report verifies 2027-06-06 (5 days past deadline): final 25000 while the
        provisional stays frozen at 10000.

        Design: Difficulty/dual_variant_calc/late_fine_provisional_vs_final_recompute
        """
        ctx = setup_late_fine_scenario(submit_clock="2027-06-03T12:00:00Z")
        verifier = create_verifier()
        record = assign_verifier(ctx["report"]["id"], verifier["id"], ctx["owner"]["id"])
        set_clock("2027-06-06T00:00:00Z")
        sign_off_verification(record["id"], verifier["id"])

        noticed = notice_fine(ctx["fine"]["id"])
        assert noticed["status"] == "NOTICED"
        assert noticed["provisional_amount_cents"] == 10000, "provisional is frozen"
        assert noticed["final_amount_cents"] == 25000, "5 days to verification * 5000"


class TestFinePayment:
    def test_payment_amount_must_match_exactly(self, api):
        """PRD §3.7: "Payment belongs to the owning `BuildingOwner` and is exact: the
        request's `paid_amount_cents` must equal the fine's `final_amount_cents` to
        the cent, and any deviation fails with `ERR_PAYMENT_AMOUNT_MISMATCH`."

        The report is still unverified at notice time, so the final variant measures
        deadline -> noticed_at: 2 days * 5000 = 10000.

        Design: Corner/validations/v_pay_amount_mismatch
        """
        ctx = setup_late_fine_scenario(submit_clock="2027-06-03T12:00:00Z")
        noticed = notice_fine(ctx["fine"]["id"])
        assert noticed["final_amount_cents"] == 10000

        short = api.pay_fine(
            ctx["fine"]["id"],
            {"paid_amount_cents": 9999},
            make_owner_headers(ctx["owner"]["id"]),
        )
        validate_error(short, ApiErrorId.ERR_PAYMENT_AMOUNT_MISMATCH)

        paid = pay_fine(ctx["fine"]["id"], ctx["owner"]["id"], 10000)
        assert paid["status"] == "PAID"

    def test_paid_fine_is_terminal(self, api):
        """PRD §3.7: "A paid fine moves `NOTICED → PAID`, stamps `paid_at`, and
        recomputes exposure — which may flip the owner's standing back to `NORMAL`."
        PRD §3.7: "`PAID` and `WAIVED` are terminal."
        PRD §2.8: "The target resource's current state must allow the requested
        transition (`ERR_INVALID_STATE_TRANSITION`)."

        A second pay on the PAID fine is rejected.

        Design: Corner/state_machines/s_fine_paid_is_terminal
        """
        ctx = setup_late_fine_scenario(submit_clock="2027-06-03T12:00:00Z")
        notice_fine(ctx["fine"]["id"])
        paid = pay_fine(ctx["fine"]["id"], ctx["owner"]["id"], 10000)
        assert paid["status"] == "PAID"

        resp = api.pay_fine(
            ctx["fine"]["id"],
            {"paid_amount_cents": 10000},
            make_owner_headers(ctx["owner"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)


class TestOwnerRestrictionThreshold:
    def _owner_with_late_submit(self, submit_clock):
        ctx = setup_report_scenario()
        set_clock(submit_clock)
        ctx["report"] = submit_report(ctx["report"]["id"], ctx["owner"]["id"])
        return ctx

    def test_owner_at_exact_threshold_stays_normal(self, api):
        """PRD §3.7: "Whenever this total is strictly greater than one hundred
        thousand cents — exactly one thousand dollars, the restriction threshold —
        the owner's `standing` is `RESTRICTED`; at exactly the threshold the standing
        stays `NORMAL`, and a total at or below the threshold leaves or returns the
        owner to `NORMAL`."

        20 days late * 5000 = 100000: exactly at the threshold, not above it.

        Design: Corner/cross_cutting/x_owner_restriction_threshold_exact
        """
        ctx = self._owner_with_late_submit("2027-06-21T00:00:00Z")
        owner = get_owner(ctx["owner"]["id"])
        assert owner["outstanding_fines_cents"] == 100000
        assert owner["standing"] == "NORMAL"

    def test_owner_above_threshold_flips_restricted(self, api):
        """PRD §3.7: "Whenever this total is strictly greater than one hundred
        thousand cents — exactly one thousand dollars, the restriction threshold —
        the owner's `standing` is `RESTRICTED`; at exactly the threshold the standing
        stays `NORMAL`, and a total at or below the threshold leaves or returns the
        owner to `NORMAL`."

        21 days late * 5000 = 105000: strictly above the threshold.

        Design: Corner/cross_cutting/x_owner_restriction_threshold_exact
        """
        ctx = self._owner_with_late_submit("2027-06-22T00:00:00Z")
        owner = get_owner(ctx["owner"]["id"])
        assert owner["outstanding_fines_cents"] == 105000
        assert owner["standing"] == "RESTRICTED"

    def test_restricted_owner_cannot_submit(self, api):
        """PRD §3.5: "Finally, the building owner's `standing` must not be
        `RESTRICTED` (`ERR_OWNER_RESTRICTED`)."
        PRD §3.7: "A `RESTRICTED` owner cannot submit reports, per the fiscal gate of
        §3.5."

        The owner's first building files 24 days late (fine 120000 -> RESTRICTED);
        the second building's otherwise-valid DRAFT then hits the fiscal gate alone.

        Design: Corner/validations/v_submit_blocked_when_owner_restricted
        """
        owner = create_owner()
        cycle = create_and_open_cycle()
        ctx1 = setup_report_scenario(
            owner=owner, cycle=cycle, building_overrides={"address": "76 Main St"}
        )
        ctx2 = setup_report_scenario(
            owner=owner, cycle=cycle, building_overrides={"address": "77 Main St"}
        )
        set_clock("2027-06-25T00:00:00Z")

        first = submit_report(ctx1["report"]["id"], owner["id"])
        assert first["is_late"] is True
        assert get_owner(owner["id"])["standing"] == "RESTRICTED"

        resp = api.submit_report(ctx2["report"]["id"], make_owner_headers(owner["id"]))
        validate_error(resp, ApiErrorId.ERR_OWNER_RESTRICTED)


class TestExposureReconciliation:
    def test_waived_fine_reconciles_owner_exposure(self, api):
        """PRD §3.7: "The `outstanding_fines_cents` on the owner sums each fine's
        `final_amount_cents` when the fine is `NOTICED` and its
        `provisional_amount_cents` when the fine is `ASSESSED`; `PAID` and `WAIVED`
        fines contribute nothing."
        PRD §3.7: "A `ComplianceOfficer` may waive a fine in `ASSESSED` or `NOTICED`,
        recording a mandatory `waive_reason` (`ERR_INVALID_REQUEST` when absent); a
        waived fine moves to `WAIVED` and exposure is recomputed."

        Design: Corner/cross_cutting/x_derived_outstanding_reconciles_on_waive
        """
        ctx = setup_late_fine_scenario(submit_clock="2027-06-03T12:00:00Z")
        assert get_owner(ctx["owner"]["id"])["outstanding_fines_cents"] == 10000

        waived = waive_fine(ctx["fine"]["id"], "Clerical error in assessment")
        assert waived["status"] == "WAIVED"

        owner = get_owner(ctx["owner"]["id"])
        assert owner["outstanding_fines_cents"] == 0
        assert owner["standing"] == "NORMAL"

    def test_compliance_summary_tracks_exposure_progression(self, api):
        """PRD §3.7: "The compliance summary (§3.2) exposes two further reads built
        from the same inputs: `settled_exposure_cents`, the sum of
        `final_amount_cents` over `NOTICED` fines, representing what is enforceable
        now; and `projected_exposure_cents`, the settled amount plus the sum of
        `provisional_amount_cents` over `ASSESSED` fines, representing the worst
        case."
        PRD §3.2: "It is a computed read, not a stored entity, and it exposes:
        `covered`, the coverage determination for that cycle; `report_status`, the
        status of the building's report for the cycle or null when none exists;
        `outstanding_fines_cents`, the owner's current outstanding exposure across
        all of their buildings; `settled_exposure_cents` and
        `projected_exposure_cents`, the two exposure reads defined in §3.7;
        `latest_score_as_reported` and `latest_label_grade`, the most recent verified
        score and label, or null when the building has none; and
        `effective_deadline_at`, the deadline actually governing the building — the
        approved extension's `extended_deadline_at` when one exists, else the cycle's
        `filing_deadline_at`."

        One 10000-cent fine walked ASSESSED -> NOTICED -> PAID.

        Design: Corner/endpoints/ep_compliance_summary_exposure_progression
        """
        ctx = setup_late_fine_scenario(submit_clock="2027-06-03T12:00:00Z")
        building_id = ctx["building"]["id"]
        cycle_id = ctx["cycle"]["id"]

        summary = validate_success(api.get_compliance_summary(building_id, cycle_id, OFFICER))
        assert summary["covered"] is True
        assert summary["report_status"] == "SUBMITTED"
        assert summary["outstanding_fines_cents"] == 10000
        assert summary["settled_exposure_cents"] == 0, "nothing NOTICED yet"
        assert summary["projected_exposure_cents"] == 10000, "ASSESSED is the worst case"
        assert str(summary["effective_deadline_at"]).startswith("2027-06-01T00:00:00")

        notice_fine(ctx["fine"]["id"])
        summary = validate_success(api.get_compliance_summary(building_id, cycle_id, OFFICER))
        assert summary["settled_exposure_cents"] == 10000
        assert summary["projected_exposure_cents"] == 10000

        pay_fine(ctx["fine"]["id"], ctx["owner"]["id"], 10000)
        summary = validate_success(api.get_compliance_summary(building_id, cycle_id, OFFICER))
        assert summary["settled_exposure_cents"] == 0
        assert summary["projected_exposure_cents"] == 0
        assert summary["outstanding_fines_cents"] == 0
