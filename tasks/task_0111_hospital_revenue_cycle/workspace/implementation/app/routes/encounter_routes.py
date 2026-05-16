"""Encounter endpoints — admission, lookup, list, PATCH metadata,
verify-eligibility, discharge, issue-bill."""
from __future__ import annotations

from flask import Flask

from ..auth import require_auth
from ..calculations import refresh_total_and_estimate, run_estimate
from ..clock import now_dt, now_iso_ms
from ..errors import ApiError
from ..pagination import parse_limit_offset, parse_optional_str
from ..response import paginate
from ..services.serializers import serialize_encounter
from ..services.validation import (
    get_encounter_or_404,
    get_patient_or_404,
    get_policy_or_404,
    require_bool,
    require_int,
    require_str,
)
from ..store import LOCK, bump_version, common_fields_create, get_store, now_iso
from ._helpers import created, get_json_body, list_ok, ok


def register(app: Flask) -> None:
    # ---- POST /encounters: admission ----
    @app.route("/encounters", methods=["POST"])
    @require_auth("RegistrationClerk")
    def admit_encounter():
        body = get_json_body()
        patient_id = require_str(body, "patient_id")
        policy_id = require_str(body, "policy_id")

        # Existence checks (priority 4 — FK in body).
        get_patient_or_404(patient_id)
        policy = get_policy_or_404(policy_id)

        # business_referential: policy.patient_id must match.
        if policy["patient_id"] != patient_id:
            raise ApiError(
                "ERR_POLICY_PATIENT_MISMATCH",
                "Policy does not belong to the supplied patient.",
            )

        store = get_store()
        with LOCK:
            base = common_fields_create()
            encounter = {
                **base,
                "patient_id": patient_id,
                "policy_id": policy_id,
                "admission_at": now_iso(),
                "discharge_at": None,
                "billed_at": None,
                "status": "REGISTERED",
                "total_charges_cents": 0,
                "payer_responsibility_cents": 0,
                "patient_responsibility_cents": 0,
                "estimated_patient_responsibility_cents": 0,
                "write_off_cents": 0,
            }
            store.encounters[encounter["id"]] = encounter
        return created(serialize_encounter(encounter))

    # ---- GET /encounters/{id} ----
    @app.route("/encounters/<encounter_id>", methods=["GET"])
    @require_auth("RegistrationClerk", "ChargeCaptureClerk", "Coder", "Biller")
    def get_encounter(encounter_id):
        enc = get_encounter_or_404(encounter_id)
        return ok(serialize_encounter(enc))

    # ---- GET /encounters ----
    @app.route("/encounters", methods=["GET"])
    @require_auth("RegistrationClerk", "Biller")
    def list_encounters():
        limit, offset = parse_limit_offset()
        status_filter = parse_optional_str("status")
        patient_filter = parse_optional_str("patient_id")
        store = get_store()
        items = list(store.encounters.values())
        if status_filter is not None:
            items = [e for e in items if e["status"] == status_filter]
        if patient_filter is not None:
            items = [e for e in items if e["patient_id"] == patient_filter]
        items.sort(key=lambda e: e["created_at"])
        sliced, pag = paginate(items, limit, offset)
        return list_ok([serialize_encounter(e) for e in sliced], pag)

    # ---- PATCH /encounters/{id}: metadata update (policy_id swap) ----
    @app.route("/encounters/<encounter_id>", methods=["PATCH"])
    @require_auth("RegistrationClerk")
    def patch_encounter(encounter_id):
        enc = get_encounter_or_404(encounter_id)
        body = get_json_body()

        # State guard: only REGISTERED allows metadata update.
        if enc["status"] != "REGISTERED":
            raise ApiError(
                "ERR_INVALID_STATE",
                f"Encounter must be REGISTERED to patch metadata; is {enc['status']}.",
            )

        # OCC: if version present, must match current.
        if "version" in body:
            v = body["version"]
            if not isinstance(v, int) or v != int(enc["version"]):
                raise ApiError("ERR_VERSION_CONFLICT", "Version mismatch on encounter PATCH.")

        new_policy_id = body.get("policy_id")
        if new_policy_id is not None:
            if not isinstance(new_policy_id, str):
                raise ApiError("ERR_INVALID_INPUT", "policy_id must be a string.")
            policy = get_policy_or_404(new_policy_id)
            # business_referential: policy.patient_id must match.
            if policy["patient_id"] != enc["patient_id"]:
                raise ApiError(
                    "ERR_POLICY_PATIENT_MISMATCH",
                    "Replacement policy does not belong to the encounter's patient.",
                )
            enc["policy_id"] = new_policy_id
            bump_version(enc)

        return ok(serialize_encounter(enc))

    # ---- POST /encounters/{id}/verify-eligibility ----
    @app.route("/encounters/<encounter_id>/verify-eligibility", methods=["POST"])
    @require_auth("RegistrationClerk")
    def verify_eligibility(encounter_id):
        enc = get_encounter_or_404(encounter_id)
        body = get_json_body()
        policy_eligible = require_bool(body, "policy_eligible")
        # denial_code optional, not stored anywhere structured per scaffold.

        # State guard: encounter must be REGISTERED.
        if enc["status"] != "REGISTERED":
            raise ApiError(
                "ERR_INVALID_STATE",
                f"Encounter must be REGISTERED to verify eligibility; is {enc['status']}.",
            )

        store = get_store()
        policy = store.policies.get(enc["policy_id"])
        if policy is None:
            raise ApiError("ERR_NOT_FOUND", "Encounter policy not found.")

        # business_safety: policy.plan_year == current calendar year.
        current_year = now_dt().year
        if int(policy["plan_year"]) != current_year:
            raise ApiError(
                "ERR_PLAN_YEAR_EXPIRED",
                f"Policy plan_year {policy['plan_year']} != current year {current_year}.",
            )

        # Side effect: set verified_at regardless of branch.
        policy["verified_at"] = now_iso_ms()

        if policy_eligible:
            policy["status"] = "ELIGIBLE"
            bump_version(policy)
            enc["status"] = "ELIGIBILITY_VERIFIED"
            bump_version(enc)
            # Seed estimate (against total_charges_cents = 0).
            run_estimate(enc)
        else:
            policy["status"] = "INELIGIBLE"
            bump_version(policy)
            # Encounter stays REGISTERED. Bump version because policy.verified_at changed
            # and the call ran against the encounter; but the encounter itself is unchanged.
            # Per PRD §3.3 the encounter stays in REGISTERED to allow re-registration.

        return ok(serialize_encounter(enc))

    # ---- POST /encounters/{id}/discharge ----
    @app.route("/encounters/<encounter_id>/discharge", methods=["POST"])
    @require_auth("RegistrationClerk")
    def discharge_encounter(encounter_id):
        enc = get_encounter_or_404(encounter_id)
        # State guard.
        if enc["status"] != "ELIGIBILITY_VERIFIED":
            raise ApiError(
                "ERR_INVALID_STATE",
                f"Encounter must be ELIGIBILITY_VERIFIED to discharge; is {enc['status']}.",
            )

        # business_fiscal: at least one POSTED, zero PENDING.
        store = get_store()
        charges = [c for c in store.charges.values() if c["encounter_id"] == encounter_id]
        any_pending = any(c["status"] == "PENDING" for c in charges)
        any_posted = any(c["status"] == "POSTED" for c in charges)
        if any_pending or not any_posted:
            raise ApiError(
                "ERR_CHARGES_NOT_READY",
                "Discharge requires at least one POSTED and zero PENDING charges.",
            )

        enc["discharge_at"] = now_iso()
        enc["status"] = "CHARGES_CAPTURED"
        bump_version(enc)
        # Side-effect refresh.
        refresh_total_and_estimate(enc)
        return ok(serialize_encounter(enc))

    # ---- POST /encounters/{id}/issue-bill ----
    @app.route("/encounters/<encounter_id>/issue-bill", methods=["POST"])
    @require_auth("Biller")
    def issue_bill(encounter_id):
        enc = get_encounter_or_404(encounter_id)
        if enc["status"] != "CLEARED":
            raise ApiError(
                "ERR_INVALID_STATE",
                f"Encounter must be CLEARED to issue bill; is {enc['status']}.",
            )
        enc["status"] = "BILLED"
        enc["billed_at"] = now_iso()
        bump_version(enc)
        return ok(serialize_encounter(enc))
