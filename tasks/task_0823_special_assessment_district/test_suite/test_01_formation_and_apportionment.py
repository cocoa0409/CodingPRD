"""District formation, the majority-protest hearing, and roll apportionment.

Covers difficulty instances apportionment_benefit_units_vs_land_area,
apportionment_floor_then_distribute_remainder_mode_b, protest_ratio_exactly_at_threshold_forms,
and corner instances for the incidental-cost default and the disclosure report.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    create_protest_payload, make_parcel_owner_headers,
    setup_confirmed_roll, setup_formed_district,
    create_district, add_parcel, open_protest, close_hearing,
    create_roll, confirm_roll, refresh_parcel,
)


# --- apportionment: benefit units vs land area (dual-variant on the Parcel domain) ---

def test_apportionment_by_benefit_units_assigns_expected_principal(api):
    """PRD §3.3: "Each parcel's weight is the value chosen by the roll's method: its
    benefit_units for BENEFIT_UNITS, its land_area_sqft for LAND_AREA, or its
    front_footage_ft for FRONT_FOOTAGE." PRD §3.3: "The remainder ... is a non-negative
    number of leftover cents, and one extra cent is awarded to each parcel in order of
    descending weight, ties broken by earlier created_at first, until the remainder is
    exhausted."

    Design: Difficulty/dual_variant_calc/apportionment_benefit_units_vs_land_area
    """
    _, parcels, _ = setup_confirmed_roll(
        api,
        parcels=[
            {"apn": "A-1", "owner_name": "O1", "benefit_units": 60, "land_area_sqft": 4000, "front_footage_ft": 60},
            {"apn": "A-2", "owner_name": "O2", "benefit_units": 40, "land_area_sqft": 6000, "front_footage_ft": 40},
        ],
        formation_method="BENEFIT_UNITS",
        total_project_cost_cents=10_000_000,
        roll_method="BENEFIT_UNITS",
    )
    assert parcels[0]["assessed_principal_cents"] == 6000000


def test_apportionment_by_land_area_differs_from_benefit_units(api):
    """PRD §3.3: "Because the same parcels can carry different relative weights under
    different methods, the same assessable total yields a different per-parcel principal
    under each method." PRD §3.3: "Each parcel's weight is the value chosen by the roll's
    method: its benefit_units for BENEFIT_UNITS, its land_area_sqft for LAND_AREA, or its
    front_footage_ft for FRONT_FOOTAGE."

    Design: Difficulty/dual_variant_calc/apportionment_benefit_units_vs_land_area
    """
    _, bu_parcels, _ = setup_confirmed_roll(
        api,
        parcels=[
            {"apn": "A-1", "owner_name": "O1", "benefit_units": 60, "land_area_sqft": 4000, "front_footage_ft": 60},
            {"apn": "A-2", "owner_name": "O2", "benefit_units": 40, "land_area_sqft": 6000, "front_footage_ft": 40},
        ],
        formation_method="BENEFIT_UNITS", total_project_cost_cents=10_000_000, roll_method="BENEFIT_UNITS",
    )
    _, la_parcels, _ = setup_confirmed_roll(
        api,
        parcels=[
            {"apn": "A-1", "owner_name": "O1", "benefit_units": 60, "land_area_sqft": 4000, "front_footage_ft": 60},
            {"apn": "A-2", "owner_name": "O2", "benefit_units": 40, "land_area_sqft": 6000, "front_footage_ft": 40},
        ],
        formation_method="LAND_AREA", total_project_cost_cents=10_000_000, roll_method="LAND_AREA",
    )
    assert la_parcels[0]["assessed_principal_cents"] == 4000000
    assert la_parcels[0]["assessed_principal_cents"] != bu_parcels[0]["assessed_principal_cents"]


# --- apportionment: floor-then-distribute leftover-cent discipline ---

def test_apportionment_distributes_leftover_cents_to_earliest_parcels(api):
    """PRD §3.3: "For each parcel, its floored share is the largest whole number of cents
    not exceeding the assessable total multiplied by that parcel's weight divided by the
    denominator." PRD §3.3: "one extra cent is awarded to each parcel in order of descending
    weight, ties broken by earlier created_at first, until the remainder is exhausted."

    Design: Difficulty/combinatorial_formula/apportionment_floor_then_distribute_remainder_mode_b
    """
    _, parcels, _ = setup_confirmed_roll(
        api,
        parcels=[
            {"apn": "R-A", "owner_name": "OA", "benefit_units": 1},
            {"apn": "R-B", "owner_name": "OB", "benefit_units": 1},
            {"apn": "R-C", "owner_name": "OC", "benefit_units": 1},
        ],
        formation_method="BENEFIT_UNITS", total_project_cost_cents=10_000_001, roll_method="BENEFIT_UNITS",
    )
    assert parcels[0]["assessed_principal_cents"] == 3333334
    assert parcels[1]["assessed_principal_cents"] == 3333334
    assert parcels[2]["assessed_principal_cents"] == 3333333


def test_apportionment_shares_sum_back_to_assessable_total(api):
    """PRD §3.3: "Each parcel's assessed_principal_cents is its floored share plus any
    leftover cent it received, and the assessed principals sum back to the assessable total
    with no drift."

    Design: Difficulty/combinatorial_formula/apportionment_floor_then_distribute_remainder_mode_b
    """
    _, parcels, _ = setup_confirmed_roll(
        api,
        parcels=[
            {"apn": "R-A", "owner_name": "OA", "benefit_units": 1},
            {"apn": "R-B", "owner_name": "OB", "benefit_units": 1},
            {"apn": "R-C", "owner_name": "OC", "benefit_units": 1},
        ],
        formation_method="BENEFIT_UNITS", total_project_cost_cents=10_000_001, roll_method="BENEFIT_UNITS",
    )
    total = sum(p["assessed_principal_cents"] for p in parcels)
    assert total == 10000001


# --- protest ratio boundary: strict greater-than ---

def _open_two_parcel_district(api, threshold=50):
    district = create_district(api, name="DBD", formation_method="BENEFIT_UNITS",
                               total_project_cost_cents=1_000_000, protest_threshold_pct=threshold)
    px = add_parcel(api, district["id"], apn="X-1", owner_name="OX", benefit_units=50)
    py = add_parcel(api, district["id"], apn="Y-1", owner_name="OY", benefit_units=50)
    open_protest(api, district["id"])
    return district, px, py


def test_protest_ratio_exactly_at_threshold_forms_district(api):
    """PRD §3.1: "Majority protest occurs only when the ratio is strictly greater than the
    threshold fraction; a ratio exactly equal to the threshold is not a majority." PRD §3.1:
    "When the ratio does not exceed the threshold the district moves to FORMED and its
    formed_at is set to the current logical clock."

    Design: Difficulty/boundary_precision_check/protest_ratio_exactly_at_threshold_forms
    """
    from test_helpers import TEST_USERS
    district, px, _ = _open_two_parcel_district(api, threshold=50)
    validate_success(api.create_protest(px["id"], create_protest_payload(filed_by="OX"),
                                        make_parcel_owner_headers(px["id"])), 201)
    data = validate_success(api.close_hearing(district["id"], TEST_USERS["admin_headers"]))
    assert data["status"] == "FORMED"


def test_protest_ratio_strictly_above_threshold_abandons_district(api):
    """PRD §3.1: "Majority protest occurs only when the ratio is strictly greater than the
    threshold fraction." PRD §3.1: "When the ratio strictly exceeds the threshold the
    district moves to ABANDONED: every ACTIVE parcel cascades to WITHDRAWN."

    Design: Difficulty/boundary_precision_check/protest_ratio_exactly_at_threshold_forms
    """
    district, px, py = _open_two_parcel_district(api, threshold=50)
    validate_success(api.create_protest(px["id"], create_protest_payload(filed_by="OX"),
                                        make_parcel_owner_headers(px["id"])), 201)
    validate_success(api.create_protest(py["id"], create_protest_payload(filed_by="OY"),
                                        make_parcel_owner_headers(py["id"])), 201)
    from test_helpers import TEST_USERS
    data = validate_success(api.close_hearing(district["id"], TEST_USERS["admin_headers"]))
    assert data["status"] == "ABANDONED"


# --- corner: incidental cost default ---

def test_incidental_cost_defaults_to_zero_in_apportioned_total(api):
    """PRD §3.1: "incidental_cost_cents, the engineering and incidental costs folded into
    the assessable total, which defaults to 0". PRD §3.3: "the roll's total_apportioned_cents
    is fixed as the district's total_project_cost_cents plus its incidental_cost_cents".

    Design: Corner/entities/district_incidental_cost_defaults_to_zero
    """
    _, parcels, roll = setup_confirmed_roll(
        api,
        parcels=[{"apn": "E3-1", "owner_name": "O", "benefit_units": 100}],
        formation_method="BENEFIT_UNITS", total_project_cost_cents=500_000, roll_method="BENEFIT_UNITS",
        name="DE3",
    )
    assert roll["total_apportioned_cents"] == 500000
    assert parcels[0]["assessed_principal_cents"] == 500000


# --- corner: disclosure report ---

def test_disclosure_report_reflects_remaining_principal_and_lien(api):
    """PRD §3.9: "The report is computed on demand and returns the parcel's current
    remaining_principal_cents ... the lien_status, reflecting the state of the parcel's
    liens". PRD §3.9: "An ASSESSMENT lien is recorded, one per ACTIVE parcel, when a roll is
    confirmed ... and a new lien starts RECORDED."

    Design: Corner/endpoints/disclosure_report_reflects_remaining_principal
    """
    _, parcels, _ = setup_confirmed_roll(
        api,
        parcels=[{"apn": "E5-1", "owner_name": "O", "benefit_units": 100}],
        formation_method="BENEFIT_UNITS", total_project_cost_cents=1_000_000, roll_method="BENEFIT_UNITS",
        name="DE5",
    )
    from test_helpers import TEST_USERS
    report = validate_success(api.get_disclosure(parcels[0]["id"], TEST_USERS["auditor_headers"]))
    assert report["remaining_principal_cents"] == 1000000
    assert report["lien_status"] == "RECORDED"
