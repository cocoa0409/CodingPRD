"""Arithmetic the Transfer of Development Rights program fixes to the unit and the cent.

Five computations are pinned here, each with its rounding discipline made
visible: the soil multiplier and the floor that turns a half unit into a whole
one at parcel enrollment, the two-bucket severance waterfall that trims a grant
by the parcel before the area, the inclusive upper bound of the first settlement
fee tier, the two deliberately divergent bonus-sizing variants on one receiving-
site application, and the window filter that scopes every evaluation metric to
its own source date.

Every test builds its whole registry state from scratch through the API.
"""
import pytest

from test_helpers import (
    REVIEWER_USER_ID,
    TEST_USERS,
    api_client,
    assert_certificate,
    assert_certificate_redemption,
    assert_certificate_units_conserved,
    assert_conservation_easement,
    assert_market_transaction,
    assert_program_cash_conserved,
    assert_program_evaluation,
    assert_receiving_site_application,
    assert_same_instant,
    assert_sending_parcel,
    assert_severance_application,
    compute_evaluation,
    create_active_sending_area,
    create_sending_parcel_payload,
    credit_party,
    enroll_parcel,
    fetch_certificate,
    fetch_easement,
    fetch_parcel,
    fetch_party,
    fetch_receiving_area,
    fetch_redemption,
    fetch_sending_area,
    file_severance,
    finalize_application,
    make_landowner_headers,
    make_reviewer_headers,
    program_cash_total_now,
    propose_transaction,
    publish_appraisal_schedule,
    register_bank,
    register_developer,
    register_landowner,
    screen_application,
    settle_transaction,
    setup_backed_receiving_application,
    setup_certified_severance,
    split_certificate,
    validate_paginated,
    validate_success,
)

ADMIN_HEADERS = TEST_USERS["admin_headers"]

CLOCK = "2026-08-10T00:00:00Z"


def test_soil_class_multipliers_move_the_floored_baseline_allocation():
    """All four soil multipliers on four otherwise identical 40.00-acre parcels.

    Two of the four raw figures land on a half unit, so the flooring rule is
    observable as truncation rather than rounding: PRIME gives 12.5 units and
    stores 12, NONE gives 7.5 units and stores 7.

    PRD 3.3: "The computation proceeds in four steps. First, a soil multiplier is
    selected from the parcel's `soil_class`: `PRIME` yields a multiplier of 1.25,
    `STATEWIDE` yields 1.10, `LOCAL` yields 1.00, and `NONE` yields 0.75."

    PRD 3.3: "Under `V1_NET_ACRE`, eligible acreage is `gross_acres` minus
    `constrained_acres`, and `gross_discount_factor` is ignored entirely."

    PRD 3.3: "Third, a raw figure is formed as the eligible acreage multiplied by
    the area's `base_rate_units_per_acre` multiplied by the soil multiplier.
    Fourth, that raw figure is floored to a whole number — truncated downward,
    never rounded — the parcel's `existing_dwelling_units` are subtracted from
    the floored value because each already-built dwelling consumes one allocated
    right, and the result is taken as zero if the subtraction would go negative.
    The outcome is a non-negative integer stored as `baseline_allocation_units`."

    PRD 3.3: "On enrollment the derived ledger fields open at their starting
    values: `remaining_units` equals `baseline_allocation_units`, `severed_units`
    is 0, `restricted_acres` is 0, `easement_status` is `NONE`, and
    `parcel_status` is `UNSEVERED`."

    PRD 3.5: "The sending area's `severed_units_total` is recomputed as the sum of
    `allocated_units` over every `CERTIFIED` application on parcels in the area,
    and its `issued_certificate_count` is incremented by one."

    Design: Corner/calculations/soil_class_multiplier_constants_move_the_baseline_allocation
    """
    landowner = register_landowner(neighborhood_code="NB-EAST")
    area = create_active_sending_area(
        code="SA-SOIL",
        name="Soil Test Area",
        neighborhood_code="NB-EAST",
        allocation_formula_version="V1_NET_ACRE",
        base_rate_units_per_acre=0.25,
        gross_discount_factor=0.80,
        equity_tier="UNDERSERVED",
        sending_cap_units=200,
    )

    expected_baseline = {"PRIME": 12, "STATEWIDE": 11, "LOCAL": 10, "NONE": 7}
    enrolled = {}
    for soil_class in ("PRIME", "STATEWIDE", "LOCAL", "NONE"):
        response = api_client.create_sending_parcel(
            create_sending_parcel_payload(
                landowner["id"], area["id"],
                apn=f"APN-{soil_class}",
                gross_acres=40.00,
                constrained_acres=0.00,
                soil_class=soil_class,
                existing_dwelling_units=0,
            ),
            ADMIN_HEADERS,
        )
        enrolled[soil_class] = validate_success(response, 201)

    for soil_class, baseline in expected_baseline.items():
        parcel = enrolled[soil_class]
        assert_sending_parcel(parcel)
        assert parcel["baseline_allocation_units"] == baseline, (
            f"{soil_class}: 40.00 net acres x 0.25 units/acre x its soil multiplier, "
            f"floored, must be {baseline}, got {parcel['baseline_allocation_units']}"
        )
        assert parcel["remaining_units"] == baseline, (
            f"{soil_class}: remaining_units must open at the baseline {baseline}, "
            f"got {parcel['remaining_units']}"
        )
        assert parcel["severed_units"] == 0, (
            f"{soil_class}: severed_units must open at 0, got {parcel['severed_units']}"
        )
        assert parcel["restricted_acres"] == pytest.approx(0.00, abs=0.01), (
            f"{soil_class}: restricted_acres must open at 0.00"
        )
        assert parcel["easement_status"] == "NONE", parcel["easement_status"]
        assert parcel["parcel_status"] == "UNSEVERED", parcel["parcel_status"]

    area_after = fetch_sending_area(area["id"])
    assert area_after["severed_units_total"] == 0, (
        "enrolling parcels allocates potential, not severed rights: severed_units_total "
        f"must still be 0, got {area_after['severed_units_total']}"
    )
    assert area_after["issued_certificate_count"] == 0, (
        "no certification has run, so issued_certificate_count must still be 0"
    )


