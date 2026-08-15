"""Remittance posting, the auto-cure cascade, voiding, and period locks."""
import pytest

from test_helpers import (
    LOCAL_ADMIN_1_HEADERS,
    SECRETARY_TREASURER_1_HEADERS,
    ST,
    ApiErrorId,
    add_remittance_line,
    drive_member_delinquent,
    get_member,
    get_success_data,
    list_member_notices,
    make_assessment_run,
    make_classification,
    make_employer,
    make_local,
    make_member,
    make_percapita_report,
    make_remittance,
    make_secretary_treasurer_headers,
    post_remittance,
    reconcile_remittance,
    resolve_remittance,
    run_period,
    send_notice,
    set_clock,
    setup_flat_local_with_journeyman,
    setup_pct_local_with_journeyman,
    sweep_delinquency,
    validate_error,
    validate_success,
    void_remittance,
)


class TestPostingGuards:
    def test_post_reconciled_remittance_with_prior_period_unposted(self, api):
        """PRD section on remittance posting: "Every other remittance of the
        same employer with a strictly earlier period must already be `POSTED`
        or `VOID`, enforcing strictly chronological posting per employer
        (`ERR_PRIOR_PERIOD_UNPOSTED`)."

        Design: Corner/validations/post_reconciled_remittance_with_prior_period_unposted
        """
        local = make_local("PCT", name="Local 100")
        emp = make_employer("Acme Widgets")
        set_clock("2026-08-01T00:00:00Z")
        make_remittance(emp["id"], local["id"], "2026-08", 0)
        r2 = make_remittance(emp["id"], local["id"], "2026-09", 0)
        reconcile_remittance(r2["id"])
        resp = api.post_remittance(r2["id"], SECRETARY_TREASURER_1_HEADERS)
        validate_error(resp, ApiErrorId.ERR_PRIOR_PERIOD_UNPOSTED)

    def test_sod_remittance_receiver_cannot_post(self, api):
        """PRD section on segregation of duties: "an attempt by the same
        operator to post the remittance they received is rejected with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 403), and the posting operator is
        recorded as `posted_by_user_id`".

        Design: Corner/rbac/sod_remittance_receiver_cannot_post
        """
        local = make_local("PCT", name="Local 100")
        emp = make_employer("Acme Widgets")
        set_clock("2026-08-01T00:00:00Z")
        rem = make_remittance(emp["id"], local["id"], "2026-08", 0)
        assert rem["received_by_user_id"] == "clerk_1"
        reconcile_remittance(rem["id"])
        resp = api.post_remittance(rem["id"], make_secretary_treasurer_headers("clerk_1"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)
        posted = post_remittance(rem["id"])
        assert posted["status"] == "POSTED", "a different operator posts successfully"


class TestPostStateVsTemporalPriority:
    """A post attempt violating both the RECONCILED state guard and the
    chronological-order rule surfaces the state guard error."""

    def _setup_two_received_remittances(self, api):
        local = make_local("PCT", name="Local 100")
        emp = make_employer("Acme Widgets")
        set_clock("2026-08-01T00:00:00Z")
        r1 = make_remittance(emp["id"], local["id"], "2026-08", 0)
        r2 = make_remittance(emp["id"], local["id"], "2026-09", 0)
        return r1, r2

    def test_state_error_precedes_temporal_error(self, api):
        """PRD section on validation order: "When several validation rules
        could reject the same request, the server evaluates them in a fixed
        priority order so that the surfaced error is deterministic." State
        guards (priority 6, including `ERR_REMITTANCE_NOT_RECONCILED`) precede
        temporal rules (priority 8, including `ERR_PRIOR_PERIOD_UNPOSTED`).

        Design: Difficulty/priority_pair_validation_conflict/post_state_vs_temporal_priority
        """
        _, r2 = self._setup_two_received_remittances(api)
        resp = api.post_remittance(r2["id"], SECRETARY_TREASURER_1_HEADERS)
        validate_error(resp, ApiErrorId.ERR_REMITTANCE_NOT_RECONCILED)

    def test_temporal_error_surfaces_once_state_guard_passes(self, api):
        """PRD section on remittance posting: "Every other remittance of the
        same employer with a strictly earlier period must already be `POSTED`
        or `VOID`, enforcing strictly chronological posting per employer
        (`ERR_PRIOR_PERIOD_UNPOSTED`)." Once the target remittance is
        RECONCILED, the temporal rule is the remaining violation.

        Design: Difficulty/priority_pair_validation_conflict/post_state_vs_temporal_priority
        """
        _, r2 = self._setup_two_received_remittances(api)
        reconcile_remittance(r2["id"])
        resp = api.post_remittance(r2["id"], SECRETARY_TREASURER_1_HEADERS)
        validate_error(resp, ApiErrorId.ERR_PRIOR_PERIOD_UNPOSTED)


class TestRemittancePostCureCascade:
    """Posting a remittance credits the member's ledger, the waterfall drops
    arrears below the delinquency threshold, the member auto-cures, and the
    SENT notice cures as the last hop of the chain."""

    def _setup_postable_remittance(self, api):
        local, cls = setup_flat_local_with_journeyman()
        emp = make_employer("Acme Widgets")
        member = make_member(
            local["id"], cls["id"], employer_id=emp["id"],
            full_name="Casc Ada", member_number="M-001",
        )
        drive_member_delinquent(local["id"], member["id"], ("2026-05", "2026-06", "2026-07"))
        notice = list_member_notices(member["id"])[0]
        send_notice(member["id"], notice["id"])
        rem = make_remittance(emp["id"], local["id"], "2026-08", 15000)
        add_remittance_line(rem["id"], member["id"], 15000, 0)
        reconcile_remittance(rem["id"])
        resolve_remittance(rem["id"], "accept over-deduction as member credit")
        return local, member, notice, rem

    def test_post_drops_arrears_and_auto_cures_member(self, api):
        """PRD section on remittance posting: "Posting writes a
        `CHECKOFF_CREDIT` of each line's `deducted_cents` to that member's
        ledger", and "Any member whose arrears thereby drop below the
        delinquency threshold auto-cures per §3.5, and the remittance records
        those members in `auto_cured_member_ids` for later compensation."

        Design: Difficulty/transitive_cascade/remittance_post_cure_cascade
        """
        local, member, notice, rem = self._setup_postable_remittance(api)
        posted = post_remittance(rem["id"])
        assert posted["status"] == "POSTED"
        assert member["id"] in posted["auto_cured_member_ids"], (
            "the cured member is recorded for later void compensation"
        )
        after = get_member(member["id"])
        assert after["arrears_cents"] == 5000, "20000 charged minus the 15000 credit"
        assert after["status"] == "ACTIVE", "arrears 5000 is below the 10000 threshold"

    def test_post_cascade_cures_sent_notice(self, api):
        """PRD section on delinquency: "Whenever any credit posting — a direct
        payment, a reinstatement, a remittance post, an objector rebate —
        drops a `DELINQUENT` member's arrears below the threshold, the member
        auto-cures to `ACTIVE` in the same request: every `SENT` notice for
        the member moves to `CURED`".

        Design: Difficulty/transitive_cascade/remittance_post_cure_cascade
        """
        local, member, notice, rem = self._setup_postable_remittance(api)
        post_remittance(rem["id"])
        notices = list_member_notices(member["id"])
        assert notices[0]["status"] == "CURED", (
            "the SENT notice cured because the member cured, not because post touched it"
        )


class TestPostThenVoidInvariant:
    """The void posts compensating entries that restore the exact pre-post
    ledger balance and delinquency state."""

    def _setup_posted_then_voidable(self, api):
        local, cls = setup_flat_local_with_journeyman()
        emp = make_employer("Acme Widgets")
        member = make_member(
            local["id"], cls["id"], employer_id=emp["id"],
            full_name="Comp Carla", member_number="M-001",
        )
        drive_member_delinquent(
            local["id"], member["id"],
            ("2026-05", "2026-06", "2026-07", "2026-08"),
        )
        rem = make_remittance(emp["id"], local["id"], "2026-08", 15000)
        add_remittance_line(rem["id"], member["id"], 15000, 0)
        reconcile_remittance(rem["id"])
        resolve_remittance(rem["id"], "accept over-deduction")
        return local, member, rem

    def test_post_credit_moves_member_to_good_state(self, api):
        """PRD section on remittance posting: "Posting writes a
        `CHECKOFF_CREDIT` of each line's `deducted_cents` to that member's
        ledger, runs the payment waterfall per affected member, recomputes
        arrears and credit balances". The 15000 credit against 20000 of
        charges leaves arrears 5000 and auto-cures the member.

        Design: Difficulty/compensating_invariant/post_then_void_restores_ledger_balance
        """
        _, member, rem = self._setup_posted_then_voidable(api)
        pre = get_member(member["id"])
        assert pre["arrears_cents"] == 20000 and pre["credit_balance_cents"] == 0
        assert pre["status"] == "DELINQUENT"
        post_remittance(rem["id"])
        mid = get_member(member["id"])
        assert mid["arrears_cents"] == 5000 and mid["status"] == "ACTIVE"
        ledger = get_success_data(api.list_member_ledger(member["id"], ST))
        credits = [e for e in ledger if e["entry_type"] == "CHECKOFF_CREDIT"]
        assert len(credits) == 1 and credits[0]["amount_cents"] == -15000

    def test_void_restores_pre_post_balance_and_state(self, api):
        """PRD section on voiding: "Voiding posts `VOID_REVERSAL` entries
        negating every checkoff credit and every finalization delta the
        remittance produced, recomputes member balances, increments the
        affected versions, and restores the pre-post delinquency state: every
        member listed in `auto_cured_member_ids` transitions back from
        `ACTIVE` to `DELINQUENT`."

        Design: Difficulty/compensating_invariant/post_then_void_restores_ledger_balance
        """
        _, member, rem = self._setup_posted_then_voidable(api)
        post_remittance(rem["id"])
        voided = void_remittance(rem["id"])
        assert voided["status"] == "VOID"
        after = get_member(member["id"])
        assert after["arrears_cents"] == 20000, "signed ledger sum restored exactly"
        assert after["credit_balance_cents"] == 0
        assert after["status"] == "DELINQUENT", "auto-cure reverted by the void"
        ledger = get_success_data(api.list_member_ledger(member["id"], ST))
        reversals = [e for e in ledger if e["entry_type"] == "VOID_REVERSAL"]
        assert len(reversals) == 1 and reversals[0]["amount_cents"] == 15000
        signed_sum = sum(e["amount_cents"] for e in ledger)
        assert signed_sum == 20000, "ledger balance identical before post and after void"


class TestVoidBlockedBySubmittedPerCapita:
    """A submitted per-capita report locks the period against remittance
    voids; an approved-but-unsubmitted report does not."""

    def _setup_posted_remittance(self, api):
        local, cls = setup_pct_local_with_journeyman(max_monthly_dues_cents=20000)
        emp = make_employer("Acme Widgets")
        member = make_member(
            local["id"], cls["id"], employer_id=emp["id"],
            full_name="Lock Larry", member_number="M-001",
        )
        set_clock("2026-08-01T00:00:00Z")
        make_assessment_run(local["id"], "2026-08")
        rem = make_remittance(emp["id"], local["id"], "2026-08", 3000)
        add_remittance_line(rem["id"], member["id"], 3000, 100000)
        reconcile_remittance(rem["id"])
        post_remittance(rem["id"])
        return local, rem

    def test_void_rejected_once_report_submitted(self, api):
        """PRD section on voiding: "once the local's per-capita report for that
        period has been submitted or paid, voiding is rejected with
        `ERR_PERIOD_LOCKED`".

        Design: Difficulty/cross_entity_state_dependency/void_blocked_by_submitted_percapita
        """
        local, rem = self._setup_posted_remittance(api)
        report = make_percapita_report(local["id"], "2026-08")
        validate_success(api.approve_percapita_report(report["id"], LOCAL_ADMIN_1_HEADERS), 200)
        validate_success(api.submit_percapita_report(report["id"], SECRETARY_TREASURER_1_HEADERS), 200)
        resp = api.void_remittance(rem["id"], LOCAL_ADMIN_1_HEADERS)
        validate_error(resp, ApiErrorId.ERR_PERIOD_LOCKED)

    def test_void_succeeds_while_report_only_approved(self, api):
        """PRD section on voiding: "once the local's per-capita report for that
        period has been submitted or paid, voiding is rejected with
        `ERR_PERIOD_LOCKED`" — the lock attaches at submission, so an
        APPROVED-but-unsubmitted report leaves the period open.

        Design: Difficulty/cross_entity_state_dependency/void_blocked_by_submitted_percapita
        """
        local, rem = self._setup_posted_remittance(api)
        report = make_percapita_report(local["id"], "2026-08")
        validate_success(api.approve_percapita_report(report["id"], LOCAL_ADMIN_1_HEADERS), 200)
        resp = api.void_remittance(rem["id"], LOCAL_ADMIN_1_HEADERS)
        voided = validate_success(resp, 200)
        assert voided["status"] == "VOID"
