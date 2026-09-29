"""Settlement: the final-credit basis, the volume tier, and the two risk views."""

from test_helpers import (
    ApiErrorId,
    MANAGER_1,
    assert_account_balance_identity,
    assert_customer_statement,
    assert_deposit_ticket,
    count_bag,
    create_bag,
    create_ticket,
    deny_claim,
    deliver_bag_to_vault,
    extend_provisional_credit,
    file_claim,
    hold_payload,
    lot_entry,
    make_manager_headers,
    read_account,
    read_ticket,
    setup_counted_bag,
    setup_processing_center,
    setup_two_counted_bags,
    settle_ticket,
    validate_error,
    validate_success,
    verify_ticket,
    window_pair,
)

BAG_100_NOTES = {
    "declared_amount_cents": 100_000,
    "declared_note_count": 100,
    "counted_amount_cents": 100_000,
    "counted_note_count": 100,
}
BAG_300_NOTES = {
    "declared_amount_cents": 110_000,
    "declared_note_count": 300,
    "counted_amount_cents": 110_000,
    "counted_note_count": 300,
    "lots": [lot_entry("FIT", 500, 200), lot_entry("UNFIT", 100, 100)],
}
SHORT_BAG = {
    "declared_amount_cents": 102_500,
    "declared_note_count": 100,
    "counted_amount_cents": 100_000,
    "counted_note_count": 100,
}


class TestProvisionalAgainstFinalCredit:
    def test_the_final_basis_lands_on_a_different_number_than_the_provisional_one(self, api):
        """PRD §3.7: "Step one: add up `settlement_amount_cents` across every bag on this
        ticket whose counting axis reads `COUNTED` or `ADJUSTED`, giving the gross counted
        figure. This basis is what the machines actually found, plus any approved claim
        adjustment, minus any counterfeit seizure; it ignores every declared field."
        PRD §3.7: "Step three: multiply the ticket's `processing_fee_total_cents` by one
        minus the discount fraction and round the product half up to a whole number of cents,
        giving the final fee. Step four: the ticket's `final_settlement_cents` is the gross
        counted figure minus that final fee. Step five: the ticket's
        `settlement_delta_cents` is `final_settlement_cents` minus the ticket's
        `provisional_credit_cents` as it stands immediately before settlement unwinds it — a
        signed figure that is negative when the vault over-advanced against the declaration
        and positive when it under-advanced."

        Design: Difficulty/dual_variant_calc/deposit_credit_provisional_vs_final_diverge_on_same_ticket
        """
        scenario = setup_two_counted_bags(
            BAG_100_NOTES, BAG_300_NOTES, tier="STANDARD", credit_branch="provisional"
        )
        ticket_before = scenario["ticket"]
        assert ticket_before["provisional_credit_cents"] == 205_800, (
            "The PROVISIONAL variant takes 98% of the declared 210000, expected 205800, got "
            f"{ticket_before['provisional_credit_cents']}"
        )
        assert ticket_before["status"] == "SETTLEMENT_READY"

        settled = settle_ticket(ticket_before["id"])
        assert_deposit_ticket(settled)
        assert settled["final_settlement_cents"] == 209_485, (
            "210000 gross minus the undiscounted 515 fee = 209485, got "
            f"{settled['final_settlement_cents']}"
        )
        assert settled["settlement_delta_cents"] == 3_685, (
            f"209485 - 205800 = 3685, got {settled['settlement_delta_cents']}"
        )

    def test_settlement_retires_the_advance_and_collects_the_final_figure(self, api):
        """PRD §3.7: "The ledger movements at settlement run in a fixed order. The
        depositor's `provisional_credit_cents` is reduced by the ticket's
        `provisional_credit_cents`, and the ticket's own `provisional_credit_cents` is then
        reset to 0 — the uncollected advance is retired. The depositor's
        `ledger_balance_cents` is increased by the ticket's `final_settlement_cents` — the
        funds are now collected. The depositor's `available_balance_cents` is recomputed as
        `ledger_balance_cents` plus `provisional_credit_cents`."
        PRD §3.7: "A `VaultManager` settles it, moving the ticket `SETTLEMENT_READY →
        SETTLED`, which is terminal."

        Design: Difficulty/dual_variant_calc/deposit_credit_provisional_vs_final_diverge_on_same_ticket
        """
        scenario = setup_two_counted_bags(
            BAG_100_NOTES, BAG_300_NOTES, tier="STANDARD", credit_branch="provisional"
        )
        settled = settle_ticket(scenario["ticket"]["id"])

        assert settled["status"] == "SETTLED", f"Expected SETTLED, got {settled['status']}"
        assert settled["provisional_credit_cents"] == 0, (
            f"The ticket's advance is retired to 0, got {settled['provisional_credit_cents']}"
        )

        account = read_account(scenario["account"]["id"])
        assert account["ledger_balance_cents"] == 209_485, (
            f"Expected the collected 209485 on the ledger, got {account['ledger_balance_cents']}"
        )
        assert account["provisional_credit_cents"] == 0, (
            f"The account's advance is retired, got {account['provisional_credit_cents']}"
        )
        assert account["available_balance_cents"] == 209_485
        assert_account_balance_identity(account)


