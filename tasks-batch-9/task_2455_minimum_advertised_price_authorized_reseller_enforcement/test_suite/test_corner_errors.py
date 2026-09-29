"""Error-code coverage for the catalogue in PRD section 5.

Most of these exercise the path-existence step of the rejection ordering in PRD
2.9: a path parameter naming a row that does not exist yields that resource
type's own not-found code at HTTP 404, ahead of the ownership, transition and
domain checks that sit below it in the order.  Two further cases close the
request-shape and transition-legality steps on endpoint families the rest of the
suite reaches by other routes.
"""
from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
)

from test_helpers import (
    ANALYST_HEADERS,
    BCM_HEADERS,
    COUNSEL_HEADERS,
    api_client,
    make_distributor_headers,
    make_reseller_headers,
)
from test_helpers.constants import DEFAULT_CLOCK
from test_helpers.factories import (
    chargeback_dispute_payload,
    confirm_outcome_payload,
    distributor_payload,
    exception_decision_payload,
    ship_downstream_payload,
    supply_status_payload,
)
from test_helpers.fixtures import (
    create_authorized_reseller,
    create_distributor,
    create_policy_in_review,
    create_product,
    create_published_policy,
    create_reseller,
    create_serial_unit,
    pin_clock,
    read_distributor,
    read_policy,
    read_product,
    read_reseller,
    read_serial_unit,
)


# --------------------------------------------------------------------------- #
# Shared setup helpers
# --------------------------------------------------------------------------- #
def _empty_world():
    """Pin the logical clock to the instant it reads before any client pins it."""
    pin_clock(DEFAULT_CLOCK)


def _published_policy():
    """A single policy carried to PUBLISHED with effective_from at the clock."""
    _empty_world()
    return create_published_policy(DEFAULT_CLOCK)


def _policy_and_product():
    """A PUBLISHED policy governing one registered product."""
    policy = _published_policy()
    product = create_product(
        policy["id"],
        sku="SKU-AUDIO-1",
        name="Studio Headphones",
        msrp_cents=20000,
        standard_map_floor_cents=15000,
    )
    return policy, product


def _applied_reseller():
    """A PUBLISHED policy and a freshly applied reseller holding no agreement."""
    policy = _published_policy()
    reseller = create_reseller(
        legal_name="Acme Retail LLC",
        contact_email="ops@acme.example",
        primary_channel="MARKETPLACE",
    )
    return policy, reseller


def _authorized_reseller():
    """A PUBLISHED policy and one reseller carried to AUTHORIZED / OPEN."""
    policy = _published_policy()
    reseller, agreement = create_authorized_reseller(
        policy["id"],
        reseller_overrides={
            "legal_name": "Acme Retail LLC",
            "contact_email": "ops@acme.example",
            "primary_channel": "MARKETPLACE",
        },
        agreement_overrides={"permitted_channels": ["MARKETPLACE", "OWN_WEBSITE"]},
    )
    return policy, reseller, agreement


# --------------------------------------------------------------------------- #
# Path existence on the policy, product and reseller endpoints
# --------------------------------------------------------------------------- #
def test_submit_review_on_an_unknown_policy_id_is_a_policy_not_found():
    """An unknown policy in the path is a 404 even for the right role and a valid body.

    PRD: "Every resource named by a path parameter exists, validated left to right, so
    that on a nested path the leftmost missing resource determines the error. The code is
    the not-found code of the resource type that is missing: `ERR_POLICY_NOT_FOUND`,
    `ERR_PRODUCT_NOT_FOUND`, `ERR_RESELLER_NOT_FOUND`, `ERR_DISTRIBUTOR_NOT_FOUND`,
    `ERR_AGREEMENT_NOT_FOUND`, `ERR_OBSERVATION_NOT_FOUND`, `ERR_VIOLATION_NOT_FOUND`,
    `ERR_NOTICE_NOT_FOUND`, `ERR_EXCEPTION_NOT_FOUND`, `ERR_SERIAL_UNIT_NOT_FOUND`,
    `ERR_TEST_PURCHASE_NOT_FOUND` or `ERR_CHARGEBACK_NOT_FOUND`, each HTTP 404."

    Design: Corner/errors/error_policy_not_found_on_submit_review_returns_not_found
    """
    _empty_world()

    validate_error(
        api_client.submit_policy_review(NON_EXISTENT_UUID, BCM_HEADERS),
        "ERR_POLICY_NOT_FOUND",
        404,
    )

    _rows, meta = validate_paginated(api_client.list_pricing_policies(BCM_HEADERS))
    assert meta["total_count"] == 0


