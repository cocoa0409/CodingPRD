"""Plans, SKUs, stock adjustments, pack pricing and the shared request-shape rules."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_plan,
    assert_sku,
    cycle_lines,
    make_sku,
    read_cycle,
    register_and_verify_account,
    set_clock,
    setup_household,
    unique_code,
    unique_email,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import allocate_cycle, generate_cycle, make_account_holder_headers

OPS = TEST_USERS["ops_admin_headers"]


def test_sku_creation_applies_the_declared_catalog_defaults(api):
    """PRD §3.3: "a `pack_size_units` count of diaper units per pack that defaults to 60
    and must lie between 1 and 200 inclusive"
    PRD §3.3: "It also carries `allergen_tags`, an array of the materials present in the
    pack, defaulting to an empty array and screened against the receiving child's
    sensitivity flags. Stock is tracked as `stock_packs`, which defaults to 0 and is
    decremented whenever packs are allocated or gifted out. A SKU's `status` starts at
    `ACTIVE` and its only other member is `DISCONTINUED`."

    Design: Corner/entities/corner_sku_defaults_pack_size_units_and_stock_and_status
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    data = validate_success(
        api.create_sku(
            {
                "code": unique_code("S3-DEF"),
                "name": "Stage 3 Default",
                "stage": "S3",
                "line": "STANDARD",
                "pack_price_cents": 1500,
            },
            OPS,
        ),
        201,
    )
    assert_sku(data)
    assert data["pack_size_units"] == 60
    assert data["stock_packs"] == 0
    assert data["status"] == "ACTIVE"
    assert data["allergen_tags"] == []


def test_plan_creation_applies_the_declared_commercial_defaults(api):
    """PRD §3.3: "a `promo_discount_pct` expressing a promotional discount as a fraction
    which defaults to 0 and may not exceed 0.25, and an `allows_hypoallergenic` boolean
    that defaults to true and, when false, forbids the plan's subscriptions from ever
    receiving a hypoallergenic SKU. A plan's `status` starts at `ACTIVE` and the only other
    member is `RETIRED`."

    Design: Corner/entities/corner_plan_defaults_promo_zero_and_allows_hypoallergenic_true
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    data = validate_success(
        api.create_plan(
            {"code": unique_code("BARE"), "name": "Bare Plan", "default_pack_count": 2}, OPS
        ),
        201,
    )
    assert_plan(data)
    assert data["promo_discount_pct"] == 0
    assert data["allows_hypoallergenic"] is True
    assert data["status"] == "ACTIVE"


def test_an_undeclared_sku_stage_routes_to_the_enum_error(api):
    """PRD §2.11: "Enum membership is checked next, and the set of fields routed to
    `ERR_INVALID_ENUM` (HTTP 422) is closed and exhaustive. Exactly these fields route
    there: a SKU's `stage`, a SKU's `line`, a SKU's `status`, a plan's `status`, an
    allergen flag's `allergen_tag`, an allergen flag's `severity`, a shipment's
    `service_level`, a gift order's `claim_mode`, a refund's `reason`, a child's `stage`
    when supplied on an update, and the `target_stage` field of a manual resize request."

    Design: Corner/entities/corner_type_constraint_rejects_unknown_sku_stage_enum
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    code = unique_code("BAD-STAGE")
    resp = api.create_sku(
        {
            "code": code,
            "name": "Bad Stage",
            "stage": "S9",
            "line": "STANDARD",
            "pack_price_cents": 1200,
        },
        OPS,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_ENUM.value, 422)

    _listed, meta = validate_paginated(api.list_skus(OPS, {"limit": 100}))
    assert meta["total_count"] == 0, "the rejected SKU must not have persisted"


def test_missing_a_required_catalog_field_is_rejected(api):
    """PRD §2.11: "A field that section 4 lists without a trailing question mark is
    required; if it is absent or explicitly null, the request is rejected with
    `ERR_MISSING_FIELD` (HTTP 400)."
    PRD §3.3: "a `pack_price_cents` base price that may not be negative and is stated
    *before* any line surcharge"

    Design: Corner/errors/corner_missing_required_field_rejected
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    resp = api.create_sku(
        {"code": unique_code("NO-PRICE"), "name": "No Price", "stage": "S2", "line": "STANDARD"},
        OPS,
    )
    validate_error(resp, ApiErrorId.ERR_MISSING_FIELD.value, 400)

    _listed, meta = validate_paginated(api.list_skus(OPS, {"limit": 100}))
    assert meta["total_count"] == 0, "a SKU missing its price must not persist"


def test_a_duplicate_sku_code_is_refused(api):
    """PRD §3.3: "It carries a `code` unique across the SKU catalog, a `name`, the `stage`
    it serves drawn from the ten-band ladder"
    PRD §3.3: "Duplicate codes are refused with `ERR_DUPLICATE_CODE`."

    Design: Corner/errors/corner_duplicate_sku_code_rejected
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    code = unique_code("S2-STD")
    make_sku(api, code=code)
    resp = api.create_sku(
        {
            "code": code,
            "name": "Duplicate",
            "stage": "S3",
            "line": "STANDARD",
            "pack_price_cents": 1500,
        },
        OPS,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_CODE.value, 409)

    listed, meta = validate_paginated(api.list_skus(OPS, {"limit": 100}))
    assert meta["total_count"] == 1
    assert listed[0]["code"] == code


