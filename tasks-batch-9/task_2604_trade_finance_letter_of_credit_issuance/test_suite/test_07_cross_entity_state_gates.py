"""Two operations whose outcome is decided entirely by another row's state.

The credit being issued is `APPROVED` in both attempts and the only difference is whether
the facility it names is closed. The claim being settled is `LODGED` in both attempts and
the only difference is where the governing screening check sits. In each pair the addressed
row never moves, so a request that reads only its own state gets both attempts wrong.
"""

from prd_bench_local_runner.testing import validate_error, validate_success
from test_helpers import (
    api_client,
    approve_credit,
    approved_credit,
    assert_facility_ledger,
    change_facility_status,
    conclude_examination,
    create_facility,
    credit_officer_headers,
    draft_credit,
    factories,
    issued_credit,
    list_claim_rows,
    lodge_claim,
    newest_presentation_screening,
    rescreen_presentation,
    review_screening,
    set_clock,
    setup_parties,
    submit_credit_for_approval,
    submitted_presentation,
    trade_finance_officer_headers,
    COMPLIANCE_OFFICER_1,
    COMPLIANCE_OFFICER_2,
)

STANDARD_TERMS = {
    "amount_cents": 10000000,
    "available_by": "SIGHT_PAYMENT",
    "tenor_days": 0,
    "tolerance_pct": 0,
    "latest_shipment_date": "2026-10-31",
    "expiry_date": "2026-11-30",
    "presentation_period_days": 21,
}


def _read_facility(facility_id):
    return validate_success(api_client.get_facility(facility_id, credit_officer_headers()))


def _attempt_issue(credit_id):
    return api_client.issue_credit(
        credit_id, factories.issue_payload(), trade_finance_officer_headers()
    )


class TestCreditIssuanceRequiresFacilityNotClosed:
    """Two approved credits, identical in every field but the facility they name."""

    def _two_credits_one_closed_facility(self):
        parties = setup_parties(facility={"limit_cents": 50000000})
        second_facility = create_facility(parties.applicant_id, limit_cents=50000000)
        on_closed = approved_credit(parties, None, **STANDARD_TERMS)
        on_open = draft_credit(
            parties, None, facility_id=second_facility["id"], **STANDARD_TERMS
        )
        submit_credit_for_approval(on_open.credit_id)
        approve_credit(on_open.credit_id)
        on_open.refresh()
        change_facility_status(parties.facility_id, "CLOSE")
        return parties, on_closed, on_open, second_facility["id"]

    def test_closing_a_facility_freezes_its_posture(self, clock):
        """A closed facility carries the `FROZEN` posture that the issuance guard reads.

        PRD 3.1: "Closing takes an `ACTIVE` or `SUSPENDED` facility to the terminal `CLOSED`
        state and sets `utilisation_posture` to `FROZEN`, and it requires that no allocation
        row on the facility is still `OPEN` — equivalently that `allocated_cents` is zero —
        failing which the request is rejected with `ERR_FACILITY_HAS_OPEN_ALLOCATION`
        (409)."

        Design: Difficulty/cross_entity_state_dependency/credit_issuance_requires_facility_not_closed
        """
        parties, _on_closed, _on_open, _second = self._two_credits_one_closed_facility()

        assert_facility_ledger(
            parties.refresh_facility(),
            allocated_cents=0,
            utilisation_posture="FROZEN",
            status="CLOSED",
        )

    def test_an_approved_credit_on_a_closed_facility_cannot_be_issued(self, clock):
        """The credit is faultless; the facility it points at is not.

        PRD 3.3: "The facility must be `ACTIVE` and its `utilisation_posture` must not be
        `FROZEN`, else `ERR_FACILITY_NOT_ACTIVE` (409)."

        Design: Difficulty/cross_entity_state_dependency/credit_issuance_requires_facility_not_closed
        """
        parties, on_closed, _on_open, _second = self._two_credits_one_closed_facility()

        validate_error(_attempt_issue(on_closed.credit_id), "ERR_FACILITY_NOT_ACTIVE", 409)

        assert on_closed.refresh()["status"] == "APPROVED"
        assert on_closed.credit["committed_allocation_cents"] == 0
        assert parties.refresh_facility()["allocated_cents"] == 0

    def test_the_same_credit_shape_issues_against_an_active_facility(self, clock):
        """Swap the facility row and the identical request succeeds.

        PRD 3.3: "Issuance is the moment the bank binds itself, and it is the single densest
        operation in this service."

        Design: Difficulty/cross_entity_state_dependency/credit_issuance_requires_facility_not_closed
        """
        _parties, _on_closed, on_open, open_facility_id = (
            self._two_credits_one_closed_facility()
        )

        issued = validate_success(_attempt_issue(on_open.credit_id), 200)

        assert issued["status"] == "ISSUED"
        assert issued["chargeable_utilisation_cents"] == 10025000
        assert_facility_ledger(
            _read_facility(open_facility_id),
            allocated_cents=10025000,
            available_cents=39975000,
            utilisation_posture="OPEN",
            status="ACTIVE",
        )


