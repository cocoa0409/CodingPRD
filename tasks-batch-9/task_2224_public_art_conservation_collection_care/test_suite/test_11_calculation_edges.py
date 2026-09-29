"""Arithmetic edges of the four scored quantities of the conservation register.

The condition index and its exposure penalty, the treatment priority score and
its deferral multiplier, the authorised draw of an endowment or a set-aside
pool, and the gross and settled figures of an insurance claim.  Every expected
literal below is re-derived from the formula the PRD states, with the derivation
chain written out beside the assertion.
"""

from test_helpers import validate_success
from test_helpers.assertions import (
    assert_condition_assessment,
    assert_condition_index_precision,
    assert_damage_incident,
    assert_funding_pool,
    assert_priority_score_precision,
)
from test_helpers.fixtures import (
    create_pool,
    read_artwork,
    read_pool,
    set_clock,
    setup_assessment_submitted,
    setup_incident_triaged,
    setup_register,
)
from test_helpers.test_users import TEST_USERS

COASTAL_SITE = {
    "site_code": "SEA-1",
    "name": "Harbor Walk",
    "address_ref": "9 Harbor Walk",
    "exposure_class": "COASTAL",
}
MURAL_WORK = {
    "accession_number": "2024.020",
    "title": "Harbor Mural",
    "material_class": "MURAL_COATING",
    "significance_tier": "STANDARD",
    "footprint_units": 4,
    "insured_value_cents": 2_000_000,
    "acquisition_date": "2019-05-01",
    "acquisition_document_ref": "DEED-2019-020",
}


def test_coastal_mural_index_halves_the_exposure_penalty(api):
    """PRD §3.2: "Each of the five subscores is multiplied by a weight chosen by the work's `material_class`, and the five products are summed into a weighted defect figure that ranges from 0.0 for a pristine work to 4.0 for a work failed on every axis."
    PRD §3.2: "That figure is multiplied by a severity factor which is 1.0 when the largest of the five subscores is exactly 4, and 0.5 otherwise — so the exposure penalty doubles the moment any single axis has failed outright."
    PRD §3.2: "The index is then 100, less 25 times the weighted defect figure, less the penalty, rounded half up to one decimal place and finally floored at 0.0."
    PRD §3.2: "The penalty is subtracted after the weighted defect term and is never folded into it."
    PRD §3.9: "The **exposure factor**, read from the `exposure_class` of the site the work occupies, is 1.3 for `COASTAL`, 1.25 for `URBAN`, 1.1 for `PARK` and 1.0 for `INTERIOR`."

    Design: Corner/calculations/condition_index_uses_material_weights_exposure_penalty_and_severity_doubling
    """
    register = setup_register(api, site=COASTAL_SITE, artwork=MURAL_WORK)
    survey = setup_assessment_submitted(
        api,
        register["artwork"]["id"],
        surface_score=3,
        structural_score=1,
        coating_score=3,
        mount_score=1,
        graffiti_score=2,
    )

    finalized = validate_success(
        api.finalize_condition_assessment(
            survey["id"], {}, TEST_USERS["chief_conservator_headers"]
        )
    )

    assert_condition_assessment(finalized)
    # MURAL_COATING weights on (3, 1, 3, 1, 2):
    #   0.35*3 + 0.10*1 + 0.30*3 + 0.05*1 + 0.20*2 = 1.05+0.10+0.90+0.05+0.40 = 2.50.
    # Largest subscore is 3, not 4, so the COASTAL penalty 6.0 is halved to 3.0.
    #   100 - 25*2.50 - 3.0 = 100 - 62.5 - 3.0 = 34.5
    # Folding a doubled penalty in would give 31.5, which the response must not show.
    assert finalized["condition_index"] == 34.5
    assert finalized["condition_index"] != 31.5
    assert_condition_index_precision(finalized["condition_index"])
    # 30.0 <= 34.5 < 55.0 puts the survey in the PRIORITY band.
    assert finalized["recommendation"] == "PRIORITY"
    assert finalized["status"] == "FINALIZED"

    artwork = read_artwork(api, register["artwork"]["id"])
    assert artwork["condition_index"] == 34.5
    # deficit 100 - 34.5 = 65.5; STANDARD 1.0; COASTAL 1.3; deferral pinned to 1.0:
    #   65.5 * 1.0 * 1.3 * 1.0 = 85.15
    assert artwork["treatment_priority_score"] == 85.15
    assert_priority_score_precision(artwork["treatment_priority_score"])
    assert artwork["priority_basis"] == "SINGLE_ASSESSMENT"
    # 34.5 is below the 55.0 treatment trigger, so the work joins the cohort.
    assert artwork["conservation_status"] == "TREATMENT_REQUIRED"
    assert artwork["treatment_priority_rank"] == 1


