"""Rejection-order corners, part three: the remaining cross-entity referential
preconditions on serialized tracing and chargebacks, and the window-and-clock
checks on observations, exception windows and cure deadlines.

Each temporal boundary is exercised on both sides so the inclusive edge is pinned
as well as the rejection.
"""
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ANALYST_HEADERS,
    BCM_HEADERS,
    ApiErrorId,
    api_client,
    make_reseller_headers,
)
from test_helpers.assertions import assert_same_instant, violation_points
from test_helpers.constants import EVIDENCE_HASH_1, EVIDENCE_HASH_3
from test_helpers.factories import (
    chargeback_payload,
    cure_submission_payload,
    exception_payload,
    observation_payload,
    serial_capture_payload,
)
from test_helpers.fixtures import (
    approve_exception,
    capture_observation,
    capture_purchase_serial,
    confirm_unauthorized,
    create_active_agreement,
    create_detected_violation,
    create_distributor,
    create_product,
    create_published_policy,
    create_reseller,
    create_serial_unit,
    current_distributor_version,
    evaluate_observation,
    issue_notice,
    order_test_purchase,
    pin_clock,
    read_distributor,
    read_notice,
    read_product,
    read_reseller,
    read_serial_unit,
    read_test_purchase,
    read_violation,
)

CLOCK_AUG_01 = "2026-08-01T00:00:00Z"
CLOCK_AUG_20 = "2026-08-20T00:00:00Z"
CLOCK_AUG_30 = "2026-08-30T00:00:00Z"
CLOCK_AUG_31 = "2026-08-31T00:00:00Z"
OBSERVED_JUL_01 = "2026-07-01T00:00:00Z"
OBSERVED_AUG_18 = "2026-08-18T00:00:00Z"
ORDERED_AUG_19 = "2026-08-19T00:00:00Z"
TERM_ENDS = "2027-06-30T00:00:00Z"
CURE_DEADLINE = "2026-08-30T00:00:00Z"

STANDARD_FLOOR = 15000
WINDOW_180_STARTS = "2026-08-01T00:00:00Z"
WINDOW_180_ENDS = "2027-01-28T00:00:00Z"


# --------------------------------------------------------------------------- #
# Shared spine
# --------------------------------------------------------------------------- #
def _published_policy():
    pin_clock(CLOCK_AUG_01)
    return create_published_policy(effective_from=CLOCK_AUG_01)


def _headphones(policy_id):
    return create_product(
        policy_id,
        sku="SKU-AUDIO-1",
        name="Studio Headphones",
        msrp_cents=20000,
        standard_map_floor_cents=STANDARD_FLOOR,
    )


def _authorized_channel():
    """Published policy, headphones and an authorized Acme on the marketplace."""
    policy = _published_policy()
    product = _headphones(policy["id"])
    reseller = create_reseller(
        legal_name="Acme Retail LLC",
        contact_email="ops@acme.example",
        primary_channel="MARKETPLACE",
    )
    agreement = create_active_agreement(
        reseller["id"],
        policy["id"],
        permitted_channels=["MARKETPLACE", "OWN_WEBSITE"],
        quality_obligations=["AUTHENTICITY_LABELING"],
        term_ends_at=TERM_ENDS,
    )
    return {
        "policy": policy,
        "product": product,
        "reseller": reseller,
        "agreement": agreement,
    }


def _warned_acme():
    """Acme carrying a three-point warning whose cure deadline is 2026-08-30."""
    world = _authorized_channel()
    pin_clock(CLOCK_AUG_20)
    violation, observation, _evaluation = create_detected_violation(
        world["product"]["id"],
        world["reseller"]["id"],
        listed_price_cents=14000,
        channel="MARKETPLACE",
        observed_at=OBSERVED_AUG_18,
        seller_display_name="Acme Store",
        listing_url="https://mkt.example/l/1",
        evidence_hash=EVIDENCE_HASH_1,
    )
    world["violation"] = violation
    world["observation"] = observation
    world["notice"] = issue_notice(world["reseller"]["id"], violation["id"])
    return world


