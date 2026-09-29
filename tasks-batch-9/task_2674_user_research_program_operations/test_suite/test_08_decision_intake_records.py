"""Decision registration, request intake and the triage stamps.

These tests cover the records at the top of the funnel: what a roadmap decision
looks like the instant it is registered, what a research request looks like
before anyone has triaged it, which fields triage is allowed to write, the
decision table that turns a question type into a recommended method, the
numeric gate on locking a decision, and the ownership gate on reframing.
"""

import pytest

from test_helpers import (
    OTHER_STAKEHOLDER_HEADERS,
    RESEARCH_LEAD_HEADERS,
    RESEARCHER_HEADERS,
    STAKEHOLDER_HEADERS,
    assert_common_fields,
    create_decision,
    create_request,
    is_valid_uuid,
    read_request,
    resubmit_research_request_payload,
    setup_request_needing_reframing,
    triage_payload,
    validate_error,
    validate_success,
)

# The logical clock's startup value, rendered with the three fractional digits
# every stored timestamp carries.
STARTUP_INSTANT = "2026-08-01T00:00:00.000Z"


# ===========================================================================
# Entity shapes at creation and on read-back
# ===========================================================================
def test_roadmap_decision_creation_returns_all_declared_fields(api):
    """Registering a decision answers 201 with the four supplied inputs echoed and
    the system fields already materialised.

    PRD 3.1: "A `Stakeholder` (or a `ResearchOpsAdmin` acting on their behalf)
    registers one by supplying a `title`, which must be non-empty and at most
    200 characters; a `decision_deadline`, the ISO 8601 UTC instant by which the
    choice must be made; a `reversibility` of either `IRREVERSIBLE` or
    `REVERSIBLE`, describing how costly the decision would be to undo; and an
    `impacted_user_count`, a whole number of end users the decision touches
    that must be zero or greater."

    PRD 3.1: "A newly registered decision opens in `status` `OPEN`, with
    `evidence_confidence` at 0.00 and `locked_at` null."

    PRD 2.4: "`version` is an integer that starts at 1 when the resource is
    created and increments by exactly 1 on every mutation."

    Design: Corner/entities/roadmap_decision_creation_returns_all_declared_fields
    """
    payload = {
        "title": "Rebuild the onboarding checklist",
        "reversibility": "IRREVERSIBLE",
        "decision_deadline": "2026-09-30T00:00:00Z",
        "impacted_user_count": 12000,
    }
    decision = validate_success(
        api.create_roadmap_decision(payload, STAKEHOLDER_HEADERS), 201
    )

    assert_common_fields(decision)
    assert is_valid_uuid(decision["id"]), (
        f"Expected a server-minted UUID with no type prefix, got {decision['id']!r}"
    )
    assert decision["title"] == "Rebuild the onboarding checklist", (
        f"Expected the supplied title to be stored verbatim, got {decision['title']!r}"
    )
    assert decision["reversibility"] == "IRREVERSIBLE", (
        f"Expected reversibility IRREVERSIBLE, got {decision['reversibility']!r}"
    )
    assert decision["impacted_user_count"] == 12000, (
        f"Expected impacted_user_count 12000, got {decision['impacted_user_count']}"
    )
    assert decision["decision_deadline"] in (
        "2026-09-30T00:00:00Z",
        "2026-09-30T00:00:00.000Z",
    ), f"Expected the supplied deadline instant, got {decision['decision_deadline']!r}"

    assert decision["status"] == "OPEN", (
        f"Expected a newly registered decision to open OPEN, got {decision['status']}"
    )
    assert decision["evidence_confidence"] == pytest.approx(0.00, abs=0.01), (
        f"Expected evidence_confidence to open at 0.00, "
        f"got {decision['evidence_confidence']}"
    )
    assert decision["locked_at"] is None, (
        f"Expected locked_at to open null, got {decision['locked_at']!r}"
    )

    assert decision["version"] == 1, (
        f"Expected version to start at 1, got {decision['version']}"
    )
    assert decision["created_at"] == STARTUP_INSTANT, (
        f"Expected created_at to be stamped from the clock's startup value, "
        f"got {decision['created_at']!r}"
    )
    assert decision["updated_at"] == decision["created_at"], (
        f"Expected updated_at to equal created_at at creation, "
        f"got {decision['updated_at']!r}"
    )


