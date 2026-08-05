"""Developer agreements, escrow ledger, OCC, and escrow conservation (PRD §2.6, §3.3)."""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated, NON_EXISTENT_UUID,
    ApiErrorId, assert_escrow_conservation,
    setup_offered_agreement, post_escrow, agreement_version,
    create_project_payload,
    make_developer_headers, TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
DEV = TEST_USERS["developer_headers"]


class TestEscrowDrawdownBoundary:
    """A DRAWDOWN of exactly escrow_held_cents succeeds and drives held to 0; a further
    DRAWDOWN of 1c is rejected — a money-metric boundary."""

    def test_drawdown_exact_held_succeeds(self, api):
        """PRD §3.3: "`escrow_held_cents` equals deposited minus drawn minus refunded."

        Design: Difficulty/boundary_precision_check/escrow_drawdown_exact_held_boundary
        """
        ctx = setup_offered_agreement(estimated_cost_cents=4000000, reimbursement_cap_cents=5000000)
        validate_success(post_escrow(ctx["agreement_id"], "DEPOSIT", 4000000,
                                     expected_version=ctx["agreement_version"]), 201)
        validate_success(post_escrow(ctx["agreement_id"], "DRAWDOWN", 4000000), 201)
        agreement = validate_success(api.get_agreement(ctx["agreement_id"], DEV), 200)
        assert agreement["escrow_held_cents"] == 0

    def test_drawdown_over_held_rejected(self, api):
        """PRD §3.3: "A `DRAWDOWN` is further constrained: its `amount_cents` may not exceed the
        current `escrow_held_cents`, or the posting is rejected with `ERR_ESCROW_INSUFFICIENT`."

        Design: Difficulty/boundary_precision_check/escrow_drawdown_exact_held_boundary
        """
        ctx = setup_offered_agreement(estimated_cost_cents=4000000, reimbursement_cap_cents=5000000)
        validate_success(post_escrow(ctx["agreement_id"], "DEPOSIT", 4000000,
                                     expected_version=ctx["agreement_version"]), 201)
        validate_success(post_escrow(ctx["agreement_id"], "DRAWDOWN", 4000000), 201)
        res = post_escrow(ctx["agreement_id"], "DRAWDOWN", 1)
        validate_error(res, ApiErrorId.ERR_ESCROW_INSUFFICIENT.value, expected_status=422)


class TestEscrowConservation:
    """Escrow dollars are conserved across deposit, drawdown, and a terminate refund."""

    def test_terminate_refunds_held_balance(self, api):
        """PRD §3.3: "an unexecuted agreement — one still in `DRAFT` or `PENDING_ESCROW` — may
        be terminated by the admin to the terminal `TERMINATED` state; if any `escrow_held_cents`
        remains at termination, a `REFUND` transaction for that held balance is appended."

        Design: Difficulty/compensating_invariant/escrow_dollar_conservation
        """
        ctx = setup_offered_agreement(estimated_cost_cents=4000000, reimbursement_cap_cents=5000000)
        validate_success(post_escrow(ctx["agreement_id"], "DEPOSIT", 4000000,
                                     expected_version=ctx["agreement_version"]), 201)
        validate_success(post_escrow(ctx["agreement_id"], "DRAWDOWN", 1000000), 201)
        agreement = validate_success(api.terminate_agreement(ctx["agreement_id"], ADMIN), 200)
        assert agreement["escrow_deposited_cents"] == 4000000
        assert agreement["escrow_drawn_cents"] == 1000000
        assert agreement["escrow_refunded_cents"] == 3000000
        assert agreement["escrow_held_cents"] == 0

    def test_conservation_invariant_holds(self, api):
        """PRD §3.3: "This holds the conservation invariant that deposited always equals held
        plus drawn plus refunded."

        Design: Difficulty/compensating_invariant/escrow_dollar_conservation
        """
        ctx = setup_offered_agreement(estimated_cost_cents=4000000, reimbursement_cap_cents=5000000)
        validate_success(post_escrow(ctx["agreement_id"], "DEPOSIT", 4000000,
                                     expected_version=ctx["agreement_version"]), 201)
        validate_success(post_escrow(ctx["agreement_id"], "DRAWDOWN", 1000000), 201)
        agreement = validate_success(api.terminate_agreement(ctx["agreement_id"], ADMIN), 200)
        assert_escrow_conservation(agreement)


