"""Application routes: create/list/get, consent, identity, submit, search,
withdraw, score, decide."""

from flask import Blueprint, request

from db import store
from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    ERR_NOT_FOUND,
    ERR_APPLICATION_TERMINAL,
    ERR_INVALID_APPLICATION_STATE,
    ERR_INVALID_REPORT_STATE,
    ERR_LANDLORD_SUSPENDED,
    ERR_CONSENT_REQUIRED,
    ERR_IDENTITY_NOT_VERIFIED,
    ERR_IDENTITY_ATTEMPTS_EXHAUSTED,
    ERR_NO_PUBLISHED_CRITERIA,
    ERR_PORTABLE_SEARCH_FORBIDDEN,
    ERR_INCOME_VERIFICATION_UNRESOLVED,
)
from middleware import (
    get_context, require_role,
    check_landlord_ownership, check_applicant_ownership,
)
from response import success_object, success_list
from services.core import (
    covering_published_criteria,
    suppression_sweep, recompute_included_count, report_records,
    screening_fee, affordability, compute_recommendation,
    withdraw_cleanup, application_report, application_income_verification,
    check_portable_temporal, check_portable_structural,
    PORTABLE_FLAT_FEE_CENTS, IDENTITY_PASS_THRESHOLD, MAX_IDENTITY_ATTEMPTS,
)
from util import (
    clock, parse_dt, get_body,
    req_string, req_int, opt_int, pagination_params, paginate,
    stamp_new, touch, serialize,
)

bp = Blueprint("applications", __name__)

TERMINAL = ("APPROVED", "DENIED", "WITHDRAWN", "CANCELLED")


def _get_application_or_404(aid):
    app = store.applications.get(aid)
    if app is None:
        raise ApiError(ERR_NOT_FOUND, "Application not found", 404)
    return app


def _check_application_ownership(user_id, role, app):
    """Entity-backed read/write scoping for both Landlord and Applicant callers."""
    if role == "Landlord":
        check_landlord_ownership(user_id, role, app["landlord_id"])
    elif role == "Applicant":
        check_applicant_ownership(user_id, role, app["applicant_id"])


def _require_nonterminal(app):
    if app["status"] in TERMINAL:
        raise ApiError(
            ERR_APPLICATION_TERMINAL,
            "Application is in a terminal state",
            409,
        )


# ---------------------------------------------------------------------------
# Create / list / get
# ---------------------------------------------------------------------------

@bp.route("/api/applications", methods=["POST"])
def create_application():
    user_id, role = get_context()
    require_role(role, ["Landlord"])
    body = get_body()

    applicant_id = body.get("applicant_id")
    if applicant_id is None:
        raise ApiError(ERR_INVALID_REQUEST, "Missing required field: applicant_id", 400)
    if not isinstance(applicant_id, str):
        raise ApiError(ERR_INVALID_REQUEST, "Field 'applicant_id' must be a string", 400)
    unit_state_code = req_string(body, "unit_state_code")
    monthly_rent = req_int(body, "monthly_rent_cents")
    if monthly_rent <= 0:
        raise ApiError(ERR_INVALID_REQUEST, "Field 'monthly_rent_cents' must be > 0", 400)
    stated_income = req_int(body, "stated_monthly_income_cents")
    if stated_income < 0:
        raise ApiError(ERR_INVALID_REQUEST, "Field 'stated_monthly_income_cents' must be >= 0", 400)
    voucher = opt_int(body, "voucher_monthly_amount_cents", 0)
    portable_report_id = body.get("portable_report_id")
    if portable_report_id is not None and not isinstance(portable_report_id, str):
        raise ApiError(ERR_INVALID_REQUEST, "Field 'portable_report_id' must be a string", 400)

    # Existence (stage 3): body-referenced ids — applicant_id then portable_report_id.
    if applicant_id not in store.applicants:
        raise ApiError(ERR_NOT_FOUND, "Referenced applicant_id does not exist", 404)
    if portable_report_id is not None and portable_report_id not in store.reports:
        raise ApiError(ERR_NOT_FOUND, "Referenced portable_report_id does not exist", 404)

    # Cross-entity state (stage 7): landlord must be ACTIVE.
    landlord = store.landlords.get(user_id)
    if landlord is None:
        raise ApiError(ERR_NOT_FOUND, "Acting landlord not found", 404)
    if landlord["status"] != "ACTIVE":
        raise ApiError(ERR_LANDLORD_SUSPENDED, "Landlord is SUSPENDED; new applications are rejected", 409)

    app = stamp_new({
        "applicant_id": applicant_id,
        "landlord_id": user_id,
        "criteria_id": None,
        "portable_report_id": portable_report_id,
        "unit_state_code": unit_state_code,
        "monthly_rent_cents": monthly_rent,
        "stated_monthly_income_cents": stated_income,
        "voucher_monthly_amount_cents": voucher,
        "consent_signed_at": None,
        "identity_status": "UNVERIFIED",
        "identity_attempts": 0,
        "status": "DRAFT",
        "submitted_at": None,
        "credit_score": None,
        "verified_income_cents": None,
        "affordability_passes": None,
        "eviction_included_count": None,
        "criminal_included_count": None,
        "recommendation": None,
        "decision": None,
        "decided_at": None,
        "requires_reconsideration": False,
        "fee_charged_cents": 0,
    })
    store.applications[app["id"]] = app
    return success_object(serialize(app), 201)


