"""Routes: logical clock, customers, jobs (incl. posture actions)."""

from flask import Blueprint, request

from calc import derive_posture, reevaluate_job_posture
from core import (
    bump,
    envelope_object,
    err_credit_hold,
    err_duplicate,
    err_invalid_request,
    err_invalid_state,
    err_job_gate,
    err_not_owner,
    get_body,
    iso,
    now_iso,
    opt_bool,
    opt_enum,
    opt_int,
    paginate,
    parse_iso,
    req_int,
    req_str,
    require_roles,
    sorted_by_created,
    stamp_new,
)
from lookups import get_customer, get_job, sweep_no_show
from serializers import ser_customer, ser_job
from store import db

bp = Blueprint("core_routes", __name__)

WARRANTY_TIERS = ("TIER_LOCAL", "TIER_REGIONAL", "TIER_NATIONAL")


# ---------------------------------------------------------------------------
# Logical clock (test-driving endpoint, mounted at root)
# ---------------------------------------------------------------------------


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_roles("ProjectManager", "QAManager")
    body = get_body()
    to_iso8601 = req_str(body, "to_iso8601")
    db.clock = parse_iso(to_iso8601)
    # advancing past a scheduled_end fires the no-show sweep
    sweep_no_show()
    return envelope_object({"current_utc": iso(db.clock)})


# ---------------------------------------------------------------------------
# Customers
# ---------------------------------------------------------------------------


@bp.route("/panel-shop/customers", methods=["POST"])
def create_customer():
    require_roles("ProjectManager")
    body = get_body()
    company_name = req_str(body, "company_name")
    site_state_code = req_str(body, "site_state_code")
    credit_hold = opt_bool(body, "credit_hold", False)
    tier = opt_enum(body, "warranty_labor_tier", WARRANTY_TIERS, "TIER_REGIONAL")
    c = stamp_new(
        {
            "company_name": company_name,
            "site_state_code": site_state_code,
            "credit_hold": credit_hold,
            "warranty_labor_tier": tier,
        }
    )
    db.customers[c["id"]] = c
    return envelope_object(ser_customer(c), 201)


@bp.route("/panel-shop/customers/<customer_id>", methods=["GET"])
def fetch_customer(customer_id):
    require_roles(
        "ProjectManager",
        "QAManager",
        "DesignEngineer",
        "Customer",
        "ShopLead",
        "TestTechnician",
        "ControlsEngineer",
        "FieldEngineer",
        "ShippingClerk",
    )
    return envelope_object(ser_customer(get_customer(customer_id)))


@bp.route("/panel-shop/customers", methods=["GET"])
def list_customers():
    require_roles("ProjectManager", "QAManager")
    return paginate(sorted_by_created(list(db.customers.values())), ser_customer)


@bp.route("/panel-shop/customers/<customer_id>", methods=["PATCH"])
def update_customer(customer_id):
    require_roles("ProjectManager")
    c = get_customer(customer_id)
    body = get_body()
    if "credit_hold" in body:
        c["credit_hold"] = opt_bool(body, "credit_hold")
    if "warranty_labor_tier" in body:
        c["warranty_labor_tier"] = opt_enum(body, "warranty_labor_tier", WARRANTY_TIERS)
    bump(c)
    return envelope_object(ser_customer(c))


@bp.route("/panel-shop/customers/<customer_id>/jobs", methods=["GET"])
def list_customer_jobs(customer_id):
    require_roles("ProjectManager", "QAManager", "Customer")
    get_customer(customer_id)
    jobs = [j for j in db.jobs.values() if j["customer_id"] == customer_id]
    return paginate(sorted_by_created(jobs), ser_job)


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------


@bp.route("/panel-shop/jobs", methods=["POST"])
def create_job():
    require_roles("ProjectManager")
    body = get_body()
    customer_id = body.get("customer_id")
    if not isinstance(customer_id, str) or not customer_id:
        raise err_invalid_request("Missing or invalid required field: customer_id")
    # priority 5: body-referenced FK
    customer = db.customers.get(customer_id)
    if customer is None:
        from core import err_ref_not_found

        raise err_ref_not_found("customer_id does not reference an existing Customer.")
    job_number = body.get("job_number")
    quoted = body.get("quoted_price_cents")
    warranty_months = body.get("warranty_months", 12)
    # priority 16: job_number unique per customer
    if isinstance(job_number, str) and any(
        j["customer_id"] == customer_id and j["job_number"] == job_number
        for j in db.jobs.values()
    ):
        raise err_duplicate("job_number already exists for this customer.")
    # priority 17: credit hold blocks job creation
    if customer["credit_hold"]:
        raise err_credit_hold("Customer is on credit hold.")
    # priority 18: fiscal ranges
    if not isinstance(quoted, int) or isinstance(quoted, bool) or quoted < 0:
        raise err_invalid_request("quoted_price_cents must be an integer >= 0.")
    if (
        not isinstance(warranty_months, int)
        or isinstance(warranty_months, bool)
        or warranty_months < 0
        or warranty_months > 60
    ):
        raise err_invalid_request("warranty_months must be an integer within [0, 60].")
    if not isinstance(job_number, str) or not job_number:
        raise err_invalid_request("Missing or invalid required field: job_number")
    j = stamp_new(
        {
            "customer_id": customer_id,
            "job_number": job_number,
            "status": "OPEN",
            "quoted_price_cents": quoted,
            "approved_co_delta_cents": 0,
            "contract_price_cents": quoted,
            "warranty_months": warranty_months,
            "warranty_expires_at": None,
        }
    )
    db.jobs[j["id"]] = j
    return envelope_object(ser_job(j), 201)


