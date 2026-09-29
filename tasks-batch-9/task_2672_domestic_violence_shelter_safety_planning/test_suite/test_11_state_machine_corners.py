"""State-machine corners: a clock-driven expiry, a cross-dimension precondition, the full
side-effect set of one transition, terminal-state lockdown, and the declared initial states.
"""

from test_helpers import (
    ADMIN_HEADERS,
    ApiErrorId,
    MODERATE_FACTORS,
    advance_clock,
    api_client,
    assert_bed_ledger_invariant,
    assert_same_instant,
    assert_screening_request,
    assert_timestamp_with_millis,
    create_shelter_payload,
    create_shelter_unit_payload,
    dispose_call,
    file_case,
    get_success_data,
    read_admission,
    read_client,
    read_staff,
    read_unit,
    record_outcome,
    report_compromise,
    seed_client,
    seed_client_with_assessed_call,
    seed_hotline_advocate,
    seed_hotline_call,
    seed_legal_advocate,
    seed_privacy_officer,
    seed_protective_order_case,
    seed_reserved_admission,
    seed_risk_assessment,
    seed_screening_request,
    seed_shelter_scene,
    validate_error,
    validate_paginated,
    validate_success,
    waitlist_screening,
)

STARTUP_CLOCK = "2026-08-01T00:00:00.000Z"
TWO_ADULTS = {"household_size": 2, "minor_children_count": 0, "accessibility_required": False}
PAGE = {"limit": 10, "offset": 0}


def test_a_waitlisted_request_survives_the_deadline_instant_and_expires_one_second_later():
    """Expiry is strict: at the deadline the row lives, a second past it the row is EXPIRED.

    PRD: "On every clock advance, any request still `WAITLISTED` whose `requested_entry_date`
    plus 14 days, taken at `00:00:00Z`, is strictly earlier than the new reading moves
    `WAITLISTED` → `EXPIRED`, which is terminal."

    Design: Corner/state_machines/waitlisted_screening_request_expires_when_the_clock_passes_the_fourteen_day_window
    """
    scene = seed_shelter_scene(unit_overrides={"unit_label": "A1", "unit_type": "STANDARD"})
    client, call, _ra = seed_client_with_assessed_call(
        scene.advocate,
        client_overrides=dict(TWO_ADULTS, client_code="C-2001", legal_name="Jena Ross"),
        assessment_overrides=dict(MODERATE_FACTORS),
        call_overrides={"presenting_concerns": "Wants a bed but can wait a week."},
    )
    request = seed_screening_request(
        scene.advocate, client["id"], call["id"], scene.shelter["id"],
        requested_entry_date="2026-08-07",
    )
    waitlisted = waitlist_screening(scene.manager, request["id"], scene.advocate.id)
    assert waitlisted["waitlist_position"] == 1
    assert waitlisted["decided_at"] == STARTUP_CLOCK

    at_boundary = advance_clock("2026-08-21T00:00:00Z")
    assert at_boundary["expired_screening_request_count"] == 0
    still_listed = get_success_data(
        api_client.get_screening_request(request["id"], scene.manager.headers)
    )
    assert still_listed["status"] == "WAITLISTED"
    assert still_listed["waitlist_position"] == 1

    past_boundary = advance_clock("2026-08-21T00:00:01Z")

    assert past_boundary["expired_screening_request_count"] == 1
    assert past_boundary["restaffed_posture_count"] == 0
    expired = get_success_data(
        api_client.get_screening_request(request["id"], scene.manager.headers)
    )
    assert expired["status"] == "EXPIRED"
    assert expired["waitlist_position"] is None
    advocate = read_staff(scene.advocate.id)
    assert advocate["secondary_trauma_index"] == 0.0
    assert advocate["wellness_posture"] == "OPEN"


