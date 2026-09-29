"""Enrollment files, their rows and the capitation remittances (PRD 3.5)."""

from flask import Blueprint

import calc
import db
import derive
import middleware
import resolve
import response
import serialize
import validate
from errors import fail

bp = Blueprint("files", __name__)

FILE_STATES = ("RECEIVED", "PARSED", "RECONCILED", "DISPUTED", "POSTED")
ROW_ACTIONS = ("ADD", "TERM", "CHANGE", "RETRO_ADD", "RETRO_TERM")
MATCH_STATUSES = ("UNMATCHED", "MATCHED", "MATCHED_ENROLLEE_ONLY",
                  "EXCEPTION_PHYSICIAN_INACTIVE")
REMITTANCE_STATES = ("RECONCILED", "DISPUTED", "POSTED")

FILE_READ_ROLES = ("IpaAdmin", "NetworkManager", "PayerRepresentative")

FILE_TRANSITION_ROLES = {
    "PARSED": ("IpaAdmin", "PayerRepresentative"),
    "RECONCILED": ("IpaAdmin",),
    "POSTED": ("IpaAdmin",),
    "DISPUTED": ("PayerRepresentative",),
    "RECEIVED": ("PayerRepresentative",),
}


# --------------------------------------------------------------------- files
@bp.post("/ipa/delegation-agreements/<agreement_id>/enrollment-files")
def create_file(agreement_id):
    user_id, role = middleware.require("IpaAdmin", "PayerRepresentative")
    body = validate.body()
    coverage_month = validate.req_coverage_month(body)
    payer_file_reference = validate.req_str(body, "payer_file_reference")

    agreement = resolve.agreement(agreement_id)
    middleware.check_ownership(role, user_id, agreement=agreement)

    # check 8
    if agreement["status"] != "ACTIVE":
        fail("ERR_AGREEMENT_NOT_ACTIVE")
    # check 20 — one live file per coverage month; DISPUTED files are exempt
    for existing in db.files_of_agreement(agreement["id"]):
        if (existing["coverage_month"] == coverage_month
                and existing["status"] != "DISPUTED"):
            fail("ERR_COVERAGE_MONTH_DUPLICATE")

    enrollment_file = db.create(
        db.files,
        agreement_id=agreement["id"],
        coverage_month=coverage_month,
        payer_file_reference=payer_file_reference,
        received_at=db.clock(),
        status="RECEIVED",
        row_count=0,
        matched_row_count=0,
        exception_row_count=0,
        claimed_capitation_cents=0,
        _retro_adjustment_cents=0,
    )
    return response.ok(serialize.enrollment_file(enrollment_file), 201)


@bp.get("/ipa/delegation-agreements/<agreement_id>/enrollment-files")
def list_agreement_files(agreement_id):
    user_id, role = middleware.require(*FILE_READ_ROLES)
    status = validate.query_enum("status", FILE_STATES)
    coverage_month = validate.query_coverage_month()
    limit, offset = validate.pagination()
    agreement = resolve.agreement(agreement_id)
    middleware.check_ownership(role, user_id, agreement=agreement)

    items = db.files_of_agreement(agreement["id"])
    if status is not None:
        items = [f for f in items if f["status"] == status]
    if coverage_month is not None:
        items = [f for f in items if f["coverage_month"] == coverage_month]
    window = validate.paginate(items, limit, offset)
    return response.ok_list([serialize.enrollment_file(f) for f in window], limit,
                            offset, len(items))


@bp.get("/ipa/enrollment-files/<file_id>")
def read_file(file_id):
    user_id, role = middleware.require(*FILE_READ_ROLES)
    enrollment_file = resolve.enrollment_file(file_id)
    middleware.check_ownership(role, user_id,
                              agreement=db.agreement_of_file(enrollment_file))
    return response.ok(serialize.enrollment_file(enrollment_file))


# ---------------------------------------------------------------------- rows
@bp.post("/ipa/enrollment-files/<file_id>/rows")
def create_row(file_id):
    user_id, role = middleware.require("IpaAdmin", "PayerRepresentative")
    body = validate.body()
    external_member_id = validate.req_str(body, "external_member_id")
    physician_npi = validate.req_str(body, "physician_npi")
    row_action = validate.req_enum(body, "row_action", ROW_ACTIONS)
    claimed_capitation_cents = validate.req_int(body, "claimed_capitation_cents",
                                                minimum=0)
    effective_date = validate.req_instant(body, "effective_date")

    enrollment_file = resolve.enrollment_file(file_id)
    middleware.check_ownership(role, user_id,
                              agreement=db.agreement_of_file(enrollment_file))

    if enrollment_file["status"] != "RECEIVED":
        fail("ERR_INVALID_STATE_TRANSITION")

    row = db.create(
        db.rows,
        versioned=False,
        file_id=enrollment_file["id"],
        external_member_id=external_member_id,
        physician_npi=physician_npi,
        row_action=row_action,
        claimed_capitation_cents=claimed_capitation_cents,
        effective_date=effective_date,
        match_status="UNMATCHED",
    )
    enrollment_file["row_count"] += 1
    db.touch(enrollment_file)
    return response.ok(serialize.row(row), 201)


