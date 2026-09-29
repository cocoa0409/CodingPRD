"""Pinned calculations and derived aggregates (PRD §2.5, §2.11, §3.1, §3.5-§3.9)."""

from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR

from store import (
    store, now_dt, dt_of, parse_iso, days, sort_rows, touch,
)

# --------------------------------------------------------------------------
# Rounding discipline (PRD §2.5)
# --------------------------------------------------------------------------
def dec(value):
    return Decimal(str(value))


def rhu(value, places=0):
    """Round half up to `places` decimal places."""
    quant = Decimal(1).scaleb(-places)
    return dec(value).quantize(quant, rounding=ROUND_HALF_UP)


def rhu_int(value):
    return int(rhu(value, 0))


def floor_int(value):
    return int(dec(value).to_integral_value(rounding=ROUND_FLOOR))


# --------------------------------------------------------------------------
# Policy selection (PRD §3.1)
# --------------------------------------------------------------------------
GOVERNING_STATUSES = ("PUBLISHED", "SUPERSEDED", "WITHDRAWN")


def select_governing_policy(as_of):
    """The policy governing an instant, or None."""
    candidates = []
    for policy in store.policies.values():
        if policy["status"] not in GOVERNING_STATUSES:
            continue
        eff = dt_of(policy, "effective_from")
        if eff is None or eff > as_of:
            continue
        candidates.append((eff, policy))
    if not candidates:
        return None
    candidates.sort(key=lambda pair: (
        -pair[0].timestamp(),
        pair[1].get("created_at") or "",
        pair[1].get("_seq", 0),
    ))
    return candidates[0][1]


# --------------------------------------------------------------------------
# Bundle allocation (PRD §3.5)
# --------------------------------------------------------------------------
def allocate_bundle(components, bundle_total_price_cents, target_sku):
    total_msrp = sum(c["msrp_cents"] for c in components)
    ordered = sorted(components, key=lambda c: (-c["msrp_cents"], c["sku"]))
    shares = {}
    running = 0
    last_index = len(ordered) - 1
    for index, component in enumerate(ordered):
        if index < last_index:
            share = rhu_int(
                dec(bundle_total_price_cents) * dec(component["msrp_cents"]) / dec(total_msrp)
            )
            shares[component["sku"]] = share
            running += share
        else:
            shares[component["sku"]] = bundle_total_price_cents - running
    return shares.get(target_sku)


# --------------------------------------------------------------------------
# Effective advertised price (PRD §3.5)
# --------------------------------------------------------------------------
def effective_advertised_price(observation, policy):
    if observation.get("is_bundle"):
        base = observation.get("allocated_component_price_cents")
    else:
        base = observation.get("listed_price_cents")
    gross = int(base)
    if policy.get("shipping_counts_as_advertised"):
        gross += int(observation.get("shipping_cents") or 0)
    qualifying = []
    if policy.get("auto_coupon_counts_as_advertised"):
        qualifying.append(int(observation.get("auto_coupon_cents") or 0))
    if policy.get("promo_code_counts_as_advertised"):
        qualifying.append(int(observation.get("promo_code_cents") or 0))
    candidate = max(qualifying) if qualifying else 0
    cap = floor_int(dec(gross) * dec(policy.get("max_discount_attribution_pct")))
    return gross - min(candidate, cap)


# --------------------------------------------------------------------------
# Floor resolution (PRD §3.6)
# --------------------------------------------------------------------------
def resolve_floor(product, channel, as_of, is_bundle):
    """Returns (floor_cents, floor_source, applied_exception_id)."""
    eligible = []
    for exc in store.exceptions.values():
        if exc["product_id"] != product["id"] or exc["status"] != "APPROVED":
            continue
        starts = dt_of(exc, "starts_at")
        ends = dt_of(exc, "ends_at")
        if starts is None or ends is None:
            continue
        if not (starts <= as_of < ends):
            continue
        scope = exc.get("channel_scope")
        if scope != "ALL" and scope != channel:
            continue
        if exc["exception_type"] == "BUNDLE" and not is_bundle:
            continue
        eligible.append(exc)
    if not eligible:
        return product["standard_map_floor_cents"], "STANDARD", None
    eligible.sort(key=lambda e: (
        0 if e.get("channel_scope") == channel else 1,
        -(dt_of(e, "starts_at").timestamp()),
        e.get("created_at") or "",
        e.get("_seq", 0),
    ))
    selected = eligible[0]
    return selected["override_floor_cents"], "EXCEPTION", selected["id"]


