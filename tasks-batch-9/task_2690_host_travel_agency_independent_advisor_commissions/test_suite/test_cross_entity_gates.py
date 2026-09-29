"""Gates that read a second entity's state: a lapsed registration, an empty trust
balance."""
import pytest

from test_helpers import (
    advisor_credentials,
    advisor_deposit,
    api_client,
    confirm_booking,
    create_booking_payload,
    decide_credential,
    file_credential,
    list_booking_ledger,
    make_advisor_headers,
    make_supplier_portal_headers,
    new_booking,
    new_client,
    new_split_schedule,
    new_supplier,
    read_advisor,
    read_booking,
    read_client,
    read_credential,
    seller_of_travel_credential_payload,
    set_clock,
    setup_active_advisor,
    validate_error,
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


def _standard_schedule():
    return new_split_schedule(
        name="Standard 2026",
        tiers=STANDARD_TIERS,
        platform_fee_tiers=FLAT_FEE_TIERS,
        chargeback_retention_pct=0.10,
    )


def _advisor_whose_registration_lapses():
    """An active New York advisor whose registration runs out on 2026-08-31."""
    supplier = new_supplier(**MERIDIAN)
    ctx = setup_active_advisor(
        state="NY",
        legal_name="Dana Reyes",
        email="dana.reyes@example.com",
        schedule=_standard_schedule(),
        suppliers=[supplier],
        sot_expires_on="2026-08-31",
    )
    client = new_client(
        ctx["advisor"]["id"],
        full_name="Nadia Okoye",
        home_state_code="NY",
        max_concurrent_trips=4,
    )
    return {
        "advisor": ctx["advisor"],
        "registration": ctx["credentials"]["seller_of_travel"],
        "client": client,
        "supplier": supplier,
    }


def _submission_payload(scenario):
    return create_booking_payload(
        scenario["advisor"]["id"],
        scenario["supplier"]["id"],
        scenario["client"]["id"],
        channel="SUPPLIER_DIRECT",
        payment_method="MERCHANT_DIRECT",
        gross_sale_cents=1_000_000,
        travel_start_date="2026-10-01",
        travel_end_date="2026-10-10",
    )


def test_a_registration_lapsed_by_the_clock_closes_the_submission_gate():
    """PRD §3.3: "Whenever the logical clock is advanced, every credential in status
    `VERIFIED` whose `expires_on` is at or before the new clock value moves to `EXPIRED`,
    its `version` increments, and — for E&O rows — the owning advisor's
    `eo_coverage_verified_cents` is recomputed."

    Design: Difficulty/cross_entity_state_dependency/booking_submission_gated_on_credential_status_expired_by_clock
    """
    scenario = _advisor_whose_registration_lapses()

    moved = set_clock("2026-09-01T00:00:00Z")
    assert moved["expired_credential_count"] == 1
    assert read_credential(scenario["registration"]["id"])["status"] == "EXPIRED"

    validate_error(
        api_client.create_booking(
            _submission_payload(scenario),
            make_advisor_headers(scenario["advisor"]["id"]),
        ),
        "ERR_SELLER_OF_TRAVEL_INVALID",
        422,
    )

    assert read_advisor(scenario["advisor"]["id"])["status"] == "ACTIVE"
    assert read_advisor(scenario["advisor"]["id"])["production_ytd_provisional_cents"] == 0


def test_a_replacement_registration_reopens_the_submission_gate():
    """PRD §3.5: "The advisor must hold an in-force verified state registration matching
    its own `seller_of_travel_state`, failing which `ERR_SELLER_OF_TRAVEL_INVALID`, and an
    in-force verified E&O policy at or above one hundred million cents of cover, failing
    which `ERR_EO_COVERAGE_INSUFFICIENT`."

    Design: Difficulty/cross_entity_state_dependency/booking_submission_gated_on_credential_status_expired_by_clock
    """
    scenario = _advisor_whose_registration_lapses()
    advisor_id = scenario["advisor"]["id"]
    set_clock("2026-09-01T00:00:00Z")

    replacement = file_credential(
        advisor_id,
        seller_of_travel_credential_payload(
            jurisdiction_state_code="NY",
            credential_number="NY-SOT-40119",
            effective_on="2026-09-01",
            expires_on="2027-09-01",
        ),
    )
    assert decide_credential(replacement["id"], "VERIFY")["status"] == "VERIFIED"

    booking = validate_success(
        api_client.create_booking(
            _submission_payload(scenario), make_advisor_headers(advisor_id)
        ),
        201,
    )

    assert booking["applied_commission_rate"] == pytest.approx(0.10)
    assert booking["expected_commission_cents"] == 100_000
    assert read_advisor(advisor_id)["production_ytd_provisional_cents"] == 100_000

    rows = advisor_credentials(advisor_id)
    assert len(rows) == 5
    assert len([row for row in rows if row["status"] == "EXPIRED"]) == 1


def _trust_booking_with_an_empty_trust_account():
    """A California advisor's trust booking whose client has funded nothing yet."""
    supplier = new_supplier(**MERIDIAN)
    ctx = setup_active_advisor(
        state="CA",
        legal_name="Priya Nair",
        email="priya.nair@example.com",
        schedule=_standard_schedule(),
        suppliers=[supplier],
    )
    advisor = ctx["advisor"]
    client = new_client(
        advisor["id"],
        full_name="Marco Vidal",
        home_state_code="CA",
        max_concurrent_trips=4,
    )
    booking = new_booking(
        advisor["id"],
        supplier["id"],
        client["id"],
        channel="SUPPLIER_DIRECT",
        payment_method="CLIENT_TRUST",
        gross_sale_cents=2_000_000,
        deposit_amount_cents=100_000,
        travel_start_date="2026-10-01",
        travel_end_date="2026-10-10",
    )
    return {
        "advisor": advisor,
        "client": client,
        "supplier": supplier,
        "booking": booking,
    }


def test_confirmation_is_refused_while_the_client_trust_balance_is_short():
    """PRD §3.6: "Three preconditions apply beyond the state itself: the acting
    supplier's `X-User-ID` must equal the booking's `supplier_id`, or the request is
    refused with `ERR_OWNERSHIP_VIOLATION`; the booking's advisor must be in `ACTIVE`,
    `SUSPENDED` or `DEPARTING` status, so a booking whose advisor has reached `DEPARTED`
    or is somehow still `DRAFT` cannot be confirmed and reports `ERR_ADVISOR_NOT_ACTIVE`;
    and where the booking's `payment_method` is `CLIENT_TRUST`, the client's
    `trust_balance_cents` must already be at least the booking's `deposit_amount_cents`,
    failing which the confirmation is refused with `ERR_TRUST_DEPOSIT_SHORTFALL`
    (HTTP 402)."

    Design: Difficulty/cross_entity_state_dependency/booking_confirm_gated_on_client_trust_balance
    """
    scenario = _trust_booking_with_an_empty_trust_account()
    assert read_client(scenario["client"]["id"])["trust_balance_cents"] == 0

    validate_error(
        api_client.confirm_booking(
            scenario["booking"]["id"],
            make_supplier_portal_headers(scenario["supplier"]["id"]),
        ),
        "ERR_TRUST_DEPOSIT_SHORTFALL",
        402,
    )

    refused = read_booking(scenario["booking"]["id"])
    assert refused["booking_status"] == "SUBMITTED"
    assert refused["commission_status"] == "PENDING"
    assert list_booking_ledger(scenario["booking"]["id"]) == []


def test_a_funded_trust_account_lets_confirmation_sweep_the_deposit():
    """PRD §3.6: "Where the `payment_method` is `CLIENT_TRUST`, confirmation additionally
    sweeps the deposit out of trust automatically: a ledger line is appended with
    `direction` `DISBURSEMENT`, `amount_cents` equal to the booking's
    `deposit_amount_cents`, `booking_id` set to this booking and `recorded_by_user_id` set
    to the acting supplier, after which the client's `trust_balance_cents` is recomputed
    and `Client.version` increments by 1."

    Design: Difficulty/cross_entity_state_dependency/booking_confirm_gated_on_client_trust_balance
    """
    scenario = _trust_booking_with_an_empty_trust_account()

    deposit = advisor_deposit(
        scenario["client"]["id"],
        scenario["advisor"]["id"],
        100_000,
        memo="Client wire for cruise deposit",
    )
    assert deposit["balance_after_cents"] == 100_000

    confirmed = confirm_booking(scenario["booking"]["id"], scenario["supplier"]["id"])
    assert confirmed["booking_status"] == "CONFIRMED"
    assert confirmed["commission_status"] == "EXPECTED"
    assert confirmed["expected_commission_cents"] == 200_000

    lines = list_booking_ledger(scenario["booking"]["id"])
    assert len(lines) == 1
    assert lines[0]["direction"] == "DISBURSEMENT"
    assert lines[0]["amount_cents"] == 100_000
    assert read_client(scenario["client"]["id"])["trust_balance_cents"] == 0
