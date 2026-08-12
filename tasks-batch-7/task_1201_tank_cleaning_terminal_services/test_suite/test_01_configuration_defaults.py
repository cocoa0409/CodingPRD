"""Terminal/product/tank registration rules (PRD §2.4, §2.11, §3.1)."""
import pytest

from test_helpers import (
    validate_success, validate_error, NON_EXISTENT_UUID,
    ApiErrorId, TEST_USERS,
    create_terminal_payload, create_product_payload, create_tank_payload,
    create_contractor_payload, create_safety_event_payload,
    create_cleaning_job_payload,
    assert_terminal, assert_safety_event,
    new_ctx, create_job,
    DEFAULTS,
)

ADMIN = TEST_USERS["admin_headers"]
OPERATOR = TEST_USERS["operator_headers"]
EHS = TEST_USERS["ehs_headers"]


class TestTerminalRegistration:
    def test_terminal_creation_applies_governance_defaults(self, api):
        """PRD §3.1: "three tunable governance values with defaults applied when omitted: `safety_score_threshold` defaulting to 85.0, the minimum contractor safety score for qualification, evaluated inclusively; `score_variant` defaulting to `ROLLING_12MO` (the alternative being `LIFETIME`), which pins which variant of the contractor safety score this terminal evaluates; and `mass_balance_tolerance_pct` defaulting to 2.0, the tolerated solids fraction at return-to-service, also inclusive."

        Design: Corner/entities/terminal_creation_applies_defaults
        """
        res = api.create_terminal(
            create_terminal_payload(name="Defaults Terminal",
                                    wastewater_daily_capacity_liters=50000),
            ADMIN)
        terminal = validate_success(res, 201)
        assert_terminal(terminal)
        assert terminal["safety_score_threshold"] == pytest.approx(85.0)
        assert terminal["score_variant"] == "ROLLING_12MO"
        assert terminal["mass_balance_tolerance_pct"] == pytest.approx(2.0)

    def test_terminal_missing_required_capacity_returns_invalid_request(self, api):
        """PRD §2.11: "Malformed payloads — a missing required field, an unknown enum value, an interval whose start is not before its end, a negative quantity, or a job whose named terminal does not own the named tank — are rejected with `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/terminal_missing_required_capacity_returns_invalid_request
        """
        res = api.create_terminal({"name": "NoCap"}, ADMIN)
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)

    def test_product_invalid_enum_family_rejected(self, api):
        """PRD §3.1: "a `family` drawn from `GASOLINE`, `DISTILLATE`, `JET`, `CRUDE`, `CHEMICAL`, and `VEGOIL`"
        PRD §2.11: "Malformed payloads — a missing required field, an unknown enum value, an interval whose start is not before its end, a negative quantity, or a job whose named terminal does not own the named tank — are rejected with `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/product_invalid_enum_family_rejected
        """
        res = api.create_product(
            create_product_payload(code="KER01", family="KEROSENE"), ADMIN)
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)

    def test_tank_get_nonexistent_returns_not_found(self, api):
        """PRD §2.11: "then existence — path identifiers validated left to right before body foreign-key references, a missing one yielding `ERR_NOT_FOUND` (HTTP 404)"

        Design: Corner/entities/tank_get_nonexistent_returns_not_found
        """
        res = api.get_tank(NON_EXISTENT_UUID, OPERATOR)
        validate_error(res, ApiErrorId.ERR_NOT_FOUND)

    def test_cleaning_job_terminal_tank_mismatch_rejected(self, api):
        """PRD §3.4: "Creation refuses a tank that is not `IN_SERVICE` with `ERR_TANK_NOT_IN_SERVICE` (HTTP 409), and refuses a `terminal_id` that differs from the tank's owning terminal with `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/cleaning_job_terminal_tank_mismatch_rejected
        """
        ctx = new_ctx()
        other_terminal = validate_success(api.create_terminal(
            create_terminal_payload(name="Terminal B",
                                    wastewater_daily_capacity_liters=100000),
            ADMIN), 201)
        res = api.create_cleaning_job(
            create_cleaning_job_payload(
                other_terminal["id"], ctx["tank"]["id"],
                ctx["contractor"]["id"], ctx["gas"]["id"], ctx["dist"]["id"],
                heel_volume_liters_sounding=100, base_service_fee_cents=1000),
            OPERATOR)
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)

    def test_safety_event_is_append_only_without_version_fields(self, api):
        """PRD §2.4: "Safety events are the deliberate exception: a safety event is append-only, carries only `id` and `created_at`, and has neither `updated_at` nor `version`, because events are never modified after being recorded."

        Design: Corner/entities/safety_event_immutable_common_fields_false
        """
        contractor = validate_success(api.create_contractor(
            create_contractor_payload(company_name="EventCo"), ADMIN), 201)
        res = api.create_safety_event(
            create_safety_event_payload(
                contractor["id"], kind="VIOLATION", severity_weight=2,
                occurred_at="2026-04-01T00:00:00Z"),
            EHS)
        event = validate_success(res, 201)
        assert_safety_event(event)
        assert "id" in event and "created_at" in event
        assert "version" not in event and "updated_at" not in event
