"""Shared domain helpers: entity factory, calendar math, rule applicability,
report totals recomputation, and the cross-entity cascades of PRD section 2.8.
"""

import uuid
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

import clock
import db
import errors
from errors import raise_error

PROPERTY_TYPES = {"CHECKING", "SAVINGS", "BROKERAGE_SHARES", "UNCASHED_CHECK", "INSURANCE_PROCEEDS"}
CONTACT_TYPES = {
    "WITHDRAWAL", "DEPOSIT", "LOGIN_VERIFIED",
    "WRITTEN_CORRESPONDENCE", "PHONE_VERIFIED", "IN_PERSON",
}
QUALIFYING_CONTACT_TYPES = {"WITHDRAWAL", "DEPOSIT", "WRITTEN_CORRESPONDENCE", "IN_PERSON"}
ARTIFACT_TYPES = {"LETTER_COPY", "REPORT_FILE", "CLAIM_EVIDENCE", "REMITTANCE_RECEIPT"}
RELATED_ENTITY_TYPES = {"DueDiligenceLetter", "HolderReport", "OwnerClaim", "Remittance"}

RETENTION_YEARS = {
    "LETTER_COPY": 5,
    "REPORT_FILE": 10,
    "CLAIM_EVIDENCE": 7,
    "REMITTANCE_RECEIPT": 10,
}

CLAIM_FEE_BP = 150
CLAIM_FEE_FREE_CAP_CENTS = 100000
BP_DENOMINATOR = 3_650_000


def new_entity(fields):
    """Attach the common system-managed fields of PRD section 2.4."""
    stamp = clock.now_iso()
    entity = {"id": str(uuid.uuid4()), "created_at": stamp, "updated_at": stamp, "version": 1}
    entity.update(fields)
    return entity


def touch(entity):
    """Refresh updated_at and bump version (PRD 2.8: cascades count too)."""
    entity["updated_at"] = clock.now_iso()
    entity["version"] += 1


# ---------------------------------------------------------------------------
# Calendar arithmetic (PRD 2.5: anniversaries land on same month-day;
# date arithmetic in whole days)
# ---------------------------------------------------------------------------

def add_years(d, years):
    """Anniversary: same month-day N years later (Feb 29 -> Feb 28 fallback)."""
    try:
        return d.replace(year=d.year + years)
    except ValueError:
        return d.replace(year=d.year + years, day=28)


def month_day_to_date(year, month_day):
    month = int(month_day[:2])
    day = int(month_day[3:])
    try:
        return date(year, month, day)
    except ValueError:
        # e.g. 02-29 on a non-leap year: clamp to the last valid day.
        return date(year, month, day - 1)


def rule_cutoff_date(rule, year):
    return month_day_to_date(year, rule["report_cutoff_month_day"])


def rule_due_date(rule, year):
    return month_day_to_date(year, rule["report_due_month_day"])


# ---------------------------------------------------------------------------
# Dormancy rule applicability (PRD 3.2)
# ---------------------------------------------------------------------------

def find_applicable_rule(state_code, property_type, contact_date):
    """Rule whose half-open window contains contact_date; None when absent."""
    for rule in db.dormancy_rules.values():
        if rule["state_code"] != state_code or rule["property_type"] != property_type:
            continue
        if rule["effective_from"] <= contact_date and (
            rule["effective_to"] is None or contact_date < rule["effective_to"]
        ):
            return rule
    return None


def check_rule_window_overlap(state_code, property_type, effective_from, effective_to, exclude_id=None):
    """ERR_DORMANCY_RULE_OVERLAP when half-open windows intersect; adjacency OK."""
    for rule in db.dormancy_rules.values():
        if exclude_id is not None and rule["id"] == exclude_id:
            continue
        if rule["state_code"] != state_code or rule["property_type"] != property_type:
            continue
        other_from = rule["effective_from"]
        other_to = rule["effective_to"]
        # Half-open overlap: new_from < other_to (or other open) and
        # other_from < new_to (or new open).
        if effective_to is not None and other_from >= effective_to:
            continue
        if other_to is not None and effective_from >= other_to:
            continue
        raise_error(
            errors.ERR_DORMANCY_RULE_OVERLAP,
            "Effective window overlaps an existing rule for this state and property type",
        )


# ---------------------------------------------------------------------------
# Report window derivation (PRD 3.2 / scaffold applicable_report_window)
# ---------------------------------------------------------------------------

def first_eligible_cycle_year(rule, dormancy_date):
    """Smallest year whose cutoff falls on or after dormancy_date."""
    year = dormancy_date.year
    while rule_cutoff_date(rule, year) < dormancy_date:
        year += 1
    return year


