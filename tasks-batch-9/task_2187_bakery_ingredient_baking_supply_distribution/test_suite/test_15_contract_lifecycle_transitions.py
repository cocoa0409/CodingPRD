"""The forward-contract state machine: offer, counter, the round cap and lockdown (PRD §3.2)."""

from test_helpers import (
    FLOUR_HRW_INDEXED,
    ApiErrorId,
    activate_contract,
    add_contract_line,
    api_client,
    counter_contract,
    create_customer,
    create_product,
    draft_contract,
    offer_contract,
    read_contract,
    read_contract_line,
    set_clock,
    terminate_contract_payload,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import AM, PC
from test_helpers.test_users import make_account_manager_headers

TERM_START = "2026-08-01T00:00:00Z"
TERM_END = "2026-12-31T00:00:00Z"


def _drafted_contract_with_one_line(volume_committed_lb=10000, basis_cents_per_lb=5):
    """A DRAFT contract for one indexed SKU, never offered."""
    set_clock("2026-08-01T00:00:00Z")
    customer = create_customer(credit_limit_cents=5000000, min_drop_cents=25000)
    flour = create_product(
        FLOUR_HRW_INDEXED, sku="FLR-HRW-50", list_price_cents_per_lb=30
    )
    contract = draft_contract(
        customer,
        term_start_on=TERM_START,
        term_end_on=TERM_END,
        pricing_mode="ORDER_DATE_INDEX",
    )
    contract_line = add_contract_line(
        contract["id"],
        flour["id"],
        volume_committed_lb=volume_committed_lb,
        basis_cents_per_lb=basis_cents_per_lb,
    )
    return {
        "customer": customer,
        "flour": flour,
        "contract": contract,
        "contract_line": contract_line,
    }


class TestOfferingADraft:
    """`DRAFT → OFFERED`, its preconditions and its three side effects."""

    def test_offering_a_drafted_contract_leaves_the_negotiation_round_at_zero(self):
        """PRD §3.2: "Offering the contract moves it from `DRAFT` to `OFFERED`. The
        account manager may only do so when the contract is genuinely in `DRAFT`,
        when at least one commitment line exists, and when `term_end_on` is
        strictly later than `term_start_on`."

        PRD §3.2: "Activation records the acting controller in
        `approved_by_user_id` and increments `version` by 1; that field is null on
        every contract that has not yet been activated."

        Design: Corner/state_machines/corner_offer_draft_contract_transitions_to_offered
        """
        scenario = _drafted_contract_with_one_line()
        assert scenario["contract"]["status"] == "DRAFT", (
            f"Expected DRAFT before the offer, got {scenario['contract']['status']}"
        )

        offered = validate_success(
            api_client.offer_forward_contract(scenario["contract"]["id"], {}, AM)
        )

        assert offered["status"] == "OFFERED", (
            f"Expected OFFERED, got {offered['status']}"
        )
        assert offered["negotiation_round"] == 0, (
            f"The first offer is not a re-offer, so expected 0, got {offered['negotiation_round']}"
        )
        assert offered["approved_by_user_id"] is None, (
            f"Expected approved_by_user_id null, got {offered['approved_by_user_id']}"
        )
        assert read_contract(scenario["contract"]["id"])["status"] == "OFFERED"

    def test_the_offer_records_its_author_and_totals_both_commitment_lines(self):
        """PRD §3.2: "The offer records the acting operator in
        `authored_by_user_id`, recomputes `committed_volume_lb` from the contract's
        lines, and increments `version` by 1."

        PRD §3.2: "A line's `volume_drawn_lb` starts at 0."

        Design: Corner/state_machines/corner_offer_side_effects_set_author_and_committed_volume
        """
        set_clock("2026-08-01T00:00:00Z")
        am7 = make_account_manager_headers("am-7")
        customer = create_customer(legal_name="Two Line Bakery", credit_limit_cents=5000000)
        flour = create_product(
            FLOUR_HRW_INDEXED, sku="FLR-HRW-50", list_price_cents_per_lb=30
        )
        sugar = create_product(
            sku="SUG-CANE-50",
            category="INCLUSION",
            allergen_class="NONE",
            shelf_life_days=720,
            index_code="CANE_SUGAR",
            list_price_cents_per_lb=45,
        )
        contract = validate_success(
            api_client.create_forward_contract(
                {
                    "customer_id": customer["id"],
                    "term_start_on": TERM_START,
                    "term_end_on": TERM_END,
                    "pricing_mode": "ORDER_DATE_INDEX",
                },
                am7,
            ),
            201,
        )
        for product_id, volume in ((flour["id"], 10000), (sugar["id"], 4000)):
            validate_success(
                api_client.create_contract_line(
                    contract["id"],
                    {
                        "product_id": product_id,
                        "volume_committed_lb": volume,
                        "basis_cents_per_lb": 5 if volume == 10000 else -20,
                    },
                    am7,
                ),
                201,
            )
        version_before = read_contract(contract["id"])["version"]

        offered = validate_success(
            api_client.offer_forward_contract(contract["id"], {}, am7)
        )

        assert offered["authored_by_user_id"] == "am-7", (
            f"Expected the acting operator recorded, got {offered['authored_by_user_id']}"
        )
        assert offered["committed_volume_lb"] == 14000, (
            f"Expected 10000 + 4000 = 14000, got {offered['committed_volume_lb']}"
        )
        assert offered["drawn_volume_lb"] == 0, (
            f"Expected drawn_volume_lb 0, got {offered['drawn_volume_lb']}"
        )
        assert offered["version"] == version_before + 1, (
            f"Expected version {version_before + 1}, got {offered['version']}"
        )


class TestActivationRequiresAnOffer:
    """`OFFERED → ACTIVE` is the only arc into `ACTIVE`."""

    def test_activating_a_contract_that_was_never_offered_is_refused(self):
        """PRD §3.2: "Only a `PricingController` may move a contract from `OFFERED`
        to `ACTIVE`, and four conditions must hold: the contract is in `OFFERED`;
        the acting operator's `X-User-ID` differs from the contract's
        `authored_by_user_id`; the bakery's own `status` is `ACTIVE` rather than
        `CREDIT_HOLD`; and no other contract for the same bakery that is already
        `ACTIVE` overlaps the interval from `term_start_on` to `term_end_on` on any
        shared `product_id`."

        PRD §2.7: "Only after all of that do state and business checks run, in this
        order: the target resource's own state-transition legality".

        Design: Corner/state_machines/corner_activate_draft_contract_invalid_transition_rejected
        """
        scenario = _drafted_contract_with_one_line()

        response = api_client.activate_forward_contract(
            scenario["contract"]["id"], {}, PC
        )

        validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        assert response.status_code == 409, (
            f"Expected HTTP 409, got {response.status_code}"
        )
        contract = read_contract(scenario["contract"]["id"])
        assert contract["status"] == "DRAFT", (
            f"Expected the contract still DRAFT, got {contract['status']}"
        )
        assert contract["approved_by_user_id"] is None, (
            f"Expected approved_by_user_id still null, got {contract['approved_by_user_id']}"
        )


class TestNegotiationCycle:
    """`OFFERED → COUNTERED → OFFERED` returns to a held state and advances the round."""

    def test_re_offering_a_countered_contract_advances_the_round_and_keeps_the_counter_basis(self):
        """PRD §3.2: "The counter carries a single `counter_basis_cents_per_lb`,
        and that value replaces `basis_cents_per_lb` on **every** line of the
        contract, not merely on one."

        PRD §3.2: "Re-offering a `COUNTERED` contract is permitted only while
        `negotiation_round` is strictly less than 3; the re-offer increments
        `negotiation_round` by 1, re-records `authored_by_user_id` as the operator
        who re-offered, and increments `version` by 1."

        Design: Corner/state_machines/corner_counter_then_reoffer_increments_negotiation_round
        """
        scenario = _drafted_contract_with_one_line()
        offer_contract(scenario["contract"]["id"])
        countered = counter_contract(
            scenario["customer"], scenario["contract"]["id"], -40
        )
        assert countered["status"] == "COUNTERED", (
            f"Expected COUNTERED, got {countered['status']}"
        )

        reoffered = validate_success(
            api_client.offer_forward_contract(scenario["contract"]["id"], {}, AM)
        )

        assert reoffered["status"] == "OFFERED", (
            f"Expected the contract back at OFFERED, got {reoffered['status']}"
        )
        assert reoffered["negotiation_round"] == 1, (
            f"Expected negotiation_round 1, got {reoffered['negotiation_round']}"
        )
        line = read_contract_line(scenario["contract_line"]["id"])
        assert line["basis_cents_per_lb"] == -40, (
            f"Expected the buyer's -40 basis to stand, got {line['basis_cents_per_lb']}"
        )
        assert line["volume_committed_lb"] == 10000, (
            f"Expected the commitment untouched, got {line['volume_committed_lb']}"
        )
        assert line["volume_drawn_lb"] == 0, (
            f"Expected volume_drawn_lb 0, got {line['volume_drawn_lb']}"
        )

    def test_a_fourth_re_offer_is_refused_once_the_round_counter_reaches_three(self):
        """PRD §3.2: "A fourth attempt — that is, an attempt made when
        `negotiation_round` has already reached 3 — is rejected with
        `ERR_ROUND_LIMIT_REACHED` (HTTP 409)."

        PRD §3.2: "Negotiation is a genuine cycle: `OFFERED → COUNTERED →
        OFFERED`, and it is bounded."

        Design: Corner/state_machines/corner_fourth_reoffer_beyond_round_cap_rejected
        """
        scenario = _drafted_contract_with_one_line()
        offer_contract(scenario["contract"]["id"])
        for basis in (-10, -20, -30):
            counter_contract(scenario["customer"], scenario["contract"]["id"], basis)
            offer_contract(scenario["contract"]["id"])
        countered = counter_contract(
            scenario["customer"], scenario["contract"]["id"], -45
        )
        assert countered["negotiation_round"] == 3, (
            f"Expected three completed cycles, got {countered['negotiation_round']}"
        )

        response = api_client.offer_forward_contract(
            scenario["contract"]["id"], {}, AM
        )

        validate_error(response, ApiErrorId.ERR_ROUND_LIMIT_REACHED)
        assert response.status_code == 409, (
            f"Expected HTTP 409, got {response.status_code}"
        )
        contract = read_contract(scenario["contract"]["id"])
        assert contract["status"] == "COUNTERED", (
            f"Expected the contract stuck at COUNTERED, got {contract['status']}"
        )
        assert contract["negotiation_round"] == 3, (
            f"A refused re-offer must not advance the counter, got {contract['negotiation_round']}"
        )


class TestTerminalStateLockdown:
    """`TERMINATED` is terminal, so no arc leaves it."""

    def test_a_terminated_contract_refuses_a_further_offer(self):
        """PRD §3.2: "`TERMINATED` and `EXPIRED` are the two terminal states of the
        contract lifecycle; a contract reaching either is done, and any further
        action on it is rejected with `ERR_INVALID_STATE_TRANSITION` (HTTP 409)."

        PRD §3.2: "A `PricingController` may terminate a contract that sits in
        `DRAFT`, `OFFERED`, `COUNTERED`, or `ACTIVE`, supplying a `reason`; the
        contract moves to `TERMINATED` and its `version` increments by 1."

        Design: Corner/state_machines/corner_terminated_contract_rejects_further_offer
        """
        scenario = _drafted_contract_with_one_line()
        offer_contract(scenario["contract"]["id"])
        activated = activate_contract(scenario["contract"]["id"])
        assert activated["approved_by_user_id"] == "pc-1", (
            f"Expected the activating controller recorded, got {activated['approved_by_user_id']}"
        )
        terminated = validate_success(
            api_client.terminate_forward_contract(
                scenario["contract"]["id"],
                terminate_contract_payload(reason="Bakery moved volume to a competitor"),
                PC,
            )
        )
        assert terminated["status"] == "TERMINATED", (
            f"Expected TERMINATED, got {terminated['status']}"
        )

        response = api_client.offer_forward_contract(
            scenario["contract"]["id"], {}, AM
        )

        validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        assert response.status_code == 409, (
            f"Expected HTTP 409, got {response.status_code}"
        )
        contract = read_contract(scenario["contract"]["id"])
        assert contract["status"] == "TERMINATED", (
            f"Expected the contract to stay TERMINATED, got {contract['status']}"
        )
        assert contract["negotiation_round"] == 0, (
            f"No negotiation cycle ever ran, so expected 0, got {contract['negotiation_round']}"
        )
        assert contract["approved_by_user_id"] == "pc-1", (
            f"Termination does not clear the approver, got {contract['approved_by_user_id']}"
        )
