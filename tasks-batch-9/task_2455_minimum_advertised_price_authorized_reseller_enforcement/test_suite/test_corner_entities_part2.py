"""Required inputs, declared defaults, derived fields and body-reference checks.

Every row type has fields the client must supply, fields the client may leave to
a declared default, and fields the server owns outright; this module pins each
of the three groups and the refusals that guard them.
"""
from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ANALYST_2_HEADERS,
    ANALYST_HEADERS,
    BCM_HEADERS,
    COUNSEL_HEADERS,
    api_client,
)
from test_helpers.assertions import (
    assert_same_instant,
    deviation_cents,
    deviation_pct,
    effective_advertised_price,
    override_floor_lower_bound,
    score_delta,
    standing_for_score,
)
from test_helpers.constants import EVIDENCE_HASH_1, EVIDENCE_HASH_3
from test_helpers.factories import (
    agreement_payload,
    chargeback_payload,
    exception_decision_payload,
    exception_payload,
    notice_payload,
    observation_payload,
    pricing_policy_payload,
    product_payload,
    serial_unit_payload,
)
from test_helpers.fixtures import (
    capture_observation,
    capture_purchase_serial,
    confirm_unauthorized,
    create_active_agreement,
    create_distributor,
    create_product,
    create_published_policy,
    create_reseller,
    create_serial_unit,
    current_reseller_version,
    order_test_purchase,
    pin_clock,
    read_compliance_summary,
    read_distributor,
    read_exception,
    read_observation,
    read_product,
    read_reseller,
    read_violation,
)

CLOCK_AUG_01 = "2026-08-01T00:00:00Z"
CLOCK_AUG_20 = "2026-08-20T00:00:00Z"
OBSERVED_AUG_18 = "2026-08-18T00:00:00Z"
ORDERED_AUG_19 = "2026-08-19T00:00:00Z"
TERM_ENDS_AT = "2027-06-30T00:00:00Z"

UNKNOWN_POLICY_ID = "00000000-0000-4000-8000-0000000000aa"
UNKNOWN_DISTRIBUTOR_ID = "00000000-0000-4000-8000-0000000000bb"
UNKNOWN_RESELLER_ID = "00000000-0000-4000-8000-0000000000cc"
SHORT_EVIDENCE_HASH = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcde"


# --------------------------------------------------------------------------- #
# Shared setup spines
# --------------------------------------------------------------------------- #
def _published_policy(**overrides):
    """The logical clock pinned and one PUBLISHED policy carrying the defaults."""
    pin_clock(CLOCK_AUG_01)
    return create_published_policy(CLOCK_AUG_01, **overrides)


def _policy_and_product(**product_overrides):
    """A PUBLISHED policy plus one product at msrp 20000 / floor 15000."""
    policy = _published_policy(policy_code="MAP-2026-A")
    overrides = {
        "sku": "SKU-AUDIO-1",
        "name": "Studio Headphones",
        "msrp_cents": 20000,
        "standard_map_floor_cents": 15000,
    }
    overrides.update(product_overrides)
    product = create_product(policy["id"], **overrides)
    return policy, product


def _authorized_reseller(policy_id):
    """One marketplace reseller walked to an ACTIVE agreement."""
    reseller = create_reseller(
        legal_name="Acme Retail LLC",
        contact_email="ops@acme.example",
        primary_channel="MARKETPLACE",
    )
    agreement = create_active_agreement(
        reseller["id"],
        policy_id,
        permitted_channels=["MARKETPLACE"],
        quality_obligations=[],
        term_ends_at=TERM_ENDS_AT,
    )
    return reseller, agreement


def _matched_breach(product_id, reseller_id):
    """A 14000 marketplace listing pinned on the reseller, then evaluated."""
    observation = capture_observation(
        product_id,
        channel="MARKETPLACE",
        seller_display_name="Acme Store",
        listing_url="https://mkt.example/l/1",
        listed_price_cents=14000,
        observed_at=OBSERVED_AUG_18,
        evidence_hash=EVIDENCE_HASH_1,
        matched_reseller_id=reseller_id,
    )
    evaluation = validate_success(
        api_client.evaluate_observation(observation["id"], ANALYST_HEADERS)
    )
    return observation, evaluation


def _confirmed_trace(product_id, distributor_id, serial_number="SN-0001"):
    """A registered unit traced through a test purchase to an unauthorized seller."""
    unit = create_serial_unit(
        product_id, distributor_id, serial_number=serial_number, lot_code="LOT-A"
    )
    pin_clock(CLOCK_AUG_20)
    observation = capture_observation(
        product_id,
        channel="MARKETPLACE",
        seller_display_name="GreyBox Deals",
        listing_url="https://mkt.example/l/9",
        listed_price_cents=9000,
        observed_at=OBSERVED_AUG_18,
        evidence_hash=EVIDENCE_HASH_1,
    )
    purchase = order_test_purchase(
        observation["id"], ordered_at=ORDERED_AUG_19, purchase_price_cents=9000
    )
    capture_purchase_serial(purchase["id"], serial_number)
    purchase = confirm_unauthorized(purchase["id"], outcome_reason="Unauthorized storefront")
    return purchase, unit, observation


