"""Breadth CRUD, not-found, well-formedness, and pagination tests.

Every test translates exactly one non-stub instance from the corner design index (queue B).
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, NON_EXISTENT_UUID,
    create_client_payload, create_bed_reservation_payload,
    new_client, new_shelter_with_beds, shelter_version,
    TEST_USERS,
)

INTAKE = TEST_USERS["intake_headers"]
SHELTER = TEST_USERS["shelter_manager_headers"]
ADMIN = TEST_USERS["hmis_admin_headers"]


def test_create_client_returns_intake_status(api):
    """PRD §3.1: "A newly registered client enters in `INTAKE` status."

    Design: Corner/entities/create_client_success_returns_intake
    """
    res = api.create_client(
        create_client_payload("New Client", "1990-01-01", household_size=3), INTAKE)
    client = validate_success(res, 201)
    assert client["status"] == "INTAKE"
    assert client["household_size"] == 3


def test_get_missing_client_returns_not_found(api):
    """PRD §2.5: "The first identifier that resolves to nothing yields `ERR_NOT_FOUND` (404).
    This applies to every endpoint."

    Design: Corner/entities/err_get_client_not_found
    """
    res = api.get_client(NON_EXISTENT_UUID, ADMIN)
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)


def test_create_client_missing_dob_rejected(api):
    """PRD §2.5: "The request must be well-formed: all required fields present, all enums and
    types valid, and for any reservation or waitlist window the `entry_date` must be strictly
    before the `expected_exit_date`. A violation yields `ERR_INVALID_REQUEST` (400)."

    Design: Corner/entities/req_create_client_missing_required_returns_invalid_request
    """
    res = api.create_client({"full_name": "No DOB"}, INTAKE)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)


def test_reservation_entry_not_before_exit_rejected(api):
    """PRD §2.5: "for any reservation or waitlist window the `entry_date` must be strictly
    before the `expected_exit_date`. A violation yields `ERR_INVALID_REQUEST` (400)."

    Design: Corner/entities/req_reservation_entry_after_exit_returns_invalid_request
    """
    client = new_client(full_name="Bad Window", dob="1990-01-01")
    shelter, _ = new_shelter_with_beds(("B1",), name="Willow ES")
    shv = shelter_version(shelter["id"])
    res = api.create_bed_reservation(create_bed_reservation_payload(
        client["id"], shelter["id"], "2026-03-20", "2026-03-10", shv), SHELTER)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)


def test_list_clients_pagination_first_page(api):
    """PRD §2.3: "The `limit` parameter caps the number of items returned; it defaults to 10,
    with a minimum of 1 and a maximum of 100."
    PRD §2.3: "Every list response includes `limit`, `offset`, `total_count`, and `has_more`
    in the `meta` object of the envelope."

    Design: Corner/endpoints/ep_list_clients_pagination
    """
    new_client(full_name="Page One", dob="1990-01-01")
    new_client(full_name="Page Two", dob="1990-02-02")

    data, meta = validate_paginated(api.list_clients(ADMIN, params={"limit": 1, "offset": 0}))
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(data) == 1