def _northwind():
    return create_distributor(
        legal_name="Northwind Distribution", annual_chargeback_cap_cents=500000
    )


def _grey_listing(product_id, listing_url, listed_price_cents, evidence_hash):
    observation = capture_observation(
        product_id,
        channel="MARKETPLACE",
        seller_display_name="GreyBox Deals",
        listing_url=listing_url,
        listed_price_cents=listed_price_cents,
        observed_at=OBSERVED_AUG_18,
        evidence_hash=evidence_hash,
    )
    evaluate_observation(observation["id"])
    return observation


def _confirmed_trace(product_id, distributor_id, serial_number, listing_url, evidence_hash):
    """Register a unit, buy the grey listing, read the serial and confirm the finding."""
    unit = create_serial_unit(
        product_id, distributor_id, serial_number=serial_number, lot_code="LOT-A"
    )
    observation = _grey_listing(product_id, listing_url, 9000, evidence_hash)
    purchase = order_test_purchase(
        observation["id"], ordered_at=ORDERED_AUG_19, purchase_price_cents=9000
    )
    capture_purchase_serial(purchase["id"], serial_number)
    purchase = confirm_unauthorized(
        purchase["id"], outcome_reason="Seller has no agreement on file"
    )
    return purchase, unit, observation


# --------------------------------------------------------------------------- #
# Priority 10 — cross-entity referential preconditions, continued
# --------------------------------------------------------------------------- #
def test_a_chargeback_on_a_purchase_that_is_not_yet_confirmed_is_refused():
    """The trace has to be confirmed before anybody is billed for it.

    PRD: "The referenced test purchase must be in status `CONFIRMED_UNAUTHORIZED`, else
    `ERR_TEST_PURCHASE_NOT_CONFIRMED`, and the `shipped_distributor_id` of the unit it
    traced must equal the chargeback's `distributor_id`, else
    `ERR_DIVERSION_NOT_ATTRIBUTED` — a distributor is only accountable for units its own
    shipping record names."

    Design: Corner/validations/chargeback_on_an_unconfirmed_test_purchase_rejected
    """
    policy = _published_policy()
    product = _headphones(policy["id"])
    distributor = _northwind()
    unit = create_serial_unit(
        product["id"], distributor["id"], serial_number="SN-0001", lot_code="LOT-A"
    )
    pin_clock(CLOCK_AUG_20)
    observation = _grey_listing(
        product["id"], "https://mkt.example/l/9", 9000, EVIDENCE_HASH_1
    )
    purchase = order_test_purchase(
        observation["id"], ordered_at=ORDERED_AUG_19, purchase_price_cents=9000
    )
    capture_purchase_serial(purchase["id"], "SN-0001")

    validate_error(
        api_client.assess_chargeback(
            chargeback_payload(
                distributor["id"],
                purchase["id"],
                current_distributor_version(distributor["id"]),
                diverted_units=4,
            ),
            BCM_HEADERS,
        ),
        ApiErrorId.ERR_TEST_PURCHASE_NOT_CONFIRMED.value,
    )

    assert read_test_purchase(purchase["id"])["status"] == "SERIAL_CAPTURED"
    assert read_serial_unit(unit["id"])["status"] == "SHIPPED_TO_DISTRIBUTOR"
    assert read_distributor(distributor["id"])["chargeback_balance_cents"] == 0