# --------------------------------------------------------------------------- #
# Required inputs
# --------------------------------------------------------------------------- #
def test_a_product_without_a_map_floor_is_refused_and_never_stored():
    """standard_map_floor_cents has no default, so omitting it is malformed.

    PRD: "**Request shape.** Required body fields present, types correct, enum members drawn from the declared sets, numeric ranges honoured, `evidence_hash` exactly 64 lowercase hexadecimal characters, `permitted_channels` members distinct, `bundle_components` well formed whenever `is_bundle` is true, a suspension window no longer than 90 days, and `diverted_units` at least 1 — else `ERR_VALIDATION` (400)." "A `BrandChannelManager` registers each branded item with a `sku` of 1 to 40 characters that must be unique across the catalogue — a duplicate is rejected with `ERR_DUPLICATE_SKU` — plus a display `name`, an `msrp_cents` figure that must be strictly greater than zero, and a `standard_map_floor_cents` figure that must be strictly greater than zero and no greater than `msrp_cents`."

    Design: Corner/entities/create_product_without_standard_map_floor_is_rejected
    """
    policy = _published_policy(policy_code="MAP-2026-A")
    payload = product_payload(
        policy["id"], sku="SKU-AUDIO-1", name="Studio Headphones", msrp_cents=20000
    )
    payload.pop("standard_map_floor_cents")

    validate_error(api_client.create_product(payload, BCM_HEADERS), "ERR_VALIDATION")

    _rows, meta = validate_paginated(
        api_client.list_products(BCM_HEADERS, params={"sku": "SKU-AUDIO-1"})
    )
    assert meta["total_count"] == 0


def test_an_observation_without_an_evidence_hash_is_refused_and_never_stored():
    """No evidence-less observation can exist: the digest is a required input.

    PRD: "**Request shape.** Required body fields present, types correct, enum members drawn from the declared sets, numeric ranges honoured, `evidence_hash` exactly 64 lowercase hexadecimal characters, `permitted_channels` members distinct, `bundle_components` well formed whenever `is_bundle` is true, a suspension window no longer than 90 days, and `diverted_units` at least 1 — else `ERR_VALIDATION` (400)." "Each captured listing names the monitored SKU by `product_id`, the `channel` on which it was seen (one of `MARKETPLACE`, `RETAILER_SITE`, `OWN_WEBSITE` or `PHYSICAL_RETAIL`), the storefront's `seller_display_name`, the evidence `listing_url`, the `listed_price_cents` as displayed (which must be at least 0), the `observed_at` instant, and an `evidence_hash` that must be exactly 64 lowercase hexadecimal characters — the SHA-256 digest of the captured screenshot."

    Design: Corner/entities/create_price_observation_without_evidence_hash_is_rejected
    """
    _policy, product = _policy_and_product()
    pin_clock(CLOCK_AUG_20)
    payload = observation_payload(
        product["id"],
        channel="MARKETPLACE",
        seller_display_name="Acme Store",
        listing_url="https://mkt.example/l/1",
        listed_price_cents=14000,
        observed_at=OBSERVED_AUG_18,
    )
    payload.pop("evidence_hash")

    validate_error(api_client.create_observation(payload, ANALYST_HEADERS), "ERR_VALIDATION")

    _rows, meta = validate_paginated(
        api_client.list_observations(BCM_HEADERS, params={"product_id": product["id"]})
    )
    assert meta["total_count"] == 0


def test_an_agreement_without_an_expiry_anchor_is_refused():
    """term_ends_at is required, and the failed draft leaves the reseller APPLIED.

    PRD: "**Request shape.** Required body fields present, types correct, enum members drawn from the declared sets, numeric ranges honoured, `evidence_hash` exactly 64 lowercase hexadecimal characters, `permitted_channels` members distinct, `bundle_components` well formed whenever `is_bundle` is true, a suspension window no longer than 90 days, and `diverted_units` at least 1 — else `ERR_VALIDATION` (400)." "The payload also supplies `term_ends_at`, the expiry instant the sweep later enforces, and may declare `price_terms_included`, which defaults to false and whose only permitted value is false per §2.7."

    Design: Corner/entities/create_reseller_agreement_without_term_ends_at_is_rejected
    """
    policy = _published_policy(policy_code="MAP-2026-A")
    reseller = create_reseller(
        legal_name="Acme Retail LLC",
        contact_email="ops@acme.example",
        primary_channel="MARKETPLACE",
    )
    payload = agreement_payload(
        reseller["id"], policy["id"], permitted_channels=["MARKETPLACE"], quality_obligations=[]
    )
    payload.pop("term_ends_at")

    validate_error(api_client.create_agreement(payload, BCM_HEADERS), "ERR_VALIDATION")

    assert read_reseller(reseller["id"])["authorization_status"] == "APPLIED"


