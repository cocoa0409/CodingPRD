"""Shared domain helpers: identity/versioning, projections, cycles, ledger, cascades."""
from decimal import Decimal

import clock
import db
from errors import ApiError

GALLON_Q = 3


# ------------------------------------------------------------------ identity

def new_entity(with_common=True):
    record = {"id": db.new_id(), "created_at": clock.now(), "_seq": db.next_seq()}
    if with_common:
        record["updated_at"] = record["created_at"]
        record["version"] = 1
    return record


def bump(entity):
    """PRD 2.8: one mutation == one version step + refreshed updated_at."""
    entity["version"] = entity.get("version", 1) + 1
    entity["updated_at"] = clock.now()
    return entity


def order_key(entity):
    return (entity["created_at"], entity["_seq"])


def by_created(items):
    return sorted(items, key=order_key)


# ------------------------------------------------------------------ existence

_NOT_FOUND = {
    "banners": "ERR_BANNER_NOT_FOUND",
    "sites": "ERR_SITE_NOT_FOUND",
    "households": "ERR_HOUSEHOLD_NOT_FOUND",
    "members": "ERR_MEMBER_NOT_FOUND",
    "household_links": "ERR_HOUSEHOLD_LINK_NOT_FOUND",
    "promo_events": "ERR_PROMO_EVENT_NOT_FOUND",
    "point_cycles": "ERR_POINT_CYCLE_NOT_FOUND",
    "purchase_transactions": "ERR_PURCHASE_TRANSACTION_NOT_FOUND",
    "ledger_entries": "ERR_LEDGER_ENTRY_NOT_FOUND",
    "fuel_redemptions": "ERR_FUEL_REDEMPTION_NOT_FOUND",
    "settlement_batches": "ERR_SETTLEMENT_BATCH_NOT_FOUND",
    "point_disputes": "ERR_POINT_DISPUTE_NOT_FOUND",
    "fraud_signals": "ERR_FRAUD_SIGNAL_NOT_FOUND",
}


def fetch(collection_name, entity_id):
    table = getattr(db, collection_name)
    if not isinstance(entity_id, str) or entity_id not in table:
        raise ApiError(_NOT_FOUND[collection_name],
                       "%s '%s' does not exist" % (collection_name[:-1], entity_id))
    return table[entity_id]


# ------------------------------------------------------------------ versioning guards

def check_version(entity, expected, label, error_id):
    """PRD 2.9: OCC on the PARENT entity only (member on redemptions, site on batches)."""
    if expected != entity["version"]:
        raise ApiError(error_id,
                       "expected_%s_version %s does not match stored version %s"
                       % (label, expected, entity["version"]))


# ------------------------------------------------------------------ ledger

def member_entries(member_id):
    rows = [e for e in db.ledger_entries.values() if e["member_id"] == member_id]
    return by_created(rows)


def available_points(member_id):
    """Sum of every points_delta ever written for the member. MAY be negative."""
    return sum(e["points_delta"] for e in db.ledger_entries.values()
               if e["member_id"] == member_id)


def lifetime_points(member_id):
    return sum(e["points_delta"] for e in db.ledger_entries.values()
               if e["member_id"] == member_id and e["entry_type"] in ("ACCRUAL", "REVERSAL"))


def add_entry(member_id, point_cycle_id, entry_type, points_delta,
              source_kind, source_ref_id, lot_expires_at=None, memo=None):
    if points_delta == 0:
        return None
    entry = new_entity(with_common=False)
    entry.update({
        "member_id": member_id,
        "point_cycle_id": point_cycle_id,
        "entry_type": entry_type,
        "points_delta": points_delta,
        "lot_expires_at": lot_expires_at if points_delta > 0 else None,
        "source_kind": source_kind,
        "source_ref_id": source_ref_id,
        "memo": memo,
    })
    db.ledger_entries[entry["id"]] = entry
    return entry


