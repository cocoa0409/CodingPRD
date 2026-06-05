"""Security freezes, protection posture derivation, overlap, and lift.

Translates queue A (Difficulty) transitive_cascade (freeze depth-2),
resource_temporal_overlap (freeze), and priority_pair_validation_conflict
(OCC-vs-overlap), plus queue B (Corner) freeze/posture instances.
"""
from test_helpers import (
    api_client,
    validate_success, validate_error, validate_paginated,
    ApiErrorId,
    make_bureau_headers, make_consumer_headers,
    find_notification,
    setup_consumer_furnisher_file, setup_active_freeze,
    set_clock, get_file_version, place_freeze, create_consumer, create_credit_file,
    create_tradeline, file_dispute,
)

BUREAU = make_bureau_headers()


def _file_at_anchor(bureau_code="EQUIFAX"):
    consumer = create_consumer()
    cfile = create_credit_file(consumer["id"], bureau_code=bureau_code)
    set_clock("2026-01-05T00:00:00.000Z")
    return consumer, cfile


# ---------------------------------------------------------------------------
# Difficulty: transitive_cascade — freeze placement depth-2
# ---------------------------------------------------------------------------

def test_freeze_placement_makes_file_frozen(api):
    """PRD §3.7: "If any freeze in that active set has freeze_type FREEZE, the
    posture is FROZEN"
    PRD §3.7: "Placing a freeze recomputes the file's protection posture, mints a
    notification with event_code FREEZE_PLACED, and increments the file's version by one."

    Design: Difficulty/transitive_cascade/freeze_place_posture_cascade_depth2
    """
    consumer, cfile = _file_at_anchor()
    place_freeze(consumer["id"], cfile["id"], cfile["version"], freeze_type="FREEZE",
                 effective_at="2026-01-05T00:00:00.000Z")
    data = validate_success(api.get_credit_file(cfile["id"], BUREAU))
    assert data["protection_state"] == "FROZEN", f"Expected FROZEN, got {data['protection_state']}"


def test_freeze_placement_mints_freeze_placed_notification(api):
    """PRD §3.7: "Placing a freeze recomputes the file's protection posture, mints a
    notification with event_code FREEZE_PLACED, and increments the file's version by one."

    Design: Difficulty/transitive_cascade/freeze_place_posture_cascade_depth2
    """
    consumer, cfile = _file_at_anchor()
    freeze = place_freeze(consumer["id"], cfile["id"], cfile["version"], freeze_type="FREEZE",
                          effective_at="2026-01-05T00:00:00.000Z")
    notifs, _meta = validate_paginated(api.list_file_notifications(cfile["id"], BUREAU))
    match = find_notification(notifs, "FREEZE_PLACED", subject_id=freeze["id"])
    assert match is not None, "Expected a FREEZE_PLACED notification for the placed freeze"


# ---------------------------------------------------------------------------
# Difficulty: resource_temporal_overlap — freeze same-type interval overlap
# ---------------------------------------------------------------------------

