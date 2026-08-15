"""Rebate / tax-credit dossiers."""
from datetime import timedelta
from flask import Blueprint, request

import clock
import db
from errors import ApiError, ERR_REBATE_MISMATCH, ERR_STALE_VERSION, \
    ERR_WINDOW_EXPIRED, invalid_state, invalid_request
from middleware import authenticate, authorize, require_owner
from response import success
from serializers import rebate_submission as ser
from services import core
from utils import StructErrors, check_unknown_fields, get_str, get_enum, \
    get_datetime, touch
from routes.common import body, get_path, get_ref, new_common, list_response

bp = Blueprint("rebates", __name__)

READ_ROLES = {"DistributorAdmin", "ContractorUser", "ComplianceOfficer"}
DOC_KINDS = {"AHRI_CERTIFICATE", "INVOICE", "LOAD_CALC", "PERMIT"}


def _validate_docs(docs, struct, required=False):
    if docs is None:
        if required:
            struct.add("Missing required field: docs")
        return None
    if not isinstance(docs, list):
        struct.add("Field docs must be an array")
        return None
    out = []
    for d in docs:
        if d not in DOC_KINDS:
            struct.add("docs entries must be one of %s" % sorted(DOC_KINDS))
        elif d not in out:
            out.append(d)
    return out


def _check_consistency(data, order, rating, struct):
    """ERR_REBATE_MISMATCH (priority 17): rating must appear on a line of the
    order; install_date >= order.submitted_at and <= logical clock."""
    install_date = data.get("_install_date")
    if order is not None and rating is not None:
        on_line = any(
            l["order_id"] == order["id"]
            and l.get("ahri_rating_id") == rating["id"]
            for l in db.order_lines.values())
        if not on_line:
            raise ApiError(ERR_REBATE_MISMATCH, 422,
                           "ahri_rating_id does not appear on a line of the "
                           "referenced order")
    if install_date is not None and order is not None:
        submitted = order.get("submitted_at")
        if submitted is not None and install_date < submitted:
            raise ApiError(ERR_REBATE_MISMATCH, 422,
                           "install_date is before the order's submission")
    if install_date is not None and install_date > clock.now():
        raise ApiError(ERR_REBATE_MISMATCH, 422,
                       "install_date may not be in the future")


@bp.post("/rebate-submissions")
def create_submission():
    user_id, role = authenticate()
    authorize({"ContractorUser"}, role)
    data = body()
    struct = StructErrors()
    check_unknown_fields(data, {"contractor_id", "order_id", "ahri_rating_id",
                                "program_type", "homeowner_name",
                                "install_address", "install_date", "docs"},
                         struct)
    contractor_id = get_str(data, "contractor_id", struct)
    order_id = get_str(data, "order_id", struct)
    ahri_rating_id = get_str(data, "ahri_rating_id", struct)
    program_type = get_enum(data, "program_type", struct,
                            {"FEDERAL_TAX_CREDIT", "UTILITY_REBATE"})
    homeowner_name = get_str(data, "homeowner_name", struct)
    install_address = get_str(data, "install_address", struct)
    install_date = get_datetime(data, "install_date", struct)
    docs = _validate_docs(data.get("docs"), struct, required=False)

    order = rating = None
    if isinstance(contractor_id, str):
        get_ref(db.contractors, contractor_id, "contractor_id")
    if isinstance(order_id, str):
        order = get_ref(db.orders, order_id, "order_id")
    if isinstance(ahri_rating_id, str):
        rating = get_ref(db.ahri_ratings, ahri_rating_id, "ahri_rating_id")

    if isinstance(contractor_id, str):
        require_owner(contractor_id, role, user_id)

    _check_consistency({"_install_date": install_date}, order, rating, struct)
    struct.raise_if_bad()

    r = new_common()
    r.update({
        "contractor_id": contractor_id,
        "order_id": order_id,
        "ahri_rating_id": ahri_rating_id,
        "program_type": program_type,
        "homeowner_name": homeowner_name,
        "install_address": install_address,
        "install_date": install_date,
        "docs": docs or [],
        "qualified_amount_cents": 0,
        "submitted_at": None,
        "decision_deadline": None,
        "status": "DRAFT",
    })
    db.rebate_submissions[r["id"]] = r
    return success(ser(r), 201)


@bp.get("/rebate-submissions/<rid>")
def get_submission(rid):
    user_id, role = authenticate()
    authorize(READ_ROLES, role)
    r = get_path(db.rebate_submissions, rid)
    require_owner(r["contractor_id"], role, user_id)
    return success(ser(r))


@bp.get("/rebate-submissions")
def list_submissions():
    user_id, role = authenticate()
    authorize(READ_ROLES, role)
    filters = {"contractor_id": request.args.get("contractor_id"),
               "order_id": request.args.get("order_id"),
               "ahri_rating_id": request.args.get("ahri_rating_id"),
               "status": request.args.get("status")}
    return list_response(db.rebate_submissions.values(), ser, filters,
                         owner_field="contractor_id", role=role,
                         user_id=user_id)


