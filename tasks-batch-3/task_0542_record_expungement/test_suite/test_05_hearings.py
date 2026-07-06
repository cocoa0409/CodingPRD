"""Hearing scheduling: jurisdiction, courtroom-buffer / judge-half-open temporal rules,
validation precedence, and optimistic concurrency on reschedule."""
from test_helpers import fixtures, validate_success, validate_error, ApiErrorId

CLERK = fixtures.CLERK


def _schedule(api, petition_id, courtroom_id, judge_id, start, end, version):
    return api.create_hearing(petition_id, {
        "courtroom_id": courtroom_id, "judge_id": judge_id,
        "scheduled_start": start, "scheduled_end": end,
        "expected_petition_version": version,
    }, CLERK)


# ---- hearing_referential_beats_temporal (Difficulty) ----------------------
def test_jurisdiction_mismatch_beats_courtroom_conflict(api):
    """PRD §2.10: "8. **Reference integrity** — cross-entity ownership and
    jurisdiction constraints (see Sections 3.3 and 3.7), else `ERR_RECORD_NOT_OWNED`
    or `ERR_JURISDICTION_MISMATCH` (both 409)."
    PRD §2.10: "9. **Temporal availability** — courtroom and judge scheduling
    conflicts and objection-window checks (Sections 3.6 and 3.7), else
    `ERR_COURTROOM_UNAVAILABLE`, `ERR_JUDGE_UNAVAILABLE`, `ERR_OBJECTION_WINDOW_CLOSED`,
    or `ERR_OBJECTION_WINDOW_OPEN` (all 409)."
    PRD §2.10: "A rule earlier in this list, when it fails, masks any later rule that
    would also have failed."

    Design: Difficulty/priority_pair_validation_conflict/hearing_referential_beats_temporal
    """
    # Petition Q (CA-02) occupies courtroom X (CA-02) at 09:00-10:00.
    ctx_q = fixtures.setup_notifications_cleared_petition(api, jurisdiction="CA-02")
    courtroom_x = fixtures.create_courtroom(api, name="Room X", jurisdiction_code="CA-02")
    judge_q = fixtures.create_judge(api, name="Judge Q", jurisdiction_code="CA-02")
    validate_success(_schedule(api, ctx_q["petition"]["id"], courtroom_x["id"], judge_q["id"],
                               "2026-06-02T09:00:00Z", "2026-06-02T10:00:00Z",
                               fixtures.petition_version(api, ctx_q["petition"]["id"])),
                     expected_status=201)
    # Petition P (CA-01) tries to book the CA-02 courtroom X at an overlapping time:
    # jurisdiction mismatch (pri 8) must mask the courtroom conflict (pri 9).
    ctx_p = fixtures.setup_filed_petition(api, jurisdiction="CA-01")
    judge_p = fixtures.create_judge(api, name="Judge P", jurisdiction_code="CA-01")
    resp = _schedule(api, ctx_p["petition"]["id"], courtroom_x["id"], judge_p["id"],
                     "2026-06-02T09:30:00Z", "2026-06-02T10:30:00Z",
                     fixtures.petition_version(api, ctx_p["petition"]["id"]))
    validate_error(resp, ApiErrorId.ERR_JURISDICTION_MISMATCH.value)


def test_courtroom_jurisdiction_must_match_petition(api):
    """PRD §3.7: "the chosen courtroom's `jurisdiction_code` and the chosen judge's
    `jurisdiction_code` must both equal the petition's `jurisdiction_code`, else the
    request is rejected with `ERR_JURISDICTION_MISMATCH` (409)."

    Design: Difficulty/priority_pair_validation_conflict/hearing_referential_beats_temporal
    """
    ctx = fixtures.setup_notifications_cleared_petition(api, jurisdiction="CA-01")
    wrong_room = fixtures.create_courtroom(api, name="Room Z", jurisdiction_code="CA-02")
    judge = fixtures.create_judge(api, name="Judge C", jurisdiction_code="CA-01")
    resp = _schedule(api, ctx["petition"]["id"], wrong_room["id"], judge["id"],
                     "2026-06-02T09:00:00Z", "2026-06-02T10:00:00Z",
                     fixtures.petition_version(api, ctx["petition"]["id"]))
    validate_error(resp, ApiErrorId.ERR_JURISDICTION_MISMATCH.value)


