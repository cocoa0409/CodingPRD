"""Birth states, stored fields and reads for every row type in the contract.

Each entity in the PRD is minted with a pinned initial status and a pinned set
of null-at-birth fields; the reads then have to hand those exact values back,
paginate them and refuse to invent a row that does not exist.
"""
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ANALYST_HEADERS,
    BCM_HEADERS,
    COUNSEL_HEADERS,
    api_client,
)
from test_helpers.assertions import score_delta, tier_rate_for_score, violation_points
from test_helpers.constants import EVIDENCE_HASH_1
from test_helpers.factories import (
    agreement_payload,
    bundle_component,
    chargeback_payload,
    distributor_payload,
    exception_payload,
    notice_payload,
    observation_payload,
    pricing_policy_payload,
    product_payload,
    reseller_payload,
    serial_unit_payload,
    test_purchase_payload,
)
from test_helpers.fixtures import (
    capture_observation,
    capture_purchase_serial,
    confirm_unauthorized,
    create_active_agreement,
    create_distributor,
    create_draft_policy,
    create_product,
    create_published_policy,
    create_reseller,
    create_serial_unit,
    current_reseller_version,
    order_test_purchase,
    pin_clock,
    read_distributor,
    read_observation,
    read_violation,
)

CLOCK_AUG_01 = "2026-08-01T00:00:00Z"
CLOCK_AUG_20 = "2026-08-20T00:00:00Z"
OBSERVED_AUG_18 = "2026-08-18T00:00:00Z"
ORDERED_AUG_19 = "2026-08-19T00:00:00Z"
TERM_ENDS_AT = "2027-06-30T00:00:00Z"

UNKNOWN_RESELLER_ID = "00000000-0000-4000-8000-000000000001"
UNKNOWN_VIOLATION_ID = "00000000-0000-4000-8000-000000000002"
UNKNOWN_CHARGEBACK_ID = "00000000-0000-4000-8000-000000000003"
UNKNOWN_SERIAL_UNIT_ID = "00000000-0000-4000-8000-000000000004"


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


def _authorized_reseller(policy_id, legal_name, contact_email):
    """One reseller walked all the way to an ACTIVE marketplace agreement."""
    reseller = create_reseller(
        legal_name=legal_name, contact_email=contact_email, primary_channel="MARKETPLACE"
    )
    agreement = create_active_agreement(
        reseller["id"],
        policy_id,
        permitted_channels=["MARKETPLACE"],
        quality_obligations=[],
        term_ends_at=TERM_ENDS_AT,
    )
    return reseller, agreement


def _matched_breach(product_id, reseller_id, listing_url, seller_display_name):
    """A below-floor marketplace listing pinned on a named reseller, evaluated."""
    observation = capture_observation(
        product_id,
        channel="MARKETPLACE",
        seller_display_name=seller_display_name,
        listing_url=listing_url,
        listed_price_cents=14000,
        observed_at=OBSERVED_AUG_18,
        evidence_hash=EVIDENCE_HASH_1,
        matched_reseller_id=reseller_id,
    )
    evaluation = validate_success(
        api_client.evaluate_observation(observation["id"], ANALYST_HEADERS)
    )
    return observation, evaluation


def _unmatched_purchase(product_id):
    """An unknown storefront's breach and the test purchase ordered against it."""
    observation = capture_observation(
        product_id,
        channel="MARKETPLACE",
        seller_display_name="GreyBox Deals",
        listing_url="https://mkt.example/l/9",
        listed_price_cents=9000,
        observed_at=OBSERVED_AUG_18,
        evidence_hash=EVIDENCE_HASH_1,
    )
    return observation


def _confirmed_trace(product_id, distributor_id, serial_number="SN-0001"):
    """A unit registered to a distributor and traced to an unauthorized seller."""
    unit = create_serial_unit(
        product_id, distributor_id, serial_number=serial_number, lot_code="LOT-A"
    )
    pin_clock(CLOCK_AUG_20)
    observation = _unmatched_purchase(product_id)
    purchase = order_test_purchase(
        observation["id"], ordered_at=ORDERED_AUG_19, purchase_price_cents=9000
    )
    capture_purchase_serial(purchase["id"], serial_number)
    purchase = confirm_unauthorized(purchase["id"], outcome_reason="Unauthorized storefront")
    return purchase, unit, observation


