"""Consistency model: every derived figure is already correct in the response that caused it."""
import pytest

from test_helpers import (
    advisor_deposit,
    api_client,
    confirm_booking,
    create_booking_payload,
    list_client_ledger,
    make_advisor_headers,
    new_client,
    new_split_schedule,
    new_supplier,
    read_advisor,
    read_booking,
    read_client,
    setup_active_advisor,
    validate_success,
)

STANDARD_TIERS = [
    {"tier_level": 1, "min_production_cents": 0, "advisor_pct": 0.70},
    {"tier_level": 2, "min_production_cents": 5_000_000, "advisor_pct": 0.80},
]
FLAT_FEE_TIERS = [{"min_share_cents": 0, "fee_pct": 0.05}]

MERIDIAN = {
    "name": "Meridian Air",
    "accreditation_scheme": "ARC",
    "base_commission_pct": 0.10,
    "preferred_override_commission_pct": 0.12,
    "rate_ceiling_pct": 0.20,
    "max_commission_per_booking_cents": 9_000_000,
    "remit_terms_days": 30,
}


def test_a_write_already_carries_the_totals_a_later_read_will_report():
    """PRD §2.9: "Two conserved quantities must hold at every observable moment. First, a
    client's `trust_balance_cents` always equals the sum of its ledger lines' signed amounts and
    is never negative."
    PRD §3.5: "Submission finally refreshes the advisor's provisional standing:
    `production_ytd_provisional_cents` and `split_tier_provisional` are recomputed as described
    below."

    Design: Corner/consistency model/corner_every_derived_field_is_visible_in_the_same_response
    """
    supplier = new_supplier(**MERIDIAN)
    ctx = setup_active_advisor(
        state="CA",
        legal_name="Priya Nair",
        email="priya.nair@example.com",
        schedule=new_split_schedule(
            name="Standard 2026",
            tiers=STANDARD_TIERS,
            platform_fee_tiers=FLAT_FEE_TIERS,
            chargeback_retention_pct=0.10,
        ),
        suppliers=[supplier],
    )
    advisor = ctx["advisor"]
    assert advisor["trust_account_required"] is True
    assert read_advisor(advisor["id"])["production_ytd_provisional_cents"] == 0

    client = new_client(
        advisor["id"],
        full_name="Marta Vidal",
        home_state_code="CA",
        max_concurrent_trips=4,
    )
    assert client["trust_balance_cents"] == 0

    funded = advisor_deposit(
        client["id"], advisor["id"], 300_000, memo="Trip funding wire"
    )
    assert funded["balance_after_cents"] == 300_000
    assert read_client(client["id"])["trust_balance_cents"] == 300_000

    booking = validate_success(
        api_client.create_booking(
            create_booking_payload(
                advisor["id"],
                supplier["id"],
                client["id"],
                channel="SUPPLIER_DIRECT",
                payment_method="CLIENT_TRUST",
                gross_sale_cents=1_000_000,
                deposit_amount_cents=250_000,
                travel_start_date="2026-10-01",
                travel_end_date="2026-10-10",
            ),
            make_advisor_headers(advisor["id"]),
        ),
        201,
    )
    assert booking["expected_commission_cents"] == 100_000
    assert booking["applied_commission_rate"] == pytest.approx(0.10)
    assert booking["commission_status"] == "PENDING"

    read_back = read_booking(booking["id"])
    assert read_back["expected_commission_cents"] == booking["expected_commission_cents"]
    assert read_back["applied_commission_rate"] == pytest.approx(
        booking["applied_commission_rate"]
    )
    assert read_advisor(advisor["id"])["production_ytd_provisional_cents"] == 100_000
    assert read_advisor(advisor["id"])["split_tier_provisional"] == 1

    confirmed = confirm_booking(booking["id"], supplier["id"])
    assert confirmed["commission_status"] == "EXPECTED"
    assert read_client(client["id"])["trust_balance_cents"] == 50_000

    lines = list_client_ledger(client["id"])
    assert len(lines) == 2
    assert [line["direction"] for line in lines] == ["DEPOSIT", "DISBURSEMENT"]
    assert [line["signed_amount_cents"] for line in lines] == [300_000, -250_000]
    assert [line["balance_after_cents"] for line in lines] == [300_000, 50_000]
    assert lines[0]["booking_id"] is None
    assert lines[1]["booking_id"] == booking["id"]
    assert lines[1]["recorded_by_user_id"] == supplier["id"]
