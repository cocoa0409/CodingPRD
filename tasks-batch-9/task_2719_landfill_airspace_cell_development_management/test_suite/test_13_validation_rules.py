"""Breadth over the validation rules: piggyback sequencing, scoped uniqueness, windows."""
from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import fixtures
from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_amount
from test_helpers.factories import cell_payload, leachate_shipment_payload
from test_helpers.test_users import TEST_USERS, make_site_operator_headers

ENV_MANAGER = TEST_USERS["environmental_manager_headers"]
AGENCY = TEST_USERS["regulatory_agency_headers"]

PARENT_CELL = {
    "cell_code": "C-1",
    "design_airspace_cy": 200,
    "design_area_sf": 120001,
    "liner_type": "DOUBLE_COMPOSITE",
}
CHILD_CELL = {
    "cell_code": "C-2",
    "design_airspace_cy": 200,
    "design_area_sf": 45001,
    "liner_type": "DOUBLE_COMPOSITE",
    "construction_start_date": "2026-08-01T00:00:00Z",
    "construction_end_date": "2026-09-01T00:00:00Z",
}


def test_a_cell_may_not_be_piggybacked_over_a_parent_that_is_still_open():
    """The reference is refused while the older cell has no final cover on it.

    The design recipe expects the reference to be accepted at creation and refused only at
    begin-construction, but rung 21 sits on `POST /cells` and §3.2 requires the parent to have
    reached `CLOSED` at creation time, so the refusal is asserted where the PRD puts it.

    PRD: "When it is supplied, the referenced cell must belong to the same landfill — a
    cross-site reference is refused with `ERR_CROSS_SITE_REFERENCE` — and it must already have
    reached `CLOSED`, because a cell may only be built over ground whose final cover is
    complete."

    Design: Corner/validations/construction_over_a_still_open_parent_cell_is_rejected
    """
    landfill = fixtures.create_landfill()
    site_headers = make_site_operator_headers(landfill["id"])
    parent = fixtures.create_cell(landfill["id"], **PARENT_CELL)
    assert parent["status"] == "DESIGN"

    response = api_client.create_cell(
        cell_payload(landfill["id"], piggyback_over_cell_id=parent["id"], **CHILD_CELL),
        site_headers,
    )

    validate_error(response, ApiErrorId.ERR_PIGGYBACK_PARENT_NOT_CLOSED.value, 409)
    _rows, meta = validate_paginated(
        api_client.list_cells(AGENCY, {"piggyback_over_cell_id": parent["id"]})
    )
    assert meta["total_count"] == 0, "the refused child must not have been stored"


