"""Role gating, ownership scope, segregation of duties and health-note projection.

The API distinguishes four different 403 identities and this module pins each of
them against the principal the PRD does authorise for the very same call:

* a role that is simply not on the endpoint          -> ERR_UNAUTHORIZED
* an entity-backed principal outside its own scope   -> ERR_FORBIDDEN_SCOPE
* a verifier deciding on their own credential        -> ERR_SELF_VERIFICATION_FORBIDDEN
* a reporter reviewing their own incident            -> ERR_SELF_REVIEW_FORBIDDEN

Every ownership-scoped call is made with headers carrying the real entity id, so
a passing test can never be an accident of a shared placeholder identifier.
"""
from prd_bench_local_runner.testing import (
    validate_error,
    validate_success,
)
from test_helpers import CLOCK_START_UTC, TEST_DEFAULTS, TEST_USERS, api_client
from test_helpers import fixtures as scenarios
from test_helpers.api_errors import ApiErrorId
from test_helpers.factories import incident_report_payload
from test_helpers.test_users import (
    make_client_sponsor_headers,
    make_fitness_staff_headers,
    make_member_headers,
    make_site_manager_headers,
)

ADMIN_HEADERS = TEST_USERS["operator_admin_headers"]
AUDITOR_HEADERS = TEST_USERS["compliance_auditor_headers"]

HEALTH_NOTE = "RPE 7, HR avg 138"


# ==========================================================================
# Private composite setups — no shared helper covers these exact shapes.
# ==========================================================================
def _setup_member_awaiting_badge() -> tuple:
    """ACTIVE contract plus one ELIGIBLE EMPLOYEE member holding a SIGNED
    waiver and still sitting at access_status NO_BADGE.

    Returns (scenario, member).
    """
    scenario = scenarios.setup_active_contract()
    member = scenarios.enrol_member(
        scenario, full_name="Iris Okafor", employee_number="E-1001"
    )
    scenarios.verify_member(scenario, member["id"])
    scenarios.file_waiver(scenario, member["id"])
    member = scenarios.read_member(member["id"])
    assert member["eligibility_status"] == "ELIGIBLE", (
        f"setup expected an ELIGIBLE member, got {member['eligibility_status']}"
    )
    assert member["access_status"] == "NO_BADGE", (
        f"setup expected access_status NO_BADGE, got {member['access_status']}"
    )
    return scenario, member


# ==========================================================================
# Badge issuance is operator-side: Member is not on the endpoint at all.
# ==========================================================================
def test_member_granting_own_badge_is_unauthorized(api):
    """PRD §2.1: "When both headers are well-formed but the named role is not
    permitted to invoke the endpoint being called, the request is rejected with
    `ERR_UNAUTHORIZED` (HTTP 403)."

    PRD §4: "Authorization is checked before anything else, so a caller whose
    role does not appear in the last column receives `ERR_UNAUTHORIZED`
    regardless of whether the record exists or the request body is
    well-formed."

    PRD §3.6: "A grant leaves `eligibility_status` unchanged."

    Design: Corner/rbac/member_cannot_grant_own_badge_unauthorized
    """
    scenario, member = _setup_member_awaiting_badge()

    response = api.badge_access(
        member["id"],
        {"action": "GRANT", "badge_number": "BDG-1001"},
        make_member_headers(member["id"]),
    )
    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value)

    after = scenarios.read_member(member["id"])
    assert after["access_status"] == "NO_BADGE", (
        "the badge dimension must not move on a rejected grant, got "
        f"{after['access_status']}"
    )
    assert after["eligibility_status"] == "ELIGIBLE", (
        "the eligibility dimension is independent and must survive the "
        f"rejection, got {after['eligibility_status']}"
    )


def test_site_manager_grants_badge_for_eligible_waivered_member(api):
    """PRD §3.6: "A **grant** takes the member from `NO_BADGE` or from
    `REVOKED` to `ACTIVE`, and is gated twice: the member's
    `eligibility_status` must be `ELIGIBLE`, failing which the request is
    refused with `ERR_ELIGIBILITY_NOT_VERIFIED`; and the member must hold a
    liability waiver in `SIGNED` status whose `expires_on` falls at or after
    today, failing which the request is refused with `ERR_WAIVER_REQUIRED`."

    PRD §3.6: "A grant leaves `eligibility_status` unchanged."

    Design: Corner/rbac/member_cannot_grant_own_badge_unauthorized
    """
    scenario, member = _setup_member_awaiting_badge()

    response = api.badge_access(
        member["id"],
        {"action": "GRANT", "badge_number": "BDG-1001"},
        scenario["manager_headers"],
    )
    granted = validate_success(response)
    assert granted["access_status"] == "ACTIVE", (
        "the site manager is authorised on the badge endpoint, so the grant "
        f"must land the member at ACTIVE, got {granted['access_status']}"
    )
    assert granted["eligibility_status"] == "ELIGIBLE", (
        "granting a badge may not disturb the eligibility dimension, got "
        f"{granted['eligibility_status']}"
    )

    after = scenarios.read_member(member["id"])
    assert after["access_status"] == "ACTIVE", (
        f"expected ACTIVE on re-read after the grant, got {after['access_status']}"
    )


