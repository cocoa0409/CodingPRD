"""
Rules that turn over on a single unit of their input.

Two quantities are exercised one unit apart: the side-lot free-area allowance,
where the 5,000th square foot is free and the 5,001st costs two cents, and the
statutory delinquent-taxpayer bar, where zero cents passes and one cent bars.
"""

from test_helpers import (
    DISP_1,
    fixtures,
    make_applicant_headers,
    validate_error,
    validate_success,
)


# ── the side-lot free-area edge ─────────────────────────────────────────────
def _side_lot_parcel(api, *, lot_area_sqft, parcel_address):
    """A vacant grade-C parcel assessed at 200,000 cents, sized to order."""
    return fixtures.create_property(
        api,
        address=parcel_address,
        situs_ward=9,
        lot_area_sqft=lot_area_sqft,
        assessed_value_cents=200000,
        structure_present=False,
        structure_condition_grade="C",
        vacancy_months=6,
    )


def test_side_lot_quote_at_exactly_the_free_area(api):
    """
    A side lot of exactly 5,000 square feet is charged the bare base price because no square foot lies beyond the free allowance.

    A `SIDE_LOT` transfer starts at a base of 10,000 cents and adds 2 cents for every square foot of `lot_area_sqft` beyond the first 5,000 — the marginal area is zero when the lot is no larger than that free allowance — then caps the result at 25 percent of `assessed_value_cents` rounded half up, and finally raises it back to the 10,000-cent base if the cap pushed it below: the floor wins over the cap.

    Design: Difficulty/boundary_precision_check/side_lot_price_tier_boundary_at_free_area
    """
    parcel = _side_lot_parcel(api, lot_area_sqft=5000, parcel_address="130 Kestrel Ave")

    quote = validate_success(api.get_price_quote(parcel["id"], "SIDE_LOT", DISP_1))

    assert quote["program"] == "SIDE_LOT"
    assert quote["marginal_area_sqft"] == 0
    assert quote["quoted_price_cents"] == 10000
    # 25 percent of the 200,000-cent assessed value sits far above the base, so
    # the cap cannot bind at this edge.
    assert quote["assessed_cap_cents"] == 50000


def test_side_lot_quote_one_square_foot_past_the_free_area(api):
    """
    A side lot of 5,001 square feet is charged two cents above the base for the single square foot beyond the free allowance.

    A `SIDE_LOT` transfer starts at a base of 10,000 cents and adds 2 cents for every square foot of `lot_area_sqft` beyond the first 5,000 — the marginal area is zero when the lot is no larger than that free allowance — then caps the result at 25 percent of `assessed_value_cents` rounded half up, and finally raises it back to the 10,000-cent base if the cap pushed it below: the floor wins over the cap.

    Design: Difficulty/boundary_precision_check/side_lot_price_tier_boundary_at_free_area
    """
    at_edge = _side_lot_parcel(
        api, lot_area_sqft=5000, parcel_address="130 Kestrel Ave"
    )
    past_edge = _side_lot_parcel(
        api, lot_area_sqft=5001, parcel_address="131 Kestrel Ave"
    )

    quote_past = validate_success(
        api.get_price_quote(past_edge["id"], "SIDE_LOT", DISP_1)
    )
    assert quote_past["marginal_area_sqft"] == 1
    assert quote_past["quoted_price_cents"] == 10002
    assert quote_past["assessed_cap_cents"] == 50000

    quote_edge = validate_success(
        api.get_price_quote(at_edge["id"], "SIDE_LOT", DISP_1)
    )
    assert quote_edge["quoted_price_cents"] == 10000
    assert quote_past["quoted_price_cents"] - quote_edge["quoted_price_cents"] == 2


def test_side_lot_quotes_carry_no_condition_discount_on_a_vacant_lot(api):
    """
    Neither side of the free-area edge is discounted, because a parcel with no structure standing cannot attract the condition discount.

    After the programme tier is settled, a condition discount applies to every programme except `COMMUNITY_USE`: when the parcel has a structure standing and its `structure_condition_grade` is `D` or `F`, 15 percent of the quoted figure, rounded half up, is subtracted — but the result is never allowed below the programme's own floor.

    Design: Difficulty/boundary_precision_check/side_lot_price_tier_boundary_at_free_area
    """
    at_edge = _side_lot_parcel(
        api, lot_area_sqft=5000, parcel_address="130 Kestrel Ave"
    )
    past_edge = _side_lot_parcel(
        api, lot_area_sqft=5001, parcel_address="131 Kestrel Ave"
    )

    quote_edge = validate_success(
        api.get_price_quote(at_edge["id"], "SIDE_LOT", DISP_1)
    )
    quote_past = validate_success(
        api.get_price_quote(past_edge["id"], "SIDE_LOT", DISP_1)
    )

    assert quote_edge["discount_applied"] is False
    assert quote_past["discount_applied"] is False
    assert quote_edge["quoted_price_cents"] == 10000
    assert quote_past["quoted_price_cents"] == 10002


# ── the delinquent-taxpayer bar, zero cents against one cent ────────────────
def _listed_target_parcel(api):
    """
    A listed 8,500 sqft parcel assessed at 1,000,000 cents: the quote a
    developer request for proposals draws against it is 900,000 cents.
    """
    return fixtures.listed_parcel(
        api,
        funding_source=fixtures.create_acquisition_funding_source(api),
        property_overrides={
            "address": "140 Larkspur St",
            "situs_ward": 2,
            "lot_area_sqft": 8500,
            "assessed_value_cents": 1000000,
            "structure_present": True,
            "structure_condition_grade": "C",
            "vacancy_months": 8,
        },
        packet_overrides={
            "title_search_fee_cents": 20000,
            "donor_name": "Larkspur Trust",
        },
    )


