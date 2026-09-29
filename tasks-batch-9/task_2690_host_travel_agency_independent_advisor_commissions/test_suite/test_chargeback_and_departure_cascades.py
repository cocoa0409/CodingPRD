"""The two named cascades, link by link."""
import pytest

from test_helpers import (
    api_client,
    calculate_run,
    cancel_booking_payload,
    compliance,
    confirm_booking,
    declare_departure,
    make_advisor_headers,
    new_booking,
    new_client,
    new_consortium,
    new_split_schedule,
    new_supplier,
    open_run,
    post_run,
    read_advisor,
    read_agreement,
    read_booking,
    read_client,
    read_supplier,
    record_receipt,
    set_clock,
    setup_active_advisor,
    validate_success,
)

REMIT_CLOCK = "2026-10-05T00:00:00Z"
REMIT_DATE = "2026-10-05"
REMIT_PERIOD = "2026-10"

STANDARD_TIERS = [
    {"tier_level": 1, "min_production_cents": 0, "advisor_pct": 0.70},
    {"tier_level": 2, "min_production_cents": 5_000_000, "advisor_pct": 0.80},
]
FLAT_FEE_TIERS = [{"min_share_cents": 0, "fee_pct": 0.05}]


def _preferred_pair(probation_chargeback_threshold):
    schedule = new_split_schedule(
        name="Standard 2026",
        tiers=STANDARD_TIERS,
        platform_fee_tiers=FLAT_FEE_TIERS,
        chargeback_retention_pct=0.10,
    )
    consortium = new_consortium(
        name="Voyager Alliance",
        membership_fee_cents=5_000_000,
        marketing_fund_accrual_pct=0.02,
        consortium_channel_bonus_pct=0.01,
    )
    aurora = new_supplier(
        name="Aurora Cruises",
        accreditation_scheme="CLIA",
        base_commission_pct=0.10,
        preferred_override_commission_pct=0.15,
        rate_ceiling_pct=0.18,
        max_commission_per_booking_cents=500_000,
        remit_terms_days=30,
        consortium_id=consortium["id"],
        program_status="PREFERRED",
        probation_chargeback_threshold=probation_chargeback_threshold,
    )
    return schedule, consortium, aurora


def _settled_booking_plus_pending_booking():
    """One collected and settled cruise, plus one still-pending cruise to reprice."""
    schedule, consortium, aurora = _preferred_pair(1)
    ctx = setup_active_advisor(
        state="NY",
        legal_name="Dana Reyes",
        email="dana.reyes@example.com",
        consortium_id=consortium["id"],
        schedule=schedule,
        suppliers=[aurora],
    )
    advisor = ctx["advisor"]
    client = new_client(
        advisor["id"],
        full_name="Nadia Okoye",
        home_state_code="NY",
        max_concurrent_trips=4,
    )
    settled = new_booking(
        advisor["id"],
        aurora["id"],
        client["id"],
        channel="CONSORTIUM",
        payment_method="MERCHANT_DIRECT",
        gross_sale_cents=1_000_000,
        travel_start_date="2026-06-01",
        travel_end_date="2026-06-10",
    )
    settled = confirm_booking(settled["id"], aurora["id"])
    pending = new_booking(
        advisor["id"],
        aurora["id"],
        client["id"],
        channel="CONSORTIUM",
        payment_method="MERCHANT_DIRECT",
        gross_sale_cents=2_000_000,
        travel_start_date="2026-09-01",
        travel_end_date="2026-09-10",
    )
    set_clock(REMIT_CLOCK)
    record_receipt(settled["id"], aurora["id"], 160_000, REMIT_DATE)
    run = open_run(REMIT_PERIOD)
    calculate_run(run["id"], "ctrl-1")
    post_run(run["id"], "ctrl-2")
    return {
        "advisor": advisor,
        "client": client,
        "aurora": aurora,
        "settled": read_booking(settled["id"]),
        "pending": read_booking(pending["id"]),
    }


