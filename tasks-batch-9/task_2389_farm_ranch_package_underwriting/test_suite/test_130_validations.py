"""Rules that refuse a request: the three conditional-field couplings, the
inspector's calendar and standing, the workers-compensation gates, and the rungs
of the ladder that outrank one another."""

from test_helpers import (
    ADMIN,
    COMPLIANCE,
    NON_EXISTENT_UUID,
    ApiErrorId,
    UW,
    add_liability_exposure,
    assert_all_null,
    assert_sweep_counters,
    bind_policy,
    bind_policy_ok,
    bootstrap_zone,
    complete_inspection_ok,
    create_farm_account_payload,
    create_liability_exposure_payload,
    create_livestock_group_payload,
    create_scheduled_item_payload,
    decide_endorsement,
    ledger_by_sequence,
    open_pool,
    patch_inspector_ok,
    rate_policy_ok,
    read_endorsement,
    read_inspection,
    read_labor_profile,
    read_ledger,
    read_policy,
    read_pool,
    read_recommendations,
    read_reservations,
    register_inspector,
    reinspect,
    request_endorsement_ok,
    run_sweep_ok,
    schedule_inspection,
    schedule_inspection_ok,
    set_clock,
    setup_draft_policy_with_dwelling,
    setup_rated_dwelling_policy,
    setup_rated_policy_with_inspector,
    upsert_labor_profile,
    validate_error,
    validate_paginated,
    validate_success,
    verify_wc,
)

UNKNOWN_INSPECTOR_ID = "00000000-0000-4000-8000-000000000054"


def test_the_blanket_limit_is_demanded_and_refused_by_the_same_error(api):
    """"`blanket_limit_cents` is required when `limit_basis` is `BLANKET` and
    forbidden when it is `PER_HEAD`; either mismatch draws
    `ERR_BLANKET_LIMIT_REQUIRED`, and when supplied the value must be greater
    than zero." The identical 170-head herd is refused twice for opposite
    reasons, and once the election and the field agree the limit follows the
    blanket branch: "On the `BLANKET` election it is `blanket_limit_cents`
    multiplied by the blanket coinsurance percentage of 0.80, rounded half up;
    the aggregate cap does not apply on this branch, and `head_count` and
    `per_head_value_cents` are recorded on the row but do not enter the limit."

    Design: Corner/validations/corner_blanket_limit_required_and_forbidden
    """
    scenario = bootstrap_zone()
    headers = scenario.agent_headers

    missing = api.create_livestock_group(
        scenario.policy_id,
        create_livestock_group_payload(limit_basis="BLANKET", peril_scope="FULL_PERIL"),
        headers,
    )
    validate_error(missing, ApiErrorId.ERR_BLANKET_LIMIT_REQUIRED.value, 422)

    forbidden = api.create_livestock_group(
        scenario.policy_id,
        create_livestock_group_payload(
            limit_basis="PER_HEAD", peril_scope="FULL_PERIL", blanket_limit_cents=25_500_000
        ),
        headers,
    )
    validate_error(forbidden, ApiErrorId.ERR_BLANKET_LIMIT_REQUIRED.value, 422)

    accepted = validate_success(
        api.create_livestock_group(
            scenario.policy_id,
            create_livestock_group_payload(
                limit_basis="BLANKET", peril_scope="FULL_PERIL", blanket_limit_cents=25_500_000
            ),
            headers,
        ),
        201,
    )

    assert accepted["covered_limit_cents"] == 20_400_000
    assert accepted["head_count"] == 170
    assert accepted["per_head_value_cents"] == 150_000

    groups, meta = validate_paginated(api.list_livestock_groups(scenario.policy_id, UW))
    assert meta["total_count"] == 1
    assert [row["id"] for row in groups] == [accepted["id"]]


