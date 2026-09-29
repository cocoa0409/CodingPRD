"""Domain services: lookups, phase gates, quarter derivation, recomputation and
the four cascade paths of PRD section 2.10.

The single rule that shapes this module: no derived money field is ever
incremented in place.  ``sync`` recomputes every derived figure of a cycle from
the full set of contributing rows and applies each row's changes exactly once,
so a row touched by a cascade is bumped by exactly one version.
"""

import clock
import db
import util
from errors import fail
from services import constants as C

# --------------------------------------------------------------------------
# lookups (ladder rungs 3 and 4)
# --------------------------------------------------------------------------


def _lookup(collection, value, error_id):
    if not isinstance(value, str) or not value:
        fail(error_id)
    row = collection.get(value)
    if row is None:
        fail(error_id)
    return row


def get_agency(value):
    return _lookup(db.agencies, value, "ERR_AGENCY_NOT_FOUND")


def get_cycle(value):
    return _lookup(db.budget_cycles, value, "ERR_BUDGET_CYCLE_NOT_FOUND")


def get_forecast(value):
    return _lookup(db.revenue_forecasts, value, "ERR_REVENUE_FORECAST_NOT_FOUND")


def get_request(value):
    return _lookup(db.agency_requests, value, "ERR_AGENCY_REQUEST_NOT_FOUND")


def get_package(value):
    return _lookup(db.decision_packages, value, "ERR_DECISION_PACKAGE_NOT_FOUND")


def get_recommendation(value):
    return _lookup(db.executive_recommendations, value, "ERR_RECOMMENDATION_NOT_FOUND")


def get_appropriation(value):
    return _lookup(db.appropriations, value, "ERR_APPROPRIATION_NOT_FOUND")


def get_allotment(value):
    return _lookup(db.allotments, value, "ERR_ALLOTMENT_NOT_FOUND")


def get_transfer(value):
    return _lookup(db.budget_transfers, value, "ERR_TRANSFER_NOT_FOUND")


def get_expenditure(value):
    return _lookup(db.expenditures, value, "ERR_EXPENDITURE_NOT_FOUND")


def get_grant(value):
    return _lookup(db.federal_grants, value, "ERR_FEDERAL_GRANT_NOT_FOUND")


def get_commitment(value):
    return _lookup(db.match_commitments, value, "ERR_MATCH_COMMITMENT_NOT_FOUND")


# --------------------------------------------------------------------------
# ownership chains
# --------------------------------------------------------------------------


def cycle_of(row):
    """The BudgetCycle owning any cycle-scoped row (or None when unreachable)."""
    if "budget_cycle_id" in row:
        return db.budget_cycles.get(row["budget_cycle_id"])
    if "agency_request_id" in row:
        parent = db.agency_requests.get(row["agency_request_id"])
        return cycle_of(parent) if parent else None
    if "appropriation_id" in row:
        parent = db.appropriations.get(row["appropriation_id"])
        return cycle_of(parent) if parent else None
    if "decision_package_id" in row:
        parent = db.decision_packages.get(row["decision_package_id"])
        return cycle_of(parent) if parent else None
    return None


def agency_of(row):
    """The owning agency id reached from any row, following its chain."""
    if "agency_id" in row:
        return row["agency_id"]
    if "agency_request_id" in row:
        parent = db.agency_requests.get(row["agency_request_id"])
        return agency_of(parent) if parent else None
    if "appropriation_id" in row:
        parent = db.appropriations.get(row["appropriation_id"])
        return agency_of(parent) if parent else None
    if "decision_package_id" in row:
        parent = db.decision_packages.get(row["decision_package_id"])
        return agency_of(parent) if parent else None
    if "federal_grant_id" in row:
        parent = db.federal_grants.get(row["federal_grant_id"])
        return agency_of(parent) if parent else None
    return None


def appropriations_of(cycle):
    rows = [a for a in db.appropriations.values() if a["budget_cycle_id"] == cycle["id"]]
    return db.sort_rows(rows)


