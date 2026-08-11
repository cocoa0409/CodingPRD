"""Build/strike tasks: dependency DAG enforcement, advance ordering, and the
season close gate chain."""
from test_helpers import (
    ApiErrorId,
    get_season,
    make_booth,
    make_build_task,
    make_faire_day,
    make_juried_vendor,
    make_season,
    set_clock,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import ANY, OPERATOR, VENDOR_CO
from test_helpers.test_users import make_vendor_headers


def test_build_task_dependency_unmet_blocks_start(api, operator_headers):
    """PRD §3.1: "Advancing a task moves it `PENDING` → `IN_PROGRESS` → `DONE` under
    the `to` parameter: the step into `IN_PROGRESS` is allowed only from `PENDING`
    and only when every task in `depends_on_task_ids` is already `DONE` (otherwise
    `ERR_TASK_DEPENDENCY_UNMET`)"

    Design: Corner/state_machines/build_task_dependency_unmet_blocks_start
    """
    season = make_season(name="Build Revel")
    t1 = make_build_task(season["id"], name="Lay foundations", phase="BUILD")
    t2 = make_build_task(
        season["id"], name="Erect stage", phase="BUILD",
        depends_on_task_ids=[t1["id"]],
    )

    res = api.advance_task(t2["id"], {"to": "IN_PROGRESS"}, OPERATOR)
    validate_error(res, ApiErrorId.ERR_TASK_DEPENDENCY_UNMET, expected_status=409)

    validate_success(api.advance_task(t1["id"], {"to": "IN_PROGRESS"}, OPERATOR), 200)
    validate_success(api.advance_task(t1["id"], {"to": "DONE"}, OPERATOR), 200)

    advanced = validate_success(api.advance_task(t2["id"], {"to": "IN_PROGRESS"}, OPERATOR), 200)
    assert advanced["status"] == "IN_PROGRESS"


def test_build_task_cycle_rejected(api, operator_headers):
    """PRD §3.1: "The dependency list must reference existing tasks of the same
    season and must never introduce a cycle — an addition that would close a
    dependency loop, whether at creation or when later extending a non-terminal
    task's dependencies via `add_task_ids`, is rejected with
    `ERR_TASK_DEPENDENCY_CYCLE`."

    Design: Corner/validations/build_task_cycle_rejected
    """
    season = make_season(name="Cycle Revel")
    t1 = make_build_task(season["id"], name="Lay foundations", phase="BUILD")
    t2 = make_build_task(
        season["id"], name="Erect stage", phase="BUILD",
        depends_on_task_ids=[t1["id"]],
    )

    # T1 -> T2 would close the loop T1 -> T2 -> T1.
    res = api.add_task_dependencies(t1["id"], {"add_task_ids": [t2["id"]]}, OPERATOR)
    validate_error(res, ApiErrorId.ERR_TASK_DEPENDENCY_CYCLE, expected_status=409)

    t1_after = validate_success(api.get_build_task(t1["id"], ANY), 200)
    assert t1_after["depends_on_task_ids"] == []


def test_task_not_advanceable_out_of_order(api, operator_headers):
    """PRD §3.1: "the step into `DONE` is allowed only from `IN_PROGRESS`; any other
    pairing of current state and `to` is rejected with
    `ERR_TASK_NOT_ADVANCEABLE`."

    Design: Corner/errors/task_not_advanceable_out_of_order
    """
    season = make_season(name="OrderGuard Revel")
    task = make_build_task(season["id"], name="Fence perimeter", phase="BUILD")

    # PENDING -> DONE skips IN_PROGRESS.
    res = api.advance_task(task["id"], {"to": "DONE"}, OPERATOR)
    validate_error(res, ApiErrorId.ERR_TASK_NOT_ADVANCEABLE, expected_status=409)

    validate_success(api.advance_task(task["id"], {"to": "IN_PROGRESS"}, OPERATOR), 200)
    done = validate_success(api.advance_task(task["id"], {"to": "DONE"}, OPERATOR), 200)
    assert done["status"] == "DONE"

    # DONE is terminal for advancement.
    res = api.advance_task(task["id"], {"to": "DONE"}, OPERATOR)
    validate_error(res, ApiErrorId.ERR_TASK_NOT_ADVANCEABLE, expected_status=409)


def test_season_close_gates_sequence(api, operator_headers, vendor_coordinator_headers):
    """PRD §3.9: "The season must be `OPEN` (else `ERR_SEASON_INVALID_STATE`) and
    every faire day of the season must already stand in a terminal state —
    `COMPLETED` or `CANCELLED_WEATHER` — else `ERR_UNRESOLVED_FAIRE_DAYS`."
    PRD §3.9: "the season must be in `STRIKE` (else `ERR_SEASON_INVALID_STATE`),
    every booth assignment of the season must stand `SETTLED` or `RELEASED` (else
    `ERR_UNSETTLED_BOOTHS`), and every build task with `phase` `STRIKE` must be
    `DONE` (else `ERR_STRIKE_TASKS_INCOMPLETE`)."

    Design: Corner/validations/season_close_gates_sequence
    """
    set_clock()
    season = make_season(name="Gatechain Revel", volunteer_min_hours=0)
    day = make_faire_day(season["id"], "2026-06-06T00:00:00Z")
    vendor, application = make_juried_vendor(
        season["id"], business_name="Puppet Cart", category="GAMES",
    )
    booth = make_booth(application["id"], "G-01", "2026-06-06T00:00:00Z",
                       "2026-06-21T00:00:00Z")
    validate_success(
        api.confirm_booth(booth["id"], make_vendor_headers(vendor["id"])), 200
    )
    task = make_build_task(season["id"], name="Raze stage", phase="STRIKE")
    validate_success(api.begin_build(season["id"], OPERATOR), 200)
    validate_success(api.open_season(season["id"], OPERATOR), 200)
    validate_success(api.open_sales(day["id"], OPERATOR), 200)

    # Gate 1: an OPEN_FOR_SALES day is not terminal.
    res = api.begin_strike(season["id"], OPERATOR)
    validate_error(res, ApiErrorId.ERR_UNRESOLVED_FAIRE_DAYS, expected_status=409)

    validate_success(api.cancel_weather(day["id"], OPERATOR), 200)
    struck = validate_success(api.begin_strike(season["id"], OPERATOR), 200)
    assert struck["status"] == "STRIKE"

    # Gate 2: a CONFIRMED booth blocks the close.
    res = api.close_season(season["id"], OPERATOR)
    validate_error(res, ApiErrorId.ERR_UNSETTLED_BOOTHS, expected_status=409)

    validate_success(api.settle_booth(booth["id"], vendor_coordinator_headers), 200)

    # Gate 3: an unfinished STRIKE-phase task blocks the close.
    res = api.close_season(season["id"], OPERATOR)
    validate_error(res, ApiErrorId.ERR_STRIKE_TASKS_INCOMPLETE, expected_status=409)

    validate_success(api.advance_task(task["id"], {"to": "IN_PROGRESS"}, OPERATOR), 200)
    validate_success(api.advance_task(task["id"], {"to": "DONE"}, OPERATOR), 200)
    closed = validate_success(api.close_season(season["id"], OPERATOR), 200)
    assert closed["status"] == "CLOSED"
