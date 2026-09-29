"""Validation ladder refusals of the Brand Registry & Counterfeit Enforcement API.

Each test drives one refusal the PRD states explicitly, checks that the refusal
carries the nominated error identifier and status, checks that nothing was
persisted, and then repairs the single offending premise so the same call
succeeds — which is what proves the refusal was caused by that premise alone.
"""

from test_helpers import (
    ApiErrorId,
    assertions,
    constants,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)


def _to_whole_second(instant: str) -> str:
    """Server instants carry three fractional digits; deadline walks do not."""
    if "." in instant:
        return instant.split(".", 1)[0] + "Z"
    return instant


def test_claim_on_a_cleared_listing_returns_listing_not_flagged(api):
    """A claim demands a FLAGGED listing; a CLEARED one is refused outright.

    PRD §3.5: "The listing's `monitor_status` must be `FLAGGED`, else `ERR_LISTING_NOT_FLAGGED` (HTTP 409)."
    PRD §2.9: "Evaluation stops there and nothing is persisted — not even a value the server had already computed."
    PRD §3.5: "On success the claim lands in status `DRAFT`, its `registration_strength` and `preliminary_score` are derived immediately, `substantiation_score` starts at 0.00, `dismissal_reason_code` starts null, and the listing's `enforcement_status` advances `NONE → CLAIM_OPEN` with the listing's `version` incremented by 1."
    Design: Corner/validations/claim_on_a_cleared_listing_returns_listing_not_flagged
    """
    fixtures.set_clock(api, "2026-08-05T09:00:00Z")
    brand = fixtures.create_brand(api, authorized_msrp_cents=10000)
    registration = fixtures.create_registration(api, brand["id"], nice_class=8)
    seller = fixtures.create_seller(api)
    listing = fixtures.create_listing(
        api, brand["id"], seller["id"], price_cents=9500, nice_class=8)
    cleared = fixtures.screen_listing(api, listing["id"], 0.50, 0.40)
    expected_cleared = assertions.match_score(0.50, 0.40, 0.0500)
    assertions.assert_listing_screening(
        cleared, 0.50, 0.40, 0.0500, expected_cleared,
        constants.MONITOR_STATUS_CLEARED, constants.VIOLATION_TYPE_NONE)

    response = api.create_claim(
        factories.claim_payload(
            brand["id"], listing["id"], registration["id"],
            claimed_violation_type=constants.VIOLATION_TYPE_TRADEMARK),
        headers=fixtures.ANALYST)
    validate_error(response, ApiErrorId.LISTING_NOT_FLAGGED)

    unchanged = fixtures.read_listing(api, listing["id"])
    assertions.assert_unchanged(cleared, unchanged)
    assert unchanged["enforcement_status"] == constants.ENFORCEMENT_STATUS_NONE, (
        f"Expected {constants.ENFORCEMENT_STATUS_NONE}, got {unchanged['enforcement_status']}")
    rows, meta = validate_paginated(
        api.list_claims(headers=fixtures.ANALYST, listing_id=listing["id"]))
    assert meta["total_count"] == 0, f"Expected total_count 0, got {meta['total_count']}"
    assert rows == [], f"Expected no claim rows, got {rows}"

    # Re-screening the same listing above the flag threshold repairs the premise.
    flagged = fixtures.screen_listing(api, listing["id"], 0.92, 0.88)
    expected_flagged = assertions.match_score(0.92, 0.88, 0.0500)
    assertions.assert_listing_screening(
        flagged, 0.92, 0.88, 0.0500, expected_flagged,
        constants.MONITOR_STATUS_FLAGGED, constants.VIOLATION_TYPE_COUNTERFEIT)

    response = api.create_claim(
        factories.claim_payload(
            brand["id"], listing["id"], registration["id"],
            claimed_violation_type=constants.VIOLATION_TYPE_TRADEMARK),
        headers=fixtures.ANALYST)
    claim = validate_success(response, 201)
    assert claim["status"] == constants.CLAIM_STATUS_DRAFT, (
        f"Expected {constants.CLAIM_STATUS_DRAFT}, got {claim['status']}")
    listing_after = fixtures.read_listing(api, listing["id"])
    assert listing_after["enforcement_status"] == constants.ENFORCEMENT_STATUS_CLAIM_OPEN, (
        f"Expected {constants.ENFORCEMENT_STATUS_CLAIM_OPEN}, "
        f"got {listing_after['enforcement_status']}")


def test_appending_to_a_sealed_package_returns_evidence_package_sealed(api):
    """A sealed exhibit bundle is frozen: no further item may be appended.

    PRD §3.7: "Appending is refused with `ERR_EVIDENCE_PACKAGE_SEALED` (HTTP 409) once the package is no longer `ASSEMBLING` — a sealed or withdrawn package accepts nothing further."
    PRD §3.7: "On success `sealed_at` is stamped from the logical clock, the `items` array becomes immutable, and the package's `version` is incremented by 1."
    PRD §3.7: "A `SEALED` package's items and score are frozen and are never re-derived."
    Design: Corner/validations/appending_to_a_sealed_package_returns_evidence_package_sealed
    """
    ctx = fixtures.setup_claim(
        api, clock="2026-08-05T09:00:00Z",
        claimed_violation_type=constants.VIOLATION_TYPE_TRADEMARK)
    required_types = assertions.required_types_for(constants.VIOLATION_TYPE_TRADEMARK)

    package = fixtures.create_evidence_package(api, ctx["claim"]["id"])
    package = fixtures.append_items(
        api, package["id"],
        [(required_types[0], "SCREEN-1"),
         (required_types[1], "CERT-1"),
         (required_types[2], "MARK-1"),
         (constants.ITEM_SELLER_PROFILE_SNAPSHOT, "PROF-1"),
         (constants.ITEM_PRICE_HISTORY_EXPORT, "PRICE-1")])
    assertions.assert_package_derivations(
        package, 5, 3, assertions.completeness_score(3, 3, 2))
    assert package["sealed_at"] is None, f"Expected sealed_at null, got {package['sealed_at']}"

    sealed = fixtures.seal_evidence_package(api, package["id"])
    assert sealed["status"] == constants.PACKAGE_STATUS_SEALED, (
        f"Expected {constants.PACKAGE_STATUS_SEALED}, got {sealed['status']}")
    assert _to_whole_second(sealed["sealed_at"]) == "2026-08-05T09:00:00Z", (
        f"Expected sealed_at 2026-08-05T09:00:00Z, got {sealed['sealed_at']}")
    assert sealed["version"] == package["version"] + 1, (
        f"Expected version {package['version'] + 1}, got {sealed['version']}")

    response = api.append_evidence_item(
        sealed["id"], constants.ITEM_CUSTOMER_COMPLAINT, "COMPLAINT-1",
        headers=fixtures.ANALYST)
    validate_error(response, ApiErrorId.EVIDENCE_PACKAGE_SEALED)

    after = fixtures.read_evidence_package(api, sealed["id"])
    assertions.assert_unchanged(sealed, after)
    assertions.assert_package_derivations(
        after, 5, 3, assertions.completeness_score(3, 3, 2))
    assert len(after["items"]) == 5, f"Expected 5 frozen items, got {len(after['items'])}"