def test_adjusting_an_unknown_product_id_is_a_product_not_found():
    """Path existence is resolved before the supplied floor is range-checked.

    PRD: "Products are adjustable in three respects by a `BrandChannelManager`:
    `lifecycle_status`, `clearance_discount_pct` and `standard_map_floor_cents` may each
    be supplied, individually or together, on an adjustment request, and the transition
    advances the product's `version`."

    Design: Corner/errors/error_product_not_found_on_patch_returns_not_found
    """
    _published_policy()

    validate_error(
        api_client.adjust_product(
            NON_EXISTENT_UUID, {"standard_map_floor_cents": 14000}, BCM_HEADERS
        ),
        "ERR_PRODUCT_NOT_FOUND",
        404,
    )

    _rows, meta = validate_paginated(api_client.list_products(BCM_HEADERS))
    assert meta["total_count"] == 0


def test_supply_status_on_an_unknown_reseller_id_is_a_reseller_not_found():
    """The path reseller is resolved before the supply axis is consulted at all.

    PRD: "When a single request violates several rules, exactly one error is returned,
    and which one is fully determined."

    Design: Corner/errors/error_reseller_not_found_on_supply_status_returns_not_found
    """
    _empty_world()

    validate_error(
        api_client.set_supply_status(
            NON_EXISTENT_UUID, supply_status_payload("OPEN"), BCM_HEADERS
        ),
        "ERR_RESELLER_NOT_FOUND",
        404,
    )

    _rows, meta = validate_paginated(api_client.list_resellers(BCM_HEADERS))
    assert meta["total_count"] == 0


def test_diversion_exposure_on_an_unknown_distributor_id_is_a_distributor_not_found():
    """A computed read enforces path existence rather than answering with a zero envelope.

    PRD: "An empty candidate set yields a counted-unit figure of 0 and an exposure of 0,
    with no division attempted."

    Design: Corner/errors/error_distributor_not_found_on_exposure_read_returns_not_found
    """
    _empty_world()

    validate_error(
        api_client.get_diversion_exposure(
            NON_EXISTENT_UUID, BCM_HEADERS, params={"variant": "TRACE_ATTRIBUTED"}
        ),
        "ERR_DISTRIBUTOR_NOT_FOUND",
        404,
    )


# --------------------------------------------------------------------------- #
# Path existence on the agreement, observation, violation and notice endpoints
# --------------------------------------------------------------------------- #
def test_sending_an_unknown_agreement_id_is_an_agreement_not_found():
    """The unknown agreement short-circuits before any reseller axis is moved.

    PRD: "The transition stamps `sent_at` with the current logical clock, advances the
    agreement's `version`, and moves the reseller's authorization axis `APPLIED →
    PENDING_AGREEMENT` while advancing the reseller's `version` as well."

    Design: Corner/errors/error_agreement_not_found_on_send_returns_not_found
    """
    _policy, reseller = _applied_reseller()
    assert reseller["authorization_status"] == "APPLIED"

    validate_error(
        api_client.send_agreement(NON_EXISTENT_UUID, BCM_HEADERS),
        "ERR_AGREEMENT_NOT_FOUND",
        404,
    )

    after = read_reseller(reseller["id"])
    assert after["authorization_status"] == "APPLIED"
    assert after["supply_status"] == "HOLD"
    assert after["hold_reason"] == "PENDING_AUTHORIZATION"
    assert after["version"] == reseller["version"]


def test_evaluating_an_unknown_observation_id_is_an_observation_not_found():
    """An unknown row is a 404, distinct from the 409 an already-evaluated row earns.

    PRD: "It requires `evaluation_status` to be `CAPTURED` — a second attempt on an
    already-evaluated row is rejected with `ERR_ALREADY_EVALUATED` — and it requires a
    governing policy to exist for `observed_at` in the sense of §3.1, with the selected
    policy being one whose status is `PUBLISHED`, `SUPERSEDED` or `WITHDRAWN` and whose
    `effective_from` is at or before `observed_at`; otherwise `ERR_NO_GOVERNING_POLICY`."

    Design: Corner/errors/error_observation_not_found_on_evaluate_returns_not_found
    """
    _policy, _product = _policy_and_product()

    validate_error(
        api_client.evaluate_observation(NON_EXISTENT_UUID, ANALYST_HEADERS),
        "ERR_OBSERVATION_NOT_FOUND",
        404,
    )

    _rows, meta = validate_paginated(api_client.list_violations(BCM_HEADERS))
    assert meta["total_count"] == 0


