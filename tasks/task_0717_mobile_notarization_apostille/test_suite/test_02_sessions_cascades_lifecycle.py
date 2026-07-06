"""RON session parallel state axes, apostille branching/resubmit cycle, cascade
chains, and compensating invariants on conserved quantities.
"""
import pytest

from test_helpers import (
    api_client, get_success_data, validate_success, validate_error,
    create_request_payload, create_document_payload, create_id_verification_payload,
    create_ron_session_payload, create_journal_entry_payload, create_loan_package_payload,
    TEST_USERS, make_notary_headers,
    setup_world, setup_assigned_request, setup_scheduled_session, setup_returned_apostille,
    setup_loan_package, scrub_package,
)

COORD = TEST_USERS["coordinator_headers"]
CLERK = TEST_USERS["apostille_clerk_headers"]
VIEWER = TEST_USERS["viewer_headers"]


# ─── Difficulty/non_linear_state_machine/ron_session_parallel_axes_couple_on_golive

def test_start_session_couples_both_session_axes(api):
    """PRD §3.6: "On success, that scheduled session is taken live: its `session_status`
    becomes `LIVE` and its `recording_status` becomes `RECORDING`."

    Design: Difficulty/non_linear_state_machine/ron_session_parallel_axes_couple_on_golive
    """
    world, request, document, session = setup_scheduled_session(
        request_overrides={"doc_category": "GENERAL", "delivery_mode": "RON",
                           "expected_stamp_count": 1},
        verify=True)
    nheaders = make_notary_headers(world["notary"]["id"])
    started = get_success_data(api.start_session(request["id"], nheaders))
    assert started["status"] == "IN_SESSION"

    session_after = get_success_data(api.get_ron_session(session["id"], VIEWER))
    assert session_after["session_status"] == "LIVE"
    assert session_after["recording_status"] == "RECORDING"


def test_new_session_begins_scheduled_not_started(api):
    """PRD §3.4: "A new session begins `SCHEDULED` with recording `NOT_STARTED`."

    Design: Difficulty/non_linear_state_machine/ron_session_parallel_axes_couple_on_golive
    """
    world, request, document, session = setup_scheduled_session(
        request_overrides={"doc_category": "GENERAL", "delivery_mode": "RON",
                           "expected_stamp_count": 1},
        verify=False)
    assert session["session_status"] == "SCHEDULED"
    assert session["recording_status"] == "NOT_STARTED"


# ─── Difficulty/non_linear_state_machine/apostille_order_branch_and_resubmit_cycle

def test_apostille_resubmit_cycles_returned_to_submitted(api):
    """PRD §3.8: "From `ROUTED` the clerk may authenticate it to the terminal
    `AUTHENTICATED`, or the Secretary-of-State office may return it for correction,
    moving it to `RETURNED`. A `RETURNED` order may be resubmitted back to `SUBMITTED`,
    which increments `resubmit_count` by one".

    Design: Difficulty/non_linear_state_machine/apostille_order_branch_and_resubmit_cycle
    """
    world, request, document, order = setup_returned_apostille(destination_country="FR")
    assert order["status"] == "RETURNED"
    resubmitted = get_success_data(api.resubmit_apostille_order(order["id"], CLERK))
    assert resubmitted["status"] == "SUBMITTED"
    assert resubmitted["resubmit_count"] == 1


def test_apostille_submitted_branches_to_rejected(api):
    """PRD §3.8: "alternatively, from `SUBMITTED` the clerk may reject it to the terminal
    `REJECTED`."

    Design: Difficulty/non_linear_state_machine/apostille_order_branch_and_resubmit_cycle
    """
    world, request, document, order = setup_returned_apostille(destination_country="DE")
    # The returned order is resubmitted back to SUBMITTED, then rejected (branch).
    get_success_data(api.resubmit_apostille_order(order["id"], CLERK))
    rejected = get_success_data(api.reject_apostille_order(order["id"], CLERK))
    assert rejected["status"] == "REJECTED"


# ─── Difficulty/transitive_cascade/notary_expire_cascade_depth3 ──────────────

