"""Bounded round-trip cycles on contracts and substitutions (PRD §3.2, §3.8)."""

from test_helpers import (
    FLOUR_HRW_INDEXED,
    RICE_FLOUR,
    YEAST_INSTANT,
    ApiErrorId,
    add_contract_line,
    add_order_line,
    api_client,
    claim_substitution_request,
    counter_contract,
    create_customer,
    create_product,
    draft_contract,
    offer_contract,
    open_order,
    raise_substitution_request,
    read_contract,
    read_contract_line,
    read_order,
    read_order_line,
    read_substitution_request,
    request_revision_payload,
    resubmit_substitution_payload,
    set_clock,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import AM, QM, TS, buyer_headers


def _draft_contract_with_one_line():
    set_clock("2026-08-05T00:00:00Z")
    customer = create_customer()
    product = create_product(FLOUR_HRW_INDEXED)
    contract = draft_contract(
        customer,
        term_start_on="2026-09-01T00:00:00Z",
        term_end_on="2026-12-31T00:00:00Z",
        pricing_mode="ORDER_DATE_INDEX",
    )
    contract_line = add_contract_line(
        contract["id"], product["id"], volume_committed_lb=40000, basis_cents_per_lb=6
    )
    return customer, contract, contract_line


class TestContractNegotiationCycle:
    """`OFFERED → COUNTERED → OFFERED` traversed to its cap."""

    def test_each_re_offer_of_a_countered_contract_increments_the_round(self):
        """PRD §3.2: "Re-offering a `COUNTERED` contract is permitted only while
        `negotiation_round` is strictly less than 3; the re-offer increments
        `negotiation_round` by 1, re-records `authored_by_user_id` as the operator
        who re-offered, and increments `version` by 1."

        The first offer leaves the counter at 0 because it comes out of `DRAFT`;
        the three re-offers take it to 1, 2 and 3.

        Design: Difficulty/non_linear_state_machine/cyclic_contract_negotiation_offered_countered_offered_capped_at_three_rounds
        """
        customer, contract, contract_line = _draft_contract_with_one_line()

        first = offer_contract(contract["id"])
        assert first["status"] == "OFFERED", f"Expected OFFERED, got {first['status']}"
        assert first["negotiation_round"] == 0, (
            f"Expected round 0 on the first offer, got {first['negotiation_round']}"
        )

        observed_rounds = []
        for basis in (5, 4, 3):
            countered = counter_contract(customer, contract["id"], basis)
            assert countered["status"] == "COUNTERED", (
                f"Expected COUNTERED, got {countered['status']}"
            )
            reoffered = offer_contract(contract["id"])
            observed_rounds.append(reoffered["negotiation_round"])

        assert observed_rounds == [1, 2, 3], (
            f"Expected rounds 1, 2, 3 across the three re-offers, got {observed_rounds}"
        )
        assert read_contract_line(contract_line["id"])["basis_cents_per_lb"] == 3, (
            "The last counter must have replaced the basis on every line"
        )

    def test_fourth_re_offer_is_rejected_once_the_round_cap_is_reached(self):
        """PRD §3.2: "A fourth attempt — that is, an attempt made when
        `negotiation_round` has already reached 3 — is rejected with
        `ERR_ROUND_LIMIT_REACHED` (HTTP 409)."

        Design: Difficulty/non_linear_state_machine/cyclic_contract_negotiation_offered_countered_offered_capped_at_three_rounds
        """
        customer, contract, contract_line = _draft_contract_with_one_line()
        offer_contract(contract["id"])
        for basis in (5, 4, 3):
            counter_contract(customer, contract["id"], basis)
            offer_contract(contract["id"])
        counter_contract(customer, contract["id"], 2)

        response = api_client.offer_forward_contract(contract["id"], {}, AM)

        validate_error(response, ApiErrorId.ERR_ROUND_LIMIT_REACHED)
        contract_now = read_contract(contract["id"])
        assert contract_now["status"] == "COUNTERED", (
            f"Expected the contract to stay COUNTERED, got {contract_now['status']}"
        )
        assert contract_now["negotiation_round"] == 3, (
            f"Expected round to stay at 3, got {contract_now['negotiation_round']}"
        )
        assert contract_now["approved_by_user_id"] is None, (
            "approved_by_user_id is null on every contract that has not been activated"
        )
        assert read_contract_line(contract_line["id"])["basis_cents_per_lb"] == 2


class TestSubstitutionRevisionCycle:
    """`REQUESTED → UNDER_REVIEW → REVISION_REQUESTED → REQUESTED` to its cap."""

    def _requested_substitution(self):
        set_clock("2026-08-05T00:00:00Z")
        customer = create_customer()
        yeast = create_product(YEAST_INSTANT)
        rice = create_product(RICE_FLOUR)
        order = open_order(customer, requested_delivery_on="2026-09-15T00:00:00Z")
        line = add_order_line(customer, order["id"], yeast["id"], 1500)
        order_version = read_order(order["id"])["version"]
        request = raise_substitution_request(
            line["id"], rice["id"], order_version, specialist_user_id="ts-1"
        )
        return {
            "customer": customer,
            "yeast": yeast,
            "rice": rice,
            "order": order,
            "order_line": line,
            "request": request,
        }

    def test_each_resubmission_increments_the_revision_round(self):
        """PRD §3.8: "The originating specialist — and only that specialist,
        identified by an `X-User-ID` equal to `requested_by_user_id` — resubmits,
        moving the request `REVISION_REQUESTED → REQUESTED`, incrementing
        `revision_round` by 1, and replacing `proposed_product_id` and `rationale`
        with the revised values."

        Design: Difficulty/non_linear_state_machine/cyclic_substitution_revision_loop_capped_at_two_rounds
        """
        scenario = self._requested_substitution()
        request_id = scenario["request"]["id"]
        assert scenario["request"]["revision_round"] == 0

        claim_substitution_request(request_id, manager_user_id="qm-1")
        bounced = validate_success(
            api_client.request_substitution_revision(
                request_id, request_revision_payload(), QM
            )
        )
        assert bounced["status"] == "REVISION_REQUESTED", (
            f"Expected REVISION_REQUESTED, got {bounced['status']}"
        )
        assert bounced["revision_round"] == 0, (
            f"Requesting a revision does not itself advance the round, got {bounced['revision_round']}"
        )
        assert bounced["decided_by_user_id"] is None, (
            "Requesting a revision clears decided_by_user_id so the next claim starts clean"
        )

        first = validate_success(
            api_client.resubmit_substitution_request(
                request_id, resubmit_substitution_payload(scenario["rice"]["id"]), TS
            )
        )
        assert first["status"] == "REQUESTED"
        assert first["revision_round"] == 1, (
            f"Expected revision_round 1 after the first resubmission, got {first['revision_round']}"
        )

        claim_substitution_request(request_id, manager_user_id="qm-1")
        validate_success(
            api_client.request_substitution_revision(
                request_id, request_revision_payload(), QM
            )
        )
        second = validate_success(
            api_client.resubmit_substitution_request(
                request_id, resubmit_substitution_payload(scenario["rice"]["id"]), TS
            )
        )
        assert second["revision_round"] == 2, (
            f"Expected revision_round 2 after the second resubmission, got {second['revision_round']}"
        )

    def test_third_revision_request_is_rejected_at_the_round_cap(self):
        """PRD §3.8: "It is permitted only while `revision_round` is strictly less
        than 2; a third revision attempt is rejected with
        `ERR_ROUND_LIMIT_REACHED`."

        Design: Difficulty/non_linear_state_machine/cyclic_substitution_revision_loop_capped_at_two_rounds
        """
        scenario = self._requested_substitution()
        request_id = scenario["request"]["id"]
        for _ in range(2):
            claim_substitution_request(request_id, manager_user_id="qm-1")
            validate_success(
                api_client.request_substitution_revision(
                    request_id, request_revision_payload(), QM
                )
            )
            validate_success(
                api_client.resubmit_substitution_request(
                    request_id, resubmit_substitution_payload(scenario["rice"]["id"]), TS
                )
            )
        claim_substitution_request(request_id, manager_user_id="qm-1")

        response = api_client.request_substitution_revision(
            request_id, request_revision_payload(), QM
        )

        validate_error(response, ApiErrorId.ERR_ROUND_LIMIT_REACHED)
        request = read_substitution_request(request_id)
        assert request["status"] == "UNDER_REVIEW", (
            f"Expected the request to stay UNDER_REVIEW, got {request['status']}"
        )
        assert request["revision_round"] == 2, (
            f"Expected revision_round to stay at 2, got {request['revision_round']}"
        )
        assert request["requested_by_user_id"] == "ts-1"
        assert request["decided_by_user_id"] == "qm-1"
        assert read_order_line(scenario["order_line"]["id"])["product_id"] == scenario["yeast"]["id"]
