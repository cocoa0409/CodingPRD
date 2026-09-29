"""Account registration, buyer qualification gates and the credit ceiling."""

from test_helpers import (
    ADMIN,
    CANONICAL_BUYER_TAX_ID,
    CANONICAL_SCAC_CODE,
    CANONICAL_SELLER_TAX_ID,
    CLOCK_START,
    INSIDE_WINDOW_CLOCK,
    TRUST_SAFETY,
    api_client,
    assert_buyer_account,
    assert_seller_account,
    bid_payload,
    bootstrap_marketplace,
    buyer_account_payload,
    carrier_payload,
    create_buyer,
    credit_limit_payload,
    make_buyer_headers,
    qualification_decision_payload,
    read_listing,
    seller_account_payload,
    set_clock,
    setup_open_auction,
    total_count,
    validate_error,
    validate_success,
)

TWO_HUNDRED_UNIT_LINES = [
    {
        "sku": "APP-RET-0100",
        "unit_count": 200,
        "unit_retail_cents": 10_000,
        "declared_condition": "USED_GOOD",
    },
]

LAPSED_CERTIFICATE_DATE = "2026-07-31"


def test_seller_registration_returns_standard_tier_and_empty_recovery_aggregates():
    """A seller created from the four declared inputs comes back on the standard
    tier with every recovery aggregate at zero, a perfect accuracy average and
    version 1.

    PRD 3.9: "A freshly registered seller starts `ACTIVE` on `TIER_STANDARD` at
    2,000 basis points with every recovery aggregate at zero and
    `manifest_accuracy_avg` at 1.000."
    PRD 3.9: "A lot that has never been claimed against has no score and is
    excluded from the population entirely rather than being counted as a perfect
    1.000, and when `scored_lot_count` is zero the average reads 1.000 by
    definition."
    PRD 2.4: "Most resources additionally carry `updated_at`, an ISO 8601 UTC
    instant refreshed on every accepted mutation, and `version`, an integer that
    begins at 1 when the resource is created and increases by exactly 1 on every
    accepted mutation of that resource."

    Design: Corner/entities/seller_account_creation_returns_computed_defaults_and_system_fields
    """
    payload = seller_account_payload()

    seller = validate_success(api_client.create_seller_account(payload, ADMIN), 201)

    assert_seller_account(seller)
    assert seller["legal_name"] == payload["legal_name"]
    assert seller["account_status"] == "ACTIVE"
    assert seller["commission_tier"] == "TIER_STANDARD"
    assert seller["commission_rate_bps"] == 2000
    assert seller["gross_hammer_cents"] == 0
    assert seller["listed_retail_value_cents"] == 0
    assert seller["gross_recovery_rate"] == 0.0
    assert seller["net_proceeds_cents"] == 0
    assert seller["sold_retail_value_cents"] == 0
    assert seller["net_recovery_rate"] == 0.0
    assert seller["manifest_accuracy_avg"] == 1.0
    assert seller["scored_lot_count"] == 0
    assert seller["version"] == 1


def test_buyer_registration_leaves_every_fiscal_field_at_zero():
    """Registering a buyer with only the four required inputs leaves the buyer
    unqualified, unverified and with no credit, wallet or exposure.

    PRD 3.2: "Registration leaves `qualification_status` at `PENDING`,
    `business_verification_status` at `UNVERIFIED`, `approved_credit_limit_cents`
    at zero, `outstanding_exposure_cents` at zero and `wallet_credit_cents` at
    zero."

    Design: Corner/entities/buyer_account_defaults_applied_when_optional_fields_omitted
    """
    payload = {
        "legal_name": "Bare Bones Resale",
        "tax_id": "B-9001",
        "state_code": "NV",
        "contact_email": "bare@bones.example",
    }

    buyer = validate_success(api_client.create_buyer_account(payload, ADMIN), 201)

    assert_buyer_account(buyer)
    assert buyer["qualification_status"] == "PENDING"
    assert buyer["business_verification_status"] == "UNVERIFIED"
    assert buyer["approved_credit_limit_cents"] == 0
    assert buyer["outstanding_exposure_cents"] == 0
    assert buyer["wallet_credit_cents"] == 0


