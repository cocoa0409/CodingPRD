"""Every calculation named in the PRD, in the pinned evaluation order.

Money is always an integer count of cents; rates are decimal fractions and are
never rounded.  Whenever a cent amount is produced by multiplying a cent amount
by a rate the result is rounded half up (PRD 2.6).
"""

from decimal import Decimal, ROUND_HALF_UP

from errors import ApiError
from store import (add_days, date_of, ordered, store, year_window)

# PRD 2.12 — states whose seller-of-travel regime mandates client trust handling.
TRUST_STATES = ("CA", "FL", "HI", "IA", "WA")

# PRD 3.2 / 3.5 — one million dollars of per-occurrence E&O cover.
MIN_EO_COVERAGE_CENTS = 100000000

# PRD 3.5 step three — flat half a percentage point for the host's own tool.
INTERNAL_TOOL_BONUS_PCT = Decimal("0.005")

# PRD 3.7 — claim escalation bands.
CLAIM_ESCALATION_DAYS = 60
CLAIM_CRITICAL_DAYS = 120

# PRD 3.7 — resubmission cap.
MAX_CLAIM_ROUNDS = 3


def D(value):
    """Exact Decimal from a JSON number without float contamination."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def round_half_up(value):
    """Round a Decimal to a whole cent, half away from zero."""
    return int(D(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# --------------------------------------------------------------------------
# ladders
# --------------------------------------------------------------------------

def select_tier(tiers, basis_cents):
    """calculations.split_tier_selection — inclusive floor, greatest wins."""
    candidates = [t for t in tiers if basis_cents >= t["min_production_cents"]]
    if not candidates:
        return None
    return max(candidates, key=lambda t: t["min_production_cents"])


def select_fee_tier(fee_tiers, gross_share_cents):
    """host_platform_fee step 2 — keyed on the pre-fee gross share."""
    candidates = [t for t in fee_tiers if gross_share_cents >= t["min_share_cents"]]
    if not candidates:
        return None
    return max(candidates, key=lambda t: t["min_share_cents"])


# --------------------------------------------------------------------------
# lookups
# --------------------------------------------------------------------------

def advisor_agreements(advisor_id):
    return ordered([a for a in store.agreements.values() if a["advisor_id"] == advisor_id])


def active_agreements(advisor_id):
    return [a for a in advisor_agreements(advisor_id) if a["status"] == "ACTIVE"]


def active_agreement(advisor_id):
    rows = active_agreements(advisor_id)
    return rows[0] if rows else None


def settlement_agreement(advisor_id):
    """host_platform_fee step 2: the ACTIVE-or-TERMINATED agreement with the
    greatest effective_date, ties broken by created_at ascending."""
    rows = [a for a in advisor_agreements(advisor_id)
            if a["status"] in ("ACTIVE", "TERMINATED")]
    if not rows:
        return None
    best = None
    for row in rows:  # already created_at ascending, so a tie keeps the earlier row
        if best is None or row["effective_date"] > best["effective_date"]:
            best = row
    return best


def schedule_of(agreement):
    if agreement is None:
        return None
    return store.split_schedules.get(agreement["split_schedule_id"])


def tier_schedule_for(advisor):
    """The schedule that governs this advisor's live tier selection."""
    schedule = schedule_of(active_agreement(advisor["id"]))
    if schedule is None:
        schedule = schedule_of(settlement_agreement(advisor["id"]))
    return schedule


def advisor_credentials(advisor_id):
    return ordered([c for c in store.credentials.values() if c["advisor_id"] == advisor_id])


def in_force(credential, clock):
    return credential["effective_on"] <= clock < credential["expires_on"]


def has_seller_of_travel(advisor, clock):
    for cred in advisor_credentials(advisor["id"]):
        if (cred["credential_type"] == "SELLER_OF_TRAVEL"
                and cred["status"] == "VERIFIED"
                and cred["jurisdiction_state_code"] == advisor["seller_of_travel_state"]
                and in_force(cred, clock)):
            return True
    return False