class TestVolumeDiscountTier:
    def test_the_tier_is_keyed_on_the_pre_fee_gross_counted_total(self, api):
        """PRD §3.7: "Step two: select the volume discount from that gross figure. A gross of
        at least 10,000,000 cents — one hundred thousand dollars — earns a twenty percent
        discount on the processing fee. Otherwise, a gross of at least 2,500,000 cents —
        twenty-five thousand dollars — earns a ten percent discount. Below that, there is no
        discount. Both comparisons are inclusive, so a gross landing exactly on 2,500,000
        cents earns the ten percent band and a gross landing exactly on 10,000,000 cents
        earns the twenty percent band. The tier is keyed on the gross figure from step one
        and on nothing else — not on the post-fee net, and not on the declared total — which
        is what pins the evaluation order of an otherwise circular-looking pair, since the fee
        reduces the total while the total selects the fee's discount."

        Design: Difficulty/combinatorial_formula/settlement_fee_tier_keyed_on_pre_fee_gross_counted_total
        """
        scenario = setup_counted_bag(
            declared_amount_cents=2_500_000,
            declared_note_count=250,
            counted_amount_cents=2_500_000,
            counted_note_count=250,
            lots=[lot_entry("FIT", 10_000, 250)],
            tier="STANDARD",
            credit_branch="provisional",
        )
        ticket = scenario["ticket"]
        assert ticket["processing_fee_total_cents"] == 259, (
            f"250 + 8.75 = 258.75 rounds to 259, got {ticket['processing_fee_total_cents']}"
        )
        assert ticket["counted_total_cents"] == 2_500_000

        settled = settle_ticket(ticket["id"])
        assert settled["final_settlement_cents"] == 2_499_767, (
            "A gross of exactly 2500000 earns the ten percent band, so the fee is 233 and "
            f"the settlement is 2499767, got {settled['final_settlement_cents']}"
        )

    def test_the_discounted_settlement_reaches_the_depositors_ledger(self, api):
        """PRD §3.7: "Step five: the ticket's `settlement_delta_cents` is
        `final_settlement_cents` minus the ticket's `provisional_credit_cents` as it stands
        immediately before settlement unwinds it — a signed figure that is negative when the
        vault over-advanced against the declaration and positive when it under-advanced."
        PRD §3.7: "The depositor's `ledger_balance_cents` is increased by the ticket's
        `final_settlement_cents` — the funds are now collected."
        PRD §3.3: "Second, select the availability haircut from the depositor's `tier`: a
        `PREMIUM` depositor takes no haircut at all, a `STANDARD` depositor takes a two
        percent haircut, and a `WATCH` depositor takes a five percent haircut."

        Design: Difficulty/combinatorial_formula/settlement_fee_tier_keyed_on_pre_fee_gross_counted_total
        """
        scenario = setup_counted_bag(
            declared_amount_cents=2_500_000,
            declared_note_count=250,
            counted_amount_cents=2_500_000,
            counted_note_count=250,
            lots=[lot_entry("FIT", 10_000, 250)],
            tier="STANDARD",
            credit_branch="provisional",
        )
        assert scenario["ticket"]["provisional_credit_cents"] == 2_450_000, (
            "98% of the declared 2500000 is 2450000, got "
            f"{scenario['ticket']['provisional_credit_cents']}"
        )

        settled = settle_ticket(scenario["ticket"]["id"])
        assert settled["settlement_delta_cents"] == 49_767, (
            f"2499767 - 2450000 = 49767, got {settled['settlement_delta_cents']}"
        )

        account = read_account(scenario["account"]["id"])
        assert account["ledger_balance_cents"] == 2_499_767
        assert account["available_balance_cents"] == 2_499_767
        assert_account_balance_identity(account)


