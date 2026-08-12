"""Occupying a jurisdiction, activating it, and the agent of record."""
from test_helpers import (
    ADMIN,
    AGENT,
    OFFICER,
    ApiErrorId,
    DE_RULE_MIN,
    TX_RULE_MIN_QUALIFICATION,
    accept_appointment,
    activate_registration,
    assert_agent_appointment,
    assert_registration,
    count_of_record,
    find_by_id,
    new_certificate,
    new_clearance,
    new_client,
    new_entity,
    new_home_registration,
    ops_run,
    propose_appointment,
    publish_rule,
    read_appointment,
    read_registration,
    set_clock,
    setup_active_home_registration,
    setup_pending_home_registration,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_home_registration_is_created_pending_with_no_agent_of_record(api):
    """PRD §3.2: "The new row takes `registration_kind` `HOME` and `state_code` equal to
    the entity's `home_state_code`, is created in `PENDING` with `name_clearance_id`
    null, and the governing jurisdiction rule is resolved for the current clock date — if
    no rule row is effective for that state on that date, the creation fails with
    `ERR_NO_EFFECTIVE_STATE_RULE`."
    PRD §3.2: "it exposes `qualified_on` (the ISO date it became `ACTIVE`, null while
    `PENDING`), `closed_on` (the ISO date it left the occupancy interval by reaching
    `WITHDRAWN`, `TERMINATED` or `CLOSED_PERMANENT`, and null otherwise),
    `agent_of_record_id`, `admin_dissolved_on`, `reinstatement_deadline`,
    `delinquency_rank`, `sop_priority_hold` and `assumed_name`."

    Design: Corner/state_machines/corner_registration_starts_in_pending_with_no_agent_of_record
    """
    publish_rule(
        {
            "state_code": "DE",
            "effective_from": "2026-01-01",
            "annual_report_basis": "FIXED_CALENDAR_DATE",
            "fixed_due_month": 3,
            "fixed_due_day": 1,
            "franchise_tax_basis": "FLAT",
            "flat_franchise_tax_cents": 0,
            "annual_report_fee_cents": 5000,
            "grace_days": 30,
            "grace_basis": "CALENDAR_DAYS",
            "late_fee_style": "FLAT",
            "late_fee_flat_cents": 20000,
        }
    )
    client = new_client()
    entity = new_entity(client["id"])

    data = validate_success(api.create_home_registration(entity["id"], OFFICER), 201)

    assert_registration(data)
    assert data["status"] == "PENDING"
    assert data["registration_kind"] == "HOME"
    assert data["state_code"] == "DE"
    assert data["qualified_on"] is None
    assert data["closed_on"] is None
    assert data["agent_of_record_id"] is None
    assert data["delinquency_rank"] == 0
    assert data["sop_priority_hold"] is False


def test_activating_an_already_active_registration_is_refused(api):
    """PRD §3.2: "The registration must be in `PENDING`, or the request is rejected with
    `ERR_INVALID_STATE`; and an agent appointment in status `APPOINTED` must already
    exist on it, or the request is rejected with `ERR_AGENT_OF_RECORD_REQUIRED`."
    PRD §3.2: "On success the status becomes `ACTIVE`, `qualified_on` is stamped with
    the current clock date, the agent-of-record selection is re-run so that
    `agent_of_record_id` and every sibling appointment's `of_record` are refreshed,
    `delinquency_rank` is recomputed, the registration's `version` increases by 1, and
    the entity's `compliance_posture` and then the client's
    `portfolio_delinquency_status` are recomputed."

    Design: Corner/state_machines/corner_activate_registration_twice_returns_invalid_state
    """
    scene = setup_active_home_registration(DE_RULE_MIN)

    response = api.activate_registration(scene["registration"]["id"], AGENT)

    assert response.status_code == 409
    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value)

    after = read_registration(scene["registration"]["id"])
    assert after["status"] == "ACTIVE"
    # The logical clock has never been moved, so it still reads 2026-05-01.
    assert after["qualified_on"] == "2026-05-01"


