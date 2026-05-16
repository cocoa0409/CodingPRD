"""Composite setup helpers — multi-step preambles tests can reuse.

The prior-authorization workflow is long: register reference data
(patient, provider, catalog) -> create authorization (DRAFT) -> attach
clinical evidence -> submit (SUBMITTED) -> start-review
(UNDER_REVIEW) -> optionally request-info / peer-to-peer cycles ->
decide (APPROVED | DENIED) -> [APPROVED ages to EXPIRED via clock +
sweep | DENIED appealable along three tiers]. Most interesting test
claims need the system in a late-pipeline state.

IDENTITY THREADING — PRD §2.1:

- Provider is ENTITY-BACKED. Every Provider-driven call (create
  authorization, attach/withdraw evidence, submit, withdraw, schedule
  P2P, file appeal, withdraw appeal, GET own authorization) MUST mint
  headers via make_provider_headers(provider["id"]) — never via the
  shared PROVIDER_FALLBACK_ID constant. The fixtures here remember the
  acting Provider.id and thread it through every Provider call.

- PlatformAdmin, InitialReviewer, MedicalDirector, ExternalReviewer,
  and PayerReviewer are OPAQUE. Their shared TEST_USERS headers are
  canonical for every call.

Setup helpers use get_success_data (a lenient 2xx validator), so a
failed setup surfaces as "Setup failed" rather than a confusing test
assertion failure downstream.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    DEFAULT_APPROVAL_VALIDITY_DAYS,
    DEFAULT_EXPEDITED_SLA_HOURS,
    DEFAULT_STANDARD_SLA_HOURS,
    TEST_DEFAULTS,
)
from .factories import (
    attach_clinical_evidence_payload,
    clock_advance_payload,
    complete_peer_to_peer_payload,
    create_authorization_request_payload,
    create_patient_payload,
    create_provider_payload,
    create_service_catalog_item_payload,
    decide_appeal_payload,
    decide_authorization_payload,
    file_appeal_payload,
    iso_offset,
    iso_utc,
    occ_payload,
    parse_iso,
    patch_service_catalog_item_payload,
    schedule_peer_to_peer_payload,
)
from .test_users import TEST_USERS, make_provider_headers


# ===========================================================================
# Clock helpers — PRD §3.10 (PlatformAdmin only)
# ===========================================================================
def advance_clock_to(iso_timestamp: str,
                     headers: Optional[Dict[str, str]] = None
                     ) -> Dict[str, Any]:
    """POST /_clock/advance. PRD §3.10: PlatformAdmin only."""
    headers = headers or TEST_USERS["admin_headers"]
    resp = api_client.clock_advance(
        clock_advance_payload(to=iso_timestamp), headers,
    )
    return get_success_data(resp)


def run_sweep(headers: Optional[Dict[str, str]] = None
              ) -> Dict[str, Any]:
    """POST /_sweep/run. PRD §3.10: PlatformAdmin only."""
    headers = headers or TEST_USERS["admin_headers"]
    resp = api_client.sweep_run(headers)
    return get_success_data(resp)


def anchor_clock() -> None:
    """Pin the server clock to the standard 2026-05-16 anchor so all
    deadline calculations in difficulty-design instances are
    deterministic."""
    advance_clock_to(TEST_DEFAULTS["CLOCK_ANCHOR"])


# ===========================================================================
# Tier 0: reference data — Patient / Provider / ServiceCatalogItem.
# ===========================================================================
def create_patient(
    *,
    member_id: Optional[str] = None,
    full_name: Optional[str] = None,
    date_of_birth: Optional[str] = None,
    plan_type: str = "COMMERCIAL",
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /patients — PlatformAdmin only."""
    headers = headers or TEST_USERS["admin_headers"]
    resp = api_client.create_patient(
        create_patient_payload(
            member_id=member_id,
            full_name=full_name,
            date_of_birth=date_of_birth,
            plan_type=plan_type,
        ),
        headers,
    )
    return get_success_data(resp)


