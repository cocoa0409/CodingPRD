"""Window & Door Replacement API — Flask entry point.

In-memory only. No seeding. Logical clock defaults to 2026-04-01T00:00:00Z.
"""
import os

from flask import Flask, request

import errors
import calculations
import services
import serializers as S
from db import db, stamp_create, touch
from clock import clock, parse_iso8601, format_iso8601, add_days
from response import success, error_response
from middleware import get_auth, require_role
import validation as V

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Role sets per operation, used by require_role(role, allowed)
# ---------------------------------------------------------------------------
ALL_AUTH = {"Homeowner", "SalesConsultant", "OperationsCoordinator", "ServiceTech", "PlatformAdmin"}


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------
@app.errorhandler(errors.ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.message), e.http_status


@app.errorhandler(404)
def handle_404(e):
    return error_response(errors.ERR_NOT_FOUND, "resource not found"), 404


@app.errorhandler(405)
def handle_405(e):
    return error_response(errors.ERR_NOT_FOUND, "method not allowed"), 404


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, errors.ApiError):
        return handle_api_error(e)
    return error_response("ERR_INTERNAL", str(e)), 500


# ---------------------------------------------------------------------------
# Lookup helpers — raise ERR_NOT_FOUND (path) in left-to-right order
# ---------------------------------------------------------------------------
def get_project_or_404(pid):
    p = db.projects.get(pid)
    if p is None:
        raise errors.err(errors.ERR_NOT_FOUND, "project not found")
    return p


def get_consultation_in_project(pid, cid):
    c = db.consultations.get(cid)
    if c is None or c["project_id"] != pid:
        raise errors.err(errors.ERR_NOT_FOUND, "consultation not found")
    return c


def get_quote_in_project(pid, qid):
    q = db.quotes.get(qid)
    if q is None or q["project_id"] != pid:
        raise errors.err(errors.ERR_NOT_FOUND, "quote not found")
    return q


def get_financing_in_quote(qid, fid):
    f = db.financing_applications.get(fid)
    if f is None or f["quote_id"] != qid:
        raise errors.err(errors.ERR_NOT_FOUND, "financing application not found")
    return f


def get_manufacture_in_project(pid, mid):
    m = db.manufacture_orders.get(mid)
    if m is None or m["project_id"] != pid:
        raise errors.err(errors.ERR_NOT_FOUND, "manufacture order not found")
    return m


def get_install_in_project(pid, jid):
    j = db.install_jobs.get(jid)
    if j is None or j["project_id"] != pid:
        raise errors.err(errors.ERR_NOT_FOUND, "install job not found")
    return j


def get_permit_in_project(pid, permid):
    p = db.permits.get(permid)
    if p is None or p["project_id"] != pid:
        raise errors.err(errors.ERR_NOT_FOUND, "permit not found")
    return p


def get_ticket_in_project(pid, sid):
    t = db.service_tickets.get(sid)
    if t is None or t["project_id"] != pid:
        raise errors.err(errors.ERR_NOT_FOUND, "service ticket not found")
    return t


def ensure_owner(project, user_id):
    """Priority 4: Homeowner acting on a project must own it."""
    if project["homeowner_id"] != user_id:
        raise errors.err(errors.ERR_NOT_PROJECT_OWNER, "homeowner does not own this project")


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _, role = get_auth()
    require_role(role, {"PlatformAdmin"})
    body = V.get_body()
    V.require_fields(body, ["to_iso8601"])
    dt = parse_iso8601(body.get("to_iso8601"))
    if dt is None:
        raise errors.err(errors.ERR_INVALID_REQUEST, "to_iso8601 must be a valid ISO 8601 UTC instant")
    clock.set(dt)
    services.expire_all_quotes()
    return success({}, 200)


# ---------------------------------------------------------------------------
# Homeowner
# ---------------------------------------------------------------------------
@app.route("/homeowners", methods=["POST"])
def create_homeowner():
    _, role = get_auth()
    require_role(role, {"SalesConsultant", "PlatformAdmin"})
    body = V.get_body()
    full_name = V.require_string(body, "full_name")
    email = V.require_string(body, "email")
    property_zip = V.require_string(body, "property_zip")
    agi_band = body.get("agi_band", "STANDARD")
    if agi_band is None:
        agi_band = "STANDARD"
    if agi_band not in {"LOW", "STANDARD", "HIGH"}:
        raise errors.err(errors.ERR_INVALID_REQUEST, "agi_band must be one of LOW, STANDARD, HIGH")
    # email must be unique across homeowners
    for h in db.homeowners.values():
        if h["email"] == email:
            raise errors.err(errors.ERR_INVALID_REQUEST, "email must be unique")
    rec = {
        "full_name": full_name,
        "email": email,
        "property_zip": property_zip,
        "agi_band": agi_band,
        "referral_credit_cents": 0,
    }
    stamp_create(rec)
    db.homeowners[rec["id"]] = rec
    return success(S.homeowner_out(rec), 201)


@app.route("/homeowners/<hid>", methods=["GET"])
def get_homeowner(hid):
    _, role = get_auth()
    require_role(role, ALL_AUTH)
    h = db.homeowners.get(hid)
    if h is None:
        raise errors.err(errors.ERR_NOT_FOUND, "homeowner not found")
    return success(S.homeowner_out(h), 200)


# ---------------------------------------------------------------------------
# Project
# ---------------------------------------------------------------------------
def derive_jurisdiction(property_zip):
    first = property_zip[0] if property_zip else ""
    if first == "9":
        return "WEST_STRICT"
    if first in ("0", "1"):
        return "NORTHEAST_STD"
    return "CENTRAL_LIGHT"


@app.route("/projects", methods=["POST"])
def create_project():
    _, role = get_auth()
    require_role(role, {"SalesConsultant", "PlatformAdmin"})
    body = V.get_body()
    homeowner_id = body.get("homeowner_id")
    if not isinstance(homeowner_id, str) or homeowner_id == "":
        raise errors.err(errors.ERR_INVALID_REQUEST, "homeowner_id is required")
    homeowner = db.homeowners.get(homeowner_id)
    if homeowner is None:
        raise errors.err(errors.ERR_REFERENCE_NOT_FOUND, "homeowner_id does not reference an existing homeowner")
    rec = {
        "homeowner_id": homeowner_id,
        "jurisdiction_code": derive_jurisdiction(homeowner["property_zip"]),
        "status": "LEAD",
        "accepted_quote_id": None,
    }
    stamp_create(rec)
    db.projects[rec["id"]] = rec
    return success(S.project_out(rec), 201)


@app.route("/projects/<pid>", methods=["GET"])
def get_project(pid):
    _, role = get_auth()
    require_role(role, {"SalesConsultant", "OperationsCoordinator", "ServiceTech", "Homeowner", "PlatformAdmin"})
    p = get_project_or_404(pid)
    services.expire_project_quotes(p)
    return success(S.project_out(p), 200)


