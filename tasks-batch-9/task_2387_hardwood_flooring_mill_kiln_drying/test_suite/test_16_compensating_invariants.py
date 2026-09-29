"""Two ledgers that must return to exactly their prior value when an action is
undone: a charge's green board feet, and a product line's warranty reserve."""

import pytest

from test_helpers import (
    allocate_receipt_payload,
    deallocate_receipt_payload,
    reverse_claim_payload,
    setup_charge_with_receipts,
    setup_line_only_approved_claim,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    ADMIN,
    OPERATOR,
    SUPERVISOR,
    refetch_claim,
    refetch_product_line,
    refetch_receipt,
)
from test_helpers.test_users import (
    CLAIM_ADJUDICATOR_USER_ID,
    make_warranty_adjudicator_headers,
)


class TestGreenVolumeConservation:
    """Allocation and deallocation are exact inverses on both derived figures."""

    def test_deallocation_restores_the_single_receipt_figures_exactly(self, api):
        """PRD 2.8: "Allocation and deallocation are exact inverses: allocating a
        receipt and then deallocating it restores both `charged_green_bf` and
        `weighted_initial_moisture_pct` to the values they held before, and returns the
        receipt to `ACCEPTED` with a null `kiln_charge_id`."

        PRD 3.4: "A charge holding 5800 board feet at 46.0 percent and 3900 board
        feet at 44.0 percent therefore carries 9700 charged board feet and a weighted
        moisture of 45.2 percent, since 438400 divided by 9700 is 45.195."

        Design: Difficulty/compensating_invariant/receipt_allocate_deallocate_conserves_charge_green_volume
        """
        ctx = setup_charge_with_receipts(api)
        assert ctx["charge"]["charged_green_bf"] == pytest.approx(9700, abs=0.01)
        assert ctx["charge"]["weighted_initial_moisture_pct"] == pytest.approx(
            45.2, abs=0.01
        )
        second = ctx["receipts"][1]

        charge = validate_success(
            api.deallocate_receipt(
                ctx["charge"]["id"], deallocate_receipt_payload(second["id"]), OPERATOR
            ),
            expected_status=200,
        )
        assert charge["charged_green_bf"] == pytest.approx(5800, abs=0.01)
        assert charge["weighted_initial_moisture_pct"] == pytest.approx(46.0, abs=0.01)

        freed = refetch_receipt(api, second["id"])
        assert freed["status"] == "ACCEPTED"
        assert freed["kiln_charge_id"] is None
        assert freed["accepted_board_feet"] == pytest.approx(3900, abs=0.01)

        _rows, meta = validate_paginated(
            api.list_green_receipts(ADMIN, params={"kiln_charge_id": ctx["charge"]["id"]})
        )
        assert meta["total_count"] == 1

    def test_repeated_cycles_leave_no_rounding_residue(self, api):
        """PRD 2.8: "Board feet on this ledger are whole integers and no rounding
        drift is permitted across repeated allocate-and-deallocate cycles."

        PRD 3.4: "Every allocation and deallocation recomputes two derived quantities
        on the charge from the set of receipts currently pointing at it in `ALLOCATED`
        status."

        Design: Difficulty/compensating_invariant/receipt_allocate_deallocate_conserves_charge_green_volume
        """
        ctx = setup_charge_with_receipts(api)
        charge_id = ctx["charge"]["id"]
        second_id = ctx["receipts"][1]["id"]

        for _cycle in range(2):
            validate_success(
                api.deallocate_receipt(
                    charge_id, deallocate_receipt_payload(second_id), OPERATOR
                ),
                expected_status=200,
            )
            charge = validate_success(
                api.allocate_receipt(
                    charge_id, allocate_receipt_payload(second_id), OPERATOR
                ),
                expected_status=200,
            )
            assert charge["charged_green_bf"] == pytest.approx(9700, abs=0.01)
            assert charge["weighted_initial_moisture_pct"] == pytest.approx(
                45.2, abs=0.01
            )

        _rows, meta = validate_paginated(
            api.list_green_receipts(ADMIN, params={"kiln_charge_id": charge_id})
        )
        assert meta["total_count"] == 2


