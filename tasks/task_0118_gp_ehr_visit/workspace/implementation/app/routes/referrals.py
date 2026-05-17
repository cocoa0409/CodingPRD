"""Referral endpoints: create, get, accept, reject, return-to-pcp, complete."""
from __future__ import annotations

from datetime import timedelta

from flask import Blueprint

from ..auth import (
    ROLE_CLINIC_ADMIN,
    ROLE_PATIENT_PORTAL,
    ROLE_PROVIDER,
    require_roles,
)
from ..clock import now
from ..errors import (
    err_forbidden,
    err_invalid_encounter_state,
    err_invalid_input,
    err_invalid_specialist,
    err_portal_disabled,
    err_referral_not_pending,
    err_referrer_not_pcp,
)
from ..helpers import (
    assert_enum,
    assert_string,
    new_uuid,
    occ_check,
    require_json_object,
)
from ..responses import created, ok
from ..services.audit import write_audit
from ..services.lookups import (
    get_encounter,
    get_patient,
    get_provider,
    get_referral,
)
from ..services.mutations import bump
from ..services.serialize import referral_to_dict
from ..store import store

bp = Blueprint("referrals", __name__)

PRIORITIES = ["ROUTINE", "URGENT"]


def _enforce_portal_self_for_referral(ref: dict, caller_id: str, caller_role: str) -> None:
    if caller_role != ROLE_PATIENT_PORTAL:
        return
    s = store()
    patient = s.patients.get(ref["patient_id"])
    if patient is None or not patient.get("portal_enabled"):
        raise err_portal_disabled()
    if patient["id"] != caller_id:
        raise err_portal_disabled()


@bp.route("/patients/<patient_id>/referrals", methods=["POST"])
@require_roles(ROLE_PROVIDER)
def create_referral(patient_id: str, *, _caller_id: str, _caller_role: str):
    body = require_json_object()
    s = store()
    with s.lock:
        patient = get_patient(patient_id)

        referring_provider_id = assert_string(
            body.get("referring_provider_id"), "referring_provider_id"
        )
        referring_provider = get_provider(referring_provider_id, source="body")
        referred_to_provider_id = assert_string(
            body.get("referred_to_provider_id"), "referred_to_provider_id"
        )
        referred_to_provider = get_provider(referred_to_provider_id, source="body")
        encounter_id = assert_string(body.get("encounter_id"), "encounter_id")
        encounter = get_encounter(encounter_id, source="body")

        reason = assert_string(body.get("reason"), "reason")
        priority = body.get("priority", "ROUTINE")
        if priority is None:
            priority = "ROUTINE"
        priority = assert_enum(priority, "priority", PRIORITIES)

        # Encounter must be COMPLETED (state precondition; surface as encounter state error 409)
        if encounter["status"] != "COMPLETED":
            raise err_invalid_encounter_state(
                "originating encounter must be COMPLETED"
            )

        # ERR_REFERRER_NOT_PCP — priority 10
        if patient.get("pcp_provider_id") != referring_provider_id:
            raise err_referrer_not_pcp()
        # ERR_INVALID_SPECIALIST — priority 11
        if referred_to_provider_id == referring_provider_id:
            raise err_invalid_specialist("referred_to must differ from referring provider")
        if referred_to_provider.get("role_type") not in {"SPECIALIST_ONLY", "BOTH"}:
            raise err_invalid_specialist("referred_to provider must be a specialist")

        ts = now()
        if priority == "URGENT":
            expires_at = ts + timedelta(hours=72)
        else:
            expires_at = ts + timedelta(days=30)
        row = {
            "id": new_uuid(),
            "patient_id": patient_id,
            "referring_provider_id": referring_provider_id,
            "referred_to_provider_id": referred_to_provider_id,
            "encounter_id": encounter_id,
            "reason": reason,
            "priority": priority,
            "status": "PENDING",
            "accepted_at": None,
            "expires_at": expires_at,
            "response_note": None,
            "created_at": ts,
            "updated_at": ts,
            "version": 1,
        }
        s.referrals[row["id"]] = row
    return created(referral_to_dict(row))


@bp.route("/referrals/<refid>", methods=["GET"])
@require_roles(ROLE_PROVIDER, ROLE_CLINIC_ADMIN, ROLE_PATIENT_PORTAL)
def get_referral_route(refid: str, *, _caller_id: str, _caller_role: str):
    s = store()
    with s.lock:
        ref = get_referral(refid)
        _enforce_portal_self_for_referral(ref, _caller_id, _caller_role)
    return ok(referral_to_dict(ref))