@bp.patch("/rebate-submissions/<rid>")
def patch_submission(rid):
    user_id, role = authenticate()
    authorize({"ContractorUser"}, role)
    r = get_path(db.rebate_submissions, rid)
    data = body()
    struct = StructErrors()
    check_unknown_fields(data, {"expected_rebate_version", "docs"}, struct)
    require_owner(r["contractor_id"], role, user_id)
    if r["status"] not in ("DRAFT", "SUBMITTED"):
        raise invalid_state("Documents may only be attached while DRAFT or "
                            "SUBMITTED")
    # OCC (priority 21).
    if "expected_rebate_version" not in data:
        raise invalid_request("Missing required field: expected_rebate_version")
    if data["expected_rebate_version"] != r["version"]:
        raise ApiError(ERR_STALE_VERSION, 412,
                       "expected_rebate_version does not match current version")
    docs = _validate_docs(data.get("docs"), struct, required=True)
    struct.raise_if_bad()

    # The checklist is cumulative: union the payload into the stored list.
    merged = list(r["docs"])
    for d in docs:
        if d not in merged:
            merged.append(d)
    r["docs"] = merged
    if r["status"] == "SUBMITTED" and len(set(merged)) == 4:
        r["status"] = "DOCS_COMPLETE"
    touch(r)
    return success(ser(r))


@bp.post("/rebate-submissions/<rid>/submit")
def submit_submission(rid):
    user_id, role = authenticate()
    authorize({"ContractorUser"}, role)
    r = get_path(db.rebate_submissions, rid)
    require_owner(r["contractor_id"], role, user_id)
    if r["status"] != "DRAFT":
        raise invalid_state("Only a DRAFT dossier may be submitted")

    order = db.orders.get(r["order_id"])
    rating = db.ahri_ratings.get(r["ahri_rating_id"])
    # Order- and rating-state gates -> ERR_INVALID_STATE (409).
    if order is None or order["status"] != "DELIVERED":
        raise invalid_state("Referenced order is not DELIVERED")
    if rating is None or rating["status"] != "ACTIVE":
        raise invalid_state("Referenced AHRI rating is not ACTIVE")

    # Consistency and document requirements -> ERR_REBATE_MISMATCH (422).
    if r["program_type"] == "FEDERAL_TAX_CREDIT" and \
            not rating["tax_credit_eligible"]:
        raise ApiError(ERR_REBATE_MISMATCH, 422,
                       "Rating is not tax-credit eligible")
    on_line = any(l["order_id"] == order["id"]
                  and l.get("ahri_rating_id") == r["ahri_rating_id"]
                  for l in db.order_lines.values())
    if not on_line:
        raise ApiError(ERR_REBATE_MISMATCH, 422,
                       "ahri_rating_id does not appear on a line of the order")
    if order.get("submitted_at") is not None and \
            r["install_date"] < order["submitted_at"]:
        raise ApiError(ERR_REBATE_MISMATCH, 422,
                       "install_date is before the order's submission")
    docs = set(r["docs"])
    if not {"AHRI_CERTIFICATE", "INVOICE"}.issubset(docs):
        raise ApiError(ERR_REBATE_MISMATCH, 422,
                       "docs must contain AHRI_CERTIFICATE and INVOICE")

    r["submitted_at"] = clock.now()
    r["decision_deadline"] = r["submitted_at"] + timedelta(days=45)
    r["status"] = "SUBMITTED"
    if len(docs) == 4:
        r["status"] = "DOCS_COMPLETE"
    touch(r)
    return success(ser(r))


@bp.post("/rebate-submissions/<rid>/decision")
def rebate_decision(rid):
    user_id, role = authenticate()
    authorize({"ComplianceOfficer", "DistributorAdmin"}, role)
    data = body()
    action = data.get("action")
    if not isinstance(action, str) or action not in ("QUALIFY", "REJECT", "PAY"):
        raise invalid_request("action must be one of QUALIFY, REJECT, PAY")
    if action in ("QUALIFY", "REJECT"):
        authorize({"ComplianceOfficer"}, role)
    else:
        authorize({"DistributorAdmin"}, role)

    r = get_path(db.rebate_submissions, rid)

    if action == "QUALIFY":
        if r["status"] != "DOCS_COMPLETE":
            raise invalid_state("Only a DOCS_COMPLETE dossier may be qualified")
        order = db.orders.get(r["order_id"])
        rating = db.ahri_ratings.get(r["ahri_rating_id"])
        r["qualified_amount_cents"] = core.compute_rebate_qualification(
            r, order, rating)
        r["status"] = "QUALIFIED"
    elif action == "REJECT":
        if r["status"] != "DOCS_COMPLETE":
            raise invalid_state("Only a DOCS_COMPLETE dossier may be rejected")
        r["status"] = "REJECTED"
    elif action == "PAY":
        # A payout attempted past the decision deadline is WINDOW_EXPIRED —
        # covering both a still-QUALIFIED dossier past its deadline and one
        # the lazy sweep already expired (EXPIRED only results from the
        # deadline passing). PAID/REJECTED/DRAFT/etc. are state violations.
        if r["status"] == "EXPIRED":
            raise ApiError(ERR_WINDOW_EXPIRED, 422,
                           "Decision deadline has passed")
        if r["status"] != "QUALIFIED":
            raise invalid_state("Only a QUALIFIED dossier may be paid")
        if clock.now() > r["decision_deadline"]:
            r["status"] = "EXPIRED"
            touch(r)
            raise ApiError(ERR_WINDOW_EXPIRED, 422,
                           "Decision deadline has passed")
        r["status"] = "PAID"
    touch(r)
    return success(ser(r))
