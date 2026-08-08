"""Plan lifecycle: revision cycle, adopt cascade, hearing preconditions, terminal lockdown.

Difficulty queue A: non_linear_state_machine/plan_revision_cycle,
transitive_cascade/adopt_supersede_dismiss_cascade.
Corner queue B: state_machines/hold_hearing_before_start_rejected,
state_machines/cancel_hearing_reverts_plan_to_comment_open,
state_machines/submit_review_incomplete_partition_rejected,
state_machines/open_comment_deviation_fail_blocks,
state_machines/adopt_without_held_hearing_rejected,
state_machines/terminal_plan_reject_again_invalid.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    setup_f1, setup_f1_hearing_scheduled, setup_f1_held_hearing,
    create_jurisdiction, add_block, create_plan, create_district, assign_block,
    create_venue, drive_to_comment_open, ApiErrorId, TEST_USERS,
)
from test_helpers.factories import (
    create_compliance_check_payload, create_comment_payload, create_hearing_payload,
)

CART = TEST_USERS["cartographer_headers"]
DEMO = TEST_USERS["demographer_headers"]
CHAIR = TEST_USERS["chair_headers"]
CLERK = TEST_USERS["clerk_headers"]
PUBLIC = TEST_USERS["public_headers"]


# ------------------------------------------- non_linear: plan revision cycle
def test_request_revision_returns_plan_to_under_review(api):
    """PRD §3.5: "From HEARING_SCHEDULED, a Demographer may request a revision,
    which sends the plan back to UNDER_REVIEW for further editing and re-review
    and cancels every SCHEDULED hearing on the plan."

    Design: Difficulty/non_linear_state_machine/plan_revision_cycle
    """
    ctx = setup_f1_hearing_scheduled(api, jname="Jcy")
    updated = validate_success(api.request_revision(ctx["pid"], DEMO))
    assert updated["status"] == "UNDER_REVIEW", "request-revision returns the plan to UNDER_REVIEW"


def test_request_revision_cancels_scheduled_hearing(api):
    """PRD §3.5: "sends the plan back to UNDER_REVIEW for further editing and
    re-review and cancels every SCHEDULED hearing on the plan."

    Design: Difficulty/non_linear_state_machine/plan_revision_cycle
    """
    ctx = setup_f1_hearing_scheduled(api, jname="Jcy2")
    validate_success(api.request_revision(ctx["pid"], DEMO))
    hearing = validate_success(api.get_hearing(ctx["h1"], DEMO))
    assert hearing["status"] == "CANCELLED", "the scheduled hearing is cancelled on revision"


# ------------------------------------------- transitive_cascade: adopt cascade
def _setup_adopt_cascade(api, jname):
    """P1 (F1) at HEARING_SCHEDULED with a HELD hearing; sibling P2 forked from P1
    driven to HEARING_SCHEDULED with a PENDING comment CM2 and a SCHEDULED hearing H2."""
    ctx = setup_f1_held_hearing(api, jname=jname)
    p2 = create_plan(api, ctx["jid"], name="P2", parent_plan_id=ctx["pid"])
    p2id = p2["id"]
    validate_success(api.submit_review(p2id, CART))
    validate_success(api.create_compliance_check(p2id, create_compliance_check_payload("POPULATION_DEVIATION"), DEMO), 201)
    validate_success(api.open_comment(p2id, CHAIR))
    cm2 = validate_success(api.create_comment(p2id, create_comment_payload(commenter_name="Jane", comment_text="Keep our neighborhood whole."), PUBLIC), 201)
    h2 = validate_success(api.create_hearing(
        p2id, create_hearing_payload(venue_id=ctx["vid"], scheduled_start="2026-06-02T10:00:00Z", scheduled_end="2026-06-02T11:00:00Z"), CHAIR), 201)
    return ctx, p2id, cm2["id"], h2["id"]


def test_adopt_supersedes_sibling_plan(api):
    """PRD §3.5: "every other non-terminal plan in the same jurisdiction is
    superseded - each such plan moves to SUPERSEDED".

    Design: Difficulty/transitive_cascade/adopt_supersede_dismiss_cascade
    """
    ctx, p2id, cm2, h2 = _setup_adopt_cascade(api, "Jca")
    adopted = validate_success(api.adopt_plan(ctx["pid"], CHAIR))
    assert adopted["status"] == "ADOPTED"
    sibling = validate_success(api.get_plan(p2id, CHAIR))
    assert sibling["status"] == "SUPERSEDED", "the competing sibling plan must be superseded"


def test_adopt_cascade_dismisses_comment_and_cancels_hearing(api):
    """PRD §3.5: "that supersession itself dismisses those plans' `PENDING` comments
    and cancels their `SCHEDULED` hearings".

    Design: Difficulty/transitive_cascade/adopt_supersede_dismiss_cascade
    """
    ctx, p2id, cm2, h2 = _setup_adopt_cascade(api, "Jca2")
    validate_success(api.adopt_plan(ctx["pid"], CHAIR))
    comments = validate_success(api.list_comments(p2id, CHAIR))
    dismissed = next(c for c in comments if c["id"] == cm2)
    assert dismissed["disposition"] == "DISMISSED", "superseded plan's PENDING comment must be DISMISSED"
    hearing = validate_success(api.get_hearing(h2, CHAIR))
    assert hearing["status"] == "CANCELLED", "superseded plan's SCHEDULED hearing must be CANCELLED"


# ------------------------------------------- corner: hold before start
def test_hold_hearing_before_start_rejected(api):
    """PRD §3.4: "A CommissionChair marks a hearing HELD once the logical clock has
    reached its scheduled_start; an attempt before that instant is rejected with
    ERR_HEARING_NOT_STARTED".

    Design: Corner/state_machines/hold_hearing_before_start_rejected
    """
    ctx = setup_f1_hearing_scheduled(api, jname="Jh")  # clock left at 2026-05-01 default
    validate_error(api.hold_hearing(ctx["h1"], CHAIR), ApiErrorId.ERR_HEARING_NOT_STARTED.value)


# ------------------------------------------- corner: cancel reverts to comment open
def test_cancel_only_hearing_reverts_plan_to_comment_open(api):
    """PRD §3.4: "if its plan was in HEARING_SCHEDULED and this was the last
    remaining SCHEDULED hearing on the plan, the plan reverts to COMMENT_OPEN."

    Design: Corner/state_machines/cancel_hearing_reverts_plan_to_comment_open
    """
    ctx = setup_f1_hearing_scheduled(api, jname="Jcc")
    cancelled = validate_success(api.cancel_hearing(ctx["h1"], CHAIR))
    assert cancelled["status"] == "CANCELLED"
    plan = validate_success(api.get_plan(ctx["pid"], CHAIR))
    assert plan["status"] == "COMMENT_OPEN", "cancelling the last hearing reverts the plan to COMMENT_OPEN"


# ------------------------------------------- corner: submit-review incomplete partition
def test_submit_review_incomplete_partition_rejected(api):
    """PRD §3.5: "Submission requires that the plan have at least one district and
    that it form a complete partition - every census block in the jurisdiction
    assigned to exactly one active block assignment in the plan; a plan with
    unassigned or multiply-assigned blocks is rejected with ERR_INCOMPLETE_PARTITION."

    Design: Corner/state_machines/submit_review_incomplete_partition_rejected
    """
    j = create_jurisdiction(api, name="Jip", target_district_count=2)
    jid = j["id"]
    blkA = add_block(api, jid, geoid="A", population=1049, voting_age_population=800, minority_vap=500, registered_voters=700)
    add_block(api, jid, geoid="B", population=951, voting_age_population=700, minority_vap=200, registered_voters=600)
    plan = create_plan(api, jid, name="Pip")
    pid = plan["id"]
    d1 = create_district(api, pid, 1)
    assign_block(api, pid, d1["id"], blkA["id"])  # block B left unassigned
    validate_error(api.submit_review(pid, CART), ApiErrorId.ERR_INCOMPLETE_PARTITION.value)


# ------------------------------------------- corner: open-comment deviation FAIL
def test_open_comment_blocked_by_failed_deviation_check(api):
    """PRD §3.4: "the plan's most recent POPULATION_DEVIATION compliance check must
    exist and must not have a result_status of FAIL; if there is no such check or
    the latest one failed, the request is rejected with ERR_DEVIATION_CHECK_FAILED."

    Design: Corner/state_machines/open_comment_deviation_fail_blocks
    """
    j = create_jurisdiction(api, name="Joc", target_district_count=2)
    jid = j["id"]
    blkA = add_block(api, jid, geoid="A", population=1049, voting_age_population=800, minority_vap=500, registered_voters=700)
    blkB = add_block(api, jid, geoid="B", population=951, voting_age_population=700, minority_vap=200, registered_voters=600)
    plan = create_plan(api, jid, name="Poc")
    pid = plan["id"]
    d1 = create_district(api, pid, 1)
    create_district(api, pid, 2)
    assign_block(api, pid, d1["id"], blkA["id"])
    assign_block(api, pid, d1["id"], blkB["id"])  # both blocks in District 1 -> +/-100%
    validate_success(api.submit_review(pid, CART))
    validate_success(api.create_compliance_check(pid, create_compliance_check_payload("POPULATION_DEVIATION"), DEMO), 201)
    validate_error(api.open_comment(pid, CHAIR), ApiErrorId.ERR_DEVIATION_CHECK_FAILED.value)


# ------------------------------------------- corner: adopt without held hearing
def test_adopt_without_held_hearing_rejected(api):
    """PRD §3.5: "at least one hearing on the plan is in status HELD, or the
    request is rejected with ERR_NO_HELD_HEARING".

    Design: Corner/state_machines/adopt_without_held_hearing_rejected
    """
    ctx = setup_f1_hearing_scheduled(api, jname="Jnh")  # hearing SCHEDULED, never HELD
    validate_error(api.adopt_plan(ctx["pid"], CHAIR), ApiErrorId.ERR_NO_HELD_HEARING.value)


# ------------------------------------------- corner: terminal reject lockdown
def test_reject_already_rejected_plan_invalid_state(api):
    """PRD §3.5: "A CommissionChair rejects a plan by moving it to the terminal
    REJECTED state". A terminal state permits no further transitions, so a second
    reject is ERR_INVALID_STATE (PRD §2.11 state check).

    Design: Corner/state_machines/terminal_plan_reject_again_invalid
    """
    j = create_jurisdiction(api, name="Jt", target_district_count=1)
    jid = j["id"]
    blkA = add_block(api, jid, geoid="A", population=1000, voting_age_population=800, minority_vap=200, registered_voters=600)
    plan = create_plan(api, jid, name="Pt")
    pid = plan["id"]
    d1 = create_district(api, pid, 1)
    assign_block(api, pid, d1["id"], blkA["id"])
    validate_success(api.submit_review(pid, CART))
    validate_success(api.reject_plan(pid, CHAIR))
    validate_error(api.reject_plan(pid, CHAIR), ApiErrorId.ERR_INVALID_STATE.value)
