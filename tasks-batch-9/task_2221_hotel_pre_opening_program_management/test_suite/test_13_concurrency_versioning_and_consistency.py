"""Optimistic concurrency, version advancement and immediate consistency.

Two creation endpoints carry an explicit version token: reservation blocks
guard the program row, OS&E orders guard the budget line they spend against.
Both tokens must advance on every write to the entity they guard, and every
derived roll-up a write touches must already be visible to the next read.
"""

from typing import Any, Dict

from prd_bench_local_runner.testing import (
    get_success_data,
    is_iso8601_timestamp,
    validate_error,
    validate_success,
)

from test_helpers import api_errors, factories, fixtures
from test_helpers.assertions import assert_budget_split, assert_cents, assert_ratio
from test_helpers.test_users import (
    COMMERCIAL_DIRECTOR,
    PROCUREMENT_MANAGER,
    PROGRAM_DIRECTOR,
    TALENT_MANAGER,
)

# ─── File-local setup helpers ─────────────────────────────────────────────────


def _booking_open_at_2026_10_01(api) -> Dict[str, Any]:
    """A program at CONSTRUCTION_COMPLETE with booking open and the clock at 2026-10-01.

    One 30-day milestone runs from the construction start, is completed once the
    clock reaches 2026-10-01, and the commercial dimension is then opened, so no
    room nights are committed yet.
    """
    return fixtures.booking_open_program(
        api, finish_iso="2026-10-01T00:00:00Z", duration_days=30
    )


def _program_with_setup_line(api) -> Dict[str, Any]:
    """A PLANNING program holding one SETUP budget line authorized at 1000000 cents."""
    program = fixtures.make_program(api)
    line = fixtures.make_budget_line(
        api, program["id"], category="SETUP", authorized_cents=1000000
    )
    return {"program": program, "budget_line": line}


def _linen_order_payload(program_id: str, line_id: str, token: int) -> Dict[str, Any]:
    return factories.ose_order_payload(
        program_id,
        line_id,
        token,
        description="Guest room linen",
        amount_cents=400000,
        pallet_count=5,
        delivery_window_start="2026-10-01",
        delivery_window_end="2026-10-10",
    )


def _chairs_order_payload(program_id: str, line_id: str, token: int) -> Dict[str, Any]:
    return factories.ose_order_payload(
        program_id,
        line_id,
        token,
        description="Banquet chairs",
        amount_cents=300000,
        pallet_count=4,
        delivery_window_start="2026-10-01",
        delivery_window_end="2026-10-10",
    )


def _block_payload(program_id: str, account_name: str, token: int) -> Dict[str, Any]:
    return factories.reservation_block_payload(
        program_id,
        token,
        account_name=account_name,
        arrival_date="2026-10-05",
        night_count=2,
        room_count=5,
        rate_cents=20000,
    )


def _read_rooms_plan(api, program_id: str) -> Dict[str, Any]:
    plans = get_success_data(
        api.list_hiring_plans(program_id, TALENT_MANAGER, {"department": "ROOMS"})
    )
    assert len(plans) == 1, f"expected exactly one ROOMS plan, got {len(plans)}"
    return plans[0]


def _read_setup_line(api, program_id: str) -> Dict[str, Any]:
    lines = fixtures.read_budget_lines(api, program_id, category="SETUP")
    assert len(lines) == 1, f"expected exactly one SETUP line, got {len(lines)}"
    return lines[0]


