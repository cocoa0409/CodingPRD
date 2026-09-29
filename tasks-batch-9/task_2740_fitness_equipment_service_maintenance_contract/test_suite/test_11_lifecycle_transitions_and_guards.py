"""
Lifecycle transitions and the state guards that protect them.

Every row in FleetCare starts in a declared initial state and moves only along the
hops the PRD names. This module walks the legal hops — a contract's
DRAFT -> ACTIVE -> SUSPENDED -> ACTIVE loop, a call's creation side effects, the
documented clearance that unlocks a tagged-out machine — and then pushes each state
machine off its rails to prove that every dimension reports its own state error, with
the exact identifier and HTTP status of the error catalogue, and that a refused
trigger leaves the row byte-for-byte where it was.

The logical clock is positioned explicitly in every test, because every stamped
instant, every elapsed-minute figure and every window comparison reads it.
"""

import pytest

from test_helpers import (
    DOWNTIME_GRACE_MINUTES,
    ERR_ASSIGNMENT_INVALID_STATE,
    ERR_CALL_INVALID_STATE,
    ERR_CONTRACT_INVALID_STATE,
    ERR_DOWNTIME_INVALID_STATE,
    ERR_PART_ORDER_INVALID_STATE,
    ERR_SAFETY_CLEARANCE_REQUIRED,
    ERR_SAFETY_DOC_INVALID_STATE,
    ERR_SAFETY_LOCKOUT_OPEN,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_VISIT_INVALID_STATE,
    SERVICE_COORDINATOR,
    SEVERITY_PLANNED_MINUTES,
    SLA_RESPONSE_MINUTES,
    arrive_call,
    assignment_for_call,
    assignment_for_visit,
    assert_common_fields,
    assert_fields,
    assert_instant,
    assert_money,
    assert_null_fields,
    assert_two_decimals,
    build_fleet,
    call_on_site,
    checklist_item,
    checklist_result_payload,
    dispatch_call,
    dispatch_payload,
    event_for_call,
    get_success_data,
    inspector_headers,
    new_part,
    open_call,
    part_order_cancel_payload,
    place_hold,
    read_assignment,
    read_call,
    read_club,
    read_contract,
    read_equipment,
    read_event,
    read_part,
    read_part_order,
    read_technician,
    read_visit,
    release_payload,
    renewal_quote_payload,
    resolve_payload,
    rows_of,
    schedule_visit,
    service_call_payload,
    set_clock,
    start_visit,
    suspend_payload,
    tag_out_payload,
    technician_headers,
    validate_error,
    validate_success,
    waive_payload,
)

# ─── Shared world-building ────────────────────────────────────────────────────

# "a region_code of two to four uppercase letters"; technician eligibility is an
# exact match on it, so club and technicians share one code.
REGION = "NW"

CLOCK_0800 = "2026-08-15T08:00:00Z"
CLOCK_0830 = "2026-08-15T08:30:00Z"
CLOCK_0900 = "2026-08-15T09:00:00Z"
CLOCK_0930 = "2026-08-15T09:30:00Z"
CLOCK_1000 = "2026-08-15T10:00:00Z"
CLOCK_1100 = "2026-08-15T11:00:00Z"

WINDOW_START = "2026-08-15T12:00:00Z"
WINDOW_END = "2026-08-15T13:30:00Z"
WINDOW_MINUTES = 90

TECH_PLAIN = {"full_name": "Dana Reyes"}
TECH_SECOND = {"full_name": "Ravi Shah"}
TECH_INSPECTOR = {"full_name": "Iris Vogel", "is_safety_inspector": True}
TECH_INSPECTOR_2 = {"full_name": "Omar Diaz", "is_safety_inspector": True}

CHECKLIST_TEMPLATE = [
    checklist_item("BELT_TENSION", consumable=True),
    checklist_item("EMERGENCY_STOP", is_safety_critical=True),
]


def _world(
    api,
    clock,
    serials,
    technicians=(),
    model_kwargs=None,
    contract_kwargs=None,
    club_kwargs=None,
    activate=True,
):
    """Clock, club, model, units, a GOLD/FULL contract and the named technicians."""
    club = {"region_code": REGION}
    club.update(club_kwargs or {})
    specs = []
    for spec in technicians:
        merged = {"region_code": REGION}
        merged.update(spec)
        specs.append(merged)
    return build_fleet(
        api,
        clock=clock,
        club_kwargs=club,
        model_kwargs=model_kwargs,
        contract_kwargs=contract_kwargs,
        serials=list(serials),
        equipment_kwargs={"initial_usage_hours": 500},
        technicians=specs,
        activate=activate,
    )


# ─── Declared initial states ──────────────────────────────────────────────────


