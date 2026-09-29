"""Change-order negotiation rounds, dimension independence and gate ordering."""

from test_helpers import (
    CUSTOMER_REP,
    PROJECT_DIRECTOR,
    SHOP_SUPERVISOR,
    ApiErrorId,
    assert_change_order,
    decide_change_order,
    make_change_order,
    make_planned_lot,
    make_project,
    make_submitted_change_order,
    read_change_order,
    read_lot,
    read_project,
    review_decision_payload,
    validate_error,
    validate_success,
)


class TestChangeOrderRevisionRounds:
    """Negotiation is bounded at three rounds."""

    def _submitted_order(self, api):
        project = make_project(api)
        change_order = make_submitted_change_order(
            api,
            project["id"],
            title="Relocate merge point",
            scope_delta_cph=0,
            price_delta_cents=4_000_000,
        )
        return project, change_order

    def test_each_revision_request_increments_the_negotiation_round(self, api):
        """Round 1 becomes 2, and a resubmission is legal from REVISION_REQUESTED.

        PRD §3.8: "A **`REQUEST_REVISION`** decision advances the order `SUBMITTED →
        REVISION_REQUESTED` and increments its `round_no` by 1."

        Design: Difficulty/non_linear_state_machine/change_order_revision_cycle_bounded_at_three_rounds
        """
        project, change_order = self._submitted_order(api)
        assert_change_order(change_order)
        assert change_order["round_no"] == 1
        assert change_order["status"] == "SUBMITTED"

        first = decide_change_order(
            api, project["id"], change_order["id"], "REQUEST_REVISION", headers=CUSTOMER_REP
        )
        assert first["status"] == "REVISION_REQUESTED"
        assert first["round_no"] == 2

        resubmitted = validate_success(
            api.submit_change_order(change_order["id"], PROJECT_DIRECTOR)
        )
        assert resubmitted["status"] == "SUBMITTED"
        assert resubmitted["round_no"] == 2

        second = decide_change_order(
            api, project["id"], change_order["id"], "REQUEST_REVISION", headers=CUSTOMER_REP
        )
        assert second["status"] == "REVISION_REQUESTED"
        assert second["round_no"] == 3

    def test_a_third_revision_request_is_refused_at_the_round_limit(self, api):
        """Incrementing round_no above 3 is rejected rather than allowed.

        PRD §3.8: "Negotiation is bounded at three rounds: if incrementing `round_no`
        would carry it above 3, the decision is rejected with
        `ERR_CHANGE_ORDER_ROUND_LIMIT`."

        Design: Difficulty/non_linear_state_machine/change_order_revision_cycle_bounded_at_three_rounds
        """
        project, change_order = self._submitted_order(api)
        for _ in range(2):
            decide_change_order(
                api, project["id"], change_order["id"], "REQUEST_REVISION", headers=CUSTOMER_REP
            )
            validate_success(api.submit_change_order(change_order["id"], PROJECT_DIRECTOR))

        current = read_project(api, project["id"])
        response = api.review_change_order(
            change_order["id"],
            review_decision_payload("REQUEST_REVISION", current["version"]),
            CUSTOMER_REP,
        )
        validate_error(response, ApiErrorId.ERR_CHANGE_ORDER_ROUND_LIMIT.value)

        stored = read_change_order(api, change_order["id"])
        assert stored["round_no"] == 3
        assert stored["status"] == "SUBMITTED"

    def test_the_negotiation_recomputes_no_money_and_stays_change_pending(self, api):
        """Rounds of revision leave the contract ledger exactly where it was.

        PRD §3.8: "No money is recomputed by a revision request and no cascade fires."

        Design: Difficulty/non_linear_state_machine/change_order_revision_cycle_bounded_at_three_rounds
        """
        project, change_order = self._submitted_order(api)
        for _ in range(2):
            decide_change_order(
                api, project["id"], change_order["id"], "REQUEST_REVISION", headers=CUSTOMER_REP
            )
            validate_success(api.submit_change_order(change_order["id"], PROJECT_DIRECTOR))

        after = read_project(api, project["id"])
        assert after["commercial_status"] == "CHANGE_PENDING"
        assert after["contract_value_cents"] == 243_600_000
        assert after["escalation_fee_cents"] == 3_600_000