class TestStaleProgramVersion:
    def test_replaying_a_consumed_program_version_is_rejected_and_writes_nothing(
        self, api, clock_at_default
    ):
        """A commercial director reads the program once and then files two group
        blocks against that single reading. The first block consumes the token
        and lifts committed room nights to ten; the second replays the spent
        token and is turned away even though twenty room nights would still sit
        far below the two-hundred ceiling and the liability far below its cap.

        If that value does not equal the program's current `version`, the create is rejected with `ERR_STALE_PROGRAM_VERSION` (HTTP 412).

        Design: Corner/cross-cutting complexity layers/stale_expected_program_version_on_block_create_returns_stale_program_version
        """
        built = _booking_open_at_2026_10_01(api)
        program_id = built["program"]["id"]
        token = built["program"]["version"]
        assert built["program"]["commercial_state"] == "BOOKING_OPEN"
        assert built["program"]["committed_room_nights"] == 0

        first = validate_success(
            api.create_reservation_block(
                _block_payload(program_id, "Harbour Regatta", token), COMMERCIAL_DIRECTOR
            ),
            201,
        )
        assert first["state"] == "ACCEPTED"
        assert first["room_nights"] == 10

        after_first = fixtures.read_program(api, program_id)
        assert after_first["committed_room_nights"] == 10
        assert_cents(after_first["contingency_liability_cents"], 262500)
        assert after_first["version"] == token + 1

        stale = api.create_reservation_block(
            _block_payload(program_id, "Coastal Rowing Club", token), COMMERCIAL_DIRECTOR
        )
        validate_error(stale, api_errors.ERR_STALE_PROGRAM_VERSION, 412)

        unchanged = fixtures.read_program(api, program_id)
        assert unchanged["committed_room_nights"] == 10
        assert_cents(unchanged["contingency_liability_cents"], 262500)
        assert unchanged["version"] == token + 1
        assert unchanged["room_night_ceiling"] == 200

    def test_the_refreshed_program_version_lets_the_same_block_through(
        self, api, clock_at_default
    ):
        """Once the client re-reads the program it holds the current token again,
        and the identical block payload is accepted: the committed room nights
        double to twenty and the contingency liability doubles with them.

        A block begins `ACCEPTED` with `at_risk_reason` null, raises the program's `committed_room_nights` by its `room_nights`, reruns the contingency computation and increments the program's `version` by one.

        Design: Corner/cross-cutting complexity layers/stale_expected_program_version_on_block_create_returns_stale_program_version
        """
        built = _booking_open_at_2026_10_01(api)
        program_id = built["program"]["id"]
        token = built["program"]["version"]

        validate_success(
            api.create_reservation_block(
                _block_payload(program_id, "Harbour Regatta", token), COMMERCIAL_DIRECTOR
            ),
            201,
        )
        validate_error(
            api.create_reservation_block(
                _block_payload(program_id, "Coastal Rowing Club", token),
                COMMERCIAL_DIRECTOR,
            ),
            api_errors.ERR_STALE_PROGRAM_VERSION,
            412,
        )

        refreshed_token = fixtures.read_program(api, program_id)["version"]
        second = validate_success(
            api.create_reservation_block(
                _block_payload(program_id, "Coastal Rowing Club", refreshed_token),
                COMMERCIAL_DIRECTOR,
            ),
            201,
        )
        assert second["state"] == "ACCEPTED"
        assert second["at_risk_reason"] is None
        assert second["room_nights"] == 10

        final = fixtures.read_program(api, program_id)
        assert final["committed_room_nights"] == 20
        assert_cents(final["contingency_liability_cents"], 525000)
        assert final["version"] == refreshed_token + 1