# ---- schedule_requires_notifications_cleared (Difficulty) -----------------
def test_schedule_rejected_when_notifications_pending(api):
    """PRD §3.7: "If any notification of the petition is not yet `CLEARED`,
    scheduling is rejected with `ERR_NOTIFICATIONS_NOT_CLEARED` (409)."

    Design: Difficulty/cross_entity_state_dependency/schedule_requires_notifications_cleared
    """
    ctx = fixtures.setup_filed_petition(api, jurisdiction="CA-01")  # 3 PENDING notifications
    room = fixtures.create_courtroom(api, name="Room 3", jurisdiction_code="CA-01")
    judge = fixtures.create_judge(api, name="Judge 3", jurisdiction_code="CA-01")
    resp = _schedule(api, ctx["petition"]["id"], room["id"], judge["id"],
                     "2026-06-02T09:00:00Z", "2026-06-02T10:00:00Z",
                     fixtures.petition_version(api, ctx["petition"]["id"]))
    validate_error(resp, ApiErrorId.ERR_NOTIFICATIONS_NOT_CLEARED.value)


def test_schedule_rejected_when_notifications_only_served(api):
    """PRD §3.7: "If any notification of the petition is not yet `CLEARED`,
    scheduling is rejected with `ERR_NOTIFICATIONS_NOT_CLEARED` (409)."

    Design: Difficulty/cross_entity_state_dependency/schedule_requires_notifications_cleared
    """
    ctx = fixtures.setup_filed_petition(api, jurisdiction="CA-01")
    for n in ctx["notifications"]:
        validate_success(api.transition_agency_notification(n["id"], {"to_status": "SERVED"}, CLERK))
    room = fixtures.create_courtroom(api, name="Room 3", jurisdiction_code="CA-01")
    judge = fixtures.create_judge(api, name="Judge 3", jurisdiction_code="CA-01")
    resp = _schedule(api, ctx["petition"]["id"], room["id"], judge["id"],
                     "2026-06-02T09:00:00Z", "2026-06-02T10:00:00Z",
                     fixtures.petition_version(api, ctx["petition"]["id"]))
    validate_error(resp, ApiErrorId.ERR_NOTIFICATIONS_NOT_CLEARED.value)


# ---- courtroom_buffer_conflict (Difficulty) -------------------------------
def test_courtroom_back_to_back_boundary_conflicts(api):
    """PRD §3.7: "two hearings conflict if their time ranges overlap or merely touch
    at a boundary — a hearing beginning exactly when another ends still conflicts,
    reflecting a changeover buffer — and a conflict is rejected with
    `ERR_COURTROOM_UNAVAILABLE` (409)."

    Design: Difficulty/resource_temporal_overlap/courtroom_buffer_conflict
    """
    sc = fixtures.setup_occupied_courtroom_scenario(api)  # Room X busy 09:00-10:00, judge J1
    # New hearing in the SAME room begins exactly when the other ends (10:00), a
    # different judge (J2) so only the courtroom boundary can conflict.
    resp = _schedule(api, sc["petition_b"]["id"], sc["courtroom_x"]["id"], sc["judge_2"]["id"],
                     "2026-06-02T10:00:00Z", "2026-06-02T11:00:00Z",
                     fixtures.petition_version(api, sc["petition_b"]["id"]))
    validate_error(resp, ApiErrorId.ERR_COURTROOM_UNAVAILABLE.value)


def test_courtroom_overlap_conflicts(api):
    """PRD §3.7: "two hearings conflict if their time ranges overlap or merely touch
    at a boundary — a hearing beginning exactly when another ends still conflicts,
    reflecting a changeover buffer — and a conflict is rejected with
    `ERR_COURTROOM_UNAVAILABLE` (409)."

    Design: Difficulty/resource_temporal_overlap/courtroom_buffer_conflict
    """
    sc = fixtures.setup_occupied_courtroom_scenario(api)  # Room X busy 09:00-10:00
    resp = _schedule(api, sc["petition_b"]["id"], sc["courtroom_x"]["id"], sc["judge_2"]["id"],
                     "2026-06-02T09:30:00Z", "2026-06-02T10:30:00Z",
                     fixtures.petition_version(api, sc["petition_b"]["id"]))
    validate_error(resp, ApiErrorId.ERR_COURTROOM_UNAVAILABLE.value)


