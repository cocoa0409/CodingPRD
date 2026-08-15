"""Characterization verification, eligibility determination lifecycle, permits."""
from test_helpers import (
    CO_APPR_USER_ID,
    TEST_USERS,
    ApiErrorId,
    create_characterization,
    create_characterized_stream,
    create_eligibility_payload,
    create_generator,
    create_state_permit_payload,
    create_stream,
    file_and_approve_eligibility,
    file_eligibility,
    set_logical_clock,
    submit_eligibility,
    validate_error,
    validate_paginated,
    validate_success,
)

BROKER = TEST_USERS["broker_ops_headers"]
CO_FILE = TEST_USERS["compliance_officer_file_headers"]
CO_APPR = TEST_USERS["compliance_officer_approve_headers"]


def test_characterization_verify_bubbles_stream_to_characterized(api):
    """PRD §3.1: "A `BrokerOps` operator may verify a submitted profile, moving
    it from `SUBMITTED` to `VERIFIED`; when that happens and the owning stream
    is still in `DRAFT`, the stream bubbles up to `CHARACTERIZED`, refreshing
    its `updated_at` and incrementing its `version`."

    Design: Corner/state_machines/characterization_verify_bubbles_stream_to_characterized
    """
    generator = create_generator()
    stream = create_stream(generator["id"], material_type="SLAG",
                           declared_moisture_pct=5.0, expected_tons_per_month=300)
    characterization = create_characterization(stream["id"], generator["id"])
    assert characterization["status"] == "SUBMITTED"

    verified = validate_success(
        api.verify_characterization(characterization["id"], BROKER), 200
    )
    assert verified["status"] == "VERIFIED"

    stream_after = validate_success(api.get_stream(stream["id"], BROKER), 200)
    assert (
        stream_after["status"] == "CHARACTERIZED"
    ), f"stream must bubble to CHARACTERIZED, got {stream_after['status']}"


def test_filing_without_verified_characterization_returns_error(api):
    """PRD §3.2: "Filing is refused with `ERR_STREAM_NOT_CHARACTERIZED` unless
    at least one characterization profile of the stream has reached `VERIFIED`."

    Design: Corner/validations/filing_without_verified_characterization_returns_error
    """
    generator = create_generator()
    stream = create_stream(generator["id"])
    # Characterization exists but stays SUBMITTED (never verified).
    create_characterization(stream["id"], generator["id"])

    resp = api.create_eligibility_determination(
        stream["id"], create_eligibility_payload(), CO_FILE
    )
    validate_error(resp, ApiErrorId.ERR_STREAM_NOT_CHARACTERIZED)


def test_same_officer_cannot_approve_own_filing(api):
    """PRD §3.2: "Approval moves a determination from `SUBMITTED` to `APPROVED`
    and is only valid when the acting officer's `X-User-ID` differs from the
    determination's `filed_by_user_id` — an officer approving their own filing
    is rejected with `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/validations/same_officer_cannot_approve_own_filing_returns_segregation_error
    """
    base = create_characterized_stream()
    determination = file_eligibility(base["stream"]["id"])
    submit_eligibility(determination["id"])

    # The filer (co_file) cannot approve their own filing.
    resp = api.approve_eligibility(determination["id"], CO_FILE)
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    # A different officer can approve.
    approved = validate_success(api.approve_eligibility(determination["id"], CO_APPR), 200)
    assert approved["status"] == "APPROVED"


def test_approve_with_past_valid_until_returns_error(api):
    """PRD §3.2: "Approval additionally requires `valid_until` to still be after
    the current logical date, else `ERR_ELIGIBILITY_WINDOW_PAST`"

    Design: Corner/validations/approve_with_past_valid_until_returns_error
    """
    base = create_characterized_stream()
    determination = file_eligibility(
        base["stream"]["id"], valid_from="2026-01-01", valid_until="2026-07-01"
    )
    submit_eligibility(determination["id"])

    # Logical clock is the default 2026-08-01, already past valid_until.
    resp = api.approve_eligibility(determination["id"], CO_APPR)
    validate_error(resp, ApiErrorId.ERR_ELIGIBILITY_WINDOW_PAST)

    dets, _ = validate_paginated(
        api.list_eligibility_determinations(base["stream"]["id"], BROKER)
    )
    assert dets[0]["status"] == "SUBMITTED", "failed approve must leave the determination SUBMITTED"