def has_eo_coverage(advisor, clock):
    for cred in advisor_credentials(advisor["id"]):
        if (cred["credential_type"] == "EO_POLICY"
                and cred["status"] == "VERIFIED"
                and in_force(cred, clock)
                and (cred["coverage_amount_cents"] or 0) >= MIN_EO_COVERAGE_CENTS):
            return True
    return False


def has_training_cert(advisor, clock):
    for cred in advisor_credentials(advisor["id"]):
        if (cred["credential_type"] == "TRAINING_CERT"
                and cred["status"] == "VERIFIED"
                and in_force(cred, clock)):
            return True
    return False


def has_supplier_accreditation(advisor, supplier_id, clock):
    for cred in advisor_credentials(advisor["id"]):
        if (cred["credential_type"] == "SUPPLIER_ACCREDITATION"
                and cred["supplier_id"] == supplier_id
                and cred["status"] == "VERIFIED"
                and in_force(cred, clock)):
            return True
    return False


def recompute_eo_coverage(advisor):
    """Greatest coverage across the advisor's VERIFIED E&O rows; 0 when empty."""
    best = 0
    for cred in advisor_credentials(advisor["id"]):
        if cred["credential_type"] == "EO_POLICY" and cred["status"] == "VERIFIED":
            amount = cred["coverage_amount_cents"] or 0
            if amount > best:
                best = amount
    advisor["eo_coverage_verified_cents"] = best


def derive_trust_requirement(advisor):
    """calculations.trust_requirement_derivation."""
    advisor["trust_account_required"] = advisor["seller_of_travel_state"] in TRUST_STATES


# --------------------------------------------------------------------------
# booking_expected_commission (PRD 3.5, four ordered steps)
# --------------------------------------------------------------------------

def price_booking(booking, advisor, supplier):
    # STEP 1 — commissionable base
    base_cents = booking["gross_sale_cents"] - booking["non_commissionable_cents"]
    booking["commissionable_base_cents"] = base_cents

    # STEP 2 — base rate: supplier programme standing AND consortium co-membership
    if (supplier["program_status"] == "PREFERRED"
            and supplier["consortium_id"] is not None
            and supplier["consortium_id"] == advisor["consortium_id"]):
        base_rate = D(supplier["preferred_override_commission_pct"])
    else:
        base_rate = D(supplier["base_commission_pct"])

    # STEP 3 — channel bonus
    if (booking["channel"] == "CONSORTIUM"
            and advisor["consortium_id"] is not None
            and advisor["consortium_id"] == supplier["consortium_id"]):
        consortium = store.consortiums.get(advisor["consortium_id"])
        bonus = D(consortium["consortium_channel_bonus_pct"]) if consortium else Decimal("0")
    elif booking["channel"] == "INTERNAL_TOOL":
        bonus = INTERNAL_TOOL_BONUS_PCT
    else:
        bonus = Decimal("0")

    # STEP 4 — ceiling first, then the absolute per-booking cap
    effective_rate = base_rate + bonus
    ceiling = D(supplier["rate_ceiling_pct"])
    if effective_rate > ceiling:
        effective_rate = ceiling
    raw = D(base_cents) * effective_rate
    expected = min(round_half_up(raw), supplier["max_commission_per_booking_cents"])

    booking["applied_commission_rate"] = float(effective_rate)
    booking["expected_commission_cents"] = expected
    return expected


# --------------------------------------------------------------------------
# advisor_production_ytd + split_tier_selection
# --------------------------------------------------------------------------

def advisor_bookings(advisor_id):
    return ordered([b for b in store.bookings.values() if b["advisor_id"] == advisor_id])