# --------------------------------------------------------------------------
# Deviation and violation points (PRD §3.5)
# --------------------------------------------------------------------------
CHANNEL_MULTIPLIERS = {
    "MARKETPLACE": Decimal("1.5"),
    "RETAILER_SITE": Decimal("1.0"),
    "OWN_WEBSITE": Decimal("1.0"),
    "PHYSICAL_RETAIL": Decimal("0.5"),
}
REPEAT_STEP = Decimal("0.25")
REPEAT_CAP = 4
POINTS_LOOKBACK_DAYS = 180
LEDGER_STATUSES = ("NOTICED", "DISPUTED", "CURED", "ESCALATED", "CLOSED_MOOT")


def deviation(floor_cents, advertised_cents):
    dev = floor_cents - advertised_cents
    if dev < 0:
        dev = 0
    if floor_cents == 0:
        pct = Decimal("0")
    else:
        pct = rhu(dec(dev) / dec(floor_cents), 4)
    return dev, pct


def base_points(deviation_pct):
    if deviation_pct <= Decimal("0.0500"):
        return 1
    if deviation_pct <= Decimal("0.1500"):
        return 2
    if deviation_pct <= Decimal("0.3000"):
        return 4
    return 6


def count_prior_noticed(reseller_id, exclude_violation_id, as_of):
    cutoff = as_of - days(POINTS_LOOKBACK_DAYS)
    count = 0
    for viol in store.violations.values():
        if viol["reseller_id"] != reseller_id:
            continue
        if exclude_violation_id is not None and viol["id"] == exclude_violation_id:
            continue
        if viol["status"] not in LEDGER_STATUSES:
            continue
        if viol.get("assessed_points") is None:
            continue
        if viol.get("cure_deadline_at") is None:
            continue
        created = dt_of(viol, "created_at")
        if created is None or created < cutoff:
            continue
        count += 1
    return count


def violation_points(reseller_id, exclude_violation_id, channel, floor_cents,
                     advertised_cents, as_of):
    """Returns (points, deviation_cents, deviation_pct as Decimal)."""
    dev_cents, dev_pct = deviation(floor_cents, advertised_cents)
    if dev_cents == 0:
        return 0, dev_cents, dev_pct
    base = base_points(dev_pct)
    channel_multiplier = CHANNEL_MULTIPLIERS[channel]
    prior = count_prior_noticed(reseller_id, exclude_violation_id, as_of)
    repeat_multiplier = Decimal("1.00") + REPEAT_STEP * min(prior, REPEAT_CAP)
    points = rhu_int(dec(base) * channel_multiplier * repeat_multiplier)
    return points, dev_cents, dev_pct


# --------------------------------------------------------------------------
# Ladder rung selection (PRD §3.7)
# --------------------------------------------------------------------------
RUNG_ORDINAL = {"WARNING": 1, "SUSPENSION": 2, "TERMINATION": 3}
RUNG_BY_ORDINAL = {1: "WARNING", 2: "SUSPENSION", 3: "TERMINATION"}
SERVED_NOTICE_STATUSES = ("ISSUED", "ACKNOWLEDGED", "SATISFIED")


def points_rung(cumulative_points, policy):
    if cumulative_points < policy["suspension_points_threshold"]:
        return "WARNING"
    if cumulative_points < policy["termination_points_threshold"]:
        return "SUSPENSION"
    return "TERMINATION"


