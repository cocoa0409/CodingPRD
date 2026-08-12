"""Teleradiology Read Distribution API — Flask entry point.

All storage is in-memory (db.store), starting empty on every boot. Domain
timestamps come from the logical clock (default 2026-05-01T00:00:00Z), never
the wall clock.
"""

import os
from datetime import timedelta

from flask import Flask, request

from db import store
import errors as E
from errors import ApiError
from middleware import (
    authenticate, require_roles,
    ROLE_PLATFORM_ADMIN, ROLE_DISPATCH_OPS, ROLE_RADIOLOGIST,
    ROLE_CLIENT_HOSPITAL_USER, ROLE_QA_REVIEWER,
)
from response import success_object, success_list, error_response
import services as S
from util import (
    new_id, iso_z, parse_iso, parse_date, touch, stamp_new, body,
    req_str, opt_str, req_enum, opt_enum, req_int, opt_int, opt_number,
    opt_bool, req_str_list, opt_str_list, pagination_params, paginate,
    sort_created, check_occ, shift_intersects_after_hours,
)

app = Flask(__name__)


@app.before_request
def _apply_logical_clock_sweeps():
    # Lazy, idempotent sweep: the logical clock defines which shifts are
    # ACTIVE, which grants have expired, and which notices are overdue, so
    # time-derived state must be current for every request, not only those
    # that advance the clock.
    with store.lock:
        S.run_clock_sweeps()


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err.error_id, err.message, err.http_status)


@app.errorhandler(404)
def handle_404(err):
    return error_response("ERR_NOT_FOUND", "Route not found", 404)


@app.errorhandler(405)
def handle_405(err):
    return error_response("ERR_NOT_FOUND", "Method not allowed", 404)


@app.errorhandler(Exception)
def handle_unexpected(err):
    return error_response("ERR_INTERNAL", str(err), 500)


# ===========================================================================
# test-driving / platform
# ===========================================================================

@app.route("/telerad/_clock/set_current_utc", methods=["POST"])
def set_clock():
    principal = authenticate()
    require_roles(principal, {ROLE_PLATFORM_ADMIN})
    data = body()
    to_iso = req_str(data, "to_iso8601")
    with store.lock:
        store.set_clock(to_iso)
        S.run_clock_sweeps()
        current = iso_z(store.now())
    return success_object({"current_utc": current}, 200)


@app.route("/telerad/_seed/finalized-studies", methods=["POST"])
def seed_finalized_studies():
    principal = authenticate()
    require_roles(principal, {ROLE_PLATFORM_ADMIN})
    data = body()
    hospital_id = req_str(data, "hospital_id")
    count = req_int(data, "count")
    received_at_raw = req_str(data, "received_at")
    final_signed_at_raw = req_str(data, "final_signed_at")
    modality = opt_enum(data, "modality", S.MODALITIES, default="CT")
    priority = opt_enum(data, "priority", S.PRIORITIES, default="ROUTINE")
    body_part_group = opt_enum(data, "body_part_group", S.BODY_PART_GROUPS, default="OTHER")
    critical_finding = opt_bool(data, "critical_finding", default=False)
    with store.lock:
        hospital = store.hospitals.get(hospital_id)
        if hospital is None:
            E.raise_err(E.ERR_HOSPITAL_NOT_FOUND, "Hospital not found")
        received_at = parse_iso(received_at_raw, "received_at")
        final_signed_at = parse_iso(final_signed_at_raw, "final_signed_at")
        if count < 0:
            E.raise_err(E.ERR_VALIDATION, "count must be >= 0")
        ids = []
        for i in range(count):
            study = {
                "id": new_id(),
                "hospital_id": hospital_id,
                "accession_number": f"SEED-{new_id()}",
                "modality": modality,
                "body_part_group": body_part_group,
                "priority": priority,
                "patient_ref": "seed",
                "state_code": hospital["state_code"],
                "received_at": iso_z(received_at),
                "due_at": iso_z(S.compute_due_at(hospital, priority, received_at)),
                "status": "FINAL_SIGNED",
                "routing_policy_id": None,
                "assigned_radiologist_id": None,
                "excluded_radiologist_ids": [],
                "addendum_count": 0,
                "first_final_signed_at": iso_z(final_signed_at),
                "tat_breached": False,
                "breach_minutes": 0,
            }
            stamp_new(study)
            S.evaluate_tat(study, final_signed_at)
            if critical_finding:
                report = {
                    "id": new_id(),
                    "assignment_id": None,
                    "study_id": study["id"],
                    "radiologist_id": None,
                    "report_type": "FINAL",
                    "findings_text": "",
                    "impression_text": "",
                    "critical_finding": True,
                    "discrepancy_grade": None,
                    "status": "SIGNED",
                    "signed_at": iso_z(final_signed_at),
                    "credited_rvu": 0.0,
                }
                stamp_new(report)
                store.reports[report["id"]] = report
            store.studies[study["id"]] = study
            ids.append(study["id"])
    return success_object({"created_count": len(ids), "study_ids": ids}, 201)


# ===========================================================================
# ClientHospital
# ===========================================================================

@app.route("/telerad/hospitals", methods=["POST"])
def create_hospital():
    principal = authenticate()
    require_roles(principal, {ROLE_PLATFORM_ADMIN})
    data = body()
    hospital = {
        "id": new_id(),
        "name": req_str(data, "name"),
        "state_code": req_str(data, "state_code"),
        "status": "ONBOARDING",
        "credentialing_mode": opt_enum(data, "credentialing_mode", {"BY_PROXY", "INDEPENDENT"}, "BY_PROXY"),
        "pricing_mode": opt_enum(data, "pricing_mode", {"MARGINAL", "FLAT_TIER"}, "MARGINAL"),
        "tat_stat_minutes": opt_int(data, "tat_stat_minutes", 60),
        "tat_urgent_minutes": opt_int(data, "tat_urgent_minutes", 240),
        "tat_routine_minutes": opt_int(data, "tat_routine_minutes", 1440),
        "penalty_per_breach_minute_cents": opt_int(data, "penalty_per_breach_minute_cents", 50),
        "breach_penalty_cap_cents": opt_int(data, "breach_penalty_cap_cents", 20000),
    }
    with store.lock:
        stamp_new(hospital)
        store.hospitals[hospital["id"]] = hospital
    return success_object(hospital, 201)


@app.route("/telerad/hospitals/<hid>", methods=["GET"])
def get_hospital(hid):
    principal = authenticate()
    require_roles(principal, {ROLE_PLATFORM_ADMIN, ROLE_DISPATCH_OPS, ROLE_CLIENT_HOSPITAL_USER})
    with store.lock:
        hospital = store.hospitals.get(hid)
        if hospital is None:
            E.raise_err(E.ERR_HOSPITAL_NOT_FOUND, "Hospital not found")
    return success_object(hospital, 200)


@app.route("/telerad/hospitals", methods=["GET"])
def list_hospitals():
    principal = authenticate()
    require_roles(principal, {ROLE_PLATFORM_ADMIN, ROLE_DISPATCH_OPS})
    limit, offset = pagination_params()
    status = request.args.get("status")
    with store.lock:
        rows = [h for h in store.hospitals.values() if status is None or h["status"] == status]
        rows = sort_created(rows)
        page, total = paginate(rows, limit, offset)
    return success_list(page, limit, offset, total, 200)


@app.route("/telerad/hospitals/<hid>/activate", methods=["POST"])
def activate_hospital(hid):
    principal = authenticate()
    require_roles(principal, {ROLE_PLATFORM_ADMIN})
    with store.lock:
        hospital = store.hospitals.get(hid)
        if hospital is None:
            E.raise_err(E.ERR_HOSPITAL_NOT_FOUND, "Hospital not found")
        if hospital["status"] not in ("ONBOARDING", "SUSPENDED"):
            E.raise_err(E.ERR_INVALID_STATE, "Hospital cannot be activated from its current state")
        hospital["status"] = "ACTIVE"
        touch(hospital)
    return success_object(hospital, 200)


@app.route("/telerad/hospitals/<hid>/suspend", methods=["POST"])
def suspend_hospital(hid):
    principal = authenticate()
    require_roles(principal, {ROLE_PLATFORM_ADMIN})
    with store.lock:
        hospital = store.hospitals.get(hid)
        if hospital is None:
            E.raise_err(E.ERR_HOSPITAL_NOT_FOUND, "Hospital not found")
        if hospital["status"] != "ACTIVE":
            E.raise_err(E.ERR_INVALID_STATE, "Only an ACTIVE hospital can be suspended")
        hospital["status"] = "SUSPENDED"
        touch(hospital)
    return success_object(hospital, 200)


# ===========================================================================
# Radiologist
# ===========================================================================

