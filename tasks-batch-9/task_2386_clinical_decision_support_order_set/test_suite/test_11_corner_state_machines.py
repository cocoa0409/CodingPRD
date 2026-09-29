"""State-machine coverage: initial states, legal moves, refusals and cascades.

The probes here stay on the transition graph itself — where an artifact starts,
which single move is legal from there, what a repeated or terminal-state move
returns, and which neighbouring records a rejection cascade does and does not
touch.
"""

from test_helpers import (
    ApiErrorId,
    api_client,
    assertions,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)

SEPSIS_REQUEST = {
    "title": "Sepsis bundle order set",
    "request_type": "ORDER_SET",
    "clinical_domain": "INTERNAL_MEDICINE",
    "urgency": "ROUTINE",
    "evidence_grade": "B",
    "patient_safety_flag": False,
    "evidence_citations": [
        factories.build_citation("Surviving Sepsis 2021", True),
        factories.build_citation("JAMA sepsis bundles 2018", True),
    ],
}

LACTATE_ITEM = {
    "orderable_code": "LAB-LACT",
    "display_name": "Lactate, serum",
    "item_category": "LAB",
    "sequence_index": 1,
}


# ---------------------------------------------------------------------------
# Initial states
# ---------------------------------------------------------------------------


def test_a_new_build_starts_in_draft_and_unpublished_at_once(committee):
    """Both dimensions are seeded together while the parent request advances.

    "The new order set starts with `review_state` `DRAFT`, `publication_state`
    `UNPUBLISHED`, `item_count` and `high_alert_item_count` at 0,
    `revision_round`, `votes_cast_count` and `votes_voided_count` at 0 ...
    `peer_required_votes`, `specialty_required_votes`, `peer_approve_ratio` and
    `specialty_approve_ratio` all null, `pharmacy_signoff_at`,
    `pharmacy_signoff_by_clinician_id`, `go_live_at`, `review_due_date`,
    `expiration_at`, `archive_eligible_at`, `latest_adherence_pct` and
    `archived_at` all null ... Creating the first build artifact on a request —
    order set or alert — advances that request `TRIAGE_ACCEPTED →
    BUILD_IN_PROGRESS` and increments the request's `version`."

    Design: Corner/state_machines/state_order_set_is_created_in_draft_and_unpublished
    """
    fixtures.reset_clock()
    release = fixtures.create_release(committee)
    content_request = fixtures.setup_accepted_request(committee, **SEPSIS_REQUEST)

    order_set = validate_success(
        api_client.create_order_set(
            content_request["id"],
            factories.build_order_set_payload(
                committee["builder"]["id"],
                release["id"],
                content_request["version"],
                name="Sepsis bundle v1",
                specialty="INTERNAL_MEDICINE",
            ),
            committee["builder_headers"],
        ),
        201,
    )

    assertions.assert_order_set_states(order_set, "DRAFT", "UNPUBLISHED")
    assert order_set["item_count"] == 0
    assert order_set["high_alert_item_count"] == 0
    # the parent request carries no safety flag, so the build seeds STANDARD
    assert order_set["risk_class"] == "STANDARD"
    assert order_set["peer_required_votes"] is None
    assert order_set["specialty_required_votes"] is None
    assert order_set["revision_round"] == 0
    assert order_set["votes_cast_count"] == 0
    assert order_set["votes_voided_count"] == 0
    assert order_set["go_live_at"] is None
    assert order_set["review_due_date"] is None
    assert order_set["latest_adherence_pct"] is None
    assert order_set["version"] == 1

    advanced = fixtures.read_request(committee, content_request["id"])
    assert advanced["status"] == "BUILD_IN_PROGRESS"
    assert advanced["version"] == content_request["version"] + 1


# ---------------------------------------------------------------------------
# A legal move and the refusal of its repeat
# ---------------------------------------------------------------------------


