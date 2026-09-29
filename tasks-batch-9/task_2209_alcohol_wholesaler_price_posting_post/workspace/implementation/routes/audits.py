"""Compliance audits, findings and penalty assessment (PRD section 3.9)."""

from flask import Blueprint

import calc
import services
from auth import ALL_ROLES, ROLE_COMPLIANCE_OFFICER, authenticate
from envelope import object_response
from errors import raise_err
from serialize import out
from store import bump, db, dt_of, month_of, new_record, sorted_records
from validators import Field, collection_response, must_find, validate_body

bp = Blueprint("audits", __name__)

AUDIT_STATUSES = ("OPEN", "COLLECTED", "ASSESSED", "CLOSED", "VOID")
FINDING_TYPES = (
    "OFF_POSTED_UNDERCHARGE",
    "OFF_POSTED_OVERCHARGE",
    "EXCESS_PROMOTIONAL_ALLOWANCE",
    "EXCESS_DEPLETION_ALLOWANCE",
    "UNPOSTED_BRAND",
)


def _flagged_invoices_for_period(wholesaler_id, period_month):
    matched = []
    for invoice in db.retailer_invoices.values():
        if invoice["wholesaler_id"] != wholesaler_id:
            continue
        if invoice["validation_status"] != "FLAGGED":
            continue
        if month_of(invoice["invoice_date"]) != period_month:
            continue
        matched.append(invoice)
    return sorted_records(matched)


def _classify(line, resolved):
    if resolved is None:
        return "UNPOSTED_BRAND"
    if line["variance_cents"] > 0:
        return "OFF_POSTED_UNDERCHARGE"
    if line["variance_cents"] < 0:
        return "OFF_POSTED_OVERCHARGE"
    if line["excess_promotional_cents"] > 0:
        return "EXCESS_PROMOTIONAL_ALLOWANCE"
    return "EXCESS_DEPLETION_ALLOWANCE"


# ---------------------------------------------------------------------------
# compliance audits
# ---------------------------------------------------------------------------
@bp.post("/compliance-audits")
def create_compliance_audit():
    authenticate([ROLE_COMPLIANCE_OFFICER])
    values = validate_body(
        [
            Field("wholesaler_id", "string"),
            Field("state_program_id", "string"),
            Field("audit_period_month", "month"),
            Field("expected_wholesaler_version", "int"),
        ]
    )
    wholesaler = must_find("wholesaler", values["wholesaler_id"])
    must_find("state_program", values["state_program_id"])

    # Priority 7 -- optimistic concurrency on the audited wholesaler.
    if values["expected_wholesaler_version"] != wholesaler["version"]:
        raise_err("ERR_STALE_WHOLESALER_VERSION")

    # Priority 14 -- one live audit per wholesaler per period month.
    for existing in db.compliance_audits.values():
        if existing["wholesaler_id"] != wholesaler["id"]:
            continue
        if existing["audit_period_month"] != values["audit_period_month"]:
            continue
        if existing["status"] == "VOID":
            continue
        raise_err("ERR_DUPLICATE_AUDIT_PERIOD")

    record = new_record(
        {
            "wholesaler_id": wholesaler["id"],
            "state_program_id": values["state_program_id"],
            "audit_period_month": values["audit_period_month"],
            "status": "OPEN",
            "finding_count": 0,
            "total_variance_cents": 0,
            "base_penalty_cents": 0,
            "tier_multiplier": 1.0,
            "penalty_assessed_cents": 0,
            "prior_violation_count": 0,
            "void_reason": None,
        }
    )
    db.compliance_audits[record["id"]] = record

    wholesaler["open_audit_count"] += 1
    bump(wholesaler)
    return object_response(out(record), 201)


@bp.post("/compliance-audits/<record_id>/collect")
def collect_compliance_audit(record_id):
    authenticate([ROLE_COMPLIANCE_OFFICER])
    audit = must_find("compliance_audit", record_id)
    if audit["status"] != "OPEN":
        raise_err("ERR_INVALID_STATE")

    invoices = _flagged_invoices_for_period(
        audit["wholesaler_id"], audit["audit_period_month"]
    )

    # Priority 22 -- an audit cannot be collected when there is nothing to find.
    if not invoices:
        raise_err("ERR_NO_FLAGGED_INVOICES")

    program = db.state_programs[audit["state_program_id"]]
    rate = program["off_posted_penalty_rate_pct"]

    for invoice in invoices:
        invoice["audit_status"] = "UNDER_AUDIT"
        invoice["audit_id"] = audit["id"]
        bump(invoice)

    finding_count = 0
    total_variance = 0
    base_penalty = 0
    for invoice in invoices:
        invoice_date = dt_of(invoice["invoice_date"])
        for line in services.sorted_lines(invoice["id"]):
            if not line["is_off_posted"]:
                continue
            item = db.price_schedule_items[line["item_id"]]
            resolved = calc.resolve_posted_item(item, invoice_date)
            variance = line["finding_variance_cents"]
            component = calc.penalty_component(variance, rate)
            finding = new_record(
                {
                    "audit_id": audit["id"],
                    "invoice_line_id": line["id"],
                    "finding_type": _classify(line, resolved),
                    "variance_cents": variance,
                    "penalty_component_cents": component,
                },
                versioned=False,
            )
            db.audit_findings[finding["id"]] = finding
            finding_count += 1
            total_variance += variance
            base_penalty += component

    audit["status"] = "COLLECTED"
    audit["finding_count"] = finding_count
    audit["total_variance_cents"] = total_variance
    audit["base_penalty_cents"] = base_penalty
    bump(audit)
    return object_response(out(audit))


