"""Sign-up period creation, run cutting, board sizing, and basic listings."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_run,
    assert_sign_up_period,
    create_period,
    create_run_piece,
    get_period,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.factories import create_operator_payload, create_sign_up_period_payload
from test_helpers.test_users import TEST_USERS

SO = TEST_USERS["scheduling_officer_headers"]


class TestSignUpPeriodCreation:
    def test_create_applies_documented_defaults(self, api):
        """PRD §3.1: "`daily_ot_threshold_minutes`, the paid minutes in a day
        beyond which the overtime rate applies — an integer from 420 to 600,
        defaulting to 480 (eight hours) when omitted — and
        `weekly_ot_threshold_minutes`, the cumulative straight-time minutes in
        a week beyond which weekly overtime applies — an integer from 2100 to
        2700, defaulting to 2400 (forty hours) when omitted."
        PRD §3.1: "A new period begins in `DRAFT` with `schedule_revision` at 1
        and `picked_through_rank` at 0, and periods can be listed with an
        optional `status` filter."

        Design: Corner/entities/signup_period_create_defaults_applied
        """
        payload = create_sign_up_period_payload(name="Def")
        # Omit the two optional OT thresholds.
        payload.pop("daily_ot_threshold_minutes", None)
        payload.pop("weekly_ot_threshold_minutes", None)
        resp = api.create_sign_up_period(payload, SO)
        created = validate_success(resp, expected_status=201)
        assert_sign_up_period(created)

        fetched = validate_success(api.get_sign_up_period(created["id"], SO))
        assert fetched["daily_ot_threshold_minutes"] == 480
        assert fetched["weekly_ot_threshold_minutes"] == 2400
        assert fetched["status"] == "DRAFT"
        assert fetched["schedule_revision"] == 1
        assert fetched["picked_through_rank"] == 0

    def test_create_missing_required_field_rejected(self, api):
        """PRD §2.6: "a malformed request body — a missing required field, a
        wrong-typed value, or a value outside a declared range or enumeration —
        is rejected with `ERR_VALIDATION` (HTTP 400)."

        Design: Corner/entities/signup_period_missing_required_field_rejected
        """
        payload = create_sign_up_period_payload(name="Bad")
        payload.pop("spread_limit_minutes")
        resp = api.create_sign_up_period(payload, SO)
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

    def test_initial_state_is_draft(self, api):
        """PRD §3.1: "A new period begins in `DRAFT` with `schedule_revision`
        at 1 and `picked_through_rank` at 0, and periods can be listed with an
        optional `status` filter."

        Design: Corner/state_machines/signup_initial_state_draft
        """
        period = create_period(name="IS")
        assert period["status"] == "DRAFT"
        fetched = get_period(period["id"])
        assert fetched["status"] == "DRAFT"


class TestOperatorRead:
    def test_get_missing_operator_not_found(self, api):
        """PRD §2.5: "The request is rejected with `ERR_NOT_FOUND` at the first
        identifier that does not resolve to an existing resource, and no later
        segment is examined."

        Design: Corner/entities/operator_get_not_found
        """
        resp = api.get_operator(NON_EXISTENT_UUID, SO)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestRunComputedFields:
    def test_spread_platform_paid_computed_below_break_line(self, api):
        """PRD §3.2: "`spread_minutes` is the largest `release_minutes` among
        the run's pieces minus the smallest `report_minutes` among them — the
        elapsed span from first report to final release. `platform_minutes` is
        the sum of the per-piece `platform_minutes`. `paid_minutes` is the
        platform time plus the break credit: the period's `paid_break_minutes`
        when the spread reaches ten hours (600 minutes) or more, and zero below
        that line."

        Design: Corner/entities/run_computed_fields_correct
        """
        period = create_period(name="CF")
        resp = api.create_run(
            period["id"],
            {
                "run_number": "RC",
                "service_date": "2026-09-07",
                "pieces": [create_run_piece(300, 800, 470)],
            },
            SO,
        )
        run = validate_success(resp, expected_status=201)
        assert_run(run)
        assert run["spread_minutes"] == 500
        assert run["platform_minutes"] == 470
        assert run["paid_minutes"] == 470  # spread 500 < 600 -> no break credit
        assert run["status"] == "CUT"

    def test_break_credit_applies_at_spread_exactly_600(self, api):
        """PRD §3.2: "`paid_minutes` is the platform time plus the break
        credit: the period's `paid_break_minutes` when the spread reaches ten
        hours (600 minutes) or more, and zero below that line."

        Design: Corner/entities/run_break_credit_at_spread_600
        """
        period = create_period(name="BC", paid_break_minutes=30)
        resp = api.create_run(
            period["id"],
            {
                "run_number": "RB",
                "service_date": "2026-09-07",
                "pieces": [create_run_piece(100, 700, 500)],
            },
            SO,
        )
        run = validate_success(resp, expected_status=201)
        assert run["spread_minutes"] == 600
        assert run["paid_minutes"] == 530  # 500 platform + 30 break credit

    def test_over_spread_run_auto_withdrawn_at_cut(self, api):
        """PRD §3.2: "Validation requires at least one run to exist under the
        period's current `schedule_revision` — otherwise the attempt is
        `ERR_INVALID_STATE` — and it disposes of every run of the current
        revision still in `CUT`: a run whose `spread_minutes` is within the
        period's `spread_limit_minutes` moves to `VALIDATED`, while a run whose
        spread exceeds the limit moves straight to `WITHDRAWN`."

        Design: Corner/state_machines/over_spread_run_auto_withdrawn_at_cut
        """
        period = create_period(name="OS", spread_limit_minutes=780)
        resp = api.create_run(
            period["id"],
            {
                "run_number": "RX",
                "service_date": "2026-09-07",
                "pieces": [create_run_piece(0, 800, 400)],
            },
            SO,
        )
        run = validate_success(resp, expected_status=201)
        validate_success(api.cut_runs(period["id"], SO))
        fetched = validate_success(api.get_run(run["id"], SO))
        assert fetched["status"] == "WITHDRAWN"  # spread 800 > 780

    def test_within_spread_run_validated_at_cut(self, api):
        """PRD §3.2: "a run whose `spread_minutes` is within the period's
        `spread_limit_minutes` moves to `VALIDATED`, while a run whose spread
        exceeds the limit moves straight to `WITHDRAWN`."

        Design: Corner/state_machines/over_spread_run_auto_withdrawn_at_cut
        """
        period = create_period(name="OS2", spread_limit_minutes=780)
        resp = api.create_run(
            period["id"],
            {
                "run_number": "ROK",
                "service_date": "2026-09-07",
                "pieces": [create_run_piece(300, 700, 400)],
            },
            SO,
        )
        run = validate_success(resp, expected_status=201)
        validate_success(api.cut_runs(period["id"], SO))
        fetched = validate_success(api.get_run(run["id"], SO))
        assert fetched["status"] == "VALIDATED"  # spread 400 <= 780


class TestListPagination:
    def test_list_pagination_envelope(self, api):
        """PRD §2.3: "The `limit` parameter caps the number of items returned;
        when omitted it defaults to 10, and it is bounded below by 1 and above
        by 100. The `offset` parameter states how many items to skip and
        defaults to 0."
        PRD §2.3: "List responses carry the following pagination fields in the
        `meta` object of the response envelope: `limit`, `offset`,
        `total_count`, and `has_more`."

        Design: Corner/entities/list_pagination_envelope
        """
        api.create_operator(
            create_operator_payload(employee_number="E1", full_name="A", hire_date="2000-01-01"),
            SO,
        )
        api.create_operator(
            create_operator_payload(employee_number="E2", full_name="B", hire_date="2001-01-01"),
            SO,
        )
        resp = api.list_operators(SO, params={"limit": 1, "offset": 0})
        data, meta = validate_paginated(resp)
        assert len(data) == 1
        assert meta["total_count"] == 2
        assert meta["has_more"] is True
        assert meta["limit"] == 1
        assert meta["offset"] == 0


class TestReverseLookup:
    def test_runs_of_period_scoped_to_period(self, api):
        """PRD §3.2: "The run records the `sign_up_period_id` it belongs to and
        the `schedule_revision` under which it was cut, and it enters the world
        in `CUT` status with `awarded_operator_id` null."

        Design: Corner/entities/fk_reverse_reachability_runs_of_period
        """
        p1 = create_period(name="P1")
        p2 = create_period(name="P2")
        api.create_run(
            p1["id"],
            {"run_number": "R1", "service_date": "2026-09-07",
             "pieces": [create_run_piece(300, 700, 400)]},
            SO,
        )
        data, meta = validate_paginated(api.list_runs(p2["id"], SO))
        assert data == [], f"period P2 should have no runs, got {data}"
        assert meta["total_count"] == 0


class TestLifecycleGuards:
    def test_cut_runs_from_open_rejected(self, api):
        """PRD §3.2: "The period itself advances from `DRAFT` to `RUNS_CUT`."
        PRD §2.6: "then whether the target resource's current state permits the
        operation at all (`ERR_INVALID_STATE`, HTTP 409)."

        Design: Corner/state_machines/invalid_transition_cut_runs_from_open
        """
        from test_helpers import create_open_period
        period, _runs = create_open_period()
        assert period["status"] == "OPEN"
        resp = api.cut_runs(period["id"], SO)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_open_picking_from_implemented_rejected(self, api):
        """PRD §3.5: "With the work materialized, the period moves from
        `LOCKED` to `IMPLEMENTED` — one of its two terminal states, the other
        being `CANCELLED`."
        PRD §2.6: "then whether the target resource's current state permits the
        operation at all (`ERR_INVALID_STATE`, HTTP 409)."

        Design: Corner/state_machines/terminal_state_lockdown_implemented
        """
        from test_helpers import (
            award_run_to_operator,
            create_operator,
            create_picking_period,
            implement_period,
            lock_period,
        )
        period, runs = create_picking_period()
        operator = create_operator()
        award_run_to_operator(period["id"], operator["id"], runs[0]["id"])
        lock_period(period["id"])
        implement_period(period["id"])
        assert get_period(period["id"])["status"] == "IMPLEMENTED"
        resp = api.open_picking(period["id"], SO)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
