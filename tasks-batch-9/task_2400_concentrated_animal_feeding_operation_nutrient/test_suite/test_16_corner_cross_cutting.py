"""Cross-cutting corner cases: the optimistic-concurrency token on plan create,
the two distinct freeboard thresholds at their exact boundaries, and the
immediate visibility of a write's whole fan-out.
"""

from datetime import datetime, timezone

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_client import api_client as client
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_immutable_register,
    assert_budget_ledger,
    assert_operation_sizing,
    assert_posture,
    assert_quantity,
    assert_storage_balance,
)
from test_helpers.factories import plan_payload
from test_helpers.fixtures import (
    file_storage_inspection,
    record_application,
    setup_ready_operation,
    setup_scenario,
)
from test_helpers.test_users import ADMIN_HEADERS, PLANNER_HEADERS



def _instant(value):
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    moment = datetime.fromisoformat(text)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment


def _same_instant(actual, expected, label="instant"):
    assert actual is not None, f"{label} is missing"
    assert _instant(actual) == _instant(expected), (
        f"{label}: expected {expected}, got {actual}"
    )


def test_stale_operation_version_is_rejected_on_plan_create():
    """A herd-size patch between the client's read and its plan create advances
    the operation's version, so the token the client observed no longer matches
    and the create is refused with nothing written.

    PRD: "Any such revision re-derives `animal_units`, `size_class`, `permit_required`, `design_annual_manure_gallons` and `daily_production_gallons`; recomputes the operation's `design_storage_days`; recomputes `days_of_storage_available` on every storage structure of the operation, since the daily production figure is the denominator of both; and increments the operation's `version` by 1."
    PRD: "If that value does not equal the operation's current `version` — because any other writer has advanced it since the client read it — the create is rejected with `ERR_STALE_OPERATION_VERSION` and HTTP 412, and nothing is written."
    Design: Corner/cross_cutting_complexity_layers/stale_operation_version_is_rejected_on_plan_create
    """
    ctx = setup_scenario(stage="LAND_BASE")
    operation_id = ctx["operation"]["id"]
    permit_id = ctx["permit"]["id"]
    operator_headers = ctx["operator_headers"]

    observed = validate_success(client.get_operation(operation_id, operator_headers))
    stale_token = observed["version"]

    patched = validate_success(
        client.update_operation(operation_id, {"head_count": 310}, operator_headers)
    )
    assert patched["version"] == stale_token + 1, (
        "a herd revision increments the operation version by exactly 1"
    )
    assert_operation_sizing(patched, 434.00, "MEDIUM", True, 3477798.00, 9528.21)

    validate_error(
        client.create_nutrient_plan(
            plan_payload(operation_id, permit_id, stale_token), PLANNER_HEADERS
        ),
        ApiErrorId.ERR_STALE_OPERATION_VERSION.value,
    )

    plans, meta = validate_paginated(
        client.list_nutrient_plans(PLANNER_HEADERS, params={"operation_id": operation_id})
    )
    assert plans == [], "the refused create must not have written a plan"
    assert meta["total_count"] == 0
    still = validate_success(client.get_operation(operation_id, operator_headers))
    assert still["version"] == stale_token + 1, (
        "the refused create must not touch the operation version either"
    )


def test_plan_create_bumps_the_operation_version_so_the_token_cannot_replay():
    """A matching token is accepted, and the accepted create advances the
    operation's version in the same write — so replaying the very token that
    just worked is refused.

    PRD: "When the value matches, the plan is created and the operation's own `version` is incremented by one as part of the same write, so the same token cannot be replayed for a second plan."
    PRD: "New plans start in `DRAFT` with `revision_count` at 0."
    Design: Corner/cross_cutting_complexity_layers/stale_operation_version_is_rejected_on_plan_create
    """
    ctx = setup_scenario(stage="LAND_BASE")
    operation_id = ctx["operation"]["id"]
    permit_id = ctx["permit"]["id"]
    operator_headers = ctx["operator_headers"]

    token = validate_success(
        client.get_operation(operation_id, operator_headers)
    )["version"]

    plan = validate_success(
        client.create_nutrient_plan(
            plan_payload(operation_id, permit_id, token), PLANNER_HEADERS
        ),
        201,
    )
    assert plan["plan_status"] == "DRAFT"
    assert plan["revision_count"] == 0
    assert plan["supersedes_plan_id"] is None

    after = validate_success(client.get_operation(operation_id, operator_headers))
    assert after["version"] == token + 1, (
        "the accepted plan create bumps the operation version by one"
    )

    validate_error(
        client.create_nutrient_plan(
            plan_payload(operation_id, permit_id, token, plan_year=2027),
            PLANNER_HEADERS,
        ),
        ApiErrorId.ERR_STALE_OPERATION_VERSION.value,
    )

    plans, meta = validate_paginated(
        client.list_nutrient_plans(PLANNER_HEADERS, params={"operation_id": operation_id})
    )
    assert meta["total_count"] == 1, "the replayed token must not create a second plan"
    assert [row["id"] for row in plans] == [plan["id"]]


