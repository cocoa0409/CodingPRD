"""
Payment approval: the second status dimension and the cascade it fires.

Approving payment settles the invoice, moves money from committed to spent on the
fiscal account, advances the placement's year-to-date counter and — only when that
counter crosses the high-cost trigger — creates a funding claim and rolls it up
onto the student.
"""

import pytest

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_ENCUMBRANCE_EXCEEDED,
    ERR_INVALID_STATE_TRANSITION,
    ERR_TRANSPORT_NOT_ASSIGNED,
)
from test_helpers.assertions import assert_ledger, assert_ledger_identity
from test_helpers.fixtures import (
    FULL_MONTH_PERIOD,
    approve_payment,
    bill_and_settle_cycle,
    build_active_day_placement,
    build_simple_billing_cycle,
    create_invoice,
    list_rows,
    placement_version,
    read_account,
    read_invoice,
    read_placement,
    read_student,
    release_transport,
    verify_invoice,
)
from test_helpers.test_users import COORDINATOR_HEADERS, FISCAL_OFFICER_HEADERS

# ─── The plain day cycle (20 enrolled days at 32000, no addenda) ──────────────
PLAIN_GROSS_CENTS = 640000
PLAIN_FEE_CENTS = 14400
PLAIN_NET_CENTS = 654400
ENCUMBRANCE_AFTER_ONE_PAYMENT_CENTS = 5105600

# ─── The residential cycle (28 days at 32000 plus 28 nights at 51500) ─────────
RESIDENTIAL_OVERRIDES = {
    "residential": True,
    "placement_type": "RESIDENTIAL",
    "contracted_instructional_days": 180,
    "contracted_residential_nights": 300,
}
RESIDENTIAL_CONTRACT_ENCUMBRANCE_CENTS = 21210000
RESIDENTIAL_GROSS_CENTS = 2338000
RESIDENTIAL_CREDIT_CENTS = 70140
RESIDENTIAL_FEE_CENTS = 51027
RESIDENTIAL_NET_CENTS = 2318887
TWO_CYCLES_PAID_CENTS = 4637774

# The high-cost trigger is 4 000 000 cents; the excess of 637 774 falls in the
# lowest tier, so the reimbursable figure is 637774 x 0.60 = 382664.4 -> 382664.
HIGH_COST_EXCESS_CENTS = 637774
HIGH_COST_TIER_RATE = 0.60
HIGH_COST_REIMBURSABLE_CENTS = 382664

CYCLE_ONE = {"period_start": "2026-09-01", "period_end": "2026-09-28"}
CYCLE_TWO = {"period_start": "2026-09-29", "period_end": "2026-10-26"}
CYCLE_ONE_FILED_AT = "2026-09-29T09:00:00Z"
CYCLE_TWO_FILED_AT = "2026-10-27T09:00:00Z"


def _residential_world(api):
    """An ACTIVE RESIDENTIAL placement with 180 days and 300 nights contracted."""
    world = build_active_day_placement(api, placement_overrides=RESIDENTIAL_OVERRIDES)
    assert (
        world["placement"]["contract_encumbrance_cents"]
        == RESIDENTIAL_CONTRACT_ENCUMBRANCE_CENTS
    )
    return world


def _settle_residential_cycle(api, world, *, period, filing_instant, settle=True):
    return bill_and_settle_cycle(
        api,
        world,
        period_start=period["period_start"],
        period_end=period["period_end"],
        filing_instant=filing_instant,
        submitted_amount_cents=RESIDENTIAL_NET_CENTS,
        basis="ENROLLMENT",
        days_enrolled=28,
        days_attended=28,
        days_absent_unexcused=0,
        residential_nights=28,
        settle=settle,
    )


