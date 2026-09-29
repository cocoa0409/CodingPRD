"""The shapes rows are born in, and the keys that decide which rules apply to them.

Jurisdiction is read off the shop rather than the renter, serial numbers are unique
only inside their own store while statutory rules are unique globally, and every
collection answers a missing identifier with its own dedicated code.
"""

from __future__ import annotations

from test_helpers import (
    ADMIN,
    AUSTIN_MAIN,
    CLOCK_EPOCH,
    DULUTH_MAIN,
    LAMP_MODEL,
    MANAGER,
    MISSING_AGREEMENT_ID,
    MISSING_CUSTOMER_ID,
    MISSING_STATE_RULE_ID,
    MISSING_UNIT_ID,
    RENO_MAIN,
    SALES,
    TULSA_MAIN,
    W52_ADJUSTED_CASH_PRICE_CENTS,
    W52_MONTHLY_EQUIVALENT_CENTS,
    W52_NV_COST_OF_RENTAL_CENTS,
    W52_NV_PROCESSING_FEE_CENTS,
    W52_NV_TOTAL_OF_PAYMENTS_CENTS,
    W52_PROCESSING_FEE_CENTS,
    W52_RENEWAL_RATE_CENTS,
    W52_RENT_SUBTOTAL_CENTS,
    W52_TOTAL_OF_PAYMENTS_CENTS,
    AccountFlag,
    Category,
    ConditionGrade,
    ErrorId,
    LoyaltyTier,
    PaymentStatus,
    PayoffFormula,
    PossessionStatus,
    ResidualBasis,
    RetiredReason,
    TermType,
    UnitStatus,
    VerificationStatus,
    assert_fields,
    assert_paid_pct,
    assert_pagination,
    assert_pricing,
    assert_row_ids,
    assert_signing_anchors_unset,
    assert_total_count,
    assert_tracked_row,
    factories,
    failure,
    page,
)

SHARED_SERIAL = "SN-DUP-0001"
BELOW_THE_PRICE_FLOOR_CENTS = 500
ILLEGAL_CATEGORY = "POWER_TOOL"


def test_the_agreement_is_priced_off_the_shops_jurisdiction_not_the_renters(world):
    """A Texas renter signing at the Nevada shop is billed Nevada's lower fee cap.

    PRD: Stores and customers reference a jurisdiction by that same natural key rather than by identifier, and three operations therefore require the matching rule row to already exist: creating a store (matched on the submitted `state_code`), creating an agreement (matched on the `state_code` of the store that holds the unit, never on the customer's), and verifying a customer (matched on the customer's own `state_code`).

    Design: Corner/entities/agreement_prices_off_the_stores_state_rule_not_the_customers
    """
    world.set_clock(CLOCK_EPOCH)
    world.seed_tx_rule()
    world.seed_nv_rule()
    store = world.open_store(RENO_MAIN, "NV", 1)
    unit = world.add_sofa(store["id"], "SN-NV-0001")
    customer = world.onboard_dana()
    assert customer["state_code"] == "TX", (
        "the renter must live in a different jurisdiction from the shop"
    )

    unregulated = world.api.create_store(
        factories.store_payload(TULSA_MAIN, "OK", 1), ADMIN
    )
    failure(unregulated, ErrorId.STATE_RULE_NOT_CONFIGURED)
    assert_total_count(world.api.list_stores(ADMIN), 1)

    agreement = world.sign(customer["id"], unit["id"], TermType.WEEKLY, 52)
    assert_fields(agreement, state_code_snapshot="NV")
    assert_pricing(
        agreement,
        adjusted_cash_price_cents=W52_ADJUSTED_CASH_PRICE_CENTS,
        renewal_rate_cents=W52_RENEWAL_RATE_CENTS,
        rent_subtotal_cents=W52_RENT_SUBTOTAL_CENTS,
        processing_fee_cents=W52_NV_PROCESSING_FEE_CENTS,
        total_of_payments_cents=W52_NV_TOTAL_OF_PAYMENTS_CENTS,
        monthly_equivalent_rate_cents=W52_MONTHLY_EQUIVALENT_CENTS,
    )
    assert agreement["processing_fee_cents"] != W52_PROCESSING_FEE_CENTS, (
        "pricing off the renter's Texas rule would have charged the higher fee cap"
    )
    assert agreement["total_of_payments_cents"] != W52_TOTAL_OF_PAYMENTS_CENTS
    assert_tracked_row(agreement, expected_version=1)
    assert_fields(
        agreement,
        payment_status=PaymentStatus.CURRENT,
        possession_status=PossessionStatus.PENDING_DELIVERY,
    )
    assert_signing_anchors_unset(agreement)
    assert_paid_pct(agreement, 0.0000)

    assert_fields(
        world.disclosure(agreement["id"]),
        state_code="NV",
        early_purchase_formula=PayoffFormula.PCT_OF_REMAINING,
        total_of_payments_cents=W52_NV_TOTAL_OF_PAYMENTS_CENTS,
        cost_of_rental_cents=W52_NV_COST_OF_RENTAL_CENTS,
    )
    assert world.get_unit(unit["id"])["status"] == UnitStatus.RESERVED