class TestWarrantyReserveConservation:
    """A reversal credits back exactly what the approval debited."""

    def test_reversal_returns_the_line_to_its_pre_approval_state(self, api):
        """PRD 2.8: "A reversal credits back exactly the amount the approval
        debited, so approving a claim and then reversing it returns the line to its
        pre-approval balance, its pre-approval committed amount and its pre-approval
        posture with no residue."

        PRD 3.9: "It moves an `APPROVED` claim to the terminal `REVERSED` status,
        credits `warranty_balance_cents` and debits `warranty_committed_cents` by
        exactly the `adjudicated_liability_cents` the approval moved, and recomputes
        the line's posture; runs that were held remain `HELD` until released
        explicitly, even when the posture returns to `OPEN`."

        PRD 3.9: "A reversal also cancels the remediation dimension: a remediation
        status of `NOT_STARTED` or `IN_PROGRESS` moves to `CANCELLED`."

        Design: Difficulty/compensating_invariant/claim_approve_reverse_conserves_warranty_reserve
        """
        ctx = setup_line_only_approved_claim(api)
        claim_id = ctx["claim"]["id"]
        validate_success(api.start_remediation(claim_id, SUPERVISOR), expected_status=200)

        before = refetch_product_line(api, ctx["product_line"]["id"])
        assert before["warranty_balance_cents"] == 448526
        assert before["warranty_committed_cents"] == 151474
        assert (
            before["warranty_balance_cents"] + before["warranty_committed_cents"]
            == before["warranty_funded_total_cents"]
        )

        claim = validate_success(
            api.reverse_claim(
                claim_id,
                reverse_claim_payload(
                    reversal_reason=(
                        "Moisture log showed a plumbing leak, not a product defect"
                    )
                ),
                make_warranty_adjudicator_headers(CLAIM_ADJUDICATOR_USER_ID),
            ),
            expected_status=200,
        )
        assert claim["adjudication_status"] == "REVERSED"
        assert claim["remediation_status"] == "CANCELLED"
        assert claim["adjudicated_liability_cents"] == 151474

        after = refetch_product_line(api, ctx["product_line"]["id"])
        assert after["warranty_funded_total_cents"] == 600000
        assert after["warranty_committed_cents"] == 0
        assert after["warranty_balance_cents"] == 600000
        assert after["posture"] == "OPEN"

    def test_committed_cents_agree_with_the_approved_claim_set_and_reversal_is_once_only(
        self, api
    ):
        """PRD 2.8: "At all times a line's `warranty_balance_cents` plus its
        `warranty_committed_cents` equals its `warranty_funded_total_cents`, and
        `warranty_committed_cents` equals the total `adjudicated_liability_cents` of the
        claims on that line whose adjudication status is `APPROVED`."

        PRD 3.9: "Work that has already finished cannot be unwound, so a claim whose
        remediation status is `COMPLETED` may not be reversed and is refused with
        `ERR_CLAIM_STATE_INVALID`, as is any attempt to reverse a claim that is not
        `APPROVED`."

        Design: Difficulty/compensating_invariant/claim_approve_reverse_conserves_warranty_reserve
        """
        ctx = setup_line_only_approved_claim(api)
        claim_id = ctx["claim"]["id"]
        adjudicator = make_warranty_adjudicator_headers(CLAIM_ADJUDICATOR_USER_ID)
        validate_success(
            api.reverse_claim(claim_id, reverse_claim_payload(), adjudicator),
            expected_status=200,
        )

        _rows, meta = validate_paginated(
            api.list_warranty_claims(
                adjudicator,
                params={
                    "product_line_id": ctx["product_line"]["id"],
                    "adjudication_status": "APPROVED",
                },
            )
        )
        assert meta["total_count"] == 0

        response = api.reverse_claim(claim_id, reverse_claim_payload(), adjudicator)
        validate_error(response, "ERR_CLAIM_STATE_INVALID", expected_status=409)

        line = refetch_product_line(api, ctx["product_line"]["id"])
        assert line["warranty_committed_cents"] == 0
        assert line["warranty_balance_cents"] == 600000
        assert refetch_claim(api, claim_id)["adjudication_status"] == "REVERSED"