def test_freeboard_exactly_at_the_requirement_is_not_a_deficit():
    """A reading exactly equal to the required freeboard leaves the deficit at
    zero and the structure in service, while still rewriting the reconciliation
    term so the volume balance matches what the inspector measured.

    PRD: "`freeboard_deficit_in` is the structure's `required_freeboard_in` less `measured_freeboard_in`, with any negative result replaced by 0, rounded half up to 2 decimal places."
    PRD: "The reconciliation term is then rewritten: `precipitation_adjustment_gallons` becomes `measured_volume_gallons` less `cumulative_intake_gallons` plus `cumulative_outflow_gallons`, rounded half up to 2 decimal places, which is precisely the value that makes the volume-balance invariant exact against what the inspector measured."
    Design: Corner/cross_cutting_complexity_layers/freeboard_and_overflow_thresholds_fire_at_their_exact_boundaries
    """
    ctx = setup_scenario(stage="COVERED", intake_gallons=1000000)
    operation_id = ctx["operation"]["id"]
    storage_id = ctx["storage"]["id"]
    operator_headers = ctx["operator_headers"]

    register = file_storage_inspection(
        operation_id,
        storage_id,
        operator_headers,
        inspected_on="2026-07-20T00:00:00Z",
        measured_freeboard_in=24,
        visual_condition="NORMAL",
    )
    assert_immutable_register(register, "storage inspection")
    assert_quantity(register["measured_volume_gallons"], 4488300.00, "measured_volume_gallons")
    assert_quantity(register["freeboard_deficit_in"], 0.00, "freeboard_deficit_in")
    assert register["alert_raised"] is False

    structure = validate_success(client.get_manure_storage(storage_id, operator_headers))
    assert structure["storage_status"] == "IN_SERVICE"
    assert_storage_balance(
        structure,
        intake=1000000.00,
        precipitation=3488300.00,
        outflow=0.00,
        current=4488300.00,
        committed=0.00,
        available=0.00,
        days=0,
    )
    _same_instant(structure["last_inspected_on"], "2026-07-20T00:00:00Z", "last_inspected_on")
    assert_posture(
        validate_success(client.get_operation(operation_id, operator_headers)), "OPEN"
    )


def test_one_inch_short_of_the_requirement_raises_a_freeboard_alert():
    """A single inch of deficit, with the reading still well above six inches,
    moves the structure to a freeboard alert and restricts the operation — and
    the available capacity it reports goes negative rather than being clipped.

    PRD: "Otherwise, when there is a freeboard deficit at all, meaning `freeboard_deficit_in` is greater than 0 while `measured_freeboard_in` remains above 6 inches, a structure in `IN_SERVICE` moves to `FREEBOARD_ALERT` and the operation's posture is recomputed to `RESTRICTED`."
    PRD: "A structure's own `days_of_storage_available` is the greater of zero and its `available_capacity_gallons`, divided by that effective daily production and floored to a whole day, so the figure shrinks as the structure fills and grows again when a transfer is suspended or cancelled."
    Design: Corner/cross_cutting_complexity_layers/freeboard_and_overflow_thresholds_fire_at_their_exact_boundaries
    """
    ctx = setup_scenario(stage="COVERED", intake_gallons=1000000)
    operation_id = ctx["operation"]["id"]
    storage_id = ctx["storage"]["id"]
    operator_headers = ctx["operator_headers"]

    register = file_storage_inspection(
        operation_id,
        storage_id,
        operator_headers,
        inspected_on="2026-07-22T00:00:00Z",
        measured_freeboard_in=23,
        visual_condition="NORMAL",
    )
    assert_quantity(register["measured_volume_gallons"], 4525702.50, "measured_volume_gallons")
    assert_quantity(register["freeboard_deficit_in"], 1.00, "freeboard_deficit_in")
    assert register["alert_raised"] is True

    structure = validate_success(client.get_manure_storage(storage_id, operator_headers))
    assert structure["storage_status"] == "FREEBOARD_ALERT"
    assert_storage_balance(
        structure,
        intake=1000000.00,
        precipitation=3525702.50,
        outflow=0.00,
        current=4525702.50,
        available=-37402.50,
        days=0,
    )
    assert_posture(
        validate_success(client.get_operation(operation_id, operator_headers)),
        "RESTRICTED",
        findings=0,
    )


