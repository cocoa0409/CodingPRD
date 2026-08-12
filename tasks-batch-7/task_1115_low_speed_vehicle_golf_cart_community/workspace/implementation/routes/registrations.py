"""VehicleRegistration endpoints: draft creation, activate, renew,
finalize-renewal, suspend, reinstate, revoke. Fee + renewal logic per §3.5/§3.6."""
from datetime import timedelta
from flask import Blueprint, request

import db
from db import touch
from errors import (err_not_found, err_invalid_state, err_equipment,
                    err_duplicate_registration, err_inspection_not_passed,
                    err_insurance_missing, err_holder_not_eligible,
                    err_holder_barred, err_insufficient_funds,
                    err_renewal_window)
from middleware import get_caller, require_role, check_holder_ownership
from response import ok_object, ok_list
from services import calc, validate as v
from services import engine
from services.serializers import base_entity, registration_view

bp = Blueprint("registrations", __name__)

READ_ROLES = ["PlatformAdmin", "CommunityAdmin", "Inspector", "EnforcementOfficer", "PermitHolder"]


def _community_for(reg):
    holder = db.permit_holders.get(reg["holder_id"])
    if holder is None:
        return None
    return db.communities.get(holder["community_id"])


@bp.post("/api/registrations")
def create_registration():
    data = v.body()
    # Stage 1: schema
    vehicle_id = v.require_str(data, "vehicle_id")
    holder_id = v.require_str(data, "holder_id")
    registration_year = v.require_int(data, "registration_year", 2020, 2100)
    # Stage 2-3
    caller = get_caller()
    require_role(caller, ["PermitHolder"])
    check_holder_ownership(caller, holder_id)
    # Stage 4: body FKs in declared order (vehicle_id, holder_id)
    veh = db.vehicles.get(vehicle_id)
    if veh is None:
        raise err_not_found("Vehicle not found")
    holder = db.permit_holders.get(holder_id)
    if holder is None:
        raise err_not_found("PermitHolder not found")
    # holder_id must equal the vehicle's owning holder
    if veh["holder_id"] != holder_id:
        raise err_not_found("Vehicle does not belong to the supplied holder")
    # Stage 6: safety gate — class equipment minimums
    if veh["vehicle_type"] == "GOLF_CART":
        ok = veh["has_headlights"] and veh["has_brake_lights"]
    else:  # LSV
        ok = (veh["has_headlights"] and veh["has_brake_lights"]
              and veh["has_seatbelts"] and veh["mirror_count"] >= 1)
    if not ok:
        raise err_equipment()
    # Stage 9: annual uniqueness — no non-REVOKED registration for the pair
    for reg in db.registrations.values():
        if (reg["vehicle_id"] == vehicle_id
                and reg["registration_year"] == registration_year
                and reg["status"] != "REVOKED"):
            raise err_duplicate_registration()

    community = db.communities.get(holder["community_id"])
    reg = base_entity()
    reg.update({
        "vehicle_id": vehicle_id,
        "holder_id": holder_id,
        "registration_year": registration_year,
        "status": "DRAFT",
        "finalized_fee_cents": None,
        "late_fee_cents": 0,
        "total_due_cents": 0,
        "paid_cents": 0,
        "renewal_score_provisional": None,
        "renewal_score_audited": None,
        "valid_from": None,
        "expiry_date": None,
        "_community_id": holder["community_id"],
    })
    reg["provisional_fee_cents"] = calc.annual_registration_fee(
        veh, community, holder_id, "provisional")
    db.registrations[reg["id"]] = reg
    return ok_object(registration_view(reg), 201)


@bp.get("/api/registrations/<rid>")
def get_registration(rid):
    caller = get_caller()
    require_role(caller, READ_ROLES)
    reg = db.registrations.get(rid)
    if reg is None:
        raise err_not_found("Registration not found")
    check_holder_ownership(caller, reg["holder_id"])
    return ok_object(registration_view(reg))


