"""1035 exchange cyclic revision loop, inbound-settle state guard, segregation
of duties, OCC on approve, and referenced-FK existence on crediting.

Difficulty-queue instances each carry >=2 tests; several corner-design error
instances are also translated here.
"""
import pytest
from test_helpers import (
    validate_success, validate_error,
    setup_outbound_exchange_submitted, setup_outbound_exchange_revision_requested,
    setup_inbound_exchange_approved_premium_submitted,
    setup_active_indexed_contract,
    make_contract_admin_headers, make_compliance_officer_headers,
    create_crediting_event_payload,
    TEST_USERS,
)

ADMIN = TEST_USERS["contract_admin_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]
CREDITING = TEST_USERS["crediting_officer_headers"]


# ─── non_linear_state_machine / exchange1035_cyclic_submit_revision_loop ──
def test_exchange_resubmit_increments_revision_count(api):
    """PRD §3.10: "Re-submitting a `REVISION_REQUESTED` exchange moves it back
    to `SUBMITTED`, increments its `revision_count` by one, and bumps its
    `version` — this is the revision loop."

    Design: Difficulty/non_linear_state_machine/exchange1035_cyclic_submit_revision_loop
    """
    source, exchange = setup_outbound_exchange_revision_requested(submitter_user_id="submitter-1")
    assert exchange["status"] == "REVISION_REQUESTED"
    resubmitted = validate_success(
        api.submit_exchange(exchange["id"], make_contract_admin_headers("submitter-1")), 200)
    assert resubmitted["status"] == "SUBMITTED"
    assert resubmitted["revision_count"] == 1


def test_exchange_revision_count_starts_zero_before_loop(api):
    """PRD §3.10: "The exchange tracks a `revision_count` that starts at 0".
    PRD §3.10: "A `ComplianceOfficer` may request a revision, moving a
    `SUBMITTED` exchange to `REVISION_REQUESTED` and bumping its `version`."

    Design: Difficulty/non_linear_state_machine/exchange1035_cyclic_submit_revision_loop
    """
    source, exchange = setup_outbound_exchange_submitted(submitter_user_id="submitter-1")
    assert exchange["revision_count"] == 0
    revised = validate_success(api.request_revision_exchange(exchange["id"], COMPLIANCE), 200)
    assert revised["status"] == "REVISION_REQUESTED"
    assert revised["revision_count"] == 0


# ─── cross_entity_state_dependency / exchange_inbound_settle_requires_cleared_premium ─
def test_inbound_settle_blocked_when_funding_premium_not_cleared(api):
    """PRD §3.10: "For an `INBOUND` exchange, settling requires that a premium
    on the `target_contract_id` carrying this exchange as its
    `source_exchange_id` already exists and is `CLEARED`."

    Design: Difficulty/cross_entity_state_dependency/exchange_inbound_settle_requires_cleared_premium_on_target
    """
    target, exchange, premium = setup_inbound_exchange_approved_premium_submitted(
        submitter_user_id="admin-submitter", approver_user_id="compliance-approver")
    assert exchange["status"] == "APPROVED"
    res = api.settle_exchange(exchange["id"], COMPLIANCE)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)
    after = validate_success(api.get_exchange(exchange["id"], COMPLIANCE), 200)
    assert after["status"] == "APPROVED"


def test_inbound_settle_succeeds_after_funding_premium_cleared(api):
    """PRD §3.10: "For an `INBOUND` exchange, settling requires that a premium
    on the `target_contract_id` carrying this exchange as its
    `source_exchange_id` already exists and is `CLEARED`."
    PRD §3.10: "A `ComplianceOfficer` settles an `APPROVED` exchange, moving it
    to `SETTLED` and bumping `version`."

    Design: Difficulty/cross_entity_state_dependency/exchange_inbound_settle_requires_cleared_premium_on_target
    """
    target, exchange, premium = setup_inbound_exchange_approved_premium_submitted(
        submitter_user_id="admin-submitter", approver_user_id="compliance-approver")
    validate_success(api.clear_premium(premium["id"], ADMIN), 200)
    settled = validate_success(api.settle_exchange(exchange["id"], COMPLIANCE), 200)
    assert settled["status"] == "SETTLED"


# ─── errors / error_segregation_of_duties_already_difficulty (corner) ─────
def test_submitter_cannot_approve_own_exchange(api):
    """PRD §3.10: "Approving a `SUBMITTED` exchange requires both that the
    approver's `X-User-ID` differ from the recorded submitter's `X-User-ID` —
    otherwise `ERR_SEGREGATION_OF_DUTIES`".

    Design: Corner/errors/error_segregation_of_duties_already_difficulty
    """
    source, exchange = setup_outbound_exchange_submitted(submitter_user_id="same_user")
    res = api.approve_exchange(
        exchange["id"], {"expected_exchange_version": exchange["version"]},
        make_compliance_officer_headers("same_user"))
    validate_error(res, "ERR_SEGREGATION_OF_DUTIES", expected_status=409)


def test_stale_exchange_version_on_approve_rejected(api):
    """PRD §2.6: "Approving a 1035 exchange requires `expected_exchange_version`
    to match the target `Exchange1035`'s current `version`. Because a
    request-revision-and-resubmit cycle bumps the exchange's version, an
    approval carrying a stale version refers to a superseded revision and is
    rejected with `ERR_STALE_EXCHANGE_VERSION` (HTTP 412)."

    Design: Corner/errors/error_stale_exchange_version_occ
    """
    source, exchange = setup_outbound_exchange_submitted(submitter_user_id="submitter1")
    stale_version = exchange["version"]
    # A revision cycle advances the version past `stale_version`.
    validate_success(api.request_revision_exchange(exchange["id"], COMPLIANCE), 200)
    validate_success(
        api.submit_exchange(exchange["id"], make_contract_admin_headers("submitter1")), 200)
    res = api.approve_exchange(
        exchange["id"], {"expected_exchange_version": stale_version},
        make_compliance_officer_headers("approver2"))
    validate_error(res, "ERR_STALE_EXCHANGE_VERSION", expected_status=412)


def test_referenced_segment_not_found_on_crediting(api):
    """PRD §2.8: "A foreign-key field carried in a request body — such as
    ... `source_segment_id` ... that points at a non-existent resource is
    instead rejected with `ERR_REFERENCED_RESOURCE_NOT_FOUND` (HTTP 404)."

    Design: Corner/errors/error_referenced_segment_not_found_on_crediting
    """
    product, contract, _ = setup_active_indexed_contract(
        gross_premium_cents=2_000_000,
        surrender_charge_schedule=[{"contract_year": 0, "charge_bps": 0}])
    res = api.create_crediting_event(create_crediting_event_payload(
        contract["id"], "INDEX_SEGMENT",
        source_segment_id="22222222-2222-4222-8222-222222222222",
        raw_index_return_bps=500, credit_period_start="2026-01-01T00:00:00Z",
        credit_period_end="2026-06-01T00:00:00Z"), CREDITING)
    validate_error(res, "ERR_REFERENCED_RESOURCE_NOT_FOUND", expected_status=404)
