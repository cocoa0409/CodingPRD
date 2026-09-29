"""
Role authorisation: exclusive operations, shared operations and the three ownership codes.

Every test builds its own world from scratch through declared endpoints — the harness
restarts the API with an empty database before each test — and sets the logical clock
explicitly whenever the scenario names an instant. Technician and club identities are
always threaded through the real row id, never a placeholder.
"""

import pytest

from test_helpers import (
    CONTRACT_ADMIN,
    DEFAULT_LIMIT,
    ERR_CLUB_SCOPE_FORBIDDEN,
    ERR_INSPECTOR_NOT_CERTIFIED,
    ERR_ROLE_FORBIDDEN,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_TECHNICIAN_NOT_ASSIGNED,
    PARTS_PLANNER,
    SERVICE_COORDINATOR,
    UNKNOWN_UUID,
    arrive_call,
    assert_fields,
    assert_pagination_meta,
    build_fleet,
    call_cancel_payload,
    checklist_item,
    checklist_result_payload,
    club_payload,
    contract_payload,
    contract_version,
    credit_reconciliation_payload,
    dispatch_call,
    dispatch_payload,
    get_success_data,
    inspector_headers,
    manager_headers,
    new_club,
    new_part,
    open_call,
    parts_hold_payload,
    place_hold,
    preventive_visit_payload,
    read_call,
    read_part_order,
    read_visit,
    renewal_quote_payload,
    resolve_payload,
    safety_doc_submit_payload,
    schedule_visit,
    service_call_payload,
    set_clock,
    start_visit,
    tag_out_payload,
    technician_headers,
    validate_error,
    validate_paginated,
)


def _club_manager_drafts_a_contract(api, club_id):
    return api.create_contract(contract_payload(club_id), manager_headers(club_id))


def _coordinator_registers_a_club(api, club_id):
    return api.create_club(
        club_payload(name="Westside Fitness", region_code="WEST"), SERVICE_COORDINATOR
    )


def _planner_reconciles_credit(api, club_id):
    return api.reconcile_credits(
        UNKNOWN_UUID, credit_reconciliation_payload("2026-08", 1), PARTS_PLANNER
    )


def _planner_dispatches_a_call(api, club_id):
    return api.dispatch_service_call(
        UNKNOWN_UUID, dispatch_payload("2026-08-15T10:00:00Z"), PARTS_PLANNER
    )


def _technician_books_a_visit(api, club_id):
    return api.create_preventive_visit(
        preventive_visit_payload(
            UNKNOWN_UUID, UNKNOWN_UUID, "2026-08-15T09:00:00Z", "2026-08-15T11:00:00Z"
        ),
        technician_headers(UNKNOWN_UUID),
    )


def _administrator_declares_end_of_support(api, club_id):
    return api.declare_end_of_support(UNKNOWN_UUID, CONTRACT_ADMIN)


def _coordinator_places_a_parts_hold(api, club_id):
    return api.place_parts_hold(
        UNKNOWN_UUID, parts_hold_payload(UNKNOWN_UUID, 1, "NEW"), SERVICE_COORDINATOR
    )


def _technician_certifies_a_safety_document(api, club_id):
    return api.certify_safety_doc(UNKNOWN_UUID, technician_headers(UNKNOWN_UUID))


def _planner_tags_out_a_machine(api, club_id):
    return api.tag_out_equipment(UNKNOWN_UUID, tag_out_payload(), PARTS_PLANNER)


