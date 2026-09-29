"""Multi-level cascades: competitor lifecycle, price execution, market posture,
signage/print-batch selection (PRD 3.4, 3.5, 3.7, 3.9, 3.10)."""
import db
from services import calc
from util import round_half_up, utc_date
import clock


# ------------------------------------------------------------- observations

def void_active_observations(link, void_reason):
    """Move every ACTIVE observation on a link to VOIDED with the given reason."""
    changed = []
    for obs in db.ordered(db.observations):
        if obs["link_id"] != link["id"]:
            continue
        if obs["status"] != "ACTIVE":
            continue
        obs["status"] = "VOIDED"
        obs["void_reason"] = void_reason
        db.touch(obs)
        changed.append(obs)
    return changed


def reelect(link):
    """Re-run the effective-price election, registering a mutation when it moves."""
    if calc.elect_effective_price(link):
        db.touch(link)
        return True
    return False


# ------------------------------------------------------------------ signage

def release_signage(order):
    """QUEUED -> RELEASED: give the printer slot back (PRD 3.5, 3.6, 3.9, 3.10)."""
    if order.get("signage_status") != "QUEUED":
        return False
    order["signage_status"] = "RELEASED"
    batch_id = order.get("label_batch_id")
    order["label_batch_id"] = None
    if batch_id is not None:
        batch = db.batches.get(batch_id)
        if batch is not None and order["id"] in batch["queued_order_ids"]:
            batch["queued_order_ids"] = [oid for oid in batch["queued_order_ids"]
                                         if oid != order["id"]]
            db.touch(batch)
    return True


def label_batch_selection(order):
    """PRD 3.10: run on approval; never fails, may leave the label unbatched."""
    store_id = order.get("signage_store_id")
    if store_id is None:
        return None
    order["signage_status"] = "QUEUED"
    store = db.stores.get(store_id)
    if store is None:
        return None
    from services import ledger
    if ledger.label_slots_remaining_today(store) < 1:
        return None
    instant = clock.now()
    candidates = [b for b in db.batches.values()
                  if b["store_id"] == store_id
                  and b["status"] == "SCHEDULED"
                  and b["window_end"] > instant]
    if not candidates:
        return None
    candidates.sort(key=lambda b: (b["window_start"], b["created_at"], b["_seq"]))
    batch = candidates[0]
    batch["queued_order_ids"] = list(batch["queued_order_ids"]) + [order["id"]]
    db.touch(batch)
    order["label_batch_id"] = batch["id"]
    return batch


# ------------------------------------------------- competitor status cascades

def suspend_competitor(competitor, suspension_reason):
    """ACTIVE -> SUSPENDED, tearing down the collected intelligence (PRD 3.4)."""
    competitor["status"] = "SUSPENDED"
    competitor["suspension_reason"] = suspension_reason
    db.touch(competitor)
    for link in calc.competitor_links(competitor["id"]):
        if link["status"] != "CONFIRMED":
            continue
        link["status"] = "UNDER_REVIEW"
        link["review_round"] = link["review_round"] + 1
        db.touch(link)
        void_active_observations(link, "COMPETITOR_SUSPENDED")
        calc.elect_effective_price(link)
    return competitor


def retire_competitor(competitor, void_observations):
    """ACTIVE/SUSPENDED -> RETIRED, rejecting the whole match population."""
    competitor["status"] = "RETIRED"
    db.touch(competitor)
    for link in calc.competitor_links(competitor["id"]):
        if link["status"] not in ("PROPOSED", "UNDER_REVIEW", "CONFIRMED"):
            continue
        link["status"] = "REJECTED"
        db.touch(link)
        if void_observations:
            void_active_observations(link, "COMPETITOR_RETIRED")
            # PRD 3.3: the election is re-run inside the competitor
            # suspension and retirement cascades.
            calc.elect_effective_price(link)
    return competitor


# ------------------------------------------------------ price execute cascade

def execute_order(order, product, rule):
    """The depth-5 cascade of PRD 3.7; every level applied in order."""
    instant = clock.now()

    # ---- level 1: the order executes and the product is repriced
    order["status"] = "EXECUTED"
    db.touch(order)
    product["own_price_cents"] = order["proposed_price_cents"]
    product["last_price_change_at"] = instant
    db.touch(product)

    # ---- level 2: confirmed matches on this product recompute their gap
    went_stale = []
    for link in db.ordered(db.links):
        if link["product_id"] != product["id"]:
            continue
        if link["status"] != "CONFIRMED":
            continue
        effective = link.get("latest_effective_price_cents")
        if effective is None:
            continue
        link["gap_bp"] = round_half_up(product["own_price_cents"] * 10000, effective)
        if abs(link["gap_bp"] - 10000) > calc.MATCH_DRIFT_ALERT_BP:
            link["gap_stale"] = True
            went_stale.append(link)
        db.touch(link)

    # ---- level 3: competitors owning a newly stale match recompute their drift
    seen = []
    for link in went_stale:
        if link["competitor_id"] not in seen:
            seen.append(link["competitor_id"])
    for competitor_id in seen:
        competitor = db.competitors.get(competitor_id)
        if competitor is None or competitor["status"] != "ACTIVE":
            continue
        if calc.confirmed_match_count(competitor_id) < 1:
            continue
        if calc.stale_share_bp(competitor_id) < calc.COMPETITOR_STALE_SHARE_LIMIT_BP:
            continue
        # ---- levels 4 and 5 live inside the drift auto-suspend body
        suspend_competitor(competitor, "MATCH_DRIFT_AUTO_SUSPEND")
    return order


