"""
Endpoint-surface behaviour: the sweep's per-counter envelope, the clock's mandatory
default, the agency guard on offer reinstatement, the clawback that returns rotation
headroom, and the existence tier that resolves path ids before body ids.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ERR_AGENCY_SUSPENDED, ERR_RESOURCE_NOT_FOUND
from test_helpers.assertions import (
    assert_account_aggregates,
    assert_ledger_entry,
    assert_page,
    assert_sweep_counters,
    assert_timestamp_equals,
    read_ledger,
)
from test_helpers.test_users import (
    ADMIN_HEADERS,
    ANALYST_HEADERS,
    APPROVER_HEADERS,
    make_cardholder_headers,
)
from test_helpers.types import (
    AGENCY_SUSPENDED,
    CATEGORY_GROCERY,
    ENTRY_CLAWBACK,
    EVENT_CLOSED,
    EVENT_RUNNING,
    OFFER_SUSPENDED,
    POSTURE_CLEAR,
    ROTATION_ACTIVE,
    SOURCE_TRANSACTION,
    SUSPENSION_AGENCY_SUSPENDED,
    TRANSACTION_REVERSED,
)

GROCERY_MCC = "5411"
BOGUS_OFFER_ID = "11111111-1111-4111-8111-111111111111"
BOGUS_ACCOUNT_ID = "33333333-3333-4333-8333-333333333333"
BOGUS_AGREEMENT_ID = "44444444-4444-4444-8444-444444444444"


def _grocery(api, base_multiplier=1.0):
    """The 1.0x grocery mapping, created once per test database."""
    return fx.ensure_mapping(
        api,
        ADMIN_HEADERS,
        mcc_code=GROCERY_MCC,
        display_name="Grocery Stores",
        base_category=CATEGORY_GROCERY,
        base_multiplier=base_multiplier,
        is_fallback=False,
    )


def test_the_sweep_envelope_moves_one_counter_per_machine_that_is_due(api):
    """
    "The sweep returns a count for each step — `rotations_activated`,
    `rotations_expired`, `bonus_events_opened`, `bonus_events_closed`,
    `notices_made_effective`, `grandfather_windows_matured`, `transfers_completed`,
    and `entitlements_expired` — together with `clock_utc`, the instant the sweep ran
    against. ... A sweep that finds nothing to do is not an error; it returns zeroes."

    Design: Corner/endpoints/ops_run_envelope_reports_each_sweep_counter_independently
    """
    category = _grocery(api)
    rotation = validate_success(
        api.create_rotation(
            f.rotation_payload(
                merchant_category_id=category["id"],
                rotation_code="SEPT-GROCERY",
                bonus_multiplier=2.0,
                capped_spend_cents=50000,
                window_start="2026-09-01T00:00:00.000Z",
                window_end="2026-10-01T00:00:00.000Z",
            ),
            ADMIN_HEADERS,
        ),
        201,
    )
    validate_success(api.publish_rotation(rotation["id"], {}, ADMIN_HEADERS))
    agreement = fx.active_agreement(
        api,
        ADMIN_HEADERS,
        APPROVER_HEADERS,
        partner_name="Skyward Miles",
        partner_program_code="SKYW",
        transfer_latency_hours=48,
        reversal_window_hours=72,
        settlement_cost_cents_per_1k=900,
    )
    event = fx.new_bonus_event(
        api,
        agreement["id"],
        ADMIN_HEADERS,
        event_code="SEPT-BOOST",
        bonus_bps=3000,
        window_start="2026-09-01T00:00:00.000Z",
        window_end="2026-09-10T00:00:00.000Z",
        cap_points_per_account=50000,
    )

    idle = fx.ops_run(api)
    assert_sweep_counters(idle)
    assert_timestamp_equals(idle["clock_utc"], "2026-08-01T00:00:00.000Z")

    fx.set_clock(api, "2026-09-01T00:00:00.000Z")
    opening = fx.ops_run(api)
    assert_sweep_counters(opening, rotations_activated=1, bonus_events_opened=1)
    assert_timestamp_equals(opening["clock_utc"], "2026-09-01T00:00:00.000Z")

    activated = validate_success(api.get_rotation(rotation["id"], ADMIN_HEADERS))
    assert activated["status"] == ROTATION_ACTIVE
    assert_timestamp_equals(activated["activated_at"], "2026-09-01T00:00:00.000Z")
    opened = validate_success(api.get_bonus_event(event["id"], ADMIN_HEADERS))
    assert opened["status"] == EVENT_RUNNING
    assert_timestamp_equals(opened["opened_at"], "2026-09-01T00:00:00.000Z")

    fx.set_clock(api, "2026-09-11T00:00:00.000Z")
    closing = fx.ops_run(api)
    assert_sweep_counters(closing, bonus_events_closed=1)
    assert_timestamp_equals(closing["clock_utc"], "2026-09-11T00:00:00.000Z")

    closed = validate_success(api.get_bonus_event(event["id"], ADMIN_HEADERS))
    assert closed["status"] == EVENT_CLOSED
    assert_timestamp_equals(closed["closed_at"], "2026-09-11T00:00:00.000Z")
    still_active = validate_success(api.get_rotation(rotation["id"], ADMIN_HEADERS))
    assert still_active["status"] == ROTATION_ACTIVE
    assert still_active["expired_at"] is None


def test_the_clock_reads_its_declared_default_to_every_role_until_it_is_set(api):
    """
    "Before any client sets it, the clock reads `2026-08-01T00:00:00.000Z`. An
    administrative test-driving capability accepts a `current_utc` instant and moves
    the clock to it; a companion read returns the clock's current `current_utc` value
    to any authenticated role."

    Design: Corner/endpoints/clock_read_returns_the_mandatory_default_before_any_set
    """
    cardholder = make_cardholder_headers("cardholder-unknown-1")

    admin_read = validate_success(api.get_clock(ADMIN_HEADERS))
    assert_timestamp_equals(admin_read["current_utc"], "2026-08-01T00:00:00.000Z")
    cardholder_read = validate_success(api.get_clock(cardholder))
    assert_timestamp_equals(cardholder_read["current_utc"], "2026-08-01T00:00:00.000Z")

    moved = validate_success(
        api.set_clock(f.clock_payload("2026-12-25T06:30:00.000Z"), ADMIN_HEADERS)
    )
    assert_timestamp_equals(moved["current_utc"], "2026-12-25T06:30:00.000Z")

    analyst_read = validate_success(api.get_clock(ANALYST_HEADERS))
    assert_timestamp_equals(analyst_read["current_utc"], "2026-12-25T06:30:00.000Z")


def test_a_cascade_suspended_offer_cannot_be_revived_while_its_agency_is_suspended(api):
    """
    "Reinstatement returns a `SUSPENDED` offer to `OPEN`, clearing `suspension_reason`
    and incrementing `version` by 1; it requires that the offer is currently
    `SUSPENDED`, that the offer's agency is `ACTIVE` (otherwise
    `ERR_AGENCY_SUSPENDED`)"

    Design: Corner/endpoints/reinstating_a_cascade_suspended_offer_under_a_suspended_agency_rejected
    """
    agency, first, supplier = fx.agency_with_offer(
        api,
        ADMIN_HEADERS,
        agency={
            "name": "Northwind Travel",
            "contracted_markup_bps": 2000,
            "parity_tolerance_bps": 1000,
            "invoice_terms_days": 30,
        },
        itinerary_code="LAX-NRT-33",
        depart_at="2026-11-11T11:00:00.000Z",
        return_at="2026-11-25T21:00:00.000Z",
        net_rate_cents=40000,
        agency_public_price_cents=50000,
        agency_public_seats=3,
        portal_seats=2,
        tax_cents=4000,
    )
    second = fx.new_offer(
        api,
        agency["id"],
        supplier,
        itinerary_code="LAX-SYD-34",
        depart_at="2026-11-12T22:00:00.000Z",
        return_at="2026-11-26T06:00:00.000Z",
        net_rate_cents=60000,
        agency_public_price_cents=80000,
        agency_public_seats=4,
        portal_seats=2,
        tax_cents=5000,
    )

    validate_success(
        api.suspend_agency_partner(
            agency["id"], f.suspend_payload("PARITY_AUDIT"), ADMIN_HEADERS
        )
    )

    validate_error(
        api.reinstate_offer(first["id"], {}, ADMIN_HEADERS),
        ERR_AGENCY_SUSPENDED,
        409,
    )

    for offer_id in (first["id"], second["id"]):
        row = fx.read_offer(api, offer_id)
        assert row["status"] == OFFER_SUSPENDED
        assert row["suspension_reason"] == SUSPENSION_AGENCY_SUSPENDED
    parent = validate_success(api.get_agency_partner(agency["id"], ADMIN_HEADERS))
    assert parent["status"] == AGENCY_SUSPENDED
    assert parent["suspended_reason"] == "PARITY_AUDIT"


def test_a_clawback_returns_the_rotation_headroom_the_reversed_purchase_had_used(api):
    """
    "The reversed purchase also leaves the rotation accumulator, because that
    accumulator counts only `POSTED` rows — which means a subsequent purchase against
    the same rotation may now find more headroom than it would have."

    Design: Corner/endpoints/transaction_reversal_clawback_frees_the_rotation_headroom_it_had_consumed
    """
    category = _grocery(api)
    account = fx.new_account(
        api,
        ADMIN_HEADERS,
        cardholder_name="Lior Ben-Ami",
        email="lior@example.com",
        enrolled_at="2025-01-16T00:00:00.000Z",
    )
    rotation = validate_success(
        api.create_rotation(
            f.rotation_payload(
                merchant_category_id=category["id"],
                rotation_code="SEPT-CLAWBACK",
                bonus_multiplier=2.0,
                capped_spend_cents=50000,
                window_start="2026-09-01T00:00:00.000Z",
                window_end="2026-10-01T00:00:00.000Z",
            ),
            ADMIN_HEADERS,
        ),
        201,
    )
    validate_success(api.publish_rotation(rotation["id"], {}, ADMIN_HEADERS))
    fx.set_clock(api, "2026-09-05T00:00:00.000Z")
    assert_sweep_counters(fx.ops_run(api), rotations_activated=1)

    first = fx.post_purchase(
        api,
        account["id"],
        30000,
        headers=ADMIN_HEADERS,
        mcc_code=GROCERY_MCC,
        posted_at="2026-09-05T00:00:00.000Z",
    )
    assert first["base_points"] == 300
    assert first["bonus_points"] == 300
    assert first["total_points_earned"] == 600
    assert first["rotation_id"] == rotation["id"]
    assert first["rotation_eligible_cents"] == 30000

    reversed_row = validate_success(
        api.reverse_transaction(
            first["id"], f.reversal_payload("MERCHANT_CREDIT"), ADMIN_HEADERS
        )
    )
    assert reversed_row["status"] == TRANSACTION_REVERSED
    assert reversed_row["reversal_reason"] == "MERCHANT_CREDIT"

    second = fx.post_purchase(
        api,
        account["id"],
        30000,
        headers=ADMIN_HEADERS,
        mcc_code=GROCERY_MCC,
        posted_at="2026-09-05T00:00:00.000Z",
    )
    assert second["rotation_eligible_cents"] == 30000
    assert second["bonus_points"] == 300
    assert second["total_points_earned"] == 600

    entries = read_ledger(api, ADMIN_HEADERS, account["id"])
    assert len(entries) == 5
    clawbacks = [e for e in entries if e["entry_type"] == ENTRY_CLAWBACK]
    assert len(clawbacks) == 1
    assert_ledger_entry(
        clawbacks[0],
        entry_type=ENTRY_CLAWBACK,
        points_delta=-600,
        balance_after=0,
        source_entity_type=SOURCE_TRANSACTION,
        source_entity_id=first["id"],
    )
    assert_page(
        api.list_ledger_entries(ADMIN_HEADERS, {"account_id": account["id"]}),
        total_count=5,
    )
    assert_account_aggregates(
        fx.read_account(api, account["id"]),
        points_balance=600,
        lifetime_points_earned=1200,
        transfer_hold_count=0,
        fraud_posture=POSTURE_CLEAR,
    )


def test_identifiers_resolve_path_before_body_and_left_to_right_in_the_body(api):
    """
    "**Existence.** Every identifier resolves, path before body, left to right
    (`ERR_RESOURCE_NOT_FOUND`, 404, every endpoint)."

    Design: Corner/errors/unresolvable_path_id_and_body_id_both_not_found
    """
    account = fx.new_account(
        api,
        ADMIN_HEADERS,
        cardholder_name="Kai Lindqvist",
        email="kai@example.com",
        enrolled_at="2025-01-17T00:00:00.000Z",
    )
    cardholder = fx.account_holder(account)
    _, offer, _ = fx.agency_with_offer(
        api,
        ADMIN_HEADERS,
        agency={
            "name": "Bare Fare Consolidators",
            "contracted_markup_bps": 0,
            "parity_tolerance_bps": 0,
        },
        itinerary_code="YYZ-LHR-36",
        depart_at="2026-10-20T21:00:00.000Z",
        return_at="2026-10-28T07:00:00.000Z",
        net_rate_cents=10000,
        agency_public_price_cents=10000,
        agency_public_seats=2,
        portal_seats=2,
        tax_cents=0,
    )

    unknown_path = validate_error(
        api.book_offer(
            BOGUS_OFFER_ID,
            f.book_payload(
                account["id"],
                expected_offer_version=offer["version"],
                traveler_name="Kai Lindqvist",
            ),
            cardholder,
        ),
        ERR_RESOURCE_NOT_FOUND,
        404,
    )
    unknown_account = validate_error(
        api.create_transfer(
            f.transfer_payload(
                BOGUS_ACCOUNT_ID,
                BOGUS_AGREEMENT_ID,
                points_out=1000,
                expected_account_version=account["version"],
            ),
            make_cardholder_headers(BOGUS_ACCOUNT_ID),
        ),
        ERR_RESOURCE_NOT_FOUND,
        404,
    )
    unknown_agreement = validate_error(
        api.create_transfer(
            f.transfer_payload(
                account["id"],
                BOGUS_AGREEMENT_ID,
                points_out=1000,
                expected_account_version=account["version"],
            ),
            cardholder,
        ),
        ERR_RESOURCE_NOT_FOUND,
        404,
    )

    for error_data in (unknown_path, unknown_account, unknown_agreement):
        assert set(error_data) == {"error_id", "message"}
        assert error_data["message"]
    assert_page(
        api.list_transfers(cardholder, {"account_id": account["id"]}),
        total_count=0,
        length=0,
    )
