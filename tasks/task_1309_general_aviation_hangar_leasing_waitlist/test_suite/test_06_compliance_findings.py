"""Use-audit findings: cure windows, escalation cascade, evidence gates, and roles."""
from test_helpers import (
    ApiErrorId,
    api_client,
    create_environmental_record_payload,
    file_finding,
    get_application,
    get_lease,
    list_audit_findings,
    list_lease_eviction_cases,
    make_tenant_headers,
    parse_instant,
    set_clock,
    setup_lease,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)


def _cure(finding_id, lease_id):
    return api_client.cure_audit_finding(finding_id, make_tenant_headers(lease_id))


def test_finding_moves_active_lease_to_cure_period(api, manager_headers, compliance_headers):
    """PRD §3.8: "A filed finding opens in `OPEN` status with `observed_at` stamped and its `cure_deadline` exactly the airport's `cure_window_days` days later. Filing against an `ACTIVE` lease moves it to `CURE_PERIOD`; filing against a `DELINQUENT` lease leaves it `DELINQUENT` with the finding `OPEN` alongside."

    Design: Difficulty/non_linear_state_machine/lease_active_cure_period_active_cycle
    """
    ctx = setup_lease(airport_overrides={"airport_code": "KCUR", "cure_window_days": 30},
                      size_class="CORPORATE", rate=250000, hangar_code="C-1",
                      applicant_name="Cora Cure")
    lease = ctx["lease"]
    set_clock("2026-08-05T00:00:00Z")

    finding = file_finding(lease["id"], "NON_AERONAUTICAL_USE")
    assert finding["status"] == "OPEN"
    # cure_window_days 30 from 2026-08-05 → 2026-09-04T00:00:00Z.
    assert parse_instant(finding["cure_deadline"]) == parse_instant("2026-09-04T00:00:00Z")
    assert get_lease(lease["id"])["status"] == "CURE_PERIOD"


def test_cure_returns_lease_to_active(api, manager_headers, compliance_headers):
    """PRD §3.8: "A successful cure stamps `cured_at`, moves the finding to `CURED`, and — when no other `OPEN` findings remain on the lease — returns the lease to `ACTIVE`."

    Design: Difficulty/non_linear_state_machine/lease_active_cure_period_active_cycle
    """
    ctx = setup_lease(airport_overrides={"airport_code": "KCU2", "cure_window_days": 30},
                      size_class="CORPORATE", rate=250000, hangar_code="C-2",
                      applicant_name="Cora Cure")
    lease = ctx["lease"]
    set_clock("2026-08-05T00:00:00Z")
    finding = file_finding(lease["id"], "NON_AERONAUTICAL_USE")

    set_clock("2026-08-20T00:00:00Z")  # strictly before the 2026-09-04 deadline
    cured = validate_success(_cure(finding["id"], lease["id"]))
    assert cured["status"] == "CURED"
    assert get_lease(lease["id"])["status"] == "ACTIVE"


def test_cure_deadline_expiry_escalates_finding(api, manager_headers, compliance_headers):
    """PRD §3.8: "When the sweep reaches a `cure_deadline` with the finding still `OPEN`, the finding becomes `ESCALATED_TO_EVICTION`, an eviction case is auto-created in `FILED` status with `reason` `UNCURED_AUDIT` and `use_audit_finding_id` pointing at that finding, and the lease moves to `EVICTION_PENDING` — a three-hop cascade from sweep to finding to case to lease."

    Design: Difficulty/transitive_cascade/cure_deadline_expiry_escalates_to_eviction_case
    """
    ctx = setup_lease(airport_overrides={"airport_code": "KESC", "cure_window_days": 30},
                      size_class="T_HANGAR", rate=90000, hangar_code="T-8",
                      applicant_name="Ed Escalate")
    lease = ctx["lease"]
    set_clock("2026-08-05T00:00:00Z")
    finding = file_finding(lease["id"], "NON_AERONAUTICAL_USE")

    set_clock("2026-09-04T00:00:00Z")  # the sweep reaches the cure deadline
    findings = list_audit_findings(lease["id"])
    assert findings[0]["id"] == finding["id"]
    assert findings[0]["status"] == "ESCALATED_TO_EVICTION"
    assert get_lease(lease["id"])["status"] == "EVICTION_PENDING"