class TestInvoiceStatusDimensions:
    """Verification and payment advance on independent axes."""

    def test_payment_approval_leaves_the_verification_dimension_terminal(self, api):
        """
        Paying the invoice sets the settled figure and the approver without
        disturbing the verified figure or the verifier.

        PRD: "- **Link 0 (the invoice itself).** `payment_status` is set to `PAID`, `settled_amount_cents` is set to `verified_amount_cents`, `approved_by_user_id` is set to the acting user's identifier, and the invoice's `version` is incremented. `verification_status` stays at `VERIFIED`."

        Design: Difficulty/non_linear_state_machine/invoice_parallel_status_dimensions_move_independently
        """
        world = build_simple_billing_cycle(api)
        invoice = create_invoice(
            api,
            world,
            world["placement"]["id"],
            world["record"]["id"],
            PLAIN_NET_CENTS,
            transport_days_billed=0,
        )
        verified = verify_invoice(api, invoice["id"], "ENROLLMENT")
        assert verified["gross_billable_cents"] == PLAIN_GROSS_CENTS
        assert verified["volume_credit_cents"] == 0
        assert verified["admin_fee_cents"] == PLAIN_FEE_CENTS
        assert verified["verified_amount_cents"] == PLAIN_NET_CENTS
        assert verified["payment_status"] == "UNPAID"

        paid = validate_success(
            api.approve_invoice_payment(invoice["id"], FISCAL_OFFICER_HEADERS)
        )
        assert paid["payment_status"] == "PAID"
        assert paid["settled_amount_cents"] == PLAIN_NET_CENTS
        assert paid["verification_status"] == "VERIFIED"
        assert paid["verified_amount_cents"] == PLAIN_NET_CENTS
        assert paid["verified_by_user_id"] == "u-coord-1"
        assert paid["approved_by_user_id"] == "u-fiscal-1"

    def test_resubmission_is_refused_once_the_verification_dimension_is_terminal(self, api):
        """
        The school cannot reopen a priced invoice by resubmitting it after payment,
        and the refusal spends no resubmission round.

        PRD: "This rung covers terminal-state lockdown and any second invocation of a transition already taken."

        Design: Difficulty/non_linear_state_machine/invoice_parallel_status_dimensions_move_independently
        """
        world = build_simple_billing_cycle(api)
        invoice = create_invoice(
            api,
            world,
            world["placement"]["id"],
            world["record"]["id"],
            PLAIN_NET_CENTS,
            transport_days_billed=0,
        )
        verify_invoice(api, invoice["id"], "ENROLLMENT")
        paid = approve_payment(api, invoice["id"])
        assert paid["payment_status"] == "PAID"

        response = api.resubmit_tuition_invoice(
            invoice["id"],
            f.resubmit_invoice_payload(700000, transport_days_billed=0),
            world["school_headers"],
        )
        validate_error(response, ERR_INVALID_STATE_TRANSITION, 409)

        after = read_invoice(api, invoice["id"])
        assert after["resubmission_round"] == 0
        assert after["verification_status"] == "VERIFIED"
        assert after["payment_status"] == "PAID"
        assert after["settled_amount_cents"] == PLAIN_NET_CENTS


