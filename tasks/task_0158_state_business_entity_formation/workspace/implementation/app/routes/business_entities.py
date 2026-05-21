"""Business entity routes: create/list/read, form, dissolve, administratively-dissolve,
exposure-summary, credit-deposit, BOI ownership endpoints, compliance-events list."""
from __future__ import annotations

from datetime import timedelta
from typing import Any

from flask import Blueprint, jsonify, request

from ..auth import current_caller, require_auth
from ..envelope import array_response, object_response
from ..errors import (
    APIError,
    err_entity_not_active,
    err_has_dependencies,
    err_invalid_input,
    err_invalid_state,
    err_not_found,
    err_segregation,
)
from ..store import store
from ..timeutil import anniversary_one_year_after, now as clock_now
from ..util import (
    STATE_CODE_RE,
    get_json_body,
    new_uuid,
    optional_enum,
    optional_int,
    parse_pagination,
    require_enum,
    require_int,
    require_state_code,
    require_str,
)
from ..services import serializers
from ..services.calculations import compute_total_due, exposure_score
from ..services.engine import (
    active_ownerships_for,
    cascade_foreign_qualifications_on_dissolution,
    emit_event,
    latest_current_or_corrected_report,
    ownerships_active_at,
    recompute_compliance_status,
    run_sweep,
    touch,
)


bp = Blueprint("entities", __name__, url_prefix="/business-registry")


def _entity_or_404(entity_id: str) -> dict[str, Any]:
    entity = store.business_entities.get(entity_id)
    if entity is None:
        raise err_not_found(f"Business entity {entity_id!r} not found")
    return entity


# ---- Create / list / read --------------------------------------------------------

@bp.post("/entities")
@require_auth(["Filer"])
def create_entity():
    body = get_json_body()
    legal_name = require_str(body, "legal_name", min_len=1, max_len=200)
    entity_type = require_enum(body, "entity_type", {"LLC", "CORP", "LP"})
    home_state = require_state_code(body, "home_state")
    registered_agent_id = require_str(body, "registered_agent_id")

    authorized_shares = optional_int(body, "authorized_shares", minimum=1)
    total_gross_assets_cents = optional_int(body, "total_gross_assets_cents", minimum=0, default=0)
    total_issued_shares = optional_int(body, "total_issued_shares", minimum=0, default=0)

    with store.lock:
        # Body-FK existence
        if registered_agent_id not in store.registered_agents:
            raise err_not_found(f"registered_agent_id {registered_agent_id!r} not found")

        # Type-driven authorized_shares semantics
        if entity_type == "CORP":
            if authorized_shares is None:
                raise err_invalid_input("authorized_shares is required for CORP and must be >= 1")
        else:
            if authorized_shares is not None:
                raise err_invalid_input("authorized_shares must be null for non-CORP entities")

        # Uniqueness check
        lower = legal_name.lower()
        for existing in store.business_entities.values():
            if existing.get("formation_status") in ("DISSOLVED", "ADMINISTRATIVELY_DISSOLVED"):
                continue
            if (existing.get("legal_name") or "").lower() == lower:
                raise APIError("ERR_DUPLICATE_LEGAL_NAME", f"legal_name {legal_name!r} already in use", 409)

        now = clock_now()
        entity = {
            "id": new_uuid(),
            "created_at": now,
            "updated_at": now,
            "version": 1,
            "legal_name": legal_name,
            "entity_type": entity_type,
            "home_state": home_state,
            "formation_date": None,
            "registered_agent_id": registered_agent_id,
            "authorized_shares": authorized_shares,
            "total_gross_assets_cents": total_gross_assets_cents or 0,
            "total_issued_shares": total_issued_shares or 0,
            "formation_status": "PENDING_FORMATION",
            "compliance_status": None,
            "next_annual_report_due_date": None,
            "ein": None,
            "dissolution_date": None,
            "credit_balance_cents": 0,
        }
        store.business_entities[entity["id"]] = entity

    return jsonify(object_response(serializers.business_entity(entity))), 201