@bp.get("/api/registrations")
def list_registrations():
    caller = get_caller()
    require_role(caller, READ_ROLES)
    limit, offset = v.pagination_args()
    vehicle_id = request.args.get("vehicle_id")
    holder_id = request.args.get("holder_id")
    rows = list(db.registrations.values())
    if vehicle_id is not None:
        rows = [r for r in rows if r["vehicle_id"] == vehicle_id]
    if holder_id is not None:
        rows = [r for r in rows if r["holder_id"] == holder_id]
    if caller.role == "PermitHolder":
        rows = [r for r in rows if r["holder_id"] == caller.user_id]
    rows = v.sorted_by_created(rows)
    page, total = v.paginate(rows, limit, offset)
    return ok_list([registration_view(r) for r in page], limit, offset, total)


def _load_registration(rid):
    reg = db.registrations.get(rid)
    if reg is None:
        raise err_not_found("Registration not found")
    return reg


@bp.post("/api/registrations/<rid>/activate")
def activate_registration(rid):
    caller = get_caller()
    require_role(caller, ["PermitHolder"])
    reg = _load_registration(rid)
    check_holder_ownership(caller, reg["holder_id"])
    # Stage 5: state
    if reg["status"] != "DRAFT":
        raise err_invalid_state("Registration is not DRAFT")
    holder = db.permit_holders.get(reg["holder_id"])
    community = db.communities.get(holder["community_id"])
    veh = db.vehicles.get(reg["vehicle_id"])
    # Stage 8 cross-entity gates: inspection, insurance, eligibility, standing
    latest = engine.latest_finalized_inspection(reg["id"])
    if latest is None or latest["status"] != "PASSED":
        raise err_inspection_not_passed()
    if community["insurance_required"] and not engine.has_active_insurance(reg["vehicle_id"]):
        raise err_insurance_missing()
    if holder["eligibility_status"] != "ELIGIBLE":
        raise err_holder_not_eligible()
    if holder["compliance_status"] == "BARRED":
        raise err_holder_barred()
    # Stage 10: wallet sufficiency (equality sufficient)
    total_due = reg["total_due_cents"]
    if holder["wallet_balance_cents"] < total_due:
        raise err_insufficient_funds()

    holder["wallet_balance_cents"] -= total_due
    touch(holder)
    reg["paid_cents"] += total_due
    reg["valid_from"] = db.now()
    reg["expiry_date"] = reg["valid_from"] + timedelta(days=365)
    reg["status"] = "ACTIVE"
    touch(reg)
    return ok_object(registration_view(reg))


@bp.post("/api/registrations/<rid>/renew")
def renew_registration(rid):
    caller = get_caller()
    require_role(caller, ["PermitHolder"])
    reg = _load_registration(rid)
    check_holder_ownership(caller, reg["holder_id"])
    holder = db.permit_holders.get(reg["holder_id"])
    community = db.communities.get(holder["community_id"])
    veh = db.vehicles.get(reg["vehicle_id"])
    now_dt = db.now()
    # Stage 5: state machine from-state
    if reg["status"] not in ("ACTIVE", "EXPIRED"):
        raise err_invalid_state("Registration is not ACTIVE or EXPIRED")
    # Stage 7: temporal window gate
    if reg["status"] == "ACTIVE":
        window_open = reg["expiry_date"] - timedelta(days=community["renewal_window_days"])
        if not (window_open <= now_dt <= reg["expiry_date"]):
            raise err_renewal_window()
    else:  # EXPIRED
        grace_end = reg["expiry_date"] + timedelta(days=community["late_grace_days"])
        if not (reg["expiry_date"] < now_dt <= grace_end):
            raise err_renewal_window()
    # Stage 8: holder not BARRED
    if holder["compliance_status"] == "BARRED":
        raise err_holder_barred()

    if reg["status"] == "ACTIVE":
        reg["provisional_fee_cents"] = calc.annual_registration_fee(
            veh, community, reg["holder_id"], "provisional", as_of=now_dt)
        reg["renewal_score_provisional"] = calc.renewal_compliance_score(
            reg["holder_id"], "provisional", now_dt)
        reg["late_fee_cents"] = 0
        # total_due_cents unchanged until finalize
    else:  # EXPIRED — late renewal
        finalized = calc.annual_registration_fee(
            veh, community, reg["holder_id"], "finalized", as_of=now_dt)
        reg["finalized_fee_cents"] = finalized
        raw_late, total_due = calc.late_renewal_fee(
            finalized, reg["expiry_date"], now_dt, community["late_grace_days"])
        reg["late_fee_cents"] = raw_late
        reg["total_due_cents"] = total_due
        reg["renewal_score_provisional"] = calc.renewal_compliance_score(
            reg["holder_id"], "provisional", now_dt)
    reg["status"] = "RENEWAL_PENDING"
    touch(reg)
    return ok_object(registration_view(reg))


