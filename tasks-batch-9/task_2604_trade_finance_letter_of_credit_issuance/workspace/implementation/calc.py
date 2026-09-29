"""The thirteen declared calculations (SCAFFOLD 1.3 / PRD 4).

Every money figure is an integer number of minor units. Two rounding modes are
used and never mixed up:

* ``fdiv`` -- floor division, used by credit_allocation_exposure and by the
  facility threshold, so the bank never under-reserves.
* ``rhu``  -- round-half-up, used by every charge component. Applied once per
  component (and once per document in settlement_proceeds), never to a running
  total.
"""

from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import add_days, end_of_day_iso

# ---- credit_allocation_exposure -----------------------------------------
TENOR_RISK_BPS_PER_MONTH = 25
COLLATERAL_ADVANCE_RATE_PCT = 90

# ---- issuance_charges ----------------------------------------------------
COMMISSION_TIER_1_CAP_CENTS = 5000000
COMMISSION_TIER_2_CAP_CENTS = 50000000
COMMISSION_TIER_1_BPS = 15
COMMISSION_TIER_2_BPS = 10
COMMISSION_TIER_3_BPS = 7
MIN_COMMISSION_CENTS = 25000
CONFIRM_BASE_BPS = 20
CONFIRM_RISK_BPS_PER_POINT = 1
DAYS_PER_QUARTER = 90
AMENDMENT_FEE_CENTS = 7500

# ---- settlement_proceeds -------------------------------------------------
SIGHT_COMMISSION_BPS = 12
NEGOTIATION_COMMISSION_BPS = 20
DISCOUNT_RATE_BPS = 450
DISCOUNT_DAY_BASIS = 360
DOC_FEE_BPS = 5
DOC_FLAT_FEE_CENTS = 3500

# ---- facility_exposure_ledger -------------------------------------------
FACILITY_RESTRICT_PCT = 95

# ---- examination_period_deadline ----------------------------------------
EXAMINATION_BANKING_DAYS = 5
WAIVER_RESPONSE_DAYS = 2

# ---- confirming line / selection ----------------------------------------
MAX_CONFIRM_COUNTRY_RISK = 60
COUNTRY_WEIGHT = 6
RATING_WEIGHT = 4
RATING_POINTS = {"AA": 100, "A": 75, "BBB": 50, "BB": 25}

# ---- amendment windows ---------------------------------------------------
AMENDMENT_CONSENT_DAYS = 10
AMENDMENT_COOLING_OFF_DAYS = 2

# ---- sanctions_dual_use_score -------------------------------------------
SANCTIONED_COUNTRY_CODES = ("IR", "KP", "SY", "CU")
HIGH_RISK_TRANSIT_CODES = ("AE", "HK", "TR")
DUAL_USE_HS_PREFIXES = ("8471", "8542", "9013", "2811")
CONTROLLED_KEYWORDS = ("centrifuge", "maraging", "gyroscope")
COUNTRY_HIT_WEIGHT = 100
DUAL_USE_HIT_WEIGHT = 60
KEYWORD_HIT_WEIGHT = 40
TRANSIT_HIT_WEIGHT = 20
SANCTIONS_REVIEW_SCORE = 40
SANCTIONS_BLOCK_SCORE = 100
SCORE_CAP = 200

AMENDABLE_KEYS = (
    "amount_cents",
    "tolerance_pct",
    "expiry_date",
    "latest_shipment_date",
    "incoterm",
    "incoterm_place",
    "presentation_period_days",
    "partial_shipment_allowed",
    "transhipment_allowed",
)


# --------------------------------------------------------------------------
# arithmetic primitives
# --------------------------------------------------------------------------

def fdiv(numerator, denominator):
    """Floor division over integers (never float)."""
    return int(numerator) // int(denominator)


