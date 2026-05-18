"""Client endpoints + risk questionnaire."""
from __future__ import annotations

from flask import Blueprint, g

from db import store
from errors import (
    err_client_not_accepting_input,
    err_fk_not_found,
    err_invalid_state,
    err_questionnaire_out_of_range,
    err_resource_not_found,
    err_time_horizon_out_of_range,
)
from middleware import require_auth
from response import success
from routes._helpers import check_version, get_json, parse_version
from services.calculations import compute_risk_score, derive_horizon_band
from services.engine import (
    assign_models_for_client,
    cascade_client_reinstate,
    cascade_client_suspend,
    recompute_client_age,
    stamp_create,
    stamp_update,
)
from services.serializers import (
    serialize_client,
    serialize_risk_questionnaire,
)
from utils import iso_now, parse_iso_date

bp = Blueprint("clients", __name__)


def _get_client_or_404(client_id):
    c = store.clients.get(client_id)
    if c is None:
        raise err_resource_not_found("Client not found.")
    return c


def _check_client_ownership_for_clientuser(client_id: str):
    if g.role == "ClientUser" and g.user_id != client_id:
        from errors import err_auth_forbidden
        raise err_auth_forbidden("ClientUser may only act on their own client id.")


def _validate_time_horizon(value):
    if value is None:
        raise err_time_horizon_out_of_range("time_horizon_years is required.")
    if isinstance(value, bool) or not isinstance(value, int):
        raise err_time_horizon_out_of_range("time_horizon_years must be an integer.")
    if value < 1 or value > 40:
        raise err_time_horizon_out_of_range()
    return value


# ── POST /clients ───────────────────────────────────────────────────────────


@bp.post("/clients")
@require_auth(["ComplianceOfficer"])
def create_client():
    body = get_json()
    full_name = body.get("full_name")
    if not isinstance(full_name, str) or not (1 <= len(full_name) <= 120):
        raise err_invalid_state("full_name must be 1–120 characters.")
    birth_date_raw = body.get("birth_date")
    if not isinstance(birth_date_raw, str):
        raise err_invalid_state("birth_date is required (ISO 8601 calendar date).")
    try:
        parse_iso_date(birth_date_raw)
    except Exception:
        raise err_invalid_state("birth_date must be ISO 8601 (YYYY-MM-DD).")
    horizon = _validate_time_horizon(body.get("time_horizon_years"))

    with store.lock:
        client = {
            "full_name": full_name,
            "birth_date": birth_date_raw,
            "age": None,
            "kyc_status": "PENDING",
            "risk_band": None,
            "time_horizon_years": horizon,
        }
        stamp_create(client)
        recompute_client_age(client)
        store.clients[client["id"]] = client
    return success(serialize_client(client), 201)


# ── GET /clients/{clientId} ────────────────────────────────────────────────


@bp.get("/clients/<client_id>")
@require_auth(["ComplianceOfficer", "Advisor", "TaxAdmin", "ClientUser"])
def get_client(client_id):
    c = _get_client_or_404(client_id)
    _check_client_ownership_for_clientuser(client_id)
    return success(serialize_client(c))


# ── PATCH /clients/{clientId} ──────────────────────────────────────────────


@bp.patch("/clients/<client_id>")
@require_auth(["ComplianceOfficer"])
def patch_client(client_id):
    c = _get_client_or_404(client_id)
    body = get_json()
    expected_version = parse_version(body)
    check_version(c, expected_version)

    old_horizon_band = derive_horizon_band(c.get("time_horizon_years"))
    changed = False
    if "full_name" in body:
        nm = body["full_name"]
        if not isinstance(nm, str) or not (1 <= len(nm) <= 120):
            raise err_invalid_state("full_name must be 1–120 characters.")
        c["full_name"] = nm
        changed = True
    if "time_horizon_years" in body:
        new_h = _validate_time_horizon(body["time_horizon_years"])
        c["time_horizon_years"] = new_h
        changed = True

    with store.lock:
        if changed:
            stamp_update(c)
        new_horizon_band = derive_horizon_band(c.get("time_horizon_years"))
        if c.get("kyc_status") == "ACTIVE" and old_horizon_band != new_horizon_band:
            assign_models_for_client(c, only_null=False)
    return success(serialize_client(c))