def test_escalation_autocreates_eviction_case(api, manager_headers, compliance_headers):
    """PRD §3.8: "When the sweep reaches a `cure_deadline` with the finding still `OPEN`, the finding becomes `ESCALATED_TO_EVICTION`, an eviction case is auto-created in `FILED` status with `reason` `UNCURED_AUDIT` and `use_audit_finding_id` pointing at that finding, and the lease moves to `EVICTION_PENDING` — a three-hop cascade from sweep to finding to case to lease."

    Design: Difficulty/transitive_cascade/cure_deadline_expiry_escalates_to_eviction_case
    """
    ctx = setup_lease(airport_overrides={"airport_code": "KES2", "cure_window_days": 30},
                      size_class="T_HANGAR", rate=90000, hangar_code="T-9",
                      applicant_name="Ed Escalate")
    lease = ctx["lease"]
    set_clock("2026-08-05T00:00:00Z")
    finding = file_finding(lease["id"], "NON_AERONAUTICAL_USE")
    set_clock("2026-09-04T00:00:00Z")

    cases = list_lease_eviction_cases(lease["id"])
    assert len(cases) == 1, "escalation auto-creates exactly one eviction case"
    case = cases[0]
    assert case["status"] == "FILED"
    assert case["reason"] == "UNCURED_AUDIT"
    assert case["use_audit_finding_id"] == finding["id"]


def test_sublease_finding_rejected_when_sublease_allowed(api, manager_headers,
                                                         compliance_headers):
    """PRD §3.8: "An `UNAUTHORIZED_SUBLEASE` finding applies only when the lease's `sublease_allowed` is false (`ERR_FINDING_NOT_APPLICABLE`, HTTP 422)."

    Design: Difficulty/cross_entity_state_dependency/audit_filing_gated_by_lease_state_and_sublease_flag
    """
    ctx = setup_lease(airport_overrides={"airport_code": "KXSF"}, size_class="BOX", rate=80000,
                      hangar_code="B-31", applicant_name="Xena Flag", sublease_allowed=True)
    resp = api_client.file_audit_finding(ctx["lease"]["id"],
                                         {"finding_type": "UNAUTHORIZED_SUBLEASE"},
                                         compliance_headers)
    validate_error(resp, ApiErrorId.ERR_FINDING_NOT_APPLICABLE)
    assert get_lease(ctx["lease"]["id"])["status"] == "ACTIVE"


def test_sublease_finding_accepted_when_sublease_disallowed(api, manager_headers,
                                                            compliance_headers):
    """PRD §3.8: "An `UNAUTHORIZED_SUBLEASE` finding applies only when the lease's `sublease_allowed` is false (`ERR_FINDING_NOT_APPLICABLE`, HTTP 422)."
    PRD §3.8: "A filed finding opens in `OPEN` status with `observed_at` stamped and its `cure_deadline` exactly the airport's `cure_window_days` days later. Filing against an `ACTIVE` lease moves it to `CURE_PERIOD`; filing against a `DELINQUENT` lease leaves it `DELINQUENT` with the finding `OPEN` alongside."

    Design: Difficulty/cross_entity_state_dependency/audit_filing_gated_by_lease_state_and_sublease_flag
    """
    ctx = setup_lease(airport_overrides={"airport_code": "KXS3"}, size_class="BOX", rate=80000,
                      hangar_code="B-32", applicant_name="Xena Flag", sublease_allowed=False)
    finding = file_finding(ctx["lease"]["id"], "UNAUTHORIZED_SUBLEASE")
    assert finding["status"] == "OPEN"
    assert get_lease(ctx["lease"]["id"])["status"] == "CURE_PERIOD"