def test_three_shapes_of_a_broken_peak_season_trio_draw_one_error(api):
    """"All three of those fields must be present when `item_class` is
    `STORED_CROP`, `HAY` or `INPUTS`, and all three must be absent for
    `DWELLING`, `FARM_STRUCTURE` and `EQUIPMENT`; furthermore
    `peak_season_value_cents` must be greater than or equal to
    `stated_value_cents`." "A partial trio, a trio on the wrong class, a missing
    trio on a seasonal class, or a peak value below the off-peak value all draw
    `ERR_PEAK_SEASON_FIELDS_REQUIRED`." A dwelling with a season, a stored crop
    without one, and a stored crop whose peak is worth less than its off-peak
    value all fail; the accepted row is valued at its stated 6005000 because
    August lies outside an October-to-February window.

    Design: Corner/validations/corner_peak_season_triple_is_all_or_nothing
    """
    scenario = bootstrap_zone()
    headers = scenario.agent_headers

    season_on_a_dwelling = api.create_scheduled_item(
        scenario.policy_id,
        create_scheduled_item_payload(
            peak_season_value_cents=50_000_000,
            peak_season_start_month=10,
            peak_season_end_month=2,
        ),
        headers,
    )
    validate_error(season_on_a_dwelling, ApiErrorId.ERR_PEAK_SEASON_FIELDS_REQUIRED.value, 422)

    crop_without_a_season = api.create_scheduled_item(
        scenario.policy_id,
        create_scheduled_item_payload(
            item_class="STORED_CROP",
            description="Bin 4 corn",
            stated_value_cents=6_005_000,
            age_years=0,
            condition_grade="A",
        ),
        headers,
    )
    validate_error(crop_without_a_season, ApiErrorId.ERR_PEAK_SEASON_FIELDS_REQUIRED.value, 422)

    peak_below_stated = api.create_scheduled_item(
        scenario.policy_id,
        create_scheduled_item_payload(
            item_class="STORED_CROP",
            description="Bin 4 corn",
            stated_value_cents=6_005_000,
            age_years=0,
            condition_grade="A",
            peak_season_value_cents=5_000_000,
            peak_season_start_month=10,
            peak_season_end_month=2,
        ),
        headers,
    )
    validate_error(peak_below_stated, ApiErrorId.ERR_PEAK_SEASON_FIELDS_REQUIRED.value, 422)

    accepted = validate_success(
        api.create_scheduled_item(
            scenario.policy_id,
            create_scheduled_item_payload(
                item_class="STORED_CROP",
                description="Bin 4 corn",
                stated_value_cents=6_005_000,
                age_years=0,
                condition_grade="A",
                peak_season_value_cents=18_000_000,
                peak_season_start_month=10,
                peak_season_end_month=2,
            ),
            headers,
        ),
        201,
    )

    assert accepted["insured_value_cents"] == 6_005_000

    items, meta = validate_paginated(api.list_scheduled_items(scenario.policy_id, UW))
    assert meta["total_count"] == 1
    assert [row["id"] for row in items] == [accepted["id"]]


def test_the_visitor_count_belongs_to_agritourism_and_nowhere_else(api):
    """"`annual_visitor_count` is required when `exposure_type` is `AGRITOURISM`
    and forbidden for every other type; either mismatch draws
    `ERR_VISITOR_COUNT_REQUIRED`, and when supplied it must not be negative."
    The agritourism line that omits its count and the custom-farming line that
    volunteers one are refused by the same error, and the corrected custom-farming
    exposure prices at 157500: "A `CUSTOM_FARMING` exposure is 45000 cents plus
    `annual_receipts_cents` multiplied by 0.0075, the receipts term rounded half
    up before addition, capped at 900000 cents."

    Design: Corner/validations/corner_visitor_count_required_only_for_agritourism
    """
    scenario = bootstrap_zone()
    headers = scenario.agent_headers

    agritourism_without_count = api.create_liability_exposure(
        scenario.policy_id,
        {"exposure_type": "AGRITOURISM", "annual_receipts_cents": 4_000_000},
        headers,
    )
    validate_error(agritourism_without_count, ApiErrorId.ERR_VISITOR_COUNT_REQUIRED.value, 422)

    custom_farming_with_count = api.create_liability_exposure(
        scenario.policy_id,
        create_liability_exposure_payload(
            exposure_type="CUSTOM_FARMING",
            annual_receipts_cents=15_000_000,
            annual_visitor_count=100,
        ),
        headers,
    )
    validate_error(custom_farming_with_count, ApiErrorId.ERR_VISITOR_COUNT_REQUIRED.value, 422)

    accepted = validate_success(
        api.create_liability_exposure(
            scenario.policy_id,
            create_liability_exposure_payload(
                exposure_type="CUSTOM_FARMING", annual_receipts_cents=15_000_000
            ),
            headers,
        ),
        201,
    )

    assert accepted["exposure_premium_cents"] == 157_500
    assert accepted["annual_visitor_count"] is None

    exposures, meta = validate_paginated(api.list_liability_exposures(scenario.policy_id, UW))
    assert meta["total_count"] == 1
    assert [row["id"] for row in exposures] == [accepted["id"]]