def test_failed_axis_doubles_the_urban_penalty_and_rounds_the_index_half_up(api):
    """PRD §3.2: "That figure is multiplied by a severity factor which is 1.0 when the largest of the five subscores is exactly 4, and 0.5 otherwise — so the exposure penalty doubles the moment any single axis has failed outright."
    PRD §3.2: "An environmental penalty is then computed separately, from the `exposure_class` of the site the work currently occupies: 6.0 for `COASTAL`, 3.0 for `URBAN`, 1.5 for `PARK` and 0.0 for `INTERIOR`."
    PRD §3.2: "The index sorts the survey into a `recommendation` band: `NONE` when the index is 75.0 or above, `ROUTINE` when it is at least 55.0 but below 75.0, `PRIORITY` when it is at least 30.0 but below 55.0, and `URGENT` when it is below 30.0."
    PRD §3.9: "The **significance factor** is 1.5 for a `LANDMARK` work, 1.2 for a `SIGNIFICANT` one and 1.0 for a `STANDARD` one."

    Design: Corner/calculations/condition_index_uses_material_weights_exposure_penalty_and_severity_doubling
    """
    register = setup_register(api)
    survey = setup_assessment_submitted(
        api,
        register["artwork"]["id"],
        surface_score=4,
        structural_score=4,
        coating_score=4,
        mount_score=3,
        graffiti_score=4,
    )

    finalized = validate_success(
        api.finalize_condition_assessment(
            survey["id"], {}, TEST_USERS["chief_conservator_headers"]
        )
    )

    # BRONZE weights on (4, 4, 4, 3, 4):
    #   0.30*4 + 0.25*4 + 0.20*4 + 0.15*3 + 0.10*4 = 1.20+1.00+0.80+0.45+0.40 = 3.85.
    # One axis is exactly 4, so the URBAN penalty 3.0 is taken whole, not halved.
    #   100 - 25*3.85 - 3.0 = 100 - 96.25 - 3.0 = 0.75, half up to one place = 0.8
    assert finalized["condition_index"] == 0.8
    assert_condition_index_precision(finalized["condition_index"])
    # 0.8 is below 30.0, the URGENT band.
    assert finalized["recommendation"] == "URGENT"

    artwork = read_artwork(api, register["artwork"]["id"])
    assert artwork["condition_index"] == 0.8
    # deficit 100 - 0.8 = 99.2; LANDMARK 1.5; URBAN 1.25; deferral pinned to 1.0:
    #   99.2 * 1.5 * 1.25 * 1.0 = 186.00
    assert artwork["treatment_priority_score"] == 186.00
    assert_priority_score_precision(artwork["treatment_priority_score"])
    assert artwork["priority_basis"] == "SINGLE_ASSESSMENT"
    assert artwork["conservation_status"] == "TREATMENT_REQUIRED"