def test_check_in_on_a_compromised_reservation_reports_the_compromise_not_the_state():
    """With the entry date reached, the leaked address is the only thing left to refuse.

    PRD: "It is barred while `location_security_status` is `COMPROMISED`, with
    `ERR_LOCATION_COMPROMISED`: a compromised reservation must be relocated before anybody
    walks through the door."

    Design: Corner/state_machines/check_in_on_a_compromised_reservation_rejected
    """
    scene, client, _request, admission = seed_reserved_admission(
        scene=seed_shelter_scene(unit_overrides={"unit_label": "A1", "unit_type": "STANDARD"}),
        client_overrides=dict(TWO_ADULTS, client_code="C-2002", legal_name="Kara Voss"),
        assessment_overrides=dict(MODERATE_FACTORS),
    )
    compromised = get_success_data(
        report_compromise(scene, admission["id"], compromise_source="ABUSER_CONTACT")
    )
    advance_clock("2026-08-07T12:00:00Z")

    response = api_client.check_in_admission(
        admission["id"], scene.manager.headers, {"school_enrollment_confirmed": False}
    )

    validate_error(response, ApiErrorId.ERR_LOCATION_COMPROMISED.value, 409)
    unchanged = read_admission(scene.manager, admission["id"])
    assert unchanged["occupancy_status"] == "RESERVED"
    assert unchanged["location_security_status"] == "COMPROMISED"
    assert unchanged["version"] == compromised["version"]
    unit = read_unit(scene.manager, scene.unit["id"])
    assert unit["reserved_beds"] == 2
    assert unit["occupied_beds"] == 0
    assert unit["available_beds"] == 2
    assert unit["status"] == "HOLD"
    assert_bed_ledger_invariant(unit)
    assert read_client(client["id"])["confidentiality_posture"] == "SEALED"


def test_a_screening_referred_disposal_performs_every_declared_side_effect_at_once():
    """One call produces the PENDING request, the copied household figures and both version bumps.

    PRD: "It creates exactly one screening request in status `PENDING`, with the client copied
    from the call, the call recorded as its originating `hotline_call_id`,
    `requested_shelter_id` and `requested_entry_date` taken from the payload,
    `household_size`, `minor_children_count` and `accessibility_required` copied from the
    survivor record rather than accepted from the caller, and `created_by_staff_id` stamped
    from the acting advocate."

    Design: Corner/state_machines/dispose_screening_referred_executes_every_declared_side_effect
    """
    advocate = seed_hotline_advocate("Rosa Marin")
    shelter = get_success_data(
        api_client.create_shelter(create_shelter_payload(name="Cedar House"), ADMIN_HEADERS)
    )
    get_success_data(
        api_client.create_shelter_unit(
            shelter["id"],
            create_shelter_unit_payload(unit_label="A1", unit_type="FAMILY_SUITE", bed_capacity=4),
            ADMIN_HEADERS,
        )
    )
    client, call, _ra = seed_client_with_assessed_call(
        advocate,
        client_overrides={
            "client_code": "C-2003",
            "legal_name": "Lena Marsh",
            "household_size": 4,
            "minor_children_count": 2,
            "accessibility_required": False,
        },
        assessment_overrides=dict(MODERATE_FACTORS),
    )

    response = dispose_call(
        advocate,
        call["id"],
        "SCREENING_REFERRED",
        requested_shelter_id=shelter["id"],
        requested_entry_date="2026-08-07",
    )

    disposed = validate_success(response, 200)
    assert disposed["status"] == "SCREENING_REFERRED"
    assert disposed["disposed_at"] == STARTUP_CLOCK
    assert disposed["version"] == 3
    survivor = read_client(client["id"])
    assert survivor["status"] == "ACTIVE"
    assert survivor["version"] == 3
    assert survivor["resource_referral_count"] == 0
    rows, meta = validate_paginated(
        api_client.list_screening_requests(
            advocate.headers, params=dict(PAGE, client_id=client["id"])
        )
    )
    assert meta["total_count"] == 1
    request = rows[0]
    assert request["status"] == "PENDING"
    assert request["version"] == 1
    assert request["household_size"] == 4
    assert request["minor_children_count"] == 2
    assert request["accessibility_required"] is False
    assert request["created_by_staff_id"] == advocate.id
    assert request["hotline_call_id"] == call["id"]
    assert request["requested_shelter_id"] == shelter["id"]
    assert request["requested_entry_date"] == "2026-08-07"
    assert request["assigned_advocate_id"] is None
    assert request["offered_shelter_unit_id"] is None
    assert request["waitlist_position"] is None
    assert request["promoted_from_waitlist"] is False
    assert request["decided_at"] is None
    assert_screening_request(request)
    _plans, plan_meta = validate_paginated(
        api_client.list_safety_plans(advocate.headers, params=dict(PAGE, client_id=client["id"]))
    )
    assert plan_meta["total_count"] == 0


