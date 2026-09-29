"""Requests that violate two rungs at once, where only the error id reveals the order."""
from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import fixtures
from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_amount
from test_helpers.test_users import TEST_USERS

ENV_MANAGER = TEST_USERS["environmental_manager_headers"]
AGENCY = TEST_USERS["regulatory_agency_headers"]

FEE_SCHEDULE = {
    "posted_tipping_fee_per_ton": 42.5,
    "host_fee_per_ton": 3.75,
    "tier1_monthly_tons": 100,
    "royalty_tier1_pct": 0.04,
    "royalty_tier2_pct": 0.07,
}


def _day_with_a_capped_profile():
    """An open day plus an approved profile capped at 100 tons and unconsumed."""
    site = fixtures.setup_open_day(
        agreement_overrides=dict(FEE_SCHEDULE),
        day_overrides={
            "operating_date": "2026-08-05T00:00:00Z",
            "working_face_area_sf": 5000,
            "cover_material_type": "ALTERNATIVE_TARP",
        },
    )
    site["approval"] = fixtures.setup_approved_special_waste(
        site["landfill"]["id"],
        waste_code="IND-221",
        approved_tons_cap=100,
        effective_from="2026-01-01T00:00:00Z",
        expires_on="2027-01-01T00:00:00Z",
    )
    return site


def _special_load(site, hauler_ref, manifest_tons, load_check_result):
    return fixtures.receive_load(
        site["landfill"]["id"],
        site["day"]["id"],
        special_waste_approval_id=site["approval"]["id"],
        hauler_ref=hauler_ref,
        waste_stream="INDUSTRIAL_SPECIAL",
        manifest_tons=manifest_tons,
        load_check_result=load_check_result,
    )


def test_the_prohibited_material_check_outranks_the_tonnage_cap():
    """One clearance breaches both 422 rules; the regulatory one must be reported.

    PRD: "11. **Prohibited-material load check** — on
    `POST /waste-loads/{waste_load_id}/clear-screening`. This is a regulatory rung and it
    outranks every fiscal rung below. Failure: `ERR_PROHIBITED_MATERIAL` (422)."

    Design: Difficulty/priority_pair_validation_conflict/prohibited_material_outranks_special_waste_tonnage_cap
    """
    site = _day_with_a_capped_profile()
    load = _special_load(site, "H-X", 150.0, "UNMANIFESTED")

    response = api_client.clear_screening(load["id"], None, site["scale_headers"])

    validate_error(response, ApiErrorId.ERR_PROHIBITED_MATERIAL.value, 422)
    unchanged = get_success_data(api_client.get_waste_load(load["id"], site["scale_headers"]))
    assert unchanged["screening_status"] == "PENDING"
    assert unchanged["billing_status"] == "UNBILLED"


def test_the_tonnage_cap_is_live_once_the_material_check_passes():
    """A clean load over the cap isolates the fiscal rung.

    PRD: "25. **Special-waste tonnage cap** — on
    `POST /waste-loads/{waste_load_id}/clear-screening`. Failure:
    `ERR_APPROVAL_TONNAGE_CAP_EXCEEDED` (422)."

    Design: Difficulty/priority_pair_validation_conflict/prohibited_material_outranks_special_waste_tonnage_cap
    """
    site = _day_with_a_capped_profile()
    load = _special_load(site, "H-Y", 150.0, "PASS")

    response = api_client.clear_screening(load["id"], None, site["scale_headers"])

    validate_error(response, ApiErrorId.ERR_APPROVAL_TONNAGE_CAP_EXCEEDED.value, 422)
    unchanged = get_success_data(api_client.get_waste_load(load["id"], site["scale_headers"]))
    assert unchanged["screening_status"] == "PENDING"


def test_a_load_landing_exactly_on_the_cap_is_cleared_and_consumes_it():
    """Exact equality with the cap is allowed and moves the profile's ledger only.

    PRD: "And finally, if the load references an approval, that approval's `consumed_tons`
    plus this load's `manifest_tons` may not exceed its `approved_tons_cap`; exact equality
    with the cap is allowed, and anything beyond it is refused with
    `ERR_APPROVAL_TONNAGE_CAP_EXCEEDED`."

    Design: Difficulty/priority_pair_validation_conflict/prohibited_material_outranks_special_waste_tonnage_cap
    """
    site = _day_with_a_capped_profile()
    load = _special_load(site, "H-Z", 100.0, "PASS")

    cleared = fixtures.clear_screening(site["landfill"]["id"], load["id"])

    assert cleared["screening_status"] == "CLEARED"
    assert_amount(cleared["gate_charge_amount"], 4625.00, "gate charge")
    approval = get_success_data(
        api_client.get_special_waste_approval(site["approval"]["id"], ENV_MANAGER)
    )
    assert_amount(approval["consumed_tons"], 100.00, "consumed tons")
    assert approval["status"] == "APPROVED", (
        "exhaustion belongs to the day close, not to screening"
    )


