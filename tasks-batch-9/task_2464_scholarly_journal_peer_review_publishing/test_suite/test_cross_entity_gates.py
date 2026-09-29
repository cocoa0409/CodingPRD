"""Gates a manuscript cannot open by itself: a sibling invoice and an open ethics case."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import ApiErrorId
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import PRODUCTION_STAFF_HEADERS, api_client
from test_helpers.constants import CLOCK_EPOCH_MS

PUBLICATION_DATE = "2026-09-10"


def _publication_request(job_id):
    return api_client.publish_article(
        job_id,
        f.publication_payload(PUBLICATION_DATE, issue_label="Vol 1 Issue 1"),
        PRODUCTION_STAFF_HEADERS,
    )


def _decision_request(manuscript_id, handling_headers, note):
    return api_client.create_decision(
        manuscript_id, f.decision_payload(editorial_note=note), handling_headers
    )


def test_second_issued_invoice_blocks_an_otherwise_ready_publication():
    """Both dimensions have landed, so the only thing left to refuse is the open invoice.

    PRD: "It further requires that the manuscript carry no invoice still at status `ISSUED`, an outstanding invoice being refused with `ERR_UNPAID_APC_INVOICE`, and that the manuscript carry no unresolved ethics case of any severity in state `OPEN`, `INVESTIGATION`, `AUTHOR_RESPONSE_REQUESTED` or `COMMITTEE_REVIEW`, an open case being refused with `ERR_ETHICS_HOLD`."

    Design: Difficulty/cross_entity_state_dependency/publication_blocked_by_second_issued_invoice_then_allowed_after_waiver
    """
    world = fx.setup_second_issued_invoice_before_publication()
    a.assert_production_stages(world["job"], "PROOF_APPROVED", "DEPOSIT_CONFIRMED")

    response = _publication_request(world["job"]["id"])

    validate_error(response, ApiErrorId.ERR_UNPAID_APC_INVOICE.value, expected_status=409)
    manuscript = fx.get_manuscript(world["manuscript"]["id"])
    assert manuscript["status"] == "IN_PRODUCTION"
    assert manuscript.get("doi") is None


def test_waiving_the_second_invoice_lets_the_identical_request_through():
    """Settling the sibling row is the only change, and the same call now succeeds.

    PRD: "Where several invoices were issued for one manuscript, that condition is what makes the last settlement the one that clears the fees."

    Design: Difficulty/cross_entity_state_dependency/publication_blocked_by_second_issued_invoice_then_allowed_after_waiver
    """
    world = fx.setup_second_issued_invoice_before_publication()
    _publication_request(world["job"]["id"])

    fx.waive_invoice(
        world["second_invoice"]["id"],
        waiver_reason="Duplicate invoice waived by the publisher",
    )
    validate_success(_publication_request(world["job"]["id"]))

    manuscript = fx.get_manuscript(world["manuscript"]["id"])
    a.assert_fields(
        manuscript,
        status="PUBLISHED",
        publication_date=PUBLICATION_DATE,
        embargo_end_date=PUBLICATION_DATE,
    )


def test_waiver_moves_the_ledgers_while_the_clearance_dimension_stands_still():
    """The waiver settles the second row without disturbing a clearance stage already past it.

    PRD: "For any `CC_BY`, `CC_BY_NC` or `CC_BY_NC_ND` manuscript, access is immediate and `embargo_end_date` simply equals `publication_date`."

    Design: Difficulty/cross_entity_state_dependency/publication_blocked_by_second_issued_invoice_then_allowed_after_waiver
    """
    world = fx.setup_second_issued_invoice_before_publication()

    fx.waive_invoice(
        world["second_invoice"]["id"],
        waiver_reason="Duplicate invoice waived by the publisher",
    )
    validate_success(_publication_request(world["job"]["id"]))

    assert fx.get_invoice(world["invoice"]["id"])["status"] == "PAID"
    assert fx.get_invoice(world["second_invoice"]["id"])["status"] == "WAIVED"

    job = fx.get_production_job(world["job"]["id"])
    a.assert_production_stages(job, "PROOF_APPROVED", "DEPOSIT_CONFIRMED")
    a.assert_fields(job, indexing_status="INDEXED", published_at="2026-09-10T00:00:00.000Z")

    journal = fx.get_journal(world["journal"]["id"])
    assert journal["published_article_count"] == 1
    a.assert_journal_ledgers(
        journal, apc_receivable_cents=0, apc_waived_cents=180000
    )


def test_open_high_severity_case_freezes_decision_issuance():
    """A row on another entity refuses a decision the manuscript is otherwise ready for.

    PRD: "An unresolved case of severity `HIGH` — unresolved meaning its state is `OPEN`, `INVESTIGATION`, `AUTHOR_RESPONSE_REQUESTED` or `COMMITTEE_REVIEW` — freezes exactly three operations on its manuscript: decision issuance, invoice issuance and publication."

    Design: Difficulty/cross_entity_state_dependency/decision_blocked_by_open_high_severity_ethics_case
    """
    world = fx.setup_ethics_hold_on_decision()
    a.assert_fields(world["ethics_case"], state="OPEN", severity="HIGH")

    response = _decision_request(
        world["manuscript"]["id"],
        world["handling_headers"],
        "Attempted decision while the ethics case is open",
    )

    validate_error(response, ApiErrorId.ERR_ETHICS_HOLD.value, expected_status=409)
    manuscript = fx.get_manuscript(world["manuscript"]["id"])
    a.assert_fields(manuscript, status="DECISION_PENDING", decision_count=0)


def test_resolving_the_case_with_no_action_lifts_the_hold():
    """Closing the case releases the frozen operation without touching the manuscript.

    PRD: "`NO_ACTION` moves the case `COMMITTEE_REVIEW → RESOLVED_NO_ACTION` and leaves the manuscript's status untouched."

    Design: Difficulty/cross_entity_state_dependency/decision_blocked_by_open_high_severity_ethics_case
    """
    world = fx.setup_ethics_hold_on_decision()
    case_id = world["ethics_case"]["id"]
    _decision_request(
        world["manuscript"]["id"],
        world["handling_headers"],
        "Attempted decision while the ethics case is open",
    )

    fx.advance_case_to_committee_review(case_id, world["chief_headers"])
    fx.resolve_ethics_case(
        case_id,
        world["second_chief_headers"],
        "NO_ACTION",
        resolution_statement="Authorship order confirmed as submitted",
    )

    case = fx.get_ethics_case(case_id)
    a.assert_fields(case, state="RESOLVED_NO_ACTION", resolved_at=CLOCK_EPOCH_MS)
    assert fx.get_manuscript(world["manuscript"]["id"])["status"] == "DECISION_PENDING"


def test_released_hold_lets_the_manuscript_leave_decision_pending():
    """The retried decision is computed exactly as it would have been before the freeze.

    PRD: "Its practical effect is release: because the case is no longer unresolved, a `HIGH`-severity hold lifts and decisions, invoicing and publication become possible again."

    Design: Difficulty/cross_entity_state_dependency/decision_blocked_by_open_high_severity_ethics_case
    """
    world = fx.setup_ethics_hold_on_decision()
    case_id = world["ethics_case"]["id"]
    _decision_request(
        world["manuscript"]["id"],
        world["handling_headers"],
        "Attempted decision while the ethics case is open",
    )
    fx.advance_case_to_committee_review(case_id, world["chief_headers"])
    fx.resolve_ethics_case(
        case_id,
        world["second_chief_headers"],
        "NO_ACTION",
        resolution_statement="Authorship order confirmed as submitted",
    )

    decision = fx.issue_decision(
        world["manuscript"]["id"],
        world["handling_headers"],
        editorial_note="Minor revision requested after the ethics case closed",
    )

    a.assert_fields(decision, auto_category="MINOR_REVISION")
    a.assert_score_equals(decision["consensus_index"], 3.00, "consensus_index")
    manuscript = fx.get_manuscript(world["manuscript"]["id"])
    a.assert_fields(manuscript, status="REVISION_REQUESTED", decision_count=1)
