"""Version preconditions on the asset and on the lease, and a code limit that comes
back down when the quantity behind it is revoked."""

from test_helpers import (
    AHJ_HEADERS,
    LANDLORD_HEADERS,
    LANDLORD_NEGOTIATOR_HEADERS,
    ApiErrorId,
    add_second_tenant_project,
    assert_capacity_pool_identity,
    assert_money,
    assert_reservation,
    assert_utilization_report,
    create_reservation,
    decide_hazmat_permit,
    file_hazmat_permit,
    get_building,
    get_lease,
    get_permit,
    get_success_data,
    get_utilization,
    proposal_payload,
    reservation_payload,
    setup_lease_at_loi,
    setup_permitted_project,
    validate_error,
    validate_paginated,
    validate_success,
)

NAMEPLATE = {
    "name": "Kendall Labs 400",
    "address_city": "Cambridge",
    "occupancy_status": "PARTIALLY_OCCUPIED",
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
    "assessment_basis": "SCREENING",
    "required_vibration_class": "VC_C",
    "required_exhaust_cfm": 50000,
    "required_power_kw": 700,
    "measured_live_load_psf": 88,
}
QC_LEASE = {
    "term_months": 120,
    "base_rent_psf": 95.00,
    "delivery_deadline": "2026-12-31T00:00:00Z",
}
QC_PROJECT = {
    "design_exhaust_cfm": 12000,
    "design_power_kw": 180,
    "scope_summary": "QC lab fit-out, floor 2",
}

DESIGN_EXHAUST_CFM = 12000
DESIGN_POWER_KW = 180
REVOCATION_REASON = "QC tenant surrendered its flammable inventory ahead of schedule"


def _qc_terms(**extra):
    """The quality control deal: 2000 square feet on floor 2 of the standard plate."""
    return dict(
        research_type="ANALYTICAL_QC",
        premises_floor_number=2,
        floor_numbers=(2,),
        rentable_sf=2000,
        lease_overrides=dict(QC_LEASE),
        building_overrides=dict(NAMEPLATE),
        floor_overrides={2: dict(PLATE)},
        assessment_overrides=dict(DEMAND),
        **extra,
    )


def _qc_permitted_project(api):
    """A conversion-approved plate on floor 2 with an executed QC lease and a
    permitted project on it."""
    return setup_permitted_project(
        api, allowance_psf=70.00, **_qc_terms(project_overrides=dict(QC_PROJECT))
    )


def test_a_reservation_replayed_against_the_version_it_read_is_refused(api):
    """What is compared is the version, not the room left in the riser.

    The replay quotes the version the caller genuinely read and asks for capacity
    the riser plainly still has, and it is refused all the same; re-reading the
    asset and sending the identical figures against the fresh version succeeds,
    and the refusal left no reservation and no version bump behind it.

    Design: Corner/complexity_layers/stale_expected_building_version_on_reservation_create_returns_412
    """
    bundle = _qc_permitted_project(api)
    project_id = bundle["project"]["id"]
    building_id = bundle["building"]["id"]
    before = get_building(api, building_id)
    assert_money(before["exhaust_available_cfm"], 80000.00, "exhaust_available_cfm")

    first = validate_success(
        api.create_reservation(
            reservation_payload(
                project_id, before["version"], DESIGN_EXHAUST_CFM, DESIGN_POWER_KW
            ),
            LANDLORD_HEADERS,
        ),
        201,
    )
    replay = api.create_reservation(
        reservation_payload(
            project_id, before["version"], DESIGN_EXHAUST_CFM, DESIGN_POWER_KW
        ),
        LANDLORD_HEADERS,
    )
    validate_error(replay, ApiErrorId.ERR_STALE_BUILDING_VERSION.value, 412)

    between = get_building(api, building_id)
    second = create_reservation(
        api, project_id, between["version"], DESIGN_EXHAUST_CFM, DESIGN_POWER_KW
    )
    after = get_building(api, building_id)

    assert_reservation(first)
    assert first["status"] == "RESERVED"
    assert second["status"] == "RESERVED"
    assert between["version"] == before["version"] + 1
    assert after["version"] == between["version"] + 1
    assert_money(between["exhaust_available_cfm"], 68000.00, "exhaust_available_cfm")
    assert_money(after["exhaust_available_cfm"], 56000.00, "exhaust_available_cfm")
    assert_money(after["exhaust_reserved_cfm"], 24000.00, "exhaust_reserved_cfm")
    assert_money(after["power_reserved_kw"], 360.00, "power_reserved_kw")
    assert_money(after["power_available_kw"], 440.00, "power_available_kw")
    assert_capacity_pool_identity(after)
    rows, meta = validate_paginated(
        api.list_reservations(LANDLORD_HEADERS, {"project_id": project_id})
    )
    assert meta["total_count"] == 2
    assert all(row["status"] == "RESERVED" for row in rows)