def test_disputing_an_unknown_violation_id_is_a_violation_not_found_not_an_ownership_failure():
    """Path existence outranks the ownership check a reseller would otherwise trip.

    PRD: "For the two entity-backed roles, `X-User-ID` equals the owning foreign key of
    the target row, else `ERR_NOT_RESOURCE_OWNER` (403)."

    Design: Corner/errors/error_violation_not_found_on_dispute_returns_not_found
    """
    _policy, reseller, _agreement = _authorized_reseller()
    assert reseller["authorization_status"] == "AUTHORIZED"

    validate_error(
        api_client.dispute_violation(
            NON_EXISTENT_UUID,
            {"dispute_reason": "Not our listing"},
            make_reseller_headers(reseller["id"]),
        ),
        "ERR_VIOLATION_NOT_FOUND",
        404,
    )


def test_acknowledging_an_unknown_notice_id_is_a_notice_not_found():
    """No acknowledgement is recorded anywhere when the notice id does not resolve.

    PRD: "A reseller may acknowledge a notice, moving it `ISSUED → ACKNOWLEDGED` with
    `acknowledged_at` stamped from the current clock and the notice's `version`
    advanced."

    Design: Corner/errors/error_notice_not_found_on_acknowledge_returns_not_found
    """
    _policy, reseller, _agreement = _authorized_reseller()

    validate_error(
        api_client.acknowledge_notice(
            NON_EXISTENT_UUID, make_reseller_headers(reseller["id"])
        ),
        "ERR_NOTICE_NOT_FOUND",
        404,
    )

    _rows, meta = validate_paginated(api_client.list_notices(BCM_HEADERS))
    assert meta["total_count"] == 0


# --------------------------------------------------------------------------- #
# Path existence on the exception, serial-unit, test-purchase and chargeback
# endpoints
# --------------------------------------------------------------------------- #
def test_deciding_an_unknown_exception_id_is_an_exception_not_found():
    """The decision never reaches the override-floor arithmetic or the product counter.

    PRD: "It increases the product's `open_exception_count` by one and advances the
    product's `version`."

    Design: Corner/errors/error_exception_not_found_on_decision_returns_not_found
    """
    _policy, product = _policy_and_product()
    assert product["open_exception_count"] == 0

    validate_error(
        api_client.decide_exception(
            NON_EXISTENT_UUID,
            exception_decision_payload("APPROVE", decision_reason="Campaign approved"),
            COUNSEL_HEADERS,
        ),
        "ERR_EXCEPTION_NOT_FOUND",
        404,
    )

    after = read_product(product["id"])
    assert after["open_exception_count"] == 0
    assert after["version"] == product["version"]

    _rows, meta = validate_paginated(api_client.list_exceptions(BCM_HEADERS))
    assert meta["total_count"] == 0


def test_shipping_downstream_from_an_unknown_serial_unit_id_is_a_serial_unit_not_found():
    """An unknown unit id in the path is not the unregistered-serial failure of a body.

    PRD: "A serial that matches no registered unit is rejected with
    `ERR_SERIAL_NOT_REGISTERED`; a serial that resolves to a unit whose custody state is
    neither `SHIPPED_TO_DISTRIBUTOR` nor `SHIPPED_TO_RESELLER` is rejected with
    `ERR_SERIAL_NOT_TRACEABLE`, since a unit already traced or recalled cannot ground a
    fresh trace."

    Design: Corner/errors/error_serial_unit_not_found_on_ship_downstream_returns_not_found
    """
    _policy, reseller, _agreement = _authorized_reseller()
    distributor = create_distributor(legal_name="Northwind Distribution")

    validate_error(
        api_client.ship_downstream(
            NON_EXISTENT_UUID,
            ship_downstream_payload(reseller["id"]),
            make_distributor_headers(distributor["id"]),
        ),
        "ERR_SERIAL_UNIT_NOT_FOUND",
        404,
    )

    _rows, meta = validate_paginated(api_client.list_serial_units(BCM_HEADERS))
    assert meta["total_count"] == 0


