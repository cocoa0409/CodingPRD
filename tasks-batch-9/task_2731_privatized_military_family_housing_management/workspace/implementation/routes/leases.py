"""Leases: creation, rent, move-in, termination notice and termination (PRD 3.5, 3.9)."""

from flask import Blueprint

import middleware as mw
import response as resp
from db import (base_row, bump, db, fmt_date, now_iso, parse_date, period_of,
                sort_rows, today)
from errors import ApiError
from services import calc, core, lookup

bp = Blueprint("leases", __name__)

LEASE_READ_ROLES = mw.ALL_ROLES
LEASE_SUB_ROLES = (mw.PLATFORM_ADMIN, mw.PROPERTY_MANAGER, mw.SERVICE_MEMBER,
                   mw.INSTALLATION_HOUSING_OFFICE)
NOTICE_ROLES = (mw.PROPERTY_MANAGER, mw.SERVICE_MEMBER, mw.INSTALLATION_HOUSING_OFFICE)

SHORT_NOTICE_REASONS = ("PCS", "DEPLOYMENT")
STANDARD_NOTICE_DAYS = 30
SHORT_NOTICE_DAYS = 14


def _owner_guard(role, user_id, lease_id):
    lease = lookup.maybe("leases", lease_id)
    if lease is not None:
        mw.require_owner(role, user_id, lease["service_member_id"])
    return lease


# ------------------------------------------------------------ 3.5 lease creation

@bp.post("/leases")
def create_lease():
    mw.authenticate((mw.PROPERTY_MANAGER,))
    body = mw.json_body()
    application_id = mw.v_id(body, "application_id")
    housing_unit_id = mw.v_id(body, "housing_unit_id")
    start_date = mw.v_date(body, "start_date")
    term_months = mw.v_int(body, "term_months", minimum=1, maximum=24)

    unit = lookup.housing_unit(housing_unit_id)
    app_row = lookup.application(application_id)

    if app_row["status"] != "ACCEPTED":
        raise ApiError("ERR_APPLICATION_NOT_ACCEPTED")
    if unit["status"] == "HAZARD_HOLD":
        raise ApiError("ERR_HAZARD_HOLD_ACTIVE")
    if unit["status"] != "ASSIGNED" or app_row["offered_unit_id"] != unit["id"]:
        raise ApiError("ERR_UNIT_NOT_AVAILABLE")
    if int(unit["bedroom_count"]) != int(app_row["bedroom_eligibility"]):
        raise ApiError("ERR_BEDROOM_MISMATCH")
    if unit["designated_rank_category"] != app_row["rank_category"]:
        raise ApiError("ERR_RANK_CATEGORY_MISMATCH")

    installation = lookup.unit_installation(unit)
    if unit.get("last_lease_end_date"):
        gap = (start_date - parse_date(unit["last_lease_end_date"])).days
        if gap < int(installation["turn_buffer_days"]):
            raise ApiError("ERR_UNIT_TURN_BUFFER_VIOLATION")

    sponsor = lookup.service_member(app_row["service_member_id"])
    year_source = parse_date(app_row["effective_control_date"]).year
    dependent_source = int(app_row["dependent_count_at_application"])
    core.require_bah_rate(unit, sponsor, year_source, dependent_source)

    row = base_row()
    row["application_id"] = app_row["id"]
    row["housing_unit_id"] = unit["id"]
    row["service_member_id"] = sponsor["id"]
    row["start_date"] = fmt_date(start_date)
    row["term_months"] = term_months
    row["occupancy_status"] = "PENDING_MOVE_IN"
    row["allotment_status"] = "NOT_STARTED"
    row["bill_of_rights_version_ack"] = None
    row["bill_of_rights_ack_at"] = None
    row["termination_reason"] = None
    row["termination_notice_date"] = None
    row["termination_effective_date"] = None
    row["early_termination_fee_cents"] = 0
    row["settlement_total_cents"] = 0
    row["allotment_balance_cents"] = 0
    row["abatement_total_cents"] = 0
    core.apply_rent(row, unit, sponsor, "OFFER_PROVISIONAL", year_source, dependent_source)
    db.leases[row["id"]] = row

    app_row["status"] = "HOUSED"
    bump(app_row)
    core.recount(installation)
    return resp.created(row)


@bp.get("/leases/<lease_id>")
def get_lease(lease_id):
    user_id, role = mw.authenticate(LEASE_READ_ROLES)
    _owner_guard(role, user_id, lease_id)
    return resp.ok(lookup.lease(lease_id))


