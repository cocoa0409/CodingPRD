from flask import Blueprint, request

from db import store
from middleware import authenticate, require_roles
from common import (
    get_json_body, require_string, require_enum, require_int, opt_int,
    get_or_404, make_entity, touch, parse_pagination, paginate,
)
from clock import parse_datetime
from response import success, success_list
from errors import (
    err, ERR_FORBIDDEN, ERR_REFERENCE_NOT_FOUND, ERR_INVALID_REQUEST,
    ERR_BILLING_MODEL_INCOHERENT, ERR_STALE_STUDENT_VERSION, ERR_INVALID_STATE,
    ERR_STUDENT_NOT_ONBOARDED, ERR_CONTRACT_ALREADY_ACTIVE, ERR_CONTRACT_HAS_ENTRIES,
    ERR_OUTSTANDING_BALANCE, ERR_OPEN_APPLICATIONS, ERR_CONTRACT_COVERAGE_OVERLAP,
)
from services.calculations import recompute_contract_balances
from services.billing import append_billing_entry

bp = Blueprint("contracts", __name__)


def serialize(c):
    return {
        "id": c["id"],
        "student_id": c["student_id"],
        "counselor_id": c["counselor_id"],
        "billing_model": c["billing_model"],
        "package_fee_cents": c["package_fee_cents"],
        "package_milestones": c["package_milestones"],
        "hourly_rate_cents": c["hourly_rate_cents"],
        "retainer_deposit_cents": c["retainer_deposit_cents"],
        "coverage_start_utc": c["coverage_start_utc"],
        "coverage_end_utc": c["coverage_end_utc"],
        "status": c["status"],
        "charged_cents": c["charged_cents"],
        "credited_cents": c["credited_cents"],
        "retainer_balance_cents": c["retainer_balance_cents"],
        "projected_balance_cents": c["projected_balance_cents"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


@bp.route("/contracts", methods=["POST"])
def create_contract():
    caller = authenticate()
    require_roles(caller, {"Counselor"})
    body = get_json_body()
    student_id = require_string(body, "student_id")
    billing_model = require_enum(body, "billing_model", {"PACKAGE", "HOURLY"})
    coverage_start_raw = require_string(body, "coverage_start_utc")
    coverage_end_raw = require_string(body, "coverage_end_utc")
    package_fee_cents = opt_int(body, "package_fee_cents", 0)
    package_milestones = opt_int(body, "package_milestones", 0)
    hourly_rate_cents = opt_int(body, "hourly_rate_cents", 0)
    retainer_deposit_cents = opt_int(body, "retainer_deposit_cents", 0)

    # body ranges (ERR_INVALID_REQUEST) — non-negativity per scaffold constraints
    for nm, val in (("package_fee_cents", package_fee_cents),
                    ("package_milestones", package_milestones),
                    ("hourly_rate_cents", hourly_rate_cents),
                    ("retainer_deposit_cents", retainer_deposit_cents)):
        if val < 0:
            raise err(ERR_INVALID_REQUEST, "%s must be >= 0" % nm)

    coverage_start = parse_datetime(coverage_start_raw)
    coverage_end = parse_datetime(coverage_end_raw)
    if not (coverage_end > coverage_start):
        raise err(ERR_INVALID_REQUEST, "coverage_end_utc must be strictly after coverage_start_utc")

    with store.lock:
        student = store.students.get(student_id)
        if student is None:
            raise err(ERR_REFERENCE_NOT_FOUND, "student_id does not reference an existing student")
        if student.get("counselor_id") != caller.user_id:
            raise err(ERR_FORBIDDEN, "Counselor does not own this student")

        # billing-model coherence (ERR_BILLING_MODEL_INCOHERENT) — after well-formedness
        if billing_model == "PACKAGE":
            if not (package_fee_cents > 0 and package_milestones > 0 and hourly_rate_cents == 0):
                raise err(ERR_BILLING_MODEL_INCOHERENT, "PACKAGE requires package_fee_cents>0, package_milestones>0, hourly_rate_cents==0")
        else:  # HOURLY
            if not (hourly_rate_cents > 0 and package_fee_cents == 0 and package_milestones == 0):
                raise err(ERR_BILLING_MODEL_INCOHERENT, "HOURLY requires hourly_rate_cents>0, package_fee_cents==0, package_milestones==0")

        # coverage overlap (closed interval, adjacency allowed) against non-VOID contracts
        for other in store.contracts.values():
            if other.get("student_id") != student_id:
                continue
            if other.get("status") == "VOID":
                continue
            o_start = parse_datetime(other["coverage_start_utc"])
            o_end = parse_datetime(other["coverage_end_utc"])
            if coverage_start < o_end and o_start < coverage_end:
                raise err(ERR_CONTRACT_COVERAGE_OVERLAP, "Coverage window overlaps an existing contract")

        c = make_entity()
        c.update({
            "student_id": student_id,
            "counselor_id": student["counselor_id"],
            "billing_model": billing_model,
            "package_fee_cents": package_fee_cents,
            "package_milestones": package_milestones,
            "hourly_rate_cents": hourly_rate_cents,
            "retainer_deposit_cents": retainer_deposit_cents,
            "coverage_start_utc": coverage_start_raw,
            "coverage_end_utc": coverage_end_raw,
            "status": "DRAFT",
            "charged_cents": 0,
            "credited_cents": 0,
            "retainer_balance_cents": 0,
            "projected_balance_cents": 0,
        })
        store.contracts[c["id"]] = c
        return success(serialize(c), 201)


@bp.route("/contracts/<contract_id>", methods=["GET"])
def get_contract(contract_id):
    caller = authenticate()
    require_roles(caller, {"Counselor", "Student"})
    with store.lock:
        c = get_or_404(store.contracts, contract_id)
        _assert_access(caller, c)
        return success(serialize(c))


@bp.route("/contracts", methods=["GET"])
def list_contracts():
    caller = authenticate()
    require_roles(caller, {"Counselor", "Student"})
    limit, offset = parse_pagination()
    filt_student = request.args.get("student_id")
    filt_counselor = request.args.get("counselor_id")
    with store.lock:
        rows = list(store.contracts.values())
        if caller.is_counselor:
            rows = [r for r in rows if r.get("counselor_id") == caller.user_id]
        elif caller.is_student:
            rows = [r for r in rows if r.get("student_id") == caller.user_id]
        if filt_student is not None:
            rows = [r for r in rows if r.get("student_id") == filt_student]
        if filt_counselor is not None:
            rows = [r for r in rows if r.get("counselor_id") == filt_counselor]
        page, total = paginate(rows, limit, offset)
        return success_list([serialize(r) for r in page], limit, offset, total)


@bp.route("/contracts/<contract_id>/activate", methods=["POST"])
def activate_contract(contract_id):
    caller = authenticate()
    require_roles(caller, {"Counselor"})
    body = get_json_body()
    expected_student_version = require_int(body, "expected_student_version")

    with store.lock:
        c = get_or_404(store.contracts, contract_id)
        if c.get("counselor_id") != caller.user_id:
            raise err(ERR_FORBIDDEN, "Counselor does not own this contract")
        student = store.students.get(c["student_id"])

        # OCC check precedes state check per PRD §2.10
        if expected_student_version != student.get("version"):
            raise err(ERR_STALE_STUDENT_VERSION, "expected_student_version is stale")

        if c["status"] != "DRAFT":
            raise err(ERR_INVALID_STATE, "Contract is not DRAFT")

        # preconditions
        if student.get("intake_status") not in ("ONBOARDED", "ACTIVE"):
            raise err(ERR_STUDENT_NOT_ONBOARDED, "Student must be ONBOARDED or ACTIVE")
        for other in store.contracts.values():
            if other["id"] == c["id"]:
                continue
            if other.get("student_id") == c["student_id"] and other.get("status") == "ACTIVE":
                raise err(ERR_CONTRACT_ALREADY_ACTIVE, "Another contract is already ACTIVE")

        # transition
        c["status"] = "ACTIVE"
        # retainer deposit credit
        deposit = c.get("retainer_deposit_cents", 0)
        if deposit > 0:
            append_billing_entry(
                contract=c,
                entry_type="CREDIT",
                source_kind="MANUAL",
                amount_cents=deposit,
                source_id=None,
                minutes=0,
                memo="",
                recompute=False,
            )
        recompute_contract_balances(c)
        # bubble student ONBOARDED -> ACTIVE
        if student.get("intake_status") == "ONBOARDED":
            student["intake_status"] = "ACTIVE"
            touch(student)
        touch(c)
        return success(serialize(c))


@bp.route("/contracts/<contract_id>/close", methods=["POST"])
def close_contract(contract_id):
    caller = authenticate()
    require_roles(caller, {"Counselor"})
    with store.lock:
        c = get_or_404(store.contracts, contract_id)
        if c.get("counselor_id") != caller.user_id:
            raise err(ERR_FORBIDDEN, "Counselor does not own this contract")
        if c["status"] != "ACTIVE":
            raise err(ERR_INVALID_STATE, "Contract is not ACTIVE")

        # no open applications
        for app in store.applications.values():
            if app.get("student_id") != c["student_id"]:
                continue
            if app.get("prep_status") in ("NOT_STARTED", "IN_PROGRESS", "READY"):
                raise err(ERR_OPEN_APPLICATIONS, "An application still has open prep")
        # recompute then check balance
        recompute_contract_balances(c)
        if c["retainer_balance_cents"] < 0:
            raise err(ERR_OUTSTANDING_BALANCE, "Outstanding balance prevents close")

        c["status"] = "CLOSED"
        recompute_contract_balances(c)
        touch(c)
        return success(serialize(c))


@bp.route("/contracts/<contract_id>/void", methods=["POST"])
def void_contract(contract_id):
    caller = authenticate()
    require_roles(caller, {"Counselor"})
    with store.lock:
        c = get_or_404(store.contracts, contract_id)
        if c.get("counselor_id") != caller.user_id:
            raise err(ERR_FORBIDDEN, "Counselor does not own this contract")
        if c["status"] != "DRAFT":
            raise err(ERR_INVALID_STATE, "Contract is not DRAFT")
        has_entries = any(
            e.get("contract_id") == c["id"] for e in store.billing_entries.values()
        )
        if has_entries:
            raise err(ERR_CONTRACT_HAS_ENTRIES, "Contract has billing entries")
        c["status"] = "VOID"
        touch(c)
        return success(serialize(c))


def _assert_access(caller, c):
    if caller.is_counselor:
        if c.get("counselor_id") != caller.user_id:
            raise err(ERR_FORBIDDEN, "Counselor does not own this contract")
    elif caller.is_student:
        if c.get("student_id") != caller.user_id:
            raise err(ERR_FORBIDDEN, "Student does not own this contract")
