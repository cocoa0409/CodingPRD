"""Events: parallel permission/health dimensions, confirmation gates, cascades."""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    create_council_and_troop,
    create_registered_youth,
    create_member,
    setup_registered_youth_with_event,
    create_hold_registration,
    create_confirmed_registration,
    create_event_payload,
    create_event_registration_payload,
)

REG = TEST_USERS["registrar_headers"]
LEAD = TEST_USERS["leader_headers"]


def test_registration_parallel_permission_health_then_confirm(api):
    """PRD §3.6: "Signing the guardian permission form moves permission_status from
    UNSIGNED to SIGNED, and filing the health form moves health_status from MISSING
    to ON_FILE."
    PRD §3.6: "Confirming a registration is the gate that moves it from HOLD to
    CONFIRMED, and it requires every one of the following to hold: the registration
    is on HOLD, its permission_status is SIGNED, the event does not require a health
    form or else health_status is ON_FILE ... On success the registration becomes
    CONFIRMED and the event's confirmed_count increases by one."

    Design: Difficulty/non_linear_state_machine/event_registration_parallel_permission_health_dimensions
    """
    council, troop, member, event = setup_registered_youth_with_event(
        council_overrides={"name": "Par Council"},
        event_overrides={"title": "Summer Camp", "capacity": 5, "requires_health_form": True},
    )
    reg = create_hold_registration(event["id"], member["id"])
    get_success_data(api.sign_permission(reg["id"], LEAD))
    after_health = validate_success(api.file_health(reg["id"], LEAD), 200)
    assert after_health["permission_status"] == "SIGNED"
    assert after_health["health_status"] == "ON_FILE"

    confirmed = validate_success(api.confirm_registration(reg["id"], LEAD), 200)
    assert confirmed["status"] == "CONFIRMED"

    event_after = validate_success(api.get_event(event["id"], REG), 200)
    assert event_after["confirmed_count"] == 1


def test_sign_permission_and_file_health_keep_registration_on_hold(api):
    """PRD §3.6: "both are permitted only while the registration is still on HOLD and
    neither changes the registration's overall status."

    Design: Difficulty/non_linear_state_machine/event_registration_parallel_permission_health_dimensions
    """
    council, troop, member, event = setup_registered_youth_with_event(
        council_overrides={"name": "Par2"},
        event_overrides={"title": "Camp2", "capacity": 5, "requires_health_form": True},
    )
    reg = create_hold_registration(event["id"], member["id"])
    after_perm = validate_success(api.sign_permission(reg["id"], LEAD), 200)
    assert after_perm["permission_status"] == "SIGNED"
    assert after_perm["status"] == "HOLD"
    after_health = validate_success(api.file_health(reg["id"], LEAD), 200)
    assert after_health["health_status"] == "ON_FILE"
    assert after_health["status"] == "HOLD"


def test_event_cancel_cascades_to_registration_and_count(api):
    """PRD §3.6: "Cancelling an event ... moves the event to the terminal CANCELLED,
    cascades every registration still in HOLD or CONFIRMED to CANCELLED, and
    recomputes the event's confirmed_count to zero."

    Design: Difficulty/transitive_cascade/event_cancel_cascades_registration_and_count_depth2
    """
    council, troop, member, event = setup_registered_youth_with_event(
        council_overrides={"name": "Ec Council"},
        event_overrides={"title": "Hike", "capacity": 5, "requires_health_form": False},
    )
    reg = create_confirmed_registration(event["id"], member["id"], requires_health_form=False)
    assert reg["status"] == "CONFIRMED"

    cancelled = validate_success(api.cancel_event(event["id"], LEAD), 200)
    assert cancelled["status"] == "CANCELLED"

    reg_after = validate_success(api.get_event_registration(reg["id"], REG), 200)
    event_after = validate_success(api.get_event(event["id"], REG), 200)
    assert reg_after["status"] == "CANCELLED"
    assert event_after["confirmed_count"] == 0


