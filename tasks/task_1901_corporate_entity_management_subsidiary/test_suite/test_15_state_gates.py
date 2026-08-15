"""State-gate claims across every machine: the adopt-time state/SoD priority
pair, single-holder offices, deactivated officers, the not-found sweep across
all resources, entity lifecycle gates, and the remaining qualification /
certificate / resolution / filing / delegation state errors."""
import pytest

from test_helpers import (
    ABSENT_UUID,
    FC1,
    SEC1,
    ApiErrorId,
    adopt_grant_resolution,
    adopt_resolution,
    appoint_agent,
    appoint_officer,
    create_agent,
    create_draft_entity,
    create_grant,
    create_grant_payload,
    create_jurisdiction_j1,
    create_jurisdiction_nv,
    create_officer,
    create_qualification_payload,
    draft_resolution,
    fetch_entity,
    fetch_entity_version,
    find_filing,
    prepare_filing,
    request_certificate,
    setup_base_entity,
    submit_filing,
    validate_error,
    validate_success,
)


def test_adopt_state_gate_fires_before_segregation(api):
    """PRD 2.10: "State-machine preconditions are evaluated fifth. Compliance
    gates and segregation-of-duties checks are sixth."
    PRD 3.4: "First, the resolution must be in `SUBMITTED` status; otherwise
    the request is rejected with `ERR_RESOLUTION_NOT_SUBMITTED`. ... Third, the
    adopter must differ from the drafter; a match is rejected with
    `ERR_SEGREGATION_OF_DUTIES`."

    Design: Difficulty/priority_pair_validation_conflict/adopt_state_before_segregation
    """
    ctx = setup_base_entity(legal_name="Priority One Corp")
    entity, j1 = ctx["entity"], ctx["jurisdiction"]
    # Drafted by a secretary and left in DRAFT; the adopt attempt is by the
    # same user, so the segregation check would also fail — but the state gate
    # (fifth) is evaluated before segregation of duties (sixth).
    resolution = draft_resolution(
        entity["id"], "AUTHORIZE_QUALIFICATION", {"jurisdiction_id": j1["id"]},
        "2026-09-01", drafter=SEC1,
    )

    response = api.adopt_resolution(
        resolution["id"],
        {"expected_entity_version": fetch_entity_version(entity["id"])},
        SEC1,
    )
    error = validate_error(response, ApiErrorId.ERR_RESOLUTION_NOT_SUBMITTED)
    assert response.status_code == 409
    assert error["error_id"] != "ERR_SEGREGATION_OF_DUTIES"

    current = validate_success(api.get_resolution(resolution["id"], SEC1))
    assert current["status"] == "DRAFT"


def test_adopt_state_gate_also_wins_for_withdrawn_resolution(api):
    """PRD 2.10: "State-machine preconditions are evaluated fifth. Compliance
    gates and segregation-of-duties checks are sixth."
    PRD 3.4: "First, the resolution must be in `SUBMITTED` status; otherwise
    the request is rejected with `ERR_RESOLUTION_NOT_SUBMITTED`."

    Design: Difficulty/priority_pair_validation_conflict/adopt_state_before_segregation
    """
    ctx = setup_base_entity(legal_name="Priority One Corp")
    entity, j1 = ctx["entity"], ctx["jurisdiction"]
    resolution = draft_resolution(
        entity["id"], "AUTHORIZE_QUALIFICATION", {"jurisdiction_id": j1["id"]},
        "2026-09-01", drafter=SEC1,
    )
    validate_success(api.withdraw_resolution(resolution["id"], SEC1))

    # WITHDRAWN is not SUBMITTED; the adopter also equals the drafter.
    response = api.adopt_resolution(
        resolution["id"],
        {"expected_entity_version": fetch_entity_version(entity["id"])},
        SEC1,
    )
    validate_error(response, ApiErrorId.ERR_RESOLUTION_NOT_SUBMITTED)

    current = validate_success(api.get_resolution(resolution["id"], SEC1))
    assert current["status"] == "WITHDRAWN"


