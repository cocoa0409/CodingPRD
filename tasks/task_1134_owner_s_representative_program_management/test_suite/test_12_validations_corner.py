"""Queue B — validations section corner tests."""
from test_helpers import (
    api_client, validate_error, get_success_data,
    create_active_program, create_program,
    create_stakeholder_group,
    create_and_execute_contract, create_change_order, submit_change_order,
    recommend_change_order, decide_change_order,
    create_owner_report,
    create_baseline_payload, create_engagement_payload,
    pm_headers, owner_headers, build_user_headers, NON_EXISTENT_UUID,
    ApiErrorId,
)


def test_auth_missing_x_user_id_header_returns_400(api):
    """PRD §2.5 priority 1: "The X-User-Role and X-User-ID headers must both
    be present and non-empty, and the role must be declared; failures surface
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER (400)."

    Design: Corner/validations/auth_missing_x_user_id_header_returns_400
    """
    # Headers with only role set, no X-User-ID
    headers = {"X-User-Role": "OwnerRepPM"}
    resp = api_client.create_program(
        {"program_name": "P-AUTH", "owner_organization": "O"}, headers)
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


def test_existence_beats_state_on_charter_decide(api):
    """PRD §2.5: priority 4 (resource existence) precedes priority 5 (state).
    §2.10: "Existence failures surface the resource-specific 404 for the
    first identifier that cannot be resolved: ... ERR_CHARTER_NOT_FOUND ...".

    Design: Corner/validations/existence_beats_state_on_charter_decide
    """
    prog = create_program(name="P-EXI")
    pid = prog["id"]
    pv = get_success_data(api_client.get_program(pid, pm_headers()))["version"]
    resp = api_client.decide_charter(
        NON_EXISTENT_UUID,
        {"decision": "APPROVE", "expected_program_version": pv},
        owner_headers(),
    )
    validate_error(resp, ApiErrorId.ERR_CHARTER_NOT_FOUND)


def test_engagement_end_before_start_returns_400(api):
    """PRD §3.7: "The end must be strictly after the start, else
    ERR_INVALID_REQUEST".

    Design: Corner/validations/engagement_end_before_start_returns_400
    """
    prog = create_active_program(
        total_budget_cents=1_000_000, contingency_total_cents=100_000,
        lines=[{"cost_code": "CC-100", "amount_cents": 1_000_000}], name="P-SHAPE",
    )
    pid = prog["id"]
    g1 = create_stakeholder_group(pid, group_name="G1", contact_email="g1@x.com")
    resp = api_client.create_engagement(
        create_engagement_payload(
            g1["id"], title="E",
            scheduled_start="2026-09-02T10:00:00Z",
            scheduled_end="2026-09-02T10:00:00Z",
        ),
        pm_headers(),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_supersedes_target_not_under_review_rejected(api):
    """PRD §3.3: "The payload may also carry an optional supersedes_id naming
    a predecessor change order this one replaces: the predecessor must
    currently be UNDER_REVIEW on the same contract, otherwise creation is
    rejected with ERR_SUPERSEDES_TARGET_INVALID (409)."

    Design: Corner/validations/supersedes_target_not_under_review_rejected
    """
    prog = create_active_program(
        total_budget_cents=1_000_000, contingency_total_cents=100_000,
        lines=[{"cost_code": "CC-100", "amount_cents": 1_000_000}], name="P-SUP",
    )
    pid = prog["id"]
    ct1 = create_and_execute_contract(pid, 100_000, solicitation_estimate_cents=100_000,
                                       vendor_name="V1", contract_type="CONTRACTOR")
    coa = create_change_order(ct1["id"], amount_cents=1_000, title="CO-A", reason="r")
    # CO-A is DRAFT (not UNDER_REVIEW)
    resp = api_client.create_change_order(
        {
            "contract_id": ct1["id"], "title": "CO-B", "reason": "r",
            "amount_cents": 2_000, "supersedes_id": coa["id"],
        },
        pm_headers(),
    )
    validate_error(resp, ApiErrorId.ERR_SUPERSEDES_TARGET_INVALID)


def test_supersede_chain_auto_rejects_predecessor(api):
    """PRD §3.3: "When a valid supersedes_id is given, the predecessor is
    automatically moved UNDER_REVIEW → REJECTED by the system at creation
    time, and the predecessor's superseded_by_id is set to the new change
    order's id".

    Design: Corner/validations/supersede_chain_auto_rejects_predecessor
    """
    prog = create_active_program(
        total_budget_cents=1_000_000, contingency_total_cents=100_000,
        lines=[{"cost_code": "CC-100", "amount_cents": 1_000_000}], name="P-SUP2",
    )
    pid = prog["id"]
    ct1 = create_and_execute_contract(pid, 400_000, solicitation_estimate_cents=400_000,
                                       vendor_name="V1", contract_type="CONTRACTOR")
    coa = create_change_order(ct1["id"], amount_cents=50_000, title="CO-A", reason="r")
    submit_change_order(coa["id"])
    cob = get_success_data(api_client.create_change_order(
        {
            "contract_id": ct1["id"], "title": "CO-B", "reason": "revised",
            "amount_cents": 60_000, "supersedes_id": coa["id"],
        },
        pm_headers(),
    ))
    assert cob["status"] == "DRAFT"
    coa_now = get_success_data(api_client.get_change_order(coa["id"], pm_headers()))
    assert coa_now["status"] == "REJECTED"
    assert coa_now["superseded_by_id"] == cob["id"]


def test_duplicate_report_period_rejected(api):
    """PRD §3.6: "At most one report may exist for a given (program_id,
    period) pair — a duplicate is rejected with ERR_DUPLICATE_REPORT_PERIOD
    (409)."

    Design: Corner/validations/duplicate_report_period_rejected
    """
    prog = create_active_program(
        total_budget_cents=1_000_000, contingency_total_cents=100_000,
        lines=[{"cost_code": "CC-100", "amount_cents": 1_000_000}], name="P-DUP",
    )
    pid = prog["id"]
    create_owner_report(pid, period="2026-08")
    resp = api_client.create_owner_report(
        {"program_id": pid, "period": "2026-08"}, pm_headers())
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_REPORT_PERIOD)


