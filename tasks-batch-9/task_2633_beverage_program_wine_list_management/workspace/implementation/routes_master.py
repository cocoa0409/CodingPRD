"""Venues, cellar bins, distributors and the wine catalogue."""
from flask import Blueprint

from core import (
    ALL_ROLES,
    API_PREFIX,
    D,
    WINE_CATEGORIES,
    authorize,
    bool_param,
    fail,
    get_body,
    get_bin,
    get_distributor,
    get_venue,
    get_wine,
    check_venue_scope,
    new_record,
    now,
    paginate,
    respond_list,
    respond_object,
    serialize,
    sort_default,
    store,
    touch,
    validate_body,
    q,
)
from cascade import apply_stale_recount

bp = Blueprint("master", __name__)

READ_ROLES = ALL_ROLES
CELLAR_READ_ROLES = ["BeverageDirector", "VenueSommelier", "Controller", "ComplianceOfficer"]

VENUE_SPEC = [
    {"name": "name", "type": "string", "required": True, "min_len": 1, "max_len": 120},
    {"name": "venue_code", "type": "string", "required": True, "min_len": 1, "max_len": 12},
    {"name": "cogs_target_pct_by_category", "type": "object", "required": True},
    {"name": "costing_method", "type": "string", "enum": ["FIFO", "WEIGHTED_AVERAGE"]},
    {"name": "event_cogs_target_pct", "type": "number", "min": "5.0", "max": "60.0"},
    {"name": "corkage_fee_cents", "type": "int", "min": 0},
    {"name": "corkage_waiver_purchase_ratio", "type": "int", "min": 1},
    {"name": "byo_bottle_limit_per_party", "type": "int", "min": 0},
    {"name": "byo_prohibited_categories", "type": "array"},
    {"name": "priority_rank", "type": "int", "min": 1, "max": 5},
]


@bp.post(API_PREFIX + "/venues")
def create_venue():
    authorize("BeverageDirector")
    body = get_body()
    validate_body(body, VENUE_SPEC)

    categories = body.get("byo_prohibited_categories") or []
    for value in categories:
        if value not in WINE_CATEGORIES:
            fail("ERR_INVALID_ENUM_VALUE", "byo_prohibited_categories carries an unknown category.")

    targets = body["cogs_target_pct_by_category"]
    if set(targets.keys()) != set(WINE_CATEGORIES):
        fail(
            "ERR_VALUE_OUT_OF_RANGE",
            "cogs_target_pct_by_category must carry exactly the six wine categories.",
        )
    for key, value in targets.items():
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            fail("ERR_INVALID_REQUEST", "cogs_target_pct_by_category values must be numbers.")
        if D(value) < D("5.0") or D(value) > D("60.0"):
            fail("ERR_VALUE_OUT_OF_RANGE", "A cost-of-goods target is outside 5.0 through 60.0.")

    if any(v["venue_code"] == body["venue_code"] for v in store.venues.values()):
        fail("ERR_VENUE_CODE_TAKEN", "That venue_code is already registered.")

    rec = new_record(
        {
            "name": body["name"],
            "venue_code": body["venue_code"],
            "costing_method": body.get("costing_method") or "FIFO",
            "cogs_target_pct_by_category": dict(targets),
            "event_cogs_target_pct": body.get("event_cogs_target_pct", 30.0),
            "corkage_fee_cents": body.get("corkage_fee_cents", 3500),
            "corkage_waiver_purchase_ratio": body.get("corkage_waiver_purchase_ratio", 2),
            "byo_bottle_limit_per_party": body.get("byo_bottle_limit_per_party", 2),
            "byo_prohibited_categories": list(categories),
            "priority_rank": body.get("priority_rank", 3),
            "last_variance_pct": D("0.00"),
            "last_pour_cost_run_at": None,
            "program_posture": "OPEN",
            "cogs_ledger_cents": 0,
            "revenue_ledger_cents": 0,
        }
    )
    store.venues[rec["id"]] = rec
    return respond_object(serialize(rec), 201)


@bp.get(API_PREFIX + "/venues/<venue_id>")
def read_venue(venue_id):
    authorize(READ_ROLES)
    return respond_object(serialize(get_venue(venue_id)))


