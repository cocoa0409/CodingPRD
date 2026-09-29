"""Endpoint breadth: pricing policies, products, distributors and resellers.

Each test drives one declared operation and checks the fields the PRD says that
operation writes or reports, including the pagination envelope of §2.3 and the
flat-addressing filter contract of §2.10.
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
    violation_points,
)
from test_helpers.factories import (
    policy_publish_payload,
    policy_review_decision_payload,
    policy_withdraw_payload,
    pricing_policy_payload,
    product_adjustment_payload,
    product_payload,
    reseller_payload,
    supply_status_payload,
)
from test_helpers.fixtures import (
    approve_exception,
    assess_chargeback,
    create_confirmed_trace,
    create_distributor,
    create_draft_policy,
    create_policy_in_review,
    create_product,
    create_published_policy,
    create_authorized_reseller,
    issue_warning,
    pin_clock,
    read_product,
    read_reseller,
    request_exception,
)

CLOCK_AUG_01 = "2026-08-01T00:00:00Z"
CLOCK_AUG_15 = "2026-08-15T00:00:00Z"
CLOCK_AUG_20 = "2026-08-20T00:00:00Z"
OBSERVED_AUG_18 = "2026-08-18T00:00:00Z"
EXCEPTION_STARTS = "2026-08-10T00:00:00Z"
EXCEPTION_ENDS = "2026-08-25T00:00:00Z"
INSIDE_WINDOW = "2026-08-18T00:00:00Z"
AFTER_WINDOW = "2026-08-26T00:00:00Z"


# --------------------------------------------------------------------------- #
# PricingPolicy
# --------------------------------------------------------------------------- #
def test_creating_a_pricing_policy_opens_it_in_draft_at_revision_one():
    """A drafted policy is born in DRAFT at revision 1 with every stamp still null.

    PRD: "The new policy is born in status `DRAFT` with `revision_number` set to 1,
    and its `effective_from`, `legal_review_notes`, `reviewed_by_user_id`,
    `published_by_user_id`, `superseded_by_policy_id` and `withdrawn_reason` all null."

    Design: Corner/endpoints/endpoint_create_pricing_policy_returns_draft_revision_one
    """
    pin_clock(CLOCK_AUG_01)
    response = api_client.create_pricing_policy(
        pricing_policy_payload(
            policy_code="MAP-2026-A",
            cure_window_days=10,
            suspension_points_threshold=6,
            termination_points_threshold=12,
            suspension_cooling_off_days=14,
        ),
        BCM_HEADERS,
    )
    policy = validate_success(response, 201)

    assert policy["status"] == "DRAFT"
    assert policy["revision_number"] == 1
    assert policy["effective_from"] is None
    assert policy["legal_review_notes"] is None
    assert policy["reviewed_by_user_id"] is None
    assert policy["published_by_user_id"] is None
    assert policy["superseded_by_policy_id"] is None
    assert policy["withdrawn_reason"] is None
    assert policy["version"] == 1


def test_submitting_a_draft_policy_hands_it_to_counsel_and_bumps_the_version():
    """Submission is a pure state move on the policy row.

    PRD: "Submission for review is available to the `BrandChannelManager` and moves
    the document `DRAFT → IN_LEGAL_REVIEW`." "The transition advances the policy's
    `version`."

    Design: Corner/endpoints/submit_policy_for_review_moves_it_to_in_legal_review
    """
    pin_clock(CLOCK_AUG_01)
    policy = create_draft_policy(policy_code="MAP-2026-A")

    updated = validate_success(api_client.submit_policy_review(policy["id"], BCM_HEADERS))

    assert updated["status"] == "IN_LEGAL_REVIEW"
    assert updated["version"] == 2


def test_an_approving_review_decision_records_the_reviewer_and_the_notes():
    """Approval records counsel's identifier and notes without touching the revision.

    PRD: "A decision of `APPROVE_FOR_PUBLICATION` moves the document
    `IN_LEGAL_REVIEW → APPROVED`: it records `legal_review_notes` and
    `reviewed_by_user_id` and advances `version`, but does **not** touch
    `revision_number`."

    Design: Corner/endpoints/review_decision_records_the_reviewer_and_notes
    """
    pin_clock(CLOCK_AUG_01)
    policy = create_policy_in_review(policy_code="MAP-2026-A")

    decided = validate_success(
        api_client.decide_policy_review(
            policy["id"],
            policy_review_decision_payload(
                "APPROVE_FOR_PUBLICATION",
                legal_review_notes="No resale price terms present",
            ),
            COUNSEL_HEADERS,
        )
    )

    assert decided["status"] == "APPROVED"
    assert decided["reviewed_by_user_id"] == "counsel-1"
    assert decided["legal_review_notes"] == "No resale price terms present"
    assert decided["revision_number"] == 1


def test_publishing_at_exactly_the_clock_instant_is_allowed_and_stamps_counsel():
    """An effective_from equal to the clock is at or after it, so publication stands.

    PRD: "The request supplies `effective_from`, which must be at or after the current
    logical clock — a policy may be scheduled forward but never backdated at
    publication." "The transition stores `effective_from`, stamps
    `published_by_user_id` with the publishing counsel's `X-User-ID`, and advances the
    policy's `version`."

    Design: Corner/endpoints/publish_requires_a_future_or_present_effective_from
    """
    pin_clock(CLOCK_AUG_01)
    policy = create_policy_in_review(policy_code="MAP-2026-A")
    approved = validate_success(
        api_client.decide_policy_review(
            policy["id"], policy_review_decision_payload("APPROVE_FOR_PUBLICATION"), COUNSEL_HEADERS
        )
    )

    published = validate_success(
        api_client.publish_policy(
            approved["id"], policy_publish_payload(CLOCK_AUG_01), COUNSEL_HEADERS
        )
    )

    assert published["status"] == "PUBLISHED"
    assert_same_instant(published["effective_from"], CLOCK_AUG_01, "effective_from")
    assert published["published_by_user_id"] == "counsel-1"
    assert published["superseded_by_policy_id"] is None


def test_withdrawing_a_policy_records_the_reason_and_cascades_to_nothing():
    """The governed product keeps its policy reference through the withdrawal.

    PRD: "Withdrawal, again by `BrandLegalCounsel`, moves a policy
    `PUBLISHED → WITHDRAWN`, recording the supplied `withdrawn_reason` and advancing
    `version`." "Withdrawal deliberately cascades to nothing: products keep their
    governing policy reference and open violations keep their citation."

    Design: Corner/endpoints/withdraw_policy_records_the_reason_without_cascading
    """
    pin_clock(CLOCK_AUG_01)
    policy = create_published_policy(CLOCK_AUG_01, policy_code="MAP-2026-A")
    product = create_product(policy["id"], sku="SKU-AUDIO-1", name="Studio Headphones")

    withdrawn = validate_success(
        api_client.withdraw_policy(
            policy["id"],
            policy_withdraw_payload(
                withdrawn_reason="Superseded by a global program redesign"
            ),
            COUNSEL_HEADERS,
        )
    )

    assert withdrawn["status"] == "WITHDRAWN"
    assert withdrawn["withdrawn_reason"] == "Superseded by a global program redesign"

    unchanged = read_product(product["id"])
    assert unchanged["governing_policy_id"] == policy["id"]
    assert unchanged["lifecycle_status"] == "ACTIVE"


def test_a_distributor_may_read_the_policy_thresholds_it_is_measured_against():
    """The single-row policy read is open to every role and echoes the stored knobs.

    PRD: "Policies may be read one at a time by every role, and the collection may be
    filtered by `status`, by `policy_code`, or by `superseded_by_policy_id` to find the
    revision a given policy displaced."

    Design: Corner/endpoints/read_one_pricing_policy_returns_its_thresholds
    """
    pin_clock(CLOCK_AUG_01)
    policy = create_published_policy(CLOCK_AUG_01, policy_code="MAP-2026-A")
    distributor = create_distributor(legal_name="Northwind Distribution")

    read = validate_success(
        api_client.get_pricing_policy(
            policy["id"], make_distributor_headers(distributor["id"])
        )
    )

    assert read["cure_window_days"] == 10
    assert read["suspension_points_threshold"] == 6
    assert read["termination_points_threshold"] == 12
    assert read["max_discount_attribution_pct"] == 0.40


def test_the_policy_collection_separates_the_published_revision_from_the_superseded_one():
    """A status filter isolates each side of the supersession cascade.

    PRD: "It also performs the supersession cascade: if any *other* policy is currently
    in status `PUBLISHED` — and by construction there is at most one — that policy moves
    `PUBLISHED → SUPERSEDED`, has its `superseded_by_policy_id` set to the newly
    published policy's `id`, and has its own `version` advanced."

    Design: Corner/endpoints/list_pricing_policies_filters_by_status_and_code
    """
    pin_clock(CLOCK_AUG_01)
    first = create_published_policy(CLOCK_AUG_01, policy_code="MAP-2026-A")
    second = create_published_policy(CLOCK_AUG_15, policy_code="MAP-2026-B")

    rows, meta = validate_paginated(
        api_client.list_pricing_policies(
            ADMIN_HEADERS,
            params={"policy_code": "MAP-2026-A", "status": "SUPERSEDED", "limit": 10, "offset": 0},
        )
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [first["id"]]
    assert rows[0]["revision_number"] == 1
    assert rows[0]["superseded_by_policy_id"] == second["id"]

    published, published_meta = validate_paginated(
        api_client.list_pricing_policies(ADMIN_HEADERS, params={"status": "PUBLISHED"})
    )
    assert published_meta["total_count"] == 1
    assert [row["id"] for row in published] == [second["id"]]

    by_code, by_code_meta = validate_paginated(
        api_client.list_pricing_policies(ADMIN_HEADERS, params={"policy_code": "MAP-2026-B"})
    )
    assert by_code_meta["total_count"] == 1
    assert [row["id"] for row in by_code] == [second["id"]]


# --------------------------------------------------------------------------- #
# Product
# --------------------------------------------------------------------------- #
def test_registering_a_product_defaults_lifecycle_clearance_depth_and_serialization():
    """The three optional product inputs fall back to their declared defaults.

    PRD: "`lifecycle_status` is the commercial stage and defaults to `ACTIVE`, with
    `CLEARANCE` and `DISCONTINUED` as its other values; it is the gate on which
    exception types may be approved." "`serialization_enabled` defaults to true and
    declares whether units of this item carry traceable serial numbers." "Every newly
    registered product starts with `open_exception_count` at 0."

    Design: Corner/endpoints/create_product_defaults_lifecycle_and_serialization
    """
    pin_clock(CLOCK_AUG_01)
    policy = create_published_policy(CLOCK_AUG_01, policy_code="MAP-2026-A")

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
        201,
    )

    assert product["lifecycle_status"] == "ACTIVE"
    assert product["clearance_discount_pct"] == 0.20
    assert product["serialization_enabled"] is True
    assert product["open_exception_count"] == 0
    assert product["msrp_cents"] == 20000


def test_adjusting_a_product_touches_only_the_fields_the_request_supplied():
    """Two of the three adjustable fields move; the standard floor keeps its value.

    PRD: "Products are adjustable in three respects by a `BrandChannelManager`:
    `lifecycle_status`, `clearance_discount_pct` and `standard_map_floor_cents` may each
    be supplied, individually or together, on an adjustment request, and the transition
    advances the product's `version`."

    Design: Corner/endpoints/patch_product_updates_only_the_supplied_fields
    """
    pin_clock(CLOCK_AUG_01)
    policy = create_published_policy(CLOCK_AUG_01, policy_code="MAP-2026-A")
    product = create_product(
        policy["id"], sku="SKU-AUDIO-1", name="Studio Headphones", msrp_cents=20000,
        standard_map_floor_cents=15000,
    )

    adjusted = validate_success(
        api_client.adjust_product(
            product["id"],
            product_adjustment_payload(lifecycle_status="CLEARANCE", clearance_discount_pct=0.25),
            BCM_HEADERS,
        )
    )

    assert adjusted["lifecycle_status"] == "CLEARANCE"
    assert adjusted["clearance_discount_pct"] == 0.25
    assert adjusted["standard_map_floor_cents"] == 15000
    assert adjusted["msrp_cents"] == 20000
    assert adjusted["version"] == product["version"] + 1


def test_reading_one_product_shows_its_raw_floor_beside_its_governing_policy():
    """The single-product read is open to every role and carries the policy foreign key.

    PRD: "Products may be read individually by every role, and the collection may be
    filtered by `governing_policy_id`, by `lifecycle_status` or by `sku`."

    Design: Corner/endpoints/read_one_product_returns_its_governing_policy
    """
    pin_clock(CLOCK_AUG_01)
    policy = create_published_policy(CLOCK_AUG_01, policy_code="MAP-2026-A")
    product = create_product(
        policy["id"], sku="SKU-AUDIO-1", name="Studio Headphones", msrp_cents=20000,
        standard_map_floor_cents=15000,
    )

    read = validate_success(api_client.get_product(product["id"], ANALYST_HEADERS))

    assert read["sku"] == "SKU-AUDIO-1"
    assert read["standard_map_floor_cents"] == 15000
    assert read["governing_policy_id"] == policy["id"]


def _setup_three_products():
    """One ACTIVE, one CLEARANCE and one unserialized ACTIVE product on one policy."""
    pin_clock(CLOCK_AUG_01)
    policy = create_published_policy(CLOCK_AUG_01, policy_code="MAP-2026-A")
    audio = create_product(
        policy["id"], sku="SKU-AUDIO-1", name="Studio Headphones", msrp_cents=20000,
        standard_map_floor_cents=15000,
    )
    clearance = create_product(
        policy["id"], sku="SKU-CLR-1", name="Legacy Turntable", msrp_cents=20000,
        standard_map_floor_cents=15000, lifecycle_status="CLEARANCE", clearance_discount_pct=0.20,
    )
    accessory = create_product(
        policy["id"], sku="SKU-NOSER-1", name="Accessory Cable", msrp_cents=5000,
        standard_map_floor_cents=4000, serialization_enabled=False,
    )
    return policy, audio, clearance, accessory


def test_the_product_collection_partitions_three_rows_across_two_pages():
    """total_count counts the matching rows before the window; has_more tracks the rest.

    PRD: "Every list response carries `limit`, `offset`, `total_count` and `has_more`
    inside `meta`: `total_count` is the number of rows matching the filters *before* the
    page window is applied, and `has_more` is true exactly when rows matching the filters
    remain beyond the current window."

    Design: Corner/endpoints/list_products_paginates_with_limit_and_offset
    """
    _policy, audio, clearance, accessory = _setup_three_products()

    first_page, first_meta = validate_paginated(
        api_client.list_products(BCM_HEADERS, params={"limit": 2, "offset": 0})
    )
    assert len(first_page) == 2
    assert first_meta["limit"] == 2
    assert first_meta["offset"] == 0
    assert first_meta["total_count"] == 3
    assert first_meta["has_more"] is True

    second_page, second_meta = validate_paginated(
        api_client.list_products(BCM_HEADERS, params={"limit": 2, "offset": 2})
    )
    assert len(second_page) == 1
    assert second_meta["total_count"] == 3
    assert second_meta["has_more"] is False

    beyond, beyond_meta = validate_paginated(
        api_client.list_products(BCM_HEADERS, params={"limit": 2, "offset": 3})
    )
    assert beyond == []
    assert beyond_meta["total_count"] == 3
    assert beyond_meta["has_more"] is False

    seen = [row["id"] for row in first_page] + [row["id"] for row in second_page]
    assert len(seen) == len(set(seen))
    assert set(seen) == {audio["id"], clearance["id"], accessory["id"]}


def test_product_filters_compose_conjunctively_across_policy_lifecycle_and_sku():
    """A lifecycle filter and an exact sku filter reach the same single row.

    PRD: "All filter parameters on a list endpoint are optional and combine
    conjunctively — supplying `status` and `reseller_id` together returns only rows
    matching both."

    Design: Corner/endpoints/list_products_filters_by_lifecycle_status_and_sku
    """
    policy, _audio, clearance, _accessory = _setup_three_products()

    rows, meta = validate_paginated(
        api_client.list_products(
            COUNSEL_HEADERS,
            params={
                "governing_policy_id": policy["id"],
                "lifecycle_status": "CLEARANCE",
                "limit": 10,
                "offset": 0,
            },
        )
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [clearance["id"]]

    by_sku, by_sku_meta = validate_paginated(
        api_client.list_products(COUNSEL_HEADERS, params={"sku": "SKU-CLR-1"})
    )
    assert by_sku_meta["total_count"] == 1
    assert [row["id"] for row in by_sku] == [clearance["id"]]

    by_policy, by_policy_meta = validate_paginated(
        api_client.list_products(COUNSEL_HEADERS, params={"governing_policy_id": policy["id"]})
    )
    assert by_policy_meta["total_count"] == 3
    assert len(by_policy) == 3


def test_the_effective_floor_read_answers_two_instants_without_mutating_the_product():
    """Inside the window the exception floor wins; outside it the standard floor does.

    PRD: "The response carries `product_id`, the echoed `channel` and `as_of`, the
    resolved `effective_map_floor_cents`, a `floor_source` of either `STANDARD` or
    `EXCEPTION`, the `applied_exception_id` of the exception that supplied the floor
    (null when the source is `STANDARD`), and the product's current
    `standard_map_floor_cents` for comparison."

    Design: Corner/endpoints/effective_floor_read_is_a_pure_computation
    """
    pin_clock(CLOCK_AUG_01)
    policy = create_published_policy(CLOCK_AUG_01, policy_code="MAP-2026-A")
    product = create_product(
        policy["id"], sku="SKU-AUDIO-1", name="Studio Headphones", msrp_cents=20000,
        standard_map_floor_cents=15000,
    )
    exception = request_exception(
        product["id"],
        exception_type="PROMOTIONAL_EVENT",
        starts_at=EXCEPTION_STARTS,
        ends_at=EXCEPTION_ENDS,
        channel_scope="ALL",
        requested_override_floor_cents=13000,
        dealer_input_source="BRAND_MARKETING_PLAN",
    )
    approve_exception(exception["id"])
    version_before = read_product(product["id"])["version"]
    reseller = validate_success(
        api_client.create_reseller(reseller_payload(legal_name="Acme Retail LLC"), BCM_HEADERS), 201
    )

    inside = validate_success(
        api_client.get_effective_floor(
            product["id"],
            make_reseller_headers(reseller["id"]),
            params={"channel": "MARKETPLACE", "as_of": INSIDE_WINDOW},
        )
    )
    assert inside["product_id"] == product["id"]
    assert inside["channel"] == "MARKETPLACE"
    assert_same_instant(inside["as_of"], INSIDE_WINDOW, "as_of")
    assert inside["effective_map_floor_cents"] == 13000
    assert inside["floor_source"] == "EXCEPTION"
    assert inside["applied_exception_id"] == exception["id"]
    assert inside["standard_map_floor_cents"] == 15000

    outside = validate_success(
        api_client.get_effective_floor(
            product["id"],
            make_reseller_headers(reseller["id"]),
            params={"channel": "MARKETPLACE", "as_of": AFTER_WINDOW},
        )
    )
    assert outside["effective_map_floor_cents"] == 15000
    assert outside["floor_source"] == "STANDARD"
    assert outside["applied_exception_id"] is None

    assert read_product(product["id"])["version"] == version_before


# --------------------------------------------------------------------------- #
# Distributor
# --------------------------------------------------------------------------- #
def test_registering_a_distributor_opens_it_in_good_standing_with_empty_ledgers():
    """Both distributor inputs are supplied; every other field is derived.

    PRD: "Every new distributor starts in `standing` `GOOD` with `diversion_score` at 0,
    `chargeback_balance_cents` at 0, `shipped_units_total` at 0 and
    `probation_entered_at` null."

    Design: Corner/endpoints/create_distributor_starts_in_good_standing
    """
    pin_clock(CLOCK_AUG_01)

    distributor = validate_success(
        api_client.create_distributor(
            {"legal_name": "Northwind Distribution", "annual_chargeback_cap_cents": 500000},
            BCM_HEADERS,
        ),
        201,
    )

    assert distributor["diversion_score"] == 0
    assert distributor["chargeback_balance_cents"] == 0
    assert distributor["shipped_units_total"] == 0
    assert distributor["standing"] == "GOOD"
    assert distributor["probation_entered_at"] is None
    assert distributor["annual_chargeback_cap_cents"] == 500000


def test_the_distributor_read_hands_back_the_version_a_chargeback_must_echo():
    """A freshly created distributor reads at version 1, the token the OCC field needs.

    PRD: "Assessing a distributor chargeback requires a non-optional
    `expected_distributor_version` field carrying the client's last observed `version` of
    the target `Distributor` row." "`version` is an integer that starts at 1 when the row
    is created and increases by exactly 1 on every mutation of that row."

    Design: Corner/endpoints/read_one_distributor_exposes_the_occ_version
    """
    pin_clock(CLOCK_AUG_01)
    distributor = create_distributor(
        legal_name="Northwind Distribution", annual_chargeback_cap_cents=500000
    )

    read = validate_success(
        api_client.get_distributor(
            distributor["id"], make_distributor_headers(distributor["id"])
        )
    )

    assert read["version"] == 1
    assert read["legal_name"] == "Northwind Distribution"
    assert read["standing"] == "GOOD"


def test_the_standing_filter_partitions_a_probation_distributor_from_a_clean_one():
    """One four-unit chargeback puts Northwind on probation while Southpaw stays good.

    PRD: "Distributors are readable one at a time and as a collection filtered by
    `standing`."

    Design: Corner/endpoints/list_distributors_filters_by_standing
    """
    pin_clock(CLOCK_AUG_01)
    policy = create_published_policy(CLOCK_AUG_01, policy_code="MAP-2026-A")
    product = create_product(
        policy["id"], sku="SKU-AUDIO-1", name="Studio Headphones", msrp_cents=20000,
        standard_map_floor_cents=15000,
    )
    northwind = create_distributor(
        legal_name="Northwind Distribution", annual_chargeback_cap_cents=500000
    )
    southpaw = create_distributor(
        legal_name="Southpaw Supply Co", annual_chargeback_cap_cents=500000
    )
    purchase, _unit, _observation = create_confirmed_trace(
        product["id"], northwind["id"], serial_number="SN-0001", lot_code="LOT-A"
    )
    chargeback = assess_chargeback(northwind["id"], purchase["id"], diverted_units=4)
    assert chargeback["score_delta_applied"] == score_delta(4) == 10.0
    assert standing_for_score(10.0) == "PROBATION"

    rows, meta = validate_paginated(
        api_client.list_distributors(
            ADMIN_HEADERS, params={"standing": "PROBATION", "limit": 10, "offset": 0}
        )
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [northwind["id"]]

    good, good_meta = validate_paginated(
        api_client.list_distributors(ADMIN_HEADERS, params={"standing": "GOOD"})
    )
    assert good_meta["total_count"] == 1
    assert [row["id"] for row in good] == [southpaw["id"]]

    everyone, everyone_meta = validate_paginated(api_client.list_distributors(ADMIN_HEADERS))
    assert everyone_meta["total_count"] == 2
    assert len(everyone) == 2


def test_the_diversion_exposure_read_echoes_the_variant_beside_the_tier_it_used():
    """One traced unit at score 0 is exposed at the bottom tier rate.

    PRD: "The response reports `distributor_id`, the echoed `variant`, the
    `traced_unit_count` of this distributor's own units in `TRACED_UNAUTHORIZED`, the
    `units_counted` the chosen variant arrived at (a whole number under
    `TRACE_ATTRIBUTED`, a two-decimal figure under `LOT_PRORATED`), the resulting
    `exposure_cents`, the `tier_rate_cents_per_unit` used, and the `diversion_score` the
    tier was read from."

    Design: Corner/endpoints/diversion_exposure_read_requires_the_variant_selector
    """
    pin_clock(CLOCK_AUG_01)
    policy = create_published_policy(CLOCK_AUG_01, policy_code="MAP-2026-A")
    product = create_product(
        policy["id"], sku="SKU-AUDIO-1", name="Studio Headphones", msrp_cents=20000,
        standard_map_floor_cents=15000,
    )
    distributor = create_distributor(
        legal_name="Northwind Distribution", annual_chargeback_cap_cents=500000
    )
    create_confirmed_trace(
        product["id"], distributor["id"], serial_number="SN-0001", lot_code="LOT-A"
    )

    exposure = validate_success(
        api_client.get_diversion_exposure(
            distributor["id"], ANALYST_HEADERS, params={"variant": "TRACE_ATTRIBUTED"}
        )
    )

    assert exposure["distributor_id"] == distributor["id"]
    assert exposure["variant"] == "TRACE_ATTRIBUTED"
    assert exposure["diversion_score"] == 0
    assert exposure["tier_rate_cents_per_unit"] == tier_rate_for_score(0) == 2500
    assert exposure["traced_unit_count"] == 1
    assert exposure["units_counted"] == 1
    assert exposure["exposure_cents"] == 2500


# --------------------------------------------------------------------------- #
# Reseller
# --------------------------------------------------------------------------- #
def test_a_reseller_application_carries_its_optional_sourcing_link_into_applied_hold():
    """The sourcing distributor is stored while both axes open at their initial pair.

    PRD: "A newly recorded reseller starts with `authorization_status` `APPLIED`,
    `supply_status` `HOLD`, `hold_reason` `PENDING_AUTHORIZATION`,
    `violation_points_total` at 0 and `review_required` evaluated once at creation (which
    for a fresh row means false unless the named sourcing distributor is already in
    `PROBATION` or `SUSPENDED`)."

    Design: Corner/endpoints/create_reseller_links_the_optional_sourcing_distributor
    """
    pin_clock(CLOCK_AUG_01)
    distributor = create_distributor(
        legal_name="Northwind Distribution", annual_chargeback_cap_cents=500000
    )

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
        201,
    )

    assert reseller["authorization_status"] == "APPLIED"
    assert reseller["supply_status"] == "HOLD"
    assert reseller["hold_reason"] == "PENDING_AUTHORIZATION"
    assert reseller["sourcing_distributor_id"] == distributor["id"]
    assert reseller["review_required"] is False
    assert reseller["violation_points_total"] == 0


def test_a_quality_hold_moves_the_supply_axis_and_leaves_authorization_alone():
    """The supply track is driven on its own route without disturbing the contract.

    PRD: "Placing an `OPEN` reseller on hold moves `OPEN → HOLD` with `hold_reason` set
    to `QUALITY_OBLIGATION`, requires the reseller's `authorization_status` not to be
    `TERMINATED`, and advances the reseller's `version`; the authorization axis is
    untouched, so a reseller sitting on a quality hold is still `AUTHORIZED`."

    Design: Corner/endpoints/supply_status_endpoint_sets_hold_reason_and_note
    """
    pin_clock(CLOCK_AUG_01)
    policy = create_published_policy(CLOCK_AUG_01, policy_code="MAP-2026-A")
    reseller, _agreement = create_authorized_reseller(
        policy["id"],
        reseller_overrides={"legal_name": "Acme Retail LLC", "primary_channel": "MARKETPLACE"},
        agreement_overrides={"permitted_channels": ["MARKETPLACE", "OWN_WEBSITE"]},
    )
    assert reseller["supply_status"] == "OPEN"

    held = validate_success(
        api_client.set_supply_status(
            reseller["id"],
            supply_status_payload(
                "HOLD",
                hold_reason="QUALITY_OBLIGATION",
                note="Authenticity labeling audit failed",
            ),
            BCM_HEADERS,
        )
    )

    assert held["supply_status"] == "HOLD"
    assert held["hold_reason"] == "QUALITY_OBLIGATION"
    assert held["authorization_status"] == "AUTHORIZED"
    assert held["version"] == reseller["version"] + 1


def test_the_reseller_read_reflects_the_agreement_cascade_in_its_version():
    """Send and activate each advance the reseller, so an authorized row reads version 3.

    PRD: "Activation stamps `activated_at` with the current clock and advances the
    agreement's `version`, and it moves the reseller on both axes at once:
    `authorization_status` to `AUTHORIZED`, `supply_status` to `OPEN`, `hold_reason` to
    `NONE`, with the reseller's `version` advanced."

    Design: Corner/endpoints/read_one_reseller_exposes_the_occ_version
    """
    pin_clock(CLOCK_AUG_01)
    policy = create_published_policy(CLOCK_AUG_01, policy_code="MAP-2026-A")
    reseller, _agreement = create_authorized_reseller(
        policy["id"],
        reseller_overrides={"legal_name": "Acme Retail LLC", "primary_channel": "MARKETPLACE"},
        agreement_overrides={"permitted_channels": ["MARKETPLACE", "OWN_WEBSITE"]},
    )

    read = validate_success(
        api_client.get_reseller(reseller["id"], make_reseller_headers(reseller["id"]))
    )

    assert read["authorization_status"] == "AUTHORIZED"
    assert read["supply_status"] == "OPEN"
    assert read["hold_reason"] == "NONE"
    assert read["version"] == 3


def test_the_derived_review_flag_is_a_first_class_reseller_list_filter():
    """A traced downstream unit raises the flag on one reseller and not the other.

    PRD: "Resellers are readable individually and as a collection filtered by
    `sourcing_distributor_id`, `authorization_status`, `supply_status` or
    `review_required`."

    Design: Corner/endpoints/list_resellers_filters_on_the_derived_review_flag
    """
    pin_clock(CLOCK_AUG_01)
    policy = create_published_policy(CLOCK_AUG_01, policy_code="MAP-2026-A")
    product = create_product(
        policy["id"], sku="SKU-AUDIO-1", name="Studio Headphones", msrp_cents=20000,
        standard_map_floor_cents=15000,
    )
    acme, _acme_agreement = create_authorized_reseller(
        policy["id"],
        reseller_overrides={"legal_name": "Acme Retail LLC", "primary_channel": "MARKETPLACE"},
        agreement_overrides={"permitted_channels": ["MARKETPLACE", "OWN_WEBSITE"]},
    )
    bravo, _bravo_agreement = create_authorized_reseller(
        policy["id"],
        reseller_overrides={"legal_name": "Bravo Outlets Inc", "primary_channel": "RETAILER_SITE"},
        agreement_overrides={"permitted_channels": ["RETAILER_SITE"]},
    )
    distributor = create_distributor(
        legal_name="Northwind Distribution", annual_chargeback_cap_cents=500000
    )
    create_confirmed_trace(
        product["id"],
        distributor["id"],
        downstream_reseller_id=acme["id"],
        serial_number="SN-0002",
        lot_code="LOT-A",
    )
    assert read_reseller(acme["id"])["review_required"] is True

    flagged, flagged_meta = validate_paginated(
        api_client.list_resellers(
            BCM_HEADERS, params={"review_required": True, "limit": 10, "offset": 0}
        )
    )
    assert flagged_meta["total_count"] == 1
    assert [row["id"] for row in flagged] == [acme["id"]]

    clean, clean_meta = validate_paginated(
        api_client.list_resellers(BCM_HEADERS, params={"review_required": False})
    )
    assert clean_meta["total_count"] == 1
    assert [row["id"] for row in clean] == [bravo["id"]]

    authorized, authorized_meta = validate_paginated(
        api_client.list_resellers(BCM_HEADERS, params={"authorization_status": "AUTHORIZED"})
    )
    assert authorized_meta["total_count"] == 2

    open_supply, open_meta = validate_paginated(
        api_client.list_resellers(BCM_HEADERS, params={"supply_status": "OPEN"})
    )
    assert open_meta["total_count"] == 2


def test_the_compliance_summary_reconciles_the_ledger_and_reports_both_gaps():
    """At three points the summary reproduces the ledger and the distance to each rung.

    PRD: "It reports `reseller_id`, the stored `violation_points_total`, the
    `contributing_violation_count` of violations that qualify under the ledger definition
    of §2.11, the `summed_assessed_points` obtained by adding up those violations'
    `assessed_points` — which must equal the stored total, since that is the whole point
    of the read — the `highest_issued_rung` served so far (reported as the empty-history
    case when no non-rescinded notice exists), the `next_rung` the ladder would install
    on the next notice, and the two gaps `points_to_suspension` and
    `points_to_termination`, each being the reseller's own governing thresholds minus the
    current total, floored at zero when the threshold has already been passed."

    Design: Corner/endpoints/compliance_summary_read_projects_the_ladder_position
    """
    pin_clock(CLOCK_AUG_01)
    policy = create_published_policy(CLOCK_AUG_01, policy_code="MAP-2026-A")
    product = create_product(
        policy["id"], sku="SKU-AUDIO-1", name="Studio Headphones", msrp_cents=20000,
        standard_map_floor_cents=15000,
    )
    reseller, _agreement = create_authorized_reseller(
        policy["id"],
        reseller_overrides={"legal_name": "Acme Retail LLC", "primary_channel": "MARKETPLACE"},
        agreement_overrides={"permitted_channels": ["MARKETPLACE", "OWN_WEBSITE"]},
    )
    pin_clock(CLOCK_AUG_20)
    notice, _violation = issue_warning(
        product["id"],
        reseller["id"],
        listed_price_cents=14000,
        observed_at=OBSERVED_AUG_18,
        listing_url="https://mkt.example/l/1",
    )
    assert notice["assessed_points"] == violation_points(15000, 14000, "MARKETPLACE", 0) == 3

    summary = validate_success(
        api_client.get_compliance_summary(
            reseller["id"],
            make_reseller_headers(reseller["id"]),
            params={"as_of": CLOCK_AUG_20},
        )
    )

    assert summary["reseller_id"] == reseller["id"]
    assert summary["violation_points_total"] == 3
    assert summary["contributing_violation_count"] == 1
    assert summary["summed_assessed_points"] == 3
    assert summary["highest_issued_rung"] == "WARNING"
    assert summary["points_to_suspension"] == 3
    assert summary["points_to_termination"] == 9
