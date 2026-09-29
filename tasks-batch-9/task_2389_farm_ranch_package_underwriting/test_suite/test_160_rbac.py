"""Who may act. Reference data belongs to the administrator, the lifecycle steps
belong to the desks that own them, the shared steps are genuinely shared, a
producer sees only its own book, the referring senior may not decide its own
referral, and a blank caller identity ends the conversation first."""

from test_helpers import (
    ApiErrorId,
    ADMIN,
    COMPLIANCE,
    NON_EXISTENT_UUID,
    SENIOR,
    SENIOR_ALT,
    SENIOR_UNDERWRITER_USER_ID,
    UW,
    add_liability_exposure,
    add_scheduled_item,
    blank_user_id_headers,
    bootstrap_zone,
    create_farm_policy_payload,
    create_inspector_payload,
    create_scheduled_item_payload,
    decide_referral,
    make_agent_headers,
    make_loss_control_headers,
    open_account,
    open_policy,
    open_pool,
    patch_agent_ok,
    patch_inspector_ok,
    patch_pool,
    rate_policy,
    rate_policy_ok,
    read_labor_profile,
    read_policy,
    register_agent,
    register_inspector,
    reservation_by_peril,
    run_sweep,
    schedule_inspection,
    schedule_inspection_ok,
    set_clock,
    setup_draft_policy_with_dwelling,
    upsert_labor_profile,
    validate_error,
    validate_paginated,
    validate_success,
    verify_wc,
)


def test_reference_data_is_written_by_the_administrator_and_by_nobody_else(api):
    """"A `PlatformAdmin` owns reference data — producers, inspectors and
    catastrophe capacity pools — and is barred from the entire policy lifecycle: it
    may not create accounts or policies, rate, decide referrals, bind, decline,
    cancel, request or decide endorsements, complete inspections, submit evidence,
    review recommendations or verify workers-compensation proof." The three creates
    and the three amendments all land for the administrator, while an underwriter
    opening a pool and a producer registering an inspector are both turned away:
    "a request whose `X-User-Role` is not among the roles authorised for the route
    it addresses is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)." A pool opens
    empty — "all three start at zero on a new pool — so `available_cents` starts
    equal to `total_capacity_cents` — and all three are recomputed, with the pool's
    `version` incremented by 1, every single time a reservation on that pool
    changes status."

    Design: Corner/rbac/corner_platform_admin_owns_all_reference_data_writes
    """
    set_clock()
    agent = register_agent(agency_name="Reference Data Agency")
    inspector = register_inspector(full_name="Reed Alba")
    pool = open_pool("ZN-9", "HAIL")

    assert pool["reserved_cents"] == 0
    assert pool["committed_cents"] == 0
    assert pool["available_cents"] == 200_000_000
    assert pool["version"] == 1

    assert patch_agent_ok(agent["id"], appointment_status="SUSPENDED")[
        "appointment_status"
    ] == "SUSPENDED"
    assert patch_inspector_ok(inspector["id"], daily_capacity_minutes=240)[
        "daily_capacity_minutes"
    ] == 240
    frozen = validate_success(patch_pool(pool["id"], status="FROZEN"))
    assert frozen["status"] == "FROZEN"
    assert frozen["version"] == 2

    underwriter_pool = api.create_cat_capacity_pool(
        {
            "zone_code": "ZN-9",
            "peril": "WIND",
            "participation_pct": 0.30,
            "total_capacity_cents": 200_000_000,
        },
        UW,
    )
    validate_error(underwriter_pool, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)

    producer_inspector = api.create_inspector(
        create_inspector_payload(full_name="Rogue Inspector", region_code="KS-WEST"),
        make_agent_headers(agent["id"]),
    )
    validate_error(producer_inspector, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)

    pools, meta = validate_paginated(
        api.list_cat_capacity_pools(ADMIN, params={"zone_code": "ZN-9"})
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in pools] == [pool["id"]]