def test_tax_id_and_scac_collisions_are_refused_while_cross_kind_reuse_is_allowed():
    """A tax_id collides only within its own account kind and a scac_code collides
    across carriers, so the seller's tax_id may legitimately reappear on a buyer.

    PRD 2.10: "A `tax_id` must be unique across seller accounts, and a `tax_id`
    must be unique across buyer accounts — the two namespaces are independent, so
    the same identifier may legitimately appear once on each side, which is
    exactly the affiliation the anti-shill rule of §3.4 detects."
    PRD 2.10: "A collision within either namespace is `ERR_DUPLICATE_TAX_ID`
    (422). A `scac_code` must be unique across carriers; a collision is
    `ERR_DUPLICATE_SCAC` (422)."

    Design: Corner/errors/duplicate_identity_errors_are_all_reachable
    """
    env = bootstrap_marketplace()

    seller_clash = api_client.create_seller_account(
        seller_account_payload(
            legal_name="Northline Returns Copy",
            tax_id=CANONICAL_SELLER_TAX_ID,
            contact_email="copy@northline.example",
        ),
        ADMIN,
    )
    validate_error(seller_clash, "ERR_DUPLICATE_TAX_ID", 422)

    buyer_clash = api_client.create_buyer_account(
        buyer_account_payload(
            legal_name="Gulf Resale Copy",
            tax_id=CANONICAL_BUYER_TAX_ID,
            contact_email="copy@gulf.example",
        ),
        ADMIN,
    )
    validate_error(buyer_clash, "ERR_DUPLICATE_TAX_ID", 422)

    carrier_clash = api_client.create_carrier(
        carrier_payload(
            name="Keystone Freight Copy",
            scac_code=CANONICAL_SCAC_CODE,
            daily_pickup_capacity=3,
        ),
        ADMIN,
    )
    validate_error(carrier_clash, "ERR_DUPLICATE_SCAC", 422)

    assert total_count(api_client.list_seller_accounts(ADMIN)) == 1
    assert total_count(api_client.list_buyer_accounts(ADMIN)) == 1
    carrier = validate_success(api_client.get_carrier(env["carrier"]["id"], ADMIN))
    assert carrier["daily_pickup_capacity"] == 5

    affiliate = validate_success(
        api_client.create_buyer_account(
            buyer_account_payload(
                legal_name="Northline Trading Arm",
                tax_id=CANONICAL_SELLER_TAX_ID,
                state_code="OH",
                contact_email="arm@northline.example",
            ),
            ADMIN,
        ),
        201,
    )
    assert affiliate["tax_id"] == CANONICAL_SELLER_TAX_ID
    assert affiliate["qualification_status"] == "PENDING"
    assert total_count(api_client.list_buyer_accounts(ADMIN)) == 2

    seller = validate_success(api_client.get_seller_account(env["seller"]["id"], ADMIN))
    assert seller["legal_name"] == seller_account_payload()["legal_name"]


