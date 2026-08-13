"""Plant configuration defaults, milk-intake creation rules, safety gates,
authentication, and authorization boundary checks."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    assert_milk_intake,
    assert_plant,
    create_intake,
    create_milk_intake_payload,
    create_plant,
    create_plant_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["plant_admin_headers"]
RECEIVER = TEST_USERS["milk_receiver_headers"]


class TestPlant:
    def test_plant_creation_applies_defaults_and_computed_fields(self, api):
        """PRD §3.1: "the `export_listed` flag, which records whether the plant
        appears on the federal export-eligible regulatory listing, defaults to
        `false` when omitted, and a later plant update may flip it — each such
        update increments the plant's `version` by one."
        PRD §3.1: "The plant's `total_aging_capacity_wheels` is a computed
        ledger, the sum of `capacity_wheels` over all of the plant's aging
        rooms that are not `DECOMMISSIONED`; a new plant starts at zero."

        Design: Corner/entities/plant_creation_applies_defaults_and_computed_fields
        """
        plant = create_plant(name="Defaults Plant", license_number="WI-200")
        fetched = validate_success(api.get_plant(plant["id"], ADMIN))
        assert_plant(fetched)
        assert fetched["export_listed"] is False
        assert fetched["total_aging_capacity_wheels"] == 0
        assert fetched["version"] == 1

    def test_plant_get_not_found_returns_404(self, api):
        """PRD §2.6: "The request is rejected with `ERR_NOT_FOUND` (HTTP 404) at
        the first identifier that does not resolve to an existing resource, and
        no later validation runs."

        Design: Corner/entities/plant_get_not_found_returns_404
        """
        resp = api.get_plant(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND, 404)


class TestMilkIntakeCreation:
    def test_milk_intake_missing_required_field_rejected(self, api):
        """PRD §3.2: "A `MilkReceiver` records each tanker receipt under its
        plant with the external `hauler_ticket` manifest reference, the
        `received_at` timestamp, the `volume_liters` delivered, the lab-measured
        `fat_pct` (for example 3.85) and `protein_pct` (for example 3.10), the
        `somatic_cell_count` per milliliter, and the rapid-screen
        `antibiotics_detected` flag, which defaults to `false` when omitted."

        Design: Corner/entities/milk_intake_missing_required_field_rejected
        """
        plant = create_plant(license_number="WI-201")
        payload = {
            "hauler_ticket": "HT-1",
            "received_at": "2026-08-01T01:00:00Z",
            "fat_pct": 3.7,
            "protein_pct": 3.0,
            "somatic_cell_count": 100000,
        }
        resp = api.create_milk_intake(plant["id"], payload, RECEIVER)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)

    def test_milk_intake_antibiotics_default_false(self, api):
        """PRD §3.2: "the rapid-screen `antibiotics_detected` flag, which
        defaults to `false` when omitted. The intake is born `RECEIVED` with
        `consumed_liters` at zero."

        Design: Corner/entities/milk_intake_antibiotics_default_false
        """
        plant = create_plant(license_number="WI-202")
        resp = api.create_milk_intake(
            plant["id"], create_milk_intake_payload(), RECEIVER
        )
        intake = validate_success(resp, 201)
        assert_milk_intake(intake)
        assert intake["antibiotics_detected"] is False
        assert intake["status"] == "RECEIVED"

    def test_milk_intake_invalid_enum_or_type_rejected(self, api):
        """PRD §2.9: "A request whose payload is malformed — an unrecognized
        enum value, a non-positive quantity, or a booking interval whose end is
        not after its start — is rejected with `ERR_INVALID_REQUEST` (HTTP 400)
        when the request is parsed, before any business rule runs."

        Design: Corner/entities/milk_intake_invalid_enum_or_type_rejected
        """
        plant = create_plant(license_number="WI-203")
        payload = create_milk_intake_payload(somatic_cell_count="high")
        resp = api.create_milk_intake(plant["id"], payload, RECEIVER)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)

    def test_child_list_pagination_envelope_fields(self, api):
        """PRD §2.3: "List responses include `limit`, `offset`, `total_count`,
        and `has_more` in the `meta` object of the response envelope."
        PRD §2.3: "Milk intakes filter by `plant_id` and `status`;"

        Design: Corner/entities/child_list_pagination_envelope_fields
        """
        plant = create_plant(license_number="WI-206")
        create_intake(plant["id"], accept=False, hauler_ticket="HT-1")
        create_intake(
            plant["id"], accept=False, hauler_ticket="HT-2",
            received_at="2026-08-01T02:00:00Z",
        )
        resp = api.list_milk_intakes(
            RECEIVER, params={"plant_id": plant["id"], "limit": 1, "offset": 0}
        )
        rows, meta = validate_paginated(resp)
        assert meta["total_count"] == 2, f"expected total_count 2, got {meta}"
        assert meta["has_more"] is True, f"expected has_more true, got {meta}"
        assert len(rows) == 1, f"expected exactly 1 row under limit=1, got {len(rows)}"
        assert all(row["plant_id"] == plant["id"] for row in rows)


class TestAuthenticationAndAuthorization:
    def test_auth_missing_role_header_returns_unauthenticated(self, api):
        """PRD §2.1: "A request missing either header, or presenting a role the
        system does not recognize, is rejected with `ERR_UNAUTHENTICATED`
        (HTTP 401)."

        Design: Corner/validations/auth_missing_role_header_returns_unauthenticated
        """
        resp = api.create_plant(create_plant_payload(license_number="WI-230"), headers=None)
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, 401)

    def test_existence_checked_after_authorization(self, api):
        """PRD §2.9: "Authorization is second: a recognized role not permitted
        on the endpoint fails with `ERR_UNAUTHORIZED`. Existence is third: any
        unresolvable identifier fails with `ERR_NOT_FOUND` in the left-to-right
        order of §2.6."

        Design: Corner/validations/existence_checked_after_authorization
        """
        resp = api.create_plant(create_plant_payload(license_number="WI-231"), RECEIVER)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, 403)


class TestMilkSafetyBoundary:
    def test_scc_exactly_at_400000_passes_accept(self, api):
        """PRD §3.2: "the `somatic_cell_count` must be no greater than 400,000
        — a reading of exactly 400,000 passes, anything strictly above fails
        with `ERR_SCC_LIMIT` — and the antibiotic screen must be negative, with
        a detected result failing with `ERR_ANTIBIOTIC_POSITIVE`."

        Design: Difficulty/boundary_precision_check/scc_exactly_at_400000_passes_accept
        """
        plant = create_plant(license_number="WI-110")
        intake_ok = create_intake(
            plant["id"], accept=False, somatic_cell_count=400000, hauler_ticket="HT-OK"
        )
        intake_bad = create_intake(
            plant["id"], accept=False, somatic_cell_count=400001,
            hauler_ticket="HT-BAD", received_at="2026-08-01T01:30:00Z",
        )
        ok_data = validate_success(api.accept_milk_intake(intake_ok["id"], RECEIVER))
        assert ok_data["status"] == "ACCEPTED", (
            f"SCC exactly 400000 must pass the safety gate, got {ok_data['status']}"
        )
        bad_resp = api.accept_milk_intake(intake_bad["id"], RECEIVER)
        validate_error(bad_resp, ApiErrorId.ERR_SCC_LIMIT, 422)

    def test_scc_over_limit_rejected(self, api):
        """PRD §3.2: "the `somatic_cell_count` must be no greater than 400,000
        — a reading of exactly 400,000 passes, anything strictly above fails
        with `ERR_SCC_LIMIT`"

        Design: Difficulty/boundary_precision_check/scc_exactly_at_400000_passes_accept
        """
        plant = create_plant(license_number="WI-110B")
        intake = create_intake(plant["id"], accept=False, somatic_cell_count=400001)
        resp = api.accept_milk_intake(intake["id"], RECEIVER)
        err = validate_error(resp, ApiErrorId.ERR_SCC_LIMIT, 422)
        assert err["error_id"] == "ERR_SCC_LIMIT"
        fetched = validate_success(api.get_milk_intake(intake["id"], RECEIVER))
        assert fetched["status"] == "RECEIVED", (
            "a failed acceptance leaves the intake in RECEIVED"
        )


class TestMilkSafetyGates:
    def test_state_beats_business_safety_on_milk_accept(self, api):
        """PRD §2.9: "Fifth, the target resource must be in a state that
        permits the requested transition, failing with `ERR_INVALID_STATE`.
        ... Sixth, the milk safety gates on acceptance: `ERR_SCC_LIMIT` and
        `ERR_ANTIBIOTIC_POSITIVE`."
        PRD §3.2: "Acceptance or rejection attempted on an intake that has
        already left `RECEIVED` fails with `ERR_INVALID_STATE`."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_business_safety_on_milk_accept
        """
        plant = create_plant(license_number="WI-108")
        intake = create_intake(plant["id"], accept=False, somatic_cell_count=999999)
        validate_success(api.reject_milk_intake(intake["id"], RECEIVER))
        resp = api.accept_milk_intake(intake["id"], RECEIVER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)

    def test_state_beats_business_safety_on_antibiotic_positive(self, api):
        """PRD §2.9: "Fifth, the target resource must be in a state that
        permits the requested transition, failing with `ERR_INVALID_STATE`.
        ... Sixth, the milk safety gates on acceptance: `ERR_SCC_LIMIT` and
        `ERR_ANTIBIOTIC_POSITIVE`."
        PRD §3.2: "Acceptance or rejection attempted on an intake that has
        already left `RECEIVED` fails with `ERR_INVALID_STATE`."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_business_safety_on_milk_accept
        """
        plant = create_plant(license_number="WI-108B")
        intake = create_intake(plant["id"], accept=False, antibiotics_detected=True)
        validate_success(api.reject_milk_intake(intake["id"], RECEIVER))
        resp = api.accept_milk_intake(intake["id"], RECEIVER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)

    def test_antibiotic_positive_accept_rejected(self, api):
        """PRD §3.2: "the antibiotic screen must be negative, with a detected
        result failing with `ERR_ANTIBIOTIC_POSITIVE`."

        Design: Corner/errors/error_antibiotic_positive_accept
        """
        plant = create_plant(license_number="WI-253")
        intake = create_intake(plant["id"], accept=False, antibiotics_detected=True)
        resp = api.accept_milk_intake(intake["id"], RECEIVER)
        validate_error(resp, ApiErrorId.ERR_ANTIBIOTIC_POSITIVE, 422)

    def test_milk_intake_rejected_terminal_lockdown(self, api):
        """PRD §3.2: "Rejection moves it `RECEIVED` → `REJECTED`, which is
        terminal; a rejected intake is ineligible for make-sheet commitment
        forever after. Acceptance or rejection attempted on an intake that has
        already left `RECEIVED` fails with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/milk_intake_rejected_terminal_lockdown
        """
        plant = create_plant(license_number="WI-210")
        intake = create_intake(plant["id"], accept=False)
        validate_success(api.reject_milk_intake(intake["id"], RECEIVER))
        resp = api.reject_milk_intake(intake["id"], RECEIVER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)

    def test_milk_intake_invalid_trigger_accept_after_accept(self, api):
        """PRD §3.2: "Acceptance or rejection attempted on an intake that has
        already left `RECEIVED` fails with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/milk_intake_invalid_trigger_accept_after_accept
        """
        plant = create_plant(license_number="WI-211")
        intake = create_intake(plant["id"], accept=True)
        resp = api.accept_milk_intake(intake["id"], RECEIVER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
