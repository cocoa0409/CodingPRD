"""Endpoint breadth: exceptions, serialized tracing, chargebacks and the sweep.

Each test drives one declared operation on the exception, tracing and
distributor-accountability families, plus the two system capabilities — the
sweep and the logical clock — that the rest of the contract depends on.
"""
from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import (
    ADMIN_HEADERS,
    ANALYST_HEADERS,
    BCM_HEADERS,
    COUNSEL_HEADERS,
    api_client,
    make_distributor_headers,
    make_reseller_headers,
)
from test_helpers.assertions import (
    assert_same_instant,
    score_delta,
    standing_for_score,
    tier_rate_for_score,
)
from test_helpers.factories import (
    chargeback_dispute_decision_payload,
    chargeback_dispute_payload,
    chargeback_payload,
    clock_payload,
    confirm_outcome_payload,
    exception_decision_payload,
    exception_payload,
    serial_capture_payload,
    serial_unit_payload,
    ship_downstream_payload,
    test_purchase_payload,
)
from test_helpers.fixtures import (
    approve_exception,
    assess_chargeback,
    capture_observation,
    capture_purchase_serial,
    confirm_unauthorized,
    create_active_agreement,
    create_authorized_reseller,
    create_confirmed_trace,
    create_detected_violation,
    create_distributor,
    create_product,
    create_published_policy,
    create_reseller,
    create_serial_unit,
    current_distributor_version,
    issue_notice,
    order_test_purchase,
    pin_clock,
    read_chargeback,
    read_distributor,
    read_exception,
    read_product,
    read_serial_unit,
    request_exception,
    ship_unit_downstream,
)

CLOCK_AUG_01 = "2026-08-01T00:00:00Z"
CLOCK_AUG_20 = "2026-08-20T00:00:00Z"
CLOCK_AUG_25 = "2026-08-25T00:00:00Z"
OBSERVED_AUG_05 = "2026-08-05T00:00:00Z"
ORDERED_AUG_19 = "2026-08-19T00:00:00Z"
WINDOW_STARTS = "2026-08-10T00:00:00Z"
WINDOW_ENDS = "2026-08-25T00:00:00Z"
LEG_ONE_ENDS = "2026-08-20T00:00:00Z"
LEG_TWO_ENDS = "2026-08-30T00:00:00Z"
TERM_ENDS = "2027-06-30T00:00:00Z"


def _setup_policy_and_product():
    """A published policy at the default clock with one serialized product."""
    pin_clock(CLOCK_AUG_01)
    policy = create_published_policy(CLOCK_AUG_01, policy_code="MAP-2026-A")
    product = create_product(
        policy["id"], sku="SKU-AUDIO-1", name="Studio Headphones", msrp_cents=20000,
        standard_map_floor_cents=15000,
    )
    return policy, product


# --------------------------------------------------------------------------- #
# PricingException
# --------------------------------------------------------------------------- #
def test_requesting_an_exception_leaves_the_floor_unresolved_until_the_decision():
    """The request records the ask; nothing is installed and no count moves.

    PRD: "A new exception is created in status `REQUESTED`, with `requested_by_user_id`
    stamped from the requesting manager's `X-User-ID`, with `override_floor_cents`,
    `approved_by_user_id` and `decision_reason` all null, and with
    `voided_violation_count` at 0."

    Design: Corner/endpoints/create_pricing_exception_starts_in_requested
    """
    _policy, product = _setup_policy_and_product()

    exception = validate_success(
        api_client.create_exception(
            exception_payload(
                product["id"],
                exception_type="PROMOTIONAL_EVENT",
                starts_at=WINDOW_STARTS,
                ends_at=WINDOW_ENDS,
                channel_scope="ALL",
                requested_override_floor_cents=13000,
                dealer_input_source="BRAND_MARKETING_PLAN",
            ),
            BCM_HEADERS,
        ),
        201,
    )

    assert exception["status"] == "REQUESTED"
    assert exception["override_floor_cents"] is None
    assert exception["approved_by_user_id"] is None
    assert exception["decision_reason"] is None
    assert exception["channel_scope"] == "ALL"
    assert exception["voided_violation_count"] == 0
    assert exception["requested_by_user_id"] == "bcm-1"
    assert read_product(product["id"])["open_exception_count"] == 0


