"""Global constants and pure calculation rules (scaffold section 1.3, PRD 2.6/3.x)."""

from decimal import Decimal, ROUND_HALF_UP

# ------------------------------------------------------------ global constants
SLA_SECONDS = 14400
CHALLENGE_TTL_SECONDS = 900
MAX_CHALLENGE_ATTEMPTS = 3
ATO_STEPUP_FLOOR = Decimal("45.00")
ATO_BLOCK_FLOOR = Decimal("75.00")
VELOCITY_CUSTOMER_WINDOW_SECONDS = 3600
VELOCITY_DEVICE_WINDOW_SECONDS = 86400
VELOCITY_PROMO_WINDOW_SECONDS = 2592000
GOOD_CUSTOMER_MIN_APPROVED = 2
GOOD_CUSTOMER_MIN_NET_CENTS = 20000
GOOD_CUSTOMER_BOOST = Decimal("20.00")
ESCALATION_BOOST = Decimal("15.00")
AMOUNT_TERM_CAP = Decimal("20.00")
RULE_SCORE_CAP = 100
BLENDED_SCORE_CAP = Decimal("200.00")
RULE_DOMINANT_MODEL_DAMPEN = Decimal("0.35")
RULE_DOMINANT_UPLIFT = Decimal("1.25")
REQUIRED_TRAINING_SEGMENTS = ("FRAUD_CNP", "FRAUD_ATO")
MIN_SAMPLES_PER_SEGMENT = 2
GUARANTEE_COVERAGE_CAP_CENTS = 500000
GUARANTEE_FEE_BPS = 250
GUARANTEE_COVERED_REASON_CODES = ("FRAUD_CNP", "FRAUD_ATO")
RULE_PACK_ACTIVATION_FREEZE_SECONDS = 3600
TIER_EXCEPTION_CAP_CENTS = {
    "STANDARD": 50000,
    "HIGH_VALUE": 500000,
    "BUSINESS": 2000000,
}
TIER_PRIORITY_BOOST = {
    "STANDARD": Decimal("0.00"),
    "HIGH_VALUE": Decimal("10.00"),
    "BUSINESS": Decimal("15.00"),
}
ATO_EVENT_BASE = {
    "LOGIN": Decimal("10.00"),
    "PASSWORD_CHANGE": Decimal("25.00"),
    "EMAIL_CHANGE": Decimal("30.00"),
    "SHIP_ADDRESS_ADD": Decimal("20.00"),
    "PAYMENT_INSTRUMENT_ADD": Decimal("35.00"),
}

