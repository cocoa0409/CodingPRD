"""Shared cascade / side-effect helpers, the funding waterfall and the sweep."""

from datetime import timedelta
from decimal import Decimal

from db import base_row, db, touch
from errors import ApiError
from services import calc, lookup

# lapse_reason / waiver_reason / withdrawal_reason constants named by the PRD
LAPSE_SOURCE_FULLY_OBLIGATED = "SOURCE_FULLY_OBLIGATED"
LAPSE_SOURCE_SUSPENDED = "SOURCE_SUSPENDED"
LAPSE_SOURCE_EXPIRED = "SOURCE_EXPIRED"
LAPSE_APPLICATION_LAPSED = "APPLICATION_LAPSED"
LAPSE_APPLICATION_WITHDRAWN = "APPLICATION_WITHDRAWN"
LAPSE_CLOSING_CANCELLED = "CLOSING_CANCELLED"
LAPSE_PLAN_SUPERSEDED = "PLAN_SUPERSEDED"
RESCISSION_SUPERSEDED = "SUPERSEDED_BY_NEWER_DRAFT"
SUSPENDED_VIOLATION_OPEN = "VIOLATION_OPEN"

STEWARDSHIP_RANK = {
    "MONITORING_CURRENT": 0,
    "MONITORING_DUE": 1,
    "MONITORING_DELINQUENT": 2,
}


# ---------------------------------------------------------------- negotiation
def append_negotiation_round(app, kind, round_index, amount_cents, actor_role,
                             actor_user_id, offer_expires_on=None, rationale=None):
    row = base_row(with_version=False)
    row.update(
        {
            "application_id": app["id"],
            "round_index": round_index,
            "kind": kind,
            "amount_cents": amount_cents,
            "offer_expires_on": offer_expires_on,
            "actor_role": actor_role,
            "actor_user_id": actor_user_id,
            "rationale": rationale,
        }
    )
    db.negotiation_rounds[row["id"]] = row
    return row


def rewrite_cost_build_up(app, amount_cents):
    donation, bsp, fee, total = calc.cost_build_up(amount_cents, app["donation_pct"] or Decimal(0))
    app["donation_cents"] = donation
    app["bargain_sale_price_cents"] = bsp
    app["admin_fee_cents"] = fee
    app["total_program_cost_cents"] = total
    if app["structure"] == "INSTALLMENT" and app["installment_years"]:
        first, final, interest = calc.installment_split(total, app["installment_years"])
        app["first_installment_cents"] = first
        app["final_installment_cents"] = final
        app["installment_interest_total_cents"] = interest
    else:
        app["first_installment_cents"] = None
        app["final_installment_cents"] = None
        app["installment_interest_total_cents"] = None


# ------------------------------------------------------------------- parcels
def parcel_release(app):
    parcel = db.parcels.get(app["parcel_id"])
    if parcel is not None and parcel["status"] == "UNDER_APPLICATION":
        parcel["status"] = "ELIGIBLE"
        touch(parcel)


# -------------------------------------------------------- funding cascades
def refresh_source(source):
    """Recompute the derived ledger (derived on read) and bump the row."""
    touch(source)
    apply_threshold_flip(source)


def apply_threshold_flip(source):
    threshold = lookup.source_fully_obligated_threshold(source)
    committed = lookup.source_committed_cents(source["id"])
    if source["status"] == "ACTIVE" and committed >= threshold:
        source["status"] = "FULLY_OBLIGATED"
        touch(source)
        lapse_reserved_on_source(source, LAPSE_SOURCE_FULLY_OBLIGATED)
    elif source["status"] == "FULLY_OBLIGATED" and committed < threshold:
        source["status"] = "ACTIVE"
        touch(source)


def lapse_reserved_on_source(source, reason, skip_application_id=None):
    for commitment in lookup.commitments_of_source(source["id"]):
        if commitment["status"] != "RESERVED":
            continue
        if skip_application_id and commitment["application_id"] == skip_application_id:
            continue
        commitment["status"] = "LAPSED"
        commitment["lapse_reason"] = reason
        touch(commitment)
        other = db.applications.get(commitment["application_id"])
        if other is not None and other["funding_plan_status"] == "FUNDED":
            other["funding_plan_status"] = "UNDERFUNDED"
            touch(other)


