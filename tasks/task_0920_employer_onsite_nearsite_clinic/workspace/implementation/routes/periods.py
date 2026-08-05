"""Reporting periods, finalization, restatement and the utilization report."""

from datetime import timedelta
from decimal import Decimal

from core import calc, constants, payload, recompute, serializers, store, timeutil
from core.errors import ApiError
from core.ladder import ObjectResult, Spec, paginate

from .common import (
    contracts_of_employer,
    filter_rows,
    participants_of_employer,
    scope_rule,
    visits_of_employer,
)


def _period(ctx):
    return ctx.entity("period_id")


def _span(period):
    return (
        timeutil.parse_date(period["period_start"]),
        timeutil.parse_date(period["period_end"]),
    )


def _in_period_visits(period):
    start, end = _span(period)
    out = []
    for visit in visits_of_employer(period["employer_id"]):
        service_date = timeutil.parse_date(visit["service_date"])
        if service_date is None or not (start <= service_date <= end):
            continue
        out.append(visit)
    return out


# ------------------------------------------------------------------ create --

def _validate_create(ctx):
    payload.require_id(ctx.body, "employer_id")
    payload.require_date(ctx.body, "period_start")
    payload.require_date(ctx.body, "period_end")


def _create(ctx):
    body = ctx.body
    row = store.insert(
        "period",
        {
            "employer_id": body["employer_id"],
            "period_start": body["period_start"],
            "period_end": body["period_end"],
            "status": "OPEN",
            "restatement_count": 0,
            "finalized_at": None,
            "incentive_awarded_cents": 0,
            "incentive_pending_cents": 0,
            "incentive_paid_cents": 0,
            "incentive_reversed_cents": 0,
            "incentive_forfeited_cents": 0,
        },
    )
    return ObjectResult(serializers.dump("period", row), 201)


def _list(ctx):
    rows = filter_rows(
        store.all_rows("period"),
        {
            "employer_id": ctx.args.get("employer_id"),
            "status": ctx.args.get("status"),
        },
    )
    return paginate(ctx, "period", rows)


def _read(ctx):
    return ObjectResult(serializers.dump("period", _period(ctx)), 200)


# ---------------------------------------------------------------- finalize --

def _state_finalize(ctx):
    period = _period(ctx)
    status = period["status"]
    count = int(period["restatement_count"])
    if status == "OPEN":
        _start, end = _span(period)
        if end is None or not store.now_date() > end:
            raise ApiError("ERR_INVALID_STATE")
        if not count < constants.MAX_RESTATEMENTS:
            raise ApiError("ERR_INVALID_STATE")
        return
    if status == "RESTATING":
        return
    raise ApiError("ERR_INVALID_STATE")


def _price_contract(contract, period, locked_visit_ids):
    start, end = _span(period)
    billable = 0
    for visit in store.all_rows("visit"):
        if visit["id"] not in locked_visit_ids:
            continue
        if visit["site_id"] != contract["site_id"]:
            continue
        billable += 1

    window_start = timeutil.instant_from_date_and_minutes(start, 0)
    window_end = timeutil.instant_from_date_and_minutes(end, 0) + timedelta(
        hours=23, minutes=59, seconds=59
    )
    hours = Decimal("0")
    for shift in store.all_rows("shift"):
        if shift["site_id"] != contract["site_id"]:
            continue
        shift_start = timeutil.parse_instant(shift["shift_start"])
        if shift_start is None or not (window_start <= shift_start <= window_end):
            continue
        # Each shift's hours were already rounded to two decimals half-up at
        # creation; the rounded values are what get added together.
        hours += calc.as_decimal(shift["staffed_hours"])

    gross = calc.contract_gross_fee_cents(contract, billable, hours)
    true_up = calc.contract_true_up_cents(contract, gross)
    contract["billable_visit_count"] = billable
    contract["staffed_hours"] = float(hours)
    contract["gross_fee_cents"] = gross
    contract["true_up_amount_cents"] = true_up
    contract["contract_cost_cents"] = gross + true_up
    return contract["contract_cost_cents"]