@pytest.mark.parametrize(
    "attempt",
    [
        _club_manager_drafts_a_contract,
        _coordinator_registers_a_club,
        _planner_reconciles_credit,
        _planner_dispatches_a_call,
        _technician_books_a_visit,
        _administrator_declares_end_of_support,
        _coordinator_places_a_parts_hold,
        _technician_certifies_a_safety_document,
        _planner_tags_out_a_machine,
    ],
    ids=[
        "club_manager_drafts_a_contract",
        "coordinator_registers_a_club",
        "planner_reconciles_credit",
        "planner_dispatches_a_call",
        "technician_books_a_visit",
        "administrator_declares_end_of_support",
        "coordinator_places_a_parts_hold",
        "technician_certifies_a_safety_document",
        "planner_tags_out_a_machine",
    ],
)
def test_an_operation_reserved_to_one_role_is_closed_to_every_other_role(api, attempt):
    """
    Each role's own operations refuse every other role before any lookup or state check.

    PRD: "If both headers are well formed but the named role is not among the roles
    authorised for the target endpoint (see the table in §4), the request is rejected with
    `ERR_ROLE_FORBIDDEN` (HTTP 403)."

    Design: Corner/rbac/each_roles_exclusive_operations_are_closed_to_the_other_five
    """
    set_clock(api, "2026-08-15T08:00:00Z")
    club = new_club(api)

    refused = attempt(api, club["id"])
    assert refused.status_code == 403
    validate_error(refused, ERR_ROLE_FORBIDDEN, 403)

    # The role rung outranks lookup and state, so nothing was created on the way past it.
    clubs, clubs_meta = validate_paginated(api.list_clubs(CONTRACT_ADMIN))
    assert_pagination_meta(clubs_meta, DEFAULT_LIMIT, 0, 1, False)
    assert clubs[0]["id"] == club["id"]
    _contracts, contracts_meta = validate_paginated(api.list_contracts(CONTRACT_ADMIN))
    assert_pagination_meta(contracts_meta, DEFAULT_LIMIT, 0, 0, False)


def test_opening_and_cancelling_a_call_accept_the_club_or_the_coordinator_interchangeably(api):
    """
    Either holder of a shared operation may act on the other's row with no handoff step.

    PRD: "When a machine breaks between preventive visits, a `ClubManager` or a
    `ServiceCoordinator` opens a **service call**."

    Design: Corner/rbac/shared_operations_accept_either_holder_without_a_handoff
    """
    fleet = build_fleet(
        api,
        clock="2026-08-15T08:00:00Z",
        serials=["SN-SH-1", "SN-SH-2"],
        equipment_kwargs={"initial_usage_hours": 500},
    )
    contract_id = fleet["contract_id"]
    e1, e2 = fleet["equipment_ids"]
    manager = fleet["manager"]

    # The club opens; the coordinator closes it out.
    club_call = open_call(
        api,
        contract_id,
        e1,
        headers=manager,
        severity="MAJOR",
        symptom_code="BELT_NOISE",
    )
    assert_fields(
        club_call, status="OPEN", severity="MAJOR", contract_id=contract_id, equipment_id=e1
    )
    cancelled_by_coordinator = get_success_data(
        api.cancel_service_call(
            club_call["id"], call_cancel_payload("CLUB_WITHDREW"), SERVICE_COORDINATOR
        )
    )
    assert_fields(
        cancelled_by_coordinator, status="CANCELLED", cancellation_reason="CLUB_WITHDREW"
    )

    # The coordinator opens; the club closes it out.
    coordinator_call = open_call(
        api, contract_id, e2, severity="MINOR", symptom_code="CONSOLE_DIM"
    )
    assert_fields(coordinator_call, status="OPEN", severity="MINOR", equipment_id=e2)
    cancelled_by_club = get_success_data(
        api.cancel_service_call(
            coordinator_call["id"], call_cancel_payload("DUPLICATE_REPORT"), manager
        )
    )
    assert_fields(
        cancelled_by_club, status="CANCELLED", cancellation_reason="DUPLICATE_REPORT"
    )

    # Both holders can read either row afterwards.
    for headers in (manager, SERVICE_COORDINATOR):
        for call_id in (club_call["id"], coordinator_call["id"]):
            assert get_success_data(api.get_service_call(call_id, headers))["id"] == call_id

    calls, calls_meta = validate_paginated(
        api.list_service_calls(manager, contract_id=contract_id)
    )
    assert_pagination_meta(calls_meta, DEFAULT_LIMIT, 0, 2, False)
    assert {row["status"] for row in calls} == {"CANCELLED"}