def test_approving_an_exception_installs_the_requested_floor_and_counts_the_product():
    """Approval snapshots the requested figure and raises the open-exception count.

    PRD: "For a `BUNDLE` or `PROMOTIONAL_EVENT` exception the installed floor is exactly
    the `requested_override_floor_cents` supplied on the request, but it must sit inside
    a permitted band: it must be strictly less than the product's
    `standard_map_floor_cents` — an "exception" that raises the floor is not an exception
    — and it must be at least the product's `standard_map_floor_cents` multiplied by 0.50
    and truncated downward to whole cents, so no exception may cut the floor by more than
    half." "It increases the product's `open_exception_count` by one and advances the
    product's `version`."

    Design: Corner/endpoints/exception_decision_approve_resolves_the_override_floor
    """
    _policy, product = _setup_policy_and_product()
    exception = request_exception(
        product["id"],
        exception_type="PROMOTIONAL_EVENT",
        starts_at=WINDOW_STARTS,
        ends_at=WINDOW_ENDS,
        channel_scope="ALL",
        requested_override_floor_cents=13000,
    )

    approved = validate_success(
        api_client.decide_exception(
            exception["id"],
            exception_decision_payload("APPROVE", decision_reason="Registered summer campaign"),
            COUNSEL_HEADERS,
        )
    )

    assert approved["status"] == "APPROVED"
    assert approved["override_floor_cents"] == 13000
    assert approved["voided_violation_count"] == 0
    assert approved["approved_by_user_id"] == "counsel-1"
    assert read_product(product["id"])["open_exception_count"] == 1


def test_reading_one_exception_returns_its_half_open_window_and_scope():
    """The window boundaries and the channel scope read back as stored.

    PRD: "Exceptions are readable individually, and the collection may be filtered by
    `product_id`, by `exception_type` or by `status`."

    Design: Corner/endpoints/read_one_exception_returns_its_window_and_scope
    """
    _policy, product = _setup_policy_and_product()
    exception = request_exception(
        product["id"],
        exception_type="PROMOTIONAL_EVENT",
        starts_at=WINDOW_STARTS,
        ends_at=WINDOW_ENDS,
        channel_scope="ALL",
        requested_override_floor_cents=13000,
    )
    approve_exception(exception["id"])
    reseller = create_reseller(legal_name="Acme Retail LLC")

    read = validate_success(
        api_client.get_exception(exception["id"], make_reseller_headers(reseller["id"]))
    )

    assert_same_instant(read["starts_at"], WINDOW_STARTS, "starts_at")
    assert_same_instant(read["ends_at"], WINDOW_ENDS, "ends_at")
    assert read["channel_scope"] == "ALL"
    assert read["status"] == "APPROVED"
    assert read["override_floor_cents"] == 13000


def test_the_exception_collection_separates_an_approved_leg_from_a_rejected_one():
    """Two adjacent half-open windows on one product diverge only in status.

    PRD: "Half-open means a window whose `starts_at` falls exactly on another's `ends_at`
    is adjacent, not overlapping — back-to-back promotional weeks are legal."

    Design: Corner/endpoints/list_exceptions_filters_by_type_and_status
    """
    _policy, product = _setup_policy_and_product()
    first = request_exception(
        product["id"],
        exception_type="PROMOTIONAL_EVENT",
        starts_at=WINDOW_STARTS,
        ends_at=LEG_ONE_ENDS,
        channel_scope="PHYSICAL_RETAIL",
        requested_override_floor_cents=13000,
    )
    second = request_exception(
        product["id"],
        exception_type="PROMOTIONAL_EVENT",
        starts_at=LEG_ONE_ENDS,
        ends_at=LEG_TWO_ENDS,
        channel_scope="PHYSICAL_RETAIL",
        requested_override_floor_cents=14000,
    )
    validate_success(
        api_client.decide_exception(
            first["id"],
            exception_decision_payload("APPROVE", decision_reason="Leg one funded"),
            COUNSEL_HEADERS,
        )
    )
    validate_success(
        api_client.decide_exception(
            second["id"],
            exception_decision_payload("REJECT", decision_reason="Leg two withdrawn"),
            COUNSEL_HEADERS,
        )
    )

    approved, approved_meta = validate_paginated(
        api_client.list_exceptions(
            BCM_HEADERS,
            params={
                "product_id": product["id"],
                "exception_type": "PROMOTIONAL_EVENT",
                "status": "APPROVED",
                "limit": 10,
                "offset": 0,
            },
        )
    )
    assert approved_meta["total_count"] == 1
    assert [row["id"] for row in approved] == [first["id"]]

    both, both_meta = validate_paginated(
        api_client.list_exceptions(BCM_HEADERS, params={"exception_type": "PROMOTIONAL_EVENT"})
    )
    assert both_meta["total_count"] == 2
    assert {row["id"] for row in both} == {first["id"], second["id"]}

    rejected, rejected_meta = validate_paginated(
        api_client.list_exceptions(BCM_HEADERS, params={"status": "REJECTED"})
    )
    assert rejected_meta["total_count"] == 1
    assert [row["id"] for row in rejected] == [second["id"]]


