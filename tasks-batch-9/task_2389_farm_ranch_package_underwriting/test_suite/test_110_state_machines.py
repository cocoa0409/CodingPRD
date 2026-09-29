"""Where each machine starts, which triggers it accepts, which it refuses by
name, and what a refused trigger leaves behind."""

from test_helpers import (
    COMPLIANCE,
    SENIOR,
    SENIOR_ALT,
    UW,
    ApiErrorId,
    assert_policy_money_zeroed,
    bind_policy,
    bind_policy_ok,
    cancel_policy,
    complete_inspection,
    complete_inspection_ok,
    create_labor_profile_payload,
    create_scheduled_item_payload,
    decide_endorsement,
    decide_referral,
    decline_policy,
    decline_policy_ok,
    get_success_data,
    ledger_by_sequence,
    patch_item,
    patch_item_ok,
    rate_policy,
    rate_policy_ok,
    read_endorsement,
    read_inspection,
    read_item,
    read_labor_profile,
    read_ledger,
    read_policy,
    read_pool,
    read_recommendations,
    read_reservations,
    register_inspector,
    reinspect,
    request_endorsement,
    request_endorsement_ok,
    rescind_endorsement,
    reservation_by_peril,
    review_recommendation,
    schedule_inspection,
    schedule_inspection_ok,
    set_clock,
    setup_agritourism_referral_policy,
    setup_draft_policy_with_dwelling,
    setup_policy_with_approved_endorsement,
    setup_rated_dwelling_policy,
    setup_rated_policy_with_inspector,
    submit_evidence,
    upsert_labor_profile,
    validate_error,
    validate_paginated,
    validate_success,
    verify_wc,
)

PTO_FINDING = {
    "severity": "MAJOR",
    "description": "Install PTO shield",
    "due_date": "2026-09-30",
}


def test_every_machine_starts_where_the_contract_says_it_starts(api):
    """Every machine sits on its declared opening state. An endorsement: "The new
    row lands in `status` `REQUESTED` with `premium_cents` 0, `decision_note` and
    `decided_by_user_id` null." An inspection: "A new inspection lands in `status`
    `SCHEDULED` with `hazard_score` 0, `recommendation_count` 0, and `completed_at`
    and `findings_summary` null." A reservation: "Its `status` starts at `RESERVED`
    and moves to `COMMITTED` on binding or to `RELEASED` when the occupation
    ends." And an all-zero crew leaves `coordination_status` at `NOT_REQUIRED`.
    Requesting the endorsement also leaves the policy's own `version` where the
    rating left it.

    Design: Corner/state_machines/corner_initial_states_of_every_machine_on_creation
    """
    scenario = setup_rated_policy_with_inspector(with_inspection=False)
    version_after_rating = read_policy(scenario.policy_id)["version"]

    profile = read_labor_profile(scenario.labor_profile["id"])
    assert float(profile["labor_exposure_units"]) == 0.00
    assert profile["wc_required"] is False
    assert profile["coordination_status"] == "NOT_REQUIRED"

    endorsement = request_endorsement_ok(
        scenario.agent_headers,
        scenario.policy_id,
        form_code="POLLUTION_BUYBACK",
        sublimit_cents=10_000_000,
        requested_effective_date="2026-09-01",
    )
    assert endorsement["status"] == "REQUESTED"
    assert endorsement["premium_cents"] == 0
    assert endorsement["decision_note"] is None
    assert endorsement["decided_by_user_id"] is None
    assert endorsement["requires_inspection"] is True

    inspection = schedule_inspection_ok(scenario.policy_id, scenario.inspector_id)
    assert inspection["status"] == "SCHEDULED"
    assert inspection["hazard_score"] == 0
    assert inspection["recommendation_count"] == 0
    assert inspection["completed_at"] is None
    assert inspection["findings_summary"] is None

    reservations = reservation_by_peril(scenario.policy_id)
    assert {row["status"] for row in reservations.values()} == {"RESERVED"}
    assert read_policy(scenario.policy_id)["version"] == version_after_rating


