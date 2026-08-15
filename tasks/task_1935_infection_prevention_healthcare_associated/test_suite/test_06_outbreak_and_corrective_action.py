"""Outbreak cluster detection, investigation workflow, unit posture cascades,
and corrective action plans (PRD §2.9, §3.7, §3.8, §3.12)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    activate_cap,
    adjudicate_hai,
    assert_instant_equal,
    close_investigation,
    create_cap,
    create_manual_investigation,
    fail_cap_verification,
    get_summary,
    get_unit,
    list_investigations,
    rule_out_investigation,
    set_clock,
    setup_cluster_scenario,
    setup_confirmed_investigation,
    setup_facility_unit,
    setup_outbreak_posture_with_open_summary,
    setup_unit_with_adjudicated_case,
    submit_cap_for_verification,
    submit_summary,
    validate_error,
    verify_cap,
)


# ---------------------------------------------------------------------------
# Cluster detection cascade (difficulty: transitive_cascade)
# ---------------------------------------------------------------------------

def test_third_case_creates_auto_threshold_investigation(api, director_headers):
    """PRD §3.8: "When the cluster holds at least three cases — exactly three
    triggers; two does not — and no investigation already exists for that unit
    and organism (compared case-insensitively) in `TRIGGERED` or `CONFIRMED`
    status, the system creates an `OutbreakInvestigation` with status
    `TRIGGERED`, `origin` `AUTO_THRESHOLD`, the window bounds stored as
    `detection_window_start` and `detection_window_end`, the contributing case
    ids captured in `trigger_case_ids` ordered by `date_of_event` ascending and
    then `created_at` ascending, and `contributing_case_count` frozen at the
    cluster size."
    PRD §3.8: "The rolling detection window spans fourteen calendar days
    inclusive: from the logical clock's current calendar date minus thirteen
    days at `00:00:00Z` through the current calendar date at `23:59:59Z`."

    Design: Difficulty/transitive_cascade/adjudication_cluster_cascade_investigation_then_posture
    """
    ctx = setup_cluster_scenario()
    before, meta_before = list_investigations({"unit_id": ctx["unit"]["id"]})
    assert meta_before["total_count"] == 0, (
        "two cases are below the threshold; no investigation may exist yet"
    )

    set_clock("2026-08-09T12:00:00Z")
    adjudicate_hai(
        ctx["case_3"]["id"], "2026-08-09T00:00:00Z",
        rationale="LCBI-1 case three confirmed",
    )

    investigations, meta = list_investigations(
        {"unit_id": ctx["unit"]["id"], "status": "TRIGGERED"}
    )
    assert meta["total_count"] == 1, (
        f"the third adjudication must auto-create one investigation, got "
        f"{meta['total_count']}"
    )
    investigation = investigations[0]
    assert investigation["origin"] == "AUTO_THRESHOLD"
    assert investigation["status"] == "TRIGGERED"
    assert investigation["contributing_case_count"] == 3
    assert_instant_equal(
        investigation["detection_window_start"], "2026-07-27T00:00:00Z",
        "detection_window_start",
    )
    assert_instant_equal(
        investigation["detection_window_end"], "2026-08-09T23:59:59Z",
        "detection_window_end",
    )
    assert investigation["trigger_case_ids"] == [
        ctx["case_1"]["id"],
        ctx["case_2"]["id"],
        ctx["case_3"]["id"],
    ], "trigger_case_ids must be ordered by date_of_event ascending"


def test_auto_investigation_drives_unit_posture_elevated(api, director_headers):
    """PRD §2.9: "Otherwise it is `ELEVATED` whenever at least one investigation
    is `TRIGGERED`, or at least one corrective action plan is in `ACTIVE`,
    `VERIFICATION_PENDING`, or `ESCALATED`."
    PRD §3.5: "Cluster detection then runs for the attributed unit and the
    case's `suspected_organism`, as described in §3.7; if the threshold is
    crossed, the system creates an `OutbreakInvestigation` in `TRIGGERED` status
    with `origin` `AUTO_THRESHOLD`. That investigation creation recomputes the
    unit's `surveillance_posture` — a freshly `TRIGGERED` investigation drives
    `ELEVATED` — and increments the unit's `version`."

    Design: Difficulty/transitive_cascade/adjudication_cluster_cascade_investigation_then_posture
    """
    ctx = setup_cluster_scenario()
    posture_before = get_unit(ctx["unit"]["id"])["surveillance_posture"]
    assert posture_before == "NORMAL"

    set_clock("2026-08-09T12:00:00Z")
    adjudicate_hai(
        ctx["case_3"]["id"], "2026-08-09T00:00:00Z",
        rationale="LCBI-1 case three confirmed",
    )
    posture_after = get_unit(ctx["unit"]["id"])["surveillance_posture"]
    assert posture_after == "ELEVATED", (
        f"auto-created TRIGGERED investigation must drive ELEVATED, got {posture_after}"
    )


# ---------------------------------------------------------------------------
# Submission gate on OUTBREAK posture (difficulty: cross_entity_state_dependency)
# ---------------------------------------------------------------------------

def test_submit_blocked_while_unit_in_outbreak_posture(api, ip_headers):
    """PRD §3.7: "Submission — from `OPEN`, `REJECTED`, or `UNDER_AMENDMENT`,
    anything else rejected with `ERR_SUMMARY_NOT_SUBMITTABLE` — records
    `submitted_by_user_id` from the acting user's header, cascades every
    denominator row for the unit and month into `LOCKED`, and is refused
    outright with `ERR_OUTBREAK_POSTURE_BLOCKS_SUBMISSION` when the unit's
    `surveillance_posture` is `OUTBREAK`."
    PRD §2.9: "A unit is in `OUTBREAK` posture whenever at least one of its
    `OutbreakInvestigation` rows has status `CONFIRMED`."

    Design: Difficulty/cross_entity_state_dependency/summary_submission_gated_by_unit_outbreak_posture
    """
    ctx = setup_outbreak_posture_with_open_summary()
    assert ctx["investigation"]["contributing_case_count"] == 1
    assert get_unit(ctx["unit"]["id"])["surveillance_posture"] == "OUTBREAK"

    resp = api.submit_summary(ctx["summary"]["id"], ip_headers)
    validate_error(resp, ApiErrorId.ERR_OUTBREAK_POSTURE_BLOCKS_SUBMISSION)
    assert resp.status_code == 403
    assert get_summary(ctx["summary"]["id"])["status"] == "OPEN", (
        "a blocked submission must leave the summary OPEN"
    )


def test_submit_succeeds_after_outbreak_closed_out(api, ip_headers):
    """PRD §3.8: "Closure requires `CONFIRMED` or `RULED_OUT` status
    (`ERR_OUTBREAK_NOT_CLOSABLE`), and closing from `CONFIRMED` additionally
    requires at least one corrective action plan with `source_type` `OUTBREAK`
    referencing this investigation to have reached `VERIFIED` — otherwise
    `ERR_OUTBREAK_CLOSE_BLOCKED`."
    PRD §2.9: "Posture is not set directly by any client; it is a pure function
    of the unit's open investigations and open corrective action plans,
    recomputed on every mutation of either."

    Design: Difficulty/cross_entity_state_dependency/summary_submission_gated_by_unit_outbreak_posture
    """
    from test_helpers import create_verified_outbreak_cap

    ctx = setup_outbreak_posture_with_open_summary()
    cap = create_verified_outbreak_cap(
        ctx["unit"]["id"], ctx["investigation"]["id"],
        description="terminal cleaning and cohorting",
        due_date="2026-08-20T00:00:00Z",
    )
    assert cap["status"] == "VERIFIED"

    closed = close_investigation(ctx["investigation"]["id"])
    assert closed["status"] == "CLOSED"
    assert get_unit(ctx["unit"]["id"])["surveillance_posture"] == "NORMAL", (
        "no CONFIRMED investigations and no open CAPs must return posture to NORMAL"
    )

    submitted = submit_summary(ctx["summary"]["id"], user_id="ip-user-1")
    assert submitted["status"] == "SUBMITTED"


# ---------------------------------------------------------------------------
# Corner: cluster threshold boundary and posture recompute
# ---------------------------------------------------------------------------

def test_outbreak_threshold_two_cases_no_investigation(api, director_headers):
    """PRD §3.8: "When the cluster holds at least three cases — exactly three
    triggers; two does not — and no investigation already exists for that unit
    and organism (compared case-insensitively) in `TRIGGERED` or `CONFIRMED`
    status, the system creates an `OutbreakInvestigation` with status
    `TRIGGERED`, `origin` `AUTO_THRESHOLD`, the window bounds stored as
    `detection_window_start` and `detection_window_end`, the contributing case
    ids captured in `trigger_case_ids` ordered by `date_of_event` ascending and
    then `created_at` ascending, and `contributing_case_count` frozen at the
    cluster size."

    Design: Corner/calculations/outbreak_threshold_two_cases_no_investigation
    """
    ctx = setup_cluster_scenario()
    # Exactly CLUSTER_THRESHOLD - 1 == 2 same-organism adjudications happened
    # inside one 14-day window; the third case is left UNDER_REVIEW.
    investigations, meta = list_investigations({"unit_id": ctx["unit"]["id"]})
    assert meta["total_count"] == 0, (
        f"2 cases must not trigger an investigation, got {meta['total_count']}"
    )
    assert get_unit(ctx["unit"]["id"])["surveillance_posture"] == "NORMAL"


def test_posture_recompute_after_rule_out_returns_normal(api, director_headers):
    """PRD §3.8: "Ruling out, also from `TRIGGERED` under
    `ERR_OUTBREAK_NOT_CONFIRMABLE`, takes a `reason`, lands the investigation in
    `RULED_OUT`, and recomputes posture — which may drop the unit from
    `ELEVATED` to `NORMAL` when no other drivers remain."
    PRD §2.9: "Otherwise it is `ELEVATED` whenever at least one investigation is
    `TRIGGERED`, or at least one corrective action plan is in `ACTIVE`,
    `VERIFICATION_PENDING`, or `ESCALATED`."

    Design: Corner/calculations/posture_recompute_after_rule_out_returns_normal
    """
    facility, unit = setup_facility_unit()
    investigation = create_manual_investigation(unit["id"], "VRE")
    assert investigation["status"] == "TRIGGERED"
    assert get_unit(unit["id"])["surveillance_posture"] == "ELEVATED", (
        "a TRIGGERED investigation must drive ELEVATED"
    )

    ruled_out = rule_out_investigation(
        investigation["id"], reason="pseudo-outbreak from lab"
    )
    assert ruled_out["status"] == "RULED_OUT"
    assert get_unit(unit["id"])["surveillance_posture"] == "NORMAL", (
        "with no drivers remaining, posture must return to NORMAL"
    )


# ---------------------------------------------------------------------------
# Corner: investigation state gates
# ---------------------------------------------------------------------------

def test_outbreak_close_blocked_without_verified_cap(api, director_headers):
    """PRD §3.8: "Closure requires `CONFIRMED` or `RULED_OUT` status
    (`ERR_OUTBREAK_NOT_CLOSABLE`), and closing from `CONFIRMED` additionally
    requires at least one corrective action plan with `source_type` `OUTBREAK`
    referencing this investigation to have reached `VERIFIED` — otherwise
    `ERR_OUTBREAK_CLOSE_BLOCKED`."

    Design: Corner/state_machines/outbreak_close_blocked_without_verified_cap
    """
    ctx = setup_confirmed_investigation(organism="Acinetobacter")
    cap = create_cap(
        ctx["unit"]["id"], "OUTBREAK", ctx["investigation"]["id"],
        user_id="ip-user-1", description="enhanced terminal cleaning",
        due_date="2026-08-20T00:00:00Z",
    )
    activate_cap(cap["id"], user_id="ip-user-1")
    submit_cap_for_verification(
        cap["id"], user_id="ip-user-1",
        evidence_notes="cleaning logs attached here",
    )

    resp_blocked = api.close_investigation(
        ctx["investigation"]["id"], director_headers
    )
    validate_error(resp_blocked, ApiErrorId.ERR_OUTBREAK_CLOSE_BLOCKED)

    verify_cap(cap["id"], user_id="dir-user-1")
    closed = close_investigation(ctx["investigation"]["id"])
    assert closed["status"] == "CLOSED"
    assert get_unit(ctx["unit"]["id"])["surveillance_posture"] == "NORMAL"


def test_outbreak_confirm_from_ruled_out_rejected(api, director_headers):
    """PRD §3.8: "Confirmation requires `TRIGGERED` status
    (`ERR_OUTBREAK_NOT_CONFIRMABLE`) and at least one contributing case — a
    `contributing_case_count` of zero is rejected with
    `ERR_OUTBREAK_EMPTY_CLUSTER`."
    PRD §3.8: "Ruling out, also from `TRIGGERED` under
    `ERR_OUTBREAK_NOT_CONFIRMABLE`, takes a `reason`, lands the investigation in
    `RULED_OUT`, and recomputes posture — which may drop the unit from
    `ELEVATED` to `NORMAL` when no other drivers remain."

    Design: Corner/state_machines/outbreak_confirm_from_ruled_out_rejected
    """
    # One adjudicated case is in place so the manual snapshot is non-empty;
    # the confirm attempt below then fails purely on the state precondition.
    ctx = setup_unit_with_adjudicated_case(organism="MRSA")
    investigation = create_manual_investigation(ctx["unit"]["id"], "MRSA")
    assert investigation["contributing_case_count"] == 1

    ruled_out = rule_out_investigation(
        investigation["id"], reason="pseudo-cluster, lab error"
    )
    assert ruled_out["status"] == "RULED_OUT"

    resp_confirm = api.confirm_investigation(investigation["id"], director_headers)
    validate_error(resp_confirm, ApiErrorId.ERR_OUTBREAK_NOT_CONFIRMABLE)

    closed = close_investigation(investigation["id"])
    assert closed["status"] == "CLOSED"

    resp_rule_out = api.rule_out_investigation(
        investigation["id"], {"reason": "second rule-out try"}, director_headers
    )
    validate_error(resp_rule_out, ApiErrorId.ERR_OUTBREAK_NOT_CONFIRMABLE)


def test_outbreak_close_from_triggered_rejected(api, director_headers):
    """PRD §3.8: "Closure requires `CONFIRMED` or `RULED_OUT` status
    (`ERR_OUTBREAK_NOT_CLOSABLE`), and closing from `CONFIRMED` additionally
    requires at least one corrective action plan with `source_type` `OUTBREAK`
    referencing this investigation to have reached `VERIFIED` — otherwise
    `ERR_OUTBREAK_CLOSE_BLOCKED`."

    Design: Corner/validations/outbreak_close_from_triggered_rejected
    """
    facility, unit = setup_facility_unit()
    investigation = create_manual_investigation(unit["id"], "VRE")
    resp = api.close_investigation(investigation["id"], director_headers)
    validate_error(resp, ApiErrorId.ERR_OUTBREAK_NOT_CLOSABLE)


def test_outbreak_confirm_empty_cluster_rejected(api, director_headers):
    """PRD §3.8: "Confirmation requires `TRIGGERED` status
    (`ERR_OUTBREAK_NOT_CONFIRMABLE`) and at least one contributing case — a
    `contributing_case_count` of zero is rejected with
    `ERR_OUTBREAK_EMPTY_CLUSTER`."
    PRD §3.8: "An `InfectionPreventionist` may also open an investigation
    manually for a `unit_id` and `organism`; a manual investigation takes
    `origin` `MANUAL`, snapshots the same matching cluster into
    `trigger_case_ids` and `contributing_case_count` at creation, starts in
    `TRIGGERED`, and recomputes posture."

    Design: Corner/validations/outbreak_confirm_empty_cluster_rejected
    """
    facility, unit = setup_facility_unit()
    investigation = create_manual_investigation(unit["id"], "VRE")
    assert investigation["contributing_case_count"] == 0, (
        "with no adjudicated cases the snapshot must be empty"
    )
    resp = api.confirm_investigation(investigation["id"], director_headers)
    validate_error(resp, ApiErrorId.ERR_OUTBREAK_EMPTY_CLUSTER)


# ---------------------------------------------------------------------------
# Corner: corrective action plans
# ---------------------------------------------------------------------------

def test_cap_source_referential_validation(api, ip_headers):
    """PRD §3.12: "The reference is polymorphic and is existence-checked against
    the type pinned by `source_type`: an `OUTBREAK` source must reference an
    `OutbreakInvestigation` that has reached `CONFIRMED`; an `ISOLATION_AUDIT`
    source references an `IsolationComplianceAudit`; a `SIR_HIGH` source
    references a `MonthlySummary`; and a `HAND_HYGIENE` source references the
    `Unit` itself. A missing reference, a reference to a non-existent entity, a
    type mismatch, or an `OUTBREAK` reference to an investigation that is not
    `CONFIRMED` is rejected with `ERR_CAP_SOURCE_INVALID`."

    Design: Corner/validations/cap_source_referential_validation
    """
    facility, unit = setup_facility_unit()
    investigation = create_manual_investigation(unit["id"], "VRE")

    resp_triggered = api.create_corrective_action_plan(
        {
            "unit_id": unit["id"],
            "source_type": "OUTBREAK",
            "source_ref_id": investigation["id"],
            "description": "premature cap for unconfirmed",
            "due_date": "2026-08-20T00:00:00Z",
        },
        ip_headers,
    )
    validate_error(resp_triggered, ApiErrorId.ERR_CAP_SOURCE_INVALID)

    resp_missing = api.create_corrective_action_plan(
        {
            "unit_id": unit["id"],
            "source_type": "OUTBREAK",
            "source_ref_id": NON_EXISTENT_UUID,
            "description": "cap against missing ref id",
            "due_date": "2026-08-20T00:00:00Z",
        },
        ip_headers,
    )
    validate_error(resp_missing, ApiErrorId.ERR_CAP_SOURCE_INVALID)


def test_cap_activation_and_verification_state_gates(api, ip_headers,
                                                     director_headers):
    """PRD §3.12: "Activation moves a `DRAFT` plan to `ACTIVE`
    (`ERR_CAP_NOT_ACTIVATABLE` otherwise) and recomputes unit posture — an
    `ACTIVE` plan drives `ELEVATED`."
    PRD §3.12: "Verification belongs to an `InfectionControlDirector` and
    requires `VERIFICATION_PENDING` (`ERR_CAP_NOT_VERIFIABLE`)."

    Design: Corner/validations/cap_activation_and_verification_state_gates
    """
    ctx = setup_confirmed_investigation(organism="MRSA")
    cap = create_cap(
        ctx["unit"]["id"], "OUTBREAK", ctx["investigation"]["id"],
        description="cap for state gate tests", due_date="2026-08-25T00:00:00Z",
    )
    assert cap["status"] == "DRAFT"
    activate_cap(cap["id"])

    resp_activate = api.activate_cap(cap["id"], ip_headers)
    validate_error(resp_activate, ApiErrorId.ERR_CAP_NOT_ACTIVATABLE)

    resp_verify = api.verify_cap(cap["id"], director_headers)
    validate_error(resp_verify, ApiErrorId.ERR_CAP_NOT_VERIFIABLE)


def test_cap_failed_verification_loop_then_escalation(api, ip_headers):
    """PRD §3.12: "Failed verification carries a `reason`, requires the same
    `VERIFICATION_PENDING` status under `ERR_CAP_NOT_VERIFIABLE`, and increments
    `failure_count` by one. While the resulting count is still below two, the
    plan returns to `ACTIVE` for rework; on the failure that brings the count to
    two, the plan instead moves to terminal `ESCALATED`."
    PRD §3.12: "Both branches recompute unit posture, and an `ESCALATED` plan
    continues to drive `ELEVATED` — an unresolved escalation is exactly the
    signal posture exists to carry."
    PRD §3.12: "When evidence of completion is ready, the preventionist submits
    the plan for verification with `evidence_notes` of at least twenty
    characters; this requires `ACTIVE` status (`ERR_CAP_NOT_SUBMITTABLE`) and
    lands the plan in `VERIFICATION_PENDING`."

    Design: Corner/state_machines/cap_failed_verification_loop_then_escalation
    """
    ctx = setup_confirmed_investigation(organism="MRSA")
    cap = create_cap(
        ctx["unit"]["id"], "OUTBREAK", ctx["investigation"]["id"],
        user_id="ip-user-1", description="staff retraining program",
        due_date="2026-08-25T00:00:00Z",
    )
    activate_cap(cap["id"], user_id="ip-user-1")

    submit_cap_for_verification(
        cap["id"], user_id="ip-user-1",
        evidence_notes="first submission of evidence",
    )
    first_fail = fail_cap_verification(
        cap["id"], reason="evidence insufficient", user_id="dir-user-1"
    )
    assert first_fail["status"] == "ACTIVE", (
        f"first failure must return the plan to ACTIVE, got {first_fail['status']}"
    )
    assert first_fail["failure_count"] == 1

    submit_cap_for_verification(
        cap["id"], user_id="ip-user-1",
        evidence_notes="second submission of evidence",
    )
    second_fail = fail_cap_verification(
        cap["id"], reason="still not sustained", user_id="dir-user-1"
    )
    assert second_fail["status"] == "ESCALATED", (
        f"the second failure must escalate terminally, got {second_fail['status']}"
    )
    assert second_fail["failure_count"] == 2

    resp_third = api.submit_cap_for_verification(
        cap["id"], {"evidence_notes": "third attempt not allowed"}, ip_headers
    )
    validate_error(resp_third, ApiErrorId.ERR_CAP_NOT_SUBMITTABLE)

    assert get_unit(ctx["unit"]["id"])["surveillance_posture"] == "OUTBREAK", (
        "the CONFIRMED investigation is still open, so posture stays OUTBREAK"
    )