def test_accepting_at_triage_moves_the_request_and_recalibrates_it(committee):
    """One legal move stores the note, bumps the version and switches the basis.

    "Accepting a request advances `INTAKE_SUBMITTED → TRIAGE_ACCEPTED`, but only
    if the evidence clears the acceptance bar." "The citation component is 6
    points for each peer-reviewed citation, capped at 40 points however many there
    are. ... The age bonus is 0.02 per whole day of backlog age, rounded half-up to
    four decimal places, then capped at 0.30. The base is multiplied by one plus
    that age bonus ... `priority_score_basis` is set to `COMMITTEE_CALIBRATED`."
    "All three decisions store the `triage_note`."

    Design: Corner/state_machines/state_content_request_triage_accept_moves_to_triage_accepted
    """
    fixtures.reset_clock()
    request = fixtures.create_request(committee, **SEPSIS_REQUEST)
    assert request["status"] == "INTAKE_SUBMITTED"
    assert request["version"] == 1

    accepted = validate_success(
        api_client.triage_content_request(
            request["id"],
            factories.build_triage_payload(
                "ACCEPT", triage_note="Evidence adequate; queue for build"
            ),
            committee["chair_headers"],
        )
    )

    assert accepted["status"] == "TRIAGE_ACCEPTED"
    assert accepted["triage_note"] == "Evidence adequate; queue for build"
    assert accepted["return_count"] == 0
    assert accepted["priority_score_basis"] == "COMMITTEE_CALIBRATED"
    # 6 * 2 peer-reviewed citations, ROUTINE 0, no safety flag, 0 backlog days
    assertions.assert_numeric_equals(accepted["priority_score"], 12.00, 2)
    assert accepted["version"] == 2


def test_a_second_triage_call_is_refused_and_changes_nothing(committee):
    """No triage transition leaves TRIAGE_ACCEPTED, so the retry is a 409.

    "A request may only be triaged out of `INTAKE_SUBMITTED`; any other `status`
    is rejected with `ERR_CONTENT_REQUEST_NOT_TRIAGEABLE`." "**The primary
    artifact's own state** — the 409 family, one code per endpoint, listed in §5
    and named in the workflows of §3."

    Design: Corner/state_machines/state_content_request_second_triage_rejected_as_not_triageable
    """
    fixtures.reset_clock()
    accepted = fixtures.setup_accepted_request(committee, **SEPSIS_REQUEST)
    assert accepted["status"] == "TRIAGE_ACCEPTED"
    assert accepted["version"] == 2

    response = api_client.triage_content_request(
        accepted["id"],
        factories.build_triage_payload("DECLINE", triage_note="Changed my mind"),
        committee["chair_headers"],
    )
    validate_error(response, ApiErrorId.ERR_CONTENT_REQUEST_NOT_TRIAGEABLE, 409)

    unchanged = fixtures.read_request(committee, accepted["id"])
    assert unchanged["status"] == "TRIAGE_ACCEPTED"
    # a refused call is not a mutation, so the version does not move
    assert unchanged["version"] == 2
    assert unchanged["triage_note"] != "Changed my mind"


def test_submitting_a_build_for_peer_review_twice_is_not_idempotent(committee):
    """The second submission is refused and does not re-derive the quorum bar.

    "Order sets enter review by a different door: the builder submits the draft,
    which requires `review_state` `DRAFT` (otherwise `ERR_ORDER_SET_NOT_DRAFT`),
    at least one item, and a `publication_state` of `UNPUBLISHED`, `EXPIRING` or
    `EXPIRED`. Submission takes an optional `submission_note`, recomputes
    `risk_class`, seeds `peer_required_votes`, and advances `review_state` `DRAFT →
    PEER_REVIEW`." "Step two takes the base vote requirement from that class — 3
    votes for `HIGH`, 2 for `STANDARD`."

    Design: Corner/state_machines/state_order_set_repeat_submit_for_peer_review_rejected_as_not_draft
    """
    fixtures.reset_clock()
    scenario = fixtures.setup_order_set_in_peer_review(
        committee,
        request_overrides=SEPSIS_REQUEST,
        order_set_overrides={"name": "Sepsis bundle v1", "specialty": "INTERNAL_MEDICINE"},
        item_payloads=[LACTATE_ITEM],
    )
    submitted = scenario["order_set"]
    assertions.assert_order_set_states(submitted, "PEER_REVIEW", "UNPUBLISHED")
    assert submitted["peer_required_votes"] == 2

    response = api_client.submit_order_set_for_peer_review(
        submitted["id"],
        factories.build_submit_for_peer_review_payload(submission_note="Submitting again"),
        committee["builder_headers"],
    )
    validate_error(response, ApiErrorId.ERR_ORDER_SET_NOT_DRAFT, 409)

    unchanged = fixtures.read_order_set(committee, submitted["id"])
    assertions.assert_order_set_states(unchanged, "PEER_REVIEW", "UNPUBLISHED")
    assert unchanged["peer_required_votes"] == 2
    assert unchanged["version"] == submitted["version"]


# ---------------------------------------------------------------------------
# Terminal-state lockdown
# ---------------------------------------------------------------------------


