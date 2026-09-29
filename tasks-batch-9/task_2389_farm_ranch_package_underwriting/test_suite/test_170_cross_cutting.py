"""Layers that cut across the whole contract: the version guards on the two
guarded parents, the compliance cascade run backwards, a stored election flipped
in place, and one rating that trips a scarcity band and a referral at once."""

from test_helpers import (
    ADMIN,
    ApiErrorId,
    COMPLIANCE,
    UW,
    add_scheduled_item,
    approve_endorsement_ok,
    bootstrap_zone,
    complete_inspection_ok,
    create_endorsement_payload,
    open_policy,
    patch_item_ok,
    rate_policy_ok,
    read_endorsement,
    read_ledger,
    read_policy,
    read_pool,
    read_recommendations,
    register_inspector,
    reinspect,
    request_endorsement_ok,
    reservation_by_peril,
    review_recommendation,
    schedule_inspection_ok,
    setup_draft_policy_with_dwelling,
    setup_rated_dwelling_policy,
    submit_evidence,
    upsert_labor_profile,
    validate_error,
    validate_success,
)

COMBINE = {
    "item_class": "EQUIPMENT",
    "description": "Combine",
    "valuation_basis": "ACV",
    "stated_value_cents": 30_001_000,
    "age_years": 12,
    "condition_grade": "B",
}


def test_the_pre_rating_version_is_stale_for_all_four_guarded_policy_writes(api):
    """"If it does not equal the policy's current `version`, the request is
    rejected with `ERR_STALE_POLICY_VERSION` (HTTP 412)." "The same non-optional
    `expected_policy_version` field, checked the same way against the same error,
    guards rating, binding and cancellation." Version 1 spends the quote on the
    rating and is then replayed three times, refused every time; version 2 requests
    an endorsement without moving, which is why the bind that follows accepts the
    very same number. "Every endorsement of the policy in `APPROVED` or `SUSPENDED`
    is moved to `RESCINDED` with `premium_cents` set to 0, and every inspection
    still `SCHEDULED` is moved to `CANCELLED`" — so the still-`REQUESTED` row is
    left exactly where it was.

    Design: Corner/cross_cutting_complexity_layers/corner_stale_policy_version_on_every_occ_guarded_policy_write
    """
    scenario = setup_draft_policy_with_dwelling()
    upsert_labor_profile(scenario.agent_headers, scenario.policy_id)
    assert read_policy(scenario.policy_id)["version"] == 1

    rated = validate_success(
        api.rate_farm_policy(scenario.policy_id, {"expected_policy_version": 1}, UW)
    )
    assert rated["uw_status"] == "RATED"
    assert rated["version"] == 2
    assert rated["total_premium_cents"] == 269_200

    stale_endorsement = api.create_endorsement(
        scenario.policy_id,
        create_endorsement_payload(
            1,
            form_code="AGRITOURISM_LIABILITY",
            sublimit_cents=10_000_000,
            requested_effective_date="2026-09-01",
        ),
        scenario.agent_headers,
    )
    validate_error(stale_endorsement, ApiErrorId.ERR_STALE_POLICY_VERSION.value, 412)
    assert read_policy(scenario.policy_id)["version"] == 2

    endorsement = validate_success(
        api.create_endorsement(
            scenario.policy_id,
            create_endorsement_payload(
                2,
                form_code="AGRITOURISM_LIABILITY",
                sublimit_cents=10_000_000,
                requested_effective_date="2026-09-01",
            ),
            scenario.agent_headers,
        ),
        201,
    )
    assert endorsement["status"] == "REQUESTED"
    assert read_policy(scenario.policy_id)["version"] == 2

    stale_bind = api.bind_farm_policy(scenario.policy_id, {"expected_policy_version": 1}, UW)
    validate_error(stale_bind, ApiErrorId.ERR_STALE_POLICY_VERSION.value, 412)
    held = read_policy(scenario.policy_id)
    assert held["uw_status"] == "RATED"
    assert held["version"] == 2
    assert held["total_premium_cents"] == 269_200

    bound = validate_success(
        api.bind_farm_policy(scenario.policy_id, {"expected_policy_version": 2}, UW)
    )
    assert bound["uw_status"] == "BOUND"
    assert bound["version"] == 3

    stale_cancel = api.cancel_farm_policy(
        scenario.policy_id,
        {"expected_policy_version": 1, "closure_reason": "insured withdrew"},
        UW,
    )
    validate_error(stale_cancel, ApiErrorId.ERR_STALE_POLICY_VERSION.value, 412)
    assert read_policy(scenario.policy_id)["uw_status"] == "BOUND"

    cancelled = validate_success(
        api.cancel_farm_policy(
            scenario.policy_id,
            {"expected_policy_version": 3, "closure_reason": "insured withdrew"},
            UW,
        )
    )

    assert cancelled["uw_status"] == "CANCELLED"
    assert cancelled["closure_reason"] == "insured withdrew"
    for field in (
        "property_premium_cents",
        "base_premium_cents",
        "cat_load_cents",
        "total_premium_cents",
    ):
        assert cancelled[field] == 0
    assert {row["status"] for row in reservation_by_peril(scenario.policy_id).values()} == {
        "RELEASED"
    }
    entries = read_ledger(scenario.policy_id)
    assert sum(row["amount_cents"] for row in entries) == 0
    assert [row["amount_cents"] for row in entries] == [144_000, 125_200, -144_000, -125_200]
    assert read_endorsement(endorsement["id"])["status"] == "REQUESTED"
    assert read_endorsement(endorsement["id"])["premium_cents"] == 0


