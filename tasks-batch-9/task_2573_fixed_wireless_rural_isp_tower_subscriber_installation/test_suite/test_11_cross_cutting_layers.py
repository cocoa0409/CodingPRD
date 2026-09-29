"""Cross-cutting behaviour of the Fixed-Wireless Rural ISP API.

Each test drives one narrative that crosses several PRD chapters at once: the
stale-view guards of PRD 2.8 layered on top of the sector ledger of PRD 3.3, the
account-creation fan-out of PRD 3.6 unwound by a late referential rejection, the
credit arithmetic of PRD 3.9 re-selected by a plan change, and the metered-cycle
counters of PRD 3.8 across three consecutive closes.

The server restarts with an empty database and its logical clock at
2026-08-01T00:00:00Z before every test, so each test builds all of its own state.
"""

from test_helpers import (
    ApiErrorId,
    BILLING_ADMIN,
    SALES_AGENT,
    SURVEY_PRESETS,
    api_client,
    apply_credit,
    assert_no_mutation,
    assert_version_advanced_by,
    change_subscriber_plan,
    close_cycle,
    close_outage,
    complete_work_order,
    create_outage,
    create_serviceability_request,
    create_service_plan,
    create_subscriber_payload,
    get_assignment_for_subscriber,
    get_capacity_hold,
    get_credit,
    get_sector,
    get_serviceability_request,
    get_subscriber,
    ingest_usage,
    iso_shift,
    list_equipment_assignments,
    prepare_credit,
    set_clock,
    setup_active_plant,
    setup_held_reservation,
    setup_pending_install_subscriber,
    setup_scheduled_work_order,
    survey_work_order,
    validate_error,
    validate_paginated,
    validate_success,
)


def _instant(value):
    """The instant of a timestamp, without pinning a fractional-second form."""
    return value.replace("Z", "").split(".")[0]


def _setup_installed_account(installed_at="2026-08-02T00:00:00Z", plan_overrides=None):
    """An ACTIVE account whose first billing cycle opens on the given calendar date.

    PRD 3.7 sets `cycle_start_date` from the logical clock at install completion, so
    the clock is moved onto the wanted date before the completion is posted.
    """
    scenario = setup_scheduled_work_order(plan_overrides=plan_overrides or {})
    survey_work_order(scenario["work_order"]["id"], **SURVEY_PRESETS["NON_PEN_ROOF_TRIPOD"])
    set_clock(installed_at)
    scenario["work_order"] = complete_work_order(
        scenario["work_order"]["id"], installed_mast_height_m=2.5
    )
    scenario["subscriber"] = get_subscriber(scenario["subscriber"]["id"])
    scenario["assignment"] = get_assignment_for_subscriber(scenario["subscriber"]["id"])
    return scenario


def _closed_outage(tower_id, started_at, minutes, cause="POWER"):
    outage = create_outage(tower_id, cause=cause, started_at=started_at)
    return close_outage(outage["id"], ended_at=iso_shift(started_at, minutes=minutes))


