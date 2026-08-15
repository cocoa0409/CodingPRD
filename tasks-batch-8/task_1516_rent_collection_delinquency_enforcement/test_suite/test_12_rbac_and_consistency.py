"""RBAC enforcement, authentication plumbing, and the immediate read-after-write
consistency model."""
from test_helpers import (
    ApiErrorId,
    add_charge,
    create_dispute_payload,
    create_lease_payload,
    create_property_payload,
    create_tenant_payload,
    file_dispute,
    list_allocations,
    list_charges,
    post_payment,
    record_payment,
    resolve_dispute,
    setup_property_tenant_lease,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS, make_tenant_headers

PM = TEST_USERS["property_manager_headers"]
AGENT = TEST_USERS["leasing_agent_headers"]
OPS = TEST_USERS["system_ops_headers"]


def test_missing_auth_header_returns_unauthenticated(api):
    """PRD 2.1: "Every request must carry two HTTP headers: `X-User-ID`, identifying
    the acting user, and `X-User-Role`, naming their operational capacity. Exactly four
    roles are recognized, spelled precisely as follows: `PropertyManager`,
    `LeasingAgent`, `Tenant`, and `SystemOps`. A request missing either header, or
    presenting a role outside this set, is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/errors/missing_auth_header_returns_unauthenticated
    """
    ctx = setup_property_tenant_lease(activate=False)
    response = api.get_lease(ctx["lease"]["id"], headers={"Content-Type": "application/json"})
    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED)


def test_body_fk_reference_not_found(api):
    """PRD 2.9 rule 4: "Foreign keys supplied in the request body — `property_id`,
    `primary_tenant_id`, `lease_id`, `tenant_id`, and every element of `charge_ids` —
    must reference existing resources; otherwise `ERR_NOT_FOUND`."

    Design: Corner/errors/body_fk_reference_not_found
    """
    from test_helpers import NON_EXISTENT_UUID, create_payment_payload
    ctx = setup_property_tenant_lease()
    lease_id = ctx["lease"]["id"]
    add_charge(lease_id, amount_cents=200000)

    response = api.create_payment(
        create_payment_payload(lease_id, NON_EXISTENT_UUID, channel="CARD", amount_cents=200000),
        AGENT,
    )
    validate_error(response, ApiErrorId.ERR_NOT_FOUND)


def test_tenant_cannot_create_property(api):
    """PRD 2.1: "A request whose role is not permitted on the target endpoint —
    including action-level restrictions such as dispute resolution being
    `PropertyManager`-only and dispute reopening being `Tenant`-only, and ownership
    checks requiring a `Tenant` to act only on their own lease graph — is rejected with
    `ERR_UNAUTHORIZED`."
    PRD 4: "POST `/api/properties` | Create a property with its statutory caps and
    policy constants | PropertyManager"

    Design: Corner/rbac/tenant_cannot_create_property
    """
    tenant = validate_success(api.create_tenant(create_tenant_payload(), AGENT), 201)
    response = api.create_property(
        create_property_payload(name="Rogue"), make_tenant_headers(tenant["id"])
    )
    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED)


def test_agent_cannot_waive_charge(api):
    """PRD 2.1: "A request whose role is not permitted on the target endpoint —
    including action-level restrictions such as dispute resolution being
    `PropertyManager`-only and dispute reopening being `Tenant`-only, and ownership
    checks requiring a `Tenant` to act only on their own lease graph — is rejected with
    `ERR_UNAUTHORIZED`."
    PRD 4: "POST `/api/charges/{id}/waive` | Waive all or part of a charge's
    outstanding balance; full waiver flips the charge to `WAIVED` | PropertyManager"

    Design: Corner/rbac/agent_cannot_waive_charge
    """
    ctx = setup_property_tenant_lease()
    lease_id = ctx["lease"]["id"]
    charge = add_charge(lease_id, kind="DAMAGE_FEE", amount_cents=10000)

    response = api.waive_charge(charge["id"], {"amount_cents": 10000, "reason": "agent attempt"}, AGENT)
    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED)

    reread = [c for c in list_charges(lease_id) if c["id"] == charge["id"]][0]
    assert reread["status"] == "OPEN"
    assert reread["waived_cents"] == 0


def test_systemops_cannot_create_lease(api):
    """PRD 2.1: "When `X-User-Role` is `SystemOps`, `X-User-ID` is again an opaque
    operator identifier; it names the automation identity behind the delinquency sweep
    and the logical clock and carries no business-mutation rights beyond those two
    capabilities, though it may perform all read operations."

    Design: Corner/rbac/systemops_cannot_create_lease
    """
    ctx = setup_property_tenant_lease(activate=False)
    response = api.create_lease(
        create_lease_payload(ctx["property"]["id"], ctx["tenant"]["id"], unit_label="202"), OPS
    )
    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED)


