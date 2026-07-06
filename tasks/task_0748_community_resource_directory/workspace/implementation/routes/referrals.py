from flask import request

from db import db
from errors import (
    ERR_AGE_INELIGIBLE,
    ERR_CAPACITY_EXHAUSTED,
    ERR_CONSENT_NOT_GRANTED,
    ERR_CONSENT_PROVIDER_MISMATCH,
    ERR_ELIGIBILITY_BELOW_THRESHOLD,
    ERR_INCOME_INELIGIBLE,
    ERR_INTAKE_NOT_FOUND,
    ERR_INTAKE_NOT_SCREENED,
    ERR_INVALID_REQUEST,
    ERR_OWNERSHIP_VIOLATION,
    ERR_PROGRAM_CATEGORY_MISMATCH,
    ERR_PROGRAM_CLOSED_TO_INTAKE,
    ERR_REFERRAL_INVALID_STATE,
    ERR_REFERRAL_NOT_FOUND,
    raise_error,
)
from middleware import get_auth, require_roles
from response import paginate, success
from services import (
    REFERRAL_INFLIGHT,
    REFERRAL_TERMINAL,
    _stamp_new,
    _touch,
    cascade_referral_withdraw,
    compute_eligibility_score,
    compute_travel_burden,
    decrement_capacity,
    increment_capacity,
    maybe_bubble_intake_closed,
    serialise_referral,
)
from util import floor_years_between
from validate import (
    TRANSPORT_MODE_ENUM,
    parse_pagination,
    require_body,
    require_enum,
    require_str,
)


REFERRAL_ACCEPT_THRESHOLD = 75.0


def _referral_or_404(rid: str):
    r = db.referrals.get(rid)
    if not r:
        raise_error(ERR_REFERRAL_NOT_FOUND, f"referral {rid} not found")
    return r


def _providerstaff_ownership_of_referral(r: dict) -> None:
    uid, role = get_auth()
    if role != "ProviderStaff":
        return
    prog = db.programs.get(r["program_id"])
    if not prog or prog["provider_id"] != uid:
        raise_error(ERR_OWNERSHIP_VIOLATION, "ProviderStaff does not own this referral's provider")


def _client_ownership_of_referral(r: dict) -> None:
    uid, role = get_auth()
    if role != "Client":
        return
    intake = db.intakes.get(r["intake_id"])
    if not intake or intake["client_id"] != uid:
        raise_error(ERR_OWNERSHIP_VIOLATION, "Client does not own this referral's client")


