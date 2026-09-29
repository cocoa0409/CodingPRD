"""Enumerations, pinned constants and every calculation from PRD section 3."""
from decimal import Decimal

from core import D0, add_days, dceil, dfloor, floor_days_between, q

# --------------------------------------------------------------------- enums
ISO = ["CAISO", "ERCOT", "PJM", "MISO"]
SETTLEMENT_POINT_TYPE = ["HUB", "NODE"]
CREDIT_RATING = ["AAA", "AA", "A", "BBB", "BB", "B", "CCC", "NR"]
RATING_AGENCY = ["SP", "MOODYS", "FITCH", "NONE"]
DISCLOSURE_FRAMEWORK = ["CDP_AND_TCFD", "TCFD_ONLY", "CDP_ONLY", "NONE"]
QUALIFICATION_STATUS = ["DRAFT", "UNDER_REVIEW", "QUALIFIED", "CONDITIONAL",
                        "WATCHLIST", "REJECTED"]
CREDIT_SCORE_VARIANT = ["STANDALONE", "GUARANTOR_SUPPORTED"]
CREDIT_TIER = ["PRIME", "STANDARD", "SUBPRIME", "DECLINED"]
TECHNOLOGY = ["SOLAR", "WIND", "STORAGE_HYBRID"]
PROJECT_STATUS = ["PRE_DEVELOPMENT", "PERMITTED", "INTERCONNECTION_APPROVED",
                  "NTP_ISSUED", "OPERATIONAL"]
PRODUCT_TYPE = ["PHYSICAL_DELIVERY", "VIRTUAL_CFD", "AGGREGATED"]
SETTLEMENT_FREQUENCY = ["HOURLY", "MONTHLY"]
SHAPE_PRODUCT = ["AS_GENERATED", "SOLAR_SHAPED_16X5", "BASELOAD_FIRM"]
BASIS_RESPONSIBILITY = ["SELLER", "SHARED", "BUYER"]
DEAL_STATUS = ["DRAFT", "TERM_SHEET_ISSUED", "UNDER_NEGOTIATION", "TERMS_AGREED",
               "EXECUTED", "EFFECTIVE", "TERMINATED"]
CREDIT_STATUS = ["NOT_SUBMITTED", "SUBMITTED", "APPROVED", "DECLINED",
                 "SUPPORT_SHORTFALL"]
PRICE_TIER = ["LOW", "MID", "HIGH"]
TERMINATION_REASON = ["CP_FAILURE", "BUYER_DEFAULT", "SELLER_DEFAULT",
                      "EXTENDED_FORCE_MAJEURE", "COD_DEADLINE_MISSED"]
ALLOCATION_STATUS = ["PROPOSED", "CONFIRMED", "WITHDRAWN"]
PROPOSED_BY = ["DEVELOPER", "OFFTAKER"]
ROUND_STATUS = ["OPEN", "ACCEPTED", "COUNTERED", "EXPIRED"]
INSTRUMENT_TYPE = ["LETTER_OF_CREDIT", "PARENT_GUARANTEE", "CASH_COLLATERAL"]
INSTRUMENT_PURPOSE = ["DEVELOPMENT_SECURITY", "PERFORMANCE_SECURITY"]
INSTRUMENT_STATUS = ["PROPOSED", "POSTED", "RELEASED", "DRAWN", "EXPIRED"]
CP_TYPE = ["PERMITTING", "INTERCONNECTION", "NOTICE_TO_PROCEED",
           "REGISTRY_ACCOUNT"]
CP_STATUS = ["PENDING", "SATISFIED", "WAIVED", "FAILED"]
PERIOD_STATUS = ["OPEN", "CALCULATED", "INVOICED", "DISPUTED", "SETTLED"]
CURTAILMENT_FLAG = ["NONE", "ECONOMIC", "GRID_EMERGENCY", "BUYER_REQUESTED"]
REGISTRY = ["WREGIS", "MRETS", "NAR"]
BATCH_STATUS = ["MINTED", "TRANSFERRED", "RETIRED", "CANCELLED"]
CLAIM_SUBSTANTIATION = ["UNSUBSTANTIATED", "SUBSTANTIATED"]
EVENT_TYPE = ["CHANGE_IN_LAW", "FORCE_MAJEURE", "CURTAILMENT"]
ALLOCATION_OUTCOME = ["SELLER_BEARS", "BUYER_BEARS", "SHARED"]
RISK_STATUS = ["CLAIMED", "ACCEPTED", "REJECTED"]
MILESTONE = ["PERMITTED", "INTERCONNECTION_APPROVED", "NOTICE_TO_PROCEED",
             "OPERATIONAL"]