def test_pool_uniqueness_binds_the_zone_and_the_peril_together(api):
    """"Opening a capacity pool captures `zone_code`, `peril`,
    `participation_pct` and `total_capacity_cents`, with `status` optional and
    defaulting to `OPEN`." "A second attempt to open a pool for a zone and peril
    that already have one is rejected with `ERR_DUPLICATE_POOL`." The pair is
    what must be unique, so a second hail pool in ZN-1 is refused while wind in
    the same zone and hail in another zone are both opened, and the refusal
    leaves the incumbent's participation and capacity exactly as registered.

    Design: Corner/validations/corner_duplicate_pool_rejected_per_zone_and_peril
    """
    set_clock()
    incumbent = open_pool("ZN-1", "HAIL")

    duplicate = api.create_cat_capacity_pool(
        {
            "zone_code": "ZN-1",
            "peril": "HAIL",
            "participation_pct": 0.25,
            "total_capacity_cents": 50_000_000,
        },
        ADMIN,
    )

    validate_error(duplicate, ApiErrorId.ERR_DUPLICATE_POOL.value, 409)
    unchanged = read_pool(incumbent["id"])
    assert float(unchanged["participation_pct"]) == 0.50
    assert unchanged["total_capacity_cents"] == 200_000_000
    assert unchanged["version"] == 1

    other_peril = open_pool("ZN-1", "WIND")
    other_zone = open_pool("ZN-2", "HAIL")
    for pool in (other_peril, other_zone):
        assert pool["reserved_cents"] == 0
        assert pool["committed_cents"] == 0
        assert pool["available_cents"] == pool["total_capacity_cents"]

    _, meta = validate_paginated(api.list_cat_capacity_pools(ADMIN))
    assert meta["total_count"] == 3


def test_the_day_fills_up_before_the_inspector_goes_off_duty(api):
    """"Second, day load: the sum of `duration_minutes` across the inspector's
    `SCHEDULED` inspections whose `scheduled_for` falls on the same UTC calendar
    date as the requested window, plus the requested `duration_minutes`, must not
    exceed the inspector's `daily_capacity_minutes`." "Third, the named
    inspector's `status` must be `ACTIVE`, or the booking is refused with
    `ERR_INSPECTOR_INACTIVE`." A 13:30 start clears the 12:30 buffered end of the
    booked visit, so the refusal of 180 further minutes comes from the 240-minute
    day and not from the calendar; 120 minutes fit the day exactly; and a later,
    empty, conflict-free day is refused only because the inspector was stood down.

    Design: Corner/validations/corner_inspector_day_capacity_then_inactive_status
    """
    scenario = setup_draft_policy_with_dwelling()
    inspector = register_inspector(
        full_name="Marta Kell", region_code="KS-WEST", daily_capacity_minutes=240
    )
    booked = schedule_inspection_ok(
        scenario.policy_id,
        inspector["id"],
        scheduled_for="2026-08-16T09:00:00Z",
        duration_minutes=120,
    )

    over_capacity = schedule_inspection(
        scenario.policy_id,
        inspector["id"],
        scheduled_for="2026-08-16T13:30:00Z",
        duration_minutes=180,
    )
    validate_error(over_capacity, ApiErrorId.ERR_INSPECTOR_DAY_CAPACITY_EXCEEDED.value, 409)

    exact_fit = schedule_inspection_ok(
        scenario.policy_id,
        inspector["id"],
        scheduled_for="2026-08-16T13:30:00Z",
        duration_minutes=120,
    )
    assert exact_fit["status"] == "SCHEDULED"
    assert exact_fit["duration_minutes"] == 120

    stood_down = patch_inspector_ok(inspector["id"], status="INACTIVE")
    assert stood_down["status"] == "INACTIVE"

    after_deactivation = schedule_inspection(
        scenario.policy_id,
        inspector["id"],
        scheduled_for="2026-08-18T09:00:00Z",
        duration_minutes=60,
        headers=COMPLIANCE,
    )
    validate_error(after_deactivation, ApiErrorId.ERR_INSPECTOR_INACTIVE.value, 422)

    for inspection in (booked, exact_fit):
        still_booked = read_inspection(inspection["id"])
        assert still_booked["status"] == "SCHEDULED"
        assert still_booked["version"] == 1
    _, meta = validate_paginated(
        api.list_inspections(ADMIN, params={"inspector_id": inspector["id"], "limit": 100})
    )
    assert meta["total_count"] == 2


