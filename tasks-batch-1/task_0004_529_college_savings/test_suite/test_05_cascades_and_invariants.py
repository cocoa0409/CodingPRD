"""Cascade and compensating-invariant tests.

Covers difficulty/transitive_cascade + compensating_invariant, the scheduler
tick endpoint, and the immediate-consistency claim.
"""
from test_helpers import (
    validate_success,
    setup_donor_beneficiary_account,
    setup_account_with_earnings,
    set_clock,
    create_and_post_contribution,
    credit_market_earnings,
    create_draft_withdrawal,
    submit_withdrawal,
    approve_withdrawal,
    disburse_withdrawal,
    create_beneficiary,
    create_beneficiary_change,
    approve_beneficiary_change,
    create_state_tax_incentive,
    create_form_1099q,
    create_scheduled_contribution,
    get_account,
    create_donor,
    create_account,
    make_account_owner_headers,
    make_custodian_headers,
    make_tax_authority_headers,
    make_compliance_headers,
    create_contribution_payload,
)


# ---------------------------------------------------------------------------
# Difficulty/transitive_cascade
# ---------------------------------------------------------------------------

class TestTransitiveCascades:
    def test_contribution_post_cascade_to_state_tax_incentive_via_account(self, api):
        """PRD §3.4: "Finally, the donor's matching StateTaxIncentive for the contribution's
        tax_year — if one exists — has its contributions_eligible_cents re-aggregated from
        scratch across the donor's accounts."
        PRD §3.4: "The owning account is then re-aggregated from primary sources:
        account_balance_cents is the sum of all POSTED Contribution.amount_cents minus the sum
        of all DISBURSED Withdrawal.amount_cents; total_basis_cents is the sum of all POSTED
        Contribution.amount_cents minus the sum of basis_portion_cents across all DISBURSED
        Withdrawal rows; and total_earnings_cents is account_balance_cents minus
        total_basis_cents."

        Design: Difficulty/transitive_cascade/contribution_post_cascade_to_state_tax_incentive_via_account
        """
        donor, _ben, account = setup_donor_beneficiary_account(donor_email="d5@x.com")
        sti = create_state_tax_incentive(donor["id"], 2026)
        assert sti["contributions_eligible_cents"] == 0
        create_and_post_contribution(account["id"], 250_000)
        # Hop 2: Account ledger updated.
        a = get_account(account["id"])
        assert a["account_balance_cents"] == 250_000
        assert a["total_basis_cents"] == 250_000
        # Hop 3: StateTaxIncentive aggregate updated.
        sti_after_resp = api.get_state_tax_incentive(sti["id"], make_custodian_headers())
        sti_after = validate_success(sti_after_resp, expected_status=200)
        assert sti_after["contributions_eligible_cents"] == 250_000

    def test_withdrawal_disburse_cascade_to_form_1099q_via_account_ytd(self, api):
        """PRD §3.5: "When the expense_class is K_12_TUITION, the account's running
        ytd_qualified_k12_cents is incremented by the qualified portion of this withdrawal only
        — that is, by amount_cents minus k12_excess_cents — so that the running total reflects
        only the cents that actually counted as qualified K-12 distribution under the annual
        cap."
        PRD §3.5: "Finally, any DRAFT Form1099Q matching the same account_id and the withdrawal's
        tax_year has its aggregate fields re-aggregated against current disbursed-withdrawal
        data (gross_distribution_cents, earnings_cents, basis_cents, penalty_cents, and
        recipient_kind are all refreshed; see §3.8)."

        Design: Difficulty/transitive_cascade/withdrawal_disburse_cascade_to_form_1099q_via_account_ytd
        """
        set_clock("2026-04-01T00:00:00.000Z")
        donor, _ben, _acc, a_v1 = setup_account_with_earnings(
            contribution_cents=2_000_000,
            market_credit_cents=500_000,
            clock_iso=None,
            donor_email="d6@x.com",
            beneficiary_tax_id="2222",
        )
        account_id = _acc["id"]
        # Pre-create the DRAFT 1099-Q for 2026.
        form = create_form_1099q(account_id, 2026)
        # K_12 withdrawal 300000.
        w = create_draft_withdrawal(account_id, donor["id"], 300_000, "K_12_TUITION")
        submit_withdrawal(w["id"], donor["id"])
        approve_withdrawal(w["id"], a_v1)
        # earnings_portion = round_half_up(300000*500000/2500000) = 60000.
        # basis_portion = 240000. penalty=0 (qualified, no excess).
        # Disburse.
        disburse_withdrawal(w["id"])
        # Hop 2: account ytd_qualified_k12_cents incremented by full 300000 (no excess).
        a_after = get_account(account_id)
        assert a_after["ytd_qualified_k12_cents"] == 300_000
        # Hop 3: Form aggregates recomputed.
        form_after_resp = api.get_form_1099q(form["id"], make_tax_authority_headers())
        form_after = validate_success(form_after_resp, expected_status=200)
        assert form_after["gross_distribution_cents"] == 300_000
        assert form_after["earnings_cents"] == 60_000
        assert form_after["basis_cents"] == 240_000


