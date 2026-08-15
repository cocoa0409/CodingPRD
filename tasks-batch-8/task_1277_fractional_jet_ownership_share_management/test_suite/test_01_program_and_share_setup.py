"""Program foundation, entity defaults, pagination, and share creation rules."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    assert_program,
    assert_share,
    create_aircraft_class,
    create_owner,
    create_program,
    create_program_payload,
    create_share_payload,
    get_success_data,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["program_admin_headers"]


class TestProgramCreation:
    def test_program_creation_applies_active_posture_and_system_fields(self, api):
        """PRD §2.9: "A program's `program_posture` takes one of four values — `ACTIVE`,
        `SUSPENDED`, `WINDING_DOWN`, or `CLOSED` — and begins at `ACTIVE` when the program
        is created."
        PRD §2.4: "At server startup the clock reads exactly 2026-08-01T00:00:00Z."

        Design: Corner/entities/program_creation_applies_defaults_and_system_fields
        """
        resp = api.create_program(
            create_program_payload(
                program_code="FJX-EN1", currency="USD",
                contract_year_start_month=8, peak_day_calendar=["2026-11-26"],
            ),
            ADMIN,
        )
        data = validate_success(resp, 201)
        assert_program(data)
        assert data["program_posture"] == "ACTIVE", "new program must open ACTIVE"
        assert is_valid_uuid(data["id"])
        # created_at is stamped from the logical clock, which starts at the default instant
        assert data["created_at"].startswith("2026-08-01T00:00:00"), (
            f"created_at should reflect the startup clock, got {data['created_at']}"
        )
        assert isinstance(data["version"], int) and data["version"] >= 1


class TestNotFound:
    def test_get_owner_with_nonexistent_id_returns_not_found(self, api):
        """PRD §2.8: "Every resource identifier in the path exists, validated left to
        right — otherwise `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/entity_get_not_found
        """
        create_program(program_code="FJX-EN4")
        resp = api.get_owner(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
        assert resp.status_code == 404


class TestPagination:
    def test_list_aircraft_classes_paginates_with_envelope_meta(self, api):
        """PRD §2.3: "The `meta` object of list responses carries the pagination fields
        `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/list_pagination_envelope
        """
        program = create_program(program_code="FJX-EN5")
        create_aircraft_class(program["id"], class_code="LIGHT")
        create_aircraft_class(program["id"], class_code="MID")
        create_aircraft_class(program["id"], class_code="HEAVY")

        resp = api.list_aircraft_classes(
            ADMIN, params={"program_id": program["id"], "limit": 2, "offset": 0}
        )
        page1, meta1 = validate_paginated(resp)
        assert len(page1) == 2, f"limit=2 page should carry 2 items, got {len(page1)}"
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True

        resp2 = api.list_aircraft_classes(
            ADMIN, params={"program_id": program["id"], "limit": 2, "offset": 2}
        )
        page2, meta2 = validate_paginated(resp2)
        assert len(page2) == 1, f"offset=2 page should carry the last item, got {len(page2)}"
        assert meta2["has_more"] is False


class TestContextAndPayloadValidation:
    def test_request_without_role_header_rejected(self, api):
        """PRD §2.1: "A request missing either header, or presenting a role the system
        does not recognize, is rejected with `ERR_MISSING_OR_INVALID_CONTEXT` (HTTP 400)."

        Design: Corner/rbac/missing_context_headers_unauthenticated
        """
        program = create_program(program_code="FJX-RB3")
        headers_without_role = {
            "X-User-ID": "test-no-role",
            "Content-Type": "application/json",
        }
        resp = api.get_program(program["id"], headers_without_role)
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_CONTEXT)
        assert resp.status_code == 400

    def test_create_share_missing_purchase_price_rejected(self, api):
        """PRD §2.8: "Independent of this pipeline, a malformed request body, a missing
        required field, or a wrong-typed value is rejected with `ERR_INVALID_REQUEST`
        (HTTP 400)."

        Design: Corner/endpoints/missing_required_field_invalid_request
        """
        program = create_program(program_code="FJX-EP2")
        cls = create_aircraft_class(program["id"], class_code="MID")
        owner = create_owner(program["id"], legal_name="EP2 Owner")
        payload = create_share_payload(owner["id"], cls["id"])
        del payload["purchase_price_cents"]
        resp = api.create_share(payload, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        assert resp.status_code == 400


class TestShareFractionValidation:
    @pytest.mark.parametrize("numerator,denominator", [(1, 5), (5, 4), (0, 8)])
    def test_invalid_fraction_rejected(self, api, numerator, denominator):
        """PRD §3.2: "The denominator must be one of 4, 8, 16, or 32, and the numerator
        must be at least 1 and no greater than the denominator; any other combination is
        rejected with `ERR_INVALID_FRACTION` (HTTP 422)."

        Design: Corner/entities/share_invalid_fraction_denominator_rejected
        """
        program = create_program(program_code=f"FJX-EN2-{numerator}-{denominator}")
        cls = create_aircraft_class(program["id"], class_code="LIGHT")
        owner = create_owner(program["id"], legal_name="EN2 Owner")
        payload = create_share_payload(
            owner["id"], cls["id"],
            fraction_numerator=numerator, fraction_denominator=denominator,
        )
        resp = api.create_share(payload, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_FRACTION)
        assert resp.status_code == 422


class TestShareActivationEntitlement:
    def test_activation_computes_entitlement_and_seeds_depreciation(self, api):
        """PRD §3.2: "Upon activation the share's annual entitlement is computed as the
        ownership fraction multiplied by the 800 block hours a full share carries per
        contract year, rounded half-up to two decimal places, and `hours_remaining_cy`
        is initialized to that full `annual_entitlement_hours`."
        PRD §3.2: "the share's depreciation schedule is created immediately with
        `basis_cents` equal to the purchase price"

        Design: Corner/entities/share_entitlement_computed_field
        """
        program = create_program(program_code="FJX-EN3")
        cls = create_aircraft_class(program["id"], class_code="LIGHT")
        owner = create_owner(program["id"], legal_name="EN3 Owner")
        share = get_success_data(api.create_share(
            create_share_payload(
                owner["id"], cls["id"],
                fraction_numerator=1, fraction_denominator=16,
                purchase_price_cents=1200000,
            ),
            ADMIN,
        ))
        resp = api.activate_share(share["id"], ADMIN)
        data = validate_success(resp, 200)
        assert_share(data)
        assert data["annual_entitlement_hours"] == pytest.approx(50.00, abs=0.005), (
            f"1/16 of 800 must be 50.00, got {data['annual_entitlement_hours']}"
        )
        assert data["hours_remaining_cy"] == pytest.approx(50.00, abs=0.005)
        assert data["share_status"] == "ACTIVE"

        # Depreciation schedule rides along with the share, basis == purchase price
        scheds, _meta = validate_paginated(
            api.list_depreciation_schedules(ADMIN, params={"share_id": share["id"]})
        )
        assert len(scheds) >= 1
        assert any(s["basis_cents"] == 1200000 for s in scheds), (
            f"expected a schedule with basis_cents 1200000, got {scheds}"
        )