def test_qualification_refuses_unverified_business_lapsed_certificate_and_pending_bidder():
    """Each qualification gate is separately reachable: a QUALIFY without
    business_verified, a QUALIFY on a certificate that lapsed today, and a bid
    from a buyer who never got past PENDING.

    PRD 3.2: "The buyer's `resale_certificate_number` must be present and
    non-empty, and the buyer's `resale_certificate_expires_on` date must fall
    strictly after the UTC calendar date of the current logical clock — a
    certificate lapsing today is already lapsed for this purpose, and the
    rejection is `ERR_RESALE_CERTIFICATE_EXPIRED`."
    PRD 3.2: "The request must also carry `business_verified` set to true;
    without it the decision is rejected with `ERR_BUSINESS_NOT_VERIFIED`."
    PRD 3.4: "At band 10, the bidder's `qualification_status` must be
    `QUALIFIED`; a `PENDING`, `REJECTED` or `SUSPENDED` buyer is refused with
    `ERR_BUYER_NOT_QUALIFIED`."

    Design: Corner/errors/buyer_qualification_gate_errors_are_all_reachable
    """
    env = bootstrap_marketplace(with_buyer=False)
    auction = setup_open_auction(
        env, lines=TWO_HUNDRED_UNIT_LINES, clock=INSIDE_WINDOW_CLOCK
    )
    pending = create_buyer(qualify=False, credit_limit_cents=None)
    lapsed = create_buyer(
        qualify=False,
        credit_limit_cents=None,
        legal_name="Lapsed Cert Resale",
        tax_id="B-2003",
        contact_email="lapsed@resale.example",
        resale_certificate_expires_on=LAPSED_CERTIFICATE_DATE,
    )

    unverified = api_client.decide_buyer_qualification(
        pending["id"],
        {"decision": "QUALIFY", "approved_credit_limit_cents": 5_000_000},
        TRUST_SAFETY,
    )
    validate_error(unverified, "ERR_BUSINESS_NOT_VERIFIED", 422)
    reread_pending = validate_success(
        api_client.get_buyer_account(pending["id"], ADMIN)
    )
    assert reread_pending["qualification_status"] == "PENDING"
    assert reread_pending["approved_credit_limit_cents"] == 0

    expired = api_client.decide_buyer_qualification(
        lapsed["id"],
        qualification_decision_payload("QUALIFY", approved_credit_limit_cents=5_000_000),
        TRUST_SAFETY,
    )
    validate_error(expired, "ERR_RESALE_CERTIFICATE_EXPIRED", 422)
    reread_lapsed = validate_success(api_client.get_buyer_account(lapsed["id"], ADMIN))
    assert reread_lapsed["qualification_status"] == "PENDING"
    assert reread_lapsed["business_verification_status"] == "UNVERIFIED"
    assert reread_lapsed["approved_credit_limit_cents"] == 0

    refused_bid = api_client.place_bid(
        auction["listing"]["id"],
        bid_payload(pending["id"], 1_000_000),
        make_buyer_headers(pending["id"]),
    )
    validate_error(refused_bid, "ERR_BUYER_NOT_QUALIFIED", 409)
    assert read_listing(env, auction["listing"]["id"])["bid_count"] == 0


def test_rejected_buyer_cannot_be_qualified_afterwards():
    """REJECTED is terminal: a later QUALIFY carrying a credit limit is refused
    and the buyer keeps its rejected standing and its zero ceiling.

    PRD 3.2: "A `REJECT` decision from `PENDING` advances `PENDING → REJECTED`
    and sets `business_verification_status` to `REJECTED`; `REJECTED` is terminal
    and no later decision can move a buyer out of it."
    PRD 3.2: "Any decision requested from a state that does not admit it — a
    `SUSPEND` on a `PENDING` buyer, a `QUALIFY` on an already `QUALIFIED` buyer,
    anything at all on a `REJECTED` buyer — is
    `ERR_BUYER_QUALIFICATION_STATE_INVALID`."

    Design: Corner/state_machines/rejected_buyer_account_is_terminal_and_blocks_requalification
    """
    set_clock(CLOCK_START)
    buyer = create_buyer(qualify=False, credit_limit_cents=None)

    rejected = validate_success(
        api_client.decide_buyer_qualification(
            buyer["id"], qualification_decision_payload("REJECT"), TRUST_SAFETY
        )
    )
    assert rejected["qualification_status"] == "REJECTED"
    assert rejected["business_verification_status"] == "REJECTED"

    revival = api_client.decide_buyer_qualification(
        buyer["id"],
        qualification_decision_payload("QUALIFY", approved_credit_limit_cents=5_000_000),
        TRUST_SAFETY,
    )
    validate_error(revival, "ERR_BUYER_QUALIFICATION_STATE_INVALID", 409)

    reread = validate_success(api_client.get_buyer_account(buyer["id"], ADMIN))
    assert reread["qualification_status"] == "REJECTED"
    assert reread["approved_credit_limit_cents"] == 0


