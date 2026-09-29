"""The annual performance test, cure rights and termination notice."""

from flask import Blueprint

import validate as v
from auth import READ_ROLES, authenticate
from db import new_row, serialize, store, touch
from errors import ApiError
from money import as_json_number, dec
from response import ok
from routes.common import paged
from services import calc, core
from timeutil import add_days_iso

bp = Blueprint("perf", __name__)

CURE_ACTIONS = ("ELECT_CURE", "PAY_CURE")


def _str_rows(agreement, accepted):
    """The deliberately narrow benchmark input set (PRD §3.7)."""
    rows = []
    for package in accepted:
        if package["benchmark_status"] != "ACCEPTED":
            continue
        for benchmark in core.benchmarks_of(package["id"]):
            if benchmark["source"] == "STR_REPORT" and not benchmark["superseded"]:
                rows.append(benchmark)
    return rows


# ---------------------------------------------------------------------------
# POST /hotel-management/agreements/{id}/performance-tests
# ---------------------------------------------------------------------------

@bp.post("/hotel-management/agreements/<agreement_id>/performance-tests")
def score_test(agreement_id):
    authenticate(["PlatformAdmin"])
    body = v.body()
    fiscal_year = v.req_int(body, "fiscal_year", ge=2000, le=2100)

    agreement = core.find_agreement(agreement_id)

    # rule 40 precedes rule 41 in the absolute precedence list of §2.8
    budget = core.select_budget_for_year(agreement["id"], fiscal_year)
    if budget is None:
        raise ApiError("ERR_BUDGET_NOT_APPROVED")

    accepted = [
        p
        for p in core.packages_of(agreement["id"])
        if p["fiscal_year"] == fiscal_year and p["financial_status"] == "ACCEPTED"
    ]
    if not accepted:
        raise ApiError("ERR_NO_ACCEPTED_PERIODS")

    str_rows = _str_rows(agreement, accepted)
    if len(str_rows) < agreement["min_benchmark_months"]:
        raise ApiError("ERR_INSUFFICIENT_BENCHMARK_DATA")

    snapshot = budget["budgeted_agop_cents"]
    prorated = calc.prorated_budget_agop(
        snapshot, len(accepted), agreement["test_periods_expected"]
    )
    if prorated <= 0:
        raise ApiError("ERR_BUDGET_AGOP_NON_POSITIVE")

    actual = sum(p["agop_cents"] for p in accepted)
    achievement = calc.gop_achievement(actual, prorated)
    weighted = calc.rpi_weighted(str_rows)
    simple = calc.rpi_simple_average(str_rows)

    # every threshold comparison is made against the ROUNDED figure
    failed = achievement < dec(agreement["gop_test_threshold_pct"]) and weighted < dec(
        agreement["rpi_test_threshold"]
    )

    row = new_row(
        {
            "agreement_id": agreement["id"],
            "fiscal_year": fiscal_year,
            "accepted_period_count": len(accepted),
            "actual_agop_cents": actual,
            "budgeted_agop_snapshot_cents": snapshot,
            "budget_source_status": budget["status"],
            "prorated_budget_agop_cents": prorated,
            "gop_achievement_pct": as_json_number(achievement),
            "rpi_weighted": as_json_number(weighted),
            "rpi_simple_average": as_json_number(simple),
            "str_month_count": len(str_rows),
            "status": "PASSED",
            "cure_payment_due_cents": 0,
            "cure_paid_cents": 0,
            "cure_deadline_utc": None,
            "streak_after_test": 0,
        }
    )
    store.performance_tests[row["id"]] = row

    if not failed:
        agreement["performance_failure_streak"] = 0
        touch(agreement)
        return ok(serialize(row), 201)

    streak_after = agreement["performance_failure_streak"] + 1
    row["streak_after_test"] = streak_after
    row["cure_payment_due_cents"] = max(0, prorated - actual)

    if streak_after >= agreement["consecutive_failure_limit"]:
        # no cure right arises; the agreement stays where it is
        row["status"] = "TERMINATION_TRIGGERED"
        agreement["performance_failure_streak"] = streak_after
        touch(agreement)
        return ok(serialize(row), 201)

    row["status"] = "FAILED_CURABLE"
    row["cure_deadline_utc"] = add_days_iso(store.now_iso, agreement["cure_window_days"])
    if agreement["status"] == "ACTIVE":
        # ACTIVE -> CURE_PERIOD carries the streak bump and the distribution hold
        agreement["status"] = "CURE_PERIOD"
        agreement["performance_failure_streak"] = streak_after
        core.raise_distribution_hold(agreement)
    return ok(serialize(row), 201)


