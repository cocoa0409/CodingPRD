"""Market registration, supplier onboarding and the certification lifecycle."""
from __future__ import annotations

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors as E
from test_helpers import factories as f
from test_helpers.assertions import (
    assert_instant_equals,
    assert_mutable_common_fields,
)
from test_helpers.fixtures import DEFAULT_INSTANT, two_leg_package
from test_helpers.test_users import (
    COMPLIANCE_OFFICER,
    PLATFORM_ADMIN,
    role_headers,
    supplier_user_headers,
)


def test_supplier_onboarding_returns_every_field_with_system_defaults(b, client):
    """A freshly onboarded supplier carries every declared field at its default.

    PRD 3.1: "A fresh supplier is not sellable: its `visibility_status` starts at
    `PENDING_CERT`, its `certification_level` at `NONE`, its `current_model` at
    `NONE`, its `content_score` and `connectivity_score` at 0, and its
    `parity_strikes` at 0, with `suspension_reason` null."

    Design: Corner/entities/supplier_create_returns_every_declared_field_with_system_defaults
    """
    b.set_clock(DEFAULT_INSTANT)
    market = b.market(market_code="EU-PAR", name="Paris")

    response = client.create_supplier(
        f.supplier_payload(
            market["id"],
            legal_name="Hotel Lutetia SA",
            supplier_type="HOTEL",
            contact_email="ops@lutetia.example",
            conversion_index=50,
        ),
        PLATFORM_ADMIN,
    )
    supplier = validate_success(response, expected_status=201)

    assert supplier["legal_name"] == "Hotel Lutetia SA"
    assert supplier["supplier_type"] == "HOTEL"
    assert supplier["home_market_id"] == market["id"]
    assert supplier["contact_email"] == "ops@lutetia.example"
    assert supplier["conversion_index"] == 50
    assert supplier["visibility_status"] == "PENDING_CERT"
    assert supplier["certification_level"] == "NONE"
    assert supplier["current_model"] == "NONE"
    assert supplier["content_score"] == 0
    assert supplier["connectivity_score"] == 0
    assert supplier["parity_strikes"] == 0
    assert supplier["suspension_reason"] is None
    assert_mutable_common_fields(supplier)
    assert supplier["version"] == 1
    assert supplier["created_at"] == supplier["updated_at"]


def test_market_read_returns_the_stored_row(b, client):
    """Reading a market hands back exactly what registration stored.

    PRD 3.1: "A market's `status` begins at `ACTIVE` and its only other value is
    `CLOSED`."

    Design: Corner/entities/market_get_by_id_returns_the_stored_row
    """
    b.set_clock(DEFAULT_INSTANT)
    market = b.market(
        market_code="EU-PAR",
        name="Paris",
        paid_slot_capacity=3,
        price_display_mode="TOTAL_UPFRONT",
        ranking_disclosure_required=True,
    )

    stored = validate_success(client.get_market(market["id"], COMPLIANCE_OFFICER))

    assert stored["market_code"] == "EU-PAR"
    assert stored["name"] == "Paris"
    assert stored["paid_slot_capacity"] == 3
    assert stored["price_display_mode"] == "TOTAL_UPFRONT"
    assert stored["ranking_disclosure_required"] is True
    assert stored["status"] == "ACTIVE"


def test_market_registration_ignores_client_supplied_system_fields(b, client):
    """Client-supplied id, status and version never reach the stored market.

    PRD 2.4: "Every resource is addressed by an `id`, which is a server-minted
    UUID carrying no type prefix. Clients never supply an `id`."

    Design: Corner/entities/market_create_system_fields_input_ignored
    """
    b.set_clock(DEFAULT_INSTANT)
    supplied_id = "11111111-1111-1111-1111-111111111111"

    market = validate_success(
        client.create_market(
            {
                "market_code": "EU-LYS",
                "name": "Lyon",
                "paid_slot_capacity": 1,
                "price_display_mode": "TOTAL_UPFRONT",
                "id": supplied_id,
                "status": "CLOSED",
                "version": 99,
            },
            PLATFORM_ADMIN,
        ),
        expected_status=201,
    )

    assert market["id"] != supplied_id
    assert market["status"] == "ACTIVE"
    assert market["version"] == 1
    assert_mutable_common_fields(market)
    assert market["created_at"] == market["updated_at"]