def test_charging_back_a_settled_booking_demotes_the_preferred_supplier():
    """PRD §3.6: "*Link two*, caused by link one, recomputes the supplier's
    `chargeback_count` as the number of its bookings now sitting in `CHARGED_BACK`;
    when that count reaches or exceeds the supplier's
    `probation_chargeback_threshold`, a supplier in `PREFERRED` standing is demoted to
    `PROBATION` and `Supplier.version` increments by 1."

    Design: Difficulty/transitive_cascade/chargeback_demotes_supplier_reprices_pending_and_moves_tier_basis
    """
    scenario = _settled_booking_plus_pending_booking()

    cancelled = validate_success(
        api_client.cancel_booking(
            scenario["settled"]["id"],
            cancel_booking_payload("CLIENT_INITIATED"),
            make_advisor_headers(scenario["advisor"]["id"]),
        )
    )

    assert cancelled["booking_status"] == "CANCELLED"
    assert cancelled["commission_status"] == "CHARGED_BACK"
    assert cancelled["chargeback_amount_cents"] == 112_000
    assert cancelled["chargeback_recognized_at"] is None

    supplier = read_supplier(scenario["aurora"]["id"])
    assert supplier["chargeback_count"] == 1
    assert supplier["program_status"] == "PROBATION"


def test_demotion_reprices_pending_bookings_and_moves_the_provisional_basis():
    """PRD §3.6: "*Link three*, caused specifically by link two's change of
    `program_status` and therefore not firing at all when the threshold was not
    crossed, reprices every booking of that supplier still sitting in
    `commission_status` `PENDING`: each such booking has `applied_commission_rate` and
    `expected_commission_cents` recomputed by the four-step pricing rule, and since a
    `PROBATION` supplier no longer grants `preferred_override_commission_pct` those
    bookings drop to `base_commission_pct`, with `Booking.version` incrementing on
    every row touched."

    Design: Difficulty/transitive_cascade/chargeback_demotes_supplier_reprices_pending_and_moves_tier_basis
    """
    scenario = _settled_booking_plus_pending_booking()
    assert scenario["pending"]["expected_commission_cents"] == 320_000

    validate_success(
        api_client.cancel_booking(
            scenario["settled"]["id"],
            cancel_booking_payload("CLIENT_INITIATED"),
            make_advisor_headers(scenario["advisor"]["id"]),
        )
    )

    repriced = read_booking(scenario["pending"]["id"])
    assert repriced["applied_commission_rate"] == pytest.approx(0.11)
    assert repriced["expected_commission_cents"] == 220_000
    assert repriced["commission_status"] == "PENDING"

    advisor = read_advisor(scenario["advisor"]["id"])
    assert advisor["production_ytd_provisional_cents"] == 220_000
    assert advisor["split_tier_provisional"] == 1


def _armed_departure():
    """A co-member advisor holding one host-owned and one advisor-owned client,
    with a departure armed toward a successor who joined no consortium."""
    schedule, consortium, aurora = _preferred_pair(5)
    departing_ctx = setup_active_advisor(
        state="NY",
        legal_name="Dana Reyes",
        email="dana.reyes@example.com",
        consortium_id=consortium["id"],
        schedule=schedule,
        suppliers=[aurora],
        number_prefix="A",
        agreement_overrides={"effective_date": "2026-01-01", "post_departure_advisor_pct": 0.50},
    )
    successor_ctx = setup_active_advisor(
        state="NY",
        legal_name="Sam Ortega",
        email="sam.ortega@example.com",
        schedule=schedule,
        suppliers=[aurora],
        number_prefix="S",
        agreement_overrides={"effective_date": "2026-02-01", "post_departure_advisor_pct": 0.50},
    )
    departing, successor = departing_ctx["advisor"], successor_ctx["advisor"]
    host_client = new_client(
        departing["id"],
        full_name="Host Book Client",
        home_state_code="NY",
        ownership_mode="HOST_OWNED",
        max_concurrent_trips=4,
    )
    own_client = new_client(
        departing["id"],
        full_name="Own Book Client",
        home_state_code="NY",
        ownership_mode="ADVISOR_OWNED",
        max_concurrent_trips=4,
    )
    host_booking = new_booking(
        departing["id"],
        aurora["id"],
        host_client["id"],
        channel="CONSORTIUM",
        payment_method="MERCHANT_DIRECT",
        gross_sale_cents=1_000_000,
        travel_start_date="2026-10-01",
        travel_end_date="2026-10-10",
    )
    own_booking = new_booking(
        departing["id"],
        aurora["id"],
        own_client["id"],
        channel="CONSORTIUM",
        payment_method="MERCHANT_DIRECT",
        gross_sale_cents=2_000_000,
        travel_start_date="2026-10-01",
        travel_end_date="2026-10-10",
    )
    declare_departure(departing["id"], successor["id"], "2026-09-01")
    return {
        "departing": departing,
        "departing_agreement": departing_ctx["agreement"],
        "successor": successor,
        "successor_agreement": successor_ctx["agreement"],
        "host_client": host_client,
        "own_client": own_client,
        "host_booking": host_booking,
        "own_booking": own_booking,
    }