@bp.get(API_PREFIX + "/venues")
def list_venues():
    authorize(READ_ROLES)
    rows = list(store.venues.values())
    posture = q("program_posture")
    method = q("costing_method")
    if posture is not None:
        rows = [r for r in rows if r["program_posture"] == posture]
    if method is not None:
        rows = [r for r in rows if r["costing_method"] == method]
    page, meta = paginate(sort_default(rows))
    return respond_list([serialize(r) for r in page], meta)


BIN_SPEC = [
    {"name": "bin_code", "type": "string", "required": True, "min_len": 1, "max_len": 12},
    {
        "name": "zone",
        "type": "string",
        "required": True,
        "enum": ["CELLAR", "BACKBAR", "RESERVE", "OFFSITE"],
    },
    {"name": "capacity_bottles", "type": "int", "required": True, "min": 1},
    {"name": "temperature_controlled", "type": "bool"},
]


@bp.post(API_PREFIX + "/venues/<venue_id>/cellar-bins")
def create_bin(venue_id):
    user_id, role = authorize("VenueSommelier", "BeverageDirector")
    check_venue_scope(role, user_id, venue_id)
    get_venue(venue_id)
    body = get_body()
    validate_body(body, BIN_SPEC)
    if any(
        b["venue_id"] == venue_id and b["bin_code"] == body["bin_code"]
        for b in store.cellar_bins.values()
    ):
        fail("ERR_BIN_CODE_TAKEN", "That bin_code already exists in this venue.")
    rec = new_record(
        {
            "venue_id": venue_id,
            "bin_code": body["bin_code"],
            "zone": body["zone"],
            "capacity_bottles": body["capacity_bottles"],
            "temperature_controlled": body.get("temperature_controlled", True),
            "bottles_stored": 0,
            "utilization_pct": D("0.00"),
            "bin_state": "ACTIVE",
        }
    )
    store.cellar_bins[rec["id"]] = rec
    return respond_object(serialize(rec), 201)


@bp.get(API_PREFIX + "/cellar-bins/<bin_id>")
def read_bin(bin_id):
    authorize(CELLAR_READ_ROLES)
    return respond_object(serialize(get_bin(bin_id)))


@bp.get(API_PREFIX + "/cellar-bins")
def list_bins():
    authorize(CELLAR_READ_ROLES)
    rows = list(store.cellar_bins.values())
    for field in ("venue_id", "zone", "bin_state"):
        value = q(field)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    page, meta = paginate(sort_default(rows))
    return respond_list([serialize(r) for r in page], meta)


DISTRIBUTOR_SPEC = [
    {"name": "name", "type": "string", "required": True, "min_len": 1, "max_len": 120},
    {"name": "license_number", "type": "string", "required": True, "min_len": 1, "max_len": 32},
    {"name": "allocation_tier", "type": "string", "enum": ["A", "B", "C"]},
    {"name": "on_time_delivery_pct", "type": "number", "min": "0.0", "max": "100.0"},
]


@bp.post(API_PREFIX + "/distributors")
def create_distributor():
    authorize("BeverageDirector")
    body = get_body()
    validate_body(body, DISTRIBUTOR_SPEC)
    rec = new_record(
        {
            "name": body["name"],
            "license_number": body["license_number"],
            "allocation_tier": body.get("allocation_tier") or "B",
            "on_time_delivery_pct": body.get("on_time_delivery_pct", 95.0),
            "compliance_state": "PENDING_REVIEW",
            "last_review_note": None,
        }
    )
    store.distributors[rec["id"]] = rec
    return respond_object(serialize(rec), 201)


@bp.get(API_PREFIX + "/distributors/<distributor_id>")
def read_distributor(distributor_id):
    authorize(READ_ROLES)
    return respond_object(serialize(get_distributor(distributor_id)))


@bp.get(API_PREFIX + "/distributors")
def list_distributors():
    authorize(READ_ROLES)
    rows = list(store.distributors.values())
    for field in ("allocation_tier", "compliance_state"):
        value = q(field)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    page, meta = paginate(sort_default(rows))
    return respond_list([serialize(r) for r in page], meta)


REVIEW_SPEC = [
    {"name": "decision", "type": "string", "required": True, "enum": ["CLEARED", "HOLD"]},
    {"name": "note", "type": "string"},
]