# --------------------------------------------------------------------------- #
# Creation birth states
# --------------------------------------------------------------------------- #
def test_drafting_a_policy_mints_revision_one_in_draft_with_nothing_decided_yet():
    """A brand-new policy is DRAFT at revision 1 with every decision field null.

    PRD: "The new policy is born in status `DRAFT` with `revision_number` set to 1, and its `effective_from`, `legal_review_notes`, `reviewed_by_user_id`, `published_by_user_id`, `superseded_by_policy_id` and `withdrawn_reason` all null." "Creation endpoints — those that mint a brand-new row — return HTTP 201 on success."

    Design: Corner/entities/create_pricing_policy_returns_draft_revision_one
    """
    pin_clock(CLOCK_AUG_01)

    policy = validate_success(
        api_client.create_pricing_policy(
            pricing_policy_payload(policy_code="MAP-2026-A"), BCM_HEADERS
        ),
        expected_status=201,
    )

    assert policy["status"] == "DRAFT"
    assert policy["revision_number"] == 1
    assert policy["policy_code"] == "MAP-2026-A"
    assert policy["version"] == 1
    assert policy["effective_from"] is None
    assert policy["legal_review_notes"] is None
    assert policy["withdrawn_reason"] is None


def test_a_product_registered_under_a_published_policy_has_no_open_exceptions():
    """Registration returns 201 and an exception counter that starts at zero.

    PRD: "Every newly registered product starts with `open_exception_count` at 0." "Registration also names a `governing_policy_id`, and that policy must be in status `PUBLISHED` at the moment of registration, else `ERR_POLICY_NOT_PUBLISHED`."

    Design: Corner/entities/create_product_under_published_policy_starts_with_zero_open_exceptions
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

    assert product["open_exception_count"] == 0
    assert product["governing_policy_id"] == policy["id"]
    assert product["version"] == 1


def test_a_new_distributor_starts_good_with_every_ledger_at_zero():
    """Both money and score ledgers start empty and probation is unstamped.

    PRD: "Every new distributor starts in `standing` `GOOD` with `diversion_score` at 0, `chargeback_balance_cents` at 0, `shipped_units_total` at 0 and `probation_entered_at` null."

    Design: Corner/entities/create_distributor_starts_good_with_empty_ledgers
    """
    pin_clock(CLOCK_AUG_01)

    distributor = validate_success(
        api_client.create_distributor(
            distributor_payload(
                legal_name="Northwind Distribution", annual_chargeback_cap_cents=500000
            ),
            BCM_HEADERS,
        ),
        expected_status=201,
    )

    assert distributor["standing"] == "GOOD"
    assert distributor["diversion_score"] == 0
    assert distributor["chargeback_balance_cents"] == 0
    assert distributor["shipped_units_total"] == 0
    assert distributor["probation_entered_at"] is None


def test_a_new_reseller_starts_applied_on_one_axis_and_held_on_the_other():
    """The two reseller axes start APPLIED and HOLD with the pending-auth reason.

    PRD: "A newly recorded reseller starts with `authorization_status` `APPLIED`, `supply_status` `HOLD`, `hold_reason` `PENDING_AUTHORIZATION`, `violation_points_total` at 0 and `review_required` evaluated once at creation (which for a fresh row means false unless the named sourcing distributor is already in `PROBATION` or `SUSPENDED`)." "The fields `suspension_ends_at`, `last_suspension_ended_at` and `terminated_at` all start null."

    Design: Corner/entities/create_reseller_starts_applied_and_held_pending_authorization
    """
    pin_clock(CLOCK_AUG_01)
    distributor = create_distributor(
        legal_name="Northwind Distribution", annual_chargeback_cap_cents=500000
    )
    assert distributor["standing"] == "GOOD"

    reseller = validate_success(
        api_client.create_reseller(
            reseller_payload(
                legal_name="Acme Retail LLC",
                contact_email="ops@acme.example",
                primary_channel="MARKETPLACE",
                sourcing_distributor_id=distributor["id"],
            ),
            BCM_HEADERS,
        ),
        expected_status=201,
    )

    assert reseller["authorization_status"] == "APPLIED"
    assert reseller["supply_status"] == "HOLD"
    assert reseller["hold_reason"] == "PENDING_AUTHORIZATION"
    assert reseller["violation_points_total"] == 0
    assert reseller["review_required"] is False
    assert reseller["suspension_ends_at"] is None
    assert reseller["last_suspension_ended_at"] is None
    assert reseller["terminated_at"] is None


def test_a_drafted_agreement_carries_no_acknowledgement_and_no_price_terms():
    """Drafting leaves every signature timestamp null and the reseller at APPLIED.

    PRD: "A fresh agreement is created in status `DRAFT` with `non_negotiation_acknowledged` false and with `sent_at`, `countersigned_at`, `countersigned_by_user_id`, `activated_at` and `closed_reason` all null." "The payload also supplies `term_ends_at`, the expiry instant the sweep later enforces, and may declare `price_terms_included`, which defaults to false and whose only permitted value is false per §2.7."

    Design: Corner/entities/create_reseller_agreement_starts_draft_with_negotiation_flags_unset
    """
    policy = _published_policy(policy_code="MAP-2026-A")
    reseller = create_reseller(
        legal_name="Acme Retail LLC",
        contact_email="ops@acme.example",
        primary_channel="MARKETPLACE",
    )

    agreement = validate_success(
        api_client.create_agreement(
            agreement_payload(
                reseller["id"],
                policy["id"],
                permitted_channels=["MARKETPLACE", "OWN_WEBSITE"],
                quality_obligations=["AUTHENTICITY_LABELING", "WARRANTY_HONORED"],
                term_ends_at=TERM_ENDS_AT,
            ),
            BCM_HEADERS,
        ),
        expected_status=201,
    )

    assert agreement["status"] == "DRAFT"
    assert agreement["non_negotiation_acknowledged"] is False
    assert agreement["price_terms_included"] is False
    assert agreement["sent_at"] is None
    assert agreement["countersigned_at"] is None
    assert agreement["countersigned_by_user_id"] is None
    assert agreement["activated_at"] is None
    assert agreement["closed_reason"] is None

    # Drafting alone does not move the reseller off its application state.
    assert validate_success(api_client.get_reseller(reseller["id"], BCM_HEADERS))[
        "authorization_status"
    ] == "APPLIED"


def test_capturing_evidence_stamps_the_analyst_and_leaves_the_money_uncomputed():
    """A captured observation carries the analyst's id and no derived money yet.

    PRD: "The row is created with `evaluation_status` `CAPTURED`, `unauthorized_seller_confirmed` false, `evidence_captured_by_user_id` stamped from the capturing analyst's `X-User-ID`, and all five computed money fields — `allocated_component_price_cents`, `effective_advertised_price_cents`, `effective_map_floor_cents`, `deviation_cents` and `deviation_pct` — still null."

    Design: Corner/entities/create_price_observation_starts_captured_with_analyst_stamp
    """
    _policy, product = _policy_and_product()
    pin_clock(CLOCK_AUG_20)

    observation = validate_success(
        api_client.create_observation(
            observation_payload(
                product["id"],
                channel="MARKETPLACE",
                marketplace_name="BigMarket",
                seller_display_name="Acme Store",
                listing_url="https://mkt.example/l/1",
                listed_price_cents=14000,
                observed_at=OBSERVED_AUG_18,
                evidence_hash=EVIDENCE_HASH_1,
            ),
            ANALYST_HEADERS,
        ),
        expected_status=201,
    )

    assert observation["evaluation_status"] == "CAPTURED"
    assert observation["evidence_captured_by_user_id"] == "analyst-1"
    assert observation["unauthorized_seller_confirmed"] is False
    assert observation["effective_advertised_price_cents"] is None
    assert observation["effective_map_floor_cents"] is None
    assert observation["deviation_cents"] is None
    assert observation["deviation_pct"] is None


def test_an_exception_window_that_opens_at_the_clock_is_not_retroactive():
    """starts_at equal to the clock is not strictly before it, so retroactive is false.

    PRD: "A new exception is created in status `REQUESTED`, with `requested_by_user_id` stamped from the requesting manager's `X-User-ID`, with `override_floor_cents`, `approved_by_user_id` and `decision_reason` all null, and with `voided_violation_count` at 0." "The `retroactive` flag is computed, not supplied: it is true exactly when `starts_at` is strictly before the logical clock at creation time."

    Design: Corner/entities/create_pricing_exception_starts_requested_and_not_retroactive
    """
    _policy, product = _policy_and_product()

    exception = validate_success(
        api_client.create_exception(
            exception_payload(
                product["id"],
                exception_type="PROMOTIONAL_EVENT",
                starts_at=CLOCK_AUG_01,
                ends_at="2026-08-31T00:00:00Z",
                channel_scope="MARKETPLACE",
                requested_override_floor_cents=13000,
                dealer_input_source="BRAND_MARKETING_PLAN",
            ),
            BCM_HEADERS,
        ),
        expected_status=201,
    )

    assert exception["status"] == "REQUESTED"
    assert exception["retroactive"] is False
    assert exception["override_floor_cents"] is None
    assert exception["approved_by_user_id"] is None
    assert exception["decision_reason"] is None
    assert exception["requested_by_user_id"] == "bcm-1"
    assert exception["voided_violation_count"] == 0


def test_registering_a_unit_puts_it_in_distributor_custody_and_bumps_the_total():
    """Custody starts at the distributor and its shipped_units_total goes 0 to 1.

    PRD: "The unit is created in custody state `SHIPPED_TO_DISTRIBUTOR` with `downstream_reseller_id`, `shipped_downstream_at` and `traced_at` all null, and the named distributor's `shipped_units_total` — which counts every unit whose `shipped_distributor_id` is that distributor, in any custody state — is increased accordingly."

    Design: Corner/entities/create_serial_unit_starts_shipped_to_distributor_and_bumps_shipped_total
    """
    _policy, product = _policy_and_product(serialization_enabled=True)
    distributor = create_distributor(
        legal_name="Northwind Distribution", annual_chargeback_cap_cents=500000
    )
    assert distributor["shipped_units_total"] == 0

    unit = validate_success(
        api_client.create_serial_unit(
            serial_unit_payload(
                product["id"], distributor["id"], serial_number="SN-0001", lot_code="LOT-A"
            ),
            BCM_HEADERS,
        ),
        expected_status=201,
    )

    assert unit["status"] == "SHIPPED_TO_DISTRIBUTOR"
    assert unit["downstream_reseller_id"] is None
    assert unit["shipped_downstream_at"] is None
    assert unit["traced_at"] is None
    assert read_distributor(distributor["id"])["shipped_units_total"] == 1


def test_ordering_a_test_purchase_stamps_the_buyer_and_traces_nothing_yet():
    """A purchase starts ORDERED with the analyst's id and no serial read off it.

    PRD: "The purchase is created in status `ORDERED` with `purchaser_user_id` stamped from the analyst's `X-User-ID` and with `captured_serial_number`, `traced_serial_unit_id` and `outcome_reason` all null."

    Design: Corner/entities/create_test_purchase_starts_ordered_with_purchaser_stamp
    """
    _policy, product = _policy_and_product()
    pin_clock(CLOCK_AUG_20)
    observation = _unmatched_purchase(product["id"])

    purchase = validate_success(
        api_client.create_test_purchase(
            test_purchase_payload(
                observation["id"], ordered_at=ORDERED_AUG_19, purchase_price_cents=9000
            ),
            ANALYST_HEADERS,
        ),
        expected_status=201,
    )

    assert purchase["status"] == "ORDERED"
    assert purchase["purchaser_user_id"] == "analyst-1"
    assert purchase["captured_serial_number"] is None
    assert purchase["traced_serial_unit_id"] is None
    assert purchase["outcome_reason"] is None


def test_the_first_chargeback_on_a_good_distributor_is_priced_at_the_lowest_tier():
    """A pre-event score of 0 is strictly below 10.0, so the rate is 2500 a unit.

    PRD: "The `tier_rate_cents_per_unit` is 2500 cents when that pre-event score is strictly below 10.0, 4000 cents when it is at or above 10.0 but strictly below 25.0, and 6000 cents when it is at or above 25.0 — twenty-five, forty and sixty dollars a unit, with both tier boundaries inclusive at the lower bound." "The `amount_cents` is that per-unit rate multiplied by `diverted_units`." "The `score_delta_applied` is two and a half score points per diverted unit." "The chargeback row itself is created in status `ASSESSED` with `dispute_rounds` at 0 and `dispute_reason` and `decision_reason` null."

    Design: Corner/entities/create_distributor_chargeback_starts_assessed_with_first_tier_rate
    """
    _policy, product = _policy_and_product()
    distributor = create_distributor(
        legal_name="Northwind Distribution", annual_chargeback_cap_cents=500000
    )
    purchase, _unit, _observation = _confirmed_trace(product["id"], distributor["id"])

    before = read_distributor(distributor["id"])
    assert before["diversion_score"] == 0

    chargeback = validate_success(
        api_client.assess_chargeback(
            chargeback_payload(
                distributor["id"], purchase["id"], before["version"], diverted_units=4
            ),
            BCM_HEADERS,
        ),
        expected_status=201,
    )

    assert chargeback["status"] == "ASSESSED"
    assert chargeback["dispute_rounds"] == 0
    assert chargeback["decision_reason"] is None
    assert chargeback["tier_rate_cents_per_unit"] == tier_rate_for_score(0) == 2500
    assert chargeback["amount_cents"] == 2500 * 4 == 10000
    assert chargeback["score_delta_applied"] == score_delta(4) == 10.0


def test_a_first_notice_on_a_clean_reseller_is_issued_at_the_warning_rung():
    """Three points sit below the suspension threshold of six, so WARNING it is.

    PRD: "Compare that figure against the cited policy's two thresholds, with both boundaries inclusive at the lower bound: the points-justified rung is `WARNING` when the cumulative figure is strictly below `suspension_points_threshold`, `SUSPENSION` when it is at or above `suspension_points_threshold` but strictly below `termination_points_threshold`, and `TERMINATION` when it is at or above `termination_points_threshold`." "And the notice itself is created in status `ISSUED`, carrying the computed `rung`, the snapshotted `cumulative_points_at_issue`, an `assessed_points` mirroring the figure charged onto the violation, and `issued_by_user_id` stamped from the issuer's `X-User-ID`, with `acknowledged_at` and `closed_reason` null."

    Design: Corner/entities/create_enforcement_notice_starts_issued_at_warning_rung
    """
    policy, product = _policy_and_product()
    reseller, _agreement = _authorized_reseller(
        policy["id"], "Acme Retail LLC", "ops@acme.example"
    )
    pin_clock(CLOCK_AUG_20)
    _observation, evaluation = _matched_breach(
        product["id"], reseller["id"], "https://mkt.example/l/1", "Acme Store"
    )

    notice = validate_success(
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

    assert notice["status"] == "ISSUED"
    assert notice["rung"] == "WARNING"
    assert notice["assessed_points"] == violation_points(15000, 14000, "MARKETPLACE", 0) == 3
    assert notice["cumulative_points_at_issue"] == 3
    assert notice["issued_by_user_id"] == "bcm-1"
    assert notice["acknowledged_at"] is None
    assert notice["closed_reason"] is None


def test_the_evaluate_cascade_is_what_mints_a_violation_and_its_snapshot():
    """A violation has no create endpoint: evaluation opens it in DETECTED.

    PRD: "If `matched_reseller_id` is not null, a violation row is opened in status `DETECTED` carrying `provisional_floor_cents` — the floor as resolved at `observed_at` — and `provisional_points`, together with `observation_id` pointing back at the evidence, `reseller_id` copied from the observation's `matched_reseller_id`, and `cited_policy_id` set to the policy the selection rule picked for `observed_at`." "A violation that was detected but never noticed contributes nothing, because its `assessed_points` is still null; a `VOIDED` violation contributes nothing, because voiding clears `assessed_points` back to null."

    Design: Corner/entities/violation_row_created_by_evaluate_cascade_carries_provisional_snapshot
    """
    policy, product = _policy_and_product()
    reseller, _agreement = _authorized_reseller(
        policy["id"], "Acme Retail LLC", "ops@acme.example"
    )
    pin_clock(CLOCK_AUG_20)
    observation, evaluation = _matched_breach(
        product["id"], reseller["id"], "https://mkt.example/l/1", "Acme Store"
    )

    violation = read_violation(evaluation["violation_id"])

    assert violation["status"] == "DETECTED"
    assert violation["observation_id"] == observation["id"]
    assert violation["reseller_id"] == reseller["id"]
    assert violation["cited_policy_id"] == policy["id"]
    assert violation["provisional_floor_cents"] == 15000
    assert violation["provisional_points"] == violation_points(15000, 14000, "MARKETPLACE", 0) == 3
    assert violation["assessed_points"] is None


# --------------------------------------------------------------------------- #
# Reads: stored fields, pagination and filters
# --------------------------------------------------------------------------- #
def test_reading_a_policy_hands_back_the_non_default_ladder_thresholds():
    """The three ladder-and-cure figures come back exactly as drafted.

    PRD: "`cure_window_days` is the number of days a reseller has to cure a noticed violation before it escalates; it must be between 1 and 60 inclusive and defaults to 10." "`suspension_points_threshold` is the cumulative points figure at or above which the ladder's points-based rung becomes suspension; it must be at least 1 and defaults to 6." "`termination_points_threshold` is the cumulative points figure at or above which the points-based rung becomes termination; it defaults to 12 and must be strictly greater than `suspension_points_threshold`."

    Design: Corner/entities/get_pricing_policy_returns_stored_revision_fields
    """
    pin_clock(CLOCK_AUG_01)
    policy = create_draft_policy(
        policy_code="MAP-2026-T",
        cure_window_days=20,
        suspension_points_threshold=8,
        termination_points_threshold=30,
        suspension_cooling_off_days=21,
        max_discount_attribution_pct=0.25,
    )

    stored = validate_success(api_client.get_pricing_policy(policy["id"], ANALYST_HEADERS))

    assert stored["cure_window_days"] == 20
    assert stored["suspension_points_threshold"] == 8
    assert stored["termination_points_threshold"] == 30


def test_reading_a_policy_hands_back_the_cooling_off_gap_and_attribution_cap():
    """A single-resource read is an object envelope carrying the stored fractions.

    PRD: "Finally, `suspension_cooling_off_days` is the mandatory gap between the end of one suspension window and the start of the next; it must be between 0 and 180 inclusive and defaults to 14." "Alongside them, `max_discount_attribution_pct` caps how much of a listing's gross price any single discount may be credited with reducing for MAP purposes; it is a two-decimal fraction between 0.00 and 1.00 inclusive and defaults to 0.40, meaning at most forty percent of the gross price." "`response_type` is either "object" for a single resource or "array" for a list of resources."

    Design: Corner/entities/get_pricing_policy_returns_stored_revision_fields
    """
    pin_clock(CLOCK_AUG_01)
    policy = create_draft_policy(
        policy_code="MAP-2026-T",
        cure_window_days=20,
        suspension_points_threshold=8,
        termination_points_threshold=30,
        suspension_cooling_off_days=21,
        max_discount_attribution_pct=0.25,
    )

    response = api_client.get_pricing_policy(policy["id"], ANALYST_HEADERS)
    stored = validate_success(response)

    assert response.json()["response_type"] == "object"
    assert stored["suspension_cooling_off_days"] == 21
    assert stored["max_discount_attribution_pct"] == 0.25


def test_reading_a_bundle_observation_returns_its_component_evidence_verbatim():
    """The two-member component array and bundle total survive the round trip.

    PRD: "When `is_bundle` is true — it defaults to false — the capture must also supply `bundle_total_price_cents`, the advertised price of the whole bundle, which must be strictly greater than zero, and `bundle_components`, an array of at least two distinct objects each carrying a `sku` string and an `msrp_cents` integer strictly greater than zero." "The component array must include the observed product's own `sku`."

    Design: Corner/entities/get_price_observation_returns_stored_bundle_evidence
    """
    _policy, product = _policy_and_product()
    pin_clock(CLOCK_AUG_20)
    components = [bundle_component("SKU-AUDIO-1", 20000), bundle_component("SKU-CABLE-9", 5000)]
    observation = capture_observation(
        product["id"],
        channel="MARKETPLACE",
        seller_display_name="Acme Store",
        listing_url="https://mkt.example/b/1",
        listed_price_cents=18000,
        observed_at=OBSERVED_AUG_18,
        evidence_hash=EVIDENCE_HASH_1,
        is_bundle=True,
        bundle_total_price_cents=18000,
        bundle_components=components,
    )

    stored = read_observation(observation["id"])

    assert stored["is_bundle"] is True
    assert stored["bundle_total_price_cents"] == 18000
    assert len(stored["bundle_components"]) == 2
    assert {row["sku"]: row["msrp_cents"] for row in stored["bundle_components"]} == {
        "SKU-AUDIO-1": 20000,
        "SKU-CABLE-9": 5000,
    }
    assert stored["evaluation_status"] == "CAPTURED"


def test_listing_products_reports_the_prefilter_count_and_a_truthful_has_more():
    """Three rows over a two-row window: total_count 3, has_more true then false.

    PRD: "Every list response carries `limit`, `offset`, `total_count` and `has_more` inside `meta`: `total_count` is the number of rows matching the filters *before* the page window is applied, and `has_more` is true exactly when rows matching the filters remain beyond the current window." "`response_type` is either "object" for a single resource or "array" for a list of resources."

    Design: Corner/entities/list_products_paginates_with_total_count_and_has_more
    """
    policy = _published_policy(policy_code="MAP-2026-A")
    create_product(
        policy["id"],
        sku="SKU-AUDIO-1",
        name="Studio Headphones",
        msrp_cents=20000,
        standard_map_floor_cents=15000,
    )
    create_product(
        policy["id"],
        sku="SKU-AUDIO-2",
        name="Desk Microphone",
        msrp_cents=12000,
        standard_map_floor_cents=9000,
    )
    create_product(
        policy["id"],
        sku="SKU-AUDIO-3",
        name="Monitor Speaker",
        msrp_cents=30000,
        standard_map_floor_cents=24000,
    )

    first_response = api_client.list_products(ANALYST_HEADERS, params={"limit": 2, "offset": 0})
    first_rows, first_meta = validate_paginated(first_response)
    assert first_response.json()["response_type"] == "array"
    assert len(first_rows) == 2
    assert first_meta["total_count"] == 3
    assert first_meta["has_more"] is True
    assert first_meta["limit"] == 2
    assert first_meta["offset"] == 0

    second_rows, second_meta = validate_paginated(
        api_client.list_products(ANALYST_HEADERS, params={"limit": 2, "offset": 2})
    )
    assert len(second_rows) == 1
    assert second_meta["total_count"] == 3
    assert second_meta["has_more"] is False
    assert second_meta["offset"] == 2


def test_filtering_violations_by_reseller_hides_the_other_resellers_violation():
    """The reseller_id filter narrows both the rows and the pre-window count.

    PRD: "Violations are readable individually and as a collection filtered by `observation_id`, `reseller_id`, `cited_policy_id` or `status`." "All filter parameters on a list endpoint are optional and combine conjunctively — supplying `status` and `reseller_id` together returns only rows matching both."

    Design: Corner/entities/list_violations_filtered_by_reseller_excludes_other_resellers
    """
    policy, product = _policy_and_product()
    acme, _acme_agreement = _authorized_reseller(
        policy["id"], "Acme Retail LLC", "ops@acme.example"
    )
    bravo, _bravo_agreement = _authorized_reseller(
        policy["id"], "Bravo Outlet Inc", "ops@bravo.example"
    )
    pin_clock(CLOCK_AUG_20)
    _acme_observation, acme_evaluation = _matched_breach(
        product["id"], acme["id"], "https://mkt.example/l/1", "Acme Store"
    )
    _bravo_observation, bravo_evaluation = _matched_breach(
        product["id"], bravo["id"], "https://mkt.example/l/2", "Bravo Store"
    )

    response = api_client.list_violations(
        BCM_HEADERS, params={"reseller_id": acme["id"], "limit": 10, "offset": 0}
    )
    rows, meta = validate_paginated(response)

    assert response.json()["response_type"] == "array"
    assert meta["total_count"] == 1
    assert len(rows) == 1
    assert rows[0]["id"] == acme_evaluation["violation_id"]
    assert bravo_evaluation["violation_id"] not in [row["id"] for row in rows]


# --------------------------------------------------------------------------- #
# Path-existence refusals
# --------------------------------------------------------------------------- #
def test_reading_an_unknown_reseller_is_a_refusal_not_an_empty_object():
    """A well-formed UUID that names no reseller is a 404, never a blank row.

    PRD: "**Path existence.** Every resource named by a path parameter exists, validated left to right, so that on a nested path the leftmost missing resource determines the error." "The code is the not-found code of the resource type that is missing: `ERR_POLICY_NOT_FOUND`, `ERR_PRODUCT_NOT_FOUND`, `ERR_RESELLER_NOT_FOUND`, `ERR_DISTRIBUTOR_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`, `ERR_OBSERVATION_NOT_FOUND`, `ERR_VIOLATION_NOT_FOUND`, `ERR_NOTICE_NOT_FOUND`, `ERR_EXCEPTION_NOT_FOUND`, `ERR_SERIAL_UNIT_NOT_FOUND`, `ERR_TEST_PURCHASE_NOT_FOUND` or `ERR_CHARGEBACK_NOT_FOUND`, each HTTP 404."

    Design: Corner/entities/get_reseller_with_unknown_id_returns_reseller_not_found
    """
    pin_clock(CLOCK_AUG_01)

    validate_error(
        api_client.get_reseller(UNKNOWN_RESELLER_ID, BCM_HEADERS), "ERR_RESELLER_NOT_FOUND"
    )


def test_reading_an_unknown_violation_is_a_refusal_even_though_none_can_be_posted():
    """Violations are only ever born by cascade, yet the read still 404s properly.

    PRD: "**Path existence.** Every resource named by a path parameter exists, validated left to right, so that on a nested path the leftmost missing resource determines the error." "The code is the not-found code of the resource type that is missing: `ERR_POLICY_NOT_FOUND`, `ERR_PRODUCT_NOT_FOUND`, `ERR_RESELLER_NOT_FOUND`, `ERR_DISTRIBUTOR_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`, `ERR_OBSERVATION_NOT_FOUND`, `ERR_VIOLATION_NOT_FOUND`, `ERR_NOTICE_NOT_FOUND`, `ERR_EXCEPTION_NOT_FOUND`, `ERR_SERIAL_UNIT_NOT_FOUND`, `ERR_TEST_PURCHASE_NOT_FOUND` or `ERR_CHARGEBACK_NOT_FOUND`, each HTTP 404."

    Design: Corner/entities/get_violation_with_unknown_id_returns_violation_not_found
    """
    pin_clock(CLOCK_AUG_01)

    validate_error(
        api_client.get_violation(UNKNOWN_VIOLATION_ID, COUNSEL_HEADERS),
        "ERR_VIOLATION_NOT_FOUND",
    )


def test_reading_an_unknown_chargeback_is_a_refusal():
    """An unknown chargeback id yields the chargeback-specific not-found code.

    PRD: "**Path existence.** Every resource named by a path parameter exists, validated left to right, so that on a nested path the leftmost missing resource determines the error." "The code is the not-found code of the resource type that is missing: `ERR_POLICY_NOT_FOUND`, `ERR_PRODUCT_NOT_FOUND`, `ERR_RESELLER_NOT_FOUND`, `ERR_DISTRIBUTOR_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`, `ERR_OBSERVATION_NOT_FOUND`, `ERR_VIOLATION_NOT_FOUND`, `ERR_NOTICE_NOT_FOUND`, `ERR_EXCEPTION_NOT_FOUND`, `ERR_SERIAL_UNIT_NOT_FOUND`, `ERR_TEST_PURCHASE_NOT_FOUND` or `ERR_CHARGEBACK_NOT_FOUND`, each HTTP 404."

    Design: Corner/entities/get_distributor_chargeback_with_unknown_id_returns_chargeback_not_found
    """
    pin_clock(CLOCK_AUG_01)

    validate_error(
        api_client.get_chargeback(UNKNOWN_CHARGEBACK_ID, BCM_HEADERS), "ERR_CHARGEBACK_NOT_FOUND"
    )


def test_reading_an_unknown_serial_unit_is_a_refusal():
    """An unknown unit id yields the unit not-found code, not the serial one.

    PRD: "**Path existence.** Every resource named by a path parameter exists, validated left to right, so that on a nested path the leftmost missing resource determines the error." "The code is the not-found code of the resource type that is missing: `ERR_POLICY_NOT_FOUND`, `ERR_PRODUCT_NOT_FOUND`, `ERR_RESELLER_NOT_FOUND`, `ERR_DISTRIBUTOR_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`, `ERR_OBSERVATION_NOT_FOUND`, `ERR_VIOLATION_NOT_FOUND`, `ERR_NOTICE_NOT_FOUND`, `ERR_EXCEPTION_NOT_FOUND`, `ERR_SERIAL_UNIT_NOT_FOUND`, `ERR_TEST_PURCHASE_NOT_FOUND` or `ERR_CHARGEBACK_NOT_FOUND`, each HTTP 404."

    Design: Corner/entities/get_serial_unit_with_unknown_id_returns_serial_unit_not_found
    """
    pin_clock(CLOCK_AUG_01)

    validate_error(
        api_client.get_serial_unit(UNKNOWN_SERIAL_UNIT_ID, BCM_HEADERS),
        "ERR_SERIAL_UNIT_NOT_FOUND",
    )
