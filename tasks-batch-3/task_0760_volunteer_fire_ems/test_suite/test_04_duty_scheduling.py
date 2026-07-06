"""Duty-shift assignment gating: validation precedence, response-eligibility gate,
rest-buffer overlap, capacity, fiscal, OCC, ownership check-in, and versioning.

Queue A: priority_pair_validation_conflict/safety_beats_fiscal_on_assignment,
priority_pair_validation_conflict/state_beats_temporal_on_assignment,
cross_entity_state_dependency/assignment_requires_member_response_eligible,
resource_temporal_overlap/member_shift_rest_buffer_overlap.
Queue B: corner_cancel_shift_from_terminal_invalid, corner_apparatus_not_at_station_on_shift,
corner_shift_full_on_assignment, corner_dues_overdue_isolated,
corner_member_cannot_create_duty_shift, corner_member_checkin_ownership_denied,
corner_occ_duty_assignment_stale_shift_version, corner_version_increments_on_mutation.
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    CHIEF,
    create_officer,
    create_member,
    create_eligible_member,
    create_station_with_apparatus,
    create_draft_shift,
    create_published_shift,
    assign_member,
    current_shift_version,
    make_member_headers,
)
from test_helpers.factories import create_duty_shift_payload, create_member_payload


def _error_id(resp):
    return resp.json()["data"]["error_id"]


# ------------------------------------------------- safety (6) beats fiscal (10)
def _assign_probationary_with_dues(api):
    off_id, off = create_officer(api)
    station, apparatus = create_station_with_apparatus(api, apparatus_type="ENGINE")
    m = create_member(api, role_class="EMT", dues=5000)  # PROBATIONARY, not eligible
    sh = create_published_shift(api, off, station["id"], apparatus["id"], "2026-05-01T06:00:00Z", "2026-05-01T18:00:00Z")
    v = current_shift_version(api, off, sh["id"])
    return api.create_assignment(sh["id"], {"member_id": m["id"], "expected_duty_shift_version": v}, off)


def test_safety_check_beats_fiscal_returns_eligibility_error(api):
    """PRD §2.6: "6. **Response-eligibility (safety)** — for duty-assignment
    creation, the member being rostered must be response-eligible, else
    `ERR_MEMBER_NOT_RESPONSE_ELIGIBLE`."
    PRD §2.6: "they are evaluated in a fixed priority order, and the **first**
    failing check determines the error returned."

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_fiscal_on_assignment
    """
    validate_error(_assign_probationary_with_dues(api), ApiErrorId.ERR_MEMBER_NOT_RESPONSE_ELIGIBLE.value)


def test_safety_preempts_fiscal_not_dues_error(api):
    """PRD §2.6: "10. **Fiscal** — a member with an outstanding dues balance cannot
    be rostered (`ERR_DUES_OVERDUE`)."
    PRD §2.6: "a later, more specific rejection must never mask an earlier, more
    general one."

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_fiscal_on_assignment
    """
    err = _error_id(_assign_probationary_with_dues(api))
    assert err == "ERR_MEMBER_NOT_RESPONSE_ELIGIBLE"
    assert err != "ERR_DUES_OVERDUE"


# --------------------------------------------------- state (5) beats temporal (8)
def _assign_to_cancelled_overlapping_shift(api):
    off_id, off = create_officer(api)
    station, apparatus = create_station_with_apparatus(api, apparatus_type="AMBULANCE")
    m, _ = create_eligible_member(api, off, role_class="EMT", dues=0)
    sh_a = create_published_shift(api, off, station["id"], apparatus["id"], "2026-06-01T06:00:00Z", "2026-06-01T18:00:00Z")
    assign_member(api, off, sh_a["id"], m["id"], current_shift_version(api, off, sh_a["id"]))
    sh_b = create_draft_shift(api, off, station["id"], apparatus["id"], "2026-06-01T12:00:00Z", "2026-06-01T20:00:00Z")
    get_success_data(api.cancel_duty_shift(sh_b["id"], off))  # DRAFT -> CANCELLED
    v_b = current_shift_version(api, off, sh_b["id"])
    return api.create_assignment(sh_b["id"], {"member_id": m["id"], "expected_duty_shift_version": v_b}, off)


def test_state_check_beats_temporal_returns_invalid_state(api):
    """PRD §2.6: "5. **State** — the target resource is in a state from which the
    requested transition is legal, else `ERR_INVALID_STATE`."
    PRD §3.4: "the shift must be in a state that accepts assignments".

    Design: Difficulty/priority_pair_validation_conflict/state_beats_temporal_on_assignment
    """
    validate_error(_assign_to_cancelled_overlapping_shift(api), ApiErrorId.ERR_INVALID_STATE.value)


def test_state_preempts_temporal_not_overlap_error(api):
    """PRD §2.6: "8. **Temporal windowing** — rest-buffer conflicts on
    duty-assignment creation (`ERR_SHIFT_OVERLAP`) and maintenance-window overlaps
    (`ERR_MAINTENANCE_OVERLAP`)."
    PRD §2.6: "so the earliest-numbered failure is the one reported."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_temporal_on_assignment
    """
    err = _error_id(_assign_to_cancelled_overlapping_shift(api))
    assert err == "ERR_INVALID_STATE"
    assert err != "ERR_SHIFT_OVERLAP"


# ------------------------------- assignment requires response-eligible member
def _loa_member_and_published_shift(api):
    off_id, off = create_officer(api)
    station, apparatus = create_station_with_apparatus(api, apparatus_type="AMBULANCE")
    m, _ = create_eligible_member(api, off, role_class="EMT", dues=0)
    get_success_data(api.leave_member(m["id"], CHIEF))  # ACTIVE -> LOA, not eligible
    sh = create_published_shift(api, off, station["id"], apparatus["id"], "2026-08-01T06:00:00Z", "2026-08-01T18:00:00Z")
    return off, m, sh


def test_assignment_rejected_while_member_on_leave(api):
    """PRD §3.4: "the member must be response-eligible, else
    `ERR_MEMBER_NOT_RESPONSE_ELIGIBLE`".
    PRD §3.1: "going on leave makes the member no longer response-eligible".

    Design: Difficulty/cross_entity_state_dependency/assignment_requires_member_response_eligible
    """
    off, m, sh = _loa_member_and_published_shift(api)
    v = current_shift_version(api, off, sh["id"])
    resp = api.create_assignment(sh["id"], {"member_id": m["id"], "expected_duty_shift_version": v}, off)
    validate_error(resp, ApiErrorId.ERR_MEMBER_NOT_RESPONSE_ELIGIBLE.value)


def test_assignment_succeeds_after_member_returns(api):
    """PRD §3.1: "A member returns from leave with `LOA → ACTIVE`."
    PRD §3.4: "A successful assignment starts in `ASSIGNED`, increments the shift's
    `assigned_count`, advances the shift's `version`, and recomputes staffing."

    Design: Difficulty/cross_entity_state_dependency/assignment_requires_member_response_eligible
    """
    off, m, sh = _loa_member_and_published_shift(api)
    get_success_data(api.return_member(m["id"], CHIEF))  # LOA -> ACTIVE
    v = current_shift_version(api, off, sh["id"])
    data = validate_success(
        api.create_assignment(sh["id"], {"member_id": m["id"], "expected_duty_shift_version": v}, off), 201
    )
    assert data["status"] == "ASSIGNED"


# ---------------------------------------------------- rest-buffer overlap
def _member_with_shift_a(api):
    off_id, off = create_officer(api)
    station, apparatus = create_station_with_apparatus(api, apparatus_type="AMBULANCE")
    m, _ = create_eligible_member(api, off, role_class="EMT", dues=0)
    sh_a = create_published_shift(api, off, station["id"], apparatus["id"], "2026-09-01T06:00:00Z", "2026-09-01T18:00:00Z")
    assign_member(api, off, sh_a["id"], m["id"], current_shift_version(api, off, sh_a["id"]))
    return off, m, station, apparatus


def test_assignment_rejected_within_rest_buffer(api):
    """PRD §3.4: "a new assignment is rejected if the member holds any other
    assignment in `ASSIGNED` or `CHECKED_IN` whose shift interval overlaps the new
    shift's interval, or is separated from it by less than 8 hours — at least 8
    hours of separation is required between the two half-open intervals, so
    overlapping, exactly-adjacent, and merely-close shifts are all rejected."

    Design: Difficulty/resource_temporal_overlap/member_shift_rest_buffer_overlap
    """
    off, m, station, apparatus = _member_with_shift_a(api)
    # Shift B starts 4h after A ends (18:00 -> 22:00): inside the 8h rest buffer.
    sh_b = create_published_shift(api, off, station["id"], apparatus["id"], "2026-09-01T22:00:00Z", "2026-09-02T06:00:00Z")
    v = current_shift_version(api, off, sh_b["id"])
    resp = api.create_assignment(sh_b["id"], {"member_id": m["id"], "expected_duty_shift_version": v}, off)
    validate_error(resp, ApiErrorId.ERR_SHIFT_OVERLAP.value)


def test_assignment_rejected_for_exactly_adjacent_shift(api):
    """PRD §3.4: "at least 8 hours of separation is required between the two
    half-open intervals, so overlapping, exactly-adjacent, and merely-close shifts
    are all rejected."

    Design: Difficulty/resource_temporal_overlap/member_shift_rest_buffer_overlap
    """
    off, m, station, apparatus = _member_with_shift_a(api)
    # Shift B starts exactly when A ends (18:00): adjacency is rejected.
    sh_b = create_published_shift(api, off, station["id"], apparatus["id"], "2026-09-01T18:00:00Z", "2026-09-02T06:00:00Z")
    v = current_shift_version(api, off, sh_b["id"])
    resp = api.create_assignment(sh_b["id"], {"member_id": m["id"], "expected_duty_shift_version": v}, off)
    validate_error(resp, ApiErrorId.ERR_SHIFT_OVERLAP.value)


# ----------------------------------------------- corner: terminal-state cancel
def test_cancel_already_cancelled_shift_rejected(api):
    """PRD §3.4: "An Officer may cancel a shift from `DRAFT`, `PUBLISHED`, or
    `SUSPENDED`, reaching `CANCELLED` (terminal); cancelling a published or
    suspended shift also cancels its assignments still in `ASSIGNED` or
    `CHECKED_IN`."

    Design: Corner/state_machines/corner_cancel_shift_from_terminal_invalid
    """
    off_id, off = create_officer(api)
    station, apparatus = create_station_with_apparatus(api)
    sh = create_draft_shift(api, off, station["id"], apparatus["id"], "2026-06-01T06:00:00Z", "2026-06-01T18:00:00Z")
    get_success_data(api.cancel_duty_shift(sh["id"], off))
    validate_error(api.cancel_duty_shift(sh["id"], off), ApiErrorId.ERR_INVALID_STATE.value)


# ----------------------------------------------- corner: apparatus not at station
def test_create_shift_apparatus_not_at_station_rejected(api):
    """PRD §3.4: "An Officer drafts a duty shift naming its `station_id` and
    `apparatus_id`, where the apparatus must belong to the station or the create is
    rejected with `ERR_APPARATUS_NOT_AT_STATION`."

    Design: Corner/validations/corner_apparatus_not_at_station_on_shift
    """
    off_id, off = create_officer(api)
    st_a, ap = create_station_with_apparatus(api)
    st_b = get_success_data(api.create_station({"name": "Station B"}, CHIEF))
    payload = create_duty_shift_payload(station_id=st_b["id"], apparatus_id=ap["id"])
    validate_error(api.create_duty_shift(payload, off), ApiErrorId.ERR_APPARATUS_NOT_AT_STATION.value)


# ----------------------------------------------- corner: shift full
def test_assignment_rejected_when_shift_full(api):
    """PRD §3.4: "The **capacity** rule rejects an assignment that would raise the
    assigned count above `max_crew`; equivalently, an assignment is admitted only
    while the current assigned count is below the ceiling."

    Design: Corner/validations/corner_shift_full_on_assignment
    """
    off_id, off = create_officer(api)
    station, apparatus = create_station_with_apparatus(api, apparatus_type="AMBULANCE")
    m1, _ = create_eligible_member(api, off, role_class="EMT", dues=0)
    m2, _ = create_eligible_member(api, off, role_class="EMT", dues=0)
    sh = create_published_shift(api, off, station["id"], apparatus["id"], "2026-06-05T06:00:00Z", "2026-06-05T18:00:00Z", max_crew=1)
    assign_member(api, off, sh["id"], m1["id"], current_shift_version(api, off, sh["id"]))
    v = current_shift_version(api, off, sh["id"])
    resp = api.create_assignment(sh["id"], {"member_id": m2["id"], "expected_duty_shift_version": v}, off)
    validate_error(resp, ApiErrorId.ERR_SHIFT_FULL.value)


# ----------------------------------------------- corner: dues overdue isolated
def test_assignment_rejected_for_member_owing_dues(api):
    """PRD §3.4: "The **fiscal** rule rejects any member whose `dues_balance_cents`
    is greater than zero."

    Design: Corner/validations/corner_dues_overdue_isolated
    """
    off_id, off = create_officer(api)
    station, apparatus = create_station_with_apparatus(api, apparatus_type="AMBULANCE")
    m, _ = create_eligible_member(api, off, role_class="EMT", dues=2500)
    sh = create_published_shift(api, off, station["id"], apparatus["id"], "2026-06-06T06:00:00Z", "2026-06-06T18:00:00Z")
    v = current_shift_version(api, off, sh["id"])
    resp = api.create_assignment(sh["id"], {"member_id": m["id"], "expected_duty_shift_version": v}, off)
    validate_error(resp, ApiErrorId.ERR_DUES_OVERDUE.value)


# ----------------------------------------------- corner: RBAC role gate
def test_member_role_cannot_create_duty_shift(api):
    """PRD §2.1: "When the headers are well-formed but the named role is not
    permitted to perform the requested operation — or an ownership check fails —
    the request is rejected with `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/rbac/corner_member_cannot_create_duty_shift
    """
    m = create_member(api, role_class="FIREFIGHTER")
    station, apparatus = create_station_with_apparatus(api)
    payload = create_duty_shift_payload(station_id=station["id"], apparatus_id=apparatus["id"])
    validate_error(api.create_duty_shift(payload, make_member_headers(m["id"])), ApiErrorId.ERR_FORBIDDEN.value)


# ----------------------------------------------- corner: check-in ownership
def test_member_cannot_check_in_another_members_assignment(api):
    """PRD §2.1: "A rank-and-file member may read records and may check in to their
    **own** duty assignment; for the check-in operation `X-User-ID` must equal the
    assignment's `member_id`, otherwise the attempt is rejected with
    `ERR_FORBIDDEN`."

    Design: Corner/rbac/corner_member_checkin_ownership_denied
    """
    off_id, off = create_officer(api)
    station, apparatus = create_station_with_apparatus(api, apparatus_type="AMBULANCE")
    m1, _ = create_eligible_member(api, off, role_class="EMT", dues=0)
    m2 = create_member(api, role_class="EMT")
    sh = create_published_shift(api, off, station["id"], apparatus["id"], "2026-06-08T06:00:00Z", "2026-06-08T18:00:00Z")
    a = assign_member(api, off, sh["id"], m1["id"], current_shift_version(api, off, sh["id"]))
    resp = api.check_in_assignment(a["id"], make_member_headers(m2["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


# ----------------------------------------------- corner: OCC stale shift version
def test_stale_shift_version_rejected_then_retry_succeeds(api):
    """PRD §2.7: "Creating a duty assignment against a shift requires
    `expected_duty_shift_version` matching that `DutyShift`'s current `version`. If
    another writer has already added an assignment ... the shift's version has
    advanced, the current writer's view of the roster is stale, and the create is
    rejected with `ERR_STALE_VERSION`."

    Design: Corner/cross_cutting_complexity_layers/corner_occ_duty_assignment_stale_shift_version
    """
    off_id, off = create_officer(api)
    station, apparatus = create_station_with_apparatus(api, apparatus_type="AMBULANCE")
    m1, _ = create_eligible_member(api, off, role_class="EMT", dues=0)
    m2, _ = create_eligible_member(api, off, role_class="EMT", dues=0)
    sh = create_published_shift(api, off, station["id"], apparatus["id"], "2026-06-09T06:00:00Z", "2026-06-09T18:00:00Z", max_crew=3)
    stale_version = current_shift_version(api, off, sh["id"])
    assign_member(api, off, sh["id"], m1["id"], stale_version)  # advances the shift version
    current_version = current_shift_version(api, off, sh["id"])
    assert current_version != stale_version
    stale_resp = api.create_assignment(
        sh["id"], {"member_id": m2["id"], "expected_duty_shift_version": stale_version}, off
    )
    validate_error(stale_resp, ApiErrorId.ERR_STALE_VERSION.value)
    ok = validate_success(
        api.create_assignment(sh["id"], {"member_id": m2["id"], "expected_duty_shift_version": current_version}, off), 201
    )
    assert ok["status"] == "ASSIGNED"


# ----------------------------------------------- corner: version increments
def test_publish_increments_shift_version(api):
    """PRD §2.4: "The `version` is an integer that begins at 1 and increments by
    one on every mutation of the resource; it is the value clients echo back for
    optimistic concurrency control (§2.7)."

    Design: Corner/cross_cutting_complexity_layers/corner_version_increments_on_mutation
    """
    off_id, off = create_officer(api)
    station, apparatus = create_station_with_apparatus(api)
    sh = create_draft_shift(api, off, station["id"], apparatus["id"], "2026-06-10T06:00:00Z", "2026-06-10T18:00:00Z")
    assert sh["version"] == 1
    published = validate_success(api.publish_duty_shift(sh["id"], off), 200)
    assert published["version"] == 2
    assert published["status"] == "PUBLISHED"
