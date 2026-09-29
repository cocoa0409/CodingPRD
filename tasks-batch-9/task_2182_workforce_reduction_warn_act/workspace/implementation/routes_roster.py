"""Sites of employment and the employee roster."""
from flask import Blueprint

from core import ApiError, base_record, db, ok, ok_list
from domain import (backfill_blocked, recompute_plans_touching_site,
                    recompute_site, refresh_employee_derived)
from serialize import employee_out, site_out
from validation import (READER_ROLES, bad, body, endpoint, must_exist, opt_bool,
                        paginate, pagination, parse_employee_attributes, query_enum,
                        query_str, req_state_code, req_str)

bp = Blueprint("roster", __name__)

EMPLOYMENT_STATUSES = ("ACTIVE", "PENDING_SEPARATION", "SEPARATED")


def _new_employee(site, attrs):
    record = base_record()
    record.update({
        "site_id": site["id"],
        "full_name": attrs["full_name"],
        "job_title": attrs["job_title"],
        "birth_date": attrs["birth_date"].isoformat(),
        "hire_date": attrs["hire_date"].isoformat(),
        "annual_base_cents": attrs["annual_base_cents"],
        "weekly_hours": attrs["weekly_hours"],
        "demographic_code": attrs["demographic_code"],
        "monthly_premium_cents": attrs["monthly_premium_cents"],
        "employment_status": "ACTIVE",
        "is_part_time": False,
        "separation_date": None,
        "age_at_separation": None,
        "years_of_service": None,
        "release_signed": False,
        "benefit_continuation_status": "NONE",
        "benefit_subsidy_months": 0,
        "benefit_subsidy_cents": 0,
        "outplacement_tier": "NONE",
    })
    refresh_employee_derived(record)
    db.employees[record["id"]] = record
    return record


# ---------------------------------------------------------------------------
# Sites
# ---------------------------------------------------------------------------
@bp.route("/sites", methods=["POST"])
@endpoint(["RestructuringLead"])
def create_site():
    payload = body()
    name = req_str(payload, "name")
    state_code = req_state_code(payload, "state_code")
    is_single_site = opt_bool(payload, "is_single_site", True)

    record = base_record()
    record.update({
        "name": name,
        "state_code": state_code,
        "is_single_site": is_single_site,
        "roster_count": 0,
        "active_headcount": 0,
        "pending_separation_count": 0,
        "separated_count": 0,
        "federal_loss_count": 0,
        "state_loss_count": 0,
        "warn_trigger_status": "NONE",
        "required_notice_days": 0,
        "window_start_date": None,
    })
    db.sites[record["id"]] = record
    return ok(site_out(record), 201)


@bp.route("/sites/<site_id>", methods=["GET"])
@endpoint(READER_ROLES)
def get_site(site_id):
    return ok(site_out(must_exist("sites", site_id)))


@bp.route("/sites/<site_id>/roster-import", methods=["POST"])
@endpoint(["RestructuringLead"])
def roster_import(site_id):
    # §2.10: the site is resolved before the entries payload is inspected.
    site = must_exist("sites", site_id)
    payload = body()
    if "entries" not in payload or payload["entries"] is None:
        raise bad("Field 'entries' is required.")
    raw = payload["entries"]
    if not isinstance(raw, list):
        raise bad("Field 'entries' must be an array.")
    parsed = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise bad("Each roster entry must be an object.")
        parsed.append(parse_employee_attributes(entry))

    from domain import release_expired_restrictions
    release_expired_restrictions()
    for attrs in parsed:
        if backfill_blocked(site["id"], attrs["job_title"]):
            raise ApiError("ERR_BACKFILL_RESTRICTED", 409)

    created = [_new_employee(site, attrs) for attrs in parsed]
    recompute_site(site)
    recompute_plans_touching_site(site["id"])
    return ok({
        "created_count": len(created),
        "employee_ids": [record["id"] for record in created],
    }, 201)


# ---------------------------------------------------------------------------
# Employees
# ---------------------------------------------------------------------------
@bp.route("/employees", methods=["POST"])
@endpoint(["RestructuringLead"])
def create_employee():
    payload = body()
    site_id = req_str(payload, "site_id")
    attrs = parse_employee_attributes(payload)

    site = db.sites.get(site_id)
    if site is None:
        raise ApiError("ERR_SITE_NOT_FOUND", 404)

    from domain import release_expired_restrictions
    release_expired_restrictions()
    if backfill_blocked(site["id"], attrs["job_title"]):
        raise ApiError("ERR_BACKFILL_RESTRICTED", 409)

    record = _new_employee(site, attrs)
    recompute_site(site)
    recompute_plans_touching_site(site["id"])
    return ok(employee_out(record), 201)


@bp.route("/employees/<employee_id>", methods=["GET"])
@endpoint(READER_ROLES)
def get_employee(employee_id):
    return ok(employee_out(must_exist("employees", employee_id)))


@bp.route("/employees", methods=["GET"])
@endpoint(READER_ROLES)
def list_employees():
    limit, offset = pagination()
    site_id = query_str("site_id")
    status = query_enum("employment_status", EMPLOYMENT_STATUSES)
    job_title = query_str("job_title")

    rows = sorted(db.employees.values(), key=lambda r: r["_seq"])
    if site_id is not None:
        rows = [r for r in rows if r["site_id"] == site_id]
    if status is not None:
        rows = [r for r in rows if r["employment_status"] == status]
    if job_title is not None:
        rows = [r for r in rows if r["job_title"] == job_title]

    page, total = paginate(rows, limit, offset)
    return ok_list([employee_out(r) for r in page], limit, offset, total)