def test_coverage_conjunct_fails_even_though_the_score_clears_the_threshold(api):
    """0.8250 with three of four mandatory types is still unsealable.

    PRD §3.7: "Two conditions must both hold: `required_type_coverage` must equal the full count of mandatory types for the claim's violation type, **and** `completeness_score` must be at least 0.8000."
    PRD §3.7: "But a counterfeit claim's package holding only three of its four mandatory types plus four supporting items scores seventy hundredths of three quarters plus thirty hundredths of 1, or 0.8250 — above the score threshold, yet **still unsealable**, because the coverage conjunct fails; that request receives `ERR_EVIDENCE_INCOMPLETE`."
    Design: Corner/validations/coverage_conjunct_fails_even_though_the_score_clears_the_threshold
    """
    ctx = fixtures.setup_claim(
        api, clock="2026-08-05T09:00:00Z",
        claimed_violation_type=constants.VIOLATION_TYPE_COUNTERFEIT)
    required_types = assertions.required_types_for(constants.VIOLATION_TYPE_COUNTERFEIT)
    assert len(required_types) == 4, f"Expected 4 mandatory types, got {len(required_types)}"
    missing_type = constants.ITEM_LAB_AUTHENTICATION_REPORT
    present_types = [t for t in required_types if t != missing_type]

    package = fixtures.create_evidence_package(api, ctx["claim"]["id"])
    package = fixtures.append_items(
        api, package["id"],
        [(item_type, f"REQ-{index}") for index, item_type in enumerate(present_types, start=1)]
        + [(constants.ITEM_SELLER_PROFILE_SNAPSHOT, "PROF-1"),
           (constants.ITEM_PRICE_HISTORY_EXPORT, "PRICE-1"),
           (constants.ITEM_CUSTOMER_COMPLAINT, "COMPLAINT-1"),
           (constants.ITEM_SHIPPING_LABEL_PHOTO, "LABEL-1")])
    expected_score = assertions.completeness_score(3, 4, 4)
    assert expected_score == 0.8250, f"Expected 0.8250, got {expected_score}"
    assertions.assert_package_derivations(package, 7, 3, expected_score)
    assert package["completeness_score"] >= constants.SEAL_COMPLETENESS_THRESHOLD, (
        f"Expected the score to clear {constants.SEAL_COMPLETENESS_THRESHOLD}, "
        f"got {package['completeness_score']}")

    response = api.seal_evidence_package(package["id"], headers=fixtures.ANALYST)
    validate_error(response, ApiErrorId.EVIDENCE_INCOMPLETE)
    after = fixtures.read_evidence_package(api, package["id"])
    assertions.assert_unchanged(package, after)
    assert after["status"] == constants.PACKAGE_STATUS_ASSEMBLING, (
        f"Expected {constants.PACKAGE_STATUS_ASSEMBLING}, got {after['status']}")
    assert after["sealed_at"] is None, f"Expected sealed_at null, got {after['sealed_at']}"

    # Supplying the one missing mandatory type satisfies the coverage conjunct.
    package = fixtures.append_items(api, package["id"], [(missing_type, "LAB-1")])
    assertions.assert_package_derivations(package, 8, 4, assertions.completeness_score(4, 4, 4))
    assertions.assert_score_4dp(package["completeness_score"], 1.0000, "completeness_score")
    sealed = fixtures.seal_evidence_package(api, package["id"])
    assert sealed["status"] == constants.PACKAGE_STATUS_SEALED, (
        f"Expected {constants.PACKAGE_STATUS_SEALED}, got {sealed['status']}")


def test_enrollment_activate_with_a_class_mismatch_returns_registration_not_eligible(api):
    """A marketplace registry will not cover a class the mark does not claim.

    PRD §3.2: "And its `nice_class` must equal the enrolment's `requested_nice_class`, since a marketplace registry will not cover a class the mark does not claim; a mismatch carries the same `ERR_REGISTRATION_NOT_ELIGIBLE`."
    PRD §3.2: "On success `activated_at` is stamped from the logical clock, the brand's posture is re-derived from `ENROLLMENT_PENDING` to `ENROLLED`, and the enrolment and the brand each have their `version` incremented by 1."
    Design: Corner/validations/enrollment_activate_with_a_class_mismatch_returns_registration_not_eligible
    """
    fixtures.set_clock(api, "2026-08-05T09:00:00Z")
    brand = fixtures.create_brand(api)
    registration = fixtures.create_registration(api, brand["id"], nice_class=8)
    mismatched = fixtures.create_enrollment(
        api, brand["id"], registration["id"], requested_nice_class=9)
    assert mismatched["requested_nice_class"] == 9, (
        f"Expected requested_nice_class 9, got {mismatched['requested_nice_class']}")
    assert registration["nice_class"] == 8, (
        f"Expected nice_class 8, got {registration['nice_class']}")
    brand_before = fixtures.read_brand(api, brand["id"])
    assert brand_before["status"] == constants.BRAND_STATUS_ENROLLMENT_PENDING, (
        f"Expected {constants.BRAND_STATUS_ENROLLMENT_PENDING}, got {brand_before['status']}")

    response = api.activate_enrollment(mismatched["id"], headers=fixtures.LIAISON)
    validate_error(response, ApiErrorId.REGISTRATION_NOT_ELIGIBLE)

    after = validate_success(
        api.get_enrollment(mismatched["id"], headers=fixtures.ADMIN), 200)
    assertions.assert_unchanged(mismatched, after)
    assert after["enrollment_status"] == constants.ENROLLMENT_STATUS_SUBMITTED, (
        f"Expected {constants.ENROLLMENT_STATUS_SUBMITTED}, got {after['enrollment_status']}")
    assert after["activated_at"] is None, (
        f"Expected activated_at null, got {after['activated_at']}")
    brand_after = fixtures.read_brand(api, brand["id"])
    assertions.assert_unchanged(brand_before, brand_after)
    assert brand_after["status"] == constants.BRAND_STATUS_ENROLLMENT_PENDING, (
        f"Expected {constants.BRAND_STATUS_ENROLLMENT_PENDING}, got {brand_after['status']}")

    # The very same registration activates an enrolment that asks for its own class.
    matched = fixtures.create_enrollment(
        api, brand["id"], registration["id"],
        marketplace_code=constants.MARKETPLACE_EBY, requested_nice_class=8)
    activated = fixtures.activate_enrollment(api, matched["id"])
    assert activated["enrollment_status"] == constants.ENROLLMENT_STATUS_ACTIVE, (
        f"Expected {constants.ENROLLMENT_STATUS_ACTIVE}, got {activated['enrollment_status']}")
    assert _to_whole_second(activated["activated_at"]) == "2026-08-05T09:00:00Z", (
        f"Expected activated_at 2026-08-05T09:00:00Z, got {activated['activated_at']}")
    brand_final = fixtures.read_brand(api, brand["id"])
    assert brand_final["status"] == constants.BRAND_STATUS_ENROLLED, (
        f"Expected {constants.BRAND_STATUS_ENROLLED}, got {brand_final['status']}")


def test_representative_under_a_submitted_enrollment_returns_enrollment_not_active(api):
    """An agent of record may only be designated against an ACTIVE enrolment.

    PRD §3.2: "The referenced enrolment must be `ACTIVE` at the moment of designation, else `ERR_ENROLLMENT_NOT_ACTIVE` (HTTP 409)."
    PRD §3.2: "The new row starts `DESIGNATED` with `revoked_at` null, and its own `id` becomes a valid `X-User-ID` for the `AuthorizedRepresentative` role."
    Design: Corner/validations/representative_under_a_submitted_enrollment_returns_enrollment_not_active
    """
    ctx = fixtures.setup_enrolled_brand(api, clock="2026-08-05T09:00:00Z", activate=False)
    submitted = ctx["enrollment"]
    assert submitted["enrollment_status"] == constants.ENROLLMENT_STATUS_SUBMITTED, (
        f"Expected {constants.ENROLLMENT_STATUS_SUBMITTED}, got {submitted['enrollment_status']}")

    response = api.create_representative(
        factories.representative_payload(submitted["id"]), headers=fixtures.ADMIN)
    validate_error(response, ApiErrorId.ENROLLMENT_NOT_ACTIVE)

    rows, meta = validate_paginated(
        api.list_representatives(headers=fixtures.ADMIN, enrollment_id=submitted["id"]))
    assert meta["total_count"] == 0, f"Expected total_count 0, got {meta['total_count']}"
    assert rows == [], f"Expected no designation rows, got {rows}"

    activated = fixtures.activate_enrollment(api, submitted["id"])
    assert activated["enrollment_status"] == constants.ENROLLMENT_STATUS_ACTIVE, (
        f"Expected {constants.ENROLLMENT_STATUS_ACTIVE}, got {activated['enrollment_status']}")

    response = api.create_representative(
        factories.representative_payload(activated["id"]), headers=fixtures.ADMIN)
    representative = validate_success(response, 201)
    assert representative["designation_status"] == constants.DESIGNATION_STATUS_DESIGNATED, (
        f"Expected {constants.DESIGNATION_STATUS_DESIGNATED}, "
        f"got {representative['designation_status']}")
    assert representative["revoked_at"] is None, (
        f"Expected revoked_at null, got {representative['revoked_at']}")