def test_event_cancel_recomputes_confirmed_count_to_zero(api):
    """PRD §3.6: "it moves the event to the terminal CANCELLED, cascades every
    registration still in HOLD or CONFIRMED to CANCELLED, and recomputes the event's
    confirmed_count to zero."

    Design: Difficulty/transitive_cascade/event_cancel_cascades_registration_and_count_depth2
    """
    council, troop, member, event = setup_registered_youth_with_event(
        council_overrides={"name": "Ec2"},
        event_overrides={"title": "Hike2", "capacity": 5, "requires_health_form": False},
    )
    reg = create_confirmed_registration(event["id"], member["id"], requires_health_form=False)
    before = validate_success(api.get_event(event["id"], REG), 200)
    assert before["confirmed_count"] == 1

    validate_success(api.cancel_event(event["id"], LEAD), 200)
    after = validate_success(api.get_event(event["id"], REG), 200)
    assert after["confirmed_count"] == 0


def test_confirm_requires_event_open_not_locked(api):
    """PRD §3.6: "Locking an event moves its status from OPEN to LOCKED, which
    freezes any further confirmations (no new HOLD -> CONFIRMED transition is allowed
    once locked)."
    PRD §3.6: "Event and registration transitions attempted from states where they
    are not defined are rejected with ERR_INVALID_STATE."

    Design: Difficulty/cross_entity_state_dependency/registration_confirm_requires_event_open
    """
    council, troop, member, event = setup_registered_youth_with_event(
        council_overrides={"name": "X7b Council"},
        event_overrides={"title": "Lock Event", "capacity": 5, "requires_health_form": False},
    )
    reg = create_hold_registration(event["id"], member["id"])
    get_success_data(api.sign_permission(reg["id"], LEAD))
    get_success_data(api.lock_event(event["id"], LEAD))

    resp = api.confirm_registration(reg["id"], LEAD)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    reg_after = validate_success(api.get_event_registration(reg["id"], REG), 200)
    assert reg_after["status"] == "HOLD"


def test_confirm_on_locked_event_leaves_registration_on_hold(api):
    """PRD §3.6: "Locking an event moves its status from OPEN to LOCKED, which
    freezes any further confirmations (no new HOLD -> CONFIRMED transition is allowed
    once locked)."

    Design: Difficulty/cross_entity_state_dependency/registration_confirm_requires_event_open
    """
    council, troop, member, event = setup_registered_youth_with_event(
        council_overrides={"name": "X7c"},
        event_overrides={"title": "Lock Event 2", "capacity": 5, "requires_health_form": False},
    )
    reg = create_hold_registration(event["id"], member["id"])
    get_success_data(api.sign_permission(reg["id"], LEAD))
    get_success_data(api.lock_event(event["id"], LEAD))
    resp = api.confirm_registration(reg["id"], LEAD)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    reg_after = validate_success(api.get_event_registration(reg["id"], REG), 200)
    assert reg_after["status"] == "HOLD"


def test_confirm_forms_incomplete_reported_before_double_booked(api):
    """PRD §3.6: "A confirmation blocked specifically by an unsigned permission slip
    or a missing-but-required health form is rejected with ERR_FORMS_INCOMPLETE."
    PRD §3.9: "Thereafter the remaining business constraints apply in order —
    advancement completeness (ERR_REQUIREMENTS_INCOMPLETE), event-registration form
    completeness (ERR_FORMS_INCOMPLETE), booth conflict (ERR_BOOTH_CONFLICT), member
    double-booking (ERR_MEMBER_DOUBLE_BOOKED)."

    Design: Difficulty/priority_pair_validation_conflict/confirm_forms_incomplete_beats_double_booked
    """
    council, troop = create_council_and_troop(
        council_overrides={"name": "P10 Council"}, troop_overrides={"unit_number": "U-1001"}
    )
    member = create_registered_youth(troop["id"], full_name="Db Youth")

    event_a = get_success_data(
        api.create_event(
            troop["id"],
            create_event_payload(title="Event A", starts_at="2026-07-01T09:00:00Z",
                                 ends_at="2026-07-03T17:00:00Z", capacity=5, requires_health_form=False),
            LEAD,
        )
    )
    reg_a = create_hold_registration(event_a["id"], member["id"])
    get_success_data(api.sign_permission(reg_a["id"], LEAD))
    get_success_data(api.confirm_registration(reg_a["id"], LEAD))

    # Overlapping event B, registration left UNSIGNED so forms-incomplete applies.
    event_b = get_success_data(
        api.create_event(
            troop["id"],
            create_event_payload(title="Event B", starts_at="2026-07-02T09:00:00Z",
                                 ends_at="2026-07-04T17:00:00Z", capacity=5, requires_health_form=False),
            LEAD,
        )
    )
    reg_b = create_hold_registration(event_b["id"], member["id"])

    resp = api.confirm_registration(reg_b["id"], LEAD)
    validate_error(resp, ApiErrorId.ERR_FORMS_INCOMPLETE.value)


