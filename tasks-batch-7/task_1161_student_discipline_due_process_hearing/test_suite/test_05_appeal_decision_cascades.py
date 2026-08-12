"""Appeal decisions: branch cascades, terminal lockdown, gate precedence."""
import pytest

from test_helpers import (
    validate_success, validate_error,
    assert_appeal,
    create_appeal_decision_payload, create_sanction_payload,
    create_conference_payload, create_conference_outcome_payload,
    create_appeal_payload,
    set_clock, setup_notice_issued_case, setup_appeal_filed_case,
    setup_closed_case, get_case,
    make_district_admin_headers, make_parent_guardian_headers,
    TEST_USERS, ApiErrorId,
)

CLS = TEST_USERS["school_classifier_headers"]


def test_appeal_second_decision_returns_409(api):
    """PRD §3.4: "A `DistrictAdmin` decides the appeal, presenting an `outcome`
    of `UPHELD`, `REVERSED`, or `REMANDED`".
    PRD §2.9: "The entity stands in a valid from-state for the requested
    transition ... Violations are rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/appeal_second_decision_returns_409
    """
    bundle = setup_appeal_filed_case(
        guardian_id="gt1", full_name="Stu Term", clock="2026-05-04T09:00:00Z",
        appeal_clock="2026-05-05T09:00:00Z", grounds="g")
    decided = validate_success(api.decide_appeal(
        bundle["appeal"]["id"], create_appeal_decision_payload("UPHELD"),
        make_district_admin_headers("da_1")), 200)
    assert decided["status"] == "UPHELD"

    # UPHELD is terminal: a second decision has no valid from-state.
    res = api.decide_appeal(
        bundle["appeal"]["id"], create_appeal_decision_payload("REVERSED"),
        make_district_admin_headers("da_1"))
    validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


# ─── Difficulty: case cycle via appeal reversal ───────

def _setup_reversal_with_held_conference(api):
    """Notice issued 2026-05-04T09:00; conference scheduled 2026-05-05T15:00
    and recorded HELD; guardian appeal FILED at 2026-05-05T09:00."""
    bundle = setup_notice_issued_case(
        guardian_id="g1", full_name="Stu Cyc", date_of_birth="2009-04-01T00:00:00Z",
        grade_level=10, demographic_group="ASIAN", clock="2026-05-04T09:00:00Z")
    conf = validate_success(api.create_conference(
        bundle["case"]["id"], create_conference_payload("2026-05-05T15:00:00Z"),
        CLS), 201)
    validate_success(api.record_conference_outcome(
        conf["id"], create_conference_outcome_payload("HELD"), CLS), 200)
    set_clock("2026-05-05T09:00:00Z")
    appeal = validate_success(api.file_appeal(
        bundle["case"]["id"],
        create_appeal_payload("procedural defect in notice"),
        make_parent_guardian_headers("g1")), 201)
    bundle["appeal"] = appeal
    bundle["conference"] = conf
    return bundle


def test_appeal_reversal_returns_case_to_sanction_proposed(api):
    """PRD §3.4: "A `REVERSED` decision unwinds the sanction: the case drops
    `NOTICE_ISSUED` → `SANCTION_PROPOSED`, its sanction fields
    `proposed_sanction_days`, `proposed_sanction_type`, `sanction_override`,
    `override_justification`, and `proposed_at` are cleared back to empty or
    false, `sanction_days_final` remains unset".

    Design: Difficulty/non_linear_state_machine/case_cycle_notice_to_proposal_on_appeal_reversal
    """
    bundle = _setup_reversal_with_held_conference(api)
    decided = validate_success(api.decide_appeal(
        bundle["appeal"]["id"],
        create_appeal_decision_payload("REVERSED", "notice content defective"),
        make_district_admin_headers("da_1")), 200)
    assert decided["status"] == "REVERSED"

    case = get_case(bundle["case"]["id"])
    assert case["status"] == "SANCTION_PROPOSED", (
        f"case must cycle back to SANCTION_PROPOSED, got {case['status']!r}")
    assert case["proposed_sanction_days"] is None
    assert case.get("sanction_days_final") is None

    # Terminal conferences are untouched by the notice-void cascade.
    confs = validate_success(api.list_conferences(case["id"], CLS), 200)
    assert confs[0]["status"] == "HELD"


