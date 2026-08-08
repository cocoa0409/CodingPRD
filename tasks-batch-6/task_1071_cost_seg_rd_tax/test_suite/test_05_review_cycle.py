"""Submit / reject / re-submit review cycle, report revision loop, and submit-review guards.

Translates queue A (non_linear_state_machine, boundary submit-review empty set,
priority_pair_validation_conflict) and queue B (no-qualified-QRE) instances.
"""
from test_helpers import validate_success, validate_error, get_success_data, ApiErrorId, TEST_USERS, fixtures
import test_helpers.factories as f

SM = TEST_USERS["study_manager_headers"]


def _submitted_cost_seg(api):
    """Cost-seg study in IN_REVIEW with a reviewer available (one ALLOCATED FIVE_YEAR comp)."""
    ctx = fixtures.setup_cost_seg_engineering(api, with_reviewer=True)
    fixtures.add_allocated_components(api, ctx, [("5yr", "FIVE_YEAR", 10000000)])
    fixtures.submit(api, ctx)
    return ctx


# ---------------------------------------------------------------------------
# Difficulty/non_linear_state_machine/study_review_engineering_cycle
# ---------------------------------------------------------------------------
def test_study_returns_to_engineering_on_reject(api):
    """PRD §3.5: "Rejecting sends the study back from `IN_REVIEW` to `ENGINEERING` for more
    work, may carry a free-text `review_note`, and moves the study's report from `DRAFT` to
    `REVISION_REQUESTED`."

    Design: Difficulty/non_linear_state_machine/study_review_engineering_cycle
    """
    ctx = _submitted_cost_seg(api)
    data = validate_success(api.reject_study(ctx["study_id"], ctx["rev_headers"], {"review_note": "revise"}), 200)
    assert data["status"] == "ENGINEERING"


def test_study_cycles_back_to_in_review_on_resubmit(api):
    """PRD §3.5: "the study can then be resubmitted, which returns the report to DRAFT and bumps
    its revision_count, closing the IN_REVIEW ↔ ENGINEERING loop."

    Design: Difficulty/non_linear_state_machine/study_review_engineering_cycle
    """
    ctx = _submitted_cost_seg(api)
    fixtures.reject(api, ctx, note="revise")
    data = validate_success(api.submit_review(ctx["study_id"], ctx["eng_headers"]), 200)
    assert data["status"] == "IN_REVIEW"


# ---------------------------------------------------------------------------
# Difficulty/non_linear_state_machine/report_revision_request_draft_loop
# ---------------------------------------------------------------------------
def test_report_enters_revision_requested_on_reject(api):
    """PRD §3.5: "Rejecting sends the study back from `IN_REVIEW` to `ENGINEERING` for more
    work, may carry a free-text `review_note`, and moves the study's report from `DRAFT` to
    `REVISION_REQUESTED`."

    Design: Difficulty/non_linear_state_machine/report_revision_request_draft_loop
    """
    ctx = _submitted_cost_seg(api)
    fixtures.reject(api, ctx)
    report = fixtures.only_report(api, ctx)
    assert report is not None
    assert report["status"] == "REVISION_REQUESTED"


def test_report_returns_to_draft_and_bumps_revision_count(api):
    """PRD §3.5: "If instead a report already exists and sits in REVISION_REQUESTED, the
    submission moves that report from REVISION_REQUESTED back to DRAFT and increments its
    revision_count by one — this is the revision loop."

    Design: Difficulty/non_linear_state_machine/report_revision_request_draft_loop
    """
    ctx = _submitted_cost_seg(api)
    fixtures.reject(api, ctx)
    fixtures.submit(api, ctx)
    report = fixtures.only_report(api, ctx)
    assert report["status"] == "DRAFT"
    assert report["revision_count"] == 1


# ---------------------------------------------------------------------------
# Difficulty/boundary_precision_check/submit_review_empty_allocated_set
# ---------------------------------------------------------------------------
def test_submit_review_with_no_allocated_components_rejected(api):
    """PRD §3.5: "a cost-segregation study needs at least one ALLOCATED component, failing
    which the submission is rejected with ERR_NO_ALLOCATED_COMPONENTS."

    Design: Difficulty/boundary_precision_check/submit_review_empty_allocated_set
    """
    ctx = fixtures.setup_cost_seg_engineering(api)
    resp = api.submit_review(ctx["study_id"], ctx["eng_headers"])
    validate_error(resp, ApiErrorId.ERR_NO_ALLOCATED_COMPONENTS.value)


def test_submit_review_with_only_proposed_component_rejected(api):
    """PRD §3.5: "a cost-segregation study needs at least one ALLOCATED component, failing
    which the submission is rejected with ERR_NO_ALLOCATED_COMPONENTS."

    A PROPOSED (never allocated) component does not satisfy the non-empty ALLOCATED set.

    Design: Difficulty/boundary_precision_check/submit_review_empty_allocated_set
    """
    ctx = fixtures.setup_cost_seg_engineering(api)
    fixtures.add_component(api, ctx, "5yr", "FIVE_YEAR", 10000000, allocate=False)
    resp = api.submit_review(ctx["study_id"], ctx["eng_headers"])
    validate_error(resp, ApiErrorId.ERR_NO_ALLOCATED_COMPONENTS.value)


