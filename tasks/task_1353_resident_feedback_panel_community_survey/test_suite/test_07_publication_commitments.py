"""Publication pipeline (k-anonymity gate, snapshot-finalized guard, second
publish), follow-up commitment lifecycle (due-date pair, renegotiate cycle,
retract cascade, department scoping, terminal states)."""
import pytest

from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS,
    create_cell, create_panelist, create_locked_instrument, create_fielding_wave,
    dispatch_invitation, submit_response, accept_response, set_clock,
    create_snapshot, create_finalized_snapshot, create_publication_payload,
    create_commitment, make_analyst_headers, make_privacy_headers,
    make_liaison_headers, assert_timestamp_eq, setup_closed_wave_with_accepted,
)

PM = TEST_USERS["panel_manager"]
DA = TEST_USERS["data_analyst"]
PO = TEST_USERS["privacy_officer"]

from test_helpers import api_client as _api


def _enroll(pid):
    return validate_success(_api.enroll_panelist(pid, PM), 200)


def _closed_weighted_wave(num_respondents=1, cell_target=5):
    """Cell + N enrolled panelists (one cell), locked instrument, wave fielded,
    all invited/answered/ACCEPTED, closed, POST_STRAT snapshot created and
    FINALIZED by analyst-1. Returns (cell, wave, snapshot, responses).

    Delegates to the shared fixture, which staggers sends in batches of three
    eight days apart to respect the per-cell contact cap of PRD §3.5."""
    s = setup_closed_wave_with_accepted(num_respondents=num_respondents,
                                       cell_target=cell_target)
    snap = create_finalized_snapshot(s["wave"]["id"], finalizer_user_id="analyst-1")
    return s["cell"], s["wave"], snap, s["responses"]


def api_close(wid):
    return _api.close_wave(wid, PM)


def _draft_publication(wave_id, snap_id, k_threshold=1, title="Results"):
    return validate_success(api_create_pub(wave_id, snap_id, k_threshold, title), 201)


def api_create_pub(wave_id, snap_id, k, title):
    return _api.create_publication(
        create_publication_payload(wave_id, snap_id, k_threshold=k, title=title), DA)


def test_publication_publish_requires_snapshot_finalized(api):
    """PRD §3.7: "Publishing is the `PrivacyOfficer`'s call and enforces four checks
    in this order: first, the pinned snapshot must be `FINALIZED`
    (`ERR_SNAPSHOT_NOT_FINALIZED`); ..." and "Finalization commits a snapshot. ...
    On success the snapshot moves `PROVISIONAL` → `FINALIZED`,
    `finalized_by_user_id` records the caller's `X-User-ID`, and the wave moves
    `CLOSED` → `WEIGHTED`."

    Design: Difficulty/cross_entity_state_dependency/publication_publish_requires_snapshot_finalized
    """
    cell = create_cell(target_size=5)
    p1 = _enroll(create_panelist()["id"])
    instr = create_locked_instrument()
    wave = create_fielding_wave(instr["id"])
    inv = dispatch_invitation(wave["id"], p1["id"])
    r1 = submit_response(inv["id"])
    accept_response(r1["id"])
    set_clock("2026-08-11T00:00:00Z")
    wave = validate_success(api_close(wave["id"]), 200)

    snap = create_snapshot(wave["id"])  # PROVISIONAL
    pub = _draft_publication(wave["id"], snap["id"], k_threshold=1)

    err = validate_error(api.publish_publication(pub["id"], make_privacy_headers("privacy-1")),
                         ApiErrorId.ERR_SNAPSHOT_NOT_FINALIZED)
    assert err["error_id"] == "ERR_SNAPSHOT_NOT_FINALIZED"

    finalized = validate_success(api.finalize_weight_snapshot(
        snap["id"], make_analyst_headers("analyst-1")), 200)
    assert finalized["finalized_by_user_id"] == "analyst-1"

    published = validate_success(api.publish_publication(
        pub["id"], make_privacy_headers("privacy-1")), 200)
    assert published["status"] == "PUBLISHED"
    wave_after = validate_success(api.get_wave(wave["id"], PM), 200)
    assert wave_after["status"] == "PUBLISHED"
    snap_after = validate_success(api.get_weight_snapshot(snap["id"], DA), 200)
    assert snap_after["finalized_by_user_id"] == "analyst-1"