@bp.get("/ipa/enrollment-files/<file_id>/rows")
def list_rows(file_id):
    user_id, role = middleware.require(*FILE_READ_ROLES)
    match_status = validate.query_enum("match_status", MATCH_STATUSES)
    row_action = validate.query_enum("row_action", ROW_ACTIONS)
    limit, offset = validate.pagination()
    enrollment_file = resolve.enrollment_file(file_id)
    middleware.check_ownership(role, user_id,
                              agreement=db.agreement_of_file(enrollment_file))

    items = db.rows_of_file(enrollment_file["id"])
    if match_status is not None:
        items = [r for r in items if r["match_status"] == match_status]
    if row_action is not None:
        items = [r for r in items if r["row_action"] == row_action]
    window = validate.paginate(items, limit, offset)
    return response.ok_list([serialize.row(r) for r in window], limit, offset,
                            len(items))


# ------------------------------------------------------------- remittances
@bp.get("/ipa/enrollment-files/<file_id>/remittances")
def list_file_remittances(file_id):
    user_id, role = middleware.require(*FILE_READ_ROLES)
    status = validate.query_enum("status", REMITTANCE_STATES)
    limit, offset = validate.pagination()
    enrollment_file = resolve.enrollment_file(file_id)
    middleware.check_ownership(role, user_id,
                              agreement=db.agreement_of_file(enrollment_file))

    items = db.remittances_of_file(enrollment_file["id"])
    if status is not None:
        items = [r for r in items if r["status"] == status]
    window = validate.paginate(items, limit, offset)
    return response.ok_list([serialize.remittance(r) for r in window], limit, offset,
                            len(items))


@bp.get("/ipa/capitation-remittances/<remittance_id>")
def read_remittance(remittance_id):
    user_id, role = middleware.require(*FILE_READ_ROLES)
    remittance = resolve.remittance(remittance_id)
    middleware.check_ownership(role, user_id,
                              agreement=db.agreement_of_remittance(remittance))
    return response.ok(serialize.remittance(remittance))


# ------------------------------------------------------------ state machine
def _live_remittance(enrollment_file):
    for remittance in db.remittances_of_file(enrollment_file["id"]):
        if remittance["status"] == "RECONCILED":
            return remittance
    return None


@bp.post("/ipa/enrollment-files/<file_id>/state")
def file_state(file_id):
    user_id, role = middleware.require("IpaAdmin", "PayerRepresentative")
    body = validate.body()
    to_state = validate.req_enum(body, "to_state", FILE_STATES)
    dispute_reason = validate.opt_str(body, "dispute_reason")
    if to_state == "DISPUTED":
        dispute_reason = validate.req_str(body, "dispute_reason")

    enrollment_file = resolve.enrollment_file(file_id)
    middleware.require_transition_role(role, FILE_TRANSITION_ROLES[to_state])
    agreement = db.agreement_of_file(enrollment_file)
    middleware.check_ownership(role, user_id, agreement=agreement)

    current = enrollment_file["status"]

    if to_state == "PARSED":
        if current != "RECEIVED":
            fail("ERR_INVALID_STATE_TRANSITION")
        # check 22
        if enrollment_file["row_count"] < 1:
            fail("ERR_ENROLLMENT_FILE_EMPTY")
        _parse(enrollment_file, agreement)

    elif to_state == "RECONCILED":
        if current != "PARSED":
            fail("ERR_INVALID_STATE_TRANSITION")
        # check 22
        if enrollment_file["matched_row_count"] < 1:
            fail("ERR_ENROLLMENT_FILE_EMPTY")
        _reconcile(enrollment_file, agreement)

    elif to_state == "DISPUTED":
        if current != "RECONCILED":
            fail("ERR_INVALID_STATE_TRANSITION")
        _dispute(enrollment_file, agreement, dispute_reason)

    elif to_state == "RECEIVED":
        if current != "DISPUTED":
            fail("ERR_INVALID_STATE_TRANSITION")
        _resubmit(enrollment_file, agreement)

    elif to_state == "POSTED":
        if current != "RECONCILED" or agreement["status"] != "ACTIVE":
            fail("ERR_INVALID_STATE_TRANSITION")
        _post(enrollment_file, agreement)

    else:  # pragma: no cover
        fail("ERR_INVALID_STATE_TRANSITION")

    return response.ok(serialize.enrollment_file(enrollment_file))


