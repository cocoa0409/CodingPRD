"""Composite setup helpers.

Every helper here drives the API exactly as a client would, using the lenient
`get_success_data` so that a setup failure surfaces as a setup failure rather
than as a false assertion about the behaviour under test. Each helper accepts
`**overrides` so a test can vary one input without rebuilding the whole chain.

Two things are threaded carefully throughout:

* `expected_service_version` is re-read from the service immediately before
  every notice draft and every consent request, because publications, grants,
  revocations and cascades each advance the service's version.
* Parent calls carry the acting `ConsentRequest` identifier in `X-User-ID`, via
  `make_parent_headers`, because that is the identity the ownership check uses.
"""

from typing import List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import REQUIRED_CONTENT_KEYS, STARTUP_CLOCK, TEST_DEFAULTS
from .factories import (
    activity_payload,
    age_screen_payload,
    audience_sample_evidence_payload,
    child_data_record_payload,
    consent_request_payload,
    design_factor_evidence_payload,
    online_service_payload,
    parental_notice_payload,
    parental_rights_request_payload,
    retention_schedule_payload,
    safe_harbor_assessment_payload,
    safe_harbor_program_payload,
    third_party_integration_payload,
)
from .test_users import (
    make_assessor_headers,
    make_certifier_headers,
    make_engineer_headers,
    make_officer_headers,
    make_parent_headers,
)

OFFICER = make_officer_headers()
ENGINEER = make_engineer_headers()


# ---------------------------------------------------------------- the clock
def set_clock(to_iso8601: str, headers: Optional[dict] = None) -> dict:
    """Reposition the logical clock. A `ComplianceOfficer` may do this."""
    return get_success_data(api_client.set_current_utc(to_iso8601, headers or OFFICER))


def reset_clock_to_startup(headers: Optional[dict] = None) -> dict:
    """Move the clock back to the documented startup instant."""
    return set_clock(STARTUP_CLOCK, headers)


# --------------------------------------------------------------- tier 1: services
def create_service(headers: Optional[dict] = None, **overrides) -> dict:
    """Register an online service. Every counter starts at 0 and `version` at 1."""
    return get_success_data(
        api_client.create_online_service(online_service_payload(**overrides), headers or OFFICER)
    )


def read_service(service_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api_client.get_online_service(service_id, headers or OFFICER))


def service_version(service_id: str, headers: Optional[dict] = None) -> int:
    """Read the service's current `version` for use as `expected_service_version`."""
    return read_service(service_id, headers)["version"]


def run_determination(service_id: str, headers: Optional[dict] = None) -> dict:
    """Execute a determination run, which refreshes the computed figures and the axis."""
    return get_success_data(api_client.run_determination(service_id, headers or OFFICER))


def set_posture_override(
    service_id: str, posture_override: Optional[str], headers: Optional[dict] = None
) -> dict:
    """Submit `posture_override`; null hands control back to the computation."""
    return get_success_data(
        api_client.set_posture(
            service_id, {"posture_override": posture_override}, headers or OFFICER
        )
    )


# ------------------------------------------------------- tier 2: evidence rows
def add_design_factor(
    service_id: str, factor_code: str, rating: str, headers: Optional[dict] = None, **overrides
) -> dict:
    """Append one design-factor evidence row."""
    return get_success_data(
        api_client.create_determination_evidence(
            design_factor_evidence_payload(service_id, factor_code, rating, **overrides),
            headers or OFFICER,
        )
    )


def add_design_factors(
    service_id: str, factors: List[Tuple[str, str]], headers: Optional[dict] = None
) -> List[dict]:
    """Append several design-factor rows in the order given."""
    return [add_design_factor(service_id, code, rating, headers) for code, rating in factors]


