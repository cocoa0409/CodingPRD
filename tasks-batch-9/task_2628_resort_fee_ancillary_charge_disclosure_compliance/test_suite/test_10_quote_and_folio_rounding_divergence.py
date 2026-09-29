"""The quote's per-night rounding order against the folio's stay aggregation."""
from test_helpers import (
    FOLIO_CHARGES_SUBTOTAL_CENTS,
    FOLIO_DESTINATION_AMOUNT_CENTS,
    FOLIO_DESTINATION_TAX_CENTS,
    FOLIO_FEE_TOTAL_CENTS,
    FOLIO_RESORT_AMOUNT_CENTS,
    FOLIO_RESORT_TAX_CENTS,
    FOLIO_ROOM_AMOUNT_CENTS,
    FOLIO_ROOM_TAX_CENTS,
    FOLIO_TAX_TOTAL_CENTS,
    FOLIO_TOTAL_CENTS,
    FOLIO_WIFI_AMOUNT_CENTS,
    FOLIO_WIFI_TAX_CENTS,
    OCCUPANCY_TAX_RATE_BPS,
    QUOTED_MANDATORY_FEE_CENTS,
    QUOTED_ROOM_TOTAL_CENTS,
    QUOTED_TAX_CENTS,
    QUOTED_TOTAL_CENTS,
    QUOTE_FOLIO_VARIANCE_CENTS,
    assert_folio_ledger_conservation,
    assert_folio_sequence_integrity,
    assert_quote_folio_variance,
    find_line_by_fee_code,
    find_line_by_sequence,
    setup_itemized_folio,
    setup_quoted_booking,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import AGENT


def test_quote_rounds_each_fee_per_night_before_multiplying_by_nights(api):
    """A quote accumulates rounded per-night fee values and then scales by nights.

    PRD 3.4: "Step two: `quoted_mandatory_fee_cents` is the mandatory-fee
    subtotal under the per-night rounding order. That subtotal walks the pinned
    program's `MANDATORY` fees in ascending `created_at` order; for every fee
    that is not `PER_STAY`, its unrounded per-night value against the booking's
    `room_rate_cents` and `guests` is rounded half up to whole cents and those
    rounded per-night values are accumulated; the accumulated per-night sum is
    then multiplied by `nights`; and finally each `PER_STAY` fee's
    `amount_cents` is added on top." The worked illustration pins the figures:
    "the per-night values round to 2243, 1495 and 650, summing to 4388, which
    multiplied by four nights gives a `quoted_mandatory_fee_cents` of 17552 ...
    the single rounding of 18003.0576 gives a `quoted_tax_cents` of 18003, and
    `quoted_total_cents` is 155155."

    Design: Difficulty/dual_variant_calc/booking_quote_per_night_rounding_versus_folio_stay_aggregation
    """
    env = setup_quoted_booking()

    booking = validate_success(api.get_booking(env["booking"]["id"], AGENT))

    assert booking["quoted_room_total_cents"] == QUOTED_ROOM_TOTAL_CENTS
    assert booking["quoted_mandatory_fee_cents"] == QUOTED_MANDATORY_FEE_CENTS
    assert booking["quoted_tax_cents"] == QUOTED_TAX_CENTS
    assert booking["quoted_total_cents"] == QUOTED_TOTAL_CENTS
    assert booking["quoted_total_cents"] == (
        QUOTED_ROOM_TOTAL_CENTS + QUOTED_MANDATORY_FEE_CENTS + QUOTED_TAX_CENTS
    )
    # Every folio-side figure is still untouched on a freshly quoted booking.
    assert booking["folio_fee_total_cents"] == 0
    assert booking["folio_total_cents"] == 0
    assert booking["quote_folio_variance_cents"] == 0
    assert booking["guest_out_of_pocket_cents"] == 0
    assert booking["stay_status"] == "QUOTED"
    assert booking["disclosure_status"] == "PENDING_AUDIT"


def test_folio_expands_each_fee_across_the_stay_and_rounds_once_at_the_end(api):
    """Itemisation bills the stay-aggregation variant, two cents under the quote.

    PRD 3.5: "Each fee line's amount is the **stay-aggregation variant**: the
    fee's unrounded whole-stay value against the booking's `room_rate_cents`,
    `guests` and `nights` is computed first and rounded half up **once**, at the
    end. This is the opposite order from the quote, which rounded per night
    before multiplying, and the divergence between the two is the entire source
    of the booking's `quote_folio_variance_cents`." The canonical folio pins it:
    "The mandatory-fee subtotal under stay aggregation is 17550 against the
    quote's 17552, `tax_total_cents` is 18002 against the quote's 18003, and
    `folio_total_cents` is 119600 plus 17550 plus 18002, that is 155152, giving
    a `quote_folio_variance_cents` of 155152 minus 155155, that is −3."

    Design: Difficulty/dual_variant_calc/booking_quote_per_night_rounding_versus_folio_stay_aggregation
    """
    env = setup_itemized_folio()

    folio = validate_success(api.get_folio(env["folio"]["id"], AGENT))
    booking = validate_success(api.get_booking(env["booking"]["id"], AGENT))
    lines, _meta = validate_paginated(
        api.list_folio_lines(AGENT, {"folio_id": folio["id"], "limit": 100})
    )

    assert folio["status"] == "ITEMIZED"
    assert folio["itemization_complete"] is True
    assert folio["line_count"] == 4
    assert folio["charges_subtotal_cents"] == FOLIO_CHARGES_SUBTOTAL_CENTS
    assert folio["credits_total_cents"] == 0
    assert folio["tax_total_cents"] == FOLIO_TAX_TOTAL_CENTS
    assert folio["folio_total_cents"] == FOLIO_TOTAL_CENTS

    assert booking["folio_fee_total_cents"] == FOLIO_FEE_TOTAL_CENTS
    assert booking["folio_fee_total_cents"] != QUOTED_MANDATORY_FEE_CENTS
    assert booking["folio_total_cents"] == FOLIO_TOTAL_CENTS
    assert booking["guest_out_of_pocket_cents"] == FOLIO_TOTAL_CENTS
    assert booking["quote_folio_variance_cents"] == QUOTE_FOLIO_VARIANCE_CENTS
    assert_quote_folio_variance(booking)
    # A three-cent variance is well inside the tolerance, so standing is intact.
    assert booking["disclosure_status"] == "PENDING_AUDIT"

    assert_folio_sequence_integrity(folio, lines)
    assert_folio_ledger_conservation(folio, lines)


def test_folio_mandatory_fee_lines_carry_the_stay_aggregated_amounts(api):
    """The three mandatory-fee lines bill 8970, 5980 and 2600, not the quote's.

    PRD 3.5: "Then one `MANDATORY_FEE` line per fee of the pinned program with
    classification `MANDATORY` **whose stay amount is strictly greater than
    0**, taken in ascending `Fee.created_at` order and numbered from 2 upward."
    The canonical folio pins the amounts: "the `ROOM` line is 119600 with tax
    16002; the percentage fee's stay amount rounds once from 8970.0 to 8970
    with tax 1200; the per-night fee is 5980 with tax 800; and the exempt
    per-person fee is 2600 with tax 0."

    Design: Difficulty/dual_variant_calc/booking_quote_per_night_rounding_versus_folio_stay_aggregation
    """
    env = setup_itemized_folio()

    fee_lines, _meta = validate_paginated(
        api.list_folio_lines(
            AGENT,
            {
                "folio_id": env["folio"]["id"],
                "line_type": "MANDATORY_FEE",
                "limit": 100,
            },
        )
    )

    assert len(fee_lines) == 3
    assert [line["amount_cents"] for line in fee_lines] == [
        FOLIO_RESORT_AMOUNT_CENTS,
        FOLIO_DESTINATION_AMOUNT_CENTS,
        FOLIO_WIFI_AMOUNT_CENTS,
    ]
    assert [line["sequence_no"] for line in fee_lines] == [2, 3, 4]
    assert sum(line["amount_cents"] for line in fee_lines) == FOLIO_FEE_TOTAL_CENTS

    all_lines, _all_meta = validate_paginated(
        api.list_folio_lines(AGENT, {"folio_id": env["folio"]["id"], "limit": 100})
    )
    room_line = find_line_by_sequence(all_lines, 1)
    assert room_line["line_type"] == "ROOM"
    assert room_line["amount_cents"] == FOLIO_ROOM_AMOUNT_CENTS
    assert room_line["fee_code"] is None
    assert room_line["fee_id"] is None


def test_folio_tax_is_summed_from_per_line_roundings_not_one_aggregate_rounding(api):
    """Four independently rounded line taxes sum to 18002, one short of 18003.

    PRD 3.5: "The line's `tax_cents` is then its own `amount_cents` times its
    own rate divided by 10000, **rounded half up per line**; the folio's
    `tax_total_cents` is the plain sum of those already-rounded per-line
    figures, never a single rounding over an aggregate base." PRD 3.4 pins the
    other order for the quote: "`quoted_tax_cents` is computed with exactly
    **one** rounding over the aggregate."

    Design: Difficulty/combinatorial_formula/folio_tax_rounded_per_line_versus_quote_tax_rounded_once
    """
    env = setup_itemized_folio()

    folio = validate_success(api.get_folio(env["folio"]["id"], AGENT))
    booking = validate_success(api.get_booking(env["booking"]["id"], AGENT))
    lines, _meta = validate_paginated(
        api.list_folio_lines(AGENT, {"folio_id": folio["id"], "limit": 100})
    )

    room_line = find_line_by_sequence(lines, 1)
    assert room_line["tax_rate_bps"] == OCCUPANCY_TAX_RATE_BPS
    assert room_line["tax_cents"] == FOLIO_ROOM_TAX_CENTS
    assert room_line["taxability_determination"] == "TAXABLE"

    resort_line = find_line_by_fee_code(lines, "RESORT")
    assert resort_line["amount_cents"] == FOLIO_RESORT_AMOUNT_CENTS
    assert resort_line["tax_rate_bps"] == OCCUPANCY_TAX_RATE_BPS
    assert resort_line["tax_cents"] == FOLIO_RESORT_TAX_CENTS

    destination_line = find_line_by_fee_code(lines, "DESTINATION")
    assert destination_line["amount_cents"] == FOLIO_DESTINATION_AMOUNT_CENTS
    assert destination_line["tax_rate_bps"] == OCCUPANCY_TAX_RATE_BPS
    assert destination_line["tax_cents"] == FOLIO_DESTINATION_TAX_CENTS

    wifi_line = find_line_by_fee_code(lines, "WIFI_PREMIUM")
    assert wifi_line["amount_cents"] == FOLIO_WIFI_AMOUNT_CENTS
    assert wifi_line["tax_rate_bps"] == 0
    assert wifi_line["tax_cents"] == FOLIO_WIFI_TAX_CENTS

    assert folio["tax_total_cents"] == sum(line["tax_cents"] for line in lines)
    assert folio["tax_total_cents"] == FOLIO_TAX_TOTAL_CENTS
    assert booking["quoted_tax_cents"] == QUOTED_TAX_CENTS
    assert folio["tax_total_cents"] != booking["quoted_tax_cents"]


def test_conditional_taxability_rule_resolves_per_line_at_itemisation(api):
    """Each line's determination comes from its own fee code's rule.

    PRD 3.5: "an `EXEMPT` rule gives determination `EXEMPT` and `tax_rate_bps`
    0; a `TAXABLE` rule gives determination `TAXABLE`; and a
    `TAXABLE_IF_MANDATORY` rule gives determination
    `TAXABLE_IF_MANDATORY_APPLIED`, because a line written at itemisation is by
    construction a mandatory charge."

    Design: Difficulty/combinatorial_formula/folio_tax_rounded_per_line_versus_quote_tax_rounded_once
    """
    env = setup_itemized_folio()

    lines, _meta = validate_paginated(
        api.list_folio_lines(AGENT, {"folio_id": env["folio"]["id"], "limit": 100})
    )

    assert (
        find_line_by_fee_code(lines, "RESORT")["taxability_determination"] == "TAXABLE"
    )
    assert (
        find_line_by_fee_code(lines, "DESTINATION")["taxability_determination"]
        == "TAXABLE_IF_MANDATORY_APPLIED"
    )
    assert find_line_by_fee_code(lines, "WIFI_PREMIUM")["taxability_determination"] == (
        "EXEMPT"
    )
    for line in lines:
        assert line["jurisdiction_id"] == env["jurisdiction"]["id"]
    # A booking whose channel attested nothing has failed to show every cent of
    # the per-night-rounded mandatory burden.
    booking = validate_success(api.get_booking(env["booking"]["id"], AGENT))
    assert booking["disclosed_fee_amounts"] == {}
    assert booking["quote_disclosure_gap_cents"] == QUOTED_MANDATORY_FEE_CENTS
