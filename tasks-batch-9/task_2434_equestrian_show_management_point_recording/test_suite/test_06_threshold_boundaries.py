"""Off-by-one probes: the three-confirmed points threshold and the stall-capacity comparison."""

from test_helpers import api_client, validate_error, validate_paginated, validate_success
from test_helpers.assertions import assert_stall_ledger_invariant
from test_helpers.fixtures import (
    build_approved_show,
    build_entry,
    build_multi_class_show,
    class_version,
    create_horse,
    create_rider,
    get_class,
    get_entry,
    get_show,
    run_class_to_posted,
    stage_class_slot,
    verify_entry,
)
from test_helpers.test_users import TEST_USERS

THREE_CLASSES = [
    {"class_number": 101, "name": "Open Jumper 1.20m", "jump_height_cm": 120, "class_share_bp": 1669},
    {"class_number": 102, "name": "Open Jumper 1.10m", "jump_height_cm": 110, "class_share_bp": 1000},
    {"class_number": 103, "name": "Open Jumper 1.00m", "jump_height_cm": 100, "class_share_bp": 1000},
]

# r1 and r2 ride all three classes; r3 rides A and C; r4 rides B only and is never settled;
# r5 rides C only.  Class A therefore has 3 confirmed rows, class B has 3 entered but only 2
# confirmed, and class C has 4 confirmed.
ENTRY_PLAN = [
    {"classes": [0, 1, 2], "confirm": True},
    {"classes": [0, 1, 2], "confirm": True},
    {"classes": [0, 2], "confirm": True},
    {"classes": [1], "confirm": False},
    {"classes": [2], "confirm": True},
]


def _three_posted_classes():
    ctx = build_multi_class_show(THREE_CLASSES, ENTRY_PLAN)
    class_a, class_b, class_c = ctx["class_ids"]
    stage_class_slot(ctx, class_a, "2026-09-10T14:00:00Z")
    stage_class_slot(ctx, class_b, "2026-09-10T15:00:00Z")
    stage_class_slot(ctx, class_c, "2026-09-10T16:00:00Z")
    run_class_to_posted(ctx, class_a, 26)
    run_class_to_posted(ctx, class_b, 26)
    run_class_to_posted(ctx, class_c, 28)
    ctx["class_a"], ctx["class_b"], ctx["class_c"] = class_a, class_b, class_c
    return ctx


def _four_verified_entries_on_a_five_stall_show():
    ctx = build_approved_show(show_overrides={"stall_capacity": 5})
    rows = []
    for requested in (3, 3, 2, 0):
        rider = create_rider()
        horse = create_horse()
        row = build_entry(
            ctx["show_id"], rider["id"], horse["id"], requested_stall_count=requested
        )
        verify_entry(row["entry_id"])
        row["requested"] = requested
        rows.append(row)
    ctx["rows"] = rows
    return ctx


def test_two_confirmed_starters_fail_the_gate_that_three_pass():
    """Class B holds three class entries but only two of them are CONFIRMED, because the fourth
    rider's entry was never settled. Raising a standings submission for it is refused, while the
    identical call on class A — three confirmed, exactly at the threshold — is accepted on the
    non-strict comparison and moves the class to POINTS_SUBMITTED.

    PRD §3.8: "A class not in `RESULTS_POSTED` is refused with `ERR_CLASS_RESULTS_NOT_POSTED`, and a class whose `point_eligible` is false — that is, whose `confirmed_entry_count` is below 3 — is refused with `ERR_CLASS_NOT_POINT_ELIGIBLE`."
    PRD §3.8: "The class's `point_eligible` is recomputed as true when its `confirmed_entry_count` is at least 3 and false otherwise."
    PRD §3.8: "The submission is created with `status` of `PREPARED`, `submitted_by_user_id` set to the raising secretary's `X-User-ID`, `national_body_reference` and `regional_body_reference` both null, and `national_points_total` and `regional_points_total` both 0."
    PRD §3.8: "The class moves `RESULTS_POSTED → POINTS_SUBMITTED` and its `version` increments."

    Design: Difficulty/boundary_precision_check/point_submission_min_entries_boundary
    """
    ctx = _three_posted_classes()

    below = get_class(ctx["class_b"])
    assert below["entry_count"] == 3
    assert below["confirmed_entry_count"] == 2
    assert below["point_eligible"] is False
    assert below["status"] == "RESULTS_POSTED"

    validate_error(
        api_client.create_point_submission(
            ctx["class_b"],
            {"expected_class_version": below["version"]},
            TEST_USERS["show_secretary_headers"],
        ),
        "ERR_CLASS_NOT_POINT_ELIGIBLE",
        409,
    )
    assert get_class(ctx["class_b"])["status"] == "RESULTS_POSTED"

    at_threshold = get_class(ctx["class_a"])
    assert at_threshold["confirmed_entry_count"] == 3
    assert at_threshold["point_eligible"] is True

    submission = validate_success(
        api_client.create_point_submission(
            ctx["class_a"],
            {"expected_class_version": at_threshold["version"]},
            TEST_USERS["show_secretary_headers"],
        ),
        201,
    )
    assert submission["status"] == "PREPARED"
    assert submission["national_points_total"] == 0
    assert submission["regional_points_total"] == 0
    assert submission["national_body_reference"] is None
    assert get_class(ctx["class_a"])["status"] == "POINTS_SUBMITTED"