@app.route("/telerad/radiologists", methods=["POST"])
def create_radiologist():
    principal = authenticate()
    require_roles(principal, {ROLE_PLATFORM_ADMIN})
    data = body()
    rad = {
        "id": new_id(),
        "full_name": req_str(data, "full_name"),
        "subspecialties": req_str_list(data, "subspecialties", S.SUBSPECIALTIES),
        "license_states": req_str_list(data, "license_states"),
        "status": opt_enum(data, "status", {"ACTIVE", "ON_LEAVE", "INACTIVE"}, "ACTIVE"),
        "fatigue_cap_rvu": opt_number(data, "fatigue_cap_rvu", 30.0),
        "max_concurrent_stat": opt_int(data, "max_concurrent_stat", 3),
        "reserved_rvu": 0.0,
        "completed_rvu_24h": 0.0,
        "stat_active_count": 0,
        "pending_critical_count": 0,
    }
    with store.lock:
        stamp_new(rad)
        store.radiologists[rad["id"]] = rad
    return success_object(rad, 201)


@app.route("/telerad/radiologists/<rid>", methods=["GET"])
def get_radiologist(rid):
    principal = authenticate()
    require_roles(principal, {ROLE_PLATFORM_ADMIN, ROLE_DISPATCH_OPS, ROLE_RADIOLOGIST, ROLE_QA_REVIEWER})
    with store.lock:
        rad = store.radiologists.get(rid)
        if rad is None:
            E.raise_err(E.ERR_RADIOLOGIST_NOT_FOUND, "Radiologist not found")
        S.recompute_radiologist_counters(rad)
    return success_object(rad, 200)


@app.route("/telerad/radiologists", methods=["GET"])
def list_radiologists():
    principal = authenticate()
    require_roles(principal, {ROLE_PLATFORM_ADMIN, ROLE_DISPATCH_OPS, ROLE_QA_REVIEWER})
    limit, offset = pagination_params()
    status = request.args.get("status")
    state_code = request.args.get("state_code")
    subspecialty = request.args.get("subspecialty")
    with store.lock:
        rows = []
        for r in store.radiologists.values():
            if status is not None and r["status"] != status:
                continue
            if state_code is not None and state_code not in r["license_states"]:
                continue
            if subspecialty is not None and subspecialty not in r["subspecialties"]:
                continue
            S.recompute_radiologist_counters(r)
            rows.append(r)
        rows = sort_created(rows)
        page, total = paginate(rows, limit, offset)
    return success_list(page, limit, offset, total, 200)


@app.route("/telerad/radiologists/<rid>", methods=["PATCH"])
def patch_radiologist(rid):
    principal = authenticate()
    require_roles(principal, {ROLE_PLATFORM_ADMIN})
    data = body()
    with store.lock:
        rad = store.radiologists.get(rid)
        if rad is None:
            E.raise_err(E.ERR_RADIOLOGIST_NOT_FOUND, "Radiologist not found")
        # enum / type validation for supplied fields
        new_status = opt_enum(data, "status", {"ACTIVE", "ON_LEAVE", "INACTIVE"}, None)
        new_cap = opt_number(data, "fatigue_cap_rvu", None)
        new_stat = opt_int(data, "max_concurrent_stat", None)
        new_subs = opt_str_list(data, "subspecialties", S.SUBSPECIALTIES, None)
        new_states = opt_str_list(data, "license_states", None, None)
        if new_status is not None and new_status != rad["status"]:
            current = rad["status"]
            allowed = {("ACTIVE", "ON_LEAVE"), ("ON_LEAVE", "ACTIVE"),
                       ("ACTIVE", "INACTIVE"), ("ON_LEAVE", "INACTIVE")}
            if (current, new_status) not in allowed:
                E.raise_err(E.ERR_INVALID_STATE, f"Radiologist cannot transition {current} -> {new_status}")
            if new_status == "INACTIVE" and current == "ACTIVE":
                has_active = any(a for a in store.assignments.values()
                                 if a["radiologist_id"] == rid and a["status"] == "ACTIVE")
                if has_active:
                    E.raise_err(E.ERR_INVALID_STATE,
                                "ACTIVE radiologist with ACTIVE assignments cannot retire to INACTIVE")
            rad["status"] = new_status
        if new_cap is not None:
            rad["fatigue_cap_rvu"] = new_cap
        if new_stat is not None:
            rad["max_concurrent_stat"] = new_stat
        if new_subs is not None:
            rad["subspecialties"] = new_subs
        if new_states is not None:
            rad["license_states"] = new_states
        touch(rad)
    return success_object(rad, 200)


# ===========================================================================
# CoverageShift
# ===========================================================================

@app.route("/telerad/shifts", methods=["POST"])
def create_shift():
    principal = authenticate()
    require_roles(principal, {ROLE_PLATFORM_ADMIN})
    data = body()
    radiologist_id = req_str(data, "radiologist_id")
    starts_at_raw = req_str(data, "starts_at")
    ends_at_raw = req_str(data, "ends_at")
    modalities = req_str_list(data, "modalities", S.MODALITIES)
    starts_at = parse_iso(starts_at_raw, "starts_at")
    ends_at = parse_iso(ends_at_raw, "ends_at")
    if ends_at <= starts_at:
        E.raise_err(E.ERR_VALIDATION, "ends_at must be strictly after starts_at")
    with store.lock:
        rad = store.radiologists.get(radiologist_id)
        if rad is None:
            E.raise_err(E.ERR_RADIOLOGIST_NOT_FOUND, "Radiologist not found")
        for other in store.shifts.values():
            if (other["radiologist_id"] == radiologist_id
                    and other["status"] in ("SCHEDULED", "ACTIVE")):
                o_start = parse_iso(other["starts_at"], "starts_at")
                o_end = parse_iso(other["ends_at"], "ends_at")
                if starts_at < o_end and o_start < ends_at:
                    E.raise_err(E.ERR_SHIFT_OVERLAP, "Shift window overlaps an existing shift")
        shift = {
            "id": new_id(),
            "radiologist_id": radiologist_id,
            "starts_at": iso_z(starts_at),
            "ends_at": iso_z(ends_at),
            "modalities": modalities,
            "status": "SCHEDULED",
            "after_hours": shift_intersects_after_hours(starts_at, ends_at),
        }
        stamp_new(shift)
        store.shifts[shift["id"]] = shift
    return success_object(shift, 201)


@app.route("/telerad/shifts/<sid>", methods=["GET"])
def get_shift(sid):
    principal = authenticate()
    require_roles(principal, {ROLE_PLATFORM_ADMIN, ROLE_DISPATCH_OPS, ROLE_RADIOLOGIST})
    with store.lock:
        shift = store.shifts.get(sid)
        if shift is None:
            E.raise_err(E.ERR_SHIFT_NOT_FOUND, "Shift not found")
    return success_object(shift, 200)


@app.route("/telerad/shifts", methods=["GET"])
def list_shifts():
    principal = authenticate()
    require_roles(principal, {ROLE_PLATFORM_ADMIN, ROLE_DISPATCH_OPS, ROLE_RADIOLOGIST})
    limit, offset = pagination_params()
    radiologist_id = request.args.get("radiologist_id")
    status = request.args.get("status")
    with store.lock:
        rows = [s for s in store.shifts.values()
                if (radiologist_id is None or s["radiologist_id"] == radiologist_id)
                and (status is None or s["status"] == status)]
        rows = sort_created(rows)
        page, total = paginate(rows, limit, offset)
    return success_list(page, limit, offset, total, 200)


@app.route("/telerad/shifts/<sid>/cancel", methods=["POST"])
def cancel_shift(sid):
    principal = authenticate()
    require_roles(principal, {ROLE_PLATFORM_ADMIN})
    with store.lock:
        shift = store.shifts.get(sid)
        if shift is None:
            E.raise_err(E.ERR_SHIFT_NOT_FOUND, "Shift not found")
        if shift["status"] != "SCHEDULED":
            E.raise_err(E.ERR_INVALID_STATE, "Only a SCHEDULED shift can be cancelled")
        shift["status"] = "CANCELLED"
        touch(shift)
    return success_object(shift, 200)


# ===========================================================================
# RoutingPolicy
# ===========================================================================