def test_cycle_cohort_deferral_grows_the_score_one_day_below_the_cap(api):
    """PRD §3.9: "The **deferral factor** starts at 1 and grows by 0.004 for each whole day between the source survey's `assessed_on` date and the logical clock's date, a count that is never negative, and is capped at 1.60 — a ceiling reached after 150 days of deferral, beyond which further delay no longer improves a work's standing in the queue."
    PRD §3.9: "Under the **single-assessment** variant, which runs as Cascade A hop 2 when a survey is finalized, the source is that very survey and the deferral day count is pinned to zero, so the deferral factor is exactly 1.0 and the score is the undeferred product; the work's `priority_basis` is set to `SINGLE_ASSESSMENT`."
    PRD §3.9: "It rescores every work holding at least one finalized survey in that cycle year under the cycle-cohort variant, sets each such work's `priority_basis` to `CYCLE_COHORT` and recomputes cohort ranks."
    PRD §3.9: "The checkpoint reports what it did, echoing the `cycle_year` it ran for alongside `artworks_rescored`, `consultations_lapsed`, `notices_elapsed` and `artworks_returned_to_monitored`."

    Design: Corner/calculations/deferral_multiplier_saturates_at_the_cap
    """
    set_clock(api, "2026-07-31T00:00:00Z")
    register = setup_register(api)
    survey = setup_assessment_submitted(
        api,
        register["artwork"]["id"],
        cycle_year=2026,
        assessed_on="2026-03-04",
        surface_score=2,
        structural_score=2,
        coating_score=2,
        mount_score=2,
        graffiti_score=1,
    )

    finalized = validate_success(
        api.finalize_condition_assessment(
            survey["id"], {}, TEST_USERS["chief_conservator_headers"]
        )
    )
    # BRONZE weights on (2, 2, 2, 2, 1): 0.60+0.50+0.40+0.30+0.10 = 1.90; largest
    # subscore is 2 so the URBAN penalty halves to 1.5;
    #   100 - 25*1.90 - 1.5 = 100 - 47.5 - 1.5 = 51.0
    assert finalized["condition_index"] == 51.0

    artwork = read_artwork(api, register["artwork"]["id"])
    # deficit 49.0; LANDMARK 1.5; URBAN 1.25; deferral pinned to 1.0 on finalization:
    #   49.0 * 1.5 * 1.25 * 1.0 = 91.875, half up to two places = 91.88
    assert artwork["treatment_priority_score"] == 91.88
    assert artwork["priority_basis"] == "SINGLE_ASSESSMENT"

    report = validate_success(
        api.run_cycle({"cycle_year": 2026}, TEST_USERS["manager_headers"])
    )
    assert report["cycle_year"] == 2026
    assert report["artworks_rescored"] == 1
    assert report["consultations_lapsed"] == 0
    assert report["notices_elapsed"] == 0
    assert report["artworks_returned_to_monitored"] == 0

    rescored = read_artwork(api, register["artwork"]["id"])
    # 2026-03-04 to the clock date 2026-07-31 is 149 whole days, one short of the
    # 150-day ceiling: deferral 1 + 0.004*149 = 1.596;
    #   49.0 * 1.5 * 1.25 * 1.596 = 91.875 * 1.596 = 146.6325, half up = 146.63
    assert rescored["treatment_priority_score"] == 146.63
    assert_priority_score_precision(rescored["treatment_priority_score"])
    assert rescored["priority_basis"] == "CYCLE_COHORT"


