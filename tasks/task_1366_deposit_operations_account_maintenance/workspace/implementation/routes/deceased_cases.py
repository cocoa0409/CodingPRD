"""DeceasedCase endpoints (PRD §3.4): REPORTED -> VERIFIED -> RELEASE_PENDING
-> RELEASED, with the deceased-hold cascade and estate-release closure.
"""

from datetime import date

from flask import Blueprint, request

import db
from errors import (
    ApiError,
    ERR_ACTIVE_REQUEST_EXISTS,
    ERR_CLOSURE_BLOCKED,
    ERR_DATE_RANGE_INVALID,
    ERR_DOCUMENTS_INCOMPLETE,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_SEGREGATION_OF_DUTIES,
)
from middleware import require_roles
from response import paginate, parse_pagination, success_list, success_object
from serialization import deceased_case_view
from services.account import (
    DEST_ESTATE,
    closure_cascade,
    get_account_or_404,
    post_transaction,
    touch_account,
    touch_resource,
)
from services.interest import VARIANT_STANDARD, accrued_interest

bp = Blueprint("deceased_cases", __name__)

ACTIVE_CASE_STATUSES = ("REPORTED", "VERIFIED", "RELEASE_PENDING")


def _get_case_or_404(case_id):
    case = db.deceased_cases.get(case_id)
    if case is None:
        raise ApiError(ERR_NOT_FOUND, f"Deceased case {case_id} does not exist")
    return case


def _has_verified_doc(account_id, doc_type):
    return any(
        d["account_id"] == account_id and d["doc_type"] == doc_type and d["status"] == "VERIFIED"
        for d in db.documents.values()
    )


@bp.post("/bank/accounts/<account_id>/deceased-cases")
def report_deceased(account_id):
    require_roles(["OpsOfficer"])
    get_account_or_404(account_id)
    body = request.get_json(silent=True) or {}

    decedent_name = body.get("decedent_name")
    if not isinstance(decedent_name, str) or not decedent_name.strip():
        raise ApiError(ERR_INVALID_REQUEST, "decedent_name is required")
    date_of_death_raw = body.get("date_of_death")
    if not isinstance(date_of_death_raw, str):
        raise ApiError(ERR_INVALID_REQUEST, "date_of_death is required")
    try:
        date_of_death = date.fromisoformat(date_of_death_raw).isoformat()
    except ValueError:
        raise ApiError(ERR_INVALID_REQUEST, "date_of_death must be a YYYY-MM-DD date")
    reported_by = body.get("reported_by")
    if not isinstance(reported_by, str) or not reported_by.strip():
        raise ApiError(ERR_INVALID_REQUEST, "reported_by is required")

    if any(
        c["account_id"] == account_id and c["status"] in ACTIVE_CASE_STATUSES
        for c in db.deceased_cases.values()
    ):
        raise ApiError(ERR_ACTIVE_REQUEST_EXISTS, "An active deceased case already exists")

    # Clock-relative: the date of death may not lie in the future (PRD §3.4).
    if date.fromisoformat(date_of_death) > db.clock_instant().date():
        raise ApiError(ERR_DATE_RANGE_INVALID, "date_of_death is in the future")

    case = {
        "id": db.new_uuid(),
        "account_id": account_id,
        "decedent_name": decedent_name,
        "date_of_death": date_of_death,
        "reported_by": reported_by,
        "status": "REPORTED",
        "balance_at_death_cents": None,
        "accrued_interest_at_death_cents": None,
        "release_variant": None,
        "release_amount_cents": None,
        "estate_representative_name": None,
        "initiated_by_user_id": None,
        "approved_by_user_id": None,
        "created_at": db.now_timestamp(),
        "updated_at": db.now_timestamp(),
        "version": 1,
        "_seq": db.next_creation_seq(),
    }
    db.deceased_cases[case["id"]] = case
    return success_object(deceased_case_view(case), status=201)


@bp.post("/bank/deceased-cases/<case_id>/verify")
def verify_case(case_id):
    require_roles(["OpsManager"])
    case = _get_case_or_404(case_id)
    acct = get_account_or_404(case["account_id"])

    if case["status"] != "REPORTED":
        raise ApiError(ERR_INVALID_STATE, "Only a REPORTED case can be verified")
    if not _has_verified_doc(acct["id"], "DEATH_CERTIFICATE"):
        raise ApiError(
            ERR_DOCUMENTS_INCOMPLETE,
            "A VERIFIED DEATH_CERTIFICATE document is required on the account",
        )

    # Freeze the estate's basis (PRD §3.4): STANDARD rounding regardless of product.
    case["balance_at_death_cents"] = acct["balance_cents"]
    case["accrued_interest_at_death_cents"] = accrued_interest(
        acct["id"], acct["accrual_start_date"], case["date_of_death"],
        acct["rate_bps"], VARIANT_STANDARD,
    )
    case["status"] = "VERIFIED"
    touch_resource(case)

    # The same act hardens the account: DECEASED_HOLD with cascades.
    acct["restriction_status"] = "DECEASED_HOLD"
    for s in db.signers.values():
        if s["account_id"] == acct["id"] and s["status"] == "ACTIVE":
            s["status"] = "SUSPENDED"  # removed_reason untouched
            touch_resource(s)
    for r in db.title_changes.values():
        if r["account_id"] == acct["id"] and r["status"] == "SUBMITTED":
            r["status"] = "REJECTED"
            r["decision_reason"] = "DECEASED_ACCOUNT"
            r["decided_by_user_id"] = None
            touch_resource(r)
    touch_account(acct)
    return success_object(deceased_case_view(case))


