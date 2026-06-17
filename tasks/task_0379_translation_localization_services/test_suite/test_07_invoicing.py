"""Invoicing: the final reconciled figure (dual variant of the quote), the client-active
and project-delivered fiscal preconditions, the optimistic-concurrency check on issue,
the QA-fail cascade that blocks invoicing, and the AR-balance effect of payment.

Covers difficulty rules `dual_variant_calc` (quote vs final invoice),
`cross_entity_state_dependency` (invoice->client), and `transitive_cascade` (QA fail ->
revision -> non-delivered -> invoice blocked), plus corner `endpoints` and
`cross_cutting_complexity_layers` instances.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    create_client, create_rate_card, create_linguist, create_project, add_job,
    quote_and_approve, assign, accept_as_translator, accept_as_reviewer,
    current_job_version, current_project_version,
    make_translator_headers, make_reviewer_headers,
    create_qa_report_payload, issue_invoice_payload, deliver_payload,
    setup_job_in_qa, setup_delivered_project, setup_issued_invoice,
    DEFAULT_BANDS, DEFAULT_ACTUAL_BANDS,
)

PM = TEST_USERS["pm_headers"]
AR = TEST_USERS["ar_headers"]


def _deliver_with_two_revision_rounds():
    """EXPRESS+CERTIFIED single job, taken through two revision rounds (one chargeable),
    delivered with actual bands {1300,600,400,300}, draft invoice created. Returns ctx
    with project DELIVERED and invoice DRAFT, plus the quoted_total captured at quote."""
    ctx = setup_job_in_qa(rush_tier="EXPRESS", certification_mode="CERTIFIED")
    quoted_total = get_success_data(
        api_get_project(ctx["project"]["id"]))["quoted_total_cents"]
    rid = ctx["reviewer_assignment"]["id"]
    jid = ctx["job"]["id"]
    rev_hdr = make_reviewer_headers(ctx["reviewer"]["id"])
    tr_hdr = make_translator_headers(ctx["translator"]["id"])
    # First QA FAIL (5 critical over 2600 -> 80.8 < 90) -> REVISION.
    get_success_data(api_post_qa(jid, rid, 5, 0, 0, 2600, rev_hdr))
    # Resubmit -> IN_QA (revision_rounds = 1).
    get_success_data(api_submit(jid, tr_hdr))
    # Second QA FAIL -> REVISION.
    get_success_data(api_post_qa(jid, rid, 5, 0, 0, 2600, rev_hdr))
    # Resubmit -> IN_QA (revision_rounds = 2).
    get_success_data(api_submit(jid, tr_hdr))
    # Third QA PASS (1 minor) -> QA_PASSED.
    get_success_data(api_post_qa(jid, rid, 0, 0, 1, 2600, rev_hdr))
    # Deliver with actual bands.
    get_success_data(api_deliver(jid, dict(DEFAULT_ACTUAL_BANDS)))
    ctx["invoice"] = get_success_data(api_create_invoice(ctx["project"]["id"]))
    ctx["quoted_total"] = quoted_total
    return ctx


# thin module-level wrappers so the helper above reads cleanly
def api_get_project(pid):
    from test_helpers import api_client
    return api_client.get_project(pid, PM)


def api_post_qa(jid, rid, c, m, mi, swc, hdr):
    from test_helpers import api_client
    return api_client.create_qa_report(
        jid, create_qa_report_payload(rid, swc, critical_count=c, major_count=m,
                                      minor_count=mi), hdr)


def api_submit(jid, hdr):
    from test_helpers import api_client
    return api_client.submit_translation(jid, hdr)


def api_deliver(jid, actual):
    from test_helpers import api_client
    return api_client.deliver_job(jid, deliver_payload(**actual), PM)


def api_create_invoice(pid):
    from test_helpers import api_client
    return api_client.create_invoice(pid, AR)


# ─── dual_variant_calc: quote estimate vs final invoice ────────────────────
def test_final_invoice_total_diverges_from_quote_with_revision_surcharge(api):
    """PRD §3.8: "**Fourth**, the `revision_surcharge_cents` is the sum over jobs of a
    per-job revision surcharge; for one job, the chargeable rounds is the job's
    `revision_rounds` minus the one free revision round allowed, floored at zero ... and
    the per-job surcharge is the half-up-rounded product of that job's translation
    subtotal, the revision surcharge rate of eight hundredths, and the chargeable round
    count."
    PRD §3.8: "**Sixth**, the `total_cents` is the after-discount amount plus
    `rush_surcharge_cents` plus `revision_surcharge_cents` plus `certification_cents`."
    PRD §3.8: "The decisive difference from the quote estimate is twofold: the final
    figure reads actual bands instead of quoted bands, and it inserts the revision
    surcharge between the rush surcharge and the certification add-on — a charge the
    quote estimate omits entirely."

    Design: Difficulty/dual_variant_calc/dvc_quote_estimate_vs_final_invoice_diverge_on_project
    """
    ctx = _deliver_with_two_revision_rounds()
    assert ctx["quoted_total"] == 39613, \
        f"expected quoted 39613, got {ctx['quoted_total']}"
    job = validate_success(api.get_job(ctx["job"]["id"], PM), 200)
    assert job["revision_rounds"] == 2, f"expected 2 rounds, got {job['revision_rounds']}"
    pv = current_project_version(ctx["project"]["id"])
    issued = validate_success(
        api.issue_invoice(ctx["invoice"]["id"], issue_invoice_payload(pv), AR), 200)
    assert issued["total_cents"] == 44313, \
        f"expected final 44313, got {issued['total_cents']}"
    assert issued["total_cents"] != ctx["quoted_total"], \
        "final invoice must diverge from the quote estimate"


def test_final_invoice_revision_surcharge_component(api):
    """PRD §3.8: "the chargeable rounds is the job's `revision_rounds` minus the one free
    revision round allowed, floored at zero ... and the per-job surcharge is the
    half-up-rounded product of that job's translation subtotal, the revision surcharge
    rate of eight hundredths, and the chargeable round count."

    Second probe on the same divergence: with revision_rounds=2 (one chargeable), the
    invoice carries a non-zero revision_surcharge_cents of 2250 (8% of the 28125 actual
    subtotal), the component the quote estimate omits.

    Design: Difficulty/dual_variant_calc/dvc_quote_estimate_vs_final_invoice_diverge_on_project
    """
    ctx = _deliver_with_two_revision_rounds()
    pv = current_project_version(ctx["project"]["id"])
    issued = validate_success(
        api.issue_invoice(ctx["invoice"]["id"], issue_invoice_payload(pv), AR), 200)
    assert issued["revision_surcharge_cents"] == 2250, \
        f"expected 2250, got {issued['revision_surcharge_cents']}"


# ─── cross_entity_state_dependency: invoice issue requires client ACTIVE ────
def test_issue_invoice_for_suspended_client_rejected(api):
    """PRD §3.8: "Three further preconditions apply: the parent project must be
    `DELIVERED`, otherwise `ERR_PROJECT_NOT_DELIVERED`; and the owning client's `status`
    must be `ACTIVE`, otherwise `ERR_CLIENT_SUSPENDED`."

    Design: Difficulty/cross_entity_state_dependency/cesd_invoice_issue_requires_client_active
    """
    ctx = setup_delivered_project(rush_tier="EXPRESS", certification_mode="CERTIFIED")
    get_success_data(api.create_invoice(ctx["project"]["id"], AR))
    inv = validate_success(api.list_project_invoices(ctx["project"]["id"], AR), 200)[0]
    get_success_data(api.suspend_client(ctx["client"]["id"], AR))
    pv = current_project_version(ctx["project"]["id"])
    resp = api.issue_invoice(inv["id"], issue_invoice_payload(pv), AR)
    validate_error(resp, ApiErrorId.ERR_CLIENT_SUSPENDED.value, 409)


def test_issue_blocked_by_suspended_client_leaves_invoice_draft(api):
    """PRD §3.8: "the owning client's `status` must be `ACTIVE`, otherwise
    `ERR_CLIENT_SUSPENDED`."
    PRD §3.8: "An operator first creates a draft **invoice** for a project; the new
    invoice's `status` is `DRAFT`".

    Second probe: the rejected issue does not transition the invoice; it stays DRAFT.

    Design: Difficulty/cross_entity_state_dependency/cesd_invoice_issue_requires_client_active
    """
    ctx = setup_delivered_project(rush_tier="EXPRESS", certification_mode="CERTIFIED")
    get_success_data(api.create_invoice(ctx["project"]["id"], AR))
    inv = validate_success(api.list_project_invoices(ctx["project"]["id"], AR), 200)[0]
    get_success_data(api.suspend_client(ctx["client"]["id"], AR))
    pv = current_project_version(ctx["project"]["id"])
    api.issue_invoice(inv["id"], issue_invoice_payload(pv), AR)
    after = validate_success(api.get_invoice(inv["id"], AR), 200)
    assert after["status"] == "DRAFT", f"expected DRAFT, got {after['status']}"


# ─── transitive_cascade: QA fail -> revision -> blocks invoice ─────────────
def test_qa_fail_keeps_project_in_production_and_blocks_invoice(api):
    """PRD §3.6: "A `PASS` outcome drives the job from `IN_QA` to `QA_PASSED`; a `FAIL` outcome drives it from `IN_QA` to `REVISION`."
    PRD §3.8: "the parent project must be `DELIVERED`, otherwise
    `ERR_PROJECT_NOT_DELIVERED`".

    A FAIL QA report (A) drives the job IN_QA->REVISION (B); the job is therefore not
    DELIVERED so the project remains IN_PRODUCTION (C); issuing the draft invoice fails
    with ERR_PROJECT_NOT_DELIVERED.

    Design: Difficulty/transitive_cascade/tc_qa_fail_revision_reopen_blocks_invoice_depth3
    """
    ctx = setup_job_in_qa()
    get_success_data(api.create_invoice(ctx["project"]["id"], AR))
    inv = validate_success(api.list_project_invoices(ctx["project"]["id"], AR), 200)[0]
    # FAIL QA: 1 crit + 3 maj + 5 min over 2600 -> 88.5 -> FAIL.
    get_success_data(api.create_qa_report(
        ctx["job"]["id"],
        create_qa_report_payload(ctx["reviewer_assignment"]["id"], 2600,
                                 critical_count=1, major_count=3, minor_count=5),
        make_reviewer_headers(ctx["reviewer"]["id"])))
    job = validate_success(api.get_job(ctx["job"]["id"], PM), 200)
    assert job["status"] == "REVISION", f"got {job['status']}"
    project = validate_success(api.get_project(ctx["project"]["id"], PM), 200)
    assert project["status"] == "IN_PRODUCTION", f"got {project['status']}"
    pv = current_project_version(ctx["project"]["id"])
    resp = api.issue_invoice(inv["id"], issue_invoice_payload(pv), AR)
    validate_error(resp, ApiErrorId.ERR_PROJECT_NOT_DELIVERED.value, 409)


def test_qa_fail_first_hop_drives_job_to_revision(api):
    """PRD §3.6: "A `PASS` outcome drives the job from `IN_QA` to `QA_PASSED`; a `FAIL` outcome drives it from `IN_QA` to `REVISION`."

    Second probe of the cascade's first hop (A->B) in isolation: filing a FAIL QA report
    drives the job from IN_QA to REVISION.

    Design: Difficulty/transitive_cascade/tc_qa_fail_revision_reopen_blocks_invoice_depth3
    """
    ctx = setup_job_in_qa()
    report = validate_success(api.create_qa_report(
        ctx["job"]["id"],
        create_qa_report_payload(ctx["reviewer_assignment"]["id"], 2600,
                                 critical_count=1, major_count=3, minor_count=5),
        make_reviewer_headers(ctx["reviewer"]["id"])), 201)
    assert report["outcome"] == "FAIL", f"got {report['outcome']}"
    job = validate_success(api.get_job(ctx["job"]["id"], PM), 200)
    assert job["status"] == "REVISION", f"got {job['status']}"


# ─── corner endpoints / OCC ────────────────────────────────────────────────
def test_pay_invoice_decrements_ar_balance(api):
    """PRD §3.8: "An issued invoice is later marked paid, advancing it from `ISSUED` to
    `PAID`; ... payment decreases the client's `ar_balance_cents` by `total_cents`."

    Design: Corner/endpoints/pay_invoice_decrements_ar_balance
    """
    ctx = setup_issued_invoice(rush_tier="EXPRESS", certification_mode="CERTIFIED")
    paid = validate_success(api.pay_invoice(ctx["invoice"]["id"], AR), 200)
    assert paid["status"] == "PAID", f"got {paid['status']}"
    client = validate_success(api.get_client(ctx["client"]["id"], AR), 200)
    assert client["ar_balance_cents"] == 0, \
        f"expected 0 after pay, got {client['ar_balance_cents']}"


def test_occ_invoice_issue_stale_project_version_returns_412(api):
    """PRD §2.8: "Issuing an invoice requires `expected_project_version` in the request
    body, carrying the `Project` version the client last read. The server compares it
    against the target project's current `version`; if another writer has advanced the
    project version since the client read it ... the issue is rejected with
    `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_invoice_issue_stale_project_version_returns_412
    """
    ctx = setup_delivered_project(rush_tier="EXPRESS", certification_mode="CERTIFIED")
    get_success_data(api.create_invoice(ctx["project"]["id"], AR))
    inv = validate_success(api.list_project_invoices(ctx["project"]["id"], AR), 200)[0]
    pv = current_project_version(ctx["project"]["id"])
    resp = api.issue_invoice(inv["id"], issue_invoice_payload(pv - 1), AR)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value, 412)