def test_the_chemical_buyback_waits_for_its_companion_exposure(api):
    """"A `CHEMICAL_APPLICATION_BUYBACK` may only be approved on a policy that
    carries a `CUSTOM_FARMING` liability exposure, and an `AGRITOURISM_LIABILITY`
    form only on a policy that carries an `AGRITOURISM` exposure; a missing
    companion exposure draws `ERR_ENDORSEMENT_EXPOSURE_MISSING`." Both safety
    gates are already satisfied by a completed visit at hazard 10, so the first
    decision fails on the companion rule alone. Scheduling the custom-farming
    exposure reverts the quote and demands a fresh rating, after which "a
    `CHEMICAL_APPLICATION_BUYBACK` is `sublimit_cents` multiplied by 0.0220 and
    rounded half up, then raised to a minimum of 90000 cents."

    Design: Corner/validations/corner_chemical_buyback_needs_custom_farming_exposure
    """
    scenario = setup_rated_policy_with_inspector()
    clean = complete_inspection_ok(
        scenario.inspection["id"], scenario.inspector_id, findings_summary="clean risk", findings=[]
    )
    assert clean["hazard_score"] == 10
    assert read_policy(scenario.policy_id)["compliance_status"] == "COMPLIANT"

    endorsement = request_endorsement_ok(
        scenario.agent_headers,
        scenario.policy_id,
        form_code="CHEMICAL_APPLICATION_BUYBACK",
        sublimit_cents=5_000_000,
        requested_effective_date="2026-09-01",
    )
    assert endorsement["requires_inspection"] is True

    validate_error(
        decide_endorsement(endorsement["id"], "APPROVE", "spray operations"),
        ApiErrorId.ERR_ENDORSEMENT_EXPOSURE_MISSING.value,
        422,
    )
    still_requested = read_endorsement(endorsement["id"])
    assert still_requested["status"] == "REQUESTED"
    assert still_requested["premium_cents"] == 0

    add_liability_exposure(
        scenario.agent_headers,
        scenario.policy_id,
        "CUSTOM_FARMING",
        annual_receipts_cents=15_000_000,
    )
    reverted = read_policy(scenario.policy_id)
    assert reverted["uw_status"] == "DRAFT"
    assert read_endorsement(endorsement["id"])["status"] == "REQUESTED"

    rerated = rate_policy_ok(scenario.policy_id)
    assert rerated["property_premium_cents"] == 144_000
    assert rerated["liability_premium_cents"] == 157_500
    assert rerated["cat_load_cents"] == 125_200
    assert rerated["total_premium_cents"] == 426_700

    approved = validate_success(
        api.decide_endorsement(
            endorsement["id"],
            {"decision": "APPROVE", "decision_note": "custom farming now scheduled"},
            UW,
        )
    )

    assert approved["status"] == "APPROVED"
    assert approved["premium_cents"] == 110_000
    assert read_policy(scenario.policy_id)["total_premium_cents"] == 536_700

    entries = read_ledger(scenario.policy_id)
    assert [row["amount_cents"] for row in entries] == [
        144_000,
        125_200,
        -144_000,
        -125_200,
        144_000,
        157_500,
        125_200,
        110_000,
    ]
    assert sum(row["amount_cents"] for row in entries) == 536_700
    by_sequence = ledger_by_sequence(entries)
    assert by_sequence[3]["reason_code"] == "RATING_REVERT"
    assert by_sequence[8]["reason_code"] == "ENDORSEMENT_APPROVAL"


