"""Role authorisation, the two sharper scope rules, and per-instance ownership."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    make_account_holder_headers,
    make_child,
    make_gift_purchaser_headers,
    read_cycle,
    read_gift_order,
    read_registry_item,
    register_and_verify_account,
    set_clock,
    setup_charged_cycle,
    setup_household,
    unique_code,
    unique_email,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    generate_cycle,
    reserve_gift,
    setup_open_registry,
    setup_paid_gift,
)

OPS = TEST_USERS["ops_admin_headers"]
SUPPORT = TEST_USERS["support_agent_headers"]


def test_a_support_agent_may_not_allocate_a_cycle(api):
    """PRD §2.1: "Once the header pair is accepted, the acting role must appear in the role
    list the endpoint declares in section 4; when it does not, the request is refused with
    `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §3.5: "Allocation is where a planned cycle becomes a concrete list of packs, and it is
    `OpsAdmin` work."

    Design: Corner/rbac/corner_support_agent_cannot_allocate_a_cycle
    """
    ctx = setup_household(api, email_prefix="roleforbid")
    cycle = generate_cycle(api, ctx["subscription"]["id"])

    resp = api.allocate_cycle(cycle["id"], SUPPORT)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)
    assert read_cycle(api, cycle["id"])["status"] == "PLANNED"


def test_a_support_agent_may_not_write_the_catalog(api):
    """PRD §2.1: "Catalog writes — creating or updating a plan, creating or updating a SKU,
    and adjusting SKU stock — belong exclusively to `OpsAdmin`, and a `SupportAgent` (or anyone
    else) attempting one is rejected with `ERR_CATALOG_WRITE_FORBIDDEN` (HTTP 403). Both of
    these run ahead of the generic `ERR_FORBIDDEN_ROLE` check."

    Design: Corner/rbac/corner_support_agent_cannot_write_the_catalog
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    code = unique_code("CS-SKU")
    resp = api.create_sku(
        {"code": code, "name": "Support Sku", "stage": "S2", "line": "STANDARD",
         "pack_price_cents": 1200},
        SUPPORT,
    )
    validate_error(resp, ApiErrorId.ERR_CATALOG_WRITE_FORBIDDEN.value, 403)

    _skus, meta = validate_paginated(api.list_skus(OPS, {"limit": 100}))
    assert meta["total_count"] == 0


def test_a_gift_purchaser_may_not_touch_the_subscription_business(api):
    """PRD §2.1: "A `GiftPurchaser` is confined to the registry-and-gift business: any attempt
    on a subscription, cycle, cycle-line, child or pause-record endpoint is rejected with
    `ERR_GIFT_PURCHASER_SCOPE` (HTTP 403) rather than the generic role error."

    Design: Corner/rbac/corner_gift_purchaser_cannot_touch_pipeline_r
    """
    ctx = setup_household(api, with_sku=False, email_prefix="scope-h")
    purchaser = register_and_verify_account(api, email=unique_email("scope-p"))

    resp = api.generate_cycle(
        ctx["subscription"]["id"], make_gift_purchaser_headers(purchaser["id"])
    )
    validate_error(resp, ApiErrorId.ERR_GIFT_PURCHASER_SCOPE.value, 403)

    _cycles, meta = validate_paginated(
        api.list_cycles(OPS, {"subscription_id": ctx["subscription"]["id"]})
    )
    assert meta["total_count"] == 0


# DELETED: test_one_household_may_not_read_another_households_child
# (Design: Corner/rbac/corner_account_holder_cannot_read_another_households_child)
#
# STEP 1b — not uniquely derivable. The only PRD grounds is the §2.1 sentence
# quoted by the deleted test, which says how an ownership check compares and
# which error a mismatch raises, but never names any *read* as an ownership-check
# site. §2.6 places Ownership as gate 5 of "The Nine-Gate Write Order", opening
# "Every mutating request walks the same nine gates", and its worked example of
# the ownership gate is a mutation ("A skip attempted by a stranger..."). §4 is
# declared "a routing summary only ... the roles permitted to call it", and the
# §3 read glosses are restatements of those role lists, not ownership rules —
# §3.9's "Registries are readable by the owner, by gift purchasers browsing for
# something to buy, by the household and by staff" enumerates exactly the five
# roles §4 lists for GET /registries/{id} and explicitly includes a non-owner,
# so §3.2's parallel "readable by the household, by a RegistryOwner, and by
# support and operations staff" is likewise the role list for GET /children/{id}
# and not a statement that only the owning household may read. A PRD-only
# implementer may therefore gate ownership on writes alone and return the child
# on a stranger's GET.


def test_a_stranger_may_not_pay_another_purchasers_gift(api):
    """PRD §2.1: "When `X-User-Role` is `GiftPurchaser`, `X-User-ID` is again the `id` of the
    acting `Account`, compared against the addressed gift order's `purchaser_account_id`; a
    mismatch is `ERR_NOT_GIFT_PURCHASER` (HTTP 403)."

    Design: Corner/rbac/corner_stranger_cannot_pay_another_purchasers_gift
    """
    parties, _registry, item = setup_open_registry(api, requested_quantity=2)
    gift = reserve_gift(api, parties, item, 1)
    stranger = register_and_verify_account(api, email=unique_email("gp-x"))

    resp = api.pay_gift_order(gift["id"], make_gift_purchaser_headers(stranger["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_GIFT_PURCHASER.value, 403)

    assert read_gift_order(api, gift["id"], parties["purchaser_headers"])["status"] == "PENDING_PAYMENT"
    assert read_registry_item(api, item["id"], parties["owner_headers"])["fulfilled_quantity"] == 0


def test_a_household_may_not_cite_a_gift_refund_reason_on_its_own_cycle(api):
    """PRD §3.10: "The valid members of `reason` are `CANCEL`, `RETURN`, `GIFT_REFUND` and
    `GOODWILL`, but an `AccountHolder` opening a Pipeline-R request may cite only `CANCEL` or
    `RETURN`: the Pipeline-G reason `GIFT_REFUND` and the operator reason `GOODWILL` are
    reserved for `OpsAdmin`, and an `AccountHolder` citing either is refused with
    `ERR_PIPELINE_R_REFUND_ACTOR` (HTTP 403)."

    Design: Corner/rbac/corner_account_holder_cannot_cite_a_gift_refund_reason
    """
    ctx, cycle = setup_charged_cycle(api, email_prefix="reason")
    resp = api.create_cycle_refund_request(cycle["id"], "GIFT_REFUND", ctx["headers"])
    validate_error(resp, ApiErrorId.ERR_PIPELINE_R_REFUND_ACTOR.value, 403)

    _refunds, meta = validate_paginated(api.list_refunds(OPS, {"cycle_id": cycle["id"]}))
    assert meta["total_count"] == 0


def test_the_registry_owner_may_not_refund_the_gift(api):
    """PRD §3.9: "Only the `GiftPurchaser` who paid may refund a gift. The registry owner can
    see the operation — it is deliberately listed among the roles so that the refusal is an
    explicit business decision rather than a routing accident — but is rejected with
    `ERR_PIPELINE_G_REFUND_ACTOR` (HTTP 403), as is any other identity."

    Design: Corner/rbac/corner_registry_owner_cannot_refund_the_gift
    """
    parties, _registry, item, gift = setup_paid_gift(api, quantity=1, requested_quantity=2)

    resp = api.refund_gift_order(gift["id"], parties["owner_headers"])
    validate_error(resp, ApiErrorId.ERR_PIPELINE_G_REFUND_ACTOR.value, 403)

    assert read_gift_order(api, gift["id"], parties["purchaser_headers"])["status"] == "PAID"
    assert read_registry_item(api, item["id"], parties["owner_headers"])["fulfilled_quantity"] == 1


def test_an_owner_may_not_buy_a_gift_from_their_own_registry(api):
    """PRD §3.9: "And an owner may not gift to their own registry: a purchaser whose account
    is the registry's `owner_account_id` is refused with `ERR_SELF_GIFT_FORBIDDEN` (HTTP 403)."

    Design: Corner/rbac/corner_registry_owner_cannot_gift_to_own_registry
    """
    parties, _registry, item = setup_open_registry(api, requested_quantity=2)
    fresh = read_registry_item(api, item["id"], parties["owner_headers"])

    resp = api.create_gift_order(
        {
            "registry_item_id": item["id"],
            "purchaser_account_id": parties["owner_id"],
            "quantity": 1,
            "expected_registry_item_version": fresh["version"],
        },
        make_gift_purchaser_headers(parties["owner_id"]),
    )
    validate_error(resp, ApiErrorId.ERR_SELF_GIFT_FORBIDDEN.value, 403)

    _gifts, meta = validate_paginated(
        api.list_gift_orders(parties["purchaser_headers"], {"registry_item_id": item["id"]})
    )
    assert meta["total_count"] == 0
