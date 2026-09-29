"""One unchanged request, answered differently as entities two levels away move."""
from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import fixtures
from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_amount
from test_helpers.test_users import (
    TEST_USERS,
    make_scale_operator_headers,
    make_site_operator_headers,
)

PLATFORM_ADMIN = TEST_USERS["platform_admin_headers"]
ENV_MANAGER = TEST_USERS["environmental_manager_headers"]
AGENCY = TEST_USERS["regulatory_agency_headers"]
FINANCE_FILER = TEST_USERS["finance_filer_headers"]

SMALL_CELL = {"design_airspace_cy": 200, "design_area_sf": 45001}
DAY_SHAPE = {"working_face_area_sf": 5000, "cover_material_type": "ALTERNATIVE_TARP"}


def _site_whose_only_active_cell_just_filled():
    """C-2 is FULL, C-3 is authorized but idle, and a PENDING truck waits on C-2's day.

    The second day and its truck are created while C-2 is still `ACTIVE`, because both a
    day and a receipt require an `ACTIVE` working face; the fill happens afterwards when
    the first day closes.
    """
    landfill = fixtures.create_landfill()
    working = fixtures.setup_qa_certified_cell(
        landfill["id"],
        cell_overrides=dict(SMALL_CELL, cell_code="C-2",
                            construction_end_date="2026-07-20T00:00:00Z"),
    )["cell"]
    idle = fixtures.setup_qa_certified_cell(
        landfill["id"],
        cell_overrides=dict(SMALL_CELL, cell_code="C-3",
                            construction_end_date="2026-07-24T00:00:00Z"),
    )["cell"]
    fixtures.setup_funded_assurance(landfill["id"])
    fixtures.authorize_waste_placement(working["id"], "AGY-2026-C2")
    fixtures.authorize_waste_placement(idle["id"], "AGY-2026-C3")
    fixtures.activate_cell(landfill["id"], working["id"])
    fixtures.setup_executed_host_agreement(landfill["id"])

    filling_day = fixtures.open_operating_day(
        landfill["id"], working["id"], operating_date="2026-08-05T00:00:00Z", **DAY_SHAPE
    )
    fixtures.place_certified_load(
        landfill["id"], filling_day["id"], 166.60, hauler_ref="H-1", manifest_tons=166.6
    )
    waiting_day = fixtures.open_operating_day(
        landfill["id"], working["id"], operating_date="2026-08-06T00:00:00Z", **DAY_SHAPE
    )
    waiting_load = fixtures.receive_load(
        landfill["id"], waiting_day["id"], hauler_ref="H-2", manifest_tons=30.0
    )
    fixtures.close_operating_day(landfill["id"], filling_day["id"])

    assert get_success_data(api_client.get_cell(working["id"], AGENCY))["status"] == "FULL"
    site = fixtures.read_landfill(landfill["id"])
    assert site["active_cell_count"] == 0
    assert site["operating_status"] == "SUSPENDED_NO_AIRSPACE"
    return {
        "landfill": landfill,
        "working": working,
        "idle": idle,
        "day": waiting_day,
        "load": waiting_load,
    }


def test_the_site_level_gate_answers_before_the_cell_level_one():
    """Both the site and the cell are unfit, and only the site error may be reported.

    PRD: "The site must be `OPEN` or `RESTRICTED_AIRSPACE`, else
    `ERR_SITE_NOT_ACCEPTING_WASTE`."

    Design: Difficulty/cross_entity_state_dependency/load_clearance_depends_on_landfill_and_cell_states_in_fixed_order
    """
    world = _site_whose_only_active_cell_just_filled()

    response = api_client.clear_screening(
        world["load"]["id"], None, make_scale_operator_headers(world["landfill"]["id"])
    )

    validate_error(response, ApiErrorId.ERR_SITE_NOT_ACCEPTING_WASTE.value, 409)