def test_a_reservation_needs_the_current_sector_version_and_every_write_advances_it():
    """PRD 2.8: "**Reserving sector bandwidth** requires `expected_sector_version` in the
    request body." "Its value must equal the current `version` of the sector the reservation
    lands on." "The write is therefore rejected with `ERR_STALE_SECTOR_VERSION` (HTTP 412)
    whenever `expected_sector_version` does not equal the sector's current `version`."

    PRD 3.4: "Its side effects on the sector are immediate: `held_mbps` rises by the reserved
    amount, `committed_mbps`, `oversubscription_ratio`, `remaining_allowance_mbps` and
    `capacity_posture` are all recomputed, and the sector's `version` is incremented — which
    invalidates any other caller's `expected_sector_version` and forces them to re-read."

    PRD 2.7: "A stale-view rejection therefore surfaces even when the sector is also out of
    allowance, and a segregation-of-duties breach surfaces even when the work order has also
    exhausted its resurveys."

    PRD 3.3: "Otherwise a provisional posture is read off the air ratio: `HOLD` when
    `oversubscription_ratio` is at or above three-quarters of `max_oversubscription_ratio`,
    `WATCH` when it is at or above half of `max_oversubscription_ratio`, and `OPEN` otherwise."

    Design: Corner/cross_cutting_complexity_layers/sector_version_must_be_current_on_every_reservation_and_advances_on_each_write
    """
    plant = setup_active_plant()
    sector_id = plant["sector"]["id"]
    request_a = create_serviceability_request(plant["tower"]["id"], plant["plan"]["id"])
    request_b = create_serviceability_request(
        plant["tower"]["id"],
        plant["plan"]["id"],
        contact_name="Wes Ortiz",
        premise_latitude=41.262,
        premise_longitude=-104.758,
    )
    assert request_a["status"] == "QUALIFIED"
    assert request_b["status"] == "QUALIFIED"
    assert request_a["qualified_sector_id"] == sector_id
    assert request_b["qualified_sector_id"] == sector_id

    opening = get_sector(sector_id)
    assert opening["committed_mbps"] == 0
    assert opening["remaining_allowance_mbps"] == 200
    stale_version = opening["version"]

    first = validate_success(
        api_client.create_capacity_hold(
            {
                "serviceability_request_id": request_a["id"],
                "expected_sector_version": stale_version,
            },
            SALES_AGENT,
        ),
        201,
    )
    assert first["status"] == "HELD"
    assert first["held_mbps"] == 50

    mid = get_sector(sector_id)
    assert_version_advanced_by(opening, mid, 1, entity="sector")
    assert mid["held_mbps"] == 50
    assert mid["sold_mbps"] == 0
    assert mid["committed_mbps"] == 50
    assert mid["oversubscription_ratio"] == 2.0
    assert mid["remaining_allowance_mbps"] == 150
    assert mid["capacity_posture"] == "OPEN"

    refused = api_client.create_capacity_hold(
        {
            "serviceability_request_id": request_b["id"],
            "expected_sector_version": stale_version,
        },
        SALES_AGENT,
    )
    validate_error(refused, ApiErrorId.ERR_STALE_SECTOR_VERSION.value, 412)

    after_refusal = get_sector(sector_id)
    assert_no_mutation(mid, after_refusal, entity="sector")
    assert after_refusal["held_mbps"] == 50
    assert after_refusal["committed_mbps"] == 50
    assert after_refusal["remaining_allowance_mbps"] == 150
    assert after_refusal["capacity_posture"] == "OPEN"
    _, refused_meta = validate_paginated(
        api_client.list_capacity_holds(SALES_AGENT, params={"status": "HELD"})
    )
    assert refused_meta["total_count"] == 1
    assert get_serviceability_request(request_b["id"])["status"] == "QUALIFIED"

    retried = validate_success(
        api_client.create_capacity_hold(
            {
                "serviceability_request_id": request_b["id"],
                "expected_sector_version": after_refusal["version"],
            },
            SALES_AGENT,
        ),
        201,
    )
    assert retried["status"] == "HELD"
    assert retried["held_mbps"] == 50

    end = get_sector(sector_id)
    assert_version_advanced_by(after_refusal, end, 1, entity="sector")
    assert end["held_mbps"] == 100
    assert end["committed_mbps"] == 100
    assert end["oversubscription_ratio"] == 4.0
    assert end["remaining_allowance_mbps"] == 100
    assert end["capacity_posture"] == "WATCH"

    rows, meta = validate_paginated(
        api_client.list_capacity_holds(SALES_AGENT, params={"status": "HELD"})
    )
    assert meta["total_count"] == 2
    assert {row["id"] for row in rows} == {first["id"], retried["id"]}


