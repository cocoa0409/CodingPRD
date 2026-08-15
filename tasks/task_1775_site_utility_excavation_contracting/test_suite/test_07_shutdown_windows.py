"""Shutdown windows: temporal rules, owner overlap, project buffer, the
committed-minutes ledger, OCC on the project, and tie-in completion."""

from test_helpers import (
    FOREMAN,
    PROJECT_MANAGER,
    ApiErrorId,
    advance_clock,
    create_locate_ticket,
    create_project,
    create_segment,
    create_unforeseen_condition,
    create_utility_owner,
    get_owner,
    get_project,
    get_segment,
    get_window,
    make_utility_owner_rep_headers,
    propose_shutdown_window,
    setup_ready_segment,
    validate_error,
    validate_paginated,
    validate_success,
)

def test_window_complete_releases_minutes_and_marks_tiein(api):
    """PRD §3.5: "When the tie-in is finished inside an `ACTIVE` window, the
    `Foreman` completes it, moving `ACTIVE → COMPLETED`: the segment's
    `tie_in_completed` flips to true and the owner's committed minutes fall by
    the window's duration."
    PRD §2.5: "Fourth, shutdown windows move: a window still `PROPOSED` when
    its `window_start` passes becomes `MISSED`; a `CONFIRMED` window becomes
    `ACTIVE` when its start is reached while the project's work posture is
    `CLEAR`; and a window in `CONFIRMED` or `ACTIVE` becomes `MISSED` once its
    `window_end` passes."

    Design: Corner/state_machines/window_complete_releases_minutes_and_marks_tiein
    """
    ctx = setup_ready_segment(
        owner_overrides={"min_notice_hours": 24, "max_shutdown_hours": 12}
    )
    owner, segment = ctx["owner"], ctx["segment"]

    window = propose_shutdown_window(
        ctx["project"], owner, segment,
        "2026-08-04T08:00:00Z", "2026-08-04T10:00:00Z",
    )
    assert window["status"] == "PROPOSED"
    assert window["duration_minutes"] == 120
    assert get_owner(owner["id"])["committed_shutdown_minutes"] == 120

    confirmed = validate_success(
        api.review_shutdown_window(
            window["id"], "CONFIRM",
            make_utility_owner_rep_headers(owner["id"]),
        )
    )
    assert confirmed["status"] == "CONFIRMED"

    advance_clock("2026-08-04T08:30:00Z")
    assert get_window(window["id"])["status"] == "ACTIVE"

    completed = validate_success(api.complete_shutdown_window(window["id"], FOREMAN))
    assert completed["status"] == "COMPLETED"
    assert get_segment(segment["id"])["tie_in_completed"] is True
    assert get_owner(owner["id"])["committed_shutdown_minutes"] == 0


def test_proposed_window_misses_at_start(api):
    """PRD §3.5: "From there, the clock decides fate as laid out in §2.5: a
    window still `PROPOSED` when its start passes becomes `MISSED` and
    releases its minutes"

    Design: Corner/state_machines/proposed_window_misses_at_start
    """
    project = create_project(name="P-MIS", contract_ref="C-208")
    owner = create_utility_owner(min_notice_hours=24, max_shutdown_hours=12)
    segment = create_segment(project, owner, segment_label="WL-M-01")

    window = propose_shutdown_window(
        project, owner, segment,
        "2026-08-03T10:00:00Z", "2026-08-03T12:00:00Z",
        expected_project_version=project["version"],
    )
    assert get_owner(owner["id"])["committed_shutdown_minutes"] == 120

    advance_clock("2026-08-03T10:00:01Z")
    assert get_window(window["id"])["status"] == "MISSED"
    assert get_owner(owner["id"])["committed_shutdown_minutes"] == 0