def test_a_site_with_no_active_cell_cannot_be_reopened_administratively():
    """The posture is a consequence of the cell set, so it cannot be waved away.

    PRD: "If the site is currently `SUSPENDED_NO_AIRSPACE`, its `active_cell_count` must be
    greater than zero, otherwise the move is refused with `ERR_INVALID_STATE_TRANSITION`."

    Design: Difficulty/cross_entity_state_dependency/load_clearance_depends_on_landfill_and_cell_states_in_fixed_order
    """
    world = _site_whose_only_active_cell_just_filled()

    response = api_client.set_operating_status(
        world["landfill"]["id"], {"operating_status": "OPEN"}, PLATFORM_ADMIN
    )

    validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, 409)


def test_activating_a_sibling_cell_exposes_the_cell_level_refusal():
    """Opening C-3 reopens the site but does nothing for the day pinned to C-2.

    PRD: "The cell named by the day's `active_cell_id` must be `ACTIVE`, else
    `ERR_CELL_NOT_ACCEPTING_WASTE`."

    Design: Difficulty/cross_entity_state_dependency/load_clearance_depends_on_landfill_and_cell_states_in_fixed_order
    """
    world = _site_whose_only_active_cell_just_filled()

    activated = fixtures.activate_cell(world["landfill"]["id"], world["idle"]["id"])

    assert activated["status"] == "ACTIVE"
    site = fixtures.read_landfill(world["landfill"]["id"])
    assert site["operating_status"] == "OPEN"
    assert site["active_cell_count"] == 1

    response = api_client.clear_screening(
        world["load"]["id"], None, make_scale_operator_headers(world["landfill"]["id"])
    )

    validate_error(response, ApiErrorId.ERR_CELL_NOT_ACCEPTING_WASTE.value, 409)
    unchanged = get_success_data(
        api_client.get_waste_load(world["load"]["id"], AGENCY)
    )
    assert unchanged["screening_status"] == "PENDING"
    assert unchanged["billing_status"] == "UNBILLED"


def test_an_identical_load_against_the_newly_active_cell_clears():
    """Nothing about the truck changed; only which cell carries the face.

    PRD: "It bills the *manifest* tonnage: the gross is `manifest_tons` multiplied by
    `posted_tipping_fee_per_ton`, rounded to 2 decimal places; the host fee is
    `manifest_tons` multiplied by `host_fee_per_ton`, also rounded to 2 decimal places; and
    `gate_charge_amount` is the sum of those two already-rounded components, rounded again
    to 2 decimal places."

    Design: Difficulty/cross_entity_state_dependency/load_clearance_depends_on_landfill_and_cell_states_in_fixed_order
    """
    world = _site_whose_only_active_cell_just_filled()
    fixtures.activate_cell(world["landfill"]["id"], world["idle"]["id"])

    fresh_day = fixtures.open_operating_day(
        world["landfill"]["id"],
        world["idle"]["id"],
        operating_date="2026-08-07T00:00:00Z",
        **DAY_SHAPE,
    )
    fresh_load = fixtures.receive_load(
        world["landfill"]["id"], fresh_day["id"], hauler_ref="H-3", manifest_tons=30.0
    )
    cleared = fixtures.clear_screening(world["landfill"]["id"], fresh_load["id"])

    assert cleared["screening_status"] == "CLEARED"
    assert_amount(cleared["gate_charge_amount"], 1387.50, "gate charge")


def _funded_site_with_a_drilled_well():
    """A QA-certified cell, a funded assurance position, and one fresh well on it."""
    landfill = fixtures.create_landfill()
    cell = fixtures.setup_qa_certified_cell(landfill["id"])["cell"]
    fixtures.setup_funded_assurance(landfill["id"], instrument_type="INSURANCE")
    well = fixtures.drill_gas_well(cell["id"])
    assert well["status"] == "DRILLED"
    return landfill, cell, well


def test_a_well_on_a_qa_certified_cell_has_no_gas_to_collect():
    """A liner-certified cell has never received waste, so the header stays shut.

    PRD: "The parent cell must be `ACTIVE`, `FULL` or `CLOSED`; a cell that has not yet
    begun receiving waste has no gas to collect and the connection is refused with
    `ERR_CELL_NOT_READY_FOR_WELLFIELD`."

    Design: Difficulty/cross_entity_state_dependency/gas_well_connect_requires_cell_past_authorization
    """
    _landfill, _cell, well = _funded_site_with_a_drilled_well()

    response = api_client.connect_gas_well(well["id"], ENV_MANAGER)

    validate_error(response, ApiErrorId.ERR_CELL_NOT_READY_FOR_WELLFIELD.value, 409)


