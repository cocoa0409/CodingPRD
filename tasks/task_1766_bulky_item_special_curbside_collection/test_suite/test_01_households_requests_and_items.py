"""Household registration, request drafting, and item-list retrieval."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
    assert_household,
    assert_pickup_request,
    create_household_payload,
    create_pickup_request_payload,
    get_success_data,
    make_resident_headers,
    set_clock,
    setup_household_with_draft,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestHouseholdRegistration:
    def test_household_creation_applies_defaults(self, api, dispatcher_headers):
        """PRD §3.1: "The registration may optionally carry
        `annual_allowance_items`, the number of items the household may set out
        free of charge each calendar year; when omitted, the household receives
        an annual allowance of 4 items, and the value must be a non-negative
        integer. A new household begins life with `status` equal to `ACTIVE`
        and `version` 1."

        Design: Corner/entities/household_creation_applies_defaults
        """
        resp = api.create_household(
            create_household_payload(
                street_address="100 Default Dr", service_zone="ZONE_NORTH"
            ),
            dispatcher_headers,
        )
        data = validate_success(resp, expected_status=201)
        assert_household(data)
        assert data["annual_allowance_items"] == 4
        assert data["status"] == "ACTIVE"
        assert data["version"] == 1
        assert data["suspension_reason"] is None

    def test_household_get_not_found(self, api, dispatcher_headers):
        """PRD §2.8: "Requests that address nested resources validate every
        identifier strictly left-to-right: the pickup-request id in the path
        first, then any `route_day_id` supplied in the body, then any item
        ids, with the first non-existent identifier rejected as
        `ERR_NOT_FOUND` (HTTP 404) before later checks proceed."

        Design: Corner/entities/household_get_not_found
        """
        resp = api.get_household(NON_EXISTENT_UUID, dispatcher_headers)
        err = validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
        assert err["error_id"] == "ERR_NOT_FOUND"
        assert resp.status_code == 404


class TestRequestDrafting:
    def test_request_initial_state_is_draft(self, api, dispatcher_headers):
        """PRD §3.2: "A resident begins by creating a **PickupRequest** for
        their household — the creation payload names the `household_id` —
        which is born in `DRAFT` with `load_units` 0,
        `provisional_total_cents` 0, and `version` 1."

        Design: Corner/state_machines/request_initial_state_is_draft
        """
        set_clock("2026-08-05T00:00:00Z")
        resp = api.create_household(
            create_household_payload(
                street_address="6 Init St", service_zone="ZONE_NORTH"
            ),
            dispatcher_headers,
        )
        hh = get_success_data(resp)
        resp = api.create_pickup_request(
            create_pickup_request_payload(hh["id"]),
            make_resident_headers(hh["id"]),
        )
        data = validate_success(resp, expected_status=201)
        assert_pickup_request(data)
        assert data["status"] == "DRAFT"
        assert data["route_day_id"] is None
        assert data["final_total_cents"] is None
        assert data["amnesty_applied"] is False
        assert data["load_units"] == 0
        assert data["provisional_total_cents"] == 0
        assert data["version"] == 1

    def test_fk_reverse_reachability_items_of_request(self, api):
        """PRD §2.8: "From a pickup request one can list its items, its fee
        assessments, its notifications, and any dumping reports linked to
        it."

        Design: Corner/entities/fk_reverse_reachability_items_of_request
        """
        hh, req, _ = setup_household_with_draft(
            street_address="4 FK Ln", service_zone="ZONE_WEST", items=()
        )
        resp = api.list_items(req["id"], make_resident_headers(hh["id"]))
        data, meta = validate_paginated(resp)
        assert data == []
        assert meta["total_count"] == 0