def test_a_closed_parent_carries_its_piggyback_child_into_construction():
    """Once the cap is on the older cell, the vertical expansion is legal.

    PRD: "Breaking ground moves the cell from `DESIGN` to `UNDER_CONSTRUCTION`, and only the
    site's own `SiteOperator` may do it."

    Design: Corner/validations/construction_over_a_still_open_parent_cell_is_rejected
    """
    site = fixtures.setup_open_day(
        cell_overrides=dict(PARENT_CELL),
        day_overrides={
            "operating_date": "2026-08-01T00:00:00Z",
            "working_face_area_sf": 5000,
            "cover_material_type": "ALTERNATIVE_TARP",
        },
    )
    landfill_id = site["landfill"]["id"]
    fixtures.place_certified_load(landfill_id, site["day"]["id"], 166.60, hauler_ref="H-FILL")
    fixtures.close_operating_day(landfill_id, site["day"]["id"])
    parent = fixtures.close_cell(landfill_id, site["cell"]["id"])
    assert parent["status"] == "CLOSED"

    child = validate_success(
        api_client.create_cell(
            cell_payload(landfill_id, piggyback_over_cell_id=parent["id"], **CHILD_CELL),
            site["site_headers"],
        ),
        201,
    )

    assert child["piggyback_over_cell_id"] == parent["id"]
    rows, meta = validate_paginated(
        api_client.list_cells(AGENCY, {"piggyback_over_cell_id": parent["id"]})
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [child["id"]]
    started = fixtures.begin_construction(landfill_id, child["id"])
    assert started["status"] == "UNDER_CONSTRUCTION"


def test_the_same_cell_code_collides_inside_one_site_and_passes_across_two():
    """Only the landfill_id differs between the refused call and the accepted one.

    PRD: "A `permit_number` is unique across all landfills, else
    `ERR_DUPLICATE_PERMIT_NUMBER`; a `cell_code` is unique within its landfill, else
    `ERR_DUPLICATE_CELL_CODE`; an `operating_date` is unique within its landfill, else
    `ERR_DUPLICATE_OPERATING_DATE`; a `well_code` is unique across every cell of one landfill,
    else `ERR_DUPLICATE_WELL_CODE`; an `estimate_year` is unique within its landfill, else
    `ERR_DUPLICATE_ESTIMATE_YEAR`."

    Design: Corner/validations/the_same_cell_code_in_two_landfills_is_accepted
    """
    lfa = fixtures.create_landfill()
    lfb = fixtures.create_landfill(name="Eastbank MSW", permit_number="MSW-9902")
    first = fixtures.create_cell(
        lfa["id"],
        cell_code="C-1",
        design_airspace_cy=1000000,
        design_area_sf=120001,
        liner_type="DOUBLE_COMPOSITE",
    )

    validate_error(
        api_client.create_cell(
            cell_payload(
                lfa["id"],
                cell_code="C-1",
                design_airspace_cy=500,
                design_area_sf=45001,
                liner_type="GCL_ONLY",
            ),
            make_site_operator_headers(lfa["id"]),
        ),
        ApiErrorId.ERR_DUPLICATE_CELL_CODE.value,
        409,
    )
    second = validate_success(
        api_client.create_cell(
            cell_payload(
                lfb["id"],
                cell_code="C-1",
                design_airspace_cy=500,
                design_area_sf=45001,
                liner_type="GCL_ONLY",
            ),
            make_site_operator_headers(lfb["id"]),
        ),
        201,
    )

    assert second["cell_code"] == "C-1"
    assert second["id"] != first["id"]
    assert second["landfill_id"] == lfb["id"]
    for landfill_id in (lfa["id"], lfb["id"]):
        _rows, meta = validate_paginated(
            api_client.list_cells(AGENCY, {"landfill_id": landfill_id})
        )
        assert meta["total_count"] == 1


FEE_SCHEDULE = {
    "posted_tipping_fee_per_ton": 42.50,
    "host_fee_per_ton": 3.75,
    "tier1_monthly_tons": 100,
    "royalty_tier1_pct": 0.04,
    "royalty_tier2_pct": 0.07,
}
BIG_CELL = {"cell_code": "C-1", "design_airspace_cy": 1000000, "design_area_sf": 120001}


def _day_past_an_expired_profile():
    """An OPEN day on 2026-08-05 over a profile whose window closed on 2026-07-31."""
    site = fixtures.setup_active_site(
        cell_overrides=dict(BIG_CELL), agreement_overrides=dict(FEE_SCHEDULE)
    )
    landfill_id = site["landfill"]["id"]
    site["approval"] = fixtures.setup_approved_special_waste(
        landfill_id,
        generator_name="Ridgeview Plating Co",
        waste_code="IS-4410",
        profile_stream="INDUSTRIAL_SPECIAL",
        approved_tons_cap=500,
        effective_from="2026-01-01T00:00:00Z",
        expires_on="2026-07-31T00:00:00Z",
    )
    assert site["approval"]["status"] == "APPROVED"
    fixtures.set_clock("2026-08-05T06:00:00Z")
    site["day"] = fixtures.open_operating_day(
        landfill_id,
        site["cell"]["id"],
        operating_date="2026-08-05T00:00:00Z",
        working_face_area_sf=5000,
        cover_material_type="ALTERNATIVE_TARP",
    )
    return site


def test_a_load_on_a_profile_whose_window_has_passed_cannot_be_cleared():
    """The profile is APPROVED with an untouched cap; only the calendar has moved.

    PRD: "If the load references an approval, that approval must currently be `APPROVED` with
    its `effective_from` at or before the current logical clock and its `expires_on` strictly
    after the current logical clock; an approval sitting in `REQUESTED`, `DENIED`, `REVOKED`,
    `SUSPENDED` or `EXHAUSTED`, or one whose window has passed, is refused with
    `ERR_APPROVAL_EXPIRED`."

    Design: Corner/validations/an_expired_special_waste_approval_cannot_clear_screening
    """
    site = _day_past_an_expired_profile()
    load = fixtures.receive_load(
        site["landfill"]["id"],
        site["day"]["id"],
        hauler_ref="H-1",
        waste_stream="INDUSTRIAL_SPECIAL",
        manifest_tons=20.00,
        special_waste_approval_id=site["approval"]["id"],
    )

    response = api_client.clear_screening(load["id"], None, site["scale_headers"])

    validate_error(response, ApiErrorId.ERR_APPROVAL_EXPIRED.value, 422)
    unchanged = get_success_data(api_client.get_waste_load(load["id"], site["scale_headers"]))
    assert unchanged["screening_status"] == "PENDING"
    assert unchanged["billing_status"] == "UNBILLED"
    assert unchanged["gate_charge_amount"] is None
    approval = get_success_data(
        api_client.get_special_waste_approval(site["approval"]["id"], ENV_MANAGER)
    )
    assert approval["status"] == "APPROVED"
    assert_amount(approval["consumed_tons"], 0, "consumed tons")


def test_the_same_day_still_clears_an_ordinary_load_with_no_profile():
    """The refusal is specific to the expired reference, not to the day or the site.

    PRD: "Special-waste streams travel on a profile. When `waste_stream` is
    `INDUSTRIAL_SPECIAL` or `ASBESTOS_SPECIAL`, the receipt **must** carry
    `special_waste_approval_id`; when the stream is `MSW` or `CD` the field must be omitted
    entirely."

    Design: Corner/validations/an_expired_special_waste_approval_cannot_clear_screening
    """
    site = _day_past_an_expired_profile()
    ordinary = fixtures.receive_load(
        site["landfill"]["id"],
        site["day"]["id"],
        hauler_ref="H-2",
        waste_stream="MSW",
        manifest_tons=30.00,
    )

    cleared = fixtures.clear_screening(site["landfill"]["id"], ordinary["id"])

    assert cleared["screening_status"] == "CLEARED"
    assert_amount(cleared["gate_charge_amount"], 1387.50, "gate charge")


NARROW_ENVELOPE = {
    "facility_name": "Narrow POTW",
    "daily_gallon_cap": 20000,
    "base_haul_fee": 350.00,
    "treatment_rate_per_kgal": 62.50,
    "effective_from": "2026-01-01T00:00:00Z",
    "expires_on": "2026-12-31T00:00:00Z",
}


def _two_contracts_each_with_one_morning_haul():
    """TA-1 holds one slot, TA-2 takes the declared default of two."""
    landfill = fixtures.create_landfill()
    narrow = fixtures.register_treatment_agreement(
        landfill["id"], concurrent_slot_capacity=1, **NARROW_ENVELOPE
    )
    wide_envelope = dict(NARROW_ENVELOPE, facility_name="Valley POTW")
    wide = fixtures.register_treatment_agreement(landfill["id"], **wide_envelope)
    assert int(narrow["concurrent_slot_capacity"]) == 1
    assert int(wide["concurrent_slot_capacity"]) == 2
    for agreement in (narrow, wide):
        fixtures.book_shipment(
            landfill["id"],
            agreement["id"],
            gallons=2000,
            window_start="2026-08-01T08:00:00Z",
            window_end="2026-08-01T12:00:00Z",
        )
    return landfill, narrow, wide


def _book(landfill_id, agreement_id, window_start, window_end):
    return api_client.create_leachate_shipment(
        leachate_shipment_payload(
            agreement_id, gallons=2000, window_start=window_start, window_end=window_end
        ),
        make_site_operator_headers(landfill_id),
    )


def test_the_identical_overlap_is_refused_at_one_slot_and_accepted_at_two():
    """The gate reads the agreement's own capacity and counts per agreement.

    PRD: "First, the number of shipments of that agreement in `SCHEDULED`, `DISPATCHED` or
    `ACCEPTED` whose windows overlap the requested one, counting the new shipment itself, may
    not exceed `concurrent_slot_capacity`; exceeding it is refused with
    `ERR_SLOT_CAPACITY_EXCEEDED`."

    Design: Corner/validations/slot_capacity_one_rejects_the_overlap_that_capacity_two_accepts
    """
    landfill, narrow, wide = _two_contracts_each_with_one_morning_haul()

    refused = _book(
        landfill["id"], narrow["id"], "2026-08-01T10:00:00Z", "2026-08-01T14:00:00Z"
    )
    accepted = _book(
        landfill["id"], wide["id"], "2026-08-01T10:00:00Z", "2026-08-01T14:00:00Z"
    )

    validate_error(refused, ApiErrorId.ERR_SLOT_CAPACITY_EXCEEDED.value, 409)
    booked = validate_success(accepted, 201)
    assert booked["status"] == "SCHEDULED"
    assert booked["treatment_agreement_id"] == wide["id"]
    reread = get_success_data(api_client.get_treatment_agreement(wide["id"], ENV_MANAGER))
    assert_amount(reread["scheduled_gallons_today"], 4000, "scheduled gallons today")


def test_a_window_that_merely_touches_another_occupies_no_slot():
    """Half-open windows do not overlap at the shared instant, even at one slot.

    PRD: "The window is **half-open**: it includes its start instant and excludes its end
    instant, `window_end` must be strictly after `window_start`, and both must fall on the
    same UTC calendar date."

    Design: Corner/validations/slot_capacity_one_rejects_the_overlap_that_capacity_two_accepts
    """
    landfill, narrow, _wide = _two_contracts_each_with_one_morning_haul()

    touching = _book(
        landfill["id"], narrow["id"], "2026-08-01T12:00:00Z", "2026-08-01T16:00:00Z"
    )

    booked = validate_success(touching, 201)
    assert booked["status"] == "SCHEDULED"
    reread = get_success_data(api_client.get_treatment_agreement(narrow["id"], ENV_MANAGER))
    assert_amount(reread["scheduled_gallons_today"], 4000, "scheduled gallons today")