def test_the_gate_reads_confirmed_starters_and_never_the_entered_count():
    """Class B's `entry_count` is three, exactly the figure the threshold names, yet it is
    refused — the gate reads confirmed starters only, and no submission row exists for it
    afterwards. Class C, one starter above the threshold, is accepted. Across the three posted
    classes the prize ledger has 73041 cents allocated, the sum of three independently rounded
    purses, and 676959 left unallocated.

    PRD §3.2: "`entry_count` is the number of class entries on the class whose `status` is `ENTERED`, `CONFIRMED`, `COMPLETED` or `DISQUALIFIED` — scratched rows drop out of it — and it is `entry_count` that `max_entries` caps."
    PRD §3.2: "`confirmed_entry_count` is the narrower number of class entries whose `status` is `CONFIRMED` or `COMPLETED`; a starter that has gone in the ring still counts."
    PRD §3.8: "A class not in `RESULTS_POSTED` is refused with `ERR_CLASS_RESULTS_NOT_POSTED`, and a class whose `point_eligible` is false — that is, whose `confirmed_entry_count` is below 3 — is refused with `ERR_CLASS_NOT_POINT_ELIGIBLE`."
    PRD §2.10: "The **prize ledger** on a show maintains `allocated_prize_cents` as the sum of `awarded_prize_cents` across classes of the show whose `status` is `RESULTS_POSTED` or `POINTS_SUBMITTED`, and `unallocated_prize_cents` as `prize_money_pool_cents` minus `allocated_prize_cents`."
    PRD §2.10: "The invariant `prize_money_pool_cents` equals `allocated_prize_cents` plus `unallocated_prize_cents` holds before and after every posting and every void."

    Design: Difficulty/boundary_precision_check/point_submission_min_entries_boundary
    """
    ctx = _three_posted_classes()

    validate_error(
        api_client.create_point_submission(
            ctx["class_b"],
            {"expected_class_version": class_version(ctx["class_b"])},
            TEST_USERS["show_secretary_headers"],
        ),
        "ERR_CLASS_NOT_POINT_ELIGIBLE",
        409,
    )
    rows, meta = validate_paginated(
        api_client.list_class_point_submissions(
            ctx["class_b"], TEST_USERS["show_secretary_headers"]
        )
    )
    assert rows == []
    assert meta["total_count"] == 0

    above = get_class(ctx["class_c"])
    assert above["confirmed_entry_count"] == 4
    assert above["estimated_minutes"] == 28
    validate_success(
        api_client.create_point_submission(
            ctx["class_c"],
            {"expected_class_version": above["version"]},
            TEST_USERS["show_secretary_headers"],
        ),
        201,
    )
    assert get_class(ctx["class_c"])["status"] == "POINTS_SUBMITTED"

    accepted_rows, accepted_meta = validate_paginated(
        api_client.list_class_point_submissions(
            ctx["class_c"], TEST_USERS["show_secretary_headers"]
        )
    )
    assert accepted_meta["total_count"] == 1
    assert len(accepted_rows) == 1

    assert get_class(ctx["class_a"])["awarded_prize_cents"] == 33793
    assert get_class(ctx["class_b"])["awarded_prize_cents"] == 16249
    assert get_class(ctx["class_c"])["awarded_prize_cents"] == 22999

    show = get_show(ctx["show_id"])
    assert show["allocated_prize_cents"] == 73041
    assert show["unallocated_prize_cents"] == 676959
    assert show["allocated_prize_cents"] + show["unallocated_prize_cents"] == 750000