def test_home_registration_can_never_be_withdrawn(api):
    """PRD §3.12: "A `HOME` registration can never be withdrawn."
    PRD §2.9: "a `HOME` registration may not be withdrawn while a `FOREIGN`
    registration may not be terminated. Applies to every action endpoint that drives a
    state machine. Failure returns `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/corner_withdraw_home_registration_is_rejected
    """
    scene = setup_active_home_registration(DE_RULE_MIN)

    response = api.withdraw_registration(scene["registration"]["id"], AGENT)

    assert response.status_code == 409
    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value)

    after = read_registration(scene["registration"]["id"])
    assert after["status"] == "ACTIVE"
    assert after["closed_on"] is None


def test_rejecting_a_proposal_touches_nothing_else(api):
    """PRD §3.3: "A `FilingAgent` may instead reject a proposal, moving it `PROPOSED →
    REJECTED`."
    PRD §3.3: "Rejection touches nothing else: no sibling changes, no registration
    change, no selector re-run. The appointment's `version` increases by 1."

    Design: Corner/state_machines/corner_agent_appointment_rejected_from_proposed
    """
    scene = setup_pending_home_registration(DE_RULE_MIN)
    appointment = propose_appointment(scene["registration"])

    data = validate_success(api.reject_agent_appointment(appointment["id"], AGENT))

    assert_agent_appointment(data)
    assert data["status"] == "REJECTED"
    assert data["of_record"] is False
    assert read_registration(scene["registration"]["id"])["agent_of_record_id"] is None


def test_resigning_agent_holds_the_record_until_the_notice_window_closes(api):
    """PRD §3.3: "On success, `resignation_noticed_on` is stamped with the current clock
    date and `resignation_effective_on` is computed as that date plus 30 calendar days,
    the statutory notice period."
    PRD §3.3: "Candidates are ranked first by a priority in which a
    `RESIGNATION_NOTICED` appointment outranks an `APPOINTED` one, then by
    `appointed_on` ascending, then by `created_at` ascending."
    PRD §3.3: "An appointment in `RESIGNATION_NOTICED` whose `resignation_effective_on`
    is on or before the current clock date moves `RESIGNATION_NOTICED → RESIGNED` with
    `of_record` set false; the registration's `agent_of_record_id` is then re-derived by
    re-running the selection, and both the appointment's `version` and the
    registration's `version` increase by 1."

    Design: Corner/state_machines/corner_resigning_agent_stays_of_record_for_the_whole_notice_window
    """
    scene = setup_active_home_registration(DE_RULE_MIN)
    appointment_a = scene["appointment"]

    set_clock("2026-05-10T00:00:00Z")
    validate_success(api.notice_resignation(appointment_a["id"], OFFICER))

    set_clock("2026-05-20T00:00:00Z")
    registration = read_registration(scene["registration"]["id"])
    appointment_b = propose_appointment(
        registration, provider_name="Keystone Agent Services", appointed_on="2026-05-20"
    )
    accept_appointment(appointment_b["id"])

    noticed = read_appointment(appointment_a["id"])
    assert noticed["resignation_noticed_on"] == "2026-05-10"
    # 2026-05-10 plus the 30 calendar-day statutory notice period is 2026-06-09.
    assert noticed["resignation_effective_on"] == "2026-06-09"

    set_clock("2026-06-08T00:00:00Z")
    ops_run()
    assert read_appointment(appointment_a["id"])["status"] == "RESIGNATION_NOTICED"
    assert read_appointment(appointment_a["id"])["of_record"] is True
    assert read_appointment(appointment_b["id"])["status"] == "APPOINTED"
    assert read_appointment(appointment_b["id"])["of_record"] is False

    set_clock("2026-06-09T00:00:00Z")
    ops_run()
    assert read_appointment(appointment_a["id"])["status"] == "RESIGNED"
    assert read_appointment(appointment_a["id"])["of_record"] is False
    assert read_appointment(appointment_b["id"])["of_record"] is True
    assert (
        read_registration(scene["registration"]["id"])["agent_of_record_id"]
        == appointment_b["id"]
    )


