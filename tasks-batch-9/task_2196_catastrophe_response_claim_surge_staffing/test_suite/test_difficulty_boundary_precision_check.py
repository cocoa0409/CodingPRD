"""Queue A — rule_id: boundary_precision_check.

Three boundaries on three different metrics: money headroom in cents, an integer
room count, and the DESK loss ceiling in dollars-and-cents.
"""
from test_helpers import validate_error, validate_success
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_money_equals
from test_helpers.test_users import (
    make_catastrophe_manager_headers,
    make_claims_examiner_headers,
    make_deployment_coordinator_headers,
)

CM = make_catastrophe_manager_headers("cm_1")
DC = make_deployment_coordinator_headers("dc_1")
CE = make_claims_examiner_headers("ce_1")


# ---------------------------------------------------------------------------
# Instance 1 — advance_headroom_exact_zero_cents_rejected_one_cent_accepted
# ---------------------------------------------------------------------------
def _claim_with_6000_advance_cap(api):
    """CAT-2026-601 DECLARED (EARTHQUAKE/CA @ 0.0500) with one claim TRIAGED at
    CAT_SEVERE whose advance_cap is exactly 6000.00."""
    event = validate_success(
        api.create_event(
            {
                "cat_code": "CAT-2026-601",
                "peril_type": "EARTHQUAKE",
                "jurisdiction_state": "CA",
                "event_start_utc": "2026-07-29T00:00:00.000Z",
                "exposure_count": 300,
                "avg_insured_value": 500000,
                "expected_severity_index": 0.0500,
            },
            CM,
        ),
        201,
    )
    validate_success(api.declare_event(event["id"], CM))
    claim = validate_success(
        api.create_claim(
            {
                "policy_number": "POL-6101",
                "loss_state": "CA",
                "loss_date_utc": "2026-07-29T00:00:00.000Z",
                "reported_loss_amount": 25000,
                "coverage_lines": [
                    {
                        "coverage_code": "DWELLING",
                        "limit_amount": 25000,
                        "deductible_amount": 5000,
                        "estimated_damage_amount": 25000,
                    }
                ],
                "event_id": event["id"],
                "access_status": "ACCESSIBLE",
            },
            CE,
        ),
        201,
    )
    triaged = validate_success(api.triage_claim(claim["id"], CE))
    return event, triaged


def test_one_cent_of_headroom_still_pays_and_clamps_the_request_down_to_it(api):
    """PRD §3.8: "The headroom is the `advance_cap` less the claim's
    `advance_paid_total`, rounded to 2 decimal places; if the headroom is 0.00 or less
    the issuance is refused with `ERR_ADVANCE_CAP_EXCEEDED` (HTTP 422) — the
    exact-zero-headroom case is a rejection, not a zero-dollar payment."
    PRD §3.8: "Otherwise the issued `amount` is the lesser of the `requested_amount`
    and the headroom."

    Design: Difficulty/boundary_precision_check/advance_headroom_exact_zero_cents_rejected_one_cent_accepted
    """
    _, claim = _claim_with_6000_advance_cap(api)
    # line eligible 20000.00 * 0.30 = 6000.00, CAT_SEVERE multiplier 1.00.
    assert_money_equals(claim["advance_cap"], 6000.00, "advance_cap")

    first = validate_success(
        api.create_advance_payment(
            {"claim_id": claim["id"], "requested_amount": 5999.99, "basis": "STRUCTURE_PARTIAL"},
            CE,
        ),
        201,
    )
    second = validate_success(
        api.create_advance_payment(
            {"claim_id": claim["id"], "requested_amount": 500.00, "basis": "STRUCTURE_PARTIAL"},
            CE,
        ),
        201,
    )

    assert_money_equals(first["amount"], 5999.99, "amount")
    # Headroom was exactly 0.01, so the waterfall min() clamps the 500.00 request.
    assert_money_equals(second["amount"], 0.01, "amount")
    refreshed = validate_success(api.get_claim(claim["id"], CE))
    assert_money_equals(refreshed["advance_paid_total"], 6000.00, "advance_paid_total")
    assert_money_equals(refreshed["paid_amount"], 6000.00, "paid_amount")