class TestStaleBudgetLineVersion:
    def test_replaying_a_consumed_budget_line_version_is_rejected_on_the_token(
        self, api, clock_at_default
    ):
        """A procurement manager reads a freshly authorized SETUP line once and
        commits two orders against that single reading. The linen order consumes
        the token; the chairs order would have fitted comfortably inside the
        600000 cents still available, so the refusal is about the spent token and
        nothing else.

        If that value does not equal the budget line's current `version`, the create is rejected with `ERR_STALE_BUDGET_LINE_VERSION` (HTTP 412), because the client's `available_cents` figure predates another commitment, cancellation or receipt against the same line.

        Design: Corner/cross-cutting complexity layers/stale_expected_budget_line_version_on_order_create_returns_stale_budget_line_version
        """
        built = _program_with_setup_line(api)
        program_id = built["program"]["id"]
        line_id = built["budget_line"]["id"]
        token = built["budget_line"]["version"]
        assert token == 1
        assert_budget_split(built["budget_line"], 1000000, 0, 0)

        first = validate_success(
            api.create_ose_order(
                _linen_order_payload(program_id, line_id, token), PROCUREMENT_MANAGER
            ),
            201,
        )
        assert first["state"] == "COMMITTED"
        assert first["received_at"] is None
        assert first["stored_bay_code"] is None

        after_first = _read_setup_line(api, program_id)
        assert_budget_split(after_first, 1000000, 400000, 0)
        assert after_first["version"] == 2

        stale = api.create_ose_order(
            _chairs_order_payload(program_id, line_id, token), PROCUREMENT_MANAGER
        )
        validate_error(stale, api_errors.ERR_STALE_BUDGET_LINE_VERSION, 412)

        unchanged = _read_setup_line(api, program_id)
        assert_budget_split(unchanged, 1000000, 400000, 0)
        assert unchanged["version"] == 2

    def test_the_refreshed_budget_line_version_lets_the_same_order_through(
        self, api, clock_at_default
    ):
        """Re-reading the line hands the client the current token, and the same
        chairs order is then committed: the line's commitment rises to 700000
        cents, its available balance falls to 300000, and nothing has been spent
        yet.

        An order begins `COMMITTED`, with `received_at` and `stored_bay_code` null; committing it raises the line's `committed_cents` by `amount_cents` and lowers its `available_cents` by the same amount, and increments the budget line's `version` by one.

        Design: Corner/cross-cutting complexity layers/stale_expected_budget_line_version_on_order_create_returns_stale_budget_line_version
        """
        built = _program_with_setup_line(api)
        program_id = built["program"]["id"]
        line_id = built["budget_line"]["id"]

        validate_success(
            api.create_ose_order(
                _linen_order_payload(program_id, line_id, 1), PROCUREMENT_MANAGER
            ),
            201,
        )
        validate_error(
            api.create_ose_order(
                _chairs_order_payload(program_id, line_id, 1), PROCUREMENT_MANAGER
            ),
            api_errors.ERR_STALE_BUDGET_LINE_VERSION,
            412,
        )

        refreshed_token = _read_setup_line(api, program_id)["version"]
        assert refreshed_token == 2

        second = validate_success(
            api.create_ose_order(
                _chairs_order_payload(program_id, line_id, refreshed_token),
                PROCUREMENT_MANAGER,
            ),
            201,
        )
        assert second["state"] == "COMMITTED"
        assert_cents(second["amount_cents"], 300000)

        final = _read_setup_line(api, program_id)
        assert_budget_split(final, 1000000, 700000, 0)
        assert final["version"] == 3


class TestVersionAdvancesOnEveryProgramWrite:
    def test_each_program_write_advances_the_token_by_exactly_one(
        self, api, clock_at_default
    ):
        """Opening the reservation ramp, then suspending it for a rate parity
        review, then re-running the schedule arithmetic are three separate writes
        to the program row, and the guarded token moves by exactly one on each,
        with no value skipped in between.

        The `CommercialDirector` may also suspend acceptance manually with an optional `reason`, moving the commercial dimension `BOOKING_OPEN → BOOKING_SUSPENDED` and incrementing the program's `version` by one.

        Design: Corner/cross-cutting complexity layers/version_increments_on_every_write_to_the_entity_it_guards
        """
        built = fixtures.construction_complete_program(
            api, finish_iso="2026-10-01T00:00:00Z", duration_days=30
        )
        program_id = built["program"]["id"]

        before_open = fixtures.program_version(api, program_id)

        opened = validate_success(api.open_booking(program_id, COMMERCIAL_DIRECTOR), 200)
        assert opened["commercial_state"] == "BOOKING_OPEN"
        assert opened["version"] == before_open + 1

        suspended = validate_success(
            api.suspend_booking(program_id, COMMERCIAL_DIRECTOR, {"reason": "rate parity review"}),
            200,
        )
        assert suspended["commercial_state"] == "BOOKING_SUSPENDED"
        assert suspended["version"] == before_open + 2

        recomputed = validate_success(
            api.recompute_schedule(program_id, PROGRAM_DIRECTOR), 200
        )
        assert recomputed["version"] == before_open + 3

    def test_a_recomputation_is_a_write_even_though_the_dimension_does_not_move(
        self, api, clock_at_default
    ):
        """Re-running the critical path over an unchanged network produces the
        same projection and leaves the delivery dimension where it was, yet it
        still consumes a token, because a refreshed derived field is a mutation
        of the record that carries it.

        A separate recomputation capability, available to both the `ProgramDirector` and the `ConstructionManager`, re-runs the same schedule arithmetic in both variants **without** changing the delivery dimension, refreshing the floats, the slip, the posture, the contingency liability and both cost-at-completion figures, and likewise incrementing the program's `version` by one.

        Design: Corner/cross-cutting complexity layers/version_increments_on_every_write_to_the_entity_it_guards
        """
        built = fixtures.construction_complete_program(
            api, finish_iso="2026-10-01T00:00:00Z", duration_days=30
        )
        program_id = built["program"]["id"]
        before = fixtures.read_program(api, program_id)
        assert before["schedule_state"] == "CONSTRUCTION_COMPLETE"
        assert before["projected_opening_date_committed"] == "2026-10-15"
        assert before["schedule_slip_days"] == 0

        recomputed = validate_success(
            api.recompute_schedule(program_id, PROGRAM_DIRECTOR), 200
        )
        assert recomputed["schedule_state"] == "CONSTRUCTION_COMPLETE"
        assert recomputed["projected_opening_date_committed"] == "2026-10-15"
        assert recomputed["schedule_slip_days"] == 0
        assert recomputed["version"] == before["version"] + 1

        again = validate_success(api.recompute_schedule(program_id, PROGRAM_DIRECTOR), 200)
        assert again["version"] == before["version"] + 2


