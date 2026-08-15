"""Validation-priority pair tests and compensating-invariant tests
(PRD §2.6, §3.5, §3.6, §3.9)."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS, headers_for,
    assert_event_order,
    setup_reference_data, setup_complaint, intake_complaint,
    setup_resolved_complaint, setup_complaint_in_response_qa,
    setup_pending_decision, create_template, publish_template,
    create_category, create_and_complete_rca, drive_to_investigating,
    claim_review, complete_review, submit_decision, create_decision,
    get_complaint, get_decision, get_template, list_complaint_events,
    list_templates,
)

MANAGER = TEST_USERS["complaint_manager_headers"]
HANDLER = TEST_USERS["case_handler_headers"]


def test_sod_safety_beats_state_on_self_qa_fail_after_resolution(api):
    """PRD §2.6: "Within the business layer the same discipline holds: a request
    that would fail both a segregation-of-duties check and a state check surfaces
    the segregation error, and a stale-version rejection is always the last gate
    evaluated, after every semantic check has already passed."
    PRD §3.5: "The qa-fail action is refused with `ERR_SOD_SELF_REVIEW` when the
    acting reviewer is the complaint's `owner_user_id`."

    Design: Difficulty/priority_pair_validation_conflict/sod_safety_beats_state_on_self_qa_fail_after_resolution
    """
    # The complaint owner is user_dual_1 (intake actor); drive it to RESOLVED.
    ctx = setup_resolved_complaint(
        "DD-PLUS", "WEB", "SVC.DIRECT_DEPOSIT",
        owner_id="user_dual_1", reviewer_id="user_qa_4",
        verdict="NOT_SUBSTANTIATED", narrative="DD posting delay",
        window_end_at="2026-08-09T00:00:00Z",
    )
    cid = ctx["complaint"]["id"]
    assert ctx["complaint"]["status"] == "RESOLVED"
    assert ctx["complaint"]["owner_user_id"] == "user_dual_1"

    # Acting QAReviewer IS the owner (SoD violation) AND the complaint is
    # RESOLVED (state violation): the segregation error must surface.
    response = api.qa_fail(cid, headers_for("QAReviewer", "user_dual_1"))
    error_data = validate_error(response, ApiErrorId.ERR_SOD_SELF_REVIEW)
    assert error_data["error_id"] != "ERR_INVALID_STATE_TRANSITION"
    assert get_complaint(cid)["status"] == "RESOLVED"


def test_sod_self_review_fires_with_valid_state_alone(api):
    """PRD §3.5: "The qa-fail action is refused with `ERR_SOD_SELF_REVIEW` when
    the acting reviewer is the complaint's `owner_user_id`."
    PRD §3.5: "Completing a review with `PASS` leaves the complaint in
    `RESPONSE_QA` — a pass alone never resolves anything — while the dedicated
    qa-fail action moves the complaint `RESPONSE_QA → INVESTIGATING`, completes
    the acting reviewer's `OPEN` review with outcome `FAIL` in the same call,
    appends `QA_FAILED`, and bumps the complaint's `version`."

    Design: Difficulty/priority_pair_validation_conflict/sod_safety_beats_state_on_self_qa_fail_after_resolution
    """
    ctx = setup_complaint_in_response_qa(
        "DD-SOD", "WEB", "SVC.SOD", owner_id="user_owner9",
        narrative="sod isolation",
    )
    cid = ctx["complaint"]["id"]
    # The owner (as a QAReviewer) holds an OPEN review, the complaint is in
    # RESPONSE_QA — only the segregation rule can fail.
    review = claim_review(cid, "user_owner9", "2026-08-01T00:00:00Z",
                          "2026-08-09T00:00:00Z")
    response = api.qa_fail(cid, headers_for("QAReviewer", "user_owner9"))
    validate_error(response, ApiErrorId.ERR_SOD_SELF_REVIEW)
    assert get_complaint(cid)["status"] == "RESPONSE_QA"


def test_referential_template_beats_constraint_rca_on_draft_response(api):
    """PRD §2.6: "Every request passes through a fixed pipeline of checks, and
    the ordering matters whenever several failures coincide: an earlier failure
    masks all later ones, and the response carries the earliest applicable
    error."
    PRD §2.6: "5. **Business and workflow rules** — posture gating
    (`ERR_PRODUCT_FROZEN`), segregation of duties (`ERR_SOD_SELF_REVIEW`,
    `ERR_SOD_SELF_APPROVAL`), state-machine from-state checks
    (`ERR_INVALID_STATE_TRANSITION`), taxonomy retirement (`ERR_CATEGORY_RETIRED`),
    template activeness and channel/category matching (`ERR_TEMPLATE_NOT_ACTIVE`,
    `ERR_TEMPLATE_MISMATCH`), deadline rules (`ERR_RCA_DEADLINE_PASSED`,
    `ERR_RETENTION_EXPIRED`), window-overlap rules (`ERR_REVIEW_WINDOW_OVERLAP`,
    `ERR_SNAPSHOT_WINDOW_OVERLAP`), composite gates (`ERR_RCA_REQUIRED`,
    `ERR_QA_PASS_REQUIRED`, `ERR_ESCALATION_OPEN`), the restitution authority cap
    (`ERR_RESTITUTION_OVER_AUTHORITY`), referral-open blocking
    (`ERR_REFERRAL_OPEN`), template-in-use blocking (`ERR_TEMPLATE_IN_USE`),
    review ownership (`ERR_REVIEW_NOT_OWNED`), remediability
    (`ERR_COMPLAINT_NOT_REMEDIABLE`), and finally optimistic-concurrency
    staleness (`ERR_STALE_VERSION`, HTTP 412)."

    Design: Difficulty/priority_pair_validation_conflict/referential_template_beats_constraint_rca_on_draft_response
    """
    ctx = setup_complaint("WIR-DOM", "BRANCH", "SVC.WIRE",
                          owner_id="user_intake_5", narrative="Wire delay")
    template = create_template("WIRE-ACK-DRAFT", "BRANCH", "SVC.WIRE",
                               "We acknowledge your wire complaint.")
    assert template["status"] == "DRAFT"

    cid = ctx["complaint"]["id"]
    drive_to_investigating(cid)
    # No RCA exists (violates the composite gate) AND the named template is
    # still DRAFT (violates template activeness): the template error is earlier.
    response = api.draft_response(
        cid, {"response_text": "Wire fee refunded.",
              "response_template_key": "WIRE-ACK-DRAFT"}, HANDLER,
    )
    error_data = validate_error(response, ApiErrorId.ERR_TEMPLATE_NOT_ACTIVE)
    assert error_data["error_id"] != "ERR_RCA_REQUIRED"
    assert get_complaint(cid)["status"] == "INVESTIGATING"


def test_template_not_active_single_failure_with_completed_rca(api):
    """PRD §3.5: "The draft persists `response_text` and may name a
    `response_template_key`; when a template is named it must be `ACTIVE`
    (otherwise `ERR_TEMPLATE_NOT_ACTIVE`) and its `channel_code` and
    `category_code` must both equal the complaint's own values at draft time
    (otherwise `ERR_TEMPLATE_MISMATCH`)."

    Design: Difficulty/priority_pair_validation_conflict/referential_template_beats_constraint_rca_on_draft_response
    """
    ctx = setup_complaint("WIR-INTL", "BRANCH", "SVC.WIRE2", narrative="Wire delay")
    template = create_template("WIRE-ACK-2", "BRANCH", "SVC.WIRE2", "body")

    cid = ctx["complaint"]["id"]
    drive_to_investigating(cid)
    create_and_complete_rca(cid, "SUBSTANTIATED", "WIR-INTL")

    response = api.draft_response(
        cid, {"response_text": "Wire traced.",
              "response_template_key": "WIRE-ACK-2"}, HANDLER,
    )
    validate_error(response, ApiErrorId.ERR_TEMPLATE_NOT_ACTIVE)
    assert get_complaint(cid)["status"] == "INVESTIGATING"


def test_approve_then_reverse_restores_approved_restitution_ledger(api):
    """PRD §3.6: "Approve-then-reverse is the designed compensation path and
    restores `approved_restitution_cents` to its pre-approval value."
    PRD §3.6: "On the complaint, `approved_restitution_cents` always equals the
    sum of `restitution_amount_cents` over its decisions in `APPROVED` or `PAID`
    status, and `paid_restitution_cents` the sum over decisions in `PAID` status
    alone."
    PRD §3.6: "A successful approval moves `PENDING_APPROVAL → APPROVED`, records
    the acting user as `approved_by_user_id`, recomputes the complaint's
    `approved_restitution_cents` upward by this decision's
    `restitution_amount_cents`, appends `REMEDIATION_APPROVED` to the complaint's
    audit trail, and bumps the decision's `version`."

    Design: Difficulty/compensating_invariant/approve_then_reverse_restores_approved_restitution_ledger
    """
    ctx = setup_pending_decision(
        "LEDG-PROD", "WEB", "FEES.OD",
        line_items=[{"label": "od-fee", "amount_cents": 15000}],
        drafter_id="user_handler_1",
    )
    cid = ctx["complaint"]["id"]
    did = ctx["decision"]["id"]
    assert ctx["decision"]["restitution_amount_cents"] == 15000
    assert get_complaint(cid)["approved_restitution_cents"] == 0

    approver = headers_for("RemediationApprover", "user_approver_1")
    approved = validate_success(api.approve_remediation_decision(did, approver))
    assert approved["status"] == "APPROVED"
    assert get_complaint(cid)["approved_restitution_cents"] == 15000

    reversed_decision = validate_success(api.reverse_remediation_decision(did, approver))
    assert reversed_decision["status"] == "REVERSED"

    complaint = get_complaint(cid)
    assert complaint["approved_restitution_cents"] == 0, (
        f"approve-then-reverse must restore the pre-approval ledger value, got "
        f"{complaint['approved_restitution_cents']}"
    )
    assert complaint["paid_restitution_cents"] == 0

    events = list_complaint_events(cid)
    assert_event_order(events, ["REMEDIATION_APPROVED", "REMEDIATION_REVERSED"])


def test_approve_then_mark_paid_keeps_approved_and_raises_paid(api):
    """PRD §3.6: "On the complaint, `approved_restitution_cents` always equals
    the sum of `restitution_amount_cents` over its decisions in `APPROVED` or
    `PAID` status, and `paid_restitution_cents` the sum over decisions in `PAID`
    status alone."
    PRD §3.6: "An `APPROVED` decision has two exits. A `CaseHandler` marks it
    paid, moving `APPROVED → PAID`: the complaint's `paid_restitution_cents`
    recomputes upward by the decision's amount, `REMEDIATION_PAID` is appended,
    and the decision's `version` bumps."

    Design: Difficulty/compensating_invariant/approve_then_reverse_restores_approved_restitution_ledger
    """
    ctx = setup_pending_decision(
        "LEDG-PAID", "WEB", "FEES.PAID",
        line_items=[{"label": "od-fee", "amount_cents": 15000}],
        drafter_id="user_handler_1",
    )
    cid = ctx["complaint"]["id"]
    did = ctx["decision"]["id"]

    approver = headers_for("RemediationApprover", "user_approver_1")
    validate_success(api.approve_remediation_decision(did, approver))
    paid = validate_success(api.mark_remediation_decision_paid(
        did, headers_for("CaseHandler", "user_handler_1"),
    ))
    assert paid["status"] == "PAID"

    complaint = get_complaint(cid)
    # PAID decisions remain inside the approved sum and join the paid sum.
    assert complaint["approved_restitution_cents"] == 15000
    assert complaint["paid_restitution_cents"] == 15000


def test_publish_then_supersede_preserves_single_active_template_invariant(api):
    """PRD §3.9: "Publishing moves `DRAFT → ACTIVE` — from any other state,
    `ERR_INVALID_STATE_TRANSITION` — and automatically retires any other `ACTIVE`
    template carrying the same `(channel_code, category_code)` pair, moving it to
    `RETIRED` and bumping its `version`; the published template's own `version`
    bumps as well, so at most one template per pair is ever `ACTIVE`."

    Design: Difficulty/compensating_invariant/publish_then_supersede_preserves_single_active_template_invariant
    """
    setup_reference_data("P-TA", "WEB", "GEN.SERVICE")
    tpl_a = create_template("GEN-SVC-A", "WEB", "GEN.SERVICE", "Template A body")
    publish_template(tpl_a["id"])
    assert get_template(tpl_a["id"])["status"] == "ACTIVE"

    tpl_b = create_template("GEN-SVC-B", "WEB", "GEN.SERVICE", "Template B body")
    published_b = validate_success(api.publish_response_template(tpl_b["id"], MANAGER))
    assert published_b["status"] == "ACTIVE"
    assert get_template(tpl_a["id"])["status"] == "RETIRED", (
        "publish must auto-retire the prior ACTIVE template of the same pair"
    )

    active, meta = validate_paginated(api.list_response_templates(
        MANAGER, params={"channel_code": "WEB", "category_code": "GEN.SERVICE",
                         "status": "ACTIVE"},
    ))
    assert len(active) == 1 and active[0]["id"] == tpl_b["id"], (
        f"exactly one ACTIVE template per pair must hold, got "
        f"{[t['template_key'] for t in active]}"
    )


def test_publish_in_other_pair_leaves_existing_active_untouched(api):
    """PRD §3.9: "Publishing moves `DRAFT → ACTIVE` — from any other state,
    `ERR_INVALID_STATE_TRANSITION` — and automatically retires any other `ACTIVE`
    template carrying the same `(channel_code, category_code)` pair, moving it to
    `RETIRED` and bumping its `version`; the published template's own `version`
    bumps as well, so at most one template per pair is ever `ACTIVE`."

    Design: Difficulty/compensating_invariant/publish_then_supersede_preserves_single_active_template_invariant
    """
    setup_reference_data("P-TB", "WEB", "GEN.ONE")
    create_category("GEN.TWO")

    tpl_a = create_template("GEN-ONE-A", "WEB", "GEN.ONE", "A body")
    publish_template(tpl_a["id"])
    tpl_b = create_template("GEN-ONE-B", "WEB", "GEN.ONE", "B body")
    publish_template(tpl_b["id"])
    assert get_template(tpl_a["id"])["status"] == "RETIRED"

    # A publish in a different (channel, category) pair must not retire B.
    tpl_c = create_template("GEN-TWO-C", "WEB", "GEN.TWO", "C body")
    publish_template(tpl_c["id"])
    assert get_template(tpl_b["id"])["status"] == "ACTIVE"
    assert get_template(tpl_c["id"])["status"] == "ACTIVE"

    active_one, _ = validate_paginated(api.list_response_templates(
        MANAGER, params={"channel_code": "WEB", "category_code": "GEN.ONE",
                         "status": "ACTIVE"},
    ))
    active_two, _ = validate_paginated(api.list_response_templates(
        MANAGER, params={"channel_code": "WEB", "category_code": "GEN.TWO",
                         "status": "ACTIVE"},
    ))
    assert [t["id"] for t in active_one] == [tpl_b["id"]]
    assert [t["id"] for t in active_two] == [tpl_c["id"]]