def test_office_occupied_rejected_at_adopt(api):
    """PRD 3.5: "The titles `PRESIDENT`, `SECRETARY`, and `TREASURER` are
    single-holder offices: adopting an `APPOINT_OFFICER` resolution for one of
    these titles fails with `ERR_OFFICE_OCCUPIED` if another appointment of the
    same title at the same entity is already `APPOINTED`."

    Design: Corner/errors/office_occupied_rejected_at_adopt
    """
    ctx = setup_base_entity(legal_name="Onechair Corp")
    entity = ctx["entity"]
    o1 = create_officer(full_name="Olivia Ortiz", email="oo@example.com")
    o2 = create_officer(full_name="CFO Carl", email="carl@example.com")
    appoint_officer(entity["id"], o1["id"], office_title="PRESIDENT")

    resolution = draft_resolution(
        entity["id"],
        "APPOINT_OFFICER",
        {"officer_id": o2["id"], "office_title": "PRESIDENT", "start_date": "2026-09-01"},
        "2026-09-01",
    )
    validate_success(api.submit_resolution(resolution["id"], FC1))

    response = api.adopt_resolution(
        resolution["id"],
        {"expected_entity_version": fetch_entity_version(entity["id"])},
        SEC1,
    )
    validate_error(response, ApiErrorId.ERR_OFFICE_OCCUPIED)

    current = validate_success(api.get_resolution(resolution["id"], SEC1))
    assert current["status"] == "SUBMITTED"


def test_deactivated_officer_blocks_appointment_adopt(api):
    """PRD 3.1: "A `CorporateSecretary` may deactivate an officer,
    transitioning `status` to `DEACTIVATED`; deactivation does not alter
    existing appointments but blocks future `APPOINT_OFFICER` resolutions from
    being adopted for that officer."
    PRD 3.4: "For `APPOINT_OFFICER` resolutions, the referenced officer must be
    `ACTIVE` and, for single-holder titles, the office must not already be
    occupied."
    PRD 5: ERR_OFFICER_NOT_ACTIVE maps to HTTP 409.

    Design: Corner/errors/deactivated_officer_blocks_appointment_adopt
    """
    ctx = setup_base_entity(legal_name="Inactive Corp")
    entity = ctx["entity"]
    officer = create_officer()
    validate_success(api.deactivate_officer(officer["id"], SEC1))

    resolution = draft_resolution(
        entity["id"],
        "APPOINT_OFFICER",
        {"officer_id": officer["id"], "office_title": "DIRECTOR", "start_date": "2026-01-01"},
        "2026-01-01",
    )
    validate_success(api.submit_resolution(resolution["id"], FC1))

    response = api.adopt_resolution(
        resolution["id"],
        {"expected_entity_version": fetch_entity_version(entity["id"])},
        SEC1,
    )
    validate_error(response, ApiErrorId.ERR_OFFICER_NOT_ACTIVE)

    current = validate_success(api.get_resolution(resolution["id"], SEC1))
    assert current["status"] == "SUBMITTED"


NOT_FOUND_PROBES = [
    ("jurisdiction", ApiErrorId.ERR_JURISDICTION_NOT_FOUND),
    ("registered_agent", ApiErrorId.ERR_AGENT_NOT_FOUND),
    ("officer", ApiErrorId.ERR_OFFICER_NOT_FOUND),
    ("officer_appointment", ApiErrorId.ERR_APPOINTMENT_NOT_FOUND),
    ("resolution", ApiErrorId.ERR_RESOLUTION_NOT_FOUND),
    ("filing", ApiErrorId.ERR_FILING_NOT_FOUND),
    ("qualification", ApiErrorId.ERR_QUALIFICATION_NOT_FOUND),
    ("signature_grant", ApiErrorId.ERR_GRANT_NOT_FOUND),
    ("certificate", ApiErrorId.ERR_CERTIFICATE_NOT_FOUND),
    ("ownership_record", ApiErrorId.ERR_OWNERSHIP_RECORD_NOT_FOUND),
]


