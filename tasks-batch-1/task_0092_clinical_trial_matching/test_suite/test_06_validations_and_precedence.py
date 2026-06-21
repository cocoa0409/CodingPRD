"""Business validations and the §2.8 precedence ordering: the blood-draw
window boundary, capacity boundary, cross-entity preconditions, visit-window
overlap, single-open-review uniqueness, and the assorted referential / state
guards (PRD §2.8, §3.1, §3.2, §3.4, §3.6)."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    transition_payload, complete_visit_payload, create_visit_payload,
    create_consent_document_payload, create_irb_review_payload,
    create_criterion_payload,
    assert_visit,
    set_clock, get_trial_version,
    create_trial, add_arm, create_consent_document,
    open_irb_review, approve_protocol, approve_consent, activate_consent,
    setup_open_trial, setup_enrollment_on_hold,
    setup_consented_enrollment, setup_randomized_enrollment, setup_active_enrollment,
    create_eligible_screened_enrollment, consent_enrollment, randomize_enrollment,
    schedule_visit,
    activate_consent_payload,
    TEST_USERS,
)


# ─── Difficulty: priority_pair_validation_conflict ──────────────────


def test_state_check_precedes_trial_not_open_on_randomize(api):
    """PRD §2.8: "then presence of the fields a given action requires
    (`ERR_MISSING_ACTION_FIELD`); then that the target resource is in a state
    from which the requested transition is defined (`ERR_INVALID_STATE`). The
    remaining business, safety, referential, temporal, and fiscal checks are
    evaluated after these"

    Design: Difficulty/priority_pair_validation_conflict/ppvc_state_before_trial_not_open
    """
    set_clock("2026-06-01T08:00:00Z")
    # FROZEN trial: one enrollment driven to HOLD freezes the trial.
    ctx = setup_enrollment_on_hold(severity="LIFE_THREATENING")
    trial_id = ctx["trial_id"]
    frozen = validate_success(api.get_trial(trial_id, TEST_USERS["sponsor_headers"]), 200)
    assert frozen["posture"] == "FROZEN", "the trial is frozen by the active hold"

    # A second enrollment, still SCREENED (never consented).
    second = create_eligible_screened_enrollment(trial_id)
    tv = get_trial_version(trial_id)

    res = api.transition_enrollment(
        second["enrollment_id"],
        transition_payload("RANDOMIZE", expected_trial_version=tv),
        TEST_USERS["coordinator_headers"],
    )
    # Wrong state (SCREENED, not CONSENTED) is checked before the posture gate.
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value, 409)


def test_screened_enrollment_unchanged_after_rejected_randomize(api):
    """PRD §3.4: "**Randomize** advances `CONSENTED → RANDOMIZED`. It requires
    the enrollment to be `CONSENTED`"

    Design: Difficulty/priority_pair_validation_conflict/ppvc_state_before_trial_not_open
    """
    set_clock("2026-06-01T08:00:00Z")
    ctx = setup_enrollment_on_hold(severity="LIFE_THREATENING")
    trial_id = ctx["trial_id"]
    second = create_eligible_screened_enrollment(trial_id)
    tv = get_trial_version(trial_id)

    api.transition_enrollment(
        second["enrollment_id"],
        transition_payload("RANDOMIZE", expected_trial_version=tv),
        TEST_USERS["coordinator_headers"],
    )
    enr = validate_success(api.get_enrollment(second["enrollment_id"], TEST_USERS["coordinator_headers"]), 200)
    assert enr["enrollment_status"] == "SCREENED", "the rejected randomize leaves the enrollment SCREENED"


# ─── Difficulty: boundary_precision_check / draw window ─────────────


def test_draw_at_upper_bound_out_of_window(api):
    """PRD §3.6: "the acceptable interval runs from `scheduled_at` minus `w`
    minutes inclusive up to `scheduled_at` plus `w` minutes exclusive. A draw
    exactly at the lower bound is in the window; a draw exactly at the upper
    bound is out of it. A draw outside this half-open window is rejected with
    `ERR_DRAW_OUT_OF_WINDOW` (HTTP 409)."

    Design: Difficulty/boundary_precision_check/bpc_draw_window_upper_bound_exclusive
    """
    set_clock("2026-06-01T08:00:00Z")
    ctx = setup_active_enrollment()
    visit = schedule_visit(ctx["enrollment_id"], 1, "2026-06-02T10:00:00Z", 15)

    # drawn_at exactly at scheduled_at + 15 minutes (upper bound, exclusive).
    res = api.complete_visit(
        visit["id"], complete_visit_payload("2026-06-02T10:15:00Z"),
        TEST_USERS["coordinator_headers"],
    )
    validate_error(res, ApiErrorId.ERR_DRAW_OUT_OF_WINDOW.value, 409)

    fetched = validate_success(api.list_visits(ctx["enrollment_id"], TEST_USERS["coordinator_headers"]), 200)
    target = next(v for v in fetched if v["id"] == visit["id"])
    assert target["status"] == "SCHEDULED", "the rejected completion leaves the visit SCHEDULED"


def test_draw_just_inside_upper_bound_completes(api):
    """PRD §3.6: "On completion the server records `drawn_at`, computes
    `draw_in_window` as whether the draw fell inside that half-open interval,
    and computes `draw_deviation_minutes` as the absolute difference between
    `drawn_at` and `scheduled_at` expressed in whole minutes with any fraction
    floored."

    Design: Difficulty/boundary_precision_check/bpc_draw_window_upper_bound_exclusive
    """
    set_clock("2026-06-01T08:00:00Z")
    ctx = setup_active_enrollment()
    visit = schedule_visit(ctx["enrollment_id"], 1, "2026-06-02T10:00:00Z", 15)

    # 10:14:00 -> deviation 14 < 15, inside the half-open window.
    res = api.complete_visit(
        visit["id"], complete_visit_payload("2026-06-02T10:14:00Z"),
        TEST_USERS["coordinator_headers"],
    )
    data = validate_success(res, 200)
    assert_visit(data)
    assert data["status"] == "COMPLETED"
    assert data["draw_in_window"] is True
    assert data["draw_deviation_minutes"] == 14, f"deviation 14 minutes, got {data['draw_deviation_minutes']}"


# ─── Difficulty: boundary_precision_check / capacity >= target ──────


def test_first_randomize_succeeds_at_capacity_one(api):
    """PRD §3.4: "It requires ... the trial's `enrolled_count` to be strictly
    less than its `target_enrollment`"

    Design: Difficulty/boundary_precision_check/bpc_capacity_ge_threshold_at_randomize
    """
    set_clock("2026-06-01T08:00:00Z")
    ot = setup_open_trial(target_enrollment=1)
    ctx = setup_consented_enrollment(open_trial=ot)
    tv = get_trial_version(ot["trial_id"])

    res = api.transition_enrollment(
        ctx["enrollment_id"], transition_payload("RANDOMIZE", expected_trial_version=tv),
        TEST_USERS["coordinator_headers"],
    )
    data = validate_success(res, 200)
    assert data["enrollment_status"] == "RANDOMIZED", "first randomize succeeds (enrolled_count 0 < 1)"


def test_second_randomize_rejected_at_capacity(api):
    """PRD §3.4: "a trial whose `enrolled_count` has reached `target_enrollment`
    rejects with `ERR_TRIAL_AT_CAPACITY` (HTTP 409)"

    Design: Difficulty/boundary_precision_check/bpc_capacity_ge_threshold_at_randomize
    """
    set_clock("2026-06-01T08:00:00Z")
    ot = setup_open_trial(target_enrollment=1)
    first = setup_consented_enrollment(open_trial=ot)
    randomize_enrollment(ot["trial_id"], first["enrollment_id"])  # consumes the lone slot

    second = create_eligible_screened_enrollment(ot["trial_id"])
    consent_enrollment(second["enrollment_id"], ot["doc_id"])
    tv = get_trial_version(ot["trial_id"])

    res = api.transition_enrollment(
        second["enrollment_id"], transition_payload("RANDOMIZE", expected_trial_version=tv),
        TEST_USERS["coordinator_headers"],
    )
    validate_error(res, ApiErrorId.ERR_TRIAL_AT_CAPACITY.value, 409)

    trial = validate_success(api.get_trial(ot["trial_id"], TEST_USERS["sponsor_headers"]), 200)
    assert trial["enrolled_count"] == 1, "enrolled_count stays at the capacity of 1"


# ─── Difficulty: cross_entity_state_dependency ──────────────────────


def test_consent_requires_trial_open(api):
    """PRD §3.4: "Because consent requires `posture` to be `OPEN`, an attempt
    while the trial is `SETUP` or `FROZEN` is rejected with `ERR_TRIAL_NOT_OPEN`
    (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/cesd_consent_requires_trial_open
    """
    set_clock("2026-06-01T08:00:00Z")
    trial = create_trial(target_enrollment=5)  # stays in SETUP
    doc = create_consent_document(trial["id"], body_hash="h1")
    enr_ctx = create_eligible_screened_enrollment(trial["id"])

    res = api.transition_enrollment(
        enr_ctx["enrollment_id"], transition_payload("CONSENT", consent_document_id=doc["id"]),
        TEST_USERS["coordinator_headers"],
    )
    validate_error(res, ApiErrorId.ERR_TRIAL_NOT_OPEN.value, 409)

    enr = validate_success(api.get_enrollment(enr_ctx["enrollment_id"], TEST_USERS["coordinator_headers"]), 200)
    assert enr["enrollment_status"] == "SCREENED", "consent on a SETUP trial leaves the enrollment SCREENED"


def test_consent_blocked_while_trial_frozen(api):
    """PRD §3.4: "Because consent requires `posture` to be `OPEN`, an attempt
    while the trial is `SETUP` or `FROZEN` is rejected with `ERR_TRIAL_NOT_OPEN`
    (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/cesd_consent_requires_trial_open
    """
    set_clock("2026-06-01T08:00:00Z")
    # An OPEN trial frozen by an active safety hold on a first enrollment.
    ctx = setup_enrollment_on_hold(severity="SEVERE")
    ot = {"trial_id": ctx["trial_id"], "doc_id": ctx["doc_id"]}
    frozen = validate_success(api.get_trial(ot["trial_id"], TEST_USERS["sponsor_headers"]), 200)
    assert frozen["posture"] == "FROZEN", "the trial is frozen by the active hold"

    # A second, SCREENED enrollment cannot CONSENT while the trial is FROZEN.
    second = create_eligible_screened_enrollment(ot["trial_id"])
    res = api.transition_enrollment(
        second["enrollment_id"], transition_payload("CONSENT", consent_document_id=ot["doc_id"]),
        TEST_USERS["coordinator_headers"],
    )
    validate_error(res, ApiErrorId.ERR_TRIAL_NOT_OPEN.value, 409)


def test_visit_complete_requires_enrollment_active(api):
    """PRD §3.6: "Completion requires the visit to be `SCHEDULED`, the parent
    enrollment's `enrollment_status` to be `ACTIVE`"

    Design: Difficulty/cross_entity_state_dependency/cesd_visit_complete_requires_enrollment_active
    """
    set_clock("2026-06-01T08:00:00Z")
    ctx = setup_randomized_enrollment()  # RANDOMIZED, not yet ACTIVE
    visit = schedule_visit(ctx["enrollment_id"], 1, "2026-06-02T10:00:00Z", 30)

    res = api.complete_visit(
        visit["id"], complete_visit_payload("2026-06-02T10:00:00Z"),
        TEST_USERS["coordinator_headers"],
    )
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value, 409)

    fetched = validate_success(api.list_visits(ctx["enrollment_id"], TEST_USERS["coordinator_headers"]), 200)
    target = next(v for v in fetched if v["id"] == visit["id"])
    assert target["status"] == "SCHEDULED", "the visit stays SCHEDULED"


def test_visit_completes_once_enrollment_active(api):
    """PRD §3.6: "Completion requires the visit to be `SCHEDULED`, the parent
    enrollment's `enrollment_status` to be `ACTIVE`, the parent enrollment's
    `safety_status` not to be `HOLD` (otherwise `ERR_ENROLLMENT_ON_HOLD`), and
    the supplied `drawn_at` to fall inside the blood-draw window."

    Design: Difficulty/cross_entity_state_dependency/cesd_visit_complete_requires_enrollment_active
    """
    set_clock("2026-06-01T08:00:00Z")
    ctx = setup_active_enrollment()  # parent enrollment is ACTIVE
    visit = schedule_visit(ctx["enrollment_id"], 1, "2026-06-02T10:00:00Z", 30)

    res = api.complete_visit(
        visit["id"], complete_visit_payload("2026-06-02T10:00:00Z"),
        TEST_USERS["coordinator_headers"],
    )
    data = validate_success(res, 200)
    assert data["status"] == "COMPLETED", \
        "with the cross-entity precondition satisfied (enrollment ACTIVE), completion succeeds"


# ─── Difficulty: resource_temporal_overlap ──────────────────────────


def test_visit_window_overlap_rejected(api):
    """PRD §3.6: "for any two visits, the absolute difference between their
    `scheduled_at` instants, measured in minutes, must be at least the sum of
    their two `draw_window_minutes` half-widths — windows are permitted to
    touch exactly at the boundary, but any closer overlap is rejected with
    `ERR_VISIT_WINDOW_OVERLAP` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/rto_visit_draw_window_sum_buffer
    """
    set_clock("2026-06-01T08:00:00Z")
    ctx = setup_active_enrollment()
    schedule_visit(ctx["enrollment_id"], 1, "2026-06-02T10:00:00Z", 30)

    # B at 10:45 with w=30: |Δ| = 45 < 30+30 = 60 -> overlap.
    res = api.create_visit(
        ctx["enrollment_id"], create_visit_payload(2, "2026-06-02T10:45:00Z", 30),
        TEST_USERS["coordinator_headers"],
    )
    validate_error(res, ApiErrorId.ERR_VISIT_WINDOW_OVERLAP.value, 409)


def test_visit_windows_touching_at_boundary_accepted(api):
    """PRD §3.6: "windows are permitted to touch exactly at the boundary, but
    any closer overlap is rejected with `ERR_VISIT_WINDOW_OVERLAP` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/rto_visit_draw_window_sum_buffer
    """
    set_clock("2026-06-01T08:00:00Z")
    ctx = setup_active_enrollment()
    schedule_visit(ctx["enrollment_id"], 1, "2026-06-02T10:00:00Z", 30)

    # B at 11:00 with w=30: |Δ| = 60 == 30+30 -> exactly touching, accepted.
    res = api.create_visit(
        ctx["enrollment_id"], create_visit_payload(2, "2026-06-02T11:00:00Z", 30),
        TEST_USERS["coordinator_headers"],
    )
    data = validate_success(res, 201)
    assert data["sequence_index"] == 2, "the touching-boundary visit is accepted"


# ─── Difficulty: resource_temporal_overlap / single open review ────


def test_second_pending_protocol_review_rejected(api):
    """PRD §3.2: "At most one `PENDING` `PROTOCOL` review may exist for a trial
    at a time; opening a second while one is still pending is rejected with
    `ERR_REVIEW_ALREADY_OPEN` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/rto_single_open_protocol_review_interval
    """
    set_clock("2026-06-01T00:00:00Z")
    trial = create_trial(target_enrollment=3)
    open_irb_review(trial["id"], scope="PROTOCOL")  # one PENDING protocol review

    res = api.create_irb_review(
        trial["id"], create_irb_review_payload(scope="PROTOCOL"), TEST_USERS["sponsor_headers"],
    )
    validate_error(res, ApiErrorId.ERR_REVIEW_ALREADY_OPEN.value, 409)


def test_first_protocol_review_pending_after_rejected_second(api):
    """PRD §3.2: "A review begins with `decision` `PENDING`, a null
    `reviewer_user_id`, and a null `decided_at`."

    Design: Difficulty/resource_temporal_overlap/rto_single_open_protocol_review_interval
    """
    set_clock("2026-06-01T00:00:00Z")
    trial = create_trial(target_enrollment=3)
    first = open_irb_review(trial["id"], scope="PROTOCOL")

    api.create_irb_review(
        trial["id"], create_irb_review_payload(scope="PROTOCOL"), TEST_USERS["sponsor_headers"],
    )
    reviews = validate_success(api.list_irb_reviews(trial["id"], TEST_USERS["sponsor_headers"]), 200)
    original = next(r for r in reviews if r["id"] == first["id"])
    assert original["decision"] == "PENDING", "the original review remains PENDING"


# ─── Corner: validations ────────────────────────────────────────────


def test_consent_version_mismatch_on_superseded_doc(api):
    """PRD §3.4: "A consent document that is not the trial's current active
    version — wrong status, wrong trial, or stale version number — is rejected
    with `ERR_CONSENT_VERSION_MISMATCH` (HTTP 409)."

    Design: Corner/validations/consent_version_mismatch_on_superseded_doc
    """
    set_clock("2026-06-01T08:00:00Z")
    ot = setup_open_trial(num_arms=1)  # v1 ACTIVE
    trial_id, doc_v1 = ot["trial_id"], ot["doc_id"]

    # Activate a v2 so v1 becomes SUPERSEDED.
    doc_v2 = create_consent_document(trial_id, body_hash="v2")
    approve_consent(trial_id, doc_v2["id"])
    activate_consent(trial_id, doc_v2["id"])

    enr_ctx = create_eligible_screened_enrollment(trial_id)
    res = api.transition_enrollment(
        enr_ctx["enrollment_id"], transition_payload("CONSENT", consent_document_id=doc_v1),
        TEST_USERS["coordinator_headers"],
    )
    validate_error(res, ApiErrorId.ERR_CONSENT_VERSION_MISMATCH.value, 409)


def test_irb_consent_scope_missing_document_rejected(api):
    """PRD §2.8: "an IRB review opened with `scope` of `CONSENT` requires
    `consent_document_id` while one opened with `scope` of `PROTOCOL` must omit
    it — a violation of any of these yields `ERR_MISSING_ACTION_FIELD`."

    Design: Corner/validations/irb_consent_scope_missing_doc_rejected
    """
    set_clock("2026-06-01T00:00:00Z")
    trial = create_trial(target_enrollment=5)

    res = api.create_irb_review(
        trial["id"], create_irb_review_payload(scope="CONSENT"), TEST_USERS["sponsor_headers"],
    )
    validate_error(res, ApiErrorId.ERR_MISSING_ACTION_FIELD.value, 400)


def test_add_criterion_after_setup_rejected(api):
    """PRD §3.1: "Adding either a criterion or an arm is permitted only while
    `posture` is `SETUP`; once the trial has left setup, an attempt to add
    either is rejected with `ERR_TRIAL_NOT_IN_SETUP` (HTTP 409)."

    Design: Corner/validations/add_criteria_after_setup_rejected
    """
    set_clock("2026-06-01T08:00:00Z")
    ot = setup_open_trial(num_arms=1)  # posture OPEN
    trial = validate_success(api.get_trial(ot["trial_id"], TEST_USERS["sponsor_headers"]), 200)
    assert trial["posture"] == "OPEN", "the trial has left SETUP"

    res = api.create_criterion(
        ot["trial_id"], create_criterion_payload(kind="INCLUSION", attribute="age_years",
                                                  comparator="GE", threshold=18),
        TEST_USERS["sponsor_headers"],
    )
    validate_error(res, ApiErrorId.ERR_TRIAL_NOT_IN_SETUP.value, 409)


def test_duplicate_visit_sequence_index_rejected(api):
    """PRD §3.6: "A `sequence_index` that already exists for the enrollment is
    rejected with `ERR_DUPLICATE_VISIT_INDEX` (HTTP 409)."

    Design: Corner/validations/duplicate_visit_sequence_index_rejected
    """
    set_clock("2026-06-01T08:00:00Z")
    ctx = setup_active_enrollment()
    schedule_visit(ctx["enrollment_id"], 1, "2026-06-02T10:00:00Z", 30)

    # Second visit reuses sequence_index 1 (far enough apart to avoid overlap).
    res = api.create_visit(
        ctx["enrollment_id"], create_visit_payload(1, "2026-06-09T10:00:00Z", 30),
        TEST_USERS["coordinator_headers"],
    )
    validate_error(res, ApiErrorId.ERR_DUPLICATE_VISIT_INDEX.value, 409)


def test_consent_activation_before_protocol_approved_rejected(api):
    """PRD §3.2: "Activation requires the document to be in `IRB_APPROVED`
    status, the trial's `irb_status` to be `APPROVED`, and the trial to have at
    least one randomization arm; if any of these preconditions is unmet, the
    activation is rejected with `ERR_TRIAL_NOT_CONFIGURED` (HTTP 409)."

    Design: Corner/validations/consent_activate_before_protocol_approved_rejected
    """
    set_clock("2026-06-01T08:00:00Z")
    trial = create_trial(target_enrollment=5)
    add_arm(trial["id"], name="TREATMENT")
    doc = create_consent_document(trial["id"], body_hash="h1")  # still DRAFT, no IRB approvals
    tv = get_trial_version(trial["id"])

    res = api.activate_consent_document(
        trial["id"], doc["id"], activate_consent_payload(tv), TEST_USERS["sponsor_headers"],
    )
    validate_error(res, ApiErrorId.ERR_TRIAL_NOT_CONFIGURED.value, 409)

    docs = validate_success(api.list_consent_documents(trial["id"], TEST_USERS["sponsor_headers"]), 200)
    target = next(d for d in docs if d["id"] == doc["id"])
    assert target["status"] == "DRAFT", "the document stays DRAFT"
