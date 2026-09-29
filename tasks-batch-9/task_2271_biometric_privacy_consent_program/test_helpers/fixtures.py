"""Composite state builders.

The harness restarts the server before every individual test, so every builder
here starts from an empty database and drives the public API only.  Builders are
layered:

* Tier 1 - single rows (program, jurisdiction, subject, ...)
* Tier 2 - rows walked to a named lifecycle state (published policy, executed
  contract, active asset, granted consent)
* Tier 3 - whole scenarios (a program whose inventory is lawfully collectable, a
  vendor-operated collection point, a priced incident, an exposure estimate)
* Tier 4 - programs deliberately parked in the RESTRICTED and FROZEN postures
* Tier 5 - convenience readers used by assertions

Every builder returns the parsed ``data`` payload, and the scenario builders
return a plain dict so tests can pick out exactly the ids they need.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import ApiClient
from .constants import DEFAULT_CLOCK_INPUT
from .test_users import (
    COMPLIANCE_APPROVER,
    HR_ADMIN,
    PRIVACY_OFFICER,
    SYSTEM_OPERATOR,
    VENDOR_MANAGER,
)

# ======================================================================
# Tier 1 - primitives
# ======================================================================


def set_clock(api: ApiClient, to_iso8601: str) -> str:
    data = get_success_data(api.set_clock(to_iso8601, SYSTEM_OPERATOR))
    return data["current_utc"]


def create_program(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(api.create_program(f.program_payload(**overrides), SYSTEM_OPERATOR))


def create_jurisdiction(api: ApiClient, program_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_jurisdiction(f.jurisdiction_payload(program_id, **overrides), SYSTEM_OPERATOR)
    )


def create_oregon_jurisdiction(api: ApiClient, program_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_jurisdiction(
            f.oregon_jurisdiction_payload(program_id, **overrides), SYSTEM_OPERATOR
        )
    )


def read_program(api: ApiClient, program_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api.get_program(program_id, headers or SYSTEM_OPERATOR))


def current_program_version(api: ApiClient, program_id: str) -> int:
    """The canonical read used by the policy-publish version pin."""
    return read_program(api, program_id)["version"]


def current_jurisdiction_version(api: ApiClient, jurisdiction_id: str) -> int:
    """The canonical read used by the exposure-assessment version pin."""
    return get_success_data(api.get_jurisdiction(jurisdiction_id, PRIVACY_OFFICER))["version"]


def create_data_subject(
    api: ApiClient,
    program_id: str,
    jurisdiction_id: str,
    external_ref: str = "EMP-0001",
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_data_subject(
            f.data_subject_payload(program_id, jurisdiction_id, external_ref, **overrides),
            HR_ADMIN,
        )
    )


# ======================================================================
# Tier 2 - rows walked to a named lifecycle state
# ======================================================================


def create_policy(api: ApiClient, program_id: str, jurisdiction_scope: List[str], **overrides: Any):
    return get_success_data(
        api.create_policy(f.policy_payload(program_id, jurisdiction_scope, **overrides), PRIVACY_OFFICER)
    )


def submit_policy(api: ApiClient, policy_id: str, headers: Optional[Dict[str, str]] = None):
    return get_success_data(
        api.transition_policy(policy_id, f.transition("IN_REVIEW"), headers or PRIVACY_OFFICER)
    )


def publish_policy(
    api: ApiClient,
    program_id: str,
    policy_id: str,
    approver_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Publish with a freshly read program version, since every child create
    bumps that version."""
    expected = current_program_version(api, program_id)
    return get_success_data(
        api.publish_policy(
            policy_id, {"expected_program_version": expected}, approver_headers or COMPLIANCE_APPROVER
        )
    )