def test_window_in_past_beats_insufficient_notice(api):
    """PRD §2.10: "Eighth come the temporal rules, also sub-ordered: a
    `window_start` that is not strictly in the future is
    `ERR_WINDOW_IN_PAST`; insufficient notice to the owner is
    `ERR_INSUFFICIENT_NOTICE`; overlap with the owner's existing committed
    windows is `ERR_OWNER_WINDOW_OVERLAP`; insufficient clearance from the
    project's other committed windows is `ERR_PROJECT_WINDOW_BUFFER`; and a
    reading timestamped outside its permit's effective window is
    `ERR_READING_OUTSIDE_PERMIT_WINDOW`."

    Design: Corner/validations/window_in_past_beats_notice
    """
    project = create_project(name="P-WP", contract_ref="C-403")
    owner = create_utility_owner(min_notice_hours=48, max_shutdown_hours=8)
    segment = create_segment(project, owner, segment_label="WL-V-03")

    # 2026-07-31 lies before the default clock (2026-08-01): both the
    # in-past rule and the 48h-notice rule are violated; (a) must win.
    response = api.create_shutdown_window(
        {
            "project_id": project["id"], "utility_owner_id": owner["id"],
            "pipe_segment_id": segment["id"],
            "window_start": "2026-07-31T10:00:00Z",
            "window_end": "2026-07-31T12:00:00Z",
            "expected_project_version": project["version"],
        },
        PROJECT_MANAGER,
    )
    validate_error(response, ApiErrorId.ERR_WINDOW_IN_PAST, 422)


def test_insufficient_notice_rejected(api):
    """PRD §3.5: "The gap between the current time and `window_start` must be
    at least the owner's `min_notice_hours` (`ERR_INSUFFICIENT_NOTICE`)."

    Design: Corner/validations/insufficient_notice_rejected
    """
    project = create_project(name="P-NTC", contract_ref="C-404")
    owner72 = create_utility_owner(
        name="Slow Water", owner_type="WATER",
        min_notice_hours=72, max_shutdown_hours=12,
    )
    owner24 = create_utility_owner(
        name="Fast Gas", owner_type="GAS",
        min_notice_hours=24, max_shutdown_hours=12,
    )
    s72 = create_segment(project, owner72, segment_label="WL-V-04")
    s24 = create_segment(
        project, owner24, segment_label="GS-V-05", pipe_material="HDPE",
        diameter_in=6, length_ft=100.0, bedding_class="CLASS_C",
        design_invert_depth_ft=6.0, design_slope_pct=0.5,
    )

    # 2026-08-03T10:00:00Z is 58h after the default clock — short of 72h.
    response = api.create_shutdown_window(
        {
            "project_id": project["id"], "utility_owner_id": owner72["id"],
            "pipe_segment_id": s72["id"],
            "window_start": "2026-08-03T10:00:00Z",
            "window_end": "2026-08-03T12:00:00Z",
            "expected_project_version": project["version"],
        },
        PROJECT_MANAGER,
    )
    validate_error(response, ApiErrorId.ERR_INSUFFICIENT_NOTICE, 422)

    # The same window against the 24h-notice owner passes.
    window = propose_shutdown_window(
        project, owner24, s24,
        "2026-08-03T10:00:00Z", "2026-08-03T12:00:00Z",
    )
    assert window["status"] == "PROPOSED"


def test_owner_rep_of_another_owner_cannot_confirm(api):
    """PRD §3.5: "The owner's answer comes from a `UtilityOwnerRep` whose
    `X-User-ID` equals the window's `utility_owner_id` (any other caller draws
    `ERR_UNAUTHORIZED_ROLE`), passing a `decision` of `CONFIRM` or `REJECT`
    and thereby moving the window from `PROPOSED` to `CONFIRMED` or
    `REJECTED`."

    Design: Corner/rbac/owner_rep_mismatch_denied
    """
    project = create_project(name="P-RB4", contract_ref="C-703")
    owner1 = create_utility_owner(
        name="City Water", min_notice_hours=24, max_shutdown_hours=12
    )
    owner2 = create_utility_owner(
        name="Gas Co", owner_type="GAS", min_notice_hours=24,
        max_shutdown_hours=12,
    )
    segment = create_segment(project, owner1, segment_label="WL-R-22")
    window = propose_shutdown_window(
        project, owner1, segment,
        "2026-08-03T10:00:00Z", "2026-08-03T12:00:00Z",
        expected_project_version=project["version"],
    )

    response = api.review_shutdown_window(
        window["id"], "CONFIRM", make_utility_owner_rep_headers(owner2["id"])
    )
    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED_ROLE, 403)
    assert get_window(window["id"])["status"] == "PROPOSED"


