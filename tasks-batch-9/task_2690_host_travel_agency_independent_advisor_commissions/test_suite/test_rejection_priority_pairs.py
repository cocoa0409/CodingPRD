"""Where two rejection conditions hold at once, only the higher band is reported."""
from test_helpers import (
    advisor_bookings,
    api_client,
    create_booking_payload,
    make_advisor_headers,
    new_booking,
    new_client,
    new_consortium,
    new_split_schedule,
    new_supplier,
    read_advisor,
    read_booking,
    setup_active_advisor,
    suspend_advisor,
    validate_error,
)

STANDARD_TIERS = [
    {"tier_level": 1, "min_production_cents": 0, "advisor_pct": 0.70},
    {"tier_level": 2, "min_production_cents": 5_000_000, "advisor_pct": 0.80},
]
FLAT_FEE_TIERS = [{"min_share_cents": 0, "fee_pct": 0.05}]


def _preferred_cruise_line():
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
        probation_chargeback_threshold=5,
    )
    return schedule, consortium, aurora


def _suspended_unaccredited_advisor():
    """A suspended advisor who never held an accreditation with the supplier."""
    schedule, consortium, aurora = _preferred_cruise_line()
    ctx = setup_active_advisor(
        state="NY",
        legal_name="Dana Reyes",
        email="dana.reyes@example.com",
        consortium_id=consortium["id"],
        schedule=schedule,
        suppliers=(),
    )
    client = new_client(
        ctx["advisor"]["id"],
        full_name="Nadia Okoye",
        home_state_code="NY",
        max_concurrent_trips=4,
    )
    suspend_advisor(ctx["advisor"]["id"], "Documentation audit in progress")
    return {"advisor": ctx["advisor"], "client": client, "aurora": aurora}


def _submission_attempt(scenario, **overrides):
    fields = {
        "channel": "CONSORTIUM",
        "payment_method": "MERCHANT_DIRECT",
        "gross_sale_cents": 1_000_000,
        "travel_start_date": "2026-10-01",
        "travel_end_date": "2026-10-10",
    }
    fields.update(overrides)
    payload = create_booking_payload(
        scenario["advisor"]["id"],
        scenario["aurora"]["id"],
        scenario["client"]["id"],
        **fields,
    )
    return api_client.create_booking(
        payload, make_advisor_headers(scenario["advisor"]["id"])
    )


def test_suspension_is_reported_ahead_of_the_missing_supplier_accreditation():
    """PRD §2.8: "8. **Own-state validity** — HTTP 409. The target row must be in a
    state from which the requested transition is declared. This band covers
    `ERR_ADVISOR_NOT_ACTIVE` and `ERR_INVALID_ADVISOR_STATE`,
    `ERR_INVALID_BOOKING_STATE`, `ERR_INVALID_COMMISSION_STATE`,
    `ERR_INVALID_CLAIM_STATE`, `ERR_INVALID_RUN_STATE`,
    `ERR_INVALID_CREDENTIAL_STATE` and `ERR_INVALID_STATEMENT_STATE`, and it applies to
    every state-transition endpoint plus booking submission and client registration."

    Design: Difficulty/priority_pair_validation_conflict/suspended_advisor_beats_missing_supplier_accreditation
    """
    scenario = _suspended_unaccredited_advisor()

    error = validate_error(
        _submission_attempt(scenario), "ERR_ADVISOR_NOT_ACTIVE", 409
    )

    assert error["error_id"] != "ERR_SUPPLIER_ACCREDITATION_MISSING"
    assert read_advisor(scenario["advisor"]["id"])["status"] == "SUSPENDED"


def test_the_refused_submission_leaves_the_advisor_untouched():
    """PRD §2.8: "A rejected request has no effect whatsoever: no row is created, no
    counter moves, no `version` increments."

    Design: Difficulty/priority_pair_validation_conflict/suspended_advisor_beats_missing_supplier_accreditation
    """
    scenario = _suspended_unaccredited_advisor()
    before = read_advisor(scenario["advisor"]["id"])

    validate_error(_submission_attempt(scenario), "ERR_ADVISOR_NOT_ACTIVE", 409)

    after = read_advisor(scenario["advisor"]["id"])
    assert after["production_ytd_provisional_cents"] == 0
    assert after["version"] == before["version"]
    assert advisor_bookings(scenario["advisor"]["id"]) == []