def test_a_chargeback_billed_to_a_distributor_that_never_shipped_the_unit_is_refused():
    """Accountability follows the shipping record, not the brand's preference.

    PRD: "The referenced test purchase must be in status `CONFIRMED_UNAUTHORIZED`, else
    `ERR_TEST_PURCHASE_NOT_CONFIRMED`, and the `shipped_distributor_id` of the unit it
    traced must equal the chargeback's `distributor_id`, else
    `ERR_DIVERSION_NOT_ATTRIBUTED` — a distributor is only accountable for units its own
    shipping record names."

    Design: Corner/validations/chargeback_against_a_distributor_that_never_shipped_the_unit_rejected
    """
    policy = _published_policy()
    product = _headphones(policy["id"])
    northwind = _northwind()
    southpaw = create_distributor(
        legal_name="Southpaw Supply Co", annual_chargeback_cap_cents=500000
    )
    pin_clock(CLOCK_AUG_20)
    purchase, unit, _observation = _confirmed_trace(
        product["id"], northwind["id"], "SN-0001", "https://mkt.example/l/9", EVIDENCE_HASH_1
    )

    validate_error(
        api_client.assess_chargeback(
            chargeback_payload(
                southpaw["id"],
                purchase["id"],
                current_distributor_version(southpaw["id"]),
                diverted_units=4,
            ),
            BCM_HEADERS,
        ),
        ApiErrorId.ERR_DIVERSION_NOT_ATTRIBUTED.value,
    )

    assert read_serial_unit(unit["id"])["shipped_distributor_id"] == northwind["id"]
    billed = read_distributor(southpaw["id"])
    assert billed["chargeback_balance_cents"] == 0
    assert billed["diversion_score"] == 0


def test_a_serial_already_traced_cannot_ground_a_second_trace():
    """A unit in TRACED_UNAUTHORIZED has left the traceable custody states.

    PRD: "A serial that matches no registered unit is rejected with
    `ERR_SERIAL_NOT_REGISTERED`; a serial that resolves to a unit whose custody state is
    neither `SHIPPED_TO_DISTRIBUTOR` nor `SHIPPED_TO_RESELLER` is rejected with
    `ERR_SERIAL_NOT_TRACEABLE`, since a unit already traced or recalled cannot ground a
    fresh trace."

    Design: Corner/validations/recapturing_an_already_traced_serial_rejected
    """
    policy = _published_policy()
    product = _headphones(policy["id"])
    distributor = _northwind()
    pin_clock(CLOCK_AUG_20)
    _purchase, unit, _observation = _confirmed_trace(
        product["id"], distributor["id"], "SN-0001", "https://mkt.example/l/9", EVIDENCE_HASH_1
    )
    assert read_serial_unit(unit["id"])["status"] == "TRACED_UNAUTHORIZED"

    second_observation = _grey_listing(
        product["id"], "https://mkt.example/l/10", 9500, EVIDENCE_HASH_3
    )
    second_purchase = order_test_purchase(
        second_observation["id"], ordered_at=ORDERED_AUG_19, purchase_price_cents=9500
    )

    validate_error(
        api_client.capture_serial(
            second_purchase["id"], serial_capture_payload("SN-0001"), ANALYST_HEADERS
        ),
        ApiErrorId.ERR_SERIAL_NOT_TRACEABLE.value,
    )

    assert read_serial_unit(unit["id"])["status"] == "TRACED_UNAUTHORIZED"
    assert read_test_purchase(second_purchase["id"])["status"] == "ORDERED"


def test_a_unit_may_not_be_registered_against_a_non_serialized_product():
    """Serialization has to be enabled on the product before units exist.

    PRD: "The product must have `serialization_enabled` set to true, else
    `ERR_PRODUCT_NOT_SERIALIZED`."

    Design: Corner/validations/serial_unit_for_a_non_serialized_product_rejected
    """
    policy = _published_policy()
    unserialized = create_product(
        policy["id"],
        sku="SKU-NOSER-1",
        name="Accessory Cable",
        msrp_cents=5000,
        standard_map_floor_cents=4000,
        serialization_enabled=False,
    )
    distributor = _northwind()

    validate_error(
        api_client.create_serial_unit(
            {
                "serial_number": "SN-0100",
                "product_id": unserialized["id"],
                "lot_code": "LOT-B",
                "shipped_distributor_id": distributor["id"],
            },
            BCM_HEADERS,
        ),
        ApiErrorId.ERR_PRODUCT_NOT_SERIALIZED.value,
    )

    _rows, meta = validate_paginated(api_client.list_serial_units(BCM_HEADERS))
    assert meta["total_count"] == 0