def test_publication_publish_blocked_while_wave_only_closed(api):
    """PRD §3.7: "Publishing is the `PrivacyOfficer`'s call and enforces four checks
    in this order: first, the pinned snapshot must be `FINALIZED`
    (`ERR_SNAPSHOT_NOT_FINALIZED`); second, the wave must be `WEIGHTED`
    (`ERR_WAVE_NOT_WEIGHTED`); ..."

    Design: Difficulty/cross_entity_state_dependency/publication_publish_requires_snapshot_finalized
    """
    cell = create_cell(target_size=5)
    p1 = _enroll(create_panelist()["id"])
    instr = create_locked_instrument()
    wave = create_fielding_wave(instr["id"])
    inv = dispatch_invitation(wave["id"], p1["id"])
    r1 = submit_response(inv["id"])
    accept_response(r1["id"])
    set_clock("2026-08-11T00:00:00Z")
    wave = validate_success(api_close(wave["id"]), 200)
    assert wave["status"] == "CLOSED"

    snap = create_snapshot(wave["id"])
    pub = _draft_publication(wave["id"], snap["id"], k_threshold=1)

    # Snapshot PROVISIONAL -> first check fires.
    err = validate_error(api.publish_publication(pub["id"], make_privacy_headers("privacy-1")),
                         ApiErrorId.ERR_SNAPSHOT_NOT_FINALIZED)
    assert err["error_id"] == "ERR_SNAPSHOT_NOT_FINALIZED"
    pub_after = validate_success(api.get_publication(pub["id"], PO), 200)
    assert pub_after["status"] == "DRAFT"


def test_k_anonymity_exactly_at_threshold_publishes(api):
    """PRD §3.7: "the k-anonymity gate — no breakdown cell may have at least one but
    fewer than `k_threshold` respondents, while a cell with exactly `k_threshold`
    respondents passes and cells with zero respondents are absent rather than
    violations (`ERR_K_ANONYMITY_VIOLATION`)."

    Design: Difficulty/boundary_precision_check/k_anonymity_exactly_at_threshold_publishes
    """
    # --- W1: exactly 5 ACCEPTED respondents in the cell; k_threshold 5 -> passes.
    cell = create_cell(target_size=10)
    panelists = [_enroll(create_panelist()["id"]) for _ in range(5)]
    instr = create_locked_instrument()
    w1 = create_fielding_wave(instr["id"], closes_at="2026-08-20T00:00:00Z")
    # Stagger sends under the 3-per-7d cell cap.
    for p in panelists[:3]:
        inv = dispatch_invitation(w1["id"], p["id"])
        r = submit_response(inv["id"])
        accept_response(r["id"])
    set_clock("2026-08-11T00:00:00Z")
    for p in panelists[3:]:
        inv = dispatch_invitation(w1["id"], p["id"])
        r = submit_response(inv["id"])
        accept_response(r["id"])
    set_clock("2026-08-21T00:00:00Z")
    w1 = validate_success(api_close(w1["id"]), 200)
    snap1 = create_finalized_snapshot(w1["id"], finalizer_user_id="analyst-1")
    pub1 = _draft_publication(w1["id"], snap1["id"], k_threshold=5, title="W1 Results")

    # --- W2: only 4 of the same 5 respond; the 4-respondent cell violates k=5.
    w2 = create_fielding_wave(instr["id"], opens_at="2026-08-22T00:00:00Z",
                              closes_at="2026-09-05T00:00:00Z",
                              fielding_now="2026-08-23T00:00:00Z")
    w2_responses = []
    for p in panelists[:3]:
        inv = dispatch_invitation(w2["id"], p["id"])
        r = submit_response(inv["id"])
        accept_response(r["id"])
        w2_responses.append(r)
    set_clock("2026-08-31T00:00:00Z")
    for p in panelists[3:]:
        inv = dispatch_invitation(w2["id"], p["id"])
        w2_responses.append((p, inv))
    # P4 responds; P5's invitation stays SENT and will expire at close.
    r4 = submit_response(w2_responses[3][1]["id"])
    accept_response(r4["id"])
    set_clock("2026-09-06T00:00:00Z")
    w2 = validate_success(api_close(w2["id"]), 200)
    snap2 = create_finalized_snapshot(w2["id"], finalizer_user_id="analyst-1")
    pub2 = _draft_publication(w2["id"], snap2["id"], k_threshold=5, title="W2 Results")

    # n == k_threshold (5): publishes.
    pub1_after = validate_success(api.publish_publication(
        pub1["id"], make_privacy_headers("privacy-1")), 200)
    assert pub1_after["status"] == "PUBLISHED"
    w1_after = validate_success(api.get_wave(w1["id"], PM), 200)
    assert w1_after["status"] == "PUBLISHED"

    # n == 4 < k_threshold (5): rejected; the draft is untouched.
    err = validate_error(api.publish_publication(
        pub2["id"], make_privacy_headers("privacy-1")),
        ApiErrorId.ERR_K_ANONYMITY_VIOLATION)
    assert err["error_id"] == "ERR_K_ANONYMITY_VIOLATION"
    pub2_after = validate_success(api.get_publication(pub2["id"], PO), 200)
    assert pub2_after["status"] == "DRAFT"
    assert pub2_after["breakdown_cells"][0]["n_respondents"] == 4
    assert pub2_after["breakdown_cells"][0]["suppressed"] is True


