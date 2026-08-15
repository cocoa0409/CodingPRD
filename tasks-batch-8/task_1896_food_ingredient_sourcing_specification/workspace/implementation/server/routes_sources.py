"""Approved sources, declarations, contracts, rebate (PRD §3.4, §3.5, §3.7)."""
from flask import Blueprint, g, request

from .envelope import (
    ALL_ROLES,
    ERR_ACTIVE_CONTRACT_EXISTS,
    ERR_CONTRACT_WINDOW_NOT_OPEN,
    ERR_CONTRACT_WINDOW_OVERLAP,
    ERR_CROSS_REFERENCE_MISMATCH,
    ERR_DECLARATION_MISSING,
    ERR_DUPLICATE,
    ERR_INVALID_STATE,
    ERR_SOURCE_NOT_ACTIVE,
    ERR_SPEC_NOT_EFFECTIVE,
    ERR_STALE_VERSION,
    ERR_SUPPLIER_NOT_QUALIFIED,
    ERR_TEMPORAL_GUARD_VIOLATION,
    body,
    err,
    invalid,
    is_number,
    list_page,
    not_found,
    pagination_params,
    require_int,
    require_roles,
    respond_object,
)
from .services import (
    DECLARATION_TYPES,
    compute_rebate,
    contracts_of_source,
    current_declaration,
    declaration_in_window,
    declarations_of_source,
    recompute_dual_source,
    sources_of_ingredient,
)
from .store import (
    STORE,
    new_record,
    parse_dt,
    ser_contract,
    ser_declaration,
    ser_source,
    set_dt,
    touch,
)

bp = Blueprint("sources", __name__)

READERS_NO_AUTHOR = (
    "ProcurementManager",
    "QualityManager",
    "SupplierQualityEngineer",
    "RegulatoryAffairs",
    "PlatformAdmin",
)


def get_source_or_404(source_id):
    src = STORE.sources.get(source_id)
    if src is None:
        not_found("approved source not found")
    return src


def get_source_under_ingredient_or_404(ingredient_id, source_id):
    src = STORE.sources.get(source_id)
    if src is None or src["ingredient_id"] != ingredient_id:
        not_found("approved source not found")
    return src


def get_ingredient_or_404(ingredient_id):
    ing = STORE.ingredients.get(ingredient_id)
    if ing is None:
        not_found("ingredient not found")
    return ing


def get_contract_or_404(source_id, contract_id):
    contract = STORE.contracts.get(contract_id)
    if contract is None or contract["approved_source_id"] != source_id:
        not_found("contract not found")
    return contract


def check_declarations_current(source_id):
    """ERR_DECLARATION_MISSING unless both required declarations are CURRENT + in-window."""
    allergen = current_declaration(source_id, "ALLERGEN")
    if allergen is None or not declaration_in_window(allergen):
        err(ERR_DECLARATION_MISSING, 422, "CURRENT ALLERGEN declaration missing or out of window")
    coo = current_declaration(source_id, "COUNTRY_OF_ORIGIN")
    if coo is None or not declaration_in_window(coo):
        err(
            ERR_DECLARATION_MISSING,
            422,
            "CURRENT COUNTRY_OF_ORIGIN declaration missing or out of window",
        )


# ---------------------------------------------------------------------------
# Approved sources
# ---------------------------------------------------------------------------

@bp.post("/sourcing/ingredients/<ingredient_id>/approved-sources")
@require_roles("ProcurementManager")
def create_source(ingredient_id):
    ing = get_ingredient_or_404(ingredient_id)
    data = body()

    # Body-FK existence (4) then cross-reference coherence (5).
    supplier_id = data.get("supplier_id")
    pinned_spec_id = data.get("pinned_spec_id")
    supplier = None
    spec = None
    if isinstance(supplier_id, str):
        supplier = STORE.suppliers.get(supplier_id)
        if supplier is None:
            not_found("supplier_id does not reference an existing supplier")
    if isinstance(pinned_spec_id, str):
        spec = STORE.specs.get(pinned_spec_id)
        if spec is None:
            not_found("pinned_spec_id does not reference an existing spec")
    if spec is not None and spec["ingredient_id"] != ing["id"]:
        err(ERR_CROSS_REFERENCE_MISMATCH, 422, "pinned_spec_id must belong to the path ingredient")

    # Uniqueness (12): (ingredient, supplier, pinned_spec) among non-REVOKED rows.
    if isinstance(supplier_id, str) and isinstance(pinned_spec_id, str):
        for other in sources_of_ingredient(ing["id"]):
            if (
                other["supplier_id"] == supplier_id
                and other["pinned_spec_id"] == pinned_spec_id
                and other["status"] != "REVOKED"
            ):
                err(ERR_DUPLICATE, 409, "approved source triple already exists")

    # Basic request shape (23).
    if not isinstance(supplier_id, str) or supplier_id == "":
        invalid("supplier_id is required")
    if not isinstance(pinned_spec_id, str) or pinned_spec_id == "":
        invalid("pinned_spec_id is required")

    # OCC (24): expected_ingredient_version.
    expected = data.get("expected_ingredient_version")
    if expected is None:
        invalid("expected_ingredient_version is required")
    if isinstance(expected, bool) or not isinstance(expected, int):
        invalid("expected_ingredient_version must be an integer")
    if expected != ing["version"]:
        err(ERR_STALE_VERSION, 412, "ingredient version has advanced")

    rec = new_record()
    rec.update(
        {
            "ingredient_id": ing["id"],
            "supplier_id": supplier_id,
            "pinned_spec_id": pinned_spec_id,
            "approved_by_user_id": None,
            "status": "PROVISIONAL",
            "suspension_reason": "NONE",
        }
    )
    STORE.sources[rec["id"]] = rec
    touch(ing)  # creating an approved source increments Ingredient.version by 1
    return respond_object(ser_source(rec), 201)


