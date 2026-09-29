"""Endpoint-level behaviour: partial forecast revision, the auto-selection flag on a
dispatch, sub-resource scoping, verification roll-up, the clock and the computed read."""

import pytest

from test_helpers import (
    AUDITOR_1_USER_ID,
    TEST_USERS,
    create_ca_program,
    create_certified_recycler,
    create_enrolled_site,
    create_pickup_order_payload,
    create_registrant,
    create_wa_program,
    make_recycler_headers,
    make_site_operator_headers,
    read_fee_adequacy,
    read_program,
    revise_forecast,
    set_clock,
    setup_logistics_chain,
    submit_commodity_output,
    submit_volume_report,
    validate_paginated,
    validate_success,
    verify_commodity_output,
)

ADMIN = TEST_USERS["admin_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


def test_a_partial_forecast_revision_leaves_the_unnamed_inputs_alone(api):
    """PRD §3.1: "A revision may carry any subset of `forecast_annual_cost_cents`,
    `forecast_annual_units`, `forecast_other_revenue_cents` and
    `reserve_target_months`, leaving unnamed fields untouched; it recomputes
    `reserve_coverage_months` and `recommended_rate_cents` and increments the
    program's `version` by one."

    Design: Corner/endpoints/cost_forecast_patch_updates_only_supplied_fields
    """
    program = create_ca_program(api)

    revised = revise_forecast(api, program["id"], {"forecast_annual_cost_cents": 72_000_000})

    assert revised["forecast_annual_cost_cents"] == 72_000_000
    assert revised["forecast_annual_units"] == 60_000
    assert revised["forecast_other_revenue_cents"] == 3_000_000
    assert revised["reserve_target_months"] == 3
    assert revised["reserve_balance_cents"] == 5_000_000
    assert revised["version"] == 2
    assert revised["reserve_coverage_months"] == pytest.approx(0.83)
    assert revised["recommended_rate_cents"] == 1309

    adequacy = read_fee_adequacy(api, program["id"])

    assert adequacy["reserve_target_cents"] == 18_000_000
    assert adequacy["reserve_gap_cents"] == 13_000_000
    assert adequacy["base_rate_cents"] == 1259
    assert adequacy["admin_surcharge_pct"] == pytest.approx(0.04)
    assert adequacy["band_low_cents"] == 1047
    assert adequacy["band_high_cents"] == 1571


def test_omitting_the_hauler_records_that_the_server_chose_it(api):
    """PRD §3.6: "The `hauler_id` may be supplied explicitly, or omitted to let the
    server choose; the resulting order records which happened in
    `hauler_auto_selected`, true when the server resolved the hauler and false when
    the client named one."

    Design: Corner/endpoints/pickup_order_omitting_hauler_id_sets_the_auto_selected_flag
    """
    chain = setup_logistics_chain(api)
    site_headers = make_site_operator_headers(chain["site_id"])

    explicit = validate_success(
        api.create_pickup_order(
            create_pickup_order_payload(
                chain["site_id"],
                chain["recycler_id"],
                hauler_id=chain["hauler_id"],
                units_manifested=100,
                route_distance_km=40.0,
                pickup_window_start="2026-08-05T09:00:00Z",
                pickup_window_end="2026-08-05T11:00:00Z",
            ),
            site_headers,
        ),
        201,
    )
    auto = validate_success(
        api.create_pickup_order(
            create_pickup_order_payload(
                chain["site_id"],
                chain["recycler_id"],
                units_manifested=100,
                route_distance_km=40.0,
                pickup_window_start="2026-08-06T09:00:00Z",
                pickup_window_end="2026-08-06T11:00:00Z",
            ),
            site_headers,
        ),
        201,
    )

    assert explicit["hauler_id"] == chain["hauler_id"]
    assert explicit["hauler_auto_selected"] is False
    assert auto["hauler_id"] == chain["hauler_id"]
    assert auto["hauler_auto_selected"] is True
    site = validate_success(api.get_collection_site(chain["site_id"], ADMIN))
    assert site["units_on_hand"] == 310
    assert site["units_in_transit"] == 200


def test_each_sites_report_list_shows_only_that_sites_reports(api):
    """PRD §3.5: "The report records the `collection_site_id` of the site it was
    submitted against."

    PRD §2.3: "Collection sites may be narrowed by `state_program_id`,
    `enrollment_status` and `site_type`; a site's volume reports by `status` and
    `period_month`."

    Design: Corner/endpoints/volume_report_sub_resource_list_is_scoped_to_its_own_site
    """
    program = create_wa_program(api)
    site_a = create_enrolled_site(api, program["id"])
    site_b = create_enrolled_site(
        api,
        program["id"],
        operator_name="Olympic Dropoff",
        site_type="PERMANENT_DROPOFF",
    )
    first_a = submit_volume_report(
        api, site_a["id"], period_month="2026-06", units_mattress=100, units_foundation=50
    )
    second_a = submit_volume_report(
        api, site_a["id"], period_month="2026-07", units_mattress=200, units_foundation=0
    )
    only_b = submit_volume_report(
        api, site_b["id"], period_month="2026-06", units_mattress=7, units_foundation=3
    )

    a_rows, a_meta = validate_paginated(
        api.list_volume_reports(site_a["id"], make_site_operator_headers(site_a["id"]))
    )
    b_rows, b_meta = validate_paginated(api.list_volume_reports(site_b["id"], ADMIN))

    assert a_meta["total_count"] == 2
    assert all(row["collection_site_id"] == site_a["id"] for row in a_rows)
    assert {row["id"] for row in a_rows} == {first_a["id"], second_a["id"]}
    assert only_b["id"] not in {row["id"] for row in a_rows}
    assert b_meta["total_count"] == 1
    assert b_rows[0]["id"] == only_b["id"]
    assert all(row["credit_cents"] == 0 for row in a_rows + b_rows)
    assert all(row["status"] == "SUBMITTED" for row in a_rows + b_rows)


def test_only_verified_records_lift_the_facilitys_outbound_weight(api):
    """PRD §3.7: "A `ProgramAuditor` verifies a record, moving `SUBMITTED → VERIFIED`
    and recording `verified_by_user_id`; verification is legal only from `SUBMITTED`,
    otherwise `ERR_COMMODITY_RECORD_NOT_SUBMITTED`. Verification recomputes the
    facility's `verified_output_weight_kg` — the sum of `output_weight_kg` over that
    facility's `VERIFIED` records — and its `diversion_rate_pct`."

    Design: Corner/endpoints/commodity_verification_rolls_up_into_recycler_verified_weight
    """
    program = create_wa_program(api)
    recycler = create_certified_recycler(api, program["id"])
    steel = submit_commodity_output(
        api,
        recycler["id"],
        commodity="STEEL",
        output_weight_kg=1200.5,
        source_period_month="2026-07",
    )
    foam = submit_commodity_output(
        api,
        recycler["id"],
        commodity="FOAM",
        output_weight_kg=800.25,
        source_period_month="2026-07",
    )

    first = verify_commodity_output(api, steel["id"])

    assert first["record_status"] == "VERIFIED"
    assert first["verified_by_user_id"] == AUDITOR_1_USER_ID
    after_first = validate_success(api.get_recycler(recycler["id"], AUDITOR))
    assert after_first["verified_output_weight_kg"] == pytest.approx(1200.5)
    assert after_first["units_processed_count"] == 0
    assert after_first["diversion_rate_pct"] == pytest.approx(0.00)

    verify_commodity_output(api, foam["id"])

    after_second = validate_success(api.get_recycler(recycler["id"], AUDITOR))
    assert after_second["verified_output_weight_kg"] == pytest.approx(2000.75)
    assert after_second["diversion_rate_pct"] == pytest.approx(0.00)
    _, meta = validate_paginated(
        api.list_commodity_output_records(
            recycler["id"], make_recycler_headers(recycler["id"]),
            params={"record_status": "VERIFIED"},
        )
    )
    assert meta["total_count"] == 2


def test_moving_the_clock_retimes_later_writes_without_rewriting_history(api):
    """PRD §2.4: "A `ProgramAdministrator` may advance or rewind the clock by
    supplying a `to_iso8601` instant to `POST /_clock/set_current_utc`, which
    responds with the new `current_utc`. Every subsequent read of the current
    instant — including the stamping of `filed_at`, `accepted_at`, `suspended_at`
    and `certified_at`, and every quarantine and effective-date comparison — uses
    the new value."

    Design: Corner/endpoints/clock_endpoint_moves_now_for_subsequent_writes_only
    """
    program = create_ca_program(api)

    clock = set_clock(api, "2026-09-15T12:00:00Z")
    registrant = create_registrant(api)

    assert clock["current_utc"].startswith("2026-09-15T12:00:00")
    assert registrant["created_at"].startswith("2026-09-15T12:00:00")
    stored_program = read_program(api, program["id"])
    assert stored_program["created_at"].startswith("2026-08-01T00:00:00")
    assert stored_program["version"] == 1


def test_the_adequacy_read_exposes_the_gap_arithmetic_and_changes_nothing(api):
    """PRD §3.1: "It returns `recommended_rate_cents`, `band_low_cents` and
    `band_high_cents` together with the intermediate values that produced them —
    `base_rate_cents`, `admin_surcharge_pct`, `reserve_target_cents` and
    `reserve_gap_cents` — plus the current `reserve_balance_cents` and
    `reserve_coverage_months`."

    Design: Corner/endpoints/fee_adequacy_read_exposes_gap_arithmetic_without_mutating
    """
    program = create_ca_program(api)

    administrator_read = read_fee_adequacy(api, program["id"])
    auditor_read = read_fee_adequacy(api, program["id"], AUDITOR)

    assert administrator_read["reserve_target_cents"] == 15_000_000
    assert administrator_read["reserve_gap_cents"] == 10_000_000
    assert administrator_read["reserve_balance_cents"] == 5_000_000
    assert administrator_read["base_rate_cents"] == 1034
    assert administrator_read["admin_surcharge_pct"] == pytest.approx(0.04)
    assert administrator_read["recommended_rate_cents"] == 1075
    assert administrator_read["band_low_cents"] == 860
    assert administrator_read["band_high_cents"] == 1290
    assert administrator_read["reserve_coverage_months"] == pytest.approx(1.00)
    assert auditor_read == administrator_read
    stored = read_program(api, program["id"])
    assert stored["version"] == 1
    assert stored["recommended_rate_cents"] == 1075
