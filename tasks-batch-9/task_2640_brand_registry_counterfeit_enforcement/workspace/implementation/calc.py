"""The seven derived quantities of PRD 3.  Every arithmetic step is exact
decimal arithmetic; every rounding step is half-up."""

from decimal import Decimal, ROUND_HALF_UP

import db

ZERO = Decimal("0")
ONE = Decimal("1")

# ---------------------------------------------------------------- rounding ---

def q(value, places):
    """Round half-up to the given number of decimal places."""
    exponent = Decimal(1).scaleb(-places)
    return Decimal(value).quantize(exponent, rounding=ROUND_HALF_UP)


def q0(value):
    return q(value, 0)


def q2(value):
    return q(value, 2)


def q4(value):
    return q(value, 4)


# -------------------------------------------------- listing_match_score ------

MATCH_THRESHOLD = Decimal("0.7000")
IMAGE_WEIGHT = Decimal("0.45")
TEXT_WEIGHT = Decimal("0.35")
PRICE_WEIGHT = Decimal("0.20")
BLOCKED_BOOST = Decimal("0.05")
STRIKE_BOOST = Decimal("0.03")
STRIKE_BOOST_THRESHOLD = Decimal("10.00")


def price_deviation_factor(authorized_msrp_cents, price_cents):
    msrp = Decimal(int(authorized_msrp_cents))
    price = Decimal(int(price_cents))
    if msrp == 0:
        raw = ZERO
    else:
        raw = (msrp - price) / msrp
    clamped = min(ONE, max(ZERO, raw))
    return q4(clamped)


def seller_risk_boost(seller):
    """A single mutually exclusive boost - the first matching rung wins."""
    if seller["status"] == "BLOCKED":
        return BLOCKED_BOOST
    if Decimal(seller["standalone_strike_points"]) >= STRIKE_BOOST_THRESHOLD:
        return STRIKE_BOOST
    return ZERO


def listing_match_score(image_score, text_score, pdf, seller):
    raw = (IMAGE_WEIGHT * image_score + TEXT_WEIGHT * text_score
           + PRICE_WEIGHT * pdf)
    boosted = raw + seller_risk_boost(seller)
    return q4(min(Decimal("1.0000"), boosted))


def monitor_verdict(match_score):
    return "FLAGGED" if match_score >= MATCH_THRESHOLD else "CLEARED"


def violation_type(verdict, image_score, text_score, pdf):
    """Ordered ladder - the first matching rung wins."""
    if verdict == "CLEARED":
        return "NONE"
    if image_score >= Decimal("0.85"):
        return "COUNTERFEIT"
    if text_score >= Decimal("0.80"):
        return "TRADEMARK"
    if image_score >= Decimal("0.60") and pdf >= Decimal("0.50"):
        return "COPYRIGHT"
    return "TRADEMARK"


def screen(listing, brand, seller, image_score, text_score):
    pdf = price_deviation_factor(brand["authorized_msrp_cents"],
                                 listing["price_cents"])
    match_score = listing_match_score(image_score, text_score, pdf, seller)
    verdict = monitor_verdict(match_score)
    return {
        "image_match_score": image_score,
        "text_match_score": text_score,
        "price_deviation_factor": pdf,
        "match_score": match_score,
        "monitor_status": verdict,
        "violation_type": violation_type(verdict, image_score, text_score, pdf),
    }


# --------------------------------------------- claim_substantiation_score ----

SUBSTANTIATION_THRESHOLD = Decimal("85.00")
PRELIMINARY_FACTOR = Decimal("0.80")
CORROBORATION_BONUS = Decimal("20.00")
STRIKE_NORMALISER = Decimal("37.65")


def registration_strength(registration, listing):
    """Ordered ladder over the asserted registration."""
    status = registration["status"]
    if (status == "REGISTERED" and registration["principal_register"]
            and registration["nice_class"] == listing["nice_class"]):
        return Decimal("1.00")
    if status == "REGISTERED":
        return Decimal("0.60")
    if status == "PENDING":
        return Decimal("0.30")
    return Decimal("0.00")


def seller_history_factor(standalone_points):
    return q4(min(ONE, Decimal(standalone_points) / STRIKE_NORMALISER))