def packages_of(request_id):
    rows = [p for p in db.decision_packages.values() if p["agency_request_id"] == request_id]
    return db.sort_rows(rows)


def measures_of(package_id):
    rows = [
        m for m in db.performance_measures.values() if m["decision_package_id"] == package_id
    ]
    return db.sort_rows(rows)


def actions_of(appropriation_id):
    rows = [
        a for a in db.committee_actions.values() if a["appropriation_id"] == appropriation_id
    ]
    return sorted(rows, key=lambda r: (r["sequence_number"], r["created_at"], r["_seq"]))


def commitments_of_appropriation(appropriation_id):
    rows = [
        m
        for m in db.match_commitments.values()
        if m["appropriation_id"] == appropriation_id
    ]
    return db.sort_rows(rows)


def commitments_of_grant(grant_id):
    rows = [m for m in db.match_commitments.values() if m["federal_grant_id"] == grant_id]
    return db.sort_rows(rows)


# --------------------------------------------------------------------------
# phase gates (ladder rung 10)
# --------------------------------------------------------------------------


def require_phase(cycle, allowed):
    if cycle is None:
        return
    if cycle["phase"] not in allowed:
        fail(
            "ERR_CYCLE_PHASE_INVALID",
            "The owning budget cycle is in phase %s, which does not permit this operation."
            % cycle["phase"],
        )


def require_not_closed(cycle):
    """Every write against a CLOSED cycle is rejected."""
    if cycle is not None and cycle["phase"] == "CLOSED":
        fail("ERR_CYCLE_PHASE_INVALID", "The owning budget cycle is CLOSED.")


# --------------------------------------------------------------------------
# the fiscal calendar (PRD 2.6)
# --------------------------------------------------------------------------


def fiscal_start(cycle):
    return util.parse_date(cycle["fiscal_year_start_date"])


def raw_quarter(cycle):
    """The quarter whose half-open interval contains the logical clock.

    0 when the clock is before quarter 1 and 5 when it is at or after twelve
    months past the start date; those out-of-band values are what the
    ERR_QUARTER_CLOSED / ERR_QUARTER_NOT_OPEN comparisons need.
    """
    start = fiscal_start(cycle)
    now = clock.get_now()
    if now < start:
        return 0
    for quarter in (1, 2, 3, 4):
        if now < util.add_months(start, 3 * quarter):
            return quarter
    return 5


def current_quarter(cycle):
    """raw_quarter clamped into 1..4 for the constant tables."""
    return min(4, max(1, raw_quarter(cycle)))


def cycle_has_ended(cycle):
    return clock.get_now() >= util.add_months(fiscal_start(cycle), 12)


def check_quarter(cycle, quarter, exact=True):
    """Rung 21 then rung 22 against the derived current cycle quarter."""
    derived = raw_quarter(cycle)
    if quarter < derived:
        fail(
            "ERR_QUARTER_CLOSED",
            "Quarter %d is earlier than the current cycle quarter." % quarter,
        )
    if exact and quarter > derived:
        fail(
            "ERR_QUARTER_NOT_OPEN",
            "Quarter %d is later than the current cycle quarter." % quarter,
        )


# --------------------------------------------------------------------------
# derived appropriation figures
# --------------------------------------------------------------------------


def authority_of(view):
    return (
        view["enacted_amount_cents"]
        + view["transfers_in_cents"]
        - view["transfers_out_cents"]
    )


def ledger_figures(view):
    """Recompute every derived money field of one appropriation from its rows."""
    appr_id = view["id"]
    transfers_in = 0
    transfers_out = 0
    for transfer in db.budget_transfers.values():
        if transfer["status"] != "EXECUTED":
            continue
        if transfer["target_appropriation_id"] == appr_id:
            transfers_in += transfer["amount_cents"]
        if transfer["source_appropriation_id"] == appr_id:
            transfers_out += transfer["amount_cents"]
    released = 0
    for allotment in db.allotments.values():
        if allotment["appropriation_id"] == appr_id and allotment["status"] == "RELEASED":
            released += allotment["released_cents"]
    expended = 0
    for expenditure in db.expenditures.values():
        if (
            expenditure["appropriation_id"] == appr_id
            and expenditure["status"] == "POSTED"
        ):
            expended += expenditure["amount_cents"]
    authority = view["enacted_amount_cents"] + transfers_in - transfers_out
    figures = {
        "transfers_in_cents": transfers_in,
        "transfers_out_cents": transfers_out,
        "released_cents": released,
        "expended_cents": expended,
        "available_cash_cents": released - expended,
        "available_authority_cents": authority - expended,
    }
    return figures, authority


