"""Community setup: property defaults, unit validation, contract shape, and
parent -> child reachability."""
from test_helpers import (
    ApiErrorId,
    assert_property,
    create_contract_payload,
    create_unit_payload,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import ADMIN, MANAGER, create_property, create_unit


class TestPropertyDefaults:
    def test_create_property_applies_default_timezone(self, api):
        """PRD §3.1: "the `timezone` defaults to America/Los_Angeles for
        schedule display when not supplied."
        PRD §3.1: "`posture`, which is `RESTRICTED` when that count reaches at
        least 3, `ELEVATED` when it is at least 1, and `STANDARD` otherwise."

        Design: Corner/entities/create_property_applies_defaults
        """
        resp = api.create_property({"name": "Default Hall", "address": "1 Default Way"}, ADMIN)
        data = validate_success(resp, 201)
        assert_property(data)
        assert data["timezone"] == "America/Los_Angeles"
        assert data["posture"] == "STANDARD"
        assert data["open_bed_bug_case_count"] == 0
        assert data["version"] == 1


class TestUnitCreation:
    def test_create_unit_missing_floor_returns_invalid_request(self, api):
        """PRD §2.7: "A malformed body, a missing required field, an unknown
        enum member, or a treatment window whose `window_start` is not strictly
        earlier than its `window_end` produces `ERR_INVALID_REQUEST` (HTTP 400)
        at the same existence-and-shape stage."

        Design: Corner/entities/create_unit_missing_required_returns_invalid_request
        """
        prop = create_property(name="Req Hall", address="2 Req Way")
        payload = {"unit_number": "101", "stack_index": 1, "bedrooms": 1}
        resp = api.create_unit(prop["id"], payload, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_get_nonexistent_unit_returns_not_found(self, api):
        """PRD §2.7: "The first identifier that does not resolve to an existing
        resource produces `ERR_NOT_FOUND` (HTTP 404)."
        PRD §2.2: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`."

        Design: Corner/entities/get_nonexistent_unit_returns_not_found
        """
        resp = api.get_unit("8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", ADMIN)
        error_data = validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
        assert error_data["error_id"] == "ERR_NOT_FOUND"
        body = resp.json()
        assert body["response_type"] == "error"
        assert body["meta"]["api_request_id"].startswith("req_")

    def test_create_unit_pest_flag_input_ignored(self, api):
        """PRD §2.5: "Computed fields named throughout this document — a
        property's `posture`, a unit's `pest_flag`, a lease's
        `outstanding_balance_cents`, a technician's `booked_minutes`, an
        inspection's `severity`, a treatment's `planned_minutes`, a case's
        `consecutive_negative_count`, a chargeback's amounts, a packet's
        `pinned_references` — are maintained by the server and are never
        accepted as client input."

        Design: Corner/entities/create_unit_pest_flag_input_ignored
        """
        prop = create_property(name="Comp Hall", address="3 Comp Way")
        payload = create_unit_payload(pest_flag="INFESTED")
        resp = api.create_unit(prop["id"], payload, ADMIN)
        data = validate_success(resp, 201)
        assert data["pest_flag"] == "CLEAR"

    def test_duplicate_unit_number_rejected(self, api):
        """PRD §3.1: "Creating a unit requires a `unit_number` unique within its
        property — a duplicate is rejected with `ERR_DUPLICATE_UNIT_NUMBER`
        (HTTP 409) — plus a `floor` and a `stack_index`, each at least 1, and a
        `bedrooms` count of zero or more."

        Design: Corner/validations/duplicate_unit_number_rejected
        """
        prop = create_property(name="Dup Hall", address="24 Dup Way")
        create_unit(prop["id"], unit_number="101", floor=1, stack_index=1, bedrooms=1)
        resp = api.create_unit(
            prop["id"], create_unit_payload(unit_number="101", floor=2, stack_index=5, bedrooms=2), ADMIN
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_UNIT_NUMBER)


class TestContractShape:
    def test_create_contract_invalid_enum_returns_invalid_request(self, api):
        """PRD §2.7: "A malformed body, a missing required field, an unknown
        enum member, or a treatment window whose `window_start` is not strictly
        earlier than its `window_end` produces `ERR_INVALID_REQUEST` (HTTP 400)
        at the same existence-and-shape stage."
        PRD §3.1: "the `scope_pest_types` array, drawn from `ANTS`, `ROACHES`,
        `RODENTS`, `BED_BUGS`, and `TERMITES`, which must be non-empty"

        Design: Corner/entities/create_contract_invalid_enum_returns_invalid_request
        """
        prop = create_property(name="Enum Hall", address="4 Enum Way")
        payload = create_contract_payload(scope_pest_types=["FLEAS"])
        resp = api.create_contract(prop["id"], payload, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestParentChildReachability:
    def test_children_listed_under_parents(self, api):
        """PRD §3.1: "Contracts, units, and claim packets all record their
        owning community through a server-assigned `property_id` referencing
        the property's `id`."
        PRD §4: "| GET | /pest/properties/{id}/contracts | List contracts of a
        property | ProgramAdmin, PropertyManager, BillingClerk |"
        PRD §4: "| GET | /pest/units/{id}/leases | List leases of a unit |
        ProgramAdmin, PropertyManager, BillingClerk, Resident |"

        Design: Corner/entities/fk_reverse_reachability_children_from_parent
        """
        prop = create_property(name="FK Hall", address="5 FK Way")
        contract = get_success_data(
            api.create_contract(prop["id"], create_contract_payload(scope_pest_types=["ROACHES"]), ADMIN)
        )
        unit = create_unit(prop["id"], unit_number="101")
        lease = get_success_data(
            api.create_lease(
                unit["id"],
                {
                    "start_date": "2026-08-01",
                    "end_date": "2027-07-31",
                    "pest_addendum_signed": True,
                    "chargeback_clause_version": "v2026.1",
                    "chargeback_cap_cents": 50000,
                },
                MANAGER,
            )
        )
        contracts, _ = validate_paginated(api.list_contracts(prop["id"], ADMIN))
        assert [c["id"] for c in contracts] == [contract["id"]]
        leases, _ = validate_paginated(api.list_leases(unit["id"], MANAGER))
        assert [l["id"] for l in leases] == [lease["id"]]
