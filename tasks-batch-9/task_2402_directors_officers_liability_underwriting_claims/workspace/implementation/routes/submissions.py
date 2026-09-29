"""Submissions, the scoring run and quote issuance (PRD 3.2, 3.3)."""

from flask import Blueprint, request

import clock
import db
from auth import UNDERWRITER, authenticate
from db import store
from errors import ApiError
from money import ZERO, dec, q2
from response import list_response, object_response
from routes.common import get_submission, insured_of_submission
from services import derive, pricing, scoring
from validation import Field, paginate, parse_body, parse_pagination, validate

bp = Blueprint("submissions", __name__)

SUBMISSION_FIELDS = [
    Field("insured_id", "string"),
    Field("requested_limit_usd", "money", check=lambda v: v > 0),
    Field("requested_retention_usd", "money", check=lambda v: v >= 0),
    Field("requested_side_c_sublimit_usd", "money", check=lambda v: v >= 0),
    Field("requested_program_target_limit_usd", "money"),
    Field("requested_period_start", "datetime"),
    Field("requested_period_end", "datetime"),
    Field("retroactive_date", "datetime"),
    Field("erp_days", "integer", required=False, default=90, check=lambda v: v >= 0),
]

SCORE_FIELDS = [Field("variant", "enum", enum=("INDICATIVE", "UNDERWRITTEN"))]

QUOTE_FIELDS = [
    Field("expected_submission_version", "integer"),
    Field("offered_limit_usd", "money", check=lambda v: v > 0),
    Field("offered_retention_usd", "money", check=lambda v: v >= 0),
    Field("offered_side_c_sublimit_usd", "money", check=lambda v: v >= 0),
    Field("quote_valid_until", "datetime"),
]

SUBMISSION_TTL_DAYS = 90


@bp.post("/dno/submissions")
def create_submission():
    authenticate(UNDERWRITER)
    values, _ = validate(parse_body(), SUBMISSION_FIELDS)
    insured = store.insureds.get(values["insured_id"])
    if insured is None:
        raise ApiError("ERR_SUBMISSION_NOT_FOUND")
    if values["requested_period_end"] <= values["requested_period_start"]:
        raise ApiError("ERR_PERIOD_INVALID")
    if values["requested_program_target_limit_usd"] < values["requested_limit_usd"]:
        raise ApiError("ERR_PROGRAM_TARGET_BELOW_LIMIT")
    erp_days = values["erp_days"]
    record = db.insert(
        "submissions",
        {
            "insured_id": insured["id"],
            "requested_limit_usd": values["requested_limit_usd"],
            "requested_retention_usd": values["requested_retention_usd"],
            "requested_side_c_sublimit_usd": values["requested_side_c_sublimit_usd"],
            "requested_program_target_limit_usd": values["requested_program_target_limit_usd"],
            "requested_period_start": values["requested_period_start"],
            "requested_period_end": values["requested_period_end"],
            "retroactive_date": values["retroactive_date"],
            "erp_days": 90 if erp_days is None else erp_days,
            "status": "DRAFT",
            "risk_score": None,
            "risk_band": None,
            "score_variant": None,
            "scored_at": None,
            "disclosure_packages_considered": 0,
            "litigation_units": q2(ZERO),
            "expires_at": None,
        },
    )
    record["expires_at"] = clock.plus_days(record["created_at"], SUBMISSION_TTL_DAYS)
    return object_response(record, 201)


@bp.get("/dno/submissions/<submission_id>")
def read_submission(submission_id):
    authenticate()
    return object_response(get_submission(submission_id))


@bp.get("/dno/submissions")
def list_submissions():
    authenticate()
    limit, offset = parse_pagination()
    records = db.ordered(list(store.submissions.values()))
    insured_id = request.args.get("insured_id")
    status = request.args.get("status")
    if insured_id is not None:
        records = [r for r in records if r["insured_id"] == insured_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    return list_response(paginate(records, limit, offset), limit, offset, len(records))


@bp.post("/dno/submissions/<submission_id>/score")
def score_submission(submission_id):
    authenticate(UNDERWRITER)
    submission = get_submission(submission_id)
    values, _ = validate(parse_body(), SCORE_FIELDS)
    if submission["status"] not in ("DRAFT", "SCORED"):
        raise ApiError("ERR_INVALID_SUBMISSION_STATE")
    insured = insured_of_submission(submission)
    touched = derive.Touched()
    scoring.run(submission, insured, values["variant"], touched)
    touched.flush()
    return object_response(submission)


@bp.post("/dno/submissions/<submission_id>/quotes")
def issue_quote(submission_id):
    authenticate(UNDERWRITER)
    submission = get_submission(submission_id)
    values, _ = validate(parse_body(), QUOTE_FIELDS)
    if values["expected_submission_version"] != submission["version"]:
        raise ApiError("ERR_STALE_VERSION")
    if submission["status"] != "SCORED":
        raise ApiError("ERR_INVALID_SUBMISSION_STATE")
    if values["offered_side_c_sublimit_usd"] > values["offered_limit_usd"]:
        raise ApiError("ERR_SIDE_C_SUBLIMIT_EXCEEDS_AGGREGATE")

    insured = insured_of_submission(submission)
    touched = derive.Touched()
    for sibling in derive.quotes_of(submission["id"]):
        if sibling["status"] == "OFFERED":
            sibling["status"] = "SUPERSEDED"
            touched.add(sibling)

    risk_band = submission["risk_band"]
    net = pricing.net_premium(
        values["offered_limit_usd"],
        values["offered_retention_usd"],
        values["offered_side_c_sublimit_usd"],
        risk_band,
        insured["exchange_listing"],
    )
    build_up = pricing.grossup(net)
    quote = db.insert(
        "quotes",
        {
            "submission_id": submission["id"],
            "offered_limit_usd": values["offered_limit_usd"],
            "offered_retention_usd": values["offered_retention_usd"],
            "offered_side_c_sublimit_usd": values["offered_side_c_sublimit_usd"],
            "quote_valid_until": values["quote_valid_until"],
            "risk_band_at_quote": risk_band,
            "net_premium_usd": net,
            "gross_premium_usd": build_up["gross_premium_usd"],
            "broker_commission_usd": build_up["broker_commission_usd"],
            "premium_tax_usd": build_up["premium_tax_usd"],
            "total_payable_usd": build_up["total_payable_usd"],
            "status": "OFFERED",
            "issued_by_user_id": request.headers.get("X-User-ID"),
        },
    )
    db.insert(
        "exclusion_terms",
        {
            "quote_id": quote["id"],
            "exclusion_type": "CONDUCT",
            "wording_variant": "BROAD",
            "premium_impact_pct": dec("0.00"),
            "proposed_by_role": "Underwriter",
            "last_actor_role": "Underwriter",
            "round_count": 1,
            "status": "PROPOSED",
            "agreed_variant": None,
        },
    )
    submission["status"] = "QUOTED"
    touched.add(submission)
    touched.flush()
    return object_response(quote, 201)


@bp.get("/dno/submissions/<submission_id>/quotes")
def list_quotes(submission_id):
    authenticate()
    submission = get_submission(submission_id)
    limit, offset = parse_pagination()
    records = derive.quotes_of(submission["id"])
    return list_response(paginate(records, limit, offset), limit, offset, len(records))