def test_suspend_expired_determination_returns_invalid_state(api):
    """PRD §2.4: "A reuse-eligibility determination in `APPROVED` or `SUSPENDED`
    status whose `valid_until` date has been reached or passed by the current
    logical date transitions to `EXPIRED`, which is terminal."
    PRD §2.10: "Eighth, state eligibility: the requested transition must be
    declared from the target resource's current state — attempting any action
    from a state where it is not defined, including any terminal state, yields
    `ERR_INVALID_STATE`"

    Design: Corner/state_machines/suspend_expired_determination_returns_invalid_state
    """
    base = create_characterized_stream(material_type="GYPSUM")
    determination = file_and_approve_eligibility(
        base["stream"]["id"],
        state_code="OH",
        use_case="SOIL_AMENDMENT",
        valid_from="2026-01-01",
        valid_until="2026-08-10",
    )
    set_logical_clock("2026-08-11T00:00:00Z")

    resp = api.suspend_eligibility(determination["id"], CO_FILE)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_permit_lifecycle_filed_active_revoked(api):
    """PRD §3.2: "A filed permit starts in `FILED` status."
    PRD §3.2: "Activation moves a permit from `FILED` to `ACTIVE`; revocation
    moves it from `ACTIVE` to the terminal `REVOKED` state"

    Design: Corner/state_machines/permit_lifecycle_filed_active_revoked
    """
    resp = api.create_state_permit(
        create_state_permit_payload(
            state_code="WV",
            material_type="SLAG",
            regime="NOTIFICATION",
            permit_number="WV-9",
        ),
        CO_FILE,
    )
    permit = validate_success(resp, 201)
    assert permit["status"] == "FILED"

    activated = validate_success(api.activate_state_permit(permit["id"], CO_FILE), 200)
    assert activated["status"] == "ACTIVE"

    revoked = validate_success(api.revoke_state_permit(permit["id"], CO_FILE), 200)
    assert revoked["status"] == "REVOKED"


def test_duplicate_permit_for_state_material_returns_error(api):
    """PRD §3.2: "The registry enforces uniqueness per pair: at most one permit
    with status `FILED` or `ACTIVE` may exist for a given state and material
    combination, so filing a second such permit — or activating a permit while
    another `FILED` or `ACTIVE` permit exists for the pair — is rejected with
    `ERR_DUPLICATE_PERMIT`."

    Design: Corner/validations/duplicate_permit_for_state_material_returns_error
    """
    first = validate_success(api.create_state_permit(create_state_permit_payload(), CO_FILE), 201)
    assert first["status"] == "FILED"

    resp = api.create_state_permit(
        create_state_permit_payload(
            regime="NOTIFICATION", permit_number="PA-002", issued_on="2026-02-01"
        ),
        CO_FILE,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_PERMIT)


def test_deny_revise_resubmit_approve_cycle(api):
    """PRD §3.2: "A denied determination is not dead: revision returns it from
    `DENIED` to `DRAFT`, clearing both `decision_reason` and
    `approved_by_user_id` so the officer can rework the window or use case and
    resubmit through the same pipeline."
    PRD §3.2: "On approval, the approver's id is stamped as
    `approved_by_user_id`, and when the owning stream is still `CHARACTERIZED`
    it bubbles up to `ACTIVE`, refreshing `updated_at` and incrementing
    `version`."

    Design: Difficulty/non_linear_state_machine/eligibility_deny_revise_and_suspend_reinstate_cycles
    """
    base = create_characterized_stream(material_type="GYPSUM")
    stream_id = base["stream"]["id"]
    determination = file_eligibility(
        stream_id, state_code="OH", use_case="SOIL_AMENDMENT"
    )
    submit_eligibility(determination["id"])

    denied = validate_success(
        api.deny_eligibility(determination["id"], {"reason": "insufficient data"}, CO_APPR),
        200,
    )
    assert denied["status"] == "DENIED"
    assert denied["decision_reason"] == "insufficient data"

    revised = validate_success(api.revise_eligibility(determination["id"], CO_FILE), 200)
    assert revised["status"] == "DRAFT"
    assert revised["decision_reason"] is None, "revise must clear decision_reason"

    resubmitted = validate_success(api.submit_eligibility(determination["id"], CO_FILE), 200)
    assert resubmitted["status"] == "SUBMITTED"

    approved = validate_success(api.approve_eligibility(determination["id"], CO_APPR), 200)
    assert approved["status"] == "APPROVED"
    assert (
        approved["approved_by_user_id"] == CO_APPR_USER_ID
    ), "approver id must be stamped as approved_by_user_id"

    stream_after = validate_success(api.get_stream(stream_id, BROKER), 200)
    assert (
        stream_after["status"] == "ACTIVE"
    ), "first APPROVED determination must bubble the stream CHARACTERIZED -> ACTIVE"


