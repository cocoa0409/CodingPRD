"""Contract endpoints (create/activate/expire/terminate/renew + nested
renewal-analysis create)."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_CONTRACT_TERM_NOT_ENDED,
    ERR_DUPLICATE_CONTRACT_REF,
    ERR_GROUP_NOT_ACTIVE,
    ERR_INVALID_RATE_CONFIG,
    ERR_INVALID_DATE_RANGE,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE_TRANSITION,
    ERR_NOT_FOUND,
    ERR_PROGRAM_NOT_ACTIVE,
    ERR_RENEWAL_NOT_RECOMMENDED,
    ERR_STALE_VERSION,
    ERR_YEARS_IN_FLIGHT,
    ERR_YEARS_NOT_CLOSED,
)
from middleware import ALL_ROLES, require_roles
from response import success_list, success_object
from util import (
    apply_filters,
    get_json_body,
    paginate,
    parse_pagination,
    reject_unknown_fields,
    require_date,
    require_enum,
    require_int,
    require_list,
    require_string,
    optional_int,
    sort_by_created_at,
)

bp = Blueprint("contracts", __name__)

RISK_TRACKS = {"ONE_SIDED_UPSIDE", "TWO_SIDED"}
RISK_MODELS = {"PROSPECTIVE", "CONCURRENT"}
ESTIMATE_METHODS = {"ANNUALIZATION", "COMPLETION_FACTOR"}

CONTRACT_FIELDS = {
    "program_id", "practice_group_id", "contract_ref", "effective_start",
    "effective_end", "risk_track", "risk_model", "benchmark_pmpm_cents",
    "shared_savings_rate_bp", "shared_loss_rate_bp", "min_savings_rate_bp",
    "min_loss_rate_bp", "savings_cap_bp", "loss_cap_bp", "stop_loss_cents",
    "withhold_rate_bp", "quality_gate_floor_points", "quality_gate_excellence_points",
    "estimate_method", "quality_measures",
}

COPY_TERM_FIELDS = [
    "program_id", "practice_group_id", "effective_start", "effective_end",
    "risk_track", "risk_model", "benchmark_pmpm_cents", "shared_savings_rate_bp",
    "shared_loss_rate_bp", "min_savings_rate_bp", "min_loss_rate_bp",
    "savings_cap_bp", "loss_cap_bp", "stop_loss_cents", "withhold_rate_bp",
    "quality_gate_floor_points", "quality_gate_excellence_points",
    "estimate_method", "quality_measures",
]


def _validate_quality_measures(raw) -> list:
    """Shape (priority 5): array of objects with the declared fields of valid
    types. Fiscal sanity (priority 12) is checked separately."""
    measures = require_list_safe(raw)
    out = []
    for entry in measures:
        if not isinstance(entry, dict):
            raise_err(ERR_INVALID_REQUEST, "quality_measures entries must be objects")
        reject_unknown_fields(entry, {"measure_code", "weight_bp", "decile_thresholds_bp"})
        code = entry.get("measure_code")
        if not isinstance(code, str) or code == "":
            raise_err(ERR_INVALID_REQUEST, "measure_code must be a non-empty string")
        weight = entry.get("weight_bp")
        if isinstance(weight, bool) or not isinstance(weight, int):
            raise_err(ERR_INVALID_REQUEST, "weight_bp must be an integer")
        thresholds = entry.get("decile_thresholds_bp")
        if not isinstance(thresholds, list) or any(
            isinstance(t, bool) or not isinstance(t, int) for t in thresholds
        ):
            raise_err(ERR_INVALID_REQUEST, "decile_thresholds_bp must be an array of integers")
        out.append(
            {
                "measure_code": code,
                "weight_bp": weight,
                "decile_thresholds_bp": list(thresholds),
            }
        )
    return out


def require_list_safe(raw) -> list:
    if not isinstance(raw, list):
        raise_err(ERR_INVALID_REQUEST, "quality_measures must be an array")
    return raw


def _validate_rate_config(payload: dict, measures: list) -> None:
    """Priority 12 (fiscal / rate sanity) -> ERR_INVALID_RATE_CONFIG (422),
    then ERR_INVALID_DATE_RANGE for the term."""
    if payload["benchmark_pmpm_cents"] <= 0:
        raise_err(ERR_INVALID_RATE_CONFIG, "benchmark_pmpm_cents must be > 0")
    for name in (
        "shared_savings_rate_bp", "min_savings_rate_bp", "savings_cap_bp", "withhold_rate_bp",
    ):
        if payload[name] < 0 or payload[name] > 10000:
            raise_err(ERR_INVALID_RATE_CONFIG, f"{name} must be in 0..10000")
    if payload["risk_track"] == "TWO_SIDED":
        if payload.get("shared_loss_rate_bp") is None or payload.get("loss_cap_bp") is None:
            raise_err(ERR_INVALID_RATE_CONFIG, "TWO_SIDED requires shared_loss_rate_bp and loss_cap_bp")
    for name in ("shared_loss_rate_bp", "min_loss_rate_bp", "loss_cap_bp"):
        value = payload.get(name)
        if value is not None and (value < 0 or value > 10000):
            raise_err(ERR_INVALID_RATE_CONFIG, f"{name} must be in 0..10000")
    floor_pts = payload["quality_gate_floor_points"]
    excellence = payload["quality_gate_excellence_points"]
    if not (0 <= floor_pts <= 100) or not (0 <= excellence <= 100) or floor_pts >= excellence:
        raise_err(
            ERR_INVALID_RATE_CONFIG,
            "quality_gate_floor_points must be strictly less than quality_gate_excellence_points, both in 0..100",
        )
    for entry in measures:
        thresholds = entry["decile_thresholds_bp"]
        if entry["weight_bp"] <= 0:
            raise_err(ERR_INVALID_RATE_CONFIG, "quality measure weight_bp must be > 0")
        if len(thresholds) != 9 or any(thresholds[i] >= thresholds[i + 1] for i in range(8)):
            raise_err(
                ERR_INVALID_RATE_CONFIG,
                "decile_thresholds_bp must contain exactly 9 strictly ascending integers",
            )
    if db.parse_date(payload["effective_start"]) >= db.parse_date(payload["effective_end"]):
        raise_err(ERR_INVALID_DATE_RANGE, "effective_start must be before effective_end")


@bp.route("/vbc/contracts", methods=["POST"])
@require_roles("ContractManager")
def create_contract(_user_id: str, _role: str):
    body = get_json_body()
    # Priority 3: body FK existence.
    raw_program = body.get("program_id")
    if isinstance(raw_program, str) and raw_program != "" and raw_program not in db.programs:
        raise_err(ERR_NOT_FOUND, "program_id does not exist")
    raw_group = body.get("practice_group_id")
    if isinstance(raw_group, str) and raw_group != "" and raw_group not in db.practice_groups:
        raise_err(ERR_NOT_FOUND, "practice_group_id does not exist")

    # Priority 5: request shape.
    reject_unknown_fields(body, CONTRACT_FIELDS)
    payload = {
        "program_id": require_string(body, "program_id"),
        "practice_group_id": require_string(body, "practice_group_id"),
        "contract_ref": require_string(body, "contract_ref"),
        "effective_start": require_date(body, "effective_start"),
        "effective_end": require_date(body, "effective_end"),
        "risk_track": require_enum(body, "risk_track", RISK_TRACKS),
        "risk_model": require_enum(body, "risk_model", RISK_MODELS),
        "benchmark_pmpm_cents": require_int(body, "benchmark_pmpm_cents"),
        "shared_savings_rate_bp": require_int(body, "shared_savings_rate_bp"),
        "shared_loss_rate_bp": optional_int(body, "shared_loss_rate_bp"),
        "min_savings_rate_bp": require_int(body, "min_savings_rate_bp"),
        "min_loss_rate_bp": optional_int(body, "min_loss_rate_bp"),
        "savings_cap_bp": require_int(body, "savings_cap_bp"),
        "loss_cap_bp": optional_int(body, "loss_cap_bp"),
        "stop_loss_cents": require_int(body, "stop_loss_cents"),
        "withhold_rate_bp": require_int(body, "withhold_rate_bp"),
        "quality_gate_floor_points": require_int(body, "quality_gate_floor_points"),
        "quality_gate_excellence_points": require_int(body, "quality_gate_excellence_points"),
        "estimate_method": require_enum(body, "estimate_method", ESTIMATE_METHODS),
        "quality_measures": _validate_quality_measures(require_field_measures(body)),
    }
    if payload["program_id"] not in db.programs:
        raise_err(ERR_NOT_FOUND, "program_id does not exist")
    if payload["practice_group_id"] not in db.practice_groups:
        raise_err(ERR_NOT_FOUND, "practice_group_id does not exist")

    # Priority 11: contract_ref unique within the program.
    for contract in db.contracts.values():
        if contract["program_id"] == payload["program_id"] and contract["contract_ref"] == payload["contract_ref"]:
            raise_err(ERR_DUPLICATE_CONTRACT_REF, "contract_ref already exists in the program")

    # Priority 12: fiscal / rate sanity + term date range.
    _validate_rate_config(payload, payload["quality_measures"])

    contract = dict(payload)
    contract["renewed_from_contract_id"] = None
    contract["contract_status"] = "DRAFT"
    db.stamp_new(contract)
    db.contracts[contract["id"]] = contract
    return success_object(contract, 201)


def require_field_measures(body: dict):
    if "quality_measures" not in body or body["quality_measures"] is None:
        raise_err(ERR_INVALID_REQUEST, "Missing required field: quality_measures")
    return body["quality_measures"]


@bp.route("/vbc/contracts", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_contracts(_user_id: str, _role: str):
    limit, offset = parse_pagination()
    items = sort_by_created_at(list(db.contracts.values()))
    items = apply_filters(items, ["program_id", "practice_group_id", "renewed_from_contract_id", "contract_status"])
    page, total = paginate(items, limit, offset)
    return success_list(page, limit, offset, total)


@bp.route("/vbc/contracts/<contract_id>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_contract(contract_id: str, _user_id: str, _role: str):
    contract = db.contracts.get(contract_id)
    if contract is None:
        raise_err(ERR_NOT_FOUND, "Contract id does not exist")
    return success_object(contract)


@bp.route("/vbc/contracts/<contract_id>/activate", methods=["POST"])
@require_roles("ContractManager")
def activate_contract(contract_id: str, _user_id: str, _role: str):
    contract = db.contracts.get(contract_id)
    if contract is None:
        raise_err(ERR_NOT_FOUND, "Contract id does not exist")
    if contract["contract_status"] != "DRAFT":
        raise_err(ERR_INVALID_STATE_TRANSITION, "Only a DRAFT contract can be activated")
    program = db.programs.get(contract["program_id"])
    if program is None or program["program_status"] != "ACTIVE":
        raise_err(ERR_PROGRAM_NOT_ACTIVE, "Program must be ACTIVE to activate the contract")
    group = db.practice_groups.get(contract["practice_group_id"])
    if group is None or group["group_status"] != "ACTIVE":
        raise_err(ERR_GROUP_NOT_ACTIVE, "PracticeGroup must be ACTIVE to activate the contract")
    contract["contract_status"] = "ACTIVE"
    db.touch(contract)
    return success_object(contract)


@bp.route("/vbc/contracts/<contract_id>/expire", methods=["POST"])
@require_roles("ContractManager")
def expire_contract(contract_id: str, _user_id: str, _role: str):
    contract = db.contracts.get(contract_id)
    if contract is None:
        raise_err(ERR_NOT_FOUND, "Contract id does not exist")
    if contract["contract_status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE_TRANSITION, "Only an ACTIVE contract can be expired")
    # State-family precondition (priority 6) before temporal (priority 8).
    for year in db.performance_years.values():
        if year["contract_id"] == contract_id and year["year_status"] != "CLOSED":
            raise_err(ERR_YEARS_NOT_CLOSED, "Every performance year must be CLOSED before expiry")
    if db.clock_date() < db.parse_date(contract["effective_end"]):
        raise_err(ERR_CONTRACT_TERM_NOT_ENDED, "Contract term has not ended on the logical clock")
    contract["contract_status"] = "EXPIRED"
    db.touch(contract)
    return success_object(contract)


@bp.route("/vbc/contracts/<contract_id>/terminate", methods=["POST"])
@require_roles("ContractManager")
def terminate_contract(contract_id: str, _user_id: str, _role: str):
    contract = db.contracts.get(contract_id)
    if contract is None:
        raise_err(ERR_NOT_FOUND, "Contract id does not exist")
    if contract["contract_status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE_TRANSITION, "Only an ACTIVE contract can be terminated")
    in_flight = {"ATTRIBUTION_OPEN", "ATTRIBUTION_LOCKED", "MEASURING", "RECONCILING", "SETTLED"}
    for year in db.performance_years.values():
        if year["contract_id"] == contract_id and year["year_status"] in in_flight:
            raise_err(ERR_YEARS_IN_FLIGHT, "Contract has in-flight performance years")
    contract["contract_status"] = "TERMINATED"
    db.touch(contract)
    return success_object(contract)


@bp.route("/vbc/contracts/<contract_id>/renew", methods=["POST"])
@require_roles("ContractManager")
def renew_contract(contract_id: str, _user_id: str, _role: str):
    contract = db.contracts.get(contract_id)
    if contract is None:
        raise_err(ERR_NOT_FOUND, "Contract id does not exist")
    if contract["contract_status"] != "EXPIRED":
        raise_err(ERR_INVALID_STATE_TRANSITION, "Only an EXPIRED contract can be renewed")
    recommended = any(
        a["contract_id"] == contract_id
        and a["analysis_status"] == "COMPLETE"
        and a["recommendation"] in ("RENEW_AS_IS", "RENEW_RENEGOTIATE")
        for a in db.renewal_analyses.values()
    )
    if not recommended:
        raise_err(ERR_RENEWAL_NOT_RECOMMENDED, "Renewal requires a COMPLETE analysis not recommending DO_NOT_RENEW")

    successor = {field: contract[field] for field in COPY_TERM_FIELDS}
    successor["quality_measures"] = [dict(m, decile_thresholds_bp=list(m["decile_thresholds_bp"])) for m in contract["quality_measures"]]
    successor["contract_ref"] = contract["contract_ref"] + "-R"
    successor["renewed_from_contract_id"] = contract["id"]
    successor["contract_status"] = "DRAFT"
    db.stamp_new(successor)
    db.contracts[successor["id"]] = successor

    contract["contract_status"] = "RENEWED"
    db.touch(contract)
    return success_object(successor, 201)


# ---------------------------------------------------------------------------
# Nested: POST /vbc/contracts/{id}/renewal-analyses (OCC-guarded)
# ---------------------------------------------------------------------------

@bp.route("/vbc/contracts/<contract_id>/renewal-analyses", methods=["POST"])
@require_roles("ContractManager")
def create_renewal_analysis(contract_id: str, _user_id: str, _role: str):
    contract = db.contracts.get(contract_id)
    if contract is None:
        raise_err(ERR_NOT_FOUND, "Contract id does not exist")
    body = get_json_body()
    reject_unknown_fields(body, {"expected_contract_version"})
    expected_version = require_int(body, "expected_contract_version")

    # Priority 6 (state): contract must be EXPIRED.
    if contract["contract_status"] != "EXPIRED":
        raise_err(ERR_INVALID_STATE_TRANSITION, "Renewal analysis requires an EXPIRED contract")
    has_closed_year = any(
        y["contract_id"] == contract_id and y["year_status"] == "CLOSED"
        for y in db.performance_years.values()
    )
    if not has_closed_year:
        raise_err(ERR_YEARS_NOT_CLOSED, "Renewal analysis requires at least one CLOSED performance year")

    # Priority 14: OCC against the contract.
    if expected_version != contract["version"]:
        raise_err(ERR_STALE_VERSION, "expected_contract_version does not match the contract's current version")

    # Supersede any prior DRAFT analysis of the contract.
    for analysis in db.renewal_analyses.values():
        if analysis["contract_id"] == contract_id and analysis["analysis_status"] == "DRAFT":
            db.apply_updates(analysis, {"analysis_status": "SUPERSEDED"})

    seq = max(
        (a["analysis_seq"] for a in db.renewal_analyses.values() if a["contract_id"] == contract_id),
        default=0,
    ) + 1
    analysis = {
        "contract_id": contract_id,
        "analysis_seq": seq,
        "realized_savings_rate_bp": None,
        "quality_trend_points": None,
        "risk_growth_milli": None,
        "recommendation": None,
        "analysis_status": "DRAFT",
    }
    db.stamp_new(analysis)
    db.renewal_analyses[analysis["id"]] = analysis
    # Creating the analysis mutates the parent contract's version (§1.2.1).
    db.touch(contract)
    return success_object(analysis, 201)