@bp.route("/panel-shop/jobs/<job_id>", methods=["GET"])
def fetch_job(job_id):
    require_roles("ProjectManager", "QAManager", "Customer", "DesignEngineer", "ShopLead")
    return envelope_object(ser_job(get_job(job_id)))


@bp.route("/panel-shop/jobs", methods=["GET"])
def list_jobs():
    require_roles("ProjectManager", "QAManager", "Customer")
    args = request.args
    jobs = list(db.jobs.values())
    if "customer_id" in args:
        jobs = [j for j in jobs if j["customer_id"] == args.get("customer_id")]
    if "status" in args:
        jobs = [j for j in jobs if j["status"] == args.get("status")]
    return paginate(sorted_by_created(jobs), ser_job)


@bp.route("/panel-shop/jobs/<job_id>/advance", methods=["POST"])
def advance_job(job_id):
    require_roles("ProjectManager")
    j = get_job(job_id)
    if j["status"] != "OPEN":
        raise err_invalid_state("Job is not OPEN.")
    customer = db.customers[j["customer_id"]]
    if customer["credit_hold"]:
        raise err_credit_hold("Customer is on credit hold.")
    j["status"] = "DESIGN"
    bump(j)
    return envelope_object(ser_job(j))


@bp.route("/panel-shop/jobs/<job_id>/hold", methods=["POST"])
def hold_job(job_id):
    require_roles("ProjectManager")
    j = get_job(job_id)
    if j["status"] not in ("DESIGN", "PROCUREMENT", "BUILD", "TEST"):
        raise err_invalid_state("Job cannot be put ON_HOLD from its current status.")
    j["status"] = "ON_HOLD"
    bump(j)
    return envelope_object(ser_job(j))


@bp.route("/panel-shop/jobs/<job_id>/resume", methods=["POST"])
def resume_job(job_id):
    require_roles("ProjectManager")
    j = get_job(job_id)
    if j["status"] != "ON_HOLD":
        raise err_invalid_state("Job is not ON_HOLD.")
    customer = db.customers[j["customer_id"]]
    if customer["credit_hold"]:
        raise err_credit_hold("Customer is on credit hold.")
    derived = derive_posture(j)
    # DESIGN is the floor on resume
    j["status"] = derived if derived != "OPEN" else "DESIGN"
    bump(j)
    return envelope_object(ser_job(j))


@bp.route("/panel-shop/jobs/<job_id>/ship", methods=["POST"])
def ship_job(job_id):
    require_roles("ShippingClerk")
    j = get_job(job_id)
    if j["status"] != "READY_TO_SHIP":
        raise err_job_gate("Job is not READY_TO_SHIP.")
    now = now_iso()
    from core import now_dt

    for p in [p for p in db.panels.values() if p["job_id"] == j["id"]]:
        if p["status"] in ("TEST_PASSED", "READY_FOR_LABEL", "LABELED"):
            p["status"] = "SHIPPED"
            p["shipped_at"] = now
            p["_shipped_dt"] = now_dt()
            bump(p)
    j["status"] = "SHIPPED"
    bump(j)
    return envelope_object(ser_job(j))


@bp.route("/panel-shop/jobs/<job_id>/close", methods=["POST"])
def close_job(job_id):
    require_roles("ProjectManager")
    j = get_job(job_id)
    if j["status"] != "COMMISSIONED":
        raise err_invalid_state("Job is not COMMISSIONED.")
    if any(
        o["job_id"] == j["id"] and o["status"] in ("PROPOSED", "REVISED")
        for o in db.change_orders.values()
    ):
        raise err_job_gate("Job has open change orders.")
    if any(
        w["job_id"] == j["id"] and w["status"] in ("FILED", "TRIAGED", "ACCEPTED")
        for w in db.warranty_claims.values()
    ):
        raise err_job_gate("Job has open warranty claims.")
    j["status"] = "CLOSED"
    bump(j)
    return envelope_object(ser_job(j))


@bp.route("/panel-shop/jobs/<job_id>/panels", methods=["GET"])
def list_job_panels(job_id):
    require_roles(
        "ProjectManager", "QAManager", "DesignEngineer", "ShopLead", "TestTechnician", "Customer"
    )
    get_job(job_id)
    from serializers import ser_panel

    panels = [p for p in db.panels.values() if p["job_id"] == job_id]
    return paginate(sorted_by_created(panels), ser_panel)


@bp.route("/panel-shop/jobs/<job_id>/change-orders", methods=["GET"])
def list_job_change_orders(job_id):
    require_roles("ProjectManager", "QAManager", "Customer")
    get_job(job_id)
    from serializers import ser_change_order

    orders = [o for o in db.change_orders.values() if o["job_id"] == job_id]
    if "status" in request.args:
        orders = [o for o in orders if o["status"] == request.args.get("status")]
    return paginate(sorted_by_created(orders), ser_change_order)


@bp.route("/panel-shop/jobs/<job_id>/warranty-claims", methods=["GET"])
def list_job_warranty_claims(job_id):
    require_roles("ProjectManager", "QAManager", "Customer")
    get_job(job_id)
    from serializers import ser_warranty_claim

    claims = [w for w in db.warranty_claims.values() if w["job_id"] == job_id]
    if "status" in request.args:
        claims = [w for w in claims if w["status"] == request.args.get("status")]
    return paginate(sorted_by_created(claims), ser_warranty_claim)


# re-exported for other modules
__all__ = ["bp", "err_not_owner", "reevaluate_job_posture"]