def test_sublease_finding_on_terminated_lease_reports_not_auditable(api, manager_headers,
                                                                    compliance_headers):
    """PRD §3.8: "A `ComplianceOfficer` files a use-audit finding against a lease in `ACTIVE` or `DELINQUENT` status — any other state fails with `ERR_LEASE_NOT_AUDITABLE` (HTTP 409) — naming a `finding_type` of `NON_AERONAUTICAL_USE`, `UNAUTHORIZED_SUBLEASE`, `INSURANCE_LAPSE`, or `ENVIRONMENTAL_LAPSE`; an invalid spelling fails with `ERR_INVALID_REQUEST`."
    PRD §2.9: "Every request passes through an ordered validation pipeline; when several checks would fail at once, the earliest check in this ordering determines the response."

    Design: Difficulty/priority_pair_validation_conflict/business_constraint_vs_business_referential_on_sublease_finding
    """
    # sublease_allowed=True, so the referential rule (ninth in the pipeline)
    # would also fail — but the state rule (fifth) decides the response.
    ctx = setup_lease(airport_overrides={"airport_code": "KPR2"}, size_class="T_HANGAR",
                      rate=90000, hangar_code="T-6", applicant_name="Pat Pair",
                      sublease_allowed=True)
    lease = ctx["lease"]
    validate_success(api_client.create_payment(lease["id"], {"amount_cents": 90000},
                                               make_tenant_headers(lease["id"])))
    validate_success(api_client.terminate_lease(lease["id"], {},
                                                make_tenant_headers(lease["id"])))

    resp = api_client.file_audit_finding(lease["id"],
                                         {"finding_type": "UNAUTHORIZED_SUBLEASE"},
                                         compliance_headers)
    validate_error(resp, ApiErrorId.ERR_LEASE_NOT_AUDITABLE)
    assert get_lease(lease["id"])["status"] == "TERMINATED"


def test_any_finding_on_terminated_lease_reports_not_auditable(api, manager_headers,
                                                               compliance_headers):
    """PRD §3.8: "A `ComplianceOfficer` files a use-audit finding against a lease in `ACTIVE` or `DELINQUENT` status — any other state fails with `ERR_LEASE_NOT_AUDITABLE` (HTTP 409) — naming a `finding_type` of `NON_AERONAUTICAL_USE`, `UNAUTHORIZED_SUBLEASE`, `INSURANCE_LAPSE`, or `ENVIRONMENTAL_LAPSE`; an invalid spelling fails with `ERR_INVALID_REQUEST`."

    Design: Difficulty/priority_pair_validation_conflict/business_constraint_vs_business_referential_on_sublease_finding
    """
    ctx = setup_lease(airport_overrides={"airport_code": "KPR4"}, size_class="T_HANGAR",
                      rate=90000, hangar_code="T-7", applicant_name="Pat Pair",
                      sublease_allowed=True)
    lease = ctx["lease"]
    validate_success(api_client.create_payment(lease["id"], {"amount_cents": 90000},
                                               make_tenant_headers(lease["id"])))
    validate_success(api_client.terminate_lease(lease["id"], {},
                                                make_tenant_headers(lease["id"])))

    # Isolated state failure: no referential rule is in play for this type.
    resp = api_client.file_audit_finding(lease["id"],
                                         {"finding_type": "NON_AERONAUTICAL_USE"},
                                         compliance_headers)
    validate_error(resp, ApiErrorId.ERR_LEASE_NOT_AUDITABLE)
    assert get_lease(lease["id"])["status"] == "TERMINATED"


