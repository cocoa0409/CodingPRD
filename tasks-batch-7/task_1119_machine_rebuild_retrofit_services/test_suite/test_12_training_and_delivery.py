"""Training, handover, and delivery: the completion bubble-up, session
overflow, decision-class constants, the stages-installed delivery gate, and
the delivery stamping of delivery_date / warranty_end."""

from datetime import datetime

import test_helpers as fx
from test_helpers import (
    LOGISTICS,
    PM,
    ApiErrorId,
    make_trainer_headers,
    validate_error,
    validate_success,
)

TRAINER_1 = "tr-1"
DELIVERY_CLOCK = "2026-06-01T00:00:00Z"


def _parse_iso(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant; PRD pins the stamped instant (§3.8:
    "stamps `delivery_date` from the logical clock") but not its serialization
    format, so comparisons are by instant, not by string."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def test_training_completion_bubble_up_to_handover_ready(api):
    """PRD §3.7: "Each logged session increments `sessions_completed` by one, and the very first logged session moves the record from `PLANNED` to `IN_PROGRESS`."
    PRD §3.7: "Documentation is handed over by the same trainer through a deliver-documentation write, which sets `documentation_delivered` to `true`."
    PRD §3.7: "Completion is re-evaluated after every session log and every documentation delivery: once `sessions_completed` has reached `sessions_required` and `documentation_delivered` is `true`, the record moves to the terminal `COMPLETED`, and the project bubbles from `TRAINING_IN_PROGRESS` to `HANDOVER_READY`."

    Design: Corner/state_machines/training_completion_bubble_up_to_handover_ready
    """
    ctx = fx.setup_project_accepted(decision="MECHANICAL_REBUILD")

    record = validate_success(
        api.begin_training(ctx.project["id"], {"trainer_id": TRAINER_1}, PM), 200
    )
    assert record["status"] == "PLANNED"
    assert record["sessions_required"] == 2

    record = validate_success(
        api.log_session(record["id"], make_trainer_headers(TRAINER_1)), 200
    )
    assert record["status"] == "IN_PROGRESS"
    assert record["sessions_completed"] == 1

    record = validate_success(
        api.log_session(record["id"], make_trainer_headers(TRAINER_1)), 200
    )
    assert record["sessions_completed"] == 2
    assert record["status"] == "IN_PROGRESS"  # documentation not yet delivered

    record = validate_success(
        api.deliver_documentation(record["id"], make_trainer_headers(TRAINER_1)), 200
    )
    assert record["documentation_delivered"] is True
    assert record["status"] == "COMPLETED"

    project = fx.get_project(ctx.project["id"])
    assert project["work_status"] == "HANDOVER_READY"


def test_training_session_overflow_rejected(api):
    """PRD §3.7: "Logging is bounded: when `sessions_completed` has already reached `sessions_required`, a further log attempt is rejected with `ERR_TRAINING_SESSION_OVERFLOW`."

    Design: Corner/validations/training_session_overflow_rejected
    """
    ctx = fx.setup_project_accepted(decision="MECHANICAL_REBUILD")
    record = validate_success(
        api.begin_training(ctx.project["id"], {"trainer_id": TRAINER_1}, PM), 200
    )
    validate_success(api.log_session(record["id"], make_trainer_headers(TRAINER_1)), 200)
    record = validate_success(api.log_session(record["id"], make_trainer_headers(TRAINER_1)), 200)
    assert record["sessions_completed"] == 2
    assert record["status"] == "IN_PROGRESS"  # documentation pending, still loggable state

    res = api.log_session(record["id"], make_trainer_headers(TRAINER_1))
    validate_error(res, ApiErrorId.ERR_TRAINING_SESSION_OVERFLOW.value)


def test_warranty_months_and_sessions_by_decision_class(api):
    """PRD §3.7: "Acceptance of the rebuilt machine triggers a bubble-up: the system auto-creates a TrainingRecord for the project in `PLANNED`, with `sessions_completed` at 0, `documentation_delivered` at `false`, and `sessions_required` fixed by the decision class — one session for `RETROFIT_ONLY`, two for `MECHANICAL_REBUILD`, three for `FULL_REBUILD`."
    PRD §3.8: "Delivery stamps `delivery_date` from the logical clock, computes `warranty_end` as `delivery_date` plus `warranty_months` calendar months landing on the same day-of-month — where `warranty_months` is 6 for `RETROFIT_ONLY`, 12 for `MECHANICAL_REBUILD`, and 24 for `FULL_REBUILD` per the decision — moves the machine from `IN_PROJECT` to the terminal `RETURNED`, and moves `work_status` to `WARRANTY_ACTIVE`."

    Design: Corner/calculations/warranty_months_by_decision_class
    """
    # wear 20.00 (4/2/3) -> recommended RETROFIT_ONLY; decision matches it.
    ctx = fx.setup_project_delivered(
        decision="RETROFIT_ONLY", pd=4, sr=2, bl=3, delivery_clock=DELIVERY_CLOCK,
    )

    assert ctx.training_record["sessions_required"] == 1
    project = ctx.project
    assert project["work_status"] == "WARRANTY_ACTIVE"
    assert project["warranty_months"] == 6
    assert _parse_iso(project["delivery_date"]) == _parse_iso(DELIVERY_CLOCK)
    # Six calendar months from 2026-06-01 land on 2026-12-01, same day-of-month
    # and same clock time as delivery.
    assert project["warranty_end"] == "2026-12-01" + project["delivery_date"][10:]


class TestDeliverRequiresAllStagesInstalled:
    def _handover_with_stage_at_received(self, api):
        ctx = fx.setup_project_handover_ready(decision="MECHANICAL_REBUILD")
        window = fx.create_window(ctx.customer["id"])
        stage = fx.create_stage(ctx.project["id"], window["id"])
        fx.get_success_data(api.ship_stage(stage["id"], LOGISTICS))
        fx.get_success_data(api.receive_stage(stage["id"], LOGISTICS))
        fx.set_clock(DELIVERY_CLOCK)
        ctx.window = window
        ctx.stage = stage
        return ctx

    def test_deliver_blocked_while_stage_not_installed(self, api):
        """PRD §3.8: "Every ShipmentStage of the project must by then be `INSTALLED` or `CANCELLED`; any stage in any other state blocks delivery with `ERR_STAGES_NOT_INSTALLED`."

        Design: Difficulty/cross_entity_state_dependency/deliver_requires_all_stages_installed
        """
        ctx = self._handover_with_stage_at_received(api)
        assert fx.get_stage(ctx.stage["id"])["status"] == "RECEIVED"

        res = api.deliver_project(ctx.project["id"], PM)
        validate_error(res, ApiErrorId.ERR_STAGES_NOT_INSTALLED.value)

        project = fx.get_project(ctx.project["id"])
        assert project["work_status"] == "HANDOVER_READY"

    def test_deliver_succeeds_after_install_and_stamps_warranty(self, api):
        """PRD §3.8: "Delivery stamps `delivery_date` from the logical clock, computes `warranty_end` as `delivery_date` plus `warranty_months` calendar months landing on the same day-of-month — where `warranty_months` is 6 for `RETROFIT_ONLY`, 12 for `MECHANICAL_REBUILD`, and 24 for `FULL_REBUILD` per the decision — moves the machine from `IN_PROJECT` to the terminal `RETURNED`, and moves `work_status` to `WARRANTY_ACTIVE`."
        PRD §3.8: "Both `delivery_date` and `warranty_end` are null until this moment."

        Design: Difficulty/cross_entity_state_dependency/deliver_requires_all_stages_installed
        """
        ctx = self._handover_with_stage_at_received(api)
        fx.get_success_data(api.install_stage(ctx.stage["id"], LOGISTICS))

        delivered = validate_success(api.deliver_project(ctx.project["id"], PM), 200)
        assert delivered["work_status"] == "WARRANTY_ACTIVE"
        assert _parse_iso(delivered["delivery_date"]) == _parse_iso(DELIVERY_CLOCK)
        assert delivered["warranty_months"] == 12
        # Twelve calendar months from 2026-06-01 land on 2027-06-01.
        assert delivered["warranty_end"] == "2027-06-01" + delivered["delivery_date"][10:]

        machine = fx.get_machine(ctx.machine["id"])
        assert machine["status"] == "RETURNED"
