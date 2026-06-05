"""Corner-design coverage — validations section."""
import pytest

from test_helpers import (
    validate_error,
    set_clock,
    register_client,
    sign_retainer,
    create_case,
    activate_case,
    register_provider,
    create_records_request,
    walk_records_request_to_reviewed,
    create_proposed_damages,
    create_demand_letter,
    send_demand_letter,
    create_lien,
    negotiate_lien,
    create_offer,
    get_case,
    ApiErrorId,
    api_client,
    create_court_event_payload,
    create_offer_payload,
    create_damages_item_payload,
    agree_lien_payload,
    make_paralegal_headers,
    make_attorney_headers,
    setup_active_case,
    setup_active_case_with_reviewed_records,
    setup_case_in_negotiation_with_offer,
)


# ─── lien_agree_overpayment_rejected ────────────────────────────────


def test_lien_agree_above_asserted_returns_lien_overpayment(api):
    """PRD §3.7: "the paralegal can land a deal, moving the lien
    `NEGOTIATING → AGREED` and supplying a `negotiated_amount_cents` in the
    request body that must be less than or equal to `asserted_amount_cents`
    (any overpayment is rejected with `ERR_LIEN_OVERPAYMENT`)."

    Design: Corner/validations/lien_agree_overpayment_rejected
    """
    set_clock("2026-01-01T00:00:00Z")
    client, case = setup_active_case()
    provider = register_provider()
    lien = create_lien(case["id"], provider["id"], 500_000)
    negotiate_lien(lien["id"])
    res = api_client.agree_lien(
        lien["id"], agree_lien_payload(500_001), make_paralegal_headers()
    )
    validate_error(res, ApiErrorId.ERR_LIEN_OVERPAYMENT.value)


# ─── court_event_in_past_rejected ───────────────────────────────────


def test_court_event_scheduled_in_past_returns_event_in_past(api):
    """PRD §3.8: "The explicit creation pins two temporal rules. First,
    `scheduled_at` must be strictly later than the current system clock at
    create time; any attempt to schedule an event at or before "now" is
    rejected with `ERR_EVENT_IN_PAST`."

    Design: Corner/validations/court_event_in_past_rejected
    """
    # Clock at 2026-01-01 (CA accident 2024-06-15 → SOL 2026-06-15, still alive);
    # schedule a HEARING at 2025-12-01, strictly before "now". PRD §3.8: "any
    # attempt to schedule an event at or before \"now\" is rejected".
    set_clock("2026-01-01T00:00:00Z")
    client, case = setup_active_case(clock_iso="2026-01-01T00:00:00Z")
    res = api_client.create_court_event(
        create_court_event_payload(case["id"], "HEARING",
                                    "2025-12-01T14:00:00Z",
                                    duration_minutes=60),
        make_attorney_headers(),
    )
    validate_error(res, ApiErrorId.ERR_EVENT_IN_PAST.value)


# ─── settlement_counter_wrong_party_rejected ────────────────────────


def test_counter_with_same_party_as_prior_returns_invalid_counter(api):
    """PRD §3.5: "The counter must be on the same `case_id` as the prior
    offer, the prior offer's status must be `PENDING`, and the `by_party`
    on the new counter must be the opposite of the prior offer's `by_party`
    (a `CARRIER` offer is countered only by a `FIRM` offer and vice versa);
    any of these conditions failing yields `ERR_INVALID_COUNTER`."

    Design: Corner/validations/settlement_counter_wrong_party_rejected
    """
    set_clock("2026-01-01T00:00:00Z")
    client, case_neg, provider, offer1 = setup_case_in_negotiation_with_offer(
        offer_amount_cents=2_000_000, by_party="CARRIER",
    )
    # Counter must be FIRM; we deliberately send another CARRIER.
    res = api_client.create_offer(
        create_offer_payload(case_neg["id"], 2_500_000, "CARRIER",
                              counter_to_offer_id=offer1["id"]),
        make_attorney_headers(),
    )
    validate_error(res, ApiErrorId.ERR_INVALID_COUNTER.value)


# ─── case_activate_without_signed_retainer_rejected ─────────────────


def test_activate_case_without_signed_retainer_returns_retainer_missing(api):
    """PRD §3.1: "Activation has two preconditions: the client must have
    signed the retainer (otherwise the activation fails with
    `ERR_RETAINER_MISSING`), and the statute of limitations must not yet
    have run for this case at the current clock value (otherwise
    `ERR_STATUTE_EXPIRED`)."

    Design: Corner/validations/case_activate_without_signed_retainer_rejected
    """
    set_clock("2026-01-01T00:00:00Z")
    client = register_client(email="nr@example.com")
    # Skip sign_retainer.
    case = create_case(client["id"], accident_date="2024-06-15",
                        jurisdiction="CA")
    res = api_client.activate_case(case["id"], make_attorney_headers())
    validate_error(res, ApiErrorId.ERR_RETAINER_MISSING.value)
    case_after = get_case(case["id"])
    assert case_after["status"] == "INTAKE"


# ─── include_medical_bills_without_reviewed_records_rejected ────────


def test_include_medical_bills_without_reviewed_records_returns_missing_records(api):
    """PRD §3.3: "if the item's `category` is `MEDICAL_BILLS`, at least one
    `MedicalRecordsRequest` on the same `case_id` must have reached
    `REVIEWED` — otherwise the include is rejected with
    `ERR_MISSING_MEDICAL_RECORDS`."

    Design: Corner/validations/include_medical_bills_without_reviewed_records_rejected
    """
    set_clock("2026-01-01T00:00:00Z")
    client, case = setup_active_case()
    provider = register_provider()
    create_records_request(case["id"], provider["id"])  # stays REQUESTED
    item = create_proposed_damages(case["id"], "MEDICAL_BILLS", 200_000)
    res = api_client.include_damages_item(item["id"], make_attorney_headers())
    validate_error(res, ApiErrorId.ERR_MISSING_MEDICAL_RECORDS.value)