def test_rating_a_draft_writes_the_quote_the_reservations_and_the_ledger(api):
    """"If no trigger matches, the policy advances `DRAFT → RATED`,
    `quote_expires_at` is set to `rating_valuation_date` plus 30 days as exact
    instant arithmetic, and `referred_at`, `referred_by_user_id` and
    `referral_reason_code` are cleared." One replacement-cost dwelling produces
    property 144000 and a catastrophe load of 125200 spread over the three pools
    in the fixed peril order, and the zero livestock and liability components
    consume no `sequence_no`.

    Design: Corner/state_machines/corner_rate_draft_to_rated_writes_quote_and_reservations
    """
    scenario = setup_draft_policy_with_dwelling()

    rated = rate_policy_ok(scenario.policy_id)

    assert rated["uw_status"] == "RATED"
    assert rated["compliance_status"] == "NOT_INSPECTED"
    assert rated["rating_valuation_date"].startswith("2026-08-15T00:00:00")
    assert rated["quote_expires_at"].startswith("2026-09-14T00:00:00")
    assert rated["referred_at"] is None
    assert rated["referred_by_user_id"] is None
    assert rated["referral_reason_code"] is None
    assert rated["property_premium_cents"] == 144_000
    assert rated["livestock_premium_cents"] == 0
    assert rated["liability_premium_cents"] == 0
    assert rated["endorsement_premium_cents"] == 0
    assert rated["base_premium_cents"] == 144_000
    assert rated["cat_load_cents"] == 125_200
    assert rated["total_premium_cents"] == 269_200
    assert rated["exposed_tiv_cents"] == 40_000_000
    assert rated["version"] == 2

    reservations = read_reservations(scenario.policy_id)
    assert [row["peril"] for row in reservations] == ["HAIL", "WIND", "WILDFIRE"]
    assert [row["status"] for row in reservations] == ["RESERVED"] * 3
    assert [row["amount_cents"] for row in reservations] == [20_000_000, 12_000_000, 8_000_000]
    assert [float(row["utilization_at_rating"]) for row in reservations] == [0.1, 0.06, 0.04]
    assert [float(row["scarcity_factor"]) for row in reservations] == [1.00, 1.00, 1.00]
    assert [row["load_cents"] for row in reservations] == [64_000, 25_200, 36_000]

    for peril, amount in (("HAIL", 20_000_000), ("WIND", 12_000_000), ("WILDFIRE", 8_000_000)):
        pool = read_pool(scenario.pools[peril]["id"])
        assert pool["reserved_cents"] == amount
        assert pool["committed_cents"] == 0
        assert pool["available_cents"] == 200_000_000 - amount
        assert pool["version"] == 2

    entries = read_ledger(scenario.policy_id)
    assert [row["sequence_no"] for row in entries] == [1, 2]
    assert [row["txn_type"] for row in entries] == ["BASE_PROPERTY", "CAT_LOAD"]
    assert [row["amount_cents"] for row in entries] == [144_000, 125_200]
    assert [row["reason_code"] for row in entries] == ["RATING", "RATING"]


def test_amending_an_item_unwinds_the_quote_before_the_re_rating_reserves_again(api):
    """"Any exposure mutation on a `RATED` policy — adding a scheduled item,
    amending one, adding a livestock group, adding a liability exposure — drives
    the policy `RATED → DRAFT` and unwinds the quote completely." The release
    step of the re-rating then finds nothing to release, so the HAIL pool is
    touched exactly three times across the whole episode and never double-counts
    the same package.

    Design: Corner/state_machines/corner_rerating_releases_prior_reservations_before_reserving_again
    """
    scenario = setup_rated_dwelling_policy(with_labor_profile=False)

    patch_item_ok(scenario.item["id"], scenario.agent_headers, stated_value_cents=50_000_000)

    reverted = read_policy(scenario.policy_id)
    assert reverted["uw_status"] == "DRAFT"
    assert_policy_money_zeroed(reverted)
    assert reverted["rating_valuation_date"] is None

    re_rated = rate_policy_ok(scenario.policy_id)
    assert re_rated["property_premium_cents"] == 180_000
    assert re_rated["cat_load_cents"] == 156_500
    assert re_rated["total_premium_cents"] == 336_500
    assert re_rated["exposed_tiv_cents"] == 50_000_000
    assert re_rated["version"] == 4

    reservations = read_reservations(scenario.policy_id)
    assert len(reservations) == 6
    assert [row["status"] for row in reservations[:3]] == ["RELEASED"] * 3
    assert [row["amount_cents"] for row in reservations[:3]] == [20_000_000, 12_000_000, 8_000_000]
    assert [row["status"] for row in reservations[3:]] == ["RESERVED"] * 3
    assert [row["amount_cents"] for row in reservations[3:]] == [25_000_000, 15_000_000, 10_000_000]
    assert [row["load_cents"] for row in reservations[3:]] == [80_000, 31_500, 45_000]

    entries = ledger_by_sequence(read_ledger(scenario.policy_id))
    assert len(entries) == 6
    assert entries[3]["amount_cents"] == -144_000
    assert entries[3]["reverses_sequence_no"] == 1
    assert entries[3]["reason_code"] == "RATING_REVERT"
    assert entries[4]["amount_cents"] == -125_200
    assert entries[4]["reverses_sequence_no"] == 2
    assert entries[5]["txn_type"] == "BASE_PROPERTY"
    assert entries[5]["amount_cents"] == 180_000
    assert entries[6]["txn_type"] == "CAT_LOAD"
    assert entries[6]["amount_cents"] == 156_500
    assert sum(row["amount_cents"] for row in entries.values()) == 336_500

    hail = read_pool(scenario.hail_pool["id"])
    assert hail["reserved_cents"] == 25_000_000
    assert hail["committed_cents"] == 0
    assert hail["available_cents"] == 175_000_000
    assert hail["version"] == 4


def test_rating_a_second_time_is_refused_and_changes_nothing(api):
    """"Only an `Underwriter` or `SeniorUnderwriter` may drive it, the policy must
    be in `DRAFT` (a `REFERRED`, `BOUND` or already-`RATED` policy draws
    `ERR_POLICY_NOT_IN_DRAFT`), and the call carries `expected_policy_version` as
    its sole input." The second call supplies the current version, so it clears
    the concurrency guard and is stopped by the state guard instead — and being
    stopped, it leaves the quote, the three reservations, the two ledger rows and
    all three pool versions exactly as the first rating left them.

    Design: Corner/state_machines/corner_rate_twice_rejected_policy_not_in_draft
    """
    scenario = setup_rated_dwelling_policy(with_labor_profile=False)
    rated = read_policy(scenario.policy_id)

    response = rate_policy(scenario.policy_id)

    validate_error(response, ApiErrorId.ERR_POLICY_NOT_IN_DRAFT.value, 409)

    after = read_policy(scenario.policy_id)
    assert after["version"] == rated["version"]
    assert after["total_premium_cents"] == 269_200
    reservations = read_reservations(scenario.policy_id)
    assert len(reservations) == 3
    assert {row["status"] for row in reservations} == {"RESERVED"}
    assert len(read_ledger(scenario.policy_id)) == 2
    for peril in ("HAIL", "WIND", "WILDFIRE"):
        assert read_pool(scenario.pools[peril]["id"])["version"] == 2