def test_new_call_its_downtime_event_and_its_dispatch_reservation_start_open_open_and_reserved(
    api,
):
    """
    A freshly opened call is OPEN, its companion outage row is OPEN and the calendar
    reservation the dispatch minted is RESERVED for the severity's planned minutes.

    "Finally, one `DowntimeEvent` is created in status `OPEN` with `started_at` equal
    to `reported_at` and with `contract_id`, `equipment_id` and `service_call_id`
    copied from the call — the downtime meter starts running the instant the fault is
    reported, not when a technician is dispatched."

    Design: Corner/state_machines/newly_created_rows_start_in_their_declared_initial_states
    """
    fleet = _world(api, CLOCK_0800, ["SN-IS-1"], [TECH_PLAIN])
    technician_id = fleet["technician_ids"][0]

    call = open_call(
        api,
        fleet["contract_id"],
        fleet["equipment_ids"][0],
        severity="MAJOR",
        symptom_code="BELT_NOISE",
    )
    assert_fields(call, status="OPEN", parts_hold_count=0)
    assert_instant(call["reported_at"], CLOCK_0800, "reported_at")
    assert_common_fields(call, expected_version=1)

    event = event_for_call(api, call["id"])
    assert_fields(
        event,
        status="OPEN",
        contract_id=fleet["contract_id"],
        equipment_id=fleet["equipment_ids"][0],
        service_call_id=call["id"],
    )
    assert_instant(event["started_at"], CLOCK_0800, "started_at")
    assert_null_fields(event, "downtime_minutes")

    dispatch_call(api, call["id"], CLOCK_0800, technician_id)
    assignment = assignment_for_call(api, call["id"])
    assert_fields(
        assignment,
        status="RESERVED",
        technician_id=technician_id,
        service_call_id=call["id"],
        planned_minutes=SEVERITY_PLANNED_MINUTES["MAJOR"],
    )
    assert_null_fields(assignment, "preventive_visit_id")
    assert_instant(assignment["start_at"], CLOCK_0800, "start_at")
    assert_common_fields(assignment, expected_version=1)

    technician = read_technician(api, technician_id)
    assert technician["committed_minutes"] == SEVERITY_PLANNED_MINUTES["MAJOR"]


def test_new_visit_starts_scheduled_and_pending_while_a_new_catalogue_line_starts_active(
    api,
):
    """
    A booked visit starts SCHEDULED on the work dimension and PENDING on the
    documentation dimension with an unresolved checklist, and a freshly registered
    spare part starts ACTIVE with its opening buckets.

    "A successful booking produces a visit whose `visit_status` is `SCHEDULED` and
    whose `safety_doc_status` is `PENDING` — two dimensions that advance on entirely
    separate triggers and are read together in exactly one place, described at the end
    of this subsection."

    Design: Corner/state_machines/newly_created_rows_start_in_their_declared_initial_states
    """
    fleet = _world(
        api,
        CLOCK_0800,
        ["SN-IS-2"],
        [TECH_INSPECTOR],
        model_kwargs={"checklist_template": CHECKLIST_TEMPLATE},
    )
    technician_id = fleet["technician_ids"][0]

    visit = schedule_visit(
        api,
        fleet["contract_id"],
        fleet["equipment_ids"][0],
        WINDOW_START,
        WINDOW_END,
        technician_id,
    )
    assert_fields(
        visit,
        visit_status="SCHEDULED",
        safety_doc_status="PENDING",
        assigned_technician_id=technician_id,
        planned_minutes=WINDOW_MINUTES,
        checklist_total_count=len(CHECKLIST_TEMPLATE),
        checklist_resolved_count=0,
        checklist_failed_count=0,
        safety_critical_failed_count=0,
        consumables_replaced_count=0,
        pm_credit_earned=False,
    )
    assert_null_fields(
        visit,
        "started_at",
        "completed_at",
        "usage_hours_at_visit",
        "inspection_summary",
        "safety_doc_certified_by_id",
        "safety_doc_rejection_reason",
        "cancellation_reason",
    )
    assert [element["code"] for element in visit["checklist"]] == [
        element["code"] for element in CHECKLIST_TEMPLATE
    ]
    for element in visit["checklist"]:
        assert element["result"] == "PENDING", (
            f"checklist element {element['code']} should start PENDING, "
            f"got {element['result']!r}"
        )
    assert_common_fields(visit, expected_version=1)

    part = new_part(api, fleet["model_id"], initial_on_hand_qty=5)
    assert_fields(
        part,
        lifecycle_status="ACTIVE",
        on_hand_qty=5,
        refurb_on_hand_qty=0,
        allocated_qty=0,
    )
    assert_common_fields(part, expected_version=1)

    technician = read_technician(api, technician_id)
    assert technician["committed_minutes"] == WINDOW_MINUTES


# ─── The contract's legal hops ────────────────────────────────────────────────


