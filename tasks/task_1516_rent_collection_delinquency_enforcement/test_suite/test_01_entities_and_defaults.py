"""Entity-level claims: creation echoes, declared defaults, initial states,
not-found routing, listing filters, computed fields and append-only shape."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    add_charge,
    assert_allocation,
    assert_charge,
    assert_lease,
    assert_property,
    assert_tenant,
    create_charge_payload,
    create_lease_payload,
    create_property_payload,
    create_tenant_payload,
    is_valid_uuid,
    record_and_post_payment,
    setup_property_tenant_lease,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS

PM = TEST_USERS["property_manager_headers"]
AGENT = TEST_USERS["leasing_agent_headers"]

PROPERTY_INPUT = create_property_payload()


def test_property_creation_returns_all_fields(api):
    """PRD 3.1: "The same payload fixes the property's policy constants for the life of
    every lease beneath it: `posting_priority_policy`, which selects the payment-posting
    waterfall order ... `late_fee_cap_cents`, the statutory ceiling on a single period's
    late fee; `nsf_fee_cap_cents`, the ceiling on a single returned-payment fee;
    `monthly_waiver_cap_cents`, the maximum total cents that may be waived across the
    property in one calendar month; `min_partial_payment_percent`, an integer percentage
    from 1 to 100 defining the smallest acceptable partial payment;
    `collections_threshold_cents`, the minimum move-out balance that may be sent to
    collections; `notice_cure_period_days`, the cure window granted by a pay-or-quit
    notice; `plan_cooling_off_days`, the waiting period after a defaulted plan during
    which no new plan may be drafted on that lease; `plan_setup_fee_cents`, the flat
    origination fee for a payment plan; and `plan_setup_fee_threshold_cents`, the
    covered balance at or above which that fee is charged."
    PRD 2.5: "`version` (integer):** a system-managed integer that increments by
    exactly one on every mutation of the resource, whether the mutation came from a
    client request or from an automatic system transition."

    Design: Corner/entities/property_creation_returns_all_fields
    """
    response = api.create_property(create_property_payload(), PM)
    prop = validate_success(response, 201)
    assert_property(prop)
    for field, expected in PROPERTY_INPUT.items():
        assert prop[field] == expected, f"Property.{field}: expected {expected!r}, got {prop[field]!r}"
    assert prop["version"] == 1
    assert prop["created_at"].startswith("2026-08-01"), (
        f"Property.created_at must read 2026-08-01 under the default logical clock, got {prop['created_at']!r}"
    )


def test_tenant_creation_applies_phone_default(api):
    """PRD 3.1: "A tenant record carries the tenant's `full_name`, a contact `email`
    that must be unique per tenant, and an optional `phone` that defaults to an empty
    string when omitted."

    Design: Corner/entities/tenant_creation_applies_phone_default
    """
    response = api.create_tenant(create_tenant_payload(), AGENT)
    tenant = validate_success(response, 201)
    assert_tenant(tenant)
    assert tenant["phone"] == "", f"Tenant.phone must default to empty string, got {tenant['phone']!r}"
    assert is_valid_uuid(tenant["id"])


def test_lease_created_in_draft_with_computed_defaults(api):
    """PRD 3.1: "A new lease begins life in `DRAFT` status."
    PRD 2.5: "`version` (integer):** a system-managed integer that increments by
    exactly one on every mutation of the resource, whether the mutation came from a
    client request or from an automatic system transition."

    Design: Corner/entities/lease_created_in_draft_with_computed_defaults
    """
    ctx = setup_property_tenant_lease(activate=False)
    lease = ctx["lease"]
    assert_lease(lease)
    assert lease["status"] == "DRAFT"
    assert lease["version"] == 1
    assert lease["move_out_date"] is None, "Lease.move_out_date must be null on creation"


def test_lease_get_not_found_returns_404(api):
    """PRD 2.9 rule 3: "Identifiers appearing in the URL path are validated for
    existence in left-to-right order — the lease first, then the charge, payment,
    notice, plan, dispute, or referral beneath it; the first missing identifier yields
    `ERR_NOT_FOUND`."

    Design: Corner/entities/lease_get_not_found_returns_404
    """
    response = api.get_lease(NON_EXISTENT_UUID, PM)
    validate_error(response, ApiErrorId.ERR_NOT_FOUND)


def test_lease_list_filters_by_property_and_status(api):
    """PRD 3.1: "Any of the four roles may read a lease or list leases; the listing
    accepts `property_id`, `primary_tenant_id`, and `status` as filters, with `limit`
    and `offset` for pagination."
    PRD 2.3: "List responses carry the following pagination fields in the `meta`
    object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/entities/lease_list_filters_by_property_and_status
    """
    p1 = validate_success(api.create_property(create_property_payload(name="P1"), PM), 201)
    p2 = validate_success(
        api.create_property(create_property_payload(name="P2", state_code="WA", posting_priority_policy="RENT_FIRST"), PM),
        201,
    )
    ten = validate_success(api.create_tenant(create_tenant_payload(), AGENT), 201)
    for prop, unit in ((p1, "101"), (p1, "102"), (p2, "201")):
        validate_success(
            api.create_lease(create_lease_payload(prop["id"], ten["id"], unit_label=unit), PM), 201
        )

    data, meta = validate_paginated(api.list_leases(PM, params={"property_id": p1["id"]}))
    assert meta["total_count"] == 2, f"Expected total_count 2, got {meta['total_count']}"
    assert meta["has_more"] is False
    assert len(data) == 2
    assert all(item["property_id"] == p1["id"] for item in data)

    data2, meta2 = validate_paginated(api.list_leases(PM, params={"property_id": p1["id"], "status": "ACTIVE"}))
    assert meta2["total_count"] == 0
    assert data2 == []


def test_charge_computed_outstanding_equals_amount_on_create(api):
    """PRD 3.2: "Its `outstanding_cents` is a computed figure — the face amount, minus
    waived cents, minus the net applied cents (the sum of `APPLY` allocations minus the
    sum of `REVERSE` allocations) — recomputed on every allocation, waiver, reversal,
    or dispute adjustment."
    PRD 2.9 rule 18: "Required fields are present, enum values are valid, identifiers
    are well-formed, no undeclared fields appear in the payload, and an adjusted amount
    accompanies an adjusted dispute outcome within its permitted range; otherwise
    `ERR_INVALID_REQUEST`."

    Design: Corner/entities/charge_computed_outstanding_equals_amount_on_create
    """
    ctx = setup_property_tenant_lease(activate=False)
    lease_id = ctx["lease"]["id"]

    charge = validate_success(
        api.create_charge(lease_id, create_charge_payload(amount_cents=200000), AGENT), 201
    )
    assert_charge(charge)
    assert charge["outstanding_cents"] == 200000
    assert charge["waived_cents"] == 0

    bad = dict(create_charge_payload(kind="DAMAGE_FEE", amount_cents=1000))
    bad["outstanding_cents"] = 5
    response = api.create_charge(lease_id, bad, AGENT)
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST)


def test_manual_charge_kind_restriction_rejected(api):
    """PRD 3.2: "Manual creation is restricted to the `RENT` and `DAMAGE_FEE` kinds —
    a payload naming any other kind is rejected with `ERR_INVALID_REQUEST` — and is
    allowed while the lease is `DRAFT` or `ACTIVE`; once the lease has ended, charge
    creation is rejected with `ERR_LEASE_ALREADY_ENDED`."

    Design: Corner/entities/manual_charge_kind_restriction_rejected
    """
    ctx = setup_property_tenant_lease(activate=False)
    payload = create_charge_payload(kind="LATE_FEE", amount_cents=4000)
    response = api.create_charge(ctx["lease"]["id"], payload, AGENT)
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST)


def test_allocation_rows_carry_no_version_fields(api):
    """PRD 2.5: "The payment allocation is the sole exception to this convention. As
    an append-only ledger entry it carries only `id` and `created_at`; both
    `updated_at` and `version` are absent from it."
    PRD 3.3: "Each allocation persists as an append-only payment allocation record
    carrying the `payment_id`, the `charge_id`, a `direction` of `APPLY`, the positive
    `amount_cents` moved (signed semantics come entirely from the direction), a
    one-based `allocation_order` reflecting the allocation's position within that
    posting run, and a free-text audit `note` that defaults to empty."

    Design: Corner/entities/allocation_rows_carry_no_version_fields
    """
    ctx = setup_property_tenant_lease()
    charge = add_charge(ctx["lease"]["id"], amount_cents=200000)
    payment = record_and_post_payment(ctx["lease"]["id"], ctx["tenant"]["id"], amount_cents=200000)

    listing, _meta = validate_paginated(api.list_allocations(PM, params={"payment_id": payment["id"]}))
    assert len(listing) == 1
    alloc_id = listing[0]["id"]
    alloc = validate_success(api.get_allocation(alloc_id, PM))
    assert_allocation(alloc)
    assert alloc["payment_id"] == payment["id"]
    assert alloc["charge_id"] == charge["id"]
    assert alloc["direction"] == "APPLY"
    assert alloc["amount_cents"] == 200000
    assert alloc["allocation_order"] == 1