def test_a_draft_package_refuses_every_trigger_that_needs_a_later_state(api):
    """From `DRAFT` each route names the state it needed. Binding: "The policy
    must be `RATED`, or `ERR_POLICY_NOT_RATED`." An endorsement request: "The
    policy's `uw_status` must be `RATED` or `BOUND`, or the request draws
    `ERR_POLICY_NOT_RATED`." Cancelling: "The policy must be `BOUND`, or
    `ERR_POLICY_NOT_BOUND`." A referral decision: "The policy's `uw_status` must be
    `REFERRED` or the call draws `ERR_POLICY_NOT_REFERRED`." Each call carries the
    version the policy actually holds, so none of the four is stopped by the
    concurrency guard ahead of the state guard.

    Design: Corner/state_machines/corner_invalid_triggers_rejected_from_draft_state
    """
    scenario = setup_draft_policy_with_dwelling()
    upsert_labor_profile(scenario.agent_headers, scenario.policy_id)

    validate_error(
        bind_policy(scenario.policy_id), ApiErrorId.ERR_POLICY_NOT_RATED.value, 409
    )
    validate_error(
        cancel_policy(scenario.policy_id, "not wanted"),
        ApiErrorId.ERR_POLICY_NOT_BOUND.value,
        409,
    )
    validate_error(
        decide_referral(scenario.policy_id, "APPROVE"),
        ApiErrorId.ERR_POLICY_NOT_REFERRED.value,
        409,
    )
    validate_error(
        request_endorsement(UW, scenario.policy_id, sublimit_cents=12_000_000),
        ApiErrorId.ERR_POLICY_NOT_RATED.value,
        409,
    )

    still_draft = read_policy(scenario.policy_id)
    assert still_draft["uw_status"] == "DRAFT"
    assert still_draft["version"] == 1
    rows, meta = validate_paginated(api.list_endorsements(scenario.policy_id, UW))
    assert rows == []
    assert meta["total_count"] == 0


def test_a_referral_decision_on_a_plainly_rated_package_is_refused(api):
    """"A referred policy waits for a `SeniorUnderwriter` to supply a `decision`
    of `APPROVE`, `RETURN` or `DECLINE`, optionally with a `decision_note`." The
    role and the body are both right, but the package was never referred, so the
    `RETURN` is refused and the release-and-reverse cascade it would have run does
    not touch the reservations or the ledger.

    Design: Corner/state_machines/corner_referral_decision_on_rated_policy_rejected
    """
    scenario = setup_rated_dwelling_policy(with_labor_profile=False)

    response = decide_referral(scenario.policy_id, "RETURN", "send it back")

    validate_error(response, ApiErrorId.ERR_POLICY_NOT_REFERRED.value, 409)

    after = read_policy(scenario.policy_id)
    assert after["uw_status"] == "RATED"
    assert after["quote_expires_at"].startswith("2026-09-14T00:00:00")
    assert after["version"] == 2
    assert {row["status"] for row in reservation_by_peril(scenario.policy_id).values()} == {
        "RESERVED"
    }
    assert len(read_ledger(scenario.policy_id)) == 2


def test_approving_a_referral_dates_the_quote_from_the_original_valuation(api):
    """"`APPROVE` moves the policy `REFERRED → RATED`. It re-derives
    `quote_expires_at` as 30 days after the original `rating_valuation_date`,
    not 30 days after the decision, and clears `referred_at`,
    `referred_by_user_id` and `referral_reason_code`." Five days pass between the
    rating and the senior underwriter's approval, and the expiry still lands on
    2026-09-14 rather than on 2026-09-19.

    Design: Corner/state_machines/corner_referral_approve_by_second_senior_restores_quote_expiry
    """
    scenario = setup_agritourism_referral_policy()

    referred = rate_policy_ok(scenario.policy_id)
    assert referred["uw_status"] == "REFERRED"
    assert referred["referral_reason_code"] == "AGRITOURISM_VISITORS"
    assert referred["referred_at"].startswith("2026-08-15T00:00:00")
    assert referred["referred_by_user_id"] == UW["X-User-ID"]
    assert referred["quote_expires_at"] is None
    assert referred["property_premium_cents"] == 144_000
    assert referred["liability_premium_cents"] == 316_000
    assert referred["base_premium_cents"] == 460_000
    assert referred["cat_load_cents"] == 125_200
    assert referred["total_premium_cents"] == 585_200
    before = read_ledger(scenario.policy_id)
    assert [row["sequence_no"] for row in before] == [1, 2, 3]
    assert sum(row["amount_cents"] for row in before) == 585_200

    set_clock("2026-08-20T00:00:00Z")
    approved = get_success_data(
        decide_referral(scenario.policy_id, "APPROVE", "acceptable agritourism controls")
    )

    assert approved["uw_status"] == "RATED"
    assert approved["quote_expires_at"].startswith("2026-09-14T00:00:00")
    assert approved["referred_at"] is None
    assert approved["referred_by_user_id"] is None
    assert approved["referral_reason_code"] is None
    assert approved["total_premium_cents"] == 585_200
    assert approved["version"] == 3
    assert {row["status"] for row in reservation_by_peril(scenario.policy_id).values()} == {
        "RESERVED"
    }
    assert read_ledger(scenario.policy_id) == before