def rhu(numerator, denominator):
    """Round half up, exactly, using Decimal (never binary float)."""
    quotient = Decimal(int(numerator)) / Decimal(int(denominator))
    return int(quotient.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def ceil_div(numerator, denominator):
    numerator = int(numerator)
    denominator = int(denominator)
    if numerator <= 0:
        return 0
    return -((-numerator) // denominator)


def parse_date(text):
    """Strict YYYY-MM-DD; returns None when the shape is wrong."""
    if not isinstance(text, str):
        return None
    raw = text.strip()
    if len(raw) != 10 or raw[4] != "-" or raw[7] != "-":
        return None
    try:
        return date(int(raw[0:4]), int(raw[5:7]), int(raw[8:10]))
    except ValueError:
        return None


def days_between(later, earlier):
    return (later - earlier).days


# --------------------------------------------------------------------------
# 1. credit_allocation_exposure
# --------------------------------------------------------------------------

def credit_allocation_exposure(credit, facility, variant, overrides=None):
    """Returns a dict of the five step outputs.

    variant == 'provisional_draft'    -> tolerance and tenor are forced to 0
    variant == 'committed_issuance'   -> declared tolerance and tenor apply

    ``overrides`` lets the amendment path evaluate the credit AFTER a change_set
    without mutating the credit row.
    """
    def field(name):
        if overrides is not None and name in overrides:
            return overrides[name]
        return credit.get(name)

    amount_cents = int(field("amount_cents") or 0)
    if variant == "provisional_draft":
        tolerance_eff_pct = 0
        tenor_eff_days = 0
    else:
        tolerance_eff_pct = int(field("tolerance_pct") or 0)
        tenor_eff_days = int(field("tenor_days") or 0)

    # step 1 -- drawable ceiling
    max_drawable_cents = fdiv(amount_cents * (100 + tolerance_eff_pct), 100)

    # step 2 -- usance risk add-on (whole months, rounded UP)
    if field("available_by") == "SIGHT_PAYMENT":
        tenor_months = 0
    else:
        tenor_months = ceil_div(tenor_eff_days, 30)
    tenor_addon_cents = fdiv(max_drawable_cents * TENOR_RISK_BPS_PER_MONTH * tenor_months, 10000)

    # step 3 -- gross exposure
    gross_exposure_cents = max_drawable_cents + tenor_addon_cents

    # step 4 -- eligible collateral credit
    posted = int((facility or {}).get("collateral_posted_cents") or 0)
    required_pct = int((facility or {}).get("collateral_required_pct") or 0)
    collateral_cap_posted_cents = fdiv(posted * COLLATERAL_ADVANCE_RATE_PCT, 100)
    collateral_cap_policy_cents = fdiv(gross_exposure_cents * required_pct, 100)
    collateral_credit_cents = min(collateral_cap_posted_cents, collateral_cap_policy_cents)

    # step 5 -- net allocation
    committed_allocation_cents = gross_exposure_cents - collateral_credit_cents

    return {
        "max_drawable_cents": max_drawable_cents,
        "tenor_addon_cents": tenor_addon_cents,
        "gross_exposure_cents": gross_exposure_cents,
        "collateral_credit_cents": collateral_credit_cents,
        "committed_allocation_cents": committed_allocation_cents,
    }


def nominal_max_drawable(credit, overrides=None):
    """max_drawable_cents on the credit itself always carries the DECLARED
    tolerance (entity note: floor(amount_cents * (100 + tolerance_pct) / 100)),
    unlike the provisional exposure estimate which forces tolerance to 0."""
    def field(name):
        if overrides is not None and name in overrides:
            return overrides[name]
        return credit.get(name)

    return fdiv(int(field("amount_cents") or 0) * (100 + int(field("tolerance_pct") or 0)), 100)


# --------------------------------------------------------------------------
# 2. issuance_charges
# --------------------------------------------------------------------------

def commission_tier_bps(gross_exposure_cents):
    """Tier selected from gross_exposure_cents ALONE (pinned order step 2)."""
    if gross_exposure_cents <= COMMISSION_TIER_1_CAP_CENTS:
        return COMMISSION_TIER_1_BPS
    if gross_exposure_cents <= COMMISSION_TIER_2_CAP_CENTS:
        return COMMISSION_TIER_2_BPS
    return COMMISSION_TIER_3_BPS


def validity_quarters(issue_date_str, expiry_date_str):
    issue_d = parse_date(issue_date_str)
    expiry_d = parse_date(expiry_date_str)
    if issue_d is None or expiry_d is None:
        return 1
    validity_days = days_between(expiry_d, issue_d) + 1
    quarters = ceil_div(validity_days, DAYS_PER_QUARTER)
    return max(1, quarters)


def issuance_charges(credit, confirming_bank=None):
    """Steps 1-5 in the pinned evaluation order. Never let a total feed a tier."""
    gross_exposure_cents = int(credit.get("gross_exposure_cents") or 0)
    quarters = validity_quarters(credit.get("issue_date"), credit.get("expiry_date"))

    commission_bps_applied = commission_tier_bps(gross_exposure_cents)
    base_commission_cents = max(
        MIN_COMMISSION_CENTS,
        rhu(gross_exposure_cents * commission_bps_applied * quarters, 10000),
    )

    if credit.get("confirming_bank_id") is None or credit.get("confirmation_status") != "CONFIRMED":
        confirmation_charge_cents = 0
    else:
        risk = int((confirming_bank or {}).get("country_risk_score") or 0)
        confirm_bps = CONFIRM_BASE_BPS + risk * CONFIRM_RISK_BPS_PER_POINT
        confirmation_charge_cents = rhu(gross_exposure_cents * confirm_bps * quarters, 10000)

    total_charge_cents = base_commission_cents + confirmation_charge_cents
    chargeable_utilisation_cents = int(credit.get("committed_allocation_cents") or 0) + total_charge_cents

    return {
        "quarters": quarters,
        "commission_bps_applied": commission_bps_applied,
        "base_commission_cents": base_commission_cents,
        "confirmation_charge_cents": confirmation_charge_cents,
        "total_charge_cents": total_charge_cents,
        "chargeable_utilisation_cents": chargeable_utilisation_cents,
    }


def amendment_recharge_fee(exposure_delta_cents, new_gross_exposure_cents, expiry_date_str, clock_date_value):
    """Variant amendment_recharge: flat fee plus a delta commission on increases.

    ``recharge_bps`` is local -- it is never written back to the credit's
    commission_bps_applied, which keeps its issuance-time tier for life.
    """
    if exposure_delta_cents <= 0:
        return AMENDMENT_FEE_CENTS
    expiry_d = parse_date(expiry_date_str)
    if expiry_d is None:
        quarters_remaining = 1
    else:
        quarters_remaining = max(1, ceil_div(days_between(expiry_d, clock_date_value) + 1, DAYS_PER_QUARTER))
    recharge_bps = commission_tier_bps(new_gross_exposure_cents)
    return AMENDMENT_FEE_CENTS + rhu(exposure_delta_cents * recharge_bps * quarters_remaining, 10000)


# --------------------------------------------------------------------------
# 3. settlement_proceeds
# --------------------------------------------------------------------------

def settlement_variant(claim_type):
    if claim_type in ("PAYMENT", "REIMBURSEMENT"):
        return "SIGHT_HONOUR"
    if claim_type == "NEGOTIATION":
        return "NEGOTIATION_UNDER_DISCOUNT"
    return "ACCEPTANCE_AT_MATURITY"


def settlement_proceeds(presentation, documents, variant, clock_date_value):
    """documents must already be ordered by created_at ASC (pinned rounding)."""
    drawn_amount_cents = int(presentation.get("drawn_amount_cents") or 0)

    # step 1 -- commission, a single round on the whole drawn amount
    if variant == "SIGHT_HONOUR":
        commission_bps_applied = SIGHT_COMMISSION_BPS
    else:
        commission_bps_applied = NEGOTIATION_COMMISSION_BPS
    commission_cents = rhu(drawn_amount_cents * commission_bps_applied, 10000)

    # step 2 -- round EACH document's fee first, then sum
    doc_examination_fee_cents = 0
    for doc in documents:
        if doc.get("doc_type") == "COMMERCIAL_INVOICE":
            doc_examination_fee_cents += rhu(int(doc.get("invoice_amount_cents") or 0) * DOC_FEE_BPS, 10000)
        else:
            doc_examination_fee_cents += DOC_FLAT_FEE_CENTS

    # step 3 -- discount charge (usance only)
    if variant == "SIGHT_HONOUR":
        days_to_maturity = 0
        discount_cents = 0
    else:
        maturity_d = parse_date(presentation.get("maturity_date"))
        if maturity_d is None:
            days_to_maturity = 0
        else:
            days_to_maturity = days_between(maturity_d, clock_date_value)
        discount_cents = rhu(
            drawn_amount_cents * DISCOUNT_RATE_BPS * days_to_maturity,
            10000 * DISCOUNT_DAY_BASIS,
        )

    # step 4 -- waterfall
    net_proceeds_cents = drawn_amount_cents - commission_cents - discount_cents - doc_examination_fee_cents

    return {
        "commission_bps_applied": commission_bps_applied,
        "commission_cents": commission_cents,
        "doc_examination_fee_cents": doc_examination_fee_cents,
        "days_to_maturity": days_to_maturity,
        "discount_cents": discount_cents,
        "net_proceeds_cents": net_proceeds_cents,
    }


# --------------------------------------------------------------------------
# 7. examination_period_deadline / waiver deadline
# --------------------------------------------------------------------------

def examination_period_deadline(received_date_str):
    """EXAMINATION_BANKING_DAYS banking days FOLLOWING the day of presentation.

    Mon..Fri are banking days; there is no holiday calendar. The day of
    presentation itself is never counted.
    """
    d = parse_date(received_date_str)
    if d is None:
        return None
    counted = 0
    while counted < EXAMINATION_BANKING_DAYS:
        d = d + timedelta(days=1)
        if d.weekday() < 5:
            counted += 1
    return end_of_day_iso(d)


def waiver_deadline(requested_date_value, examination_deadline_iso):
    """requested date + WAIVER_RESPONSE_DAYS at end of day, bounded above by the
    examination deadline (whichever is earlier)."""
    candidate = end_of_day_iso(add_days(requested_date_value, WAIVER_RESPONSE_DAYS))
    if examination_deadline_iso and examination_deadline_iso < candidate:
        return examination_deadline_iso
    return candidate


# --------------------------------------------------------------------------
# 8. presentation_window
# --------------------------------------------------------------------------

def presentation_window(credit, overrides=None):
    def field(name):
        if overrides is not None and name in overrides:
            return overrides[name]
        return credit.get(name)

    expiry_d = parse_date(field("expiry_date"))
    shipment_d = parse_date(field("latest_shipment_date"))
    period_days = int(field("presentation_period_days") or 0)

    result = {
        "presentation_deadline_date": None,
        "confirmation_window_start": None,
        "confirmation_window_end": None,
    }
    if expiry_d is None:
        return result
    if shipment_d is not None:
        shipment_cutoff = add_days(shipment_d, period_days)
        result["presentation_deadline_date"] = min(expiry_d, shipment_cutoff).isoformat()
    else:
        result["presentation_deadline_date"] = expiry_d.isoformat()

    issue_d = parse_date(field("issue_date"))
    if issue_d is not None:
        result["confirmation_window_start"] = issue_d.isoformat()
    result["confirmation_window_end"] = add_days(expiry_d, period_days).isoformat()
    return result


# --------------------------------------------------------------------------
# 9. confirming_line_peak_occupancy
# --------------------------------------------------------------------------

OCCUPYING_CONFIRMATION_STATUSES = ("CONFIRMATION_REQUESTED", "CONFIRMED")
OCCUPYING_CREDIT_STATUSES = ("ISSUED", "AMENDMENT_PENDING", "UTILISED")


def _occupations(credits, bank_id, exclude_credit_id=None):
    rows = []
    for credit in credits:
        if credit.get("confirming_bank_id") != bank_id:
            continue
        if exclude_credit_id is not None and credit["id"] == exclude_credit_id:
            continue
        if credit.get("confirmation_status") not in OCCUPYING_CONFIRMATION_STATUSES:
            continue
        if credit.get("status") not in OCCUPYING_CREDIT_STATUSES:
            continue
        rows.append(credit)
    return rows


def _peak_from_intervals(intervals):
    """intervals: list of (start_date, end_date_exclusive, weight)."""
    events = []
    for start, end, weight in intervals:
        if start is None or end is None:
            continue
        events.append((start, weight))
        events.append((end, -weight))
    # -x sorts before +x on the SAME date: an occupation ending on D frees the
    # line before one starting on D takes it (half-open semantics).
    events.sort(key=lambda e: (e[0], e[1]))
    running = 0
    peak = 0
    for _, delta in events:
        running += delta
        if running > peak:
            peak = running
    return peak


def confirming_line_peak_occupancy(credits, bank_id, candidate=None):
    """Peak concurrent occupancy of a bank's confirming line.

    ``candidate`` is the credit being admitted (its own occupation is included
    exactly once even when it is already in the occupying set).
    """
    exclude = candidate["id"] if candidate is not None else None
    intervals = []
    for credit in _occupations(credits, bank_id, exclude_credit_id=exclude):
        intervals.append((
            parse_date(credit.get("confirmation_window_start")),
            parse_date(credit.get("confirmation_window_end")),
            int(credit.get("gross_exposure_cents") or 0),
        ))
    if candidate is not None:
        intervals.append((
            parse_date(candidate.get("confirmation_window_start")),
            parse_date(candidate.get("confirmation_window_end")),
            int(candidate.get("gross_exposure_cents") or 0),
        ))
    return _peak_from_intervals(intervals)


# --------------------------------------------------------------------------
# 10. amendment_window_overlap
# --------------------------------------------------------------------------

LIVE_AMENDMENT_STATUSES = ("ISSUED", "PENDING_CONSENT")


def amendment_window_conflict(siblings, amendment_id, new_start):
    """Closed intervals plus a symmetric cooling-off buffer, pairwise.

    ``siblings`` must be the other amendments of the same credit in created_at
    ASC order. Returns True as soon as one neighbour collides.
    """
    new_end = add_days(new_start, AMENDMENT_CONSENT_DAYS)
    for other in siblings:
        if other["id"] == amendment_id:
            continue
        if other.get("status") == "SUPERSEDED":
            continue
        other_start = parse_date(other.get("consent_window_start"))
        if other_start is None:
            continue
        other_end = parse_date(other.get("window_end_effective"))
        if other_end is None:
            other_end = other_start
        if (new_start <= add_days(other_end, AMENDMENT_COOLING_OFF_DAYS)
                and new_end >= add_days(other_start, -AMENDMENT_COOLING_OFF_DAYS)):
            return True
    return False


# --------------------------------------------------------------------------
# 11. confirming_bank_selection
# --------------------------------------------------------------------------

def eligibility_score(bank):
    rating_points = RATING_POINTS.get(bank.get("credit_rating"), 0)
    return (100 - int(bank.get("country_risk_score") or 0)) * COUNTRY_WEIGHT + rating_points * RATING_WEIGHT


def bank_confirmation_eligible(bank, beneficiary_country_code):
    """The explicit eligibility predicate over Bank fields (filter (a)),
    excluding the line-capacity clause which needs the whole credit book."""
    if bank.get("status") != "ACTIVE":
        return False
    if bank.get("sanctions_flag"):
        return False
    if int(bank.get("country_risk_score") or 0) > MAX_CONFIRM_COUNTRY_RISK:
        return False
    if beneficiary_country_code is not None and bank.get("country_code") == beneficiary_country_code:
        return False
    return True


def select_confirming_bank(banks, credits, credit, beneficiary_country_code, declined_bank_ids):
    """Returns the winning bank row, or None when the candidate set is empty."""
    candidates = []
    for bank in banks:
        if not bank_confirmation_eligible(bank, beneficiary_country_code):
            continue
        if bank["id"] in declined_bank_ids:
            continue
        peak = confirming_line_peak_occupancy(credits, bank["id"], candidate=credit)
        if peak > int(bank.get("confirmation_appetite_cents") or 0):
            continue
        candidates.append(bank)
    if not candidates:
        return None
    candidates.sort(key=lambda b: (
        -eligibility_score(b),
        int(b.get("country_risk_score") or 0),
        b["_seq"],
    ))
    return candidates[0]


# --------------------------------------------------------------------------
# 12. sanctions_dual_use_score
# --------------------------------------------------------------------------

def _transit_codes(doc):
    codes = doc.get("transit_country_codes")
    if not isinstance(codes, list):
        return []
    return [c for c in codes if isinstance(c, str)]


def sanctions_dual_use_score(scope, documents=None, parties=None):
    country_hits = 0
    dual_use_hits = 0
    keyword_hits = 0
    transit_hits = 0

    if scope == "PRESENTED_DOCUMENTS":
        for doc in (documents or []):
            transit = _transit_codes(doc)
            # a document with several sanctioned matches counts ONCE
            if doc.get("consignee_country") in SANCTIONED_COUNTRY_CODES or any(
                    code in SANCTIONED_COUNTRY_CODES for code in transit):
                country_hits += 1
            hs_code = doc.get("hs_code") or ""
            if isinstance(hs_code, str) and hs_code[:4] in DUAL_USE_HS_PREFIXES:
                dual_use_hits += 1
            description = (doc.get("goods_description") or "")
            if isinstance(description, str):
                lowered = description.lower()
                if any(keyword in lowered for keyword in CONTROLLED_KEYWORDS):
                    keyword_hits += 1
            # transit_hits counts (document, transit code) PAIRS
            for code in transit:
                if code in HIGH_RISK_TRANSIT_CODES and code not in SANCTIONED_COUNTRY_CODES:
                    transit_hits += 1
    else:  # CREDIT_PARTIES
        for party in (parties or []):
            if party is None:
                continue
            if party.get("country_code") in SANCTIONED_COUNTRY_CODES:
                country_hits += 1
            if party.get("sanctions_flag"):
                country_hits += 1

    risk_score = min(
        SCORE_CAP,
        COUNTRY_HIT_WEIGHT * country_hits
        + DUAL_USE_HIT_WEIGHT * dual_use_hits
        + KEYWORD_HIT_WEIGHT * keyword_hits
        + TRANSIT_HIT_WEIGHT * transit_hits,
    )

    if risk_score >= SANCTIONS_BLOCK_SCORE:
        result = "BLOCKED"
    elif risk_score >= SANCTIONS_REVIEW_SCORE:
        result = "HIT_PENDING_REVIEW"
    else:
        result = "CLEAR"

    return {
        "country_hits": country_hits,
        "dual_use_hits": dual_use_hits,
        "keyword_hits": keyword_hits,
        "transit_hits": transit_hits,
        "risk_score": risk_score,
        "result": result,
    }


# --------------------------------------------------------------------------
# 13. amendment_consent_requirement
# --------------------------------------------------------------------------

_REDUCING_NUMERIC_KEYS = ("amount_cents", "tolerance_pct", "presentation_period_days")
_REDUCING_DATE_KEYS = ("expiry_date", "latest_shipment_date")
_DIFFERING_KEYS = ("incoterm", "incoterm_place")
_WITHDRAWN_FLAG_KEYS = ("partial_shipment_allowed", "transhipment_allowed")


def effective_change_set(change_set, credit):
    """Keys whose new value equals the current value are ignored entirely."""
    effective = {}
    for key, value in change_set.items():
        if credit.get(key) != value:
            effective[key] = value
    return effective


def requires_beneficiary_consent(change_set, credit):
    for key in _REDUCING_NUMERIC_KEYS:
        if key in change_set and int(change_set[key]) < int(credit.get(key) or 0):
            return True
    for key in _REDUCING_DATE_KEYS:
        if key in change_set:
            new_d = parse_date(change_set[key])
            cur_d = parse_date(credit.get(key))
            if new_d is not None and cur_d is not None and new_d < cur_d:
                return True
    for key in _DIFFERING_KEYS:
        if key in change_set and change_set[key] != credit.get(key):
            return True
    for key in _WITHDRAWN_FLAG_KEYS:
        if key in change_set and change_set[key] is False and credit.get(key) is True:
            return True
    return False
