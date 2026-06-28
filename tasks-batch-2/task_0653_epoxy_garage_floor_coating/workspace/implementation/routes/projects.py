"""Project endpoints (SCAFFOLD §1.5 / PRD §3.3, §3.4, §3.5, §3.8)."""
from flask import Blueprint

from db import db
from errors import err
from middleware import authenticate, require_role
from response import success
from services import serialize
from services.calc import (REFERRAL_CREDIT_CENTS, billable_crack_ft, condition_score,
                           financing_payment, quote_pricing)
from services.common import (get_body, new_row, parse_pagination, paginate,
                             require_bool, require_enum, require_int, require_str, touch)

bp = Blueprint("projects", __name__)

READ_PROJECT_ROLES = {"PlatformAdmin", "SalesRep", "Scheduler", "WarrantyAgent", "Customer"}


# ---------------------------------------------------------------------------
# Create / Get
# ---------------------------------------------------------------------------
@bp.route("/projects", methods=["POST"])
def create_project():
    _, role = authenticate()
    require_role(role, {"SalesRep"})
    body = get_body()
    customer_id = require_str(body, "customer_id")
    site_zip = require_str(body, "site_zip")

    # priority 5: body reference resolves
    customer = db.customers.get(customer_id)
    if customer is None:
        raise err("ERR_REFERENCE_NOT_FOUND", "customer_id does not resolve")

    referral_code = body.get("referral_code")

    row = new_row({
        "customer_id": customer_id,
        "site_zip": site_zip,
        "sales_status": "LEAD",
        "build_status": "PRE_BUILD",
        "accepted_quote_id": None,
        "referral_id": None,
    })
    db.projects[row["id"]] = row

    # Implicit referral creation when referral_code matches another customer's code
    if referral_code:
        referrer = next((c for c in db.customers.values()
                         if c["referral_code"] == referral_code), None)
        if referrer is not None:
            ref = new_row({
                "referrer_customer_id": referrer["id"],
                "referred_customer_id": customer_id,
                "project_id": row["id"],
                "credit_cents": REFERRAL_CREDIT_CENTS,
                "status": "PENDING",
            })
            db.referrals[ref["id"]] = ref
            row["referral_id"] = ref["id"]

    return success(serialize.project(row), 201)


@bp.route("/projects/<id>", methods=["GET"])
def get_project(id):
    _, role = authenticate()
    require_role(role, READ_PROJECT_ROLES)
    row = db.projects.get(id)
    if row is None:
        raise err("ERR_NOT_FOUND", "Project not found")
    return success(serialize.project(row), 200)


# ---------------------------------------------------------------------------
# Assessments
# ---------------------------------------------------------------------------
@bp.route("/projects/<id>/assessments", methods=["POST"])
def create_assessment(id):
    _, role = authenticate()
    require_role(role, {"SalesRep"})
    project = db.projects.get(id)
    if project is None:
        raise err("ERR_NOT_FOUND", "Project not found")

    # state guard (priority 8): re-measure allowed only at LEAD or ASSESSED
    if project["sales_status"] not in ("LEAD", "ASSESSED"):
        raise err("ERR_INVALID_STATE",
                  "Assessment only allowed while sales_status is LEAD or ASSESSED")

    body = get_body()
    measured_sqft = require_int(body, "measured_sqft", minimum=1)
    oil_stain_pct = require_int(body, "oil_stain_pct", minimum=0, maximum=100)
    crack_density = require_int(body, "crack_density", minimum=0)
    crack_linear_ft = require_int(body, "crack_linear_ft", minimum=0)
    spalling = require_bool(body, "spalling")
    moisture_pct = require_int(body, "moisture_pct", minimum=0, maximum=100)

    score, prep_tier = condition_score(oil_stain_pct, crack_density, spalling, moisture_pct)
    bcf = billable_crack_ft(crack_linear_ft, prep_tier)

    # supersede prior APPROVED assessment on this project
    for a in db.assessments.values():
        if a["project_id"] == id and a["status"] == "APPROVED":
            a["status"] = "SUPERSEDED"
            touch(a)

    row = new_row({
        "project_id": id,
        "measured_sqft": measured_sqft,
        "oil_stain_pct": oil_stain_pct,
        "crack_density": crack_density,
        "crack_linear_ft": crack_linear_ft,
        "spalling": spalling,
        "moisture_pct": moisture_pct,
        "condition_score": score,
        "prep_tier": prep_tier,
        "billable_crack_ft": bcf,
        "status": "APPROVED",
    })
    db.assessments[row["id"]] = row

    # advance sales track to ASSESSED, bump project version
    project["sales_status"] = "ASSESSED"
    touch(project)

    return success(serialize.assessment(row), 201)