def test_a_renter_created_with_only_the_required_fields_takes_every_default(world):
    """Nothing optional is sent, so the whole declared default set must appear.

    PRD: A newly created customer is `PENDING` with a `verification_score` of 0, a `verified_reference_count` of 0, an empty-string `verified_by_user_id`, a `loyalty_points_balance` and `loyalty_points_lifetime` of 0, a `loyalty_tier` of `STANDARD`, a `credit_balance_cents` of 0, an `account_flag` of `NORMAL`, and an `adverse_agreement_count` and `lifetime_delinquency_count` of 0.

    Design: Corner/entities/customer_create_applies_every_declared_default
    """
    world.set_clock(CLOCK_EPOCH)
    world.seed_tx_rule()

    created_row = world.create_customer(factories.milo_chen_payload())
    expected = dict(
        employer_verified=False,
        government_id_verified=False,
        in_person_contact_consent=False,
        verification_status=VerificationStatus.PENDING,
        verification_score=0,
        verified_reference_count=0,
        verified_by_user_id="",
        loyalty_points_balance=0,
        loyalty_points_lifetime=0,
        loyalty_tier=LoyaltyTier.STANDARD,
        credit_balance_cents=0,
        account_flag=AccountFlag.NORMAL,
        adverse_agreement_count=0,
        lifetime_delinquency_count=0,
    )
    assert_fields(created_row, **expected)
    assert_tracked_row(created_row, expected_version=1)

    reread = world.get_customer(created_row["id"])
    assert_fields(reread, **expected)
    for field, value in created_row.items():
        assert reread[field] == value, (
            f"the immediate re-read disagrees with the create response on {field}: "
            f"{reread[field]!r} vs {value!r}"
        )


def test_serials_are_unique_per_store_while_statutory_rules_are_unique_globally(world):
    """The same serial is legal at a second shop; a second rule for one state is not.

    PRD: `serial_number` is unique within its store and `state_code` is unique across statutory rules — otherwise `ERR_DUPLICATE_SERIAL` or `ERR_DUPLICATE_STATE_RULE` (409). Applies to inventory-unit creation and statutory-rule creation.

    Design: Corner/entities/duplicate_serial_is_store_scoped_while_state_rules_are_globally_unique
    """
    world.set_clock(CLOCK_EPOCH)
    world.seed_tx_rule()
    world.seed_mn_rule()
    tx_store = world.open_store(AUSTIN_MAIN, "TX", 1)
    mn_store = world.open_store(DULUTH_MAIN, "MN", 2)
    world.add_sofa(tx_store["id"], SHARED_SERIAL)

    failure(
        world.api.create_inventory_unit(
            tx_store["id"], factories.sofa_payload(SHARED_SERIAL), MANAGER
        ),
        ErrorId.DUPLICATE_SERIAL,
    )

    elsewhere = world.add_sofa(mn_store["id"], SHARED_SERIAL)
    assert_fields(
        elsewhere,
        store_id=mn_store["id"],
        serial_number=SHARED_SERIAL,
        status=UnitStatus.AVAILABLE,
    )

    failure(
        world.api.create_state_rule(
            factories.tx_rule_payload(
                late_fee_grace_days=7, processing_fee_max_cents=9000
            ),
            ADMIN,
        ),
        ErrorId.DUPLICATE_STATE_RULE,
    )
    rules = assert_total_count(
        world.api.list_state_rules(ADMIN, {"state_code": "TX"}), 1
    )
    # The refused second rule must not have overwritten the one already on file.
    assert_fields(rules[0], late_fee_grace_days=3, processing_fee_max_cents=5000)

    assert_total_count(
        world.api.list_store_inventory_units(tx_store["id"], MANAGER), 1
    )


