"""Provider and room geometry, the post-insertion window, and the two holds."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_same_instant,
    book_procedure,
    new_patient,
    new_physician,
    new_standing_order,
    read_patient,
    record_consult,
    set_hold,
    setup_pellet_procedure,
    validate_error,
    validate_paginated,
    validate_success,
)

FRONT_DESK = TEST_USERS["front_desk_headers"]


def _one_booked_slot(api, *, room_code, scheduled_start, second_physician=False):
    """A physician, a patient, a consult, a standing order and one booked slot."""
    physician = new_physician(api)
    other = (
        new_physician(api, "Dr Ben Sato", "1000000002") if second_physician else None
    )
    patient = new_patient(api, "Pat TwentyFive", "p25@example.com")
    consult = record_consult(api, patient["id"], physician["id"], prescribed_dose_mg=1000)
    order = new_standing_order(api, physician["id"])
    first = book_procedure(
        api, patient["id"], physician["id"], consult["id"], order["id"],
        room_code=room_code, scheduled_start=scheduled_start,
    )
    return {
        "physician": physician,
        "other_physician": other,
        "patient": patient,
        "consult": consult,
        "order": order,
        "first": first,
    }


def test_provider_slot_inside_the_twenty_minute_buffer_is_rejected(api):
    """PRD §3.4: "For the provider, expand the new booking by 20 minutes on each side and test
    that expanded interval against the raw intervals of the provider's existing bookings:
    there is a conflict when the new start minus twenty minutes falls strictly before an
    existing booking's end **and** that booking's start falls strictly before the new end plus
    twenty minutes."
    PRD §3.4: "The codes are `ERR_PROVIDER_SLOT_CONFLICT` and `ERR_ROOM_CONFLICT`, and the
    provider rule is checked first."

    Design: Difficulty/resource_temporal_overlap/provider_buffer_expanded_overlap_rejects_but_exact_gap_admits
    """
    ctx = _one_booked_slot(api, room_code="RM18", scheduled_start="2026-06-01T09:00:00Z")
    assert_same_instant(
        ctx["first"]["scheduled_end"], "2026-06-01T09:45:00Z", "scheduled_end"
    )

    response = api.create_procedure(
        {
            "patient_id": ctx["patient"]["id"],
            "provider_id": ctx["physician"]["id"],
            "consult_id": ctx["consult"]["id"],
            "standing_order_id": ctx["order"]["id"],
            "procedure_type": "INITIAL",
            "room_code": "RM19",
            "scheduled_start": "2026-06-01T10:00:00Z",
        },
        FRONT_DESK,
    )
    validate_error(response, ApiErrorId.ERR_PROVIDER_SLOT_CONFLICT.value)
    assert response.status_code == 409

    rows, meta = validate_paginated(
        api.list_procedures(FRONT_DESK, {"provider_id": ctx["physician"]["id"]})
    )
    assert meta["total_count"] == 1, "The rejected slot must not be booked"


def test_provider_slot_exactly_twenty_minutes_after_the_previous_end_is_admitted(api):
    """PRD §3.4: "For the provider, expand the new booking by 20 minutes on each side and test
    that expanded interval against the raw intervals of the provider's existing bookings:
    there is a conflict when the new start minus twenty minutes falls strictly before an
    existing booking's end **and** that booking's start falls strictly before the new end plus
    twenty minutes."
    PRD §3.4: "On success the server copies `hormone_type`, `planned_pellet_count` and
    `planned_total_mg` from the referenced consult onto the procedure, sets `scheduled_end` to
    45 minutes after `scheduled_start`, sets `status` to `SCHEDULED` and `recall_status` to
    `NONE`, and initialises `pellets_allocated`, `pellets_opened`, `pellets_inserted`,
    `pellets_wasted`, `delivered_total_mg`, `charge_cents` and `cancel_fee_cents` all to 0,
    with `consent_record_id`, `cancel_tier`, `performed_at` and `hold_reason` all null."

    Design: Difficulty/resource_temporal_overlap/provider_buffer_expanded_overlap_rejects_but_exact_gap_admits
    """
    ctx = _one_booked_slot(api, room_code="RM18", scheduled_start="2026-06-01T09:00:00Z")

    response = api.create_procedure(
        {
            "patient_id": ctx["patient"]["id"],
            "provider_id": ctx["physician"]["id"],
            "consult_id": ctx["consult"]["id"],
            "standing_order_id": ctx["order"]["id"],
            "procedure_type": "INITIAL",
            "room_code": "RM19",
            "scheduled_start": "2026-06-01T10:05:00Z",
        },
        FRONT_DESK,
    )
    second = validate_success(response, 201)
    assert_same_instant(second["scheduled_start"], "2026-06-01T10:05:00Z", "scheduled_start")
    assert_same_instant(second["scheduled_end"], "2026-06-01T10:50:00Z", "scheduled_end")

    rows, meta = validate_paginated(
        api.list_procedures(FRONT_DESK, {"provider_id": ctx["physician"]["id"]})
    )
    assert meta["total_count"] == 2


def test_room_booking_that_straddles_an_existing_one_is_rejected(api):
    """PRD §3.4: "For the room, use no buffer at all and test half-open overlap on the raw
    intervals: there is a conflict when the new start falls strictly before an existing end
    **and** the existing start falls strictly before the new end — so two bookings that touch
    exactly at a boundary in the same room are allowed, while the same pair on one provider is
    not."

    Design: Difficulty/resource_temporal_overlap/room_back_to_back_boundary_admits_but_straddle_rejects
    """
    ctx = _one_booked_slot(
        api, room_code="RM21", scheduled_start="2026-06-02T09:00:00Z", second_physician=True
    )

    response = api.create_procedure(
        {
            "patient_id": ctx["patient"]["id"],
            "provider_id": ctx["other_physician"]["id"],
            "consult_id": ctx["consult"]["id"],
            "standing_order_id": ctx["order"]["id"],
            "procedure_type": "INITIAL",
            "room_code": "RM21",
            "scheduled_start": "2026-06-02T09:30:00Z",
        },
        FRONT_DESK,
    )
    validate_error(response, ApiErrorId.ERR_ROOM_CONFLICT.value)
    assert response.status_code == 409


def test_room_booking_touching_exactly_at_the_boundary_is_admitted(api):
    """PRD §3.4: "For the room, use no buffer at all and test half-open overlap on the raw
    intervals: there is a conflict when the new start falls strictly before an existing end
    **and** the existing start falls strictly before the new end — so two bookings that touch
    exactly at a boundary in the same room are allowed, while the same pair on one provider is
    not."

    Design: Difficulty/resource_temporal_overlap/room_back_to_back_boundary_admits_but_straddle_rejects
    """
    ctx = _one_booked_slot(
        api, room_code="RM21", scheduled_start="2026-06-02T09:00:00Z", second_physician=True
    )
    assert_same_instant(
        ctx["first"]["scheduled_end"], "2026-06-02T09:45:00Z", "scheduled_end"
    )

    response = api.create_procedure(
        {
            "patient_id": ctx["patient"]["id"],
            "provider_id": ctx["other_physician"]["id"],
            "consult_id": ctx["consult"]["id"],
            "standing_order_id": ctx["order"]["id"],
            "procedure_type": "INITIAL",
            "room_code": "RM21",
            "scheduled_start": "2026-06-02T09:45:00Z",
        },
        FRONT_DESK,
    )
    second = validate_success(response, 201)
    assert second["room_code"] == "RM21"
    assert_same_instant(second["scheduled_start"], "2026-06-02T09:45:00Z", "scheduled_start")

    rows, meta = validate_paginated(api.list_procedures(FRONT_DESK, {"limit": 100}))
    assert len([r for r in rows if r["room_code"] == "RM21"]) == 2


def test_cross_hormone_booking_ten_days_after_an_insertion_is_refused(api):
    """PRD §3.4: "The **post-insertion restriction** is anchored on the patient and spans
    every hormone: a booking is refused when its `scheduled_start` falls strictly earlier than
    `last_insertion_at` plus 14 days, which means a slot exactly 14 days after the last
    insertion of any hormone is permitted. The rejection code is
    `ERR_POST_INSERTION_RESTRICTION`."
    PRD §3.4: "For a same-hormone re-dose the 84-day or 70-day interval always subsumes this
    14-day window, so the restriction bites in practice on cross-hormone bookings — a patient
    who completed a testosterone insertion on day zero and books an estradiol `INITIAL`
    insertion on day ten skips the whole re-dose gate and lands here."

    Design: Difficulty/resource_temporal_overlap/patient_post_insertion_forward_window_blocks_cross_hormone_booking
    """
    ctx = setup_pellet_procedure(
        api, target_status="COMPLETED", room_code="RM20",
        scheduled_start="2026-05-10T09:00:00Z", perform_at="2026-05-10T09:00:00Z",
        patient_name="Pat TwentySix", patient_email="p26@example.com", sex_at_birth="FEMALE",
    )
    estradiol_consult = record_consult(
        api, ctx["patient_id"], ctx["physician_id"], "ESTRADIOL",
        prescribed_dose_mg=100, indication="Vasomotor",
    )

    patient = read_patient(api, ctx["patient_id"])
    assert_same_instant(
        patient["last_insertion_at"], "2026-05-10T09:00:00Z", "last_insertion_at"
    )
    assert patient["last_insertion_hormone_type"] == "TESTOSTERONE"

    response = api.create_procedure(
        {
            "patient_id": ctx["patient_id"],
            "provider_id": ctx["physician_id"],
            "consult_id": estradiol_consult["id"],
            "standing_order_id": ctx["standing_order_id"],
            "procedure_type": "INITIAL",
            "room_code": "RM20",
            "scheduled_start": "2026-05-20T09:00:00Z",
        },
        FRONT_DESK,
    )
    validate_error(response, ApiErrorId.ERR_POST_INSERTION_RESTRICTION.value)
    assert response.status_code == 409


def test_cross_hormone_booking_exactly_fourteen_days_after_is_admitted(api):
    """PRD §3.4: "The **post-insertion restriction** is anchored on the patient and spans
    every hormone: a booking is refused when its `scheduled_start` falls strictly earlier than
    `last_insertion_at` plus 14 days, which means a slot exactly 14 days after the last
    insertion of any hormone is permitted. The rejection code is
    `ERR_POST_INSERTION_RESTRICTION`."
    PRD §2.9: "**Rung 26** — the post-insertion restriction, on `POST /clinic/procedures`:
    reject when `scheduled_start` falls strictly earlier than the patient's
    `last_insertion_at` plus 14 days."

    Design: Difficulty/resource_temporal_overlap/patient_post_insertion_forward_window_blocks_cross_hormone_booking
    """
    ctx = setup_pellet_procedure(
        api, target_status="COMPLETED", room_code="RM20",
        scheduled_start="2026-05-10T09:00:00Z", perform_at="2026-05-10T09:00:00Z",
        patient_name="Pat TwentySix", patient_email="p26@example.com", sex_at_birth="FEMALE",
    )
    estradiol_consult = record_consult(
        api, ctx["patient_id"], ctx["physician_id"], "ESTRADIOL",
        prescribed_dose_mg=100, indication="Vasomotor",
    )

    response = api.create_procedure(
        {
            "patient_id": ctx["patient_id"],
            "provider_id": ctx["physician_id"],
            "consult_id": estradiol_consult["id"],
            "standing_order_id": ctx["standing_order_id"],
            "procedure_type": "INITIAL",
            "room_code": "RM20",
            "scheduled_start": "2026-05-24T09:00:00Z",
        },
        FRONT_DESK,
    )
    booked = validate_success(response, 201)
    assert booked["hormone_type"] == "ESTRADIOL"
    assert booked["planned_total_mg"] == 100
    assert booked["status"] == "SCHEDULED"


def _dual_held_patient(api):
    physician = new_physician(api)
    patient = new_patient(api, "Pat Seventeen", "p17@example.com")
    consult = record_consult(api, patient["id"], physician["id"], prescribed_dose_mg=1000)
    order = new_standing_order(api, physician["id"])
    set_hold(
        api, patient["id"], "FINANCIAL", "SET", reason="Defaulted plan on another account"
    )
    set_hold(
        api, patient["id"], "CLINICAL", "SET", physician_id=physician["id"],
        reason="Awaiting cardiology clearance",
    )
    return physician, patient, consult, order


def test_dual_held_patient_hears_the_clinical_complaint_when_booking(api):
    """PRD §2.9: "**Rung 39** — `financial_hold` is false on the patient, on
    `POST /clinic/procedures` and `POST /clinic/procedures/{id}/perform`. This sits at the very
    bottom of the ladder deliberately, so that a patient carrying both holds always hears
    `ERR_PATIENT_CLINICAL_HOLD` from rung 14 rather than the financial complaint. Otherwise
    `ERR_PATIENT_FINANCIAL_HOLD` (402)."
    PRD §3.1: "What *is* derived, on every request that writes either boolean, is
    `eligibility_status`, a compound projection over the pair: `DUAL_HOLD` when both booleans
    are true, `CLINICAL_HOLD` when only the clinical one is true, `FINANCIAL_HOLD` when only
    the financial one is true, and `CLEAR` when neither is."

    Design: Difficulty/priority_pair_validation_conflict/clinical_hold_pre_empts_financial_hold_on_scheduling
    """
    physician, patient, consult, order = _dual_held_patient(api)

    held = read_patient(api, patient["id"])
    assert held["eligibility_status"] == "DUAL_HOLD"
    assert held["clinical_hold"] is True
    assert held["financial_hold"] is True

    response = api.create_procedure(
        {
            "patient_id": patient["id"],
            "provider_id": physician["id"],
            "consult_id": consult["id"],
            "standing_order_id": order["id"],
            "procedure_type": "INITIAL",
            "room_code": "RM10",
            "scheduled_start": "2026-06-10T09:00:00Z",
        },
        FRONT_DESK,
    )
    validate_error(response, ApiErrorId.ERR_PATIENT_CLINICAL_HOLD.value)
    assert response.status_code == 409


def test_clearing_only_the_clinical_hold_exposes_the_financial_complaint(api):
    """PRD §2.9: "**Rung 14** — `clinical_hold` is false on the patient, on
    `POST /clinic/procedures`, `POST /clinic/procedures/{id}/perform` and
    `POST /clinic/injection-visits/{id}/administer`. Otherwise `ERR_PATIENT_CLINICAL_HOLD`
    (409)."
    PRD §3.1: "`CLEAR → FINANCIAL_HOLD` fires on the delinquency default cascade when
    `financial_hold` flips true while `clinical_hold` is false, and its effect is narrower:
    scheduling and performing a procedure are blocked at rung 39 with HTTP 402, while
    injection administration is deliberately **not** blocked, because a financial hold must
    never withhold care the patient has already paid for through a series or a membership."

    Design: Difficulty/priority_pair_validation_conflict/clinical_hold_pre_empts_financial_hold_on_scheduling
    """
    physician, patient, consult, order = _dual_held_patient(api)

    set_hold(
        api, patient["id"], "CLINICAL", "CLEAR", physician_id=physician["id"],
        reason="Cardiology cleared",
    )
    cleared = read_patient(api, patient["id"])
    assert cleared["clinical_hold"] is False
    assert cleared["financial_hold"] is True
    assert cleared["eligibility_status"] == "FINANCIAL_HOLD"

    response = api.create_procedure(
        {
            "patient_id": patient["id"],
            "provider_id": physician["id"],
            "consult_id": consult["id"],
            "standing_order_id": order["id"],
            "procedure_type": "INITIAL",
            "room_code": "RM10",
            "scheduled_start": "2026-06-10T09:00:00Z",
        },
        FRONT_DESK,
    )
    validate_error(response, ApiErrorId.ERR_PATIENT_FINANCIAL_HOLD.value)
    assert response.status_code == 402

    rows, meta = validate_paginated(
        api.list_procedures(FRONT_DESK, {"patient_id": patient["id"]})
    )
    assert meta["total_count"] == 0, "Neither attempt may leave a Procedure row behind"