# ==========================================================================
# The sponsor of a different contract is on the endpoint but out of scope.
# ==========================================================================
def _setup_issued_invoice_and_foreign_contract() -> tuple:
    """Contract A taken ACTIVE with its 2026-08 invoice drafted and issued, plus
    a second contract B left in DRAFT so its sponsor is a real but foreign
    principal.

    Returns (scenario_a, contract_b, invoice_a).
    """
    scenario = scenarios.setup_active_contract("COST_PLUS")
    other = scenarios.create_draft_contract("MANAGEMENT_FEE")
    invoice = scenarios.draft_invoice(scenario, "2026-08")
    scenarios.issue_invoice(invoice["id"])
    invoice = scenarios.read_invoice(invoice["id"])
    assert invoice["status"] == "ISSUED", (
        f"setup expected an ISSUED invoice, got {invoice['status']}"
    )
    return scenario, other, invoice


def test_foreign_sponsor_disputing_invoice_is_out_of_scope(api):
    """PRD §2.1: "A scope check runs immediately after the role gate on the
    client contract decision, invoice dispute, invoice payment, member
    eligibility decision, waiver filing, participation check-in,
    staffing-assignment confirmation, and contract utilization-report
    operations: for these eight operations, an entity-backed principal acting
    on a resource it does not own is rejected with `ERR_FORBIDDEN_SCOPE`
    (HTTP 403)."

    PRD §3.9: "**Disputing** is the client's move and requires a non-empty
    `dispute_reason`; only the sponsor of that very contract may do it, as §2.1
    sets out."

    Design: Corner/rbac/client_sponsor_cannot_dispute_another_contracts_invoice_forbidden
    """
    scenario, other, invoice = _setup_issued_invoice_and_foreign_contract()
    ytd_before = scenarios.read_contract(scenario["contract_id"])["ytd_billed_cents"]

    response = api.dispute_invoice(
        invoice["id"],
        {"dispute_reason": "We never approved this month's programming."},
        make_client_sponsor_headers(other["id"]),
    )
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_SCOPE.value)

    after = scenarios.read_invoice(invoice["id"])
    assert after["status"] == "ISSUED", (
        "a rejected dispute must leave the invoice ISSUED, got "
        f"{after['status']}"
    )
    assert after["disputed_at"] is None, (
        f"disputed_at must stay null after the rejection, got {after['disputed_at']}"
    )
    assert (
        scenarios.read_contract(scenario["contract_id"])["ytd_billed_cents"]
        == ytd_before
    ), "the owning contract's year-to-date ledger must not move on a rejected dispute"
    assert scenarios.read_contract(other["id"])["ytd_billed_cents"] == 0, (
        "the foreign sponsor's own contract has never billed anything and must "
        "still read 0"
    )


def test_owning_sponsor_disputes_its_own_issued_invoice(api):
    """PRD §3.9: "It moves the invoice `ISSUED → DISPUTED`, stamps
    `disputed_at`, and **compensates** the ledger by subtracting
    `net_amount_cents` back out of the contract's `ytd_billed_cents`."

    PRD §3.9: "**Disputing** is the client's move and requires a non-empty
    `dispute_reason`; only the sponsor of that very contract may do it, as §2.1
    sets out."

    Design: Corner/rbac/client_sponsor_cannot_dispute_another_contracts_invoice_forbidden
    """
    scenario, other, invoice = _setup_issued_invoice_and_foreign_contract()
    ytd_before = scenarios.read_contract(scenario["contract_id"])["ytd_billed_cents"]

    response = api.dispute_invoice(
        invoice["id"],
        {"dispute_reason": "We never approved this month's programming."},
        make_client_sponsor_headers(scenario["contract_id"]),
    )
    disputed = validate_success(response)
    assert disputed["status"] == "DISPUTED", (
        "the owning sponsor's identical request must succeed, got status "
        f"{disputed['status']}"
    )
    assert disputed["disputed_at"] is not None, "disputed_at must be stamped"
    assert disputed["disputed_at"].startswith("2026-08-01T00:00:00"), (
        "disputed_at is stamped from the logical clock instant, expected "
        f"2026-08-01T00:00:00Z, got {disputed['disputed_at']}"
    )

    ytd_after = scenarios.read_contract(scenario["contract_id"])["ytd_billed_cents"]
    assert ytd_after == ytd_before - disputed["net_amount_cents"], (
        f"expected {ytd_before - disputed['net_amount_cents']}, got {ytd_after} "
        "after the dispute compensated the year-to-date ledger"
    )


