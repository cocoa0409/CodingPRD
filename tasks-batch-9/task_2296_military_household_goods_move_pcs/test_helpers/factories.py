"""Payload factories — one per write endpoint, carrying only client-supplied fields."""

from typing import Any, Dict, List, Optional

DEFAULTS: Dict[str, Any] = {
    "FULL_NAME": "Dana Reyes",
    "RANK_CODE": "E6",
    "BRANCH": "ARMY",
    "EMAIL": "dana.reyes@example.mil",
    "ORIGIN_DUTY_STATION": "FORT MEADE MD",
    "DESTINATION_DUTY_STATION": "FORT CARSON CO",
    "ORIGIN_MARKET_CODE": "MKT-BWI",
    "DISTANCE_MILES": 1200,
    "ISSUE_DATE": "2026-08-01T00:00:00Z",
    "REPORT_NO_LATER_THAN_DATE": "2026-10-01T00:00:00Z",
    "SCHEDULED_AT": "2026-08-05T00:00:00Z",
    "TSP_NAME": "Chesapeake Van Lines",
    "SCAC_CODE": "CVLQ",
    "WEEK_START_DATE": "2026-08-17T00:00:00Z",
    "TOTAL_CAPACITY_LBS": 12000,
    "SHORT_NOTICE_RESERVE_PCT": 0.15,
    "REQUESTED_PACK_DATE": "2026-08-14T00:00:00Z",
    "REQUESTED_PICKUP_DATE": "2026-08-17T00:00:00Z",
    "REQUESTED_DELIVERY_DATE": "2026-08-24T00:00:00Z",
}

# Room-by-room cube figures that yield a 5286 lb provisional estimate under the
# cube-times-seven method: 1005 + 1878 + 1474 + 677 = 5034, plus a 5% uplift.
CANONICAL_ROOM_ESTIMATES: List[Dict[str, Any]] = [
    {"room_name": "KITCHEN", "cube_feet": 143.5},
    {"room_name": "LIVING_ROOM", "cube_feet": 268.25},
    {"room_name": "MASTER_BEDROOM", "cube_feet": 210.5},
    {"room_name": "GARAGE", "cube_feet": 96.75},
]


