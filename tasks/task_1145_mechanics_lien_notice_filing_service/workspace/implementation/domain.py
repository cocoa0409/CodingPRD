"""Domain logic: rule effectiveness, furnishing dates, deadlines, claim amount
calculations, waiver waterfall, notice fee quote, pre-judgment interest, posture
derivation, and lazy auto-expiry — all evaluated against the logical clock."""

from decimal import Decimal, ROUND_HALF_UP

from core import (
    db, clock_date, parse_date, fmt_date, add_days, add_calendar_days, touch,
)

# ---------------------------------------------------------------------------
# Constants (pinned by PRD/scaffold)
# ---------------------------------------------------------------------------

RECIPIENT_BASE_CENTS = 1499
LENDER_SURCHARGE_PCT = Decimal("0.15")
DELIVERY_BASE_CENTS = 899
METHOD_MULTIPLIER = {
    "CERTIFIED_MAIL": Decimal("1.0"),
    "PERSONAL_SERVICE": Decimal("2.5"),
    "EMAIL_STATUTORY": Decimal("0.5"),
}

INTEREST_TIER_THRESHOLD_CENTS = 1000000
INTEREST_TIER_BUMP = Decimal("0.02")
MAX_AWARD_CENTS = 1000000000

UNCONDITIONAL_WAIVERS = {"UNCONDITIONAL_PROGRESS", "UNCONDITIONAL_FINAL"}
CONDITIONAL_WAIVERS = {"CONDITIONAL_PROGRESS", "CONDITIONAL_FINAL"}

OPEN_NOTICE_STATUSES = {"DRAFT", "SERVED", "DELIVERY_FAILED"}
OPEN_CLAIM_STATUSES = {"DRAFT", "AMOUNT_LOCKED", "FILED"}
OPEN_REFERRAL_STATUSES = {"DRAFT", "SENT", "DECLINED", "ACCEPTED"}


def round_half_up_cents(value):
    """Round a Decimal to integer cents, half-up."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Jurisdiction rules
# ---------------------------------------------------------------------------


def effective_rule(project):
    """Effective PUBLISHED rule for a project per §2.7:
    greatest effective_from <= clock date; tie-break created_at ASC."""
    today = clock_date()
    candidates = []
    for rule in db["jurisdiction_rules"].values():
        if rule["status"] != "PUBLISHED":
            continue
        if rule["state_code"] != project["state_code"] or rule["project_type"] != project["project_type"]:
            continue
        ef = parse_date(rule["effective_from"])
        if ef is None or ef > today:
            continue
        candidates.append(rule)
    if not candidates:
        return None
    candidates.sort(key=lambda r: (parse_date(r["effective_from"])))
    # greatest effective_from; tie-break earliest created_at
    best = None
    for r in candidates:
        if best is None:
            best = r
            continue
        r_ef, b_ef = parse_date(r["effective_from"]), parse_date(best["effective_from"])
        if r_ef > b_ef:
            best = r
        elif r_ef == b_ef and r["created_at"] < best["created_at"]:
            best = r
    return best


def published_rule_exists(state_code, project_type):
    for rule in db["jurisdiction_rules"].values():
        if (rule["status"] == "PUBLISHED" and rule["state_code"] == state_code
                and rule["project_type"] == project_type):
            return rule
    return None


# ---------------------------------------------------------------------------
# Furnishing dates
# ---------------------------------------------------------------------------


def active_spans(project_id):
    return [s for s in db["furnishing_spans"].values()
            if s["project_id"] == project_id and s["status"] == "ACTIVE"]


def first_furnishing_date(project_id):
    spans = active_spans(project_id)
    if not spans:
        return None
    return min(parse_date(s["start_date"]) for s in spans)


def last_furnishing_date(project, rule=None):
    """Variant per effective rule's counts_punch_list. Returns (date, variant)."""
    spans = active_spans(project["id"])
    if not spans:
        return None, None
    if rule is None:
        rule = effective_rule(project)
    inclusive = bool(rule and rule.get("counts_punch_list"))
    if inclusive:
        cands = [parse_date(s["end_date"]) for s in spans]
        variant = "inclusive"
    else:
        cands = [parse_date(s["end_date"]) for s in spans
                 if s["span_kind"] in ("BASE_CONTRACT", "CHANGE_ORDER")]
        variant = "strict"
    if not cands:
        return None, variant
    return max(cands), variant