def _parse(enrollment_file, agreement):
    file_rows = db.rows_of_file(enrollment_file["id"])
    for row in file_rows:
        row["match_status"] = calc.enrollment_row_match_status(
            row, enrollment_file["agreement_id"])
    matched = sum(1 for r in file_rows if r["match_status"] == "MATCHED")
    claimed, retro = calc.file_claimed_capitation(file_rows)
    enrollment_file["status"] = "PARSED"
    enrollment_file["matched_row_count"] = matched
    enrollment_file["exception_row_count"] = enrollment_file["row_count"] - matched
    enrollment_file["claimed_capitation_cents"] = claimed
    enrollment_file["_retro_adjustment_cents"] = retro
    db.touch(enrollment_file)


def _reconcile(enrollment_file, agreement):
    method = agreement["reconciliation_method"]
    expected, member_months, per_enrollee_mm, attribution = (
        calc.expected_capitation_for_coverage_month(
            agreement, enrollment_file["coverage_month"], method))
    claimed = enrollment_file["claimed_capitation_cents"]
    retro = enrollment_file.get("_retro_adjustment_cents", 0)
    variance, withhold, net_payable, institutional, professional = (
        calc.remittance_variance_and_allocation(agreement, expected, claimed, retro))

    remittance = db.create(
        db.remittances,
        file_id=enrollment_file["id"],
        coverage_month=enrollment_file["coverage_month"],
        reconciliation_method_used=method,
        expected_capitation_cents=expected,
        claimed_capitation_cents=claimed,
        retro_adjustment_cents=retro,
        variance_cents=variance,
        withhold_cents=withhold,
        net_payable_cents=net_payable,
        institutional_allocation_cents=institutional,
        professional_allocation_cents=professional,
        member_month_count_bps=member_months,
        status="RECONCILED",
        _per_enrollee_mm=per_enrollee_mm,
        _per_enrollee_physician=attribution,
    )
    enrollment_file["status"] = "RECONCILED"
    db.touch(enrollment_file)
    agreement["accrued_capitation_cents"] += expected + retro
    db.touch(agreement)
    return remittance


def _dispute(enrollment_file, agreement, dispute_reason):
    remittance = _live_remittance(enrollment_file)
    enrollment_file["status"] = "DISPUTED"
    enrollment_file["_dispute_reason"] = dispute_reason
    db.touch(enrollment_file)
    if remittance is not None:
        remittance["status"] = "DISPUTED"
        db.touch(remittance)
        # the accrual is reversed exactly — the conserved quantity
        agreement["accrued_capitation_cents"] -= (
            remittance["expected_capitation_cents"]
            + remittance["retro_adjustment_cents"])
        db.touch(agreement)
    derive.sync_capitation_posture(agreement)


def _resubmit(enrollment_file, agreement):
    enrollment_file["status"] = "RECEIVED"
    enrollment_file["matched_row_count"] = 0
    enrollment_file["exception_row_count"] = 0
    enrollment_file["claimed_capitation_cents"] = 0
    enrollment_file["_retro_adjustment_cents"] = 0
    for row in db.rows_of_file(enrollment_file["id"]):
        row["match_status"] = "UNMATCHED"
    db.touch(enrollment_file)
    derive.sync_capitation_posture(agreement)


def _post(enrollment_file, agreement):
    remittance = _live_remittance(enrollment_file)
    # L1
    enrollment_file["status"] = "POSTED"
    db.touch(enrollment_file)
    if remittance is None:
        return
    remittance["status"] = "POSTED"
    db.touch(remittance)

    # L2 — route the money to the pools covering the coverage month
    month_start, _end, _days = calc.month_window(remittance["coverage_month"])
    funded_pools = []
    for pool in db.pools_of_agreement(agreement["id"]):
        if not (pool["pool_year_start"].dt <= month_start <= pool["pool_year_end"].dt):
            continue
        if pool["pool_type"] == "PROFESSIONAL":
            pool["funded_cents"] += remittance["professional_allocation_cents"]
        else:
            pool["funded_cents"] += remittance["institutional_allocation_cents"]
        pool["member_months_bps"] += remittance["member_month_count_bps"]
        ids = pool.setdefault("_remittance_ids", [])
        if remittance["id"] not in ids:
            ids.append(remittance["id"])
        db.touch(pool)
        funded_pools.append(pool)

    agreement["withheld_balance_cents"] += remittance["withhold_cents"]
    db.touch(agreement)

    # L3 — funding moved, so every funded pool's ratio and flag are restated
    for pool in funded_pools:
        derive.sync_pool_ledger(pool)

    # L4 and L5 — posture re-derivation closes the open panels
    derive.sync_capitation_posture(agreement)