@bp.get("/entities/<entity_id>")
@require_auth(["Filer", "StateRegistrar", "TaxOfficer", "ComplianceOfficer"])
def read_entity(entity_id):
    entity = _entity_or_404(entity_id)
    # If ACTIVE, lazily refresh compliance posture so reads observe overdue/etc.
    if entity.get("formation_status") == "ACTIVE":
        recompute_compliance_status(entity_id)
    return jsonify(object_response(serializers.business_entity(entity))), 200


@bp.get("/entities")
@require_auth(["Filer", "StateRegistrar", "TaxOfficer", "ComplianceOfficer"])
def list_entities():
    entity_type = request.args.get("entity_type")
    formation_status = request.args.get("formation_status")
    compliance_status = request.args.get("compliance_status")
    limit, offset = parse_pagination()

    # Lazy refresh of compliance posture for ACTIVE entities so the filter is accurate.
    for entity in store.business_entities.values():
        if entity.get("formation_status") == "ACTIVE":
            recompute_compliance_status(entity["id"])

    rows = list(store.business_entities.values())
    if entity_type:
        rows = [r for r in rows if r.get("entity_type") == entity_type]
    if formation_status:
        rows = [r for r in rows if r.get("formation_status") == formation_status]
    if compliance_status:
        rows = [r for r in rows if (r.get("compliance_status") or "") == compliance_status]
    rows.sort(key=lambda r: r.get("created_at"))
    total = len(rows)
    page = rows[offset:offset + limit]
    return jsonify(array_response([serializers.business_entity(r) for r in page],
                                  limit=limit, offset=offset, total_count=total)), 200


# ---- Form / dissolve / admin-dissolve --------------------------------------------

@bp.post("/entities/<entity_id>/form")
@require_auth(["StateRegistrar"])
def form_entity(entity_id):
    with store.lock:
        entity = _entity_or_404(entity_id)
        if entity.get("formation_status") != "PENDING_FORMATION":
            raise err_invalid_state("Entity is not in PENDING_FORMATION")
        agent = store.registered_agents.get(entity.get("registered_agent_id"))
        if agent is None:
            raise err_not_found("Registered agent not found")
        if agent.get("status") != "ACTIVE":
            raise err_invalid_state("Registered agent is not ACTIVE")
        if agent.get("service_state") != entity.get("home_state"):
            raise err_invalid_state("Registered agent service_state must equal entity home_state")
        if entity.get("entity_type") == "CORP":
            if entity.get("authorized_shares") is None or int(entity.get("authorized_shares") or 0) < 1:
                raise err_invalid_input("CORP entity requires authorized_shares >= 1")
        now = clock_now()
        entity["formation_date"] = now
        entity["formation_status"] = "ACTIVE"
        entity["compliance_status"] = "GOOD_STANDING"
        entity["next_annual_report_due_date"] = anniversary_one_year_after(now)
        touch(entity, ts=now)
        emit_event(entity_id, "FORMED", {"formation_date": str(now)}, occurred_at=now)
        return jsonify(object_response(serializers.business_entity(entity))), 200


