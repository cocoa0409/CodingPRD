"""Decision-time gates read live configuration, and ethics resolutions read live status."""

from prd_bench_local_runner.testing import validate_error, validate_paginated

from test_helpers import ApiErrorId
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import SYSTEM_ADMIN_HEADERS, api_client


def _decision_request(manuscript_id, handling_headers):
    return api_client.create_decision(
        manuscript_id, f.decision_payload(), handling_headers
    )


def _appeal_request(decision_id, author_headers):
    return api_client.create_appeal(f.appeal_payload(decision_id), author_headers)


def _correction_request(case_id, chief_headers):
    return api_client.resolve_ethics_case(
        case_id,
        f.ethics_case_resolution_payload(
            "CORRECTION",
            resolution_statement="The committee asked for a correction notice.",
        ),
        chief_headers,
    )


def _count_rows(response):
    rows, meta = validate_paginated(response)
    assert len(rows) == meta["total_count"], "the whole set fits in one page"
    return meta["total_count"]


def _setup_threshold_raised_after_decision_pending():
    """One review met a threshold of one; the journal then asks for two."""
    world = fx.setup_decision_pending(
        recommendations=("ACCEPT",),
        journal_overrides={"min_completed_reviews_for_decision": 1},
    )
    world["journal"] = fx.update_journal(
        world["journal"]["id"], min_completed_reviews_for_decision=2
    )
    return world


def _setup_committee_review_on_an_unpublished_manuscript():
    """An ethics case at `COMMITTEE_REVIEW` over a manuscript still in peer review."""
    world = fx.setup_under_review_manuscript()
    case = fx.open_ethics_case(
        world["manuscript"]["id"],
        SYSTEM_ADMIN_HEADERS,
        case_type="AUTHORSHIP_DISPUTE",
        severity="MEDIUM",
    )
    fx.advance_case_to_committee_review(case["id"], world["chief_headers"])
    world["case"] = fx.get_ethics_case(case["id"])
    return world


def test_threshold_raised_mid_flight_blocks_the_pending_decision():
    """The gate reads the journal now, not when the manuscript arrived at the gate.

    PRD: "Raising `min_completed_reviews_for_decision` after a manuscript has already reached `DECISION_PENDING` blocks that manuscript's decision until enough further reviews arrive, because the threshold is read at decision time rather than captured when the manuscript entered the state."

    Design: Corner/validations/decision_rejected_when_review_threshold_raised_mid_flight
    """
    world = _setup_threshold_raised_after_decision_pending()
    a.assert_fields(world["manuscript"], status="DECISION_PENDING")
    a.assert_fields(world["journal"], min_completed_reviews_for_decision=2)

    response = _decision_request(
        world["manuscript"]["id"], world["handling_headers"]
    )

    validate_error(
        response, ApiErrorId.ERR_INSUFFICIENT_REVIEWS.value, expected_status=409
    )


def test_blocked_decision_writes_no_decision_row():
    """The single delivered review is still the whole round, and nothing was decided.

    PRD: "The manuscript must be at `DECISION_PENDING`, the current round must hold at least the journal's `min_completed_reviews_for_decision` submitted reviews — fewer is refused with `ERR_INSUFFICIENT_REVIEWS` — and the manuscript must carry no unresolved `HIGH`-severity ethics case, which is refused with `ERR_ETHICS_HOLD`."

    Design: Corner/validations/decision_rejected_when_review_threshold_raised_mid_flight
    """
    world = _setup_threshold_raised_after_decision_pending()

    _decision_request(world["manuscript"]["id"], world["handling_headers"])

    manuscript = fx.get_manuscript(world["manuscript"]["id"])
    a.assert_fields(
        manuscript,
        status="DECISION_PENDING",
        submitted_review_count=1,
        decision_count=0,
    )
    assert manuscript.get("consensus_index_at_last_decision") is None
    assert (
        _count_rows(
            api_client.list_decisions(
                world["handling_headers"],
                params={"manuscript_id": world["manuscript"]["id"]},
            )
        )
        == 0
    )


def test_revision_decision_refused_when_the_journal_allows_no_rounds():
    """Round 0 is not strictly less than a ceiling of 0, so the revision cannot open.

    PRD: "A resolved category of `MINOR_REVISION` or `MAJOR_REVISION` moves the manuscript `DECISION_PENDING → REVISION_REQUESTED`, but only while its `revision_round` is strictly less than the journal's `max_revision_rounds`; a revision decision that would open the round after the last permitted one is refused with `ERR_REVISION_LIMIT_REACHED`."

    Design: Corner/validations/revision_decision_rejected_when_no_revision_rounds_allowed
    """
    world = fx.setup_decision_pending(
        recommendations=("MAJOR_REVISION",),
        journal_overrides={
            "min_completed_reviews_for_decision": 1,
            "max_revision_rounds": 0,
        },
    )
    a.assert_fields(world["manuscript"], status="DECISION_PENDING", revision_round=0)

    response = _decision_request(
        world["manuscript"]["id"], world["handling_headers"]
    )

    validate_error(
        response, ApiErrorId.ERR_REVISION_LIMIT_REACHED.value, expected_status=409
    )


