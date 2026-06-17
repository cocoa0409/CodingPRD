"""Sale lifecycle: pricing, settlement effects, returns, voids, reversals.

A Sale stores, internally (underscore-prefixed, stripped from the public view):
  _lines        : list of resolved line dicts
  _tenders      : list of tender line ids in append order
A resolved line dict carries:
  line_no, product_id, quantity, return_of_line_no,
  list_price_cents, tax_exempt, loyalty_eligible   (snapshotted at create)
"""
from errors import (
    err, ERR_INVALID_RETURN_REFERENCE, ERR_INSUFFICIENT_STOCK,
    ERR_PROMO_NOT_APPLICABLE,
)
from common import touch
from services.pricing import price_basket, eligible_net
from services.inventory import recompute, find_item
from services.loyalty import recompute_tier, apply_tier_multiplier


def resolve_lines(db, raw_lines, kind):
    """Validate and snapshot the lines array into resolved line dicts.

    raw_lines: list of {product_id, quantity, return_of_line_no?}.
    Raises ERR_INVALID_REQUEST (via as_int-style checks) handled by caller;
    raises ERR_REFERENCE_NOT_FOUND for unknown product ids.
    """
    from errors import ERR_INVALID_REQUEST, ERR_REFERENCE_NOT_FOUND
    if not isinstance(raw_lines, list) or len(raw_lines) == 0:
        raise err(ERR_INVALID_REQUEST, "lines must be a non-empty array")
    resolved = []
    for idx, rl in enumerate(raw_lines):
        if not isinstance(rl, dict):
            raise err(ERR_INVALID_REQUEST, "each line must be an object")
        product_id = rl.get("product_id")
        quantity = rl.get("quantity")
        if not isinstance(product_id, str):
            raise err(ERR_INVALID_REQUEST, "line product_id required")
        if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 1:
            raise err(ERR_INVALID_REQUEST, "line quantity must be a positive integer")
        return_of_line_no = rl.get("return_of_line_no")
        if return_of_line_no is not None:
            if isinstance(return_of_line_no, bool) or not isinstance(return_of_line_no, int):
                raise err(ERR_INVALID_REQUEST, "return_of_line_no must be an integer")
        product = db.products.get(product_id)
        if product is None:
            raise err(ERR_REFERENCE_NOT_FOUND, "line product_id not found")
        resolved.append({
            "line_no": idx + 1,
            "product_id": product_id,
            "quantity": quantity,
            "return_of_line_no": return_of_line_no,
            "list_price_cents": product["list_price_cents"],
            "tax_exempt": product["tax_exempt"],
            "loyalty_eligible": product["loyalty_eligible"],
        })
    return resolved


def _pricing_inputs(lines):
    """Project resolved lines into the structure price_basket expects."""
    return [
        {
            "list_price_cents": ln["list_price_cents"],
            "quantity": ln["quantity"],
            "tax_exempt": ln["tax_exempt"],
            "loyalty_eligible": ln["loyalty_eligible"],
        }
        for ln in lines
    ]


def price_sale(db, sale, enforce_guards=True):
    """Compute and store all pricing figures on a SALE.

    For RETURN/EXCHANGE the refund is computed from the ORIGINAL sale; this is
    handled by price_return (see below). This function is for kind == SALE.
    """
    store = db.stores[sale["store_id"]]
    promo = _resolve_promo(db, sale.get("promo_code"), enforce_guards)
    account = None
    if sale.get("loyalty_account_id"):
        account = db.loyalty_accounts.get(sale["loyalty_account_id"])
    redeem = sale.get("redeem_points", 0) or 0

    result = price_basket(
        _pricing_inputs(sale["_lines"]),
        promo,
        redeem,
        account,
        store["tax_rate_bps"],
        enforce_guards=enforce_guards,
    )
    sale["merchandise_subtotal_cents"] = result["merchandise_subtotal_cents"]
    sale["discount_cents"] = result["discount_cents"]
    sale["loyalty_redeemed_cents"] = result["loyalty_redeemed_cents"]
    sale["tax_cents"] = result["tax_cents"]
    sale["total_due_cents"] = result["total_due_cents"]
    sale["_line_net_alloc"] = result["line_net_alloc"]
    return result


