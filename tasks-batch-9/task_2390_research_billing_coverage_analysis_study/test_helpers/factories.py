"""Payload factories — one per write endpoint, input fields only.

Every factory accepts ``**overrides``; passing ``field=None`` for an optional
field removes it from the payload so that omission itself can be tested.
"""

_SENTINEL_REMOVE = "__REMOVE__"


def _finish(payload: dict, overrides: dict) -> dict:
    payload.update(overrides)
    return {k: v for k, v in payload.items() if v != _SENTINEL_REMOVE}


# --------------------------------------------------------------------------
# Studies
# --------------------------------------------------------------------------


def create_study_payload(**overrides) -> dict:
    """Register a protocol in the research billing office."""
    payload = {
        "protocol_number": "AMC-2390-BASE",
        "title": "A Phase II Study of Investigational Therapy",
        "sponsor_name": "Northgate Therapeutics",
        "funding_source": "INDUSTRY_SPONSORED",
        "ind_ide_status": "IND_HELD",
        "therapeutic_intent": True,
    }
    return _finish(payload, overrides)


def qct_determination_payload(**overrides) -> dict:
    """Record or re-record the Medicare qualifying-clinical-trial determination."""
    payload = {"basis": "DEEMED_IND_IDE"}
    return _finish(payload, overrides)


def budget_build_payload(source_analysis_id, expected_study_version, **overrides) -> dict:
    """Build the sponsor budget from an approved coverage analysis."""
    payload = {
        "source_analysis_id": source_analysis_id,
        "basis": "COVERAGE_DRIVEN",
        "indirect_rate_pct": 20.0,
        "expected_study_version": expected_study_version,
    }
    return _finish(payload, overrides)


def accrual_payload(**overrides) -> dict:
    """Open or close the protocol to accrual."""
    payload = {"target_status": "OPEN_TO_ACCRUAL"}
    return _finish(payload, overrides)


# --------------------------------------------------------------------------
# Coverage analyses and items
# --------------------------------------------------------------------------


def create_coverage_analysis_payload(study_id, expected_study_version, **overrides) -> dict:
    """Open a coverage analysis revision for a protocol."""
    payload = {
        "study_id": study_id,
        "expected_study_version": expected_study_version,
    }
    return _finish(payload, overrides)


def create_coverage_item_payload(
    coverage_analysis_id, expected_coverage_analysis_version, **overrides
) -> dict:
    """Add one immutable item to a draft or returned analysis."""
    payload = {
        "coverage_analysis_id": coverage_analysis_id,
        "expected_coverage_analysis_version": expected_coverage_analysis_version,
        "item_code": "36415",
        "description": "Collection of venous blood by venipuncture",
        "classification": "RESEARCH_PAID",
        "medicare_coverage_basis": "NOT_COVERED",
        "budget_category": "PER_PATIENT",
        "charge_master_unit_cents": 5000,
        "negotiated_unit_cents": 3000,
        "expected_occurrences": 1,
    }
    return _finish(payload, overrides)


def return_analysis_payload(**overrides) -> dict:
    """Return an analysis under review to the analyst."""
    payload = {"return_reason": "Reclassify the screening laboratory panel."}
    return _finish(payload, overrides)


# --------------------------------------------------------------------------
# Study calendars, visits and charge routes
# --------------------------------------------------------------------------


def create_study_calendar_payload(study_id, source_analysis_id, **overrides) -> dict:
    """Start a new EHR study-calendar generation from an approved analysis."""
    payload = {
        "study_id": study_id,
        "source_analysis_id": source_analysis_id,
    }
    return _finish(payload, overrides)


def create_calendar_visit_payload(study_calendar_id, **overrides) -> dict:
    """Add a visit to a draft calendar."""
    payload = {
        "study_calendar_id": study_calendar_id,
        "visit_name": "Screening",
        "sequence_index": 1,
        "target_day_offset": 0,
        "window_before_days": 0,
        "window_after_days": 3,
    }
    return _finish(payload, overrides)


