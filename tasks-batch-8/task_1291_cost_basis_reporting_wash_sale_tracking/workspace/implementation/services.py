"""Business logic: calculations, state transitions, cascades."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from db import store, _parse_iso, _iso3
from errors import (
    err,
    ERR_NOT_FOUND,
    ERR_INVALID_STATE_TRANSITION,
    ERR_INVALID_REQUEST,
    ERR_FOREIGN_KEY_UNRESOLVABLE,
    ERR_CUSTOMER_SUSPENDED,
    ERR_ACCOUNT_RESTRICTED,
    ERR_TAX_YEAR_CLOSED,
    ERR_LOT_SCOPE_MISMATCH,
    ERR_INCOMPLETE_ACTION_PAYLOAD,
    ERR_INCOMPLETE_LOT_BASIS_DETAIL,
    ERR_LOT_ALLOCATION_MISMATCH,
    ERR_INSUFFICIENT_LOT_QUANTITY,
    ERR_SOD_VIOLATION,
    ERR_MISSING_SUPPORTING_DOC,
    ERR_CORRECTION_WINDOW_CLOSED,
    ERR_SUPERSEDE_TARGET_INVALID,
    ERR_TRANSFER_ALREADY_SUPERSEDED,
    ERR_TRANSFER_INSUFFICIENT_POSITION,
    ERR_TRANSFER_MISSING_LOT_DETAIL,
    ERR_FORM_FROZEN,
    ERR_ACCOUNT_HAS_OPEN_LOTS,
    ERR_CUSTOMER_HAS_OPEN_ACCOUNTS,
    ERR_PENDING_BASIS_REQUESTS,
    ERR_STALE_ACCOUNT_VERSION,
    ERR_STALE_LOT_VERSION,
    ERR_STALE_FORM_VERSION,
)


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------

def _touch(entity):
    """Refresh updated_at + bump version."""
    entity["updated_at"] = store.now_iso()
    entity["version"] = entity.get("version", 0) + 1


def _new_entity(fields):
    now = store.now_iso()
    e = {
        "id": store.new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 0,
    }
    e.update(fields)
    return e


def _round_half_up_cents(value):
    """Round a numeric to whole cents (integer), half-up."""
    if isinstance(value, Decimal):
        d = value
    else:
        d = Decimal(str(value))
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _dt(s):
    return _parse_iso(s)


def _iso(dt):
    return _iso3(dt)


# ---------------------------------------------------------------------------
# Lookups with firm-scoping and left-to-right validation
# ---------------------------------------------------------------------------

def get_firm_or_404(firm_id):
    f = store.firms.get(firm_id)
    if f is None:
        raise err(ERR_NOT_FOUND, f"Firm {firm_id} not found")
    return f


def get_customer_or_404(firm_id, customer_id):
    c = store.customers.get(customer_id)
    if c is None or c["firm_id"] != firm_id:
        raise err(ERR_NOT_FOUND, f"Customer {customer_id} not found")
    return c


def get_account_or_404(firm_id, account_id):
    a = store.accounts.get(account_id)
    if a is None or a["firm_id"] != firm_id:
        raise err(ERR_NOT_FOUND, f"Account {account_id} not found")
    return a


def get_security_or_404(firm_id, security_id):
    s = store.securities.get(security_id)
    if s is None or s["firm_id"] != firm_id:
        raise err(ERR_NOT_FOUND, f"Security {security_id} not found")
    return s


def get_lot_or_404(firm_id, lot_id):
    l = store.tax_lots.get(lot_id)
    if l is None or l["firm_id"] != firm_id:
        raise err(ERR_NOT_FOUND, f"TaxLot {lot_id} not found")
    return l


def get_disposition_or_404(firm_id, disposition_id):
    d = store.dispositions.get(disposition_id)
    if d is None or d["firm_id"] != firm_id:
        raise err(ERR_NOT_FOUND, f"Disposition {disposition_id} not found")
    return d


def get_corporate_action_or_404(firm_id, action_id):
    a = store.corporate_actions.get(action_id)
    if a is None or a["firm_id"] != firm_id:
        raise err(ERR_NOT_FOUND, f"CorporateAction {action_id} not found")
    return a


def get_transfer_statement_or_404(firm_id, stmt_id):
    s = store.transfer_statements.get(stmt_id)
    if s is None or s["firm_id"] != firm_id:
        raise err(ERR_NOT_FOUND, f"TransferStatement {stmt_id} not found")
    return s


def get_wash_sale_event_or_404(firm_id, event_id):
    e = store.wash_sale_events.get(event_id)
    if e is None or e["firm_id"] != firm_id:
        raise err(ERR_NOT_FOUND, f"WashSaleEvent {event_id} not found")
    return e


def get_tax_form_or_404(firm_id, customer_id, form_id):
    f = store.tax_forms.get(form_id)
    if f is None or f["firm_id"] != firm_id or f["customer_id"] != customer_id:
        raise err(ERR_NOT_FOUND, f"TaxForm1099B {form_id} not found")
    return f


def get_basis_change_request_or_404(firm_id, req_id):
    r = store.basis_change_requests.get(req_id)
    if r is None or r["firm_id"] != firm_id:
        raise err(ERR_NOT_FOUND, f"BasisChangeRequest {req_id} not found")
    return r


# ---------------------------------------------------------------------------
# Covered status classification (§3.2)
# ---------------------------------------------------------------------------

def compute_covered_status(acquisition_kind, acquisition_date, security):
    if acquisition_kind == "INHERITANCE":
        return "NONCOVERED"
    if acquisition_kind == "GIFT":
        return "NONCOVERED"
    acq = _dt(acquisition_date)
    eff = _dt(security["covered_security_effective_date"])
    return "COVERED" if acq >= eff else "NONCOVERED"


# ---------------------------------------------------------------------------
# Term classification (§3.3)
# ---------------------------------------------------------------------------

def classify_term(lot, trade_date):
    """Return 'LONG_TERM' or 'SHORT_TERM' for an allocation from lot."""
    if lot["acquisition_kind"] == "INHERITANCE":
        return "LONG_TERM"
    hps = _dt(lot["holding_period_start"])
    td = _dt(trade_date)
    holding_days = (td - hps).days
    return "LONG_TERM" if holding_days > 365 else "SHORT_TERM"


# ---------------------------------------------------------------------------
# Lot selection and gain computation (§3.3, calculations.lot_selection_and_gain)
# ---------------------------------------------------------------------------

def _per_share_basis_cents(lot):
    """round_half_up(adjusted_cost_basis_cents / quantity, 0)"""
    if lot["quantity"] == 0:
        return 0
    return _round_half_up_cents(
        Decimal(lot["adjusted_cost_basis_cents"]) / Decimal(str(lot["quantity"]))
    )


def _gift_per_share_figures(lot):
    """Return (donor_basis_per_share, fmv_per_share) for a GIFT lot."""
    q = Decimal(str(lot["quantity"]))
    donor = Decimal(lot["gift_donor_basis_cents"]) / q
    fmv = Decimal(lot["gift_fmv_cents_at_gift"]) / q
    return donor, fmv


def _order_lots(candidates, method):
    """Sort candidate lots per the disposition method."""
    if method == "FIFO":
        return sorted(candidates, key=lambda l: (_dt(l["acquisition_date"]), _dt(l["created_at"])))
    if method == "LIFO":
        return sorted(candidates, key=lambda l: (_dt(l["acquisition_date"]), _dt(l["created_at"])), reverse=True)
    if method == "HIFO":
        return sorted(
            candidates,
            key=lambda l: (-_per_share_basis_cents(l), _dt(l["created_at"])),
        )
    # SPECIFIC_ID: order comes from lot_allocations; handled by caller.
    return list(candidates)


def _select_allocations(disposition, account, lots_by_id, preview=False):
    """Walk the method-ordered candidate list, build allocation list.

    Returns list of dicts: {lot_id, quantity, per_share_basis_cents, allocation_basis_cents, term}.
    Raises ERR_INSUFFICIENT_LOT_QUANTITY or ERR_LOT_ALLOCATION_MISMATCH as needed.
    """
    sec_id = disposition["security_id"]
    method = disposition["method"]

    if method == "SPECIFIC_ID":
        allocs_in = disposition.get("lot_allocations") or []
        total_alloc = Decimal("0")
        for a in allocs_in:
            total_alloc += Decimal(str(a.get("quantity", 0)))
        if total_alloc != Decimal(str(disposition["quantity"])):
            raise err(ERR_LOT_ALLOCATION_MISMATCH,
                      "sum(lot_allocations.quantity) != Disposition.quantity")
        ordered = []
        for a in allocs_in:
            lot = lots_by_id.get(a["lot_id"])
            if lot is None:
                raise err(ERR_LOT_SCOPE_MISMATCH,
                          f"lot_allocations references unknown lot {a['lot_id']}")
            ordered.append((lot, Decimal(str(a["quantity"]))))
    else:
        candidates = [
            l for l in store.tax_lots.values()
            if l["firm_id"] == disposition["firm_id"]
            and l["account_id"] == account["id"]
            and l["security_id"] == sec_id
            and l["lot_status"] in ("OPEN", "PARTIALLY_DISPOSED")
            and Decimal(str(l["quantity_remaining"])) > 0
        ]
        ordered_lots = _order_lots(candidates, method)
        needed = Decimal(str(disposition["quantity"]))
        ordered = []
        for lot in ordered_lots:
            if needed <= 0:
                break
            take = min(Decimal(str(lot["quantity_remaining"])), needed)
            if take > 0:
                ordered.append((lot, take))
                needed -= take

    # Verify sufficiency
    total_selected = sum(q for _, q in ordered)
    if total_selected < Decimal(str(disposition["quantity"])):
        raise err(ERR_INSUFFICIENT_LOT_QUANTITY,
                  "Selected lots cannot cover Disposition.quantity")

    allocations = []
    total_basis = 0
    for lot, qty in ordered:
        if method != "SPECIFIC_ID":
            if lot["lot_status"] not in ("OPEN", "PARTIALLY_DISPOSED"):
                raise err(ERR_INVALID_STATE_TRANSITION,
                          f"Lot {lot['id']} is not in a selectable state")
            if Decimal(str(lot["quantity_remaining"])) < qty:
                raise err(ERR_INSUFFICIENT_LOT_QUANTITY,
                          f"Lot {lot['id']} has insufficient quantity_remaining")

        # GIFT dual-basis: decide per-allocation at settle time
        if lot["acquisition_kind"] == "GIFT":
            donor_ps, fmv_ps = _gift_per_share_figures(lot)
            sale_ps = Decimal(disposition["proceeds_cents"]) / Decimal(str(disposition["quantity"]))
            if sale_ps > donor_ps:
                # Gain path: use donor basis
                basis_ps = _round_half_up_cents(donor_ps)
            elif sale_ps < fmv_ps and fmv_ps < donor_ps:
                # Loss path: use FMV
                basis_ps = _round_half_up_cents(fmv_ps)
            else:
                # No-man's land: zero gain/loss
                basis_ps = _round_half_up_cents(sale_ps)
        else:
            basis_ps = _per_share_basis_cents(lot)

        alloc_basis = basis_ps * int(qty) if qty == int(qty) else _round_half_up_cents(Decimal(basis_ps) * qty)
        term = classify_term(lot, disposition["trade_date"])
        allocations.append({
            "lot_id": lot["id"],
            "quantity": float(qty) if qty == qty.to_integral_value() else float(qty),
            "per_share_basis_cents": basis_ps,
            "allocation_basis_cents": alloc_basis,
            "term": term,
            "covered_status": lot["covered_status"],
        })
        total_basis += alloc_basis

    return allocations, total_basis


def compute_realized_gain(disposition, allocations, total_basis):
    return disposition["proceeds_cents"] - total_basis


# ---------------------------------------------------------------------------
# Wash-sale detection (§3.4, calculations.wash_sale_detection)
# ---------------------------------------------------------------------------

def detect_wash_sales(disposition, allocations, lots_by_id, same_account_only=False):
    """Run wash-sale detection.

    Returns (events_to_create, total_disallowed_cents).
    Each event is a dict ready to insert. Also mutates the triggering lots
    (taint + adjusted basis + holding period).
    """
    if disposition["realized_gain_cents"] >= 0:
        return [], 0

    firm = store.firms[disposition["firm_id"]]
    half = firm["wash_sale_window_days"]
    trade_dt = _dt(disposition["trade_date"])
    window_start = trade_dt - timedelta(days=half)
    window_end = trade_dt + timedelta(days=half)

    sold_sec = store.securities[disposition["security_id"]]
    sold_cusip = sold_sec["cusip"]
    customer = store.customers[store.accounts[disposition["account_id"]]["customer_id"]]
    scope_key = customer["wash_sale_scope_key"]

    # shares_sold_at_loss: sum of allocation qty from lots whose per-lot gain < 0
    per_lot_gain = {}
    for a in allocations:
        per_lot_gain.setdefault(a["lot_id"], 0)
        per_lot_gain[a["lot_id"]] += a["allocation_basis_cents"]
    # Compute per-lot proceeds share
    total_qty = Decimal(str(disposition["quantity"]))
    total_proceeds = disposition["proceeds_cents"]
    loss_lots = {}
    for a in allocations:
        lot = lots_by_id[a["lot_id"]]
        alloc_qty = Decimal(str(a["quantity"]))
        alloc_proceeds = _round_half_up_cents(
            Decimal(total_proceeds) * alloc_qty / total_qty
        )
        gain = alloc_proceeds - a["allocation_basis_cents"]
        loss_lots.setdefault(a["lot_id"], {"qty": Decimal("0"), "gain": 0})
        loss_lots[a["lot_id"]]["qty"] += alloc_qty
        loss_lots[a["lot_id"]]["gain"] += gain

    shares_sold_at_loss = Decimal("0")
    for lot_id, info in loss_lots.items():
        if info["gain"] < 0:
            shares_sold_at_loss += info["qty"]

    if shares_sold_at_loss <= 0:
        return [], 0

    total_loss = abs(disposition["realized_gain_cents"])

    # Find candidate replacement lots
    candidates = []
    for lot in store.tax_lots.values():
        if lot["firm_id"] != disposition["firm_id"]:
            continue
        acct = store.accounts.get(lot["account_id"])
        if acct is None:
            continue
        cust = store.customers.get(acct["customer_id"])
        if cust is None or cust["wash_sale_scope_key"] != scope_key:
            continue
        sec = store.securities.get(lot["security_id"])
        if sec is None or sec["cusip"] != sold_cusip:
            continue
        acq = _dt(lot["acquisition_date"])
        if not (window_start <= acq <= window_end):
            continue
        # Must be strictly after the sold lot's acquisition date
        sold_lot_ids = {a["lot_id"] for a in allocations}
        if lot["id"] in sold_lot_ids:
            continue
        # Check acquisition_date > sold lot's acquisition_date
        is_replacement = False
        for a in allocations:
            sold_lot = lots_by_id[a["lot_id"]]
            if acq > _dt(sold_lot["acquisition_date"]):
                is_replacement = True
                break
        if not is_replacement:
            continue
        if lot["lot_status"] not in ("OPEN", "PARTIALLY_DISPOSED"):
            continue
        if same_account_only and lot["account_id"] != disposition["account_id"]:
            continue
        candidates.append(lot)

    candidates.sort(key=lambda l: (_dt(l["acquisition_date"]), _dt(l["created_at"])))

    events = []
    remaining = shares_sold_at_loss
    total_disallowed = 0

    for cand in candidates:
        if remaining <= 0:
            break
        cand_avail = Decimal(str(cand["quantity_remaining"]))
        replacement_shares = min(cand_avail, remaining)
        if replacement_shares <= 0:
            continue

        if cand_avail >= remaining:
            rule = "SHARE_FOR_SHARE"
        else:
            rule = "PARTIAL_PRORATA"

        disallowed = _round_half_up_cents(
            Decimal(total_loss) * replacement_shares / shares_sold_at_loss
        )

        # Cascade onto candidate lot
        cand["wash_sale_taint_basis_cents"] = cand.get("wash_sale_taint_basis_cents", 0) + disallowed
        cand["adjusted_cost_basis_cents"] += disallowed
        sold_lot_hps = None
        for a in allocations:
            sl = lots_by_id[a["lot_id"]]
            hps = _dt(sl["holding_period_start"])
            if sold_lot_hps is None or hps < sold_lot_hps:
                sold_lot_hps = hps
        cand_hps = _dt(cand["holding_period_start"])
        if sold_lot_hps and sold_lot_hps < cand_hps:
            cand["holding_period_start"] = _iso(sold_lot_hps)
        _touch(cand)

        # Use first sold lot as representative
        sold_lot_id = allocations[0]["lot_id"]
        ev = _new_entity({
            "firm_id": disposition["firm_id"],
            "disposition_id": disposition["id"],
            "triggering_lot_id": cand["id"],
            "sold_lot_id": sold_lot_id,
            "disallowed_loss_cents": disallowed,
            "wash_sale_window_start": _iso(window_start),
            "wash_sale_window_end": _iso(window_end),
            "matching_rule": rule,
        })
        events.append(ev)
        total_disallowed += disallowed
        remaining -= replacement_shares

    return events, total_disallowed


# ---------------------------------------------------------------------------
# Disposition settle / correct
# ---------------------------------------------------------------------------

def settle_disposition(disp, acting_user_id=None):
    """PENDING -> SETTLED. Returns the mutated disposition."""
    if disp["status"] != "PENDING":
        raise err(ERR_INVALID_STATE_TRANSITION,
                  f"Disposition {disp['id']} is not PENDING")

    account = store.accounts[disp["account_id"]]
    if account["status"] != "OPEN":
        raise err(ERR_ACCOUNT_RESTRICTED,
                  "Account is not OPEN at settle time")
    customer = store.customers[account["customer_id"]]
    if customer["status"] != "ACTIVE":
        raise err(ERR_CUSTOMER_SUSPENDED,
                  "Customer is not ACTIVE at settle time")

    lots_by_id = {l["id"]: l for l in store.tax_lots.values() if l["firm_id"] == disp["firm_id"]}

    # For SPECIFIC_ID verify lot scope
    if disp["method"] == "SPECIFIC_ID":
        for a in (disp.get("lot_allocations") or []):
            lot = lots_by_id.get(a.get("lot_id"))
            if lot is None:
                raise err(ERR_LOT_SCOPE_MISMATCH,
                          f"lot {a.get('lot_id')} not found")
            if lot["account_id"] != account["id"] or lot["security_id"] != disp["security_id"]:
                raise err(ERR_LOT_SCOPE_MISMATCH,
                          "SPECIFIC_ID lot not on this Account+Security")
            if lot["lot_status"] not in ("OPEN", "PARTIALLY_DISPOSED"):
                raise err(ERR_INVALID_STATE_TRANSITION,
                          f"Lot {lot['id']} is not selectable")
            if Decimal(str(lot["quantity_remaining"])) < Decimal(str(a["quantity"])):
                raise err(ERR_INSUFFICIENT_LOT_QUANTITY,
                          f"Lot {lot['id']} has insufficient quantity")

    allocations, total_basis = _select_allocations(disp, account, lots_by_id)

    # Apply allocations to lots
    for a in allocations:
        lot = lots_by_id[a["lot_id"]]
        lot["quantity_remaining"] = float(Decimal(str(lot["quantity_remaining"])) - Decimal(str(a["quantity"])))
        lot["adjusted_cost_basis_cents"] -= a["allocation_basis_cents"]
        if Decimal(str(lot["quantity_remaining"])) <= 0:
            lot["quantity_remaining"] = 0
            lot["lot_status"] = "FULLY_DISPOSED"
        elif lot["lot_status"] == "OPEN":
            lot["lot_status"] = "PARTIALLY_DISPOSED"
        _touch(lot)

    realized = compute_realized_gain(disp, allocations, total_basis)
    disp["realized_gain_cents"] = realized
    disp["lot_allocations"] = [
        {"lot_id": a["lot_id"], "quantity": a["quantity"],
         "allocation_basis_cents": a["allocation_basis_cents"],
         "term": a["term"], "covered_status": a["covered_status"]}
        for a in allocations
    ]

    # Wash-sale detection
    events, disallowed = detect_wash_sales(disp, allocations, lots_by_id)
    for ev in events:
        store.wash_sale_events[ev["id"]] = ev
    disp["wash_sale_disallowed_loss_cents"] = disallowed
    disp["is_wash_sale_flag"] = disallowed > 0
    if disallowed > 0:
        disp["realized_gain_cents"] = realized + disallowed
        # Invalidate DRAFT/GENERATED 1099-B for this customer + tax_year
        _invalidate_draft_generated_forms(disp)

    disp["status"] = "SETTLED"
    _touch(disp)

    # If wash-sale events created after a form was FILED, flip FILED -> CORRECTION_PENDING
    if disallowed > 0:
        _mark_filed_forms_correction_pending(disp)

    return disp


def _invalidate_draft_generated_forms(disp):
    """Wash sale detected: DRAFT/GENERATED forms for this customer+year go back to DRAFT."""
    account = store.accounts[disp["account_id"]]
    customer_id = account["customer_id"]
    tax_year = _dt(disp["trade_date"]).year
    for form in store.tax_forms.values():
        if (form["firm_id"] == disp["firm_id"]
                and form["customer_id"] == customer_id
                and form["tax_year"] == tax_year
                and form["status"] in ("DRAFT", "GENERATED")):
            if form["status"] == "GENERATED":
                form["status"] = "DRAFT"
                _touch(form)


def _mark_filed_forms_correction_pending(disp):
    """Any in-scope FILED/REFILED form flips to CORRECTION_PENDING (wash sale event created after FILED)."""
    account = store.accounts[disp["account_id"]]
    customer_id = account["customer_id"]
    tax_year = _dt(disp["trade_date"]).year
    for form in store.tax_forms.values():
        if (form["firm_id"] == disp["firm_id"]
                and form["customer_id"] == customer_id
                and form["tax_year"] == tax_year
                and form["status"] in ("FILED", "REFILED")):
            form["status"] = "CORRECTION_PENDING"
            _touch(form)
            cust = store.customers[customer_id]
            _touch(cust)


def void_disposition(disp):
    if disp["status"] != "PENDING":
        raise err(ERR_INVALID_STATE_TRANSITION,
                  f"Disposition {disp['id']} is not PENDING")
    disp["status"] = "VOIDED"
    _touch(disp)
    return disp


def correct_disposition(disp, body):
    """SETTLED -> CORRECTED; create a new PENDING->SETTLED disposition."""
    if disp["status"] != "SETTLED":
        raise err(ERR_INVALID_STATE_TRANSITION,
                  f"Disposition {disp['id']} is not SETTLED")

    # At least one corrected field must differ
    new_proceeds = body.get("proceeds_cents", disp["proceeds_cents"])
    new_quantity = body.get("quantity", disp["quantity"])
    new_allocations = body.get("lot_allocations")
    differs = (
        new_proceeds != disp["proceeds_cents"]
        or new_quantity != disp["quantity"]
        or (new_allocations is not None and new_allocations != [
            {"lot_id": a["lot_id"], "quantity": a["quantity"]}
            for a in (disp.get("lot_allocations") or [])
        ])
    )
    if not differs:
        raise err(ERR_INVALID_REQUEST,
                  "At least one corrected field must differ")

    # Check no in-scope FROZEN form
    account = store.accounts[disp["account_id"]]
    customer_id = account["customer_id"]
    tax_year = _dt(disp["trade_date"]).year
    for form in store.tax_forms.values():
        if (form["firm_id"] == disp["firm_id"]
                and form["customer_id"] == customer_id
                and form["tax_year"] == tax_year
                and form["status"] == "FROZEN"):
            raise err(ERR_FORM_FROZEN,
                      "Cannot correct: in-scope TaxForm1099B is FROZEN")

    lots_by_id = {l["id"]: l for l in store.tax_lots.values() if l["firm_id"] == disp["firm_id"]}

    # Reverse prior allocations
    for a in (disp.get("lot_allocations") or []):
        lot = lots_by_id.get(a["lot_id"])
        if lot is None:
            continue
        lot["quantity_remaining"] = float(
            Decimal(str(lot["quantity_remaining"])) + Decimal(str(a["quantity"]))
        )
        lot["adjusted_cost_basis_cents"] += a.get("allocation_basis_cents", 0)
        if lot["lot_status"] == "FULLY_DISPOSED" and Decimal(str(lot["quantity_remaining"])) > 0:
            lot["lot_status"] = "OPEN" if Decimal(str(lot["quantity_remaining"])) == Decimal(str(lot["quantity"])) else "PARTIALLY_DISPOSED"
        elif lot["lot_status"] == "PARTIALLY_DISPOSED" and Decimal(str(lot["quantity_remaining"])) == Decimal(str(lot["quantity"])):
            lot["lot_status"] = "OPEN"
        _touch(lot)

    # Unwind wash-sale events
    for ev in list(store.wash_sale_events.values()):
        if ev["disposition_id"] == disp["id"]:
            trig = lots_by_id.get(ev["triggering_lot_id"])
            if trig:
                trig["wash_sale_taint_basis_cents"] = max(
                    0, trig.get("wash_sale_taint_basis_cents", 0) - ev["disallowed_loss_cents"]
                )
                trig["adjusted_cost_basis_cents"] -= ev["disallowed_loss_cents"]
                _touch(trig)
            del store.wash_sale_events[ev["id"]]

    # Mark original CORRECTED
    disp["status"] = "CORRECTED"
    _touch(disp)

    # Create new disposition with corrected values
    new_disp = _new_entity({
        "firm_id": disp["firm_id"],
        "account_id": disp["account_id"],
        "security_id": disp["security_id"],
        "trade_date": disp["trade_date"],
        "settlement_date": disp["settlement_date"],
        "quantity": new_quantity,
        "proceeds_cents": new_proceeds,
        "method": disp["method"],
        "lot_allocations": new_allocations if new_allocations is not None else None,
        "status": "PENDING",
        "realized_gain_cents": 0,
        "is_wash_sale_flag": False,
        "wash_sale_disallowed_loss_cents": 0,
    })
    store.dispositions[new_disp["id"]] = new_disp

    # Settle the new disposition
    settle_disposition(new_disp)

    # Mark in-scope forms CORRECTION_PENDING (§3.5 list plus REFILED — §3.8:
    # "Further qualifying changes flip a REFILED form back to
    # CORRECTION_PENDING — the loop ... is unbounded while the window stays
    # open.")
    for form in store.tax_forms.values():
        if (form["firm_id"] == disp["firm_id"]
                and form["customer_id"] == customer_id
                and form["tax_year"] == tax_year
                and form["status"] in ("GENERATED", "FILED", "REFILED", "CORRECTION_PENDING")):
            if form["status"] != "CORRECTION_PENDING":
                form["status"] = "CORRECTION_PENDING"
                _touch(form)
                cust = store.customers[customer_id]
                _touch(cust)

    return disp


# ---------------------------------------------------------------------------
# 1099-B aggregation (§3.8)
# ---------------------------------------------------------------------------

def aggregate_1099b(firm_id, customer_id, tax_year):
    """Compute the six totals + disallowed_wash_sale_loss_cents."""
    st_proceeds = 0
    st_basis = 0
    lt_proceeds = 0
    lt_basis = 0
    wash_disallowed = 0

    for disp in store.dispositions.values():
        if disp["firm_id"] != firm_id:
            continue
        acct = store.accounts.get(disp["account_id"])
        if acct is None or acct["customer_id"] != customer_id:
            continue
        if disp["status"] != "SETTLED":
            continue
        if _dt(disp["trade_date"]).year != tax_year:
            continue
        allocs = disp.get("lot_allocations") or []
        if not allocs:
            continue
        # Only dispositions with at least one COVERED allocation
        covered = [a for a in allocs if a.get("covered_status") == "COVERED"]
        if not covered:
            continue

        total_qty = Decimal(str(disp["quantity"]))
        for a in covered:
            qty = Decimal(str(a["quantity"]))
            proceeds_share = _round_half_up_cents(
                Decimal(disp["proceeds_cents"]) * qty / total_qty
            )
            if a.get("term") == "LONG_TERM":
                lt_proceeds += proceeds_share
                lt_basis += a.get("allocation_basis_cents", 0)
            else:
                st_proceeds += proceeds_share
                st_basis += a.get("allocation_basis_cents", 0)

        wash_disallowed += disp.get("wash_sale_disallowed_loss_cents", 0)

    return {
        "short_term_proceeds_cents": st_proceeds,
        "short_term_basis_cents": st_basis,
        "short_term_gain_cents": st_proceeds - st_basis,
        "long_term_proceeds_cents": lt_proceeds,
        "long_term_basis_cents": lt_basis,
        "long_term_gain_cents": lt_proceeds - lt_basis,
        "disallowed_wash_sale_loss_cents": wash_disallowed,
    }


# ---------------------------------------------------------------------------
# Corporate action basis adjustment (§3.6)
# ---------------------------------------------------------------------------

def apply_corporate_action(action):
    """ANNOUNCED -> EFFECTIVE; rewrite all affected lots."""
    if action["status"] != "ANNOUNCED":
        raise err(ERR_INVALID_STATE_TRANSITION,
                  f"CorporateAction {action['id']} is not ANNOUNCED")

    _validate_action_payload(action)

    affected_accounts = set()
    source_lots = [
        l for l in store.tax_lots.values()
        if l["firm_id"] == action["firm_id"]
        and l["security_id"] == action["security_id"]
        and l["lot_status"] in ("OPEN", "PARTIALLY_DISPOSED")
    ]

    for lot in source_lots:
        _apply_action_to_lot(action, lot)
        affected_accounts.add(lot["account_id"])

    # Bubble up account versions
    for acct_id in affected_accounts:
        acct = store.accounts.get(acct_id)
        if acct:
            _touch(acct)

    action["status"] = "EFFECTIVE"
    _touch(action)
    return action


def _validate_action_payload(action):
    at = action["action_type"]
    if at in ("SPLIT", "REVERSE_SPLIT"):
        num = action.get("split_ratio_numerator")
        den = action.get("split_ratio_denominator")
        if num is None or den is None:
            raise err(ERR_INCOMPLETE_ACTION_PAYLOAD,
                      "SPLIT/REVERSE_SPLIT requires split_ratio_numerator and split_ratio_denominator")
        if Decimal(str(num)) <= 0 or Decimal(str(den)) <= 0:
            raise err(ERR_INCOMPLETE_ACTION_PAYLOAD,
                      "split_ratio_numerator and split_ratio_denominator must be > 0")
    elif at == "MERGER":
        if not action.get("merger_acquirer_security_id"):
            raise err(ERR_INCOMPLETE_ACTION_PAYLOAD,
                      "MERGER requires merger_acquirer_security_id")
        cash = action.get("merger_cash_per_share_cents")
        if cash is None or cash < 0:
            raise err(ERR_INCOMPLETE_ACTION_PAYLOAD,
                      "MERGER requires merger_cash_per_share_cents >= 0")
        shares = action.get("merger_shares_per_source_share")
        if shares is None or Decimal(str(shares)) <= 0:
            raise err(ERR_INCOMPLETE_ACTION_PAYLOAD,
                      "MERGER requires merger_shares_per_source_share > 0")
    elif at == "SPINOFF":
        if not action.get("merger_acquirer_security_id"):
            raise err(ERR_INCOMPLETE_ACTION_PAYLOAD,
                      "SPINOFF requires merger_acquirer_security_id")
        pct = action.get("spinoff_cost_allocation_pct")
        if pct is None or not (0 < float(pct) < 1):
            raise err(ERR_INCOMPLETE_ACTION_PAYLOAD,
                      "SPINOFF requires 0 < spinoff_cost_allocation_pct < 1")
        shares = action.get("merger_shares_per_source_share")
        if shares is None or Decimal(str(shares)) <= 0:
            raise err(ERR_INCOMPLETE_ACTION_PAYLOAD,
                      "SPINOFF requires merger_shares_per_source_share > 0")

    if at in ("MERGER", "SPINOFF"):
        acquirer = store.securities.get(action.get("merger_acquirer_security_id"))
        if acquirer is None or acquirer["firm_id"] != action["firm_id"]:
            raise err(ERR_FOREIGN_KEY_UNRESOLVABLE,
                      "merger_acquirer_security_id does not resolve in this firm")


def _apply_action_to_lot(action, lot):
    """Supersede lot, spawn derived lot(s)."""
    Q = Decimal(str(lot["quantity_remaining"]))
    B = lot["adjusted_cost_basis_cents"]
    at = action["action_type"]
    firm_id = action["firm_id"]

    derived = []

    if at == "SPLIT":
        num = Decimal(str(action["split_ratio_numerator"]))
        den = Decimal(str(action["split_ratio_denominator"]))
        new_q = Q * num / den
        derived.append(_new_entity({
            "firm_id": firm_id,
            "account_id": lot["account_id"],
            "security_id": lot["security_id"],
            "acquisition_date": lot["acquisition_date"],
            "quantity": float(new_q),
            "quantity_remaining": float(new_q),
            "original_cost_basis_cents": B,
            "adjusted_cost_basis_cents": B,
            "acquisition_kind": "CORPORATE_ACTION_DERIVED",
            "holding_period_start": lot["holding_period_start"],
            "wash_sale_taint_basis_cents": lot.get("wash_sale_taint_basis_cents", 0),
            "covered_status": lot["covered_status"],
            "lot_status": "OPEN",
            "superseded_by_action_id": None,
        }))

    elif at == "REVERSE_SPLIT":
        num = Decimal(str(action["split_ratio_numerator"]))
        den = Decimal(str(action["split_ratio_denominator"]))
        raw_new_q = Q * num / den
        new_q = int(raw_new_q)  # floor
        frac = raw_new_q - Decimal(new_q)
        cash_in_lieu = _round_half_up_cents(frac * Decimal(B) / Q) if Q > 0 else 0
        new_basis = B - cash_in_lieu
        taint = max(0, lot.get("wash_sale_taint_basis_cents", 0) - cash_in_lieu)
        derived.append(_new_entity({
            "firm_id": firm_id,
            "account_id": lot["account_id"],
            "security_id": lot["security_id"],
            "acquisition_date": lot["acquisition_date"],
            "quantity": new_q,
            "quantity_remaining": new_q,
            "original_cost_basis_cents": new_basis,
            "adjusted_cost_basis_cents": new_basis,
            "acquisition_kind": "CORPORATE_ACTION_DERIVED",
            "holding_period_start": lot["holding_period_start"],
            "wash_sale_taint_basis_cents": taint,
            "covered_status": lot["covered_status"],
            "lot_status": "OPEN",
            "superseded_by_action_id": None,
        }))

    elif at == "MERGER":
        shares_per = Decimal(str(action["merger_shares_per_source_share"]))
        cash_per = action["merger_cash_per_share_cents"]
        new_q = Q * shares_per
        boot = _round_half_up_cents(Q * Decimal(cash_per))
        new_basis = max(0, B - min(boot, B))
        derived.append(_new_entity({
            "firm_id": firm_id,
            "account_id": lot["account_id"],
            "security_id": action["merger_acquirer_security_id"],
            "acquisition_date": lot["acquisition_date"],
            "quantity": float(new_q),
            "quantity_remaining": float(new_q),
            "original_cost_basis_cents": new_basis,
            "adjusted_cost_basis_cents": new_basis,
            "acquisition_kind": "CORPORATE_ACTION_DERIVED",
            "holding_period_start": lot["holding_period_start"],
            "wash_sale_taint_basis_cents": lot.get("wash_sale_taint_basis_cents", 0),
            "covered_status": lot["covered_status"],
            "lot_status": "OPEN",
            "superseded_by_action_id": None,
        }))

    elif at == "SPINOFF":
        shares_per = Decimal(str(action["merger_shares_per_source_share"]))
        pct = Decimal(str(action["spinoff_cost_allocation_pct"]))
        spun_q = Q * shares_per
        spun_basis = _round_half_up_cents(Decimal(B) * pct)
        parent_basis = B - spun_basis
        # Spun-off lot on acquirer security
        derived.append(_new_entity({
            "firm_id": firm_id,
            "account_id": lot["account_id"],
            "security_id": action["merger_acquirer_security_id"],
            "acquisition_date": lot["acquisition_date"],
            "quantity": float(spun_q),
            "quantity_remaining": float(spun_q),
            "original_cost_basis_cents": spun_basis,
            "adjusted_cost_basis_cents": spun_basis,
            "acquisition_kind": "CORPORATE_ACTION_DERIVED",
            "holding_period_start": lot["holding_period_start"],
            "wash_sale_taint_basis_cents": 0,
            "covered_status": lot["covered_status"],
            "lot_status": "OPEN",
            "superseded_by_action_id": None,
        }))
        # Parent lot stays on original security
        derived.append(_new_entity({
            "firm_id": firm_id,
            "account_id": lot["account_id"],
            "security_id": lot["security_id"],
            "acquisition_date": lot["acquisition_date"],
            "quantity": float(Q),
            "quantity_remaining": float(Q),
            "original_cost_basis_cents": parent_basis,
            "adjusted_cost_basis_cents": parent_basis,
            "acquisition_kind": "CORPORATE_ACTION_DERIVED",
            "holding_period_start": lot["holding_period_start"],
            "wash_sale_taint_basis_cents": lot.get("wash_sale_taint_basis_cents", 0),
            "covered_status": lot["covered_status"],
            "lot_status": "OPEN",
            "superseded_by_action_id": None,
        }))

    for d in derived:
        store.tax_lots[d["id"]] = d

    lot["lot_status"] = "SUPERSEDED"
    lot["superseded_by_action_id"] = action["id"]
    lot["quantity_remaining"] = 0
    _touch(lot)


# ---------------------------------------------------------------------------
# Logical clock freeze sweep
# ---------------------------------------------------------------------------

def freeze_expired_forms():
    """CORRECTION_PENDING -> FROZEN when logical clock > filed_at + correction_deadline_days."""
    now = store.clock
    for form in store.tax_forms.values():
        if form["status"] != "CORRECTION_PENDING":
            continue
        if not form.get("filed_at"):
            continue
        firm = store.firms.get(form["firm_id"])
        if firm is None:
            continue
        deadline = _dt(form["filed_at"]) + timedelta(days=firm["correction_deadline_days"])
        if now > deadline:
            form["status"] = "FROZEN"
            _touch(form)