def test_a_round_replayed_against_the_version_it_read_is_refused_on_the_version(api):
    """The version precondition is examined before whose turn it is.

    The landlord's replay is both stale and out of turn -- its own first round is
    still open -- and the answer names the version, because that check runs
    first; no second live round is opened, and the tenant's properly versioned
    counter then goes through.

    Design: Corner/complexity_layers/stale_expected_lease_version_on_proposal_create_returns_412
    """
    bundle = setup_lease_at_loi(
        api, **_qc_terms(complete_disciplines=("LAB_EXHAUST",))
    )
    lease_id = bundle["lease"]["id"]
    first_version = bundle["lease"]["version"]

    first = validate_success(
        api.create_proposal(
            lease_id,
            proposal_payload(first_version, 70.00),
            LANDLORD_NEGOTIATOR_HEADERS,
        ),
        201,
    )
    replay = api.create_proposal(
        lease_id, proposal_payload(first_version, 65.00), LANDLORD_NEGOTIATOR_HEADERS
    )
    validate_error(replay, ApiErrorId.ERR_STALE_LEASE_VERSION.value, 412)

    countered = get_lease(api, lease_id)
    second = validate_success(
        api.create_proposal(
            lease_id,
            proposal_payload(countered["version"], 90.00),
            bundle["tenant_headers"],
        ),
        201,
    )

    assert first["round_number"] == 1
    assert second["round_number"] == 2
    assert countered["status"] == "NEGOTIATING"
    assert countered["version"] == first_version + 1
    assert get_success_data(
        api.get_proposal(first["id"], LANDLORD_HEADERS)
    )["status"] == "COUNTERED"
    assert get_success_data(
        api.get_proposal(second["id"], LANDLORD_HEADERS)
    )["status"] == "OPEN"
    final = get_lease(api, lease_id)
    assert final["status"] == "COUNTER_PENDING"
    assert final["negotiation_round_count"] == 2
    _, all_rounds = validate_paginated(
        api.list_lease_proposals(lease_id, LANDLORD_HEADERS)
    )
    assert all_rounds["total_count"] == 2
    _, open_rounds = validate_paginated(
        api.list_lease_proposals(lease_id, LANDLORD_HEADERS, {"status": "OPEN"})
    )
    assert open_rounds["total_count"] == 1


def test_revoking_the_approved_quantity_lets_the_refused_one_through(api):
    """The limit comes back down; it is not a one-way ratchet.

    One hundred and fifty gallons already approved leaves too little room for the
    neighbour's forty, and once the hundred and fifty are revoked the identical
    forty are approved -- while the report, which counts what has merely been
    asked for as well, reads a hundred and ninety before the revocation and forty
    after it.

    Design: Corner/complexity_layers/revoking_the_approved_permit_resets_the_floor_wide_cumulative_basis
    """
    first = _qc_permitted_project(api)
    second = add_second_tenant_project(
        api, first, rentable_sf=3000, allowance_psf=60.00
    )
    floor_id = first["premises_floor"]["id"]
    approved_permit = file_hazmat_permit(
        api, first["project"]["id"], floor_id, "FLAMMABLE_IB", "CLOSED_SYSTEM_USE",
        150.00, 1, first["tenant_headers"],
    )
    decide_hazmat_permit(api, approved_permit["id"], "APPROVE")
    waiting_permit = file_hazmat_permit(
        api, second["project"]["id"], second["floor"]["id"], "FLAMMABLE_IB",
        "CLOSED_SYSTEM_USE", 40.00, 1, second["tenant_headers"],
    )

    before = get_utilization(api, floor_id, "FLAMMABLE_IB", 1)
    refused = api.decide_hazmat_permit(
        waiting_permit["id"], {"decision": "APPROVE"}, AHJ_HEADERS
    )
    validate_error(refused, ApiErrorId.ERR_CONTROL_AREA_MAQ_EXCEEDED.value, 409)
    revoked = decide_hazmat_permit(
        api, approved_permit["id"], "REVOKE", REVOCATION_REASON
    )
    after = get_utilization(api, floor_id, "FLAMMABLE_IB", 1)
    accepted = decide_hazmat_permit(api, waiting_permit["id"], "APPROVE")
    final = get_utilization(api, floor_id, "FLAMMABLE_IB", 1)

    assert_utilization_report(before, floor_id, "FLAMMABLE_IB")
    assert_money(before["allowance_per_control_area_gal"], 180.00, "allowance")
    assert_money(before["per_control_area_basis_gal"], 190.00, "basis before")
    assert revoked["status"] == "REVOKED"
    assert revoked["decision_reason"] == REVOCATION_REASON
    assert_money(after["per_control_area_basis_gal"], 40.00, "basis after")
    assert accepted["status"] == "APPROVED"
    assert_money(final["per_control_area_basis_gal"], 40.00, "basis final")
    assert_money(final["per_control_area_utilization_pct"], 22.22, "utilisation")
    assert get_permit(api, approved_permit["id"])["status"] == "REVOKED"
    assert get_permit(api, waiting_permit["id"])["status"] == "APPROVED"