@app.route("/telerad/routing-policies", methods=["POST"])
def create_routing_policy():
    principal = authenticate()
    require_roles(principal, {ROLE_PLATFORM_ADMIN})
    data = body()
    hospital_id = req_str(data, "hospital_id")
    modality = req_enum(data, "modality", S.MODALITIES)
    body_part_group = req_enum(data, "body_part_group", S.BODY_PART_GROUPS)
    priority = req_enum(data, "priority", S.PRIORITIES)
    required_subspecialty = req_enum(data, "required_subspecialty", S.SUBSPECIALTIES)
    prelim_required = opt_bool(data, "prelim_required", False)
    with store.lock:
        hospital = store.hospitals.get(hospital_id)
        if hospital is None:
            E.raise_err(E.ERR_HOSPITAL_NOT_FOUND, "Hospital not found")
        check_occ(data, "expected_hospital_version", hospital["version"])
        # retire any same-key ACTIVE policy
        for p in store.routing_policies.values():
            if (p["hospital_id"] == hospital_id and p["modality"] == modality
                    and p["body_part_group"] == body_part_group and p["priority"] == priority
                    and p["status"] == "ACTIVE"):
                p["status"] = "RETIRED"
                touch(p)
        policy = {
            "id": new_id(),
            "hospital_id": hospital_id,
            "modality": modality,
            "body_part_group": body_part_group,
            "priority": priority,
            "required_subspecialty": required_subspecialty,
            "prelim_required": prelim_required,
            "status": "ACTIVE",
        }
        stamp_new(policy)
        store.routing_policies[policy["id"]] = policy
        touch(hospital)  # side effect: hospital version increments
    return success_object(policy, 201)


@app.route("/telerad/routing-policies/<pid>", methods=["GET"])
def get_routing_policy(pid):
    principal = authenticate()
    require_roles(principal, {ROLE_PLATFORM_ADMIN, ROLE_DISPATCH_OPS})
    with store.lock:
        policy = store.routing_policies.get(pid)
        if policy is None:
            E.raise_err(E.ERR_POLICY_NOT_FOUND, "Routing policy not found")
    return success_object(policy, 200)


@app.route("/telerad/routing-policies", methods=["GET"])
def list_routing_policies():
    principal = authenticate()
    require_roles(principal, {ROLE_PLATFORM_ADMIN, ROLE_DISPATCH_OPS})
    limit, offset = pagination_params()
    hospital_id = request.args.get("hospital_id")
    status = request.args.get("status")
    with store.lock:
        rows = [p for p in store.routing_policies.values()
                if (hospital_id is None or p["hospital_id"] == hospital_id)
                and (status is None or p["status"] == status)]
        rows = sort_created(rows)
        page, total = paginate(rows, limit, offset)
    return success_list(page, limit, offset, total, 200)


# ===========================================================================
# CredentialGrant
# ===========================================================================

def _grant_overlap(radiologist_id, hospital_id, valid_from, valid_until, exclude_id=None):
    for g in store.credential_grants.values():
        if g["id"] == exclude_id:
            continue
        if (g["radiologist_id"] == radiologist_id and g["hospital_id"] == hospital_id
                and g["status"] in ("PENDING", "GRANTED", "SUSPENDED")):
            if valid_from <= g["valid_until"] and g["valid_from"] <= valid_until:
                return True
    return False


@app.route("/telerad/credential-grants", methods=["POST"])
def create_credential_grant():
    principal = authenticate()
    require_roles(principal, {ROLE_PLATFORM_ADMIN})
    data = body()
    radiologist_id = req_str(data, "radiologist_id")
    hospital_id = req_str(data, "hospital_id")
    grant_type = req_enum(data, "grant_type", {"BY_PROXY", "INDEPENDENT"})
    valid_from_raw = req_str(data, "valid_from")
    valid_until_raw = req_str(data, "valid_until")
    valid_from = parse_date(valid_from_raw, "valid_from")
    valid_until = parse_date(valid_until_raw, "valid_until")
    if valid_until < valid_from:
        E.raise_err(E.ERR_VALIDATION, "valid_until must be on or after valid_from")
    with store.lock:
        if radiologist_id not in store.radiologists:
            E.raise_err(E.ERR_RADIOLOGIST_NOT_FOUND, "Radiologist not found")
        hospital = store.hospitals.get(hospital_id)
        if hospital is None:
            E.raise_err(E.ERR_HOSPITAL_NOT_FOUND, "Hospital not found")
        if grant_type != hospital["credentialing_mode"]:
            E.raise_err(E.ERR_GRANT_TYPE_MISMATCH,
                        "grant_type must equal the hospital's credentialing_mode")
        if _grant_overlap(radiologist_id, hospital_id, valid_from_raw, valid_until_raw):
            E.raise_err(E.ERR_GRANT_OVERLAP, "Grant window overlaps an existing grant")
        grant = {
            "id": new_id(),
            "radiologist_id": radiologist_id,
            "hospital_id": hospital_id,
            "grant_type": grant_type,
            "valid_from": valid_from.isoformat(),
            "valid_until": valid_until.isoformat(),
            "status": "PENDING",
        }
        stamp_new(grant)
        store.credential_grants[grant["id"]] = grant
    return success_object(grant, 201)


@app.route("/telerad/credential-grants/<gid>", methods=["GET"])
def get_credential_grant(gid):
    principal = authenticate()
    require_roles(principal, {ROLE_PLATFORM_ADMIN, ROLE_DISPATCH_OPS, ROLE_RADIOLOGIST})
    with store.lock:
        grant = store.credential_grants.get(gid)
        if grant is None:
            E.raise_err(E.ERR_GRANT_NOT_FOUND, "Credential grant not found")
    return success_object(grant, 200)


@app.route("/telerad/credential-grants", methods=["GET"])
def list_credential_grants():
    principal = authenticate()
    require_roles(principal, {ROLE_PLATFORM_ADMIN, ROLE_DISPATCH_OPS, ROLE_RADIOLOGIST})
    limit, offset = pagination_params()
    radiologist_id = request.args.get("radiologist_id")
    hospital_id = request.args.get("hospital_id")
    status = request.args.get("status")
    with store.lock:
        rows = [g for g in store.credential_grants.values()
                if (radiologist_id is None or g["radiologist_id"] == radiologist_id)
                and (hospital_id is None or g["hospital_id"] == hospital_id)
                and (status is None or g["status"] == status)]
        rows = sort_created(rows)
        page, total = paginate(rows, limit, offset)
    return success_list(page, limit, offset, total, 200)


def _grant_action(gid, allowed_from, target):
    principal = authenticate()
    require_roles(principal, {ROLE_PLATFORM_ADMIN})
    with store.lock:
        grant = store.credential_grants.get(gid)
        if grant is None:
            E.raise_err(E.ERR_GRANT_NOT_FOUND, "Credential grant not found")
        if grant["status"] != allowed_from:
            E.raise_err(E.ERR_INVALID_STATE,
                        f"Grant must be {allowed_from} for this transition")
        grant["status"] = target
        touch(grant)
    return success_object(grant, 200)


@app.route("/telerad/credential-grants/<gid>/grant", methods=["POST"])
def grant_grant(gid):
    return _grant_action(gid, "PENDING", "GRANTED")


@app.route("/telerad/credential-grants/<gid>/suspend", methods=["POST"])
def suspend_grant(gid):
    return _grant_action(gid, "GRANTED", "SUSPENDED")


@app.route("/telerad/credential-grants/<gid>/reinstate", methods=["POST"])
def reinstate_grant(gid):
    principal = authenticate()
    require_roles(principal, {ROLE_PLATFORM_ADMIN})
    with store.lock:
        grant = store.credential_grants.get(gid)
        if grant is None:
            E.raise_err(E.ERR_GRANT_NOT_FOUND, "Credential grant not found")
        if grant["status"] != "SUSPENDED":
            E.raise_err(E.ERR_INVALID_STATE, "Only a SUSPENDED grant can be reinstated")
        valid_until = parse_date(grant["valid_until"], "valid_until")
        if store.now().date() > valid_until:
            E.raise_err(E.ERR_INVALID_STATE,
                        "Grant validity window has passed; the grant must expire first")
        grant["status"] = "GRANTED"
        touch(grant)
    return success_object(grant, 200)


@app.route("/telerad/credential-grants/<gid>/revoke", methods=["POST"])
def revoke_grant(gid):
    return _grant_action(gid, "GRANTED", "REVOKED")


@app.route("/telerad/credential-grants/<gid>/renew", methods=["POST"])
def renew_grant(gid):
    principal = authenticate()
    require_roles(principal, {ROLE_PLATFORM_ADMIN})
    data = body()
    valid_from_raw = req_str(data, "valid_from")
    valid_until_raw = req_str(data, "valid_until")
    valid_from = parse_date(valid_from_raw, "valid_from")
    valid_until = parse_date(valid_until_raw, "valid_until")
    if valid_until < valid_from:
        E.raise_err(E.ERR_VALIDATION, "valid_until must be on or after valid_from")
    with store.lock:
        grant = store.credential_grants.get(gid)
        if grant is None:
            E.raise_err(E.ERR_GRANT_NOT_FOUND, "Credential grant not found")
        if grant["status"] != "EXPIRED":
            E.raise_err(E.ERR_INVALID_STATE, "Only an EXPIRED grant can be renewed")
        if _grant_overlap(grant["radiologist_id"], grant["hospital_id"],
                          valid_from_raw, valid_until_raw, exclude_id=gid):
            E.raise_err(E.ERR_GRANT_OVERLAP, "Renewed window overlaps another grant")
        grant["valid_from"] = valid_from.isoformat()
        grant["valid_until"] = valid_until.isoformat()
        grant["status"] = "PENDING"
        touch(grant)
    return success_object(grant, 200)


