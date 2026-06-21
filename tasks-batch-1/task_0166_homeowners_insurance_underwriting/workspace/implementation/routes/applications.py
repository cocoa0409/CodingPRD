"""Application routes (PRD §3.4, §3.6) — submit/quote, review, bind cascade, decline."""
from decimal import Decimal

from flask import Blueprint, g, request

from db import db
from errors import err
from middleware import require_roles
from response import success
from services.calc import (
    base_premium, wind_hail_deductible_amount, round_half_up, to_money,
)
from services.common import (
    get_json_body, require_field, as_number, as_int, as_enum,
    get_or_404, parse_pagination, paginate,
)
from services.ledger import post
from services.models import base_record, serialize, touch

bp = Blueprint("applications", __name__)

DEDUCTIBLE_PCTS = {1, 2, 5}


def _latest_risk_assessment(property_id):
    matches = [r for r in db.risk_assessments.values() if r["property_id"] == property_id]
    if not matches:
        return None
    return max(matches, key=lambda r: r["_seq"])


@bp.post("/applications")
@require_roles("Agent")
def create_application():
    body = get_json_body()
    property_id = require_field(body, "property_id")
    requested_coverage_a = as_number(require_field(body, "requested_coverage_a"), "requested_coverage_a")
    if requested_coverage_a < 0:
        raise err("ERR_INVALID_REQUEST", "requested_coverage_a must be >= 0.")
    if "wind_hail_deductible_pct" in body and body["wind_hail_deductible_pct"] is not None:
        whp = body["wind_hail_deductible_pct"]
        if isinstance(whp, bool) or not isinstance(whp, (int, float)) or int(whp) != whp or int(whp) not in DEDUCTIBLE_PCTS:
            raise err("ERR_INVALID_REQUEST", "wind_hail_deductible_pct must be one of 1, 2, 5.")
        wind_hail_deductible_pct = int(whp)
    else:
        wind_hail_deductible_pct = 2

    with db.lock:
        get_or_404("property", property_id)
        rec = base_record()
        rec.update({
            "property_id": property_id,
            "agent_id": g.user_id,
            "requested_coverage_a": requested_coverage_a,
            "wind_hail_deductible_pct": wind_hail_deductible_pct,
            "quoted_premium": Decimal("0"),
            "decline_reason": "NONE",
            "assigned_underwriter_id": None,
            "status": "DRAFT",
        })
        db.applications[rec["id"]] = rec
    return success(serialize(rec), status=201)


@bp.get("/applications")
@require_roles("Admin", "Agent", "Underwriter")
def list_applications():
    limit, offset = parse_pagination()
    property_id = request.args.get("property_id")
    agent_id = request.args.get("agent_id")
    assigned_underwriter_id = request.args.get("assigned_underwriter_id")
    with db.lock:
        items = list(db.applications.values())
        if property_id is not None:
            items = [a for a in items if a["property_id"] == property_id]
        if agent_id is not None:
            items = [a for a in items if a["agent_id"] == agent_id]
        if assigned_underwriter_id is not None:
            items = [a for a in items if a["assigned_underwriter_id"] == assigned_underwriter_id]
        window, meta = paginate(items, limit, offset)
        data = [serialize(a) for a in window]
    return success(data, status=200, list_meta=meta)


@bp.get("/applications/<rid>")
@require_roles("Admin", "Agent", "Underwriter")
def get_application(rid):
    with db.lock:
        rec = get_or_404("application", rid)
        return success(serialize(rec), status=200)


@bp.post("/applications/<rid>/submit")
@require_roles("Agent")
def submit_application(rid):
    with db.lock:
        app = get_or_404("application", rid)
        # state gate
        if app["status"] != "DRAFT":
            raise err("ERR_APPLICATION_NOT_DRAFT", "submit requires Application in DRAFT.")
        prop = db.properties[app["property_id"]]
        # business gates (in scaffold precondition order)
        if to_money(prop["replacement_cost"]) <= 0:
            raise err("ERR_REPLACEMENT_COST_MISSING", "submit requires a committed replacement_cost.")
        if to_money(app["requested_coverage_a"]) < to_money(prop["replacement_cost"]):
            raise err("ERR_COVERAGE_BELOW_REPLACEMENT_COST",
                      "requested_coverage_a must be >= Property.replacement_cost.")
        ra = _latest_risk_assessment(app["property_id"])
        if ra is None:
            raise err("ERR_RISK_ASSESSMENT_NOT_FOUND",
                      "A RiskAssessment must exist for the application's property.")
        # generate quote
        _generate_quote(app, prop, ra)
        app["status"] = "SUBMITTED"
        touch(app)
        return success(serialize(app), status=200)