def test_a_disposed_call_cannot_be_disposed_a_second_time():
    """SAFETY_PLAN_ONLY is terminal, so a different disposition on the same call is refused.

    PRD: "**Disposing** a `RISK_ASSESSED` call closes it down exactly one of three divergent
    branches, chosen by the `disposition` value in the payload, and each branch is terminal — a
    disposed call can never be disposed again, and an attempt is
    `ERR_INVALID_STATE_TRANSITION`."

    Design: Corner/state_machines/second_dispose_on_an_already_disposed_call_cannot_repeat
    """
    advocate = seed_hotline_advocate("Rosa Marin")
    client, call, _ra = seed_client_with_assessed_call(
        advocate,
        client_overrides=dict(TWO_ADULTS, client_code="C-2004", legal_name="Mira Otto"),
        assessment_overrides=dict(MODERATE_FACTORS),
        call_overrides={"presenting_concerns": "Wants a plan, not a bed."},
    )
    first = get_success_data(dispose_call(advocate, call["id"], "SAFETY_PLAN_ONLY"))
    assert first["version"] == 3

    response = dispose_call(advocate, call["id"], "RESOURCE_REFERRED")

    validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, 409)
    unchanged = get_success_data(api_client.get_hotline_call(call["id"], advocate.headers))
    assert unchanged["status"] == "SAFETY_PLAN_ONLY"
    assert unchanged["version"] == 3
    survivor = read_client(client["id"])
    assert survivor["resource_referral_count"] == 0
    assert survivor["version"] == 3
    plans, meta = validate_paginated(
        api_client.list_safety_plans(advocate.headers, params=dict(PAGE, client_id=client["id"]))
    )
    assert meta["total_count"] == 1
    assert plans[0]["status"] == "DRAFT"


def test_three_machines_each_open_in_their_declared_initial_state():
    """A drafted petition, a requested disclosure and an auto-authored plan all start where declared.

    PRD: "A drafted case begins at `PETITION_DRAFTED` with `refile_count` 0,
    `accompanying_advocate_id` null, `filed_court` null, both hearing timestamps null,
    `outcome_recorded_at` null and `version` 1."

    PRD: "A new event starts at `REQUESTED` with `released_field_keys` an empty array,
    `suppressed_field_keys` an empty array, `decided_by_staff_id` null, `decided_at` null,
    `late_filed` false and `version` 1."

    Design: Corner/state_machines/newly_created_rows_start_in_their_declared_initial_state
    """
    advocate = seed_hotline_advocate("Rosa Marin")
    legal = seed_legal_advocate("Nils Berg", max_caseload=12)
    officer = seed_privacy_officer("Opal Reed", max_caseload=12)
    client, call, _ra = seed_client_with_assessed_call(
        advocate,
        client_overrides=dict(TWO_ADULTS, client_code="C-2005", legal_name="Nadia Roe"),
        assessment_overrides=dict(MODERATE_FACTORS),
        call_overrides={"presenting_concerns": "Asking about a protective order."},
    )
    get_success_data(dispose_call(advocate, call["id"], "SAFETY_PLAN_ONLY"))

    case = validate_success(
        api_client.create_protective_order_case(
            {"client_id": client["id"], "order_type": "EMERGENCY_EX_PARTE"}, legal.headers
        ),
        201,
    )
    event = validate_success(
        api_client.create_disclosure_event(
            {
                "client_id": client["id"],
                "requested_by_staff_id": advocate.id,
                "kind": "PARTNER_AGENCY",
                "requester_org": "Northside Legal Aid",
                "requested_field_keys": ["client_code", "household_size"],
                "roi_signed_on": "2026-07-20",
                "roi_expires_on": "2026-09-20",
            },
            officer.headers,
        ),
        201,
    )
    plans, _meta = validate_paginated(
        api_client.list_safety_plans(advocate.headers, params=dict(PAGE, client_id=client["id"]))
    )

    assert case["status"] == "PETITION_DRAFTED"
    assert case["refile_count"] == 0
    assert case["filed_court"] is None
    assert case["hearing_start_utc"] is None
    assert case["hearing_end_utc"] is None
    assert case["accompanying_advocate_id"] is None
    assert case["outcome_recorded_at"] is None
    assert case["version"] == 1
    assert event["status"] == "REQUESTED"
    assert event["released_field_keys"] == []
    assert event["suppressed_field_keys"] == []
    assert event["decided_by_staff_id"] is None
    assert event["decided_at"] is None
    assert event["late_filed"] is False
    assert event["decision_deadline_utc"] is None
    assert event["version"] == 1
    plan = plans[0]
    assert plan["status"] == "DRAFT"
    assert plan["coverage_score"] == 0.00
    assert plan["revision_count"] == 0
    assert plan["superseded_by_plan_id"] is None
    assert plan["archived_at"] is None
    assert plan["version"] == 1
    assert plan["authored_by_staff_id"] == advocate.id
    assert read_client(client["id"])["protective_order_active"] is False


