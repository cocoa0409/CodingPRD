"""State machines: warranty cycle, parallel workflow/compliance dimensions, the
clearance bubble-up gate, panel-upgrade cascades, and cyclic permit corrections.

Translates difficulty rules non_linear_state_machine and transitive_cascade, plus
state-machine and cross-cutting corner instances.
"""
from test_helpers import (
    api_client,
    validate_success,
    get_success_data,
    setup_quote_sent,
    setup_blocked_job,
    setup_activated_job,
    setup_assessed_job,
    create_permit_application_payload,
    create_interconnection_request_payload,
    make_homeowner_headers,
    make_electrician_headers,
    TEST_USERS,
)

COORDINATOR = TEST_USERS["coordinator_headers"]
UTILITY = TEST_USERS["utility_reviewer_headers"]


# ─── WarrantyTicket cyclic diagnose<->awaiting-parts ─────────────────────

def test_warranty_diagnose_awaiting_cycle_returns_to_diagnosing():
    """PRD §3.9: "From `DIAGNOSING` the electrician may order parts (moving it to
    `AWAITING_PARTS`) and later record parts received (moving it back to `DIAGNOSING`);
    this diagnosing-and-awaiting-parts loop may repeat."

    Design: Difficulty/non_linear_state_machine/warranty_ticket_diagnose_awaiting_cycle
    """
    ctx = setup_activated_job()
    el_headers = make_electrician_headers(ctx["electrician"]["id"])
    ho_headers = make_homeowner_headers(ctx["homeowner"]["id"])
    ticket = get_success_data(api_client.create_warranty_ticket(
        {"install_job_id": ctx["job"]["id"], "summary": "no charge"}, ho_headers))
    get_success_data(api_client.diagnose_warranty_ticket(ticket["id"], el_headers))
    get_success_data(api_client.order_parts_warranty_ticket(ticket["id"], el_headers))
    res = validate_success(api_client.parts_received_warranty_ticket(ticket["id"], el_headers), 200)
    assert res["status"] == "DIAGNOSING"


def test_warranty_order_parts_moves_to_awaiting():
    """PRD §3.9: "From `DIAGNOSING` the electrician may order parts (moving it to
    `AWAITING_PARTS`) and later record parts received (moving it back to `DIAGNOSING`)"

    Design: Difficulty/non_linear_state_machine/warranty_ticket_diagnose_awaiting_cycle
    """
    ctx = setup_activated_job()
    el_headers = make_electrician_headers(ctx["electrician"]["id"])
    ho_headers = make_homeowner_headers(ctx["homeowner"]["id"])
    ticket = get_success_data(api_client.create_warranty_ticket(
        {"install_job_id": ctx["job"]["id"], "summary": "no charge"}, ho_headers))
    get_success_data(api_client.diagnose_warranty_ticket(ticket["id"], el_headers))
    res = validate_success(api_client.order_parts_warranty_ticket(ticket["id"], el_headers), 200)
    assert res["status"] == "AWAITING_PARTS"


# ─── InstallJob parallel dimensions reach CLEARED via bubble-up ──────────

def test_install_job_parallel_dimensions_quoted_and_cleared():
    """PRD §2.9: "If the job is in `compliance_status` `PERMIT_PENDING` and there now
    exists both an `APPROVED` permit application and an `APPROVED` interconnection request
    on that job, the server bubbles the job's `compliance_status` up to `CLEARED`"
    PRD §3.4: "the job's `workflow_status` advances from `ASSESSED` to `QUOTED`"

    Design: Difficulty/non_linear_state_machine/install_job_parallel_workflow_compliance_dimensions
    """
    ctx = setup_quote_sent()
    job = get_success_data(api_client.get_install_job(ctx["job"]["id"], COORDINATOR))
    ho_headers = make_homeowner_headers(ctx["homeowner"]["id"])
    get_success_data(api_client.accept_quote(
        ctx["quote"]["id"], {"expected_install_job_version": job["version"]}, ho_headers))

    permit = get_success_data(api_client.create_permit_application(
        create_permit_application_payload(ctx["job"]["id"]), COORDINATOR))
    get_success_data(api_client.approve_permit_application(permit["id"], COORDINATOR))
    ic = get_success_data(api_client.create_interconnection_request(
        create_interconnection_request_payload(ctx["job"]["id"]), COORDINATOR))
    get_success_data(api_client.start_review_interconnection_request(ic["id"], UTILITY))
    get_success_data(api_client.approve_interconnection_request(ic["id"], UTILITY))

    final = validate_success(api_client.get_install_job(ctx["job"]["id"], COORDINATOR), 200)
    assert final["workflow_status"] == "QUOTED"
    assert final["compliance_status"] == "CLEARED"