def test_omitted_optional_inputs_apply_their_declared_defaults(b, client):
    """Omitting the three optional inputs yields true, 50 and true.

    PRD 3.1: a supplier takes "optionally a `conversion_index` between 0
    and 100 which defaults to 50". PRD 3.4: a rate plan takes "optionally
    `parity_monitored`, which defaults to true". PRD 2.12: a market's
    `ranking_disclosure_required` flag is true "(which is the default when the
    flag is omitted at registration)".

    Design: Corner/entities/optional_inputs_apply_their_declared_defaults
    """
    b.set_clock(DEFAULT_INSTANT)
    market = validate_success(
        client.create_market(
            {
                "market_code": "EU-NCE",
                "name": "Nice",
                "paid_slot_capacity": 2,
                "price_display_mode": "TOTAL_UPFRONT",
            },
            PLATFORM_ADMIN,
        ),
        expected_status=201,
    )
    assert market["ranking_disclosure_required"] is True

    supplier = validate_success(
        client.create_supplier(
            {
                "legal_name": "Hotel Negresco SA",
                "supplier_type": "HOTEL",
                "home_market_id": market["id"],
                "contact_email": "ops@negresco.example",
            },
            PLATFORM_ADMIN,
        ),
        expected_status=201,
    )
    assert supplier["conversion_index"] == 50

    b.certify(supplier["id"], content_score=85, connectivity_score=80)
    plan = validate_success(
        client.create_rate_plan(
            supplier["id"],
            {
                "market_id": market["id"],
                "name": "Non-monitored corporate",
                "currency": "EUR",
                "cancellation_policy_code": "STRICT",
                "free_cancel_cutoff_hours": 72,
                "tax_fee_pct": 0.02,
            },
            supplier_user_headers(supplier["id"]),
        ),
        expected_status=201,
    )
    assert plan["parity_monitored"] is True
    assert plan["status"] == "ACTIVE"


def test_duplicate_market_code_is_rejected(b, client):
    """A second market reusing a registered market_code is refused.

    PRD 3.1: a market carries "a `market_code` - 3 to 12 characters of uppercase
    letters and hyphens, unique across all markets, with a duplicate rejected as
    `ERR_MARKET_CODE_TAKEN`".

    Design: Corner/errors/duplicate_market_code_is_rejected
    """
    b.set_clock(DEFAULT_INSTANT)
    b.market(market_code="EU-PAR", name="Paris")

    duplicate = client.create_market(
        f.market_payload(
            market_code="EU-PAR",
            name="Paris Secondary",
            paid_slot_capacity=5,
            ranking_disclosure_required=False,
        ),
        PLATFORM_ADMIN,
    )
    validate_error(duplicate, E.ERR_MARKET_CODE_TAKEN, 409)

    distinct = validate_success(
        client.create_market(
            f.market_payload(
                market_code="EU-LON", name="London", paid_slot_capacity=5
            ),
            PLATFORM_ADMIN,
        ),
        expected_status=201,
    )
    assert distinct["market_code"] == "EU-LON"

    _data, meta = validate_paginated(client.list_markets(PLATFORM_ADMIN))
    assert meta["total_count"] == 2


def test_certify_decision_applies_every_declared_side_effect(b, client):
    """One decide call stamps the package, sets the expiry and lifts the supplier.

    PRD 3.1: a CERTIFY decision "moves the package `IN_REVIEW -> CERTIFIED`,
    stamping `reviewed_by_user_id` and setting `expires_at` to the logical-clock
    instant of the decision plus a full year of validity, which is 365 days" and
    both outcomes "drive the supplier from `PENDING_CERT` to `ACTIVE`, set its
    `certification_level` to `CERTIFIED` or `PROVISIONAL` respectively, and copy
    the adjudicated `content_score` and `connectivity_score` from the
    certification onto the supplier's own `content_score` and
    `connectivity_score`".

    Design: Corner/state_machines/certification_certify_decision_side_effects_are_all_applied
    """
    b.set_clock(DEFAULT_INSTANT)
    market = b.market(market_code="EU-PAR", name="Paris")
    supplier = b.supplier(market["id"], legal_name="Hotel Lutetia SA")
    cert = b.submit_certification(supplier["id"], content_score_claimed=90)
    validate_success(
        client.start_certification_review(cert["id"], {}, COMPLIANCE_OFFICER)
    )

    decided = validate_success(
        client.decide_certification(
            cert["id"],
            {
                "decision": "CERTIFY",
                "content_score": 88,
                "connectivity_score": 91,
                "note": "full certification granted",
            },
            COMPLIANCE_OFFICER,
        )
    )

    assert decided["status"] == "CERTIFIED"
    assert decided["decision"] == "CERTIFY"
    assert decided["content_score"] == 88
    assert decided["connectivity_score"] == 91
    assert decided["reviewed_by_user_id"] == COMPLIANCE_OFFICER["X-User-ID"]
    assert_instant_equals(decided["expires_at"], "2027-08-05T00:00:00Z")

    after = b.read_supplier(supplier["id"])
    assert after["visibility_status"] == "ACTIVE"
    assert after["certification_level"] == "CERTIFIED"
    assert after["content_score"] == 88
    assert after["connectivity_score"] == 91
    assert after["suspension_reason"] is None
    assert after["version"] == supplier["version"] + 1


def test_compliance_officer_cannot_register_a_market(b, client):
    """Market registration is refused to every role but the platform administrator.

    PRD 2.1: "If both headers are well formed but the named role does not appear
    on the endpoint's authorised-role list in §4, the request is rejected with
    `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/compliance_officer_cannot_register_a_market
    """
    b.set_clock(DEFAULT_INSTANT)
    payload = f.market_payload(
        market_code="EU-MAD", name="Madrid", paid_slot_capacity=4
    )

    refused = client.create_market(payload, COMPLIANCE_OFFICER)
    validate_error(refused, E.ERR_UNAUTHORIZED, 403)

    _data, meta = validate_paginated(client.list_markets(PLATFORM_ADMIN))
    assert meta["total_count"] == 0

    allowed = validate_success(
        client.create_market(payload, PLATFORM_ADMIN), expected_status=201
    )
    assert allowed["market_code"] == "EU-MAD"


