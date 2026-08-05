"""Sublet & Lease-Takeover Marketplace API — Flask entry point.

All behaviour traces to PRD.md. In-memory store, logical clock, no seeding.
"""

import os
from datetime import date, timedelta

from flask import Flask, request

import core
from core import (
    ApiError, require_auth, require_role, get_or_404, get_body,
    req_str, opt_str, req_int, opt_int, opt_bool, req_enum, opt_enum,
    parse_date, parse_datetime_field, parse_iso_datetime,
    ok_object, ok_array, error_response, paginate, serialize, touch,
    new_common, now_iso, set_clock, STORE, parse_pagination,
)
import services
import presenters
from presenters import present_applicant, present_lease, present_agreement

app = Flask(__name__)

ALL_ROLES = ["Landlord", "Leaseholder", "Applicant", "ComplianceOfficer", "PlatformAdmin"]


@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.message)


@app.errorhandler(404)
def handle_404(e):
    return error_response("ERR_VALIDATION", "No such route")


@app.errorhandler(405)
def handle_405(e):
    return error_response("ERR_VALIDATION", "Method not allowed")


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return error_response(e.error_id, e.message)
    return error_response("ERR_VALIDATION", "Unexpected error: %s" % e)


# ---------------------------------------------------------------------------
# Ownership helpers (PRD §2.1)
# ---------------------------------------------------------------------------
def own_check(actual_owner_id, uid):
    if actual_owner_id != uid:
        raise ApiError("ERR_OWNERSHIP_VIOLATION")


def lease_of_listing(listing):
    return STORE["leases"].get(listing["lease_id"])


def lease_of_agreement(agreement):
    return STORE["leases"].get(agreement["lease_id"])