def highest_served_ordinal(reseller_id):
    highest = 0
    for notice in store.notices.values():
        if notice["reseller_id"] != reseller_id:
            continue
        if notice["status"] not in SERVED_NOTICE_STATUSES:
            continue
        highest = max(highest, RUNG_ORDINAL[notice["rung"]])
    return highest


def select_rung(reseller_id, cumulative_points, policy):
    justified = points_rung(cumulative_points, policy)
    ceiling = min(highest_served_ordinal(reseller_id) + 1, 3)
    return RUNG_BY_ORDINAL[min(RUNG_ORDINAL[justified], ceiling)]


def notices_of_violation(violation_id):
    return sort_rows([n for n in store.notices.values() if n["violation_id"] == violation_id])


def latest_non_rescinded_notice(violation_id):
    candidates = [n for n in notices_of_violation(violation_id) if n["status"] != "RESCINDED"]
    return candidates[-1] if candidates else None


def governing_suspension_notice(reseller_id):
    candidates = [
        n for n in sort_rows(list(store.notices.values()))
        if n["reseller_id"] == reseller_id
        and n["rung"] == "SUSPENSION"
        and n["status"] != "RESCINDED"
    ]
    return candidates[-1] if candidates else None


def live_suspension_notice(reseller_id):
    candidates = [
        n for n in sort_rows(list(store.notices.values()))
        if n["reseller_id"] == reseller_id
        and n["rung"] == "SUSPENSION"
        and n["status"] in ("ISSUED", "ACKNOWLEDGED")
    ]
    return candidates[-1] if candidates else None


# --------------------------------------------------------------------------
# Distributor tiers (PRD §3.9)
# --------------------------------------------------------------------------
SCORE_PER_UNIT = Decimal("2.5")


def tier_rate(score):
    value = dec(score)
    if value < Decimal("10.0"):
        return 2500
    if value < Decimal("25.0"):
        return 4000
    return 6000


def derive_standing(score):
    value = dec(score)
    if value < Decimal("10.0"):
        return "GOOD"
    if value < Decimal("25.0"):
        return "PROBATION"
    return "SUSPENDED"


def apply_standing(distributor, score):
    """Re-derive standing from a score, stamping probation_entered_at (PRD §3.3)."""
    previous = distributor.get("standing")
    standing = derive_standing(score)
    distributor["diversion_score"] = float(rhu(score, 1))
    distributor["standing"] = standing
    if standing == "PROBATION":
        if previous != "PROBATION":
            from store import now_iso
            distributor["probation_entered_at"] = now_iso()
    elif standing == "GOOD":
        distributor["probation_entered_at"] = None
    return standing


# --------------------------------------------------------------------------
# Derived aggregates (PRD §2.11)
# --------------------------------------------------------------------------
def compute_review_required(reseller):
    sourcing_id = reseller.get("sourcing_distributor_id")
    if sourcing_id:
        distributor = store.distributors.get(sourcing_id)
        if distributor is not None and distributor.get("standing") in ("PROBATION", "SUSPENDED"):
            return True
    for unit in store.serial_units.values():
        if unit.get("downstream_reseller_id") == reseller["id"] and unit["status"] == "TRACED_UNAUTHORIZED":
            return True
    return False


def refresh_review_required(reseller):
    """Idempotent recomputation — no version bump when the value is unchanged."""
    value = compute_review_required(reseller)
    if reseller.get("review_required") == value:
        return False
    reseller["review_required"] = value
    touch(reseller)
    return True


def refresh_review_required_for_distributor(distributor_id):
    for reseller in sort_rows(list(store.resellers.values())):
        if reseller.get("sourcing_distributor_id") == distributor_id:
            refresh_review_required(reseller)


def recount_open_exceptions(product):
    count = 0
    for exc in store.exceptions.values():
        if exc["product_id"] == product["id"] and exc["status"] == "APPROVED":
            count += 1
    product["open_exception_count"] = count
    return count


def contributing_violations(reseller_id):
    rows = []
    for viol in store.violations.values():
        if viol["reseller_id"] != reseller_id:
            continue
        if viol.get("assessed_points") is None:
            continue
        if viol["status"] not in LEDGER_STATUSES:
            continue
        rows.append(viol)
    return sort_rows(rows)