def test_regulatory_authorization_alone_does_not_open_the_wellfield():
    """READY_FOR_WASTE is not in the permitted set, and the refusal touches nothing.

    PRD: "10. **Cross-entity gating states**, evaluated in this fixed internal order: (a) the
    owning landfill's `operating_status` must be `OPEN` or `RESTRICTED_AIRSPACE` for a load
    to be cleared, else `ERR_SITE_NOT_ACCEPTING_WASTE`; (b) the target cell must be `ACTIVE`
    for a load to be cleared and must be `ACTIVE`, `FULL` or `CLOSED` for a gas well to be
    connected, else `ERR_CELL_NOT_ACCEPTING_WASTE` or `ERR_CELL_NOT_READY_FOR_WELLFIELD`
    respectively; (c) the treatment agreement must be `ACTIVE` for a leachate shipment to be
    booked or dispatched, else `ERR_AGREEMENT_NOT_ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/gas_well_connect_requires_cell_past_authorization
    """
    _landfill, cell, well = _funded_site_with_a_drilled_well()
    api_client.connect_gas_well(well["id"], ENV_MANAGER)

    authorized = fixtures.authorize_waste_placement(cell["id"], "AGY-2026-77")
    assert authorized["status"] == "READY_FOR_WASTE"

    response = api_client.connect_gas_well(well["id"], ENV_MANAGER)

    validate_error(response, ApiErrorId.ERR_CELL_NOT_READY_FOR_WELLFIELD.value, 409)
    unchanged = get_success_data(api_client.get_gas_well(well["id"], ENV_MANAGER))
    assert unchanged["status"] == "DRILLED"
    assert unchanged["version"] == well["version"], "a refused connect writes nothing"


def test_opening_the_working_face_opens_the_wellfield():
    """Only the parent cell's own state changed between the refusal and the success.

    PRD: "Tying the well into the header and blower moves it to `CONNECTED`, and is available
    both from `DRILLED` and from `OFFLINE` — a valved-out well can be brought back."

    Design: Difficulty/cross_entity_state_dependency/gas_well_connect_requires_cell_past_authorization
    """
    landfill, cell, well = _funded_site_with_a_drilled_well()
    fixtures.authorize_waste_placement(cell["id"], "AGY-2026-77")
    api_client.connect_gas_well(well["id"], ENV_MANAGER)

    activated = fixtures.activate_cell(landfill["id"], cell["id"])
    assert activated["status"] == "ACTIVE"

    connected = get_success_data(api_client.connect_gas_well(well["id"], ENV_MANAGER))

    assert connected["status"] == "CONNECTED"


HAULING_CONTRACT = {
    "daily_gallon_cap": 20000,
    "concurrent_slot_capacity": 2,
    "base_haul_fee": 350.0,
    "treatment_rate_per_kgal": 62.5,
    "effective_from": "2026-01-01T00:00:00Z",
    "expires_on": "2026-09-30T00:00:00Z",
}
FIRST_HAUL = {
    "gallons": 2000,
    "window_start": "2026-08-01T08:00:00Z",
    "window_end": "2026-08-01T10:00:00Z",
}


def _suspended_contract_with_one_booked_haul():
    """The tanker is booked and legal; the receiving plant is the thing that broke."""
    landfill = fixtures.create_landfill()
    agreement = fixtures.register_treatment_agreement(landfill["id"], **HAULING_CONTRACT)
    shipment = fixtures.book_shipment(landfill["id"], agreement["id"], **FIRST_HAUL)
    assert shipment["status"] == "SCHEDULED"
    suspended = fixtures.suspend_treatment_agreement(
        agreement["id"], "POTW pretreatment upset."
    )
    assert suspended["status"] == "SUSPENDED"
    return landfill, agreement, shipment