# ----------------------------------------------------------------- constants
RATING_POINTS = {
    "AAA": Decimal("100"), "AA": Decimal("92"), "A": Decimal("84"),
    "BBB": Decimal("72"), "BB": Decimal("55"), "B": Decimal("38"),
    "CCC": Decimal("20"), "NR": Decimal("10"),
}
DISCLOSURE_POINTS = {
    "CDP_AND_TCFD": Decimal("100"), "TCFD_ONLY": Decimal("80"),
    "CDP_ONLY": Decimal("70"), "NONE": Decimal("30"),
}
RATING_WEIGHT = Decimal("0.55")
LEVERAGE_WEIGHT = Decimal("0.30")
DISCLOSURE_WEIGHT = Decimal("0.15")
GUARANTOR_RATING_NOTCH_PENALTY = Decimal("8")

TIER_THRESHOLDS = [
    ("PRIME", Decimal("80.00")),
    ("STANDARD", Decimal("62.00")),
    ("SUBPRIME", Decimal("45.00")),
]

SBT_POINTS = Decimal("40")
RE100_POINTS = Decimal("30")
SCOPE2_POINTS = Decimal("20")
SCOPE2_TARGET_YEAR_CUTOFF = 2030
DISCLOSURE_ANY_POINTS = Decimal("10")

TIER_CAP_USD = {
    "PRIME": Decimal("25000000"), "STANDARD": Decimal("10000000"),
    "SUBPRIME": Decimal("2000000"), "DECLINED": Decimal("0"),
}
TIER_EBITDA_PCT = {
    "PRIME": Decimal("0.05"), "STANDARD": Decimal("0.02"),
    "SUBPRIME": Decimal("0.005"), "DECLINED": Decimal("0.0"),
}

PRICING_BASE_YEAR = 2026
PRICE_TIER_LOW_MAX = Decimal("40.00")
PRICE_TIER_MID_MAX = Decimal("60.00")
SHAPE_PREMIUM = {
    "AS_GENERATED": {"LOW": Decimal("0.00"), "MID": Decimal("0.00"),
                     "HIGH": Decimal("0.00")},
    "SOLAR_SHAPED_16X5": {"LOW": Decimal("2.00"), "MID": Decimal("3.10"),
                          "HIGH": Decimal("4.00")},
    "BASELOAD_FIRM": {"LOW": Decimal("4.50"), "MID": Decimal("6.25"),
                      "HIGH": Decimal("8.00")},
}
BASIS_ADDER = {"SELLER": Decimal("1.50"), "SHARED": Decimal("0.75"),
               "BUYER": Decimal("0.00")}

CAPACITY_FACTOR = {"SOLAR": Decimal("0.28"), "WIND": Decimal("0.42"),
                   "STORAGE_HYBRID": Decimal("0.35")}
HOURS_PER_YEAR = Decimal("8760")

COLLATERAL_INCREMENT_USD = Decimal("250000")

LC_HAIRCUT_PCT = {
    "AAA": Decimal("0.00"), "AA": Decimal("0.00"), "A": Decimal("0.00"),
    "BBB": Decimal("10.00"), "BB": Decimal("35.00"),
}
PG_HAIRCUT_PCT = {
    "PRIME": Decimal("0.00"), "STANDARD": Decimal("25.00"),
    "SUBPRIME": Decimal("60.00"),
}
CASH_HAIRCUT_PCT = Decimal("0.00")

DEEMED_SHARE = {"SELLER_BEARS": Decimal("0.00"), "SHARED": Decimal("0.50"),
                "BUYER_BEARS": Decimal("1.00")}