# ── POST /clients/{clientId}/activate ───────────────────────────────────────


@bp.post("/clients/<client_id>/activate")
@require_auth(["ComplianceOfficer"])
def activate_client(client_id):
    c = _get_client_or_404(client_id)
    if c["kyc_status"] != "PENDING":
        raise err_invalid_state(f"Client not in PENDING (was {c['kyc_status']}).")
    has_q = any(q["client_id"] == client_id for q in store.risk_questionnaires.values())
    if not has_q:
        raise err_invalid_state("Client has not submitted a risk questionnaire.")
    if c.get("time_horizon_years") is None:
        raise err_invalid_state("Client.time_horizon_years not set.")

    with store.lock:
        c["kyc_status"] = "ACTIVE"
        stamp_update(c)
        assign_models_for_client(c, only_null=True)
    return success(serialize_client(c))


# ── POST /clients/{clientId}/suspend ────────────────────────────────────────


@bp.post("/clients/<client_id>/suspend")
@require_auth(["ComplianceOfficer"])
def suspend_client(client_id):
    c = _get_client_or_404(client_id)
    if c["kyc_status"] != "ACTIVE":
        raise err_invalid_state(f"Client not ACTIVE (was {c['kyc_status']}).")
    with store.lock:
        c["kyc_status"] = "SUSPENDED"
        stamp_update(c)
        cascade_client_suspend(c)
    return success(serialize_client(c))


# ── POST /clients/{clientId}/reinstate ──────────────────────────────────────


@bp.post("/clients/<client_id>/reinstate")
@require_auth(["ComplianceOfficer"])
def reinstate_client(client_id):
    c = _get_client_or_404(client_id)
    if c["kyc_status"] != "SUSPENDED":
        raise err_invalid_state(f"Client not SUSPENDED (was {c['kyc_status']}).")
    with store.lock:
        c["kyc_status"] = "ACTIVE"
        stamp_update(c)
        cascade_client_reinstate(c)
    return success(serialize_client(c))


# ── POST /clients/{clientId}/risk-questionnaire ────────────────────────────


@bp.post("/clients/<client_id>/risk-questionnaire")
@require_auth(["ComplianceOfficer", "ClientUser"])
def submit_risk_questionnaire(client_id):
    c = _get_client_or_404(client_id)
    _check_client_ownership_for_clientuser(client_id)
    if c.get("kyc_status") == "SUSPENDED":
        raise err_client_not_accepting_input()

    body = get_json()
    answers = {}
    for field in (
        "q1_loss_tolerance",
        "q2_volatility_comfort",
        "q3_growth_vs_stability",
        "q4_liquidity_need",
        "q5_experience",
    ):
        v = body.get(field)
        if v is None or isinstance(v, bool) or not isinstance(v, int):
            raise err_questionnaire_out_of_range(f"{field} must be an integer in [1,5].")
        if v < 1 or v > 5:
            raise err_questionnaire_out_of_range()
        answers[field] = v

    scoring_method = body.get("scoring_method", "STANDARD")
    if scoring_method not in ("STANDARD", "AGE_ADJUSTED"):
        raise err_invalid_state("scoring_method must be STANDARD or AGE_ADJUSTED.")

    recompute_client_age(c)

    raw, band = compute_risk_score(
        answers["q1_loss_tolerance"],
        answers["q2_volatility_comfort"],
        answers["q3_growth_vs_stability"],
        answers["q4_liquidity_need"],
        answers["q5_experience"],
        scoring_method,
        c.get("age"),
    )

    with store.lock:
        q = {
            "client_id": client_id,
            "submitted_at": iso_now(store.now()),
            **answers,
            "scoring_method": scoring_method,
            "raw_score": raw,
            "assigned_band": band,
        }
        stamp_create(q, common=False)
        store.risk_questionnaires[q["id"]] = q
        c["risk_band"] = band
        stamp_update(c)
    return success(serialize_risk_questionnaire(q), 201)
