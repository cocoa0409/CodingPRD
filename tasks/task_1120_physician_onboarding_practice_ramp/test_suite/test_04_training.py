"""EHR training: module listing order, hire-type provisioning, the 80-point
pass boundary, the retake cycle, and the NOTE_TEMPLATES template gate."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    setup_executed_offer, get_training_plan_for_case, get_module_by_code,
    schedule_module, complete_module,
    make_physician_headers,
)

PM = TEST_USERS["practice_manager_headers"]


def test_module_listing_ordered_by_module_code(api):
    """PRD §3.4: "Modules are listed ordered by `module_code` ascending rather than by creation time, so indexed access is deterministic, with optional `training_plan_id`, `status`, and `module_code` filters."
    PRD §3.4: "Every physician must complete three required modules, `EHR_FUNDAMENTALS`, `ORDER_ENTRY`, and `NOTE_TEMPLATES`; a `NEW_GRAD` hire has a fourth, `BILLING`, so `required_module_count` is 4 for `NEW_GRAD` and 3 otherwise."

    Design: Corner/entities/module_listing_ordered_by_module_code
    """
    ctx = setup_executed_offer(full_name="Dr. Ed", hire_type="EXPERIENCED")
    data = get_success_data(
        api.list_training_modules(PM, params={"training_plan_id": ctx["plan"]["id"]})
    )
    codes = [m["module_code"] for m in data]
    assert codes == ["EHR_FUNDAMENTALS", "NOTE_TEMPLATES", "ORDER_ENTRY"], (
        f"module list must be ordered by module_code ascending, got {codes}"
    )
    for module in data:
        assert module["status"] == "NOT_STARTED"
        assert module["required"] is True


def test_new_grad_requires_four_modules_and_five_templates(api):
    """PRD §3.4: "a `NEW_GRAD` hire has a fourth, `BILLING`, so `required_module_count` is 4 for `NEW_GRAD` and 3 otherwise."
    PRD §3.4: "The plan also pins `templates_required`, the number of EHR note templates the physician must build inside `NOTE_TEMPLATES`: 5 for a `NEW_GRAD`, 3 otherwise."

    Design: Corner/entities/new_grad_requires_four_modules_and_five_templates
    """
    ctx = setup_executed_offer(full_name="Dr. Fi", specialty="PEDIATRICS", hire_type="NEW_GRAD")
    plan = get_training_plan_for_case(ctx["case"]["id"])
    assert plan["required_module_count"] == 4
    assert plan["templates_required"] == 5
    data = get_success_data(
        api.list_training_modules(PM, params={"training_plan_id": plan["id"]})
    )
    assert len(data) == 4
    assert all(m["required"] is True for m in data)
    assert "BILLING" in [m["module_code"] for m in data]


def test_module_pass_threshold_exactly_80_completes(api):
    """PRD §3.4: "The pass mark is 80: a score of at least 80 — exactly 80 passes — moves the module to `COMPLETED` with the `score` and any `templates_built_count` recorded, while a score of 79 or below moves it to `FAILED` with the score recorded"

    Design: Difficulty/boundary_precision_check/module_pass_threshold_exactly_80
    """
    ctx = setup_executed_offer(full_name="Dr. Lou")
    plan_id = ctx["plan"]["id"]
    module = get_module_by_code(plan_id, "EHR_FUNDAMENTALS")
    schedule_module(module["id"])
    data = complete_module(module["id"], ctx["physician"]["id"], score=80)
    assert data["status"] == "COMPLETED", "score exactly at the pass mark must COMPLETE the module"
    assert data["score"] == 80


def test_module_pass_threshold_79_fails_without_error(api):
    """PRD §3.4: "a score of 79 or below moves it to `FAILED` with the score recorded; a failing score is a state outcome, not an error, and the module can be re-scheduled."
    PRD §3.4: "The first time any module of a plan is scheduled, the plan bubbles up from `PLANNED` to `IN_PROGRESS`."

    Design: Difficulty/boundary_precision_check/module_pass_threshold_exactly_80
    """
    ctx = setup_executed_offer(full_name="Dr. Lou")
    plan_id = ctx["plan"]["id"]
    module = get_module_by_code(plan_id, "ORDER_ENTRY")
    schedule_module(module["id"])
    resp = api.complete_training_module(
        module["id"], {"score": 79}, make_physician_headers(ctx["physician"]["id"])
    )
    data = validate_success(resp, 200)
    assert data["status"] == "FAILED", "one point below the pass mark must FAIL, not error"
    assert data["score"] == 79
    plan = get_training_plan_for_case(ctx["case"]["id"])
    assert plan["status"] == "IN_PROGRESS", (
        "other required modules are still open, so no premature AWAITING_SIGNOFF"
    )


def test_module_failed_retake_cycle(api):
    """PRD §3.4: "a module in `NOT_STARTED` or `FAILED` moves to `SCHEDULED` with its `scheduled_on` date set, and scheduling from any other state is rejected with `ERR_INVALID_STATE`. The `FAILED` → `SCHEDULED` hop is the retake cycle."

    Design: Corner/state_machines/module_failed_retake_cycle
    """
    ctx = setup_executed_offer(full_name="Dr. Kat")
    module = get_module_by_code(ctx["plan"]["id"], "EHR_FUNDAMENTALS")
    schedule_module(module["id"])
    data = complete_module(module["id"], ctx["physician"]["id"], score=70)
    assert data["status"] == "FAILED"

    data = schedule_module(module["id"], scheduled_on="2026-05-20")
    assert data["status"] == "SCHEDULED", "FAILED is not terminal; re-scheduling is the retake cycle"
    data = complete_module(module["id"], ctx["physician"]["id"], score=85)
    assert data["status"] == "COMPLETED"


def test_templates_insufficient_for_note_templates_module(api):
    """PRD §3.4: "The `NOTE_TEMPLATES` module adds a second gate: completing it requires `templates_built_count` to be at least the plan's `templates_required`, otherwise the completion is rejected with `ERR_TEMPLATES_INSUFFICIENT` (HTTP 422) and no transition occurs."

    Design: Corner/validations/templates_insufficient_for_note_templates_module
    """
    ctx = setup_executed_offer(full_name="Dr. Gab")
    module = get_module_by_code(ctx["plan"]["id"], "NOTE_TEMPLATES")
    schedule_module(module["id"])
    headers = make_physician_headers(ctx["physician"]["id"])

    resp = api.complete_training_module(
        module["id"], {"score": 90, "templates_built_count": 2}, headers
    )
    validate_error(resp, ApiErrorId.ERR_TEMPLATES_INSUFFICIENT)
    assert get_module_by_code(ctx["plan"]["id"], "NOTE_TEMPLATES")["status"] == "SCHEDULED", (
        "a rejected completion must leave the module SCHEDULED"
    )

    data = validate_success(
        api.complete_training_module(
            module["id"], {"score": 90, "templates_built_count": 3}, headers
        ),
        200,
    )
    assert data["status"] == "COMPLETED"