# ------------------------------------------------------------------ cycles

def month_after(cycle_month):
    year = int(cycle_month[:4])
    month = int(cycle_month[5:7]) + 1
    if month == 13:
        year, month = year + 1, 1
    return "%04d-%02d" % (year, month)


def cycles_of(banner_id):
    return sorted([c for c in db.point_cycles.values() if c["banner_id"] == banner_id],
                  key=lambda c: (c["cycle_month"], c["created_at"], c["_seq"]))


def open_cycle(banner_id):
    """The banner's OPEN cycle whose window contains the logical clock."""
    now = clock.now()
    for cycle in cycles_of(banner_id):
        if cycle["status"] == "OPEN" and cycle["opens_at"] <= now <= cycle["closes_at"]:
            return cycle
    return None


def require_open_cycle(banner_id):
    cycle = open_cycle(banner_id)
    if cycle is None:
        raise ApiError("ERR_CYCLE_NOT_OPEN",
                       "no OPEN PointCycle of the governing banner contains the current instant")
    return cycle


def cycle_for_clock(banner_id):
    """Best-effort cycle attribution when no OPEN-cycle guard applies."""
    cycle = open_cycle(banner_id)
    if cycle is not None:
        return cycle
    now = clock.now()
    for candidate in cycles_of(banner_id):
        if candidate["opens_at"] <= now <= candidate["closes_at"]:
            return candidate
    return None


def cycle_by_month(banner_id, cycle_month):
    for cycle in cycles_of(banner_id):
        if cycle["cycle_month"] == cycle_month:
            return cycle
    return None


def require_next_cycle(cycle):
    nxt = cycle_by_month(cycle["banner_id"], month_after(cycle["cycle_month"]))
    if nxt is None:
        raise ApiError("ERR_NEXT_CYCLE_NOT_DEFINED",
                       "no PointCycle exists for the month following %s" % cycle["cycle_month"])
    return nxt


# ------------------------------------------------------------------ links / households

def links_of_member(member_id, statuses=None):
    rows = [l for l in db.household_links.values() if l["member_id"] == member_id]
    if statuses is not None:
        rows = [l for l in rows if l["status"] in statuses]
    return by_created(rows)


def links_of_household(household_id, statuses=None):
    rows = [l for l in db.household_links.values() if l["household_id"] == household_id]
    if statuses is not None:
        rows = [l for l in rows if l["status"] in statuses]
    return by_created(rows)


def households_of_member(member_id):
    return [db.households[l["household_id"]] for l in links_of_member(member_id, ("ACTIVE",))]


def assert_no_frozen_household(member_id):
    """PRD 2.10 step 11."""
    for household in households_of_member(member_id):
        if household["status"] != "ACTIVE":
            raise ApiError("ERR_HOUSEHOLD_FROZEN",
                           "household %s is FROZEN" % household["id"])


def link_is_cross_banner(link):
    household = db.households.get(link["household_id"])
    member = db.members.get(link["member_id"])
    if household is None or member is None:
        return False
    return household["banner_id"] != member["banner_id"]


def household_linked_member_count(household_id):
    return len(links_of_household(household_id, ("ACTIVE",)))


def household_cross_banner_member_ids(household):
    ids = []
    for link in links_of_household(household["id"], ("ACTIVE",)):
        member = db.members.get(link["member_id"])
        if member is not None and member["banner_id"] != household["banner_id"]:
            if member["id"] not in ids:
                ids.append(member["id"])
    return ids


def household_aggregate_available_points(household_id):
    total = 0
    for link in links_of_household(household_id, ("ACTIVE",)):
        total += available_points(link["member_id"])
    return total


def open_signals(household_id):
    rows = [s for s in db.fraud_signals.values()
            if s["household_id"] == household_id and s["status"] == "OPEN"]
    return by_created(rows)