def test_finalization_terminates_the_agreement_and_splits_the_book_by_ownership():
    """PRD §3.9: "*Link two*, caused by the departing advisor now having no `ACTIVE`
    agreement, re-homes that advisor's clients: a client whose `ownership_mode` is
    `HOST_OWNED` has its `owner_advisor_id` reassigned to the successor while its
    `portability_status` stays `RETAINED`, whereas a client whose `ownership_mode` is
    `ADVISOR_OWNED` keeps its `owner_advisor_id` and instead has `portability_status`
    set to `RELEASED` — the advisor keeps the relationship they own, the host keeps the
    ones it owns."

    Design: Difficulty/transitive_cascade/departure_finalize_rehomes_clients_transfers_and_reprices_bookings
    """
    scenario = _armed_departure()

    departed = validate_success(
        api_client.finalize_departure(scenario["departing"]["id"], compliance())
    )

    assert departed["status"] == "DEPARTED"
    assert read_agreement(scenario["departing_agreement"]["id"])["status"] == "TERMINATED"

    host_client = read_client(scenario["host_client"]["id"])
    assert host_client["owner_advisor_id"] == scenario["successor"]["id"]
    assert host_client["portability_status"] == "RETAINED"

    own_client = read_client(scenario["own_client"]["id"])
    assert own_client["owner_advisor_id"] == scenario["departing"]["id"]
    assert own_client["portability_status"] == "RELEASED"


def test_transferred_bookings_are_repriced_in_the_successor_consortium_context():
    """PRD §3.9: "*Link three*, caused by link two and firing only for those clients
    whose `owner_advisor_id` actually changed, moves the in-flight work: every booking
    of such a client whose `booking_status` is `SUBMITTED` or `CONFIRMED` has its
    `advisor_id` set to the successor and its `agreement_id` re-pinned to the
    successor's `ACTIVE` agreement, and among those, any whose `commission_status` is
    still `PENDING` has `applied_commission_rate` and `expected_commission_cents`
    recomputed by the four-step pricing rule under the successor's consortium context —
    which can raise or lower the expected commission, since co-membership with the
    supplier's consortium may now hold where it did not before, or vice versa."

    Design: Difficulty/transitive_cascade/departure_finalize_rehomes_clients_transfers_and_reprices_bookings
    """
    scenario = _armed_departure()

    validate_success(api_client.finalize_departure(scenario["departing"]["id"], compliance()))

    transferred = read_booking(scenario["host_booking"]["id"])
    assert transferred["advisor_id"] == scenario["successor"]["id"]
    assert transferred["agreement_id"] == scenario["successor_agreement"]["id"]
    assert transferred["applied_commission_rate"] == pytest.approx(0.10)
    assert transferred["expected_commission_cents"] == 100_000

    retained = read_booking(scenario["own_booking"]["id"])
    assert retained["advisor_id"] == scenario["departing"]["id"]
    assert retained["expected_commission_cents"] == 320_000

    assert read_advisor(scenario["departing"]["id"])["production_ytd_provisional_cents"] == 320_000
    successor = read_advisor(scenario["successor"]["id"])
    assert successor["production_ytd_provisional_cents"] == 100_000
    assert successor["split_tier_provisional"] == 1