def test_confirming_an_unknown_test_purchase_id_is_a_test_purchase_not_found():
    """No unit is driven to TRACED_UNAUTHORIZED by a purchase id that does not resolve.

    PRD: "It also reaches into two other rows: the linked observation has
    `unauthorized_seller_confirmed` set to true with its `version` advanced, and the
    traced unit moves from `SHIPPED_TO_DISTRIBUTOR` or `SHIPPED_TO_RESELLER` to
    `TRACED_UNAUTHORIZED` with `traced_at` stamped from the current clock and its own
    `version` advanced."

    Design: Corner/errors/error_test_purchase_not_found_on_confirm_outcome_returns_not_found
    """
    _policy, product = _policy_and_product()
    distributor = create_distributor(legal_name="Northwind Distribution")
    unit = create_serial_unit(
        product["id"], distributor["id"], serial_number="SN-0001", lot_code="LOT-A"
    )
    assert unit["status"] == "SHIPPED_TO_DISTRIBUTOR"

    validate_error(
        api_client.confirm_outcome(
            NON_EXISTENT_UUID,
            confirm_outcome_payload(
                "UNAUTHORIZED", outcome_reason="No authorization on file"
            ),
            ANALYST_HEADERS,
        ),
        "ERR_TEST_PURCHASE_NOT_FOUND",
        404,
    )

    after = read_serial_unit(unit["id"])
    assert after["status"] == "SHIPPED_TO_DISTRIBUTOR"
    assert after["traced_at"] is None
    assert after["version"] == unit["version"]


def test_disputing_an_unknown_chargeback_id_is_a_chargeback_not_found():
    """The 404 precedes both the ownership check and the ASSESSED/UPHELD state guard.

    PRD: "Supplying a `dispute_reason` moves a chargeback `ASSESSED → DISPUTED` or
    `UPHELD → DISPUTED`, recording that reason and advancing the chargeback's `version`;
    it requires the chargeback to be in `ASSESSED` or `UPHELD`, requires `dispute_rounds`
    to be strictly below 2 (else `ERR_DISPUTE_ROUNDS_EXHAUSTED`), and requires the acting
    distributor's `X-User-ID` to equal the chargeback's `distributor_id`."

    Design: Corner/errors/error_chargeback_not_found_on_dispute_returns_not_found
    """
    _empty_world()
    distributor = create_distributor(
        legal_name="Northwind Distribution", annual_chargeback_cap_cents=500000
    )
    assert distributor["chargeback_balance_cents"] == 0

    validate_error(
        api_client.dispute_chargeback(
            NON_EXISTENT_UUID,
            chargeback_dispute_payload(
                dispute_reason="Units were never in our custody"
            ),
            make_distributor_headers(distributor["id"]),
        ),
        "ERR_CHARGEBACK_NOT_FOUND",
        404,
    )

    after = read_distributor(distributor["id"])
    assert after["chargeback_balance_cents"] == 0
    assert after["diversion_score"] == 0
    assert after["version"] == distributor["version"]


# --------------------------------------------------------------------------- #
# Request shape and transition legality on families the not-found cases skip
# --------------------------------------------------------------------------- #
def test_a_negative_annual_chargeback_cap_is_rejected_as_a_request_shape_failure():
    """The numeric-range step is generic: a negative ceiling is a plain ERR_VALIDATION.

    PRD: "Distributors enter the system through a `BrandChannelManager` registration
    carrying a `legal_name` and an `annual_chargeback_cap_cents` ceiling that must be
    strictly greater than zero."

    Design: Corner/errors/error_validation_on_distributor_cap_rejected
    """
    _empty_world()

    validate_error(
        api_client.create_distributor(
            distributor_payload(legal_name="Bad Cap Ltd", annual_chargeback_cap_cents=-1),
            BCM_HEADERS,
        ),
        "ERR_VALIDATION",
        400,
    )

    _rows, meta = validate_paginated(api_client.list_distributors(BCM_HEADERS))
    assert meta["total_count"] == 0


def test_a_second_submit_review_from_in_legal_review_is_an_invalid_state():
    """The policy machine reaches ERR_INVALID_STATE and the version does not move again.

    PRD: "It requires the policy to be in `DRAFT`, and it re-checks that
    `termination_points_threshold` is strictly greater than `suspension_points_threshold`
    — a draft whose ladder thresholds have been edited into an incoherent order cannot be
    handed to counsel."

    Design: Corner/errors/error_invalid_state_on_second_submit_review_returns_invalid_state
    """
    _empty_world()
    policy = create_policy_in_review(policy_code="MAP-2026-A")
    assert policy["status"] == "IN_LEGAL_REVIEW"
    assert policy["version"] == 2

    validate_error(
        api_client.submit_policy_review(policy["id"], BCM_HEADERS),
        "ERR_INVALID_STATE",
        409,
    )

    after = read_policy(policy["id"])
    assert after["status"] == "IN_LEGAL_REVIEW"
    assert after["version"] == 2
