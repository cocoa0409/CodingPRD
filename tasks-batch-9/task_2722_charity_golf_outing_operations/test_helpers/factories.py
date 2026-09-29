"""Payload factories.

Every factory returns a fresh, valid request body and accepts ``**overrides``
so a test can flip exactly the field under examination.  Money is always an
integer number of cents and timestamps are always ISO 8601 UTC with a
trailing ``Z``.
"""

from typing import Any, Dict, List, Optional

# The logical clock starts at 2026-08-01T00:00:00Z, so every default instant in
# this module sits comfortably after it.
DEFAULT_SCHEDULED_DATE = "2026-09-19T12:00:00Z"
DEFAULT_WAVE_A_START = "2026-09-19T12:00:00Z"
DEFAULT_WAVE_A_END = "2026-09-19T16:30:00Z"
DEFAULT_WAVE_B_START = "2026-09-19T17:00:00Z"
DEFAULT_WAVE_B_END = "2026-09-19T21:00:00Z"
DEFAULT_RAIN_DATE = "2026-09-26T12:00:00Z"
DEFAULT_FULFILLMENT_DUE_AT = "2026-09-15T00:00:00Z"


def _merge(base: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    """Apply overrides; a value of ``None`` removes the key entirely."""
    payload = dict(base)
    for key, value in overrides.items():
        if value is None and key in payload:
            del payload[key]
        else:
            payload[key] = value
    return payload


# ------------------------------------------------------------- outings ------


def outing_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "name": "Northside Charity Classic",
            "beneficiary_name": "Northside Youth Fund",
            "format": "SCRAMBLE",
            "start_format": "TEE_TIME",
            "scheduled_date": DEFAULT_SCHEDULED_DATE,
            "wave_a_start": DEFAULT_WAVE_A_START,
            "wave_a_end": DEFAULT_WAVE_A_END,
            "field_capacity_teams": 1,
            "prize_pool_cents": 0,
        },
        overrides,
    )


def wave_split_outing_payload(**overrides: Any) -> Dict[str, Any]:
    return outing_payload(
        start_format="WAVE_SPLIT",
        wave_b_start=DEFAULT_WAVE_B_START,
        wave_b_end=DEFAULT_WAVE_B_END,
        **overrides,
    )


def play_transition_payload(action: str, **overrides: Any) -> Dict[str, Any]:
    return _merge({"action": action}, overrides)


def finance_transition_payload(
    action: str, expected_outing_version: int, **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {"action": action, "expected_outing_version": expected_outing_version}, overrides
    )


def remit_payload(
    expected_outing_version: int,
    remittance_cents: int,
    remittance_reference: str = "WIRE-2026-0001",
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "action": "REMIT",
            "expected_outing_version": expected_outing_version,
            "remittance_cents": remittance_cents,
            "remittance_reference": remittance_reference,
        },
        overrides,
    )


# ----------------------------------------------------------- contracts ------


def contract_payload(outing_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "outing_id": outing_id,
            "course_name": "Cedar Ridge GC",
            "rate_per_player_cents": 9500,
            "guaranteed_player_count": 0,
            "fnb_minimum_cents": 0,
            "fnb_per_player_cents": 4500,
        },
        overrides,
    )


def minimal_contract_payload(outing_id: str, **overrides: Any) -> Dict[str, Any]:
    """Only the two required inputs plus the rate, so every default applies."""
    return _merge(
        {
            "outing_id": outing_id,
            "course_name": "Cedar Ridge GC",
            "rate_per_player_cents": 9500,
        },
        overrides,
    )


def contract_lifecycle_payload(action: str, **overrides: Any) -> Dict[str, Any]:
    return _merge({"action": action}, overrides)


# -------------------------------------------------------- package tiers -----


def package_tier_payload(outing_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "outing_id": outing_id,
            "code": "TEAM4",
            "kind": "TEAM",
            "price_cents": 120000,
            "player_slots": 4,
            "gsv_cents": 24000,
            "inventory_cap": 10,
        },
        overrides,
    )


def sponsor_tier_payload(outing_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "outing_id": outing_id,
            "code": "GOLD",
            "kind": "SPONSOR",
            "price_cents": 250000,
            "player_slots": 0,
            "gsv_cents": 0,
            "inventory_cap": 5,
        },
        overrides,
    )


# --------------------------------------------------------- registrations ----


def registration_payload(
    outing_id: str, package_tier_id: str, **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {
            "outing_id": outing_id,
            "package_tier_id": package_tier_id,
            "buyer_name": "Cedar Street Dental",
            "player_count": 4,
        },
        overrides,
    )


def payment_payload(amount_cents: int, **overrides: Any) -> Dict[str, Any]:
    return _merge({"amount_cents": amount_cents}, overrides)


def amend_tier_payload(
    package_tier_id: str, expected_registration_version: int, **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {
            "package_tier_id": package_tier_id,
            "expected_registration_version": expected_registration_version,
        },
        overrides,
    )


def registration_lifecycle_payload(action: str, **overrides: Any) -> Dict[str, Any]:
    return _merge({"action": action}, overrides)


# ---------------------------------------------------------------- players ---


def player_payload(registration_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "registration_id": registration_id,
            "full_name": "Dana Ortiz",
            "handicap_index": 12.0,
        },
        overrides,
    )


