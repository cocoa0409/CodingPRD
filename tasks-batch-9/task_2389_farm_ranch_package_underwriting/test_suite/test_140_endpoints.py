"""What the routes themselves are obliged to report: a derived figure that is
allowed to go negative, the checkpoint's five counters, a frozen read, the state
a request is gated on, and the two body references a booking must resolve."""

from test_helpers import (
    ApiErrorId,
    COMPLIANCE,
    NON_EXISTENT_UUID,
    UW,
    add_scheduled_item,
    assert_inspection,
    assert_pool_capacity_identity,
    assert_sweep_counters,
    bind_policy_ok,
    bootstrap_zone,
    complete_inspection_ok,
    get_success_data,
    open_account,
    open_policy,
    patch_pool,
    rate_policy_ok,
    read_endorsement,
    read_labor_profile,
    read_policy,
    read_pool,
    register_inspector,
    request_endorsement,
    request_endorsement_ok,
    reservation_by_peril,
    run_sweep_ok,
    schedule_inspection,
    schedule_inspection_ok,
    set_clock,
    setup_draft_policy_with_dwelling,
    setup_rated_dwelling_policy,
    upsert_labor_profile,
    validate_error,
    validate_paginated,
    validate_success,
    verify_wc,
)

WC_PROOF_EXPIRING = {
    "wc_carrier_name": "Prairie Mutual WC",
    "wc_policy_number": "WC-2026-0140",
    "wc_expiry_date": "2026-08-10",
}


def test_shrinking_a_pool_under_its_holdings_reports_a_negative_availability(api):
    """"Resizing or freezing a pool afterwards takes `expected_pool_version`
    together with either or both of `total_capacity_cents` and `status`; the
    pool's `available_cents` is re-derived from the new capacity against whatever
    is currently reserved and committed, and its `version` climbs by 1."
    "`available_cents` is `total_capacity_cents` less `reserved_cents` less
    `committed_cents`." A pool holding a 20000000-cent reservation and cut to
    10000000 of capacity therefore reports minus 10000000, because "shrinking a
    pool below what it already holds is permitted and drives `available_cents`
    negative; the figure is reported as computed and is not clamped at zero."

    Design: Corner/endpoints/corner_pool_patch_can_drive_available_capacity_negative
    """
    scenario = setup_rated_dwelling_policy()
    before = read_pool(scenario.hail_pool["id"])
    assert before["total_capacity_cents"] == 200_000_000
    assert before["reserved_cents"] == 20_000_000
    assert before["committed_cents"] == 0
    assert before["available_cents"] == 180_000_000
    assert before["version"] == 2

    shrunk = validate_success(patch_pool(before["id"], total_capacity_cents=10_000_000))

    assert shrunk["total_capacity_cents"] == 10_000_000
    assert shrunk["reserved_cents"] == 20_000_000
    assert shrunk["committed_cents"] == 0
    assert shrunk["available_cents"] == -10_000_000
    assert shrunk["version"] == before["version"] + 1
    assert_pool_capacity_identity(shrunk)
    assert read_pool(before["id"])["available_cents"] == -10_000_000

    hail = reservation_by_peril(scenario.policy_id)["HAIL"]
    assert hail["status"] == "RESERVED"
    assert hail["amount_cents"] == 20_000_000
    assert float(hail["utilization_at_rating"]) == 0.100000

    assert read_policy(scenario.policy_id)["total_premium_cents"] == 269_200