def create_visit_charge_route_payload(
    calendar_visit_id, coverage_item_id, **overrides
) -> dict:
    """Link a coverage item to a calendar visit."""
    payload = {
        "calendar_visit_id": calendar_visit_id,
        "coverage_item_id": coverage_item_id,
    }
    return _finish(payload, overrides)


# --------------------------------------------------------------------------
# Subjects and subject visits
# --------------------------------------------------------------------------


def create_study_subject_payload(study_id, **overrides) -> dict:
    """Register a screening subject on a protocol open to accrual."""
    payload = {
        "study_id": study_id,
        "subject_number": "S-001",
    }
    return _finish(payload, overrides)


def consent_payload(**overrides) -> dict:
    """Record informed consent and pin the study's published calendar generation."""
    payload = {"consent_date": "2026-09-01"}
    return _finish(payload, overrides)


def create_subject_visit_payload(
    study_subject_id, calendar_visit_id, actual_service_date, **overrides
) -> dict:
    """Schedule a calendar visit for a consented subject."""
    payload = {
        "study_subject_id": study_subject_id,
        "calendar_visit_id": calendar_visit_id,
        "actual_service_date": actual_service_date,
    }
    return _finish(payload, overrides)


# --------------------------------------------------------------------------
# Charges
# --------------------------------------------------------------------------


def create_charge_payload(study_id, **overrides) -> dict:
    """Post a charge from the EHR charge interface."""
    payload = {
        "study_id": study_id,
        "charge_code": "80053",
        "service_date": "2026-08-01",
        "amount_cents": 9000,
    }
    return _finish(payload, overrides)


def charge_review_payload(decision, **overrides) -> dict:
    """Charge review: route, hold for the sponsor, or write off as promotional."""
    payload = {"decision": decision}
    return _finish(payload, overrides)


# --------------------------------------------------------------------------
# Sponsor invoices
# --------------------------------------------------------------------------


def create_sponsor_invoice_payload(study_id, expected_study_version, **overrides) -> dict:
    """Raise a draft sponsor invoice and select its lines under the waterfall."""
    payload = {
        "study_id": study_id,
        "period_end_date": "2026-12-31",
        "expected_study_version": expected_study_version,
    }
    return _finish(payload, overrides)


def remittance_payload(outcome, **overrides) -> dict:
    """Record the sponsor's response: paid in full, short paid, or disputed."""
    payload = {"outcome": outcome}
    return _finish(payload, overrides)


# --------------------------------------------------------------------------
# Audit findings
# --------------------------------------------------------------------------


def create_audit_finding_payload(study_id, **overrides) -> dict:
    """Open an audit finding against a study or one of its charges."""
    payload = {
        "study_id": study_id,
        "finding_type": "IMPROPER_PAYER_BILL",
        "claimed_amount_cents": 9000,
    }
    return _finish(payload, overrides)


def respond_finding_payload(**overrides) -> dict:
    """File the billing office's response to an audit finding."""
    payload = {
        "response_narrative": "The billing office has reviewed the claim and agrees.",
    }
    return _finish(payload, overrides)


def resolve_finding_payload(disposition, **overrides) -> dict:
    """Close a responded finding."""
    payload = {"disposition": disposition}
    return _finish(payload, overrides)


# --------------------------------------------------------------------------
# Amendments and operations
# --------------------------------------------------------------------------


def create_amendment_payload(study_id, **overrides) -> dict:
    """File a protocol amendment."""
    payload = {
        "study_id": study_id,
        "scope": "ITEM_CHANGE",
        "effective_date": "2026-08-01",
    }
    return _finish(payload, overrides)


def aging_run_payload(study_id, **overrides) -> dict:
    """Advance the unbilled-charge aging epoch for one study."""
    payload = {"study_id": study_id}
    return _finish(payload, overrides)


REMOVE = _SENTINEL_REMOVE
