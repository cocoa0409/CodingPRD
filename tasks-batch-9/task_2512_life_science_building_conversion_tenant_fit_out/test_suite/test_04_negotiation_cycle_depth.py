"""The negotiation cycle: a lease returning to a state it already occupied."""

from test_helpers import (
    CLOCK_START,
    LANDLORD_HEADERS,
    LANDLORD_NEGOTIATOR_HEADERS,
    PROPOSAL_TTL_DAYS,
    ApiErrorId,
    assert_money,
    assert_proposal,
    get_lease,
    get_success_data,
    make_tenant_headers,
    same_instant,
    set_clock,
    setup_lease_at_loi,
    shift,
    validate_error,
)

NAMEPLATE = {
    "name": "Kendall Labs 400",
    "published_floor_to_floor_ft": 14.0,
    "published_live_load_psf": 95,
    "published_vibration_class": "VC_C",
    "exhaust_riser_capacity_cfm": 60000,
    "emergency_power_capacity_kw": 800,
    "chilled_water_capacity_tons": 1200,
}
PLATE = {
    "floor_to_floor_ft": 14.0,
    "live_load_psf": 95,
    "vibration_class": "VC_C",
    "sprinklered": True,
}
DEMAND = {
    "required_vibration_class": "VC_C",
    "required_exhaust_cfm": 50000,
    "required_power_kw": 700,
    "measured_live_load_psf": 88,
}


def _lease_ready_to_negotiate(api):
    """A chemistry lease at letter of intent on a cleared fifth-floor plate."""
    set_clock(api, CLOCK_START)
    return setup_lease_at_loi(
        api,
        research_type="CHEMISTRY_SYNTHESIS",
        premises_floor_number=5,
        floor_numbers=(5,),
        rentable_sf=24200,
        lease_overrides={"term_months": 180, "base_rent_psf": 118.00},
        building_overrides=NAMEPLATE,
        floor_overrides={5: dict(PLATE)},
        assessment_overrides=dict(DEMAND),
    )


def _round(api, lease_id, allowance_psf, headers):
    """One negotiation round taken against the lease's current version."""
    version = get_lease(api, lease_id)["version"]
    return get_success_data(
        api.create_proposal(
            lease_id,
            {
                "expected_lease_version": version,
                "proposed_allowance_psf": allowance_psf,
            },
            headers,
        )
    )


def _proposal(api, proposal_id):
    """Read one negotiation round back."""
    return get_success_data(api.get_proposal(proposal_id, LANDLORD_HEADERS))


def test_three_rounds_carry_the_lease_back_to_a_status_it_already_held(api):
    """The lease's posture alternates rather than advancing monotonically.

    The landlord's opening round carries the lease into negotiation, the
    tenant's counter carries it to a pending counter, and the landlord's second
    round carries it back into negotiation -- the same status it held after
    round one, with the round counter now at three.

    Design: Difficulty/non_linear_state_machine/lease_negotiation_cycles_negotiating_counter_pending_negotiating
    """
    bundle = _lease_ready_to_negotiate(api)
    lease_id = bundle["lease"]["id"]
    tenant_headers = make_tenant_headers(bundle["tenant"]["id"])
    assert bundle["lease"]["status"] == "LOI"

    _round(api, lease_id, 140.00, LANDLORD_NEGOTIATOR_HEADERS)
    after_one = get_lease(api, lease_id)
    assert after_one["status"] == "NEGOTIATING"
    assert after_one["negotiation_round_count"] == 1

    _round(api, lease_id, 175.00, tenant_headers)
    after_two = get_lease(api, lease_id)
    assert after_two["status"] == "COUNTER_PENDING"
    assert after_two["negotiation_round_count"] == 2

    _round(api, lease_id, 158.00, LANDLORD_NEGOTIATOR_HEADERS)
    after_three = get_lease(api, lease_id)
    assert after_three["status"] == "NEGOTIATING"
    assert after_three["negotiation_round_count"] == 3
    assert after_three["status"] == after_one["status"], "the cycle closed"


def test_each_new_round_settles_the_round_it_supersedes(api):
    """Creating a round closes the live one before opening its own.

    Rounds one and two are both marked countered once round three exists, only
    round three is live, and its ten-day window is measured from the instant it
    was created.

    Design: Difficulty/non_linear_state_machine/lease_negotiation_cycles_negotiating_counter_pending_negotiating
    """
    bundle = _lease_ready_to_negotiate(api)
    lease_id = bundle["lease"]["id"]
    tenant_headers = make_tenant_headers(bundle["tenant"]["id"])

    first = _round(api, lease_id, 140.00, LANDLORD_NEGOTIATOR_HEADERS)
    second = _round(api, lease_id, 175.00, tenant_headers)
    third = _round(api, lease_id, 158.00, LANDLORD_NEGOTIATOR_HEADERS)

    assert _proposal(api, first["id"])["status"] == "COUNTERED"
    assert _proposal(api, second["id"])["status"] == "COUNTERED"
    assert_proposal(third)
    assert third["status"] == "OPEN"
    assert third["round_number"] == 3
    assert third["proposed_by"] == "LANDLORD"
    assert_money(third["proposed_allowance_psf"], 158.00, "proposed_allowance_psf")
    assert same_instant(
        third["expires_at"], shift(CLOCK_START, days=PROPOSAL_TTL_DAYS)
    ), "the window runs ten days from creation"
    assert second["proposed_by"] == "TENANT"
    assert second["round_number"] == 2


def test_a_party_may_not_counter_its_own_live_round(api):
    """Turn-taking is enforced against the live round's author.

    With the tenant's round still live it is the landlord's turn, so a second
    consecutive tenant round is refused rather than absorbed, and the lease is
    left exactly where the tenant's counter put it.

    Design: Difficulty/non_linear_state_machine/lease_negotiation_cycles_negotiating_counter_pending_negotiating
    """
    bundle = _lease_ready_to_negotiate(api)
    lease_id = bundle["lease"]["id"]
    tenant_headers = make_tenant_headers(bundle["tenant"]["id"])

    _round(api, lease_id, 140.00, LANDLORD_NEGOTIATOR_HEADERS)
    tenant_round = _round(api, lease_id, 175.00, tenant_headers)
    before = get_lease(api, lease_id)

    response = api.create_proposal(
        lease_id,
        {
            "expected_lease_version": before["version"],
            "proposed_allowance_psf": 172.00,
        },
        tenant_headers,
    )
    validate_error(response, ApiErrorId.ERR_NOT_YOUR_TURN.value, 409)

    after = get_lease(api, lease_id)
    assert after["status"] == "COUNTER_PENDING"
    assert after["negotiation_round_count"] == 2
    assert after["version"] == before["version"]
    assert _proposal(api, tenant_round["id"])["status"] == "OPEN"
