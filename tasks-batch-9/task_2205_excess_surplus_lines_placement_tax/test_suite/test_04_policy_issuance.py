"""Issuing a policy: the densest gate in the system, its ladder order, its
pinning and the half-open term-overlap rule.
"""

from test_helpers import (
    ERR_CARRIER_NOT_FOUND,
    ERR_CARRIER_NOT_SECURITY_APPROVED,
    ERR_CARRIER_NOT_WHITE_LISTED,
    ERR_PLACEMENT_NOT_BINDABLE,
    ERR_PLACEMENT_NOT_FOUND,
    ERR_POLICY_TERM_OVERLAP,
    ERR_STALE_PLACEMENT_VERSION,
    NON_EXISTENT_UUID,
    OMIT,
    PLATFORM_ADMIN,
    STATE_REGULATOR_TX,
    assert_policy_dimensions,
    carrier_eligibility_payload,
    policy_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_policy_create_omitting_the_fee_fields_defaults_them_to_zero(searched_world):
    """The optional money fields default rather than being required.

    PRD 3.5: "Three optional money fields round out the payload:
    `policy_fee_cents`, the carrier's policy fee, defaulting to 0 and
    non-negative; `broker_fee_cents`, the surplus lines broker's own fee,
    defaulting to 0 and non-negative; and `min_earned_premium_pct`, defaulting
    to 0, the fraction of taxable premium the carrier retains as minimum earned
    premium if the policy is later cancelled."

    Design: Corner/entities/policy_create_omitting_the_fee_fields_defaults_them_to_zero
    """
    world = searched_world
    policy = world.issue_policy(
        policy_number="SL-2026-0200",
        policy_fee_cents=OMIT,
        broker_fee_cents=OMIT,
        min_earned_premium_pct=OMIT,
    )
    assert policy["policy_fee_cents"] == 0
    assert policy["broker_fee_cents"] == 0
    assert policy["min_earned_premium_pct"] == 0
    assert policy["gross_premium_cents"] == 1_000_000
    assert policy["taxable_premium_cents"] == 0

    calculated = world.calculate_tax()
    # Taxable premium is the gross premium alone, with no fee added.
    assert calculated["taxable_premium_cents"] == 1_000_000


def test_policy_create_body_foreign_keys_are_checked_in_declared_input_order(
    searched_world,
):
    """The placement is resolved before the carrier, whatever else is wrong.

    PRD 2.9: "Policy issuance declares `placement_id` before `carrier_id`, so a
    request naming both an unknown placement and an unknown carrier reports
    `ERR_PLACEMENT_NOT_FOUND`."

    Design: Corner/entities/policy_create_body_foreign_keys_are_checked_in_declared_input_order
    """
    world = searched_world
    placement = world.get_placement()

    validate_error(
        world.api.create_policy(
            policy_payload(
                NON_EXISTENT_UUID,
                NON_EXISTENT_UUID,
                placement["version"],
                policy_number="SL-2026-0300",
            ),
            world.broker_headers,
        ),
        ERR_PLACEMENT_NOT_FOUND,
        404,
    )

    validate_error(
        world.api.create_policy(
            policy_payload(
                placement["id"],
                NON_EXISTENT_UUID,
                placement["version"],
                policy_number="SL-2026-0301",
            ),
            world.broker_headers,
        ),
        ERR_CARRIER_NOT_FOUND,
        404,
    )


def test_binding_a_placement_whose_search_is_not_complete_is_refused(placement_world):
    """A draft placement is not bindable however clean the carrier is.

    PRD 3.5: "The placement must be `SEARCH_COMPLETE` or already `BOUND`, else
    `ERR_PLACEMENT_NOT_BINDABLE`."

    Design: Corner/errors/binding_a_placement_whose_search_is_not_complete_is_refused
    """
    world = placement_world
    placement = world.placement
    assert placement["status"] == "DRAFT"

    validate_error(
        world.api.create_policy(
            policy_payload(
                placement["id"],
                world.carrier["id"],
                placement["version"],
                policy_number="SL-2026-0400",
            ),
            world.broker_headers,
        ),
        ERR_PLACEMENT_NOT_BINDABLE,
        409,
    )

    rows, meta = validate_paginated(world.api.list_policies(PLATFORM_ADMIN))
    assert meta["total_count"] == 0
    assert rows == []


def test_an_approved_carrier_that_is_not_white_listed_in_the_home_state_is_refused(
    approved_carrier_world,
):
    """Security clearance is not the same thing as state eligibility.

    PRD 2.11: "**Carrier white-listing.** A white-list entry exists for the
    carrier and the home state's program, whose `listing_status` is
    `WHITE_LISTED` and whose listing window contains the policy's
    `effective_date`. Applies to policy issuance. Violation:
    `ERR_CARRIER_NOT_WHITE_LISTED` (409)."

    Design: Corner/errors/an_approved_carrier_that_is_not_white_listed_in_the_home_state_is_refused
    """
    world = approved_carrier_world
    assert world.carrier["security_status"] == "APPROVED"
    placement = world.searched_placement()

    validate_error(
        world.api.create_policy(
            policy_payload(
                placement["id"],
                world.carrier["id"],
                placement["version"],
                policy_number="SL-2026-0500",
            ),
            world.broker_headers,
        ),
        ERR_CARRIER_NOT_WHITE_LISTED,
        409,
    )

    world.white_list("TX")
    policy = validate_success(
        world.api.create_policy(
            policy_payload(
                placement["id"],
                world.carrier["id"],
                placement["version"],
                policy_number="SL-2026-0500",
            ),
            world.broker_headers,
        ),
        201,
    )
    assert policy["home_state"] == "TX"
    assert_policy_dimensions(policy, status="ISSUED")


def test_the_placement_state_check_pre_empts_the_carrier_security_check(
    configured_world,
):
    """Two rules are broken at once and the lower rung reports.

    PRD 3.5: "The gates run in the order fixed by §2.11: ownership of the
    placement, then the stale-placement-version check, then the placement's own
    state, then the brokerage's surplus lines licensing in the home state, then
    the carrier's security standing, then the carrier's white-listing, and
    finally term overlap."

    Design: Difficulty/priority_pair_validation_conflict/policy_issue_state_check_pre_empts_carrier_referential_checks
    """
    world = configured_world
    carrier = world.create_carrier(naic_number="12345")
    assert carrier["security_status"] == "UNREVIEWED"
    placement = world.create_placement()
    assert placement["status"] == "DRAFT"

    # The placement is not bindable *and* the carrier is neither cleared nor
    # listed; the state rung is the lower of the three.
    validate_error(
        world.api.create_policy(
            policy_payload(
                placement["id"],
                carrier["id"],
                placement["version"],
                policy_number="SL-2026-0600",
            ),
            world.broker_headers,
        ),
        ERR_PLACEMENT_NOT_BINDABLE,
        409,
    )

    rows, meta = validate_paginated(world.api.list_policies(PLATFORM_ADMIN))
    assert meta["total_count"] == 0
    after = world.get_placement(placement["id"])
    assert after["status"] == "DRAFT"
    assert after["version"] == placement["version"]


def test_with_the_placement_bindable_the_carrier_security_rung_is_reached(
    configured_world,
):
    """Fixing the state error exposes the next rung down, not the listing one.

    PRD 2.11: "**Carrier security standing.** The carrier's `security_status` is
    `APPROVED` or `CONDITIONAL`. Applies to policy issuance. Violation:
    `ERR_CARRIER_NOT_SECURITY_APPROVED` (409). This rung precedes the white-list
    rung, so an `UNREVIEWED` carrier reports its security standing rather than
    its listing."

    Design: Difficulty/priority_pair_validation_conflict/policy_issue_state_check_pre_empts_carrier_referential_checks
    """
    world = configured_world
    carrier = world.create_carrier(naic_number="12345")
    placement = world.searched_placement()
    assert placement["status"] == "SEARCH_COMPLETE"

    validate_error(
        world.api.create_policy(
            policy_payload(
                placement["id"],
                carrier["id"],
                placement["version"],
                policy_number="SL-2026-0601",
            ),
            world.broker_headers,
        ),
        ERR_CARRIER_NOT_SECURITY_APPROVED,
        409,
    )

    rows, meta = validate_paginated(world.api.list_policies(PLATFORM_ADMIN))
    assert meta["total_count"] == 0


def test_a_stale_placement_version_pre_empts_the_placement_state_check(
    white_listed_world,
):
    """A client whose view predates the search opening is told to refresh.

    PRD 2.11: "**Stale parent version.** Where the endpoint declares a version
    field, it matches the parent's current `version`. Applies to policy issuance,
    endorsement creation and review decision. Violation: the relevant 412 error
    from §2.10. Stale-version rejection precedes every state and business check,
    so a client holding an outdated view is told to refresh rather than told its
    business intent is invalid."

    Design: Difficulty/priority_pair_validation_conflict/policy_issue_stale_version_pre_empts_state_check
    """
    world = white_listed_world
    placement = world.create_placement()
    stale_version = placement["version"]
    world.begin_search(placement)

    validate_error(
        world.api.create_policy(
            policy_payload(
                placement["id"],
                world.carrier["id"],
                stale_version,
                policy_number="SL-2026-0700",
            ),
            world.broker_headers,
        ),
        ERR_STALE_PLACEMENT_VERSION,
        412,
    )

    rows, meta = validate_paginated(world.api.list_policies(PLATFORM_ADMIN))
    assert meta["total_count"] == 0
    assert rows == []
    assert world.get_placement(placement["id"])["status"] == "SEARCH_IN_PROGRESS"


def test_a_fresh_placement_version_reveals_the_state_error_underneath(
    white_listed_world,
):
    """With the version correct the same request reports its real problem.

    PRD 2.10: "Issuing a policy requires `expected_placement_version`, matching
    the target placement's current `version`. A mismatch is rejected with
    `ERR_STALE_PLACEMENT_VERSION` (HTTP 412)."

    Design: Difficulty/priority_pair_validation_conflict/policy_issue_stale_version_pre_empts_state_check
    """
    world = white_listed_world
    placement = world.create_placement()
    in_progress = world.begin_search(placement)

    validate_error(
        world.api.create_policy(
            policy_payload(
                placement["id"],
                world.carrier["id"],
                in_progress["version"],
                policy_number="SL-2026-0701",
            ),
            world.broker_headers,
        ),
        ERR_PLACEMENT_NOT_BINDABLE,
        409,
    )


def test_a_declined_carrier_cannot_take_the_placement(configured_world):
    """The carrier's own state dimension gates a write on the policy collection.

    PRD 2.11: "**Carrier security standing.** The carrier's `security_status` is
    `APPROVED` or `CONDITIONAL`. Applies to policy issuance. Violation:
    `ERR_CARRIER_NOT_SECURITY_APPROVED` (409). This rung precedes the white-list
    rung, so an `UNREVIEWED` carrier reports its security standing rather than
    its listing."

    Design: Difficulty/cross_entity_state_dependency/policy_issuance_depends_on_the_carriers_security_status
    """
    world = configured_world
    meridian = world.create_carrier(
        naic_number="22222",
        legal_name="Meridian Indemnity Company",
        capital_surplus_cents=1_600_000_000,
        am_best_rating="NR",
        trust_fund_cents=0,
        naic_quarterly_listing=False,
    )
    validate_success(
        world.api.create_carrier_eligibility(
            carrier_eligibility_payload(meridian["id"], world.program_id("TX")),
            STATE_REGULATOR_TX,
        ),
        201,
    )
    world.review_carrier("DECLINE", carrier=meridian)
    assert world.get_carrier(meridian["id"])["security_status"] == "DECLINED"

    placement = world.searched_placement()
    validate_error(
        world.api.create_policy(
            policy_payload(
                placement["id"],
                meridian["id"],
                placement["version"],
                policy_number="SL-2026-0010",
            ),
            world.broker_headers,
        ),
        ERR_CARRIER_NOT_SECURITY_APPROVED,
        409,
    )

    after = world.get_placement(placement["id"])
    assert after["status"] == "SEARCH_COMPLETE"
    assert after["version"] == placement["version"]


def test_a_conditionally_cleared_carrier_may_take_the_placement(configured_world):
    """`CONDITIONAL` satisfies the security rung just as `APPROVED` does.

    PRD 3.5: "Issuance pins a great deal. The policy's `broker_id` is copied from
    the placement's `broker_id`; its `home_state` is copied from the placement's
    `home_state`; and its `allocation_method_applied` is copied from the home
    state's program `allocation_method`, taking the value `HOME_STATE_SINGLE` or
    `ALLOCATED_MULTI`."

    Design: Difficulty/cross_entity_state_dependency/policy_issuance_depends_on_the_carriers_security_status
    """
    world = configured_world
    trident = world.create_carrier(
        naic_number="33333",
        legal_name="Trident Global Assurance Ltd",
        domicile_type="ALIEN",
        capital_surplus_cents=2_000_000_000,
        am_best_rating="A",
        trust_fund_cents=539_999_999,
        naic_quarterly_listing=True,
    )
    world.review_carrier(
        "CONDITION",
        carrier=trident,
        conditions_note="Bind only with quarterly trust-fund attestation.",
    )
    assert world.get_carrier(trident["id"])["security_status"] == "CONDITIONAL"
    world.white_list("TX", carrier=trident)

    placement = world.searched_placement()
    policy = validate_success(
        world.api.create_policy(
            policy_payload(
                placement["id"],
                trident["id"],
                placement["version"],
                policy_number="SL-2026-0010",
            ),
            world.broker_headers,
        ),
        201,
    )
    assert policy["home_state"] == "TX"
    assert policy["broker_id"] == world.broker["id"]
    assert policy["allocation_method_applied"] == "ALLOCATED_MULTI"
    assert_policy_dimensions(
        policy,
        status="ISSUED",
        compliance_status="PENDING_NOTICES",
        tax_status="UNCALCULATED",
        stamping_status="PENDING",
    )


def test_an_intersecting_policy_term_on_the_same_placement_is_refused(policy_world):
    """A second term that genuinely overlaps the first collides.

    PRD 2.11: "Policy terms on one placement are half-open, running from
    `effective_date` inclusive up to but excluding `expiration_date`, so
    back-to-back terms that merely touch are permitted; an intersection with an
    existing non-`CANCELLED` policy on the same placement is
    `ERR_POLICY_TERM_OVERLAP` (409)."

    Design: Difficulty/resource_temporal_overlap/policy_terms_on_one_placement_are_half_open_so_adjacency_is_legal
    """
    world = policy_world
    placement = world.get_placement()
    assert placement["status"] == "BOUND"

    validate_error(
        world.api.create_policy(
            policy_payload(
                placement["id"],
                world.carrier["id"],
                placement["version"],
                policy_number="SL-2026-0001-OVERLAP",
                effective_date="2027-07-01T00:00:00Z",
                expiration_date="2028-06-30T00:00:00Z",
                original_gross_premium_cents=900_000,
                policy_fee_cents=0,
                broker_fee_cents=0,
            ),
            world.broker_headers,
        ),
        ERR_POLICY_TERM_OVERLAP,
        409,
    )

    rows, meta = validate_paginated(world.api.list_policies(PLATFORM_ADMIN))
    assert meta["total_count"] == 1
    after = world.get_placement()
    assert after["version"] == placement["version"]


def test_a_back_to_back_policy_term_that_merely_touches_is_permitted(policy_world):
    """Adjacency at the exact expiration instant is legal, and the placement
    stays bindable.

    PRD 3.5: "This is deliberate: a risk file legitimately carries successive
    terms and layered policies, so a placement that is already `BOUND` remains
    bindable, further issuances succeed, and the status simply stays at `BOUND` —
    while still incrementing the placement's `version` on *every* issuance,
    including those that leave the status unchanged."

    Design: Difficulty/resource_temporal_overlap/policy_terms_on_one_placement_are_half_open_so_adjacency_is_legal
    """
    world = policy_world
    placement = world.get_placement()
    first_policy = world.policy
    assert first_policy["expiration_date"] == "2027-08-01T00:00:00Z"

    second = validate_success(
        world.api.create_policy(
            policy_payload(
                placement["id"],
                world.carrier["id"],
                placement["version"],
                policy_number="SL-2026-0001-RENEWAL",
                effective_date="2027-08-01T00:00:00Z",
                expiration_date="2028-07-31T00:00:00Z",
                original_gross_premium_cents=900_000,
                policy_fee_cents=0,
                broker_fee_cents=0,
            ),
            world.broker_headers,
        ),
        201,
    )
    assert second["effective_date"] == "2027-08-01T00:00:00Z"

    rows, meta = validate_paginated(
        world.api.list_policies(PLATFORM_ADMIN, {"placement_id": placement["id"]})
    )
    assert meta["total_count"] == 2
    assert len(rows) == 2

    after = world.get_placement()
    assert after["status"] == "BOUND"
    assert after["version"] == placement["version"] + 1
