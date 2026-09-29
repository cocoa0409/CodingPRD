"""Withdrawal events and liability assessments (§3.4 - §3.6)."""

from flask import Blueprint

import calc
import serialize
import services as svc
from clockutil import add_days, now
from db import db
from errors import fail, invalid
from listing import paged, str_filters
from response import created, obj
from validate import (ANY_ROLE, authorize, body, field_datetime, field_enum,
                      field_int, field_str)

bp = Blueprint("withdrawal", __name__)

REPORTED_CAUSES = ("CONTRIBUTION_OBLIGATION_CEASED", "COVERED_WORK_CEASED",
                   "CBA_PARTIAL_CESSATION", "FACILITY_CESSATION", "CBU_DECLINE")

COMPLETE_CAUSES = ("CONTRIBUTION_OBLIGATION_CEASED", "COVERED_WORK_CEASED")

YEAR_MIN = 1900
YEAR_MAX = 2200


# --------------------------------------------------------------------------
# WithdrawalEvent
# --------------------------------------------------------------------------

@bp.post("/withdrawal-events")
def create_event():
    ctx = authorize(("FundAdministrator", "EmployerRepresentative"))
    data = body()
    employer_id = field_str(data, "employer_id", required=True)
    cessation_date = field_datetime(data, "cessation_date", required=True)
    withdrawal_plan_year = field_int(data, "withdrawal_plan_year", required=True,
                                     minimum=YEAR_MIN, maximum=YEAR_MAX)
    if withdrawal_plan_year != cessation_date.year:
        invalid("'withdrawal_plan_year' must equal the calendar year of "
                "'cessation_date'.")
    reported_cause = field_enum(data, "reported_cause", REPORTED_CAUSES,
                                required=True)
    ceased_cba_count = field_int(data, "ceased_cba_count", default=0, minimum=0)

    employer = svc.get_employer(employer_id)
    svc.require_owner(ctx, employer)

    plan = svc.plan_of_employer(employer)
    event = svc.new_row(db.withdrawal_events, {
        "employer_id": employer["id"],
        "cessation_date": cessation_date,
        "withdrawal_plan_year": withdrawal_plan_year,
        "reported_cause": reported_cause,
        "ceased_cba_count": ceased_cba_count,
        "rules_variant": calc.rules_variant_for(plan),
        "determined_type": "NONE",
        "high_base_year_average_cbu": 0.0,
        "testing_period_average_cbu": 0.0,
        "decline_ratio": 0.0,
        "base_year_one": None,
        "base_year_two": None,
        "partial_withdrawal_fraction": 0.0,
        "status": "REPORTED",
        "determined_at": None,
    })
    return created(serialize.withdrawal_event(event))


def _classify(event, employer, variant):
    """Returns (determined_type, decline_figures_or_None); raises on tier-12 rejects."""
    cause = event["reported_cause"]
    W = event["withdrawal_plan_year"]

    if cause in COMPLETE_CAUSES:
        if variant == "GENERAL_RULES":
            return "COMPLETE", None
        performing = employer["covered_work_status"] == "PERFORMING"
        return ("COMPLETE" if performing else "NONE"), None

    if cause == "CBU_DECLINE":
        if variant != "GENERAL_RULES":
            fail("ERR_PARTIAL_WITHDRAWAL_NOT_AVAILABLE")
        figures = calc.seventy_percent_decline_test(employer, W)
        return ("PARTIAL_70_DECLINE" if figures["is_decline"] else "NONE"), figures

    if cause == "CBA_PARTIAL_CESSATION":
        if variant == "ENTERTAINMENT_RULES":
            fail("ERR_PARTIAL_WITHDRAWAL_NOT_AVAILABLE")
        ceased = event["ceased_cba_count"]
        if ceased == 0:
            fail("ERR_CBA_CESSATION_COUNT_INVALID")
        if ceased >= employer["cba_count"]:
            return "COMPLETE", None
        return "PARTIAL_CBA_CESSATION", None

    # FACILITY_CESSATION
    if variant == "CONSTRUCTION_RULES":
        fail("ERR_PARTIAL_WITHDRAWAL_NOT_AVAILABLE")
    return "PARTIAL_FACILITY_CESSATION", None


