"""Rental contract endpoints.

The contract row carries two independent state dimensions (billing_status and
service_status); nothing in this module writes the service dimension except the
close/cap paths that are explicitly declared to.
"""
from flask import Blueprint

from calc import (
    cap_candidate_month,
    cap_positions,
    prorated_amount_cents,
    select_equipment_unit,
    travel_supply,
)
from core import (
    CONTRACT_READERS,
    ROLE_AUDITOR,
    ROLE_BILLING,
    ROLE_INTAKE,
    ROLE_MANAGER,
    ROLE_THERAPIST,
    ApiError,
    authenticate,
    base_row,
    current_month,
    db,
    enum_filter,
    now,
    paginate,
    pagination,
    parse_datetime,
    respond,
    sorted_rows,
    str_filter,
    touch,
)
from domain import (
    contract_has_recalled_equipment,
    get_branch,
    get_cmn,
    get_contract,
    get_patient,
    open_contract_exists,
    placements_for_contract,
    recompute_allowable,
)
from serial import contract_out, placement_out, travel_authorization_out
from validate import Field, validate

bp = Blueprint("contracts", __name__)

PRICING_BASES = (
    "COMPETITIVE_BID_SINGLE_PAYMENT",
    "FEE_SCHEDULE_ADJUSTED",
    "CASH",
)
BILLING_STATUSES = ("ACCRUING", "CAP_REACHED", "SUSPENDED", "CLOSED")
SERVICE_STATUSES = (
    "PENDING_SETUP",
    "SETUP_FAILED",
    "IN_SERVICE",
    "PICKUP_SCHEDULED",
    "RETURNED",
)
PLACEMENT_ROLES = ("PRIMARY_STATIONARY", "PORTABLE", "BACKUP")
AMBULATORY = ("LIMITED_AMBULATORY", "ACTIVE_AMBULATORY")
MAX_TRAVEL_CYLINDERS = 12

CREATE_FIELDS = [
    Field("patient_id", "string", required=True, min_len=1),
    Field("cmn_id", "string", required=True, min_len=1),
    Field("pricing_basis", "enum", required=True, enum=PRICING_BASES),
    Field("cap_month_limit", "integer", default=36, minimum=1, maximum=36),
]

POST_MONTH_FIELDS = [Field("service_month", "month", required=True)]

ASSIGNMENT_FIELDS = [Field("role", "enum", required=True, enum=PLACEMENT_ROLES)]

TRAVEL_FIELDS = [
    Field("receiving_branch_id", "string", nullable=True, default=None, min_len=1),
    Field(
        "destination_altitude_feet", "integer", default=0, minimum=0, maximum=15000
    ),
    Field("depart_utc", "datetime", required=True),
    Field("return_utc", "datetime", required=True),
    Field("expected_contract_version", "integer", required=True, minimum=0),
]


def _contract_cmn(contract):
    return db.cmns.get(contract["cmn_id"])


def _require_cmn_active(contract):
    cmn = _contract_cmn(contract)
    if cmn is None or cmn["status"] != "ACTIVE":
        raise ApiError("ERR_CMN_NOT_ACTIVE")
    return cmn


def _refresh_ledger(contract):
    months = contract["posted_months"]
    contract["posted_month_count"] = len(months)
    contract["lifetime_paid_cents"] = sum(m["amount_cents"] for m in months)
    if months:
        contract["last_posted_service_month"] = max(
            m["service_month"] for m in months
        )
    else:
        contract["last_posted_service_month"] = None


@bp.post("/rental-contracts")
def create_contract():
    authenticate((ROLE_BILLING,))
    data = validate(CREATE_FIELDS)
    patient = get_patient(data["patient_id"])
    cmn = get_cmn(data["cmn_id"])
    if patient["status"] != "ACTIVE":
        raise ApiError("ERR_PATIENT_NOT_ACTIVE")
    if cmn["patient_id"] != patient["id"]:
        raise ApiError("ERR_CMN_PATIENT_MISMATCH")
    if open_contract_exists(patient["id"]):
        raise ApiError("ERR_PATIENT_HAS_OPEN_CONTRACT")
    if cmn["status"] != "ACTIVE":
        raise ApiError("ERR_CMN_NOT_ACTIVE")
    row = base_row()
    row.update(
        {
            "patient_id": patient["id"],
            "cmn_id": cmn["id"],
            "pricing_basis": data["pricing_basis"],
            "cap_month_limit": data["cap_month_limit"],
            "billing_status": "ACCRUING",
            "service_status": "PENDING_SETUP",
            "suspension_reason": "NONE",
            "first_service_month": None,
            "monthly_allowable_cents": 0,
            "posted_months": [],
            "posted_month_count": 0,
            "lifetime_paid_cents": 0,
            "last_posted_service_month": None,
            "malfunction_count": 0,
            "cumulative_oxygen_gap_minutes": 0,
            "_service_started_at": None,
        }
    )
    db.contracts[row["id"]] = row
    return respond(contract_out(row), 201)


