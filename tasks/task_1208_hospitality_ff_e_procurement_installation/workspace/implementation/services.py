"""Business logic: derived-field recomputation, freight allocation, fee,
posture, attic targets, evaluated bid cost. All cascades recompute within the
request per PRD 2.12 (immediate consistency)."""
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

import db
from errors import ApiError

S = db.STORE

# Calculation constants (SCAFFOLD Table 3)
FCL_CUBE_THRESHOLD_M3 = 67
FCL_FLAT_FREIGHT_CENTS = 480000
LTL_RATE_PER_M3_CENTS = 9000
LEAD_TIME_PENALTY_PER_DAY_CENTS = 25000
SAMPLE_ROUND_MAX = 2
CRITICAL_ATTIC_MULTIPLIER = 2

COMMITTED_PO_STATES = ("ISSUED", "ACKNOWLEDGED", "READY_TO_SHIP", "CONSOLIDATED")
NON_TERMINAL_CLAIM_STATES = ("OPEN", "SUBMITTED", "DISPUTED")


def po_of_line(line):
    return S["purchase_orders"][line["purchase_order_id"]]


def spec_of_line(line):
    return S["spec_items"][line["spec_item_id"]]


def project_of_line(line):
    return S["projects"][po_of_line(line)["project_id"]]


def lines_of_po(po_id, include_cancelled=False):
    rows = [l for l in S["po_lines"].values() if l["purchase_order_id"] == po_id]
    if not include_cancelled:
        rows = [l for l in rows if l["status"] != "CANCELLED"]
    return db.sorted_items(rows)


# ---------------------------------------------------------------------------
# POLine derived fields
# ---------------------------------------------------------------------------

def recompute_landed(line):
    """actual_landed_cents = qty_received * unit_price_cents
    + COALESCE(freight_alloc_final_cents, freight_alloc_provisional_cents)
    - damage_credit_cents"""
    freight = line["freight_alloc_final_cents"]
    if freight is None:
        freight = line["freight_alloc_provisional_cents"]
    val = line["qty_received"] * line["unit_price_cents"] + freight - line["damage_credit_cents"]
    if val != line["actual_landed_cents"]:
        line["actual_landed_cents"] = val
        db.touch(line)


def recompute_line_status_from_receipts(line):
    if line["status"] in ("CANCELLED", "RECONCILED"):
        return
    r = line["qty_received"]
    if r == 0:
        new = "OPEN"
    elif r < line["quantity_ordered"]:
        new = "PARTIALLY_RECEIVED"
    else:
        new = "FULLY_RECEIVED"
    if new != line["status"]:
        line["status"] = new
        db.touch(line)


def recompute_po_totals(po):
    lines = lines_of_po(po["id"])
    ext = sum(l["extended_cents"] for l in lines)
    cube = sum(l["declared_cube_m3"] for l in lines)
    if ext != po["total_extended_cents"] or cube != po["total_cube_m3"]:
        po["total_extended_cents"] = ext
        po["total_cube_m3"] = cube
        db.touch(po)


# ---------------------------------------------------------------------------
# Budget ledger (PRD 2.10)
# ---------------------------------------------------------------------------

def recompute_budget_line(bl):
    committed = 0
    actual = 0
    for line in S["po_lines"].values():
        if line["status"] == "CANCELLED":
            continue
        po = S["purchase_orders"][line["purchase_order_id"]]
        if po["project_id"] != bl["project_id"]:
            continue
        spec = S["spec_items"][line["spec_item_id"]]
        if spec["category"] != bl["category"]:
            continue
        if po["fulfillment_status"] in COMMITTED_PO_STATES:
            committed += line["extended_cents"] + line["freight_alloc_provisional_cents"]
        if line["qty_received"] > 0:
            actual += line["actual_landed_cents"]
    vc = bl["budgeted_cents"] - committed - actual
    vf = bl["budgeted_cents"] - actual
    if (committed != bl["committed_cents"] or actual != bl["actual_cents"]
            or vc != bl["variance_commitment_cents"] or vf != bl["variance_final_cents"]):
        bl["committed_cents"] = committed
        bl["actual_cents"] = actual
        bl["variance_commitment_cents"] = vc
        bl["variance_final_cents"] = vf
        db.touch(bl)


# ---------------------------------------------------------------------------
# Project aggregates and posture (PRD 2.9)
# ---------------------------------------------------------------------------