class TestBudgetLineReconciliation:
    def test_the_three_way_split_reconciles_after_commit_receipt_and_cancellation(
        self, api, clock_at_default
    ):
        """Two orders are committed against one 1000000-cent line, the linen
        order is then received into storage and the chairs order cancelled. A
        receipt shifts value from commitment to spend without touching the
        available balance, a cancellation gives it back, and the authorized
        figure never drifts.

        Thereafter `committed_cents` is the sum of `amount_cents` over the line's orders in state `COMMITTED`, `spent_cents` is the sum of `amount_cents` over its orders in state `STORED`, and `available_cents` is `authorized_cents` less `committed_cents` less `spent_cents`.

        Design: Corner/cross-cutting complexity layers/budget_line_derived_totals_reconcile_after_commit_receipt_and_cancellation
        """
        built = _program_with_setup_line(api)
        program_id = built["program"]["id"]
        line_id = built["budget_line"]["id"]

        order_a = validate_success(
            api.create_ose_order(
                _linen_order_payload(program_id, line_id, built["budget_line"]["version"]),
                PROCUREMENT_MANAGER,
            ),
            201,
        )
        after_a = _read_setup_line(api, program_id)
        assert_budget_split(after_a, 1000000, 400000, 0)

        order_b = validate_success(
            api.create_ose_order(
                _chairs_order_payload(program_id, line_id, after_a["version"]),
                PROCUREMENT_MANAGER,
            ),
            201,
        )
        after_b = _read_setup_line(api, program_id)
        assert_budget_split(after_b, 1000000, 700000, 0)

        fixtures.set_clock(api, "2026-10-05T00:00:00Z")
        validate_success(
            api.receive_ose_order(
                order_a["id"], factories.receive_payload("BAY-01"), PROCUREMENT_MANAGER
            ),
            200,
        )
        after_receipt = _read_setup_line(api, program_id)
        assert_budget_split(after_receipt, 1000000, 300000, 400000)
        assert_cents(after_receipt["available_cents"], after_b["available_cents"])

        validate_success(
            api.cancel_ose_order(
                order_b["id"], PROCUREMENT_MANAGER, {"reason": "specification change"}
            ),
            200,
        )
        after_cancel = _read_setup_line(api, program_id)
        assert_budget_split(after_cancel, 1000000, 0, 400000)

    def test_each_order_event_advances_the_line_token_and_lands_its_own_record(
        self, api, clock_at_default
    ):
        """The same four events — two commitments, one receipt, one cancellation
        — each advance the guarded budget line by one version, and the two orders
        end in their own terminal shapes: one stored in a numbered bay, one
        cancelled.

        On success `received_at` and `stored_bay_code` are set, the money moves from commitment to spend — the line's `committed_cents` falls by `amount_cents` while its `spent_cents` rises by the same amount, leaving `available_cents` unchanged — the budget line's `version` increments by one, and the cost-at-completion computation reruns.

        Design: Corner/cross-cutting complexity layers/budget_line_derived_totals_reconcile_after_commit_receipt_and_cancellation
        """
        built = _program_with_setup_line(api)
        program_id = built["program"]["id"]
        line_id = built["budget_line"]["id"]
        assert built["budget_line"]["version"] == 1

        order_a = validate_success(
            api.create_ose_order(
                _linen_order_payload(program_id, line_id, 1), PROCUREMENT_MANAGER
            ),
            201,
        )
        assert _read_setup_line(api, program_id)["version"] == 2

        order_b = validate_success(
            api.create_ose_order(
                _chairs_order_payload(program_id, line_id, 2), PROCUREMENT_MANAGER
            ),
            201,
        )
        assert _read_setup_line(api, program_id)["version"] == 3

        fixtures.set_clock(api, "2026-10-05T00:00:00Z")
        received = validate_success(
            api.receive_ose_order(
                order_a["id"], factories.receive_payload("BAY-01"), PROCUREMENT_MANAGER
            ),
            200,
        )
        assert received["state"] == "STORED"
        assert received["stored_bay_code"] == "BAY-01"
        assert is_iso8601_timestamp(received["received_at"])
        assert received["received_at"].startswith("2026-10-05T00:00:00")
        assert _read_setup_line(api, program_id)["version"] == 4

        cancelled = validate_success(
            api.cancel_ose_order(
                order_b["id"], PROCUREMENT_MANAGER, {"reason": "specification change"}
            ),
            200,
        )
        assert cancelled["state"] == "CANCELLED"
        assert _read_setup_line(api, program_id)["version"] == 5

        stored = validate_success(api.get_ose_order(order_a["id"], PROCUREMENT_MANAGER))
        assert stored["state"] == "STORED"
        assert stored["stored_bay_code"] == "BAY-01"
        terminal = validate_success(api.get_ose_order(order_b["id"], PROCUREMENT_MANAGER))
        assert terminal["state"] == "CANCELLED"