# ------------------------------------------------------------------- enums
TIERS = ("STANDARD", "HIGH_VALUE", "BUSINESS")
ACCOUNT_STATUSES = ("ACTIVE", "LOCKED", "CLOSED")
ATO_POSTURES = ("CLEAR", "WATCH", "CONTAINED")
SENIORITIES = ("JUNIOR", "SENIOR", "LEAD")
ANALYST_STATUSES = ("AVAILABLE", "OFF_SHIFT", "SUSPENDED")
SKILL_FAMILIES = (
    "DEVICE",
    "BEHAVIORAL",
    "VELOCITY",
    "IDENTITY",
    "ADDRESS",
    "PROMO",
    "MODEL",
)
RULE_SIGNAL_FAMILIES = (
    "DEVICE",
    "BEHAVIORAL",
    "VELOCITY",
    "IDENTITY",
    "ADDRESS",
    "PROMO",
)
DEVICE_REPUTATIONS = ("NEW", "TRUSTED", "SUSPECT", "BLOCKED")
ADDRESS_CLASSIFICATIONS = ("RESIDENTIAL", "COMMERCIAL", "FREIGHT_FORWARDER", "PO_BOX")
DROP_RISK_STATES = ("CLEAN", "WATCH", "KNOWN_DROP")
BLEND_MODES = ("WEIGHTED", "RULE_DOMINANT")
RULE_PACK_STATUSES = ("DRAFT", "ACTIVE", "RETIRED")
RULE_CODES = (
    "DEV_MULTI_ACCOUNT",
    "DEV_EMULATOR",
    "BEH_FAST_CHECKOUT",
    "BEH_BULK_CART",
    "VEL_CUSTOMER_1H",
    "VEL_DEVICE_CARD_24H",
    "ID_GEO_MISMATCH",
    "ADDR_DROP_RISK",
    "ADDR_FREIGHT_FORWARDER",
    "PROMO_ADDRESS_ABUSE",
)
RULE_CODE_FAMILY = {
    "DEV_MULTI_ACCOUNT": "DEVICE",
    "DEV_EMULATOR": "DEVICE",
    "BEH_FAST_CHECKOUT": "BEHAVIORAL",
    "BEH_BULK_CART": "BEHAVIORAL",
    "VEL_CUSTOMER_1H": "VELOCITY",
    "VEL_DEVICE_CARD_24H": "VELOCITY",
    "ID_GEO_MISMATCH": "IDENTITY",
    "ADDR_DROP_RISK": "ADDRESS",
    "ADDR_FREIGHT_FORWARDER": "ADDRESS",
    "PROMO_ADDRESS_ABUSE": "PROMO",
}
MODEL_STATUSES = ("DRAFT", "TRAINING", "SHADOW", "ACTIVE", "RETIRED")
MODEL_ACTIONS = ("START_TRAINING", "PUBLISH_SHADOW", "REJECT", "PROMOTE", "RETIRE")
ASSESSMENT_STATES = (
    "PENDING_SIGNALS",
    "IN_REVIEW",
    "DECIDED_APPROVE",
    "DECIDED_DECLINE",
)
DECISIONS = ("APPROVE", "REVIEW", "DECLINE")
OUTCOME_LABELS = ("UNKNOWN", "LEGIT", "FRAUD")
CASE_STATES = ("QUEUED", "ASSIGNED", "ESCALATED", "RESOLVED_APPROVE", "RESOLVED_DECLINE")
AUTH_EVENT_TYPES = (
    "LOGIN",
    "PASSWORD_CHANGE",
    "EMAIL_CHANGE",
    "SHIP_ADDRESS_ADD",
    "PAYMENT_INSTRUMENT_ADD",
)
AUTH_OUTCOMES = ("ALLOWED", "STEP_UP_REQUIRED", "BLOCKED")
CHALLENGE_STATES = ("NONE", "ISSUED", "PASSED", "FAILED", "EXPIRED")
CHALLENGE_METHODS = ("OTP_SMS", "OTP_EMAIL", "THREE_DS")
CHALLENGE_ACTIONS = ("PASS", "FAIL", "REISSUE", "EXPIRE")
CHARGEBACK_REASON_CODES = (
    "FRAUD_CNP",
    "FRAUD_ATO",
    "PRODUCT_NOT_RECEIVED",
    "SUBSCRIPTION_CANCELED",
)
CHARGEBACK_STATES = ("RECEIVED", "REPRESENTED", "WON", "LOST")
CHARGEBACK_ACTIONS = ("REPRESENT", "WIN", "LOSE")
GUARANTEE_STATES = ("NOT_APPLICABLE", "REIMBURSED", "DENIED")
EXCEPTION_SCOPES = ("AUTO_APPROVE_UNDER_AMOUNT", "ADDRESS_WHITELIST")
EXCEPTION_STATES = ("REQUESTED", "APPROVED", "REJECTED", "REVOKED")
EXCEPTION_ACTIONS = ("APPROVE", "REJECT", "REVOKE")
COHORTS = ("DECISION_COHORT", "GOOD_CUSTOMER_COHORT")
SENIORITY_RANK = {"JUNIOR": 0, "SENIOR": 1, "LEAD": 2}