def test_returning_a_referral_releases_the_capacity_and_reverses_the_ledger(api):
    """"`RETURN` moves the policy `REFERRED → DRAFT` with exactly the release,
    reversal and zeroing effects of the `RATED → DRAFT` revision cycle in §3.6,
    and likewise clears the three referral fields." The three pools come back to
    their opening capacity, the six ledger rows sum to zero, and the exposures
    that caused the referral survive so the package can be reworked.

    Design: Corner/state_machines/corner_referral_return_reverses_ledger_and_releases_capacity
    """
    scenario = setup_agritourism_referral_policy()
    assert rate_policy_ok(scenario.policy_id)["uw_status"] == "REFERRED"

    returned = get_success_data(
        decide_referral(scenario.policy_id, "RETURN", "reduce the visitor exposure")
    )

    assert returned["uw_status"] == "DRAFT"
    assert_policy_money_zeroed(returned)
    assert returned["rating_valuation_date"] is None
    assert returned["referred_at"] is None
    assert returned["referred_by_user_id"] is None
    assert returned["referral_reason_code"] is None

    reservations = read_reservations(scenario.policy_id)
    assert [row["status"] for row in reservations] == ["RELEASED"] * 3
    assert [row["amount_cents"] for row in reservations] == [20_000_000, 12_000_000, 8_000_000]

    for peril in ("HAIL", "WIND", "WILDFIRE"):
        pool = read_pool(scenario.pools[peril]["id"])
        assert pool["reserved_cents"] == 0
        assert pool["committed_cents"] == 0
        assert pool["available_cents"] == 200_000_000
        assert pool["version"] == 3

    entries = ledger_by_sequence(read_ledger(scenario.policy_id))
    assert len(entries) == 6
    assert [entries[n]["amount_cents"] for n in (4, 5, 6)] == [-144_000, -316_000, -125_200]
    assert [entries[n]["reverses_sequence_no"] for n in (4, 5, 6)] == [1, 2, 3]
    assert sum(row["amount_cents"] for row in entries.values()) == 0
    assert returned["total_premium_cents"] == 0

    assert read_item(scenario.item["id"])["insured_value_cents"] == 40_000_000
    exposures, _ = validate_paginated(api.list_liability_exposures(scenario.policy_id, UW))
    assert [row["exposure_premium_cents"] for row in exposures] == [316_000]


def test_binding_moves_capacity_between_buckets_and_leaves_the_money_alone(api):
    """"On success every `RESERVED` reservation of the policy moves
    `RESERVED → COMMITTED`, and each touched pool re-derives `reserved_cents`,
    `committed_cents` and `available_cents` and lifts its `version` by 1 — the
    amount migrates from reserved to committed and `available_cents` does not
    move." The bind stamps `bound_at` and `bound_by_user_id` from the acting
    underwriter, and "No premium figure changes on bind."

    Design: Corner/state_machines/corner_bind_commits_reserved_capacity_without_moving_premium
    """
    scenario = setup_rated_dwelling_policy()
    reserved = reservation_by_peril(scenario.policy_id)

    bound = bind_policy_ok(scenario.policy_id)

    assert bound["uw_status"] == "BOUND"
    assert bound["bound_at"].startswith("2026-08-15T00:00:00")
    assert bound["bound_by_user_id"] == UW["X-User-ID"]
    assert bound["version"] == 3
    assert bound["compliance_status"] == "NOT_INSPECTED"
    assert bound["total_premium_cents"] == 269_200

    committed = reservation_by_peril(scenario.policy_id)
    for peril, before in reserved.items():
        after = committed[peril]
        assert after["status"] == "COMMITTED"
        assert after["amount_cents"] == before["amount_cents"]
        assert after["utilization_at_rating"] == before["utilization_at_rating"]
        assert after["scarcity_factor"] == before["scarcity_factor"]
        assert after["load_cents"] == before["load_cents"]

    hail = read_pool(scenario.hail_pool["id"])
    assert hail["reserved_cents"] == 0
    assert hail["committed_cents"] == 20_000_000
    assert hail["available_cents"] == 180_000_000
    assert hail["version"] == 3

    entries = read_ledger(scenario.policy_id)
    assert len(entries) == 2
    assert sum(row["amount_cents"] for row in entries) == 269_200