def test_contract_walks_draft_active_suspended_active_bumping_version_once_per_hop(
    api, admin
):
    """
    Activation, suspension and reinstatement each advance the contract by exactly one
    version, and the suspension reason is stored on the way down and cleared on the
    way back up.

    "The contract's `status` traverses `DRAFT` → `ACTIVE`, then optionally cycles
    `ACTIVE` → `SUSPENDED` → `ACTIVE` any number of times, then advances `ACTIVE` →
    `RENEWAL_QUOTED`, may re-enter `RENEWAL_QUOTED` from itself on a re-quote, and
    finally forks to either `RENEWED` or `EXPIRED`."

    Design: Corner/state_machines/contract_walks_draft_active_suspended_active_with_a_version_bump_per_hop
    """
    fleet = _world(api, CLOCK_0800, ["SN-SM-1"], activate=False)
    contract_id = fleet["contract_id"]

    drafted = fleet["contract"]
    assert_fields(drafted, status="DRAFT")
    assert_common_fields(drafted, expected_version=1)
    assert_null_fields(drafted, "suspension_reason")

    response = api.activate_contract(contract_id, admin)
    assert response.json()["response_type"] == "object"
    activated = validate_success(response, 200)
    assert_fields(activated, status="ACTIVE", version=2)

    response = api.suspend_contract(
        contract_id, suspend_payload(reason="BILLING_DISPUTE"), admin
    )
    assert response.json()["response_type"] == "object"
    suspended = validate_success(response, 200)
    assert_fields(
        suspended, status="SUSPENDED", suspension_reason="BILLING_DISPUTE", version=3
    )

    response = api.reinstate_contract(contract_id, admin)
    assert response.json()["response_type"] == "object"
    reinstated = validate_success(response, 200)
    assert_fields(reinstated, status="ACTIVE", version=4)
    assert_null_fields(reinstated, "suspension_reason")

    final = read_contract(api, contract_id)
    assert_fields(final, status="ACTIVE", version=4)
    assert_null_fields(final, "suspension_reason")


def test_reinstatement_is_refused_while_a_unit_is_locked_out_and_succeeds_after_clearance(
    api, admin
):
    """
    The same reinstate request is refused with 409 while the club carries an open
    lockout and accepted once a documented clearance has returned the unit to service.

    "A single locked-out treadmill anywhere on the site blocks reinstatement with
    `ERR_SAFETY_LOCKOUT_OPEN`, and the only way through is the documented clearance
    work described in §3.5."

    Design: Corner/state_machines/reinstate_is_guarded_by_the_clubs_open_lockout_count
    """
    fleet = _world(
        api, CLOCK_0800, ["SN-RI-1"], [TECH_INSPECTOR, TECH_INSPECTOR_2]
    )
    club_id = fleet["club_id"]
    contract_id = fleet["contract_id"]
    equipment_id = fleet["equipment_ids"][0]
    worker_id, signer_id = fleet["technician_ids"]

    call = open_call(
        api, contract_id, equipment_id, severity="MAJOR", symptom_code="DECK_CRACK"
    )
    get_success_data(
        api.tag_out_equipment(
            equipment_id, tag_out_payload(), inspector_headers(signer_id)
        )
    )
    assert read_club(api, club_id)["open_safety_lockout_count"] == 1

    dispatch_call(api, call["id"], CLOCK_0800, worker_id)
    set_clock(api, CLOCK_0900)
    arrive_call(api, call["id"], worker_id)
    get_success_data(
        api.suspend_contract(contract_id, suspend_payload(reason="SAFETY_REVIEW"), admin)
    )

    before = read_contract(api, contract_id)
    assert before["status"] == "SUSPENDED"
    refused = api.reinstate_contract(contract_id, admin)
    validate_error(refused, ERR_SAFETY_LOCKOUT_OPEN, 409)
    blocked = read_contract(api, contract_id)
    assert_fields(blocked, status="SUSPENDED", version=before["version"])

    set_clock(api, CLOCK_1100)
    resolved = get_success_data(
        api.resolve_service_call(
            call["id"],
            resolve_payload(
                resolution_code="DECK_REPLACED",
                safety_clearance_technician_id=signer_id,
            ),
            technician_headers(worker_id),
        )
    )
    assert_fields(resolved, status="RESOLVED")

    unit = read_equipment(api, equipment_id)
    assert_fields(
        unit,
        lifecycle_status="IN_SERVICE",
        safety_lockout_reason=None,
        downtime_minutes_ytd=180,
        health_score_variant="USAGE_BASED",
    )
    assert_instant(unit["last_safety_clearance_at"], CLOCK_1100, "last_safety_clearance_at")
    assert_two_decimals(unit["health_score"], "93.50", "health_score")
    assert read_club(api, club_id)["open_safety_lockout_count"] == 0

    worked = read_call(api, call["id"])
    assert_fields(
        worked,
        sla_target_minutes=SLA_RESPONSE_MINUTES["GOLD"],
        response_minutes=60,
        sla_met=True,
    )

    event = read_event(api, event_for_call(api, call["id"])["id"])
    assert_fields(event, status="CLOSED", downtime_minutes=DOWNTIME_GRACE_MINUTES["GOLD"])
    assert_money(event["provisional_credit_cents"], 0, "provisional_credit_cents")

    response = api.reinstate_contract(contract_id, admin)
    cleared = validate_success(response, 200)
    assert_fields(cleared, status="ACTIVE")
    assert_null_fields(cleared, "suspension_reason")


