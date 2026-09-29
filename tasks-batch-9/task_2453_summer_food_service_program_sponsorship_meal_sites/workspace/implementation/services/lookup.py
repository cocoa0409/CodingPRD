"""Existence resolution.

Callers must invoke these in the sequence fixed by PRD sec 2.6 step 4:
sponsor, area record, budget, advance, site, service day, count entry,
holding-log entry, monitoring visit, corrective action, claim, line item.
"""

import db
from errors import ApiError


def _resolve(collection, identifier, error_id):
    if not isinstance(identifier, str) or identifier == "":
        raise ApiError(error_id)
    row = collection.get(identifier)
    if row is None:
        raise ApiError(error_id)
    return row


def require_sponsor(identifier):
    return _resolve(db.store.sponsors, identifier, "ERR_SPONSOR_NOT_FOUND")


def require_area_record(identifier):
    return _resolve(db.store.area_records, identifier, "ERR_AREA_RECORD_NOT_FOUND")


def require_budget(identifier):
    return _resolve(db.store.budgets, identifier, "ERR_BUDGET_NOT_FOUND")


def require_advance(identifier):
    return _resolve(db.store.advances, identifier, "ERR_ADVANCE_NOT_FOUND")


def require_site(identifier):
    return _resolve(db.store.sites, identifier, "ERR_SITE_NOT_FOUND")


def require_day(identifier):
    return _resolve(db.store.days, identifier, "ERR_SERVICE_DAY_NOT_FOUND")


def require_count_entry(identifier):
    return _resolve(db.store.count_entries, identifier, "ERR_COUNT_ENTRY_NOT_FOUND")


def require_holding_log(identifier):
    return _resolve(db.store.holding_logs, identifier, "ERR_HOLDING_LOG_NOT_FOUND")


def require_visit(identifier):
    return _resolve(db.store.visits, identifier, "ERR_VISIT_NOT_FOUND")


def require_action(identifier):
    return _resolve(db.store.actions, identifier, "ERR_CORRECTIVE_ACTION_NOT_FOUND")


def require_claim(identifier):
    return _resolve(db.store.claims, identifier, "ERR_CLAIM_NOT_FOUND")


def require_line_item(identifier):
    return _resolve(db.store.line_items, identifier, "ERR_CLAIM_LINE_ITEM_NOT_FOUND")


# --------------------------------------------------------------------------
# Related-collection helpers
# --------------------------------------------------------------------------
def site_days(site_id):
    return db.ordered(
        [day for day in db.store.days.values() if day["site_id"] == site_id]
    )


def sponsor_sites(sponsor_id):
    return db.ordered(
        [site for site in db.store.sites.values() if site["sponsor_id"] == sponsor_id]
    )


def site_visits(site_id):
    return db.ordered(
        [visit for visit in db.store.visits.values() if visit["site_id"] == site_id]
    )


def site_actions(site_id):
    return db.ordered(
        [action for action in db.store.actions.values() if action["site_id"] == site_id]
    )


def visit_actions(visit_id):
    return db.ordered(
        [
            action
            for action in db.store.actions.values()
            if action["monitoring_visit_id"] == visit_id
        ]
    )


def claim_line_items(claim_id):
    return db.ordered(
        [
            line
            for line in db.store.line_items.values()
            if line["meal_claim_id"] == claim_id
        ]
    )


def site_line_items(site_id):
    return db.ordered(
        [line for line in db.store.line_items.values() if line["site_id"] == site_id]
    )


def approved_budget_for(sponsor, prefer_year=None):
    """The sponsor's live spending plan: APPROVED or AMENDMENT_PENDING."""
    candidates = db.ordered(
        [
            budget
            for budget in db.store.budgets.values()
            if budget["sponsor_id"] == sponsor["id"]
            and budget["status"] in ("APPROVED", "AMENDMENT_PENDING")
        ]
    )
    if not candidates:
        return None
    if prefer_year is not None:
        for budget in candidates:
            if budget["program_year"] == prefer_year:
                return budget
    for budget in candidates:
        if budget["program_year"] == sponsor["program_year"]:
            return budget
    return candidates[0]
