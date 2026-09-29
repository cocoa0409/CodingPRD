"""Two simultaneous violations, one reported error: the rejection ladder decides which."""

from prd_bench_local_runner.testing import validate_error

from test_helpers import ApiErrorId
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import PRODUCTION_STAFF_HEADERS, api_client


def _attempt_publication(job_id):
    return api_client.publish_article(
        job_id,
        f.publication_payload("2026-09-10", issue_label="Vol 1 Issue 1"),
        PRODUCTION_STAFF_HEADERS,
    )


def _attempt_advance_to_review(manuscript_id, handling_headers):
    return api_client.screening_decision(
        manuscript_id,
        f.screening_decision_payload(
            "ADVANCE_TO_REVIEW", note="Attempting to advance despite both defects"
        ),
        handling_headers,
    )


def test_publication_reports_the_stage_gate_and_not_the_unpaid_invoice():
    """The higher rung of the ladder wins even though both rules are violated.

    PRD: "When a single request violates more than one rule, exactly one error is returned: the one belonging to the **highest-priority** violated rule."

    Design: Difficulty/priority_pair_validation_conflict/publication_stage_gate_outranks_unpaid_apc_invoice
    """
    world = fx.setup_stage_gate_blocked_publication()

    response = _attempt_publication(world["job"]["id"])

    error = validate_error(
        response, ApiErrorId.ERR_PRODUCTION_STAGE_NOT_READY.value, expected_status=409
    )
    assert error["error_id"] != ApiErrorId.ERR_UNPAID_APC_INVOICE.value, (
        "the unpaid invoice is a lower-priority violation and must not be reported"
    )


def test_unpaid_invoice_survives_the_refusal_unreported():
    """The lower-priority fiscal violation is still there, and was never named.

    PRD: "Publication requires that the manuscript carry no invoice still in status `ISSUED` — otherwise `ERR_UNPAID_APC_INVOICE` (409)."

    Design: Difficulty/priority_pair_validation_conflict/publication_stage_gate_outranks_unpaid_apc_invoice
    """
    world = fx.setup_stage_gate_blocked_publication()

    _attempt_publication(world["job"]["id"])

    invoice = fx.get_invoice(world["invoice"]["id"])
    a.assert_fields(invoice, status="ISSUED")
    a.assert_invoice_amounts(invoice, total_due_cents=180000)


def test_refused_publication_leaves_the_job_and_manuscript_untouched():
    """Nothing about the two production dimensions moved.

    PRD: "Publication is the **join** of the two dimensions, and the only operation that reads both."

    Design: Difficulty/priority_pair_validation_conflict/publication_stage_gate_outranks_unpaid_apc_invoice
    """
    world = fx.setup_stage_gate_blocked_publication()

    _attempt_publication(world["job"]["id"])

    job = fx.get_production_job(world["job"]["id"])
    a.assert_production_stages(job, "TYPESETTING", "LICENSE_PENDING")
    assert job["indexing_status"] == "NOT_INDEXED"
    manuscript = fx.get_manuscript(world["manuscript"]["id"])
    assert manuscript["status"] == "IN_PRODUCTION"
    assert manuscript.get("doi") is None


def test_screening_decision_reports_the_integrity_block_over_the_formatting_defect():
    """Rung 16 is evaluated before rung 18, so the block is the only error named.

    PRD: "Evaluation stops at the first violation."

    Design: Difficulty/priority_pair_validation_conflict/integrity_block_outranks_formatting_non_compliance
    """
    world = fx.setup_blocked_and_non_compliant_manuscript()

    response = _attempt_advance_to_review(
        world["manuscript"]["id"], world["handling_headers"]
    )

    error = validate_error(
        response, ApiErrorId.ERR_INTEGRITY_BLOCK.value, expected_status=409
    )
    assert error["error_id"] != ApiErrorId.ERR_FORMATTING_NON_COMPLIANT.value, (
        "the formatting defect is a lower-priority violation and must not be reported"
    )


def test_formatting_non_compliance_remains_present_and_unreported():
    """Both defects sit on the manuscript; only one of them was answered.

    PRD: "A manuscript advancing to review has `formatting_status` `COMPLIANT` — otherwise `ERR_FORMATTING_NON_COMPLIANT` (409), on the screening decision."

    Design: Difficulty/priority_pair_validation_conflict/integrity_block_outranks_formatting_non_compliance
    """
    world = fx.setup_blocked_and_non_compliant_manuscript()

    _attempt_advance_to_review(world["manuscript"]["id"], world["handling_headers"])

    manuscript = fx.get_manuscript(world["manuscript"]["id"])
    a.assert_fields(
        manuscript, integrity_status="BLOCK", formatting_status="NON_COMPLIANT"
    )


def test_blocked_manuscript_stays_at_submitted():
    """The refusal writes nothing: the paper is still awaiting a way forward.

    PRD: "It additionally requires that the manuscript's `integrity_status` is either `PASS` or `FLAG` — a `BLOCK` rollup is refused with `ERR_INTEGRITY_BLOCK`, and the only ways forward from there are a desk rejection or an ethics case resolved in the manuscript's favour; that the manuscript's `formatting_status` is `COMPLIANT`, a `NON_COMPLIANT` manuscript being refused with `ERR_FORMATTING_NON_COMPLIANT`; and that the manuscript's `subject_area` is a member of the journal's `subject_areas`, an out-of-scope paper being refused with `ERR_SUBJECT_AREA_OUT_OF_SCOPE`."

    Design: Difficulty/priority_pair_validation_conflict/integrity_block_outranks_formatting_non_compliance
    """
    world = fx.setup_blocked_and_non_compliant_manuscript()

    _attempt_advance_to_review(world["manuscript"]["id"], world["handling_headers"])

    assert fx.get_manuscript(world["manuscript"]["id"])["status"] == "SUBMITTED"
    a.assert_fields(world["screening"], round=0, verdict="BLOCK")