def test_the_rating_moves_the_pool_version_under_the_administrator(api):
    """"It, too, is not optional, and a mismatch against the pool's current
    `version` is rejected with `ERR_STALE_POOL_VERSION` (HTTP 412)." The
    administrator read the pool at version 1 before the quote existed, and
    "repeated capacity adjustments are perfectly legitimate, so the pool's state
    forbids nothing; the rejection exists because the adjustment was computed
    against a utilization picture that reservations have since moved." The rating
    moved it: "all three start at zero on a new pool — so `available_cents` starts
    equal to `total_capacity_cents` — and all three are recomputed, with the pool's
    `version` incremented by 1, every single time a reservation on that pool changes
    status." Each of the three pools counts only its own bumps.

    Design: Corner/cross_cutting_complexity_layers/corner_stale_pool_version_on_capacity_pool_patch
    """
    scenario = setup_draft_policy_with_dwelling()
    hail_id = scenario.hail_pool["id"]
    assert read_pool(hail_id)["version"] == 1

    rate_policy_ok(scenario.policy_id)
    assert read_pool(hail_id)["version"] == 2

    stale = api.update_cat_capacity_pool(
        hail_id, {"expected_pool_version": 1, "total_capacity_cents": 300_000_000}, ADMIN
    )

    validate_error(stale, ApiErrorId.ERR_STALE_POOL_VERSION.value, 412)
    unchanged = read_pool(hail_id)
    assert unchanged["total_capacity_cents"] == 200_000_000
    assert unchanged["version"] == 2

    resized = validate_success(
        api.update_cat_capacity_pool(
            hail_id, {"expected_pool_version": 2, "total_capacity_cents": 300_000_000}, ADMIN
        )
    )

    assert resized["total_capacity_cents"] == 300_000_000
    assert resized["reserved_cents"] == 20_000_000
    assert resized["available_cents"] == 280_000_000
    assert resized["version"] == 3
    assert read_pool(scenario.wind_pool["id"])["version"] == 2
    assert read_pool(scenario.wildfire_pool["id"])["version"] == 2


