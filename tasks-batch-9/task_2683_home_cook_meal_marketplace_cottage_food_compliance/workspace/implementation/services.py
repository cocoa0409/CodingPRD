"""Cross-entity side effects: recomputations and the two synchronous cascades."""
from core import db, parse_date, touch
import calc


# ---------------------------------------------------------------- pickup hubs
def recompute_hub(hub):
    """PRD 3.4: assigned_order_count and status are pure functions of occupancy."""
    count = calc.hub_assigned_count(hub)
    status = "CLOSED" if count >= int(hub["slot_capacity_orders"]) else "OPEN"
    if count != int(hub["assigned_order_count"]) or status != hub["status"]:
        hub["assigned_order_count"] = count
        hub["status"] = status
        touch(hub)


def recompute_hub_by_id(hub_id):
    hub = db.hubs.get(hub_id)
    if hub is not None:
        recompute_hub(hub)


# ------------------------------------------------------------ menu item labels
def compute_label_status(item, policy):
    required = set(policy["label_required_fields"])
    declared = set(item["label_fields"])
    return "COMPLIANT" if required.issubset(declared) else "MISSING_FIELDS"


def refresh_label_status(item):
    cook = db.cooks[item["cook_id"]]
    policy = calc.policy_for_cook(cook)
    status = compute_label_status(item, policy)
    if status != item["label_compliance_status"]:
        item["label_compliance_status"] = status
    return status


# ------------------------------------------------------------- cook money state
def recompute_cook_money(cook, run_cap_cascade=True):
    policy = calc.policy_for_cook(cook)
    recognised, reversed_amount = calc.recognised_amounts(cook["id"])
    cottage = recognised - reversed_amount
    pending = calc.pending_payout(cook["id"])
    paid = calc.lifetime_paid(cook["id"])
    new_cap = calc.cap_status_for(cottage, int(policy["cottage_food_annual_cap_cents"]))
    previous_cap = cook["cap_status"]

    changed = (
        int(cook["ytd_gross_sales_cents"]) != recognised
        or int(cook["ytd_cottage_revenue_cents"]) != cottage
        or int(cook["pending_payout_cents"]) != pending
        or int(cook["lifetime_paid_cents"]) != paid
        or previous_cap != new_cap
    )
    cook["ytd_gross_sales_cents"] = recognised
    cook["ytd_cottage_revenue_cents"] = cottage
    cook["pending_payout_cents"] = pending
    cook["lifetime_paid_cents"] = paid
    cook["cap_status"] = new_cap
    if changed:
        touch(cook)
    if run_cap_cascade and new_cap == "CAP_REACHED" and previous_cap != "CAP_REACHED":
        cap_reached_cascade(cook)


def cap_reached_cascade(cook):
    """PRD 3.2: the cap event delists approved items and bounces items in review."""
    for item in calc.ordered_items(cook["id"]):
        if item["review_status"] == "APPROVED":
            item["review_status"] = "DELISTED"
            item["delist_reason"] = "CAP_REACHED"
            touch(item)
        elif item["review_status"] == "UNDER_REVIEW":
            rounds = int(item["revision_round"])
            item["review_status"] = "REVISION_REQUESTED" if rounds < 2 else "REJECTED"
            item["revision_round"] = rounds + 1
            touch(item)


# ------------------------------------------------------- order level operations
def cancel_order(order, cancelled_reason):
    """Shared by diner cancellation and by both cascades."""
    order["fulfillment_status"] = "CANCELLED"
    order["cancelled_reason"] = cancelled_reason
    if order["payment_status"] == "AUTHORIZED":
        order["payment_status"] = "VOIDED"
    touch(order)
    window = db.windows.get(order["production_window_id"])
    if window is not None:
        window["committed_meals"] = int(window["committed_meals"]) - int(order["quantity"])
        calc.derive_window_capacity(window)
        touch(window)
    if order["pickup_hub_id"]:
        recompute_hub_by_id(order["pickup_hub_id"])


def capture_order(order):
    order["payment_status"] = "CAPTURED"
    order["captured_at"] = db.now_iso()
    order["effective_year"] = db.now().year
    touch(order)