def test_adequate_freeboard_with_an_abnormal_condition_still_blocks_return_to_service():
    """Above the deficit boundary the condition field alone raises the alert, and
    return to service is gated on the latest record showing both no deficit and
    a normal condition.

    PRD: "`alert_raised` is true when `freeboard_deficit_in` is greater than 0 or `visual_condition` is anything other than `NORMAL`."
    PRD: "A structure whose latest inspection still shows a deficit, or shows `SEEPAGE`, `EROSION` or `CRACKING` even with adequate freeboard, cannot come back, and neither can a structure that is already `IN_SERVICE`; all three cases are refused with `ERR_STORAGE_STATE_INVALID`."
    PRD: "A successful return sets `storage_status` to `IN_SERVICE` and recomputes the operation's posture, which returns to `OPEN` when no other restricting condition remains."
    Design: Corner/cross_cutting_complexity_layers/freeboard_and_overflow_thresholds_fire_at_their_exact_boundaries
    """
    ctx = setup_scenario(stage="COVERED", intake_gallons=1000000)
    operation_id = ctx["operation"]["id"]
    storage_id = ctx["storage"]["id"]
    operator_headers = ctx["operator_headers"]

    file_storage_inspection(
        operation_id,
        storage_id,
        operator_headers,
        inspected_on="2026-07-22T00:00:00Z",
        measured_freeboard_in=23,
        visual_condition="NORMAL",
    )
    alerted = validate_success(client.get_manure_storage(storage_id, operator_headers))
    assert alerted["storage_status"] == "FREEBOARD_ALERT"

    seepage = file_storage_inspection(
        operation_id,
        storage_id,
        operator_headers,
        inspected_on="2026-07-24T00:00:00Z",
        measured_freeboard_in=30,
        visual_condition="SEEPAGE",
    )
    assert_quantity(seepage["measured_volume_gallons"], 4263885.00, "measured_volume_gallons")
    assert_quantity(seepage["freeboard_deficit_in"], 0.00, "freeboard_deficit_in")
    assert seepage["alert_raised"] is True

    structure = validate_success(client.get_manure_storage(storage_id, operator_headers))
    assert structure["storage_status"] == "FREEBOARD_ALERT"
    assert_storage_balance(
        structure,
        intake=1000000.00,
        precipitation=3263885.00,
        current=4263885.00,
        available=224415.00,
        days=24,
    )

    validate_error(
        client.return_storage_to_service(storage_id, operator_headers),
        ApiErrorId.ERR_STORAGE_STATE_INVALID.value,
    )
    assert (
        validate_success(client.get_manure_storage(storage_id, operator_headers))[
            "storage_status"
        ]
        == "FREEBOARD_ALERT"
    )

    cleared = file_storage_inspection(
        operation_id,
        storage_id,
        ADMIN_HEADERS,
        inspected_on="2026-07-26T00:00:00Z",
        measured_freeboard_in=30,
        visual_condition="NORMAL",
    )
    assert cleared["alert_raised"] is False

    returned = validate_success(
        client.return_storage_to_service(storage_id, operator_headers)
    )
    assert returned["storage_status"] == "IN_SERVICE"
    assert_posture(
        validate_success(client.get_operation(operation_id, operator_headers)), "OPEN"
    )

    validate_error(
        client.return_storage_to_service(storage_id, operator_headers),
        ApiErrorId.ERR_STORAGE_STATE_INVALID.value,
    )


