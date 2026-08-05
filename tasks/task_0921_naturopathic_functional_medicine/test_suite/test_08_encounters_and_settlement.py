"""Booking, occupancy geometry, settlement and the cancellation compensations."""

from test_helpers import (
    ApiErrorId,
    assert_encounter,
    assert_membership_visit_conservation,
    book_encounter,
    complete_encounter,
    make_nd_headers,
    make_patient_headers,
    open_membership,
    read_membership,
    read_patient,
    register_nd,
    set_clock,
    setup_booking_ready_patient,
    setup_patient_at_booking_score,
    validate_error,
    validate_paginated,
    validate_success,
)


def _member_and_cash_patient(api):
    """One ND, one CORE member and one cash-pay patient, both bookable remotely."""
    nd = register_nd(api)
    member = setup_booking_ready_patient(api, nd=nd, telehealth_consent=True)["patient"]
    cash = setup_booking_ready_patient(api, nd=nd, telehealth_consent=True)["patient"]
    membership = open_membership(api, member["id"], tier="CORE", cycle_start_date="2026-05-01")
    return nd, member, cash, membership


def test_a_reserved_seventy_five_minute_visit_settles_at_the_extended_charge_only(api):
    """PRD §3.3: "When the encounter reserved a visit unit at booking and its
    billing axis is `ENTITLEMENT_RESERVED`, `cash_charged_cents` is set to the
    extended-time charge alone — the base fee is absorbed by the visit unit —
    and the axis advances `ENTITLEMENT_RESERVED → ENTITLEMENT_CONSUMED`."
    PRD §3.3: "The `base_fee_cents` is 22500 for an `IN_PERSON` visit, 18000 for
    a `TELEHEALTH` visit, and 9500 for an `EVISIT`."

    Design: Difficulty/dual_variant_calc/encounter_settlement_entitlement_first_versus_cash_fallback
    """
    nd, member, _cash, _membership = _member_and_cash_patient(api)
    booked = book_encounter(
        api,
        nd["id"],
        member["id"],
        modality="TELEHEALTH",
        scheduled_start="2026-06-01T15:00:00Z",
        scheduled_end="2026-06-01T16:30:00Z",
    )
    assert booked["billing_status"] == "ENTITLEMENT_RESERVED"

    settled = complete_encounter(
        api, nd["id"], booked["id"], duration_minutes=75, service_code="99215",
        diagnosis_codes=["E03.9"],
    )

    assert_encounter(settled)
    assert settled["billing_status"] == "ENTITLEMENT_CONSUMED"
    assert settled["base_fee_cents"] == 18000
    assert settled["extended_block_count"] == 2
    assert settled["cash_charged_cents"] == 9000
    assert read_patient(api, member["id"])["cash_charged_total_cents"] == 9000


def test_the_same_visit_without_entitlement_settles_at_base_plus_extended(api):
    """PRD §3.3: "When no unit was available and the axis is `CASH_PENDING`,
    `cash_charged_cents` is set to the base fee plus the extended-time charge,
    and the axis advances `CASH_PENDING → CASH_CHARGED`. The clinically
    identical encounter therefore produces a strictly larger cash figure for a
    non-member."
    PRD §3.3: "The `extended_block_count` is zero when `duration_minutes` is at
    most 45; otherwise it is the number of minutes beyond 45 divided by 15 and
    rounded **up** to a whole block, so a 46-minute visit already buys one full
    block and a 60-minute visit buys exactly one."

    Design: Difficulty/dual_variant_calc/encounter_settlement_entitlement_first_versus_cash_fallback
    """
    nd, _member, cash, _membership = _member_and_cash_patient(api)
    booked = book_encounter(
        api,
        nd["id"],
        cash["id"],
        modality="TELEHEALTH",
        scheduled_start="2026-06-01T17:00:00Z",
        scheduled_end="2026-06-01T18:30:00Z",
    )
    assert booked["billing_status"] == "CASH_PENDING"

    settled = complete_encounter(
        api, nd["id"], booked["id"], duration_minutes=75, service_code="99215",
        diagnosis_codes=["E03.9"],
    )

    assert settled["billing_status"] == "CASH_CHARGED"
    assert settled["extended_block_count"] == 2
    assert settled["cash_charged_cents"] == 27000
    assert read_patient(api, cash["id"])["cash_charged_total_cents"] == 27000


