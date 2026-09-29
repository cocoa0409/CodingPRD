"""Derived state: postures, counters, cascades and the pinned calculations."""
from datetime import date
from decimal import Decimal

import clock
import constants as C
from db import db, new_id, sorted_rows
from errors import ApiError
from numeric import dec, q1, q2

# ---------------------------------------------------------------------------
# lookups
# ---------------------------------------------------------------------------

_NOT_FOUND = {
    "projects": "ERR_PROJECT_NOT_FOUND",
    "dams": "ERR_DAM_NOT_FOUND",
    "sites": "ERR_SITE_NOT_FOUND",
    "study_plans": "ERR_STUDY_PLAN_NOT_FOUND",
    "studies": "ERR_STUDY_NOT_FOUND",
    "comments": "ERR_COMMENT_NOT_FOUND",
    "parties": "ERR_PARTY_NOT_FOUND",
    "settlements": "ERR_SETTLEMENT_NOT_FOUND",
    "signatures": "ERR_SIGNATURE_NOT_FOUND",
    "wqcs": "ERR_WQC_NOT_FOUND",
    "measures": "ERR_MEASURE_NOT_FOUND",
    "applications": "ERR_APPLICATION_NOT_FOUND",
    "orders": "ERR_ORDER_NOT_FOUND",
    "obligations": "ERR_OBLIGATION_NOT_FOUND",
}


def fetch(collection_name, row_id):
    collection = getattr(db, collection_name)
    row = collection.get(row_id) if isinstance(row_id, str) else None
    if row is None:
        raise ApiError(_NOT_FOUND[collection_name])
    return row


def get_project(project_id):
    return fetch("projects", project_id)


# ---------------------------------------------------------------------------
# row helpers
# ---------------------------------------------------------------------------


def base_row(versioned=True):
    row = {"id": new_id(), "_seq": db.next_seq(), "created_at": clock.now_iso()}
    if versioned:
        row["updated_at"] = row["created_at"]
        row["version"] = 1
    return row


def touch(row):
    row["updated_at"] = clock.now_iso()
    row["version"] = row.get("version", 1) + 1


# ---------------------------------------------------------------------------
# project navigation
# ---------------------------------------------------------------------------


def project_of_plan(plan):
    return db.projects[plan["project_id"]]


def project_of_study(study):
    return project_of_plan(db.study_plans[study["study_plan_id"]])


def project_of_comment(comment):
    return project_of_plan(db.study_plans[comment["study_plan_id"]])


def project_of_settlement(settlement):
    return db.projects[settlement["project_id"]]


def project_of_application(application):
    return db.projects[application["project_id"]]


def project_of_order(order):
    return project_of_application(db.applications[order["application_id"]])


def project_of_obligation(obligation):
    return project_of_order(db.orders[obligation["order_id"]])


def project_id_of_plan(plan):
    return plan["project_id"]


# ---------------------------------------------------------------------------
# deadlines and timeline posture
# ---------------------------------------------------------------------------


def expiration_date(project):
    return clock.parse_iso_date(project["license_expiration_date"])


def pad_due_date(project):
    return clock.add_months(expiration_date(project), -C.PAD_LEAD_MONTHS)


def application_due_date(project):
    return clock.add_months(expiration_date(project), -C.APPLICATION_LEAD_MONTHS)


def compute_timeline_posture(project):
    if project.get("pad_filed_at") is None:
        milestone = pad_due_date(project)
    elif project.get("application_filed_at") is None:
        milestone = application_due_date(project)
    else:
        return "ON_TRACK"
    slack = clock.days_between(milestone, clock.today())
    if slack < 0:
        return "DELINQUENT"
    if slack <= C.TIMELINE_AT_RISK_DAYS:
        return "AT_RISK"
    return "ON_TRACK"


def refresh_timeline_posture(project):
    project["timeline_posture"] = compute_timeline_posture(project)


# ---------------------------------------------------------------------------
# project row counters
# ---------------------------------------------------------------------------


def refresh_unresolved_mandatory_comment_count(project):
    total = 0
    for comment in db.comments.values():
        plan = db.study_plans.get(comment["study_plan_id"])
        if plan is None or plan["project_id"] != project["id"]:
            continue
        if plan["status"] == "SUPERSEDED":
            continue
        if comment["is_mandatory_condition"] and comment["resolution_status"] == "OPEN":
            total += 1
    project["unresolved_mandatory_comment_count"] = total


def refresh_open_deficiency_count(project):
    project["open_deficiency_count"] = sum(
        1
        for a in db.applications.values()
        if a["project_id"] == project["id"] and a["filing_status"] == "DEFICIENT"
    )