def add_audience_sample(
    service_id: str,
    total_users: int,
    users_under_13: int,
    measurement_method: str = "PANEL",
    period_start: str = "2026-01-01T00:00:00Z",
    period_end: str = "2026-02-01T00:00:00Z",
    sample_verified: Optional[bool] = True,
    headers: Optional[dict] = None,
    **overrides,
) -> dict:
    """Append one audience-sample evidence row."""
    return get_success_data(
        api_client.create_determination_evidence(
            audience_sample_evidence_payload(
                service_id,
                measurement_method,
                period_start,
                period_end,
                total_users,
                users_under_13,
                sample_verified=sample_verified,
                **overrides,
            ),
            headers or OFFICER,
        )
    )


# --------------------------------------- tier 1/3: services at a determination
def service_with_design_score(
    factors: List[Tuple[str, str]], headers: Optional[dict] = None, **overrides
) -> dict:
    """Register a service, append the given design factors, and run the determination."""
    service = create_service(headers, **overrides)
    add_design_factors(service["id"], factors, headers)
    return run_determination(service["id"], headers)


def mixed_audience_service(headers: Optional[dict] = None, **overrides) -> dict:
    """A service determined `MIXED_AUDIENCE` on a single moderate subject-matter factor.

    One `SUBJECT_MATTER` row rated `MODERATE` yields a `design_score` of 0.60, which
    is at or above the design-first mixed threshold of 0.45 but below 0.75.
    """
    return service_with_design_score([("SUBJECT_MATTER", "MODERATE")], headers, **overrides)


def child_directed_primary_service(headers: Optional[dict] = None, **overrides) -> dict:
    """A service determined `CHILD_DIRECTED_PRIMARY` on one strong subject-matter factor.

    One `SUBJECT_MATTER` row rated `STRONG` yields a `design_score` of 1.00, at or
    above the design-first primary threshold of 0.75.
    """
    return service_with_design_score([("SUBJECT_MATTER", "STRONG")], headers, **overrides)


def general_audience_service(headers: Optional[dict] = None, **overrides) -> dict:
    """A service determined `GENERAL_AUDIENCE` on one incidental subject-matter factor.

    One `SUBJECT_MATTER` row rated `INCIDENTAL` yields a `design_score` of 0.25,
    below the design-first mixed threshold of 0.45.
    """
    return service_with_design_score([("SUBJECT_MATTER", "INCIDENTAL")], headers, **overrides)


# ------------------------------------------------------------ tier 2: age screens
def create_age_screen(service_id: str, headers: Optional[dict] = None, **overrides) -> dict:
    """Declare an age screen. It is born `DRAFT` with `revision_round` 0."""
    return get_success_data(
        api_client.create_age_screen(
            age_screen_payload(service_id, **overrides), headers or ENGINEER
        )
    )


def set_screen_status(
    screen_id: str, to_status: str, headers: Optional[dict] = None, **body
) -> dict:
    payload = {"to_status": to_status}
    payload.update(body)
    return get_success_data(
        api_client.set_age_screen_status(screen_id, payload, headers or OFFICER)
    )


def age_screen_in_review(service_id: str, **overrides) -> dict:
    """A screen submitted for review. `DRAFT -> IN_REVIEW` is engineer-only."""
    screen = create_age_screen(service_id, **overrides)
    return set_screen_status(screen["id"], "IN_REVIEW", ENGINEER)


def active_age_screen(service_id: str, **overrides) -> dict:
    """A fully neutral screen carried through to `ACTIVE`.

    `DRAFT -> IN_REVIEW` is made by the engineer and `IN_REVIEW -> ACTIVE` by the
    officer, which is where the segregation of duties bites.
    """
    screen = age_screen_in_review(service_id, **overrides)
    return set_screen_status(screen["id"], "ACTIVE", OFFICER)


def rejected_age_screen(service_id: str, **overrides) -> dict:
    """A screen sent back by the officer: `IN_REVIEW -> REJECTED`."""
    screen = age_screen_in_review(service_id, **overrides)
    return set_screen_status(screen["id"], "REJECTED", OFFICER)