def test_listing_list_with_limit_zero_returns_invalid_pagination(api):
    """Page size must be an integer from 1 through 100; zero is out of range.

    PRD §2.3: "`limit` controls page size: it defaults to 10 when omitted, its minimum accepted value is 1 and its maximum accepted value is 100."
    PRD §2.3: "A `limit` that is not an integer in the range 1 through 100 inclusive, or an `offset` that is not an integer of at least 0, is rejected with `ERR_INVALID_PAGINATION` (HTTP 400)."
    Design: Corner/validations/listing_list_with_limit_zero_returns_invalid_pagination
    """
    fixtures.set_clock(api, "2026-08-05T09:00:00Z")
    brand = fixtures.create_brand(api)
    seller = fixtures.create_seller(api)
    fixtures.create_listing(api, brand["id"], seller["id"], price_cents=3000, nice_class=8)

    response = api.list_listings(headers=fixtures.ANALYST, brand_id=brand["id"], limit=0)
    validate_error(response, ApiErrorId.INVALID_PAGINATION)

    response = api.list_listings(headers=fixtures.ANALYST, brand_id=brand["id"], limit=101)
    validate_error(response, ApiErrorId.INVALID_PAGINATION)

    response = api.list_listings(headers=fixtures.ANALYST, brand_id=brand["id"], offset=-1)
    validate_error(response, ApiErrorId.INVALID_PAGINATION)

    # One above the rejected floor and the documented ceiling are both accepted.
    rows, meta = validate_paginated(
        api.list_listings(headers=fixtures.ANALYST, brand_id=brand["id"], limit=1, offset=0))
    assert meta["limit"] == 1, f"Expected limit 1, got {meta['limit']}"
    assert meta["offset"] == 0, f"Expected offset 0, got {meta['offset']}"
    assert meta["total_count"] == 1, f"Expected total_count 1, got {meta['total_count']}"
    assert len(rows) == 1, f"Expected 1 row, got {len(rows)}"

    rows, meta = validate_paginated(
        api.list_listings(headers=fixtures.ANALYST, brand_id=brand["id"], limit=100))
    assert meta["limit"] == 100, f"Expected limit 100, got {meta['limit']}"
    assert meta["total_count"] == 1, f"Expected total_count 1, got {meta['total_count']}"


def test_alias_links_deeper_than_one_level_return_alias_chain_not_allowed(api):
    """Seller clusters are exactly one level deep, and three links prove it.

    PRD §3.3: "Clusters are exactly one level deep, which imposes three refusals, all carrying `ERR_ALIAS_CHAIN_NOT_ALLOWED` (HTTP 422): the row being linked must not already name a canonical seller, the target must not itself be an alias of somebody else, and a seller may not be linked to itself."
    PRD §3.3: "On success both strike variants are recomputed for every member of the enlarged cluster, the escalation ladder is re-evaluated for each of them, and the alias row and the canonical row each have their `version` incremented by 1."
    Design: Corner/validations/alias_links_deeper_than_one_level_return_alias_chain_not_allowed
    """
    fixtures.set_clock(api, "2026-08-05T09:00:00Z")
    root = fixtures.create_seller(api)
    alias = fixtures.create_seller(api)
    outsider = fixtures.create_seller(api)

    linked = validate_success(
        api.link_alias(alias["id"], root["id"], root["version"], headers=fixtures.ANALYST), 200)
    assert linked["canonical_seller_id"] == root["id"], (
        f"Expected canonical_seller_id {root['id']}, got {linked['canonical_seller_id']}")

    # The row being linked already names a canonical seller.
    response = api.link_alias(
        alias["id"], outsider["id"],
        fixtures.read_seller(api, outsider["id"])["version"], headers=fixtures.ANALYST)
    validate_error(response, ApiErrorId.ALIAS_CHAIN_NOT_ALLOWED)

    # The target is itself an alias of somebody else.
    response = api.link_alias(
        outsider["id"], alias["id"],
        fixtures.read_seller(api, alias["id"])["version"], headers=fixtures.ANALYST)
    validate_error(response, ApiErrorId.ALIAS_CHAIN_NOT_ALLOWED)

    # A seller may not be linked to itself.
    response = api.link_alias(
        outsider["id"], outsider["id"],
        fixtures.read_seller(api, outsider["id"])["version"], headers=fixtures.ANALYST)
    validate_error(response, ApiErrorId.ALIAS_CHAIN_NOT_ALLOWED)

    still_outside = fixtures.read_seller(api, outsider["id"])
    assertions.assert_unchanged(outsider, still_outside)
    assert still_outside["canonical_seller_id"] is None, (
        f"Expected canonical_seller_id null, got {still_outside['canonical_seller_id']}")
    still_alias = fixtures.read_seller(api, alias["id"])
    assertions.assert_unchanged(linked, still_alias)
    assert still_alias["canonical_seller_id"] == root["id"], (
        f"Expected canonical_seller_id {root['id']}, got {still_alias['canonical_seller_id']}")

    # A second storefront may still join the root, since that stays one level deep.
    sibling = fixtures.create_seller(api)
    joined = validate_success(
        api.link_alias(sibling["id"], root["id"],
                       fixtures.read_seller(api, root["id"])["version"],
                       headers=fixtures.ANALYST), 200)
    assert joined["canonical_seller_id"] == root["id"], (
        f"Expected canonical_seller_id {root['id']}, got {joined['canonical_seller_id']}")


def test_takedown_bound_to_another_claims_package_returns_package_mismatch(api):
    """A notice may only carry an exhibit bundle assembled on its own claim.

    PRD §3.8: "And the supplied evidence package must belong to the same claim as the notice, else `ERR_EVIDENCE_PACKAGE_MISMATCH` (HTTP 422)."
    PRD §3.8: "The draft lands in status `DRAFT` with `round_number` 0, `submitted_by_rep_id` null, and `submitted_at`, `decision_due_at`, `decided_at`, `counter_notice_deadline_at` and `marketplace_case_ref` all null."
    Design: Corner/validations/takedown_bound_to_another_claims_package_returns_package_mismatch
    """
    ctx = fixtures.setup_substantiated_claim(api, clock="2026-08-05T09:00:00Z")
    own_claim = ctx["claim"]

    foreign_seller = fixtures.create_seller(api)
    foreign_listing = fixtures.create_listing(
        api, ctx["brand"]["id"], foreign_seller["id"], price_cents=0, nice_class=8)
    fixtures.screen_listing(api, foreign_listing["id"], 1.00, 1.00)
    foreign_claim = fixtures.create_claim(
        api, ctx["brand"]["id"], foreign_listing["id"], ctx["registration"]["id"],
        claimed_violation_type=constants.VIOLATION_TYPE_TRADEMARK)
    foreign_claim = fixtures.substantiate_claim(api, foreign_claim["id"])

    foreign_package = fixtures.fill_and_seal_package(
        api, foreign_claim["id"],
        claimed_violation_type=constants.VIOLATION_TYPE_TRADEMARK, tag="foreign")
    own_package = fixtures.fill_and_seal_package(
        api, own_claim["id"],
        claimed_violation_type=constants.VIOLATION_TYPE_TRADEMARK, tag="own")
    assert foreign_package["claim_id"] == foreign_claim["id"], (
        f"Expected claim_id {foreign_claim['id']}, got {foreign_package['claim_id']}")

    response = api.create_takedown(
        factories.takedown_payload(
            ctx["enrollment"]["id"], own_claim["id"], foreign_package["id"]),
        headers=fixtures.ANALYST)
    validate_error(response, ApiErrorId.EVIDENCE_PACKAGE_MISMATCH)

    rows, meta = validate_paginated(
        api.list_takedowns(headers=fixtures.ANALYST, claim_id=own_claim["id"]))
    assert meta["total_count"] == 0, f"Expected total_count 0, got {meta['total_count']}"
    assert rows == [], f"Expected no notice rows, got {rows}"

    response = api.create_takedown(
        factories.takedown_payload(ctx["enrollment"]["id"], own_claim["id"], own_package["id"]),
        headers=fixtures.ANALYST)
    draft = validate_success(response, 201)
    assert draft["status"] == constants.TAKEDOWN_STATUS_DRAFT, (
        f"Expected {constants.TAKEDOWN_STATUS_DRAFT}, got {draft['status']}")
    assert draft["round_number"] == 0, f"Expected round_number 0, got {draft['round_number']}"
    for field in ("submitted_by_rep_id", "submitted_at", "decision_due_at", "decided_at",
                  "counter_notice_deadline_at", "marketplace_case_ref"):
        assert draft[field] is None, f"Expected {field} null on a draft, got {draft[field]}"


