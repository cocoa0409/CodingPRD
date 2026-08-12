"""Baseline entity claims: creation defaults, required fields, existence checks,
response envelope shape, append-only ledger surface, and version counters."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_ledger_entry,
    assert_member,
    assert_station,
    create_installment,
    create_member,
    create_member_payload,
    issue_installment,
    list_ledger_entries,
    setup_credited_world,
    validate_error,
    validate_success,
)


def test_member_creation_applies_defaults(api, admin_headers, pool_accountant_headers):
    """PRD §3.1: "A member begins `ACTIVE` and may cycle `ACTIVE` to `SUSPENDED`
    and back to `ACTIVE` without limit."
    PRD §3.1: "A member's `net_ledger_cents` and `deterioration_loss_lbs` start
    at 0 and evolve per §2.8."
    PRD §2.4: "`version` (integer): a system-managed counter starting at creation
    and incremented by exactly 1 on every mutation of the resource, including
    mutations driven by cascading side effects from another resource's
    transition."

    Design: Corner/entities/member_creation_applies_defaults
    """
    res = api.create_member(create_member_payload(
        name="M1", member_code="M-1001", haul_distance_miles=22.5), admin_headers)
    member = validate_success(res, 201)
    assert_member(member)
    assert member["status"] == "ACTIVE"
    assert member["net_ledger_cents"] == 0
    assert member["deterioration_loss_lbs"] == 0
    assert member["version"] == 1


def test_member_create_missing_required_field_returns_invalid_request(api, admin_headers):
    """PRD §3.1: "Registering a member requires a `name`, a cooperative-unique
    `member_code` (for example `M-1001`; a duplicate code is a malformed
    request), and a `haul_distance_miles` figure"
    PRD §2.7: "State-machine and request-shape checks run fifth
    (`ERR_INVALID_STATE`, `ERR_INVALID_REQUEST`, `ERR_TICKET_NOT_CREDITABLE`,
    `ERR_BOOKING_NOT_CONFIRMED`, `ERR_CAMPAIGN_NOT_OPEN`,
    `ERR_POOL_NOT_ACCRUING`, `ERR_PILE_NOT_FILLING`, `ERR_LAB_SAMPLE_REQUIRED`)".

    Design: Corner/entities/member_create_missing_required_field_returns_invalid_request
    """
    payload = {"name": "M1", "haul_distance_miles": 22.5}  # member_code omitted
    res = api.create_member(payload, admin_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_station_computed_fields_input_ignored(api, admin_headers):
    """PRD §2.8: "Several aggregates on stations, members, piles, and pools are
    not stored as authoritative inputs but derived from underlying records, and
    the server recomputes them immediately whenever an underlying record changes."
    PRD §3.1: "A **receiving station** is created by a `COOP_ADMIN` with a `name`
    and a `booking_capacity_tons` ceiling that must be greater than zero".

    Design: Corner/entities/station_computed_fields_input_ignored
    """
    payload = {"name": "ST", "booking_capacity_tons": 100, "booked_tons": 999}
    res = api.create_station(payload, admin_headers)
    station = validate_success(res, 201)
    assert_station(station)
    assert station["booked_tons"] == 0
    assert station["received_tons"] == 0
    assert station["stored_tons"] == 0


def test_ticket_get_not_found_returns_404(api, pool_accountant_headers):
    """PRD §2.7: "every path identifier and every body foreign key (`booking_id`,
    `pile_id`, `ticket_id`, `campaign_id`, `station_id`) must resolve to an
    existing resource, otherwise the request fails with `ERR_NOT_FOUND` (404)".

    Design: Corner/entities/ticket_get_not_found_returns_404
    """
    res = api.get_ticket(NON_EXISTENT_UUID, pool_accountant_headers)
    validate_error(res, ApiErrorId.ERR_NOT_FOUND.value)


def test_pile_requires_existing_station_fk(api, station_operator_headers):
    """PRD §2.7: "every path identifier and every body foreign key (`booking_id`,
    `pile_id`, `ticket_id`, `campaign_id`, `station_id`) must resolve to an
    existing resource, otherwise the request fails with `ERR_NOT_FOUND` (404)".
    PRD §3.8: "A **storage pile** is created by a `STATION_OPERATOR` with a
    `station_id` placing it at a station and a `capacity_tons` that must be
    greater than zero."

    Design: Corner/entities/pile_requires_existing_station_fk
    """
    res = api.create_pile(
        {"station_id": NON_EXISTENT_UUID, "capacity_tons": 200},
        station_operator_headers)
    validate_error(res, ApiErrorId.ERR_NOT_FOUND.value)


def test_ledger_entry_get_not_found_returns_404(api, pool_accountant_headers):
    """PRD §2.7: "every path identifier and every body foreign key (`booking_id`,
    `pile_id`, `ticket_id`, `campaign_id`, `station_id`) must resolve to an
    existing resource, otherwise the request fails with `ERR_NOT_FOUND` (404)".
    PRD §2.8: "Every ledger entry is addressable by its `entry_id`".

    Design: Corner/entities/ledger_entry_is_append_only_immutable
    """
    res = api.get_ledger_entry(NON_EXISTENT_UUID, pool_accountant_headers)
    validate_error(res, ApiErrorId.ERR_NOT_FOUND.value)


def test_ledger_entry_carries_no_version_or_updated_at(api):
    """PRD §2.4: "Because the ledger is an append-only event log in which
    corrections are posted as compensating `REVERSAL` entries rather than edits,
    a ledger entry carries only `id` and `created_at`; both `updated_at` and
    `version` are absent from it."

    Design: Corner/entities/ledger_entry_is_append_only_immutable
    """
    world = setup_credited_world(quick_first=(16.50, 4.50))
    installment = create_installment(world["pool"], 30)
    issue_installment(installment["id"])
    entries = list_ledger_entries(installment_id=installment["id"])
    assert len(entries) == 1, f"Expected one ADVANCE_CREDIT entry, got {len(entries)}"
    entry = entries[0]
    assert_ledger_entry(entry)  # enforces absence of updated_at/version
    assert entry["kind"] == "ADVANCE_CREDIT"


def test_response_envelope_shape_on_success(api, admin_headers, pool_accountant_headers):
    """PRD §2.2: "The `api_request_id` is a server-generated unique identifier
    for the request that starts with `req_`." and "The `response_type` is either
    "object" for a single resource or "array" for a list of resources."

    Design: Corner/endpoints/response_envelope_shape_on_success
    """
    member = create_member()
    res = api.get_member(member["id"], pool_accountant_headers)
    assert res.status_code == 200
    body = res.json()
    assert isinstance(body["meta"]["api_request_id"], str)
    assert body["meta"]["api_request_id"].startswith("req_")
    assert isinstance(body["meta"]["api_request_timestamp"], str)
    assert body["response_type"] == "object"
    assert body["data"]["member_code"] == "M-1001"


def test_entity_version_increments_on_every_mutation(api, admin_headers):
    """PRD §2.4: "`version` (integer): a system-managed counter starting at
    creation and incremented by exactly 1 on every mutation of the resource,
    including mutations driven by cascading side effects from another resource's
    transition."

    Design: Corner/complexity_layers/entity_version_increments_on_every_mutation
    """
    member = create_member()
    assert member["version"] == 1
    suspended = validate_success(api.suspend_member(member["id"], admin_headers), 200)
    assert suspended["version"] == 2
    reinstated = validate_success(api.reinstate_member(member["id"], admin_headers), 200)
    assert reinstated["version"] == 3