def age_screen_at_revision_round(service_id: str, rounds: int, **overrides) -> dict:
    """A screen driven around the rejection/revision loop `rounds` times.

    Each `REJECTED -> DRAFT` advances `revision_round` by one, and the loop is
    permitted only while `revision_round` is strictly below 2.
    """
    screen = create_age_screen(service_id, **overrides)
    screen_id = screen["id"]
    current = screen
    for _ in range(rounds):
        set_screen_status(screen_id, "IN_REVIEW", ENGINEER)
        set_screen_status(screen_id, "REJECTED", OFFICER)
        current = set_screen_status(screen_id, "DRAFT", ENGINEER)
    return current


# ----------------------------------------------------- tier 2: parental notices
def create_notice(
    service_id: str,
    content_keys: Optional[List[str]] = None,
    headers: Optional[dict] = None,
    **overrides,
) -> dict:
    """Draft a notice revision, re-reading the service version for the guard."""
    version = service_version(service_id, headers)
    return get_success_data(
        api_client.create_parental_notice(
            parental_notice_payload(service_id, version, content_keys, **overrides),
            headers or OFFICER,
        )
    )


def publish_notice(notice_id: str, headers: Optional[dict] = None) -> dict:
    """Publish a notice: `DRAFT -> PUBLISHED`."""
    return get_success_data(api_client.publish_parental_notice(notice_id, headers or OFFICER))


def published_notice(
    service_id: str,
    content_keys: Optional[List[str]] = None,
    headers: Optional[dict] = None,
    **overrides,
) -> dict:
    """A complete notice carried through to `PUBLISHED`.

    A complete notice has an empty `missing_content_keys`, which is what permits
    publication.
    """
    notice = create_notice(
        service_id,
        list(REQUIRED_CONTENT_KEYS) if content_keys is None else content_keys,
        headers,
        **overrides,
    )
    return publish_notice(notice["id"], headers)


# --------------------------------------------------------- tier 2: activities
def create_activity(
    service_id: str,
    activity_code: str = TEST_DEFAULTS["ACTIVITY_CODE"],
    participation_required_elements: Optional[List[str]] = None,
    headers: Optional[dict] = None,
    **overrides,
) -> dict:
    return get_success_data(
        api_client.create_activity(
            activity_payload(
                service_id, activity_code, participation_required_elements, **overrides
            ),
            headers or OFFICER,
        )
    )


# ------------------------------------------------- tier 2: retention schedules
def create_retention_schedule(service_id: str, headers: Optional[dict] = None, **overrides) -> dict:
    return get_success_data(
        api_client.create_retention_schedule(
            retention_schedule_payload(service_id, **overrides), headers or OFFICER
        )
    )


# ------------------------------------------------------ tier 2: integrations
def create_integration(
    service_id: str,
    vendor_name: str = "AdVendor",
    integration_type: str = "ANALYTICS",
    collects_persistent_identifier: bool = False,
    placement_area: str = "CHILD_DIRECTED_AREA",
    headers: Optional[dict] = None,
    **overrides,
) -> dict:
    """Declare an integration. A newly declared integration has `status` `DECLARED`."""
    return get_success_data(
        api_client.create_third_party_integration(
            third_party_integration_payload(
                service_id,
                vendor_name,
                integration_type,
                collects_persistent_identifier,
                placement_area,
                **overrides,
            ),
            headers or OFFICER,
        )
    )


def set_integration_status(
    integration_id: str, to_status: str, headers: Optional[dict] = None, **body
) -> dict:
    payload = {"to_status": to_status}
    payload.update(body)
    return get_success_data(
        api_client.set_third_party_integration_status(integration_id, payload, headers or OFFICER)
    )


def approved_integration(
    service_id: str,
    vendor_name: str = "AdVendor",
    integration_type: str = "ANALYTICS",
    collects_persistent_identifier: bool = False,
    placement_area: str = "CHILD_DIRECTED_AREA",
    **overrides,
) -> dict:
    """An integration disclosed in a published notice and carried through to `APPROVED`.

    Approval requires `disclosed_in_notice` to be true, which is what publishing a
    notice naming the vendor unlocks.
    """
    integration = create_integration(
        service_id,
        vendor_name,
        integration_type,
        collects_persistent_identifier,
        placement_area,
        **overrides,
    )
    published_notice(service_id, disclosed_integration_vendors=[vendor_name])
    set_integration_status(integration["id"], "AUDIT_PENDING")
    return set_integration_status(integration["id"], "APPROVED")