def create_provider(
    *,
    npi: Optional[str] = None,
    full_name: Optional[str] = None,
    specialty: str = "CARDIOLOGY",
    in_network: Optional[bool] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /providers — PlatformAdmin only."""
    headers = headers or TEST_USERS["admin_headers"]
    resp = api_client.create_provider(
        create_provider_payload(
            npi=npi, full_name=full_name,
            specialty=specialty, in_network=in_network,
        ),
        headers,
    )
    return get_success_data(resp)


def create_service_catalog_item(
    *,
    code: Optional[str] = None,
    kind: str = "SERVICE",
    name: Optional[str] = None,
    requires_pa: Optional[bool] = None,
    standard_sla_hours: int = DEFAULT_STANDARD_SLA_HOURS,
    expedited_sla_hours: int = DEFAULT_EXPEDITED_SLA_HOURS,
    approval_validity_days: int = DEFAULT_APPROVAL_VALIDITY_DAYS,
    required_evidence_categories: Optional[List[str]] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /service-catalog-items — PlatformAdmin only."""
    headers = headers or TEST_USERS["admin_headers"]
    resp = api_client.create_service_catalog_item(
        create_service_catalog_item_payload(
            code=code, kind=kind, name=name, requires_pa=requires_pa,
            standard_sla_hours=standard_sla_hours,
            expedited_sla_hours=expedited_sla_hours,
            approval_validity_days=approval_validity_days,
            required_evidence_categories=required_evidence_categories,
        ),
        headers,
    )
    return get_success_data(resp)


def patch_service_catalog_item(
    *,
    item: Dict[str, Any],
    headers: Optional[Dict[str, str]] = None,
    **patch_fields: Any,
) -> Dict[str, Any]:
    """PATCH /service-catalog-items/{id} — PlatformAdmin."""
    headers = headers or TEST_USERS["admin_headers"]
    resp = api_client.patch_service_catalog_item(
        item["id"],
        patch_service_catalog_item_payload(
            version=item["version"], **patch_fields,
        ),
        headers,
    )
    return get_success_data(resp)


def retire_service_catalog_item(item: Dict[str, Any]) -> Dict[str, Any]:
    """Retire a catalog item by patching status to RETIRED. PRD §3.1:
    "an admin may retire a catalog item by moving its status to
    RETIRED."""
    return patch_service_catalog_item(item=item, status="RETIRED")


def setup_reference_data(
    *,
    standard_sla_hours: int = DEFAULT_STANDARD_SLA_HOURS,
    expedited_sla_hours: int = DEFAULT_EXPEDITED_SLA_HOURS,
    approval_validity_days: int = DEFAULT_APPROVAL_VALIDITY_DAYS,
    required_evidence_categories: Optional[List[str]] = None,
    kind: str = "SERVICE",
    plan_type: str = "COMMERCIAL",
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Compose: ACTIVE patient + ACTIVE provider + ACTIVE catalog item.
    Returns (patient, provider, catalog_item)."""
    patient = create_patient(plan_type=plan_type)
    provider = create_provider()
    catalog_item = create_service_catalog_item(
        kind=kind,
        standard_sla_hours=standard_sla_hours,
        expedited_sla_hours=expedited_sla_hours,
        approval_validity_days=approval_validity_days,
        required_evidence_categories=required_evidence_categories,
    )
    return patient, provider, catalog_item


# ===========================================================================
# Re-fetch helpers (Provider-owned reads require provider headers).
# ===========================================================================
def re_get_authorization(
    auth_id: str,
    *,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """GET /authorization-requests/{id}. PRD §2.1: Provider sees only
    its own; admin / reviewers see any."""
    headers = headers or TEST_USERS["admin_headers"]
    return get_success_data(
        api_client.get_authorization_request(auth_id, headers),
    )


def re_get_peer_to_peer(p2p_id: str,
                        *,
                        headers: Optional[Dict[str, str]] = None
                        ) -> Dict[str, Any]:
    headers = headers or TEST_USERS["admin_headers"]
    return get_success_data(
        api_client.get_peer_to_peer_review(p2p_id, headers),
    )


def re_get_appeal(appeal_id: str,
                  *,
                  headers: Optional[Dict[str, str]] = None
                  ) -> Dict[str, Any]:
    headers = headers or TEST_USERS["admin_headers"]
    return get_success_data(api_client.get_appeal(appeal_id, headers))


# ===========================================================================
# Tier 1: AuthorizationRequest — DRAFT.
# ===========================================================================
def create_authorization_request(
    *,
    patient: Dict[str, Any],
    provider: Dict[str, Any],
    catalog_item: Dict[str, Any],
    urgency: Optional[str] = None,
    clinical_justification: Optional[str] = None,
    requested_units: Optional[int] = None,
    prior_request_id: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /authorization-requests — Provider only.

    PRD §2.1: Provider is entity-backed; X-User-ID MUST equal the
    acting Provider.id. The headers default uses
    make_provider_headers(provider["id"])."""
    headers = headers or make_provider_headers(provider["id"])
    payload = create_authorization_request_payload(
        patient_id=patient["id"],
        provider_id=provider["id"],
        service_catalog_item_id=catalog_item["id"],
        urgency=urgency,
        clinical_justification=clinical_justification,
        requested_units=requested_units,
        prior_request_id=prior_request_id,
    )
    resp = api_client.create_authorization_request(payload, headers)
    return get_success_data(resp)


# ===========================================================================
# Tier 2: ClinicalEvidence — attach helpers.
# ===========================================================================
def attach_evidence(
    *,
    provider: Dict[str, Any],
    authorization: Dict[str, Any],
    category: str = "LAB",
    title: Optional[str] = None,
    uri: Optional[str] = None,
    byte_size: int = 1024,
    sourced_from_request_id: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /authorization-requests/{id}/clinical-evidence — Provider."""
    headers = headers or make_provider_headers(provider["id"])
    resp = api_client.attach_clinical_evidence(
        authorization["id"],
        attach_clinical_evidence_payload(
            category=category, title=title, uri=uri,
            byte_size=byte_size,
            sourced_from_request_id=sourced_from_request_id,
        ),
        headers,
    )
    return get_success_data(resp)


def attach_categories(
    *,
    provider: Dict[str, Any],
    authorization: Dict[str, Any],
    categories: List[str],
    sourced_from_request_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Attach one ClinicalEvidence row per category in `categories`.
    Useful for reaching specific evidence_completeness_score values:
    e.g., passing 2 of 4 required categories yields a base score of
    0.50. Each row uses an independent uri so the duplicate-uri rule is
    not triggered."""
    out: List[Dict[str, Any]] = []
    for cat in categories:
        ev = attach_evidence(
            provider=provider, authorization=authorization,
            category=cat,
            sourced_from_request_id=sourced_from_request_id,
        )
        out.append(ev)
    return out


def withdraw_evidence(
    *,
    provider: Dict[str, Any],
    authorization: Dict[str, Any],
    evidence: Dict[str, Any],
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = headers or make_provider_headers(provider["id"])
    resp = api_client.withdraw_clinical_evidence(
        authorization["id"], evidence["id"], headers,
    )
    return get_success_data(resp)


# ===========================================================================
# Tier 3: AuthorizationRequest — SUBMITTED.
# ===========================================================================
def submit_authorization(
    *,
    provider: Dict[str, Any],
    authorization: Dict[str, Any],
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /authorization-requests/{id}/submit — Provider."""
    headers = headers or make_provider_headers(provider["id"])
    resp = api_client.submit_authorization_request(
        authorization["id"],
        occ_payload(version=authorization["version"]),
        headers,
    )
    return get_success_data(resp)


def setup_submitted_authorization(
    *,
    standard_sla_hours: int = DEFAULT_STANDARD_SLA_HOURS,
    expedited_sla_hours: int = DEFAULT_EXPEDITED_SLA_HOURS,
    approval_validity_days: int = DEFAULT_APPROVAL_VALIDITY_DAYS,
    required_evidence_categories: Optional[List[str]] = None,
    urgency: str = "STANDARD",
    clinical_justification: Optional[str] = None,
    requested_units: Optional[int] = None,
    evidence_categories_to_attach: Optional[List[str]] = None,
    anchor_clock_first: bool = False,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any],
           Dict[str, Any], List[Dict[str, Any]]]:
    """Compose: reference data + DRAFT authorization + N attached
    evidence rows + submit -> SUBMITTED.

    `evidence_categories_to_attach` defaults to the full
    `required_evidence_categories` set, so the request enters SUBMITTED
    with evidence_completeness_score = 1.00 — start-review will pass
    its 0.50 gate.

    Returns (patient, provider, catalog_item, authorization, evidences)
    with `authorization` re-fetched after submit so submitted_at,
    decision_deadline_at, evidence_completeness_score, etc. are
    visible."""
    if anchor_clock_first:
        anchor_clock()
    patient, provider, catalog_item = setup_reference_data(
        standard_sla_hours=standard_sla_hours,
        expedited_sla_hours=expedited_sla_hours,
        approval_validity_days=approval_validity_days,
        required_evidence_categories=required_evidence_categories,
    )
    auth = create_authorization_request(
        patient=patient, provider=provider, catalog_item=catalog_item,
        urgency=urgency,
        clinical_justification=clinical_justification,
        requested_units=requested_units,
    )
    # Attach evidence BEFORE submitting so the submit-time recompute of
    # evidence_completeness_score reflects the attached rows.
    cats_to_attach = (
        evidence_categories_to_attach
        if evidence_categories_to_attach is not None
        else list(
            catalog_item.get("required_evidence_categories", [])
            or TEST_DEFAULTS["REQUIRED_EVIDENCE_CATEGORIES"]
        )
    )
    evidences = attach_categories(
        provider=provider, authorization=auth, categories=cats_to_attach,
    )
    # Re-fetch so authorization.version is fresh in case the implementation
    # bumps version on each evidence recompute (PRD §2.4: version increments
    # on every mutation; §3.3 calls evidence attach a parent-recomputing
    # mutation). The OCC payload on submit must match the current version.
    auth = re_get_authorization(auth["id"])
    auth_after = submit_authorization(provider=provider, authorization=auth)
    auth_after = re_get_authorization(auth_after["id"])
    return patient, provider, catalog_item, auth_after, evidences


# ===========================================================================
# Tier 4: AuthorizationRequest — UNDER_REVIEW.
# ===========================================================================
def start_review(
    *,
    authorization: Dict[str, Any],
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /authorization-requests/{id}/start-review — InitialReviewer."""
    headers = headers or TEST_USERS["initial_reviewer_headers"]
    resp = api_client.start_review(
        authorization["id"],
        occ_payload(version=authorization["version"]),
        headers,
    )
    return get_success_data(resp)


def setup_under_review_authorization(
    *,
    standard_sla_hours: int = DEFAULT_STANDARD_SLA_HOURS,
    expedited_sla_hours: int = DEFAULT_EXPEDITED_SLA_HOURS,
    approval_validity_days: int = DEFAULT_APPROVAL_VALIDITY_DAYS,
    required_evidence_categories: Optional[List[str]] = None,
    urgency: str = "STANDARD",
    clinical_justification: Optional[str] = None,
    requested_units: Optional[int] = None,
    evidence_categories_to_attach: Optional[List[str]] = None,
    anchor_clock_first: bool = False,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any],
           Dict[str, Any], List[Dict[str, Any]]]:
    """Submitted authorization + start-review -> UNDER_REVIEW."""
    patient, provider, catalog_item, auth, evidences = (
        setup_submitted_authorization(
            standard_sla_hours=standard_sla_hours,
            expedited_sla_hours=expedited_sla_hours,
            approval_validity_days=approval_validity_days,
            required_evidence_categories=required_evidence_categories,
            urgency=urgency,
            clinical_justification=clinical_justification,
            requested_units=requested_units,
            evidence_categories_to_attach=evidence_categories_to_attach,
            anchor_clock_first=anchor_clock_first,
        )
    )
    start_review(authorization=auth)
    auth = re_get_authorization(auth["id"])
    return patient, provider, catalog_item, auth, evidences


# ===========================================================================
# Tier 5: pending_info <-> under_review cycles.
# ===========================================================================
def request_info(
    *,
    authorization: Dict[str, Any],
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /authorization-requests/{id}/request-info — InitialReviewer."""
    headers = headers or TEST_USERS["initial_reviewer_headers"]
    resp = api_client.request_info(
        authorization["id"],
        occ_payload(version=authorization["version"]),
        headers,
    )
    return get_success_data(resp)


def resume_review(
    *,
    authorization: Dict[str, Any],
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /authorization-requests/{id}/resume-review — InitialReviewer."""
    headers = headers or TEST_USERS["initial_reviewer_headers"]
    resp = api_client.resume_review(
        authorization["id"],
        occ_payload(version=authorization["version"]),
        headers,
    )
    return get_success_data(resp)


def cycle_pending_info(
    *,
    provider: Dict[str, Any],
    authorization: Dict[str, Any],
    extra_categories_for_resume: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Perform one full PENDING_INFO cycle on an UNDER_REVIEW
    authorization: request-info (UNDER_REVIEW -> PENDING_INFO), attach
    `extra_categories_for_resume` (defaults to none — the caller is
    expected to have configured the evidence set so the 0.75 resume
    gate is already met), then resume-review (PENDING_INFO ->
    UNDER_REVIEW). Returns the re-fetched authorization."""
    request_info(authorization=authorization)
    auth = re_get_authorization(authorization["id"])
    if extra_categories_for_resume:
        attach_categories(
            provider=provider, authorization=auth,
            categories=extra_categories_for_resume,
        )
        auth = re_get_authorization(auth["id"])
    resume_review(authorization=auth)
    return re_get_authorization(auth["id"])


# ===========================================================================
# Tier 6: peer-to-peer scheduling and completion.
# ===========================================================================
def schedule_peer_to_peer(
    *,
    provider: Dict[str, Any],
    authorization: Dict[str, Any],
    scheduled_at: Optional[str] = None,
    duration_minutes: int = 30,
    payer_reviewer_id: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /authorization-requests/{id}/peer-to-peer — Provider.
    PRD §3.5: scheduled_at must be strictly after now."""
    headers = headers or make_provider_headers(provider["id"])
    scheduled_at = scheduled_at or iso_offset(hours=2)
    resp = api_client.schedule_peer_to_peer(
        authorization["id"],
        schedule_peer_to_peer_payload(
            scheduled_at=scheduled_at,
            duration_minutes=duration_minutes,
            payer_reviewer_id=payer_reviewer_id,
            version=authorization["version"],
        ),
        headers,
    )
    return get_success_data(resp)


def complete_peer_to_peer(
    *,
    p2p: Dict[str, Any],
    outcome: str = "UPHELD",
    notes: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /peer-to-peer-reviews/{id}/complete — PayerReviewer."""
    headers = headers or TEST_USERS["payer_reviewer_headers"]
    resp = api_client.complete_peer_to_peer_review(
        p2p["id"],
        complete_peer_to_peer_payload(
            outcome=outcome, notes=notes, version=p2p["version"],
        ),
        headers,
    )
    return get_success_data(resp)


def cancel_peer_to_peer(
    *,
    p2p: Dict[str, Any],
    actor_provider: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /peer-to-peer-reviews/{id}/cancel — Provider or PayerReviewer."""
    if headers is None:
        if actor_provider is not None:
            headers = make_provider_headers(actor_provider["id"])
        else:
            headers = TEST_USERS["payer_reviewer_headers"]
    resp = api_client.cancel_peer_to_peer_review(
        p2p["id"], occ_payload(version=p2p["version"]), headers,
    )
    return get_success_data(resp)


# ===========================================================================
# Tier 7: decide -> APPROVED / DENIED.
# ===========================================================================
def decide_authorization(
    *,
    authorization: Dict[str, Any],
    outcome: str = "APPROVED",
    approved_units: Optional[int] = None,
    denial_reason_code: Optional[str] = None,
    rationale: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /authorization-requests/{id}/decide — InitialReviewer.

    Defaults to APPROVED with approved_units = authorization's
    requested_units. For DENIED, denial_reason_code is required;
    defaults to NOT_MEDICALLY_NECESSARY when omitted."""
    headers = headers or TEST_USERS["initial_reviewer_headers"]
    if outcome == "APPROVED":
        if approved_units is None:
            approved_units = authorization.get("requested_units", 1)
    else:
        approved_units = 0
        if denial_reason_code is None:
            denial_reason_code = "NOT_MEDICALLY_NECESSARY"
    resp = api_client.decide_authorization_request(
        authorization["id"],
        decide_authorization_payload(
            outcome=outcome,
            rationale=rationale,
            approved_units=approved_units,
            denial_reason_code=denial_reason_code,
            version=authorization["version"],
        ),
        headers,
    )
    return get_success_data(resp)


def setup_approved_authorization(
    *,
    standard_sla_hours: int = DEFAULT_STANDARD_SLA_HOURS,
    expedited_sla_hours: int = DEFAULT_EXPEDITED_SLA_HOURS,
    approval_validity_days: int = DEFAULT_APPROVAL_VALIDITY_DAYS,
    urgency: str = "STANDARD",
    required_evidence_categories: Optional[List[str]] = None,
    approved_units: Optional[int] = None,
    anchor_clock_first: bool = False,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any],
           Dict[str, Any]]:
    """Full lifecycle through APPROVED. Returns (patient, provider,
    catalog_item, authorization)."""
    patient, provider, catalog_item, auth, _ = (
        setup_under_review_authorization(
            standard_sla_hours=standard_sla_hours,
            expedited_sla_hours=expedited_sla_hours,
            approval_validity_days=approval_validity_days,
            required_evidence_categories=required_evidence_categories,
            urgency=urgency,
            anchor_clock_first=anchor_clock_first,
        )
    )
    decide_authorization(
        authorization=auth, outcome="APPROVED",
        approved_units=approved_units,
    )
    auth = re_get_authorization(auth["id"])
    return patient, provider, catalog_item, auth


def setup_denied_authorization(
    *,
    standard_sla_hours: int = DEFAULT_STANDARD_SLA_HOURS,
    expedited_sla_hours: int = DEFAULT_EXPEDITED_SLA_HOURS,
    approval_validity_days: int = DEFAULT_APPROVAL_VALIDITY_DAYS,
    urgency: str = "STANDARD",
    required_evidence_categories: Optional[List[str]] = None,
    denial_reason_code: str = "NOT_MEDICALLY_NECESSARY",
    anchor_clock_first: bool = False,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any],
           Dict[str, Any]]:
    """Full lifecycle through DENIED. Returns (patient, provider,
    catalog_item, authorization)."""
    patient, provider, catalog_item, auth, _ = (
        setup_under_review_authorization(
            standard_sla_hours=standard_sla_hours,
            expedited_sla_hours=expedited_sla_hours,
            approval_validity_days=approval_validity_days,
            required_evidence_categories=required_evidence_categories,
            urgency=urgency,
            anchor_clock_first=anchor_clock_first,
        )
    )
    decide_authorization(
        authorization=auth, outcome="DENIED",
        denial_reason_code=denial_reason_code,
    )
    auth = re_get_authorization(auth["id"])
    return patient, provider, catalog_item, auth


# ===========================================================================
# Tier 8: appeals.
# ===========================================================================
def file_appeal(
    *,
    provider: Dict[str, Any],
    authorization: Dict[str, Any],
    reason: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /authorization-requests/{id}/appeals — Provider."""
    headers = headers or make_provider_headers(provider["id"])
    resp = api_client.file_appeal(
        authorization["id"], file_appeal_payload(reason=reason), headers,
    )
    return get_success_data(resp)


_TIER_TO_REVIEWER_HEADER_KEY = {
    1: "initial_reviewer_headers",
    2: "medical_director_headers",
    3: "external_reviewer_headers",
}


def headers_for_appeal_tier(tier: int) -> Dict[str, str]:
    """PRD §3.11: "tier 1 is decided by an InitialReviewer, tier 2 by a
    MedicalDirector, and tier 3 by an ExternalReviewer."
    """
    key = _TIER_TO_REVIEWER_HEADER_KEY[tier]
    return TEST_USERS[key]


def decide_appeal(
    *,
    appeal: Dict[str, Any],
    outcome: str = "UPHELD",
    approved_units: Optional[int] = None,
    rationale: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /appeals/{id}/decide — tier-restricted reviewer."""
    if headers is None:
        headers = headers_for_appeal_tier(appeal["tier"])
    if outcome == "OVERTURNED" and approved_units is None:
        approved_units = 1
    resp = api_client.decide_appeal(
        appeal["id"],
        decide_appeal_payload(
            outcome=outcome,
            rationale=rationale,
            approved_units=approved_units,
            version=appeal["version"],
        ),
        headers,
    )
    return get_success_data(resp)


def withdraw_appeal(
    *,
    provider: Dict[str, Any],
    appeal: Dict[str, Any],
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /appeals/{id}/withdraw — Provider."""
    headers = headers or make_provider_headers(provider["id"])
    resp = api_client.withdraw_appeal(
        appeal["id"], occ_payload(version=appeal["version"]), headers,
    )
    return get_success_data(resp)


# ===========================================================================
# Tier 9: APPROVED -> EXPIRED via clock advance + sweep.
# ===========================================================================
def expire_authorization_via_sweep(
    *,
    authorization: Dict[str, Any],
) -> Dict[str, Any]:
    """Advance the clock past expires_at and run the sweep. Returns the
    re-fetched authorization (EXPIRED).

    PRD §3.10: "The expiration sweep — an admin-driven test capability
    — examines every authorization currently in APPROVED and, for each
    one whose current server time has reached or passed expires_at,
    advances its status to EXPIRED."""
    assert authorization.get("status") == "APPROVED", (
        f"expire_authorization_via_sweep requires APPROVED, got "
        f"{authorization.get('status')!r}"
    )
    expires_at = authorization.get("expires_at")
    assert expires_at, "authorization missing expires_at"
    # Advance the clock to one second past expires_at.
    after = parse_iso(expires_at)
    advance_clock_to(iso_utc(after))
    # Tiny extra padding to ensure now() >= expires_at.
    advance_clock_to(iso_offset(seconds=1, base=after))
    run_sweep()
    return re_get_authorization(authorization["id"])


# ===========================================================================
# Difficulty-design composite recipes — pre-built helpers for the
# scaffold_difficulty_design instances in SCAFFOLD_DIFFICULTY_DESIGN.yaml.
# ===========================================================================
def setup_two_drafts_for_dual_deadline(
    *,
    standard_sla_hours: int = 336,
    expedited_sla_hours: int = 72,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any],
           Dict[str, Any], Dict[str, Any]]:
    """Two DRAFT authorizations sharing the same catalog item, patient,
    and provider — one with urgency=STANDARD, one with EXPEDITED — each
    with the four-category required evidence set fully attached.
    Returns (patient, provider, catalog_item, draft_std, draft_exp).

    Used by `standard_vs_expedited_decision_deadline`.
    """
    anchor_clock()
    patient, provider, catalog_item = setup_reference_data(
        standard_sla_hours=standard_sla_hours,
        expedited_sla_hours=expedited_sla_hours,
    )
    draft_std = create_authorization_request(
        patient=patient, provider=provider, catalog_item=catalog_item,
        urgency="STANDARD",
    )
    # PRD §3.2: expedited justification must have >= 50 non-whitespace
    # chars. The default sentence in TEST_DEFAULTS has > 50.
    draft_exp = create_authorization_request(
        patient=patient, provider=provider, catalog_item=catalog_item,
        urgency="EXPEDITED",
    )
    attach_categories(
        provider=provider, authorization=draft_std,
        categories=list(TEST_DEFAULTS["REQUIRED_EVIDENCE_CATEGORIES"]),
    )
    attach_categories(
        provider=provider, authorization=draft_exp,
        categories=list(TEST_DEFAULTS["REQUIRED_EVIDENCE_CATEGORIES"]),
    )
    # Re-fetch so version reflects any parent recompute bumps from attaches.
    draft_std = re_get_authorization(draft_std["id"])
    draft_exp = re_get_authorization(draft_exp["id"])
    return patient, provider, catalog_item, draft_std, draft_exp


def setup_denied_then_overturn_with_patched_catalog() -> Tuple[
    Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any],
]:
    """Setup for `initial_vs_appeal_overturn_approval_expiration`:

    1. Anchor clock to 2026-05-16.
    2. Create catalog (approval_validity_days=90), patient, provider.
    3. Submit AuthorizationRequest R (urgency=STANDARD).
    4. PATCH catalog to approval_validity_days=30 -> version bumps to 2.
    5. start-review; decide DENIED.
    6. Advance clock to 2026-05-20.

    Returns (patient, provider, catalog_item_v2, authorization_DENIED).
    The DENIED authorization's service_catalog_item_version is pinned
    to the pre-patch version=1 with approval_validity_days=90."""
    anchor_clock()
    patient = create_patient()
    provider = create_provider()
    catalog_item_v1 = create_service_catalog_item(
        approval_validity_days=90,
    )
    auth = create_authorization_request(
        patient=patient, provider=provider, catalog_item=catalog_item_v1,
        urgency="STANDARD",
    )
    attach_categories(
        provider=provider, authorization=auth,
        categories=list(TEST_DEFAULTS["REQUIRED_EVIDENCE_CATEGORIES"]),
    )
    auth = re_get_authorization(auth["id"])
    submit_authorization(provider=provider, authorization=auth)
    # PATCH catalog to validity=30 AFTER submission so the version
    # captured at submission_at remains 90.
    catalog_item_v2 = patch_service_catalog_item(
        item=catalog_item_v1, approval_validity_days=30,
    )
    auth = re_get_authorization(auth["id"])
    start_review(authorization=auth)
    auth = re_get_authorization(auth["id"])
    decide_authorization(
        authorization=auth, outcome="DENIED",
        denial_reason_code="NOT_MEDICALLY_NECESSARY",
    )
    auth = re_get_authorization(auth["id"])
    # Advance clock to 2026-05-20T00:00:00Z so the appeal-overturn
    # decided_at is at that instant.
    advance_clock_to("2026-05-20T00:00:00.000Z")
    return patient, provider, catalog_item_v2, auth


def setup_resubmission_with_n_reused_evidence(
    *,
    num_reused: int = 3,
    required_categories: Optional[List[str]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any],
           Dict[str, Any], Dict[str, Any], List[Dict[str, Any]]]:
    """For the reuse-discount difficulty instances. Build:
    1. Catalog with `required_categories` (default 4 cats).
    2. A prior AuthorizationRequest P that reaches EXPIRED via:
       submit -> start-review -> decide APPROVED with small validity_days
       -> advance clock past expires_at -> run sweep.
    3. A resubmission authorization R with prior_request_id=P.id.

    On R, attach `num_reused` evidence rows with
    sourced_from_request_id=P.id, plus enough fresh rows to cover the
    required categories. Returns (patient, provider, catalog_item, P,
    R, [evidence_rows_on_R]).
    """
    cats = list(
        required_categories
        if required_categories is not None
        else TEST_DEFAULTS["REQUIRED_EVIDENCE_CATEGORIES"]
    )
    # Step 1: build an APPROVED authorization with a 1-day validity
    # window so it can be expired quickly.
    anchor_clock()
    patient, provider, catalog_item = setup_reference_data(
        required_evidence_categories=cats,
        approval_validity_days=1,
    )
    prior = create_authorization_request(
        patient=patient, provider=provider, catalog_item=catalog_item,
    )
    attach_categories(
        provider=provider, authorization=prior, categories=cats,
    )
    prior = re_get_authorization(prior["id"])
    submit_authorization(provider=provider, authorization=prior)
    prior = re_get_authorization(prior["id"])
    start_review(authorization=prior)
    prior = re_get_authorization(prior["id"])
    decide_authorization(
        authorization=prior, outcome="APPROVED", approved_units=1,
    )
    prior = re_get_authorization(prior["id"])
    prior = expire_authorization_via_sweep(authorization=prior)
    # Step 2: resubmission referencing prior_request_id.
    resub = create_authorization_request(
        patient=patient, provider=provider, catalog_item=catalog_item,
        prior_request_id=prior["id"],
    )
    # Step 3: attach `num_reused` reused rows + enough fresh rows so
    # that every required category is covered at least once.
    reused_rows: List[Dict[str, Any]] = []
    for i in range(num_reused):
        # Distribute reused rows across categories (cycle through cats).
        cat = cats[i % max(len(cats), 1)] if cats else "OTHER"
        ev = attach_evidence(
            provider=provider, authorization=resub,
            category=cat, sourced_from_request_id=prior["id"],
        )
        reused_rows.append(ev)
    # If reused rows didn't cover every required category, attach
    # fresh rows for the missing categories.
    covered = {ev["category"] for ev in reused_rows}
    for cat in cats:
        if cat not in covered:
            ev = attach_evidence(
                provider=provider, authorization=resub, category=cat,
            )
            reused_rows.append(ev)
    # Re-fetch resub so version reflects attach_evidence recompute bumps.
    resub = re_get_authorization(resub["id"])
    return patient, provider, catalog_item, prior, resub, reused_rows


def setup_authorization_for_two_pending_info_cycles() -> Tuple[
    Dict[str, Any], Dict[str, Any], Dict[str, Any],
]:
    """For `decision_deadline_circular_extension_evaluation_order`:
    Submit a STANDARD authorization with all required categories
    attached -> start-review. Returns (provider, catalog_item, auth) in
    UNDER_REVIEW, ready for cycle_pending_info() x 2."""
    anchor_clock()
    patient, provider, catalog_item = setup_reference_data()
    auth = create_authorization_request(
        patient=patient, provider=provider, catalog_item=catalog_item,
        urgency="STANDARD",
    )
    attach_categories(
        provider=provider, authorization=auth,
        categories=list(TEST_DEFAULTS["REQUIRED_EVIDENCE_CATEGORIES"]),
    )
    auth = re_get_authorization(auth["id"])
    submit_authorization(provider=provider, authorization=auth)
    auth = re_get_authorization(auth["id"])
    start_review(authorization=auth)
    auth = re_get_authorization(auth["id"])
    return provider, catalog_item, auth


def setup_authorization_in_peer_review(
    *,
    urgency: str = "STANDARD",
    evidence_categories_to_attach: Optional[List[str]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any],
           Dict[str, Any], Dict[str, Any]]:
    """Submitted -> start-review -> schedule peer-to-peer. Returns
    (patient, provider, catalog_item, authorization_PEER_REVIEW, p2p).
    """
    patient, provider, catalog_item, auth, _ = (
        setup_under_review_authorization(
            urgency=urgency,
            evidence_categories_to_attach=evidence_categories_to_attach,
        )
    )
    p2p = schedule_peer_to_peer(
        provider=provider, authorization=auth,
        scheduled_at=iso_offset(hours=24),
    )
    auth = re_get_authorization(auth["id"])
    return patient, provider, catalog_item, auth, p2p


def setup_authorization_with_two_p2p_calls_for_same_payer_reviewer(
    *,
    payer_reviewer_id: str,
    first_slot_iso: str,
    first_duration_minutes: int = 30,
) -> Tuple[
    Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any],
          Dict[str, Any]],
    Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]],
]:
    """For the half-open interval overlap difficulty instance.

    Set the clock so all P2P slots are strictly after now() (PRD §3.5).
    Build two independent UNDER_REVIEW authorizations under DIFFERENT
    patients/providers (so the per-authorization capacity-1 rule does
    not collide). Schedule a P2P for the first using
    `payer_reviewer_id` at `first_slot_iso` for `first_duration_minutes`.
    Returns:
      ((patient1, provider1, catalog1, auth1_PEER_REVIEW, p2p1),
       (patient2, provider2, catalog2, auth2_UNDER_REVIEW)).

    The test then schedules a second P2P on auth2 with the same
    payer_reviewer_id and varies the slot/duration to exercise the
    half-open boundary.
    """
    # Make sure the slot is strictly after the clock.
    anchor_clock()
    patient1, provider1, catalog1, auth1, _ = (
        setup_under_review_authorization()
    )
    patient2, provider2, catalog2, auth2, _ = (
        setup_under_review_authorization()
    )
    p2p1 = schedule_peer_to_peer(
        provider=provider1, authorization=auth1,
        scheduled_at=first_slot_iso,
        duration_minutes=first_duration_minutes,
        payer_reviewer_id=payer_reviewer_id,
    )
    auth1 = re_get_authorization(auth1["id"])
    return (
        (patient1, provider1, catalog1, auth1, p2p1),
        (patient2, provider2, catalog2, auth2),
    )


def setup_completed_p2p_on_authorization(
    *,
    p2p_outcome: str = "UPHELD",
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any],
           Dict[str, Any], Dict[str, Any]]:
    """For `peer_to_peer_per_authorization_aggregate_capacity_one`:
    Build an UNDER_REVIEW authorization, schedule one P2P, complete it
    (so the parent returns to UNDER_REVIEW per PRD §3.5). Returns
    (patient, provider, catalog_item, auth_UNDER_REVIEW, p2p_COMPLETED).
    """
    anchor_clock()
    patient, provider, catalog_item, auth, p2p = (
        setup_authorization_in_peer_review()
    )
    complete_peer_to_peer(p2p=p2p, outcome=p2p_outcome)
    auth = re_get_authorization(auth["id"])
    p2p = re_get_peer_to_peer(p2p["id"])
    return patient, provider, catalog_item, auth, p2p


def setup_denied_with_tier1_upheld() -> Tuple[
    Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any],
    Dict[str, Any],
]:
    """For `appeal_branching_per_tier_with_role_branch`:
    Reach R in DENIED with a tier=1 appeal already UPHELD. Returns
    (patient, provider, catalog_item, authorization_DENIED, appeal1_UPHELD)."""
    anchor_clock()
    patient, provider, catalog_item, auth = setup_denied_authorization()
    appeal1 = file_appeal(provider=provider, authorization=auth)
    decide_appeal(appeal=appeal1, outcome="UPHELD")
    appeal1 = re_get_appeal(appeal1["id"])
    auth = re_get_authorization(auth["id"])
    return patient, provider, catalog_item, auth, appeal1


def setup_denied_with_pending_tier1_appeal() -> Tuple[
    Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any],
    Dict[str, Any],
]:
    """For `appeal_overturn_cascade_depth_three`:
    Reach R in DENIED with a tier=1 PENDING appeal. Returns
    (patient, provider, catalog_item, authorization_DENIED, appeal1_PENDING).
    """
    anchor_clock()
    patient, provider, catalog_item, auth = setup_denied_authorization()
    appeal1 = file_appeal(provider=provider, authorization=auth)
    return patient, provider, catalog_item, auth, appeal1


