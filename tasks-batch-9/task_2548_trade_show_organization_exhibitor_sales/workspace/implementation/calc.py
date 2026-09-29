"""Deterministic calculations (PRD 2.6, 2.8, 2.9, section 3).

Every money and percentage figure is computed with decimal.Decimal and
rounded half up. Python's float and built-in round() are never used.
"""
from decimal import Decimal, ROUND_HALF_UP

from db import add_days, db

ZERO = Decimal(0)
HUNDRED = Decimal(100)

# ---------------------------------------------------------------- constants
LOCATION_MULTIPLIER = {
    "INLINE": Decimal("1.00"),
    "CORNER": Decimal("1.10"),
    "PENINSULA": Decimal("1.20"),
    "ISLAND": Decimal("1.30"),
}
ZONE_MULTIPLIER = {
    "NONE": Decimal("1.00"),
    "MAIN_AISLE": Decimal("1.08"),
    "ENTRANCE": Decimal("1.15"),
    "FOOD_COURT": Decimal("1.05"),
}
LOCATION_RANK = {"INLINE": 1, "CORNER": 2, "PENINSULA": 3, "ISLAND": 4}
ZONE_RANK = {"ENTRANCE": 1, "MAIN_AISLE": 2, "FOOD_COURT": 3, "NONE": 4}

LOCATION_CLASSES = ("INLINE", "CORNER", "PENINSULA", "ISLAND")
PREMIUM_ZONES = ("NONE", "MAIN_AISLE", "ENTRANCE", "FOOD_COURT")

DEPOSIT_PCT = Decimal(25)
DARK_DAY_BUFFER_DAYS = 2
ADVANCE_ORDER_LEAD_DAYS = 21
OBLIGATION_LEAD_DAYS = 14
MAX_NEGOTIATION_ROUNDS = 3
DISCOUNT_APPROVAL_THRESHOLD_PCT = 10
MAX_APPROVED_DISCOUNT_PCT = 40
MAX_SPONSOR_DISCOUNT_PCT = Decimal(20)
SQFT_PER_POINT_BLOCK = 100
POINTS_PER_BLOCK = 2
REBOOK_BONUS_POINTS = 5
SPONSOR_SPEND_PER_POINT = 500000
CERTIFIED_DECAY_AFTER_YEARS = 3
CERTIFIED_DECAY_FACTOR = Decimal("0.5")
ATTRITION_RATE_CENTS_PER_SQFT = 1800
FLOOR_EXPEDITE_FEE_CENTS = 7500
FLOOR_RATE_MULTIPLIER = Decimal("1.35")
MATERIAL_HANDLING_MIN_CWT = 2
SPACE_LOCK_RATIO_PCT = 85
FREEZE_RATIO_PCT = 100
FREEZE_UPHELD_VIOLATIONS = 3
FORFEIT_PENALTY_POINTS = 3
BREACH_PENALTY_POINTS = 20
SUSPENSION_PENALTY_THRESHOLD = 30
PENALTY_POINTS = {
    "BOOTH_HEIGHT": 10,
    "NOISE": 5,
    "AISLE_ENCROACHMENT": 8,
    "SALES_CONDUCT": 15,
}
AUTHORITY_POINTS = {
    "NONE": 0,
    "INFLUENCER": 15,
    "RECOMMENDER": 25,
    "DECISION_MAKER": 40,
}
SPEND_BAND_POINTS = {
    "UNDER_50K": 5,
    "K50_250K": 15,
    "K250K_1M": 25,
    "OVER_1M": 35,
}
CATEGORY_WEIGHT = {
    "BUYER": Decimal("1.00"),
    "VIP_BUYER": Decimal("1.15"),
    "STUDENT": Decimal("0.50"),
}
TITLE_KEYWORDS = ("CHIEF", "VP", "VICE PRESIDENT", "DIRECTOR", "HEAD OF",
                  "BUYER", "OWNER", "PARTNER")