def recompute_project_furnishing_dates(project):
    """Recompute and persist first/last furnishing dates on the project record."""
    project["first_furnishing_date"] = fmt_date(first_furnishing_date(project["id"]))
    last, _variant = last_furnishing_date(project)
    project["last_furnishing_date"] = fmt_date(last)


# ---------------------------------------------------------------------------
# Deadlines
# ---------------------------------------------------------------------------


def prelim_service_deadline(project, rule):
    """first_furnishing + rule.prelim_days on rule basis. None if no span/rule."""
    if rule is None:
        return None
    ffd = first_furnishing_date(project["id"])
    if ffd is None:
        return None
    return add_days(ffd, int(rule["prelim_days"]), rule["prelim_day_basis"])


# ---------------------------------------------------------------------------
# Waiver helpers
# ---------------------------------------------------------------------------


def waiver_is_effective(waiver, project_id):
    """Effectiveness per claimable_amount (conditional gating)."""
    if waiver["status"] != "APPLIED":
        return False
    if waiver["waiver_type"] in UNCONDITIONAL_WAIVERS:
        return True
    # conditional: needs a VERIFIED payment on the project with received_at >= period_end
    pend = parse_date(waiver["period_end"])
    for p in db["payments"].values():
        if p["project_id"] != project_id or p["status"] != "VERIFIED":
            continue
        if parse_date(p["received_at"]) >= pend:
            return True
    return False


def effective_waiver_sum(project_id):
    total = 0
    for w in db["waivers"].values():
        if w["project_id"] != project_id:
            continue
        if waiver_is_effective(w, project_id):
            total += w["amount_cents"]
    return total


def waiver_waterfall(project):
    """Allocate effective waivers to extras then contract pool.
    Returns (effective_waiver_cents, waived_to_extras_cents, waived_to_contract_cents)."""
    waivers = [w for w in db["waivers"].values()
               if w["project_id"] == project["id"] and waiver_is_effective(w, project["id"])]
    waivers.sort(key=lambda w: (w["period_end"], w["created_at"]))
    extras_pool = project["approved_extras_cents"]
    contract_pool = project["contract_value_cents"]
    effective_total = 0
    for w in waivers:
        amt = w["amount_cents"]
        effective_total += amt
        take = min(amt, extras_pool)
        extras_pool -= take
        remainder = amt - take
        take2 = min(remainder, contract_pool)
        contract_pool -= take2
    waived_to_extras = project["approved_extras_cents"] - extras_pool
    waived_to_contract = project["contract_value_cents"] - contract_pool
    return effective_total, waived_to_extras, waived_to_contract


def verified_paid_sum(project_id):
    return sum(p["amount_cents"] for p in db["payments"].values()
               if p["project_id"] == project_id and p["status"] == "VERIFIED")


def all_paid_sum(project_id):
    return sum(p["amount_cents"] for p in db["payments"].values()
               if p["project_id"] == project_id)


def all_waiver_sum(project_id):
    return sum(w["amount_cents"] for w in db["waivers"].values()
               if w["project_id"] == project_id and w["status"] != "VOIDED")


# ---------------------------------------------------------------------------
# Claim amounts
# ---------------------------------------------------------------------------


def provisional_amount(project):
    val = project["contract_value_cents"] + project["approved_extras_cents"] \
        - all_paid_sum(project["id"]) - all_waiver_sum(project["id"])
    return max(0, val)


def gross_claimable(project, rule):
    retainage_sub = 0 if rule["retainage_claimable"] else project["retainage_held_cents"]
    return project["contract_value_cents"] + project["approved_extras_cents"] - retainage_sub


def final_amount(project, rule):
    gross = gross_claimable(project, rule)
    vpaid = verified_paid_sum(project["id"])
    ewaiv = effective_waiver_sum(project["id"])
    if rule["cap_mode"] == "CONTRACT_BALANCE":
        cap = max(0, project["contract_value_cents"] - vpaid)
    else:
        cap = None  # UNCAPPED -> +infinity
    remainder = gross - vpaid - ewaiv
    if cap is not None:
        remainder = min(cap, remainder)
    return max(0, remainder)


def outstanding_for_claim(claim):
    """final_amount - VERIFIED payments allocated to this claim."""
    paid = sum(p["amount_cents"] for p in db["payments"].values()
               if p.get("lien_claim_id") == claim["id"] and p["status"] == "VERIFIED")
    return claim["final_amount_cents"] - paid