class TestHighCostCascade:
    """The claim is caused by the counter crossing the trigger, not by the payment."""

    def test_a_payment_below_the_trigger_creates_no_funding_claim(self, api):
        """
        One settled residential cycle takes the year-to-date figure to 2318887,
        which is short of the four-million-cent trigger, so nothing cascades.

        PRD: "This link is caused by Link 2's counter movement, not by the approval call: an approval that does not push the counter over the trigger, or one where a qualifying claim already exists, creates nothing."

        Design: Difficulty/transitive_cascade/payment_rollup_crosses_high_cost_trigger_and_creates_claim_then_student_rollup
        """
        world = _residential_world(api)
        first = _settle_residential_cycle(
            api, world, period=CYCLE_ONE, filing_instant=CYCLE_ONE_FILED_AT
        )
        invoice = first["invoice"]
        assert invoice["gross_billable_cents"] == RESIDENTIAL_GROSS_CENTS
        assert invoice["volume_credit_cents"] == RESIDENTIAL_CREDIT_CENTS
        assert invoice["admin_fee_cents"] == RESIDENTIAL_FEE_CENTS
        assert invoice["verified_amount_cents"] == RESIDENTIAL_NET_CENTS
        assert invoice["settled_amount_cents"] == RESIDENTIAL_NET_CENTS

        placement = read_placement(api, world["placement"]["id"])
        assert placement["paid_total_ytd_cents"] == RESIDENTIAL_NET_CENTS

        _, meta = list_rows(
            api.list_funding_claims(
                FISCAL_OFFICER_HEADERS, {"placement_id": world["placement"]["id"]}
            )
        )
        assert meta["total_count"] == 0

        student = read_student(api, world["student"]["id"])
        assert student["high_cost_flag"] is False
        assert student["projected_state_recovery_cents"] == 0

    def test_the_second_payment_crosses_the_trigger_and_rolls_up_to_the_student(self, api):
        """
        The payment that lifts the counter to 4637774 creates one automatic
        high-cost claim and adds its reimbursable figure to the student.

        PRD: "- **Link 4 (funding claim to student, caused by Link 3).** Only if Link 3 actually created a claim, the student's `high_cost_flag` is set to true, `projected_state_recovery_cents` is increased by the new claim's `reimbursable_amount_cents`, and the student's `version` is incremented."

        Design: Difficulty/transitive_cascade/payment_rollup_crosses_high_cost_trigger_and_creates_claim_then_student_rollup
        """
        world = _residential_world(api)
        _settle_residential_cycle(
            api, world, period=CYCLE_ONE, filing_instant=CYCLE_ONE_FILED_AT
        )
        second = _settle_residential_cycle(
            api,
            world,
            period=CYCLE_TWO,
            filing_instant=CYCLE_TWO_FILED_AT,
            settle=False,
        )
        assert second["invoice"]["payment_status"] == "UNPAID"

        paid = validate_success(
            api.approve_invoice_payment(
                second["invoice"]["id"], FISCAL_OFFICER_HEADERS
            )
        )
        assert paid["payment_status"] == "PAID"
        assert paid["settled_amount_cents"] == RESIDENTIAL_NET_CENTS

        account = read_account(api, world["account"]["id"])
        assert_ledger_identity(account)
        assert_ledger(
            account,
            available=78790000,
            encumbered=16572226,
            disbursed=TWO_CYCLES_PAID_CENTS,
        )

        placement = read_placement(api, world["placement"]["id"])
        assert placement["paid_total_ytd_cents"] == TWO_CYCLES_PAID_CENTS

        claims, meta = list_rows(
            api.list_funding_claims(
                FISCAL_OFFICER_HEADERS, {"placement_id": world["placement"]["id"]}
            )
        )
        assert meta["total_count"] == 1
        claim = claims[0]
        assert claim["claim_type"] == "HIGH_COST_FUND"
        assert claim["source"] == "AUTO_CASCADE"
        assert claim["status"] == "ELIGIBLE"
        assert claim["fiscal_year"] == 2027
        assert claim["eligible_base_cents"] == TWO_CYCLES_PAID_CENTS
        assert claim["tier_rate"] == pytest.approx(HIGH_COST_TIER_RATE)
        assert claim["reimbursable_amount_cents"] == HIGH_COST_REIMBURSABLE_CENTS
        assert TWO_CYCLES_PAID_CENTS - 4000000 == HIGH_COST_EXCESS_CENTS

        student = read_student(api, world["student"]["id"])
        assert student["high_cost_flag"] is True
        assert (
            student["projected_state_recovery_cents"] == HIGH_COST_REIMBURSABLE_CENTS
        )


