"""Cyclic state machines: the negotiation loop and the invoice credit revert."""

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    counter_contract,
    create_program,
    create_sent_contract,
    create_supplier,
    make_supplier_headers,
    resend_contract,
    reset_clock,
    setup_invoiced_program,
    validate_error,
    validate_success,
)

PD = TEST_USERS["program_director_headers"]
SM = TEST_USERS["supplier_manager_headers"]
CTRL = TEST_USERS["controller_headers"]

CREDIT_REASON = (
    "Client disputed the venue service charge; invoice withdrawn for re-reconciliation."
)


def _contract_at_the_round_ceiling():
    """Drive one contract through send/counter/send/counter/send so round_count is 3."""
    reset_clock()
    supplier = create_supplier(
        legal_name="Metro Motorcoach Co", supplier_type="TRANSPORT"
    )
    program = create_program(
        client_name="Vantage Robotics",
        group_name="Dealer Conference",
        guaranteed_count=150,
        markup_pct=0.15,
    )
    contract = create_sent_contract(
        program["id"],
        supplier["id"],
        contract_value_cents=900_000,
        cancellation_tier="STRICT",
    )
    counter_contract(contract["id"], supplier["id"], 960_000)
    resend_contract(contract["id"])
    counter_contract(contract["id"], supplier["id"], 940_000)
    contract = resend_contract(contract["id"])
    return {"supplier": supplier, "program": program, "contract": contract}


class TestNegotiationRoundCeiling:
    def test_every_send_adds_one_round_to_the_contract(self):
        """PRD §3.3: "Sending the contract advances it `DRAFT` → `SENT`, and re-sending
        after a counter-offer advances it `COUNTERED` → `SENT`; both writes stamp
        `sent_by_user_id` with the acting `X-User-ID`, add one to `round_count`, and
        increment the contract's `version`."

        Design: Difficulty/non_linear_state_machine/contract_negotiation_cycle_capped_at_three_rounds
        """
        ctx = _contract_at_the_round_ceiling()
        contract = ctx["contract"]

        assert contract["status"] == "SENT"
        assert contract["round_count"] == 3
        # The supplier's last accepted counter-offer overwrote the contract value.
        assert contract["contract_value_cents"] == 940_000

    def test_a_counter_at_the_ceiling_is_refused_and_writes_nothing(self, api):
        """PRD §3.3: "Both the counter and the send are bounded: the DMC permits at most
        three negotiation rounds, so a send or a counter attempted while `round_count` has
        already reached 3 is refused with `ERR_NEGOTIATION_ROUNDS_EXHAUSTED`."

        Design: Difficulty/non_linear_state_machine/contract_negotiation_cycle_capped_at_three_rounds
        """
        ctx = _contract_at_the_round_ceiling()
        contract_id = ctx["contract"]["id"]
        version_before = ctx["contract"]["version"]

        response = api.counter_supplier_contract(
            contract_id,
            {"countered_value_cents": 930_000},
            make_supplier_headers(ctx["supplier"]["id"]),
        )

        validate_error(
            response, ApiErrorId.ERR_NEGOTIATION_ROUNDS_EXHAUSTED.value, 422
        )
        contract = validate_success(api.get_supplier_contract(contract_id, SM))
        assert contract["round_count"] == 3
        assert contract["status"] == "SENT"
        assert contract["contract_value_cents"] == 940_000
        assert contract["version"] == version_before

    def test_the_loop_turns_at_most_three_times(self, api):
        """PRD §3.3: "The `SENT` → `COUNTERED` → `SENT` loop can therefore turn at most
        three times before somebody has to either countersign or walk away."

        Design: Difficulty/non_linear_state_machine/contract_negotiation_cycle_capped_at_three_rounds
        """
        ctx = _contract_at_the_round_ceiling()
        supplier_headers = make_supplier_headers(ctx["supplier"]["id"])

        first_refusal = api.counter_supplier_contract(
            ctx["contract"]["id"],
            {"countered_value_cents": 930_000},
            supplier_headers,
        )
        second_refusal = api.counter_supplier_contract(
            ctx["contract"]["id"],
            {"countered_value_cents": 920_000},
            supplier_headers,
        )

        for response in (first_refusal, second_refusal):
            validate_error(
                response, ApiErrorId.ERR_NEGOTIATION_ROUNDS_EXHAUSTED.value, 422
            )
        contract = validate_success(api.get_supplier_contract(ctx["contract"]["id"], SM))
        assert contract["round_count"] == 3
        assert contract["contract_value_cents"] == 940_000