# ----------------------------------------------------- market posture cascade

def recompute_market_posture(market):
    """PRD 3.5: reselect the governing report, recompute posture, cascade."""
    fields = calc.market_posture_fields(market)
    market["observed_index_bp"] = fields["observed_index_bp"]
    market["positioning_gap_bp"] = fields["positioning_gap_bp"]
    market["insufficient_data_report_count"] = fields["insufficient_data_report_count"]
    market["pricing_posture"] = fields["pricing_posture"]
    db.touch(market)
    if fields["pricing_posture"] == "FROZEN":
        _freeze_market(market)
    else:
        _unfreeze_market(market)
    return market


def _freeze_market(market):
    for order in db.ordered(db.orders):
        if order["market_id"] != market["id"]:
            continue
        if order["status"] not in ("DRAFT", "PENDING_APPROVAL", "APPROVED"):
            continue
        was_approved = order["status"] == "APPROVED"
        order["status"] = "SUSPENDED"
        if was_approved:
            release_signage(order)
        db.touch(order)
    for policy in db.ordered(db.policies):
        if policy["market_id"] != market["id"]:
            continue
        if policy["status"] != "ACTIVE":
            continue
        policy["status"] = "SUSPENDED"
        db.touch(policy)


def _unfreeze_market(market):
    """PRD 3.5: a later publication landing OPEN/RESTRICTED thaws the orders."""
    for order in db.ordered(db.orders):
        if order["market_id"] != market["id"]:
            continue
        if order["status"] != "SUSPENDED":
            continue
        order["status"] = "DRAFT"
        db.touch(order)


# ----------------------------------------------------------- order supersede

def supersede_order(order):
    """PRD 3.6: terminal SUPERSEDED, releasing a queued label from DRAFT/APPROVED."""
    from_status = order["status"]
    order["status"] = "SUPERSEDED"
    if from_status in ("DRAFT", "APPROVED", "SUSPENDED"):
        release_signage(order)
    db.touch(order)
    return order


# ------------------------------------------------------------ batch cascades

def complete_batch(batch):
    """PRD 3.10: queued labels become PRINTED; order status is untouched."""
    batch["status"] = "COMPLETED"
    db.touch(batch)
    for order_id in list(batch["queued_order_ids"]):
        order = db.orders.get(order_id)
        if order is None:
            continue
        if order.get("signage_status") != "QUEUED":
            continue
        order["signage_status"] = "PRINTED"
        db.touch(order)
    return batch


def cancel_batch(batch, cancel_reason):
    """PRD 3.10: release every queued label and give all the slots back."""
    batch["status"] = "CANCELLED"
    batch["cancel_reason"] = cancel_reason
    for order_id in list(batch["queued_order_ids"]):
        order = db.orders.get(order_id)
        if order is None:
            continue
        if order.get("signage_status") == "QUEUED":
            order["signage_status"] = "RELEASED"
            order["label_batch_id"] = None
            db.touch(order)
    batch["queued_order_ids"] = []
    db.touch(batch)
    return batch


def batch_window_conflict(store_id, window_start, window_end, buffer_minutes):
    """PRD 3.10 buffered window rule; a gap of exactly the buffer is accepted."""
    from datetime import timedelta
    buffer = timedelta(minutes=buffer_minutes)
    for other in db.batches.values():
        if other["store_id"] != store_id:
            continue
        if other["status"] not in ("SCHEDULED", "PRINTING", "COMPLETED"):
            continue
        starts_clear = window_start >= other["window_end"] + buffer
        ends_clear = window_end <= other["window_start"] - buffer
        if not (starts_clear or ends_clear):
            return True
    return False


def effective_window_overlap(product_id, effective_from, effective_until,
                             exclude_order_id=None):
    """PRD 3.6: half-open [from, until) intervals against live orders."""
    for other in db.orders.values():
        if other["product_id"] != product_id:
            continue
        if exclude_order_id is not None and other["id"] == exclude_order_id:
            continue
        if other["status"] not in ("DRAFT", "PENDING_APPROVAL", "APPROVED", "EXECUTED"):
            continue
        other_from = other["effective_from"]
        other_until = other["effective_until"]
        if effective_until is not None and effective_until <= other_from:
            continue
        if other_until is not None and other_until <= effective_from:
            continue
        return True
    return False


def utc_day(instant):
    return utc_date(instant)