def test_severance_grant_is_trimmed_by_the_parcel_bucket_before_the_area_bucket():
    """A 30-unit request against a 10-unit parcel inside a 200-unit area.

    The parcel bucket binds first, so the grant is 10 and nothing is retained;
    the area, with 200 units of untouched headroom, never enters the answer.

    PRD 3.4: "The grant computation is a two-bucket waterfall in whole units, with
    no rounding anywhere. The parcel bucket is the parcel's `remaining_units`. The
    area bucket is the area's `sending_cap_units` less its `severed_units_total`."

    PRD 3.4: "Otherwise `allocated_units` is the smallest of three quantities: the
    `requested_units` on the application, the parcel bucket, and the area bucket.
    If that smallest quantity is not at least one, the approval is rejected with
    `ERR_NO_ALLOCABLE_UNITS`. The parcel bucket is consumed before the area
    bucket, so a request that the area could accommodate but the parcel cannot is
    trimmed down by the parcel. Finally, `residual_units_retained` is the parcel
    bucket less `allocated_units` — the rights the owner keeps and may sever in a
    future application."

    PRD 3.4: "It runs that computation, writes `allocated_units` and
    `residual_units_retained`, and pins `applied_formula_version` by copying the
    area's `allocation_formula_version` onto the application, so that a later
    ordinance change cannot restate a grant that has already been decided."

    PRD 3.3: "`remaining_units` is always `baseline_allocation_units` less
    `severed_units`, and `severed_units` is always the sum of `allocated_units`
    over the parcel's severance applications that reached `CERTIFIED`."

    PRD 4: "Endpoints that advance, amend, or read an existing record respond with
    HTTP 200."

    Design: Corner/calculations/severance_grant_is_trimmed_by_the_parcel_bucket_before_the_area_bucket
    """
    landowner = register_landowner(neighborhood_code="NB-EAST")
    area = create_active_sending_area(
        code="SA-EAST",
        name="East Ridge",
        neighborhood_code="NB-EAST",
        allocation_formula_version="V1_NET_ACRE",
        base_rate_units_per_acre=0.25,
        gross_discount_factor=0.80,
        equity_tier="UNDERSERVED",
        sending_cap_units=200,
    )
    parcel = enroll_parcel(
        landowner["id"], area["id"], apn="APN-TEN",
        gross_acres=40.00, constrained_acres=0.00,
        soil_class="LOCAL", existing_dwelling_units=0,
    )
    assert parcel["baseline_allocation_units"] == 10, (
        "the parcel bucket must open at 10 units for this waterfall to be legible, "
        f"got {parcel['baseline_allocation_units']}"
    )

    application = file_severance(parcel["id"], landowner["id"], 30)
    screen_application(application["id"], REVIEWER_USER_ID)

    decided = validate_success(
        api_client.review_severance_application(
            application["id"], {"decision": "APPROVE"},
            make_reviewer_headers(REVIEWER_USER_ID),
        )
    )
    assert_severance_application(decided)
    assert decided["status"] == "APPROVED", decided["status"]
    assert decided["allocated_units"] == 10, (
        "allocated_units must be the smallest of requested 30, parcel bucket 10 and "
        f"area bucket 200, so 10; got {decided['allocated_units']}"
    )
    assert decided["residual_units_retained"] == 0, (
        "the parcel bucket less the grant is 10 - 10 = 0; got "
        f"{decided['residual_units_retained']}"
    )
    assert decided["applied_formula_version"] == "V1_NET_ACRE", (
        "the area's allocation_formula_version must be pinned onto the application, got "
        f"{decided['applied_formula_version']}"
    )
    assert decided["requested_units"] == 30, (
        f"the request itself is not rewritten by the grant, got {decided['requested_units']}"
    )

    parcel_after = fetch_parcel(parcel["id"])
    assert parcel_after["severed_units"] == 0, (
        "approval sizes the grant; only certification consumes it, so severed_units must "
        f"still be 0, got {parcel_after['severed_units']}"
    )
    assert parcel_after["remaining_units"] == 10, (
        f"remaining_units must still be 10, got {parcel_after['remaining_units']}"
    )
    assert fetch_sending_area(area["id"])["severed_units_total"] == 0, (
        "the area bucket is untouched until a certification lands"
    )