def setup_authorization_in_peer_review_with_partial_evidence() -> Tuple[
    Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any],
    Dict[str, Any],
]:
    """For `p2p_overturn_recompute_unlocks_decision_chain_depth_two`:
    Submit with exactly 3 of 4 required categories attached (base score
    0.75), start-review, schedule peer-to-peer. Returns (patient,
    provider, catalog_item, authorization_PEER_REVIEW, p2p_SCHEDULED).
    The post-P2P-OVERTURNED bonus then raises the score to 0.85."""
    anchor_clock()
    cats = list(TEST_DEFAULTS["REQUIRED_EVIDENCE_CATEGORIES"])
    patient, provider, catalog_item, auth, _ = (
        setup_under_review_authorization(
            required_evidence_categories=cats,
            evidence_categories_to_attach=cats[:3],  # 3 of 4
        )
    )
    p2p = schedule_peer_to_peer(
        provider=provider, authorization=auth,
        scheduled_at=iso_offset(hours=24),
    )
    auth = re_get_authorization(auth["id"])
    return patient, provider, catalog_item, auth, p2p


def setup_under_review_with_partial_score_05() -> Tuple[
    Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any],
]:
    """For `evidence_completeness_at_exact_0_50_threshold`:
    Submit a STANDARD authorization with exactly 2 of 4 required
    categories attached (base 0.50). Returns (patient, provider,
    catalog_item, authorization_SUBMITTED).
    """
    anchor_clock()
    cats = list(TEST_DEFAULTS["REQUIRED_EVIDENCE_CATEGORIES"])
    patient, provider, catalog_item, auth, _ = (
        setup_submitted_authorization(
            required_evidence_categories=cats,
            evidence_categories_to_attach=cats[:2],  # 2 of 4 -> 0.50
        )
    )
    return patient, provider, catalog_item, auth