def test_a_notice_that_omits_the_expected_reseller_version_is_malformed():
    """The concurrency token is a required input, so omitting it never reaches OCC.

    PRD: "Requests to any other endpoint that happen to carry one are not rejected for it, and requests to these two that omit it are rejected as malformed with `ERR_VALIDATION` (HTTP 400)."

    Design: Corner/entities/create_enforcement_notice_without_expected_reseller_version_is_rejected
    """
    policy, product = _policy_and_product()
    reseller, _agreement = _authorized_reseller(policy["id"])
    pin_clock(CLOCK_AUG_20)
    _observation, evaluation = _matched_breach(product["id"], reseller["id"])
    payload = notice_payload(reseller["id"], evaluation["violation_id"], 1)
    payload.pop("expected_reseller_version")

    validate_error(api_client.issue_notice(payload, BCM_HEADERS), "ERR_VALIDATION")

    assert read_violation(evaluation["violation_id"])["status"] == "DETECTED"
    assert read_reseller(reseller["id"])["violation_points_total"] == 0


# --------------------------------------------------------------------------- #
# Declared defaults
# --------------------------------------------------------------------------- #
def test_a_policy_drafted_with_only_a_code_gets_the_declared_ladder_defaults():
    """Cure window 10, thresholds 6 and 12, cooling-off 14 all arrive unasked.

    PRD: "`cure_window_days` is the number of days a reseller has to cure a noticed violation before it escalates; it must be between 1 and 60 inclusive and defaults to 10." "`suspension_points_threshold` is the cumulative points figure at or above which the ladder's points-based rung becomes suspension; it must be at least 1 and defaults to 6." "`termination_points_threshold` is the cumulative points figure at or above which the points-based rung becomes termination; it defaults to 12 and must be strictly greater than `suspension_points_threshold`." "Finally, `suspension_cooling_off_days` is the mandatory gap between the end of one suspension window and the start of the next; it must be between 0 and 180 inclusive and defaults to 14."

    Design: Corner/entities/policy_optional_thresholds_fall_back_to_declared_defaults
    """
    pin_clock(CLOCK_AUG_01)

    policy = validate_success(
        api_client.create_pricing_policy(
            pricing_policy_payload(policy_code="MAP-2026-D"), BCM_HEADERS
        ),
        expected_status=201,
    )

    assert policy["cure_window_days"] == 10
    assert policy["suspension_points_threshold"] == 6
    assert policy["termination_points_threshold"] == 12
    assert policy["suspension_cooling_off_days"] == 14


def test_a_policy_drafted_with_only_a_code_gets_the_declared_price_defaults():
    """Shipping is out, an auto coupon is in, a typed code is out, cap 0.40.

    PRD: "`shipping_counts_as_advertised` decides whether a displayed shipping charge is added to the item price; it defaults to false, reflecting the common position that shipping is not part of the advertised price." "`auto_coupon_counts_as_advertised` decides whether a coupon that the marketplace applies automatically on the listing page is treated as reducing the advertised price; it defaults to true, because a shopper sees that price without doing anything." "`promo_code_counts_as_advertised` decides whether a discount reachable only by typing a code is treated as reducing the advertised price; it defaults to false, because a code the shopper must go and find is not what the page advertises." "Alongside them, `max_discount_attribution_pct` caps how much of a listing's gross price any single discount may be credited with reducing for MAP purposes; it is a two-decimal fraction between 0.00 and 1.00 inclusive and defaults to 0.40, meaning at most forty percent of the gross price." "`non_negotiation_ack_required` defaults to true and decides whether a reseller must acknowledge the policy's unilateral, non-negotiable character before its agreement can be activated."

    Design: Corner/entities/policy_optional_thresholds_fall_back_to_declared_defaults
    """
    pin_clock(CLOCK_AUG_01)

    policy = validate_success(
        api_client.create_pricing_policy(
            pricing_policy_payload(policy_code="MAP-2026-D"), BCM_HEADERS
        ),
        expected_status=201,
    )

    assert policy["shipping_counts_as_advertised"] is False
    assert policy["auto_coupon_counts_as_advertised"] is True
    assert policy["promo_code_counts_as_advertised"] is False
    assert policy["max_discount_attribution_pct"] == 0.40
    assert policy["non_negotiation_ack_required"] is True


def test_a_product_registered_without_lifecycle_hints_gets_the_declared_defaults():
    """ACTIVE, a twenty-percent clearance cut and serialization on, unasked.

    PRD: "`lifecycle_status` is the commercial stage and defaults to `ACTIVE`, with `CLEARANCE` and `DISCONTINUED` as its other values; it is the gate on which exception types may be approved." "`clearance_discount_pct` is the fraction subtracted from the standard floor when a clearance exception is approved; it is a two-decimal fraction between 0.00 and 0.60 inclusive and defaults to 0.20, meaning a twenty-percent cut." "`serialization_enabled` defaults to true and declares whether units of this item carry traceable serial numbers."

    Design: Corner/entities/product_optional_lifecycle_and_clearance_depth_fall_back_to_defaults
    """
    policy = _published_policy(policy_code="MAP-2026-A")

    product = validate_success(
        api_client.create_product(
            product_payload(
                policy["id"],
                sku="SKU-AUDIO-1",
                name="Studio Headphones",
                msrp_cents=20000,
                standard_map_floor_cents=15000,
            ),
            BCM_HEADERS,
        ),
        expected_status=201,
    )

    assert product["lifecycle_status"] == "ACTIVE"
    assert product["clearance_discount_pct"] == 0.20
    assert product["serialization_enabled"] is True