def _dispatch(landfill_id, shipment_id):
    return api_client.dispatch_leachate_shipment(
        shipment_id, {"hauler_ref": "TNK-1"}, make_site_operator_headers(landfill_id)
    )


def _book(landfill_id, agreement_id, gallons, window_start, window_end):
    from test_helpers.factories import leachate_shipment_payload

    return api_client.create_leachate_shipment(
        leachate_shipment_payload(
            agreement_id,
            gallons=gallons,
            window_start=window_start,
            window_end=window_end,
        ),
        make_site_operator_headers(landfill_id),
    )


def _shipments_of(agreement_id):
    rows, _meta = validate_paginated(
        api_client.list_leachate_shipments(ENV_MANAGER, params={"limit": 100})
    )
    return [row for row in rows if row["treatment_agreement_id"] == agreement_id]


def test_a_suspended_plant_blocks_a_perfectly_legal_dispatch():
    """The shipment is in exactly the right state; its parent is not.

    PRD: "Shipments already booked keep both their slot and their gallons; what suspension
    blocks is new booking and new dispatch."

    Design: Difficulty/cross_entity_state_dependency/leachate_scheduling_and_dispatch_depend_on_agreement_state
    """
    landfill, _agreement, shipment = _suspended_contract_with_one_booked_haul()

    response = _dispatch(landfill["id"], shipment["id"])

    validate_error(response, ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE.value, 409)
    unchanged = get_success_data(api_client.get_leachate_shipment(shipment["id"], ENV_MANAGER))
    assert unchanged["status"] == "SCHEDULED"
    assert unchanged["hauler_ref"] is None


def test_a_booking_attempted_during_suspension_creates_no_row():
    """The refusal is total: no shipment, no gallons, nothing to cancel later.

    PRD: "10. **Cross-entity gating states**, evaluated in this fixed internal order: (a) the
    owning landfill's `operating_status` must be `OPEN` or `RESTRICTED_AIRSPACE` for a load
    to be cleared, else `ERR_SITE_NOT_ACCEPTING_WASTE`; (b) the target cell must be `ACTIVE`
    for a load to be cleared and must be `ACTIVE`, `FULL` or `CLOSED` for a gas well to be
    connected, else `ERR_CELL_NOT_ACCEPTING_WASTE` or `ERR_CELL_NOT_READY_FOR_WELLFIELD`
    respectively; (c) the treatment agreement must be `ACTIVE` for a leachate shipment to be
    booked or dispatched, else `ERR_AGREEMENT_NOT_ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/leachate_scheduling_and_dispatch_depend_on_agreement_state
    """
    landfill, agreement, _shipment = _suspended_contract_with_one_booked_haul()

    response = _book(
        landfill["id"], agreement["id"], 1000, "2026-08-01T12:00:00Z", "2026-08-01T14:00:00Z"
    )

    validate_error(response, ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE.value, 409)
    assert len(_shipments_of(agreement["id"])) == 1


def test_reinstating_the_plant_releases_the_untouched_tanker():
    """The shipment never moved; the dispatch that failed now succeeds unchanged.

    PRD: "Reinstatement moves the agreement `SUSPENDED → ACTIVE`, resets `suspension_reason`
    to null and increments `version` by 1, and is available only while the current logical
    clock is at or before the agreement's `expires_on`."

    Design: Difficulty/cross_entity_state_dependency/leachate_scheduling_and_dispatch_depend_on_agreement_state
    """
    landfill, agreement, shipment = _suspended_contract_with_one_booked_haul()
    _dispatch(landfill["id"], shipment["id"])

    reinstated = get_success_data(
        api_client.reinstate_treatment_agreement(agreement["id"], ENV_MANAGER)
    )
    assert reinstated["status"] == "ACTIVE"
    assert reinstated["suspension_reason"] is None

    dispatched = get_success_data(_dispatch(landfill["id"], shipment["id"]))

    assert dispatched["status"] == "DISPATCHED"
    reread = get_success_data(api_client.get_treatment_agreement(agreement["id"], ENV_MANAGER))
    assert_amount(reread["scheduled_gallons_today"], 2000, "scheduled gallons today")