@bp.get("/leases")
def list_leases():
    mw.authenticate(LEASE_READ_ROLES)
    limit, offset = mw.pagination()
    application_id = mw.q_str("application_id")
    housing_unit_id = mw.q_str("housing_unit_id")
    member_id = mw.q_str("service_member_id")
    occupancy = mw.q_enum("occupancy_status", mw.OCCUPANCY_STATUSES)
    allotment = mw.q_enum("allotment_status", mw.ALLOTMENT_STATUSES)
    rows = sort_rows(list(db.leases.values()))
    if application_id is not None:
        rows = [r for r in rows if r["application_id"] == application_id]
    if housing_unit_id is not None:
        rows = [r for r in rows if r["housing_unit_id"] == housing_unit_id]
    if member_id is not None:
        rows = [r for r in rows if r["service_member_id"] == member_id]
    if occupancy is not None:
        rows = [r for r in rows if r["occupancy_status"] == occupancy]
    if allotment is not None:
        rows = [r for r in rows if r["allotment_status"] == allotment]
    return resp.page(rows, limit, offset)


@bp.get("/leases/<lease_id>/move-in-inspections")
def list_lease_inspections(lease_id):
    user_id, role = mw.authenticate(LEASE_SUB_ROLES)
    _owner_guard(role, user_id, lease_id)
    limit, offset = mw.pagination()
    status = mw.q_enum("status", mw.INSPECTION_STATUSES)
    lease = lookup.lease(lease_id)
    rows = lookup.inspections_of(lease["id"])
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return resp.page(rows, limit, offset)


@bp.get("/leases/<lease_id>/allotment-transactions")
def list_lease_transactions(lease_id):
    user_id, role = mw.authenticate(LEASE_SUB_ROLES)
    _owner_guard(role, user_id, lease_id)
    limit, offset = mw.pagination()
    period_month = mw.q_period("period_month")
    txn_type = mw.q_enum("type", mw.TRANSACTION_TYPES)
    lease = lookup.lease(lease_id)
    rows = lookup.transactions_of(lease["id"])
    if period_month is not None:
        rows = [r for r in rows if r["period_month"] == period_month]
    if txn_type is not None:
        rows = [r for r in rows if r["type"] == txn_type]
    return resp.page(rows, limit, offset)


# ----------------------------------------------------- 3.5 rent redetermination

@bp.post("/leases/<lease_id>/rent-redetermination")
def rent_redetermination(lease_id):
    mw.authenticate((mw.PROPERTY_MANAGER, mw.PLATFORM_ADMIN))
    body = mw.json_body()
    expected_version = mw.v_int(body, "expected_lease_version")
    effective_date = mw.v_date(body, "effective_date")
    lease = lookup.lease(lease_id)
    lookup.check_lease_version(lease, expected_version)

    unit = lookup.lease_unit(lease)
    sponsor = lookup.service_member(lease["service_member_id"])
    dependent_source = int(sponsor["dependent_count"])
    core.require_bah_rate(unit, sponsor, effective_date.year, dependent_source)
    core.apply_rent(lease, unit, sponsor, "MOVE_IN_FINAL", effective_date.year,
                    dependent_source)
    bump(lease)
    return resp.ok(lease)


# ------------------------------------------------------------------ 3.6 move-in

@bp.post("/leases/<lease_id>/move-in")
def move_in(lease_id):
    mw.authenticate((mw.PROPERTY_MANAGER,))
    mw.json_body()
    lease = lookup.lease(lease_id)

    if lease["occupancy_status"] == "TERMINATED":
        raise ApiError("ERR_TERMINAL_STATE_LOCKED")
    if lease["occupancy_status"] != "PENDING_MOVE_IN":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    acknowledged = [i for i in lookup.inspections_of(lease["id"])
                    if i["status"] in ("TENANT_ACKNOWLEDGED", "COMPLETED")]
    if not acknowledged:
        raise ApiError("ERR_INSPECTION_NOT_ACKNOWLEDGED")

    unit = lookup.lease_unit(lease)
    if unit["status"] == "HAZARD_HOLD":
        raise ApiError("ERR_HAZARD_HOLD_ACTIVE")

    clear = [i for i in acknowledged if int(i["critical_open_count"]) == 0]
    if not clear:
        raise ApiError("ERR_UNRESOLVED_CRITICAL_DEFICIENCY")

    sponsor = lookup.service_member(lease["service_member_id"])
    year_source = parse_date(lease["start_date"]).year
    dependent_source = int(sponsor["dependent_count"])
    core.require_bah_rate(unit, sponsor, year_source, dependent_source)

    core.apply_rent(lease, unit, sponsor, "MOVE_IN_FINAL", year_source, dependent_source)
    lease["occupancy_status"] = "OCCUPIED"
    if lease["allotment_status"] == "NOT_STARTED":
        lease["allotment_status"] = "ACTIVE"
    bump(lease)
    unit["status"] = "OCCUPIED"
    bump(unit)
    core.recount_for_unit(unit)
    return resp.ok(lease)