def test_an_observation_without_modifiers_prices_at_the_gross_listed_price():
    """All three modifiers default to 0, so nothing qualifies as a discount.

    PRD: "Three optional money fields all default to 0 and must each be at least 0: `shipping_cents` for the displayed shipping charge, `auto_coupon_cents` for a coupon the page applies automatically, and `promo_code_cents` for a discount reachable only by typing a code." "When no discount qualifies, the candidate is zero and the effective advertised price equals the gross price." "Because the allocation reads only immutable fields of the observation itself, the server is free to compute `allocated_component_price_cents` eagerly at capture time as well; the value stored after evaluation is in either case exactly the figure this rule produces, and it remains null for any listing that is not a bundle."

    Design: Corner/entities/observation_money_modifiers_default_to_zero_and_bundle_flag_to_false
    """
    _policy, product = _policy_and_product()
    pin_clock(CLOCK_AUG_20)
    observation = capture_observation(
        product["id"],
        channel="RETAILER_SITE",
        seller_display_name="Acme Store",
        listing_url="https://rs.example/l/1",
        listed_price_cents=14000,
        observed_at=OBSERVED_AUG_18,
        evidence_hash=EVIDENCE_HASH_1,
    )

    evaluation = validate_success(
        api_client.evaluate_observation(observation["id"], ANALYST_HEADERS)
    )

    assert evaluation["effective_advertised_price_cents"] == effective_advertised_price(14000) == 14000
    stored = read_observation(observation["id"])
    assert stored["shipping_cents"] == 0
    assert stored["auto_coupon_cents"] == 0
    assert stored["promo_code_cents"] == 0
    assert stored["is_bundle"] is False
    assert stored["allocated_component_price_cents"] is None


# --------------------------------------------------------------------------- #
# Derived fields
# --------------------------------------------------------------------------- #
def test_only_an_approved_exception_raises_a_products_open_exception_count():
    """A REQUESTED row counts nothing; approval counts one; a rejection adds none.

    PRD: "A product's `open_exception_count` equals the count of that product's pricing exceptions in status `APPROVED`." "Exceptions in `REQUESTED`, `REJECTED`, `EXPIRED` or `VOIDED` are excluded, and the count is recomputed on every approval, expiry and voiding." "It increases the product's `open_exception_count` by one and advances the product's `version`."

    Design: Corner/entities/product_open_exception_count_tracks_approved_exceptions_only
    """
    _policy, product = _policy_and_product()
    first = validate_success(
        api_client.create_exception(
            exception_payload(
                product["id"],
                exception_type="PROMOTIONAL_EVENT",
                starts_at="2026-08-05T00:00:00Z",
                ends_at="2026-08-15T00:00:00Z",
                channel_scope="ALL",
                requested_override_floor_cents=13000,
                dealer_input_source="BRAND_MARKETING_PLAN",
            ),
            BCM_HEADERS,
        ),
        expected_status=201,
    )
    second = validate_success(
        api_client.create_exception(
            exception_payload(
                product["id"],
                exception_type="PROMOTIONAL_EVENT",
                starts_at="2026-08-20T00:00:00Z",
                ends_at="2026-08-25T00:00:00Z",
                channel_scope="ALL",
                requested_override_floor_cents=12500,
                dealer_input_source="BRAND_MARKETING_PLAN",
            ),
            BCM_HEADERS,
        ),
        expected_status=201,
    )
    assert read_product(product["id"])["open_exception_count"] == 0

    validate_success(
        api_client.decide_exception(
            first["id"],
            exception_decision_payload("APPROVE", decision_reason="Marketing plan approved"),
            COUNSEL_HEADERS,
        )
    )
    assert read_product(product["id"])["open_exception_count"] == 1

    validate_success(
        api_client.decide_exception(
            second["id"],
            exception_decision_payload(
                "REJECT", decision_reason="Overlaps a competing campaign"
            ),
            COUNSEL_HEADERS,
        )
    )
    assert read_product(product["id"])["open_exception_count"] == 1