def test_a_plan_change_needs_a_current_account_version_and_bumps_both_rows():
    """PRD 2.8: "**Changing an account's plan** requires `expected_subscriber_version` in the
    request body, likewise non-optional and likewise refused with `ERR_VALIDATION` when
    absent." "Its value must equal the current `version` of the account being changed." "A
    mismatch is rejected with `ERR_STALE_SUBSCRIBER_VERSION` (HTTP 412)."

    PRD 3.6: "On success, the sector's `sold_mbps` moves by the difference between the two
    plans' `downstream_mbps`, its ledger and `capacity_posture` are recomputed, and the
    account's `cycle_usage_gb` position is re-evaluated against the new plan's `soft_cap_gb`
    and `deprioritization_factor` so that `usage_priority` and `effective_downstream_mbps`
    reflect the plan the account is actually on." "Both the account's and the sector's
    `version` are incremented." "A downgrade never fails that test and hands allowance back."

    PRD 2.7: "The practical reading of this ladder is that identity beats existence, existence
    beats state, state beats concurrency, concurrency beats physics, physics beats process, and
    process beats capacity."

    Design: Corner/cross_cutting_complexity_layers/plan_change_requires_a_current_account_version_and_bumps_both_rows
    """
    scenario = setup_pending_install_subscriber()
    subscriber_id = scenario["subscriber"]["id"]
    sector_id = scenario["sector"]["id"]
    standard_plan_id = scenario["plan"]["id"]
    gig_plan = create_service_plan(
        tier_code="GIG150",
        downstream_mbps=150,
        upstream_mbps=25,
        monthly_price_cents=12999,
        soft_cap_gb=1500.0,
        equipment_policy="RENTAL_OR_PURCHASE",
    )

    opening_account = get_subscriber(subscriber_id)
    opening_sector = get_sector(sector_id)
    assert opening_account["service_status"] == "PENDING_INSTALL"
    assert opening_sector["sold_mbps"] == 50
    assert opening_sector["remaining_allowance_mbps"] == 150
    stale_version = opening_account["version"]

    upgraded = validate_success(
        api_client.change_subscriber_plan(
            subscriber_id,
            {
                "service_plan_id": gig_plan["id"],
                "expected_subscriber_version": stale_version,
            },
            SALES_AGENT,
        ),
        200,
    )
    assert upgraded["service_plan_id"] == gig_plan["id"]
    assert upgraded["sector_id"] == sector_id
    assert upgraded["effective_downstream_mbps"] == 150.0
    assert_version_advanced_by(opening_account, upgraded, 1, entity="account")

    sector_after_upgrade = get_sector(sector_id)
    assert_version_advanced_by(opening_sector, sector_after_upgrade, 1, entity="sector")
    assert sector_after_upgrade["sold_mbps"] == 150
    assert sector_after_upgrade["held_mbps"] == 0
    assert sector_after_upgrade["committed_mbps"] == 150
    assert sector_after_upgrade["oversubscription_ratio"] == 6.0
    assert sector_after_upgrade["remaining_allowance_mbps"] == 50
    assert sector_after_upgrade["capacity_posture"] == "HOLD"

    refused = api_client.change_subscriber_plan(
        subscriber_id,
        {
            "service_plan_id": standard_plan_id,
            "expected_subscriber_version": stale_version,
        },
        BILLING_ADMIN,
    )
    validate_error(refused, ApiErrorId.ERR_STALE_SUBSCRIBER_VERSION.value, 412)

    account_after_refusal = get_subscriber(subscriber_id)
    assert_no_mutation(upgraded, account_after_refusal, entity="account")
    assert account_after_refusal["service_plan_id"] == gig_plan["id"]
    sector_after_refusal = get_sector(sector_id)
    assert_no_mutation(sector_after_upgrade, sector_after_refusal, entity="sector")
    assert sector_after_refusal["sold_mbps"] == 150
    assert sector_after_refusal["oversubscription_ratio"] == 6.0
    assert sector_after_refusal["capacity_posture"] == "HOLD"

    downgraded = validate_success(
        api_client.change_subscriber_plan(
            subscriber_id,
            {
                "service_plan_id": standard_plan_id,
                "expected_subscriber_version": account_after_refusal["version"],
            },
            BILLING_ADMIN,
        ),
        200,
    )
    assert downgraded["service_plan_id"] == standard_plan_id
    assert downgraded["effective_downstream_mbps"] == 50.0
    assert_version_advanced_by(account_after_refusal, downgraded, 1, entity="account")

    final_sector = get_sector(sector_id)
    assert final_sector["sold_mbps"] == 50
    assert final_sector["committed_mbps"] == 50
    assert final_sector["oversubscription_ratio"] == 2.0
    assert final_sector["remaining_allowance_mbps"] == 150
    assert final_sector["capacity_posture"] == "OPEN"


