"""Depth tests for the ``compensating_invariant`` rule.

Two quantities in this contract are conserved, and each has its own compensator.
Gross invoice face must always equal ``remaining_face_cents`` plus the face
covered by the payments still sitting in ``RESERVED``, ``DEPLOYED`` or
``RELEASED``; the forward drive is a reservation, and a recorded settlement
failure is the compensator that must hand the face back exactly, leaving the
offer ``ACCEPTED`` so a replacement payment can re-cover the same face without
the voided row ever being counted twice.

The funder's capital pool is the second: committed capital at the clock date
must always equal ``available_capital_cents`` plus ``encumbered_capital_cents``,
and the dispute-suppression cascade is its compensator. The hard step is in the
middle, because executing later than the requested pay date reprices the net and
the encumbrance has to move by exactly that delta rather than staying at its
reservation-time figure. Every checkpoint below reads the ledger back through
the public API rather than trusting the mutating response alone.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.api_errors import ERR_STALE_OFFER_VERSION
from test_helpers.assertions import (
    assert_cash_breakdown,
    assert_created_at_ascending,
    assert_funder_capital_conserved,
    assert_invoice,
    assert_invoice_face_conserved,
    assert_offer,
    assert_payment_axes,
    ids_of,
)
from test_helpers.test_users import (
    PLATFORM_OPS_HEADERS,
    make_buyer_treasury_headers,
)

# ─── Instance 1: the invoice-face pool ────────────────
# A face of 100000 at 1000 bps against a net due date of 2026-09-30.
FACE_A = 100_000
APR_A = 1_000

# Reservation and the first execution both work from 2026-08-05, which is
# 2026-09-30 - 2026-08-05 = 56 days on the pay-date basis:
#   100000 * 1000 * 56 / (10000 * 360) = 5600000000 / 3600000 = 1555.55… -> 1556
FIRST_DAYS = 56
FIRST_DISCOUNT = 1_556
FIRST_NET = 98_444  # 100000 - 1556 - 0, self-funded so the fee is 0

# The 365-day year an implementation might reach for instead:
#   100000 * 1000 * 56 / (10000 * 365) = 5600000000 / 3650000 = 1534.24 -> 1534
WRONG_365_NET = 98_466  # 100000 - 1534

# The replacement executes on 2026-08-07, i.e. 2026-09-30 - 2026-08-07 = 54:
#   100000 * 1000 * 54 / 3600000 = 5400000000 / 3600000 = 1500 exactly
REPLACEMENT_DAYS = 54
REPLACEMENT_DISCOUNT = 1_500
REPLACEMENT_NET = 98_500
REPLACEMENT_VALUE_DATE_DAY = "2026-08-09"  # execution 2026-08-07 plus two days

# Confirmation reprices on the value-date basis, 2026-09-30 - 2026-08-09 = 52:
#   100000 * 1000 * 52 / 3600000 = 5200000000 / 3600000 = 1444.44… -> 1444
FINAL_DAYS = 52
FINAL_DISCOUNT = 1_444
FINAL_NET = 98_556  # 100000 - 1444 - 0
TRUE_UP = -56  # 1444 - 1500

SELF_ONLY_PROGRAM = {
    "program_type": "SUPPLIER_NAMED",
    "max_acceptable_apr_bps": 1200,
    "min_days_early": 5,
    "concentration_cap_pct": 100.00,
    "funding_policy": "SELF_ONLY",
}

# ─── Instance 2: the funder-capital pool ──────────────
# A face of 1000000 at 900 bps against a net due date of 2026-09-04, financed
# by one funder holding a single 60000000-cent tranche over 2026-08-01..12-31.
FACE_B = 1_000_000
APR_B = 900
COMMITTED = 60_000_000

# Reservation prices from the requested pay date 2026-08-05, so
# 2026-09-04 - 2026-08-05 = 30 days:
#   1000000 * 900 * 30 / 3600000 = 27000000000 / 3600000 = 7500 exactly
RESERVED_DAYS = 30
RESERVED_DISCOUNT = 7_500
RESERVED_PRE_FEE_NET = 992_500  # 1000000 - 7500, below 5000000 so the tier is 45 bps
RESERVED_FEE = 4_466  # 992500 * 45 / 10000 = 4466.25 -> 4466
RESERVED_NET = 988_034  # 1000000 - 7500 - 4466
RESERVED_AVAILABLE = 59_011_966  # 60000000 - 988034

# Execution lands on 2026-08-12, so 2026-09-04 - 2026-08-12 = 23 days:
#   1000000 * 900 * 23 / 3600000 = 20700000000 / 3600000 = 5750 exactly
DEPLOYED_DAYS = 23
DEPLOYED_DISCOUNT = 5_750
DEPLOYED_FEE = 4_474  # 994250 * 45 / 10000 = 4474.125 -> 4474
DEPLOYED_NET = 989_776  # 1000000 - 5750 - 4474
DEPLOYED_AVAILABLE = 59_010_224  # 60000000 - 989776
NET_DELTA = 1_742  # 989776 - 988034, and 59011966 - 59010224

# Keying the fee tier on the post-fee net instead of the pre-fee net:
#   989776 * 45 / 10000 = 4453.99… -> 4454
WRONG_POST_FEE_KEYED_FEE = 4_454

FUNDER_ONLY_PROGRAM = {
    "program_type": "SUPPLIER_NAMED",
    "max_acceptable_apr_bps": 1200,
    "min_days_early": 5,
    "concentration_cap_pct": 100.00,
    "funding_policy": "FUNDER_ONLY",
}


def _self_funded_award():
    """An OPEN SELF_ONLY programme on a well-capitalised buyer, one onboarded
    supplier, a LIVE session, and an ACCEPTED 1000 bps offer on a 100000-cent
    invoice due 2026-09-30 with a requested pay date of 2026-08-05.

    The clock is parked at 2026-08-02, and ``ctx.offer_version`` carries the OCC
    anchor as it stands immediately after acceptance.
    """
    ctx = fx.build_base(
        clock="2026-08-01T00:00:00Z",
        buyer_overrides={
            "legal_name": "Face Conservation Buyer",
            "credit_limit_cents": 100_000_000,
            "self_funding_enabled": True,
        },
        program_overrides=dict(
            SELF_ONLY_PROGRAM, name="Face Conservation Programme"
        ),
        supplier_overrides={
            "legal_name": "Conservation Supply Co",
            "remittance_email": "ar@conservation.example",
        },
        session_window=("2026-08-02T00:00:00Z", "2026-08-31T00:00:00Z"),
    )
    fx.ingest_rows(
        ctx,
        [
            f.payable_row(
                ctx.supplier_id,
                invoice_number="CN-1",
                approval_date="2026-07-22T00:00:00Z",
                net_due_date="2026-09-30T00:00:00Z",
                line_amount_cents=FACE_A,
                tax_rate_bps=0,
            )
        ],
    )
    fx.set_clock("2026-08-02T00:00:00Z")
    ctx.clock = "2026-08-02T00:00:00Z"
    fx.load_invoices(ctx)
    offer = fx.name_offer(
        ctx.invoice_id,
        ctx.session_id,
        ctx.supplier_id,
        ctx.invoice_version,
        offered_apr_bps=APR_A,
        requested_pay_date="2026-08-05T00:00:00Z",
        acceptance_deadline="2026-08-20T00:00:00Z",
    )
    ctx.offer_id = offer["id"]
    accepted = fx.accept_offer_as_buyer(ctx.offer_id, ctx.buyer_id)
    ctx.offer_version = accepted["version"]
    return ctx


def _funder_financed_award():
    """An OPEN FUNDER_ONLY programme whose buyer cannot self-fund at all, one
    ACTIVE funder holding a single 60000000-cent tranche over
    2026-08-01..2026-12-31, and an ACCEPTED 900 bps offer on a 1000000-cent
    invoice due 2026-09-04 with a requested pay date of 2026-08-05."""
    ctx = fx.build_base(
        clock="2026-08-01T00:00:00Z",
        buyer_overrides={
            "legal_name": "Pool Conservation Buyer",
            "credit_limit_cents": 1_000,
            "self_funding_enabled": False,
        },
        program_overrides=dict(
            FUNDER_ONLY_PROGRAM, name="Pool Conservation Programme"
        ),
        supplier_overrides={
            "legal_name": "Pool Supply Co",
            "remittance_email": "ar@poolsupply.example",
        },
        session_window=("2026-08-02T00:00:00Z", "2026-08-31T00:00:00Z"),
        funders=[
            {
                "legal_name": "Pool Conservation Capital",
                "capital_limit_cents": COMMITTED,
                "min_apr_bps": 500,
                "fee_spread_bps": 0,
                "max_single_invoice_cents": 5_000_000,
                "committed_amount_cents": COMMITTED,
                "effective_from": "2026-08-01T00:00:00Z",
                "effective_to": "2026-12-31T00:00:00Z",
            }
        ],
    )
    fx.ingest_rows(
        ctx,
        [
            f.payable_row(
                ctx.supplier_id,
                invoice_number="PL-1",
                approval_date="2026-07-22T00:00:00Z",
                net_due_date="2026-09-04T00:00:00Z",
                line_amount_cents=FACE_B,
                tax_rate_bps=0,
            )
        ],
    )
    fx.set_clock("2026-08-02T00:00:00Z")
    ctx.clock = "2026-08-02T00:00:00Z"
    fx.load_invoices(ctx)
    offer = fx.name_offer(
        ctx.invoice_id,
        ctx.session_id,
        ctx.supplier_id,
        ctx.invoice_version,
        offered_apr_bps=APR_B,
        requested_pay_date="2026-08-05T00:00:00Z",
        acceptance_deadline="2026-08-20T00:00:00Z",
    )
    ctx.offer_id = offer["id"]
    accepted = fx.accept_offer_as_buyer(ctx.offer_id, ctx.buyer_id)
    ctx.offer_version = accepted["version"]
    return ctx


def _payments_of_invoice(ctx):
    """Every early payment on the scenario's invoice, created_at ascending."""
    rows, meta = validate_paginated(
        api_client.list_early_payments(
            make_buyer_treasury_headers(ctx.buyer_id), invoice_id=ctx.invoice_id
        )
    )
    assert_created_at_ascending(rows)
    return rows, meta


