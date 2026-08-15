"""Calculation rules per scaffold §1.3.

excusable_delay_credit, payment_certification, change_order_pricing,
additional_service_billing, contract_position, ca_posture_derivation.

All money is integer cents; all percentage products round half up to the cent
before participating in further arithmetic.
"""

import math
from decimal import Decimal, ROUND_HALF_UP

import db
from services.helpers import touch

# payment_certification constants
HIGH_PCT = Decimal("0.10")
LOW_PCT = Decimal("0.05")
HALFWAY_PCT = Decimal("0.50")
STORED_PCT = Decimal("0.10")

# change_order_pricing constants
TIER1_CAP_CENTS = 5_000_000
TIER2_CAP_CENTS = 5_000_000
TIER1_PCT = Decimal("0.10")
TIER2_PCT = Decimal("0.07")
TIER3_PCT = Decimal("0.04")

# additional_service_billing constants
MONTH_DAYS = 30


def _rh_up(value: Decimal) -> int:
    """Round a Decimal half up to whole cents."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def retainage_on_gross(gross: int, mode: str, threshold_cents: int) -> int:
    """R(g) per CaProject.retainage_mode, using the CURRENT mode and CURRENT
    threshold for both evaluations. A fractional-cent product is rounded half
    up to the cent."""
    g = Decimal(gross)
    t = Decimal(threshold_cents)
    if mode == "TIERED_MARGINAL":
        return _rh_up(HIGH_PCT * min(g, t)) + _rh_up(LOW_PCT * max(Decimal(0), g - t))
    # REDUCTION_AT_HALFWAY
    if g < t:
        return _rh_up(HIGH_PCT * g)
    return _rh_up(LOW_PCT * g)


def halfway_threshold(project: dict) -> int:
    return _rh_up(HALFWAY_PCT * Decimal(project["adjusted_contract_sum_cents"]))


def payment_certification_compute(project: dict, app: dict) -> dict:
    """Pinned evaluation order per payment_certification (both variants).

    Uses the application's current lines / period_ending_date. Mutates the
    application's computed snapshot fields and returns the computed dict.
    """
    prev = find_previous_application(project["id"], app["period_ending_date"], exclude_id=app["id"])
    gross_prev = prev["gross_work_completed_cents"] if prev else 0

    earned_work = sum(line["work_completed_this_period_cents"] for line in app["lines"])
    gross_now = gross_prev + earned_work

    threshold = halfway_threshold(project)
    mode = project["retainage_mode"]
    retainage_work = retainage_on_gross(gross_now, mode, threshold) - retainage_on_gross(gross_prev, mode, threshold)

    # PINNED ROUNDING ORDER: round per line first, then sum.
    retainage_stored = sum(
        _rh_up(Decimal(line["stored_materials_cents"]) * STORED_PCT) for line in app["lines"]
    )
    stored_total = sum(line["stored_materials_cents"] for line in app["lines"])

    current_due = earned_work - retainage_work + (stored_total - retainage_stored)

    return {
        "previous_application_id": prev["id"] if prev else None,
        "gross_work_completed_cents": gross_now,
        "earned_work_this_period_cents": earned_work,
        "retainage_work_cents": retainage_work,
        "retainage_stored_cents": retainage_stored,
        "current_due_cents": current_due,
    }


def find_previous_application(project_id: str, period_ending_date: str, exclude_id: str | None = None):
    """CERTIFIED application on the same project with the greatest
    period_ending_date strictly before the given one; tie-break created_at ASC.
    VOIDED applications are excluded."""
    candidates = [
        a for a in db.payment_applications.values()
        if a["project_id"] == project_id
        and a["status"] == "CERTIFIED"
        and a["period_ending_date"] < period_ending_date
        and a["id"] != exclude_id
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda a: (-_date_key(a["period_ending_date"]), a["created_at"], a["id"]))
    return candidates[0]


def _date_key(date_str: str) -> int:
    return db.parse_date(date_str).toordinal()


def change_order_pricing(net_cost_change_cents: int) -> tuple[int, int]:
    """Returns (markup_cents, total_amount_cents). Marginal tiers; 0 for deducts."""
    net = net_cost_change_cents
    if net > 0:
        markup = (
            _rh_up(TIER1_PCT * Decimal(min(net, TIER1_CAP_CENTS)))
            + _rh_up(TIER2_PCT * Decimal(min(max(net - TIER1_CAP_CENTS, 0), TIER2_CAP_CENTS)))
            + _rh_up(TIER3_PCT * Decimal(max(net - TIER1_CAP_CENTS - TIER2_CAP_CENTS, 0)))
        )
    else:
        markup = 0
    return markup, net + markup


def recompute_excusable_delay(project: dict) -> bool:
    """CaProject.excusable_delay_days = sum of credited_delay_days over ALL
    Submittals and RFIs of the project. Returns True when the value changed."""
    total = sum(
        s["credited_delay_days"] for s in db.submittals.values() if s["project_id"] == project["id"]
    ) + sum(
        r["credited_delay_days"] for r in db.rfis.values() if r["project_id"] == project["id"]
    )
    changed = total != project["excusable_delay_days"]
    project["excusable_delay_days"] = total
    return changed


def recompute_posture(project: dict):
    """ca_posture = EXTENDED_DURATION iff status == ACTIVE and clock date is
    strictly later than adjusted date + excusable delay + grace days."""
    horizon = db.add_days(
        project["adjusted_substantial_completion_date"],
        project["excusable_delay_days"] + project["grace_days"],
    )
    if project["status"] == "ACTIVE" and db.today() > horizon:
        project["ca_posture"] = "EXTENDED_DURATION"
    else:
        project["ca_posture"] = "NORMAL"


def recompute_posture_all_active():
    for p in db.projects.values():
        if p["status"] == "ACTIVE":
            old = p["ca_posture"]
            recompute_posture(p)
            if p["ca_posture"] != old:
                touch(p)


def recompute_contract_position(project: dict):
    """certified_to_date_cents and retainage_held_cents per contract_position."""
    certified = [
        a for a in db.payment_applications.values()
        if a["project_id"] == project["id"] and a["status"] == "CERTIFIED"
    ]
    project["certified_to_date_cents"] = sum(a["certified_current_due_cents"] or 0 for a in certified)
    if certified:
        latest = max(certified, key=lambda a: (_date_key(a["period_ending_date"]), a["created_at"], a["id"]))
        mode = project["retainage_mode"]
        threshold = halfway_threshold(project)
        project["retainage_held_cents"] = (
            retainage_on_gross(latest["gross_work_completed_cents"], mode, threshold)
            + sum(a["retainage_stored_cents"] for a in certified)
        )
    else:
        project["retainage_held_cents"] = 0


def invoice_horizon_start(project: dict) -> str:
    return db.add_days(
        project["adjusted_substantial_completion_date"],
        project["excusable_delay_days"] + project["grace_days"],
    )


def invoice_horizon_end(project: dict, creation: bool = False) -> str:
    """horizon_end_date = substantial_completion_actual_date when already
    achieved at computation time, else the logical-clock date."""
    if project["substantial_completion_actual_date"] is not None:
        return project["substantial_completion_actual_date"]
    return db.today()


def invoice_billable_days(period_start: str, period_end: str, horizon_start: str, horizon_end: str) -> int:
    """Count of calendar dates d with period_start <= d <= period_end AND
    horizon_start_date < d <= horizon_end_date."""
    ps = db.parse_date(period_start).toordinal()
    pe = db.parse_date(period_end).toordinal()
    hs = db.parse_date(horizon_start).toordinal()
    he = db.parse_date(horizon_end).toordinal()
    lo = max(ps, hs + 1)
    hi = min(pe, he)
    return max(0, hi - lo + 1)


def invoice_amount(project: dict, billable_days: int) -> int:
    if project["billing_method"] == "PER_DIEM_PRORATED":
        return billable_days * project["daily_extension_rate_cents"]
    # WHOLE_MONTH
    return math.ceil(billable_days / MONTH_DAYS) * project["monthly_extension_rate_cents"]


def compute_invoice_fields(project: dict, period_start: str, period_end: str) -> dict:
    hs = invoice_horizon_start(project)
    he = invoice_horizon_end(project)
    days = invoice_billable_days(period_start, period_end, hs, he)
    return {
        "horizon_start_date": hs,
        "horizon_end_date": he,
        "billable_days": days,
        "amount_cents": invoice_amount(project, days),
    }


def recompute_draft_invoices(project: dict):
    """Every DRAFT invoice of the project recomputes; a draft whose billable
    days fall to 0 auto-transitions to CANCELLED. Each recomputed invoice is
    a mutation (updated_at refreshed, version incremented)."""
    for inv in db.invoices.values():
        if inv["project_id"] != project["id"] or inv["status"] != "DRAFT":
            continue
        fields = compute_invoice_fields(project, inv["period_start"], inv["period_end"])
        inv.update(fields)
        if inv["billable_days"] == 0:
            inv["status"] = "CANCELLED"
        touch(inv)


def recompute_project_dependents(project: dict, delay_changed: bool):
    """Common side-effect chain after excusable-delay / adjusted-date changes:
    project excusable delay + posture + DRAFT invoices, each touched."""
    recompute_posture(project)
    touch(project)
    recompute_draft_invoices(project)
