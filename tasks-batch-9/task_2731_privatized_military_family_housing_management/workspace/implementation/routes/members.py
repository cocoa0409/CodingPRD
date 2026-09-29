"""Service members, their orders record and their dependents (PRD 3.2)."""

from flask import Blueprint

import middleware as mw
import response as resp
from db import base_row, bump, db, fmt_date, sort_rows
from services import calc, core, lookup

bp = Blueprint("members", __name__)

MEMBER_READ_ROLES = (mw.PLATFORM_ADMIN, mw.PROPERTY_MANAGER, mw.SERVICE_MEMBER,
                     mw.ENVIRONMENTAL_SPECIALIST, mw.INSTALLATION_HOUSING_OFFICE)
DEPENDENT_READ_ROLES = (mw.PLATFORM_ADMIN, mw.PROPERTY_MANAGER, mw.SERVICE_MEMBER,
                        mw.INSTALLATION_HOUSING_OFFICE)


def refresh_dependent_count(sponsor):
    dependents = lookup.dependents_of(sponsor["id"])
    sponsor["dependent_count"] = calc.full_time_dependent_count(dependents)


@bp.post("/service-members")
def create_member():
    mw.authenticate((mw.PLATFORM_ADMIN, mw.INSTALLATION_HOUSING_OFFICE))
    body = mw.json_body()
    dodid = mw.v_str(body, "dodid")
    last_name = mw.v_str(body, "last_name")
    first_name = mw.v_str(body, "first_name")
    branch = mw.v_enum(body, "branch", mw.BRANCHES)
    pay_grade = mw.v_pay_grade(body, "pay_grade")
    for existing in db.service_members.values():
        if existing["dodid"] == dodid:
            mw.bad("dodid", "must be globally unique")
    row = base_row()
    row["dodid"] = dodid
    row["last_name"] = last_name
    row["first_name"] = first_name
    row["branch"] = branch
    row["pay_grade"] = pay_grade
    row["rank_category"] = calc.rank_category(pay_grade)
    row["deployment_status"] = "NOT_DEPLOYED"
    row["deployment_orders_ref"] = None
    row["expected_return_date"] = None
    row["pcs_orders_ref"] = None
    row["pcs_report_date"] = None
    row["dependent_count"] = 0
    db.service_members[row["id"]] = row
    return resp.created(row)


@bp.get("/service-members/<member_id>")
def get_member(member_id):
    mw.authenticate(MEMBER_READ_ROLES)
    return resp.ok(lookup.service_member(member_id))


@bp.get("/service-members/<member_id>/dependents")
def list_dependents(member_id):
    mw.authenticate(DEPENDENT_READ_ROLES)
    limit, offset = mw.pagination()
    relationship = mw.q_enum("relationship", mw.RELATIONSHIPS)
    full_time = mw.q_bool("is_full_time_custody")
    sponsor = lookup.service_member(member_id)
    rows = lookup.dependents_of(sponsor["id"])
    if relationship is not None:
        rows = [r for r in rows if r["relationship"] == relationship]
    if full_time is not None:
        rows = [r for r in rows if bool(r["is_full_time_custody"]) == full_time]
    return resp.page(rows, limit, offset)


@bp.post("/service-members/<member_id>/orders")
def record_orders(member_id):
    mw.authenticate((mw.PLATFORM_ADMIN, mw.INSTALLATION_HOUSING_OFFICE))
    body = mw.json_body()
    deployment_status = mw.v_enum(body, "deployment_status", mw.DEPLOYMENT_STATUSES,
                                  required=False, default=None)
    deployment_orders_ref = mw.v_str(body, "deployment_orders_ref", required=False,
                                     default=None)
    expected_return_date = mw.v_date(body, "expected_return_date", required=False,
                                     default=None)
    pcs_orders_ref = mw.v_str(body, "pcs_orders_ref", required=False, default=None)
    pcs_report_date = mw.v_date(body, "pcs_report_date", required=False, default=None)
    pay_grade = mw.v_pay_grade(body, "pay_grade", required=False, default=None)
    sponsor = lookup.service_member(member_id)

    if deployment_status is not None:
        sponsor["deployment_status"] = deployment_status
    if deployment_orders_ref is not None:
        sponsor["deployment_orders_ref"] = deployment_orders_ref
    if expected_return_date is not None:
        sponsor["expected_return_date"] = fmt_date(expected_return_date)
    if pcs_orders_ref is not None:
        sponsor["pcs_orders_ref"] = pcs_orders_ref
    if pcs_report_date is not None:
        sponsor["pcs_report_date"] = fmt_date(pcs_report_date)
    if pay_grade is not None:
        sponsor["pay_grade"] = pay_grade
        sponsor["rank_category"] = calc.rank_category(pay_grade)
    bump(sponsor)
    return resp.ok(sponsor)


@bp.post("/dependents")
def create_dependent():
    user_id, role = mw.authenticate((mw.PLATFORM_ADMIN, mw.SERVICE_MEMBER,
                                    mw.INSTALLATION_HOUSING_OFFICE))
    body = mw.json_body()
    mw.require_owner(role, user_id, mw.raw_ref(body, "service_member_id"))
    member_id = mw.v_id(body, "service_member_id")
    relationship = mw.v_enum(body, "relationship", mw.RELATIONSHIPS)
    dob = mw.v_date(body, "date_of_birth")
    gender = mw.v_enum(body, "gender", mw.GENDERS)
    full_time = mw.v_bool(body, "is_full_time_custody", required=False, default=True)
    sponsor = lookup.service_member(member_id)
    row = base_row()
    row["service_member_id"] = sponsor["id"]
    row["relationship"] = relationship
    row["date_of_birth"] = fmt_date(dob)
    row["gender"] = gender
    row["is_full_time_custody"] = full_time
    db.dependents[row["id"]] = row
    refresh_dependent_count(sponsor)
    bump(sponsor)
    return resp.created(row)