def test_the_refused_booking_performs_the_lazy_expiry_itself():
    """The request that is turned away is the request that retires the contract.

    PRD: "Expiry itself is **lazy** and has exactly one producer path: when a booking is
    attempted against an agreement in `ACTIVE` or `SUSPENDED` whose `expires_on` is strictly
    earlier than the current logical clock, the agreement is first moved to the terminal
    `EXPIRED` with its `version` incremented by 1, and then the triggering booking is refused
    with `ERR_AGREEMENT_NOT_ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/leachate_scheduling_and_dispatch_depend_on_agreement_state
    """
    landfill, agreement, shipment = _suspended_contract_with_one_booked_haul()
    get_success_data(api_client.reinstate_treatment_agreement(agreement["id"], ENV_MANAGER))
    get_success_data(_dispatch(landfill["id"], shipment["id"]))
    fixtures.set_clock("2026-10-01T00:00:00Z")

    response = _book(
        landfill["id"], agreement["id"], 1000, "2026-10-01T12:00:00Z", "2026-10-01T14:00:00Z"
    )

    validate_error(response, ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE.value, 409)
    assert get_success_data(
        api_client.get_treatment_agreement(agreement["id"], ENV_MANAGER)
    )["status"] == "EXPIRED"

    reinstate = api_client.reinstate_treatment_agreement(agreement["id"], ENV_MANAGER)

    validate_error(reinstate, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, 409)
    assert len(_shipments_of(agreement["id"])) == 1
    assert get_success_data(
        api_client.get_leachate_shipment(shipment["id"], ENV_MANAGER)
    )["status"] == "DISPATCHED"


FIRST_SCHEDULE = {
    "posted_tipping_fee_per_ton": 42.5,
    "host_fee_per_ton": 3.75,
    "tier1_monthly_tons": 100,
    "royalty_tier1_pct": 0.04,
    "royalty_tier2_pct": 0.07,
}
REPLACEMENT_SCHEDULE = dict(
    FIRST_SCHEDULE,
    posted_tipping_fee_per_ton=50.0,
    host_fee_per_ton=5.0,
    minimum_annual_payment=300000,
    effective_from="2026-08-01T00:00:00Z",
    expires_on="2036-08-01T00:00:00Z",
)


def _site_whose_agreement_is_still_a_draft():
    """Everything is ready to price waste except that nothing has been signed."""
    site = fixtures.setup_active_site(with_host_agreement=False)
    site["agreement"] = fixtures.draft_host_agreement(
        site["landfill"]["id"], **FIRST_SCHEDULE
    )
    assert site["agreement"]["status"] == "DRAFT"
    site["day"] = fixtures.open_operating_day(
        site["landfill"]["id"],
        site["cell"]["id"],
        operating_date="2026-08-05T00:00:00Z",
        **DAY_SHAPE,
    )
    site["load"] = fixtures.receive_load(
        site["landfill"]["id"], site["day"]["id"], hauler_ref="H-1", manifest_tons=100.0
    )
    return site


def test_a_draft_agreement_cannot_price_a_load():
    """The gate rate has to come from somewhere, and a draft is not somewhere.

    PRD: "The site must have exactly one host community agreement in `EXECUTED` or
    `UNDER_AMENDMENT`, because the gate rate comes from it, else
    `ERR_NO_EXECUTED_HOST_AGREEMENT`."

    Design: Difficulty/cross_entity_state_dependency/billing_depends_on_which_host_agreement_is_live
    """
    site = _site_whose_agreement_is_still_a_draft()

    response = api_client.clear_screening(
        site["load"]["id"], None, make_scale_operator_headers(site["landfill"]["id"])
    )

    validate_error(response, ApiErrorId.ERR_NO_EXECUTED_HOST_AGREEMENT.value, 409)


