"""Credit-balance election waterfall, revocation windows, and conserved quantities."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    create_plan,
    register_prep_and_review_actuaries,
    get_plan,
    get_plan_version,
    get_demand,
    get_ledger,
    create_election,
    create_payment,
    list_elections_for_demand,
    list_elections_for_plan,
    set_clock,
    setup_certified_plan,
    api_client,
)

PLAN_ADMIN = TEST_USERS["plan_admin_headers"]

FAMILY_A_ROWS = [
    {"external_ref": "A1", "date_of_birth": "1966-03-10", "status": "ACTIVE",
     "years_of_service": 10, "annual_compensation": 100000},
    {"external_ref": "A2", "date_of_birth": "1968-11-20", "status": "ACTIVE",
     "years_of_service": 5, "annual_compensation": 60000},
    {"external_ref": "R1", "date_of_birth": "1965-01-30", "status": "RETIREE",
     "current_annual_benefit": 50000},
]


def _family_a(sponsor, carryover=2000, prefunding=3000):
    return setup_certified_plan(
        sponsor_name=sponsor,
        participant_rows=FAMILY_A_ROWS,
        market_value_begin=60000, contributions_received=0,
        benefits_paid=2000, investment_return=3000,
        initial_carryover_balance=carryover,
        initial_prefunding_balance=prefunding,
        prior_aftap_pct=84.00,
    )


class TestElectionWindowConflict:
    def test_constraint_beats_fiscal_on_election_window_conflict(self, api):
        """PRD §2.8: checks execute in a fixed priority order ... "the election-window
        conflict (`ERR_ELECTION_WINDOW_CONFLICT`)" (temporal) precedes "the fiscal
        limits (`ERR_CREDIT_BALANCE_EXCEEDED`, `ERR_OVERPAYMENT`)".
        PRD §3.8: "if another `EFFECTIVE` election on the same demand was created
        less than twenty-one days ago ... the new election is rejected with
        `ERR_ELECTION_WINDOW_CONFLICT` (HTTP 409)".

        Design: Difficulty/priority_pair_validation_conflict/constraint_beats_fiscal_on_election_window_conflict
        """
        set_clock("2028-03-01T00:00:00Z")
        fx = _family_a("Conflict Co")
        demand = fx["demand"]
        plan_id = fx["plan"]["id"]
        create_election(plan_id, demand["id"], 1000.00)  # pool now 4000

        set_clock("2028-03-11T00:00:00Z")  # inside E1's 21-day window
        plan_v = get_plan_version(plan_id)
        resp = api.create_credit_balance_election(
            plan_id,
            {"contribution_demand_id": demand["id"], "amount": 99999,
             "expected_plan_version": plan_v},
            PLAN_ADMIN,
        )
        # 99999 also exceeds the remaining pool — but the window conflict fires first
        validate_error(resp, ApiErrorId.ERR_ELECTION_WINDOW_CONFLICT, 409)
        # No second election persisted
        elections = list_elections_for_demand(demand["id"])
        assert len(elections) == 1

    def test_election_window_conflict_inside_window(self, api):
        """PRD §3.8: "if another `EFFECTIVE` election on the same demand was created
        less than twenty-one days ago — that is, its revocation window, running
        from its creation up to but not including the instant twenty-one days
        later, is still open — the new election is rejected with
        `ERR_ELECTION_WINDOW_CONFLICT` (HTTP 409)".

        Design: Difficulty/priority_pair_validation_conflict/constraint_beats_fiscal_on_election_window_conflict
        """
        set_clock("2028-03-01T00:00:00Z")
        fx = _family_a("Conflict 2 Co")
        demand = fx["demand"]
        plan_id = fx["plan"]["id"]
        create_election(plan_id, demand["id"], 1000.00)

        set_clock("2028-03-10T00:00:00Z")
        plan_v = get_plan_version(plan_id)
        resp = api.create_credit_balance_election(
            plan_id,
            {"contribution_demand_id": demand["id"], "amount": 100.00,
             "expected_plan_version": plan_v},
            PLAN_ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_ELECTION_WINDOW_CONFLICT, 409)


class TestElectionRevocationWindowBoundary:
    def test_election_revocation_window_relative_duration(self, api):
        """PRD §3.8: "its revocation window, running from its creation up to but
        not including the instant twenty-one days later, is still open — the new
        election is rejected with `ERR_ELECTION_WINDOW_CONFLICT` (HTTP 409); an
        earlier election whose window closed at exactly the twenty-one-day mark
        does not block."

        Design: Difficulty/resource_temporal_overlap/election_revocation_window_relative_duration
        """
        set_clock("2028-03-01T00:00:00Z")
        fx = _family_a("Window Co")
        demand = fx["demand"]
        plan_id = fx["plan"]["id"]
        e1 = create_election(plan_id, demand["id"], 500.00)

        # Just inside the window (2028-03-21T23:59:59Z): conflict
        set_clock("2028-03-21T23:59:59Z")
        plan_v = get_plan_version(plan_id)
        resp = api.create_credit_balance_election(
            plan_id,
            {"contribution_demand_id": demand["id"], "amount": 100.00,
             "expected_plan_version": plan_v},
            PLAN_ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_ELECTION_WINDOW_CONFLICT, 409)

        # At exactly +21 days (2028-03-22T00:00:00Z): window closed, election succeeds
        set_clock("2028-03-22T00:00:00Z")
        e2 = create_election(plan_id, demand["id"], 100.00)
        assert e2["status"] == "EFFECTIVE"
        # Ledger total drawn = 500 + 100 = 600
        ledger = get_ledger(plan_id)
        assert ledger["total_applied_to_date"] == 600.00

    def test_election_window_adjacency_permitted_at_exactly_21_days(self, api):
        """PRD §3.8: "an earlier election whose window closed at exactly the
        twenty-one-day mark does not block."
        PRD §3.8: the revocation window runs "from its creation up to but not
        including the instant twenty-one days later".

        Design: Difficulty/resource_temporal_overlap/election_revocation_window_relative_duration
        """
        set_clock("2028-03-01T00:00:00Z")
        fx = _family_a("Window 2 Co")
        demand = fx["demand"]
        plan_id = fx["plan"]["id"]
        e1 = create_election(plan_id, demand["id"], 500.00)
        assert e1["status"] == "EFFECTIVE"

        # Exactly +21 days: the earlier window has closed, so a new election is permitted
        set_clock("2028-03-22T00:00:00Z")
        e2 = create_election(plan_id, demand["id"], 200.00)
        assert e2["status"] == "EFFECTIVE"
        elections = list_elections_for_demand(demand["id"])
        assert len(elections) == 2

    def test_revoke_window_expired_rejected(self, api):
        """PRD §3.8: "Revocation — `EFFECTIVE` → `REVOKED`, terminal — is permitted
        only while the logical clock is strictly before `revoke_deadline`; at or
        after that instant the attempt is rejected with
        `ERR_REVOCATION_WINDOW_EXPIRED` (HTTP 422)."
        PRD §3.8: "The election is born `EFFECTIVE`, with `revoke_deadline`
        computed as its `created_at` plus twenty-one days."

        Design: Corner/validations/revoke_window_expired_rejected
        """
        set_clock("2028-03-01T00:00:00Z")
        fx = _family_a("Revoke Co")
        demand = fx["demand"]
        e1 = create_election(fx["plan"]["id"], demand["id"], 1000.00)

        # Exactly created_at + 21 days -> not strictly before -> rejected
        set_clock("2028-03-22T00:00:00Z")
        resp = api.revoke_credit_balance_election(e1["id"], PLAN_ADMIN)
        validate_error(resp, ApiErrorId.ERR_REVOCATION_WINDOW_EXPIRED, 422)
        # Election remains EFFECTIVE
        elections = list_elections_for_plan(fx["plan"]["id"])
        assert elections[0]["status"] == "EFFECTIVE"


class TestElectionOnSatisfiedDemand:
    def test_election_requires_demand_not_satisfied(self, api):
        """PRD §2.8: "the generic from-state validity of the target entity —
        rejected as `ERR_INVALID_STATE` (HTTP 409) when, for example, a payment is
        posted to an already `SATISFIED` demand".
        PRD §3.7: "the same zeroing moves a `PARTIALLY_SATISFIED` demand to
        `SATISFIED`" — an election against a SATISFIED demand fails the state gate.

        Design: Difficulty/cross_entity_state_dependency/election_requires_demand_not_satisfied
        """
        fx = _family_a("Demand Gate Co")
        demand = fx["demand"]
        plan_id = fx["plan"]["id"]
        create_election(plan_id, demand["id"], 2839.98)
        assert get_demand(demand["id"])["status"] == "SATISFIED"

        set_clock("2028-04-01T00:00:00Z")
        plan_v = get_plan_version(plan_id)
        resp = api.create_credit_balance_election(
            plan_id,
            {"contribution_demand_id": demand["id"], "amount": 100.00,
             "expected_plan_version": plan_v},
            PLAN_ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
        elections = list_elections_for_demand(demand["id"])
        assert len(elections) == 1

    def test_election_on_satisfied_demand_keeps_single_row(self, api):
        """PRD §3.7: "the same zeroing moves a `PARTIALLY_SATISFIED` demand to
        `SATISFIED`"; a SATISFIED demand rejects further offsets at the state gate
        (`ERR_INVALID_STATE`, §2.8).

        Design: Difficulty/cross_entity_state_dependency/election_requires_demand_not_satisfied
        """
        fx = _family_a("Demand Gate 2 Co")
        demand = fx["demand"]
        plan_id = fx["plan"]["id"]
        create_election(plan_id, demand["id"], 2839.98)
        assert get_demand(demand["id"])["status"] == "SATISFIED"

        set_clock("2028-04-02T00:00:00Z")
        plan_v = get_plan_version(plan_id)
        resp = api.create_credit_balance_election(
            plan_id,
            {"contribution_demand_id": demand["id"], "amount": 50.00,
             "expected_plan_version": plan_v},
            PLAN_ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
        assert len(list_elections_for_demand(demand["id"])) == 1


class TestCompensatingInvariants:
    def test_credit_pool_conservation_across_create_revoke(self, api):
        """PRD §3.8: "A conserved quantity guards the ledger: across any
        create-and-revoke pair, the sum of `carryover_balance`,
        `prefunding_balance`, and `total_applied_to_date` is invariant, and no
        operation other than election creation and revocation ever mutates these
        fields."
        PRD §3.8: "Revocation restores the two pools in the same proportions
        recorded at draw time, reduces `total_applied_to_date` by the election
        amount".

        Design: Difficulty/compensating_invariant/credit_pool_conservation_across_create_revoke
        """
        set_clock("2028-03-01T00:00:00Z")
        fx = _family_a("Pool Co")
        plan_id = fx["plan"]["id"]
        demand = fx["demand"]
        # Baseline: 2000 + 3000 + 0 = 5000
        ledger0 = get_ledger(plan_id)
        assert ledger0["carryover_balance"] + ledger0["prefunding_balance"] + ledger0["total_applied_to_date"] == 5000.00

        e1 = create_election(plan_id, demand["id"], 1000.00)
        ledger1 = get_ledger(plan_id)
        # After create: carryover 1000, prefunding 3000, applied 1000 -> 5000
        assert ledger1["carryover_balance"] == 1000.00
        assert ledger1["prefunding_balance"] == 3000.00
        assert ledger1["total_applied_to_date"] == 1000.00
        assert ledger1["carryover_balance"] + ledger1["prefunding_balance"] + ledger1["total_applied_to_date"] == 5000.00

        api.revoke_credit_balance_election(e1["id"], PLAN_ADMIN)
        ledger2 = get_ledger(plan_id)
        # After revoke: back to 2000 + 3000 + 0 = 5000
        assert ledger2["carryover_balance"] == 2000.00
        assert ledger2["prefunding_balance"] == 3000.00
        assert ledger2["total_applied_to_date"] == 0.00
        elections = list_elections_for_plan(plan_id)
        assert elections[0]["status"] == "REVOKED"

    def test_credit_pool_conservation_create_only(self, api):
        """PRD §3.8: "the sum of `carryover_balance`, `prefunding_balance`, and
        `total_applied_to_date` is invariant, and no operation other than election
        creation and revocation ever mutates these fields."
        PRD §3.8: "Each pool is reduced by the amount drawn from it,
        `total_applied_to_date` increases by the election amount".

        Design: Difficulty/compensating_invariant/credit_pool_conservation_across_create_revoke
        """
        set_clock("2028-03-01T00:00:00Z")
        fx = _family_a("Pool 2 Co")
        plan_id = fx["plan"]["id"]
        demand = fx["demand"]
        # Waterfall: 1500 drains carryover (2000 -> 500) only, prefunding untouched
        create_election(plan_id, demand["id"], 1500.00)
        ledger = get_ledger(plan_id)
        assert ledger["carryover_balance"] == 500.00
        assert ledger["prefunding_balance"] == 3000.00
        assert ledger["total_applied_to_date"] == 1500.00
        assert ledger["carryover_balance"] + ledger["prefunding_balance"] + ledger["total_applied_to_date"] == 5000.00

    def test_demand_satisfaction_identity_across_payment_and_revocation(self, api):
        """PRD §3.7: "`outstanding_amount` is `minimum_due` minus `paid_to_date`";
        "`minimum_due` is `tentative_minimum` minus `credit_applied`" — so
        credit_applied + paid_to_date + outstanding_amount == tentative_minimum.
        PRD §3.8: revocation "recomputes the demand — which may pull a `SATISFIED`
        demand back out of satisfaction when the outstanding amount becomes
        positive again, compensating the original offset."

        Design: Difficulty/compensating_invariant/demand_satisfaction_identity_across_payment_and_revocation
        """
        set_clock("2028-03-01T00:00:00Z")
        fx = _family_a("Identity Co")
        plan_id = fx["plan"]["id"]
        demand = fx["demand"]
        demand_id = demand["id"]
        tentative = demand["tentative_minimum"]  # 2839.98

        # Cash payment 500.00
        create_payment(demand_id, 500.00, paid_on="2028-05-01")
        d = get_demand(demand_id)
        assert d["paid_to_date"] == 500.00
        assert d["outstanding_amount"] == 2339.98
        assert d["credit_applied"] + d["paid_to_date"] + d["outstanding_amount"] == pytest.approx(tentative, abs=0.005)

        # Election 1000.00
        e1 = create_election(plan_id, demand_id, 1000.00)
        d = get_demand(demand_id)
        assert d["credit_applied"] == 1000.00
        assert d["outstanding_amount"] == 1339.98
        assert d["credit_applied"] + d["paid_to_date"] + d["outstanding_amount"] == pytest.approx(tentative, abs=0.005)

        # Revoke -> outstanding returns to 2339.98
        api.revoke_credit_balance_election(e1["id"], PLAN_ADMIN)
        d = get_demand(demand_id)
        assert d["credit_applied"] == 0.00
        assert d["outstanding_amount"] == 2339.98
        assert d["credit_applied"] + d["paid_to_date"] + d["outstanding_amount"] == pytest.approx(tentative, abs=0.005)
        assert d["status"] == "PARTIALLY_SATISFIED"

    def test_demand_identity_holds_after_full_election_offset(self, api):
        """PRD §3.7: "`outstanding_amount` is `minimum_due` minus `paid_to_date`";
        "`minimum_due` is `tentative_minimum` minus `credit_applied`".
        PRD §3.7: "one that leaves the outstanding amount at exactly zero moves it
        straight to `SATISFIED`".

        Design: Difficulty/compensating_invariant/demand_satisfaction_identity_across_payment_and_revocation
        """
        set_clock("2028-03-01T00:00:00Z")
        fx = _family_a("Identity 2 Co")
        plan_id = fx["plan"]["id"]
        demand = fx["demand"]
        tentative = demand["tentative_minimum"]  # 2839.98

        # Offset the full tentative minimum by election
        create_election(plan_id, demand["id"], 2839.98)
        d = get_demand(demand["id"])
        # Identity: credit 2839.98 + paid 0 + outstanding 0 == tentative
        assert d["credit_applied"] == 2839.98
        assert d["paid_to_date"] == 0.00
        assert d["outstanding_amount"] == 0.00
        assert d["credit_applied"] + d["paid_to_date"] + d["outstanding_amount"] == pytest.approx(tentative, abs=0.005)
        assert d["status"] == "SATISFIED"
