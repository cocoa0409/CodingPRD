"""RBAC and entity-backed ownership: exclusive role operations and the Driver
ownership rule on settlement disputes."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS, make_driver_headers,
    create_active_lease, create_verified_operator, create_truck, create_lease,
    set_clock, create_and_issue_settlement,
    create_settlement_payload,
)

ADMIN = TEST_USERS["lease_admin_headers"]
CLERK = TEST_USERS["settlement_clerk_headers"]
OFFICER = TEST_USERS["compliance_officer_headers"]


# ─── Queue B: corner/rbac ────────────────────────────

def test_driver_cannot_create_settlement(api):
    """PRD section 2.1: "A request whose role is not permitted for the target
    endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)." PRD section 2.1:
    "The `SettlementClerk` owns the settlement lifecycle and escrow
    disbursement."

    Design: Corner/rbac/driver_cannot_create_settlement
    """
    scenario = create_active_lease()
    set_clock("2026-08-12T00:00:00Z")

    res = api.create_settlement(
        create_settlement_payload(scenario["lease"]["id"], "2026-08-03"),
        make_driver_headers(scenario["operator"]["id"]))
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_compliance_officer_cannot_activate_lease(api):
    """PRD section 2.1: "A request whose role is not permitted for the target
    endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)." PRD section 2.1:
    "the `LeaseAdmin` owns operators, trucks, lease agreements, lane offers,
    buyout-quote generation, and the logical clock."

    Design: Corner/rbac/compliance_officer_cannot_activate_lease
    """
    operator = create_verified_operator()
    truck = create_truck()
    lease = create_lease(operator["id"], truck["id"])

    res = api.activate_lease(lease["id"], OFFICER)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_ROLE.value)

    after = validate_success(api.get_lease_agreement(lease["id"], ADMIN), 200)
    assert after["status"] == "APPLICATION", "rejected activation changes nothing"


def test_driver_dispute_other_operators_settlement_forbidden(api):
    """PRD section 2.1: "When `X-User-Role` is `Driver`, `X-User-ID` is the `id`
    of the acting `OwnerOperator`; ownership checks on any resource that
    references an `OwnerOperator` (directly or through a lease's
    `owner_operator_id`) compare that foreign-key field to `X-User-ID`. A
    `Driver` acting on a resource belonging to a different operator is rejected
    with `ERR_RESOURCE_NOT_OWNED` (HTTP 403)."

    Design: Corner/rbac/driver_dispute_other_operators_settlement_forbidden
    """
    scenario_a = create_active_lease()
    scenario_b = create_active_lease()
    set_clock("2026-08-12T00:00:00Z")
    st_b = create_and_issue_settlement(scenario_b["lease"]["id"], "2026-08-03")

    # Operator A attempts to dispute a settlement on operator B's lease.
    res = api.dispute_settlement(
        st_b["id"], make_driver_headers(scenario_a["operator"]["id"]))
    validate_error(res, ApiErrorId.ERR_RESOURCE_NOT_OWNED.value)

    after = validate_success(api.get_settlement(st_b["id"], CLERK), 200)
    assert after["status"] == "ISSUED", "rejected dispute leaves the statement ISSUED"


def test_driver_dispute_own_settlement_succeeds(api):
    """PRD section 3.4: "a `Driver` whose identity matches the lease's operator
    may dispute an `ISSUED` statement, moving `ISSUED` → `DISPUTED` (wrong state:
    `ERR_SETTLEMENT_NOT_ISSUED`; wrong operator: `ERR_RESOURCE_NOT_OWNED`)."

    Design: Corner/rbac/driver_dispute_own_settlement_succeeds
    """
    scenario = create_active_lease()
    set_clock("2026-08-12T00:00:00Z")
    st = create_and_issue_settlement(scenario["lease"]["id"], "2026-08-03")

    disputed = validate_success(api.dispute_settlement(
        st["id"], make_driver_headers(scenario["operator"]["id"])), 200)
    assert disputed["status"] == "DISPUTED"
