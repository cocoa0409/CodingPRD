"""Payload factories — one per PRD input surface, input fields only.

Optional fields are omitted from the payload unless a value is supplied, so a
factory call can exercise a documented default (for example an author's annual
cap or a journal's required embargo) simply by leaving the argument out.
"""

from typing import List, Optional

from .constants import TEST_DEFAULTS


# --------------------------------------------------------------------------- #
# small deterministic value builders
# --------------------------------------------------------------------------- #
def make_issn(seed: int = 1) -> str:
    """An ISSN in the NNNN-NNNX form."""
    return f"2041-{200 + seed:03d}X"


def make_orcid(seed: int = 1) -> str:
    """An ORCID iD in the four-groups-of-four form."""
    return f"0000-0002-{1800 + seed:04d}-009X"


def make_checksum(seed: int = 1) -> str:
    """A SHA-256 digest rendered as exactly 64 lowercase hexadecimal characters."""
    head = f"{seed:04x}"
    return (head + "abcdef0123456789" * 4)[:64]


# --------------------------------------------------------------------------- #
# publishers and journals
# --------------------------------------------------------------------------- #
def create_publisher_payload(
    publisher_code: str = "MERID",
    name: str = "Meridian Academic Press",
    country_code: str = TEST_DEFAULTS["COUNTRY_CODE"],
    **overrides,
) -> dict:
    payload = {
        "name": name,
        "publisher_code": publisher_code,
        "country_code": country_code,
    }
    payload.update(overrides)
    return payload


def create_screening_run_payload(
    doaj_indexed: bool = True,
    cope_member: bool = True,
    editorial_board_verified: bool = True,
    retraction_rate_per_1000: float = 0.0,
    peer_review_days_median: int = 40,
    apc_transparency_score: int = 100,
    **overrides,
) -> dict:
    payload = {
        "doaj_indexed": doaj_indexed,
        "cope_member": cope_member,
        "editorial_board_verified": editorial_board_verified,
        "retraction_rate_per_1000": retraction_rate_per_1000,
        "peer_review_days_median": peer_review_days_median,
        "apc_transparency_score": apc_transparency_score,
    }
    payload.update(overrides)
    return payload


def create_journal_payload(
    publisher_id: str,
    issn: str = None,
    title: str = "Journal of Open Scholarship",
    oa_model: str = "FULLY_OA",
    list_apc_cents: int = TEST_DEFAULTS["LIST_APC_CENTS"],
    required_embargo_months: Optional[int] = None,
    **overrides,
) -> dict:
    payload = {
        "publisher_id": publisher_id,
        "issn": issn if issn is not None else make_issn(1),
        "title": title,
        "oa_model": oa_model,
        "list_apc_cents": list_apc_cents,
    }
    if required_embargo_months is not None:
        payload["required_embargo_months"] = required_embargo_months
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------- #
# agreements and coverage lines
# --------------------------------------------------------------------------- #
def create_transformative_agreement_payload(
    publisher_id: str,
    expected_publisher_version: int,
    agreement_code: str = "TA-MERID-H1",
    effective_from: str = "2026-07-01",
    effective_until: str = "2027-07-01",
    article_quota: int = TEST_DEFAULTS["ARTICLE_QUOTA"],
    discount_pct: float = TEST_DEFAULTS["DISCOUNT_PCT"],
    covered_oa_models: Optional[List[str]] = None,
    **overrides,
) -> dict:
    payload = {
        "publisher_id": publisher_id,
        "agreement_code": agreement_code,
        "effective_from": effective_from,
        "effective_until": effective_until,
        "article_quota": article_quota,
        "discount_pct": discount_pct,
        "covered_oa_models": covered_oa_models
        if covered_oa_models is not None
        else ["FULLY_OA", "HYBRID"],
        "expected_publisher_version": expected_publisher_version,
    }
    payload.update(overrides)
    return payload