def test_refused_revision_decision_leaves_the_round_and_the_tally_alone():
    """No decision was recorded, so neither the count nor the consensus reading moved.

    PRD: "Regardless of category, the manuscript's `consensus_index_at_last_decision` is set to this decision's `consensus_index`, its `decision_count` rises by 1, and its `version` advances by 1."

    Design: Corner/validations/revision_decision_rejected_when_no_revision_rounds_allowed
    """
    world = fx.setup_decision_pending(
        recommendations=("MAJOR_REVISION",),
        journal_overrides={
            "min_completed_reviews_for_decision": 1,
            "max_revision_rounds": 0,
        },
    )

    _decision_request(world["manuscript"]["id"], world["handling_headers"])

    manuscript = fx.get_manuscript(world["manuscript"]["id"])
    a.assert_fields(
        manuscript, status="DECISION_PENDING", revision_round=0, decision_count=0
    )
    assert manuscript.get("consensus_index_at_last_decision") is None
    assert (
        _count_rows(
            api_client.list_decisions(
                world["handling_headers"],
                params={"manuscript_id": world["manuscript"]["id"]},
            )
        )
        == 0
    )


def test_appeal_on_the_thirty_first_day_is_out_of_time():
    """A rejection on 1 August cannot be appealed on 1 September.

    PRD: "An appeal is permitted only against the manuscript's **most recent** decision, only when that decision's `category` is `REJECT` or `REJECT_AND_RESUBMIT`, only within 30 days of that decision, and at most once per decision; a request that fails any of those four conditions is refused with `ERR_APPEAL_WINDOW_CLOSED`."

    Design: Corner/validations/appeal_rejected_thirty_one_days_after_the_rejection
    """
    world = fx.setup_rejected_manuscript()
    a.assert_fields(world["decision"], category="REJECT")
    fx.set_clock("2026-09-01T00:00:00Z")

    response = _appeal_request(world["decision"]["id"], world["author_headers"])

    validate_error(
        response, ApiErrorId.ERR_APPEAL_WINDOW_CLOSED.value, expected_status=409
    )


def test_out_of_time_appeal_leaves_the_manuscript_rejected():
    """No appeal row was filed and the rejection still stands.

    PRD: "Filing an appeal creates it at state `FILED`, copies the decision's manuscript into the appeal's `manuscript_id` for filtering, leaves `adjudicated_by_editor_id`, `rationale` and `adjudicated_at` absent, and moves the manuscript `REJECTED → UNDER_APPEAL`, advancing the manuscript's `version` by 1."

    Design: Corner/validations/appeal_rejected_thirty_one_days_after_the_rejection
    """
    world = fx.setup_rejected_manuscript()
    fx.set_clock("2026-09-01T00:00:00Z")

    _appeal_request(world["decision"]["id"], world["author_headers"])

    assert fx.get_manuscript(world["manuscript"]["id"])["status"] == "REJECTED"
    assert (
        _count_rows(
            api_client.list_appeals(
                world["chief_headers"],
                params={"decision_id": world["decision"]["id"]},
            )
        )
        == 0
    )


def test_correction_cannot_be_issued_against_an_unpublished_manuscript():
    """The committee may sit, but there is no published record to correct.

    PRD: "A correction requires the manuscript to be at `PUBLISHED`; requesting one against a manuscript in any other status is refused with `ERR_RETRACTION_NOT_SUPPORTED`."

    Design: Corner/validations/correction_resolution_rejected_on_unpublished_manuscript
    """
    world = _setup_committee_review_on_an_unpublished_manuscript()
    a.assert_fields(world["case"], state="COMMITTEE_REVIEW")
    assert fx.get_manuscript(world["manuscript"]["id"])["status"] == "UNDER_REVIEW"

    response = _correction_request(world["case"]["id"], world["chief_headers"])

    error = validate_error(
        response, ApiErrorId.ERR_RETRACTION_NOT_SUPPORTED.value, expected_status=409
    )
    assert error["error_id"] != ApiErrorId.ERR_INVALID_ETHICS_CASE_STATE.value, (
        "the case sits in the one state resolution is declared from"
    )


def test_refused_correction_resolves_nothing():
    """The case is still open business and the manuscript is untouched.

    PRD: "Every resolution sets `resolved_at` to the current clock instant, stores the `resolution_statement`, and raises the case's `version` by 1."

    Design: Corner/validations/correction_resolution_rejected_on_unpublished_manuscript
    """
    world = _setup_committee_review_on_an_unpublished_manuscript()

    _correction_request(world["case"]["id"], world["chief_headers"])

    case = fx.get_ethics_case(world["case"]["id"])
    a.assert_fields(case, state="COMMITTEE_REVIEW")
    assert case.get("resolved_at") is None
    assert case.get("resolution_statement") is None
    assert fx.get_manuscript(world["manuscript"]["id"])["status"] == "UNDER_REVIEW"