def test_a_club_manager_may_act_only_on_the_club_named_in_its_own_user_id(api):
    """
    Every club-scoped operation resolves the target's club and refuses a foreign manager.

    PRD: "A `ClubManager` acting on a resource that belongs to a different club — resolved
    through the target's `club_id`, or through the referenced machine's or contract's
    `club_id` — is rejected with `ERR_CLUB_SCOPE_FORBIDDEN` (HTTP 403); this applies to
    every `ClubManager` operation, namely opening a service call, cancelling a call,
    accepting or declining a renewal quote, and every club-scoped read."

    Design: Corner/rbac/a_club_manager_is_confined_to_the_club_named_in_its_user_id
    """
    home = build_fleet(
        api,
        clock="2026-08-15T08:00:00Z",
        club_kwargs={"name": "Northside Fitness", "region_code": "NW"},
        serials=["SN-CS-A1", "SN-CS-A2"],
        equipment_kwargs={"initial_usage_hours": 500},
    )
    away = build_fleet(
        api,
        club_kwargs={"name": "Southside Fitness", "region_code": "SW"},
        serials=["SN-CS-B1"],
        equipment_kwargs={"initial_usage_hours": 500},
    )
    home_contract = home["contract_id"]
    a1, a2 = home["equipment_ids"]
    home_manager = home["manager"]
    away_manager = away["manager"]

    # The home manager acts inside its own club without friction.
    own_call = open_call(
        api,
        home_contract,
        a1,
        headers=home_manager,
        severity="MAJOR",
        symptom_code="BELT_NOISE",
    )
    assert_fields(own_call, status="OPEN", contract_id=home_contract)
    own_summary = get_success_data(api.get_credit_summary(home_contract, home_manager))
    assert own_summary["contract_id"] == home_contract

    # The foreign manager is turned away from the write, the cancel and the read alike.
    foreign_open = api.create_service_call(
        service_call_payload(home_contract, a2, severity="MINOR", symptom_code="ROLLER_WEAR"),
        away_manager,
    )
    assert foreign_open.status_code == 403
    validate_error(foreign_open, ERR_CLUB_SCOPE_FORBIDDEN, 403)

    foreign_cancel = api.cancel_service_call(
        own_call["id"], call_cancel_payload("CLUB_WITHDREW"), away_manager
    )
    assert foreign_cancel.status_code == 403
    validate_error(foreign_cancel, ERR_CLUB_SCOPE_FORBIDDEN, 403)

    foreign_read = api.get_credit_summary(home_contract, away_manager)
    assert foreign_read.status_code == 403
    validate_error(foreign_read, ERR_CLUB_SCOPE_FORBIDDEN, 403)

    # A quote on the home contract belongs to the home club, whoever holds the role.
    quote = get_success_data(
        api.create_renewal_quote(
            home_contract,
            renewal_quote_payload(contract_version(api, home_contract)),
            CONTRACT_ADMIN,
        ),
        201,
    )
    foreign_accept = api.accept_renewal_quote(quote["id"], away_manager)
    assert foreign_accept.status_code == 403
    validate_error(foreign_accept, ERR_CLUB_SCOPE_FORBIDDEN, 403)

    accepted = get_success_data(api.accept_renewal_quote(quote["id"], home_manager))
    assert_fields(accepted, id=quote["id"], status="ACCEPTED")

    # None of the foreign attempts left a row behind in either club.
    home_calls, home_meta = validate_paginated(
        api.list_service_calls(CONTRACT_ADMIN, contract_id=home_contract)
    )
    assert_pagination_meta(home_meta, DEFAULT_LIMIT, 0, 1, False)
    assert home_calls[0]["id"] == own_call["id"]
    _away_calls, away_meta = validate_paginated(
        api.list_service_calls(CONTRACT_ADMIN, contract_id=away["contract_id"])
    )
    assert_pagination_meta(away_meta, DEFAULT_LIMIT, 0, 0, False)


