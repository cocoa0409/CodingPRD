"""Registration, waitlist promotion, workshop cancellation, seat conservation,
and the list/pagination envelope (PRD §3.2, §2.9, §2.2/§2.3)."""
from test_helpers import (
    ApiErrorId,
    api_client,
    create_module,
    create_participant,
    create_certified_coach,
    create_registration,
    create_registration_payload,
    create_workshop,
    set_clock,
    setup_full_waitlist_workshop,
    setup_workshop_scenario,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_cancel_registered_promotes_lowest_waitlist_position(api, admin_headers):
    """PRD §3.2: "Cancelling a `REGISTERED` entry frees a seat —
    `confirmed_count` drops by 1 — and that freed seat immediately triggers the
    promotion scan, provided the workshop is still `SCHEDULED` and the logical
    clock still reads before its `start_at`." PRD §3.2: "The first eligible
    entry is promoted to `REGISTERED`, its `waitlist_position` is cleared,
    `confirmed_count` rises back by 1, and the scan stops."

    Design: Difficulty/transitive_cascade/cancel_registration_promotes_waitlist
    """
    ctx = setup_full_waitlist_workshop(admin_headers, capacity=1, num_waitlisted=1,
                                       module_overrides=dict(module_code="CR-301"))
    _p1, r1 = ctx["registered"][0]
    _p2, r2 = ctx["waitlisted"][0]
    assert r1["status"] == "REGISTERED"
    assert r2["status"] == "WAITLISTED"
    assert r2["waitlist_position"] == 1

    validate_success(api.cancel_registration(r1["id"], admin_headers))
    r2_after = validate_success(api.get_registration(r2["id"], admin_headers))
    assert r2_after["status"] == "REGISTERED"
    assert r2_after["waitlist_position"] is None


def test_cancel_with_promotion_nets_confirmed_count_to_unchanged(api, admin_headers):
    """PRD §2.9: "a cancellation that triggers a waitlist promotion nets to
    zero, because the freed seat is immediately refilled."

    Design: Difficulty/transitive_cascade/cancel_registration_promotes_waitlist
    """
    ctx = setup_full_waitlist_workshop(admin_headers, capacity=1, num_waitlisted=1,
                                       module_overrides=dict(module_code="CR-301B"))
    _p1, r1 = ctx["registered"][0]
    validate_success(api.cancel_registration(r1["id"], admin_headers))
    workshop = validate_success(api.get_workshop(ctx["workshop"]["id"], admin_headers))
    assert workshop["confirmed_count"] == 1, (
        f"cancel (-1) plus promotion (+1) must net to zero drift; "
        f"got {workshop['confirmed_count']}"
    )


def test_registration_at_exact_capacity_waitlists(api, admin_headers):
    """PRD §3.2: "If the workshop's `confirmed_count` is below its `capacity`,
    the registration is created `REGISTERED` and `confirmed_count` rises by 1.
    Otherwise the registration is created `WAITLISTED`".

    Design: Difficulty/boundary_precision_check/workshop_seat_boundary_at_exact_capacity
    """
    ctx = setup_workshop_scenario(
        admin_headers, capacity=1,
        module_overrides=dict(module_code="TX-501", session_count=1,
                              completion_threshold=1),
    )
    p1 = create_participant(admin_headers, full_name="P E1", email="pe1@test.org")
    p2 = create_participant(admin_headers, full_name="P E2", email="pe2@test.org")
    r1 = validate_success(
        api.create_registration(
            create_registration_payload(ctx["workshop"]["id"], p1["id"]), admin_headers
        ),
        expected_status=201,
    )
    # confirmed_count 0 < capacity 1 -> REGISTERED.
    assert r1["status"] == "REGISTERED"
    r2 = validate_success(
        api.create_registration(
            create_registration_payload(ctx["workshop"]["id"], p2["id"]), admin_headers
        ),
        expected_status=201,
    )
    # confirmed_count == capacity exactly -> WAITLISTED.
    assert r2["status"] == "WAITLISTED"


def test_confirmed_count_matches_registered_count_at_boundary(api, admin_headers):
    """PRD §2.9: "A workshop's `confirmed_count` always equals the number of
    registrations on that workshop currently in `REGISTERED` status, and it
    never leaves the range from zero up to the workshop's `capacity`."

    Design: Difficulty/boundary_precision_check/workshop_seat_boundary_at_exact_capacity
    """
    ctx = setup_workshop_scenario(
        admin_headers, capacity=1,
        module_overrides=dict(module_code="TX-501B", session_count=1,
                              completion_threshold=1),
    )
    p1 = create_participant(admin_headers)
    p2 = create_participant(admin_headers)
    create_registration(ctx["workshop"]["id"], p1["id"], admin_headers)
    create_registration(ctx["workshop"]["id"], p2["id"], admin_headers)
    workshop = validate_success(api.get_workshop(ctx["workshop"]["id"], admin_headers))
    assert workshop["confirmed_count"] == 1
    assert 0 <= workshop["confirmed_count"] <= workshop["capacity"]


def test_seat_ledger_conserved_across_register_cancel_promote(api, admin_headers):
    """PRD §2.9: "A workshop's `confirmed_count` always equals the number of
    registrations on that workshop currently in `REGISTERED` status, and it
    never leaves the range from zero up to the workshop's `capacity`."
    PRD §2.9: "a cancellation that triggers a waitlist promotion nets to zero,
    because the freed seat is immediately refilled."

    Design: Difficulty/compensating_invariant/workshop_seat_ledger_conserved_across_register_cancel
    """
    ctx = setup_workshop_scenario(
        admin_headers, capacity=2,
        module_overrides=dict(module_code="IN-901", session_count=1,
                              completion_threshold=1),
    )
    w_id = ctx["workshop"]["id"]
    participants = [create_participant(admin_headers) for _ in range(3)]
    regs = [create_registration(w_id, p["id"], admin_headers) for p in participants]
    # Third registration overflows capacity 2 -> WAITLISTED.
    assert regs[2]["status"] == "WAITLISTED"

    validate_success(api.cancel_registration(regs[0]["id"], admin_headers))
    workshop = validate_success(api.get_workshop(w_id, admin_headers))
    assert workshop["confirmed_count"] == 2, (
        "cancel of one REGISTERED entry plus promotion of the waitlisted entry "
        "must net to zero drift"
    )
    listed, meta = validate_paginated(
        api.list_registrations(
            admin_headers, params={"workshop_id": w_id, "status": "REGISTERED", "limit": 100}
        )
    )
    assert meta["total_count"] == 2
    assert len(listed) == workshop["confirmed_count"]


def test_seat_ledger_drops_by_one_when_waitlist_empty(api, admin_headers):
    """PRD §2.9: "a later cancellation of that same registration removes one".

    Design: Difficulty/compensating_invariant/workshop_seat_ledger_conserved_across_register_cancel
    """
    ctx = setup_workshop_scenario(
        admin_headers, capacity=2,
        module_overrides=dict(module_code="IN-901B", session_count=1,
                              completion_threshold=1),
    )
    w_id = ctx["workshop"]["id"]
    participants = [create_participant(admin_headers) for _ in range(3)]
    regs = [create_registration(w_id, p["id"], admin_headers) for p in participants]
    assert regs[2]["status"] == "WAITLISTED"
    # First cancel frees a seat and promotes the waitlisted entry: still 2.
    validate_success(api.cancel_registration(regs[0]["id"], admin_headers))
    # Second cancel faces an empty waitlist: ledger drops by exactly 1.
    validate_success(api.cancel_registration(regs[1]["id"], admin_headers))
    workshop = validate_success(api.get_workshop(w_id, admin_headers))
    assert workshop["confirmed_count"] == 1


def test_waitlist_promotion_skips_restricted_participant(api, admin_headers):
    """PRD §3.2: "The scan walks the workshop's `WAITLISTED` registrations from
    the lowest `waitlist_position` upward, skipping any entry whose participant
    is no longer `ACTIVE` and any entry whose promotion would violate the
    buffered collision rule against that participant's other `REGISTERED`
    commitments; skipped entries remain `WAITLISTED`."

    Design: Corner/calculations/waitlist_promotion_skips_restricted_participant
    """
    module = create_module(admin_headers, module_code="SK-100", title="SK",
                           session_count=3, incentive_cents_per_hour=500,
                           completion_bonus_cents=0, completion_threshold=1)
    coach = create_certified_coach(admin_headers, full_name="CSK", email="csk@test.org")
    p1 = create_participant(admin_headers, full_name="PSK1", email="psk1@test.org")
    p2 = create_participant(admin_headers, full_name="PSK2", email="psk2@test.org")
    p3 = create_participant(admin_headers, full_name="PSK3", email="psk3@test.org")
    target = create_workshop(module["id"], coach["id"], admin_headers,
                             start_at="2026-08-10T10:00:00Z",
                             end_at="2026-08-10T11:00:00Z", capacity=1)
    r1 = create_registration(target["id"], p1["id"], admin_headers)
    r2 = create_registration(target["id"], p2["id"], admin_headers)
    r3 = create_registration(target["id"], p3["id"], admin_headers)
    assert r2["status"] == "WAITLISTED" and r2["waitlist_position"] == 1
    assert r3["waitlist_position"] == 2

    # P2 racks up 3 NO_SHOWs on separate earlier workshops -> RESTRICTED.
    p2_prior_regs = []
    for day in ("2026-08-02", "2026-08-03", "2026-08-04"):
        w = create_workshop(module["id"], coach["id"], admin_headers,
                            location="Rm N",
                            start_at=f"{day}T10:00:00Z", end_at=f"{day}T11:00:00Z",
                            capacity=10)
        p2_prior_regs.append(create_registration(w["id"], p2["id"], admin_headers))
    # Advance the clock past all three starts, then mark NO_SHOW on each.
    set_clock("2026-08-05T00:00:00Z", admin_headers)
    for reg in p2_prior_regs:
        validate_success(
            api.mark_attendance(reg["id"], {"outcome": "NO_SHOW"}, admin_headers)
        )
    p2_after = validate_success(api.get_participant(p2["id"], admin_headers))
    assert p2_after["status"] == "RESTRICTED"

    # The freed seat skips RESTRICTED P2 (position 1) and promotes P3 (position 2).
    validate_success(api.cancel_registration(r1["id"], admin_headers))
    r2_after = validate_success(api.get_registration(r2["id"], admin_headers))
    r3_after = validate_success(api.get_registration(r3["id"], admin_headers))
    assert r2_after["status"] == "WAITLISTED", (
        "RESTRICTED participant's waitlist entry must be skipped, not promoted"
    )
    assert r3_after["status"] == "REGISTERED", (
        "the next eligible waitlist position must be promoted instead"
    )


def test_registration_initial_state_registered_when_seat_free(api, admin_headers):
    """PRD §3.2: "If the workshop's `confirmed_count` is below its `capacity`,
    the registration is created `REGISTERED` and `confirmed_count` rises by 1."

    Design: Corner/state_machines/registration_initial_state_registered_when_seat_free
    """
    ctx = setup_workshop_scenario(
        admin_headers, capacity=3,
        module_overrides=dict(module_code="IS-100", session_count=1,
                              completion_threshold=1),
    )
    participant = create_participant(admin_headers, full_name="PIS", email="pis@test.org")
    registration = validate_success(
        api.create_registration(
            create_registration_payload(ctx["workshop"]["id"], participant["id"]),
            admin_headers,
        ),
        expected_status=201,
    )
    assert registration["status"] == "REGISTERED"
    workshop = validate_success(api.get_workshop(ctx["workshop"]["id"], admin_headers))
    assert workshop["confirmed_count"] == 1


def test_cancelled_registration_terminal_lockdown(api, admin_headers):
    """PRD §3.2: "Cancellation is available to a `ProgramAdmin` or to the
    participant who owns the registration, and only from `REGISTERED` or
    `WAITLISTED` (anything else is `ERR_INVALID_STATE`)." PRD §3.2: "marking a
    registration no longer `REGISTERED`, or one on a workshop no longer
    `SCHEDULED`, is rejected with `ERR_INVALID_STATE`".

    Design: Corner/state_machines/cancelled_registration_terminal_lockdown
    """
    ctx = setup_workshop_scenario(
        admin_headers, capacity=3,
        module_overrides=dict(module_code="TL-100", session_count=1,
                              completion_threshold=1),
    )
    participant = create_participant(admin_headers, full_name="PTL", email="ptl@test.org")
    reg = create_registration(ctx["workshop"]["id"], participant["id"], admin_headers)
    validate_success(api.cancel_registration(reg["id"], admin_headers))

    resp1 = api.cancel_registration(reg["id"], admin_headers)
    validate_error(resp1, ApiErrorId.ERR_INVALID_STATE)
    resp2 = api.mark_attendance(reg["id"], {"outcome": "ATTENDED"}, admin_headers)
    validate_error(resp2, ApiErrorId.ERR_INVALID_STATE)


def test_workshop_cancel_cascades_without_promotion(api, admin_headers):
    """PRD §3.1: "Cancelling a workshop — again `ProgramAdmin`-only, and only
    from `SCHEDULED` on pain of `ERR_INVALID_STATE` — moves it to the terminal
    `CANCELLED` status and cancels every registration still sitting in
    `REGISTERED` or `WAITLISTED`, driving `confirmed_count` to 0. No waitlist
    promotion runs, because the workshop itself is gone."

    Design: Corner/state_machines/workshop_cancel_cascades_without_promotion
    """
    ctx = setup_full_waitlist_workshop(admin_headers, capacity=1, num_waitlisted=1,
                                       module_overrides=dict(module_code="WC-100",
                                                             session_count=1,
                                                             completion_threshold=1))
    _p1, r1 = ctx["registered"][0]
    _p2, r2 = ctx["waitlisted"][0]
    workshop = validate_success(api.cancel_workshop(ctx["workshop"]["id"], admin_headers))
    assert workshop["status"] == "CANCELLED"

    r1_after = validate_success(api.get_registration(r1["id"], admin_headers))
    r2_after = validate_success(api.get_registration(r2["id"], admin_headers))
    assert r1_after["status"] == "CANCELLED"
    # The waitlisted entry is cancelled too — NOT promoted; the workshop is gone.
    assert r2_after["status"] == "CANCELLED"

    workshop_after = validate_success(api.get_workshop(ctx["workshop"]["id"], admin_headers))
    assert workshop_after["confirmed_count"] == 0


def test_duplicate_active_registration_rejected(api, admin_headers):
    """PRD §3.2: "the participant must not already hold a `REGISTERED` or
    `WAITLISTED` entry on this workshop (`ERR_ALREADY_REGISTERED`)".

    Design: Corner/validations/duplicate_active_registration_rejected

    The duplicate guard is reached via a WAITLISTED entry: per PRD §3.2 the
    buffered-window conflict check ignores WAITLISTED registrations, so a
    waitlisted participant re-registering for the same workshop passes the
    (earlier) conflict tier and surfaces ERR_ALREADY_REGISTERED. A duplicate
    against an own REGISTERED entry on the same workshop would instead trip
    ERR_PARTICIPANT_SCHEDULE_CONFLICT first, per the pinned order in §2.7/§3.2.
    """
    ctx = setup_full_waitlist_workshop(
        admin_headers, capacity=1, num_waitlisted=1,
        module_overrides=dict(module_code="AR-100", session_count=1,
                              completion_threshold=1),
    )
    _wait_participant, wait_reg = ctx["waitlisted"][0]
    assert wait_reg["status"] == "WAITLISTED"
    resp = api.create_registration(
        create_registration_payload(ctx["workshop"]["id"], wait_reg["participant_id"]),
        admin_headers,
    )
    validate_error(resp, ApiErrorId.ERR_ALREADY_REGISTERED)


def test_list_registrations_pagination_and_envelope(api, admin_headers):
    """PRD §2.3: "Paginated and non-paginated list-based responses include the
    following fields in the `meta` object of the response envelope: `limit`,
    `offset`, `total_count`, and `has_more`." PRD §2.2: "The `api_request_id`
    is a server-generated unique identifier for the request that starts with
    `req_`."

    Design: Corner/endpoints/list_registrations_pagination_and_envelope
    """
    ctx = setup_workshop_scenario(
        admin_headers, capacity=5,
        module_overrides=dict(module_code="PG-100", session_count=1,
                              completion_threshold=1),
    )
    p1 = create_participant(admin_headers, full_name="PP1", email="pp1@test.org")
    p2 = create_participant(admin_headers, full_name="PP2", email="pp2@test.org")
    create_registration(ctx["workshop"]["id"], p1["id"], admin_headers)
    create_registration(ctx["workshop"]["id"], p2["id"], admin_headers)

    resp = api.list_registrations(
        admin_headers,
        params={"workshop_id": ctx["workshop"]["id"], "limit": 1, "offset": 0},
    )
    body = resp.json()
    assert "meta" in body and "api_request_id" in body["meta"]
    assert body["response_type"] == "array"
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(data) == 1


def test_immediate_read_after_write_consistency(api, admin_headers):
    """PRD §2.9: "Three derived quantities are reconciled continuously and must
    hold exactly after every mutation." PRD §3.2: "If the workshop's
    `confirmed_count` is below its `capacity`, the registration is created
    `REGISTERED` and `confirmed_count` rises by 1." PRD §3.2: "Client-supplied
    values for this field are always ignored; it defaults to 0 until earned."

    Design: Corner/consistency_model/immediate_read_after_write_consistency
    """
    ctx = setup_workshop_scenario(
        admin_headers, capacity=5,
        module_overrides=dict(module_code="IM-100", session_count=1,
                              completion_threshold=1),
    )
    participant = create_participant(admin_headers, full_name="PIM", email="pim@test.org")
    reg = create_registration(ctx["workshop"]["id"], participant["id"], admin_headers)

    reg_read = validate_success(api.get_registration(reg["id"], admin_headers))
    assert reg_read["status"] == "REGISTERED"
    assert reg_read["incentive_earned_cents"] == 0
    workshop = validate_success(api.get_workshop(ctx["workshop"]["id"], admin_headers))
    assert workshop["confirmed_count"] == 1


def test_registration_create_computed_incentive_input_ignored(api, admin_headers):
    """PRD §3.2: "Client-supplied values for this field are always ignored; it
    defaults to 0 until earned."

    Design: Corner/entities/registration_create_computed_incentive_input_ignored
    """
    ctx = setup_workshop_scenario(
        admin_headers, capacity=5,
        module_overrides=dict(module_code="IG-100", session_count=1,
                              completion_threshold=1),
    )
    participant = create_participant(admin_headers, full_name="PI", email="pi@test.org")
    resp = api.create_registration(
        {"workshop_id": ctx["workshop"]["id"], "participant_id": participant["id"],
         "incentive_earned_cents": 99999},
        admin_headers,
    )
    registration = validate_success(resp, expected_status=201)
    assert registration["incentive_earned_cents"] == 0
    assert registration["status"] == "REGISTERED"
