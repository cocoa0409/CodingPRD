"""Single-failure validation probes and error-catalogue triggers."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    make_client_headers,
    create_studio,
    setup_studio_client,
    create_draft_project,
    add_milestone,
    create_and_activate_project,
    create_project_in_concept,
    create_project_in_delivery,
    create_project_in_handoff,
    create_active_retainer,
    create_change_order_payload,
    create_care_cycle_payload,
    issue_invoice,
    set_clock,
)

SO = TEST_USERS["studio_ops_headers"]
DES = TEST_USERS["designer_headers"]
BO = TEST_USERS["billing_ops_headers"]


def test_activate_without_milestones_rejected(api):
    """PRD §3.2: "Activation is refused unless the project has at least one milestone
    — otherwise ERR_NO_MILESTONES"

    Design: Corner/validations/activate_without_milestones_no_milestones_error
    """
    studio, client = setup_studio_client()
    project = create_draft_project(studio["id"], client["id"], deposit_pct=0.30)
    resp = api.activate_project(studio["id"], project["id"], SO)
    validate_error(resp, ApiErrorId.ERR_NO_MILESTONES.value)


def test_activate_with_archived_client_rejected(api):
    """PRD §3.2: "and unless its client_id references a client whose status is ACTIVE
    — otherwise ERR_CLIENT_NOT_ACTIVE"

    Design: Corner/validations/activate_with_archived_client_not_active_error
    """
    studio, client = setup_studio_client()
    sid, cid = studio["id"], client["id"]
    project = create_draft_project(sid, cid, deposit_pct=0.30)
    add_milestone(sid, project["id"], 10000, 1)
    get_success_data(api.archive_client(sid, cid, SO))
    resp = api.activate_project(sid, project["id"], SO)
    validate_error(resp, ApiErrorId.ERR_CLIENT_NOT_ACTIVE.value)


def test_advance_discovery_without_approved_moodboard_rejected(api):
    """PRD §3.3: "This advance is permitted only when at least one moodboard on the
    project has reached APPROVED; if none has, the advance is rejected with
    ERR_MOODBOARD_NOT_APPROVED."

    Design: Corner/validations/advance_discovery_without_approved_moodboard_error
    """
    studio, client, project, _ = create_and_activate_project([10000], deposit_pct=0.30)
    sid, pid = studio["id"], project["id"]
    mb = get_success_data(api.create_moodboard(sid, pid, {"title": "MB"}, DES))
    get_success_data(api.submit_moodboard(sid, pid, mb["id"], DES))  # SUBMITTED, not approved
    resp = api.advance_project(sid, pid, SO)
    validate_error(resp, ApiErrorId.ERR_MOODBOARD_NOT_APPROVED.value)


def test_advance_to_handoff_with_pending_required_deliverable_rejected(api):
    """PRD §3.5: "every deliverable whose is_required_for_handoff is true must be in
    ACCEPTED; if any required deliverable is not yet accepted, the advance is
    rejected with ERR_DELIVERABLES_INCOMPLETE."

    Design: Corner/validations/advance_delivery_handoff_deliverables_incomplete_error
    """
    studio, client, project, _ = create_project_in_delivery([10000], deposit_pct=0.0, tax_rate=0.0)
    sid, pid = studio["id"], project["id"]
    get_success_data(
        api.create_deliverable(sid, pid, {"asset_type": "BRAND_GUIDE", "is_required_for_handoff": True}, DES)
    )  # still PENDING
    resp = api.advance_project(sid, pid, SO)
    validate_error(resp, ApiErrorId.ERR_DELIVERABLES_INCOMPLETE.value)


def test_advance_to_handoff_with_unpaid_deposit_rejected(api):
    """PRD §3.5: "the project's deposit_collected_cents must be at least its
    final_deposit_cents; if the collected deposit falls short, the advance is
    rejected with ERR_DEPOSIT_UNPAID (HTTP 402)."

    Design: Corner/validations/advance_delivery_handoff_deposit_unpaid_error
    """
    # deposit_pct 0.30, final_deposit 12000, nothing collected; deliverable accepted
    studio, client, project, milestones = create_project_in_delivery(
        [40000], deposit_pct=0.30, tax_rate=0.0, deposit_cents=0
    )
    sid, pid, cid = studio["id"], project["id"], client["id"]
    deliverable = get_success_data(
        api.create_deliverable(sid, pid, {"asset_type": "BRAND_GUIDE", "is_required_for_handoff": True}, DES)
    )
    get_success_data(api.deliver_deliverable(sid, pid, deliverable["id"], DES))
    get_success_data(api.accept_deliverable(sid, pid, deliverable["id"], make_client_headers(cid)))
    resp = api.advance_project(sid, pid, SO)
    validate_error(resp, ApiErrorId.ERR_DEPOSIT_UNPAID.value)


def test_complete_with_open_invoice_rejected(api):
    """PRD §3.5: "Completion is refused if any invoice on the project is still in
    ISSUED or OVERDUE — the project may not close over open invoices — yielding
    ERR_OPEN_INVOICES."

    Design: Corner/validations/complete_with_open_invoice_blocked_error
    """
    studio, client, project, milestones, deliverable = create_project_in_handoff(
        [40000], deposit_pct=0.0, tax_rate=0.0, asset_type="BRAND_GUIDE"
    )
    sid, pid = studio["id"], project["id"]
    # issue an invoice on the 40000 milestone, leave it ISSUED
    issue_invoice(sid, milestones[0]["id"], "2026-04-01T00:00:00Z")
    resp = api.complete_project(sid, pid, SO)
    validate_error(resp, ApiErrorId.ERR_OPEN_INVOICES.value)


def test_issue_invoice_for_zero_amount_milestone_rejected(api):
    """PRD §3.6: "only for a milestone whose amount_cents is greater than zero — a
    zero-amount milestone cannot be invoiced and the attempt is rejected with
    ERR_ZERO_AMOUNT_MILESTONE."

    Design: Corner/validations/issue_invoice_zero_amount_milestone_error
    """
    studio, client, project, milestones = create_project_in_delivery(
        [0], deposit_pct=0.0, tax_rate=0.0
    )
    sid = studio["id"]
    resp = api.create_invoice(sid, {"milestone_id": milestones[0]["id"], "due_date": "2026-04-01T00:00:00Z"}, BO)
    validate_error(resp, ApiErrorId.ERR_ZERO_AMOUNT_MILESTONE.value)


def test_mark_overdue_before_due_date_rejected(api):
    """PRD §3.6: "but only once the logical clock has advanced strictly beyond the
    invoice's due_date; calling mark-overdue before that instant is rejected with
    ERR_NOT_YET_DUE."

    Design: Corner/validations/mark_overdue_before_due_date_not_yet_due_error
    """
    set_clock("2026-03-01T00:00:00Z", BO)
    studio, client, project, milestones = create_project_in_delivery(
        [40000], deposit_pct=0.0, tax_rate=0.0
    )
    sid = studio["id"]
    inv = issue_invoice(sid, milestones[0]["id"], "2026-05-01T00:00:00Z")
    resp = api.mark_invoice_overdue(sid, inv["id"], BO)
    validate_error(resp, ApiErrorId.ERR_NOT_YET_DUE.value)


def test_retainer_cancel_with_open_cycle_rejected(api):
    """PRD §3.10: "Both pausing and cancelling are blocked while any care cycle on
    the retainer is still OPEN: such an attempt is rejected with ERR_OPEN_CYCLE."

    Design: Corner/validations/retainer_cancel_with_open_cycle_blocked
    """
    set_clock("2026-03-01T00:00:00Z", SO)
    sid, cid, retainer = create_active_retainer()
    rid = retainer["id"]
    get_success_data(api.create_care_cycle(
        sid, rid, create_care_cycle_payload("2026-03-01T00:00:00Z", "2026-04-01T00:00:00Z", hours_used=2), SO
    ))
    resp = api.cancel_retainer(sid, rid, SO)
    validate_error(resp, ApiErrorId.ERR_OPEN_CYCLE.value)


def test_existence_checked_before_state_on_unknown_invoice_pay(api):
    """PRD §2.12: "Existence follows: any path- or body-referenced resource that does
    not resolve yields ERR_NOT_FOUND, validated left to right through the path."

    Design: Corner/validations/priority_existence_before_state_on_unknown_invoice_pay
    """
    studio = create_studio()
    resp = api.pay_invoice(studio["id"], "00000000-0000-4000-8000-000000000009", BO)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_change_order_create_with_stale_version_returns_412(api):
    """PRD §2.7: "If they do not match — which happens precisely when some other
    writer has approved a change order and thereby advanced the project's version
    since the client last read it — the creation is rejected with
    ERR_STALE_PROJECT_VERSION and HTTP status 412"

    Design: Corner/errors/error_stale_project_version_triggerable
    """
    from test_helpers import propose_change_order, approve_change_order
    studio, client, project, _ = create_project_in_concept([100000], deposit_pct=0.30, service_type="IDENTITY")
    sid, pid, cid = studio["id"], project["id"], client["id"]
    pv = validate_success(api.get_project(sid, pid, SO))["version"]
    co1 = propose_change_order(sid, pid, 50000, pv, reason="SCOPE_ADD")
    approve_change_order(sid, co1["id"], cid)  # bumps project.version

    resp = api.create_change_order(sid, create_change_order_payload(pid, 10000, pv, reason="SCOPE_ADD"), SO)
    validate_error(resp, ApiErrorId.ERR_STALE_PROJECT_VERSION.value)


def test_missing_auth_headers_unauthenticated(api):
    """PRD §2.1: "If either header is missing, or if X-User-Role is not one of the
    recognized roles, the request is rejected with ERR_UNAUTHENTICATED."

    Design: Corner/errors/error_unauthenticated_missing_headers
    """
    resp = api.create_studio({"name": "S"}, headers={})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


def test_approve_change_order_on_draft_project_not_activated(api):
    """PRD §3.8: "and only when the project has actually been activated, since a
    project still in DRAFT has no ledger to amend, otherwise
    ERR_PROJECT_NOT_ACTIVATED."

    Design: Corner/errors/error_change_order_not_activated_on_draft_project
    """
    studio, client = setup_studio_client()
    sid, cid = studio["id"], client["id"]
    project = create_draft_project(sid, cid, deposit_pct=0.30)
    pid, pv = project["id"], project["version"]
    co = get_success_data(
        api.create_change_order(sid, create_change_order_payload(pid, 5000, pv, reason="SCOPE_ADD"), SO)
    )
    resp = api.approve_change_order(sid, co["id"], make_client_headers(cid))
    validate_error(resp, ApiErrorId.ERR_PROJECT_NOT_ACTIVATED.value)
