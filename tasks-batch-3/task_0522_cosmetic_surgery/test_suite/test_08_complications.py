"""Complication cases: the cyclic OPEN/UNDER_REVIEW workflow, the booking-completed
review precondition, and the attribution-driven revision charge."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, PROC_A,
    create_procedure, create_completed_booking, create_accepted_quote,
    create_surgery_booking_payload, open_complication_case,
    make_surgeon_headers,
)

FRONT = TEST_USERS["front_desk_headers"]
SURGEON = make_surgeon_headers("surgeon-1")


def _completed_booking_with_case(api, attribution="SURGICAL_ORIGIN"):
    procA = create_procedure(**PROC_A)
    booking, _q, _p, line_items = create_completed_booking([procA["id"]], deposit_cents=170000)
    case = open_complication_case(booking["id"], line_items[0]["id"], attribution)
    return booking, line_items[0], case


def test_complication_case_cycle_returns_to_under_review(api):
    """PRD §3.9: "Moving a case from OPEN to UNDER_REVIEW requires the case to be OPEN
    ... A case may be sent back from UNDER_REVIEW to OPEN, which clears any provisional
    attribution decision and returns the case to intake — this is the cyclic revision
    loop, and it requires the case to be UNDER_REVIEW."

    Design: Difficulty/non_linear_state_machine/nonlinear_complication_case_cycle
    """
    _booking, _li, case = _completed_booking_with_case(api)
    get_success_data(api.review_complication_case(case["id"], SURGEON))
    get_success_data(api.reopen_complication_case(case["id"], SURGEON))
    data = validate_success(api.review_complication_case(case["id"], SURGEON), 200)
    assert data["status"] == "UNDER_REVIEW"


def test_complication_case_reopen_returns_to_open(api):
    """PRD §3.9: "A case may be sent back from UNDER_REVIEW to OPEN, which clears any
    provisional attribution decision and returns the case to intake — this is the cyclic
    revision loop, and it requires the case to be UNDER_REVIEW (otherwise
    ERR_INVALID_STATE)."

    Design: Difficulty/non_linear_state_machine/nonlinear_complication_case_cycle
    """
    _booking, _li, case = _completed_booking_with_case(api)
    get_success_data(api.review_complication_case(case["id"], SURGEON))
    data = validate_success(api.reopen_complication_case(case["id"], SURGEON), 200)
    assert data["status"] == "OPEN"


def test_review_requires_booking_completed(api):
    """PRD §3.9: "Moving a case from OPEN to UNDER_REVIEW requires the case to be OPEN
    (otherwise ERR_INVALID_STATE) and the parent SurgeryBooking to be COMPLETED
    (otherwise ERR_BOOKING_NOT_COMPLETED)."

    Design: Difficulty/cross_entity_state_dependency/cross_entity_complication_review_requires_booking_completed
    """
    procA = create_procedure(**PROC_A)
    quote, _c, _p, line_items = create_accepted_quote([procA["id"]], deposit_cents=170000)
    booking = get_success_data(api.create_surgery_booking(
        create_surgery_booking_payload(quote["id"], quote["version"]), FRONT))
    # booking still SCHEDULED (not completed)
    case = open_complication_case(booking["id"], line_items[0]["id"], "SURGICAL_ORIGIN")
    resp = api.review_complication_case(case["id"], SURGEON)
    validate_error(resp, ApiErrorId.ERR_BOOKING_NOT_COMPLETED, 409)


def test_review_scheduled_booking_case_still_blocked(api):
    """PRD §3.9: "the parent SurgeryBooking to be COMPLETED (otherwise
    ERR_BOOKING_NOT_COMPLETED)."

    Design: Difficulty/cross_entity_state_dependency/cross_entity_complication_review_requires_booking_completed
    """
    procA = create_procedure(**PROC_A)
    quote, _c, _p, line_items = create_accepted_quote([procA["id"]], deposit_cents=170000)
    booking = get_success_data(api.create_surgery_booking(
        create_surgery_booking_payload(quote["id"], quote["version"]), FRONT))
    case = open_complication_case(booking["id"], line_items[0]["id"], "PATIENT_FACTOR")
    resp = api.review_complication_case(case["id"], SURGEON)
    validate_error(resp, ApiErrorId.ERR_BOOKING_NOT_COMPLETED, 409)


def test_surgical_origin_within_window_free_revision(api):
    """PRD §3.9: "When the attribution is SURGICAL_ORIGIN and the case is within the
    revision window, the revision is free and revision_charge_cents is 0."

    Design: Difficulty/dual_variant_calc/dual_variant_revision_charge_attribution
    """
    _booking, _li, case = _completed_booking_with_case(api, attribution="SURGICAL_ORIGIN")
    get_success_data(api.review_complication_case(case["id"], SURGEON))
    data = validate_success(api.approve_revision(case["id"], SURGEON), 200)
    assert data["revision_charge_cents"] == 0
    assert data["within_revision_window"] is True


def test_patient_factor_within_window_half_fee_revision(api):
    """PRD §3.9: "In every other case — a non-surgical attribution, or a surgical-origin
    case reported after the window closes — the charge is 50 percent of the affected line
    item's surgical_fee_cents, rounded half up to whole cents."

    Design: Difficulty/dual_variant_calc/dual_variant_revision_charge_attribution
    """
    _booking, _li, case = _completed_booking_with_case(api, attribution="PATIENT_FACTOR")
    get_success_data(api.review_complication_case(case["id"], SURGEON))
    data = validate_success(api.approve_revision(case["id"], SURGEON), 200)
    # 50% of ProcA surgical_fee 500000
    assert data["revision_charge_cents"] == 250000