# ------------------------------------------------------- 3.9 termination notice

@bp.post("/leases/<lease_id>/termination-notice")
def termination_notice(lease_id):
    user_id, role = mw.authenticate(NOTICE_ROLES)
    _owner_guard(role, user_id, lease_id)
    body = mw.json_body()
    reason = mw.v_enum(body, "termination_reason", mw.TERMINATION_REASONS)
    notice_date = mw.v_date(body, "termination_notice_date")
    effective_date = mw.v_date(body, "termination_effective_date")
    lease = lookup.lease(lease_id)

    if lease["occupancy_status"] == "TERMINATED":
        raise ApiError("ERR_TERMINAL_STATE_LOCKED")
    # The lease is this request's primary target, so rung 19 answers before
    # rung 25: the only declared notice edge is OCCUPIED -> NOTICE_GIVEN.
    if lease["occupancy_status"] != "OCCUPIED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    if lease["occupancy_status"] not in ("OCCUPIED", "NOTICE_GIVEN"):
        raise ApiError("ERR_LEASE_NOT_OCCUPIED")

    sponsor = lookup.service_member(lease["service_member_id"])
    if reason == "PCS":
        if not sponsor.get("pcs_orders_ref"):
            raise ApiError("ERR_ORDERS_NOT_ON_FILE")
    elif reason == "DEPLOYMENT":
        if not sponsor.get("deployment_orders_ref") \
                or sponsor.get("deployment_status") != "DEPLOYED":
            raise ApiError("ERR_ORDERS_NOT_ON_FILE")

    required_days = SHORT_NOTICE_DAYS if reason in SHORT_NOTICE_REASONS \
        else STANDARD_NOTICE_DAYS
    if (effective_date - notice_date).days < required_days:
        raise ApiError("ERR_NOTICE_PERIOD_TOO_SHORT")

    lease["occupancy_status"] = "NOTICE_GIVEN"
    lease["termination_reason"] = reason
    lease["termination_notice_date"] = fmt_date(notice_date)
    lease["termination_effective_date"] = fmt_date(effective_date)
    bump(lease)
    return resp.ok(lease)


# ------------------------------------------------------------ 3.9 terminate

@bp.post("/leases/<lease_id>/terminate")
def terminate(lease_id):
    mw.authenticate((mw.PROPERTY_MANAGER,))
    mw.json_body()
    lease = lookup.lease(lease_id)

    if lease["occupancy_status"] == "TERMINATED":
        raise ApiError("ERR_TERMINAL_STATE_LOCKED")
    # Same primary-target reasoning as the notice: rung 19 outranks rung 25 and
    # the only declared termination edge is NOTICE_GIVEN -> TERMINATED.
    if lease["occupancy_status"] != "NOTICE_GIVEN":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    if lease["occupancy_status"] not in ("OCCUPIED", "NOTICE_GIVEN"):
        raise ApiError("ERR_LEASE_NOT_OCCUPIED")

    effective_date = parse_date(lease["termination_effective_date"])
    if today() < effective_date:
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "The termination effective date has not been reached.")

    awarded = 0
    for dispute in lookup.disputes_of_lease(lease["id"]):
        if dispute["status"] == "CLOSED_RESOLVED":
            awarded += int(dispute["credit_award_cents"])

    figures = calc.settlement(lease["daily_rent_cents"], effective_date, awarded,
                              lease["termination_reason"])
    lease["early_termination_fee_cents"] = figures["early_termination_fee_cents"]
    lease["settlement_total_cents"] = figures["settlement_total_cents"]

    period_month = period_of(effective_date)
    source_ref = "TERMINATION_SETTLEMENT:" + lease["id"]
    posted_total = 0
    core.post_transaction(lease, "CHARGE", period_month,
                          figures["prorated_rent_cents"], source_ref)
    posted_total += figures["prorated_rent_cents"]
    if figures["early_termination_fee_cents"] > 0:
        core.post_transaction(lease, "EARLY_TERMINATION_FEE", period_month,
                              figures["early_termination_fee_cents"], source_ref)
        posted_total += figures["early_termination_fee_cents"]

    lease["occupancy_status"] = "TERMINATED"
    if lease["allotment_status"] in ("ACTIVE", "SUSPENDED"):
        lease["allotment_status"] = "CLOSED"
    bump(lease)

    unit = lookup.lease_unit(lease)
    unit["status"] = "AVAILABLE"
    unit["last_lease_end_date"] = fmt_date(effective_date)
    bump(unit)
    core.recount_for_unit(unit)

    core.add_contribution(unit["installation_id"], effective_date.year,
                          calc.contribution_from(posted_total))
    return resp.ok(lease)