def test_field_actions_refuse_every_technician_but_the_one_holding_the_assignment(api):
    """
    Call and visit actions are bound to the assigned technician, one action at a time.

    PRD: "A `FieldTechnician` acting on a call, visit or part order that is not assigned to
    them is rejected with `ERR_TECHNICIAN_NOT_ASSIGNED` (HTTP 403); this guards call
    arrival, parts hold, resume and resolve, visit start, checklist recording and
    completion, safety-document submission, and part-order installation."

    Design: Corner/rbac/field_actions_are_bound_to_the_technician_holding_the_assignment
    """
    fleet = build_fleet(
        api,
        clock="2026-08-15T08:00:00Z",
        model_kwargs={
            "checklist_template": [
                checklist_item("BELT_TENSION", consumable=True),
                checklist_item("EMERGENCY_STOP", is_safety_critical=True),
            ]
        },
        serials=["SN-OWN-1", "SN-OWN-2"],
        equipment_kwargs={"initial_usage_hours": 500},
        technicians=[{"full_name": "Dana Reyes"}, {"full_name": "Ilan Cruz"}],
    )
    contract_id = fleet["contract_id"]
    e1, e2 = fleet["equipment_ids"]
    owner, stranger = fleet["technician_ids"]
    belt = new_part(
        api,
        fleet["model_id"],
        part_number="BELT-STD",
        category="WEAR",
        unit_price_cents=8000,
        initial_on_hand_qty=3,
    )

    call = open_call(api, contract_id, e1, severity="MAJOR", symptom_code="BELT_FRAY")
    dispatch_call(api, call["id"], "2026-08-15T08:00:00Z", owner)

    # Arrival.
    refused = api.arrive_service_call(call["id"], technician_headers(stranger))
    assert refused.status_code == 403
    validate_error(refused, ERR_TECHNICIAN_NOT_ASSIGNED, 403)
    arrive_call(api, call["id"], owner)

    # Parts hold.
    refused = api.place_parts_hold(
        call["id"], parts_hold_payload(belt["id"], 1, "NEW"), technician_headers(stranger)
    )
    assert refused.status_code == 403
    validate_error(refused, ERR_TECHNICIAN_NOT_ASSIGNED, 403)
    order = place_hold(api, call["id"], owner, belt["id"], 1, "NEW")

    # Part-order installation.
    refused = api.install_part_order(order["id"], technician_headers(stranger))
    assert refused.status_code == 403
    validate_error(refused, ERR_TECHNICIAN_NOT_ASSIGNED, 403)
    get_success_data(api.install_part_order(order["id"], technician_headers(owner)))
    assert_fields(read_part_order(api, order["id"]), status="INSTALLED")

    # Resume.
    refused = api.resume_service_call(call["id"], technician_headers(stranger))
    assert refused.status_code == 403
    validate_error(refused, ERR_TECHNICIAN_NOT_ASSIGNED, 403)
    get_success_data(api.resume_service_call(call["id"], technician_headers(owner)))

    # Resolve.
    refused = api.resolve_service_call(
        call["id"], resolve_payload(), technician_headers(stranger)
    )
    assert refused.status_code == 403
    validate_error(refused, ERR_TECHNICIAN_NOT_ASSIGNED, 403)
    assert_fields(read_call(api, call["id"]), status="ON_SITE", assigned_technician_id=owner)

    # The visit dimension is guarded the same way.
    visit = schedule_visit(
        api, contract_id, e2, "2026-08-15T13:00:00Z", "2026-08-15T15:00:00Z", owner
    )
    set_clock(api, "2026-08-15T13:10:00Z")
    refused = api.start_visit(visit["id"], technician_headers(stranger))
    assert refused.status_code == 403
    validate_error(refused, ERR_TECHNICIAN_NOT_ASSIGNED, 403)
    start_visit(api, visit["id"], owner)

    refused = api.record_checklist_result(
        visit["id"], checklist_result_payload("BELT_TENSION"), technician_headers(stranger)
    )
    assert refused.status_code == 403
    validate_error(refused, ERR_TECHNICIAN_NOT_ASSIGNED, 403)

    refused = api.submit_safety_doc(
        visit["id"], safety_doc_submit_payload(), technician_headers(stranger)
    )
    assert refused.status_code == 403
    validate_error(refused, ERR_TECHNICIAN_NOT_ASSIGNED, 403)

    refused = api.complete_visit(visit["id"], technician_headers(stranger))
    assert refused.status_code == 403
    validate_error(refused, ERR_TECHNICIAN_NOT_ASSIGNED, 403)

    # The assigned technician performs the very action the stranger was refused.
    get_success_data(
        api.record_checklist_result(
            visit["id"],
            checklist_result_payload("BELT_TENSION", consumable_replaced=True),
            technician_headers(owner),
        )
    )
    assert_fields(
        read_visit(api, visit["id"]),
        visit_status="IN_PROGRESS",
        assigned_technician_id=owner,
        checklist_resolved_count=1,
    )