def _counted_face(rows):
    """The conserved sum: face_covered_cents over the payments whose
    funding_status is RESERVED, DEPLOYED or RELEASED."""
    counted = ("RESERVED", "DEPLOYED", "RELEASED")
    return sum(
        row["face_covered_cents"] for row in rows if row["funding_status"] in counted
    )


def _encumbered_from_rows(rows):
    """The conserved sum on the funder side: net_payment_cents over the
    payments whose funding_status is RESERVED or DEPLOYED."""
    return sum(
        row["net_payment_cents"]
        for row in rows
        if row["funding_status"] in ("RESERVED", "DEPLOYED")
    )


def test_failed_settlement_hands_the_whole_invoice_face_back_with_no_residue():
    """Three checkpoints on the face ledger: 0/100000 before anything, 100000/0
    once the payment is reserved and executed, and exactly 0/100000 again after
    the settlement failure — with the offer left ACCEPTED and its bumped
    ``version`` the only anchor a replacement reservation may carry.

    PRD §2.10: "The first is **gross invoice face**. For every invoice,
    `face_amount_cents` must always equal `remaining_face_cents` plus the sum of
    `face_covered_cents` over that invoice's early payments whose
    `funding_status` is `RESERVED`, `DEPLOYED` or `RELEASED`."

    PRD §2.10: "After a forward action followed by its compensation the equality
    must hold with `remaining_face_cents` back at its original value; a residual
    of even one cent is a defect."

    PRD §3.8: "The remittance axis moves `REMITTED → FAILED` and the cash axis
    moves `DEPLOYED → VOID`, releasing the funder's `encumbered_capital_cents`
    or the buyer's `credit_used_cents` in full."

    PRD §3.8: "Deliberately, the invoice's `status` stays `AWARDED`, its
    `provisional_discount_cents` returns to 0, and the offer stays `ACCEPTED` —
    so a replacement reservation can be created against the same award without
    renegotiating the rate."

    PRD §3.8: "It also increments the offer's `version` by one, which is what
    makes any further reservation carrying the old `expected_offer_version`
    stale."

    PRD §2.6: "If that value does not equal the offer's current `version`, the
    create is rejected with `ERR_STALE_OFFER_VERSION` (HTTP 412)."

    Design: Difficulty/compensating_invariant/invoice_face_conservation_survives_failed_settlement_and_replacement
    """
    ctx = _self_funded_award()

    # ── checkpoint 1: nothing reserved, so the whole face is remaining ──
    before = fx.read_invoice(ctx.invoice_id, ctx.buyer_id)
    assert_invoice(
        before,
        status="AWARDED",
        face_amount_cents=FACE_A,
        face_covered_cents=0,
        remaining_face_cents=FACE_A,
        provisional_discount_cents=0,
        final_discount_cents=0,
        discount_true_up_cents=0,
    )
    assert_invoice_face_conserved(before)
    assert _counted_face(_payments_of_invoice(ctx)[0]) == 0, (
        "no payment exists yet, so the counted face must be 0"
    )

    # ── checkpoint 2: the reservation drives the ledger to 100000/0 ──
    reserved = fx.reserve_payment(ctx.offer_id, ctx.offer_version, ctx.buyer_id)
    assert_payment_axes(
        reserved,
        funding_status="RESERVED",
        settlement_status="UNSENT",
        accounting_status="UNCLASSIFIED",
    )
    assert reserved["funding_source"] == "BUYER_SELF", (
        "a SELF_ONLY programme resolves to the buyer's own balance sheet"
    )
    assert_cash_breakdown(
        reserved,
        days_early=FIRST_DAYS,
        discount_amount_cents=FIRST_DISCOUNT,
        funder_fee_cents=0,
        net_payment_cents=FIRST_NET,
    )
    assert reserved["net_payment_cents"] != WRONG_365_NET, (
        "the discount uses a 360-day year, not 365"
    )
    after_reserve = fx.read_invoice(ctx.invoice_id, ctx.buyer_id)
    assert_invoice(
        after_reserve,
        face_amount_cents=FACE_A,
        face_covered_cents=FACE_A,
        remaining_face_cents=0,
    )
    assert_invoice_face_conserved(after_reserve)
    assert _counted_face(_payments_of_invoice(ctx)[0]) == FACE_A, (
        "the single RESERVED row covers the whole face"
    )

    fx.set_clock("2026-08-05T00:00:00Z")
    deployed = fx.execute_payment(reserved["id"], ctx.buyer_id)
    assert_payment_axes(
        deployed, funding_status="DEPLOYED", settlement_status="REMITTED"
    )
    assert str(deployed["execution_date"]).startswith("2026-08-05"), (
        "execution_date is stamped from the logical clock, got {!r}".format(
            deployed["execution_date"]
        )
    )
    # The real execution date equals the requested pay date here, so the
    # pay-date-basis figures are unchanged by the recompute.
    assert_cash_breakdown(
        deployed,
        days_early=FIRST_DAYS,
        discount_amount_cents=FIRST_DISCOUNT,
        net_payment_cents=FIRST_NET,
    )
    still_covered = fx.read_invoice(ctx.invoice_id, ctx.buyer_id)
    assert_invoice(
        still_covered,
        face_covered_cents=FACE_A,
        remaining_face_cents=0,
        provisional_discount_cents=FIRST_DISCOUNT,
    )
    assert_invoice_face_conserved(still_covered)

    # ── checkpoint 3: the compensator gives the face back exactly ──
    fx.set_clock("2026-08-07T00:00:00Z")
    voided = fx.fail_settlement(
        reserved["id"],
        ctx.buyer_id,
        failure_reason="Supplier bank rejected the credit as account name mismatch",
    )
    assert_payment_axes(
        voided,
        funding_status="VOID",
        settlement_status="FAILED",
        accounting_status="UNCLASSIFIED",
    )
    assert voided["funding_status"] != "RELEASED", (
        "a returned payment leaves the counted set as VOID, never as RELEASED"
    )

    after_fail = fx.read_invoice(ctx.invoice_id, ctx.buyer_id)
    assert_invoice(
        after_fail,
        status="AWARDED",
        face_amount_cents=FACE_A,
        face_covered_cents=0,
        remaining_face_cents=FACE_A,
        provisional_discount_cents=0,
    )
    assert_invoice_face_conserved(after_fail)
    assert after_fail["remaining_face_cents"] != FACE_A - 1, (
        "a one-cent residue on the compensated ledger is a defect"
    )
    assert after_fail["face_covered_cents"] != FACE_A, (
        "the VOID row must leave the counted set entirely"
    )
    assert after_fail["status"] != "EARLY_PAID", (
        "a failed settlement never marks the invoice paid"
    )
    assert _counted_face(_payments_of_invoice(ctx)[0]) == 0, (
        "the only payment is VOID, so nothing is counted against the face"
    )

    # ── the offer survives, and its bumped version is the only usable anchor ──
    offer_after = fx.read_offer(ctx.offer_id, ctx.buyer_id)
    assert_offer(offer_after, status="ACCEPTED", accepted_apr_bps=APR_A)
    assert offer_after["status"] != "EXPIRED", (
        "the award is preserved so the rate need not be renegotiated"
    )
    assert offer_after["version"] == ctx.offer_version + 1, (
        "the reservation bumped the offer version once and the failure did not, "
        "expected {}, got {}".format(ctx.offer_version + 1, offer_after["version"])
    )
    stale = api_client.create_early_payment(
        f.early_payment_payload(ctx.offer_id, ctx.offer_version),
        make_buyer_treasury_headers(ctx.buyer_id),
    )
    validate_error(stale, ERR_STALE_OFFER_VERSION, 412)
    assert _counted_face(_payments_of_invoice(ctx)[0]) == 0, (
        "the refused reservation must not have touched the face ledger"
    )


