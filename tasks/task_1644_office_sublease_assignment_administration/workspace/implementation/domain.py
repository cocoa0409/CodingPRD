"""Business logic: business-day arithmetic, measurement calc, settlement calc,
deemed-approval evaluation, and cross-entity cascade helpers."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

import db
from db import store, touch, iso_logical, parse_iso


# ---------------------------------------------------------------------------
# Rounding helpers
# ---------------------------------------------------------------------------

def round_half_up(value):
    """Round to nearest integer, half-up (not banker's rounding)."""
    if isinstance(value, Decimal):
        return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Business-day calendar
# ---------------------------------------------------------------------------

def _is_business_day(d):
    """Monday=0 .. Friday=4 are business days."""
    return d.weekday() < 5


def _next_business_day(d):
    """Advance a date to the next business day."""
    d = d + timedelta(days=1)
    while not _is_business_day(d):
        d += timedelta(days=1)
    return d


def compute_consent_deadline(submitted_at, window_business_days):
    """Nth business day strictly after the submission calendar day, at 17:00:00.000Z.

    Counting begins on the first business day strictly after the submission day.
    """
    day = submitted_at.date() if isinstance(submitted_at, datetime) else submitted_at
    # First business day strictly after submission day = business day 1
    day = _next_business_day(day)
    # Advance to the Nth business day
    for _ in range(window_business_days - 1):
        day = _next_business_day(day)
    return datetime(day.year, day.month, day.day, 17, 0, 0, tzinfo=timezone.utc)


def compute_deemed_approval_instant(consent_deadline):
    """2 business days after consent_deadline, at 17:00:00.000Z."""
    day = consent_deadline.date() if isinstance(consent_deadline, datetime) else consent_deadline
    day = _next_business_day(day)
    day = _next_business_day(day)
    return datetime(day.year, day.month, day.day, 17, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Space measurement
# ---------------------------------------------------------------------------

METHOD_B_COMMON_ADDON_BPS = 250


def compute_measurement(usable_sf, measurement_standard, loss_factor_bps,
                        total_rentable_sf, leased_rsf):
    """Compute rentable_sf, prorata_share_bps, is_partial_floor.

    Pinned evaluation order: rentable_sf -> prorata_share_bps -> is_partial_floor.
    """
    if measurement_standard == "METHOD_A":
        rentable_sf = round_half_up(
            Decimal(usable_sf) * Decimal(10000 + loss_factor_bps) / Decimal(10000)
        )
    else:  # METHOD_B
        half_loss = loss_factor_bps // 2  # integer division, remainder discarded
        rentable_sf = round_half_up(
            Decimal(usable_sf) * Decimal(10000 + half_loss + METHOD_B_COMMON_ADDON_BPS) / Decimal(10000)
        )
    prorata_share_bps = round_half_up(
        Decimal(rentable_sf) * Decimal(10000) / Decimal(total_rentable_sf)
    )
    is_partial_floor = rentable_sf < leased_rsf
    return rentable_sf, prorata_share_bps, is_partial_floor


# ---------------------------------------------------------------------------
# Rent differential
# ---------------------------------------------------------------------------

def compute_rent_differential(rent_per_rsf_cents, base_rent_per_rsf_cents, rentable_sf):
    """max(0, proposed_rent - base_rent) * certified RSF. Integer cents, no rounding."""
    spread = rent_per_rsf_cents - base_rent_per_rsf_cents
    if spread <= 0:
        return 0
    return spread * rentable_sf


# ---------------------------------------------------------------------------
# Settlement profit-share waterfall
# ---------------------------------------------------------------------------

DAYS_PER_YEAR = 365
PARTIAL_FLOOR_GROSSUP_BPS = 1500


def compute_settlement_fields(lease, rentable_sf, is_partial_floor,
                              period_start, period_end, subrent_collected_cents):
    """Compute all derived settlement fields in the pinned order.

    1) day_count  2) passthrough (with partial-floor gross-up)
    3) net_profit  4) tier split with PER-TIER rounding then sum.
    """
    day_count = (period_end - period_start).days
    if day_count <= 0:
        return {
            "passthrough_rent_cents": 0,
            "net_profit_cents": 0,
            "landlord_share_cents": 0,
            "tenant_share_cents": 0,
        }

    # Step 1: base passthrough (round step 1)
    base = (Decimal(lease["base_rent_per_rsf_annual_cents"])
            * Decimal(rentable_sf) * Decimal(day_count) / Decimal(DAYS_PER_YEAR))
    base_passthrough = round_half_up(base)

    # Step 2: partial-floor gross-up (round step 2, nested)
    if is_partial_floor:
        passthrough_rent_cents = round_half_up(
            Decimal(base_passthrough) * Decimal(10000 + PARTIAL_FLOOR_GROSSUP_BPS) / Decimal(10000)
        )
    else:
        passthrough_rent_cents = base_passthrough

    # Step 3: net profit (floored at zero)
    net_profit_cents = max(0, subrent_collected_cents - passthrough_rent_cents)

    # Step 4: annualize
    annualized_profit_cents = round_half_up(
        Decimal(net_profit_cents) * Decimal(DAYS_PER_YEAR) / Decimal(day_count)
    )

    # Step 5: tier split with per-tier rounding then sum
    tier1_threshold = lease["profit_share_tier1_threshold_annual_cents"]
    tier1_base = min(annualized_profit_cents, tier1_threshold)
    tier2_base = max(0, annualized_profit_cents - tier1_threshold)
    tier1_landlord = round_half_up(
        Decimal(tier1_base) * Decimal(lease["profit_share_tier1_pct_bps"]) / Decimal(10000)
    )
    tier2_landlord = round_half_up(
        Decimal(tier2_base) * Decimal(lease["profit_share_tier2_pct_bps"]) / Decimal(10000)
    )
    landlord_share_annualized = tier1_landlord + tier2_landlord

    # Step 6: de-annualize (round step 3)
    landlord_share_cents = round_half_up(
        Decimal(landlord_share_annualized) * Decimal(day_count) / Decimal(DAYS_PER_YEAR)
    )

    # Tenant share is NOT floored — may go negative
    tenant_share_cents = net_profit_cents - landlord_share_cents

    return {
        "passthrough_rent_cents": passthrough_rent_cents,
        "net_profit_cents": net_profit_cents,
        "landlord_share_cents": landlord_share_cents,
        "tenant_share_cents": tenant_share_cents,
    }


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------

def get_certified_area(transfer_request_id):
    """Return the CERTIFIED, non-superseded DemisedArea for a transfer, or None."""
    for area in store.demised_areas.values():
        if (area["transfer_request_id"] == transfer_request_id
                and area["status"] == "CERTIFIED"
                and area["superseded_by_id"] is None):
            return area
    return None


def get_consent_review(transfer_request_id):
    """Return the ConsentReview for a transfer, or None."""
    for cr in store.consent_reviews.values():
        if cr["transfer_request_id"] == transfer_request_id:
            return cr
    return None


def get_credit_review(transfer_request_id):
    """Return the CreditReview for a transfer, or None."""
    for cr in store.credit_reviews.values():
        if cr["transfer_request_id"] == transfer_request_id:
            return cr
    return None


def get_recognition_agreement(transfer_request_id):
    """Return the RecognitionAgreement for a transfer, or None."""
    for ra in store.recognition_agreements.values():
        if ra["transfer_request_id"] == transfer_request_id:
            return ra
    return None


def get_sublease_agreement(transfer_request_id):
    """Return the SubleaseAgreement for a transfer, or None."""
    for sa in store.sublease_agreements.values():
        if sa["transfer_request_id"] == transfer_request_id:
            return sa
    return None


def get_conditions_for_review(consent_review_id):
    """Return all ConsentConditions for a review."""
    return [c for c in store.consent_conditions.values()
            if c["consent_review_id"] == consent_review_id]


def get_settlement_measurement(transfer):
    """Get the DemisedArea to use for settlement math.

    For SUBLEASE with an instrument: use the pinned demised_area_id.
    Otherwise: use the transfer's certified non-superseded record.
    """
    if transfer["transfer_type"] == "SUBLEASE":
        sa = get_sublease_agreement(transfer["id"])
        if sa is not None and sa.get("demised_area_id"):
            area = store.demised_areas.get(sa["demised_area_id"])
            if area is not None:
                return area
    return get_certified_area(transfer["id"])


# ---------------------------------------------------------------------------
# Cross-entity helpers
# ---------------------------------------------------------------------------

NON_TERMINAL_TRANSFER_STATUSES = {
    "DRAFT", "SUBMITTED", "CONSENT_PENDING", "CONSENT_GRANTED",
    "DEEMED_APPROVED", "DOCUMENTED",
}


def count_open_transfers(lease_id):
    """Count non-terminal TransferRequests for a lease."""
    return sum(1 for t in store.transfer_requests.values()
               if t["lease_id"] == lease_id and t["status"] in NON_TERMINAL_TRANSFER_STATUSES)


def grant_consent(transfer, lease, release_of_assignor):
    """Apply the CONSENT_GRANTED side effects to a transfer.

    Called by express GRANTED, conditional-acceptance join, and deemed approval.
    """
    now = db.LOGICAL_CLOCK
    transfer["consent_granted_at"] = iso_logical(now)
    certified = get_certified_area(transfer["id"])
    if certified is not None:
        transfer["annual_rent_differential_cents"] = compute_rent_differential(
            transfer["proposed_rent_per_rsf_annual_cents"],
            lease["base_rent_per_rsf_annual_cents"],
            certified["rentable_sf"],
        )
    transfer["liability_released"] = (
        transfer["transfer_type"] == "ASSIGNMENT" and release_of_assignor
    )
    touch(transfer)


def decrement_lease_open_count(lease):
    """Decrement open_transfer_count and bump version."""
    lease["open_transfer_count"] = max(0, lease.get("open_transfer_count", 0) - 1)
    touch(lease)


def void_recognition_agreements(transfer):
    """Void any DRAFTED or PARTIALLY_SIGNED RecognitionAgreement for a transfer."""
    ra = get_recognition_agreement(transfer["id"])
    if ra is not None and ra["status"] in ("DRAFTED", "PARTIALLY_SIGNED"):
        ra["status"] = "VOIDED"
        touch(ra)


def evaluate_deemed_approvals():
    """Evaluate deemed-approval for all SUBMITTED/CONSENT_PENDING transfers.

    Returns the count of transitions fired.
    """
    now = db.LOGICAL_CLOCK
    advanced = 0
    for transfer in list(store.transfer_requests.values()):
        if transfer["status"] not in ("SUBMITTED", "CONSENT_PENDING"):
            continue
        lease = store.leases.get(transfer["lease_id"])
        if lease is None or not lease.get("deemed_approval_enabled"):
            continue
        review = get_consent_review(transfer["id"])
        if review is None or review["decision"] != "PENDING":
            continue
        if transfer.get("reminder_sent_at") is None:
            continue
        reminder_dt = parse_iso(transfer["reminder_sent_at"])
        deadline_dt = parse_iso(transfer["consent_deadline"])
        if reminder_dt < deadline_dt:
            continue
        deemed_instant = compute_deemed_approval_instant(deadline_dt)
        if now < deemed_instant:
            continue
        # Fire deemed approval
        transfer["status"] = "DEEMED_APPROVED"
        transfer["consent_granted_at"] = iso_logical(now)
        transfer["liability_released"] = False
        certified = get_certified_area(transfer["id"])
        if certified is not None:
            transfer["annual_rent_differential_cents"] = compute_rent_differential(
                transfer["proposed_rent_per_rsf_annual_cents"],
                lease["base_rent_per_rsf_annual_cents"],
                certified["rentable_sf"],
            )
        touch(transfer)
        review["decision"] = "GRANTED"
        review["decided_at"] = iso_logical(now)
        review["release_of_assignor"] = False
        touch(review)
        advanced += 1
    return advanced
