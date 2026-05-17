"""Physician and StateLicense routes."""
from flask import Blueprint, jsonify

from app.auth import require_roles
from app.errors import (
    err_invalid_state,
    err_license_period_overlap,
    err_not_found,
)
from app.responses import success_array, success_object
from app.services.compliance import physician_aggregate_compliance
from app.services.licenses import (
    list_licenses_for_physician,
    project_license_status,
    view_license,
)
from app.store import store
from app.utils import (
    bump_version_and_timestamp,
    check_version_if_supplied,
    is_valid_dea,
    is_valid_npi,
    is_valid_state_code,
    paginate_sorted,
    parse_iso_datetime,
    parse_json_body,
    parse_pagination,
)


bp = Blueprint("physicians", __name__)


# ---------------- Physicians ----------------

@bp.post("/telemed/physicians")
@require_roles(["PlatformAdmin"])
def create_physician():
    body = parse_json_body()
    full_name = body.get("full_name")
    npi = body.get("npi_number")
    imlc_compact_member = body.get("imlc_compact_member", False)
    imlc_home_state = body.get("imlc_home_state", None)
    dea_number = body.get("dea_number", None)

    # Field validation
    if not isinstance(full_name, str) or not full_name:
        raise err_invalid_state("full_name is required")
    if not is_valid_npi(npi):
        raise err_invalid_state("npi_number must be 10 digits")
    if not isinstance(imlc_compact_member, bool):
        raise err_invalid_state("imlc_compact_member must be boolean")
    if imlc_compact_member:
        if not is_valid_state_code(imlc_home_state):
            raise err_invalid_state("imlc_home_state must be a 2-letter state code when imlc_compact_member is true")
    else:
        imlc_home_state = None
    if dea_number is not None and not is_valid_dea(dea_number):
        raise err_invalid_state("dea_number must match ^[A-Z]{2}[0-9]{7}$ when present")

    # Uniqueness checks
    with store.lock:
        for p in store.physicians.values():
            if p["npi_number"] == npi:
                raise err_invalid_state("npi_number must be unique across physicians")
            if dea_number is not None and p.get("dea_number") == dea_number:
                raise err_invalid_state("dea_number must be unique across physicians")

        now_iso = store.now_iso()
        physician = {
            "id": store.new_id(),
            "full_name": full_name,
            "npi_number": npi,
            "imlc_compact_member": imlc_compact_member,
            "imlc_home_state": imlc_home_state,
            "dea_number": dea_number,
            "status": "ACTIVE",
            "created_at": now_iso,
            "updated_at": now_iso,
            "version": 1,
        }
        store.physicians[physician["id"]] = physician

    return jsonify(success_object(physician)), 201


@bp.get("/telemed/physicians/<pid>")
@require_roles(["PlatformAdmin", "ComplianceOfficer", "Physician"])
def get_physician(pid: str):
    physician = store.physicians.get(pid)
    if not physician:
        raise err_not_found()
    return jsonify(success_object(physician)), 200


@bp.get("/telemed/physicians")
@require_roles(["PlatformAdmin", "ComplianceOfficer"])
def list_physicians():
    from flask import request

    limit, offset = parse_pagination()
    status = request.args.get("status")
    filtered = []
    for p in store.physicians.values():
        if status and p["status"] != status:
            continue
        filtered.append(p)
    sliced, total = paginate_sorted(filtered, limit, offset)
    return jsonify(success_array(sliced, limit, offset, total)), 200


# ---------------- StateLicenses ----------------

@bp.post("/telemed/physicians/<pid>/licenses")
@require_roles(["PlatformAdmin"])
def create_license(pid: str):
    if pid not in store.physicians:
        raise err_not_found()
    body = parse_json_body()

    state_code = body.get("state_code")
    license_number = body.get("license_number")
    license_type = body.get("license_type")
    issued_at_raw = body.get("issued_at")
    expires_at_raw = body.get("expires_at")

    if not is_valid_state_code(state_code):
        raise err_invalid_state("state_code must be a 2-letter US state code")
    if not isinstance(license_number, str) or not license_number:
        raise err_invalid_state("license_number is required")
    if license_type not in ("FULL", "IMLC_EXPEDITED"):
        raise err_invalid_state("license_type must be FULL or IMLC_EXPEDITED")

    try:
        issued_at = parse_iso_datetime(issued_at_raw)
        expires_at = parse_iso_datetime(expires_at_raw)
    except ValueError:
        raise err_invalid_state("issued_at and expires_at must be ISO 8601 strings")

    if not (expires_at > issued_at):
        raise err_invalid_state("expires_at must be strictly greater than issued_at")

    # Half-open overlap check against existing licenses for same (physician, state).
    with store.lock:
        for existing in store.state_licenses.values():
            if existing["physician_id"] != pid or existing["state_code"] != state_code:
                continue
            try:
                e_issued = parse_iso_datetime(existing["issued_at"])
                e_expires = parse_iso_datetime(existing["expires_at"])
            except ValueError:
                continue
            # Overlap: a1 < e2 AND a2 < e1
            if issued_at < e_expires and e_issued < expires_at:
                raise err_license_period_overlap()

        now_iso = store.now_iso()
        # Store timestamps in canonical form
        issued_iso = issued_at.strftime("%Y-%m-%dT%H:%M:%S.") + f"{issued_at.microsecond // 1000:03d}Z"
        expires_iso = expires_at.strftime("%Y-%m-%dT%H:%M:%S.") + f"{expires_at.microsecond // 1000:03d}Z"

        lic = {
            "id": store.new_id(),
            "physician_id": pid,
            "state_code": state_code,
            "license_number": license_number,
            "license_type": license_type,
            "issued_at": issued_iso,
            "expires_at": expires_iso,
            "status": "ACTIVE",
            "created_at": now_iso,
            "updated_at": now_iso,
            "version": 1,
        }
        store.state_licenses[lic["id"]] = lic

    return jsonify(success_object(view_license(lic))), 201