@app.route("/projects", methods=["GET"])
def list_projects():
    _, role = get_auth()
    require_role(role, {"SalesConsultant", "OperationsCoordinator", "ServiceTech", "PlatformAdmin"})
    limit, offset = V.parse_pagination()
    items = list(db.projects.values())
    homeowner_id = request.args.get("homeowner_id")
    accepted_quote_id = request.args.get("accepted_quote_id")
    if homeowner_id is not None:
        items = [p for p in items if p["homeowner_id"] == homeowner_id]
    if accepted_quote_id is not None:
        items = [p for p in items if p.get("accepted_quote_id") == accepted_quote_id]
    items = V.sort_by_created(items)
    page, meta = V.paginate(items, limit, offset)
    return success([S.project_out(p) for p in page], 200, pagination=meta)


@app.route("/projects/<pid>/cancel", methods=["POST"])
def cancel_project(pid):
    _, role = get_auth()
    require_role(role, {"OperationsCoordinator", "PlatformAdmin"})
    p = get_project_or_404(pid)
    services.expire_project_quotes(p)
    # state precondition: status in {LEAD, CONSULTING, QUOTING, CONTRACTED, IN_PRODUCTION}
    # and no InstallJob COMPLETED.
    if p["status"] not in {"LEAD", "CONSULTING", "QUOTING", "CONTRACTED", "IN_PRODUCTION"}:
        raise errors.err(errors.ERR_INVALID_STATE, "project cannot be cancelled in its current state")
    if any(j["status"] == "COMPLETED" for j in services.install_jobs_of_project(pid)):
        raise errors.err(errors.ERR_INVALID_STATE, "project cannot be cancelled after an install job completed")
    # cascade hop 1: project -> CANCELLED
    p["status"] = "CANCELLED"
    touch(p)
    # hop 2: cancel non-terminal manufacture orders
    for m in services.manufacture_of_project(pid):
        if m["status"] in {"QUEUED", "IN_BUILD"}:
            m["status"] = "CANCELLED"
            touch(m)
    # hop 3: cancel SCHEDULED install jobs (release capacity = no stored counter; capacity is derived)
    for j in services.install_jobs_of_project(pid):
        if j["status"] == "SCHEDULED":
            j["status"] = "CANCELLED"
            touch(j)
    # hop 4: VOID pending referrals whose referred project is this project
    services.void_referrals_for_referred_project(p)
    return success(S.project_out(p), 200)


# ---------------------------------------------------------------------------
# Consultation
# ---------------------------------------------------------------------------
@app.route("/projects/<pid>/consultations", methods=["POST"])
def create_consultation(pid):
    _, role = get_auth()
    require_role(role, {"SalesConsultant", "PlatformAdmin"})
    p = get_project_or_404(pid)
    body = V.get_body()
    # project_id, consultant_id, scheduled_at required
    consultant_id = body.get("consultant_id")
    scheduled_at = body.get("scheduled_at")
    if not isinstance(consultant_id, str) or consultant_id == "":
        raise errors.err(errors.ERR_INVALID_REQUEST, "consultant_id is required")
    if not isinstance(scheduled_at, str) or parse_iso8601(scheduled_at) is None:
        raise errors.err(errors.ERR_INVALID_REQUEST, "scheduled_at must be a valid ISO 8601 instant")
    rec = {
        "project_id": pid,
        "consultant_id": consultant_id,
        "scheduled_at": scheduled_at,
        "status": "BOOKED",
        "total_opening_count": 0,
    }
    stamp_create(rec)
    db.consultations[rec["id"]] = rec
    # if first consultation: Project LEAD -> CONSULTING
    services.recompute_project_status(p)
    return success(S.consultation_out(rec), 201)


@app.route("/projects/<pid>/consultations", methods=["GET"])
def list_consultations(pid):
    _, role = get_auth()
    require_role(role, {"SalesConsultant", "OperationsCoordinator", "Homeowner", "PlatformAdmin"})
    get_project_or_404(pid)
    limit, offset = V.parse_pagination()
    items = V.sort_by_created(services.consultations_of_project(pid))
    page, meta = V.paginate(items, limit, offset)
    return success([S.consultation_out(c) for c in page], 200, pagination=meta)


@app.route("/projects/<pid>/consultations/<cid>", methods=["GET"])
def get_consultation(pid, cid):
    _, role = get_auth()
    require_role(role, {"SalesConsultant", "OperationsCoordinator", "Homeowner", "PlatformAdmin"})
    get_project_or_404(pid)
    c = get_consultation_in_project(pid, cid)
    return success(S.consultation_out(c), 200)


@app.route("/projects/<pid>/consultations/<cid>/complete-measure", methods=["POST"])
def complete_measure(pid, cid):
    _, role = get_auth()
    require_role(role, {"SalesConsultant"})
    p = get_project_or_404(pid)
    c = get_consultation_in_project(pid, cid)
    if c["status"] != "BOOKED":
        raise errors.err(errors.ERR_INVALID_STATE, "consultation is not BOOKED")
    if c["total_opening_count"] < 1:
        raise errors.err(errors.ERR_NO_OPENINGS, "cannot complete a measure with zero openings")
    c["status"] = "MEASURED"
    touch(c)
    services.recompute_project_status(p)
    return success(S.consultation_out(c), 200)


@app.route("/projects/<pid>/consultations/<cid>/cancel", methods=["POST"])
def cancel_consultation(pid, cid):
    _, role = get_auth()
    require_role(role, {"SalesConsultant"})
    p = get_project_or_404(pid)
    c = get_consultation_in_project(pid, cid)
    if c["status"] != "BOOKED":
        raise errors.err(errors.ERR_INVALID_STATE, "only a BOOKED consultation can be cancelled")
    c["status"] = "CANCELLED"
    touch(c)
    services.recompute_project_status(p)
    return success(S.consultation_out(c), 200)


# ---------------------------------------------------------------------------
# Opening
# ---------------------------------------------------------------------------
PRODUCT_TYPES = {"DOUBLE_HUNG", "CASEMENT", "PICTURE", "SLIDING_PATIO_DOOR", "ENTRY_DOOR"}
GLASS_PACKAGES = {"STANDARD", "LOWE_DUAL", "LOWE_TRIPLE"}


@app.route("/projects/<pid>/consultations/<cid>/openings", methods=["POST"])
def create_opening(pid, cid):
    _, role = get_auth()
    require_role(role, {"SalesConsultant"})
    get_project_or_404(pid)
    c = get_consultation_in_project(pid, cid)
    body = V.get_body()
    product_type = V.require_enum(body, "product_type", PRODUCT_TYPES)
    width_in = V.require_positive_number(body, "width_in")
    height_in = V.require_positive_number(body, "height_in")
    glass_package = V.require_enum(body, "glass_package", GLASS_PACKAGES)
    computed = calculations.compute_opening(product_type, width_in, height_in, glass_package)
    rec = {
        "consultation_id": cid,
        "product_type": product_type,
        "width_in": width_in,
        "height_in": height_in,
        "glass_package": glass_package,
        "u_factor": computed["u_factor"],
        "energy_qualified": computed["energy_qualified"],
        "unit_price_cents": computed["unit_price_cents"],
    }
    stamp_create(rec)
    db.openings[rec["id"]] = rec
    # bump Consultation.total_opening_count
    c["total_opening_count"] += 1
    touch(c)
    return success(S.opening_out(rec), 201)