def recompute_provisional(advisor):
    """PROVISIONAL basis: pipeline work at its expected amount, keyed on
    travel_start_date."""
    year_start, year_end = year_window(store.clock)
    total = 0
    for booking in advisor_bookings(advisor["id"]):
        if booking["booking_status"] not in ("SUBMITTED", "CONFIRMED", "TRAVELED"):
            continue
        if booking["commission_status"] in ("CHARGED_BACK", "WRITTEN_OFF"):
            continue
        if not (year_start <= booking["travel_start_date"] < year_end):
            continue
        total += booking["expected_commission_cents"]
    advisor["production_ytd_provisional_cents"] = total
    schedule = tier_schedule_for(advisor)
    if schedule is not None:
        tier = select_tier(schedule["tiers"], total)
        if tier is None:
            raise ApiError("ERR_SPLIT_TIER_UNRESOLVED")
        advisor["split_tier_provisional"] = tier["tier_level"]


def recompute_final(advisor):
    """FINAL basis: only received money, keyed on commission_received_on."""
    year_start, year_end = year_window(store.clock)
    total = 0
    for booking in advisor_bookings(advisor["id"]):
        if booking["booking_status"] not in ("CONFIRMED", "TRAVELED"):
            continue
        if booking["commission_status"] != "RECEIVED":
            continue
        received_on = booking["commission_received_on"]
        if received_on is None or not (year_start <= received_on < year_end):
            continue
        total += booking["received_commission_cents"]
    advisor["production_ytd_final_cents"] = total
    schedule = tier_schedule_for(advisor)
    if schedule is not None:
        tier = select_tier(schedule["tiers"], total)
        if tier is None:
            raise ApiError("ERR_SPLIT_TIER_UNRESOLVED")
        advisor["split_tier_final"] = tier["tier_level"]


def final_tier_pct(advisor):
    """advisor_pct of the tier the FINAL basis selects for this advisor."""
    schedule = tier_schedule_for(advisor)
    if schedule is None:
        return None
    tier = select_tier(schedule["tiers"], advisor["production_ytd_final_cents"])
    if tier is None:
        raise ApiError("ERR_SPLIT_TIER_UNRESOLVED")
    return tier


# --------------------------------------------------------------------------
# supplier_commission_aging (PRD 3.7)
# --------------------------------------------------------------------------

def supplier_bookings(supplier_id):
    return ordered([b for b in store.bookings.values() if b["supplier_id"] == supplier_id])


def booking_due_date(booking, supplier):
    return add_days(date_of(booking["travel_end_date"]), supplier["remit_terms_days"])


def recompute_supplier_aging(supplier):
    as_of = date_of(store.clock)
    buckets = [0, 0, 0, 0]
    for booking in supplier_bookings(supplier["id"]):
        if booking["booking_status"] not in ("CONFIRMED", "TRAVELED"):
            continue
        if booking["commission_status"] not in ("EXPECTED", "CLAIMED"):
            continue
        due = booking_due_date(booking, supplier)
        if due > as_of:
            continue
        age_days = (as_of - due).days
        amount = booking["expected_commission_cents"] - booking["received_commission_cents"]
        if age_days <= 30:
            buckets[0] += amount
        elif age_days <= 60:
            buckets[1] += amount
        elif age_days <= 90:
            buckets[2] += amount
        else:
            buckets[3] += amount
    supplier["aging_0_30_cents"] = buckets[0]
    supplier["aging_31_60_cents"] = buckets[1]
    supplier["aging_61_90_cents"] = buckets[2]
    supplier["aging_over_90_cents"] = buckets[3]
    supplier["total_outstanding_cents"] = sum(buckets)


def recompute_supplier_chargeback_count(supplier):
    count = 0
    for booking in supplier_bookings(supplier["id"]):
        if booking["commission_status"] == "CHARGED_BACK":
            count += 1
    supplier["chargeback_count"] = count
    return count


def recompute_aging_for_booking(booking):
    supplier = store.suppliers.get(booking["supplier_id"])
    if supplier is not None:
        recompute_supplier_aging(supplier)


# --------------------------------------------------------------------------
# client_trust_balance (PRD 3.4)
# --------------------------------------------------------------------------

def client_entries(client_id):
    return ordered([e for e in store.trust_entries.values() if e["client_id"] == client_id])


