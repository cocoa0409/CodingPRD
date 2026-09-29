"""The seven-step application pricing procedure (PRD 3.6)."""

from decimal import Decimal

import clock
import db
from services import calc, derive
from util import bp, d4, dec, rhu_cents

THOUSAND = Decimal(1000)


def applicable_lines(study_id, land_use_category):
    """Step one: VALID lines of the pinned study for this land use, by code ASC."""
    rows = []
    for component in derive.components_of_study(study_id):
        category = derive.category_of_component(component)
        if category is None:
            continue
        for item in derive.items_of_component(component["id"]):
            if item["land_use_category"] != land_use_category:
                continue
            if item["schedule_status"] != "VALID":
                continue
            rows.append((item, component, category))
    rows.sort(key=lambda row: (row[2]["code"], row[2]["_seq"]))
    return rows


def price(application, program, study):
    lines = applicable_lines(study["id"], application["land_use_category"])

    # Step two: billable units, demand units and the per-line gross fee.
    assessed = []
    gross_total = 0
    for item, _component, category in lines:
        if item["unit_basis"] == "PER_DWELLING":
            billable = dec(application["dwelling_units"])
        else:
            billable = dec(application["nonres_sqft"]) / THOUSAND
        demand_units = d4(billable * dec(item["conversion_factor"]))
        line_gross = rhu_cents(dec(item["fee_per_unit_cents"] or 0) * billable)
        gross_total += line_gross
        assessed.append({
            "facility_category_id": category["id"],
            "facility_category_code": category["code"],
            "demand_units": demand_units,
            "line_gross_cents": line_gross,
            "line_credit_cents": 0,
            "line_admin_cents": 0,
            "line_net_cents": line_gross,
        })

    # Step three: raw approved credit per facility category code.
    raw_by_code = {}
    for claim in derive.claims_of_application(application["id"]):
        if claim["status"] not in derive.APPROVED_CLAIM_STATUSES:
            continue
        code = claim["facility_category_code"]
        raw_by_code[code] = raw_by_code.get(code, 0) + (claim["approved_cents"] or 0)

    total_raw = sum(raw_by_code.get(line["facility_category_code"], 0) for line in assessed)

    # Step four: the aggregate cap taken on the gross fee.
    cap = rhu_cents(dec(gross_total) * bp(program["credit_cap_bp"]))
    credit_applied = total_raw if total_raw < cap else cap

    # Step five: the waterfall in facility category code ascending order.
    remaining = credit_applied
    for line in assessed:
        line_raw = raw_by_code.get(line["facility_category_code"], 0)
        assign = min(line_raw, remaining, line["line_gross_cents"])
        if assign < 0:
            assign = 0
        line["line_credit_cents"] = assign
        remaining -= assign

    # Step six: the per-line administrative charge, rounded once per line.
    admin_total = 0
    for line in assessed:
        net_before_admin = line["line_gross_cents"] - line["line_credit_cents"]
        line_admin = rhu_cents(dec(net_before_admin) * bp(program["admin_charge_bp"]))
        line["line_admin_cents"] = line_admin
        line["line_net_cents"] = net_before_admin + line_admin
        admin_total += line_admin

    # Step seven: the application totals.
    penalty = application.get("default_penalty_cents") or 0
    net_due = gross_total - credit_applied + admin_total + penalty
    return {
        "assessed_lines": assessed,
        "gross_assessed_cents": gross_total,
        "credit_applied_cents": credit_applied,
        "admin_charge_cents": admin_total,
        "net_due_cents": net_due,
    }


def _touched_category_ids(application, result):
    previous = {line["facility_category_id"] for line in application.get("assessed_lines") or []}
    fresh = {line["facility_category_id"] for line in result["assessed_lines"]}
    return previous | fresh


def run_assessment(application, program, study):
    """Officer-initiated assessment: prices, pins, and moves both dimensions."""
    result = price(application, program, study)
    touched = _touched_category_ids(application, result)
    first_assessment = application["assessment_status"] == "UNASSESSED"

    application.update(result)
    application["pinned_fee_study_id"] = study["id"]
    application["pinned_fee_study_version"] = study["version"]
    application["reassessment_required"] = False
    if first_assessment:
        application["assessment_status"] = "ASSESSED"
        application["assessed_at"] = clock.now()
        if application["collection_trigger"] == "PERMIT" and application["collection_status"] == "NOT_DUE":
            application["collection_status"] = "DUE"
    else:
        application["assessment_status"] = "REASSESSED"
        application["reassessed_at"] = clock.now()
    db.touch(application)

    derive.sync_categories(touched, force=True)
    return application


def system_reassessment(application, program):
    """Re-pricing triggered by an approved credit claim (PRD 3.7)."""
    study = db.fee_studies.get(application.get("pinned_fee_study_id"))
    if study is None:
        return application
    result = price(application, program, study)
    touched = _touched_category_ids(application, result)
    application.update(result)
    application["assessment_status"] = "REASSESSED"
    application["reassessed_at"] = clock.now()
    db.touch(application)
    derive.sync_categories(touched)
    return application