class TestCreditRevertCycle:
    PROGRAM = {
        "client_name": "Kestrel Bank",
        "group_name": "Wealth Forum",
        "guaranteed_count": 40,
        "markup_pct": 0.20,
    }
    ELEMENT = {
        "title": "Sunset Terrace Reception",
        "starts_at": "2026-09-11T17:00:00Z",
        "ends_at": "2026-09-11T21:00:00Z",
        "planned_headcount": 40,
        "guaranteed_headcount": 40,
        "per_person_cost_cents": 5_000,
    }

    def _invoiced_then_credited(self, api):
        ctx = setup_invoiced_program(
            actual_headcount=40,
            deliver_clock="2026-09-11T21:30:00Z",
            program_overrides=self.PROGRAM,
            element_overrides=self.ELEMENT,
            venue_overrides={"name": "Lighthouse Terrace"},
            supplier_overrides={
                "legal_name": "Seagate Catering Group",
                "supplier_type": "VENUE_SERVICES",
            },
        )
        assert ctx["program"]["final_client_total_cents"] == 268_800
        ctx["program"] = validate_success(
            api.credit_program_invoice(
                ctx["program"]["id"], CTRL, {"credit_reason": CREDIT_REASON}
            )
        )
        return ctx

    def test_credit_lands_two_hops_away_in_reconciling(self, api):
        """PRD §3.9: "Then, within the same request, a further server-driven transition
        fires: once no reconciliation line of the programme remains `APPROVED`, the
        programme advances `CREDITED` → `RECONCILING`, setting `management_fee_cents` to 0,
        `final_client_total_cents` to 0 and `invoice_issued_at` back to null, and
        incrementing the programme's `version` again."

        Design: Difficulty/non_linear_state_machine/program_parallel_dimensions_and_credit_revert_cycle
        """
        ctx = self._invoiced_then_credited(api)
        program = ctx["program"]

        assert program["settlement_status"] == "RECONCILING"
        assert program["settlement_status"] != "CREDITED"
        assert program["management_fee_cents"] == 0
        assert program["final_client_total_cents"] == 0
        assert program["invoice_issued_at"] is None

    def test_credit_note_records_the_full_invoiced_amount_and_reverts_the_line(self, api):
        """PRD §3.9: "The credit adds the programme's current `final_client_total_cents`
        to its cumulative `credit_note_cents` — a credit note is issued for the full
        invoiced amount — and then reverts every reconciliation line of the programme in
        `APPROVED` back to `DRAFT`, each such line transition recomputing
        `final_subtotal_cents`, `disclosed_markup_cents`, `supplier_gross_payable_cents`
        and `supplier_open_payable_cents` and incrementing the line's own `version`."

        Design: Difficulty/non_linear_state_machine/program_parallel_dimensions_and_credit_revert_cycle
        """
        ctx = self._invoiced_then_credited(api)
        program = ctx["program"]
        line = validate_success(
            api.get_reconciliation_line(ctx["lines"][0]["id"], PD)
        )

        assert program["credit_note_cents"] == 268_800
        assert program["final_subtotal_cents"] == 0
        assert program["disclosed_markup_cents"] == 0
        assert program["supplier_gross_payable_cents"] == 0
        assert program["supplier_open_payable_cents"] == 0
        assert line["status"] == "DRAFT"

    def test_the_execution_dimension_is_untouched_by_the_credit(self, api):
        """PRD §3.1: "Neither dimension constrains the other's transition legality
        directly; where one dimension does gate the other, the gate is stated explicitly
        below."

        Design: Difficulty/non_linear_state_machine/program_parallel_dimensions_and_credit_revert_cycle
        """
        ctx = self._invoiced_then_credited(api)
        element = validate_success(api.get_program_element(ctx["element"]["id"], PD))

        assert ctx["program"]["execution_status"] == "COMPLETED"
        assert element["status"] == "DELIVERED"