def test_a_visit_of_exactly_forty_five_minutes_buys_no_extended_block(api):
    """PRD §2.7: "**The extended-visit threshold is inclusive.** A visit lasting
    exactly the threshold number of minutes buys no extended block; one minute
    more already buys a whole one."
    PRD §3.3: "The `extended_block_count` is zero when `duration_minutes` is at
    most 45; otherwise it is the number of minutes beyond 45 divided by 15 and
    rounded **up** to a whole block, so a 46-minute visit already buys one full
    block and a 60-minute visit buys exactly one."

    Design: Difficulty/combinatorial_formula/extended_visit_block_ceiling_at_and_past_the_threshold
    """
    ready = setup_booking_ready_patient(api)
    nd, patient = ready["nd"], ready["patient"]
    booked = book_encounter(
        api, nd["id"], patient["id"],
        scheduled_start="2026-06-01T09:00:00Z",
        scheduled_end="2026-06-01T10:00:00Z",
    )

    settled = complete_encounter(
        api, nd["id"], booked["id"], duration_minutes=45, service_code="99214"
    )

    assert settled["extended_block_count"] == 0
    assert settled["cash_charged_cents"] == 22500
    assert read_patient(api, patient["id"])["cash_charged_total_cents"] == 22500


def test_one_minute_past_the_threshold_buys_a_whole_extended_block(api):
    """PRD §3.3: "The extended-time charge is that block count multiplied by 4500
    cents per block."
    PRD §2.8: "`cash_charged_total_cents` accumulates everything the practice
    has charged the patient in cash across encounters, e-visits, cash-funded
    laboratory panels, dispensed supplements and positive membership
    proration."

    Design: Difficulty/combinatorial_formula/extended_visit_block_ceiling_at_and_past_the_threshold
    """
    ready = setup_booking_ready_patient(api)
    nd, patient = ready["nd"], ready["patient"]
    at_threshold = book_encounter(
        api, nd["id"], patient["id"],
        scheduled_start="2026-06-01T09:00:00Z",
        scheduled_end="2026-06-01T10:00:00Z",
    )
    past_threshold = book_encounter(
        api, nd["id"], patient["id"],
        scheduled_start="2026-06-01T11:00:00Z",
        scheduled_end="2026-06-01T12:00:00Z",
    )

    complete_encounter(
        api, nd["id"], at_threshold["id"], duration_minutes=45, service_code="99214"
    )
    settled = complete_encounter(
        api, nd["id"], past_threshold["id"], duration_minutes=46, service_code="99214"
    )

    assert settled["extended_block_count"] == 1
    assert settled["cash_charged_cents"] == 27000
    assert read_patient(api, patient["id"])["cash_charged_total_cents"] == 49500


def _telehealth_practice(api):
    ready = setup_booking_ready_patient(api, telehealth_consent=True)
    nd, patient = ready["nd"], ready["patient"]
    base = book_encounter(
        api, nd["id"], patient["id"], modality="TELEHEALTH",
        scheduled_start="2026-06-01T10:00:00Z",
        scheduled_end="2026-06-01T10:30:00Z",
    )
    return nd, patient, base


