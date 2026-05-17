"""Consult routes: create, read, list, route/decline/unroute/start/complete/close."""
from flask import Blueprint, jsonify, request

from app.auth import require_roles
from app.errors import (
    err_billing_not_terminal,
    err_forbidden,
    err_insurance_not_enrolled,
    err_invalid_state,
    err_no_valid_license,
    err_not_found,
    err_patient_has_active_consult,
)
from app.responses import success_array, success_object
from app.services.billing import (
    compute_base_charge_cents,
    create_followup,
    create_insurance_claim,
    create_self_pay_invoice,
)
from app.services.licenses import (
    find_active_matching_license,
    project_license_status,
)
from app.store import store
from app.utils import (
    bump_version_and_timestamp,
    check_version_if_supplied,
    is_valid_state_code,
    paginate_sorted,
    parse_json_body,
    parse_pagination,
)


bp = Blueprint("consults", __name__)


VALID_BILLING = {"INSURANCE", "SELF_PAY"}
VALID_TIER = {"BRIEF", "STANDARD", "EXTENDED"}
NON_TERMINAL_FOR_PATIENT_GUARD = {"REQUESTED", "ROUTED", "IN_PROGRESS", "COMPLETED"}


@bp.post("/telemed/consults")
@require_roles(["ComplianceOfficer"])
def create_consult():
    body = parse_json_body()
    patient_id = body.get("patient_id")
    present_state_override = body.get("present_state_code", None)
    billing_mode = body.get("billing_mode")
    visit_tier = body.get("visit_tier")
    requires_followup = bool(body.get("requires_followup", False))

    if not isinstance(patient_id, str):
        raise err_invalid_state("patient_id is required")
    patient = store.patients.get(patient_id)
    if not patient:
        raise err_not_found()
    if billing_mode not in VALID_BILLING:
        raise err_invalid_state("billing_mode must be INSURANCE or SELF_PAY")
    if visit_tier not in VALID_TIER:
        raise err_invalid_state("visit_tier must be BRIEF, STANDARD, or EXTENDED")

    # Determine present_state_code (snapshot onto consult).
    if present_state_override is not None:
        if not is_valid_state_code(present_state_override):
            raise err_invalid_state("present_state_code must be a 2-letter state code")
        present_state = present_state_override
    else:
        present_state = patient.get("present_state_code") or patient.get("home_state_code")

    # Insurance enrolment check (priority 10).
    if billing_mode == "INSURANCE":
        if not patient.get("insurance_payer_id") or not patient.get("insurance_member_id"):
            raise err_insurance_not_enrolled()

    # Active-consult guard (priority 14).
    with store.lock:
        for c in store.consults.values():
            if c.get("patient_id") != patient_id:
                continue
            if c.get("status") in NON_TERMINAL_FOR_PATIENT_GUARD:
                raise err_patient_has_active_consult()

        now_iso = store.now_iso()
        consult = {
            "id": store.new_id(),
            "patient_id": patient_id,
            "physician_id": None,
            "present_state_code": present_state,
            "billing_mode": billing_mode,
            "visit_tier": visit_tier,
            "routing_basis": None,
            "requires_followup": requires_followup,
            "base_charge_cents": None,
            "final_charge_cents": None,
            "status": "REQUESTED",
            "created_at": now_iso,
            "updated_at": now_iso,
            "version": 1,
        }
        store.consults[consult["id"]] = consult

    return jsonify(success_object(consult)), 201


@bp.get("/telemed/consults/<cid>")
@require_roles(["ComplianceOfficer", "Physician"])
def get_consult(cid: str):
    consult = store.consults.get(cid)
    if not consult:
        raise err_not_found()
    return jsonify(success_object(consult)), 200


@bp.get("/telemed/consults")
@require_roles(["ComplianceOfficer", "Physician"])
def list_consults():
    limit, offset = parse_pagination()
    status = request.args.get("status")
    billing_mode = request.args.get("billing_mode")
    present_state_code = request.args.get("present_state_code")

    filtered = []
    for c in store.consults.values():
        if status and c["status"] != status:
            continue
        if billing_mode and c["billing_mode"] != billing_mode:
            continue
        if present_state_code and c["present_state_code"] != present_state_code:
            continue
        filtered.append(c)
    sliced, total = paginate_sorted(filtered, limit, offset)
    return jsonify(success_array(sliced, limit, offset, total)), 200


