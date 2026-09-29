"""Compensating actions on both conserved axes: waived credit cents and reclassified copies."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.api_client import api_client
from test_helpers.api_errors import ERR_ALREADY_TERMINAL, ERR_INVALID_STATE
from test_helpers.assertions import (
    assert_credit_buckets,
    assert_credit_pool_conserved,
    assert_ledger_buckets,
    assert_pct,
)
from test_helpers.factories import (
    reclassify_payload,
    undeliverable_event_payload,
    waive_payload,
)
from test_helpers.fixtures import (
    add_complete_rule_set,
    add_subscriber,
    certify_statement,
    move_clock,
    offer_make_good,
    open_statement,
    qualify_subscriber,
    read_contract,
    read_publication,
    read_subscriber,
    register_contract,
    register_publication,
    run_hygiene_sweep,
    settle_guarantees,
    waive_make_good,
)
from test_helpers.test_users import EXECUTIVE_HEADERS, MANAGER_HEADERS

PERIOD_START = "2026-07-01T00:00:00Z"
PERIOD_END = "2026-09-01T00:00:00Z"
SETTLEMENT_CLOCK = "2026-10-01T00:00:00Z"
WAIVER_REASON = "advertiser declined the credit in exchange for a schedule change"


def publication_short_of_its_guarantees(name):
    """A filed 1,200-copy statement over the closed quarter, ready to be settled."""
    publication = register_publication(
        name=name, industry_code="MANUFACTURING", materiality_pct=2.00
    )
    add_complete_rule_set(publication["id"])
    qualify_subscriber(
        publication["id"],
        signed_at="2026-07-01T00:00:00Z",
        captured_at="2026-07-15T00:00:00Z",
        company_name="Sierra Paid Works",
        subscription_class="PAID",
        copies=1200,
        paid_amount_cents=96000,
    )
    return publication


def file_the_quarter(publication_id):
    move_clock(SETTLEMENT_CLOCK)
    statement = open_statement(
        publication_id,
        period_start=PERIOD_START,
        period_end=PERIOD_END,
        basis="AS_OF_PERIOD_END",
    )
    assert statement["total_qualified_copies"] == 1200
    filed = certify_statement(statement["id"])
    assert filed["declared_total_copies"] == 1200
    return filed


def test_waiving_a_credit_moves_cents_between_buckets_without_touching_the_pool():
    """The waived cents leave the committed bucket and do not come back as available.

    "A `PublisherExecutive`, and only a `PublisherExecutive`, may waive an `OFFERED`
    obligation with a required `waiver_reason`, moving it `OFFERED → WAIVED`, recording
    `closed_reason` from `waiver_reason`, and performing the one compensating ledger
    move in this path: `credit_cents` leaves `makegood_credit_committed_cents` and
    enters `makegood_credit_waived_cents`, so `makegood_credit_available_cents` and
    `makegood_credit_pool_cents` are both unchanged and the pool identity still
    balances."

    Design: Difficulty/compensating_invariant/makegood_waiver_preserves_credit_pool_conservation
    """
    publication = publication_short_of_its_guarantees("Waiver Conservation Monthly")
    contract = register_contract(
        publication["id"],
        advertiser_name="Released Guarantee Media",
        insertion_count=12,
        gross_rate_cents_per_insertion=850000,
        guaranteed_rate_base=1750,
        shortfall_tolerance_pct=2.00,
    )
    assert_credit_buckets(
        contract, pool=10200000, committed=0, waived=0, available=10200000
    )

    filed = file_the_quarter(publication["id"])
    obligation = settle_guarantees(filed["id"])[0]
    assert obligation["credit_cents"] == 4808796
    offer_make_good(obligation["id"])

    before = read_contract(contract["id"])
    assert_credit_buckets(
        before, pool=10200000, committed=4808796, waived=0, available=5391204
    )
    assert_credit_pool_conserved(before)

    waived = waive_make_good(obligation["id"], waiver_reason=WAIVER_REASON)
    assert waived["status"] == "WAIVED"
    assert waived["closed_reason"] == WAIVER_REASON
    # The compensation is on the contract's buckets, not on the obligation's amount.
    assert waived["credit_cents"] == 4808796

    after = read_contract(contract["id"])
    assert_credit_buckets(
        after, pool=10200000, committed=0, waived=4808796, available=5391204
    )
    # The waiver did not return a single cent to the available bucket.
    assert (
        after["makegood_credit_available_cents"]
        == before["makegood_credit_available_cents"]
    )
    assert_credit_pool_conserved(after)


def test_the_waived_bucket_is_private_to_its_own_contract_and_the_row_is_terminal():
    """Two contracts settled together compensate independently, and a waiver closes for good.

    "`makegood_credit_committed_cents` sums `credit_cents` across the contract's
    obligations whose status is `PENDING`, `OFFERED` or `ACCEPTED`.
    `makegood_credit_waived_cents` sums `credit_cents` across those whose status is
    `WAIVED`. `makegood_credit_available_cents` is the pool minus the committed sum
    minus the waived sum."

    Design: Difficulty/compensating_invariant/makegood_waiver_preserves_credit_pool_conservation
    """
    publication = publication_short_of_its_guarantees("Two Guarantees Monthly")
    big = register_contract(
        publication["id"],
        advertiser_name="Tango Media Buying",
        insertion_count=12,
        gross_rate_cents_per_insertion=850000,
        guaranteed_rate_base=1750,
        shortfall_tolerance_pct=2.00,
    )
    small = register_contract(
        publication["id"],
        advertiser_name="Uniform Media Buying",
        insertion_count=10,
        gross_rate_cents_per_insertion=100000,
        guaranteed_rate_base=1300,
        shortfall_tolerance_pct=2.00,
    )

    filed = file_the_quarter(publication["id"])
    obligations = settle_guarantees(filed["id"])
    assert len(obligations) == 2
    by_contract = {row["contract_id"]: row for row in obligations}

    big_obligation = by_contract[big["id"]]
    assert big_obligation["credit_cents"] == 4808796
    small_obligation = by_contract[small["id"]]
    assert small_obligation["shortfall_copies"] == 100
    # 100 of 1,300 is 7.69 percent, which lands in the middle tier band.
    assert_pct(small_obligation["shortfall_pct"], 7.69)
    assert_pct(small_obligation["tier_factor"], 1.00)
    assert small_obligation["per_insertion_credit_cents"] == 7690
    assert small_obligation["credit_cents"] == 76900
    # 76,900 cents does not buy a whole insertion at 100,000 each.
    assert small_obligation["bonus_insertions"] == 0

    # A waiver is declared only from OFFERED, so the PENDING row refuses it.
    validate_error(
        api_client.waive_make_good(
            big_obligation["id"], waive_payload(), EXECUTIVE_HEADERS
        ),
        ERR_INVALID_STATE,
        409,
    )
    offer_make_good(big_obligation["id"])
    offer_make_good(small_obligation["id"])

    waive_make_good(big_obligation["id"], waiver_reason=WAIVER_REASON)

    compensated = read_contract(big["id"])
    assert_credit_buckets(
        compensated, pool=10200000, committed=0, waived=4808796, available=5391204
    )
    untouched = read_contract(small["id"])
    assert_credit_buckets(
        untouched, pool=1000000, committed=76900, waived=0, available=923100
    )
    assert_credit_pool_conserved(compensated)
    assert_credit_pool_conserved(untouched)

    # WAIVED is terminal, so the compensation cannot be applied twice.
    validate_error(
        api_client.waive_make_good(
            big_obligation["id"], waive_payload(), EXECUTIVE_HEADERS
        ),
        ERR_ALREADY_TERMINAL,
        409,
    )
    assert_credit_buckets(read_contract(big["id"]), committed=0, waived=4808796)


def reclassify(subscriber_id, subscription_class, **extra):
    response = api_client.reclassify_subscriber(
        subscriber_id, reclassify_payload(subscription_class, **extra), MANAGER_HEADERS
    )
    return validate_success(response, 200)


def test_reclassifying_and_reclassifying_back_restores_every_class_bucket():
    """The round trip returns each bucket to its exact starting value, not merely a valid one.

    "Reclassification is precisely compensating on the ledger: the old class bucket
    falls by the recipient's `copies` and the new class bucket rises by the same
    amount, so `copies_on_file_total` is untouched and the class-axis conserved
    quantity of §2.10 still holds."

    Design: Difficulty/compensating_invariant/subscriber_reclassification_round_trip_preserves_copy_conservation
    """
    publication = register_publication(
        name="Round Trip Monthly", industry_code="MANUFACTURING"
    )
    add_subscriber(
        publication["id"],
        company_name="Victor Paid Works",
        subscription_class="PAID",
        copies=950,
        paid_amount_cents=76000,
    )
    mover = add_subscriber(
        publication["id"],
        company_name="Whiskey Directed Works",
        subscription_class="CONTROLLED",
        copies=50,
    )

    before = read_publication(publication["id"])
    assert_ledger_buckets(
        before,
        total=1000,
        paid=950,
        qualified_non_paid=0,
        controlled=50,
        deliverable=1000,
        undeliverable=0,
        removed=0,
    )

    forward = reclassify(mover["id"], "PAID", paid_amount_cents=2500)
    assert forward["subscription_class"] == "PAID"
    assert forward["paid_amount_cents"] == 2500
    midway = read_publication(publication["id"])
    assert_ledger_buckets(
        midway, total=1000, paid=1000, qualified_non_paid=0, controlled=0
    )

    back = reclassify(mover["id"], "CONTROLLED")
    assert back["subscription_class"] == "CONTROLLED"
    # Two mutations, so exactly two version steps on the recipient.
    assert back["version"] == mover["version"] + 2

    after = read_publication(publication["id"])
    assert_ledger_buckets(
        after,
        total=1000,
        paid=950,
        qualified_non_paid=0,
        controlled=50,
        deliverable=1000,
        undeliverable=0,
        removed=0,
    )
    # The delivery axis was never in play, so the hygiene ratio never moved.
    assert_pct(after["undeliverable_pct"], 0.00)


def test_the_class_round_trip_leaves_a_displaced_delivery_axis_exactly_where_it_was():
    """Copies removed by a sweep stay removed while the class buckets travel and return.

    "On the class axis, `copies_on_file_total` always equals the sum of
    `paid_copies_on_file`, `qualified_non_paid_copies_on_file` and
    `controlled_copies_on_file`. On the delivery axis, `copies_on_file_total` always
    equals the sum of `deliverable_copies`, `undeliverable_copies` and
    `removed_copies`."

    Design: Difficulty/compensating_invariant/subscriber_reclassification_round_trip_preserves_copy_conservation
    """
    publication = register_publication(
        name="Two Axes Monthly", industry_code="MANUFACTURING"
    )
    add_subscriber(
        publication["id"],
        company_name="X-ray Paid Works",
        subscription_class="PAID",
        copies=600,
        paid_amount_cents=48000,
    )
    mover = add_subscriber(
        publication["id"],
        company_name="Yankee Requested Works",
        subscription_class="QUALIFIED_NON_PAID",
        copies=200,
    )
    add_subscriber(
        publication["id"],
        company_name="Zulu Directed Works",
        subscription_class="CONTROLLED",
        copies=200,
    )

    for _ in range(2):
        validate_success(
            api_client.record_undeliverable_event(
                mover["id"], undeliverable_event_payload(), MANAGER_HEADERS
            ),
            200,
        )
    sweep = run_hygiene_sweep(publication["id"], run_type="UNDELIVERABLE_SWEEP")
    assert sweep["removed_count"] == 1
    assert read_subscriber(mover["id"])["delivery_status"] == "REMOVED"

    displaced = read_publication(publication["id"])
    assert_ledger_buckets(
        displaced,
        total=1000,
        paid=600,
        qualified_non_paid=200,
        controlled=200,
        deliverable=800,
        undeliverable=0,
        removed=200,
    )
    assert_pct(displaced["undeliverable_pct"], 20.00)

    forward = reclassify(mover["id"], "CONTROLLED")
    assert forward["subscription_class"] == "CONTROLLED"
    # Reclassification never writes the delivery dimension.
    assert forward["delivery_status"] == "REMOVED"
    midway = read_publication(publication["id"])
    assert_ledger_buckets(
        midway,
        total=1000,
        paid=600,
        qualified_non_paid=0,
        controlled=400,
        deliverable=800,
        undeliverable=0,
        removed=200,
    )
    assert_pct(midway["undeliverable_pct"], 20.00)

    back = reclassify(mover["id"], "QUALIFIED_NON_PAID")
    assert back["subscription_class"] == "QUALIFIED_NON_PAID"
    assert back["delivery_status"] == "REMOVED"

    after = read_publication(publication["id"])
    assert_ledger_buckets(
        after,
        total=1000,
        paid=600,
        qualified_non_paid=200,
        controlled=200,
        deliverable=800,
        undeliverable=0,
        removed=200,
    )
    # Both axes reconcile, and the displaced one is untouched by the compensation.
    assert_pct(after["undeliverable_pct"], 20.00)