def test_cure_finding_after_deadline_rejected_and_escalated(api, manager_headers,
                                                            compliance_headers):
    """PRD §3.8: "A finding is curable strictly before its `cure_deadline`; a cure attempt at exactly the deadline or later is rejected with `ERR_CURE_WINDOW_EXPIRED` (HTTP 409), and curing a finding that is not `OPEN` fails with `ERR_FINDING_NOT_OPEN` (HTTP 409)."
    PRD §3.8: "When the sweep reaches a `cure_deadline` with the finding still `OPEN`, the finding becomes `ESCALATED_TO_EVICTION`, an eviction case is auto-created in `FILED` status with `reason` `UNCURED_AUDIT` and `use_audit_finding_id` pointing at that finding, and the lease moves to `EVICTION_PENDING` — a three-hop cascade from sweep to finding to case to lease."

    Design: Corner/state_machines/cure_finding_after_deadline_rejected_and_escalated
    """
    ctx = setup_lease(airport_overrides={"airport_code": "KCDL", "cure_window_days": 30},
                      size_class="T_HANGAR", rate=90000, hangar_code="T-61",
                      applicant_name="Cal Deadline")
    lease = ctx["lease"]
    set_clock("2026-08-05T00:00:00Z")
    finding = file_finding(lease["id"], "NON_AERONAUTICAL_USE")

    # Exactly the cure deadline (2026-09-04): the same sweep escalates the
    # finding, so the late cure is rejected — the PRD names both the expired
    # window and the no-longer-OPEN state for this instant.
    set_clock("2026-09-04T00:00:00Z")
    resp = _cure(finding["id"], lease["id"])
    validate_error_is_one_of(
        resp, [ApiErrorId.ERR_CURE_WINDOW_EXPIRED, ApiErrorId.ERR_FINDING_NOT_OPEN]
    )
    findings = list_audit_findings(lease["id"])
    assert findings[0]["status"] == "ESCALATED_TO_EVICTION"
    assert get_lease(lease["id"])["status"] == "EVICTION_PENDING"


def test_insurance_lapse_finding_auto_created_on_certificate_expiry(api, manager_headers):
    """PRD §3.7: "A certificate whose coverage and dates pass this check at submission is recorded `VALID`; on each sweep, any `VALID` certificate whose `effective_to` has been reached flips to `EXPIRED`, and a lease left with zero covering certificates is flagged with an `INSURANCE_LAPSE` finding per §3.8 unless one is already `OPEN`."
    PRD §3.8: "The sweep also files `INSURANCE_LAPSE` findings automatically when a lease loses coverage, skipping the sublease check and requiring only that the lease is `ACTIVE` or `DELINQUENT`."

    Design: Corner/calculations/insurance_lapse_finding_auto_created_on_certificate_expiry
    """
    ctx = setup_lease(airport_overrides={"airport_code": "KINL", "cure_window_days": 30},
                      size_class="T_HANGAR", rate=90000, hangar_code="T-130",
                      applicant_name="Ike Lapse",
                      insurance_effective_to="2026-08-20T00:00:00Z")
    lease = ctx["lease"]
    validate_success(api_client.create_payment(lease["id"], {"amount_cents": 90000},
                                               make_tenant_headers(lease["id"])))

    set_clock("2026-08-21T00:00:00Z")  # past the certificate's effective_to
    certs, _ = validate_paginated(api_client.list_insurance_certificates(lease["id"],
                                                                         manager_headers))
    assert certs[0]["status"] == "EXPIRED"

    findings = list_audit_findings(lease["id"])
    assert len(findings) == 1
    assert findings[0]["finding_type"] == "INSURANCE_LAPSE"
    assert findings[0]["status"] == "OPEN"
    assert get_lease(lease["id"])["status"] == "CURE_PERIOD"

    # A second sweep must not duplicate the already-OPEN finding.
    set_clock("2026-08-22T00:00:00Z")
    assert len(list_audit_findings(lease["id"])) == 1