def test_an_overdue_critical_finding_stops_the_bind_without_a_suspension(api):
    """"Every recommendation in `OPEN` whose `due_date` falls strictly before the
    current clock date is moved `OPEN → OVERDUE` and each affected policy advances
    `RECS_OPEN → RECS_OVERDUE`." The escalation to a suspension needs a quote,
    and this policy is still a draft when the checkpoint runs, so the compliance
    axis stops at `RECS_OVERDUE` and the later bind reaches the next rung down:
    "No recommendation of `severity` `CRITICAL` on any inspection of the policy
    may be in `OVERDUE`, or `ERR_CRITICAL_REC_OVERDUE`."

    Design: Corner/validations/corner_critical_overdue_recommendation_blocks_bind
    """
    scenario = setup_draft_policy_with_dwelling()
    upsert_labor_profile(scenario.agent_headers, scenario.policy_id)
    inspector = register_inspector()
    inspection = schedule_inspection_ok(scenario.policy_id, inspector["id"])
    first = complete_inspection_ok(
        inspection["id"],
        inspector["id"],
        findings_summary="no findings on the initial survey",
        findings=[],
    )
    assert first["hazard_score"] == 10
    validate_success(
        reinspect(inspection["id"], scheduled_for="2026-08-17T09:00:00Z", headers=COMPLIANCE)
    )
    second = complete_inspection_ok(
        inspection["id"],
        inspector["id"],
        findings_summary="anhydrous storage unguarded",
        findings=[
            {
                "severity": "CRITICAL",
                "description": "Cage the anhydrous tank",
                "due_date": "2026-08-10",
            }
        ],
    )
    assert second["hazard_score"] == 35
    assert [row["sequence_no"] for row in read_recommendations(inspection["id"])] == [1]
    assert read_policy(scenario.policy_id)["compliance_status"] == "RECS_OPEN"

    counters = run_sweep_ok(scenario.policy_id)

    assert_sweep_counters(
        counters,
        policies_scanned=1,
        recommendations_marked_overdue=1,
        policies_marked_recs_overdue=1,
        policies_suspended=0,
        labor_profiles_lapsed=0,
    )
    swept = read_policy(scenario.policy_id)
    assert swept["compliance_status"] == "RECS_OVERDUE"
    assert swept["uw_status"] == "DRAFT"

    rated = rate_policy_ok(scenario.policy_id)
    assert rated["uw_status"] == "RATED"
    assert rated["total_premium_cents"] == 269_200

    response = bind_policy(scenario.policy_id)

    validate_error(response, ApiErrorId.ERR_CRITICAL_REC_OVERDUE.value, 422)
    assert read_policy(scenario.policy_id)["uw_status"] == "RATED"
    assert {row["status"] for row in read_reservations(scenario.policy_id)} == {"RESERVED"}
    assert read_pool(scenario.hail_pool["id"])["committed_cents"] == 0


