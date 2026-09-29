"""Quote arithmetic, the disclosure gap, the reference burden and the posture minimum."""
from test_helpers import (
    ARRIVAL_DATE,
    BASE_ROOM_RATE_CENTS,
    PUBLISHED_DESTINATION_PER_NIGHT_CENTS,
    PUBLISHED_RESORT_PER_NIGHT_CENTS,
    PUBLISHED_TOTAL_MANDATORY_FEE_CENTS_PER_NIGHT,
    PUBLISHED_WIFI_PER_NIGHT_CENTS,
    QUOTED_MANDATORY_FEE_CENTS,
    QUOTED_ROOM_TOTAL_CENTS,
    QUOTED_TAX_CENTS,
    QUOTED_TOTAL_CENTS,
    STAY_GUESTS,
    STAY_NIGHTS,
    add_booking,
    add_channel,
    add_draft_profile,
    create_booking_payload,
    deploy_profile,
    read_disclosure_summary,
    read_fee_program,
    read_profile,
    read_property,
    setup_deployed_profile,
    setup_program_under_review,
    setup_published_program,
    validate_success,
)
from test_helpers.fixtures import AGENT, COMPLIANCE

FOLIO_STYLE_TAX_TOTAL_CENTS = 18002
PARTIAL_DISCLOSURE_MAP = {"RESORT": 6000, "DESTINATION": 5980}
GAP_UNDER_PARTIAL_MAP = 5572
OVERSTATED_MAP = {"RESORT": 6000, "DESTINATION": 9000}
HONEST_MAP = {"RESORT": 8972, "DESTINATION": 5980, "WIFI_PREMIUM": 2600}
CHARGED_RESORT_STAY_CENTS = 8972
CHARGED_DESTINATION_STAY_CENTS = 5980
CHARGED_WIFI_STAY_CENTS = 2600
CAPABLE_GDS = {
    "name": "WorldGDS Terminal",
    "channel_type": "GDS",
    "supports_total_price_display": True,
    "supports_itemization": True,
}
SILENT_PROFILE = {
    "first_quote_shows_total": False,
    "itemized_at_first_quote": False,
    "disclosure_placement": "ABSENT",
}


def test_the_quote_rounds_tax_once_over_the_assembled_taxable_base(api):
    """18003 over an aggregate of 134552, never the folio's per-fee 18002.

    PRD 3.4: "Step four: `quoted_tax_cents` is computed with exactly **one**
    rounding over the aggregate ... when every contributing rate is the same, the
    whole base is multiplied by that single rate, divided by 10000, and rounded
    half up once." PRD 3.4 works it through: "the taxable base is 119600 plus
    8972 plus 5980, that is 134552, the single rounding of 18003.0576 gives a
    `quoted_tax_cents` of 18003, and `quoted_total_cents` is 155155."

    Design: Corner/calculations/booking_quote_taxes_the_aggregate_base_with_a_single_rounding
    """
    env = setup_deployed_profile()
    payload = create_booking_payload(
        env["property"]["id"],
        env["channel"]["id"],
        env["profile"]["id"],
        disclosed_fee_amounts=PARTIAL_DISCLOSURE_MAP,
    )

    quoted = validate_success(api.create_booking(payload, AGENT), 201)

    assert quoted["quoted_room_total_cents"] == QUOTED_ROOM_TOTAL_CENTS
    assert quoted["quoted_room_total_cents"] == BASE_ROOM_RATE_CENTS * STAY_NIGHTS
    # 2243 + 1495 + 650 rounded per night, then multiplied by the four nights.
    assert quoted["quoted_mandatory_fee_cents"] == QUOTED_MANDATORY_FEE_CENTS
    assert quoted["quoted_tax_cents"] == QUOTED_TAX_CENTS
    assert quoted["quoted_tax_cents"] != FOLIO_STYLE_TAX_TOTAL_CENTS
    assert quoted["quoted_total_cents"] == QUOTED_TOTAL_CENTS
    assert quoted["quoted_total_cents"] == (
        QUOTED_ROOM_TOTAL_CENTS + QUOTED_MANDATORY_FEE_CENTS + QUOTED_TAX_CENTS
    )

    assert quoted["stay_status"] == "QUOTED"
    assert quoted["disclosure_status"] == "PENDING_AUDIT"
    assert quoted["fee_program_id"] == env["program"]["id"]
    assert quoted["guests"] == STAY_GUESTS
    assert quoted["arrival_date"].startswith(ARRIVAL_DATE[:10])
    assert quoted["folio_fee_total_cents"] == 0
    assert quoted["folio_total_cents"] == 0
    assert quoted["quote_folio_variance_cents"] == 0
    assert quoted["guest_out_of_pocket_cents"] == 0