def test_permit_filing_advances_compliance_to_permit_pending():
    """PRD §3.5: "A successful filing creates the permit in `SUBMITTED` status and advances
    the job's `compliance_status` from `PENDING_REVIEW` to `PERMIT_PENDING`"

    Design: Difficulty/non_linear_state_machine/install_job_parallel_workflow_compliance_dimensions
    """
    ctx = setup_assessed_job()
    get_success_data(api_client.create_permit_application(
        create_permit_application_payload(ctx["job"]["id"]), COORDINATOR))
    job = validate_success(api_client.get_install_job(ctx["job"]["id"], COORDINATOR), 200)
    assert job["compliance_status"] == "PERMIT_PENDING"
    assert job["workflow_status"] == "ASSESSED"


# ─── Transitive cascade: accept -> referral -> BLOCKED (depth 3) ─────────

def test_assessment_accept_cascades_referral_then_blocks_compliance():
    """PRD §3.3: "The job's `requires_panel_upgrade` flag is set to the logical negation
    of the accepted assessment's `charger_fits`"
    PRD §3.3: "the system creates a `PanelUpgradeReferral` against the job (carrying its
    `install_job_id`, a `recommended_main_amps` of either 150 or 200, and a `status` of
    `OPEN`)."
    PRD §3.3: "The very act of creating that referral drives the job's compliance
    dimension: a job in `compliance_status` `PENDING_REVIEW` is moved to `BLOCKED`"

    Design: Difficulty/transitive_cascade/assessment_accept_cascades_referral_then_blocks_compliance
    """
    ctx = setup_blocked_job()
    job = validate_success(api_client.get_install_job(ctx["job"]["id"], COORDINATOR), 200)
    assert job["requires_panel_upgrade"] is True
    assert job["compliance_status"] == "BLOCKED"
    assert ctx["referral"] is not None
    referral = validate_success(
        api_client.get_panel_upgrade_referral(ctx["referral"]["id"], COORDINATOR), 200)
    assert referral["status"] == "OPEN"


def test_assessment_accept_sets_requires_panel_upgrade_flag():
    """PRD §3.3: "The job's `requires_panel_upgrade` flag is set to the logical negation
    of the accepted assessment's `charger_fits` — that is, it becomes true precisely when
    the chosen method reported insufficient spare capacity."

    Design: Difficulty/transitive_cascade/assessment_accept_cascades_referral_then_blocks_compliance
    """
    ctx = setup_blocked_job()
    job = validate_success(api_client.get_install_job(ctx["job"]["id"], COORDINATOR), 200)
    assert job["requires_panel_upgrade"] is True


# ─── Transitive cascade: panel-upgrade complete -> property + unblock (depth 2) ─

def test_panel_upgrade_complete_cascades_property_then_unblocks():
    """PRD §3.3: "Completion moves the referral to `COMPLETED`, writes the referral's
    `recommended_main_amps` onto the property's `main_breaker_amps`, clears the job's
    `requires_panel_upgrade` back to false, and returns the job's `compliance_status` from
    `BLOCKED` to `PENDING_REVIEW`"

    Design: Difficulty/transitive_cascade/panel_upgrade_complete_cascades_property_then_unblocks
    """
    ctx = setup_blocked_job()
    ho_headers = make_homeowner_headers(ctx["homeowner"]["id"])
    get_success_data(api_client.accept_panel_upgrade_referral(ctx["referral"]["id"], ho_headers))
    referral = validate_success(
        api_client.complete_panel_upgrade_referral(ctx["referral"]["id"], COORDINATOR), 200)
    assert referral["status"] == "COMPLETED"

    prop = validate_success(api_client.get_property(ctx["property"]["id"], COORDINATOR), 200)
    assert prop["main_breaker_amps"] == referral["recommended_main_amps"]

    job = validate_success(api_client.get_install_job(ctx["job"]["id"], COORDINATOR), 200)
    assert job["compliance_status"] == "PENDING_REVIEW"
    assert job["requires_panel_upgrade"] is False


def test_panel_upgrade_complete_returns_compliance_to_pending_review():
    """PRD §3.3: "returns the job's `compliance_status` from `BLOCKED` to `PENDING_REVIEW`,
    refreshing `updated_at` and incrementing the job's `version`."

    Design: Difficulty/transitive_cascade/panel_upgrade_complete_cascades_property_then_unblocks
    """
    ctx = setup_blocked_job()
    ho_headers = make_homeowner_headers(ctx["homeowner"]["id"])
    get_success_data(api_client.accept_panel_upgrade_referral(ctx["referral"]["id"], ho_headers))
    get_success_data(api_client.complete_panel_upgrade_referral(ctx["referral"]["id"], COORDINATOR))
    job = validate_success(api_client.get_install_job(ctx["job"]["id"], COORDINATOR), 200)
    assert job["compliance_status"] == "PENDING_REVIEW"


