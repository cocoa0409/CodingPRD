"""Transitive cascades and complaint workflows: interpreter deactivation,
upheld-billing waiver, balance conservation, and the complaint review loop."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    provision_med_phone, create_issued_invoice_for_session, create_under_review_complaint,
    create_client, create_language_pair, create_interpreter, add_certification,
    add_language_grant, create_request, dispatch_request, create_ended_session,
    set_clock, make_client_headers, make_interpreter_headers, coordinator_headers, admin_headers,
    factories,
)


def test_interpreter_deactivation_cascade_cancels_offer_and_reopens_request(api):
    """PRD 3.6: "When an interpreter's no_show_strikes reaches the deactivation threshold of
    3, the platform sets that interpreter's status to DEACTIVATED and resets its active_load.
    That deactivation cascades further: every other still-offered assignment the interpreter
    holds is moved to lifecycle_status CANCELLED, and each such cancellation in turn bubbles
    its own parent request from ASSIGNED back to OPEN so those requests can be re-dispatched
    to other interpreters."

    Design: Difficulty/transitive_cascade/interpreter_deactivation_cascade_depth3
    """
    client = create_client(org_name="Mercy Hosp", org_type="HOSPITAL", contact_email="h@x.com")
    create_language_pair_id = create_language_pair(source_lang="en", target_lang="es")["id"]
    # Rate plan needed for any billing, harmless here.
    from test_helpers import create_rate_plan
    create_rate_plan(client["id"], certification_tier="MEDICAL", modality="PHONE",
                     billing_mode="PER_MINUTE", rate_cents=195, min_block_units=10)
    itp = create_interpreter(full_name="Strikey", max_concurrent_load=3)
    add_certification(itp["id"], tier="MEDICAL", expires_at="2027-01-01T00:00:00Z")
    add_language_grant(itp["id"], create_language_pair_id)
    set_clock("2026-03-10T09:00:00Z")
    itp_h = make_interpreter_headers(itp["id"])
    client_h = make_client_headers(client["id"])

    def strike():
        req = create_request(client["id"], create_language_pair_id)
        asg = dispatch_request(req["id"], req["version"])
        validate_success(api.accept_assignment(asg["id"], itp_h))
        sess = validate_success(api.start_session(asg["id"], itp_h), expected_status=201)
        set_clock("2026-03-10T09:30:00Z")
        validate_success(api.mark_no_show(sess["id"], factories.mark_no_show_payload("INTERPRETER"), coordinator_headers()))
        set_clock("2026-03-10T09:00:00Z")  # reset clock for next offer
        return req

    strike()  # strike 1
    strike()  # strike 2
    # Third strike's session, but FIRST create a 4th request held OFFERED by this interpreter.
    req3 = create_request(client["id"], create_language_pair_id)
    asg3 = dispatch_request(req3["id"], req3["version"])
    validate_success(api.accept_assignment(asg3["id"], itp_h))
    sess3 = validate_success(api.start_session(asg3["id"], itp_h), expected_status=201)
    # 4th request stays OFFERED (not accepted) so the deactivation cascade can cancel it.
    req4 = create_request(client["id"], create_language_pair_id)
    asg4 = dispatch_request(req4["id"], req4["version"])

    set_clock("2026-03-10T09:30:00Z")
    validate_success(api.mark_no_show(sess3["id"], factories.mark_no_show_payload("INTERPRETER"), coordinator_headers()))

    itp_after = validate_success(api.get_interpreter(itp["id"], coordinator_headers()))
    assert itp_after["no_show_strikes"] == 3, f"expected 3 strikes, got {itp_after['no_show_strikes']}"
    assert itp_after["status"] == "DEACTIVATED", f"expected DEACTIVATED, got {itp_after['status']}"
    asg4_after = validate_success(api.get_assignment(asg4["id"], coordinator_headers()))
    assert asg4_after["lifecycle_status"] == "CANCELLED", (
        f"OFFERED assignment must be cancelled by deactivation, got {asg4_after['lifecycle_status']}"
    )
    req4_after = validate_success(api.get_request(req4["id"], coordinator_headers()))
    assert req4_after["status"] == "OPEN", (
        f"cancelled offer must bubble request back to OPEN, got {req4_after['status']}"
    )


def test_third_interpreter_no_show_deactivates(api):
    """PRD 3.6: "When an interpreter's no_show_strikes reaches the deactivation threshold of
    3, the platform sets that interpreter's status to DEACTIVATED and resets its active_load."

    Design: Difficulty/transitive_cascade/interpreter_deactivation_cascade_depth3
    """
    client = create_client(org_name="Mercy Hosp", org_type="HOSPITAL", contact_email="h@x.com")
    lp_id = create_language_pair(source_lang="en", target_lang="es")["id"]
    itp = create_interpreter(full_name="Strikey", max_concurrent_load=3)
    add_certification(itp["id"], tier="MEDICAL", expires_at="2027-01-01T00:00:00Z")
    add_language_grant(itp["id"], lp_id)
    itp_h = make_interpreter_headers(itp["id"])

    for _ in range(3):
        set_clock("2026-03-10T09:00:00Z")
        req = create_request(client["id"], lp_id)
        asg = dispatch_request(req["id"], req["version"])
        validate_success(api.accept_assignment(asg["id"], itp_h))
        sess = validate_success(api.start_session(asg["id"], itp_h), expected_status=201)
        set_clock("2026-03-10T09:30:00Z")
        validate_success(api.mark_no_show(sess["id"], factories.mark_no_show_payload("INTERPRETER"), coordinator_headers()))

    itp_after = validate_success(api.get_interpreter(itp["id"], coordinator_headers()))
    assert itp_after["no_show_strikes"] == 3
    assert itp_after["status"] == "DEACTIVATED"


def test_upheld_billing_complaint_waives_and_debits_balance(api):
    """PRD 3.9: "when the category is `BILLING` or `NO_SHOW`, upholding cascades a refund —
    the session's assignment has its `billing_status` set to `WAIVED`, the complaint's
    `remedy_credit_cents` is set to the session's `billed_amount_cents`, and if that session
    had already been swept into an `ISSUED` invoice, the same amount is debited from the
    client's `outstanding_balance_cents`."

    Design: Difficulty/transitive_cascade/upheld_billing_complaint_cascade_depth2
    """
    env = create_issued_invoice_for_session()  # 3900c session on an ISSUED invoice
    cmp = create_under_review_complaint(env["session"]["id"], env["client"]["id"], "BILLING")
    resolved = validate_success(
        api.resolve_complaint(cmp["id"], factories.resolve_payload("UPHELD"), admin_headers())
    )
    assert resolved["status"] == "UPHELD"
    assert resolved["remedy_credit_cents"] == 3900, (
        f"remedy must equal billed amount 3900, got {resolved['remedy_credit_cents']}"
    )
    asg = validate_success(api.get_assignment(env["assignment"]["id"], coordinator_headers()))
    assert asg["billing_status"] == "WAIVED", f"got {asg['billing_status']}"
    client = validate_success(api.get_client(env["client"]["id"], coordinator_headers()))
    assert client["outstanding_balance_cents"] == 0, (
        f"3900 must be debited from outstanding, got {client['outstanding_balance_cents']}"
    )


def test_upheld_billing_complaint_sets_assignment_waived(api):
    """PRD 3.9: "the session's assignment has its `billing_status` set to `WAIVED`, the
    complaint's `remedy_credit_cents` is set to the session's `billed_amount_cents`,"

    Design: Difficulty/transitive_cascade/upheld_billing_complaint_cascade_depth2
    """
    env = create_issued_invoice_for_session()
    cmp = create_under_review_complaint(env["session"]["id"], env["client"]["id"], "BILLING")
    validate_success(api.resolve_complaint(cmp["id"], factories.resolve_payload("UPHELD"), admin_headers()))
    asg = validate_success(api.get_assignment(env["assignment"]["id"], coordinator_headers()))
    assert asg["billing_status"] == "WAIVED"


def test_outstanding_balance_conserved_after_issue_and_waiver(api):
    """PRD 3.10: "A draft invoice is then issued, which pins `total_cents` and adds it to the
    client's `outstanding_balance_cents`."
    PRD 3.9: "if that session had already been swept into an `ISSUED` invoice, the same amount
    is debited from the client's `outstanding_balance_cents`."

    Design: Difficulty/compensating_invariant/invoice_issue_settle_balance_conserved
    """
    env = create_issued_invoice_for_session()  # issue added 3900 to outstanding
    before = validate_success(api.get_client(env["client"]["id"], coordinator_headers()))
    assert before["outstanding_balance_cents"] == 3900, (
        f"issue must raise outstanding to 3900, got {before['outstanding_balance_cents']}"
    )
    cmp = create_under_review_complaint(env["session"]["id"], env["client"]["id"], "BILLING")
    validate_success(api.resolve_complaint(cmp["id"], factories.resolve_payload("UPHELD"), admin_headers()))
    after = validate_success(api.get_client(env["client"]["id"], coordinator_headers()))
    assert after["outstanding_balance_cents"] == 0, (
        f"waiver must debit 3900 back to 0, got {after['outstanding_balance_cents']}"
    )


def test_invoice_total_unchanged_by_waiver(api):
    """PRD 3.10: "A draft invoice is then issued, which pins `total_cents` and adds it to the
    client's `outstanding_balance_cents`."

    Design: Difficulty/compensating_invariant/invoice_issue_settle_balance_conserved
    """
    env = create_issued_invoice_for_session()
    cmp = create_under_review_complaint(env["session"]["id"], env["client"]["id"], "BILLING")
    validate_success(api.resolve_complaint(cmp["id"], factories.resolve_payload("UPHELD"), admin_headers()))
    inv = validate_success(api.get_invoice(env["invoice"]["id"], coordinator_headers()))
    assert inv["total_cents"] == 3900, (
        f"invoice total is pinned and not mutated by the waiver, got {inv['total_cents']}"
    )


def test_dismissed_complaint_resolve_again_returns_invalid_state(api):
    """PRD 3.9: "A dismissal moves the complaint to `DISMISSED` with no billing effect." and
    PRD 2.6: a transition is permitted only "whether the target is in a state from which the
    requested transition is defined (`ERR_INVALID_STATE`)."

    Design: Corner/state_machines/terminal_complaint_resolve_again_returns_invalid_state
    """
    env = provision_med_phone()
    set_clock("2026-03-10T09:00:00Z")
    req, asg, session = create_ended_session(
        env["client"]["id"], env["lp"]["id"], env["interpreter"]["id"],
        connect_iso="2026-03-10T09:00:00Z", end_iso="2026-03-10T09:20:00Z",
    )
    client_h = make_client_headers(env["client"]["id"])
    cmp = validate_success(
        api.create_complaint(factories.complaint_payload(session["id"], "QUALITY"), client_h),
        expected_status=201,
    )
    validate_success(api.review_complaint(cmp["id"], admin_headers()))
    validate_success(api.resolve_complaint(cmp["id"], factories.resolve_payload("DISMISSED"), admin_headers()))
    resp = api.resolve_complaint(cmp["id"], factories.resolve_payload("UPHELD"), admin_headers())
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_complaint_needs_info_resubmit_cycles_to_under_review(api):
    """PRD 3.9: "the administrator may request more information, moving the complaint to
    NEEDS_INFO; the owning client then resubmits, moving it back to UNDER_REVIEW. This
    review-and-revert loop between UNDER_REVIEW and NEEDS_INFO may repeat any number of
    times before resolution."

    Design: Corner/state_machines/complaint_needs_info_resubmit_cycle
    """
    env = provision_med_phone()
    set_clock("2026-03-10T09:00:00Z")
    req, asg, session = create_ended_session(
        env["client"]["id"], env["lp"]["id"], env["interpreter"]["id"],
        connect_iso="2026-03-10T09:00:00Z", end_iso="2026-03-10T09:20:00Z",
    )
    client_h = make_client_headers(env["client"]["id"])
    cmp = validate_success(
        api.create_complaint(factories.complaint_payload(session["id"], "QUALITY"), client_h),
        expected_status=201,
    )
    validate_success(api.review_complaint(cmp["id"], admin_headers()))
    validate_success(api.request_info_complaint(cmp["id"], admin_headers()))  # -> NEEDS_INFO
    resubmitted = validate_success(api.resubmit_complaint(cmp["id"], client_h))
    assert resubmitted["status"] == "UNDER_REVIEW", (
        f"resubmit must cycle back to UNDER_REVIEW, got {resubmitted['status']}"
    )
