"""Support-statement reconciliation, both variants (PRD 3.5)."""

from decimal import Decimal

import db
import util
from services import derive
from services import enums as E

APPOINTMENT_TYPES_COUNTED = ("FOREIGN_APPOINTMENT", "TALENT_PROGRAM",
                             "VISITING_SCHOLAR")
SUPPORT_TYPES_COUNTED = ("OUTSIDE_SUPPORT", "IN_KIND_RESOURCE")


def _newest_certified(investigator_id):
    certified = [d for d in derive.investigator_disclosures(investigator_id)
                 if d["review_status"] == "CERTIFIED"]
    if not certified:
        return None

    def sort_key(disclosure):
        submitted = util.parse_dt(disclosure.get("submitted_at"))
        return (
            submitted.timestamp() if submitted else float("-inf"),
            disclosure["created_at"],
            disclosure["_seq"],
        )

    certified.sort(key=sort_key)
    return certified[-1]


def _source_items(statement, variant):
    investigator_id = statement["investigator_id"]
    if variant == "STRICT_AGENCY":
        disclosure = _newest_certified(investigator_id)
        sources = [disclosure] if disclosure is not None else []
    else:
        sources = [d for d in derive.investigator_disclosures(investigator_id)
                   if d["review_status"] not in ("DRAFT", "REJECTED")]
    rows = []
    for disclosure in sources:
        rows.extend(derive.disclosure_items(disclosure["id"]))
    return [i for i in rows if i["status"] != "WITHDRAWN"]


def run(statement, variant):
    """Compute and store the five reconciliation fields; returns the verdict."""
    investigator_id = statement["investigator_id"]
    counted_types = ("FOREIGN_APPOINTMENT",) if variant == "STRICT_AGENCY" \
        else APPOINTMENT_TYPES_COUNTED

    rows = derive.active_personnel(investigator_id)
    if variant == "STRICT_AGENCY":
        filtered = []
        for row in rows:
            project = db.projects.get(row["project_id"])
            if project is not None and \
                    project["agency_code"] == statement["agency_code"]:
                filtered.append(row)
        rows = filtered

    personnel_months = Decimal("0")
    for row in rows:
        personnel_months += util.dec(row["committed_person_months"])

    items = _source_items(statement, variant)
    counted_items = [i for i in items if i["item_type"] in counted_types]

    if variant == "STRICT_AGENCY":
        outside = Decimal("0.00")
    else:
        hours = Decimal("0")
        for item in counted_items:
            hours += util.dec(item.get("annual_effort_hours") or 0)
        outside = util.round2(hours / E.OUTSIDE_HOURS_PER_PERSON_MONTH)

    institutional = util.round2(personnel_months + outside)
    declared = util.dec(statement["declared_person_months"])
    variance = util.round2(institutional - declared)

    appointment_bucket = max(
        0,
        sum(1 for i in counted_items
            if i["item_type"] in APPOINTMENT_TYPES_COUNTED)
        - int(statement["declared_appointment_count"]))
    if variant == "STRICT_AGENCY":
        support_bucket = 0
    else:
        actual_support = sum(1 for i in items
                             if i["item_type"] in SUPPORT_TYPES_COUNTED)
        support_bucket = max(
            0, actual_support - int(statement["declared_support_count"]))
    omission_count = appointment_bucket + support_bucket

    if omission_count >= 1 or abs(variance) >= E.MATERIAL_VARIANCE_PM:
        verdict = "MATERIAL_DISCREPANCY"
    elif abs(variance) >= E.MINOR_VARIANCE_PM:
        verdict = "MINOR_VARIANCE"
    else:
        verdict = "CONSISTENT"

    statement["applied_variant"] = variant
    statement["institutional_person_months"] = institutional
    statement["variance_person_months"] = variance
    statement["omission_count"] = omission_count
    statement["verdict"] = verdict
    statement["status"] = "RECONCILED" if verdict == "CONSISTENT" \
        else "INCONSISTENT"
    return verdict