@bp.route("/api/applications", methods=["GET"])
def list_applications():
    user_id, role = get_context()
    require_role(role, ["ComplianceAdmin", "Screener", "Landlord", "Applicant"])
    items = sorted(store.applications.values(), key=lambda a: a["created_at"])
    if role == "Landlord":
        items = [a for a in items if a["landlord_id"] == user_id]
    elif role == "Applicant":
        items = [a for a in items if a["applicant_id"] == user_id]
    for param in ("landlord_id", "applicant_id", "criteria_id", "portable_report_id", "status"):
        v = request.args.get(param)
        if v is not None:
            items = [a for a in items if str(a.get(param)) == v]
    limit, offset = pagination_params()
    page, total = paginate(items, limit, offset)
    return success_list([serialize(a) for a in page], limit, offset, total)


@bp.route("/api/applications/<aid>", methods=["GET"])
def get_application(aid):
    user_id, role = get_context()
    require_role(role, ["ComplianceAdmin", "Screener", "Landlord", "Applicant"])
    app = _get_application_or_404(aid)
    _check_application_ownership(user_id, role, app)
    return success_object(serialize(app))


# ---------------------------------------------------------------------------
# Consent
# ---------------------------------------------------------------------------

@bp.route("/api/applications/<aid>/consent", methods=["POST"])
def consent(aid):
    user_id, role = get_context()
    require_role(role, ["Applicant"])
    app = _get_application_or_404(aid)
    check_applicant_ownership(user_id, role, app["applicant_id"])
    _require_nonterminal(app)
    app["consent_signed_at"] = clock()
    touch(app)
    return success_object(serialize(app))


# ---------------------------------------------------------------------------
# Identity verification (parallel dimension)
# ---------------------------------------------------------------------------

@bp.route("/api/applications/<aid>/verify-identity", methods=["POST"])
def verify_identity(aid):
    user_id, role = get_context()
    require_role(role, ["Screener"])
    body = get_body()
    method = req_string(body, "method")
    evidence_score = req_int(body, "evidence_score")
    app = _get_application_or_404(aid)

    # From-state (stage 6): DRAFT or SUBMITTED only; terminal distinct error.
    if app["status"] in TERMINAL:
        raise ApiError(ERR_APPLICATION_TERMINAL, "Application is in a terminal state", 409)
    if app["status"] not in ("DRAFT", "SUBMITTED"):
        raise ApiError(
            ERR_INVALID_APPLICATION_STATE,
            "Identity verification is only permitted while the application is DRAFT or SUBMITTED",
            409,
        )
    # VERIFIED is terminal for this dimension.
    if app["identity_status"] == "VERIFIED":
        raise ApiError(
            ERR_INVALID_APPLICATION_STATE,
            "Identity is already VERIFIED",
            409,
        )
    # Structural constraint: attempts exhausted (checked before scoring).
    if app["identity_attempts"] >= MAX_IDENTITY_ATTEMPTS:
        raise ApiError(
            ERR_IDENTITY_ATTEMPTS_EXHAUSTED,
            "Identity verification attempt limit (3) reached",
            409,
        )

    app["identity_attempts"] += 1
    app["identity_status"] = "VERIFIED" if evidence_score >= IDENTITY_PASS_THRESHOLD else "FAILED"
    touch(app)
    return success_object(serialize(app))