def recompute_project(p):
    bls = [b for b in S["budget_lines"].values() if b["project_id"] == p["id"]]
    committed = sum(b["committed_cents"] for b in bls)
    actual = sum(b["actual_cents"] for b in bls)
    if committed + actual > p["total_budget_cents"]:
        posture = "FROZEN"
    elif any(w["project_id"] == p["id"] and w["status"] == "IN_PROGRESS"
             for w in S["installation_windows"].values()):
        posture = "SEALED"
    else:
        posture = "OPEN"
    if (committed != p["committed_cents"] or actual != p["actual_spend_cents"]
            or posture != p["procurement_posture"]):
        p["committed_cents"] = committed
        p["actual_spend_cents"] = actual
        p["procurement_posture"] = posture
        db.touch(p)


def recompute_project_financials(project_id):
    """Recompute every budget line of the project, then project rollups/posture."""
    for b in db.sorted_items(
            [b for b in S["budget_lines"].values() if b["project_id"] == project_id]):
        recompute_budget_line(b)
    recompute_project(S["projects"][project_id])


def check_posture_open(project):
    """Stage-5 posture gate; FROZEN is checked before SEALED."""
    if project["procurement_posture"] == "FROZEN":
        raise ApiError("ERR_PROJECT_BUDGET_FROZEN",
                       "Project committed + actual exceeds total budget")
    if project["procurement_posture"] == "SEALED":
        raise ApiError("ERR_PROJECT_PROCUREMENT_SEALED",
                       "Installation has started; procurement is sealed")


# ---------------------------------------------------------------------------
# Bids (PRD 3.3)
# ---------------------------------------------------------------------------

def evaluated_cost(bid):
    spec = S["spec_items"][bid["spec_item_id"]]
    penalty = max(0, bid["lead_time_days"] - spec["required_lead_days"]) * LEAD_TIME_PENALTY_PER_DAY_CENTS
    return bid["unit_price_cents"] * spec["total_qty"] + bid["freight_estimate_cents"] + penalty


def refresh_bid_cost(bid):
    val = evaluated_cost(bid)
    if val != bid["evaluated_cost_cents"]:
        bid["evaluated_cost_cents"] = val


def serialize_bid(bid):
    refresh_bid_cost(bid)  # computed whenever a VendorBid is read
    return db.pub(bid)


# ---------------------------------------------------------------------------
# Attic target (PRD 3.7)
# ---------------------------------------------------------------------------

def recompute_attic_target(spec):
    lines = [l for l in S["po_lines"].values()
             if l["spec_item_id"] == spec["id"] and l["status"] != "CANCELLED"]
    if not lines:
        tgt = 0
    else:
        line = db.sorted_items(lines)[0]
        crit = CRITICAL_ATTIC_MULTIPLIER if spec["is_critical"] else 1
        raw = Decimal(line["qty_installed"]) * Decimal(str(spec["attic_target_pct"])) * crit
        raw = int(raw.to_integral_value(rounding="ROUND_CEILING"))
        tgt = min(max(raw, spec["attic_min_qty"]), spec["attic_max_qty"])
    if tgt != spec["attic_target_qty"]:
        spec["attic_target_qty"] = tgt
        db.touch(spec)


# ---------------------------------------------------------------------------
# Freight mode and allocation (PRD 2.11)
# ---------------------------------------------------------------------------

def shipment_pos(shipment):
    return db.sorted_items([p for p in S["purchase_orders"].values()
                            if p["shipment_id"] == shipment["id"]])


def allocation_lines(shipment):
    out = []
    for po in shipment_pos(shipment):
        out.extend(lines_of_po(po["id"]))
    return db.sorted_items(out)


def recompute_shipment_cube(shipment):
    cube = sum(p["total_cube_m3"] for p in shipment_pos(shipment))
    if cube != shipment["total_cube_m3"]:
        shipment["total_cube_m3"] = cube
        db.touch(shipment)


def _allocate(total_cents, lines, basis):
    """Round each line's raw share half-up first, then reconcile the signed
    residual to the line with the largest raw share (tie: earliest created_at)."""
    total_basis = sum(basis(l) for l in lines)
    if total_basis <= 0:
        return {l["id"]: 0 for l in lines}
    raws = {}
    rounded = {}
    for l in lines:
        raw = Decimal(total_cents) * Decimal(basis(l)) / Decimal(total_basis)
        raws[l["id"]] = raw
        rounded[l["id"]] = int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    residual = total_cents - sum(rounded.values())
    if residual != 0:
        best = max(lines, key=lambda l: (raws[l["id"]], -l["_seq"]))
        rounded[best["id"]] += residual
    return rounded