def recompute_points_total(reseller):
    total = sum(v["assessed_points"] for v in contributing_violations(reseller["id"]))
    reseller["violation_points_total"] = total
    return total


def recompute_distributor_ledgers(distributor):
    balance = 0
    score = Decimal("0")
    for cb in store.chargebacks.values():
        if cb["distributor_id"] != distributor["id"]:
            continue
        if cb["status"] not in ("ASSESSED", "DISPUTED", "UPHELD"):
            continue
        balance += cb["amount_cents"]
        score += dec(cb["score_delta_applied"])
    distributor["chargeback_balance_cents"] = balance
    return balance, score


def recount_shipped_units(distributor):
    count = 0
    for unit in store.serial_units.values():
        if unit.get("shipped_distributor_id") == distributor["id"]:
            count += 1
    distributor["shipped_units_total"] = count
    return count


# --------------------------------------------------------------------------
# Diversion exposure (PRD §3.9)
# --------------------------------------------------------------------------
def diversion_exposure(distributor, variant):
    score = distributor.get("diversion_score") or 0
    rate = tier_rate(score)
    own_units = [u for u in store.serial_units.values()
                 if u.get("shipped_distributor_id") == distributor["id"]]
    traced_count = len([u for u in own_units if u["status"] == "TRACED_UNAUTHORIZED"])
    if variant == "TRACE_ATTRIBUTED":
        units_counted = traced_count
        exposure = rate * units_counted
        return {
            "distributor_id": distributor["id"],
            "variant": variant,
            "traced_unit_count": traced_count,
            "units_counted": units_counted,
            "exposure_cents": exposure,
            "tier_rate_cents_per_unit": rate,
            "diversion_score": distributor.get("diversion_score"),
        }
    tally = Decimal("0")
    lot_codes = sorted({u["lot_code"] for u in own_units})
    for lot in lot_codes:
        lot_units = [u for u in store.serial_units.values() if u["lot_code"] == lot]
        lot_traced = len([u for u in lot_units if u["status"] == "TRACED_UNAUTHORIZED"])
        if lot_traced == 0:
            continue
        lot_shipped = len(lot_units)
        own_shipped = len([u for u in lot_units
                           if u.get("shipped_distributor_id") == distributor["id"]])
        tally += rhu(dec(lot_traced) * dec(own_shipped) / dec(lot_shipped), 2)
    exposure = rhu_int(dec(rate) * tally)
    return {
        "distributor_id": distributor["id"],
        "variant": variant,
        "traced_unit_count": traced_count,
        "units_counted": float(rhu(tally, 2)),
        "exposure_cents": exposure,
        "tier_rate_cents_per_unit": rate,
        "diversion_score": distributor.get("diversion_score"),
    }


# --------------------------------------------------------------------------
# Misc lookups
# --------------------------------------------------------------------------
def agreements_of_reseller(reseller_id, statuses=None):
    rows = [a for a in store.agreements.values() if a["reseller_id"] == reseller_id]
    if statuses is not None:
        rows = [a for a in rows if a["status"] in statuses]
    return sort_rows(rows)


def governing_permitted_channels(reseller_id):
    """The channel restriction currently in force for a reseller (its ACTIVE agreement)."""
    active = agreements_of_reseller(reseller_id, ("ACTIVE",))
    if not active:
        return None
    return active[-1].get("permitted_channels")


def thresholds_for_reseller(reseller, as_of):
    """Policy whose ladder thresholds govern a reseller (PRD §3.7 compliance summary)."""
    agreements = agreements_of_reseller(reseller["id"], ("ACTIVE",))
    if not agreements:
        agreements = agreements_of_reseller(reseller["id"])
    for agreement in reversed(agreements):
        policy = store.policies.get(agreement.get("policy_id"))
        if policy is not None:
            return policy
    policy = select_governing_policy(as_of)
    if policy is not None:
        return policy
    return None