def refresh_compliance_flag_count(project):
    total = 0
    for order in db.orders.values():
        app = db.applications.get(order["application_id"])
        if app is None or app["project_id"] != project["id"]:
            continue
        if order["compliance_state"] == "COMPLIANCE_FLAGGED":
            total += 1
    project["compliance_flag_count"] = total


def refresh_plan_counters(plan):
    open_count = 0
    mandatory_count = 0
    for comment in db.comments.values():
        if comment["study_plan_id"] != plan["id"]:
            continue
        if comment["resolution_status"] == "OPEN":
            open_count += 1
            if comment["is_mandatory_condition"]:
                mandatory_count += 1
    plan["open_comment_count"] = open_count
    plan["unresolved_mandatory_comment_count"] = mandatory_count


# ---------------------------------------------------------------------------
# regulatory posture
# ---------------------------------------------------------------------------


def compute_regulatory_posture(project):
    if (
        project["wqc_status"] == "DENIED"
        or project["compliance_flag_count"] > 0
        or project["timeline_posture"] == "DELINQUENT"
    ):
        return "FROZEN"
    if (
        project["unresolved_mandatory_comment_count"] > 0
        or project["open_deficiency_count"] > 0
        or (project["economically_infeasible"] and not project["infeasibility_waiver_granted"])
        or project["timeline_posture"] == "AT_RISK"
    ):
        return "RESTRICTED"
    return "OPEN"


def refresh_regulatory_posture(project):
    posture = compute_regulatory_posture(project)
    project["regulatory_posture"] = posture
    if posture == "FROZEN":
        suspend_pending_applications(project)
    return posture


def suspend_pending_applications(project):
    for app in sorted_rows(db.applications, lambda a: a["project_id"] == project["id"]):
        if app["filing_status"] in C.FILING_SUSPENDABLE:
            app["filing_status"] = "SUSPENDED"
            touch(app)


def refresh_wqc_mirror(project):
    """project.wqc_status mirrors the most recently created certification (PRD 3.6)."""
    rows = sorted_rows(db.wqcs, lambda w: w["project_id"] == project["id"])
    project["wqc_status"] = rows[-1]["status"] if rows else "NONE"


def finalize_project(project):
    """Recompute every row-counted counter, the ledger and the posture.

    Each of these is a pure function of stored rows, so running it at the end of
    every mutating request yields exactly the value the PRD pins for that
    request.  timeline_posture is deliberately excluded: it moves only at the
    four moments named in PRD 2.7.
    """
    refresh_unresolved_mandatory_comment_count(project)
    refresh_open_deficiency_count(project)
    refresh_compliance_flag_count(project)
    refresh_wqc_mirror(project)
    run_burden_ledger(project)
    return refresh_regulatory_posture(project)


def require_not_frozen(project):
    if project["regulatory_posture"] == "FROZEN":
        raise ApiError("ERR_PROJECT_POSTURE_FROZEN", "Project regulatory posture is FROZEN.")


def require_stage(project, allowed):
    if project["stage"] not in allowed:
        raise ApiError(
            "ERR_PROJECT_STAGE_INVALID",
            "Project stage %s does not permit this operation." % project["stage"],
        )


# ---------------------------------------------------------------------------
# the measure calculation (PRD 3.7)
# ---------------------------------------------------------------------------


def escalation_years(measure, project):
    pad_year = project.get("pad_year")
    if pad_year is None:
        return 0
    return max(0, int(measure["construction_start_year"]) - int(pad_year))


def _escalation_factor(years):
    factor = Decimal(1)
    step = Decimal(1) + C.ESCALATION_RATE
    for _ in range(years):
        factor *= step
    return factor


def run_measure_calculation(measure, project, variant=None):
    variant = variant or measure["cost_estimate_variant"]
    contingency = C.CONTINGENCY_BY_VARIANT[variant]
    years = escalation_years(measure, project)

    escalated = q2(
        dec(measure["capital_cost_usd"]) * (Decimal(1) + contingency) * _escalation_factor(years)
    )
    amort = C.AMORTIZATION_YEARS_BY_CATEGORY[measure["resource_category"]]
    annualized = q2(escalated / Decimal(amort))
    annual_cost = q2(annualized + dec(measure["annual_om_cost_usd"]))

    flow = dec(measure["flow_release_cfs"])
    days = dec(measure["release_days"])
    if variant == "PRELIMINARY":
        loss = q1(flow * days * C.PROXY_MWH_PER_CFS_DAY)
    else:
        kw = flow * dec(measure["gross_head_ft"]) * C.PLANT_EFFICIENCY / C.HYDRO_KW_DIVISOR
        loss = q1(kw * Decimal(24) * days / Decimal(1000))

    value = q2(loss * C.ENERGY_PRICE_USD_PER_MWH)

    measure["cost_estimate_variant"] = variant
    measure["escalated_capital_usd"] = escalated
    measure["annualized_capital_usd"] = annualized
    measure["annual_cost_usd"] = annual_cost
    measure["annual_generation_loss_mwh"] = loss
    measure["annual_generation_value_usd"] = value
    measure["annual_burden_usd"] = q2(annual_cost + value)