def test_one_error_guards_both_sides_of_the_binding_boundary(api):
    """Cancelling requires a bound package — "The policy must be `BOUND`, or
    `ERR_POLICY_NOT_BOUND`." Declining requires an unbound one: "It is available
    from `DRAFT`, `RATED` or `REFERRED`; attempting it on an already-bound policy
    draws `ERR_POLICY_NOT_BOUND`, and on a closed policy `ERR_POLICY_TERMINAL`."
    The same error therefore fires on either side of the bind, and neither refusal
    stores a `closure_reason`.

    Design: Corner/state_machines/corner_cancel_needs_bound_and_decline_refuses_bound
    """
    scenario = setup_rated_dwelling_policy()
    rated_version = read_policy(scenario.policy_id)["version"]

    validate_error(
        cancel_policy(scenario.policy_id, "too early"),
        ApiErrorId.ERR_POLICY_NOT_BOUND.value,
        409,
    )
    assert read_policy(scenario.policy_id)["version"] == rated_version

    assert bind_policy_ok(scenario.policy_id)["uw_status"] == "BOUND"

    validate_error(
        decline_policy(scenario.policy_id, "changed our minds"),
        ApiErrorId.ERR_POLICY_NOT_BOUND.value,
        409,
    )

    after = read_policy(scenario.policy_id)
    assert after["uw_status"] == "BOUND"
    assert after["closure_reason"] is None
    assert after["total_premium_cents"] == 269_200
    assert after["version"] == 3
    assert {row["status"] for row in reservation_by_peril(scenario.policy_id).values()} == {
        "COMMITTED"
    }


def test_a_declined_package_freezes_itself_and_everything_hanging_off_it(api):
    """"Once a policy reaches a terminal `uw_status`, it and every row hanging off
    it are frozen: any mutating call on the policy or on any of its scheduled
    items, livestock groups, liability exposures, labor profile, endorsements,
    inspections or recommendations is rejected with `ERR_POLICY_TERMINAL` (HTTP
    409)." The decline first cancels the visit still on the calendar — "every
    inspection of the policy still in `SCHEDULED` is moved to `CANCELLED`" — and
    then refuses six different mutations under the one error, the rating attempt
    included.

    Design: Corner/state_machines/corner_declined_policy_locks_itself_and_all_children
    """
    scenario = setup_draft_policy_with_dwelling()
    scenario.inspector = register_inspector()
    inspection = schedule_inspection_ok(scenario.policy_id, scenario.inspector_id)

    declined = decline_policy_ok(
        scenario.policy_id, "unacceptable wildfire exposure", headers=SENIOR
    )
    assert declined["uw_status"] == "DECLINED"
    assert declined["closure_reason"] == "unacceptable wildfire exposure"
    assert read_inspection(inspection["id"])["status"] == "CANCELLED"
    declined_version = declined["version"]

    validate_error(
        rate_policy(scenario.policy_id), ApiErrorId.ERR_POLICY_TERMINAL.value, 409
    )
    validate_error(
        api.create_scheduled_item(
            scenario.policy_id,
            create_scheduled_item_payload(
                item_class="EQUIPMENT",
                description="Combine",
                valuation_basis="ACV",
                stated_value_cents=30_001_000,
                age_years=12,
                condition_grade="B",
            ),
            scenario.agent_headers,
        ),
        ApiErrorId.ERR_POLICY_TERMINAL.value,
        409,
    )
    validate_error(
        patch_item(scenario.item["id"], scenario.agent_headers, stated_value_cents=45_000_000),
        ApiErrorId.ERR_POLICY_TERMINAL.value,
        409,
    )
    validate_error(
        api.upsert_labor_profile(
            scenario.policy_id,
            create_labor_profile_payload(full_time_count=1),
            scenario.agent_headers,
        ),
        ApiErrorId.ERR_POLICY_TERMINAL.value,
        409,
    )
    validate_error(
        schedule_inspection(
            scenario.policy_id,
            scenario.inspector_id,
            scheduled_for="2026-08-18T09:00:00Z",
            headers=COMPLIANCE,
        ),
        ApiErrorId.ERR_POLICY_TERMINAL.value,
        409,
    )
    validate_error(
        decline_policy(scenario.policy_id, "again"), ApiErrorId.ERR_POLICY_TERMINAL.value, 409
    )

    assert read_item(scenario.item["id"])["stated_value_cents"] == 40_000_000
    items, item_meta = validate_paginated(api.list_scheduled_items(scenario.policy_id, UW))
    assert item_meta["total_count"] == 1
    assert [row["id"] for row in items] == [scenario.item["id"]]
    profiles, profile_meta = validate_paginated(
        api.get_policy_labor_profile(scenario.policy_id, UW)
    )
    assert profiles == []
    assert profile_meta["total_count"] == 0
    assert read_policy(scenario.policy_id)["version"] == declined_version