def _resolve_promo(db, promo_code, enforce_guards=True):
    if not promo_code:
        return None
    for p in db.promotions.values():
        if p["code"] == promo_code:
            return p
    # Unknown promo code: a code that names no promotion cannot be ACTIVE, so it
    # is ERR_PROMO_NOT_APPLICABLE (PRD §3.4, priority 11). When recomputing an
    # already-settled original sale (enforce_guards False) this never fires.
    if enforce_guards:
        raise err(ERR_PROMO_NOT_APPLICABLE, "Promotion code not applicable")
    return None


# ----- RETURN / EXCHANGE refund (PRD §3.7, calc B) -------------------------

def validate_return_reference(db, original_sale_id, return_lines):
    """PRD §3.7 / priority 10: original must be SETTLED & kind==SALE; each
    return_of_line_no maps to an original line not already fully returned."""
    if not original_sale_id:
        raise err(ERR_INVALID_RETURN_REFERENCE, "original_sale_id required")
    original = db.sales.get(original_sale_id)
    if original is None:
        raise err(ERR_INVALID_RETURN_REFERENCE, "original_sale_id not found")
    if original["kind"] != "SALE" or original["settlement_status"] != "SETTLED":
        raise err(ERR_INVALID_RETURN_REFERENCE, "original sale must be a SETTLED SALE")

    already = _already_returned_by_line(db, original_sale_id)
    orig_by_no = {ln["line_no"]: ln for ln in original["_lines"]}
    # Aggregate requested return qty per original line for this request.
    req_by_no = {}
    for rl in return_lines:
        ln_no = rl["return_of_line_no"]
        if ln_no is None or ln_no not in orig_by_no:
            raise err(ERR_INVALID_RETURN_REFERENCE, "return_of_line_no does not map to an original line")
        req_by_no[ln_no] = req_by_no.get(ln_no, 0) + rl["quantity"]
    for ln_no, qty in req_by_no.items():
        orig_qty = orig_by_no[ln_no]["quantity"]
        if already.get(ln_no, 0) + qty > orig_qty:
            raise err(ERR_INVALID_RETURN_REFERENCE, "return exceeds original line quantity")
    return original


def _already_returned_by_line(db, original_sale_id):
    """How many units of each original line have already been returned by
    SETTLED returns/exchanges referencing this original sale."""
    counts = {}
    for s in db.sales.values():
        if s.get("original_sale_id") != original_sale_id:
            continue
        if s["kind"] not in ("RETURN", "EXCHANGE"):
            continue
        if s["settlement_status"] != "SETTLED":
            continue
        for ln in s["_lines"]:
            if ln.get("return_of_line_no") is not None:
                counts[ln["return_of_line_no"]] = counts.get(ln["return_of_line_no"], 0) + ln["quantity"]
    return counts


def _original_pricing(db, original):
    """Re-run the ORIGINAL sale's pricing to recover per-line nets and tax.
    Returns the price_basket result plus per-line original effective unit price
    (floored) and proportional original tax."""
    store = db.stores[original["store_id"]]
    promo = None
    if original.get("promo_code"):
        for p in db.promotions.values():
            if p["code"] == original["promo_code"]:
                promo = p
                break
    account = None
    if original.get("loyalty_account_id"):
        account = db.loyalty_accounts.get(original["loyalty_account_id"])
    redeem = original.get("redeem_points", 0) or 0
    result = price_basket(
        _pricing_inputs(original["_lines"]),
        promo,
        redeem,
        account,
        store["tax_rate_bps"],
        enforce_guards=False,
    )
    return result