def test_the_two_workers_compensation_gates_fire_in_their_own_order(api):
    """"A labor profile must exist whose `coordination_status` is `NOT_REQUIRED`
    or `VERIFIED` — a `PENDING_PROOF` or `LAPSED` profile draws
    `ERR_WC_COORDINATION_UNVERIFIED`, and a policy that never had a profile
    submitted at all draws `ERR_WC_PROOF_MISSING`." The bind is therefore refused
    twice for different reasons before it is allowed once, and "on success
    `verified_at` takes the current clock instant, `verified_by_user_id` takes the
    acting officer's `X-User-ID`, and the profile's `version` climbs by 1." None
    of the refusals lifts the policy's version, so the quote the underwriter was
    holding stays current throughout.

    Design: Corner/validations/corner_bind_requires_labor_profile_then_verified_coordination
    """
    scenario = setup_rated_dwelling_policy(with_labor_profile=False)
    rated_version = read_policy(scenario.policy_id)["version"]

    validate_error(
        bind_policy(scenario.policy_id), ApiErrorId.ERR_WC_PROOF_MISSING.value, 422
    )
    assert read_policy(scenario.policy_id)["version"] == rated_version

    profile = upsert_labor_profile(
        scenario.agent_headers,
        scenario.policy_id,
        full_time_count=4,
        seasonal_count=4,
        migrant_h2a_count=0,
        wc_carrier_name="Prairie Mutual WC",
        wc_policy_number="WC-2026-0007",
        wc_expiry_date="2027-08-31",
    )
    assert float(profile["labor_exposure_units"]) == 6.00
    assert profile["wc_required"] is True
    assert profile["coordination_status"] == "PENDING_PROOF"
    unpriced = read_policy(scenario.policy_id)
    assert unpriced["uw_status"] == "RATED"
    assert unpriced["total_premium_cents"] == 269_200
    assert unpriced["version"] == rated_version

    validate_error(
        bind_policy(scenario.policy_id), ApiErrorId.ERR_WC_COORDINATION_UNVERIFIED.value, 422
    )
    assert read_policy(scenario.policy_id)["version"] == rated_version

    verified = validate_success(
        verify_wc(profile["id"], note="certificate matches the carrier of record")
    )
    assert verified["coordination_status"] == "VERIFIED"
    assert verified["verified_at"].startswith("2026-08-15T00:00:00")

    bound = bind_policy_ok(scenario.policy_id)

    assert bound["uw_status"] == "BOUND"
    assert bound["version"] == rated_version + 1
    assert {row["status"] for row in read_reservations(scenario.policy_id)} == {"COMMITTED"}
    assert read_labor_profile(profile["id"])["coordination_status"] == "VERIFIED"