def test_an_endorsement_cannot_be_decided_a_second_time(api):
    """"The endorsement must be in `REQUESTED`, or `ERR_ENDORSEMENT_NOT_REQUESTED`."
    A peak-season increase of 12000000 prices at 132000 and lifts base and total
    with it, while "`cat_load_cents` is never recomputed by an endorsement — the
    catastrophe load is frozen at the rating that produced the current
    reservations." The identical second approval is refused, so the premium is
    posted once and only once.

    Design: Corner/state_machines/corner_endorsement_decided_twice_rejected
    """
    scenario = setup_rated_dwelling_policy(with_labor_profile=False)
    endorsement = request_endorsement_ok(
        UW,
        scenario.policy_id,
        form_code="PEAK_SEASON_INCREASE",
        sublimit_cents=12_000_000,
        requested_effective_date="2026-09-01",
    )
    assert endorsement["requires_inspection"] is False

    approved = validate_success(
        decide_endorsement(endorsement["id"], "APPROVE", "seasonal inventory build")
    )
    assert approved["status"] == "APPROVED"
    assert approved["premium_cents"] == 132_000

    policy = read_policy(scenario.policy_id)
    assert policy["endorsement_premium_cents"] == 132_000
    assert policy["base_premium_cents"] == 276_000
    assert policy["cat_load_cents"] == 125_200
    assert policy["total_premium_cents"] == 401_200

    entries = read_ledger(scenario.policy_id)
    assert [row["sequence_no"] for row in entries] == [1, 2, 3]
    assert entries[2]["txn_type"] == "ENDORSEMENT_ADD"
    assert entries[2]["amount_cents"] == 132_000
    assert entries[2]["reason_code"] == "ENDORSEMENT_APPROVAL"
    assert sum(row["amount_cents"] for row in entries) == 401_200

    validate_error(
        decide_endorsement(endorsement["id"], "APPROVE", "again", headers=SENIOR),
        ApiErrorId.ERR_ENDORSEMENT_NOT_REQUESTED.value,
        409,
    )

    after = read_ledger(scenario.policy_id)
    assert len([row for row in after if row["txn_type"] == "ENDORSEMENT_ADD"]) == 1
    assert read_policy(scenario.policy_id)["total_premium_cents"] == 401_200
    assert read_endorsement(endorsement["id"])["version"] == 2


def test_a_rejected_endorsement_touches_no_money_and_cannot_be_rescinded(api):
    """"`REJECT` moves it `REQUESTED → REJECTED`, stores `decision_note` and
    `decided_by_user_id`, leaves `premium_cents` at 0, appends no ledger entry,
    changes no policy field, and lifts only the endorsement's `version` by 1."
    Rescission then refuses the row: "The row must be in `APPROVED` or
    `SUSPENDED`, or the call draws `ERR_ENDORSEMENT_NOT_APPROVED`, and the policy's
    `uw_status` must be `RATED` or `BOUND`."

    Design: Corner/state_machines/corner_endorsement_reject_then_rescind_refused
    """
    scenario = setup_rated_dwelling_policy(with_labor_profile=False)
    endorsement = request_endorsement_ok(
        UW,
        scenario.policy_id,
        form_code="PEAK_SEASON_INCREASE",
        sublimit_cents=12_000_000,
        requested_effective_date="2026-09-01",
    )

    rejected = validate_success(
        decide_endorsement(
            endorsement["id"], "REJECT", "values not supported", headers=SENIOR_ALT
        )
    )

    assert rejected["status"] == "REJECTED"
    assert rejected["premium_cents"] == 0
    assert rejected["decision_note"] == "values not supported"
    assert rejected["decided_by_user_id"] == SENIOR_ALT["X-User-ID"]
    assert rejected["version"] == 2

    entries = read_ledger(scenario.policy_id)
    assert len(entries) == 2
    assert sum(row["amount_cents"] for row in entries) == 269_200
    policy = read_policy(scenario.policy_id)
    assert policy["version"] == 2
    assert policy["endorsement_premium_cents"] == 0

    validate_error(
        rescind_endorsement(endorsement["id"], "undo"),
        ApiErrorId.ERR_ENDORSEMENT_NOT_APPROVED.value,
        409,
    )

    unchanged = read_endorsement(endorsement["id"])
    assert unchanged["status"] == "REJECTED"
    assert unchanged["version"] == 2
    assert len(read_ledger(scenario.policy_id)) == 2


def test_rescinding_an_approved_endorsement_walks_the_premium_back_down(api):
    """"Rescinding from `APPROVED` appends an `ENDORSEMENT_REMOVE` entry whose
    `amount_cents` is the negation of `premium_cents` with `reason_code`
    `ENDORSEMENT_RESCISSION`." The four ledger rows net back to the rated 269200,
    the row itself keeps no money, and the catastrophe load is untouched
    throughout.

    Design: Corner/state_machines/corner_endorsement_rescission_removes_its_premium
    """
    scenario = setup_policy_with_approved_endorsement(with_labor_profile=False)
    endorsement_id = scenario.endorsement["id"]
    assert scenario.endorsement["premium_cents"] == 132_000

    rescinded = validate_success(
        rescind_endorsement(endorsement_id, "insured withdrew the request")
    )

    assert rescinded["status"] == "RESCINDED"
    assert rescinded["premium_cents"] == 0
    assert rescinded["version"] == 3

    entries = ledger_by_sequence(read_ledger(scenario.policy_id))
    assert len(entries) == 4
    assert entries[3]["txn_type"] == "ENDORSEMENT_ADD"
    assert entries[3]["amount_cents"] == 132_000
    assert entries[4]["txn_type"] == "ENDORSEMENT_REMOVE"
    assert entries[4]["amount_cents"] == -132_000
    assert entries[4]["reason_code"] == "ENDORSEMENT_RESCISSION"
    assert sum(row["amount_cents"] for row in entries.values()) == 269_200

    policy = read_policy(scenario.policy_id)
    assert policy["endorsement_premium_cents"] == 0
    assert policy["base_premium_cents"] == 144_000
    assert policy["cat_load_cents"] == 125_200
    assert policy["total_premium_cents"] == 269_200
    assert policy["version"] == 4