def derive_cash_status(released, authority):
    if released == 0:
        return "UNRELEASED"
    if released >= authority:
        return "FULLY_RELEASED"
    return "PARTIALLY_RELEASED"


# --------------------------------------------------------------------------
# derived cycle figures
# --------------------------------------------------------------------------


def adopted_general_revenue(cycle):
    total = 0
    for forecast in db.revenue_forecasts.values():
        if (
            forecast["budget_cycle_id"] == cycle["id"]
            and forecast["status"] == "ADOPTED"
            and forecast["fund_type"] == "GENERAL"
        ):
            total += forecast["amount_cents"]
    return total


def has_adopted_general_forecast(cycle):
    return adopted_general_revenue(cycle) > 0


def has_any_adopted_forecast(cycle):
    for forecast in db.revenue_forecasts.values():
        if forecast["budget_cycle_id"] == cycle["id"] and forecast["status"] == "ADOPTED":
            return True
    return False


def total_recommended(cycle):
    total = 0
    for rec in db.executive_recommendations.values():
        if rec["status"] != "APPROVED":
            continue
        request = db.agency_requests.get(rec["agency_request_id"])
        if request is not None and request["budget_cycle_id"] == cycle["id"]:
            total += rec["recommended_amount_cents"]
    return total


def projected_cash_for_quarter(cycle, quarter, adopted=None):
    if adopted is None:
        adopted = cycle["adopted_general_fund_revenue_cents"]
    factor = C.CASH_FLOW_FACTOR[min(4, max(1, quarter))]
    return util.pct_of_cents(factor, adopted)


def cycle_figures(cycle, views):
    """Recompute the cycle aggregates from the (possibly pending) appropriations."""
    adopted = adopted_general_revenue(cycle)
    required_reserve = util.pct_of_cents(cycle["constitutional_reserve_pct"], adopted)
    released = 0
    expended = 0
    reverted = 0
    carryforward = 0
    emergency = 0
    for view in views:
        released += view["released_cents"]
        expended += view["expended_cents"]
        reverted += view["reverted_cents"]
        carryforward += view["carryforward_cents"]
        if view["is_emergency"] and view["authority_status"] == "ENACTED":
            emergency += view["enacted_amount_cents"]
    projected = projected_cash_for_quarter(cycle, current_quarter(cycle), adopted)
    utilization = util.ratio(released, projected if projected > 0 else 1, 4)
    posture = (
        "CONSTRAINED" if utilization >= util.dec(C.CASH_POSTURE_THRESHOLD) else "NORMAL"
    )
    return {
        "adopted_general_fund_revenue_cents": adopted,
        "required_reserve_cents": required_reserve,
        "total_recommended_cents": total_recommended(cycle),
        "emergency_granted_cents": emergency,
        "total_released_cents": released,
        "total_expended_cents": expended,
        "total_reverted_cents": reverted,
        "total_carryforward_cents": carryforward,
        "projected_cumulative_cash_cents": projected,
        "cash_utilization_pct": float(utilization),
        "cash_posture": posture,
    }


# --------------------------------------------------------------------------
# the cascade driver
# --------------------------------------------------------------------------


