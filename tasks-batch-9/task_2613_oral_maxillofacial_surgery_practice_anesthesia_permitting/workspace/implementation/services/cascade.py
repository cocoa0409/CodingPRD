"""Privilege cascades (PRD 2.10, 3.1, 3.10)."""
from db import db, touch
from services.domain import (NON_TERMINAL_CASE_STATUSES,
                             VOIDABLE_EVALUATION_STATUSES, cases_of_practice,
                             evaluations_of_case, get_block,
                             reservations_of_case)
from services.inventory import release_reservation
from services.practice import (recompute_consignment,
                               recompute_open_adverse_events,
                               recompute_privilege, touch_practice)
from services.scheduling import touch_block


def probation_cascade(practice):
    """Narrow cascade: only DEEP cases already CLEARED lose their clearance."""
    for case in cases_of_practice(practice["id"]):
        if case["planned_anesthesia_level"] != "DEEP_SEDATION_GENERAL":
            continue
        if case["clearance_status"] != "CLEARED":
            continue
        case["clearance_status"] = "DEFERRED"
        touch(case)


def suspension_cascade(practice):
    """Five hops: privilege, confirmed sedated cases, their holds, the lots, the exposure."""
    released = 0
    for case in cases_of_practice(practice["id"]):
        if case["scheduling_status"] != "CONFIRMED":
            continue
        if case["planned_anesthesia_level"] == "LOCAL_ONLY":
            continue
        case["scheduling_status"] = "BLOCK_HELD"
        case["clearance_status"] = "DEFERRED"
        touch(case)
        for reservation in reservations_of_case(case["id"]):
            if reservation["status"] != "HELD":
                continue
            release_reservation(reservation)
            released += 1
    recompute_consignment(practice)
    touch_practice(practice)
    return released


def sweep_cascade(practice):
    """Sweep form: non-terminal sedated cases are cancelled outright."""
    cancelled = 0
    released = 0
    touched_blocks = []
    for case in cases_of_practice(practice["id"]):
        if case["scheduling_status"] not in NON_TERMINAL_CASE_STATUSES:
            continue
        if case["planned_anesthesia_level"] == "LOCAL_ONLY":
            continue
        case["scheduling_status"] = "CANCELLED"
        case["cancellation_reason"] = "PRIVILEGE_SUSPENDED"
        touch(case)
        cancelled += 1
        for evaluation in evaluations_of_case(case["id"]):
            if evaluation["status"] in VOIDABLE_EVALUATION_STATUSES:
                evaluation["status"] = "VOIDED"
                touch(evaluation)
        for reservation in reservations_of_case(case["id"]):
            if reservation["status"] != "HELD":
                continue
            release_reservation(reservation)
            released += 1
        block = get_block(case.get("block_id")) if case.get("block_id") else None
        if block is not None and block["id"] not in touched_blocks:
            touched_blocks.append(block["id"])
    recompute_consignment(practice)
    recompute_open_adverse_events(practice)
    touch_practice(practice)
    for block_id in touched_blocks:
        block = get_block(block_id)
        if block is not None:
            touch_block(block)
    return cancelled, released
