"""The two cycles that are not simple ladders: claim negotiation rounds and the
suspend/reinstate loop that is re-gated on fresh compliance."""
from test_helpers import (
    advisor_credentials,
    api_client,
    compliance,
    confirm_booking,
    decide_credential,
    deny_claim,
    file_credential,
    file_claim,
    make_advisor_headers,
    mark_traveled,
    new_booking,
    new_client,
    new_consortium,
    new_split_schedule,
    new_supplier,
    read_advisor,
    read_booking,
    read_claim,
    read_credential,
    resubmit_claim,
    seller_of_travel_credential_payload,
    setup_active_advisor,
    validate_error,
    validate_success,
)

STANDARD_TIERS = [
    {"tier_level": 1, "min_production_cents": 0, "advisor_pct": 0.70},
    {"tier_level": 2, "min_production_cents": 5_000_000, "advisor_pct": 0.80},
]
FLAT_FEE_TIERS = [{"min_share_cents": 0, "fee_pct": 0.05}]


def _co_member_scenario():
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
    ctx = setup_active_advisor(
        state="NY",
        legal_name="Dana Reyes",
        email="dana.reyes@example.com",
        consortium_id=consortium["id"],
        schedule=schedule,
        suppliers=[aurora],
    )
    client = new_client(
        ctx["advisor"]["id"],
        full_name="Nadia Okoye",
        home_state_code="NY",
        max_concurrent_trips=4,
    )
    ctx["client"] = client
    ctx["aurora"] = aurora
    ctx["consortium"] = consortium
    return ctx


def _unpaid_claim():
    """An uncollected travelled booking whose advisor has filed a claim."""
    ctx = _co_member_scenario()
    booking = new_booking(
        ctx["advisor"]["id"],
        ctx["aurora"]["id"],
        ctx["client"]["id"],
        channel="CONSORTIUM",
        payment_method="MERCHANT_DIRECT",
        gross_sale_cents=1_000_000,
        travel_start_date="2026-06-01",
        travel_end_date="2026-06-10",
    )
    booking = confirm_booking(booking["id"], ctx["aurora"]["id"])
    booking = mark_traveled(booking["id"])
    claim = file_claim(booking["id"], ctx["advisor"]["id"], 160_000)
    ctx["booking"] = booking
    ctx["claim"] = claim
    return ctx


def test_resubmission_increments_the_round_count_and_clears_the_denial_reason():
    """PRD §3.7: "The advisor may then resubmit, optionally with a `note`, moving
    `DENIED` back to `SUBMITTED` and incrementing `round_count` by 1 while
    `denial_reason` is cleared."

    Design: Difficulty/non_linear_state_machine/claim_deny_resubmit_cycle_blocked_at_third_round
    """
    ctx = _unpaid_claim()
    claim_id = ctx["claim"]["id"]
    assert ctx["claim"]["round_count"] == 1
    assert ctx["claim"]["status"] == "SUBMITTED"

    denied = deny_claim(claim_id, ctx["aurora"]["id"], "Missing supplier confirmation number")
    assert denied["status"] == "DENIED"
    assert denied["denial_reason"] == "Missing supplier confirmation number"
    assert denied["round_count"] == 1

    second = resubmit_claim(claim_id, ctx["advisor"]["id"], note="Confirmation number attached")
    assert second["status"] == "SUBMITTED"
    assert second["round_count"] == 2
    assert second["denial_reason"] is None

    deny_claim(claim_id, ctx["aurora"]["id"], "Amount disputed")
    third = resubmit_claim(claim_id, ctx["advisor"]["id"], note="Invoice attached")
    assert third["status"] == "SUBMITTED"
    assert third["round_count"] == 3