def release_application_commitments(app, statuses, reason):
    sources = []
    for commitment in lookup.commitments_of_application(app["id"]):
        if commitment["status"] not in statuses:
            continue
        commitment["status"] = "RELEASED"
        commitment["lapse_reason"] = reason
        touch(commitment)
        source = db.funding_sources.get(commitment["funding_source_id"])
        if source is not None and source not in sources:
            sources.append(source)
    for source in sources:
        refresh_source(source)
    if app["funding_plan_status"] in ("FUNDED", "UNDERFUNDED", "OBLIGATED"):
        app["funding_plan_status"] = "RELEASED"
    return sources


# ---------------------------------------------------------- closing statuses
def create_closing_requirements(app):
    parcel = db.parcels.get(app["parcel_id"])
    types = ["TITLE_COMMITMENT", "BOUNDARY_SURVEY"]
    lienholder = parcel.get("mortgage_lienholder_name") if parcel else None
    if lienholder:
        types.append("MORTGAGE_SUBORDINATION")
    for requirement_type in types:
        row = base_row()
        row.update(
            {
                "application_id": app["id"],
                "requirement_type": requirement_type,
                "status": "OUTSTANDING",
                "lienholder_name": lienholder if requirement_type == "MORTGAGE_SUBORDINATION" else None,
                "exception_count": 0,
                "surveyed_acres": None,
                "submitted_by_user_id": None,
                "reviewed_by_user_id": None,
                "deficiency_note": None,
                "waiver_reason": None,
            }
        )
        db.closing_requirements[row["id"]] = row


def bubble_closing_status(app):
    """The closing dimension is a pure function of the requirement children
    plus the funding dimension (PRD 3.7)."""
    current = app["closing_status"]
    if current not in ("PENDING_REQUIREMENTS", "BLOCKED", "CLEARED"):
        return
    requirements = lookup.requirements_of(app["id"])
    total = len(requirements)
    satisfied = sum(1 for r in requirements if r["status"] in ("SATISFIED", "WAIVED"))
    has_deficient = any(r["status"] == "DEFICIENT" for r in requirements)
    if has_deficient:
        target = "BLOCKED"
    elif total > 0 and satisfied == total and app["funding_plan_status"] == "OBLIGATED":
        target = "CLEARED"
    else:
        target = "PENDING_REQUIREMENTS"
    if target != current:
        app["closing_status"] = target
        touch(app)


# --------------------------------------------------------------- stewardship
def project_stewardship(easement, program):
    """calculations.stewardship_due_projection."""
    anchor = easement["last_monitored_on"] or easement["recorded_on"]
    due = anchor + timedelta(days=int(program["monitoring_interval_days"]))
    easement["next_monitoring_due_on"] = due
    grace_end = due + timedelta(days=int(program["monitoring_grace_days"]))
    now = db.clock
    if now < due:
        return "MONITORING_CURRENT"
    if now < grace_end:
        return "MONITORING_DUE"
    return "MONITORING_DELINQUENT"


def open_violation(easement, violation_type, excess_sqft, monitoring_visit_id):
    severity = calc.violation_severity(excess_sqft)
    opened_on = db.clock
    deadline = opened_on + timedelta(days=calc.cure_window_days(severity))
    row = base_row()
    row.update(
        {
            "easement_id": easement["id"],
            "monitoring_visit_id": monitoring_visit_id,
            "violation_type": violation_type,
            "excess_sqft": int(excess_sqft),
            "severity": severity,
            "opened_on": opened_on,
            "cure_deadline_on": deadline,
            "status": "OPEN",
            "cure_plan_note": None,
            "cured_on": None,
            "escalated_on": None,
        }
    )
    db.violations[row["id"]] = row
    # COMPLIANT -> VIOLATION_OPEN (PRD 3.8); a re-offence on a cured easement
    # re-opens, while an already escalated posture is never regressed.
    if easement["compliance_status"] != "VIOLATION_ESCALATED":
        easement["compliance_status"] = "VIOLATION_OPEN"
    easement["stewardship_hold"] = True
    touch(easement)
    for amendment in lookup.amendments_of(easement["id"]):
        if amendment["status"] == "UNDER_REVIEW":
            amendment["status"] = "SUSPENDED"
            amendment["suspended_reason"] = SUSPENDED_VIOLATION_OPEN
            touch(amendment)
    return row