def test_window_book_with_stale_project_version_rejected(api):
    """PRD §2.9: "Two creation operations — proposing a shutdown window and
    creating a change order — are guarded by optimistic concurrency control on
    the project they reference. Each such request must carry
    `expected_project_version`, the `version` of the project as the client
    last observed it; the field is not optional on these two creates. If the
    project's current `version` has advanced beyond the supplied value — for
    example because another writer has just booked a window, an operation that
    legitimately succeeds and bumps the project's version — the create is
    rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/complexity_layers/window_book_stale_version_rejected
    """
    project = create_project(name="P-OCC1", contract_ref="C-800")
    owner = create_utility_owner(min_notice_hours=24, max_shutdown_hours=12)
    segment = create_segment(project, owner, segment_label="WL-O-01")

    window1 = propose_shutdown_window(
        project, owner, segment,
        "2026-08-03T10:00:00Z", "2026-08-03T12:00:00Z",
        expected_project_version=project["version"],
    )
    assert window1["status"] == "PROPOSED"
    assert get_project(project["id"])["version"] == 2

    # The second create still carries the pre-W1 version.
    response = api.create_shutdown_window(
        {
            "project_id": project["id"], "utility_owner_id": owner["id"],
            "pipe_segment_id": segment["id"],
            "window_start": "2026-08-04T10:00:00Z",
            "window_end": "2026-08-04T12:00:00Z",
            "expected_project_version": project["version"],
        },
        PROJECT_MANAGER,
    )
    validate_error(response, ApiErrorId.ERR_STALE_VERSION, 412)

    _, meta = validate_paginated(
        api.list_shutdown_windows(PROJECT_MANAGER, params={"project_id": project["id"]})
    )
    assert meta["total_count"] == 1, "rejected create must not persist"


def test_owner_window_half_open_adjacency(api):
    """PRD §3.5: "The new window must not overlap any existing `PROPOSED`,
    `CONFIRMED`, or `ACTIVE` window of the same owner under half-open
    semantics — two windows that merely touch endpoints do not overlap
    (`ERR_OWNER_WINDOW_OVERLAP`)."
    PRD §2.10: "Eighth come the temporal rules, also sub-ordered: a
    `window_start` that is not strictly in the future is
    `ERR_WINDOW_IN_PAST`; insufficient notice to the owner is
    `ERR_INSUFFICIENT_NOTICE`; overlap with the owner's existing committed
    windows is `ERR_OWNER_WINDOW_OVERLAP`; insufficient clearance from the
    project's other committed windows is `ERR_PROJECT_WINDOW_BUFFER`; and a
    reading timestamped outside its permit's effective window is
    `ERR_READING_OUTSIDE_PERMIT_WINDOW`."

    Design: Difficulty/resource_temporal_overlap/owner_window_half_open_adjacency
    """
    p1 = create_project(name="P1-OV", contract_ref="C-1500")
    p2 = create_project(name="P2-OV", contract_ref="C-1501")
    owner = create_utility_owner(min_notice_hours=24, max_shutdown_hours=12)
    s1 = create_segment(p1, owner, segment_label="WL-I-01")
    s2 = create_segment(p2, owner, segment_label="WL-I-02")

    w1 = propose_shutdown_window(
        p1, owner, s1, "2026-08-03T10:00:00Z", "2026-08-03T12:00:00Z",
        expected_project_version=p1["version"],
    )
    # Touching endpoint: W2 starts exactly where W1 ends — not an overlap.
    w2 = propose_shutdown_window(
        p2, owner, s2, "2026-08-03T12:00:00Z", "2026-08-03T14:00:00Z",
        expected_project_version=p2["version"],
    )
    assert w1["status"] == "PROPOSED" and w2["status"] == "PROPOSED"
    assert get_owner(owner["id"])["committed_shutdown_minutes"] == 240

    # Straddling W1's end is a strict overlap.
    response = api.create_shutdown_window(
        {
            "project_id": p2["id"], "utility_owner_id": owner["id"],
            "pipe_segment_id": s2["id"],
            "window_start": "2026-08-03T11:30:00Z",
            "window_end": "2026-08-03T12:30:00Z",
            "expected_project_version": get_project(p2["id"])["version"],
        },
        PROJECT_MANAGER,
    )
    validate_error(response, ApiErrorId.ERR_OWNER_WINDOW_OVERLAP, 409)