@bp.post("/entities/<entity_id>/dissolve")
@require_auth(["Filer"])
def dissolve_entity(entity_id):
    caller = current_caller()
    with store.lock:
        entity = _entity_or_404(entity_id)
        if entity.get("formation_status") != "ACTIVE":
            raise err_invalid_state("Entity is not ACTIVE")
        # Filer ownership: the entity itself must match the caller.
        if caller.user_id != entity_id:
            # Filer is "the entity"; another Filer cannot dissolve someone else's entity.
            raise APIError("ERR_FORBIDDEN", "Filer may not act on another entity", 403)

        # Dependencies
        for assessment in store.tax_assessments.values():
            if assessment.get("business_entity_id") != entity_id:
                continue
            if assessment.get("status") in ("OVERDUE", "DELINQUENT"):
                raise err_has_dependencies("Open OVERDUE/DELINQUENT tax assessment")
        for r in store.boi_reports.values():
            if r.get("business_entity_id") == entity_id and r.get("status") == "STALE":
                raise err_has_dependencies("STALE BOI report present")
        for fq in store.foreign_qualifications.values():
            if fq.get("business_entity_id") == entity_id and fq.get("status") == "QUALIFIED":
                raise err_has_dependencies("QUALIFIED ForeignQualification present; withdraw first")

        now = clock_now()
        entity["formation_status"] = "DISSOLVED"
        entity["dissolution_date"] = now
        entity["compliance_status"] = None
        touch(entity, ts=now)
        cascade_foreign_qualifications_on_dissolution(entity_id, admin=False, at=now)
        emit_event(entity_id, "VOLUNTARILY_DISSOLVED", {}, occurred_at=now)
        store.delinquent_since.pop(entity_id, None)
        return jsonify(object_response(serializers.business_entity(entity))), 200


@bp.post("/entities/<entity_id>/administratively-dissolve")
@require_auth(["ComplianceOfficer"])
def administratively_dissolve(entity_id):
    with store.lock:
        entity = _entity_or_404(entity_id)
        if entity.get("formation_status") != "ACTIVE":
            raise err_invalid_state("Entity is not ACTIVE")
        # Refresh posture so we see the latest DELINQUENT anchor.
        recompute_compliance_status(entity_id)
        if entity.get("compliance_status") != "DELINQUENT":
            raise err_invalid_state("Entity is not DELINQUENT")
        anchored = store.delinquent_since.get(entity_id)
        if anchored is None:
            raise err_invalid_state("Entity DELINQUENT anchor not set")
        now = clock_now()
        if (now - anchored) < timedelta(days=60):
            raise err_invalid_state("Entity has not been DELINQUENT for 60+ days")

        entity["formation_status"] = "ADMINISTRATIVELY_DISSOLVED"
        entity["dissolution_date"] = now
        entity["compliance_status"] = None
        touch(entity, ts=now)
        cascade_foreign_qualifications_on_dissolution(entity_id, admin=True, at=now)
        emit_event(entity_id, "ADMIN_DISSOLVED", {}, occurred_at=now)
        store.delinquent_since.pop(entity_id, None)
        return jsonify(object_response(serializers.business_entity(entity))), 200


# ---- Credit deposit --------------------------------------------------------------

@bp.post("/entities/<entity_id>/credit-deposit")
@require_auth(["TaxOfficer"])
def credit_deposit(entity_id):
    body = get_json_body()
    amount = require_int(body, "amount_cents", minimum=1)
    with store.lock:
        entity = _entity_or_404(entity_id)
        # No formation-status gate is specified for credit-deposit in PRD/scaffold;
        # allow on any entity.
        entity["credit_balance_cents"] = int(entity.get("credit_balance_cents", 0)) + amount
        touch(entity)
        return jsonify(object_response(serializers.business_entity(entity))), 200


# ---- Exposure summary ------------------------------------------------------------

@bp.get("/entities/<entity_id>/exposure-summary")
@require_auth(["Filer", "ComplianceOfficer"])
def exposure_summary(entity_id):
    entity = _entity_or_404(entity_id)
    view = request.args.get("view", "finalized")
    if view not in ("provisional", "finalized"):
        raise err_invalid_input("Query parameter 'view' must be one of {provisional, finalized}")

    owners = {o["id"]: o for o in store.beneficial_owners.values()}
    provisional_rows = active_ownerships_for(entity_id)
    prov_score = exposure_score(provisional_rows, owners)

    # Finalized: snapshot at the most recent BOIReport with status IN {CURRENT, CORRECTED}
    latest = latest_current_or_corrected_report(entity_id)
    if latest is None:
        fin_rows = []
    else:
        # If latest BOI report status is STALE/DRAFT we would have picked the prior CURRENT
        # because we filter to CURRENT/CORRECTED above. The snapshot instant is filed_at.
        fin_rows = ownerships_active_at(entity_id, latest.get("filed_at") or latest.get("created_at"))
    fin_score = exposure_score(fin_rows, owners)

    score = prov_score if view == "provisional" else fin_score
    return jsonify(object_response({
        "business_entity_id": entity_id,
        "view": view,
        "score": score,
        "provisional_score": prov_score,
        "finalized_score": fin_score,
    })), 200