def test_dismiss_while_a_notice_is_in_flight_returns_decision_window_open(api):
    """A claim may not be abandoned while its notice is still with the marketplace.

    PRD §3.5: "The withdrawal is refused with `ERR_DECISION_WINDOW_OPEN` (HTTP 409) while any notice on the claim sits in status `SUBMITTED`, `APPROVED_REMOVED` or `COUNTER_NOTICED` — a claim may not be abandoned while a marketplace notice is still in flight or still in force."
    PRD §3.8: "On the **rejected** branch the notice advances `SUBMITTED → REJECTED`, `counter_notice_deadline_at` stays null, the claim's listing is released `TAKEDOWN_PENDING → CLAIM_OPEN`, and **no strike is attributed** — a rejected notice carries no enforcement consequence for the seller."
    PRD §3.5: "On success two cascades follow: the listing's `enforcement_status` is re-derived, falling `CLAIM_OPEN → NONE` once no open claim remains on it, and every evidence package of the claim whose status is `ASSEMBLING` or `SEALED` moves to `WITHDRAWN`."
    Design: Corner/validations/dismiss_while_a_notice_is_in_flight_returns_decision_window_open
    """
    ctx = fixtures.setup_submitted_takedown(api, clock="2026-08-05T09:00:00Z")
    assert ctx["takedown"]["status"] == constants.TAKEDOWN_STATUS_SUBMITTED, (
        f"Expected {constants.TAKEDOWN_STATUS_SUBMITTED}, got {ctx['takedown']['status']}")
    claim_before = fixtures.read_claim(api, ctx["claim"]["id"])
    assert claim_before["status"] == constants.CLAIM_STATUS_SUBSTANTIATED, (
        f"Expected {constants.CLAIM_STATUS_SUBSTANTIATED}, got {claim_before['status']}")

    response = api.dismiss_claim(
        ctx["claim"]["id"], constants.DISMISSAL_ANALYST_WITHDRAWN, headers=fixtures.ANALYST)
    validate_error(response, ApiErrorId.DECISION_WINDOW_OPEN)

    claim_after = fixtures.read_claim(api, ctx["claim"]["id"])
    assertions.assert_unchanged(claim_before, claim_after)
    assert claim_after["dismissal_reason_code"] is None, (
        f"Expected dismissal_reason_code null, got {claim_after['dismissal_reason_code']}")
    package_after = fixtures.read_evidence_package(api, ctx["package"]["id"])
    assert package_after["status"] == constants.PACKAGE_STATUS_SEALED, (
        f"Expected {constants.PACKAGE_STATUS_SEALED}, got {package_after['status']}")
    listing_after = fixtures.read_listing(api, ctx["listing"]["id"])
    assert listing_after["enforcement_status"] == constants.ENFORCEMENT_STATUS_TAKEDOWN_PENDING, (
        f"Expected {constants.ENFORCEMENT_STATUS_TAKEDOWN_PENDING}, "
        f"got {listing_after['enforcement_status']}")

    # A refusal by the marketplace closes the decision window and carries no strike.
    rejected = fixtures.decide_takedown(
        api, ctx["takedown"]["id"], constants.DECISION_REJECTED)
    assert rejected["status"] == constants.TAKEDOWN_STATUS_REJECTED, (
        f"Expected {constants.TAKEDOWN_STATUS_REJECTED}, got {rejected['status']}")
    assert rejected["counter_notice_deadline_at"] is None, (
        f"Expected counter_notice_deadline_at null on a rejection, "
        f"got {rejected['counter_notice_deadline_at']}")
    seller = fixtures.read_seller(api, ctx["seller"]["id"])
    assertions.assert_seller_strikes(seller, 0.00, 0.00, constants.SELLER_STATUS_ACTIVE)
    released = fixtures.read_listing(api, ctx["listing"]["id"])
    assert released["enforcement_status"] == constants.ENFORCEMENT_STATUS_CLAIM_OPEN, (
        f"Expected {constants.ENFORCEMENT_STATUS_CLAIM_OPEN}, "
        f"got {released['enforcement_status']}")

    response = api.dismiss_claim(
        ctx["claim"]["id"], constants.DISMISSAL_ANALYST_WITHDRAWN, headers=fixtures.ANALYST)
    dismissed = validate_success(response, 200)
    assert dismissed["status"] == constants.CLAIM_STATUS_DISMISSED, (
        f"Expected {constants.CLAIM_STATUS_DISMISSED}, got {dismissed['status']}")
    assert dismissed["dismissal_reason_code"] == constants.DISMISSAL_ANALYST_WITHDRAWN, (
        f"Expected {constants.DISMISSAL_ANALYST_WITHDRAWN}, "
        f"got {dismissed['dismissal_reason_code']}")
    assert fixtures.read_listing(api, ctx["listing"]["id"])["enforcement_status"] == (
        constants.ENFORCEMENT_STATUS_NONE), "Expected the listing to fall back to NONE"
    assert fixtures.read_evidence_package(api, ctx["package"]["id"])["status"] == (
        constants.PACKAGE_STATUS_WITHDRAWN), "Expected the sealed package to be WITHDRAWN"


def test_counter_notice_after_the_filing_deadline_returns_window_expired(api):
    """The contest window is inclusive at its final instant and shut one second later.

    PRD §2.5: "Every one of those windows is tested inclusively against the logical clock: acting at exactly the deadline instant is still in time, and one second past it is not."
    PRD §3.8: "`counter_notice_deadline_at` is computed by advancing `decided_at` by ten business days, opening the seller's contest window."
    PRD §3.8: "The filing must land at or before that notice's `counter_notice_deadline_at`, else `ERR_COUNTER_NOTICE_WINDOW_EXPIRED` (HTTP 422)."
    Design: Corner/validations/counter_notice_after_the_filing_deadline_returns_window_expired
    """
    ctx = fixtures.setup_removed_takedown(api, clock="2026-08-05T09:00:00Z")
    ctx = fixtures.setup_second_removal_on_same_seller(api, ctx, tag="2")
    inside = ctx["takedown"]
    outside = ctx["takedown_2"]

    deadline = assertions.add_business_days(
        "2026-08-05T09:00:00Z", constants.COUNTER_NOTICE_FILING_BUSINESS_DAYS)
    assert deadline == "2026-08-19T09:00:00Z", f"Expected 2026-08-19T09:00:00Z, got {deadline}"
    for notice in (inside, outside):
        assert notice["status"] == constants.TAKEDOWN_STATUS_APPROVED_REMOVED, (
            f"Expected {constants.TAKEDOWN_STATUS_APPROVED_REMOVED}, got {notice['status']}")
        assert _to_whole_second(notice["counter_notice_deadline_at"]) == deadline, (
            f"Expected {deadline}, got {notice['counter_notice_deadline_at']}")

    # Exactly at the deadline instant the seller is still in time.
    fixtures.set_clock(api, deadline)
    response = api.create_counter_notice(
        factories.counter_notice_payload(inside["id"], ctx["seller"]["id"]),
        headers=fixtures.LIAISON)
    filed = validate_success(response, 201)
    assert filed["status"] == constants.COUNTER_NOTICE_STATUS_FILED, (
        f"Expected {constants.COUNTER_NOTICE_STATUS_FILED}, got {filed['status']}")
    assert _to_whole_second(filed["filed_at"]) == deadline, (
        f"Expected filed_at {deadline}, got {filed['filed_at']}")
    assert fixtures.read_takedown(api, inside["id"])["status"] == (
        constants.TAKEDOWN_STATUS_COUNTER_NOTICED), (
        "Expected the contested notice to reach COUNTER_NOTICED")

    # One second past it, the identical filing is out of time.
    fixtures.set_clock(api, assertions.add_seconds(deadline, 1))
    response = api.create_counter_notice(
        factories.counter_notice_payload(outside["id"], ctx["seller"]["id"]),
        headers=fixtures.LIAISON)
    validate_error(response, ApiErrorId.COUNTER_NOTICE_WINDOW_EXPIRED)

    untouched = fixtures.read_takedown(api, outside["id"])
    assertions.assert_unchanged(outside, untouched)
    assert untouched["status"] == constants.TAKEDOWN_STATUS_APPROVED_REMOVED, (
        f"Expected {constants.TAKEDOWN_STATUS_APPROVED_REMOVED}, got {untouched['status']}")
    rows, meta = validate_paginated(
        api.list_counter_notices(headers=fixtures.LIAISON, takedown_id=outside["id"]))
    assert meta["total_count"] == 0, f"Expected total_count 0, got {meta['total_count']}"
    assert rows == [], f"Expected no counter notice rows, got {rows}"


