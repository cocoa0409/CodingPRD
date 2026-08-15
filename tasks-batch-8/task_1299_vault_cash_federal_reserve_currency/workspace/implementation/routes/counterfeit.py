"""CounterfeitCase endpoints."""
from flask import Blueprint, request

from db import DB, new_id, clock_date_str, clock_iso_ms
from errors import ApiError
from middleware import auth, ALL_ROLES, SITE_SCOPED_STAFF_ROLES, require_site_scope
from response import ok, ok_list
from services import (
    stamp_new, touch, public, append_ledger, site_mutation, derive_site_posture,
    DENOMINATIONS,
)
from util import body, required, as_int, as_str, pagination_args

bp = Blueprint("counterfeit", __name__)


def _get_case_or_404(case_id):
    case = DB["counterfeit_cases"].get(case_id)
    if case is None:
        raise ApiError(
            "ERR_COUNTERFEIT_CASE_NOT_FOUND", 404, "Counterfeit case not found"
        )
    return case


def _site_or_404(site_id):
    site = DB["vault_sites"].get(site_id)
    if site is None:
        raise ApiError("ERR_VAULT_SITE_NOT_FOUND", 404, "Vault site not found")
    return site


@bp.post("/vault-cash/counterfeit-cases")
def create_case():
    principal = auth(["VaultCustodian", "ComplianceOfficer"])
    data = body()
    site_id = as_str(required(data, "site_id"), "site_id")
    _site_or_404(site_id)
    require_site_scope(principal, site_id)
    denom = as_int(required(data, "denomination_cents"), "denomination_cents")
    if denom not in DENOMINATIONS:
        raise ApiError("ERR_INVALID_REQUEST", 400, "Invalid denomination_cents")
    note_count = as_int(required(data, "note_count"), "note_count")
    if note_count < 1:
        raise ApiError("ERR_INVALID_REQUEST", 400, "note_count must be >= 1")
    batch_id = data.get("fitness_batch_id")
    if batch_id is not None:
        batch_id = as_str(batch_id, "fitness_batch_id")
        if batch_id not in DB["fitness_batches"]:
            raise ApiError(
                "ERR_FITNESS_BATCH_NOT_FOUND", 404, "Fitness batch not found"
            )

    case = stamp_new({
        "id": new_id(),
        "site_id": site_id,
        "fitness_batch_id": batch_id,
        "denomination_cents": denom,
        "note_count": note_count,
        "face_value_cents": denom * note_count,
        "seized_by_staff_id": None,
        "seized_at": None,
        "reported_by_staff_id": None,
        "reported_at": None,
        "status": "DETECTED",
    })
    DB["counterfeit_cases"][case["id"]] = case
    return ok(public(case), status=201)


@bp.get("/vault-cash/counterfeit-cases")
def list_cases():
    principal = auth(ALL_ROLES)
    limit, offset = pagination_args()
    site_id = request.args.get("site_id")
    fitness_batch_id = request.args.get("fitness_batch_id")
    status = request.args.get("status")
    rows = list(DB["counterfeit_cases"].values())
    if site_id is not None:
        rows = [c for c in rows if c["site_id"] == site_id]
    if fitness_batch_id is not None:
        rows = [c for c in rows if c.get("fitness_batch_id") == fitness_batch_id]
    if status is not None:
        rows = [c for c in rows if c["status"] == status]
    if principal.role in SITE_SCOPED_STAFF_ROLES:
        rows = [c for c in rows if c["site_id"] == principal.home_site_id]
    rows.sort(key=lambda c: (c["created_at"], c["_seq"]))
    total = len(rows)
    return ok_list([public(c) for c in rows[offset:offset + limit]], total, limit, offset)


@bp.get("/vault-cash/counterfeit-cases/<caseId>")
def get_case(caseId):
    principal = auth(ALL_ROLES)
    case = _get_case_or_404(caseId)
    require_site_scope(principal, case["site_id"])
    return ok(public(case))


@bp.post("/vault-cash/counterfeit-cases/<caseId>/seize")
def seize_case(caseId):
    principal = auth(["VaultCustodian"])
    case = _get_case_or_404(caseId)
    require_site_scope(principal, case["site_id"])
    if case["status"] != "DETECTED":
        raise ApiError(
            "ERR_CASE_INVALID_STATE", 409, "Only DETECTED cases may be seized"
        )
    case["status"] = "SEIZED"
    case["seized_by_staff_id"] = principal.user_id
    case["seized_at"] = clock_iso_ms()
    touch(case)
    # Face value leaves circulation immediately (FIT bucket).
    append_ledger(
        case["site_id"], clock_date_str(), "COUNTERFEIT_SEIZURE",
        -case["face_value_cents"], "FIT",
        note=f"Counterfeit case {case['id']} seizure",
    )
    return ok(public(case))


@bp.post("/vault-cash/counterfeit-cases/<caseId>/report")
def report_case(caseId):
    principal = auth(["ComplianceOfficer"])
    case = _get_case_or_404(caseId)
    require_site_scope(principal, case["site_id"])
    if case["status"] != "SEIZED":
        raise ApiError(
            "ERR_CASE_INVALID_STATE", 409, "Only SEIZED cases may be reported"
        )
    if principal.user_id == case.get("seized_by_staff_id"):
        raise ApiError(
            "ERR_SOD_VIOLATION", 403, "Reporter must differ from the seizer"
        )
    case["status"] = "REPORTED"
    case["reported_by_staff_id"] = principal.user_id
    case["reported_at"] = clock_iso_ms()
    touch(case)
    site = _site_or_404(case["site_id"])
    derive_site_posture(site)
    touch(site)
    return ok(public(case))


@bp.post("/vault-cash/counterfeit-cases/<caseId>/release")
def release_case(caseId):
    principal = auth(["ComplianceOfficer"])
    case = _get_case_or_404(caseId)
    require_site_scope(principal, case["site_id"])
    if case["status"] != "SEIZED":
        raise ApiError(
            "ERR_CASE_INVALID_STATE", 409, "Only SEIZED cases may be released"
        )
    if principal.user_id == case.get("seized_by_staff_id"):
        raise ApiError(
            "ERR_SOD_VIOLATION", 403, "Releaser must differ from the seizer"
        )
    case["status"] = "RELEASED"
    touch(case)
    # Notes determined genuine: face value returns to circulation.
    append_ledger(
        case["site_id"], clock_date_str(), "COUNTERFEIT_RELEASE",
        case["face_value_cents"], "FIT",
        note=f"Counterfeit case {case['id']} release",
    )
    return ok(public(case))


@bp.post("/vault-cash/counterfeit-cases/<caseId>/settle")
def settle_case(caseId):
    principal = auth(["ComplianceOfficer"])
    case = _get_case_or_404(caseId)
    require_site_scope(principal, case["site_id"])
    if case["status"] != "REPORTED":
        raise ApiError(
            "ERR_CASE_INVALID_STATE", 409, "Only REPORTED cases may be settled"
        )
    case["status"] = "SETTLED_WITH_FED"
    touch(case)
    # No cash movement: seized face was already booked as a permanent loss.
    site = _site_or_404(case["site_id"])
    derive_site_posture(site)
    touch(site)
    return ok(public(case))