def test_undeclared_role_header_returns_unauthenticated(b, client):
    """A role outside the six declared ones is unauthenticated, not unauthorized.

    PRD 2.1: "If either header is absent, or if `X-User-Role` is not one of the
    six roles declared below, the request is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401). ... These two checks run before any other, in that order."

    Design: Corner/rbac/undeclared_role_header_returns_unauthenticated
    """
    b.set_clock(DEFAULT_INSTANT)
    market = b.market(market_code="EU-PAR", name="Paris")
    rogue = role_headers("SupplierAdmin", "rogue-1")

    validate_error(client.get_market(market["id"], rogue), E.ERR_UNAUTHENTICATED, 401)
    validate_error(
        client.get_market(NON_EXISTENT_UUID, rogue), E.ERR_UNAUTHENTICATED, 401
    )
    validate_error(
        client.create_market(f.market_payload(), rogue), E.ERR_UNAUTHENTICATED, 401
    )


def test_certification_revoke_cascades_four_hops(b, client):
    """Revoking the backing certification suspends, suppresses and withdraws.

    PRD 3.1: revocation triggers that "the supplier moves `ACTIVE -> SUSPENDED`
    with `suspension_reason` set to `CERTIFICATION_REVOKED` ...; every `LIVE`
    offer of that supplier moves to `SUPPRESSED` with `suppression_reason`
    `SUPPLIER_SUSPENDED`; every `PUBLISHED` package holding one of those offers
    moves to `WITHDRAWN` and every `PUBLISHED` ranking run holding one of them
    moves to `WITHDRAWN`".

    Design: Difficulty/transitive_cascade/certification_revoke_cascades_supplier_offer_package_and_ranking
    """
    ctx = two_leg_package(
        b,
        hotel_net_rate_cents=185053,
        hotel_tax_fee_pct=0.07,
        air_net_rate_cents=119936,
        air_tax_fee_pct=0.05,
        publish=True,
    )
    run = b.ranking_run(ctx.market["id"], disclosure_version="EU-2026-Q3")
    b.publish_ranking_run(run["id"])

    validate_success(
        client.revoke_certification(
            ctx.certification["id"],
            {"revocation_reason": "content audit failed post-certification"},
            COMPLIANCE_OFFICER,
        )
    )

    cert = validate_success(
        client.get_certification(ctx.certification["id"], PLATFORM_ADMIN)
    )
    assert cert["status"] == "REVOKED"
    assert cert["revocation_reason"] == "content audit failed post-certification"

    supplier = b.read_supplier(ctx.supplier["id"])
    assert supplier["visibility_status"] == "SUSPENDED"
    assert supplier["suspension_reason"] == "CERTIFICATION_REVOKED"
    assert supplier["certification_level"] == "NONE"
    assert supplier["content_score"] == 0
    assert supplier["connectivity_score"] == 0

    offer = b.read_offer(ctx.offer["id"])
    assert offer["status"] == "SUPPRESSED"
    assert offer["suppression_reason"] == "SUPPLIER_SUSPENDED"

    assert b.read_package(ctx.package["id"])["status"] == "WITHDRAWN"
    assert b.read_ranking_run(run["id"])["status"] == "WITHDRAWN"


def test_certification_revoke_leaves_the_other_supplier_and_the_price_alone(b, client):
    """The cascade follows the certification's ownership edge, and reprices nothing.

    PRD 3.1: "The suspension cascade only fires when the revoked or expired
    package is the one currently backing the supplier's `certification_level`".
    PRD 3.7: withdrawal moves the package "`PUBLISHED -> WITHDRAWN`, a terminal
    status, resetting `reveal_supplier_names` back to false".

    Design: Difficulty/transitive_cascade/certification_revoke_cascades_supplier_offer_package_and_ranking
    """
    ctx = two_leg_package(
        b,
        hotel_net_rate_cents=185053,
        hotel_tax_fee_pct=0.07,
        air_net_rate_cents=119936,
        air_tax_fee_pct=0.05,
        publish=True,
    )
    assert ctx.package["package_total_cents"] == 310413

    validate_success(
        client.revoke_certification(
            ctx.certification["id"],
            {"revocation_reason": "content audit failed post-certification"},
            COMPLIANCE_OFFICER,
        )
    )

    air_offer = b.read_offer(ctx.air_offer["id"])
    assert air_offer["status"] == "LIVE"
    air_supplier = b.read_supplier(ctx.air_supplier["id"])
    assert air_supplier["visibility_status"] == "ACTIVE"
    assert air_supplier["certification_level"] == "CERTIFIED"

    package = b.read_package(ctx.package["id"])
    assert package["status"] == "WITHDRAWN"
    assert package["package_total_cents"] == 310413
    assert package["reveal_supplier_names"] is False
