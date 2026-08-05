"""Resource organizations, offerings, eligibility criteria and the gauntlet (PRD §3.3)."""

from flask import Blueprint

import calc
import store
import validate as v
from envelope import created, listing, ok
from errors import ApiError, ERR_INVALID_STATE, ERR_PATIENT_NOT_FOUND, ERR_RESOURCE_NOT_FOUND
from ladder import ALL_ROLES, CHW, Endpoint, PROGRAM_ADMIN, SUPERVISOR, run
from serial import dump, dump_all

bp = Blueprint("resources", __name__)

EP_ORG_CREATE = Endpoint("org.create", [PROGRAM_ADMIN])
EP_ORG_READ = Endpoint("org.read", ALL_ROLES, path=[("org_id", "org")])
EP_ORG_SUSPEND = Endpoint("org.suspend", [PROGRAM_ADMIN], path=[("org_id", "org")])
EP_OFFERING_CREATE = Endpoint("offering.create", [PROGRAM_ADMIN])
EP_OFFERING_READ = Endpoint("offering.read", ALL_ROLES, path=[("offering_id", "offering")])
EP_OFFERING_LIST = Endpoint("offering.list", ALL_ROLES)
EP_CRITERION_CREATE = Endpoint("criterion.create", [PROGRAM_ADMIN],
                               path=[("offering_id", "offering")])
EP_CRITERION_LIST = Endpoint("criterion.list", ALL_ROLES, path=[("offering_id", "offering")])
EP_ELIGIBILITY_CHECK = Endpoint("offering.eligibility_check",
                                [CHW, SUPERVISOR, PROGRAM_ADMIN],
                                path=[("offering_id", "offering")])

ORG_TYPES = ("FOOD", "HOUSING", "TRANSPORT")
UNIT_TYPES = ("FOOD_BOX", "HOUSING_VOUCHER", "TRANSPORT_RIDE")
ORG_ACTIONS = ("SUSPEND", "REINSTATE")
CRITERION_TYPES = tuple(calc.EVAL_RANK.keys())


# ------------------------------------------------------ resource organizations
@bp.post("/chw/resource-orgs")
def create_org():
    def payload(ctx):
        s = ctx.state
        s["name"] = v.req_str(ctx.body, "name")
        s["org_type"] = v.req_enum(ctx.body, "org_type", ORG_TYPES)
        s["service_zips"] = v.zip_array("service_zips", v.req_list(ctx.body, "service_zips"))
        s["contact_email"] = v.req_str(ctx.body, "contact_email")

    ctx = run(EP_ORG_CREATE, steps={5: [payload]})
    s = ctx.state
    row = store.insert("org", {
        "name": s["name"],
        "org_type": s["org_type"],
        "service_zips": s["service_zips"],
        "contact_email": s["contact_email"],
        "status": "ACTIVE",
    })
    return created(dump(row))


@bp.get("/chw/resource-orgs/<org_id>")
def read_org(org_id):
    ctx = run(EP_ORG_READ, {"org_id": org_id})
    return ok(dump(ctx.row("org_id")))


@bp.post("/chw/resource-orgs/<org_id>/suspend")
def suspend_org(org_id):
    def payload(ctx):
        ctx.state["action"] = v.req_enum(ctx.body, "action", ORG_ACTIONS)

    def target_state(ctx):
        org = ctx.row("org_id")
        action = ctx.state["action"]
        if action == "SUSPEND" and org["status"] != "ACTIVE":
            raise ApiError(ERR_INVALID_STATE, "Only an ACTIVE organization may be suspended")
        if action == "REINSTATE" and org["status"] != "SUSPENDED":
            raise ApiError(ERR_INVALID_STATE, "Only a SUSPENDED organization may be reinstated")

    ctx = run(EP_ORG_SUSPEND, {"org_id": org_id}, steps={5: [payload], 8: [target_state]})
    org = ctx.row("org_id")
    org["status"] = "SUSPENDED" if ctx.state["action"] == "SUSPEND" else "ACTIVE"
    store.touch(org)
    return ok(dump(org))


# ------------------------------------------------------------------ offerings
@bp.post("/chw/offerings")
def create_offering():
    def payload(ctx):
        s = ctx.state
        s["resource_org_id"] = v.req_str(ctx.body, "resource_org_id")
        s["unit_type"] = v.req_enum(ctx.body, "unit_type", UNIT_TYPES)
        s["capacity_total"] = v.req_int(ctx.body, "capacity_total", minimum=1)

    def body_refs(ctx):
        org = store.get("org", ctx.state["resource_org_id"])
        if org is None:
            raise ApiError(ERR_RESOURCE_NOT_FOUND, "resource_org_id does not resolve")

    ctx = run(EP_OFFERING_CREATE, steps={5: [payload], 6: [body_refs]})
    s = ctx.state
    row = store.insert("offering", {
        "resource_org_id": s["resource_org_id"],
        "unit_type": s["unit_type"],
        "capacity_total": s["capacity_total"],
        "available_units": s["capacity_total"],
        "allocated_units": 0,
        "delivered_units": 0,
        "released_units": 0,
        "expired_units": 0,
        "lifetime_allocated_units": 0,
        "availability_state": "AVAILABLE",
        "exhausted_since": None,
    })
    return created(dump(row))