def test_notary_expire_cascades_to_assignment_and_request(api):
    """PRD §3.1: "Expiry from either origin releases every `ACTIVE` `Assignment` held by
    that notary, moving each to `RELEASED`. Expiry specifically from the `ACTIVE` state
    cascades one level deeper: for each released assignment, if its `SigningRequest` is
    currently in `ASSIGNED`, the request reverts to `DRAFT` and its `assigned_notary_id`
    is cleared — a three-level cascade from notary to assignment to request."

    Design: Difficulty/transitive_cascade/notary_expire_cascade_depth3
    """
    world, request, document = setup_assigned_request(
        request_overrides={"doc_category": "GENERAL", "delivery_mode": "MOBILE",
                           "expected_stamp_count": 1})
    data, meta = api_client_list_assignments(api, request["id"])
    assignment_id = data[0]["id"]

    expired = get_success_data(api.expire_notary(world["notary"]["id"], COORD))
    assert expired["status"] == "EXPIRED"

    assignment_after = get_success_data(api.get_assignment(assignment_id, VIEWER))
    assert assignment_after["status"] == "RELEASED"

    request_after = get_success_data(api.get_request(request["id"], VIEWER))
    assert request_after["status"] == "DRAFT"
    assert request_after["assigned_notary_id"] in (None, "")


def test_notary_expire_releases_active_assignment(api):
    """PRD §3.1: "Expiry from either origin releases every `ACTIVE` `Assignment` held by
    that notary, moving each to `RELEASED`."

    Design: Difficulty/transitive_cascade/notary_expire_cascade_depth3
    """
    world, request, document = setup_assigned_request(
        request_overrides={"doc_category": "GENERAL", "delivery_mode": "MOBILE",
                           "expected_stamp_count": 1})
    data, meta = api_client_list_assignments(api, request["id"])
    assignment_id = data[0]["id"]
    assert data[0]["status"] == "ACTIVE"

    get_success_data(api.expire_notary(world["notary"]["id"], COORD))
    assignment_after = get_success_data(api.get_assignment(assignment_id, VIEWER))
    assert assignment_after["status"] == "RELEASED"


# ─── Difficulty/transitive_cascade/request_revise_cancels_session_depth2 ─────

def test_revise_cancels_scheduled_session(api):
    """PRD §3.5: "On success it clears `assigned_notary_id`, moves the owning
    `Assignment` to `RELEASED`, cancels any session still in `SCHEDULED` by moving its
    `session_status` to `ENDED` and `recording_status` to `ARCHIVED`, and resets
    `estimate_fee_cents` to 0."

    Design: Difficulty/transitive_cascade/request_revise_cancels_session_depth2
    """
    world, request, document, session = setup_scheduled_session(
        request_overrides={"doc_category": "GENERAL", "delivery_mode": "RON",
                           "expected_stamp_count": 1},
        verify=False)
    revised = get_success_data(api.revise_request(request["id"], COORD))
    assert revised["status"] == "DRAFT"

    session_after = get_success_data(api.get_ron_session(session["id"], VIEWER))
    assert session_after["session_status"] == "ENDED"
    assert session_after["recording_status"] == "ARCHIVED"


def test_revise_clears_assigned_notary_and_resets_estimate(api):
    """PRD §3.5: "Revision is the cyclic edge that returns an `ASSIGNED` request to
    `DRAFT` for rework."
    PRD §3.5: "On success it clears `assigned_notary_id`, moves the owning `Assignment`
    to `RELEASED`, cancels any session still in `SCHEDULED` by moving its `session_status`
    to `ENDED` and `recording_status` to `ARCHIVED`, and resets `estimate_fee_cents` to 0."

    Design: Difficulty/transitive_cascade/request_revise_cancels_session_depth2
    """
    world, request, document, session = setup_scheduled_session(
        request_overrides={"doc_category": "GENERAL", "delivery_mode": "RON",
                           "expected_stamp_count": 1},
        verify=False)
    revised = get_success_data(api.revise_request(request["id"], COORD))
    assert revised["assigned_notary_id"] in (None, "")
    assert revised["estimate_fee_cents"] == 0


# ─── Difficulty/compensating_invariant/loan_package_scrub_unscrub_preserves_fee_zero

def test_unscrub_restores_zero_fee_and_flag(api):
    """PRD §3.9: "A scrubbed package may be reverted to `DRAFT` for re-scrub, which sets
    `scrub_passed` back to false and `package_fee_cents` back to 0."

    Design: Difficulty/compensating_invariant/loan_package_scrub_unscrub_preserves_fee_zero_invariant
    """
    world, request, documents, package = setup_loan_package(
        doc_specs=[{"title": "Deed", "doc_type": "DEED", "signing_fee_cents": 5000}],
        package_overrides={"lender_ref": "LN-9", "package_discount_pct": 0})
    scrubbed = scrub_package(world, package)
    assert scrubbed["package_fee_cents"] == 5000

    nheaders = make_notary_headers(world["notary"]["id"])
    unscrubbed = get_success_data(api.unscrub_loan_package(package["id"], nheaders))
    assert unscrubbed["package_fee_cents"] == 0
    assert unscrubbed["scrub_passed"] is False
    assert unscrubbed["status"] == "DRAFT"


