"""Signature grant depth claims: the suspend/reinstate cycle observed through
verify, the inclusive amount boundary, half-open window adjacency, the
appointed-officer gate, and the overlap-vs-limit priority pair."""
from test_helpers import (
    AUD1,
    SEC1,
    ApiErrorId,
    adopt_grant_resolution,
    appoint_officer,
    create_grant,
    create_grant_payload,
    create_officer,
    create_verify_payload,
    make_officer_headers,
    setup_base_entity,
    setup_entity_with_officer_and_grant,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import api_client


def test_grant_suspend_reinstate_cycle_observed_via_verify(api):
    """PRD 3.9: "Suspension is performed by a `ComplianceAuditor` or
    `CorporateSecretary` and transitions the grant from `ACTIVE` to
    `SUSPENDED`, recording `suspended_by_user_id`."
    PRD 3.9: "Given `entity_id`, `officer_id`, `scope`, `amount_cents`, and
    `as_of_date`, the system identifies the single `ACTIVE` grant matching the
    entity, officer, and scope whose half-open window covers `as_of_date`. If
    none exists, the result is unauthorized with `effective_limit_cents` of 0."
    PRD 3.9: "Reinstatement ... returns the grant to `ACTIVE`."

    Design: Difficulty/non_linear_state_machine/grant_suspend_reinstate_cycle
    """
    ctx = setup_entity_with_officer_and_grant(legal_name="Grantloop Inc")
    entity, officer, grant = ctx["entity"], ctx["officer"], ctx["grant"]

    suspended = validate_success(api.suspend_grant(grant["id"], AUD1))
    assert suspended["status"] == "SUSPENDED"

    denied = validate_success(
        api.verify_signature(
            create_verify_payload(entity["id"], officer["id"], "CONTRACTS", 50000, "2026-08-01"),
            SEC1,
        )
    )
    assert denied["authorized"] is False, "SUSPENDED grants leave the candidate set"
    assert denied["effective_limit_cents"] == 0

    reinstated = validate_success(api.reinstate_grant(grant["id"], SEC1))
    assert reinstated["status"] == "ACTIVE"

    allowed = validate_success(
        api.verify_signature(
            create_verify_payload(entity["id"], officer["id"], "CONTRACTS", 50000, "2026-08-01"),
            SEC1,
        )
    )
    assert allowed["authorized"] is True
    assert allowed["effective_limit_cents"] == 100000


def test_grant_suspend_reinstate_records_and_clears_suspender(api):
    """PRD 3.9: "Suspension is performed by a `ComplianceAuditor` or
    `CorporateSecretary` and transitions the grant from `ACTIVE` to
    `SUSPENDED`, recording `suspended_by_user_id`."
    PRD 3.9: "Reinstatement is performed by a `CorporateSecretary` who must
    differ from the suspender; it clears `suspended_by_user_id` and returns the
    grant to `ACTIVE`."

    Design: Difficulty/non_linear_state_machine/grant_suspend_reinstate_cycle
    """
    ctx = setup_entity_with_officer_and_grant(legal_name="Grantloop Inc")
    grant = ctx["grant"]

    suspended = validate_success(api.suspend_grant(grant["id"], AUD1))
    assert suspended["suspended_by_user_id"] == "aud-01"

    reinstated = validate_success(api.reinstate_grant(grant["id"], SEC1))
    assert reinstated["status"] == "ACTIVE"
    assert reinstated["suspended_by_user_id"] is None


def test_verify_amount_at_limit_authorized(api):
    """PRD 3.9: "Authorization is granted when `effective_limit_cents` is
    greater than 0 and `amount_cents` is less than or equal to
    `effective_limit_cents`; equality is authorized."
    PRD 3.9: "If the grant is direct, `effective_limit_cents` is its
    `max_amount_cents`."

    Design: Difficulty/boundary_precision_check/signature_amount_at_limit
    """
    ctx = setup_entity_with_officer_and_grant(
        legal_name="Limit Corp", max_amount_cents=80000
    )
    entity, officer = ctx["entity"], ctx["officer"]

    result = validate_success(
        api.verify_signature(
            create_verify_payload(entity["id"], officer["id"], "CONTRACTS", 80000, "2026-08-01"),
            SEC1,
        )
    )
    assert result["authorized"] is True, "amount == limit is authorized (inclusive <=)"
    assert result["effective_limit_cents"] == 80000


def test_verify_amount_one_cent_over_limit_unauthorized(api):
    """PRD 3.9: "Authorization is granted when `effective_limit_cents` is
    greater than 0 and `amount_cents` is less than or equal to
    `effective_limit_cents`; equality is authorized."

    Design: Difficulty/boundary_precision_check/signature_amount_at_limit
    """
    ctx = setup_entity_with_officer_and_grant(
        legal_name="Limit Corp", max_amount_cents=80000
    )
    entity, officer = ctx["entity"], ctx["officer"]

    result = validate_success(
        api.verify_signature(
            create_verify_payload(entity["id"], officer["id"], "CONTRACTS", 80001, "2026-08-01"),
            SEC1,
        )
    )
    assert result["authorized"] is False
    assert result["effective_limit_cents"] == 80000, (
        "the limit is still reported; only the comparison flips"
    )


def test_grant_window_adjacency_permitted(api):
    """PRD 3.9: "No two grants for the same entity, officer, and scope may have
    overlapping windows among `ACTIVE` and `SUSPENDED` statuses; adjacency —
    where one grant's `expiry_date` equals another's `effective_date` — is
    permitted."
    PRD 3.9: "The grant's validity window is half-open: it includes
    `effective_date` and excludes `expiry_date`."

    Design: Difficulty/resource_temporal_overlap/grant_window_half_open_adjacency
    """
    ctx = setup_entity_with_officer_and_grant(legal_name="Window Corp")
    entity, officer = ctx["entity"], ctx["officer"]
    # Incumbent G1: [2026-01-01, 2027-01-01). The successor starts exactly at
    # the incumbent's exclusive expiry — half-open windows are disjoint.
    adjacent = validate_success(
        api.create_signature_grant(
            entity["id"],
            create_grant_payload(officer["id"], "CONTRACTS", 60000, "2027-01-01", "2028-01-01"),
            SEC1,
        ),
        201,
    )
    assert adjacent["status"] == "ACTIVE"


def test_grant_window_overlap_rejected(api):
    """PRD 3.9: "No two grants for the same entity, officer, and scope may have
    overlapping windows among `ACTIVE` and `SUSPENDED` statuses; adjacency —
    where one grant's `expiry_date` equals another's `effective_date` — is
    permitted. Overlaps are rejected with `ERR_GRANT_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/grant_window_half_open_adjacency
    """
    ctx = setup_entity_with_officer_and_grant(legal_name="Window Corp")
    entity, officer = ctx["entity"], ctx["officer"]
    validate_success(
        api.create_signature_grant(
            entity["id"],
            create_grant_payload(officer["id"], "CONTRACTS", 60000, "2027-01-01", "2028-01-01"),
            SEC1,
        ),
        201,
    )

    # [2026-12-15, 2027-02-01) starts 17 days before the incumbent's expiry.
    overlap = api.create_signature_grant(
        entity["id"],
        create_grant_payload(officer["id"], "CONTRACTS", 30000, "2026-12-15", "2027-02-01"),
        SEC1,
    )
    validate_error(overlap, ApiErrorId.ERR_GRANT_WINDOW_OVERLAP)

    rows, meta = validate_paginated(
        api.list_signature_grants(
            SEC1,
            params={
                "entity_id": entity["id"],
                "officer_id": officer["id"],
                "scope": "CONTRACTS",
                "status": "ACTIVE",
            },
        )
    )
    assert meta["total_count"] == 2, "only the incumbent and the adjacent grant exist"


def _setup_resigned_officer_with_grant_resolution():
    """ACTIVE entity whose only officer was appointed PRESIDENT and then
    self-resigned; an ADOPTED GRANT_SIGNATURE_AUTHORITY resolution still stands."""
    ctx = setup_base_entity(legal_name="Roster Corp")
    entity = ctx["entity"]
    officer = create_officer()
    appointment = appoint_officer(entity["id"], officer["id"])
    resigned = validate_success(
        api_client.resign_officer_appointment(
            appointment["id"], make_officer_headers(officer["id"])
        )
    )
    assert resigned["status"] == "RESIGNED"
    adopt_grant_resolution(entity["id"], officer["id"], "CONTRACTS")
    return ctx, officer


def test_grant_requires_officer_appointed(api):
    """PRD 3.9: "The officer must hold an `APPOINTED` appointment at the
    entity; otherwise the request is rejected with `ERR_OFFICER_NOT_APPOINTED`."
    PRD 3.5: "Resignation transitions the appointment from `APPOINTED` to
    `RESIGNED`, sets `end_date` to the current logical date."

    Design: Difficulty/cross_entity_state_dependency/grant_requires_officer_appointed
    """
    ctx, officer = _setup_resigned_officer_with_grant_resolution()
    entity = ctx["entity"]

    response = api.create_signature_grant(
        entity["id"],
        create_grant_payload(officer["id"], "CONTRACTS", 50000, "2026-02-01", "2027-01-01"),
        SEC1,
    )
    validate_error(response, ApiErrorId.ERR_OFFICER_NOT_APPOINTED)


def test_grant_requires_officer_appointed_leaves_no_grants(api):
    """PRD 3.9: "The officer must hold an `APPOINTED` appointment at the
    entity; otherwise the request is rejected with `ERR_OFFICER_NOT_APPOINTED`."
    PRD 3.9: "A `GRANT_SIGNATURE_AUTHORITY` resolution in `ADOPTED` or
    `EFFECTIVE` status must exist; the grant records its
    `source_resolution_id`."

    Design: Difficulty/cross_entity_state_dependency/grant_requires_officer_appointed
    """
    ctx, officer = _setup_resigned_officer_with_grant_resolution()
    entity = ctx["entity"]

    response = api.create_signature_grant(
        entity["id"],
        create_grant_payload(officer["id"], "CONTRACTS", 50000, "2026-02-01", "2027-01-01"),
        SEC1,
    )
    validate_error(response, ApiErrorId.ERR_OFFICER_NOT_APPOINTED)

    rows, meta = validate_paginated(
        api.list_signature_grants(SEC1, params={"entity_id": entity["id"]})
    )
    assert meta["total_count"] == 0 and rows == []

    # The failing gate is the appointment's state, not the resolution: the
    # authorizing resolution still stands in an adopted/effective status.
    resolutions, _ = validate_paginated(
        api.list_resolutions(
            SEC1,
            params={"entity_id": entity["id"], "resolution_type": "GRANT_SIGNATURE_AUTHORITY"},
        )
    )
    assert len(resolutions) == 1
    assert resolutions[0]["status"] in ("ADOPTED", "EFFECTIVE")


def _setup_overlap_vs_limit():
    """Entity with PRESIDENT O1 and CFO O2 appointed; G1 direct O1/100000 and
    G2a direct O2/50000/[2026-02-01, 2026-12-01)."""
    ctx = setup_base_entity(legal_name="Priority Two Corp")
    entity = ctx["entity"]
    o1 = create_officer(full_name="Olivia Ortiz", email="oo@example.com")
    o2 = create_officer(full_name="CFO Carl", email="carl@example.com")
    appoint_officer(entity["id"], o1["id"], office_title="PRESIDENT")
    appoint_officer(entity["id"], o2["id"], office_title="CFO")
    g1 = create_grant(entity["id"], o1["id"], max_amount_cents=100000)
    g2a = create_grant(
        entity["id"], o2["id"], max_amount_cents=50000,
        effective_date="2026-02-01", expiry_date="2026-12-01",
    )
    return ctx, o1, o2, g1, g2a


def test_overlap_fires_before_delegation_limit(api):
    """PRD 2.10: "Uniqueness and structural constraints — such as duplicate
    officer emails, overlapping grant windows, and ownership cycles — are
    eighth."
    PRD 2.10: "Monetary and aggregate caps are evaluated last (priority 10)."
    PRD 3.9: "Overlaps are rejected with `ERR_GRANT_WINDOW_OVERLAP`."

    Design: Difficulty/priority_pair_validation_conflict/grant_overlap_before_delegation_limit
    """
    ctx, o1, o2, g1, g2a = _setup_overlap_vs_limit()
    entity = ctx["entity"]

    # This request violates both the window overlap (against G2a, priority 8)
    # and the delegation cap (200000 > delegator's 100000, priority 10).
    response = api.create_signature_grant(
        entity["id"],
        create_grant_payload(
            o2["id"], "CONTRACTS", 200000, "2026-06-01", "2026-09-01",
            delegated_from_grant_id=g1["id"],
        ),
        SEC1,
    )
    error = validate_error(response, ApiErrorId.ERR_GRANT_WINDOW_OVERLAP)
    assert response.status_code == 409
    assert error["error_id"] != "ERR_DELEGATION_LIMIT_EXCEEDED", (
        "the structural check (eighth) wins over the fiscal cap (tenth)"
    )


def test_overlap_rejection_creates_no_grant(api):
    """PRD 2.10: "Uniqueness and structural constraints — such as duplicate
    officer emails, overlapping grant windows, and ownership cycles — are
    eighth."
    PRD 2.10: "Monetary and aggregate caps are evaluated last (priority 10)."
    PRD 3.9: "Overlaps are rejected with `ERR_GRANT_WINDOW_OVERLAP`."

    Design: Difficulty/priority_pair_validation_conflict/grant_overlap_before_delegation_limit
    """
    ctx, o1, o2, g1, g2a = _setup_overlap_vs_limit()
    entity = ctx["entity"]

    response = api.create_signature_grant(
        entity["id"],
        create_grant_payload(
            o2["id"], "CONTRACTS", 200000, "2026-06-01", "2026-09-01",
            delegated_from_grant_id=g1["id"],
        ),
        SEC1,
    )
    validate_error(response, ApiErrorId.ERR_GRANT_WINDOW_OVERLAP)

    rows, meta = validate_paginated(
        api.list_signature_grants(
            SEC1, params={"entity_id": entity["id"], "officer_id": o2["id"]}
        )
    )
    assert meta["total_count"] == 1, "the rejected delegated grant was not created"
    incumbent = validate_success(api.get_signature_grant(g1["id"], SEC1))
    assert incumbent["status"] == "ACTIVE", "the delegator is untouched"