# ---------------------------------------------------------------------------
# the project burden ledger (PRD 3.7)
# ---------------------------------------------------------------------------


def live_measures(project):
    return sorted_rows(
        db.measures,
        lambda m: m["project_id"] == project["id"] and m["status"] in C.MEASURE_LIVE_STATUSES,
    )


def admin_charge_rate(total_pme):
    for ceiling, rate in C.ADMIN_CHARGE_TIERS:
        if ceiling is None or total_pme <= ceiling:
            return rate
    return C.ADMIN_CHARGE_TIERS[-1][1]


def run_burden_ledger(project):
    live = live_measures(project)

    total_pme = q2(sum((dec(m["annual_cost_usd"]) for m in live), Decimal(0)))
    total_loss = q1(sum((dec(m["annual_generation_loss_mwh"]) for m in live), Decimal(0)))

    rate = admin_charge_rate(total_pme)
    admin_charge = q2(total_pme * rate)

    energy_value = q2(total_loss * C.ENERGY_PRICE_USD_PER_MWH)
    total_burden = q2(total_pme + admin_charge + energy_value)

    gross_revenue = q2(dec(project["base_annual_generation_mwh"]) * C.ENERGY_PRICE_USD_PER_MWH)
    if gross_revenue > 0:
        ratio = q2(Decimal(100) * total_burden / gross_revenue)
    else:
        ratio = q2(0)

    project["total_pme_annual_cost_usd"] = total_pme
    project["total_generation_loss_mwh"] = total_loss
    project["administrative_annual_charge_usd"] = admin_charge
    project["total_annual_burden_usd"] = total_burden
    project["burden_ratio_pct"] = ratio
    project["economically_infeasible"] = ratio >= C.BURDEN_RATIO_LIMIT_PCT


# ---------------------------------------------------------------------------
# prerequisite graph
# ---------------------------------------------------------------------------


def creates_cycle(measure_id, prerequisite_id):
    """True when pointing measure_id at prerequisite_id would close a cycle."""
    if prerequisite_id is None:
        return False
    if prerequisite_id == measure_id:
        return True
    seen = set()
    current = prerequisite_id
    while current is not None and current not in seen:
        seen.add(current)
        if current == measure_id:
            return True
        row = db.measures.get(current)
        if row is None:
            return False
        current = row.get("prerequisite_measure_id")
    return False


# ---------------------------------------------------------------------------
# settlement tally (PRD 3.5)
# ---------------------------------------------------------------------------


def project_parties(project):
    return sorted_rows(db.parties, lambda p: p["project_id"] == project["id"])


def round_signatures(settlement):
    return sorted_rows(
        db.signatures,
        lambda s: s["settlement_id"] == settlement["id"]
        and s["round_number"] == settlement["round_number"],
    )


def compute_tally(settlement, project):
    parties = project_parties(project)
    total_weight = sum(int(p["vote_weight"]) for p in parties)
    shares = []
    support_sum = Decimal(0)
    for signature in round_signatures(settlement):
        if signature["position"] != "SUPPORT":
            continue
        party = db.parties.get(signature["party_id"])
        if party is None or total_weight <= 0:
            continue
        share = q2(Decimal(100) * Decimal(int(party["vote_weight"])) / Decimal(total_weight))
        shares.append((signature, share))
        support_sum += share
    return {
        "total_vote_weight": total_weight,
        "support_pct": q2(support_sum),
        "shares": shares,
    }


def persist_tally(settlement, tally):
    settlement["total_vote_weight"] = tally["total_vote_weight"]
    settlement["support_pct"] = tally["support_pct"]
    for signature, share in tally["shares"]:
        signature["share_pct"] = share


def conditioning_party_opposes(settlement):
    for signature in round_signatures(settlement):
        if signature["position"] != "OPPOSE":
            continue
        party = db.parties.get(signature["party_id"])
        if party is not None and party["has_conditioning_authority"]:
            return True
    return False


def project_has_approved_plan(project):
    return any(
        p["project_id"] == project["id"] and p["status"] == "APPROVED"
        for p in db.study_plans.values()
    )


def approved_plans(project):
    return sorted_rows(
        db.study_plans, lambda p: p["project_id"] == project["id"] and p["status"] == "APPROVED"
    )


# ---------------------------------------------------------------------------
# obligation schedule generation (PRD 3.9)
# ---------------------------------------------------------------------------