def test_over_disclosing_one_fee_never_offsets_another_fees_silence(api):
    """Each fee floors at zero, and an absent code is charged in full.

    PRD 3.4: "The gap contribution is the charged amount minus the shown amount
    when that difference is positive, and 0 otherwise: over-disclosure never
    produces a negative offset that could mask a different fee's
    under-disclosure. `quote_disclosure_gap_cents` is the sum of those
    contributions." PRD 3.4: "its shown amount is the value stored under its code
    in `disclosed_fee_amounts`, or 0 when the code is absent."

    Design: Corner/calculations/quote_disclosure_gap_floors_each_fee_at_zero_and_charges_absent_codes_in_full
    """
    env = setup_deployed_profile()

    overstated = add_booking(env, disclosed_fee_amounts=OVERSTATED_MAP)

    understated_resort = CHARGED_RESORT_STAY_CENTS - OVERSTATED_MAP["RESORT"]
    assert understated_resort == 2972
    assert overstated["quote_disclosure_gap_cents"] == GAP_UNDER_PARTIAL_MAP
    assert overstated["quote_disclosure_gap_cents"] == (
        understated_resort + 0 + CHARGED_WIFI_STAY_CENTS
    )
    # A difference of totals would have reported 2572 by netting the overstatement.
    assert overstated["quote_disclosure_gap_cents"] != (
        QUOTED_MANDATORY_FEE_CENTS
        - OVERSTATED_MAP["RESORT"]
        - OVERSTATED_MAP["DESTINATION"]
    )
    # What is measured as undisclosed never changes what is charged.
    assert overstated["quoted_mandatory_fee_cents"] == QUOTED_MANDATORY_FEE_CENTS

    honest = add_booking(env, disclosed_fee_amounts=HONEST_MAP)
    assert honest["quote_disclosure_gap_cents"] == 0
    assert honest["quoted_mandatory_fee_cents"] == QUOTED_MANDATORY_FEE_CENTS

    silent = add_booking(env)
    assert silent["disclosed_fee_amounts"] == {}
    assert silent["quote_disclosure_gap_cents"] == (
        CHARGED_RESORT_STAY_CENTS
        + CHARGED_DESTINATION_STAY_CENTS
        + CHARGED_WIFI_STAY_CENTS
    )
    assert silent["quote_disclosure_gap_cents"] == QUOTED_MANDATORY_FEE_CENTS

    # Every booking is still PENDING_AUDIT, so none of it aggregates yet.
    assert read_property(env["property"]["id"])["aggregate_disclosure_gap_cents"] == 0