@app.route("/projects/<pid>/consultations/<cid>/openings", methods=["GET"])
def list_openings(pid, cid):
    _, role = get_auth()
    require_role(role, {"SalesConsultant", "OperationsCoordinator", "Homeowner", "PlatformAdmin"})
    get_project_or_404(pid)
    get_consultation_in_project(pid, cid)
    limit, offset = V.parse_pagination()
    items = V.sort_by_created(services.openings_of_consultation(cid))
    page, meta = V.paginate(items, limit, offset)
    return success([S.opening_out(o) for o in page], 200, pagination=meta)


@app.route("/openings/<oid>", methods=["GET"])
def get_opening(oid):
    _, role = get_auth()
    require_role(role, {"SalesConsultant", "OperationsCoordinator", "ServiceTech", "Homeowner", "PlatformAdmin"})
    o = db.openings.get(oid)
    if o is None:
        raise errors.err(errors.ERR_NOT_FOUND, "opening not found")
    return success(S.opening_out(o), 200)


@app.route("/openings/<oid>", methods=["PATCH"])
def update_opening(oid):
    _, role = get_auth()
    require_role(role, {"SalesConsultant"})
    o = db.openings.get(oid)
    if o is None:
        raise errors.err(errors.ERR_NOT_FOUND, "opening not found")
    body = V.get_body()
    glass_package = V.require_enum(body, "glass_package", GLASS_PACKAGES)
    computed = calculations.compute_opening(o["product_type"], o["width_in"], o["height_in"], glass_package)
    o["glass_package"] = glass_package
    o["u_factor"] = computed["u_factor"]
    o["energy_qualified"] = computed["energy_qualified"]
    o["unit_price_cents"] = computed["unit_price_cents"]
    touch(o)
    return success(S.opening_out(o), 200)


# ---------------------------------------------------------------------------
# Quote
# ---------------------------------------------------------------------------
@app.route("/projects/<pid>/quotes", methods=["POST"])
def create_quote(pid):
    _, role = get_auth()
    require_role(role, {"SalesConsultant"})
    p = get_project_or_404(pid)
    body = V.get_body()
    consultation_id = body.get("consultation_id")
    if not isinstance(consultation_id, str) or consultation_id == "":
        raise errors.err(errors.ERR_INVALID_REQUEST, "consultation_id is required")
    consultation = db.consultations.get(consultation_id)
    if consultation is None or consultation["project_id"] != pid:
        raise errors.err(errors.ERR_REFERENCE_NOT_FOUND, "consultation_id does not reference an existing consultation")
    supersede_quote_id = body.get("supersede_quote_id")
    if supersede_quote_id is not None:
        prior = db.quotes.get(supersede_quote_id)
        if prior is None or prior["project_id"] != pid:
            raise errors.err(errors.ERR_REFERENCE_NOT_FOUND, "supersede_quote_id does not reference an existing quote")
    rec = {
        "project_id": pid,
        "consultation_id": consultation_id,
        "status": "DRAFT",
        "discount_tier": None,
        "openings_subtotal_cents": 0,
        "estimate_total_cents": 0,
        "provisional_rebate_cents": 0,
        "expires_at": None,
    }
    stamp_create(rec)
    db.quotes[rec["id"]] = rec
    return success(S.quote_out(rec), 201)


@app.route("/projects/<pid>/quotes", methods=["GET"])
def list_quotes(pid):
    _, role = get_auth()
    require_role(role, {"SalesConsultant", "OperationsCoordinator", "Homeowner", "PlatformAdmin"})
    get_project_or_404(pid)
    services.expire_project_quotes(db.projects[pid])
    limit, offset = V.parse_pagination()
    items = V.sort_by_created(services.quotes_of_project(pid))
    page, meta = V.paginate(items, limit, offset)
    return success([S.quote_out(q) for q in page], 200, pagination=meta)


@app.route("/projects/<pid>/quotes/<qid>", methods=["GET"])
def get_quote(pid, qid):
    _, role = get_auth()
    require_role(role, {"SalesConsultant", "OperationsCoordinator", "Homeowner", "PlatformAdmin"})
    get_project_or_404(pid)
    q = get_quote_in_project(pid, qid)
    services.expire_quote_if_due(q)
    return success(S.quote_out(q), 200)


@app.route("/projects/<pid>/quotes/<qid>/send", methods=["POST"])
def send_quote(pid, qid):
    _, role = get_auth()
    require_role(role, {"SalesConsultant"})
    p = get_project_or_404(pid)
    q = get_quote_in_project(pid, qid)
    services.expire_quote_if_due(q)
    if q["status"] != "DRAFT":
        raise errors.err(errors.ERR_INVALID_STATE, "quote is not DRAFT")
    consultation = db.consultations.get(q["consultation_id"])
    if consultation is None or consultation["status"] != "MEASURED":
        raise errors.err(errors.ERR_CONSULTATION_NOT_MEASURED, "linked consultation is not MEASURED")
    openings = services.openings_of_consultation(q["consultation_id"])
    est = calculations.quote_estimate_total(openings, consultation["total_opening_count"])
    q["openings_subtotal_cents"] = est["openings_subtotal_cents"]
    q["discount_tier"] = est["discount_tier"]
    q["estimate_total_cents"] = est["estimate_total_cents"]
    q["provisional_rebate_cents"] = calculations.rebate_25c(openings, final=False)
    q["expires_at"] = format_iso8601(add_days(clock.get(), 30))
    q["status"] = "SENT"
    touch(q)
    services.recompute_project_status(p)
    return success(S.quote_out(q), 200)


@app.route("/projects/<pid>/quotes/<qid>/accept", methods=["POST"])
def accept_quote(pid, qid):
    user_id, role = get_auth()
    require_role(role, {"Homeowner"})
    p = get_project_or_404(pid)
    q = get_quote_in_project(pid, qid)
    # priority 4: ownership
    ensure_owner(p, user_id)
    # lazily expire before evaluating state
    services.expire_quote_if_due(q)
    body = V.get_body()
    # OCC field expected_quote_version is mandatory for accept
    if "expected_quote_version" not in body or body["expected_quote_version"] is None:
        raise errors.err(errors.ERR_INVALID_REQUEST, "expected_quote_version is required")
    expected = body["expected_quote_version"]
    # priority 6: state (must be SENT)
    if q["status"] != "SENT":
        raise errors.err(errors.ERR_INVALID_STATE, "quote is not SENT")
    # priority 7: OCC
    if not isinstance(expected, int) or isinstance(expected, bool) or expected != q["version"]:
        raise errors.err(errors.ERR_STALE_QUOTE_VERSION, "expected_quote_version does not match current quote version")
    # priority 10: not expired (current_clock < expires_at)
    expires = parse_iso8601(q["expires_at"])
    if expires is None or clock.get() >= expires:
        raise errors.err(errors.ERR_QUOTE_EXPIRED, "quote has expired")
    # priority 11: at most one ACCEPTED quote per project
    if any(other["status"] == "ACCEPTED" for other in services.quotes_of_project(pid)):
        raise errors.err(errors.ERR_PROJECT_ALREADY_CONTRACTED, "project already has an accepted quote")

    # commit: bump version, ACCEPTED
    touch(q)  # increments version by 1
    q["status"] = "ACCEPTED"

    # cascade hop 1: accepted_quote_id + project -> CONTRACTED
    p["accepted_quote_id"] = q["id"]
    services.recompute_project_status(p)

    # cascade hop 2: auto-create ManufactureOrder (QUEUED), compute lead time + ready_at
    consultation = db.consultations.get(q["consultation_id"])
    openings = services.openings_of_consultation(q["consultation_id"])
    lead = calculations.lead_time_days(openings)
    mo = {
        "project_id": pid,
        "quote_id": q["id"],
        "status": "QUEUED",
        "lead_time_days": lead,
        "ready_at": format_iso8601(add_days(clock.get(), lead)),
    }
    stamp_create(mo)
    db.manufacture_orders[mo["id"]] = mo

    # cascade hop 3: supersede other SENT quotes
    for other in services.quotes_of_project(pid):
        if other["id"] != q["id"] and other["status"] == "SENT":
            other["status"] = "SUPERSEDED"
            touch(other)

    # cascade hop 4: settle pending referrals whose referred project is this project
    services.settle_referrals_for_referred_project(p)

    return success(S.quote_out(q), 200)