def test_freeze_same_type_overlap_rejected(api):
    """PRD §3.7: "A new freeze interval must not overlap an existing ACTIVE freeze of
    the same freeze_type on the same file; because the intervals are half-open, two
    freezes that merely abut — one ending exactly where the next begins — do not
    overlap, but any genuine overlap is rejected with ERR_FREEZE_OVERLAP."

    Design: Difficulty/resource_temporal_overlap/freeze_same_type_interval_overlap
    """
    consumer, cfile, _freeze = setup_active_freeze(
        freeze_type="FREEZE", effective_at="2026-01-05T00:00:00.000Z", expires_at="2026-02-05T00:00:00.000Z"
    )
    resp = api.create_security_freeze(
        {"credit_file_id": cfile["id"], "freeze_type": "FREEZE",
         "effective_at": "2026-01-20T00:00:00.000Z", "expires_at": "2026-03-01T00:00:00.000Z",
         "expected_credit_file_version": cfile["version"]},
        make_consumer_headers(consumer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FREEZE_OVERLAP.value)


def test_overlapping_different_type_freeze_accepted(api):
    """PRD §3.7: "A new freeze interval must not overlap an existing ACTIVE freeze of
    the same freeze_type on the same file; because the intervals are half-open, two
    freezes that merely abut — one ending exactly where the next begins — do not
    overlap, but any genuine overlap is rejected with ERR_FREEZE_OVERLAP."

    Design: Difficulty/resource_temporal_overlap/freeze_same_type_interval_overlap
    """
    consumer, cfile, _freeze = setup_active_freeze(
        freeze_type="FREEZE", effective_at="2026-01-05T00:00:00.000Z", expires_at="2026-02-05T00:00:00.000Z"
    )
    # A LOCK overlapping the FREEZE is a DIFFERENT freeze_type -> not rejected.
    second = validate_success(
        api.create_security_freeze(
            {"credit_file_id": cfile["id"], "freeze_type": "LOCK",
             "effective_at": "2026-01-20T00:00:00.000Z", "expires_at": "2026-03-01T00:00:00.000Z",
             "expected_credit_file_version": cfile["version"]},
            make_consumer_headers(consumer["id"])),
        201,
    )
    assert second["status"] == "ACTIVE"


# ---------------------------------------------------------------------------
# Difficulty: priority_pair_validation_conflict
# ---------------------------------------------------------------------------

def test_invalid_state_beats_file_frozen_on_open_investigation(api):
    """PRD §2.7: "then the state-machine check that the target is in a state from
    which the requested transition is defined (ERR_INVALID_STATE); and only then the
    domain-specific business rules described throughout Section 3 — the
    investigation-deadline check, the frozen-file check, the furnisher-suspension
    check, and the remaining constraint and temporal checks."

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_file_frozen_on_open_investigation
    """
    consumer, furnisher, cfile = setup_consumer_furnisher_file()
    set_clock("2026-01-05T00:00:00.000Z")
    tl = create_tradeline(cfile["id"], furnisher["id"], balance_cents=50000)
    dispute = file_dispute(consumer["id"], cfile["id"], tl["id"], get_file_version(cfile["id"]),
                           dispute_reason="NOT_MINE", clock_mode="CALENDAR")
    # Advance dispute to INVESTIGATING (so re-opening investigation is an invalid transition).
    validate_success(api.open_investigation(dispute["id"], BUREAU))
    # Freeze the file (so the frozen-file check would also fire).
    v = get_file_version(cfile["id"])
    place_freeze(consumer["id"], cfile["id"], v, freeze_type="FREEZE", effective_at="2026-01-05T00:00:00.000Z")
    resp = api.open_investigation(dispute["id"], BUREAU)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_open_investigation_conflict_does_not_change_dispute_state(api):
    """PRD §2.7: "A failure at any stage short-circuits the rest, so an earlier, more
    fundamental fault is never masked by a later one."
    PRD §3.4: "Opening the investigation changes no tradeline and leaves the file's
    open-dispute count unchanged, since the dispute remains non-terminal."

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_file_frozen_on_open_investigation
    """
    consumer, furnisher, cfile = setup_consumer_furnisher_file()
    set_clock("2026-01-05T00:00:00.000Z")
    tl = create_tradeline(cfile["id"], furnisher["id"], balance_cents=50000)
    dispute = file_dispute(consumer["id"], cfile["id"], tl["id"], get_file_version(cfile["id"]),
                           dispute_reason="NOT_MINE", clock_mode="CALENDAR")
    validate_success(api.open_investigation(dispute["id"], BUREAU))
    v = get_file_version(cfile["id"])
    place_freeze(consumer["id"], cfile["id"], v, freeze_type="FREEZE", effective_at="2026-01-05T00:00:00.000Z")
    api.open_investigation(dispute["id"], BUREAU)
    d_after = validate_success(api.get_dispute(dispute["id"], BUREAU))
    assert d_after["status"] == "INVESTIGATING", "dispute must remain INVESTIGATING after the rejected re-open"


def test_occ_stale_beats_freeze_overlap_on_freeze_create(api):
    """PRD §2.7: "then the optimistic-concurrency version check
    (ERR_STALE_FILE_VERSION); then the state-machine check ... and only then the
    domain-specific business rules described throughout Section 3 ... and the
    remaining constraint and temporal checks."

    Design: Difficulty/priority_pair_validation_conflict/occ_stale_beats_freeze_overlap_on_freeze_create
    """
    consumer, cfile = _file_at_anchor()
    stale_v = cfile["version"]
    # First freeze bumps the version, making stale_v stale; it also creates an overlap target.
    place_freeze(consumer["id"], cfile["id"], stale_v, freeze_type="FREEZE",
                 effective_at="2026-01-05T00:00:00.000Z", expires_at="2026-02-05T00:00:00.000Z")
    # Second freeze is BOTH overlapping AND carries the stale version -> OCC wins.
    resp = api.create_security_freeze(
        {"credit_file_id": cfile["id"], "freeze_type": "FREEZE",
         "effective_at": "2026-01-20T00:00:00.000Z", "expires_at": "2026-03-01T00:00:00.000Z",
         "expected_credit_file_version": stale_v},
        make_consumer_headers(consumer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_FILE_VERSION.value)


def test_stale_freeze_create_does_not_increment_version(api):
    """PRD §2.8: "If another writer has advanced the file's version since the client
    last read it ... the placement is rejected with ERR_STALE_FILE_VERSION (HTTP 412),
    so the writer cannot act on a stale view of the file."
    PRD §3.7: "Placing a freeze recomputes the file's protection posture, mints a
    notification with event_code FREEZE_PLACED, and increments the file's version by one."

    Design: Difficulty/priority_pair_validation_conflict/occ_stale_beats_freeze_overlap_on_freeze_create
    """
    consumer, cfile = _file_at_anchor()
    stale_v = cfile["version"]
    place_freeze(consumer["id"], cfile["id"], stale_v, freeze_type="FREEZE",
                 effective_at="2026-01-05T00:00:00.000Z", expires_at="2026-02-05T00:00:00.000Z")
    version_after_first = get_file_version(cfile["id"])
    # Rejected (stale + overlapping) placement must not bump the version.
    api.create_security_freeze(
        {"credit_file_id": cfile["id"], "freeze_type": "FREEZE",
         "effective_at": "2026-01-20T00:00:00.000Z", "expires_at": "2026-03-01T00:00:00.000Z",
         "expected_credit_file_version": stale_v},
        make_consumer_headers(consumer["id"]),
    )
    assert get_file_version(cfile["id"]) == version_after_first, (
        "A rejected freeze placement must not increment the file version"
    )


# ---------------------------------------------------------------------------
# Corner: state_machines / calculations — lift, dominance, future, abutting
# ---------------------------------------------------------------------------

def test_lift_already_lifted_freeze_invalid_state(api):
    """PRD §3.7: "Lifting requires that the freeze be ACTIVE (otherwise
    ERR_INVALID_STATE) and that the acting consumer own the parent file"

    Design: Corner/state_machines/security_freeze_lift_from_lifted_returns_invalid_state
    """
    consumer, cfile, freeze = setup_active_freeze(freeze_type="LOCK", effective_at="2026-01-05T00:00:00.000Z")
    validate_success(api.lift_security_freeze(freeze["id"], make_consumer_headers(consumer["id"])))
    resp = api.lift_security_freeze(freeze["id"], make_consumer_headers(consumer["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_lock_then_lift_recomputes_protection_state_to_open(api):
    """PRD §3.7: "if any has freeze_type LOCK, the posture is LOCKED; otherwise the
    posture is OPEN."
    PRD §3.7: "A consumer lifts a freeze they own, moving it from ACTIVE to LIFTED.
    ... Lifting recomputes the file's protection_state, increments the file's version
    by one, and mints a notification with event_code FREEZE_LIFTED."

    Design: Corner/state_machines/lock_then_lift_recomputes_protection_state_to_open
    """
    consumer, cfile, freeze = setup_active_freeze(freeze_type="LOCK", effective_at="2026-01-05T00:00:00.000Z")
    before = validate_success(api.get_credit_file(cfile["id"], BUREAU))
    assert before["protection_state"] == "LOCKED"
    lifted = validate_success(api.lift_security_freeze(freeze["id"], make_consumer_headers(consumer["id"])))
    assert lifted["status"] == "LIFTED"
    after = validate_success(api.get_credit_file(cfile["id"], BUREAU))
    assert after["protection_state"] == "OPEN"


def test_freeze_dominates_lock_in_posture(api):
    """PRD §3.7: "If any freeze in that active set has freeze_type FREEZE, the
    posture is FROZEN; otherwise, if any has freeze_type LOCK, the posture is LOCKED;
    otherwise the posture is OPEN. A FREEZE strictly dominates a LOCK."

    Design: Corner/calculations/lock_under_freeze_yields_frozen_dominance
    """
    consumer, cfile = _file_at_anchor()
    place_freeze(consumer["id"], cfile["id"], cfile["version"], freeze_type="LOCK",
                 effective_at="2026-01-05T00:00:00.000Z")
    v1 = get_file_version(cfile["id"])
    place_freeze(consumer["id"], cfile["id"], v1, freeze_type="FREEZE",
                 effective_at="2026-01-05T00:00:00.000Z")
    data = validate_success(api.get_credit_file(cfile["id"], BUREAU))
    assert data["protection_state"] == "FROZEN", f"Expected FROZEN, got {data['protection_state']}"


def test_future_freeze_interval_keeps_file_open(api):
    """PRD §3.7: "The system considers the set of that file's freezes that are
    simultaneously ACTIVE in status and whose half-open interval currently contains
    the clock — that is, whose effective_at is at or before the clock and whose
    expires_at is either null or strictly after the clock."

    Design: Corner/calculations/future_freeze_interval_not_yet_active_keeps_open
    """
    consumer, cfile = _file_at_anchor()
    place_freeze(consumer["id"], cfile["id"], cfile["version"], freeze_type="FREEZE",
                 effective_at="2026-02-01T00:00:00.000Z")
    data = validate_success(api.get_credit_file(cfile["id"], BUREAU))
    assert data["protection_state"] == "OPEN", f"Expected OPEN, got {data['protection_state']}"


def test_freeze_abutting_endpoints_accepted(api):
    """PRD §3.7: "because the intervals are half-open, two freezes that merely abut —
    one ending exactly where the next begins — do not overlap, but any genuine
    overlap is rejected with ERR_FREEZE_OVERLAP."

    Design: Corner/calculations/freeze_abutting_endpoints_no_overlap_accepted
    """
    consumer, cfile, _freeze = setup_active_freeze(
        freeze_type="FREEZE", effective_at="2026-01-05T00:00:00.000Z", expires_at="2026-02-05T00:00:00.000Z"
    )
    second = validate_success(
        api.create_security_freeze(
            {"credit_file_id": cfile["id"], "freeze_type": "FREEZE",
             "effective_at": "2026-02-05T00:00:00.000Z", "expires_at": "2026-03-05T00:00:00.000Z",
             "expected_credit_file_version": cfile["version"]},
            make_consumer_headers(consumer["id"])),
        201,
    )
    assert second["status"] == "ACTIVE"
