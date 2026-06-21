"""Corner-design coverage — calculations section."""
import pytest

from test_helpers import (
    validate_success,
    set_clock,
    register_client,
    sign_retainer,
    create_case,
    activate_case,
    register_provider,
    create_records_request,
    walk_records_request_to_reviewed,
    create_included_damages,
    create_demand_letter,
    send_demand_letter,
    create_lien,
    create_offer,
    accept_offer,
    get_case_version,
    get_case,
    get_disbursement_for_case,
    api_client,
    setup_active_case_with_reviewed_records,
)


# ─── lien_proportional_cap_overflow_waterfall ───────────────────────


def test_lien_waterfall_floors_per_lien_with_oldest_first_remainder(api):
    """PRD §3.7: "Otherwise, a shrink ratio is computed as the distributable
    pool divided by the total asserted, every lien's interim cap is set to
    its `asserted_amount_cents` multiplied by that shrink ratio and then
    floored to a whole cent, the sum of all the floored caps is taken, and
    the difference between the pool and that sum is a non-negative
    integer-cent remainder — flooring guarantees this. The remainder is
    then distributed cent by cent to the oldest liens first (in `created_at`
    ascending order), incrementing each lien's cap by one cent in turn until
    the remainder is exhausted."

    Design: Corner/calculations/lien_proportional_cap_overflow_waterfall
    """
    from test_helpers import TEST_USERS
    set_clock("2026-01-01T00:00:00Z")
    client, case, provider_a, mrr = setup_active_case_with_reviewed_records()
    provider_b = register_provider(name="WF Hosp B",
                                    contact="wfb@p.example")
    create_included_damages(case["id"], "MEDICAL_BILLS", 500_000)
    dl = create_demand_letter(case["id"], pain_multiplier=1.5,
                               drafter_user_id="drafter-wf")
    send_demand_letter(dl["id"], partner_user_id="partner-wf")
    # Two liens — A older than B.
    lien_a = create_lien(case["id"], provider_a["id"], 400_000)
    lien_b = create_lien(case["id"], provider_b["id"], 600_000)
    offer = create_offer(case["id"], 1_000_000, "CARRIER")
    case_v = get_case_version(case["id"])
    accept_offer(offer["id"], case_v, partner_user_id="partner-wf")

    case_after = get_case(case["id"])
    disb = get_disbursement_for_case(case["id"])
    # gross=1_000_000, pre-suit fee=333_300, distributable=666_700.
    # total_asserted=1_000_000 > distributable; shrink=0.6667.
    # cap_a=floor(400_000 * 0.6667)=266_680; cap_b=floor(600_000*0.6667)=400_020.
    # Sum=666_700; remainder=0.
    assert case_after["gross_settlement_cents"] == 1_000_000
    assert disb["contingency_fee_cents"] == 333_300
    assert disb["total_lien_payout_cents"] == 666_700
    assert disb["net_to_client_cents"] == 0

    h = TEST_USERS["attorney_headers"]
    lien_a_after = validate_success(api.get_lien(lien_a["id"], h), 200)
    lien_b_after = validate_success(api.get_lien(lien_b["id"], h), 200)
    assert lien_a_after["negotiated_amount_cents"] == 266_680
    assert lien_b_after["negotiated_amount_cents"] == 400_020


# ─── sol_with_tolling_extends_deadline ──────────────────────────────


def test_sol_tolling_days_extends_effective_sol_window(api):
    """PRD §3.1: "with the client in place, the paralegal opens the matter
    by creating the case, supplying the `client_id`, the `accident_date` on
    which the injury occurred, the `jurisdiction` in which the case will
    sit, and optionally an integer `sol_tolled_days` to add for tolling
    reasons such as a minor claimant or fraudulent concealment."
    PRD §3.1: "its `statute_of_limitations_date` is computed from the
    accident date plus the jurisdictional statute years (California, New
    York, Texas, and Illinois each give two years; Florida gives four), and
    that statute date is effectively immutable because `accident_date` and
    `jurisdiction` cannot be changed after creation. The tolling number is
    added on top in days."

    Design: Corner/calculations/sol_with_tolling_extends_deadline
    """
    # Clock past raw SOL (2026-01-15) but before tolled SOL (raw + 30 days).
    set_clock("2026-02-01T00:00:00Z")
    client = register_client(email="toll@example.com")
    sign_retainer(client["id"])
    # Tolling +30 days pushes effective SOL to 2026-02-14; clock is 2026-02-01.
    case = create_case(client["id"], accident_date="2024-01-15",
                        jurisdiction="CA", sol_tolled_days=30)
    activated = activate_case(case["id"])
    # Activation must succeed because tolled SOL is still in the future.
    assert activated["status"] == "ACTIVE"


# ─── contingency_fee_rounding_half_up_at_third_decimal ──────────────


def test_contingency_fee_rounds_half_up_once_at_the_end(api):
    """PRD §3.7: "The `contingency_fee_cents` is computed as the product of
    `gross_settlement_cents` and the applicable rate, with the
    multiplication performed as a single Decimal operation against integer
    cents, rounded half-up once at the end — there is no per-line rounding
    inside the fee."
    PRD §2.6: "When a calculation requires multiplication by a rate (a
    contingency-fee percentage, a present-value factor, a pain-and-suffering
    multiplier, or a buffer percentage), the multiplication is performed
    against the integer cent amount, and the product is rounded half-up to
    the nearest whole cent."

    Design: Corner/calculations/contingency_fee_rounding_half_up_at_third_decimal
    """
    set_clock("2026-01-01T00:00:00Z")
    client, case, provider, mrr = setup_active_case_with_reviewed_records()
    create_included_damages(case["id"], "MEDICAL_BILLS", 1_000_000)
    dl = create_demand_letter(case["id"], pain_multiplier=1.5,
                               drafter_user_id="drafter-rh")
    send_demand_letter(dl["id"], partner_user_id="partner-rh")
    offer = create_offer(case["id"], 3_000_001, "CARRIER")
    case_v = get_case_version(case["id"])
    accept_offer(offer["id"], case_v, partner_user_id="partner-rh")

    case_after = get_case(case["id"])
    disb = get_disbursement_for_case(case["id"])
    # gross=3_000_001, pre-suit rate=0.3333.
    # 3_000_001 * 0.3333 = 999_900.3333 → round_half_up → 999_900.
    assert case_after["gross_settlement_cents"] == 3_000_001
    assert disb["contingency_fee_cents"] == 999_900