def test_the_sku_list_reports_the_full_pagination_block(api):
    """PRD §2.3: "The `meta` block of a list response carries `limit`, `offset`,
    `total_count` and `has_more`; `total_count` reports the number of rows matching the
    filters before the page window is applied, and `has_more` is true exactly when rows
    remain beyond the current window."
    PRD §2.2: "The `response_type` is either "object" for a single resource or "array" for
    a list of resources."

    Design: Corner/entities/corner_sku_listing_is_paginated_with_total_count_and_has_more
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    make_sku(api, code=unique_code("S1-P"), stage="S1", pack_price_cents=1000, stock_packs=5)
    make_sku(api, code=unique_code("S2-P"), stage="S2", pack_price_cents=1200, stock_packs=5)
    make_sku(api, code=unique_code("S3-P"), stage="S3", pack_price_cents=1400, stock_packs=5)

    resp = api.list_skus(OPS, {"limit": 2, "offset": 0})
    listed, meta = validate_paginated(resp)
    assert len(listed) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True
    assert resp.json()["response_type"] == "array"


def test_a_pagination_limit_above_one_hundred_is_rejected(api):
    """PRD §2.3: "`limit` controls page size: it defaults to 10 when omitted, may not be
    smaller than 1 and may not be larger than 100. `offset` controls the starting position:
    it defaults to 0 and may not be negative. A `limit` outside the range from 1 to 100
    inclusive, or an `offset` below 0, is rejected with `ERR_INVALID_PAGINATION` (HTTP 400) —
    list endpoints carry no request body, so pagination faults never surface as the
    body-oriented range error."

    Design: Corner/errors/corner_pagination_limit_above_hundred_rejected
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    resp = api.list_skus(OPS, {"limit": 500})
    validate_error(resp, ApiErrorId.ERR_INVALID_PAGINATION.value, 400)


def test_the_hypoallergenic_surcharge_is_added_to_every_pack(api):
    """PRD §3.3: "The effective per-pack price is the SKU's `pack_price_cents` plus a
    surcharge of 350 cents when the SKU's `line` is `HYPOALLERGENIC`, and plus nothing when
    the line is `STANDARD`. That value becomes a cycle line's `unit_price_cents`, and it is
    the same unit used to value a gift order."
    PRD §3.2: "A child whose `hypoallergenic_required` is true must never receive a SKU
    whose `line` is `STANDARD`, and an attempt to do so is refused with
    `ERR_HYPOALLERGENIC_REQUIRED` (HTTP 422)"

    Design: Corner/calculations/corner_hypoallergenic_surcharge_applied_per_pack
    """
    ctx = setup_household(
        api,
        email_prefix="hypo",
        sku_overrides={"code": unique_code("S2-STD"), "pack_price_cents": 1200},
        child_overrides={"hypoallergenic_required": True},
    )
    sku_hypo = make_sku(
        api,
        code=unique_code("S2-HYPO"),
        name="Stage 2 Hypoallergenic",
        line="HYPOALLERGENIC",
        pack_price_cents=1400,
    )
    cycle = generate_cycle(api, ctx["subscription"]["id"])
    allocated = allocate_cycle(api, cycle["id"])

    assert allocated["subtotal_cents"] == 3500, "2 packs at 1400 + 350 surcharge"
    lines = cycle_lines(api, cycle["id"])
    assert len(lines) == 1
    assert lines[0]["sku_id"] == sku_hypo["id"]
    assert lines[0]["unit_price_cents"] == 1750
    assert lines[0]["quantity_packs"] == 2
    assert allocated["shipping_cents"] == 599
    assert allocated["total_due_cents"] == 4099


def test_catalog_and_account_attributes_remain_editable_and_listable(api):
    """PRD §3.3: "Operators may later revise `name`, `promo_discount_pct`,
    `allows_hypoallergenic` and `status`; plans are readable by every role and listable
    with a `status` filter."
    PRD §3.1: "Account attributes remain editable after registration: an `AccountHolder`
    or a `SupportAgent` may revise `full_name` and `payment_method_on_file`. Support and
    operations staff may also browse accounts, filtering by `status`, by `email` or by
    `loyalty_account_id`."

    Design: Corner/endpoints/corner_catalog_and_account_patch_endpoints
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    plan = validate_success(
        api.create_plan(
            {"code": unique_code("CORE"), "name": "Core Plan", "default_pack_count": 2}, OPS
        ),
        201,
    )
    account = register_and_verify_account(
        api, email=unique_email("patch"), payment_method_on_file=False
    )
    headers = make_account_holder_headers(account["id"])

    patched_plan = validate_success(
        api.update_plan(plan["id"], {"promo_discount_pct": 0.2}, OPS)
    )
    assert patched_plan["promo_discount_pct"] == 0.20

    patched_account = validate_success(
        api.update_account(
            account["id"],
            {"payment_method_on_file": True, "full_name": "Patched Household"},
            headers,
        )
    )
    assert patched_account["payment_method_on_file"] is True
    assert patched_account["full_name"] == "Patched Household"

    plans, _ = validate_paginated(api.list_plans(OPS, {"status": "ACTIVE"}))
    assert [p["id"] for p in plans] == [plan["id"]]

    accounts, _ = validate_paginated(api.list_accounts(OPS, {"status": "ACTIVE"}))
    assert [a["id"] for a in accounts] == [account["id"]]