def test_recordation_sharing_a_boundary_date_returns_window_overlap(api):
    """Customs coverage windows are closed on both ends, so a shared date collides.

    PRD §3.10: "The window `[recorded_on, expires_on]` is closed on both ends at whole-date granularity, so two windows collide whenever the first begins on or before the second ends and the second begins on or before the first ends."
    PRD §3.10: "Sharing a single boundary date is therefore a collision: a window ending `2026-12-31` collides with one starting `2026-12-31`."
    PRD §3.10: "A window starting the very next day, `2027-01-01`, is clean."
    PRD §3.10: "A collision is `ERR_RECORDATION_WINDOW_OVERLAP` (HTTP 409)."
    PRD §3.10: "The collision test is scoped to rows that already sit at `status` `RECORDED` and that share this row's `brand_id`, `customs_authority_code` and `nice_class` all three; `DRAFT` and `EXPIRED` rows are invisible to it, and a different authority or a different Nice class is a different scope entirely."
    Design: Corner/validations/recordation_sharing_a_boundary_date_returns_window_overlap
    """
    fixtures.set_clock(api, "2026-08-05T09:00:00Z")
    brand = fixtures.create_brand(api)
    registration = fixtures.create_registration(api, brand["id"], nice_class=8)

    live = fixtures.create_recorded_recordation(
        api, brand["id"], registration["id"], "CBP-0001",
        customs_authority_code=constants.CUSTOMS_AUTHORITY_US_CBP, nice_class=8,
        recorded_on="2026-01-01", expires_on="2026-12-31")
    assert live["status"] == constants.RECORDATION_STATUS_RECORDED, (
        f"Expected {constants.RECORDATION_STATUS_RECORDED}, got {live['status']}")

    colliding = fixtures.create_recordation(
        api, brand["id"], registration["id"],
        customs_authority_code=constants.CUSTOMS_AUTHORITY_US_CBP, nice_class=8,
        recorded_on="2026-12-31", expires_on="2027-06-30")
    assert colliding["status"] == constants.RECORDATION_STATUS_DRAFT, (
        f"Expected {constants.RECORDATION_STATUS_DRAFT}, got {colliding['status']}")

    response = api.record_recordation(colliding["id"], "CBP-0002", headers=fixtures.CUSTOMS)
    validate_error(response, ApiErrorId.RECORDATION_WINDOW_OVERLAP)
    after = validate_success(
        api.get_recordation(colliding["id"], headers=fixtures.CUSTOMS), 200)
    assertions.assert_unchanged(colliding, after)
    assert after["status"] == constants.RECORDATION_STATUS_DRAFT, (
        f"Expected {constants.RECORDATION_STATUS_DRAFT}, got {after['status']}")
    assert after["recordation_number"] is None, (
        f"Expected recordation_number null, got {after['recordation_number']}")

    # Starting the very next day is clean.
    adjacent = fixtures.create_recordation(
        api, brand["id"], registration["id"],
        customs_authority_code=constants.CUSTOMS_AUTHORITY_US_CBP, nice_class=8,
        recorded_on="2027-01-01", expires_on="2027-12-31")
    recorded = fixtures.record_recordation(api, adjacent["id"], "CBP-0003")
    assert recorded["status"] == constants.RECORDATION_STATUS_RECORDED, (
        f"Expected {constants.RECORDATION_STATUS_RECORDED}, got {recorded['status']}")

    # The same shared boundary under a different authority is a different scope.
    other_authority = fixtures.create_recordation(
        api, brand["id"], registration["id"],
        customs_authority_code=constants.CUSTOMS_AUTHORITY_EU_TAXUD, nice_class=8,
        recorded_on="2026-12-31", expires_on="2027-06-30")
    recorded_elsewhere = fixtures.record_recordation(api, other_authority["id"], "EU-0001")
    assert recorded_elsewhere["status"] == constants.RECORDATION_STATUS_RECORDED, (
        f"Expected {constants.RECORDATION_STATUS_RECORDED}, got {recorded_elsewhere['status']}")


def test_recordation_status_check_outranks_the_principal_register_check(api):
    """When a mark is both unregistered and off the principal register, 45 beats 46.

    PRD §2.9: "When a request violates more than one rule, exactly one error is returned: the violation with the **lowest priority number** in the ladder below."
    PRD §2.9: "**Priority 45** — the asserted trademark registration is enforceable, meaning its status is `REGISTERED` rather than `PENDING` or `LAPSED`, and, for enrolment activation, its `nice_class` matches the requested class; else `ERR_REGISTRATION_NOT_ELIGIBLE` (422). Applies to four operations: activating an enrolment, drafting a takedown notice, filing a notice, and confirming a customs recordation."
    PRD §2.9: "**Priority 46** — the registration behind a customs recordation sits on the principal register, else `ERR_RECORDATION_NOT_PRINCIPAL_REGISTER` (422). Applies to confirming a customs recordation."
    PRD §3.10: "That registration's `principal_register` flag must be true, because supplemental-register marks are not recordable, and a false flag is `ERR_RECORDATION_NOT_PRINCIPAL_REGISTER` (HTTP 422)."
    Design: Corner/validations/recordation_status_check_outranks_the_principal_register_check
    """
    fixtures.set_clock(api, "2026-08-05T09:00:00Z")
    brand = fixtures.create_brand(api)

    both_faults = fixtures.create_registration(
        api, brand["id"], nice_class=8,
        status=constants.REGISTRATION_STATUS_PENDING, principal_register=False)
    draft = fixtures.create_recordation(
        api, brand["id"], both_faults["id"],
        customs_authority_code=constants.CUSTOMS_AUTHORITY_US_CBP, nice_class=8)
    response = api.record_recordation(draft["id"], "CBP-1001", headers=fixtures.CUSTOMS)
    validate_error(response, ApiErrorId.REGISTRATION_NOT_ELIGIBLE)
    after = validate_success(api.get_recordation(draft["id"], headers=fixtures.CUSTOMS), 200)
    assertions.assert_unchanged(draft, after)
    assert after["recordation_number"] is None, (
        f"Expected recordation_number null, got {after['recordation_number']}")

    # Repairing only the status leaves the register fault, which now surfaces.
    supplemental = fixtures.create_registration(
        api, brand["id"], nice_class=8,
        status=constants.REGISTRATION_STATUS_REGISTERED, principal_register=False)
    draft = fixtures.create_recordation(
        api, brand["id"], supplemental["id"],
        customs_authority_code=constants.CUSTOMS_AUTHORITY_US_CBP, nice_class=8)
    response = api.record_recordation(draft["id"], "CBP-1002", headers=fixtures.CUSTOMS)
    validate_error(response, ApiErrorId.RECORDATION_NOT_PRINCIPAL_REGISTER)
    assert validate_success(
        api.get_recordation(draft["id"], headers=fixtures.CUSTOMS), 200)["status"] == (
        constants.RECORDATION_STATUS_DRAFT), "Expected the row to stay DRAFT"

    # Repairing both premises lets the same confirmation through.
    clean = fixtures.create_registration(
        api, brand["id"], nice_class=8,
        status=constants.REGISTRATION_STATUS_REGISTERED, principal_register=True)
    draft = fixtures.create_recordation(
        api, brand["id"], clean["id"],
        customs_authority_code=constants.CUSTOMS_AUTHORITY_US_CBP, nice_class=8)
    recorded = validate_success(
        api.record_recordation(draft["id"], "CBP-1003", headers=fixtures.CUSTOMS), 200)
    assert recorded["status"] == constants.RECORDATION_STATUS_RECORDED, (
        f"Expected {constants.RECORDATION_STATUS_RECORDED}, got {recorded['status']}")
    assert recorded["recordation_number"] == "CBP-1003", (
        f"Expected CBP-1003, got {recorded['recordation_number']}")