@bp.post("/compliance-audits/<record_id>/assess")
def assess_compliance_audit(record_id):
    authenticate([ROLE_COMPLIANCE_OFFICER])
    audit = must_find("compliance_audit", record_id)
    if audit["status"] != "COLLECTED":
        raise_err("ERR_INVALID_STATE")

    wholesaler = db.wholesalers[audit["wholesaler_id"]]

    # The prior count is captured before this audit's findings are added to it.
    prior = wholesaler["off_posted_violation_count"]
    multiplier = calc.tier_multiplier_for(prior)
    assessed = calc.escalated_penalty(audit["base_penalty_cents"], multiplier)

    audit["status"] = "ASSESSED"
    audit["prior_violation_count"] = prior
    audit["tier_multiplier"] = float(multiplier)
    audit["penalty_assessed_cents"] = assessed
    bump(audit)

    wholesaler["assessed_penalty_cents"] += assessed
    wholesaler["off_posted_violation_count"] += audit["finding_count"]
    services.recompute_exposure(wholesaler)
    bump(wholesaler)

    for invoice in sorted_records(services.invoices_of_audit(audit["id"])):
        if invoice["audit_status"] != "UNDER_AUDIT":
            continue
        invoice["audit_status"] = "ASSESSED"
        bump(invoice)

    return object_response(out(audit))


@bp.post("/compliance-audits/<record_id>/close")
def close_compliance_audit(record_id):
    authenticate([ROLE_COMPLIANCE_OFFICER])
    audit = must_find("compliance_audit", record_id)
    if audit["status"] != "ASSESSED":
        raise_err("ERR_INVALID_STATE")
    audit["status"] = "CLOSED"
    bump(audit)
    return object_response(out(audit))


@bp.post("/compliance-audits/<record_id>/void")
def void_compliance_audit(record_id):
    authenticate([ROLE_COMPLIANCE_OFFICER])
    audit = must_find("compliance_audit", record_id)
    values = validate_body([Field("void_reason", "string")])
    if audit["status"] != "ASSESSED":
        raise_err("ERR_INVALID_STATE")

    collected = sorted_records(services.invoices_of_audit(audit["id"]))

    audit["status"] = "VOID"
    audit["void_reason"] = values["void_reason"]
    bump(audit)

    wholesaler = db.wholesalers[audit["wholesaler_id"]]
    wholesaler["assessed_penalty_cents"] -= audit["penalty_assessed_cents"]
    wholesaler["off_posted_violation_count"] -= audit["finding_count"]
    services.recompute_exposure(wholesaler)
    bump(wholesaler)

    for invoice in collected:
        invoice["audit_status"] = "NOT_AUDITED"
        invoice["audit_id"] = None
        bump(invoice)

    return object_response(out(audit))


@bp.get("/compliance-audits/<record_id>")
def get_compliance_audit(record_id):
    authenticate(ALL_ROLES)
    return object_response(out(must_find("compliance_audit", record_id)))


@bp.get("/compliance-audits")
def list_compliance_audits():
    authenticate(ALL_ROLES)
    return collection_response(
        list(db.compliance_audits.values()),
        {
            "wholesaler_id": None,
            "state_program_id": None,
            "audit_period_month": None,
            "status": AUDIT_STATUSES,
        },
        out,
    )


# ---------------------------------------------------------------------------
# audit findings
# ---------------------------------------------------------------------------
@bp.get("/audit-findings/<record_id>")
def get_audit_finding(record_id):
    authenticate(ALL_ROLES)
    return object_response(out(must_find("audit_finding", record_id)))


@bp.get("/audit-findings")
def list_audit_findings():
    authenticate(ALL_ROLES)
    return collection_response(
        list(db.audit_findings.values()),
        {"audit_id": None, "invoice_line_id": None, "finding_type": FINDING_TYPES},
        out,
    )
