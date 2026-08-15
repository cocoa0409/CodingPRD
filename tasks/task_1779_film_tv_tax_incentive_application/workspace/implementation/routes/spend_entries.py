"""SpendEntry endpoints: recording (with amendment) and review."""
from datetime import timedelta
from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_AMENDMENT_TARGET_MISMATCH,
    ERR_DUPLICATE_SPEND_INVOICE,
    ERR_INVALID_STATE_TRANSITION,
    ERR_VENDOR_PRODUCTION_MISMATCH,
    ERR_VENDOR_RESIDENCY_NOT_VERIFIED,
    ERR_VERIFICATION_WINDOW_EXPIRED,
)
from helpers import (
    check_producer_owns,
    company_id_of_application,
    get_one,
    list_query,
    program_of_application,
    public,
)
from middleware import authorized
from response import success_object
from services.core import (
    effective_amount_for_entry,
    new_record,
    recompute_application,
    touch,
)
from util import parse_dt
from validate import (
    get_body,
    opt_bool,
    opt_str,
    reject_unknown_fields,
    req_datetime,
    req_enum,
    req_int,
    req_str,
    require_body_ref,
    require_path_resource,
)

bp = Blueprint("spend_entries", __name__)

CATEGORIES = {"ATL", "BTL"}
REVIEW_DECISIONS = {"QUALIFY", "DISQUALIFY"}
AMENDABLE_STATUSES = {"PENDING_REVIEW", "QUALIFIED", "DISQUALIFIED"}


@bp.post("/spend-entries")
def create_spend_entry():
    caller = authorized(["Producer"])
    body = get_body()
    reject_unknown_fields(body, {
        "application_id", "vendor_id", "external_invoice_ref", "category",
        "is_resident_labor", "spend_date", "amount_cents", "amends_entry_id",
    })
    # Shape first: pure request-shape failures surface before stateful checks.
    application_id = req_str(body, "application_id")
    vendor_id = req_str(body, "vendor_id")
    external_invoice_ref = req_str(body, "external_invoice_ref")
    category = req_enum(body, "category", CATEGORIES)
    is_resident_labor = opt_bool(body, "is_resident_labor", False)
    spend_date = req_datetime(body, "spend_date")
    amount_cents = req_int(body, "amount_cents", positive=True)
    amends_entry_id = opt_str(body, "amends_entry_id", None)

    # Existence (3): body FKs left to right.
    app = require_body_ref("applications", application_id, "application_id")
    vendor = require_body_ref("vendors", vendor_id, "vendor_id")
    amend_target = None
    if amends_entry_id is not None:
        amend_target = require_body_ref("spend_entries", amends_entry_id, "amends_entry_id")

    # Ownership (4).
    check_producer_owns(caller, company_id_of_application(app))

    # State (5): spend is recorded only while APPROVED or CREDIT_ISSUED.
    if app["status"] not in ("APPROVED", "CREDIT_ISSUED"):
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    f"cannot record spend while the application is {app['status']}")

    # Structural (10): invoice unique per production across ALL applications.
    production_id = app["production_id"]
    for e in db["spend_entries"].values():
        if e["status"] == "SUPERSEDED":
            continue
        other_app = db["applications"].get(e["application_id"])
        if other_app is None or other_app["production_id"] != production_id:
            continue
        if e["external_invoice_ref"] == external_invoice_ref:
            raise_error(ERR_DUPLICATE_SPEND_INVOICE,
                        "external_invoice_ref already used by a non-SUPERSEDED entry of this production")

    # Referential (11): vendor belongs to the application's production;
    # amendment target belongs to the same application in an amendable status.
    if vendor["production_id"] != production_id:
        raise_error(ERR_VENDOR_PRODUCTION_MISMATCH,
                    "the vendor belongs to a different production than the application")
    if amend_target is not None:
        if amend_target["application_id"] != app["id"] or amend_target["status"] not in AMENDABLE_STATUSES:
            raise_error(ERR_AMENDMENT_TARGET_MISMATCH,
                        "amends_entry_id must reference an entry of the same application "
                        "in PENDING_REVIEW, QUALIFIED, or DISQUALIFIED")

    rec = new_record("spend_entries", {
        "application_id": application_id,
        "vendor_id": vendor_id,
        "external_invoice_ref": external_invoice_ref,
        "category": category,
        "is_resident_labor": is_resident_labor,
        "spend_date": spend_date,
        "amount_cents": amount_cents,
        "amends_entry_id": amends_entry_id,
        "status": "PENDING_REVIEW",
        "effective_amount_cents": 0,
        "disqualify_reason": None,
        "reviewed_by": None,
    })

    if amend_target is not None:
        # Atomic supersession; a QUALIFIED target drops out of the totals
        # through the same recompute cascade a disqualification triggers.
        was_qualified = amend_target["status"] == "QUALIFIED"
        amend_target["status"] = "SUPERSEDED"
        amend_target["effective_amount_cents"] = 0
        touch(amend_target)
        if was_qualified:
            recompute_application(app)

    return success_object(public(rec), status=201)