def test_authenticate_without_custody_paperwork_returns_chain_of_custody_incomplete(api):
    """A sample with no custody log may be received but never authenticated.

    PRD §3.6: "The `chain_of_custody_ref` custody-log reference (1 to 80 characters, not blank) is optional: when the courier supplied no custody paperwork the receipt is still accepted and the field stays null."
    PRD §3.6: "The row must be `RECEIVED`, and its `chain_of_custody_ref` must be non-null, else the verdict is refused with `ERR_CHAIN_OF_CUSTODY_INCOMPLETE` (HTTP 422)."
    PRD §3.6: "On the **counterfeit** branch the row moves `RECEIVED → AUTHENTICATED_COUNTERFEIT`."
    PRD §3.6: "Neither authentication branch refunds anything: the purchase genuinely happened, so the brand's `enforcement_spend_cents` is untouched by the verdict."
    Design: Corner/validations/authenticate_without_custody_paperwork_returns_chain_of_custody_incomplete
    """
    fixtures.set_clock(api, "2026-08-05T09:00:00Z")
    brand = fixtures.create_brand(api)
    registration = fixtures.create_registration(api, brand["id"], nice_class=8)

    buys = {}
    for tag in ("undocumented", "documented"):
        seller = fixtures.create_seller(api)
        listing = fixtures.create_listing(api, brand["id"], seller["id"], price_cents=3000)
        fixtures.screen_listing(api, listing["id"], 0.92, 0.88)
        claim = fixtures.create_claim(api, brand["id"], listing["id"], registration["id"])
        buys[tag] = fixtures.create_test_buy(
            api, claim["id"], purchase_price_cents=3000, shipping_cents=500, lab_fee_cents=2000)
        buys[tag + "_claim"] = claim
        assertions.assert_test_buy_pricing(buys[tag], 3000, 500, 2000)
        assert buys[tag]["subtotal_cents"] == 5500, (
            f"Expected subtotal_cents 5500, got {buys[tag]['subtotal_cents']}")
        assert buys[tag]["service_fee_cents"] == 660, (
            f"Expected service_fee_cents 660, got {buys[tag]['service_fee_cents']}")
        assert buys[tag]["billable_total_cents"] == 6160, (
            f"Expected billable_total_cents 6160, got {buys[tag]['billable_total_cents']}")

    spend_after_orders = fixtures.read_brand(api, brand["id"])["enforcement_spend_cents"]
    assert spend_after_orders == 12320, f"Expected 12320, got {spend_after_orders}"

    # Receipt without custody paperwork is accepted and leaves the field null.
    received = fixtures.receive_test_buy(
        api, buys["undocumented"]["id"], "LOT-NO-COC", chain_of_custody_ref=None)
    assert received["status"] == constants.TEST_BUY_STATUS_RECEIVED, (
        f"Expected {constants.TEST_BUY_STATUS_RECEIVED}, got {received['status']}")
    assert received["chain_of_custody_ref"] is None, (
        f"Expected chain_of_custody_ref null, got {received['chain_of_custody_ref']}")

    response = api.authenticate_test_buy(
        buys["undocumented"]["id"], constants.AUTHENTICATION_RESULT_COUNTERFEIT, "LAB-NO-COC",
        headers=fixtures.ANALYST)
    validate_error(response, ApiErrorId.CHAIN_OF_CUSTODY_INCOMPLETE)
    unchanged = validate_success(
        api.get_test_buy(buys["undocumented"]["id"], headers=fixtures.ANALYST), 200)
    assertions.assert_unchanged(received, unchanged)
    blocked_claim = fixtures.read_claim(api, buys["undocumented_claim"]["id"])
    assert blocked_claim["substantiation_score"] == 0.00, (
        f"Expected substantiation_score 0.00, got {blocked_claim['substantiation_score']}")

    # The very same verdict lands once the custody log is present.
    fixtures.receive_test_buy(api, buys["documented"]["id"], "LOT-COC", chain_of_custody_ref="COC-9")
    authenticated = fixtures.authenticate_test_buy(
        api, buys["documented"]["id"], constants.AUTHENTICATION_RESULT_COUNTERFEIT, "LAB-COC")
    assert authenticated["status"] == constants.TEST_BUY_STATUS_AUTHENTICATED_COUNTERFEIT, (
        f"Expected {constants.TEST_BUY_STATUS_AUTHENTICATED_COUNTERFEIT}, "
        f"got {authenticated['status']}")

    spend_after_verdicts = fixtures.read_brand(api, brand["id"])["enforcement_spend_cents"]
    assert spend_after_verdicts == 12320, (
        f"Expected the ledger untouched at 12320, got {spend_after_verdicts}")


def test_detention_response_at_the_deadline_second_passes_and_one_second_later_expires(api):
    """The seizure response window admits its final instant and nothing after it.

    PRD §3.10: "For a `BORDER_SEIZURE`, `detention_notice_at` is stamped from the logical clock at creation and `response_due_at` is computed by advancing `detention_notice_at` by seven business days, giving the brand a bounded window in which to answer the detention notice."
    PRD §3.10: "An `EnforcementAnalyst` files the brand's side by supplying `evidence_ref` and `suspected_distributor_ref` (each 1 to 80 characters, not blank), moving `status` `OPEN → EVIDENCE_SUBMITTED`, persisting both references and incrementing `version` by 1."
    PRD §3.10: "For a `BORDER_SEIZURE` the logical clock must be at or before `response_due_at`; the boundary instant itself is still inside the window, and a submission past it is `ERR_SEIZURE_RESPONSE_WINDOW_EXPIRED` (HTTP 422)."
    Design: Corner/validations/detention_response_at_the_deadline_second_passes_and_one_second_later_expires
    """
    notice_instant = "2026-08-05T08:00:00Z"
    fixtures.set_clock(api, notice_instant)
    brand = fixtures.create_brand(api)
    registration = fixtures.create_registration(api, brand["id"], nice_class=8)
    recordation = fixtures.create_recorded_recordation(
        api, brand["id"], registration["id"], "CBP-2001",
        customs_authority_code=constants.CUSTOMS_AUTHORITY_US_CBP, nice_class=8)

    inside = fixtures.create_border_seizure_investigation(
        api, brand["id"], recordation["id"], lot_code="LOT-SZ-1")
    outside = fixtures.create_border_seizure_investigation(
        api, brand["id"], recordation["id"], lot_code="LOT-SZ-2")

    deadline = assertions.add_business_days(notice_instant, 7)
    assert deadline == "2026-08-14T08:00:00Z", f"Expected 2026-08-14T08:00:00Z, got {deadline}"
    for investigation in (inside, outside):
        assert investigation["status"] == constants.INVESTIGATION_STATUS_OPEN, (
            f"Expected {constants.INVESTIGATION_STATUS_OPEN}, got {investigation['status']}")
        assert _to_whole_second(investigation["detention_notice_at"]) == notice_instant, (
            f"Expected {notice_instant}, got {investigation['detention_notice_at']}")
        assert _to_whole_second(investigation["response_due_at"]) == deadline, (
            f"Expected {deadline}, got {investigation['response_due_at']}")

    fixtures.set_clock(api, deadline)
    filed = fixtures.submit_investigation_evidence(api, inside["id"], "EVID-EDGE", "DIST-EDGE")
    assert filed["status"] == constants.INVESTIGATION_STATUS_EVIDENCE_SUBMITTED, (
        f"Expected {constants.INVESTIGATION_STATUS_EVIDENCE_SUBMITTED}, got {filed['status']}")
    assert filed["evidence_ref"] == "EVID-EDGE", (
        f"Expected EVID-EDGE, got {filed['evidence_ref']}")
    assert filed["suspected_distributor_ref"] == "DIST-EDGE", (
        f"Expected DIST-EDGE, got {filed['suspected_distributor_ref']}")
    assert filed["version"] == inside["version"] + 1, (
        f"Expected version {inside['version'] + 1}, got {filed['version']}")

    fixtures.set_clock(api, assertions.add_seconds(deadline, 1))
    response = api.submit_investigation_evidence(
        outside["id"], "EVID-LATE", "DIST-LATE", headers=fixtures.ANALYST)
    validate_error(response, ApiErrorId.SEIZURE_RESPONSE_WINDOW_EXPIRED)
    untouched = validate_success(
        api.get_investigation(outside["id"], headers=fixtures.CUSTOMS), 200)
    assertions.assert_unchanged(outside, untouched)
    assert untouched["status"] == constants.INVESTIGATION_STATUS_OPEN, (
        f"Expected {constants.INVESTIGATION_STATUS_OPEN}, got {untouched['status']}")
    assert untouched["evidence_ref"] is None, (
        f"Expected evidence_ref null, got {untouched['evidence_ref']}")