def test_scrub_sets_passed_and_positive_fee(api):
    """PRD §3.9: "Scrubbing the package moves it from `DRAFT` to `SCRUBBED`."
    PRD §3.9: "On success it sets `scrub_passed` to true and computes the aggregate
    `package_fee_cents`."

    Design: Difficulty/compensating_invariant/loan_package_scrub_unscrub_preserves_fee_zero_invariant
    """
    world, request, documents, package = setup_loan_package(
        doc_specs=[{"title": "Deed", "doc_type": "DEED", "signing_fee_cents": 5000}],
        package_overrides={"package_discount_pct": 0})
    assert package["scrub_passed"] is False
    assert package["package_fee_cents"] == 0
    scrubbed = scrub_package(world, package)
    assert scrubbed["scrub_passed"] is True
    assert scrubbed["package_fee_cents"] == 5000


# ─── Difficulty/compensating_invariant/request_assign_revise_preserves_notary_session_count

def test_revise_returns_active_session_count_to_zero(api):
    """PRD §2.6: "A notary's `active_session_count` is a derived field, never written
    directly: it always equals the number of that notary's RON sessions whose
    `session_status` is either `SCHEDULED` or `LIVE` (sessions in `ENDED` are excluded)".
    PRD §3.5: "cancels any session still in `SCHEDULED` by moving its `session_status` to
    `ENDED` and `recording_status` to `ARCHIVED`".

    Design: Difficulty/compensating_invariant/request_assign_revise_preserves_notary_session_count_invariant
    """
    world, request, document, session = setup_scheduled_session(
        request_overrides={"doc_category": "GENERAL", "delivery_mode": "RON",
                           "expected_stamp_count": 1},
        verify=False)
    before = get_success_data(api.get_notary(world["notary"]["id"], VIEWER))
    assert before["active_session_count"] == 1

    get_success_data(api.revise_request(request["id"], COORD))
    after = get_success_data(api.get_notary(world["notary"]["id"], VIEWER))
    assert after["active_session_count"] == 0
    request_after = get_success_data(api.get_request(request["id"], VIEWER))
    assert request_after["status"] == "DRAFT"


def test_scheduling_session_raises_active_session_count(api):
    """PRD §2.6: "it always equals the number of that notary's RON sessions whose
    `session_status` is either `SCHEDULED` or `LIVE` (sessions in `ENDED` are excluded),
    and it is reconciled whenever a session's status changes and whenever the notary is
    read."

    Design: Difficulty/compensating_invariant/request_assign_revise_preserves_notary_session_count_invariant
    """
    world, request, document, session = setup_scheduled_session(
        request_overrides={"doc_category": "GENERAL", "delivery_mode": "RON",
                           "expected_stamp_count": 1},
        verify=False)
    after = get_success_data(api.get_notary(world["notary"]["id"], VIEWER))
    assert after["active_session_count"] == 1


# ─── Corner/state_machines/new_request_starts_in_draft ───────────────────────

def test_new_request_starts_in_draft(api):
    """PRD §3.2: "A `SigningRequest` is the central workflow resource and is raised by
    `CoordinatorOps` in `DRAFT`."

    Design: Corner/state_machines/new_request_starts_in_draft
    """
    world = setup_world()
    request = get_success_data(api.create_request(
        create_request_payload(world["account"]["id"], world["signer"]["id"],
                               doc_category="GENERAL", delivery_mode="MOBILE",
                               expected_stamp_count=1), COORD))
    assert request["status"] == "DRAFT"


# ─── Corner/state_machines/cancel_already_cancelled_request_invalid_state ────