def test_a_declined_request_accepts_neither_a_resubmission_nor_a_build(committee):
    """Two different doors are locked by the same terminal status.

    "Declining a request advances `INTAKE_SUBMITTED → DECLINED`, which is
    terminal." "only the clinician whose id equals the request's
    `clinical_sponsor_id` may resubmit, and only from `RETURNED_TO_SPONSOR` — any
    other `status` is `ERR_CONTENT_REQUEST_NOT_RETURNED`". "A build may only be
    opened against a request whose `status` is `TRIAGE_ACCEPTED` or already
    `BUILD_IN_PROGRESS`; anything else is `ERR_CONTENT_REQUEST_NOT_ACCEPTED`."

    Design: Corner/state_machines/state_declined_content_request_rejects_resubmit_and_build
    """
    fixtures.reset_clock()
    release = fixtures.create_release(committee)
    request = fixtures.create_request(
        committee,
        title="Duplicate therapy alert",
        request_type="ALERT",
        clinical_domain="INTERNAL_MEDICINE",
        urgency="ROUTINE",
        evidence_grade="EXPERT_OPINION",
        evidence_citations=[factories.build_citation("Ward hearsay", False)],
    )
    declined = fixtures.triage_request(
        committee,
        request["id"],
        "DECLINE",
        triage_note="No supporting evidence and no safety signal",
    )
    assert declined["status"] == "DECLINED"

    resubmission = api_client.resubmit_content_request(
        declined["id"],
        factories.build_resubmit_payload(evidence_grade="A"),
        committee["sponsor_headers"],
    )
    validate_error(resubmission, ApiErrorId.ERR_CONTENT_REQUEST_NOT_RETURNED, 409)

    build = api_client.create_order_set(
        declined["id"],
        factories.build_order_set_payload(
            committee["builder"]["id"],
            release["id"],
            declined["version"],
            name="Sneak build",
            specialty="INTERNAL_MEDICINE",
        ),
        committee["builder_headers"],
    )
    validate_error(build, ApiErrorId.ERR_CONTENT_REQUEST_NOT_ACCEPTED, 409)

    unchanged = fixtures.read_request(committee, declined["id"])
    assert unchanged["status"] == "DECLINED"
    assert unchanged["return_count"] == 0
    assert unchanged["version"] == declined["version"]

    _rows, meta = validate_paginated(
        api_client.list_order_sets(
            committee["chair_headers"], {"content_request_id": declined["id"]}
        )
    )
    assert meta["total_count"] == 0


# ---------------------------------------------------------------------------
# A precondition that blocks entry into a stage
# ---------------------------------------------------------------------------


def test_an_unjustified_hard_stop_cannot_be_taken_into_review(committee):
    """The stage-opening assignment is refused, so the alert never leaves DRAFT.

    "Assigning a reviewer to a `TIER_1_HARD_STOP` alert also requires that the
    alert already carry a non-empty `hard_stop_justification`; without it the
    assignment is refused with `ERR_TIER1_JUSTIFICATION_REQUIRED`, so a hard-stop
    alert cannot enter review unjustified." "A `TIER_1_HARD_STOP` alert
    additionally requires a non-empty `hard_stop_justification` narrative before
    it may enter review or be activated".

    Design: Corner/state_machines/state_tier1_alert_without_hard_stop_justification_rejects_first_assignment
    """
    fixtures.reset_clock()
    content_request = fixtures.setup_accepted_request(
        committee,
        title="Potassium hard stop",
        request_type="ALERT",
        clinical_domain="INTERNAL_MEDICINE",
        urgency="SAFETY_URGENT",
        evidence_grade="A",
        patient_safety_flag=True,
        evidence_citations=[
            factories.build_citation("ISMP high alert list 2024", True),
            factories.build_citation("NEJM hyperkalemia 2019", True),
        ],
    )
    alert = fixtures.design_alert(
        committee,
        content_request,
        name="Potassium hard stop",
        severity_tier="TIER_1_HARD_STOP",
        override_reason_codes=["CLINICAL_JUDGMENT", "PATIENT_SPECIFIC_PLAN"],
        firing_criteria={
            "trigger_event": "ORDER_ENTRY",
            "expression": "potassium_iv_rate > 10",
        },
    )
    assert alert["hard_stop_justification"] is None
    approver = committee["specialists"][0]

    response = api_client.create_review_assignment(
        factories.build_review_assignment_payload(
            approver["id"], "SPECIALTY_APPROVAL", alert_id=alert["id"]
        ),
        committee["chair_headers"],
    )
    validate_error(response, ApiErrorId.ERR_TIER1_JUSTIFICATION_REQUIRED, 422)

    unchanged = fixtures.read_alert(committee, alert["id"])
    assertions.assert_alert_states(unchanged, "DRAFT", "UNPUBLISHED")
    assert unchanged["approval_cast_count"] == 0
    # the stage never opened, so the tier's vote requirement was never seeded
    assert unchanged["required_approval_votes"] is None

    _rows, meta = validate_paginated(
        api_client.list_review_assignments(
            committee["chair_headers"], {"alert_id": alert["id"]}
        )
    )
    assert meta["total_count"] == 0
    assertions.assert_workload_ledger(
        validate_success(
            api_client.get_clinician(approver["id"], committee["chair_headers"])
        ),
        0,
        480,
        0,
    )