@pytest.mark.parametrize("resource,error_id", NOT_FOUND_PROBES, ids=[p[0] for p in NOT_FOUND_PROBES])
def test_all_resource_get_not_found_sweep(api, resource, error_id):
    """PRD 2.5: "When an endpoint path contains multiple resource identifiers,
    the system validates each identifier from left to right. The request is
    rejected with a 404 error for the first identifier that does not resolve to
    an existing resource."
    PRD 5: each resource's ERR_*_NOT_FOUND maps to HTTP 404.

    Design: Corner/errors/all_resource_get_not_found_sweep
    """
    getter = getattr(api, f"get_{resource}")
    response = getter(ABSENT_UUID, SEC1)
    validate_error(response, error_id)
    assert response.status_code == 404


def test_entity_lifecycle_state_gate_errors(api):
    """PRD 3.2: "This step requires an `AUTHORIZE_FORMATION` resolution in
    `ADOPTED` or `EFFECTIVE` status; otherwise the request is rejected with
    `ERR_REQUIRED_RESOLUTION_MISSING`."
    PRD 3.2: "The system requires an `AgentAppointment` covering the entity's
    formation jurisdiction with status `ACTIVE` or `NOTICE_PENDING` and a
    `start_date` on or before the current logical date; absence of coverage is
    rejected with `ERR_AGENT_COVERAGE_GAP`."
    PRD 3.2: "Attempting to submit formation on an entity that is not in
    `DRAFT` is rejected with `ERR_ENTITY_NOT_DRAFT`."
    PRD 3.12: "Attempting to revoke from a non-`DISSOLUTION_PENDING` status is
    rejected with `ERR_ENTITY_NOT_DISSOLUTION_PENDING`."

    Design: Corner/errors/entity_lifecycle_state_gate_errors
    """
    j1 = create_jurisdiction_j1()
    ag1 = create_agent(j1["id"])

    # E3: bare DRAFT — no authorizing resolution at all.
    e3 = create_draft_entity(j1["id"], legal_name="Gatethree Corp", authorized_shares=None)
    missing_resolution = api.submit_formation(e3["id"], SEC1)
    validate_error(missing_resolution, ApiErrorId.ERR_REQUIRED_RESOLUTION_MISSING)

    # E2: adopted formation resolution but no agent coverage.
    e2 = create_draft_entity(j1["id"], legal_name="Gatetwo Corp", authorized_shares=None)
    adopt_resolution(e2["id"], "AUTHORIZE_FORMATION", {}, "2025-06-15")
    validate_success(api.submit_formation(e2["id"], SEC1))
    no_coverage = api.confirm_formation(e2["id"], SEC1)
    validate_error(no_coverage, ApiErrorId.ERR_AGENT_COVERAGE_GAP)

    # E1: full coverage — first submit succeeds, the second hits the state gate.
    e1 = create_draft_entity(j1["id"], legal_name="Gateone Corp", authorized_shares=None)
    appoint_agent(e1["id"], ag1["id"], j1["id"])
    adopt_resolution(e1["id"], "AUTHORIZE_FORMATION", {}, "2025-06-15")
    validate_success(api.submit_formation(e1["id"], SEC1))
    not_draft = api.submit_formation(e1["id"], SEC1)
    validate_error(not_draft, ApiErrorId.ERR_ENTITY_NOT_DRAFT)

    # Revoking a dissolution from FORMATION_PENDING hits the state gate.
    not_pending = api.revoke_dissolution(e1["id"], SEC1)
    validate_error(not_pending, ApiErrorId.ERR_ENTITY_NOT_DISSOLUTION_PENDING)


