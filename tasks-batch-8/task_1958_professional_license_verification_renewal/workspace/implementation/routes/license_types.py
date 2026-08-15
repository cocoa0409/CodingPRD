"""License type endpoints (PRD 3.1)."""
from flask import Blueprint

from db import DB, new_id, now_iso
from errors import ApiError
from middleware import ALL_ROLES, auth
from response import ok, ok_list
from serializers import license_type_view
from util import as_bool, as_enum, as_int, as_num, as_str, body, pagination_args, required

bp = Blueprint("license_types", __name__, url_prefix="/licensing/license-types")

REIMBURSEMENT_MODES = ("RECEIPT_BASED", "FLAT_SCHEDULE")


@bp.post("")
def create_license_type():
    auth(["ComplianceAdmin"])
    data = body()
    code = as_str(required(data, "code"), "code")
    name = as_str(required(data, "name"), "name")
    ce_hours = as_num(required(data, "ce_hours_required_per_cycle"), "ce_hours_required_per_cycle")
    if ce_hours < 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "ce_hours_required_per_cycle must be >= 0")
    cycle_length = as_int(required(data, "cycle_length_months"), "cycle_length_months")
    if not 1 <= cycle_length <= 120:
        raise ApiError("ERR_INVALID_REQUEST", 400, "cycle_length_months must be in 1..120")
    freq_days = as_int(required(data, "verification_frequency_days"), "verification_frequency_days")
    if not 1 <= freq_days <= 3650:
        raise ApiError("ERR_INVALID_REQUEST", 400, "verification_frequency_days must be in 1..3650")
    grace_days = as_int(required(data, "grace_period_days"), "grace_period_days")
    if grace_days < 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "grace_period_days must be >= 0")
    req_screening = as_bool(required(data, "requires_exclusion_screening"), "requires_exclusion_screening")
    mode = as_enum(required(data, "reimbursement_mode"), "reimbursement_mode", REIMBURSEMENT_MODES)
    full_cap = as_int(required(data, "reimburse_full_up_to_cents"), "reimburse_full_up_to_cents")
    if full_cap < 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "reimburse_full_up_to_cents must be >= 0")
    half_cap = as_int(required(data, "reimburse_half_up_to_cents"), "reimburse_half_up_to_cents")
    if half_cap < full_cap:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400,
            "reimburse_half_up_to_cents must be >= reimburse_full_up_to_cents",
        )
    flat_amount = as_int(required(data, "flat_schedule_amount_cents"), "flat_schedule_amount_cents")
    if flat_amount < 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "flat_schedule_amount_cents must be >= 0")
    hard_cap = as_int(required(data, "hard_claim_cap_cents"), "hard_claim_cap_cents")
    if hard_cap <= 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "hard_claim_cap_cents must be > 0")

    # Uniqueness: license-type code (PRD 2.8 step 8).
    for lt in DB["license_types"].values():
        if lt["code"] == code:
            raise ApiError(
                "ERR_DUPLICATE_LICENSE_TYPE_CODE", 409,
                "A license type with this code already exists",
            )

    ts = now_iso()
    lt = {
        "id": new_id(),
        "code": code,
        "name": name,
        "ce_hours_required_per_cycle": ce_hours,
        "cycle_length_months": cycle_length,
        "verification_frequency_days": freq_days,
        "grace_period_days": grace_days,
        "requires_exclusion_screening": req_screening,
        "reimbursement_mode": mode,
        "reimburse_full_up_to_cents": full_cap,
        "reimburse_half_up_to_cents": half_cap,
        "flat_schedule_amount_cents": flat_amount,
        "hard_claim_cap_cents": hard_cap,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    DB["license_types"][lt["id"]] = lt
    return ok(license_type_view(lt), status=201)


@bp.get("")
def list_license_types():
    auth(ALL_ROLES)
    limit, offset = pagination_args()
    items = sorted(DB["license_types"].values(), key=lambda x: x["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([license_type_view(x) for x in page], total, limit, offset)


@bp.get("/<lid>")
def get_license_type(lid):
    auth(ALL_ROLES)
    lt = DB["license_types"].get(lid)
    if lt is None:
        raise ApiError("ERR_NOT_FOUND", 404, "License type not found")
    return ok(license_type_view(lt))