def test_a_request_one_stall_past_the_remaining_capacity_is_refused_without_partial_reservation():
    """Five stalls on the grounds. The first acceptance takes three and leaves two. The second
    entry also wants three, one more than remains, and is refused: the entry stays VERIFIED with
    nothing assigned, and the ledger still reads three reserved against two available — no
    partial reservation is recorded.

    PRD §3.5: "The entry's `requested_stall_count` must not exceed the show's current `available_stall_count`; only a strictly greater request is refused, and the refusal is `ERR_STALL_CAPACITY_EXCEEDED`."
    PRD §3.5: "Only an entry in `VERIFIED` may be accepted; otherwise `ERR_ENTRY_NOT_VERIFIED`."
    PRD §2.10: "The **stall ledger** on a show maintains `reserved_stall_count` as the sum of `assigned_stall_count` across all of that show's entries whose `verification_status` is `ACCEPTED`, and `available_stall_count` as `stall_capacity` minus `reserved_stall_count`."
    PRD §2.10: "Entries in `RECEIVED`, `VERIFIED` or `WITHDRAWN` contribute zero regardless of what they requested."

    Design: Difficulty/boundary_precision_check/stall_capacity_accept_boundary
    """
    ctx = _four_verified_entries_on_a_five_stall_show()
    first, second = ctx["rows"][0], ctx["rows"][1]

    before = get_show(ctx["show_id"])
    assert before["reserved_stall_count"] == 0
    assert before["available_stall_count"] == 5

    accepted = validate_success(
        api_client.accept_entry(first["entry_id"], TEST_USERS["show_secretary_headers"])
    )
    assert accepted["assigned_stall_count"] == 3
    mid = get_show(ctx["show_id"])
    assert mid["reserved_stall_count"] == 3
    assert mid["available_stall_count"] == 2

    validate_error(
        api_client.accept_entry(second["entry_id"], TEST_USERS["show_secretary_headers"]),
        "ERR_STALL_CAPACITY_EXCEEDED",
        409,
    )

    refused = get_entry(second["entry_id"])
    assert refused["verification_status"] == "VERIFIED"
    assert refused["assigned_stall_count"] == 0

    after = get_show(ctx["show_id"])
    assert after["reserved_stall_count"] == 3
    assert after["available_stall_count"] == 2
    assert after["stall_capacity"] == 5
    assert_stall_ledger_invariant(after)


def test_a_request_exactly_equal_to_the_remainder_and_a_zero_request_both_pass():
    """The comparison rejects only a strictly greater request. With two stalls left, an entry
    asking for exactly two is accepted and fills the grounds, and a fourth entry asking for zero
    is accepted even with nothing available at all. The retried three-stall request is still
    refused once the grounds are full, and the capacity itself never moves.

    PRD §3.5: "The entry's `requested_stall_count` must not exceed the show's current `available_stall_count`; only a strictly greater request is refused, and the refusal is `ERR_STALL_CAPACITY_EXCEEDED`."
    PRD §3.5: "**Acceptance.** Accepting a verified entry moves `VERIFIED → ACCEPTED` and is where stalls are actually committed."
    PRD §2.10: "The invariant `stall_capacity` equals `reserved_stall_count` plus `available_stall_count` holds before and after every acceptance and every withdrawal."

    Design: Difficulty/boundary_precision_check/stall_capacity_accept_boundary
    """
    ctx = _four_verified_entries_on_a_five_stall_show()
    first, second, third, fourth = ctx["rows"]

    validate_success(
        api_client.accept_entry(first["entry_id"], TEST_USERS["show_secretary_headers"])
    )
    validate_error(
        api_client.accept_entry(second["entry_id"], TEST_USERS["show_secretary_headers"]),
        "ERR_STALL_CAPACITY_EXCEEDED",
        409,
    )

    at_boundary = validate_success(
        api_client.accept_entry(third["entry_id"], TEST_USERS["show_secretary_headers"])
    )
    assert at_boundary["verification_status"] == "ACCEPTED"
    assert at_boundary["assigned_stall_count"] == 2
    full = get_show(ctx["show_id"])
    assert full["reserved_stall_count"] == 5
    assert full["available_stall_count"] == 0

    degenerate = validate_success(
        api_client.accept_entry(fourth["entry_id"], TEST_USERS["show_secretary_headers"])
    )
    assert degenerate["verification_status"] == "ACCEPTED"
    assert degenerate["assigned_stall_count"] == 0

    validate_error(
        api_client.accept_entry(second["entry_id"], TEST_USERS["show_secretary_headers"]),
        "ERR_STALL_CAPACITY_EXCEEDED",
        409,
    )

    end = get_show(ctx["show_id"])
    assert end["reserved_stall_count"] == 5
    assert end["available_stall_count"] == 0
    assert end["stall_capacity"] == 5
    assert_stall_ledger_invariant(end)