def setup_submitted_with_empty_required_categories() -> Tuple[
    Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any],
]:
    """For `empty_required_evidence_categories_yields_score_one`:
    Catalog with required_evidence_categories=[], so base coverage is
    1.0 with zero attached evidence rows. Submit and return.
    Returns (patient, provider, catalog_item, authorization_SUBMITTED).
    """
    anchor_clock()
    patient, provider, catalog_item, auth, _ = (
        setup_submitted_authorization(
            required_evidence_categories=[],
            evidence_categories_to_attach=[],
        )
    )
    return patient, provider, catalog_item, auth


__all__ = [
    # clock + sweep
    "advance_clock_to",
    "run_sweep",
    "anchor_clock",
    # reference data
    "create_patient",
    "create_provider",
    "create_service_catalog_item",
    "patch_service_catalog_item",
    "retire_service_catalog_item",
    "setup_reference_data",
    # re-fetch
    "re_get_authorization",
    "re_get_peer_to_peer",
    "re_get_appeal",
    # authorization lifecycle
    "create_authorization_request",
    "attach_evidence",
    "attach_categories",
    "withdraw_evidence",
    "submit_authorization",
    "setup_submitted_authorization",
    "start_review",
    "setup_under_review_authorization",
    "request_info",
    "resume_review",
    "cycle_pending_info",
    "schedule_peer_to_peer",
    "complete_peer_to_peer",
    "cancel_peer_to_peer",
    "decide_authorization",
    "setup_approved_authorization",
    "setup_denied_authorization",
    "file_appeal",
    "headers_for_appeal_tier",
    "decide_appeal",
    "withdraw_appeal",
    "expire_authorization_via_sweep",
    # difficulty-design recipes
    "setup_two_drafts_for_dual_deadline",
    "setup_denied_then_overturn_with_patched_catalog",
    "setup_resubmission_with_n_reused_evidence",
    "setup_authorization_for_two_pending_info_cycles",
    "setup_authorization_in_peer_review",
    "setup_authorization_with_two_p2p_calls_for_same_payer_reviewer",
    "setup_completed_p2p_on_authorization",
    "setup_denied_with_tier1_upheld",
    "setup_denied_with_pending_tier1_appeal",
    "setup_authorization_in_peer_review_with_partial_evidence",
    "setup_under_review_with_partial_score_05",
    "setup_submitted_with_empty_required_categories",
]
