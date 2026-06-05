"""Calculation rules (SCAFFOLD §1.3 / PRD §3).

These are pure functions over records + clock; they perform no mutation.
"""

from decimal import Decimal, ROUND_HALF_UP

from clock import parse_iso8601, add_calendar_days

CAP_GAP_CEILING_DAYS = 180
EXPIRING_WINDOW_DAYS = 30

# onboarding_compliance_risk weights (SCAFFOLD constants).
W_OVERDUE = 40
W_EVERIFY_LATE = 25
W_OPEN_TNC = 20
W_UNRESOLVED_RECEIPT = 15
W_EXPIRING_AUTH = 10
CLAMP_MAX = 100


def is_document_valid(expiration_iso, is_receipt, clock):
    """document_validity (PRD §3.3, SCAFFOLD document_validity).

    Valid iff the controlling expiration is strictly AFTER the clock. Receipts
    are exempt at acceptance. A null expiration (non-expiring) is always valid.
    Boundary: expiry == clock is EXPIRED (strict >).
    """
    if is_receipt:
        return True
    if expiration_iso is None:
        return True
    exp = parse_iso8601(expiration_iso)
    return exp > clock


def section2_path(chosen_docs):
    """section2_document_sufficiency (PRD §3.3).

    chosen_docs: list of IdentityDocument records. Returns "LIST_A" or
    "LIST_B_AND_C" when the cardinality matches exactly one path, else None.
    """
    a = [d for d in chosen_docs if d.get("list_category") == "LIST_A"]
    b = [d for d in chosen_docs if d.get("list_category") == "LIST_B"]
    c = [d for d in chosen_docs if d.get("list_category") == "LIST_C"]
    if len(a) == 1 and len(b) == 0 and len(c) == 0:
        return "LIST_A"
    if len(a) == 0 and len(b) == 1 and len(c) == 1:
        return "LIST_B_AND_C"
    return None


def receipt_resolution_deadline(section2_completed_at_iso):
    """= section2_completed_at + 90 calendar days (PRD §3.3)."""
    base = parse_iso8601(section2_completed_at_iso)
    return add_calendar_days(base, 90)


def stem_cap_gap_days(requested_gap_days):
    """cap_gap_days = min(requested, 180). Default requested 0 when omitted
    (PRD §3.6 / SCAFFOLD stem_extension_window). Negative requests floor at 0."""
    req = requested_gap_days if requested_gap_days is not None else 0
    if req < 0:
        req = 0
    return min(req, CAP_GAP_CEILING_DAYS)


def effective_valid_until(valid_until_iso, cap_gap_days):
    """effective_valid_until = valid_until + cap_gap_days days (whole-day)."""
    base = parse_iso8601(valid_until_iso)
    return add_calendar_days(base, cap_gap_days)


def compliance_risk(onboarding, everify_case, accepted_receipt_docs,
                    controlling_auths, clock):
    """onboarding_compliance_risk (PRD §3.8 / SCAFFOLD onboarding_compliance_risk).

    Weighted sum, summed first then rounded ONCE half up, then clamped [0,100].
    Per-term rounding is forbidden.
    """
    score = Decimal(0)

    if onboarding.get("is_overdue", False):
        score += Decimal(W_OVERDUE)

    if everify_case is not None and everify_case.get("was_late", False):
        score += Decimal(W_EVERIFY_LATE)

    # Open TNC: tnc_type != NONE and onboarding not AUTHORIZED.
    if (everify_case is not None
            and everify_case.get("tnc_type", "NONE") != "NONE"
            and onboarding.get("status") != "AUTHORIZED"):
        score += Decimal(W_OPEN_TNC)

    # 15 per accepted receipt whose resolution deadline is earlier than clock.
    unresolved = 0
    for d in accepted_receipt_docs:
        if not d.get("is_receipt"):
            continue
        if d.get("status") != "ACCEPTED":
            continue
        deadline_iso = d.get("receipt_resolution_deadline")
        if deadline_iso is None:
            continue
        if parse_iso8601(deadline_iso) < clock:
            unresolved += 1
    score += Decimal(W_UNRESOLVED_RECEIPT) * unresolved

    # 10 if any controlling auth's effective_valid_until is within 30 days of clock.
    for a in controlling_auths:
        evu_iso = a.get("effective_valid_until")
        if evu_iso is None:
            continue
        evu = parse_iso8601(evu_iso)
        window_end = add_calendar_days(clock, EXPIRING_WINDOW_DAYS)
        # "within 30 days of clock": evu lies in [clock, clock+30].
        if clock <= evu <= window_end:
            score += Decimal(W_EXPIRING_AUTH)
            break

    rounded = int(score.quantize(Decimal(0), rounding=ROUND_HALF_UP))
    if rounded > CLAMP_MAX:
        rounded = CLAMP_MAX
    if rounded < 0:
        rounded = 0
    return rounded