def compute_provisional_refund(db, original, return_lines):
    """PROVISIONAL refund (PRD §3.7): per return line, original effective unit
    price (original line net / original quantity, floored per unit) * returned
    qty, plus proportional original tax; summed. Returns a NEGATIVE total_due
    convention is handled by caller. Here returns positive magnitude per the
    estimate, then caller negates appropriately."""
    result = _original_pricing(db, original)
    line_net = result["line_net_alloc"]            # net (post-discount-post-redeem) per orig line
    taxable_base = result["taxable_base"]
    total_tax = result["tax_cents"]
    orig_lines = original["_lines"]
    # per-original-line taxable share (its net alloc if not exempt)
    by_no = {}
    for i, ln in enumerate(orig_lines):
        by_no[ln["line_no"]] = (ln, line_net[i])

    refund = 0
    for rl in return_lines:
        ln_no = rl["return_of_line_no"]
        orig_ln, net = by_no[ln_no]
        qty = rl["quantity"]
        orig_qty = orig_ln["quantity"]
        eff_unit = net // orig_qty if orig_qty else 0
        line_refund = eff_unit * qty
        # proportional original tax for the returned units
        if not orig_ln["tax_exempt"] and taxable_base > 0 and total_tax > 0:
            # this line's taxable share is its net alloc (non-exempt)
            line_tax = (total_tax * net) // taxable_base
            unit_tax = line_tax // orig_qty if orig_qty else 0
            line_refund += unit_tax * qty
        refund += line_refund
    return refund


def _reduced_pricing(db, original, return_lines):
    """Re-run the original sale's pricing with the returned units removed."""
    reduce_by = {}
    for rl in return_lines:
        ln_no = rl["return_of_line_no"]
        reduce_by[ln_no] = reduce_by.get(ln_no, 0) + rl["quantity"]
    reduced_inputs = []
    for ln in original["_lines"]:
        remaining = ln["quantity"] - reduce_by.get(ln["line_no"], 0)
        if remaining <= 0:
            continue
        reduced_inputs.append({
            "list_price_cents": ln["list_price_cents"],
            "quantity": remaining,
            "tax_exempt": ln["tax_exempt"],
            "loyalty_eligible": ln["loyalty_eligible"],
        })

    store = db.stores[original["store_id"]]
    promo = None
    if original.get("promo_code"):
        for p in db.promotions.values():
            if p["code"] == original["promo_code"]:
                promo = p
                break
    account = None
    if original.get("loyalty_account_id"):
        account = db.loyalty_accounts.get(original["loyalty_account_id"])
    redeem = original.get("redeem_points", 0) or 0

    if reduced_inputs:
        return price_basket(reduced_inputs, promo, redeem, account,
                            store["tax_rate_bps"], enforce_guards=False)
    return None


def compute_final_refund(db, original, return_lines):
    """FINAL refund (PRD §3.7): basket delta — re-run original pricing with the
    returned units removed; refund = original_total_due - recomputed_total_due."""
    orig_result = _original_pricing(db, original)
    orig_total = orig_result["total_due_cents"]
    reduced = _reduced_pricing(db, original, return_lines)
    reduced_total = reduced["total_due_cents"] if reduced else 0
    return orig_total - reduced_total


# ----- Settlement effects (PRD §3.5, §3.6, §3.8) ---------------------------

def check_settlement_stock(db, sale):
    """Validate stock availability for settlement WITHOUT mutating (PRD §3.6).

    For a SALE every line's InventoryItem.available_qty must be >= line qty.
    For an EXCHANGE the outbound (newly-sold) lines must clear the same bar.
    Raises ERR_INSUFFICIENT_STOCK before any side effect lands (PRD §2.10).
    """
    if sale["kind"] == "SALE":
        check_lines = sale["_lines"]
    else:
        check_lines = [ln for ln in sale["_lines"] if ln.get("return_of_line_no") is None]
    for ln in check_lines:
        item = find_item(db, sale["store_id"], ln["product_id"])
        if item is None or item["available_qty"] < ln["quantity"]:
            raise err(ERR_INSUFFICIENT_STOCK, "Insufficient stock at settlement")


def settle_sale(db, sale):
    """Apply the stock + loyalty + cash side effects of settlement.

    Precondition checks (stock availability for SALE / EXCHANGE outbound) are
    enforced here and raise ERR_INSUFFICIENT_STOCK before any mutation lands.
    """
    if sale["kind"] == "SALE":
        _commit_sale_inventory(db, sale)
        sale["stock_status"] = "COMMITTED"
        _earn_loyalty(db, sale)
    else:  # RETURN or EXCHANGE
        _restock_return_inventory(db, sale)
        sale["stock_status"] = "RESTOCKED"
        _reverse_loyalty_for_return(db, sale)
    _apply_cash_movement(db, sale)
    sale["settlement_status"] = "SETTLED"