def _generate_quote(app, prop, ra):
    """Generate a BOUND_OFFER quote; supersede any prior BOUND_OFFER (PRD §3.4)."""
    # supersede prior BOUND_OFFER quotes on this application
    for q in db.quotes.values():
        if q["application_id"] == app["id"] and q["status"] == "BOUND_OFFER":
            q["status"] = "SUPERSEDED"
            touch(q)

    bp_amt = base_premium(
        app["requested_coverage_a"],
        app["wind_hail_deductible_pct"],
        ra["wildfire_score"],
        ra["flood_zone"],
        ra["wind_hail_tier"],
    )
    # endorsement_premium = sum of premium_delta over PENDING endorsements (each pre-rounded)
    endt_sum = Decimal("0")
    for e in db.endorsements.values():
        if e["application_id"] == app["id"] and e["status"] == "PENDING":
            endt_sum += to_money(e["premium_delta"])
    endt_amt = round_half_up(endt_sum, 2)
    annual = round_half_up(bp_amt, 2) + round_half_up(endt_amt, 2)  # per-component then sum
    whd = wind_hail_deductible_amount(app["requested_coverage_a"], app["wind_hail_deductible_pct"])

    quote = base_record()
    quote.update({
        "application_id": app["id"],
        "base_premium": to_money(bp_amt),
        "endorsement_premium": to_money(endt_amt),
        "annual_premium": to_money(annual),
        "wind_hail_deductible_amount": to_money(whd),
        "status": "BOUND_OFFER",
    })
    db.quotes[quote["id"]] = quote
    app["quoted_premium"] = to_money(annual)
    return quote


def _latest_bound_offer_quote(application_id):
    matches = [
        q for q in db.quotes.values()
        if q["application_id"] == application_id and q["status"] == "BOUND_OFFER"
    ]
    if not matches:
        return None
    return max(matches, key=lambda q: q["_seq"])


@bp.post("/applications/<rid>/take-review")
@require_roles("Underwriter")
def take_review(rid):
    with db.lock:
        app = get_or_404("application", rid)
        if app["status"] != "SUBMITTED":
            raise err("ERR_APPLICATION_NOT_SUBMITTED", "take-review requires Application in SUBMITTED.")
        app["assigned_underwriter_id"] = g.user_id
        app["status"] = "UNDER_REVIEW"
        touch(app)
        return success(serialize(app), status=200)


@bp.post("/applications/<rid>/return-to-queue")
@require_roles("Underwriter")
def return_to_queue(rid):
    with db.lock:
        app = get_or_404("application", rid)
        if app["status"] != "UNDER_REVIEW":
            raise err("ERR_APPLICATION_NOT_UNDER_REVIEW",
                      "return-to-queue requires Application in UNDER_REVIEW.")
        if app["assigned_underwriter_id"] != g.user_id:
            raise err("ERR_NOT_ASSIGNED_UNDERWRITER",
                      "Acting underwriter is not the assigned underwriter.")
        app["assigned_underwriter_id"] = None
        app["status"] = "SUBMITTED"
        touch(app)
        return success(serialize(app), status=200)