def _certified_cell_with_an_open_exceedance():
    """A QA-certified cell on a site that is both unfunded and in corrective action."""
    landfill = fixtures.create_landfill()
    certified = fixtures.setup_qa_certified_cell(landfill["id"])
    scan = fixtures.record_surface_scan(
        landfill["id"],
        scanned_on="2026-08-01T00:00:00Z",
        grid_points_count=180,
        max_reading_ppm=500.0,
        exceedance_point_ref="GRID-002",
    )
    assert scan["status"] == "EXCEEDANCE_OPEN"
    assert scan["corrective_well_id"] is None
    posture = fixtures.read_landfill(landfill["id"])
    assert posture["gas_collection_status"] == "CORRECTIVE_ACTION"
    assert posture["financial_assurance_status"] == "UNFUNDED"
    return landfill, certified["cell"], scan


def test_the_gas_corrective_action_rung_outranks_the_assurance_shortfall():
    """Both blockers are live, and the 409 environmental one is reported first.

    PRD: "14. **Landfill-gas corrective action** — on
    `POST /cells/{cell_id}/authorize-waste-placement` and `POST /cells/{cell_id}/activate`.
    While the site's `gas_collection_status` is `CORRECTIVE_ACTION`, no cell of that site may
    be authorized for waste placement and no cell may be activated. Failure:
    `ERR_GAS_CORRECTIVE_ACTION_OPEN` (409)."

    Design: Difficulty/priority_pair_validation_conflict/gas_corrective_action_outranks_financial_assurance_shortfall
    """
    _landfill, cell, _scan = _certified_cell_with_an_open_exceedance()

    response = api_client.authorize_waste_placement(
        cell["id"], {"approval_reference": "AGY-2026-77"}, AGENCY
    )

    validate_error(response, ApiErrorId.ERR_GAS_CORRECTIVE_ACTION_OPEN.value, 409)


def test_resolving_the_exceedance_exposes_the_funding_blocker_underneath():
    """The lower rung was live all along, and it answers with a different status code.

    PRD: "27. **Financial assurance for closure and post-closure care** — on
    `POST /cells/{cell_id}/authorize-waste-placement`. Failure:
    `ERR_FINANCIAL_ASSURANCE_SHORTFALL` (402)."

    Design: Difficulty/priority_pair_validation_conflict/gas_corrective_action_outranks_financial_assurance_shortfall
    """
    landfill, cell, scan = _certified_cell_with_an_open_exceedance()

    resolved = fixtures.resolve_surface_scan(
        scan["id"], "Cover regraded; no wellfield exists yet."
    )
    assert resolved["status"] == "RESOLVED"
    assert fixtures.read_landfill(landfill["id"])["gas_collection_status"] == "COMPLIANT"

    response = api_client.authorize_waste_placement(
        cell["id"], {"approval_reference": "AGY-2026-77"}, AGENCY
    )

    validate_error(response, ApiErrorId.ERR_FINANCIAL_ASSURANCE_SHORTFALL.value, 402)


def test_clearing_both_blockers_lets_the_identical_request_through():
    """Three different outcomes from one unchanged authorization request.

    PRD: "On success the acting agency principal's `X-User-ID` is written to the cell's
    `authorized_by_agency_user_id` and the cell's `version` is incremented by 1."

    Design: Difficulty/priority_pair_validation_conflict/gas_corrective_action_outranks_financial_assurance_shortfall
    """
    landfill, cell, scan = _certified_cell_with_an_open_exceedance()
    fixtures.resolve_surface_scan(scan["id"], "Cover regraded; no wellfield exists yet.")
    estimate = fixtures.setup_funded_assurance(landfill["id"])
    assert_amount(estimate["required_assurance_amount"], 4742266.36, "required assurance")

    authorized = fixtures.authorize_waste_placement(cell["id"], "AGY-2026-77")

    assert authorized["status"] == "READY_FOR_WASTE"
    assert authorized["authorized_by_agency_user_id"] == "agency-inspector-1"


TREATMENT_ENVELOPE = {
    "daily_gallon_cap": 20000,
    "base_haul_fee": 350.0,
    "treatment_rate_per_kgal": 62.5,
    "concurrent_slot_capacity": 2,
}


def _agreement_with_two_overlapping_hauls():
    """Both slots are taken across 11:00 and 8,000 of 20,000 gallons are still free."""
    fixtures.set_clock("2026-08-05T06:00:00Z")
    landfill = fixtures.create_landfill()
    agreement = fixtures.register_treatment_agreement(landfill["id"], **TREATMENT_ENVELOPE)
    first = fixtures.book_shipment(
        landfill["id"],
        agreement["id"],
        gallons=8000,
        window_start="2026-08-05T08:00:00Z",
        window_end="2026-08-05T12:00:00Z",
    )
    second = fixtures.book_shipment(
        landfill["id"],
        agreement["id"],
        gallons=4000,
        window_start="2026-08-05T10:00:00Z",
        window_end="2026-08-05T14:00:00Z",
    )
    return landfill, agreement, first, second