def _commit_sale_inventory(db, sale):
    # Check ALL lines first (atomicity, PRD §2.10 / §3.6).
    items = []
    for ln in sale["_lines"]:
        item = find_item(db, sale["store_id"], ln["product_id"])
        if item is None or item["available_qty"] < ln["quantity"]:
            raise err(ERR_INSUFFICIENT_STOCK, "Insufficient stock at settlement")
        items.append((item, ln["quantity"]))
    for item, qty in items:
        item["on_hand_qty"] -= qty
        recompute(item)


def _restock_return_inventory(db, sale):
    # First validate outbound EXCHANGE stock (decrements like a sale).
    outbound = [ln for ln in sale["_lines"] if ln.get("return_of_line_no") is None]
    out_items = []
    for ln in outbound:
        item = find_item(db, sale["store_id"], ln["product_id"])
        if item is None or item["available_qty"] < ln["quantity"]:
            raise err(ERR_INSUFFICIENT_STOCK, "Insufficient stock for exchange outbound line")
        out_items.append((item, ln["quantity"]))
    # Restock returned units.
    for ln in sale["_lines"]:
        if ln.get("return_of_line_no") is not None:
            item = find_item(db, sale["store_id"], ln["product_id"])
            if item is not None:
                item["on_hand_qty"] += ln["quantity"]
                recompute(item)
    # Decrement outbound exchange lines.
    for item, qty in out_items:
        item["on_hand_qty"] -= qty
        recompute(item)


def _earn_loyalty(db, sale):
    account = None
    if sale.get("loyalty_account_id"):
        account = db.loyalty_accounts.get(sale["loyalty_account_id"])
    store = db.stores[sale["store_id"]]

    # Debit redeemed points first (PRD §3.5: redeemed points debited).
    redeemed = sale.get("loyalty_redeemed_cents", 0)
    if account is not None and redeemed > 0:
        account["points_balance"] -= redeemed

    points = 0
    if account is not None:
        # tier at settlement time governs the multiplier (PRD §3.8); snapshot it
        # so a later partial-return clawback uses the same tier.
        settle_tier = account["tier"]
        sale["_settle_tier"] = settle_tier
        net = eligible_net(_pricing_inputs(sale["_lines"]), sale["_line_net_alloc"])
        base = (net * store["loyalty_earn_rate_bps"]) // 10000
        points = apply_tier_multiplier(base, settle_tier)
        account["points_balance"] += points
        account["lifetime_points"] += points
        recompute_tier(account)
        touch(account)
    sale["points_earned"] = points


def _reverse_loyalty_for_return(db, sale):
    """Clawback for RETURN/EXCHANGE settlement (PRD §3.8): points earned for the
    returned units are debited from points_balance only (lifetime untouched);
    redeemed points proportional to the returned units are restored."""
    original = db.sales.get(sale.get("original_sale_id"))
    if original is None:
        return
    account = None
    if original.get("loyalty_account_id"):
        account = db.loyalty_accounts.get(original["loyalty_account_id"])
    if account is None:
        return
    return_lines = [ln for ln in sale["_lines"] if ln.get("return_of_line_no") is not None]

    # Points earned attributable to returned units = original earned minus the
    # earned recomputed without the returned units (delta method).
    earned_for_returned = _earned_delta(db, original, return_lines)
    # Redeemed points restored = original redeemed minus redeemed-without-returned.
    redeemed_restored = _redeemed_delta(db, original, return_lines)

    account["points_balance"] -= earned_for_returned
    account["points_balance"] += redeemed_restored
    if account["points_balance"] < 0:
        account["points_balance"] = 0
    # lifetime_points untouched -> tier never downgrades; recompute is a no-op
    # on lifetime but keep it consistent.
    recompute_tier(account)
    touch(account)
    sale["points_earned"] = -earned_for_returned


def _earned_for_lines(db, store, lines, line_net_alloc, tier):
    net = eligible_net(lines, line_net_alloc)
    base = (net * store["loyalty_earn_rate_bps"]) // 10000
    return apply_tier_multiplier(base, tier)