BASIS_SHARE_TO_BUYER = {"SELLER": Decimal("0.00"), "SHARED": Decimal("0.50"),
                        "BUYER": Decimal("1.00")}
NEGATIVE_PRICE_FLOOR = Decimal("0.00")

CP_PERMITTING_DAYS = 270
CP_INTERCONNECTION_DAYS = 540
CP_NTP_DAYS = 720
CP_REGISTRY_DAYS = 60

ROUND_RESPONSE_DAYS = 14
SUPPORT_CURE_DAYS = 10
CP_CURE_DAYS = 15
CP_WAIVER_EXTENSION_DAYS = 30
FM_TERMINATION_DAYS = 180
REC_CLAIM_WINDOW_YEARS = 1
MIN_TENOR_DAYS = 365
SECONDS_PER_DAY = 86400


# --------------------------------------------------------- offtaker scoring
def leverage_points(net_debt_to_ebitda):
    raw = Decimal("100") - Decimal("10") * Decimal(net_debt_to_ebitda)
    if raw < 0:
        return Decimal("0")
    if raw > 100:
        return Decimal("100")
    return raw


def credit_tier_for_score(score):
    for tier, floor_value in TIER_THRESHOLDS:
        if score >= floor_value:
            return tier
    return "DECLINED"


def offtaker_credit_score(offtaker, guarantor):
    """Returns (score, variant, tier)."""
    own_rating = RATING_POINTS[offtaker["credit_rating"]]
    own_leverage = leverage_points(offtaker["net_debt_to_ebitda"])
    disclosure = DISCLOSURE_POINTS[offtaker["disclosure_framework"]]

    supported = (offtaker.get("parent_guarantor_offtaker_id") is not None
                 and guarantor is not None
                 and guarantor.get("qualification_status") == "QUALIFIED")
    if supported:
        variant = "GUARANTOR_SUPPORTED"
        g_rating = RATING_POINTS[guarantor["credit_rating"]]
        g_leverage = leverage_points(guarantor["net_debt_to_ebitda"])
        eff_rating = max(own_rating, g_rating - GUARANTOR_RATING_NOTCH_PENALTY)
        eff_leverage = max(own_leverage, g_leverage)
    else:
        variant = "STANDALONE"
        eff_rating = own_rating
        eff_leverage = own_leverage

    raw = (RATING_WEIGHT * eff_rating
           + LEVERAGE_WEIGHT * eff_leverage
           + DISCLOSURE_WEIGHT * disclosure)
    score = q(raw, 2)
    return score, variant, credit_tier_for_score(score)


def offtaker_sustainability_score(offtaker):
    total = D0
    if offtaker.get("has_science_based_target"):
        total += SBT_POINTS
    if offtaker.get("re100_member"):
        total += RE100_POINTS
    target_year = offtaker.get("scope2_target_year")
    if target_year is not None and int(target_year) <= SCOPE2_TARGET_YEAR_CUTOFF:
        total += SCOPE2_POINTS
    if offtaker.get("disclosure_framework") != "NONE":
        total += DISCLOSURE_ANY_POINTS
    return q(total, 2)


def unsecured_credit_limit(tier, reported_ebitda_usd):
    cap = TIER_CAP_USD[tier]
    pct_based = q(Decimal(reported_ebitda_usd) * TIER_EBITDA_PCT[tier], 2)
    return q(min(cap, pct_based), 2)


# --------------------------------------------------------------- deal pricing
def deal_contract_price(base_price, escalation_pct, first_delivery_year,
                        shape_product, basis_responsibility):
    """Returns (contract_price, price_tier, escalated_base)."""
    years = int(first_delivery_year) - PRICING_BASE_YEAR
    factor = (Decimal("1") + Decimal(escalation_pct) / Decimal("100")) ** years
    escalated_base = q(Decimal(base_price) * factor, 4)
    if escalated_base < PRICE_TIER_LOW_MAX:
        tier = "LOW"
    elif escalated_base < PRICE_TIER_MID_MAX:
        tier = "MID"
    else:
        tier = "HIGH"
    premium = SHAPE_PREMIUM[shape_product][tier]
    adder = BASIS_ADDER[basis_responsibility]
    price = q(escalated_base + premium + adder, 2)
    return price, tier, escalated_base


