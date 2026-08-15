"""Program lifecycle: creation defaults, activation gates, OCC config patch,
sweep idempotency, and the error envelope."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_control,
    assert_iso_instant_equal,
    assert_safety_program,
    assess_hazard,
    create_active_program,
    create_hazard_record,
    create_program,
    create_program_payload,
    get_program,
    get_success_data,
    set_clock,
    setup_roster,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["ehs_admin_headers"]


class TestProgramCreation:
    def test_program_creation_defaults_applied(self, api):
        """PRD §3.1: "Two thresholds may be tuned at creation:
        `near_miss_floor_ratio`, the minimum near-miss share of triaged reports
        tolerated before the reporting-integrity flag rises, defaulting to 0.20,
        and `quorum_min`, the minimum committee-member attendance for a valid
        meeting, defaulting to 5."
        PRD §3.1: "A new program is born in `DRAFT`, with
        `remaining_budget_cents` initialized to the full `incentive_budget_cents`
        and `posture` starting at `NORMAL`."

        Design: Corner/entities/program_creation_defaults_applied
        """
        set_clock("2026-06-01T00:00:00Z")
        program = validate_success(
            api.create_program(create_program_payload(incentive_budget_cents=500_000),
                               ADMIN),
            expected_status=201)
        assert_safety_program(program)
        assert program["status"] == "DRAFT"
        assert program["posture"] == "NORMAL"
        assert program["version"] == 1
        assert program["near_miss_floor_ratio"] == pytest.approx(0.20, abs=1e-9)
        assert program["quorum_min"] == 5
        assert program["remaining_budget_cents"] == 500_000, \
            "remaining budget initialized from the full incentive budget"
        assert program["sweep_index"] == 0
        assert program["integrity_flag"] is False

    def test_program_create_missing_required_field_returns_invalid_request(self, api):
        """PRD §2.6: "Only then is the request body examined for well-formedness
        — missing required fields, enum values outside their declared sets, a
        `severity` or `probability` outside the one-to-five range, negative money
        or counts, a `scheduled_end` that is not after `scheduled_start`, a FAIL
        verification outcome missing its note or new due date, a deny or void
        missing its reason, or a contractor resubmission that changes no metric
        — all of which yield `ERR_INVALID_REQUEST`."

        Design: Corner/entities/program_create_missing_required_field_returns_invalid_request
        """
        set_clock("2026-06-01T00:00:00Z")
        payload = create_program_payload()
        del payload["program_year"]
        resp = api.create_program(payload, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        _rows, meta = validate_paginated(api.list_programs(ADMIN))
        assert meta["total_count"] == 0, "the rejected create must not persist a program"

    def test_program_create_missing_auth_returns_unauthenticated(self, api):
        """PRD §2.1: "A request whose `X-User-Role` is not one of these declared
        roles, or whose `X-User-ID` header is missing, is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/program_create_missing_auth_returns_unauthenticated
        """
        resp = api.create_program(create_program_payload(), None)
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


class TestActivationGates:
    def test_payroll_incomplete_blocks_activate(self, api):
        """PRD §3.1: "The payroll rate card must cover all three hazard classes
        — `LOW`, `MODERATE`, and `HIGH` — each with positive `payroll_cents`,
        and the ELR card must likewise cover all three classes; an incomplete
        card is rejected with `ERR_PAYROLL_INCOMPLETE`."

        Design: Corner/validations/payroll_incomplete_blocks_activate
        """
        set_clock("2026-06-01T00:00:00Z")
        program = create_program(payroll_by_class=[
            {"hazard_class": "LOW", "payroll_cents": 10_000_000},
            {"hazard_class": "MODERATE", "payroll_cents": 10_000_000},
        ])
        resp = api.activate_program(program["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_PAYROLL_INCOMPLETE)
        assert get_program(program["id"])["status"] == "DRAFT", \
            "rejected activation leaves the program in DRAFT"

    def test_program_already_active_rejected(self, api):
        """PRD §3.1: "Because the enterprise runs one program year at a time, at
        most one SafetyProgram may be `ACTIVE` at any moment; activating while
        another program is active is rejected with
        `ERR_PROGRAM_ALREADY_ACTIVE`."

        Design: Corner/validations/program_already_active_rejected
        """
        set_clock("2026-06-01T00:00:00Z")
        first = create_program(program_year=2025)
        second = create_program(program_year=2026, scoring_variant="BALANCED")
        activate_first = validate_success(api.activate_program(first["id"], ADMIN))
        assert activate_first["status"] == "ACTIVE"
        resp = api.activate_program(second["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_PROGRAM_ALREADY_ACTIVE)
        assert get_program(second["id"])["status"] == "DRAFT"


class TestOccConfigPatch:
    def test_occ_stale_config_patch_returns_412(self, api):
        """PRD §2.8: "A request to update a draft program's incentive
        configuration must carry `expected_program_version`, holding the
        `version` of the program as the client last observed it; if that value
        does not match the program's current `version` — because another
        committed write has advanced it since the client's last read — the
        update is rejected with `ERR_STALE_VERSION` (HTTP 412), and the client
        must re-read before writing."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_config_patch_returns_412
        """
        set_clock("2026-06-01T00:00:00Z")
        program = create_program()
        observed_version = program["version"]
        patched = validate_success(api.patch_incentive_config(
            program["id"],
            {"expected_program_version": observed_version,
             "observation_target_rate": 6.0},
            ADMIN))
        assert patched["observation_target_rate"] == pytest.approx(6.0, abs=1e-9)
        assert patched["version"] == observed_version + 1, \
            "a successful config write increments version"

        resp = api.patch_incentive_config(
            program["id"],
            {"expected_program_version": observed_version,
             "observation_target_rate": 7.0},
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        assert get_program(program["id"])["observation_target_rate"] == pytest.approx(
            6.0, abs=1e-9), "the stale write must not overwrite the committed rate"


class TestSweepIdempotency:
    def test_sweep_second_run_is_idempotent(self, api):
        """PRD §3.7: "Every `PLANNED` control whose `due_date` has passed moves
        to `OVERDUE`, and its hazard's and program's `overdue_control_count` are
        recomputed."
        PRD §3.7: "Failing that, it is `WATCH` when there is at least one
        overdue control, or the `integrity_flag` is raised, or at least one
        recommendation stands `OVERDUE`."
        PRD §3.7: "Each run increments the program's `sweep_index` — a monotone
        counter that starts at zero when the program is created — and its
        `version`"

        Design: Corner/cross_cutting_complexity_layers/sweep_second_run_is_idempotent
        """
        set_clock("2026-06-01T00:00:00Z")
        program = create_active_program()
        _role, employees = setup_roster()
        manager = employees["Marta M"]
        hazard = create_hazard_record(program["id"], manager["id"],
                                      identified_by=manager["id"],
                                      description="Noise")
        hazard = assess_hazard(hazard["id"], manager["id"], severity=3,
                               probability=2)
        add_control(hazard["id"], manager["id"], manager["id"],
                    description="Enclosure", due_date="2026-06-10T00:00:00Z")
        set_clock("2026-06-15T00:00:00Z")

        first = validate_success(api.sweep_program(program["id"], {}, ADMIN))
        assert first["overdue_controls"] == 1, "one PLANNED control past due flips"
        assert first["posture"] == "WATCH", \
            "one overdue control (< 3, no SLA breach) yields WATCH"
        assert first["sweep_index"] == 1

        second = validate_success(api.sweep_program(program["id"], {}, ADMIN))
        assert second["overdue_controls"] == 0, \
            "already-OVERDUE rows are not flipped a second time"
        assert second["posture"] == "WATCH", "posture persists without clock movement"
        assert second["sweep_index"] == 2, "every sweep run advances the counter"


class TestErrorEnvelope:
    def test_error_envelope_shape(self, api):
        """PRD §2.2: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`."
        PRD §2.10: "The system confirms each path identifier in sequence and
        rejects the request with `ERR_NOT_FOUND` (HTTP 404) at the first
        identifier that does not resolve, before any later identifier or any
        business rule is consulted."

        Design: Corner/errors/error_envelope_shape
        """
        set_clock("2026-06-01T00:00:00Z")
        from test_helpers import NON_EXISTENT_UUID
        resp = api.get_program(NON_EXISTENT_UUID, ADMIN)
        error = validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
        assert error["message"].strip(), "error envelope carries a human message"
        body = resp.json()
        assert body["response_type"] == "error"
        assert body["meta"]["api_request_id"]
        assert body["meta"]["api_request_timestamp"]
        assert set(body["meta"].keys()) == {"api_request_id",
                                            "api_request_timestamp"}