def register(app):

    @app.post("/intakes/<iid>/referrals")
    @require_roles("Caseworker", "PlatformAdmin")
    def create_referral(iid):
        # Existence: intake in path (priority 7).
        intake = db.intakes.get(iid)
        if not intake:
            raise_error(ERR_INTAKE_NOT_FOUND, f"intake {iid} not found")

        body = require_body(request.get_json(silent=True))
        program_id = require_str(body, "program_id")
        consent_grant_id = require_str(body, "consent_grant_id")
        transport_mode = require_enum(body, "transport_mode", TRANSPORT_MODE_ENUM)

        # Priority 11: body FK resolution.
        program = db.programs.get(program_id)
        if not program:
            raise_error(ERR_INVALID_REQUEST, f"program_id {program_id} not found")
        consent = db.consent_grants.get(consent_grant_id)
        if not consent:
            raise_error(ERR_INVALID_REQUEST, f"consent_grant_id {consent_grant_id} not found")

        # Priority 14: intake must be SCREENED.
        if intake["status"] != "SCREENED":
            raise_error(ERR_INTAKE_NOT_SCREENED, "intake must be SCREENED")

        # Priority 18: program.intake_posture must not be CLOSED.
        if program["intake_posture"] == "CLOSED":
            raise_error(ERR_PROGRAM_CLOSED_TO_INTAKE, "program is CLOSED to intake")

        # Priority 20: consent-shape.
        client = db.clients.get(intake["client_id"])
        if not client:
            # Should not happen given intake creation validates client_id, but be safe.
            raise_error(ERR_INVALID_REQUEST, "intake has dangling client_id")
        if (
            consent["provider_id"] != program["provider_id"]
            or consent["client_id"] != intake["client_id"]
            or consent["status"] != "GRANTED"
        ):
            raise_error(ERR_CONSENT_PROVIDER_MISMATCH, "consent grant does not match program+intake or is not GRANTED")

        # Priority 21: category match.
        if program["category"] not in intake["presenting_needs"]:
            raise_error(ERR_PROGRAM_CATEGORY_MISMATCH,
                        "program.category not in intake.presenting_needs")

        # Priority 22: eligibility score threshold.
        provider = db.providers.get(program["provider_id"])
        if not provider:
            raise_error(ERR_INVALID_REQUEST, "program has dangling provider_id")
        score = compute_eligibility_score(client, intake, program, provider)
        if score < REFERRAL_ACCEPT_THRESHOLD:
            raise_error(ERR_ELIGIBILITY_BELOW_THRESHOLD,
                        f"eligibility_score {score} < {REFERRAL_ACCEPT_THRESHOLD}")

        # Priority 23: age band.
        age_years = floor_years_between(client["date_of_birth"], db.clock)
        if not (program["eligibility_age_min"] <= age_years <= program["eligibility_age_max"]):
            raise_error(ERR_AGE_INELIGIBLE, "client age outside program's age band")

        # Priority 24: income.
        if client["monthly_income_cents"] > program["eligibility_income_max_cents"]:
            raise_error(ERR_INCOME_INELIGIBLE, "client income exceeds program ceiling")

        # Priority 28: capacity.
        if program["capacity_slots_taken"] >= program["capacity_slots_total"]:
            raise_error(ERR_CAPACITY_EXHAUSTED, "program capacity exhausted")

        # All gates passed. Compute travel burden.
        naive_min, routed_min = compute_travel_burden(client, provider, transport_mode)

        referral = {
            "intake_id": iid,
            "program_id": program_id,
            "consent_grant_id": consent_grant_id,
            "transport_mode": transport_mode,
            "travel_burden_naive_min": naive_min,
            "travel_burden_routed_min": routed_min,
            "eligibility_score": score,
            "provisional_cost_cents": program["unit_cost_cents"],
            "status": "PROPOSED",
        }
        _stamp_new(referral)
        db.referrals[referral["id"]] = referral

        # Side effect: increment program capacity (and posture recompute + version bump).
        increment_capacity(program)

        return success(serialise_referral(referral), 201)

    @app.get("/referrals/<rid>")
    @require_roles("Caseworker", "ProviderStaff", "PlatformAdmin")
    def get_referral(rid):
        r = _referral_or_404(rid)
        _providerstaff_ownership_of_referral(r)
        return success(serialise_referral(r), 200)

    @app.get("/referrals")
    @require_roles("Caseworker", "ProviderStaff", "PlatformAdmin")
    def list_referrals():
        limit, offset = parse_pagination(request.args)
        uid, role = get_auth()
        items = list(db.referrals.values())
        if role == "ProviderStaff":
            items = [
                r for r in items
                if (db.programs.get(r["program_id"], {}).get("provider_id") == uid)
            ]
        intake_id = request.args.get("intake_id")
        program_id = request.args.get("program_id")
        consent_grant_id = request.args.get("consent_grant_id")
        status = request.args.get("status")
        if intake_id is not None:
            items = [r for r in items if r["intake_id"] == intake_id]
        if program_id is not None:
            items = [r for r in items if r["program_id"] == program_id]
        if consent_grant_id is not None:
            items = [r for r in items if r["consent_grant_id"] == consent_grant_id]
        if status is not None:
            items = [r for r in items if r["status"] == status]
        items.sort(key=lambda x: x["created_at"])
        window, pg = paginate(items, limit, offset)
        return success([serialise_referral(r) for r in window], 200, "array", pg)

    @app.post("/referrals/<rid>/accept")
    @require_roles("ProviderStaff", "PlatformAdmin")
    def accept_referral(rid):
        r = _referral_or_404(rid)
        _providerstaff_ownership_of_referral(r)

        # Priority 15: state must be PROPOSED.
        if r["status"] != "PROPOSED":
            raise_error(ERR_REFERRAL_INVALID_STATE, "referral is not PROPOSED")

        # Priority 18: program.intake_posture must not be CLOSED.
        program = db.programs.get(r["program_id"])
        if program and program["intake_posture"] == "CLOSED":
            raise_error(ERR_PROGRAM_CLOSED_TO_INTAKE, "program is CLOSED to intake")

        # Priority 19: consent must be GRANTED.
        consent = db.consent_grants.get(r["consent_grant_id"])
        if not consent or consent["status"] != "GRANTED":
            raise_error(ERR_CONSENT_NOT_GRANTED, "consent grant is not GRANTED")

        r["status"] = "ACCEPTED"
        _touch(r)
        return success(serialise_referral(r), 200)

    @app.post("/referrals/<rid>/decline")
    @require_roles("ProviderStaff", "PlatformAdmin")
    def decline_referral(rid):
        r = _referral_or_404(rid)
        _providerstaff_ownership_of_referral(r)
        if r["status"] != "PROPOSED":
            raise_error(ERR_REFERRAL_INVALID_STATE, "referral is not PROPOSED")
        r["status"] = "DECLINED"
        _touch(r)
        program = db.programs.get(r["program_id"])
        if program:
            decrement_capacity(program)
        maybe_bubble_intake_closed(r["intake_id"])
        return success(serialise_referral(r), 200)

    @app.post("/referrals/<rid>/start-service")
    @require_roles("ProviderStaff", "PlatformAdmin")
    def start_service(rid):
        r = _referral_or_404(rid)
        _providerstaff_ownership_of_referral(r)
        if r["status"] != "ACCEPTED":
            raise_error(ERR_REFERRAL_INVALID_STATE, "referral is not ACCEPTED")
        consent = db.consent_grants.get(r["consent_grant_id"])
        if not consent or consent["status"] != "GRANTED":
            raise_error(ERR_CONSENT_NOT_GRANTED, "consent grant is not GRANTED")
        r["status"] = "SERVICE_IN_PROGRESS"
        _touch(r)
        return success(serialise_referral(r), 200)

    @app.post("/referrals/<rid>/complete")
    @require_roles("ProviderStaff", "PlatformAdmin")
    def complete_referral(rid):
        r = _referral_or_404(rid)
        _providerstaff_ownership_of_referral(r)
        if r["status"] != "SERVICE_IN_PROGRESS":
            raise_error(ERR_REFERRAL_INVALID_STATE, "referral is not SERVICE_IN_PROGRESS")
        body = require_body(request.get_json(silent=True))
        outcome_class = require_str(body, "outcome_class")
        if outcome_class not in ("SUCCESS", "UNSUCCESSFUL"):
            raise_error(ERR_INVALID_REQUEST, "outcome_class must be SUCCESS or UNSUCCESSFUL")
        r["status"] = "COMPLETED_SUCCESS" if outcome_class == "SUCCESS" else "COMPLETED_UNSUCCESSFUL"
        _touch(r)
        program = db.programs.get(r["program_id"])
        if program:
            decrement_capacity(program)
        maybe_bubble_intake_closed(r["intake_id"])
        return success(serialise_referral(r), 200)

    @app.post("/referrals/<rid>/withdraw")
    @require_roles("Client", "Caseworker", "PlatformAdmin")
    def withdraw_referral(rid):
        r = _referral_or_404(rid)
        _client_ownership_of_referral(r)
        if r["status"] not in REFERRAL_INFLIGHT:
            raise_error(ERR_REFERRAL_INVALID_STATE, "referral is terminal")
        cascade_referral_withdraw(r)
        return success(serialise_referral(r), 200)