@bp.get("/telemed/physicians/<pid>/licenses")
@require_roles(["PlatformAdmin", "ComplianceOfficer", "Physician"])
def list_physician_licenses(pid: str):
    from flask import request

    if pid not in store.physicians:
        raise err_not_found()
    limit, offset = parse_pagination()
    state_code = request.args.get("state_code")
    status_filter = request.args.get("status")

    rows = list_licenses_for_physician(pid)
    out = []
    for lic in rows:
        if state_code and lic["state_code"] != state_code:
            continue
        view = view_license(lic)
        if status_filter and view["status"] != status_filter:
            continue
        out.append(view)
    sliced, total = paginate_sorted(out, limit, offset)
    return jsonify(success_array(sliced, limit, offset, total)), 200


@bp.post("/telemed/physicians/<pid>/licenses/<lid>/revoke")
@require_roles(["PlatformAdmin"])
def revoke_license(pid: str, lid: str):
    from flask import request

    # Existence: left-to-right
    physician = store.physicians.get(pid)
    if not physician:
        raise err_not_found()
    lic = store.state_licenses.get(lid)
    if not lic or lic["physician_id"] != pid:
        raise err_not_found()

    body = parse_json_body()
    check_version_if_supplied(lic, body)

    actor_role = request.headers.get("X-User-Role", "PlatformAdmin")

    with store.lock:
        # Pre-check: if already revoked, raise INVALID_STATE.
        if project_license_status(lic) == "REVOKED":
            raise err_invalid_state("License is already revoked")

        now_iso = store.now_iso()

        # Link 1: append LICENSE_REVOKED audit event for the license itself.
        store.append_audit(
            event_type="LICENSE_REVOKED",
            subject_entity="StateLicense",
            subject_id=lic["id"],
            actor_role=actor_role,
            payload_json={
                "physician_id": pid,
                "state_code": lic["state_code"],
                "license_number": lic.get("license_number"),
            },
        )
        # Bump license itself.
        bump_version_and_timestamp(lic, now_iso)

        # Link 2: find affected consults — non-terminal (REQUESTED/ROUTED/IN_PROGRESS)
        # with matching physician_id and present_state_code.
        # In practice REQUESTED consults have null physician_id, so the system-edge
        # transitions are ROUTED→REQUESTED and IN_PROGRESS→REQUESTED.
        affected_consult_ids = []
        for consult in store.consults.values():
            if consult.get("physician_id") != pid:
                continue
            if consult.get("present_state_code") != lic["state_code"]:
                continue
            if consult.get("status") not in {"ROUTED", "IN_PROGRESS"}:
                continue
            # Reset
            consult["physician_id"] = None
            consult["routing_basis"] = None
            consult["status"] = "REQUESTED"
            bump_version_and_timestamp(consult, now_iso)
            affected_consult_ids.append(consult["id"])

        # Link 3: void DRAFT prescriptions under affected consults.
        for cid in affected_consult_ids:
            for rx in store.prescriptions.values():
                if rx.get("consult_id") != cid:
                    continue
                if rx.get("status") != "DRAFT":
                    continue
                rx["status"] = "VOIDED"
                rx["void_reason"] = "LICENSE_REVOKED"
                bump_version_and_timestamp(rx, now_iso)
                store.append_audit(
                    event_type="RX_VOIDED",
                    subject_entity="Prescription",
                    subject_id=rx["id"],
                    actor_role="system",
                    payload_json={
                        "consult_id": cid,
                        "void_reason": "LICENSE_REVOKED",
                    },
                )

    return jsonify(success_object(view_license(lic))), 200


@bp.get("/telemed/physicians/<pid>/compliance")
@require_roles(["PlatformAdmin", "ComplianceOfficer"])
def get_physician_compliance(pid: str):
    if pid not in store.physicians:
        raise err_not_found()
    return jsonify(success_object(physician_aggregate_compliance(pid))), 200
