"""Reserve provisioning: the two disputed bases, the tier floors and the append-only ledger."""

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers.assertions import (
    assert_fields_absent,
    assert_identity_fields,
    assert_ledger_entry,
    assert_money,
    assert_reserve_summary,
)
from test_helpers.constants import (
    RATED_TOTAL_PRELIMINARY,
    RESERVE_BUCKET_DISPUTED,
    RESERVE_BUCKET_UNCOLLECTIBLE,
)
from test_helpers.factories import dispute_payload, payment_payload
from test_helpers.fixtures import (
    read_carrier,
    read_invoice,
    read_ledger,
    read_reserve_summary,
    setup_dispute,
    setup_issued_invoice,
)

DISPUTED = 10.00
ISSUE_RESERVE = 1.62
NET_AFTER_DISPUTE = 22.47
RESERVE_AFTER_DISPUTE = 0.45


def test_reserve_ledger_entry_links_carrier_and_invoice_across_aggregates(
    api, controller_headers
):
    """The single issue-time entry is reachable from both the carrier and the invoice.

    PRD 2.11: "An entry's `invoice_id` names the access invoice that caused the movement, and is null for a carrier-level reserve re-measurement that no single invoice can be attributed to."
    PRD 3.10: "Filtering it by `carrier_id` gives a carrier's full reserve history in `created_at` ascending order, and narrowing further by `invoice_id` isolates the movements attributable to a single invoice; `reserve_bucket` and `entry_type` filters separate the disputed-revenue story from the uncollectible one."
    PRD 2.4: "Four record types are deliberately immutable-shaped ledger rows and carry **only** `id` and `created_at` — both `updated_at` and `version` are absent from them entirely: negotiation offers, traffic measurements, call detail records and reserve ledger entries."

    Design: Corner/entities/reserve_ledger_entry_links_carrier_and_invoice_across_aggregates
    """
    state = setup_issued_invoice(api)

    by_carrier, carrier_meta = validate_paginated(
        api.list_reserve_ledger_entries(
            controller_headers, {"carrier_id": state["carrier_id"]}
        )
    )
    assert carrier_meta["total_count"] == 1
    entry = by_carrier[0]
    assert entry["reserve_bucket"] == RESERVE_BUCKET_UNCOLLECTIBLE
    assert_money(entry["amount_usd"], ISSUE_RESERVE)
    assert_money(entry["balance_after_usd"], ISSUE_RESERVE)

    by_invoice, invoice_meta = validate_paginated(
        api.list_reserve_ledger_entries(
            controller_headers, {"invoice_id": state["invoice_id"]}
        )
    )
    assert invoice_meta["total_count"] == 1
    assert by_invoice[0]["id"] == entry["id"]

    assert entry["carrier_id"] == state["carrier_id"]
    assert entry["invoice_id"] == state["invoice_id"]
    assert_identity_fields(entry, "reserve ledger entry")
    assert_fields_absent(entry, ("version",), "reserve ledger entry")


def test_reserve_provision_reports_regulatory_and_gaap_bases_from_one_dispute(api):
    """One 10.00 dispute yields a 10.00 regulatory hold and a 6.00 GAAP reserve.

    PRD 2.11: "Because the regulator requires disputed access revenue to be held in full until the dispute closes, the persisted `disputed_reserve_balance_usd` on the carrier equals the whole `disputed_receivable_usd`, and every reserve ledger entry in the `DISPUTED_REVENUE` bucket moves that regulatory figure."
    PRD 2.11: "The **GAAP basis** reserves only the probable loss: `disputed_receivable_usd` multiplied by 60.00 percent (the dispute loss probability), rounded half up to two decimal places."
    PRD 2.11: "`net_receivable_usd` is `open_receivable_usd` minus `disputed_receivable_usd`. If that net figure is zero or negative the applicable reserve percentage is zero. If it is positive but below twenty-five dollars the percentage is 2.00."

    Design: Difficulty/dual_variant_calc/reserve_provision_regulatory_versus_gaap_basis_on_carrier
    """
    state = setup_dispute(api)
    assert state["dispute"]["status"] == "SUBMITTED"

    assert_reserve_summary(
        read_reserve_summary(api, state["carrier_id"]),
        open_receivable_usd=RATED_TOTAL_PRELIMINARY,
        disputed_receivable_usd=DISPUTED,
        net_receivable_usd=NET_AFTER_DISPUTE,
        tier_pct=2.00,
        uncollectible_reserve_balance_usd=RESERVE_AFTER_DISPUTE,
        regulatory_disputed_reserve_usd=DISPUTED,
        gaap_disputed_reserve_usd=6.00,
        disputed_reserve_basis_delta_usd=4.00,
    )

    carrier = read_carrier(api, state["carrier_id"])
    assert_money(
        carrier["disputed_reserve_balance_usd"],
        DISPUTED,
        "the persisted balance follows the regulatory basis, never the GAAP basis",
    )
    assert_money(carrier["uncollectible_reserve_balance_usd"], RESERVE_AFTER_DISPUTE)


