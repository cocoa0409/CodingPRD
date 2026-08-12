"""Schedule templates, weekly capacity, panel opening and census: half-open
overlap semantics, derived-minute reconciliation, go-live posture gating, the
retire cascade, and census boundaries."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    create_physician, create_case, get_case,
    create_schedule_template_payload, create_active_template, setup_ready_schedule,
    setup_executed_offer, setup_credentials_complete, complete_training,
    setup_go_live, get_module_by_code, schedule_module, complete_module,
    set_clock,
)

PM = TEST_USERS["practice_manager_headers"]
DIRECTOR = TEST_USERS["onboarding_director_headers"]


def test_weekly_minutes_exclude_admin_blocks(api):
    """PRD §3.5: "The case's `weekly_active_minutes` is the sum, over its `ACTIVE` templates whose `block_type` is `CLINIC`, `PROCEDURE`, or `OR`, of each block's length — its `end_minute` minus its `start_minute`; `ADMIN` blocks never count."
    PRD §3.5: "`practice_status` is `READY` when `weekly_active_minutes` is at least the requirement, `BUILDING` when at least one `ACTIVE` template exists but the total falls short"

    Design: Corner/calculations/weekly_minutes_exclude_admin_blocks
    """
    physician = create_physician(full_name="Dr. Ree")
    case = create_case(physician["id"])
    create_active_template(case["id"], weekday=1, start_minute=480, end_minute=960)
    create_active_template(case["id"], weekday=2, start_minute=480, end_minute=1080, block_type="ADMIN")

    case = get_case(case["id"])
    assert case["weekly_active_minutes"] == 480, "the 600-minute ADMIN block must not count"
    assert case["practice_status"] == "BUILDING", "480 < 1200 keeps practice BUILDING"


def test_template_half_open_adjacency_allowed(api):
    """PRD §3.5: "Two half-open blocks overlap exactly when one's start falls before the other's end and the other's start falls before the one's end; blocks that merely touch — one's `end_minute` equal to the other's `start_minute` — are allowed."

    Design: Difficulty/resource_temporal_overlap/template_half_open_adjacency_allowed
    """
    physician = create_physician(full_name="Dr. Pam", specialty="ORTHOPEDICS")
    case = create_case(physician["id"])
    create_active_template(case["id"], weekday=1, start_minute=480, end_minute=960)

    adjacent = validate_success(
        api.create_schedule_template(
            create_schedule_template_payload(
                case["id"], weekday=1, start_minute=960, end_minute=1020
            ),
            PM,
        ),
        201,
    )
    data = validate_success(api.activate_schedule_template(adjacent["id"], PM), 200)
    assert data["status"] == "ACTIVE", "touching at 960 is not an overlap under half-open semantics"


def test_template_half_open_one_minute_overlap_rejected(api):
    """PRD §3.5: "A conflicting activation is rejected with `ERR_TEMPLATE_OVERLAP` (HTTP 422)."
    PRD §3.5: "Two half-open blocks overlap exactly when one's start falls before the other's end and the other's start falls before the one's end; blocks that merely touch — one's `end_minute` equal to the other's `start_minute` — are allowed."

    Design: Difficulty/resource_temporal_overlap/template_half_open_adjacency_allowed
    """
    physician = create_physician(full_name="Dr. Pam", specialty="ORTHOPEDICS")
    case = create_case(physician["id"])
    create_active_template(case["id"], weekday=1, start_minute=480, end_minute=960)
    create_active_template(case["id"], weekday=1, start_minute=960, end_minute=1020)

    overlapping = validate_success(
        api.create_schedule_template(
            create_schedule_template_payload(
                case["id"], weekday=1, start_minute=959, end_minute=1020
            ),
            PM,
        ),
        201,
    )
    resp = api.activate_schedule_template(overlapping["id"], PM)
    validate_error(resp, ApiErrorId.ERR_TEMPLATE_OVERLAP)

    case = get_case(case["id"])
    assert case["weekly_active_minutes"] == 540, (
        "only the two accepted blocks (480 + 60) count; the rejected template contributes nothing"
    )


def test_derived_minutes_reconciled_on_activate_and_retire(api):
    """PRD §3.5: "Every activation and retirement recomputes `weekly_active_minutes`, `practice_status`, and `posture` together."
    PRD §3.5: "`practice_status` is `READY` when `weekly_active_minutes` is at least the requirement, `BUILDING` when at least one `ACTIVE` template exists but the total falls short, and `PLANNING` when nothing is `ACTIVE` at all."

    Design: Corner/cross_cutting_layers/derived_minutes_reconciled_on_activate_and_retire
    """
    physician = create_physician(full_name="Dr. Ned", specialty="ORTHOPEDICS")
    case = create_case(physician["id"])
    template = validate_success(
        api.create_schedule_template(
            create_schedule_template_payload(
                case["id"], weekday=1, start_minute=480, end_minute=960
            ),
            PM,
        ),
        201,
    )

    case = get_case(case["id"])
    assert case["weekly_active_minutes"] == 0, "a DRAFT template contributes nothing"

    validate_success(api.activate_schedule_template(template["id"], PM), 200)
    case = get_case(case["id"])
    assert case["weekly_active_minutes"] == 480
    assert case["practice_status"] == "BUILDING", "480 < 900 for ORTHOPEDICS"

    validate_success(api.retire_schedule_template(template["id"], PM), 200)
    case = get_case(case["id"])
    assert case["weekly_active_minutes"] == 0
    assert case["practice_status"] == "PLANNING", "no ACTIVE templates remain"


def test_template_retire_cascade_recomputes_practice_and_posture(api):
    """PRD §3.5: "When retirement pulls `weekly_active_minutes` below the specialty requirement, `practice_status` drops from `READY` to `BUILDING`, and if the case's panel is `OPEN` at that moment the practice drop freezes it: the panel moves `OPEN` → `FROZEN` and the case's posture leaves `LIVE`, per the panel rules of §3.6."

    Design: Difficulty/transitive_cascade/template_retire_cascade_freezes_panel
    """
    ctx = setup_go_live(full_name="Dr. Ida")
    case = get_case(ctx["case"]["id"])
    assert case["posture"] == "LIVE"
    assert case["practice_status"] == "READY"
    assert case["weekly_active_minutes"] == 1200, "exactly 1200 weekly minutes meets the >= boundary"

    # Retire the 240-minute weekday-3 block (the third default template).
    validate_success(api.retire_schedule_template(ctx["templates"][2]["id"], PM), 200)

    case = get_case(ctx["case"]["id"])
    assert case["weekly_active_minutes"] == 960
    assert case["practice_status"] == "BUILDING"
    assert case["posture"] == "RAMP_PREP", "the practice dimension dropped out of the LIVE gate"


def test_template_retire_cascade_freezes_open_panel(api):
    """PRD §3.5: "if the case's panel is `OPEN` at that moment the practice drop freezes it: the panel moves `OPEN` → `FROZEN` and the case's posture leaves `LIVE`, per the panel rules of §3.6."

    Design: Difficulty/transitive_cascade/template_retire_cascade_freezes_panel
    """
    ctx = setup_go_live(full_name="Dr. Ida")
    panel_id = ctx["panel"]["id"]
    assert get_success_data(api.get_panel(panel_id, DIRECTOR))["status"] == "OPEN"

    validate_success(api.retire_schedule_template(ctx["templates"][2]["id"], PM), 200)

    panel = get_success_data(api.get_panel(panel_id, DIRECTOR))
    assert panel["status"] == "FROZEN", "the retire cascade must freeze the OPEN panel"
    case = get_case(ctx["case"]["id"])
    assert case["posture"] == "RAMP_PREP"


def test_census_exactly_at_capacity_allowed(api):
    """PRD §3.6: "Adjustments are bounded on both sides — the result may reach the panel's `capacity` exactly, but one patient beyond it is rejected with `ERR_PANEL_CAPACITY_EXCEEDED` (HTTP 422), and a result below zero is rejected with `ERR_NEGATIVE_CENSUS` (HTTP 422)."

    Design: Difficulty/boundary_precision_check/census_exactly_at_capacity_allowed
    """
    ctx = setup_go_live(full_name="Dr. Mae", panel_capacity=1000)
    resp = api.adjust_panel_census(ctx["panel"]["id"], {"delta": 1000}, PM)
    data = validate_success(resp, 200)
    assert data["current_size"] == 1000, "reaching capacity exactly must succeed (<= is inclusive)"
    assert data["capacity"] == 1000


def test_census_one_beyond_capacity_rejected(api):
    """PRD §3.6: "the result may reach the panel's `capacity` exactly, but one patient beyond it is rejected with `ERR_PANEL_CAPACITY_EXCEEDED` (HTTP 422)"

    Design: Difficulty/boundary_precision_check/census_exactly_at_capacity_allowed
    """
    ctx = setup_go_live(full_name="Dr. Mae", panel_capacity=1000)
    validate_success(api.adjust_panel_census(ctx["panel"]["id"], {"delta": 1000}, PM), 200)

    resp = api.adjust_panel_census(ctx["panel"]["id"], {"delta": 1}, PM)
    validate_error(resp, ApiErrorId.ERR_PANEL_CAPACITY_EXCEEDED)
    panel = get_success_data(api.get_panel(ctx["panel"]["id"], DIRECTOR))
    assert panel["current_size"] == 1000, "a rejected adjustment must not move the census"


def test_negative_census_below_zero_rejected(api):
    """PRD §3.6: "a result below zero is rejected with `ERR_NEGATIVE_CENSUS` (HTTP 422)"

    Design: Corner/validations/negative_census_below_zero_rejected
    """
    ctx = setup_go_live(full_name="Dr. Fox")
    resp = api.adjust_panel_census(ctx["panel"]["id"], {"delta": -1}, PM)
    validate_error(resp, ApiErrorId.ERR_NEGATIVE_CENSUS)
    panel = get_success_data(api.get_panel(ctx["panel"]["id"], DIRECTOR))
    assert panel["current_size"] == 0


def test_panel_open_rejected_until_posture_go_live_ready(api):
    """PRD §3.6: "Opening the panel is the go-live act, performed by a `PracticeManager` and guarded by three checks: the panel must be `NOT_OPEN` (else `ERR_PANEL_NOT_OPEN`), the case's `posture` must be `GO_LIVE_READY` (else `ERR_POSTURE_NOT_READY`), and the logical clock's date must have reached the case's `actual_start_date` (else `ERR_START_DATE_NOT_REACHED`, HTTP 422)."

    Design: Difficulty/cross_entity_state_dependency/panel_open_requires_go_live_posture
    """
    ctx = setup_executed_offer(full_name="Dr. Noa")
    case_id = ctx["case"]["id"]
    setup_credentials_complete(case_id)
    # Only one module completed: training_status stays IN_PROGRESS.
    module = get_module_by_code(ctx["plan"]["id"], "EHR_FUNDAMENTALS")
    schedule_module(module["id"])
    complete_module(module["id"], ctx["physician"]["id"], score=90)
    setup_ready_schedule(case_id)
    set_clock("2027-06-01T09:00:00Z")

    case = get_case(case_id)
    assert case["training_status"] == "IN_PROGRESS"
    assert case["posture"] == "RAMP_PREP", (
        "credentials COMPLETE and practice READY but training incomplete lands on RAMP_PREP"
    )

    resp = api.open_panel(ctx["panel"]["id"], PM)
    validate_error(resp, ApiErrorId.ERR_POSTURE_NOT_READY)
    assert resp.status_code == 409


def test_panel_open_succeeds_at_go_live_ready_with_cascades(api):
    """PRD §3.6: "A successful open stamps `opened_at` with the logical clock, sets the case's `posture` to `LIVE`, moves the physician `ONBOARDING` → `ACTIVE`, moves the case `IN_PROGRESS` → `HIRED`, and increments the versions of panel, case, and physician alike."

    Design: Difficulty/cross_entity_state_dependency/panel_open_requires_go_live_posture
    """
    ctx = setup_executed_offer(full_name="Dr. Noa")
    case_id = ctx["case"]["id"]
    setup_credentials_complete(case_id)
    module = get_module_by_code(ctx["plan"]["id"], "EHR_FUNDAMENTALS")
    schedule_module(module["id"])
    complete_module(module["id"], ctx["physician"]["id"], score=90)
    setup_ready_schedule(case_id)
    set_clock("2027-06-01T09:00:00Z")

    resp = api.open_panel(ctx["panel"]["id"], PM)
    validate_error(resp, ApiErrorId.ERR_POSTURE_NOT_READY)

    # Complete the missing dimension, then the identical open succeeds.
    complete_training(case_id, ctx["physician"]["id"])
    data = validate_success(api.open_panel(ctx["panel"]["id"], PM), 200)
    assert data["status"] == "OPEN"
    assert data["opened_at"] is not None

    physician = get_success_data(api.get_physician(ctx["physician"]["id"], DIRECTOR))
    assert physician["status"] == "ACTIVE"
    case = get_case(case_id)
    assert case["case_status"] == "HIRED"
    assert case["posture"] == "LIVE"


def test_case_parallel_dimensions_evolve_independently(api):
    """PRD §2.6: "An OnboardingCase is not governed by a single status. Its `case_status` moves from `IN_PROGRESS` at creation to `HIRED` when the panel opens and finally to `SEPARATED`, but alongside it three parallel dimensions evolve independently, and a fourth derived field gates the go-live decision."
    PRD §2.6: "Once an offer executes, the case is `CREDENTIALING` while `credential_status` is anything other than `COMPLETE`"

    Design: Difficulty/non_linear_state_machine/onboarding_case_parallel_dimensions_independent
    """
    ctx = setup_executed_offer(full_name="Dr. Gia")
    case_id = ctx["case"]["id"]
    complete_training(case_id, ctx["physician"]["id"])
    setup_ready_schedule(case_id)

    case = get_case(case_id)
    assert case["training_status"] == "COMPLETE"
    assert case["credential_status"] == "NOT_STARTED", (
        "the credential dimension never moved while training completed"
    )
    assert case["practice_status"] == "READY"
    assert case["weekly_active_minutes"] == 1200
    assert case["posture"] == "CREDENTIALING", (
        "the incomplete credential dimension dominates the gate despite training COMPLETE and practice READY"
    )


def test_case_posture_reaches_go_live_ready_when_all_dimensions_done(api):
    """PRD §2.6: "it reaches `GO_LIVE_READY` only when `credential_status` is `COMPLETE`, `training_status` is `COMPLETE`, and `practice_status` is `READY` at the same time."

    Design: Difficulty/non_linear_state_machine/onboarding_case_parallel_dimensions_independent
    """
    ctx = setup_executed_offer(full_name="Dr. Gia")
    case_id = ctx["case"]["id"]
    complete_training(case_id, ctx["physician"]["id"])
    setup_ready_schedule(case_id)
    assert get_case(case_id)["posture"] == "CREDENTIALING"

    setup_credentials_complete(case_id)
    case = get_case(case_id)
    assert case["credential_status"] == "COMPLETE"
    assert case["training_status"] == "COMPLETE"
    assert case["practice_status"] == "READY"
    assert case["posture"] == "GO_LIVE_READY"