def test_replacement_payment_recovers_the_face_without_counting_the_void_row():
    """Checkpoints four and five: after the replacement is reserved and executed
    the ledger is back at 100000/0 with exactly one row counted — the VOID row is
    never double-counted — and confirmation keeps it there because `RELEASED` is
    still inside the counted set, while the value-date recompute writes the
    52-day true-up.

    PRD §2.10: "The first is **gross invoice face**. For every invoice,
    `face_amount_cents` must always equal `remaining_face_cents` plus the sum of
    `face_covered_cents` over that invoice's early payments whose
    `funding_status` is `RESERVED`, `DEPLOYED` or `RELEASED`."

    PRD §3.8: "`value_date` is then set to `execution_date` advanced by two
    days."

    PRD §3.8: "Because the actual execution date usually differs from the
    originally requested pay date, `days_early`, `discount_amount_cents` — still
    on the pay-date basis, now measured from the real `execution_date` —
    `funder_fee_cents` and `net_payment_cents` are all recomputed"

    PRD §3.8: "The discount is then recomputed on the value-date basis, and
    `days_early`, `funder_fee_cents` and `net_payment_cents` are rewritten from
    it."

    PRD §3.8: "its `final_discount_cents` is written from the value-date-basis
    discount, and its `discount_true_up_cents` is written as
    `final_discount_cents` minus `provisional_discount_cents` — a signed figure
    that is negative whenever the APR is positive, because the value-date basis
    always spans two fewer days."

    Design: Difficulty/compensating_invariant/invoice_face_conservation_survives_failed_settlement_and_replacement
    """
    ctx = _self_funded_award()
    first = fx.reserve_payment(ctx.offer_id, ctx.offer_version, ctx.buyer_id)
    fx.set_clock("2026-08-05T00:00:00Z")
    fx.execute_payment(first["id"], ctx.buyer_id)
    fx.set_clock("2026-08-07T00:00:00Z")
    fx.fail_settlement(first["id"], ctx.buyer_id)

    anchor = fx.read_offer(ctx.offer_id, ctx.buyer_id)
    assert_offer(anchor, status="ACCEPTED")

    # ── checkpoint 4: the replacement re-covers the same face, once ──
    second = fx.reserve_payment(ctx.offer_id, anchor["version"], ctx.buyer_id)
    assert second["id"] != first["id"], "the replacement is a new row"
    assert_payment_axes(
        second, funding_status="RESERVED", settlement_status="UNSENT"
    )
    deployed = fx.execute_payment(second["id"], ctx.buyer_id)
    assert_payment_axes(
        deployed, funding_status="DEPLOYED", settlement_status="REMITTED"
    )
    assert str(deployed["execution_date"]).startswith("2026-08-07"), (
        "the replacement executes on the clock date, got {!r}".format(
            deployed["execution_date"]
        )
    )
    assert str(deployed["value_date"]).startswith(REPLACEMENT_VALUE_DATE_DAY), (
        "value_date is 2026-08-07 plus the two-day lag, got {!r}".format(
            deployed["value_date"]
        )
    )
    assert_cash_breakdown(
        deployed,
        days_early=REPLACEMENT_DAYS,
        discount_amount_cents=REPLACEMENT_DISCOUNT,
        funder_fee_cents=0,
        net_payment_cents=REPLACEMENT_NET,
    )
    assert deployed["net_payment_cents"] != FIRST_NET, (
        "the replacement reprices from its real 2026-08-07 execution date, not "
        "from the original 2026-08-05 pay date"
    )

    rows, meta = _payments_of_invoice(ctx)
    assert len(rows) == 2, "two payment rows exist, got {}".format(len(rows))
    assert meta["total_count"] == 2
    counted = [row for row in rows if row["funding_status"] != "VOID"]
    assert len(counted) == 1, (
        "exactly one row of this invoice is inside the counted set, got {}".format(
            len(counted)
        )
    )
    assert _counted_face(rows) == FACE_A, (
        "the counted face is the single live row's 100000, got {}".format(
            _counted_face(rows)
        )
    )
    assert _counted_face(rows) != 2 * FACE_A, (
        "the VOID row must never be double-counted into the covered face"
    )
    mid = fx.read_invoice(ctx.invoice_id, ctx.buyer_id)
    assert_invoice(
        mid,
        status="AWARDED",
        face_amount_cents=FACE_A,
        face_covered_cents=FACE_A,
        remaining_face_cents=0,
        provisional_discount_cents=REPLACEMENT_DISCOUNT,
    )
    assert_invoice_face_conserved(mid)

    # ── checkpoint 5: RELEASED is still counted, so the ledger does not move ──
    fx.set_clock("2026-08-09T00:00:00Z")
    released = fx.confirm_settlement(second["id"], ctx.buyer_id)
    assert_payment_axes(
        released, funding_status="RELEASED", settlement_status="CONFIRMED"
    )
    assert_cash_breakdown(
        released,
        days_early=FINAL_DAYS,
        discount_amount_cents=FINAL_DISCOUNT,
        funder_fee_cents=0,
        net_payment_cents=FINAL_NET,
        check_identity=False,
    )
    assert released["net_payment_cents"] != REPLACEMENT_NET, (
        "confirmation rewrites the net on the value-date basis"
    )

    final = fx.read_invoice(ctx.invoice_id, ctx.buyer_id)
    assert_invoice(
        final,
        status="EARLY_PAID",
        face_amount_cents=FACE_A,
        face_covered_cents=FACE_A,
        remaining_face_cents=0,
        provisional_discount_cents=REPLACEMENT_DISCOUNT,
        final_discount_cents=FINAL_DISCOUNT,
        discount_true_up_cents=TRUE_UP,
    )
    assert_invoice_face_conserved(final)
    assert final["remaining_face_cents"] != FACE_A, (
        "a RELEASED payment stays inside the counted set, so the face stays covered"
    )
    assert final["discount_true_up_cents"] != -TRUE_UP, (
        "the true-up is signed and negative: 1444 - 1500 is -56, not 56"
    )

    end_rows, end_meta = _payments_of_invoice(ctx)
    assert end_meta["total_count"] == 2
    assert sorted(ids_of(end_rows)) == sorted([first["id"], second["id"]]), (
        "the invoice filter returns exactly the two rows this test created"
    )
    axes = {row["id"]: row["funding_status"] for row in end_rows}
    assert axes[first["id"]] == "VOID", (
        "the failed row stays VOID, got {}".format(axes[first["id"]])
    )
    assert axes[second["id"]] == "RELEASED", (
        "the replacement settled to RELEASED, got {}".format(axes[second["id"]])
    )
    assert _counted_face(end_rows) == FACE_A