def render_list(rows, present_fn=serialize):
    limit, offset = parse_pagination()
    ordered = sorted(rows, key=lambda e: (e["created_at"], e["_seq"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return ok_array([present_fn(e) for e in page], limit, offset, total)


# ===========================================================================
# Clock
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock_endpoint():
    uid, role = require_auth()
    require_role(role, ["PlatformAdmin", "ComplianceOfficer"])
    body = get_body()
    iso = req_str(body, "to_iso8601")
    dt = parse_iso_datetime(iso)
    set_clock(dt)
    return ok_object({})


# ===========================================================================
# Parties
# ===========================================================================
@app.route("/landlords", methods=["POST"])
def create_landlord():
    uid, role = require_auth()
    require_role(role, ["PlatformAdmin"])
    body = get_body()
    name = req_str(body, "name")
    email = req_str(body, "email")
    ent = new_common()
    ent.update({"name": name, "email": email})
    STORE["landlords"][ent["id"]] = ent
    return ok_object(serialize(ent), 201)


@app.route("/landlords/<lid>", methods=["GET"])
def get_landlord(lid):
    uid, role = require_auth()
    require_role(role, ALL_ROLES)
    ent = get_or_404("landlords", lid, "ERR_LANDLORD_NOT_FOUND")
    return ok_object(serialize(ent))


@app.route("/leaseholders", methods=["POST"])
def create_leaseholder():
    uid, role = require_auth()
    require_role(role, ["PlatformAdmin"])
    body = get_body()
    name = req_str(body, "name")
    email = req_str(body, "email")
    ent = new_common()
    ent.update({"name": name, "email": email})
    STORE["leaseholders"][ent["id"]] = ent
    return ok_object(serialize(ent), 201)


@app.route("/leaseholders/<lid>", methods=["GET"])
def get_leaseholder(lid):
    uid, role = require_auth()
    require_role(role, ALL_ROLES)
    ent = get_or_404("leaseholders", lid, "ERR_LEASEHOLDER_NOT_FOUND")
    return ok_object(serialize(ent))


@app.route("/applicants", methods=["POST"])
def create_applicant():
    uid, role = require_auth()
    require_role(role, ["PlatformAdmin"])
    body = get_body()
    name = req_str(body, "name")
    email = req_str(body, "email")
    annual_income = req_int(body, "annual_income_cents", min_val=0)
    monthly_debt = opt_int(body, "monthly_debt_cents", 0, min_val=0)
    credit_score = req_int(body, "credit_score", min_val=300, max_val=850)
    ent = new_common()
    ent.update({
        "name": name, "email": email,
        "annual_income_cents": annual_income,
        "monthly_debt_cents": monthly_debt,
        "credit_score": credit_score,
    })
    STORE["applicants"][ent["id"]] = ent
    return ok_object(present_applicant(ent), 201)


@app.route("/applicants/<aid>", methods=["GET"])
def get_applicant(aid):
    uid, role = require_auth()
    require_role(role, ALL_ROLES)
    ent = get_or_404("applicants", aid, "ERR_APPLICANT_NOT_FOUND")
    return ok_object(present_applicant(ent))


# ===========================================================================
# Leases
# ===========================================================================
@app.route("/leases", methods=["POST"])
def create_lease():
    uid, role = require_auth()
    require_role(role, ["Landlord"])
    body = get_body()
    landlord_id = req_str(body, "landlord_id")
    leaseholder_id = req_str(body, "leaseholder_id")
    monthly_rent = req_int(body, "monthly_rent_cents", min_val=1)
    security_deposit = req_int(body, "security_deposit_cents", min_val=0)
    term_start = parse_date(body, "term_start_date")
    term_end = parse_date(body, "term_end_date")
    allows_sublet = opt_bool(body, "allows_sublet", False)
    allows_assignment = opt_bool(body, "allows_assignment", False)
    # ownership (§2.9 step 3): acting landlord must be landlord_id
    own_check(landlord_id, uid)
    # existence (step 4)
    get_or_404("landlords", landlord_id, "ERR_LANDLORD_NOT_FOUND")
    get_or_404("leaseholders", leaseholder_id, "ERR_LEASEHOLDER_NOT_FOUND")
    # date validity
    if not (term_end > term_start):
        raise ApiError("ERR_LEASE_DATES_INVALID")
    ent = new_common()
    ent.update({
        "landlord_id": landlord_id,
        "leaseholder_id": leaseholder_id,
        "monthly_rent_cents": monthly_rent,
        "security_deposit_cents": security_deposit,
        "term_start_date": body["term_start_date"],
        "term_end_date": body["term_end_date"],
        "allows_sublet": allows_sublet,
        "allows_assignment": allows_assignment,
        "status": "UNVERIFIED",
        "active_occupancy_count": 0,
    })
    STORE["leases"][ent["id"]] = ent
    return ok_object(present_lease(ent), 201)


@app.route("/leases/<lid>", methods=["GET"])
def get_lease(lid):
    uid, role = require_auth()
    require_role(role, ALL_ROLES)
    ent = get_or_404("leases", lid, "ERR_LEASE_NOT_FOUND")
    return ok_object(present_lease(ent))


@app.route("/leases", methods=["GET"])
def list_leases():
    uid, role = require_auth()
    require_role(role, ALL_ROLES)
    landlord_id = request.args.get("landlord_id")
    leaseholder_id = request.args.get("leaseholder_id")
    status = request.args.get("status")
    rows = list(STORE["leases"].values())
    if landlord_id is not None:
        rows = [r for r in rows if r["landlord_id"] == landlord_id]
    if leaseholder_id is not None:
        rows = [r for r in rows if r["leaseholder_id"] == leaseholder_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return render_list(rows, present_lease)


@app.route("/leases/<lid>/submit-verification", methods=["POST"])
def submit_verification(lid):
    uid, role = require_auth()
    require_role(role, ["Landlord"])
    lease = get_or_404("leases", lid, "ERR_LEASE_NOT_FOUND")
    own_check(lease["landlord_id"], uid)
    if lease["status"] != "UNVERIFIED":
        raise ApiError("ERR_LEASE_NOT_VERIFIABLE")
    lease["status"] = "PENDING_REVIEW"
    touch(lease)
    return ok_object(present_lease(lease))


@app.route("/leases/<lid>/verify", methods=["POST"])
def verify_lease(lid):
    uid, role = require_auth()
    require_role(role, ["ComplianceOfficer"])
    body = get_body()
    decision = req_enum(body, "decision", ["VERIFIED", "REJECTED"])
    lease = get_or_404("leases", lid, "ERR_LEASE_NOT_FOUND")
    if lease["status"] != "PENDING_REVIEW":
        raise ApiError("ERR_LEASE_NOT_PENDING_REVIEW")
    lease["status"] = "VERIFIED" if decision == "VERIFIED" else "REJECTED"
    touch(lease)
    return ok_object(present_lease(lease))


@app.route("/leases/<lid>/amend", methods=["POST"])
def amend_lease(lid):
    uid, role = require_auth()
    require_role(role, ["Landlord"])
    body = get_body()
    monthly_rent = opt_int(body, "monthly_rent_cents", None, min_val=1)
    security_deposit = opt_int(body, "security_deposit_cents", None, min_val=0)
    lease = get_or_404("leases", lid, "ERR_LEASE_NOT_FOUND")
    own_check(lease["landlord_id"], uid)
    if lease["status"] != "VERIFIED":
        raise ApiError("ERR_LEASE_NOT_VERIFIED")
    if monthly_rent is not None:
        lease["monthly_rent_cents"] = monthly_rent
    if security_deposit is not None:
        lease["security_deposit_cents"] = security_deposit
    touch(lease)
    return ok_object(present_lease(lease))


# ===========================================================================
# Listings
# ===========================================================================
@app.route("/listings", methods=["POST"])
def create_listing():
    uid, role = require_auth()
    require_role(role, ["Leaseholder"])
    body = get_body()
    lease_id = req_str(body, "lease_id")
    listing_type = req_enum(body, "listing_type", ["SUBLET", "TAKEOVER"])
    asking_rent = req_int(body, "asking_rent_cents", min_val=1)
    available_from = parse_date(body, "available_from")
    available_to = parse_date(body, "available_to")
    min_term_months = opt_int(body, "min_term_months", 1, min_val=1)
    screening_policy = opt_enum(body, "screening_policy", ["STANDARD", "STRICT"], "STANDARD")
    # existence then ownership
    lease = get_or_404("leases", lease_id, "ERR_LEASE_NOT_FOUND")
    own_check(lease["leaseholder_id"], uid)
    if not (available_to > available_from):
        raise ApiError("ERR_INVALID_DATE_RANGE")
    ent = new_common()
    ent.update({
        "lease_id": lease_id,
        "listing_type": listing_type,
        "asking_rent_cents": asking_rent,
        "available_from": body["available_from"],
        "available_to": body["available_to"],
        "min_term_months": min_term_months,
        "screening_policy": screening_policy,
        "landlord_approval_note": "",
        "status": "DRAFT",
    })
    STORE["listings"][ent["id"]] = ent
    return ok_object(serialize(ent), 201)


@app.route("/listings/<lid>", methods=["GET"])
def get_listing(lid):
    uid, role = require_auth()
    require_role(role, ALL_ROLES)
    ent = get_or_404("listings", lid, "ERR_LISTING_NOT_FOUND")
    return ok_object(serialize(ent))


@app.route("/listings", methods=["GET"])
def list_listings():
    uid, role = require_auth()
    require_role(role, ALL_ROLES)
    lease_id = request.args.get("lease_id")
    status = request.args.get("status")
    rows = list(STORE["listings"].values())
    if lease_id is not None:
        rows = [r for r in rows if r["lease_id"] == lease_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return render_list(rows)


@app.route("/listings/<lid>/request-approval", methods=["POST"])
def request_approval(lid):
    uid, role = require_auth()
    require_role(role, ["Leaseholder"])
    listing = get_or_404("listings", lid, "ERR_LISTING_NOT_FOUND")
    lease = lease_of_listing(listing)
    own_check(lease["leaseholder_id"], uid)
    # state
    if listing["status"] != "DRAFT":
        raise ApiError("ERR_LISTING_NOT_DRAFT")
    # cross-entity referential: lease VERIFIED
    if lease["status"] != "VERIFIED":
        raise ApiError("ERR_LEASE_NOT_VERIFIED")
    # business constraint: listing_type allowed by lease flags
    if listing["listing_type"] == "SUBLET" and not lease["allows_sublet"]:
        raise ApiError("ERR_LISTING_TYPE_NOT_ALLOWED")
    if listing["listing_type"] == "TAKEOVER" and not lease["allows_assignment"]:
        raise ApiError("ERR_LISTING_TYPE_NOT_ALLOWED")
    listing["status"] = "PENDING_APPROVAL"
    touch(listing)
    return ok_object(serialize(listing))


@app.route("/listings/<lid>/approve", methods=["POST"])
def approve_listing(lid):
    uid, role = require_auth()
    require_role(role, ["Landlord"])
    body = get_body()
    note = opt_str(body, "landlord_approval_note", None)
    listing = get_or_404("listings", lid, "ERR_LISTING_NOT_FOUND")
    lease = lease_of_listing(listing)
    own_check(lease["landlord_id"], uid)
    if listing["status"] != "PENDING_APPROVAL":
        raise ApiError("ERR_LISTING_NOT_PENDING_APPROVAL")
    if note is not None:
        listing["landlord_approval_note"] = note
    listing["status"] = "OPEN"
    touch(listing)
    return ok_object(serialize(listing))


@app.route("/listings/<lid>/decline", methods=["POST"])
def decline_listing(lid):
    uid, role = require_auth()
    require_role(role, ["Landlord"])
    body = get_body()
    note = opt_str(body, "landlord_approval_note", None)
    listing = get_or_404("listings", lid, "ERR_LISTING_NOT_FOUND")
    lease = lease_of_listing(listing)
    own_check(lease["landlord_id"], uid)
    if listing["status"] != "PENDING_APPROVAL":
        raise ApiError("ERR_LISTING_NOT_PENDING_APPROVAL")
    if note is not None:
        listing["landlord_approval_note"] = note
    listing["status"] = "DECLINED"
    touch(listing)
    return ok_object(serialize(listing))


@app.route("/listings/<lid>/withdraw", methods=["POST"])
def withdraw_listing(lid):
    uid, role = require_auth()
    require_role(role, ["Leaseholder"])
    listing = get_or_404("listings", lid, "ERR_LISTING_NOT_FOUND")
    lease = lease_of_listing(listing)
    own_check(lease["leaseholder_id"], uid)
    if listing["status"] in ("CLOSED", "DECLINED", "WITHDRAWN"):
        raise ApiError("ERR_LISTING_NOT_WITHDRAWABLE")
    listing["status"] = "WITHDRAWN"
    touch(listing)
    services.withdraw_listing_cascade(listing)
    return ok_object(serialize(listing))


# ===========================================================================
# Applications
# ===========================================================================
@app.route("/applications", methods=["POST"])
def create_application():
    uid, role = require_auth()
    require_role(role, ["Applicant"])
    body = get_body()
    listing_id = req_str(body, "listing_id")
    applicant_id = req_str(body, "applicant_id")
    move_in = parse_date(body, "proposed_move_in_date")
    move_out = parse_date(body, "proposed_move_out_date")
    # ownership: applicant_id must be the caller
    own_check(applicant_id, uid)
    # existence left-to-right: listing then applicant
    listing = get_or_404("listings", listing_id, "ERR_LISTING_NOT_FOUND")
    get_or_404("applicants", applicant_id, "ERR_APPLICANT_NOT_FOUND")
    # state: listing OPEN
    if listing["status"] != "OPEN":
        raise ApiError("ERR_LISTING_NOT_OPEN")
    # referential: no duplicate non-terminal application on this listing
    for a in STORE["applications"].values():
        if (a["listing_id"] == listing_id and a["applicant_id"] == applicant_id
                and a["status"] in services.NON_TERMINAL_APP):
            raise ApiError("ERR_DUPLICATE_APPLICATION")
    # date range
    if not (move_out > move_in):
        raise ApiError("ERR_INVALID_DATE_RANGE")
    # availability window (inclusive)
    af = date(*[int(x) for x in listing["available_from"].split("-")])
    at = date(*[int(x) for x in listing["available_to"].split("-")])
    if move_in < af or move_out > at:
        raise ApiError("ERR_OUTSIDE_AVAILABILITY_WINDOW")
    # term length
    if services.months_between(move_in, move_out) < listing["min_term_months"]:
        raise ApiError("ERR_TERM_TOO_SHORT")
    ent = new_common()
    ent.update({
        "listing_id": listing_id,
        "applicant_id": applicant_id,
        "proposed_move_in_date": body["proposed_move_in_date"],
        "proposed_move_out_date": body["proposed_move_out_date"],
        "status": "SUBMITTED",
        "screening_result": "PENDING",
    })
    STORE["applications"][ent["id"]] = ent
    applicant = STORE["applicants"][applicant_id]
    touch(applicant)
    return ok_object(serialize(ent), 201)


@app.route("/applications/<aid>", methods=["GET"])
def get_application(aid):
    uid, role = require_auth()
    require_role(role, ALL_ROLES)
    ent = get_or_404("applications", aid, "ERR_APPLICATION_NOT_FOUND")
    return ok_object(serialize(ent))


@app.route("/applications", methods=["GET"])
def list_applications():
    uid, role = require_auth()
    require_role(role, ALL_ROLES)
    listing_id = request.args.get("listing_id")
    applicant_id = request.args.get("applicant_id")
    status = request.args.get("status")
    rows = list(STORE["applications"].values())
    if listing_id is not None:
        rows = [r for r in rows if r["listing_id"] == listing_id]
    if applicant_id is not None:
        rows = [r for r in rows if r["applicant_id"] == applicant_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return render_list(rows)


@app.route("/applications/<aid>/start-screening", methods=["POST"])
def start_screening(aid):
    uid, role = require_auth()
    require_role(role, ["ComplianceOfficer"])
    app_ = get_or_404("applications", aid, "ERR_APPLICATION_NOT_FOUND")
    if app_["status"] != "SUBMITTED":
        raise ApiError("ERR_APPLICATION_NOT_SCREENABLE")
    app_["status"] = "SCREENING"
    touch(app_)
    return ok_object(serialize(app_))


@app.route("/applications/<aid>/request-info", methods=["POST"])
def request_info(aid):
    uid, role = require_auth()
    require_role(role, ["ComplianceOfficer"])
    app_ = get_or_404("applications", aid, "ERR_APPLICATION_NOT_FOUND")
    if app_["status"] != "SCREENING":
        raise ApiError("ERR_APPLICATION_NOT_IN_SCREENING")
    app_["status"] = "INFO_REQUESTED"
    touch(app_)
    return ok_object(serialize(app_))


@app.route("/applications/<aid>/resubmit-info", methods=["POST"])
def resubmit_info(aid):
    uid, role = require_auth()
    require_role(role, ["Applicant"])
    app_ = get_or_404("applications", aid, "ERR_APPLICATION_NOT_FOUND")
    own_check(app_["applicant_id"], uid)
    if app_["status"] != "INFO_REQUESTED":
        raise ApiError("ERR_APPLICATION_NOT_INFO_REQUESTED")
    app_["status"] = "SCREENING"
    touch(app_)
    return ok_object(serialize(app_))


@app.route("/applications/<aid>/screening-report", methods=["POST"])
def create_screening_report(aid):
    uid, role = require_auth()
    require_role(role, ["ComplianceOfficer"])
    body = get_body()
    credit_score = req_int(body, "credit_score", min_val=300, max_val=850)
    income_verified = body.get("income_verified")
    if not isinstance(income_verified, bool):
        raise ApiError("ERR_VALIDATION", "Invalid boolean: income_verified")
    app_ = get_or_404("applications", aid, "ERR_APPLICATION_NOT_FOUND")
    if app_["status"] != "SCREENING":
        raise ApiError("ERR_APPLICATION_NOT_IN_SCREENING")
    listing = STORE["listings"][app_["listing_id"]]
    lease = STORE["leases"][listing["lease_id"]]
    applicant = STORE["applicants"][app_["applicant_id"]]
    if listing["listing_type"] == "SUBLET":
        eff_rent = listing["asking_rent_cents"]
    else:
        eff_rent = lease["monthly_rent_cents"]
    annual_income = applicant["annual_income_cents"]
    policy = listing["screening_policy"]
    affordability, multiple, result = services.compute_qualification(annual_income, eff_rent, policy)
    ent = new_common()
    ent.update({
        "application_id": aid,
        "credit_score": credit_score,
        "income_verified": income_verified,
        "applicant_annual_income_cents": annual_income,
        "effective_monthly_rent_cents": eff_rent,
        "screening_policy": policy,
        "affordability_ratio": affordability,
        "income_multiple": multiple,
        "qualification_result": result,
    })
    STORE["screening_reports"][ent["id"]] = ent
    app_["status"] = "SCREENED"
    app_["screening_result"] = result
    touch(app_)
    return ok_object(serialize(ent), 201)


@app.route("/applications/<aid>/screening-report", methods=["GET"])
def list_screening_reports(aid):
    uid, role = require_auth()
    require_role(role, ALL_ROLES)
    get_or_404("applications", aid, "ERR_APPLICATION_NOT_FOUND")
    rows = [r for r in STORE["screening_reports"].values() if r["application_id"] == aid]
    return render_list(rows)


@app.route("/applications/<aid>/match", methods=["POST"])
def match_application(aid):
    uid, role = require_auth()
    require_role(role, ["ComplianceOfficer"])
    app_ = get_or_404("applications", aid, "ERR_APPLICATION_NOT_FOUND")
    if app_["status"] != "SCREENED":
        raise ApiError("ERR_APPLICATION_NOT_SCREENED")
    if app_["screening_result"] != "PASS":
        raise ApiError("ERR_SCREENING_NOT_PASSED")
    listing = STORE["listings"][app_["listing_id"]]
    if listing["status"] != "OPEN":
        raise ApiError("ERR_LISTING_NOT_OPEN")
    app_["status"] = "MATCHED"
    touch(app_)
    applicant = STORE["applicants"].get(app_["applicant_id"])
    if applicant is not None:
        touch(applicant)
    return ok_object(serialize(app_))


@app.route("/applications/<aid>/decline", methods=["POST"])
def decline_application(aid):
    uid, role = require_auth()
    require_role(role, ["ComplianceOfficer"])
    app_ = get_or_404("applications", aid, "ERR_APPLICATION_NOT_FOUND")
    if app_["status"] in ("MATCHED", "DECLINED", "WITHDRAWN"):
        raise ApiError("ERR_APPLICATION_NOT_ACTIONABLE")
    app_["status"] = "DECLINED"
    touch(app_)
    applicant = STORE["applicants"].get(app_["applicant_id"])
    if applicant is not None:
        touch(applicant)
    return ok_object(serialize(app_))


@app.route("/applications/<aid>/withdraw", methods=["POST"])
def withdraw_application(aid):
    uid, role = require_auth()
    require_role(role, ["Applicant"])
    app_ = get_or_404("applications", aid, "ERR_APPLICATION_NOT_FOUND")
    own_check(app_["applicant_id"], uid)
    if app_["status"] in ("MATCHED", "DECLINED", "WITHDRAWN"):
        raise ApiError("ERR_APPLICATION_NOT_ACTIONABLE")
    app_["status"] = "WITHDRAWN"
    touch(app_)
    applicant = STORE["applicants"].get(app_["applicant_id"])
    if applicant is not None:
        touch(applicant)
    return ok_object(serialize(app_))


# ===========================================================================
# Agreements
# ===========================================================================
def _ymd(s):
    return date(*[int(x) for x in s.split("-")])


def _intervals_overlap(s1, e1, s2, e2):
    # closed intervals; touching endpoints conflict
    return s1 <= e2 and s2 <= e1


@app.route("/agreements", methods=["POST"])
def create_agreement():
    uid, role = require_auth()
    require_role(role, ["Leaseholder"])
    body = get_body()
    application_id = req_str(body, "application_id")
    expected_version = req_int(body, "expected_listing_version")
    occ_start = parse_date(body, "occupancy_start_date")
    occ_end = parse_date(body, "occupancy_end_date")
    # existence
    app_ = get_or_404("applications", application_id, "ERR_APPLICATION_NOT_FOUND")
    listing = STORE["listings"][app_["listing_id"]]
    lease = STORE["leases"][listing["lease_id"]]
    # ownership
    own_check(lease["leaseholder_id"], uid)
    # state: application MATCHED
    if app_["status"] != "MATCHED":
        raise ApiError("ERR_APPLICATION_NOT_MATCHED")
    # screening gate
    if app_["screening_result"] != "PASS":
        raise ApiError("ERR_SCREENING_NOT_PASSED")
    # date range
    if not (occ_end > occ_start):
        raise ApiError("ERR_INVALID_DATE_RANGE")
    # occupancy overlap with EXECUTED/ACTIVE agreements on same lease
    for ag in STORE["agreements"].values():
        if ag["lease_id"] == lease["id"] and ag["status"] in ("EXECUTED", "ACTIVE"):
            if _intervals_overlap(occ_start, occ_end,
                                  _ymd(ag["occupancy_start_date"]), _ymd(ag["occupancy_end_date"])):
                raise ApiError("ERR_OCCUPANCY_OVERLAP")
    # OCC
    if expected_version != listing["version"]:
        raise ApiError("ERR_STALE_LISTING_VERSION")
    # supersede prior non-terminal agreements on the same listing
    for ag in list(STORE["agreements"].values()):
        if ag["listing_id"] == listing["id"] and ag["status"] in ("DRAFT", "PENDING_SIGNATURES", "EXECUTED"):
            services.void_agreement(ag)
    # bump listing version (OCC)
    touch(listing)
    # create agreement
    ent = new_common()
    ent.update({
        "application_id": application_id,
        "listing_id": listing["id"],
        "lease_id": lease["id"],
        "agreement_type": listing["listing_type"],
        "occupancy_start_date": body["occupancy_start_date"],
        "occupancy_end_date": body["occupancy_end_date"],
        "status": "DRAFT",
    })
    STORE["agreements"][ent["id"]] = ent
    # auto-create settlement
    st = new_common()
    st.update({
        "agreement_id": ent["id"],
        "agreement_type": ent["agreement_type"],
        "funded_amount_cents": 0,
        "deposit_held_cents": 0,
        "handoff_date": None,
        "status": "PENDING",
    })
    services.compute_settlement_financials(st, ent, listing, lease)
    STORE["settlements"][st["id"]] = st
    return ok_object(present_agreement(ent), 201)


@app.route("/agreements/<aid>", methods=["GET"])
def get_agreement(aid):
    uid, role = require_auth()
    require_role(role, ALL_ROLES)
    ent = get_or_404("agreements", aid, "ERR_AGREEMENT_NOT_FOUND")
    return ok_object(present_agreement(ent))


@app.route("/agreements", methods=["GET"])
def list_agreements():
    uid, role = require_auth()
    require_role(role, ALL_ROLES)
    application_id = request.args.get("application_id")
    listing_id = request.args.get("listing_id")
    lease_id = request.args.get("lease_id")
    status = request.args.get("status")
    rows = list(STORE["agreements"].values())
    if application_id is not None:
        rows = [r for r in rows if r["application_id"] == application_id]
    if listing_id is not None:
        rows = [r for r in rows if r["listing_id"] == listing_id]
    if lease_id is not None:
        rows = [r for r in rows if r["lease_id"] == lease_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return render_list(rows, present_agreement)


@app.route("/agreements/<aid>/send-for-signature", methods=["POST"])
def send_for_signature(aid):
    uid, role = require_auth()
    require_role(role, ["Leaseholder"])
    ag = get_or_404("agreements", aid, "ERR_AGREEMENT_NOT_FOUND")
    lease = lease_of_agreement(ag)
    own_check(lease["leaseholder_id"], uid)
    if ag["status"] != "DRAFT":
        raise ApiError("ERR_AGREEMENT_NOT_DRAFT")
    ag["status"] = "PENDING_SIGNATURES"
    touch(ag)
    return ok_object(present_agreement(ag))


SIGNER_ROLE_FOR = {"Landlord": "LANDLORD", "Leaseholder": "LEASEHOLDER", "Applicant": "APPLICANT"}


@app.route("/agreements/<aid>/signatures", methods=["POST"])
def add_signature(aid):
    uid, role = require_auth()
    require_role(role, ["Landlord", "Leaseholder", "Applicant"])
    body = get_body()
    signer_role = req_str(body, "signer_role")
    ag = get_or_404("agreements", aid, "ERR_AGREEMENT_NOT_FOUND")
    lease = lease_of_agreement(ag)
    application = STORE["applications"][ag["application_id"]]
    # ownership: acting party must be the agreement's party for their role
    if role == "Landlord":
        own_check(lease["landlord_id"], uid)
    elif role == "Leaseholder":
        own_check(lease["leaseholder_id"], uid)
    else:  # Applicant
        own_check(application["applicant_id"], uid)
    # state
    if ag["status"] != "PENDING_SIGNATURES":
        raise ApiError("ERR_AGREEMENT_NOT_PENDING_SIGNATURES")
    # signer_role legality: must match acting role (and thus be in required set)
    if signer_role != SIGNER_ROLE_FOR[role]:
        raise ApiError("ERR_INVALID_SIGNER_ROLE")
    # duplicate
    for s in STORE["signatures"].values():
        if s["agreement_id"] == aid and s["signer_role"] == signer_role:
            raise ApiError("ERR_DUPLICATE_SIGNATURE")
    sig = new_common(with_common=False)
    sig.update({
        "agreement_id": aid,
        "signer_role": signer_role,
        "signer_id": uid,
        "signed_at": now_iso(),
    })
    STORE["signatures"][sig["id"]] = sig
    # execution when fully signed
    collected = presenters.collected_roles_for(aid)
    if set(presenters.REQUIRED_SIGNER_ROLES).issubset(set(collected)):
        services.execute_agreement(ag)
        touch(ag)
    else:
        touch(ag)
    return ok_object(serialize(sig), 201)


@app.route("/agreements/<aid>/signatures", methods=["GET"])
def list_signatures(aid):
    uid, role = require_auth()
    require_role(role, ALL_ROLES)
    get_or_404("agreements", aid, "ERR_AGREEMENT_NOT_FOUND")
    rows = [r for r in STORE["signatures"].values() if r["agreement_id"] == aid]
    return render_list(rows)


@app.route("/agreements/<aid>/activate", methods=["POST"])
def activate_agreement(aid):
    uid, role = require_auth()
    require_role(role, ["Leaseholder"])
    ag = get_or_404("agreements", aid, "ERR_AGREEMENT_NOT_FOUND")
    lease = lease_of_agreement(ag)
    own_check(lease["leaseholder_id"], uid)
    if ag["status"] != "EXECUTED":
        raise ApiError("ERR_AGREEMENT_NOT_EXECUTED")
    settlement = _settlement_of(aid)
    if settlement is None or settlement["status"] != "FUNDED":
        raise ApiError("ERR_SETTLEMENT_NOT_FUNDED")
    ag["status"] = "ACTIVE"
    touch(ag)
    return ok_object(present_agreement(ag))


@app.route("/agreements/<aid>/complete", methods=["POST"])
def complete_agreement(aid):
    uid, role = require_auth()
    require_role(role, ["Leaseholder", "ComplianceOfficer"])
    ag = get_or_404("agreements", aid, "ERR_AGREEMENT_NOT_FOUND")
    lease = lease_of_agreement(ag)
    if role == "Leaseholder":
        own_check(lease["leaseholder_id"], uid)
    if ag["status"] != "ACTIVE":
        raise ApiError("ERR_AGREEMENT_NOT_ACTIVE")
    settlement = _settlement_of(aid)
    if settlement is None or settlement["status"] != "HANDED_OFF":
        raise ApiError("ERR_SETTLEMENT_NOT_HANDED_OFF")
    # cascade
    ag["status"] = "COMPLETED"
    touch(ag)
    settlement["status"] = "RELEASED"
    settlement["deposit_held_cents"] = 0
    touch(settlement)
    if lease is not None:
        lease["active_occupancy_count"] = services.lease_occupancy_count(lease["id"])
        touch(lease)
    listing = STORE["listings"].get(ag["listing_id"])
    if listing is not None and listing["status"] in ("OPEN", "MATCHED"):
        listing["status"] = "CLOSED"
        touch(listing)
    return ok_object(present_agreement(ag))


@app.route("/agreements/<aid>/void", methods=["POST"])
def void_agreement_endpoint(aid):
    uid, role = require_auth()
    require_role(role, ["Leaseholder"])
    ag = get_or_404("agreements", aid, "ERR_AGREEMENT_NOT_FOUND")
    lease = lease_of_agreement(ag)
    own_check(lease["leaseholder_id"], uid)
    if ag["status"] not in ("DRAFT", "PENDING_SIGNATURES", "EXECUTED"):
        raise ApiError("ERR_AGREEMENT_NOT_VOIDABLE")
    services.void_agreement(ag)
    return ok_object(present_agreement(ag))


def _settlement_of(agreement_id):
    for s in STORE["settlements"].values():
        if s["agreement_id"] == agreement_id:
            return s
    return None


# ===========================================================================
# Settlements
# ===========================================================================
def _owner_ids_for_settlement(settlement):
    ag = STORE["agreements"][settlement["agreement_id"]]
    lease = STORE["leases"][ag["lease_id"]]
    application = STORE["applications"][ag["application_id"]]
    return ag, lease, application


@app.route("/settlements/<sid>", methods=["GET"])
def get_settlement(sid):
    uid, role = require_auth()
    require_role(role, ALL_ROLES)
    ent = get_or_404("settlements", sid, "ERR_SETTLEMENT_NOT_FOUND")
    return ok_object(serialize(ent))


@app.route("/settlements", methods=["GET"])
def list_settlements():
    uid, role = require_auth()
    require_role(role, ALL_ROLES)
    agreement_id = request.args.get("agreement_id")
    status = request.args.get("status")
    rows = list(STORE["settlements"].values())
    if agreement_id is not None:
        rows = [r for r in rows if r["agreement_id"] == agreement_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return render_list(rows)


@app.route("/settlements/<sid>/fund", methods=["POST"])
def fund_settlement(sid):
    uid, role = require_auth()
    require_role(role, ["Applicant"])
    settlement = get_or_404("settlements", sid, "ERR_SETTLEMENT_NOT_FOUND")
    ag, lease, application = _owner_ids_for_settlement(settlement)
    own_check(application["applicant_id"], uid)
    if settlement["status"] != "PENDING":
        raise ApiError("ERR_SETTLEMENT_NOT_PENDING")
    body = get_body()
    funded = req_int(body, "funded_amount_cents", min_val=0)
    if funded != settlement["total_move_in_cents"]:
        raise ApiError("ERR_FUNDING_AMOUNT_MISMATCH")
    settlement["funded_amount_cents"] = funded
    settlement["status"] = "FUNDED"
    settlement["deposit_held_cents"] = settlement["deposit_amount_cents"]
    touch(settlement)
    return ok_object(serialize(settlement))


@app.route("/settlements/<sid>/handoff", methods=["POST"])
def handoff_settlement(sid):
    uid, role = require_auth()
    require_role(role, ["Leaseholder"])
    settlement = get_or_404("settlements", sid, "ERR_SETTLEMENT_NOT_FOUND")
    ag, lease, application = _owner_ids_for_settlement(settlement)
    own_check(lease["leaseholder_id"], uid)
    if settlement["status"] != "FUNDED":
        raise ApiError("ERR_SETTLEMENT_NOT_FUNDED")
    if ag["status"] != "ACTIVE":
        raise ApiError("ERR_AGREEMENT_NOT_ACTIVE")
    body = get_body()
    handoff_date = parse_date(body, "handoff_date")
    settlement["handoff_date"] = body["handoff_date"]
    settlement["final_prorated_first_rent_cents"] = services.prorate(
        settlement["base_monthly_rent_cents"], handoff_date)
    settlement["status"] = "HANDED_OFF"
    touch(settlement)
    return ok_object(serialize(settlement))


@app.route("/settlements/<sid>/release", methods=["POST"])
def release_settlement(sid):
    uid, role = require_auth()
    require_role(role, ["ComplianceOfficer"])
    settlement = get_or_404("settlements", sid, "ERR_SETTLEMENT_NOT_FOUND")
    if settlement["status"] != "HANDED_OFF":
        raise ApiError("ERR_SETTLEMENT_NOT_HANDED_OFF")
    settlement["status"] = "RELEASED"
    settlement["deposit_held_cents"] = 0
    touch(settlement)
    return ok_object(serialize(settlement))


# ===========================================================================
# Handoff appointments (landlord calendar)
# ===========================================================================
@app.route("/handoff-appointments", methods=["POST"])
def create_appointment():
    uid, role = require_auth()
    require_role(role, ["Landlord"])
    body = get_body()
    agreement_id = req_str(body, "agreement_id")
    scheduled_start = parse_datetime_field(body, "scheduled_start")
    scheduled_end = parse_datetime_field(body, "scheduled_end")
    ag = get_or_404("agreements", agreement_id, "ERR_AGREEMENT_NOT_FOUND")
    lease = lease_of_agreement(ag)
    own_check(lease["landlord_id"], uid)
    if ag["status"] not in ("EXECUTED", "ACTIVE"):
        raise ApiError("ERR_AGREEMENT_NOT_READY_FOR_HANDOFF")
    if not (scheduled_end > scheduled_start):
        raise ApiError("ERR_INVALID_DATE_RANGE")
    buffer = timedelta(minutes=services.HANDOFF_BUFFER_MINUTES)
    landlord_id = lease["landlord_id"]
    for ap in STORE["appointments"].values():
        if ap["landlord_id"] != landlord_id or ap["status"] != "SCHEDULED":
            continue
        es = parse_iso_datetime(ap["scheduled_start"])
        ee = parse_iso_datetime(ap["scheduled_end"])
        clear = scheduled_end <= es - buffer or scheduled_start >= ee + buffer
        if not clear:
            raise ApiError("ERR_APPOINTMENT_CONFLICT")
    ent = new_common()
    ent.update({
        "agreement_id": agreement_id,
        "landlord_id": landlord_id,
        "scheduled_start": body["scheduled_start"],
        "scheduled_end": body["scheduled_end"],
        "status": "SCHEDULED",
    })
    STORE["appointments"][ent["id"]] = ent
    return ok_object(serialize(ent), 201)


@app.route("/handoff-appointments/<apid>", methods=["GET"])
def get_appointment(apid):
    uid, role = require_auth()
    require_role(role, ALL_ROLES)
    ent = get_or_404("appointments", apid, "ERR_APPOINTMENT_NOT_FOUND")
    return ok_object(serialize(ent))


@app.route("/handoff-appointments", methods=["GET"])
def list_appointments():
    uid, role = require_auth()
    require_role(role, ALL_ROLES)
    agreement_id = request.args.get("agreement_id")
    landlord_id = request.args.get("landlord_id")
    status = request.args.get("status")
    rows = list(STORE["appointments"].values())
    if agreement_id is not None:
        rows = [r for r in rows if r["agreement_id"] == agreement_id]
    if landlord_id is not None:
        rows = [r for r in rows if r["landlord_id"] == landlord_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return render_list(rows)


@app.route("/handoff-appointments/<apid>/complete", methods=["POST"])
def complete_appointment(apid):
    uid, role = require_auth()
    require_role(role, ["Landlord"])
    ent = get_or_404("appointments", apid, "ERR_APPOINTMENT_NOT_FOUND")
    own_check(ent["landlord_id"], uid)
    if ent["status"] != "SCHEDULED":
        raise ApiError("ERR_APPOINTMENT_NOT_SCHEDULED")
    ent["status"] = "COMPLETED"
    touch(ent)
    return ok_object(serialize(ent))


@app.route("/handoff-appointments/<apid>/cancel", methods=["POST"])
def cancel_appointment(apid):
    uid, role = require_auth()
    require_role(role, ["Landlord"])
    ent = get_or_404("appointments", apid, "ERR_APPOINTMENT_NOT_FOUND")
    own_check(ent["landlord_id"], uid)
    if ent["status"] != "SCHEDULED":
        raise ApiError("ERR_APPOINTMENT_NOT_SCHEDULED")
    ent["status"] = "CANCELLED"
    touch(ent)
    return ok_object(serialize(ent))


# ===========================================================================
# Disputes
# ===========================================================================
@app.route("/disputes", methods=["POST"])
def create_dispute():
    uid, role = require_auth()
    require_role(role, ["Leaseholder", "Applicant"])
    body = get_body()
    agreement_id = req_str(body, "agreement_id")
    raised_by = req_enum(body, "raised_by", ["LEASEHOLDER", "APPLICANT"])
    reason = req_str(body, "reason")
    ag = get_or_404("agreements", agreement_id, "ERR_AGREEMENT_NOT_FOUND")
    lease = lease_of_agreement(ag)
    application = STORE["applications"][ag["application_id"]]
    if role == "Leaseholder":
        own_check(lease["leaseholder_id"], uid)
    else:  # Applicant
        own_check(application["applicant_id"], uid)
    if ag["status"] != "ACTIVE":
        raise ApiError("ERR_AGREEMENT_NOT_ACTIVE")
    ent = new_common()
    ent.update({
        "agreement_id": agreement_id,
        "raised_by": raised_by,
        "reason": reason,
        "status": "FILED",
        "outcome": None,
        "resolution_amount_cents": 0,
    })
    STORE["disputes"][ent["id"]] = ent
    return ok_object(serialize(ent), 201)


@app.route("/disputes/<did>", methods=["GET"])
def get_dispute(did):
    uid, role = require_auth()
    require_role(role, ALL_ROLES)
    ent = get_or_404("disputes", did, "ERR_DISPUTE_NOT_FOUND")
    return ok_object(serialize(ent))


@app.route("/disputes", methods=["GET"])
def list_disputes():
    uid, role = require_auth()
    require_role(role, ALL_ROLES)
    agreement_id = request.args.get("agreement_id")
    status = request.args.get("status")
    rows = list(STORE["disputes"].values())
    if agreement_id is not None:
        rows = [r for r in rows if r["agreement_id"] == agreement_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return render_list(rows)


@app.route("/disputes/<did>/review", methods=["POST"])
def review_dispute(did):
    uid, role = require_auth()
    require_role(role, ["ComplianceOfficer"])
    ent = get_or_404("disputes", did, "ERR_DISPUTE_NOT_FOUND")
    if ent["status"] != "FILED":
        raise ApiError("ERR_DISPUTE_NOT_FILED")
    ent["status"] = "UNDER_REVIEW"
    touch(ent)
    return ok_object(serialize(ent))


@app.route("/disputes/<did>/resolve", methods=["POST"])
def resolve_dispute(did):
    uid, role = require_auth()
    require_role(role, ["ComplianceOfficer"])
    ent = get_or_404("disputes", did, "ERR_DISPUTE_NOT_FOUND")
    if ent["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_DISPUTE_NOT_UNDER_REVIEW")
    body = get_body()
    outcome = req_enum(body, "outcome",
                       ["RESOLVED_LEASEHOLDER", "RESOLVED_APPLICANT", "RESOLVED_SPLIT", "DISMISSED"],
                       error_id="ERR_INVALID_DISPUTE_OUTCOME")
    resolution_amount = opt_int(body, "resolution_amount_cents", 0, min_val=0)
    ent["resolution_amount_cents"] = resolution_amount
    ent["outcome"] = outcome
    ent["status"] = outcome
    touch(ent)
    ag = STORE["agreements"][ent["agreement_id"]]
    settlement = _settlement_of(ag["id"])
    if outcome == "RESOLVED_APPLICANT":
        if ag["status"] == "ACTIVE":
            services.terminate_agreement(ag)
    elif outcome == "RESOLVED_LEASEHOLDER":
        if (settlement is not None and settlement["status"] == "HANDED_OFF"
                and resolution_amount == settlement["deposit_amount_cents"]):
            settlement["status"] = "FORFEITED"
            settlement["deposit_held_cents"] = 0
            touch(settlement)
    # RESOLVED_SPLIT / DISMISSED: no settlement state change
    return ok_object(serialize(ent))


# ===========================================================================
# Fees
# ===========================================================================
@app.route("/fees", methods=["POST"])
def create_fee():
    uid, role = require_auth()
    require_role(role, ["PlatformAdmin"])
    body = get_body()
    agreement_id = req_str(body, "agreement_id")
    fee_type = req_enum(body, "fee_type", ["PLATFORM", "SCREENING", "CANCELLATION", "LATE"])
    amount = req_int(body, "amount_cents", min_val=0)
    get_or_404("agreements", agreement_id, "ERR_AGREEMENT_NOT_FOUND")
    ent = new_common()
    ent.update({
        "agreement_id": agreement_id,
        "fee_type": fee_type,
        "amount_cents": amount,
        "status": "PENDING",
    })
    STORE["fees"][ent["id"]] = ent
    return ok_object(serialize(ent), 201)


@app.route("/fees/<fid>", methods=["GET"])
def get_fee(fid):
    uid, role = require_auth()
    require_role(role, ALL_ROLES)
    ent = get_or_404("fees", fid, "ERR_FEE_NOT_FOUND")
    return ok_object(serialize(ent))


@app.route("/fees", methods=["GET"])
def list_fees():
    uid, role = require_auth()
    require_role(role, ALL_ROLES)
    agreement_id = request.args.get("agreement_id")
    status = request.args.get("status")
    rows = list(STORE["fees"].values())
    if agreement_id is not None:
        rows = [r for r in rows if r["agreement_id"] == agreement_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return render_list(rows)


@app.route("/fees/<fid>/charge", methods=["POST"])
def charge_fee(fid):
    uid, role = require_auth()
    require_role(role, ["PlatformAdmin"])
    ent = get_or_404("fees", fid, "ERR_FEE_NOT_FOUND")
    if ent["status"] != "PENDING":
        raise ApiError("ERR_FEE_NOT_PENDING")
    ent["status"] = "CHARGED"
    touch(ent)
    return ok_object(serialize(ent))


@app.route("/fees/<fid>/waive", methods=["POST"])
def waive_fee(fid):
    uid, role = require_auth()
    require_role(role, ["PlatformAdmin"])
    ent = get_or_404("fees", fid, "ERR_FEE_NOT_FOUND")
    if ent["status"] != "PENDING":
        raise ApiError("ERR_FEE_NOT_PENDING")
    ent["status"] = "WAIVED"
    touch(ent)
    return ok_object(serialize(ent))


@app.route("/fees/<fid>/refund", methods=["POST"])
def refund_fee(fid):
    uid, role = require_auth()
    require_role(role, ["PlatformAdmin"])
    ent = get_or_404("fees", fid, "ERR_FEE_NOT_FOUND")
    if ent["status"] != "CHARGED":
        raise ApiError("ERR_FEE_NOT_CHARGED")
    ent["status"] = "REFUNDED"
    touch(ent)
    return ok_object(serialize(ent))


# ===========================================================================
# Entry point
# ===========================================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
