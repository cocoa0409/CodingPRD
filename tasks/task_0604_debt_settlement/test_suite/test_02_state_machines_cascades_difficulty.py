"""Difficulty-queue tests for parallel/branching state machines and transitive
cascades (settlement completion, program drop)."""
import pytest
from test_helpers import (
    TEST_USERS, make_client_headers, validate_success, get_success_data,
    create_offer_payload, accept_offer_payload, create_lawsuit_payload,
    set_clock, create_client, create_program, create_debt, create_active_program,
    create_offer, accept_offer, fund_settlement, complete_settlement,
)

ADMIN = TEST_USERS["program_admin_headers"]
AGENT = TEST_USERS["negotiation_agent_headers"]


def _fund(api, program_id, client_id, months, amount=600, day=10, start=1):
    for i in range(months):
        m = start + i
        api.create_deposit(
            {"program_id": program_id, "scheduled_for": f"2026-{m:02d}-{day:02d}T00:00:00Z",
             "amount": amount}, make_client_headers(client_id))


# =========================================================================
# Difficulty/non_linear_state_machine
# =========================================================================
class TestParallelAndBranchingMachines:

    def test_program_phase_and_standing_advance_independently(self, api):
        """PRD §2.9: "Independently of where a program sits in its lifecycle, every
        program tracks an `account_standing` derived from its `missed_deposit_count`"
        PRD §2.9: "The moment the missed count reaches at least one but stays below three
        (a count of 1 or 2), standing becomes `DELINQUENT`"

        Design: Difficulty/non_linear_state_machine/program_parallel_phase_and_standing_dimensions
        """
        set_clock("2026-06-01T00:00:00Z")
        client = create_client(full_name="Para Llel", email="para@x.com", state_code="FL")
        program = create_program(client["id"], monthly_deposit_amount=600)
        create_debt(program["id"], creditor_name="Cred", account_number="P-1",
                   original_balance=5000)
        get_success_data(api.activate_program(program["id"], ADMIN))
        api.create_deposit(
            {"program_id": program["id"], "scheduled_for": "2026-06-15T00:00:00Z",
             "amount": 600, "status": "MISSED"}, ADMIN)
        prog = get_success_data(api.get_program(program["id"], ADMIN))
        assert prog["program_phase"] == "ACTIVE"
        assert prog["account_standing"] == "DELINQUENT"
        assert prog["missed_deposit_count"] == 1

    def test_missed_deposit_does_not_revert_program_phase(self, api):
        """PRD §3.4: "Once at least one debt is in place, a `ProgramAdmin` activates the program, advancing `program_phase` from `ENROLLING` to `ACTIVE`."
        PRD §2.9: "These standing transitions are computed automatically by the system whenever the missed count changes; they are never requested directly."

        Design: Difficulty/non_linear_state_machine/program_parallel_phase_and_standing_dimensions
        """
        set_clock("2026-06-01T00:00:00Z")
        client = create_client(full_name="Para Two", email="para2@x.com", state_code="FL")
        program = create_program(client["id"], monthly_deposit_amount=600)
        create_debt(program["id"], creditor_name="Cred", account_number="P-1",
                   original_balance=5000)
        get_success_data(api.activate_program(program["id"], ADMIN))
        api.create_deposit(
            {"program_id": program["id"], "scheduled_for": "2026-06-15T00:00:00Z",
             "amount": 600, "status": "MISSED"}, ADMIN)
        prog = get_success_data(api.get_program(program["id"], ADMIN))
        # standing moved but phase remained ACTIVE
        assert prog["account_standing"] == "DELINQUENT"
        assert prog["program_phase"] == "ACTIVE"

    def test_accept_offer_rejects_sibling_pending_offers(self, api):
        """PRD §3.6: "Acceptance moves the offer from `PENDING` to `ACCEPTED`, and as a side effect every sibling `PENDING` offer on the same debt is moved to `REJECTED` and the program's `version` is incremented by one."

        Design: Difficulty/non_linear_state_machine/offer_branching_fork_accept_rejects_siblings
        """
        set_clock("2026-06-01T00:00:00Z")
        client = create_client(full_name="For Kk", email="fork@x.com", state_code="CA")
        program = create_program(client["id"], monthly_deposit_amount=600, reserve_floor=0)
        debt = create_debt(program["id"], creditor_name="Cred", account_number="F-1",
                          original_balance=5000)
        activated = get_success_data(api.activate_program(program["id"], ADMIN))
        v1 = activated["version"]
        _fund(api, program["id"], client["id"], 5)
        offer_1 = create_offer(program["id"], debt["id"], offer_pct=0.40,
                              due_date="2026-07-01T00:00:00Z")
        offer_2 = create_offer(program["id"], debt["id"], offer_pct=0.45,
                              due_date="2026-12-01T00:00:00Z")
        accept_offer(offer_1["id"], v1)
        o2 = get_success_data(api.get_offer(offer_2["id"], AGENT))
        assert o2["status"] == "REJECTED"

    def test_accepted_offer_reaches_accepted_state(self, api):
        """PRD §3.6: "Acceptance moves the offer from `PENDING` to `ACCEPTED`, and as a side effect every sibling `PENDING` offer on the same debt is moved to `REJECTED` and the program's `version` is incremented by one."

        Design: Difficulty/non_linear_state_machine/offer_branching_fork_accept_rejects_siblings
        """
        set_clock("2026-06-01T00:00:00Z")
        client = create_client(full_name="Fork Two", email="fork2@x.com", state_code="CA")
        program = create_program(client["id"], monthly_deposit_amount=600, reserve_floor=0)
        debt = create_debt(program["id"], creditor_name="Cred", account_number="F-1",
                          original_balance=5000)
        activated = get_success_data(api.activate_program(program["id"], ADMIN))
        v1 = activated["version"]
        _fund(api, program["id"], client["id"], 5)
        offer_1 = create_offer(program["id"], debt["id"], offer_pct=0.40,
                              due_date="2026-07-01T00:00:00Z")
        create_offer(program["id"], debt["id"], offer_pct=0.45,
                    due_date="2026-12-01T00:00:00Z")
        accepted = accept_offer(offer_1["id"], v1)
        assert accepted["status"] == "ACCEPTED"


