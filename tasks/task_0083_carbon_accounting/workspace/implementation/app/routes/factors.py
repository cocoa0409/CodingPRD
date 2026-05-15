"""EmissionFactor endpoints."""
from __future__ import annotations

from decimal import Decimal

from flask import Blueprint, g, request

from ..auth import require_auth
from ..errors import api_error
from ..response import empty_204, list_envelope, success_envelope
from ..store import store, now_ts
from ..utils import (
    check_version,
    decimal_places,
    get_json_body,
    page_slice,
    parse_iso_datetime,
    parse_pagination,
    require_enum,
    require_str,
    to_decimal,
    validate_code,
)
from ._helpers import get_factor_or_404, get_org_or_404, sort_by_created


factors_bp = Blueprint("factors", __name__)


LIBRARIES = {"IPCC_DEFAULT", "NATIONAL_PUBLISHED", "SUPPLIER_SPECIFIC", "MEASURED"}
GAS_TYPES = {"CO2", "CH4", "N2O", "HFC", "PFC", "SF6", "NF3"}
SCOPE2_METHODS = {"LOCATION_BASED", "MARKET_BASED"}
UNCERTAINTIES = {"LOW", "MEDIUM", "HIGH"}


def _bump(row: dict) -> None:
    """Refresh updated_at on a factor without changing `version`.

    For EmissionFactor, `version` is the per-code factor version (1, 2, 3 …),
    not a per-row mutation counter; see scaffold entity definition.
    """
    row["updated_at"] = now_ts()


def _serialize_factor(row: dict) -> dict:
    """Return a copy of an EmissionFactor row with internal-only fields
    stripped before sending to the client."""
    out = dict(row)
    out.pop("_predecessor_at_create_id", None)
    return out


@factors_bp.route("/organizations/<org_id>/factors", methods=["POST"])
@require_auth(["FactorManager"])
def create_factor(org_id):
    get_org_or_404(org_id)
    body = get_json_body()
    code = require_str(body, "code", min_len=1, max_len=50)
    validate_code(code, "code")
    library = require_enum(body, "library", LIBRARIES)
    gas_type = require_enum(body, "gas_type", GAS_TYPES)
    scope2_method = body.get("scope2_method")
    if scope2_method is not None and scope2_method not in SCOPE2_METHODS:
        raise api_error("ERR_VALIDATION_FAILED", "Invalid scope2_method")

    kg_per_unit_raw = body.get("kg_per_unit")
    kg_per_unit = to_decimal(kg_per_unit_raw, "kg_per_unit")
    if kg_per_unit < 0:
        raise api_error("ERR_VALIDATION_FAILED", "kg_per_unit must be >= 0")
    if decimal_places(kg_per_unit) > 6:
        raise api_error("ERR_VALIDATION_FAILED", "kg_per_unit must have at most 6 decimal places")

    uncertainty = require_enum(body, "uncertainty_rating", UNCERTAINTIES)
    effective_from = parse_iso_datetime(body.get("effective_from"))
    traceability_url = require_str(body, "traceability_url", min_len=1, max_len=500)

    # version is server-assigned per code: next version for the family
    existing = [
        ef for ef in store.emission_factors.values()
        if ef.get("organization_id") == org_id and ef.get("code") == code
    ]
    next_version = 1 + max((ef.get("version", 0) for ef in existing), default=0)

    # Capture the predecessor ACTIVE for this code at draft creation. Used
    # at approve time to detect concurrent supersession (PRD §3.4).
    predecessor_at_create_id = None
    for ef in store.emission_factors.values():
        if (
            ef.get("organization_id") == org_id
            and ef.get("code") == code
            and ef.get("status") == "ACTIVE"
        ):
            predecessor_at_create_id = ef["id"]
            break

    payload = {
        "organization_id": org_id,
        "code": code,
        "library": library,
        "gas_type": gas_type,
        "scope2_method": scope2_method,
        "kg_per_unit": float(kg_per_unit),
        "uncertainty_rating": uncertainty,
        "effective_from": body.get("effective_from"),
        "effective_to": None,
        "status": "DRAFT",
        "traceability_url": traceability_url,
        "approved_by_user_id": None,
        "_predecessor_at_create_id": predecessor_at_create_id,
    }
    with store.lock:
        store.stamp_create(payload)
        # Override common `version` with per-code factor version, per scaffold's
        # EmissionFactor.version field definition.
        payload["version"] = next_version
        store.emission_factors[payload["id"]] = payload
    return success_envelope(_serialize_factor(payload), status=201)