def test_qualification_certificate_resolution_state_gates(api):
    """PRD 3.8: "Attempting to commence withdrawal on a non-`QUALIFIED`
    qualification is rejected with `ERR_QUALIFICATION_NOT_QUALIFIED`."
    PRD 3.8: "Attempting to confirm a non-`PENDING` qualification is rejected
    with `ERR_QUALIFICATION_NOT_PENDING`."
    PRD 3.10: "Attempting to issue or deny a non-`REQUESTED` certificate is
    rejected with `ERR_CERTIFICATE_NOT_REQUESTED`."
    PRD 3.4: "An `ADOPTED` or `EFFECTIVE` resolution may be rescinded by a
    `CorporateSecretary`."
    PRD 3.10: "Upon issuance, `issued_date` is set to the current logical date
    and `valid_until` is set to `issued_date` plus 90 calendar days."

    Design: Corner/errors/qualification_certificate_resolution_state_gates
    """
    ctx = setup_base_entity(legal_name="Gates Corp")
    entity, j1 = ctx["entity"], ctx["jurisdiction"]
    j3 = create_jurisdiction_nv()
    ag3 = create_agent(j3["id"], name="NV Agent Co", address="9 Agent Rd")
    aa3 = appoint_agent(entity["id"], ag3["id"], j3["id"], start_date="2026-06-01")
    adopt_resolution(
        entity["id"], "AUTHORIZE_QUALIFICATION", {"jurisdiction_id": j3["id"]}, "2026-06-01"
    )
    qualification = validate_success(
        api.create_qualification(
            entity["id"], create_qualification_payload(j3["id"], aa3["id"]), SEC1
        ),
        201,
    )
    cert = request_certificate(entity["id"], j1["id"], "STANDARD")
    draft_only = draft_resolution(entity["id"], "AUTHORIZE_DISSOLUTION", {}, "2027-01-01")

    # Commence-withdrawal from PENDING.
    not_qualified = api.commence_withdrawal(qualification["id"], SEC1)
    validate_error(not_qualified, ApiErrorId.ERR_QUALIFICATION_NOT_QUALIFIED)

    # Confirm works once; the second confirm hits the state gate.
    confirmed = validate_success(api.confirm_qualification(qualification["id"], SEC1))
    assert confirmed["status"] == "QUALIFIED"
    not_pending = api.confirm_qualification(qualification["id"], SEC1)
    validate_error(not_pending, ApiErrorId.ERR_QUALIFICATION_NOT_PENDING)

    # Issue works once; the second issue hits the state gate.
    issued = validate_success(api.issue_certificate(cert["id"], SEC1))
    assert issued["status"] == "ISSUED"
    assert issued["valid_until"] == "2026-10-30"
    not_requested = api.issue_certificate(cert["id"], SEC1)
    validate_error(not_requested, ApiErrorId.ERR_CERTIFICATE_NOT_REQUESTED)

    # Rescind requires ADOPTED or EFFECTIVE; a DRAFT resolution is neither.
    not_adopted = api.rescind_resolution(draft_only["id"], {"reason": "too early"}, SEC1)
    validate_error(not_adopted, ApiErrorId.ERR_RESOLUTION_NOT_ADOPTED)
    current = validate_success(api.get_resolution(draft_only["id"], SEC1))
    assert current["status"] == "DRAFT"