# ─── Service-call creation and its side-effect set ────────────────────────────


def test_opening_a_non_injury_call_stamps_the_target_downs_the_unit_and_opens_the_outage(
    api,
):
    """
    One POST pins the response promise from tier and severity, drives the unit
    IN_SERVICE -> DOWN and opens the companion outage row, all without raising a
    safety review.

    "`reported_at` is stamped from the logical clock, `status` is `OPEN`,
    `parts_hold_count` starts at `0`, and `sla_target_minutes` is frozen onto the call
    as `round_half_up(contract.sla_response_minutes × SEVERITY_SLA_FACTOR[severity])`,
    where the severity factor is `0.5` for `CRITICAL`, `1.0` for `MAJOR` and `2.0` for
    `MINOR`."

    Design: Corner/state_machines/service_call_creation_fires_its_whole_side_effect_set
    """
    fleet = _world(api, CLOCK_0930, ["SN-SE-1"])
    club_id = fleet["club_id"]
    contract_id = fleet["contract_id"]
    equipment_id = fleet["equipment_ids"][0]

    response = api.create_service_call(
        service_call_payload(
            contract_id, equipment_id, severity="MAJOR", symptom_code="BELT_NOISE"
        ),
        fleet["manager"],
    )
    call = validate_success(response, 201)
    assert_fields(
        call,
        status="OPEN",
        sla_target_minutes=SLA_RESPONSE_MINUTES["GOLD"],
        safety_review_required=False,
        parts_hold_count=0,
    )
    assert_instant(call["reported_at"], CLOCK_0930, "reported_at")
    assert_null_fields(call, "response_minutes", "sla_met")

    unit = read_equipment(api, equipment_id)
    assert_fields(
        unit,
        lifecycle_status="DOWN",
        safety_lockout_reason=None,
        downtime_minutes_ytd=0,
    )

    event = event_for_call(api, call["id"])
    assert_fields(
        event,
        status="OPEN",
        contract_id=contract_id,
        equipment_id=equipment_id,
        service_call_id=call["id"],
    )
    assert_instant(event["started_at"], CLOCK_0930, "started_at")
    assert_null_fields(event, "downtime_minutes")

    assert read_club(api, club_id)["open_safety_lockout_count"] == 0


def test_opening_an_injury_call_tags_the_unit_out_and_halves_the_response_target(api):
    """
    The injury branch of the same creation endpoint tags the unit out for MEMBER_INJURY,
    raises the safety review and halves the GOLD target through the CRITICAL factor.

    "The machine's `lifecycle_status` moves to `TAGGED_OUT` with
    `safety_lockout_reason` `MEMBER_INJURY` when an injury was reported; otherwise it
    moves from `IN_SERVICE` to `DOWN`, and a machine that was already `TAGGED_OUT`
    stays `TAGGED_OUT`."

    Design: Corner/state_machines/injury_report_tags_the_unit_out_and_halves_the_response_target
    """
    fleet = _world(api, CLOCK_0800, ["SN-IJ-1"])
    club_id = fleet["club_id"]
    equipment_id = fleet["equipment_ids"][0]

    response = api.create_service_call(
        service_call_payload(
            fleet["contract_id"],
            equipment_id,
            severity="CRITICAL",
            symptom_code="MEMBER_FALL",
            injury_reported=True,
        ),
        fleet["manager"],
    )
    call = validate_success(response, 201)
    assert_fields(
        call,
        status="OPEN",
        sla_target_minutes=60,
        injury_reported=True,
        safety_review_required=True,
    )

    unit = read_equipment(api, equipment_id)
    assert_fields(
        unit, lifecycle_status="TAGGED_OUT", safety_lockout_reason="MEMBER_INJURY"
    )
    assert read_club(api, club_id)["open_safety_lockout_count"] == 1

    event = event_for_call(api, call["id"])
    assert_fields(event, status="OPEN")
    assert_instant(event["started_at"], CLOCK_0800, "started_at")


# ─── The clearance signature on a safety-review resolution ────────────────────