def test_six_lifecycle_routes_refuse_the_neighbouring_desk(api):
    """"Binding and cancelling are reserved to the line `Underwriter` and are
    closed even to a `SeniorUnderwriter`." "Reviewing loss-control evidence and
    verifying workers-compensation coordination belong exclusively to the
    `ComplianceOfficer`, who in turn may not rate, bind, decline, cancel, decide
    referrals, decide or rescind endorsements, or complete inspections." "A
    `LossControlSpecialist` completes inspections but neither schedules nor
    re-schedules them, and never reviews the recommendations it raised." Each probe
    is a role refusal and never a state refusal, because the role rung is
    "evaluated before any body parsing, so a role violation outranks a malformed
    payload" — the referral decision on a `DRAFT` policy never reports
    `ERR_POLICY_NOT_REFERRED`, and the verification of a `NOT_REQUIRED` profile
    never reports `ERR_WC_STATE_INVALID`.

    Design: Corner/rbac/corner_lifecycle_writes_are_forbidden_to_the_wrong_roles
    """
    scenario = setup_draft_policy_with_dwelling()
    profile = upsert_labor_profile(scenario.agent_headers, scenario.policy_id)
    assert profile["coordination_status"] == "NOT_REQUIRED"
    inspector = register_inspector()
    inspection = schedule_inspection_ok(scenario.policy_id, inspector["id"])

    validate_error(
        rate_policy(scenario.policy_id, headers=scenario.agent_headers),
        ApiErrorId.ERR_FORBIDDEN_ROLE.value,
        403,
    )
    validate_error(
        decide_referral(scenario.policy_id, "APPROVE", headers=UW),
        ApiErrorId.ERR_FORBIDDEN_ROLE.value,
        403,
    )
    validate_error(
        api.complete_inspection(
            inspection["id"],
            {"findings_summary": "underwriter tries to close its own survey", "findings": []},
            UW,
        ),
        ApiErrorId.ERR_FORBIDDEN_ROLE.value,
        403,
    )
    validate_error(
        schedule_inspection(
            scenario.policy_id,
            inspector["id"],
            scheduled_for="2026-08-20T09:00:00Z",
            duration_minutes=60,
            headers=scenario.agent_headers,
        ),
        ApiErrorId.ERR_FORBIDDEN_ROLE.value,
        403,
    )
    validate_error(
        run_sweep(headers=scenario.agent_headers), ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403
    )
    validate_error(
        verify_wc(
            profile["id"],
            note="loss control tries to verify a certificate",
            headers=make_loss_control_headers(inspector["id"]),
        ),
        ApiErrorId.ERR_FORBIDDEN_ROLE.value,
        403,
    )

    untouched_inspection = validate_success(api.get_inspection(inspection["id"], UW))
    assert untouched_inspection["status"] == "SCHEDULED"
    assert untouched_inspection["hazard_score"] == 0
    assert untouched_inspection["recommendation_count"] == 0
    assert untouched_inspection["completed_at"] is None
    assert untouched_inspection["version"] == 1

    policy = read_policy(scenario.policy_id)
    assert policy["uw_status"] == "DRAFT"
    assert policy["version"] == 1
    assert policy["total_premium_cents"] == 0
    assert policy["exposed_tiv_cents"] == 0
    assert read_labor_profile(profile["id"])["coordination_status"] == "NOT_REQUIRED"


def test_the_shared_steps_take_either_of_their_two_desks(api):
    """§4 opens the rating route to an `Underwriter` and a `SeniorUnderwriter`
    alike and the booking route to an `Underwriter` and a `ComplianceOfficer`, and
    both pairs are exercised here on sibling policies of one producer. The second
    rating still sits in the base scarcity band: "`scarcity_factor` is selected from
    that ratio in four bands: at most 0.50 gives 1.00, above 0.50 and at most 0.75
    gives 1.15, above 0.75 and at most 0.90 gives 1.35, above 0.90 and at most 1.00
    gives 1.60; a ratio strictly greater than 1.00 aborts the entire rating call
    with `ERR_CAT_CAPACITY_EXCEEDED` and leaves no reservation behind for any
    peril." The two bookings clear one another's travel buffer and the day's
    capacity, and every desk may look: "read routes are open to all six roles, with
    the producer's reads confined to its own accounts."

    Design: Corner/rbac/corner_shared_operations_accept_either_authorized_role
    """
    scenario = bootstrap_zone(
        with_policy=False, account_overrides={"legal_name": "Shared Ops Farms A"}
    )
    headers = scenario.agent_headers
    inspector = register_inspector()
    policy_a = open_policy(headers, scenario.account["id"])
    add_scheduled_item(headers, policy_a["id"])
    account_b = open_account(headers, legal_name="Shared Ops Farms B")
    policy_b = open_policy(headers, account_b["id"])
    add_scheduled_item(headers, policy_b["id"])

    rated_a = rate_policy_ok(policy_a["id"], headers=UW)
    rated_b = rate_policy_ok(policy_b["id"], headers=SENIOR)

    assert rated_a["uw_status"] == "RATED"
    assert rated_a["total_premium_cents"] == 269_200
    assert rated_b["uw_status"] == "RATED"
    assert rated_b["total_premium_cents"] == 269_200
    hail_b = reservation_by_peril(policy_b["id"])["HAIL"]
    assert float(hail_b["utilization_at_rating"]) == 0.200000
    assert float(hail_b["scarcity_factor"]) == 1.00

    booking_a = schedule_inspection_ok(
        policy_a["id"], inspector["id"], scheduled_for="2026-08-16T09:00:00Z"
    )
    booking_b = validate_success(
        schedule_inspection(
            policy_b["id"],
            inspector["id"],
            scheduled_for="2026-08-16T13:00:00Z",
            headers=COMPLIANCE,
        ),
        201,
    )
    assert booking_a["status"] == "SCHEDULED"
    assert booking_b["status"] == "SCHEDULED"
    assert booking_b["inspector_id"] == inspector["id"]

    by_specialist = validate_success(
        api.get_farm_policy(policy_a["id"], make_loss_control_headers(inspector["id"]))
    )
    by_admin = validate_success(api.get_farm_policy(policy_a["id"], ADMIN))
    assert by_specialist["uw_status"] == "RATED"
    assert by_admin["uw_status"] == "RATED"
    assert by_specialist["total_premium_cents"] == 269_200


