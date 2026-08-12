"""Composite setup helpers for multi-step test prerequisites.

Every helper builds its preconditions from scratch using only PRD-declared
endpoints (each test runs against a fresh server/database). Setup calls use
the lenient get_success_data() validator so failures surface as clear
"Setup step failed" errors.

Identity threading: every Surgeon call uses make_surgeon_headers(surgeon_id)
with the real entity id, because ownership checks compare X-User-ID to the
resource's surgeon_id.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import (
    CLOCK_AFTER_WEEK,
    DATE_MONDAY,
)
from .factories import (
    create_anesthesia_coverage_payload,
    create_block_payload,
    create_case_payload,
    create_operating_room_payload,
    create_reallocation_request_payload,
    create_service_line_payload,
    create_surgeon_payload,
    create_vote_payload,
    schedule_block_payload,
)
from .test_users import TEST_USERS, make_committee_member_headers, make_surgeon_headers

ADMIN = TEST_USERS["admin_headers"]
NURSE = TEST_USERS["nurse_headers"]
COORDINATOR = TEST_USERS["coordinator_headers"]
CHAIR = TEST_USERS["chair_headers"]


# ─── Tier 1: single-entity creation ──────────────────

def make_line(name="GS", target=75, release_deadline_hours=None) -> dict:
    """Create a service line. Omits release_deadline_hours unless given so the
    server applies its documented default."""
    payload = create_service_line_payload(name=name, target_utilization_pct=target)
    if release_deadline_hours is not None:
        payload["release_deadline_hours"] = release_deadline_hours
    return get_success_data(api_client.create_service_line(payload, ADMIN))


def make_surgeon(line_id: str, full_name="Dr. G") -> dict:
    return get_success_data(
        api_client.create_surgeon(create_surgeon_payload(line_id, full_name=full_name), ADMIN)
    )


def make_room(room_name="OR1", is_hybrid=False) -> dict:
    return get_success_data(
        api_client.create_operating_room(
            create_operating_room_payload(room_name=room_name, is_hybrid=is_hybrid), ADMIN
        )
    )


def make_coverage(or_id, date, start_minute=420, end_minute=1200, provider_ref="AN1") -> dict:
    return get_success_data(
        api_client.create_anesthesia_coverage(
            create_anesthesia_coverage_payload(
                or_id,
                date=date,
                start_minute=start_minute,
                end_minute=end_minute,
                provider_ref=provider_ref,
            ),
            COORDINATOR,
        )
    )


def make_block(line_id, or_id, date=DATE_MONDAY, start_minute=420, end_minute=720,
               surgeon_id=None, activate=False) -> dict:
    payload = create_block_payload(
        line_id, or_id, date=date, start_minute=start_minute, end_minute=end_minute
    )
    if surgeon_id is not None:
        payload["surgeon_id"] = surgeon_id
    block = get_success_data(api_client.create_block(payload, ADMIN))
    if activate:
        block = get_success_data(api_client.activate_block(block["id"], ADMIN))
    return block


def make_case(surgeon_id, procedure_class="STANDARD", priority="ELECTIVE",
              patient_ref=None) -> dict:
    payload = create_case_payload(
        surgeon_id, procedure_class=procedure_class, priority=priority
    )
    if patient_ref is not None:
        payload["patient_ref"] = patient_ref
    return get_success_data(
        api_client.create_case(payload, make_surgeon_headers(surgeon_id))
    )


# ─── Tier 2: composite scheduling setups ─────────────

def schedule_case_in_block(case_id, block_id, surgeon_id) -> dict:
    """Schedule a POSTED case into a block as its owning surgeon."""
    return get_success_data(
        api_client.schedule_case(
            case_id, schedule_block_payload(block_id), make_surgeon_headers(surgeon_id)
        )
    )


def setup_active_block_with_case(line_name="GS", target=75, date=DATE_MONDAY,
                                 block_start=420, block_end=1020,
                                 coverage_start=420, coverage_end=1200,
                                 procedure_class="STANDARD",
                                 priority="ELECTIVE", is_hybrid=False):
    """Line + surgeon + room + coverage + ACTIVE block + one SCHEDULED case.

    Returns dict(line, surgeon, room, coverage, block, case).
    """
    line = make_line(name=line_name, target=target)
    surgeon = make_surgeon(line["id"], full_name=f"Dr. {line_name}")
    room = make_room(is_hybrid=is_hybrid)
    coverage = make_coverage(room["id"], date, coverage_start, coverage_end)
    block = make_block(line["id"], room["id"], date=date,
                       start_minute=block_start, end_minute=block_end, activate=True)
    case = make_case(surgeon["id"], procedure_class=procedure_class, priority=priority)
    case = schedule_case_in_block(case["id"], block["id"], surgeon["id"])
    return {
        "line": line, "surgeon": surgeon, "room": room,
        "coverage": coverage, "block": block, "case": case,
    }


def run_case_lifecycle(case_id, block_id, surgeon_id, actual_duration):
    """Schedule -> start -> complete. actual_start is the packed scheduled
    start (on-time); actual_end = actual_start + actual_duration."""
    scheduled = schedule_case_in_block(case_id, block_id, surgeon_id)
    start = scheduled["scheduled_start_minute"]
    get_success_data(
        api_client.start_case(case_id, {"actual_start_minute": start}, NURSE)
    )
    return get_success_data(
        api_client.complete_case(
            case_id, {"actual_end_minute": start + actual_duration}, NURSE
        )
    )


def setup_surgeon_with_completions(line_name="GS", target=75, date=DATE_MONDAY,
                                   block_start=420, block_end=1080,
                                   coverage_start=420, coverage_end=1440,
                                   procedure_class="STANDARD",
                                   actual_durations=()):
    """Drive a surgeon's bias: post/schedule/start/complete one case per entry
    in actual_durations. Returns dict(line, surgeon, room, block, cases)."""
    line = make_line(name=line_name, target=target)
    surgeon = make_surgeon(line["id"], full_name=f"Dr. {line_name}")
    room = make_room()
    make_coverage(room["id"], date, coverage_start, coverage_end)
    block = make_block(line["id"], room["id"], date=date,
                       start_minute=block_start, end_minute=block_end, activate=True)
    cases = []
    for duration in actual_durations:
        case = make_case(surgeon["id"], procedure_class=procedure_class)
        cases.append(run_case_lifecycle(case["id"], block["id"], surgeon["id"], duration))
    return {"line": line, "surgeon": surgeon, "room": room, "block": block, "cases": cases}


# ─── Tier 3: release / open-time setups ──────────────

def release_block_and_get_slot(block_id, as_headers=None):
    """Manually release an ACTIVE block; return (released_block, [slots])."""
    released = get_success_data(
        api_client.release_block(block_id, as_headers or ADMIN)
    )
    slots, _ = validate_paginated(
        api_client.list_open_time_slots(ADMIN, params={"block_id": block_id})
    )
    return released, slots


def setup_open_slot(line_name="GS", target=75, date=DATE_MONDAY,
                    block_start=420, block_end=720, with_case=False,
                    room_name="OR1", coverage_start=420, coverage_end=1200):
    """ACTIVE block (optionally holding one SCHEDULED STANDARD case owned by
    the line's surgeon), manually released by the admin. Returns
    dict(line, surgeon, room, block, slots, case_or_None)."""
    line = make_line(name=line_name, target=target)
    surgeon = make_surgeon(line["id"], full_name=f"Dr. {line_name}")
    room = make_room(room_name=room_name)
    make_coverage(room["id"], date, coverage_start, coverage_end)
    block = make_block(line["id"], room["id"], date=date,
                       start_minute=block_start, end_minute=block_end, activate=True)
    case = None
    if with_case:
        case = make_case(surgeon["id"])
        case = schedule_case_in_block(case["id"], block["id"], surgeon["id"])
    released = get_success_data(api_client.release_block(block["id"], ADMIN))
    slots, _ = validate_paginated(
        api_client.list_open_time_slots(ADMIN, params={"block_id": block["id"]})
    )
    return {"line": line, "surgeon": surgeon, "room": room,
            "block": released, "slots": slots, "case": case}


def make_reallocation_request(slot_id, case_id, surgeon_id) -> dict:
    return get_success_data(
        api_client.create_reallocation_request(
            create_reallocation_request_payload(slot_id, case_id),
            make_surgeon_headers(surgeon_id),
        )
    )


# ─── Tier 4: governance setups ───────────────────────

def setup_deficient_review(line_name="GS", target=75, block_date=DATE_MONDAY,
                           block_start=420, block_end=1020,
                           clock=CLOCK_AFTER_WEEK):
    """A line whose single STANDARD case in a 600-prime-minute block yields
    prime utilization 15.00 < target; scoring run opens one OPEN review.

    Returns dict(line, surgeon, room, block, case, review, report).
    """
    env = setup_active_block_with_case(
        line_name=line_name, target=target, date=block_date,
        block_start=block_start, block_end=block_end,
    )
    get_success_data(api_client.set_clock(clock, ADMIN))
    get_success_data(api_client.scoring_run(ADMIN))
    reviews, meta = validate_paginated(
        api_client.list_committee_reviews(
            ADMIN, params={"service_line_id": env["line"]["id"], "status": "OPEN"}
        )
    )
    assert meta["total_count"] == 1, (
        f"Setup expected exactly one OPEN review, got {meta['total_count']}"
    )
    reports, rmeta = validate_paginated(
        api_client.list_utilization_reports(env["line"]["id"], ADMIN)
    )
    assert rmeta["total_count"] >= 1, "Setup expected at least one utilization report"
    env.update({"review": reviews[0], "report": reports[0]})
    return env


def cast_votes_sequential(review_id, votes, start_version):
    """Cast votes in order, chaining expected_review_version from each
    response. votes: list of (member_user_id, vote_value). Returns the last
    accepted review payload."""
    current_version = start_version
    review = None
    for member_id, vote in votes:
        review = get_success_data(
            api_client.cast_committee_vote(
                review_id,
                create_vote_payload(vote, current_version),
                make_committee_member_headers(member_id),
            )
        )
        current_version = review["version"]
    return review


def list_votes(review_id):
    return validate_paginated(api_client.list_committee_votes(review_id, ADMIN))
