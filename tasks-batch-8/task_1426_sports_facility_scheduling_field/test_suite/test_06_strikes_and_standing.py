"""The strike economy: escalating strike points, standing thresholds, the
suspension revocation cascade, rescission, and reinstatement."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_deposit_waterfall_conservation,
    assert_invoice,
    assert_strike_record,
    get_invoice,
    get_organization,
    get_permit,
    list_strikes,
    record_no_shows,
    setup_org_with_confirmed_permits,
    setup_suspended_org,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["athletics_admin_headers"]


class TestStrikePoints:
    def test_strike_points_escalate_with_ordinal(self, api):
        """PRD §3.1: "When a field supervisor marks a confirmed permit as a no-show
        (§3.6), the system creates a StrikeRecord linking the `organization_id` to the
        offending `permit_id` and stores `strike_points` equal to ten times the
        organization's new active-strike count including the strike just created — a
        first strike records 10 points, a second records 20, a third records 30."
        PRD §3.1: "Strike history can be browsed through the strike listing with
        filters on `organization_id`, `permit_id`, and `status`, ordered by creation
        ascending so indexed reads are stable."

        Design: Corner/calculations/strike_points_escalate_with_ordinal
        """
        ctx = setup_org_with_confirmed_permits(dates=("2026-08-06", "2026-08-07"))
        record_no_shows(ctx, 2)
        strikes = list_strikes(ctx["organization"]["id"])
        assert len(strikes) == 2
        for strike in strikes:
            assert_strike_record(strike)
        assert strikes[0]["strike_points"] == 10, "first strike: 10 x 1"
        assert strikes[1]["strike_points"] == 20, "second strike: 10 x 2"
        org = get_organization(ctx["organization"]["id"])
        assert org["no_show_strikes_active"] == 2


class TestStrikeThreshold:
    def test_two_strikes_probation_not_suspended(self, api):
        """PRD §3.1: "Standing re-evaluates on every change to the active strike
        count. The moment the count becomes exactly 2, the organization falls from
        `GOOD` to `PROBATION`. The moment the count reaches 3 or more, the
        organization becomes `SUSPENDED` — including a direct `GOOD` → `SUSPENDED`
        fall when a single event pushes the count from below 2 to 3 or more in one
        step, and the ordinary `PROBATION` → `SUSPENDED` fall otherwise."

        At exactly 2 active strikes the threshold for SUSPENDED is NOT crossed.

        Design: Difficulty/boundary_precision_check/strike_threshold_third_strike_suspends
        """
        ctx = setup_org_with_confirmed_permits(dates=("2026-08-06", "2026-08-07",
                                                      "2026-08-08"))
        record_no_shows(ctx, 1)
        org = get_organization(ctx["organization"]["id"])
        assert org["no_show_strikes_active"] == 1
        assert org["standing"] == "GOOD"

        record_no_shows(ctx, 1, start=1)
        org = get_organization(ctx["organization"]["id"])
        assert org["no_show_strikes_active"] == 2
        assert org["standing"] == "PROBATION", "exactly 2 strikes: PROBATION only"

    def test_third_strike_suspends(self, api):
        """PRD §3.1: "The moment the count reaches 3 or more, the organization becomes
        `SUSPENDED` — including a direct `GOOD` → `SUSPENDED` fall when a single event
        pushes the count from below 2 to 3 or more in one step, and the ordinary
        `PROBATION` → `SUSPENDED` fall otherwise."

        The third strike crosses the boundary: PROBATION -> SUSPENDED.

        Design: Difficulty/boundary_precision_check/strike_threshold_third_strike_suspends
        """
        ctx = setup_org_with_confirmed_permits(dates=("2026-08-06", "2026-08-07",
                                                      "2026-08-08"))
        record_no_shows(ctx, 3)
        org = get_organization(ctx["organization"]["id"])
        assert org["no_show_strikes_active"] == 3
        assert org["standing"] == "SUSPENDED", "boundary crossed on the 3rd strike"


class TestStandingCycle:
    def test_full_cycle_suspension_rescind_reinstate_to_good(self, api):
        """PRD §3.1: "Rescission recomputes `no_show_strikes_active` and re-evaluates
        standing immediately: a `PROBATION` organization whose active count has fallen
        below 2 returns to `GOOD` automatically, while a `SUSPENDED` organization stays
        `SUSPENDED` no matter how far the count falls — only an explicit administrative
        reinstatement lifts a suspension, moving the organization `SUSPENDED` →
        `PROBATION`. Reinstatement itself re-evaluates standing within the same
        request, so when the active count is already below 2 the follow-on `PROBATION`
        → `GOOD` transition fires immediately as part of that request."

        GOOD -> PROBATION -> SUSPENDED via three no-shows; two rescissions leave the
        org SUSPENDED (no auto-un-suspend); reinstate then lands on GOOD because the
        count (1) is already below 2.

        Design: Difficulty/non_linear_state_machine/organization_standing_cycle_with_reinstate
        """
        ctx = setup_suspended_org()
        org_id = ctx["organization"]["id"]
        org = get_organization(org_id)
        assert org["standing"] == "SUSPENDED"
        assert org["no_show_strikes_active"] == 3

        strikes = list_strikes(org_id)
        for strike in strikes[:2]:
            validate_success(api.rescind_strike(strike["id"], ADMIN), 200)
        org = get_organization(org_id)
        assert org["no_show_strikes_active"] == 1
        assert org["standing"] == "SUSPENDED", \
            "a SUSPENDED organization stays SUSPENDED no matter how far the count falls"

        validate_success(api.reinstate_organization(org_id, ADMIN), 200)
        org = get_organization(org_id)
        assert org["standing"] == "GOOD", \
            "reinstate SUSPENDED -> PROBATION, then the follow-on to GOOD fires (1 < 2)"

    def test_reinstate_stays_probation_when_count_still_two(self, api):
        """PRD §3.1: "Rescission recomputes `no_show_strikes_active` and re-evaluates
        standing immediately: a `PROBATION` organization whose active count has fallen
        below 2 returns to `GOOD` automatically, while a `SUSPENDED` organization
        stays `SUSPENDED` no matter how far the count falls — only an explicit
        administrative reinstatement lifts a suspension, moving the organization
        `SUSPENDED` → `PROBATION`. Reinstatement itself re-evaluates standing within
        the same request, so when the active count is already below 2 the follow-on
        `PROBATION` → `GOOD` transition fires immediately as part of that request."

        With the count at exactly 2 (not below 2), the follow-on does not fire and
        the organization remains PROBATION after reinstatement.

        Design: Difficulty/non_linear_state_machine/organization_standing_cycle_with_reinstate
        """
        ctx = setup_suspended_org()
        org_id = ctx["organization"]["id"]
        strikes = list_strikes(org_id)
        validate_success(api.rescind_strike(strikes[0]["id"], ADMIN), 200)
        org = get_organization(org_id)
        assert org["no_show_strikes_active"] == 2
        assert org["standing"] == "SUSPENDED"

        validate_success(api.reinstate_organization(org_id, ADMIN), 200)
        org = get_organization(org_id)
        assert org["standing"] == "PROBATION", \
            "count 2 is not below 2: reinstate lands on PROBATION and stays"


class TestSuspensionRevocationCascade:
    def test_third_noshow_strike_points_and_suspension(self, api):
        """PRD §3.1: "When a field supervisor marks a confirmed permit as a no-show
        (§3.6), the system creates a StrikeRecord linking the `organization_id` to the
        offending `permit_id` and stores `strike_points` equal to ten times the
        organization's new active-strike count including the strike just created — a
        first strike records 10 points, a second records 20, a third records 30."
        PRD §3.6: "Marking fans out widely: the StrikeRecord of §3.1 is created and
        the organization's standing is re-evaluated with the full cascade; the
        invoice's `penalty_cents` is set to the full `deposit_cents` and the deposit
        waterfall of §3.8 runs, with any remaining total still owed; the season ledger
        releases the awarded hours and increments `no_show_count`; and the facility's
        `weekly_prime_hours_used` is recomputed. The permit ends in the terminal
        `NO_SHOW` state."

        Link 1-3 of the cascade: the third no-show writes 30 points and flips the
        organization to SUSPENDED.

        Design: Difficulty/transitive_cascade/noshow_strike_suspension_revocation_cascade
        """
        ctx = setup_org_with_confirmed_permits()
        record_no_shows(ctx, 2)
        org = get_organization(ctx["organization"]["id"])
        assert org["standing"] == "PROBATION"

        record_no_shows(ctx, 1, start=2)
        org = get_organization(ctx["organization"]["id"])
        assert org["no_show_strikes_active"] == 3
        assert org["standing"] == "SUSPENDED"
        strikes = list_strikes(ctx["organization"]["id"], status="ACTIVE")
        assert len(strikes) == 3
        assert strikes[2]["strike_points"] == 30, "third strike: 10 x 3"
        assert get_permit(ctx["permits"][2]["id"])["status"] == "NO_SHOW"

    def test_suspension_cascade_revokes_future_permit_forfeits_deposit(self, api):
        """PRD §3.1: "Suspension triggers the revocation cascade: every permit the
        organization holds in `RESERVED` or `CONFIRMED` status whose `permit_date`
        falls on or after the current logical date transitions to `REVOKED` under the
        fault code `ORG_FAULT`; each revoked permit's invoice runs the deposit
        waterfall of §3.8 with `penalty_cents` set to the full `deposit_cents` — the
        deposit is forfeited — while any remaining `balance_due_cents` stays owed; the
        released hours come out of the season's UsageLedger, with
        `awarded_prime_hours` and `awarded_nonprime_hours` decremented accordingly;
        each affected facility's `weekly_prime_hours_used` is recomputed; and every
        `WAITLISTED` application belonging to the organization is denied with
        `decision_note` `ORG_SUSPENDED`."

        The org's fourth permit (2026-08-15, fully paid 4000 with deposit 4000) is
        not the no-show permit, yet the standing flip revokes it: penalty 4000, the
        waterfall drains the 4000 held deposit entirely into the penalty bucket.

        Design: Difficulty/transitive_cascade/noshow_strike_suspension_revocation_cascade
        """
        ctx = setup_suspended_org()
        permit4 = get_permit(ctx["permits"][3]["id"])
        assert permit4["status"] == "REVOKED", \
            "the cascade revokes the org's other future CONFIRMED permit"

        invoice4 = get_invoice(ctx["invoices"][3]["id"])
        assert_invoice(invoice4)
        assert invoice4["penalty_cents"] == 4000, "deposit forfeited under ORG_FAULT"
        assert invoice4["deposit_penalty_applied_cents"] == 4000
        assert invoice4["deposit_balance_applied_cents"] == 0
        assert invoice4["deposit_refunded_cents"] == 0
        assert invoice4["balance_due_cents"] == 0
        assert_deposit_waterfall_conservation(invoice4)


class TestStrikeRescission:
    def test_strike_rescind_twice_rejected(self, api):
        """PRD §3.1: "An administrator may rescind an `ACTIVE` strike; attempting to
        rescind one already `RESCINDED` is rejected with `ERR_INVALID_STRIKE_STATE`."

        A second rescind of the same strike is rejected and the organization's count
        does not double-decrement.

        Design: Corner/state_machines/strike_rescind_twice_rejected
        """
        ctx = setup_org_with_confirmed_permits(dates=("2026-08-06",))
        record_no_shows(ctx, 1)
        org_id = ctx["organization"]["id"]
        strikes = list_strikes(org_id)
        assert len(strikes) == 1
        validate_success(api.rescind_strike(strikes[0]["id"], ADMIN), 200)
        assert get_organization(org_id)["no_show_strikes_active"] == 0

        res = api.rescind_strike(strikes[0]["id"], ADMIN)
        validate_error(res, ApiErrorId.ERR_INVALID_STRIKE_STATE)
        assert get_organization(org_id)["no_show_strikes_active"] == 0, \
            "rejected rescind must not decrement the count again"