def test_one_checkpoint_pass_moves_four_counters_and_the_next_pass_moves_none(api):
    """"Every recommendation in `OPEN` whose `due_date` falls strictly before the
    current clock date is moved `OPEN → OVERDUE` and each affected policy advances
    `RECS_OPEN → RECS_OVERDUE`." "Then, in the same pass that aged the
    recommendation, a policy whose `uw_status` is `RATED` or `BOUND` and which now
    holds at least one `CRITICAL` recommendation in `OVERDUE` is escalated
    `RECS_OVERDUE → SUSPENDED`, and its endorsements with `requires_inspection`
    true and `status` `APPROVED` are suspended with the same `ENDORSEMENT_REMOVE`
    entries and `COMPLIANCE_SUSPENSION` reason code as the completion cascade — a
    single run therefore performs both hops for the same policy." "Separately,
    every labor profile in `VERIFIED` whose `wc_expiry_date` falls strictly before
    the current clock date is moved `VERIFIED → LAPSED` with `verified_at` and
    `verified_by_user_id` cleared." The draft policy's minor finding ages but
    cannot escalate; the rated policy takes both hops at once and loses its proof.
    "The checkpoint is idempotent: running it twice at the same clock value changes
    nothing on the second run."

    Design: Corner/endpoints/corner_compliance_sweep_reports_every_counter_it_moved
    """
    scenario = bootstrap_zone(
        clock="2026-08-01T00:00:00Z",
        with_policy=False,
        account_overrides={"legal_name": "Sweep One Farms"},
    )
    headers = scenario.agent_headers
    inspector = register_inspector()

    draft_policy = open_policy(headers, scenario.account["id"])
    add_scheduled_item(headers, draft_policy["id"])
    draft_visit = schedule_inspection_ok(
        draft_policy["id"], inspector["id"], scheduled_for="2026-08-02T09:00:00Z"
    )
    draft_visit = complete_inspection_ok(
        draft_visit["id"],
        inspector["id"],
        findings_summary="Housekeeping in the machine shed",
        findings=[
            {
                "severity": "MINOR",
                "description": "Clear the aisle behind the shop bench",
                "due_date": "2026-08-10",
            }
        ],
    )
    assert draft_visit["hazard_score"] == 14

    rated_account = open_account(headers, legal_name="Sweep Two Farms")
    rated_policy = open_policy(headers, rated_account["id"])
    add_scheduled_item(headers, rated_policy["id"])
    profile = upsert_labor_profile(
        headers,
        rated_policy["id"],
        full_time_count=4,
        seasonal_count=4,
        migrant_h2a_count=0,
        **WC_PROOF_EXPIRING,
    )
    verified = get_success_data(verify_wc(profile["id"], note="Certificate on file"))
    assert verified["coordination_status"] == "VERIFIED"
    assert rate_policy_ok(rated_policy["id"])["total_premium_cents"] == 269_200
    rated_visit = schedule_inspection_ok(
        rated_policy["id"], inspector["id"], scheduled_for="2026-08-03T09:00:00Z"
    )
    rated_visit = complete_inspection_ok(
        rated_visit["id"],
        inspector["id"],
        findings_summary="Grain leg guarding missing",
        findings=[
            {
                "severity": "CRITICAL",
                "description": "Refit the guard on the grain leg",
                "due_date": "2026-08-10",
            }
        ],
    )
    assert rated_visit["hazard_score"] == 40
    assert read_policy(rated_policy["id"])["compliance_status"] == "RECS_OPEN"

    set_clock("2026-08-15T00:00:00Z")
    first_pass = run_sweep_ok()

    assert_sweep_counters(
        first_pass,
        policies_scanned=2,
        recommendations_marked_overdue=2,
        policies_marked_recs_overdue=2,
        policies_suspended=1,
        labor_profiles_lapsed=1,
    )
    stayed_draft = read_policy(draft_policy["id"])
    assert stayed_draft["uw_status"] == "DRAFT"
    assert stayed_draft["compliance_status"] == "RECS_OVERDUE"
    escalated = read_policy(rated_policy["id"])
    assert escalated["uw_status"] == "RATED"
    assert escalated["compliance_status"] == "SUSPENDED"
    assert escalated["total_premium_cents"] == 269_200
    lapsed = read_labor_profile(profile["id"])
    assert lapsed["coordination_status"] == "LAPSED"
    assert lapsed["verified_at"] is None
    assert lapsed["verified_by_user_id"] is None

    second_pass = run_sweep_ok()

    assert_sweep_counters(
        second_pass,
        policies_scanned=2,
        recommendations_marked_overdue=0,
        policies_marked_recs_overdue=0,
        policies_suspended=0,
        labor_profiles_lapsed=0,
    )
    assert read_policy(draft_policy["id"])["compliance_status"] == "RECS_OVERDUE"
    assert read_policy(rated_policy["id"])["compliance_status"] == "SUSPENDED"
    assert read_labor_profile(profile["id"])["coordination_status"] == "LAPSED"