def test_a_telehealth_booking_inside_the_turnaround_buffer_collides(api):
    """PRD §3.3: "There is one adjustment: when **both** the existing encounter
    and the requested one are `TELEHEALTH`, the existing encounter's effective
    end is pushed out by 10 minutes of turnaround before the comparison is made,
    so a remote visit needs ten clear minutes after it before the next remote
    visit may start."
    PRD §3.3: "A collision is refused with `ERR_PRACTITIONER_DOUBLE_BOOKED`."

    Design: Difficulty/resource_temporal_overlap/practitioner_windows_are_half_open_with_a_telehealth_only_buffer
    """
    nd, patient, _base = _telehealth_practice(api)

    response = api.create_encounter(
        {
            "patient_id": patient["id"],
            "practitioner_id": nd["id"],
            "modality": "TELEHEALTH",
            "scheduled_start": "2026-06-01T10:35:00Z",
            "scheduled_end": "2026-06-01T11:05:00Z",
        },
        make_nd_headers(nd["id"]),
    )
    validate_error(response, ApiErrorId.ERR_PRACTITIONER_DOUBLE_BOOKED.value, 409)


def test_a_touching_in_person_window_and_a_clear_telehealth_window_both_book(api):
    """PRD §2.7: "**Practitioner occupancy on an encounter is half-open.** The
    occupied interval runs from `scheduled_start` inclusive up to
    `scheduled_end` exclusive. Two encounters that merely touch — one ending at
    exactly the instant the next begins — do **not** collide."
    PRD §3.3: "That buffer is not applied when both encounters are `IN_PERSON`
    and it is not applied to a mixed pair — only to telehealth-on-telehealth."

    Design: Difficulty/resource_temporal_overlap/practitioner_windows_are_half_open_with_a_telehealth_only_buffer
    """
    nd, patient, _base = _telehealth_practice(api)

    touching = validate_success(
        api.create_encounter(
            {
                "patient_id": patient["id"],
                "practitioner_id": nd["id"],
                "modality": "IN_PERSON",
                "scheduled_start": "2026-06-01T10:30:00Z",
                "scheduled_end": "2026-06-01T11:00:00Z",
            },
            make_nd_headers(nd["id"]),
        ),
        201,
    )
    assert touching["scheduling_status"] == "SCHEDULED"

    after = validate_success(
        api.create_encounter(
            {
                "patient_id": patient["id"],
                "practitioner_id": nd["id"],
                "modality": "TELEHEALTH",
                "scheduled_start": "2026-06-01T11:00:00Z",
                "scheduled_end": "2026-06-01T11:30:00Z",
            },
            make_nd_headers(nd["id"]),
        ),
        201,
    )
    assert after["scheduling_status"] == "SCHEDULED"

    _rows, meta = validate_paginated(
        api.list_encounters(make_nd_headers(nd["id"]), params={"practitioner_id": nd["id"]})
    )
    assert meta["total_count"] == 3


def _two_reserved_encounters(api):
    """A CORE member with two reserved IN_PERSON bookings."""
    nd = register_nd(api)
    patient = setup_patient_at_booking_score(
        api, nd,
        attested=("CHIEF_COMPLAINT_TIMELINE", "SYSTEMS_REVIEW", "FAMILY_HISTORY"),
    )
    membership = open_membership(api, patient["id"], tier="CORE", cycle_start_date="2026-05-01")
    early = book_encounter(
        api, nd["id"], patient["id"],
        scheduled_start="2026-06-10T09:00:00Z", scheduled_end="2026-06-10T10:00:00Z",
    )
    late = book_encounter(
        api, nd["id"], patient["id"],
        scheduled_start="2026-06-01T09:00:00Z", scheduled_end="2026-06-01T10:00:00Z",
    )
    return nd, patient, membership, early, late


