"""Optimistic concurrency on the three shared parents, the strike ladder under
repeated border diversions, and the not-found code each entity family owns.
"""

from test_helpers import (
    ApiErrorId,
    BRAND_STATUS_ENROLLMENT_PENDING,
    CASE_STATUS_OPEN,
    CLAIM_STATUS_SUBSTANTIATED,
    CORRESPONDENCE_NONE,
    CUSTOMS_AUTHORITY_US_CBP,
    ENROLLMENT_STATUS_SUBMITTED,
    INVESTIGATION_STATUS_DIVERSION_CONFIRMED,
    INVESTIGATION_STATUS_EVIDENCE_SUBMITTED,
    LITIGATION_NONE,
    MARKETPLACE_AMZ,
    MARKETPLACE_EBY,
    MONITOR_STATUS_NEW,
    NON_EXISTENT_UUID,
    PACKAGE_STATUS_ASSEMBLING,
    SELLER_STATUS_ACTIVE,
    SELLER_STATUS_BLOCKED,
    SELLER_STATUS_UNDER_INVESTIGATION,
    TEST_USERS,
    assertions,
    factories,
    fixtures,
    is_iso8601_timestamp,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["brand_administrator_headers"]
ANALYST = TEST_USERS["enforcement_analyst_headers"]
LIAISON = TEST_USERS["marketplace_liaison_headers"]
CUSTOMS = TEST_USERS["customs_coordinator_headers"]
COUNSEL = TEST_USERS["legal_counsel_headers"]


def test_enrollment_create_with_a_stale_brand_version_returns_412(api):
    """A second enrolment quoting the pre-enrolment brand version is refused.

    The first enrolment advances the brand's version, so the client's remembered
    value is stale. Only the stale premise is at fault: the same create on a
    different marketplace succeeds once the current version is quoted.

    PRD §2.7: "Enrolling a brand in a marketplace registry pins that brand's portfolio and its `authorized_msrp_cents` into the enrolment decision, so the create requires `expected_brand_version` carrying the client's last observed `version` of the target brand."
    PRD §2.7: "If another writer has advanced the brand's `version` since the client read it, the create is rejected with `ERR_STALE_BRAND_VERSION` (HTTP 412)."
    PRD §2.7: "Quoting the brand's current `version` instead returns 201 and increments the brand's `version` by 1."
    PRD §2.7: "The refusal is caused only by the stale premise: a brand may hold one active enrolment per marketplace, so a second enrolment create that quotes the current brand `version` and names a different `marketplace_code` succeeds normally."
    PRD §3.2: "The new row lands in `enrollment_status` `SUBMITTED` with `activated_at`, `suspension_reason_code` and `superseded_by_enrollment_id` all null, and the owning brand's posture is immediately re-derived, which increments the brand's `version` by 1."
    PRD §3.1: "Otherwise, if any enrolment of the brand is `SUBMITTED`, the brand is `ENROLLMENT_PENDING`."
    Design: Corner/cross_cutting_complexity_layers/enrollment_create_with_a_stale_brand_version_returns_412
    """
    brand = fixtures.create_brand(api)
    registration = fixtures.create_registration(api, brand["id"])
    observed_version = fixtures.read_brand(api, brand["id"])["version"]

    first = validate_success(
        api.create_enrollment(
            factories.enrollment_payload(brand["id"], registration["id"], observed_version,
                                        marketplace_code=MARKETPLACE_AMZ), headers=ADMIN), 201)
    assert first["enrollment_status"] == ENROLLMENT_STATUS_SUBMITTED, (
        f"Expected enrollment_status {ENROLLMENT_STATUS_SUBMITTED}, got {first['enrollment_status']}")

    after_first = fixtures.read_brand(api, brand["id"])
    assert after_first["version"] == observed_version + 1, (
        f"Expected brand version {observed_version + 1}, got {after_first['version']}")
    assert after_first["status"] == BRAND_STATUS_ENROLLMENT_PENDING, (
        f"Expected brand status {BRAND_STATUS_ENROLLMENT_PENDING}, got {after_first['status']}")

    validate_error(
        api.create_enrollment(
            factories.enrollment_payload(brand["id"], registration["id"], observed_version,
                                        marketplace_code=MARKETPLACE_EBY), headers=ADMIN),
        ApiErrorId.STALE_BRAND_VERSION)

    rows, meta = validate_paginated(api.list_enrollments(headers=ADMIN, brand_id=brand["id"]))
    assert meta["total_count"] == 1, (
        f"Expected the refused create to persist nothing, got {meta['total_count']} enrolments")
    assert rows[0]["id"] == first["id"], f"Expected only {first['id']}, got {rows[0]['id']}"
    assertions.assert_unchanged(after_first, fixtures.read_brand(api, brand["id"]))

    retried = validate_success(
        api.create_enrollment(
            factories.enrollment_payload(brand["id"], registration["id"], after_first["version"],
                                        marketplace_code=MARKETPLACE_EBY), headers=ADMIN), 201)
    assert retried["enrollment_status"] == ENROLLMENT_STATUS_SUBMITTED, (
        f"Expected enrollment_status {ENROLLMENT_STATUS_SUBMITTED}, got {retried['enrollment_status']}")
    assert retried["marketplace_code"] == MARKETPLACE_EBY, (
        f"Expected marketplace_code {MARKETPLACE_EBY}, got {retried['marketplace_code']}")

    after_retry = fixtures.read_brand(api, brand["id"])
    assert after_retry["version"] == after_first["version"] + 1, (
        f"Expected brand version {after_first['version'] + 1}, got {after_retry['version']}")
    assertions.assert_unchanged(
        first, validate_success(api.get_enrollment(first["id"], headers=ADMIN), 200))


def test_evidence_package_create_with_a_stale_claim_version_returns_412(api):
    """A second package quoting the pre-package claim version is refused.

    Opening the first package advances the claim's version. A claim legitimately
    holds several packages, so the same create succeeds against the refreshed
    version, and the claim's substantiation posture is untouched throughout.

    PRD §2.7: "The create therefore requires `expected_claim_version` carrying the client's last observed `version` of the parent claim, and a mismatch with the claim's current `version` is rejected with `ERR_STALE_CLAIM_VERSION` (HTTP 412)."
    PRD §2.7: "Quoting the current value returns 201 and increments the claim's `version` by 1."
    PRD §2.7: "Again only the stale premise is refused: a claim legitimately holds several packages, so a second package create quoting the current claim `version` succeeds."
    PRD §3.7: "The package lands in status `ASSEMBLING` with an empty `items` array, `item_count` 0, `required_type_coverage` 0, `completeness_score` 0.0000 and `sealed_at` null; the parent claim's `version` is incremented by 1."
    Design: Corner/cross_cutting_complexity_layers/evidence_package_create_with_a_stale_claim_version_returns_412
    """
    ctx = fixtures.setup_substantiated_claim(api, clock="2026-08-05T08:00:00Z")
    claim_id = ctx["claim"]["id"]
    observed_version = fixtures.read_claim(api, claim_id)["version"]

    first = validate_success(
        api.create_evidence_package(
            factories.evidence_package_payload(claim_id, observed_version), headers=ANALYST), 201)
    assert first["status"] == PACKAGE_STATUS_ASSEMBLING, (
        f"Expected package status {PACKAGE_STATUS_ASSEMBLING}, got {first['status']}")
    assert first["items"] == [], f"Expected an empty items array, got {first['items']}"
    assertions.assert_package_derivations(first, 0, 0, 0.0000)
    assert first["sealed_at"] is None, f"Expected sealed_at null, got {first['sealed_at']}"

    after_first = fixtures.read_claim(api, claim_id)
    assert after_first["version"] == observed_version + 1, (
        f"Expected claim version {observed_version + 1}, got {after_first['version']}")
    assertions.assert_score_2dp(after_first["substantiation_score"], 85.00, "substantiation_score")
    assert after_first["status"] == CLAIM_STATUS_SUBSTANTIATED, (
        f"Expected claim status {CLAIM_STATUS_SUBSTANTIATED}, got {after_first['status']}")

    validate_error(
        api.create_evidence_package(
            factories.evidence_package_payload(claim_id, observed_version), headers=ANALYST),
        ApiErrorId.STALE_CLAIM_VERSION)

    rows, meta = validate_paginated(api.list_evidence_packages(headers=ANALYST, claim_id=claim_id))
    assert meta["total_count"] == 1, (
        f"Expected the refused create to persist nothing, got {meta['total_count']} packages")
    assert rows[0]["id"] == first["id"], f"Expected only {first['id']}, got {rows[0]['id']}"
    assertions.assert_unchanged(after_first, fixtures.read_claim(api, claim_id))

    second = validate_success(
        api.create_evidence_package(
            factories.evidence_package_payload(claim_id, after_first["version"]),
            headers=ANALYST), 201)
    assert second["status"] == PACKAGE_STATUS_ASSEMBLING, (
        f"Expected package status {PACKAGE_STATUS_ASSEMBLING}, got {second['status']}")
    assertions.assert_package_derivations(second, 0, 0, 0.0000)

    after_second = fixtures.read_claim(api, claim_id)
    assert after_second["version"] == after_first["version"] + 1, (
        f"Expected claim version {after_first['version'] + 1}, got {after_second['version']}")
    both, both_meta = validate_paginated(api.list_evidence_packages(headers=ANALYST, claim_id=claim_id))
    assert both_meta["total_count"] == 2, f"Expected 2 packages, got {both_meta['total_count']}"
    assert {row["status"] for row in both} == {PACKAGE_STATUS_ASSEMBLING}, (
        f"Expected both packages {PACKAGE_STATUS_ASSEMBLING}, got {[r['status'] for r in both]}")


def test_alias_link_with_a_stale_canonical_seller_version_returns_412(api):
    """A second alias link quoting the pre-merge canonical version is refused.

    The first link advances the canonical seller's version. A canonical seller
    may absorb many aliases, so the refused link succeeds unchanged once the
    current version is quoted, and every member of the cluster stays clean.

    PRD §2.7: "The link therefore requires `expected_canonical_seller_version` carrying the client's last observed `version` of the canonical seller, and a mismatch with that seller's current `version` is rejected with `ERR_STALE_SELLER_VERSION` (HTTP 412)."
    PRD §2.7: "Quoting the current value returns 200, recomputes both strike variants across the enlarged cluster, and increments the canonical seller's `version` by 1."
    PRD §2.7: "A canonical seller may absorb many aliases, so linking a different alias while quoting the current canonical `version` succeeds."
    PRD §3.3: "The path seller becomes the alias; its `canonical_seller_id` is persisted."
    PRD §3.3: "Sellers are readable individually and listable with optional filters on `canonical_seller_id` — which is how an entire alias cluster is enumerated — on `marketplace_code` and on `status`."
    PRD §3.3: "A new seller row starts with `status` `ACTIVE`, `canonical_seller_id` null, and both `standalone_strike_points` and `cluster_strike_points` at 0.00."
    PRD §3.3: "`standalone_strike_points` counts only strikes attributed to that exact seller row, ignoring every alias and the canonical root."
    Design: Corner/cross_cutting_complexity_layers/alias_link_with_a_stale_canonical_seller_version_returns_412
    """
    canonical = fixtures.create_seller(api)
    alias_one = fixtures.create_seller(api)
    alias_two = fixtures.create_seller(api)
    observed_version = canonical["version"]
    assert observed_version == 1, f"Expected a fresh seller at version 1, got {observed_version}"

    validate_success(
        api.link_alias(alias_one["id"], canonical["id"], observed_version, headers=ANALYST), 200)
    linked_one = fixtures.read_seller(api, alias_one["id"])
    assert linked_one["canonical_seller_id"] == canonical["id"], (
        f"Expected canonical_seller_id {canonical['id']}, got {linked_one['canonical_seller_id']}")

    after_first = fixtures.read_seller(api, canonical["id"])
    assert after_first["version"] == observed_version + 1, (
        f"Expected canonical version {observed_version + 1}, got {after_first['version']}")

    validate_error(
        api.link_alias(alias_two["id"], canonical["id"], observed_version, headers=ANALYST),
        ApiErrorId.STALE_SELLER_VERSION)

    refused = fixtures.read_seller(api, alias_two["id"])
    assert refused["canonical_seller_id"] is None, (
        f"Expected canonical_seller_id to stay null, got {refused['canonical_seller_id']}")
    assert refused["version"] == 1, f"Expected version 1 on the refused alias, got {refused['version']}"
    assertions.assert_unchanged(after_first, fixtures.read_seller(api, canonical["id"]))

    validate_success(
        api.link_alias(alias_two["id"], canonical["id"], after_first["version"], headers=ANALYST), 200)
    linked_two = fixtures.read_seller(api, alias_two["id"])
    assert linked_two["canonical_seller_id"] == canonical["id"], (
        f"Expected canonical_seller_id {canonical['id']}, got {linked_two['canonical_seller_id']}")

    after_second = fixtures.read_seller(api, canonical["id"])
    assert after_second["version"] == after_first["version"] + 1, (
        f"Expected canonical version {after_first['version'] + 1}, got {after_second['version']}")

    cluster, cluster_meta = validate_paginated(
        api.list_sellers(headers=ANALYST, canonical_seller_id=canonical["id"]))
    assert cluster_meta["total_count"] == 2, (
        f"Expected 2 alias rows naming the root, got {cluster_meta['total_count']}")
    assert {row["id"] for row in cluster} == {alias_one["id"], alias_two["id"]}, (
        f"Expected both aliases in the cluster, got {[row['id'] for row in cluster]}")
    for row in (after_second, linked_one, linked_two):
        assertions.assert_seller_strikes(row, 0.00, 0.00, SELLER_STATUS_ACTIVE)


def test_three_confirmed_diversions_cross_the_escalation_then_the_block_threshold(api):
    """Three seizure-confirmed strikes walk one seller 25.15, 50.30, 75.45.

    Each strike is worth 25.15 points, so the first confirmation escalates the
    seller on its own and auto-creates the enforcement case, the second leaves
    both untouched in kind, and the third crosses the blocking threshold. The
    case is created once and only once.

    PRD §3.3: "A **seizure confirmed** strike carries a base of 25.15 points — the heaviest single strike in the domain, enough to escalate a previously clean seller on its own."
    PRD §3.3: "Each strike's decayed contribution is rounded half-up to two decimal places **before** any summation."
    PRD §3.3: "The contributions are then added together, the sum is rounded half-up to two decimal places, and the result is capped at 100.00."
    PRD §3.3: "At a cluster total of 60.00 or more the seller is `BLOCKED`; at a cluster total of at least 25.00 but below 60.00 the seller is `UNDER_INVESTIGATION`; below 25.00 the seller is `ACTIVE`."
    PRD §3.10: "On success, a seizure-confirmed strike of 25.15 base points — the heaviest single charge in the domain — is attributed to that seller with an effective instant equal to `concluded_at`, both strike variants are recomputed, the seller escalates to `UNDER_INVESTIGATION` when its cluster total reaches 25.00 and is auto-blocked when it reaches 60.00, and every row touched has its `version` incremented by 1."
    PRD §3.10: "When that escalation occurs and no live enforcement case already exists for the pair of this investigation's `brand_id` and the seller, one is auto-created with `originating_takedown_id` null."
    PRD §3.10: "Both outcomes stamp `concluded_at` from the logical clock, persist `findings_ref` and increment `version` by 1, and both are terminal."
    Design: Corner/cross_cutting_complexity_layers/three_confirmed_diversions_cross_the_escalation_then_the_block_threshold
    """
    fixtures.set_clock(api, "2026-08-05T08:00:00Z")
    brand = fixtures.create_brand(api)
    registration = fixtures.create_registration(api, brand["id"])
    recordation = fixtures.create_recorded_recordation(
        api, brand["id"], registration["id"], "CBP-8001",
        customs_authority_code=CUSTOMS_AUTHORITY_US_CBP)
    seller = fixtures.create_seller(api)
    assertions.assert_seller_strikes(seller, 0.00, 0.00, SELLER_STATUS_ACTIVE)

    ladder = [
        (25.15, SELLER_STATUS_UNDER_INVESTIGATION),
        (50.30, SELLER_STATUS_UNDER_INVESTIGATION),
        (75.45, SELLER_STATUS_BLOCKED),
    ]
    first_case_id = None

    for index, (expected_total, expected_status) in enumerate(ladder, start=1):
        investigation = fixtures.create_border_seizure_investigation(
            api, brand["id"], recordation["id"], seller_id=seller["id"],
            lot_code=f"LOT-DIV-{index}")
        submitted = fixtures.submit_investigation_evidence(
            api, investigation["id"], f"EVID-{index}", f"DIST-{index}")
        assert submitted["status"] == INVESTIGATION_STATUS_EVIDENCE_SUBMITTED, (
            f"Expected status {INVESTIGATION_STATUS_EVIDENCE_SUBMITTED}, got {submitted['status']}")

        concluded = validate_success(
            api.conclude_investigation(investigation["id"],
                                       INVESTIGATION_STATUS_DIVERSION_CONFIRMED,
                                       f"FIND-DIV-{index}", headers=CUSTOMS), 200)
        assert concluded["status"] == INVESTIGATION_STATUS_DIVERSION_CONFIRMED, (
            f"Expected status {INVESTIGATION_STATUS_DIVERSION_CONFIRMED}, got {concluded['status']}")
        assert is_iso8601_timestamp(concluded["concluded_at"]), (
            f"Expected an ISO 8601 concluded_at, got {concluded['concluded_at']}")
        assert concluded["concluded_at"].startswith("2026-08-05T08:00:00"), (
            f"Expected concluded_at from the logical clock, got {concluded['concluded_at']}")

        settled = fixtures.read_seller(api, seller["id"])
        assertions.assert_seller_strikes(settled, expected_total, expected_total, expected_status)

        cases, case_meta = validate_paginated(api.list_cases(headers=COUNSEL, brand_id=brand["id"]))
        assert case_meta["total_count"] == 1, (
            f"Expected exactly 1 auto-created case after diversion {index}, "
            f"got {case_meta['total_count']}")
        case = cases[0]
        assert case["seller_id"] == seller["id"], (
            f"Expected the case aimed at {seller['id']}, got {case['seller_id']}")
        assert case["originating_takedown_id"] is None, (
            f"Expected originating_takedown_id null on a diversion-triggered case, "
            f"got {case['originating_takedown_id']}")
        assert case["case_status"] == CASE_STATUS_OPEN, (
            f"Expected case_status {CASE_STATUS_OPEN}, got {case['case_status']}")
        assert case["correspondence_status"] == CORRESPONDENCE_NONE, (
            f"Expected correspondence_status {CORRESPONDENCE_NONE}, got {case['correspondence_status']}")
        assert case["litigation_status"] == LITIGATION_NONE, (
            f"Expected litigation_status {LITIGATION_NONE}, got {case['litigation_status']}")
        if first_case_id is None:
            first_case_id = case["id"]
        else:
            assert case["id"] == first_case_id, (
                f"Expected the same case {first_case_id} to be reused, got {case['id']}")

    confirmed, confirmed_meta = validate_paginated(
        api.list_investigations(headers=CUSTOMS, seller_id=seller["id"],
                                status=INVESTIGATION_STATUS_DIVERSION_CONFIRMED))
    assert confirmed_meta["total_count"] == 3, (
        f"Expected 3 confirmed diversions, got {confirmed_meta['total_count']}")
    assert len(confirmed) == 3, f"Expected 3 rows, got {len(confirmed)}"


def test_unknown_path_ids_return_each_entitys_own_not_found_code(api):
    """Every family answers an unknown path id with its own 404 code.

    Nothing exists in the database, so each detail read and each action on an
    unknown id can only fail on path resolution, which runs before any state or
    payload gate.

    PRD §2.9: "**Priority 4** — every identifier embedded in the path exists, validated strictly left to right, else the matching not-found error (404)."
    PRD §2.4: "When a URL carries more than one identifier they are resolved strictly left to right, and the first one that resolves to nothing determines the 404 that is returned."
    PRD §2.4: "References supplied in a request *body* are resolved after the path, in the field order declared for that endpoint, and each missing target yields the not-found error for its own entity family — `ERR_BRAND_NOT_FOUND`, `ERR_REGISTRATION_NOT_FOUND`, `ERR_ENROLLMENT_NOT_FOUND`, `ERR_REPRESENTATIVE_NOT_FOUND`, `ERR_SELLER_NOT_FOUND`, `ERR_LISTING_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_TEST_BUY_NOT_FOUND`, `ERR_EVIDENCE_PACKAGE_NOT_FOUND`, `ERR_TAKEDOWN_NOT_FOUND`, `ERR_COUNTER_NOTICE_NOT_FOUND`, `ERR_CASE_NOT_FOUND`, `ERR_CUSTOMS_RECORDATION_NOT_FOUND` or `ERR_INVESTIGATION_NOT_FOUND`, each with HTTP status 404."
    Design: Corner/errors/unknown_path_ids_return_each_entitys_own_not_found_code
    """
    validate_error(api.get_brand(NON_EXISTENT_UUID, headers=ADMIN),
                   ApiErrorId.BRAND_NOT_FOUND)
    validate_error(api.get_registration(NON_EXISTENT_UUID, headers=ADMIN),
                   ApiErrorId.REGISTRATION_NOT_FOUND)
    validate_error(api.get_enrollment(NON_EXISTENT_UUID, headers=ADMIN),
                   ApiErrorId.ENROLLMENT_NOT_FOUND)
    validate_error(api.get_representative(NON_EXISTENT_UUID, headers=ADMIN),
                   ApiErrorId.REPRESENTATIVE_NOT_FOUND)
    validate_error(api.get_seller(NON_EXISTENT_UUID, headers=ANALYST),
                   ApiErrorId.SELLER_NOT_FOUND)
    validate_error(api.get_listing(NON_EXISTENT_UUID, headers=ANALYST),
                   ApiErrorId.LISTING_NOT_FOUND)
    validate_error(api.get_claim(NON_EXISTENT_UUID, headers=ANALYST),
                   ApiErrorId.CLAIM_NOT_FOUND)
    validate_error(api.get_test_buy(NON_EXISTENT_UUID, headers=ANALYST),
                   ApiErrorId.TEST_BUY_NOT_FOUND)
    validate_error(api.get_evidence_package(NON_EXISTENT_UUID, headers=ANALYST),
                   ApiErrorId.EVIDENCE_PACKAGE_NOT_FOUND)
    validate_error(api.get_takedown(NON_EXISTENT_UUID, headers=LIAISON),
                   ApiErrorId.TAKEDOWN_NOT_FOUND)
    validate_error(api.get_counter_notice(NON_EXISTENT_UUID, headers=LIAISON),
                   ApiErrorId.COUNTER_NOTICE_NOT_FOUND)
    validate_error(api.get_case(NON_EXISTENT_UUID, headers=COUNSEL),
                   ApiErrorId.CASE_NOT_FOUND)
    validate_error(api.get_recordation(NON_EXISTENT_UUID, headers=CUSTOMS),
                   ApiErrorId.CUSTOMS_RECORDATION_NOT_FOUND)
    validate_error(api.get_investigation(NON_EXISTENT_UUID, headers=CUSTOMS),
                   ApiErrorId.INVESTIGATION_NOT_FOUND)

    validate_error(api.activate_enrollment(NON_EXISTENT_UUID, headers=LIAISON),
                   ApiErrorId.ENROLLMENT_NOT_FOUND)
    validate_error(api.substantiate_claim(NON_EXISTENT_UUID, headers=ANALYST),
                   ApiErrorId.CLAIM_NOT_FOUND)
    validate_error(api.get_enforcement_metrics(NON_EXISTENT_UUID, headers=ADMIN),
                   ApiErrorId.BRAND_NOT_FOUND)


def test_body_fk_lookups_report_the_registration_and_enrollment_not_found_codes(api):
    """Unknown body references answer in the endpoint's declared field order.

    Opening a claim declares `brand_id`, then `listing_id`, then
    `asserted_registration_id`, so an unknown brand outranks an unknown
    registration and an unknown registration outranks the listing's unflagged
    state. Drafting a notice declares the enrolment first, so three unknown
    references report the enrolment.

    PRD §2.9: "**Priority 5** — every reference supplied in the body exists, validated in the field order declared by that endpoint's input list, else the matching not-found error (404)."
    PRD §2.9: "**Priority 28** — the target listing's `monitor_status` is `FLAGGED`, else `ERR_LISTING_NOT_FLAGGED` (409)."
    PRD §3.5: "An `EnforcementAnalyst` opens a claim by supplying `brand_id`, the `listing_id` of the flagged listing the claim is filed against, the `asserted_registration_id` offered as the claim's legal basis, and the `claimed_violation_type` the brand asserts — one of `COUNTERFEIT`, `COPYRIGHT` or `TRADEMARK` — which also selects the evidence-item set the eventual package must cover."
    PRD §3.8: "Either an `EnforcementAnalyst` or an `AuthorizedRepresentative` may draft the notice, binding together the `enrollment_id` through which the notice will be filed, the `claim_id` being enforced, and the `evidence_package_id` attached to the current round."
    Design: Corner/errors/body_fk_lookups_report_the_registration_and_enrollment_not_found_codes
    """
    fixtures.set_clock(api, "2026-08-05T08:00:00Z")
    brand = fixtures.create_brand(api)
    seller = fixtures.create_seller(api)
    listing = fixtures.create_listing(api, brand["id"], seller["id"])
    assert listing["monitor_status"] == MONITOR_STATUS_NEW, (
        f"Expected an unscreened listing at {MONITOR_STATUS_NEW}, got {listing['monitor_status']}")

    validate_error(
        api.create_claim(
            factories.claim_payload(brand["id"], listing["id"], NON_EXISTENT_UUID),
            headers=ANALYST),
        ApiErrorId.REGISTRATION_NOT_FOUND)

    validate_error(
        api.create_claim(
            factories.claim_payload(NON_EXISTENT_UUID, listing["id"], NON_EXISTENT_UUID),
            headers=ANALYST),
        ApiErrorId.BRAND_NOT_FOUND)

    validate_error(
        api.create_takedown(
            factories.takedown_payload(NON_EXISTENT_UUID, NON_EXISTENT_UUID, NON_EXISTENT_UUID),
            headers=ANALYST),
        ApiErrorId.ENROLLMENT_NOT_FOUND)

    claims, claim_meta = validate_paginated(api.list_claims(headers=ANALYST))
    assert claim_meta["total_count"] == 0, (
        f"Expected no claim to be persisted, got {claim_meta['total_count']}")
    assert claims == [], f"Expected an empty claim index, got {claims}"

    notices, notice_meta = validate_paginated(api.list_takedowns(headers=LIAISON))
    assert notice_meta["total_count"] == 0, (
        f"Expected no notice to be persisted, got {notice_meta['total_count']}")
    assert notices == [], f"Expected an empty notice index, got {notices}"

    untouched = fixtures.read_listing(api, listing["id"])
    assert untouched["monitor_status"] == MONITOR_STATUS_NEW, (
        f"Expected the listing to stay {MONITOR_STATUS_NEW}, got {untouched['monitor_status']}")
    assert untouched["match_score"] is None, (
        f"Expected match_score to stay null, got {untouched['match_score']}")
    assertions.assert_unchanged(listing, untouched)
