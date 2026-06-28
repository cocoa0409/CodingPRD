"""Cross-entity state dependencies, the state-vs-compliance priority conflict, and
compensating-action invariants (incentive reversal, dispatch-cancel slot conservation).

Translates difficulty rules cross_entity_state_dependency, priority_pair_validation_conflict
(instance 1), and compensating_invariant.
"""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    setup_quoted_job,
    setup_compliance_cleared,
    setup_activated_job,
    create_electrician,
    create_dispatch_assignment_payload,
    create_permit_application_payload,
    create_incentive_claim_payload,
    make_homeowner_headers,
    make_electrician_headers,
    TEST_USERS,
)
from test_helpers.fixtures import _list_data

COORDINATOR = TEST_USERS["coordinator_headers"]
UTILITY = TEST_USERS["utility_reviewer_headers"]


def _second_quoted_job(ctx):
    job = get_success_data(api_client.create_install_job(
        {"property_id": ctx["property"]["id"], "charger_product_sku": ctx["charger"]["sku"]},
        COORDINATOR))
    sa = get_success_data(api_client.create_site_assessment(
        {"property_id": ctx["property"]["id"], "install_job_id": job["id"],
         "assessment_method": "LOAD_STUDY_220_87", "declared_fixed_appliance_va": 0,
         "max_measured_demand_va": 7200}, COORDINATOR))
    get_success_data(api_client.accept_site_assessment(sa["id"], COORDINATOR))
    quote = get_success_data(api_client.create_quote(
        {"install_job_id": job["id"], "labor_cents": 120000, "parts_line_cents": [60000, 5000]},
        COORDINATOR))
    get_success_data(api_client.send_quote(quote["id"], COORDINATOR))
    cur = get_success_data(api_client.get_install_job(job["id"], COORDINATOR))
    ho_headers = make_homeowner_headers(ctx["homeowner"]["id"])
    get_success_data(api_client.accept_quote(
        quote["id"], {"expected_install_job_version": cur["version"]}, ho_headers))
    return job


# ─── Dispatch complete requires InstallJob compliance CLEARED ────────────

def test_dispatch_complete_requires_install_job_cleared():
    """PRD §3.6: "Completion is the single point where the two install-job dimensions
    intersect: it requires the assignment to be `EN_ROUTE` and the job's `compliance_status`
    to be `CLEARED`. If compliance has not cleared, completion is rejected with
    `ERR_COMPLIANCE_NOT_CLEARED` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/dispatch_complete_requires_install_job_cleared
    """
    ctx = setup_quoted_job()
    el = create_electrician()
    # File a permit (compliance -> PERMIT_PENDING) but do NOT approve it / no interconnection.
    get_success_data(api_client.create_permit_application(
        create_permit_application_payload(ctx["job"]["id"]), COORDINATOR))
    da = get_success_data(api_client.create_dispatch_assignment(
        create_dispatch_assignment_payload(ctx["job"]["id"], el["id"],
                                            window_date="2026-05-06T00:00:00Z",
                                            window_start_minute=540, window_end_minute=720),
        COORDINATOR))
    el_headers = make_electrician_headers(el["id"])
    get_success_data(api_client.depart_dispatch_assignment(da["id"], el_headers))
    # EN_ROUTE but compliance still PERMIT_PENDING
    res = api_client.complete_dispatch_assignment(da["id"], el_headers)
    validate_error(res, "ERR_COMPLIANCE_NOT_CLEARED")


def test_dispatch_complete_succeeds_when_cleared():
    """PRD §3.6: "On a valid completion the assignment moves to `COMPLETED`, the system
    mints a one-time `activation_pairing_code` onto the job, and the job's `workflow_status`
    advances from `SCHEDULED` to `INSTALLED`"

    Design: Difficulty/cross_entity_state_dependency/dispatch_complete_requires_install_job_cleared
    """
    ctx = setup_compliance_cleared()
    el = create_electrician()
    da = get_success_data(api_client.create_dispatch_assignment(
        create_dispatch_assignment_payload(ctx["job"]["id"], el["id"],
                                            window_date="2026-05-06T00:00:00Z",
                                            window_start_minute=540, window_end_minute=720),
        COORDINATOR))
    el_headers = make_electrician_headers(el["id"])
    get_success_data(api_client.depart_dispatch_assignment(da["id"], el_headers))
    res = validate_success(api_client.complete_dispatch_assignment(da["id"], el_headers), 200)
    assert res["status"] == "COMPLETED"
    job = validate_success(api_client.get_install_job(ctx["job"]["id"], COORDINATOR), 200)
    assert job["workflow_status"] == "INSTALLED"


# ─── Warranty open requires InstallJob ACTIVATED/CLOSED ──────────────────