# ─── Permit corrections loop auto-rejects at 3 rounds (corner cyclic) ────

def test_permit_corrections_loop_three_rounds_auto_reject():
    """PRD §3.5: "From there a coordinator resubmits: if `correction_rounds` is fewer
    than 3, the permit returns to `SUBMITTED`; but if `correction_rounds` has reached 3 or
    more, the resubmission instead auto-rejects the permit, moving it to the terminal
    `REJECTED` state."

    Design: Corner/state_machines/permit_corrections_loop_three_rounds_auto_reject
    """
    ctx = setup_assessed_job()
    permit = get_success_data(api_client.create_permit_application(
        create_permit_application_payload(ctx["job"]["id"]), COORDINATOR))
    for _ in range(2):
        get_success_data(api_client.request_corrections_permit_application(permit["id"], COORDINATOR))
        get_success_data(api_client.resubmit_permit_application(permit["id"], COORDINATOR))
    get_success_data(api_client.request_corrections_permit_application(permit["id"], COORDINATOR))
    res = validate_success(api_client.resubmit_permit_application(permit["id"], COORDINATOR), 200)
    assert res["correction_rounds"] == 3
    assert res["status"] == "REJECTED"


# ─── Interconnection deny is terminal and does not clear the gate ────────

def test_interconnection_deny_does_not_clear_gate():
    """PRD §3.5: "Denial moves it from `UNDER_REVIEW` to the terminal `DENIED` state."
    PRD §2.9: "the job reaches `compliance_status` `CLEARED` only once both an approved
    permit and an approved interconnection request coexist on it."

    Design: Corner/state_machines/interconnection_deny_terminal
    """
    ctx = setup_quote_sent()
    job = get_success_data(api_client.get_install_job(ctx["job"]["id"], COORDINATOR))
    ho_headers = make_homeowner_headers(ctx["homeowner"]["id"])
    get_success_data(api_client.accept_quote(
        ctx["quote"]["id"], {"expected_install_job_version": job["version"]}, ho_headers))
    permit = get_success_data(api_client.create_permit_application(
        create_permit_application_payload(ctx["job"]["id"]), COORDINATOR))
    get_success_data(api_client.approve_permit_application(permit["id"], COORDINATOR))
    ic = get_success_data(api_client.create_interconnection_request(
        create_interconnection_request_payload(ctx["job"]["id"]), COORDINATOR))
    get_success_data(api_client.start_review_interconnection_request(ic["id"], UTILITY))
    denied = validate_success(api_client.deny_interconnection_request(ic["id"], UTILITY), 200)
    assert denied["status"] == "DENIED"

    job_after = validate_success(api_client.get_install_job(ctx["job"]["id"], COORDINATOR), 200)
    assert job_after["compliance_status"] == "PERMIT_PENDING"


# ─── Clearance gate requires BOTH approvals (cross-cutting threshold) ────

def test_clear_gate_requires_both_permit_and_interconnection():
    """PRD §2.9: "Regulatory clearance is not set by a single action; it emerges when two
    independent children both reach approval."
    PRD §2.9: "If the job is in `compliance_status` `PERMIT_PENDING` and there now exists
    both an `APPROVED` permit application and an `APPROVED` interconnection request on that
    job, the server bubbles the job's `compliance_status` up to `CLEARED`"

    Design: Corner/cross_cutting_complexity_layers/clear_gate_requires_both_permit_and_interconnection
    """
    ctx = setup_quote_sent()
    job = get_success_data(api_client.get_install_job(ctx["job"]["id"], COORDINATOR))
    ho_headers = make_homeowner_headers(ctx["homeowner"]["id"])
    get_success_data(api_client.accept_quote(
        ctx["quote"]["id"], {"expected_install_job_version": job["version"]}, ho_headers))
    permit = get_success_data(api_client.create_permit_application(
        create_permit_application_payload(ctx["job"]["id"]), COORDINATOR))
    get_success_data(api_client.approve_permit_application(permit["id"], COORDINATOR))
    ic = get_success_data(api_client.create_interconnection_request(
        create_interconnection_request_payload(ctx["job"]["id"]), COORDINATOR))
    # Only start review (no approval) — one approval alone must not cross the gate.
    get_success_data(api_client.start_review_interconnection_request(ic["id"], UTILITY))
    job_after = validate_success(api_client.get_install_job(ctx["job"]["id"], COORDINATOR), 200)
    assert job_after["compliance_status"] == "PERMIT_PENDING"
