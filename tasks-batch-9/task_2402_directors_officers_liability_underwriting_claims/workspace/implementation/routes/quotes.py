"""Quotes, exclusion wording negotiation and binding (PRD 3.3, 3.4)."""

from flask import Blueprint

import clock
import db
from auth import RISK_MANAGER, UNDERWRITER, authenticate, require_owner
from db import store
from errors import ApiError
from money import ZERO, dec, q2
from response import list_response, object_response
from routes.common import (
    get_quote,
    get_term,
    owning_insured_id_for_quote,
    owning_insured_id_for_term,
)
from services import derive, pricing
from services.derive import SIDE_A, SIDE_B, SIDE_C
from validation import Field, paginate, parse_body, parse_pagination, validate

bp = Blueprint("quotes", __name__)

EXCLUSION_TYPES = ("CONDUCT", "PRIOR_ACTS", "INSURED_VS_INSURED", "BODILY_INJURY", "REGULATORY")
WORDING_VARIANTS = (
    "BROAD",
    "FINAL_ADJUDICATION",
    "NON_APPEALABLE_ADJUDICATION",
    "DERIVATIVE_CARVEBACK",
    "BANKRUPTCY_CARVEBACK",
    "RETRO_DATE_FULL_PRIOR_ACTS",
    "NONE",
)
TERMINAL_TERM_STATES = ("AGREED", "REJECTED", "IMPASSE")
MAX_NEGOTIATION_ROUNDS = 4
BIND_DUE_DAYS = 30

IMPACT_BOUNDS = (dec("-0.25"), dec("0.25"))

TERM_FIELDS = [
    Field("exclusion_type", "enum", enum=EXCLUSION_TYPES),
    Field("wording_variant", "enum", enum=WORDING_VARIANTS),
    Field(
        "premium_impact_pct",
        "number",
        check=lambda v: IMPACT_BOUNDS[0] <= v <= IMPACT_BOUNDS[1],
    ),
]

COUNTER_FIELDS = [
    Field("wording_variant", "enum", enum=WORDING_VARIANTS),
    Field(
        "premium_impact_pct",
        "number",
        check=lambda v: IMPACT_BOUNDS[0] <= v <= IMPACT_BOUNDS[1],
    ),
]

RESOLVE_FIELDS = [Field("resolution", "enum", enum=("AGREE", "REJECT"))]


@bp.get("/dno/quotes/<quote_id>")
def read_quote(quote_id):
    authenticate()
    return object_response(get_quote(quote_id))


@bp.post("/dno/quotes/<quote_id>/exclusion-terms")
def open_term(quote_id):
    authenticate(UNDERWRITER)
    quote = get_quote(quote_id)
    values, _ = validate(parse_body(), TERM_FIELDS)
    if quote["status"] != "OFFERED":
        raise ApiError("ERR_INVALID_QUOTE_STATE")
    record = db.insert(
        "exclusion_terms",
        {
            "quote_id": quote["id"],
            "exclusion_type": values["exclusion_type"],
            "wording_variant": values["wording_variant"],
            "premium_impact_pct": values["premium_impact_pct"],
            "proposed_by_role": "Underwriter",
            "last_actor_role": "Underwriter",
            "round_count": 1,
            "status": "PROPOSED",
            "agreed_variant": None,
        },
    )
    return object_response(record, 201)


@bp.get("/dno/quotes/<quote_id>/exclusion-terms")
def list_terms(quote_id):
    authenticate()
    quote = get_quote(quote_id)
    limit, offset = parse_pagination()
    records = derive.terms_of(quote["id"])
    return list_response(paginate(records, limit, offset), limit, offset, len(records))


@bp.post("/dno/exclusion-terms/<term_id>/counter")
def counter_term(term_id):
    user_id, role = authenticate(UNDERWRITER, RISK_MANAGER)
    term = get_term(term_id)
    require_owner(role, user_id, owning_insured_id_for_term(term))
    values, _ = validate(parse_body(), COUNTER_FIELDS)
    quote = store.quotes.get(term["quote_id"])
    if quote is None or quote["status"] != "OFFERED":
        raise ApiError("ERR_INVALID_QUOTE_STATE")
    if role == term["last_actor_role"]:
        raise ApiError("ERR_TERM_ACTOR_SEQUENCE")
    if term["status"] in TERMINAL_TERM_STATES:
        raise ApiError("ERR_INVALID_TERM_STATE")

    term["wording_variant"] = values["wording_variant"]
    term["premium_impact_pct"] = values["premium_impact_pct"]
    next_round = term["round_count"] + 1
    if next_round >= MAX_NEGOTIATION_ROUNDS:
        term["round_count"] = MAX_NEGOTIATION_ROUNDS
        term["status"] = "IMPASSE"
    else:
        term["round_count"] = next_round
        term["status"] = "COUNTERED" if term["status"] == "PROPOSED" else "PROPOSED"
    term["last_actor_role"] = role
    db.touch(term)
    return object_response(term)