def handicap_index_payload(handicap_index: float, **overrides: Any) -> Dict[str, Any]:
    return _merge({"handicap_index": handicap_index}, overrides)


# ------------------------------------------------------------------ teams ---


def team_payload(outing_id: str, player_ids: List[str], **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {"outing_id": outing_id, "team_name": "ALPHA", "player_ids": list(player_ids)},
        overrides,
    )


def tee_assignment_payload(
    expected_team_version: int,
    wave: str = "A",
    starting_hole: int = 1,
    tee_time: str = DEFAULT_WAVE_A_START,
    cart_number: int = 1,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "expected_team_version": expected_team_version,
            "wave": wave,
            "starting_hole": starting_hole,
            "tee_time": tee_time,
            "cart_number": cart_number,
        },
        overrides,
    )


def score_payload(
    gross_score: int = 72,
    gross_back_9: int = 36,
    gross_back_6: int = 24,
    gross_back_3: int = 12,
    gross_hole_18: int = 4,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "gross_score": gross_score,
            "gross_back_9": gross_back_9,
            "gross_back_6": gross_back_6,
            "gross_back_3": gross_back_3,
            "gross_hole_18": gross_hole_18,
        },
        overrides,
    )


# ------------------------------------------------------ sponsorship assets --


def sponsorship_asset_payload(outing_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "outing_id": outing_id,
            "asset_type": "HOLE_SIGN",
            "label": "Hole 5 tee sign",
            "hole_number": 5,
            "capacity": 1,
            "exclusive": True,
            "list_price_cents": 50000,
            "fulfillment_due_at": DEFAULT_FULFILLMENT_DUE_AT,
        },
        overrides,
    )


def beverage_station_payload(outing_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "outing_id": outing_id,
            "asset_type": "BEVERAGE_STATION",
            "label": "Turn beverage cart",
            "hole_number": 10,
            "capacity": 2,
            "exclusive": False,
            "list_price_cents": 40000,
            "fulfillment_due_at": "2026-09-19T18:00:00Z",
        },
        overrides,
    )


def inventory_payload(action: str, **overrides: Any) -> Dict[str, Any]:
    return _merge({"action": action}, overrides)


# ----------------------------------------------------- sponsor allocations --


def sponsor_allocation_payload(
    registration_id: str, sponsorship_asset_id: str, source: str = "PACKAGE_ENTITLEMENT", **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {
            "registration_id": registration_id,
            "sponsorship_asset_id": sponsorship_asset_id,
            "source": source,
        },
        overrides,
    )


def fulfillment_payload(action: str, **overrides: Any) -> Dict[str, Any]:
    return _merge({"action": action}, overrides)


# --------------------------------------------------------------- contests ---


def contest_payload(outing_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "outing_id": outing_id,
            "contest_type": "HOLE_IN_ONE",
            "hole_number": 7,
            "prize_value_cents": 500000,
        },
        overrides,
    )


def insurance_payload(
    insurance_carrier: str = "Fairway Mutual",
    insurance_premium_cents: int = 40000,
    insurance_coverage_cap_cents: int = 500000,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "insurance_carrier": insurance_carrier,
            "insurance_premium_cents": insurance_premium_cents,
            "insurance_coverage_cap_cents": insurance_coverage_cap_cents,
        },
        overrides,
    )


def contest_status_payload(action: str, **overrides: Any) -> Dict[str, Any]:
    return _merge({"action": action}, overrides)


def award_payload(winner_player_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge({"winner_player_id": winner_player_id}, overrides)


# ------------------------------------------------------ fundraising items ---


def fundraising_item_payload(outing_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "outing_id": outing_id,
            "item_type": "AUCTION",
            "description": "Signed pin flag",
            "fmv_cents": 0,
            "ask_cents": 0,
        },
        overrides,
    )


def item_sale_payload(
    buyer_registration_id: str, bid_cents: int, **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {"buyer_registration_id": buyer_registration_id, "bid_cents": bid_cents}, overrides
    )


def item_lifecycle_payload(action: str, **overrides: Any) -> Dict[str, Any]:
    return _merge({"action": action}, overrides)


# --------------------------------------------------------------- receipts ---


def registration_receipt_payload(
    outing_id: str, registration_id: str, **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {
            "outing_id": outing_id,
            "receipt_kind": "REGISTRATION",
            "registration_id": registration_id,
        },
        overrides,
    )


def item_receipt_payload(
    outing_id: str, fundraising_item_id: str, **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {
            "outing_id": outing_id,
            "receipt_kind": "FUNDRAISING_ITEM",
            "fundraising_item_id": fundraising_item_id,
        },
        overrides,
    )


def reversal_receipt_payload(
    outing_id: str, reverses_receipt_id: str, **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {
            "outing_id": outing_id,
            "receipt_kind": "REVERSAL",
            "reverses_receipt_id": reverses_receipt_id,
        },
        overrides,
    )


def reversal_payload(reversal_reason: Optional[str] = None, **overrides: Any) -> Dict[str, Any]:
    base: Dict[str, Any] = {}
    if reversal_reason is not None:
        base["reversal_reason"] = reversal_reason
    return _merge(base, overrides)