@bp.get("/rental-contracts")
def list_contracts():
    authenticate(CONTRACT_READERS)
    patient_id = str_filter("patient_id")
    cmn_id = str_filter("cmn_id")
    billing = enum_filter("billing_status", BILLING_STATUSES)
    service = enum_filter("service_status", SERVICE_STATUSES)
    basis = enum_filter("pricing_basis", PRICING_BASES)
    limit, offset = pagination()
    rows = sorted_rows(db.contracts.values())
    if patient_id is not None:
        rows = [r for r in rows if r["patient_id"] == patient_id]
    if cmn_id is not None:
        rows = [r for r in rows if r["cmn_id"] == cmn_id]
    if billing is not None:
        rows = [r for r in rows if r["billing_status"] == billing]
    if service is not None:
        rows = [r for r in rows if r["service_status"] == service]
    if basis is not None:
        rows = [r for r in rows if r["pricing_basis"] == basis]
    return paginate(rows, limit, offset, contract_out)


@bp.get("/rental-contracts/<contract_id>")
def read_contract(contract_id):
    authenticate(CONTRACT_READERS)
    return respond(contract_out(get_contract(contract_id)))


@bp.get("/rental-contracts/<contract_id>/cap-summary")
def cap_summary(contract_id):
    """Computed read: both cap-counting bases plus the selected one."""
    authenticate((ROLE_BILLING, ROLE_MANAGER, ROLE_AUDITOR))
    contract = get_contract(contract_id)
    candidate = cap_candidate_month(contract)
    service_basis, paid_basis, effective, remaining = cap_positions(
        contract, candidate
    )
    variant = (
        "SERVICE_MONTH_BASIS"
        if contract["pricing_basis"] == "COMPETITIVE_BID_SINGLE_PAYMENT"
        else "PAID_MONTH_BASIS"
    )
    return respond(
        {
            "contract_id": contract["id"],
            "candidate_service_month": candidate,
            "service_month_basis_position": service_basis,
            "paid_month_basis_position": paid_basis,
            "variant_applied": variant,
            "effective_position": effective,
            "cap_month_limit": contract["cap_month_limit"],
            "months_remaining": remaining,
            "monthly_allowable_cents": contract["monthly_allowable_cents"],
            "lifetime_paid_cents": contract["lifetime_paid_cents"],
            "posted_month_count": contract["posted_month_count"],
        }
    )


@bp.post("/rental-contracts/<contract_id>/billing-months")
def post_billing_month(contract_id):
    """Post one rental month; hits CAP_REACHED when the cap position lands exactly."""
    authenticate((ROLE_BILLING,))
    contract = get_contract(contract_id)
    data = validate(POST_MONTH_FIELDS)
    if contract["billing_status"] == "CLOSED":
        raise ApiError("ERR_CONTRACT_CLOSED")
    if contract["billing_status"] != "ACCRUING":
        raise ApiError("ERR_CONTRACT_BILLING_SUSPENDED")
    if contract["service_status"] != "IN_SERVICE":
        raise ApiError("ERR_CONTRACT_NOT_IN_SERVICE")
    _require_cmn_active(contract)
    month = data["service_month"]
    first = contract["first_service_month"]
    if first is not None and month < first:
        raise ApiError("ERR_SERVICE_MONTH_BEFORE_START")
    if month > current_month():
        raise ApiError("ERR_SERVICE_MONTH_IN_FUTURE")
    for entry in contract["posted_months"]:
        if entry["service_month"] == month:
            raise ApiError("ERR_SERVICE_MONTH_ALREADY_POSTED")
    _, _, effective, _ = cap_positions(contract, month)
    if effective > contract["cap_month_limit"]:
        raise ApiError("ERR_CAP_MONTHS_EXHAUSTED")
    if contract["monthly_allowable_cents"] <= 0:
        raise ApiError("ERR_NO_PLACED_EQUIPMENT")
    amount, days_in_service, _total = prorated_amount_cents(
        contract, int(month[:4]), int(month[5:7])
    )
    contract["posted_months"].append(
        {
            "service_month": month,
            "amount_cents": amount,
            "days_in_service": days_in_service,
            "posted_at": now(),
        }
    )
    _refresh_ledger(contract)
    if effective == contract["cap_month_limit"]:
        contract["billing_status"] = "CAP_REACHED"
    touch(contract)
    return respond(contract_out(contract))