@bp.get("/spend-entries")
def list_spend_entries():
    return list_query("spend_entries", {
        "application_id": request.args.get("application_id"),
        "vendor_id": request.args.get("vendor_id"),
        "amends_entry_id": request.args.get("amends_entry_id"),
        "status": request.args.get("status"),
    })


@bp.get("/spend-entries/<entryId>")
def get_spend_entry(entryId):
    return get_one("spend_entries", entryId)


@bp.post("/spend-entries/<entryId>/review")
def review_spend_entry(entryId):
    caller = authorized(["FilmOfficeReviewer"])
    entry = require_path_resource("spend_entries", entryId)
    body = get_body()
    reject_unknown_fields(body, {"decision", "disqualify_reason"})
    decision = req_enum(body, "decision", REVIEW_DECISIONS)
    disqualify_reason = opt_str(body, "disqualify_reason", None)

    # State (5): the decision must be declared from the entry's current status.
    declared = (
        (entry["status"] in ("PENDING_REVIEW", "DISQUALIFIED") and decision == "QUALIFY")
        or (entry["status"] in ("PENDING_REVIEW", "QUALIFIED") and decision == "DISQUALIFY")
    )
    if not declared:
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    f"review decision {decision} is not declared from status {entry['status']}")

    app = db["applications"].get(entry["application_id"])
    program = program_of_application(app)
    vendor = db["vendors"].get(entry["vendor_id"])

    if decision == "QUALIFY":
        # The application must be APPROVED or CREDIT_ISSUED (state, 5).
        if app["status"] not in ("APPROVED", "CREDIT_ISSUED"):
            raise_error(ERR_INVALID_STATE_TRANSITION,
                        f"cannot qualify spend while the application is {app['status']}")
        # Compliance (8): vendor residency must be VERIFIED.
        if vendor is None or vendor["residency_status"] != "VERIFIED":
            raise_error(ERR_VENDOR_RESIDENCY_NOT_VERIFIED,
                        "the vendor's residency_status is not VERIFIED")
        # Temporal (9): spend_date in [verified_at, verified_at + validity) —
        # start inclusive, end exclusive, against the application's program.
        verified_at = parse_dt(vendor["verified_at"])
        window_end = verified_at + timedelta(days=int(program["vendor_verification_validity_days"]))
        spend_at = parse_dt(entry["spend_date"])
        if not (verified_at <= spend_at < window_end):
            raise_error(ERR_VERIFICATION_WINDOW_EXPIRED,
                        "spend_date falls outside the vendor's verification validity window")
        entry["effective_amount_cents"] = effective_amount_for_entry(entry, vendor, program)
        entry["status"] = "QUALIFIED"
        entry["reviewed_by"] = caller.user_id
        touch(entry)
        # Totals recompute cascade (provisional/recomputed, shares, exposure,
        # auto-clawback on a 0 -> >0 exposure transition).
        recompute_application(app)
    else:
        was_qualified = entry["status"] == "QUALIFIED"
        entry["status"] = "DISQUALIFIED"
        entry["disqualify_reason"] = disqualify_reason
        entry["effective_amount_cents"] = 0
        entry["reviewed_by"] = caller.user_id
        touch(entry)
        if was_qualified:
            recompute_application(app)

    return success_object(public(entry))
