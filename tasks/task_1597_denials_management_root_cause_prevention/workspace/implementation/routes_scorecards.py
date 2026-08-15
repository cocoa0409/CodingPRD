"""Routes: department scorecards (create, finalize), overturn-rate analytics,
and the denial-event audit trail."""

from decimal import Decimal, ROUND_HALF_UP
from fractions import Fraction

from flask import Blueprint, request

from auth import require_roles
from cascades import finalize_scorecard
from db import store
from envelope import list_response, ok, pagination_params
from errors import (
    ApiError,
    ERR_DUPLICATE_SCORECARD_PERIOD,
    ERR_SCORECARD_NOT_OPEN,
    ERR_VALIDATION,
)
from services import (
    OUTCOME_STATES,
    find_event,
    find_scorecard,
    make_record,
    public,
)
from util import (
    ALL_ROLES,
    DEPARTMENTS,
    get_body,
    parse_date,
    req_date,
    req_enum,
    sort_created,
)

bp = Blueprint("scorecards", __name__)

TWO_DP = Decimal("0.01")


# ---------------------------------------------------------------------------
# Department scorecards
# ---------------------------------------------------------------------------


@bp.post("/rcm/department-scorecards")
@require_roles("RevenueCycleDirector")
def create_scorecard():
    body = get_body()
    department = req_enum(body, "department", DEPARTMENTS)
    start_s = req_date(body, "period_start_date")
    end_s = req_date(body, "period_end_date")
    if parse_date(end_s) <= parse_date(start_s):
        raise ApiError(
            ERR_VALIDATION, 400, "period_end_date must be after period_start_date"
        )
    for sc in store.scorecards.values():
        if sc["department"] == department and sc["period_start_date"] == start_s:
            raise ApiError(
                ERR_DUPLICATE_SCORECARD_PERIOD,
                409,
                "A scorecard already exists for (%s, %s)" % (department, start_s),
            )
    sc = make_record(
        {
            "department": department,
            "period_start_date": start_s,
            "period_end_date": end_s,
            "status": "OPEN",
            "denial_count": 0,
            "preventable_denial_count": 0,
            "denied_cents": 0,
            "preventable_denied_cents": 0,
            "recovered_cents": 0,
            "written_off_cents": 0,
            "expired_denial_count": 0,
            "auto_writeoff_request_count": 0,
            "verified_fix_count": 0,
            "recurrence_count": 0,
            "verified_linked_denied_cents": 0,
            "recurrence_linked_denied_cents": 0,
            "open_task_count": 0,
            "prevention_score_incidence": None,
            "prevention_score_financial": None,
            "score_tier": None,
        }
    )
    store.scorecards[sc["id"]] = sc
    return ok(public(sc), "object", 201)


@bp.get("/rcm/department-scorecards")
@require_roles(*ALL_ROLES)
def list_scorecards():
    items = list(store.scorecards.values())
    department = request.args.get("department")
    if department is not None:
        items = [s for s in items if s["department"] == department]
    status = request.args.get("status")
    if status is not None:
        items = [s for s in items if s["status"] == status]
    return list_response([public(s) for s in sort_created(items)])


@bp.get("/rcm/department-scorecards/<sid>")
@require_roles(*ALL_ROLES)
def get_scorecard(sid):
    return ok(public(find_scorecard(sid)))


@bp.post("/rcm/department-scorecards/<sid>/finalize")
@require_roles("RevenueCycleDirector")
def finalize(sid):
    sc = find_scorecard(sid)
    if sc["status"] != "OPEN":
        raise ApiError(ERR_SCORECARD_NOT_OPEN, 409, "Scorecard is not OPEN")
    finalize_scorecard(sc)
    return ok(public(sc))


# ---------------------------------------------------------------------------
# Overturn-rate analytics
# ---------------------------------------------------------------------------


def _pct(overturned, partial, resolved):
    if resolved == 0:
        return None
    rate = Fraction(100 * (2 * overturned + partial), 2 * resolved)
    dec = Decimal(rate.numerator) / Decimal(rate.denominator)
    return float(dec.quantize(TWO_DP, rounding=ROUND_HALF_UP))


@bp.get("/rcm/analytics/overturn-rates")
@require_roles(*ALL_ROLES)
def overturn_rates():
    group_by = request.args.get("group_by")
    if group_by not in ("payer", "category"):
        raise ApiError(ERR_VALIDATION, 400, "group_by must be 'payer' or 'category'")
    from_s = request.args.get("from_date")
    to_s = request.args.get("to_date")
    from_d = parse_date(from_s, "from_date") if from_s else None
    to_d = parse_date(to_s, "to_date") if to_s else None

    def in_window(appeal):
        if not appeal.get("outcome_recorded_at"):
            return False
        d = parse_date(appeal["outcome_recorded_at"][:10])
        if from_d is not None and d < from_d:
            return False
        if to_d is not None and d > to_d:
            return False
        return True

    # Groups: every key with at least one denial; resolved appeals accumulate in.
    groups = {}
    for denial in store.denials.values():
        key = denial["payer_id"] if group_by == "payer" else denial["category"]
        groups.setdefault(key, {"resolved": 0, "overturned": 0, "partial": 0})
    for appeal in store.appeals.values():
        if appeal["status"] not in OUTCOME_STATES or not in_window(appeal):
            continue
        denial = store.denials.get(appeal["denial_case_id"])
        if denial is None:
            continue
        key = denial["payer_id"] if group_by == "payer" else denial["category"]
        cell = groups.setdefault(key, {"resolved": 0, "overturned": 0, "partial": 0})
        cell["resolved"] += 1
        if appeal["status"] == "OVERTURNED":
            cell["overturned"] += 1
        elif appeal["status"] == "PARTIALLY_OVERTURNED":
            cell["partial"] += 1

    key_field = "payer_id" if group_by == "payer" else "category"
    rows = []
    for key in sorted(groups.keys()):
        cell = groups[key]
        rows.append(
            {
                key_field: key,
                "resolved_count": cell["resolved"],
                "overturned_count": cell["overturned"],
                "partial_count": cell["partial"],
                "overturn_rate_pct": _pct(
                    cell["overturned"], cell["partial"], cell["resolved"]
                ),
            }
        )

    limit, offset = pagination_params()
    total = len(rows)
    page = rows[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    tot_resolved = sum(c["resolved"] for c in groups.values())
    tot_overturned = sum(c["overturned"] for c in groups.values())
    tot_partial = sum(c["partial"] for c in groups.values())
    totals = {
        "resolved_count": tot_resolved,
        "overturned_count": tot_overturned,
        "partial_count": tot_partial,
        "overturn_rate_pct": _pct(tot_overturned, tot_partial, tot_resolved),
    }
    return ok(
        {"group_by": group_by, "rows": page, "totals": totals},
        "object",
        200,
        pagination,
    )


# ---------------------------------------------------------------------------
# Denial events (append-only audit trail)
# ---------------------------------------------------------------------------


@bp.get("/rcm/denial-events")
@require_roles(*ALL_ROLES)
def list_events():
    items = list(store.events.values())
    denial_id = request.args.get("denial_case_id")
    if denial_id is not None:
        items = [e for e in items if e["denial_case_id"] == denial_id]
    etype = request.args.get("event_type")
    if etype is not None:
        items = [e for e in items if e["event_type"] == etype]
    return list_response([public(e) for e in sort_created(items)])


@bp.get("/rcm/denial-events/<eid>")
@require_roles(*ALL_ROLES)
def get_event(eid):
    return ok(public(find_event(eid)))