def test_execution_makes_the_identical_clearance_price_the_load():
    """One signature later, the same truck is billed 4625.00 at the gate.

    PRD: "This variant applies **no royalty component whatsoever**, and once written
    `gate_charge_amount` is never overwritten by anything."

    Design: Difficulty/cross_entity_state_dependency/billing_depends_on_which_host_agreement_is_live
    """
    site = _site_whose_agreement_is_still_a_draft()

    executed = fixtures.execute_host_agreement(
        site["agreement"]["id"], site["landfill"]["id"]
    )
    assert executed["status"] == "EXECUTED"

    cleared = fixtures.clear_screening(site["landfill"]["id"], site["load"]["id"])

    assert_amount(cleared["gate_charge_amount"], 4625.00, "gate charge")
    assert cleared["host_royalty_amount"] is None


def test_terminating_the_agreement_blocks_a_day_that_never_referenced_it():
    """The day is stopped by an entity it holds no foreign key to.

    PRD: "Termination is available from `DRAFT` or `EXECUTED`, records the supplied
    `termination_reason`, moves the agreement to the terminal `TERMINATED`, and increments
    both the agreement's and the landfill's `version` by 1."

    Design: Difficulty/cross_entity_state_dependency/billing_depends_on_which_host_agreement_is_live
    """
    site = _site_whose_agreement_is_still_a_draft()
    fixtures.execute_host_agreement(site["agreement"]["id"], site["landfill"]["id"])
    fixtures.clear_screening(site["landfill"]["id"], site["load"]["id"])
    fixtures.certify_weight(site["landfill"]["id"], site["load"]["id"], 100.0)

    terminated = get_success_data(
        api_client.terminate_host_community_agreement(
            site["agreement"]["id"],
            {"termination_reason": "Renegotiated with the township."},
            FINANCE_FILER,
        )
    )
    assert terminated["status"] == "TERMINATED"

    response = api_client.close_operating_day(
        site["day"]["id"], make_site_operator_headers(site["landfill"]["id"])
    )

    validate_error(response, ApiErrorId.ERR_NO_EXECUTED_HOST_AGREEMENT.value, 409)


def test_the_two_pricing_variants_can_be_governed_by_two_different_agreements():
    """4625.00 was frozen under the old schedule; 5700.00 is settled under the new one.

    PRD: "The gross is `certified_net_tons` multiplied by `posted_tipping_fee_per_ton`,
    rounded to 2 decimal places; the host fee is `certified_net_tons` multiplied by
    `host_fee_per_ton`, rounded to 2 decimal places; the royalty is computed by the waterfall
    below and stored as `host_royalty_amount`; and `final_charge_amount` is the sum of those
    three components, rounded to 2 decimal places."

    Design: Difficulty/cross_entity_state_dependency/billing_depends_on_which_host_agreement_is_live
    """
    site = _site_whose_agreement_is_still_a_draft()
    fixtures.execute_host_agreement(site["agreement"]["id"], site["landfill"]["id"])
    fixtures.clear_screening(site["landfill"]["id"], site["load"]["id"])
    fixtures.certify_weight(site["landfill"]["id"], site["load"]["id"], 100.0)
    api_client.terminate_host_community_agreement(
        site["agreement"]["id"],
        {"termination_reason": "Renegotiated with the township."},
        FINANCE_FILER,
    )
    replacement = fixtures.draft_host_agreement(
        site["landfill"]["id"], **REPLACEMENT_SCHEDULE
    )
    live = fixtures.execute_host_agreement(replacement["id"], site["landfill"]["id"])
    assert live["status"] == "EXECUTED"

    closed = fixtures.close_operating_day(site["landfill"]["id"], site["day"]["id"])

    assert closed["status"] == "CLOSED"
    assert_amount(closed["tons_placed"], 100.00, "tons placed")
    load = get_success_data(api_client.get_waste_load(site["load"]["id"], FINANCE_FILER))
    assert load["billing_status"] == "FINALIZED"
    assert_amount(load["gate_charge_amount"], 4625.00, "gate charge")
    assert_amount(load["host_royalty_amount"], 200.00, "host royalty")
    assert_amount(load["final_charge_amount"], 5700.00, "final charge")
    assert get_success_data(
        api_client.get_host_community_agreement(site["agreement"]["id"], FINANCE_FILER)
    )["status"] == "TERMINATED"