# ---- judge_halfopen_adjacent_ok (Difficulty) ------------------------------
def test_judge_back_to_back_boundary_is_accepted(api):
    """PRD §3.7: "each hearing occupies the interval from its `scheduled_start`
    (inclusive) up to but not including its `scheduled_end`, so two hearings conflict
    only when these half-open intervals genuinely overlap; back-to-back hearings that
    merely share a boundary instant do not conflict."
    PRD §3.7: "Once a petition is `FILED` and every one of its agency notifications is
    `CLEARED`, a `Clerk` schedules the hearing, which moves the petition from `FILED`
    to `HEARING_SET` and creates a `Hearing` in the `SCHEDULED` state."

    Design: Difficulty/resource_temporal_overlap/judge_halfopen_adjacent_ok
    """
    sc = fixtures.setup_occupied_courtroom_scenario(api)  # judge J1 busy 09:00-10:00 in Room X
    # Same judge J1, back-to-back at 10:00, but in a DIFFERENT (free) room Y.
    hearing = validate_success(
        _schedule(api, sc["petition_b"]["id"], sc["courtroom_y"]["id"], sc["judge_1"]["id"],
                  "2026-06-02T10:00:00Z", "2026-06-02T11:00:00Z",
                  fixtures.petition_version(api, sc["petition_b"]["id"])),
        expected_status=201)
    assert hearing["status"] == "SCHEDULED"
    petition = validate_success(api.get_petition(sc["petition_b"]["id"], CLERK))
    assert petition["status"] == "HEARING_SET"


def test_judge_genuine_overlap_conflicts(api):
    """PRD §3.7: "each hearing occupies the interval from its `scheduled_start`
    (inclusive) up to but not including its `scheduled_end`, so two hearings conflict
    only when these half-open intervals genuinely overlap; back-to-back hearings that
    merely share a boundary instant do not conflict. A judge conflict is rejected
    with `ERR_JUDGE_UNAVAILABLE` (409)."

    Design: Difficulty/resource_temporal_overlap/judge_halfopen_adjacent_ok
    """
    sc = fixtures.setup_occupied_courtroom_scenario(api)  # judge J1 busy 09:00-10:00
    # Same judge J1, genuine overlap (09:30-10:30), in a free room Y so only the judge conflicts.
    resp = _schedule(api, sc["petition_b"]["id"], sc["courtroom_y"]["id"], sc["judge_1"]["id"],
                     "2026-06-02T09:30:00Z", "2026-06-02T10:30:00Z",
                     fixtures.petition_version(api, sc["petition_b"]["id"]))
    validate_error(resp, ApiErrorId.ERR_JUDGE_UNAVAILABLE.value)


# ---- Corner: optimistic concurrency ---------------------------------------
def test_stale_petition_version_on_reschedule_rejected(api):
    """PRD §3.7: "Because a reschedule advances the petition's `version`, a second
    scheduling request that still carries an `expected_petition_version` the server
    has already moved past is a stale-view write and fails the version check with
    `ERR_STALE_VERSION` (412) rather than silently superseding a hearing the client
    never saw."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_petition_version_on_reschedule
    """
    ctx = fixtures.setup_notifications_cleared_petition(api, jurisdiction="CA-01")
    room = fixtures.create_courtroom(api, name="Room O", jurisdiction_code="CA-01")
    judge = fixtures.create_judge(api, name="Judge O", jurisdiction_code="CA-01")
    pet_id = ctx["petition"]["id"]
    v0 = fixtures.petition_version(api, pet_id)
    # First schedule with v0 succeeds and advances the petition version to v0+1.
    validate_success(_schedule(api, pet_id, room["id"], judge["id"],
                               "2026-06-02T09:00:00Z", "2026-06-02T10:00:00Z", v0),
                     expected_status=201)
    # A second scheduling still carrying the now-stale v0 is rejected.
    resp = _schedule(api, pet_id, room["id"], judge["id"],
                     "2026-06-03T09:00:00Z", "2026-06-03T10:00:00Z", v0)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)