def test_formation_pending_dissolution_blocked_delegator_invalid(api):
    """PRD 3.2: "Confirming formation transitions the entity from
    `FORMATION_PENDING` to `ACTIVE`."
    PRD 5: ERR_ENTITY_NOT_FORMATION_PENDING maps to HTTP 409.
    PRD 3.12: "Finalization is blocked if any filing is in `SCHEDULED`,
    `PREPARED`, `OVERDUE`, `SUBMITTED`, or `REJECTED` status, or if any
    certificate is in `REQUESTED` status; such requests are rejected with
    `ERR_DISSOLUTION_BLOCKED`."
    PRD 3.12: "Commencement withdraws all `SCHEDULED` and `PREPARED` filings"
    PRD 3.9: "The delegator must be a direct grant — delegation depth is at
    most 2 — and must be `ACTIVE`. ... Violations are rejected with
    `ERR_DELEGATION_DEPTH_EXCEEDED`, `ERR_DELEGATOR_GRANT_INVALID`,
    `ERR_DELEGATOR_WINDOW_INSUFFICIENT`, or `ERR_DELEGATION_LIMIT_EXCEEDED`
    respectively."

    Design: Corner/errors/formation_pending_dissolution_blocked_delegator_invalid
    """
    ctx = setup_base_entity(legal_name="Blocked Corp")
    entity, j1 = ctx["entity"], ctx["jurisdiction"]
    o1 = create_officer(full_name="Olivia Ortiz", email="oo@example.com")
    o2 = create_officer(full_name="CFO Carl", email="carl@example.com")
    appoint_officer(entity["id"], o1["id"], office_title="PRESIDENT")
    appoint_officer(entity["id"], o2["id"], office_title="CFO")
    g1 = create_grant(entity["id"], o1["id"], max_amount_cents=100000)
    adopt_grant_resolution(entity["id"], o2["id"], "CONTRACTS")

    # Submit the FRANCHISE_TAX filing so it survives commencement (only
    # SCHEDULED/PREPARED filings withdraw) and blocks finalization.
    filing = find_filing(entity["id"], filing_type="FRANCHISE_TAX", period_year=2026)
    prepare_filing(filing["id"])
    submit_filing(filing["id"])

    adopt_resolution(entity["id"], "AUTHORIZE_DISSOLUTION", {}, "2026-08-01")
    validate_success(api.commence_dissolution(entity["id"], SEC1))
    validate_success(api.suspend_grant(g1["id"], SEC1))

    e2 = create_draft_entity(j1["id"], legal_name="Draft E2 Corp", authorized_shares=None)

    # 1) Confirm-formation requires FORMATION_PENDING; E2 is DRAFT.
    not_pending = api.confirm_formation(e2["id"], SEC1)
    validate_error(not_pending, ApiErrorId.ERR_ENTITY_NOT_FORMATION_PENDING)

    # 2) Finalize with the SUBMITTED filing outstanding is blocked.
    blocked = api.finalize_dissolution(entity["id"], SEC1)
    validate_error(blocked, ApiErrorId.ERR_DISSOLUTION_BLOCKED)
    assert fetch_entity(entity["id"])["status"] == "DISSOLUTION_PENDING"

    # 3) The delegator is SUSPENDED, not ACTIVE.
    invalid_delegator = api.create_signature_grant(
        entity["id"],
        create_grant_payload(
            o2["id"], "CONTRACTS", 50000, "2026-03-01", "2026-12-01",
            delegated_from_grant_id=g1["id"],
        ),
        SEC1,
    )
    validate_error(invalid_delegator, ApiErrorId.ERR_DELEGATOR_GRANT_INVALID)


def test_patch_non_active_entity_rejected(api):
    """PRD 3.2: "While an entity is `ACTIVE`, a `CorporateSecretary` may update
    `legal_name`, `authorized_shares`, or `fiscal_year_end_month` via a
    modification request."
    PRD 3.2: "Attempting to modify a non-`ACTIVE` entity is rejected with
    `ERR_ENTITY_NOT_ACTIVE`."

    Design: Corner/validations/patch_non_active_entity_rejected
    """
    j1 = create_jurisdiction_j1()
    entity = create_draft_entity(j1["id"], legal_name="Patchme Corp", authorized_shares=None)

    response = api.patch_entity(entity["id"], {"authorized_shares": 25000}, SEC1)
    validate_error(response, ApiErrorId.ERR_ENTITY_NOT_ACTIVE)

    current = fetch_entity(entity["id"])
    assert current["authorized_shares"] == 0, "the rejected PATCH changed nothing"
    assert current["version"] == 1
