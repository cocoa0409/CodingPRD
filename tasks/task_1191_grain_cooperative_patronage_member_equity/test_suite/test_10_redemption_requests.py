"""Redemption request lifecycle: cancel, rejection branch, appeal loop,
disburse gating, fiscal-year dependency (PRD §2.10, §3.4, §3.6)."""
from test_helpers import (
    validate_success, validate_error, validate_error_is_one_of,
    validate_paginated, api_client,
    setup_under_review_request, setup_closed_final_year,
    create_redemption_request, decide_request,
    pass_resolution, set_clock, get_fiscal_year, list_member_certificates,
    make_member_headers, TEST_USERS,
)

SECRETARY = TEST_USERS["secretary_headers"]
TREASURER = TEST_USERS["treasurer_headers"]


def test_cancel_pending_request(api):
    """PRD §3.6: "A `PENDING` request may instead be cancelled by the member,
    moving it to `CANCELLED`."

    Design: Corner/state_machines/redemption_request_cancel_from_pending_works
    """
    ctx = setup_closed_final_year(
        [{"member_key": "patron", "commodity": "CORN", "gross_bushels": 100}],
    )
    member = ctx["members"]["patron"]
    certs = list_member_certificates(
        member["id"], headers=make_member_headers(member["id"]),
    )
    set_clock("2031-09-01T00:00:00Z")
    request = create_redemption_request(
        member["id"], "RETIREMENT", [certs[0]["id"]], 100,
        "2031-10-01T10:00:00Z",
    )
    assert request["status"] == "PENDING"
    cancelled = validate_success(
        api.cancel_redemption(
            request["id"], make_member_headers(member["id"]),
        ),
        200,
    )
    assert cancelled["status"] == "CANCELLED"


def test_decide_reject_moves_to_rejected(api):
    """PRD §3.6: "A rejection moves the request to `REJECTED`, and the member
    may appeal within 30 days of `decided_at`; appealing moves the original
    request to `APPEALED` and spawns a fresh request already in
    `UNDER_REVIEW` with `appeal_of_request_id` linking it to the rejected
    one."

    Design: Difficulty/non_linear_state_machine/redemption_request_branching_with_appeal_cycle
    """
    ctx = setup_under_review_request()
    request = ctx["request"]
    resolution = pass_resolution(
        "APPROVE_RETIREMENT", request["id"], ctx["delegate"]["id"],
    )
    rejected = validate_success(
        decide_request(request["id"], "REJECT", resolution["id"]), 200,
    )
    assert rejected["status"] == "REJECTED"
    # The rejection branch leaves the certificate untouched.
    cert_after = validate_success(
        api_client.get_certificate(ctx["certificate"]["id"], TREASURER), 200,
    )
    assert cert_after["status"] == "ACTIVE"


def test_appeal_spawns_linked_under_review_request(api):
    """PRD §3.6: "A rejection moves the request to `REJECTED`, and the member
    may appeal within 30 days of `decided_at`; appealing moves the original
    request to `APPEALED` and spawns a fresh request already in
    `UNDER_REVIEW` with `appeal_of_request_id` linking it to the rejected
    one."

    Design: Difficulty/non_linear_state_machine/redemption_request_branching_with_appeal_cycle
    """
    ctx = setup_under_review_request()
    member = ctx["member"]
    request = ctx["request"]
    resolution = pass_resolution(
        "APPROVE_RETIREMENT", request["id"], ctx["delegate"]["id"],
    )
    rejected = validate_success(
        decide_request(request["id"], "REJECT", resolution["id"]), 200,
    )
    assert rejected["status"] == "REJECTED"
    appealed = validate_success(
        api.appeal_redemption(request["id"], make_member_headers(member["id"])),
        200,
    )
    assert appealed["status"] == "APPEALED"
    data, _ = validate_paginated(
        api.list_redemption_requests(
            SECRETARY, params={"appeal_of_request_id": request["id"]},
        ),
    )
    assert len(data) == 1, (
        f"Expected exactly one spawned appeal request, got {len(data)}"
    )
    spawned = data[0]
    assert spawned["status"] == "UNDER_REVIEW"
    assert spawned["appeal_of_request_id"] == request["id"]


