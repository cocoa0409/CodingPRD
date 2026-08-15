"""Signature grant rule claims: half-open expiry, revoke cascade to delegated
grants, delegation depth/window/limit violations, state gates, the empty
verify read, segregation of duties on reinstatement, and immediate
read-after-write."""
from test_helpers import (
    AUD1,
    FC1,
    SEC1,
    SEC2,
    ApiErrorId,
    adopt_grant_resolution,
    appoint_officer,
    create_draft_entity,
    create_grant,
    create_grant_payload,
    create_jurisdiction_j1,
    create_officer,
    create_verify_payload,
    find_filing,
    list_event_types,
    make_officer_headers,
    run_sweep,
    set_clock,
    setup_base_entity,
    setup_entity_with_officer_and_grant,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_grant_expiry_half_open_window_end(api):
    """PRD 3.9: "The grant's validity window is half-open: it includes
    `effective_date` and excludes `expiry_date`."
    PRD 3.9: "A grant also transitions to `EXPIRED` when the logical clock
    reaches its `expiry_date`."
    PRD 3.15: "The sweep response reports `filings_marked_overdue`,
    `resolutions_made_effective`, `resolutions_blocked`, `grants_expired`,
    `certificates_expired`, `certificates_auto_denied`, and `posture_changes`."

    Design: Corner/state_machines/grant_expiry_half_open_window_end
    """
    set_clock("2026-07-31T00:00:00Z")
    ctx = setup_entity_with_officer_and_grant(
        legal_name="Expiry Corp", effective_date="2026-01-01", expiry_date="2026-08-01"
    )
    grant = ctx["grant"]
    assert grant["status"] == "ACTIVE", "one day before expiry the window still covers"

    set_clock("2026-08-01T00:00:00Z")  # == expiry_date: window end is exclusive
    report = run_sweep()
    assert report["grants_expired"] == 1

    current = validate_success(api.get_signature_grant(grant["id"], SEC1))
    assert current["status"] == "EXPIRED"


def test_grant_revoke_cascades_to_delegated_grant(api):
    """PRD 3.9: "Revocation transitions a grant from `ACTIVE` or `SUSPENDED` to
    `REVOKED` and cascades to any grants that delegate from it."
    PRD 3.9: "Given `entity_id`, `officer_id`, `scope`, `amount_cents`, and
    `as_of_date`, the system identifies the single `ACTIVE` grant matching the
    entity, officer, and scope whose half-open window covers `as_of_date`. If
    none exists, the result is unauthorized with `effective_limit_cents` of 0."
    PRD 3.14: "Every significant mutation appends a `ComplianceEvent` to the
    entity's audit trail."

    Design: Corner/errors/grant_revoke_cascades_to_delegated_grant
    """
    ctx = setup_base_entity(legal_name="Revoke Corp")
    entity = ctx["entity"]
    o1 = create_officer(full_name="Olivia Ortiz", email="oo@example.com")
    o2 = create_officer(full_name="CFO Carl", email="carl@example.com")
    appoint_officer(entity["id"], o1["id"], office_title="PRESIDENT")
    appoint_officer(entity["id"], o2["id"], office_title="CFO")
    g1 = create_grant(entity["id"], o1["id"], max_amount_cents=100000)
    g2 = create_grant(
        entity["id"], o2["id"], max_amount_cents=80000,
        effective_date="2026-03-01", expiry_date="2026-12-31",
        delegated_from_grant_id=g1["id"],
    )

    revoked = validate_success(
        api.revoke_grant(g1["id"], {"reason": "authority review"}, SEC1)
    )
    assert revoked["status"] == "REVOKED"

    cascaded = validate_success(api.get_signature_grant(g2["id"], SEC1))
    assert cascaded["status"] == "REVOKED", "delegated grants revoke with the delegator"

    denied = validate_success(
        api.verify_signature(
            create_verify_payload(entity["id"], o2["id"], "CONTRACTS", 1000, "2026-08-01"),
            SEC1,
        )
    )
    assert denied["authorized"] is False
    assert denied["effective_limit_cents"] == 0

    events = list_event_types(entity["id"])
    assert events.count("GRANT_REVOKED") == 2, "one audit event per revoked grant"


def _setup_two_officers_with_direct_grant():
    """Entity with PRESIDENT O1 and CFO O2 appointed and grant resolutions
    adopted for (O1, CONTRACTS) and (O2, CONTRACTS); G1 direct O1/100000."""
    ctx = setup_base_entity(legal_name="Depth Corp")
    entity = ctx["entity"]
    o1 = create_officer(full_name="Olivia Ortiz", email="oo@example.com")
    o2 = create_officer(full_name="CFO Carl", email="carl@example.com")
    appoint_officer(entity["id"], o1["id"], office_title="PRESIDENT")
    appoint_officer(entity["id"], o2["id"], office_title="CFO")
    g1 = create_grant(entity["id"], o1["id"], max_amount_cents=100000)
    adopt_grant_resolution(entity["id"], o2["id"], "CONTRACTS")
    return ctx, o1, o2, g1


def test_delegation_depth_exceeded_rejected(api):
    """PRD 3.9: "The delegator must be a direct grant — delegation depth is at
    most 2 — and must be `ACTIVE`. The delegated grant's window must be
    contained within the delegator's window, and its `max_amount_cents` must
    not exceed the delegator's `max_amount_cents`. Violations are rejected with
    `ERR_DELEGATION_DEPTH_EXCEEDED`, `ERR_DELEGATOR_GRANT_INVALID`,
    `ERR_DELEGATOR_WINDOW_INSUFFICIENT`, or `ERR_DELEGATION_LIMIT_EXCEEDED`
    respectively."

    Design: Corner/errors/delegation_depth_exceeded_rejected
    """
    ctx, o1, o2, g1 = _setup_two_officers_with_direct_grant()
    entity = ctx["entity"]
    g2 = create_grant(
        entity["id"], o2["id"], max_amount_cents=80000,
        effective_date="2026-03-01", expiry_date="2026-12-31",
        delegated_from_grant_id=g1["id"],
    )
    # G2 is itself delegated, so delegating from it would create depth 3.
    adopt_grant_resolution(entity["id"], o2["id"], "BANKING")
    response = api.create_signature_grant(
        entity["id"],
        create_grant_payload(
            o2["id"], "BANKING", 5000, "2026-06-01", "2026-09-01",
            delegated_from_grant_id=g2["id"],
        ),
        SEC1,
    )
    validate_error(response, ApiErrorId.ERR_DELEGATION_DEPTH_EXCEEDED)

    rows, meta = validate_paginated(
        api.list_signature_grants(SEC1, params={"entity_id": entity["id"]})
    )
    assert meta["total_count"] == 2, "the depth-3 grant was not created"


def test_delegator_window_containment_rejected(api):
    """PRD 3.9: "The delegated grant's window must be contained within the
    delegator's window, and its `max_amount_cents` must not exceed the
    delegator's `max_amount_cents`. Violations are rejected with
    `ERR_DELEGATION_DEPTH_EXCEEDED`, `ERR_DELEGATOR_GRANT_INVALID`,
    `ERR_DELEGATOR_WINDOW_INSUFFICIENT`, or `ERR_DELEGATION_LIMIT_EXCEEDED`
    respectively."

    Design: Corner/errors/delegator_window_containment_rejected
    """
    ctx, o1, o2, g1 = _setup_two_officers_with_direct_grant()
    entity = ctx["entity"]
    # [2026-06-01, 2027-06-01) is not contained in the delegator's
    # [2026-01-01, 2027-01-01): the expiry runs past it.
    response = api.create_signature_grant(
        entity["id"],
        create_grant_payload(
            o2["id"], "CONTRACTS", 50000, "2026-06-01", "2027-06-01",
            delegated_from_grant_id=g1["id"],
        ),
        SEC1,
    )
    validate_error(response, ApiErrorId.ERR_DELEGATOR_WINDOW_INSUFFICIENT)


def test_delegation_limit_exceeded_rejected(api):
    """PRD 3.9: "The delegated grant's window must be contained within the
    delegator's window, and its `max_amount_cents` must not exceed the
    delegator's `max_amount_cents`. Violations are rejected with
    `ERR_DELEGATION_DEPTH_EXCEEDED`, `ERR_DELEGATOR_GRANT_INVALID`,
    `ERR_DELEGATOR_WINDOW_INSUFFICIENT`, or `ERR_DELEGATION_LIMIT_EXCEEDED`
    respectively."

    Design: Corner/errors/delegation_limit_exceeded_rejected
    """
    ctx, o1, o2, g1 = _setup_two_officers_with_direct_grant()
    entity = ctx["entity"]
    # Window contained, no overlap, depth valid — only the cap is violated.
    response = api.create_signature_grant(
        entity["id"],
        create_grant_payload(
            o2["id"], "CONTRACTS", 150000, "2026-03-01", "2026-12-01",
            delegated_from_grant_id=g1["id"],
        ),
        SEC1,
    )
    validate_error(response, ApiErrorId.ERR_DELEGATION_LIMIT_EXCEEDED)


def test_filing_and_grant_state_gate_errors(api):
    """PRD 3.6: "Attempting to submit from any other status is rejected with
    `ERR_FILING_NOT_PREPARED`."
    PRD 3.9: "Attempting to reinstate a non-`SUSPENDED` grant is rejected with
    `ERR_GRANT_NOT_SUSPENDED`."
    PRD 3.9: "Attempting to suspend a non-`ACTIVE` grant is rejected with
    `ERR_GRANT_NOT_ACTIVE`."
    PRD 3.9: "Attempting to revoke a grant that is already terminal is rejected
    with `ERR_GRANT_ALREADY_TERMINAL`."

    Design: Corner/errors/filing_and_grant_state_gate_errors
    """
    ctx = setup_entity_with_officer_and_grant(legal_name="Gates2 Corp")
    entity, grant = ctx["entity"], ctx["grant"]
    filing = find_filing(entity["id"], filing_type="FRANCHISE_TAX", period_year=2026)

    # Submit from SCHEDULED (never prepared).
    premature_submit = api.submit_filing(filing["id"], FC1)
    validate_error(premature_submit, ApiErrorId.ERR_FILING_NOT_PREPARED)

    # Reinstate from ACTIVE.
    premature_reinstate = api.reinstate_grant(grant["id"], SEC1)
    validate_error(premature_reinstate, ApiErrorId.ERR_GRANT_NOT_SUSPENDED)

    # Suspend; a second suspend hits the state gate.
    suspended = validate_success(api.suspend_grant(grant["id"], SEC1))
    assert suspended["status"] == "SUSPENDED"
    double_suspend = api.suspend_grant(grant["id"], SEC2)
    validate_error(double_suspend, ApiErrorId.ERR_GRANT_NOT_ACTIVE)

    # Revoke from SUSPENDED; a second revoke hits the terminal gate.
    revoked = validate_success(api.revoke_grant(grant["id"], {"reason": "retire"}, SEC1))
    assert revoked["status"] == "REVOKED"
    double_revoke = api.revoke_grant(grant["id"], {"reason": "again"}, SEC1)
    validate_error(double_revoke, ApiErrorId.ERR_GRANT_ALREADY_TERMINAL)


def test_verify_without_any_grant_unauthorized(api):
    """PRD 3.9: "If none exists, the result is unauthorized with
    `effective_limit_cents` of 0."

    Design: Corner/endpoints/verify_without_any_grant_unauthorized
    """
    j1 = create_jurisdiction_j1()
    entity = create_draft_entity(j1["id"], legal_name="Nogrant Corp", authorized_shares=None)
    officer = create_officer()

    result = validate_success(
        api.verify_signature(
            create_verify_payload(entity["id"], officer["id"], "BANKING", 1, "2026-08-01"),
            make_officer_headers(officer["id"]),
        )
    )
    assert result["authorized"] is False
    assert result["effective_limit_cents"] == 0


def test_sod_suspender_cannot_reinstate(api):
    """PRD 3.9: "Reinstatement is performed by a `CorporateSecretary` who must
    differ from the suspender; it clears `suspended_by_user_id` and returns the
    grant to `ACTIVE`."
    PRD 2.9: "The same `X-User-ID` may not perform both sides of any of these
    pairs; violations are rejected with `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/rbac/sod_suspender_cannot_reinstate
    """
    ctx = setup_entity_with_officer_and_grant(legal_name="Suspend Corp")
    grant = ctx["grant"]
    validate_success(api.suspend_grant(grant["id"], SEC1))

    same_user = api.reinstate_grant(grant["id"], SEC1)
    validate_error(same_user, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
    current = validate_success(api.get_signature_grant(grant["id"], SEC1))
    assert current["status"] == "SUSPENDED"

    reinstated = validate_success(api.reinstate_grant(grant["id"], SEC2))
    assert reinstated["status"] == "ACTIVE"
    assert reinstated["suspended_by_user_id"] is None


def test_immediate_read_after_write_on_grant_create(api):
    """PRD 1: "All monetary amounts are expressed in integer cents, all dates
    are ISO calendar dates, and every mutation is immediately visible in the
    response of the same request."
    PRD 3.9: "A `GRANT_SIGNATURE_AUTHORITY` resolution in `ADOPTED` or
    `EFFECTIVE` status must exist; the grant records its `source_resolution_id`.
    The grant begins in `ACTIVE` status."

    Design: Corner/consistency_model/immediate_read_after_write_on_grant_create
    """
    ctx = setup_base_entity(legal_name="Immediate Corp")
    entity = ctx["entity"]
    officer = create_officer()
    appoint_officer(entity["id"], officer["id"])
    grant_resolution = adopt_grant_resolution(entity["id"], officer["id"], "CONTRACTS")

    created = validate_success(
        api.create_signature_grant(
            entity["id"],
            create_grant_payload(officer["id"], "CONTRACTS", 100000, "2026-01-01", "2027-01-01"),
            SEC1,
        ),
        201,
    )
    assert created["status"] == "ACTIVE"
    assert created["source_resolution_id"] == grant_resolution["id"]

    fetched = validate_success(api.get_signature_grant(created["id"], AUD1))
    assert fetched["status"] == created["status"]
    assert fetched["version"] == created["version"], "no eventual lag between write and read"

    allowed = validate_success(
        api.verify_signature(
            create_verify_payload(entity["id"], officer["id"], "CONTRACTS", 100000, "2026-08-01"),
            FC1,
        )
    )
    assert allowed["authorized"] is True, "the fresh grant already authorizes at the limit"
    assert allowed["effective_limit_cents"] == 100000