def _has_any_prescription(consult_id: str) -> bool:
    for rx in store.prescriptions.values():
        if rx.get("consult_id") == consult_id:
            return True
    return False


def _has_draft_prescription(consult_id: str) -> bool:
    for rx in store.prescriptions.values():
        if rx.get("consult_id") == consult_id and rx.get("status") == "DRAFT":
            return True
    return False


@bp.post("/telemed/consults/<cid>/route")
@require_roles(["ComplianceOfficer"])
def route_consult(cid: str):
    consult = store.consults.get(cid)
    if not consult:
        raise err_not_found()
    body = parse_json_body()

    # State first (priority 4) — then OCC (priority 16) — then business rules.
    if consult["status"] != "REQUESTED":
        raise err_invalid_state("Consult is not in REQUESTED state")
    check_version_if_supplied(consult, body)

    physician_id = body.get("physician_id")
    if not isinstance(physician_id, str) or not physician_id:
        raise err_invalid_state("physician_id is required for routing")
    physician = store.physicians.get(physician_id)
    if not physician:
        raise err_not_found()
    if physician["status"] != "ACTIVE":
        raise err_no_valid_license("Physician is not ACTIVE")

    # Find an ACTIVE matching license.
    matched = find_active_matching_license(physician_id, consult["present_state_code"])
    if not matched:
        raise err_no_valid_license()

    actor_role = request.headers.get("X-User-Role", "ComplianceOfficer")

    with store.lock:
        # Re-check state under lock for race safety.
        if consult["status"] != "REQUESTED":
            raise err_invalid_state("Consult is not in REQUESTED state")
        consult["physician_id"] = physician_id
        consult["routing_basis"] = (
            "FULL_LICENSE" if matched["license_type"] == "FULL" else "IMLC_EXPEDITED"
        )
        consult["status"] = "ROUTED"
        now_iso = store.now_iso()
        bump_version_and_timestamp(consult, now_iso)

        store.append_audit(
            event_type="CONSULT_ROUTED",
            subject_entity="Consult",
            subject_id=consult["id"],
            actor_role=actor_role,
            payload_json={
                "physician_id": physician_id,
                "routing_basis": consult["routing_basis"],
                "state_code": consult["present_state_code"],
            },
        )

    return jsonify(success_object(consult)), 200


@bp.post("/telemed/consults/<cid>/decline")
@require_roles(["ComplianceOfficer"])
def decline_consult(cid: str):
    consult = store.consults.get(cid)
    if not consult:
        raise err_not_found()
    body = parse_json_body()
    if consult["status"] != "REQUESTED":
        raise err_invalid_state("Consult is not in REQUESTED state")
    check_version_if_supplied(consult, body)

    with store.lock:
        if consult["status"] != "REQUESTED":
            raise err_invalid_state("Consult is not in REQUESTED state")
        consult["status"] = "DECLINED"
        now_iso = store.now_iso()
        bump_version_and_timestamp(consult, now_iso)

    return jsonify(success_object(consult)), 200


@bp.post("/telemed/consults/<cid>/unroute")
@require_roles(["ComplianceOfficer"])
def unroute_consult(cid: str):
    consult = store.consults.get(cid)
    if not consult:
        raise err_not_found()
    body = parse_json_body()
    if consult["status"] != "ROUTED":
        raise err_invalid_state("Consult is not in ROUTED state")
    check_version_if_supplied(consult, body)

    if _has_any_prescription(consult["id"]):
        raise err_invalid_state("Cannot unroute: prescriptions exist under this consult")

    with store.lock:
        if consult["status"] != "ROUTED":
            raise err_invalid_state("Consult is not in ROUTED state")
        if _has_any_prescription(consult["id"]):
            raise err_invalid_state("Cannot unroute: prescriptions exist under this consult")
        consult["physician_id"] = None
        consult["routing_basis"] = None
        consult["status"] = "REQUESTED"
        now_iso = store.now_iso()
        bump_version_and_timestamp(consult, now_iso)

    return jsonify(success_object(consult)), 200