def test_research_request_retrieval_returns_stored_and_default_fields(api):
    """A GET on a freshly raised request returns what was stored plus the
    untriaged defaults, with the requester taken from the creating call's header.

    PRD 3.1: "Intake takes the `roadmap_decision_id` of the decision the request
    claims to inform, a `question` — the framed research question, non-empty and
    at most 500 characters — a `question_type` drawn from `DISCOVERY`,
    `EVALUATIVE`, `BEHAVIORAL_LONGITUDINAL` and `MEASUREMENT`, and an
    `evidence_gap` of `NONE`, `PARTIAL` or `FULL` describing how much existing
    evidence is missing."

    PRD 3.1: "The request lands in `status` `SUBMITTED` with `revision_round` at
    0, its `requester_user_id` set to the acting operator's `X-User-ID`, and
    `priority_score`, `recommended_method`, `approved_method`, `triage_reason`
    and `triaged_at` all null."

    Design: Corner/entities/research_request_retrieval_returns_stored_and_default_fields
    """
    decision = create_decision(
        api,
        title="Checklist rebuild",
        reversibility="REVERSIBLE",
        decision_deadline="2026-10-01T00:00:00Z",
        impacted_user_count=4000,
    )
    created = create_request(
        decision["id"],
        api,
        question="Where do admins stall in the checklist?",
        question_type="DISCOVERY",
        evidence_gap="PARTIAL",
    )

    request = validate_success(
        api.get_research_request(created["id"], RESEARCH_LEAD_HEADERS)
    )

    assert request["id"] == created["id"], (
        f"Expected the read to return the created request, got {request['id']!r}"
    )
    assert request["roadmap_decision_id"] == decision["id"], (
        f"Expected the request to point at the decision it informs, "
        f"got {request['roadmap_decision_id']!r}"
    )
    assert request["question"] == "Where do admins stall in the checklist?", (
        f"Expected the framed question to be stored verbatim, got {request['question']!r}"
    )
    assert request["question_type"] == "DISCOVERY", (
        f"Expected question_type DISCOVERY, got {request['question_type']!r}"
    )
    assert request["evidence_gap"] == "PARTIAL", (
        f"Expected evidence_gap PARTIAL, got {request['evidence_gap']!r}"
    )
    assert request["requester_user_id"] == "u_stake_1", (
        f"Expected requester_user_id to come from the creating operator's X-User-ID, "
        f"got {request['requester_user_id']!r}"
    )

    assert request["status"] == "SUBMITTED", (
        f"Expected an untriaged request to read SUBMITTED, got {request['status']}"
    )
    assert request["revision_round"] == 0, (
        f"Expected revision_round to open at 0, got {request['revision_round']}"
    )
    for field in (
        "priority_score",
        "recommended_method",
        "approved_method",
        "triage_reason",
        "triaged_at",
    ):
        assert request[field] is None, (
            f"Expected {field} to stay null until a ResearchLead triages the request, "
            f"got {request[field]!r}"
        )
    assert request["version"] == 1, (
        f"Expected an untouched request to sit at version 1, got {request['version']}"
    )