@bp.route("/referrals/<refid>/accept", methods=["POST"])
@require_roles(ROLE_PROVIDER)
def accept_referral(refid: str, *, _caller_id: str, _caller_role: str):
    body = require_json_object()
    s = store()
    with s.lock:
        ref = get_referral(refid)
        if ref["status"] != "PENDING":
            raise err_referral_not_pending()

        # identity match — must be the specialist (referred_to)
        if _caller_id != ref["referred_to_provider_id"]:
            raise err_forbidden(
                "Only the referred-to specialist may accept this referral"
            )
        prov = s.providers.get(ref["referred_to_provider_id"])
        if prov is None or prov.get("role_type") not in {"SPECIALIST_ONLY", "BOTH"}:
            raise err_invalid_specialist()

        patient = s.patients.get(ref["patient_id"])
        if patient is None or patient.get("status") != "ACTIVE":
            raise err_referral_not_pending("patient is not ACTIVE")

        # window check
        if now() >= ref["expires_at"]:
            raise err_referral_not_pending("referral has expired")

        response_note = body.get("response_note")
        if response_note is not None and not isinstance(response_note, str):
            raise err_invalid_input("response_note must be a string")

        occ_check(body.get("version"), ref["version"])
        ref["status"] = "ACCEPTED"
        ref["accepted_at"] = now()
        if response_note is not None:
            ref["response_note"] = response_note
        bump(ref)
        write_audit(
            actor_role=_caller_role,
            actor_id=_caller_id,
            action="referral.accept",
            target_entity="Referral",
            target_id=ref["id"],
        )
    return ok(referral_to_dict(ref))


@bp.route("/referrals/<refid>/reject", methods=["POST"])
@require_roles(ROLE_PROVIDER)
def reject_referral(refid: str, *, _caller_id: str, _caller_role: str):
    body = require_json_object()
    s = store()
    with s.lock:
        ref = get_referral(refid)
        if ref["status"] != "PENDING":
            raise err_referral_not_pending()
        if _caller_id != ref["referred_to_provider_id"]:
            raise err_forbidden(
                "Only the referred-to specialist may reject this referral"
            )
        if now() >= ref["expires_at"]:
            raise err_referral_not_pending("referral has expired")

        response_note = body.get("response_note")
        if response_note is not None and not isinstance(response_note, str):
            raise err_invalid_input("response_note must be a string")

        occ_check(body.get("version"), ref["version"])
        ref["status"] = "REJECTED"
        if response_note is not None:
            ref["response_note"] = response_note
        bump(ref)
        write_audit(
            actor_role=_caller_role,
            actor_id=_caller_id,
            action="referral.reject",
            target_entity="Referral",
            target_id=ref["id"],
        )
    return ok(referral_to_dict(ref))


@bp.route("/referrals/<refid>/return-to-pcp", methods=["POST"])
@require_roles(ROLE_PROVIDER)
def return_to_pcp(refid: str, *, _caller_id: str, _caller_role: str):
    body = require_json_object()
    s = store()
    with s.lock:
        ref = get_referral(refid)
        if ref["status"] != "ACCEPTED":
            raise err_referral_not_pending(
                f"referral in state {ref['status']} cannot be returned"
            )
        if _caller_id != ref["referred_to_provider_id"]:
            raise err_forbidden(
                "Only the referred-to specialist may return this referral"
            )
        # Precondition: no completed Encounter for the specialist for this patient since accepted_at
        has_completed = False
        accepted_at = ref.get("accepted_at")
        for enc in s.encounters.values():
            if enc["provider_id"] != ref["referred_to_provider_id"]:
                continue
            if enc["patient_id"] != ref["patient_id"]:
                continue
            if enc["status"] != "COMPLETED":
                continue
            ae = enc.get("actual_end")
            if accepted_at is not None and ae is not None and ae >= accepted_at:
                has_completed = True
                break
        if has_completed:
            raise err_referral_not_pending(
                "a completed encounter exists; referral cannot be returned"
            )

        response_note = body.get("response_note")
        if response_note is not None and not isinstance(response_note, str):
            raise err_invalid_input("response_note must be a string")

        occ_check(body.get("version"), ref["version"])
        ref["status"] = "PENDING"
        if response_note is not None:
            ref["response_note"] = response_note
        bump(ref)
        write_audit(
            actor_role=_caller_role,
            actor_id=_caller_id,
            action="referral.return-to-pcp",
            target_entity="Referral",
            target_id=ref["id"],
        )
    return ok(referral_to_dict(ref))


@bp.route("/referrals/<refid>/complete", methods=["POST"])
@require_roles(ROLE_PROVIDER)
def complete_referral(refid: str, *, _caller_id: str, _caller_role: str):
    body = require_json_object()
    s = store()
    with s.lock:
        ref = get_referral(refid)
        if ref["status"] != "ACCEPTED":
            raise err_referral_not_pending(
                f"complete requires ACCEPTED; current status: {ref['status']}"
            )
        if _caller_id != ref["referred_to_provider_id"]:
            raise err_forbidden(
                "Only the referred-to specialist may complete this referral"
            )
        # Precondition: at least one COMPLETED encounter with provider == referred_to since accepted_at
        accepted_at = ref.get("accepted_at")
        ok_completed = False
        for enc in s.encounters.values():
            if enc["provider_id"] != ref["referred_to_provider_id"]:
                continue
            if enc["patient_id"] != ref["patient_id"]:
                continue
            if enc["status"] != "COMPLETED":
                continue
            ae = enc.get("actual_end")
            if accepted_at is not None and ae is not None and ae >= accepted_at:
                ok_completed = True
                break
        if not ok_completed:
            raise err_referral_not_pending(
                "no completed encounter with the specialist since accepted_at"
            )

        occ_check(body.get("version"), ref["version"])
        ref["status"] = "COMPLETED"
        bump(ref)
        write_audit(
            actor_role=_caller_role,
            actor_id=_caller_id,
            action="referral.complete",
            target_entity="Referral",
            target_id=ref["id"],
        )
    return ok(referral_to_dict(ref))