def test_a_reservation_keeps_the_utilization_it_was_written_with(api):
    """"A reservation row records the policy and pool it bridges through
    `policy_id` and `pool_id`, copies the pool's `peril` at the moment it is
    written, and carries the derived `amount_cents`, `utilization_at_rating`,
    `scarcity_factor` and `load_cents` described in §3.7." Doubling the pool's
    capacity afterwards re-derives only the pool: "Resizing or freezing a pool
    afterwards takes `expected_pool_version` together with either or both of
    `total_capacity_cents` and `status`; the pool's `available_cents` is re-derived
    from the new capacity against whatever is currently reserved and committed, and
    its `version` climbs by 1." The row keeps the 0.100000 it was priced against
    and the policy keeps the load that ratio bought.

    Design: Corner/endpoints/corner_reservation_read_shows_frozen_rating_snapshot
    """
    scenario = setup_rated_dwelling_policy()
    reservations, meta = validate_paginated(
        api.list_cat_reservations(UW, params={"policy_id": scenario.policy_id, "peril": "HAIL"})
    )
    assert meta["total_count"] == 1
    hail = reservations[0]
    assert hail["pool_id"] == scenario.hail_pool["id"]
    assert hail["amount_cents"] == 20_000_000
    assert float(hail["utilization_at_rating"]) == 0.100000
    assert float(hail["scarcity_factor"]) == 1.00
    assert hail["load_cents"] == 64_000

    enlarged = validate_success(
        patch_pool(scenario.hail_pool["id"], total_capacity_cents=400_000_000)
    )
    assert enlarged["total_capacity_cents"] == 400_000_000
    assert enlarged["reserved_cents"] == 20_000_000
    assert enlarged["available_cents"] == 380_000_000

    frozen = validate_success(api.get_cat_reservation(hail["id"], UW))

    assert frozen["amount_cents"] == 20_000_000
    assert float(frozen["utilization_at_rating"]) == 0.100000
    assert float(frozen["scarcity_factor"]) == 1.00
    assert frozen["load_cents"] == 64_000
    assert frozen["status"] == "RESERVED"
    assert frozen["version"] == hail["version"]

    policy = read_policy(scenario.policy_id)
    assert policy["cat_load_cents"] == 125_200
    assert policy["total_premium_cents"] == 269_200


def test_an_endorsement_request_waits_for_the_quote_and_leaves_the_version_alone(api):
    """"The policy's `uw_status` must be `RATED` or `BOUND`, or the request draws
    `ERR_POLICY_NOT_RATED`, and its `compliance_status` must not be `SUSPENDED`, or
    `ERR_COMPLIANCE_SUSPENDED`." "The new row lands in `status` `REQUESTED` with
    `premium_cents` 0, `decision_note` and `decided_by_user_id` null, and
    `requires_inspection` derived as true exactly when `form_code` is
    `POLLUTION_BUYBACK` or `CHEMICAL_APPLICATION_BUYBACK` and false for the other
    two forms." The same request refused on the draft succeeds the moment the quote
    exists, and because "requesting an endorsement changes no policy premium figure
    and — importantly for the version check that guards it — does not lift the
    policy's `version`", the version observed before the request is still the one
    that binds. A bound policy accepts a further request.

    Design: Corner/endpoints/corner_endorsement_creation_is_gated_on_uw_status
    """
    scenario = setup_draft_policy_with_dwelling()
    upsert_labor_profile(scenario.agent_headers, scenario.policy_id)

    refused = request_endorsement(
        scenario.agent_headers,
        scenario.policy_id,
        form_code="AGRITOURISM_LIABILITY",
        sublimit_cents=10_000_000,
    )

    validate_error(refused, ApiErrorId.ERR_POLICY_NOT_RATED.value, 409)
    _, empty_meta = validate_paginated(api.list_endorsements(scenario.policy_id, UW))
    assert empty_meta["total_count"] == 0

    rated = rate_policy_ok(scenario.policy_id)
    assert rated["uw_status"] == "RATED"
    assert rated["version"] == 2
    assert rated["total_premium_cents"] == 269_200

    requested = request_endorsement_ok(
        scenario.agent_headers,
        scenario.policy_id,
        form_code="AGRITOURISM_LIABILITY",
        sublimit_cents=10_000_000,
    )

    assert requested["status"] == "REQUESTED"
    assert requested["premium_cents"] == 0
    assert requested["requires_inspection"] is False
    assert requested["decided_by_user_id"] is None
    assert requested["decision_note"] is None
    unmoved = read_policy(scenario.policy_id)
    assert unmoved["version"] == 2
    assert unmoved["total_premium_cents"] == 269_200

    bound = bind_policy_ok(scenario.policy_id)
    assert bound["uw_status"] == "BOUND"
    assert bound["total_premium_cents"] == 269_200

    on_bound = request_endorsement_ok(
        scenario.agent_headers,
        scenario.policy_id,
        form_code="PEAK_SEASON_INCREASE",
        sublimit_cents=12_000_000,
    )

    assert on_bound["status"] == "REQUESTED"
    assert on_bound["premium_cents"] == 0
    assert on_bound["requires_inspection"] is False
    assert read_endorsement(requested["id"])["status"] == "REQUESTED"
    _, both_meta = validate_paginated(api.list_endorsements(scenario.policy_id, UW))
    assert both_meta["total_count"] == 2
    assert read_policy(scenario.policy_id)["total_premium_cents"] == 269_200


