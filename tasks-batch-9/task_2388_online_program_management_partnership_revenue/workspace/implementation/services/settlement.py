"""Settlement: recognition lines, the marginal tier walk and the waterfall.

PRD 3.8 steps 1 through 7.  The evaluation order and the rounding order are both
pinned by the specification and are deliberately explicit here.
"""

import datetime

import constants as C
import db
from db import store, touch
from services.derive import (contract_year_recognized, recompute_partnership,
                             recompute_program)
from services.money import D, day_span, floor_int, parse_iso_date, rhu_int

RECOGNISED_STATUSES = ("ENROLLED", "ACTIVE", "COMPLETED", "WITHDRAWN")


# --------------------------------------------------------------------------- #
# step 1 — recognition                                                        #
# --------------------------------------------------------------------------- #

def in_scope_enrollments(partnership, statement):
    period_end = parse_iso_date(statement["period_end"])
    rows = []
    for program in db.programs_of(partnership["id"]):
        for enrollment in db.enrollments_of_program(program["id"]):
            if enrollment["status"] not in RECOGNISED_STATUSES:
                continue
            if parse_iso_date(enrollment["term_start_date"]) > period_end:
                continue
            rows.append(enrollment)
    rows.sort(key=lambda e: (e["created_at"], e["student_external_id"]))
    return rows


def _straight_line_amount(enrollment, statement):
    term_start = parse_iso_date(enrollment["term_start_date"])
    term_end = parse_iso_date(enrollment["term_end_date"])
    term_days = day_span(term_start, term_end)
    if term_days <= 0:  # pragma: no cover - term dates are ordered at step 4
        return 0
    charged = D(enrollment["tuition_charged_cents"])

    def elapsed(date_value):
        if date_value < term_start:
            return 0
        return min(day_span(term_start, date_value), term_days)

    def cumulative(date_value):
        return rhu_int(charged * D(elapsed(date_value)) / D(term_days))

    period_start = parse_iso_date(statement["period_start"])
    period_end = parse_iso_date(statement["period_end"])
    prior = period_start - datetime.timedelta(days=1)
    return cumulative(period_end) - cumulative(prior)


def _milestone_amount(enrollment):
    if enrollment["credits_enrolled"] == 0:
        cumulative = 0
    else:
        cumulative = rhu_int(D(enrollment["tuition_charged_cents"])
                             * D(enrollment["credits_completed"])
                             / D(enrollment["credits_enrolled"]))
    return cumulative - enrollment["recognized_to_date_cents"]


def _reverse(statement):
    """Recompute semantics: strip this statement's own prior contributions."""
    for line in statement.get("_lines") or []:
        enrollment = store.enrollments.get(line["enrollment_id"])
        if enrollment is None:  # pragma: no cover
            continue
        if line["amount_cents"]:
            enrollment["recognized_to_date_cents"] -= line["amount_cents"]
            touch(enrollment)
    statement["_lines"] = []
    statement["recognized_revenue_cents"] = 0


# --------------------------------------------------------------------------- #
# step 2 — the marginal tier walk                                             #
# --------------------------------------------------------------------------- #

def tier_walk(amounts, tiers, running):
    """Round half up per line, then sum.  Summing exact line shares and rounding
    once at the end is forbidden (PRD 3.8 step 2)."""
    total = 0
    for amount in amounts:
        remaining = amount
        line_share = D(0)
        if remaining != 0:
            for tier in tiers:
                through = tier["through_cents"]
                room = remaining if through is None else through - running
                if room <= 0:
                    continue
                take = remaining if remaining < room else room
                line_share += D(take) * D(tier["partner_rate"])
                remaining -= take
                running += take
                if remaining == 0:
                    break
        total += rhu_int(line_share)
    return total


# --------------------------------------------------------------------------- #
# steps 3 through 7 — the waterfall                                           #
# --------------------------------------------------------------------------- #

def apply_waterfall(statement, partnership):
    share_gross = statement["share_gross_cents"]
    recoup_cap = floor_int(D(share_gross) * D(C.RECOUP_CAP_PCT))
    unrecouped = partnership["unrecouped_marketing_spend_cents"]
    recoupment = unrecouped if unrecouped < recoup_cap else recoup_cap
    subtotal = share_gross - recoupment
    pct = C.HOLDBACK_HIGH_PCT if subtotal >= C.HOLDBACK_TRIGGER_CENTS else C.HOLDBACK_LOW_PCT
    holdback = rhu_int(D(subtotal) * D(pct))
    fee = (partnership["fee_schedule_monthly_cents"]
           if partnership["contract_structure"] == "FEE_FOR_SERVICE" else 0)

    statement["marketing_recoupment_cents"] = recoupment
    statement["subtotal_cents"] = subtotal
    statement["holdback_pct"] = float(D(pct))
    statement["holdback_cents"] = holdback
    statement["fee_for_service_cents"] = fee
    statement["net_payable_cents"] = subtotal - holdback + fee


def compute_statement(statement, partnership):
    """Run all three settlement calculations in their pinned order."""
    _reverse(statement)

    method = statement["recognition_method_applied"]
    rows = in_scope_enrollments(partnership, statement)

    amounts = []
    lines = []
    for enrollment in rows:
        if method == "MILESTONE_CHRONOLOGICAL":
            amount = _milestone_amount(enrollment)
        else:
            amount = _straight_line_amount(enrollment, statement)
        amounts.append(amount)
        lines.append({"enrollment_id": enrollment["id"], "amount_cents": amount})

    for enrollment, line in zip(rows, lines):
        if line["amount_cents"]:
            enrollment["recognized_to_date_cents"] += line["amount_cents"]
            touch(enrollment)

    statement["_lines"] = lines
    statement["recognized_revenue_cents"] = sum(amounts)
    statement["line_count"] = len(lines)

    for program in db.programs_of(partnership["id"]):
        recompute_program(program)
    recompute_partnership(partnership)

    if partnership["contract_structure"] == "FEE_FOR_SERVICE":
        statement["share_gross_cents"] = 0
    else:
        running = contract_year_recognized(
            partnership,
            parse_iso_date(statement["period_start"]),
            exclude_id=statement["id"],
        )
        statement["share_gross_cents"] = tier_walk(
            amounts, partnership["revenue_share_tiers"], running)

    apply_waterfall(statement, partnership)