# ---------------------------------------------------------------------------
# Difficulty/compensating_invariant
# ---------------------------------------------------------------------------

class TestCompensatingInvariants:
    def test_contribution_post_reverse_preserves_account_balance_cents(self, api):
        """PRD §3.4: "Reversing a posted contribution drives it from POSTED to the terminal
        REVERSED. The reverse is a narrow, time-boxed correction: the clock-time delta between
        the current clock and the contribution's posted_at_utc must be strictly less than 72
        hours, or the request is rejected with ERR_REVERSE_WINDOW_CLOSED."
        PRD §3.4: "On success, the same re-aggregation pass refreshes the account's
        account_balance_cents, total_basis_cents, and total_earnings_cents; Account.version is
        incremented; and the donor's StateTaxIncentive for the original tax_year is recomputed."

        Design: Difficulty/compensating_invariant/contribution_post_reverse_preserves_account_balance_cents
        """
        _donor, _ben, account = setup_donor_beneficiary_account(donor_email="d15@x.com")
        # Snapshot ledger before.
        pre = get_account(account["id"])
        bal_pre = pre["account_balance_cents"]
        basis_pre = pre["total_basis_cents"]
        # Post a 100000 LUMP_SUM.
        posted = create_and_post_contribution(account["id"], 100_000)
        # Within 72h, reverse.
        set_clock("2026-03-02T00:00:00.000Z")
        resp = api.reverse_contribution(posted["id"], make_custodian_headers())
        reversed_row = validate_success(resp, expected_status=200)
        assert reversed_row["status"] == "REVERSED"
        # Balance & basis returned to their pre-post values.
        post = get_account(account["id"])
        assert post["account_balance_cents"] == bal_pre == 0
        assert post["total_basis_cents"] == basis_pre == 0

    def test_beneficiary_change_round_trip_preserves_account_beneficiary_id(self, api):
        """PRD §3.7: "Approval drives it to APPROVED; rejection drives it to REJECTED ... on
        approval, the account's beneficiary_id is overwritten with the change's
        to_beneficiary_id, and Account.version is incremented along with a refresh of
        updated_at."

        Design: Difficulty/compensating_invariant/beneficiary_change_round_trip_preserves_account_beneficiary_id
        """
        donor, b1, account = setup_donor_beneficiary_account(donor_email="d16@x.com")
        a_v0 = account["version"]
        b2 = create_beneficiary(
            full_name="B16b",
            date_of_birth="2010-06-01",
            relationship_class="CHILD",
            federal_tax_id_last4="3333",
        )
        # Forward: b1 -> b2.
        bc1 = create_beneficiary_change(account["id"], donor["id"], b2["id"])
        result1 = approve_beneficiary_change(bc1["id"], a_v0)
        a_v1 = result1["version"] if "version" in result1 else None
        # Read account version after forward approval.
        mid = get_account(account["id"])
        assert mid["beneficiary_id"] == b2["id"]
        # Compensating: b2 -> b1.
        bc2 = create_beneficiary_change(account["id"], donor["id"], b1["id"])
        approve_beneficiary_change(bc2["id"], mid["version"])
        final = get_account(account["id"])
        # Invariant: final beneficiary == initial.
        assert final["beneficiary_id"] == b1["id"]