def test_a_granted_case_refuses_both_a_repeat_and_a_contradicting_outcome():
    """GRANTED is terminal, and the rejected calls leave the survivor's flags alone.

    PRD: "A record-outcome attempt against a case that is not `FILED` is
    `ERR_INVALID_STATE_TRANSITION`."

    Design: Corner/state_machines/granted_protective_order_cannot_record_a_second_outcome
    """
    advocate = seed_hotline_advocate("Rosa Marin")
    legal = seed_legal_advocate("Nils Berg", max_caseload=12)
    client = seed_client(
        advocate, client_code="C-2006", legal_name="Pia Lund", household_size=2,
        minor_children_count=0,
    )
    case = seed_protective_order_case(legal, client["id"], order_type="FULL_ORDER")
    get_success_data(
        file_case(legal, case["id"], legal.id, "2026-08-05T09:00:00Z", "2026-08-05T10:00:00Z")
    )
    advance_clock("2026-08-05T11:00:00Z")
    granted = get_success_data(record_outcome(legal, case["id"], "GRANTED"))

    repeat = record_outcome(legal, case["id"], "GRANTED")
    flip = record_outcome(legal, case["id"], "DENIED")

    validate_error(repeat, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, 409)
    validate_error(flip, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, 409)
    unchanged = get_success_data(
        api_client.get_protective_order_case(case["id"], legal.headers)
    )
    assert unchanged["status"] == "GRANTED"
    assert unchanged["refile_count"] == 0
    assert unchanged["version"] == granted["version"]
    assert unchanged["outcome_recorded_at"] == granted["outcome_recorded_at"]
    assert unchanged["outcome_recorded_at"] == "2026-08-05T11:00:00.000Z"
    assert_timestamp_with_millis(unchanged["outcome_recorded_at"])
    assert_same_instant(unchanged["hearing_start_utc"], "2026-08-05T09:00:00Z")
    assert_same_instant(unchanged["hearing_end_utc"], "2026-08-05T10:00:00Z")
    assert unchanged["accompanying_advocate_id"] == legal.id
    survivor = read_client(client["id"])
    assert survivor["protective_order_active"] is True
    assert survivor["confidentiality_posture"] == "HEIGHTENED"