def restore_impervious_allowance(easement, program):
    easement["impervious_allowance_sqft"] = calc.impervious_allowance_sqft(
        easement["protected_acres"], program["impervious_allowance_pct"]
    )


def terminate_easement(easement):
    easement["status"] = "TERMINATED"
    touch(easement)
    parcel = db.parcels.get(easement["parcel_id"])
    if parcel is not None and parcel["status"] == "ENCUMBERED":
        parcel["status"] = "ELIGIBLE"
        touch(parcel)
    program = lookup.program_of_easement(easement)
    touch(program)


# ------------------------------------------------------------------ waterfall
def run_waterfall(app, program, target_closing_date):
    """calculations.funding_waterfall_allocation. Raises on any failed test and
    writes nothing."""
    target = int(app["total_program_cost_cents"])
    eligible = [
        s
        for s in db.funding_sources.values()
        if s["program_id"] == program["id"]
        and s["status"] == "ACTIVE"
        and s["obligation_window_start"] <= target_closing_date <= s["obligation_window_end"]
    ]
    eligible.sort(key=lambda s: (s["priority_order"], s["created_at"], s["_seq"]))

    remaining = target
    takes = []
    position = 0
    for source in eligible:
        position += 1
        cap = calc.floor_int(Decimal(target) * source["max_share_pct"])
        available = lookup.source_available_cents(source)
        take = min(remaining, cap, available)
        if take <= 0:
            continue
        takes.append(
            {
                "source": source,
                "amount": take,
                "sweep_order": position,
                "absorbed": 0,
            }
        )
        remaining -= take

    if remaining > 0 and takes:
        last = takes[-1]
        headroom = lookup.source_available_cents(last["source"]) - last["amount"]
        extra = min(remaining, headroom)
        if extra > 0:
            last["amount"] += extra
            last["absorbed"] = extra
            remaining -= extra

    if remaining > 0:
        raise ApiError(
            "ERR_FUNDING_SHORTFALL",
            "eligible sources cannot cover total_program_cost_cents",
        )

    federal_total = sum(t["amount"] for t in takes if t["source"]["level"] == "FEDERAL")
    local_total = sum(t["amount"] for t in takes if t["source"]["level"] == "LOCAL")
    state_total = sum(t["amount"] for t in takes if t["source"]["level"] == "STATE")
    nonfederal_total = target - federal_total

    federal_cap = calc.floor_int(Decimal(target) * program["federal_max_share_pct"])
    if federal_total > federal_cap:
        raise ApiError(
            "ERR_FEDERAL_SHARE_EXCEEDED",
            "federal share exceeds the program ceiling",
        )
    local_floor = calc.ceil_int(Decimal(target) * program["local_match_min_pct"])
    if local_total < local_floor:
        raise ApiError(
            "ERR_LOCAL_MATCH_SHORTFALL", "local match falls below the program floor"
        )
    for source in eligible:
        if not source["requires_match"]:
            continue
        needed = calc.round_half_up_int(Decimal(federal_total) * source["match_ratio"])
        if nonfederal_total < needed:
            raise ApiError(
                "ERR_MATCH_RATIO_UNSATISFIED",
                "non-federal money does not satisfy the source match ratio",
            )
    for take in takes:
        if take["amount"] > lookup.source_available_cents(take["source"]):
            raise ApiError(
                "ERR_SOURCE_WINDOW_CAPACITY_EXCEEDED",
                "a source would be committed beyond its available capacity",
            )
    return takes, federal_total, local_total, state_total


def materialise_commitments(app, takes):
    commitments = []
    for take in takes:
        source = take["source"]
        row = base_row()
        row.update(
            {
                "application_id": app["id"],
                "funding_source_id": source["id"],
                "amount_cents": take["amount"],
                "sweep_order": take["sweep_order"],
                "absorbed_remainder_cents": take["absorbed"],
                "window_start": source["obligation_window_start"],
                "window_end": source["obligation_window_end"],
                "status": "RESERVED",
                "lapse_reason": None,
            }
        )
        db.funding_commitments[row["id"]] = row
        commitments.append(row)
        touch(source)
    return commitments


