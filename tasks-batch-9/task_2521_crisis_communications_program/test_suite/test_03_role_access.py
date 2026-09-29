"""Role-based access control: authentication, the per-endpoint permission
matrix, shared operations and ownership binding (PRD §2.1, §2.9, §4)."""

from test_helpers import (
    PROGRAM_ADMIN_USER_ID,
    STARTUP_CLOCK,
    assert_field,
    assert_ids_equal,
    assert_ledger,
    assert_no_write,
    assert_pagination_meta,
    assert_state,
    assert_two_decimals,
    assert_privilege_payload,
    book_interview,
    cancel_interview_payload,
    decide_payload,
    draft_statement,
    escalate_signal,
    find_by,
    incident_payload,
    incident_version,
    issue_signal_payload,
    link_signal,
    link_signal_payload,
    make_incident_lead_headers,
    media_interview_payload,
    prepared_material_payload,
    read_assignment,
    read_incident,
    read_interview,
    read_member,
    read_statement,
    read_task,
    record_signal,
    register_member,
    seat_member,
    set_clock,
    setup_activated_incident,
    setup_monitoring_incident,
    statement_payload,
    submit_for_review,
    team_member_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_missing_or_empty_identity_header_is_unauthenticated(api):
    """PRD §2.1: "Every request to this API must carry two headers:
    `X-User-ID`, identifying the caller, and `X-User-Role`, naming the capability
    set the caller is acting under. If either header is missing or empty, or if
    `X-User-Role` is not one of the seven declared role names, the request is
    rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/corner_rbac_missing_x_user_header_is_unauthenticated
    """
    set_clock(STARTUP_CLOCK)
    member = register_member(full_name="Dana Ruiz", org_title="VP Operations")

    admin_without_id = {"X-User-Role": "ProgramAdmin", "Content-Type": "application/json"}
    lead_without_id = {"X-User-Role": "IncidentLead", "Content-Type": "application/json"}

    # A read is refused just as bluntly as a write.
    validate_error(
        api.get_team_member(member["id"], admin_without_id), "ERR_UNAUTHENTICATED"
    )
    validate_error(
        api.create_incident(
            incident_payload(title="Attempt with no identity"), lead_without_id
        ),
        "ERR_UNAUTHENTICATED",
    )

    # An empty header is the same as an absent one.
    admin_with_empty_id = {
        "X-User-ID": "",
        "X-User-Role": "ProgramAdmin",
        "Content-Type": "application/json",
    }
    lead_with_empty_id = {
        "X-User-ID": "",
        "X-User-Role": "IncidentLead",
        "Content-Type": "application/json",
    }
    validate_error(
        api.get_team_member(member["id"], admin_with_empty_id), "ERR_UNAUTHENTICATED"
    )
    validate_error(
        api.create_incident(
            incident_payload(title="Attempt with no identity"), lead_with_empty_id
        ),
        "ERR_UNAUTHENTICATED",
    )

    # A missing role header, and a role name outside the declared seven, land in
    # the same place.
    validate_error(
        api.get_team_member(
            member["id"],
            {"X-User-ID": PROGRAM_ADMIN_USER_ID, "Content-Type": "application/json"},
        ),
        "ERR_UNAUTHENTICATED",
    )
    validate_error(
        api.get_team_member(
            member["id"],
            {
                "X-User-ID": PROGRAM_ADMIN_USER_ID,
                "X-User-Role": "CrisisTsar",
                "Content-Type": "application/json",
            },
        ),
        "ERR_UNAUTHENTICATED",
    )

    # Header presence is check 1 of the rejection order, so it beats both role
    # membership and body validation: this request has an undeclared role, no
    # caller id and a body missing its required title, and is still a 401.
    validate_error(
        api.create_incident(
            {"scenario_code": "PRODUCT_RECALL"},
            {"X-User-Role": "CrisisTsar", "Content-Type": "application/json"},
        ),
        "ERR_UNAUTHENTICATED",
    )

    rows, meta = validate_paginated(
        api.list_incidents(make_incident_lead_headers(member["id"]))
    )
    assert_pagination_meta(meta, total_count=0, has_more=False)
    assert rows == [], f"no incident may exist after refused creates, got {rows}"


def test_role_cannot_reach_another_roles_exclusive_operations(api):
    """PRD §2.1: "If both headers are well formed but the named role is not
    among the roles authorised for the endpoint being called, the rejection is
    `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

    Design: Corner/rbac/corner_rbac_role_cannot_reach_another_roles_exclusive_operations
    """
    scenario = setup_monitoring_incident(clock="2026-08-10T09:00:00Z")
    incident_id = scenario["incident"]["id"]
    signal = record_signal(
        scenario["channel"]["id"],
        scenario["headers"]["listener"],
        headline="Outage noticed",
        reach_score=75,
    )
    link_signal(signal["id"], incident_id, scenario["headers"]["listener"])
    escalate_signal(signal["id"], scenario["headers"]["listener"])
    seat_member(
        incident_id,
        scenario["ids"]["lead"],
        "INCIDENT_LEAD",
        scenario["headers"]["lead"],
        member_headers=scenario["headers"]["lead"],
    )
    seat_member(
        incident_id,
        scenario["ids"]["counsel"],
        "LEGAL_COUNSEL",
        scenario["headers"]["lead"],
        member_headers=scenario["headers"]["counsel"],
    )
    before = read_incident(incident_id)

    # The roster registry belongs to the program administrator alone.
    validate_error(
        api.create_team_member(
            team_member_payload(full_name="Unauthorised Addition", org_title="Intern"),
            scenario["headers"]["listener"],
        ),
        "ERR_ROLE_NOT_PERMITTED",
    )
    # Activation belongs to the incident lead; this incident is otherwise ready
    # to activate, so nothing but the role can be refusing it.
    validate_error(
        api.activate_incident(incident_id, scenario["headers"]["comms"]),
        "ERR_ROLE_NOT_PERMITTED",
    )
    # Drafting belongs to the communications lead. The role refusal precedes
    # every state check: the incident is still MONITORING and the version carried
    # is current, yet the answer is 403 rather than a state or version error.
    validate_error(
        api.create_statement(
            statement_payload(
                incident_id,
                incident_version(incident_id),
                body="Written by the wrong role.",
            ),
            scenario["headers"]["lead"],
        ),
        "ERR_ROLE_NOT_PERMITTED",
    )
    # Privilege authority belongs to counsel alone.
    validate_error(
        api.assert_privilege(
            incident_id,
            assert_privilege_payload(
                privilege_basis="Claimed by a role that has no privilege authority."
            ),
            scenario["headers"]["comms"],
        ),
        "ERR_ROLE_NOT_PERMITTED",
    )

    _, member_meta = validate_paginated(
        api.list_team_members(scenario["headers"]["admin"])
    )
    assert_pagination_meta(member_meta, total_count=6, has_more=False)

    after = read_incident(incident_id)
    assert_no_write(before, after, "incident")
    assert_field(after, "response_state", "MONITORING", "incident")
    assert_field(after, "activated_at", None, "incident")
    assert_field(after, "privilege_state", "NON_PRIVILEGED", "incident")
    assert_field(after, "legal_hold_active", False, "incident")

    _, statement_meta = validate_paginated(
        api.list_statements(
            scenario["headers"]["admin"], {"incident_id": incident_id}
        )
    )
    assert_pagination_meta(statement_meta, total_count=0, has_more=False)


def test_shared_operations_accept_each_declared_role(api):
    """PRD §3.3: "An operator checkpoint — available to the program
    administrator, the incident lead and the communications lead — advances every
    time-driven consequence at the current logical clock reading for one
    incident."

    Design: Corner/rbac/corner_rbac_shared_operations_accept_each_declared_role
    """
    scenario = setup_monitoring_incident(clock="2026-08-10T09:00:00Z")
    incident_id = scenario["incident"]["id"]

    # Signal recording is shared with the opaque program-administrator identity,
    # which carries no roster row at all.
    signal = validate_success(
        api.create_issue_signal(
            issue_signal_payload(
                scenario["channel"]["id"],
                headline="Minor outage noticed",
                reach_score=75,
            ),
            scenario["headers"]["admin"],
        ),
        201,
    )
    # Linking and escalation are shared between the listener and the lead.
    validate_success(
        api.link_issue_signal(
            signal["id"], link_signal_payload(incident_id), scenario["headers"]["lead"]
        )
    )
    validate_success(
        api.escalate_issue_signal(signal["id"], scenario["headers"]["lead"])
    )
    seat_member(
        incident_id,
        scenario["ids"]["lead"],
        "INCIDENT_LEAD",
        scenario["headers"]["lead"],
        member_headers=scenario["headers"]["lead"],
    )
    validate_success(api.activate_incident(incident_id, scenario["headers"]["lead"]))

    # The same checkpoint runs under each of its three declared roles.
    for role_key in ("admin", "lead", "comms"):
        validate_success(api.sla_sweep(incident_id, scenario["headers"][role_key]))

    incident = read_incident(incident_id)
    assert_field(incident, "sla_breached", False, "incident")
    assert_ledger(incident, "open_approval_task_count", 0)

    # Filing dark-site material is shared between the administrator and comms.
    admin_material = validate_success(
        api.create_prepared_material(
            prepared_material_payload(
                material_type="FAQ", title="Outage FAQ, admin copy"
            ),
            scenario["headers"]["admin"],
        ),
        201,
    )
    comms_material = validate_success(
        api.create_prepared_material(
            prepared_material_payload(
                material_type="FAQ", title="Outage FAQ, comms copy"
            ),
            scenario["headers"]["comms"],
        ),
        201,
    )
    for material in (admin_material, comms_material):
        assert_field(material, "readiness_state", "DRAFT", "material")
        assert_two_decimals(material["readiness_score"], 0.00, "readiness_score")

    _, material_meta = validate_paginated(
        api.list_prepared_materials(
            scenario["headers"]["spox"], {"scenario_code": "PRODUCT_RECALL"}
        )
    )
    assert_pagination_meta(material_meta, total_count=2, has_more=False)


def test_holding_the_role_cannot_substitute_for_owning_the_row(api):
    """PRD §2.1: "acknowledging a crisis-team seat requires `X-User-ID` to equal
    the seat's `member_id`; and deciding an approval task requires `X-User-ID` to
    equal the task's `assignee_member_id`."

    Design: Corner/rbac/corner_rbac_holding_the_role_cannot_substitute_for_owning_the_row
    """
    scenario = setup_activated_incident(
        tier="SEV2", clock="2026-08-10T09:00:00Z", scenario_code="REGULATORY_PROBE"
    )
    incident_id = scenario["incident"]["id"]
    exec_seat = seat_member(
        incident_id,
        scenario["ids"]["exec"],
        "EXEC_SPONSOR",
        scenario["headers"]["lead"],
        decision_authority="LIMITED",
        acknowledge=False,
    )
    draft_statement(
        scenario, body="We have received the letter and are responding."
    )
    submit_for_review(scenario)
    lead_task = find_by(
        scenario["tasks"], assignee_member_id=scenario["ids"]["lead"]
    )

    # IncidentLead is a declared role on seat acknowledgement, but this seat
    # belongs to the executive sponsor.
    validate_error(
        api.acknowledge_team_assignment(exec_seat["id"], scenario["headers"]["lead"]),
        "ERR_ROLE_NOT_PERMITTED",
    )
    # LegalCounsel is a declared role on the decide endpoint and holds its own
    # PENDING task on this very statement, yet it is not this task's assignee.
    validate_error(
        api.decide_approval_task(
            lead_task["id"],
            decide_payload("APPROVE", "Approving a task that is not mine."),
            scenario["headers"]["counsel"],
        ),
        "ERR_ROLE_NOT_PERMITTED",
    )

    seat = read_assignment(exec_seat["id"])
    assert_state(seat, "ASSIGNED", "seat")
    assert_field(seat, "acknowledged_at", None, "seat")

    task = read_task(lead_task["id"])
    assert_state(task, "PENDING", "approval task")
    assert_field(task, "decided_at", None, "approval task")

    statement = read_statement(scenario["statement"]["id"])
    assert_state(statement, "IN_REVIEW", "statement")
    assert_field(statement, "quorum_required", 2, "statement")
    assert_field(statement, "approvals_recorded", 0, "statement")

    assert_ledger(read_incident(incident_id), "open_approval_task_count", 2)


def test_spokesperson_may_read_interviews_but_not_book_one(api):
    """PRD §3.7: "Booking an interview is the communications lead's job and
    requires the `incident_id` the interview addresses, the
    `spokesperson_member_id` of the designated speaker, the `channel_id` of the
    outlet conducting it, an `outlet_name` of at most 160 non-empty characters
    naming the outlet or programme in free text, and the two endpoints of the
    booking, `scheduled_start_at` and `scheduled_end_at`."

    Design: Corner/rbac/corner_rbac_spokesperson_can_read_and_cancel_but_cannot_book
    """
    scenario = setup_activated_incident(
        tier="SEV2", clock="2026-08-10T09:00:00Z", scenario_code="PLANT_INCIDENT"
    )
    incident_id = scenario["incident"]["id"]
    interview = book_interview(
        scenario,
        "2026-08-12T10:00:00Z",
        "2026-08-12T10:45:00Z",
        anticipated_question_count=8,
        outlet_name="Morning Wire",
    )

    # The narrowest role in the matrix still reads every listing.
    rows, meta = validate_paginated(
        api.list_media_interviews(
            scenario["headers"]["spox"], {"incident_id": incident_id}
        )
    )
    assert_pagination_meta(meta, total_count=1, has_more=False)
    assert_ids_equal(rows, [interview["id"]])

    validate_error(
        api.create_media_interview(
            media_interview_payload(
                incident_id,
                scenario["ids"]["spox"],
                scenario["channel"]["id"],
                "2026-08-13T10:00:00Z",
                "2026-08-13T10:30:00Z",
                outlet_name="Self-booked podcast",
            ),
            scenario["headers"]["spox"],
        ),
        "ERR_ROLE_NOT_PERMITTED",
    )

    _, after_meta = validate_paginated(
        api.list_media_interviews(
            scenario["headers"]["spox"], {"incident_id": incident_id}
        )
    )
    assert_pagination_meta(after_meta, total_count=1, has_more=False)


def test_spokesperson_may_stand_down_her_own_booking(api):
    """PRD §3.7: "Cancellation may be initiated either by the communications
    lead or by the spokesperson standing themselves down, and it takes a
    `cancel_reason` that is stored on the booking."

    Design: Corner/rbac/corner_rbac_spokesperson_can_read_and_cancel_but_cannot_book
    """
    scenario = setup_activated_incident(
        tier="SEV2", clock="2026-08-10T09:00:00Z", scenario_code="PLANT_INCIDENT"
    )
    incident_id = scenario["incident"]["id"]
    interview = book_interview(
        scenario,
        "2026-08-12T10:00:00Z",
        "2026-08-12T10:45:00Z",
        anticipated_question_count=8,
        outlet_name="Morning Wire",
    )

    cancelled = validate_success(
        api.cancel_media_interview(
            interview["id"],
            cancel_interview_payload(
                cancel_reason="I am not the right voice for this topic."
            ),
            scenario["headers"]["spox"],
        )
    )
    assert_state(cancelled, "CANCELLED", "interview")
    assert_field(
        cancelled,
        "cancel_reason",
        "I am not the right voice for this topic.",
        "interview",
    )
    assert_state(read_interview(interview["id"]), "CANCELLED", "interview")

    # The booking never reached CONFIRMED, so the spokesperson-load ledger was
    # never charged and stays at 0.
    assert_ledger(
        read_member(scenario["ids"]["spox"]), "scheduled_interview_minutes", 0
    )
    assert_ledger(read_incident(incident_id), "confirmed_interview_count", 0)