def test_only_the_assigned_inspector_may_close_out_the_visit(api):
    """"The caller's `X-User-ID` must equal the inspection's `inspector_id`, or
    `ERR_NOT_ASSIGNED_INSPECTOR`." A second loss-control specialist holds the
    right role and is refused anyway; the assigned inspector then closes the same
    row with no findings, which scores the `INITIAL` base of 10 and moves the
    compliance axis to `COMPLIANT` while the underwriting axis stays `DRAFT`.

    Design: Corner/state_machines/corner_inspection_completion_only_by_assigned_inspector
    """
    scenario = setup_draft_policy_with_dwelling()
    scenario.inspector = register_inspector()
    peer = register_inspector(full_name="Lee Whitfield")
    inspection = schedule_inspection_ok(scenario.policy_id, scenario.inspector_id)

    validate_error(
        complete_inspection(inspection["id"], peer["id"], findings_summary="peer attempt"),
        ApiErrorId.ERR_NOT_ASSIGNED_INSPECTOR.value,
        403,
    )
    still_scheduled = read_inspection(inspection["id"])
    assert still_scheduled["status"] == "SCHEDULED"
    assert still_scheduled["completed_at"] is None

    completed = complete_inspection_ok(
        inspection["id"],
        scenario.inspector_id,
        findings_summary="housekeeping acceptable, no findings",
        findings=[],
    )

    assert completed["status"] == "COMPLETED"
    assert completed["completed_at"].startswith("2026-08-15T00:00:00")
    assert completed["hazard_score"] == 10
    assert completed["recommendation_count"] == 0
    assert read_recommendations(inspection["id"]) == []

    policy = read_policy(scenario.policy_id)
    assert policy["compliance_status"] == "COMPLIANT"
    assert policy["uw_status"] == "DRAFT"


def test_the_inspection_cycle_alternates_and_refuses_a_repeat_of_either_hop(api):
    """"The inspection must be `SCHEDULED`, or `ERR_INSPECTION_STATE_INVALID`" on
    completion, and on the way back out "The row must be `COMPLETED` or the call
    draws `ERR_INSPECTION_STATE_INVALID`, the policy must not be closed, the
    holding inspector's `status` must still be `ACTIVE`". The visit in between keeps the
    earlier score and finding, because "`hazard_score` and
    `recommendation_count` are retained until the re-inspection completes,
    existing recommendation rows are untouched, the policy's `compliance_status`
    does not move".

    Design: Corner/state_machines/corner_completion_and_reinspection_are_not_repeatable
    """
    scenario = setup_draft_policy_with_dwelling()
    scenario.inspector = register_inspector()
    inspection = schedule_inspection_ok(scenario.policy_id, scenario.inspector_id)

    completed = complete_inspection_ok(
        inspection["id"],
        scenario.inspector_id,
        findings_summary="guarding missing on the PTO shaft",
        findings=[PTO_FINDING],
    )
    assert completed["hazard_score"] == 22
    assert completed["recommendation_count"] == 1
    recommendations = read_recommendations(inspection["id"])
    assert [row["sequence_no"] for row in recommendations] == [1]
    assert recommendations[0]["status"] == "OPEN"
    assert recommendations[0]["due_date"] == "2026-09-30"
    assert read_policy(scenario.policy_id)["compliance_status"] == "RECS_OPEN"

    validate_error(
        complete_inspection(inspection["id"], scenario.inspector_id, findings_summary="again"),
        ApiErrorId.ERR_INSPECTION_STATE_INVALID.value,
        409,
    )
    assert read_inspection(inspection["id"])["recommendation_count"] == 1

    reopened = validate_success(
        reinspect(inspection["id"], scheduled_for="2026-08-20T09:00:00Z", duration_minutes=60)
    )
    assert reopened["status"] == "SCHEDULED"
    assert reopened["inspection_type"] == "RE_INSPECTION"
    assert reopened["scheduled_for"].startswith("2026-08-20T09:00:00")
    assert reopened["duration_minutes"] == 60
    assert reopened["completed_at"] is None
    assert reopened["hazard_score"] == 22
    assert [row["id"] for row in read_recommendations(inspection["id"])] == [
        recommendations[0]["id"]
    ]

    validate_error(
        reinspect(inspection["id"], scheduled_for="2026-08-21T09:00:00Z", duration_minutes=60),
        ApiErrorId.ERR_INSPECTION_STATE_INVALID.value,
        409,
    )
    assert read_inspection(inspection["id"])["scheduled_for"].startswith("2026-08-20T09:00:00")
    assert read_policy(scenario.policy_id)["compliance_status"] == "RECS_OPEN"