def test_appeal_reversal_then_reproposal_completes_cycle(api):
    """PRD §3.4: "A `REVERSED` decision unwinds the sanction: the case drops
    `NOTICE_ISSUED` → `SANCTION_PROPOSED`, ... the case's `ISSUED` notice is
    voided to `VOIDED`".
    PRD §3.3: "the same write serves as the adjustment self-loop
    (`SANCTION_PROPOSED` → `SANCTION_PROPOSED`)".
    PRD §3.4: "A lawful issuance creates the notice in `ISSUED` status ... and
    advances the case `SANCTION_PROPOSED` → `NOTICE_ISSUED`."

    Design: Difficulty/non_linear_state_machine/case_cycle_notice_to_proposal_on_appeal_reversal
    """
    bundle = _setup_reversal_with_held_conference(api)
    validate_success(api.decide_appeal(
        bundle["appeal"]["id"], create_appeal_decision_payload("REVERSED"),
        make_district_admin_headers("da_1")), 200)

    case = get_case(bundle["case"]["id"])
    notices = validate_success(api.list_notices(case["id"], CLS), 200)
    assert len(notices) == 1
    assert notices[0]["status"] == "VOIDED", "the first notice is voided"

    # Re-propose (still at clock 2026-05-05T09:00) and issue a second notice:
    # the loop SANCTION_PROPOSED -> NOTICE_ISSUED closes a second time.
    reproposed = validate_success(api.propose_sanction(
        case["id"], create_sanction_payload(2, case["version"]), CLS), 200)
    validate_success(api.issue_notice(
        case["id"], {"delivery_method": "CERTIFIED_MAIL"}, CLS), 201)

    case = get_case(case["id"])
    assert case["status"] == "NOTICE_ISSUED"
    notices = validate_success(api.list_notices(case["id"], CLS), 200)
    assert len(notices) == 2, "the notices list holds both issuances"
    statuses = sorted(n["status"] for n in notices)
    assert statuses == ["ISSUED", "VOIDED"], (
        f"exactly one ISSUED and one VOIDED notice, got {statuses}")


# ─── Difficulty: depth-3 appeal reversal cascade ──────

def _setup_reversal_with_rescheduled_conference(api):
    """Notice issued 2026-05-04T09:00; conference NO_SHOW then rescheduled to
    2026-05-06T10:00 (attempt 2, SCHEDULED); appeal FILED 2026-05-05T09:00."""
    bundle = setup_notice_issued_case(
        guardian_id="g3", full_name="Stu Casc", date_of_birth="2009-07-01T00:00:00Z",
        grade_level=8, demographic_group="BLACK", clock="2026-05-04T09:00:00Z")
    conf = validate_success(api.create_conference(
        bundle["case"]["id"], create_conference_payload("2026-05-05T10:00:00Z"),
        CLS), 201)
    validate_success(api.record_conference_outcome(
        conf["id"], create_conference_outcome_payload("NO_SHOW"), CLS), 200)
    rescheduled = validate_success(api.reschedule_conference(
        conf["id"], create_conference_payload("2026-05-06T10:00:00Z"), CLS), 200)
    assert rescheduled["status"] == "SCHEDULED"
    set_clock("2026-05-05T09:00:00Z")
    appeal = validate_success(api.file_appeal(
        bundle["case"]["id"], create_appeal_payload("insufficient evidence"),
        make_parent_guardian_headers("g3")), 201)
    bundle["appeal"] = appeal
    bundle["conference"] = rescheduled
    return bundle