def test_the_reference_burden_rounds_every_fee_before_it_sums_them(api):
    """4388 from 2243 plus 1495 plus 650, against the property's own room rate.

    PRD 3.2: "`total_mandatory_fee_cents_per_night` becomes a reference per-night
    mandatory burden, computed against the *property's* `base_room_rate_cents`
    rather than any booking's rate, at a reference occupancy of two guests and
    over a reference stay of four nights, walking the mandatory fees in ascending
    `created_at` order and using the per-night rounding order: a `PER_STAY` fee
    contributes its `amount_cents` divided by the four reference nights and
    rounded half up to whole cents, and every other fee contributes its unrounded
    per-night value rounded half up to whole cents; those rounded contributions
    are then summed."

    Design: Corner/calculations/publication_rollup_applies_the_reference_guest_and_night_constants
    """
    env = setup_program_under_review()
    before = read_fee_program(env["program"]["id"])

    assert env["property"]["base_room_rate_cents"] == BASE_ROOM_RATE_CENTS
    assert env["property"]["disclosure_posture"] == "COMPLIANT"
    assert before["fee_count"] == 3
    assert before["mandatory_fee_count"] == 3
    assert before["total_mandatory_fee_cents_per_night"] == 0
    assert float(before["inclusion_coverage_ratio"]) == 0.0

    published = validate_success(
        api.publish_fee_program(
            env["program"]["id"],
            "Three mandatory fees; inclusion analysis complete.",
            COMPLIANCE,
        )
    )

    assert published["total_mandatory_fee_cents_per_night"] == (
        PUBLISHED_TOTAL_MANDATORY_FEE_CENTS_PER_NIGHT
    )
    assert published["total_mandatory_fee_cents_per_night"] == (
        PUBLISHED_RESORT_PER_NIGHT_CENTS
        + PUBLISHED_DESTINATION_PER_NIGHT_CENTS
        + PUBLISHED_WIFI_PER_NIGHT_CENTS
    )
    # 2242.5 is carried half up per fee before the sum, so the total is not a
    # single rounding of an aggregated 4387.5.
    assert PUBLISHED_RESORT_PER_NIGHT_CENTS == 2243
    # The per-person term uses the reference occupancy, not any booking's guests.
    assert PUBLISHED_WIFI_PER_NIGHT_CENTS == 325 * 2
    assert published["mandatory_fee_count"] == 3
    assert float(published["inclusion_coverage_ratio"]) == 1.0

    prop = read_property(env["property"]["id"])
    assert prop["published_fee_program_count"] == 1
    summary = read_disclosure_summary(env["property"]["id"])
    assert summary["total_mandatory_fee_cents_per_night"] == (
        PUBLISHED_TOTAL_MANDATORY_FEE_CENTS_PER_NIGHT
    )


def test_a_draft_path_never_drags_the_property_minimum_down(api):
    """An empty candidate set reads null, and a drafted path stays outside it.

    PRD 3.3: "The candidate set for a property's posture is every one of its
    profiles whose status is `DEPLOYED`, `FLAGGED` or `REMEDIATED`. Profiles in
    `DRAFT` or `RETIRED` are excluded entirely, which is why a draft path scoring
    0 does not drag a property down ... The property's
    `min_channel_disclosure_score` is the minimum of those effective scores. When
    the candidate set is empty the minimum is null and the posture is
    `COMPLIANT`."

    Design: Corner/calculations/posture_excludes_draft_profiles_from_the_minimum_score
    """
    env = setup_published_program()
    gds = add_channel(env, "gds_channel", **CAPABLE_GDS)
    low = add_draft_profile(env, channel=gds, **SILENT_PROFILE)
    full = add_draft_profile(env)

    assert low["status"] == "DRAFT"
    assert low["disclosure_score"] == 10
    assert full["status"] == "DRAFT"
    assert full["disclosure_score"] == 100

    empty_set = read_property(env["property"]["id"])
    assert empty_set["min_channel_disclosure_score"] is None
    assert empty_set["disclosure_posture"] == "COMPLIANT"
    assert empty_set["open_disclosure_obligation_count"] == 0

    deployed = deploy_profile(env, profile=full)
    assert deployed["status"] == "DEPLOYED"

    after = read_property(env["property"]["id"])
    assert after["min_channel_disclosure_score"] == 100
    assert after["disclosure_posture"] == "COMPLIANT"
    assert after["open_disclosure_obligation_count"] == 0

    # Exclusion from the posture does not zero the drafted path's own score.
    still_drafted = read_profile(low["id"])
    assert still_drafted["status"] == "DRAFT"
    assert still_drafted["disclosure_score"] == 10
    assert read_disclosure_summary(env["property"]["id"])["deployed_profile_count"] == 1