def test_owner_window_containment_is_an_overlap(api):
    """PRD §3.5: "The new window must not overlap any existing `PROPOSED`,
    `CONFIRMED`, or `ACTIVE` window of the same owner under half-open
    semantics — two windows that merely touch endpoints do not overlap
    (`ERR_OWNER_WINDOW_OVERLAP`)."
    PRD §2.10: "Eighth come the temporal rules, also sub-ordered: a
    `window_start` that is not strictly in the future is
    `ERR_WINDOW_IN_PAST`; insufficient notice to the owner is
    `ERR_INSUFFICIENT_NOTICE`; overlap with the owner's existing committed
    windows is `ERR_OWNER_WINDOW_OVERLAP`; insufficient clearance from the
    project's other committed windows is `ERR_PROJECT_WINDOW_BUFFER`; and a
    reading timestamped outside its permit's effective window is
    `ERR_READING_OUTSIDE_PERMIT_WINDOW`."

    Design: Difficulty/resource_temporal_overlap/owner_window_half_open_adjacency
    """
    project = create_project(name="P-OVC", contract_ref="C-1502")
    owner = create_utility_owner(min_notice_hours=24, max_shutdown_hours=12)
    segment = create_segment(project, owner, segment_label="WL-I-03")

    propose_shutdown_window(
        project, owner, segment,
        "2026-08-03T10:00:00Z", "2026-08-03T12:00:00Z",
        expected_project_version=project["version"],
    )
    # Fully covering the existing window is a strict overlap.
    response = api.create_shutdown_window(
        {
            "project_id": project["id"], "utility_owner_id": owner["id"],
            "pipe_segment_id": segment["id"],
            "window_start": "2026-08-03T09:00:00Z",
            "window_end": "2026-08-03T13:00:00Z",
            "expected_project_version": get_project(project["id"])["version"],
        },
        PROJECT_MANAGER,
    )
    validate_error(response, ApiErrorId.ERR_OWNER_WINDOW_OVERLAP, 409)


