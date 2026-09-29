"""Request-payload builders.

Each builder returns a fresh dictionary carrying the required fields of one
endpoint, with keyword overrides for the fields a scenario varies. Optional
fields are omitted unless supplied, so that the server's declared defaults are
exercised rather than shadowed.
"""

from .constants import (
    CANON_BUFFER_DAYS,
    CANON_FILER_STATUS,
    CANON_FORM_TYPE,
    CANON_MATERIALITY_BASE,
    CANON_PERIOD_END,
    CANON_PERIOD_LABEL,
)


def _drop_unset(payload, optional):
    for key, value in optional.items():
        if value is not None:
            payload[key] = value
    return payload


def charter_payload(
    name="Disclosure Committee Charter",
    version_label="2026.1",
    min_quorum_count=2,
    required_functions=None,
):
    return {
        "name": name,
        "version_label": version_label,
        "min_quorum_count": min_quorum_count,
        "required_functions": list(required_functions or ["FINANCE", "LEGAL"]),
    }


def member_payload(full_name, function, is_officer=None, voting=None):
    return _drop_unset(
        {"full_name": full_name, "function": function},
        {"is_officer": is_officer, "voting": voting},
    )


def cycle_payload(
    charter_id,
    fiscal_period_label=CANON_PERIOD_LABEL,
    form_type=CANON_FORM_TYPE,
    period_end_date=CANON_PERIOD_END,
    filer_status=CANON_FILER_STATUS,
    materiality_base_amount=CANON_MATERIALITY_BASE,
    internal_buffer_days=CANON_BUFFER_DAYS,
):
    return _drop_unset(
        {
            "fiscal_period_label": fiscal_period_label,
            "form_type": form_type,
            "period_end_date": period_end_date,
            "filer_status": filer_status,
            "materiality_base_amount": materiality_base_amount,
            "charter_id": charter_id,
        },
        {"internal_buffer_days": internal_buffer_days},
    )


def milestone_payload(kind, planned_start_utc, planned_end_utc):
    return {
        "kind": kind,
        "planned_start_utc": planned_start_utc,
        "planned_end_utc": planned_end_utc,
    }


def subcert_payload(cycle_id, member_id, scope_area, due_utc):
    return {
        "cycle_id": cycle_id,
        "member_id": member_id,
        "scope_area": scope_area,
        "due_utc": due_utc,
    }


def officer_cert_payload(cycle_id, officer_member_id, cert_type):
    return {
        "cycle_id": cycle_id,
        "officer_member_id": officer_member_id,
        "cert_type": cert_type,
    }


def document_payload(
    cycle_id,
    doc_type,
    author_member_id,
    expected_cycle_version,
    title=None,
    safe_harbor_present=None,
):
    return _drop_unset(
        {
            "cycle_id": cycle_id,
            "doc_type": doc_type,
            "title": title or f"{doc_type} draft",
            "author_member_id": author_member_id,
            "expected_cycle_version": expected_cycle_version,
        },
        {"safe_harbor_present": safe_harbor_present},
    )


def tie_out_item_payload(
    line_label,
    reported_value,
    source_record_value,
    tolerance_bp,
    preparer_member_id,
    expected_document_version,
):
    return {
        "line_label": line_label,
        "reported_value": reported_value,
        "source_record_value": source_record_value,
        "tolerance_bp": tolerance_bp,
        "preparer_member_id": preparer_member_id,
        "expected_document_version": expected_document_version,
    }


def tie_out_review_payload(reviewer_member_id, decision):
    return {"reviewer_member_id": reviewer_member_id, "decision": decision}


def adjusted_measure_payload(
    measure_label,
    adjusted_value,
    comparable_gaap_value,
    reconciliation_items,
    adjusted_prominence_index,
    gaap_prominence_index,
):
    return {
        "measure_label": measure_label,
        "adjusted_value": adjusted_value,
        "comparable_gaap_value": comparable_gaap_value,
        "reconciliation_items": list(reconciliation_items),
        "adjusted_prominence_index": adjusted_prominence_index,
        "gaap_prominence_index": gaap_prominence_index,
    }


def reconcile_payload(
    reconciliation_items=None,
    adjusted_prominence_index=None,
    gaap_prominence_index=None,
):
    return _drop_unset(
        {},
        {
            "reconciliation_items": reconciliation_items,
            "adjusted_prominence_index": adjusted_prominence_index,
            "gaap_prominence_index": gaap_prominence_index,
        },
    )


def qa_item_payload(question_text, topic, risk_tier, requires_safe_harbor=None):
    return _drop_unset(
        {"question_text": question_text, "topic": topic, "risk_tier": risk_tier},
        {"requires_safe_harbor": requires_safe_harbor},
    )


def material_event_payload(
    category,
    occurred_utc,
    discovered_utc,
    magnitude_amount,
    description="A between-periods event under assessment",
):
    return {
        "category": category,
        "occurred_utc": occurred_utc,
        "discovered_utc": discovered_utc,
        "magnitude_amount": magnitude_amount,
        "description": description,
    }


def filing_payload(cycle_id, document_id, amends_filing_id=None):
    return _drop_unset(
        {"cycle_id": cycle_id, "document_id": document_id},
        {"amends_filing_id": amends_filing_id},
    )


def correction_payload(
    description,
    error_amount,
    current_period_pretax_income,
    prior_period_pretax_income,
    cumulative_prior_uncorrected_amount=None,
):
    return _drop_unset(
        {
            "description": description,
            "error_amount": error_amount,
            "current_period_pretax_income": current_period_pretax_income,
            "prior_period_pretax_income": prior_period_pretax_income,
        },
        {"cumulative_prior_uncorrected_amount": cumulative_prior_uncorrected_amount},
    )


def assess_correction_payload(
    method=None,
    likelihood_pct=None,
    magnitude_amount=None,
    compensating_control_present=None,
):
    return _drop_unset(
        {"action": "ASSESS"},
        {
            "method": method,
            "likelihood_pct": likelihood_pct,
            "magnitude_amount": magnitude_amount,
            "compensating_control_present": compensating_control_present,
        },
    )


def action_payload(action, **extra):
    """A transition body: the action discriminator plus whatever the specific
    action requires."""
    payload = {"action": action}
    for key, value in extra.items():
        if value is not None:
            payload[key] = value
    return payload