def test_settlement_fee_tier_upper_bound_is_inclusive_at_five_million_cents():
    """Two settlements one cent apart across the first fee-tier boundary.

    A gross of exactly 5,000,000 cents is billed at 350 basis points; a gross of
    5,000,001 cents falls to the next tier at 275, so the larger deal pays the
    smaller fee.  The origin area is `UNDERSERVED`, which zeroes the surcharge and
    leaves the fee as the only deduction.

    PRD 3.7: "The money split runs in four steps and reads every figure off the
    gross price. First, a fee rate is selected by tier from `gross_price_cents`
    itself, never from any post-surcharge figure: a gross of at most 5,000,000
    cents — fifty thousand dollars — attracts 350 basis points; a gross above that
    but at most 25,000,000 cents — two hundred fifty thousand dollars — attracts
    275 basis points; anything above that attracts 200 basis points. Tier
    boundaries are inclusive on their upper bound, so a gross of exactly 5,000,000
    cents sits in the first tier at 350 basis points while 5,000,001 cents sits in
    the second at 275. Second, `program_fee_cents` is `gross_price_cents`
    multiplied by that rate divided by ten thousand, rounded half up to whole
    cents. Third, `equity_surcharge_cents` is `gross_price_cents` multiplied by a
    surcharge rate divided by ten thousand, rounded half up to whole cents, where
    the surcharge rate comes from the `equity_tier` of the sending area named by
    the certificate's `origin_sending_area_id`: 150 basis points for `HIGH_VALUE`,
    75 basis points for `MODERATE`, and 0 basis points for `UNDERSERVED`, so
    preserving land in an underserved neighborhood carries no surcharge at all.
    Fourth, `net_to_seller_cents` is `gross_price_cents` less `program_fee_cents`
    less `equity_surcharge_cents`. Each cents figure is rounded independently."

    PRD 3.7: "Cash then moves in three legs that sum to zero, as §2.11 requires:
    the buyer's `cash_balance_cents` is reduced by `gross_price_cents`, the
    seller's `cash_balance_cents` is increased by `net_to_seller_cents`, and the
    `MUNICIPAL_BANK` party's `fee_revenue_cents` is increased by
    `program_fee_cents` plus `equity_surcharge_cents`."

    PRD 3.7: "For `PRIVATE`, `gross_price_cents` is the `agreed_price_cents` from
    the request, taken exactly as supplied."

    Design: Corner/calculations/settlement_fee_tier_upper_bound_is_inclusive_at_five_million_cents
    """
    scenario = setup_certified_severance(
        units=10,
        clock=CLOCK,
        equity_tier="UNDERSERVED",
        neighborhood_code="NB-EAST",
        parcel_overrides={
            "gross_acres": 40.00,
            "constrained_acres": 0.00,
            "soil_class": "LOCAL",
            "existing_dwelling_units": 0,
        },
    )
    landowner = scenario["landowner"]
    parent = scenario["certificate"]
    assert parent["units_face"] == 10, (
        f"the scenario must issue exactly 10 units, got {parent['units_face']}"
    )

    developer = register_developer(neighborhood_code="NB-CORE")
    bank = register_bank(neighborhood_code="NB-CORE")
    publish_appraisal_schedule(
        neighborhood_code="NB-EAST",
        per_unit_value_cents=1_000_000,
        equity_adjustment_bps=0,
        effective_from="2026-01-01",
        effective_to="2027-01-01",
    )
    credit_party(developer["id"], 20_000_000)
    cash_before = program_cash_total_now()

    seller_headers = make_landowner_headers(landowner["id"])
    child = split_certificate(parent["id"], 5, seller_headers)

    tx_at_boundary = propose_transaction(
        parent["id"], landowner["id"], developer["id"], units=5,
        channel="PRIVATE", agreed_price_cents=5_000_000,
    )
    tx_one_cent_over = propose_transaction(
        child["id"], landowner["id"], developer["id"], units=5,
        channel="PRIVATE", agreed_price_cents=5_000_001,
    )

    settled_at_boundary = settle_transaction(tx_at_boundary["id"])
    settled_over = settle_transaction(tx_one_cent_over["id"])

    for settled in (settled_at_boundary, settled_over):
        assert_market_transaction(settled)
        assert settled["status"] == "SETTLED", settled["status"]
        assert settled["applied_per_unit_value_cents"] == 1_000_000, (
            "a zero equity adjustment leaves the schedule per-unit value untouched, got "
            f"{settled['applied_per_unit_value_cents']}"
        )
        assert settled["appraised_reference_cents"] == 5_000_000, (
            f"5 units at 1,000,000 cents each, got {settled['appraised_reference_cents']}"
        )
        assert settled["equity_surcharge_cents"] == 0, (
            "an UNDERSERVED origin area carries 0 basis points of surcharge, got "
            f"{settled['equity_surcharge_cents']}"
        )

    assert settled_at_boundary["gross_price_cents"] == 5_000_000, (
        f"the agreed price is taken as supplied, got {settled_at_boundary['gross_price_cents']}"
    )
    assert settled_at_boundary["program_fee_cents"] == 175_000, (
        "a gross of exactly 5,000,000 sits in the first tier at 350 bps, so the fee is "
        f"175,000 cents; got {settled_at_boundary['program_fee_cents']}"
    )
    assert settled_at_boundary["net_to_seller_cents"] == 4_825_000, (
        "5,000,000 less 175,000 less 0 is 4,825,000; got "
        f"{settled_at_boundary['net_to_seller_cents']}"
    )

    assert settled_over["gross_price_cents"] == 5_000_001, (
        f"the agreed price is taken as supplied, got {settled_over['gross_price_cents']}"
    )
    assert settled_over["program_fee_cents"] == 137_500, (
        "a gross of 5,000,001 drops to the second tier at 275 bps, so 5,000,001 * 275 / 10000 "
        f"= 137,500.0275 rounds half up to 137,500; got {settled_over['program_fee_cents']}"
    )
    assert settled_over["net_to_seller_cents"] == 4_862_501, (
        "5,000,001 less 137,500 less 0 is 4,862,501; got "
        f"{settled_over['net_to_seller_cents']}"
    )
    assert settled_over["program_fee_cents"] < settled_at_boundary["program_fee_cents"], (
        "the inclusive upper bound makes the one-cent-larger deal pay the smaller fee"
    )

    seller_after = fetch_party(landowner["id"])
    buyer_after = fetch_party(developer["id"])
    bank_after = fetch_party(bank["id"])
    assert seller_after["cash_balance_cents"] == 4_825_000 + 4_862_501, (
        "the seller receives both net proceeds, 9,687,501 cents in total; got "
        f"{seller_after['cash_balance_cents']}"
    )
    assert buyer_after["cash_balance_cents"] == 20_000_000 - 10_000_001, (
        "the buyer is debited both gross prices, leaving 9,999,999 cents; got "
        f"{buyer_after['cash_balance_cents']}"
    )
    assert bank_after["fee_revenue_cents"] == 175_000 + 137_500, (
        "the bank accrues both fees plus both zero surcharges, 312,500 cents; got "
        f"{bank_after['fee_revenue_cents']}"
    )
    assert_program_cash_conserved(
        cash_before, program_cash_total_now(), "across two PRIVATE settlements"
    )