# ----------------------------------------------------------------- the sweep
def run_stewardship_sweep():
    now = db.clock
    counters = {
        "swept_easement_count": 0,
        "due_count": 0,
        "delinquent_count": 0,
        "cleared_to_compliant_count": 0,
        "terminated_easement_count": 0,
        "lapsed_offer_count": 0,
        "escalated_violation_count": 0,
        "expired_source_count": 0,
        "closed_round_count": 0,
    }

    # 1. expired offers lapse
    for app in sorted(db.applications.values(), key=lambda r: (r["created_at"], r["_seq"])):
        if app["status"] != "OFFER_ISSUED":
            continue
        if app["current_offer_expires_on"] is None or now <= app["current_offer_expires_on"]:
            continue
        append_negotiation_round(
            app,
            "EXPIRATION",
            max(1, lookup.application_negotiation_round_count(app["id"])),
            None,
            None,
            None,
        )
        app["status"] = "LAPSED"
        release_application_commitments(app, ("RESERVED",), LAPSE_APPLICATION_LAPSED)
        parcel_release(app)
        touch(app)
        counters["lapsed_offer_count"] += 1

    # 2. funding sources past their obligation window expire
    for source in sorted(db.funding_sources.values(), key=lambda r: (r["created_at"], r["_seq"])):
        if source["status"] not in ("ACTIVE", "FULLY_OBLIGATED"):
            continue
        if now <= source["obligation_window_end"]:
            continue
        source["status"] = "EXPIRED"
        touch(source)
        lapse_reserved_on_source(source, LAPSE_SOURCE_EXPIRED)
        counters["expired_source_count"] += 1

    # 3. violations past their cure deadline escalate
    for violation in sorted(db.violations.values(), key=lambda r: (r["created_at"], r["_seq"])):
        if violation["status"] not in ("OPEN", "CURE_PLAN_ACCEPTED"):
            continue
        if now <= violation["cure_deadline_on"]:
            continue
        violation["status"] = "ESCALATED"
        violation["escalated_on"] = now
        touch(violation)
        easement = db.easements.get(violation["easement_id"])
        if easement is not None and easement["compliance_status"] == "VIOLATION_OPEN":
            easement["compliance_status"] = "VIOLATION_ESCALATED"
            touch(easement)
        counters["escalated_violation_count"] += 1

    # 4. stewardship re-projection, compliance clearing and termination
    for easement in sorted(db.easements.values(), key=lambda r: (r["created_at"], r["_seq"])):
        if easement["status"] not in ("RECORDED", "AMENDED"):
            continue
        counters["swept_easement_count"] += 1
        program = lookup.program_of_easement(easement)
        projected = project_stewardship(easement, program)
        previous = easement["stewardship_status"]
        if STEWARDSHIP_RANK[projected] > STEWARDSHIP_RANK[previous]:
            easement["stewardship_status"] = projected
            touch(easement)
            if projected == "MONITORING_DUE":
                counters["due_count"] += 1
            elif projected == "MONITORING_DELINQUENT":
                counters["delinquent_count"] += 1

        if easement["compliance_status"] == "VIOLATION_CURED":
            if lookup.easement_open_violation_count(easement["id"]) == 0:
                cured = [
                    v["cured_on"]
                    for v in lookup.violations_of(easement["id"])
                    if v["status"] == "CURED" and v["cured_on"] is not None
                ]
                if cured and now >= max(cured) + timedelta(days=calc.COMPLIANCE_CLEAR_DAYS):
                    easement["compliance_status"] = "COMPLIANT"
                    touch(easement)
                    counters["cleared_to_compliant_count"] += 1

        if easement["compliance_status"] == "VIOLATION_ESCALATED":
            escalated = [
                v["escalated_on"]
                for v in lookup.violations_of(easement["id"])
                if v["status"] == "ESCALATED" and v["escalated_on"] is not None
            ]
            if escalated and now >= min(escalated) + timedelta(
                days=calc.ESCALATION_TERMINATION_DAYS
            ):
                terminate_easement(easement)
                counters["terminated_easement_count"] += 1

    # 5. selected rounds whose applications are all terminal close
    for rnd in sorted(db.rounds.values(), key=lambda r: (r["created_at"], r["_seq"])):
        if rnd["status"] != "SELECTED":
            continue
        outstanding = [
            a
            for a in lookup.applications_of_round(rnd["id"])
            if a["status"] not in lookup.TERMINAL_APPLICATION_STATUSES
        ]
        if outstanding:
            continue
        rnd["status"] = "CLOSED"
        touch(rnd)
        counters["closed_round_count"] += 1

    return counters