def deal_expected_volume(contracted_mw, technology):
    return q(Decimal(contracted_mw) * CAPACITY_FACTOR[technology]
             * HOURS_PER_YEAR, 2)


def credit_support_requirement(expected_annual_mwh, contract_price, threshold):
    """Returns (exposure_usd, credit_support_required_usd)."""
    exposure = q(Decimal(expected_annual_mwh) * Decimal(contract_price), 2)
    threshold = Decimal(threshold or 0)
    if exposure <= threshold:
        return exposure, q(D0, 2)
    increments = dceil((exposure - threshold) / COLLATERAL_INCREMENT_USD)
    return exposure, q(Decimal(increments) * COLLATERAL_INCREMENT_USD, 2)


def eligible_credit_support(instrument, guarantor):
    """Returns (haircut_pct, eligible_credit_usd) or None when ineligible."""
    kind = instrument["instrument_type"]
    if kind == "CASH_COLLATERAL":
        haircut = CASH_HAIRCUT_PCT
    elif kind == "LETTER_OF_CREDIT":
        rating = instrument.get("issuer_rating")
        if rating is None or rating not in LC_HAIRCUT_PCT:
            return None
        haircut = LC_HAIRCUT_PCT[rating]
    else:  # PARENT_GUARANTEE
        if guarantor is None:
            return None
        tier = guarantor.get("credit_tier")
        if tier is None or tier not in PG_HAIRCUT_PCT:
            return None
        haircut = PG_HAIRCUT_PCT[tier]
    face = Decimal(instrument["face_amount_usd"])
    eligible = q(face * (Decimal("1") - haircut / Decimal("100")), 2)
    return q(haircut, 2), eligible


# --------------------------------------------------------- deemed generation
def deemed_generation(interval, contracted_mw, technology, covering_event):
    expected = q(Decimal(contracted_mw) * CAPACITY_FACTOR[technology], 4)
    excused = (interval.get("curtailment_flag") != "NONE"
               and covering_event is not None)
    if excused:
        share = DEEMED_SHARE[covering_event.get("allocation_outcome")]
    else:
        share = D0
    shortfall = expected - Decimal(interval["metered_mwh"])
    if shortfall < 0:
        shortfall = D0
    deemed = q(shortfall * share, 4)
    delivered = q(Decimal(interval["metered_mwh"]) + deemed, 4)
    return expected, deemed, delivered


# ----------------------------------------------------------- settlement math
def settlement_netting(intervals, netting_method, contract_price,
                       basis_responsibility, settlement_point_type):
    total_metered = q(sum((Decimal(i["metered_mwh"]) for i in intervals), D0), 4)
    total_deemed = q(sum((Decimal(i["deemed_mwh"]) for i in intervals), D0), 4)
    total_delivered = q(sum((Decimal(i["delivered_mwh"]) for i in intervals), D0), 4)

    result = {
        "total_metered_mwh": total_metered,
        "total_deemed_mwh": total_deemed,
        "total_delivered_mwh": total_delivered,
    }

    if total_delivered == 0:
        result["weighted_avg_index_usd_per_mwh"] = q(D0, 4)
        result["energy_settlement_usd"] = q(D0, 2)
        result["basis_adjustment_usd"] = q(D0, 2)
        result["net_settlement_usd"] = q(D0, 2)
        result["seller_pays_usd"] = q(D0, 2)
        result["buyer_pays_usd"] = q(D0, 2)
        return result

    def index_of(interval):
        if settlement_point_type == "HUB":
            return Decimal(interval["hub_price_usd_per_mwh"])
        return Decimal(interval["node_price_usd_per_mwh"])

    weighted = sum((Decimal(i["delivered_mwh"]) * index_of(i)
                    for i in intervals), D0)
    weighted_avg = q(weighted / total_delivered, 4)
    result["weighted_avg_index_usd_per_mwh"] = weighted_avg

    contract_price = Decimal(contract_price)
    if netting_method == "HOURLY":
        total = D0
        for i in intervals:
            effective = max(index_of(i), NEGATIVE_PRICE_FLOOR)
            total += q(Decimal(i["delivered_mwh"]) * (effective - contract_price), 2)
        energy = q(total, 2)
    else:
        energy = q(total_delivered * (weighted_avg - contract_price), 2)
    result["energy_settlement_usd"] = energy

    if settlement_point_type == "NODE":
        basis = q(D0, 2)
    else:
        differential = sum(
            (Decimal(i["delivered_mwh"])
             * (Decimal(i["node_price_usd_per_mwh"])
                - Decimal(i["hub_price_usd_per_mwh"])) for i in intervals), D0)
        basis = q(differential * BASIS_SHARE_TO_BUYER[basis_responsibility], 2)
    result["basis_adjustment_usd"] = basis

    net = q(energy + basis, 2)
    result["net_settlement_usd"] = net
    if net >= 0:
        result["seller_pays_usd"] = q(net, 2)
        result["buyer_pays_usd"] = q(D0, 2)
    else:
        result["seller_pays_usd"] = q(D0, 2)
        result["buyer_pays_usd"] = q(-net, 2)
    return result