class TestPaymentGuards:
    """Two distinct refusals guard the money: the placement's and the route's."""

    def test_payment_beyond_the_placement_commitment_is_refused(self, api):
        """
        A placement that contracted a single instructional day holds only 32000
        cents of commitment, so a 654400-cent invoice cannot be paid from it even
        though the account is flush.

        PRD: "and the placement still holds enough unspent contract commitment — `contract_encumbrance_cents` minus `paid_total_ytd_cents` must be greater than or equal to `verified_amount_cents`, or the request is refused with `ERR_ENCUMBRANCE_EXCEEDED`."

        Design: Corner/errors/payment_beyond_the_remaining_contract_encumbrance_rejected
        """
        world = build_simple_billing_cycle(
            api, placement_overrides={"contracted_instructional_days": 1}
        )
        assert world["placement"]["contract_encumbrance_cents"] == 32000
        invoice = create_invoice(
            api,
            world,
            world["placement"]["id"],
            world["record"]["id"],
            PLAIN_NET_CENTS,
            transport_days_billed=0,
        )
        verified = verify_invoice(api, invoice["id"], "ENROLLMENT")
        assert verified["verified_amount_cents"] == PLAIN_NET_CENTS

        response = api.approve_invoice_payment(invoice["id"], FISCAL_OFFICER_HEADERS)
        validate_error(response, ERR_ENCUMBRANCE_EXCEEDED, 402)

        after = read_invoice(api, invoice["id"])
        assert after["payment_status"] == "UNPAID"
        assert after["settled_amount_cents"] == 0
        assert after["approved_by_user_id"] is None

        account = read_account(api, world["account"]["id"])
        assert_ledger_identity(account)
        assert_ledger(account, available=99968000, encumbered=32000, disbursed=0)
        assert read_placement(api, world["placement"]["id"])["paid_total_ytd_cents"] == 0

    def test_billing_transport_days_without_an_active_assignment_is_refused(self, api):
        """
        The transport line is priced off an `ACTIVE` assignment, so billing twenty
        transport days with none in place fails at verification and computes nothing.

        PRD: "If the placement has no `ACTIVE` assignment at all while `transport_days_billed` is greater than 0, verification fails outright with `ERR_TRANSPORT_NOT_ASSIGNED`."

        Design: Corner/errors/transport_billing_without_an_active_assignment_rejected
        """
        world = build_simple_billing_cycle(
            api, placement_overrides={"transportation_required": True}
        )
        release_transport(api, world["assignment"]["id"])
        assert read_placement(api, world["placement"]["id"])["transport_status"] == (
            "RELEASED"
        )

        created = validate_success(
            api.create_tuition_invoice(
                f.tuition_invoice_payload(
                    world["placement"]["id"],
                    world["record"]["id"],
                    PLAIN_NET_CENTS,
                    placement_version(api, world["placement"]["id"]),
                    billing_period_start=FULL_MONTH_PERIOD["period_start"],
                    billing_period_end=FULL_MONTH_PERIOD["period_end"],
                    transport_days_billed=20,
                ),
                world["school_headers"],
            ),
            201,
        )

        response = api.verify_tuition_invoice(
            created["id"], f.verify_invoice_payload("ENROLLMENT"), COORDINATOR_HEADERS
        )
        validate_error(response, ERR_TRANSPORT_NOT_ASSIGNED, 409)

        after = read_invoice(api, created["id"])
        assert after["verification_status"] == "SUBMITTED"
        assert after["transport_line_cents"] == 0
        assert after["gross_billable_cents"] == 0
        assert after["verified_amount_cents"] == 0


class TestPaymentVisibility:
    """Every rollup the approval writes is readable on the very next request."""

    def test_the_approval_body_and_the_next_reads_already_carry_the_cascade(self, api):
        """
        The approval response itself shows the settled invoice, and the first reads
        of the placement, the account and the student agree with it immediately.

        PRD: "- **Link 2 (invoice to placement).** The placement's `paid_total_ytd_cents` is increased by `settled_amount_cents`, its `encumbrance_cents` is recomputed from the four components per §2.6 — which mechanically shrinks the contract component, since that component is the contract commitment net of payments to date — and its `version` is incremented."

        Design: Corner/consistency_model/every_cascade_from_payment_approval_is_visible_in_the_same_response
        """
        world = build_simple_billing_cycle(api)
        invoice = create_invoice(
            api,
            world,
            world["placement"]["id"],
            world["record"]["id"],
            PLAIN_NET_CENTS,
            transport_days_billed=0,
        )
        verify_invoice(api, invoice["id"], "ENROLLMENT")
        assert read_placement(api, world["placement"]["id"])["paid_total_ytd_cents"] == 0

        paid = validate_success(
            api.approve_invoice_payment(invoice["id"], FISCAL_OFFICER_HEADERS)
        )
        assert paid["payment_status"] == "PAID"
        assert paid["settled_amount_cents"] == PLAIN_NET_CENTS
        assert paid["approved_by_user_id"] == "u-fiscal-1"

        placement = read_placement(api, world["placement"]["id"])
        assert placement["paid_total_ytd_cents"] == PLAIN_NET_CENTS
        assert placement["encumbrance_cents"] == ENCUMBRANCE_AFTER_ONE_PAYMENT_CENTS

        account = read_account(api, world["account"]["id"])
        assert_ledger_identity(account)
        assert_ledger(
            account,
            available=94240000,
            encumbered=ENCUMBRANCE_AFTER_ONE_PAYMENT_CENTS,
            disbursed=PLAIN_NET_CENTS,
        )

        student = read_student(api, world["student"]["id"])
        assert student["high_cost_flag"] is False
        assert student["projected_state_recovery_cents"] == 0

        assert read_placement(api, world["placement"]["id"]) == placement
        assert read_account(api, world["account"]["id"]) == account
        assert read_student(api, world["student"]["id"]) == student