def test_deferral_multiplier_clamps_at_one_point_six_after_one_hundred_fifty_days(api):
    """PRD §3.9: "The **deferral factor** starts at 1 and grows by 0.004 for each whole day between the source survey's `assessed_on` date and the logical clock's date, a count that is never negative, and is capped at 1.60 — a ceiling reached after 150 days of deferral, beyond which further delay no longer improves a work's standing in the queue."
    PRD §3.9: "The score is the product of all four factors, rounded half up to two decimal places, with that rounding applied once to the final product and never to an intermediate factor."
    PRD §3.9: "Under the **cycle-cohort** variant, which runs at the cycle checkpoint, the source is the *earliest* finalized survey of the named cycle year for that work — ordered by `assessed_on` ascending and, where two surveys share a date, by `created_at` ascending — and the deferral day count is measured from that survey's `assessed_on` to the logical clock; the work's `priority_basis` is set to `CYCLE_COHORT`."

    Design: Corner/calculations/deferral_multiplier_saturates_at_the_cap
    """
    register = setup_register(api)
    survey = setup_assessment_submitted(
        api,
        register["artwork"]["id"],
        cycle_year=2026,
        assessed_on="2026-03-04",
        surface_score=2,
        structural_score=2,
        coating_score=2,
        mount_score=2,
        graffiti_score=1,
    )
    validate_success(
        api.finalize_condition_assessment(
            survey["id"], {}, TEST_USERS["chief_conservator_headers"]
        )
    )

    at_cap = validate_success(
        api.run_cycle({"cycle_year": 2026}, TEST_USERS["manager_headers"])
    )
    assert at_cap["artworks_rescored"] == 1

    artwork = read_artwork(api, register["artwork"]["id"])
    # The clock sits at its default 2026-08-01, exactly 150 days after 2026-03-04,
    # so the multiplier reaches its ceiling: 1 + 0.004*150 = 1.600;
    #   deficit 49.0 * 1.5 (LANDMARK) * 1.25 (URBAN) * 1.600 = 147.0000 -> 147.00
    assert artwork["treatment_priority_score"] == 147.00
    assert_priority_score_precision(artwork["treatment_priority_score"])
    assert artwork["priority_basis"] == "CYCLE_COHORT"

    set_clock(api, "2026-09-20T00:00:00Z")
    beyond_cap = validate_success(
        api.run_cycle({"cycle_year": 2026}, TEST_USERS["manager_headers"])
    )
    assert beyond_cap["artworks_rescored"] == 1

    clamped = read_artwork(api, register["artwork"]["id"])
    # 2026-03-04 to 2026-09-20 is 200 days: the uncapped factor would be
    # 1 + 0.004*200 = 1.80 and the score 91.875 * 1.80 = 165.38, but the factor is
    # clamped at 1.60, so the score stands still at 91.875 * 1.600 = 147.00.
    assert clamped["treatment_priority_score"] == 147.00
    assert clamped["treatment_priority_score"] != 165.38


def test_percent_for_art_set_aside_authorizes_in_full_with_no_admin_fee(api):
    """PRD §3.10: "For a `PERCENT_FOR_ART` pool the amount authorised before fees is simply the `set_aside_cents`, and `admin_fee_cents` is zero — set-asides carry no administrative charge."
    PRD §3.10: "`draw_authorized_cents` is the pre-fee authorised amount less `admin_fee_cents`."
    PRD §3.10: "A pool's `available_cents` is then its `draw_authorized_cents`, plus its `recovery_credits_cents` — the running total of insurance settlements credited back to it, which begins at zero — less the total `amount_cents` of the pool's allocations sitting in `RESERVED`, `COMMITTED` or `DISBURSED`."
    PRD §3.10: "The administrative fee is then 2.25 percent of that pre-fee authorised amount, rounded half up to a whole cent, and recorded as `admin_fee_cents`."

    Design: Corner/calculations/percent_for_art_pool_authorizes_the_set_aside_with_no_admin_fee
    """
    set_aside = validate_success(
        api.create_funding_pool(
            {
                "pool_code": "PFA-2026",
                "pool_type": "PERCENT_FOR_ART",
                "fiscal_year": 2026,
                "set_aside_cents": 5_000_000,
            },
            TEST_USERS["finance_headers"],
        ),
        201,
    )
    endowment = validate_success(
        api.create_funding_pool(
            {
                "pool_code": "END-5M",
                "pool_type": "ENDOWMENT",
                "fiscal_year": 2026,
                "principal_cents": 100_000_000,
                "draw_rate_bps": 500,
            },
            TEST_USERS["finance_headers"],
        ),
        201,
    )

    assert_funding_pool(set_aside)
    # A set-aside of 5000000 is authorised before fees at 5000000, carries no
    # administrative charge, so draw_authorized_cents = 5000000 - 0 = 5000000 and
    # available_cents = 5000000 + 0 recovery credits - 0 encumbered = 5000000.
    assert set_aside["admin_fee_cents"] == 0
    assert set_aside["draw_authorized_cents"] == 5_000_000
    assert set_aside["available_cents"] == 5_000_000
    assert set_aside["recovery_credits_cents"] == 0
    # An endowment carries neither set-aside inputs; both default to zero.
    assert set_aside["principal_cents"] == 0
    assert set_aside["draw_rate_bps"] == 0

    assert_funding_pool(endowment)
    # The same gross figure through the endowment pipeline: gross draw
    # 100000000 * 500 / 10000 = 5000000, which is at the 5000000 floor and so takes
    # the 75 bps supplement 100000000 * 75 / 10000 = 750000, giving 5750000 before
    # fees; the fee is 5750000 * 0.0225 = 129375 exactly, so the authorised draw is
    # 5750000 - 129375 = 5620625 — a fee the set-aside branch never pays.
    assert endowment["admin_fee_cents"] == 129_375
    assert endowment["draw_authorized_cents"] == 5_620_625
    assert endowment["available_cents"] == 5_620_625
    assert endowment["recovery_credits_cents"] == 0