def test_confirm_double_booked_touching_event_rejected(api):
    """PRD §3.6: "Treating each event's [starts_at, ends_at] window as a closed
    interval, two windows collide if they overlap or even merely touch at an
    endpoint — a zero gap is a collision, since the buffer is inclusive. A
    confirmation that would give the member a second overlapping-or-touching
    confirmed registration is rejected with ERR_MEMBER_DOUBLE_BOOKED."

    Design: Difficulty/resource_temporal_overlap/member_double_book_closed_interval_touching_rejected
    """
    council, troop = create_council_and_troop(
        council_overrides={"name": "Db8 Council"}, troop_overrides={"unit_number": "U-1601"}
    )
    member = create_registered_youth(troop["id"], full_name="Db8 Youth")

    event_a = get_success_data(
        api.create_event(
            troop["id"],
            create_event_payload(title="A", starts_at="2026-09-01T09:00:00Z",
                                 ends_at="2026-09-01T12:00:00Z", capacity=5, requires_health_form=False),
            LEAD,
        )
    )
    reg_a = create_hold_registration(event_a["id"], member["id"])
    get_success_data(api.sign_permission(reg_a["id"], LEAD))
    get_success_data(api.confirm_registration(reg_a["id"], LEAD))

    # Event B starts exactly when A ends (touching) -> closed-interval collision.
    event_b = get_success_data(
        api.create_event(
            troop["id"],
            create_event_payload(title="B", starts_at="2026-09-01T12:00:00Z",
                                 ends_at="2026-09-01T15:00:00Z", capacity=5, requires_health_form=False),
            LEAD,
        )
    )
    reg_b = create_hold_registration(event_b["id"], member["id"])
    get_success_data(api.sign_permission(reg_b["id"], LEAD))

    resp = api.confirm_registration(reg_b["id"], LEAD)
    validate_error(resp, ApiErrorId.ERR_MEMBER_DOUBLE_BOOKED.value)

    reg_b_after = validate_success(api.get_event_registration(reg_b["id"], REG), 200)
    assert reg_b_after["status"] == "HOLD"


def test_confirm_unsigned_permission_reports_forms_incomplete_over_double_book(api):
    """PRD §3.6: "A confirmation blocked specifically by an unsigned permission slip
    or a missing-but-required health form is rejected with ERR_FORMS_INCOMPLETE."
    PRD §3.9: "they are evaluated in a fixed priority order so that the earliest
    applicable failure is the one reported."

    Design: Difficulty/priority_pair_validation_conflict/confirm_forms_incomplete_beats_double_booked
    """
    council, troop = create_council_and_troop(
        council_overrides={"name": "P10b"}, troop_overrides={"unit_number": "U-1002"}
    )
    member = create_registered_youth(troop["id"], full_name="Db Youth 2")

    event_a = get_success_data(
        api.create_event(
            troop["id"],
            create_event_payload(title="Event A2", starts_at="2026-07-01T09:00:00Z",
                                 ends_at="2026-07-03T17:00:00Z", capacity=5, requires_health_form=False),
            LEAD,
        )
    )
    reg_a = create_confirmed_registration(event_a["id"], member["id"], requires_health_form=False)
    assert reg_a["status"] == "CONFIRMED"

    event_b = get_success_data(
        api.create_event(
            troop["id"],
            create_event_payload(title="Event B2", starts_at="2026-07-02T09:00:00Z",
                                 ends_at="2026-07-04T17:00:00Z", capacity=5, requires_health_form=False),
            LEAD,
        )
    )
    reg_b = create_hold_registration(event_b["id"], member["id"])
    # Permission left UNSIGNED -> forms-incomplete fires before the double-book check.
    resp = api.confirm_registration(reg_b["id"], LEAD)
    validate_error(resp, ApiErrorId.ERR_FORMS_INCOMPLETE.value)
    reg_b_after = validate_success(api.get_event_registration(reg_b["id"], REG), 200)
    assert reg_b_after["status"] == "HOLD"