def test_suspend_reinstate_cycle(api):
    """PRD §3.2: "An approved determination can be suspended, moving from
    `APPROVED` to `SUSPENDED`, and later reinstated from `SUSPENDED` back to
    `APPROVED`"

    Design: Difficulty/non_linear_state_machine/eligibility_deny_revise_and_suspend_reinstate_cycles
    """
    base = create_characterized_stream(material_type="GYPSUM")
    determination = file_and_approve_eligibility(
        base["stream"]["id"], state_code="OH", use_case="SOIL_AMENDMENT"
    )
    assert determination["status"] == "APPROVED"

    suspended = validate_success(api.suspend_eligibility(determination["id"], CO_FILE), 200)
    assert suspended["status"] == "SUSPENDED"

    reinstated = validate_success(api.reinstate_eligibility(determination["id"], CO_FILE), 200)
    assert reinstated["status"] == "APPROVED"


def test_adjacent_eligibility_window_submits(api):
    """PRD §3.2: "Submission is guarded by two checks: the stream must still
    have a `VERIFIED` characterization (else `ERR_STREAM_NOT_CHARACTERIZED`),
    and the half-open window must not overlap the window of any other
    determination for the same stream and state pair currently in `SUBMITTED`,
    `APPROVED`, or `SUSPENDED` status (else `ERR_ELIGIBILITY_WINDOW_OVERLAP`).
    Because windows are half-open, two determinations whose windows merely touch
    at a boundary date do not overlap."

    The logical clock is moved to 2026-06-01 so D1's window
    [2026-01-01, 2026-07-01) is still in the future at approval time.

    Design: Difficulty/resource_temporal_overlap/eligibility_window_half_open_exclusivity
    """
    set_logical_clock("2026-06-01T00:00:00Z")
    base = create_characterized_stream(material_type="GYPSUM")
    stream_id = base["stream"]["id"]

    d1 = file_and_approve_eligibility(
        stream_id,
        state_code="OH",
        use_case="SOIL_AMENDMENT",
        valid_from="2026-01-01",
        valid_until="2026-07-01",
    )
    d2 = file_eligibility(
        stream_id,
        state_code="OH",
        use_case="SOIL_AMENDMENT",
        valid_from="2026-07-01",
        valid_until="2027-01-01",
    )

    # D2's valid_from equals D1's valid_until: half-open windows merely touch.
    submitted = validate_success(api.submit_eligibility(d2["id"], CO_FILE), 200)
    assert submitted["status"] == "SUBMITTED"

    dets, _ = validate_paginated(api.list_eligibility_determinations(stream_id, BROKER))
    d1_after = next(d for d in dets if d["id"] == d1["id"])
    assert d1_after["status"] == "APPROVED", "D1 must remain APPROVED"


def test_overlapping_eligibility_window_rejected(api):
    """PRD §3.2: "the half-open window must not overlap the window of any other
    determination for the same stream and state pair currently in `SUBMITTED`,
    `APPROVED`, or `SUSPENDED` status (else `ERR_ELIGIBILITY_WINDOW_OVERLAP`)."

    The logical clock is moved to 2026-06-01 so D1's window
    [2026-01-01, 2026-07-01) is still in the future at approval time.

    Design: Difficulty/resource_temporal_overlap/eligibility_window_half_open_exclusivity
    """
    set_logical_clock("2026-06-01T00:00:00Z")
    base = create_characterized_stream(material_type="GYPSUM")
    stream_id = base["stream"]["id"]

    file_and_approve_eligibility(
        stream_id,
        state_code="OH",
        use_case="SOIL_AMENDMENT",
        valid_from="2026-01-01",
        valid_until="2026-07-01",
    )
    d3 = file_eligibility(
        stream_id,
        state_code="OH",
        use_case="ROAD_BASE",
        valid_from="2026-06-30",
        valid_until="2026-12-01",
    )

    # D3 starts one day before D1's exclusive end: the windows overlap.
    resp = api.submit_eligibility(d3["id"], CO_FILE)
    validate_error(resp, ApiErrorId.ERR_ELIGIBILITY_WINDOW_OVERLAP)