def test_a_booking_resolves_the_policy_before_the_inspector(api):
    """"The booking names `policy_id` and `inspector_id`, an `inspection_type` of
    `INITIAL`, `RE_INSPECTION` or `LOSS_TRIGGERED`, a `scheduled_for` instant in
    ISO 8601 UTC, and a `duration_minutes` between 30 and 480 inclusive." Both
    references must resolve, and the ladder's "body-referenced existence —
    `ERR_FARM_ACCOUNT_NOT_FOUND`, `ERR_FARM_POLICY_NOT_FOUND` or
    `ERR_INSPECTOR_NOT_FOUND` (404), in declared field order" reports the policy
    first. Once both resolve, "a new inspection lands in `status` `SCHEDULED` with
    `hazard_score` 0, `recommendation_count` 0, and `completed_at` and
    `findings_summary` null" and the policy's compliance axis has not moved.

    Design: Corner/endpoints/corner_inspection_links_an_existing_policy_and_inspector
    """
    scenario = setup_draft_policy_with_dwelling()
    inspector = register_inspector()

    no_policy = schedule_inspection(NON_EXISTENT_UUID, inspector["id"])
    validate_error(no_policy, ApiErrorId.ERR_FARM_POLICY_NOT_FOUND.value, 404)

    no_inspector = schedule_inspection(
        scenario.policy_id, NON_EXISTENT_UUID, headers=COMPLIANCE
    )
    validate_error(no_inspector, ApiErrorId.ERR_INSPECTOR_NOT_FOUND.value, 404)

    _, none_yet = validate_paginated(api.list_inspections(UW))
    assert none_yet["total_count"] == 0

    booked = schedule_inspection_ok(
        scenario.policy_id,
        inspector["id"],
        scheduled_for="2026-08-16T09:00:00Z",
        duration_minutes=120,
    )

    assert_inspection(booked)
    assert booked["policy_id"] == scenario.policy_id
    assert booked["inspector_id"] == inspector["id"]
    assert booked["inspection_type"] == "INITIAL"
    assert booked["status"] == "SCHEDULED"
    assert booked["duration_minutes"] == 120
    assert booked["scheduled_for"].startswith("2026-08-16T09:00:00")
    assert booked["hazard_score"] == 0
    assert booked["recommendation_count"] == 0
    assert booked["completed_at"] is None
    assert booked["findings_summary"] is None

    by_policy, policy_meta = validate_paginated(
        api.list_inspections(UW, params={"policy_id": scenario.policy_id})
    )
    assert policy_meta["total_count"] == 1
    assert [row["id"] for row in by_policy] == [booked["id"]]
    by_inspector, inspector_meta = validate_paginated(
        api.list_inspections(UW, params={"inspector_id": inspector["id"]})
    )
    assert inspector_meta["total_count"] == 1
    assert [row["id"] for row in by_inspector] == [booked["id"]]

    policy = read_policy(scenario.policy_id)
    assert policy["compliance_status"] == "NOT_INSPECTED"
    assert policy["uw_status"] == "DRAFT"
