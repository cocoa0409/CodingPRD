"""Corner-case coverage of the contract's read-your-writes consistency model.

Nothing in this specification is eventually consistent: an operation that
creates or modifies a resource returns the created or updated resource in its own
``data`` field, every derived figure the write produced is already populated in
that response, and every cross-entity consequence of the write — the funder's
capital ledger, the invoice's face ledger — is visible on the very next read with
no settling delay.

The harness restarts the API server before every test, so each test builds all
of its own state from an empty database using the shared builders in
``test_helpers.fixtures``.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.assertions import (
    assert_cash_breakdown,
    assert_funder_capital_conserved,
    assert_invoice,
    assert_invoice_face_conserved,
    assert_payment,
    assert_payment_axes,
)
from test_helpers.test_users import PLATFORM_OPS_HEADERS


def test_every_write_is_visible_in_its_own_response_and_in_the_next_read():
    """A funder-financed reservation is the densest single write in the contract:
    it derives the discount, the tier-keyed funder fee, the net payment and the
    accounting default, encumbers the funder's capital and moves the invoice's
    face ledger. All of that must already be present in the create response
    itself — nothing null or zero pending a later recompute — and the funder
    ledger, the payment row and the invoice ledger must all read back with the
    same figures on the very next request, field for field.

    PRD §2.2: "The `data` field contains the resource object or an array of resource objects. For 2xx responses with no data, it contains an empty object. Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field."
    PRD §3.8: "`funding_source`, `funder_id`, `days_early`, `discount_amount_cents`, `funder_fee_cents`, `net_payment_cents` and `default_accounting_status` are all written at this moment."
    PRD §3.8: "Reservation encumbers whichever balance sheet won the waterfall — a funder's `encumbered_capital_cents` rises by `net_payment_cents` and its available capital is recomputed, or the buyer's `credit_used_cents` rises by the same amount — and it moves the invoice's face ledger, setting `face_covered_cents` to the full face and `remaining_face_cents` to 0."
    PRD §3.7: "`available_capital_cents` is then that committed figure at the logical clock's current date minus the funder's `encumbered_capital_cents`, floored at zero so it never goes negative."
    PRD §3.9: "For a funder-financed payment, the default is `DEBT_RECLASSIFIED` when either the payment's `days_early` is strictly greater than the buyer's `reclass_days_threshold` or the payment's `accepted_apr_bps` is strictly greater than the buyer's `reclass_apr_threshold_bps`, and `TRADE_PAYABLE` otherwise."
    Design: Corner/consistency_model/every_write_is_visible_in_its_own_response_and_in_the_next_read
    """
    committed_cents = 60_000_000
    ctx = fx.build_accepted_offer(
        requested_pay_date="2026-08-07T00:00:00Z",
        buyer_overrides={
            "legal_name": "Immediate Buyer",
            "credit_limit_cents": 100_000_000,
            "self_funding_enabled": False,
        },
        program_overrides={
            "name": "Immediate Programme",
            "funding_policy": "FUNDER_ONLY",
        },
        funders=[
            {
                "legal_name": "Immediate Capital",
                "capital_limit_cents": committed_cents,
                "min_apr_bps": 500,
                "fee_spread_bps": 0,
                "max_single_invoice_cents": 5_000_000,
                "committed_amount_cents": committed_cents,
                "effective_from": "2026-08-01T00:00:00Z",
                "effective_to": "2026-09-30T00:00:00Z",
            }
        ],
    )
    funder_id = ctx.funder_id
    face_cents = ctx.invoice["face_amount_cents"]
    assert face_cents == 100_000, "the fixture invoice face must be 100000 cents"

    # days early on the pay-date basis: 2026-09-30 minus 2026-08-07 == 54.
    expected_days_early = 54
    expected_discount = f.expected_discount_cents(face_cents, 900, expected_days_early)
    assert expected_discount == 1_350, (
        "100000 * 900 * 54 / (10000 * 360) is exactly 1350, got {}".format(
            expected_discount
        )
    )
    pre_fee_net = face_cents - expected_discount
    assert pre_fee_net == 98_650
    expected_fee = f.expected_funder_fee_cents(pre_fee_net, fee_spread_bps=0)
    assert expected_fee == 444, (
        "the pre-fee net of 98650 sits in the 45 bps tier: round_half_up(98650 * "
        "45 / 10000) is 444, got {}".format(expected_fee)
    )
    expected_net = pre_fee_net - expected_fee
    assert expected_net == 98_206

    before = validate_success(api_client.get_funder(funder_id, PLATFORM_OPS_HEADERS), 200)
    assert before["encumbered_capital_cents"] == 0
    assert before["available_capital_cents"] == committed_cents
    assert_funder_capital_conserved(before, committed_cents)

    # ─── The write ────────────────────────────────────
    created = validate_success(
        api_client.create_early_payment(
            f.early_payment_payload(ctx.offer_id, ctx.offer_version), ctx.treasury
        ),
        201,
    )
    payment_id = created["id"]

    # The create response already carries every derived figure.
    assert_payment(
        created,
        offer_id=ctx.offer_id,
        invoice_id=ctx.invoice_id,
        funding_source="FUNDER",
        funder_id=funder_id,
        accepted_apr_bps=900,
        face_covered_cents=face_cents,
        default_accounting_status="DEBT_RECLASSIFIED",
        version=1,
    )
    assert_payment_axes(
        created,
        funding_status="RESERVED",
        settlement_status="UNSENT",
        accounting_status="UNCLASSIFIED",
    )
    assert_cash_breakdown(
        created,
        days_early=expected_days_early,
        discount_amount_cents=expected_discount,
        funder_fee_cents=expected_fee,
        net_payment_cents=expected_net,
    )
    assert created["execution_date"] is None, (
        "a reserved payment has no execution_date yet, got {!r}".format(
            created["execution_date"]
        )
    )
    assert created["value_date"] is None, (
        "a reserved payment has no value_date yet, got {!r}".format(
            created["value_date"]
        )
    )

    # ─── The funder ledger on the very next read ──────
    funder_after = validate_success(
        api_client.get_funder(funder_id, PLATFORM_OPS_HEADERS), 200
    )
    assert funder_after["encumbered_capital_cents"] == expected_net, (
        "encumbered capital must rise by net_payment_cents immediately: expected "
        "{}, got {}".format(expected_net, funder_after["encumbered_capital_cents"])
    )
    assert funder_after["available_capital_cents"] == committed_cents - expected_net, (
        "available capital must fall by the same amount immediately: expected {}, "
        "got {}".format(
            committed_cents - expected_net, funder_after["available_capital_cents"]
        )
    )
    assert_funder_capital_conserved(funder_after, committed_cents)

    # ─── The payment row reads back field for field ───
    read_back = validate_success(
        api_client.get_early_payment(payment_id, ctx.treasury), 200
    )
    for key, value in created.items():
        assert read_back[key] == value, (
            "the read-back of the reserved payment must match the create response "
            "field for field: {} is {!r} on read but {!r} on create".format(
                key, read_back.get(key), value
            )
        )

    # ─── The cross-entity invoice ledger is visible too ───
    invoice_after = validate_success(
        api_client.get_invoice(ctx.invoice_id, ctx.treasury), 200
    )
    assert_invoice(
        invoice_after,
        id=ctx.invoice_id,
        status="AWARDED",
        face_amount_cents=face_cents,
        face_covered_cents=face_cents,
        remaining_face_cents=0,
    )
    assert_invoice_face_conserved(invoice_after)
