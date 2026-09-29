"""Request-payload builders.

Every builder returns a plain dict of the fields the endpoint accepts, with all
money as Python integers — never strings — and every proportional quantity as
integer basis points. Each takes ``**overrides`` so a test can restate one field
without restating the request, and ``omit`` removes a field entirely when a test
needs to exercise a default or a missing-field refusal.
"""

from .types import (
    APPROACH_SEPARATE_INTEREST,
    DISCLOSURE_FULL,
    EARNINGS_PERIOD_END,
    ELECTION_CASH,
    FORMULA_CODES,
    FORMULA_PERCENTAGE_OF_ACCOUNT,
    PLAN_TYPE_DEFINED_CONTRIBUTION,
    RECIPIENT_PARTICIPANT,
    REPRESENTS_PARTICIPANT,
    SNAPSHOT_TRUSTEE_STATEMENT,
    TEMPLATE_DETERMINATION_QUALIFIED,
)


def omit(payload, *field_names):
    """Return a copy of the payload with the named fields removed."""
    return {key: value for key, value in payload.items() if key not in field_names}


def _build(base, overrides):
    merged = dict(base)
    merged.update(overrides)
    return merged


# ─── Plans ────────────────────────────────────────────────────────────────


def plan_payload(**overrides):
    """A registration carrying every input, including the four switches."""
    return _build(
        {
            "plan_name": "Nordvik Manufacturing 401(k) Plan",
            "plan_type": PLAN_TYPE_DEFINED_CONTRIBUTION,
            "model_language_version": "MLP-2026.1",
            "acceptable_formula_codes": list(FORMULA_CODES),
            "allowed_approaches": [APPROACH_SEPARATE_INTEREST],
            "earnings_adjustment_method": EARNINGS_PERIOD_END,
        },
        overrides,
    )


def minimal_plan_payload(**overrides):
    """Only the six mandatory registration inputs, so defaults can be read."""
    return plan_payload(**overrides)


def procedure_status_payload(to_status, **overrides):
    return _build({"to_status": to_status}, overrides)


# ─── Participants and accounts ────────────────────────────────────────────


def participant_payload(plan_id, **overrides):
    return _build(
        {
            "plan_id": plan_id,
            "full_name": "Ingrid Halvorsen",
            "ssn_last4": "4417",
            "date_of_birth": "1975-03-12",
            "participation_start_date": "1999-01-01",
        },
        overrides,
    )


def plan_account_payload(**overrides):
    """An account opening; `monthly_payment_cents` defaults to 0 when omitted."""
    return _build({}, overrides)


def money_source_payload(source_code, balance_cents, **overrides):
    return _build(
        {"source_code": source_code, "balance_cents": balance_cents}, overrides
    )


def valuation_snapshot_payload(as_of_date, balance_cents, **overrides):
    return _build(
        {
            "as_of_date": as_of_date,
            "balance_cents": balance_cents,
            "source": SNAPSHOT_TRUSTEE_STATEMENT,
        },
        overrides,
    )


# ─── Cases, counsel and correspondence ────────────────────────────────────


def qdro_case_payload(participant_id, **overrides):
    return _build(
        {
            "participant_id": participant_id,
            "alternate_payee_name": "Marit Halvorsen",
            "alternate_payee_dob": "1977-08-22",
            "alternate_payee_address_on_file": True,
            "marital_period_start": "2005-06-01",
            "marital_period_end": "2024-01-01",
            "valuation_date": "2026-06-30",
        },
        overrides,
    )


def attorney_authorization_payload(**overrides):
    return _build(
        {
            "represents": REPRESENTS_PARTICIPANT,
            "attorney_name": "Halla Ingimundur",
            "attorney_bar_number": "BAR-77120",
            "attorney_email": "halla@ingimundur-law.example",
            "disclosure_scope": DISCLOSURE_FULL,
            "effective_from": "2026-08-01",
            "expires_at": "2027-08-01T00:00:00Z",
        },
        overrides,
    )


def communication_payload(**overrides):
    return _build(
        {
            "recipient_type": RECIPIENT_PARTICIPANT,
            "template_code": TEMPLATE_DETERMINATION_QUALIFIED,
            "disclosure_level": DISCLOSURE_FULL,
        },
        overrides,
    )


# ─── Draft orders and the revision cycle ──────────────────────────────────


def draft_order_payload(qdro_case_id, expected_case_version, **overrides):
    """A percentage-of-account separate-interest receipt, model language adopted."""
    return _build(
        {
            "qdro_case_id": qdro_case_id,
            "expected_case_version": expected_case_version,
            "document_reference": "DRO-2663-W1",
            "uses_model_language": True,
            "proposed_approach": APPROACH_SEPARATE_INTEREST,
            "proposed_formula_code": FORMULA_PERCENTAGE_OF_ACCOUNT,
            "proposed_percentage_bps": 4000,
        },
        overrides,
    )


def resubmission_payload(**overrides):
    """The same substantive terms as a receipt, minus the two create-only fields."""
    return _build(
        {
            "document_reference": "DRO-2663-W1-rev2",
            "uses_model_language": True,
            "proposed_approach": APPROACH_SEPARATE_INTEREST,
            "proposed_formula_code": FORMULA_PERCENTAGE_OF_ACCOUNT,
            "proposed_percentage_bps": 4000,
        },
        overrides,
    )


def deficiency_notice_payload(**overrides):
    """Issuance takes only the optional free-text explanation."""
    return _build({}, overrides)


def denial_payload(denial_reason, **overrides):
    return _build({"denial_reason": denial_reason}, overrides)


# ─── Distributions ────────────────────────────────────────────────────────


def distribution_payload(expected_ap_account_version, gross_amount_cents, **overrides):
    return _build(
        {
            "expected_ap_account_version": expected_ap_account_version,
            "election": ELECTION_CASH,
            "gross_amount_cents": gross_amount_cents,
        },
        overrides,
    )


# ─── Test-driving capabilities ────────────────────────────────────────────


def clock_payload(current_utc, **overrides):
    return _build({"current_utc": current_utc}, overrides)