def test_project_window_buffer_clearance(api):
    """PRD §3.5: "And the new window must keep at least 120 minutes of
    clearance from every existing `PROPOSED`, `CONFIRMED`, or `ACTIVE` window
    of the same project, with exactly 120 minutes of clearance passing
    (`ERR_PROJECT_WINDOW_BUFFER`)."

    Design: Difficulty/resource_temporal_overlap/project_window_buffer_clearance
    """
    project = create_project(name="P-BUF", contract_ref="C-1600")
    owner1 = create_utility_owner(
        name="City Water", min_notice_hours=24, max_shutdown_hours=12
    )
    owner2 = create_utility_owner(
        name="Gas Co", owner_type="GAS", min_notice_hours=24,
        max_shutdown_hours=12,
    )
    s1 = create_segment(project, owner1, segment_label="WL-J-01")
    s2 = create_segment(
        project, owner2, segment_label="GS-J-02", pipe_material="HDPE",
        diameter_in=6, length_ft=100.0, bedding_class="CLASS_C",
        design_invert_depth_ft=6.0, design_slope_pct=0.5,
    )

    propose_shutdown_window(
        project, owner1, s1, "2026-08-03T10:00:00Z", "2026-08-03T12:00:00Z",
        expected_project_version=project["version"],
    )

    # 60-minute gap — under the 120-minute clearance.
    response = api.create_shutdown_window(
        {
            "project_id": project["id"], "utility_owner_id": owner2["id"],
            "pipe_segment_id": s2["id"],
            "window_start": "2026-08-03T13:00:00Z",
            "window_end": "2026-08-03T15:00:00Z",
            "expected_project_version": get_project(project["id"])["version"],
        },
        PROJECT_MANAGER,
    )
    validate_error(response, ApiErrorId.ERR_PROJECT_WINDOW_BUFFER, 409)

    # Exactly 120 minutes of clearance passes (inclusive).
    w3 = propose_shutdown_window(
        project, owner2, s2, "2026-08-03T14:00:00Z", "2026-08-03T16:00:00Z",
    )
    assert w3["status"] == "PROPOSED"
    # The two windows use different owners, so the owner-overlap rule never
    # fires; each owner's ledger carries its own 120 minutes.
    assert get_owner(owner1["id"])["committed_shutdown_minutes"] == 120
    assert get_owner(owner2["id"])["committed_shutdown_minutes"] == 120


def test_project_window_buffer_applies_before_existing_window(api):
    """PRD §3.5: "And the new window must keep at least 120 minutes of
    clearance from every existing `PROPOSED`, `CONFIRMED`, or `ACTIVE` window
    of the same project, with exactly 120 minutes of clearance passing
    (`ERR_PROJECT_WINDOW_BUFFER`)."

    Design: Difficulty/resource_temporal_overlap/project_window_buffer_clearance
    """
    project = create_project(name="P-BUF2", contract_ref="C-1601")
    owner1 = create_utility_owner(
        name="City Water", min_notice_hours=24, max_shutdown_hours=12
    )
    owner2 = create_utility_owner(
        name="Gas Co", owner_type="GAS", min_notice_hours=24,
        max_shutdown_hours=12,
    )
    s1 = create_segment(project, owner1, segment_label="WL-J-03")
    s2 = create_segment(
        project, owner2, segment_label="GS-J-04", pipe_material="HDPE",
        diameter_in=6, length_ft=100.0, bedding_class="CLASS_C",
        design_invert_depth_ft=6.0, design_slope_pct=0.5,
    )

    propose_shutdown_window(
        project, owner1, s1, "2026-08-03T10:00:00Z", "2026-08-03T12:00:00Z",
        expected_project_version=project["version"],
    )

    # Ending 119 minutes before the existing start is short of clearance.
    response = api.create_shutdown_window(
        {
            "project_id": project["id"], "utility_owner_id": owner2["id"],
            "pipe_segment_id": s2["id"],
            "window_start": "2026-08-03T07:01:00Z",
            "window_end": "2026-08-03T08:01:00Z",
            "expected_project_version": get_project(project["id"])["version"],
        },
        PROJECT_MANAGER,
    )
    validate_error(response, ApiErrorId.ERR_PROJECT_WINDOW_BUFFER, 409)

    # Ending exactly 120 minutes before the existing start passes.
    before = propose_shutdown_window(
        project, owner2, s2, "2026-08-03T07:00:00Z", "2026-08-03T08:00:00Z",
    )
    assert before["status"] == "PROPOSED"