class TestImmediateConsistency:
    def test_one_onboarding_leaves_hire_plan_and_program_consistent_at_once(
        self, api, clock_at_default
    ):
        """A single onboarding closes out a one-person rooms plan. The write's own
        response already shows the hire onboarded, and the very next reads of the
        plan, the program and the readiness view agree with it and with each
        other, with no second write and no settling step anywhere.

        Third, caused by the second, the program's `departments_ready_count` rises by one, so the posture computation reruns and `readiness_score` rises by its staffing term.

        Design: Corner/consistency model/every_cascade_is_visible_without_a_second_write_or_a_re_read_delay
        """
        program = fixtures.make_program(api)
        plan = fixtures.make_hiring_plan(
            api,
            program["id"],
            department="ROOMS",
            headcount_target=1,
            wave_start_date="2026-09-10",
        )
        session = fixtures.make_training_session(
            api,
            program["id"],
            title="Rooms orientation",
            training_room_code="TR-1",
            starts_at="2026-09-14T09:00:00Z",
            ends_at="2026-09-14T12:00:00Z",
            capacity=5,
            department="ROOMS",
        )
        hire = fixtures.make_hire(
            api,
            plan["id"],
            session["id"],
            full_name="A. Keeper",
            hourly_rate_cents=2500,
            scheduled_hours_per_day=8,
            start_date="2026-09-15",
        )
        fixtures.respond_to_offer(api, hire["id"], "ACCEPT")
        fixtures.set_clock(api, "2026-09-20T00:00:00Z")
        fixtures.complete_session(api, session["id"])

        onboarded = validate_success(api.onboard_hire(hire["id"], TALENT_MANAGER), 200)
        assert onboarded["state"] == "ONBOARDED"
        assert is_iso8601_timestamp(onboarded["onboarded_at"])
        assert onboarded["onboarded_at"].startswith("2026-09-20T00:00:00")

        rolled_up = _read_rooms_plan(api, program["id"])
        assert rolled_up["accepted_count"] == 1
        assert rolled_up["onboarded_count"] == 1
        assert_ratio(rolled_up["staffing_ratio"], 1.0)
        assert rolled_up["readiness_flag"] == "READY"

        refreshed = fixtures.read_program(api, program["id"])
        assert refreshed["hiring_plan_count"] == 1
        assert refreshed["departments_ready_count"] == 1

        readiness = fixtures.read_readiness(api, program["id"])
        assert_ratio(readiness["staffing_ratio"], 1.0)

        # Repeating each read returns the identical derived values: no lag window
        # exists in which a denormalized field disagrees with its source.
        assert _read_rooms_plan(api, program["id"]) == rolled_up
        assert fixtures.read_program(api, program["id"]) == refreshed
        assert fixtures.read_readiness(api, program["id"]) == readiness