@bp.get("/sourcing/ingredients/<ingredient_id>/approved-sources")
@require_roles(*ALL_ROLES)
def list_sources_of_ingredient(ingredient_id):
    get_ingredient_or_404(ingredient_id)
    limit, offset = pagination_params()
    status = request.args.get("status")
    supplier_id = request.args.get("supplier_id")
    rows = sources_of_ingredient(ingredient_id)
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if supplier_id is not None:
        rows = [r for r in rows if r["supplier_id"] == supplier_id]
    return list_page(rows, ser_source, limit, offset)


@bp.get("/sourcing/approved-sources/<source_id>")
@require_roles(*ALL_ROLES)
def get_source(source_id):
    return respond_object(ser_source(get_source_or_404(source_id)))


def _check_supplier_qualified(src):
    supplier = STORE.suppliers.get(src["supplier_id"])
    if supplier is None or supplier["status"] != "QUALIFIED":
        err(ERR_SUPPLIER_NOT_QUALIFIED, 409, "supplier is not QUALIFIED")


def _check_spec_effective(src):
    spec = STORE.specs.get(src["pinned_spec_id"])
    if spec is None or spec["status"] != "EFFECTIVE":
        err(ERR_SPEC_NOT_EFFECTIVE, 409, "pinned spec is not EFFECTIVE")


@bp.post("/sourcing/ingredients/<ingredient_id>/approved-sources/<source_id>/activate")
@require_roles("ProcurementManager")
def activate_source(ingredient_id, source_id):
    ing = get_ingredient_or_404(ingredient_id)
    src = get_source_under_ingredient_or_404(ingredient_id, source_id)
    if src["status"] != "PROVISIONAL":
        err(ERR_INVALID_STATE, 409, "approved source is not PROVISIONAL")
    _check_supplier_qualified(src)
    _check_spec_effective(src)
    check_declarations_current(src["id"])
    src["status"] = "ACTIVE"
    src["approved_by_user_id"] = g.user_id
    touch(src)
    recompute_dual_source(ing)
    return respond_object(ser_source(src))


@bp.post("/sourcing/ingredients/<ingredient_id>/approved-sources/<source_id>/suspend")
@require_roles("ProcurementManager")
def suspend_source(ingredient_id, source_id):
    ing = get_ingredient_or_404(ingredient_id)
    src = get_source_under_ingredient_or_404(ingredient_id, source_id)
    if src["status"] != "ACTIVE":
        err(ERR_INVALID_STATE, 409, "approved source is not ACTIVE")
    src["status"] = "SUSPENDED"
    src["suspension_reason"] = "MANUAL"
    touch(src)
    recompute_dual_source(ing)
    return respond_object(ser_source(src))


@bp.post("/sourcing/ingredients/<ingredient_id>/approved-sources/<source_id>/reinstate")
@require_roles("ProcurementManager")
def reinstate_source(ingredient_id, source_id):
    ing = get_ingredient_or_404(ingredient_id)
    src = get_source_under_ingredient_or_404(ingredient_id, source_id)
    if src["status"] != "SUSPENDED":
        err(ERR_INVALID_STATE, 409, "approved source is not SUSPENDED")
    _check_supplier_qualified(src)
    _check_spec_effective(src)
    check_declarations_current(src["id"])
    src["status"] = "ACTIVE"
    src["suspension_reason"] = "NONE"
    touch(src)
    recompute_dual_source(ing)
    return respond_object(ser_source(src))