@bp.route("/projects/<id>/assessments", methods=["GET"])
def list_assessments(id):
    _, role = authenticate()
    require_role(role, {"PlatformAdmin", "SalesRep", "Scheduler"})
    if db.projects.get(id) is None:
        raise err("ERR_NOT_FOUND", "Project not found")
    limit, offset = parse_pagination()
    rows = [a for a in db.assessments.values() if a["project_id"] == id]
    page, meta = paginate(rows, limit, offset)
    return success([serialize.assessment(r) for r in page], 200, pagination=meta)


# ---------------------------------------------------------------------------
# Quotes (ESTIMATE create + list)
# ---------------------------------------------------------------------------
@bp.route("/projects/<id>/quotes", methods=["POST"])
def create_quote(id):
    _, role = authenticate()
    require_role(role, {"SalesRep"})
    project = db.projects.get(id)
    if project is None:
        raise err("ERR_NOT_FOUND", "Project not found")

    body = get_body()
    assessment_id = require_str(body, "assessment_id")
    coating_system_id = require_str(body, "coating_system_id")
    color_option_id = require_str(body, "color_option_id")
    install_season = require_enum(body, "install_season", {"PEAK", "STANDARD", "OFF"})
    financing_plan_id = body.get("financing_plan_id")

    # priority 5: body references resolve
    assessment = db.assessments.get(assessment_id)
    if assessment is None:
        raise err("ERR_REFERENCE_NOT_FOUND", "assessment_id does not resolve")
    coating_system = db.coating_systems.get(coating_system_id)
    if coating_system is None:
        raise err("ERR_REFERENCE_NOT_FOUND", "coating_system_id does not resolve")
    color_option = db.color_options.get(color_option_id)
    if color_option is None:
        raise err("ERR_REFERENCE_NOT_FOUND", "color_option_id does not resolve")
    financing_plan = None
    if financing_plan_id is not None:
        financing_plan = db.financing_plans.get(financing_plan_id)
        if financing_plan is None:
            raise err("ERR_REFERENCE_NOT_FOUND", "financing_plan_id does not resolve")

    # priority 6: color belongs to system
    if color_option["coating_system_id"] != coating_system_id:
        raise err("ERR_COLOR_SYSTEM_MISMATCH", "color_option does not belong to coating_system")

    # priority 10: assessment must be APPROVED and on this project
    if assessment["project_id"] != id or assessment["status"] != "APPROVED":
        raise err("ERR_ASSESSMENT_NOT_APPROVED",
                  "assessment must be the project's APPROVED assessment")

    priced = quote_pricing(
        sqft_in=assessment["measured_sqft"],
        crack_ft_in=assessment["crack_linear_ft"],
        prep_tier=assessment["prep_tier"],
        coating_family=coating_system["family"],
        sku=coating_system["sku"],
        install_season=install_season,
    )

    # priority 19: financing eligibility on grand_total
    monthly_payment_cents = 0
    if financing_plan is not None:
        if priced["grand_total_cents"] < financing_plan["min_principal_cents"]:
            raise err("ERR_FINANCING_PRINCIPAL_TOO_LOW",
                      "grand_total below financing plan minimum principal")
        monthly_payment_cents = financing_payment(
            priced["grand_total_cents"], financing_plan["apr_bps"], financing_plan["term_months"])

    row = new_row({
        "project_id": id,
        "assessment_id": assessment_id,
        "coating_system_id": coating_system_id,
        "color_option_id": color_option_id,
        "financing_plan_id": financing_plan_id,
        "install_season": install_season,
        "variant": "ESTIMATE",
        "priced_sqft": priced["priced_sqft"],
        "system_material_cents": priced["system_material_cents"],
        "prep_labor_cents": priced["prep_labor_cents"],
        "volume_discount_pct_bps": priced["volume_discount_pct_bps"],
        "discount_cents": priced["discount_cents"],
        "mobilization_cents": priced["mobilization_cents"],
        "grand_total_cents": priced["grand_total_cents"],
        "monthly_payment_cents": monthly_payment_cents,
        "status": "DRAFT",
    })
    db.quotes[row["id"]] = row
    return success(serialize.quote(row), 201)


@bp.route("/projects/<id>/quotes", methods=["GET"])
def list_quotes(id):
    from flask import request
    _, role = authenticate()
    require_role(role, {"PlatformAdmin", "SalesRep", "Customer"})
    if db.projects.get(id) is None:
        raise err("ERR_NOT_FOUND", "Project not found")
    limit, offset = parse_pagination()
    variant = request.args.get("variant")
    rows = [q for q in db.quotes.values() if q["project_id"] == id]
    if variant is not None:
        rows = [q for q in rows if q["variant"] == variant]
    page, meta = paginate(rows, limit, offset)
    return success([serialize.quote(r) for r in page], 200, pagination=meta)