def _trust_state_advisor_at_capacity():
    """A California advisor whose only client already has its single trip booked."""
    schedule, consortium, aurora = _preferred_cruise_line()
    ctx = setup_active_advisor(
        state="CA",
        legal_name="Priya Nair",
        email="priya.nair@example.com",
        consortium_id=consortium["id"],
        schedule=schedule,
        suppliers=[aurora],
    )
    advisor = ctx["advisor"]
    client = new_client(
        advisor["id"],
        full_name="Marco Vidal",
        home_state_code="CA",
        ownership_mode="ADVISOR_OWNED",
        max_concurrent_trips=1,
    )
    booking = new_booking(
        advisor["id"],
        aurora["id"],
        client["id"],
        channel="CONSORTIUM",
        payment_method="CLIENT_TRUST",
        gross_sale_cents=1_000_000,
        deposit_amount_cents=50_000,
        travel_start_date="2026-10-01",
        travel_end_date="2026-10-10",
    )
    return {"advisor": advisor, "client": client, "aurora": aurora, "booking": booking}


def test_the_trust_regime_check_is_reported_ahead_of_the_travel_window_conflict():
    """PRD §2.8: "10. **Compliance gates**, in this internal order: seller-of-travel
    validity (`ERR_SELLER_OF_TRAVEL_INVALID`, 422) on `POST /bookings`,
    `POST /advisors/{id}/activate` and `POST /advisors/{id}/reinstate`; then E&O
    sufficiency (`ERR_EO_COVERAGE_INSUFFICIENT`, 422) on
    `POST /advisors/{id}/activate`, `POST /advisors/{id}/reinstate` and
    `POST /bookings`; then training certification (`ERR_TRAINING_CERT_MISSING`, 422) on
    `POST /advisors/{id}/activate`; then the payment-processing regime check
    (`ERR_TRUST_ACCOUNT_REQUIRED` or `ERR_TRUST_ACCOUNT_NOT_PERMITTED`, 422) on
    `POST /bookings`."

    Design: Difficulty/priority_pair_validation_conflict/trust_account_required_beats_travel_window_conflict
    """
    scenario = _trust_state_advisor_at_capacity()

    error = validate_error(
        _submission_attempt(
            scenario,
            payment_method="MERCHANT_DIRECT",
            gross_sale_cents=700_000,
            travel_start_date="2026-10-05",
            travel_end_date="2026-10-15",
        ),
        "ERR_TRUST_ACCOUNT_REQUIRED",
        422,
    )

    assert error["error_id"] != "ERR_TRAVEL_WINDOW_CONFLICT"
    assert read_advisor(scenario["advisor"]["id"])["trust_account_required"] is True


def test_the_overlapping_booking_is_not_stored_when_the_regime_check_fails():
    """PRD §3.5: "The payment-processing regime must match the advisor's obligation:
    when `trust_account_required` is true the `payment_method` must be `CLIENT_TRUST`
    and anything else is refused with `ERR_TRUST_ACCOUNT_REQUIRED`, while when
    `trust_account_required` is false the `payment_method` must be either
    `MERCHANT_DIRECT` or `HOST_MERCHANT` and a `CLIENT_TRUST` booking is refused with
    `ERR_TRUST_ACCOUNT_NOT_PERMITTED`."

    Design: Difficulty/priority_pair_validation_conflict/trust_account_required_beats_travel_window_conflict
    """
    scenario = _trust_state_advisor_at_capacity()

    validate_error(
        _submission_attempt(
            scenario,
            payment_method="MERCHANT_DIRECT",
            gross_sale_cents=700_000,
            travel_start_date="2026-10-05",
            travel_end_date="2026-10-15",
        ),
        "ERR_TRUST_ACCOUNT_REQUIRED",
        422,
    )

    assert read_booking(scenario["booking"]["id"])["booking_status"] == "SUBMITTED"
    assert len(advisor_bookings(scenario["advisor"]["id"])) == 1
    assert read_advisor(scenario["advisor"]["id"])["production_ytd_provisional_cents"] == 160_000