@bp.get("/chw/offerings/<offering_id>")
def read_offering(offering_id):
    ctx = run(EP_OFFERING_READ, {"offering_id": offering_id})
    return ok(dump(ctx.row("offering_id")))


@bp.get("/chw/offerings")
def list_offerings():
    def pagination(ctx):
        ctx.state["page"] = v.pagination(ctx.args)

    ctx = run(EP_OFFERING_LIST, steps={5: [pagination]})
    limit, offset = ctx.state["page"]
    rows = store.all_rows("offering")
    for key in ("resource_org_id", "unit_type", "availability_state"):
        wanted = ctx.args.get(key)
        if wanted is not None:
            rows = [r for r in rows if r.get(key) == wanted]
    page, total = v.paginate(rows, limit, offset)
    return listing(dump_all(page), limit, offset, total)


# ---------------------------------------------------------------- criteria
@bp.post("/chw/offerings/<offering_id>/criteria")
def create_criterion(offering_id):
    def payload(ctx):
        s = ctx.state
        kind = v.req_enum(ctx.body, "criterion_type", CRITERION_TYPES)
        s["criterion_type"] = kind
        s["max_monthly_income_cents"] = v.opt_int(ctx.body, "max_monthly_income_cents")
        zips = v.opt_list(ctx.body, "allowed_zips", [])
        for item in zips or []:
            if not isinstance(item, str):
                v.bad("allowed_zips entries must be strings")
        s["allowed_zips"] = zips or []
        s["min_household_size"] = v.opt_int(ctx.body, "min_household_size")
        s["max_household_size"] = v.opt_int(ctx.body, "max_household_size")
        s["required_program_code"] = v.opt_str(ctx.body, "required_program_code")
        s["excluded_flag_code"] = v.opt_str(ctx.body, "excluded_flag_code")

    ctx = run(EP_CRITERION_CREATE, {"offering_id": offering_id}, steps={5: [payload]})
    s = ctx.state
    kind = s["criterion_type"]
    row = store.insert("criterion", {
        "offering_id": ctx.row("offering_id")["id"],
        "criterion_type": kind,
        "evaluation_rank": calc.EVAL_RANK[kind],
        "max_monthly_income_cents":
            s["max_monthly_income_cents"] if kind == "INCOME_BAND" else None,
        "allowed_zips": s["allowed_zips"] if kind == "GEOGRAPHY" else [],
        "min_household_size": s["min_household_size"] if kind == "HOUSEHOLD_SIZE" else None,
        "max_household_size": s["max_household_size"] if kind == "HOUSEHOLD_SIZE" else None,
        "required_program_code":
            s["required_program_code"] if kind == "PROGRAM_ENROLLMENT" else None,
        "excluded_flag_code":
            s["excluded_flag_code"] if kind == "CATEGORICAL_EXCLUSION" else None,
    })
    return created(dump(row))


@bp.get("/chw/offerings/<offering_id>/criteria")
def list_criteria(offering_id):
    def pagination(ctx):
        ctx.state["page"] = v.pagination(ctx.args)

    ctx = run(EP_CRITERION_LIST, {"offering_id": offering_id}, steps={5: [pagination]})
    limit, offset = ctx.state["page"]
    rows = calc.ordered_criteria(ctx.row("offering_id")["id"])
    page, total = v.paginate(rows, limit, offset)
    return listing(dump_all(page), limit, offset, total)


@bp.post("/chw/offerings/<offering_id>/eligibility-check")
def eligibility_check(offering_id):
    def payload(ctx):
        ctx.state["patient_id"] = v.req_str(ctx.body, "patient_id")

    def body_refs(ctx):
        patient = store.get("patient", ctx.state["patient_id"])
        if patient is None:
            raise ApiError(ERR_PATIENT_NOT_FOUND, "patient_id does not resolve")
        ctx.state["patient"] = patient

    ctx = run(EP_ELIGIBILITY_CHECK, {"offering_id": offering_id},
              steps={5: [payload], 6: [body_refs]})
    order, failing, error_id = calc.run_gauntlet(ctx.state["patient"],
                                                 ctx.row("offering_id")["id"])
    return ok({
        "eligible": failing is None,
        "evaluated_count": len(order),
        "first_failing_criterion_id": failing["id"] if failing else None,
        "first_failing_criterion_type": failing["criterion_type"] if failing else None,
        "first_failing_error_id": error_id,
    })