@app.route("/projects/<pid>/quotes/<qid>/reject", methods=["POST"])
def reject_quote(pid, qid):
    user_id, role = get_auth()
    require_role(role, {"Homeowner"})
    p = get_project_or_404(pid)
    q = get_quote_in_project(pid, qid)
    ensure_owner(p, user_id)
    services.expire_quote_if_due(q)
    if q["status"] != "SENT":
        raise errors.err(errors.ERR_INVALID_STATE, "quote is not SENT")
    q["status"] = "REJECTED"
    touch(q)
    # cancel SUBMITTED financing on this quote
    for f in services.financing_of_quote(qid):
        if f["status"] == "SUBMITTED":
            f["status"] = "CANCELLED"
            touch(f)
    # recompute project status (back to QUOTING if other live SENT quotes, else CONSULTING)
    services.recompute_project_status(p)
    return success(S.quote_out(q), 200)


# ---------------------------------------------------------------------------
# Financing
# ---------------------------------------------------------------------------
@app.route("/projects/<pid>/quotes/<qid>/financing", methods=["POST"])
def create_financing(pid, qid):
    _, role = get_auth()
    require_role(role, {"Homeowner", "SalesConsultant"})
    p = get_project_or_404(pid)
    q = get_quote_in_project(pid, qid)
    body = V.get_body()
    requested = V.require_positive_int(body, "requested_amount_cents")
    term_months = body.get("term_months")
    if term_months not in {12, 24, 36, 60} or isinstance(term_months, bool):
        raise errors.err(errors.ERR_INVALID_REQUEST, "term_months must be one of 12, 24, 36, 60")
    rec = {
        "quote_id": qid,
        "requested_amount_cents": requested,
        "term_months": term_months,
        "status": "SUBMITTED",
        "approved_apr_bps": None,
        "monthly_payment_cents": None,
    }
    stamp_create(rec)
    db.financing_applications[rec["id"]] = rec
    return success(S.financing_out(rec), 201)


@app.route("/projects/<pid>/quotes/<qid>/financing", methods=["GET"])
def list_financing(pid, qid):
    _, role = get_auth()
    require_role(role, {"Homeowner", "SalesConsultant", "OperationsCoordinator", "PlatformAdmin"})
    get_project_or_404(pid)
    get_quote_in_project(pid, qid)
    limit, offset = V.parse_pagination()
    items = V.sort_by_created(services.financing_of_quote(qid))
    page, meta = V.paginate(items, limit, offset)
    return success([S.financing_out(f) for f in page], 200, pagination=meta)


@app.route("/projects/<pid>/quotes/<qid>/financing/<fid>/decide", methods=["POST"])
def decide_financing(pid, qid, fid):
    _, role = get_auth()
    require_role(role, {"OperationsCoordinator"})
    get_project_or_404(pid)
    q = get_quote_in_project(pid, qid)
    f = get_financing_in_quote(qid, fid)
    body = V.get_body()
    decision = body.get("decision")
    if decision not in {"APPROVE", "DECLINE"}:
        raise errors.err(errors.ERR_INVALID_REQUEST, "decision must be APPROVE or DECLINE")
    if f["status"] != "SUBMITTED":
        raise errors.err(errors.ERR_INVALID_STATE, "financing application is not SUBMITTED")
    if decision == "DECLINE":
        f["status"] = "DECLINED"
        touch(f)
        return success(S.financing_out(f), 200)
    # APPROVE: requested_amount_cents <= linked Quote.estimate_total_cents
    if f["requested_amount_cents"] > q["estimate_total_cents"]:
        raise errors.err(errors.ERR_FINANCING_OVER_QUOTE, "requested amount exceeds quote estimate total")
    homeowner = db.homeowners.get(db.projects[pid]["homeowner_id"])
    agi_band = homeowner["agi_band"] if homeowner else "STANDARD"
    apr_bps, monthly = calculations.financing_monthly_payment(agi_band, f["term_months"], f["requested_amount_cents"])
    f["approved_apr_bps"] = apr_bps
    f["monthly_payment_cents"] = monthly
    f["status"] = "APPROVED"
    touch(f)
    return success(S.financing_out(f), 200)


# ---------------------------------------------------------------------------
# Manufacture
# ---------------------------------------------------------------------------
@app.route("/projects/<pid>/manufacture", methods=["GET"])
def list_manufacture(pid):
    _, role = get_auth()
    require_role(role, {"OperationsCoordinator", "SalesConsultant", "Homeowner", "PlatformAdmin"})
    get_project_or_404(pid)
    limit, offset = V.parse_pagination()
    items = V.sort_by_created(services.manufacture_of_project(pid))
    page, meta = V.paginate(items, limit, offset)
    return success([S.manufacture_out(m) for m in page], 200, pagination=meta)


@app.route("/projects/<pid>/manufacture/<mid>", methods=["GET"])
def get_manufacture(pid, mid):
    _, role = get_auth()
    require_role(role, {"OperationsCoordinator", "SalesConsultant", "Homeowner", "PlatformAdmin"})
    get_project_or_404(pid)
    m = get_manufacture_in_project(pid, mid)
    return success(S.manufacture_out(m), 200)


@app.route("/projects/<pid>/manufacture/<mid>/start-build", methods=["POST"])
def start_build(pid, mid):
    _, role = get_auth()
    require_role(role, {"OperationsCoordinator"})
    p = get_project_or_404(pid)
    m = get_manufacture_in_project(pid, mid)
    if m["status"] != "QUEUED" or p["status"] != "CONTRACTED":
        raise errors.err(errors.ERR_INVALID_STATE, "manufacture order cannot start build in current state")
    m["status"] = "IN_BUILD"
    touch(m)
    services.recompute_project_status(p)
    return success(S.manufacture_out(m), 200)


