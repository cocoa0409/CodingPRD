"""Lifecycle transitions, their cascades and the states they refuse to leave.

Drives the registry, enrolment, designation, claim, test-buy, notice, customs and
case machines through the transitions PRD §3.1 to §3.11 declare, including the
terminal states that refuse a replay, the cascades that run inside the triggering
request per §2.8, and the sweep's clock-idempotency guarantee.
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

# A pinned Wednesday, so every business-day walk in this module is predictable.
PINNED_CLOCK = "2026-08-05T09:00:00Z"


def instant_without_fraction(value: str) -> str:
    """The second-precision prefix of a stamped instant, dropping the millis."""
    assert isinstance(value, str) and len(value) >= 19, f"Expected an instant, got {value!r}"
    return value[:19]


def assert_instant_equals(actual: str, expected: str, label: str) -> None:
    """Compare a stamped instant against an expected instant at second precision."""
    assert instant_without_fraction(actual) == instant_without_fraction(expected), (
        f"Expected {label} {expected}, got {actual}")


def test_registration_lapse_by_sweep_is_terminal_and_replay_changes_nothing(
    api, marketplace_liaison_headers
):
    """The sweep lapses an expired registration once; a replay at the same clock is a no-op.

    PRD §3.11: "Every `REGISTERED` trademark registration whose `expiry_date` has passed moves to `LAPSED`."
    PRD §3.11: "It increments `version` by 1 on every row it actually changes and on no other row."
    PRD §3.11: "And the sweep is idempotent with respect to the clock: running it a second time without advancing the clock changes nothing and returns every count as zero."
    PRD §3.1: "The full domain of the field is `PENDING`, `REGISTERED` and `LAPSED`, but there is no operation in this version that promotes a pending application to registered, and `LAPSED` is reachable only through the sweep's auto-lapse pass, described in §3.11."
    PRD §3.1: "If the brand has never had an enrolment, it stays `DRAFT`."
    Design: Corner/state_machines/registration_lapse_by_sweep_is_terminal_and_replay_changes_nothing
    """
    fixtures.set_clock(api, PINNED_CLOCK)
    brand = fixtures.create_brand(api)
    registration = fixtures.create_registration(api, brand["id"], expiry_date="2026-08-20")
    assert registration["status"] == constants.REGISTRATION_STATUS_REGISTERED, (
        f"Expected status REGISTERED at creation, got {registration['status']}")
    assertions.assert_common_fields(registration, expected_version=1)

    fixtures.set_clock(api, "2026-08-24T09:00:00Z")
    first_sweep = validate_success(
        api.run_enforcement_sweep(headers=marketplace_liaison_headers), 200)
    assertions.assert_sweep_counts(
        first_sweep,
        lapsed_registration_count=1,
        suspended_enrollment_count=0,
        withdrawn_takedown_count=0,
        expired_counter_notice_count=0,
        reinstated_takedown_count=0,
        cd_ignored_case_count=0,
        expired_recordation_count=0,
        escalated_seller_count=0,
        blocked_seller_count=0,
        deescalated_seller_count=0,
    )

    lapsed = validate_success(
        api.get_registration(registration["id"], headers=marketplace_liaison_headers), 200)
    assert lapsed["status"] == constants.REGISTRATION_STATUS_LAPSED, (
        f"Expected status LAPSED after the sweep, got {lapsed['status']}")
    assertions.assert_common_fields(lapsed, expected_version=2)

    replay = validate_success(api.run_enforcement_sweep(headers=marketplace_liaison_headers), 200)
    assertions.assert_all_sweep_counts_zero(replay)

    after_replay = validate_success(
        api.get_registration(registration["id"], headers=marketplace_liaison_headers), 200)
    assertions.assert_unchanged(lapsed, after_replay)
    assert after_replay["status"] == constants.REGISTRATION_STATUS_LAPSED, (
        f"LAPSED is terminal; expected LAPSED, got {after_replay['status']}")

    brand_after = fixtures.read_brand(api, brand["id"])
    assert brand_after["status"] == constants.BRAND_STATUS_DRAFT, (
        f"A brand with no enrolment stays DRAFT, got {brand_after['status']}")
    assertions.assert_unchanged(brand, brand_after)


def test_enrollment_activate_twice_returns_invalid_state(api, marketplace_liaison_headers):
    """A second activation of an already ACTIVE enrolment is refused and re-stamps nothing.

    PRD §3.2: "The marketplace side of the conversation accepts the enrolment, taking it `SUBMITTED → ACTIVE`."
    PRD §3.2: "On success `activated_at` is stamped from the logical clock, the brand's posture is re-derived from `ENROLLMENT_PENDING` to `ENROLLED`, and the enrolment and the brand each have their `version` incremented by 1."
    PRD §2.9: "**Priority 20** — the target row is in a state from which the requested transition exists, including the cross-entity state gates spelled out in §3 (the claim must be substantiated before a notice is filed, the package must be sealed before it is attached, a test buy must be received before it is authenticated, an investigation must have evidence submitted before it may be confirmed as diversion, and the litigation track must be untouched for a no-action closure); else `ERR_INVALID_STATE` (409)."
    PRD §2.9: "Evaluation stops there and nothing is persisted — not even a value the server had already computed."
    Design: Corner/state_machines/enrollment_activate_twice_returns_invalid_state
    """
    fixtures.set_clock(api, PINNED_CLOCK)
    brand = fixtures.create_brand(api)
    registration = fixtures.create_registration(api, brand["id"])
    enrollment = fixtures.create_enrollment(api, brand["id"], registration["id"])
    assert enrollment["enrollment_status"] == constants.ENROLLMENT_STATUS_SUBMITTED, (
        f"Expected SUBMITTED before activation, got {enrollment['enrollment_status']}")
    assert enrollment["activated_at"] is None, (
        f"Expected activated_at null before activation, got {enrollment['activated_at']!r}")

    activated = validate_success(
        api.activate_enrollment(enrollment["id"], headers=marketplace_liaison_headers), 200)
    assert activated["enrollment_status"] == constants.ENROLLMENT_STATUS_ACTIVE, (
        f"Expected ACTIVE after activation, got {activated['enrollment_status']}")
    assert_instant_equals(activated["activated_at"], PINNED_CLOCK, "activated_at")
    assertions.assert_common_fields(activated, expected_version=2)

    brand_enrolled = fixtures.read_brand(api, brand["id"])
    assert brand_enrolled["status"] == constants.BRAND_STATUS_ENROLLED, (
        f"Expected brand ENROLLED, got {brand_enrolled['status']}")
    assertions.assert_common_fields(brand_enrolled, expected_version=3)

    # Moving the clock proves the refused replay does not re-stamp activated_at.
    fixtures.set_clock(api, "2026-08-06T10:00:00Z")
    validate_error(
        api.activate_enrollment(enrollment["id"], headers=marketplace_liaison_headers),
        ApiErrorId.INVALID_STATE,
    )

    after = validate_success(
        api.get_enrollment(enrollment["id"], headers=marketplace_liaison_headers), 200)
    assertions.assert_unchanged(activated, after)
    assert after["enrollment_status"] == constants.ENROLLMENT_STATUS_ACTIVE, (
        f"Expected the enrolment to stay ACTIVE, got {after['enrollment_status']}")
    assert_instant_equals(after["activated_at"], PINNED_CLOCK, "activated_at")

    brand_after = fixtures.read_brand(api, brand["id"])
    assertions.assert_unchanged(brand_enrolled, brand_after)
    assert brand_after["status"] == constants.BRAND_STATUS_ENROLLED, (
        f"Expected the brand to stay ENROLLED, got {brand_after['status']}")


def test_brand_posture_bubbles_up_through_the_whole_enrollment_lifecycle(
    api, brand_administrator_headers
):
    """Every enrolment transition re-derives the owning brand's posture in the same request.

    PRD §3.1: "Consequently a brand walks `DRAFT → ENROLLMENT_PENDING` on its first enrolment, `ENROLLMENT_PENDING → ENROLLED` when an enrolment is activated, `ENROLLED → ENROLLMENT_PENDING` when the last active enrolment leaves the active state while a submitted one remains, `ENROLLED → ENROLLMENT_LAPSED` when the last active enrolment is suspended, superseded or auto-suspended by the sweep and no submitted enrolment remains, `ENROLLMENT_PENDING → ENROLLMENT_LAPSED` when the last submitted enrolment is superseded, and `ENROLLMENT_LAPSED → ENROLLMENT_PENDING` on a re-enrolment."
    PRD §3.1: "Each of those re-derivations increments the brand's `version` by 1, and the last one is reached in the very same request that suspended the enrolment — a brand can go from `ENROLLED` to `ENROLLMENT_LAPSED` inside a single registration-lapse cascade."
    PRD §3.2: "The new row lands in `enrollment_status` `SUBMITTED` with `activated_at`, `suspension_reason_code` and `superseded_by_enrollment_id` all null, and the owning brand's posture is immediately re-derived, which increments the brand's `version` by 1."
    PRD §3.2: "A `MarketplaceLiaison` may suspend an `ACTIVE` enrolment, taking it `ACTIVE → SUSPENDED`, supplying a `reason_code` which is persisted as `suspension_reason_code` and must be one of `MANUAL`, `REGISTRATION_LAPSED` or `MARKETPLACE_ACTION`."
    Design: Corner/state_machines/brand_posture_bubbles_up_through_the_whole_enrollment_lifecycle
    """
    fixtures.set_clock(api, PINNED_CLOCK)
    brand = fixtures.create_brand(api)
    assert brand["status"] == constants.BRAND_STATUS_DRAFT, (
        f"Expected a fresh brand to be DRAFT, got {brand['status']}")
    assertions.assert_common_fields(brand, expected_version=1)

    registration = fixtures.create_registration(api, brand["id"])
    amz = fixtures.create_enrollment(api, brand["id"], registration["id"])
    assert amz["enrollment_status"] == constants.ENROLLMENT_STATUS_SUBMITTED, (
        f"Expected SUBMITTED, got {amz['enrollment_status']}")
    assert amz["superseded_by_enrollment_id"] is None, (
        f"Expected superseded_by_enrollment_id null, got {amz['superseded_by_enrollment_id']!r}")
    assert amz["suspension_reason_code"] is None, (
        f"Expected suspension_reason_code null, got {amz['suspension_reason_code']!r}")

    pending = fixtures.read_brand(api, brand["id"])
    assert pending["status"] == constants.BRAND_STATUS_ENROLLMENT_PENDING, (
        f"Expected ENROLLMENT_PENDING after the first enrolment, got {pending['status']}")
    assertions.assert_common_fields(pending, expected_version=2)

    fixtures.activate_enrollment(api, amz["id"])
    enrolled = fixtures.read_brand(api, brand["id"])
    assert enrolled["status"] == constants.BRAND_STATUS_ENROLLED, (
        f"Expected ENROLLED after activation, got {enrolled['status']}")
    assertions.assert_common_fields(enrolled, expected_version=3)

    suspended = fixtures.suspend_enrollment(api, amz["id"], constants.SUSPENSION_REASON_MARKETPLACE_ACTION)
    assert suspended["enrollment_status"] == constants.ENROLLMENT_STATUS_SUSPENDED, (
        f"Expected SUSPENDED, got {suspended['enrollment_status']}")
    assert suspended["suspension_reason_code"] == constants.SUSPENSION_REASON_MARKETPLACE_ACTION, (
        f"Expected suspension_reason_code MARKETPLACE_ACTION, got "
        f"{suspended['suspension_reason_code']}")

    lapsed = fixtures.read_brand(api, brand["id"])
    assert lapsed["status"] == constants.BRAND_STATUS_ENROLLMENT_LAPSED, (
        f"Expected ENROLLMENT_LAPSED once the last active enrolment is suspended, got "
        f"{lapsed['status']}")
    assertions.assert_common_fields(lapsed, expected_version=4)

    eby = fixtures.create_enrollment(api, brand["id"], registration["id"], marketplace_code="EBY")
    assert eby["enrollment_status"] == constants.ENROLLMENT_STATUS_SUBMITTED, (
        f"Expected the re-enrolment to be SUBMITTED, got {eby['enrollment_status']}")

    re_pending = fixtures.read_brand(api, brand["id"])
    assert re_pending["status"] == constants.BRAND_STATUS_ENROLLMENT_PENDING, (
        f"Expected ENROLLMENT_PENDING on re-enrolment, got {re_pending['status']}")
    assertions.assert_common_fields(re_pending, expected_version=5)


def test_enrollment_suspension_withdraws_the_in_flight_takedown_and_reopens_the_listing(api):
    """Suspending the filing enrolment withdraws its live notice and releases the listing.

    PRD §3.2: "At the first level, every takedown notice filed through this enrolment whose status is `DRAFT` or `SUBMITTED` moves to `WITHDRAWN`."
    PRD §3.2: "At the second level, because those notices were withdrawn, each of them reaches through its claim to that claim's listing, and any such listing whose `enforcement_status` is `TAKEDOWN_PENDING` is released back to `CLAIM_OPEN`."
    PRD §3.2: "At the third level, because those listings left `TAKEDOWN_PENDING`, every claim on such a listing whose status is `ENFORCED` is demoted back to `SUBSTANTIATED`."
    PRD §3.3: "It exists for as long as a takedown notice sits in status `APPROVED_REMOVED`; its effective instant is that notice's `decided_at`, and it is attributed to the seller that owns the listing behind the notice's claim."
    PRD §3.11: "Notices at `DRAFT`, `SUBMITTED`, `COUNTER_NOTICED` or `WITHDRAWN` appear in neither count: an in-flight or abandoned notice is not a marketplace decision."
    PRD §3.11: "When `decided_takedown_count` is zero the rate is exactly 0.0000 — not null, not an error, and not 1.0000."
    Design: Corner/state_machines/enrollment_suspension_withdraws_the_in_flight_takedown_and_reopens_the_listing
    """
    ctx = fixtures.setup_submitted_takedown(api, clock=PINNED_CLOCK)
    assert ctx["takedown"]["status"] == constants.TAKEDOWN_STATUS_SUBMITTED, (
        f"Expected the notice SUBMITTED before suspension, got {ctx['takedown']['status']}")
    listing_pending = fixtures.read_listing(api, ctx["listing"]["id"])
    assert listing_pending["enforcement_status"] == constants.ENFORCEMENT_STATUS_TAKEDOWN_PENDING, (
        f"Expected TAKEDOWN_PENDING before suspension, got "
        f"{listing_pending['enforcement_status']}")

    suspended = fixtures.suspend_enrollment(
        api, ctx["enrollment"]["id"], constants.SUSPENSION_REASON_MANUAL)
    assert suspended["enrollment_status"] == constants.ENROLLMENT_STATUS_SUSPENDED, (
        f"Expected SUSPENDED, got {suspended['enrollment_status']}")
    assert suspended["suspension_reason_code"] == constants.SUSPENSION_REASON_MANUAL, (
        f"Expected suspension_reason_code MANUAL, got {suspended['suspension_reason_code']}")

    takedown = fixtures.read_takedown(api, ctx["takedown"]["id"])
    assert takedown["status"] == constants.TAKEDOWN_STATUS_WITHDRAWN, (
        f"Expected the in-flight notice WITHDRAWN, got {takedown['status']}")

    listing = fixtures.read_listing(api, ctx["listing"]["id"])
    assert listing["enforcement_status"] == constants.ENFORCEMENT_STATUS_CLAIM_OPEN, (
        f"Expected the listing released to CLAIM_OPEN, got {listing['enforcement_status']}")
    assert listing["monitor_status"] == constants.MONITOR_STATUS_FLAGGED, (
        f"Expected the screening dimension to stay FLAGGED, got {listing['monitor_status']}")

    claim = fixtures.read_claim(api, ctx["claim"]["id"])
    assert claim["status"] == constants.CLAIM_STATUS_SUBSTANTIATED, (
        f"Expected the claim to stay SUBSTANTIATED, got {claim['status']}")

    seller = fixtures.read_seller(api, ctx["seller"]["id"])
    assertions.assert_seller_strikes(seller, 0.00, 0.00, constants.SELLER_STATUS_ACTIVE)

    metrics = fixtures.read_metrics(api, ctx["brand"]["id"])
    assertions.assert_metrics(
        metrics,
        decided_takedown_count=0,
        removed_takedown_count=0,
        listing_removal_rate=0.0000,
        open_case_count=0,
        repeat_infringer_count=0,
    )

    brand = fixtures.read_brand(api, ctx["brand"]["id"])
    assert brand["status"] == constants.BRAND_STATUS_ENROLLMENT_LAPSED, (
        f"Expected the brand ENROLLMENT_LAPSED, got {brand['status']}")


def test_superseding_enrollment_terminates_the_suspended_row_and_revokes_its_designations(
    api, brand_administrator_headers
):
    """A fresh enrolment on the same marketplace terminates the old row and revokes its agents.

    PRD §3.2: "Supersession is the only path by which an enrolment ever reaches `TERMINATED`: the older row moves `SUBMITTED → TERMINATED` or `SUSPENDED → TERMINATED`, its `superseded_by_enrollment_id` is set to the new enrolment's `id`, and every representative designation still attached to it and still `DESIGNATED` moves to `REVOKED` with `revoked_at` stamped from the logical clock."
    PRD §3.2: "The brand's posture is re-derived, and the superseded row, each revoked designation and the brand each have their `version` incremented by 1."
    PRD §3.2: "The new row lands in `enrollment_status` `SUBMITTED` with `activated_at`, `suspension_reason_code` and `superseded_by_enrollment_id` all null, and the owning brand's posture is immediately re-derived, which increments the brand's `version` by 1."
    PRD §3.1: "Otherwise, if any enrolment of the brand is `SUBMITTED`, the brand is `ENROLLMENT_PENDING`."
    Design: Corner/state_machines/superseding_enrollment_terminates_the_suspended_row_and_revokes_its_designations
    """
    ctx = fixtures.setup_enrolled_brand(api, clock=PINNED_CLOCK)
    old_enrollment = ctx["enrollment"]
    representative = ctx["representative"]
    assert representative["designation_status"] == constants.DESIGNATION_STATUS_DESIGNATED, (
        f"Expected DESIGNATED, got {representative['designation_status']}")

    fixtures.suspend_enrollment(api, old_enrollment["id"], constants.SUSPENSION_REASON_MANUAL)
    brand_lapsed = fixtures.read_brand(api, ctx["brand"]["id"])
    assert brand_lapsed["status"] == constants.BRAND_STATUS_ENROLLMENT_LAPSED, (
        f"Expected ENROLLMENT_LAPSED before the re-enrolment, got {brand_lapsed['status']}")
    assertions.assert_common_fields(brand_lapsed, expected_version=4)

    supersession_clock = "2026-08-06T11:00:00Z"
    fixtures.set_clock(api, supersession_clock)
    new_enrollment = fixtures.create_enrollment(
        api, ctx["brand"]["id"], ctx["registration"]["id"])
    assert new_enrollment["enrollment_status"] == constants.ENROLLMENT_STATUS_SUBMITTED, (
        f"Expected the new row SUBMITTED, got {new_enrollment['enrollment_status']}")
    assert new_enrollment["superseded_by_enrollment_id"] is None, (
        f"Expected the new row's superseded_by_enrollment_id null, got "
        f"{new_enrollment['superseded_by_enrollment_id']!r}")
    assert new_enrollment["activated_at"] is None, (
        f"Expected the new row's activated_at null, got {new_enrollment['activated_at']!r}")
    assert new_enrollment["suspension_reason_code"] is None, (
        f"Expected the new row's suspension_reason_code null, got "
        f"{new_enrollment['suspension_reason_code']!r}")

    terminated = validate_success(
        api.get_enrollment(old_enrollment["id"], headers=brand_administrator_headers), 200)
    assert terminated["enrollment_status"] == constants.ENROLLMENT_STATUS_TERMINATED, (
        f"Expected the superseded row TERMINATED, got {terminated['enrollment_status']}")
    assert terminated["superseded_by_enrollment_id"] == new_enrollment["id"], (
        f"Expected superseded_by_enrollment_id {new_enrollment['id']}, got "
        f"{terminated['superseded_by_enrollment_id']}")
    assertions.assert_common_fields(terminated, expected_version=4)

    revoked = validate_success(
        api.get_representative(representative["id"], headers=brand_administrator_headers), 200)
    assert revoked["designation_status"] == constants.DESIGNATION_STATUS_REVOKED, (
        f"Expected the designation REVOKED, got {revoked['designation_status']}")
    assert_instant_equals(revoked["revoked_at"], supersession_clock, "revoked_at")
    assertions.assert_common_fields(revoked, expected_version=2)

    brand_after = fixtures.read_brand(api, ctx["brand"]["id"])
    assert brand_after["status"] == constants.BRAND_STATUS_ENROLLMENT_PENDING, (
        f"Expected ENROLLMENT_PENDING after the re-enrolment, got {brand_after['status']}")
    assertions.assert_common_fields(brand_after, expected_version=5)

    rows, meta = validate_paginated(
        api.list_enrollments(
            headers=brand_administrator_headers,
            brand_id=ctx["brand"]["id"],
            marketplace_code="AMZ",
        )
    )
    assert meta["total_count"] == 2, (
        f"Expected 2 AMZ enrolments for the brand, got {meta['total_count']}")
    assert {row["id"] for row in rows} == {old_enrollment["id"], new_enrollment["id"]}, (
        "Expected both the terminated row and its successor in the AMZ list")


def test_second_enrollment_on_a_marketplace_with_an_active_row_is_rejected(
    api, brand_administrator_headers
):
    """An ACTIVE row blocks a second enrolment on the same marketplace but not on another.

    PRD §3.2: "A brand may hold only one `ACTIVE` enrolment per marketplace; attempting to create a second while one is already active on the same `marketplace_code` is refused with `ERR_DUPLICATE_ENROLLMENT` (HTTP 409)."
    PRD §2.7: "The refusal is caused only by the stale premise: a brand may hold one active enrolment per marketplace, so a second enrolment create that quotes the current brand `version` and names a different `marketplace_code` succeeds normally."
    PRD §2.9: "Evaluation stops there and nothing is persisted — not even a value the server had already computed."
    PRD §3.1: "If any enrolment of the brand is `ACTIVE`, the brand is `ENROLLED`."
    Design: Corner/state_machines/second_enrollment_on_a_marketplace_with_an_active_row_is_rejected
    """
    ctx = fixtures.setup_enrolled_brand(api, clock=PINNED_CLOCK)
    brand_enrolled = fixtures.read_brand(api, ctx["brand"]["id"])
    assert brand_enrolled["status"] == constants.BRAND_STATUS_ENROLLED, (
        f"Expected ENROLLED, got {brand_enrolled['status']}")
    assertions.assert_common_fields(brand_enrolled, expected_version=3)

    duplicate = factories.enrollment_payload(
        ctx["brand"]["id"], ctx["registration"]["id"], brand_enrolled["version"],
        marketplace_code="AMZ")
    validate_error(
        api.create_enrollment(duplicate, headers=brand_administrator_headers),
        ApiErrorId.DUPLICATE_ENROLLMENT,
    )

    brand_after = fixtures.read_brand(api, ctx["brand"]["id"])
    assertions.assert_unchanged(brand_enrolled, brand_after)
    assert brand_after["status"] == constants.BRAND_STATUS_ENROLLED, (
        f"Expected the brand to stay ENROLLED, got {brand_after['status']}")

    rows, meta = validate_paginated(
        api.list_enrollments(
            headers=brand_administrator_headers,
            brand_id=ctx["brand"]["id"],
            marketplace_code="AMZ",
        )
    )
    assert meta["total_count"] == 1, (
        f"Expected the refused create to persist nothing, got {meta['total_count']} AMZ enrolments")

    # The brand version was never consumed, so the same quoted version still works elsewhere.
    other_marketplace = factories.enrollment_payload(
        ctx["brand"]["id"], ctx["registration"]["id"], brand_enrolled["version"],
        marketplace_code="EBY")
    accepted = validate_success(
        api.create_enrollment(other_marketplace, headers=brand_administrator_headers), 201)
    assert accepted["marketplace_code"] == "EBY", (
        f"Expected marketplace_code EBY, got {accepted['marketplace_code']}")
    assert accepted["enrollment_status"] == constants.ENROLLMENT_STATUS_SUBMITTED, (
        f"Expected SUBMITTED, got {accepted['enrollment_status']}")

    brand_final = fixtures.read_brand(api, ctx["brand"]["id"])
    assert brand_final["status"] == constants.BRAND_STATUS_ENROLLED, (
        f"Expected ENROLLED to outrank the new SUBMITTED row, got {brand_final['status']}")
    assertions.assert_common_fields(brand_final, expected_version=4)


def test_claim_dismissal_withdraws_its_live_packages_and_releases_the_listing(
    api, enforcement_analyst_headers
):
    """Withdrawing a claim releases the listing's enforcement dimension and kills its packages.

    PRD §3.5: "An `EnforcementAnalyst` may withdraw a claim that is `DRAFT` or `SUBSTANTIATED`, supplying a `reason_code` for the audit trail; the claim moves to `DISMISSED` and its `dismissal_reason_code` is set to `ANALYST_WITHDRAWN`."
    PRD §3.5: "On success two cascades follow: the listing's `enforcement_status` is re-derived, falling `CLAIM_OPEN → NONE` once no open claim remains on it, and every evidence package of the claim whose status is `ASSEMBLING` or `SEALED` moves to `WITHDRAWN`."
    PRD §3.5: "`DISMISSED` is terminal: a dismissed claim never returns to any other status."
    PRD §3.4: "A re-screen may flip `FLAGGED → CLEARED` while the enforcement dimension stays at `REMOVED`, and a marketplace decision may move the enforcement dimension while the screening dimension stays `FLAGGED`."
    PRD §2.9: "Evaluation stops there and nothing is persisted — not even a value the server had already computed."
    Design: Corner/state_machines/claim_dismissal_withdraws_its_live_packages_and_releases_the_listing
    """
    ctx = fixtures.setup_claim(
        api, clock=PINNED_CLOCK, claimed_violation_type=constants.VIOLATION_TYPE_COUNTERFEIT)
    listing_open = fixtures.read_listing(api, ctx["listing"]["id"])
    assert listing_open["enforcement_status"] == constants.ENFORCEMENT_STATUS_CLAIM_OPEN, (
        f"Expected CLAIM_OPEN while the claim is live, got {listing_open['enforcement_status']}")

    package = fixtures.create_evidence_package(api, ctx["claim"]["id"])
    assert package["status"] == constants.PACKAGE_STATUS_ASSEMBLING, (
        f"Expected ASSEMBLING, got {package['status']}")
    fixtures.append_items(
        api, package["id"], [(constants.ITEM_LISTING_SCREENSHOT, "LIS-DISMISS-1")])
    assembling = fixtures.read_evidence_package(api, package["id"])
    expected_completeness = assertions.completeness_score(1, 4, 0)
    assertions.assert_package_derivations(
        assembling, item_count=1, coverage=1, completeness=expected_completeness)
    assertions.assert_score_4dp(assembling["completeness_score"], 0.1750, "completeness_score")

    dismissed = validate_success(
        api.dismiss_claim(
            ctx["claim"]["id"],
            constants.DISMISSAL_ANALYST_WITHDRAWN,
            headers=enforcement_analyst_headers,
        ),
        200,
    )
    assert dismissed["status"] == constants.CLAIM_STATUS_DISMISSED, (
        f"Expected DISMISSED, got {dismissed['status']}")
    assert dismissed["dismissal_reason_code"] == constants.DISMISSAL_ANALYST_WITHDRAWN, (
        f"Expected dismissal_reason_code ANALYST_WITHDRAWN, got "
        f"{dismissed['dismissal_reason_code']}")

    listing = fixtures.read_listing(api, ctx["listing"]["id"])
    assert listing["enforcement_status"] == constants.ENFORCEMENT_STATUS_NONE, (
        f"Expected the listing released to NONE, got {listing['enforcement_status']}")
    assert listing["monitor_status"] == constants.MONITOR_STATUS_FLAGGED, (
        f"Expected the screening dimension to stay FLAGGED, got {listing['monitor_status']}")
    assert listing["violation_type"] == constants.VIOLATION_TYPE_COUNTERFEIT, (
        f"Expected the screened violation_type to stay COUNTERFEIT, got "
        f"{listing['violation_type']}")

    withdrawn = fixtures.read_evidence_package(api, package["id"])
    assert withdrawn["status"] == constants.PACKAGE_STATUS_WITHDRAWN, (
        f"Expected the live package WITHDRAWN, got {withdrawn['status']}")
    assertions.assert_score_4dp(
        withdrawn["completeness_score"], expected_completeness, "completeness_score")
    assert withdrawn["item_count"] == 1, (
        f"Expected item_count to stay 1, got {withdrawn['item_count']}")

    validate_error(
        api.dismiss_claim(
            ctx["claim"]["id"],
            constants.DISMISSAL_ANALYST_WITHDRAWN,
            headers=enforcement_analyst_headers,
        ),
        ApiErrorId.INVALID_STATE,
    )
    after = fixtures.read_claim(api, ctx["claim"]["id"])
    assertions.assert_unchanged(dismissed, after)
    assert after["status"] == constants.CLAIM_STATUS_DISMISSED, (
        f"DISMISSED is terminal; expected DISMISSED, got {after['status']}")


def test_representative_revoke_is_terminal_and_frees_the_overlap_slot(
    api, brand_administrator_headers
):
    """Revocation is a one-way move that releases the window-and-scope slot it occupied.

    PRD §3.2: "A `BrandAdministrator` may revoke a designation at any time while it is `DESIGNATED`, optionally supplying a `reason_code` for the audit trail; the row moves `DESIGNATED → REVOKED`, `revoked_at` is stamped from the logical clock, and its `version` is incremented by 1."
    PRD §3.2: "Revocation releases the window-and-scope occupancy the row held, so a fresh designation may then cover an overlapping window."
    PRD §3.2: "A conflict is refused with `ERR_REPRESENTATIVE_WINDOW_OVERLAP` (HTTP 409)."
    PRD §2.9: "**Priority 20** — the target row is in a state from which the requested transition exists, including the cross-entity state gates spelled out in §3 (the claim must be substantiated before a notice is filed, the package must be sealed before it is attached, a test buy must be received before it is authenticated, an investigation must have evidence submitted before it may be confirmed as diversion, and the litigation track must be untouched for a no-action closure); else `ERR_INVALID_STATE` (409)."
    Design: Corner/state_machines/representative_revoke_is_terminal_and_frees_the_overlap_slot
    """
    ctx = fixtures.setup_enrolled_brand(api, clock=PINNED_CLOCK)
    original = ctx["representative"]
    assert original["designation_status"] == constants.DESIGNATION_STATUS_DESIGNATED, (
        f"Expected DESIGNATED, got {original['designation_status']}")
    assert original["revoked_at"] is None, (
        f"Expected revoked_at null while designated, got {original['revoked_at']!r}")

    blocked = factories.representative_payload(
        ctx["enrollment"]["id"],
        authority_scope=constants.SCOPE_SUBMIT_TAKEDOWN,
        effective_from="2026-08-01T00:00:00Z",
        effective_to="2027-08-01T00:00:00Z",
        power_of_attorney_ref="POA-BLOCKED",
    )
    validate_error(
        api.create_representative(blocked, headers=brand_administrator_headers),
        ApiErrorId.REPRESENTATIVE_WINDOW_OVERLAP,
    )

    revoke_clock = "2026-08-06T11:00:00Z"
    fixtures.set_clock(api, revoke_clock)
    revoked = validate_success(
        api.revoke_representative(
            original["id"], reason_code="POA_TERMINATED", headers=brand_administrator_headers),
        200,
    )
    assert revoked["designation_status"] == constants.DESIGNATION_STATUS_REVOKED, (
        f"Expected REVOKED, got {revoked['designation_status']}")
    assert_instant_equals(revoked["revoked_at"], revoke_clock, "revoked_at")
    assertions.assert_common_fields(revoked, expected_version=2)

    validate_error(
        api.revoke_representative(
            original["id"], reason_code="POA_TERMINATED", headers=brand_administrator_headers),
        ApiErrorId.INVALID_STATE,
    )
    after_replay = validate_success(
        api.get_representative(original["id"], headers=brand_administrator_headers), 200)
    assertions.assert_unchanged(revoked, after_replay)
    assert_instant_equals(after_replay["revoked_at"], revoke_clock, "revoked_at")

    replacement = validate_success(
        api.create_representative(blocked, headers=brand_administrator_headers), 201)
    assert replacement["designation_status"] == constants.DESIGNATION_STATUS_DESIGNATED, (
        f"Expected the replacement DESIGNATED, got {replacement['designation_status']}")
    assert replacement["id"] != original["id"], (
        "Expected the replacement designation to be a new row")

    rows, meta = validate_paginated(
        api.list_representatives(
            headers=brand_administrator_headers,
            enrollment_id=ctx["enrollment"]["id"],
            designation_status=constants.DESIGNATION_STATUS_DESIGNATED,
        )
    )
    assert meta["total_count"] == 1, (
        f"Expected exactly one live designation, got {meta['total_count']}")
    assert rows[0]["id"] == replacement["id"], (
        f"Expected the replacement {replacement['id']}, got {rows[0]['id']}")


def test_test_buy_authenticate_before_receipt_returns_invalid_state(
    api, enforcement_analyst_headers
):
    """An ORDERED purchase cannot take a laboratory verdict, and the refusal stamps nothing.

    PRD §3.6: "The analyst records the laboratory verdict on a `RECEIVED` row by supplying `authentication_result`, which is either `AUTHENTIC` or `COUNTERFEIT`, and the `lab_ref` report reference (1 to 80 characters, not blank)."
    PRD §2.9: "When a request violates more than one rule, exactly one error is returned: the violation with the **lowest priority number** in the ladder below."
    PRD §2.9: "**Priority 20** — the target row is in a state from which the requested transition exists, including the cross-entity state gates spelled out in §3 (the claim must be substantiated before a notice is filed, the package must be sealed before it is attached, a test buy must be received before it is authenticated, an investigation must have evidence submitted before it may be confirmed as diversion, and the litigation track must be untouched for a no-action closure); else `ERR_INVALID_STATE` (409)."
    PRD §3.6: "A purchase of 4200 plus 700 shipping plus no lab fee gives a subtotal of 4900, which sits in the first band at 0.15, a fee of 735 and a billable total of 5635 — and although 5635 falls inside the second band, the rate is not revised to 0.12."
    PRD §3.6: "Otherwise `billable_total_cents` is added to the brand's `enforcement_spend_cents` and the brand's `version` is incremented by 1."
    PRD §3.5: "On success the claim lands in status `DRAFT`, its `registration_strength` and `preliminary_score` are derived immediately, `substantiation_score` starts at 0.00, `dismissal_reason_code` starts null, and the listing's `enforcement_status` advances `NONE → CLAIM_OPEN` with the listing's `version` incremented by 1."
    Design: Corner/state_machines/test_buy_authenticate_before_receipt_returns_invalid_state
    """
    ctx = fixtures.setup_claim(api, clock=PINNED_CLOCK)
    test_buy = fixtures.create_test_buy(api, ctx["claim"]["id"], 4200, 700, 0)
    assert test_buy["status"] == constants.TEST_BUY_STATUS_ORDERED, (
        f"Expected ORDERED, got {test_buy['status']}")
    assertions.assert_test_buy_pricing(test_buy, 4200, 700, 0)
    assertions.assert_cents(test_buy["subtotal_cents"], 4900, "subtotal_cents")
    assertions.assert_cents(test_buy["service_fee_cents"], 735, "service_fee_cents")
    assertions.assert_cents(test_buy["billable_total_cents"], 5635, "billable_total_cents")
    assert test_buy["received_at"] is None, (
        f"Expected received_at null before receipt, got {test_buy['received_at']!r}")

    # The custody reference is also null here, but the state gate outranks it.
    validate_error(
        api.authenticate_test_buy(
            test_buy["id"],
            constants.AUTHENTICATION_RESULT_COUNTERFEIT,
            "LAB-EARLY",
            headers=enforcement_analyst_headers,
        ),
        ApiErrorId.INVALID_STATE,
    )

    after = validate_success(
        api.get_test_buy(test_buy["id"], headers=enforcement_analyst_headers), 200)
    assertions.assert_unchanged(test_buy, after)
    assert after["status"] == constants.TEST_BUY_STATUS_ORDERED, (
        f"Expected the purchase to stay ORDERED, got {after['status']}")
    assert after["authentication_result"] is None, (
        f"Expected authentication_result null, got {after['authentication_result']!r}")
    assert after["lab_ref"] is None, (
        f"Expected lab_ref null, got {after['lab_ref']!r}")
    assert after["lot_code"] is None, (
        f"Expected lot_code null before receipt, got {after['lot_code']!r}")
    assert after["chain_of_custody_ref"] is None, (
        f"Expected chain_of_custody_ref null before receipt, got "
        f"{after['chain_of_custody_ref']!r}")
    assertions.assert_common_fields(after, expected_version=1)

    brand = fixtures.read_brand(api, ctx["brand"]["id"])
    assertions.assert_cents(brand["enforcement_spend_cents"], 5635, "enforcement_spend_cents")

    claim = fixtures.read_claim(api, ctx["claim"]["id"])
    assert claim["status"] == constants.CLAIM_STATUS_DRAFT, (
        f"Expected the claim to stay DRAFT, got {claim['status']}")
    assertions.assert_score_2dp(claim["substantiation_score"], 0.00, "substantiation_score")


def test_authentic_verdict_dismisses_the_claim_clears_the_listing_and_keeps_the_charge(
    api, enforcement_analyst_headers
):
    """An AUTHENTIC verdict collapses the whole thesis but refunds nothing.

    PRD §3.6: "On the **authentic** branch the row moves `RECEIVED → AUTHENTICATED_AUTHENTIC`, and the enforcement thesis collapses."
    PRD §3.6: "The parent claim is auto-dismissed with `dismissal_reason_code` `TEST_BUY_AUTHENTIC`; because the claim was dismissed, the listing's `enforcement_status` falls to `NONE`, its `monitor_status` is set to `CLEARED` and its `violation_type` is reset to `NONE`; and every evidence package of that claim still in `ASSEMBLING` or `SEALED` moves to `WITHDRAWN`."
    PRD §3.6: "Neither authentication branch refunds anything: the purchase genuinely happened, so the brand's `enforcement_spend_cents` is untouched by the verdict."
    PRD §3.5: "On success the claim lands in status `DRAFT`, its `registration_strength` and `preliminary_score` are derived immediately, `substantiation_score` starts at 0.00, `dismissal_reason_code` starts null, and the listing's `enforcement_status` advances `NONE → CLAIM_OPEN` with the listing's `version` incremented by 1."
    Design: Corner/state_machines/authentic_verdict_dismisses_the_claim_clears_the_listing_and_keeps_the_charge
    """
    ctx = fixtures.setup_claim(api, clock=PINNED_CLOCK)
    screened_match_score = fixtures.read_listing(api, ctx["listing"]["id"])["match_score"]
    assertions.assert_score_4dp(screened_match_score, 0.8620, "match_score")

    package = fixtures.create_evidence_package(api, ctx["claim"]["id"])
    fixtures.append_items(
        api, package["id"], [(constants.ITEM_LISTING_SCREENSHOT, "LIS-AUTH-1")])

    test_buy = fixtures.create_test_buy(api, ctx["claim"]["id"], 4200, 700, 0)
    fixtures.receive_test_buy(api, test_buy["id"], "LOT-AUTH-1", "COC-AUTH-1")
    brand_after_order = fixtures.read_brand(api, ctx["brand"]["id"])
    assertions.assert_cents(
        brand_after_order["enforcement_spend_cents"], 5635, "enforcement_spend_cents")

    verdict = validate_success(
        api.authenticate_test_buy(
            test_buy["id"],
            constants.AUTHENTICATION_RESULT_AUTHENTIC,
            "LAB-AUTH-1",
            headers=enforcement_analyst_headers,
        ),
        200,
    )
    assert verdict["status"] == constants.TEST_BUY_STATUS_AUTHENTICATED_AUTHENTIC, (
        f"Expected AUTHENTICATED_AUTHENTIC, got {verdict['status']}")
    assert verdict["authentication_result"] == constants.AUTHENTICATION_RESULT_AUTHENTIC, (
        f"Expected authentication_result AUTHENTIC, got {verdict['authentication_result']}")
    assert verdict["lab_ref"] == "LAB-AUTH-1", (
        f"Expected lab_ref LAB-AUTH-1, got {verdict['lab_ref']}")

    claim = fixtures.read_claim(api, ctx["claim"]["id"])
    assert claim["status"] == constants.CLAIM_STATUS_DISMISSED, (
        f"Expected the claim auto-dismissed, got {claim['status']}")
    assert claim["dismissal_reason_code"] == constants.DISMISSAL_TEST_BUY_AUTHENTIC, (
        f"Expected dismissal_reason_code TEST_BUY_AUTHENTIC, got "
        f"{claim['dismissal_reason_code']}")
    assertions.assert_score_2dp(claim["substantiation_score"], 0.00, "substantiation_score")

    listing = fixtures.read_listing(api, ctx["listing"]["id"])
    assert listing["enforcement_status"] == constants.ENFORCEMENT_STATUS_NONE, (
        f"Expected enforcement_status NONE, got {listing['enforcement_status']}")
    assert listing["monitor_status"] == constants.MONITOR_STATUS_CLEARED, (
        f"Expected monitor_status CLEARED, got {listing['monitor_status']}")
    assert listing["violation_type"] == constants.VIOLATION_TYPE_NONE, (
        f"Expected violation_type reset to NONE, got {listing['violation_type']}")
    assertions.assert_score_4dp(listing["match_score"], 0.8620, "match_score")

    withdrawn = fixtures.read_evidence_package(api, package["id"])
    assert withdrawn["status"] == constants.PACKAGE_STATUS_WITHDRAWN, (
        f"Expected the live package WITHDRAWN, got {withdrawn['status']}")

    brand = fixtures.read_brand(api, ctx["brand"]["id"])
    assertions.assert_cents(brand["enforcement_spend_cents"], 5635, "enforcement_spend_cents")
    assertions.assert_unchanged(brand_after_order, brand)


def test_takedown_cycles_to_round_three_then_refuses_the_fourth_resubmission(
    api, marketplace_liaison_headers
):
    """Three rounds of filing are allowed; a fourth refiling is refused by the round cap.

    PRD §3.8: "The draft lands in status `DRAFT` with `round_number` 0, `submitted_by_rep_id` null, and `submitted_at`, `decision_due_at`, `decided_at`, `counter_notice_deadline_at` and `marketplace_case_ref` all null."
    PRD §3.8: "On a successful filing, `submitted_by_rep_id` is stamped with the acting `X-User-ID`, `submitted_at` is stamped from the logical clock, `round_number` becomes 1, and `decision_due_at` is computed by advancing `submitted_at` by the marketplace's own service-level allowance — five business days for `AMZ`, eight for `EBY`, ten for `WLM` — read from the filing enrolment's `marketplace_code`."
    PRD §3.8: "On a successful refiling, `round_number` is increased by 1, `evidence_package_id` is replaced with the newly supplied one, `submitted_at` and `decision_due_at` are recomputed from the current clock and the marketplace's allowance, and `decided_at`, `marketplace_case_ref` and `counter_notice_deadline_at` are all reset to null."
    PRD §3.8: "Refiling requires a `round_number` strictly below 3, else `ERR_MAX_TAKEDOWN_ROUNDS` (HTTP 409); after three rounds the brand must pursue the seller through correspondence and litigation instead."
    PRD §3.11: "`decided_takedown_count` counts those takedowns whose `status` is `APPROVED_REMOVED`, `REJECTED` or `REINSTATED`."
    PRD §3.11: "`removed_takedown_count` counts those whose `status` is `APPROVED_REMOVED`."
    PRD §3.11: "`listing_removal_rate` is `removed_takedown_count` divided by `decided_takedown_count`, rounded to four decimal places using ROUND_HALF_UP."
    Design: Corner/state_machines/takedown_cycles_to_round_three_then_refuses_the_fourth_resubmission
    """
    ctx = fixtures.setup_drafted_takedown(api, clock=PINNED_CLOCK)
    representative_id = ctx["representative"]["id"]
    draft = ctx["takedown"]
    assert draft["status"] == constants.TAKEDOWN_STATUS_DRAFT, (
        f"Expected DRAFT, got {draft['status']}")
    assert draft["round_number"] == 0, (
        f"Expected round_number 0 on the draft, got {draft['round_number']}")
    assert draft["submitted_by_rep_id"] is None, (
        f"Expected submitted_by_rep_id null on the draft, got {draft['submitted_by_rep_id']!r}")

    later_packages = [
        fixtures.fill_and_seal_package(
            api, ctx["claim"]["id"],
            claimed_violation_type=constants.VIOLATION_TYPE_TRADEMARK,
            tag=tag)
        for tag in ("2", "3", "4")
    ]
    expected_due_at = fixtures.expected_decision_due_at(PINNED_CLOCK, "AMZ")
    assert instant_without_fraction(expected_due_at) == "2026-08-12T09:00:00", (
        f"Expected five AMZ business days to land on 2026-08-12T09:00:00, got {expected_due_at}")

    round_one = fixtures.submit_takedown(api, draft["id"], representative_id)
    assert round_one["status"] == constants.TAKEDOWN_STATUS_SUBMITTED, (
        f"Expected SUBMITTED, got {round_one['status']}")
    assert round_one["round_number"] == 1, (
        f"Expected round_number 1 after the first filing, got {round_one['round_number']}")
    assert round_one["submitted_by_rep_id"] == representative_id, (
        f"Expected submitted_by_rep_id {representative_id}, got "
        f"{round_one['submitted_by_rep_id']}")
    assert_instant_equals(round_one["submitted_at"], PINNED_CLOCK, "submitted_at")
    assert_instant_equals(round_one["decision_due_at"], expected_due_at, "decision_due_at")

    for expected_round, package in enumerate(later_packages[:2], start=2):
        rejected = fixtures.decide_takedown(
            api, draft["id"], constants.DECISION_REJECTED, f"MC-ROUND-{expected_round - 1}")
        assert rejected["status"] == constants.TAKEDOWN_STATUS_REJECTED, (
            f"Expected REJECTED, got {rejected['status']}")
        assert rejected["counter_notice_deadline_at"] is None, (
            f"Expected counter_notice_deadline_at null on a rejection, got "
            f"{rejected['counter_notice_deadline_at']!r}")
        listing_released = fixtures.read_listing(api, ctx["listing"]["id"])
        assert listing_released["enforcement_status"] == constants.ENFORCEMENT_STATUS_CLAIM_OPEN, (
            f"Expected the listing released to CLAIM_OPEN, got "
            f"{listing_released['enforcement_status']}")

        refiled = fixtures.resubmit_takedown(
            api, draft["id"], package["id"], representative_id)
        assert refiled["status"] == constants.TAKEDOWN_STATUS_SUBMITTED, (
            f"Expected SUBMITTED after refiling, got {refiled['status']}")
        assert refiled["round_number"] == expected_round, (
            f"Expected round_number {expected_round}, got {refiled['round_number']}")
        assert refiled["evidence_package_id"] == package["id"], (
            f"Expected evidence_package_id {package['id']}, got {refiled['evidence_package_id']}")
        assert refiled["decided_at"] is None, (
            f"Expected decided_at reset to null, got {refiled['decided_at']!r}")
        assert refiled["marketplace_case_ref"] is None, (
            f"Expected marketplace_case_ref reset to null, got "
            f"{refiled['marketplace_case_ref']!r}")
        assert refiled["counter_notice_deadline_at"] is None, (
            f"Expected counter_notice_deadline_at reset to null, got "
            f"{refiled['counter_notice_deadline_at']!r}")
        assert_instant_equals(refiled["decision_due_at"], expected_due_at, "decision_due_at")

    third_rejection = fixtures.decide_takedown(
        api, draft["id"], constants.DECISION_REJECTED, "MC-ROUND-3")
    assert third_rejection["status"] == constants.TAKEDOWN_STATUS_REJECTED, (
        f"Expected REJECTED, got {third_rejection['status']}")
    assert third_rejection["round_number"] == 3, (
        f"Expected round_number 3 after three filings, got {third_rejection['round_number']}")

    # The fourth attempt presents a genuinely new sealed package of the same claim,
    # so the round cap is the only rule left to break.
    validate_error(
        api.resubmit_takedown(
            draft["id"],
            later_packages[2]["id"],
            headers=fixtures.make_authorized_representative_headers(representative_id),
        ),
        ApiErrorId.MAX_TAKEDOWN_ROUNDS,
    )

    final = fixtures.read_takedown(api, draft["id"])
    assertions.assert_unchanged(third_rejection, final)
    assert final["status"] == constants.TAKEDOWN_STATUS_REJECTED, (
        f"Expected the notice to stay REJECTED, got {final['status']}")
    assert final["round_number"] == 3, (
        f"Expected round_number to stay 3, got {final['round_number']}")
    assert final["evidence_package_id"] == later_packages[1]["id"], (
        f"Expected evidence_package_id {later_packages[1]['id']}, got "
        f"{final['evidence_package_id']}")

    untouched = fixtures.read_evidence_package(api, later_packages[2]["id"])
    assert untouched["status"] == constants.PACKAGE_STATUS_SEALED, (
        f"Expected the unused package to stay SEALED, got {untouched['status']}")

    metrics = fixtures.read_metrics(api, ctx["brand"]["id"])
    assertions.assert_metrics(
        metrics,
        decided_takedown_count=1,
        removed_takedown_count=0,
        listing_removal_rate=0.0000,
    )


def test_recordation_expiry_by_the_sweep_leaves_an_open_investigation_alive(
    api, customs_coordinator_headers, enforcement_analyst_headers, marketplace_liaison_headers
):
    """The sweep expires the lapsed recordation and leaves the in-flight seizure untouched.

    PRD §3.10: "The sweep expires a recordation once the date part of the logical clock has passed its `expires_on`, moving it `RECORDED → EXPIRED` and incrementing `version` by 1; `EXPIRED` is terminal and there is no renewal transition."
    PRD §3.10: "Expiry does not touch investigations: `OPEN` investigations that reference the recordation stay open, because an in-flight seizure survives the recordation lapsing underneath it."
    PRD §3.10: "For a `BORDER_SEIZURE`, `detention_notice_at` is stamped from the logical clock at creation and `response_due_at` is computed by advancing `detention_notice_at` by seven business days, giving the brand a bounded window in which to answer the detention notice."
    PRD §3.10: "An `EnforcementAnalyst` files the brand's side by supplying `evidence_ref` and `suspected_distributor_ref` (each 1 to 80 characters, not blank), moving `status` `OPEN → EVIDENCE_SUBMITTED`, persisting both references and incrementing `version` by 1."
    PRD §3.11: "And the sweep is idempotent with respect to the clock: running it a second time without advancing the clock changes nothing and returns every count as zero."
    Design: Corner/state_machines/recordation_expiry_by_the_sweep_leaves_an_open_investigation_alive
    """
    detention_clock = "2026-08-05T08:00:00Z"
    fixtures.set_clock(api, detention_clock)
    brand = fixtures.create_brand(api)
    registration = fixtures.create_registration(api, brand["id"])
    recordation = fixtures.create_recorded_recordation(
        api, brand["id"], registration["id"],
        recordation_number="CBP-0001",
        customs_authority_code=constants.CUSTOMS_AUTHORITY_US_CBP,
        recorded_on="2026-07-01",
        expires_on="2026-08-10",
    )
    assert recordation["status"] == constants.RECORDATION_STATUS_RECORDED, (
        f"Expected RECORDED, got {recordation['status']}")
    assert recordation["recordation_number"] == "CBP-0001", (
        f"Expected recordation_number CBP-0001, got {recordation['recordation_number']}")
    assertions.assert_common_fields(recordation, expected_version=2)

    seller = fixtures.create_seller(api)
    investigation = fixtures.create_border_seizure_investigation(
        api, brand["id"], recordation["id"], seller_id=seller["id"], lot_code="LOT-DETAINED-1")
    assert investigation["status"] == constants.INVESTIGATION_STATUS_OPEN, (
        f"Expected OPEN, got {investigation['status']}")
    assert_instant_equals(
        investigation["detention_notice_at"], detention_clock, "detention_notice_at")
    expected_response_due_at = assertions.add_business_days(detention_clock, 7)
    assert instant_without_fraction(expected_response_due_at) == "2026-08-14T08:00:00", (
        f"Expected seven business days to land on 2026-08-14T08:00:00, got "
        f"{expected_response_due_at}")
    assert_instant_equals(
        investigation["response_due_at"], expected_response_due_at, "response_due_at")

    fixtures.set_clock(api, "2026-08-12T09:00:00Z")
    sweep = validate_success(api.run_enforcement_sweep(headers=marketplace_liaison_headers), 200)
    assertions.assert_sweep_counts(
        sweep,
        lapsed_registration_count=0,
        suspended_enrollment_count=0,
        withdrawn_takedown_count=0,
        expired_counter_notice_count=0,
        reinstated_takedown_count=0,
        cd_ignored_case_count=0,
        expired_recordation_count=1,
        escalated_seller_count=0,
        blocked_seller_count=0,
        deescalated_seller_count=0,
    )

    expired = validate_success(
        api.get_recordation(recordation["id"], headers=customs_coordinator_headers), 200)
    assert expired["status"] == constants.RECORDATION_STATUS_EXPIRED, (
        f"Expected EXPIRED after the sweep, got {expired['status']}")
    assert expired["recordation_number"] == "CBP-0001", (
        f"Expected recordation_number to survive expiry, got {expired['recordation_number']}")
    assertions.assert_common_fields(expired, expected_version=3)

    survivor = validate_success(
        api.get_investigation(investigation["id"], headers=customs_coordinator_headers), 200)
    assert survivor["status"] == constants.INVESTIGATION_STATUS_OPEN, (
        f"Expected the investigation to stay OPEN, got {survivor['status']}")
    assertions.assert_unchanged(investigation, survivor)

    replay = validate_success(api.run_enforcement_sweep(headers=marketplace_liaison_headers), 200)
    assertions.assert_all_sweep_counts_zero(replay)
    after_replay = validate_success(
        api.get_recordation(recordation["id"], headers=customs_coordinator_headers), 200)
    assertions.assert_unchanged(expired, after_replay)

    answered = validate_success(
        api.submit_investigation_evidence(
            investigation["id"], "EVID-DETAINED-1", "DIST-DETAINED-1",
            headers=enforcement_analyst_headers),
        200,
    )
    assert answered["status"] == constants.INVESTIGATION_STATUS_EVIDENCE_SUBMITTED, (
        f"Expected EVIDENCE_SUBMITTED, got {answered['status']}")
    assert answered["evidence_ref"] == "EVID-DETAINED-1", (
        f"Expected evidence_ref EVID-DETAINED-1, got {answered['evidence_ref']}")
    assert answered["suspected_distributor_ref"] == "DIST-DETAINED-1", (
        f"Expected suspected_distributor_ref DIST-DETAINED-1, got "
        f"{answered['suspected_distributor_ref']}")
    assertions.assert_common_fields(answered, expected_version=2)


def test_diversion_confirmed_cannot_skip_evidence_submitted_while_release_can(
    api, customs_coordinator_headers, brand_administrator_headers
):
    """Confirming a diversion demands filed evidence; releasing the detention does not.

    PRD §3.10: "`DIVERSION_CONFIRMED` may be reached only from `EVIDENCE_SUBMITTED`, never directly from `OPEN`; attempting to confirm a diversion on an `OPEN` investigation is `ERR_INVALID_STATE` (HTTP 409)."
    PRD §3.10: "`RELEASED` is reachable from either `EVIDENCE_SUBMITTED` or directly from `OPEN` — a detention may be released without the brand ever having answered it."
    PRD §3.10: "No strike is attributed and no case is created on this branch."
    PRD §3.10: "Both outcomes stamp `concluded_at` from the logical clock, persist `findings_ref` and increment `version` by 1, and both are terminal."
    PRD §3.3: "A new seller row starts with `status` `ACTIVE`, `canonical_seller_id` null, and both `standalone_strike_points` and `cluster_strike_points` at 0.00."
    Design: Corner/state_machines/diversion_confirmed_cannot_skip_evidence_submitted_while_release_can
    """
    conclusion_clock = "2026-08-05T08:00:00Z"
    fixtures.set_clock(api, conclusion_clock)
    brand = fixtures.create_brand(api)
    registration = fixtures.create_registration(api, brand["id"])
    recordation = fixtures.create_recorded_recordation(
        api, brand["id"], registration["id"],
        recordation_number="CBP-2002",
        customs_authority_code=constants.CUSTOMS_AUTHORITY_US_CBP,
    )
    seller = fixtures.create_seller(api)
    investigation = fixtures.create_border_seizure_investigation(
        api, brand["id"], recordation["id"], seller_id=seller["id"], lot_code="LOT-RELEASE-1")
    assert investigation["status"] == constants.INVESTIGATION_STATUS_OPEN, (
        f"Expected OPEN, got {investigation['status']}")

    validate_error(
        api.conclude_investigation(
            investigation["id"],
            constants.INVESTIGATION_STATUS_DIVERSION_CONFIRMED,
            "FND-TOO-EARLY",
            headers=customs_coordinator_headers,
        ),
        ApiErrorId.INVALID_STATE,
    )
    still_open = validate_success(
        api.get_investigation(investigation["id"], headers=customs_coordinator_headers), 200)
    assertions.assert_unchanged(investigation, still_open)
    assert still_open["status"] == constants.INVESTIGATION_STATUS_OPEN, (
        f"Expected the investigation to stay OPEN, got {still_open['status']}")
    assert still_open["concluded_at"] is None, (
        f"Expected concluded_at null, got {still_open['concluded_at']!r}")
    assert still_open["findings_ref"] is None, (
        f"Expected findings_ref null, got {still_open['findings_ref']!r}")
    assertions.assert_seller_strikes(
        fixtures.read_seller(api, seller["id"]), 0.00, 0.00, constants.SELLER_STATUS_ACTIVE)

    released = validate_success(
        api.conclude_investigation(
            investigation["id"],
            constants.INVESTIGATION_STATUS_RELEASED,
            "FND-RELEASED-1",
            headers=customs_coordinator_headers,
        ),
        200,
    )
    assert released["status"] == constants.INVESTIGATION_STATUS_RELEASED, (
        f"Expected RELEASED straight from OPEN, got {released['status']}")
    assert_instant_equals(released["concluded_at"], conclusion_clock, "concluded_at")
    assert released["findings_ref"] == "FND-RELEASED-1", (
        f"Expected findings_ref FND-RELEASED-1, got {released['findings_ref']}")
    assertions.assert_common_fields(released, expected_version=2)

    assertions.assert_seller_strikes(
        fixtures.read_seller(api, seller["id"]), 0.00, 0.00, constants.SELLER_STATUS_ACTIVE)
    _rows, meta = validate_paginated(
        api.list_cases(headers=brand_administrator_headers, brand_id=brand["id"]))
    assert meta["total_count"] == 0, (
        f"Expected no case on the release branch, got {meta['total_count']}")

    validate_error(
        api.conclude_investigation(
            investigation["id"],
            constants.INVESTIGATION_STATUS_RELEASED,
            "FND-RELEASED-2",
            headers=customs_coordinator_headers,
        ),
        ApiErrorId.INVALID_STATE,
    )
    after = validate_success(
        api.get_investigation(investigation["id"], headers=customs_coordinator_headers), 200)
    assertions.assert_unchanged(released, after)
    assert after["findings_ref"] == "FND-RELEASED-1", (
        f"Expected findings_ref to stay FND-RELEASED-1, got {after['findings_ref']}")


def test_case_closed_no_action_is_locked_against_a_second_closure(api, legal_counsel_headers):
    """A no-action closure is terminal, and the litigation track is never engaged by it.

    PRD §3.9: "`LegalCounsel` opens a case manually by supplying `brand_id` and the `seller_id` of the cluster-root seller being pursued; the row starts with `correspondence_status` `NONE`, `litigation_status` `NONE`, `case_status` `OPEN`, `originating_takedown_id` null, and `cease_desist_sent_by_rep_id`, `litigation_authorized_by_rep_id`, `letter_ref`, `cd_sent_at`, `cd_response_due_at`, `response_kind`, `docket_ref` and `closure_outcome` all null."
    PRD §3.9: "`NO_ACTION` is available only while `case_status` is `OPEN` and `litigation_status` is still `NONE`; a case whose litigation track has been engaged can only be closed through `SETTLED` or `DISMISSED`, and attempting a no-action closure on it is `ERR_INVALID_STATE` (HTTP 409)."
    PRD §3.9: "On the `NO_ACTION` path `litigation_status` remains `NONE`."
    PRD §3.9: "On every outcome, `closure_outcome` is persisted, the roll-up sets `case_status` to `CLOSED`, and `version` is incremented by 1."
    PRD §3.11: "`open_case_count` counts enforcement cases of this brand whose `case_status` is `OPEN` or `IN_LITIGATION`; `CLOSED` cases are excluded."
    Design: Corner/state_machines/case_closed_no_action_is_locked_against_a_second_closure
    """
    fixtures.set_clock(api, PINNED_CLOCK)
    brand = fixtures.create_brand(api)
    seller = fixtures.create_seller(api)
    case = fixtures.create_case(api, brand["id"], seller["id"])
    assert case["case_status"] == constants.CASE_STATUS_OPEN, (
        f"Expected case_status OPEN, got {case['case_status']}")
    assert case["correspondence_status"] == constants.CORRESPONDENCE_NONE, (
        f"Expected correspondence_status NONE, got {case['correspondence_status']}")
    assert case["litigation_status"] == constants.LITIGATION_NONE, (
        f"Expected litigation_status NONE, got {case['litigation_status']}")
    assert case["closure_outcome"] is None, (
        f"Expected closure_outcome null on a fresh case, got {case['closure_outcome']!r}")
    assertions.assert_common_fields(case, expected_version=1)

    closed = validate_success(
        api.close_case(case["id"], constants.CLOSURE_NO_ACTION, headers=legal_counsel_headers), 200)
    assert closed["closure_outcome"] == constants.CLOSURE_NO_ACTION, (
        f"Expected closure_outcome NO_ACTION, got {closed['closure_outcome']}")
    assert closed["case_status"] == constants.CASE_STATUS_CLOSED, (
        f"Expected case_status CLOSED, got {closed['case_status']}")
    assert closed["litigation_status"] == constants.LITIGATION_NONE, (
        f"Expected litigation_status to stay NONE, got {closed['litigation_status']}")
    assert closed["correspondence_status"] == constants.CORRESPONDENCE_NONE, (
        f"Expected correspondence_status to stay NONE, got {closed['correspondence_status']}")
    assertions.assert_common_fields(closed, expected_version=2)

    metrics = fixtures.read_metrics(api, brand["id"])
    assertions.assert_metrics(metrics, open_case_count=0)

    validate_error(
        api.close_case(case["id"], constants.CLOSURE_NO_ACTION, headers=legal_counsel_headers),
        ApiErrorId.INVALID_STATE,
    )
    after = fixtures.read_case(api, case["id"])
    assertions.assert_unchanged(closed, after)
    assert after["case_status"] == constants.CASE_STATUS_CLOSED, (
        f"Expected the case to stay CLOSED, got {after['case_status']}")
    assert after["closure_outcome"] == constants.CLOSURE_NO_ACTION, (
        f"Expected closure_outcome to stay NO_ACTION, got {after['closure_outcome']}")