# ==========================================================================
# The confirm endpoint is dual-actor and only the FitnessStaff side is
# ownership-scoped.
# ==========================================================================
def _setup_assigned_lead_with_peer_instructor() -> tuple:
    """ACTIVE programme plus a second credentialed instructor, and one session
    on 2026-08-05 carrying an ASSIGNED LEAD row that belongs to the first
    instructor.

    Returns (scenario, peer_staff_id, session, lead_assignment).
    """
    scenario = scenarios.setup_active_program()
    peer = scenarios.add_instructor(scenario, full_name="Mia Chen")
    session = scenarios.schedule_session(
        scenario,
        scheduled_start_utc="2026-08-05T12:00:00Z",
        scheduled_end_utc="2026-08-05T12:55:00Z",
        forecast_attendance=3,
    )
    assignment = scenarios.assign_staff(
        scenario, session["id"], scenario["instructor_id"], role_on_session="LEAD"
    )
    assert assignment["status"] == "ASSIGNED", (
        f"setup expected an ASSIGNED lead row, got {assignment['status']}"
    )
    return scenario, peer["staff"]["id"], scenarios.read_session(session["id"]), assignment


def test_peer_instructor_confirming_another_lead_row_is_out_of_scope(api):
    """PRD §2.1: "When `X-User-Role` is `FitnessStaff`, `X-User-ID` is the `id`
    of the acting staff member record; a staffing assignment may be confirmed by
    a `FitnessStaff` principal only when the assignment's `staff_member_id`
    equals `X-User-ID`."

    PRD §2.1: "A scope check runs immediately after the role gate on the client
    contract decision, invoice dispute, invoice payment, member eligibility
    decision, waiver filing, participation check-in, staffing-assignment
    confirmation, and contract utilization-report operations: for these eight
    operations, an entity-backed principal acting on a resource it does not own
    is rejected with `ERR_FORBIDDEN_SCOPE` (HTTP 403)."

    Design: Corner/rbac/fitness_staff_cannot_confirm_another_staffs_assignment_forbidden
    """
    scenario, peer_staff_id, session, assignment = (
        _setup_assigned_lead_with_peer_instructor()
    )

    response = api.confirm_assignment(
        assignment["id"], make_fitness_staff_headers(peer_staff_id)
    )
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_SCOPE.value)

    after = scenarios.read_assignment(assignment["id"])
    assert after["status"] == "ASSIGNED", (
        "a rejected confirmation must leave the assignment ASSIGNED, got "
        f"{after['status']}"
    )
    assert after["confirmed_at"] is None, (
        f"confirmed_at must stay null after the rejection, got {after['confirmed_at']}"
    )
    session_after = scenarios.read_session(session["id"])
    assert session_after["status"] == "SCHEDULED", (
        "no lead has confirmed, so the session must still be SCHEDULED, got "
        f"{session_after['status']}"
    )