def test_rebaseline_undercutting_commitments_rejected(api):
    """PRD §3.1: "the incoming contingency_total_cents must be at least the
    sum of the program's currently outstanding contingency_reserved_cents
    plus contingency_committed_cents plus contingency_drawn_cents; a
    rebaseline that would undercut those standing commitments is rejected
    with ERR_BASELINE_UNDERCUTS_COMMITMENTS (HTTP 402)."

    Design: Corner/validations/rebaseline_undercutting_commitments_rejected
    """
    prog = create_active_program(
        total_budget_cents=10_000_000, contingency_total_cents=1_000_000,
        lines=[{"cost_code": "CC-100", "amount_cents": 10_000_000}], name="P-UNDER",
    )
    pid = prog["id"]
    ct1 = create_and_execute_contract(pid, 1_000_000, solicitation_estimate_cents=1_000_000,
                                       vendor_name="V1", contract_type="CONTRACTOR")
    co = create_change_order(ct1["id"], amount_cents=200_000, title="CO", reason="r")
    submit_change_order(co["id"])
    recommend_change_order(co["id"], recommendation="APPROVE", analysis_note="ok")
    decide_change_order(co["id"], decision="APPROVE")
    # Outstanding committed = 200_000; propose new baseline with contingency 100_000
    bl2 = get_success_data(api_client.create_baseline(
        create_baseline_payload(pid, total_budget_cents=9_000_000,
                                 contingency_total_cents=100_000,
                                 target_finish_date="2027-06-30",
                                 lines=[{"cost_code": "CC-100", "amount_cents": 9_000_000}]),
        pm_headers(),
    ))
    api_client.submit_baseline(bl2["id"], pm_headers())
    pv = get_success_data(api_client.get_program(pid, pm_headers()))["version"]
    resp = api_client.decide_baseline(
        bl2["id"], {"decision": "APPROVE", "expected_program_version": pv},
        owner_headers(),
    )
    validate_error(resp, ApiErrorId.ERR_BASELINE_UNDERCUTS_COMMITMENTS)