def recompute_client_balance(client):
    running = 0
    for entry in client_entries(client["id"]):
        running += entry["signed_amount_cents"]
        entry["balance_after_cents"] = running
    client["trust_balance_cents"] = running
    return running


# --------------------------------------------------------------------------
# claim_aging_escalation (PRD 3.7)
# --------------------------------------------------------------------------

def refresh_claim_aging(claim):
    delta = store.clock - claim["created_at"]
    aging_days = delta.days if delta.days > 0 else (0 if delta.total_seconds() < 86400 else delta.days)
    if aging_days < 0:
        aging_days = 0
    claim["aging_days"] = aging_days
    if aging_days < CLAIM_ESCALATION_DAYS:
        claim["escalation_level"] = "NORMAL"
    elif aging_days < CLAIM_CRITICAL_DAYS:
        claim["escalation_level"] = "ESCALATED"
    else:
        claim["escalation_level"] = "CRITICAL"


# --------------------------------------------------------------------------
# cancellation_chargeback (PRD 3.6)
# --------------------------------------------------------------------------

def cancellation_chargeback(booking):
    settled = booking["settled_share_cents"]
    reason = booking["cancellation_reason"]
    if reason in ("CLIENT_INITIATED", "ADVISOR_ERROR"):
        return settled                                  # GROSS_REVERSAL
    agreement = store.agreements.get(booking["agreement_id"])
    schedule = schedule_of(agreement)
    retention = D(schedule["chargeback_retention_pct"]) if schedule else Decimal("0")
    return round_half_up(D(settled) * (Decimal("1") - retention))   # NET_OF_RETENTION


# --------------------------------------------------------------------------
# host_platform_fee (PRD 3.8, five pinned steps)
# --------------------------------------------------------------------------

def host_platform_fee(advisor, gross_share_cents, chargeback_cents):
    agreement = settlement_agreement(advisor["id"])
    schedule = schedule_of(agreement)
    platform_fee = 0
    if schedule is not None:
        fee_tier = select_fee_tier(schedule["platform_fee_tiers"], gross_share_cents)
        if fee_tier is not None:
            platform_fee = round_half_up(D(gross_share_cents) * D(fee_tier["fee_pct"]))

    if advisor["consortium_id"] is None:
        marketing_fund = 0
    else:
        consortium = store.consortiums.get(advisor["consortium_id"])
        if consortium is None:
            marketing_fund = 0
        else:
            marketing_base = gross_share_cents - platform_fee
            marketing_fund = round_half_up(
                D(marketing_base) * D(consortium["marketing_fund_accrual_pct"]))

    raw_net = gross_share_cents - platform_fee - marketing_fund - chargeback_cents
    if raw_net >= 0:
        net_payout = raw_net
        carryforward = 0
    else:
        net_payout = 0
        carryforward = -raw_net
    return platform_fee, marketing_fund, net_payout, carryforward


# --------------------------------------------------------------------------
# advisor_recognized_share_invariant (PRD 2.9 / 3.8)
# --------------------------------------------------------------------------

def advisor_statements(advisor_id):
    return ordered([s for s in store.statements.values() if s["advisor_id"] == advisor_id])


def recompute_advisor_lifetime(advisor):
    settled = 0
    charged = 0
    for statement in advisor_statements(advisor["id"]):
        if statement["status"] in ("POSTED", "PAID"):
            settled += statement["advisor_share_cents"]
            charged += statement["chargeback_cents"]
    advisor["lifetime_settled_share_cents"] = settled
    advisor["lifetime_chargeback_cents"] = charged


def recompute_consortium_fund(consortium):
    total = 0
    for statement in ordered(store.statements.values()):
        if statement["status"] not in ("POSTED", "PAID"):
            continue
        advisor = store.advisors.get(statement["advisor_id"])
        if advisor is None or advisor["consortium_id"] != consortium["id"]:
            continue
        total += statement["marketing_fund_cents"]
    consortium["marketing_fund_balance_cents"] = total
