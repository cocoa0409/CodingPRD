"""Logical clock, price-index observations, flat read aliases."""
from flask import Blueprint, request

from .envelope import (
    ALL_ROLES,
    ERR_DUPLICATE,
    body,
    err,
    invalid,
    is_number,
    list_page,
    not_found,
    pagination_params,
    require_roles,
    require_str,
    respond_object,
)
from .services import params_of_spec, run_clock_sweeps
from .store import (
    STORE,
    new_record,
    parse_dt,
    ser_audit,
    ser_capa,
    ser_coa,
    ser_contract,
    ser_finding,
    ser_observation,
    ser_parameter,
    ser_source,
    ser_spec,
    set_dt,
)

bp = Blueprint("misc", __name__)

READERS_NO_AUTHOR = (
    "ProcurementManager",
    "QualityManager",
    "SupplierQualityEngineer",
    "RegulatoryAffairs",
    "PlatformAdmin",
)


# ---------------------------------------------------------------------------
# Logical clock (PRD §2.6)
# ---------------------------------------------------------------------------

@bp.post("/sourcing/_clock/set_current_utc")
@require_roles("PlatformAdmin")
def set_clock():
    data = body()
    raw = data.get("to_iso8601")
    if not isinstance(raw, str) or raw == "":
        invalid("to_iso8601 is required and must be an ISO8601 string")
    try:
        parsed = parse_dt(raw)
    except ValueError:
        invalid("to_iso8601 must be a valid ISO8601 timestamp")
    STORE.clock = parsed
    STORE.clock_raw = raw
    run_clock_sweeps()
    return respond_object({"current_utc": STORE.clock_raw})


# ---------------------------------------------------------------------------
# Price index observations
# ---------------------------------------------------------------------------

@bp.post("/sourcing/price-index-observations")
@require_roles("PlatformAdmin")
def create_observation():
    data = body()
    index_name = data.get("index_name")
    observed_raw = data.get("observed_at")
    # Uniqueness (12): (index_name, observed_at).
    if isinstance(index_name, str) and isinstance(observed_raw, str):
        try:
            observed_dt = parse_dt(observed_raw)
        except ValueError:
            observed_dt = None
        if observed_dt is not None:
            for other in STORE.observations.values():
                if (
                    other["index_name"] == index_name
                    and other["observed_at__dt"] == observed_dt
                ):
                    err(ERR_DUPLICATE, 409, "index observation already exists")
    index_name = require_str(data, "index_name")
    if not isinstance(observed_raw, str):
        invalid("observed_at is required and must be an ISO8601 string")
    try:
        parse_dt(observed_raw)
    except ValueError:
        invalid("observed_at must be a valid ISO8601 timestamp")
    value = data.get("index_value")
    if not is_number(value) or value <= 0:
        invalid("index_value is required and must be > 0")

    rec = new_record(common=False)
    rec.update({"index_name": index_name, "index_value": value})
    set_dt(rec, "observed_at", observed_raw)
    STORE.observations[rec["id"]] = rec
    return respond_object(ser_observation(rec), 201)


@bp.get("/sourcing/price-index-observations")
@require_roles(*ALL_ROLES)
def list_observations():
    limit, offset = pagination_params()
    index_name = request.args.get("index_name")
    rows = list(STORE.observations.values())
    if index_name is not None:
        rows = [r for r in rows if r["index_name"] == index_name]
    return list_page(rows, ser_observation, limit, offset)


# ---------------------------------------------------------------------------
# Flat read aliases
# ---------------------------------------------------------------------------