def _settled_and_open_ticket_scenario():
    """One SETTLED clean ticket plus one SETTLEMENT_READY ticket short by 120000."""
    scenario = setup_processing_center(tier="STANDARD")
    vault_id = scenario["vault"]["id"]
    account_id = scenario["account"]["id"]
    machine_id = scenario["machine"]["id"]

    first_ticket = create_ticket(account_id, vault_id, declared_bag_count=1)
    first_bag = create_bag(
        first_ticket["id"],
        bag_type="CURRENCY",
        declared_amount_cents=100_000,
        declared_note_count=100,
        declared_coin_weight_grams=0,
    )
    deliver_bag_to_vault(first_bag["id"], first_bag["seal_number"])
    verify_ticket(first_ticket["id"])
    extend_provisional_credit(first_ticket["id"])
    first_window = window_pair(0)
    count_bag(
        first_bag["id"],
        first_bag["seal_number"],
        machine_id,
        100_000,
        100,
        window_start=first_window[0],
        window_end=first_window[1],
    )
    settle_ticket(first_ticket["id"])

    second_ticket = create_ticket(account_id, vault_id, declared_bag_count=1)
    second_bag = create_bag(
        second_ticket["id"],
        bag_type="CURRENCY",
        declared_amount_cents=200_000,
        declared_note_count=200,
        declared_coin_weight_grams=0,
    )
    deliver_bag_to_vault(second_bag["id"], second_bag["seal_number"])
    verify_ticket(second_ticket["id"])
    extend_provisional_credit(second_ticket["id"])
    second_window = window_pair(1)
    count_bag(
        second_bag["id"],
        second_bag["seal_number"],
        machine_id,
        80_000,
        80,
        window_start=second_window[0],
        window_end=second_window[1],
    )

    scenario["first_ticket"] = read_ticket(first_ticket["id"])
    scenario["second_ticket"] = read_ticket(second_ticket["id"])
    return scenario


class TestRiskModelViews:
    def test_the_statement_projects_a_lower_score_than_the_persisted_one(self, api):
        """PRD §3.7: "The `POINT_IN_TIME` view is the forward-looking one and is never
        persisted anywhere: its ticket input set is this depositor's tickets whose `status`
        is any of `VERIFIED`, `PROVISIONAL_CREDITED`, `HELD`, `SETTLEMENT_READY` or `SETTLED`
        — everything from verification onward, but not tickets still in `INTAKE` — and its
        counterfeit count is the account's `counterfeit_incident_count` plus the number of
        `DRAFT` counterfeit reports whose fitness lots are reachable from this account's
        bags."
        PRD §3.7: "otherwise the variance ratio is 100 multiplied by the absolute-variance
        total, divided by the declared total, and rounded half up to 2 decimal places."
        PRD §3.7: "The raw score then starts at 100 and subtracts three penalties: 1.5 points
        for each percentage point of variance ratio, 8 points for each counterfeit incident
        in the view, and 3 points for each denied claim on the account."
        PRD §3.7: "The letter band follows from the score: at least 80 is `A`, otherwise at
        least 60 is `B`, otherwise at least 40 is `C`, and anything below 40 is `D`."

        Design: Difficulty/dual_variant_calc/customer_risk_grade_settled_only_vs_point_in_time_diverge
        """
        scenario = _settled_and_open_ticket_scenario()

        statement = validate_success(
            api.get_customer_statement(
                scenario["account"]["id"], make_manager_headers(MANAGER_1)
            )
        )
        assert_customer_statement(statement)
        assert statement["risk_score"] == 100.00, (
            "The closed view sees only the clean SETTLED ticket, expected 100.00, got "
            f"{statement['risk_score']}"
        )
        assert statement["projected_risk_score"] == 40.00, (
            "The forward-looking view adds the 120000 variance over a 300000 declared total: "
            f"100 - 1.5 * 40.00 = 40.00, got {statement['projected_risk_score']}"
        )
        assert statement["projected_risk_grade"] == "C", (
            f"40.00 falls in the C band, got {statement['projected_risk_grade']}"
        )

    def test_the_persisted_grade_ignores_the_in_flight_variance(self, api):
        """PRD §3.7: "The `SETTLED_ONLY` view is the chronologically closed one and is the
        view that is ever persisted: its ticket input set is this depositor's tickets whose
        `status` is `SETTLED`, and its counterfeit count is the account's
        `counterfeit_incident_count`, which tallies `SUBMITTED` reports only. In-flight
        variance and unsent drafts are invisible to it."
        PRD §3.7: "Reading the account resource itself, by contrast, returns the stored
        balances and the stored `SETTLED_ONLY` grade without any projection."
        PRD §3.4: "Once no bag on the ticket remains outside `COUNTED` or `ADJUSTED`, the
        ticket moves itself to `SETTLEMENT_READY`."

        Design: Difficulty/dual_variant_calc/customer_risk_grade_settled_only_vs_point_in_time_diverge
        """
        scenario = _settled_and_open_ticket_scenario()

        account = read_account(scenario["account"]["id"])
        assert account["risk_score"] == 100.00, (
            f"The persisted score stays at 100.00, got {account['risk_score']}"
        )
        assert account["risk_grade"] == "A", f"Expected grade A, got {account['risk_grade']}"
        assert account["ledger_balance_cents"] == 99_746, (
            f"The first ticket settled at 100000 - 254 = 99746, got {account['ledger_balance_cents']}"
        )
        assert account["provisional_credit_cents"] == 196_000, (
            "The second ticket's advance of 98% of 200000 is still outstanding, got "
            f"{account['provisional_credit_cents']}"
        )
        assert scenario["second_ticket"]["status"] == "SETTLEMENT_READY", (
            f"The second ticket is counted but unsettled, got {scenario['second_ticket']['status']}"
        )