def _book(landfill_id, agreement_id, window_start, window_end, gallons=9000):
    from test_helpers.factories import leachate_shipment_payload
    from test_helpers.test_users import make_site_operator_headers

    return api_client.create_leachate_shipment(
        leachate_shipment_payload(
            agreement_id,
            gallons=gallons,
            window_start=window_start,
            window_end=window_end,
        ),
        make_site_operator_headers(landfill_id),
    )


def test_the_slot_ceiling_outranks_the_daily_gallon_ceiling():
    """A third overlapping 9,000-gallon haul breaches both ceilings; slots answer first.

    PRD: "26. **Leachate daily gallon cap** — on `POST /leachate-shipments`, and evaluated
    only after rung 19, so a booking that breaches both reports the slot-capacity error.
    Failure: `ERR_DAILY_GALLON_CAP_EXCEEDED` (422)."

    Design: Difficulty/priority_pair_validation_conflict/slot_capacity_outranks_daily_gallon_cap
    """
    landfill, agreement, _first, _second = _agreement_with_two_overlapping_hauls()

    response = _book(
        landfill["id"], agreement["id"], "2026-08-05T11:00:00Z", "2026-08-05T13:00:00Z"
    )

    validate_error(response, ApiErrorId.ERR_SLOT_CAPACITY_EXCEEDED.value, 409)


def test_a_haul_outside_every_window_isolates_the_gallon_ceiling():
    """The same 9,000 gallons booked overnight take no slot and still overrun the cap.

    PRD: "Second, `scheduled_gallons_today` for that agreement on the calendar date of the
    requested `window_start`, plus the requested `gallons`, may not exceed
    `daily_gallon_cap`; exact equality with the cap is allowed, and exceeding it is refused
    with `ERR_DAILY_GALLON_CAP_EXCEEDED`."

    Design: Difficulty/priority_pair_validation_conflict/slot_capacity_outranks_daily_gallon_cap
    """
    landfill, agreement, _first, _second = _agreement_with_two_overlapping_hauls()

    response = _book(
        landfill["id"], agreement["id"], "2026-08-05T20:00:00Z", "2026-08-05T22:00:00Z"
    )

    validate_error(response, ApiErrorId.ERR_DAILY_GALLON_CAP_EXCEEDED.value, 422)


def test_neither_refusal_moved_the_booked_gallon_ledger():
    """Two rejected bookings leave the contract exactly where the two accepted ones left it.

    PRD: "`scheduled_gallons_today` is a derivation, not a counter: at any moment it is the
    sum of `gallons` over the shipments of that agreement which are in `SCHEDULED`,
    `DISPATCHED` or `ACCEPTED` and whose `window_start` falls on the current logical clock's
    UTC calendar date."

    Design: Difficulty/priority_pair_validation_conflict/slot_capacity_outranks_daily_gallon_cap
    """
    landfill, agreement, first, second = _agreement_with_two_overlapping_hauls()
    _book(landfill["id"], agreement["id"], "2026-08-05T11:00:00Z", "2026-08-05T13:00:00Z")
    _book(landfill["id"], agreement["id"], "2026-08-05T20:00:00Z", "2026-08-05T22:00:00Z")

    reread = get_success_data(
        api_client.get_treatment_agreement(agreement["id"], ENV_MANAGER)
    )

    assert_amount(reread["scheduled_gallons_today"], 12000, "scheduled gallons today")
    for shipment in (first, second):
        current = get_success_data(
            api_client.get_leachate_shipment(shipment["id"], ENV_MANAGER)
        )
        assert current["status"] == "SCHEDULED"


SMALL_CELL = {"cell_code": "C-A", "design_airspace_cy": 200, "design_area_sf": 45001}
DAY_SHAPE = {"working_face_area_sf": 5000, "cover_material_type": "ALTERNATIVE_TARP"}