def create_published_policy(
    api: ApiClient,
    program_id: str,
    jurisdiction_scope: List[str],
    submitter_headers: Optional[Dict[str, str]] = None,
    approver_headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    policy = create_policy(api, program_id, jurisdiction_scope, **overrides)
    submit_policy(api, policy["id"], submitter_headers)
    return publish_policy(api, program_id, policy["id"], approver_headers)


def create_notice_packet(
    api: ApiClient, program_id: str, jurisdiction_id: str, policy_id: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.create_notice_packet(
            f.notice_packet_payload(program_id, jurisdiction_id, policy_id, **overrides),
            PRIVACY_OFFICER,
        )
    )


def create_published_notice(
    api: ApiClient, program_id: str, jurisdiction_id: str, policy_id: str, **overrides: Any
) -> Dict[str, Any]:
    notice = create_notice_packet(api, program_id, jurisdiction_id, policy_id, **overrides)
    return get_success_data(
        api.transition_notice_packet(notice["id"], f.transition("PUBLISHED"), PRIVACY_OFFICER)
    )


def create_vendor(
    api: ApiClient, program_id: str, attestation_status: Optional[str] = None, **overrides: Any
) -> Dict[str, Any]:
    """Create a vendor and, when asked, walk its attestation through the
    declared order NOT_REQUESTED -> REQUESTED -> RECEIVED/REJECTED."""
    vendor = get_success_data(api.create_vendor(f.vendor_payload(program_id, **overrides), VENDOR_MANAGER))
    if attestation_status in (None, "NOT_REQUESTED"):
        return vendor
    vendor = get_success_data(
        api.record_attestation(vendor["id"], f.attestation_payload("REQUESTED"), VENDOR_MANAGER)
    )
    if attestation_status == "REQUESTED":
        return vendor
    return get_success_data(
        api.record_attestation(vendor["id"], f.attestation_payload(attestation_status), VENDOR_MANAGER)
    )


def create_vendor_contract(
    api: ApiClient, vendor_id: str, target_status: str = "DRAFT", **overrides: Any
) -> Dict[str, Any]:
    """Walk a contract to ``target_status`` along DRAFT -> APPROVED -> EXECUTED
    -> TERMINATED -> CLOSED_OUT, with approval always performed by an approver
    who is not the drafter."""
    contract = get_success_data(
        api.create_vendor_contract(f.vendor_contract_payload(vendor_id, **overrides), VENDOR_MANAGER)
    )
    if target_status == "DRAFT":
        return contract
    contract = get_success_data(
        api.transition_vendor_contract(contract["id"], f.transition("APPROVED"), COMPLIANCE_APPROVER)
    )
    if target_status == "APPROVED":
        return contract
    contract = get_success_data(
        api.transition_vendor_contract(contract["id"], f.transition("EXECUTED"), VENDOR_MANAGER)
    )
    if target_status == "EXECUTED":
        return contract
    contract = get_success_data(
        api.transition_vendor_contract(contract["id"], f.transition("TERMINATED"), VENDOR_MANAGER)
    )
    if target_status == "TERMINATED":
        return contract
    return get_success_data(
        api.transition_vendor_contract(
            contract["id"],
            f.transition("CLOSED_OUT", deletion_certificate_ref="cert-001"),
            VENDOR_MANAGER,
        )
    )


def create_asset(
    api: ApiClient,
    program_id: str,
    jurisdiction_id: str,
    target_status: str = "DISCOVERED",
    payload_builder=None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Walk an asset to ``target_status`` along DISCOVERED -> CLASSIFIED ->
    ACTIVE."""
    builder = payload_builder or f.asset_payload
    asset = get_success_data(
        api.create_asset(builder(program_id, jurisdiction_id, **overrides), PRIVACY_OFFICER)
    )
    if target_status == "DISCOVERED":
        return asset
    asset = get_success_data(
        api.transition_asset(asset["id"], f.transition("CLASSIFIED"), PRIVACY_OFFICER)
    )
    if target_status == "CLASSIFIED":
        return asset
    asset = get_success_data(api.transition_asset(asset["id"], f.transition("ACTIVE"), PRIVACY_OFFICER))
    if target_status == "ACTIVE":
        return asset
    return get_success_data(api.transition_asset(asset["id"], f.transition("GATED"), PRIVACY_OFFICER))


def create_consent(
    api: ApiClient,
    data_subject_id: str,
    asset_id: str,
    target_status: str = "SOLICITED",
    **overrides: Any,
) -> Dict[str, Any]:
    """Create a consent record and optionally walk it to GRANTED, DECLINED or
    REVOKED."""
    payload = f.consent_payload(data_subject_id, asset_id, **overrides)
    consent = get_success_data(api.create_consent_record(payload, HR_ADMIN))
    if target_status == "SOLICITED":
        return consent
    if target_status == "DECLINED":
        return get_success_data(
            api.transition_consent_record(
                consent["id"],
                f.transition("DECLINED", decline_reason="employee prefers manual timesheet"),
                HR_ADMIN,
            )
        )
    grant_body: Dict[str, Any] = {"to_status": "GRANTED"}
    if not payload.get("written_release_acknowledged"):
        grant_body["written_release_acknowledged"] = True
        grant_body["signature_ref"] = payload.get("signature_ref") or "sig-emp1-r1"
    consent = get_success_data(api.transition_consent_record(consent["id"], grant_body, HR_ADMIN))
    if target_status == "GRANTED":
        return consent
    if target_status == "REVOKED":
        return get_success_data(
            api.transition_consent_record(
                consent["id"],
                f.transition("REVOKED", revocation_reason="employee withdrew consent"),
                HR_ADMIN,
            )
        )
    raise ValueError(f"unsupported consent target status {target_status}")


# ======================================================================
# Tier 3 - whole scenarios
# ======================================================================


def compliance_baseline(
    api: ApiClient,
    jurisdiction_overrides: Optional[Dict[str, Any]] = None,
    policy_overrides: Optional[Dict[str, Any]] = None,
    notice_overrides: Optional[Dict[str, Any]] = None,
    program_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """A program with one Illinois jurisdiction, a PUBLISHED policy scoped to
    it and a PUBLISHED (IL, EMPLOYEE) notice packet: the minimum lawful footing
    for activating a collection point."""
    program = create_program(api, **(program_overrides or {}))
    jurisdiction = create_jurisdiction(api, program["id"], **(jurisdiction_overrides or {}))
    policy = create_published_policy(
        api, program["id"], [jurisdiction["id"]], **(policy_overrides or {})
    )
    notice = create_published_notice(
        api, program["id"], jurisdiction["id"], policy["id"], **(notice_overrides or {})
    )
    return {
        "program": program,
        "program_id": program["id"],
        "jurisdiction": jurisdiction,
        "jurisdiction_id": jurisdiction["id"],
        "policy": policy,
        "policy_id": policy["id"],
        "notice": notice,
        "notice_id": notice["id"],
    }


def baseline_with_active_asset(
    api: ApiClient,
    activation_clock: Optional[str] = "2026-08-15T00:00:00Z",
    asset_overrides: Optional[Dict[str, Any]] = None,
    payload_builder=None,
    **baseline_kwargs: Any,
) -> Dict[str, Any]:
    """The compliance baseline plus one in-house collection point in ACTIVE.

    ``activation_clock`` is applied after classification and before activation,
    so ``collection_started_at`` lands on exactly that instant; pass ``None`` to
    activate at the clock already in force.
    """
    ctx = compliance_baseline(api, **baseline_kwargs)
    asset = create_asset(
        api,
        ctx["program_id"],
        ctx["jurisdiction_id"],
        target_status="CLASSIFIED",
        payload_builder=payload_builder,
        **(asset_overrides or {}),
    )
    if activation_clock:
        set_clock(api, activation_clock)
    asset = get_success_data(api.transition_asset(asset["id"], f.transition("ACTIVE"), PRIVACY_OFFICER))
    ctx["asset"] = asset
    ctx["asset_id"] = asset["id"]
    return ctx


def baseline_with_granted_consent(
    api: ApiClient,
    activation_clock: Optional[str] = "2026-08-15T00:00:00Z",
    external_ref: str = "EMP-0001",
    **kwargs: Any,
) -> Dict[str, Any]:
    """One ACTIVE collection point with one enrolled employee."""
    ctx = baseline_with_active_asset(api, activation_clock=activation_clock, **kwargs)
    subject = create_data_subject(api, ctx["program_id"], ctx["jurisdiction_id"], external_ref)
    consent = create_consent(
        api,
        subject["id"],
        ctx["asset_id"],
        target_status="GRANTED",
        written_release_acknowledged=True,
        signature_ref="sig-emp1-r1",
    )
    ctx["subject"] = subject
    ctx["subject_id"] = subject["id"]
    ctx["consent"] = consent
    ctx["consent_id"] = consent["id"]
    return ctx


def vendor_operated_active_asset(
    api: ApiClient,
    vendor_overrides: Optional[Dict[str, Any]] = None,
    attestation_status: str = "RECEIVED",
    contract_status: str = "EXECUTED",
    activation_clock: Optional[str] = "2026-08-15T00:00:00Z",
    asset_overrides: Optional[Dict[str, Any]] = None,
    **baseline_kwargs: Any,
) -> Dict[str, Any]:
    """A collection point operated by a processor holding a live contract."""
    ctx = compliance_baseline(api, **baseline_kwargs)
    vendor = create_vendor(
        api, ctx["program_id"], attestation_status=attestation_status, **(vendor_overrides or {})
    )
    contract = create_vendor_contract(api, vendor["id"], target_status=contract_status)
    asset = create_asset(
        api,
        ctx["program_id"],
        ctx["jurisdiction_id"],
        target_status="CLASSIFIED",
        vendor_id=vendor["id"],
        **(asset_overrides or {}),
    )
    if activation_clock:
        set_clock(api, activation_clock)
    asset = get_success_data(api.transition_asset(asset["id"], f.transition("ACTIVE"), PRIVACY_OFFICER))
    ctx.update(
        {
            "vendor": vendor,
            "vendor_id": vendor["id"],
            "contract": contract,
            "contract_id": contract["id"],
            "asset": asset,
            "asset_id": asset["id"],
        }
    )
    return ctx


def exposure_units_scenario(
    api: ApiClient,
    program_overrides: Optional[Dict[str, Any]] = None,
    jurisdiction_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Two employees carrying three open consent violations: EMP-0001 holds one
    REVOKED record whose auto accommodation is still merely REQUESTED plus one
    fresh SOLICITED record, and EMP-0002 holds one SOLICITED record.
    """
    ctx = baseline_with_active_asset(
        api,
        program_overrides=program_overrides,
        jurisdiction_overrides=jurisdiction_overrides,
    )
    s1 = create_data_subject(api, ctx["program_id"], ctx["jurisdiction_id"], "EMP-0001")
    s2 = create_data_subject(api, ctx["program_id"], ctx["jurisdiction_id"], "EMP-0002")
    c1 = create_consent(
        api,
        s1["id"],
        ctx["asset_id"],
        target_status="REVOKED",
        written_release_acknowledged=True,
        signature_ref="sig-emp1-r1",
    )
    c2 = create_consent(api, s1["id"], ctx["asset_id"])
    c3 = create_consent(api, s2["id"], ctx["asset_id"])
    ctx.update(
        {
            "subject_1": s1,
            "subject_1_id": s1["id"],
            "subject_2": s2,
            "subject_2_id": s2["id"],
            "revoked_consent_id": c1["id"],
            "solicited_consent_1_id": c2["id"],
            "solicited_consent_2_id": c3["id"],
        }
    )
    return ctx


def draft_exposure_assessment(
    api: ApiClient,
    ctx: Dict[str, Any],
    variant: str = "PER_VIOLATION_STACKED",
    creator_headers: Optional[Dict[str, str]] = None,
    incident_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a DRAFT estimate with a freshly read jurisdiction version."""
    expected = current_jurisdiction_version(api, ctx["jurisdiction_id"])
    payload = f.exposure_assessment_payload(
        ctx["program_id"], ctx["jurisdiction_id"], expected, variant=variant, incident_id=incident_id
    )
    return get_success_data(
        api.create_exposure_assessment(payload, creator_headers or PRIVACY_OFFICER)
    )


def create_incident(
    api: ApiClient,
    program_id: str,
    affected_asset_ids: List[str],
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_incident(f.incident_payload(program_id, affected_asset_ids, **overrides), PRIVACY_OFFICER)
    )


def assessed_incident(
    api: ApiClient,
    program_id: str,
    affected_asset_ids: List[str],
    **overrides: Any,
) -> Dict[str, Any]:
    incident = create_incident(api, program_id, affected_asset_ids, **overrides)
    return get_success_data(
        api.transition_incident_notification(incident["id"], f.transition("ASSESSED"), PRIVACY_OFFICER)
    )


# ======================================================================
# Tier 4 - programs parked in a non-OPEN posture
# ======================================================================


def program_in_restricted_posture(api: ApiClient, **kwargs: Any) -> Dict[str, Any]:
    """Drive a program to RESTRICTED by gating a live collection point."""
    ctx = baseline_with_active_asset(api, **kwargs)
    gated = get_success_data(api.transition_asset(ctx["asset_id"], f.transition("GATED"), PRIVACY_OFFICER))
    ctx["asset"] = gated
    return ctx


def program_in_frozen_posture(api: ApiClient) -> Dict[str, Any]:
    """Drive a program to FROZEN by finalizing an estimate that reaches the
    80% share of the exposure ceiling."""
    ctx = exposure_units_scenario(api)
    assessment = draft_exposure_assessment(api, ctx)
    final = get_success_data(
        api.transition_exposure_assessment(assessment["id"], f.transition("FINAL"), COMPLIANCE_APPROVER)
    )
    ctx["assessment"] = final
    ctx["assessment_id"] = final["id"]
    return ctx


# ======================================================================
# Tier 5 - readers
# ======================================================================


def read_asset(api: ApiClient, asset_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_asset(asset_id, PRIVACY_OFFICER))


def read_policy(api: ApiClient, policy_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_policy(policy_id, PRIVACY_OFFICER))


def read_notice(api: ApiClient, notice_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_notice_packet(notice_id, PRIVACY_OFFICER))


def read_vendor(api: ApiClient, vendor_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_vendor(vendor_id, VENDOR_MANAGER))


def read_contract(api: ApiClient, contract_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_vendor_contract(contract_id, VENDOR_MANAGER))


def read_consent(api: ApiClient, consent_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_consent_record(consent_id, HR_ADMIN))


def read_subject(api: ApiClient, subject_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_data_subject(subject_id, HR_ADMIN))


def read_accommodation(api: ApiClient, accommodation_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_accommodation(accommodation_id, HR_ADMIN))


def read_incident(api: ApiClient, incident_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_incident(incident_id, PRIVACY_OFFICER))


def read_assessment(api: ApiClient, assessment_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_exposure_assessment(assessment_id, PRIVACY_OFFICER))


def accommodations_for_consent(api: ApiClient, consent_id: str) -> List[Dict[str, Any]]:
    body = get_success_data(api.list_accommodations(HR_ADMIN, {"created_from_consent_id": consent_id}))
    return body


def accommodations_for_subject(api: ApiClient, subject_id: str) -> List[Dict[str, Any]]:
    return get_success_data(api.list_accommodations(HR_ADMIN, {"data_subject_id": subject_id}))


# The clock every scenario starts from unless a test moves it.
STARTING_CLOCK = DEFAULT_CLOCK_INPUT