# ---------------------------------------------------- tier 3: consent lifecycle
def create_consent(
    service_id: str,
    notice_id: str,
    parent_email: str = "parent@example.com",
    child_pseudonym: str = "child-1",
    headers: Optional[dict] = None,
    **overrides,
) -> dict:
    """Open a consent request, re-reading the service version for the guard."""
    version = service_version(service_id, headers)
    return get_success_data(
        api_client.create_consent_request(
            consent_request_payload(
                service_id,
                notice_id,
                parent_email,
                child_pseudonym,
                version,
                **overrides,
            ),
            headers or OFFICER,
        )
    )


def set_consent_status(
    consent_id: str, to_status: str, headers: Optional[dict] = None, **body
) -> dict:
    payload = {"to_status": to_status}
    payload.update(body)
    return get_success_data(
        api_client.set_consent_request_status(consent_id, payload, headers or OFFICER)
    )


def deliver_notice_to_consent(consent_id: str, headers: Optional[dict] = None) -> dict:
    """`INITIATED -> NOTICE_DELIVERED`, which sets `verification_deadline_at`."""
    return set_consent_status(consent_id, "NOTICE_DELIVERED", headers)


def open_verification(consent_id: str, headers: Optional[dict] = None) -> dict:
    """`NOTICE_DELIVERED -> PENDING_VERIFICATION`."""
    return set_consent_status(consent_id, "PENDING_VERIFICATION", headers)


def grant_consent(
    consent_id: str,
    verification_evidence_code: str = "EVID-001",
    headers: Optional[dict] = None,
    **body,
) -> dict:
    """`PENDING_VERIFICATION -> GRANTED`, which requires `verification_evidence_code`."""
    return set_consent_status(
        consent_id,
        "GRANTED",
        headers,
        verification_evidence_code=verification_evidence_code,
        **body,
    )


def granted_consent(
    service_id: str,
    notice_id: str,
    parent_email: str = "parent@example.com",
    child_pseudonym: str = "child-1",
    verification_evidence_code: str = "EVID-001",
    grant_body: Optional[dict] = None,
    **overrides,
) -> dict:
    """A consent request carried from `INITIATED` all the way to `GRANTED`."""
    consent = create_consent(service_id, notice_id, parent_email, child_pseudonym, **overrides)
    deliver_notice_to_consent(consent["id"])
    open_verification(consent["id"])
    return grant_consent(
        consent["id"], verification_evidence_code, **(grant_body or {})
    )


def revoke_consent(
    consent_id: str, revocation_reason: Optional[str] = None, headers: Optional[dict] = None
) -> dict:
    """`GRANTED -> REVOKED`, requested directly by a `ComplianceOfficer`."""
    body = {} if revocation_reason is None else {"revocation_reason": revocation_reason}
    return set_consent_status(consent_id, "REVOKED", headers, **body)


# ------------------------------------------- tier 3: a service ready to collect
def collection_ready_service(
    data_element_code: str = "SCREEN_NAME",
    purpose_code: str = "PARTICIPATION_CORE",
    retention_days: int = 30,
    disposal_method: str = "ANONYMIZE",
    intended_uses: Optional[List[str]] = None,
    consent_method: str = "KNOWLEDGE_BASED_AUTH",
    parent_email: str = "parent@example.com",
    child_pseudonym: str = "child-1",
    determination: str = "MIXED_AUDIENCE",
    **service_overrides,
) -> dict:
    """Assemble every precondition collection needs, and return the whole bundle.

    Collection requires a determination that is not general audience, an `ACTIVE`
    age screen, an activity that names the element as required for participation,
    a granted consent covering the purpose, and a retention schedule in force.
    """
    if determination == "CHILD_DIRECTED_PRIMARY":
        service = child_directed_primary_service(**service_overrides)
    else:
        service = mixed_audience_service(**service_overrides)
    service_id = service["id"]

    screen = active_age_screen(service_id)
    activity = create_activity(
        service_id, participation_required_elements=[data_element_code]
    )
    schedule = create_retention_schedule(
        service_id,
        data_element_code=data_element_code,
        purpose_code=purpose_code,
        retention_days=retention_days,
        disposal_method=disposal_method,
    )
    notice = published_notice(service_id)
    consent = granted_consent(
        service_id,
        notice["id"],
        parent_email=parent_email,
        child_pseudonym=child_pseudonym,
        intended_uses=intended_uses,
        consent_method=consent_method,
    )
    return {
        "service": read_service(service_id),
        "service_id": service_id,
        "age_screen": screen,
        "activity": activity,
        "activity_id": activity["id"],
        "retention_schedule": schedule,
        "notice": notice,
        "notice_id": notice["id"],
        "consent": consent,
        "consent_id": consent["id"],
    }