def test_a_late_plan_mismatch_leaves_the_whole_account_creation_fan_out_unwritten():
    """PRD 2.7 rung 13: "**Referential compatibility** — coordination is between sectors on
    different towers (`ERR_SAME_TOWER_COORDINATION`, 422), the plan permits the chosen
    equipment acquisition mode and matches the qualified plan (`ERR_PLAN_MISMATCH`, 422), the
    credited account is served from the tower that went down (`ERR_SUBSCRIBER_NOT_AFFECTED`,
    422), and the account has no install work order already open
    (`ERR_WORK_ORDER_ALREADY_OPEN`, 409)."

    PRD 3.6: "`ERR_PLAN_MISMATCH` is also raised here when the chosen `equipment_mode` is not
    permitted by the plan's `equipment_policy`: `RENTAL` is refused against a `PURCHASE_ONLY`
    plan, `PURCHASE` is refused against a `RENTAL_ONLY` plan, and a `RENTAL_OR_PURCHASE` plan
    accepts either." "A new account is stamped with an `account_number` from a deterministic
    sequential series in the form `RB-000001`, `RB-000002` and so on, zero-padded to six
    digits." "Opening an account has four consequences beyond the account itself." "The enquiry
    moves `QUALIFIED → CONSUMED`, which is terminal." "The reservation moves `HELD →
    CONSUMED`." "On the sector, `held_mbps` falls by the reservation's amount and `sold_mbps`
    rises by exactly the same amount, so `committed_mbps` and hence `oversubscription_ratio`,
    `remaining_allowance_mbps` and `capacity_posture` are **unchanged** by the conversion — the
    reservation was always a stand-in for this account, and the ledger simply reclassifies the
    bandwidth from reserved to sold." "Finally, exactly one equipment record is minted as a
    side effect: it opens in `ASSIGNED` `status`, its `acquisition_mode` copied from the
    account's `equipment_mode`, its `radio_serial` absent because no radio has been allocated
    yet, its `monthly_rental_cents` at 1000 for a `RENTAL` acquisition and 0 for a `PURCHASE`,
    its `purchase_price_cents` at 29900 for a `PURCHASE` and 0 for a `RENTAL`, its
    `replacement_cost_cents` at 34900 in both cases, its `settlement_cents` at 0 and its
    `settlement_basis`, `deployed_at`, `return_due_at`, `returned_at` and `return_condition`
    all absent."

    Design: Corner/cross_cutting_complexity_layers/a_late_priority_rejection_rolls_back_the_whole_account_creation_fan_out
    """
    scenario = setup_held_reservation(
        plan_overrides={"tier_code": "RNT50", "equipment_policy": "RENTAL_ONLY"}
    )
    request_id = scenario["request"]["id"]
    plan_id = scenario["plan"]["id"]
    hold_id = scenario["hold"]["id"]
    sector_id = scenario["sector"]["id"]

    opening_sector = get_sector(sector_id)
    assert opening_sector["sold_mbps"] == 0
    assert opening_sector["held_mbps"] == 50
    assert opening_sector["committed_mbps"] == 50

    refused = api_client.create_subscriber(
        create_subscriber_payload(
            request_id,
            plan_id,
            billing_email="rollback.one@example.com",
            equipment_mode="PURCHASE",
        ),
        SALES_AGENT,
    )
    validate_error(refused, ApiErrorId.ERR_PLAN_MISMATCH.value, 422)

    assert get_capacity_hold(hold_id)["status"] == "HELD"
    assert get_serviceability_request(request_id)["status"] == "QUALIFIED"
    _, accounts_meta = validate_paginated(api_client.list_subscribers(SALES_AGENT))
    assert accounts_meta["total_count"] == 0
    sector_after_refusal = get_sector(sector_id)
    assert_no_mutation(opening_sector, sector_after_refusal, entity="sector")
    assert sector_after_refusal["sold_mbps"] == 0
    assert sector_after_refusal["held_mbps"] == 50

    account = validate_success(
        api_client.create_subscriber(
            create_subscriber_payload(
                request_id,
                plan_id,
                billing_email="rollback.one@example.com",
                equipment_mode="RENTAL",
            ),
            SALES_AGENT,
        ),
        201,
    )
    assert account["service_status"] == "PENDING_INSTALL"
    assert account["account_number"] == "RB-000001"
    assert account["equipment_mode"] == "RENTAL"
    assert account["sector_id"] == sector_id
    assert account["usage_priority"] == "STANDARD"

    assert get_capacity_hold(hold_id)["status"] == "CONSUMED"
    assert get_serviceability_request(request_id)["status"] == "CONSUMED"
    _, retry_meta = validate_paginated(api_client.list_subscribers(SALES_AGENT))
    assert retry_meta["total_count"] == 1

    assignments = list_equipment_assignments(account["id"])
    assert len(assignments) == 1
    assert assignments[0]["status"] == "ASSIGNED"
    assert assignments[0]["acquisition_mode"] == "RENTAL"
    assert assignments[0]["monthly_rental_cents"] == 1000
    assert assignments[0]["purchase_price_cents"] == 0
    assert assignments[0]["replacement_cost_cents"] == 34900
    assert assignments[0]["settlement_cents"] == 0
    assert assignments[0].get("radio_serial") is None
    assert assignments[0].get("deployed_at") is None

    final_sector = get_sector(sector_id)
    assert final_sector["sold_mbps"] == 50
    assert final_sector["held_mbps"] == 0
    assert final_sector["committed_mbps"] == 50
    assert final_sector["oversubscription_ratio"] == 2.0
    assert final_sector["remaining_allowance_mbps"] == 150
    assert final_sector["capacity_posture"] == "OPEN"


