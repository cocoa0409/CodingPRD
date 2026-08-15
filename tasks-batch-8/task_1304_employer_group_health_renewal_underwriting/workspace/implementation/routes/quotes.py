"""Quote endpoints (PRD 3.5, 3.6)."""
from flask import Blueprint

from db import store, new_record
from errors import (
    ApiError, not_found, invalid_request,
    ERR_STALE_VERSION, ERR_CASE_NOT_IN_RATING, ERR_CASE_NOT_QUOTABLE,
    ERR_CASE_NOT_NEGOTIATING, ERR_NO_MODELED_PLAN,
    ERR_GROUP_TOO_SMALL_LEVEL_FUNDED, ERR_QUOTE_NOT_DRAFT,
    ERR_QUOTE_NOT_PROPOSED, ERR_QUOTE_NOT_COUNTERED,
    ERR_BROKER_NOT_ACTIVE, ERR_NOT_BROKER_OF_RECORD,
)
from middleware import auth
from response import ok, created, paginated, sorted_items
from serializers import quote_json
from services import workflow
from validators import (
    body, req_str, req_int, req_num, req_enum, opt_int,
)

bp = Blueprint("quotes", __name__)

READ_ROLES = ["Underwriter", "SeniorUnderwriter", "Broker", "ComplianceOfficer"]
QUOTE_FUNDING_TYPES = ["FULLY_INSURED", "LEVEL_FUNDED"]
GUARANTEE_MONTHS = (12, 18, 24)
# Case postures in which a quote may be created (PRD 3.5; the OCC rule exists
# precisely because later quotes are created after the first advanced the case)
QUOTABLE_CREATE_STATES = ["RATING_IN_PROGRESS", "QUOTED", "NEGOTIATING"]


def get_quote_or_404(quote_id):
    quote = store.quotes.get(quote_id)
    if quote is None:
        raise not_found("Quote does not exist")
    return quote


def _check_broker_active_and_of_record(case, uid):
    broker = store.brokers.get(uid)
    if broker is None or broker["status"] != "ACTIVE":
        raise ApiError(ERR_BROKER_NOT_ACTIVE, "Broker must be in ACTIVE status", 409)
    if case["broker_id"] != uid:
        raise ApiError(ERR_NOT_BROKER_OF_RECORD,
                       "Acting broker is not the broker of record on this case", 403)


def _negotiation_body():
    data = body()
    pepm = req_int(data, "proposed_pepm_cents")
    contrib = req_num(data, "proposed_contribution_pct")
    justification = req_str(data, "justification")
    if len(justification) < 20:
        raise invalid_request("justification must be at least 20 characters")
    deductible = opt_int(data, "proposed_deductible_individual")
    return pepm, contrib, deductible, justification


@bp.post("/underwriting-cases/<caseId>/quotes")
def create_quote(caseId):
    auth(["Underwriter"])
    case = store.cases.get(caseId)
    if case is None:
        raise not_found("Underwriting case does not exist")
    data = body()
    plan_design_id = req_str(data, "plan_design_id")
    funding_type = req_enum(data, "funding_type", QUOTE_FUNDING_TYPES)
    rate_guarantee_months = req_int(data, "rate_guarantee_months")
    if rate_guarantee_months not in GUARANTEE_MONTHS:
        raise invalid_request("rate_guarantee_months must be one of 12, 18, 24")
    enrollment_change_threshold = req_num(data, "enrollment_change_threshold")
    expected_case_version = req_int(data, "expected_case_version")

    plan = store.plans.get(plan_design_id)
    if plan is None or plan["case_id"] != caseId:
        raise not_found("Plan design does not exist")

    # OCC check: immediately after existence, strictly before business rules
    # (PRD 2.5, 2.6).
    if expected_case_version != case["version"]:
        raise ApiError(ERR_STALE_VERSION,
                       "expected_case_version does not match current "
                       "UnderwritingCase.version", 412)

    if case["status"] not in QUOTABLE_CREATE_STATES:
        raise ApiError(ERR_CASE_NOT_IN_RATING,
                       "Case must be in RATING_IN_PROGRESS to create a quote", 409)

    modeled = [p for p in store.plans.values()
               if p["case_id"] == caseId and p["status"] == "MODELED"]
    if not modeled or plan["status"] != "MODELED":
        raise ApiError(ERR_NO_MODELED_PLAN,
                       "At least one MODELED plan design is required to create a quote", 409)

    if funding_type == "LEVEL_FUNDED" and case["group_size"] < 10:
        raise ApiError(ERR_GROUP_TOO_SMALL_LEVEL_FUNDED,
                       "Group size must be >= 10 for level-funded quotes", 409)

    rec = new_record()
    rec.update({
        "case_id": caseId,
        "plan_design_id": plan_design_id,
        "quote_number": len([q for q in store.quotes.values()
                             if q["case_id"] == caseId]) + 1,
        "funding_type": funding_type,
        "pepm_rate_cents": 0,
        "annual_premium_cents": 0,
        "renewal_increase_pct": 0,
        "claims_fund_cents": 0,
        "admin_fee_cents": 0,
        "stop_loss_premium_cents": 0,
        "broker_commission_cents": 0,
        "commission_disclosure_required": False,
        "rate_guarantee_months": rate_guarantee_months,
        "enrollment_change_threshold": enrollment_change_threshold,
        "status": "DRAFT",
        "negotiation_round": 0,
        "parent_quote_id": None,
    })
    store.quotes[rec["id"]] = rec
    # Creating a quote mutates the parent case: version increments by one
    from db import touch
    touch(case)
    return created(quote_json(rec))