def test_the_technician_who_filed_the_safety_document_may_not_certify_it(api):
    """
    Certification demands the inspector credential first and a second pair of eyes next.

    PRD: "And the acting `X-User-ID` must differ from the visit's
    `assigned_technician_id` — nobody signs off their own work — or the answer is
    `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/rbac/the_technician_who_signed_the_document_may_not_certify_it
    """
    fleet = build_fleet(
        api,
        clock="2026-08-15T08:00:00Z",
        model_kwargs={
            "checklist_template": [
                checklist_item("BELT_TENSION", consumable=True),
                checklist_item("EMERGENCY_STOP", is_safety_critical=True),
            ]
        },
        serials=["SN-SD-1"],
        equipment_kwargs={"initial_usage_hours": 500},
        technicians=[
            {"full_name": "Dana Reyes", "is_safety_inspector": True},
            {"full_name": "Ilan Cruz"},
            {"full_name": "Mira Osei", "is_safety_inspector": True},
        ],
    )
    visiting, uncredentialled, inspector = fleet["technician_ids"]

    visit = schedule_visit(
        api,
        fleet["contract_id"],
        fleet["equipment_ids"][0],
        "2026-08-15T09:00:00Z",
        "2026-08-15T11:00:00Z",
        visiting,
    )
    set_clock(api, "2026-08-15T09:10:00Z")
    start_visit(api, visit["id"], visiting)
    filed = get_success_data(
        api.submit_safety_doc(
            visit["id"], safety_doc_submit_payload(), technician_headers(visiting)
        )
    )
    assert_fields(filed, safety_doc_status="SUBMITTED", visit_status="IN_PROGRESS")

    # The credential rung comes first: a technician without it never reaches segregation.
    without_credential = api.certify_safety_doc(
        visit["id"], inspector_headers(uncredentialled)
    )
    assert without_credential.status_code == 403
    validate_error(without_credential, ERR_INSPECTOR_NOT_CERTIFIED, 403)

    # The visiting technician holds the credential and is still refused.
    own_work = api.certify_safety_doc(visit["id"], inspector_headers(visiting))
    assert own_work.status_code == 409
    validate_error(own_work, ERR_SEGREGATION_OF_DUTIES, 409)

    untouched = read_visit(api, visit["id"])
    assert_fields(
        untouched,
        safety_doc_status="SUBMITTED",
        visit_status="IN_PROGRESS",
        pm_credit_earned=False,
    )
    assert untouched["safety_doc_certified_by_id"] is None, (
        "a refused certification must not record a certifier"
    )

    # A different credentialled inspector signs it off.
    set_clock(api, "2026-08-15T09:30:00Z")
    certified = get_success_data(
        api.certify_safety_doc(visit["id"], inspector_headers(inspector))
    )
    assert_fields(
        certified,
        safety_doc_status="CERTIFIED",
        safety_doc_certified_by_id=inspector,
        visit_status="IN_PROGRESS",
        pm_credit_earned=False,
    )