def test_home_registration_without_an_effective_rule_is_refused(api):
    """PRD §3.2: "the governing jurisdiction rule is resolved for the current clock date
    — if no rule row is effective for that state on that date, the creation fails with
    `ERR_NO_EFFECTIVE_STATE_RULE`."
    PRD §2.6: "If the candidate set is empty, the operation is rejected with
    `ERR_NO_EFFECTIVE_STATE_RULE` and HTTP 422."

    Design: Corner/validations/corner_no_effective_state_rule_blocks_home_registration
    """
    publish_rule(DE_RULE_MIN)
    client = new_client()
    entity = new_entity(
        client["id"], legal_name="High Plains Widgets LLC", home_state_code="WY"
    )

    response = api.create_home_registration(entity["id"], OFFICER)

    assert response.status_code == 422
    validate_error(response, ApiErrorId.ERR_NO_EFFECTIVE_STATE_RULE.value)

    _rows, meta = validate_paginated(
        api.list_registrations(ADMIN, params={"legal_entity_id": entity["id"]})
    )
    assert meta["total_count"] == 0


def test_conflicting_name_blocks_qualification_until_a_fallback_resolves_it(api):
    """PRD §3.2: "Name resolution means the referenced clearance either carries `result`
    `AVAILABLE`, or carries `result` `CONFLICT` together with a non-null
    `fallback_assumed_name`. A clearance still `PENDING`, or a `CONFLICT` with no
    fallback, is rejected with `ERR_NAME_CONFLICT_UNRESOLVED`."
    PRD §3.2: "it becomes the `fallback_assumed_name` when the result is `CONFLICT` and
    a fallback was supplied; and it stays null in every other case, which in practice
    means a `CONFLICT` with no fallback."
    PRD §3.2: "When the referenced clearance's result was `CONFLICT`, the clearance's
    `resolved_name` is copied onto the registration as `assumed_name`; when the result was `AVAILABLE`,
    `assumed_name` stays null."

    Design: Corner/validations/corner_name_conflict_blocks_qualification_until_a_fallback_exists
    """
    publish_rule(DE_RULE_MIN)
    publish_rule(TX_RULE_MIN_QUALIFICATION)
    client = new_client()
    entity = new_entity(client["id"])
    registration = new_home_registration(entity["id"])
    appointment = propose_appointment(registration)
    accept_appointment(appointment["id"])
    activate_registration(registration["id"])
    certificate = new_certificate(registration["id"])

    bare = new_clearance(
        entity["id"],
        record_payload={"result": "CONFLICT", "conflicting_name": "Northwind Widgets Inc"},
    )
    with_fallback = new_clearance(
        entity["id"],
        record_payload={"result": "CONFLICT", "conflicting_name": "Northwind Widgets Inc"},
        fallback_assumed_name="Northwind Widgets of Texas",
    )

    assert bare["resolved_name"] is None
    assert with_fallback["resolved_name"] == "Northwind Widgets of Texas"

    blocked = api.create_foreign_qualification(
        entity["id"],
        {
            "state_code": "TX",
            "name_clearance_id": bare["id"],
            "good_standing_certificate_id": certificate["id"],
        },
        OFFICER,
    )
    assert blocked.status_code == 409
    validate_error(blocked, ApiErrorId.ERR_NAME_CONFLICT_UNRESOLVED.value)

    qualified = validate_success(
        api.create_foreign_qualification(
            entity["id"],
            {
                "state_code": "TX",
                "name_clearance_id": with_fallback["id"],
                "good_standing_certificate_id": certificate["id"],
            },
            OFFICER,
        ),
        201,
    )
    assert qualified["assumed_name"] == "Northwind Widgets of Texas"
    assert qualified["name_clearance_id"] == with_fallback["id"]

    rows, meta = validate_paginated(
        api.list_registrations(ADMIN, params={"name_clearance_id": with_fallback["id"]})
    )
    assert meta["total_count"] == 1
    assert find_by_id(rows, qualified["id"]) is not None
