"""Transitions whose own state machine permits them but whose guard reads another entity."""

from test_helpers import *  # noqa: F401,F403


# ---------------------------------------------------------------------------
# Countersigning an agreement reads the licensee's status
# ---------------------------------------------------------------------------


def _agreement_awaiting_signature_under_a_suspended_licensee():
    category = create_jersey_category()
    licensee = create_active_licensee()
    agreement = create_draft_agreement(
        licensee["id"],
        category["id"],
        minimum_guarantee_cents=1000000,
        required_advance_cents=250000,
    )
    pay_advance(agreement["id"], 250000)
    grant_territory(agreement["id"])
    agreement = submit_agreement_for_signature(agreement["id"])
    assert agreement["contract_status"] == "PENDING_SIGNATURE"

    # The agreement was never ACTIVE, so the suspension cascade cannot reach it.
    suspend_licensee(licensee["id"], reason="Unresolved mark misuse notice")
    return {"category": category, "licensee": licensee, "agreement": agreement}


def test_countersigning_under_a_suspended_licensee_is_refused(api, ops_headers):
    """PRD §2.8: "17. The governing licensee's `status` is `ACTIVE`. This guards four
    operations: drafting an agreement, the activate and reinstate actions on an agreement's
    contract dimension, creating a retailer authorization under a licensee, and the approve
    and reinstate actions on a retailer authorization. In all four the rejection is
    `ERR_LICENSEE_NOT_ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/agreement_activation_requires_active_licensee
    """
    context = _agreement_awaiting_signature_under_a_suspended_licensee()
    agreement_id = context["agreement"]["id"]

    response = api.set_contract_status(
        agreement_id, contract_status_payload("ACTIVATE", countersigned_by="R. Vance"), ops_headers
    )
    validate_error(response, ApiErrorId.LICENSEE_NOT_ACTIVE.value, 409)

    unchanged = get_agreement(agreement_id)
    assert unchanged["contract_status"] == "PENDING_SIGNATURE"
    assert unchanged["countersigned_by"] is None


def test_countersigning_succeeds_once_the_licensee_is_reinstated(api):
    """PRD §3.3: "Activation takes `PENDING_SIGNATURE` to `ACTIVE`, requires the governing
    licensee to be `ACTIVE`, and requires a non-empty `countersigned_by` naming the
    countersigning party, which is stored on the agreement; it also recomputes the
    licensee's `agreement_count`."

    Design: Difficulty/cross_entity_state_dependency/agreement_activation_requires_active_licensee
    """
    context = _agreement_awaiting_signature_under_a_suspended_licensee()

    reinstated = reinstate_licensee(context["licensee"]["id"])
    assert reinstated["status"] == "ACTIVE"
    assert reinstated["suspension_reason"] is None

    activated = activate_agreement(context["agreement"]["id"])
    assert activated["contract_status"] == "ACTIVE"
    assert activated["countersigned_by"] == "R. Vance"


# ---------------------------------------------------------------------------
# Approving a design reads the status of every mark it uses
# ---------------------------------------------------------------------------


def _submission_in_review_with_a_restricted_mark():
    club = create_club()
    league_mark = create_league_mark()
    club_mark = create_club_mark(
        club["id"], mark_code="CLUB_ATL_ROUNDEL", usage_class="SECONDARY"
    )
    context = setup_submission_in_review(mark_ids=[league_mark["id"], club_mark["id"]])
    context["club"] = club
    context["league_mark"] = league_mark
    context["club_mark"] = club_mark

    # The mark is restricted only after the design entered review.
    restricted = set_mark_status(club_mark["id"], "RESTRICT", reason="Roundel artwork under revision")
    assert restricted["status"] == "RESTRICTED"
    return context


def test_approval_is_refused_while_one_of_the_marks_is_restricted(api, ops_headers):
    """PRD §2.8: "20. Every mark in `mark_ids` has `status` `ACTIVE`. Guards submission
    creation, design submission, and the approve review decision; otherwise
    `ERR_MARK_NOT_ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/submission_approval_requires_active_marks
    """
    context = _submission_in_review_with_a_restricted_mark()
    submission_id = context["submission"]["id"]

    response = api.create_submission_review_decision(
        submission_id, submission_review_decision_payload("APPROVE"), ops_headers
    )
    validate_error(response, ApiErrorId.MARK_NOT_ACTIVE.value, 409)

    unchanged = get_submission(submission_id)
    assert unchanged["status"] == "IN_REVIEW"
    assert unchanged["approved_at"] is None
    assert get_agreement(context["agreement"]["id"])["approved_sku_count"] == 0