class TestSettlementGuardsAndTerminality:
    def test_an_open_material_variance_blocks_settlement_until_the_claim_is_decided(self, api):
        """PRD §3.7: "Exactly one business guard stands in the way: the ticket's
        `material_variance_open_count` must be 0. While even one flagged bag sits unresolved
        — neither adjusted by an approved claim nor released by a denied one — the settlement
        is refused with `ERR_MATERIAL_VARIANCE_UNRESOLVED`."
        PRD §3.6: "Two things do move: the depositor's `denied_claim_count` is incremented by
        1, which feeds directly into the risk model, and, if the bag carried
        `materiality_flag` true, the ticket's `material_variance_open_count` is decremented by
        1."
        PRD §3.6: "**Denying** the claim moves it `SUBMITTED → DENIED`, requires a
        `denial_reason` which is recorded, and records the deciding `X-User-ID` as
        `decided_by_user_id`. No money field on the bag moves at all —
        `claim_adjustment_cents` stays where it was and the bag's counting axis stays at
        `COUNTED`."

        Design: Corner/validations/material_variance_blocks_settlement_until_the_claim_is_decided
        """
        scenario = setup_counted_bag(**SHORT_BAG)
        ticket_id = scenario["ticket"]["id"]
        assert read_ticket(ticket_id)["material_variance_open_count"] == 1

        blocked = api.settle_deposit_ticket(ticket_id, make_manager_headers(MANAGER_1))
        validate_error(blocked, ApiErrorId.ERR_MATERIAL_VARIANCE_UNRESOLVED.value)
        assert blocked.status_code == 409

        claim = file_claim(scenario["bag"]["id"], scenario["account"]["id"], 2_500)
        denied = deny_claim(claim["id"], "Machine tape and customer tape agree; no shortage found.")
        assert denied["status"] == "DENIED", f"Expected DENIED, got {denied['status']}"

        released = read_ticket(ticket_id)
        assert released["material_variance_open_count"] == 0, (
            "Denial releases the settlement block, got "
            f"{released['material_variance_open_count']}"
        )
        bag = scenario["bag"]
        assert read_ticket(ticket_id)["counted_total_cents"] == 100_000
        assert validate_success(
            api.get_sealed_bag(bag["id"], make_manager_headers(MANAGER_1))
        )["claim_adjustment_cents"] == 0, "Denial moves no money field on the bag"

        settled = settle_ticket(ticket_id)
        assert settled["status"] == "SETTLED"
        assert settled["final_settlement_cents"] == 99_746, (
            f"100000 gross minus the 254 fee = 99746, got {settled['final_settlement_cents']}"
        )

        account = read_account(scenario["account"]["id"])
        assert account["denied_claim_count"] == 1, (
            f"The denial raises denied_claim_count to 1, got {account['denied_claim_count']}"
        )
        assert account["ledger_balance_cents"] == 99_746

    def test_a_settled_ticket_is_terminal_and_refuses_a_hold(self, api):
        """PRD §3.7: "A `VaultManager` settles it, moving the ticket `SETTLEMENT_READY →
        SETTLED`, which is terminal."
        PRD §2.6: "**Transition legality.** The target entity is in a state from which the
        requested transition is declared — `ERR_INVALID_STATE` (409)."
        PRD §3.3: "Placing a hold is a `VaultManager` decision and requires a free-text
        `hold_reason`, which is recorded on the ticket; the field is null until a hold is
        placed. A hold also increments the account's `hold_count` by 1."

        Design: Corner/state_machines/settled_ticket_is_terminal_and_rejects_hold
        """
        scenario = setup_counted_bag(tier="PREMIUM", credit_branch="provisional")
        settled = settle_ticket(scenario["ticket"]["id"])
        assert settled["status"] == "SETTLED"
        assert settled["final_settlement_cents"] == 99_746

        response = api.hold_deposit_ticket(
            scenario["ticket"]["id"],
            hold_payload("Late review request."),
            make_manager_headers(MANAGER_1),
        )
        validate_error(response, ApiErrorId.ERR_INVALID_STATE.value)
        assert response.status_code == 409

        ticket = read_ticket(scenario["ticket"]["id"])
        assert ticket["hold_reason"] is None, (
            f"The refused hold writes no reason, got {ticket['hold_reason']!r}"
        )
        account = read_account(scenario["account"]["id"])
        assert account["hold_count"] == 0, (
            f"The refused hold leaves hold_count at 0, got {account['hold_count']}"
        )
        assert account["ledger_balance_cents"] == 99_746

    def test_settlement_effects_are_visible_in_the_same_response(self, api):
        """PRD §3.7: "Step five: the ticket's `settlement_delta_cents` is
        `final_settlement_cents` minus the ticket's `provisional_credit_cents` as it stands
        immediately before settlement unwinds it — a signed figure that is negative when the
        vault over-advanced against the declaration and positive when it under-advanced."
        PRD §3.7: "The depositor's `available_balance_cents` is recomputed as
        `ledger_balance_cents` plus `provisional_credit_cents`. Finally the persisted risk
        figures are refreshed by running the `SETTLED_ONLY` view of the risk model onto
        `risk_score` and `risk_grade`."
        PRD §2.2: "Unless otherwise noted, operations that create or modify a resource will
        return the created or updated resource object in the data field."

        Design: Corner/consistency_model/settlement_side_effects_are_visible_in_the_same_response
        """
        scenario = setup_counted_bag(tier="PREMIUM", credit_branch="provisional")
        assert scenario["ticket"]["provisional_credit_cents"] == 100_000

        response = api.settle_deposit_ticket(
            scenario["ticket"]["id"], make_manager_headers(MANAGER_1)
        )
        settled = validate_success(response, 200)
        assert settled["final_settlement_cents"] == 99_746, (
            f"Expected final_settlement_cents 99746 in the settle response, got "
            f"{settled['final_settlement_cents']}"
        )
        assert settled["provisional_credit_cents"] == 0, (
            "The settle response already shows the retired advance"
        )
        assert settled["settlement_delta_cents"] == -254, (
            f"99746 - 100000 = -254, got {settled['settlement_delta_cents']}"
        )

        account = read_account(scenario["account"]["id"])
        assert account["ledger_balance_cents"] == 99_746, (
            "A read issued straight afterwards already shows the collected funds"
        )
        assert account["provisional_credit_cents"] == 0
        assert account["available_balance_cents"] == 99_746
        assert account["risk_score"] == 100.00, (
            f"The clean settled ticket leaves the score at 100.00, got {account['risk_score']}"
        )
        assert_account_balance_identity(account)
