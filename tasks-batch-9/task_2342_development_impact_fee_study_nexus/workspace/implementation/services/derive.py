"""Derived field reconciliation (PRD 2.11) and the small graph traversals."""

from decimal import Decimal

import clock
import db
from util import add_days, d4, dec

APPROVED_CLAIM_STATUSES = ("APPROVED_FULL", "APPROVED_PARTIAL")
ELIGIBLE_ENTRY_STATUSES = ("OPEN", "PARTIALLY_EXPENDED")
UNEXPENDED_ENTRY_STATUSES = ("OPEN", "PARTIALLY_EXPENDED", "REFUND_DUE")


# --------------------------------------------------------------------------- #
# Traversals
# --------------------------------------------------------------------------- #


def effective_study(program_id):
    for study in db.ordered(db.fee_studies):
        if study["fee_program_id"] == program_id and study["status"] == "EFFECTIVE":
            return study
    return None


def program_of_study(study):
    return db.fee_programs.get(study["fee_program_id"])


def study_of_component(component):
    return db.fee_studies.get(component["fee_study_id"])


def category_of_component(component):
    return db.facility_categories.get(component["facility_category_id"])


def program_of_component(component):
    study = study_of_component(component)
    return program_of_study(study) if study else None


def component_of_item(item):
    return db.nexus_components.get(item["nexus_component_id"])


def program_of_category(category):
    return db.fee_programs.get(category["fee_program_id"])


def program_of_application(application):
    return db.fee_programs.get(application["fee_program_id"])


def components_of_study(study_id):
    return [c for c in db.ordered(db.nexus_components) if c["fee_study_id"] == study_id]


def items_of_component(component_id):
    return [i for i in db.ordered(db.fee_schedule_items)
            if i["nexus_component_id"] == component_id]


def items_of_study(study_id):
    items = []
    for component in components_of_study(study_id):
        items.extend(items_of_component(component["id"]))
    return items


def filings_of_study(study_id):
    return [f for f in db.ordered(db.protest_filings) if f["fee_study_id"] == study_id]


def claims_of_application(application_id):
    return [c for c in db.ordered(db.credit_claims)
            if c["development_application_id"] == application_id]


def agreements_of_application(application_id):
    return [a for a in db.ordered(db.deferral_agreements)
            if a["development_application_id"] == application_id]


def entries_of_category(category_id):
    return [e for e in db.ordered(db.fund_ledger_entries)
            if e["facility_category_id"] == category_id]


def entries_of_application(application_id):
    return [e for e in db.ordered(db.fund_ledger_entries)
            if e.get("development_application_id") == application_id]


def categories_of_program(program_id):
    rows = [c for c in db.facility_categories.values() if c["fee_program_id"] == program_id]
    return sorted(rows, key=lambda c: (c["code"], c["_seq"]))


def applications_of_program(program_id):
    return [a for a in db.ordered(db.development_applications)
            if a["fee_program_id"] == program_id]


def category_by_code(program_id, code):
    for category in db.ordered(db.facility_categories):
        if category["fee_program_id"] == program_id and category["code"] == code:
            return category
    return None


def fifo_key(entry):
    return (entry["vintage_at"], entry["created_at"], entry["_seq"])


def eligible_collections(category_id):
    rows = [e for e in db.fund_ledger_entries.values()
            if e["facility_category_id"] == category_id
            and e["kind"] == "COLLECTION"
            and e["entry_status"] in ELIGIBLE_ENTRY_STATUSES]
    return sorted(rows, key=fifo_key)


# --------------------------------------------------------------------------- #
# Study tally
# --------------------------------------------------------------------------- #


def sync_study_tally(study):
    weight = 0
    count = 0
    for filing in filings_of_study(study["id"]):
        if filing["status"] == "RECORDED":
            weight += filing["weight_bp"]
            count += 1
    study["protest_weight_bp"] = weight
    study["protest_count"] = count


# --------------------------------------------------------------------------- #
# Application derived money
# --------------------------------------------------------------------------- #