def _finalize(ctx):
    period = _period(ctx)
    start, end = _span(period)
    count = int(period["restatement_count"])
    was_restating = period["status"] == "RESTATING"

    # hop 1 -- status and finalized_at
    if was_restating and count == constants.MAX_RESTATEMENTS:
        period["status"] = "CLOSED"
    else:
        period["status"] = "FINALIZED"
    period["finalized_at"] = store.now_iso()

    # hop 2 -- in-period COMPLETED and AMENDED visits lock
    locked_visit_ids = set()
    for visit in _in_period_visits(period):
        if visit["encounter_status"] in ("COMPLETED", "AMENDED"):
            visit["encounter_status"] = "LOCKED"
        if visit["encounter_status"] == "LOCKED":
            locked_visit_ids.add(visit["id"])

    # hop 3 -- price every contract of the employer, then TRUED_UP
    delta = 0
    for contract in store.sorted_rows("contract", contracts_of_employer(period["employer_id"])):
        if contract["status"] not in ("ACTIVE", "TRUED_UP"):
            continue
        previous_cost = (
            int(contract["contract_cost_cents"]) if contract["status"] == "TRUED_UP" else 0
        )
        new_cost = _price_contract(contract, period, locked_visit_ids)
        contract["status"] = "TRUED_UP"
        delta += new_cost - previous_cost

    # hop 4 -- employer program cost to date
    employer = store.get("employer", period["employer_id"])
    if employer is not None:
        employer["program_cost_to_date_cents"] = (
            int(employer["program_cost_to_date_cents"]) + delta
        )

    # Participant completed_visit_count still counts LOCKED encounters, but
    # the locking step does not change the membership of that set.
    recompute.recompute_period_buckets(period)
    return ObjectResult(serializers.dump("period", period), 200)


# ---------------------------------------------------------------- restate ---

def _state_restate(ctx):
    period = _period(ctx)
    if period["status"] != "FINALIZED":
        raise ApiError("ERR_INVALID_STATE")
    if not int(period["restatement_count"]) < constants.MAX_RESTATEMENTS:
        raise ApiError("ERR_INVALID_STATE")


def _restate(ctx):
    period = _period(ctx)
    period["status"] = "RESTATING"
    period["restatement_count"] = int(period["restatement_count"]) + 1
    for visit in _in_period_visits(period):
        if visit["encounter_status"] == "LOCKED":
            visit["encounter_status"] = "AMENDED"
    # Restatement does not unwind pricing: contracts stay TRUED_UP and the
    # employer's program_cost_to_date_cents keeps the amount already booked.
    return ObjectResult(serializers.dump("period", period), 200)


# ------------------------------------------------------- utilization report --

def _rate(numerator, denominator):
    if denominator == 0:
        return 0.0
    return float(
        calc.round_half_up(Decimal(numerator) / Decimal(denominator), constants.ROI_RATIO_DECIMALS)
    )


