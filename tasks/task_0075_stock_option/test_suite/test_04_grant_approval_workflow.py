"""Grant lifecycle: draft → board → shareholder → sign (PRD §3.4)."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_grant,
    create_and_activate_plan,
    create_and_open_batch,
    create_grant_payload,
    list_audit_for_target,
    make_board_secretary_headers,
    make_grantee_headers,
    make_plan_admin_headers,
    make_shareholder_registrar_headers,
    register_grantee,
    setup_plan_batch_grantee,
    setup_plan_with_blackout,
    sign_agreement_payload,
    validate_error,
    validate_success,
)


# ---------------------------------------------------------------------------
# Draft creation (PRD §3.4)
# ---------------------------------------------------------------------------
def test_draft_grant_captured_submitted_by_actor_id(api, plan_admin_headers):
    """PRD §3.4: "The submitting administrator's X-User-ID is captured as
    submitted_by_actor_id; this captured id is the segregation-of-duties
    anchor for the rest of the approval flow."
    """
    plan, batch, grantee = setup_plan_batch_grantee()
    custom_admin = make_plan_admin_headers("admin-special-1")
    res = api.create_grant(
        plan["id"], batch["id"],
        create_grant_payload(grantee["id"]),
        custom_admin,
    )
    grant = validate_success(res, expected_status=201)
    assert_grant(grant)
    assert grant["status"] == "DRAFT"
    assert grant["submitted_by_actor_id"] == "admin-special-1"


# ---------------------------------------------------------------------------
# Board approval (PRD §3.4)
# ---------------------------------------------------------------------------
def test_board_approve_transitions_to_board_approved(api,
                                                      plan_admin_headers,
                                                      board_secretary_headers):
    """PRD §3.4: "Board approval, performed by a BoardSecretary,
    transitions the grant from DRAFT to BOARD_APPROVED."
    """
    plan, batch, grantee = setup_plan_batch_grantee()
    grant = validate_success(api.create_grant(
        plan["id"], batch["id"], create_grant_payload(grantee["id"]),
        plan_admin_headers,
    ), expected_status=201)
    res = api.board_approve_grant(grant["id"], board_secretary_headers)
    after = validate_success(res, expected_status=200)
    assert after["status"] == "BOARD_APPROVED"
    assert after["board_approval_actor_id"] == (
        board_secretary_headers["X-User-ID"]
    )


def test_board_approve_increments_pool_reserved(api, plan_admin_headers,
                                                board_secretary_headers):
    """PRD §3.4: "On success, ... pool_reserved_options increases by quantity..."
    """
    plan, batch, grantee = setup_plan_batch_grantee(pool_total_options=5000)
    grant = validate_success(api.create_grant(
        plan["id"], batch["id"],
        create_grant_payload(grantee["id"], quantity=1500),
        plan_admin_headers,
    ), expected_status=201)
    plan_before = validate_success(api.get_option_plan(
        plan["id"], plan_admin_headers,
    ), expected_status=200)
    validate_success(api.board_approve_grant(
        grant["id"], board_secretary_headers,
    ), expected_status=200)
    plan_after = validate_success(api.get_option_plan(
        plan["id"], plan_admin_headers,
    ), expected_status=200)
    assert plan_after["pool_reserved_options"] == (
        plan_before["pool_reserved_options"] + 1500
    )


def test_board_approve_rejects_same_actor_as_submitter(api,
                                                       plan_admin_headers,
                                                       board_secretary_headers):
    """PRD §3.4: "the acting X-User-ID must differ from
    submitted_by_actor_id or the operation is rejected with
    ERR_SEGREGATION_OF_DUTIES_VIOLATION."
    """
    plan, batch, grantee = setup_plan_batch_grantee()
    # Submit grant with X-User-ID 'shared-actor'.
    submitter = make_plan_admin_headers("shared-actor")
    grant = validate_success(api.create_grant(
        plan["id"], batch["id"], create_grant_payload(grantee["id"]),
        submitter,
    ), expected_status=201)
    # Now attempt /board-approve with the SAME X-User-ID under BoardSecretary.
    same_actor_board = make_board_secretary_headers("shared-actor")
    res = api.board_approve_grant(grant["id"], same_actor_board)
    validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES_VIOLATION.value)


def test_board_approve_rejected_if_pool_insufficient(api,
                                                    plan_admin_headers,
                                                    board_secretary_headers):
    """PRD §3.4: "quantity must be less than or equal to
    pool_remaining_options or it is rejected with ERR_POOL_INSUFFICIENT."
    """
    plan, batch, grantee = setup_plan_batch_grantee(pool_total_options=1000)
    grant = validate_success(api.create_grant(
        plan["id"], batch["id"],
        create_grant_payload(grantee["id"], quantity=1001),
        plan_admin_headers,
    ), expected_status=201)
    res = api.board_approve_grant(grant["id"], board_secretary_headers)
    validate_error(res, ApiErrorId.ERR_POOL_INSUFFICIENT.value)


def test_board_approve_rejects_from_wrong_state(api, plan_admin_headers,
                                                 board_secretary_headers):
    """PRD §3.4: "the grant must be in DRAFT or it is rejected with
    ERR_GRANT_NOT_IN_DRAFT."
    """
    plan, batch, grantee = setup_plan_batch_grantee()
    grant = validate_success(api.create_grant(
        plan["id"], batch["id"], create_grant_payload(grantee["id"]),
        plan_admin_headers,
    ), expected_status=201)
    validate_success(api.board_approve_grant(
        grant["id"], board_secretary_headers,
    ), expected_status=200)
    res = api.board_approve_grant(grant["id"], board_secretary_headers)
    validate_error(res, ApiErrorId.ERR_GRANT_NOT_IN_DRAFT.value)


# ---------------------------------------------------------------------------
# Shareholder approval (PRD §3.4)
# ---------------------------------------------------------------------------
def test_shareholder_approve_segregation_excludes_submitter(api,
                                                            plan_admin_headers,
                                                            board_secretary_headers):
    """PRD §3.4: "The acting X-User-ID must be neither
    submitted_by_actor_id nor board_approval_actor_id — failing this
    check yields ERR_SEGREGATION_OF_DUTIES_VIOLATION..."
    """
    plan, batch, grantee = setup_plan_batch_grantee()
    submitter = make_plan_admin_headers("shared-id-X")
    grant = validate_success(api.create_grant(
        plan["id"], batch["id"], create_grant_payload(grantee["id"]),
        submitter,
    ), expected_status=201)
    validate_success(api.board_approve_grant(
        grant["id"], board_secretary_headers,
    ), expected_status=200)
    # ShareholderRegistrar tries with the *submitter's* X-User-ID.
    sh_same_as_submitter = make_shareholder_registrar_headers("shared-id-X")
    res = api.shareholder_approve_grant(grant["id"], sh_same_as_submitter)
    validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES_VIOLATION.value)


def test_shareholder_approve_segregation_excludes_board_actor(api,
                                                              plan_admin_headers):
    """PRD §3.4: "The acting X-User-ID must be neither
    submitted_by_actor_id nor board_approval_actor_id..."
    """
    plan, batch, grantee = setup_plan_batch_grantee()
    grant = validate_success(api.create_grant(
        plan["id"], batch["id"], create_grant_payload(grantee["id"]),
        plan_admin_headers,
    ), expected_status=201)
    board_hdr = make_board_secretary_headers("board-shared-Z")
    validate_success(api.board_approve_grant(
        grant["id"], board_hdr,
    ), expected_status=200)
    # ShareholderRegistrar tries with the *board approver's* X-User-ID.
    sh_same_as_board = make_shareholder_registrar_headers("board-shared-Z")
    res = api.shareholder_approve_grant(grant["id"], sh_same_as_board)
    validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES_VIOLATION.value)


def test_shareholder_approve_rejects_from_draft(api, plan_admin_headers,
                                                shareholder_registrar_headers):
    """PRD §3.4: "the grant must be in BOARD_APPROVED or the result is
    ERR_GRANT_NOT_BOARD_APPROVED."
    """
    plan, batch, grantee = setup_plan_batch_grantee()
    grant = validate_success(api.create_grant(
        plan["id"], batch["id"], create_grant_payload(grantee["id"]),
        plan_admin_headers,
    ), expected_status=201)
    res = api.shareholder_approve_grant(
        grant["id"], shareholder_registrar_headers,
    )
    validate_error(res, ApiErrorId.ERR_GRANT_NOT_BOARD_APPROVED.value)


def test_shareholder_approve_sets_grant_date_to_plan_clock(api,
                                                            plan_admin_headers,
                                                            board_secretary_headers,
                                                            shareholder_registrar_headers):
    """PRD §3.4: "On success, ... grant_date is set to plan.current_clock_ts..."
    """
    plan, batch, grantee = setup_plan_batch_grantee()
    grant = validate_success(api.create_grant(
        plan["id"], batch["id"], create_grant_payload(grantee["id"]),
        plan_admin_headers,
    ), expected_status=201)
    validate_success(api.board_approve_grant(
        grant["id"], board_secretary_headers,
    ), expected_status=200)
    plan_now = validate_success(api.get_option_plan(
        plan["id"], plan_admin_headers,
    ), expected_status=200)
    after = validate_success(api.shareholder_approve_grant(
        grant["id"], shareholder_registrar_headers,
    ), expected_status=200)
    assert after["status"] == "SHAREHOLDER_APPROVED"
    assert after["grant_date"] == plan_now["current_clock_ts"]


# ---------------------------------------------------------------------------
# Sign agreement (PRD §3.4)
# ---------------------------------------------------------------------------
def test_sign_agreement_routes_live_when_no_blackout(api,
                                                     plan_admin_headers,
                                                     board_secretary_headers,
                                                     shareholder_registrar_headers):
    """PRD §3.4: "If no blackout is active, the grant goes to LIVE."
    """
    plan, batch, grantee = setup_plan_batch_grantee()
    grant = validate_success(api.create_grant(
        plan["id"], batch["id"], create_grant_payload(grantee["id"]),
        plan_admin_headers,
    ), expected_status=201)
    validate_success(api.board_approve_grant(
        grant["id"], board_secretary_headers,
    ), expected_status=200)
    validate_success(api.shareholder_approve_grant(
        grant["id"], shareholder_registrar_headers,
    ), expected_status=200)
    grantee_hdrs = make_grantee_headers(grantee["hr_employee_id"])
    after = validate_success(api.sign_agreement(
        grant["id"], grantee_hdrs, sign_agreement_payload(),
    ), expected_status=200)
    assert after["status"] == "LIVE"
    assert after["pinned_price_version_id"] is not None


def test_sign_agreement_routes_frozen_during_blackout(api,
                                                     plan_admin_headers,
                                                     board_secretary_headers,
                                                     shareholder_registrar_headers):
    """PRD §3.4: "If any EARNINGS_BLACKOUT or MATERIAL_EVENT_BLACKOUT
    corporate event is currently active ... the grant goes to FROZEN
    when require_live is false or omitted..."
    """
    setup = setup_plan_with_blackout()
    plan = setup["plan"]
    batch = create_and_open_batch(plan["id"])
    grantee = register_grantee(plan["id"])
    grant = validate_success(api.create_grant(
        plan["id"], batch["id"], create_grant_payload(grantee["id"]),
        plan_admin_headers,
    ), expected_status=201)
    validate_success(api.board_approve_grant(
        grant["id"], board_secretary_headers,
    ), expected_status=200)
    validate_success(api.shareholder_approve_grant(
        grant["id"], shareholder_registrar_headers,
    ), expected_status=200)
    grantee_hdrs = make_grantee_headers(grantee["hr_employee_id"])
    after = validate_success(api.sign_agreement(
        grant["id"], grantee_hdrs, sign_agreement_payload(),
    ), expected_status=200)
    assert after["status"] == "FROZEN"


def test_sign_agreement_require_live_during_blackout_rejected(api,
                                                              plan_admin_headers,
                                                              board_secretary_headers,
                                                              shareholder_registrar_headers):
    """PRD §3.4: "or the request fails with ERR_BLACKOUT_ACTIVE when
    require_live is true."
    """
    setup = setup_plan_with_blackout()
    plan = setup["plan"]
    batch = create_and_open_batch(plan["id"])
    grantee = register_grantee(plan["id"])
    grant = validate_success(api.create_grant(
        plan["id"], batch["id"], create_grant_payload(grantee["id"]),
        plan_admin_headers,
    ), expected_status=201)
    validate_success(api.board_approve_grant(
        grant["id"], board_secretary_headers,
    ), expected_status=200)
    validate_success(api.shareholder_approve_grant(
        grant["id"], shareholder_registrar_headers,
    ), expected_status=200)
    grantee_hdrs = make_grantee_headers(grantee["hr_employee_id"])
    res = api.sign_agreement(
        grant["id"], grantee_hdrs,
        sign_agreement_payload(require_live=True),
    )
    validate_error(res, ApiErrorId.ERR_BLACKOUT_ACTIVE.value)


def test_sign_agreement_pins_current_tip_version(api, plan_admin_headers,
                                                  board_secretary_headers,
                                                  shareholder_registrar_headers):
    """PRD §3.4: "the server snapshots the current tip of the batch's
    exercise-price-version chain (the row with the highest version_index
    for that batch_id) and locks it onto the grant."
    """
    from test_helpers import create_stock_split, get_tip_price_version
    plan, batch, grantee = setup_plan_batch_grantee()
    grant = validate_success(api.create_grant(
        plan["id"], batch["id"], create_grant_payload(grantee["id"]),
        plan_admin_headers,
    ), expected_status=201)
    validate_success(api.board_approve_grant(
        grant["id"], board_secretary_headers,
    ), expected_status=200)
    validate_success(api.shareholder_approve_grant(
        grant["id"], shareholder_registrar_headers,
    ), expected_status=200)
    # Reprice — adds v2 to the chain.
    create_stock_split(plan["id"], plan["current_clock_ts"], 2, 1)
    tip_after_split = get_tip_price_version(batch["id"])
    grantee_hdrs = make_grantee_headers(grantee["hr_employee_id"])
    after = validate_success(api.sign_agreement(
        grant["id"], grantee_hdrs, sign_agreement_payload(),
    ), expected_status=200)
    assert after["pinned_price_version_id"] == tip_after_split["id"]


def test_audit_entries_appended_through_approval_chain(api,
                                                       plan_admin_headers,
                                                       board_secretary_headers,
                                                       shareholder_registrar_headers):
    """PRD §3.11: "Every state-changing operation appends one
    AuditLogEntry whose action_code is one of GRANT_CREATED,
    GRANT_BOARD_APPROVED, GRANT_SHAREHOLDER_APPROVED,
    GRANT_AGREEMENT_SIGNED..."
    """
    plan, batch, grantee = setup_plan_batch_grantee()
    grant = validate_success(api.create_grant(
        plan["id"], batch["id"], create_grant_payload(grantee["id"]),
        plan_admin_headers,
    ), expected_status=201)
    validate_success(api.board_approve_grant(
        grant["id"], board_secretary_headers,
    ), expected_status=200)
    validate_success(api.shareholder_approve_grant(
        grant["id"], shareholder_registrar_headers,
    ), expected_status=200)
    grantee_hdrs = make_grantee_headers(grantee["hr_employee_id"])
    validate_success(api.sign_agreement(
        grant["id"], grantee_hdrs, sign_agreement_payload(),
    ), expected_status=200)
    entries = list_audit_for_target(plan["id"], grant["id"])
    codes = [e["action_code"] for e in entries]
    assert "GRANT_BOARD_APPROVED" in codes
    assert "GRANT_SHAREHOLDER_APPROVED" in codes
    assert "GRANT_AGREEMENT_SIGNED" in codes
