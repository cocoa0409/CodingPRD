"""The compliance calendar: date derivation, pricing, the reminder ladder and
the monotone status ladder (PRD 3.4, 3.5, 3.6)."""

import lookup
import timeutil
from constants import (
    DUE_SOON_WINDOW_DAYS,
    LATE_FEE_MONTH_BLOCK_DAYS,
    OBLIGATION_LADDER,
    OPEN_OBLIGATION_STATUSES,
    OVERDUE_REMINDER_OFFSET_DAYS,
    REMINDER_OFFSETS_DAYS,
    SERVICE_FEE_BASE_CENTS,
    VOLUME_DISCOUNT_BPS,
    VOLUME_DISCOUNT_THRESHOLD_OPEN_OBLIGATIONS,
)
from money import round_half_up
from services import rollups
from store import DB, new_row, touch


# ---------------------------------------------------------------------------
# dates
# ---------------------------------------------------------------------------
def derive_due_date(entity, rule, period_year):
    """PRD 3.4: "The same derivation produces due_date for every obligation
    type; the type does not branch the formula, only the pinned rule's
    annual_report_basis does."

    ADJUDICATION OF FRICTION 4 -- due_date for BOI_INITIAL / BOI_UPDATE /
    FINAL_REPORT obligations.  Reading: THE STATE-RULE FORMULA FOR EVERY TYPE,
    exactly as the sentence above says; the entity's boi_initial_deadline /
    boi_update_deadline are the federal axis of PRD 3.10 and are not consulted
    here.  This keeps the largest number of declared behaviours reachable: the
    three annual_report_basis variants, the grace/delinquency derivations and
    the whole reminder ladder stay exercisable on every one of the five
    obligation types, whereas borrowing the federal deadline would make those
    branches unreachable for three of the five types and would leave the
    derivation undefined whenever the federal deadline is null (an exempt
    entity, or an entity that has never armed an update clock).
    """
    basis = rule["annual_report_basis"]
    if basis == "ANNIVERSARY_MONTH_DAY":
        month = entity["formation_date"].month
        day = timeutil.clamp_day(period_year, month, entity["formation_date"].day)
        raw = _safe_date(period_year, month, day)
    elif basis == "FIXED_CALENDAR_DATE":
        month = rule["fixed_due_month"]
        day = timeutil.clamp_day(period_year, month, rule["fixed_due_day"])
        raw = _safe_date(period_year, month, day)
    else:  # FISCAL_YEAR_END_OFFSET
        month = entity["fiscal_year_end_month"]
        day = timeutil.clamp_day(period_year, month, entity["fiscal_year_end_day"])
        raw = _safe_date(period_year, month, day)
        raw = timeutil.add_days(raw, rule["fiscal_offset_days"])
    return timeutil.roll_forward(raw)


def _safe_date(year, month, day):
    import datetime

    return datetime.date(year, month, day)


def derive_grace_end(due_date, rule):
    if rule["grace_basis"] == "CALENDAR_DAYS":
        # deliberately NOT rolled; it may fall on a weekend or a holiday
        return timeutil.add_days(due_date, rule["grace_days"])
    working = due_date
    for _ in range(rule["grace_days"]):
        working = timeutil.roll_forward(timeutil.add_days(working, 1))
    return working


def derive_delinquency_date(grace_end_date, rule):
    return timeutil.add_days(grace_end_date, rule["delinquency_to_dissolution_days"])


def derive_all_dates(entity, rule, period_year):
    due = derive_due_date(entity, rule, period_year)
    grace_end = derive_grace_end(due, rule)
    return due, grace_end, derive_delinquency_date(grace_end, rule)


# ---------------------------------------------------------------------------
# money
# ---------------------------------------------------------------------------
def state_fee_for(obligation_type, rule):
    if obligation_type in ("ANNUAL_REPORT", "FINAL_REPORT"):
        return rule["annual_report_fee_cents"]
    if obligation_type == "FRANCHISE_TAX":
        return rule["franchise_tax_filing_fee_cents"]
    return 0  # BOI_INITIAL / BOI_UPDATE: the registry charges no state fee


def franchise_tax_for(obligation_type, entity, rule):
    if obligation_type != "FRANCHISE_TAX":
        return 0
    basis = rule["franchise_tax_basis"]
    if basis == "FLAT":
        return rule["flat_franchise_tax_cents"]
    if basis == "AUTHORIZED_SHARES_TIERS":
        tiers = sorted(
            rule["authorized_shares_tiers"],
            key=lambda t: (t["up_to_shares"] is None, t["up_to_shares"] or 0),
        )
        for tier in tiers:
            if tier["up_to_shares"] is None or entity["authorized_shares"] <= tier["up_to_shares"]:
                return tier["tax_cents"]
        return 0
    if basis == "ASSUMED_PAR_VALUE":
        if entity["authorized_shares"] == 0:
            assumed_par_capital = 0
        else:
            assumed_par_capital = round_half_up(
                entity["total_gross_assets_cents"] * entity["issued_shares"],
                entity["authorized_shares"],
            )
        raw = round_half_up(assumed_par_capital * rule["assumed_par_value_rate_bps"], 10000)
        return max(rule["min_franchise_tax_cents"], min(raw, rule["max_franchise_tax_cents"]))
    # GROSS_RECEIPTS_BRACKETS
    brackets = sorted(
        rule["gross_receipts_brackets"],
        key=lambda b: (b["up_to_cents"] is None, b["up_to_cents"] or 0),
    )
    for bracket in brackets:
        if (
            bracket["up_to_cents"] is None
            or entity["annual_gross_receipts_cents"] <= bracket["up_to_cents"]
        ):
            return bracket["tax_cents"]
    return 0