def applicable_due_date(rule, dormancy_date, current_date):
    """First eligible cycle due date, rolled forward while it is in the past."""
    year = first_eligible_cycle_year(rule, dormancy_date)
    while rule_due_date(rule, year) < current_date:
        year += 1
    return rule_due_date(rule, year)


def missed_due_date_no_rolldorward(rule, dormancy_date):
    """First eligible cycle's due date without roll-forward (audit exposure)."""
    return rule_due_date(rule, first_eligible_cycle_year(rule, dormancy_date))


# ---------------------------------------------------------------------------
# Rounding helpers (PRD 2.6)
# ---------------------------------------------------------------------------

def round_half_up_cents(numerator, denominator):
    """round_half_up(numerator / denominator) to whole cents; integer inputs."""
    value = (Decimal(numerator) / Decimal(denominator)).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP
    )
    return int(value)


def floor_pct(pct, base):
    """floor(pct * base / 100) — penalty cap convention."""
    return (pct * base) // 100


# ---------------------------------------------------------------------------
# Report totals (PRD 3.4 report_totals: eager recompute + version bump)
# ---------------------------------------------------------------------------

def included_lines(report_id):
    return [
        line for line in db.line_items.values()
        if line["report_id"] == report_id and line["status"] in ("INCLUDED", "FINAL")
    ]


def recompute_report_totals(report, bump=True):
    lines = included_lines(report["id"])
    report["total_provisional_cents"] = sum(l["provisional_value_cents"] for l in lines)
    report["total_final_cents"] = sum(
        l["final_value_cents"] if l["status"] == "FINAL" else l["provisional_value_cents"]
        for l in lines
    )
    report["line_count"] = len(lines)
    if bump:
        touch(report)


def compute_report_totals(report_id):
    """Pure computation (no mutation) — used for OCC-free snapshot needs."""
    lines = included_lines(report_id)
    return {
        "total_provisional_cents": sum(l["provisional_value_cents"] for l in lines),
        "total_final_cents": sum(
            l["final_value_cents"] if l["status"] == "FINAL" else l["provisional_value_cents"]
            for l in lines
        ),
        "line_count": len(lines),
    }


# ---------------------------------------------------------------------------
# Securities valuation (scaffold securities_valuation)
# ---------------------------------------------------------------------------

def securities_provisional_value(detail):
    return detail["last_close_price_cents"] * detail["shares_quantity"] + detail["accrued_dividends_cents"]


# ---------------------------------------------------------------------------
# Cascades
# ---------------------------------------------------------------------------

def remove_property_lines_from_draft_reports(prop, touched_reports):
    """Reactivation cascade hop 2/3: INCLUDED lines in DRAFT reports -> REMOVED;
    each affected DRAFT report recomputes totals with a version increment."""
    for line in db.line_items.values():
        if line["property_id"] != prop["id"] or line["status"] != "INCLUDED":
            continue
        report = db.reports.get(line["report_id"])
        if report is None or report["status"] != "DRAFT":
            continue
        line["status"] = "REMOVED"
        touch(line)
        touched_reports[report["id"]] = report


def property_has_line_in_submitted_or_accepted(prop_id):
    for line in db.line_items.values():
        if line["property_id"] != prop_id or line["status"] not in ("INCLUDED", "FINAL"):
            continue
        report = db.reports.get(line["report_id"])
        if report is not None and report["status"] in ("SUBMITTED", "ACCEPTED"):
            return True
    return False


def reactivate_property(prop, evidence_event):
    """Shared reactivation effects (PRD 3.3): status -> ACTIVE, letters voided,
    draft-report lines removed with totals recompute, dates advanced/cleared."""
    prop["status"] = "ACTIVE"
    if evidence_event["contact_date"] > prop["last_contact_date"]:
        prop["last_contact_date"] = evidence_event["contact_date"]
    prop["dormancy_date"] = None
    touch(prop)

    for letter in db.letters.values():
        if letter["property_id"] == prop["id"] and letter["status"] in ("SENT", "DELIVERED"):
            letter["status"] = "VOIDED"
            touch(letter)

    touched_reports = {}
    remove_property_lines_from_draft_reports(prop, touched_reports)
    for report in touched_reports.values():
        recompute_report_totals(report, bump=True)


def validate_evidence_event(prop, event_id, min_contact_date=None):
    """Existence -> belongs-to-property -> qualifies (+ optional date floor)."""
    event = db.contact_events.get(event_id)
    if event is None:
        raise_error(errors.ERR_CONTACT_EVENT_NOT_FOUND, "Contact event does not exist")
    if event["property_id"] != prop["id"]:
        raise_error(
            errors.ERR_CONTACT_EVENT_PROPERTY_MISMATCH,
            "Contact event belongs to a different property",
        )
    if not event["qualifies_for_reactivation"]:
        raise_error(
            errors.ERR_CONTACT_NOT_QUALIFYING,
            "Contact event type does not qualify for reactivation",
        )
    if min_contact_date is not None and event["contact_date"] < min_contact_date:
        raise_error(
            errors.ERR_CONTACT_NOT_QUALIFYING,
            "Contact event predates the letter's sent_date",
        )
    return event