def test_switching_the_credit_method_moves_the_same_outage_from_1706_to_206_cents():
    """PRD 3.9: "The credit records `prepared_by_user_id` as the preparing administrator's
    identifier and copies its `method` from the plan's `sla_credit_method`, which selects
    between the two computations below." "**The `SLA_SHORTFALL` method** compensates against the
    uptime promise across the whole cycle." "The cycle's gross entitlement is the plan's
    `monthly_price_cents` multiplied by `shortfall_pct`, divided by 100, multiplied by the
    shortfall multiplier of 10, rounded half up to whole cents, and then limited to the monthly
    cap." "**The `PER_INCIDENT` method** compensates strictly for the outage named in the
    request." "`cycle_outage_minutes` is that single outage's creditable minutes."
    "`measured_uptime_pct` and `shortfall_pct` are both recorded as 0.0 and
    `prior_cycle_credited_cents` as zero, because none of the three has any meaning under this
    method — they are reported for structural uniformity, not as measurements." "`credit_cents`
    is the plan's `monthly_price_cents` multiplied by those creditable minutes, divided by the
    monthly allowance of 43200 minutes, rounded half up to whole cents, and then limited to the
    same monthly cap." "A per-incident credit therefore refunds pro-rata for the minutes lost,
    and repeated outages in one cycle each earn their own credit up to the cap, without any
    prior-credit netting." "Because `credit_cents` is fixed at preparation and is **never**
    recomputed afterwards — not by a later cycle close, not by a further outage, not by a plan
    change — a reversal returns `credit_balance_cents` and `total_credited_cents` to exactly the
    values they held before the application, to the cent."

    Design: Corner/cross_cutting_complexity_layers/switching_the_credit_method_changes_the_same_outage_from_1706_to_206_cents
    """
    scenario = _setup_installed_account()
    subscriber_id = scenario["subscriber"]["id"]
    tower_id = scenario["tower"]["id"]
    assert scenario["subscriber"]["service_status"] == "ACTIVE"
    assert scenario["subscriber"]["cycle_start_date"] == "2026-08-02"
    per_incident_plan = create_service_plan(
        tier_code="PIN50", sla_credit_method="PER_INCIDENT"
    )
    assert per_incident_plan["monthly_price_cents"] == 6999
    assert per_incident_plan["downstream_mbps"] == 50

    set_clock("2026-08-06T00:00:00Z")
    first_outage = _closed_outage(tower_id, "2026-08-05T00:00:00Z", 1269)
    assert first_outage["status"] == "CLOSED"
    assert first_outage["duration_minutes"] == 1269
    assert first_outage["sla_excluded"] is False

    shortfall_credit = prepare_credit(first_outage["id"], subscriber_id)
    assert shortfall_credit["method"] == "SLA_SHORTFALL"
    assert shortfall_credit["cycle_outage_minutes"] == 1269
    assert shortfall_credit["measured_uptime_pct"] == 97.063
    assert shortfall_credit["shortfall_pct"] == 2.437
    assert shortfall_credit["prior_cycle_credited_cents"] == 0
    assert shortfall_credit["credit_cents"] == 1706
    assert shortfall_credit["status"] == "PENDING"
    assert shortfall_credit.get("denial_reason") is None

    applied_shortfall = apply_credit(shortfall_credit["id"])
    assert applied_shortfall["status"] == "APPLIED"
    account_on_shortfall = get_subscriber(subscriber_id)
    assert account_on_shortfall["credit_balance_cents"] == 1706

    switched = change_subscriber_plan(
        subscriber_id, per_incident_plan["id"], account_on_shortfall["version"]
    )
    assert switched["service_plan_id"] == per_incident_plan["id"]
    assert switched["cycle_start_date"] == "2026-08-02"

    set_clock("2026-08-08T00:00:00Z")
    second_outage = _closed_outage(tower_id, "2026-08-07T00:00:00Z", 1269)
    assert second_outage["duration_minutes"] == 1269
    assert second_outage["sla_excluded"] is False

    per_incident_credit = prepare_credit(second_outage["id"], subscriber_id)
    assert per_incident_credit["method"] == "PER_INCIDENT"
    assert per_incident_credit["cycle_outage_minutes"] == 1269
    assert per_incident_credit["measured_uptime_pct"] == 0.0
    assert per_incident_credit["shortfall_pct"] == 0.0
    assert per_incident_credit["prior_cycle_credited_cents"] == 0
    assert per_incident_credit["credit_cents"] == 206
    assert per_incident_credit["status"] == "PENDING"
    assert per_incident_credit.get("denial_reason") is None

    assert shortfall_credit["credit_cents"] - per_incident_credit["credit_cents"] == 1500
    assert get_credit(shortfall_credit["id"])["credit_cents"] == 1706

    applied_per_incident = apply_credit(per_incident_credit["id"])
    assert applied_per_incident["status"] == "APPLIED"
    settled_account = get_subscriber(subscriber_id)
    assert settled_account["credit_balance_cents"] == 1912