def _injury_call_on_site(api):
    """An injury CRITICAL call on a tagged-out unit, ON_SITE with inspector T2, at 10:00."""
    fleet = _world(
        api, CLOCK_0800, ["SN-CL-1"], [TECH_INSPECTOR, TECH_INSPECTOR_2]
    )
    worker_id, signer_id = fleet["technician_ids"]
    call = open_call(
        api,
        fleet["contract_id"],
        fleet["equipment_ids"][0],
        severity="CRITICAL",
        symptom_code="MEMBER_FALL",
        injury_reported=True,
    )
    dispatch_call(api, call["id"], CLOCK_0800, worker_id)
    set_clock(api, CLOCK_0830)
    arrive_call(api, call["id"], worker_id)
    set_clock(api, CLOCK_1000)
    return fleet, call["id"], worker_id, signer_id


@pytest.mark.parametrize(
    ("sign_with_self", "expected_error", "expected_status"),
    [
        pytest.param(False, ERR_SAFETY_CLEARANCE_REQUIRED, 422, id="no-signature"),
        pytest.param(True, ERR_SEGREGATION_OF_DUTIES, 409, id="self-signature"),
    ],
)
def test_resolving_a_safety_review_call_refuses_a_missing_or_self_clearance_signature(
    api, sign_with_self, expected_error, expected_status
):
    """
    A safety-review resolution without a clearance signature is 422 and one signed by
    the technician who did the work is 409; in both cases the call stays ON_SITE.

    "If `safety_review_required` is `true`, that clearance must be present, must
    reference a technician whose `is_safety_inspector` is `true`, and must differ from
    the call's own `assigned_technician_id`; a missing or uncertified signature is
    `ERR_SAFETY_CLEARANCE_REQUIRED` and a self-signature is
    `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/state_machines/resolving_a_safety_review_call_demands_an_independent_clearance_signature
    """
    fleet, call_id, worker_id, _signer_id = _injury_call_on_site(api)

    before = read_call(api, call_id)
    assert before["status"] == "ON_SITE"

    payload = resolve_payload(
        resolution_code="GUARD_REPLACED",
        safety_clearance_technician_id=worker_id if sign_with_self else None,
    )
    refused = api.resolve_service_call(call_id, payload, technician_headers(worker_id))
    validate_error(refused, expected_error, expected_status)

    after = read_call(api, call_id)
    assert_fields(after, status="ON_SITE", version=before["version"])
    assert_null_fields(after, "resolved_at", "safety_clearance_technician_id")

    unit = read_equipment(api, fleet["equipment_ids"][0])
    assert_fields(
        unit, lifecycle_status="TAGGED_OUT", safety_lockout_reason="MEMBER_INJURY"
    )
    assert read_club(api, fleet["club_id"])["open_safety_lockout_count"] == 1


def test_an_independent_inspectors_signature_resolves_the_call_and_clears_the_lockout(
    api,
):
    """
    A second inspector's signature carries the resolution through: the call is RESOLVED,
    the machine returns to service with the clearance stamped and the club's lockout
    count falls back to zero.

    "The same person may not stand on both sides of a safety control: the certifier or
    rejecter of a visit's documentation must differ from that visit's
    `assigned_technician_id`, and the clearance signer named on a resolve must differ
    from that call's `assigned_technician_id`; a violation on safety-document certify,
    safety-document reject or call resolve answers `ERR_SEGREGATION_OF_DUTIES` (409)."

    Design: Corner/state_machines/resolving_a_safety_review_call_demands_an_independent_clearance_signature
    """
    fleet, call_id, worker_id, signer_id = _injury_call_on_site(api)

    response = api.resolve_service_call(
        call_id,
        resolve_payload(
            resolution_code="GUARD_REPLACED",
            safety_clearance_technician_id=signer_id,
        ),
        technician_headers(worker_id),
    )
    resolved = validate_success(response, 200)
    assert_fields(
        resolved,
        status="RESOLVED",
        safety_clearance_technician_id=signer_id,
        resolution_code="GUARD_REPLACED",
        response_minutes=30,
        sla_met=True,
        sla_target_minutes=60,
    )
    assert_instant(resolved["resolved_at"], CLOCK_1000, "resolved_at")

    unit = read_equipment(api, fleet["equipment_ids"][0])
    assert_fields(
        unit,
        lifecycle_status="IN_SERVICE",
        safety_lockout_reason=None,
        downtime_minutes_ytd=120,
    )
    assert_instant(
        unit["last_safety_clearance_at"], CLOCK_1000, "last_safety_clearance_at"
    )
    assert read_club(api, fleet["club_id"])["open_safety_lockout_count"] == 0

    event = read_event(api, event_for_call(api, call_id)["id"])
    assert_fields(event, status="CLOSED", downtime_minutes=120)
    assert_money(event["provisional_credit_cents"], 0, "provisional_credit_cents")

    assignment = assignment_for_call(api, call_id)
    assert_fields(assignment, status="COMPLETED")
    assert read_technician(api, worker_id)["committed_minutes"] == 0