# ---------------------------------------------------------------------------
# Corner/endpoints: scheduler tick
# ---------------------------------------------------------------------------

class TestSchedulerTick:
    def test_scheduler_tick_due_schedule_produces_recurring_contribution(self, api):
        """PRD §3.3: "Recurring contributions are materialized by an admin-only scheduler-tick
        capability that, when invoked, walks every ScheduledContribution whose next_run_utc is
        at or before the current clock and which is in ACTIVE status. For each due schedule,
        the system creates a fresh Contribution row with contribution_kind = RECURRING, the
        schedule's account_id and amount_cents, and the schedule's id recorded as the
        contribution's scheduled_contribution_id. That fresh contribution is then immediately
        posted (see §3.4), and the schedule's posted_runs is incremented and next_run_utc
        advanced by one cadence interval relative to the just-posted time."

        Design: Corner/endpoints/scheduler_tick_due_schedule_produces_recurring_contribution
        """
        donor, _ben, account = setup_donor_beneficiary_account(donor_email="dst@x.com")
        schedule = create_scheduled_contribution(account["id"], donor["id"], 50_000, "MONTHLY")
        # Advance past next_run_utc (set initially to current + 1 month = 2026-04-01).
        set_clock("2026-04-02T00:00:00.000Z")
        # Tick.
        tick_resp = api.scheduler_tick(make_custodian_headers())
        validate_success(tick_resp, expected_status=200)
        # Schedule's posted_runs incremented.
        sched_resp = api.get_scheduled_contribution(schedule["id"], make_custodian_headers())
        sched_after = validate_success(sched_resp, expected_status=200)
        assert sched_after["posted_runs"] == 1
        # A POSTED RECURRING Contribution exists for this schedule.
        list_resp = api.list_contributions(
            make_custodian_headers(), params={"scheduled_contribution_id": schedule["id"]}
        )
        body = list_resp.json()
        items = body["data"]
        recurring_posted = [
            c for c in items if c["status"] == "POSTED" and c["contribution_kind"] == "RECURRING"
        ]
        assert len(recurring_posted) == 1
        # Account.balance reflects the new contribution.
        acc_after = get_account(account["id"])
        assert acc_after["account_balance_cents"] == 50_000


# ---------------------------------------------------------------------------
# Corner/consistency_model
# ---------------------------------------------------------------------------

class TestImmediateConsistency:
    def test_immediate_consistency_post_returns_final_state(self, api):
        """PRD §3.4: "Posting a contribution drives it from DRAFT to POSTED. The post step is gated
        on the account being either OPEN or RESTRICTED ... On a successful post, the
        contribution's status becomes POSTED, its posted_at_utc is pinned to the current clock,
        and its tax_year is pinned to the calendar year of posted_at_utc. The owning account is
        then re-aggregated from primary sources"

        Design: Corner/consistency_model/immediate_consistency_post_returns_final_state
        """
        _donor, _ben, account = setup_donor_beneficiary_account(donor_email="dic@x.com")
        create_resp = api.create_contribution(
            create_contribution_payload(account["id"], 50_000, "LUMP_SUM"),
            make_custodian_headers(),
        )
        c = validate_success(create_resp, expected_status=201)
        # POST endpoint must return the final state (POSTED) in the same call.
        post_resp = api.post_contribution(c["id"], make_custodian_headers())
        posted = validate_success(post_resp, expected_status=200)
        assert posted["status"] == "POSTED"
        # Account ledger is visible immediately.
        acc = get_account(account["id"])
        assert acc["account_balance_cents"] == 50_000