def test_k_anonymity_below_threshold_marks_suppressed(api):
    """PRD §3.7: "At creation the publication computes `breakdown_cells`: the wave's
    `ACCEPTED` responses are grouped by home cell, and each entry records the
    `cell_id`, the `n_respondents` count, the `weighted_share` mirroring the pinned
    snapshot's per-cell share, and a `suppressed` flag that is true when the cell
    has at least one but fewer than `k_threshold` respondents."

    Design: Difficulty/boundary_precision_check/k_anonymity_exactly_at_threshold_publishes
    """
    # 4 respondents against the default k_threshold of 5: suppressed at creation.
    cell, wave, snap, _ = _closed_weighted_wave(num_respondents=4, cell_target=10)
    pub = _draft_publication(wave["id"], snap["id"], k_threshold=5)
    assert pub["breakdown_cells"][0]["cell_id"] == cell["id"]
    assert pub["breakdown_cells"][0]["n_respondents"] == 4
    assert pub["breakdown_cells"][0]["suppressed"] is True

    err = validate_error(api.publish_publication(
        pub["id"], make_privacy_headers("privacy-1")),
        ApiErrorId.ERR_K_ANONYMITY_VIOLATION)
    assert err["error_id"] == "ERR_K_ANONYMITY_VIOLATION"


def test_commitment_on_draft_publication_returns_409(api):
    """PRD §3.8: "A `DepartmentLiaison` creates one against a `PUBLISHED`
    publication — any other publication status fails with
    `ERR_PUBLICATION_NOT_PUBLISHED` ..."

    Design: Corner/validations/corner_commitment_on_draft_publication_returns_409
    """
    cell = create_cell(target_size=5)
    p1 = _enroll(create_panelist()["id"])
    instr = create_locked_instrument()
    wave = create_fielding_wave(instr["id"])
    inv = dispatch_invitation(wave["id"], p1["id"])
    r1 = submit_response(inv["id"])
    accept_response(r1["id"])
    set_clock("2026-08-11T00:00:00Z")
    wave = validate_success(api_close(wave["id"]), 200)
    snap = create_snapshot(wave["id"])  # PROVISIONAL; publication stays DRAFT
    pub = _draft_publication(wave["id"], snap["id"], k_threshold=1,
                             title="Draft Results")

    err = validate_error(api.create_commitment(
        {"publication_id": pub["id"], "department_name": "DEPT_TRANSPORT",
         "summary": "Act on findings", "due_at": "2026-09-01T00:00:00Z"},
        make_liaison_headers("DEPT_TRANSPORT")),
        ApiErrorId.ERR_PUBLICATION_NOT_PUBLISHED)
    assert err["error_id"] == "ERR_PUBLICATION_NOT_PUBLISHED"