# --------------------------------------------------------------------------- #
# SerialUnit
# --------------------------------------------------------------------------- #
def test_registering_a_serial_unit_opens_it_in_the_distributors_custody():
    """Both foreign keys are stored and the downstream hop is still empty.

    PRD: "The unit is created in custody state `SHIPPED_TO_DISTRIBUTOR` with
    `downstream_reseller_id`, `shipped_downstream_at` and `traced_at` all null, and the
    named distributor's `shipped_units_total` — which counts every unit whose
    `shipped_distributor_id` is that distributor, in any custody state — is increased
    accordingly."

    Design: Corner/endpoints/create_serial_unit_links_product_and_distributor
    """
    _policy, product = _setup_policy_and_product()
    distributor = create_distributor(
        legal_name="Northwind Distribution", annual_chargeback_cap_cents=500000
    )

    unit = validate_success(
        api_client.create_serial_unit(
            serial_unit_payload(
                product["id"], distributor["id"], serial_number="SN-0001", lot_code="LOT-A"
            ),
            BCM_HEADERS,
        ),
        201,
    )

    assert unit["status"] == "SHIPPED_TO_DISTRIBUTOR"
    assert unit["downstream_reseller_id"] is None
    assert unit["shipped_downstream_at"] is None
    assert unit["traced_at"] is None
    assert unit["lot_code"] == "LOT-A"
    assert unit["shipped_distributor_id"] == distributor["id"]
    assert unit["product_id"] == product["id"]
    assert read_distributor(distributor["id"])["shipped_units_total"] == 1


def test_shipping_downstream_to_an_open_reseller_stamps_the_hop_at_the_clock():
    """The next custody hop is legal precisely because the target supply axis is OPEN.

    PRD: "Supplying a `downstream_reseller_id` moves a unit
    `SHIPPED_TO_DISTRIBUTOR → SHIPPED_TO_RESELLER`, setting `downstream_reseller_id` and
    stamping `shipped_downstream_at` with the current clock, and advancing the unit's
    `version`." "Three preconditions apply: the unit must be in
    `SHIPPED_TO_DISTRIBUTOR`, the acting distributor's `X-User-ID` must equal the unit's
    `shipped_distributor_id`, and the target reseller's `supply_status` must be `OPEN` —
    a distributor may not ship to a reseller the brand has put on hold or cut off, which
    is precisely the mechanism a supply hold is meant to be."

    Design: Corner/endpoints/ship_downstream_requires_an_open_supply_status
    """
    policy, product = _setup_policy_and_product()
    distributor = create_distributor(
        legal_name="Northwind Distribution", annual_chargeback_cap_cents=500000
    )
    reseller, _agreement = create_authorized_reseller(
        policy["id"],
        reseller_overrides={"legal_name": "Acme Retail LLC", "primary_channel": "MARKETPLACE"},
        agreement_overrides={"permitted_channels": ["MARKETPLACE"], "term_ends_at": TERM_ENDS},
    )
    assert reseller["supply_status"] == "OPEN"
    unit = create_serial_unit(
        product["id"], distributor["id"], serial_number="SN-0002", lot_code="LOT-A"
    )

    shipped = validate_success(
        api_client.ship_downstream(
            unit["id"],
            ship_downstream_payload(reseller["id"]),
            make_distributor_headers(distributor["id"]),
        )
    )

    assert shipped["status"] == "SHIPPED_TO_RESELLER"
    assert shipped["downstream_reseller_id"] == reseller["id"]
    assert_same_instant(shipped["shipped_downstream_at"], CLOCK_AUG_01, "shipped_downstream_at")


def test_a_traced_unit_keeps_both_custody_links_beside_its_trace_stamp():
    """Tracing adds a stamp without erasing where the unit came from or went.

    PRD: "It also reaches into two other rows: the linked observation has
    `unauthorized_seller_confirmed` set to true with its `version` advanced, and the
    traced unit moves from `SHIPPED_TO_DISTRIBUTOR` or `SHIPPED_TO_RESELLER` to
    `TRACED_UNAUTHORIZED` with `traced_at` stamped from the current clock and its own
    `version` advanced."

    Design: Corner/endpoints/read_one_serial_unit_returns_its_trace_position
    """
    policy, product = _setup_policy_and_product()
    distributor = create_distributor(
        legal_name="Northwind Distribution", annual_chargeback_cap_cents=500000
    )
    reseller, _agreement = create_authorized_reseller(
        policy["id"],
        reseller_overrides={"legal_name": "Acme Retail LLC", "primary_channel": "MARKETPLACE"},
        agreement_overrides={"permitted_channels": ["MARKETPLACE"], "term_ends_at": TERM_ENDS},
    )
    unit = create_serial_unit(
        product["id"], distributor["id"], serial_number="SN-0002", lot_code="LOT-A"
    )
    ship_unit_downstream(unit["id"], distributor["id"], reseller["id"])
    pin_clock(CLOCK_AUG_20)
    observation = capture_observation(
        product["id"], listed_price_cents=9000, seller_display_name="GreyBox Deals"
    )
    purchase = order_test_purchase(observation["id"])
    capture_purchase_serial(purchase["id"], "SN-0002")
    confirm_unauthorized(purchase["id"])

    read = validate_success(
        api_client.get_serial_unit(unit["id"], make_distributor_headers(distributor["id"]))
    )

    assert read["status"] == "TRACED_UNAUTHORIZED"
    assert read["shipped_distributor_id"] == distributor["id"]
    assert read["downstream_reseller_id"] == reseller["id"]
    assert_same_instant(read["traced_at"], CLOCK_AUG_20, "traced_at")


