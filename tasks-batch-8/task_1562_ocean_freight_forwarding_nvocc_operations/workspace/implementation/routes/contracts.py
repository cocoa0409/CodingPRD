"""Carrier contract endpoints (PRD section 3.3).

Contract service windows are CLOSED [service_start, service_end]; adjacency IS
an intersection (unlike tariffs). Contracts age lazily ACTIVE -> EXPIRED when
the logical clock passes service_end.
"""

from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_CONTRACT_INVALID_STATE,
    ERR_CONTRACT_NOT_FOUND,
    ERR_CONTRACT_WINDOW_OVERLAP,
    ERR_INVALID_REQUEST,
)
from middleware import ALL_ROLES, require_roles
from response import success_list, success_object
from services import domain
from util import (
    apply_filters,
    get_json_body,
    optional_field,
    paginate,
    parse_pagination,
    pub,
    require_int,
    require_list,
    require_string,
    require_ts,
    sort_by_created_at,
)

bp = Blueprint("carrier_contracts", __name__)

CONTAINER_TYPES = {"20GP", "40GP", "40HC", "40RF"}


def _get_contract(contract_id: str) -> dict:
    contract = db.carrier_contracts.get(contract_id)
    if contract is None:
        raise_err(ERR_CONTRACT_NOT_FOUND, "CarrierContract id does not exist")
    return contract


def _validate_container_rates(rates: list) -> None:
    for entry in rates:
        if not isinstance(entry, dict):
            raise_err(ERR_INVALID_REQUEST, "container_rates entries must be objects")
        ct = entry.get("container_type")
        rc = entry.get("rate_cents")
        if ct not in CONTAINER_TYPES:
            raise_err(ERR_INVALID_REQUEST, "container_rates.container_type must be a valid container type")
        if isinstance(rc, bool) or not isinstance(rc, int) or rc < 0:
            raise_err(ERR_INVALID_REQUEST, "container_rates.rate_cents must be an integer >= 0")


def _validate_demurrage_tiers(tiers: list) -> None:
    """Tiers must tile contiguously from from_day=1; to_day null = unbounded
    (only allowed on the last tier)."""
    expected_from = 1
    for i, tier in enumerate(tiers):
        if not isinstance(tier, dict):
            raise_err(ERR_INVALID_REQUEST, "demurrage_tiers entries must be objects")
        from_day = tier.get("from_day")
        to_day = tier.get("to_day")
        per_diem = tier.get("per_diem_cents")
        if isinstance(from_day, bool) or not isinstance(from_day, int) or from_day != expected_from:
            raise_err(ERR_INVALID_REQUEST, "demurrage_tiers must tile contiguously from from_day=1")
        if to_day is None:
            if i != len(tiers) - 1:
                raise_err(ERR_INVALID_REQUEST, "Only the last demurrage tier may be unbounded")
        else:
            if isinstance(to_day, bool) or not isinstance(to_day, int) or to_day < from_day:
                raise_err(ERR_INVALID_REQUEST, "demurrage_tiers.to_day must be >= from_day")
            expected_from = to_day + 1
        if isinstance(per_diem, bool) or not isinstance(per_diem, int) or per_diem < 0:
            raise_err(ERR_INVALID_REQUEST, "demurrage_tiers.per_diem_cents must be an integer >= 0")


def _window_overlap_check(candidate: dict, statuses: set[str], exclude_id: str) -> None:
    """CLOSED-window overlap on same (carrier_name, service_lane): adjacency
    (a.service_end == b.service_start) IS an intersection."""
    c_start = db.parse_iso(candidate["service_start"])
    c_end = db.parse_iso(candidate["service_end"])
    for other in db.carrier_contracts.values():
        if other["id"] == exclude_id:
            continue
        if other["status"] not in statuses:
            continue
        if (
            other["carrier_name"] != candidate["carrier_name"]
            or other["service_lane"] != candidate["service_lane"]
        ):
            continue
        o_start = db.parse_iso(other["service_start"])
        o_end = db.parse_iso(other["service_end"])
        if c_start <= o_end and o_start <= c_end:
            raise_err(
                ERR_CONTRACT_WINDOW_OVERLAP,
                "Another contract on the same carrier+lane has an intersecting closed window",
            )