@bp.post("/api/registrations/<rid>/finalize-renewal")
def finalize_renewal(rid):
    caller = get_caller()
    require_role(caller, ["CommunityAdmin"])
    reg = _load_registration(rid)
    if reg["status"] != "RENEWAL_PENDING":
        raise err_invalid_state("Registration is not RENEWAL_PENDING")
    holder = db.permit_holders.get(reg["holder_id"])
    community = db.communities.get(holder["community_id"])
    veh = db.vehicles.get(reg["vehicle_id"])
    now_dt = db.now()

    audited = calc.renewal_compliance_score(reg["holder_id"], "audited", now_dt)
    reg["renewal_score_audited"] = audited
    finalized = calc.annual_registration_fee(
        veh, community, reg["holder_id"], "finalized", as_of=now_dt)
    reg["finalized_fee_cents"] = finalized
    if reg["late_fee_cents"]:
        raw_late, total_due = calc.late_renewal_fee(
            finalized, reg["expiry_date"], now_dt, community["late_grace_days"])
        reg["late_fee_cents"] = raw_late
        reg["total_due_cents"] = total_due
    else:
        reg["total_due_cents"] = min(finalized + reg["late_fee_cents"],
                                     2 * finalized)

    if audited >= calc.RENEWAL_PASS_THRESHOLD:
        # Wallet sufficiency at recomputed total
        if holder["wallet_balance_cents"] < reg["total_due_cents"]:
            raise err_insufficient_funds()
        holder["wallet_balance_cents"] -= reg["total_due_cents"]
        touch(holder)
        reg["paid_cents"] += reg["total_due_cents"]
        reg["expiry_date"] = reg["expiry_date"] + timedelta(days=365)
        reg["status"] = "ACTIVE"
        touch(reg)
    else:
        reg["status"] = "SUSPENDED"
        touch(reg)
    return ok_object(registration_view(reg))


@bp.post("/api/registrations/<rid>/suspend")
def suspend_registration(rid):
    caller = get_caller()
    require_role(caller, ["CommunityAdmin"])
    reg = _load_registration(rid)
    if reg["status"] != "ACTIVE":
        raise err_invalid_state("Registration is not ACTIVE")
    engine.suspend_registration(reg)
    return ok_object(registration_view(reg))


@bp.post("/api/registrations/<rid>/reinstate")
def reinstate_registration(rid):
    caller = get_caller()
    require_role(caller, ["CommunityAdmin"])
    reg = _load_registration(rid)
    if reg["status"] != "SUSPENDED":
        raise err_invalid_state("Registration is not SUSPENDED")
    holder = db.permit_holders.get(reg["holder_id"])
    community = db.communities.get(holder["community_id"])
    if holder["compliance_status"] == "BARRED":
        raise err_holder_barred()
    latest = engine.latest_finalized_inspection(reg["id"])
    if latest is None or latest["status"] != "PASSED":
        raise err_inspection_not_passed()
    if community["insurance_required"] and not engine.has_active_insurance(reg["vehicle_id"]):
        raise err_insurance_missing()
    reg["status"] = "ACTIVE"
    touch(reg)
    return ok_object(registration_view(reg))


@bp.post("/api/registrations/<rid>/revoke")
def revoke_registration(rid):
    caller = get_caller()
    require_role(caller, ["EnforcementOfficer"])
    reg = _load_registration(rid)
    if reg["status"] not in ("ACTIVE", "RENEWAL_PENDING", "SUSPENDED", "EXPIRED"):
        raise err_invalid_state("Registration cannot be revoked from its current state")
    engine.revoke_registration(reg)
    return ok_object(registration_view(reg))