def collect_record(
    service_id: str,
    consent_request_id: str,
    activity_id: str,
    headers: Optional[dict] = None,
    **overrides,
) -> dict:
    """Collect one child data element. Collection is the `PrivacyEngineer`'s act."""
    return get_success_data(
        api_client.create_child_data_record(
            child_data_record_payload(service_id, consent_request_id, activity_id, **overrides),
            headers or ENGINEER,
        )
    )


def collected_record(**bundle_overrides) -> dict:
    """A collection-ready service plus one collected record, returned as one bundle."""
    bundle = collection_ready_service(**bundle_overrides)
    record = collect_record(
        bundle["service_id"],
        bundle["consent_id"],
        bundle["activity_id"],
        data_element_code=bundle_overrides.get("data_element_code", "SCREEN_NAME"),
        purpose_code=bundle_overrides.get("purpose_code", "PARTICIPATION_CORE"),
    )
    bundle["record"] = record
    bundle["record_id"] = record["id"]
    bundle["service"] = read_service(bundle["service_id"])
    return bundle


# ------------------------------------------------ tier 3: parental rights flow
def create_rights_request(
    service_id: str,
    consent_request_id: str,
    right_type: str = "REVIEW",
    requester_email: str = "parent@example.com",
    headers: Optional[dict] = None,
    **overrides,
) -> dict:
    """Open a rights request as the `Parent` who holds the referenced consent."""
    return get_success_data(
        api_client.create_parental_rights_request(
            parental_rights_request_payload(
                service_id, consent_request_id, right_type, requester_email, **overrides
            ),
            headers or make_parent_headers(consent_request_id),
        )
    )


def set_rights_status(
    request_id: str, to_status: str, headers: Optional[dict] = None, **body
) -> dict:
    payload = {"to_status": to_status}
    payload.update(body)
    return get_success_data(
        api_client.set_parental_rights_request_status(request_id, payload, headers or OFFICER)
    )


def verified_rights_request(
    service_id: str,
    consent_request_id: str,
    right_type: str = "REVIEW",
    requester_email: str = "parent@example.com",
    verification_method: str = "GOVT_ID_MATCH",
    **overrides,
) -> dict:
    """A rights request carried `SUBMITTED -> VERIFYING -> VERIFIED`.

    The officer drives verification, and the method's tier must be at or above the
    tier of the consent's own `consent_method`.
    """
    request = create_rights_request(
        service_id, consent_request_id, right_type, requester_email, **overrides
    )
    set_rights_status(
        request["id"], "VERIFYING", OFFICER, verification_method=verification_method
    )
    return set_rights_status(request["id"], "VERIFIED", OFFICER)


def fulfilled_rights_request(
    service_id: str,
    consent_request_id: str,
    right_type: str = "REVIEW",
    scope_mode: str = "PARENT_CONSENT_SCOPE",
    requester_email: str = "parent@example.com",
    verification_method: str = "GOVT_ID_MATCH",
    **overrides,
) -> dict:
    """A rights request carried all the way to `FULFILLED` under the given scope."""
    request = verified_rights_request(
        service_id,
        consent_request_id,
        right_type,
        requester_email,
        verification_method,
        **overrides,
    )
    return set_rights_status(request["id"], "FULFILLED", OFFICER, scope_mode=scope_mode)


