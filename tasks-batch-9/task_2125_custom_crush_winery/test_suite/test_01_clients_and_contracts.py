"""Client onboarding, the contract entitlement envelope and their lifecycles."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    activate_contract,
    assert_client,
    assert_contract,
    assert_vessel,
    assert_vessel_allocation,
    create_client_payload,
    create_contract_payload,
    new_client,
    new_contract,
    new_vessel,
    reserve_allocation,
    set_clock,
    setup_active_contract,
    setup_contract_with_lot,
    validate_error,
    validate_paginated,
    validate_success,
)


# ── Client registration and reads ────────────────────────────────────


def test_client_registration_returns_active_defaults_and_version_one(
    api, facility_admin_headers
):
    """PRD 3.1: "A newly registered client opens in `status` `ACTIVE`, with
    `bond_gallons_in_bond` and `taxpaid_gallons_ytd` both at 0 and
    `last_filed_period_end` null."
    PRD 2.4: "`version` (integer): a counter that starts at 1 when the resource
    is created and increases by exactly 1 on every mutation."
    PRD 4: "Operations that mint a new, independently addressable resource
    return `201 Created`."

    Design: Corner/entities/corner_client_creation_returns_defaults_and_version_one
    """
    set_clock("2026-08-01T00:00:00Z")

    response = api.create_client(create_client_payload(), facility_admin_headers)
    data = validate_success(response, 201)
    assert response.json()["response_type"] == "object"

    assert_client(data)
    assert data["status"] == "ACTIVE", f"Expected ACTIVE, got {data['status']}"
    assert data["version"] == 1, f"Expected version 1, got {data['version']}"
    assert data["bond_gallons_in_bond"] == pytest.approx(0, abs=0.01)
    assert data["taxpaid_gallons_ytd"] == pytest.approx(0, abs=0.01)
    assert data["last_filed_period_end"] is None
    assert data["created_at"] == "2026-08-01T00:00:00.000Z", (
        f"created_at must read the logical clock, got {data['created_at']}"
    )


def test_client_read_returns_the_stored_registration_row(api, compliance_officer_headers):
    """PRD 3.1: "A `FacilityAdmin` registers one by supplying the client's legal
    `name`, its `ttb_permit_number`, and a `contact_email` for billing and
    compliance correspondence."

    Design: Corner/entities/corner_client_retrieval_returns_stored_row
    """
    client = new_client()

    data = validate_success(api.get_client(client["id"], compliance_officer_headers))

    assert_client(data)
    assert data["name"] == "Coombsville Cellars"
    assert data["ttb_permit_number"] == "BW-CA-15001"
    assert data["contact_email"] == "ops@coombsville.example"


def test_client_listing_honours_limit_offset_and_total_count(api, facility_admin_headers):
    """PRD 2.3: "The `limit` parameter caps the number of records returned; it
    defaults to 10, may not be smaller than 1, and may not be larger than 100."
    PRD 2.3: "The `meta` object of a list response carries `limit`, `offset`,
    `total_count` and `has_more`, where `total_count` counts every record
    matching the filter before pagination is applied and `has_more` indicates
    whether records remain beyond the current page."

    Design: Corner/entities/corner_client_listing_paginates_with_limit_and_offset
    """
    new_client(name="Coombsville Cellars", ttb_permit_number="BW-CA-15001",
               contact_email="a@x.example")
    new_client(name="Pritchard Hill Partners", ttb_permit_number="BW-CA-15002",
               contact_email="b@x.example")
    new_client(name="Howell Ridge Wines", ttb_permit_number="BW-CA-15003",
               contact_email="c@x.example")

    response = api.list_clients(facility_admin_headers, params={"limit": 2, "offset": 0})
    rows, meta = validate_paginated(response)
    assert response.json()["response_type"] == "array"
    assert len(rows) == 2, f"Expected 2 rows on the first page, got {len(rows)}"
    assert meta["total_count"] == 3
    assert meta["limit"] == 2
    assert meta["offset"] == 0
    assert meta["has_more"] is True

    rows2, meta2 = validate_paginated(
        api.list_clients(facility_admin_headers, params={"limit": 2, "offset": 2})
    )
    assert len(rows2) == 1, f"Expected 1 row on the second page, got {len(rows2)}"
    assert meta2["has_more"] is False


def test_client_read_with_unknown_id_reports_client_not_found(api, facility_admin_headers):
    """PRD 2.5: "Each identifier in the URL must resolve to a stored resource,
    validated left to right, and the rejection names the collection that failed:
    `ERR_CLIENT_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`, `ERR_VESSEL_NOT_FOUND`,
    `ERR_ALLOCATION_NOT_FOUND`, `ERR_INTAKE_NOT_FOUND`, `ERR_LOT_NOT_FOUND`,
    `ERR_TRIAL_NOT_FOUND`, `ERR_WORK_ORDER_NOT_FOUND`, `ERR_LINE_NOT_FOUND`,
    `ERR_RUN_NOT_FOUND`, `ERR_DRY_GOODS_ITEM_NOT_FOUND`,
    `ERR_TTB_REPORT_NOT_FOUND` or `ERR_RELEASE_ORDER_NOT_FOUND` — each with
    status 404."

    Design: Corner/entities/corner_client_get_with_unknown_id_not_found
    """
    set_clock("2026-08-01T00:00:00Z")

    response = api.get_client(NON_EXISTENT_UUID, facility_admin_headers)

    validate_error(response, ApiErrorId.ERR_CLIENT_NOT_FOUND.value, 404)


def test_client_close_refused_while_a_lot_still_holds_wine_in_bond(
    api, facility_admin_headers
):
    """PRD 3.1: "Closing a client is the terminal step and may be taken from
    either `ACTIVE` or `SUSPENDED`, but only when no lot on any of that client's
    contracts still carries `bond_status` `IN_BOND` together with a
    `volume_gallons` greater than zero; a client with wine still in bond is
    refused with `ERR_CLIENT_HAS_BONDED_INVENTORY`."

    Design: Corner/state_machines/corner_client_close_blocked_by_bonded_inventory
    """
    scenario = setup_contract_with_lot()

    response = api.client_status(
        scenario["client"]["id"], {"action": "CLOSE"}, facility_admin_headers
    )

    validate_error(response, ApiErrorId.ERR_CLIENT_HAS_BONDED_INVENTORY.value, 422)

    client = validate_success(
        api.get_client(scenario["client"]["id"], facility_admin_headers)
    )
    assert client["status"] == "ACTIVE", "a refused close must not move the client"
    assert client["bond_gallons_in_bond"] == pytest.approx(3135.00, abs=0.01)

    contract = validate_success(
        api.get_contract(scenario["contract"]["id"], facility_admin_headers)
    )
    assert contract["status"] == "ACTIVE", "no termination cascade may fire"


# ── Contract creation and shape validation ───────────────────────────


def test_contract_creation_without_tank_entitlement_is_invalid_request(
    api, facility_admin_headers
):
    """PRD 2.5: "The body must carry every required field for the endpoint; each
    field must have its declared type; every enum-valued field must carry a
    declared member; every numeric constraint must hold, including the "greater
    than zero", "at least zero", bounded-range and decimal-place constraints
    stated per field in §3; and the pagination `limit` must lie between 1 and
    100 with `offset` at least 0."
    PRD 3.1: "`tank_gallons_entitled` (greater than zero) caps the aggregate
    gallons the client may hold in tanks at one time"

    Design: Corner/entities/corner_contract_creation_missing_required_field_invalid_request
    """
    client = new_client()
    payload = create_contract_payload(client["id"])
    payload.pop("tank_gallons_entitled")

    response = api.create_contract(payload, facility_admin_headers)

    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

    rows, meta = validate_paginated(
        api.list_contracts(facility_admin_headers, params={"client_id": client["id"]})
    )
    assert rows == [], "a rejected creation must store nothing"
    assert meta["total_count"] == 0


def test_contract_creation_with_unknown_client_reports_client_not_found(
    api, facility_admin_headers
):
    """PRD 2.5: "Every reference supplied in a request body must resolve:
    `client_id`, `contract_id`, `vessel_id`, `lot_id`, `line_id`, each entry of
    `intake_ids`, and each `source_lot_id` inside `components`. The rejection is
    the matching not-found code above, with status 404."

    Design: Corner/entities/corner_contract_creation_with_unknown_client_id_not_found
    """
    set_clock("2026-08-01T00:00:00Z")

    response = api.create_contract(
        create_contract_payload(NON_EXISTENT_UUID), facility_admin_headers
    )

    validate_error(response, ApiErrorId.ERR_CLIENT_NOT_FOUND.value, 404)


# ── Contract lifecycle ───────────────────────────────────────────────


def test_contract_activate_from_draft_is_an_undeclared_transition(
    api, facility_admin_headers
):
    """PRD 3.1: "Activation moves `PENDING_SIGNATURE` to `ACTIVE` and requires
    the owning client to be `ACTIVE`, failing otherwise with
    `ERR_CLIENT_NOT_ACTIVE`."
    PRD 2.5: "The requested action must be a transition declared out of the
    target's current state. Repeating a trigger that has already fired, and any
    action attempted out of a terminal state, both fail here with
    `ERR_INVALID_STATE` (409)."

    Design: Corner/state_machines/corner_contract_activate_from_draft_rejected
    """
    client = new_client()
    contract = new_contract(client["id"])

    response = api.contract_transition(
        contract["id"], {"action": "ACTIVATE"}, facility_admin_headers
    )

    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value, 409)

    stored = validate_success(api.get_contract(contract["id"], facility_admin_headers))
    assert stored["status"] == "DRAFT"
    assert stored["version"] == 1, "a rejected transition performs no mutation"


def test_contract_revision_loop_returns_to_draft_and_may_repeat(
    api, facility_admin_headers
):
    """PRD 3.1: "From `PENDING_SIGNATURE` the admin may revise, sending it back
    to `DRAFT`; that loop may repeat any number of times."
    PRD 3.1: "Every one of these six transitions increments the contract's
    `version` by 1."

    Design: Corner/state_machines/corner_contract_revision_loop_returns_to_draft
    """
    client = new_client()
    contract = new_contract(client["id"])

    first = validate_success(
        api.contract_transition(contract["id"], {"action": "SUBMIT"}, facility_admin_headers)
    )
    assert first["status"] == "PENDING_SIGNATURE"

    revised = validate_success(
        api.contract_transition(contract["id"], {"action": "REVISE"}, facility_admin_headers)
    )
    assert revised["status"] == "DRAFT"
    assert revised["version"] == 3, (
        f"create + SUBMIT + REVISE must read version 3, got {revised['version']}"
    )

    resubmitted = validate_success(
        api.contract_transition(contract["id"], {"action": "SUBMIT"}, facility_admin_headers)
    )
    assert resubmitted["status"] == "PENDING_SIGNATURE"
    assert resubmitted["version"] == 4


def test_contract_activate_blocked_while_its_client_is_suspended(
    api, facility_admin_headers
):
    """PRD 3.1: "Activation moves `PENDING_SIGNATURE` to `ACTIVE` and requires
    the owning client to be `ACTIVE`, failing otherwise with
    `ERR_CLIENT_NOT_ACTIVE`."
    PRD 3.1: "In the first hop, every contract of that client currently in
    `ACTIVE` moves to `SUSPENDED`, each incrementing its own `version`."

    Design: Corner/errors/corner_contract_activate_blocked_by_suspended_client
    """
    client = new_client()
    contract = new_contract(client["id"])
    validate_success(
        api.contract_transition(contract["id"], {"action": "SUBMIT"}, facility_admin_headers)
    )
    validate_success(
        api.client_status(client["id"], {"action": "SUSPEND"}, facility_admin_headers)
    )

    response = api.contract_transition(
        contract["id"], {"action": "ACTIVATE"}, facility_admin_headers
    )
    validate_error(response, ApiErrorId.ERR_CLIENT_NOT_ACTIVE.value, 409)

    blocked = validate_success(api.get_contract(contract["id"], facility_admin_headers))
    assert blocked["status"] == "PENDING_SIGNATURE"

    validate_success(
        api.client_status(client["id"], {"action": "REINSTATE"}, facility_admin_headers)
    )
    activated = validate_success(
        api.contract_transition(
            contract["id"], {"action": "ACTIVATE"}, facility_admin_headers
        )
    )
    assert activated["status"] == "ACTIVE", "reinstating the client unblocks activation"


def test_contract_terminate_blocked_while_a_reserved_allocation_survives(
    api, facility_admin_headers
):
    """PRD 3.1: "Termination may be taken from either `ACTIVE` or `SUSPENDED`,
    but only when the contract owns no allocation in `RESERVED` or `COMMITTED`;
    otherwise the request is refused with `ERR_ALLOCATIONS_OUTSTANDING`."

    Design: Corner/errors/corner_contract_terminate_blocked_by_outstanding_allocations
    """
    scenario = setup_active_contract()
    vessel = new_vessel()
    allocation = reserve_allocation(
        scenario["contract"]["id"], vessel["id"], allocated_gallons=2500
    )

    response = api.contract_transition(
        scenario["contract"]["id"], {"action": "TERMINATE"}, facility_admin_headers
    )
    validate_error(response, ApiErrorId.ERR_ALLOCATIONS_OUTSTANDING.value, 422)

    blocked = validate_success(
        api.get_contract(scenario["contract"]["id"], facility_admin_headers)
    )
    assert blocked["status"] == "ACTIVE"

    validate_success(
        api.vessel_allocation_transition(
            allocation["id"], {"action": "CANCEL"}, facility_admin_headers
        )
    )
    terminated = validate_success(
        api.contract_transition(
            scenario["contract"]["id"], {"action": "TERMINATE"}, facility_admin_headers
        )
    )
    assert terminated["status"] == "TERMINATED", (
        "cancelling the last live allocation must let the same call through"
    )


# ── The three-hop client suspension cascade ──────────────────────────


def _setup_client_with_two_reserved_allocations():
    """ACTIVE client and contract holding a 2500-gallon tank reservation and one
    barrel slot, so gallons_allocated is 2500.00 and barrel_slots_used is 1."""
    scenario = setup_active_contract()
    tank = new_vessel(vessel_code="T-101")
    barrel = new_vessel(
        vessel_code="BBL-0442",
        vessel_type="BARREL",
        capacity_gallons=60,
        facility_zone="BARREL_HALL",
    )
    tank_allocation = reserve_allocation(
        scenario["contract"]["id"], tank["id"], allocated_gallons=2500
    )
    barrel_allocation = reserve_allocation(
        scenario["contract"]["id"], barrel["id"], allocated_gallons=60
    )
    scenario.update(
        {
            "tank": tank,
            "barrel": barrel,
            "tank_allocation": tank_allocation,
            "barrel_allocation": barrel_allocation,
        }
    )
    return scenario


def test_client_suspension_cascades_to_contract_and_cancels_reserved_allocations(
    api, facility_admin_headers
):
    """PRD 3.1: "Suspending an `ACTIVE` client sets its `status` to `SUSPENDED`
    and starts a three-hop cascade."
    PRD 3.1: "In the first hop, every contract of that client currently in
    `ACTIVE` moves to `SUSPENDED`, each incrementing its own `version`."
    PRD 3.1: "In the second hop, each contract that just entered `SUSPENDED`
    cancels every one of its own allocations that stood in `RESERVED`; those
    allocations keep a null `lot_id` and a null `released_at`, because nothing
    was ever housed in them."

    Design: Difficulty/transitive_cascade/client_suspend_cascade_contract_to_allocation_to_counters
    """
    scenario = _setup_client_with_two_reserved_allocations()
    before = validate_success(
        api.get_contract(scenario["contract"]["id"], facility_admin_headers)
    )
    assert before["gallons_allocated"] == pytest.approx(2500.00, abs=0.01)
    assert before["barrel_slots_used"] == 1

    suspended = validate_success(
        api.client_status(
            scenario["client"]["id"], {"action": "SUSPEND"}, facility_admin_headers
        )
    )
    assert_client(suspended)
    assert suspended["status"] == "SUSPENDED"

    contract = validate_success(
        api.get_contract(scenario["contract"]["id"], facility_admin_headers)
    )
    assert contract["status"] == "SUSPENDED", "hop 1 must suspend the ACTIVE contract"

    for key in ("tank_allocation", "barrel_allocation"):
        allocation = validate_success(
            api.get_vessel_allocation(scenario[key]["id"], facility_admin_headers)
        )
        assert_vessel_allocation(allocation)
        assert allocation["status"] == "CANCELLED", (
            f"hop 2 must cancel the RESERVED {key}, got {allocation['status']}"
        )
        assert allocation["lot_id"] is None
        assert allocation["released_at"] is None, (
            "a cancelled allocation never stamps a release instant"
        )


def test_client_suspension_recomputes_counters_without_dirtying_cooperage(
    api, facility_admin_headers
):
    """PRD 3.1: "In the third hop, each contract whose allocations were just
    cancelled recomputes `gallons_allocated` and `barrel_slots_used` from the
    allocations that survive in `RESERVED` or `COMMITTED`, incrementing that
    contract's `version` a second time."
    PRD 3.2: "**Cancelling** a `RESERVED` allocation — a `FacilityAdmin`'s
    action — sets it to `CANCELLED`, leaves `released_at` null, and leaves the
    vessel entirely untouched: its `condition` does not become `DIRTY` and its
    `last_released_at` does not move, because no wine was ever in it."

    Design: Difficulty/transitive_cascade/client_suspend_cascade_contract_to_allocation_to_counters
    """
    scenario = _setup_client_with_two_reserved_allocations()

    validate_success(
        api.client_status(
            scenario["client"]["id"], {"action": "SUSPEND"}, facility_admin_headers
        )
    )

    contract = validate_success(
        api.get_contract(scenario["contract"]["id"], facility_admin_headers)
    )
    assert_contract(contract)
    assert contract["gallons_allocated"] == pytest.approx(0.00, abs=0.01), (
        f"hop 3 must recompute gallons_allocated to 0.00, got "
        f"{contract['gallons_allocated']}"
    )
    assert contract["barrel_slots_used"] == 0, (
        f"hop 3 must recompute barrel_slots_used to 0, got {contract['barrel_slots_used']}"
    )

    for key in ("tank", "barrel"):
        vessel = validate_success(
            api.get_vessel(scenario[key]["id"], facility_admin_headers)
        )
        assert_vessel(vessel)
        assert vessel["condition"] == "CLEAN", (
            f"the cancel branch never dirties cooperage; {key} read "
            f"{vessel['condition']}"
        )
        assert vessel["last_released_at"] is None
