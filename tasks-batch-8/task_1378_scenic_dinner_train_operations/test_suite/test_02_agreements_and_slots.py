"""Track rights agreements and operating slot timetable rules (PRD §3.1, §2.7)."""
import pytest

from test_helpers import (
    MECH,
    OPS,
    SCHED,
    assert_slot,
    create_active_agreement,
    create_agreement_payload,
    create_open_slot,
    create_slot_payload,
    validate_error,
    validate_success,
)
from test_helpers.api_errors import ApiErrorId


def test_adjacent_slots_allowed(api, scheduler_headers):
    """PRD §2.7: "Because the intervals are half-open, two slots on the same agreement
    and date may touch — one slot's `end_minute` equal to another's `start_minute` is
    adjacency, not overlap."
    PRD §3.1: "the slot must not overlap any other non-`RELEASED` slot on the same
    agreement and date — with adjacency expressly allowed — otherwise `ERR_SLOT_OVERLAP`".

    Design: Difficulty/resource_temporal_overlap/slot_adjacency_half_open_allowed
    """
    agreement = create_active_agreement()
    create_open_slot(agreement["id"], start_minute=600, end_minute=780)

    res = api.create_slot(create_slot_payload(agreement["id"], start_minute=780, end_minute=900),
                          scheduler_headers)
    slot_b = validate_success(res, 201)
    assert_slot(slot_b)
    assert slot_b["status"] == "OPEN", "adjacent slot accepted under half-open semantics"
    assert slot_b["start_minute"] == 780 and slot_b["end_minute"] == 900


def test_interleaved_slot_rejected(api, scheduler_headers):
    """PRD §3.1: "the slot must not overlap any other non-`RELEASED` slot on the same
    agreement and date — with adjacency expressly allowed — otherwise `ERR_SLOT_OVERLAP`".

    Design: Difficulty/resource_temporal_overlap/slot_adjacency_half_open_allowed
    """
    agreement = create_active_agreement()
    create_open_slot(agreement["id"], start_minute=600, end_minute=780)

    res = api.create_slot(create_slot_payload(agreement["id"], start_minute=700, end_minute=800),
                          scheduler_headers)
    validate_error(res, ApiErrorId.ERR_SLOT_OVERLAP.value, expected_status=409)


def test_terminated_agreement_rejects_further_events(api, scheduler_headers, operations_manager_headers):
    """PRD §3.1: "Activation by a `Scheduler` moves it `DRAFT → ACTIVE`; an
    `OperationsManager` may instead terminate it, and termination is possible from
    either `DRAFT` or `ACTIVE`, landing in the terminal `TERMINATED` state."
    PRD §2.9: "the target entity is in a legal from-state for the requested event —
    events on terminal entities, out-of-order boarding or operation, consist edits on a
    non-`DRAFT` excursion, starting a work order on a unit that is not `AVAILABLE`,
    checking in while the excursion is not `BOARDING`, and creating an excursion on a
    slot that is not `OPEN` all fail here with `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/terminated_agreement_rejects_further_events
    """
    res = api.create_agreement(create_agreement_payload(), scheduler_headers)
    agreement = validate_success(res, 201)
    term = api.agreement_event(agreement["id"], {"event_type": "TERMINATE"}, operations_manager_headers)
    terminated = validate_success(term, 200)
    assert terminated["status"] == "TERMINATED"

    res = api.agreement_event(agreement["id"], {"event_type": "ACTIVATE"}, scheduler_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)


def test_events_unknown_type_returns_invalid_request(api, scheduler_headers):
    """PRD §3.5: "getting that conditional wrong is `ERR_VALIDATION`, as is any
    malformed body, missing required field, invalid enum value, or unknown `event_type`."
    PRD §5: `ERR_VALIDATION` -> 400 Bad Request.

    Design: Corner/validations/events_unknown_type_returns_invalid_request
    """
    res = api.create_agreement(create_agreement_payload(), scheduler_headers)
    agreement = validate_success(res, 201)

    res = api.agreement_event(agreement["id"], {"event_type": "FROBNICATE"}, scheduler_headers)
    validate_error(res, ApiErrorId.ERR_VALIDATION.value, expected_status=400)


def test_slot_outside_agreement_window_rejected(api, scheduler_headers):
    """PRD §3.1: "the `service_date` must lie inside the agreement's validity window
    from `valid_from` through `valid_until` inclusive, otherwise
    `ERR_SLOT_OUTSIDE_AGREEMENT_WINDOW`".

    Design: Corner/validations/slot_outside_agreement_window_rejected
    """
    agreement = create_active_agreement()
    res = api.create_slot(create_slot_payload(agreement["id"], service_date="2027-02-01"),
                          scheduler_headers)
    validate_error(res, ApiErrorId.ERR_SLOT_OUTSIDE_AGREEMENT_WINDOW.value, expected_status=422)


def test_slot_duration_below_minimum_rejected(api, scheduler_headers):
    """PRD §3.1: "The duration floor produces `ERR_SLOT_DURATION_TOO_SHORT` when the
    window is shorter than `min_slot_minutes`."

    Design: Corner/validations/slot_duration_below_minimum_rejected
    """
    agreement = create_active_agreement()
    # 645 - 600 = 45 minutes < min_slot_minutes 60
    res = api.create_slot(create_slot_payload(agreement["id"], start_minute=600, end_minute=645),
                          scheduler_headers)
    validate_error(res, ApiErrorId.ERR_SLOT_DURATION_TOO_SHORT.value, expected_status=422)


def test_daily_train_cap_enforced(api, scheduler_headers):
    """PRD §3.1: "the creation must not push the count of slots in `OPEN`, `RESERVED`,
    or `CONSUMED` status on that date past the agreement's `max_trains_per_day`,
    otherwise `ERR_DAILY_TRAIN_CAP_REACHED`".

    Design: Corner/validations/daily_train_cap_enforced
    """
    agreement = create_active_agreement()  # max_trains_per_day = 3
    for start, end in ((600, 780), (780, 900), (900, 1020)):
        res = api.create_slot(create_slot_payload(agreement["id"], start_minute=start, end_minute=end),
                              scheduler_headers)
        validate_success(res, 201)

    res = api.create_slot(create_slot_payload(agreement["id"], start_minute=1020, end_minute=1140),
                          scheduler_headers)
    validate_error(res, ApiErrorId.ERR_DAILY_TRAIN_CAP_REACHED.value, expected_status=409)


def test_slot_create_on_draft_agreement_rejected(api, scheduler_headers):
    """PRD §3.1: "Only an `ACTIVE` agreement can receive operating slots; an attempt
    under a `DRAFT` or `TERMINATED` agreement fails with `ERR_AGREEMENT_NOT_ACTIVE`."

    Design: Corner/validations/slot_create_on_draft_agreement_rejected
    """
    res = api.create_agreement(create_agreement_payload(), scheduler_headers)
    agreement = validate_success(res, 201)
    assert agreement["status"] == "DRAFT"

    res = api.create_slot(create_slot_payload(agreement["id"]), scheduler_headers)
    validate_error(res, ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE.value, expected_status=409)