def rights_request_at_attempt_count(
    service_id: str,
    consent_request_id: str,
    attempts: int,
    right_type: str = "REVIEW",
    requester_email: str = "parent@example.com",
    verification_method: str = "GOVT_ID_MATCH",
) -> dict:
    """A rights request driven around the failed-verification loop `attempts` times.

    Each `VERIFYING -> VERIFICATION_FAILED` advances `verification_attempt_count`
    by one; the parent's re-submission is permitted only while that count is
    strictly below 3.
    """
    request = create_rights_request(
        service_id, consent_request_id, right_type, requester_email
    )
    request_id = request["id"]
    parent = make_parent_headers(consent_request_id)
    current = request
    for index in range(attempts):
        set_rights_status(
            request_id, "VERIFYING", OFFICER, verification_method=verification_method
        )
        current = set_rights_status(request_id, "VERIFICATION_FAILED", OFFICER)
        if index < attempts - 1:
            current = set_rights_status(request_id, "SUBMITTED", parent)
    return current


# ---------------------------------------------------- tier 3/5: safe harbor
def create_program(headers: Optional[dict] = None, **overrides) -> dict:
    """Register a safe harbor program. Its three settings carry declared defaults."""
    return get_success_data(
        api_client.create_safe_harbor_program(
            safe_harbor_program_payload(**overrides), headers or OFFICER
        )
    )


def create_assessment(
    service_id: str,
    program_id: str,
    assessment_year: int = 2026,
    headers: Optional[dict] = None,
    **overrides,
) -> dict:
    """Open an assessment. It is `DRAFT` with `preparer_user_id` set to the actor."""
    return get_success_data(
        api_client.create_safe_harbor_assessment(
            safe_harbor_assessment_payload(service_id, program_id, assessment_year, **overrides),
            headers or make_assessor_headers("assessor-1"),
        )
    )


def set_assessment_status(
    assessment_id: str, to_status: str, headers: Optional[dict] = None, **body
) -> dict:
    payload = {"to_status": to_status}
    payload.update(body)
    return get_success_data(
        api_client.set_safe_harbor_assessment_status(
            assessment_id, payload, headers or make_assessor_headers("assessor-1")
        )
    )


def submit_assessment(
    assessment_id: str,
    findings_open_count: int = 0,
    headers: Optional[dict] = None,
) -> dict:
    """`DRAFT -> SUBMITTED`, reserved to the assessor and requiring `findings_open_count`."""
    return set_assessment_status(
        assessment_id,
        "SUBMITTED",
        headers or make_assessor_headers("assessor-1"),
        findings_open_count=findings_open_count,
    )


def submitted_assessment(
    service_id: str,
    program_id: str,
    assessment_year: int = 2026,
    findings_open_count: int = 0,
    preparer_user_id: str = "assessor-1",
) -> dict:
    """An assessment opened by the named preparer and submitted for review."""
    assessor = make_assessor_headers(preparer_user_id)
    assessment = create_assessment(service_id, program_id, assessment_year, assessor)
    return submit_assessment(assessment["id"], findings_open_count, assessor)


def assessment_at_remediation_round(
    service_id: str,
    program_id: str,
    rounds: int,
    assessment_year: int = 2026,
    findings_open_count: int = 0,
    preparer_user_id: str = "assessor-1",
    certifier_user_id: str = "certifier-1",
) -> dict:
    """An assessment driven around the remediation loop `rounds` times.

    Each `SUBMITTED -> REMEDIATION_REQUIRED` is certifier-only and advances
    `remediation_round` by one; it is permitted only while that round is strictly
    below 2. The assessment is left in `SUBMITTED`.
    """
    assessor = make_assessor_headers(preparer_user_id)
    certifier = make_certifier_headers(certifier_user_id)
    assessment = create_assessment(service_id, program_id, assessment_year, assessor)
    assessment_id = assessment["id"]
    current = submit_assessment(assessment_id, findings_open_count, assessor)
    for _ in range(rounds):
        current = set_assessment_status(assessment_id, "REMEDIATION_REQUIRED", certifier)
        current = set_assessment_status(
            assessment_id, "SUBMITTED", assessor, findings_open_count=findings_open_count
        )
    return current