def test_a_call_is_scored_once_and_a_repeat_assessment_is_refused():
    """The identical body a second time is a guarded rejection, not a silent no-op.

    PRD: "Because that is the only source state declared for the transition, a second
    assessment against the same call is refused with `ERR_INVALID_STATE_TRANSITION` — a call
    is scored once."

    Design: Corner/state_machines/second_risk_assessment_on_the_same_call_rejected
    """
    advocate = seed_hotline_advocate("Rosa Marin")
    client = seed_client(
        advocate, client_code="C-2007", legal_name="Quin Adler", household_size=2,
        minor_children_count=0,
    )
    call = seed_hotline_call(
        advocate, client["id"], presenting_concerns="He has a gun in the truck."
    )
    first = seed_risk_assessment(advocate, call["id"], **MODERATE_FACTORS)

    response = api_client.create_risk_assessment(
        call["id"], dict(MODERATE_FACTORS), advocate.headers
    )

    validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, 409)
    rows, meta = validate_paginated(
        api_client.list_risk_assessments(call["id"], advocate.headers, params=dict(PAGE))
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == first["id"]
    scored_call = get_success_data(api_client.get_hotline_call(call["id"], advocate.headers))
    assert scored_call["status"] == "RISK_ASSESSED"
    assert scored_call["version"] == 2
    survivor = read_client(client["id"])
    assert survivor["current_danger_score"] == 48.4
    assert survivor["current_risk_band"] == "MODERATE"
    assert survivor["version"] == 2


def test_each_disposition_branch_creates_only_its_own_artefact():
    """Three assessed calls fork three ways and no branch leaks another branch's child row.

    PRD: "Branch B, `SAFETY_PLAN_ONLY`, is the only branch that authors a safety plan, and it
    creates no screening request."

    PRD: "Branch C, `RESOURCE_REFERRED`, is a warm hand-off to an outside resource and creates
    no child row whatsoever."

    Design: Corner/state_machines/dispose_branching_reaches_each_of_the_three_terminal_states
    """
    advocate = seed_hotline_advocate("Rosa Marin")
    shelter = get_success_data(
        api_client.create_shelter(
            create_shelter_payload(name="Cedar House", nightly_rate_cents=8500), ADMIN_HEADERS
        )
    )
    get_success_data(
        api_client.create_shelter_unit(
            shelter["id"],
            create_shelter_unit_payload(unit_label="A1", unit_type="STANDARD", bed_capacity=4),
            ADMIN_HEADERS,
        )
    )
    people = []
    for code, name, concerns in (
        ("C-2008", "Rae Nolan", "Needs a bed."),
        ("C-2009", "Sela Ward", "Wants a written plan only."),
        ("C-2010", "Tara Finn", "Clinic asks for community resources."),
    ):
        people.append(
            seed_client_with_assessed_call(
                advocate,
                client_overrides=dict(TWO_ADULTS, client_code=code, legal_name=name),
                assessment_overrides=dict(MODERATE_FACTORS),
                call_overrides={"presenting_concerns": concerns},
            )
        )
    (client_a, call_a, _), (client_b, call_b, _), (client_c, call_c, _) = people

    referred = get_success_data(
        dispose_call(
            advocate,
            call_a["id"],
            "SCREENING_REFERRED",
            requested_shelter_id=shelter["id"],
            requested_entry_date="2026-08-07",
        )
    )
    planned = get_success_data(dispose_call(advocate, call_b["id"], "SAFETY_PLAN_ONLY"))
    handed_off = get_success_data(dispose_call(advocate, call_c["id"], "RESOURCE_REFERRED"))

    assert referred["status"] == "SCREENING_REFERRED"
    assert planned["status"] == "SAFETY_PLAN_ONLY"
    assert handed_off["status"] == "RESOURCE_REFERRED"
    for disposed in (referred, planned, handed_off):
        assert disposed["disposed_at"] == STARTUP_CLOCK
        assert disposed["version"] == 3
    for client, requests_expected, plans_expected, referral_count in (
        (client_a, 1, 0, 0),
        (client_b, 0, 1, 0),
        (client_c, 0, 0, 1),
    ):
        _rows, request_meta = validate_paginated(
            api_client.list_screening_requests(
                advocate.headers, params=dict(PAGE, client_id=client["id"])
            )
        )
        plan_rows, plan_meta = validate_paginated(
            api_client.list_safety_plans(
                advocate.headers, params=dict(PAGE, client_id=client["id"])
            )
        )
        assert request_meta["total_count"] == requests_expected
        assert plan_meta["total_count"] == plans_expected
        if plans_expected:
            assert plan_rows[0]["status"] == "DRAFT"
        survivor = read_client(client["id"])
        assert survivor["status"] == "ACTIVE"
        assert survivor["resource_referral_count"] == referral_count