def test_assigned_instructor_confirms_own_lead_row_and_staffs_session(api):
    """PRD §3.5: "Confirmation is the staff member's acknowledgement that they
    will work the session, and it may be performed by the assigned person
    themselves or by their site manager; a `FitnessStaff` principal may confirm
    only their own assignment."

    PRD §3.5: "It moves the assignment `ASSIGNED → CONFIRMED` and stamps
    `confirmed_at` with the current instant."

    PRD §3.5: "When the confirmed assignment is the `LEAD`, the session itself
    advances: `SCHEDULED → STAFFED`, or `STAFFING_AT_RISK → STAFFED` if it was a
    replacement covering an earlier gap."

    Design: Corner/rbac/fitness_staff_cannot_confirm_another_staffs_assignment_forbidden
    """
    scenario, peer_staff_id, session, assignment = (
        _setup_assigned_lead_with_peer_instructor()
    )

    response = api.confirm_assignment(
        assignment["id"], make_fitness_staff_headers(scenario["instructor_id"])
    )
    confirmed = validate_success(response)
    assert confirmed["status"] == "CONFIRMED", (
        "the assigned instructor's identical call must succeed, got status "
        f"{confirmed['status']}"
    )
    assert confirmed["confirmed_at"] is not None, "confirmed_at must be stamped"
    assert confirmed["confirmed_at"].startswith("2026-08-01T00:00:00"), (
        "confirmed_at is stamped with the current logical instant, expected "
        f"2026-08-01T00:00:00Z, got {confirmed['confirmed_at']}"
    )

    session_after = scenarios.read_session(session["id"])
    assert session_after["status"] == "STAFFED", (
        "a confirmed LEAD advances the session, expected STAFFED, got "
        f"{session_after['status']}"
    )


# ==========================================================================
# Segregation of duties: the holder may never decide their own certification.
# ==========================================================================
def _setup_pending_manager_credential() -> tuple:
    """A DRAFT contract with a SITE_MANAGER whose CPR_AED credential is still
    PENDING_VERIFICATION.

    Returns (contract, manager, credential).
    """
    scenarios.set_clock(CLOCK_START_UTC)
    contract = scenarios.create_draft_contract("COST_PLUS")
    manager = scenarios.hire_staff(
        contract["id"],
        role_type="SITE_MANAGER",
        full_name="Dana Reed",
        hourly_cost_cents=TEST_DEFAULTS["MANAGER_HOURLY_COST_CENTS"],
    )
    credential = scenarios.file_credential(
        manager["id"],
        credential_type="CPR_AED",
        issuer="American Heart Association",
        credential_number="AHA-771",
        expires_on=TEST_DEFAULTS["TERM_END_ON"],
    )
    assert credential["status"] == "PENDING_VERIFICATION", (
        "setup expected a PENDING_VERIFICATION credential, got "
        f"{credential['status']}"
    )
    return contract, manager, credential


def test_site_manager_verifying_own_credential_is_self_verification(api):
    """PRD §2.1: "A staff member may never accept or reject their own
    certification: when the acting principal's `X-User-ID` equals the
    credential's `staff_member_id`, the verification decision is refused with
    `ERR_SELF_VERIFICATION_FORBIDDEN` (HTTP 403), regardless of whether the
    acting role would otherwise be permitted to verify credentials."

    PRD §3.2: "A new record lands in `PENDING_VERIFICATION` with
    `renewal_count` at 0, `verified_at` and `verified_by_user_id` null, and
    `rejection_reason` null, and the holder's `readiness_index` is recomputed on
    the spot."

    Design: Corner/rbac/site_manager_cannot_verify_own_credential_forbidden
    """
    contract, manager, credential = _setup_pending_manager_credential()

    response = api.verify_credential(
        credential["id"],
        {"decision": "ACCEPT"},
        make_site_manager_headers(manager["id"]),
    )
    validate_error(response, ApiErrorId.ERR_SELF_VERIFICATION_FORBIDDEN.value)

    after = scenarios.read_credential(credential["id"])
    assert after["status"] == "PENDING_VERIFICATION", (
        "a refused self-verification must leave the record pending, got "
        f"{after['status']}"
    )
    assert after["verified_at"] is None, (
        f"verified_at must stay null after the refusal, got {after['verified_at']}"
    )
    assert after["verified_by_user_id"] is None, (
        "verified_by_user_id must stay null after the refusal, got "
        f"{after['verified_by_user_id']}"
    )