def test_approval_installs_the_requested_floor_while_rejection_installs_nothing():
    """The approved row snapshots its band-checked floor; the rejected row stays null.

    PRD: "For a `BUNDLE` or `PROMOTIONAL_EVENT` exception the installed floor is exactly the `requested_override_floor_cents` supplied on the request, but it must sit inside a permitted band: it must be strictly less than the product's `standard_map_floor_cents` — an "exception" that raises the floor is not an exception — and it must be at least the product's `standard_map_floor_cents` multiplied by 0.50 and truncated downward to whole cents, so no exception may cut the floor by more than half." "A `decision` of `REJECT` moves it `REQUESTED → REJECTED`, recording `decision_reason` and stamping `approved_by_user_id` with the deciding counsel's `X-User-ID`, and advances the exception's `version`."

    Design: Corner/entities/product_open_exception_count_tracks_approved_exceptions_only
    """
    _policy, product = _policy_and_product()
    assert 13000 < 15000
    assert 13000 >= override_floor_lower_bound(15000) == 7500

    first = validate_success(
        api_client.create_exception(
            exception_payload(
                product["id"],
                exception_type="PROMOTIONAL_EVENT",
                starts_at="2026-08-05T00:00:00Z",
                ends_at="2026-08-15T00:00:00Z",
                channel_scope="ALL",
                requested_override_floor_cents=13000,
                dealer_input_source="BRAND_MARKETING_PLAN",
            ),
            BCM_HEADERS,
        ),
        expected_status=201,
    )
    second = validate_success(
        api_client.create_exception(
            exception_payload(
                product["id"],
                exception_type="PROMOTIONAL_EVENT",
                starts_at="2026-08-20T00:00:00Z",
                ends_at="2026-08-25T00:00:00Z",
                channel_scope="ALL",
                requested_override_floor_cents=12500,
                dealer_input_source="BRAND_MARKETING_PLAN",
            ),
            BCM_HEADERS,
        ),
        expected_status=201,
    )

    validate_success(
        api_client.decide_exception(
            first["id"],
            exception_decision_payload("APPROVE", decision_reason="Marketing plan approved"),
            COUNSEL_HEADERS,
        )
    )
    validate_success(
        api_client.decide_exception(
            second["id"],
            exception_decision_payload(
                "REJECT", decision_reason="Overlaps a competing campaign"
            ),
            COUNSEL_HEADERS,
        )
    )

    assert read_exception(first["id"])["override_floor_cents"] == 13000
    assert read_exception(second["id"])["override_floor_cents"] is None


def test_a_resellers_points_ledger_equals_the_summed_points_the_summary_reports():
    """The stored total and the recomputed sum agree over one contributing row.

    PRD: "A reseller's `violation_points_total` equals the sum of `assessed_points` over that reseller's violations whose `assessed_points` is not null and whose `status` is one of `NOTICED`, `DISPUTED`, `CURED`, `ESCALATED` or `CLOSED_MOOT`." "It reports `reseller_id`, the stored `violation_points_total`, the `contributing_violation_count` of violations that qualify under the ledger definition of §2.11, the `summed_assessed_points` obtained by adding up those violations' `assessed_points` — which must equal the stored total, since that is the whole point of the read — the `highest_issued_rung` served so far (reported as the empty-history case when no non-rescinded notice exists), the `next_rung` the ladder would install on the next notice, and the two gaps `points_to_suspension` and `points_to_termination`, each being the reseller's own governing thresholds minus the current total, floored at zero when the threshold has already been passed."

    Design: Corner/entities/reseller_violation_points_total_equals_summed_assessed_points
    """
    policy, product = _policy_and_product()
    reseller, _agreement = _authorized_reseller(policy["id"])
    pin_clock(CLOCK_AUG_20)
    _observation, evaluation = _matched_breach(product["id"], reseller["id"])
    validate_success(
        api_client.issue_notice(
            notice_payload(
                reseller["id"],
                evaluation["violation_id"],
                current_reseller_version(reseller["id"]),
            ),
            BCM_HEADERS,
        ),
        expected_status=201,
    )

    summary = read_compliance_summary(reseller["id"], params={"as_of": CLOCK_AUG_20})

    assert summary["violation_points_total"] == 3
    assert summary["summed_assessed_points"] == 3
    assert summary["contributing_violation_count"] == 1
    assert summary["highest_issued_rung"] == "WARNING"
    assert read_reseller(reseller["id"])["violation_points_total"] == 3


def test_a_four_unit_chargeback_lands_exactly_on_the_inclusive_probation_edge():
    """A score of exactly 10.0 is at the lower bound, so standing is PROBATION.

    PRD: "Only after both figures are fixed is the distributor's state moved, and in this order: `amount_cents` is added to `chargeback_balance_cents`, then `score_delta_applied` is added to the pre-event score to give the new `diversion_score`, then `standing` is re-derived from that new score — `GOOD` when it is strictly below 10.0, `PROBATION` when it is at or above 10.0 but strictly below 25.0, and `SUSPENDED` when it is at or above 25.0." "Whenever that re-derivation moves a distributor into `PROBATION`, `probation_entered_at` is stamped with the current logical clock; while a distributor is `GOOD`, the field is null."

    Design: Corner/entities/distributor_diversion_score_and_standing_derived_from_chargebacks
    """
    _policy, product = _policy_and_product()
    distributor = create_distributor(
        legal_name="Northwind Distribution", annual_chargeback_cap_cents=500000
    )
    purchase, _unit, _observation = _confirmed_trace(product["id"], distributor["id"])

    chargeback = validate_success(
        api_client.assess_chargeback(
            chargeback_payload(
                distributor["id"],
                purchase["id"],
                read_distributor(distributor["id"])["version"],
                diverted_units=4,
            ),
            BCM_HEADERS,
        ),
        expected_status=201,
    )

    assert chargeback["amount_cents"] == 10000
    stored = read_distributor(distributor["id"])
    assert stored["diversion_score"] == score_delta(4) == 10.0
    assert stored["standing"] == standing_for_score(10.0) == "PROBATION"
    assert stored["chargeback_balance_cents"] == 10000
    assert_same_instant(stored["probation_entered_at"], CLOCK_AUG_20, "probation_entered_at")


