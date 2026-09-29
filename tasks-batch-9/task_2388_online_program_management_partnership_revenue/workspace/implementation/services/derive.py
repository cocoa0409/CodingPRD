"""Derived-field recomputation (PRD 2.7 INV-1/INV-2 and 2.8).

Every derived total is recomputed from the underlying facts rather than
incremented, so a compensating entry restores the prior position exactly and no
drift can survive a cascade.
"""

import datetime

import db
from db import store, touch, touch_soft
from services.money import D, add_months, parse_iso_date, rhu_int


def _set(entity, name, value, bump=True):
    """Assign a derived field; mutate metadata only when the value changed."""
    if entity.get(name) == value:
        return False
    entity[name] = value
    if bump:
        touch(entity)
    else:
        touch_soft(entity)
    return True


# --------------------------------------------------------------------------- #
# contract year                                                               #
# --------------------------------------------------------------------------- #

def contract_year_window(partnership, reference_date):
    """The twelve-month window that begins on effective_date and repeats on each
    anniversary, containing ``reference_date``."""
    start = parse_iso_date(partnership["effective_date"])
    if start is None:  # pragma: no cover - effective_date is validated
        return None, None
    while True:
        nxt = add_months(start, 12)
        if nxt <= reference_date:
            start = nxt
            continue
        return start, nxt


def _in_contract_year(partnership, statement, window):
    period_start = parse_iso_date(statement["period_start"])
    return window[0] <= period_start < window[1]


def contract_year_recognized(partnership, reference_date, exclude_id=None):
    window = contract_year_window(partnership, reference_date)
    if window[0] is None:  # pragma: no cover
        return 0
    total = 0
    for st in db.statements_of(partnership["id"]):
        if exclude_id is not None and st["id"] == exclude_id:
            continue
        if _in_contract_year(partnership, st, window):
            total += st.get("recognized_revenue_cents") or 0
    return total


# --------------------------------------------------------------------------- #
# enrollment / program / partnership                                          #
# --------------------------------------------------------------------------- #

def recompute_enrollment_cash(enrollment):
    collected = 0
    refunded = 0
    for entry in db.payments_of(enrollment["id"]):
        if entry["entry_type"] == "PAYMENT":
            collected += entry["amount_cents"]
        else:
            refunded += entry["amount_cents"]
    changed = _set(enrollment, "collected_cents", collected)
    changed = _set(enrollment, "refunded_cents", refunded) or changed
    return changed


def recompute_program(program):
    enrollments = db.enrollments_of_program(program["id"])
    active = sum(1 for e in enrollments if e["status"] in ("ENROLLED", "ACTIVE"))
    total = sum(1 for e in enrollments
                if e["status"] in ("ENROLLED", "ACTIVE", "COMPLETED"))
    recognized = sum(e["recognized_to_date_cents"] for e in enrollments)

    spend = 0
    for entry in db.marketing_of(program["id"]):
        if entry["entry_type"] == "SPEND":
            spend += entry["amount_cents"]
        else:
            spend -= entry["amount_cents"]

    cac = None if total == 0 else rhu_int(D(spend) / D(total))

    _set(program, "active_enrollment_count", active)
    _set(program, "total_enrollment_count", total)
    _set(program, "recognized_revenue_cents", recognized)
    _set(program, "marketing_spend_net_cents", spend)
    _set(program, "blended_cac_cents", cac)


def posted_net_marketing(partnership_id):
    total = 0
    for program in db.programs_of(partnership_id):
        for entry in db.marketing_of(program["id"]):
            if entry["entry_type"] == "SPEND":
                total += entry["amount_cents"]
            else:
                total -= entry["amount_cents"]
    return total


def recompute_partnership(partnership):
    """All of the partnership's derived ledger totals.  Refreshes ``updated_at``
    without advancing ``version`` (PRD 2.4)."""
    pid = partnership["id"]

    collected = 0
    recognized = 0
    for program in db.programs_of(pid):
        for enrollment in db.enrollments_of_program(program["id"]):
            recognized += enrollment["recognized_to_date_cents"]
            for entry in db.payments_of(enrollment["id"]):
                if entry["entry_type"] == "PAYMENT":
                    collected += entry["amount_cents"]
                else:
                    collected -= entry["amount_cents"]

    posted_net = posted_net_marketing(pid)
    remitted = 0
    holdback = 0
    recouped = 0
    for st in db.statements_of(pid):
        if st["status"] == "REMITTED":
            remitted += st["net_payable_cents"]
            holdback += st["holdback_cents"]
            recouped += st["marketing_recoupment_cents"]

    released = 0
    for program in db.programs_of(pid):
        for plan in db.plans_of(program["id"]):
            if plan["status"] == "CERTIFIED":
                released += plan["holdback_applied_cents"] or 0

    remaining = 0
    if partnership.get("executed_date") is not None:
        remaining = partnership["marketing_budget_cents"] - posted_net

    cy = contract_year_recognized(partnership, db.current_date())

    _set(partnership, "collected_tuition_cents", collected, bump=False)
    _set(partnership, "recognized_revenue_cents", recognized, bump=False)
    _set(partnership, "contract_year_recognized_cents", cy, bump=False)
    _set(partnership, "remitted_to_partner_cents", remitted, bump=False)
    _set(partnership, "holdback_balance_cents", holdback - released, bump=False)
    _set(partnership, "marketing_budget_remaining_cents", remaining, bump=False)
    _set(partnership, "unrecouped_marketing_spend_cents",
         posted_net - recouped, bump=False)


def recompute_counselor_pipeline(counselor):
    open_count = sum(1 for lead in db.leads_of_counselor(counselor["id"])
                     if lead["status"] in ("NEW", "CONTACTED", "APPLIED"))
    return _set(counselor, "open_pipeline_count", open_count)


def recompute_chain(program):
    """Recompute a program and then its partnership."""
    recompute_program(program)
    partnership = store.partnerships.get(program["partnership_id"])
    if partnership is not None:
        recompute_partnership(partnership)


def expiry_date(effective_date, term_months):
    """effective_date plus term_months, minus one day."""
    start = parse_iso_date(effective_date)
    end = add_months(start, term_months)
    return (end - datetime.timedelta(days=1)).isoformat()