def test_execution_delta_moves_the_funder_encumbrance_by_exactly_the_net_change():
    """Checkpoints one to three on the funder's pool. An empty pool sums to the
    committed 60000000; the reservation encumbers 988034 against 59011966; and
    executing seven days later than the requested pay date shrinks days early
    from 30 to 23, raises the net to 989776 and must move the encumbrance by
    exactly that 1742-cent delta rather than leaving it at its reservation-time
    figure.

    PRD §2.10: "The second is **funder capital covering the clock date**. For
    every funder, the capital committed at the logical clock date must always
    equal `available_capital_cents` plus `encumbered_capital_cents`, where
    `encumbered_capital_cents` is the sum of `net_payment_cents` over that
    funder's early payments whose `funding_status` is `RESERVED` or `DEPLOYED`."

    PRD §2.10: "One subtlety must be honoured or the sum drifts: the
    recomputation of the discount at execution time changes `net_payment_cents`,
    and the encumbrance must be adjusted by exactly that delta rather than left
    at its reservation-time figure."

    PRD §3.7: "`available_capital_cents` is then that committed figure at the
    logical clock's current date minus the funder's `encumbered_capital_cents`,
    floored at zero so it never goes negative."

    PRD §3.8: "**The funder fee** is computed immediately after the discount,
    and its tier is keyed on the **pre-fee net** — the invoice's
    `face_amount_cents` minus the payment's `discount_amount_cents` — never on
    the final net after the fee has been taken out."

    Design: Difficulty/compensating_invariant/funder_capital_conservation_across_execute_delta_and_suppression_void
    """
    ctx = _funder_financed_award()

    # ── checkpoint 1: nothing encumbered, the pool is entirely available ──
    idle = fx.read_funder(ctx.funder_id)
    assert idle["status"] == "ACTIVE"
    assert idle["available_capital_cents"] == COMMITTED, (
        "the whole 60000000 tranche covers 2026-08-02, got {}".format(
            idle["available_capital_cents"]
        )
    )
    assert idle["encumbered_capital_cents"] == 0
    assert_funder_capital_conserved(idle, COMMITTED)

    # ── checkpoint 2: the reservation encumbers the reservation-time net ──
    reserved = fx.reserve_payment(ctx.offer_id, ctx.offer_version, ctx.buyer_id)
    assert reserved["funding_source"] == "FUNDER", (
        "a FUNDER_ONLY programme has no self-funding candidate at all"
    )
    assert reserved["funder_id"] == ctx.funder_id
    assert_cash_breakdown(
        reserved,
        days_early=RESERVED_DAYS,
        discount_amount_cents=RESERVED_DISCOUNT,
        funder_fee_cents=RESERVED_FEE,
        net_payment_cents=RESERVED_NET,
    )
    after_reserve = fx.read_funder(ctx.funder_id)
    assert after_reserve["encumbered_capital_cents"] == RESERVED_NET, (
        "encumbrance is the payment's net 988034, got {}".format(
            after_reserve["encumbered_capital_cents"]
        )
    )
    assert after_reserve["available_capital_cents"] == RESERVED_AVAILABLE, (
        "available is 60000000 - 988034, got {}".format(
            after_reserve["available_capital_cents"]
        )
    )
    assert_funder_capital_conserved(after_reserve, COMMITTED)
    assert after_reserve["available_capital_cents"] != COMMITTED, (
        "a standing reservation must actually consume the pool"
    )
    assert after_reserve["encumbered_capital_cents"] != RESERVED_PRE_FEE_NET, (
        "the encumbrance is the net after the funder fee, not the pre-fee net"
    )

    # ── checkpoint 3: executing seven days late reprices and re-encumbers ──
    fx.set_clock("2026-08-12T00:00:00Z")
    deployed = fx.execute_payment(reserved["id"], ctx.buyer_id)
    assert_payment_axes(
        deployed, funding_status="DEPLOYED", settlement_status="REMITTED"
    )
    assert str(deployed["execution_date"]).startswith("2026-08-12"), (
        "execution_date is the clock date, got {!r}".format(
            deployed["execution_date"]
        )
    )
    assert_cash_breakdown(
        deployed,
        days_early=DEPLOYED_DAYS,
        discount_amount_cents=DEPLOYED_DISCOUNT,
        funder_fee_cents=DEPLOYED_FEE,
        net_payment_cents=DEPLOYED_NET,
    )
    assert deployed["days_early"] != RESERVED_DAYS, (
        "days early is remeasured from the real execution date, 23 not 30"
    )
    assert deployed["funder_fee_cents"] != WRONG_POST_FEE_KEYED_FEE, (
        "the fee is keyed on the 994250 pre-fee net, never on the final net"
    )
    assert deployed["funder_fee_cents"] != RESERVED_FEE, (
        "the fee is recomputed at execution time along with the discount"
    )

    after_execute = fx.read_funder(ctx.funder_id)
    assert after_execute["encumbered_capital_cents"] == DEPLOYED_NET, (
        "encumbrance follows the repriced net 989776, got {}".format(
            after_execute["encumbered_capital_cents"]
        )
    )
    assert after_execute["available_capital_cents"] == DEPLOYED_AVAILABLE, (
        "available is 60000000 - 989776, got {}".format(
            after_execute["available_capital_cents"]
        )
    )
    assert_funder_capital_conserved(after_execute, COMMITTED)
    assert after_execute["encumbered_capital_cents"] != RESERVED_NET, (
        "leaving the encumbrance at its reservation-time 988034 is the drift bug"
    )
    assert after_execute["available_capital_cents"] != RESERVED_AVAILABLE, (
        "the available side has to move by the same delta"
    )
    assert (
        after_execute["encumbered_capital_cents"]
        - after_reserve["encumbered_capital_cents"]
        == NET_DELTA
    ), "the encumbrance moved by exactly 1742 cents, got {}".format(
        after_execute["encumbered_capital_cents"]
        - after_reserve["encumbered_capital_cents"]
    )
    assert (
        after_reserve["available_capital_cents"]
        - after_execute["available_capital_cents"]
        == NET_DELTA
    ), "the available side gave up exactly the same 1742 cents"
    rows, _ = _payments_of_invoice(ctx)
    assert _encumbered_from_rows(rows) == after_execute["encumbered_capital_cents"], (
        "encumbrance is recomputed in full from the qualifying payment rows"
    )