def test_operator_admin_verifies_the_managers_credential(api):
    """PRD §3.2: "An `ACCEPT` moves the record `PENDING_VERIFICATION →
    VERIFIED`, stamps `verified_at` with the logical clock instant and
    `verified_by_user_id` with the deciding principal's identifier, and
    recomputes the holder's `readiness_index`."

    PRD §2.1: "When `X-User-Role` is `OperatorAdmin`, `X-User-ID` is an opaque
    operator identifier not tied to any persisted entity; the server may record
    it for audit purposes (for example as `verified_by_user_id` on a
    certification record or `reviewed_by_user_id` on an incident report) but
    never compares it to any entity's `id`."

    Design: Corner/rbac/site_manager_cannot_verify_own_credential_forbidden
    """
    contract, manager, credential = _setup_pending_manager_credential()

    response = api.verify_credential(
        credential["id"], {"decision": "ACCEPT"}, ADMIN_HEADERS
    )
    verified = validate_success(response)
    assert verified["status"] == "VERIFIED", (
        "the operator has no staff identity to collide with, so the acceptance "
        f"must succeed, got status {verified['status']}"
    )
    assert verified["verified_at"] is not None, "verified_at must be stamped"
    assert verified["verified_at"].startswith("2026-08-01T00:00:00"), (
        "verified_at is stamped with the logical clock instant, expected "
        f"2026-08-01T00:00:00Z, got {verified['verified_at']}"
    )
    assert verified["verified_by_user_id"] == ADMIN_HEADERS["X-User-ID"], (
        f"expected {ADMIN_HEADERS['X-User-ID']} recorded as the deciding "
        f"principal, got {verified['verified_by_user_id']}"
    )


# ==========================================================================
# Segregation of duties: the reporter may never take their own report to review.
# ==========================================================================
def _setup_incident_reported_by_manager() -> tuple:
    """ACTIVE contract with one MINOR / SLIP_FALL incident filed by the site
    manager and still in REPORTED.

    Returns (scenario, incident).
    """
    scenario = scenarios.setup_active_contract()
    incident = validate_success(
        api_client.create_incident_report(
            incident_report_payload(
                scenario["contract_id"],
                scenario["manager_id"],
                occurred_at_utc="2026-07-31T16:05:00Z",
                severity="MINOR",
                cause_category="SLIP_FALL",
                narrative="Member slipped near the fountain; no injury.",
            ),
            scenario["manager_headers"],
        ),
        201,
    )
    assert incident["status"] == "REPORTED", (
        f"setup expected a REPORTED incident, got {incident['status']}"
    )
    return scenario, incident


def test_reporter_reviewing_own_incident_is_self_review(api):
    """PRD §2.1: "Likewise, the staff member who filed an incident report may
    not be the person who takes it into review: when `X-User-ID` equals the
    report's `reported_by_staff_id`, the review is refused with
    `ERR_SELF_REVIEW_FORBIDDEN` (HTTP 403)."

    PRD §3.8: "A new report lands in `REPORTED` with `return_count` at 0 and
    `reviewed_by_user_id`, `claim_reference`, and `closure_note` all null."

    Design: Corner/rbac/site_manager_cannot_review_own_incident_forbidden
    """
    scenario, incident = _setup_incident_reported_by_manager()

    response = api.review_incident(
        incident["id"],
        {"review_note": "Reviewing my own report."},
        make_site_manager_headers(scenario["manager_id"]),
    )
    validate_error(response, ApiErrorId.ERR_SELF_REVIEW_FORBIDDEN.value)

    after = scenarios.read_incident(incident["id"])
    assert after["status"] == "REPORTED", (
        "a refused self-review must leave the report REPORTED, got "
        f"{after['status']}"
    )
    assert after["reviewed_by_user_id"] is None, (
        "reviewed_by_user_id must stay null after the refusal, got "
        f"{after['reviewed_by_user_id']}"
    )


def test_compliance_auditor_takes_the_managers_incident_under_review(api):
    """PRD §3.8: "**Review** moves the report `REPORTED → UNDER_REVIEW` and
    records the reviewer in `reviewed_by_user_id`, optionally alongside a
    `review_note`."

    PRD §3.8: "It enforces **segregation of duties**: the reviewer's
    `X-User-ID` may not equal the report's `reported_by_staff_id`, and a
    self-review is refused with `ERR_SELF_REVIEW_FORBIDDEN` at 403."

    Design: Corner/rbac/site_manager_cannot_review_own_incident_forbidden
    """
    scenario, incident = _setup_incident_reported_by_manager()

    response = api.review_incident(
        incident["id"], {"review_note": "Independent review opened."}, AUDITOR_HEADERS
    )
    reviewed = validate_success(response)
    assert reviewed["status"] == "UNDER_REVIEW", (
        "the auditor's identity can never collide with a staff id, so the "
        f"review must succeed, got status {reviewed['status']}"
    )
    assert reviewed["reviewed_by_user_id"] == AUDITOR_HEADERS["X-User-ID"], (
        f"expected {AUDITOR_HEADERS['X-User-ID']} recorded as the reviewer, got "
        f"{reviewed['reviewed_by_user_id']}"
    )
    assert reviewed["reported_by_staff_id"] == scenario["manager_id"], (
        "the reporter must be unchanged by the review, expected "
        f"{scenario['manager_id']}, got {reviewed['reported_by_staff_id']}"
    )