@bp.post("/sourcing/ingredients/<ingredient_id>/approved-sources/<source_id>/revoke")
@require_roles("ProcurementManager")
def revoke_source(ingredient_id, source_id):
    ing = get_ingredient_or_404(ingredient_id)
    src = get_source_under_ingredient_or_404(ingredient_id, source_id)
    if src["status"] not in ("PROVISIONAL", "ACTIVE", "SUSPENDED"):
        err(ERR_INVALID_STATE, 409, "approved source cannot be revoked from its status")
    active_contracts = [
        c for c in contracts_of_source(src["id"]) if c["status"] == "ACTIVE"
    ]
    if active_contracts:
        err(ERR_ACTIVE_CONTRACT_EXISTS, 409, "source has an ACTIVE contract")
    src["status"] = "REVOKED"
    touch(src)
    for decl in declarations_of_source(src["id"]):
        if decl["status"] == "CURRENT":
            decl["status"] = "SUPERSEDED"
            touch(decl)
    recompute_dual_source(ing)
    return respond_object(ser_source(src))


# ---------------------------------------------------------------------------
# Declarations
# ---------------------------------------------------------------------------

@bp.post("/sourcing/approved-sources/<source_id>/declarations")
@require_roles("RegulatoryAffairs")
def create_declaration(source_id):
    src = get_source_or_404(source_id)
    data = body()

    # Temporal guard (8): valid_until strictly after valid_from.
    from_raw = data.get("valid_from")
    until_raw = data.get("valid_until")
    if isinstance(from_raw, str) and isinstance(until_raw, str):
        try:
            from_dt = parse_dt(from_raw)
            until_dt = parse_dt(until_raw)
        except ValueError:
            invalid("valid_from and valid_until must be valid ISO8601 timestamps")
        else:
            if until_dt <= from_dt:
                err(
                    ERR_TEMPORAL_GUARD_VIOLATION,
                    422,
                    "valid_until must be strictly after valid_from",
                )

    declaration_type = data.get("declaration_type")
    if declaration_type not in DECLARATION_TYPES:
        invalid("declaration_type must be ALLERGEN or COUNTRY_OF_ORIGIN")
    payload = data.get("payload")
    if not isinstance(payload, dict):
        invalid("payload is required and must be an object")
    if declaration_type == "ALLERGEN":
        if not isinstance(payload.get("allergen_tags"), list):
            invalid("payload.allergen_tags must be an array")
    else:
        if not isinstance(payload.get("country_codes"), list):
            invalid("payload.country_codes must be an array")
        if not isinstance(payload.get("primary_country"), str):
            invalid("payload.primary_country is required")
    if not isinstance(from_raw, str):
        invalid("valid_from is required and must be an ISO8601 string")
    if not isinstance(until_raw, str):
        invalid("valid_until is required and must be an ISO8601 string")

    # Supersede the prior CURRENT declaration of the same type.
    for decl in declarations_of_source(src["id"]):
        if decl["declaration_type"] == declaration_type and decl["status"] == "CURRENT":
            decl["status"] = "SUPERSEDED"
            touch(decl)

    rec = new_record()
    rec.update(
        {
            "approved_source_id": src["id"],
            "declaration_type": declaration_type,
            "payload": payload,
            "collected_by_user_id": g.user_id,
            "status": "CURRENT",
        }
    )
    set_dt(rec, "valid_from", from_raw)
    set_dt(rec, "valid_until", until_raw)
    STORE.declarations[rec["id"]] = rec
    return respond_object(ser_declaration(rec), 201)


@bp.get("/sourcing/approved-sources/<source_id>/declarations")
@require_roles(*READERS_NO_AUTHOR)
def list_declarations(source_id):
    get_source_or_404(source_id)
    limit, offset = pagination_params()
    dtype = request.args.get("declaration_type")
    status = request.args.get("status")
    rows = declarations_of_source(source_id)
    if dtype is not None:
        rows = [r for r in rows if r["declaration_type"] == dtype]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return list_page(rows, ser_declaration, limit, offset)


# ---------------------------------------------------------------------------
# Contracts
# ---------------------------------------------------------------------------