@bp.get("/underwriting-cases/<caseId>/quotes")
def list_quotes(caseId):
    auth(READ_ROLES)
    if caseId not in store.cases:
        raise not_found("Underwriting case does not exist")
    items = [q for q in store.quotes.values() if q["case_id"] == caseId]
    return paginated([quote_json(q) for q in sorted_items(items)])


@bp.get("/quotes/<quoteId>")
def get_quote(quoteId):
    auth(READ_ROLES)
    return ok(quote_json(get_quote_or_404(quoteId)))


@bp.post("/quotes/<quoteId>/propose")
def propose_quote(quoteId):
    auth(["Underwriter"])
    quote = get_quote_or_404(quoteId)
    case = store.cases[quote["case_id"]]
    if case["status"] not in ("RATING_IN_PROGRESS", "QUOTED", "NEGOTIATING"):
        raise ApiError(ERR_CASE_NOT_QUOTABLE,
                       "Case must be in RATING_IN_PROGRESS, QUOTED, or "
                       "NEGOTIATING to propose", 409)
    if quote["status"] != "DRAFT":
        raise ApiError(ERR_QUOTE_NOT_DRAFT, "Quote must be in DRAFT to propose", 409)
    workflow.propose_quote(quote)
    return ok(quote_json(quote))


@bp.post("/quotes/<quoteId>/counter")
def counter_quote(quoteId):
    uid, _ = auth(["Broker"])
    quote = get_quote_or_404(quoteId)
    case = store.cases[quote["case_id"]]
    if quote["status"] != "PROPOSED":
        raise ApiError(ERR_QUOTE_NOT_PROPOSED, "Quote must be in PROPOSED status", 409)
    _check_broker_active_and_of_record(case, uid)
    pepm, contrib, deductible, justification = _negotiation_body()
    workflow.counter_quote(quote, pepm, contrib, deductible, justification)
    return ok(quote_json(quote))


@bp.post("/quotes/<quoteId>/respond")
def respond_quote(quoteId):
    auth(["Underwriter"])
    quote = get_quote_or_404(quoteId)
    # PRD 3.6: requires the quote to be COUNTERED and the case NEGOTIATING.
    if quote["status"] != "COUNTERED":
        raise ApiError(ERR_QUOTE_NOT_COUNTERED,
                       "Quote must be in COUNTERED status for underwriter response", 409)
    case = store.cases[quote["case_id"]]
    if case["status"] != "NEGOTIATING":
        raise ApiError(ERR_CASE_NOT_NEGOTIATING,
                       "Case must be in NEGOTIATING for underwriter counter-response", 409)
    pepm, contrib, deductible, justification = _negotiation_body()
    workflow.respond_quote(quote, pepm, contrib, deductible, justification)
    return ok(quote_json(quote))


@bp.post("/quotes/<quoteId>/accept")
def accept_quote(quoteId):
    uid, _ = auth(["Broker"])
    quote = get_quote_or_404(quoteId)
    case = store.cases[quote["case_id"]]
    if quote["status"] != "PROPOSED":
        raise ApiError(ERR_QUOTE_NOT_PROPOSED, "Quote must be in PROPOSED status", 409)
    _check_broker_active_and_of_record(case, uid)
    workflow.accept_quote(quote)
    return ok(quote_json(quote))


@bp.post("/quotes/<quoteId>/reject-quote")
def reject_quote(quoteId):
    uid, role = auth(["Broker", "Underwriter"])
    quote = get_quote_or_404(quoteId)
    if quote["status"] not in ("PROPOSED", "COUNTERED"):
        raise ApiError(ERR_QUOTE_NOT_PROPOSED, "Quote must be in PROPOSED status", 409)
    if role == "Broker":
        case = store.cases[quote["case_id"]]
        if case["broker_id"] != uid:
            raise ApiError(ERR_NOT_BROKER_OF_RECORD,
                           "Acting broker is not the broker of record on this case", 403)
    workflow.reject_quote(quote)
    return ok(quote_json(quote))
