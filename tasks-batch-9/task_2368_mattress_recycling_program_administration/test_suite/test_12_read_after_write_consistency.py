"""Every effect of a write is on the record before the response leaves: the next read
sees the same custody buckets, the same credit and the same reserve, never a stale copy."""

import pytest

from test_helpers import (
    TEST_USERS,
    create_enrolled_site,
    create_pickup_order_payload,
    create_wa_program,
    make_site_operator_headers,
    read_fee_adequacy,
    setup_logistics_chain,
    submit_volume_report,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


def test_the_order_read_straight_after_dispatch_matches_what_dispatch_returned(api):
    """PRD §2.11: "Cascades are applied in the same request, synchronously, before the
    response is produced — there is no deferred settlement and no eventual
    consistency."

    PRD §3.6: "Creation moves the manifested units out of the site's `units_on_hand`
    into `units_in_transit` and increments the hauler's `active_route_count` by one."

    Design: Corner/consistency_model/dispatch_response_and_immediate_reads_agree_on_custody
    """
    chain = setup_logistics_chain(api)

    created = validate_success(
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
            make_site_operator_headers(chain["site_id"]),
        ),
        201,
    )
    read_back = validate_success(api.get_pickup_order(created["id"], chain["hauler_headers"]))
    site = validate_success(
        api.get_collection_site(chain["site_id"], make_site_operator_headers(chain["site_id"]))
    )
    hauler = validate_success(api.get_hauler(chain["hauler_id"], ADMIN))

    assert read_back == created
    assert read_back["fulfillment_status"] == "SCHEDULED"
    assert read_back["settlement_status"] == "UNSETTLED"
    assert read_back["units_manifested"] == 100
    assert read_back["estimated_payment_cents"] is None
    assert site["units_on_hand"] == 410
    assert site["units_in_transit"] == 100
    assert hauler["active_route_count"] == 1


def test_the_accepted_credit_is_already_in_every_ledger_the_next_read_touches(api):
    """PRD §2.11: "Cascades are applied in the same request, synchronously, before the
    response is produced — there is no deferred settlement and no eventual
    consistency."

    PRD §3.5: "The credit in cents is the credited units multiplied by the program's
    `site_credit_cents_per_unit`, multiplied by one plus the bonus percentage, with
    the round-half-up applied once to that bonus-multiplied product."

    Design: Corner/consistency_model/volume_report_acceptance_is_visible_to_the_next_read
    """
    program = create_wa_program(api)
    site = create_enrolled_site(api, program["id"])
    site_headers = make_site_operator_headers(site["id"])
    report = submit_volume_report(
        api, site["id"], period_month="2026-08", units_mattress=320, units_foundation=190
    )

    accepted = validate_success(api.accept_volume_report(report["id"], ADMIN))

    assert accepted["status"] == "ACCEPTED"
    assert accepted["credited_units"] == 510
    assert accepted["credit_cents"] == 163_328

    rows, meta = validate_paginated(api.list_volume_reports(site["id"], site_headers))
    stored_site = validate_success(api.get_collection_site(site["id"], site_headers))
    adequacy = read_fee_adequacy(api, program["id"])

    assert meta["total_count"] == 1
    assert rows[0]["id"] == report["id"]
    assert rows[0]["status"] == "ACCEPTED"
    assert rows[0]["credit_cents"] == 163_328
    assert stored_site["units_on_hand"] == 510
    assert stored_site["units_reported_total"] == 510
    assert adequacy["reserve_balance_cents"] == 4_836_672
    assert adequacy["reserve_coverage_months"] == pytest.approx(0.97)