def test_confirm_double_booked_touching_leaves_first_confirmed(api):
    """PRD §3.6: "two windows collide if they overlap or even merely touch at an
    endpoint — a zero gap is a collision, since the buffer is inclusive. A
    confirmation that would give the member a second overlapping-or-touching confirmed
    registration is rejected with ERR_MEMBER_DOUBLE_BOOKED."

    Design: Difficulty/resource_temporal_overlap/member_double_book_closed_interval_touching_rejected
    """
    council, troop = create_council_and_troop(
        council_overrides={"name": "Db8b"}, troop_overrides={"unit_number": "U-1602"}
    )
    member = create_registered_youth(troop["id"], full_name="Db8 Youth 2")

    event_a = get_success_data(
        api.create_event(
            troop["id"],
            create_event_payload(title="A2", starts_at="2026-09-01T09:00:00Z",
                                 ends_at="2026-09-01T12:00:00Z", capacity=5, requires_health_form=False),
            LEAD,
        )
    )
    reg_a = create_confirmed_registration(event_a["id"], member["id"], requires_health_form=False)

    event_b = get_success_data(
        api.create_event(
            troop["id"],
            create_event_payload(title="B2", starts_at="2026-09-01T12:00:00Z",
                                 ends_at="2026-09-01T15:00:00Z", capacity=5, requires_health_form=False),
            LEAD,
        )
    )
    reg_b = create_hold_registration(event_b["id"], member["id"])
    get_success_data(api.sign_permission(reg_b["id"], LEAD))
    resp = api.confirm_registration(reg_b["id"], LEAD)
    validate_error(resp, ApiErrorId.ERR_MEMBER_DOUBLE_BOOKED.value)

    # The first confirmed registration is untouched.
    reg_a_after = validate_success(api.get_event_registration(reg_a["id"], REG), 200)
    assert reg_a_after["status"] == "CONFIRMED"


def test_event_full_capacity_boundary(api):
    """PRD §3.6: "a confirmation blocked because the event is already at capacity is
    rejected with ERR_EVENT_FULL."

    Design: Corner/validations/event_full_capacity_boundary
    """
    council, troop = create_council_and_troop(
        council_overrides={"name": "V6"}, troop_overrides={"unit_number": "V-6"}
    )
    m1 = create_registered_youth(troop["id"], full_name="Y1")
    m2 = create_registered_youth(troop["id"], full_name="Y2")

    event = get_success_data(
        api.create_event(
            troop["id"],
            create_event_payload(title="Small", capacity=1, requires_health_form=False),
            LEAD,
        )
    )
    create_confirmed_registration(event["id"], m1["id"], requires_health_form=False)

    reg2 = create_hold_registration(event["id"], m2["id"])
    get_success_data(api.sign_permission(reg2["id"], LEAD))
    resp = api.confirm_registration(reg2["id"], LEAD)
    validate_error(resp, ApiErrorId.ERR_EVENT_FULL.value)

    event_after = validate_success(api.get_event(event["id"], REG), 200)
    assert event_after["confirmed_count"] == 1