def test_gross_draw_five_cents_below_the_tier_floor_takes_no_supplement(api):
    """PRD §3.10: "For an `ENDOWMENT` pool the gross draw is the `principal_cents` multiplied by the `draw_rate_bps` and divided by 10,000, rounded half up to a whole cent."
    PRD §3.10: "That gross figure then selects a supplemental tier: no supplement at all when the gross draw is below 5,000,000 cents (50,000 dollars); a supplement of 75 basis points when the gross draw is at least 5,000,000 cents but below 20,000,000 cents (200,000 dollars); and a supplement of 125 basis points when the gross draw is 20,000,000 cents or more."
    PRD §3.10: "The administrative fee is then 2.25 percent of that pre-fee authorised amount, rounded half up to a whole cent, and recorded as `admin_fee_cents`."
    PRD §3.10: "Tier selection is pinned to the **gross, pre-fee** draw."

    Design: Corner/calculations/endowment_tier_floor_is_inclusive_and_keyed_on_the_gross_draw
    """
    below_floor = validate_success(
        api.create_funding_pool(
            {
                "pool_code": "END-BELOW",
                "pool_type": "ENDOWMENT",
                "fiscal_year": 2026,
                "principal_cents": 99_999_900,
                "draw_rate_bps": 500,
            },
            TEST_USERS["finance_headers"],
        ),
        201,
    )
    at_floor = validate_success(
        api.create_funding_pool(
            {
                "pool_code": "END-AT1",
                "pool_type": "ENDOWMENT",
                "fiscal_year": 2026,
                "principal_cents": 100_000_000,
                "draw_rate_bps": 500,
            },
            TEST_USERS["finance_headers"],
        ),
        201,
    )

    # Gross draw 99999900 * 500 / 10000 = 4999995, five cents below the 5000000
    # floor, so no supplement applies and the pre-fee amount stays 4999995; the fee
    # is 4999995 * 0.0225 = 112499.8875, half up to 112500, leaving
    #   4999995 - 112500 = 4887495
    assert below_floor["admin_fee_cents"] == 112_500
    assert below_floor["draw_authorized_cents"] == 4_887_495
    assert below_floor["available_cents"] == 4_887_495

    # Gross draw 100000000 * 500 / 10000 = 5000000 lands exactly on the inclusive
    # floor: supplement 100000000 * 75 / 10000 = 750000, pre-fee 5750000, fee
    # 5750000 * 0.0225 = 129375, authorised 5750000 - 129375 = 5620625.
    assert at_floor["admin_fee_cents"] == 129_375
    assert at_floor["draw_authorized_cents"] == 5_620_625
    assert at_floor["available_cents"] == 5_620_625
    # Five cents of gross moves the authorised draw by 5620625 - 4887495 = 733130.
    assert at_floor["draw_authorized_cents"] - below_floor["draw_authorized_cents"] == 733_130