def test_the_serial_unit_collection_filters_by_lot_and_by_custody_state():
    """Two units of one lot diverge in custody, so lot and status cut differently.

    PRD: "Units are readable individually and as a collection filtered by `product_id`,
    `shipped_distributor_id`, `downstream_reseller_id`, `lot_code` or `status`."

    Design: Corner/endpoints/list_serial_units_filters_by_lot_and_status
    """
    _policy, product = _setup_policy_and_product()
    distributor = create_distributor(
        legal_name="Northwind Distribution", annual_chargeback_cap_cents=500000
    )
    _purchase, traced, _observation = create_confirmed_trace(
        product["id"], distributor["id"], serial_number="SN-0001", lot_code="LOT-A"
    )
    untraced = create_serial_unit(
        product["id"], distributor["id"], serial_number="SN-0003", lot_code="LOT-A"
    )

    rows, meta = validate_paginated(
        api_client.list_serial_units(
            COUNSEL_HEADERS,
            params={
                "lot_code": "LOT-A",
                "status": "TRACED_UNAUTHORIZED",
                "limit": 10,
                "offset": 0,
            },
        )
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [traced["id"]]

    lot, lot_meta = validate_paginated(
        api_client.list_serial_units(COUNSEL_HEADERS, params={"lot_code": "LOT-A"})
    )
    assert lot_meta["total_count"] == 2

    shipped, shipped_meta = validate_paginated(
        api_client.list_serial_units(
            COUNSEL_HEADERS, params={"shipped_distributor_id": distributor["id"]}
        )
    )
    assert shipped_meta["total_count"] == 2

    in_custody, in_custody_meta = validate_paginated(
        api_client.list_serial_units(
            COUNSEL_HEADERS,
            params={"product_id": product["id"], "status": "SHIPPED_TO_DISTRIBUTOR"},
        )
    )
    assert in_custody_meta["total_count"] == 1
    assert [row["id"] for row in in_custody] == [untraced["id"]]


# --------------------------------------------------------------------------- #
# TestPurchase
# --------------------------------------------------------------------------- #
def _setup_grey_listing():
    """An unmatched grey-market marketplace listing at 9000 with one Northwind unit."""
    _policy, product = _setup_policy_and_product()
    distributor = create_distributor(
        legal_name="Northwind Distribution", annual_chargeback_cap_cents=500000
    )
    unit = create_serial_unit(
        product["id"], distributor["id"], serial_number="SN-0001", lot_code="LOT-A"
    )
    pin_clock(CLOCK_AUG_20)
    observation = capture_observation(
        product["id"],
        seller_display_name="GreyBox Deals",
        listing_url="https://mkt.example/l/9",
        listed_price_cents=9000,
        observed_at=ORDERED_AUG_19,
    )
    return product, distributor, unit, observation


def test_ordering_a_test_purchase_hangs_it_off_the_observation_in_ordered():
    """The purchase opens with both trace fields still empty.

    PRD: "The purchase is created in status `ORDERED` with `purchaser_user_id` stamped
    from the analyst's `X-User-ID` and with `captured_serial_number`,
    `traced_serial_unit_id` and `outcome_reason` all null."

    Design: Corner/endpoints/create_test_purchase_links_the_observation
    """
    _product, _distributor, _unit, observation = _setup_grey_listing()

    purchase = validate_success(
        api_client.create_test_purchase(
            test_purchase_payload(
                observation["id"], ordered_at=ORDERED_AUG_19, purchase_price_cents=9000
            ),
            ANALYST_HEADERS,
        ),
        201,
    )

    assert purchase["status"] == "ORDERED"
    assert purchase["captured_serial_number"] is None
    assert purchase["traced_serial_unit_id"] is None
    assert purchase["outcome_reason"] is None
    assert purchase["observation_id"] == observation["id"]
    assert purchase["purchase_price_cents"] == 9000
    assert purchase["purchaser_user_id"] == "analyst-1"


def test_capturing_a_serial_resolves_the_printed_string_to_the_registered_unit():
    """The natural key becomes an identifier while the unit's custody is untouched.

    PRD: "Supplying a `serial_number` moves the purchase `ORDERED → SERIAL_CAPTURED`,
    storing that value as `captured_serial_number` and resolving it to a
    `traced_serial_unit_id`, and advancing the purchase's `version`."

    Design: Corner/endpoints/serial_capture_resolves_the_natural_key_to_a_unit
    """
    _product, _distributor, unit, observation = _setup_grey_listing()
    purchase = order_test_purchase(
        observation["id"], ordered_at=ORDERED_AUG_19, purchase_price_cents=9000
    )

    captured = validate_success(
        api_client.capture_serial(
            purchase["id"], serial_capture_payload("SN-0001"), ANALYST_HEADERS
        )
    )

    assert captured["status"] == "SERIAL_CAPTURED"
    assert captured["captured_serial_number"] == "SN-0001"
    assert captured["traced_serial_unit_id"] == unit["id"]
    assert read_serial_unit(unit["id"])["status"] == "SHIPPED_TO_DISTRIBUTOR"


def test_an_authorized_outcome_clears_the_purchase_and_leaves_the_unit_alone():
    """The cleared branch is terminal for the purchase and only the purchase.

    PRD: "An `outcome` of `AUTHORIZED` moves the purchase `SERIAL_CAPTURED → CLEARED`,
    recording `outcome_reason` and advancing only the purchase's own `version`; the
    traced unit and the observation are left entirely untouched."

    Design: Corner/endpoints/confirm_outcome_cleared_ends_the_trace_without_a_chargeback
    """
    _product, distributor, unit, observation = _setup_grey_listing()
    purchase = order_test_purchase(
        observation["id"], ordered_at=ORDERED_AUG_19, purchase_price_cents=9000
    )
    capture_purchase_serial(purchase["id"], "SN-0001")

    cleared = validate_success(
        api_client.confirm_outcome(
            purchase["id"],
            confirm_outcome_payload(
                "AUTHORIZED", outcome_reason="Seller produced a valid authorization letter"
            ),
            ANALYST_HEADERS,
        )
    )

    assert cleared["status"] == "CLEARED"
    assert cleared["outcome_reason"] == "Seller produced a valid authorization letter"

    untouched = read_serial_unit(unit["id"])
    assert untouched["status"] == "SHIPPED_TO_DISTRIBUTOR"
    assert untouched["traced_at"] is None
    assert read_distributor(distributor["id"])["diversion_score"] == 0


def test_reading_one_test_purchase_closes_the_loop_from_listing_to_unit():
    """The row carries the observation, the captured serial and the resolved unit at once.

    PRD: "Test purchases are readable individually and as a collection filtered by
    `observation_id`, `traced_serial_unit_id` or `status`."

    Design: Corner/endpoints/read_one_test_purchase_returns_the_traced_unit
    """
    _product, _distributor, unit, observation = _setup_grey_listing()
    purchase = order_test_purchase(
        observation["id"], ordered_at=ORDERED_AUG_19, purchase_price_cents=9000
    )
    capture_purchase_serial(purchase["id"], "SN-0001")
    confirm_unauthorized(purchase["id"])

    read = validate_success(api_client.get_test_purchase(purchase["id"], ADMIN_HEADERS))

    assert read["status"] == "CONFIRMED_UNAUTHORIZED"
    assert read["observation_id"] == observation["id"]
    assert read["captured_serial_number"] == "SN-0001"
    assert read["traced_serial_unit_id"] == unit["id"]
    assert_same_instant(read["ordered_at"], ORDERED_AUG_19, "ordered_at")


def test_the_test_purchase_collection_filters_by_the_derived_traced_unit():
    """The nullable trace link is a first-class filter beside status and observation.

    PRD: "Test purchases are readable individually and as a collection filtered by
    `observation_id`, `traced_serial_unit_id` or `status`."

    Design: Corner/endpoints/list_test_purchases_filters_by_traced_unit
    """
    product, distributor, unit, observation = _setup_grey_listing()
    confirmed = order_test_purchase(
        observation["id"], ordered_at=ORDERED_AUG_19, purchase_price_cents=9000
    )
    capture_purchase_serial(confirmed["id"], "SN-0001")
    confirm_unauthorized(confirmed["id"])
    second_observation = capture_observation(
        product["id"],
        seller_display_name="GreyBox Deals Two",
        listing_url="https://mkt.example/l/10",
        listed_price_cents=9500,
        observed_at=ORDERED_AUG_19,
    )
    ordered = order_test_purchase(
        second_observation["id"], ordered_at=ORDERED_AUG_19, purchase_price_cents=9500
    )

    traced, traced_meta = validate_paginated(
        api_client.list_test_purchases(
            make_distributor_headers(distributor["id"]),
            params={"traced_serial_unit_id": unit["id"], "limit": 10, "offset": 0},
        )
    )
    assert traced_meta["total_count"] == 1
    assert [row["id"] for row in traced] == [confirmed["id"]]

    still_ordered, ordered_meta = validate_paginated(
        api_client.list_test_purchases(ANALYST_HEADERS, params={"status": "ORDERED"})
    )
    assert ordered_meta["total_count"] == 1
    assert [row["id"] for row in still_ordered] == [ordered["id"]]

    by_observation, by_observation_meta = validate_paginated(
        api_client.list_test_purchases(
            ANALYST_HEADERS, params={"observation_id": second_observation["id"]}
        )
    )
    assert by_observation_meta["total_count"] == 1
    assert [row["id"] for row in by_observation] == [ordered["id"]]


# --------------------------------------------------------------------------- #
# DistributorChargeback
# --------------------------------------------------------------------------- #
def _setup_confirmed_diversion(serial_number="SN-0001"):
    """A confirmed trace against a Northwind unit at score 0 with a 500000 cap."""
    _policy, product = _setup_policy_and_product()
    distributor = create_distributor(
        legal_name="Northwind Distribution", annual_chargeback_cap_cents=500000
    )
    purchase, unit, _observation = create_confirmed_trace(
        product["id"], distributor["id"], serial_number=serial_number, lot_code="LOT-A"
    )
    return product, distributor, purchase, unit


def test_assessing_a_chargeback_freezes_the_pre_event_tier_onto_the_row():
    """Four units at the bottom tier price the event at one hundred dollars.

    PRD: "The `tier_rate_cents_per_unit` is 2500 cents when that pre-event score is
    strictly below 10.0, 4000 cents when it is at or above 10.0 but strictly below 25.0,
    and 6000 cents when it is at or above 25.0 — twenty-five, forty and sixty dollars a
    unit, with both tier boundaries inclusive at the lower bound." "The `amount_cents` is
    that per-unit rate multiplied by `diverted_units`."

    Design: Corner/endpoints/create_chargeback_links_distributor_and_test_purchase
    """
    _product, distributor, purchase, _unit = _setup_confirmed_diversion()

    chargeback = validate_success(
        api_client.assess_chargeback(
            chargeback_payload(
                distributor["id"],
                purchase["id"],
                current_distributor_version(distributor["id"]),
                diverted_units=4,
            ),
            BCM_HEADERS,
        ),
        201,
    )

    assert chargeback["status"] == "ASSESSED"
    assert chargeback["distributor_id"] == distributor["id"]
    assert chargeback["test_purchase_id"] == purchase["id"]
    assert chargeback["diverted_units"] == 4
    assert chargeback["tier_rate_cents_per_unit"] == tier_rate_for_score(0) == 2500
    assert chargeback["amount_cents"] == 10000
    assert chargeback["score_delta_applied"] == score_delta(4) == 10.0
    assert chargeback["dispute_rounds"] == 0


def test_disputing_a_chargeback_leaves_both_distributor_ledgers_in_place():
    """DISPUTED is still a contributing status, so the balance and score stand.

    PRD: "Supplying a `dispute_reason` moves a chargeback `ASSESSED → DISPUTED` or
    `UPHELD → DISPUTED`, recording that reason and advancing the chargeback's `version`;
    it requires the chargeback to be in `ASSESSED` or `UPHELD`, requires `dispute_rounds`
    to be strictly below 2 (else `ERR_DISPUTE_ROUNDS_EXHAUSTED`), and requires the acting
    distributor's `X-User-ID` to equal the chargeback's `distributor_id`."

    Design: Corner/endpoints/chargeback_dispute_records_the_reason
    """
    _product, distributor, purchase, _unit = _setup_confirmed_diversion()
    chargeback = assess_chargeback(distributor["id"], purchase["id"], diverted_units=4)

    disputed = validate_success(
        api_client.dispute_chargeback(
            chargeback["id"],
            chargeback_dispute_payload(
                dispute_reason="Units were stolen in transit, not diverted"
            ),
            make_distributor_headers(distributor["id"]),
        )
    )

    assert disputed["status"] == "DISPUTED"
    assert disputed["dispute_reason"] == "Units were stolen in transit, not diverted"

    ledger = read_distributor(distributor["id"])
    assert ledger["chargeback_balance_cents"] == 10000
    assert ledger["diversion_score"] == 10.0


def test_upholding_a_disputed_chargeback_is_a_status_only_write():
    """The round counter moves and the ledgers do not.

    PRD: "A `decision` of `UPHOLD` moves it `DISPUTED → UPHELD`: `dispute_rounds` is
    increased by one, `decision_reason` is recorded, the chargeback's `version` is
    advanced, and both ledgers are left exactly as they are — the `amount_cents` stays in
    the distributor's balance and the `score_delta_applied` stays in its diversion
    score."

    Design: Corner/endpoints/chargeback_dispute_decision_uphold_keeps_the_charge
    """
    _product, distributor, purchase, _unit = _setup_confirmed_diversion()
    chargeback = assess_chargeback(distributor["id"], purchase["id"], diverted_units=4)
    validate_success(
        api_client.dispute_chargeback(
            chargeback["id"],
            chargeback_dispute_payload(
                dispute_reason="Units were stolen in transit, not diverted"
            ),
            make_distributor_headers(distributor["id"]),
        )
    )

    upheld = validate_success(
        api_client.decide_chargeback_dispute(
            chargeback["id"],
            chargeback_dispute_decision_payload(
                "UPHOLD",
                decision_reason="Chain-of-custody records contradict the transit claim",
            ),
            COUNSEL_HEADERS,
        )
    )

    assert upheld["status"] == "UPHELD"
    assert upheld["dispute_rounds"] == 1

    ledger = read_distributor(distributor["id"])
    assert ledger["chargeback_balance_cents"] == 10000
    assert ledger["standing"] == standing_for_score(10.0) == "PROBATION"


def test_a_reversed_chargeback_keeps_the_tier_and_delta_it_once_applied():
    """The audit figures survive on the row after the ledgers are restored.

    PRD: "A `REVERSED` chargeback keeps its historical `amount_cents` and
    `score_delta_applied` on the row for audit but contributes to neither sum."

    Design: Corner/endpoints/read_one_chargeback_returns_the_frozen_tier
    """
    _product, distributor, purchase, _unit = _setup_confirmed_diversion()
    chargeback = assess_chargeback(distributor["id"], purchase["id"], diverted_units=4)
    validate_success(
        api_client.dispute_chargeback(
            chargeback["id"],
            chargeback_dispute_payload(
                dispute_reason="Units were stolen in transit, not diverted"
            ),
            make_distributor_headers(distributor["id"]),
        )
    )
    validate_success(
        api_client.decide_chargeback_dispute(
            chargeback["id"],
            chargeback_dispute_decision_payload(
                "REVERSE", decision_reason="Units were stolen in transit"
            ),
            COUNSEL_HEADERS,
        )
    )

    read = validate_success(
        api_client.get_chargeback(
            chargeback["id"], make_distributor_headers(distributor["id"])
        )
    )

    assert read["status"] == "REVERSED"
    assert read["tier_rate_cents_per_unit"] == 2500
    assert read["score_delta_applied"] == 10.0
    assert read["amount_cents"] == 10000
    assert read_distributor(distributor["id"])["chargeback_balance_cents"] == 0


def test_the_chargeback_collection_filters_by_distributor_purchase_and_status():
    """Two chargebacks against one distributor separate by status and by purchase.

    PRD: "Chargebacks are readable individually and as a collection filtered by
    `distributor_id`, `test_purchase_id` or `status`."

    Design: Corner/endpoints/list_chargebacks_filters_by_distributor_and_status
    """
    product, distributor, purchase, _unit = _setup_confirmed_diversion()
    first = assess_chargeback(distributor["id"], purchase["id"], diverted_units=4)
    second_purchase, _second_unit, _second_observation = create_confirmed_trace(
        product["id"], distributor["id"], serial_number="SN-0003", lot_code="LOT-A"
    )
    second = assess_chargeback(distributor["id"], second_purchase["id"], diverted_units=6)
    assert second["tier_rate_cents_per_unit"] == tier_rate_for_score(10.0) == 4000
    assert second["amount_cents"] == 24000
    validate_success(
        api_client.dispute_chargeback(
            first["id"],
            chargeback_dispute_payload(
                dispute_reason="Units were stolen in transit, not diverted"
            ),
            make_distributor_headers(distributor["id"]),
        )
    )

    disputed, disputed_meta = validate_paginated(
        api_client.list_chargebacks(
            BCM_HEADERS,
            params={
                "distributor_id": distributor["id"],
                "status": "DISPUTED",
                "limit": 10,
                "offset": 0,
            },
        )
    )
    assert disputed_meta["total_count"] == 1
    assert [row["id"] for row in disputed] == [first["id"]]

    both, both_meta = validate_paginated(
        api_client.list_chargebacks(BCM_HEADERS, params={"distributor_id": distributor["id"]})
    )
    assert both_meta["total_count"] == 2

    by_purchase, by_purchase_meta = validate_paginated(
        api_client.list_chargebacks(
            BCM_HEADERS, params={"test_purchase_id": second_purchase["id"]}
        )
    )
    assert by_purchase_meta["total_count"] == 1
    assert [row["id"] for row in by_purchase] == [second["id"]]

    assert read_distributor(distributor["id"])["chargeback_balance_cents"] == 34000
    assert read_chargeback(first["id"])["amount_cents"] == 10000


# --------------------------------------------------------------------------- #
# The sweep and the logical clock
# --------------------------------------------------------------------------- #
def test_the_sweep_reports_each_bucket_it_touched_separately():
    """One lapsed exception expires while the other three buckets stay empty.

    PRD: "The sweep responds with the `swept_at` instant it ran at and four counters:
    `expired_agreements`, `expired_exceptions`, `escalated_violations` and
    `reinstated_resellers`." "Second, exceptions in `APPROVED` whose `ends_at` is at or
    before the clock become `EXPIRED` and decrement their product's
    `open_exception_count`."

    Design: Corner/endpoints/enforcement_sweep_reports_every_bucket_it_touched
    """
    policy, product = _setup_policy_and_product()
    reseller = create_reseller(legal_name="Acme Retail LLC", primary_channel="MARKETPLACE")
    create_active_agreement(
        reseller["id"], policy["id"], permitted_channels=["MARKETPLACE", "OWN_WEBSITE"],
        term_ends_at=TERM_ENDS,
    )
    exception = request_exception(
        product["id"],
        exception_type="PROMOTIONAL_EVENT",
        starts_at=WINDOW_STARTS,
        ends_at=WINDOW_ENDS,
        channel_scope="ALL",
        requested_override_floor_cents=13000,
    )
    approve_exception(exception["id"])
    pin_clock(CLOCK_AUG_25)

    sweep = validate_success(api_client.run_sweep(ADMIN_HEADERS))

    assert_same_instant(sweep["swept_at"], CLOCK_AUG_25, "swept_at")
    assert sweep["expired_exceptions"] == 1
    assert sweep["escalated_violations"] == 0
    assert sweep["reinstated_resellers"] == 0
    assert read_exception(exception["id"])["status"] == "EXPIRED"
    assert read_product(product["id"])["open_exception_count"] == 0


def test_the_sweep_returns_four_zeroes_when_nothing_is_due():
    """A live agreement, a live exception and an open cure window are all left alone.

    PRD: "Running the sweep when nothing is due is legal and returns four zeroes."

    Design: Corner/endpoints/sweep_is_a_no_op_when_nothing_is_due
    """
    policy, product = _setup_policy_and_product()
    reseller, agreement = create_authorized_reseller(
        policy["id"],
        reseller_overrides={"legal_name": "Acme Retail LLC", "primary_channel": "MARKETPLACE"},
        agreement_overrides={
            "permitted_channels": ["MARKETPLACE", "OWN_WEBSITE"],
            "term_ends_at": TERM_ENDS,
        },
    )
    exception = request_exception(
        product["id"],
        exception_type="PROMOTIONAL_EVENT",
        starts_at=WINDOW_STARTS,
        ends_at=WINDOW_ENDS,
        channel_scope="ALL",
        requested_override_floor_cents=13000,
    )
    approve_exception(exception["id"])
    pin_clock(CLOCK_AUG_20)
    violation, _observation, _evaluation = create_detected_violation(
        product["id"],
        reseller["id"],
        # The approved exception installs a 13000 floor over the issuance instant,
        # so the listing must sit below 13000 for the notice to be issuable at all
        # (PRD 3.7: the recomputed final points must be strictly greater than zero).
        listed_price_cents=12000,
        observed_at=OBSERVED_AUG_05,
        listing_url="https://mkt.example/l/1",
    )
    issue_notice(reseller["id"], violation["id"])

    sweep = validate_success(api_client.run_sweep(BCM_HEADERS))

    assert sweep["expired_agreements"] == 0
    assert sweep["expired_exceptions"] == 0
    assert sweep["escalated_violations"] == 0
    assert sweep["reinstated_resellers"] == 0
    assert validate_success(api_client.get_violation(violation["id"], BCM_HEADERS))["status"] == (
        "NOTICED"
    )
    assert read_exception(exception["id"])["status"] == "APPROVED"
    assert validate_success(api_client.get_agreement(agreement["id"], BCM_HEADERS))["status"] == (
        "ACTIVE"
    )


def test_pinning_the_clock_reports_both_sides_of_the_jump():
    """The control returns the instant it installed and the one it replaced.

    PRD: "A `PlatformAdmin` may pin the clock to an arbitrary instant by supplying a
    `to_iso8601` value; the response reports the new `current_utc` and the
    `previous_utc` it replaced."

    Design: Corner/endpoints/clock_endpoint_reports_both_sides_of_the_jump
    """
    pin_clock(CLOCK_AUG_01)

    jumped = validate_success(
        api_client.set_clock(clock_payload(CLOCK_AUG_20)["to_iso8601"], ADMIN_HEADERS),
        200,
    )

    assert_same_instant(jumped["current_utc"], CLOCK_AUG_20, "current_utc")
    assert_same_instant(jumped["previous_utc"], CLOCK_AUG_01, "previous_utc")