def test_bonus_sizing_switches_from_the_provisional_to_the_final_variant_at_finalization():
    """One 12.00-acre application asking for 20 bonus units, sized twice.

    Intake runs the provisional variant and writes 8 — half of the 16-unit
    ceiling, floored — while finalization runs the final variant on the same
    application and grants the full 16, so the two figures for one filing differ
    by construction.

    PRD 3.8: "First a site tier factor is chosen from `site_acres`: a site of at
    least 10.00 acres takes 1.00, a site of at least 3.00 but under 10.00 acres
    takes 0.90, and anything smaller takes 0.75."

    PRD 3.8: "Second, `base_units` is `site_acres` multiplied by the area's
    `base_density_units_per_acre`, floored to a whole number. Third,
    `max_bonus_units` is the already-floored `base_units` multiplied by the area's
    `max_bonus_pct` and then by the tier factor, floored again."

    PRD 3.8: "`required_backing_units` is then the lesser of
    `requested_bonus_units` and `max_bonus_units` — a developer who asks for more
    density than the area can grant is not rejected at intake, but is only ever
    required to back, and can only ever receive, the area's maximum."

    PRD 3.8: "The provisional variant, used at intake and again on every design
    resubmission, writes `provisional_bonus_units` as the lesser of
    `requested_bonus_units` and half of `max_bonus_units` floored — a release
    fraction of one half."

    PRD 3.8: "The final variant, used only at finalization, drops the half-release
    cap and writes `allocated_bonus_units` as the smallest of
    `requested_bonus_units`, `max_bonus_units`, and `backed_units`."

    PRD 3.8: "Either way the provisional sizing has already run, and `backed_units`,
    `pending_backed_units`, and `allocated_bonus_units` all start at 0."

    PRD 3.8: "Each confirmation moves its units out of the certificate's
    `units_encumbered` and into `units_redeemed`, moves the same units out of the
    area's `reserved_units` and into `absorbed_units`, increases the source
    easement's `units_redeemed_confirmed` and decreases its `units_outstanding` by
    the same amount, appends a `REDEMPTION` chain-of-title row, and advances the
    certificate's `lifecycle_status` — `ISSUED → PARTIALLY_REDEEMED` when part of
    the certificate survives, or straight to `REDEEMED` when the confirmation
    consumes everything that remained."

    PRD 3.8: "The final sizing variant then writes `allocated_bonus_units`,
    `finalized_at` is set from the clock, the application moves `DESIGN_APPROVED →
    FINALIZED`, and its `version` increments."

    PRD 3.8: "Note that the backing figure the final variant consumes counts
    redemptions in `ALLOCATED` and `CONFIRMED` only; rows in
    `HELD_PENDING_COMPLIANCE` and `RELEASED` are excluded from it."

    Design: Corner/calculations/bonus_sizing_switches_from_the_provisional_to_the_final_variant_at_finalization
    """
    scenario = setup_backed_receiving_application(
        backing_units=16,
        site_acres=12.00,
        requested_bonus_units=20,
        absorption_cap_units=500,
        design_review_required=False,
        clock=CLOCK,
    )
    developer = scenario["developer"]
    rsa = scenario["rsa"]
    redemption = scenario["redemption"]

    assert_receiving_site_application(rsa)
    assert rsa["status"] == "DESIGN_APPROVED", rsa["status"]
    assert rsa["base_units"] == 48, (
        f"12.00 acres x 4.00 units/acre floored is 48, got {rsa['base_units']}"
    )
    assert rsa["max_bonus_units"] == 16, (
        "48 x 0.35 x the 1.00 tier factor is 16.8, floored again to 16; got "
        f"{rsa['max_bonus_units']}"
    )
    assert rsa["required_backing_units"] == 16, (
        "the lesser of the 20 units requested and the 16-unit ceiling is 16; got "
        f"{rsa['required_backing_units']}"
    )
    assert rsa["provisional_bonus_units"] == 8, (
        "the provisional variant takes the lesser of 20 and half of 16 floored, so 8; got "
        f"{rsa['provisional_bonus_units']}"
    )
    assert rsa["allocated_bonus_units"] == 0, (
        "the final variant has not run yet, so allocated_bonus_units must still be 0; got "
        f"{rsa['allocated_bonus_units']}"
    )
    assert rsa["backed_units"] == 0, (
        f"no redemption is CONFIRMED yet, got backed_units {rsa['backed_units']}"
    )
    assert rsa["pending_backed_units"] == 16, (
        f"the ALLOCATED redemption commits 16 units, got {rsa['pending_backed_units']}"
    )
    assert redemption["status"] == "ALLOCATED", redemption["status"]

    finalized = finalize_application(rsa["id"], developer["id"])
    assert_receiving_site_application(finalized)
    assert finalized["status"] == "FINALIZED", finalized["status"]
    assert finalized["allocated_bonus_units"] == 16, (
        "the final variant takes the smallest of requested 20, ceiling 16 and backed 16, "
        f"so 16 — not the provisional 8; got {finalized['allocated_bonus_units']}"
    )
    assert finalized["provisional_bonus_units"] == 8, (
        "finalization does not rewrite the provisional figure; got "
        f"{finalized['provisional_bonus_units']}"
    )
    assert finalized["backed_units"] == 16, (
        f"the confirmed redemption counts toward backed_units, got {finalized['backed_units']}"
    )
    assert finalized["version"] > rsa["version"], (
        "finalization must increment the application's version"
    )
    assert_same_instant(finalized["finalized_at"], CLOCK, "finalized_at")

    confirmed = fetch_redemption(redemption["id"])
    assert_certificate_redemption(confirmed)
    assert confirmed["status"] == "CONFIRMED", confirmed["status"]
    assert_same_instant(confirmed["confirmed_at"], CLOCK, "confirmed_at")

    certificate = fetch_certificate(scenario["certificate"]["id"])
    assert_certificate(certificate)
    assert certificate["units_redeemed"] == 16, (
        f"confirmation consumes 16 units, got {certificate['units_redeemed']}"
    )
    assert certificate["units_encumbered"] == 0, (
        "the confirmed units leave units_encumbered, got "
        f"{certificate['units_encumbered']}"
    )
    assert certificate["units_remaining"] == 6, (
        f"22 face less 16 redeemed is 6, got {certificate['units_remaining']}"
    )
    assert certificate["lifecycle_status"] == "PARTIALLY_REDEEMED", (
        "6 of 22 units survive, so the certificate is PARTIALLY_REDEEMED, got "
        f"{certificate['lifecycle_status']}"
    )
    assert_certificate_units_conserved(certificate)

    area_after = fetch_receiving_area(scenario["receiving_area"]["id"])
    assert area_after["absorbed_units"] == 16, (
        f"the granted units are absorbed by the area, got {area_after['absorbed_units']}"
    )
    assert area_after["reserved_units"] == 0, (
        f"the reservation is consumed by confirmation, got {area_after['reserved_units']}"
    )
    assert area_after["status"] == "ACTIVE", (
        "16 absorbed units are far below the 500-unit cap, so the area stays ACTIVE; got "
        f"{area_after['status']}"
    )

    easement_after = fetch_easement(scenario["easement"]["id"])
    assert_conservation_easement(easement_after)
    assert easement_after["units_redeemed_confirmed"] == 16, (
        f"got {easement_after['units_redeemed_confirmed']}"
    )
    assert easement_after["units_outstanding"] == 6, (
        f"22 issued less 16 confirmed is 6 outstanding, got {easement_after['units_outstanding']}"
    )

    developer_after = fetch_party(developer["id"])
    assert developer_after["units_held"] == 6, (
        f"the developer still holds the 6 unredeemed units, got {developer_after['units_held']}"
    )


