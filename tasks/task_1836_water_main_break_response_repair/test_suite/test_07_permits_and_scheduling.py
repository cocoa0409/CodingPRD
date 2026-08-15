"""Traffic permits and restoration scheduling: half-open overlap, permit-state
gate, window coverage, and the referential-vs-temporal priority ordering."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    confirm_break,
    create_approved_permit,
    create_break,
    create_traffic_permit_payload,
    get_restoration_job,
    schedule_restoration_job_payload,
    setup_confirmed_break,
    setup_repaired_break,
    validate_error,
    validate_success,
)
from test_helpers import api_client as _api

DISPATCHER = TEST_USERS["dispatcher_headers"]
ENGINEER = TEST_USERS["engineer_headers"]


def _elm_repaired_with_pending_job():
    """Break on MAIN-8-ELM fully repaired; its restoration job PENDING."""
    return setup_repaired_break(
        segment_ref="MAIN-8-ELM", material="CAST_IRON", diameter_inches=8,
        install_year=1962, break_type="CIRCUMFERENTIAL", severity="MEDIUM",
        location_description="100 Elm St",
        crew_name="Crew Beta", crew_rate=6000,
    )


# ---------------------------------------------------------------------------
# Difficulty: schedule_gated_on_permit_approved (2 tests)
# ---------------------------------------------------------------------------

def test_schedule_rejected_while_permit_applied(api):
    """PRD §3.6: "Four conditions hold: the referenced permit must belong to
    the same break as the job's work order (otherwise
    `ERR_CROSS_REFERENCE_MISMATCH`); the permit must be `APPROVED` (otherwise
    `ERR_PERMIT_NOT_APPROVED`); the permit's half-open validity window must
    fully cover the scheduled window, meaning `valid_from` is at or before
    `scheduled_start` and `valid_to` is at or after `scheduled_end` (otherwise
    `ERR_PERMIT_WINDOW_MISMATCH`); and `scheduled_start` must be before
    `scheduled_end` (otherwise `ERR_VALIDATION`)."

    Design: Difficulty/cross_entity_state_dependency/schedule_gated_on_permit_approved
    """
    ctx = _elm_repaired_with_pending_job()
    br, rj = ctx["break"], ctx["restoration_job"]
    perm = validate_success(
        _api.create_traffic_permit(
            create_traffic_permit_payload(
                break_report_id=br["id"], street_block="ELM-100-BLK",
                valid_from="2026-08-10T00:00:00Z", valid_to="2026-08-12T00:00:00Z",
            ),
            DISPATCHER,
        ),
        201,
    )
    assert perm["permit_status"] == "APPLIED"
    resp = _api.schedule_restoration_job(
        rj["id"],
        schedule_restoration_job_payload(
            scheduled_start="2026-08-10T08:00:00Z",
            scheduled_end="2026-08-10T16:00:00Z",
            traffic_permit_id=perm["id"],
        ),
        DISPATCHER,
    )
    validate_error(resp, ApiErrorId.ERR_PERMIT_NOT_APPROVED)
    assert get_restoration_job(rj["id"])["restoration_status"] == "PENDING"


def test_schedule_succeeds_after_permit_approved(api):
    """PRD §3.6: "A new permit's `permit_status` is born `APPLIED`; a
    `PublicWorksEngineer` approves it, moving it to `APPROVED`."
    PRD §3.6: "Scheduling moves the job to `SCHEDULED` and records the window
    and permit."

    Design: Difficulty/cross_entity_state_dependency/schedule_gated_on_permit_approved
    """
    ctx = _elm_repaired_with_pending_job()
    br, rj = ctx["break"], ctx["restoration_job"]
    perm = validate_success(
        _api.create_traffic_permit(
            create_traffic_permit_payload(
                break_report_id=br["id"], street_block="ELM-100-BLK",
                valid_from="2026-08-10T00:00:00Z", valid_to="2026-08-12T00:00:00Z",
            ),
            DISPATCHER,
        ),
        201,
    )
    # Gate fails while APPLIED.
    resp = _api.schedule_restoration_job(
        rj["id"],
        schedule_restoration_job_payload(
            scheduled_start="2026-08-10T08:00:00Z",
            scheduled_end="2026-08-10T16:00:00Z",
            traffic_permit_id=perm["id"],
        ),
        DISPATCHER,
    )
    validate_error(resp, ApiErrorId.ERR_PERMIT_NOT_APPROVED)
    # Approve; the identical schedule call now succeeds.
    validate_success(_api.approve_traffic_permit(perm["id"], ENGINEER), 200)
    scheduled = validate_success(
        _api.schedule_restoration_job(
            rj["id"],
            schedule_restoration_job_payload(
                scheduled_start="2026-08-10T08:00:00Z",
                scheduled_end="2026-08-10T16:00:00Z",
                traffic_permit_id=perm["id"],
            ),
            DISPATCHER,
        ),
        200,
    )
    assert scheduled["restoration_status"] == "SCHEDULED"
    assert scheduled["traffic_permit_id"] == perm["id"]


# ---------------------------------------------------------------------------
# Difficulty: schedule_conflict_referential_beats_temporal (2 tests)
# ---------------------------------------------------------------------------

def _two_breaks_with_other_break_permit():
    """Break A on MAIN-8-ELM fully repaired (job PENDING); break B confirmed on
    the same segment with an APPROVED permit for 2026-08-10..2026-08-12."""
    ctx = _elm_repaired_with_pending_job()
    seg = ctx["segment"]
    br_b = create_break(location_description="240 Elm St", source="SENSOR_SCADA")
    br_b = confirm_break(br_b["id"], seg["id"], break_type="SPLIT", severity="LOW")
    perm_b = create_approved_permit(
        br_b["id"], street_block="ELM-200-BLK",
        valid_from="2026-08-10T00:00:00Z", valid_to="2026-08-12T00:00:00Z",
    )
    ctx.update({"break_b": br_b, "permit_b": perm_b})
    return ctx


def test_cross_break_permit_rejected_referential_error(api):
    """PRD §3.6: "Four conditions hold: the referenced permit must belong to
    the same break as the job's work order (otherwise
    `ERR_CROSS_REFERENCE_MISMATCH`); the permit must be `APPROVED` (otherwise
    `ERR_PERMIT_NOT_APPROVED`); the permit's half-open validity window must
    fully cover the scheduled window, meaning `valid_from` is at or before
    `scheduled_start` and `valid_to` is at or after `scheduled_end` (otherwise
    `ERR_PERMIT_WINDOW_MISMATCH`); and `scheduled_start` must be before
    `scheduled_end` (otherwise `ERR_VALIDATION`)."
    PRD §2.7: "After state legality come the domain guard tiers: water-quality
    compliance (`ERR_ADVISORY_TESTS_INSUFFICIENT`, `ERR_SEGREGATION_OF_DUTIES`,
    `ERR_TEST_SAMPLE_TOO_SOON`), cross-aggregate referential integrity
    (`ERR_CROSS_REFERENCE_MISMATCH`, `ERR_SEGMENT_REPLACED`), temporal windows
    (`ERR_CLAIM_FILED_LATE`, `ERR_PERMIT_WINDOW_MISMATCH`, `ERR_PERMIT_OVERLAP`,
    `ERR_CREW_DOUBLE_BOOKED`, `ERR_CORRELATION_WINDOW`), structural constraints
    (`ERR_BREAK_NOT_ISOLATED`, `ERR_DUPLICATE_ACTIVE_WORK_ORDER`,
    `ERR_ADVISORY_ALREADY_OPEN`, `ERR_ADVISORY_STILL_ACTIVE`, `ERR_CLAIMS_OPEN`,
    `ERR_NO_CREW_AVAILABLE`), and finally fiscal rules (`ERR_INVALID_AMOUNT`
    with HTTP 400, and `ERR_AMOUNT_EXCEEDS_CLAIMED` with HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/schedule_conflict_referential_beats_temporal
    """
    ctx = _two_breaks_with_other_break_permit()
    rj, perm_b = ctx["restoration_job"], ctx["permit_b"]
    # The window 2026-09-01 is also outside the permit's validity, so both the
    # referential and the temporal rule are violated; referential wins.
    resp = _api.schedule_restoration_job(
        rj["id"],
        schedule_restoration_job_payload(
            scheduled_start="2026-09-01T08:00:00Z",
            scheduled_end="2026-09-01T16:00:00Z",
            traffic_permit_id=perm_b["id"],
        ),
        DISPATCHER,
    )
    validate_error(resp, ApiErrorId.ERR_CROSS_REFERENCE_MISMATCH)


def test_referential_rejection_leaves_job_pending(api):
    """PRD §2.7: "When several checks could reject the same request, they are
    evaluated in a fixed order so that the surfaced error is deterministic."
    PRD §2.7: "After state legality come the domain guard tiers: water-quality
    compliance (`ERR_ADVISORY_TESTS_INSUFFICIENT`, `ERR_SEGREGATION_OF_DUTIES`,
    `ERR_TEST_SAMPLE_TOO_SOON`), cross-aggregate referential integrity
    (`ERR_CROSS_REFERENCE_MISMATCH`, `ERR_SEGMENT_REPLACED`), temporal windows
    (`ERR_CLAIM_FILED_LATE`, `ERR_PERMIT_WINDOW_MISMATCH`, `ERR_PERMIT_OVERLAP`,
    `ERR_CREW_DOUBLE_BOOKED`, `ERR_CORRELATION_WINDOW`), structural constraints
    (`ERR_BREAK_NOT_ISOLATED`, `ERR_DUPLICATE_ACTIVE_WORK_ORDER`,
    `ERR_ADVISORY_ALREADY_OPEN`, `ERR_ADVISORY_STILL_ACTIVE`, `ERR_CLAIMS_OPEN`,
    `ERR_NO_CREW_AVAILABLE`), and finally fiscal rules (`ERR_INVALID_AMOUNT`
    with HTTP 400, and `ERR_AMOUNT_EXCEEDS_CLAIMED` with HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/schedule_conflict_referential_beats_temporal
    """
    ctx = _two_breaks_with_other_break_permit()
    rj, perm_b = ctx["restoration_job"], ctx["permit_b"]
    resp = _api.schedule_restoration_job(
        rj["id"],
        schedule_restoration_job_payload(
            scheduled_start="2026-09-01T08:00:00Z",
            scheduled_end="2026-09-01T16:00:00Z",
            traffic_permit_id=perm_b["id"],
        ),
        DISPATCHER,
    )
    err = validate_error(resp, ApiErrorId.ERR_CROSS_REFERENCE_MISMATCH)
    assert err["error_id"] != "ERR_PERMIT_WINDOW_MISMATCH", (
        "referential tier must win over the temporal tier when both fail"
    )
    assert get_restoration_job(rj["id"])["restoration_status"] == "PENDING"


# ---------------------------------------------------------------------------
# Difficulty: permit_half_open_overlap_semantics (2 tests)
# ---------------------------------------------------------------------------

def _oak_confirmed_with_permit_p1():
    """Confirmed break on MAIN-8-OAK; permit P1 on OAK-100-BLK valid
    [2026-08-10T00:00:00Z, 2026-08-12T00:00:00Z) in APPLIED."""
    ctx = setup_confirmed_break(
        segment_ref="MAIN-8-OAK", diameter_inches=8, install_year=1978,
        break_type="CIRCUMFERENTIAL", severity="MEDIUM",
        location_description="400 Oak St",
    )
    p1 = validate_success(
        _api.create_traffic_permit(
            create_traffic_permit_payload(
                break_report_id=ctx["break"]["id"], street_block="OAK-100-BLK",
                valid_from="2026-08-10T00:00:00Z", valid_to="2026-08-12T00:00:00Z",
            ),
            DISPATCHER,
        ),
        201,
    )
    ctx["permit_p1"] = p1
    return ctx


def test_adjacent_permit_window_accepted(api):
    """PRD §3.6: "Overlap is judged per street block: if any existing permit
    for the same `street_block` in `APPLIED` or `APPROVED` status has a
    validity window overlapping the new one under half-open semantics, the
    application is rejected with `ERR_PERMIT_OVERLAP`. Adjacency is not overlap
    — a new window starting exactly when an existing one ends is allowed."

    Design: Difficulty/resource_temporal_overlap/permit_half_open_overlap_semantics
    """
    ctx = _oak_confirmed_with_permit_p1()
    br = ctx["break"]
    p2 = validate_success(
        _api.create_traffic_permit(
            create_traffic_permit_payload(
                break_report_id=br["id"], street_block="OAK-100-BLK",
                valid_from="2026-08-12T00:00:00Z", valid_to="2026-08-14T00:00:00Z",
                control_plan="FULL_CLOSURE",
            ),
            DISPATCHER,
        ),
        201,
    )
    assert p2["permit_status"] == "APPLIED", (
        "a permit starting exactly when P1 ends (half-open adjacency) must be accepted"
    )


def test_overlapping_permit_window_rejected(api):
    """PRD §3.6: "Overlap is judged per street block: if any existing permit
    for the same `street_block` in `APPLIED` or `APPROVED` status has a
    validity window overlapping the new one under half-open semantics, the
    application is rejected with `ERR_PERMIT_OVERLAP`. Adjacency is not overlap
    — a new window starting exactly when an existing one ends is allowed."

    Design: Difficulty/resource_temporal_overlap/permit_half_open_overlap_semantics
    """
    ctx = _oak_confirmed_with_permit_p1()
    br = ctx["break"]
    # Adjacent permit accepted (proves the boundary is exactly at valid_to).
    validate_success(
        _api.create_traffic_permit(
            create_traffic_permit_payload(
                break_report_id=br["id"], street_block="OAK-100-BLK",
                valid_from="2026-08-12T00:00:00Z", valid_to="2026-08-14T00:00:00Z",
                control_plan="FULL_CLOSURE",
            ),
            DISPATCHER,
        ),
        201,
    )
    resp = _api.create_traffic_permit(
        create_traffic_permit_payload(
            break_report_id=br["id"], street_block="OAK-100-BLK",
            valid_from="2026-08-11T00:00:00Z", valid_to="2026-08-13T00:00:00Z",
            control_plan="FLAGGING",
        ),
        DISPATCHER,
    )
    validate_error(resp, ApiErrorId.ERR_PERMIT_OVERLAP)


# ---------------------------------------------------------------------------
# Corner: schedule_window_outside_permit_rejected
# ---------------------------------------------------------------------------

def test_schedule_window_outside_permit_rejected(api):
    """PRD §3.6: "Four conditions hold: the referenced permit must belong to
    the same break as the job's work order (otherwise
    `ERR_CROSS_REFERENCE_MISMATCH`); the permit must be `APPROVED` (otherwise
    `ERR_PERMIT_NOT_APPROVED`); the permit's half-open validity window must
    fully cover the scheduled window, meaning `valid_from` is at or before
    `scheduled_start` and `valid_to` is at or after `scheduled_end` (otherwise
    `ERR_PERMIT_WINDOW_MISMATCH`); and `scheduled_start` must be before
    `scheduled_end` (otherwise `ERR_VALIDATION`)."

    Design: Corner/validations/schedule_window_outside_permit_rejected
    """
    ctx = _elm_repaired_with_pending_job()
    br, rj = ctx["break"], ctx["restoration_job"]
    perm = create_approved_permit(
        br["id"], street_block="ELM-100-BLK",
        valid_from="2026-08-10T00:00:00Z", valid_to="2026-08-12T00:00:00Z",
    )
    resp = _api.schedule_restoration_job(
        rj["id"],
        schedule_restoration_job_payload(
            scheduled_start="2026-08-13T08:00:00Z",
            scheduled_end="2026-08-13T16:00:00Z",
            traffic_permit_id=perm["id"],
        ),
        DISPATCHER,
    )
    validate_error(resp, ApiErrorId.ERR_PERMIT_WINDOW_MISMATCH)
    assert get_restoration_job(rj["id"])["restoration_status"] == "PENDING"