def test_committed_minutes_book_then_cancel_conserved(api):
    """PRD §3.5: "A created window starts `PROPOSED`, and booking it already
    commits the owner's time: the owner's `committed_shutdown_minutes` rises
    by `duration_minutes`, and the project's `version` increments by one as
    the schedule changes."
    PRD §3.5: "A `ProjectManager` may instead cancel: a `PROPOSED` window may
    be cancelled at any time, while a `CONFIRMED` window may be cancelled only
    while the current time is still before its `window_end` — once the end has
    passed, the window is in missed territory and the cancel is rejected with
    `ERR_INVALID_STATE`. Cancellation releases the committed minutes in both
    cases."

    Design: Difficulty/compensating_invariant/owner_committed_minutes_book_then_cancel
    """
    project = create_project(name="P-INV1", contract_ref="C-1700")
    owner = create_utility_owner(min_notice_hours=24, max_shutdown_hours=12)
    segment = create_segment(project, owner, segment_label="WL-K-01")
    assert get_owner(owner["id"])["committed_shutdown_minutes"] == 0

    window = propose_shutdown_window(
        project, owner, segment,
        "2026-08-03T10:00:00Z", "2026-08-03T13:00:00Z",
        expected_project_version=project["version"],
    )
    assert window["duration_minutes"] == 180
    assert get_owner(owner["id"])["committed_shutdown_minutes"] == 180

    cancelled = validate_success(
        api.cancel_shutdown_window(window["id"], PROJECT_MANAGER)
    )
    assert cancelled["status"] == "CANCELLED"
    assert get_owner(owner["id"])["committed_shutdown_minutes"] == 0


def test_committed_minutes_book_then_reject_conserved(api):
    """PRD §3.5: "an owner's committed minutes are the total `duration_minutes`
    of that owner's windows in `PROPOSED`, `CONFIRMED`, or `ACTIVE`, and
    windows in any terminal state — `COMPLETED`, `MISSED`, `REJECTED`, or
    `CANCELLED` — contribute zero."
    PRD §3.5: "A rejection releases the window's minutes back off the ledger."

    Design: Difficulty/compensating_invariant/owner_committed_minutes_book_then_cancel
    """
    project = create_project(name="P-INV1R", contract_ref="C-1701")
    owner = create_utility_owner(min_notice_hours=24, max_shutdown_hours=12)
    segment = create_segment(project, owner, segment_label="WL-K-02")

    window = propose_shutdown_window(
        project, owner, segment,
        "2026-08-03T10:00:00Z", "2026-08-03T13:00:00Z",
        expected_project_version=project["version"],
    )
    assert get_owner(owner["id"])["committed_shutdown_minutes"] == 180

    rejected = validate_success(
        api.review_shutdown_window(
            window["id"], "REJECT", make_utility_owner_rep_headers(owner["id"])
        )
    )
    assert rejected["status"] == "REJECTED"
    assert get_owner(owner["id"])["committed_shutdown_minutes"] == 0


def test_window_confirm_blocked_while_project_stopped(api):
    """PRD §3.5: "Confirming additionally requires the project's posture to be
    `CLEAR` (`ERR_PROJECT_STOPPED`) and the tied-in segment to be in `READY`,
    `INSTALLING`, `INSTALLED`, or `BACKFILLING` (`ERR_INVALID_STATE`); a
    confirmation leaves the committed-minutes ledger unchanged, because
    `PROPOSED` already counted."

    Design: Difficulty/cross_entity_state_dependency/window_confirm_gated_by_project_posture
    """
    ctx = setup_ready_segment()
    project, owner, segment = ctx["project"], ctx["owner"], ctx["segment"]
    window = propose_shutdown_window(
        project, owner, segment,
        "2026-08-05T10:00:00Z", "2026-08-05T12:00:00Z",
    )

    condition = create_unforeseen_condition(
        project, condition_type="CONFLICTING_UTILITY", stop_work_required=True,
        description="unmarked gas line",
    )
    assert get_project(project["id"])["work_posture"] == "STOPPED"

    response = api.review_shutdown_window(
        window["id"], "CONFIRM", make_utility_owner_rep_headers(owner["id"])
    )
    validate_error(response, ApiErrorId.ERR_PROJECT_STOPPED, 409)
    assert get_window(window["id"])["status"] == "PROPOSED"
    assert get_owner(owner["id"])["committed_shutdown_minutes"] == 120
    assert condition["status"] == "OPEN"