# ─── Triggers a state machine refuses ─────────────────────────────────────────

DRAFT_REFUSED_TRIGGERS = [
    pytest.param(
        lambda api, contract_id, headers: api.suspend_contract(
            contract_id, suspend_payload(reason="TOO_EARLY"), headers
        ),
        id="suspend",
    ),
    pytest.param(
        lambda api, contract_id, headers: api.reinstate_contract(contract_id, headers),
        id="reinstate",
    ),
    pytest.param(
        lambda api, contract_id, headers: api.create_renewal_quote(
            contract_id, renewal_quote_payload(1), headers
        ),
        id="renewal-quote",
    ),
]


@pytest.mark.parametrize("trigger", DRAFT_REFUSED_TRIGGERS)
def test_a_draft_contract_refuses_suspension_reinstatement_and_renewal_quoting(
    api, admin, trigger
):
    """
    From DRAFT the only accepted lifecycle action is activation: suspend, reinstate and
    renewal quoting all answer 409 without moving the row, and the quote attempt is
    refused on state grounds even though its version token is the live one.

    "A contract lifecycle action must match the contract's `status`: activation
    requires `DRAFT`, suspension requires `ACTIVE`, reinstatement requires
    `SUSPENDED`, and renewal quoting requires `ACTIVE` or `RENEWAL_QUOTED`; otherwise
    `ERR_CONTRACT_INVALID_STATE` (409)."

    Design: Corner/state_machines/draft_contract_refuses_every_trigger_except_activate
    """
    fleet = _world(api, CLOCK_0800, ["SN-DR-1"], activate=False)
    contract_id = fleet["contract_id"]
    assert fleet["contract"]["version"] == 1

    refused = trigger(api, contract_id, admin)
    validate_error(refused, ERR_CONTRACT_INVALID_STATE, 409)

    contract = read_contract(api, contract_id)
    assert_fields(contract, status="DRAFT", version=1)
    assert_null_fields(contract, "suspension_reason")
    assert rows_of(api.list_renewal_quotes(admin, contract_id=contract_id)) == []


ON_SITE_REFUSED_TRIGGERS = [
    pytest.param(
        lambda api, call_id, technician_id, second_technician_id: api.dispatch_service_call(
            call_id,
            dispatch_payload("2026-08-15T14:00:00Z", second_technician_id),
            SERVICE_COORDINATOR,
        ),
        id="second-dispatch",
    ),
    pytest.param(
        lambda api, call_id, technician_id, second_technician_id: api.resume_service_call(
            call_id, technician_headers(technician_id)
        ),
        id="resume",
    ),
]


@pytest.mark.parametrize("trigger", ON_SITE_REFUSED_TRIGGERS)
def test_an_on_site_call_refuses_a_second_dispatch_and_a_resume(api, trigger):
    """
    A call that has already been attended answers the call machine's own state error for
    a second dispatch and for a resume, and no second reservation is minted.

    "A service-call action must match the call's `status`: dispatch requires `OPEN`,
    arrival requires `DISPATCHED`, parts hold and resolve require `ON_SITE`, resume
    requires `PARTS_HOLD`, and cancellation requires `OPEN` or `DISPATCHED`; otherwise
    `ERR_CALL_INVALID_STATE` (409)."

    Design: Corner/state_machines/on_site_call_and_scheduled_visit_refuse_out_of_order_triggers
    """
    fleet = _world(api, CLOCK_0800, ["SN-OT-1"], [TECH_PLAIN, TECH_SECOND])
    first_id, second_id = fleet["technician_ids"]

    call = open_call(
        api,
        fleet["contract_id"],
        fleet["equipment_ids"][0],
        severity="MAJOR",
        symptom_code="BELT_NOISE",
    )
    dispatch_call(api, call["id"], CLOCK_0800, first_id)
    set_clock(api, CLOCK_0900)
    on_site = arrive_call(api, call["id"], first_id)
    assert on_site["status"] == "ON_SITE"

    refused = trigger(api, call["id"], first_id, second_id)
    validate_error(refused, ERR_CALL_INVALID_STATE, 409)

    assert read_call(api, call["id"])["status"] == "ON_SITE"
    assert_fields(assignment_for_call(api, call["id"]), status="CONFIRMED")
    assert (
        read_technician(api, first_id)["committed_minutes"]
        == SEVERITY_PLANNED_MINUTES["MAJOR"]
    )
    assert read_technician(api, second_id)["committed_minutes"] == 0


