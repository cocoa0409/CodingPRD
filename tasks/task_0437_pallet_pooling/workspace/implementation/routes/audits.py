"""AuditReconciliation routes (PRD §3.6) and the loss-valuation cascade."""
from flask import Blueprint, request

from db import db, parse_dt, iso
from errors import err
from middleware import get_auth, require_roles, get_json_body
from response import object_response, array_response
from services import core

bp = Blueprint("audits", __name__)


@bp.route("/audit-reconciliations", methods=["POST"])
def create_audit():
    _, role = get_auth()
    require_roles(role, {"PoolAdmin", "PoolOperator"})
    body = get_json_body()
    # Existence first (priority 3, PRD §2.10).
    core.resolve_body_fk(body, "location_id", db.locations)
    # Body well-formedness (priority 4).
    core.require_fields(body, ["location_id", "window_start", "window_end", "counted_physical"])
    location_id = core.require_str(body, "location_id")
    window_start = core.require_datetime(body, "window_start")
    window_end = core.require_datetime(body, "window_end")
    counted_physical = core.require_int(body, "counted_physical", minimum=0)
    loss_basis = core.optional_enum(body, "loss_basis", {"REPLACEMENT", "NET_BOOK"}, "REPLACEMENT")

    # window_end must be on or after window_start (PRD §3.6).
    if window_end < window_start:
        raise err("ERR_INVALID_REQUEST", "window_end must be on or after window_start")

    audit = core.stamp_new({
        "location_id": location_id,
        "window_start": iso(window_start),
        "window_end": iso(window_end),
        "counted_physical": counted_physical,
        "loss_basis": loss_basis,
        "declared_loss_qty": 0,
        "declared_loss_cents": 0,
        "status": "DRAFT",
    })
    db.audits[audit["id"]] = audit
    return object_response(core.public(audit), 201)


@bp.route("/audit-reconciliations/<audit_id>", methods=["GET"])
def get_audit(audit_id):
    _, role = get_auth()
    require_roles(role, {"PoolAdmin", "PoolOperator", "Participant"})
    audit = core.require(db.audits, audit_id)
    return object_response(core.public(audit), 200)


@bp.route("/audit-reconciliations", methods=["GET"])
def list_audits():
    _, role = get_auth()
    require_roles(role, {"PoolAdmin", "PoolOperator", "Participant"})
    items = list(db.audits.values())
    for field in ("location_id", "status"):
        val = request.args.get(field)
        if val is not None:
            items = [a for a in items if a[field] == val]
    data, limit, offset, total = core.paginate(items, request.args)
    return array_response(data, limit, offset, total, 200)


def _windows_conflict(a_start, a_end, b_start, b_end, buffer_days):
    """True when [a_start, a_end] overlaps [b_start, b_end] or sits closer than
    buffer_days to it (closed-interval adjacency buffer) (PRD §3.6)."""
    buffer_secs = buffer_days * core.DAY_SECONDS
    # Overlap if intervals intersect at all.
    if a_start <= b_end and b_start <= a_end:
        return True
    # Otherwise the gap between the nearer endpoints must respect the buffer.
    if a_start > b_end:
        gap = (a_start - b_end).total_seconds()
    else:  # b_start > a_end
        gap = (b_start - a_end).total_seconds()
    return gap < buffer_secs