def test_second_dispute_moves_both_bases_but_persists_only_the_regulatory_one(api):
    """A 15.00 disputed base holds 15.00 in full while GAAP reserves 9.00.

    PRD 2.11: "`disputed_receivable_usd` is the sum of `disputed_amount_usd` over the carrier's access invoices whose `lifecycle_status` is `ISSUED`, regardless of payment position."
    PRD 2.11: "The **GAAP basis** reserves only the probable loss: `disputed_receivable_usd` multiplied by 60.00 percent (the dispute loss probability), rounded half up to two decimal places."
    PRD 2.11: "This figure is not persisted on the carrier; it is reported as `gaap_disputed_reserve_usd` by the carrier reserve-summary read, alongside `regulatory_disputed_reserve_usd`, the difference between them as `disputed_reserve_basis_delta_usd`, and the supporting `open_receivable_usd`, `disputed_receivable_usd`, `net_receivable_usd`, `tier_pct` and `uncollectible_reserve_balance_usd` values."

    Design: Difficulty/dual_variant_calc/reserve_provision_regulatory_versus_gaap_basis_on_carrier
    """
    state = setup_dispute(api)
    validate_success(
        api.create_dispute(
            dispute_payload(
                state["invoice_id"],
                disputed_amount_usd=5.00,
                reason_code="JURISDICTION_FACTOR",
                supporting_detail="Second element of the same period is also in question",
            ),
            state["rep_headers"],
        ),
        expected_status=201,
    )

    invoice = read_invoice(api, state["invoice_id"])
    assert_money(invoice["disputed_amount_usd"], 15.00)
    assert_money(invoice["open_balance_usd"], RATED_TOTAL_PRELIMINARY)

    assert_reserve_summary(
        read_reserve_summary(api, state["carrier_id"]),
        open_receivable_usd=RATED_TOTAL_PRELIMINARY,
        disputed_receivable_usd=15.00,
        net_receivable_usd=17.47,
        tier_pct=2.00,
        uncollectible_reserve_balance_usd=0.35,
        regulatory_disputed_reserve_usd=15.00,
        gaap_disputed_reserve_usd=9.00,
        disputed_reserve_basis_delta_usd=6.00,
    )

    carrier = read_carrier(api, state["carrier_id"])
    assert_money(carrier["disputed_reserve_balance_usd"], 15.00)
    assert_money(carrier["uncollectible_reserve_balance_usd"], 0.35)