@bp.post("/sourcing/approved-sources/<source_id>/contracts")
@require_roles("ProcurementManager")
def create_contract(source_id):
    src = get_source_or_404(source_id)
    data = body()

    # Basic request shape (23).
    volume = data.get("annual_committed_volume_kg")
    if isinstance(volume, bool) or not isinstance(volume, (int, float)):
        invalid("annual_committed_volume_kg is required and must be a positive integer")
    if isinstance(volume, float) and not volume.is_integer():
        invalid("annual_committed_volume_kg must be an integer")
    if volume <= 0:
        invalid("annual_committed_volume_kg must be > 0")
    index_base = data.get("index_base_value")
    if not is_number(index_base) or index_base <= 0:
        invalid("index_base_value is required and must be > 0")
    pct = data.get("index_pass_through_pct")
    if not is_number(pct) or not (0 < pct <= 1):
        invalid("index_pass_through_pct must be > 0 and <= 1")
    start_raw = data.get("window_start")
    end_raw = data.get("window_end")
    if not isinstance(start_raw, str) or not isinstance(end_raw, str):
        invalid("window_start and window_end are required ISO8601 strings")
    try:
        start_dt = parse_dt(start_raw)
    except ValueError:
        invalid("window_start must be a valid ISO8601 timestamp")
    try:
        end_dt = parse_dt(end_raw)
    except ValueError:
        invalid("window_end must be a valid ISO8601 timestamp")
    if end_dt <= start_dt:
        invalid("window_end must be strictly after window_start")

    # OCC (24): expected_approved_source_version.
    expected = data.get("expected_approved_source_version")
    if expected is None:
        invalid("expected_approved_source_version is required")
    if isinstance(expected, bool) or not isinstance(expected, int):
        invalid("expected_approved_source_version must be an integer")
    if expected != src["version"]:
        err(ERR_STALE_VERSION, 412, "approved source version has advanced")

    rec = new_record()
    rec.update(
        {
            "approved_source_id": src["id"],
            "annual_committed_volume_kg": volume,
            "index_base_value": index_base,
            "index_pass_through_pct": pct,
            "status": "PENDING",
            "cumulative_shipped_kg": 0,
        }
    )
    set_dt(rec, "window_start", start_raw)
    set_dt(rec, "window_end", end_raw)
    STORE.contracts[rec["id"]] = rec
    touch(src)  # creating a contract increments ApprovedSource.version by 1
    return respond_object(ser_contract(rec), 201)


@bp.get("/sourcing/approved-sources/<source_id>/contracts")
@require_roles(*READERS_NO_AUTHOR)
def list_contracts(source_id):
    get_source_or_404(source_id)
    limit, offset = pagination_params()
    status = request.args.get("status")
    rows = contracts_of_source(source_id)
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return list_page(rows, ser_contract, limit, offset)


@bp.post("/sourcing/approved-sources/<source_id>/contracts/<contract_id>/activate")
@require_roles("ProcurementManager")
def activate_contract(source_id, contract_id):
    src = get_source_or_404(source_id)
    contract = get_contract_or_404(source_id, contract_id)
    if contract["status"] != "PENDING":
        err(ERR_INVALID_STATE, 409, "contract is not PENDING")
    if src["status"] != "ACTIVE":
        err(ERR_SOURCE_NOT_ACTIVE, 409, "approved source is not ACTIVE")
    clock = STORE.clock
    if not (contract["window_start__dt"] <= clock < contract["window_end__dt"]):
        err(ERR_CONTRACT_WINDOW_NOT_OPEN, 422, "logical clock is outside the contract window")
    for other in contracts_of_source(source_id):
        if other["id"] == contract["id"] or other["status"] != "ACTIVE":
            continue
        # Half-open [start, end) intervals: touching endpoints do not overlap.
        if (
            contract["window_start__dt"] < other["window_end__dt"]
            and other["window_start__dt"] < contract["window_end__dt"]
        ):
            err(ERR_CONTRACT_WINDOW_OVERLAP, 409, "overlapping ACTIVE contract exists")
    contract["status"] = "ACTIVE"
    touch(contract)
    return respond_object(ser_contract(contract))


@bp.post("/sourcing/approved-sources/<source_id>/contracts/<contract_id>/terminate")
@require_roles("ProcurementManager")
def terminate_contract(source_id, contract_id):
    get_source_or_404(source_id)
    contract = get_contract_or_404(source_id, contract_id)
    if contract["status"] not in ("PENDING", "ACTIVE"):
        err(ERR_INVALID_STATE, 409, "contract is not PENDING or ACTIVE")
    contract["status"] = "TERMINATED"
    touch(contract)
    return respond_object(ser_contract(contract))


@bp.get("/sourcing/approved-sources/<source_id>/contracts/<contract_id>/rebate")
@require_roles("ProcurementManager", "QualityManager", "PlatformAdmin")
def contract_rebate(source_id, contract_id):
    get_source_or_404(source_id)
    contract = get_contract_or_404(source_id, contract_id)
    return respond_object(compute_rebate(contract))