def test_commitment_due_date_temporal_pair(api):
    """PRD §3.8: "Fulfilling moves `IN_PROGRESS` → `FULFILLED` and is on time only
    when the current time is at or before `due_at`; a late fulfill is rejected with
    `ERR_COMMITMENT_OVERDUE`. Breach marking is the `PanelManager`'s escalation:
    from `COMMITTED` or `IN_PROGRESS`, when the current time is strictly past
    `due_at`, the commitment moves to `BREACHED` and `breached_at` is stamped with
    the current time; marking a commitment not yet overdue fails with
    `ERR_COMMITMENT_NOT_OVERDUE`."

    Design: Corner/validations/corner_commitment_due_date_temporal_pair
    """
    cell, wave, snap, _ = _closed_weighted_wave(num_respondents=1)
    pub = _draft_publication(wave["id"], snap["id"], k_threshold=1)
    validate_success(api.publish_publication(pub["id"], make_privacy_headers("privacy-1")), 200)

    cm1 = create_commitment(pub["id"], due_at="2026-08-15T00:00:00Z")
    cm2 = create_commitment(pub["id"], summary="Future item",
                            due_at="2026-09-01T00:00:00Z")
    validate_success(api.start_commitment(cm1["id"], make_liaison_headers("DEPT_TRANSPORT")), 200)
    set_clock("2026-08-16T00:00:00Z")

    err1 = validate_error(api.fulfill_commitment(
        cm1["id"], make_liaison_headers("DEPT_TRANSPORT")),
        ApiErrorId.ERR_COMMITMENT_OVERDUE)
    assert err1["error_id"] == "ERR_COMMITMENT_OVERDUE"
    err2 = validate_error(api.mark_breached_commitment(cm2["id"], PM),
                          ApiErrorId.ERR_COMMITMENT_NOT_OVERDUE)
    assert err2["error_id"] == "ERR_COMMITMENT_NOT_OVERDUE"
    cm1_after = validate_success(api.get_commitment(cm1["id"], PM), 200)
    assert cm1_after["status"] == "IN_PROGRESS"
    cm2_after = validate_success(api.get_commitment(cm2["id"], PM), 200)
    assert cm2_after["status"] == "COMMITTED"


def test_commitment_renegotiate_cycle(api):
    """PRD §3.8: "Renegotiation moves `BREACHED` → `COMMITTED` with a `new_due_at`
    that must lie strictly in the future — one at or before the current time fails
    with `ERR_COMMITMENT_OVERDUE` — and on success `due_at` becomes `new_due_at`
    and `breached_at` clears to null."

    Design: Corner/state_machines/corner_commitment_renegotiate_cycle
    """
    cell, wave, snap, _ = _closed_weighted_wave(num_respondents=1)
    pub = _draft_publication(wave["id"], snap["id"], k_threshold=1)
    validate_success(api.publish_publication(pub["id"], make_privacy_headers("privacy-1")), 200)

    cm = create_commitment(pub["id"], due_at="2026-08-15T00:00:00Z")
    validate_success(api.start_commitment(cm["id"], make_liaison_headers("DEPT_TRANSPORT")), 200)
    set_clock("2026-08-16T00:00:00Z")

    breached = validate_success(api.mark_breached_commitment(cm["id"], PM), 200)
    assert breached["status"] == "BREACHED"
    assert_timestamp_eq(breached["breached_at"], "2026-08-16T00:00:00Z")

    renegotiated = validate_success(api.renegotiate_commitment(
        cm["id"], {"new_due_at": "2026-09-01T00:00:00Z"},
        make_liaison_headers("DEPT_TRANSPORT")), 200)
    assert renegotiated["status"] == "COMMITTED"
    assert_timestamp_eq(renegotiated["due_at"], "2026-09-01T00:00:00Z")
    assert renegotiated["breached_at"] is None