def test_uncollectible_ledger_records_the_re_tier_in_creation_order(api):
    """Issue then dispute leave two ordered entries whose signed sum is the balance.

    PRD 2.11: "**Fourth**, and only after both balances are known, the ledger is written. For each of the two reserve buckets whose balance actually moved, a reserve ledger entry is appended carrying `amount_usd` equal to the new balance minus the old balance — positive when the reserve grows, negative when it releases — and `balance_after_usd` equal to the new balance."
    PRD 3.9: "The fourth hop appends a reserve ledger entry in bucket `DISPUTED_REVENUE` with `entry_type` `DISPUTE_PROVISION` and `source_event` `BILLING_DISPUTE_SUBMITTED` carrying the signed delta, followed by a second entry in bucket `UNCOLLECTIBLE` with `entry_type` `UNCOLLECTIBLE_ADJUSTMENT` and the same `source_event` whenever the re-tier actually moved the uncollectible balance."
    PRD 2.11: "The reserve balances are outputs only. They never feed back into `open_receivable_usd` or `net_receivable_usd`, so a single pass reaches the fixed point and re-running the calculation on unchanged inputs produces no ledger entries at all."

    Design: Difficulty/combinatorial_formula/reserve_evaluation_order_tier_then_balances_then_ledger
    """
    state = setup_dispute(api)

    entries = read_ledger(
        api, carrier_id=state["carrier_id"], reserve_bucket=RESERVE_BUCKET_UNCOLLECTIBLE
    )
    assert len(entries) == 2
    assert_ledger_entry(
        entries[0],
        entry_type="UNCOLLECTIBLE_ADJUSTMENT",
        source_event="INVOICE_CREATED",
        amount_usd=ISSUE_RESERVE,
        balance_after_usd=ISSUE_RESERVE,
        reserve_bucket=RESERVE_BUCKET_UNCOLLECTIBLE,
    )
    assert_ledger_entry(
        entries[1],
        entry_type="UNCOLLECTIBLE_ADJUSTMENT",
        source_event="BILLING_DISPUTE_SUBMITTED",
        amount_usd=-1.17,
        balance_after_usd=RESERVE_AFTER_DISPUTE,
        reserve_bucket=RESERVE_BUCKET_UNCOLLECTIBLE,
    )
    assert entries[0]["created_at"] <= entries[1]["created_at"]

    carrier = read_carrier(api, state["carrier_id"])
    signed_sum = round(sum(float(entry["amount_usd"]) for entry in entries), 2)
    assert signed_sum == RESERVE_AFTER_DISPUTE
    assert_money(carrier["uncollectible_reserve_balance_usd"], RESERVE_AFTER_DISPUTE)
    assert_money(carrier["disputed_reserve_balance_usd"], DISPUTED)

    assert_reserve_summary(
        read_reserve_summary(api, state["carrier_id"]),
        net_receivable_usd=NET_AFTER_DISPUTE,
        tier_pct=2.00,
    )


def test_reserve_summary_reads_append_no_ledger_entries_of_their_own(
    api, controller_headers
):
    """Each bucket's last balance is the live balance, and a re-read writes nothing.

    PRD 2.11: "The carrier-level reserve position is the system's financial summary, and it is recomputed **from scratch** on every event that changes a carrier's receivable or dispute position: issuing an invoice, applying a payment, writing a balance off, submitting, escalating, withdrawing or resolving a dispute, a deemed-allowed sweep outcome, a reconciliation adjustment, and a factor-audit re-rate."
    PRD 2.11: "The reserve balances are outputs only. They never feed back into `open_receivable_usd` or `net_receivable_usd`, so a single pass reaches the fixed point and re-running the calculation on unchanged inputs produces no ledger entries at all."
    PRD 3.10: "Because entries are never rewritten, the last entry in a bucket's history always carries that bucket's current `balance_after_usd`, and the entries between any two points sum exactly to the difference between their balances."

    Design: Difficulty/combinatorial_formula/reserve_evaluation_order_tier_then_balances_then_ledger
    """
    state = setup_dispute(api)

    _, before = validate_paginated(
        api.list_reserve_ledger_entries(
            controller_headers, {"carrier_id": state["carrier_id"]}
        )
    )
    assert before["total_count"] == 3

    read_reserve_summary(api, state["carrier_id"])
    read_reserve_summary(api, state["carrier_id"])

    _, after = validate_paginated(
        api.list_reserve_ledger_entries(
            controller_headers, {"carrier_id": state["carrier_id"]}
        )
    )
    assert after["total_count"] == 3, "a computed read appends nothing"

    disputed = read_ledger(
        api, carrier_id=state["carrier_id"], reserve_bucket=RESERVE_BUCKET_DISPUTED
    )
    assert len(disputed) == 1
    assert_ledger_entry(
        disputed[-1],
        entry_type="DISPUTE_PROVISION",
        source_event="BILLING_DISPUTE_SUBMITTED",
        amount_usd=DISPUTED,
        balance_after_usd=DISPUTED,
        reserve_bucket=RESERVE_BUCKET_DISPUTED,
    )
    uncollectible = read_ledger(
        api, carrier_id=state["carrier_id"], reserve_bucket=RESERVE_BUCKET_UNCOLLECTIBLE
    )
    assert_money(uncollectible[-1]["balance_after_usd"], RESERVE_AFTER_DISPUTE)

    carrier = read_carrier(api, state["carrier_id"])
    assert_money(carrier["disputed_reserve_balance_usd"], DISPUTED)
    assert_money(carrier["uncollectible_reserve_balance_usd"], RESERVE_AFTER_DISPUTE)