def _two_sites_with_a_day_over_a_non_active_cell():
    """LF-A carries an OPEN day whose working face has since gone FULL.

    A cell must be `ACTIVE` when a day is opened, so the only PRD-reachable way for an open
    day to name a non-`ACTIVE` face is to fill that face afterwards: a second, closed day
    drives C-A to exactly 98 percent. A second `ACTIVE` cell keeps the site itself `OPEN`,
    so rung 10(a) stays satisfied and only rung 10(b) is in play.
    """
    lfa = fixtures.create_landfill()
    face = fixtures.setup_qa_certified_cell(lfa["id"], cell_overrides=SMALL_CELL)["cell"]
    spare = fixtures.setup_qa_certified_cell(
        lfa["id"], cell_overrides={"cell_code": "C-B"}
    )["cell"]
    fixtures.setup_funded_assurance(lfa["id"])
    for cell, reference in ((face, "AGY-2026-A7"), (spare, "AGY-2026-B7")):
        fixtures.authorize_waste_placement(cell["id"], reference)
        fixtures.activate_cell(lfa["id"], cell["id"])
    fixtures.setup_executed_host_agreement(lfa["id"])
    approval_a = fixtures.setup_approved_special_waste(lfa["id"], waste_code="IND-221")

    lfb = fixtures.create_landfill(name="Eastbank MSW", permit_number="MSW-8802")
    approval_b = fixtures.setup_approved_special_waste(lfb["id"], waste_code="IND-221")

    day = fixtures.open_operating_day(
        lfa["id"], face["id"], operating_date="2026-08-05T00:00:00Z", **DAY_SHAPE
    )
    filler = fixtures.open_operating_day(
        lfa["id"], face["id"], operating_date="2026-08-06T00:00:00Z", **DAY_SHAPE
    )
    fixtures.place_certified_load(lfa["id"], filler["id"], 166.60, hauler_ref="H-FILL")
    fixtures.close_operating_day(lfa["id"], filler["id"])

    assert fixtures.read_landfill(lfa["id"])["operating_status"] == "OPEN"
    assert get_success_data(api_client.get_cell(face["id"], AGENCY))["status"] == "FULL"
    return {
        "lfa": lfa,
        "spare": spare,
        "day": day,
        "approval_a": approval_a,
        "approval_b": approval_b,
    }


def _cross_site_load(landfill_id, day_id, approval_id, hauler_ref):
    from test_helpers.factories import waste_load_payload
    from test_helpers.test_users import make_scale_operator_headers

    return api_client.create_waste_load(
        waste_load_payload(
            day_id,
            special_waste_approval_id=approval_id,
            hauler_ref=hauler_ref,
            waste_stream="INDUSTRIAL_SPECIAL",
            manifest_tons=30.0,
        ),
        make_scale_operator_headers(landfill_id),
    )


def test_the_cross_site_reference_outranks_the_non_active_working_face():
    """Both 409 rules are violated, and only the referential one may be reported.

    PRD: "The named approval must belong to the same landfill as the operating day, and its
    `profile_stream` must equal the load's `waste_stream`; a mismatch on either count is
    refused with `ERR_CROSS_SITE_REFERENCE`."

    Design: Difficulty/priority_pair_validation_conflict/cross_site_reference_outranks_cell_not_accepting_waste
    """
    world = _two_sites_with_a_day_over_a_non_active_cell()

    response = _cross_site_load(
        world["lfa"]["id"], world["day"]["id"], world["approval_b"]["id"], "H-CROSS"
    )

    validate_error(response, ApiErrorId.ERR_CROSS_SITE_REFERENCE.value, 409)


def test_a_same_site_profile_isolates_the_working_face_refusal():
    """Removing the referential defect exposes the gating rung underneath it.

    PRD: "The owning site must be `OPEN` or `RESTRICTED_AIRSPACE`, else
    `ERR_SITE_NOT_ACCEPTING_WASTE`; the cell named as the day's working face must be
    `ACTIVE`, else `ERR_CELL_NOT_ACCEPTING_WASTE`."

    Design: Difficulty/priority_pair_validation_conflict/cross_site_reference_outranks_cell_not_accepting_waste
    """
    world = _two_sites_with_a_day_over_a_non_active_cell()

    response = _cross_site_load(
        world["lfa"]["id"], world["day"]["id"], world["approval_a"]["id"], "H-SAME"
    )

    validate_error(response, ApiErrorId.ERR_CELL_NOT_ACCEPTING_WASTE.value, 409)


def test_a_same_site_profile_over_an_active_face_is_received():
    """Neither rung blocks the same truck once both defects are gone.

    PRD: "A new load row starts with `screening_status` `PENDING` and `billing_status`
    `UNBILLED`."

    Design: Difficulty/priority_pair_validation_conflict/cross_site_reference_outranks_cell_not_accepting_waste
    """
    world = _two_sites_with_a_day_over_a_non_active_cell()
    open_face_day = fixtures.open_operating_day(
        world["lfa"]["id"],
        world["spare"]["id"],
        operating_date="2026-08-07T00:00:00Z",
        **DAY_SHAPE,
    )

    response = _cross_site_load(
        world["lfa"]["id"], open_face_day["id"], world["approval_a"]["id"], "H-SAME"
    )

    load = get_success_data(response)
    assert load["screening_status"] == "PENDING"
    assert load["billing_status"] == "UNBILLED"
    assert load["operating_day_id"] == open_face_day["id"]