def certify_assessment(
    assessment_id: str, certifier_user_id: str = "certifier-1", headers: Optional[dict] = None
) -> dict:
    """`SUBMITTED -> CERTIFIED`, which requires an actor other than the preparer."""
    return get_success_data(
        api_client.certify_safe_harbor_assessment(
            assessment_id, headers or make_certifier_headers(certifier_user_id)
        )
    )


def certified_service(
    service_id: str,
    assessment_year: int = 2026,
    preparer_user_id: str = "assessor-1",
    certifier_user_id: str = "certifier-1",
    program_overrides: Optional[dict] = None,
) -> dict:
    """Enrol a service in a program and carry one assessment through to `CERTIFIED`.

    Certification sets `expires_at` to `certified_at` plus the program's
    `assessment_validity_days`, and the service's `safe_harbor_status` follows.
    """
    program = create_program(**(program_overrides or {}))
    assessment = submitted_assessment(
        service_id, program["id"], assessment_year, 0, preparer_user_id
    )
    certified = certify_assessment(assessment["id"], certifier_user_id)
    return {
        "program": program,
        "program_id": program["id"],
        "assessment": certified,
        "assessment_id": certified["id"],
        "service": read_service(service_id),
    }


# ------------------------------------------------------------------- readers
def _find_in_reverse_lookup(response, resource_id: str, label: str) -> dict:
    """Pick one row out of a service's reverse-lookup listing by its `id`."""
    rows, _ = validate_paginated(response)
    matches = [row for row in rows if row["id"] == resource_id]
    assert matches, f"{label} {resource_id} must appear in the service's {label} listing"
    return matches[0]


def read_integration(
    service_id: str, integration_id: str, headers: Optional[dict] = None
) -> dict:
    """Read one integration through the service's integration reverse lookup."""
    return _find_in_reverse_lookup(
        api_client.list_service_third_party_integrations(service_id, headers or OFFICER),
        integration_id,
        "integration",
    )


def read_age_screen(service_id: str, screen_id: str, headers: Optional[dict] = None) -> dict:
    """Read one age screen through the service's age-screen reverse lookup."""
    return _find_in_reverse_lookup(
        api_client.list_service_age_screens(service_id, headers or OFFICER),
        screen_id,
        "age screen",
    )


def read_notice(service_id: str, notice_id: str, headers: Optional[dict] = None) -> dict:
    """Read one notice revision through the service's notice reverse lookup."""
    return _find_in_reverse_lookup(
        api_client.list_service_parental_notices(service_id, headers or OFFICER),
        notice_id,
        "notice",
    )


def read_consent(consent_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api_client.get_consent_request(consent_id, headers or OFFICER))


def read_record(record_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api_client.get_child_data_record(record_id, headers or OFFICER))


def read_rights_request(request_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(
        api_client.get_parental_rights_request(request_id, headers or OFFICER)
    )


def read_assessment(assessment_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api_client.get_safe_harbor_assessment(assessment_id, headers or OFFICER))


# ------------------------------------------------------- tier 5: compliance runs
def run_compliance(service_id: str, headers: Optional[dict] = None) -> dict:
    """Trigger a compliance run for one service and return its inline summary."""
    return get_success_data(
        api_client.create_compliance_run({"service_id": service_id}, headers or OFFICER)
    )


def dispose_record_over_two_runs(service_id: str, headers: Optional[dict] = None) -> dict:
    """Run compliance twice, which is what secure disposal of a due record takes.

    Phase two schedules a due record in the first run; phase three destroys only
    records whose `scheduled_run_sequence` is strictly less than the current run's,
    so destruction happens in the second run.
    """
    first = run_compliance(service_id, headers)
    second = run_compliance(service_id, headers)
    return {"first_run": first, "second_run": second, "service": read_service(service_id)}