def test_cure_insurance_lapse_without_new_certificate_rejected(api, manager_headers):
    """PRD §3.8: "Two finding types carry evidence gates: curing an `INSURANCE_LAPSE` requires a `VALID` certificate covering the current instant (`ERR_INSURANCE_STILL_LAPSED`, HTTP 422), and curing an `ENVIRONMENTAL_LAPSE` requires an `APPROVED` environmental record covering the current instant (`ERR_ENVIRONMENTAL_STILL_LAPSED`, HTTP 422)."

    Design: Corner/validations/cure_insurance_lapse_without_new_certificate_rejected
    """
    ctx = setup_lease(airport_overrides={"airport_code": "KCIN", "cure_window_days": 30},
                      size_class="T_HANGAR", rate=90000, hangar_code="T-180",
                      applicant_name="Cy Ins",
                      insurance_effective_to="2026-08-20T00:00:00Z")
    lease = ctx["lease"]
    tenant = make_tenant_headers(lease["id"])
    validate_success(api_client.create_payment(lease["id"], {"amount_cents": 90000}, tenant))
    set_clock("2026-08-21T00:00:00Z")
    finding = list_audit_findings(lease["id"])[0]

    # No covering VALID certificate exists yet.
    resp = _cure(finding["id"], lease["id"])
    validate_error(resp, ApiErrorId.ERR_INSURANCE_STILL_LAPSED)

    # A new certificate covering the current instant clears the gate.
    validate_success(
        api_client.create_insurance_certificate(
            lease["id"],
            {"insurer_name": "Avemco", "policy_number": "POL-CI2",
             "liability_coverage_cents": 100000000,
             "effective_from": "2026-08-20T00:00:00Z",
             "effective_to": "2027-08-20T00:00:00Z"},
            tenant,
        ),
        expected_status=201,
    )
    cured = validate_success(_cure(finding["id"], lease["id"]))
    assert cured["status"] == "CURED"
    assert get_lease(lease["id"])["status"] == "ACTIVE"


def test_compliance_officer_can_file_finding_and_approve_record(api, manager_headers,
                                                                compliance_headers):
    """PRD §3.7: "A submission enters `PENDING_REVIEW`; a `ComplianceOfficer` then approves or rejects it with a `review_note`, moving the record to `APPROVED` or `REJECTED`."
    PRD §3.8: "A filed finding opens in `OPEN` status with `observed_at` stamped and its `cure_deadline` exactly the airport's `cure_window_days` days later. Filing against an `ACTIVE` lease moves it to `CURE_PERIOD`; filing against a `DELINQUENT` lease leaves it `DELINQUENT` with the finding `OPEN` alongside."

    Design: Corner/rbac/compliance_officer_can_file_finding_and_approve_record
    """
    ctx = setup_lease(airport_overrides={"airport_code": "KRBA"}, size_class="T_HANGAR",
                      rate=90000, hangar_code="T-220", applicant_name="Rae Allow")
    lease = ctx["lease"]
    record = validate_success(
        api_client.create_environmental_record(
            lease["id"],
            create_environmental_record_payload(record_type="STORMWATER_PLAN"),
            make_tenant_headers(lease["id"]),
        ),
        expected_status=201,
    )
    assert record["status"] == "PENDING_REVIEW"

    approved = validate_success(
        api_client.approve_environmental_record(record["id"], {"review_note": "compliant"},
                                                compliance_headers)
    )
    assert approved["status"] == "APPROVED"

    finding = file_finding(lease["id"], "NON_AERONAUTICAL_USE")
    assert finding["status"] == "OPEN"
    assert get_lease(lease["id"])["status"] == "CURE_PERIOD"


def test_tenant_cannot_file_audit_finding_or_approve_environmental(api, manager_headers,
                                                                   tenant_headers):
    """PRD §2.1: "Once the headers are accepted, the named role must be permitted on the target endpoint per the authorization table in §4; otherwise the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
    PRD §4: "| POST | /leases/{id}/audit-findings | File a non-aeronautical-use / compliance audit finding | ComplianceOfficer |"
    PRD §4: "| POST | /environmental-records/{id}/approve | Approve an environmental record | ComplianceOfficer |"

    Design: Corner/rbac/tenant_cannot_file_audit_finding_or_approve_environmental
    """
    ctx = setup_lease(airport_overrides={"airport_code": "KRBD"}, size_class="T_HANGAR",
                      rate=90000, hangar_code="T-210", applicant_name="Ted Nant")
    lease = ctx["lease"]
    record = validate_success(
        api_client.create_environmental_record(
            lease["id"], create_environmental_record_payload(),
            make_tenant_headers(lease["id"]),
        ),
        expected_status=201,
    )

    resp = api_client.file_audit_finding(lease["id"],
                                         {"finding_type": "NON_AERONAUTICAL_USE"},
                                         tenant_headers)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    resp = api_client.approve_environmental_record(record["id"],
                                                   {"review_note": "looks fine"},
                                                   tenant_headers)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