def _utilization_report(ctx):
    period = _period(ctx)
    start, end = _span(period)
    employer_id = period["employer_id"]

    # --- population figures ------------------------------------------------
    eligible = 0
    for record in store.all_rows("eligibility"):
        if record["employer_id"] != employer_id:
            continue
        rec_start = timeutil.parse_date(record["effective_date"])
        rec_end = (
            timeutil.parse_date(record["termination_date"])
            if record.get("termination_date")
            else None
        )
        if rec_start is None:
            continue
        if calc.spans_overlap(rec_start, rec_end, start, end):
            eligible += 1

    enrolled = 0
    for participant in participants_of_employer(employer_id):
        enrolled_on = timeutil.parse_date(participant.get("enrolled_on"))
        if enrolled_on is not None and enrolled_on <= end:
            enrolled += 1

    delivered = [
        v
        for v in _in_period_visits(period)
        if v["encounter_status"] in constants.DELIVERED_ENCOUNTER_STATES
    ]
    utilizing_ids = {v["participant_id"] for v in delivered}
    utilizing = len(utilizing_ids)
    completed_visits = len(delivered)

    # --- per-track cells ---------------------------------------------------
    cells = {}
    for visit_type in constants.VISIT_TYPES:
        subset = [v for v in delivered if v["visit_type"] == visit_type]
        cells[visit_type] = {
            "visits": len(subset),
            "participants": len({v["participant_id"] for v in subset}),
        }

    # --- avoided cost (round each category first, then sum) ---------------
    avoided = 0
    for visit_type in constants.VISIT_TYPES:
        n = cells[visit_type]["visits"]
        category = calc.round_half_up(
            Decimal(n)
            * Decimal(constants.DIVERSION_RATE_BY_VISIT_TYPE[visit_type])
            * Decimal(constants.BENCHMARK_CENTS_BY_VISIT_TYPE[visit_type]),
            0,
        )
        avoided += int(category)

    program_cost = 0
    for contract in contracts_of_employer(employer_id):
        if contract["status"] == "TRUED_UP":
            program_cost += int(contract["contract_cost_cents"])

    roi_ratio = 0.0
    if program_cost != 0:
        roi_ratio = float(
            calc.round_half_up(
                Decimal(avoided) / Decimal(program_cost), constants.ROI_RATIO_DECIMALS
            )
        )

    month_count = timeutil.months_touched(start, end)
    if enrolled == 0 or month_count == 0:
        pepm = 0
    else:
        pepm = int(
            calc.round_half_up(Decimal(program_cost) / Decimal(enrolled * month_count), 0)
        )

    report = {
        "reporting_period_id": period["id"],
        "eligible_population_count": eligible,
        "enrolled_population_count": enrolled,
        "utilizing_participant_count": utilizing,
        "completed_visit_count": completed_visits,
        "engagement_rate_over_eligible": _rate(utilizing, eligible),
        "engagement_rate_over_enrolled": _rate(utilizing, enrolled),
        "visits_per_utilizer": _rate(completed_visits, utilizing),
        "primary_care_visit_count": cells["PRIMARY_CARE"]["visits"],
        "primary_care_participant_count": cells["PRIMARY_CARE"]["participants"],
        "occ_health_visit_count": cells["OCC_HEALTH"]["visits"],
        "occ_health_participant_count": cells["OCC_HEALTH"]["participants"],
        "wellness_visit_count": cells["WELLNESS"]["visits"],
        "wellness_participant_count": cells["WELLNESS"]["participants"],
        "suppressed_cell_keys": [],
        "avoided_cost_cents": avoided,
        "program_cost_cents": program_cost,
        "roi_ratio": roi_ratio,
        "pepm_cents": pepm,
    }

    # --- small-cell suppression, applied last, employer-side callers only --
    if ctx.role in constants.EMPLOYER_SIDE_ROLES:
        suppressed = []
        prefix = {
            "PRIMARY_CARE": "primary_care",
            "OCC_HEALTH": "occ_health",
            "WELLNESS": "wellness",
        }
        for visit_type in constants.VISIT_TYPES:
            distinct = cells[visit_type]["participants"]
            if distinct == 0:
                continue  # an empty cell re-identifies nobody
            if distinct < constants.MIN_CELL_SIZE:
                report["%s_visit_count" % prefix[visit_type]] = None
                report["%s_participant_count" % prefix[visit_type]] = None
                suppressed.append(visit_type)
        if 0 < utilizing < constants.MIN_CELL_SIZE:
            report["utilizing_participant_count"] = None
            report["visits_per_utilizer"] = None
            suppressed.append("UTILIZING")
        report["suppressed_cell_keys"] = suppressed

    return ObjectResult(report, 200)


_READ_ROLES = [constants.ROLE_PROGRAM_ADMIN, constants.ROLE_EMPLOYER_BENEFITS_ADMIN]

_period_scope = scope_rule(employer_of=lambda ctx: ctx.entity("period_id")["employer_id"])

SPECS = [
    Spec(
        method="POST",
        path="/reporting-periods",
        roles=[constants.ROLE_PROGRAM_ADMIN],
        handler=_create,
        status=201,
        body_fks=[("employer_id", "employer", True)],
        payload=_validate_create,
        is_write=True,
    ),
    Spec(
        method="GET",
        path="/reporting-periods",
        roles=_READ_ROLES,
        handler=_list,
    ),
    Spec(
        method="GET",
        path="/reporting-periods/{period_id}",
        roles=_READ_ROLES,
        handler=_read,
        path_ids=[("period_id", "period")],
        scope=_period_scope,
    ),
    Spec(
        method="POST",
        path="/reporting-periods/{period_id}/finalize",
        roles=[constants.ROLE_PROGRAM_ADMIN],
        handler=_finalize,
        path_ids=[("period_id", "period")],
        checks={10: _state_finalize},
        is_write=True,
    ),
    Spec(
        method="POST",
        path="/reporting-periods/{period_id}/restate",
        roles=[constants.ROLE_PROGRAM_ADMIN],
        handler=_restate,
        path_ids=[("period_id", "period")],
        checks={10: _state_restate},
        is_write=True,
    ),
    Spec(
        method="GET",
        path="/reporting-periods/{period_id}/utilization-report",
        roles=_READ_ROLES,
        handler=_utilization_report,
        path_ids=[("period_id", "period")],
        scope=_period_scope,
    ),
]