@bp.post("/rental-contracts/<contract_id>/billing-months/<service_month>/reverse")
def reverse_billing_month(contract_id, service_month):
    """Compensating counterpart of the post action; conserves lifetime_paid_cents."""
    authenticate((ROLE_BILLING,))
    contract = get_contract(contract_id)
    target = None
    for entry in contract["posted_months"]:
        if entry["service_month"] == service_month:
            target = entry
            break
    if target is None:
        raise ApiError("ERR_POSTED_MONTH_NOT_FOUND")
    if contract["billing_status"] == "CLOSED":
        raise ApiError("ERR_CONTRACT_CLOSED")
    if contract["billing_status"] not in ("ACCRUING", "CAP_REACHED"):
        raise ApiError("ERR_INVALID_STATE")
    remaining = [e for e in contract["posted_months"] if e is not target]
    if contract["billing_status"] == "CAP_REACHED":
        if remaining:
            candidate = max(e["service_month"] for e in remaining)
        else:
            candidate = contract["first_service_month"]
        _, _, effective, _ = cap_positions(contract, candidate, remaining)
        if effective >= contract["cap_month_limit"]:
            raise ApiError("ERR_REVERSAL_WOULD_NOT_CLEAR_CAP")
        contract["billing_status"] = "ACCRUING"
    contract["posted_months"] = remaining
    _refresh_ledger(contract)
    touch(contract)
    return respond(contract_out(contract))


@bp.post("/rental-contracts/<contract_id>/resume-billing")
def resume_billing(contract_id):
    authenticate((ROLE_BILLING,))
    contract = get_contract(contract_id)
    if contract["billing_status"] == "CLOSED":
        raise ApiError("ERR_CONTRACT_CLOSED")
    if contract["billing_status"] != "SUSPENDED":
        raise ApiError("ERR_INVALID_STATE")
    patient = get_patient(contract["patient_id"])
    if patient["status"] != "ACTIVE":
        raise ApiError("ERR_PATIENT_NOT_ACTIVE")
    _require_cmn_active(contract)
    if contract_has_recalled_equipment(contract["id"]):
        raise ApiError("ERR_CONTRACT_HAS_RECALLED_EQUIPMENT")
    candidate = cap_candidate_month(contract)
    _, _, effective, _ = cap_positions(contract, candidate)
    if effective > contract["cap_month_limit"]:
        raise ApiError("ERR_CAP_MONTHS_EXHAUSTED")
    contract["suspension_reason"] = "NONE"
    contract["billing_status"] = (
        "CAP_REACHED" if effective == contract["cap_month_limit"] else "ACCRUING"
    )
    recompute_allowable(contract)
    touch(contract)
    return respond(contract_out(contract))


@bp.post("/rental-contracts/<contract_id>/close")
def close_contract(contract_id):
    authenticate((ROLE_BILLING,))
    contract = get_contract(contract_id)
    if contract["billing_status"] == "CLOSED":
        raise ApiError("ERR_INVALID_STATE")
    if contract["service_status"] not in ("RETURNED", "SETUP_FAILED"):
        raise ApiError("ERR_CONTRACT_NOT_RETURNED")
    contract["monthly_allowable_cents"] = 0
    contract["billing_status"] = "CLOSED"
    touch(contract)
    return respond(contract_out(contract))


