"""Calculation rules (SCAFFOLD §1.3 / PRD §3). All money is integer cents."""
import db

# ---- coupon credential constants (SCAFFOLD coupon_credential_assignment) ----
NETWORK_BIN = "610279"
GOLD_PCN = "GDX"
STANDARD_PCN = "STD"
GOLD_GROUP = "GOLDRX"
STANDARD_GROUP = "DISCRX"

# ---- gold fee constants (SCAFFOLD gold_fee_resolution) ----
INDIVIDUAL_FEE_CENTS = 999
FAMILY_FEE_CENTS = 1999
MAX_FAMILY_COVERED = 5
MEMBERSHIP_BUFFER_SECONDS = 86400


def member_is_gold(member):
    """A member is Gold exactly when active_gold_membership_id is not null."""
    return member.get("active_gold_membership_id") is not None


def quote_in_window(quote, now_dt):
    """Half-open window [effective_at, expires_at): effective_at <= clock < expires_at."""
    eff = db.parse_iso(quote["effective_at"])
    exp = db.parse_iso(quote["expires_at"])
    return eff <= now_dt < exp


def eff_price(quote, is_gold):
    return quote["gold_price_cents"] if is_gold else quote["discount_price_cents"]


def basis_price(quote, pricing_basis):
    return quote["gold_price_cents"] if pricing_basis == "GOLD" else quote["discount_price_cents"]


# ---------------------------------------------------------------------------
# best_price_selection (on comparison run)
# ---------------------------------------------------------------------------
def best_price_selection(comparison, member):
    """Return (selected_pharmacy_id, best_price_cents, candidate_count)."""
    now_dt = db.clock_now_dt()
    is_gold = member_is_gold(member)
    pool = []
    for quote in db.price_quotes.values():
        if quote["drug_id"] != comparison["drug_id"]:
            continue
        if quote["status"] != "PUBLISHED":
            continue
        if not quote_in_window(quote, now_dt):
            continue
        pharmacy = db.pharmacies.get(quote["pharmacy_id"])
        if pharmacy is None:
            continue
        if pharmacy["status"] != "ACTIVE":
            continue
        if pharmacy["state_code"] != comparison["state_code"]:
            continue
        pool.append((quote, pharmacy))

    candidate_count = len(pool)
    if candidate_count == 0:
        return None, None, 0

    # sort: ascending eff_price; tie-break lower dispense_fee_cents; tie-break earlier created_at ASC
    pool.sort(key=lambda pair: (
        eff_price(pair[0], is_gold),
        pair[1]["dispense_fee_cents"],
        pair[0]["created_at"],
        pair[0]["id"],
    ))
    winner_quote, winner_pharmacy = pool[0]
    return winner_pharmacy["id"], eff_price(winner_quote, is_gold), candidate_count


# ---------------------------------------------------------------------------
# resolve_quote — pick the winning PUBLISHED quote for a (pharmacy, drug) at clock
# Used by savings_calculation and mail_order_total.
#   greatest effective_at; tie-break earliest created_at ASC.
# ---------------------------------------------------------------------------
def resolve_quote(pharmacy_id, drug_id):
    now_dt = db.clock_now_dt()
    candidates = []
    for quote in db.price_quotes.values():
        if quote["pharmacy_id"] != pharmacy_id:
            continue
        if quote["drug_id"] != drug_id:
            continue
        if quote["status"] != "PUBLISHED":
            continue
        if not quote_in_window(quote, now_dt):
            continue
        candidates.append(quote)
    if not candidates:
        return None
    candidates.sort(key=lambda q: (
        _neg_iso_key(q["effective_at"]),  # greatest effective_at first
        q["created_at"],                   # earliest created_at next
        q["id"],
    ))
    return candidates[0]


def _neg_iso_key(iso_str):
    """Sort key that orders later instants first (descending effective_at)."""
    dt = db.parse_iso(iso_str)
    return -dt.timestamp()


# ---------------------------------------------------------------------------
# copay_offset_calculation (waterfall: min of three caps)
# ---------------------------------------------------------------------------
def copay_offset(copay_card, discounted_cents):
    cap_a = copay_card["per_fill_cap_cents"]
    cap_b = copay_card["remaining_benefit_cents"]
    cap_c = discounted_cents
    return min(cap_a, cap_b, cap_c)


# ---------------------------------------------------------------------------
# discount_vs_insurance_choice (threshold)
# ---------------------------------------------------------------------------
def discount_vs_insurance(best_price_cents, copay_cents, deductible_remaining_cents, awp_cents):
    discount_net = best_price_cents
    insurance_net = copay_cents + min(deductible_remaining_cents, awp_cents)
    if discount_net < insurance_net:
        return "DISCOUNT"
    if discount_net > insurance_net:
        return "INSURANCE"
    return "TIE_DISCOUNT"


# ---------------------------------------------------------------------------
# coupon_credential_assignment
# ---------------------------------------------------------------------------
def coupon_credentials(member, drug):
    is_gold = member_is_gold(member)
    pricing_basis = "GOLD" if is_gold else "DISCOUNT"
    if pricing_basis == "GOLD":
        pcn, group_code = GOLD_PCN, GOLD_GROUP
    else:
        pcn, group_code = STANDARD_PCN, STANDARD_GROUP
    # member_code: uppercase(last 8 hex chars of Member.id with '-' removed) + '-' + Drug.ndc
    hex_only = member["id"].replace("-", "")
    suffix = hex_only[-8:].upper()
    member_code = suffix + "-" + drug["ndc"]
    return {
        "bin": NETWORK_BIN,
        "pcn": pcn,
        "group_code": group_code,
        "member_code": member_code,
        "pricing_basis": pricing_basis,
    }


# ---------------------------------------------------------------------------
# gold_fee_resolution
# ---------------------------------------------------------------------------
def gold_monthly_fee(tier):
    return INDIVIDUAL_FEE_CENTS if tier == "GOLD_INDIVIDUAL" else FAMILY_FEE_CENTS


# ---------------------------------------------------------------------------
# lifetime_savings_reconciliation
# ---------------------------------------------------------------------------
def recompute_lifetime_savings(member_id):
    """Sum savings_cents over ADJUDICATED claims whose card belongs to this member."""
    total = 0
    for claim in db.claims.values():
        if claim["status"] != "ADJUDICATED":
            continue
        card = db.discount_cards.get(claim["discount_card_id"])
        if card is None:
            continue
        if card["member_id"] != member_id:
            continue
        total += claim["savings_cents"]
    member = db.members.get(member_id)
    if member is not None:
        member["lifetime_savings_cents"] = total
        db.touch(member)
