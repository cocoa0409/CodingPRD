"""Quarterly traffic factors: the sum ceiling, supersession, dispute lock and audit."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_errors import (
    ERR_FACTOR_FILING_DISPUTE_OPEN,
    ERR_FACTOR_SUM_EXCEEDS_TOTAL,
)
from test_helpers.assertions import (
    assert_invoice_dimensions,
    assert_ledger_amounts,
    assert_ledger_entry,
    assert_minutes,
    assert_money,
    assert_pct,
)
from test_helpers.constants import (
    BILLABLE_MINUTES_TOTAL,
    FACTOR_QUARTER,
    RATED_INTERSTATE_PRELIMINARY,
    RATED_INTRASTATE_PRELIMINARY,
    RATED_LOCAL_PRELIMINARY,
    RATED_TOTAL_PRELIMINARY,
    T_2026_08_01,
)
from test_helpers.factories import (
    factor_audit_payload,
    factor_filing_payload,
    factor_review_accept_payload,
    factor_review_dispute_payload,
)
from test_helpers.fixtures import (
    read_carrier,
    read_factor_filing,
    read_invoice,
    read_ledger,
    read_usage_batch,
    setup_carrier,
    setup_factor_filing,
    setup_issued_invoice,
    setup_rated_batch,
)


def test_factor_filing_whose_piu_and_plu_exceed_one_hundred_is_refused(
    api, analyst_headers
):
    """A 60.00/50.00 pair breaches the pairwise ceiling with its own safety code.

    PRD 3.6: "The two reported percentages together may not exceed 100.00; a pairwise sum above that is refused with `ERR_FACTOR_SUM_EXCEEDS_TOTAL`, and that ceiling is enforced as a business-safety rule in its own priority band rather than as a range check on either field individually."
    PRD 2.7: "Regulatory caps come first: the access charge reform parity cap, the reciprocal compensation rate cap, and the traffic factor sum ceiling are evaluated before the transit-permission and unrateable-record refusals."

    Design: Corner/validations/factor_filing_whose_piu_and_plu_exceed_one_hundred_is_refused
    """
    carrier = setup_carrier(api)
    assert carrier["version"] == 1

    response = api.create_factor_filing(
        factor_filing_payload(
            carrier["id"], carrier["version"], reported_piu_pct=60.00, reported_plu_pct=50.00
        ),
        analyst_headers,
    )
    validate_error(response, ERR_FACTOR_SUM_EXCEEDS_TOTAL, expected_status=422)

    _, meta = validate_paginated(
        api.list_carrier_factor_filings(carrier["id"], analyst_headers)
    )
    assert meta["total_count"] == 0, "the refused filing must not be persisted"

    assert read_carrier(api, carrier["id"])["version"] == 1, (
        "the rejected write never bumped the stale-view parent"
    )


def test_factor_filing_whose_piu_and_plu_sum_to_exactly_one_hundred_is_accepted(
    api, analyst_headers
):
    """A 70.00/30.00 pair sits exactly on the ceiling and is accepted.

    PRD 3.6: "The two reported percentages together may not exceed 100.00; a pairwise sum above that is refused with `ERR_FACTOR_SUM_EXCEEDS_TOTAL`, and that ceiling is enforced as a business-safety rule in its own priority band rather than as a range check on either field individually."
    PRD 3.6: "A new filing lands in `status` `REPORTED`, with `audited_piu_pct`, `audited_plu_pct`, `dispute_reason`, `audit_completed_at` and `superseded_at` all null. Its `effective_piu_pct` and `effective_plu_pct` — the pair that jurisdiction determination actually consumes — mirror the reported values."
    PRD 3.6: "Creating a filing also increments the carrier's `version` by 1, and — as covered in §2.6 — requires `expected_carrier_version` to match the carrier's current `version`."

    Design: Corner/validations/factor_filing_whose_piu_and_plu_sum_to_exactly_one_hundred_is_accepted
    """
    carrier = setup_carrier(api)

    response = api.create_factor_filing(
        factor_filing_payload(
            carrier["id"], carrier["version"], reported_piu_pct=70.00, reported_plu_pct=30.00
        ),
        analyst_headers,
    )
    filing = validate_success(response, expected_status=201)

    assert filing["status"] == "REPORTED"
    assert_pct(filing["effective_piu_pct"], 70.00, "effective_piu_pct")
    assert_pct(filing["effective_plu_pct"], 30.00, "effective_plu_pct")
    assert filing["audited_piu_pct"] is None
    assert filing["audit_completed_at"] is None

    assert read_carrier(api, carrier["id"])["version"] == 2, (
        "the accepted write bumped the stale-view parent"
    )


def test_factor_filing_supersession_retires_the_previous_filing_for_the_quarter(
    api, analyst_headers
):
    """A second 2026Q3 filing supersedes the first and stamps its retirement.

    PRD 3.6: "Filing a new quarter's factors **supersedes** the prior filing for that same carrier and quarter. Whichever prior filing is in `REPORTED`, `ACCEPTED`, `DISPUTED` or `AUDITED` moves to `SUPERSEDED`, which is terminal, with its `superseded_at` stamped from the logical clock and its `version` incremented by 1."
    PRD 3.6: "A decision of `ACCEPT` moves the filing to `ACCEPTED` and its `effective_piu_pct` and `effective_plu_pct` resolve to the reported values; it is permitted from `REPORTED` and from `AUDITED`."

    Design: Corner/state_machines/factor_filing_supersession_retires_the_previous_filing_for_the_quarter
    """
    carrier = setup_carrier(api)
    first = setup_factor_filing(api, carrier)
    validate_success(
        api.review_factor_filing(
            first["id"], factor_review_accept_payload(), analyst_headers
        ),
        expected_status=200,
    )
    refreshed = read_carrier(api, carrier["id"])

    response = api.create_factor_filing(
        factor_filing_payload(
            carrier["id"],
            refreshed["version"],
            reported_piu_pct=72.00,
            reported_plu_pct=8.00,
        ),
        analyst_headers,
    )
    second = validate_success(response, expected_status=201)

    assert second["status"] == "REPORTED"
    assert_pct(second["effective_piu_pct"], 72.00, "effective_piu_pct")
    assert_pct(second["effective_plu_pct"], 8.00, "effective_plu_pct")

    retired = read_factor_filing(api, first["id"])
    assert retired["status"] == "SUPERSEDED"
    assert retired["superseded_at"] == T_2026_08_01

    rows, meta = validate_paginated(
        api.list_carrier_factor_filings(
            carrier["id"], analyst_headers, params={"quarter": FACTOR_QUARTER}
        )
    )
    assert meta["total_count"] == 2
    assert [row["status"] for row in rows].count("SUPERSEDED") == 1, (
        "exactly one of the two rows was retired"
    )


def test_factor_filing_for_a_quarter_under_dispute_is_refused(api, analyst_headers):
    """A standing DISPUTED filing locks the quarter against new factors.

    PRD 3.6: "There is one refusal built into this: a filing for a carrier-and-quarter pair that currently has a filing in `DISPUTED` is rejected with `ERR_FACTOR_FILING_DISPUTE_OPEN`, because the standing challenge must be audited or accepted before new factors may displace it."
    PRD 3.6: "A decision of `DISPUTE` moves the filing to `DISPUTED` and requires a non-empty `dispute_reason`, which is stored on the filing; it is permitted from `REPORTED`, from `ACCEPTED` and from `AUDITED`."

    Design: Corner/errors/factor_filing_for_a_quarter_under_dispute_is_refused
    """
    carrier = setup_carrier(api)
    filing = setup_factor_filing(api, carrier)
    validate_success(
        api.review_factor_filing(
            filing["id"], factor_review_dispute_payload(), analyst_headers
        ),
        expected_status=200,
    )
    refreshed = read_carrier(api, carrier["id"])

    response = api.create_factor_filing(
        factor_filing_payload(
            carrier["id"],
            refreshed["version"],
            reported_piu_pct=40.00,
            reported_plu_pct=20.00,
        ),
        analyst_headers,
    )
    validate_error(response, ERR_FACTOR_FILING_DISPUTE_OPEN, expected_status=409)

    standing = read_factor_filing(api, filing["id"])
    assert standing["status"] == "DISPUTED"
    assert_pct(standing["effective_piu_pct"], 50.00, "effective_piu_pct")
    assert_pct(standing["effective_plu_pct"], 10.00, "effective_plu_pct")

    _, meta = validate_paginated(
        api.list_carrier_factor_filings(carrier["id"], analyst_headers)
    )
    assert meta["total_count"] == 1


def _rated_batch_under_disputed_factors(api, analyst_headers, state=None):
    """A PRELIMINARY-rated batch whose pinned 2026Q3 filing has been disputed."""
    state = state or setup_rated_batch(api)
    filing = state["factor_filing"]
    disputed = validate_success(
        api.review_factor_filing(
            filing["id"], factor_review_dispute_payload(), analyst_headers
        ),
        expected_status=200,
    )
    assert disputed["status"] == "DISPUTED"
    batch = state["batch"]
    assert batch["rating_variant"] == "PRELIMINARY"
    assert batch["traffic_factor_filing_id"] == filing["id"]
    assert_money(batch["rated_amount_usd"], RATED_TOTAL_PRELIMINARY, "rated_amount_usd")
    return state


def test_factor_audit_moves_the_batch_from_preliminary_to_final_minutes(
    api, analyst_headers, controller_headers
):
    """Audited 80.00/5.00 factors re-allocate the 63 indeterminate minutes.

    PRD 3.6: "The filing moves `DISPUTED → AUDITED`, the audited pair is stored, `effective_piu_pct` and `effective_plu_pct` now resolve to the audited values, and `audit_completed_at` is stamped from the logical clock."
    PRD 3.6: "In the first hop, every usage batch whose pinned `traffic_factor_filing_id` is this filing and whose `status` is `RATED` or `INVOICED` is re-jurisdictionalised and re-rated with the audited factors, processed in `created_at` ascending order; each such batch has its three minute buckets, its three jurisdiction subtotals and its `rated_amount_usd` rewritten, its `rating_variant` set to `FINAL`, its `rerate_count` incremented by 1, its `rated_at` refreshed from the logical clock, and its `version` incremented by 1; the batch's `status` does not move, so a re-rated batch stays `RATED` if it was `RATED` and stays `INVOICED` if it was `INVOICED`."
    PRD 3.7: "The allocated interstate minutes are `indeterminate_minutes` multiplied by the working interstate percentage and divided by one hundred, rounded half up to four decimal places; the allocated local minutes are `indeterminate_minutes` multiplied by the working local percentage and divided by one hundred, rounded half up to four decimal places; and the allocated intrastate minutes are `indeterminate_minutes` less the allocated interstate minutes less the allocated local minutes, with no rounding of their own — which is precisely why no rounding remainder is ever lost."
    PRD 3.7: "The conservation invariant holds by construction: the three buckets always re-sum to `total_billable_minutes`."

    Design: Difficulty/dual_variant_calc/access_charge_rating_preliminary_to_final_on_usage_batch
    """
    state = _rated_batch_under_disputed_factors(api, analyst_headers)
    filing_id = state["factor_filing"]["id"]

    response = api.audit_factor_filing(
        filing_id, factor_audit_payload(80.00, 5.00), controller_headers
    )
    audited = validate_success(response, expected_status=200)

    assert audited["status"] == "AUDITED"
    assert_pct(audited["effective_piu_pct"], 80.00, "effective_piu_pct")
    assert_pct(audited["effective_plu_pct"], 5.00, "effective_plu_pct")

    batch = read_usage_batch(api, state["batch_id"])
    assert batch["rating_variant"] == "FINAL"
    assert batch["rerate_count"] == 1
    assert batch["total_billable_minutes"] == BILLABLE_MINUTES_TOTAL
    assert_minutes(batch["interstate_minutes"], 52.4000, "interstate_minutes")
    assert_minutes(batch["intrastate_minutes"], 14.4500, "intrastate_minutes")
    assert_minutes(batch["local_minutes"], 6.1500, "local_minutes")
    assert_minutes(
        float(batch["interstate_minutes"])
        + float(batch["intrastate_minutes"])
        + float(batch["local_minutes"]),
        73.0000,
        "conserved minutes",
    )


def test_factor_audit_rewrites_the_three_jurisdiction_subtotals(
    api, analyst_headers, controller_headers
):
    """The FINAL variant shifts money onto interstate and off intrastate and local.

    PRD 3.7: "**Per-jurisdiction subtotals** are then formed for interstate, intrastate and local, and the two legs of each subtotal are rounded **separately before being added**: the signaling leg is the sum of `rated_amount_usd` over the signaling-determined records of that jurisdiction, rounded half up to two decimal places; the factor leg is that jurisdiction's allocated minutes multiplied by that jurisdiction's rate, rounded half up to two decimal places; and the subtotal is the sum of those two already-rounded figures."
    PRD 3.7: "**The batch total**, `rated_amount_usd`, is the exact sum of the three two-decimal subtotals and is never re-rounded."
    PRD 3.7: "When the pinned factor filing's `status` is `AUDITED`, the indeterminate minutes were allocated with audited percentages and the batch is `FINAL`."
    PRD 3.7: "Records whose `jurisdiction_source` is `FACTOR_ALLOCATED` keep `rated_amount_usd` null, because their charge is only defined at the batch bucket level."

    Design: Difficulty/dual_variant_calc/access_charge_rating_preliminary_to_final_on_usage_batch
    """
    state = _rated_batch_under_disputed_factors(api, analyst_headers)
    preliminary = state["batch"]
    assert_money(
        preliminary["interstate_amount_usd"],
        RATED_INTERSTATE_PRELIMINARY,
        "preliminary interstate_amount_usd",
    )
    assert_money(
        preliminary["intrastate_amount_usd"],
        RATED_INTRASTATE_PRELIMINARY,
        "preliminary intrastate_amount_usd",
    )
    assert_money(
        preliminary["local_amount_usd"],
        RATED_LOCAL_PRELIMINARY,
        "preliminary local_amount_usd",
    )

    validate_success(
        api.audit_factor_filing(
            state["factor_filing"]["id"],
            factor_audit_payload(80.00, 5.00),
            controller_headers,
        ),
        expected_status=200,
    )

    batch = read_usage_batch(api, state["batch_id"])
    assert_money(batch["interstate_amount_usd"], 26.86, "interstate_amount_usd")
    assert_money(batch["intrastate_amount_usd"], 7.05, "intrastate_amount_usd")
    assert_money(batch["local_amount_usd"], 0.37, "local_amount_usd")
    assert_money(batch["rated_amount_usd"], 34.28, "rated_amount_usd")
    assert round(
        float(batch["rated_amount_usd"]) - float(preliminary["rated_amount_usd"]), 2
    ) == 1.81, "the variant delta is exactly 1.81"

    records, _ = validate_paginated(
        api.list_batch_call_detail_records(state["batch_id"], analyst_headers)
    )
    allocated = [
        record
        for record in records
        if record["jurisdiction_source"] == "FACTOR_ALLOCATED"
    ]
    assert len(allocated) == 3
    for record in allocated:
        assert record["rated_amount_usd"] is None, (
            "a factor-allocated record carries no per-record charge"
        )


def test_factor_audit_cascade_refreshes_the_batch_and_its_issued_invoice(
    api, analyst_headers, controller_headers
):
    """Hops one and two: the re-rate stays INVOICED and rewrites the ISSUED invoice.

    PRD 3.6: "In the first hop, every usage batch whose pinned `traffic_factor_filing_id` is this filing and whose `status` is `RATED` or `INVOICED` is re-jurisdictionalised and re-rated with the audited factors, processed in `created_at` ascending order; each such batch has its three minute buckets, its three jurisdiction subtotals and its `rated_amount_usd` rewritten, its `rating_variant` set to `FINAL`, its `rerate_count` incremented by 1, its `rated_at` refreshed from the logical clock, and its `version` incremented by 1; the batch's `status` does not move, so a re-rated batch stays `RATED` if it was `RATED` and stays `INVOICED` if it was `INVOICED`."
    PRD 3.6: "Because a re-rated batch's `rated_amount_usd` changed, the second hop refreshes that batch's access invoice — if one exists and only while its `lifecycle_status` is `ISSUED` — rewriting `billed_amount_usd`, the three jurisdiction subtotals and `rating_variant`, recomputing `open_balance_usd`, incrementing `adjustment_count` by 1 and incrementing the invoice's `version` by 1."
    PRD 3.6: "Re-rating is a **self-loop on the batch's status dimension**: a batch that was `RATED` stays `RATED` and a batch that was `INVOICED` stays `INVOICED` while its amounts move underneath it."

    Design: Difficulty/transitive_cascade/factor_audit_cascade_batch_to_invoice_to_carrier_to_ledger
    """
    state = _rated_batch_under_disputed_factors(
        api, analyst_headers, state=setup_issued_invoice(api)
    )
    assert_money(
        state["invoice"]["billed_amount_usd"],
        RATED_TOTAL_PRELIMINARY,
        "billed_amount_usd",
    )

    validate_success(
        api.audit_factor_filing(
            state["factor_filing"]["id"],
            factor_audit_payload(80.00, 5.00),
            controller_headers,
        ),
        expected_status=200,
    )

    batch = read_usage_batch(api, state["batch_id"])
    assert_money(batch["rated_amount_usd"], 34.28, "rated_amount_usd")
    assert batch["rating_variant"] == "FINAL"
    assert batch["rerate_count"] == 1
    assert batch["status"] == "INVOICED", "the re-rate is a self-loop on the batch status"

    invoice = read_invoice(api, state["invoice_id"])
    assert_money(invoice["billed_amount_usd"], 34.28, "billed_amount_usd")
    assert_money(invoice["interstate_amount_usd"], 26.86, "interstate_amount_usd")
    assert_money(invoice["intrastate_amount_usd"], 7.05, "intrastate_amount_usd")
    assert_money(invoice["local_amount_usd"], 0.37, "local_amount_usd")
    assert_money(invoice["open_balance_usd"], 34.28, "open_balance_usd")
    assert invoice["rating_variant"] == "FINAL"
    assert invoice["adjustment_count"] == 1
    assert_invoice_dimensions(invoice, "ISSUED", "UNPAID", "NONE")


def test_factor_audit_cascade_reaches_the_carrier_reserves_and_the_ledger(
    api, analyst_headers, controller_headers
):
    """Hops three and four: the reserve is rebuilt and the delta is appended.

    PRD 3.6: "Because an invoice's `open_balance_usd` changed, the third hop re-runs the reserve recomputation of §2.11 for the carrier, rewriting `open_receivable_usd`, `uncollectible_reserve_balance_usd` and `disputed_reserve_balance_usd` and incrementing the carrier's `version` by 1."
    PRD 3.6: "Because the uncollectible balance changed, the fourth hop appends a reserve ledger entry in bucket `UNCOLLECTIBLE` with `entry_type` `UNCOLLECTIBLE_ADJUSTMENT` and `source_event` `FACTOR_AUDIT_RERATE`, carrying the signed delta."
    PRD 2.11: "If it is at least twenty-five dollars but below two hundred and fifty dollars the percentage is 5.00."
    PRD 2.11: "For each of the two reserve buckets whose balance actually moved, a reserve ledger entry is appended carrying `amount_usd` equal to the new balance minus the old balance — positive when the reserve grows, negative when it releases — and `balance_after_usd` equal to the new balance."

    Design: Difficulty/transitive_cascade/factor_audit_cascade_batch_to_invoice_to_carrier_to_ledger
    """
    state = _rated_batch_under_disputed_factors(
        api, analyst_headers, state=setup_issued_invoice(api)
    )
    carrier_id = state["carrier_id"]
    before = read_carrier(api, carrier_id)
    assert_money(before["open_receivable_usd"], RATED_TOTAL_PRELIMINARY, "open_receivable_usd")
    assert_money(
        before["uncollectible_reserve_balance_usd"], 1.62, "uncollectible_reserve_balance_usd"
    )

    validate_success(
        api.audit_factor_filing(
            state["factor_filing"]["id"],
            factor_audit_payload(80.00, 5.00),
            controller_headers,
        ),
        expected_status=200,
    )

    carrier = read_carrier(api, carrier_id)
    assert_money(carrier["open_receivable_usd"], 34.28, "open_receivable_usd")
    assert_money(carrier["net_receivable_usd"], 34.28, "net_receivable_usd")
    assert_money(
        carrier["uncollectible_reserve_balance_usd"], 1.71, "uncollectible_reserve_balance_usd"
    )
    assert_money(
        carrier["disputed_reserve_balance_usd"], 0.00, "disputed_reserve_balance_usd"
    )

    entries = read_ledger(api, carrier_id=carrier_id, reserve_bucket="UNCOLLECTIBLE")
    assert len(entries) == 2, f"expected two uncollectible entries, got {len(entries)}"
    assert_ledger_amounts(entries, [1.62, 0.09])
    assert_ledger_entry(
        entries[0], source_event="INVOICE_CREATED", balance_after_usd=1.62
    )
    assert_ledger_entry(
        entries[-1],
        entry_type="UNCOLLECTIBLE_ADJUSTMENT",
        source_event="FACTOR_AUDIT_RERATE",
        amount_usd=0.09,
        balance_after_usd=1.71,
        reserve_bucket="UNCOLLECTIBLE",
    )