def test_dispute_suppression_void_restores_the_funder_pool_with_zero_drift():
    """Checkpoint four: raising a dispute on the financed invoice drives the
    DEPLOYED payment to VOID, and the pool must come back to 60000000 available
    against 0 encumbered — not to the 989776 the payment was holding — while the
    capital tranche itself is untouched, proving the committed side was never
    what changed.

    PRD §2.10: "Both the dispute-suppression cascade, which drives
    `funding_status` to `VOID`, and a recorded settlement failure are
    compensating actions that give the capital back."

    PRD §3.4: "Hop three applies when one of those offers had been `ACCEPTED` and
    financed: every early payment on it whose `funding_status` is `RESERVED` or
    `DEPLOYED` becomes `VOID`, and its encumbrance is released according to that
    payment's own funding source — a funder-financed payment decrements its
    funder's `encumbered_capital_cents` by that payment's `net_payment_cents` and
    triggers a recomputation of the funder's `available_capital_cents`"

    PRD §3.4: "Hop four is the ledger consequence: because those payments have
    left the reserved-deployed-released set, the invoice's `face_covered_cents`
    drops back to 0 and `remaining_face_cents` returns to `face_amount_cents`,
    restoring face conservation."

    PRD §3.4: "`reason_code` is one of `BUYER_FILE_SUPPRESSION`,
    `SHORT_SHIPMENT`, `PRICE_VARIANCE` or `GOODS_REJECTED`"

    PRD §3.7: "Tranches are persisted in `status` `ACTIVE`, and the only other
    tranche state is the terminal `EXPIRED`."

    Design: Difficulty/compensating_invariant/funder_capital_conservation_across_execute_delta_and_suppression_void
    """
    ctx = _funder_financed_award()
    payment = fx.reserve_payment(ctx.offer_id, ctx.offer_version, ctx.buyer_id)
    fx.set_clock("2026-08-12T00:00:00Z")
    deployed = fx.execute_payment(payment["id"], ctx.buyer_id)
    assert_cash_breakdown(deployed, net_payment_cents=DEPLOYED_NET)
    before = fx.read_funder(ctx.funder_id)
    assert before["encumbered_capital_cents"] == DEPLOYED_NET
    assert_funder_capital_conserved(before, COMMITTED)

    # ── the compensator: a dispute on the financed invoice ──
    fx.set_clock("2026-08-13T00:00:00Z")
    dispute = fx.raise_dispute(
        ctx.invoice_id, ctx.buyer_id, 400_000, reason_code="GOODS_REJECTED"
    )
    assert dispute["status"] == "OPEN"
    assert dispute["reason_code"] == "GOODS_REJECTED"
    assert dispute["disputed_amount_cents"] == 400_000
    assert dispute["invoice_id"] == ctx.invoice_id

    # ── checkpoint 4: the pool is whole again, with no drift ──
    after = fx.read_funder(ctx.funder_id)
    assert after["encumbered_capital_cents"] == 0, (
        "the VOID payment releases its whole encumbrance, got {}".format(
            after["encumbered_capital_cents"]
        )
    )
    assert after["available_capital_cents"] == COMMITTED, (
        "available returns to the committed 60000000, got {}".format(
            after["available_capital_cents"]
        )
    )
    assert_funder_capital_conserved(after, COMMITTED)
    assert after["encumbered_capital_cents"] != DEPLOYED_NET, (
        "leaving 989776 standing behind a voided payment is the drift bug"
    )
    assert after["available_capital_cents"] != DEPLOYED_AVAILABLE, (
        "the available side must be given back too"
    )
    assert after["available_capital_cents"] != RESERVED_AVAILABLE, (
        "releasing only the reservation-time 988034 leaves a 1742-cent residue"
    )
    assert after["status"] == "ACTIVE", "the funder itself is not touched"

    voided = fx.read_payment(payment["id"], ctx.buyer_id)
    assert_payment_axes(voided, funding_status="VOID")
    assert voided["funding_status"] != "DEPLOYED", (
        "hop three drives the financed payment out of the encumbered set"
    )
    rows, _ = _payments_of_invoice(ctx)
    assert _encumbered_from_rows(rows) == 0, (
        "no payment row of this invoice qualifies for encumbrance any more"
    )

    # ── the offer and the invoice ledger follow the same cascade ──
    assert_offer(
        fx.read_offer(ctx.offer_id, ctx.buyer_id), status="VOIDED_BY_SUPPRESSION"
    )
    invoice = fx.read_invoice(ctx.invoice_id, ctx.buyer_id)
    assert_invoice(
        invoice,
        status="SUPPRESSED",
        dispute_suppressed=True,
        face_amount_cents=FACE_B,
        face_covered_cents=0,
        remaining_face_cents=FACE_B,
    )
    assert_invoice_face_conserved(invoice)
    assert invoice["remaining_face_cents"] != 0, (
        "the suppression cascade hands the whole face back"
    )
    assert invoice["status"] != "MATURED", (
        "MATURED is the upheld-resolution outcome, not the suppression outcome"
    )

    # ── committed capital was never the thing that moved ──
    tranches, meta = validate_paginated(
        api_client.list_commitments(ctx.funder_id, PLATFORM_OPS_HEADERS)
    )
    assert meta["total_count"] == 1, "one tranche was ever committed"
    tranche = tranches[0]
    assert tranche["id"] == ctx.funder["commitment_id"]
    assert tranche["status"] == "ACTIVE", (
        "the tranche is untouched by the suppression, got {}".format(
            tranche["status"]
        )
    )
    assert tranche["status"] != "EXPIRED", (
        "releasing an encumbrance never expires committed capital"
    )
    assert tranche["committed_amount_cents"] == COMMITTED
    reread = validate_success(
        api_client.get_funder(ctx.funder_id, PLATFORM_OPS_HEADERS)
    )
    assert_funder_capital_conserved(reread, COMMITTED)