def test_credit_ceiling_admits_each_bid_alone_but_refuses_the_pair():
    """Two identical bids are admitted on the aggregate prospective exposure, so
    the second is refused one cent short of the ceiling and admitted once the
    ceiling is raised to exactly the exposure it would create.

    PRD 3.2: "The first part covers live bidding commitments: over all of this
    buyer's bids whose `bid_status` is either `STANDING` or `WINNING`, sum each
    bid's `ceiling_cents` plus the buyer premium that ceiling would attract, where
    that premium is the ceiling multiplied by the premium rate its own amount
    selects from the tier table in §3.6, divided by 10,000 and rounded half up to
    a whole cent before being added into the sum."
    PRD 3.2: "Every new commitment is admitted on the exposure the request
    *would* create: if that prospective exposure is less than or equal to the
    ceiling the commitment is allowed — the boundary is inclusive, so a
    prospective exposure exactly equal to the ceiling is admitted — and otherwise
    the request is rejected with `ERR_CREDIT_LIMIT_EXCEEDED` and nothing is
    created."
    PRD 2.10: "A `BuyerAccount` is registered with the same four fields plus,
    optionally, a `resale_certificate_number`, a `resale_certificate_expires_on`
    calendar date rendered as `YYYY-MM-DD`, and a `requested_credit_limit_cents`
    figure that records what the applicant asked for and is advisory only — it
    never participates in any fiscal check."

    Design: Corner/validations/credit_ceiling_admits_each_bid_alone_but_blocks_the_pair
    """
    env = bootstrap_marketplace(
        buyer_overrides={"requested_credit_limit_cents": 2_279_999},
        credit_limit_cents=2_279_999,
    )
    first = setup_open_auction(
        env, lines=TWO_HUNDRED_UNIT_LINES, clock=INSIDE_WINDOW_CLOCK
    )
    second = setup_open_auction(
        env,
        lines=TWO_HUNDRED_UNIT_LINES,
        lot_overrides={"title": "Second 200-unit apparel lot"},
    )
    buyer_id = env["buyer"]["id"]

    admitted = validate_success(
        api_client.place_bid(
            first["listing"]["id"],
            bid_payload(buyer_id, 1_000_000),
            env["buyer_headers"],
        ),
        201,
    )
    assert admitted["bid_status"] == "WINNING"
    buyer = validate_success(api_client.get_buyer_account(buyer_id, ADMIN))
    assert buyer["outstanding_exposure_cents"] == 1_140_000

    refused = api_client.place_bid(
        second["listing"]["id"],
        bid_payload(buyer_id, 1_000_000),
        env["buyer_headers"],
    )
    validate_error(refused, "ERR_CREDIT_LIMIT_EXCEEDED", 422)
    assert read_listing(env, second["listing"]["id"])["bid_count"] == 0
    buyer = validate_success(api_client.get_buyer_account(buyer_id, ADMIN))
    assert buyer["outstanding_exposure_cents"] == 1_140_000

    validate_success(
        api_client.set_buyer_credit_limit(
            buyer_id, credit_limit_payload(2_280_000), ADMIN
        )
    )
    accepted = validate_success(
        api_client.place_bid(
            second["listing"]["id"],
            bid_payload(buyer_id, 1_000_000),
            env["buyer_headers"],
        ),
        201,
    )
    assert accepted["bid_status"] == "WINNING"

    buyer = validate_success(api_client.get_buyer_account(buyer_id, ADMIN))
    assert buyer["outstanding_exposure_cents"] == 2_280_000
    assert buyer["approved_credit_limit_cents"] == 2_280_000
    assert buyer["wallet_credit_cents"] == 0
    assert buyer["requested_credit_limit_cents"] == 2_279_999