def late_fee_for(state_fee_cents, franchise_tax_cents, grace_end_date, rule, assessment_date):
    days_late = max(0, timeutil.day_diff(assessment_date, grace_end_date))
    if days_late == 0:
        return 0
    style = rule["late_fee_style"]
    if style == "FLAT":
        return rule["late_fee_flat_cents"]
    if style == "PER_MONTH":
        blocks = -(-days_late // LATE_FEE_MONTH_BLOCK_DAYS)  # ceiling division
        return blocks * rule["late_fee_per_month_cents"]
    base = state_fee_cents + franchise_tax_cents
    raw = round_half_up(base * rule["late_fee_percent_bps"], 10000)
    return min(raw, rule["late_fee_cap_cents"])


def service_fee_for(client_id):
    """Pinned once at creation; the discount is keyed on the open-obligation
    count measured BEFORE the new row is inserted (PRD 3.5)."""
    prior_open = sum(
        1 for o in lookup.obligations_of_client(client_id) if o["status"] in OPEN_OBLIGATION_STATUSES
    )
    if prior_open >= VOLUME_DISCOUNT_THRESHOLD_OPEN_OBLIGATIONS:
        discount = round_half_up(SERVICE_FEE_BASE_CENTS * VOLUME_DISCOUNT_BPS, 10000)
    else:
        discount = 0
    return SERVICE_FEE_BASE_CENTS - discount


def recompute_total(obligation):
    obligation["total_due_cents"] = (
        obligation["state_fee_cents"]
        + obligation["franchise_tax_cents"]
        + obligation["late_fee_cents"]
        + obligation["service_fee_cents"]
    )
    return obligation["total_due_cents"]


def reprice_late_fee(obligation, assessment_date):
    rule = DB.state_rules.get(obligation["governing_rule_id"])
    if rule is None:  # pragma: no cover - defensive
        return
    obligation["late_fee_cents"] = late_fee_for(
        obligation["state_fee_cents"],
        obligation["franchise_tax_cents"],
        obligation["grace_end_date"],
        rule,
        assessment_date,
    )
    recompute_total(obligation)


# ---------------------------------------------------------------------------
# the reminder ladder
# ---------------------------------------------------------------------------
def mint_reminder_ladder(obligation):
    minted = []
    for offset in REMINDER_OFFSETS_DAYS:
        minted.append(
            _mint_reminder(
                obligation, "T_MINUS_%d" % offset, timeutil.add_days(obligation["due_date"], -offset)
            )
        )
    minted.append(
        _mint_reminder(
            obligation,
            "OVERDUE",
            timeutil.add_days(obligation["grace_end_date"], OVERDUE_REMINDER_OFFSET_DAYS),
        )
    )
    return minted


def _mint_reminder(obligation, label, scheduled_for):
    return new_row(
        DB.reminders,
        {
            "compliance_obligation_id": obligation["id"],
            "offset_label": label,
            "scheduled_for": scheduled_for,
            "due_date_snapshot": obligation["due_date"],
            "status": "PENDING",
            "sent_on": None,
        },
    )


def suppress_reminders(obligation):
    """PRD 3.6: when an obligation leaves the ladder every notice in PENDING
    moves to SUPPRESSED and every notice in SENT also moves to SUPPRESSED."""
    for notice in lookup.reminders_of_obligation(obligation["id"]):
        if notice["status"] in ("PENDING", "SENT"):
            notice["status"] = "SUPPRESSED"
            touch(notice)


# ---------------------------------------------------------------------------
# terminal transitions
# ---------------------------------------------------------------------------
def to_terminal(obligation, status, zero_total):
    obligation["status"] = status
    obligation["satisfied_on"] = timeutil.today()
    if zero_total:
        obligation["total_due_cents"] = 0
    touch(obligation)
    suppress_reminders(obligation)


# ---------------------------------------------------------------------------
# the monotone status ladder
# ---------------------------------------------------------------------------
def target_status(obligation, clock_date):
    if clock_date > obligation["grace_end_date"]:
        return "DELINQUENT"
    if clock_date > obligation["due_date"]:
        return "IN_GRACE"
    if clock_date >= timeutil.add_days(obligation["due_date"], -DUE_SOON_WINDOW_DAYS):
        return "DUE_SOON"
    return "SCHEDULED"


def advance(obligation, clock_date):
    """Returns True when the row actually moved rungs."""
    if obligation["status"] not in OPEN_OBLIGATION_STATUSES:
        return False
    current_index = OBLIGATION_LADDER.index(obligation["status"])
    target_index = OBLIGATION_LADDER.index(target_status(obligation, clock_date))
    new_index = max(current_index, target_index)
    if new_index == current_index:
        return False
    obligation["status"] = OBLIGATION_LADDER[new_index]
    reprice_late_fee(obligation, clock_date)
    touch(obligation)
    return True


def satisfy(obligation):
    """Cascade hops 2-5 of PRD 2.12, driven by an ACCEPTED filing outcome."""
    to_terminal(obligation, "SATISFIED", zero_total=False)
    cure_registration(DB.registrations.get(obligation["registration_id"]))
    rollups.cascade_from_obligation(obligation)


def cure_registration(registration):
    """Hop 4: a DELINQUENT registration returns to ACTIVE once no obligation of
    it remains DELINQUENT.  A hop that does not fire touches nothing."""
    if registration is None or registration["status"] != "DELINQUENT":
        return False
    still_delinquent = any(
        o["status"] == "DELINQUENT" for o in lookup.obligations_of_registration(registration["id"])
    )
    if still_delinquent:
        return False
    registration["status"] = "ACTIVE"
    rollups.recompute_registration_rank(registration)
    touch(registration)
    return True