# ===========================================================================
# Study
# ===========================================================================

@app.route("/telerad/studies", methods=["POST"])
def create_study():
    principal = authenticate()
    require_roles(principal, {ROLE_CLIENT_HOSPITAL_USER})
    data = body()
    hospital_id = req_str(data, "hospital_id")
    if hospital_id != principal.user_id:
        E.raise_err(E.ERR_UNAUTHORIZED, "hospital_id must equal X-User-ID")
    accession_number = req_str(data, "accession_number")
    modality = req_enum(data, "modality", S.MODALITIES)
    body_part_group = req_enum(data, "body_part_group", S.BODY_PART_GROUPS)
    priority = req_enum(data, "priority", S.PRIORITIES)
    patient_ref = req_str(data, "patient_ref")
    with store.lock:
        hospital = store.hospitals.get(hospital_id)
        if hospital is None:
            E.raise_err(E.ERR_HOSPITAL_NOT_FOUND, "Hospital not found")
        if hospital["status"] != "ACTIVE":
            E.raise_err(E.ERR_HOSPITAL_NOT_ACTIVE, "Hospital is not ACTIVE")
        for s in store.studies.values():
            if (s["hospital_id"] == hospital_id
                    and s["accession_number"] == accession_number
                    and s["status"] != "CANCELLED"):
                E.raise_err(E.ERR_DUPLICATE_ACCESSION,
                            "Accession number already in use for this hospital")
        received = store.now()
        study = {
            "id": new_id(),
            "hospital_id": hospital_id,
            "accession_number": accession_number,
            "modality": modality,
            "body_part_group": body_part_group,
            "priority": priority,
            "patient_ref": patient_ref,
            "state_code": hospital["state_code"],
            "received_at": iso_z(received),
            "due_at": iso_z(S.compute_due_at(hospital, priority, received)),
            "status": "RECEIVED",
            "routing_policy_id": None,
            "assigned_radiologist_id": None,
            "excluded_radiologist_ids": [],
            "addendum_count": 0,
            "first_final_signed_at": None,
            "tat_breached": False,
            "breach_minutes": 0,
        }
        stamp_new(study)
        store.studies[study["id"]] = study
    return success_object(study, 201)


@app.route("/telerad/studies/<sid>", methods=["GET"])
def get_study(sid):
    principal = authenticate()
    require_roles(principal, {ROLE_PLATFORM_ADMIN, ROLE_DISPATCH_OPS, ROLE_RADIOLOGIST,
                              ROLE_CLIENT_HOSPITAL_USER, ROLE_QA_REVIEWER})
    with store.lock:
        study = store.studies.get(sid)
        if study is None:
            E.raise_err(E.ERR_STUDY_NOT_FOUND, "Study not found")
        if (principal.role == ROLE_CLIENT_HOSPITAL_USER
                and study["hospital_id"] != principal.user_id):
            E.raise_err(E.ERR_UNAUTHORIZED, "Study belongs to another hospital")
    return success_object(study, 200)


@app.route("/telerad/studies", methods=["GET"])
def list_studies():
    principal = authenticate()
    require_roles(principal, {ROLE_PLATFORM_ADMIN, ROLE_DISPATCH_OPS, ROLE_RADIOLOGIST,
                              ROLE_CLIENT_HOSPITAL_USER, ROLE_QA_REVIEWER})
    limit, offset = pagination_params()
    hospital_id = request.args.get("hospital_id")
    routing_policy_id = request.args.get("routing_policy_id")
    assigned_radiologist_id = request.args.get("assigned_radiologist_id")
    status = request.args.get("status")
    priority = request.args.get("priority")
    with store.lock:
        rows = []
        for s in store.studies.values():
            if principal.role == ROLE_CLIENT_HOSPITAL_USER and s["hospital_id"] != principal.user_id:
                continue
            if hospital_id is not None and s["hospital_id"] != hospital_id:
                continue
            if routing_policy_id is not None and s["routing_policy_id"] != routing_policy_id:
                continue
            if assigned_radiologist_id is not None and s["assigned_radiologist_id"] != assigned_radiologist_id:
                continue
            if status is not None and s["status"] != status:
                continue
            if priority is not None and s["priority"] != priority:
                continue
            rows.append(s)
        rows = sort_created(rows)
        page, total = paginate(rows, limit, offset)
    return success_list(page, limit, offset, total, 200)


@app.route("/telerad/studies/<sid>/route", methods=["POST"])
def route_study(sid):
    principal = authenticate()
    require_roles(principal, {ROLE_DISPATCH_OPS})
    with store.lock:
        study = store.studies.get(sid)
        if study is None:
            E.raise_err(E.ERR_STUDY_NOT_FOUND, "Study not found")
        hospital = store.hospitals.get(study["hospital_id"])
        if hospital is not None and hospital["status"] != "ACTIVE":
            E.raise_err(E.ERR_HOSPITAL_NOT_ACTIVE, "Hospital is not ACTIVE")
        if study["status"] != "RECEIVED":
            E.raise_err(E.ERR_INVALID_STATE, "Only a RECEIVED study can be routed")
        matches = [p for p in store.routing_policies.values()
                   if p["hospital_id"] == study["hospital_id"]
                   and p["modality"] == study["modality"]
                   and p["body_part_group"] == study["body_part_group"]
                   and p["priority"] == study["priority"]
                   and p["status"] == "ACTIVE"]
        if len(matches) != 1:
            E.raise_err(E.ERR_NO_ROUTING_POLICY, "No ACTIVE routing policy matches this study")
        study["routing_policy_id"] = matches[0]["id"]
        study["status"] = "QUEUED"
        touch(study)
    return success_object(study, 200)


@app.route("/telerad/studies/<sid>/cancel", methods=["POST"])
def cancel_study(sid):
    principal = authenticate()
    require_roles(principal, {ROLE_CLIENT_HOSPITAL_USER, ROLE_DISPATCH_OPS})
    with store.lock:
        study = store.studies.get(sid)
        if study is None:
            E.raise_err(E.ERR_STUDY_NOT_FOUND, "Study not found")
        if (principal.role == ROLE_CLIENT_HOSPITAL_USER
                and study["hospital_id"] != principal.user_id):
            E.raise_err(E.ERR_UNAUTHORIZED, "Study belongs to another hospital")
        if study["status"] not in ("RECEIVED", "QUEUED", "ASSIGNED", "IN_PROGRESS"):
            E.raise_err(E.ERR_INVALID_STATE, "Study cannot be cancelled from its current state")
        active = S.active_assignment_for_study(sid)
        study["status"] = "CANCELLED"
        study["assigned_radiologist_id"] = None
        touch(study)
        if active is not None:
            S.release_assignment_cascade(active)
    return success_object(study, 200)


@app.route("/telerad/studies/<sid>/request-addendum", methods=["POST"])
def request_addendum(sid):
    principal = authenticate()
    require_roles(principal, {ROLE_CLIENT_HOSPITAL_USER})
    with store.lock:
        study = store.studies.get(sid)
        if study is None:
            E.raise_err(E.ERR_STUDY_NOT_FOUND, "Study not found")
        if study["hospital_id"] != principal.user_id:
            E.raise_err(E.ERR_UNAUTHORIZED, "Study belongs to another hospital")
        if study["status"] != "FINAL_SIGNED":
            E.raise_err(E.ERR_INVALID_STATE, "Only a FINAL_SIGNED study can request an addendum")
        if S.open_case_for_study(sid) is not None:
            E.raise_err(E.ERR_OPEN_DISCREPANCY_EXISTS,
                        "A non-terminal discrepancy case exists for this study")
        study["status"] = "AMENDMENT_PENDING"
        touch(study)
    return success_object(study, 200)


# ===========================================================================
# Assignment
# ===========================================================================