def test_evaluation_counts_only_records_dated_inside_the_window():
    """One preservation dated 2026-08-10, measured over August and then September.

    Every window-scoped metric reports the easement and its certificate in the
    August window and zero in the September window, while the two program-wide
    snapshots — `absorption_pct` and `total_cash_cents` — read the same in both.

    PRD 3.9: "The window is inclusive at both ends and compared at date
    granularity."

    PRD 3.9: "`preserved_acres` sums `restricted_acres` over easements whose
    `recording_status` is `RECORDED` or `AMENDED` and whose `recorded_at` date
    falls in the window; easements still `PENDING_RECORDING` are excluded
    entirely. `easement_count` counts those same easements. `issued_units` sums
    `units_face` over certificates whose `issued_at` date falls in the window, and
    `retired_units` sums `units_retired` over that same certificate set — note that
    both are scoped by issuance date, so a retirement is attributed to the period
    in which the certificate was issued, not the period in which it was retired.
    `redeemed_units` sums `units` over redemptions that are `CONFIRMED` and whose
    `confirmed_at` date falls in the window. `outstanding_units` is `issued_units`
    less `redeemed_units` less `retired_units`."

    PRD 3.9: "`absorption_pct` is the sum of `absorbed_units` divided by the sum of
    `absorption_cap_units` across every receiving area whose `status` is `ACTIVE`
    or `SUSPENDED`, as a percentage rounded half up to two decimal places, and
    reports 0.00 rather than erroring when the denominator is zero; `DRAFT` areas
    never enter that denominator, and the figure is a program-wide snapshot rather
    than a window-scoped one."

    PRD 3.9: "`total_cash_cents` is the sum of `cash_balance_cents` plus the sum of
    `fee_revenue_cents` across all parties, which by §2.11 is a constant the
    evaluation merely reports."

    PRD 3.9: "Under `ACREAGE_WEIGHTED` the index is the underserved share of
    `preserved_acres`; under `PARCEL_COUNT_WEIGHTED` it is the underserved share of
    `easement_count`. Both are percentages rounded half up to two decimal places,
    and both report 0.00 when their denominator is zero."

    PRD 3.5: "The easement's `restricted_acres` is recomputed as the parcel's
    `gross_acres` multiplied by the cumulative severed unit count and divided by
    the parcel's `baseline_allocation_units`, rounded half up to two decimal
    places, where the cumulative severed count is the parcel's `severed_units`
    before this certification plus the `allocated_units` now being certified."

    PRD 3.9: "Evaluations start in `COMPUTED` and can be listed with `status` and
    `equity_weighting` filters plus `limit` and `offset`."

    Design: Corner/calculations/evaluation_counts_only_records_dated_inside_the_window
    """
    scenario = setup_certified_severance(
        units=22, clock=CLOCK, equity_tier="UNDERSERVED", neighborhood_code="NB-EAST",
    )
    easement = scenario["easement"]
    certificate = scenario["certificate"]
    assert easement["recording_status"] == "RECORDED", easement["recording_status"]
    assert easement["restricted_acres"] == pytest.approx(100.00, abs=0.01), (
        "severing the parcel's whole 22-unit baseline encumbers all 100.00 gross acres, got "
        f"{easement['restricted_acres']}"
    )
    assert certificate["units_face"] == 22, certificate["units_face"]

    inside = compute_evaluation("2026-08-01", "2026-08-31", "ACREAGE_WEIGHTED")
    assert_program_evaluation(inside)
    assert inside["status"] == "COMPUTED", inside["status"]
    assert inside["preserved_acres"] == pytest.approx(100.00, abs=0.01), (
        "the August window covers the 2026-08-10 recording, so all 100.00 restricted acres "
        f"count; got {inside['preserved_acres']}"
    )
    assert inside["easement_count"] == 1, (
        f"exactly one RECORDED easement sits in the window, got {inside['easement_count']}"
    )
    assert inside["issued_units"] == 22, (
        f"the certificate's 22 face units were issued in the window, got {inside['issued_units']}"
    )
    assert inside["retired_units"] == 0, (
        f"nothing has been retired, got {inside['retired_units']}"
    )
    assert inside["redeemed_units"] == 0, (
        f"no redemption has been confirmed, got {inside['redeemed_units']}"
    )
    assert inside["outstanding_units"] == 22, (
        "22 issued less 0 redeemed less 0 retired is 22, got "
        f"{inside['outstanding_units']}"
    )
    assert inside["equity_index"] == pytest.approx(100.00, abs=0.01), (
        "the only easement sits in an UNDERSERVED sending area, so its acreage share is "
        f"100.00 percent; got {inside['equity_index']}"
    )
    assert inside["absorption_pct"] == pytest.approx(0.00, abs=0.01), (
        "no receiving area exists, so the absorption denominator is zero and the metric "
        f"reports 0.00; got {inside['absorption_pct']}"
    )
    assert inside["total_cash_cents"] == program_cash_total_now(), (
        "total_cash_cents must report the program-wide money total, got "
        f"{inside['total_cash_cents']}"
    )

    outside = compute_evaluation("2026-09-01", "2026-09-30", "ACREAGE_WEIGHTED")
    assert_program_evaluation(outside)
    assert outside["status"] == "COMPUTED", outside["status"]
    assert outside["preserved_acres"] == pytest.approx(0.00, abs=0.01), (
        "the September window covers no recording date, so no acreage counts; got "
        f"{outside['preserved_acres']}"
    )
    assert outside["easement_count"] == 0, (
        f"the August easement is out of window, got {outside['easement_count']}"
    )
    assert outside["issued_units"] == 0, (
        f"the certificate was issued in August, got {outside['issued_units']}"
    )
    assert outside["retired_units"] == 0, outside["retired_units"]
    assert outside["redeemed_units"] == 0, outside["redeemed_units"]
    assert outside["outstanding_units"] == 0, (
        f"0 issued less 0 redeemed less 0 retired is 0, got {outside['outstanding_units']}"
    )
    assert outside["equity_index"] == pytest.approx(0.00, abs=0.01), (
        "an empty easement set leaves the equity denominator at zero, which reports 0.00; got "
        f"{outside['equity_index']}"
    )
    assert outside["absorption_pct"] == pytest.approx(0.00, abs=0.01), (
        f"got {outside['absorption_pct']}"
    )
    assert outside["total_cash_cents"] == inside["total_cash_cents"], (
        "the cash total is a program-wide snapshot, so the two windows must agree: "
        f"{outside['total_cash_cents']} != {inside['total_cash_cents']}"
    )

    rows, meta = validate_paginated(
        api_client.list_evaluations(ADMIN_HEADERS, params={"limit": 50, "offset": 0})
    )
    assert meta["total_count"] == 2, (
        f"both computed evaluations must be readable back, got {meta['total_count']}"
    )
    assert {row["id"] for row in rows} == {inside["id"], outside["id"]}, (
        "the listing must return exactly the two evaluations computed here"
    )