# --------------------------------------------------------------- arithmetic
def dec(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def rh(value, places):
    """ROUND_HALF_UP to `places` decimals (PRD 2.6)."""
    quantum = Decimal(1).scaleb(-places)
    return dec(value).quantize(quantum, rounding=ROUND_HALF_UP)


# ------------------------------------------------- 3 / 16 model calibration
def model_point_calibration(raw_probability, intercept, slope):
    p_cal = dec(intercept) + dec(slope) * dec(raw_probability)
    p_clamped = min(Decimal("1.0000"), max(Decimal("0.0000"), p_cal))
    return rh(p_clamped * 100, 2)


# ---------------------------------------------------- 4 / 16 blended score
def blended_risk_score(blend_mode, rule_weight, model_weight, rule_score, model_points):
    if blend_mode == "RULE_DOMINANT":
        inner = rh(dec(model_points) * RULE_DOMINANT_MODEL_DAMPEN, 1)
        raw = rh((dec(rule_score) + inner) * RULE_DOMINANT_UPLIFT, 2)
    else:
        raw = rh(
            dec(rule_weight) * dec(rule_score) + dec(model_weight) * dec(model_points),
            2,
        )
    return min(BLENDED_SCORE_CAP, raw)


# --------------------------------------------- 6 / 16 customer good standing
def customer_good_standing(customer):
    return (
        customer["account_status"] == "ACTIVE"
        and customer["ato_posture"] != "CONTAINED"
        and customer["confirmed_fraud_count"] == 0
        and customer["approved_count"] >= GOOD_CUSTOMER_MIN_APPROVED
        and customer["lifetime_net_approved_cents"] >= GOOD_CUSTOMER_MIN_NET_CENTS
    )


# ---------------------------------------------- 7 / 16 review case priority
def review_case_priority_score(assessment, customer, escalation_count):
    amount_term = min(AMOUNT_TERM_CAP, rh(dec(assessment["amount_cents"]) / 10000, 2))
    blended = dec(assessment.get("blended_score") or 0)
    total = (
        blended * Decimal("0.50")
        + amount_term
        + TIER_PRIORITY_BOOST[customer["tier"]]
        + (GOOD_CUSTOMER_BOOST if customer["good_customer_flag"] else Decimal("0.00"))
        + (ESCALATION_BOOST if escalation_count > 0 else Decimal("0.00"))
    )
    return rh(total, 2)


# ------------------------------------------------- 9 / 16 ato score
def ato_score_evaluation(event_type, ip_country, customer, device, first_seen):
    base = ATO_EVENT_BASE[event_type]
    geo_term = Decimal("25.00") if ip_country != customer["home_country"] else Decimal("0.00")
    if first_seen:
        device_term = Decimal("20.00")
    else:
        reputation = device["reputation"]
        if reputation == "BLOCKED":
            device_term = Decimal("40.00")
        elif reputation == "SUSPECT":
            device_term = Decimal("15.00")
        else:
            device_term = Decimal("0.00")
    failed_term = min(Decimal("15.00"), dec(customer["failed_login_count"]) * Decimal("5.00"))
    return min(Decimal("100.00"), rh(base + geo_term + device_term + failed_term, 2))


def ato_outcome(score):
    if score >= ATO_BLOCK_FLOOR:
        return "BLOCKED"
    if score >= ATO_STEPUP_FLOOR:
        return "STEP_UP_REQUIRED"
    return "ALLOWED"


# ----------------------------------------- 10 / 16 device reputation ladder
def device_reputation(fraud_confirmed_count, distinct_customer_count,
                      approved_use_count, emulator_flag):
    if fraud_confirmed_count >= 2:
        return "BLOCKED"
    if fraud_confirmed_count == 1 or distinct_customer_count >= 3 or emulator_flag:
        return "SUSPECT"
    if (
        fraud_confirmed_count == 0
        and approved_use_count >= 3
        and distinct_customer_count <= 2
    ):
        return "TRUSTED"
    return "NEW"


# --------------------------------------- 11 / 16 address intelligence ladder
def drop_risk_state(fraud_confirmed_count, distinct_customer_count, classification):
    if fraud_confirmed_count >= 2:
        return "KNOWN_DROP"
    if classification == "FREIGHT_FORWARDER" and distinct_customer_count >= 3:
        return "KNOWN_DROP"
    if (
        fraud_confirmed_count == 1
        or distinct_customer_count >= 3
        or classification in ("FREIGHT_FORWARDER", "PO_BOX")
    ):
        return "WATCH"
    return "CLEAN"


def reshipper_confidence(distinct_customer_count, promo_redemption_count, classification):
    total = (
        Decimal("0.20") * min(distinct_customer_count, 3)
        + Decimal("0.15") * min(promo_redemption_count, 2)
    )
    if classification == "FREIGHT_FORWARDER":
        total += Decimal("0.30")
    elif classification == "PO_BOX":
        total += Decimal("0.10")
    return rh(min(Decimal("1.00"), total), 2)


# --------------------------------------- 13 / 16 guarantee liability waterfall
def guarantee_liability_evaluation(chargeback, assessment):
    if chargeback["liability_shift"]:
        return ("DENIED", "LIABILITY_SHIFTED", 0, 0, 0)
    if chargeback["reason_code"] not in GUARANTEE_COVERED_REASON_CODES:
        return ("DENIED", "REASON_NOT_COVERED", 0, 0, 0)
    if assessment.get("applied_exception_id") is not None:
        return ("DENIED", "EXCEPTION_OVERRIDE", 0, 0, 0)
    if (
        assessment.get("decision") != "APPROVE"
        or assessment.get("decision_reason") == "MANUAL_REVIEW"
    ):
        return ("DENIED", "DECISION_NOT_ELIGIBLE", 0, 0, 0)
    eligible = min(
        chargeback["amount_cents"],
        assessment["amount_cents"],
        GUARANTEE_COVERAGE_CAP_CENTS,
    )
    fee = (eligible * GUARANTEE_FEE_BPS) // 10000
    return ("REIMBURSED", None, eligible, fee, eligible - fee)


# --------------------------------------------------- 15 / 16 report rates
def rate(numerator, denominator):
    if denominator == 0:
        return Decimal("0.0000")
    return rh(dec(numerator) / dec(denominator), 4)