def recompute_claim_amounts(claim):
    """Recompute a DRAFT or AMOUNT_LOCKED claim's derived money fields.
    FILED+ claims: only outstanding_cents recomputes (final is frozen)."""
    project = db["projects"][claim["project_id"]]
    if claim["status"] == "DRAFT":
        claim["provisional_amount_cents"] = provisional_amount(project)
        claim["verified_paid_cents"] = verified_paid_sum(project["id"])
        eff, w_extras, w_contract = waiver_waterfall(project)
        claim["effective_waiver_cents"] = eff
        claim["waived_to_extras_cents"] = w_extras
        claim["waived_to_contract_cents"] = w_contract
    elif claim["status"] == "AMOUNT_LOCKED":
        rule = db["jurisdiction_rules"].get(claim["locked_rule_id"])
        if rule is not None:
            claim["final_amount_cents"] = final_amount(project, rule)
        claim["verified_paid_cents"] = verified_paid_sum(project["id"])
        eff, w_extras, w_contract = waiver_waterfall(project)
        claim["effective_waiver_cents"] = eff
        claim["waived_to_extras_cents"] = w_extras
        claim["waived_to_contract_cents"] = w_contract
        claim["outstanding_cents"] = outstanding_for_claim(claim)
    elif claim["status"] in ("FILED", "FORECLOSED"):
        claim["outstanding_cents"] = outstanding_for_claim(claim)
    touch(claim)


def compute_interest(claim):
    """Pre-judgment interest for FILED/FORECLOSED claims; (interest, total) or (None, None)."""
    if claim["status"] not in ("FILED", "FORECLOSED"):
        return None, None
    if claim["final_amount_cents"] is None or claim["filed_at"] is None:
        return None, None
    rule = db["jurisdiction_rules"].get(claim["locked_rule_id"])
    if rule is None:
        return None, None
    base = claim["final_amount_cents"]
    rate = Decimal(str(rule["interest_annual_rate"]))
    if base > INTEREST_TIER_THRESHOLD_CENTS:
        rate += INTEREST_TIER_BUMP
    filed = parse_date(claim["filed_at"])
    deadline = parse_date(claim["foreclosure_deadline"]) if claim["foreclosure_deadline"] else None
    end = clock_date()
    if deadline is not None and deadline < end:
        end = deadline
    days = (end - filed).days
    if days < 0:
        days = 0
    interest = round_half_up_cents(Decimal(base) * rate * Decimal(days) / Decimal(365))
    total = min(base + interest, MAX_AWARD_CENTS)
    return interest, total


def serialize_claim(claim):
    interest, total = compute_interest(claim)
    out = dict(claim)
    out["interest_cents"] = interest
    out["total_with_interest_cents"] = total
    return out


# ---------------------------------------------------------------------------
# Notice fee
# ---------------------------------------------------------------------------


def notice_fee_cents(recipient_role, delivery_method):
    mult = Decimal("1") + (LENDER_SURCHARGE_PCT if recipient_role == "LENDER" else Decimal("0"))
    recipient_line = round_half_up_cents(Decimal(RECIPIENT_BASE_CENTS) * mult)
    delivery_line = round_half_up_cents(Decimal(DELIVERY_BASE_CENTS) * METHOD_MULTIPLIER[delivery_method])
    return recipient_line + delivery_line


def bond_amount(claim, rule):
    return round_half_up_cents(Decimal(claim["final_amount_cents"]) * Decimal(str(rule["bond_pct"])))


# ---------------------------------------------------------------------------
# Lien posture
# ---------------------------------------------------------------------------


def recompute_posture(project):
    pid = project["id"]
    claims = [c for c in db["lien_claims"].values() if c["project_id"] == pid]
    referrals = [r for r in db["foreclosure_referrals"].values()
                 if db["lien_claims"].get(r["lien_claim_id"], {}).get("project_id") == pid]
    notices = [n for n in db["notices"].values() if n["project_id"] == pid]
    stops = [s for s in db["stop_notices"].values() if s["project_id"] == pid]
    bonds = [b for b in db["bond_claims"].values() if b["project_id"] == pid]

    if any(c["status"] == "FORECLOSED" for c in claims) or \
            any(r["status"] == "SUIT_FILED" for r in referrals):
        posture = "LITIGATION"
    elif any(c["status"] == "FILED" for c in claims) or \
            any(s["status"] == "SERVED" for s in stops) or \
            any(b["status"] == "SUBMITTED" for b in bonds):
        posture = "ENCUMBERED"
    elif any(n["status"] in ("SERVED", "PROOF_CONFIRMED") for n in notices):
        posture = "NOTICED"
    else:
        posture = "CLEAR"
    project["lien_posture"] = posture
    return posture