@app.route("/telerad/assignments", methods=["POST"])
def create_assignment():
    principal = authenticate()
    require_roles(principal, {ROLE_DISPATCH_OPS})
    data = body()
    study_id = req_str(data, "study_id")
    radiologist_id = data.get("radiologist_id")
    if radiologist_id is not None and not isinstance(radiologist_id, str):
        E.raise_err(E.ERR_VALIDATION, "radiologist_id must be a string")
    with store.lock:
        study = store.studies.get(study_id)
        if study is None:
            E.raise_err(E.ERR_STUDY_NOT_FOUND, "Study not found")
        if radiologist_id is not None and radiologist_id not in store.radiologists:
            E.raise_err(E.ERR_RADIOLOGIST_NOT_FOUND, "Radiologist not found")
        check_occ(data, "expected_study_version", study["version"])
        if study["status"] not in ("QUEUED", "PRELIMINARY_SIGNED", "AMENDMENT_PENDING"):
            E.raise_err(E.ERR_INVALID_STATE, "Study is not assignable in its current state")
        if S.active_assignment_for_study(study_id) is not None:
            E.raise_err(E.ERR_INVALID_STATE, "Study already has an ACTIVE assignment")

        policy = store.routing_policies.get(study["routing_policy_id"]) \
            if study["routing_policy_id"] else None
        prelim = S.signed_prelim_for_study(study_id)
        if policy is not None and policy["prelim_required"] and prelim is None:
            phase = "PRELIMINARY"
        else:
            phase = "FINAL"
        rvu_value = S.study_rvu(study)
        prelim_signer_id = prelim["radiologist_id"] if prelim is not None else None

        if radiologist_id is None:
            chosen = S.auto_select_radiologist(study, policy, rvu_value, phase, prelim_signer_id)
            auto_selected = True
        else:
            chosen = store.radiologists[radiologist_id]
            failure = S.selector_check_radiologist(
                chosen, study, policy, rvu_value, phase, prelim_signer_id,
                enforce_prelim_signer_gate=False)
            if failure is not None:
                spec, message = failure
                E.raise_err(spec, message)
            auto_selected = False

        assignment = {
            "id": new_id(),
            "study_id": study_id,
            "radiologist_id": chosen["id"],
            "phase": phase,
            "reserved_rvu": float(rvu_value),
            "status": "ACTIVE",
            "auto_selected": auto_selected,
        }
        stamp_new(assignment)
        store.assignments[assignment["id"]] = assignment
        study["assigned_radiologist_id"] = chosen["id"]
        study["status"] = "ASSIGNED"
        touch(study)
        S.recompute_radiologist_counters(chosen)
    return success_object(assignment, 201)


@app.route("/telerad/assignments/<aid>", methods=["GET"])
def get_assignment(aid):
    principal = authenticate()
    require_roles(principal, {ROLE_PLATFORM_ADMIN, ROLE_DISPATCH_OPS, ROLE_RADIOLOGIST, ROLE_QA_REVIEWER})
    with store.lock:
        assignment = store.assignments.get(aid)
        if assignment is None:
            E.raise_err(E.ERR_ASSIGNMENT_NOT_FOUND, "Assignment not found")
        if (principal.role == ROLE_RADIOLOGIST
                and assignment["radiologist_id"] != principal.user_id):
            E.raise_err(E.ERR_UNAUTHORIZED, "Assignment belongs to another radiologist")
    return success_object(assignment, 200)


@app.route("/telerad/assignments", methods=["GET"])
def list_assignments():
    principal = authenticate()
    require_roles(principal, {ROLE_PLATFORM_ADMIN, ROLE_DISPATCH_OPS, ROLE_RADIOLOGIST, ROLE_QA_REVIEWER})
    limit, offset = pagination_params()
    study_id = request.args.get("study_id")
    radiologist_id = request.args.get("radiologist_id")
    status = request.args.get("status")
    with store.lock:
        rows = []
        for a in store.assignments.values():
            if principal.role == ROLE_RADIOLOGIST and a["radiologist_id"] != principal.user_id:
                continue
            if study_id is not None and a["study_id"] != study_id:
                continue
            if radiologist_id is not None and a["radiologist_id"] != radiologist_id:
                continue
            if status is not None and a["status"] != status:
                continue
            rows.append(a)
        rows = sort_created(rows)
        page, total = paginate(rows, limit, offset)
    return success_list(page, limit, offset, total, 200)


@app.route("/telerad/assignments/<aid>/accept", methods=["POST"])
def accept_assignment(aid):
    principal = authenticate()
    require_roles(principal, {ROLE_RADIOLOGIST})
    with store.lock:
        assignment = store.assignments.get(aid)
        if assignment is None:
            E.raise_err(E.ERR_ASSIGNMENT_NOT_FOUND, "Assignment not found")
        if assignment["radiologist_id"] != principal.user_id:
            E.raise_err(E.ERR_UNAUTHORIZED, "Only the assigned radiologist may accept")
        if assignment["status"] != "ACTIVE":
            E.raise_err(E.ERR_INVALID_STATE, "Assignment is not ACTIVE")
        study = store.studies.get(assignment["study_id"])
        if study is None or study["status"] != "ASSIGNED":
            E.raise_err(E.ERR_INVALID_STATE, "Study is not in ASSIGNED state")
        study["status"] = "IN_PROGRESS"
        touch(study)
        touch(assignment)
    return success_object(assignment, 200)


@app.route("/telerad/assignments/<aid>/release", methods=["POST"])
def release_assignment(aid):
    principal = authenticate()
    require_roles(principal, {ROLE_RADIOLOGIST})
    with store.lock:
        assignment = store.assignments.get(aid)
        if assignment is None:
            E.raise_err(E.ERR_ASSIGNMENT_NOT_FOUND, "Assignment not found")
        if assignment["radiologist_id"] != principal.user_id:
            E.raise_err(E.ERR_UNAUTHORIZED, "Only the assigned radiologist may release")
        if assignment["status"] != "ACTIVE":
            E.raise_err(E.ERR_INVALID_STATE, "Assignment is not ACTIVE")
        study = store.studies.get(assignment["study_id"])
        if study is None or study["status"] != "ASSIGNED":
            E.raise_err(E.ERR_INVALID_STATE, "Study is not in ASSIGNED state")
        study["status"] = "QUEUED"
        study["assigned_radiologist_id"] = None
        if principal.user_id not in study["excluded_radiologist_ids"]:
            study["excluded_radiologist_ids"].append(principal.user_id)
        touch(study)
        S.release_assignment_cascade(assignment)
    return success_object(assignment, 200)


# ===========================================================================
# Report
# ===========================================================================

@app.route("/telerad/reports", methods=["POST"])
def create_report():
    principal = authenticate()
    require_roles(principal, {ROLE_RADIOLOGIST})
    data = body()
    assignment_id = req_str(data, "assignment_id")
    report_type = req_enum(data, "report_type", {"PRELIMINARY", "FINAL", "ADDENDUM"})
    findings_text = req_str(data, "findings_text")
    impression_text = req_str(data, "impression_text")
    critical_finding = opt_bool(data, "critical_finding", False)
    discrepancy_grade = data.get("discrepancy_grade")
    if discrepancy_grade is not None:
        if isinstance(discrepancy_grade, bool) or not isinstance(discrepancy_grade, int) \
                or discrepancy_grade < 0 or discrepancy_grade > 3:
            E.raise_err(E.ERR_VALIDATION, "discrepancy_grade must be an integer in 0..3")
    with store.lock:
        assignment = store.assignments.get(assignment_id)
        if assignment is None:
            E.raise_err(E.ERR_ASSIGNMENT_NOT_FOUND, "Assignment not found")
        if assignment["radiologist_id"] != principal.user_id:
            E.raise_err(E.ERR_UNAUTHORIZED, "Only the assignment's radiologist may draft its report")
        if assignment["status"] != "ACTIVE":
            E.raise_err(E.ERR_INVALID_STATE, "Assignment is not ACTIVE")
        study = store.studies.get(assignment["study_id"])
        if study is None or study["status"] != "IN_PROGRESS":
            E.raise_err(E.ERR_INVALID_STATE, "Study is not IN_PROGRESS")
        report = {
            "id": new_id(),
            "assignment_id": assignment_id,
            "study_id": assignment["study_id"],
            "radiologist_id": assignment["radiologist_id"],
            "report_type": report_type,
            "findings_text": findings_text,
            "impression_text": impression_text,
            "critical_finding": critical_finding,
            "discrepancy_grade": discrepancy_grade,
            "status": "DRAFT",
            "signed_at": None,
            "credited_rvu": 0.0,
        }
        stamp_new(report)
        store.reports[report["id"]] = report
    return success_object(report, 201)


@app.route("/telerad/reports/<rid>", methods=["GET"])
def get_report(rid):
    principal = authenticate()
    require_roles(principal, {ROLE_PLATFORM_ADMIN, ROLE_DISPATCH_OPS, ROLE_RADIOLOGIST,
                              ROLE_QA_REVIEWER, ROLE_CLIENT_HOSPITAL_USER})
    with store.lock:
        report = store.reports.get(rid)
        if report is None:
            E.raise_err(E.ERR_REPORT_NOT_FOUND, "Report not found")
        if principal.role == ROLE_RADIOLOGIST and report["radiologist_id"] != principal.user_id:
            E.raise_err(E.ERR_UNAUTHORIZED, "Report belongs to another radiologist")
        if principal.role == ROLE_CLIENT_HOSPITAL_USER:
            study = store.studies.get(report["study_id"])
            if study is None or study["hospital_id"] != principal.user_id:
                E.raise_err(E.ERR_UNAUTHORIZED, "Report belongs to another hospital")
    return success_object(report, 200)