def test_request_creation_extra_priority_score_input_ignored(api):
    """`priority_score` is written only by triage: a value supplied in the create
    body is discarded and the field stays null until the lead triages.

    PRD 3.1: "The request lands in `status` `SUBMITTED` with `revision_round` at
    0, its `requester_user_id` set to the acting operator's `X-User-ID`, and
    `priority_score`, `recommended_method`, `approved_method`, `triage_reason`
    and `triaged_at` all null."

    PRD 3.1: "Scoring does not happen at intake — nothing is stamped on the
    request until a `ResearchLead` triages it."

    PRD 3.1: "Whichever outcome is chosen, the request's `priority_score` and
    `recommended_method` are recomputed against the current logical clock and
    stored, `triaged_at` is set to the clock instant, and `triage_reason` is set
    to the supplied `reason` (or to null when none was supplied)."

    Design: Corner/entities/request_creation_extra_priority_score_input_ignored
    """
    decision = create_decision(
        api,
        title="Guided setup",
        reversibility="IRREVERSIBLE",
        decision_deadline="2026-09-30T00:00:00Z",
        impacted_user_count=12000,
    )

    created = validate_success(
        api.create_research_request(
            {
                "roadmap_decision_id": decision["id"],
                "question": "What makes setup feel long?",
                "question_type": "DISCOVERY",
                "evidence_gap": "FULL",
                "priority_score": 99.99,
                "status": "APPROVED",
            },
            STAKEHOLDER_HEADERS,
        ),
        201,
    )
    assert created["priority_score"] is None, (
        f"Expected the client-supplied priority_score to be discarded at intake, "
        f"got {created['priority_score']!r}"
    )
    assert created["status"] == "SUBMITTED", (
        f"Expected the client-supplied status to be discarded and the request to land "
        f"SUBMITTED, got {created['status']}"
    )

    triaged = validate_success(
        api.triage_research_request(
            created["id"], triage_payload("APPROVED"), RESEARCH_LEAD_HEADERS
        )
    )
    assert triaged["priority_score"] == pytest.approx(75.00, abs=0.01), (
        f"Expected 40.00 IRREVERSIBLE plus 25.00 FULL plus 10.00 reach at an urgency "
        f"multiplier of 1.00, got {triaged['priority_score']}"
    )
    assert triaged["recommended_method"] == "INTERVIEW", (
        f"Expected a DISCOVERY question to recommend INTERVIEW, "
        f"got {triaged['recommended_method']!r}"
    )
    assert triaged["approved_method"] == "INTERVIEW", (
        f"Expected approved_method to take the freshly computed recommendation, "
        f"got {triaged['approved_method']!r}"
    )
    assert triaged["triaged_at"] == STARTUP_INSTANT, (
        f"Expected triaged_at to be set to the current clock instant, "
        f"got {triaged['triaged_at']!r}"
    )
    assert triaged["version"] == 2, (
        f"Expected the single triage mutation to take version to 2, "
        f"got {triaged['version']}"
    )


# ===========================================================================
# The question-type to method decision table
# ===========================================================================
@pytest.mark.parametrize(
    "question_type,impacted_user_count,expected_method",
    [
        ("DISCOVERY", 4000, "INTERVIEW"),
        ("EVALUATIVE", 4000, "USABILITY_TEST"),
        ("BEHAVIORAL_LONGITUDINAL", 4000, "DIARY_STUDY"),
        ("MEASUREMENT", 4000, "INTERVIEW"),
        ("MEASUREMENT", 5000, "SURVEY"),
    ],
)
def test_method_recommendation_maps_each_question_type(
    api, question_type, impacted_user_count, expected_method
):
    """Each question type maps to its one method, and only a MEASUREMENT question
    strictly below 5,000 impacted users is downgraded — exactly 5,000 still surveys.

    PRD 3.1: "The **method recommendation** runs in the same triage call and is a
    small decision table over `question_type`: a `DISCOVERY` question recommends
    `INTERVIEW`, an `EVALUATIVE` question recommends `USABILITY_TEST`, a
    `BEHAVIORAL_LONGITUDINAL` question recommends `DIARY_STUDY`, and a
    `MEASUREMENT` question recommends `SURVEY`."

    PRD 3.1: "One override exists, because a measurement question over too small
    an audience is statistically under-powered: when `question_type` is
    `MEASUREMENT` **and** the referenced decision's `impacted_user_count` is
    below 5,000, the recommendation is downgraded to `INTERVIEW` instead."

    PRD 3.1: "On the `SUBMITTED → APPROVED` transition, and only there,
    `approved_method` is stamped: it takes the value of `method_override` when
    triage supplied one, and otherwise the freshly computed
    `recommended_method`."

    Design: Corner/calculations/method_recommendation_maps_each_question_type
    """
    decision = create_decision(
        api,
        title=f"Method table {question_type} {impacted_user_count}",
        reversibility="REVERSIBLE",
        decision_deadline="2026-10-01T00:00:00Z",
        impacted_user_count=impacted_user_count,
    )
    request = create_request(
        decision["id"],
        api,
        question="Which step of the checklist do users abandon?",
        question_type=question_type,
        evidence_gap="PARTIAL",
    )

    triaged = validate_success(
        api.triage_research_request(
            request["id"], triage_payload("APPROVED"), RESEARCH_LEAD_HEADERS
        )
    )

    assert triaged["recommended_method"] == expected_method, (
        f"Expected a {question_type} question over {impacted_user_count} impacted "
        f"users to recommend {expected_method}, got {triaged['recommended_method']!r}"
    )
    assert triaged["approved_method"] == expected_method, (
        f"Expected approved_method to take the freshly computed recommendation "
        f"{expected_method} when no method_override was supplied, "
        f"got {triaged['approved_method']!r}"
    )
    assert triaged["status"] == "APPROVED", (
        f"Expected the request to reach APPROVED, got {triaged['status']}"
    )
    assert triaged["priority_score"] == pytest.approx(39.00, abs=0.01), (
        f"Expected 22.00 REVERSIBLE plus 12.00 PARTIAL plus one 5.00 reach bucket at "
        f"an urgency multiplier of 1.00, got {triaged['priority_score']}"
    )