def recount_open_notices(project):
    pid = project["id"]
    count = sum(1 for n in db["notices"].values()
                if n["project_id"] == pid and n["status"] in OPEN_NOTICE_STATUSES)
    project["open_notice_count"] = count
    company = db["companies"].get(project["company_id"])
    if company is not None:
        ccount = sum(1 for n in db["notices"].values()
                     if db["projects"].get(n["project_id"], {}).get("company_id") == company["id"]
                     and n["status"] in OPEN_NOTICE_STATUSES)
        company["open_notice_count"] = ccount
    return count


# ---------------------------------------------------------------------------
# Lazy auto-expiry (evaluated against the logical clock)
# ---------------------------------------------------------------------------


def apply_notice_expiry(notice):
    """DRAFT -> EXPIRED when clock date > service_deadline. Returns True if changed."""
    if notice["status"] != "DRAFT":
        return False
    deadline = parse_date(notice["service_deadline"]) if notice["service_deadline"] else None
    if deadline is not None and clock_date() > deadline:
        notice["status"] = "EXPIRED"
        touch(notice)
        project = db["projects"].get(notice["project_id"])
        if project is not None:
            recount_open_notices(project)
            touch(project)
            recompute_posture(project)
        return True
    return False


def cancel_open_referrals(claim, reason):
    for r in db["foreclosure_referrals"].values():
        if r["lien_claim_id"] == claim["id"] and r["status"] in OPEN_REFERRAL_STATUSES:
            r["status"] = "CANCELLED"
            r["cancel_reason"] = reason
            touch(r)


def claim_exit_filed(claim, new_status, reason):
    """Common side effects for a FILED claim leaving FILED."""
    claim["status"] = new_status
    touch(claim)
    project = db["projects"].get(claim["project_id"])
    if project is not None:
        if new_status in ("RELEASED", "BONDED_OFF", "EXPIRED"):
            project["open_lien_count"] = max(0, project["open_lien_count"] - 1)
        touch(project)
        recompute_posture(project)
    cancel_open_referrals(claim, reason)


def apply_claim_expiry(claim):
    """FILED -> EXPIRED when clock date > foreclosure_deadline and no SUIT_FILED referral."""
    if claim["status"] != "FILED":
        return False
    deadline = parse_date(claim["foreclosure_deadline"]) if claim["foreclosure_deadline"] else None
    if deadline is None or clock_date() <= deadline:
        return False
    suit_filed = any(r["lien_claim_id"] == claim["id"] and r["status"] == "SUIT_FILED"
                     for r in db["foreclosure_referrals"].values())
    if suit_filed:
        return False
    claim_exit_filed(claim, "EXPIRED", "MOOT_EXPIRED")
    return True


def apply_stop_notice_expiry(stop):
    if stop["status"] != "DRAFT":
        return False
    project = db["projects"].get(stop["project_id"])
    if project is None:
        return False
    rule = effective_rule(project)
    if rule is None:
        return False
    last, _ = last_furnishing_date(project, rule)
    if last is None:
        return False
    deadline = add_calendar_days(last, int(rule["stop_notice_days"]))
    if clock_date() > deadline:
        stop["status"] = "EXPIRED"
        touch(stop)
        return True
    return False


def apply_bond_claim_expiry(bond):
    if bond["status"] != "DRAFT":
        return False
    project = db["projects"].get(bond["project_id"])
    if project is None:
        return False
    rule = effective_rule(project)
    if rule is None:
        return False
    last, _ = last_furnishing_date(project, rule)
    if last is None:
        return False
    deadline = add_calendar_days(last, int(rule["bond_claim_days"]))
    if clock_date() > deadline:
        bond["status"] = "EXPIRED"
        touch(bond)
        return True
    return False


def lazy_refresh_project(project):
    """Apply due auto-expiry to every child of the project (used on reads of the project)."""
    for n in list(db["notices"].values()):
        if n["project_id"] == project["id"]:
            apply_notice_expiry(n)
    for c in list(db["lien_claims"].values()):
        if c["project_id"] == project["id"]:
            apply_claim_expiry(c)
    for s in list(db["stop_notices"].values()):
        if s["project_id"] == project["id"]:
            apply_stop_notice_expiry(s)
    for b in list(db["bond_claims"].values()):
        if b["project_id"] == project["id"]:
            apply_bond_claim_expiry(b)
    recompute_project_furnishing_dates(project)
    recompute_posture(project)
