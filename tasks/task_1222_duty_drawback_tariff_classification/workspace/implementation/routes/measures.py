"""Tariff measure endpoints: publish, list, revoke (PRD §3.3, §2.9)."""
from flask import Blueprint, request

from calc import (
    active_lines_on_entry,
    active_measures_for_entry,
    compute_non_drawbackable,
    measure_matches_entry,
    measure_window_overlaps,
    mint_entity,
    recompute_entry,
    touch,
)
from db import STORE
from errors import (
    ERR_ALREADY_TERMINAL,
    ERR_INVALID_WINDOW,
    ERR_MEASURE_BLOCKED_BY_CLAIM_LINES,
    ERR_MEASURE_WINDOW_OVERLAP,
    ERR_NOT_FOUND,
    raise_err,
)
from middleware import (
    authenticate,
    get_body,
    opt_dt,
    req_dt,
    req_enum,
    req_int,
    req_str,
    require_role,
)
from response import paginate, success_object
from serializers import serialize, sorted_by_creation

bp = Blueprint("measures", __name__)

ALL_ROLES = {"FirmAdmin", "Analyst", "LicensedBroker", "ComplianceManager", "ClientContact"}
MEASURE_TYPES = {"EXCLUSION", "SECTION_301", "AD_CVD", "SAFEGUARD"}


def get_measure_or_404(measure_id):
    measure = STORE["tariff_measures"].get(measure_id)
    if measure is None:
        raise_err(ERR_NOT_FOUND, f"Tariff measure {measure_id} not found")
    return measure


def _matching_entries(measure):
    return [e for e in STORE["import_entries"].values() if measure_matches_entry(measure, e)]


@bp.route("/customs/tariff-measures", methods=["POST"])
def create_measure():
    _, role = authenticate()
    require_role(role, {"FirmAdmin"})
    body = get_body()
    hts_code_prefix = req_str(body, "hts_code_prefix")
    measure_type = req_enum(body, "measure_type", MEASURE_TYPES)
    surcharge_bps = req_int(body, "surcharge_bps", minimum=0)
    effective_from = req_dt(body, "effective_from")
    effective_to = opt_dt(body, "effective_to")

    if effective_to is not None and effective_to <= effective_from:
        raise_err(ERR_INVALID_WINDOW, "effective_to must be strictly after effective_from")
    if measure_window_overlaps(measure_type, hts_code_prefix, effective_from, effective_to):
        raise_err(
            ERR_MEASURE_WINDOW_OVERLAP,
            "Window overlaps another ACTIVE measure with the same type and prefix",
        )

    candidate = {
        "hts_code_prefix": hts_code_prefix,
        "measure_type": measure_type,
        "surcharge_bps": surcharge_bps,
        "effective_from": effective_from,
        "effective_to": effective_to,
    }

    # Frozen-ledger protection: the new measure may not reduce eligible duty of
    # any entry referenced by ACTIVE claim lines.
    for entry in _matching_entries(candidate):
        if not active_lines_on_entry(entry["id"]):
            continue
        current_nd = compute_non_drawbackable(entry, active_measures_for_entry(entry))
        new_nd = compute_non_drawbackable(entry, active_measures_for_entry(entry, extra=candidate))
        current_eligible = max(0, entry["duty_paid_cents"] - current_nd)
        new_eligible = max(0, entry["duty_paid_cents"] - new_nd)
        if new_eligible < current_eligible:
            raise_err(
                ERR_MEASURE_BLOCKED_BY_CLAIM_LINES,
                "Measure would reduce eligible duty of an entry with ACTIVE claim lines",
            )

    measure = mint_entity()
    measure.update(candidate)
    measure["status"] = "ACTIVE"
    STORE["tariff_measures"][measure["id"]] = measure

    for entry in sorted_by_creation(_matching_entries(measure)):
        recompute_entry(entry)
        touch(entry)

    return success_object(serialize(measure), 201)


@bp.route("/customs/tariff-measures/<measure_id>", methods=["GET"])
def get_measure(measure_id):
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    measure = get_measure_or_404(measure_id)
    return success_object(serialize(measure))


@bp.route("/customs/tariff-measures", methods=["GET"])
def list_measures():
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    items = sorted_by_creation(STORE["tariff_measures"].values())
    prefix = request.args.get("hts_code_prefix")
    if prefix is not None:
        items = [m for m in items if m["hts_code_prefix"] == prefix]
    measure_type = request.args.get("measure_type")
    if measure_type is not None:
        items = [m for m in items if m["measure_type"] == measure_type]
    status = request.args.get("status")
    if status is not None:
        items = [m for m in items if m["status"] == status]
    return paginate([serialize(m) for m in items])


@bp.route("/customs/tariff-measures/<measure_id>/revoke", methods=["POST"])
def revoke_measure(measure_id):
    _, role = authenticate()
    require_role(role, {"FirmAdmin"})
    measure = get_measure_or_404(measure_id)
    get_body()
    if measure["status"] != "ACTIVE":
        raise_err(ERR_ALREADY_TERMINAL, f"Measure is {measure['status']} (terminal)")

    touched_entries = _matching_entries(measure)
    measure["status"] = "REVOKED"
    touch(measure)
    for entry in sorted_by_creation(touched_entries):
        recompute_entry(entry)
        touch(entry)
    return success_object(serialize(measure))