@bp.post("/withdrawal-events/<withdrawal_event_id>/determine")
def determine_event(withdrawal_event_id):
    authorize(("PlanActuary",))
    event = svc.get_event(withdrawal_event_id)
    if event["status"] != "REPORTED":
        fail("ERR_WITHDRAWAL_ALREADY_DETERMINED")

    employer = svc.employer_of_event(event)
    W = event["withdrawal_plan_year"]

    # tier 10: the preceding plan year must carry a certified valuation
    if calc.valuation_for_year(employer["plan_id"], W - 1) is None:
        fail("ERR_VALUATION_YEAR_MISSING")

    determined_type, decline = _classify(event, employer, event["rules_variant"])
    fraction = calc.partial_withdrawal_fraction(employer, event, determined_type)

    changes = {
        "determined_type": determined_type,
        "partial_withdrawal_fraction": fraction,
        "determined_at": now(),
    }
    if decline is not None:
        changes.update({
            "high_base_year_average_cbu": decline["high_base_year_average_cbu"],
            "testing_period_average_cbu": decline["testing_period_average_cbu"],
            "decline_ratio": decline["decline_ratio"],
            "base_year_one": decline["base_year_one"],
            "base_year_two": decline["base_year_two"],
        })

    employer_changes = {}
    if determined_type == "COMPLETE":
        changes["status"] = "COMPLETE_DETERMINED"
        employer_changes["status"] = "COMPLETE_WITHDRAWN"
        employer_changes["obligation_end_year"] = W
    elif determined_type == "NONE":
        changes["status"] = "NO_WITHDRAWAL"
    else:
        changes["status"] = "PARTIAL_DETERMINED"
        employer_changes["status"] = "PARTIAL_WITHDRAWN"
        if determined_type == "PARTIAL_CBA_CESSATION":
            employer_changes["ceased_cba_count"] = event["ceased_cba_count"]

    event.update(changes)
    svc.touch(event)

    employer.update(employer_changes)
    svc.touch(employer)
    svc.recompute_group_of(employer)

    return obj(serialize.withdrawal_event(event))


@bp.get("/withdrawal-events")
def list_events():
    authorize(ANY_ROLE)
    rows = str_filters(list(db.withdrawal_events.values()), {
        "employer_id": "employer_id",
        "status": "status",
    })
    return paged(rows, serialize.withdrawal_event)


@bp.get("/withdrawal-events/<withdrawal_event_id>")
def read_event(withdrawal_event_id):
    authorize(ANY_ROLE)
    return obj(serialize.withdrawal_event(svc.get_event(withdrawal_event_id)))


# --------------------------------------------------------------------------
# LiabilityAssessment
# --------------------------------------------------------------------------

@bp.post("/liability-assessments")
def create_assessment():
    authorize(("PlanActuary",))
    data = body()
    event_id = field_str(data, "withdrawal_event_id", required=True)
    event = svc.get_event(event_id)

    if event["status"] not in ("COMPLETE_DETERMINED", "PARTIAL_DETERMINED"):
        if event["status"] == "NO_WITHDRAWAL":
            fail("ERR_NO_WITHDRAWAL_DETERMINED")
        fail("ERR_WITHDRAWAL_NOT_DETERMINED")

    employer = svc.employer_of_event(event)
    plan = svc.plan_of_employer(employer)
    W = event["withdrawal_plan_year"]

    # tier 10: anchor valuation, then the whole five-year valuation window
    anchor_candidates = calc.certified_valuations(plan["id"], W - 1)
    if not anchor_candidates:
        fail("ERR_VALUATION_YEAR_MISSING")
    anchor = anchor_candidates[0]
    for year in range(W - 5, W):
        if calc.valuation_for_year(plan["id"], year) is None:
            fail("ERR_VALUATION_YEAR_MISSING")

    covered = False
    for year in range(W - 5, W):
        rec = calc._certified_record(employer["id"], year)
        if rec is not None:
            covered = True
            break
    if not covered:
        fail("ERR_EMPTY_CONTRIBUTION_WINDOW")

    method = plan["allocation_method"]
    variant = plan["de_minimis_variant"]
    gross, breakdown = calc.allocation_gross_share(plan, employer, event, anchor, method)
    de_minimis = calc.de_minimis_reduction(plan, anchor, variant, gross)
    net = calc.net_assessed(gross, de_minimis, 0)
    payment = calc.annual_payment_amount(employer, W)

    if payment["annual_payment_cents"] <= 0:
        fail("ERR_ANNUAL_PAYMENT_ZERO")

    assessment = svc.new_row(db.assessments, {
        "withdrawal_event_id": event["id"],
        "valuation_id": anchor["id"],
        "allocation_method_applied": method,
        "de_minimis_variant_applied": variant,
        "interest_rate_bps_applied": anchor["interest_rate_bps"],
        "gross_allocated_cents": gross,
        "pool_term_breakdown": breakdown,
        "de_minimis_reduction_cents": de_minimis,
        "award_adjustment_cents": 0,
        "net_assessed_cents": net,
        "high_3yr_average_cbu": payment["high_3yr_average_cbu"],
        "high_3yr_window_start_year": payment["high_3yr_window_start_year"],
        "peak_contribution_rate_cents_per_cbu":
            payment["peak_contribution_rate_cents_per_cbu"],
        "peak_rate_plan_year": payment["peak_rate_plan_year"],
        "annual_payment_cents": payment["annual_payment_cents"],
        "lifecycle_status": "DRAFT",
        "review_status": "NONE",
        "collection_status": "NOT_YET_DUE",
        "issued_at": None,
        "issued_by_user_id": None,
        "review_deadline_at": None,
        "active_schedule_generation": 0,
    })
    return created(serialize.assessment(assessment))