def mintable_attributes(total_metered_mwh):
    return dfloor(total_metered_mwh)


# ------------------------------------------------------- attribute allocation
def attribute_allocation(quantity_mwh, confirmed_allocations):
    """Largest-remainder split; returns the breakdown in tie-break order."""
    if not confirmed_allocations:
        return []
    basis = sum((Decimal(a["allocated_mw"]) for a in confirmed_allocations), D0)
    if basis == 0:
        return []
    rows = []
    for alloc in confirmed_allocations:
        exact = Decimal(quantity_mwh) * Decimal(alloc["allocated_mw"]) / basis
        floor_part = dfloor(exact)
        rows.append({
            "offtaker_id": alloc["offtaker_id"],
            "quantity_mwh": floor_part,
            "_remainder": exact - Decimal(floor_part),
            "_allocated_mw": Decimal(alloc["allocated_mw"]),
            "_created_at": alloc["created_at"],
            "_seq": alloc.get("_seq", 0),
        })
    leftover = int(quantity_mwh) - sum(r["quantity_mwh"] for r in rows)
    rows.sort(key=lambda r: (-r["_remainder"], -r["_allocated_mw"],
                             r["_created_at"], r["_seq"]))
    for i in range(max(0, leftover)):
        rows[i % len(rows)]["quantity_mwh"] += 1
    return [{"offtaker_id": r["offtaker_id"],
             "quantity_mwh": r["quantity_mwh"]} for r in rows]


def cp_completion_pct(conditions):
    total = len(conditions)
    if total == 0:
        return q(Decimal("100"), 2)
    cleared = len([c for c in conditions
                   if c["status"] in ("SATISFIED", "WAIVED")])
    return q(Decimal(100) * Decimal(cleared) / Decimal(total), 2)


def cp_template_selection(project_status, registry_account_id, cod_deadline,
                          clock):
    """Returns the ordered list of (cp_type, deadline_date, is_waivable)."""
    out = []
    if project_status == "PRE_DEVELOPMENT":
        out.append(("PERMITTING",
                    min(cod_deadline, add_days(clock, CP_PERMITTING_DAYS)),
                    False))
    if project_status in ("PRE_DEVELOPMENT", "PERMITTED"):
        out.append(("INTERCONNECTION",
                    min(cod_deadline, add_days(clock, CP_INTERCONNECTION_DAYS)),
                    False))
    if project_status != "OPERATIONAL":
        out.append(("NOTICE_TO_PROCEED",
                    min(cod_deadline, add_days(clock, CP_NTP_DAYS)),
                    True))
    if registry_account_id is None:
        out.append(("REGISTRY_ACCOUNT", add_days(clock, CP_REGISTRY_DAYS), True))
    return out


def risk_event_duration_days(window_start, window_end):
    return floor_days_between(window_start, window_end) + 1


def allocation_share_pct(allocated_mw, contracted_mw):
    return q(Decimal(100) * Decimal(allocated_mw) / Decimal(contracted_mw), 4)
