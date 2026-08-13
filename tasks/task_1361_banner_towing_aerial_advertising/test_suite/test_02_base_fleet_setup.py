"""Base, aircraft, and pilot registration: creation defaults, retrieval,
and payload validation."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_base,
    create_aircraft_payload,
    create_base,
    create_pilot_payload,
    is_valid_uuid,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import ADMIN


class TestBaseRegistration:

    def test_base_creation_stores_inputs_and_defaults(self, api):
        """PRD §3.1: "A base is born with `status` `ACTIVE` and may later be
        `CLOSED`." PRD §2.4: "The `id` is a server-minted UUID with no type
        prefix. `created_at` records the creation instant as an ISO 8601 UTC
        timestamp with three fractional digits".

        Design: Corner/entities/base_creation_stores_input_fields_and_defaults
        """
        resp = api.create_base({"code": "KMYB", "name": "Myrtle Beach"}, ADMIN)
        data = validate_success(resp, expected_status=201)
        assert_base(data)
        assert data["code"] == "KMYB"
        assert data["name"] == "Myrtle Beach"
        assert data["status"] == "ACTIVE", \
            f"base must be born ACTIVE, got {data['status']}"
        assert data["version"] == 1
        assert is_valid_uuid(data["id"])

    def test_base_get_returns_persisted_fields(self, api):
        """PRD §3.1: a base is "identified by a unique `code` such as an
        airfield identifier, plus a human-readable `name`". PRD §2.2: "Unless
        otherwise noted, operations that create or modify a resource will
        return the created or updated resource object in the data field."

        Design: Corner/entities/base_get_by_id_returns_persisted_fields
        """
        created = create_base(code="KPDK", name="DeKalb-Peachtree")
        resp = api.get_base(created["id"], ADMIN)
        data = validate_success(resp, expected_status=200)
        assert_base(data)
        assert data["id"] == created["id"]
        assert data["code"] == "KPDK"
        assert data["name"] == "DeKalb-Peachtree"

    def test_base_get_nonexistent_returns_not_found(self, api):
        """PRD §2.6: "the request is rejected with `ERR_NOT_FOUND` (HTTP 404)
        at the first identifier that does not correspond to an existing
        resource".

        Design: Corner/entities/base_get_nonexistent_returns_404
        """
        resp = api.get_base(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND, expected_status=404)


class TestFleetRegistrationValidation:

    def test_aircraft_missing_required_field_rejected(self, api):
        """PRD §3.1: "each **Aircraft** is created with a system-wide unique
        `tail_number`, a `model` of `CITABRIA`, `SUPER_CUB`, or `PAWNEE`, a
        rated `max_tow_weight_lbs`, and a published `hourly_rate_cents`".
        PRD §2.7: "A missing required field, a wrong-typed value, or an
        out-of-range scalar ... is rejected with `ERR_INVALID_REQUEST`
        (HTTP 400)."

        Design: Corner/entities/aircraft_creation_missing_required_field_rejected
        """
        base = create_base(code="KMIA", name="Miami")
        payload = create_aircraft_payload()
        payload.pop("hourly_rate_cents")
        resp = api.create_aircraft(base["id"], payload, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)

    def test_pilot_invalid_endorsement_enum_rejected(self, api):
        """PRD §3.1: a pilot carries "a `tow_endorsement_level` of `TRAINEE`,
        `STANDARD`, or `STADIUM_QUALIFIED`". PRD §2.7: "An enum field whose
        value is outside its declared set is rejected with `ERR_INVALID_ENUM`
        (HTTP 400)."

        Design: Corner/entities/pilot_invalid_enum_rejected
        """
        base = create_base(code="KTPA", name="Tampa")
        payload = create_pilot_payload(tow_endorsement_level="SUPERPILOT")
        resp = api.create_pilot(base["id"], payload, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_ENUM, expected_status=400)