def test_gross_draw_exactly_at_the_upper_floor_takes_the_125_basis_point_tier(api):
    """PRD §3.10: "Tier floors are inclusive, so a gross draw of exactly 20,000,000 cents selects the 125-basis-point tier."
    PRD §3.10: "The supplemental amount is the `principal_cents` multiplied by the selected tier's basis points and divided by 10,000, rounded half up to a whole cent, and the amount authorised before fees is the gross draw plus that supplement."
    PRD §3.10: "`draw_authorized_cents` is the pre-fee authorised amount less `admin_fee_cents`."

    Design: Corner/calculations/endowment_tier_floor_is_inclusive_and_keyed_on_the_gross_draw
    """
    at_upper_floor = validate_success(
        api.create_funding_pool(
            {
                "pool_code": "END-AT2",
                "pool_type": "ENDOWMENT",
                "fiscal_year": 2026,
                "principal_cents": 400_000_000,
                "draw_rate_bps": 500,
            },
            TEST_USERS["finance_headers"],
        ),
        201,
    )

    assert_funding_pool(at_upper_floor)
    # Gross draw 400000000 * 500 / 10000 = 20000000, exactly the upper floor, so the
    # 125 bps tier applies: supplement 400000000 * 125 / 10000 = 5000000, pre-fee
    # 25000000, fee 25000000 * 0.0225 = 562500, authorised 25000000 - 562500 =
    # 24437500.  The 75 bps tier would have given 3000000 and 21000000 before fees.
    assert at_upper_floor["admin_fee_cents"] == 562_500
    assert at_upper_floor["draw_authorized_cents"] == 24_437_500
    assert at_upper_floor["draw_authorized_cents"] != 20_527_500
    # Nothing is encumbered yet, so availability equals the authorised draw.
    assert at_upper_floor["available_cents"] == 24_437_500
    assert at_upper_floor["recovery_credits_cents"] == 0


def test_acv_claim_gross_is_capped_at_the_policy_limit(api):
    """PRD §3.11: "The elapsed days between the work's `acquisition_date` and the logical clock's date are divided by 365 and truncated down to a whole number of years, and that age is capped at 25 years."
    PRD §3.11: "The depreciated value is the work's `insured_value_cents` multiplied by 0.98 raised to the power of that age in years, rounded half up to a whole cent."
    PRD §3.11: "The gross claim is first capped at the policy limit of 25,000,000 cents (250,000 dollars), the deductible of 250,000 cents (2,500 dollars) is then subtracted, and the result is floored at zero."
    PRD §3.11: "On settlement the named pool's `recovery_credits_cents` rises by `settlement_cents` and its `available_cents` rises by the same amount, and the pool's `version` increments — which is exactly the kind of unrequested movement that makes the pool version check in §2.11 necessary."

    Design: Corner/calculations/claim_gross_is_capped_by_the_policy_limit_and_depreciation_stops_at_25_years
    """
    pool = create_pool(api)
    register = setup_register(
        api,
        artwork={
            "accession_number": "2024.030",
            "title": "Total Loss Figure",
            "insured_value_cents": 40_000_000,
            "acquisition_date": "2014-06-01",
            "acquisition_document_ref": "DEED-2014-030",
        },
    )
    incident = setup_incident_triaged(
        api,
        register["artwork"]["id"],
        triage_class="TOTAL_LOSS",
        incident_type="VEHICLE_IMPACT",
        damage_extent_pct=1.00,
    )

    filed = validate_success(
        api.file_insurance_claim(
            incident["id"],
            {"claim_basis": "ACV", "credited_pool_id": pool["id"]},
            TEST_USERS["finance_headers"],
        )
    )

    assert_damage_incident(filed)
    assert filed["claim_status"] == "FILED"
    assert filed["claim_basis"] == "ACV"
    # 2014-06-01 to the clock date 2026-08-01 is 4444 days; 4444 / 365 = 12.17
    # truncated to age 12, under the 25-year cap.  Depreciated value
    # 40000000 * 0.98^12 = 40000000 * 0.7847167237348 = 31388668.95, half up to
    # 31388669; the extent multiplier is 1.00 so the gross stays 31388669.
    assert filed["claimed_gross_cents"] == 31_388_669
    # The gross exceeds the 25000000 policy limit, so the limit bites first and the
    # deductible comes off the capped figure: 25000000 - 250000 = 24750000.
    assert filed["settlement_cents"] == 24_750_000

    credited = read_pool(api, pool["id"])
    # Filing computes the figures but credits nothing; only a settlement credits.
    assert credited["recovery_credits_cents"] == 0