def test_a_cancellation_inside_the_window_moves_the_unit_to_forfeited(api):
    """PRD §2.9: "Cancelling at least 24 hours ahead returns it, decreasing
    `visits_consumed` by one and increasing `visits_remaining` by one;
    cancelling later moves it instead, decreasing `visits_consumed` by one and
    increasing `visits_forfeited` by one."
    PRD §3.3: "A late cancellation of a reserved encounter moves the axis
    `ENTITLEMENT_RESERVED → FORFEITED` and moves the unit instead of returning
    it: `visits_consumed` decreases by 1 and `visits_forfeited` increases by 1,
    with `visits_remaining` and `visits_granted` untouched, and
    `entitlement_consumed` is again set false — the patient loses the visit but
    the pool does not pretend it was never spent."

    Design: Difficulty/compensating_invariant/visit_unit_returned_on_early_cancel_and_moved_to_forfeited_on_late_cancel
    """
    nd, patient, _membership, _early, late = _two_reserved_encounters(api)

    set_clock(api, "2026-05-31T10:00:00Z")
    cancelled = validate_success(
        api.cancel_encounter(
            late["id"], {"reason": "unwell"}, make_patient_headers(patient["id"])
        )
    )

    assert cancelled["scheduling_status"] == "CANCELLED"
    assert cancelled["billing_status"] == "FORFEITED"
    assert cancelled["entitlement_consumed"] is False

    membership = read_membership(api, patient["id"])
    assert membership["visits_granted"] == 4
    assert membership["visits_consumed"] == 1
    assert membership["visits_remaining"] == 2
    assert membership["visits_forfeited"] == 1
    assert_membership_visit_conservation(membership)


def test_a_cancellation_exactly_twenty_four_hours_ahead_returns_the_unit(api):
    """PRD §2.7: "**The cancellation refund window is inclusive at its
    boundary.** A cancellation landing exactly 24 hours before `scheduled_start`
    still refunds."
    PRD §3.3: "A timely cancellation of a reserved encounter moves the axis
    `ENTITLEMENT_RESERVED → REFUNDED` and gives the unit back:
    `visits_consumed` decreases by 1 and `visits_remaining` increases by 1, with
    `visits_granted` and `visits_forfeited` untouched, and
    `entitlement_consumed` is set false."

    Design: Difficulty/compensating_invariant/visit_unit_returned_on_early_cancel_and_moved_to_forfeited_on_late_cancel
    """
    nd, patient, _membership, early, late = _two_reserved_encounters(api)

    set_clock(api, "2026-05-31T10:00:00Z")
    validate_success(
        api.cancel_encounter(
            late["id"], {"reason": "unwell"}, make_patient_headers(patient["id"])
        )
    )

    set_clock(api, "2026-06-09T09:00:00Z")
    refunded = validate_success(
        api.cancel_encounter(
            early["id"], {"reason": "travel"}, make_patient_headers(patient["id"])
        )
    )
    assert refunded["billing_status"] == "REFUNDED"

    membership = read_membership(api, patient["id"])
    assert membership["visits_granted"] == 4
    assert membership["visits_consumed"] == 0
    assert membership["visits_remaining"] == 3
    assert membership["visits_forfeited"] == 1
    assert_membership_visit_conservation(membership)
    assert read_patient(api, patient["id"])["cash_charged_total_cents"] == 0


def _out_of_state_practice(api):
    """An ND licensed only in WA holding an IN_PERSON window, and an OR patient."""
    nd = register_nd(api, full_name="Dr Wes Han", licensed_state_codes=["WA"], npi="1122334455")
    ready = setup_booking_ready_patient(api, nd=nd, telehealth_consent=True)
    patient = ready["patient"]
    existing = book_encounter(
        api, nd["id"], patient["id"],
        scheduled_start="2026-06-01T15:00:00Z", scheduled_end="2026-06-01T16:00:00Z",
    )
    return nd, patient, existing