@app.route("/telerad/reports", methods=["GET"])
def list_reports():
    principal = authenticate()
    require_roles(principal, {ROLE_PLATFORM_ADMIN, ROLE_DISPATCH_OPS, ROLE_RADIOLOGIST,
                              ROLE_QA_REVIEWER, ROLE_CLIENT_HOSPITAL_USER})
    limit, offset = pagination_params()
    study_id = request.args.get("study_id")
    assignment_id = request.args.get("assignment_id")
    radiologist_id = request.args.get("radiologist_id")
    report_type = request.args.get("report_type")
    status = request.args.get("status")
    with store.lock:
        rows = []
        for r in store.reports.values():
            if principal.role == ROLE_RADIOLOGIST and r["radiologist_id"] != principal.user_id:
                continue
            if principal.role == ROLE_CLIENT_HOSPITAL_USER:
                st = store.studies.get(r["study_id"])
                if st is None or st["hospital_id"] != principal.user_id:
                    continue
            if study_id is not None and r["study_id"] != study_id:
                continue
            if assignment_id is not None and r["assignment_id"] != assignment_id:
                continue
            if radiologist_id is not None and r["radiologist_id"] != radiologist_id:
                continue
            if report_type is not None and r["report_type"] != report_type:
                continue
            if status is not None and r["status"] != status:
                continue
            rows.append(r)
        rows = sort_created(rows)
        page, total = paginate(rows, limit, offset)
    return success_list(page, limit, offset, total, 200)


@app.route("/telerad/reports/<rid>/sign", methods=["POST"])
def sign_report(rid):
    principal = authenticate()
    require_roles(principal, {ROLE_RADIOLOGIST})
    with store.lock:
        report = store.reports.get(rid)
        if report is None:
            E.raise_err(E.ERR_REPORT_NOT_FOUND, "Report not found")
        if report["radiologist_id"] != principal.user_id:
            E.raise_err(E.ERR_UNAUTHORIZED, "Only the report's author may sign it")
        if report["status"] != "DRAFT":
            E.raise_err(E.ERR_INVALID_STATE, "Report is not DRAFT")
        study = store.studies.get(report["study_id"])
        if study is None:
            E.raise_err(E.ERR_STUDY_NOT_FOUND, "Study not found")
        if study["status"] != "IN_PROGRESS":
            E.raise_err(E.ERR_INVALID_STATE, "Study is not IN_PROGRESS")
        assignment = store.assignments.get(report["assignment_id"]) \
            if report.get("assignment_id") else None
        if assignment is None:
            E.raise_err(E.ERR_ASSIGNMENT_NOT_FOUND, "Assignment not found")
        if assignment["status"] != "ACTIVE":
            E.raise_err(E.ERR_INVALID_STATE, "Assignment is not ACTIVE")

        policy = store.routing_policies.get(study["routing_policy_id"]) \
            if study["routing_policy_id"] else None
        prelim = S.signed_prelim_for_study(study["id"])
        report_type = report["report_type"]
        rvu_base = S.study_rvu(study)
        now = store.now()

        if report_type == "PRELIMINARY":
            if policy is None or not policy["prelim_required"]:
                E.raise_err(E.ERR_PRELIM_NOT_PERMITTED,
                            "The resolved policy does not require a preliminary report")
            if prelim is not None:
                E.raise_err(E.ERR_PRELIM_NOT_PERMITTED,
                            "A signed preliminary report already exists for this study")
            credit = S.credit_for_report("PRELIMINARY", rvu_base, None)
            report["status"] = "SIGNED"
            report["signed_at"] = iso_z(now)
            report["credited_rvu"] = credit
            touch(report)
            study["status"] = "PRELIMINARY_SIGNED"
            touch(study)
            S.evaluate_tat(study, now)  # prelim_required: this signature is TAT-relevant
            S.complete_assignment_cascade(assignment, report)
            if report["critical_finding"]:
                S.spawn_critical_notice(report)

        elif report_type == "FINAL":
            if S.signed_final_for_study(study["id"]) is not None:
                E.raise_err(E.ERR_INVALID_STATE, "A signed FINAL report already exists")
            if policy is not None and policy["prelim_required"] and prelim is None:
                E.raise_err(E.ERR_FINAL_NOT_DUE,
                            "Policy requires a signed preliminary before any final")
            if prelim is not None and report["radiologist_id"] == prelim["radiologist_id"]:
                E.raise_err(E.ERR_SAME_READER_CONFLICT,
                            "Final signer must differ from the preliminary signer")
            grade = report["discrepancy_grade"]
            if prelim is not None and grade is None:
                E.raise_err(E.ERR_VALIDATION,
                            "discrepancy_grade is required when a signed preliminary exists")
            credit = S.credit_for_report("FINAL", rvu_base, grade)
            report["status"] = "SIGNED"
            report["signed_at"] = iso_z(now)
            report["credited_rvu"] = credit
            touch(report)
            study["status"] = "FINAL_SIGNED"
            study["first_final_signed_at"] = iso_z(now)
            touch(study)
            if prelim is not None:
                prelim["status"] = "SUPERSEDED"
                touch(prelim)
            S.complete_assignment_cascade(assignment, report)
            if policy is None or not policy["prelim_required"]:
                S.evaluate_tat(study, now)  # no prelim required: final is TAT-relevant
            if grade is not None and grade >= 2 and prelim is not None:
                case = {
                    "id": new_id(),
                    "study_id": study["id"],
                    "prelim_report_id": prelim["id"],
                    "final_report_id": report["id"],
                    "grade": grade,
                    "origin": "AUTO",
                    "status": "OPEN",
                    "reconciliation_note": None,
                    "reconciled_by": None,
                }
                stamp_new(case)
                store.discrepancy_cases[case["id"]] = case
            if report["critical_finding"]:
                S.spawn_critical_notice(report)

        else:  # ADDENDUM
            if study["first_final_signed_at"] is None:
                E.raise_err(E.ERR_ADDENDUM_NOT_PERMITTED,
                            "Addendum requires a previously signed final")
            if prelim is not None and report["radiologist_id"] == prelim["radiologist_id"]:
                E.raise_err(E.ERR_SAME_READER_CONFLICT,
                            "Addendum signer must differ from the preliminary signer")
            report["status"] = "SIGNED"
            report["signed_at"] = iso_z(now)
            report["credited_rvu"] = 0.0
            touch(report)
            study["status"] = "FINAL_SIGNED"
            study["addendum_count"] = study["addendum_count"] + 1
            touch(study)
            S.complete_assignment_cascade(assignment, report)
            if report["critical_finding"]:
                S.spawn_critical_notice(report)

    return success_object(report, 200)


# ===========================================================================
# DiscrepancyCase
# ===========================================================================

@app.route("/telerad/discrepancy-cases", methods=["POST"])
def create_discrepancy_case():
    principal = authenticate()
    require_roles(principal, {ROLE_QA_REVIEWER})
    data = body()
    prelim_report_id = req_str(data, "prelim_report_id")
    final_report_id = req_str(data, "final_report_id")
    with store.lock:
        prelim = store.reports.get(prelim_report_id)
        if prelim is None:
            E.raise_err(E.ERR_REPORT_NOT_FOUND, "Preliminary report not found")
        final = store.reports.get(final_report_id)
        if final is None:
            E.raise_err(E.ERR_REPORT_NOT_FOUND, "Final report not found")
        if prelim["report_type"] != "PRELIMINARY" or final["report_type"] != "FINAL":
            E.raise_err(E.ERR_VALIDATION,
                        "prelim_report_id / final_report_id must reference those report types")
        if prelim["study_id"] != final["study_id"]:
            E.raise_err(E.ERR_VALIDATION, "Reports must belong to the same study")
        for c in store.discrepancy_cases.values():
            if (c["prelim_report_id"] == prelim_report_id
                    and c["final_report_id"] == final_report_id
                    and c["status"] in S.NON_TERMINAL_CASE_STATUSES):
                E.raise_err(E.ERR_OPEN_DISCREPANCY_EXISTS,
                            "A non-terminal case already exists for this report pair")
        case = {
            "id": new_id(),
            "study_id": prelim["study_id"],
            "prelim_report_id": prelim_report_id,
            "final_report_id": final_report_id,
            "grade": final["discrepancy_grade"],
            "origin": "MANUAL",
            "status": "OPEN",
            "reconciliation_note": None,
            "reconciled_by": None,
        }
        stamp_new(case)
        store.discrepancy_cases[case["id"]] = case
    return success_object(case, 201)