def create_agreement_coverage_payload(
    journal_id: str,
    coverage_type: str = "FULL_APC",
    covered_from: str = "2026-07-01",
    covered_until: str = "2027-06-30",
    capped_amount_cents: Optional[int] = None,
    **overrides,
) -> dict:
    payload = {
        "journal_id": journal_id,
        "coverage_type": coverage_type,
        "covered_from": covered_from,
        "covered_until": covered_until,
    }
    if capped_amount_cents is not None:
        payload["capped_amount_cents"] = capped_amount_cents
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------- #
# people, mandates and awards
# --------------------------------------------------------------------------- #
def create_author_payload(
    full_name: str = "Dr Ada Whitfield",
    email: str = "ada.whitfield@example.edu",
    department_code: str = "PHYS",
    affiliation_status: str = "ELIGIBLE_FACULTY",
    appointment_from: str = "2026-01-01",
    appointment_until: str = "2027-12-31",
    orcid: Optional[str] = None,
    annual_cap_cents: Optional[int] = None,
    **overrides,
) -> dict:
    payload = {
        "full_name": full_name,
        "email": email,
        "department_code": department_code,
        "affiliation_status": affiliation_status,
        "appointment_from": appointment_from,
        "appointment_until": appointment_until,
    }
    if orcid is not None:
        payload["orcid"] = orcid
    if annual_cap_cents is not None:
        payload["annual_cap_cents"] = annual_cap_cents
    payload.update(overrides)
    return payload


def create_funder_payload(
    name: str = "National Science Council",
    funder_code: str = "NSC",
    mandate_type: str = "GOLD_OA",
    max_embargo_months: int = 12,
    deposit_deadline_days: int = 90,
    license_required: str = "ANY",
    apc_allowable: bool = True,
    **overrides,
) -> dict:
    payload = {
        "name": name,
        "funder_code": funder_code,
        "mandate_type": mandate_type,
        "max_embargo_months": max_embargo_months,
        "deposit_deadline_days": deposit_deadline_days,
        "license_required": license_required,
        "apc_allowable": apc_allowable,
    }
    payload.update(overrides)
    return payload


def create_grant_payload(
    funder_id: str,
    pi_author_id: str,
    grant_number: str = "NSC-2026-0001",
    award_from: str = "2026-01-01",
    award_until: str = "2027-12-31",
    apc_budget_cents: int = 1000000,
    **overrides,
) -> dict:
    payload = {
        "funder_id": funder_id,
        "pi_author_id": pi_author_id,
        "grant_number": grant_number,
        "award_from": award_from,
        "award_until": award_until,
        "apc_budget_cents": apc_budget_cents,
    }
    payload.update(overrides)
    return payload


def create_apc_fund_payload(
    fund_code: str = "OA-CENTRAL-2027",
    fiscal_year: int = 2027,
    period_from: str = "2026-07-01",
    period_to: str = "2027-06-30",
    total_budget_cents: int = 1000000,
    priority_rank: int = 1,
    eligible_affiliation_statuses: Optional[List[str]] = None,
    per_article_cap_cents: int = 500000,
    **overrides,
) -> dict:
    payload = {
        "fund_code": fund_code,
        "fiscal_year": fiscal_year,
        "period_from": period_from,
        "period_to": period_to,
        "total_budget_cents": total_budget_cents,
        "priority_rank": priority_rank,
        "eligible_affiliation_statuses": eligible_affiliation_statuses
        if eligible_affiliation_statuses is not None
        else ["ELIGIBLE_FACULTY"],
        "per_article_cap_cents": per_article_cap_cents,
    }
    payload.update(overrides)
    return payload


def create_freeze_payload(reason: str = "AUDIT_HOLD", **overrides) -> dict:
    payload = {"reason": reason}
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------- #
# articles, determinations and publication
# --------------------------------------------------------------------------- #
def create_article_payload(
    journal_id: str,
    corresponding_author_id: str,
    manuscript_title: str = "Coherent Transport in Layered Oxides",
    accepted_on: str = "2026-08-05",
    grant_id: Optional[str] = None,
    apc_list_cents: Optional[int] = None,
    **overrides,
) -> dict:
    payload = {
        "journal_id": journal_id,
        "corresponding_author_id": corresponding_author_id,
        "manuscript_title": manuscript_title,
        "accepted_on": accepted_on,
    }
    if grant_id is not None:
        payload["grant_id"] = grant_id
    if apc_list_cents is not None:
        payload["apc_list_cents"] = apc_list_cents
    payload.update(overrides)
    return payload