def substantiation_base(match_score, strength, standalone_points):
    shf = seller_history_factor(standalone_points)
    return (Decimal("60") * Decimal(match_score)
            + Decimal("25") * Decimal(strength)
            + Decimal("15") * shf)


def preliminary_score(base):
    """No corroboration bonus, no cap."""
    return q2(PRELIMINARY_FACTOR * base)


def has_corroboration(claim_id):
    for buy in db.values("test_buys"):
        if (buy["claim_id"] == claim_id
                and buy["status"] == "AUTHENTICATED_COUNTERFEIT"
                and buy["chain_of_custody_ref"] is not None):
            return True
    return False


def full_score(base, claim_id):
    bonus = CORROBORATION_BONUS if has_corroboration(claim_id) else ZERO
    return q2(min(Decimal("100.00"), base + bonus))


def claim_inputs(claim):
    listing = db.get("listings", claim["listing_id"])
    seller = db.get("sellers", listing["seller_id"])
    registration = db.get("registrations", claim["asserted_registration_id"])
    return listing, seller, registration


def recompute_full_substantiation(claim):
    listing, seller, registration = claim_inputs(claim)
    strength = registration_strength(registration, listing)
    base = substantiation_base(listing["match_score"], strength,
                               seller["standalone_strike_points"])
    return full_score(base, claim["id"]), strength


# ------------------------------------------------ test_buy_billable_total ----

FEE_TIERS = (
    (5000, Decimal("0.15")),
    (20000, Decimal("0.12")),
    (50000, Decimal("0.09")),
)
TOP_RATE = Decimal("0.06")


def service_fee_rate(subtotal_cents):
    """The tier is selected from the subtotal alone and never re-selected from
    the billable total."""
    for ceiling, rate in FEE_TIERS:
        if subtotal_cents <= ceiling:
            return rate
    return TOP_RATE


def test_buy_pricing(purchase_price_cents, shipping_cents, lab_fee_cents):
    subtotal = int(purchase_price_cents) + int(shipping_cents) + int(lab_fee_cents)
    rate = service_fee_rate(subtotal)
    fee = int(q0(Decimal(subtotal) * rate))
    return {
        "subtotal_cents": subtotal,
        "service_fee_rate": rate,
        "service_fee_cents": fee,
        "billable_total_cents": subtotal + fee,
    }


# ------------------------------------------ evidence_completeness_score ------

REQUIRED_ITEM_TYPES = {
    "COUNTERFEIT": ["TEST_BUY_INVOICE", "LAB_AUTHENTICATION_REPORT",
                    "LISTING_SCREENSHOT", "REGISTRATION_CERTIFICATE"],
    "TRADEMARK": ["LISTING_SCREENSHOT", "REGISTRATION_CERTIFICATE",
                  "MARK_COMPARISON"],
    "COPYRIGHT": ["LISTING_SCREENSHOT", "COPYRIGHT_DEPOSIT_COPY",
                  "WORK_COMPARISON"],
}

OPTIONAL_ITEM_TYPES = ["SELLER_PROFILE_SNAPSHOT", "PRICE_HISTORY_EXPORT",
                       "CUSTOMER_COMPLAINT", "CUSTOMS_SEIZURE_NOTICE",
                       "SHIPPING_LABEL_PHOTO"]

ALL_ITEM_TYPES = sorted(
    set(OPTIONAL_ITEM_TYPES)
    | set(t for types in REQUIRED_ITEM_TYPES.values() for t in types)
)

OPTIONAL_TARGET = Decimal("4")
COMPLETENESS_THRESHOLD = Decimal("0.8000")
COVERAGE_WEIGHT = Decimal("0.70")
OPTIONAL_WEIGHT = Decimal("0.30")


def evidence_completeness(items, violation_type_value):
    required = REQUIRED_ITEM_TYPES[violation_type_value]
    present = set(i["item_type"] for i in items)
    coverage = len([t for t in required if t in present])
    optional_count = len([i for i in items if i["item_type"] not in required])
    coverage_term = Decimal(coverage) / Decimal(len(required))
    optional_term = min(ONE, Decimal(optional_count) / OPTIONAL_TARGET)
    score = q4(COVERAGE_WEIGHT * coverage_term + OPTIONAL_WEIGHT * optional_term)
    return coverage, len(required), score


def evidence_sealable(coverage, required_total, score):
    return coverage == required_total and score >= COMPLETENESS_THRESHOLD