def test_test_buy_investigation_with_a_foreign_lot_code_returns_lot_code_not_traceable(api):
    """A test-buy trace needs an authenticated counterfeit sample bearing that lot.

    PRD §3.10: "The row is created with `status` `OPEN`."
    PRD §3.10: "A `TEST_BUY` must carry `source_test_buy_id` and leaves `recordation_id` and the four detention details null."
    PRD §3.10: "For a `TEST_BUY`, both `detention_notice_at` and `response_due_at` stay null — there is no customs clock on a test-buy trace — and instead the lot code is verified at creation against the named source test buy: that test buy must be `AUTHENTICATED_COUNTERFEIT` and its `lot_code` must equal the investigation's `lot_code`, else `ERR_LOT_CODE_NOT_TRACEABLE` (HTTP 422)."
    Design: Corner/validations/test_buy_investigation_with_a_foreign_lot_code_returns_lot_code_not_traceable
    """
    fixtures.set_clock(api, "2026-08-05T09:00:00Z")
    brand = fixtures.create_brand(api)
    registration = fixtures.create_registration(api, brand["id"], nice_class=8)

    def order_buy():
        seller = fixtures.create_seller(api)
        listing = fixtures.create_listing(api, brand["id"], seller["id"], price_cents=3000)
        fixtures.screen_listing(api, listing["id"], 0.92, 0.88)
        claim = fixtures.create_claim(api, brand["id"], listing["id"], registration["id"])
        return fixtures.create_test_buy(api, claim["id"])

    traceable = order_buy()
    fixtures.receive_test_buy(api, traceable["id"], "LOT-77", chain_of_custody_ref="COC-77")
    authenticated = fixtures.authenticate_test_buy(
        api, traceable["id"], constants.AUTHENTICATION_RESULT_COUNTERFEIT, "LAB-77")
    assert authenticated["lot_code"] == "LOT-77", (
        f"Expected lot_code LOT-77, got {authenticated['lot_code']}")

    # A lot code the sample does not bear is not traceable.
    response = api.create_investigation(
        factories.test_buy_investigation_payload(brand["id"], traceable["id"], lot_code="LOT-88"),
        headers=fixtures.CUSTOMS)
    validate_error(response, ApiErrorId.LOT_CODE_NOT_TRACEABLE)
    rows, meta = validate_paginated(api.list_investigations(
        headers=fixtures.CUSTOMS, source_test_buy_id=traceable["id"]))
    assert meta["total_count"] == 0, f"Expected total_count 0, got {meta['total_count']}"
    assert rows == [], f"Expected no investigation rows, got {rows}"

    # A matching lot code on an authenticated counterfeit sample is traceable.
    response = api.create_investigation(
        factories.test_buy_investigation_payload(brand["id"], traceable["id"], lot_code="LOT-77"),
        headers=fixtures.CUSTOMS)
    opened = validate_success(response, 201)
    assert opened["status"] == constants.INVESTIGATION_STATUS_OPEN, (
        f"Expected {constants.INVESTIGATION_STATUS_OPEN}, got {opened['status']}")
    assert opened["source_test_buy_id"] == traceable["id"], (
        f"Expected source_test_buy_id {traceable['id']}, got {opened['source_test_buy_id']}")
    for field in ("recordation_id", "detention_notice_at", "response_due_at",
                  "seizure_ref", "port_code", "seized_qty", "declared_value_cents"):
        assert opened[field] is None, f"Expected {field} null on a test-buy trace, got {opened[field]}"

    # A sample that was merely received, never authenticated, is not traceable either.
    unauthenticated = order_buy()
    fixtures.receive_test_buy(api, unauthenticated["id"], "LOT-99", chain_of_custody_ref="COC-99")
    response = api.create_investigation(
        factories.test_buy_investigation_payload(
            brand["id"], unauthenticated["id"], lot_code="LOT-99"),
        headers=fixtures.CUSTOMS)
    validate_error(response, ApiErrorId.LOT_CODE_NOT_TRACEABLE)