def create_eligibility_check_payload(basis: Optional[str] = None, **overrides) -> dict:
    payload = {}
    if basis is not None:
        payload["basis"] = basis
    payload.update(overrides)
    return payload


def create_publication_payload(publication_date: str, **overrides) -> dict:
    payload = {"publication_date": publication_date}
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------- #
# fund requests
# --------------------------------------------------------------------------- #
def create_fund_request_payload(
    article_id: str,
    requested_cents: int,
    justification: str = TEST_DEFAULTS["JUSTIFICATION"],
    **overrides,
) -> dict:
    payload = {
        "article_id": article_id,
        "requested_cents": requested_cents,
        "justification": justification,
    }
    payload.update(overrides)
    return payload


def create_info_request_payload(
    info_needed: str = "Please confirm the quoted charge with the publisher.",
    **overrides,
) -> dict:
    payload = {"info_needed": info_needed}
    payload.update(overrides)
    return payload


def create_resubmission_payload(
    requested_cents: int,
    response_note: str = "Publisher confirmed the revised charge.",
    **overrides,
) -> dict:
    payload = {"requested_cents": requested_cents, "response_note": response_note}
    payload.update(overrides)
    return payload


def create_decision_payload(
    decision: str = "APPROVE", reason: Optional[str] = None, **overrides
) -> dict:
    payload = {"decision": decision}
    if reason is not None:
        payload["reason"] = reason
    payload.update(overrides)
    return payload


def create_withdrawal_payload(
    reason: str = "The author secured external funds.", **overrides
) -> dict:
    payload = {"reason": reason}
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------- #
# invoices
# --------------------------------------------------------------------------- #
def create_publisher_invoice_payload(
    publisher_id: str,
    article_id: str,
    invoice_number: str,
    invoice_amount_cents: int,
    claimed_discount_pct: float,
    vat_pct: float,
    invoice_date: str,
    currency: str = TEST_DEFAULTS["CURRENCY"],
    **overrides,
) -> dict:
    payload = {
        "publisher_id": publisher_id,
        "article_id": article_id,
        "invoice_number": invoice_number,
        "invoice_amount_cents": invoice_amount_cents,
        "currency": currency,
        "claimed_discount_pct": claimed_discount_pct,
        "vat_pct": vat_pct,
        "invoice_date": invoice_date,
    }
    payload.update(overrides)
    return payload


def create_payment_payload(payment_reference: str = "WIRE-88001", **overrides) -> dict:
    payload = {"payment_reference": payment_reference}
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------- #
# repository deposits
# --------------------------------------------------------------------------- #
def create_repository_deposit_payload(
    article_id: str,
    expected_article_version: int,
    version_label: str = "ACCEPTED_MANUSCRIPT",
    file_checksum: Optional[str] = None,
    license: str = "CC_BY",
    **overrides,
) -> dict:
    payload = {
        "article_id": article_id,
        "version_label": version_label,
        "file_checksum": file_checksum if file_checksum is not None else make_checksum(1),
        "license": license,
        "expected_article_version": expected_article_version,
    }
    payload.update(overrides)
    return payload


def create_curation_decision_payload(
    decision: str = "INGEST", curation_note: Optional[str] = None, **overrides
) -> dict:
    payload = {"decision": decision}
    if curation_note is not None:
        payload["curation_note"] = curation_note
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------- #
# logical clock
# --------------------------------------------------------------------------- #
def create_clock_payload(to_iso8601: str, **overrides) -> dict:
    payload = {"to_iso8601": to_iso8601}
    payload.update(overrides)
    return payload