@bp.post("/bank/deceased-cases/<case_id>/initiate-release")
def initiate_release(case_id):
    user_id, _ = require_roles(["OpsOfficer"])
    case = _get_case_or_404(case_id)
    acct = get_account_or_404(case["account_id"])
    body = request.get_json(silent=True) or {}

    release_variant = body.get("release_variant")
    if release_variant not in ("DATE_OF_DEATH", "DATE_OF_RELEASE"):
        raise ApiError(ERR_INVALID_REQUEST, "release_variant must be DATE_OF_DEATH or DATE_OF_RELEASE")
    estate_representative_name = body.get("estate_representative_name")
    if not isinstance(estate_representative_name, str) or not estate_representative_name.strip():
        raise ApiError(ERR_INVALID_REQUEST, "estate_representative_name is required")

    if case["status"] != "VERIFIED":
        raise ApiError(ERR_INVALID_STATE, "Only a VERIFIED case can initiate release")
    if not _has_verified_doc(acct["id"], "LETTERS_TESTAMENTARY"):
        raise ApiError(
            ERR_DOCUMENTS_INCOMPLETE,
            "A VERIFIED LETTERS_TESTAMENTARY document is required on the account",
        )
    if any(
        g["account_id"] == acct["id"] and g["status"] == "FUNDS_HELD"
        for g in db.garnishments.values()
    ):
        raise ApiError(ERR_CLOSURE_BLOCKED, "A garnishment order still holds funds on the account")

    if release_variant == "DATE_OF_DEATH":
        release_amount = case["balance_at_death_cents"] + case["accrued_interest_at_death_cents"]
    else:
        release_amount = acct["balance_cents"] + accrued_interest(
            acct["id"], acct["accrual_start_date"], db.clock_date_str(),
            acct["rate_bps"], VARIANT_STANDARD,
        )

    case["release_variant"] = release_variant
    case["estate_representative_name"] = estate_representative_name
    case["release_amount_cents"] = release_amount
    case["initiated_by_user_id"] = user_id
    case["status"] = "RELEASE_PENDING"
    touch_resource(case)
    return success_object(deceased_case_view(case))


@bp.post("/bank/deceased-cases/<case_id>/approve-release")
def approve_release(case_id):
    user_id, _ = require_roles(["OpsManager"])
    case = _get_case_or_404(case_id)
    acct = get_account_or_404(case["account_id"])

    if case["status"] != "RELEASE_PENDING":
        raise ApiError(ERR_INVALID_STATE, "Only a RELEASE_PENDING case can be approved")
    if user_id == case["initiated_by_user_id"]:
        raise ApiError(ERR_SEGREGATION_OF_DUTIES, "Approver cannot be the release initiator")

    close_date = db.clock_date_str()
    release_amount = case["release_amount_cents"]
    if release_amount > 0:
        post_transaction(acct, "ESTATE_RELEASE", release_amount, False, close_date)
    # Residual sweep (e.g., post-death credits under DATE_OF_DEATH).
    residual = acct["balance_cents"]
    if residual > 0:
        post_transaction(acct, "CLOSURE_PAYOUT", residual, False, close_date)
    payout = release_amount + residual  # balance before approve == release + residual

    case["status"] = "RELEASED"
    case["approved_by_user_id"] = user_id
    touch_resource(case)

    acct["restriction_status"] = "NONE"  # clears only as part of this closure
    acct["lifecycle_status"] = "CLOSED"
    acct["closure_payout_cents"] = payout
    acct["closure_payout_destination"] = DEST_ESTATE
    closure_cascade(acct, close_date, "DECEASED_CASCADE")
    touch_account(acct)
    return success_object(deceased_case_view(case))


@bp.get("/bank/accounts/<account_id>/deceased-cases")
def list_deceased_cases(account_id):
    require_roles(["OpsOfficer", "OpsManager", "Auditor", "System"])
    get_account_or_404(account_id)
    limit, offset = parse_pagination(request.args)
    status = request.args.get("status")

    items = [c for c in db.deceased_cases.values() if c["account_id"] == account_id]
    items.sort(key=lambda c: c["_seq"])
    if status is not None:
        items = [c for c in items if c["status"] == status]
    total = len(items)
    page = paginate(items, limit, offset)
    return success_list([deceased_case_view(c) for c in page], total, limit, offset)
