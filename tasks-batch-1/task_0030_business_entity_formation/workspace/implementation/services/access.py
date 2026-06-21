"""Resource resolution + Filer-ownership scoping."""
from __future__ import annotations

import db
import errors


def get_business_entity_or_404(be_id: str) -> dict:
    be = db.business_entities.get(be_id)
    if be is None:
        raise errors.err_not_found(f"BusinessEntity {be_id} not found.")
    return be


def get_registered_agent_or_404(ra_id: str) -> dict:
    ra = db.registered_agents.get(ra_id)
    if ra is None:
        raise errors.err_not_found(f"RegisteredAgent {ra_id} not found.")
    return ra


def get_operating_agreement_or_404(oa_id: str) -> dict:
    oa = db.operating_agreements.get(oa_id)
    if oa is None:
        raise errors.err_not_found(f"OperatingAgreement {oa_id} not found.")
    return oa


def get_ein_application_or_404(ea_id: str) -> dict:
    ea = db.ein_applications.get(ea_id)
    if ea is None:
        raise errors.err_not_found(f"EINApplication {ea_id} not found.")
    return ea


def get_annual_report_or_404(ar_id: str) -> dict:
    ar = db.annual_reports.get(ar_id)
    if ar is None:
        raise errors.err_not_found(f"AnnualReport {ar_id} not found.")
    return ar


def get_foreign_qualification_or_404(fq_id: str) -> dict:
    fq = db.foreign_qualifications.get(fq_id)
    if fq is None:
        raise errors.err_not_found(f"ForeignQualification {fq_id} not found.")
    return fq


def get_boi_disclosure_or_404(b_id: str) -> dict:
    b = db.boi_disclosures.get(b_id)
    if b is None:
        raise errors.err_not_found(f"BOIDisclosure {b_id} not found.")
    return b


def require_filer_owns(role: str, user_id: str, business_entity_id: str) -> None:
    """If caller is Filer, X-User-ID must equal the target BusinessEntity.id.

    For non-Filer roles (StateAdmin, ComplianceOfficer), no ownership check.
    """
    if role == "Filer" and user_id != business_entity_id:
        raise errors.err_unauthorized("Filer can only act on its own BusinessEntity.")