SCHEDULED_VISIT_REFUSED_TRIGGERS = [
    pytest.param(
        lambda api, visit_id, technician_id: api.record_checklist_result(
            visit_id,
            checklist_result_payload("BELT_TENSION", result="PASS"),
            technician_headers(technician_id),
        ),
        id="checklist-result",
    ),
    pytest.param(
        lambda api, visit_id, technician_id: api.complete_visit(
            visit_id, technician_headers(technician_id)
        ),
        id="complete",
    ),
]


@pytest.mark.parametrize("trigger", SCHEDULED_VISIT_REFUSED_TRIGGERS)
def test_a_scheduled_visit_refuses_checklist_recording_and_completion(api, trigger):
    """
    Work recorded against a visit nobody has started yet is refused on the visit's own
    state, and the checklist element it named is left untouched.

    "A visit action must match `visit_status`: start requires `SCHEDULED`, checklist
    recording and completion require `IN_PROGRESS`, cancellation requires `SCHEDULED`,
    and marking missed requires `SCHEDULED` together with a logical clock at or after
    `window_end`; otherwise `ERR_VISIT_INVALID_STATE` (409)."

    Design: Corner/state_machines/on_site_call_and_scheduled_visit_refuse_out_of_order_triggers
    """
    fleet = _world(
        api,
        CLOCK_0900,
        ["SN-OT-2"],
        [TECH_PLAIN],
        model_kwargs={"checklist_template": [checklist_item("BELT_TENSION", consumable=True)]},
    )
    technician_id = fleet["technician_ids"][0]

    visit = schedule_visit(
        api,
        fleet["contract_id"],
        fleet["equipment_ids"][0],
        WINDOW_START,
        WINDOW_END,
        technician_id,
    )
    assert visit["visit_status"] == "SCHEDULED"

    refused = trigger(api, visit["id"], technician_id)
    validate_error(refused, ERR_VISIT_INVALID_STATE, 409)

    after = read_visit(api, visit["id"])
    assert_fields(
        after,
        visit_status="SCHEDULED",
        safety_doc_status="PENDING",
        checklist_resolved_count=0,
    )
    assert after["checklist"][0]["result"] == "PENDING"
    assert_null_fields(after, "started_at", "completed_at")
    assert read_technician(api, technician_id)["committed_minutes"] == WINDOW_MINUTES


def test_certifying_a_never_submitted_document_reports_the_document_dimensions_error(
    api,
):
    """
    The documentation dimension answers for itself: certifying a document still in
    PENDING is a safety-document state error even though the visit it belongs to is
    legitimately IN_PROGRESS.

    "A safety-document action must match `safety_doc_status`: submission requires
    `PENDING` or `REJECTED` with `visit_status` of `IN_PROGRESS` or `COMPLETED`, while
    certification and rejection require `SUBMITTED`; otherwise
    `ERR_SAFETY_DOC_INVALID_STATE` (409)."

    Design: Corner/state_machines/safety_doc_and_part_order_report_their_own_dimension_state_errors
    """
    fleet = _world(
        api,
        CLOCK_0800,
        ["SN-DP-2"],
        [TECH_PLAIN, TECH_INSPECTOR_2],
        model_kwargs={"checklist_template": [checklist_item("BELT_TENSION", consumable=True)]},
    )
    worker_id, inspector_id = fleet["technician_ids"]

    visit = schedule_visit(
        api,
        fleet["contract_id"],
        fleet["equipment_ids"][0],
        CLOCK_0800,
        CLOCK_0930,
        worker_id,
    )
    started = start_visit(api, visit["id"], worker_id)
    assert_fields(started, visit_status="IN_PROGRESS", safety_doc_status="PENDING")

    refused = api.certify_safety_doc(visit["id"], inspector_headers(inspector_id))
    validate_error(refused, ERR_SAFETY_DOC_INVALID_STATE, 409)

    after = read_visit(api, visit["id"])
    assert_fields(after, safety_doc_status="PENDING", visit_status="IN_PROGRESS")
    assert_null_fields(after, "safety_doc_certified_by_id", "inspection_summary")


