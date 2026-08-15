"""Contractor accounts and bulk purchase agreements: finalize cascade,
supersede, OCC create, lazy expiry (PRD §3.9, §2.4, §2.7)."""
from test_helpers import (
    ApiErrorId,
    add_line,
    create_account,
    create_agreement,
    create_category,
    create_placed_item,
    create_sale,
    create_zone,
    finalize_sale,
    get_account,
    get_success_data,
    set_clock,
    validate_error,
    validate_success,
)
from test_helpers.factories import create_bulk_agreement_payload
from test_helpers.test_users import TEST_USERS

MANAGER = TEST_USERS["store_manager_headers"]
ADMIN = TEST_USERS["warehouse_admin_headers"]


# ---------------------------------------------------------------------------
# Difficulty: transitive_cascade / finalize_cascade_item_zone_account_agreement
# ---------------------------------------------------------------------------

def _setup_finalize_cascade():
    """Account F (credit limit 90000) + agreement (0.10 off, min 1.0 UNIT) +
    item priced 100000 placed in zone ZF + sale with agreement and one line."""
    category = create_category(code="FIXTURES", display_name="Fixtures",
                               base_rate_cents=5000)
    account = create_account(company_name="Ctor F", contact_email="f@x.com",
                             credit_limit_cents=90000)
    agreement = create_agreement(account["id"], category["id"], discount_pct=0.10,
                                 min_quantity=1.0, quantity_unit="UNIT")
    zone = create_zone(code="ZF", display_name="Zone F", capacity=5, restock_threshold=0)
    item = create_placed_item(category["id"], zone["id"], 100000,
                              description_text="fixture", estimated_weight_lbs=30)
    sale = create_sale("CONTRACTOR_ACCOUNT", contractor_id=account["id"],
                       agreement_id=agreement["id"])
    add_line(sale["id"], item["id"])
    return {"category": category, "account": account, "agreement": agreement,
            "zone": zone, "item": item, "sale": sale}


class TestFinalizeCascadeItemZoneAccountAgreement:
    def test_finalize_cascade_item_sold_and_zone_decremented(self, api):
        """PRD §3.9: "Finalization cascades outward in hops. Each line's item
        moves from `RESERVED` to `SOLD` with `sold_via_sale_id` set and its
        `zone_id` and `floor_since` cleared; each such item's former zone loses
        one from its `current_count` and recomputes `restock_recommended`."

        Design: Difficulty/transitive_cascade/finalize_cascade_item_zone_account_agreement
        """
        ctx = _setup_finalize_cascade()
        sale = finalize_sale(ctx["sale"]["id"])
        assert sale["status"] == "FINALIZED"
        assert sale["total_cents"] == 96300, (
            f"100000 - round(100000*0.10) + round(90000*0.07) = 96300, got {sale['total_cents']}")

        item = get_success_data(api.get_item(ctx["item"]["id"], MANAGER))
        assert item["sales_status"] == "SOLD"
        assert item["zone_id"] is None
        zone = get_success_data(api.get_store_zone(ctx["zone"]["id"], MANAGER))
        assert zone["current_count"] == 0
        assert zone["restock_recommended"] is True

    def test_finalize_cascade_auto_suspend_cancels_agreement(self, api):
        """PRD §3.9: "if the post-finalize balance now exceeds the
        `credit_limit_cents`, the account is suspended automatically with
        `suspension_reason` recorded as `CREDIT_LIMIT_BREACH` and every one of its
        `ACTIVE` agreements is cancelled."

        Design: Difficulty/transitive_cascade/finalize_cascade_item_zone_account_agreement
        """
        ctx = _setup_finalize_cascade()
        sale = finalize_sale(ctx["sale"]["id"])
        assert sale["total_cents"] == 96300

        account = get_account(ctx["account"]["id"])
        assert account["outstanding_balance_cents"] == 96300
        assert account["status"] == "SUSPENDED", (
            "hop 3: 96300 > credit limit 90000 suspends the account automatically")
        assert account["suspension_reason"] == "CREDIT_LIMIT_BREACH"

        agreement = get_success_data(api.get_bulk_agreement(ctx["agreement"]["id"], ADMIN))
        assert agreement["status"] == "CANCELLED", (
            "hop 4: the suspension cascade cancels the account's ACTIVE agreements")


# ---------------------------------------------------------------------------
# Corner: state_machines / agreement_supersede_transitions_old_to_superseded
# ---------------------------------------------------------------------------