@app.route("/projects/<pid>/manufacture/<mid>/mark-ready", methods=["POST"])
def mark_ready(pid, mid):
    _, role = get_auth()
    require_role(role, {"OperationsCoordinator"})
    get_project_or_404(pid)
    m = get_manufacture_in_project(pid, mid)
    if m["status"] != "IN_BUILD":
        raise errors.err(errors.ERR_INVALID_STATE, "manufacture order is not IN_BUILD")
    ready_at = parse_iso8601(m["ready_at"])
    if ready_at is None or clock.get() < ready_at:
        raise errors.err(errors.ERR_INVALID_STATE, "lead time has not elapsed")
    m["status"] = "READY"
    touch(m)
    return success(S.manufacture_out(m), 200)


# ---------------------------------------------------------------------------
# Crew
# ---------------------------------------------------------------------------
JURISDICTIONS = {"WEST_STRICT", "NORTHEAST_STD", "CENTRAL_LIGHT"}


@app.route("/crews", methods=["POST"])
def create_crew():
    _, role = get_auth()
    require_role(role, {"OperationsCoordinator", "PlatformAdmin"})
    body = V.get_body()
    name = V.require_string(body, "name")
    home_jurisdiction = V.require_enum(body, "home_jurisdiction", JURISDICTIONS)
    daily = body.get("daily_capacity_openings")
    if isinstance(daily, bool) or not isinstance(daily, int) or daily < 1:
        raise errors.err(errors.ERR_INVALID_REQUEST, "daily_capacity_openings must be an integer >= 1")
    rec = {
        "name": name,
        "home_jurisdiction": home_jurisdiction,
        "daily_capacity_openings": daily,
    }
    stamp_create(rec)
    db.crews[rec["id"]] = rec
    return success(S.crew_out(rec), 201)


@app.route("/crews/<crew_id>", methods=["GET"])
def get_crew(crew_id):
    _, role = get_auth()
    require_role(role, {"OperationsCoordinator", "SalesConsultant", "PlatformAdmin"})
    c = db.crews.get(crew_id)
    if c is None:
        raise errors.err(errors.ERR_NOT_FOUND, "crew not found")
    return success(S.crew_out(c), 200)


# ---------------------------------------------------------------------------
# InstallJob
# ---------------------------------------------------------------------------
def _day_set(start_dt, end_dt):
    """Set of calendar days [start.date, end.date) touched by a half-open window.

    A half-open window [start, end) occupies day D if it covers any instant in D.
    The end instant is exclusive: if end falls exactly at midnight (00:00:00) the
    end day is NOT occupied; otherwise the end day IS occupied.
    """
    from datetime import timedelta
    days = set()
    d = start_dt.date()
    last = end_dt.date()
    # Walk from start date up to (and possibly including) end date.
    cur = d
    while cur <= last:
        days.add(cur)
        cur = cur + timedelta(days=1)
    # If end is exactly midnight, the end day is not actually occupied (exclusive).
    if end_dt.time().hour == 0 and end_dt.time().minute == 0 and end_dt.time().second == 0 and end_dt.microsecond == 0:
        days.discard(end_dt.date())
    return days


def _windows_overlap(s1, e1, s2, e2):
    """Half-open overlap: [s1,e1) and [s2,e2) overlap iff s1 < e2 and s2 < e1."""
    return s1 < e2 and s2 < e1


@app.route("/projects/<pid>/install-jobs", methods=["POST"])
def create_install_job(pid):
    _, role = get_auth()
    require_role(role, {"OperationsCoordinator"})
    p = get_project_or_404(pid)
    body = V.get_body()
    crew_id = body.get("crew_id")
    if not isinstance(crew_id, str) or crew_id == "":
        raise errors.err(errors.ERR_INVALID_REQUEST, "crew_id is required")
    crew = db.crews.get(crew_id)
    if crew is None:
        raise errors.err(errors.ERR_REFERENCE_NOT_FOUND, "crew_id does not reference an existing crew")
    window_start_raw = body.get("window_start")
    window_end_raw = body.get("window_end")
    ws = parse_iso8601(window_start_raw) if isinstance(window_start_raw, str) else None
    we = parse_iso8601(window_end_raw) if isinstance(window_end_raw, str) else None
    if ws is None or we is None:
        raise errors.err(errors.ERR_INVALID_REQUEST, "window_start and window_end must be valid ISO 8601 instants")
    if not (we > ws):
        raise errors.err(errors.ERR_INVALID_REQUEST, "window_end must be strictly after window_start")
    # business: crew jurisdiction must equal project jurisdiction
    if crew["home_jurisdiction"] != p["jurisdiction_code"]:
        raise errors.err(errors.ERR_CREW_JURISDICTION_MISMATCH, "crew jurisdiction does not match project jurisdiction")
    # window overlap on same crew (non-terminal jobs)
    existing = [j for j in services.install_jobs_of_crew(crew_id) if j["status"] in {"SCHEDULED", "EN_ROUTE"}]
    for j in existing:
        js = parse_iso8601(j["window_start"])
        je = parse_iso8601(j["window_end"])
        if _windows_overlap(ws, we, js, je):
            raise errors.err(errors.ERR_CREW_WINDOW_CONFLICT, "install window overlaps an existing crew window")
    # capacity: opening_count copied from accepted quote's consultation total_opening_count
    accepted_quote = db.quotes.get(p.get("accepted_quote_id"))
    opening_count = 0
    if accepted_quote is not None:
        consultation = db.consultations.get(accepted_quote["consultation_id"])
        if consultation is not None:
            opening_count = consultation["total_opening_count"]
    new_days = _day_set(ws, we)
    for day in new_days:
        same_day_total = 0
        for j in existing:
            js = parse_iso8601(j["window_start"])
            je = parse_iso8601(j["window_end"])
            if day in _day_set(js, je):
                same_day_total += j["opening_count"]
        if same_day_total + opening_count > crew["daily_capacity_openings"]:
            raise errors.err(errors.ERR_CREW_CAPACITY_EXCEEDED, "crew daily capacity would be exceeded")
    rec = {
        "project_id": pid,
        "crew_id": crew_id,
        "window_start": window_start_raw,
        "window_end": window_end_raw,
        "opening_count": opening_count,
        "status": "SCHEDULED",
    }
    stamp_create(rec)
    db.install_jobs[rec["id"]] = rec
    return success(S.install_job_out(rec), 201)


@app.route("/projects/<pid>/install-jobs", methods=["GET"])
def list_install_jobs(pid):
    _, role = get_auth()
    require_role(role, {"OperationsCoordinator", "SalesConsultant", "Homeowner", "PlatformAdmin"})
    get_project_or_404(pid)
    limit, offset = V.parse_pagination()
    items = V.sort_by_created(services.install_jobs_of_project(pid))
    page, meta = V.paginate(items, limit, offset)
    return success([S.install_job_out(j) for j in page], 200, pagination=meta)


@app.route("/install-jobs", methods=["GET"])
def list_install_jobs_flat():
    _, role = get_auth()
    require_role(role, {"OperationsCoordinator", "PlatformAdmin"})
    limit, offset = V.parse_pagination()
    items = list(db.install_jobs.values())
    crew_id = request.args.get("crew_id")
    project_id = request.args.get("project_id")
    if crew_id is not None:
        items = [j for j in items if j["crew_id"] == crew_id]
    if project_id is not None:
        items = [j for j in items if j["project_id"] == project_id]
    items = V.sort_by_created(items)
    page, meta = V.paginate(items, limit, offset)
    return success([S.install_job_out(j) for j in page], 200, pagination=meta)