def test_the_attribution_check_outranks_the_annual_chargeback_ceiling():
    """A misattributed chargeback is reported even when it also breaches the cap.

    PRD: "Because this check runs last, a request that both breaches the cap and fails
    any earlier check reports the earlier failure."

    Design: Corner/validations/referential_check_precedes_fiscal_cap_rejected
    """
    policy = _published_policy()
    product = _headphones(policy["id"])
    northwind = _northwind()
    tightwad = create_distributor(
        legal_name="Tightwad Ltd", annual_chargeback_cap_cents=5000
    )
    pin_clock(CLOCK_AUG_20)
    purchase, _unit, _observation = _confirmed_trace(
        product["id"], northwind["id"], "SN-0001", "https://mkt.example/l/9", EVIDENCE_HASH_1
    )

    validate_error(
        api_client.assess_chargeback(
            chargeback_payload(
                tightwad["id"],
                purchase["id"],
                current_distributor_version(tightwad["id"]),
                diverted_units=4,
            ),
            BCM_HEADERS,
        ),
        ApiErrorId.ERR_DIVERSION_NOT_ATTRIBUTED.value,
    )

    assert read_distributor(tightwad["id"])["chargeback_balance_cents"] == 0


# --------------------------------------------------------------------------- #
# Priority 11 — window and clock checks
# --------------------------------------------------------------------------- #
def test_a_listing_observed_more_than_thirty_days_ago_is_refused():
    """A screenshot from outside the trailing month cannot enter the evidence chain.

    PRD: "`observed_at` must be at or before the current logical clock and at or after
    the clock minus 30 days; anything outside that trailing month is rejected with
    `ERR_OBSERVATION_STALE`, because a screenshot older than a month is not a usable
    basis for a notice."

    Design: Corner/validations/observation_older_than_thirty_days_rejected
    """
    policy = _published_policy()
    product = _headphones(policy["id"])
    pin_clock(CLOCK_AUG_20)

    validate_error(
        api_client.create_observation(
            observation_payload(
                product["id"],
                channel="MARKETPLACE",
                seller_display_name="GreyBox Deals",
                listing_url="https://mkt.example/l/old",
                listed_price_cents=14000,
                observed_at=OBSERVED_JUL_01,
                evidence_hash=EVIDENCE_HASH_1,
            ),
            ANALYST_HEADERS,
        ),
        ApiErrorId.ERR_OBSERVATION_STALE.value,
    )

    _rows, meta = validate_paginated(api_client.list_observations(ANALYST_HEADERS))
    assert meta["total_count"] == 0


def test_a_listing_observed_exactly_thirty_days_ago_is_captured():
    """The trailing window is inclusive at the clock minus thirty days.

    PRD: "`observed_at` must be at or before the current logical clock and at or after
    the clock minus 30 days; anything outside that trailing month is rejected with
    `ERR_OBSERVATION_STALE`, because a screenshot older than a month is not a usable
    basis for a notice."

    Design: Corner/validations/observation_exactly_thirty_days_old_is_accepted
    """
    policy = _published_policy()
    product = _headphones(policy["id"])
    pin_clock(CLOCK_AUG_31)

    observation = validate_success(
        api_client.create_observation(
            observation_payload(
                product["id"],
                channel="MARKETPLACE",
                seller_display_name="GreyBox Deals",
                listing_url="https://mkt.example/l/edge",
                listed_price_cents=14000,
                observed_at=CLOCK_AUG_01,
                evidence_hash=EVIDENCE_HASH_1,
            ),
            ANALYST_HEADERS,
        ),
        expected_status=201,
    )

    assert observation["evaluation_status"] == "CAPTURED"
    assert_same_instant(observation["observed_at"], CLOCK_AUG_01, "observed_at")


