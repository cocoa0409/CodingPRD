"""Statutory termination notices and the auto-renewal sweep: deadline
boundaries, the serve/withdraw cycle, compounded escalation, notice-blocked
renewal, late-notice retargeting, and the termination cascade."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    assert_iso_instant_equal,
    get_lease,
    get_notice,
    list_landlord_reports,
    list_lease_installments,
    make_landlord_headers,
    serve_notice,
    setup_active_lease,
    setup_terminated_lease_with_improvements,
    set_clock,
    validate_success,
)

MGR = TEST_USERS["farm_manager_headers"]


class TestNoticeDeadlines:
    def test_notice_served_on_deadline_is_on_time(self, api):
        """PRD §2.9: "The boundary is inclusive on the on-time side: service exactly on the deadline counts as on time. Renewal, conversely, is strict: the auto-renewal sweep renews a lease only when the clock is strictly later than `current_notice_deadline`, so a clock reading exactly equal to the deadline does not renew, and a notice served exactly on the deadline blocks renewal."
        PRD §3.9: "At service, `served_date` is stamped from the clock, the `statutory_deadline` is captured as the lease's `term_end_date` minus its `notice_lead_days`"

        Design: Corner/calculations/notice_served_on_deadline_is_on_time
        """
        ctx = setup_active_lease("CASH")  # deadline = 2028-03-01 - 180d = 2027-09-03
        set_clock("2027-09-03T00:00:00Z")
        notice = serve_notice(ctx, "LANDLORD")
        assert_iso_instant_equal(notice["statutory_deadline"], "2027-09-03T00:00:00Z")
        assert_iso_instant_equal(notice["served_date"], "2027-09-03T00:00:00Z")
        assert_iso_instant_equal(notice["effective_date"], "2028-03-01T00:00:00Z"), (
            "served exactly on the deadline: on time, effective at current term end"
        )
        lease = get_lease(ctx["lease"]["id"])
        assert lease["term_index"] == 1, "no renewal fires at exact deadline equality"
        assert lease["status"] == "TERMINATION_PENDING"

    def test_renewal_at_exact_deadline_does_not_fire(self, api):
        """PRD §2.9: "Renewal, conversely, is strict: the auto-renewal sweep renews a lease only when the clock is strictly later than `current_notice_deadline`, so a clock reading exactly equal to the deadline does not renew"
        PRD §3.9: "any whose `current_notice_deadline` the clock has strictly passed is renewed for one year: `term_index` increments, `term_end_date` extends by one year"

        Design: Corner/calculations/renewal_at_exact_deadline_does_not_fire
        """
        ctx = setup_active_lease("CASH")  # deadline 2027-09-03
        set_clock("2027-09-03T00:00:00Z")
        lease = get_lease(ctx["lease"]["id"])
        assert lease["term_index"] == 1, "clock == deadline: strict > does not renew"

        set_clock("2027-09-04T00:00:00Z")
        lease = get_lease(ctx["lease"]["id"])
        assert lease["term_index"] == 2, "one day past the deadline renews"
        assert_iso_instant_equal(lease["term_end_date"], "2029-03-01T00:00:00Z")

    def test_late_notice_after_renewal_targets_new_term_end(self, api):
        """PRD §2.9: "A termination notice served on or before the deadline is on time and takes effect at the current term's end; a notice served after it misses the statutory window and takes effect at the end of the following term instead."
        PRD §3.9: "the `statutory_deadline` is captured as the lease's `term_end_date` minus its `notice_lead_days`, and the `effective_date` is resolved per the deadline semantics of §2.9"

        Design: Corner/calculations/late_notice_after_renewal_targets_new_term_end
        """
        ctx = setup_active_lease("CASH")
        set_clock("2027-09-04T00:00:00Z")  # past deadline: auto-renewal fires
        lease = get_lease(ctx["lease"]["id"])
        assert lease["term_index"] == 2
        assert_iso_instant_equal(lease["term_end_date"], "2029-03-01T00:00:00Z")

        set_clock("2027-09-10T00:00:00Z")
        notice = serve_notice(ctx, "LANDLORD")
        # The renewed term ends 2029-03-01; its deadline is 2028-09-02, and
        # 2027-09-10 is on time for that cycle.
        assert_iso_instant_equal(notice["statutory_deadline"], "2028-09-02T00:00:00Z")
        assert_iso_instant_equal(notice["effective_date"], "2029-03-01T00:00:00Z")
        assert get_lease(ctx["lease"]["id"])["status"] == "TERMINATION_PENDING"


class TestRenewal:
    def test_renewal_applies_compounded_escalation(self, api):
        """PRD §3.9: "The base rent escalates at renewal according to the lease's `escalation_type`: under `NONE` it carries forward unchanged, and under `FIXED_PCT` the new base is the previous term's base increased by the `escalation_pct` fraction and rounded half up to whole cents — compounding applies the rounded value of the previous term, not the original base, year after year."
        PRD §3.9: "The clock sweep examines every `ACTIVE` lease with no notice in `SERVED` status, and any whose `current_notice_deadline` the clock has strictly passed is renewed for one year: `term_index` increments, `term_end_date` extends by one year, `current_notice_deadline` is recomputed from the new end date, and the lease's `version` increments by one."
        PRD §3.9: "New-term installments are then generated per the schedule rules of §3.5."

        Design: Corner/calculations/renewal_applies_compounded_escalation
        """
        ctx = setup_active_lease(
            "CASH", cash_bid_cents=10009, min_bid_cents=5000,
            escalation_type="FIXED_PCT", escalation_pct=0.03,
        )

        set_clock("2027-09-04T00:00:00Z")  # past deadline 2027-09-03: renewal 1
        lease = get_lease(ctx["lease"]["id"])
        # base_1 = round_half_up(10009 * 1.03) = round_half_up(10309.27) = 10309.
        assert lease["base_rent_cents_per_acre"] == 10309
        assert lease["term_index"] == 2
        assert_iso_instant_equal(lease["term_end_date"], "2029-03-01T00:00:00Z")
        assert_iso_instant_equal(
            lease["current_notice_deadline"], "2028-09-02T00:00:00Z"
        )

        set_clock("2028-09-03T00:00:00Z")  # past new deadline 2028-09-02: renewal 2
        lease = get_lease(ctx["lease"]["id"])
        # base_2 = round_half_up(10309 * 1.03) = 10618; compounding the
        # unrounded original base would give 10619 and is forbidden.
        assert lease["base_rent_cents_per_acre"] == 10618
        assert lease["term_index"] == 3
        assert_iso_instant_equal(lease["term_end_date"], "2030-03-01T00:00:00Z")

        installments = list_lease_installments(ctx["lease"]["id"])
        # due-date ordering: two installments per term year.
        assert len(installments) == 6
        term2_first = installments[2]
        assert term2_first["amount_cents"] == 515450, "10309 * 100 / 2"
        term3_first = installments[4]
        assert term3_first["amount_cents"] == 530900, "round_half_up(1061800 / 2)"
        assert_iso_instant_equal(term3_first["due_date"], "2029-03-01T00:00:00Z")

    def test_renewal_blocked_by_served_notice(self, api):
        """PRD §3.9: "The clock sweep examines every `ACTIVE` lease with no notice in `SERVED` status, and any whose `current_notice_deadline` the clock has strictly passed is renewed for one year"
        PRD §3.9: "The notice starts in `SERVED` status, and the lease moves from `ACTIVE` to `TERMINATION_PENDING`."

        Design: Corner/calculations/renewal_blocked_by_served_notice
        """
        ctx = setup_active_lease("CASH")
        set_clock("2027-08-15T00:00:00Z")
        notice = serve_notice(ctx, "TENANT")
        assert notice["status"] == "SERVED"

        set_clock("2027-09-04T00:00:00Z")  # past the deadline
        lease = get_lease(ctx["lease"]["id"])
        assert lease["term_index"] == 1, "a SERVED notice excludes the lease from renewal"
        assert lease["status"] == "TERMINATION_PENDING"


class TestServeWithdrawCycle:
    def test_notice_serve_moves_lease_to_termination_pending(self, api):
        """PRD §3.9: "At service, `served_date` is stamped from the clock, the `statutory_deadline` is captured as the lease's `term_end_date` minus its `notice_lead_days`, and the `effective_date` is resolved per the deadline semantics of §2.9: service on or before the statutory deadline is on time and the notice takes effect at the current term's `term_end_date`"
        PRD §3.9: "The notice starts in `SERVED` status, and the lease moves from `ACTIVE` to `TERMINATION_PENDING`."

        Design: Difficulty/non_linear_state_machine/lease_notice_serve_withdraw_cycle
        """
        ctx = setup_active_lease("CASH")  # term end 2028-03-01, lead 180 days
        set_clock("2027-08-15T00:00:00Z")
        notice = serve_notice(ctx, "LANDLORD")
        assert notice["status"] == "SERVED"
        assert_iso_instant_equal(notice["served_date"], "2027-08-15T00:00:00Z")
        # statutory_deadline = 2028-03-01 - 180 days = 2027-09-03.
        assert_iso_instant_equal(notice["statutory_deadline"], "2027-09-03T00:00:00Z")
        # served 2027-08-15 <= deadline: effective at the current term end.
        assert_iso_instant_equal(notice["effective_date"], "2028-03-01T00:00:00Z")
        assert get_lease(ctx["lease"]["id"])["status"] == "TERMINATION_PENDING"

    def test_notice_withdraw_returns_lease_to_active(self, api):
        """PRD §3.9: "A serving party who changes their mind may withdraw a `SERVED` notice before it becomes effective; the caller must be the serving party and a party to the lease, else `ERR_NOT_RESOURCE_OWNER`. Withdrawal moves the notice to the terminal `WITHDRAWN` state and returns the lease from `TERMINATION_PENDING` to `ACTIVE`"

        Design: Difficulty/non_linear_state_machine/lease_notice_serve_withdraw_cycle
        """
        ctx = setup_active_lease("CASH")
        set_clock("2027-08-15T00:00:00Z")
        notice = serve_notice(ctx, "LANDLORD")
        assert get_lease(ctx["lease"]["id"])["status"] == "TERMINATION_PENDING"

        withdrawn = validate_success(
            api.withdraw_notice(
                notice["id"], make_landlord_headers(ctx["landlord"]["id"])
            )
        )
        assert withdrawn["status"] == "WITHDRAWN"
        assert get_lease(ctx["lease"]["id"])["status"] == "ACTIVE", (
            "cycle closed: ACTIVE -> TERMINATION_PENDING -> ACTIVE"
        )


class TestTerminationCascade:
    def test_notice_effectiveness_cascades_to_field_and_report(self, api):
        """PRD §3.9: "When the clock reaches or passes a `SERVED` notice's `effective_date`, the notice becomes `EFFECTIVE` and the lease moves from `TERMINATION_PENDING` to the terminal `TERMINATED` state."
        PRD §3.9: "Termination cascades: the field returns from `LEASED` to `AVAILABLE`; every completed improvement linked to the lease whose `reimbursement_status` is `NONE` computes its `reimbursement_due_cents` per §3.8 and flips to `DUE`; when the landlord is an absentee owner, a `TERMINATION`-type owner report is auto-created in `DRAFT` status covering the closed window from the final term's `term_start_date` through the `effective_date`; and the landlord's ledger balances are recomputed."

        Design: Corner/state_machines/notice_effectiveness_cascades_to_field_and_report
        """
        ctx = setup_terminated_lease_with_improvements(
            methods=(),
            project_types=(),
            landlord_overrides={
                "name": "L NE",
                "contact_email": "lne@x.com",
                "absentee": True,
                "ack_required_days": 14,
            },
        )
        assert ctx["notice"]["status"] == "EFFECTIVE"
        assert ctx["lease"]["status"] == "TERMINATED"
        assert ctx["field"]["status"] == "AVAILABLE", "termination releases the field"

        reports = list_landlord_reports(ctx["landlord"]["id"])
        assert len(reports) == 1, "one auto-created TERMINATION report"
        report = reports[0]
        assert report["report_type"] == "TERMINATION"
        assert report["status"] == "DRAFT"
        assert_iso_instant_equal(report["period_start"], "2027-03-01T00:00:00Z")
        assert_iso_instant_equal(report["period_end"], "2028-03-01T00:00:00Z")