@bp.route("/audit-reconciliations/<audit_id>/finalize", methods=["POST"])
def finalize_audit(audit_id):
    _, role = get_auth()
    require_roles(role, {"PoolAdmin", "PoolOperator"})
    audit = core.require(db.audits, audit_id)
    # DRAFT -> FINALIZED (PRD §3.6) -> ERR_INVALID_STATE.
    if audit["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Audit is not DRAFT")
    location = db.locations[audit["location_id"]]

    # Precondition 1: location OPEN (PRD §3.6) -> ERR_LOCATION_CLOSED.
    if location["status"] != "OPEN":
        raise err("ERR_LOCATION_CLOSED", "Audited location is not OPEN")

    # Precondition 2: no overlap / buffer violation vs any FINALIZED window for
    # the same location (PRD §3.6) -> ERR_AUDIT_WINDOW_OVERLAP.
    policy = core.active_policy()
    buffer_days = policy["audit_min_interval_days"] if policy else 28
    a_start = parse_dt(audit["window_start"])
    a_end = parse_dt(audit["window_end"])
    for other in db.audits.values():
        if other["id"] == audit_id:
            continue
        if other["status"] != "FINALIZED":
            continue
        if other["location_id"] != audit["location_id"]:
            continue
        b_start = parse_dt(other["window_start"])
        b_end = parse_dt(other["window_end"])
        if _windows_conflict(a_start, a_end, b_start, b_end, buffer_days):
            raise err("ERR_AUDIT_WINDOW_OVERLAP",
                      "Audit window overlaps or violates the adjacency buffer")

    # --- Atomic cascade (PRD §3.6) ---
    # declared_loss_qty = max(0, equity_balance - counted_physical).
    declared_loss_qty = max(0, location["equity_balance"] - audit["counted_physical"])
    audit["declared_loss_qty"] = declared_loss_qty

    # Select victims: AVAILABLE assets at location, oldest in_service_at first,
    # then created_at (we use _seq as the stable creation tiebreak).
    available = [a for a in db.assets.values()
                 if a["current_location_id"] == audit["location_id"]
                 and a["condition"] == "AVAILABLE"]
    available.sort(key=lambda a: (parse_dt(a["in_service_at"]), a["_seq"]))
    victims = available[:declared_loss_qty]

    # declared_loss_cents under loss_basis (PRD §3.6 loss valuation).
    at = db.asset_types
    declared_loss_cents = 0
    if audit["loss_basis"] == "REPLACEMENT":
        # Sum per-victim replacement cost (assets may differ in asset type).
        for v in victims:
            declared_loss_cents += at[v["asset_type_id"]]["replacement_cost_cents"]
    else:  # NET_BOOK
        for v in victims:
            atype = at[v["asset_type_id"]]
            useful_life = atype["useful_life_days"]
            age_days = core.whole_days(parse_dt(v["in_service_at"]), a_end)
            remaining = max(0, useful_life - age_days)
            nbv = (atype["replacement_cost_cents"] * remaining) // useful_life
            declared_loss_cents += nbv
    audit["declared_loss_cents"] = declared_loss_cents

    # Mark victims LOST (AVAILABLE -> LOST), clear location (PRD §3.6).
    for v in victims:
        v["condition"] = "LOST"
        v["current_location_id"] = None
        core.touch(v)

    # Parallel sweep: auto-expire OUTSTANDING vouchers from this location whose
    # issued_at + voucher_expiry_days <= window_end (PRD §3.6/§3.7).
    voucher_expiry_days = policy["voucher_expiry_days"] if policy else 90
    for vou in db.vouchers.values():
        if vou["from_location_id"] != audit["location_id"]:
            continue
        if vou["status"] != "OUTSTANDING":
            continue
        issued = parse_dt(vou["issued_at"])
        if issued is None:
            continue
        expiry = issued + _days(voucher_expiry_days)
        if expiry <= a_end:
            vou["status"] = "EXPIRED"
            # Equity restored to issuer (PRD §3.7).
            from_loc = db.locations.get(vou["from_location_id"])
            if from_loc is not None:
                from_loc["equity_balance"] += vou["quantity"]
                core.recompute_equity_status(from_loc)
                core.touch(from_loc)
            core.touch(vou)

    # equity_balance unchanged by loss (PRD §3.6); recompute physical_balance
    # and equity_status.
    audit["status"] = "FINALIZED"
    core.touch(audit)
    core.recompute_location_derived(location)
    core.touch(location)
    return object_response(core.public(audit), 200)


def _days(n):
    from datetime import timedelta
    return timedelta(seconds=n * core.DAY_SECONDS)


@bp.route("/audit-reconciliations/<audit_id>/void", methods=["POST"])
def void_audit(audit_id):
    _, role = get_auth()
    require_roles(role, {"PoolAdmin"})
    audit = core.require(db.audits, audit_id)
    # DRAFT -> VOIDED (PRD §3.6) -> ERR_INVALID_STATE.
    if audit["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Only a DRAFT audit can be voided")
    audit["status"] = "VOIDED"
    core.touch(audit)
    return object_response(core.public(audit), 200)