def test_evaluation_is_what_computes_the_deviation_against_the_standard_floor():
    """1000 cents under a 15000 floor is 0.0667 once rounded to four places.

    PRD: "`deviation_cents` itself is defined as the resolved floor minus the effective advertised price, floored at 0 so it is never negative, and `deviation_pct` is `deviation_cents` divided by the resolved floor, rounded half up to four decimal places." "If nothing qualifies, the floor is the product's `standard_map_floor_cents` and the floor source is `STANDARD`." "It stores the same computed fields plus a genuine `deviation_cents` and `deviation_pct`, and advances its own `version`."

    Design: Corner/entities/observation_deviation_fields_computed_at_evaluate_time
    """
    _policy, product = _policy_and_product()
    pin_clock(CLOCK_AUG_20)
    observation = capture_observation(
        product["id"],
        channel="MARKETPLACE",
        seller_display_name="GreyBox Deals",
        listing_url="https://mkt.example/l/1",
        listed_price_cents=14000,
        observed_at=OBSERVED_AUG_18,
        evidence_hash=EVIDENCE_HASH_1,
    )

    evaluation = validate_success(
        api_client.evaluate_observation(observation["id"], ANALYST_HEADERS)
    )

    assert evaluation["effective_map_floor_cents"] == 15000
    assert evaluation["floor_source"] == "STANDARD"
    assert evaluation["deviation_cents"] == deviation_cents(15000, 14000) == 1000
    assert evaluation["deviation_pct"] == deviation_pct(15000, 1000) == 0.0667

    stored = read_observation(observation["id"])
    assert stored["evaluation_status"] == "EVALUATED_BREACH"
    assert stored["deviation_cents"] == 1000
    assert stored["deviation_pct"] == 0.0667


# --------------------------------------------------------------------------- #
# Server-owned fields
# --------------------------------------------------------------------------- #
def test_the_server_mints_the_identity_and_audit_fields_of_a_new_policy():
    """A bare UUID, three-digit clock timestamps, version 1 and no decisions yet.

    PRD: "`id` is a server-minted UUID with no type prefix; clients never supply it." "`created_at` is the ISO 8601 UTC instant of creation, formatted with three fractional digits." "`updated_at` is the ISO 8601 UTC instant of the most recent mutation, in the same format; at creation it equals `created_at`." "`version` is an integer that starts at 1 when the row is created and increases by exactly 1 on every mutation of that row." "Timestamps minted by the server are always read from the logical clock described in §2.6, never from wall-clock time."

    Design: Corner/entities/system_fields_minted_by_server_on_pricing_policy_create
    """
    pin_clock(CLOCK_AUG_01)

    policy = validate_success(
        api_client.create_pricing_policy(
            pricing_policy_payload(policy_code="MAP-2026-S"), BCM_HEADERS
        ),
        expected_status=201,
    )

    assert is_valid_uuid(policy["id"])
    assert "_" not in policy["id"]
    assert is_iso8601_timestamp(policy["created_at"])
    assert_same_instant(policy["created_at"], CLOCK_AUG_01, "created_at")
    assert policy["created_at"].endswith(".000Z")
    assert policy["updated_at"] == policy["created_at"]
    assert policy["version"] == 1
    assert policy["status"] == "DRAFT"
    assert policy["reviewed_by_user_id"] is None
    assert policy["published_by_user_id"] is None
    assert policy["superseded_by_policy_id"] is None


def test_the_capturing_analyst_is_read_off_the_header_not_the_request_body():
    """Two analysts capturing two listings leave two different identity stamps.

    PRD: "The row is created with `evaluation_status` `CAPTURED`, `unauthorized_seller_confirmed` false, `evidence_captured_by_user_id` stamped from the capturing analyst's `X-User-ID`, and all five computed money fields — `allocated_component_price_cents`, `effective_advertised_price_cents`, `effective_map_floor_cents`, `deviation_cents` and `deviation_pct` — still null." "The same holds for `BrandLegalCounsel`, whose identifier is recorded as `reviewed_by_user_id` and `published_by_user_id` on a policy, as `approved_by_user_id` on an exception, and as `issued_by_user_id` on an enforcement notice; for `MonitoringAnalyst`, whose identifier is recorded as `evidence_captured_by_user_id` on a price observation and as `purchaser_user_id` on a test purchase; and for `PlatformAdmin`, whose identifier is recorded nowhere but which is nonetheless required for the clock and sweep capabilities."

    Design: Corner/entities/observation_evidence_captured_by_user_id_comes_from_header_not_body
    """
    _policy, product = _policy_and_product()
    pin_clock(CLOCK_AUG_20)

    first = validate_success(
        api_client.create_observation(
            observation_payload(
                product["id"],
                channel="MARKETPLACE",
                seller_display_name="Store One",
                listing_url="https://mkt.example/l/1",
                listed_price_cents=14000,
                observed_at=OBSERVED_AUG_18,
                evidence_hash=EVIDENCE_HASH_1,
            ),
            ANALYST_HEADERS,
        ),
        expected_status=201,
    )
    second = validate_success(
        api_client.create_observation(
            observation_payload(
                product["id"],
                channel="MARKETPLACE",
                seller_display_name="Store Two",
                listing_url="https://mkt.example/l/2",
                listed_price_cents=14500,
                observed_at=OBSERVED_AUG_18,
                evidence_hash=EVIDENCE_HASH_3,
            ),
            ANALYST_2_HEADERS,
        ),
        expected_status=201,
    )

    assert first["evidence_captured_by_user_id"] == "analyst-1"
    assert second["evidence_captured_by_user_id"] == "analyst-2"