# ------------------------------------------------------------- CASCADE A (3.7)
def suspension_cascade(cook):
    """Runs after the cook's standing has already been written to SUSPENDED."""
    for item in calc.ordered_items(cook["id"]):
        if item["review_status"] == "APPROVED":
            item["review_status"] = "DELISTED"
            item["delist_reason"] = "COOK_SUSPENDED"
            touch(item)
    for window in calc.ordered_windows(cook["id"]):
        if window["status"] not in ("OPEN", "CUTOFF_PASSED"):
            continue
        window["status"] = "CANCELLED"
        window["cancelled_reason"] = "NO_APPROVED_MENU"
        touch(window)
        for order in calc.ordered_window_orders(window["id"]):
            if order["fulfillment_status"] in ("PLACED", "ROUTED"):
                cancel_order(order, "WINDOW_CANCELLED")
    recompute_cook_money(cook, run_cap_cascade=False)


# ------------------------------------------------------------- CASCADE B (3.3)
def window_close_cascade(window):
    window["closed_at"] = db.now_iso()
    for order in calc.ordered_window_orders(window["id"]):
        if order["fulfillment_status"] == "HANDED_OFF" and order["payment_status"] == "AUTHORIZED":
            capture_order(order)
    cook = db.cooks.get(window["cook_id"])
    if cook is not None:
        recompute_cook_money(cook)


# ---------------------------------------------------- onboarding re-evaluation
def reevaluate_onboarding(cook):
    """PRD 3.1: the two system-driven edges of the onboarding dimension."""
    if cook["onboarding_status"] != "DOCS_SUBMITTED":
        return
    policy = calc.policy_for_cook(cook)
    allowed = policy["allowed_kitchen_types"]
    today = db.now().date()
    docs = calc.cook_documents(cook["id"])

    cert_ok = False
    for d in docs:
        if d["doc_type"] != "FOOD_HANDLER_CERT" or d["review_status"] != "VERIFIED":
            continue
        expires = parse_date(d.get("expires_on"))
        if expires is not None and expires > today:
            cert_ok = True

    graded = [
        d
        for d in docs
        if d["doc_type"] == "KITCHEN_INSPECTION" and d["review_status"] in ("PASSED", "WAIVED")
    ]
    inspection_ok = any(d.get("kitchen_type_claimed") in allowed for d in graded)

    if cert_ok and inspection_ok:
        newest = sorted(graded, key=lambda d: (d["created_at"], d["_seq"]), reverse=True)[0]
        cook["onboarding_status"] = "VERIFIED"
        cook["verified_kitchen_type"] = newest.get("kitchen_type_claimed")
        touch(cook)
        return

    live = [d for d in docs if d["review_status"] in ("SUBMITTED", "VERIFIED", "PASSED", "WAIVED")]
    if not live:
        cook["onboarding_status"] = "DRAFT"
        cook["verified_kitchen_type"] = None
        touch(cook)


# ------------------------------------------------------- safety score plumbing
def apply_safety_score(cook, allow_standing_moves=True):
    """Recompute the authoritative score and let it drive the standing dimension."""
    score = calc.safety_score(cook["id"])
    changed = int(cook["safety_score"]) != score
    cook["safety_score"] = score
    suspended = False
    if allow_standing_moves:
        band = calc.standing_band(score)
        standing = cook["compliance_standing"]
        if standing == "CLEAR" and band == "WARNED":
            cook["compliance_standing"] = "WARNED"
            cook["standing_reason"] = "SAFETY_SCORE_WARN"
            changed = True
        elif standing in ("CLEAR", "WARNED") and band == "SUSPENDED":
            cook["compliance_standing"] = "SUSPENDED"
            cook["standing_reason"] = "SAFETY_SCORE_SUSPEND"
            changed = True
            suspended = True
    if changed:
        touch(cook)
    if suspended:
        suspension_cascade(cook)


def reevaluate_all_safety_scores():
    """PRD 2.5 / 3.7: the one retroactive effect of moving the logical clock."""
    for cook in sorted(db.cooks.values(), key=lambda c: (c["created_at"], c["_seq"])):
        score = calc.safety_score(cook["id"])
        changed = int(cook["safety_score"]) != score
        cook["safety_score"] = score
        if cook["compliance_standing"] == "WARNED" and score >= 80:
            cook["compliance_standing"] = "CLEAR"
            cook["standing_reason"] = None
            changed = True
        if changed:
            touch(cook)


def reevaluate_revert(cook):
    """PRD 3.1: the revert edge alone, re-evaluated after a superseding write."""
    if cook["onboarding_status"] != "DOCS_SUBMITTED":
        return
    docs = calc.cook_documents(cook["id"])
    live = [d for d in docs if d["review_status"] in ("SUBMITTED", "VERIFIED", "PASSED", "WAIVED")]
    if not live:
        cook["onboarding_status"] = "DRAFT"
        cook["verified_kitchen_type"] = None
        touch(cook)