def test_the_soft_cap_bites_only_strictly_above_the_line():
    """PRD 3.8: "The cycle is breached when `cycle_usage_gb` is **strictly greater** than the
    plan's `soft_cap_gb`; usage landing exactly on the cap is not a breach." "`usage_priority`
    is then `DEPRIORITIZED` when either the current cycle is breached or
    `sticky_deprioritization_active` is true, and `STANDARD` otherwise."
    "`effective_downstream_mbps` follows: while `DEPRIORITIZED` it is the plan's
    `downstream_mbps` multiplied by the plan's `deprioritization_factor`, floored at a minimum
    deliverable rate of 0.1 Mbps, and rounded half up to one decimal place — so a heavy user on
    a 25 Mbps plan with a factor of 0.05 is shaped to 1.3 Mbps rather than to 1.25, and a 1 Mbps
    plan with a factor of 0.05 is shaped to the 0.1 Mbps floor rather than to 0.1 by rounding
    coincidence." "`cycle_usage_gb` is recomputed from scratch on every ingestion and on every
    cycle close."

    Design: Corner/cross_cutting_complexity_layers/the_soft_cap_bites_only_above_the_line_and_stickiness_survives_one_clean_cycle
    """
    scenario = _setup_installed_account()
    subscriber_id = scenario["subscriber"]["id"]
    assert scenario["subscriber"]["cycle_start_date"] == "2026-08-02"
    assert scenario["subscriber"]["usage_priority"] == "STANDARD"
    assert scenario["plan"]["soft_cap_gb"] == 600.0
    assert scenario["plan"]["deprioritization_factor"] == 0.25

    set_clock("2026-08-20T00:00:00Z")
    on_the_line = ingest_usage(subscriber_id, "2026-08-03", 590.0, 10.0)
    assert on_the_line["total_gb"] == 600.0
    assert on_the_line["in_current_cycle"] is True

    at_cap = get_subscriber(subscriber_id)
    assert at_cap["cycle_usage_gb"] == 600.0
    assert at_cap["usage_priority"] == "STANDARD"
    assert at_cap["effective_downstream_mbps"] == 50.0
    assert at_cap.get("deprioritized_at") is None
    assert at_cap["consecutive_breach_cycles"] == 0
    assert at_cap["sticky_deprioritization_active"] is False

    over_the_line = ingest_usage(subscriber_id, "2026-08-04", 0.1, 0.0)
    assert over_the_line["total_gb"] == 0.1
    assert over_the_line["in_current_cycle"] is True

    breached = get_subscriber(subscriber_id)
    assert breached["cycle_usage_gb"] == 600.1
    assert breached["usage_priority"] == "DEPRIORITIZED"
    assert breached["effective_downstream_mbps"] == 12.5
    assert _instant(breached["deprioritized_at"]) == "2026-08-20T00:00:00"
    assert breached["consecutive_breach_cycles"] == 0
    assert breached["sticky_deprioritization_active"] is False