def test_approval_succeeds_once_the_mark_is_reinstated_and_pins_both_marks(api):
    """PRD §3.2: "Reinstatement is permitted from `RESTRICTED` and from `WITHDRAWN` and
    returns the mark to `ACTIVE`; from `RESTRICTED` it clears `status_reason` to null, and
    from `WITHDRAWN` it clears both `status_reason` and `withdrawn_at` to null."

    Design: Difficulty/cross_entity_state_dependency/submission_approval_requires_active_marks
    """
    context = _submission_in_review_with_a_restricted_mark()

    reinstated = set_mark_status(context["club_mark"]["id"], "REINSTATE")
    assert reinstated["status"] == "ACTIVE"
    assert reinstated["status_reason"] is None

    approved = submission_decision(context["submission"]["id"], "APPROVE")
    assert approved["status"] == "APPROVED"
    assert approved["mark_snapshot_stale"] is False
    pinned = {entry["mark_id"] for entry in approved["approved_mark_snapshot"]}
    assert pinned == {context["league_mark"]["id"], context["club_mark"]["id"]}
    assert get_agreement(context["agreement"]["id"])["approved_sku_count"] == 1


# ---------------------------------------------------------------------------
# Locking a run reads the status of every central report for the quarter
# ---------------------------------------------------------------------------


def _open_run_with_a_filed_central_report():
    create_club()
    context = setup_licensed_operation(
        minimum_guarantee_cents=1000000,
        required_advance_cents=250000,
        central_licensing_flag=True,
    )
    licensee_id = context["licensee"]["id"]

    first_lines = simple_report_lines(context["authorization"]["id"], 6250000, units=12500)
    first = create_report(context["agreement"]["id"], "2026Q1", first_lines, licensee_id)
    file_report(first["id"], licensee_id)
    accept_report(first["id"])

    second_lines = simple_report_lines(context["authorization"]["id"], 6250000, units=12500)
    second = create_report(context["agreement"]["id"], "2026Q2", second_lines, licensee_id)
    context["pending_report"] = file_report(second["id"], licensee_id)

    context["run"] = create_distribution_run("2026Q2")
    assert context["run"]["status"] == "OPEN"
    return context


def test_locking_is_blocked_while_a_central_report_is_still_filed(api, finance_headers):
    """PRD §3.9: "Locking moves `OPEN` to `LOCKED`, requires the `expected_run_version` of
    Section 2.7, requires that no report with `status` `FILED` or `RETURNED` exists for the
    run's quarter on an agreement whose `central_licensing_flag` is true, stamps `locked_at`
    with the clock instant and increments the run's `version` by 1."

    Design: Difficulty/cross_entity_state_dependency/distribution_blocked_until_central_reports_leave_filed
    """
    context = _open_run_with_a_filed_central_report()
    run_id = context["run"]["id"]

    response = api.lock_distribution_run(
        run_id, run_version_payload(run_version(run_id)), finance_headers
    )
    validate_error(response, ApiErrorId.PENDING_REPORTS_BLOCK_DISTRIBUTION.value, 409)

    unchanged = get_run(run_id)
    assert unchanged["status"] == "OPEN"
    assert unchanged["locked_at"] is None


def test_locking_succeeds_once_that_report_is_accepted_and_pooled(api):
    """PRD §3.9: "While the run is `OPEN`, each accepted report on a central agreement for
    that quarter raises `projected_pool_cents` by its `royalty_due_cents` and `report_count`
    by one, as described in Section 3.7."

    Design: Difficulty/cross_entity_state_dependency/distribution_blocked_until_central_reports_leave_filed
    """
    context = _open_run_with_a_filed_central_report()
    run_id = context["run"]["id"]

    accepted = accept_report(context["pending_report"]["id"])
    assert accepted["status"] == "ACCEPTED"
    assert accepted["royalty_due_cents"] == 500000

    locked = lock_run(run_id)
    assert locked["status"] == "LOCKED"
    assert locked["locked_at"] is not None
    # Only the 2026Q2 report is in scope for a 2026Q2 run.
    assert locked["projected_pool_cents"] == 500000
    assert locked["report_count"] == 1
