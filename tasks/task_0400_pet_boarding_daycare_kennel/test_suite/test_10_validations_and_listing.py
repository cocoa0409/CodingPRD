"""Temporal/referential validation corners and a paginated list envelope.

Translates corner (B) validations (addon window, cross-facility, belongings)
and endpoints (paginated list) instances.
"""
import pytest
from test_helpers import (
    api_client, get_success_data, validate_success, validate_error, validate_paginated,
    create_reservation_payload, create_addon_payload,
    create_facility, create_owner, create_pet,
    setup_facility_owner_pet, create_run, advance_clock, create_assignment,
    TEST_USERS,
)

MGR = TEST_USERS["manager_headers"]


def test_addon_out_of_window_rejected(api):
    """PRD §3.5: "An owner or staff member adds an `AddOn` with a `kind` of either `BATH`
    or `PLAYTIME` and a `scheduled_date`, which must fall inside the reservation window or
    the booking is rejected with `ERR_ADDON_OUT_OF_WINDOW`."

    Design: Corner/validations/addon_out_of_window_rejected
    """
    facility, owner, pet = setup_facility_owner_pet(deposit_policy="NONE", vaccinate=False, review=None)
    res = get_success_data(api_client.create_reservation(
        facility["id"],
        create_reservation_payload(pet["id"], "OVERNIGHT", "2026-03-01", "2026-03-04"),
        MGR))
    out = api.create_addon(
        res["id"], create_addon_payload("BATH", "2026-03-10"), MGR)
    validate_error(out, "ERR_ADDON_OUT_OF_WINDOW")


def test_cross_facility_pet_reference_rejected(api):
    """PRD §3.6: "The body's references must also be in-facility: the `pet_id`, `run_id`,
    and `package_id` involved must all belong to the reservation's facility, or the create
    is rejected with `ERR_CROSS_FACILITY_REFERENCE`."

    Creating a reservation in facility A with a pet from facility B.

    Design: Corner/validations/cross_facility_pet_reference_rejected
    """
    facA = create_facility(deposit_policy="NONE")
    facB = create_facility(deposit_policy="NONE")
    ownB = create_owner(facB["id"])
    petB = create_pet(ownB["id"], weight_kg=6)
    out = api_client.create_reservation(
        facA["id"],
        create_reservation_payload(petB["id"], "DAYCARE", "2026-03-01", "2026-03-01"),
        MGR)
    validate_error(out, "ERR_CROSS_FACILITY_REFERENCE")


def test_belongings_outstanding_blocks_close(api):
    """PRD §3.8: "The reservation then advances from `CHECKED_OUT` to `CLOSED` only when
    every belonging entry has `returned` true — if any belonging is still outstanding the
    advance is rejected with `ERR_BELONGINGS_OUTSTANDING`."

    Design: Corner/validations/belongings_outstanding_blocks_close
    """
    facility, owner, pet = setup_facility_owner_pet(deposit_policy="NONE")
    run = create_run(facility["id"], label="Pen-V8", kind="DAYCARE_PEN", size_class="LARGE", daycare_capacity=5)
    res = get_success_data(api_client.create_reservation(
        facility["id"],
        create_reservation_payload(
            pet["id"], "DAYCARE", "2026-01-10", "2026-01-10",
            belongings=[{"description": "red leash", "quantity": 1}]),
        MGR))
    create_assignment(res["id"], run["id"], res["version"])
    get_success_data(api_client.confirm_reservation(res["id"], MGR))
    advance_clock(facility["id"], "2026-01-10")
    get_success_data(api_client.check_in(res["id"], MGR))
    get_success_data(api_client.check_out(res["id"], MGR))  # CHECKED_IN -> CHECKED_OUT
    # Second check_out without returning belongings -> blocked.
    out = api.check_out(res["id"], MGR, payload={"return_all_belongings": False})
    validate_error(out, "ERR_BELONGINGS_OUTSTANDING")


def test_list_reservations_paginated_envelope(api):
    """PRD §2.3: "Each list response carries `limit`, `offset`, `total_count`, and
    `has_more` inside the `meta` object of the envelope, where `total_count` reflects the
    full size of the filtered collection and `has_more` indicates whether further pages
    remain."

    A single reservation listed by owner_id -> total_count 1, has_more false.

    Design: Corner/endpoints/list_reservations_paginated_envelope
    """
    facility, owner, pet = setup_facility_owner_pet(deposit_policy="NONE", vaccinate=False, review=None)
    res = get_success_data(api_client.create_reservation(
        facility["id"],
        create_reservation_payload(pet["id"], "DAYCARE", "2026-03-01", "2026-03-01"),
        MGR))
    data, meta = validate_paginated(
        api.list_reservations(MGR, params={"owner_id": owner["id"], "limit": 10, "offset": 0}))
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    assert any(r["id"] == res["id"] for r in data), "the created reservation is listed"
