"""Usage batches, call detail ingest, jurisdiction determination and rating."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_errors import (
    ERR_BATCH_PERIOD_OVERLAP,
    ERR_CDR_UNRATEABLE,
    ERR_DUPLICATE_RECONCILIATION_CASE,
    ERR_INVALID_USAGE_PERIOD,
    ERR_NO_EFFECTIVE_TARIFF_RATE,
)
from test_helpers.assertions import (
    assert_created_at_ascending,
    assert_fields_absent,
    assert_identity_fields,
    assert_minutes,
    assert_money,
    assert_rate,
)
from test_helpers.constants import (
    BATCH_EXCHANGE_REFERENCE_IN,
    RATED_INTERSTATE_PRELIMINARY,
    RATED_INTRASTATE_PRELIMINARY,
    RATED_LOCAL_PRELIMINARY,
    RATED_TOTAL_PRELIMINARY,
    RATE_LOCAL,
    T_2026_08_01,
    T_2026_09_01,
)
from test_helpers.factories import (
    cdr_payload,
    local_cdr_payload,
    reconciliation_case_payload,
    usage_batch_payload,
)
from test_helpers.fixtures import (
    advance_clock,
    read_factor_filing,
    read_usage_batch,
    setup_carrier,
    setup_draft_invoice,
    setup_jurisdictionalized_batch,
    setup_rated_batch,
    setup_reconciliation_case,
    setup_submitted_batch,
)

PERIOD_OPEN_START = "2026-09-01T00:00:00.000Z"
PERIOD_OPEN_END = "2026-09-30T00:00:00.000Z"
PERIOD_LATE_START = "2026-07-15T00:00:00.000Z"


def test_usage_batch_whose_period_has_not_closed_is_refused(api, analyst_headers):
    """A batch whose period end is still ahead of the clock cannot be exchanged.

    PRD 3.7: "The period end must fall strictly after the period start **and** strictly before the logical clock — a period that has not yet closed cannot be exchanged — and a violation of either condition is refused with `ERR_INVALID_USAGE_PERIOD`."
    PRD 3.7: "An `AccessBillingAnalyst` opens a **usage batch** for a closed exchange period, naming the `carrier_id`, the `period_start` and `period_end` bounding it, a `direction` that is either `TERMINATING_TO_US` (traffic the counterparty handed us to terminate) or `ORIGINATING_FROM_US` (traffic we handed the counterparty), and the counterparty's `exchange_reference` for the batch, which must be non-empty."

    Design: Corner/validations/usage_batch_whose_period_has_not_closed_is_refused
    """
    carrier = setup_carrier(api)
    advance_clock(api, T_2026_09_01)

    response = api.create_usage_batch(
        usage_batch_payload(
            carrier["id"],
            period_start=PERIOD_OPEN_START,
            period_end=PERIOD_OPEN_END,
            exchange_reference="EXG-2026-09-IN",
        ),
        analyst_headers,
    )
    validate_error(response, ERR_INVALID_USAGE_PERIOD, expected_status=422)

    _, meta = validate_paginated(
        api.list_usage_batches(analyst_headers, params={"carrier_id": carrier["id"]})
    )
    assert meta["total_count"] == 0, "the refused batch must not be persisted"


def test_call_detail_record_is_readable_by_id_after_ingest(api, analyst_headers):
    """A freshly appended record reports its billable minutes and nothing else yet.

    PRD 3.7: "On acceptance the record's `billable_minutes` is computed immediately as its `duration_seconds` divided by 60 and rounded **up** to a whole number, its `jurisdiction`, `jurisdiction_source` and `rated_amount_usd` are left null, and the batch's `record_count` and `total_billable_minutes` increase accordingly with the batch's `version` incrementing by 1."
    PRD 2.4: "Every persisted resource carries an `id` that is a server-minted UUID with no type prefix and no client-supplied component, and a `created_at` timestamp in ISO 8601 UTC form with exactly three fractional digits, stamped from the logical clock at creation."
    PRD 2.4: "Four record types are deliberately immutable-shaped ledger rows and carry **only** `id` and `created_at` — both `updated_at` and `version` are absent from them entirely: negotiation offers, traffic measurements, call detail records and reserve ledger entries."

    Design: Corner/endpoints/call_detail_record_is_readable_by_id_after_ingest
    """
    state = setup_submitted_batch(api, builders=(local_cdr_payload,))
    appended = state["records"][0]

    response = api.get_call_detail_record(appended["id"], analyst_headers)
    record = validate_success(response, expected_status=200)

    assert record["id"] == appended["id"]
    assert record["usage_batch_id"] == state["batch_id"]
    assert record["duration_seconds"] == 180
    assert record["billable_minutes"] == 3
    assert record["jurisdiction"] is None
    assert record["jurisdiction_source"] is None
    assert record["rated_amount_usd"] is None
    assert_identity_fields(record, "call detail record")
    assert_fields_absent(record, ("version",), "call detail record")

    batch = read_usage_batch(api, state["batch_id"])
    assert batch["record_count"] == 1
    assert batch["status"] == "SUBMITTED"


def test_call_detail_record_with_no_terminating_state_is_refused_at_ingest(
    api, analyst_headers
):
    """A record that cannot be placed at all is unrateable and never lands.

    PRD 3.7: "A record without a `terminating_state_code` is **unrateable** and is refused at ingest with `ERR_CDR_UNRATEABLE`."
    PRD 3.7: "A new batch lands in `status` `SUBMITTED` with `record_count` at 0, `total_billable_minutes`, `signaling_determined_minutes`, `indeterminate_minutes`, `interstate_minutes`, `intrastate_minutes` and `local_minutes` all at 0, `interstate_amount_usd`, `intrastate_amount_usd`, `local_amount_usd` and `rated_amount_usd` all at 0.00, `rerate_count` at 0, and `traffic_factor_filing_id`, `factor_source`, `rating_variant`, `jurisdictionalized_at` and `rated_at` all null."

    Design: Corner/errors/call_detail_record_with_no_terminating_state_is_refused_at_ingest
    """
    state = setup_submitted_batch(api, builders=())
    batch_id = state["batch_id"]

    response = api.append_call_detail_record(
        batch_id,
        cdr_payload(
            terminating_npanxx="999888",
            duration_seconds=240,
            terminating_state_code=None,
            same_local_calling_area=False,
        ),
        analyst_headers,
    )
    validate_error(response, ERR_CDR_UNRATEABLE, expected_status=422)

    batch = read_usage_batch(api, batch_id)
    assert batch["record_count"] == 0
    assert_minutes(batch["total_billable_minutes"], 0.0000, "total_billable_minutes")

    _, meta = validate_paginated(
        api.list_batch_call_detail_records(batch_id, analyst_headers)
    )
    assert meta["total_count"] == 0, "the unrateable record must not be persisted"


def test_touching_usage_period_and_repeat_exchange_reference_are_refused(
    api, analyst_headers, controller_headers
):
    """A period that shares one instant and a repeated exchange file both conflict.

    PRD 3.7: "Periods for the same carrier and the same direction may neither overlap **nor touch**: a new `period_start` equal to an existing batch's `period_end` is rejected, as is any true overlap, with `ERR_BATCH_PERIOD_OVERLAP`."
    PRD 3.10: "At most one case may exist per batch-and-exchange-reference pair; a repeat is refused with `ERR_DUPLICATE_RECONCILIATION_CASE`."
    PRD 3.10: "Creation snapshots our side of the comparison: `our_minutes` from the batch's `total_billable_minutes` and `our_amount_usd` from the batch's `rated_amount_usd`."

    Design: Corner/errors/touching_usage_period_and_repeat_exchange_reference_are_refused
    """
    state = setup_draft_invoice(api)
    setup_reconciliation_case(api, state, evaluate=False)
    carrier_id = state["carrier_id"]

    touching = api.create_usage_batch(
        usage_batch_payload(
            carrier_id,
            period_start=PERIOD_LATE_START,
            period_end=T_2026_08_01,
            exchange_reference="EXG-2026-07-LATE",
        ),
        analyst_headers,
    )
    validate_error(touching, ERR_BATCH_PERIOD_OVERLAP, expected_status=409)

    repeat = api.create_reconciliation_case(
        reconciliation_case_payload(
            state["batch_id"],
            counterparty_reported_minutes=70.0000,
            counterparty_reported_amount_usd=31.00,
            exchange_reference=BATCH_EXCHANGE_REFERENCE_IN,
        ),
        controller_headers,
    )
    validate_error(repeat, ERR_DUPLICATE_RECONCILIATION_CASE, expected_status=409)

    _, batch_meta = validate_paginated(
        api.list_usage_batches(analyst_headers, params={"carrier_id": carrier_id})
    )
    assert batch_meta["total_count"] == 1, "the touching period bought no second batch"

    _, case_meta = validate_paginated(
        api.list_batch_reconciliation_cases(state["batch_id"], controller_headers)
    )
    assert case_meta["total_count"] == 1, "the repeat exchange reference wrote no case"


def test_missing_factor_filing_falls_back_to_the_default_tariff_factors(api):
    """With no filing on record the tariff defaults of 50.00 and 20.00 allocate the pool.

    PRD 3.7: "If there are no candidates, the tariff defaults apply: `factor_source` is set to `DEFAULT_TARIFF`, `traffic_factor_filing_id` stays null, the working interstate percentage is **50.00** and the working local percentage is **20.00**."
    PRD 3.7: "The allocated interstate minutes are `indeterminate_minutes` multiplied by the working interstate percentage and divided by one hundred, rounded half up to four decimal places; the allocated local minutes are `indeterminate_minutes` multiplied by the working local percentage and divided by one hundred, rounded half up to four decimal places; and the allocated intrastate minutes are `indeterminate_minutes` less the allocated interstate minutes less the allocated local minutes, with no rounding of their own — which is precisely why no rounding remainder is ever lost."
    PRD 3.7: "When the pinned filing sits in `REPORTED`, `ACCEPTED` or `DISPUTED`, or when no filing existed and the tariff defaults were used, the batch is `PRELIMINARY` — the interstate bucket is understated whenever a later audit raises the interstate percentage, and the batch remains eligible for the re-rate cascade of §3.6 that will move it to `FINAL` and post the delta to the invoice."

    Design: Corner/calculations/missing_factor_filing_falls_back_to_the_default_tariff_factors
    """
    state = setup_rated_batch(api, with_factor_filing=False)
    batch = state["batch"]

    assert batch["factor_source"] == "DEFAULT_TARIFF"
    assert batch["traffic_factor_filing_id"] is None

    assert_minutes(batch["interstate_minutes"], 33.5000, "interstate_minutes")
    assert_minutes(batch["intrastate_minutes"], 23.9000, "intrastate_minutes")
    assert_minutes(batch["local_minutes"], 15.6000, "local_minutes")
    assert_minutes(
        float(batch["interstate_minutes"])
        + float(batch["intrastate_minutes"])
        + float(batch["local_minutes"]),
        73.0000,
        "the three buckets re-summed",
    )

    assert_money(batch["interstate_amount_usd"], 17.17, "interstate_amount_usd")
    assert_money(batch["intrastate_amount_usd"], 11.65, "intrastate_amount_usd")
    assert_money(batch["local_amount_usd"], 0.95, "local_amount_usd")
    assert_money(batch["rated_amount_usd"], 29.77, "rated_amount_usd")
    assert round(float(batch["rated_amount_usd"]), 2) != RATED_TOTAL_PRELIMINARY, (
        "the default factors must not reproduce the carrier-reported total"
    )

    assert batch["rating_variant"] == "PRELIMINARY"
    assert batch["status"] == "RATED"


def _hour_long_local_cdr(**overrides):
    """One hour of local traffic: CPN present, both endpoints in the same state."""
    return local_cdr_payload(duration_seconds=3600, **overrides)


def test_all_signaling_batch_reports_signaling_only_and_pins_no_filing(api):
    """With nothing indeterminate the factor filing is never consulted or pinned.

    PRD 3.7: "If `indeterminate_minutes` is zero there is nothing to allocate: `factor_source` is set to `SIGNALING_ONLY`, `traffic_factor_filing_id` is set to null, and both working percentages are 0.00."
    PRD 3.7: "If they are the same and `same_local_calling_area` is true, the call is `LOCAL`."
    PRD 3.7: "When the pinned factor filing's `status` is `AUDITED`, the indeterminate minutes were allocated with audited percentages and the batch is `FINAL`."
    PRD 3.7: "**The batch total**, `rated_amount_usd`, is the exact sum of the three two-decimal subtotals and is never re-rounded."

    Design: Corner/calculations/all_signaling_batch_reports_signaling_only_and_pins_no_filing
    """
    state = setup_rated_batch(api, builders=(_hour_long_local_cdr,))
    batch = state["batch"]

    assert_minutes(batch["total_billable_minutes"], 60.0000, "total_billable_minutes")
    assert_minutes(
        batch["signaling_determined_minutes"], 60.0000, "signaling_determined_minutes"
    )
    assert_minutes(batch["indeterminate_minutes"], 0.0000, "indeterminate_minutes")

    assert batch["factor_source"] == "SIGNALING_ONLY"
    assert batch["traffic_factor_filing_id"] is None

    assert_minutes(batch["local_minutes"], 60.0000, "local_minutes")
    assert_minutes(batch["interstate_minutes"], 0.0000, "interstate_minutes")
    assert_minutes(batch["intrastate_minutes"], 0.0000, "intrastate_minutes")

    assert_money(batch["local_amount_usd"], 3.68, "local_amount_usd")
    assert_money(batch["rated_amount_usd"], 3.68, "rated_amount_usd")
    assert batch["rating_variant"] == "PRELIMINARY", (
        "no filing was pinned, so the audited variant cannot be claimed"
    )

    filing = read_factor_filing(api, state["factor_filing"]["id"])
    assert filing["status"] == "REPORTED", "rating must not touch the factor filing"


def test_partial_minutes_round_up_and_records_price_at_six_decimals(
    api, analyst_headers
):
    """Every part minute bills whole, and signaling charges keep six decimals.

    PRD 3.7: "On acceptance the record's `billable_minutes` is computed immediately as its `duration_seconds` divided by 60 and rounded **up** to a whole number, its `jurisdiction`, `jurisdiction_source` and `rated_amount_usd` are left null, and the batch's `record_count` and `total_billable_minutes` increase accordingly with the batch's `version` incrementing by 1."
    PRD 3.7: "**Per-record charges** are written for the signaling-determined records only: each such record's `rated_amount_usd` is its `billable_minutes` multiplied by the rate for its own `jurisdiction`, rounded half up to six decimal places."
    PRD 3.7: "Records whose `jurisdiction_source` is `FACTOR_ALLOCATED` keep `rated_amount_usd` null, because their charge is only defined at the batch bucket level."
    PRD 3.7: "A record whose `signaling_cpn_present` is false, or whose `originating_state_code` is null, cannot be placed from its own signaling: its `jurisdiction` becomes `INDETERMINATE` and its `jurisdiction_source` becomes `FACTOR_ALLOCATED`."

    Design: Corner/calculations/partial_minutes_round_up_and_records_price_at_six_decimals
    """
    state = setup_rated_batch(api)

    rows, meta = validate_paginated(
        api.list_batch_call_detail_records(state["batch_id"], analyst_headers)
    )
    assert meta["total_count"] == 6
    assert_created_at_ascending(rows, "call detail records")

    assert [row["billable_minutes"] for row in rows] == [3, 2, 5, 2, 60, 1]
    assert sum(row["billable_minutes"] for row in rows) == 73

    interstate_record = rows[1]
    assert interstate_record["duration_seconds"] == 61
    assert interstate_record["billable_minutes"] == 2
    assert interstate_record["jurisdiction"] == "INTERSTATE"
    assert interstate_record["jurisdiction_source"] == "SIGNALING"
    assert_rate(interstate_record["rated_amount_usd"], 1.025000, "rated_amount_usd")
    assert float(interstate_record["rated_amount_usd"]) != 1.03, (
        "the per-record charge is held at six decimals, not rounded to 1.03"
    )

    indeterminate_record = rows[3]
    assert indeterminate_record["duration_seconds"] == 120
    assert indeterminate_record["signaling_cpn_present"] is False
    assert indeterminate_record["jurisdiction"] == "INDETERMINATE"
    assert indeterminate_record["jurisdiction_source"] == "FACTOR_ALLOCATED"
    assert indeterminate_record["rated_amount_usd"] is None

    batch = read_usage_batch(api, state["batch_id"])
    assert_minutes(
        batch["signaling_determined_minutes"], 10.0000, "signaling_determined_minutes"
    )
    assert_minutes(batch["indeterminate_minutes"], 63.0000, "indeterminate_minutes")


def test_access_charge_subtotals_round_each_leg_before_summing(api, analyst_headers):
    """Each jurisdiction rounds its signaling leg and its factor leg separately.

    PRD 3.7: "**Per-jurisdiction subtotals** are then formed for interstate, intrastate and local, and the two legs of each subtotal are rounded **separately before being added**: the signaling leg is the sum of `rated_amount_usd` over the signaling-determined records of that jurisdiction, rounded half up to two decimal places; the factor leg is that jurisdiction's allocated minutes multiplied by that jurisdiction's rate, rounded half up to two decimal places; and the subtotal is the sum of those two already-rounded figures."
    PRD 3.7: "Those three subtotals become the batch's `interstate_amount_usd`, `intrastate_amount_usd` and `local_amount_usd`."
    PRD 3.7: "**Rating** is likewise run by an `AccessBillingAnalyst` and moves the batch `JURISDICTIONALIZED → RATED`."

    Design: Difficulty/combinatorial_formula/access_charge_subtotals_round_each_leg_before_summing
    """
    state = setup_jurisdictionalized_batch(api)
    assert state["batch"]["status"] == "JURISDICTIONALIZED"

    response = api.rate_batch(state["batch_id"], {}, analyst_headers)
    batch = validate_success(response, expected_status=200)

    assert_money(
        batch["intrastate_amount_usd"],
        RATED_INTRASTATE_PRELIMINARY,
        "intrastate_amount_usd",
    )
    assert round(float(batch["intrastate_amount_usd"]), 2) != 14.72, (
        "summing the two intrastate legs before rounding would understate by a cent"
    )
    assert_money(
        batch["interstate_amount_usd"],
        RATED_INTERSTATE_PRELIMINARY,
        "interstate_amount_usd",
    )
    assert_money(batch["local_amount_usd"], RATED_LOCAL_PRELIMINARY, "local_amount_usd")

    assert batch["status"] == "RATED"
    assert batch["rating_variant"] == "PRELIMINARY"


def test_rated_batch_total_is_the_untouched_sum_of_its_three_subtotals(
    api, analyst_headers
):
    """The batch total is the plain sum of the three subtotals and is never re-rounded.

    PRD 3.7: "**The batch total**, `rated_amount_usd`, is the exact sum of the three two-decimal subtotals and is never re-rounded."
    PRD 3.7: "**Per-record charges** are written for the signaling-determined records only: each such record's `rated_amount_usd` is its `billable_minutes` multiplied by the rate for its own `jurisdiction`, rounded half up to six decimal places."
    PRD 3.7: "The batch's `rated_at` is stamped from the logical clock and its `version` increments by 1."

    Design: Difficulty/combinatorial_formula/access_charge_subtotals_round_each_leg_before_summing
    """
    state = setup_jurisdictionalized_batch(api)
    batch = validate_success(
        api.rate_batch(state["batch_id"], {}, analyst_headers), expected_status=200
    )

    subtotal_sum = (
        round(float(batch["interstate_amount_usd"]), 2)
        + round(float(batch["intrastate_amount_usd"]), 2)
        + round(float(batch["local_amount_usd"]), 2)
    )
    assert_money(batch["rated_amount_usd"], subtotal_sum, "rated_amount_usd")
    assert_money(batch["rated_amount_usd"], RATED_TOTAL_PRELIMINARY, "rated_amount_usd")
    assert round(float(batch["rated_amount_usd"]), 2) != 34.28, (
        "34.28 is the audited-factor total, not the carrier-reported one"
    )
    assert batch["rated_at"] == T_2026_09_01

    rows, _ = validate_paginated(
        api.list_batch_call_detail_records(state["batch_id"], analyst_headers)
    )
    assert_rate(rows[2]["rated_amount_usd"], 2.437500, "intrastate rated_amount_usd")
    assert rows[2]["billable_minutes"] == 5
    assert_rate(rows[1]["rated_amount_usd"], 1.025000, "interstate rated_amount_usd")
    assert rows[1]["billable_minutes"] == 2


def test_batch_rating_without_an_effective_local_rate_is_refused(api, analyst_headers):
    """A carried local bucket with its filing still FILED blocks the whole rating.

    PRD 3.7: "Every jurisdiction whose minute bucket is greater than zero must have such a filing; if any does not, rating is refused with `ERR_NO_EFFECTIVE_TARIFF_RATE`."
    PRD 3.7: "Rates come from the tariff rate book: for each jurisdiction, the rate is the `rate_per_mou_usd` of the tariff filing whose `status` is `EFFECTIVE`, whose `rate_element` is the one mapped to that jurisdiction — `INTERSTATE_SWITCHED_ACCESS` for interstate traffic, `INTRASTATE_SWITCHED_ACCESS` for intrastate traffic and `LOCAL_RECIPROCAL_COMP` for local traffic — and whose half-open window covers the batch's `period_start`, meaning the window's effective instant is at or before the period start and its expiry instant is strictly after it."
    PRD 3.7: "The batch's `interstate_minutes` is the sum of `billable_minutes` over `SIGNALING` records whose jurisdiction is `INTERSTATE` plus the allocated interstate minutes; `intrastate_minutes` is the signaling-derived intrastate sum plus the allocated intrastate residual; and `local_minutes` is the signaling-derived local sum plus the allocated local minutes."

    Design: Difficulty/cross_entity_state_dependency/batch_rating_requires_effective_tariff_for_every_carried_jurisdiction
    """
    state = setup_jurisdictionalized_batch(api, approve_local=False)
    assert state["filings"]["LOCAL_RECIPROCAL_COMP"]["status"] == "FILED"

    response = api.rate_batch(state["batch_id"], {}, analyst_headers)
    validate_error(response, ERR_NO_EFFECTIVE_TARIFF_RATE, expected_status=409)

    batch = read_usage_batch(api, state["batch_id"])
    assert batch["status"] == "JURISDICTIONALIZED"
    assert batch["rating_variant"] is None
    assert batch["rated_at"] is None
    assert_money(batch["rated_amount_usd"], 0.00, "rated_amount_usd")

    assert_minutes(batch["local_minutes"], 9.3000, "local_minutes")
    assert_minutes(batch["interstate_minutes"], 33.5000, "interstate_minutes")
    assert_minutes(batch["intrastate_minutes"], 30.2000, "intrastate_minutes")


def test_batch_rating_succeeds_once_the_local_tariff_is_approved(
    api, analyst_headers, regulator_headers
):
    """Approving the missing local filing unblocks exactly the refused rating.

    PRD 3.5: "Approval moves the filing `FILED → EFFECTIVE`."
    PRD 3.7: "Every jurisdiction whose minute bucket is greater than zero must have such a filing; if any does not, rating is refused with `ERR_NO_EFFECTIVE_TARIFF_RATE`."
    PRD 3.7: "Those three subtotals become the batch's `interstate_amount_usd`, `intrastate_amount_usd` and `local_amount_usd`."

    Design: Difficulty/cross_entity_state_dependency/batch_rating_requires_effective_tariff_for_every_carried_jurisdiction
    """
    state = setup_jurisdictionalized_batch(api, approve_local=False)
    local_filing = state["filings"]["LOCAL_RECIPROCAL_COMP"]
    validate_error(
        api.rate_batch(state["batch_id"], {}, analyst_headers),
        ERR_NO_EFFECTIVE_TARIFF_RATE,
        expected_status=409,
    )

    approved = validate_success(
        api.approve_tariff_filing(local_filing["id"], {}, regulator_headers),
        expected_status=200,
    )
    assert approved["status"] == "EFFECTIVE"
    assert_rate(approved["rate_per_mou_usd"], RATE_LOCAL, "rate_per_mou_usd")

    batch = validate_success(
        api.rate_batch(state["batch_id"], {}, analyst_headers), expected_status=200
    )
    assert batch["status"] == "RATED"
    assert_money(batch["rated_amount_usd"], RATED_TOTAL_PRELIMINARY, "rated_amount_usd")
    assert_money(batch["local_amount_usd"], RATED_LOCAL_PRELIMINARY, "local_amount_usd")
    assert_money(
        batch["interstate_amount_usd"],
        RATED_INTERSTATE_PRELIMINARY,
        "interstate_amount_usd",
    )
    assert_money(
        batch["intrastate_amount_usd"],
        RATED_INTRASTATE_PRELIMINARY,
        "intrastate_amount_usd",
    )