def test_exact_zero_headroom_is_rejected_and_writes_nothing(api):
    """PRD §3.8: "The headroom is the `advance_cap` less the claim's
    `advance_paid_total`, rounded to 2 decimal places; if the headroom is 0.00 or less
    the issuance is refused with `ERR_ADVANCE_CAP_EXCEEDED` (HTTP 422) — the
    exact-zero-headroom case is a rejection, not a zero-dollar payment."
    PRD §3.6: "First compute the eligible damage of each coverage line as the line's
    `estimated_damage_amount` capped at its `limit_amount`, less its
    `deductible_amount`, with a floor of zero; sum those **raw, unrounded** line values;
    take the greater of that sum and the claim's `reported_loss_amount` as the basis;
    multiply the basis by the tier reserve factor for the claim's `triage_tier` — 0.85
    for `CAT_SEVERE`, 0.65 for `COMPLEX`, 0.45 for `STANDARD`, 0.25 for `FAST_TRACK` —
    and round half up to 2 decimal places **once, at the end**."
    PRD §3.8: "Issuance creates the advance in `ISSUED`, refreshes the claim's
    `advance_cap`, and appends a `PAYMENT` ledger entry whose paid movement is the issued
    `amount` and whose case-reserve movement is the negation of that amount, recording
    that row's identifier in the advance's `reserve_entry_id`."

    Design: Difficulty/boundary_precision_check/advance_headroom_exact_zero_cents_rejected_one_cent_accepted
    """
    event, claim = _claim_with_6000_advance_cap(api)
    for amount in (5999.99, 500.00):
        validate_success(
            api.create_advance_payment(
                {"claim_id": claim["id"], "requested_amount": amount, "basis": "STRUCTURE_PARTIAL"},
                CE,
            ),
            201,
        )

    validate_error(
        api.create_advance_payment(
            {"claim_id": claim["id"], "requested_amount": 0.01, "basis": "STRUCTURE_PARTIAL"},
            CE,
        ),
        ApiErrorId.ERR_ADVANCE_CAP_EXCEEDED,
        422,
    )

    refreshed = validate_success(api.get_claim(claim["id"], CE))
    assert_money_equals(refreshed["advance_paid_total"], 6000.00, "advance_paid_total")
    # initial reserve round(max(25000, 20000) * 0.85, 2) = 21250.00, less 6000.00 paid.
    assert_money_equals(refreshed["case_reserve"], 15250.00, "case_reserve")
    assert_money_equals(
        validate_success(api.get_event(event["id"], CM))["incurred_total"],
        21250.00,
        "incurred_total",
    )
    rows = validate_success(api.list_advance_payments(CE, params={"claim_id": claim["id"]}))
    assert len(rows) == 2


# ---------------------------------------------------------------------------
# Instance 2 — housing_block_rooms_total_zero_cannot_open_one_can
# ---------------------------------------------------------------------------
def _zero_room_and_one_room_blocks(api):
    """CAT-2026-602 DECLARED with a PENDING 0-room block and a PENDING 1-room block,
    otherwise identical."""
    event = validate_success(
        api.create_event(
            {
                "cat_code": "CAT-2026-602",
                "peril_type": "FLOOD",
                "jurisdiction_state": "LA",
                "event_start_utc": "2026-07-30T00:00:00.000Z",
                "exposure_count": 800,
                "avg_insured_value": 180000,
                "expected_severity_index": 0.1200,
            },
            CM,
        ),
        201,
    )
    validate_success(api.declare_event(event["id"], CM))

    def _block(hotel_name, rooms_total):
        return validate_success(
            api.create_housing_block(
                {
                    "event_id": event["id"],
                    "hotel_name": hotel_name,
                    "city": "Baton Rouge",
                    "rooms_total": rooms_total,
                    "nightly_rate": 120,
                    "block_start_date": "2026-09-01T00:00:00.000Z",
                    "block_end_date": "2026-09-10T00:00:00.000Z",
                },
                DC,
            ),
            201,
        )

    return event, _block("Zero Rooms Lodge", 0), _block("One Room Lodge", 1)