@bp.post("/applications/<rid>/bind")
@require_roles("Underwriter")
def bind_application(rid):
    # Body is parsed up-front, but generic input-integrity (priority 13) is the
    # LOWEST gate (PRD §2.6): existence/state/business gates are evaluated first,
    # so field-format validation is deferred below them.
    body = get_json_body()

    with db.lock:
        app = get_or_404("application", rid)
        # state gate
        if app["status"] != "UNDER_REVIEW":
            raise err("ERR_APPLICATION_NOT_UNDER_REVIEW", "bind requires Application in UNDER_REVIEW.")
        # segregation of duties: acting underwriter must be the assigned one
        if app["assigned_underwriter_id"] != g.user_id:
            raise err("ERR_NOT_ASSIGNED_UNDERWRITER",
                      "Acting underwriter is not the assigned underwriter.")
        property_id = app["property_id"]
        # business-referential: a PASSED inspection for the property
        if not any(i["property_id"] == property_id and i["status"] == "PASSED"
                   for i in db.inspections.values()):
            raise err("ERR_INSPECTION_NOT_PASSED", "bind requires a PASSED Inspection for the property.")
        # risk assessment must have reached FINAL
        ra = _latest_risk_assessment(property_id)
        if ra is None or ra["score_stage"] != "FINAL":
            raise err("ERR_SCORE_NOT_FINAL", "bind requires RiskAssessment.score_stage == FINAL.")
        # wildfire insurability boundary at 80
        if int(ra["wildfire_score"]) >= 80:
            raise err("ERR_WILDFIRE_UNINSURABLE", "FINAL wildfire_score >= 80 declines the risk.")
        # underwriter authority (the acting underwriter is entity-backed per §2.1)
        underwriter = get_or_404("underwriter", g.user_id)
        if to_money(app["requested_coverage_a"]) > to_money(underwriter["authority_limit"]):
            raise err("ERR_AUTHORITY_LIMIT_EXCEEDED",
                      "requested_coverage_a exceeds the underwriter's authority_limit.")
        # generic input integrity (lowest priority) — validated after business gates
        effective_date = as_int(require_field(body, "effective_date"), "effective_date")
        expiration_date = as_int(require_field(body, "expiration_date"), "expiration_date")
        if expiration_date <= effective_date:
            raise err("ERR_INVALID_REQUEST", "expiration_date must be > effective_date.")
        expected_version = as_int(require_field(body, "expected_application_version"),
                                  "expected_application_version")
        # OCC last
        if expected_version != app["version"]:
            raise err("ERR_STALE_APPLICATION_VERSION",
                      "expected_application_version does not match the application's version.")

        # --- success: mutate application then run CASCADE A ---
        app["status"] = "BOUND"
        touch(app)  # increments Application.version by 1

        quote = _latest_bound_offer_quote(app["id"])
        annual_premium = to_money(quote["annual_premium"]) if quote else Decimal("0.00")

        policy = base_record()
        policy.update({
            "application_id": app["id"],
            "property_id": property_id,
            "effective_date": effective_date,
            "expiration_date": expiration_date,
            "annual_premium": annual_premium,
            "premium_balance": Decimal("0.00"),
            "lapse_count": 0,
            "status": "PENDING_PAYMENT",
        })
        db.policies[policy["id"]] = policy
        db.ledgers[policy["id"]] = []

        # CASCADE A step 2 & 3: PENDING endorsements -> APPLIED + ledger postings
        prop = db.properties[property_id]
        for e in db.endorsements.values():
            if e["application_id"] == app["id"] and e["status"] == "PENDING":
                e["status"] = "APPLIED"
                delta = to_money(e["premium_delta"])
                if e["kind"] == "PERIL_ADD":
                    post(policy, "DEBIT", delta, "ENDORSEMENT_APPLY")
                    prop["total_insured_value"] = to_money(
                        to_money(prop["total_insured_value"]) + to_money(e["coverage_limit"])
                    )
                    touch(prop)
                else:  # EXCLUSION
                    post(policy, "CREDIT", abs(delta), "ENDORSEMENT_APPLY")
                touch(e)

        return success(serialize(app), status=200)


@bp.post("/applications/<rid>/decline")
@require_roles("Underwriter")
def decline_application(rid):
    body = get_json_body()
    with db.lock:
        app = get_or_404("application", rid)
        if app["status"] != "UNDER_REVIEW":
            raise err("ERR_APPLICATION_NOT_UNDER_REVIEW", "decline requires Application in UNDER_REVIEW.")
        if app["assigned_underwriter_id"] != g.user_id:
            raise err("ERR_NOT_ASSIGNED_UNDERWRITER",
                      "Acting underwriter is not the assigned underwriter.")
        # input integrity (lowest priority) after state + assigned gates
        reason = as_enum(require_field(body, "reason"), "reason",
                         {"WILDFIRE_UNINSURABLE", "INSPECTION_FAILED"})
        app["status"] = "DECLINED"
        app["decline_reason"] = reason
        touch(app)
        # reject every DRAFT/PENDING endorsement on this application
        for e in db.endorsements.values():
            if e["application_id"] == app["id"] and e["status"] in ("DRAFT", "PENDING"):
                e["status"] = "REJECTED"
                touch(e)
        return success(serialize(app), status=200)