@app.route("/telerad/discrepancy-cases/<cid>", methods=["GET"])
def get_discrepancy_case(cid):
    principal = authenticate()
    require_roles(principal, {ROLE_PLATFORM_ADMIN, ROLE_DISPATCH_OPS, ROLE_QA_REVIEWER})
    with store.lock:
        case = store.discrepancy_cases.get(cid)
        if case is None:
            E.raise_err(E.ERR_CASE_NOT_FOUND, "Discrepancy case not found")
    return success_object(case, 200)


@app.route("/telerad/discrepancy-cases", methods=["GET"])
def list_discrepancy_cases():
    principal = authenticate()
    require_roles(principal, {ROLE_PLATFORM_ADMIN, ROLE_DISPATCH_OPS, ROLE_QA_REVIEWER})
    limit, offset = pagination_params()
    study_id = request.args.get("study_id")
    prelim_report_id = request.args.get("prelim_report_id")
    final_report_id = request.args.get("final_report_id")
    status = request.args.get("status")
    with store.lock:
        rows = [c for c in store.discrepancy_cases.values()
                if (study_id is None or c["study_id"] == study_id)
                and (prelim_report_id is None or c["prelim_report_id"] == prelim_report_id)
                and (final_report_id is None or c["final_report_id"] == final_report_id)
                and (status is None or c["status"] == status)]
        rows = sort_created(rows)
        page, total = paginate(rows, limit, offset)
    return success_list(page, limit, offset, total, 200)


def _case_action(cid, allowed_from, target):
    principal = authenticate()
    require_roles(principal, {ROLE_QA_REVIEWER})
    with store.lock:
        case = store.discrepancy_cases.get(cid)
        if case is None:
            E.raise_err(E.ERR_CASE_NOT_FOUND, "Discrepancy case not found")
        if case["status"] != allowed_from:
            E.raise_err(E.ERR_INVALID_STATE,
                        f"Case must be {allowed_from} for this transition")
        case["status"] = target
        touch(case)
    return success_object(case, 200)


@app.route("/telerad/discrepancy-cases/<cid>/open-peer-review", methods=["POST"])
def case_open_peer_review(cid):
    return _case_action(cid, "OPEN", "PEER_REVIEW")


@app.route("/telerad/discrepancy-cases/<cid>/close-no-action", methods=["POST"])
def case_close_no_action(cid):
    principal = authenticate()
    require_roles(principal, {ROLE_QA_REVIEWER})
    with store.lock:
        case = store.discrepancy_cases.get(cid)
        if case is None:
            E.raise_err(E.ERR_CASE_NOT_FOUND, "Discrepancy case not found")
        if case["status"] != "OPEN":
            E.raise_err(E.ERR_INVALID_STATE, "Only an OPEN case can be closed with no action")
        if case["grade"] is not None and case["grade"] > 1:
            E.raise_err(E.ERR_INVALID_STATE, "Only grade <= 1 cases may be closed with no action")
        case["status"] = "NO_ACTION_CLOSED"
        touch(case)
    return success_object(case, 200)


@app.route("/telerad/discrepancy-cases/<cid>/escalate", methods=["POST"])
def case_escalate(cid):
    return _case_action(cid, "PEER_REVIEW", "ESCALATED_QI")


@app.route("/telerad/discrepancy-cases/<cid>/reconcile", methods=["POST"])
def case_reconcile(cid):
    principal = authenticate()
    require_roles(principal, {ROLE_QA_REVIEWER})
    data = body()
    note = req_str(data, "reconciliation_note")
    with store.lock:
        case = store.discrepancy_cases.get(cid)
        if case is None:
            E.raise_err(E.ERR_CASE_NOT_FOUND, "Discrepancy case not found")
        if case["status"] not in ("PEER_REVIEW", "ESCALATED_QI"):
            E.raise_err(E.ERR_INVALID_STATE,
                        "Case must be PEER_REVIEW or ESCALATED_QI to reconcile")
        prelim = store.reports.get(case["prelim_report_id"])
        final = store.reports.get(case["final_report_id"])
        signer_ids = {r["radiologist_id"] for r in (prelim, final) if r is not None}
        if principal.user_id in signer_ids:
            E.raise_err(E.ERR_SELF_RECONCILIATION_FORBIDDEN,
                        "Reconciler must differ from both report signers")
        case["status"] = "RECONCILED"
        case["reconciliation_note"] = note
        case["reconciled_by"] = principal.user_id
        touch(case)
    return success_object(case, 200)


# ===========================================================================
# CriticalResultNotice
# ===========================================================================

@app.route("/telerad/critical-notices/<nid>", methods=["GET"])
def get_notice(nid):
    principal = authenticate()
    require_roles(principal, {ROLE_PLATFORM_ADMIN, ROLE_DISPATCH_OPS, ROLE_RADIOLOGIST,
                              ROLE_CLIENT_HOSPITAL_USER, ROLE_QA_REVIEWER})
    with store.lock:
        notice = store.critical_notices.get(nid)
        if notice is None:
            E.raise_err(E.ERR_NOTICE_NOT_FOUND, "Critical-result notice not found")
        _check_notice_read_scope(principal, notice)
    return success_object(notice, 200)


def _check_notice_read_scope(principal, notice):
    if principal.role == ROLE_RADIOLOGIST and notice["radiologist_id"] != principal.user_id:
        E.raise_err(E.ERR_UNAUTHORIZED, "Notice belongs to another radiologist")
    if principal.role == ROLE_CLIENT_HOSPITAL_USER:
        study = store.studies.get(notice["study_id"])
        if study is None or study["hospital_id"] != principal.user_id:
            E.raise_err(E.ERR_UNAUTHORIZED, "Notice belongs to another hospital")


@app.route("/telerad/critical-notices", methods=["GET"])
def list_notices():
    principal = authenticate()
    require_roles(principal, {ROLE_PLATFORM_ADMIN, ROLE_DISPATCH_OPS, ROLE_RADIOLOGIST,
                              ROLE_CLIENT_HOSPITAL_USER, ROLE_QA_REVIEWER})
    limit, offset = pagination_params()
    report_id = request.args.get("report_id")
    study_id = request.args.get("study_id")
    radiologist_id = request.args.get("radiologist_id")
    status = request.args.get("status")
    with store.lock:
        rows = []
        for n in store.critical_notices.values():
            if principal.role == ROLE_RADIOLOGIST and n["radiologist_id"] != principal.user_id:
                continue
            if principal.role == ROLE_CLIENT_HOSPITAL_USER:
                st = store.studies.get(n["study_id"])
                if st is None or st["hospital_id"] != principal.user_id:
                    continue
            if report_id is not None and n["report_id"] != report_id:
                continue
            if study_id is not None and n["study_id"] != study_id:
                continue
            if radiologist_id is not None and n["radiologist_id"] != radiologist_id:
                continue
            if status is not None and n["status"] != status:
                continue
            rows.append(n)
        rows = sort_created(rows)
        page, total = paginate(rows, limit, offset)
    return success_list(page, limit, offset, total, 200)


@app.route("/telerad/critical-notices/<nid>/record-notification", methods=["POST"])
def record_notification(nid):
    principal = authenticate()
    require_roles(principal, {ROLE_RADIOLOGIST})
    data = body()
    notified_party_name = req_str(data, "notified_party_name")
    with store.lock:
        notice = store.critical_notices.get(nid)
        if notice is None:
            E.raise_err(E.ERR_NOTICE_NOT_FOUND, "Critical-result notice not found")
        if notice["radiologist_id"] != principal.user_id:
            E.raise_err(E.ERR_UNAUTHORIZED, "Only the signing radiologist may record notification")
        if notice["status"] not in ("PENDING", "ESCALATED"):
            E.raise_err(E.ERR_INVALID_STATE, "Notice cannot be notified from its current state")
        notice["status"] = "NOTIFIED"
        notice["notified_party_name"] = notified_party_name
        notice["notified_at"] = iso_z(store.now())
        touch(notice)
    return success_object(notice, 200)


@app.route("/telerad/critical-notices/<nid>/confirm-readback", methods=["POST"])
def confirm_readback(nid):
    principal = authenticate()
    require_roles(principal, {ROLE_CLIENT_HOSPITAL_USER})
    data = body()
    readback_confirmed_by = req_str(data, "readback_confirmed_by")
    with store.lock:
        notice = store.critical_notices.get(nid)
        if notice is None:
            E.raise_err(E.ERR_NOTICE_NOT_FOUND, "Critical-result notice not found")
        study = store.studies.get(notice["study_id"])
        if study is None or study["hospital_id"] != principal.user_id:
            E.raise_err(E.ERR_UNAUTHORIZED, "Notice belongs to another hospital")
        if notice["status"] not in ("NOTIFIED", "ESCALATED") or notice["notified_at"] is None:
            E.raise_err(E.ERR_INVALID_STATE, "Notice cannot be read-back confirmed from its current state")
        notice["status"] = "READBACK_CONFIRMED"
        notice["readback_confirmed_by"] = readback_confirmed_by
        notice["readback_at"] = iso_z(store.now())
        touch(notice)
        rad = store.radiologists.get(notice["radiologist_id"])
        if rad is not None:
            S.recompute_radiologist_counters(rad)
    return success_object(notice, 200)