def test_window_confirm_succeeds_once_posture_clears(api):
    """PRD §3.5: "Confirming additionally requires the project's posture to be
    `CLEAR` (`ERR_PROJECT_STOPPED`) and the tied-in segment to be in `READY`,
    `INSTALLING`, `INSTALLED`, or `BACKFILLING` (`ERR_INVALID_STATE`); a
    confirmation leaves the committed-minutes ledger unchanged, because
    `PROPOSED` already counted."
    PRD §3.7: "Whenever a stop-work condition leaves `OPEN`, the project's
    posture recomputes: if no other `OPEN` condition with `stop_work_required`
    remains, the posture clears and every segment held with `hold_reason`
    `STOP_WORK` resumes per §2.6; segments held for `DEWATERING` are not
    resumed by this transition."

    Design: Difficulty/cross_entity_state_dependency/window_confirm_gated_by_project_posture
    """
    ctx = setup_ready_segment()
    project, owner, segment = ctx["project"], ctx["owner"], ctx["segment"]
    window = propose_shutdown_window(
        project, owner, segment,
        "2026-08-05T10:00:00Z", "2026-08-05T12:00:00Z",
    )

    condition = create_unforeseen_condition(
        project, condition_type="CONFLICTING_UTILITY", stop_work_required=True,
        description="unmarked gas line",
    )
    response = api.review_shutdown_window(
        window["id"], "CONFIRM", make_utility_owner_rep_headers(owner["id"])
    )
    validate_error(response, ApiErrorId.ERR_PROJECT_STOPPED, 409)

    resolved = validate_success(
        api.resolve_unforeseen_condition(
            condition["id"], "RESOLVED", PROJECT_MANAGER
        )
    )
    assert resolved["status"] == "RESOLVED"
    assert get_project(project["id"])["work_posture"] == "CLEAR"

    confirmed = validate_success(
        api.review_shutdown_window(
            window["id"], "CONFIRM", make_utility_owner_rep_headers(owner["id"])
        )
    )
    assert confirmed["status"] == "CONFIRMED"
    # PROPOSED already counted, so confirmation does not move the ledger.
    assert get_owner(owner["id"])["committed_shutdown_minutes"] == 120


def test_mutations_visible_immediately(api):
    """PRD §2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data
    field."
    PRD §3.5: "A created window starts `PROPOSED`, and booking it already
    commits the owner's time: the owner's `committed_shutdown_minutes` rises
    by `duration_minutes`, and the project's `version` increments by one as
    the schedule changes."

    Design: Corner/consistency_model/mutation_visible_immediately
    """
    project = create_project(name="P-IMM", contract_ref="C-900")
    owner = create_utility_owner(min_notice_hours=24, max_shutdown_hours=12)
    ticket = create_locate_ticket(
        project["id"], ticket_number="T-1",
        legal_start_at="2026-08-03T00:00:00Z",
    )
    segment = create_segment(project, owner, segment_label="WL-I-99")

    submitted = validate_success(
        api.submit_locate_ticket(ticket["id"], PROJECT_MANAGER)
    )
    assert submitted["status"] == "SUBMITTED"

    propose_shutdown_window(
        project, owner, segment,
        "2026-08-03T10:00:00Z", "2026-08-03T12:00:00Z",
        expected_project_version=project["version"],
    )
    # The ledger effect is visible in the very next read.
    assert get_owner(owner["id"])["committed_shutdown_minutes"] == 120
