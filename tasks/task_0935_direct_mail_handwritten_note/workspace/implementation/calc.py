"""The thirteen calculation rules of scaffold section 1.3 / PRD section 3."""
import datetime
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP

import derive
import store
from errors import ApiError
from store import db


def round_half_up(value, places=0):
    q = Decimal(1).scaleb(-places)
    return Decimal(value).quantize(q, rounding=ROUND_HALF_UP)


def ceil_cents(value):
    return int(Decimal(value).quantize(Decimal(1), rounding=ROUND_CEILING))


def floor_cents(value):
    return int(Decimal(value).quantize(Decimal(1), rounding=ROUND_FLOOR))


def ceil_div(numerator, denominator):
    return -((-numerator) // denominator)


# ------------------------------------------------------ cass_deliverability_tier
def cass_deliverability_tier(record):
    """Deterministic mapping, first matching clause wins (PRD 3.3)."""
    if record["country_code"] != store.DOMESTIC_COUNTRY_CODE:
        return "UNMAILABLE", "UNMAILABLE"
    code = record["dpv_confirmation_code"]
    if code == "Y":
        return "STANDARDIZED", "AUTOMATION"
    if code in ("D", "S"):
        return "STANDARDIZED", "RETAIL"
    return "UNMAILABLE", "UNMAILABLE"


def apply_cass_to_record(record):
    cass_status, tier = cass_deliverability_tier(record)
    record["cass_status"] = cass_status
    record["deliverability_tier"] = tier


# ------------------------------------------------------------- dedupe_screen
def dedupe_screen(mailing_list_id, mode):
    """Group, order by created_at ASC then insertion_seq ASC, first survives."""
    rows = derive.list_records_of(mailing_list_id)
    for r in rows:
        r["dedupe_status"] = "UNSCREENED"
    key_field = "exact_key" if mode == "EXACT" else "household_key"
    survivor_label = "UNIQUE" if mode == "EXACT" else "HOUSEHOLD_HEAD"
    duplicate_label = "DUP_EXACT" if mode == "EXACT" else "DUP_HOUSEHOLD"
    groups = {}
    for r in rows:
        groups.setdefault(r[key_field], []).append(r)
    for members in groups.values():
        ordered = sorted(members, key=lambda r: (r["created_at"], r["insertion_seq"]))
        ordered[0]["dedupe_status"] = survivor_label
        for r in ordered[1:]:
            r["dedupe_status"] = duplicate_label


# ------------------------------------------------------- presort_tier_selection
def presort_tier_selection(job, automation_pieces):
    if job["job_kind"] == "EDDM":
        return "EDDM_ROUTE"
    if job["mail_class"] == "FIRST_CLASS":
        if automation_pieces >= store.FIRST_CLASS_AUTOMATION_MIN_PIECES:
            return "PRESORT_AADC"
        return "NO_PRESORT"
    if automation_pieces >= store.PRESORT_5D_MIN_PIECES:
        return "PRESORT_5D"
    if automation_pieces >= store.PRESORT_AADC_MIN_PIECES:
        return "PRESORT_AADC"
    if automation_pieces >= store.PRESORT_MIXED_AADC_MIN_PIECES:
        return "PRESORT_MIXED_AADC"
    return "NO_PRESORT"


MARKETING_AUTOMATION_RATE = {
    "PRESORT_5D": store.PRESORT_5D_RATE_CENTS,
    "PRESORT_AADC": store.PRESORT_AADC_RATE_CENTS,
    "PRESORT_MIXED_AADC": store.PRESORT_MIXED_AADC_RATE_CENTS,
    "NO_PRESORT": store.MARKETING_NO_PRESORT_RATE_CENTS,
}


# ---------------------------------------------------------- eddm_route_pricing
def refresh_route(route):
    route["selected_piece_count"] = route["residential_piece_count"] + route["business_piece_count"]
    if route["total_deliveries"]:
        pct = round_half_up(
            Decimal(100) * Decimal(route["selected_piece_count"]) / Decimal(route["total_deliveries"]),
            2,
        )
    else:
        pct = Decimal("0.00")
    route["saturation_pct"] = float(pct)


def eddm_route_pricing(job, routes):
    """Returns the per-piece rate, raising ERR_EDDM_VARIANT_INELIGIBLE (rung 33)
    when one route fails the declared variant's eligibility test."""
    for route in routes:
        refresh_route(route)
    variant = job["eddm_rate_variant"]
    if variant == "SATURATION":
        eligible = all(r["selected_piece_count"] == r["total_deliveries"] for r in routes)
        rate = store.EDDM_SATURATION_RATE_CENTS
    else:
        eligible = all(r["residential_piece_count"] >= store.EDDM_HDPLUS_MIN_RESIDENTIAL_PIECES
                       for r in routes)
        rate = store.EDDM_HDPLUS_RATE_CENTS
    if not eligible:
        raise ApiError("ERR_EDDM_VARIANT_INELIGIBLE")
    return rate


# ------------------------------------------------------------ postage_estimate
def surviving_records(job, variant):
    """PROVISIONAL counts every CASS-mailable record, ignoring dedupe_status.
    FINAL additionally requires a surviving dedupe_status."""
    if not job["mailing_list_id"]:
        return []
    rows = derive.list_records_of(job["mailing_list_id"])
    out = []
    for r in rows:
        if r["deliverability_tier"] not in derive.MAILABLE_TIERS:
            continue
        if variant == "FINAL" and r["dedupe_status"] not in derive.SURVIVING_DEDUPE:
            continue
        out.append(r)
    return out


def job_piece_counts(job, variant):
    """Returns (automation, retail, unmailable, eddm, billable)."""
    if job["job_kind"] == "EDDM":
        routes = derive.job_routes(job["id"])
        for route in routes:
            refresh_route(route)
        pieces = sum(r["selected_piece_count"] for r in routes)
        return 0, 0, 0, pieces, pieces
    survivors = surviving_records(job, variant)
    automation = sum(1 for r in survivors if r["deliverability_tier"] == "AUTOMATION")
    retail = sum(1 for r in survivors if r["deliverability_tier"] == "RETAIL")
    unmailable = 0
    if job["mailing_list_id"]:
        unmailable = sum(1 for r in derive.list_records_of(job["mailing_list_id"])
                         if r["deliverability_tier"] == "UNMAILABLE")
    return automation, retail, unmailable, 0, automation + retail


def postage_for(job, automation, retail, eddm_pieces, presort_tier):
    """Round each tier subtotal to whole cents, THEN sum (PRD 3.4, pinned)."""
    if job["job_kind"] == "EDDM":
        rate = eddm_route_pricing(job, derive.job_routes(job["id"]))
        return int(round_half_up(Decimal(eddm_pieces) * Decimal(rate)))
    if job["mail_class"] == "MARKETING_MAIL":
        auto_rate = MARKETING_AUTOMATION_RATE[presort_tier]
        retail_rate = store.MARKETING_RETAIL_TIER_RATE_CENTS
    else:
        if automation >= store.FIRST_CLASS_AUTOMATION_MIN_PIECES:
            auto_rate = store.FIRST_CLASS_AUTOMATION_RATE_CENTS
        else:
            auto_rate = store.FIRST_CLASS_RETAIL_RATE_CENTS
        retail_rate = store.FIRST_CLASS_RETAIL_RATE_CENTS
    auto_subtotal = int(round_half_up(Decimal(automation) * Decimal(auto_rate)))
    retail_subtotal = int(round_half_up(Decimal(retail) * Decimal(retail_rate)))
    return auto_subtotal + retail_subtotal


# ---------------------------------------------------------- commit_settlement
def commit_settlement(postage_cents, billable_piece_count):
    handling = store.HANDLING_BASE_CENTS + ceil_cents(
        Decimal(postage_cents) * Decimal(store.HANDLING_PCT))
    subtotal = postage_cents + handling
    if billable_piece_count >= store.VOLUME_CREDIT_MIN_PIECES:
        credit = floor_cents(Decimal(subtotal) * Decimal(store.VOLUME_CREDIT_PCT))
    else:
        credit = 0
    total_due = subtotal - credit
    return handling, credit, total_due


# ------------------------------------------------------ production_capacity_plan
def production_capacity_plan(piece_count, character_count, chars_per_minute,
                             ink_ul_per_1000_chars, capacity_variant):
    chars = piece_count * character_count
    write_minutes = ceil_div(chars, chars_per_minute)
    passes = (store.SINGLE_PASS_SETUP_PASSES if capacity_variant == "SINGLE_PASS"
              else store.SPLIT_RUN_SETUP_PASSES)
    slot_minutes = write_minutes + store.RUN_SETUP_MINUTES * passes
    ink_ul = ceil_cents(Decimal(chars) * Decimal(str(ink_ul_per_1000_chars)) / Decimal(1000))
    return write_minutes, slot_minutes, ink_ul


# ------------------------------------------------------- mail_date_derivation
def mail_date_derivation(anchor_date, mail_class, anchor_variant):
    """Rungs 27, 28 and 29 in their pinned order (PRD 3.6)."""
    transit = store.TRANSIT_DAYS[mail_class]
    current_date = store.today()
    # STEP 1 (rung 27) — strict: an anchor equal to today passes.
    if anchor_date < current_date:
        raise ApiError("ERR_IN_HOME_DATE_PAST")
    # STEP 2
    if anchor_variant == "ANCHOR_IN_HOME":
        raw = anchor_date - datetime.timedelta(days=transit)
    else:
        raw = anchor_date
    # STEP 3 (rung 28) — cap is INCLUSIVE: a shift of exactly 5 is accepted.
    shift = 0
    blackouts = set(b["blackout_date"] for b in db.blackout_dates.values())
    while raw in blackouts:
        raw = raw - datetime.timedelta(days=1)
        shift += 1
        if shift > store.BLACKOUT_SHIFT_MAX_DAYS:
            raise ApiError("ERR_BLACKOUT_UNRESOLVABLE")
    # STEP 4 (rung 29) — strict: landing exactly on current_date + 3 is accepted.
    if raw < current_date + datetime.timedelta(days=store.PRODUCTION_LEAD_DAYS):
        raise ApiError("ERR_MAIL_DATE_UNREACHABLE")
    return raw, raw + datetime.timedelta(days=transit), shift


# --------------------------------------------------------- return_settlement
def return_settlement(record, job):
    entitlement = "REPRINT" if record["move_status"] == "MOVE_APPLIED" else "REFUND"
    if job["mail_class"] == "FIRST_CLASS":
        fee = store.RETURN_FEE_CENTS_FIRST_CLASS
    elif job["mail_class"] == "MARKETING_MAIL":
        fee = store.RETURN_FEE_CENTS_MARKETING_MAIL
    else:
        fee = 0
    return entitlement, fee