@bp.post(API_PREFIX + "/distributors/<distributor_id>/compliance-reviews")
def review_distributor(distributor_id):
    authorize("ComplianceOfficer")
    distributor = get_distributor(distributor_id)
    body = get_body()
    validate_body(body, REVIEW_SPEC)

    decision = body["decision"]
    distributor["compliance_state"] = decision
    distributor["last_review_note"] = body.get("note")
    touch(distributor)

    # The compliance dimension of every offer of this distributor follows the licence,
    # and no offer's fulfillment_state moves.
    for offer in store.allocation_offers.values():
        if offer["distributor_id"] != distributor_id:
            continue
        if decision == "HOLD":
            if offer["compliance_state"] in ("PENDING_LICENSE_CHECK", "CLEARED"):
                offer["compliance_state"] = "BLOCKED"
                touch(offer)
        else:
            if offer["compliance_state"] in ("BLOCKED", "PENDING_LICENSE_CHECK"):
                offer["compliance_state"] = "CLEARED"
                touch(offer)
    return respond_object(serialize(distributor))


WINE_SPEC = [
    {"name": "producer", "type": "string", "required": True, "min_len": 1, "max_len": 120},
    {"name": "cuvee", "type": "string", "required": True, "min_len": 1, "max_len": 120},
    {"name": "vintage_year", "type": "int", "required": True, "min": 1900, "max": 2100},
    {"name": "category", "type": "string", "required": True, "enum": WINE_CATEGORIES},
    {"name": "reference_cost_cents", "type": "int", "required": True, "min": 1},
    {"name": "bottle_size_ml", "type": "int", "min": 187, "max": 6000},
    {"name": "case_pack", "type": "int", "min": 1, "max": 24},
    {"name": "is_allocated", "type": "bool"},
    {"name": "predecessor_wine_id", "type": "string"},
]


@bp.post(API_PREFIX + "/wines")
def create_wine():
    authorize("BeverageDirector")
    body = get_body()
    predecessor = None
    if body.get("predecessor_wine_id") is not None:
        predecessor = get_wine(body["predecessor_wine_id"])
    validate_body(body, WINE_SPEC)

    rec = new_record(
        {
            "producer": body["producer"],
            "cuvee": body["cuvee"],
            "vintage_year": body["vintage_year"],
            "category": body["category"],
            "bottle_size_ml": body.get("bottle_size_ml", 750),
            "reference_cost_cents": body["reference_cost_cents"],
            "case_pack": body.get("case_pack", 6),
            "is_allocated": body.get("is_allocated", False),
            "predecessor_wine_id": body.get("predecessor_wine_id"),
            "successor_count": 0,
        }
    )
    store.wines[rec["id"]] = rec

    if predecessor is not None:
        predecessor["successor_count"] = int(predecessor["successor_count"]) + 1
        touch(predecessor)
        affected = []
        for entry in store.list_entries.values():
            if entry["wine_id"] != predecessor["id"]:
                continue
            version = store.list_versions.get(entry["list_version_id"])
            if version is None or version["state"] not in (
                "DRAFT",
                "IN_REVIEW",
                "PUBLISHED",
                "REPRINT_PENDING",
            ):
                continue
            if not entry["vintage_stale"]:
                entry["vintage_stale"] = True
                touch(entry)
            if version["id"] not in [v["id"] for v in affected]:
                affected.append(version)
        for version in affected:
            apply_stale_recount(version)
    return respond_object(serialize(rec), 201)


@bp.get(API_PREFIX + "/wines/<wine_id>")
def read_wine(wine_id):
    authorize(READ_ROLES)
    return respond_object(serialize(get_wine(wine_id)))


@bp.get(API_PREFIX + "/wines")
def list_wines():
    authorize(READ_ROLES)
    rows = list(store.wines.values())
    category = q("category")
    if category is not None:
        rows = [r for r in rows if r["category"] == category]
    allocated = bool_param("is_allocated")
    if allocated is not None:
        rows = [r for r in rows if bool(r["is_allocated"]) == allocated]
    predecessor = q("predecessor_wine_id")
    if predecessor is not None:
        rows = [r for r in rows if r["predecessor_wine_id"] == predecessor]
    page, meta = paginate(sort_default(rows))
    return respond_list([serialize(r) for r in page], meta)