def test_a_producer_cannot_read_or_write_another_producers_rows(api):
    """"A producer that touches a row reachable from someone else's account is
    rejected with `ERR_NOT_ACCOUNT_AGENT` (HTTP 403)." "A caller acting as `Agent`
    may read or write only rows reachable from an account whose producer is that
    caller; anything else is `ERR_NOT_ACCOUNT_AGENT`." The rows plainly exist —
    "producer scoping is applied after path resolution and before any state check"
    — so the answer is 403 and not 404, and the rung is the producer's alone:
    "read routes are open to all six roles, with the producer's reads confined to
    its own accounts."

    Design: Corner/rbac/corner_agent_cannot_reach_another_producers_book
    """
    first = bootstrap_zone(with_policy=False)
    second_agent = register_agent(agency_name="Second Producer LLC")
    second_headers = make_agent_headers(second_agent["id"])
    foreign_account = open_account(
        second_headers,
        legal_name="Foreign Book Farms",
        county_name="Rice",
        acreage=900,
        operation_type="CROP",
    )
    foreign_policy = open_policy(second_headers, foreign_account["id"])
    own_account = first.account

    validate_error(
        api.get_farm_account(foreign_account["id"], first.agent_headers),
        ApiErrorId.ERR_NOT_ACCOUNT_AGENT.value,
        403,
    )
    validate_error(
        api.create_scheduled_item(
            foreign_policy["id"],
            create_scheduled_item_payload(description="Injected dwelling"),
            first.agent_headers,
        ),
        ApiErrorId.ERR_NOT_ACCOUNT_AGENT.value,
        403,
    )
    validate_error(
        api.create_farm_policy(
            create_farm_policy_payload(
                foreign_account["id"],
                term_start_date="2027-09-01",
                term_end_date="2028-08-31",
            ),
            first.agent_headers,
        ),
        ApiErrorId.ERR_NOT_ACCOUNT_AGENT.value,
        403,
    )

    _, no_items = validate_paginated(api.list_scheduled_items(foreign_policy["id"], UW))
    assert no_items["total_count"] == 0
    _, foreign_policies = validate_paginated(
        api.list_farm_policies(UW, params={"account_id": foreign_account["id"]})
    )
    assert foreign_policies["total_count"] == 1

    seen_by_underwriter = validate_success(api.get_farm_policy(foreign_policy["id"], UW))
    assert seen_by_underwriter["uw_status"] == "DRAFT"

    own, own_meta = validate_paginated(
        api.list_farm_accounts(first.agent_headers, params={"agent_id": first.agent_id})
    )
    assert own_meta["total_count"] == 1
    assert [row["id"] for row in own] == [own_account["id"]]