def _payload(defaults: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    body = dict(defaults)
    body.update(overrides)
    return {k: v for k, v in body.items() if v is not _OMIT}


class _Omit:
    """Sentinel allowing a factory caller to drop a field from the payload."""

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "<OMIT>"


_OMIT = _Omit()
OMIT = _OMIT


# ---------------------------------------------------------------------------
# Service members and orders
# ---------------------------------------------------------------------------


def create_service_member_payload(dod_id: str = "7000000001", **overrides) -> Dict[str, Any]:
    return _payload(
        {
            "dod_id": dod_id,
            "full_name": DEFAULTS["FULL_NAME"],
            "rank_code": DEFAULTS["RANK_CODE"],
            "branch": DEFAULTS["BRANCH"],
            "email": DEFAULTS["EMAIL"],
            "dependents_count": 2,
            "spouse_present": True,
        },
        overrides,
    )


def create_order_payload(
    service_member_id: str, order_number: str = "ORD-C-01", **overrides
) -> Dict[str, Any]:
    return _payload(
        {
            "service_member_id": service_member_id,
            "order_number": order_number,
            "move_type": "PCS_CONUS",
            "issue_date": DEFAULTS["ISSUE_DATE"],
            "report_no_later_than_date": DEFAULTS["REPORT_NO_LATER_THAN_DATE"],
            "origin_duty_station": DEFAULTS["ORIGIN_DUTY_STATION"],
            "destination_duty_station": DEFAULTS["DESTINATION_DUTY_STATION"],
            "origin_market_code": DEFAULTS["ORIGIN_MARKET_CODE"],
            "distance_miles": DEFAULTS["DISTANCE_MILES"],
        },
        overrides,
    )


def amend_order_payload(amendment_reason: str = "DEPENDENTS CORRECTED", **overrides) -> Dict[str, Any]:
    return _payload({"amendment_reason": amendment_reason}, overrides)


# ---------------------------------------------------------------------------
# Counseling and entitlements
# ---------------------------------------------------------------------------


def create_counseling_session_payload(order_id: str, **overrides) -> Dict[str, Any]:
    return _payload(
        {
            "order_id": order_id,
            "session_type": "VIRTUAL",
            "scheduled_at": DEFAULTS["SCHEDULED_AT"],
        },
        overrides,
    )


def complete_counseling_payload(entitlement_briefed: bool = True, **overrides) -> Dict[str, Any]:
    return _payload({"entitlement_briefed": entitlement_briefed}, overrides)


def authorize_entitlement_payload(admin_weight_bump_lbs: int = 0, **overrides) -> Dict[str, Any]:
    return _payload({"admin_weight_bump_lbs": admin_weight_bump_lbs}, overrides)


def excess_cost_waiver_payload(
    waived_amount_usd: float, waiver_reason: str = "FINANCIAL HARDSHIP", **overrides
) -> Dict[str, Any]:
    return _payload(
        {"waived_amount_usd": waived_amount_usd, "waiver_reason": waiver_reason},
        overrides,
    )


def revoke_waiver_payload(revocation_reason: str = "DOCUMENTATION WITHDRAWN", **overrides) -> Dict[str, Any]:
    return _payload({"revocation_reason": revocation_reason}, overrides)


def resume_entitlement_payload(resume_note: str = "EXCESS COST CLEARED", **overrides) -> Dict[str, Any]:
    return _payload({"resume_note": resume_note}, overrides)


# ---------------------------------------------------------------------------
# Providers and capacity
# ---------------------------------------------------------------------------


def create_tsp_payload(
    scac_code: str = DEFAULTS["SCAC_CODE"],
    markets: Optional[List[str]] = None,
    **overrides,
) -> Dict[str, Any]:
    return _payload(
        {
            "name": DEFAULTS["TSP_NAME"],
            "scac_code": scac_code,
            "markets": list(markets) if markets is not None else ["MKT-BWI"],
        },
        overrides,
    )


def create_capacity_block_payload(
    tsp_id: str,
    market_code: str = "MKT-BWI",
    week_start_date: str = DEFAULTS["WEEK_START_DATE"],
    total_capacity_lbs: int = DEFAULTS["TOTAL_CAPACITY_LBS"],
    short_notice_reserve_pct: float = DEFAULTS["SHORT_NOTICE_RESERVE_PCT"],
    **overrides,
) -> Dict[str, Any]:
    return _payload(
        {
            "tsp_id": tsp_id,
            "market_code": market_code,
            "week_start_date": week_start_date,
            "total_capacity_lbs": total_capacity_lbs,
            "short_notice_reserve_pct": short_notice_reserve_pct,
        },
        overrides,
    )


def award_payload(shipment_id: str, expected_capacity_block_version: int, **overrides) -> Dict[str, Any]:
    return _payload(
        {
            "shipment_id": shipment_id,
            "expected_capacity_block_version": expected_capacity_block_version,
        },
        overrides,
    )


def release_award_payload(shipment_id: str, **overrides) -> Dict[str, Any]:
    return _payload({"shipment_id": shipment_id}, overrides)


# ---------------------------------------------------------------------------
# Shipments
# ---------------------------------------------------------------------------


def create_shipment_payload(
    order_id: str,
    entitlement_id: str,
    tsp_id: str,
    expected_entitlement_version: int,
    shipment_code: str = "SHP-C01",
    **overrides,
) -> Dict[str, Any]:
    return _payload(
        {
            "order_id": order_id,
            "entitlement_id": entitlement_id,
            "tsp_id": tsp_id,
            "shipment_code": shipment_code,
            "shipment_method": "HHG",
            "origin_market_code": DEFAULTS["ORIGIN_MARKET_CODE"],
            "requested_pack_date": DEFAULTS["REQUESTED_PACK_DATE"],
            "requested_pickup_date": DEFAULTS["REQUESTED_PICKUP_DATE"],
            "requested_delivery_date": DEFAULTS["REQUESTED_DELIVERY_DATE"],
            "expected_entitlement_version": expected_entitlement_version,
        },
        overrides,
    )


def survey_payload(
    estimate_method: str = "CUBE_X7",
    room_estimates: Optional[List[Dict[str, Any]]] = None,
    **overrides,
) -> Dict[str, Any]:
    return _payload(
        {
            "estimate_method": estimate_method,
            "room_estimates": (
                [dict(r) for r in CANONICAL_ROOM_ESTIMATES]
                if room_estimates is None
                else room_estimates
            ),
        },
        overrides,
    )


def room_estimates(*cube_feet: float) -> List[Dict[str, Any]]:
    """Build a room-estimate array from a bare list of cube figures."""
    return [
        {"room_name": f"ROOM_{index + 1}", "cube_feet": value}
        for index, value in enumerate(cube_feet)
    ]


def pack_payload(pack_date: str, **overrides) -> Dict[str, Any]:
    return _payload({"pack_date": pack_date}, overrides)


def pickup_payload(actual_pickup_date: str, **overrides) -> Dict[str, Any]:
    return _payload({"actual_pickup_date": actual_pickup_date}, overrides)


def record_actual_weight_payload(
    actual_gross_lbs: int,
    actual_tare_lbs: int,
    weigh_date: str,
    scale_certified: bool = True,
    **overrides,
) -> Dict[str, Any]:
    return _payload(
        {
            "actual_gross_lbs": actual_gross_lbs,
            "actual_tare_lbs": actual_tare_lbs,
            "weigh_date": weigh_date,
            "scale_certified": scale_certified,
        },
        overrides,
    )


def dispute_weight_payload(dispute_reason: str = "SCALE TICKET MISMATCH", **overrides) -> Dict[str, Any]:
    return _payload({"dispute_reason": dispute_reason}, overrides)


def reweigh_payload(
    actual_gross_lbs: int,
    actual_tare_lbs: int,
    weigh_date: str,
    scale_certified: bool = True,
    **overrides,
) -> Dict[str, Any]:
    return _payload(
        {
            "actual_gross_lbs": actual_gross_lbs,
            "actual_tare_lbs": actual_tare_lbs,
            "weigh_date": weigh_date,
            "scale_certified": scale_certified,
        },
        overrides,
    )


def deliver_payload(delivery_date: str, **overrides) -> Dict[str, Any]:
    return _payload({"delivery_date": delivery_date}, overrides)


def cancel_shipment_payload(cancel_reason: str = "ORDERS RESCINDED", **overrides) -> Dict[str, Any]:
    return _payload({"cancel_reason": cancel_reason}, overrides)


# ---------------------------------------------------------------------------
# Pro-gear
# ---------------------------------------------------------------------------


def create_pro_gear_payload(
    owner: str = "MEMBER",
    claimed_weight_lbs: int = 500,
    documentation_type: str = "ITEMIZED_INVENTORY",
    item_description: str = "PROFESSIONAL TOOL SET",
    **overrides,
) -> Dict[str, Any]:
    return _payload(
        {
            "owner": owner,
            "item_description": item_description,
            "claimed_weight_lbs": claimed_weight_lbs,
            "documentation_type": documentation_type,
        },
        overrides,
    )


def verify_pro_gear_payload(verified_weight_lbs: int, **overrides) -> Dict[str, Any]:
    return _payload({"verified_weight_lbs": verified_weight_lbs}, overrides)


def reject_pro_gear_payload(rejection_reason: str = "NO DOCUMENTATION SUPPLIED", **overrides) -> Dict[str, Any]:
    return _payload({"rejection_reason": rejection_reason}, overrides)


def resubmit_pro_gear_payload(
    claimed_weight_lbs: int = 500,
    documentation_type: str = "EMPLOYER_LETTER",
    **overrides,
) -> Dict[str, Any]:
    return _payload(
        {
            "claimed_weight_lbs": claimed_weight_lbs,
            "documentation_type": documentation_type,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Storage in transit
# ---------------------------------------------------------------------------


def create_sit_payload(
    entry_date: str, requested_days: int = 10, sit_type: str = "ORIGIN", **overrides
) -> Dict[str, Any]:
    return _payload(
        {
            "sit_type": sit_type,
            "entry_date": entry_date,
            "requested_days": requested_days,
        },
        overrides,
    )


def authorize_sit_payload(authorized_days: int, **overrides) -> Dict[str, Any]:
    return _payload({"authorized_days": authorized_days}, overrides)


def extend_sit_payload(
    extension_days: int, extension_reason: str = "DESTINATION HOUSING DELAYED", **overrides
) -> Dict[str, Any]:
    return _payload(
        {"extension_days": extension_days, "extension_reason": extension_reason},
        overrides,
    )


def release_sit_payload(release_date: str, **overrides) -> Dict[str, Any]:
    return _payload({"release_date": release_date}, overrides)


# ---------------------------------------------------------------------------
# Claims
# ---------------------------------------------------------------------------


def create_claim_payload(
    notice_date: str,
    claim_type: str = "DAMAGE",
    incident_description: str = "DINING TABLE CRUSHED IN TRANSIT",
    **overrides,
) -> Dict[str, Any]:
    return _payload(
        {
            "claim_type": claim_type,
            "notice_date": notice_date,
            "incident_description": incident_description,
        },
        overrides,
    )


def create_claim_item_payload(
    replacement_cost_usd: float,
    category: str = "FURNITURE",
    age_years: float = 0.0,
    inventory_item_number: str = "INV-0001",
    item_description: str = "OAK DINING TABLE",
    high_value_inventory_documented: bool = False,
    **overrides,
) -> Dict[str, Any]:
    return _payload(
        {
            "item_description": item_description,
            "inventory_item_number": inventory_item_number,
            "category": category,
            "replacement_cost_usd": replacement_cost_usd,
            "age_years": age_years,
            "high_value_inventory_documented": high_value_inventory_documented,
        },
        overrides,
    )


def review_claim_payload(review_note: str = "OPENING REVIEW", **overrides) -> Dict[str, Any]:
    return _payload({"review_note": review_note}, overrides)


def request_claim_info_payload(info_request_note: str = "SUPPLY PURCHASE RECEIPTS", **overrides) -> Dict[str, Any]:
    return _payload({"info_request_note": info_request_note}, overrides)


def provide_claim_info_payload(response_note: str = "RECEIPTS ATTACHED", **overrides) -> Dict[str, Any]:
    return _payload({"response_note": response_note}, overrides)


def settle_claim_payload(settlement_note: str = "SETTLED ON THE FILED BASIS", **overrides) -> Dict[str, Any]:
    return _payload({"settlement_note": settlement_note}, overrides)


def disposition_claim_item_payload(
    disposition: str, adjudication_note: str = "ADJUDICATED", **overrides
) -> Dict[str, Any]:
    return _payload(
        {"disposition": disposition, "adjudication_note": adjudication_note}, overrides
    )


def deny_claim_payload(denial_reason: str = "NO CARRIER LIABILITY", **overrides) -> Dict[str, Any]:
    return _payload({"denial_reason": denial_reason}, overrides)


# ---------------------------------------------------------------------------
# Personally procured moves
# ---------------------------------------------------------------------------


def trip_ticket(
    trip_number: int,
    full_lbs: int,
    empty_lbs: int,
    ticket_source: str = "CERTIFIED PUBLIC SCALE",
    certified: bool = True,
) -> Dict[str, Any]:
    return {
        "trip_number": trip_number,
        "full_lbs": full_lbs,
        "empty_lbs": empty_lbs,
        "ticket_source": ticket_source,
        "certified": certified,
    }


def create_ppm_payload(
    trip_tickets: Optional[List[Dict[str, Any]]] = None,
    documented_expenses_usd: float = 0.00,
    advance_paid_usd: float = 0.00,
    elected_basis: str = "AUTO",
    **overrides,
) -> Dict[str, Any]:
    return _payload(
        {
            "trip_tickets": (
                trip_tickets
                if trip_tickets is not None
                else [trip_ticket(1, 9200, 5400)]
            ),
            "documented_expenses_usd": documented_expenses_usd,
            "advance_paid_usd": advance_paid_usd,
            "elected_basis": elected_basis,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------


def dispatch_notification_payload(channel: str = "EMAIL", **overrides) -> Dict[str, Any]:
    return _payload({"channel": channel}, overrides)
