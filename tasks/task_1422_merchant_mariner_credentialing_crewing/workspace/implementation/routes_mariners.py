"""Mariner registry, lifecycle, and computed reads (PRD 3.1, 3.2, 3.4)."""

from datetime import timedelta

from flask import Blueprint, request

from db import fmt_dt_sec, store
from errors import err
from helpers import (
    get_body,
    opt_int,
    paginate,
    req_enum,
    req_int,
    req_str,
    require_roles,
    scope_mariner_id,
    sorted_items,
)
from response import success
from serialize import ser_mariner
from services import (
    DRUG_CURRENCY_DAYS,
    UPGRADE_REQUIREMENTS,
    cancel_assignment_cascade,
    credential_is_valid,
    medical_is_valid,
    recompute_mariner,
    upgrade_eligibility,
)

bp = Blueprint("mariners", __name__)

HIRE_CHANNELS = ("DIRECT", "UNION_HALL")
RANK_TRACKS = ("DECK", "ENGINE", "STEWARD")

ALL_ROLES = (
    "FleetAdmin",
    "CrewingManager",
    "CredentialingOfficer",
    "PortCaptain",
    "UnionDispatcher",
    "Mariner",
)


def get_mariner_or_404(mariner_id):
    m = store.mariners.get(mariner_id)
    if m is None:
        raise err("ERR_MARINER_NOT_FOUND", "Mariner %s not found" % mariner_id)
    return m


def _activation_gates_met(m):
    """The three activation gates (PRD 3.1)."""
    now = store.clock
    med_ok = any(
        c["mariner_id"] == m["id"] and medical_is_valid(c, now)
        for c in store.medical_certificates.values()
    )
    drug_ok = any(
        t["mariner_id"] == m["id"]
        and t["status"] == "COMPLETED"
        and t["result"] == "NEGATIVE"
        and t["collected_date"] is not None
        and t["collected_date"] + timedelta(days=DRUG_CURRENCY_DAYS) >= now
        for t in store.drug_tests.values()
    )
    cred_ok = any(
        c["mariner_id"] == m["id"] and credential_is_valid(c, now)
        for c in store.credentials.values()
    )
    return med_ok and drug_ok and cred_ok


@bp.route("/mariners", methods=["POST"])
@require_roles("FleetAdmin")
def create_mariner():
    body = get_body()
    full_name = req_str(body, "full_name")
    ref = req_str(body, "mariner_reference_number")
    home_port = req_str(body, "home_port_code")
    hire_channel = req_enum(body, "hire_channel", HIRE_CHANNELS)
    rank_track = req_enum(body, "rank_track", RANK_TRACKS)
    rank_grade = req_int(body, "rank_grade", min_v=1, max_v=9)
    primary = req_str(body, "primary_endorsement_code")
    cap = opt_int(body, "annual_training_cap_cents", default=500000, min_v=0)
    if any(m["mariner_reference_number"] == ref for m in store.mariners.values()):
        raise err(
            "ERR_INVALID_REQUEST",
            "mariner_reference_number %s already exists" % ref,
        )
    m = {
        "full_name": full_name,
        "mariner_reference_number": ref,
        "home_port_code": home_port,
        "hire_channel": hire_channel,
        "rank_track": rank_track,
        "rank_grade": rank_grade,
        "primary_endorsement_code": primary,
        "annual_training_cap_cents": cap,
        "status": "APPLICANT",
        "readiness_posture": "BLOCKED",
        "readiness_reasons": ["STATUS_NOT_ACTIVE"],
        "drug_test_current_until": None,
        "no_show_strike_count": 0,
        "training_privileges": "ENABLED",
        "_earliest_expiry": None,
    }
    store.stamp(m)
    store.mariners[m["id"]] = m
    return success(ser_mariner(m), code=201)


