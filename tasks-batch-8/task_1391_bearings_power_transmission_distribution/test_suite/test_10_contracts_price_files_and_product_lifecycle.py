"""Contract window geometry, contract expiry, price-file publish/supersede,
and product lifecycle gating of new order lines."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    create_product, create_branch, create_customer, create_draft_contract,
    create_active_contract, publish_price_file, set_clock, get_price_file,
    get_product, get_contract, parse_iso,
    ApiErrorId, TEST_USERS,
)

ANALYST = TEST_USERS["pricing_analyst_headers"]
ADMIN = TEST_USERS["system_admin_headers"]
CONTRACT_ADMIN = TEST_USERS["contract_admin_headers"]
REP = TEST_USERS["counter_sales_rep_headers"]


def _setup_contract_windows():
    """C1 with ACTIVE contract A [2026-01-01, 2026-06-01); drafts B (adjacent),
    C (overlapping); C2 with draft D identical to A's window."""
    c1 = create_customer(name="Triangle Plant")
    c2 = create_customer(name="Quadrant Plant")
    contract_a = create_active_contract(
        c1["id"], family="BEARING", price_basis="LIST_LESS", discount_pct=0.10,
        effective_from="2026-01-01T00:00:00Z", effective_to="2026-06-01T00:00:00Z")
    contract_b = create_draft_contract(
        c1["id"], family="BEARING", price_basis="LIST_LESS", discount_pct=0.12,
        effective_from="2026-06-01T00:00:00Z", effective_to="2026-12-01T00:00:00Z")
    contract_c = create_draft_contract(
        c1["id"], family="BEARING", price_basis="LIST_LESS", discount_pct=0.15,
        effective_from="2026-05-15T00:00:00Z", effective_to="2026-07-01T00:00:00Z")
    contract_d = create_draft_contract(
        c2["id"], family="BEARING", price_basis="LIST_LESS", discount_pct=0.10,
        effective_from="2026-01-01T00:00:00Z", effective_to="2026-06-01T00:00:00Z")
    return {"c1": c1, "c2": c2, "a": contract_a, "b": contract_b,
            "c": contract_c, "d": contract_d}


def test_adjacent_contract_window_activates_and_overlap_rejected(api):
    """PRD §3.2: "requires that no other `ACTIVE` contract for the same
    customer and family have a half-open window overlapping this one; windows
    that merely touch, this one's start equal to the other's end or vice versa,
    do not overlap and are allowed (`ERR_CONTRACT_WINDOW_OVERLAP`, 409)."

    Design: Difficulty/resource_temporal_overlap/contract_activation_half_open_window_overlap
    """
    ctx = _setup_contract_windows()
    activated_b = validate_success(
        api.activate_contract(ctx["b"]["id"], CONTRACT_ADMIN), 200)
    assert activated_b["status"] == "ACTIVE", (
        "adjacency allowed: B.effective_from == A.effective_to")
    res = api.activate_contract(ctx["c"]["id"], CONTRACT_ADMIN)
    validate_error(res, ApiErrorId.ERR_CONTRACT_WINDOW_OVERLAP, expected_status=409)
    assert get_contract(ctx["c"]["id"])["status"] == "DRAFT"


def test_contract_overlap_scope_is_per_customer(api):
    """PRD §3.2: "requires that no other `ACTIVE` contract for the same
    customer and family have a half-open window overlapping this one".

    Design: Difficulty/resource_temporal_overlap/contract_activation_half_open_window_overlap
    """
    ctx = _setup_contract_windows()
    activated_d = validate_success(
        api.activate_contract(ctx["d"]["id"], CONTRACT_ADMIN), 200)
    assert activated_d["status"] == "ACTIVE", (
        "the overlap rule is scoped per (customer, family); a different "
        "customer may hold the identical window")


def test_contract_auto_expires_at_window_end(api):
    """PRD §3.2: "An active contract expires automatically when the logical
    clock reaches its exclusive end, moving to `EXPIRED`."

    Design: Corner/state_machines/contract_auto_expires_at_window_end
    """
    customer = create_customer(name="Expiry Plant", credit_limit_cents=1000000)
    contract = create_active_contract(
        customer["id"], family="GEARBOX", price_basis="LIST_LESS",
        discount_pct=0.05,
        effective_from="2026-01-01T00:00:00Z", effective_to="2026-06-01T00:00:00Z")
    set_clock("2026-06-01T00:00:00Z")  # window end is exclusive
    expired = get_contract(contract["id"])
    assert expired["status"] == "EXPIRED", (
        f"at exactly effective_to the contract no longer applies; got {expired['status']}")


def test_contract_fixed_basis_requires_fixed_price(api):
    """PRD §3.2: "`fixed_unit_price_cents` pins a unit price regardless of list
    and is required for `CONTRACT_FIXED` (its absence surfaces at activation as
    `ERR_CONTRACT_FIXED_PRICE_MISSING`, 400)".

    Design: Corner/validations/contract_fixed_basis_requires_fixed_price
    """
    customer = create_customer(name="Fixed Plant", credit_limit_cents=1000000)
    contract = create_draft_contract(
        customer["id"], family="BELT", price_basis="CONTRACT_FIXED",
        effective_from="2026-01-01T00:00:00Z", effective_to="2027-01-01T00:00:00Z")
    res = api.activate_contract(contract["id"], CONTRACT_ADMIN)
    validate_error(res, ApiErrorId.ERR_CONTRACT_FIXED_PRICE_MISSING,
                   expected_status=400)
    assert get_contract(contract["id"])["status"] == "DRAFT"