def test_one_room_is_the_first_openable_block_size(api):
    """PRD §3.4: "Opening a block moves it `PENDING → ACTIVE` and is refused with
    `ERR_HOUSING_NOT_PENDING` from any other status."
    PRD §3.4: "A newly held block is `PENDING`, with `rooms_occupied` of zero and
    `rooms_available` equal to `rooms_total`."
    PRD §3.4: "From that span the system computes `block_night_count`, the number of
    whole days from `block_start_date` up to but not including `block_end_date`."

    Design: Difficulty/boundary_precision_check/housing_block_rooms_total_zero_cannot_open_one_can
    """
    _, zero_block, one_block = _zero_room_and_one_room_blocks(api)
    assert zero_block["status"] == "PENDING"
    assert zero_block["rooms_total"] == 0
    assert zero_block["rooms_available"] == 0
    assert zero_block["block_night_count"] == 9

    opened = validate_success(api.open_housing_block(one_block["id"], DC))

    assert opened["status"] == "ACTIVE"
    assert opened["rooms_available"] == 1
    assert opened["block_night_count"] == 9


def test_a_zero_room_block_can_never_be_opened(api):
    """PRD §3.4: "Two further conditions apply: the block must hold at least one room,
    so a block created with `rooms_total` of zero can never be opened and any attempt is
    refused with `ERR_HOUSING_BLOCK_EMPTY`; and the parent event must be `DECLARED` or
    `SURGE_ACTIVE`, otherwise `ERR_EVENT_NOT_DECLARED`."
    PRD §3.4: "A newly held block is `PENDING`, with `rooms_occupied` of zero and
    `rooms_available` equal to `rooms_total`."

    Design: Difficulty/boundary_precision_check/housing_block_rooms_total_zero_cannot_open_one_can
    """
    _, zero_block, one_block = _zero_room_and_one_room_blocks(api)
    validate_success(api.open_housing_block(one_block["id"], DC))

    validate_error(
        api.open_housing_block(zero_block["id"], DC), ApiErrorId.ERR_HOUSING_BLOCK_EMPTY, 409
    )

    refreshed = validate_success(api.get_housing_block(zero_block["id"], DC))
    assert refreshed["status"] == "PENDING"
    assert refreshed["rooms_total"] == 0
    assert refreshed["rooms_occupied"] == 0
    assert refreshed["rooms_available"] == 0
    assert validate_success(api.get_housing_block(one_block["id"], DC))["status"] == "ACTIVE"


# ---------------------------------------------------------------------------
# Instance 3 — desk_loss_ceiling_inclusive_at_10000_00_flips_at_10000_01
# ---------------------------------------------------------------------------
def _two_claims_straddling_the_desk_ceiling(api):
    """CAT-2026-603 DECLARED (WINTER_STORM/GA @ 0.1000) with two otherwise identical
    claims reporting 10000.00 and 10000.01."""
    event = validate_success(
        api.create_event(
            {
                "cat_code": "CAT-2026-603",
                "peril_type": "WINTER_STORM",
                "jurisdiction_state": "GA",
                "event_start_utc": "2026-07-30T00:00:00.000Z",
                "exposure_count": 400,
                "avg_insured_value": 220000,
                "expected_severity_index": 0.1000,
            },
            CM,
        ),
        201,
    )
    validate_success(api.declare_event(event["id"], CM))

    def _claim(policy_number, reported_loss_amount):
        return validate_success(
            api.create_claim(
                {
                    "policy_number": policy_number,
                    "loss_state": "GA",
                    "loss_date_utc": "2026-07-30T00:00:00.000Z",
                    "reported_loss_amount": reported_loss_amount,
                    "coverage_lines": [
                        {
                            "coverage_code": "DWELLING",
                            "limit_amount": 200000,
                            "deductible_amount": 1000,
                            "estimated_damage_amount": 12000,
                        }
                    ],
                    "event_id": event["id"],
                    "access_status": "ACCESSIBLE",
                },
                CE,
            ),
            201,
        )

    return event, _claim("POL-6301", 10000.00), _claim("POL-6302", 10000.01)


