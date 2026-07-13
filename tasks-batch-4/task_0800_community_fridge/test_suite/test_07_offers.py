"""Surplus offer lifecycle: acceptance gating and conversion on intake."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    setup_accepted_offer, reset_clock, new_fridge, new_donor, new_steward,
    new_offer, set_clock, intake_batch,
    make_steward_headers, make_admin_headers,
)


def test_accepting_already_accepted_offer_rejected_invalid_state(api):
    """PRD §3.4: "Acceptance is only valid from `OFFERED`; from any other status it is
    rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/accept_offer_already_accepted_returns_invalid_state
    """
    fridge, donor, steward, offer = setup_accepted_offer(api, capacity_slots=5)
    assert offer["status"] == "ACCEPTED"
    resp = api.accept_offer(offer["id"], make_steward_headers(steward["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_accepting_offer_past_pickup_deadline_rejected_expired(api):
    """PRD §3.4: "requires the current logical time to be strictly before `pickup_by`,
    failing with `ERR_OFFER_EXPIRED` if the deadline has passed."

    Design: Corner/state_machines/accept_offer_past_pickup_by_returns_offer_expired
    """
    reset_clock(api)
    fridge = new_fridge(api, capacity_slots=5)
    donor = new_donor(api)
    steward = new_steward(api)
    offer = new_offer(api, donor["id"], fridge["id"], pickup_by="2026-03-05T00:00:00Z")
    set_clock(api, "2026-03-06T00:00:00Z")
    resp = api.accept_offer(offer["id"], make_steward_headers(steward["id"]))
    validate_error(resp, ApiErrorId.ERR_OFFER_EXPIRED.value)


def test_intake_citing_accepted_offer_converts_it(api):
    """PRD §3.5: "If the intake cited a `surplus_offer_id` whose offer is in
    `ACCEPTED` status, that offer is moved to `CONVERTED` as part of the same
    operation."

    Design: Corner/cross_cutting_complexity_layers/convert_offer_on_intake_with_surplus_offer_id
    """
    fridge, donor, steward, offer = setup_accepted_offer(api, capacity_slots=10)
    intake_batch(
        api, fridge["id"], steward["id"],
        food_category="PREPARED", storage_type="COLD_CHAIN",
        declared_quantity_kg=3.0, intake_temp_c=4.0, allergens=["DAIRY"],
        use_by="2026-03-04T00:00:00Z", surplus_offer_id=offer["id"],
    )
    fetched = validate_success(api.get_offer(offer["id"], make_admin_headers()), 200)
    assert fetched["status"] == "CONVERTED"