def test_warranty_open_requires_install_job_activated():
    """PRD §3.9: "the homeowner may open a `WarrantyTicket` against it ... Opening a ticket
    before the job has been activated is rejected with `ERR_JOB_NOT_ACTIVATED`."

    Design: Difficulty/cross_entity_state_dependency/warranty_open_requires_install_job_activated
    """
    ctx = setup_quoted_job()
    ho_headers = make_homeowner_headers(ctx["homeowner"]["id"])
    res = api_client.create_warranty_ticket(
        {"install_job_id": ctx["job"]["id"], "summary": "premature"}, ho_headers)
    validate_error(res, "ERR_JOB_NOT_ACTIVATED")


def test_warranty_open_succeeds_after_activation():
    """PRD §3.9: "Once a job has reached `workflow_status` `ACTIVATED` or `CLOSED`, the
    homeowner may open a `WarrantyTicket` against it, supplying the `install_job_id` and a
    `summary` of the defect. ... A ticket is born in `OPEN` status"

    Design: Difficulty/cross_entity_state_dependency/warranty_open_requires_install_job_activated
    """
    ctx = setup_activated_job()
    ho_headers = make_homeowner_headers(ctx["homeowner"]["id"])
    res = validate_success(api_client.create_warranty_ticket(
        {"install_job_id": ctx["job"]["id"], "summary": "real defect"}, ho_headers), 201)
    assert res["status"] == "OPEN"


# ─── Priority conflict: INVALID_STATE (P6) beats COMPLIANCE_NOT_CLEARED (P8) ─

def test_invalid_state_beats_compliance_not_cleared():
    """PRD §3.10: "then the requirement that the target be in a state from which the
    requested transition is defined, failing with `ERR_INVALID_STATE`; ... then the
    compliance-cleared gate on install completion, failing with
    `ERR_COMPLIANCE_NOT_CLEARED`"

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_compliance_not_cleared
    """
    ctx = setup_quoted_job()
    el = create_electrician()
    get_success_data(api_client.create_permit_application(
        create_permit_application_payload(ctx["job"]["id"]), COORDINATOR))
    da = get_success_data(api_client.create_dispatch_assignment(
        create_dispatch_assignment_payload(ctx["job"]["id"], el["id"],
                                            window_date="2026-05-03T00:00:00Z",
                                            window_start_minute=540, window_end_minute=720),
        COORDINATOR))
    el_headers = make_electrician_headers(el["id"])
    # Assignment is BOOKED (not EN_ROUTE) AND compliance is PERMIT_PENDING (not CLEARED):
    # state check (P6) wins.
    res = api_client.complete_dispatch_assignment(da["id"], el_headers)
    validate_error(res, "ERR_INVALID_STATE")


def test_invalid_state_wins_leaves_dispatch_unchanged():
    """PRD §3.10: "then the requirement that the target be in a state from which the
    requested transition is defined, failing with `ERR_INVALID_STATE`; ... then the
    compliance-cleared gate on install completion, failing with
    `ERR_COMPLIANCE_NOT_CLEARED`"
    PRD §3.6: "From `EN_ROUTE` the electrician completes the install."

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_compliance_not_cleared
    """
    ctx = setup_quoted_job()
    el = create_electrician()
    get_success_data(api_client.create_permit_application(
        create_permit_application_payload(ctx["job"]["id"]), COORDINATOR))
    da = get_success_data(api_client.create_dispatch_assignment(
        create_dispatch_assignment_payload(ctx["job"]["id"], el["id"],
                                            window_date="2026-05-03T00:00:00Z",
                                            window_start_minute=540, window_end_minute=720),
        COORDINATOR))
    el_headers = make_electrician_headers(el["id"])
    # BOOKED (not EN_ROUTE) + PERMIT_PENDING (not CLEARED) -> state check (P6) wins.
    res = api_client.complete_dispatch_assignment(da["id"], el_headers)
    validate_error(res, "ERR_INVALID_STATE")
    # The rejected completion must not have advanced the dispatch out of BOOKED.
    da_after = validate_success(api_client.get_dispatch_assignment(da["id"], COORDINATOR), 200)
    assert da_after["status"] == "BOOKED"


# ─── Compensating invariant: incentive reversal conserves net-paid ───────

