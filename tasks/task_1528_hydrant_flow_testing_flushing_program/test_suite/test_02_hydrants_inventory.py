"""Hydrant registration: defaults, conditional-required owner, uniqueness,
and the inspection-create pointer side effect."""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    assert_hydrant,
    assert_inspection,
    api_client,
    TEST_USERS,
    create_program,
    create_zone,
    create_hydrant,
    create_hydrant_payload,
    open_inspection,
    get_hydrant,
    setup_program_zone_hydrant,
)

ADMIN = TEST_USERS["admin_headers"]
OP1 = TEST_USERS["operator_headers"]


class TestHydrantCreate:
    def test_hydrant_create_applies_defaults(self, api):
        """PRD §3.1: "optionally the `outlet_diameter_in` (default 2.5 inches)
        and `discharge_coefficient` (default 0.9) used later by the pitot flow
        formula."
        PRD §3.1: "A newly registered hydrant starts with `status` of
        `IN_SERVICE`, `inspection_tier` of `CURRENT`, `targeted_flush_pending`
        false, `active_outage_id` and `latest_inspection_id` and
        `last_verified_inspection_date` all unset, and both computed fire-flow
        fields — `provisional_fire_flow_gpm` and `approved_fire_flow_gpm` —
        null."

        Design: Corner/entities/hydrant_create_applies_defaults
        """
        program = create_program()
        zone = create_zone()
        resp = api.create_hydrant(
            create_hydrant_payload(
                program["id"], zone["id"],
                hydrant_number="H-100", required_fire_flow_gpm=1500,
            ),
            ADMIN,
        )
        hydrant = validate_success(resp, expected_status=201)
        assert_hydrant(hydrant)
        assert hydrant["outlet_diameter_in"] == 2.5, (
            f"default outlet_diameter_in must be 2.5, got {hydrant['outlet_diameter_in']}"
        )
        assert hydrant["discharge_coefficient"] == 0.9, (
            f"default discharge_coefficient must be 0.9, got {hydrant['discharge_coefficient']}"
        )
        assert hydrant["status"] == "IN_SERVICE"
        assert hydrant["inspection_tier"] == "CURRENT"
        assert hydrant["targeted_flush_pending"] is False
        assert hydrant.get("provisional_fire_flow_gpm") is None
        assert hydrant.get("approved_fire_flow_gpm") is None
        assert isinstance(hydrant["version"], int) and hydrant["version"] >= 1

    def test_hydrant_create_private_missing_owner_returns_invalid_request(self, api):
        """PRD §3.1: "When `ownership` is `PRIVATE`, the payload must include
        `private_owner_id` referencing a registered `PrivateOwner`; when
        `ownership` is `MUNICIPAL`, `private_owner_id` must be absent."
        PRD §3.1: "A violation of this conditional-required rule is rejected
        with `ERR_INVALID_REQUEST`."

        Design: Corner/entities/hydrant_create_private_missing_owner_returns_invalid_request
        """
        program = create_program()
        zone = create_zone()
        resp = api.create_hydrant(
            create_hydrant_payload(
                program["id"], zone["id"],
                hydrant_number="H-100", ownership="PRIVATE",
                required_fire_flow_gpm=1500,
            ),
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)
        # No hydrant persisted: the list stays empty.
        data, meta = __import__("test_helpers").validate_paginated(api.list_hydrants(ADMIN))
        assert meta["total_count"] == 0, "rejected create must not persist a hydrant"

    def test_hydrant_number_duplicate_rejected(self, api):
        """PRD §3.1: "A `ProgramAdmin` creates a `Hydrant` by supplying a
        globally unique `hydrant_number` (a duplicate is rejected with
        `ERR_HYDRANT_NUMBER_NOT_UNIQUE`), the `program_id` of the owning
        seasonal program, the `zone_id` of the pressure zone the hydrant sits
        in, the `ownership` classification (`MUNICIPAL` or `PRIVATE`), the
        `required_fire_flow_gpm` for the hydrant's location, and optionally the
        `outlet_diameter_in` (default 2.5 inches) and `discharge_coefficient`
        (default 0.9) used later by the pitot flow formula."

        Design: Corner/entities/hydrant_number_duplicate_rejected
        """
        program, zone, hydrant = setup_program_zone_hydrant(hydrant_overrides={"hydrant_number": "H-100"})
        resp = api.create_hydrant(
            create_hydrant_payload(
                program["id"], zone["id"],
                hydrant_number="H-100", required_fire_flow_gpm=2000,
            ),
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_HYDRANT_NUMBER_NOT_UNIQUE, 409)


class TestHeaderEnforcement:
    def test_hydrant_create_missing_header_rejected(self, api):
        """PRD §2.1: "Every request must carry two headers: `X-User-ID` and
        `X-User-Role`. If either header is missing or empty, the request is
        rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/validations/hydrant_create_missing_header_rejected
        """
        resp = api.create_hydrant(
            {
                "hydrant_number": "H-100",
                "program_id": "00000000-0000-0000-0000-000000000000",
                "zone_id": "00000000-0000-0000-0000-000000000000",
                "ownership": "MUNICIPAL",
                "required_fire_flow_gpm": 1000,
            },
            headers={},
        )
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER, 400)


class TestInspectionCreateSideEffect:
    def test_inspection_create_sets_hydrant_pointer_and_bumps_version(self, api):
        """PRD §3.2: "A successful create starts the inspection in `SCHEDULED`
        status and writes the new inspection's id into the hydrant's
        `latest_inspection_id`, incrementing the hydrant's `version` by one."

        Design: Corner/entities/inspection_create_sets_hydrant_pointer_and_bumps_version
        """
        program, zone, hydrant = setup_program_zone_hydrant()
        version_before = hydrant["version"]

        inspection = open_inspection(hydrant["id"])
        assert_inspection(inspection)
        assert inspection["status"] == "SCHEDULED"

        after = get_hydrant(hydrant["id"])
        assert after["latest_inspection_id"] == inspection["id"], (
            "hydrant latest_inspection_id must point at the new inspection"
        )
        assert after["version"] == version_before + 1, (
            f"hydrant version must increment by one: {version_before} -> {after['version']}"
        )