def test_licensure_wins_over_occupancy_on_a_doubly_violating_booking(api):
    """PRD §2.6: "On encounter booking and on thread-to-e-visit conversion, the
    patient's `state_code` must appear in the rendering practitioner's
    `licensed_state_codes` — otherwise `ERR_STATE_NOT_LICENSED` (403)."
    PRD §2.6: "The checks form a single ordered ladder; the lowest-numbered
    violated rung wins and no later rung is consulted."

    Design: Difficulty/priority_pair_validation_conflict/telehealth_licensure_pre_empts_practitioner_double_booking
    """
    nd, patient, _existing = _out_of_state_practice(api)

    response = api.create_encounter(
        {
            "patient_id": patient["id"],
            "practitioner_id": nd["id"],
            "modality": "TELEHEALTH",
            "scheduled_start": "2026-06-01T15:30:00Z",
            "scheduled_end": "2026-06-01T16:30:00Z",
        },
        make_nd_headers(nd["id"]),
    )
    validate_error(response, ApiErrorId.ERR_STATE_NOT_LICENSED.value, 403)


def test_an_out_of_state_remote_booking_is_refused_even_with_a_clear_diary(api):
    """PRD §3.3: "Then, for a remote modality, the patient's `state_code` must
    appear in the rendering practitioner's `licensed_state_codes`, or the
    booking is refused with `ERR_STATE_NOT_LICENSED`."
    PRD §2.6: "On encounter booking, the requested window must not collide with
    another window of the same practitioner — otherwise
    `ERR_PRACTITIONER_DOUBLE_BOOKED` (409)."

    Design: Difficulty/priority_pair_validation_conflict/telehealth_licensure_pre_empts_practitioner_double_booking
    """
    nd, patient, _existing = _out_of_state_practice(api)

    overlapping = api.create_encounter(
        {
            "patient_id": patient["id"],
            "practitioner_id": nd["id"],
            "modality": "TELEHEALTH",
            "scheduled_start": "2026-06-01T15:30:00Z",
            "scheduled_end": "2026-06-01T16:30:00Z",
        },
        make_nd_headers(nd["id"]),
    )
    validate_error(overlapping, ApiErrorId.ERR_STATE_NOT_LICENSED.value, 403)

    clear_diary = api.create_encounter(
        {
            "patient_id": patient["id"],
            "practitioner_id": nd["id"],
            "modality": "TELEHEALTH",
            "scheduled_start": "2026-06-02T09:00:00Z",
            "scheduled_end": "2026-06-02T10:00:00Z",
        },
        make_nd_headers(nd["id"]),
    )
    validate_error(clear_diary, ApiErrorId.ERR_STATE_NOT_LICENSED.value, 403)

    _rows, meta = validate_paginated(
        api.list_encounters(make_nd_headers(nd["id"]), params={"patient_id": patient["id"]})
    )
    assert meta["total_count"] == 1, "Neither refused booking may persist an Encounter"


def _cancelled_cash_encounter(api):
    ready = setup_booking_ready_patient(api)
    nd, patient = ready["nd"], ready["patient"]
    booked = book_encounter(api, nd["id"], patient["id"])
    validate_success(
        api.cancel_encounter(
            booked["id"], {"reason": "patient rescheduled"},
            make_patient_headers(patient["id"]),
        )
    )
    return nd, patient, booked


def test_completing_a_cancelled_visit_reports_the_state_rung_not_the_payload(api):
    """PRD §2.6: "The addressed resource is in a state from which the requested
    transition is declared, on the relevant axis, on every state-transition
    endpoint — otherwise `ERR_INVALID_STATE` (409)."
    PRD §2.6: "Every required input field for the endpoint is present, non-null
    and of the declared type; integers such as `quantity`, `duration_minutes`
    and `current_symptom_score` are positive where the domain demands it; and
    `scheduled_end` is strictly after `scheduled_start`. Any failure yields
    `ERR_VALIDATION` (400)."

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_pre_empts_missing_required_completion_field
    """
    nd, _patient, booked = _cancelled_cash_encounter(api)

    response = api.complete_encounter(
        booked["id"],
        {"service_code": "99214", "diagnosis_codes": ["R53.83"]},
        make_nd_headers(nd["id"]),
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value, 409)