def test_the_remediation_loop_may_repeat_and_only_acceptance_clears_the_file(api):
    """"`REJECT` also requires `SUBMITTED` and sends the row back to `OPEN`,
    retaining `evidence_note` and `completed_date` for the next attempt and
    leaving the policy's `compliance_status` where it was — this is the
    remediation loop, and evidence can be resubmitted as often as necessary."
    Only the closing `ACCEPT` clears the file, after which "any review of a row
    already `VERIFIED` or `WAIVED`, draws `ERR_RECOMMENDATION_STATE_INVALID`".

    Design: Corner/state_machines/corner_recommendation_reject_loop_then_accept_clears_compliance
    """
    scenario = setup_draft_policy_with_dwelling()
    scenario.inspector = register_inspector()
    inspection = schedule_inspection_ok(scenario.policy_id, scenario.inspector_id)
    complete_inspection_ok(
        inspection["id"],
        scenario.inspector_id,
        findings_summary="guarding missing on the PTO shaft",
        findings=[PTO_FINDING],
    )
    recommendation_id = read_recommendations(inspection["id"])[0]["id"]

    first = validate_success(
        submit_evidence(
            scenario.agent_headers,
            recommendation_id,
            evidence_note="shield ordered",
            completed_date="2026-08-16",
        )
    )
    assert first["status"] == "SUBMITTED"
    assert read_policy(scenario.policy_id)["compliance_status"] == "RECS_OPEN"

    sent_back = validate_success(
        review_recommendation(
            recommendation_id, "REJECT", "photo does not show the installed shield"
        )
    )
    assert sent_back["status"] == "OPEN"
    assert sent_back["evidence_note"] == "shield ordered"
    assert sent_back["completed_date"] == "2026-08-16"
    assert sent_back["reviewed_by_user_id"] == COMPLIANCE["X-User-ID"]
    assert read_policy(scenario.policy_id)["compliance_status"] == "RECS_OPEN"

    second = validate_success(
        submit_evidence(
            scenario.agent_headers,
            recommendation_id,
            evidence_note="shield installed, photo attached",
            completed_date="2026-08-18",
        )
    )
    assert second["status"] == "SUBMITTED"
    assert read_policy(scenario.policy_id)["compliance_status"] == "RECS_OPEN"

    accepted = validate_success(review_recommendation(recommendation_id, "ACCEPT", "verified"))
    assert accepted["status"] == "VERIFIED"
    assert accepted["version"] == 5
    assert read_policy(scenario.policy_id)["compliance_status"] == "COMPLIANT"

    validate_error(
        submit_evidence(
            scenario.agent_headers,
            recommendation_id,
            evidence_note="more photos",
            completed_date="2026-08-19",
        ),
        ApiErrorId.ERR_RECOMMENDATION_STATE_INVALID.value,
        409,
    )
    validate_error(
        review_recommendation(recommendation_id, "WAIVE", "never mind"),
        ApiErrorId.ERR_RECOMMENDATION_STATE_INVALID.value,
        409,
    )

    assert read_recommendations(inspection["id"])[0]["status"] == "VERIFIED"
    policy = read_policy(scenario.policy_id)
    assert policy["uw_status"] == "DRAFT"
    assert policy["total_premium_cents"] == 0


def test_the_workers_compensation_proof_is_judged_completeness_first(api):
    """"Three conditions guard it: the `coordination_status` must actually be
    `PENDING_PROOF`, or the call is rejected with `ERR_WC_STATE_INVALID`;
    `wc_carrier_name`, `wc_policy_number` and `wc_expiry_date` must all be
    populated, or it is rejected with `ERR_WC_PROOF_MISSING`; and
    `wc_expiry_date` must be on or after the current logical clock date, or it is
    rejected with `ERR_WC_PROOF_EXPIRED`." A six-unit crew therefore fails first
    on the blank certificate, then on a stale one dated 2026-08-10, and reaches
    `VERIFIED` only on a certificate that outlives the clock.

    Design: Corner/state_machines/corner_wc_verification_precondition_matrix
    """
    scenario = setup_draft_policy_with_dwelling()
    profile = upsert_labor_profile(
        scenario.agent_headers,
        scenario.policy_id,
        full_time_count=4,
        seasonal_count=4,
        migrant_h2a_count=0,
    )
    assert float(profile["labor_exposure_units"]) == 6.00
    assert profile["wc_required"] is True
    assert profile["coordination_status"] == "PENDING_PROOF"

    validate_error(
        verify_wc(profile["id"], "no proof on file"),
        ApiErrorId.ERR_WC_PROOF_MISSING.value,
        422,
    )

    upsert_labor_profile(
        scenario.agent_headers,
        scenario.policy_id,
        full_time_count=4,
        seasonal_count=4,
        migrant_h2a_count=0,
        wc_carrier_name="Prairie Mutual WC",
        wc_policy_number="WC-2026-0001",
        wc_expiry_date="2026-08-10",
    )

    validate_error(
        verify_wc(profile["id"], "stale certificate"),
        ApiErrorId.ERR_WC_PROOF_EXPIRED.value,
        422,
    )

    upsert_labor_profile(
        scenario.agent_headers,
        scenario.policy_id,
        full_time_count=4,
        seasonal_count=4,
        migrant_h2a_count=0,
        wc_carrier_name="Prairie Mutual WC",
        wc_policy_number="WC-2026-0002",
        wc_expiry_date="2027-08-31",
    )

    verified = validate_success(verify_wc(profile["id"], "certificate on file"))

    assert verified["coordination_status"] == "VERIFIED"
    assert verified["verified_at"].startswith("2026-08-15T00:00:00")
    assert verified["verified_by_user_id"] == COMPLIANCE["X-User-ID"]
    assert verified["version"] == 4

    profiles, meta = validate_paginated(api.get_policy_labor_profile(scenario.policy_id, UW))
    assert meta["total_count"] == 1
    assert [row["id"] for row in profiles] == [profile["id"]]
    policy = read_policy(scenario.policy_id)
    assert policy["uw_status"] == "DRAFT"
    assert policy["total_premium_cents"] == 0