def seal_freight(shipment):
    """CONSOLIDATING -> SEALED: fix freight_mode/freight_total_cents and assign
    provisional per-line freight by declared-cube share."""
    cube = shipment["total_cube_m3"]
    if cube >= FCL_CUBE_THRESHOLD_M3:
        shipment["freight_mode"] = "FCL"
        shipment["freight_total_cents"] = FCL_FLAT_FREIGHT_CENTS
    else:
        shipment["freight_mode"] = "LTL"
        shipment["freight_total_cents"] = LTL_RATE_PER_M3_CENTS * cube
    lines = allocation_lines(shipment)
    alloc = _allocate(shipment["freight_total_cents"], lines,
                      lambda l: l["declared_cube_m3"])
    for l in lines:
        if l["freight_alloc_provisional_cents"] != alloc[l["id"]]:
            l["freight_alloc_provisional_cents"] = alloc[l["id"]]
            db.touch(l)
        recompute_landed(l)


def final_freight(shipment):
    """IN_TRANSIT -> RECEIVED: final allocation on the received-units basis."""
    lines = allocation_lines(shipment)
    alloc = _allocate(shipment["freight_total_cents"], lines,
                      lambda l: l["qty_received"])
    for l in lines:
        if l["freight_alloc_final_cents"] != alloc[l["id"]]:
            l["freight_alloc_final_cents"] = alloc[l["id"]]
            db.touch(l)
        recompute_landed(l)


# ---------------------------------------------------------------------------
# Change-order contingency draw fee (PRD 3.9, pinned evaluation order)
# ---------------------------------------------------------------------------

def compute_draw_fee(project, pos):
    """utilization u = (committed + actual + POS) / total_budget, pre-fee;
    rate 5% when u <= 0.80, 8% when u <= 0.95, else 12%; fee = round_half_up(rate*POS)."""
    x = project["committed_cents"] + project["actual_spend_cents"] + pos
    t = project["total_budget_cents"]
    if x * 100 <= 80 * t:
        rate_pct = 5
    elif x * 100 <= 95 * t:
        rate_pct = 8
    else:
        rate_pct = 12
    fee = (Decimal(pos) * Decimal(rate_pct) / Decimal(100)).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP)
    return int(fee)


# ---------------------------------------------------------------------------
# Shared getters with 404s (path ids validated left to right, PRD 2.7)
# ---------------------------------------------------------------------------

def _get(kind, rid, error_id):
    e = S[kind].get(rid)
    if e is None:
        raise ApiError(error_id)
    return e


def get_project(rid):
    return _get("projects", rid, "ERR_PROJECT_NOT_FOUND")


def get_budget_line(rid):
    return _get("budget_lines", rid, "ERR_BUDGET_LINE_NOT_FOUND")


def get_spec(rid):
    return _get("spec_items", rid, "ERR_SPEC_ITEM_NOT_FOUND")


def get_bid(rid):
    return _get("bids", rid, "ERR_BID_NOT_FOUND")


def get_po(rid):
    return _get("purchase_orders", rid, "ERR_PURCHASE_ORDER_NOT_FOUND")


def get_line(rid):
    return _get("po_lines", rid, "ERR_PO_LINE_NOT_FOUND")


def get_shipment(rid):
    return _get("shipments", rid, "ERR_SHIPMENT_NOT_FOUND")


def get_event(rid):
    return _get("receiving_events", rid, "ERR_RECEIVING_EVENT_NOT_FOUND")


def get_claim(rid):
    return _get("damage_claims", rid, "ERR_DAMAGE_CLAIM_NOT_FOUND")


def get_room(rid):
    return _get("rooms", rid, "ERR_ROOM_NOT_FOUND")


def get_window(rid):
    return _get("installation_windows", rid, "ERR_INSTALLATION_WINDOW_NOT_FOUND")


def get_task(rid):
    return _get("installation_tasks", rid, "ERR_INSTALLATION_TASK_NOT_FOUND")


def get_change_order(rid):
    return _get("change_orders", rid, "ERR_CHANGE_ORDER_NOT_FOUND")


def parse_iso_date(value, field):
    if not isinstance(value, str):
        raise ApiError("ERR_INVALID_REQUEST", f"Field {field} must be an ISO 8601 date")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ApiError("ERR_INVALID_REQUEST", f"Field {field} must be an ISO 8601 date")