def test_an_exception_window_intersecting_a_live_window_is_refused():
    """An approved window blocks a later request that overlaps it on a shared channel.

    PRD: "A request is rejected with `ERR_EXCEPTION_WINDOW_OVERLAP` when another
    exception on the same product, in status `REQUESTED` or `APPROVED`, has a window
    that intersects the requested one under half-open interval semantics and has a
    channel scope that intersects the requested scope."

    Design: Corner/validations/overlapping_exception_window_rejected
    """
    policy = _published_policy()
    product = _headphones(policy["id"])
    pin_clock(CLOCK_AUG_20)
    first = validate_success(
        api_client.create_exception(
            exception_payload(
                product["id"],
                exception_type="PROMOTIONAL_EVENT",
                starts_at="2026-08-10T00:00:00Z",
                ends_at="2026-08-25T00:00:00Z",
                channel_scope="ALL",
                requested_override_floor_cents=13000,
                dealer_input_source="BRAND_MARKETING_PLAN",
            ),
            BCM_HEADERS,
        ),
        expected_status=201,
    )
    approved = approve_exception(
        first["id"], decision_reason="Promotional calendar cleared by legal"
    )
    assert approved["status"] == "APPROVED"

    validate_error(
        api_client.create_exception(
            exception_payload(
                product["id"],
                exception_type="PROMOTIONAL_EVENT",
                starts_at="2026-08-19T00:00:00Z",
                ends_at="2026-08-30T00:00:00Z",
                channel_scope="MARKETPLACE",
                requested_override_floor_cents=13500,
                dealer_input_source="BRAND_MARKETING_PLAN",
            ),
            BCM_HEADERS,
        ),
        ApiErrorId.ERR_EXCEPTION_WINDOW_OVERLAP.value,
    )

    assert read_product(product["id"])["open_exception_count"] == 1
    _rows, meta = validate_paginated(
        api_client.list_exceptions(BCM_HEADERS, params={"product_id": product["id"]})
    )
    assert meta["total_count"] == 1


def test_an_exception_window_of_exactly_one_hundred_eighty_days_is_requested():
    """The span limit is inclusive at one hundred and eighty days.

    PRD: "A `BrandChannelManager` may request an exception naming the `product_id` it
    covers and an `exception_type` of `CLEARANCE`, `BUNDLE` or `PROMOTIONAL_EVENT`,
    together with a window: `starts_at` is inclusive and `ends_at` is exclusive,
    `ends_at` must be strictly after `starts_at`, and the window may not span more than
    180 days."

    Design: Corner/validations/exception_window_of_exactly_one_hundred_eighty_days_is_accepted
    """
    policy = _published_policy()
    product = _headphones(policy["id"])

    exception = validate_success(
        api_client.create_exception(
            exception_payload(
                product["id"],
                exception_type="PROMOTIONAL_EVENT",
                starts_at=WINDOW_180_STARTS,
                ends_at=WINDOW_180_ENDS,
                channel_scope="ALL",
                requested_override_floor_cents=13000,
                dealer_input_source="BRAND_MARKETING_PLAN",
            ),
            BCM_HEADERS,
        ),
        expected_status=201,
    )

    assert exception["status"] == "REQUESTED"
    assert_same_instant(exception["starts_at"], WINDOW_180_STARTS, "starts_at")
    assert_same_instant(exception["ends_at"], WINDOW_180_ENDS, "ends_at")
    assert read_product(product["id"])["open_exception_count"] == 0


def test_a_retroactive_exception_reaching_back_past_thirty_days_is_refused():
    """Retroactivity is allowed, but not arbitrarily far back.

    PRD: "A retroactive exception is allowed — reaching back is precisely how a
    promotional event that legal cleared late gets applied to listings already captured
    — but it may not reach back arbitrarily far: a retroactive exception whose
    `starts_at` is earlier than the clock minus 30 days is rejected with
    `ERR_RETROACTIVE_WINDOW_TOO_OLD`."

    Design: Corner/validations/retroactive_exception_starting_before_the_thirty_day_floor_rejected
    """
    policy = _published_policy()
    product = _headphones(policy["id"])
    pin_clock(CLOCK_AUG_20)

    validate_error(
        api_client.create_exception(
            exception_payload(
                product["id"],
                exception_type="PROMOTIONAL_EVENT",
                starts_at=OBSERVED_JUL_01,
                ends_at="2026-08-25T00:00:00Z",
                channel_scope="ALL",
                requested_override_floor_cents=13000,
                dealer_input_source="BRAND_MARKETING_PLAN",
            ),
            BCM_HEADERS,
        ),
        ApiErrorId.ERR_RETROACTIVE_WINDOW_TOO_OLD.value,
    )

    _rows, meta = validate_paginated(api_client.list_exceptions(BCM_HEADERS))
    assert meta["total_count"] == 0