def test_disburse_pending_request_invalid_state(api):
    """PRD §2.10: "Every request is evaluated against a fixed validation
    cascade, and the order matters because earlier failures mask later ones."
    PRD §2.10: "The resource is in a valid source state for the requested
    transition — otherwise `ERR_INVALID_STATE` (HTTP 409)."
    PRD §3.6: "Disbursement is the treasurer's act: it moves an `APPROVED`
    request to `PAID` and draws down the listed certificates."

    A request still in PENDING is not APPROVED, so disbursement fails the
    state check before any fiscal rule is examined.

    Design: Difficulty/priority_pair_validation_conflict/state_vs_business_fiscal_on_redemption_disburse
    """
    ctx = setup_under_review_request()
    member = ctx["member"]
    cert = ctx["certificate"]
    # A second, fresh request that stays in PENDING.
    pending = create_redemption_request(
        member["id"], "RETIREMENT", [cert["id"]], 100,
        "2031-11-01T10:00:00Z",
    )
    assert pending["status"] == "PENDING"
    res = api.disburse_redemption(
        pending["id"],
        {"expected_certificate_versions": [cert["version"]]},
        TREASURER,
    )
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)
    after = validate_success(
        api.get_redemption_request(pending["id"], SECRETARY), 200,
    )
    assert after["status"] == "PENDING"
    cert_after = validate_success(
        api_client.get_certificate(cert["id"], TREASURER), 200,
    )
    assert cert_after["status"] == "ACTIVE"


def test_disburse_under_review_request_invalid_state(api):
    """PRD §2.10: "The resource is in a valid source state for the requested
    transition — otherwise `ERR_INVALID_STATE` (HTTP 409)."
    PRD §3.6: "Disbursement is the treasurer's act: it moves an `APPROVED`
    request to `PAID` and draws down the listed certificates."

    A request in UNDER_REVIEW has not been approved, so disbursement fails
    the state check.

    Design: Difficulty/priority_pair_validation_conflict/state_vs_business_fiscal_on_redemption_disburse
    """
    ctx = setup_under_review_request()
    request = ctx["request"]
    cert = ctx["certificate"]
    assert request["status"] == "UNDER_REVIEW"
    res = api.disburse_redemption(
        request["id"],
        {"expected_certificate_versions": [cert["version"]]},
        TREASURER,
    )
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)
    after = validate_success(
        api.get_redemption_request(request["id"], SECRETARY), 200,
    )
    assert after["status"] == "UNDER_REVIEW"


def test_decide_blocked_when_year_not_closed_final(api):
    """PRD §3.6: "The fiscal year that issued the affected certificates must
    be `CLOSED_FINAL`."
    PRD §3.4: "Reopening moves the year to `REOPENED`, clears
    `final_audit_locked`, returns all `FINALIZED` allocations for the year to
    `PROVISIONAL` pending recalculation, and moves the affected tax forms to
    `VOID` with corrected versions pending."

    With the year reopened (no longer CLOSED_FINAL), approval of a request
    under review must be refused and the request must stay UNDER_REVIEW.

    Design: Difficulty/cross_entity_state_dependency/redemption_approval_depends_on_fiscal_year_final
    """
    ctx = setup_under_review_request()
    fy = ctx["fiscal_year"]
    request = ctx["request"]
    delegate = ctx["delegate"]
    # Move the year out of CLOSED_FINAL via a PASSED AMEND_ALLOCATION.
    amend = pass_resolution("AMEND_ALLOCATION", fy["id"], delegate["id"])
    reopened = validate_success(
        api_client.reopen_fiscal_year(
            fy["id"], {"resolution_id": amend["id"]}, SECRETARY,
        ),
        200,
    )
    assert reopened["status"] == "REOPENED"
    approve_res = pass_resolution(
        "APPROVE_RETIREMENT", request["id"], delegate["id"],
    )
    res = decide_request(request["id"], "APPROVE", approve_res["id"])
    validate_error_is_one_of(
        res, ["ERR_INVALID_STATE", "ERR_COMPLIANCE_GATE", "ERR_FISCAL"],
    )
    after = validate_success(
        api.get_redemption_request(request["id"], SECRETARY), 200,
    )
    assert after["status"] == "UNDER_REVIEW", (
        "Approval must be refused while the issuing year is not "
        f"CLOSED_FINAL; request moved to {after['status']}"
    )


def test_decide_approve_when_year_closed_final(api):
    """PRD §3.6: "The fiscal year that issued the affected certificates must
    be `CLOSED_FINAL`."
    PRD §3.6: "The board decides each request under review. The
    `BoardSecretary` records the `decision` together with the `resolution_id`
    of a `PASSED` board resolution whose kind corresponds to the request's
    kind — an estate request is backed by `APPROVE_ESTATE`, a retirement
    request by `APPROVE_RETIREMENT`, and so on — and the request's
    `resolution_id` and `decided_at` are recorded."

    Design: Difficulty/cross_entity_state_dependency/redemption_approval_depends_on_fiscal_year_final
    """
    ctx = setup_under_review_request()
    fy = get_fiscal_year(ctx["fiscal_year"]["id"])
    assert fy["status"] == "CLOSED_FINAL"
    request = ctx["request"]
    resolution = pass_resolution(
        "APPROVE_RETIREMENT", request["id"], ctx["delegate"]["id"],
    )
    approved = validate_success(
        decide_request(request["id"], "APPROVE", resolution["id"]), 200,
    )
    assert approved["status"] == "APPROVED"
    assert approved["resolution_id"] == resolution["id"]