def test_agreement_supersede_transitions_old_to_superseded(api):
    """PRD §3.9: "The create may name a `supersedes_agreement_id` referencing an
    `ACTIVE` agreement of the same contractor and category — anything else fails
    with `ERR_AGREEMENT_NOT_ACTIVE` — in which case the prior agreement moves to
    `SUPERSEDED`; the create bumps the account's `version` by one."
    PRD §3.9: "New agreements stand `ACTIVE`"

    Design: Corner/state_machines/agreement_supersede_transitions_old_to_superseded
    """
    category = create_category(code="SUPCAT", display_name="Sup Cat")
    account = create_account(company_name="Ctor Sup", contact_email="sup@x.com")
    first = create_agreement(account["id"], category["id"], discount_pct=0.05,
                             min_quantity=1.0, valid_until="2026-12-31T00:00:00Z")
    assert first["status"] == "ACTIVE"

    second = create_agreement(account["id"], category["id"], discount_pct=0.08,
                              min_quantity=2.0, valid_from="2026-06-01T00:00:00Z",
                              valid_until="2027-06-01T00:00:00Z",
                              supersedes_agreement_id=first["id"])
    assert second["status"] == "ACTIVE"
    assert second["supersedes_agreement_id"] == first["id"]

    first = get_success_data(api.get_bulk_agreement(first["id"], ADMIN))
    assert first["status"] == "SUPERSEDED"


# ---------------------------------------------------------------------------
# Corner: cross_cutting_layers / bulk_agreement_stale_version_rejected
# ---------------------------------------------------------------------------

def test_bulk_agreement_stale_version_rejected(api):
    """PRD §2.7: "Creating a bulk purchase agreement — `POST /reuse/bulk-agreements`
    — requires `expected_account_version`, carrying the `version` of the parent
    contractor account as the client last observed it. If the account's current
    `version` has moved past that value — because another writer has since mutated
    the account, for example by creating an agreement that superseded the
    previously active one — the create is rejected with `ERR_STALE_ACCOUNT_VERSION`
    (HTTP 412), preventing the client from writing against a stale view of the
    account."
    PRD §3.9: "the create bumps the account's `version` by one."

    Design: Corner/cross_cutting_layers/bulk_agreement_stale_version_rejected
    """
    cat1 = create_category(code="OCCAT1", display_name="OCC Cat 1")
    cat2 = create_category(code="OCCAT2", display_name="OCC Cat 2")
    account = create_account(company_name="Ctor OCC", contact_email="occ@x.com")
    observed_version = account["version"]

    first = validate_success(api.create_bulk_agreement(
        create_bulk_agreement_payload(account["id"], cat1["id"], observed_version,
                                      discount_pct=0.05),
        ADMIN), expected_status=201)
    assert first["status"] == "ACTIVE"
    moved = get_account(account["id"])
    assert moved["version"] > observed_version, "the create bumps the account's version"

    response = api.create_bulk_agreement(
        create_bulk_agreement_payload(account["id"], cat2["id"], observed_version,
                                      discount_pct=0.07),
        ADMIN)
    validate_error(response, ApiErrorId.ERR_STALE_ACCOUNT_VERSION)


# ---------------------------------------------------------------------------
# Corner: calculations / expired_agreement_rejected_at_sale_open
# ---------------------------------------------------------------------------

def test_expired_agreement_rejected_at_sale_open(api):
    """PRD §3.9: "A contractor-account sale may attach a bulk purchase agreement
    by `agreement_id`; the attached agreement must stand `ACTIVE`
    (`ERR_AGREEMENT_NOT_ACTIVE`) and the logical clock must lie inside its
    validity window (`ERR_AGREEMENT_NOT_IN_WINDOW`)."
    PRD §2.4: "Agreement expiry in particular is lazy: an `ACTIVE` agreement whose
    `valid_until` the clock has passed flips to `EXPIRED` the next time the
    agreement is read or used, not through any background sweep."

    Design: Corner/calculations/expired_agreement_rejected_at_sale_open
    """
    category = create_category(code="EXPCAT", display_name="Exp Cat")
    account = create_account(company_name="Ctor Exp", contact_email="exp@x.com")
    agreement = create_agreement(account["id"], category["id"], discount_pct=0.10,
                                 valid_from="2026-01-01T00:00:00Z",
                                 valid_until="2026-05-10T00:00:00Z")
    set_clock("2026-06-01T00:00:00Z")  # past valid_until

    response = api.create_sale(
        {"sale_channel": "CONTRACTOR_ACCOUNT", "contractor_id": account["id"],
         "agreement_id": agreement["id"]},
        TEST_USERS["cashier_headers"])
    validate_error(response, ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE)

    agreement = get_success_data(api.get_bulk_agreement(agreement["id"], ADMIN))
    assert agreement["status"] == "EXPIRED", "lazy expiry flips the agreement on read/use"