def test_the_refused_completion_leaves_both_encounter_axes_where_they_were(api):
    """PRD §3.3: "A timely cancellation of a cash encounter moves the axis
    `CASH_PENDING → REFUNDED` and no money moves at all, because nothing had
    been charged yet."
    PRD §2.6: "When a request violates more than one rule, exactly one error is
    returned, and which one is fully determined."

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_pre_empts_missing_required_completion_field
    """
    nd, patient, booked = _cancelled_cash_encounter(api)

    validate_error(
        api.complete_encounter(
            booked["id"],
            {"service_code": "99214", "diagnosis_codes": ["R53.83"]},
            make_nd_headers(nd["id"]),
        ),
        ApiErrorId.ERR_INVALID_STATE.value,
        409,
    )

    unchanged = validate_success(api.get_encounter(booked["id"], make_nd_headers(nd["id"])))
    assert unchanged["scheduling_status"] == "CANCELLED"
    assert unchanged["billing_status"] == "REFUNDED"
    assert read_patient(api, patient["id"])["cash_charged_total_cents"] == 0


def test_the_booking_response_already_carries_the_reservation_side_effects(api):
    """PRD §3.3: "When the patient holds a membership in status `ACTIVE` with
    `visits_remaining` of at least 1 and the modality is `IN_PERSON` or
    `TELEHEALTH`, the encounter's billing axis is created at
    `ENTITLEMENT_RESERVED` rather than `CASH_PENDING`: the membership's
    `visits_consumed` increases by 1, its `visits_remaining` decreases by 1,
    `visits_granted` is untouched, the encounter's `entitlement_consumed` flag
    is set true, and the membership's `version` increments by 1."

    Design: Corner/cross_cutting_complexity_layers/cascade_effects_are_visible_in_the_same_response_body
    """
    nd = register_nd(api)
    patient = setup_booking_ready_patient(api, nd=nd)["patient"]
    open_membership(api, patient["id"], tier="CORE", cycle_start_date="2026-05-01")

    response = api.create_encounter(
        {
            "patient_id": patient["id"],
            "practitioner_id": nd["id"],
            "modality": "IN_PERSON",
            "scheduled_start": "2026-06-01T09:00:00Z",
            "scheduled_end": "2026-06-01T10:00:00Z",
        },
        make_nd_headers(nd["id"]),
    )
    booked = validate_success(response, 201)

    assert booked["billing_status"] == "ENTITLEMENT_RESERVED"
    assert booked["entitlement_consumed"] is True

    membership = read_membership(api, patient["id"])
    assert membership["visits_consumed"] == 1
    assert membership["visits_remaining"] == 3
    assert membership["visits_granted"] == 4
    assert membership["visits_forfeited"] == 0
    assert_membership_visit_conservation(membership)


def test_a_telehealth_booking_without_consent_is_refused_after_licensure_passes(api):
    """PRD §3.3: "Then, for `TELEHEALTH` or `EVISIT`, the patient's
    `telehealth_consent` must be true, or the booking is refused with
    `ERR_MODALITY_CONSENT_MISSING` — and because licensure is checked first, a
    patient who is both out of state and unconsented hears about licensure, not
    consent."

    Design: Corner/errors/telehealth_without_consent_returns_modality_consent_missing
    """
    ready = setup_booking_ready_patient(api)
    nd, patient = ready["nd"], ready["patient"]
    assert read_patient(api, patient["id"])["telehealth_consent"] is False

    response = api.create_encounter(
        {
            "patient_id": patient["id"],
            "practitioner_id": nd["id"],
            "modality": "TELEHEALTH",
            "scheduled_start": "2026-06-01T15:00:00Z",
            "scheduled_end": "2026-06-01T16:00:00Z",
        },
        make_nd_headers(nd["id"]),
    )
    validate_error(response, ApiErrorId.ERR_MODALITY_CONSENT_MISSING.value, 422)

    rows, meta = validate_paginated(
        api.list_encounters(make_nd_headers(nd["id"]), params={"patient_id": patient["id"]})
    )
    assert meta["total_count"] == 0 and rows == []