@bp.post("/liability-assessments/<liability_assessment_id>/issue")
def issue_assessment(liability_assessment_id):
    ctx = authorize(("PlanTrustee",))
    assessment = svc.get_assessment(liability_assessment_id)

    if assessment["lifecycle_status"] != "DRAFT":
        fail("ERR_ASSESSMENT_ALREADY_ISSUED")
    siblings = [a for a in db.assessments.values()
                if a["withdrawal_event_id"] == assessment["withdrawal_event_id"]
                and a["id"] != assessment["id"]]
    if any(a["lifecycle_status"] in ("ISSUED", "FINAL") for a in siblings):
        fail("ERR_ASSESSMENT_ALREADY_ISSUED")

    anchor = db.valuations.get(assessment["valuation_id"])
    if anchor is not None and anchor["certified_by_user_id"] == ctx.user_id:
        fail("ERR_SEGREGATION_OF_DUTIES")

    employer = svc.employer_of_assessment(assessment)
    plan = svc.plan_of_employer(employer)
    net = assessment["net_assessed_cents"]

    if net != 0:
        svc.check_amortizable(plan, net, assessment["annual_payment_cents"],
                              assessment["interest_rate_bps_applied"], 0)

    issued_at = now()
    assessment["issued_at"] = issued_at
    assessment["issued_by_user_id"] = ctx.user_id
    assessment["review_deadline_at"] = add_days(issued_at, calc.REVIEW_WINDOW_DAYS)

    event = db.withdrawal_events.get(assessment["withdrawal_event_id"])

    if net == 0:
        # degenerate case: nothing to amortise, so no generation is minted
        assessment["lifecycle_status"] = "FINAL"
        assessment["collection_status"] = "SATISFIED"
        assessment["active_schedule_generation"] = 0
        svc.touch(assessment)
    else:
        assessment["lifecycle_status"] = "ISSUED"
        svc.touch(assessment)
        schedule = svc.mint_generation(
            assessment, "ISSUANCE", 1,
            assessment["interest_rate_bps_applied"], 0)
        svc.apply_changes(assessment, {
            "collection_status": svc.projected_collection_status(assessment),
            "active_schedule_generation": schedule["generation_seq"],
        })
        svc.recompute_employer(employer)

    if event is not None:
        svc.apply_changes(event, {"status": "ASSESSED"})
    for sibling in siblings:
        if sibling["lifecycle_status"] == "DRAFT":
            svc.apply_changes(sibling, {"lifecycle_status": "RESCINDED"})

    if anchor is not None:
        allocated, unallocated = serialize.valuation_allocation(anchor)
        anchor["allocated_uvb_cents"] = allocated
        anchor["unallocated_uvb_cents"] = unallocated
        svc.touch(anchor)
    if plan is not None:
        employer_count, issued_count = serialize.plan_counters(plan)
        plan["employer_count"] = employer_count
        plan["issued_assessment_count"] = issued_count
        svc.touch(plan)

    return obj(serialize.assessment(assessment))


@bp.get("/liability-assessments")
def list_assessments():
    authorize(ANY_ROLE)
    rows = str_filters(list(db.assessments.values()), {
        "withdrawal_event_id": "withdrawal_event_id",
        "valuation_id": "valuation_id",
        "lifecycle_status": "lifecycle_status",
        "review_status": "review_status",
        "collection_status": "collection_status",
    })
    return paged(rows, serialize.assessment)


@bp.get("/liability-assessments/<liability_assessment_id>")
def read_assessment(liability_assessment_id):
    authorize(ANY_ROLE)
    return obj(serialize.assessment(svc.get_assessment(liability_assessment_id)))