def test_a_fourth_negotiation_round_is_refused_once_three_have_been_used():
    """PRD §3.7: "The cycle is capped: resubmission is permitted only while
    `round_count` is still below three, and a fourth attempt is refused with
    `ERR_CLAIM_ROUND_LIMIT`."

    Design: Difficulty/non_linear_state_machine/claim_deny_resubmit_cycle_blocked_at_third_round
    """
    ctx = _unpaid_claim()
    claim_id = ctx["claim"]["id"]
    deny_claim(claim_id, ctx["aurora"]["id"], "Missing supplier confirmation number")
    resubmit_claim(claim_id, ctx["advisor"]["id"], note="Confirmation number attached")
    deny_claim(claim_id, ctx["aurora"]["id"], "Amount disputed")
    resubmit_claim(claim_id, ctx["advisor"]["id"], note="Invoice attached")
    deny_claim(claim_id, ctx["aurora"]["id"], "Final refusal")

    validate_error(
        api_client.resubmit_commission_claim(
            claim_id,
            make_advisor_headers(ctx["advisor"]["id"]),
            {"note": "Third attempt"},
        ),
        "ERR_CLAIM_ROUND_LIMIT",
        409,
    )

    blocked = read_claim(claim_id)
    assert blocked["status"] == "DENIED"
    assert blocked["round_count"] == 3
    assert read_booking(ctx["booking"]["id"])["commission_status"] == "CLAIMED"


def _suspended_by_revocation():
    """An advisor the system suspended when its last registration was revoked."""
    ctx = _co_member_scenario()
    registration = ctx["credentials"]["seller_of_travel"]
    decide_credential(registration["id"], "REVOKE", note="State registration lapsed")
    ctx["registration"] = registration
    return ctx


def test_reinstatement_is_refused_while_no_registration_is_in_force():
    """PRD §3.2: "Reinstatement runs the other way, from `SUSPENDED` back to `ACTIVE`,
    and it re-verifies compliance against the *current* clock rather than trusting the
    state the advisor had when it was suspended: an in-force verified
    `SELLER_OF_TRAVEL` registration matching the home state and an in-force verified
    `EO_POLICY` at or above the one-million-dollar floor must both be present, reported
    as `ERR_SELLER_OF_TRAVEL_INVALID` and `ERR_EO_COVERAGE_INSUFFICIENT` respectively."

    Design: Difficulty/non_linear_state_machine/advisor_suspend_reinstate_cycle_regated_on_fresh_registration
    """
    ctx = _suspended_by_revocation()
    advisor_id = ctx["advisor"]["id"]
    assert read_advisor(advisor_id)["status"] == "SUSPENDED"

    validate_error(
        api_client.reinstate_advisor(advisor_id, compliance()),
        "ERR_SELLER_OF_TRAVEL_INVALID",
        422,
    )

    assert read_advisor(advisor_id)["status"] == "SUSPENDED"
    assert read_credential(ctx["registration"]["id"])["status"] == "REVOKED"


def test_a_freshly_verified_registration_reopens_the_reinstatement_path():
    """PRD §3.2: "On success `eo_coverage_verified_cents` is recomputed,
    `split_tier_provisional` is re-derived from `production_ytd_provisional_cents`, and
    `version` increments by 1."

    Design: Difficulty/non_linear_state_machine/advisor_suspend_reinstate_cycle_regated_on_fresh_registration
    """
    ctx = _suspended_by_revocation()
    advisor_id = ctx["advisor"]["id"]

    replacement = file_credential(
        advisor_id,
        seller_of_travel_credential_payload(
            jurisdiction_state_code="NY",
            credential_number="NY-SOT-40119",
            effective_on="2026-07-01",
            expires_on="2027-07-01",
        ),
    )
    replacement = decide_credential(replacement["id"], "VERIFY")
    assert replacement["status"] == "VERIFIED"

    reinstated = validate_success(api_client.reinstate_advisor(advisor_id, compliance()))

    assert reinstated["status"] == "ACTIVE"
    assert reinstated["split_tier_provisional"] == 1
    assert reinstated["production_ytd_provisional_cents"] == 0
    assert read_credential(ctx["registration"]["id"])["status"] == "REVOKED"
    registrations = advisor_credentials(advisor_id, credential_type="SELLER_OF_TRAVEL")
    assert sorted(row["status"] for row in registrations) == ["REVOKED", "VERIFIED"]