class TestSettlementRequiresScreeningClearOrReleased:
    """One lodged claim, settled twice, against a screening check that moves underneath it."""

    def _lodged_claim_behind_a_pending_screening(self):
        ctx = issued_credit(
            setup_parties(facility={"limit_cents": 50000000}),
            amount_cents=5000000,
            available_by="SIGHT_PAYMENT",
            tenor_days=0,
            tolerance_pct=0,
            latest_shipment_date="2026-10-31",
            expiry_date="2026-11-30",
            presentation_period_days=21,
        )
        set_clock("2026-09-14T09:00:00Z")
        pctx = submitted_presentation(
            ctx,
            (2000000,),
            invoice_overrides={
                "goods_description": "Rack mount servers",
                "hs_code": "8471600000",
            },
            transport_overrides={"goods_description": "Rack mount servers"},
        )
        first_check = newest_presentation_screening(pctx.presentation_id)
        review_screening(first_check["id"], "RELEASE", COMPLIANCE_OFFICER_1)
        conclude_examination(pctx)
        claim = lodge_claim(pctx, "PAYMENT", 2000000)
        second_check = rescreen_presentation(
            pctx, "PRESENTED_DOCUMENTS", COMPLIANCE_OFFICER_1
        )
        return pctx, claim, first_check, second_check

    def _attempt_settle(self, claim_id):
        return api_client.settle_claim(
            claim_id, factories.settle_payload(), trade_finance_officer_headers()
        )

    def test_a_screening_awaiting_review_blocks_the_settlement(self, clock):
        """The newest check sits at `HIT_PENDING_REVIEW`, so the claim cannot be settled.

        PRD 3.8: "A newest `PRESENTED_DOCUMENTS` check at `HIT_PENDING_REVIEW` blocks
        settlement with `ERR_SCREENING_NOT_CLEARED` (409)."

        Design: Difficulty/cross_entity_state_dependency/settlement_requires_screening_clear_or_released
        """
        pctx, claim, _first, second_check = (
            self._lodged_claim_behind_a_pending_screening()
        )
        assert second_check["risk_score"] == 60
        newest = newest_presentation_screening(pctx.presentation_id)
        assert newest["id"] == second_check["id"]
        assert newest["result"] == "HIT_PENDING_REVIEW"

        validate_error(self._attempt_settle(claim["id"]), "ERR_SCREENING_NOT_CLEARED", 409)

    def test_escalating_the_same_check_swaps_the_error_but_not_the_outcome(self, clock):
        """Moving the other row from awaiting review to escalated changes only the error id.

        PRD 3.8: "One at `ESCALATED` blocks settlement with `ERR_DUAL_USE_ESCALATED` (409)."

        Design: Difficulty/cross_entity_state_dependency/settlement_requires_screening_clear_or_released
        """
        pctx, claim, _first, second_check = self._lodged_claim_behind_a_pending_screening()
        validate_error(self._attempt_settle(claim["id"]), "ERR_SCREENING_NOT_CLEARED", 409)

        escalated = review_screening(second_check["id"], "ESCALATE", COMPLIANCE_OFFICER_2)

        assert escalated["result"] == "ESCALATED"
        assert escalated["reviewed_by_user_id"] == COMPLIANCE_OFFICER_2
        validate_error(self._attempt_settle(claim["id"]), "ERR_DUAL_USE_ESCALATED", 409)
        assert newest_presentation_screening(pctx.presentation_id)["result"] == "ESCALATED"

    def test_the_claim_and_the_credit_stay_exactly_where_they_were(self, clock):
        """Two refused settlements leave the claim lodged and the drawing reserved.

        PRD 3.9: "A claim's own `status` is `LODGED`, `SETTLED` or `REJECTED`, starting at
        `LODGED`, and every fee and proceeds field — `variant_applied`,
        `commission_bps_applied`, `commission_cents`, `discount_cents`,
        `doc_examination_fee_cents`, `days_to_maturity` and `net_proceeds_cents` — stays at
        zero or unset until the claim is settled."

        Design: Difficulty/cross_entity_state_dependency/settlement_requires_screening_clear_or_released
        """
        pctx, claim, _first, second_check = self._lodged_claim_behind_a_pending_screening()
        self._attempt_settle(claim["id"])
        review_screening(second_check["id"], "ESCALATE", COMPLIANCE_OFFICER_2)
        self._attempt_settle(claim["id"])

        rows = list_claim_rows(pctx.presentation_id)
        assert len(rows) == 1
        assert rows[0]["status"] == "LODGED"
        assert rows[0]["net_proceeds_cents"] == 0
        assert rows[0]["settled_at"] is None
        presentation = pctx.refresh()
        assert presentation["settlement_status"] == "CLAIM_LODGED"
        assert presentation["examination_status"] == "COMPLYING"
        credit = pctx.refresh_credit()
        assert credit["reserved_cents"] == 2000000
        assert credit["drawn_settled_cents"] == 0