def test_the_ladder_reports_the_role_then_the_schema_then_the_body_reference(api):
    """"Role permission — `ERR_FORBIDDEN_ROLE` (403). Evaluated before any body
    parsing, so a role violation outranks a malformed payload." "Schema —
    `ERR_INVALID_REQUEST` (400) for a missing or null required field, a wrong JSON
    type, an enumerated value outside its declared set, a numeric value outside
    its declared range, a blank or over-long string, bad pagination, or any
    unknown body field." "Body-referenced existence —
    `ERR_FARM_ACCOUNT_NOT_FOUND`, `ERR_FARM_POLICY_NOT_FOUND` or
    `ERR_INSPECTOR_NOT_FOUND` (404), in declared field order." A producer editing
    an unknown producer never learns the id was unknown; a policy submitted
    without its deductible reports the schema fault rather than the unknown
    account; and a booking that names two unknown rows reports the policy, which
    "the booking names `policy_id` and `inspector_id`, an `inspection_type` of
    `INITIAL`, `RE_INSPECTION` or `LOSS_TRIGGERED`, a `scheduled_for` instant in
    ISO 8601 UTC, and a `duration_minutes` between 30 and 480 inclusive" declares
    first.

    Design: Corner/validations/corner_role_check_outranks_schema_and_existence_checks
    """
    scenario = bootstrap_zone(with_policy=False)

    forbidden = api.update_agent(
        NON_EXISTENT_UUID, {"appointment_status": "SUSPENDED"}, scenario.agent_headers
    )
    validate_error(forbidden, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)

    schema_first = api.create_farm_policy(
        {
            "account_id": NON_EXISTENT_UUID,
            "term_start_date": "2026-09-01",
            "term_end_date": "2027-08-31",
        },
        scenario.agent_headers,
    )
    validate_error(schema_first, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

    unknown_policy = schedule_inspection(NON_EXISTENT_UUID, UNKNOWN_INSPECTOR_ID)
    validate_error(unknown_policy, ApiErrorId.ERR_FARM_POLICY_NOT_FOUND.value, 404)

    untouched = validate_success(api.get_agent(scenario.agent_id, ADMIN))
    assert untouched["appointment_status"] == "ACTIVE"
    assert untouched["version"] == 1
    _, policy_meta = validate_paginated(api.list_farm_policies(UW))
    assert policy_meta["total_count"] == 0
    _, inspection_meta = validate_paginated(api.list_inspections(UW))
    assert inspection_meta["total_count"] == 0
    _, account_meta = validate_paginated(api.list_farm_accounts(UW))
    assert account_meta["total_count"] == 1


def test_the_conditional_fields_stay_absent_where_they_do_not_belong(api):
    """"Conditional-field coupling — `ERR_BLANKET_LIMIT_REQUIRED`,
    `ERR_PEAK_SEASON_FIELDS_REQUIRED` and `ERR_VISITOR_COUNT_REQUIRED` (all
    422)." Each rule bites only on the shape it names, so the mirror image is
    simply accepted: a dwelling with no season, a per-head herd with no blanket
    limit — "On the `PER_HEAD` election it is the smaller of two figures:
    `head_count` multiplied by `per_head_value_cents`, and the per-head aggregate
    cap of 30000000 cents." — and a general-farm exposure with no visitor count.
    None of the three writes prices the policy: "A profile submission never
    changes `uw_status` and never touches any premium figure."

    Design: Corner/validations/corner_conditional_fields_absent_when_not_applicable
    """
    scenario = bootstrap_zone()
    headers = scenario.agent_headers

    item = validate_success(
        api.create_scheduled_item(scenario.policy_id, create_scheduled_item_payload(), headers), 201
    )
    group = validate_success(
        api.create_livestock_group(
            scenario.policy_id,
            create_livestock_group_payload(limit_basis="PER_HEAD", peril_scope="FULL_PERIL"),
            headers,
        ),
        201,
    )
    exposure = validate_success(
        api.create_liability_exposure(
            scenario.policy_id,
            create_liability_exposure_payload(exposure_type="GENERAL_FARM"),
            headers,
        ),
        201,
    )

    assert item["insured_value_cents"] == 40_000_000
    assert group["covered_limit_cents"] == 25_500_000
    assert exposure["exposure_premium_cents"] == 133_000

    assert_all_null(
        item,
        ["peak_season_value_cents", "peak_season_start_month", "peak_season_end_month"],
        "a dwelling",
    )
    assert_all_null(group, ["blanket_limit_cents"], "a per-head herd")
    assert_all_null(exposure, ["annual_visitor_count"], "a general-farm exposure")

    policy = read_policy(scenario.policy_id)
    assert policy["uw_status"] == "DRAFT"
    assert policy["property_premium_cents"] == 0
    assert policy["livestock_premium_cents"] == 0
    assert policy["liability_premium_cents"] == 0
    assert policy["exposed_tiv_cents"] == 0
    assert policy["total_premium_cents"] == 0


def test_the_envelope_and_the_stamped_agent_are_policed_by_the_schema_rung(api):
    """"A `limit` outside 1 through 100, or a negative `offset`, is rejected with
    `ERR_INVALID_REQUEST` (HTTP 400)." "The account's `agent_id` is stamped by the
    server from the caller's `X-User-ID`; a client that tries to supply `agent_id`
    in the body has supplied an unknown field and is rejected with
    `ERR_INVALID_REQUEST`." A page one past the ceiling, an offset one below the
    floor and a spoofed owner are all turned away at the same rung, and the
    default page still reports the documented "`limit` defaults to 10, may be no
    smaller than 1 and no larger than 100."

    Design: Corner/validations/corner_pagination_and_unknown_field_rejected
    """
    scenario = bootstrap_zone()

    validate_error(
        api.list_farm_policies(UW, params={"limit": 101}), ApiErrorId.ERR_INVALID_REQUEST.value, 400
    )
    validate_error(
        api.list_farm_policies(UW, params={"offset": -1}), ApiErrorId.ERR_INVALID_REQUEST.value, 400
    )
    spoofed = api.create_farm_account(
        create_farm_account_payload(
            legal_name="Spoofed Owner Farms", acreage=640, agent_id=NON_EXISTENT_UUID
        ),
        scenario.agent_headers,
    )
    validate_error(spoofed, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

    _, account_meta = validate_paginated(api.list_farm_accounts(UW))
    assert account_meta["total_count"] == 1
    assert account_meta["limit"] == 10
    assert account_meta["offset"] == 0
    assert account_meta["has_more"] is False

    policies, policy_meta = validate_paginated(api.list_farm_policies(UW))
    assert [row["id"] for row in policies] == [scenario.policy_id]
    assert policy_meta["limit"] == 10
    assert policy_meta["offset"] == 0