def test_litigation_ladder_requires_an_answered_letter_then_a_second_representative(api):
    """Litigation needs a closed correspondence loop and a different signatory.

    PRD §3.9: "And the case's seller must be `UNDER_INVESTIGATION` or `BLOCKED`, because correspondence may only be aimed at an escalated seller; a still-`ACTIVE` seller is refused with `ERR_SELLER_NOT_UNDER_INVESTIGATION` (HTTP 422)."
    PRD §3.9: "Sending the letter stamps `cease_desist_sent_by_rep_id` with the acting `X-User-ID` — this is the pin that the segregation-of-duties rule reads later — sets `cd_sent_at` from the logical clock, persists `letter_ref`, computes `cd_response_due_at` by advancing `cd_sent_at` by fourteen business days, and increments the case's `version` by 1."
    PRD §3.9: "The case must be at `CD_SENT` and the logical clock must be at or before `cd_response_due_at`; the track then advances `CD_SENT → CD_RESPONDED`, `response_kind` is persisted, and `version` is incremented by 1."
    PRD §3.9: "The correspondence track must have been answered or have lapsed — `CD_RESPONDED` or `CD_IGNORED` — else `ERR_CEASE_DESIST_NOT_ANSWERED` (HTTP 409); a case still at `CD_SENT`, or one where no letter was ever sent, cannot reach litigation."
    PRD §3.9: "The acting `X-User-ID` must differ from the case's `cease_desist_sent_by_rep_id`, else `ERR_SEGREGATION_OF_DUTIES` (HTTP 409)."
    PRD §3.9: "On success `litigation_authorized_by_rep_id` is stamped with the acting `X-User-ID`, the roll-up moves `case_status` `OPEN → IN_LITIGATION`, and `version` is incremented by 1."
    PRD §3.9: "`litigation_status` advances `AUTHORIZED → FILED`, `docket_ref` is persisted, `case_status` stays `IN_LITIGATION`, and `version` is incremented by 1."
    PRD §3.9: "On every outcome, `closure_outcome` is persisted, the roll-up sets `case_status` to `CLOSED`, and `version` is incremented by 1."
    PRD §3.9: "Closure never reverses strikes already attributed — the ledger records what happened, and a settlement does not unsay it."
    Design: Corner/validations/litigation_ladder_requires_an_answered_letter_then_a_second_representative
    """
    sent_at = "2026-08-05T09:00:00Z"
    fixtures.set_clock(api, sent_at)
    brand = fixtures.create_brand(api)
    registration = fixtures.create_registration(api, brand["id"], nice_class=8)

    # Two agents of record, each able to authorise litigation for this brand.
    first_enrollment = fixtures.create_enrollment(
        api, brand["id"], registration["id"],
        marketplace_code=constants.MARKETPLACE_AMZ, requested_nice_class=8)
    fixtures.activate_enrollment(api, first_enrollment["id"])
    second_enrollment = fixtures.create_enrollment(
        api, brand["id"], registration["id"],
        marketplace_code=constants.MARKETPLACE_EBY, requested_nice_class=8)
    fixtures.activate_enrollment(api, second_enrollment["id"])
    sender = fixtures.create_representative(
        api, first_enrollment["id"], authority_scope=constants.SCOPE_AUTHORIZE_LITIGATION)
    authorizer = fixtures.create_representative(
        api, second_enrollment["id"], authority_scope=constants.SCOPE_AUTHORIZE_LITIGATION)
    assert sender["id"] != authorizer["id"], "Expected two distinct designations"

    seller = fixtures.create_seller(api)
    case = fixtures.create_case(api, brand["id"], seller["id"])
    assert case["correspondence_status"] == constants.CORRESPONDENCE_NONE, (
        f"Expected {constants.CORRESPONDENCE_NONE}, got {case['correspondence_status']}")
    assert case["litigation_status"] == constants.LITIGATION_NONE, (
        f"Expected {constants.LITIGATION_NONE}, got {case['litigation_status']}")

    # Correspondence is only aimed at an escalated seller, so escalate this one.
    ctx = {"brand": brand, "registration": registration, "seller": seller}
    ctx = fixtures.setup_escalated_seller_via_diversion(api, ctx)
    assertions.assert_seller_strikes(
        ctx["seller"], 25.15, 25.15, constants.SELLER_STATUS_UNDER_INVESTIGATION)
    rows, meta = validate_paginated(api.list_cases(
        headers=fixtures.COUNSEL, brand_id=brand["id"], seller_id=seller["id"]))
    assert meta["total_count"] == 1, (
        f"Expected the pre-existing case to be reused, got total_count {meta['total_count']}")
    assert rows[0]["id"] == case["id"], f"Expected case {case['id']}, got {rows[0]['id']}"
    assert rows[0]["originating_takedown_id"] is None, (
        f"Expected originating_takedown_id null, got {rows[0]['originating_takedown_id']}")

    # No letter has ever been sent, so litigation is out of reach.
    before_letter = fixtures.read_case(api, case["id"])
    response = api.authorize_litigation(
        case["id"], "AUTH-EARLY",
        headers=fixtures.make_authorized_representative_headers(authorizer["id"]))
    validate_error(response, ApiErrorId.CEASE_DESIST_NOT_ANSWERED)
    assertions.assert_unchanged(before_letter, fixtures.read_case(api, case["id"]))

    letter = fixtures.send_cease_desist(api, case["id"], sender["id"], letter_ref="CD-LADDER")
    assert letter["correspondence_status"] == constants.CORRESPONDENCE_CD_SENT, (
        f"Expected {constants.CORRESPONDENCE_CD_SENT}, got {letter['correspondence_status']}")
    assert letter["cease_desist_sent_by_rep_id"] == sender["id"], (
        f"Expected {sender['id']}, got {letter['cease_desist_sent_by_rep_id']}")
    assert _to_whole_second(letter["cd_sent_at"]) == sent_at, (
        f"Expected cd_sent_at {sent_at}, got {letter['cd_sent_at']}")
    response_due = assertions.add_business_days(sent_at, 14)
    assert response_due == "2026-08-25T09:00:00Z", (
        f"Expected 2026-08-25T09:00:00Z, got {response_due}")
    assert _to_whole_second(letter["cd_response_due_at"]) == response_due, (
        f"Expected {response_due}, got {letter['cd_response_due_at']}")
    assert letter["version"] == before_letter["version"] + 1, (
        f"Expected version {before_letter['version'] + 1}, got {letter['version']}")

    # A letter still awaiting its answer is not an answered letter.
    response = api.authorize_litigation(
        case["id"], "AUTH-UNANSWERED",
        headers=fixtures.make_authorized_representative_headers(authorizer["id"]))
    validate_error(response, ApiErrorId.CEASE_DESIST_NOT_ANSWERED)
    assertions.assert_unchanged(letter, fixtures.read_case(api, case["id"]))

    answered = fixtures.record_case_response(
        api, case["id"], response_ref="RESP-LADDER",
        response_kind=constants.RESPONSE_KIND_DENIAL)
    assert answered["correspondence_status"] == constants.CORRESPONDENCE_CD_RESPONDED, (
        f"Expected {constants.CORRESPONDENCE_CD_RESPONDED}, got {answered['correspondence_status']}")
    assert answered["response_kind"] == constants.RESPONSE_KIND_DENIAL, (
        f"Expected {constants.RESPONSE_KIND_DENIAL}, got {answered['response_kind']}")
    assert answered["version"] == letter["version"] + 1, (
        f"Expected version {letter['version'] + 1}, got {answered['version']}")

    # The signatory of the letter may not also authorise the suit.
    response = api.authorize_litigation(
        case["id"], "AUTH-SAME-HAND",
        headers=fixtures.make_authorized_representative_headers(sender["id"]))
    validate_error(response, ApiErrorId.SEGREGATION_OF_DUTIES)
    still_open = fixtures.read_case(api, case["id"])
    assertions.assert_unchanged(answered, still_open)
    assert still_open["litigation_status"] == constants.LITIGATION_NONE, (
        f"Expected {constants.LITIGATION_NONE}, got {still_open['litigation_status']}")
    assert still_open["litigation_authorized_by_rep_id"] is None, (
        f"Expected litigation_authorized_by_rep_id null, "
        f"got {still_open['litigation_authorized_by_rep_id']}")
    assert still_open["case_status"] == constants.CASE_STATUS_OPEN, (
        f"Expected {constants.CASE_STATUS_OPEN}, got {still_open['case_status']}")

    # The second representative carries the identical request through.
    authorized = fixtures.authorize_litigation(
        api, case["id"], authorizer["id"], authorization_ref="AUTH-SECOND-HAND")
    assert authorized["litigation_status"] == constants.LITIGATION_AUTHORIZED, (
        f"Expected {constants.LITIGATION_AUTHORIZED}, got {authorized['litigation_status']}")
    assert authorized["litigation_authorized_by_rep_id"] == authorizer["id"], (
        f"Expected {authorizer['id']}, got {authorized['litigation_authorized_by_rep_id']}")
    assert authorized["case_status"] == constants.CASE_STATUS_IN_LITIGATION, (
        f"Expected {constants.CASE_STATUS_IN_LITIGATION}, got {authorized['case_status']}")
    assert authorized["version"] == answered["version"] + 1, (
        f"Expected version {answered['version'] + 1}, got {authorized['version']}")

    filed = validate_success(
        api.file_suit(case["id"], "DOCKET-2026-771", "USDC-CACD", headers=fixtures.COUNSEL), 200)
    assert filed["litigation_status"] == constants.LITIGATION_FILED, (
        f"Expected {constants.LITIGATION_FILED}, got {filed['litigation_status']}")
    assert filed["docket_ref"] == "DOCKET-2026-771", (
        f"Expected DOCKET-2026-771, got {filed['docket_ref']}")
    assert filed["case_status"] == constants.CASE_STATUS_IN_LITIGATION, (
        f"Expected {constants.CASE_STATUS_IN_LITIGATION}, got {filed['case_status']}")
    assert filed["version"] == authorized["version"] + 1, (
        f"Expected version {authorized['version'] + 1}, got {filed['version']}")

    closed = validate_success(
        api.close_case(case["id"], constants.CLOSURE_SETTLED, headers=fixtures.COUNSEL), 200)
    assert closed["closure_outcome"] == constants.CLOSURE_SETTLED, (
        f"Expected {constants.CLOSURE_SETTLED}, got {closed['closure_outcome']}")
    assert closed["case_status"] == constants.CASE_STATUS_CLOSED, (
        f"Expected {constants.CASE_STATUS_CLOSED}, got {closed['case_status']}")
    assert closed["version"] == filed["version"] + 1, (
        f"Expected version {filed['version'] + 1}, got {closed['version']}")

    # A settlement does not unsay the strike that opened the case.
    assertions.assert_seller_strikes(
        fixtures.read_seller(api, seller["id"]), 25.15, 25.15,
        constants.SELLER_STATUS_UNDER_INVESTIGATION)