@bp.get("/sourcing/specs")
@require_roles(*ALL_ROLES)
def list_specs_flat():
    limit, offset = pagination_params()
    ingredient_id = request.args.get("ingredient_id")
    supersedes_id = request.args.get("supersedes_spec_id")
    status = request.args.get("status")
    rows = list(STORE.specs.values())
    if ingredient_id is not None:
        rows = [r for r in rows if r["ingredient_id"] == ingredient_id]
    if supersedes_id is not None:
        rows = [r for r in rows if r["supersedes_spec_id"] == supersedes_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return list_page(rows, ser_spec, limit, offset)


@bp.get("/sourcing/specs/<spec_id>")
@require_roles(*ALL_ROLES)
def get_spec_flat(spec_id):
    spec = STORE.specs.get(spec_id)
    if spec is None:
        not_found("spec not found")
    return respond_object(ser_spec(spec))


@bp.get("/sourcing/specs/<spec_id>/parameters")
@require_roles(*ALL_ROLES)
def list_parameters_flat(spec_id):
    spec = STORE.specs.get(spec_id)
    if spec is None:
        not_found("spec not found")
    limit, offset = pagination_params()
    return list_page(params_of_spec(spec["id"]), ser_parameter, limit, offset)


@bp.get("/sourcing/specs/<spec_id>/approved-sources")
@require_roles(*ALL_ROLES)
def list_sources_by_spec(spec_id):
    spec = STORE.specs.get(spec_id)
    if spec is None:
        not_found("spec not found")
    limit, offset = pagination_params()
    status = request.args.get("status")
    rows = [s for s in STORE.sources.values() if s["pinned_spec_id"] == spec["id"]]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return list_page(rows, ser_source, limit, offset)


@bp.get("/sourcing/suppliers/<supplier_id>/approved-sources")
@require_roles(*ALL_ROLES)
def list_sources_by_supplier(supplier_id):
    if STORE.suppliers.get(supplier_id) is None:
        not_found("supplier not found")
    limit, offset = pagination_params()
    status = request.args.get("status")
    rows = [s for s in STORE.sources.values() if s["supplier_id"] == supplier_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return list_page(rows, ser_source, limit, offset)


@bp.get("/sourcing/contracts/<contract_id>")
@require_roles(*READERS_NO_AUTHOR)
def get_contract_flat(contract_id):
    contract = STORE.contracts.get(contract_id)
    if contract is None:
        not_found("contract not found")
    return respond_object(ser_contract(contract))


@bp.get("/sourcing/contracts/<contract_id>/coas")
@require_roles(*READERS_NO_AUTHOR)
def list_coas_by_contract(contract_id):
    if STORE.contracts.get(contract_id) is None:
        not_found("contract not found")
    limit, offset = pagination_params()
    status = request.args.get("status")
    rows = [c for c in STORE.coas.values() if c["contract_id"] == contract_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return list_page(rows, ser_coa, limit, offset)


@bp.get("/sourcing/coas/<coa_id>")
@require_roles(*READERS_NO_AUTHOR)
def get_coa_flat(coa_id):
    coa = STORE.coas.get(coa_id)
    if coa is None:
        not_found("CoA not found")
    return respond_object(ser_coa(coa))


@bp.get("/sourcing/coas/<coa_id>/findings")
@require_roles(*READERS_NO_AUTHOR)
def list_findings_flat(coa_id):
    coa = STORE.coas.get(coa_id)
    if coa is None:
        not_found("CoA not found")
    from .services import findings_of_coa

    limit, offset = pagination_params()
    disposition = request.args.get("disposition")
    rows = findings_of_coa(coa["id"])
    if disposition is not None:
        rows = [r for r in rows if r["disposition"] == disposition]
    return list_page(rows, ser_finding, limit, offset)


@bp.get("/sourcing/audits/<audit_id>")
@require_roles(*READERS_NO_AUTHOR)
def get_audit_flat(audit_id):
    audit = STORE.audits.get(audit_id)
    if audit is None:
        not_found("audit not found")
    return respond_object(ser_audit(audit))


@bp.get("/sourcing/audits/<audit_id>/corrective-actions")
@require_roles(*READERS_NO_AUTHOR)
def list_capas_flat(audit_id):
    if STORE.audits.get(audit_id) is None:
        not_found("audit not found")
    limit, offset = pagination_params()
    status = request.args.get("status")
    rows = [c for c in STORE.capas.values() if c["audit_id"] == audit_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return list_page(rows, ser_capa, limit, offset)