def test_net_receivable_of_exactly_twenty_five_dollars_selects_tier_two(api):
    """A payment that lands the net exactly on 25.00 keeps the 5.00 percent tier.

    PRD 2.11: "The tier floors are inclusive at their lower edge: a net receivable of exactly 25.00 sits in the second tier, while 24.99 sits in the first, and exactly 250.00 sits in the third."
    PRD 2.11: "If it is at least twenty-five dollars but below two hundred and fifty dollars the percentage is 5.00."
    PRD 3.8: "Where the payment lands determines the resulting dimension move: an amount strictly less than the open balance moves `payment_status` `UNPAID → PARTIALLY_PAID`, while an amount exactly equal to the open balance moves it `UNPAID → PAID` when no earlier payment had been applied and `PARTIALLY_PAID → PAID` when one had."

    Design: Difficulty/boundary_precision_check/net_receivable_exactly_twenty_five_dollars_selects_tier_two
    """
    state = setup_issued_invoice(api)

    paid = validate_success(
        api.apply_payment(
            state["invoice_id"],
            payment_payload(7.47, remittance_reference="WIRE-2026-09-01-TO-FLOOR"),
            state["rep_headers"],
        ),
        expected_status=200,
    )
    assert_money(paid["open_balance_usd"], 25.00)
    assert paid["payment_status"] == "PARTIALLY_PAID"

    assert_reserve_summary(
        read_reserve_summary(api, state["carrier_id"]),
        open_receivable_usd=25.00,
        net_receivable_usd=25.00,
        tier_pct=5.00,
        uncollectible_reserve_balance_usd=1.25,
    )

    entries = read_ledger(
        api, carrier_id=state["carrier_id"], reserve_bucket=RESERVE_BUCKET_UNCOLLECTIBLE
    )
    assert len(entries) == 2
    assert_ledger_entry(
        entries[1],
        entry_type="UNCOLLECTIBLE_ADJUSTMENT",
        source_event="INVOICE_PAYMENT_APPLIED",
        amount_usd=-0.37,
        balance_after_usd=1.25,
    )


def test_one_cent_below_the_floor_drops_to_the_two_percent_tier(api):
    """A single cent under 25.00 falls out of the second tier into the first.

    PRD 2.11: "The tier floors are inclusive at their lower edge: a net receivable of exactly 25.00 sits in the second tier, while 24.99 sits in the first, and exactly 250.00 sits in the third."
    PRD 2.11: "If it is positive but below twenty-five dollars the percentage is 2.00."
    PRD 3.8: "Because the uncollectible balance changed, the third hop appends a reserve ledger entry in bucket `UNCOLLECTIBLE` with `entry_type` `UNCOLLECTIBLE_ADJUSTMENT` and `source_event` `INVOICE_PAYMENT_APPLIED`, carrying the signed delta."

    Design: Difficulty/boundary_precision_check/net_receivable_exactly_twenty_five_dollars_selects_tier_two
    """
    state = setup_issued_invoice(api)
    validate_success(
        api.apply_payment(
            state["invoice_id"],
            payment_payload(7.47, remittance_reference="WIRE-2026-09-01-TO-FLOOR"),
            state["rep_headers"],
        ),
        expected_status=200,
    )
    one_cent = validate_success(
        api.apply_payment(
            state["invoice_id"],
            payment_payload(0.01, remittance_reference="WIRE-2026-09-01-ONE-CENT"),
            state["rep_headers"],
        ),
        expected_status=200,
    )
    assert_money(one_cent["open_balance_usd"], 24.99)

    assert_reserve_summary(
        read_reserve_summary(api, state["carrier_id"]),
        net_receivable_usd=24.99,
        tier_pct=2.00,
        uncollectible_reserve_balance_usd=0.50,
    )

    carrier = read_carrier(api, state["carrier_id"])
    assert_money(carrier["uncollectible_reserve_balance_usd"], 0.50)

    entries = read_ledger(
        api, carrier_id=state["carrier_id"], reserve_bucket=RESERVE_BUCKET_UNCOLLECTIBLE
    )
    assert len(entries) == 3
    assert_money(entries[0]["amount_usd"], ISSUE_RESERVE)
    assert_money(entries[0]["balance_after_usd"], ISSUE_RESERVE)
    assert_money(entries[1]["amount_usd"], -0.37)
    assert_money(entries[1]["balance_after_usd"], 1.25)
    assert_money(entries[2]["amount_usd"], -0.75)
    assert_money(entries[2]["balance_after_usd"], 0.50)