def _developer_owning_a_parcel_with_delinquency(
    api, *, legal_name, contact_email, parcel_address, delinquent_tax_balance_cents
):
    """
    Register a developer, give it a registry parcel of record, and post the
    county tax roll for that parcel at the exact balance asked for.
    """
    buyer = fixtures.create_developer_applicant(
        api, legal_name=legal_name, contact_email=contact_email
    )
    owned = fixtures.create_property(
        api,
        address=parcel_address,
        situs_ward=2,
        lot_area_sqft=4000,
        assessed_value_cents=300000,
        structure_present=True,
        structure_condition_grade="C",
        vacancy_months=0,
    )
    fixtures.set_owner_of_record(api, owned["id"], buyer["id"])
    fixtures.post_tax_roll(
        api,
        owned["id"],
        delinquent_tax_balance_cents=delinquent_tax_balance_cents,
        tax_year=2025,
    )
    return buyer


def test_exactly_zero_cents_of_delinquency_submits(api):
    """
    A buyer whose parcels of record carry exactly zero cents of delinquency is not caught by the bar and its submission succeeds.

    The buyer must owe the county nothing: any delinquent-tax total strictly greater than zero across the parcels it owns of record bars the sale with `ERR_APPLICANT_TAX_DELINQUENT`, and two or more open code-enforcement violations across those same parcels bars it with `ERR_APPLICANT_CODE_VIOLATOR`.

    Design: Difficulty/boundary_precision_check/applicant_delinquency_zero_versus_one_cent_at_submit
    """
    bundle = _listed_target_parcel(api)
    buyer = _developer_owning_a_parcel_with_delinquency(
        api,
        legal_name="Zero Balance Developers",
        contact_email="a@zerobalance.example",
        parcel_address="141 Larkspur St",
        delinquent_tax_balance_cents=0,
    )
    application = fixtures.draft_application(
        api,
        bundle["property"]["id"],
        buyer["id"],
        proposed_use="Row-house infill",
        offer_price_cents=900000,
    )

    data = validate_success(
        api.submit_application(
            application["id"], make_applicant_headers(buyer["id"])
        )
    )

    assert data["status"] == "SUBMITTED"
    assert data["quoted_price_cents"] == 900000


def test_exactly_one_cent_of_delinquency_is_barred_at_submit(api):
    """
    A buyer whose parcels of record carry exactly one cent of delinquency is barred, and its application stays in draft.

    The buyer must owe the county nothing: any delinquent-tax total strictly greater than zero across the parcels it owns of record bars the sale with `ERR_APPLICANT_TAX_DELINQUENT`, and two or more open code-enforcement violations across those same parcels bars it with `ERR_APPLICANT_CODE_VIOLATOR`.

    Design: Difficulty/boundary_precision_check/applicant_delinquency_zero_versus_one_cent_at_submit
    """
    bundle = _listed_target_parcel(api)
    buyer = _developer_owning_a_parcel_with_delinquency(
        api,
        legal_name="One Cent Developers",
        contact_email="b@onecent.example",
        parcel_address="142 Larkspur St",
        delinquent_tax_balance_cents=1,
    )
    application = fixtures.draft_application(
        api,
        bundle["property"]["id"],
        buyer["id"],
        proposed_use="Row-house infill",
        offer_price_cents=900000,
    )

    response = api.submit_application(
        application["id"], make_applicant_headers(buyer["id"])
    )
    validate_error(response, "ERR_APPLICANT_TAX_DELINQUENT", 422)

    unchanged = fixtures.read_application(api, application["id"])
    assert unchanged["status"] == "DRAFT"
    assert unchanged["submitted_at"] is None


def test_one_cent_of_delinquency_bars_the_buyer_while_zero_cents_does_not(api):
    """
    The buyer's own standing turns over on the same cent: zero cents leaves it eligible, one cent bars it.

    The same roll-up drives the applicant record's own standing: `eligibility_status` is `BARRED` whenever the delinquent-tax total is strictly greater than zero, or the open-violation total is at least 2, or at least one reverter falls in the lookback window, and `ELIGIBLE` otherwise.

    Design: Difficulty/boundary_precision_check/applicant_delinquency_zero_versus_one_cent_at_submit
    """
    at_zero = _developer_owning_a_parcel_with_delinquency(
        api,
        legal_name="Zero Balance Developers",
        contact_email="a@zerobalance.example",
        parcel_address="141 Larkspur St",
        delinquent_tax_balance_cents=0,
    )
    at_one_cent = _developer_owning_a_parcel_with_delinquency(
        api,
        legal_name="One Cent Developers",
        contact_email="b@onecent.example",
        parcel_address="142 Larkspur St",
        delinquent_tax_balance_cents=1,
    )

    zero_row = validate_success(api.get_applicant(at_zero["id"], DISP_1))
    one_cent_row = validate_success(api.get_applicant(at_one_cent["id"], DISP_1))

    assert zero_row["delinquent_tax_total_cents"] == 0
    assert zero_row["eligibility_status"] == "ELIGIBLE"
    assert one_cent_row["delinquent_tax_total_cents"] == 1
    assert one_cent_row["eligibility_status"] == "BARRED"