def paid_cents(application_id):
    total = 0
    for entry in db.fund_ledger_entries.values():
        if entry.get("development_application_id") != application_id:
            continue
        if entry["kind"] == "COLLECTION":
            total += entry["amount_cents"]
        elif entry["kind"] == "REFUND":
            total -= entry["amount_cents"]
    return total


def sync_application_paid(application, force=False):
    value = paid_cents(application["id"])
    changed = application.get("paid_cents") != value
    application["paid_cents"] = value
    if changed or force:
        db.touch(application)
    return changed


# --------------------------------------------------------------------------- #
# Facility category derived fields and fund posture
# --------------------------------------------------------------------------- #


def _fund_balance(category_id):
    total = 0
    for entry in db.fund_ledger_entries.values():
        if entry["facility_category_id"] != category_id:
            continue
        if entry["kind"] == "COLLECTION":
            total += entry["amount_cents"]
        else:
            total -= entry["amount_cents"]
    return total


def _refund_due(category_id):
    total = 0
    for entry in db.fund_ledger_entries.values():
        if entry["facility_category_id"] == category_id and entry["entry_status"] == "REFUND_DUE":
            total += entry.get("unexpended_cents") or 0
    return total


def _oldest_vintage(category_id):
    oldest = None
    for entry in db.fund_ledger_entries.values():
        if (entry["facility_category_id"] == category_id
                and entry["kind"] == "COLLECTION"
                and entry["entry_status"] in UNEXPENDED_ENTRY_STATUSES):
            if oldest is None or entry["vintage_at"] < oldest:
                oldest = entry["vintage_at"]
    return oldest


def _committed_demand_units(category_id):
    total = Decimal(0)
    for application in db.development_applications.values():
        if application["assessment_status"] not in ("ASSESSED", "REASSESSED"):
            continue
        for line in application.get("assessed_lines") or []:
            if line["facility_category_id"] == category_id:
                total += dec(line["demand_units"])
    return d4(total)


def _deferred_receivable(category_id):
    total = 0
    for application in db.development_applications.values():
        if application["collection_status"] not in ("DEFERRED", "DELINQUENT"):
            continue
        for line in application.get("assessed_lines") or []:
            if line["facility_category_id"] == category_id:
                total += line["line_net_cents"]
    return total


def compute_posture(category):
    if (category.get("refund_due_cents") or 0) > 0:
        return "REFUND_DUE"
    program = program_of_category(category)
    window_days = program["at_risk_window_days"] if program else 0
    horizon = add_days(clock.now(), window_days)
    for entry in db.fund_ledger_entries.values():
        if (entry["facility_category_id"] == category["id"]
                and entry["kind"] == "COLLECTION"
                and entry["entry_status"] in ELIGIBLE_ENTRY_STATUSES
                and entry.get("deadline_at") is not None
                and entry["deadline_at"] <= horizon):
            return "AT_RISK"
    return "COMPLIANT"


def sync_category(category, posture=False, force=False):
    """Recompute a category's derived fields; bump version when changed or forced."""
    before = (
        category.get("fund_balance_cents"),
        category.get("refund_due_cents"),
        category.get("oldest_unexpended_vintage_at"),
        category.get("committed_demand_units"),
        category.get("deferred_receivable_cents"),
        category.get("fund_posture"),
    )
    category["fund_balance_cents"] = _fund_balance(category["id"])
    category["refund_due_cents"] = _refund_due(category["id"])
    category["oldest_unexpended_vintage_at"] = _oldest_vintage(category["id"])
    category["committed_demand_units"] = _committed_demand_units(category["id"])
    category["deferred_receivable_cents"] = _deferred_receivable(category["id"])
    if posture:
        category["fund_posture"] = compute_posture(category)
    after = (
        category["fund_balance_cents"],
        category["refund_due_cents"],
        category["oldest_unexpended_vintage_at"],
        category["committed_demand_units"],
        category["deferred_receivable_cents"],
        category["fund_posture"],
    )
    changed = before != after
    if changed or force:
        db.touch(category)
    return changed


def sync_categories(category_ids, posture=False, force=False):
    for category_id in category_ids:
        category = db.facility_categories.get(category_id)
        if category is not None:
            sync_category(category, posture=posture, force=force)