def test_measured_freeboard_at_six_inches_suspends_the_operation():
    """Six inches is the inclusive edge of the overflow threshold, so it takes
    the structure to overflow imminent — not merely to a freeboard alert — and
    suspends the operation.

    PRD: "When `measured_freeboard_in` is 6 inches or less, the structure moves to `OVERFLOW_IMMINENT` — from `IN_SERVICE` or from `FREEBOARD_ALERT` alike — and the operation's posture is recomputed to `SUSPENDED`."
    PRD: "`SUSPENDED` when `open_discharge_incident_count` is at least 1, **or** any storage structure of the operation has `storage_status` equal to `OVERFLOW_IMMINENT`."
    Design: Corner/cross_cutting_complexity_layers/freeboard_and_overflow_thresholds_fire_at_their_exact_boundaries
    """
    ctx = setup_scenario(stage="COVERED", intake_gallons=1000000)
    operation_id = ctx["operation"]["id"]
    storage_id = ctx["storage"]["id"]
    operator_headers = ctx["operator_headers"]

    register = file_storage_inspection(
        operation_id,
        storage_id,
        operator_headers,
        inspected_on="2026-07-28T00:00:00Z",
        measured_freeboard_in=6,
        visual_condition="NORMAL",
    )
    assert_quantity(register["measured_volume_gallons"], 5161545.00, "measured_volume_gallons")
    assert_quantity(register["freeboard_deficit_in"], 18.00, "freeboard_deficit_in")
    assert register["alert_raised"] is True

    structure = validate_success(client.get_manure_storage(storage_id, operator_headers))
    assert structure["storage_status"] == "OVERFLOW_IMMINENT", (
        "6 inches is on the overflow side of the boundary, not the alert side"
    )
    assert_storage_balance(
        structure,
        intake=1000000.00,
        precipitation=4161545.00,
        current=5161545.00,
        available=-673245.00,
        days=0,
    )
    assert_posture(
        validate_success(client.get_operation(operation_id, operator_headers)),
        "SUSPENDED",
        discharges=0,
    )


def test_application_event_fan_out_is_visible_in_its_own_response_and_the_next_read():
    """The record's own response already carries its derived load, and each of
    the four places the write fans out to reports the new figure on the very
    next read.

    PRD: "Writing the record then fans out to four other places in the same request."
    PRD: "All four effects are visible in the response to the request that caused them and in every subsequent read."
    Design: Corner/consistency_model/every_write_is_visible_in_its_own_response_and_the_next_read
    """
    ctx = setup_ready_operation()
    operation_id = ctx["operation"]["id"]
    storage_id = ctx["storage"]["id"]
    budget_id = ctx["budget"]["id"]
    field_id = ctx["field"]["id"]
    operator_headers = ctx["operator_headers"]

    event = record_application(
        operation_id,
        ctx["plan"]["id"],
        budget_id,
        storage_id,
        operator_headers,
        applied_on="2026-07-10T00:00:00Z",
        gallons_applied=100000,
        acres_treated=20,
        precipitation_forecast_in_24h=0.1,
    )
    assert event["event_status"] == "RECORDED"
    assert_quantity(event["rate_gal_per_acre"], 5000.00, "rate_gal_per_acre")
    assert_quantity(event["n_applied_lbs"], 1560.00, "n_applied_lbs")
    assert_quantity(event["p2o5_applied_lbs"], 1000.00, "p2o5_applied_lbs")

    budget = validate_success(client.get_field_budget(budget_id, operator_headers))
    assert_budget_ledger(budget, applied=100000.00, remaining=314396, total=414396)

    structure = validate_success(client.get_manure_storage(storage_id, operator_headers))
    assert_storage_balance(
        structure,
        intake=1000000.00,
        precipitation=0.00,
        outflow=100000.00,
        current=900000.00,
        committed=0.00,
        available=3588300.00,
        days=388,
    )

    field = validate_success(client.get_field(field_id, operator_headers))
    _same_instant(field["last_application_on"], "2026-07-10T00:00:00Z", "last_application_on")

    operation = validate_success(client.get_operation(operation_id, operator_headers))
    assert_quantity(
        operation["recorded_annual_manure_gallons"],
        100000.00,
        "recorded_annual_manure_gallons",
    )