# ---------------------------------------------------------------------------
# A conditional cascade that skips already-terminal rows
# ---------------------------------------------------------------------------


def test_a_peer_reject_voids_the_open_row_and_leaves_the_withdrawn_one_alone(committee):
    """Only ASSIGNED and CAST siblings are voided; a WITHDRAWN row is untouched.

    "A `PEER_REVIEW` vote of `REJECT`, cast while the order set is in `PEER_REVIEW`
    from an assignment in state `ASSIGNED`, sends the order set `PEER_REVIEW →
    DRAFT`, increments `revision_round` by 1, and voids every *other* assignment
    on that order set in state `ASSIGNED` or `CAST` with `void_reason`
    `ARTIFACT_RETURNED_TO_DRAFT`, crediting each of those reviewers' minutes
    back." "Both `WITHDRAWN` and `VOIDED` are terminal." "Casting moves the
    assignment `ASSIGNED → CAST`, stores `vote`, `comment`, `evidence_concern` and
    `cast_at`, and leaves the workload debit in place".

    Design: Corner/state_machines/state_peer_reject_cascade_voids_open_assignments_and_skips_the_withdrawn_one
    """
    fixtures.reset_clock()
    scenario = fixtures.setup_order_set_in_peer_review(
        committee,
        request_overrides=SEPSIS_REQUEST,
        order_set_overrides={"name": "Sepsis bundle v1", "specialty": "INTERNAL_MEDICINE"},
        item_payloads=[LACTATE_ITEM],
    )
    order_set_id = scenario["order_set"]["id"]
    withdrawn_reviewer, rejecting_reviewer, open_reviewer = committee["peers"]

    to_withdraw = fixtures.assign_reviewer(
        committee, withdrawn_reviewer["id"], "PEER_REVIEW", order_set_id=order_set_id
    )
    rejecting = fixtures.assign_reviewer(
        committee, rejecting_reviewer["id"], "PEER_REVIEW", order_set_id=order_set_id
    )
    still_open = fixtures.assign_reviewer(
        committee, open_reviewer["id"], "PEER_REVIEW", order_set_id=order_set_id
    )
    validate_success(
        api_client.withdraw_review_assignment(
            to_withdraw["id"],
            factories.build_withdraw_payload(
                withdrawal_reason="Reviewer reassigned to another committee"
            ),
            committee["chair_headers"],
        )
    )

    cast = validate_success(
        api_client.cast_review_vote(
            rejecting["id"],
            factories.build_cast_payload("REJECT", comment="Antibiotic choice unsafe"),
            committee["peer_headers"][1],
        )
    )
    assert cast["state"] == "CAST"
    assert cast["vote"] == "REJECT"

    voided = validate_success(
        api_client.get_review_assignment(still_open["id"], committee["chair_headers"])
    )
    assert voided["state"] == "VOIDED"
    assert voided["void_reason"] == "ARTIFACT_RETURNED_TO_DRAFT"

    skipped = validate_success(
        api_client.get_review_assignment(to_withdraw["id"], committee["chair_headers"])
    )
    assert skipped["state"] == "WITHDRAWN"
    assert skipped["void_reason"] is None

    returned = fixtures.read_order_set(committee, order_set_id)
    assertions.assert_order_set_states(returned, "DRAFT", "UNPUBLISHED")
    assert returned["revision_round"] == 1
    assert returned["votes_cast_count"] == 1
    assert returned["votes_voided_count"] == 1

    for reviewer in (withdrawn_reviewer, open_reviewer):
        credited = validate_success(
            api_client.get_clinician(reviewer["id"], committee["chair_headers"])
        )
        assertions.assert_workload_ledger(credited, 0, 480, 0)

    rejector = validate_success(
        api_client.get_clinician(rejecting_reviewer["id"], committee["chair_headers"])
    )
    # the minutes stay debited because the reading was actually performed
    assert rejector["review_workload_assigned_minutes"] == 20
    assert rejector["review_workload_remaining_minutes"] == 460
    assertions.assert_workload_identity(rejector)
