"""Stale views, sub-threshold strikes and derived totals: what a refreshed version pin
buys, what two rejected loads do not cost, and how the ledgers re-derive themselves."""

import pytest

from test_helpers import (
    TEST_USERS,
    create_accepted_volume_report,
    create_active_rate,
    create_ca_program,
    create_enrolled_site,
    create_fee_rate_schedule_payload,
    create_registrant,
    create_remittance,
    create_take_back,
    complete_take_back,
    dispatch_order,
    file_remittance,
    inspect_load,
    make_registrant_headers,
    open_audit,
    pay_remittance,
    pickup_and_deliver,
    read_fee_adequacy,
    read_program,
    request_amendment,
    revise_forecast,
    setup_logistics_chain,
    setup_paid_remittance,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


def test_a_proposal_written_from_an_unrefreshed_program_view_is_refused(api):
    """PRD §2.9: "If that value does not equal the program's current `version`, the
    proposal is rejected with `ERR_STALE_PROGRAM_VERSION` and HTTP 412."

    PRD §3.2: "It snapshots the program's recommended rate at that instant into
    `recommended_rate_cents_at_proposal` and derives `band_low_cents` and
    `band_high_cents` from that snapshot, and it increments the program's `version`
    by one."

    Design: Corner/cross_cutting_layers/stale_program_version_rejects_a_rate_proposal
    """
    program = create_ca_program(api)
    first_version = program["version"]
    revised = revise_forecast(api, program["id"], {"forecast_other_revenue_cents": 3_000_000})
    second_version = revised["version"]

    stale = api.create_fee_rate_schedule(
        create_fee_rate_schedule_payload(program["id"], first_version), ADMIN
    )

    validate_error(stale, "ERR_STALE_PROGRAM_VERSION", 412)
    _, meta = validate_paginated(
        api.list_fee_rate_schedules(ADMIN, params={"state_program_id": program["id"]})
    )
    assert meta["total_count"] == 0

    accepted = validate_success(
        api.create_fee_rate_schedule(
            create_fee_rate_schedule_payload(program["id"], second_version), ADMIN
        ),
        201,
    )

    assert accepted["status"] == "PROPOSED"
    assert accepted["recommended_rate_cents_at_proposal"] == 1075
    assert read_program(api, program["id"])["version"] == 3


def test_the_version_pin_answers_before_the_band_arithmetic_does(api):
    """PRD §2.10: "Program version pinning (`ERR_STALE_PROGRAM_VERSION`), then
    remittance version pinning (`ERR_STALE_REMITTANCE_VERSION`)."

    PRD §3.2: "The proposed `fee_cents_per_unit` must be at least `band_low_cents`
    and at most `band_high_cents` as snapshotted on this proposal; a value outside
    that inclusive range is rejected with `ERR_RATE_OUTSIDE_RECOMMENDED_BAND`."

    Design: Corner/cross_cutting_layers/stale_program_version_precedes_the_band_check
    """
    program = create_ca_program(api)
    first_version = program["version"]
    revised = revise_forecast(api, program["id"], {"forecast_annual_cost_cents": 72_000_000})
    second_version = revised["version"]

    stale_and_low = api.create_fee_rate_schedule(
        create_fee_rate_schedule_payload(
            program["id"], first_version, fee_cents_per_unit=900
        ),
        ADMIN,
    )
    fresh_and_low = api.create_fee_rate_schedule(
        create_fee_rate_schedule_payload(
            program["id"], second_version, fee_cents_per_unit=900
        ),
        ADMIN,
    )
    at_the_floor = api.create_fee_rate_schedule(
        create_fee_rate_schedule_payload(
            program["id"], second_version, fee_cents_per_unit=1047
        ),
        ADMIN,
    )

    validate_error(stale_and_low, "ERR_STALE_PROGRAM_VERSION", 412)
    validate_error(fresh_and_low, "ERR_RATE_OUTSIDE_RECOMMENDED_BAND", 422)
    accepted = validate_success(at_the_floor, 201)
    assert accepted["recommended_rate_cents_at_proposal"] == 1309
    assert accepted["band_low_cents"] == 1047
    assert accepted["band_high_cents"] == 1571
    assert accepted["fee_cents_per_unit"] == 1047


def test_a_stale_amendment_burns_no_round_and_the_refreshed_one_lands(api):
    """PRD §2.9: "If that value does not equal the remittance's current `version`,
    the submission is rejected with `ERR_STALE_REMITTANCE_VERSION` and HTTP 412."

    PRD §3.4: "Accepting the submission does three things: it increments the audited
    remittance's `amendment_round` by one, increments that remittance's `version` by
    one, and creates a **new** remittance row in `DRAFT` whose `amends_remittance_id`
    points at the audited parent and which copies the parent's `registrant_id`,
    `state_program_id` and `period_code` while carrying the revised sales figures."

    Design: Corner/cross_cutting_layers/stale_remittance_version_rejects_an_amendment
    """
    program = create_ca_program(api)
    create_active_rate(
        api,
        program["id"],
        unit_class="MATTRESS",
        fee_cents_per_unit=1100,
        effective_from="2026-01-01T00:00:00Z",
    )
    registrant = create_registrant(api)
    registrant_headers = make_registrant_headers(registrant["id"])
    draft = create_remittance(
        api,
        registrant["id"],
        program["id"],
        period_code="2026Q2",
        units_sold_mattress=500,
        units_sold_foundation=0,
    )
    draft_version = draft["version"]
    file_remittance(api, draft["id"], registrant["id"])
    pay_remittance(api, draft["id"], registrant["id"], 550_000)
    open_audit(api, draft["id"])
    sent_back = request_amendment(
        api, draft["id"], "Reconcile 2026Q2 unit counts against the shipment log"
    )

    stale = api.create_remittance_amendment(
        draft["id"],
        {
            "units_sold_mattress": 520,
            "units_sold_foundation": 0,
            "expected_remittance_version": draft_version,
        },
        registrant_headers,
    )

    validate_error(stale, "ERR_STALE_REMITTANCE_VERSION", 412)
    waiting = validate_success(api.get_sales_remittance(draft["id"], AUDITOR))
    assert waiting["status"] == "AMENDMENT_REQUIRED"
    assert waiting["amendment_round"] == 0

    parent = validate_success(
        api.create_remittance_amendment(
            draft["id"],
            {
                "units_sold_mattress": 520,
                "units_sold_foundation": 0,
                "expected_remittance_version": sent_back["version"],
            },
            registrant_headers,
        ),
        201,
    )

    assert parent["status"] == "UNDER_AUDIT"
    assert parent["amendment_round"] == 1
    rows, meta = validate_paginated(
        api.list_sales_remittances(ADMIN, params={"registrant_id": registrant["id"]})
    )
    assert meta["total_count"] == 2
    child = next(row for row in rows if row["id"] != draft["id"])
    assert child["status"] == "DRAFT"
    assert child["amends_remittance_id"] == draft["id"]
    assert child["units_sold_mattress"] == 520
    assert child["period_code"] == "2026Q2"


def test_two_rejected_loads_leave_the_site_enrolled_with_two_strikes(api):
    """PRD §3.7: "The third hop applies when the strike count has thereby reached
    three: the site's `enrollment_status` moves `ENROLLED → SUSPENDED` with
    `suspended_at` set from the logical clock."

    PRD §3.7: "The source site's `units_at_recycler_count` falls by the order's
    delivered units, its `units_recycled_count` grows by the accepted units, and its
    `units_written_off_count` grows by the rejected remainder."

    Design: Corner/cross_cutting_layers/contamination_strikes_below_the_threshold_do_not_suspend_the_site
    """
    chain = setup_logistics_chain(api)
    windows = [
        ("2026-08-05T09:00:00Z", "2026-08-05T10:00:00Z"),
        ("2026-08-07T09:00:00Z", "2026-08-07T10:00:00Z"),
    ]
    for start, end in windows:
        order = dispatch_order(
            api,
            chain["site_id"],
            chain["recycler_id"],
            hauler_id=chain["hauler_id"],
            units_manifested=50,
            route_distance_km=10.0,
            pickup_window_start=start,
            pickup_window_end=end,
        )
        pickup_and_deliver(api, order["id"], chain["hauler_id"], 50)
        inspection = inspect_load(api, order["id"], chain["recycler_id"], 10)

        assert inspection["contamination_pct"] == pytest.approx(20.00)
        assert inspection["disposition"] == "FULL_REJECT"
        assert inspection["rejection_reason"] == "CONTAMINATION_THRESHOLD"
        assert inspection["units_accepted"] == 0

    site = validate_success(api.get_collection_site(chain["site_id"], ADMIN))

    assert site["contamination_strike_count"] == 2
    assert site["enrollment_status"] == "ENROLLED"
    assert site["infestation_quarantine_until"] is None
    assert site["units_written_off_count"] == 100
    assert site["units_recycled_count"] == 0
    assert site["units_at_recycler_count"] == 0
    assert site["units_in_transit"] == 0
    assert site["units_on_hand"] == 410


def test_a_partial_refund_re_derives_the_reserve_and_the_recommendation(api):
    """PRD §3.3: "On success the refunded amount is added to `fee_refunded_cents`, and
    the program's `fee_collected_cents` and `reserve_balance_cents` are reconciled,
    followed by `reserve_coverage_months` and `recommended_rate_cents`."

    PRD §3.1: "It returns `recommended_rate_cents`, `band_low_cents` and
    `band_high_cents` together with the intermediate values that produced them —
    `base_rate_cents`, `admin_surcharge_pct`, `reserve_target_cents` and
    `reserve_gap_cents` — plus the current `reserve_balance_cents` and
    `reserve_coverage_months`."

    Design: Corner/cross_cutting_layers/reserve_balance_and_recommendation_reconcile_after_a_partial_refund
    """
    chain = setup_paid_remittance(api)

    refunded = validate_success(
        api.refund_sales_remittance(
            chain["remittance_id"],
            {"amount_cents": 200_000, "reason": "OVERSTATED_UNITS"},
            ADMIN,
        )
    )

    assert refunded["status"] == "REFUNDED"
    assert refunded["fee_paid_cents"] == 550_000
    assert refunded["fee_refunded_cents"] == 200_000
    program = read_program(api, chain["program_id"])
    assert program["fee_collected_cents"] == 350_000
    assert program["reserve_balance_cents"] == 5_350_000
    assert program["reserve_coverage_months"] == pytest.approx(1.07)
    assert program["recommended_rate_cents"] == 1072
    adequacy = read_fee_adequacy(api, chain["program_id"])
    assert adequacy["reserve_gap_cents"] == 9_650_000
    assert adequacy["base_rate_cents"] == 1031
    assert adequacy["recommended_rate_cents"] == 1072
    assert adequacy["band_low_cents"] == 857
    assert adequacy["band_high_cents"] == 1287


def test_the_reported_total_gathers_both_intake_paths_but_credit_pays_one(api):
    """PRD §3.5: "The credited units are added to the site's `units_on_hand` and to
    its `units_reported_total`. The credit in cents is added to the program's
    `site_credit_paid_cents`, after which the program's `reserve_balance_cents`,
    `reserve_coverage_months`, `recommended_rate_cents` and `reported_units_total`
    are all recomputed."

    PRD §3.8: "The collected units are added to the receiving site's `units_on_hand`
    and to its `units_reported_total`, and the program's `reported_units_total` is
    recomputed. Nothing is charged to the registrant."

    Design: Corner/cross_cutting_layers/site_reported_units_total_reconciles_two_independent_intake_paths
    """
    program = create_ca_program(api)
    site = create_enrolled_site(
        api,
        program["id"],
        operator_name="Bay Area Collection Site",
        site_type="COLLECTION_SITE",
        region_code="WEST",
    )
    registrant = create_registrant(api)
    june = create_accepted_volume_report(
        api, site["id"], period_month="2026-06", units_mattress=100, units_foundation=50
    )
    july = create_accepted_volume_report(
        api, site["id"], period_month="2026-07", units_mattress=200, units_foundation=0
    )
    delivery = create_take_back(
        api,
        registrant["id"],
        site["id"],
        delivery_reference="DEL-6001",
        units_delivered_new=10,
        units_takeback_offered=10,
    )

    completed = complete_take_back(api, delivery["id"], registrant["id"], 10)

    assert completed["status"] == "OBLIGATION_MET"
    assert completed["breach_penalty_cents"] == 0
    assert june["credit_cents"] == 45_750
    assert july["credit_cents"] == 61_000
    stored_site = validate_success(api.get_collection_site(site["id"], ADMIN))
    assert stored_site["units_reported_total"] == 360
    assert stored_site["units_on_hand"] == 360
    assert stored_site["units_in_transit"] == 0
    assert stored_site["units_at_recycler_count"] == 0
    assert stored_site["units_recycled_count"] == 0
    assert stored_site["units_written_off_count"] == 0
    stored_program = read_program(api, program["id"])
    assert stored_program["site_credit_paid_cents"] == 106_750
    assert stored_program["reported_units_total"] == 360
    assert stored_program["reserve_balance_cents"] == 4_893_250
    assert stored_program["reserve_coverage_months"] == pytest.approx(0.98)