# ---- BOI Ownership endpoints (nested under entity) -------------------------------

@bp.post("/entities/<entity_id>/boi-ownership")
@require_auth(["Filer"])
def add_ownership(entity_id):
    caller = current_caller()
    body = get_json_body()
    beneficial_owner_id = require_str(body, "beneficial_owner_id")
    bps = require_int(body, "ownership_percent_basis_points", minimum=0, maximum=10000)
    with store.lock:
        entity = _entity_or_404(entity_id)
        if beneficial_owner_id not in store.beneficial_owners:
            raise err_not_found(f"beneficial_owner_id {beneficial_owner_id!r} not found")
        if entity.get("formation_status") != "ACTIVE":
            raise err_entity_not_active()
        if caller.user_id != entity_id:
            raise APIError("ERR_FORBIDDEN", "Filer may not act on another entity", 403)
        now = clock_now()
        row = {
            "id": new_uuid(),
            "created_at": now,
            "business_entity_id": entity_id,
            "beneficial_owner_id": beneficial_owner_id,
            "ownership_percent_basis_points": bps,
            "effective_at": now,
            "terminated_at": None,
        }
        store.boi_ownerships[row["id"]] = row
        # Schedule the 30-day stale check iff a CURRENT BOIReport exists.
        latest = latest_current_or_corrected_report(entity_id)
        if latest is not None and latest.get("status") == "CURRENT":
            store.ownership_change_at[entity_id] = now
        return jsonify(object_response(serializers.boi_ownership(row))), 201


@bp.delete("/entities/<entity_id>/boi-ownership/<ownership_id>")
@require_auth(["Filer"])
def terminate_ownership(entity_id, ownership_id):
    caller = current_caller()
    with store.lock:
        entity = _entity_or_404(entity_id)
        row = store.boi_ownerships.get(ownership_id)
        if row is None or row.get("business_entity_id") != entity_id:
            raise err_not_found(f"ownership_id {ownership_id!r} not found under entity {entity_id!r}")
        if entity.get("formation_status") != "ACTIVE":
            raise err_entity_not_active()
        if caller.user_id != entity_id:
            raise APIError("ERR_FORBIDDEN", "Filer may not act on another entity", 403)
        if row.get("terminated_at") is not None:
            raise err_invalid_state("BOI ownership already terminated")
        now = clock_now()
        row["terminated_at"] = now
        # Schedule the 30-day stale timer if a CURRENT BOI report exists.
        latest = latest_current_or_corrected_report(entity_id)
        if latest is not None and latest.get("status") == "CURRENT":
            store.ownership_change_at[entity_id] = now
        return ("", 204)


# ---- Compliance events list ------------------------------------------------------

@bp.get("/entities/<entity_id>/compliance-events")
@require_auth(["Filer", "StateRegistrar", "TaxOfficer", "ComplianceOfficer"])
def list_compliance_events(entity_id):
    _entity_or_404(entity_id)
    limit, offset = parse_pagination()
    event_type = request.args.get("event_type")
    rows = [r for r in store.compliance_events.values() if r.get("business_entity_id") == entity_id]
    if event_type:
        rows = [r for r in rows if r.get("event_type") == event_type]
    rows.sort(key=lambda r: r.get("occurred_at"))
    total = len(rows)
    page = rows[offset:offset + limit]
    return jsonify(array_response([serializers.compliance_event(r) for r in page],
                                  limit=limit, offset=offset, total_count=total)), 200