# ---------------------------------------------------------------------------
# Submit
# ---------------------------------------------------------------------------

@bp.route("/api/applications/<aid>/submit", methods=["POST"])
def submit(aid):
    user_id, role = get_context()
    require_role(role, ["Landlord"])
    app = _get_application_or_404(aid)
    check_landlord_ownership(user_id, role, app["landlord_id"])

    # From-state (stage 6)
    if app["status"] in TERMINAL:
        raise ApiError(ERR_APPLICATION_TERMINAL, "Application is in a terminal state", 409)
    if app["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_APPLICATION_STATE, "Application is not in DRAFT", 409)

    at = clock()
    portable_id = app.get("portable_report_id")
    source_report = store.reports.get(portable_id) if portable_id else None
    if portable_id and source_report is None:
        raise ApiError(ERR_NOT_FOUND, "Referenced portable_report_id does not exist", 404)

    # Temporal gate (stage 9): portable validity window
    if source_report is not None:
        check_portable_temporal(source_report, at)

    # Structural (stage 10), in pinned relative order:
    # 1) exactly one covering PUBLISHED criteria
    matches = covering_published_criteria(app["landlord_id"], at)
    if len(matches) != 1:
        raise ApiError(
            ERR_NO_PUBLISHED_CRITERIA,
            "No PUBLISHED criteria of the landlord covers the submission clock time",
            409,
        )
    criteria = matches[0]

    # 2) portable same-applicant + DELIVERED/RE_DELIVERED; 3) portable acceptance
    if source_report is not None:
        check_portable_structural(app, source_report, criteria, at)

    # Commit
    app["criteria_id"] = criteria["id"]
    app["submitted_at"] = at
    app["status"] = "SUBMITTED"

    if source_report is not None:
        # Create the portable-copy report: copy records, re-run the sweep under
        # THIS application's unit_state_code at the submission clock.
        report = stamp_new({
            "application_id": app["id"],
            "is_portable_copy": True,
            "source_report_id": source_report["id"],
            "status": "DRAFT",
            "originating_screener_id": source_report.get("originating_screener_id"),
            "credit_score": source_report.get("credit_score"),
            "included_record_count": 0,
            "delivered_at": None,
            "last_delivered_at": None,
        })
        store.reports[report["id"]] = report
        new_records = []
        for src_rec in report_records(source_report["id"]):
            rec = stamp_new({
                "report_id": report["id"],
                "record_type": src_rec["record_type"],
                "jurisdiction_state_code": src_rec["jurisdiction_state_code"],
                "record_date": src_rec["record_date"],
                "description": src_rec["description"],
                "status": None,
                "suppression_reason": None,
            })
            store.records[rec["id"]] = rec
            new_records.append(rec)
        suppression_sweep(new_records, app["unit_state_code"], at)
        recompute_included_count(report)
        # Flat fee, no surcharges, no cap.
        app["fee_charged_cents"] = PORTABLE_FLAT_FEE_CENTS
        landlord = store.landlords[app["landlord_id"]]
        landlord["fee_balance_cents"] += PORTABLE_FLAT_FEE_CENTS
        touch(landlord)

    touch(app)
    return success_object(serialize(app))


# ---------------------------------------------------------------------------
# Record searches (bureau search)
# ---------------------------------------------------------------------------

@bp.route("/api/applications/<aid>/record-searches", methods=["POST"])
def record_searches(aid):
    user_id, role = get_context()
    require_role(role, ["Screener"])
    body = get_body()
    credit_score = req_int(body, "credit_score")
    records_input = body.get("records")
    if records_input is None:
        raise ApiError(ERR_INVALID_REQUEST, "Missing required field: records", 400)
    if not isinstance(records_input, list):
        raise ApiError(ERR_INVALID_REQUEST, "Field 'records' must be an array", 400)

    app = _get_application_or_404(aid)

    # From-state (stage 6): SUBMITTED required; terminal distinct error.
    if app["status"] in TERMINAL:
        raise ApiError(ERR_APPLICATION_TERMINAL, "Application is in a terminal state", 409)
    if app["status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_APPLICATION_STATE, "Application is not in SUBMITTED", 409)
    if app.get("portable_report_id"):
        raise ApiError(
            ERR_PORTABLE_SEARCH_FORBIDDEN,
            "Portable applications reuse the copied report and never run a bureau search",
            409,
        )

    # Compliance gates (stage 8): consent first, then identity.
    if app.get("consent_signed_at") is None:
        raise ApiError(ERR_CONSENT_REQUIRED, "Applicant consent is required before any bureau record search", 422)
    if app["identity_status"] != "VERIFIED":
        raise ApiError(ERR_IDENTITY_NOT_VERIFIED, "Applicant identity must be VERIFIED before any bureau record search", 422)

    # Validate record entries.
    parsed_records = []
    for i, entry in enumerate(records_input):
        if not isinstance(entry, dict):
            raise ApiError(ERR_INVALID_REQUEST, f"records[{i}] must be an object", 400)
        rtype = entry.get("record_type")
        if rtype not in ("EVICTION", "CRIMINAL"):
            raise ApiError(ERR_INVALID_REQUEST, f"records[{i}].record_type must be EVICTION or CRIMINAL", 400)
        jstate = entry.get("jurisdiction_state_code")
        if not isinstance(jstate, str) or not jstate.strip():
            raise ApiError(ERR_INVALID_REQUEST, f"records[{i}].jurisdiction_state_code must be a string", 400)
        rdate_raw = entry.get("record_date")
        if rdate_raw is None:
            raise ApiError(ERR_INVALID_REQUEST, f"records[{i}].record_date is required", 400)
        rdate = parse_dt(rdate_raw, f"records[{i}].record_date")
        desc = entry.get("description")
        if not isinstance(desc, str):
            raise ApiError(ERR_INVALID_REQUEST, f"records[{i}].description must be a string", 400)
        parsed_records.append((rtype, jstate, rdate, desc))

    at = clock()

    report = stamp_new({
        "application_id": app["id"],
        "is_portable_copy": False,
        "source_report_id": None,
        "status": "DRAFT",
        "originating_screener_id": user_id,
        "credit_score": credit_score,
        "included_record_count": 0,
        "delivered_at": None,
        "last_delivered_at": None,
    })
    store.reports[report["id"]] = report

    new_records = []
    for rtype, jstate, rdate, desc in parsed_records:
        rec = stamp_new({
            "report_id": report["id"],
            "record_type": rtype,
            "jurisdiction_state_code": jstate,
            "record_date": rdate,
            "description": desc,
            "status": None,
            "suppression_reason": None,
        })
        store.records[rec["id"]] = rec
        new_records.append(rec)

    suppression_sweep(new_records, app["unit_state_code"], at)
    recompute_included_count(report)

    fee = screening_fee(app["unit_state_code"], at)
    app["fee_charged_cents"] += fee
    app["credit_score"] = credit_score
    app["status"] = "SCREENING"
    touch(app)

    landlord = store.landlords[app["landlord_id"]]
    landlord["fee_balance_cents"] += fee
    touch(landlord)

    return success_object(serialize(report), 201)


# ---------------------------------------------------------------------------
# Withdraw
# ---------------------------------------------------------------------------

@bp.route("/api/applications/<aid>/withdraw", methods=["POST"])
def withdraw(aid):
    user_id, role = get_context()
    require_role(role, ["Landlord", "Applicant"])
    app = _get_application_or_404(aid)
    _check_application_ownership(user_id, role, app)
    if app["status"] in TERMINAL:
        raise ApiError(ERR_APPLICATION_TERMINAL, "Application is in a terminal state", 409)
    app["status"] = "WITHDRAWN"
    touch(app)
    landlord = store.landlords[app["landlord_id"]]
    withdraw_cleanup(app, landlord)
    return success_object(serialize(app))


# ---------------------------------------------------------------------------
# Score
# ---------------------------------------------------------------------------

@bp.route("/api/applications/<aid>/score", methods=["POST"])
def score(aid):
    user_id, role = get_context()
    require_role(role, ["Screener"])
    app = _get_application_or_404(aid)

    if app["status"] in TERMINAL:
        raise ApiError(ERR_APPLICATION_TERMINAL, "Application is in a terminal state", 409)
    if app["status"] != "SCREENING":
        raise ApiError(ERR_INVALID_APPLICATION_STATE, "Application is not in SCREENING", 409)

    # Cross-entity state (stage 7): income verification resolved.
    iv = application_income_verification(app["id"])
    if iv is None or iv["status"] not in ("VERIFIED", "FAILED"):
        raise ApiError(
            ERR_INCOME_VERIFICATION_UNRESOLVED,
            "Scoring requires the application's income verification to be VERIFIED or FAILED",
            409,
        )

    criteria = store.criteria.get(app["criteria_id"])
    if criteria is None:
        # Should not happen for a SCREENING application, but guard anyway.
        raise ApiError(ERR_NOT_FOUND, "Pinned criteria not found", 404)

    at = clock()
    app["verified_income_cents"] = iv["verified_monthly_income_cents"] if iv["status"] == "VERIFIED" else None
    app["affordability_passes"] = affordability(app, criteria, at)

    report = application_report(app["id"])
    included = [r for r in report_records(report["id"]) if r["status"] == "INCLUDED"] if report else []
    app["eviction_included_count"] = sum(1 for r in included if r["record_type"] == "EVICTION")
    app["criminal_included_count"] = sum(1 for r in included if r["record_type"] == "CRIMINAL")

    app["recommendation"] = compute_recommendation(app, criteria)
    app["status"] = "SCORED"
    touch(app)
    return success_object(serialize(app))


# ---------------------------------------------------------------------------
# Decide
# ---------------------------------------------------------------------------

@bp.route("/api/applications/<aid>/decide", methods=["POST"])
def decide(aid):
    user_id, role = get_context()
    require_role(role, ["Landlord"])
    body = get_body()
    decision = body.get("decision")
    if decision not in ("APPROVE", "DENY"):
        raise ApiError(ERR_INVALID_REQUEST, "Field 'decision' must be APPROVE or DENY", 400)

    app = _get_application_or_404(aid)
    check_landlord_ownership(user_id, role, app["landlord_id"])

    if app["status"] in TERMINAL:
        raise ApiError(ERR_APPLICATION_TERMINAL, "Application is in a terminal state", 409)
    if app["status"] != "SCORED":
        raise ApiError(ERR_INVALID_APPLICATION_STATE, "Application is not in SCORED", 409)

    # Cross-entity state (stage 7): report must be DELIVERED or RE_DELIVERED.
    report = application_report(app["id"])
    if report is None or report["status"] not in ("DELIVERED", "RE_DELIVERED"):
        raise ApiError(
            ERR_INVALID_REPORT_STATE,
            "Decision requires the report DELIVERED or RE_DELIVERED",
            409,
        )

    at = clock()
    app["decision"] = decision
    app["decided_at"] = at
    app["status"] = "APPROVED" if decision == "APPROVE" else "DENIED"
    touch(app)

    if decision == "DENY":
        criteria = store.criteria.get(app["criteria_id"])
        iv = application_income_verification(app["id"])
        reasons = []
        if app.get("credit_score") is not None and criteria is not None and app["credit_score"] < criteria["min_credit_score"]:
            reasons.append("CREDIT_SCORE_BELOW_MINIMUM")
        if (app.get("eviction_included_count") or 0) > 0:
            reasons.append("EVICTION_RECORD")
        if (app.get("criminal_included_count") or 0) > 0:
            reasons.append("CRIMINAL_RECORD")
        if iv is not None and iv["status"] == "FAILED":
            reasons.append("INCOME_UNVERIFIABLE")
        if app.get("affordability_passes") is False and iv is not None and iv["status"] == "VERIFIED":
            reasons.append("RENT_TO_INCOME_BELOW_REQUIRED")
        notice = stamp_new({
            "application_id": app["id"],
            "reason_codes": reasons,
            "status": "DRAFT",
            "issued_at": None,
            "dispute_deadline": None,
            "rescinded_at": None,
        })
        store.notices[notice["id"]] = notice

    return success_object(serialize(app))