def test_accepted_evidence_walks_the_suspended_buyback_back_onto_the_policy(api):
    """"A `POLLUTION_BUYBACK` is `sublimit_cents` multiplied by 0.0150 and rounded
    half up, then raised to a minimum of 75000 cents if the product falls below it."
    A minor finding on the follow-up visit suspends it — "when a policy's
    `compliance_status` enters `RECS_OPEN`, `RECS_OVERDUE` or `SUSPENDED`, every
    endorsement of that policy with `requires_inspection` true and `status`
    `APPROVED` is moved `APPROVED → SUSPENDED`, its `premium_cents` retained on the
    row for later reinstatement, its `version` up by 1" — and the accepted evidence
    brings it back: "whenever an `ACCEPT` or a `WAIVE` leaves no recommendation of
    the policy in `OPEN`, `OVERDUE` or `SUBMITTED`, the policy's compliance axis
    advances to `COMPLIANT` — a move available from `RECS_OPEN`, `RECS_OVERDUE` or
    `SUSPENDED` — every `SUSPENDED` endorsement returns to `APPROVED`, one
    `ENDORSEMENT_ADD` entry with `reason_code` `COMPLIANCE_REINSTATEMENT` is
    appended per reinstated endorsement in `created_at` ascending order, the three
    endorsement-driven premium figures rise accordingly, and the policy's `version`
    climbs by 1."

    Design: Corner/cross_cutting_complexity_layers/corner_compliance_reinstatement_restores_the_suspended_endorsement
    """
    scenario = setup_rated_dwelling_policy()
    inspector = register_inspector()
    visit = schedule_inspection_ok(scenario.policy_id, inspector["id"])
    clean = complete_inspection_ok(
        visit["id"], inspector["id"], findings_summary="clean survey", findings=[]
    )
    assert clean["hazard_score"] == 10
    assert read_policy(scenario.policy_id)["compliance_status"] == "COMPLIANT"

    endorsement = request_endorsement_ok(
        scenario.agent_headers,
        scenario.policy_id,
        form_code="POLLUTION_BUYBACK",
        sublimit_cents=10_000_000,
        requested_effective_date="2026-09-01",
    )
    assert endorsement["requires_inspection"] is True
    approved = approve_endorsement_ok(
        endorsement["id"], "clean inspection, pollution buy-back granted"
    )
    assert approved["premium_cents"] == 150_000
    assert read_policy(scenario.policy_id)["total_premium_cents"] == 419_200

    sent_back = validate_success(
        reinspect(visit["id"], scheduled_for="2026-08-17T09:00:00Z", duration_minutes=60,
                  headers=COMPLIANCE)
    )
    assert sent_back["status"] == "SCHEDULED"
    assert sent_back["inspection_type"] == "RE_INSPECTION"
    followed_up = complete_inspection_ok(
        visit["id"],
        inspector["id"],
        findings_summary="chemical shed housekeeping",
        findings=[
            {
                "severity": "MINOR",
                "description": "Bund the chemical shed floor",
                "due_date": "2026-09-30",
            }
        ],
    )
    assert followed_up["hazard_score"] == 9
    suspended_policy = read_policy(scenario.policy_id)
    assert suspended_policy["compliance_status"] == "RECS_OPEN"
    assert suspended_policy["total_premium_cents"] == 269_200
    assert read_endorsement(endorsement["id"])["status"] == "SUSPENDED"
    assert read_endorsement(endorsement["id"])["premium_cents"] == 150_000

    recommendation = read_recommendations(visit["id"])[0]
    submitted = validate_success(
        submit_evidence(
            scenario.agent_headers,
            recommendation["id"],
            evidence_note="floor bunded, photos attached",
            completed_date="2026-08-20",
        )
    )
    assert submitted["status"] == "SUBMITTED"
    assert read_policy(scenario.policy_id)["total_premium_cents"] == 269_200

    verified = validate_success(
        review_recommendation(recommendation["id"], "ACCEPT", "bunding verified")
    )

    assert verified["status"] == "VERIFIED"
    restored_policy = read_policy(scenario.policy_id)
    assert restored_policy["compliance_status"] == "COMPLIANT"
    assert restored_policy["endorsement_premium_cents"] == 150_000
    assert restored_policy["total_premium_cents"] == 419_200
    restored_endorsement = read_endorsement(endorsement["id"])
    assert restored_endorsement["status"] == "APPROVED"
    assert restored_endorsement["premium_cents"] == 150_000

    entries = read_ledger(scenario.policy_id)
    assert [row["amount_cents"] for row in entries] == [
        144_000,
        125_200,
        150_000,
        -150_000,
        150_000,
    ]
    assert sum(row["amount_cents"] for row in entries) == 419_200
    assert entries[3]["reason_code"] == "COMPLIANCE_SUSPENSION"
    assert entries[4]["reason_code"] == "COMPLIANCE_REINSTATEMENT"
    assert entries[4]["txn_type"] == "ENDORSEMENT_ADD"