class TestDeliveryAndCommercialIndependence:
    """One axis moves without disturbing the other."""

    def _frozen_lot_and_order(self, api):
        state = make_planned_lot(api, lot_code="LOT-300")
        change_order = make_change_order(
            api,
            state["project"]["id"],
            title="Add spiral chute",
            scope_delta_cph=0,
            price_delta_cents=2_000_000,
        )
        return state, change_order

    def test_submitting_an_order_moves_only_the_commercial_dimension(self, api):
        """The project stays DESIGN_FROZEN while its commercial axis goes pending.

        PRD §3.8: "Submission advances the order to `SUBMITTED`, moves the project's
        `commercial_status` from `CLEAN` to `CHANGE_PENDING` if it was `CLEAN`, and
        increments both the order's `version` and the project's `version` by 1."

        Design: Difficulty/non_linear_state_machine/project_delivery_and_commercial_dimensions_advance_independently
        """
        state, change_order = self._frozen_lot_and_order(api)
        validate_success(api.submit_change_order(change_order["id"], PROJECT_DIRECTOR))

        after = read_project(api, state["project"]["id"])
        assert after["commercial_status"] == "CHANGE_PENDING"
        assert after["delivery_status"] == "DESIGN_FROZEN"

    def test_starting_fabrication_moves_only_the_delivery_dimension(self, api):
        """The commercial axis stays CHANGE_PENDING across a delivery transition.

        PRD §2.5: "No commercial transition reads or writes `delivery_status`, and no
        delivery transition reads or writes `commercial_status`, with the single
        documented exception that certificate issuance requires the commercial
        dimension to be `CLEAN`."

        Design: Difficulty/non_linear_state_machine/project_delivery_and_commercial_dimensions_advance_independently
        """
        state, change_order = self._frozen_lot_and_order(api)
        validate_success(api.submit_change_order(change_order["id"], PROJECT_DIRECTOR))
        validate_success(api.start_fabrication(state["lot"]["id"], SHOP_SUPERVISOR))

        after = read_project(api, state["project"]["id"])
        assert after["delivery_status"] == "IN_FABRICATION"
        assert after["commercial_status"] == "CHANGE_PENDING"
        assert read_lot(api, state["lot"]["id"])["status"] == "FABRICATING"
        assert read_change_order(api, change_order["id"])["status"] == "SUBMITTED"


class TestChangeOrderStateBeforeMoneyGate:
    """A draft order that would also breach the ceiling reports its state failure."""

    def _draft_order_over_the_ceiling(self, api):
        project = make_project(api)
        change_order = make_change_order(
            api,
            project["id"],
            title="Full mezzanine extension",
            scope_delta_cph=0,
            price_delta_cents=60_000_000,
            schedule_delta_days=45,
        )
        return project, change_order

    def test_state_admissibility_is_reported_ahead_of_the_ceiling_breach(self, api):
        """Band 8 beats band 15, so the DRAFT status decides the response.

        PRD §2.12: "**Money gates, evaluated last** — the recomputed contract value
        must not exceed the authorized ceiling (`ERR_CONTRACT_CEILING_EXCEEDED`, 422),
        and a provisioning run must find at least one fundable line
        (`ERR_NO_FUNDABLE_SPARE_LINES`, 422)."

        Design: Difficulty/priority_pair_validation_conflict/change_order_state_check_precedes_contract_ceiling_check
        """
        project, change_order = self._draft_order_over_the_ceiling(api)
        current = read_project(api, project["id"])

        response = api.review_change_order(
            change_order["id"],
            review_decision_payload("APPROVE", current["version"]),
            CUSTOMER_REP,
        )
        validate_error(response, ApiErrorId.ERR_CHANGE_ORDER_INVALID_STATE.value)

    def test_the_refused_decision_leaves_the_order_and_the_ledger_untouched(self, api):
        """A decision is only legal against a SUBMITTED order.

        PRD §3.8: "The order must be in `SUBMITTED`; a decision recorded against an
        order in any other status is rejected with `ERR_CHANGE_ORDER_INVALID_STATE`."

        Design: Difficulty/priority_pair_validation_conflict/change_order_state_check_precedes_contract_ceiling_check
        """
        project, change_order = self._draft_order_over_the_ceiling(api)
        current = read_project(api, project["id"])
        api.review_change_order(
            change_order["id"],
            review_decision_payload("APPROVE", current["version"]),
            CUSTOMER_REP,
        )

        stored = read_change_order(api, change_order["id"])
        assert stored["status"] == "DRAFT"
        after = read_project(api, project["id"])
        assert after["contract_value_cents"] == 243_600_000
        assert after["escalation_fee_cents"] == 3_600_000
        assert after["commercial_status"] == "CLEAN"