def _earned_delta(db, original, return_lines):
    """Original points earned minus points earned on the reduced basket, using
    the tier snapshotted when the original sale settled."""
    tier = original.get("_settle_tier", "STANDARD")
    store = db.stores[original["store_id"]]

    orig_result = _original_pricing(db, original)
    orig_inputs = _pricing_inputs(original["_lines"])
    orig_earned = _earned_for_lines(db, store, orig_inputs,
                                    orig_result["line_net_alloc"], tier)

    reduced = _reduced_pricing(db, original, return_lines)
    if reduced is None:
        reduced_earned = 0
    else:
        reduced_inputs = _reduced_inputs(original, return_lines)
        reduced_earned = _earned_for_lines(db, store, reduced_inputs,
                                           reduced["line_net_alloc"], tier)
    return orig_earned - reduced_earned


def _redeemed_delta(db, original, return_lines):
    orig_result = _original_pricing(db, original)
    reduced = _reduced_pricing(db, original, return_lines)
    orig_redeem = orig_result["loyalty_redeemed_cents"]
    reduced_redeem = reduced["loyalty_redeemed_cents"] if reduced else 0
    return orig_redeem - reduced_redeem


def _reduced_inputs(original, return_lines):
    reduce_by = {}
    for rl in return_lines:
        ln_no = rl["return_of_line_no"]
        reduce_by[ln_no] = reduce_by.get(ln_no, 0) + rl["quantity"]
    inputs = []
    for ln in original["_lines"]:
        remaining = ln["quantity"] - reduce_by.get(ln["line_no"], 0)
        if remaining <= 0:
            continue
        inputs.append({
            "list_price_cents": ln["list_price_cents"],
            "quantity": remaining,
            "tax_exempt": ln["tax_exempt"],
            "loyalty_eligible": ln["loyalty_eligible"],
        })
    return inputs


def _apply_cash_movement(db, sale):
    """Update the bound session's expected_cash_cents by net CASH movement at
    settlement (PRD §3.5). expected_cash is otherwise derivable; we keep a
    running figure that is also recomputable from settled-sale cash tenders."""
    session = db.cash_sessions.get(sale.get("cash_session_id"))
    if session is None:
        return
    _recompute_expected_cash(db, session)


def _recompute_expected_cash(db, session):
    """expected_cash_cents from opening float + cash on SETTLED bound sales
    (calc E / PRD §3.2)."""
    expected = session["opening_float_cents"]
    for sale in db.sales.values():
        if sale.get("cash_session_id") != session["id"]:
            continue
        if sale["settlement_status"] != "SETTLED":
            continue
        for tid in sale.get("_tenders", []):
            t = db.tender_lines.get(tid)
            if t is None or t["method"] != "CASH":
                continue
            if t["amount_cents"] > 0:
                expected += t["amount_cents"]
                expected -= t["change_due_cents"]
            elif t["amount_cents"] < 0:
                expected += t["amount_cents"]  # negative reduces drawer
    session["expected_cash_cents"] = expected


# ----- Void / reversal (PRD §3.5, §2.10) -----------------------------------

def void_sale(db, sale):
    """Void a non-SETTLED sale: reverse tenders via compensating lines, release
    reservations/commitments (none placed pre-settlement), restore loyalty
    redemption (none debited pre-settlement). Sets settlement_status VOIDED."""
    _reverse_tenders(db, sale)
    sale["settlement_status"] = "VOIDED"
    session = db.cash_sessions.get(sale.get("cash_session_id"))
    if session is not None:
        _recompute_expected_cash(db, session)


def _reverse_tenders(db, sale):
    """Append a compensating TenderLine for each captured tender (PRD §2.10)."""
    from common import stamp_create  # not used; tenders have minimal fields
    existing = list(sale.get("_tenders", []))
    for tid in existing:
        t = db.tender_lines.get(tid)
        if t is None or t.get("_reversal"):
            continue
        comp = _make_tender(db, sale, t["method"], -t["amount_cents"], 0,
                            reversal=True)
        sale["_tenders"].append(comp["id"])


def _make_tender(db, sale, method, amount_cents, change_due_cents, reversal=False):
    from db import new_id, now_iso
    tender = {
        "id": new_id(),
        "sale_id": sale["id"],
        "method": method,
        "amount_cents": amount_cents,
        "change_due_cents": change_due_cents,
        "created_at": now_iso(),
        "_seq": db.next_seq(),
        "_reversal": reversal,
    }
    db.tender_lines[tender["id"]] = tender
    return tender