def test_flipping_one_row_to_replacement_cost_repriced_the_whole_quote(api):
    """"On the `ACV` branch, three quantities are formed from the effective value."
    "The insured value is then the larger of the depreciated value and the salvage
    floor, capped at the class cap, rounded half up." That election stored 11040368
    for the combine. Flipping it — "on the `RC` branch, the insured value is the
    smaller of the effective value and the class cap, rounded half up; `age_years`
    and `condition_grade` are read on this branch but contribute nothing at all" —
    restates the same row at 30001000, and "because a schedule change invalidates
    any price already struck, adding or amending a scheduled item on a policy whose
    `uw_status` is `RATED` drives that policy back through `RATED → DRAFT` with the
    full unwind described in §3.7." The re-rating carries the whole delta, since
    "each `ACTIVE` item then contributes one line: its `insured_value_cents`
    multiplied by the property rate for its `item_class`, multiplied by the credit,
    rounded half up to a whole cent on that line."

    Design: Corner/cross_cutting_complexity_layers/corner_valuation_basis_switch_reprices_the_same_row
    """
    scenario = bootstrap_zone()
    combine = validate_success(
        api.create_scheduled_item(scenario.policy_id, dict(COMBINE), scenario.agent_headers), 201
    )
    assert combine["insured_value_cents"] == 11_040_368

    first = rate_policy_ok(scenario.policy_id)
    assert first["property_premium_cents"] == 89_427
    assert first["exposed_tiv_cents"] == 11_040_368
    assert reservation_by_peril(scenario.policy_id)["HAIL"]["amount_cents"] == 5_520_184

    flipped = patch_item_ok(combine["id"], scenario.agent_headers, valuation_basis="RC")

    assert flipped["valuation_basis"] == "RC"
    assert flipped["insured_value_cents"] == 30_001_000
    reverted = read_policy(scenario.policy_id)
    assert reverted["uw_status"] == "DRAFT"
    assert reverted["property_premium_cents"] == 0
    assert reverted["exposed_tiv_cents"] == 0
    assert reverted["quote_expires_at"] is None
    assert {row["status"] for row in reservation_by_peril(scenario.policy_id).values()} == {
        "RELEASED"
    }

    second = rate_policy_ok(scenario.policy_id)

    assert second["uw_status"] == "RATED"
    assert second["property_premium_cents"] == 243_008
    assert second["exposed_tiv_cents"] == 30_001_000
    reservations = reservation_by_peril(scenario.policy_id)
    assert reservations["HAIL"]["amount_cents"] == 15_000_500
    assert reservations["HAIL"]["status"] == "RESERVED"


def test_one_rating_takes_the_top_scarcity_band_and_the_utilization_referral(api):
    """"`scarcity_factor` is selected from that ratio in four bands: at most 0.50
    gives 1.00, above 0.50 and at most 0.75 gives 1.15, above 0.75 and at most 0.90
    gives 1.35, above 0.90 and at most 1.00 gives 1.60; a ratio strictly greater
    than 1.00 aborts the entire rating call with `ERR_CAT_CAPACITY_EXCEEDED` and
    leaves no reservation behind for any peril." The same 0.952381 that buys the
    1.60 band also refers the quote: "any peril's prospective utilization — the
    unrounded ratio, not the six-decimal stored figure — strictly greater than 0.90
    yields `CAT_UTILIZATION_HIGH`." And a referral holds its capacity: "if at least
    one trigger matches, the policy advances `DRAFT → REFERRED` instead, and every
    premium, reservation, pool and ledger effect above fires identically — the
    divergence is narrow and precise: on the `REFERRED` branch `quote_expires_at`
    stays null, while `referred_at` takes the current clock instant,
    `referred_by_user_id` takes the rating actor's `X-User-ID` and
    `referral_reason_code` takes the first matching trigger."

    Design: Corner/cross_cutting_complexity_layers/corner_top_scarcity_tier_and_referral_trigger_in_one_rating
    """
    scenario = bootstrap_zone(
        zone_code="ZN-3",
        hail_capacity_cents=21_000_000,
        with_policy=False,
        account_overrides={"legal_name": "Hailstreak Ranch", "county_name": "Stafford"},
    )
    policy = open_policy(scenario.agent_headers, scenario.account["id"])
    add_scheduled_item(scenario.agent_headers, policy["id"])

    referred = rate_policy_ok(policy["id"])

    hail = reservation_by_peril(policy["id"])["HAIL"]
    assert hail["amount_cents"] == 20_000_000
    assert float(hail["utilization_at_rating"]) == 0.952381
    assert float(hail["scarcity_factor"]) == 1.60
    assert hail["load_cents"] == 102_400

    assert referred["cat_load_cents"] == 163_600
    assert referred["property_premium_cents"] == 144_000
    assert referred["total_premium_cents"] == 307_600
    assert referred["uw_status"] == "REFERRED"
    assert referred["referral_reason_code"] == "CAT_UTILIZATION_HIGH"
    assert referred["quote_expires_at"] is None
    assert referred["referred_at"].startswith("2026-08-15T00:00:00")

    reservations = reservation_by_peril(policy["id"])
    assert set(reservations) == {"HAIL", "WIND", "WILDFIRE"}
    assert {row["status"] for row in reservations.values()} == {"RESERVED"}