def test_acv_depreciation_stops_at_twenty_five_years(api):
    """PRD §3.11: "The elapsed days between the work's `acquisition_date` and the logical clock's date are divided by 365 and truncated down to a whole number of years, and that age is capped at 25 years."
    PRD §3.11: "The depreciated value is the work's `insured_value_cents` multiplied by 0.98 raised to the power of that age in years, rounded half up to a whole cent."
    PRD §3.11: "`claimed_gross_cents` is then that depreciated value multiplied by `damage_extent_pct`, rounded half up to a whole cent — note that the depreciation is rounded once before the extent multiplier is applied, and the product is rounded again after."

    Design: Corner/calculations/claim_gross_is_capped_by_the_policy_limit_and_depreciation_stops_at_25_years
    """
    register = setup_register(
        api,
        artwork={
            "accession_number": "2024.031",
            "title": "Old Marker",
            "significance_tier": "STANDARD",
            "footprint_units": 4,
            "insured_value_cents": 10_000_000,
            "acquisition_date": "1990-01-01",
            "acquisition_document_ref": "DEED-1990-031",
        },
    )
    incident = setup_incident_triaged(
        api,
        register["artwork"]["id"],
        triage_class="TOTAL_LOSS",
        incident_type="THEFT",
        damage_extent_pct=1.00,
    )

    filed = validate_success(
        api.file_insurance_claim(
            incident["id"], {"claim_basis": "ACV"}, TEST_USERS["finance_headers"]
        )
    )

    # 1990-01-01 to the clock date 2026-08-01 is 13361 days; 13361 / 365 = 36.60
    # truncated to 36 years, which the 25-year cap pulls back to 25.  Depreciated
    # value 10000000 * 0.98^25 = 10000000 * 0.60346472978 = 6034647.30, half up to
    # 6034647; extent 1.00 leaves the gross there.  Depreciating at the true age of
    # 36 would instead have given 10000000 * 0.98^36 = 4832131.
    assert filed["claimed_gross_cents"] == 6_034_647
    assert filed["claimed_gross_cents"] != 4_832_131
    # The gross is under the 25000000 limit, so only the deductible applies:
    #   6034647 - 250000 = 5784647
    assert filed["settlement_cents"] == 5_784_647
    assert filed["claim_status"] == "FILED"


def test_acv_settlement_floors_at_zero_when_the_deductible_exceeds_the_gross(api):
    """PRD §3.11: "`claimed_gross_cents` is then that depreciated value multiplied by `damage_extent_pct`, rounded half up to a whole cent — note that the depreciation is rounded once before the extent multiplier is applied, and the product is rounded again after."
    PRD §3.11: "The gross claim is first capped at the policy limit of 25,000,000 cents (250,000 dollars), the deductible of 250,000 cents (2,500 dollars) is then subtracted, and the result is floored at zero."
    PRD §3.11: "A claim whose gross figure does not exceed the deductible therefore settles at zero."

    Design: Corner/calculations/claim_gross_is_capped_by_the_policy_limit_and_depreciation_stops_at_25_years
    """
    register = setup_register(
        api,
        artwork={
            "accession_number": "2024.032",
            "title": "Scratched Plaque",
            "significance_tier": "STANDARD",
            "footprint_units": 2,
            "insured_value_cents": 12_000_000,
            "acquisition_date": "2014-06-01",
            "acquisition_document_ref": "DEED-2014-032",
        },
    )
    incident = setup_incident_triaged(
        api,
        register["artwork"]["id"],
        triage_class="ROUTINE_MAINTENANCE",
        incident_type="VANDALISM",
        damage_extent_pct=0.02,
    )

    filed = validate_success(
        api.file_insurance_claim(
            incident["id"], {"claim_basis": "ACV"}, TEST_USERS["finance_headers"]
        )
    )

    # Age 12 as at the clock date 2026-08-01: depreciated value
    # 12000000 * 0.98^12 = 9416600.68, half up to 9416601; the extent multiplier is
    # then applied to that rounded figure: 9416601 * 0.02 = 188332.02, half up to
    # 188332.
    assert filed["claimed_gross_cents"] == 188_332
    # 188332 does not exceed the 250000 deductible, so the settlement floors at zero
    # rather than going negative.
    assert filed["settlement_cents"] == 0
    assert filed["claim_status"] == "FILED"