def test_cancel_already_cancelled_request_rejected(api):
    """PRD §2.8: "Sixth, the target resource's current state is checked for transition
    legality, yielding `ERR_INVALID_STATE`."
    PRD §3.5: "Cancellation is terminal and moves a request to `CANCELLED` from `DRAFT`,
    `QUOTED`, or `ASSIGNED`."

    Design: Corner/state_machines/cancel_already_cancelled_request_invalid_state
    """
    world = setup_world()
    request = get_success_data(api.create_request(
        create_request_payload(world["account"]["id"], world["signer"]["id"],
                               doc_category="GENERAL", delivery_mode="MOBILE",
                               expected_stamp_count=1), COORD))
    get_success_data(api.cancel_request(request["id"], COORD))
    res = api.cancel_request(request["id"], COORD)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


# ─── Corner/state_machines/notary_reinstate_cycle_active_again ───────────────

def test_notary_suspend_then_reinstate_returns_active(api):
    """PRD §3.1: "From `ACTIVE`, an operator may move the notary to `SUSPENDED` (a
    reversible administrative hold) provided the notary has no RON session in
    `session_status` `LIVE`".
    PRD §3.1: "From `SUSPENDED`, reinstatement returns the notary to `ACTIVE`, but only
    if `commission_expires_at` is strictly after the logical clock".

    Design: Corner/state_machines/notary_reinstate_cycle_active_again
    """
    world = setup_world()
    notary_id = world["notary"]["id"]
    get_success_data(api.suspend_notary(notary_id, COORD))
    reinstated = get_success_data(api.reinstate_notary(notary_id, COORD))
    assert reinstated["status"] == "ACTIVE"


# ─── Corner/state_machines/expire_notary_with_live_session_blocked ───────────

def test_expire_notary_with_live_session_blocked(api):
    """PRD §3.1: "From `ACTIVE`, expiry additionally requires that the notary have no
    `LIVE` session (`ERR_NOTARY_HAS_LIVE_SESSION`); from `SUSPENDED` it has no such
    precondition."

    Design: Corner/state_machines/expire_notary_with_live_session_blocked
    """
    world, request, document, session = setup_scheduled_session(
        request_overrides={"doc_category": "GENERAL", "delivery_mode": "RON",
                           "expected_stamp_count": 1},
        verify=True)
    nheaders = make_notary_headers(world["notary"]["id"])
    get_success_data(api.start_session(request["id"], nheaders))  # session now LIVE
    res = api.expire_notary(world["notary"]["id"], COORD)
    validate_error(res, "ERR_NOTARY_HAS_LIVE_SESSION", expected_status=409)


# ─── Corner/state_machines/apostille_resubmit_limit_exceeded ─────────────────

def test_apostille_resubmit_limit_exceeded(api):
    """PRD §3.8: "this cyclic resubmission is capped, and a resubmission that would push
    `resubmit_count` to 3 or beyond is refused with `ERR_RESUBMIT_LIMIT`."

    Design: Corner/state_machines/apostille_resubmit_limit_exceeded
    """
    world, request, document, order = setup_returned_apostille(destination_country="FR")
    # Cycle resubmit -> route -> return three times to reach resubmit_count=3, RETURNED.
    for _ in range(3):
        get_success_data(api.resubmit_apostille_order(order["id"], CLERK))
        get_success_data(api.route_apostille_order(order["id"], CLERK))
        get_success_data(api.return_apostille_order(order["id"], CLERK))
    res = api.resubmit_apostille_order(order["id"], CLERK)
    validate_error(res, "ERR_RESUBMIT_LIMIT", expected_status=409)


# ─── Corner/cross_cutting_complexity_layers/derived_active_session_count_after_schedule

def test_active_session_count_after_one_schedule(api):
    """PRD §2.6: "A notary's `active_session_count` is a derived field, never written
    directly: it always equals the number of that notary's RON sessions whose
    `session_status` is either `SCHEDULED` or `LIVE` (sessions in `ENDED` are excluded),
    and it is reconciled whenever a session's status changes and whenever the notary is
    read."

    Design: Corner/cross_cutting_complexity_layers/derived_active_session_count_after_schedule
    """
    world, request, document, session = setup_scheduled_session(
        request_overrides={"doc_category": "GENERAL", "delivery_mode": "RON",
                           "expected_stamp_count": 1},
        verify=False)
    notary = get_success_data(api.get_notary(world["notary"]["id"], VIEWER))
    assert notary["active_session_count"] == 1


# Helper to list assignments via the framework client (returns (data, meta)).
def api_client_list_assignments(api, request_id):
    from test_helpers import validate_paginated
    return validate_paginated(api.list_assignments(VIEWER, params={"request_id": request_id}))