# ==========================================================================
# The health-note boundary is a projection rule, not an access rule.
# ==========================================================================
def _setup_participation_with_health_note() -> tuple:
    """ACTIVE programme with one IN_PROGRESS session and a consenting member
    checked in by the instructor, carrying a health_metrics_note.

    Returns (scenario, member, record).
    """
    scenario, session, _assignment = scenarios.setup_in_progress_session(
        scheduled_start_utc="2026-08-05T12:00:00Z",
        scheduled_end_utc="2026-08-05T12:55:00Z",
        forecast_attendance=3,
    )
    member = scenarios.setup_ready_member(
        scenario, full_name="Iris Okafor", health_data_consent=True
    )
    record = scenarios.check_in(
        scenario,
        member["id"],
        session["id"],
        headers=scenario["instructor_headers"],
        health_metrics_note=HEALTH_NOTE,
    )
    return scenario, member, record


def test_health_note_is_visible_to_auditor_and_owning_member(api):
    """PRD §2.10: "`ComplianceAuditor` principals see `health_metrics_note` in
    full, and a `Member` principal sees the note on their own records."

    PRD §3.7: "`recorded_by_role` is derived from the caller's role header and
    stores `MEMBER` for a self check-in and `FITNESS_STAFF` for anybody else."

    Design: Corner/rbac/health_note_projection_differs_by_role
    """
    scenario, member, record = _setup_participation_with_health_note()

    auditor_view = validate_success(
        api.get_participation_record(record["id"], AUDITOR_HEADERS)
    )
    assert auditor_view["health_metrics_note"] == HEALTH_NOTE, (
        f"the auditor must see the note in full, expected {HEALTH_NOTE!r}, got "
        f"{auditor_view['health_metrics_note']!r}"
    )

    member_view = validate_success(
        api.get_participation_record(record["id"], make_member_headers(member["id"]))
    )
    assert member_view["health_metrics_note"] == HEALTH_NOTE, (
        "the owning member must see their own note, expected "
        f"{HEALTH_NOTE!r}, got {member_view['health_metrics_note']!r}"
    )

    for label, view in (("auditor", auditor_view), ("owning member", member_view)):
        assert view["status"] == "COUNTED", (
            f"the {label} view must report the record as COUNTED, got "
            f"{view['status']}"
        )
        assert view["recorded_by_role"] == "FITNESS_STAFF", (
            f"the instructor recorded this check-in, so the {label} view must "
            f"report FITNESS_STAFF, got {view['recorded_by_role']}"
        )
    assert auditor_view["points_awarded"] == member_view["points_awarded"], (
        "the two permitted readers must agree on every non-note field, "
        f"got {auditor_view['points_awarded']} and {member_view['points_awarded']} "
        "for points_awarded"
    )


def test_health_note_is_masked_for_staff_and_operator_readers(api):
    """PRD §2.10: "`SiteManager`, `FitnessStaff`, `OperatorAdmin`, and
    `ClientSponsor` principals always receive `health_metrics_note` as null when
    they list participation records or fetch one by identifier — the record is
    still readable, but the note is not."

    PRD §3.7: "The record is written in `COUNTED` status with `check_in_utc`
    stamped from the logical clock, and the member's `last_check_in_utc` is
    updated to the same instant."

    Design: Corner/rbac/health_note_projection_differs_by_role
    """
    scenario, member, record = _setup_participation_with_health_note()

    readers = (
        ("the FitnessStaff who recorded it", scenario["instructor_headers"]),
        ("the SiteManager", scenario["manager_headers"]),
        ("the OperatorAdmin", ADMIN_HEADERS),
    )
    for label, headers in readers:
        view = validate_success(api.get_participation_record(record["id"], headers))
        assert view["health_metrics_note"] is None, (
            f"{label} must receive health_metrics_note as null, got "
            f"{view['health_metrics_note']!r}"
        )
        assert view["status"] == "COUNTED", (
            f"the record stays readable for {label}, expected status COUNTED, "
            f"got {view['status']}"
        )
        assert view["recorded_by_role"] == "FITNESS_STAFF", (
            f"{label} must still see recorded_by_role FITNESS_STAFF, got "
            f"{view['recorded_by_role']}"
        )
        assert view["member_id"] == member["id"], (
            f"{label} must still see the subject member, expected "
            f"{member['id']}, got {view['member_id']}"
        )
