"""State-machine lifecycle tests across complaint, referral, remediation,
escalation, template, and product resources (PRD §3.3–§3.10)."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS, headers_for,
    setup_reference_data, setup_complaint, intake_complaint,
    intake_portal_complaint, setup_resolved_complaint, setup_pending_decision,
    setup_product_with_substantiated,
    get_complaint, get_referral, get_decision, get_template, get_product,
    get_escalation, create_template,
)

MANAGER = TEST_USERS["complaint_manager_headers"]
HANDLER = TEST_USERS["case_handler_headers"]
INTAKE = TEST_USERS["intake_specialist_headers"]
EXECUTIVE = TEST_USERS["executive_reviewer_headers"]


def test_complaint_initial_state_intake(api):
    """PRD §3.2: "A successful intake stamps `received_at` from the logical
    clock, sets `status` to `INTAKE`, records the acting `X-User-ID` as
    `owner_user_id` (the anchor for later segregation-of-duties checks),
    initializes `version` at 1, appends a `CREATED` audit event, increments the
    product's `open_complaint_count` by 1, and recomputes the product's
    `posture`."

    Design: Corner/state_machines/complaint_initial_state_intake
    """
    setup_reference_data("P-SM1", "WEB", "C.SM1")
    complaint = validate_success(
        api.create_complaint(
            {"complainant_ref": "CU-SM1", "channel_code": "WEB",
             "product_code": "P-SM1", "category_code": "C.SM1", "narrative": "init"},
            INTAKE,
        ),
        expected_status=201,
    )
    assert complaint["status"] == "INTAKE"
    assert complaint["version"] == 1
    assert complaint.get("resolved_at") is None, (
        "a fresh complaint has not resolved, so resolved_at must be null"
    )


def test_complaint_invalid_transition_intake_to_resolved(api):
    """PRD §3.5: "Resolution is a `CaseHandler` action moving `RESPONSE_QA →
    RESOLVED`, guarded by two further checks evaluated after the state check: a
    `QualityReview` with `status` `COMPLETED` and `outcome` `PASS` must exist for
    the complaint (otherwise `ERR_QA_PASS_REQUIRED`), and no `EscalationCase` of
    the complaint may sit in `RAISED` or `ACKNOWLEDGED` (otherwise
    `ERR_ESCALATION_OPEN`)."
    PRD §3.3: "A `CaseHandler` triages an `INTAKE` complaint, moving `INTAKE →
    TRIAGED`; triage from any other state is `ERR_INVALID_STATE_TRANSITION`, and
    triage against a retired category is additionally blocked by
    `ERR_CATEGORY_RETIRED`."

    Design: Corner/state_machines/complaint_invalid_transition_intake_to_resolved
    """
    ctx = setup_complaint("P-SM2", "WEB", "C.SM2", narrative="skip everything")
    cid = ctx["complaint"]["id"]
    response = api.resolve_complaint(cid, HANDLER)
    validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
    after = get_complaint(cid)
    assert after["status"] == "INTAKE", f"rejected resolve must not move state: {after['status']}"
    assert after["version"] == 1, f"rejected resolve must not bump version: {after['version']}"


def test_complaint_terminal_lockdown_withdrawn_rejects_all_actions(api):
    """PRD §3.5: "Withdrawal by a `CaseHandler` or `ComplaintManager` moves a
    complaint from any non-terminal state — `INTAKE`, `TRIAGED`, `INVESTIGATING`,
    `RESPONSE_DRAFTED`, or `RESPONSE_QA` — to `WITHDRAWN`; from any other state
    the request is `ERR_INVALID_STATE_TRANSITION`."
    PRD §3.3: "A `CaseHandler` triages an `INTAKE` complaint, moving `INTAKE →
    TRIAGED`; triage from any other state is `ERR_INVALID_STATE_TRANSITION`, and
    triage against a retired category is additionally blocked by
    `ERR_CATEGORY_RETIRED`."
    PRD §3.5: "A successful reopen moves `RESOLVED → REOPENED`, clears both
    `resolved_at` and `retention_purge_at` to null, increments the product's
    `open_complaint_count` by 1, recomputes `posture`, appends `REOPENED`, and
    bumps `version`."

    Design: Corner/state_machines/complaint_terminal_lockdown_withdrawn_rejects_all_actions
    """
    ctx = setup_complaint("P-SM3", "WEB", "C.SM3", narrative="to withdraw")
    cid = ctx["complaint"]["id"]
    withdrawn = validate_success(api.withdraw_complaint(cid, HANDLER))
    assert withdrawn["status"] == "WITHDRAWN"

    for action in (api.triage_complaint, api.reopen_complaint, api.withdraw_complaint):
        response = action(cid, HANDLER)
        validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
    after = get_complaint(cid)
    assert after["status"] == "WITHDRAWN"


def test_complaint_resolve_is_not_idempotent(api):
    """PRD §3.5: "Resolution is a `CaseHandler` action moving `RESPONSE_QA →
    RESOLVED`, guarded by two further checks evaluated after the state check: a
    `QualityReview` with `status` `COMPLETED` and `outcome` `PASS` must exist for
    the complaint (otherwise `ERR_QA_PASS_REQUIRED`), and no `EscalationCase` of
    the complaint may sit in `RAISED` or `ACKNOWLEDGED` (otherwise
    `ERR_ESCALATION_OPEN`)."

    Design: Corner/state_machines/complaint_resolve_is_not_idempotent
    """
    ctx = setup_resolved_complaint("P-SM4", "WEB", "C.SM4", verdict="NOT_SUBSTANTIATED",
                                   owner_id="user_intake_sm4", reviewer_id="user_qa_sm4",
                                   window_end_at="2026-08-05T00:00:00Z")
    cid = ctx["complaint"]["id"]
    assert ctx["complaint"]["status"] == "RESOLVED"
    response = api.resolve_complaint(cid, HANDLER)
    validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
    assert get_complaint(cid)["status"] == "RESOLVED"


def test_referral_close_from_open_rejected(api):
    """PRD §3.8: "From `RESPONSE_SUBMITTED` a `ComplaintManager` may close the
    referral, moving it to the terminal `CLOSED_BY_REGULATOR`, or register a
    regulator reopen, moving it `RESPONSE_SUBMITTED → REOPENED_BY_REGULATOR`."
    PRD §3.2: "The referral opens in `OPEN` status with `timeliness` `PENDING`
    and `submitted_at` null, and a `REFERRAL_FILED` event lands on the
    complaint's audit trail."

    Design: Corner/state_machines/referral_close_from_open_rejected
    """
    complaint, referral = intake_portal_complaint(
        "P-SM5", "CFPB_PORTAL", "C.SM5", narrative="close early", portal_ref="R-SM5",
    )
    assert referral["status"] == "OPEN"
    response = api.close_referral(referral["id"], MANAGER)
    validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
    assert get_referral(referral["id"])["status"] == "OPEN"


def test_remediation_reject_is_terminal_and_pay_after_reject_fails(api):
    """PRD §3.6: "`PAID`, `REJECTED`, and `REVERSED` are all terminal."
    PRD §3.6: "An `APPROVED` decision has two exits. A `CaseHandler` marks it
    paid, moving `APPROVED → PAID`: the complaint's `paid_restitution_cents`
    recomputes upward by the decision's amount, `REMEDIATION_PAID` is appended,
    and the decision's `version` bumps."

    Design: Corner/state_machines/remediation_reject_is_terminal_and_pay_after_reject_fails
    """
    ctx = setup_pending_decision(
        "P-SM6", "WEB", "C.SM6",
        line_items=[{"label": "fee", "amount_cents": 5000}],
        drafter_id="user_handler_sm6",
    )
    did = ctx["decision"]["id"]
    rejected = validate_success(api.reject_remediation_decision(
        did, headers_for("RemediationApprover", "user_approver_sm6"),
    ))
    assert rejected["status"] == "REJECTED"

    response = api.mark_remediation_decision_paid(
        did, headers_for("CaseHandler", "user_handler_sm6"),
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
    assert get_decision(did)["status"] == "REJECTED"


def test_escalation_full_happy_path_and_dismiss_from_acknowledged_fails(api):
    """PRD §3.9: "A `CaseHandler` or `ComplaintManager` raises an
    `EscalationCase` on a complaint by supplying an `escalation_tier` of
    `EXECUTIVE` or `LEGAL` and a free-text `reason`; the case opens `RAISED` with
    `raised_by_user_id` set to the acting user and an `ESCALATED` event appended
    to the complaint. From there an `ExecutiveReviewer` acknowledges the case
    (`RAISED → ACKNOWLEDGED`), resolves an acknowledged case (`ACKNOWLEDGED →
    RESOLVED`, appending `ESCALATION_RESOLVED` on the parent complaint), or
    dismisses a raised case outright (`RAISED → DISMISSED`)."

    Design: Corner/state_machines/escalation_full_happy_path_and_dismiss_from_acknowledged_fails
    """
    ctx = setup_complaint("P-SM7", "WEB", "C.SM7", narrative="escalate me")
    cid = ctx["complaint"]["id"]
    escalation = validate_success(
        api.create_escalation(cid, {"escalation_tier": "LEGAL",
                                    "reason": "Litigation hold risk"}, HANDLER),
        expected_status=201,
    )
    eid = escalation["id"]
    acknowledged = validate_success(api.acknowledge_escalation(eid, EXECUTIVE))
    assert acknowledged["status"] == "ACKNOWLEDGED"

    response = api.dismiss_escalation(eid, EXECUTIVE)
    validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

    resolved = validate_success(api.resolve_escalation(eid, EXECUTIVE))
    assert resolved["status"] == "RESOLVED", (
        "ACKNOWLEDGED -> RESOLVED is the declared happy path"
    )
    assert get_escalation(eid)["status"] == "RESOLVED"


def test_template_retire_from_draft_rejected(api):
    """PRD §3.9: "Retiring an `ACTIVE` template directly is blocked with
    `ERR_TEMPLATE_IN_USE` while any complaint in `RESPONSE_DRAFTED` or
    `RESPONSE_QA` references it via `response_template_key`; otherwise it moves
    to the terminal `RETIRED` with a version bump."
    PRD §3.9: "Publishing moves `DRAFT → ACTIVE` — from any other state,
    `ERR_INVALID_STATE_TRANSITION` — and automatically retires any other `ACTIVE`
    template carrying the same `(channel_code, category_code)` pair, moving it to
    `RETIRED` and bumping its `version`; the published template's own `version`
    bumps as well, so at most one template per pair is ever `ACTIVE`."

    Design: Corner/state_machines/template_retire_from_draft_rejected
    """
    setup_reference_data("P-TPL", "WEB", "C.TPL")
    template = create_template("TPL-DRAFT", "WEB", "C.TPL", "draft body")
    assert template["status"] == "DRAFT"
    response = api.retire_response_template(template["id"], MANAGER)
    validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
    assert get_template(template["id"])["status"] == "DRAFT"


def test_product_manual_unfreeze_moves_frozen_to_watch(api):
    """PRD §3.10: "A `ComplaintManager` may also unfreeze a `FROZEN` product
    manually, moving it to `WATCH` and bumping the product's `version`; the
    system path back from `FROZEN` to `WATCH` fires on its own whenever a
    recompute finds `substantiated_count_90d` below 5."
    PRD §3.10: "While a product is `FROZEN`, complaint intake on it is rejected
    with `ERR_PRODUCT_FROZEN`."

    Design: Corner/state_machines/product_manual_unfreeze_moves_frozen_to_watch
    """
    ctx = setup_product_with_substantiated("P-SM8", 5, "WEB", "C.SM8")
    pid = ctx["product"]["id"]
    assert get_product(pid)["posture"] == "FROZEN"

    blocked = api.create_complaint(
        {"complainant_ref": "CU-SM8-B", "channel_code": "WEB",
         "product_code": "P-SM8", "category_code": "C.SM8", "narrative": "frozen"},
        INTAKE,
    )
    validate_error(blocked, ApiErrorId.ERR_PRODUCT_FROZEN)

    unfrozen = validate_success(api.unfreeze_product(pid, MANAGER))
    assert unfrozen["posture"] == "WATCH", (
        f"manual unfreeze must land on WATCH, got {unfrozen['posture']}"
    )
    assert get_product(pid)["posture"] == "WATCH"

    complaint = intake_complaint("P-SM8", "WEB", "C.SM8", narrative="after unfreeze")
    assert complaint["status"] == "INTAKE", (
        "intake gates only on FROZEN, so a WATCH product accepts new complaints"
    )