def test_price_file_auto_effectivity_and_supersede_chain(api):
    """PRD §3.1: "The new file is born `PENDING`, `published_by` records the
    analyst's `X-User-ID`, and publishing supersedes the product's previously
    `PENDING` file, if any — a create-with-supersede pattern that bumps the
    product's `version`." and "When the logical clock reaches a pending file's
    `effective_at`, the file becomes `EFFECTIVE` and, in the same instant, the
    product's `list_price_cents` takes the file's `new_list_price_cents`,
    `last_price_change_at` is set to `effective_at`".

    Design: Corner/state_machines/price_file_auto_effectivity_and_supersede_chain
    """
    product = create_product(sku="BRG-6013", list_price_cents=10000)
    pf1 = publish_price_file(product["id"], 11000, "2026-08-10T00:00:00Z")
    pf2 = publish_price_file(product["id"], 12000, "2026-08-20T00:00:00Z")
    # PF1 superseded at PF2's publish, before ever taking effect.
    assert get_price_file(pf1["id"])["status"] == "SUPERSEDED"

    set_clock("2026-08-20T00:00:00Z")
    assert get_price_file(pf2["id"])["status"] == "EFFECTIVE"
    product_after = get_product(product["id"])
    assert product_after["list_price_cents"] == 12000
    assert parse_iso(product_after["last_price_change_at"]) == parse_iso(
        "2026-08-20T00:00:00Z"), (
        f"last_price_change_at is set to effective_at; got "
        f"{product_after['last_price_change_at']}")


def test_price_file_cancel_effective_rejected(api):
    """PRD §3.1: "A still-`PENDING` file may be cancelled by a
    `PricingAnalyst`, moving it to `CANCELLED`; cancelling anything else fails
    with `ERR_PRICE_FILE_NOT_PENDING` (409)."

    Design: Corner/validations/price_file_cancel_effective_rejected
    """
    product = create_product(sku="BRG-6037", list_price_cents=1000)
    price_file = publish_price_file(product["id"], 2000, "2026-08-05T00:00:00Z")
    set_clock("2026-08-06T00:00:00Z")  # file becomes EFFECTIVE
    assert get_price_file(price_file["id"])["status"] == "EFFECTIVE"
    res = api.cancel_price_file(price_file["id"], ANALYST)
    validate_error(res, ApiErrorId.ERR_PRICE_FILE_NOT_PENDING, expected_status=409)
    assert get_price_file(price_file["id"])["status"] == "EFFECTIVE"


def test_price_file_effective_at_must_be_future(api):
    """PRD §3.1: "The `effective_at` instant must lie strictly in the future of
    the current logical time at publish, else `ERR_EFFECTIVE_AT_IN_PAST` (409)."
    PRD §2.4: "At startup, before any explicit set, the logical clock reads
    exactly `2026-08-01T00:00:00Z`; it never falls back to wall-clock time."

    Design: Corner/validations/price_file_effective_at_must_be_future
    """
    product = create_product(sku="BRG-6034", list_price_cents=1000)
    # Clock never set: logical time is the 2026-08-01T00:00:00Z startup default.
    res = api.create_price_file(
        {"product_id": product["id"], "new_list_price_cents": 2000,
         "effective_at": "2026-08-01T00:00:00Z",
         "expected_product_version": product["version"]},
        ANALYST)
    validate_error(res, ApiErrorId.ERR_EFFECTIVE_AT_IN_PAST, expected_status=409)


def test_obsolete_product_blocked_from_new_order_line(api):
    """PRD §3.4: "the referenced product must exist and be `ACTIVE`
    (`ERR_PRODUCT_NOT_ACTIVE`, 409)."
    PRD §3.1: "From `ACTIVE` a `PricingAnalyst` may patch the product to
    `PHASEOUT`, and from `PHASEOUT` to `OBSOLETE`".

    Design: Corner/validations/obsolete_product_blocked_from_new_order_line
    """
    product = create_product(sku="BRG-6038", list_price_cents=1000)
    validate_success(api.patch_product(product["id"], {"status": "PHASEOUT"},
                                       ANALYST), 200)
    validate_success(api.patch_product(product["id"], {"status": "OBSOLETE"},
                                       ANALYST), 200)
    branch = create_branch(code="OBS-25")
    customer = create_customer(name="Obsolete Plant", credit_limit_cents=1000000)
    order = get_success_data(api.create_order(
        {"customer_id": customer["id"], "branch_id": branch["id"]}, REP))
    res = api.add_order_line(
        order["id"], {"product_id": product["id"], "qty": 1}, REP)
    validate_error(res, ApiErrorId.ERR_PRODUCT_NOT_ACTIVE, expected_status=409)