def sync(
    cycle,
    derive_cash_for=(),
    appr_extra=None,
    cycle_extra=None,
    touch_cycle=True,
    force_cycle=False,
    force_appr=(),
):
    """Recompute every derived figure of one cycle and apply each change once.

    ``derive_cash_for`` names appropriations whose cash dimension must be
    re-derived from released cash against current authority (a FROZEN row is
    never moved by that derivation).  ``appr_extra`` and ``cycle_extra`` carry
    the caller's own field writes so that they land in the same single mutation
    as the recomputation, keeping the version increment at exactly one per row.

    ``touch_cycle`` is False for the cascades of PRD 2.10 that stop at the
    appropriation (expenditure posting/voiding, transfer execution/reversal,
    committee replay and enactment all leave the cycle row alone).
    ``force_cycle`` / ``force_appr`` bump a row whose declared transition must
    increment its version even when every recomputed value came out identical.
    """
    appr_extra = appr_extra or {}
    cycle_extra = cycle_extra or {}
    derive_cash_for = set(derive_cash_for)
    force_appr = set(force_appr)

    rows = appropriations_of(cycle)
    pending = {}
    views = []
    for row in rows:
        extra = appr_extra.get(row["id"], {})
        view = dict(row)
        view.update(extra)
        figures, authority = ledger_figures(view)
        view.update(figures)
        updates = dict(extra)
        updates.update(figures)
        if row["id"] in derive_cash_for and view["cash_status"] != "FROZEN":
            status = derive_cash_status(figures["released_cents"], authority)
            updates["cash_status"] = status
            view["cash_status"] = status
        pending[row["id"]] = updates
        views.append(view)

    cycle_updates = cycle_figures(cycle, views)
    cycle_updates.update(cycle_extra)
    constrained = cycle_updates["cash_posture"] == "CONSTRAINED"

    for view in views:
        hold = (
            constrained
            and view["fund_type"] == "GENERAL"
            and view["cash_status"] == "UNRELEASED"
        )
        pending[view["id"]]["release_hold"] = hold

    for row in rows:
        changed = db.apply_changes(row, pending[row["id"]])
        if not changed and row["id"] in force_appr:
            db.touch(row)
    if touch_cycle:
        changed = db.apply_changes(cycle, cycle_updates)
        if not changed and force_cycle:
            db.touch(cycle)


def sync_many(cycles, **kwargs):
    seen = set()
    for cycle in cycles:
        if cycle is None or cycle["id"] in seen:
            continue
        seen.add(cycle["id"])
        sync(cycle, **kwargs)


def initial_release_hold(cycle, fund_type, cash_status):
    """release_hold for a row being created, without mutating anything."""
    return (
        cycle["cash_posture"] == "CONSTRAINED"
        and fund_type == "GENERAL"
        and cash_status == "UNRELEASED"
    )


# --------------------------------------------------------------------------
# request total (calculation agency_request_total)
# --------------------------------------------------------------------------


def request_total(request):
    additive = 0
    subtractive = 0
    for package in db.decision_packages.values():
        if package["agency_request_id"] != request["id"]:
            continue
        if package["status"] not in ("PROPOSED", "RECOMMENDED"):
            continue
        if package["package_type"] == "REDUCTION":
            subtractive += package["amount_cents"]
        else:
            additive += package["amount_cents"]
    return request["base_budget_cents"] + additive - subtractive


def recompute_request_total(request, extra=None):
    updates = {"total_request_cents": request_total(request)}
    if extra:
        updates.update(extra)
    db.apply_changes(request, updates)


# --------------------------------------------------------------------------
# federal grant / agency cascades (PRD 3.8)
# --------------------------------------------------------------------------


def grant_period(grant):
    return grant["_period_start"], grant["_period_end"]


def periods_overlap(grant_a, grant_b):
    a_start, a_end = grant_period(grant_a)
    b_start, b_end = grant_period(grant_b)
    return a_start < b_end and b_start < a_end


def match_status_for(grant, committed, any_at_risk):
    required = grant["required_state_match_cents"]
    if committed < required and committed == 0:
        return "SHORTFALL" if any_at_risk else "UNMET"
    if committed < required:
        return "SHORTFALL"
    if any_at_risk:
        return "AT_RISK"
    return "MET"