def test_a_method_override_does_not_rewrite_the_recommendation(api):
    """A supplied `method_override` lands only in `approved_method`; the recommended
    method stays whatever the question type maps to.

    PRD 3.1: "The **method recommendation** runs in the same triage call and is a
    small decision table over `question_type`: a `DISCOVERY` question recommends
    `INTERVIEW`, an `EVALUATIVE` question recommends `USABILITY_TEST`, a
    `BEHAVIORAL_LONGITUDINAL` question recommends `DIARY_STUDY`, and a
    `MEASUREMENT` question recommends `SURVEY`."

    PRD 3.1: "On the `SUBMITTED → APPROVED` transition, and only there,
    `approved_method` is stamped: it takes the value of `method_override` when
    triage supplied one, and otherwise the freshly computed
    `recommended_method`."

    Design: Corner/calculations/method_recommendation_maps_each_question_type
    """
    decision = create_decision(
        api,
        title="Override the recommendation",
        reversibility="REVERSIBLE",
        decision_deadline="2026-10-01T00:00:00Z",
        impacted_user_count=4000,
    )
    request = create_request(
        decision["id"],
        api,
        question="Which step of the checklist do users abandon?",
        question_type="DISCOVERY",
        evidence_gap="PARTIAL",
    )

    triaged = validate_success(
        api.triage_research_request(
            request["id"],
            triage_payload(
                "APPROVED",
                reason="Prototype is already in hand",
                method_override="USABILITY_TEST",
            ),
            RESEARCH_LEAD_HEADERS,
        )
    )

    assert triaged["recommended_method"] == "INTERVIEW", (
        f"Expected the DISCOVERY row of the table to stand regardless of the "
        f"override, got {triaged['recommended_method']!r}"
    )
    assert triaged["approved_method"] == "USABILITY_TEST", (
        f"Expected approved_method to take the supplied method_override, "
        f"got {triaged['approved_method']!r}"
    )
    assert triaged["triage_reason"] == "Prototype is already in hand", (
        f"Expected the supplied reason to land in triage_reason, "
        f"got {triaged['triage_reason']!r}"
    )


# ===========================================================================
# The numeric gate on locking, and the ownership gate on reframing
# ===========================================================================
def test_locking_a_decision_without_accepted_readouts_is_rejected(api):
    """With no accepted readouts the recomputed confidence is 0.00, so the lock is
    refused and the decision stays open.

    PRD 3.1: "On the `OPEN → LOCKED` transition the decision's
    `evidence_confidence` is recomputed from its accepted readouts (the rule is
    spelled out in §3.8) and stored, and the transition is permitted only when
    that recomputed confidence is **at least 0.60**; below that bar the request
    is refused with `ERR_CONFIDENCE_BELOW_LOCK_THRESHOLD`."

    PRD 3.8: "**Decision confidence is an aggregation over accepted readouts
    only.** Readouts in `DRAFT`, `SUPERSEDED`, `DELIVERED` or `DEFERRED`
    contribute nothing at all."

    PRD 3.1: "On success `locked_at` is set to the current logical clock
    instant."

    Design: Corner/validations/locking_a_decision_without_accepted_readouts_is_rejected
    """
    decision = create_decision(
        api,
        title="Lock with nothing behind it",
        reversibility="IRREVERSIBLE",
        decision_deadline="2026-10-01T00:00:00Z",
        impacted_user_count=12000,
    )

    validate_error(
        api.lock_roadmap_decision(decision["id"], STAKEHOLDER_HEADERS),
        "ERR_CONFIDENCE_BELOW_LOCK_THRESHOLD",
    )

    after = validate_success(
        api.get_roadmap_decision(decision["id"], STAKEHOLDER_HEADERS)
    )
    assert after["status"] == "OPEN", (
        f"Expected the refused lock to leave the decision OPEN, got {after['status']}"
    )
    assert after["evidence_confidence"] == pytest.approx(0.00, abs=0.01), (
        f"Expected a decision with no accepted readouts to hold confidence 0.00, "
        f"got {after['evidence_confidence']}"
    )
    assert after["locked_at"] is None, (
        f"Expected locked_at to stay null when the lock was refused, "
        f"got {after['locked_at']!r}"
    )