def _new_obligation(order, obligation_type, due_date, pme_measure_id=None, dam_id=None):
    row = base_row()
    row.update(
        {
            "order_id": order["id"],
            "pme_measure_id": pme_measure_id,
            "dam_id": dam_id,
            "obligation_type": obligation_type,
            "due_date": clock.fmt_date(due_date),
            "status": "PENDING",
            "activity_window_start": None,
            "activity_window_end": None,
            "certified_at": None,
            "certified_by_user_id": None,
            "overdue_marked_at": None,
        }
    )
    db.obligations[row["id"]] = row
    return row


def generate_obligation_schedule(order, project, effective_date):
    created = []

    measures = live_measures(project)
    live_ids = {m["id"] for m in measures}
    due_by_measure = {}
    pending = list(measures)
    guard = 0
    while pending and guard <= len(measures) + 1:
        guard += 1
        progressed = []
        deferred = []
        for measure in pending:
            prereq = measure.get("prerequisite_measure_id")
            if prereq in live_ids and prereq not in due_by_measure:
                deferred.append(measure)
                continue
            progressed.append(measure)
        if not progressed:
            progressed = pending
            deferred = []
        for measure in progressed:
            own = clock.add_months(effective_date, int(measure["implementation_months"]))
            prereq = measure.get("prerequisite_measure_id")
            if prereq in due_by_measure:
                lagged = clock.add_months(due_by_measure[prereq], C.PREREQ_LAG_MONTHS)
                due = max(own, lagged)
            else:
                due = own
            due_by_measure[measure["id"]] = due
            created.append(
                _new_obligation(order, "PME_IMPLEMENTATION", due, pme_measure_id=measure["id"])
            )
        pending = deferred

    for dam in sorted_rows(db.dams, lambda d: d["project_id"] == project["id"]):
        created.append(
            _new_obligation(
                order,
                "DAM_SAFETY_INSPECTION",
                clock.add_months(effective_date, int(dam["inspection_interval_months"])),
                dam_id=dam["id"],
            )
        )
        created.append(
            _new_obligation(
                order,
                "PUBLIC_SAFETY_SIGNAGE",
                clock.add_months(effective_date, C.PUBLIC_SAFETY_SIGNAGE_MONTHS),
                dam_id=dam["id"],
            )
        )
        if dam["eap_exercise_required"]:
            created.append(
                _new_obligation(
                    order,
                    "EAP_EXERCISE",
                    clock.add_months(effective_date, C.EAP_EXERCISE_MONTHS),
                    dam_id=dam["id"],
                )
            )
    return created


def order_obligations(order):
    return sorted_rows(db.obligations, lambda o: o["order_id"] == order["id"])


def refresh_order_violations(order, flag_on_violation=False, unflag_on_zero=False):
    count = sum(1 for o in order_obligations(order) if o["status"] == "OVERDUE")
    changed = order["open_violation_count"] != count
    order["open_violation_count"] = count

    state_changed = False
    if flag_on_violation and count > 0 and order["compliance_state"] == "EFFECTIVE":
        order["compliance_state"] = "COMPLIANCE_FLAGGED"
        state_changed = True
    if unflag_on_zero and count == 0 and order["compliance_state"] == "COMPLIANCE_FLAGGED":
        order["compliance_state"] = "EFFECTIVE"
        state_changed = True

    if changed or state_changed:
        touch(order)
    return state_changed


# ---------------------------------------------------------------------------
# compliance year assessment (PRD 3.9)
# ---------------------------------------------------------------------------


def report_window(order, basis, period_year):
    if basis == "CALENDAR":
        return date(period_year, 1, 1), date(period_year, 12, 31)
    effective = clock.parse_iso_date(order["effective_date"])
    start = _clamped(period_year, effective.month, effective.day)
    end = clock.minus_one_day(clock.add_months(start, 12))
    return start, end


def _clamped(year, month, day):
    import calendar as _calendar

    return date(year, month, min(day, _calendar.monthrange(year, month)[1]))


def assess_compliance_year(order, basis, period_year):
    start, end = report_window(order, basis, period_year)
    assessed = []
    for obligation in order_obligations(order):
        if obligation["status"] == "WAIVED":
            continue
        due = clock.parse_iso_date(obligation["due_date"])
        if due is None or due < start or due > end:
            continue
        assessed.append(obligation)

    noncompliant = []
    for obligation in assessed:
        if obligation["status"] != "CERTIFIED":
            noncompliant.append(obligation)
            continue
        certified_at = obligation.get("certified_at")
        due = clock.parse_iso_date(obligation["due_date"])
        if certified_at is not None:
            certified_date = clock.parse_iso8601_datetime(certified_at).date()
            if certified_date > due:
                noncompliant.append(obligation)

    total = len(assessed)
    bad = len(noncompliant)
    if total == 0:
        score = q2(100)
    else:
        score = q2(Decimal(100) * Decimal(total - bad) / Decimal(total))
    return total, bad, score, start, end