def terminal_letter_exists(prop_id):
    """EXPIRED or UNDELIVERABLE letter on file for the property (PRD 3.4)."""
    for letter in db.letters.values():
        if letter["property_id"] == prop_id and letter["status"] in ("EXPIRED", "UNDELIVERABLE"):
            return True
    return False


def get_owner_or_404(owner_id):
    owner = db.owners.get(owner_id)
    if owner is None:
        raise_error(errors.ERR_OWNER_NOT_FOUND, "Owner does not exist")
    return owner


def get_property_or_404(prop_id):
    prop = db.properties.get(prop_id)
    if prop is None:
        raise_error(errors.ERR_PROPERTY_NOT_FOUND, "Property does not exist")
    return prop


def get_report_or_404(report_id):
    report = db.reports.get(report_id)
    if report is None:
        raise_error(errors.ERR_REPORT_NOT_FOUND, "Holder report does not exist")
    return report


def get_letter_or_404(letter_id):
    letter = db.letters.get(letter_id)
    if letter is None:
        raise_error(errors.ERR_LETTER_NOT_FOUND, "Due-diligence letter does not exist")
    return letter


def get_order_or_404(order_id):
    order = db.liquidation_orders.get(order_id)
    if order is None:
        raise_error(errors.ERR_LIQUIDATION_ORDER_NOT_FOUND, "Liquidation order does not exist")
    return order


def get_remittance_or_404(remittance_id):
    rem = db.remittances.get(remittance_id)
    if rem is None:
        raise_error(errors.ERR_REMITTANCE_NOT_FOUND, "Remittance does not exist")
    return rem


def get_claim_or_404(claim_id):
    claim = db.claims.get(claim_id)
    if claim is None:
        raise_error(errors.ERR_CLAIM_NOT_FOUND, "Owner claim does not exist")
    return claim


def get_assessment_or_404(assessment_id):
    pa = db.penalty_assessments.get(assessment_id)
    if pa is None:
        raise_error(errors.ERR_PENALTY_ASSESSMENT_NOT_FOUND, "Penalty assessment does not exist")
    return pa


def get_audit_or_404(audit_id):
    audit = db.audit_cases.get(audit_id)
    if audit is None:
        raise_error(errors.ERR_AUDIT_CASE_NOT_FOUND, "Audit case does not exist")
    return audit


def get_document_or_404(doc_id):
    doc = db.document_records.get(doc_id)
    if doc is None:
        raise_error(errors.ERR_DOCUMENT_RECORD_NOT_FOUND, "Document record does not exist")
    return doc


def check_claimant_owner_scope(ctx, owner_id):
    """Layer 5: a Claimant may only touch resources whose owner == X-User-ID."""
    if ctx.role == "Claimant" and ctx.user_id != owner_id:
        raise_error(
            errors.ERR_OWNERSHIP_SCOPE_VIOLATION,
            "Claimant may only access resources they own",
        )


def recoverable_base_cents(prop):
    """The claim recoverable base: remitted line value (CASH) or settled
    liquidation net proceeds (SECURITIES). None when not determinable."""
    if prop["property_type"] == "BROKERAGE_SHARES":
        for order in db.liquidation_orders.values():
            if order["property_id"] == prop["id"] and order["status"] == "SETTLED":
                return order["net_proceeds_cents"]
        return None
    # CASH: final_value of the property's line in a report whose remittance
    # confirmed (the line that carried it to REMITTED/ESCHEATED).
    best = None
    for line in db.line_items.values():
        if line["property_id"] != prop["id"] or line["status"] != "FINAL":
            continue
        report = db.reports.get(line["report_id"])
        if report is None:
            continue
        if report["status"] in ("ACCEPTED", "SUPERSEDED") and line["final_value_cents"] is not None:
            best = line["final_value_cents"]
    return best


def confirmed_remittance_for_property(prop_id):
    """The CONFIRMED remittance of the report carrying this property (for
    claim days_held). Returns the most recently confirmed match."""
    found = None
    for line in db.line_items.values():
        if line["property_id"] != prop_id or line["status"] not in ("INCLUDED", "FINAL"):
            continue
        for rem in db.remittances.values():
            if rem["report_id"] == line["report_id"] and rem["status"] == "CONFIRMED":
                if found is None or rem["confirmed_date"] >= found["confirmed_date"]:
                    found = rem
    return found