@bp.route("/mariners", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_mariners():
    items = list(store.mariners.values())
    status = request.args.get("status")
    posture = request.args.get("readiness_posture")
    home_port = request.args.get("home_port_code")
    channel = request.args.get("hire_channel")
    if status is not None:
        items = [m for m in items if m["status"] == status]
    if posture is not None:
        items = [m for m in items if m["readiness_posture"] == posture]
    if home_port is not None:
        items = [m for m in items if m["home_port_code"] == home_port]
    if channel is not None:
        items = [m for m in items if m["hire_channel"] == channel]
    page, meta = paginate(sorted_items(items))
    return success([ser_mariner(m) for m in page], response_type="array", pagination=meta)


@bp.route("/mariners/<mariner_id>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_mariner(mariner_id):
    scope_mariner_id(mariner_id)
    m = get_mariner_or_404(mariner_id)
    return success(ser_mariner(m))


@bp.route("/mariners/<mariner_id>", methods=["PUT"])
@require_roles("FleetAdmin")
def update_mariner(mariner_id):
    m = get_mariner_or_404(mariner_id)
    body = get_body()
    # Schema validation of any supplied fields (pipeline step 6).
    new_values = {}
    if "full_name" in body and body["full_name"] is not None:
        new_values["full_name"] = req_str(body, "full_name")
    if "home_port_code" in body and body["home_port_code"] is not None:
        new_values["home_port_code"] = req_str(body, "home_port_code")
    if "hire_channel" in body and body["hire_channel"] is not None:
        new_values["hire_channel"] = req_enum(body, "hire_channel", HIRE_CHANNELS)
    if "rank_track" in body and body["rank_track"] is not None:
        new_values["rank_track"] = req_enum(body, "rank_track", RANK_TRACKS)
    if "rank_grade" in body and body["rank_grade"] is not None:
        new_values["rank_grade"] = req_int(body, "rank_grade", min_v=1, max_v=9)
    if (
        "primary_endorsement_code" in body
        and body["primary_endorsement_code"] is not None
    ):
        new_values["primary_endorsement_code"] = req_str(
            body, "primary_endorsement_code"
        )
    if (
        "annual_training_cap_cents" in body
        and body["annual_training_cap_cents"] is not None
    ):
        new_values["annual_training_cap_cents"] = req_int(
            body, "annual_training_cap_cents", min_v=0
        )
    # OCC (pipeline step 7): expected_mariner_version is required.
    expected = body.get("expected_mariner_version")
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise err(
            "ERR_INVALID_REQUEST",
            "Field 'expected_mariner_version' is required and must be an integer",
        )
    if expected != m["version"]:
        raise err(
            "ERR_STALE_VERSION",
            "expected_mariner_version %s does not match current version %s"
            % (expected, m["version"]),
        )
    primary_changed = (
        "primary_endorsement_code" in new_values
        and new_values["primary_endorsement_code"] != m["primary_endorsement_code"]
    )
    m.update(new_values)
    if primary_changed:
        recompute_mariner(m)  # may itself bump if posture fields change
    store.bump(m)
    if primary_changed and m["readiness_posture"] == "BLOCKED":
        # Profile edit flipped the mariner to BLOCKED: suspend open crewing.
        from services import cascade_assignments_suspended

        cascade_assignments_suspended(m)
    return success(ser_mariner(m))


@bp.route("/mariners/<mariner_id>/activate", methods=["POST"])
@require_roles("FleetAdmin")
def activate_mariner(mariner_id):
    m = get_mariner_or_404(mariner_id)
    if m["status"] != "APPLICANT":
        raise err("ERR_INVALID_STATE", "Mariner must be APPLICANT to activate")
    if not _activation_gates_met(m):
        raise err(
            "ERR_MARINER_ACTIVATION_REQUIREMENTS_MISSING",
            "Activation requires a VALID medical certificate, a qualifying "
            "NEGATIVE drug test, and a VALID credential",
        )
    m["status"] = "ACTIVE"
    recompute_mariner(m)
    store.bump(m)
    return success(ser_mariner(m))


@bp.route("/mariners/<mariner_id>/suspend", methods=["POST"])
@require_roles("FleetAdmin")
def suspend_mariner(mariner_id):
    m = get_mariner_or_404(mariner_id)
    if m["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Mariner must be ACTIVE to suspend")
    m["status"] = "SUSPENDED"
    recompute_mariner(m)
    store.bump(m)
    # Cascade: open CONFIRMED/ONBOARD assignments suspend (PRD 3.7).
    from services import cascade_assignments_suspended

    cascade_assignments_suspended(m)
    return success(ser_mariner(m))


@bp.route("/mariners/<mariner_id>/reinstate", methods=["POST"])
@require_roles("FleetAdmin")
def reinstate_mariner(mariner_id):
    m = get_mariner_or_404(mariner_id)
    if m["status"] != "SUSPENDED":
        raise err("ERR_INVALID_STATE", "Mariner must be SUSPENDED to reinstate")
    if not _activation_gates_met(m):
        raise err(
            "ERR_MARINER_ACTIVATION_REQUIREMENTS_MISSING",
            "Reinstatement re-checks the activation gates",
        )
    m["status"] = "ACTIVE"
    recompute_mariner(m)
    store.bump(m)
    return success(ser_mariner(m))


@bp.route("/mariners/<mariner_id>/terminate", methods=["POST"])
@require_roles("FleetAdmin")
def terminate_mariner(mariner_id):
    m = get_mariner_or_404(mariner_id)
    if m["status"] not in ("ACTIVE", "SUSPENDED"):
        raise err(
            "ERR_INVALID_STATE", "Mariner must be ACTIVE or SUSPENDED to terminate"
        )
    if any(
        a["mariner_id"] == m["id"] and a["assignment_status"] == "ONBOARD"
        for a in store.assignments.values()
    ):
        raise err(
            "ERR_ACTIVE_CREW_ABOARD",
            "Mariner has an ONBOARD assignment and cannot be terminated",
        )
    m["status"] = "TERMINATED"
    recompute_mariner(m)
    store.bump(m)
    # Cascades: PROPOSED/CONFIRMED assignments -> CANCELLED (travel cascade),
    # REQUESTED enrollments -> REJECTED, APPROVED enrollments -> CANCELLED.
    vessel_ids = set()
    for a in store.assignments.values():
        if a["mariner_id"] == m["id"] and a["assignment_status"] in (
            "PROPOSED",
            "CONFIRMED",
        ):
            cancel_assignment_cascade(a)
            vessel_ids.add(a["vessel_id"])
    for e in store.training_enrollments.values():
        if e["mariner_id"] != m["id"]:
            continue
        if e["status"] == "REQUESTED":
            e["status"] = "REJECTED"
            store.bump(e)
        elif e["status"] == "APPROVED":
            e["status"] = "CANCELLED"
            store.bump(e)
    from services import recompute_vessel

    for vid in vessel_ids:
        v = store.vessels.get(vid)
        if v is not None:
            recompute_vessel(v)
    return success(ser_mariner(m))


@bp.route("/mariners/<mariner_id>/upgrade-eligibility", methods=["GET"])
@require_roles(
    "FleetAdmin", "CrewingManager", "CredentialingOfficer", "PortCaptain", "Mariner"
)
def get_upgrade_eligibility(mariner_id):
    scope_mariner_id(mariner_id)
    m = get_mariner_or_404(mariner_id)
    target = request.args.get("target_endorsement_code")
    if not target or target not in UPGRADE_REQUIREMENTS:
        raise err(
            "ERR_INVALID_REQUEST",
            "target_endorsement_code must be one of %s"
            % sorted(UPGRADE_REQUIREMENTS),
        )
    result = upgrade_eligibility(m, target)
    result["window_start"] = fmt_dt_sec(result["window_start"])
    return success(result)


@bp.route("/mariners/<mariner_id>/sea-service-summary", methods=["GET"])
@require_roles(
    "FleetAdmin", "CrewingManager", "CredentialingOfficer", "PortCaptain", "Mariner"
)
def get_sea_service_summary(mariner_id):
    scope_mariner_id(mariner_id)
    m = get_mariner_or_404(mariner_id)
    provisional_total = 0.0
    verified_total = 0.0
    by_track = {}
    for r in store.sea_service_records.values():
        if r["mariner_id"] != m["id"]:
            continue
        track = r["rank_track"]
        if r["record_status"] in ("SUBMITTED", "VERIFIED"):
            provisional_total += r["provisional_days"]
            entry = by_track.setdefault(
                track, {"rank_track": track, "provisional_days": 0.0, "verified_days": 0.0}
            )
            entry["provisional_days"] += r["provisional_days"]
        if r["record_status"] == "VERIFIED":
            verified_total += r["verified_days"] or 0.0
            entry = by_track.setdefault(
                track, {"rank_track": track, "provisional_days": 0.0, "verified_days": 0.0}
            )
            entry["verified_days"] += r["verified_days"] or 0.0
    return success(
        {
            "provisional_days_total": provisional_total,
            "verified_days_total": verified_total,
            "by_track": [by_track[t] for t in sorted(by_track)],
        }
    )
