"""Award arithmetic, DOB offsets, the cap-and-offset waterfall, and ledger cascades.

All amounts are integer cents. See PRD §3.3-§3.10 and scaffold §1.3.
"""
from db import STORE, new_id, now_iso, now_dt, parse_iso

# Per-component caps (scaffold §1.3 eligible_award_amount constants)
REPAIR_CATEGORY_CAP_CENTS = 4150000
PERSONAL_CATEGORY_CAP_CENTS = 4150000
REPLACEMENT_CAP_CENTS = 4150000

# SBA thresholds (scaffold §1.3 sba_referral_eligibility constants)
SBA_INCOME_CEILING_CENTS = 7500000
SBA_LOSS_THRESHOLD_CENTS = 3000000

# Fixed category order for the waterfall (PRD §3.6)
CATEGORY_ORDER = ["RENTAL_ASSISTANCE", "REPAIR_ASSISTANCE", "PERSONAL_PROPERTY", "REPLACEMENT"]


def compute_components(repair, personal, rental_mo, fmr, habitable):
    """Per-category gross amounts (before cap, before DOB). Returns dict by category."""
    comp = {
        "REPAIR_ASSISTANCE": min(repair, REPAIR_CATEGORY_CAP_CENTS),
        "PERSONAL_PROPERTY": min(personal, PERSONAL_CATEGORY_CAP_CENTS),
        "RENTAL_ASSISTANCE": 0,
        "REPLACEMENT": 0,
    }
    if not habitable:
        comp["RENTAL_ASSISTANCE"] = fmr * rental_mo
        if repair > REPAIR_CATEGORY_CAP_CENTS:
            comp["REPLACEMENT"] = min(repair, REPLACEMENT_CAP_CENTS)
        else:
            comp["REPLACEMENT"] = 0
    return comp


def dob_offset(applicant_id, at_award=False, approved_at=None):
    """Sum of RECORDED DobRecord.amount_cents for the applicant.

    at_award: filter received_at <= approved_at (only DOB known at award time).
    at_recoupment (at_award=False): include ALL RECORDED DOB.
    """
    total = 0
    for d in STORE.dob_records.values():
        if d["applicant_id"] != applicant_id:
            continue
        if d["dob_status"] != "RECORDED":
            continue
        if at_award and approved_at is not None:
            recv = parse_iso(d["received_at"])
            if recv > approved_at:
                continue
        total += d["amount_cents"]
    return total


def recompute_total_dob(applicant):
    total = 0
    for d in STORE.dob_records.values():
        if d["applicant_id"] == applicant["id"] and d["dob_status"] == "RECORDED":
            total += d["amount_cents"]
    applicant["total_dob_cents"] = total


def case_line_items(case_id):
    """Award line items of a case, in fixed CATEGORY_ORDER."""
    items = [li for li in STORE.award_line_items.values() if li["ihp_case_id"] == case_id]
    order = {c: i for i, c in enumerate(CATEGORY_ORDER)}
    items.sort(key=lambda li: order.get(li["category"], 99))
    return items


def apply_cap_and_offset_waterfall(case, gross_by_category, max_grant, dob_offset_cents):
    """Two-step waterfall (PRD §3.6). Sets approved_amount_cents per line and
    returns total_approved_cents. Operates on the case's existing line items,
    keyed by category, in fixed CATEGORY_ORDER."""
    lines = case_line_items(case["id"])
    by_cat = {li["category"]: li for li in lines}

    gross_total = sum(gross_by_category.get(c, 0) for c in CATEGORY_ORDER)

    # Step 1 - proportional cap reduction (floor per line), remainder to last non-zero line
    capped = {}
    for c in CATEGORY_ORDER:
        capped[c] = gross_by_category.get(c, 0)
    if max_grant is not None and gross_total > max_grant:
        for c in CATEGORY_ORDER:
            g = gross_by_category.get(c, 0)
            # floor(g * max_grant / gross_total) using integer arithmetic
            capped[c] = (g * max_grant) // gross_total
        remainder = max_grant - sum(capped[c] for c in CATEGORY_ORDER)
        if remainder != 0:
            last_nonzero = None
            for c in CATEGORY_ORDER:
                if capped[c] > 0:
                    last_nonzero = c
            if last_nonzero is not None:
                capped[last_nonzero] += remainder

    # Step 2 - DOB waterfall over capped lines in fixed order
    remaining_offset = dob_offset_cents
    approved = {}
    for c in CATEGORY_ORDER:
        cap_line = capped[c]
        take = min(cap_line, remaining_offset)
        approved[c] = cap_line - take
        remaining_offset -= take

    # Write onto line items
    for c in CATEGORY_ORDER:
        li = by_cat.get(c)
        if li is None:
            continue
        li["gross_amount_cents"] = gross_by_category.get(c, 0)
        li["approved_amount_cents"] = approved[c]

    total_approved = sum(approved[c] for c in CATEGORY_ORDER if by_cat.get(c) is not None)
    return total_approved