@bp.post("/telemed/consults/<cid>/start")
@require_roles(["Physician"])
def start_consult(cid: str):
    consult = store.consults.get(cid)
    if not consult:
        raise err_not_found()
    body = parse_json_body()
    user_id = request.headers.get("X-User-ID")

    if consult["status"] != "ROUTED":
        raise err_invalid_state("Consult is not in ROUTED state")
    # Ownership check (Physician must equal consult.physician_id).
    if consult.get("physician_id") != user_id:
        raise err_forbidden()
    check_version_if_supplied(consult, body)

    # Re-check matched license is still ACTIVE.
    matched = find_active_matching_license(consult["physician_id"], consult["present_state_code"])
    if not matched:
        raise err_invalid_state("Matched StateLicense is no longer ACTIVE")

    with store.lock:
        if consult["status"] != "ROUTED":
            raise err_invalid_state("Consult is not in ROUTED state")
        consult["status"] = "IN_PROGRESS"
        now_iso = store.now_iso()
        bump_version_and_timestamp(consult, now_iso)

    return jsonify(success_object(consult)), 200


@bp.post("/telemed/consults/<cid>/complete")
@require_roles(["Physician"])
def complete_consult(cid: str):
    consult = store.consults.get(cid)
    if not consult:
        raise err_not_found()
    body = parse_json_body()
    user_id = request.headers.get("X-User-ID")

    if consult["status"] != "IN_PROGRESS":
        raise err_invalid_state("Consult is not in IN_PROGRESS state")
    if consult.get("physician_id") != user_id:
        raise err_forbidden()
    check_version_if_supplied(consult, body)

    # All prescriptions under this consult must be non-DRAFT.
    if _has_draft_prescription(consult["id"]):
        raise err_invalid_state("DRAFT prescriptions remain under this consult")

    patient = store.patients.get(consult["patient_id"])
    if not patient:
        # Should not happen, but defensive.
        raise err_not_found()

    with store.lock:
        if consult["status"] != "IN_PROGRESS":
            raise err_invalid_state("Consult is not in IN_PROGRESS state")
        base = compute_base_charge_cents(consult["visit_tier"])
        consult["base_charge_cents"] = base
        now_iso = store.now_iso()

        if consult["billing_mode"] == "SELF_PAY":
            invoice = create_self_pay_invoice(consult["id"], base, now_iso)
            consult["final_charge_cents"] = invoice["amount_due_cents"]
            consult["invoice_id"] = invoice["id"]
        else:
            # Uniqueness: enforce at most one InsuranceClaim per consult.
            for cl in store.claims.values():
                if cl["consult_id"] == consult["id"]:
                    from app.errors import err_claim_already_exists
                    raise err_claim_already_exists()
            claim = create_insurance_claim(consult["id"], base, patient, now_iso)
            consult["final_charge_cents"] = claim["patient_responsibility_cents"]
            consult["claim_id"] = claim["id"]

        consult["status"] = "COMPLETED"
        bump_version_and_timestamp(consult, now_iso)

        # FollowUp creation if requires_followup.
        if consult.get("requires_followup"):
            create_followup(consult["id"], now_iso)

    return jsonify(success_object(consult)), 200


@bp.post("/telemed/consults/<cid>/close")
@require_roles(["ComplianceOfficer"])
def close_consult(cid: str):
    consult = store.consults.get(cid)
    if not consult:
        raise err_not_found()
    body = parse_json_body()

    if consult["status"] != "COMPLETED":
        raise err_invalid_state("Consult is not in COMPLETED state")
    check_version_if_supplied(consult, body)

    # Billing terminal: per billing_mode.
    if consult["billing_mode"] == "INSURANCE":
        for cl in store.claims.values():
            if cl["consult_id"] != consult["id"]:
                continue
            if cl["status"] not in {"PAID", "DENIED"}:
                raise err_billing_not_terminal()
    else:
        for inv in store.invoices.values():
            if inv["consult_id"] != consult["id"]:
                continue
            if inv["status"] not in {"PAID", "VOIDED"}:
                raise err_billing_not_terminal()

    # FollowUp terminal (if any exists).
    for fu in store.followups.values():
        if fu["consult_id"] != consult["id"]:
            continue
        if fu["status"] not in {"COMPLETED", "MISSED", "CANCELLED"}:
            raise err_billing_not_terminal()

    with store.lock:
        if consult["status"] != "COMPLETED":
            raise err_invalid_state("Consult is not in COMPLETED state")
        consult["status"] = "CLOSED"
        now_iso = store.now_iso()
        bump_version_and_timestamp(consult, now_iso)

    return jsonify(success_object(consult)), 200