def test_a_cure_submitted_after_the_deadline_is_refused():
    """One day past the deadline the reseller's own remedy has closed.

    PRD: "Cure requires the violation to be `NOTICED` and requires the current clock to
    be at or before `cure_deadline_at`, else `ERR_CURE_WINDOW_EXPIRED`."

    Design: Corner/validations/cure_submitted_after_the_deadline_rejected
    """
    world = _warned_acme()
    assert_same_instant(
        read_violation(world["violation"]["id"])["cure_deadline_at"],
        CURE_DEADLINE,
        "cure_deadline_at",
    )
    pin_clock(CLOCK_AUG_31)

    validate_error(
        api_client.submit_cure(
            world["violation"]["id"],
            cure_submission_payload(
                cure_evidence_url="https://acme.example/proof/late",
                corrected_price_cents=15000,
                evidence_hash=EVIDENCE_HASH_3,
            ),
            make_reseller_headers(world["reseller"]["id"]),
        ),
        ApiErrorId.ERR_CURE_WINDOW_EXPIRED.value,
    )

    assert read_violation(world["violation"]["id"])["status"] == "NOTICED"


def test_a_cure_submitted_exactly_on_the_deadline_is_accepted():
    """The deadline is inclusive, and curing settles the notice without refunding points.

    PRD: "It moves the violation `NOTICED → CURED` with `resolution_reason` set to
    `CURE_ACCEPTED` and its `version` advanced, and it moves the latest non-rescinded
    notice for that violation to `SATISFIED` with `closed_reason` recorded as
    `VIOLATION_CURED` and that notice's `version` advanced. What curing does **not** do
    is refund points: the `assessed_points` stay in the reseller's
    `violation_points_total`, because a cured violation still counts toward the ladder."

    Design: Corner/validations/cure_submitted_exactly_at_the_deadline_is_accepted
    """
    world = _warned_acme()
    pin_clock(CLOCK_AUG_30)

    validate_success(
        api_client.submit_cure(
            world["violation"]["id"],
            cure_submission_payload(
                cure_evidence_url="https://acme.example/proof/ontime",
                corrected_price_cents=15000,
                evidence_hash=EVIDENCE_HASH_3,
            ),
            make_reseller_headers(world["reseller"]["id"]),
        )
    )

    violation = read_violation(world["violation"]["id"])
    assert violation["status"] == "CURED"
    assert violation["resolution_reason"] == "CURE_ACCEPTED"
    assert violation["assessed_points"] == violation_points(
        STANDARD_FLOOR, 14000, "MARKETPLACE", 0
    ) == 3
    assert read_reseller(world["reseller"]["id"])["violation_points_total"] == 3
    assert read_notice(world["notice"]["id"])["status"] == "SATISFIED"


def test_a_stale_observation_outranks_the_channel_permission_check():
    """The trailing-month check is settled before channel permissions are consulted.

    PRD: "When a single request violates several rules, exactly one error is returned,
    and which one is fully determined."

    Design: Corner/validations/temporal_check_precedes_domain_constraint_rejected
    """
    world = _authorized_channel()
    assert world["agreement"]["permitted_channels"] == ["MARKETPLACE", "OWN_WEBSITE"]
    pin_clock(CLOCK_AUG_20)

    validate_error(
        api_client.create_observation(
            observation_payload(
                world["product"]["id"],
                channel="RETAILER_SITE",
                seller_display_name="Acme Store",
                listing_url="https://retail.example/l/stale",
                listed_price_cents=12000,
                observed_at=OBSERVED_JUL_01,
                evidence_hash=EVIDENCE_HASH_1,
                matched_reseller_id=world["reseller"]["id"],
            ),
            ANALYST_HEADERS,
        ),
        ApiErrorId.ERR_OBSERVATION_STALE.value,
    )

    _rows, meta = validate_paginated(api_client.list_observations(ANALYST_HEADERS))
    assert meta["total_count"] == 0