def test_execute_before_escrow_funded_rejected(api):
    """PRD §3.3: "the execute action transitions `PENDING_ESCROW → EXECUTED`, and is permitted
    only when the acting developer owns the agreement and `escrow_held_cents` is at least
    `required_escrow_cents` (otherwise `ERR_ESCROW_INSUFFICIENT`, HTTP 422)."

    Design: Corner/validations/execute_before_escrow_funded_rejected
    """
    ctx = setup_offered_agreement(estimated_cost_cents=4000000, reimbursement_cap_cents=5000000)
    res = api.execute_agreement(ctx["agreement_id"], make_developer_headers("dev-1"))
    validate_error(res, ApiErrorId.ERR_ESCROW_INSUFFICIENT.value, expected_status=422)


def test_escrow_stale_version_conflict(api):
    """PRD §2.6: "A request that appends an escrow transaction must include
    `expected_developer_agreement_version` carrying the client's last-observed `version` of the
    target `DeveloperAgreement`. If that value does not equal the agreement's current `version`,
    the request is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting/escrow_occ_stale_version_conflict
    """
    ctx = setup_offered_agreement(estimated_cost_cents=4000000, reimbursement_cap_cents=5000000)
    stale_version = ctx["agreement_version"]
    # First deposit succeeds and advances the agreement version.
    validate_success(post_escrow(ctx["agreement_id"], "DEPOSIT", 1000000,
                                 expected_version=stale_version), 201)
    # Second posting still carries the pre-deposit (now stale) version.
    res = post_escrow(ctx["agreement_id"], "DEPOSIT", 1000000, expected_version=stale_version)
    validate_error(res, ApiErrorId.ERR_STALE_VERSION.value, expected_status=412)


def test_escrow_transactions_reverse_reachable(api):
    """PRD §3.3: "Each **escrow transaction** is an immutable ledger entry against an agreement,
    carrying the `developer_agreement_id`, a `txn_type` of `DEPOSIT`, `DRAWDOWN`, or `REFUND`, a
    positive `amount_cents`, and an optional free-text `memo` (defaulting to empty)."

    Design: Corner/cross_cutting/escrow_transactions_reverse_reachable_by_agreement
    """
    ctx = setup_offered_agreement(estimated_cost_cents=4000000, reimbursement_cap_cents=5000000)
    validate_success(post_escrow(ctx["agreement_id"], "DEPOSIT", 1000000,
                                 expected_version=ctx["agreement_version"]), 201)
    data, meta = validate_paginated(api.list_escrow_transactions(ctx["agreement_id"], ADMIN))
    assert meta["total_count"] == 1
    assert len(data) == 1
    assert data[0]["txn_type"] == "DEPOSIT"
    assert data[0]["amount_cents"] == 1000000


def test_create_project_unknown_application_fk_rejected(api):
    """PRD §2.8: "The same not-found treatment applies to foreign-key references supplied in a
    request body — for example, an `application_id`, `inspector_id`, `crew_id`,
    `main_extension_project_id`, `benefiting_application_id`, `developer_agreement_id`, or
    `main_extension_project_id` that does not correspond to an existing resource is rejected
    with `ERR_NOT_FOUND`."

    Design: Corner/cross_cutting/create_project_unknown_application_fk_rejected
    """
    res = api.create_project(
        create_project_payload(NON_EXISTENT_UUID, developer_user_id="dev-1",
                               length_ft=300, estimated_cost_cents=3000000,
                               total_assessable_front_ft=300, total_assessable_area_sqft=60000,
                               reimbursement_cap_cents=4000000),
        make_developer_headers("dev-1"))
    validate_error(res, ApiErrorId.ERR_NOT_FOUND.value, expected_status=404)