# --------------------------------------------------------------------------- #
# Field-level constraint refusals
# --------------------------------------------------------------------------- #
def test_a_lifecycle_status_outside_the_declared_set_is_refused():
    """RETIRED is not one of the three declared lifecycle members.

    PRD: "**Request shape.** Required body fields present, types correct, enum members drawn from the declared sets, numeric ranges honoured, `evidence_hash` exactly 64 lowercase hexadecimal characters, `permitted_channels` members distinct, `bundle_components` well formed whenever `is_bundle` is true, a suspension window no longer than 90 days, and `diverted_units` at least 1 — else `ERR_VALIDATION` (400)." "`lifecycle_status` is the commercial stage and defaults to `ACTIVE`, with `CLEARANCE` and `DISCONTINUED` as its other values; it is the gate on which exception types may be approved."

    Design: Corner/entities/create_product_with_unknown_lifecycle_enum_is_rejected
    """
    policy = _published_policy(policy_code="MAP-2026-A")

    validate_error(
        api_client.create_product(
            product_payload(
                policy["id"],
                sku="SKU-AUDIO-1",
                name="Studio Headphones",
                msrp_cents=20000,
                standard_map_floor_cents=15000,
                lifecycle_status="RETIRED",
            ),
            BCM_HEADERS,
        ),
        "ERR_VALIDATION",
    )


def test_a_sixty_three_character_evidence_digest_is_refused():
    """The digest must be exactly 64 hex characters, so 63 is malformed.

    PRD: "**Request shape.** Required body fields present, types correct, enum members drawn from the declared sets, numeric ranges honoured, `evidence_hash` exactly 64 lowercase hexadecimal characters, `permitted_channels` members distinct, `bundle_components` well formed whenever `is_bundle` is true, a suspension window no longer than 90 days, and `diverted_units` at least 1 — else `ERR_VALIDATION` (400)." "Each captured listing names the monitored SKU by `product_id`, the `channel` on which it was seen (one of `MARKETPLACE`, `RETAILER_SITE`, `OWN_WEBSITE` or `PHYSICAL_RETAIL`), the storefront's `seller_display_name`, the evidence `listing_url`, the `listed_price_cents` as displayed (which must be at least 0), the `observed_at` instant, and an `evidence_hash` that must be exactly 64 lowercase hexadecimal characters — the SHA-256 digest of the captured screenshot."

    Design: Corner/entities/create_price_observation_with_non_hex_evidence_hash_is_rejected
    """
    _policy, product = _policy_and_product()
    pin_clock(CLOCK_AUG_20)
    assert len(SHORT_EVIDENCE_HASH) == 63

    validate_error(
        api_client.create_observation(
            observation_payload(
                product["id"],
                channel="MARKETPLACE",
                seller_display_name="Acme Store",
                listing_url="https://mkt.example/l/1",
                listed_price_cents=14000,
                observed_at=OBSERVED_AUG_18,
                evidence_hash=SHORT_EVIDENCE_HASH,
            ),
            ANALYST_HEADERS,
        ),
        "ERR_VALIDATION",
    )


def test_a_chargeback_for_zero_units_is_refused_before_the_ledger_moves():
    """diverted_units must be at least 1, and the refusal leaves both ledgers at 0.

    PRD: "**Request shape.** Required body fields present, types correct, enum members drawn from the declared sets, numeric ranges honoured, `evidence_hash` exactly 64 lowercase hexadecimal characters, `permitted_channels` members distinct, `bundle_components` well formed whenever `is_bundle` is true, a suspension window no longer than 90 days, and `diverted_units` at least 1 — else `ERR_VALIDATION` (400)." "A `BrandChannelManager` assesses one by naming the accountable `distributor_id`, the originating `test_purchase_id`, the number of `diverted_units` charged for this event (at least 1), and the `expected_distributor_version` demanded by §2.8."

    Design: Corner/entities/create_distributor_chargeback_with_zero_diverted_units_is_rejected
    """
    _policy, product = _policy_and_product()
    distributor = create_distributor(
        legal_name="Northwind Distribution", annual_chargeback_cap_cents=500000
    )
    purchase, _unit, _observation = _confirmed_trace(product["id"], distributor["id"])

    validate_error(
        api_client.assess_chargeback(
            chargeback_payload(
                distributor["id"],
                purchase["id"],
                read_distributor(distributor["id"])["version"],
                diverted_units=0,
            ),
            BCM_HEADERS,
        ),
        "ERR_VALIDATION",
    )

    stored = read_distributor(distributor["id"])
    assert stored["chargeback_balance_cents"] == 0
    assert stored["diversion_score"] == 0


