"""Read surfaces of the brand-protection API: computed metrics, list filters,
the released-seizure branch and the immediacy of derived state.

Every test builds its own world from an empty database and asserts only what
PRD.md states.
"""

from test_helpers import (
    CLAIM_STATUS_DRAFT,
    CUSTOMS_AUTHORITY_US_CBP,
    ENFORCEMENT_STATUS_NONE,
    INVESTIGATION_STATUS_OPEN,
    INVESTIGATION_STATUS_RELEASED,
    MONITOR_STATUS_CLEARED,
    MONITOR_STATUS_FLAGGED,
    MONITOR_STATUS_NEW,
    RECORDATION_STATUS_RECORDED,
    SELLER_STATUS_ACTIVE,
    TEST_BUY_STATUS_ORDERED,
    TEST_USERS,
    VIOLATION_TYPE_COUNTERFEIT,
    VIOLATION_TYPE_NONE,
    assertions,
    factories,
    fixtures,
    is_iso8601_timestamp,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["brand_administrator_headers"]
ANALYST = TEST_USERS["enforcement_analyst_headers"]
LIAISON = TEST_USERS["marketplace_liaison_headers"]
CUSTOMS = TEST_USERS["customs_coordinator_headers"]
COUNSEL = TEST_USERS["legal_counsel_headers"]


def test_enforcement_metrics_read_after_a_single_removal_is_pure(api):
    """One approved removal gives a removal rate of 1.0000 and persists nothing.

    The only decided notice is the removed one, the seller's single 12.55-point
    strike leaves it below the repeat-infringer threshold, no case was ever
    opened and no test buy was ordered, so every counter is pinned. Reading the
    scorecard twice, under two different roles, must not touch the brand row.

    PRD §3.11: "A computed read on a brand, available to `BrandAdministrator`, `EnforcementAnalyst` and `LegalCounsel`, derives the brand's enforcement scorecard on the fly and persists nothing."
    PRD §3.11: "`decided_takedown_count` counts those takedowns whose `status` is `APPROVED_REMOVED`, `REJECTED` or `REINSTATED`."
    PRD §3.11: "`removed_takedown_count` counts those whose `status` is `APPROVED_REMOVED`."
    PRD §3.11: "`listing_removal_rate` is `removed_takedown_count` divided by `decided_takedown_count`, rounded to four decimal places using ROUND_HALF_UP."
    PRD §3.11: "`repeat_infringer_count` counts cluster roots — never alias rows — whose `cluster_strike_points` has reached 25.00 and that have at least one strike attributable to this brand somewhere in the cluster."
    PRD §3.11: "`open_case_count` counts enforcement cases of this brand whose `case_status` is `OPEN` or `IN_LITIGATION`; `CLOSED` cases are excluded."
    PRD §3.11: "`enforcement_spend_cents` is read straight off the brand row, exactly as accumulated by the test buy programme of §3.6."
    PRD §3.3: "A **takedown removal** strike carries a base of 12.55 points."
    PRD §3.3: "At a cluster total of 60.00 or more the seller is `BLOCKED`; at a cluster total of at least 25.00 but below 60.00 the seller is `UNDER_INVESTIGATION`; below 25.00 the seller is `ACTIVE`."
    Design: Corner/endpoints/enforcement_metrics_computed_read_after_a_single_removal
    """
    ctx = fixtures.setup_removed_takedown(api, clock="2026-08-05T09:00:00Z")
    brand_id = ctx["brand"]["id"]

    seller = fixtures.read_seller(api, ctx["seller"]["id"])
    assertions.assert_seller_strikes(seller, 12.55, 12.55, SELLER_STATUS_ACTIVE)

    brand_before = fixtures.read_brand(api, brand_id)

    first = validate_success(api.get_enforcement_metrics(brand_id, headers=ADMIN), 200)
    assertions.assert_metrics(
        first,
        listing_removal_rate=1.0000,
        decided_takedown_count=1,
        removed_takedown_count=1,
        repeat_infringer_count=0,
        open_case_count=0,
        enforcement_spend_cents=0,
    )

    second = validate_success(api.get_enforcement_metrics(brand_id, headers=COUNSEL), 200)
    assert second == first, f"Expected an identical scorecard on re-read, got {second} then {first}"

    brand_after = fixtures.read_brand(api, brand_id)
    assertions.assert_unchanged(brand_before, brand_after)
    assertions.assert_cents(brand_after["enforcement_spend_cents"], 0, "enforcement_spend_cents")


def test_listing_index_filters_on_each_state_dimension_and_pages_stably(api):
    """Three listings in three screening states separate by filter and paginate.

    A never-screened listing stays NEW with null matcher output, a listing
    priced above the authorized MSRP clears at 0.0800, and a deeply discounted
    close match flags at 0.8620. Filters combine conjunctively and total_count
    keeps reporting the unpaged size.

    PRD §3.4: "Listings are readable individually and listable with optional filters on `brand_id`, `seller_id`, `marketplace_code`, `monitor_status`, `enforcement_status` and `violation_type`."
    PRD §2.3: "Every filter documented for a list endpoint in §3 and §4 is optional, and filters combine conjunctively: a request supplying two filters returns only rows matching both."
    PRD §2.3: "`total_count` is the number of rows matching the request's filters before the page window is applied, and `has_more` is true exactly when rows matching the filters remain beyond the current window."
    PRD §3.4: "A new listing starts with `monitor_status` `NEW`, `enforcement_status` `NONE`, `violation_type` `NONE`, and `image_match_score`, `text_match_score`, `price_deviation_factor` and `match_score` all null until the first screening."
    PRD §3.4: "A reference of 10000 cents against a price of 3000 cents gives 0.7000; against a price of 9500 cents it gives 0.0500; against a price of 12000 cents it gives 0.0000."
    PRD §3.4: "Second, three weighted terms are accumulated at full precision, with weights that sum to exactly 1.00: the image sub-score contributes forty-five hundredths of its value, the text sub-score contributes thirty-five hundredths of its value, and the price deviation factor contributes twenty hundredths of its value."
    PRD §3.4: "Fourth, the weighted sum plus the boost is capped at 1.0000 and then rounded half-up, exactly once, to four decimal places."
    PRD §3.4: "Fifth, the verdict: if `match_score` is at least 0.7000 the listing's `monitor_status` becomes `FLAGGED`, and otherwise it becomes `CLEARED`."
    PRD §3.4: "Otherwise, if `image_match_score` is at least 0.85, `violation_type` is `COUNTERFEIT`."
    PRD §3.4: "`violation_type` is always `NONE` whenever `monitor_status` is `NEW` or `CLEARED`."
    Design: Corner/endpoints/listing_index_filters_on_each_state_dimension_and_pages_stably
    """
    fixtures.set_clock(api, "2026-08-05T09:00:00Z")
    brand = fixtures.create_brand(api, authorized_msrp_cents=10000)
    seller_a = fixtures.create_seller(api)
    seller_b = fixtures.create_seller(api)

    never_screened = fixtures.create_listing(api, brand["id"], seller_a["id"], price_cents=9500)
    cleared = fixtures.create_listing(api, brand["id"], seller_a["id"], price_cents=12000)
    fixtures.screen_listing(api, cleared["id"], 0.10, 0.10)
    flagged = fixtures.create_listing(api, brand["id"], seller_b["id"], price_cents=3000)
    fixtures.screen_listing(api, flagged["id"], 0.92, 0.88)

    rows, meta = validate_paginated(
        api.list_listings(headers=LIAISON, brand_id=brand["id"], monitor_status=MONITOR_STATUS_FLAGGED))
    assert meta["total_count"] == 1, f"Expected total_count 1, got {meta['total_count']}"
    assert [row["id"] for row in rows] == [flagged["id"]], (
        f"Expected only {flagged['id']}, got {[row['id'] for row in rows]}")
    assertions.assert_listing_screening(
        rows[0], 0.92, 0.88, 0.7000, 0.8620, MONITOR_STATUS_FLAGGED, VIOLATION_TYPE_COUNTERFEIT)

    new_row = fixtures.read_listing(api, never_screened["id"])
    assert new_row["monitor_status"] == MONITOR_STATUS_NEW, (
        f"Expected monitor_status {MONITOR_STATUS_NEW}, got {new_row['monitor_status']}")
    assert new_row["enforcement_status"] == ENFORCEMENT_STATUS_NONE, (
        f"Expected enforcement_status {ENFORCEMENT_STATUS_NONE}, got {new_row['enforcement_status']}")
    assert new_row["violation_type"] == VIOLATION_TYPE_NONE, (
        f"Expected violation_type {VIOLATION_TYPE_NONE}, got {new_row['violation_type']}")
    for field in ("image_match_score", "text_match_score", "price_deviation_factor", "match_score"):
        assert new_row[field] is None, f"Expected {field} null before the first screening, got {new_row[field]}"

    cleared_row = fixtures.read_listing(api, cleared["id"])
    assertions.assert_listing_screening(
        cleared_row, 0.10, 0.10, 0.0000, 0.0800, MONITOR_STATUS_CLEARED, VIOLATION_TYPE_NONE)
    assert cleared_row["enforcement_status"] == ENFORCEMENT_STATUS_NONE, (
        f"Expected enforcement_status {ENFORCEMENT_STATUS_NONE}, got {cleared_row['enforcement_status']}")

    unpaged, unpaged_meta = validate_paginated(
        api.list_listings(headers=LIAISON, brand_id=brand["id"],
                          enforcement_status=ENFORCEMENT_STATUS_NONE))
    assert unpaged_meta["total_count"] == 3, f"Expected total_count 3, got {unpaged_meta['total_count']}"
    assert len(unpaged) == 3, f"Expected 3 rows, got {len(unpaged)}"
    assert unpaged_meta["has_more"] is False, f"Expected has_more False, got {unpaged_meta['has_more']}"

    page, page_meta = validate_paginated(
        api.list_listings(headers=LIAISON, brand_id=brand["id"],
                          enforcement_status=ENFORCEMENT_STATUS_NONE, limit=1, offset=1))
    assert page_meta["total_count"] == 3, (
        f"Expected total_count 3 before the page window, got {page_meta['total_count']}")
    assert page_meta["has_more"] is True, f"Expected has_more True, got {page_meta['has_more']}"
    assert len(page) == 1, f"Expected 1 row, got {len(page)}"
    assert page[0]["id"] == unpaged[1]["id"], (
        f"Expected the second row of the same ordering {unpaged[1]['id']}, got {page[0]['id']}")

    seller_rows, seller_meta = validate_paginated(
        api.list_listings(headers=LIAISON, seller_id=seller_a["id"],
                          violation_type=VIOLATION_TYPE_NONE))
    assert seller_meta["total_count"] == 2, f"Expected total_count 2, got {seller_meta['total_count']}"
    returned = {row["id"] for row in seller_rows}
    assert returned == {never_screened["id"], cleared["id"]}, (
        f"Expected {never_screened['id']} and {cleared['id']}, got {returned}")
    assert flagged["id"] not in returned, "The other seller's flagged listing must not appear"


def test_released_seizure_concludes_straight_from_open_without_a_strike(api):
    """A detention released from OPEN attributes no strike and opens no case.

    The investigation never passes through EVIDENCE_SUBMITTED: the coordinator
    releases it directly, which is a legitimate terminal outcome. The named
    shipper must keep a clean ledger and the brand must still have no case.

    PRD §3.10: "`RELEASED` is reachable from either `EVIDENCE_SUBMITTED` or directly from `OPEN` — a detention may be released without the brand ever having answered it."
    PRD §3.10: "No strike is attributed and no case is created on this branch."
    PRD §3.10: "Both outcomes stamp `concluded_at` from the logical clock, persist `findings_ref` and increment `version` by 1, and both are terminal."
    PRD §3.3: "A new seller row starts with `status` `ACTIVE`, `canonical_seller_id` null, and both `standalone_strike_points` and `cluster_strike_points` at 0.00."
    PRD §3.3: "At a cluster total of 60.00 or more the seller is `BLOCKED`; at a cluster total of at least 25.00 but below 60.00 the seller is `UNDER_INVESTIGATION`; below 25.00 the seller is `ACTIVE`."
    Design: Corner/endpoints/released_seizure_concludes_straight_from_open_without_a_strike
    """
    fixtures.set_clock(api, "2026-08-05T08:00:00Z")
    brand = fixtures.create_brand(api)
    registration = fixtures.create_registration(api, brand["id"])
    recordation = fixtures.create_recorded_recordation(
        api, brand["id"], registration["id"], "CBP-7001",
        customs_authority_code=CUSTOMS_AUTHORITY_US_CBP)
    assert recordation["status"] == RECORDATION_STATUS_RECORDED, (
        f"Expected recordation status {RECORDATION_STATUS_RECORDED}, got {recordation['status']}")

    seller = fixtures.create_seller(api)
    investigation = fixtures.create_border_seizure_investigation(
        api, brand["id"], recordation["id"], seller_id=seller["id"], lot_code="LOT-REL-1")
    assert investigation["status"] == INVESTIGATION_STATUS_OPEN, (
        f"Expected investigation status {INVESTIGATION_STATUS_OPEN}, got {investigation['status']}")

    concluded = validate_success(
        api.conclude_investigation(investigation["id"], INVESTIGATION_STATUS_RELEASED, "FIND-REL-1",
                                   headers=CUSTOMS), 200)
    assert concluded["status"] == INVESTIGATION_STATUS_RELEASED, (
        f"Expected status {INVESTIGATION_STATUS_RELEASED}, got {concluded['status']}")
    assert concluded["findings_ref"] == "FIND-REL-1", (
        f"Expected findings_ref FIND-REL-1, got {concluded['findings_ref']}")
    assert is_iso8601_timestamp(concluded["concluded_at"]), (
        f"Expected an ISO 8601 concluded_at, got {concluded['concluded_at']}")
    assert concluded["concluded_at"].startswith("2026-08-05T08:00:00"), (
        f"Expected concluded_at stamped from the logical clock, got {concluded['concluded_at']}")
    assert concluded["version"] == investigation["version"] + 1, (
        f"Expected version {investigation['version'] + 1}, got {concluded['version']}")

    settled_seller = fixtures.read_seller(api, seller["id"])
    assertions.assert_seller_strikes(settled_seller, 0.00, 0.00, SELLER_STATUS_ACTIVE)

    cases, case_meta = validate_paginated(api.list_cases(headers=COUNSEL, brand_id=brand["id"]))
    assert case_meta["total_count"] == 0, (
        f"Expected no case on the released branch, got {case_meta['total_count']}")
    assert cases == [], f"Expected an empty case index, got {cases}"

    still_recorded = validate_success(api.get_recordation(recordation["id"], headers=CUSTOMS), 200)
    assert still_recorded["status"] == RECORDATION_STATUS_RECORDED, (
        f"Expected the recordation to stay {RECORDATION_STATUS_RECORDED}, got {still_recorded['status']}")


def test_test_buy_create_response_already_carries_the_ledger_effect(api):
    """Ordering a covert purchase returns the priced order and the moved ledger.

    A subtotal of 5500 cents sits in the second fee band at 0.12, giving a fee
    of 660 cents and a billable total of 6160 cents. That total must already be
    on the brand's ledger by the time the 201 is read back, with no second
    request needed to settle it.

    PRD §2.8: "Consistency is immediate; there is no deferred queue."
    PRD §3.6: "The order lands in status `ORDERED`, its `ordered_at` is stamped from the logical clock, and its `seller_id` is *copied* at creation from the claim's listing rather than supplied, so that the cooling period can be evaluated per seller."
    PRD §3.6: "The three supplied amounts are added together to give `subtotal_cents`."
    PRD §3.6: "A `service_fee_rate` is then selected from `subtotal_cents` **alone**, on an inclusive-upper-bound ladder: a subtotal of 5000 cents or less takes a rate of 0.15, a subtotal above that but no more than 20000 cents takes 0.12, a subtotal above that but no more than 50000 cents takes 0.09, and anything above 50000 cents takes 0.06."
    PRD §3.6: "`service_fee_cents` is that rate applied to `subtotal_cents` and rounded half-up to a whole number of cents."
    PRD §3.6: "`billable_total_cents` is `subtotal_cents` plus `service_fee_cents`."
    PRD §3.6: "Otherwise `billable_total_cents` is added to the brand's `enforcement_spend_cents` and the brand's `version` is incremented by 1."
    Design: Corner/consistency_model/the_mutating_response_already_carries_the_ledger_effect
    """
    fixtures.set_clock(api, "2026-08-05T09:00:00Z")
    brand = fixtures.create_brand(api, authorized_msrp_cents=10000)
    registration = fixtures.create_registration(api, brand["id"])
    seller = fixtures.create_seller(api)
    listing = fixtures.create_listing(api, brand["id"], seller["id"], price_cents=3000)
    fixtures.screen_listing(api, listing["id"], 0.92, 0.88)
    claim = fixtures.create_claim(api, brand["id"], listing["id"], registration["id"],
                                 claimed_violation_type=VIOLATION_TYPE_COUNTERFEIT)

    brand_before = fixtures.read_brand(api, brand["id"])
    assertions.assert_cents(brand_before["enforcement_spend_cents"], 0, "enforcement_spend_cents")

    ordered = validate_success(
        api.create_test_buy(claim["id"], factories.test_buy_payload(3000, 500, 2000),
                            headers=ANALYST), 201)

    assert ordered["status"] == TEST_BUY_STATUS_ORDERED, (
        f"Expected status {TEST_BUY_STATUS_ORDERED}, got {ordered['status']}")
    assert ordered["seller_id"] == seller["id"], (
        f"Expected seller_id copied from the claim's listing {seller['id']}, got {ordered['seller_id']}")
    assert is_iso8601_timestamp(ordered["ordered_at"]), (
        f"Expected an ISO 8601 ordered_at, got {ordered['ordered_at']}")
    assert ordered["ordered_at"].startswith("2026-08-05T09:00:00"), (
        f"Expected ordered_at stamped from the logical clock, got {ordered['ordered_at']}")
    assertions.assert_cents(ordered["subtotal_cents"], 5500, "subtotal_cents")
    assertions.assert_score_2dp(ordered["service_fee_rate"], 0.12, "service_fee_rate")
    assertions.assert_cents(ordered["service_fee_cents"], 660, "service_fee_cents")
    assertions.assert_cents(ordered["billable_total_cents"], 6160, "billable_total_cents")

    brand_after = fixtures.read_brand(api, brand["id"])
    assertions.assert_cents(brand_after["enforcement_spend_cents"], 6160, "enforcement_spend_cents")
    assert brand_after["version"] == brand_before["version"] + 1, (
        f"Expected brand version {brand_before['version'] + 1}, got {brand_after['version']}")

    untouched_listing = fixtures.read_listing(api, listing["id"])
    assertions.assert_score_4dp(untouched_listing["match_score"], 0.8620, "match_score")
    untouched_claim = fixtures.read_claim(api, claim["id"])
    assert untouched_claim["status"] == CLAIM_STATUS_DRAFT, (
        f"Expected the claim to stay {CLAIM_STATUS_DRAFT}, got {untouched_claim['status']}")