@factors_bp.route("/organizations/<org_id>/factors/<factor_id>/approve", methods=["POST"])
@require_auth(["FactorManager"])
def approve_factor(org_id, factor_id):
    get_org_or_404(org_id)
    factor = get_factor_or_404(org_id, factor_id)
    body = get_json_body()

    if factor.get("status") != "DRAFT":
        raise api_error("ERR_INVALID_STATE", "Factor must be in DRAFT to approve")
    check_version(body, factor)

    actor_user_id = g.user_id
    actor_role = g.user_role

    with store.lock:
        # Re-check status under the lock to serialize concurrent approvals
        # (PRD §3.4: approvals serialize on the code).
        if factor.get("status") != "DRAFT":
            raise api_error("ERR_INVALID_STATE", "Factor must be in DRAFT to approve")

        # Find current ACTIVE predecessor for the same code
        predecessor = None
        for ef in store.emission_factors.values():
            if (
                ef.get("organization_id") == org_id
                and ef.get("code") == factor["code"]
                and ef.get("status") == "ACTIVE"
            ):
                predecessor = ef
                break

        # PRD §3.4: "the loser sees a freshly superseded predecessor — the
        # loser receives ERR_FACTOR_VERSION_CONFLICT". Detect a
        # concurrent-approval race: at draft creation we captured the
        # then-ACTIVE predecessor for the code. If that predecessor is no
        # longer ACTIVE at approve time, another approval has freshly
        # superseded it — we are the loser.
        expected_pred_id = factor.get("_predecessor_at_create_id")
        if expected_pred_id is not None:
            pred_now = store.emission_factors.get(expected_pred_id)
            if pred_now is None or pred_now.get("status") != "ACTIVE":
                raise api_error(
                    "ERR_FACTOR_VERSION_CONFLICT",
                    "Predecessor was freshly superseded by a concurrent approval",
                )
        else:
            # No predecessor was expected at draft creation. If a different
            # ACTIVE factor for this code now exists, another approval beat
            # us to the punch — we are the loser.
            for ef in store.emission_factors.values():
                if ef.get("id") == factor["id"]:
                    continue
                if ef.get("organization_id") != org_id:
                    continue
                if ef.get("code") != factor["code"]:
                    continue
                if ef.get("status") == "ACTIVE":
                    raise api_error(
                        "ERR_FACTOR_VERSION_CONFLICT",
                        "Another approval for this code became ACTIVE first",
                    )

        new_eff = parse_iso_datetime(factor["effective_from"])
        if predecessor is not None:
            prev_eff = parse_iso_datetime(predecessor["effective_from"])
            if not (new_eff > prev_eff):
                raise api_error(
                    "ERR_FACTOR_EFFECTIVE_FROM_ORDER",
                    "effective_from must be strictly greater than predecessor's effective_from",
                )

        # Approve
        factor["status"] = "ACTIVE"
        factor["approved_by_user_id"] = actor_user_id
        _bump(factor)

        # Cascade predecessor
        affected_periods: set[str] = set()
        if predecessor is not None:
            predecessor["status"] = "SUPERSEDED"
            predecessor["effective_to"] = factor["effective_from"]
            _bump(predecessor)
            # Cascade emission records pinned to predecessor whose parent ReportingPeriod.status == OPEN
            for er in store.emission_records.values():
                if er.get("emission_factor_id") != predecessor["id"]:
                    continue
                if er.get("status") != "FRESH":
                    continue
                period = store.reporting_periods.get(er.get("reporting_period_id"))
                if not period or period.get("status") != "OPEN":
                    continue
                er["status"] = "STALE"
                _bump(er)
                affected_periods.add(er["reporting_period_id"])
            store.append_audit(
                organization_id=org_id,
                actor_user_id=actor_user_id,
                actor_role=actor_role,
                event_type="FACTOR_SUPERSEDE",
                target_entity="EmissionFactor",
                target_id=predecessor["id"],
                payload_json={"code": predecessor["code"], "version": predecessor.get("version")},
            )

        # Cascade reports
        if affected_periods:
            for rep in store.reports.values():
                if rep.get("organization_id") != org_id:
                    continue
                if (
                    rep.get("reporting_period_id") in affected_periods
                    and rep.get("status") in ("DRAFT", "UNDER_REVIEW")
                ):
                    rep["status"] = "RECOMPUTE_REQUIRED"
                    _bump(rep)

        store.append_audit(
            organization_id=org_id,
            actor_user_id=actor_user_id,
            actor_role=actor_role,
            event_type="FACTOR_APPROVE",
            target_entity="EmissionFactor",
            target_id=factor["id"],
            payload_json={"code": factor["code"], "version": factor.get("version")},
        )

    return success_envelope(_serialize_factor(factor))


@factors_bp.route("/organizations/<org_id>/factors/<factor_id>", methods=["DELETE"])
@require_auth(["FactorManager"])
def retire_factor(org_id, factor_id):
    get_org_or_404(org_id)
    factor = get_factor_or_404(org_id, factor_id)

    if factor.get("status") != "DRAFT":
        raise api_error("ERR_INVALID_STATE", "Only DRAFT factors can be retired")

    # Check OCC via query (no body)
    if "version" in request.args:
        try:
            v = int(request.args["version"])
        except (TypeError, ValueError):
            raise api_error("ERR_VERSION_CONFLICT", "version mismatch")
        if v != factor.get("version"):
            raise api_error("ERR_VERSION_CONFLICT", "Supplied version does not match stored version")
    body = get_json_body() if request.data else {}
    if body:
        check_version(body, factor)

    # No EmissionRecord may reference this factor
    for er in store.emission_records.values():
        if er.get("emission_factor_id") == factor_id:
            raise api_error("ERR_INVALID_STATE", "Factor is referenced by an EmissionRecord")

    with store.lock:
        factor["status"] = "RETIRED"
        _bump(factor)
    return empty_204()


@factors_bp.route("/organizations/<org_id>/factors", methods=["GET"])
@require_auth(["FactorManager", "DataSteward", "Verifier"])
def list_factors(org_id):
    get_org_or_404(org_id)
    limit, offset = parse_pagination()
    code_f = request.args.get("code")
    status_f = request.args.get("status")
    items = [
        ef for ef in store.emission_factors.values()
        if ef.get("organization_id") == org_id
        and (code_f is None or ef.get("code") == code_f)
        and (status_f is None or ef.get("status") == status_f)
    ]
    items = sort_by_created(items)
    page, total = page_slice(items, limit, offset)
    return list_envelope([_serialize_factor(it) for it in page], total, limit, offset)
