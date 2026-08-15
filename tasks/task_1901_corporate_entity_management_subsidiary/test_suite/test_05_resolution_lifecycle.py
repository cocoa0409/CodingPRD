"""Resolution lifecycle claims: the return-for-revision loop, scheduled
EFFECTIVE materialization, rescission rules, grant-rescission compensation,
and optimistic concurrency on adoption."""
from test_helpers import (
    ApiErrorId,
    FC1,
    SEC1,
    adopt_grant_resolution,
    adopt_resolution,
    appoint_officer,
    create_draft_entity,
    create_grant,
    create_jurisdiction_j1,
    create_officer,
    draft_resolution,
    fetch_entity,
    fetch_entity_version,
    find_officer_appointment,
    list_event_types,
    run_sweep,
    set_clock,
    setup_base_entity,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_resolution_return_revision_cycle_statuses(api):
    """PRD 3.4: "A `CorporateSecretary` may return a `SUBMITTED` resolution to
    `DRAFT` for revision, optionally supplying a `reason`; this loop is
    unbounded."
    PRD 3.4: "Adoption sets `adopted_by_user_id`, transitions the resolution to
    `ADOPTED`, and increments the parent entity's `version`."

    Design: Difficulty/non_linear_state_machine/resolution_return_revision_cycle
    """
    ctx = setup_base_entity(legal_name="Cycle Corp")
    entity, j1 = ctx["entity"], ctx["jurisdiction"]

    resolution = draft_resolution(
        entity["id"], "AUTHORIZE_QUALIFICATION", {"jurisdiction_id": j1["id"]}, "2026-09-01"
    )
    assert resolution["status"] == "DRAFT"
    assert resolution["drafted_by_user_id"] == "fc-01"

    validate_success(api.submit_resolution(resolution["id"], FC1))
    returned = validate_success(
        api.return_resolution(resolution["id"], {"reason": "revise quorum language"}, SEC1)
    )
    assert returned["status"] == "DRAFT", "SUBMITTED -> DRAFT cycle hop traversed"

    validate_success(api.submit_resolution(resolution["id"], FC1))
    version = fetch_entity_version(entity["id"])
    adopted = validate_success(
        api.adopt_resolution(resolution["id"], {"expected_entity_version": version}, SEC1)
    )
    assert adopted["status"] == "ADOPTED"
    assert adopted["adopted_by_user_id"] == "sec-01"
    assert adopted["drafted_by_user_id"] == "fc-01"


def test_resolution_return_revision_cycle_version_increments(api):
    """PRD 2.4: "`version` — an integer that increments by 1 on every mutation
    of the resource."
    PRD 3.4: "A `CorporateSecretary` may return a `SUBMITTED` resolution to
    `DRAFT` for revision, optionally supplying a `reason`; this loop is
    unbounded."

    Design: Difficulty/non_linear_state_machine/resolution_return_revision_cycle
    """
    ctx = setup_base_entity(legal_name="Cycle Corp")
    entity, j1 = ctx["entity"], ctx["jurisdiction"]

    resolution = draft_resolution(
        entity["id"], "AUTHORIZE_QUALIFICATION", {"jurisdiction_id": j1["id"]}, "2026-09-01"
    )
    v0 = resolution["version"]

    submitted = validate_success(api.submit_resolution(resolution["id"], FC1))
    assert submitted["version"] == v0 + 1, "submit is a mutation"
    returned = validate_success(api.return_resolution(resolution["id"], {"reason": "r"}, SEC1))
    assert returned["version"] == v0 + 2, "return is a mutation, not a no-op"
    resubmitted = validate_success(api.submit_resolution(resolution["id"], FC1))
    assert resubmitted["version"] == v0 + 3

    version = fetch_entity_version(entity["id"])
    adopted = validate_success(
        api.adopt_resolution(resolution["id"], {"expected_entity_version": version}, SEC1)
    )
    assert adopted["version"] == v0 + 4, "adopt is a mutation"


def test_withdrawn_resolution_terminal(api):
    """PRD 3.4: "A `DRAFT` resolution may be withdrawn, transitioning to
    `WITHDRAWN`."
    PRD 3.4: "Submitting a resolution transitions it from `DRAFT` to
    `SUBMITTED`."
    PRD 5: ERR_RESOLUTION_NOT_DRAFT maps to HTTP 409.

    Design: Corner/state_machines/withdrawn_resolution_terminal
    """
    j1 = create_jurisdiction_j1()
    entity = create_draft_entity(j1["id"], legal_name="Drafty Corp", authorized_shares=None)
    resolution = draft_resolution(
        entity["id"], "AUTHORIZE_QUALIFICATION", {"jurisdiction_id": j1["id"]}, "2026-09-01"
    )
    validate_success(api.withdraw_resolution(resolution["id"], FC1))

    response = api.submit_resolution(resolution["id"], FC1)
    validate_error(response, ApiErrorId.ERR_RESOLUTION_NOT_DRAFT)

    current = validate_success(api.get_resolution(resolution["id"], FC1))
    assert current["status"] == "WITHDRAWN"


def test_resolution_effective_materialization_at_date(api):
    """PRD 3.4: "The resolution then waits for the logical clock to reach its
    `effective_date`. When that occurs — either via a system sweep or lazy
    evaluation on read — the resolution transitions from `ADOPTED` to
    `EFFECTIVE` and its payload materializes. An `APPOINT_OFFICER` resolution
    creates the appointment."
    PRD 3.5: "When an `APPOINT_OFFICER` resolution becomes `EFFECTIVE`, the
    system creates an `OfficerAppointment` with the `officer_id`,
    `office_title`, and `start_date` drawn from the resolution's `payload`, and
    records the originating `resolution_id`. The appointment begins in
    `APPOINTED` status with `end_date` null."

    Design: Corner/state_machines/resolution_effective_materialization_at_date
    """
    ctx = setup_base_entity(legal_name="Deferred Corp")
    entity = ctx["entity"]
    officer = create_officer()

    resolution = adopt_resolution(
        entity["id"],
        "APPOINT_OFFICER",
        {"officer_id": officer["id"], "office_title": "PRESIDENT", "start_date": "2026-09-01"},
        "2026-09-01",
    )
    assert resolution["status"] == "ADOPTED"

    run_sweep()
    staged = validate_success(api.get_resolution(resolution["id"], SEC1))
    assert staged["status"] == "ADOPTED", "effective_date 2026-09-01 is still in the future"
    rows = validate_paginated(
        api.list_officer_appointments(SEC1, params={"entity_id": entity["id"]})
    )[0]
    assert rows == [], "no appointment materializes before the effective date"

    set_clock("2026-09-01T00:00:00Z")
    run_sweep()
    effective = validate_success(api.get_resolution(resolution["id"], SEC1))
    assert effective["status"] == "EFFECTIVE"

    appointment = find_officer_appointment(entity["id"], officer["id"])
    assert appointment["officer_id"] == officer["id"]
    assert appointment["office_title"] == "PRESIDENT"
    assert appointment["status"] == "APPOINTED"
    assert appointment["start_date"] == "2026-09-01"
    assert appointment["resolution_id"] == resolution["id"]
    assert appointment["end_date"] is None


def test_scheduled_resolution_rescinded_before_effective(api):
    """PRD 3.4: "An `ADOPTED` or `EFFECTIVE` resolution may be rescinded by a
    `CorporateSecretary`."
    PRD 3.4: "When that occurs — either via a system sweep or lazy evaluation
    on read — the resolution transitions from `ADOPTED` to `EFFECTIVE` and its
    payload materializes."

    Design: Corner/cross_cutting_layers/scheduled_resolution_rescinded_before_effective
    """
    ctx = setup_base_entity(legal_name="Cancel Corp")
    entity = ctx["entity"]
    officer = create_officer()

    resolution = adopt_resolution(
        entity["id"],
        "APPOINT_OFFICER",
        {"officer_id": officer["id"], "office_title": "PRESIDENT", "start_date": "2026-09-01"},
        "2026-09-01",
    )
    rescinded = validate_success(
        api.rescind_resolution(
            resolution["id"],
            {"reason": "board withdrew the appointment before it took effect"},
            SEC1,
        )
    )
    assert rescinded["status"] == "RESCINDED"

    set_clock("2026-09-02T00:00:00Z")
    run_sweep()

    current = validate_success(api.get_resolution(resolution["id"], SEC1))
    assert current["status"] == "RESCINDED", (
        "RESCINDED is terminal; the EFFECTIVE transition fires only from ADOPTED"
    )
    rows = validate_paginated(
        api.list_officer_appointments(SEC1, params={"entity_id": entity["id"]})
    )[0]
    assert rows == [], "no appointment was ever created"


def test_rescind_effective_formation_resolution_rejected(api):
    """PRD 3.4: "Rescission of an `EFFECTIVE` resolution is permitted only for
    `APPOINT_OFFICER` and `GRANT_SIGNATURE_AUTHORITY`; other types are rejected
    with `ERR_RESOLUTION_NOT_RESCINDABLE`."

    Design: Corner/errors/rescind_effective_formation_resolution_rejected
    """
    ctx = setup_base_entity(legal_name="Norescind Corp")
    entity = ctx["entity"]
    # The base chain's AUTHORIZE_FORMATION resolution materializes to EFFECTIVE
    # at the default clock (its effective_date 2025-06-15 has passed).
    run_sweep()
    rows = validate_paginated(
        api.list_resolutions(
            SEC1, params={"entity_id": entity["id"], "resolution_type": "AUTHORIZE_FORMATION"}
        )
    )[0]
    assert len(rows) == 1 and rows[0]["status"] == "EFFECTIVE"
    formation_resolution = rows[0]

    response = api.rescind_resolution(
        formation_resolution["id"], {"reason": "attempt to unwind formation"}, SEC1
    )
    validate_error(response, ApiErrorId.ERR_RESOLUTION_NOT_RESCINDABLE)

    current = validate_success(api.get_resolution(formation_resolution["id"], SEC1))
    assert current["status"] == "EFFECTIVE"
    assert fetch_entity(entity["id"])["status"] == "ACTIVE"


def test_grant_rescission_revokes_sourced_grants(api):
    """PRD 3.4: "Rescission of an `EFFECTIVE` resolution is permitted only for
    `APPOINT_OFFICER` and `GRANT_SIGNATURE_AUTHORITY`; other types are rejected
    with `ERR_RESOLUTION_NOT_RESCINDABLE`."
    PRD 3.4: "Rescinding any `GRANT_SIGNATURE_AUTHORITY` resolution revokes
    every grant whose `source_resolution_id` matches, including delegated
    grants."

    Design: Difficulty/compensating_invariant/grant_rescission_restores_authority_ledger
    """
    ctx = setup_base_entity(legal_name="Rescind Corp")
    entity = ctx["entity"]
    officer = create_officer()
    appoint_officer(entity["id"], officer["id"])
    grant_resolution = adopt_grant_resolution(entity["id"], officer["id"], "CONTRACTS")
    run_sweep()  # the grant resolution materializes to EFFECTIVE
    grant = create_grant(
        entity["id"], officer["id"], with_resolution=False, max_amount_cents=90000
    )
    assert grant["source_resolution_id"] == grant_resolution["id"]

    rescinded = validate_success(
        api.rescind_resolution(
            grant_resolution["id"], {"reason": "board reversed the delegation policy"}, SEC1
        )
    )
    assert rescinded["status"] == "RESCINDED"

    revoked = validate_success(api.get_signature_grant(grant["id"], SEC1))
    assert revoked["status"] == "REVOKED", (
        "compensation matched by source_resolution_id"
    )


def test_grant_rescission_restores_active_grant_baseline(api):
    """PRD 3.4: "Rescinding any `GRANT_SIGNATURE_AUTHORITY` resolution revokes
    every grant whose `source_resolution_id` matches, including delegated
    grants."
    PRD 3.14: "Every significant mutation appends a `ComplianceEvent` to the
    entity's audit trail."

    Design: Difficulty/compensating_invariant/grant_rescission_restores_authority_ledger
    """
    ctx = setup_base_entity(legal_name="Rescind Corp")
    entity = ctx["entity"]
    officer = create_officer()
    appoint_officer(entity["id"], officer["id"])
    grant_resolution = adopt_grant_resolution(entity["id"], officer["id"], "CONTRACTS")
    run_sweep()
    create_grant(entity["id"], officer["id"], with_resolution=False, max_amount_cents=90000)

    validate_success(
        api.rescind_resolution(grant_resolution["id"], {"reason": "reversed"}, SEC1)
    )

    active, meta = validate_paginated(
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
    assert meta["total_count"] == 0 and active == [], (
        "forward + compensating pair conserves the ACTIVE-grant count at 0"
    )
    assert "GRANT_REVOKED" in list_event_types(entity["id"])


def test_occ_stale_version_on_adopt(api):
    """PRD 2.7: "Adopting a resolution requires the request body to carry
    `expected_entity_version`, which must equal the current `version` of the
    parent `LegalEntity`. A mismatch is rejected with `ERR_STALE_VERSION`
    (HTTP 412)."
    PRD 3.4: "Adoption sets `adopted_by_user_id`, transitions the resolution to
    `ADOPTED`, and increments the parent entity's `version`."

    Design: Corner/cross_cutting_layers/occ_stale_version_on_adopt
    """
    ctx = setup_base_entity(legal_name="OCC Corp")
    entity, j1 = ctx["entity"], ctx["jurisdiction"]

    r2 = draft_resolution(
        entity["id"], "AUTHORIZE_QUALIFICATION", {"jurisdiction_id": j1["id"]}, "2026-09-01"
    )
    validate_success(api.submit_resolution(r2["id"], FC1))
    r3 = draft_resolution(entity["id"], "AUTHORIZE_DISSOLUTION", {}, "2026-12-01")
    validate_success(api.submit_resolution(r3["id"], FC1))

    version_a = fetch_entity_version(entity["id"])
    # Adopting R3 against the observed version succeeds and bumps the version.
    adopted_r3 = validate_success(
        api.adopt_resolution(r3["id"], {"expected_entity_version": version_a}, SEC1)
    )
    assert adopted_r3["status"] == "ADOPTED"
    assert fetch_entity_version(entity["id"]) == version_a + 1

    # R2's adoption now carries a stale version.
    stale = api.adopt_resolution(r2["id"], {"expected_entity_version": version_a}, SEC1)
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION)
    r2_now = validate_success(api.get_resolution(r2["id"], SEC1))
    assert r2_now["status"] == "SUBMITTED"

    # Re-issued with the fresh version it succeeds.
    version_b = fetch_entity_version(entity["id"])
    adopted_r2 = validate_success(
        api.adopt_resolution(r2["id"], {"expected_entity_version": version_b}, SEC1)
    )
    assert adopted_r2["status"] == "ADOPTED"