@bp.get("/hotel-management/agreements/<agreement_id>/performance-tests")
def list_tests(agreement_id):
    authenticate(READ_ROLES)
    agreement = core.find_agreement(agreement_id)
    rows = [t for t in store.performance_tests.values() if t["agreement_id"] == agreement["id"]]
    rows.sort(key=lambda t: t["_seq"])
    fiscal_year = v.query_int("fiscal_year")
    status = v.query_str("status")
    if fiscal_year is not None:
        rows = [r for r in rows if r["fiscal_year"] == fiscal_year]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return paged(rows)


# ---------------------------------------------------------------------------
# POST /hotel-management/performance-tests/{id}/cure
# ---------------------------------------------------------------------------

@bp.post("/hotel-management/performance-tests/<test_id>/cure")
def cure_test(test_id):
    authenticate(["HotelManagerOps"])
    body = v.body()
    action = v.req_str(body, "action")
    if action == "PAY_CURE":
        v.req_int(body, "payment_amount_cents", ge=0)
    v.check_enum(action, CURE_ACTIONS, "action")

    test = core.find_test(test_id)
    agreement = core.find_agreement(test["agreement_id"])

    origins = {"ELECT_CURE": ("FAILED_CURABLE",), "PAY_CURE": ("CURE_ELECTED",)}
    if test["status"] not in origins[action]:
        raise ApiError("ERR_INVALID_TEST_STATE")

    if not core.datetime_at_or_before(store.now_iso, test["cure_deadline_utc"]):
        raise ApiError("ERR_CURE_WINDOW_CLOSED")

    if action == "ELECT_CURE":
        test["status"] = "CURE_ELECTED"
        touch(test)
        return ok(serialize(test))

    payment = body["payment_amount_cents"]
    if payment < test["cure_payment_due_cents"]:
        raise ApiError("ERR_CURE_PAYMENT_INSUFFICIENT")

    test["status"] = "CURED"
    test["cure_paid_cents"] = payment
    touch(test)

    if agreement["status"] == "CURE_PERIOD":
        agreement["status"] = "ACTIVE"
        agreement["performance_failure_streak"] = 0
        agreement["working_capital_balance_cents"] = (
            agreement["working_capital_balance_cents"] + payment
        )
        core.release_distribution_hold(agreement)
    return ok(serialize(test))


# ---------------------------------------------------------------------------
# POST /hotel-management/performance-tests/{id}/terminate
# ---------------------------------------------------------------------------

@bp.post("/hotel-management/performance-tests/<test_id>/terminate")
def terminate(test_id):
    authenticate(["OwnerRep"])
    body = v.body()
    v.opt_str(body, "reason")

    test = core.find_test(test_id)
    agreement = core.find_agreement(test["agreement_id"])
    core.require_active_or_cure(agreement)
    if test["status"] != "TERMINATION_TRIGGERED":
        raise ApiError("ERR_INVALID_TEST_STATE")

    was_cure_period = agreement["status"] == "CURE_PERIOD"

    test["status"] = "TERMINATED_NOTICE_ISSUED"
    touch(test)

    agreement["status"] = "TERMINATION_NOTICED"
    agreement["termination_effective_utc"] = add_days_iso(
        store.now_iso, agreement["termination_notice_days"]
    )
    touch(agreement)

    if was_cure_period:
        # the hold is already up; nothing to freeze, but submitted budgets go
        core.deny_pending_variances(agreement)
        core.supersede_submitted_budgets(agreement)
    else:
        core.raise_distribution_hold(agreement)
        core.deny_pending_variances(agreement)
    return ok(serialize(test))