def test_each_collection_answers_a_missing_identifier_with_its_own_code(world):
    """Four unknown identifiers, four different not-found codes, no shape confusion.

    PRD: Each collection has its own 404: `ERR_STORE_NOT_FOUND`, `ERR_CUSTOMER_NOT_FOUND`, `ERR_REFERENCE_NOT_FOUND`, `ERR_UNIT_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`, `ERR_DELIVERY_ORDER_NOT_FOUND`, `ERR_TICKET_NOT_FOUND`, `ERR_INSPECTION_NOT_FOUND`, `ERR_PAYMENT_NOT_FOUND`, `ERR_QUOTE_NOT_FOUND`, `ERR_STATE_RULE_NOT_FOUND` and `ERR_LEDGER_ENTRY_NOT_FOUND`.

    Design: Corner/entities/unknown_ids_return_the_entity_specific_not_found_code
    """
    world.set_clock(CLOCK_EPOCH)
    world.seed_tx_rule()
    store = world.open_store(AUSTIN_MAIN, "TX", 1)
    unit = world.add_sofa(store["id"], "SN-TX-0001")
    customer = world.create_customer(factories.dana_reyes_payload())

    failure(
        world.api.get_agreement(MISSING_AGREEMENT_ID, ADMIN),
        ErrorId.AGREEMENT_NOT_FOUND,
    )
    failure(
        world.api.get_state_rule(MISSING_STATE_RULE_ID, ADMIN),
        ErrorId.STATE_RULE_NOT_FOUND,
    )

    # The renter is still PENDING, so a customer-not-found must win over the
    # verification gate: the row has to be located before it can be judged.
    failure(
        world.api.create_agreement(
            factories.agreement_payload(MISSING_CUSTOMER_ID, unit["id"]), SALES
        ),
        ErrorId.CUSTOMER_NOT_FOUND,
    )
    failure(
        world.api.create_agreement(
            factories.agreement_payload(customer["id"], MISSING_UNIT_ID), SALES
        ),
        ErrorId.UNIT_NOT_FOUND,
    )

    assert_total_count(world.api.list_agreements(ADMIN), 0)
    assert world.get_unit(unit["id"])["status"] == UnitStatus.AVAILABLE


def test_the_inventory_listing_pages_the_window_and_counts_the_whole_match(world):
    """Two rows then one, with total_count describing the match rather than the page.

    PRD: Every list response reports `limit`, `offset`, `total_count` and `has_more` inside `meta`, where `total_count` is the number of rows matching the filters before the page window is applied and `has_more` is true exactly when rows remain after the current page.

    Design: Corner/entities/inventory_unit_listing_paginates_and_orders_by_created_at
    """
    world.set_clock(CLOCK_EPOCH)
    world.seed_tx_rule()
    store = world.open_store(AUSTIN_MAIN, "TX", 1)
    first = world.add_sofa(store["id"], "SN-TX-0001")
    second = world.add_washer(store["id"], "SN-TX-0002")
    third = world.add_sofa(store["id"], "SN-TX-0003")

    rows, meta = page(
        world.api.list_store_inventory_units(
            store["id"], MANAGER, {"limit": 2, "offset": 0}
        )
    )
    assert_pagination(meta, limit=2, offset=0, total_count=3, has_more=True)
    assert_row_ids(rows, [first["id"], second["id"]])

    rows, meta = page(
        world.api.list_store_inventory_units(
            store["id"], MANAGER, {"limit": 2, "offset": 2}
        )
    )
    assert_pagination(meta, limit=2, offset=2, total_count=3, has_more=False)
    assert_row_ids(rows, [third["id"]])

    rows, meta = page(
        world.api.list_inventory_units(
            MANAGER,
            {
                "store_id": store["id"],
                "category": Category.APPLIANCE,
                "limit": 10,
                "offset": 0,
            },
        )
    )
    assert_pagination(meta, limit=10, offset=0, total_count=1, has_more=False)
    assert_row_ids(rows, [second["id"]])
    assert_fields(
        rows[0], category=Category.APPLIANCE, status=UnitStatus.AVAILABLE
    )

    failure(
        world.api.list_store_inventory_units(store["id"], MANAGER, {"limit": 0}),
        ErrorId.INVALID_REQUEST,
    )


def test_a_malformed_body_is_refused_before_any_business_rule_is_consulted(world):
    """An illegal enum member and a price under the floor never reach the domain.

    PRD: The body parses, required fields are present, enum members are legal, integers are non-negative where non-negative is required, and `limit` and `offset` are in range — otherwise `ERR_INVALID_REQUEST` (400). Applies to every endpoint.

    Design: Corner/entities/malformed_requests_are_rejected_before_any_business_rule
    """
    world.set_clock(CLOCK_EPOCH)
    world.seed_tx_rule()
    store = world.open_store(AUSTIN_MAIN, "TX", 1)
    world.create_customer(factories.dana_reyes_payload())
    world.add_sofa(store["id"], "SN-TX-0001")

    failure(
        world.api.create_inventory_unit(
            store["id"],
            factories.unit_payload("SN-TX-0004", category=ILLEGAL_CATEGORY),
            MANAGER,
        ),
        ErrorId.INVALID_REQUEST,
    )
    failure(
        world.api.create_inventory_unit(
            store["id"],
            factories.unit_payload(
                "SN-TX-0005",
                model_code=LAMP_MODEL,
                cash_price_cents=BELOW_THE_PRICE_FLOOR_CENTS,
            ),
            MANAGER,
        ),
        ErrorId.INVALID_REQUEST,
    )

    surviving = assert_total_count(
        world.api.list_store_inventory_units(store["id"], MANAGER), 1
    )
    assert_fields(
        surviving[0],
        serial_number="SN-TX-0001",
        category=Category.FURNITURE,
        status=UnitStatus.AVAILABLE,
        condition_grade=ConditionGrade.NEW,
        residual_valuation_basis=ResidualBasis.NONE,
        retired_reason=RetiredReason.NONE,
    )