def test_stickiness_needs_two_breached_cycles_and_one_clean_cycle_clears_it():
    """PRD 3.8: "The close first judges the cycle that is ending against the plan's
    `soft_cap_gb`, then rolls the window forward, then re-derives the posture over the new
    window." "**A breached cycle on a `DEPRIORITIZED` account** keeps it `DEPRIORITIZED`."
    "`consecutive_breach_cycles` is increased by one, and once that counter reaches the sticky
    threshold of 2, `sticky_deprioritization_active` is set to true — which is what makes the
    shaping survive the next cycle: the account opens the following window already
    `DEPRIORITIZED` even at zero metered usage, and only a clean cycle can clear it."
    "`cycle_start_date` advances by 30 days and `cycle_usage_gb` and
    `effective_downstream_mbps` are recomputed over the new window." "**A clean cycle on a
    `DEPRIORITIZED` account** moves it `DEPRIORITIZED → STANDARD`, provided the closing cycle's
    `cycle_usage_gb` was at or below `soft_cap_gb` and `consecutive_breach_cycles` after the
    close is strictly below the sticky threshold of 2." "`consecutive_breach_cycles` is set to
    zero, `sticky_deprioritization_active` is set to false, `deprioritized_at` is cleared,
    `cycle_start_date` advances by 30 days, and `cycle_usage_gb` is recomputed over the new
    window with `effective_downstream_mbps` restored to the plan's `downstream_mbps`."

    Design: Corner/cross_cutting_complexity_layers/the_soft_cap_bites_only_above_the_line_and_stickiness_survives_one_clean_cycle
    """
    scenario = _setup_installed_account()
    subscriber_id = scenario["subscriber"]["id"]
    assert scenario["subscriber"]["cycle_start_date"] == "2026-08-02"

    set_clock("2026-08-20T00:00:00Z")
    ingest_usage(subscriber_id, "2026-08-03", 590.0, 10.0)
    ingest_usage(subscriber_id, "2026-08-04", 0.1, 0.0)
    breached = get_subscriber(subscriber_id)
    assert breached["cycle_usage_gb"] == 600.1
    assert breached["usage_priority"] == "DEPRIORITIZED"

    first_close = close_cycle(subscriber_id)
    assert first_close["consecutive_breach_cycles"] == 1
    assert first_close["sticky_deprioritization_active"] is False
    assert first_close["cycle_start_date"] == "2026-09-01"
    assert first_close["cycle_usage_gb"] == 0.0

    set_clock("2026-09-20T00:00:00Z")
    second_cycle_day = ingest_usage(subscriber_id, "2026-09-02", 700.0, 0.0)
    assert second_cycle_day["in_current_cycle"] is True
    over_again = get_subscriber(subscriber_id)
    assert over_again["cycle_usage_gb"] == 700.0
    assert over_again["usage_priority"] == "DEPRIORITIZED"
    assert over_again["effective_downstream_mbps"] == 12.5

    second_close = close_cycle(subscriber_id)
    assert second_close["consecutive_breach_cycles"] == 2
    assert second_close["sticky_deprioritization_active"] is True
    assert second_close["cycle_start_date"] == "2026-10-01"
    assert second_close["cycle_usage_gb"] == 0.0
    assert second_close["usage_priority"] == "DEPRIORITIZED"
    assert second_close["effective_downstream_mbps"] == 12.5

    set_clock("2026-11-01T00:00:00Z")
    third_close = close_cycle(subscriber_id)
    assert third_close["consecutive_breach_cycles"] == 0
    assert third_close["sticky_deprioritization_active"] is False
    assert third_close["cycle_start_date"] == "2026-10-31"
    assert third_close["cycle_usage_gb"] == 0.0
    assert third_close["usage_priority"] == "STANDARD"
    assert third_close["effective_downstream_mbps"] == 50.0
    assert third_close.get("deprioritized_at") is None