def test_an_exception_window_that_closes_before_it_opens_is_refused():
    """ends_at must be strictly after starts_at, so a backwards window is malformed.

    PRD: "A `BrandChannelManager` may request an exception naming the `product_id` it covers and an `exception_type` of `CLEARANCE`, `BUNDLE` or `PROMOTIONAL_EVENT`, together with a window: `starts_at` is inclusive and `ends_at` is exclusive, `ends_at` must be strictly after `starts_at`, and the window may not span more than 180 days."

    Design: Corner/entities/create_pricing_exception_with_ends_at_before_starts_at_is_rejected
    """
    _policy, product = _policy_and_product()

    validate_error(
        api_client.create_exception(
            exception_payload(
                product["id"],
                exception_type="PROMOTIONAL_EVENT",
                starts_at="2026-08-10T00:00:00Z",
                ends_at="2026-08-09T00:00:00Z",
                requested_override_floor_cents=13000,
            ),
            BCM_HEADERS,
        ),
        "ERR_VALIDATION",
    )

    _rows, meta = validate_paginated(
        api_client.list_exceptions(BCM_HEADERS, params={"product_id": product["id"]})
    )
    assert meta["total_count"] == 0


# --------------------------------------------------------------------------- #
# Body-reference existence
# --------------------------------------------------------------------------- #
def test_a_product_naming_an_unknown_governing_policy_is_a_policy_not_found():
    """A dangling policy FK is a 404 on the policy, not a not-published complaint.

    PRD: "**Body reference existence.** Every foreign key supplied in the request body resolves to an existing row, validated in the order the fields are listed for that endpoint in §4's companion narrative, again yielding the not-found code of the missing type (and `ERR_SERIAL_NOT_REGISTERED`, HTTP 404, when a submitted `serial_number` matches no registered serialized unit)."

    Design: Corner/entities/create_product_with_unknown_governing_policy_returns_policy_not_found
    """
    pin_clock(CLOCK_AUG_01)

    validate_error(
        api_client.create_product(
            product_payload(
                UNKNOWN_POLICY_ID,
                sku="SKU-AUDIO-1",
                name="Studio Headphones",
                msrp_cents=20000,
                standard_map_floor_cents=15000,
            ),
            BCM_HEADERS,
        ),
        "ERR_POLICY_NOT_FOUND",
    )


def test_a_unit_shipped_to_an_unknown_distributor_is_a_distributor_not_found():
    """With the product resolving first, the dangling distributor FK is what fails.

    PRD: "**Body reference existence.** Every foreign key supplied in the request body resolves to an existing row, validated in the order the fields are listed for that endpoint in §4's companion narrative, again yielding the not-found code of the missing type (and `ERR_SERIAL_NOT_REGISTERED`, HTTP 404, when a submitted `serial_number` matches no registered serialized unit)."

    Design: Corner/entities/create_serial_unit_with_unknown_distributor_returns_distributor_not_found
    """
    _policy, product = _policy_and_product(serialization_enabled=True)

    validate_error(
        api_client.create_serial_unit(
            serial_unit_payload(
                product["id"],
                UNKNOWN_DISTRIBUTOR_ID,
                serial_number="SN-0001",
                lot_code="LOT-A",
            ),
            BCM_HEADERS,
        ),
        "ERR_DISTRIBUTOR_NOT_FOUND",
    )

    _rows, meta = validate_paginated(
        api_client.list_serial_units(BCM_HEADERS, params={"product_id": product["id"]})
    )
    assert meta["total_count"] == 0


def test_an_agreement_drafted_for_an_unknown_reseller_is_a_reseller_not_found():
    """The reseller FK is checked ahead of the perfectly valid policy FK.

    PRD: "**Body reference existence.** Every foreign key supplied in the request body resolves to an existing row, validated in the order the fields are listed for that endpoint in §4's companion narrative, again yielding the not-found code of the missing type (and `ERR_SERIAL_NOT_REGISTERED`, HTTP 404, when a submitted `serial_number` matches no registered serialized unit)."

    Design: Corner/entities/create_reseller_agreement_with_unknown_reseller_returns_reseller_not_found
    """
    policy = _published_policy(policy_code="MAP-2026-A")

    validate_error(
        api_client.create_agreement(
            agreement_payload(
                UNKNOWN_RESELLER_ID,
                policy["id"],
                permitted_channels=["MARKETPLACE"],
                quality_obligations=[],
                term_ends_at=TERM_ENDS_AT,
            ),
            BCM_HEADERS,
        ),
        "ERR_RESELLER_NOT_FOUND",
    )
