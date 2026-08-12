"""Common resource properties: creation defaults, system-field immunity,
append-only ledger shape, 404/400 plumbing, and pagination (PRD §2.3, §2.5,
§3.1, §3.7)."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    assert_contractor_account,
    assert_loyalty_transaction,
    create_account,
    create_product_payload,
    get_account_version,
    place_and_pay_order,
    setup_account_job_product,
    create_product,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
ASSOCIATE = TEST_USERS["associate_headers"]


def test_create_account_applies_defaults(api):
    """PRD §3.1: "A new account starts with `status` `ACTIVE`, `tier`
    `STANDARD`, and all computed balances at zero." PRD §2.5: "Every persisted
    resource carries an `id` — a server-minted UUID with no type prefix — and
    a `created_at` timestamp in ISO 8601 UTC with three fractional digits.
    Unless stated otherwise, every resource also carries `updated_at` (same
    timestamp format, refreshed on every mutation) and `version` (an integer
    that increments by 1 on every mutation of that resource)."

    Design: Corner/entities/create_contractor_account_applies_defaults
    """
    created = validate_success(
        api.create_contractor_account(
            {"company_name": "Default Co", "credit_limit_cents": 1000}, ADMIN),
        expected_status=201)
    assert_contractor_account(created)
    assert created["status"] == "ACTIVE"
    assert created["tier"] == "STANDARD"
    for field in ("outstanding_balance_cents", "loyalty_points_balance",
                  "ytd_net_volume_cents", "lifetime_rebate_paid_cents"):
        assert created[field] == 0, f"{field} must start at zero"
    assert created["version"] == 1
    readback = validate_success(
        api.get_contractor_account(created["id"], ADMIN))
    assert readback["status"] == "ACTIVE"
    assert readback["tier"] == "STANDARD"
    assert readback["version"] == 1


def test_system_fields_not_writable_through_patch(api):
    """PRD §3.1: "A `CorporateAdmin` may patch `company_name` and/or
    `credit_limit_cents`, but the request must present
    `expected_contractor_account_version` matching the account's current
    `version`, or it fails with `ERR_STALE_VERSION` as described in §2.7; a
    successful patch increments `version`." PRD §2.9: "Fields described as
    "recomputed" or "computed" — balances, spent totals, pull-through
    percentages, order totals — are derived from underlying rows and are kept
    in sync immediately whenever a contributing event lands; they are never
    stale snapshots and never client-writable."

    The declared patch surface carries only company_name and
    credit_limit_cents: after a profile patch the system-owned tier and status
    remain STANDARD and ACTIVE while version advances to 2.

    Design: Corner/entities/system_fields_not_writable_through_declared_surface
    """
    account = create_account(company_name="Sneaky Co", credit_limit_cents=1000)
    resp = api.patch_contractor_account(
        account["id"],
        {"expected_contractor_account_version": account["version"],
         "company_name": "Renamed Co"},
        ADMIN)
    patched = validate_success(resp, expected_status=200)
    assert patched["company_name"] == "Renamed Co"
    assert patched["tier"] == "STANDARD", (
        "no writable path mutates the system-owned tier")
    assert patched["status"] == "ACTIVE", (
        "no writable path mutates the system-owned status")
    assert patched["version"] == account["version"] + 1


def test_get_missing_product_returns_404(api):
    """PRD §2.8: "**Path existence**: every path identifier resolves to an
    existing resource, validated left-to-right along the URL — an unresolved
    earlier segment means later segments are never examined; otherwise
    `ERR_NOT_FOUND` (404)."

    Design: Corner/entities/get_missing_product_returns_404
    """
    resp = api.get_product(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_missing_required_sku_returns_400(api):
    """PRD §2.8: "**Shape**: required fields are present, types match, enum
    members are valid, and range constraints hold — `quantity` greater than
    zero, `voc_gpl` greater than zero, `max_voc_gpl` greater than zero,
    `specified_qty` greater than zero, `credit_limit_cents` at least zero,
    `cost_basis_cents` at least zero, `budget_cap_cents` at least zero when
    not null, `window_end` after `window_start`, `period_end` after
    `period_start`; otherwise `ERR_VALIDATION` (400)." PRD §3.3: "Products are
    created by a `CorporateAdmin` with a `sku` (unique across products, else
    `ERR_SKU_EXISTS`, HTTP 409), a `name`, a coating `category` from the same
    three values used for VOC lookup, ...".

    Design: Corner/entities/missing_required_field_returns_400
    """
    payload = create_product_payload(sku="P-X")
    del payload["sku"]
    resp = api.create_product(payload, ADMIN)
    validate_error(resp, ApiErrorId.ERR_VALIDATION)


def _setup_earn_entry(api):
    """Account with a paid order of 4 units at 20000 so an EARN entry of 800
    points exists."""
    account, _, job, product = setup_account_job_product(
        company_name="Led Co", credit_limit_cents=1_000_000,
        jurisdiction_code="WY-OPEN", jurisdiction_name="Wyoming",
        job_name="J", sku="P-LED", list_price_cents=20_000)
    order = place_and_pay_order(
        account["id"], job["id"],
        [{"product_id": product["id"], "quantity": 4}], headers=ASSOCIATE)
    return account, order


def test_loyalty_ledger_rows_are_append_only(api):
    """PRD §2.5: "Every persisted resource carries an `id` — a server-minted
    UUID with no type prefix — and a `created_at` timestamp in ISO 8601 UTC
    with three fractional digits. Unless stated otherwise, every resource also
    carries `updated_at` (same timestamp format, refreshed on every mutation)
    and `version` (an integer that increments by 1 on every mutation of that
    resource). Two ledger entities are exceptions: a return record and a
    loyalty transaction are append-only events and carry only `id` and
    `created_at` — both `updated_at` and `version` are absent from them."

    Design: Corner/entities/append_only_ledger_has_no_version
    """
    account, order = _setup_earn_entry(api)
    resp = api.list_loyalty_transactions(
        ADMIN, params={"contractor_account_id": account["id"]})
    entries, _meta = validate_paginated(resp)
    earns = [t for t in entries if t["type"] == "EARN"]
    assert len(earns) == 1, "exactly one EARN entry must exist after payment"
    earn = earns[0]
    assert_loyalty_transaction(earn)
    assert "version" not in earn, "append-only row must not expose version"
    assert "updated_at" not in earn, "append-only row must not expose updated_at"


def test_loyalty_earn_entry_values(api):
    """PRD §3.7: "Earning happens at payment: the posted `EARN` entry's
    `points_delta` is the whole dollars of merchandise — the order's
    `subtotal_cents` divided by 100 and truncated down — multiplied by the
    tier multiplier from the order's `tier_snapshot`, which is 1 for
    `STANDARD`, 2 for `SILVER`, 3 for `GOLD`, and 5 for `PLATINUM`; the floor
    is taken before the multiplication."

    The 80000-cent subtotal on a STANDARD-tier order earns
    floor(80000/100) * 1 = 800 points against the paying order.

    Design: Corner/entities/append_only_ledger_has_no_version
    """
    account, order = _setup_earn_entry(api)
    resp = api.list_loyalty_transactions(
        ADMIN, params={"contractor_account_id": account["id"]})
    entries, _meta = validate_paginated(resp)
    earns = [t for t in entries if t["type"] == "EARN"]
    assert len(earns) == 1
    assert earns[0]["points_delta"] == 800, (
        f"floor(80000/100) * 1 = 800, got {earns[0]['points_delta']}")
    assert earns[0]["order_id"] == order["id"]


def test_product_list_pagination_defaults(api):
    """PRD §2.3: "List endpoints accept two query parameters. `limit` controls
    the page size: it defaults to 10, must be at least 1, and may not exceed
    100. `offset` controls how many rows are skipped and defaults to 0. List
    responses are always sorted by `created_at` ascending. The `meta` object
    of a list response carries `limit`, `offset`, `total_count` (the full
    count of matching rows), and `has_more` (whether rows remain beyond the
    returned page)."

    With twelve products created, the default page holds 10 items with
    total_count 12 and has_more true.

    Design: Corner/entities/product_list_pagination_defaults
    """
    for i in range(12):
        create_product(sku=f"P-{i:02d}", name=f"N{i}", list_price_cents=100)
    data, meta = validate_paginated(api.list_products(ADMIN))
    assert len(data) == 10, f"default page size is 10, got {len(data)}"
    assert meta["total_count"] == 12
    assert meta["has_more"] is True


def test_product_list_limit_and_offset(api):
    """PRD §2.3: "List endpoints accept two query parameters. `limit` controls
    the page size: it defaults to 10, must be at least 1, and may not exceed
    100. `offset` controls how many rows are skipped and defaults to 0. List
    responses are always sorted by `created_at` ascending. The `meta` object
    of a list response carries `limit`, `offset`, `total_count` (the full
    count of matching rows), and `has_more` (whether rows remain beyond the
    returned page)."

    limit=5&offset=10 over twelve rows returns the final 2 with has_more
    false.

    Design: Corner/entities/product_list_pagination_defaults
    """
    for i in range(12):
        create_product(sku=f"P-{i:02d}", name=f"N{i}", list_price_cents=100)
    data, meta = validate_paginated(
        api.list_products(ADMIN, params={"limit": 5, "offset": 10}))
    assert len(data) == 2, f"the last page holds the remaining 2, got {len(data)}"
    assert meta["total_count"] == 12
    assert meta["has_more"] is False