def test_action_level_rbac_on_dispute_resolve_and_reopen(api):
    """PRD 3.9: "Resolution belongs to the `PropertyManager` alone — a tenant
    attempting to resolve is rejected with `ERR_UNAUTHORIZED`."
    PRD 3.9: "The filing `Tenant` — and only that tenant, by ownership — may reopen a
    `RESOLVED_UPHELD` dispute, moving it to `REOPENED` with its `reopen_count`
    incremented by one."
    PRD 2.1: "A request whose role is not permitted on the target endpoint — including
    action-level restrictions such as dispute resolution being `PropertyManager`-only
    and dispute reopening being `Tenant`-only, and ownership checks requiring a
    `Tenant` to act only on their own lease graph — is rejected with
    `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/action_level_rbac_on_dispute_resolve_and_reopen
    """
    ctx = setup_property_tenant_lease()
    lease_id = ctx["lease"]["id"]
    t1 = ctx["tenant"]["id"]
    other = validate_success(api.create_tenant(create_tenant_payload(email="other@example.com", full_name="Other Tenant"), AGENT), 201)
    charge = add_charge(lease_id, kind="DAMAGE_FEE", amount_cents=50000)
    dispute = file_dispute(lease_id, charge["id"], t1)

    # Tenant cannot RESOLVE.
    response = api.transition_dispute(dispute["id"], {"action": "RESOLVE", "outcome": "UPHELD"}, make_tenant_headers(t1))
    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED)

    resolved = resolve_dispute(dispute["id"], outcome="UPHELD")
    assert resolved["status"] == "RESOLVED_UPHELD"

    # PropertyManager cannot REOPEN; a non-owner tenant cannot REOPEN.
    response2 = api.transition_dispute(dispute["id"], {"action": "REOPEN"}, PM)
    validate_error(response2, ApiErrorId.ERR_UNAUTHORIZED)
    response3 = api.transition_dispute(dispute["id"], {"action": "REOPEN"}, make_tenant_headers(other["id"]))
    validate_error(response3, ApiErrorId.ERR_UNAUTHORIZED)

    # The filing tenant can REOPEN.
    reopened = validate_success(api.transition_dispute(dispute["id"], {"action": "REOPEN"}, make_tenant_headers(t1)))
    assert reopened["status"] == "REOPENED"


def test_tenant_read_scoping_own_lease(api):
    """PRD 2.1: "When `X-User-Role` is `Tenant`, `X-User-ID` is the `id` of the acting
    `Tenant` record; ownership checks on any resource that references a tenant compare
    the resource's tenant-referencing foreign key — a lease's `primary_tenant_id`, a
    payment's `tenant_id`, a dispute's `tenant_id` — to `X-User-ID`."

    Design: Corner/rbac/tenant_read_scoping_own_lease
    """
    ctx = setup_property_tenant_lease(activate=False)
    other = validate_success(api.create_tenant(create_tenant_payload(email="other@example.com", full_name="Other Tenant"), AGENT), 201)

    own = validate_success(api.get_lease(ctx["lease"]["id"], make_tenant_headers(ctx["tenant"]["id"])))
    assert own["id"] == ctx["lease"]["id"]

    response = api.get_lease(ctx["lease"]["id"], make_tenant_headers(other["id"]))
    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED)


def test_immediate_read_after_write_consistency(api):
    """PRD 3.3: "An accepted posting runs the payment waterfall. ... Every touched
    charge then recomputes its `outstanding_cents` and flips status per §3.2, and the
    payment records the current date as its `posted_date`. A single posting may be
    replayed by reading one allocation, or the allocation collection may be listed with
    `payment_id` and `charge_id` filters; payments themselves may be listed with
    `lease_id`, `tenant_id`, and `status` filters, and a single payment read returns
    its full record."
    PRD 2.7: "First, every mutation described anywhere in this document —
    client-driven transitions and automatic system transitions alike — refreshes the
    affected resource's `updated_at` and increments its `version` by exactly one; this
    includes cascaded mutations on notices, plans, charges, payments, referrals, and
    the lease whose draft artifacts are superseded."

    Design: Corner/consistency_model/immediate_read_after_write_consistency
    """
    ctx = setup_property_tenant_lease()
    lease_id = ctx["lease"]["id"]
    charge = add_charge(lease_id, amount_cents=200000)
    payment = record_payment(lease_id, ctx["tenant"]["id"], channel="CARD", amount_cents=50000)

    posted = post_payment(payment["id"])
    assert posted["status"] == "POSTED"

    reread = validate_success(api.get_payment(payment["id"], PM))
    assert reread["status"] == "POSTED"
    assert reread["posted_date"] == "2026-08-01"

    rent = [c for c in list_charges(lease_id) if c["id"] == charge["id"]][0]
    assert rent["outstanding_cents"] == 150000
    assert rent["status"] == "PARTIALLY_PAID"

    allocs = list_allocations(params={"payment_id": payment["id"]})
    assert len(allocs) == 1
    assert allocs[0]["direction"] == "APPLY" and allocs[0]["amount_cents"] == 50000