def test_reversal_cascade_mutates_case(api):
    """PRD §3.4: "A `REVERSED` decision unwinds the sanction: the case drops
    `NOTICE_ISSUED` → `SANCTION_PROPOSED`, its sanction fields
    `proposed_sanction_days`, `proposed_sanction_type`, `sanction_override`,
    `override_justification`, and `proposed_at` are cleared back to empty or
    false".

    Design: Difficulty/transitive_cascade/appeal_reversal_cascade_case_notice_conference
    """
    bundle = _setup_reversal_with_rescheduled_conference(api)
    decided = validate_success(api.decide_appeal(
        bundle["appeal"]["id"], create_appeal_decision_payload("REVERSED"),
        make_district_admin_headers("da_1")), 200)
    assert decided["status"] == "REVERSED", "trigger link 0: appeal decided"

    case = get_case(bundle["case"]["id"])
    assert case["status"] == "SANCTION_PROPOSED", (
        "link 1 (appeal -> case): the case reverts to SANCTION_PROPOSED")
    assert case["proposed_sanction_days"] is None


def test_reversal_cascade_voids_notice_and_cancels_conference(api):
    """PRD §3.4: "the case's `ISSUED` notice is voided to `VOIDED`, and that
    voiding cascades one link further — every conference of the case still
    `SCHEDULED` or `NO_SHOW` is `CANCELLED`, while conferences already `HELD`
    or `WAIVED` are untouched."

    Design: Difficulty/transitive_cascade/appeal_reversal_cascade_case_notice_conference
    """
    bundle = _setup_reversal_with_rescheduled_conference(api)
    validate_success(api.decide_appeal(
        bundle["appeal"]["id"], create_appeal_decision_payload("REVERSED"),
        make_district_admin_headers("da_1")), 200)

    notices = validate_success(
        api.list_notices(bundle["case"]["id"], CLS), 200)
    assert notices[0]["status"] == "VOIDED", (
        f"link 2 (case revert -> notice void): got {notices[0]['status']!r}")

    confs = validate_success(
        api.list_conferences(bundle["case"]["id"], CLS), 200)
    assert confs[0]["status"] == "CANCELLED", (
        f"link 3 (notice void -> conference cancel): got {confs[0]['status']!r}")
    assert confs[0]["attempt_number"] == 2


# ─── Difficulty: state guard beats temporal window ────

def test_appeal_on_closed_case_state_beats_deadline(api):
    """PRD §2.9: "Every request traverses a fixed ladder of checks, and a
    failure at any rung stops the evaluation with that rung's error."
    PRD §2.9 (rung 8): "state-guarded child creation is honored: ... a
    conference or an appeal only while its case is `NOTICE_ISSUED`" — the
    state rung precedes the due-process-windows rung that carries
    `ERR_APPEAL_WINDOW_CLOSED`.

    Design: Difficulty/priority_pair_validation_conflict/appeal_on_closed_case_state_beats_deadline
    """
    bundle = setup_closed_case(guardian_id="g5", full_name="Stu Prio",
                               grade_level=10)
    assert bundle["case"]["status"] == "CLOSED"

    # Far past the appeal deadline (notice 2026-05-04 + 5 days): the state
    # failure (case CLOSED) is reported, not the temporal failure.
    set_clock("2026-06-20T00:00:00Z")
    res = api.file_appeal(
        bundle["case"]["id"], create_appeal_payload("very late appeal"),
        make_parent_guardian_headers("g5"))
    validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


def test_appeal_on_closed_case_creates_no_row(api):
    """PRD §2.9: "Every request traverses a fixed ladder of checks, and a
    failure at any rung stops the evaluation with that rung's error."
    PRD §3.4: "A `ParentGuardian` files an appeal with `grounds` while the
    case is `NOTICE_ISSUED`".

    Design: Difficulty/priority_pair_validation_conflict/appeal_on_closed_case_state_beats_deadline
    """
    bundle = setup_closed_case(guardian_id="g5", full_name="Stu Prio",
                               grade_level=10)
    set_clock("2026-06-20T00:00:00Z")
    res = api.file_appeal(
        bundle["case"]["id"], create_appeal_payload("very late appeal"),
        make_parent_guardian_headers("g5"))
    validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    appeals = validate_success(
        api.list_appeals(bundle["case"]["id"], CLS), 200)
    assert appeals == [], "the rejected filing must not persist an Appeal row"