QUALIFIED_THRESHOLD = 60
WAITLISTED_THRESHOLD = 40
AUTO_QUALIFIED_CATEGORIES = ("PRESS", "EXHIBITOR_STAFF")
DEFAULT_CANCELLATION_FEE_SCHEDULE = [
    {"min_days_out": 180, "pct": 25},
    {"min_days_out": 90, "pct": 50},
    {"min_days_out": 0, "pct": 100},
]

ACTIVE_CONTRACT_STATUSES = ("OFFERED", "COUNTERED", "SIGNED")
NON_TERMINAL_CONTRACT_STATUSES = ("OFFERED", "COUNTERED", "SIGNED")
PROVISIONAL_SHOW_STATUSES = ("PLANNING", "SPACE_SELECTION", "SELLING", "ON_SITE")


def rhu(value):
    """Round half up to a whole unit and return an int."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def dec(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def plain(value):
    """Render a Decimal as an int when integral, else as a float."""
    if isinstance(value, Decimal):
        if value == value.to_integral_value():
            return int(value)
        return float(value)
    if isinstance(value, float) and value == int(value):
        return int(value)
    return value


def floor_div(numerator, denominator):
    return int(numerator) // int(denominator)


# ------------------------------------------------------------- collections
def show_booths(show_id):
    return [b for b in db.booths.values() if b["show_id"] == show_id]


def show_contracts(show_id):
    return [c for c in db.space_contracts.values() if c["show_id"] == show_id]


def show_appointments(show_id):
    return [a for a in db.selection_appointments.values() if a["show_id"] == show_id]


def show_packages(show_id):
    return [p for p in db.sponsorship_packages.values() if p["show_id"] == show_id]


def show_registrations(show_id):
    return [r for r in db.registrations.values() if r["show_id"] == show_id]


def package_deals(package_id):
    return [d for d in db.sponsorship_deals.values()
            if d["sponsorship_package_id"] == package_id]


def show_deals(show_id):
    package_ids = set(p["id"] for p in show_packages(show_id))
    return [d for d in db.sponsorship_deals.values()
            if d["sponsorship_package_id"] in package_ids]


def deal_obligations(deal_id):
    return [o for o in db.fulfillment_obligations.values()
            if o["sponsorship_deal_id"] == deal_id]


def contract_scans(contract_id):
    return [s for s in db.lead_scans.values() if s["space_contract_id"] == contract_id]


def registration_scans(registration_id):
    return [s for s in db.lead_scans.values() if s["registration_id"] == registration_id]


def contract_service_orders(contract_id):
    return [o for o in db.service_orders.values()
            if o["space_contract_id"] == contract_id]


def contract_violations(contract_id):
    return [v for v in db.rule_violations.values()
            if v["space_contract_id"] == contract_id]


def exhibitor_contracts(exhibitor_id):
    return [c for c in db.space_contracts.values() if c["exhibitor_id"] == exhibitor_id]


def exhibitor_deals(exhibitor_id):
    return [d for d in db.sponsorship_deals.values() if d["exhibitor_id"] == exhibitor_id]


def venue_shows(venue_contract_id):
    return [s for s in db.shows.values() if s["venue_contract_id"] == venue_contract_id]


# ---------------------------------------------------------- show aggregates
def show_venue_contract(show):
    return db.venue_contracts.get(show["venue_contract_id"])


def sellable_area(show):
    """Derivable floor capacity: floor(gross_sqft * (100 - aisle_ratio_pct) / 100)."""
    exact = dec(show["gross_sqft"]) * (HUNDRED - dec(show["aisle_ratio_pct"])) / HUNDRED
    return int(exact.to_integral_value(rounding="ROUND_FLOOR"))


def sellable_booth_sqft(show):
    return sum(b["area_sqft"] for b in show_booths(show["id"]) if b["status"] != "MERGED")


def held_net_sqft(show):
    return sum(b["area_sqft"] for b in show_booths(show["id"]) if b["status"] == "HELD")


def assigned_net_sqft(show):
    return sum(b["area_sqft"] for b in show_booths(show["id"]) if b["status"] == "ASSIGNED")


def upheld_violation_count(show):
    contract_ids = set(c["id"] for c in show_contracts(show["id"]))
    return len([v for v in db.rule_violations.values()
                if v["status"] == "UPHELD" and v["space_contract_id"] in contract_ids])


def committed_ratio_pct(show):
    sellable = sellable_booth_sqft(show)
    if sellable == 0:
        return 0
    occupied = held_net_sqft(show) + assigned_net_sqft(show)
    return rhu(HUNDRED * dec(occupied) / dec(sellable))


def floor_posture(show):
    ratio = committed_ratio_pct(show)
    if ratio >= FREEZE_RATIO_PCT:
        return "FROZEN"
    if show["status"] == "ON_SITE" and upheld_violation_count(show) >= FREEZE_UPHELD_VIOLATIONS:
        return "FROZEN"
    if ratio >= SPACE_LOCK_RATIO_PCT:
        return "SPACE_LOCKED"
    return "OPEN"


def available_net_sqft(show):
    return sellable_booth_sqft(show) - held_net_sqft(show) - assigned_net_sqft(show)


def advance_order_deadline(show):
    from db import parse_date
    move_in = parse_date(show["move_in_start"])
    if move_in is None:
        return None
    return add_days(move_in, -ADVANCE_ORDER_LEAD_DAYS)


# ------------------------------------------------------- contract pricing
def volume_tier_pct(offered_net_sqft):
    if offered_net_sqft >= 4000:
        return Decimal(12)
    if offered_net_sqft >= 2000:
        return Decimal(8)
    if offered_net_sqft >= 1000:
        return Decimal(5)
    return ZERO


def bundle_discount_pct(subtotal_cents):
    if subtotal_cents >= 5000000:
        return Decimal(4)
    if subtotal_cents >= 2000000:
        return Decimal("2.5")
    return ZERO


def contract_booths(contract):
    booths = []
    for booth_id in contract["offered_booth_ids"]:
        booth = db.booths.get(booth_id)
        if booth is not None:
            booths.append(booth)
    return booths


def offered_net_sqft(contract):
    return sum(b["area_sqft"] for b in contract_booths(contract))


def contract_assigned_net_sqft(contract):
    return sum(b["area_sqft"] for b in db.booths.values()
               if b["space_contract_id"] == contract["id"] and b["status"] == "ASSIGNED")


def sponsorship_attached_cents(contract):
    total = 0
    for deal in db.sponsorship_deals.values():
        if deal["deal_status"] != "SIGNED":
            continue
        if deal["exhibitor_id"] != contract["exhibitor_id"]:
            continue
        package = db.sponsorship_packages.get(deal["sponsorship_package_id"])
        if package is None or package["show_id"] != contract["show_id"]:
            continue
        total += deal["negotiated_price_cents"]
    return total


def price_space_fee(contract):
    """PRD 3.5: round each booth line half up, then sum the rounded lines."""
    show = db.shows[contract["show_id"]]
    booths = contract_booths(contract)
    total_sqft = sum(b["area_sqft"] for b in booths)
    tier = volume_tier_pct(total_sqft)
    total_discount = tier + dec(contract["approved_discount_pct"] or 0)
    if total_discount > Decimal(MAX_APPROVED_DISCOUNT_PCT):
        total_discount = Decimal(MAX_APPROVED_DISCOUNT_PCT)
    base_rate = dec(show["base_rate_cents_per_sqft"])
    fee = 0
    for booth in booths:
        gross = (dec(booth["area_sqft"]) * base_rate
                 * LOCATION_MULTIPLIER[booth["location_class"]]
                 * ZONE_MULTIPLIER[booth["premium_zone"]])
        fee += rhu(gross * (HUNDRED - total_discount) / HUNDRED)
    contract["volume_tier_pct"] = plain(tier)
    contract["space_fee_cents"] = fee
    contract["min_deposit_cents"] = rhu(dec(fee) * DEPOSIT_PCT / HUNDRED)
    price_invoice(contract)


def price_invoice(contract):
    """PRD 3.5: the bundle tier is chosen from the pre-discount subtotal."""
    attached = sponsorship_attached_cents(contract)
    subtotal = contract["space_fee_cents"] + attached
    pct = bundle_discount_pct(subtotal)
    discount = rhu(dec(subtotal) * pct / HUNDRED)
    contract["sponsorship_attached_cents"] = attached
    contract["bundle_discount_pct"] = plain(pct)
    contract["bundle_discount_cents"] = discount
    contract["invoice_total_cents"] = subtotal - discount


# ------------------------------------------------------------ booth selector
def select_booth(show_id, requested_sqft, premium_placement_requested):
    """PRD 3.5 booth_selector: returns the single winning booth, or None."""
    candidates = []
    for booth in show_booths(show_id):
        if booth["status"] != "AVAILABLE":
            continue
        if booth["combined_parent_booth_id"] is not None:
            continue
        if booth["area_sqft"] < requested_sqft:
            continue
        if not premium_placement_requested and booth["premium_zone"] == "ENTRANCE":
            continue
        candidates.append(booth)
    if not candidates:
        return None
    if premium_placement_requested:
        candidates.sort(key=lambda b: (ZONE_RANK[b["premium_zone"]], b["area_sqft"],
                                       LOCATION_RANK[b["location_class"]], b["booth_number"]))
    else:
        candidates.sort(key=lambda b: (b["area_sqft"], LOCATION_RANK[b["location_class"]],
                                       b["booth_number"]))
    return candidates[0]


# ------------------------------------------------------------ service orders
def service_unit_rate(venue_contract, service_type):
    if service_type == "LABOR":
        return venue_contract["labor_rate_cents_per_hour"]
    if service_type == "ELECTRICAL":
        return venue_contract["electrical_rate_cents_per_amp"]
    return venue_contract["material_handling_rate_cents_per_cwt"]


def billable_quantity(service_type, quantity):
    if service_type == "MATERIAL_HANDLING":
        return max(quantity, MATERIAL_HANDLING_MIN_CWT)
    return quantity


def service_line_total(venue_contract, service_type, billable, rate_variant):
    rate = dec(service_unit_rate(venue_contract, service_type))
    quantity = dec(billable)
    if rate_variant == "ADVANCE":
        pct = HUNDRED - dec(venue_contract["advance_order_discount_pct"])
        return rhu(quantity * rate * pct / HUNDRED)
    rounded = rhu(quantity * rate * FLOOR_RATE_MULTIPLIER)
    return rounded + FLOOR_EXPEDITE_FEE_CENTS


# ----------------------------------------------------------------- points
def contract_effective_sqft(contract):
    if contract["status"] in ("SIGNED", "CLOSED_OUT"):
        return contract_assigned_net_sqft(contract)
    return offered_net_sqft(contract)


def contract_points(contract):
    blocks = floor_div(contract_effective_sqft(contract), SQFT_PER_POINT_BLOCK)
    points = blocks * POINTS_PER_BLOCK
    if contract["rebooked_from_space_contract_id"]:
        points += REBOOK_BONUS_POINTS
    return points


def deal_points(deal):
    return floor_div(deal["negotiated_price_cents"], SPONSOR_SPEND_PER_POINT)


def space_points_provisional(exhibitor_id):
    total = 0
    for contract in exhibitor_contracts(exhibitor_id):
        if contract["status"] not in ACTIVE_CONTRACT_STATUSES:
            continue
        show = db.shows.get(contract["show_id"])
        if show is None or show["status"] not in PROVISIONAL_SHOW_STATUSES:
            continue
        total += contract_points(contract)
    return total


def spend_points_provisional(exhibitor_id):
    return sum(deal_points(d) for d in exhibitor_deals(exhibitor_id)
               if d["deal_status"] == "SIGNED")


def space_points_certified(exhibitor_id):
    from db import now
    current_year = now().year
    total = 0
    for contract in exhibitor_contracts(exhibitor_id):
        if contract["status"] != "CLOSED_OUT":
            continue
        show = db.shows.get(contract["show_id"])
        if show is None or show["status"] != "CLOSED":
            continue
        points = contract_points(contract)
        edition_age = current_year - show["edition_year"]
        if edition_age > CERTIFIED_DECAY_AFTER_YEARS:
            points = int((dec(points) * CERTIFIED_DECAY_FACTOR).to_integral_value(
                rounding="ROUND_FLOOR"))
        total += points
    return total


def spend_points_certified(exhibitor_id):
    total = 0
    for deal in exhibitor_deals(exhibitor_id):
        if deal["deal_status"] != "SIGNED":
            continue
        package = db.sponsorship_packages.get(deal["sponsorship_package_id"])
        if package is None:
            continue
        show = db.shows.get(package["show_id"])
        if show is None or show["status"] != "CLOSED":
            continue
        total += deal_points(deal)
    return total


def provisional_priority_points(exhibitor):
    total = (exhibitor["ledger_points"]
             + space_points_provisional(exhibitor["id"])
             + spend_points_provisional(exhibitor["id"])
             + exhibitor["sponsorship_fulfillment_points"]
             - exhibitor["penalty_points"])
    return max(0, total)


def certified_priority_points(exhibitor):
    total = (exhibitor["ledger_points"]
             + space_points_certified(exhibitor["id"])
             + spend_points_certified(exhibitor["id"])
             + exhibitor["sponsorship_fulfillment_points"]
             - exhibitor["penalty_points"])
    return max(0, total)


def priority_tier(provisional_points):
    if provisional_points >= 1000:
        return "PLATINUM"
    if provisional_points >= 600:
        return "GOLD"
    if provisional_points >= 300:
        return "SILVER"
    return "BRONZE"


# --------------------------------------------------------- sponsorship state
def inventory_committed(package):
    return len([d for d in package_deals(package["id"])
                if d["deal_status"] in ("PROPOSED", "SIGNED")])


def inventory_available(package):
    return package["inventory_total"] - inventory_committed(package)


def derived_fulfillment_status(deal):
    obligations = deal_obligations(deal["id"])
    if not obligations:
        return "NOT_STARTED"
    if any(o["status"] == "MISSED" for o in obligations):
        return "BREACHED"
    resolved = len([o for o in obligations if o["status"] in ("DELIVERED", "WAIVED")])
    if resolved == len(obligations):
        return "COMPLETE"
    if resolved == 0:
        return "NOT_STARTED"
    return "PARTIAL"


def resolved_obligation_count(deal):
    return len([o for o in deal_obligations(deal["id"])
                if o["status"] in ("DELIVERED", "WAIVED")])


def obligation_count(deal):
    return len(deal_obligations(deal["id"]))


# -------------------------------------------------------------- registration
def title_bonus(job_title):
    upper = (job_title or "").upper()
    for keyword in TITLE_KEYWORDS:
        if keyword in upper:
            return 10
    return 0


def registration_score(category, purchasing_authority, annual_spend_band, job_title):
    """PRD 3.8: weight the summed raw points exactly once."""
    if category in AUTO_QUALIFIED_CATEGORIES:
        return 0, "QUALIFIED"
    raw = (AUTHORITY_POINTS[purchasing_authority]
           + SPEND_BAND_POINTS[annual_spend_band]
           + title_bonus(job_title))
    score = rhu(dec(raw) * CATEGORY_WEIGHT[category])
    if score >= QUALIFIED_THRESHOLD:
        status = "QUALIFIED"
    elif score >= WAITLISTED_THRESHOLD:
        status = "WAITLISTED"
    else:
        status = "REJECTED"
    return score, status


# ------------------------------------------------------- cancellation / close
def fee_schedule_pct(schedule, days_out):
    buckets = sorted(schedule, key=lambda b: b["min_days_out"], reverse=True)
    if days_out < 0:
        for bucket in buckets:
            if bucket["min_days_out"] == 0:
                return dec(bucket["pct"])
        return ZERO
    for bucket in buckets:
        if bucket["min_days_out"] <= days_out:
            return dec(bucket["pct"])
    return ZERO


def cancellation_fee_cents(contract, show, venue_contract, cascade=False):
    if cascade:
        return 0
    if contract["status"] in ("OFFERED", "COUNTERED"):
        return 0
    from db import parse_date, today
    event_start = parse_date(show["event_start"])
    days_out = (event_start - today()).days
    pct = fee_schedule_pct(venue_contract["cancellation_fee_schedule"], days_out)
    return rhu(dec(contract["space_fee_cents"]) * pct / HUNDRED)


def attrition_figures(show, venue_contract):
    committed = venue_contract["committed_net_sqft_per_year"]
    allowance = int((dec(committed) * dec(venue_contract["attrition_allowance_pct"])
                     / HUNDRED).to_integral_value(rounding="ROUND_FLOOR"))
    forgiven_floor = committed - allowance
    actual = 0
    for contract in show_contracts(show["id"]):
        if contract["status"] in ("SIGNED", "CLOSED_OUT"):
            actual += contract_assigned_net_sqft(contract)
    shortfall = max(0, forgiven_floor - actual)
    return shortfall, shortfall * ATTRITION_RATE_CENTS_PER_SQFT


# ------------------------------------------------------------- post-show report
def post_show_report(show):
    from db import by_created
    registrations = show_registrations(show["id"])
    total_registrations = len(registrations)
    qualified_registrations = 0
    attended_registrations = 0
    qualified_attended = 0
    for reg in registrations:
        scans = len(registration_scans(reg["id"]))
        is_qualified = reg["qualification_status"] == "QUALIFIED"
        if is_qualified:
            qualified_registrations += 1
        if scans >= 1:
            attended_registrations += 1
            if is_qualified:
                qualified_attended += 1
    if attended_registrations == 0:
        attendance_quality_index = 0
    else:
        attendance_quality_index = rhu(HUNDRED * dec(qualified_attended)
                                       / dec(attended_registrations))

    report_contracts = [c for c in show_contracts(show["id"])
                        if c["status"] in ("SIGNED", "CLOSED_OUT")]
    lines = []
    total_lead_scans = 0
    scored_pcts = []
    for contract in by_created(report_contracts):
        scans = contract_scans(contract["id"])
        lead_count = len(scans)
        qualified_lead_count = 0
        for scan in scans:
            reg = db.registrations.get(scan["registration_id"])
            if reg is not None and reg["qualification_status"] == "QUALIFIED":
                qualified_lead_count += 1
        if lead_count == 0:
            pct = 0
        else:
            pct = rhu(HUNDRED * dec(qualified_lead_count) / dec(lead_count))
            scored_pcts.append(pct)
        total_lead_scans += lead_count
        lines.append({
            "space_contract_id": contract["id"],
            "exhibitor_id": contract["exhibitor_id"],
            "lead_count": lead_count,
            "qualified_lead_count": qualified_lead_count,
            "exhibitor_lead_quality_pct": pct,
        })
    scored_contract_count = len(scored_pcts)
    if scored_contract_count == 0:
        show_lead_quality_index = 0
    else:
        show_lead_quality_index = rhu(dec(sum(scored_pcts)) / dec(scored_contract_count))
    return {
        "show_id": show["id"],
        "total_registrations": total_registrations,
        "qualified_registrations": qualified_registrations,
        "attended_registrations": attended_registrations,
        "qualified_attended": qualified_attended,
        "attendance_quality_index": attendance_quality_index,
        "scored_contract_count": scored_contract_count,
        "total_lead_scans": total_lead_scans,
        "show_lead_quality_index": show_lead_quality_index,
        "attrition_shortfall_sqft": show["attrition_shortfall_sqft"],
        "attrition_settlement_cents": show["attrition_settlement_cents"],
        "exhibitor_lines": lines,
    }


def sponsor_discount_floor(list_price_cents):
    """PRD 3.7: the hard cap of MAX_SPONSOR_DISCOUNT_PCT off the list price."""
    return rhu(dec(list_price_cents) * (HUNDRED - MAX_SPONSOR_DISCOUNT_PCT) / HUNDRED)