# ---------------------------------------------------------------------------
# Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_submit_review
# ---------------------------------------------------------------------------
def test_submit_review_in_scoping_state_beats_fiscal(api):
    """PRD §2.1: "then whether the target resource is in a state from which the requested
    transition is legal (ERR_INVALID_STATE), then segregation of duties, then study-type
    applicability, then numeric-range checks on the body, then the temporal and overlap
    checks, then the fiscal checks ... the earlier-priority failure is the one surfaced."

    A study in SCOPING (not ENGINEERING) with zero ALLOCATED components fails both the state
    check and the fiscal empty-set check; the state error wins.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_submit_review
    """
    cli = fixtures.create_client(api)
    eng = fixtures.create_engineer(api)
    prop = fixtures.create_property(api, cli["id"])
    st = fixtures.create_study(api, cli["id"], "COST_SEGREGATION", tax_year=2024)
    get_success_data(api.scope_study(st["id"], f.scope_cost_seg_payload(prop["id"]), SM))  # SCOPING
    from test_helpers import make_engineer_headers
    resp = api.submit_review(st["id"], make_engineer_headers(eng["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_submit_review_in_draft_state_beats_fiscal(api):
    """PRD §2.1: "then whether the target resource is in a state from which the requested
    transition is legal (ERR_INVALID_STATE) ... then the fiscal checks ... the earlier-priority
    failure is the one surfaced."

    A study still in DRAFT (never scoped/assigned, no components) also fails both state and
    fiscal; the state error again wins over the empty-set fiscal check.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_submit_review
    """
    cli = fixtures.create_client(api)
    eng = fixtures.create_engineer(api)
    st = fixtures.create_study(api, cli["id"], "COST_SEGREGATION", tax_year=2024)  # DRAFT
    from test_helpers import make_engineer_headers
    resp = api.submit_review(st["id"], make_engineer_headers(eng["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ---------------------------------------------------------------------------
# Difficulty/priority_pair_validation_conflict/referential_beats_constraint_on_add_component
# ---------------------------------------------------------------------------
def test_add_component_to_rd_study_type_beats_amount(api):
    """PRD §3.3: "Adding a component to a study whose study_type is not COST_SEGREGATION is
    rejected with ERR_STUDY_TYPE_MISMATCH."
    PRD §2.1: "then study-type applicability, then numeric-range checks on the body ... the
    earlier-priority failure is the one surfaced."

    An AssetComponent with allocated_cost_cents 0 on an RD_CREDIT study fails both the type
    check and the amount check; the study-type error wins.

    Design: Difficulty/priority_pair_validation_conflict/referential_beats_constraint_on_add_component
    """
    cli = fixtures.create_client(api)
    eng = fixtures.create_engineer(api)
    st = fixtures.create_study(api, cli["id"], "RD_CREDIT", tax_year=2024)
    from test_helpers import make_engineer_headers
    resp = api.add_asset_component(
        st["id"], {"component_name": "bad", "asset_class": "FIVE_YEAR", "allocated_cost_cents": 0},
        make_engineer_headers(eng["id"]))
    validate_error(resp, ApiErrorId.ERR_STUDY_TYPE_MISMATCH.value)


def test_add_qre_line_to_cost_seg_study_type_mismatch(api):
    """PRD §3.4: "Adding a line to a study whose `study_type` is not `RD_CREDIT` is rejected
    with `ERR_STUDY_TYPE_MISMATCH`."

    The mirror of the referential type check: a QRE line on a COST_SEGREGATION study.

    Design: Difficulty/priority_pair_validation_conflict/referential_beats_constraint_on_add_component
    """
    cli = fixtures.create_client(api)
    eng = fixtures.create_engineer(api)
    st = fixtures.create_study(api, cli["id"], "COST_SEGREGATION", tax_year=2024)
    from test_helpers import make_engineer_headers
    resp = api.add_qre_line_item(
        st["id"], f.qre_line_payload("WAGES", 5000000, 0.80), make_engineer_headers(eng["id"]))
    validate_error(resp, ApiErrorId.ERR_STUDY_TYPE_MISMATCH.value)


# ---------------------------------------------------------------------------
# Corner/validations/rd_submit_review_no_qualified_qre_rejected
# ---------------------------------------------------------------------------
def test_rd_submit_review_no_qualified_qre_rejected(api):
    """PRD §3.5: "an R&D study needs at least one `QUALIFIED` line, failing which it is
    rejected with `ERR_NO_QUALIFIED_QRE`."

    Design: Corner/validations/rd_submit_review_no_qualified_qre_rejected
    """
    ctx = fixtures.setup_rd_engineering(api, credit_method="ASC", tax_year=2024)
    # add a DRAFT line but do not qualify it
    get_success_data(api.add_qre_line_item(
        ctx["study_id"], f.qre_line_payload("WAGES", 5000000, 0.80), ctx["eng_headers"]))
    resp = api.submit_review(ctx["study_id"], ctx["eng_headers"])
    validate_error(resp, ApiErrorId.ERR_NO_QUALIFIED_QRE.value)