def test_installing_a_cancelled_part_order_reports_the_orders_own_state_error(api, coordinator):
    """
    The part order answers for itself: installing a CANCELLED order is refused on the
    order's state even though the owning call is still legitimately parked in
    PARTS_HOLD, and the cancelled allocation stays returned to stock.

    "Part-order install and cancel require the order to be `ALLOCATED`, and install
    additionally requires the owning call to be in `PARTS_HOLD`; otherwise
    `ERR_PART_ORDER_INVALID_STATE` (409)."

    Design: Corner/state_machines/safety_doc_and_part_order_report_their_own_dimension_state_errors
    """
    fleet = _world(
        api,
        CLOCK_0800,
        ["SN-DP-1"],
        [TECH_PLAIN],
        contract_kwargs={"initial_parts_allowance_cents": 500000},
    )
    contract_id = fleet["contract_id"]
    technician_id = fleet["technician_ids"][0]
    part = new_part(
        api,
        fleet["model_id"],
        part_number="BELT-STD",
        category="WEAR",
        unit_price_cents=8000,
        initial_on_hand_qty=5,
    )

    call = call_on_site(
        api,
        contract_id,
        fleet["equipment_ids"][0],
        technician_id,
        CLOCK_0800,
        severity="MAJOR",
        symptom_code="BELT_NOISE",
    )
    order = place_hold(api, call["id"], technician_id, part["id"], 1, "NEW")
    get_success_data(
        api.cancel_part_order(order["id"], part_order_cancel_payload(), coordinator)
    )

    refused = api.install_part_order(order["id"], technician_headers(technician_id))
    validate_error(refused, ERR_PART_ORDER_INVALID_STATE, 409)

    after = read_part_order(api, order["id"])
    assert_fields(after, status="CANCELLED")
    assert_null_fields(after, "installed_at")

    assert_fields(read_call(api, call["id"]), status="PARTS_HOLD", parts_hold_count=1)
    assert_fields(read_part(api, part["id"]), on_hand_qty=5, allocated_qty=0)
    assert_money(
        read_contract(api, contract_id)["parts_allowance_remaining_cents"],
        500000,
        "parts_allowance_remaining_cents",
    )


def test_a_waived_downtime_event_cannot_be_waived_a_second_time(api, admin):
    """
    WAIVED is where the outage machine stops: a second waiver is refused and the reason
    recorded by the first one is left in place.

    "Waiving is permitted from `OPEN`, from `CLOSED` and from `RECONCILED`; a `WAIVED`
    event cannot be waived again and answers `ERR_DOWNTIME_INVALID_STATE`."

    Design: Corner/state_machines/waived_event_and_released_assignment_cannot_be_acted_on_twice
    """
    fleet = _world(api, CLOCK_0800, ["SN-TW-1"])
    call = open_call(
        api,
        fleet["contract_id"],
        fleet["equipment_ids"][0],
        severity="MAJOR",
        symptom_code="BELT_NOISE",
    )
    event = event_for_call(api, call["id"])
    waived = get_success_data(
        api.waive_downtime_event(event["id"], waive_payload("GOODWILL"), admin)
    )
    assert_fields(waived, status="WAIVED", waive_reason="GOODWILL")

    refused = api.waive_downtime_event(
        event["id"], waive_payload("GOODWILL_AGAIN"), admin
    )
    validate_error(refused, ERR_DOWNTIME_INVALID_STATE, 409)

    after = read_event(api, event["id"])
    assert_fields(after, status="WAIVED", waive_reason="GOODWILL")
    assert_fields(after, version=waived["version"])


def test_a_released_assignment_cannot_be_released_a_second_time(api, coordinator):
    """
    RELEASED is terminal for a reservation: the second release is refused, the original
    reason survives and the technician's minutes are given back once and once only.

    "A `ServiceCoordinator` or a `ContractAdministrator` may release a `RESERVED` or
    `CONFIRMED` slot directly, supplying a `reason` that is stored verbatim in
    `release_reason`; a slot already `RELEASED` or `COMPLETED` answers
    `ERR_ASSIGNMENT_INVALID_STATE`."

    Design: Corner/state_machines/waived_event_and_released_assignment_cannot_be_acted_on_twice
    """
    fleet = _world(api, CLOCK_0800, ["SN-TW-2"], [TECH_SECOND])
    technician_id = fleet["technician_ids"][0]

    visit = schedule_visit(
        api,
        fleet["contract_id"],
        fleet["equipment_ids"][0],
        WINDOW_START,
        WINDOW_END,
        technician_id,
    )
    assignment = assignment_for_visit(api, visit["id"])
    assert assignment["status"] == "RESERVED"

    released = get_success_data(
        api.release_assignment(
            assignment["id"], release_payload("ROUTE_REBALANCE"), coordinator
        )
    )
    assert_fields(released, status="RELEASED", release_reason="ROUTE_REBALANCE")
    assert read_technician(api, technician_id)["committed_minutes"] == 0

    refused = api.release_assignment(
        assignment["id"], release_payload("ROUTE_REBALANCE_AGAIN"), coordinator
    )
    validate_error(refused, ERR_ASSIGNMENT_INVALID_STATE, 409)

    after = read_assignment(api, assignment["id"])
    assert_fields(
        after,
        status="RELEASED",
        release_reason="ROUTE_REBALANCE",
        version=released["version"],
    )
    assert read_technician(api, technician_id)["committed_minutes"] == 0
    assert_fields(
        read_visit(api, visit["id"]),
        visit_status="SCHEDULED",
        assigned_technician_id=technician_id,
    )