@app.route("/install-jobs/<jid>", methods=["GET"])
def get_install_job_flat(jid):
    _, role = get_auth()
    require_role(role, {"OperationsCoordinator", "SalesConsultant", "Homeowner", "PlatformAdmin"})
    j = db.install_jobs.get(jid)
    if j is None:
        raise errors.err(errors.ERR_NOT_FOUND, "install job not found")
    return success(S.install_job_out(j), 200)


@app.route("/projects/<pid>/install-jobs/<jid>/depart", methods=["POST"])
def depart_install_job(pid, jid):
    _, role = get_auth()
    require_role(role, {"OperationsCoordinator"})
    p = get_project_or_404(pid)
    j = get_install_in_project(pid, jid)
    if j["status"] != "SCHEDULED":
        raise errors.err(errors.ERR_INVALID_STATE, "install job is not SCHEDULED")
    # linked ManufactureOrder.status == READY
    mos = services.manufacture_of_project(pid)
    if not any(m["status"] == "READY" for m in mos):
        raise errors.err(errors.ERR_GOODS_NOT_READY, "manufacture order is not READY")
    # current_clock >= window_start
    ws = parse_iso8601(j["window_start"])
    if ws is None or clock.get() < ws:
        raise errors.err(errors.ERR_INVALID_STATE, "install window has not started")
    j["status"] = "EN_ROUTE"
    touch(j)
    services.recompute_project_status(p)
    return success(S.install_job_out(j), 200)


@app.route("/projects/<pid>/install-jobs/<jid>/complete", methods=["POST"])
def complete_install_job(pid, jid):
    _, role = get_auth()
    require_role(role, {"OperationsCoordinator"})
    p = get_project_or_404(pid)
    j = get_install_in_project(pid, jid)
    if j["status"] != "EN_ROUTE":
        raise errors.err(errors.ERR_INVALID_STATE, "install job is not EN_ROUTE")
    # project must hold an APPROVED (or later) permit
    has_permit = any(
        perm["status"] in {"APPROVED", "INSPECTION_PASSED", "INSPECTION_FAILED"}
        for perm in services.permits_of_project(pid)
    )
    if not has_permit:
        raise errors.err(errors.ERR_PERMIT_NOT_APPROVED, "project has no approved permit")
    j["status"] = "COMPLETED"
    touch(j)
    services.recompute_project_status(p)
    return success(S.install_job_out(j), 200)


@app.route("/projects/<pid>/install-jobs/<jid>/cancel", methods=["POST"])
def cancel_install_job(pid, jid):
    _, role = get_auth()
    require_role(role, {"OperationsCoordinator"})
    get_project_or_404(pid)
    j = get_install_in_project(pid, jid)
    if j["status"] != "SCHEDULED":
        raise errors.err(errors.ERR_INVALID_STATE, "only a SCHEDULED install job can be cancelled")
    j["status"] = "CANCELLED"
    touch(j)
    return success(S.install_job_out(j), 200)


# ---------------------------------------------------------------------------
# Permit
# ---------------------------------------------------------------------------
@app.route("/projects/<pid>/permits", methods=["POST"])
def create_permit(pid):
    _, role = get_auth()
    require_role(role, {"OperationsCoordinator"})
    get_project_or_404(pid)
    rec = {
        "project_id": pid,
        "status": "FILED",
        "inspection_due_at": None,
    }
    stamp_create(rec)
    db.permits[rec["id"]] = rec
    return success(S.permit_out(rec), 201)


@app.route("/projects/<pid>/permits", methods=["GET"])
def list_permits(pid):
    _, role = get_auth()
    require_role(role, {"OperationsCoordinator", "SalesConsultant", "Homeowner", "PlatformAdmin"})
    get_project_or_404(pid)
    limit, offset = V.parse_pagination()
    items = V.sort_by_created(services.permits_of_project(pid))
    page, meta = V.paginate(items, limit, offset)
    return success([S.permit_out(p) for p in page], 200, pagination=meta)


@app.route("/projects/<pid>/permits/<permid>/approve", methods=["POST"])
def approve_permit(pid, permid):
    _, role = get_auth()
    require_role(role, {"OperationsCoordinator"})
    p = get_project_or_404(pid)
    permit = get_permit_in_project(pid, permid)
    if permit["status"] not in {"FILED", "INSPECTION_FAILED"}:
        raise errors.err(errors.ERR_INVALID_STATE, "permit cannot be approved in current state")
    permit["status"] = "APPROVED"
    window_days = calculations.INSPECTION_WINDOW_DAYS[p["jurisdiction_code"]]
    permit["inspection_due_at"] = format_iso8601(add_days(clock.get(), window_days))
    touch(permit)
    return success(S.permit_out(permit), 200)


@app.route("/projects/<pid>/permits/<permid>/record-inspection", methods=["POST"])
def record_inspection(pid, permid):
    _, role = get_auth()
    require_role(role, {"OperationsCoordinator"})
    p = get_project_or_404(pid)
    permit = get_permit_in_project(pid, permid)
    body = V.get_body()
    result = body.get("result")
    if result not in {"PASS", "FAIL"}:
        raise errors.err(errors.ERR_INVALID_REQUEST, "result must be PASS or FAIL")
    if permit["status"] != "APPROVED":
        raise errors.err(errors.ERR_INVALID_STATE, "permit is not APPROVED")
    # cross-entity: project must have a COMPLETED install job
    if not any(j["status"] == "COMPLETED" for j in services.install_jobs_of_project(pid)):
        raise errors.err(errors.ERR_INVALID_STATE, "no completed install job on project")
    if result == "PASS":
        permit["status"] = "INSPECTION_PASSED"
        touch(permit)
        services.recompute_project_status(p)
    else:
        permit["status"] = "INSPECTION_FAILED"
        touch(permit)
    return success(S.permit_out(permit), 200)


# ---------------------------------------------------------------------------
# ServiceTicket
# ---------------------------------------------------------------------------
@app.route("/projects/<pid>/service-tickets", methods=["POST"])
def create_service_ticket(pid):
    _, role = get_auth()
    require_role(role, {"Homeowner", "ServiceTech", "PlatformAdmin"})
    p = get_project_or_404(pid)
    body = V.get_body()
    opening_id = body.get("opening_id")
    if not isinstance(opening_id, str) or opening_id == "":
        raise errors.err(errors.ERR_INVALID_REQUEST, "opening_id is required")
    category = body.get("category")
    if category not in {"WARRANTY", "BILLABLE"}:
        raise errors.err(errors.ERR_INVALID_REQUEST, "category must be WARRANTY or BILLABLE")
    opening = db.openings.get(opening_id)
    if opening is None:
        raise errors.err(errors.ERR_REFERENCE_NOT_FOUND, "opening_id does not reference an existing opening")
    # business: project must be COMPLETED
    if p["status"] != "COMPLETED":
        raise errors.err(errors.ERR_PROJECT_NOT_COMPLETED, "service ticket can only be opened on a COMPLETED project")
    # opening must belong to that project (via consultation -> project)
    consultation = db.consultations.get(opening["consultation_id"])
    if consultation is None or consultation["project_id"] != pid:
        raise errors.err(errors.ERR_PROJECT_NOT_COMPLETED, "opening does not belong to this project")
    rec = {
        "project_id": pid,
        "opening_id": opening_id,
        "category": category,
        "status": "OPEN",
        "charge_cents": 0,
    }
    stamp_create(rec)
    db.service_tickets[rec["id"]] = rec
    return success(S.service_ticket_out(rec), 201)