def test_retract_suspends_open_commitments_conditional(api):
    """PRD §3.7: "Retraction moves `PUBLISHED` → `RETRACTED` and cascades
    conditionally: the publication's commitments in `COMMITTED` or `IN_PROGRESS`
    move to `SUSPENDED`, while `FULFILLED` and `BREACHED` commitments are left
    unchanged."

    Design: Corner/state_machines/corner_retract_suspends_open_commitments_conditional
    """
    cell, wave, snap, _ = _closed_weighted_wave(num_respondents=1)
    pub = _draft_publication(wave["id"], snap["id"], k_threshold=1)
    validate_success(api.publish_publication(pub["id"], make_privacy_headers("privacy-1")), 200)

    cm1 = create_commitment(pub["id"], summary="Fix crosswalks",
                            due_at="2026-08-20T00:00:00Z")
    cm2 = create_commitment(pub["id"], summary="Repaint lanes",
                            due_at="2026-08-20T00:00:00Z")
    cm3 = create_commitment(pub["id"], department_name="DEPT_PARKS",
                            summary="Trim trees", due_at="2026-08-20T00:00:00Z")
    validate_success(api.start_commitment(cm1["id"], make_liaison_headers("DEPT_TRANSPORT")), 200)
    validate_success(api.fulfill_commitment(cm1["id"], make_liaison_headers("DEPT_TRANSPORT")), 200)
    validate_success(api.start_commitment(cm2["id"], make_liaison_headers("DEPT_TRANSPORT")), 200)

    retracted = validate_success(api.retract_publication(
        pub["id"], make_privacy_headers("privacy-1")), 200)
    assert retracted["status"] == "RETRACTED"
    cm1_after = validate_success(api.get_commitment(cm1["id"], PM), 200)
    assert cm1_after["status"] == "FULFILLED"
    cm2_after = validate_success(api.get_commitment(cm2["id"], PM), 200)
    assert cm2_after["status"] == "SUSPENDED"
    cm3_after = validate_success(api.get_commitment(cm3["id"], PM), 200)
    assert cm3_after["status"] == "SUSPENDED"


def test_second_publish_same_snapshot_returns_409(api):
    """PRD §3.7: "Publishing is the `PrivacyOfficer`'s call and enforces four checks
    in this order: first, the pinned snapshot must be `FINALIZED`
    (`ERR_SNAPSHOT_NOT_FINALIZED`); second, the wave must be `WEIGHTED`
    (`ERR_WAVE_NOT_WEIGHTED`); ..." and "A successful publish moves the publication
    `DRAFT` → `PUBLISHED` and the wave `WEIGHTED` → `PUBLISHED`."

    Design: Corner/errors/corner_second_publish_same_snapshot_returns_409
    """
    cell, wave, snap, _ = _closed_weighted_wave(num_respondents=1)
    pub_a = _draft_publication(wave["id"], snap["id"], k_threshold=1, title="Pub A")
    pub_b = _draft_publication(wave["id"], snap["id"], k_threshold=1, title="Pub B")

    validate_success(api.publish_publication(pub_a["id"], make_privacy_headers("privacy-1")), 200)
    err = validate_error(api.publish_publication(pub_b["id"], make_privacy_headers("privacy-1")),
                         ApiErrorId.ERR_WAVE_NOT_WEIGHTED)
    assert err["error_id"] == "ERR_WAVE_NOT_WEIGHTED"
    pub_b_after = validate_success(api.get_publication(pub_b["id"], PO), 200)
    assert pub_b_after["status"] == "DRAFT"


def test_commitment_start_from_breached_returns_409(api):
    """PRD §3.8: "Any commitment action from a status that does not permit it is
    rejected with `ERR_COMMITMENT_NOT_OPEN`, and `FULFILLED` and `SUSPENDED` are
    terminal."

    Design: Corner/errors/corner_commitment_start_from_breached_returns_409
    """
    cell, wave, snap, _ = _closed_weighted_wave(num_respondents=1)
    pub = _draft_publication(wave["id"], snap["id"], k_threshold=1)
    validate_success(api.publish_publication(pub["id"], make_privacy_headers("privacy-1")), 200)
    cm = create_commitment(pub["id"], due_at="2026-08-15T00:00:00Z")
    set_clock("2026-08-16T00:00:00Z")
    validate_success(api.mark_breached_commitment(cm["id"], PM), 200)

    err = validate_error(api.start_commitment(
        cm["id"], make_liaison_headers("DEPT_TRANSPORT")),
        ApiErrorId.ERR_COMMITMENT_NOT_OPEN)
    assert err["error_id"] == "ERR_COMMITMENT_NOT_OPEN"
    cm_after = validate_success(api.get_commitment(cm["id"], PM), 200)
    assert cm_after["status"] == "BREACHED"