def test_the_senior_who_referred_the_quote_may_not_decide_it(api):
    """"A `SeniorUnderwriter` whose rating produced a referral may not decide that
    same referral; the attempt is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP
    403)." The referral itself comes from the visitor trigger — "the largest
    `annual_visitor_count` among the policy's `AGRITOURISM` exposures strictly
    greater than 2000 yields `AGRITOURISM_VISITORS`" — and money is fully computed
    on that branch: "if at least one trigger matches, the policy advances `DRAFT →
    REFERRED` instead, and every premium, reservation, pool and ledger effect above
    fires identically — the divergence is narrow and precise: on the `REFERRED`
    branch `quote_expires_at` stays null, while `referred_at` takes the current
    clock instant, `referred_by_user_id` takes the rating actor's `X-User-ID` and
    `referral_reason_code` takes the first matching trigger." A second senior then
    approves, and "it re-derives `quote_expires_at` as 30 days after the original
    `rating_valuation_date`, not 30 days after the decision, and clears
    `referred_at`, `referred_by_user_id` and `referral_reason_code`."

    Design: Corner/rbac/corner_segregation_of_duties_on_the_referral_decision
    """
    scenario = setup_draft_policy_with_dwelling()
    add_liability_exposure(
        scenario.agent_headers,
        scenario.policy_id,
        "AGRITOURISM",
        annual_receipts_cents=4_000_000,
        annual_visitor_count=2_500,
    )

    referred = rate_policy_ok(scenario.policy_id, headers=SENIOR)

    assert referred["uw_status"] == "REFERRED"
    assert referred["referral_reason_code"] == "AGRITOURISM_VISITORS"
    assert referred["referred_by_user_id"] == SENIOR_UNDERWRITER_USER_ID
    assert referred["referred_at"].startswith("2026-08-15T00:00:00")
    assert referred["quote_expires_at"] is None
    assert referred["property_premium_cents"] == 144_000
    assert referred["liability_premium_cents"] == 316_000
    assert referred["cat_load_cents"] == 125_200
    assert referred["total_premium_cents"] == 585_200
    assert {row["status"] for row in reservation_by_peril(scenario.policy_id).values()} == {
        "RESERVED"
    }

    self_decision = decide_referral(
        scenario.policy_id, "APPROVE", "self-approval attempt", headers=SENIOR
    )

    validate_error(self_decision, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)
    held = read_policy(scenario.policy_id)
    assert held["uw_status"] == "REFERRED"
    assert held["version"] == referred["version"]
    assert held["total_premium_cents"] == 585_200

    approved = validate_success(
        decide_referral(
            scenario.policy_id,
            "APPROVE",
            "agritourism exposure reviewed and accepted",
            headers=SENIOR_ALT,
        )
    )

    assert approved["uw_status"] == "RATED"
    assert approved["quote_expires_at"].startswith("2026-09-14T00:00:00")
    assert approved["referred_at"] is None
    assert approved["referred_by_user_id"] is None
    assert approved["referral_reason_code"] is None
    assert approved["total_premium_cents"] == 585_200
    assert {row["status"] for row in reservation_by_peril(scenario.policy_id).values()} == {
        "RESERVED"
    }


def test_a_blank_caller_identity_ends_the_request_before_any_other_rung(api):
    """"A request that omits `X-User-ID`, or supplies it blank, is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)." The three requests below would otherwise
    have drawn a schema refusal on three separate field violations and a
    body-reference 404 apiece, but none of that is reached, because the ladder
    starts at authentication. Only one route is exempt: "every request other than
    the logical-clock-setting capability described in §4 must carry two headers:
    `X-User-ID`, identifying the caller, and `X-User-Role`, naming the capacity in
    which the caller is acting."

    Design: Corner/rbac/corner_unauthenticated_requests_rejected_before_every_other_check
    """
    scenario = bootstrap_zone(perils=())
    assert scenario.pools == {}

    blank_read = api.get_farm_policy(scenario.policy_id, blank_user_id_headers("Agent"))
    validate_error(blank_read, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)

    blank_pool = api.create_cat_capacity_pool(
        {
            "zone_code": "ZN-1",
            "peril": "NOT_A_PERIL",
            "participation_pct": 9.0,
            "total_capacity_cents": -5,
        },
        blank_user_id_headers("PlatformAdmin"),
    )
    validate_error(blank_pool, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)

    blank_rate = api.rate_farm_policy(
        NON_EXISTENT_UUID, {"expected_policy_version": 1}, blank_user_id_headers("Underwriter")
    )
    validate_error(blank_rate, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)

    _, pool_rows = validate_paginated(api.list_cat_capacity_pools(ADMIN))
    assert pool_rows["total_count"] == 0
    policy = read_policy(scenario.policy_id)
    assert policy["uw_status"] == "DRAFT"
    assert policy["version"] == 1

    exempt = validate_success(
        api.set_clock({"current_utc": "2026-08-20T00:00:00Z"}, blank_user_id_headers("PlatformAdmin"))
    )
    assert exempt is not None