# ---------------------------------------------------------------------------
# Decline (Customer)
# ---------------------------------------------------------------------------
@bp.route("/projects/<id>/decline", methods=["POST"])
def decline_project(id):
    user_id, role = authenticate()
    require_role(role, {"Customer"})
    project = db.projects.get(id)
    if project is None:
        raise err("ERR_NOT_FOUND", "Project not found")

    # priority 3: ownership
    if project["customer_id"] != user_id:
        raise err("ERR_NOT_RESOURCE_OWNER", "Customer does not own this project")

    # decline-specific: once scheduled (build left PRE_BUILD), a late decline is
    # rejected with ERR_DECLINE_AFTER_SCHEDULED (PRD §3.5). This dedicated guard
    # precedes the generic sales-state guard so a scheduled project (sales already
    # ACCEPTED) reports the scheduled-specific error rather than ERR_INVALID_STATE.
    if project["build_status"] != "PRE_BUILD":
        raise err("ERR_DECLINE_AFTER_SCHEDULED",
                  "Project cannot be declined once it has left PRE_BUILD")
    # generic state guard: must be LEAD/ASSESSED/QUOTED to decline
    if project["sales_status"] not in ("LEAD", "ASSESSED", "QUOTED"):
        raise err("ERR_INVALID_STATE", "Project not in a declinable sales state")

    project["sales_status"] = "DECLINED"
    # supersede non-terminal quotes
    for q in db.quotes.values():
        if q["project_id"] == id and q["status"] in ("DRAFT", "SENT"):
            q["status"] = "SUPERSEDED"
            touch(q)
    # PENDING referral -> EXPIRED
    if project["referral_id"]:
        ref = db.referrals.get(project["referral_id"])
        if ref and ref["status"] == "PENDING":
            ref["status"] = "EXPIRED"
            touch(ref)
    touch(project)
    return success(serialize.project(project), 200)


# ---------------------------------------------------------------------------
# Cancel (PlatformAdmin, OCC-guarded)
# ---------------------------------------------------------------------------
@bp.route("/projects/<id>/cancel", methods=["POST"])
def cancel_project(id):
    _, role = authenticate()
    require_role(role, {"PlatformAdmin"})
    project = db.projects.get(id)
    if project is None:
        raise err("ERR_NOT_FOUND", "Project not found")

    body = get_body()
    # state guard: cancellable only at PRE_BUILD/SCHEDULED/CURING
    if project["build_status"] not in ("PRE_BUILD", "SCHEDULED", "CURING"):
        raise err("ERR_PROJECT_NOT_CANCELLABLE",
                  "Project build_status already terminal")

    # priority 20: OCC (expected_project_version is required, not optional)
    expected = body.get("expected_project_version")
    if expected is None or isinstance(expected, bool) or not isinstance(expected, int):
        raise err("ERR_VALIDATION", "expected_project_version is required")
    if expected != project["version"]:
        raise err("ERR_STALE_PROJECT_VERSION", "expected_project_version is stale")

    project["build_status"] = "CANCELLED"

    # any BOOKED/IN_PROGRESS install job -> CANCELLED (frees crew day)
    for j in db.install_jobs.values():
        if j["project_id"] == id and j["status"] in ("BOOKED", "IN_PROGRESS"):
            j["status"] = "CANCELLED"
            touch(j)

    # any warranty on the project -> VOID; non-terminal claims -> CLOSED
    for w in db.warranties.values():
        if w["project_id"] == id and w["status"] != "VOID":
            w["status"] = "VOID"
            touch(w)
            for c in db.warranty_claims.values():
                if c["warranty_id"] == w["id"] and c["status"] in (
                        "SUBMITTED", "NEEDS_INFO", "APPROVED", "CALLBACK_SCHEDULED"):
                    c["status"] = "CLOSED"
                    touch(c)

    # converted referral -> CLAWED_BACK; referrer credit -= 15000
    if project["referral_id"]:
        ref = db.referrals.get(project["referral_id"])
        if ref and ref["status"] == "CONVERTED":
            ref["status"] = "CLAWED_BACK"
            touch(ref)
            referrer = db.customers.get(ref["referrer_customer_id"])
            if referrer is not None:
                referrer["account_credit_balance_cents"] -= REFERRAL_CREDIT_CENTS
                touch(referrer)

    touch(project)
    return success(serialize.project(project), 200)