def recompute_grant(grant):
    committed = 0
    any_at_risk = False
    for commitment in db.match_commitments.values():
        if commitment["federal_grant_id"] != grant["id"]:
            continue
        if commitment["status"] == "COMMITTED":
            committed += commitment["committed_match_cents"]
        elif commitment["status"] == "AT_RISK":
            any_at_risk = True
    db.apply_changes(
        grant,
        {
            "committed_match_cents": committed,
            "match_status": match_status_for(grant, committed, any_at_risk),
        },
    )


def recompute_agency(agency):
    flag = "CLEAR"
    statuses = [
        g["match_status"]
        for g in db.federal_grants.values()
        if g["agency_id"] == agency["id"]
    ]
    if "SHORTFALL" in statuses:
        flag = "DEFICIENT"
    elif "AT_RISK" in statuses:
        flag = "AT_RISK"
    db.apply_changes(agency, {"federal_compliance_flag": flag})


def recompute_grants_and_agencies(grant_ids):
    agency_ids = set()
    for grant_id in grant_ids:
        grant = db.federal_grants.get(grant_id)
        if grant is None:
            continue
        recompute_grant(grant)
        agency_ids.add(grant["agency_id"])
    for agency_id in agency_ids:
        agency = db.agencies.get(agency_id)
        if agency is not None:
            recompute_agency(agency)


def overlapping_committed_total(appropriation_id, grant, exclude_ids=()):
    """Sum of COMMITTED pledges on this appropriation overlapping ``grant``."""
    total = 0
    for commitment in commitments_of_appropriation(appropriation_id):
        if commitment["id"] in exclude_ids:
            continue
        if commitment["status"] != "COMMITTED":
            continue
        other = db.federal_grants.get(commitment["federal_grant_id"])
        if other is None:
            continue
        if periods_overlap(other, grant):
            total += commitment["committed_match_cents"]
    return total


def impair_commitments(appropriation):
    """COMMITTED -> AT_RISK for over-pledged rows after authority fell."""
    available = appropriation["available_authority_cents"]
    touched = set()
    for commitment in commitments_of_appropriation(appropriation["id"]):
        if commitment["status"] != "COMMITTED":
            continue
        grant = db.federal_grants.get(commitment["federal_grant_id"])
        if grant is None:
            continue
        total = overlapping_committed_total(appropriation["id"], grant)
        if total > available:
            db.apply_changes(commitment, {"status": "AT_RISK"})
            touched.add(grant["id"])
    return touched


def restore_commitments(appropriation):
    """AT_RISK -> COMMITTED for rows that fit again after authority recovered."""
    available = appropriation["available_authority_cents"]
    touched = set()
    for commitment in commitments_of_appropriation(appropriation["id"]):
        if commitment["status"] != "AT_RISK":
            continue
        grant = db.federal_grants.get(commitment["federal_grant_id"])
        if grant is None:
            continue
        total = overlapping_committed_total(
            appropriation["id"], grant, exclude_ids={commitment["id"]}
        )
        if total + commitment["committed_match_cents"] <= available:
            db.apply_changes(commitment, {"status": "COMMITTED"})
            touched.add(grant["id"])
    return touched


# --------------------------------------------------------------------------
# maintenance of effort spend refresh
# --------------------------------------------------------------------------


def moe_spend(agency_id, cycle_id):
    total = 0
    for expenditure in db.expenditures.values():
        if expenditure["status"] != "POSTED":
            continue
        appropriation = db.appropriations.get(expenditure["appropriation_id"])
        if appropriation is None:
            continue
        if (
            appropriation["fund_type"] == "GENERAL"
            and appropriation["agency_id"] == agency_id
            and appropriation["budget_cycle_id"] == cycle_id
        ):
            total += expenditure["amount_cents"]
    return total


def refresh_moe_spend(agency_id, cycle_id):
    spend = moe_spend(agency_id, cycle_id)
    for grant in db.federal_grants.values():
        if grant["agency_id"] == agency_id and grant["budget_cycle_id"] == cycle_id:
            db.apply_changes(grant, {"moe_current_spend_cents": spend})