@bp.route("/freight/carrier-contracts", methods=["POST"])
@require_roles("OperationsManager")
def create_contract(_user_id: str, _role: str):
    body = get_json_body()
    contract_number = require_string(body, "contract_number")
    carrier_name = require_string(body, "carrier_name")
    service_lane = require_string(body, "service_lane")
    container_rates = require_list(body, "container_rates")
    _validate_container_rates(container_rates)
    demurrage_free_days = optional_field(body, "demurrage_free_days", 4)
    detention_free_days = optional_field(body, "detention_free_days", 3)
    for name, val in (("demurrage_free_days", demurrage_free_days), ("detention_free_days", detention_free_days)):
        if isinstance(val, bool) or not isinstance(val, int) or val < 0:
            raise_err(ERR_INVALID_REQUEST, f"{name} must be an integer >= 0")
    demurrage_tiers = require_list(body, "demurrage_tiers")
    _validate_demurrage_tiers(demurrage_tiers)
    detention_per_diem_cents = require_int(body, "detention_per_diem_cents", minimum=0)
    service_start = require_ts(body, "service_start")
    service_end = require_ts(body, "service_end")
    if not (service_start <= service_end):
        raise_err(ERR_INVALID_REQUEST, "service_start must not be later than service_end")

    contract = {
        "contract_number": contract_number,
        "carrier_name": carrier_name,
        "service_lane": service_lane,
        "container_rates": container_rates,
        "demurrage_free_days": demurrage_free_days,
        "detention_free_days": detention_free_days,
        "demurrage_tiers": demurrage_tiers,
        "detention_per_diem_cents": detention_per_diem_cents,
        "service_start": db.format_iso(service_start),
        "service_end": db.format_iso(service_end),
        "status": "NEGOTIATION",
    }
    db.stamp_new(contract)
    db.carrier_contracts[contract["id"]] = contract
    return success_object(pub(contract), 201)


@bp.route("/freight/carrier-contracts", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_contracts(_user_id: str, _role: str):
    domain.lazy_expire_all_contracts()
    limit, offset = parse_pagination()
    items = sort_by_created_at(list(db.carrier_contracts.values()))
    items = apply_filters(items, ["status", "carrier_name"])
    page, total = paginate(items, limit, offset)
    return success_list([domain.serialize_contract(c) for c in page], limit, offset, total)


@bp.route("/freight/carrier-contracts/<contract_id>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_contract(contract_id: str, _user_id: str, _role: str):
    return success_object(domain.serialize_contract(_get_contract(contract_id)))


@bp.route("/freight/carrier-contracts/<contract_id>/activate", methods=["POST"])
@require_roles("OperationsManager")
def activate_contract(contract_id: str, _user_id: str, _role: str):
    contract = _get_contract(contract_id)
    if contract["status"] != "NEGOTIATION":
        raise_err(ERR_CONTRACT_INVALID_STATE, "Contract must be NEGOTIATION to activate")
    if not (db.parse_iso(contract["service_start"]) <= db.parse_iso(contract["service_end"])):
        raise_err(ERR_INVALID_REQUEST, "service_start must not be later than service_end")
    _window_overlap_check(contract, {"ACTIVE", "SUSPENDED"}, contract["id"])
    contract["status"] = "ACTIVE"
    db.touch(contract)
    return success_object(pub(contract))


@bp.route("/freight/carrier-contracts/<contract_id>/suspend", methods=["POST"])
@require_roles("OperationsManager")
def suspend_contract(contract_id: str, _user_id: str, _role: str):
    contract = _get_contract(contract_id)
    domain.lazy_expire_contract(contract)
    if contract["status"] != "ACTIVE":
        raise_err(ERR_CONTRACT_INVALID_STATE, "Contract must be ACTIVE to suspend")
    contract["status"] = "SUSPENDED"
    db.touch(contract)
    return success_object(pub(contract))


@bp.route("/freight/carrier-contracts/<contract_id>/resume", methods=["POST"])
@require_roles("OperationsManager")
def resume_contract(contract_id: str, _user_id: str, _role: str):
    contract = _get_contract(contract_id)
    domain.lazy_expire_contract(contract)
    if contract["status"] != "SUSPENDED":
        raise_err(ERR_CONTRACT_INVALID_STATE, "Contract must be SUSPENDED to resume")
    # Overlap check re-run against ACTIVE contracts on resume.
    _window_overlap_check(contract, {"ACTIVE"}, contract["id"])
    contract["status"] = "ACTIVE"
    db.touch(contract)
    return success_object(pub(contract))