@bp.post("/rental-contracts/<contract_id>/equipment-assignments")
def create_assignment(contract_id):
    """Assign equipment by role; the server picks the unit, never the client."""
    authenticate((ROLE_THERAPIST,))
    contract = get_contract(contract_id)
    data = validate(ASSIGNMENT_FIELDS)
    if contract["billing_status"] == "CLOSED":
        raise ApiError("ERR_CONTRACT_CLOSED")
    patient = get_patient(contract["patient_id"])
    if patient["status"] != "ACTIVE":
        raise ApiError("ERR_PATIENT_NOT_ACTIVE")
    if patient["compliance_hold"]:
        raise ApiError("ERR_PATIENT_ON_COMPLIANCE_HOLD")
    role = data["role"]
    cmn = _contract_cmn(contract)
    if role == "PORTABLE":
        indicated = (
            cmn is not None
            and cmn["portable_prescribed"]
            and patient["mobility_profile"] in AMBULATORY
        )
        if not indicated:
            raise ApiError("ERR_PORTABLE_NOT_INDICATED")
    _require_cmn_active(contract)
    for existing in placements_for_contract(contract["id"]):
        if existing["role"] == role and existing["status"] in ("RESERVED", "PLACED"):
            raise ApiError("ERR_ROLE_ALREADY_OCCUPIED")
    branch = get_branch(patient["branch_id"])
    unit = select_equipment_unit(branch, role, cmn["prescribed_lpm"])
    if unit is None:
        raise ApiError("ERR_NO_ELIGIBLE_EQUIPMENT")
    row = base_row()
    row.update(
        {
            "contract_id": contract["id"],
            "equipment_unit_id": unit["id"],
            "role": role,
            "status": "RESERVED",
            "placed_at": None,
            "removed_at": None,
            "removal_reason": "NONE",
            "malfunction_count": 0,
            "last_symptom": "NONE",
            "last_severity_tier": "NONE",
        }
    )
    db.placements[row["id"]] = row
    unit["status"] = "RESERVED"
    touch(unit)
    touch(contract)
    return respond(placement_out(row), 201)


@bp.post("/rental-contracts/<contract_id>/travel-authorizations")
def create_travel_authorization(contract_id):
    """Request travel supply; guarded by OCC on the parent contract."""
    authenticate((ROLE_INTAKE,))
    contract = get_contract(contract_id)
    data = validate(TRAVEL_FIELDS)
    branch = None
    if data["receiving_branch_id"] is not None:
        branch = get_branch(data["receiving_branch_id"])
    if data["expected_contract_version"] != contract["version"]:
        raise ApiError("ERR_STALE_CONTRACT_VERSION")
    if contract["billing_status"] == "CLOSED":
        raise ApiError("ERR_CONTRACT_CLOSED")
    patient = get_patient(contract["patient_id"])
    if patient["status"] != "ACTIVE":
        raise ApiError("ERR_PATIENT_NOT_ACTIVE")
    if patient["compliance_hold"]:
        raise ApiError("ERR_PATIENT_ON_COMPLIANCE_HOLD")
    cmn = _require_cmn_active(contract)
    if branch is not None and branch["id"] == patient["branch_id"]:
        raise ApiError("ERR_RECEIVING_BRANCH_INVALID")
    depart = parse_datetime(data["depart_utc"])
    ret = parse_datetime(data["return_utc"])
    if ret <= depart:
        raise ApiError("ERR_INVALID_TRAVEL_INTERVAL")
    for other in sorted_rows(db.travel_authorizations.values()):
        if other["contract_id"] != contract["id"]:
            continue
        if other["status"] not in ("REQUESTED", "APPROVED"):
            continue
        if depart <= other["return_utc"] and other["depart_utc"] <= ret:
            raise ApiError("ERR_TRAVEL_INTERVAL_CONFLICT")
    supply = travel_supply(
        depart,
        ret,
        patient["altitude_feet"],
        data["destination_altitude_feet"],
        cmn["prescribed_lpm"],
        cmn["hours_per_day"],
    )
    if supply["supply_cylinders_authorized"] > MAX_TRAVEL_CYLINDERS:
        raise ApiError("ERR_TRAVEL_SUPPLY_EXCEEDS_LIMIT")
    row = base_row()
    row.update(
        {
            "contract_id": contract["id"],
            "receiving_branch_id": branch["id"] if branch is not None else None,
            "destination_altitude_feet": data["destination_altitude_feet"],
            "depart_utc": depart,
            "return_utc": ret,
            "status": "REQUESTED",
            "decided_by_user_id": None,
        }
    )
    row.update(supply)
    db.travel_authorizations[row["id"]] = row
    touch(contract)
    return respond(travel_authorization_out(row), 201)