def test_reported_loss_of_exactly_ten_thousand_resolves_to_desk(api):
    """PRD §3.6: "Otherwise, if the tier is `FAST_TRACK` and the `reported_loss_amount`
    is 10000.00 or less, the mode is `DESK` — the boundary is inclusive, so a reported
    loss of exactly 10000.00 resolves to `DESK` while 10000.01 resolves to `FIELD`."
    PRD §3.6: "The score then selects the band recorded in `triage_tier`: a score of
    75.00 or more is `CAT_SEVERE`, a score of 50.00 or more but below 75.00 is
    `COMPLEX`, a score of 25.00 or more but below 50.00 is `STANDARD`, and anything
    below 25.00 is `FAST_TRACK`."

    Design: Difficulty/boundary_precision_check/desk_loss_ceiling_inclusive_at_10000_00_flips_at_10000_01
    """
    _, claim_s, _ = _two_claims_straddling_the_desk_ceiling(api)

    triaged = validate_success(api.triage_claim(claim_s["id"], CE))

    # base 100 * (10000/200000) = 5.00; * 0.90 WINTER_STORM = 4.50; + 20 * 0.1000.
    assert_money_equals(triaged["severity_score"], 6.50, "severity_score")
    assert triaged["triage_tier"] == "FAST_TRACK"
    assert triaged["inspection_mode"] == "DESK"
    assert_money_equals(triaged["case_reserve"], 2750.00, "case_reserve")


def test_one_extra_cent_of_reported_loss_flips_the_mode_to_field(api):
    """PRD §3.6: "Otherwise, if the tier is `FAST_TRACK` and the `reported_loss_amount`
    is 10000.00 or less, the mode is `DESK` — the boundary is inclusive, so a reported
    loss of exactly 10000.00 resolves to `DESK` while 10000.01 resolves to `FIELD`."
    PRD §3.6: "Clamp the result so it is not below 0 and not above 100, and only then
    round half up to 2 decimal places — a single rounding, applied after the clamp."
    PRD §2.9: "A strain of 8 or more bands as `FROZEN`; a strain of 3 or more but below
    8 bands as `RESTRICTED`; a strain below 3 bands as `OPEN`."

    Design: Difficulty/boundary_precision_check/desk_loss_ceiling_inclusive_at_10000_00_flips_at_10000_01
    """
    event, claim_s, claim_t = _two_claims_straddling_the_desk_ceiling(api)
    desk = validate_success(api.triage_claim(claim_s["id"], CE))

    field = validate_success(api.triage_claim(claim_t["id"], CE))

    # 6.50000225 rounds to the same 6.50, so only the one cent of reported loss differs.
    assert_money_equals(field["severity_score"], 6.50, "severity_score")
    assert field["severity_score"] == desk["severity_score"]
    assert field["triage_tier"] == "FAST_TRACK"
    assert field["inspection_mode"] == "FIELD"
    assert_money_equals(field["case_reserve"], 2750.00, "case_reserve")
    refreshed_event = validate_success(api.get_event(event["id"], CM))
    assert_money_equals(refreshed_event["case_reserve_total"], 5500.00, "case_reserve_total")
    assert refreshed_event["posture"] == "OPEN"