@bp.post("/dno/exclusion-terms/<term_id>/resolve")
def resolve_term(term_id):
    user_id, role = authenticate(UNDERWRITER, RISK_MANAGER)
    term = get_term(term_id)
    require_owner(role, user_id, owning_insured_id_for_term(term))
    values, _ = validate(parse_body(), RESOLVE_FIELDS)
    quote = store.quotes.get(term["quote_id"])
    if quote is None or quote["status"] != "OFFERED":
        raise ApiError("ERR_INVALID_QUOTE_STATE")
    if role == term["last_actor_role"]:
        raise ApiError("ERR_TERM_ACTOR_SEQUENCE")
    if term["status"] in TERMINAL_TERM_STATES:
        raise ApiError("ERR_INVALID_TERM_STATE")

    if values["resolution"] == "AGREE":
        term["status"] = "AGREED"
        term["agreed_variant"] = term["wording_variant"]
    else:
        term["status"] = "REJECTED"
        term["agreed_variant"] = None
    db.touch(term)
    return object_response(term)


def _overlaps(a_start, a_end, b_start, b_end):
    """Half-open overlap: a starts strictly before b ends and vice versa."""
    return a_start < b_end and b_start < a_end


def _admission_total(insured, candidate_start, candidate_end):
    total = ZERO
    for policy in derive.policies_of_insured(insured["id"]):
        if policy["coverage_status"] not in derive.OPEN_COVERAGE_STATUSES:
            continue
        if not _overlaps(
            policy["period_start"], policy["period_end"], candidate_start, candidate_end
        ):
            continue
        part = derive.part_of(policy["id"], SIDE_C)
        if part is not None and part["status"] == "ACTIVE":
            total += dec(part["limit_usd"])
    return total


@bp.post("/dno/quotes/<quote_id>/accept")
def accept_quote(quote_id):
    user_id, role = authenticate(RISK_MANAGER)
    quote = get_quote(quote_id)
    require_owner(role, user_id, owning_insured_id_for_quote(quote))
    parse_body()

    if quote["status"] != "OFFERED":
        raise ApiError("ERR_INVALID_QUOTE_STATE")

    terms = derive.terms_of(quote["id"])
    conduct_agreed = any(
        t["exclusion_type"] == "CONDUCT" and t["status"] == "AGREED" for t in terms
    )
    if not conduct_agreed:
        raise ApiError("ERR_MANDATORY_EXCLUSION_MISSING")
    if any(t["status"] not in ("AGREED", "REJECTED") for t in terms):
        raise ApiError("ERR_UNRESOLVED_EXCLUSION_TERMS")

    now = clock.now()
    if now >= quote["quote_valid_until"]:
        raise ApiError("ERR_QUOTE_EXPIRED")

    submission = store.submissions.get(quote["submission_id"])
    insured = store.insureds.get(submission["insured_id"])
    if insured["control_status"] != "INDEPENDENT":
        raise ApiError("ERR_CONTROL_CHANGE_BLOCKS_BIND")

    committed = _admission_total(
        insured, submission["requested_period_start"], submission["requested_period_end"]
    )
    if committed + dec(quote["offered_side_c_sublimit_usd"]) > dec(
        insured["entity_capacity_cap_usd"]
    ):
        raise ApiError("ERR_ENTITY_CAPACITY_EXCEEDED")

    touched = derive.Touched()
    gross = pricing.bound_premium(quote["gross_premium_usd"], terms)
    limit = q2(dec(quote["offered_limit_usd"]))
    retention = q2(dec(quote["offered_retention_usd"]))
    sublimit = q2(dec(quote["offered_side_c_sublimit_usd"]))

    policy = db.insert(
        "policies",
        {
            "submission_id": submission["id"],
            "insured_id": insured["id"],
            "quote_id": quote["id"],
            "policy_number": store.next_policy_number(),
            "period_start": submission["requested_period_start"],
            "period_end": submission["requested_period_end"],
            "retroactive_date": submission["retroactive_date"],
            "erp_days": submission["erp_days"],
            "shared_aggregate_limit_usd": limit,
            "aggregate_remaining_usd": limit,
            "total_eroded_usd": q2(ZERO),
            "retention_usd": retention,
            "gross_premium_usd": gross,
            "premium_due_date": clock.plus_days(now, BIND_DUE_DAYS),
            "coverage_status": "INCEPTED",
            "premium_status": "INVOICED",
            "program_target_limit_usd": q2(dec(submission["requested_program_target_limit_usd"])),
            "placed_limit_usd": q2(ZERO),
            "tower_posture": "INCOMPLETE",
            "tower_sealed": False,
            "runoff_start_date": None,
            "runoff_end_date": None,
            "runoff_premium_usd": q2(ZERO),
            "return_premium_usd": q2(ZERO),
            "open_claim_count": 0,
            "cancelled_reason": None,
        },
    )

    for part_name, part_limit, part_retention in (
        (SIDE_A, limit, q2(ZERO)),
        (SIDE_B, limit, retention),
        (SIDE_C, sublimit, retention),
    ):
        if part_name == SIDE_C and sublimit <= 0:
            continue
        db.insert(
            "coverage_parts",
            {
                "policy_id": policy["id"],
                "part": part_name,
                "limit_usd": part_limit,
                "retention_usd": part_retention,
                "remaining_limit_usd": part_limit,
                "eroded_usd": q2(ZERO),
                "status": "ACTIVE",
            },
        )

    derive.refresh_policy_totals(policy)
    quote["status"] = "ACCEPTED"
    touched.add(quote)
    submission["status"] = "BOUND"
    touched.add(submission)
    derive.recompute_insured_capacity(insured)
    touched.add(insured)
    touched.flush()
    return object_response(policy, 201)