def test_resubmit_by_a_non_owner_is_rejected(api):
    """Reframing belongs to the recorded requester: another stakeholder and an
    authorised researcher are both refused, and the requester then succeeds.

    PRD 3.1: "Reframing is the requester's move, not the lead's."

    PRD 3.1: "Anyone other than the recorded requester attempting a resubmit is
    refused with `ERR_OWNERSHIP_REQUIRED`."

    PRD 3.1: "All three submitted values overwrite the stored ones verbatim,
    `revision_round` is incremented by 1, and `priority_score`,
    `recommended_method` and `approved_method` are all cleared back to null so
    that nothing stale survives the loop."

    Design: Corner/errors/resubmit_by_a_non_owner_is_rejected
    """
    ctx = setup_request_needing_reframing(api)
    request_id = ctx["request"]["id"]
    assert ctx["request"]["requester_user_id"] == "u_stake_1", (
        f"Expected the reframing request to be owned by u_stake_1, "
        f"got {ctx['request']['requester_user_id']!r}"
    )

    payload = resubmit_research_request_payload(
        question="Which inbox filters do power users rebuild every Monday?",
        question_type="BEHAVIORAL_LONGITUDINAL",
        evidence_gap="PARTIAL",
    )

    validate_error(
        api.resubmit_research_request(request_id, payload, OTHER_STAKEHOLDER_HEADERS),
        "ERR_OWNERSHIP_REQUIRED",
    )
    validate_error(
        api.resubmit_research_request(request_id, payload, RESEARCHER_HEADERS),
        "ERR_OWNERSHIP_REQUIRED",
    )

    untouched = read_request(request_id, api)
    assert untouched["status"] == "NEEDS_REFRAMING", (
        f"Expected the refused resubmits to leave the request NEEDS_REFRAMING, "
        f"got {untouched['status']}"
    )
    assert untouched["revision_round"] == 0, (
        f"Expected revision_round to stay at 0 after two refused resubmits, "
        f"got {untouched['revision_round']}"
    )
    assert untouched["question"] == ctx["request"]["question"], (
        f"Expected the stored question to be untouched by the refused resubmits, "
        f"got {untouched['question']!r}"
    )

    reframed = validate_success(
        api.resubmit_research_request(request_id, payload, STAKEHOLDER_HEADERS)
    )
    assert reframed["status"] == "SUBMITTED", (
        f"Expected the requester's resubmit to carry the request back to SUBMITTED, "
        f"got {reframed['status']}"
    )
    assert reframed["revision_round"] == 1, (
        f"Expected revision_round to increment to 1, got {reframed['revision_round']}"
    )
    assert (
        reframed["question"] == "Which inbox filters do power users rebuild every Monday?"
    ), f"Expected the fresh question to overwrite the stored one, got {reframed['question']!r}"
    assert reframed["question_type"] == "BEHAVIORAL_LONGITUDINAL", (
        f"Expected the fresh question_type to overwrite the stored one, "
        f"got {reframed['question_type']!r}"
    )
    assert reframed["evidence_gap"] == "PARTIAL", (
        f"Expected the fresh evidence_gap to overwrite the stored one, "
        f"got {reframed['evidence_gap']!r}"
    )
    for field in ("priority_score", "recommended_method", "approved_method"):
        assert reframed[field] is None, (
            f"Expected {field} to be cleared back to null by the resubmit, "
            f"got {reframed[field]!r}"
        )