@app.route("/projects/<pid>/service-tickets", methods=["GET"])
def list_service_tickets(pid):
    _, role = get_auth()
    require_role(role, {"Homeowner", "ServiceTech", "OperationsCoordinator", "PlatformAdmin"})
    get_project_or_404(pid)
    limit, offset = V.parse_pagination()
    items = V.sort_by_created(services.service_tickets_of_project(pid))
    page, meta = V.paginate(items, limit, offset)
    return success([S.service_ticket_out(t) for t in page], 200, pagination=meta)


@app.route("/openings/<oid>/service-tickets", methods=["GET"])
def list_service_tickets_for_opening(oid):
    _, role = get_auth()
    require_role(role, {"Homeowner", "ServiceTech", "OperationsCoordinator", "PlatformAdmin"})
    o = db.openings.get(oid)
    if o is None:
        raise errors.err(errors.ERR_NOT_FOUND, "opening not found")
    limit, offset = V.parse_pagination()
    items = V.sort_by_created([t for t in db.service_tickets.values() if t["opening_id"] == oid])
    page, meta = V.paginate(items, limit, offset)
    return success([S.service_ticket_out(t) for t in page], 200, pagination=meta)


@app.route("/projects/<pid>/service-tickets/<sid>/dispatch", methods=["POST"])
def dispatch_ticket(pid, sid):
    _, role = get_auth()
    require_role(role, {"ServiceTech"})
    get_project_or_404(pid)
    t = get_ticket_in_project(pid, sid)
    if t["status"] not in {"OPEN", "REOPENED"}:
        raise errors.err(errors.ERR_INVALID_STATE, "ticket is not OPEN or REOPENED")
    t["status"] = "DISPATCHED"
    touch(t)
    return success(S.service_ticket_out(t), 200)


@app.route("/projects/<pid>/service-tickets/<sid>/resolve", methods=["POST"])
def resolve_ticket(pid, sid):
    _, role = get_auth()
    require_role(role, {"ServiceTech"})
    p = get_project_or_404(pid)
    t = get_ticket_in_project(pid, sid)
    if t["status"] != "DISPATCHED":
        raise errors.err(errors.ERR_INVALID_STATE, "ticket is not DISPATCHED")
    completed_at = parse_iso8601(p.get("completed_at")) if p.get("completed_at") else None
    t["charge_cents"] = calculations.service_charge(t["category"], clock.get(), completed_at)
    t["status"] = "RESOLVED"
    touch(t)
    return success(S.service_ticket_out(t), 200)


@app.route("/projects/<pid>/service-tickets/<sid>/close", methods=["POST"])
def close_ticket(pid, sid):
    _, role = get_auth()
    require_role(role, {"ServiceTech"})
    get_project_or_404(pid)
    t = get_ticket_in_project(pid, sid)
    if t["status"] != "RESOLVED":
        raise errors.err(errors.ERR_INVALID_STATE, "ticket is not RESOLVED")
    t["status"] = "CLOSED"
    touch(t)
    return success(S.service_ticket_out(t), 200)


@app.route("/projects/<pid>/service-tickets/<sid>/reopen", methods=["POST"])
def reopen_ticket(pid, sid):
    user_id, role = get_auth()
    require_role(role, {"Homeowner"})
    p = get_project_or_404(pid)
    t = get_ticket_in_project(pid, sid)
    ensure_owner(p, user_id)
    if t["status"] != "RESOLVED":
        raise errors.err(errors.ERR_INVALID_STATE, "ticket is not RESOLVED")
    t["status"] = "REOPENED"
    touch(t)
    return success(S.service_ticket_out(t), 200)


# ---------------------------------------------------------------------------
# Referral
# ---------------------------------------------------------------------------
@app.route("/referrals", methods=["POST"])
def create_referral():
    _, role = get_auth()
    require_role(role, {"SalesConsultant", "PlatformAdmin"})
    body = V.get_body()
    referrer_project_id = body.get("referrer_project_id")
    referred_project_id = body.get("referred_project_id")
    if not isinstance(referrer_project_id, str) or referrer_project_id == "":
        raise errors.err(errors.ERR_INVALID_REQUEST, "referrer_project_id is required")
    if not isinstance(referred_project_id, str) or referred_project_id == "":
        raise errors.err(errors.ERR_INVALID_REQUEST, "referred_project_id is required")
    referrer = db.projects.get(referrer_project_id)
    referred = db.projects.get(referred_project_id)
    if referrer is None or referred is None:
        raise errors.err(errors.ERR_REFERENCE_NOT_FOUND, "referrer or referred project does not exist")
    # business: referrer must be COMPLETED and referrer != referred
    if referrer["status"] != "COMPLETED" or referrer_project_id == referred_project_id:
        raise errors.err(errors.ERR_REFERRER_NOT_COMPLETED, "referrer project must be COMPLETED and differ from referred")
    rec = {
        "referrer_project_id": referrer_project_id,
        "referred_project_id": referred_project_id,
        "status": "PENDING",
        "reward_amount_cents": 0,
    }
    stamp_create(rec)
    db.referrals[rec["id"]] = rec
    # If the referred project is already CONTRACTED (or beyond) with an accepted
    # quote, settle immediately per the system-driven settlement rule.
    if referred.get("accepted_quote_id"):
        services.settle_referrals_for_referred_project(referred)
    return success(S.referral_out(rec), 201)


@app.route("/referrals", methods=["GET"])
def list_referrals():
    _, role = get_auth()
    require_role(role, {"SalesConsultant", "OperationsCoordinator", "Homeowner", "PlatformAdmin"})
    limit, offset = V.parse_pagination()
    items = list(db.referrals.values())
    referrer_project_id = request.args.get("referrer_project_id")
    referred_project_id = request.args.get("referred_project_id")
    if referrer_project_id is not None:
        items = [r for r in items if r["referrer_project_id"] == referrer_project_id]
    if referred_project_id is not None:
        items = [r for r in items if r["referred_project_id"] == referred_project_id]
    items = V.sort_by_created(items)
    page, meta = V.paginate(items, limit, offset)
    return success([S.referral_out(r) for r in page], 200, pagination=meta)


@app.route("/referrals/<rid>", methods=["GET"])
def get_referral(rid):
    _, role = get_auth()
    require_role(role, {"SalesConsultant", "OperationsCoordinator", "Homeowner", "PlatformAdmin"})
    r = db.referrals.get(rid)
    if r is None:
        raise errors.err(errors.ERR_NOT_FOUND, "referral not found")
    return success(S.referral_out(r), 200)