def test_incentive_award_reversal_conserves_net_paid():
    """PRD §3.8: "a coordinator submits the claim (moving it to `SUBMITTED`), then marks
    it paid (moving it from `SUBMITTED` to `PAID`), and may later reverse a paid claim
    (moving it from `PAID` to the terminal `REVERSED` state). Reversal is a compensating
    action: the claim's `award_cents` is conceptually clawed back so that the conservation
    of awarded incentive across the job is preserved."

    Design: Difficulty/compensating_invariant/incentive_award_reversal_conserves_net_paid
    """
    ctx = setup_activated_job()
    claim = get_success_data(api_client.create_incentive_claim(
        create_incentive_claim_payload(ctx["job"]["id"], "FEDERAL_45W", 195750), COORDINATOR))
    assert claim["award_cents"] == 58725
    get_success_data(api_client.submit_incentive_claim(claim["id"], COORDINATOR))
    get_success_data(api_client.pay_incentive_claim(claim["id"], COORDINATOR))
    reversed_claim = validate_success(api_client.reverse_incentive_claim(claim["id"], COORDINATOR), 200)
    assert reversed_claim["status"] == "REVERSED"
    assert reversed_claim["award_cents"] == 58725  # award retained for audit


def test_incentive_reversal_from_paid_only():
    """PRD §3.8: "may later reverse a paid claim (moving it from `PAID` to the terminal
    `REVERSED` state)."

    Design: Difficulty/compensating_invariant/incentive_award_reversal_conserves_net_paid
    """
    ctx = setup_activated_job()
    claim = get_success_data(api_client.create_incentive_claim(
        create_incentive_claim_payload(ctx["job"]["id"], "FEDERAL_45W", 195750), COORDINATOR))
    get_success_data(api_client.submit_incentive_claim(claim["id"], COORDINATOR))
    get_success_data(api_client.pay_incentive_claim(claim["id"], COORDINATOR))
    reversed_claim = validate_success(api_client.reverse_incentive_claim(claim["id"], COORDINATOR), 200)
    assert reversed_claim["status"] == "REVERSED"


# ─── Compensating invariant: dispatch cancel conserves day-load + reverts job ─

def test_dispatch_cancel_conserves_day_load_and_reverts_job():
    """PRD §3.6: "A booked assignment may be cancelled by a coordinator before departure:
    from `BOOKED` it moves to `CANCELLED`, and if the parent job is currently in
    `workflow_status` `SCHEDULED`, the job reverts from `SCHEDULED` back to `QUOTED`"

    Design: Difficulty/compensating_invariant/dispatch_cancel_conserves_electrician_day_load
    """
    ctx = setup_quoted_job()
    el = create_electrician(max_daily_jobs=2)
    date = "2026-05-10T00:00:00Z"
    # First booking on ctx's job (remains booked)
    get_success_data(api_client.create_dispatch_assignment(
        create_dispatch_assignment_payload(ctx["job"]["id"], el["id"], window_date=date,
                                            window_start_minute=480, window_end_minute=600),
        COORDINATOR))
    # Second booking on a fresh job, then cancel it
    job_b = _second_quoted_job(ctx)
    da_b = get_success_data(api_client.create_dispatch_assignment(
        create_dispatch_assignment_payload(job_b["id"], el["id"], window_date=date,
                                            window_start_minute=660, window_end_minute=780),
        COORDINATOR))
    cancelled = validate_success(api_client.cancel_dispatch_assignment(da_b["id"], COORDINATOR), 200)
    assert cancelled["status"] == "CANCELLED"

    job_b_after = validate_success(api_client.get_install_job(job_b["id"], COORDINATOR), 200)
    assert job_b_after["workflow_status"] == "QUOTED"

    # Day-load conserved: exactly 1 active (BOOKED/EN_ROUTE) assignment remains on the date.
    data, _ = _list_data(api_client.list_dispatch_assignments(
        COORDINATOR, params={"electrician_id": el["id"]}))
    active_on_date = [
        d for d in data
        if d["status"] in ("BOOKED", "EN_ROUTE") and d["window_date"].startswith("2026-05-10")
    ]
    assert len(active_on_date) == 1


def test_dispatch_cancel_sets_cancelled_and_reverts_job():
    """PRD §3.6: "A booked assignment may be cancelled by a coordinator before departure:
    from `BOOKED` it moves to `CANCELLED`, and if the parent job is currently in
    `workflow_status` `SCHEDULED`, the job reverts from `SCHEDULED` back to `QUOTED`"

    Design: Difficulty/compensating_invariant/dispatch_cancel_conserves_electrician_day_load
    """
    ctx = setup_quoted_job()
    el = create_electrician(max_daily_jobs=2)
    da = get_success_data(api_client.create_dispatch_assignment(
        create_dispatch_assignment_payload(ctx["job"]["id"], el["id"],
                                            window_date="2026-05-10T00:00:00Z",
                                            window_start_minute=660, window_end_minute=780),
        COORDINATOR))
    cancelled = validate_success(api_client.cancel_dispatch_assignment(da["id"], COORDINATOR), 200)
    assert cancelled["status"] == "CANCELLED"
    job_after = validate_success(api_client.get_install_job(ctx["job"]["id"], COORDINATOR), 200)
    assert job_after["workflow_status"] == "QUOTED"