@app.route("/telerad/critical-notices/<nid>/escalate", methods=["POST"])
def escalate_notice(nid):
    principal = authenticate()
    require_roles(principal, {ROLE_DISPATCH_OPS})
    with store.lock:
        notice = store.critical_notices.get(nid)
        if notice is None:
            E.raise_err(E.ERR_NOTICE_NOT_FOUND, "Critical-result notice not found")
        if notice["status"] not in ("PENDING", "NOTIFIED"):
            E.raise_err(E.ERR_INVALID_STATE, "Notice cannot be escalated from its current state")
        notice["status"] = "ESCALATED"
        notice["escalation_count"] += 1
        touch(notice)
    return success_object(notice, 200)


# ===========================================================================
# BillingPeriod / Invoice
# ===========================================================================

@app.route("/telerad/billing-periods", methods=["POST"])
def create_billing_period():
    principal = authenticate()
    require_roles(principal, {ROLE_PLATFORM_ADMIN})
    data = body()
    hospital_id = req_str(data, "hospital_id")
    period_start_raw = req_str(data, "period_start")
    period_end_raw = req_str(data, "period_end")
    period_start = parse_date(period_start_raw, "period_start")
    period_end = parse_date(period_end_raw, "period_end")
    if period_end < period_start:
        E.raise_err(E.ERR_VALIDATION, "period_end must be on or after period_start")
    with store.lock:
        if hospital_id not in store.hospitals:
            E.raise_err(E.ERR_HOSPITAL_NOT_FOUND, "Hospital not found")
        for p in store.billing_periods.values():
            if (p["hospital_id"] == hospital_id
                    and p["status"] in ("OPEN", "CLOSED", "INVOICED")):
                if period_start_raw <= p["period_end"] and p["period_start"] <= period_end_raw:
                    E.raise_err(E.ERR_PERIOD_OVERLAP,
                                "Period overlaps an existing billing period")
        period = {
            "id": new_id(),
            "hospital_id": hospital_id,
            "period_start": period_start.isoformat(),
            "period_end": period_end.isoformat(),
            "status": "OPEN",
        }
        stamp_new(period)
        store.billing_periods[period["id"]] = period
    return success_object(period, 201)


@app.route("/telerad/billing-periods/<pid>", methods=["GET"])
def get_billing_period(pid):
    principal = authenticate()
    require_roles(principal, {ROLE_PLATFORM_ADMIN, ROLE_CLIENT_HOSPITAL_USER})
    with store.lock:
        period = store.billing_periods.get(pid)
        if period is None:
            E.raise_err(E.ERR_BILLING_PERIOD_NOT_FOUND, "Billing period not found")
        if (principal.role == ROLE_CLIENT_HOSPITAL_USER
                and period["hospital_id"] != principal.user_id):
            E.raise_err(E.ERR_UNAUTHORIZED, "Period belongs to another hospital")
    return success_object(period, 200)


@app.route("/telerad/billing-periods", methods=["GET"])
def list_billing_periods():
    principal = authenticate()
    require_roles(principal, {ROLE_PLATFORM_ADMIN, ROLE_CLIENT_HOSPITAL_USER})
    limit, offset = pagination_params()
    hospital_id = request.args.get("hospital_id")
    status = request.args.get("status")
    with store.lock:
        rows = []
        for p in store.billing_periods.values():
            if principal.role == ROLE_CLIENT_HOSPITAL_USER and p["hospital_id"] != principal.user_id:
                continue
            if hospital_id is not None and p["hospital_id"] != hospital_id:
                continue
            if status is not None and p["status"] != status:
                continue
            rows.append(p)
        rows = sort_created(rows)
        page, total = paginate(rows, limit, offset)
    return success_list(page, limit, offset, total, 200)


@app.route("/telerad/billing-periods/<pid>/close", methods=["POST"])
def close_billing_period(pid):
    principal = authenticate()
    require_roles(principal, {ROLE_PLATFORM_ADMIN})
    with store.lock:
        period = store.billing_periods.get(pid)
        if period is None:
            E.raise_err(E.ERR_BILLING_PERIOD_NOT_FOUND, "Billing period not found")
        if period["status"] != "OPEN":
            E.raise_err(E.ERR_INVALID_STATE, "Only an OPEN period can be closed")
        period["status"] = "CLOSED"
        touch(period)
    return success_object(period, 200)


@app.route("/telerad/billing-periods/<pid>/reopen", methods=["POST"])
def reopen_billing_period(pid):
    principal = authenticate()
    require_roles(principal, {ROLE_PLATFORM_ADMIN})
    with store.lock:
        period = store.billing_periods.get(pid)
        if period is None:
            E.raise_err(E.ERR_BILLING_PERIOD_NOT_FOUND, "Billing period not found")
        if period["status"] != "CLOSED":
            E.raise_err(E.ERR_INVALID_STATE, "Only a CLOSED period can be reopened")
        period_end = parse_date(period["period_end"], "period_end")
        if store.now().date() > period_end + timedelta(days=7):
            E.raise_err(E.ERR_REOPEN_WINDOW_EXPIRED,
                        "Reopen grace window has expired")
        period["status"] = "OPEN"
        touch(period)
    return success_object(period, 200)


@app.route("/telerad/billing-periods/<pid>/generate-invoice", methods=["POST"])
def generate_invoice(pid):
    principal = authenticate()
    require_roles(principal, {ROLE_PLATFORM_ADMIN})
    data = body()
    with store.lock:
        period = store.billing_periods.get(pid)
        if period is None:
            E.raise_err(E.ERR_BILLING_PERIOD_NOT_FOUND, "Billing period not found")
        check_occ(data, "expected_billing_period_version", period["version"])
        if period["status"] not in ("CLOSED", "INVOICED"):
            E.raise_err(E.ERR_INVALID_STATE,
                        "Period must be CLOSED or INVOICED to generate an invoice")
        hospital = store.hospitals.get(period["hospital_id"])
        if hospital is None:
            E.raise_err(E.ERR_HOSPITAL_NOT_FOUND, "Hospital not found")
        computed = S.compute_invoice(hospital, period)
        # supersede prior CURRENT invoice
        for inv in store.invoices.values():
            if inv["billing_period_id"] == pid and inv["status"] == "CURRENT":
                inv["status"] = "VOID"
                touch(inv)
        invoice = {
            "id": new_id(),
            "billing_period_id": pid,
            "hospital_id": period["hospital_id"],
            "status": "CURRENT",
            **computed,
        }
        stamp_new(invoice)
        store.invoices[invoice["id"]] = invoice
        period["status"] = "INVOICED"
        touch(period)
    return success_object(invoice, 201)


@app.route("/telerad/invoices/<iid>", methods=["GET"])
def get_invoice(iid):
    principal = authenticate()
    require_roles(principal, {ROLE_PLATFORM_ADMIN, ROLE_CLIENT_HOSPITAL_USER})
    with store.lock:
        invoice = store.invoices.get(iid)
        if invoice is None:
            E.raise_err(E.ERR_INVOICE_NOT_FOUND, "Invoice not found")
        if (principal.role == ROLE_CLIENT_HOSPITAL_USER
                and invoice["hospital_id"] != principal.user_id):
            E.raise_err(E.ERR_UNAUTHORIZED, "Invoice belongs to another hospital")
    return success_object(invoice, 200)


@app.route("/telerad/invoices", methods=["GET"])
def list_invoices():
    principal = authenticate()
    require_roles(principal, {ROLE_PLATFORM_ADMIN, ROLE_CLIENT_HOSPITAL_USER})
    limit, offset = pagination_params()
    billing_period_id = request.args.get("billing_period_id")
    hospital_id = request.args.get("hospital_id")
    status = request.args.get("status")
    with store.lock:
        rows = []
        for inv in store.invoices.values():
            if principal.role == ROLE_CLIENT_HOSPITAL_USER and inv["hospital_id"] != principal.user_id:
                continue
            if billing_period_id is not None and inv["billing_period_id"] != billing_period_id:
                continue
            if hospital_id is not None and inv["hospital_id"] != hospital_id:
                continue
            if status is not None and inv["status"] != status:
                continue
            rows.append(inv)
        rows = sort_created(rows)
        page, total = paginate(rows, limit, offset)
    return success_list(page, limit, offset, total, 200)


# ===========================================================================

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