def household_fraud_score(household):
    """Dual-variant calculation household_fraud_score."""
    banner = db.banners.get(household["banner_id"])
    signals = open_signals(household["id"])
    mode = banner["fraud_scoring_mode"] if banner else "INSTANTANEOUS"
    if mode == "INSTANTANEOUS":
        return sum(s["severity_weight"] for s in signals)
    now = clock.now()
    total = Decimal(0)
    for signal in signals:
        elapsed = (now - signal["detected_at"]).total_seconds()
        days_open = int(elapsed // 86400)
        if days_open < 0:
            days_open = 0
        decay = Decimal(1) - Decimal("0.05") * days_open
        if decay < Decimal("0.25"):
            decay = Decimal("0.25")
        total += Decimal(signal["severity_weight"]) * decay
    return clock.rhu_int(total)


def evaluate_auto_freeze(household):
    """Shared tail of household_fraud_score: freeze at/over threshold, never thaw."""
    banner = db.banners.get(household["banner_id"])
    if banner is None:
        return False
    score = household_fraud_score(household)
    if score >= banner["freeze_threshold_score"] and household["status"] == "ACTIVE":
        household["status"] = "FROZEN"
        household["frozen_reason"] = "AUTO_FRAUD_SCORE"
        household["frozen_at"] = clock.now()
        return True
    return False


def raise_system_signal(household, signal_type, severity_weight):
    signal = new_entity()
    signal.update({
        "household_id": household["id"],
        "signal_type": signal_type,
        "severity_weight": severity_weight,
        "status": "OPEN",
        "source": "SYSTEM",
        "detected_at": clock.now(),
        "cleared_at": None,
        "cleared_by_user_id": None,
    })
    db.fraud_signals[signal["id"]] = signal
    evaluate_auto_freeze(household)
    bump(household)
    return signal


# ------------------------------------------------------------------ site projections

def redemptions_of_site(site_id):
    return by_created([r for r in db.fuel_redemptions.values() if r["site_id"] == site_id])


def site_unbatched(site_id):
    gallons = Decimal(0)
    cents = 0
    for redemption in db.fuel_redemptions.values():
        if redemption["site_id"] != site_id:
            continue
        if redemption["settlement_status"] != "PENDING":
            continue
        if redemption["gallons_dispensed"] is not None:
            gallons += redemption["gallons_dispensed"]
        cents += redemption["discount_amount_cents"] or 0
    return clock.rhu(gallons, GALLON_Q), cents


def site_settlement_balance_cents(site_id):
    total = 0
    for batch in db.settlement_batches.values():
        if batch["site_id"] == site_id and batch["status"] == "APPROVED":
            total += batch["reimbursement_cents"] or 0
    return total


# ------------------------------------------------------------------ lots / expiry

def lot_remainders(member_id, expiry_basis):
    """Drain the member's credit lots by the configured ordering.

    Returns a list of (entry, remainder) pairs in draining order.
    """
    entries = member_entries(member_id)
    credits = [e for e in entries if e["points_delta"] > 0]
    consumption = sum(-e["points_delta"] for e in entries if e["points_delta"] < 0)

    dated = [e for e in credits if e["lot_expires_at"] is not None]
    undated = [e for e in credits if e["lot_expires_at"] is None]
    if expiry_basis == "LOT_FIFO":
        dated.sort(key=lambda e: (e["lot_expires_at"], e["created_at"], e["_seq"]))
        undated.sort(key=lambda e: (e["created_at"], e["_seq"]))
        ordered = dated + undated                      # nulls LAST
    else:                                              # CYCLE_SCOPED
        dated.sort(key=lambda e: (e["lot_expires_at"], e["created_at"], e["_seq"]),
                   reverse=True)
        undated.sort(key=lambda e: (e["created_at"], e["_seq"]), reverse=True)
        ordered = undated + dated                      # nulls FIRST

    result = []
    remaining_consumption = consumption
    for entry in ordered:
        take = min(entry["points_delta"], remaining_consumption)
        remaining_consumption -= take
        result.append((entry, entry["points_delta"] - take))
    return result


def earliest_unconsumed_lot_expiry(member_id, expiry_basis):
    best = None
    for entry, remainder in lot_remainders(member_id, expiry_basis):
        if remainder <= 0 or entry["lot_expires_at"] is None:
            continue
        if best is None or entry["lot_expires_at"] < best:
            best = entry["lot_expires_at"]
    return best


def rollover_eligible(member_id):
    """An ACTIVE linkage to an ACTIVE household carrying zero OPEN fraud signals."""
    for link in links_of_member(member_id, ("ACTIVE",)):
        household = db.households.get(link["household_id"])
        if household is None or household["status"] != "ACTIVE":
            continue
        if not open_signals(household["id"]):
            return True
    return False


def sweep_amounts(member, banner, cycle):
    """point_expiry_sweep, evaluation only (no ledger writes)."""
    expiring_remainder = 0
    for entry, remainder in lot_remainders(member["id"], banner["expiry_basis"]):
        if remainder <= 0:
            continue
        if entry["lot_expires_at"] is not None and entry["lot_expires_at"] <= cycle["closes_at"]:
            expiring_remainder += remainder
    if expiring_remainder <= 0:
        return 0, 0, 0
    if rollover_eligible(member["id"]):
        rolled_over = min(expiring_remainder, banner["rollover_cap_points"])
    else:
        rolled_over = 0
    expired = expiring_remainder - rolled_over
    return expiring_remainder, rolled_over, expired


# ------------------------------------------------------------------ cascades

def release_points(redemption, member, new_status, reason_cycle_id=None):
    """AUTHORIZED -> VOIDED | SUPERSEDED: release the debited points, bump both records."""
    redemption["authorization_status"] = new_status
    bump(redemption)
    if reason_cycle_id is not None:
        cycle_id = reason_cycle_id
    else:
        cycle = cycle_for_clock(member["banner_id"])
        cycle_id = cycle["id"] if cycle else None
    entry = add_entry(member["id"], cycle_id, "REDEMPTION_RELEASE",
                      redemption["points_debited_at_auth"], "FUEL_REDEMPTION",
                      redemption["id"])
    if entry is not None:
        bump(member)
    return redemption


def void_redemption(redemption, member, reason_cycle_id=None):
    return release_points(redemption, member, "VOIDED", reason_cycle_id)


def supersede_redemption(redemption, member, reason_cycle_id=None):
    return release_points(redemption, member, "SUPERSEDED", reason_cycle_id)


def repair_overdraw(member, cycle_id=None):
    """overdraw_auto_void_selection: newest-first, stop at the first non-negative balance."""
    voided = []
    while available_points(member["id"]) < 0:
        candidates = [r for r in db.fuel_redemptions.values()
                      if r["member_id"] == member["id"]
                      and r["authorization_status"] == "AUTHORIZED"]
        if not candidates:
            break
        candidates.sort(key=lambda r: (r["created_at"], r["points_debited_at_auth"], r["_seq"]),
                        reverse=True)
        void_redemption(candidates[0], member, reason_cycle_id=cycle_id)
        voided.append(candidates[0])
    return voided


def oldest_active_household(member_id):
    links = links_of_member(member_id, ("ACTIVE",))
    if not links:
        return None
    return db.households.get(links[0]["household_id"])


# ------------------------------------------------------------------ transfers

def shared_household(sender_id, recipient_id):
    """First household (sender's link created_at ASC) both members hold ACTIVE links to."""
    recipient_ids = set(l["household_id"]
                        for l in links_of_member(recipient_id, ("ACTIVE",)))
    for link in links_of_member(sender_id, ("ACTIVE",)):
        if link["household_id"] in recipient_ids:
            return db.households.get(link["household_id"])
    return None


def fraud_locked(member_id):
    """PRD 3.7: >= 2 OPEN signals, or any OPEN RAPID_TRANSFER / ALT_ID_SHARING signal."""
    for household in households_of_member(member_id):
        signals = open_signals(household["id"])
        if len(signals) >= 2:
            return True
        for signal in signals:
            if signal["signal_type"] in ("RAPID_TRANSFER", "ALT_ID_SHARING"):
                return True
    return False


def household_member_ids(household_id):
    return [l["member_id"] for l in links_of_household(household_id, ("ACTIVE",))]


def transfer_out_count(household_id, cycle_id):
    member_ids = set(household_member_ids(household_id))
    total = 0
    for entry in db.ledger_entries.values():
        if entry["entry_type"] == "TRANSFER_OUT" \
                and entry["point_cycle_id"] == cycle_id \
                and entry["member_id"] in member_ids:
            total += 1
    return total


def member_has_active_link_to_banner(member_id, banner_id):
    for link in links_of_member(member_id, ("ACTIVE",)):
        household = db.households.get(link["household_id"])
        if household is not None and household["banner_id"] == banner_id:
            return True
    return False


# ------------------------------------------------------------------ promo / batch conflicts

def promo_conflict(event):
    """PRD 3.1: same banner, SCHEDULED|ACTIVE, overlapping half-open window,
    intersecting categories AND equal stack_priority."""
    categories = set(event["applies_to_categories"])
    for other in db.promo_events.values():
        if other["id"] == event["id"]:
            continue
        if other["banner_id"] != event["banner_id"]:
            continue
        if other["status"] not in ("SCHEDULED", "ACTIVE"):
            continue
        if other["stack_priority"] != event["stack_priority"]:
            continue
        if not categories & set(other["applies_to_categories"]):
            continue
        # half-open [starts_at, ends_at): touching endpoints do NOT overlap
        if event["starts_at"] < other["ends_at"] and other["starts_at"] < event["ends_at"]:
            return other
    return None


def batch_period_overlap(site_id, period_start, period_end, statuses=("SUBMITTED", "APPROVED"),
                         exclude_id=None):
    """Closed [period_start, period_end]: touching endpoints DO overlap."""
    hits = []
    for batch in db.settlement_batches.values():
        if batch["site_id"] != site_id or batch["id"] == exclude_id:
            continue
        if batch["status"] not in statuses:
            continue
        if period_start <= batch["period_end"] and batch["period_start"] <= period_end:
            hits.append(batch)
    return by_created(hits)


def batch_claimed_redemptions(batch_id):
    return by_created([r for r in db.fuel_redemptions.values()
                       if r["settlement_batch_id"] == batch_id])


def settleable_redemptions(site_id, period_start, period_end):
    rows = []
    for redemption in db.fuel_redemptions.values():
        if redemption["site_id"] != site_id:
            continue
        if redemption["settlement_status"] != "PENDING":
            continue
        dispensed = redemption["dispensed_at"]
        if dispensed is None:
            continue
        if period_start <= dispensed <= period_end:
            rows.append(redemption)
    return by_created(rows)


# ------------------------------------------------------------------ disputes

def dispute_chain_length(dispute):
    """Length of the supersede chain ending at `dispute` (inclusive)."""
    length = 1
    seen = set()
    current = dispute
    while current is not None and current["supersedes_dispute_id"] is not None:
        if current["id"] in seen:
            break
        seen.add(current["id"])
        current = db.point_disputes.get(current["supersedes_dispute_id"])
        if current is None:
            break
        length += 1
    return length


def accrual_entry_of(transaction_id):
    for entry in by_created(list(db.ledger_entries.values())):
        if entry["source_kind"] == "PURCHASE_TRANSACTION" \
                and entry["source_ref_id"] == transaction_id \
                and entry["entry_type"] == "ACCRUAL":
            return entry
    return None
