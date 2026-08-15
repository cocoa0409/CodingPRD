"""Property configuration defaults, floorplan availability ledger on creation,
system-managed field handling, and floorplan existence checks."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_same_instant,
    create_floorplan_payload,
    create_property,
    is_valid_uuid,
    validate_error,
    validate_success,
)


class TestPropertyDefaults:
    def test_property_creation_applies_config_defaults(self, api, property_manager_headers):
        """PRD §3.1: "`response_time_target_minutes` sets the first-response service
        target and defaults to 60 minutes. `tour_buffer_minutes`, defaulting to 15, is
        the minimum turnaround the system requires between one agent's tours.
        `self_guided_window_minutes`, defaulting to 60, fixes the access-window length
        granted to self-guided visitors. `max_moveins_per_day`, defaulting to 2, caps
        aggregate move-in volume per UTC calendar date at the property.
        `utility_transfer_required`, defaulting to true, decides whether a move-in may
        complete without a confirmed utility transfer."
        PRD §3.1: "`prorate_method` selects how first-period rent is prorated:
        `CALENDAR` prorates by the actual days in the move-in month, `FIXED_30`
        prorates by thirty-day months, and the default is `CALENDAR`."
        PRD §3.1: "Finally, `required_addenda` lists the addendum codes that must be
        snapshotted onto every lease the property generates; it defaults to an empty
        list."

        Design: Corner/entities/property_creation_applies_config_defaults
        """
        resp = api.create_property({"name": "Default Hall", "code": "DFT1"},
                                   property_manager_headers)
        prop = validate_success(resp, 201)
        assert prop["response_time_target_minutes"] == 60
        assert prop["tour_buffer_minutes"] == 15
        assert prop["self_guided_window_minutes"] == 60
        assert prop["max_moveins_per_day"] == 2
        assert prop["utility_transfer_required"] is True
        assert prop["prorate_method"] == "CALENDAR"
        assert prop["required_addenda"] == []


class TestFloorplanCreation:
    def test_floorplan_computed_availability_on_create(self, api, property_manager_headers):
        """PRD §2.7: "A freshly created floorplan starts with `committed_units` at
        zero, so `available_units` equals `total_units`."

        Design: Corner/entities/floorplan_computed_availability_on_create
        """
        prop = create_property(name="Avail Arms", code="AV1")
        resp = api.create_floorplan(
            create_floorplan_payload(prop["id"], name="3BR", bedrooms=3,
                                     base_rent_cents=350000, total_units=4),
            property_manager_headers)
        floorplan = validate_success(resp, 201)
        assert floorplan["committed_units"] == 0
        assert floorplan["available_units"] == 4

    def test_system_fields_input_ignored_on_floorplan_create(self, api,
                                                             property_manager_headers):
        """PRD §2.5: "`id` (string): a unique, server-minted identifier formatted as
        a UUID, with no type prefix."
        PRD §2.5: "`version` (integer): a system-managed integer that increments on
        every mutation of the resource."
        PRD §2.4: "At server startup, before any adjustment, the logical clock reads
        exactly 2026-08-01T00:00:00Z."

        Design: Corner/entities/system_fields_input_ignored_on_floorplan_create
        """
        prop = create_property(name="Sysfield Suites", code="SY1")
        payload = create_floorplan_payload(prop["id"], name="2BR", bedrooms=2,
                                           base_rent_cents=250000, total_units=2)
        payload.update({
            "id": "11111111-1111-1111-1111-111111111111",
            "version": 99,
            "created_at": "2020-01-01T00:00:00Z",
        })
        resp = api.create_floorplan(payload, property_manager_headers)
        floorplan = validate_success(resp, 201)
        # Client-supplied system fields are ignored in favor of server-managed values.
        assert floorplan["id"] != "11111111-1111-1111-1111-111111111111"
        assert is_valid_uuid(floorplan["id"])
        assert floorplan["version"] != 99
        # created_at is stamped from the logical clock at creation, not the client value.
        assert floorplan["created_at"] != "2020-01-01T00:00:00Z"
        assert_same_instant(floorplan["created_at"], "2026-08-01T00:00:00Z",
                            label="Floorplan.created_at")


class TestFloorplanExistence:
    def test_get_nonexistent_floorplan_returns_not_found(self, api,
                                                         property_manager_headers):
        """PRD §2.10: "Third, existence and request shape: path identifiers are
        resolved and each body reference must point at an existing resource — a
        missing property, agent, floorplan, pricing offer, inquiry, tour, waitlist
        entry, application, lease, or move-in surfaces `ERR_PROPERTY_NOT_FOUND`,
        `ERR_AGENT_NOT_FOUND`, `ERR_FLOORPLAN_NOT_FOUND`, `ERR_PRICING_OFFER_NOT_FOUND`,
        `ERR_INQUIRY_NOT_FOUND`, `ERR_TOUR_NOT_FOUND`, `ERR_WAITLIST_ENTRY_NOT_FOUND`,
        `ERR_APPLICATION_NOT_FOUND`, `ERR_LEASE_NOT_FOUND`, or `ERR_MOVE_IN_NOT_FOUND`
        respectively;"

        Design: Corner/entities/get_nonexistent_floorplan_returns_not_found
        """
        resp = api.get_floorplan(NON_EXISTENT_UUID, property_manager_headers)
        validate_error(resp, ApiErrorId.ERR_FLOORPLAN_NOT_FOUND, 404)