# ---------------------------------------------------------------------------
# Flat read surface
# ---------------------------------------------------------------------------
@app.route("/consultations/<cid>", methods=["GET"])
def get_consultation_flat(cid):
    _, role = get_auth()
    require_role(role, {"SalesConsultant", "OperationsCoordinator", "Homeowner", "PlatformAdmin"})
    c = db.consultations.get(cid)
    if c is None:
        raise errors.err(errors.ERR_NOT_FOUND, "consultation not found")
    return success(S.consultation_out(c), 200)


@app.route("/consultations", methods=["GET"])
def list_consultations_flat():
    _, role = get_auth()
    require_role(role, {"SalesConsultant", "OperationsCoordinator", "Homeowner", "PlatformAdmin"})
    limit, offset = V.parse_pagination()
    items = list(db.consultations.values())
    project_id = request.args.get("project_id")
    if project_id is not None:
        items = [c for c in items if c["project_id"] == project_id]
    items = V.sort_by_created(items)
    page, meta = V.paginate(items, limit, offset)
    return success([S.consultation_out(c) for c in page], 200, pagination=meta)


@app.route("/openings", methods=["GET"])
def list_openings_flat():
    _, role = get_auth()
    require_role(role, {"SalesConsultant", "OperationsCoordinator", "Homeowner", "PlatformAdmin"})
    limit, offset = V.parse_pagination()
    items = list(db.openings.values())
    consultation_id = request.args.get("consultation_id")
    if consultation_id is not None:
        items = [o for o in items if o["consultation_id"] == consultation_id]
    items = V.sort_by_created(items)
    page, meta = V.paginate(items, limit, offset)
    return success([S.opening_out(o) for o in page], 200, pagination=meta)


@app.route("/quotes/<qid>", methods=["GET"])
def get_quote_flat(qid):
    _, role = get_auth()
    require_role(role, {"SalesConsultant", "OperationsCoordinator", "Homeowner", "PlatformAdmin"})
    q = db.quotes.get(qid)
    if q is None:
        raise errors.err(errors.ERR_NOT_FOUND, "quote not found")
    services.expire_quote_if_due(q)
    return success(S.quote_out(q), 200)


@app.route("/quotes", methods=["GET"])
def list_quotes_flat():
    _, role = get_auth()
    require_role(role, {"SalesConsultant", "OperationsCoordinator", "Homeowner", "PlatformAdmin"})
    limit, offset = V.parse_pagination()
    services.expire_all_quotes()
    items = list(db.quotes.values())
    project_id = request.args.get("project_id")
    consultation_id = request.args.get("consultation_id")
    if project_id is not None:
        items = [q for q in items if q["project_id"] == project_id]
    if consultation_id is not None:
        items = [q for q in items if q["consultation_id"] == consultation_id]
    items = V.sort_by_created(items)
    page, meta = V.paginate(items, limit, offset)
    return success([S.quote_out(q) for q in page], 200, pagination=meta)


@app.route("/financing-applications/<fid>", methods=["GET"])
def get_financing_flat(fid):
    _, role = get_auth()
    require_role(role, {"Homeowner", "SalesConsultant", "OperationsCoordinator", "PlatformAdmin"})
    f = db.financing_applications.get(fid)
    if f is None:
        raise errors.err(errors.ERR_NOT_FOUND, "financing application not found")
    return success(S.financing_out(f), 200)


@app.route("/financing-applications", methods=["GET"])
def list_financing_flat():
    _, role = get_auth()
    require_role(role, {"Homeowner", "SalesConsultant", "OperationsCoordinator", "PlatformAdmin"})
    limit, offset = V.parse_pagination()
    items = list(db.financing_applications.values())
    quote_id = request.args.get("quote_id")
    if quote_id is not None:
        items = [f for f in items if f["quote_id"] == quote_id]
    items = V.sort_by_created(items)
    page, meta = V.paginate(items, limit, offset)
    return success([S.financing_out(f) for f in page], 200, pagination=meta)


@app.route("/manufacture-orders/<mid>", methods=["GET"])
def get_manufacture_flat(mid):
    _, role = get_auth()
    require_role(role, {"OperationsCoordinator", "SalesConsultant", "Homeowner", "PlatformAdmin"})
    m = db.manufacture_orders.get(mid)
    if m is None:
        raise errors.err(errors.ERR_NOT_FOUND, "manufacture order not found")
    return success(S.manufacture_out(m), 200)


@app.route("/manufacture-orders", methods=["GET"])
def list_manufacture_flat():
    _, role = get_auth()
    require_role(role, {"OperationsCoordinator", "SalesConsultant", "Homeowner", "PlatformAdmin"})
    limit, offset = V.parse_pagination()
    items = list(db.manufacture_orders.values())
    project_id = request.args.get("project_id")
    quote_id = request.args.get("quote_id")
    if project_id is not None:
        items = [m for m in items if m["project_id"] == project_id]
    if quote_id is not None:
        items = [m for m in items if m["quote_id"] == quote_id]
    items = V.sort_by_created(items)
    page, meta = V.paginate(items, limit, offset)
    return success([S.manufacture_out(m) for m in page], 200, pagination=meta)


@app.route("/permits/<permid>", methods=["GET"])
def get_permit_flat(permid):
    _, role = get_auth()
    require_role(role, {"OperationsCoordinator", "SalesConsultant", "Homeowner", "PlatformAdmin"})
    p = db.permits.get(permid)
    if p is None:
        raise errors.err(errors.ERR_NOT_FOUND, "permit not found")
    return success(S.permit_out(p), 200)


@app.route("/permits", methods=["GET"])
def list_permits_flat():
    _, role = get_auth()
    require_role(role, {"OperationsCoordinator", "SalesConsultant", "Homeowner", "PlatformAdmin"})
    limit, offset = V.parse_pagination()
    items = list(db.permits.values())
    project_id = request.args.get("project_id")
    if project_id is not None:
        items = [p for p in items if p["project_id"] == project_id]
    items = V.sort_by_created(items)
    page, meta = V.paginate(items, limit, offset)
    return success([S.permit_out(p) for p in page], 200, pagination=meta)


@app.route("/service-tickets/<sid>", methods=["GET"])
def get_service_ticket_flat(sid):
    _, role = get_auth()
    require_role(role, {"Homeowner", "ServiceTech", "OperationsCoordinator", "PlatformAdmin"})
    t = db.service_tickets.get(sid)
    if t is None:
        raise errors.err(errors.ERR_NOT_FOUND, "service ticket not found")
    return success(S.service_ticket_out(t), 200)


@app.route("/service-tickets", methods=["GET"])
def list_service_tickets_flat():
    _, role = get_auth()
    require_role(role, {"Homeowner", "ServiceTech", "OperationsCoordinator", "PlatformAdmin"})
    limit, offset = V.parse_pagination()
    items = list(db.service_tickets.values())
    project_id = request.args.get("project_id")
    opening_id = request.args.get("opening_id")
    if project_id is not None:
        items = [t for t in items if t["project_id"] == project_id]
    if opening_id is not None:
        items = [t for t in items if t["opening_id"] == opening_id]
    items = V.sort_by_created(items)
    page, meta = V.paginate(items, limit, offset)
    return success([S.service_ticket_out(t) for t in page], 200, pagination=meta)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