# =========================================================================
# Difficulty/transitive_cascade
# =========================================================================
class TestTransitiveCascades:

    def test_settlement_complete_cascades_debt_lawsuit_taxevent(self, api):
        """PRD §3.7: "The parent debt becomes `SETTLED`: its `settled_amount` is set to the settlement's `funded_amount`, its `forgiven_amount` becomes `original_balance` minus `funded_amount`, its `current_balance` falls to zero, and its `settled_offer_id` is set to the originating offer."
        PRD §3.7: "When the debt that completes was under an open `REFERRED` lawsuit, that lawsuit cascades to `RESOLVED_SETTLED`."
        PRD §3.7: "A `TaxEvent` is always issued whenever the forgiven amount is greater than zero."
        PRD §3.7: "a `reportable` flag that is true when the forgiven amount is at least 600 dollars (the IRS 1099-C reporting threshold)"

        Design: Difficulty/transitive_cascade/settlement_complete_cascade_debt_taxevent_lawsuit
        """
        set_clock("2026-06-01T00:00:00Z")
        client = create_client(full_name="Cas Cade", email="cas@x.com", state_code="OH")
        program = create_program(client["id"], monthly_deposit_amount=800, reserve_floor=0)
        debt = create_debt(program["id"], creditor_name="Cred", account_number="CC-6",
                          original_balance=6000)
        create_debt(program["id"], creditor_name="Filler", account_number="CC-4",
                   original_balance=4000)
        activated = get_success_data(api.activate_program(program["id"], ADMIN))
        v1 = activated["version"]
        lawsuit = get_success_data(api.create_lawsuit(
            create_lawsuit_payload(program["id"], debt["id"],
                                  court_reference="CASE-1", filed_at="2026-05-15T00:00:00Z"),
            ADMIN))
        _fund(api, program["id"], client["id"], 5, amount=800, day=5)
        offer = create_offer(program["id"], debt["id"], offer_pct=0.50,
                            due_date="2026-12-01T00:00:00Z")
        accept_offer(offer["id"], v1)
        settle = fund_settlement(program["id"], offer["id"])
        complete_settlement(settle["id"])

        debt_after = get_success_data(api.get_debt(debt["id"], ADMIN))
        assert debt_after["status"] == "SETTLED"
        lawsuit_after = get_success_data(api.get_lawsuit(lawsuit["id"], ADMIN))
        assert lawsuit_after["status"] == "RESOLVED_SETTLED"
        tes = get_success_data(api.list_tax_events(
            ADMIN, params={"source_settlement_id": settle["id"]}))
        assert len(tes) == 1
        te = tes[0]
        assert te["forgiven_amount"] == pytest.approx(3000.00, abs=0.01)
        assert te["reportable"] is True
        assert te["status"] == "ISSUED"

    def test_settlement_complete_issues_reportable_taxevent(self, api):
        """PRD §3.7: "Completion also issues a cancellation-of-debt tax record. The forgiven amount is the debt's `original_balance` minus the settlement's `funded_amount`."
        PRD §3.7: "a `reportable` flag that is true when the forgiven amount is at least 600 dollars (the IRS 1099-C reporting threshold) and false when it is greater than zero but below 600."

        Design: Difficulty/transitive_cascade/settlement_complete_cascade_debt_taxevent_lawsuit
        """
        set_clock("2026-06-01T00:00:00Z")
        client = create_client(full_name="Cas Two", email="cas2@x.com", state_code="OH")
        program = create_program(client["id"], monthly_deposit_amount=800, reserve_floor=0)
        debt = create_debt(program["id"], creditor_name="Cred", account_number="CC-6",
                          original_balance=6000)
        create_debt(program["id"], creditor_name="Filler", account_number="CC-4",
                   original_balance=4000)
        activated = get_success_data(api.activate_program(program["id"], ADMIN))
        v1 = activated["version"]
        get_success_data(api.create_lawsuit(
            create_lawsuit_payload(program["id"], debt["id"],
                                  court_reference="CASE-1", filed_at="2026-05-15T00:00:00Z"),
            ADMIN))
        _fund(api, program["id"], client["id"], 5, amount=800, day=5)
        offer = create_offer(program["id"], debt["id"], offer_pct=0.50,
                            due_date="2026-12-01T00:00:00Z")
        accept_offer(offer["id"], v1)
        settle = fund_settlement(program["id"], offer["id"])
        complete_settlement(settle["id"])
        tes = get_success_data(api.list_tax_events(
            ADMIN, params={"source_settlement_id": settle["id"]}))
        assert tes[0]["forgiven_amount"] == pytest.approx(3000.00, abs=0.01)
        assert tes[0]["reportable"] is True

    def test_program_drop_cascades_debt_withdrawn_and_offer_expired(self, api):
        """PRD §3.10: "The drop fires a cascade: every debt still in `ENROLLED`,
        `IN_NEGOTIATION`, or `LAWSUIT` is moved to the terminal `WITHDRAWN` status; each
        withdrawn debt's open `PENDING` offers are moved to `EXPIRED`"

        Design: Difficulty/transitive_cascade/program_drop_cascade_debts_offers
        """
        set_clock("2026-06-01T00:00:00Z")
        client = create_client(full_name="Dro Pp", email="drop@x.com", state_code="CA")
        program = create_program(client["id"], monthly_deposit_amount=600)
        debt = create_debt(program["id"], creditor_name="Cred", account_number="D-1",
                          original_balance=5000)
        get_success_data(api.activate_program(program["id"], ADMIN))
        offer = create_offer(program["id"], debt["id"], offer_pct=0.40,
                            due_date="2026-12-01T00:00:00Z")
        drop_res = api.drop_program(program["id"], make_client_headers(client["id"]))
        dropped = validate_success(drop_res, 200)
        assert dropped["program_phase"] == "TERMINATED"
        debt_after = get_success_data(api.get_debt(debt["id"], ADMIN))
        assert debt_after["status"] == "WITHDRAWN"
        offer_after = get_success_data(api.get_offer(offer["id"], ADMIN))
        assert offer_after["status"] == "EXPIRED"

    def test_program_drop_withdraws_open_debt(self, api):
        """PRD §3.10: "every debt still in `ENROLLED`, `IN_NEGOTIATION`, or `LAWSUIT` is moved
        to the terminal `WITHDRAWN` status; each withdrawn debt's open `PENDING` offers are
        moved to `EXPIRED`"

        Design: Difficulty/transitive_cascade/program_drop_cascade_debts_offers
        """
        set_clock("2026-06-01T00:00:00Z")
        client = create_client(full_name="Drop Two", email="drop2@x.com", state_code="CA")
        program = create_program(client["id"], monthly_deposit_amount=600)
        debt = create_debt(program["id"], creditor_name="Cred", account_number="D-1",
                          original_balance=5000)
        get_success_data(api.activate_program(program["id"], ADMIN))
        create_offer(program["id"], debt["id"], offer_pct=0.40,
                    due_date="2026-12-01T00:00:00Z")
        api.drop_program(program["id"], make_client_headers(client["id"]))
        debt_after = get_success_data(api.get_debt(debt["id"], ADMIN))
        assert debt_after["status"] == "WITHDRAWN"
