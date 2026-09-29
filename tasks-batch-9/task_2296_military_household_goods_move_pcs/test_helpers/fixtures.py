"""Composite setup helpers.

Each helper builds its preconditions from scratch through published endpoints, because
every test starts against an empty system.  Helpers use the lenient success reader so a
broken precondition surfaces as a clear setup failure rather than as a puzzling
assertion inside the test under scrutiny.

The dictionaries these helpers return are plain scenario bags; the keys are stable:

    member, member_headers, order, session, entitlement, tsp, tsp_headers,
    shipment, block, claim, claim_items, sit, ppm

Only the keys a helper actually created are present.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import BASE_CLOCK_UTC
from .factories import (
    amend_order_payload,
    authorize_entitlement_payload,
    authorize_sit_payload,
    award_payload,
    cancel_shipment_payload,
    complete_counseling_payload,
    create_capacity_block_payload,
    create_claim_item_payload,
    create_claim_payload,
    create_counseling_session_payload,
    create_order_payload,
    create_ppm_payload,
    create_pro_gear_payload,
    create_service_member_payload,
    create_shipment_payload,
    create_sit_payload,
    create_tsp_payload,
    deliver_payload,
    disposition_claim_item_payload,
    excess_cost_waiver_payload,
    pack_payload,
    pickup_payload,
    record_actual_weight_payload,
    release_sit_payload,
    review_claim_payload,
    settle_claim_payload,
    survey_payload,
    trip_ticket,
    verify_pro_gear_payload,
)
from .test_users import (
    TEST_USERS,
    make_claims_examiner_headers,
    make_move_counselor_headers,
    make_program_admin_headers,
    make_service_member_headers,
    make_tsp_coordinator_headers,
)

COUNSELOR = TEST_USERS["move_counselor_headers"]
ADMIN = TEST_USERS["program_admin_headers"]
ADMIN_ALT = TEST_USERS["program_admin_alt_headers"]
EXAMINER = TEST_USERS["claims_examiner_headers"]
EXAMINER_ALT = TEST_USERS["claims_examiner_alt_headers"]

# Canonical dates used by the standard scenario.
DEFAULT_PACK_DATE = "2026-08-15T00:00:00Z"
DEFAULT_PICKUP_DATE = "2026-08-17T00:00:00Z"
DEFAULT_WEIGH_DATE = "2026-08-18T00:00:00Z"
DEFAULT_DELIVERY_DATE = "2026-08-20T00:00:00Z"


# ---------------------------------------------------------------------------
# Tier 0 — clock and version readers
# ---------------------------------------------------------------------------


def set_clock(current_utc: str = BASE_CLOCK_UTC, headers: Optional[Dict] = None) -> Dict:
    """Pin the logical clock so every derived date in the scenario is deterministic."""
    return get_success_data(api_client.set_clock(current_utc, headers or ADMIN))


def read_entitlement(entitlement_id: str, headers: Optional[Dict] = None) -> Dict:
    return get_success_data(
        api_client.get_entitlement(entitlement_id, headers or COUNSELOR)
    )


def entitlement_version(entitlement_id: str) -> int:
    """Current version of the entitlement, for the mandatory booking precondition."""
    return read_entitlement(entitlement_id)["version"]


def read_capacity_block(block_id: str, headers: Optional[Dict] = None) -> Dict:
    return get_success_data(
        api_client.get_capacity_block(block_id, headers or COUNSELOR)
    )


def capacity_block_version(block_id: str) -> int:
    """Current version of the capacity block, for the mandatory award precondition."""
    return read_capacity_block(block_id)["version"]


def read_shipment(shipment_id: str, headers: Optional[Dict] = None) -> Dict:
    return get_success_data(api_client.get_shipment(shipment_id, headers or COUNSELOR))


def read_claim(claim_id: str, headers: Optional[Dict] = None) -> Dict:
    return get_success_data(api_client.get_claim(claim_id, headers or EXAMINER))


def read_tsp(tsp_id: str, headers: Optional[Dict] = None) -> Dict:
    return get_success_data(api_client.get_tsp(tsp_id, headers or ADMIN))


def read_sit(sit_id: str, headers: Optional[Dict] = None) -> Dict:
    return get_success_data(api_client.get_sit_authorization(sit_id, headers or COUNSELOR))


# ---------------------------------------------------------------------------
# Tier 1 — single-entity creation and state progression
# ---------------------------------------------------------------------------


def create_service_member(dod_id: str = "7000000001", **overrides) -> Dict:
    """Register one service member."""
    return get_success_data(
        api_client.create_service_member(
            create_service_member_payload(dod_id=dod_id, **overrides), COUNSELOR
        )
    )


def create_order(member_id: str, order_number: str = "ORD-C-01", **overrides) -> Dict:
    """Issue one set of orders against a member."""
    return get_success_data(
        api_client.create_order(
            create_order_payload(member_id, order_number=order_number, **overrides),
            COUNSELOR,
        )
    )


def create_counseling_session(order_id: str, **overrides) -> Dict:
    """Book one counseling appointment against orders."""
    return get_success_data(
        api_client.create_counseling_session(
            create_counseling_session_payload(order_id, **overrides), COUNSELOR
        )
    )


def complete_counseling(session_id: str, **overrides) -> Dict:
    """Complete counseling and return the draft entitlement it created."""
    get_success_data(
        api_client.complete_counseling_session(
            session_id, complete_counseling_payload(**overrides), COUNSELOR
        )
    )
    rows = get_success_data(
        api_client.list_counseling_session_entitlements(session_id, COUNSELOR)
    )
    assert rows, "Setup step failed: completing counseling created no entitlement"
    return rows[0]


def authorize_entitlement(
    entitlement_id: str, admin_weight_bump_lbs: int = 0, headers: Optional[Dict] = None
) -> Dict:
    """Authorize the entitlement so shipment work may begin."""
    return get_success_data(
        api_client.authorize_entitlement(
            entitlement_id,
            authorize_entitlement_payload(admin_weight_bump_lbs=admin_weight_bump_lbs),
            headers or COUNSELOR,
        )
    )


def create_tsp(scac_code: str = "CVLQ", markets: Optional[List[str]] = None, **overrides) -> Dict:
    """Onboard one transportation service provider."""
    return get_success_data(
        api_client.create_tsp(
            create_tsp_payload(scac_code=scac_code, markets=markets, **overrides), ADMIN
        )
    )


def create_capacity_block(tsp_id: str, **overrides) -> Dict:
    """Publish one weekly capacity block for a provider and market."""
    return get_success_data(
        api_client.create_capacity_block(
            create_capacity_block_payload(tsp_id, **overrides), ADMIN
        )
    )


def award_shipment(
    block_id: str,
    shipment_id: str,
    expected_capacity_block_version: Optional[int] = None,
    headers: Optional[Dict] = None,
) -> Dict:
    """Award a surveyed shipment into a block, reading the block version if not given."""
    version = (
        expected_capacity_block_version
        if expected_capacity_block_version is not None
        else capacity_block_version(block_id)
    )
    return get_success_data(
        api_client.create_award(
            block_id, award_payload(shipment_id, version), headers or ADMIN
        )
    )


def amend_order(order_id: str, **overrides) -> Dict:
    """Amend a set of orders with at least one override."""
    return get_success_data(
        api_client.amend_order(order_id, amend_order_payload(**overrides), COUNSELOR)
    )


# ---------------------------------------------------------------------------
# Tier 2 — entity hierarchy
# ---------------------------------------------------------------------------


def setup_authorized_entitlement(
    clock: str = BASE_CLOCK_UTC,
    dod_id: str = "7000000001",
    order_number: str = "ORD-C-01",
    member_overrides: Optional[Dict[str, Any]] = None,
    order_overrides: Optional[Dict[str, Any]] = None,
    session_overrides: Optional[Dict[str, Any]] = None,
    admin_weight_bump_lbs: int = 0,
    authorize: bool = True,
    authorize_headers: Optional[Dict] = None,
) -> Dict[str, Any]:
    """Member, orders, completed counseling and an authorized entitlement.

    Set authorize=False to stop at the draft entitlement.
    """
    set_clock(clock)
    member = create_service_member(dod_id=dod_id, **(member_overrides or {}))
    order = create_order(
        member["id"], order_number=order_number, **(order_overrides or {})
    )
    session = create_counseling_session(order["id"], **(session_overrides or {}))
    entitlement = complete_counseling(session["id"])
    if authorize:
        entitlement = authorize_entitlement(
            entitlement["id"],
            admin_weight_bump_lbs=admin_weight_bump_lbs,
            headers=authorize_headers,
        )
    return {
        "member": member,
        "member_headers": make_service_member_headers(member["id"]),
        "order": order,
        "session": session,
        "entitlement": entitlement,
    }


def book_shipment(
    scenario: Dict[str, Any],
    shipment_code: str = "SHP-C01",
    expected_entitlement_version: Optional[int] = None,
    **overrides,
) -> Dict:
    """Book a shipment on the scenario's entitlement, refreshing the version first."""
    entitlement_id = scenario["entitlement"]["id"]
    version = (
        expected_entitlement_version
        if expected_entitlement_version is not None
        else entitlement_version(entitlement_id)
    )
    payload = create_shipment_payload(
        scenario["order"]["id"],
        entitlement_id,
        scenario["tsp"]["id"],
        version,
        shipment_code=shipment_code,
        **overrides,
    )
    return get_success_data(api_client.create_shipment(payload, COUNSELOR))


def setup_booked_shipment(
    tsp_markets: Optional[List[str]] = None,
    shipment_code: str = "SHP-C01",
    shipment_overrides: Optional[Dict[str, Any]] = None,
    **entitlement_kwargs,
) -> Dict[str, Any]:
    """Authorized entitlement plus a provider and one freshly booked shipment."""
    scenario = setup_authorized_entitlement(**entitlement_kwargs)
    scenario["tsp"] = create_tsp(markets=tsp_markets)
    scenario["tsp_headers"] = make_tsp_coordinator_headers(scenario["tsp"]["id"])
    scenario["shipment"] = book_shipment(
        scenario, shipment_code=shipment_code, **(shipment_overrides or {})
    )
    return scenario


def survey_shipment(
    scenario: Dict[str, Any], shipment_id: Optional[str] = None, **overrides
) -> Dict:
    """Record the pre-move survey as the assigned provider's coordinator."""
    return get_success_data(
        api_client.survey_shipment(
            shipment_id or scenario["shipment"]["id"],
            survey_payload(**overrides),
            scenario["tsp_headers"],
        )
    )


def setup_surveyed_shipment(
    survey_overrides: Optional[Dict[str, Any]] = None, **kwargs
) -> Dict[str, Any]:
    """Booked shipment carried through the pre-move survey."""
    scenario = setup_booked_shipment(**kwargs)
    scenario["shipment"] = survey_shipment(scenario, **(survey_overrides or {}))
    return scenario


def setup_awarded_shipment(
    block_overrides: Optional[Dict[str, Any]] = None, **kwargs
) -> Dict[str, Any]:
    """Surveyed shipment awarded into a published weekly capacity block."""
    scenario = setup_surveyed_shipment(**kwargs)
    scenario["block"] = create_capacity_block(
        scenario["tsp"]["id"], **(block_overrides or {})
    )
    award_shipment(scenario["block"]["id"], scenario["shipment"]["id"])
    scenario["block"] = read_capacity_block(scenario["block"]["id"])
    scenario["shipment"] = read_shipment(scenario["shipment"]["id"])
    return scenario


# ---------------------------------------------------------------------------
# Tier 3 — full lifecycle shortcuts
# ---------------------------------------------------------------------------


def pack_shipment(
    scenario: Dict[str, Any], pack_date: str = DEFAULT_PACK_DATE, shipment_id: Optional[str] = None
) -> Dict:
    return get_success_data(
        api_client.pack_shipment(
            shipment_id or scenario["shipment"]["id"],
            pack_payload(pack_date),
            scenario["tsp_headers"],
        )
    )


def pickup_shipment(
    scenario: Dict[str, Any],
    actual_pickup_date: str = DEFAULT_PICKUP_DATE,
    shipment_id: Optional[str] = None,
) -> Dict:
    return get_success_data(
        api_client.pickup_shipment(
            shipment_id or scenario["shipment"]["id"],
            pickup_payload(actual_pickup_date),
            scenario["tsp_headers"],
        )
    )


def record_actual_weight(
    scenario: Dict[str, Any],
    actual_gross_lbs: int,
    actual_tare_lbs: int,
    weigh_date: str = DEFAULT_WEIGH_DATE,
    scale_certified: bool = True,
    shipment_id: Optional[str] = None,
) -> Dict:
    return get_success_data(
        api_client.record_actual_weight(
            shipment_id or scenario["shipment"]["id"],
            record_actual_weight_payload(
                actual_gross_lbs, actual_tare_lbs, weigh_date, scale_certified
            ),
            scenario["tsp_headers"],
        )
    )


def deliver_shipment(
    scenario: Dict[str, Any],
    delivery_date: str = DEFAULT_DELIVERY_DATE,
    shipment_id: Optional[str] = None,
) -> Dict:
    return get_success_data(
        api_client.deliver_shipment(
            shipment_id or scenario["shipment"]["id"],
            deliver_payload(delivery_date),
            scenario["tsp_headers"],
        )
    )


def cancel_shipment(
    scenario: Dict[str, Any], shipment_id: Optional[str] = None, **overrides
) -> Dict:
    return get_success_data(
        api_client.cancel_shipment(
            shipment_id or scenario["shipment"]["id"],
            cancel_shipment_payload(**overrides),
            COUNSELOR,
        )
    )


def setup_packed_shipment(
    pack_date: str = DEFAULT_PACK_DATE, **kwargs
) -> Dict[str, Any]:
    """Awarded shipment with its packing date confirmed."""
    scenario = setup_awarded_shipment(**kwargs)
    scenario["shipment"] = pack_shipment(scenario, pack_date=pack_date)
    return scenario


def setup_weighed_shipment(
    actual_gross_lbs: int = 6200,
    actual_tare_lbs: int = 1500,
    weigh_date: str = DEFAULT_WEIGH_DATE,
    pack_date: str = DEFAULT_PACK_DATE,
    **kwargs,
) -> Dict[str, Any]:
    """Packed shipment whose certified scale weights have been recorded."""
    scenario = setup_packed_shipment(pack_date=pack_date, **kwargs)
    scenario["shipment"] = record_actual_weight(
        scenario, actual_gross_lbs, actual_tare_lbs, weigh_date=weigh_date
    )
    return scenario


def setup_picked_up_shipment(
    actual_gross_lbs: int = 6200,
    actual_tare_lbs: int = 1500,
    actual_pickup_date: str = DEFAULT_PICKUP_DATE,
    **kwargs,
) -> Dict[str, Any]:
    """Shipment weighed on a certified scale and then picked up."""
    scenario = setup_weighed_shipment(
        actual_gross_lbs=actual_gross_lbs, actual_tare_lbs=actual_tare_lbs, **kwargs
    )
    scenario["shipment"] = pickup_shipment(
        scenario, actual_pickup_date=actual_pickup_date
    )
    return scenario


def setup_delivered_shipment(
    delivery_date: str = DEFAULT_DELIVERY_DATE, **kwargs
) -> Dict[str, Any]:
    """Full movement chain through delivery, with the weight of record in place."""
    scenario = setup_picked_up_shipment(**kwargs)
    scenario["shipment"] = deliver_shipment(scenario, delivery_date=delivery_date)
    return scenario


def declare_pro_gear(
    scenario: Dict[str, Any], shipment_id: Optional[str] = None, **overrides
) -> Dict:
    return get_success_data(
        api_client.create_pro_gear_declaration(
            shipment_id or scenario["shipment"]["id"],
            create_pro_gear_payload(**overrides),
            COUNSELOR,
        )
    )


def verify_pro_gear(declaration_id: str, verified_weight_lbs: int) -> Dict:
    return get_success_data(
        api_client.verify_pro_gear_declaration(
            declaration_id, verify_pro_gear_payload(verified_weight_lbs), COUNSELOR
        )
    )


def setup_shipment_with_verified_pro_gear(
    claimed_weight_lbs: int = 500,
    verified_weight_lbs: Optional[int] = None,
    owner: str = "MEMBER",
    **kwargs,
) -> Dict[str, Any]:
    """Surveyed shipment carrying one verified professional-gear declaration."""
    scenario = setup_surveyed_shipment(**kwargs)
    declaration = declare_pro_gear(
        scenario, owner=owner, claimed_weight_lbs=claimed_weight_lbs
    )
    scenario["pro_gear"] = verify_pro_gear(
        declaration["id"],
        claimed_weight_lbs if verified_weight_lbs is None else verified_weight_lbs,
    )
    scenario["shipment"] = read_shipment(scenario["shipment"]["id"])
    return scenario


# ---------------------------------------------------------------------------
# Tier 3 — storage in transit
# ---------------------------------------------------------------------------


def request_sit(
    scenario: Dict[str, Any], entry_date: str, requested_days: int = 10, **overrides
) -> Dict:
    return get_success_data(
        api_client.create_sit_authorization(
            scenario["shipment"]["id"],
            create_sit_payload(entry_date, requested_days=requested_days, **overrides),
            scenario["tsp_headers"],
        )
    )


def authorize_sit(sit_id: str, authorized_days: int) -> Dict:
    return get_success_data(
        api_client.authorize_sit(sit_id, authorize_sit_payload(authorized_days), COUNSELOR)
    )


def release_sit(scenario: Dict[str, Any], sit_id: str, release_date: str) -> Dict:
    return get_success_data(
        api_client.release_sit(
            sit_id, release_sit_payload(release_date), scenario["tsp_headers"]
        )
    )


def setup_sit_authorized_shipment(
    entry_date: str = "2026-09-16T00:00:00Z",
    requested_days: int = 10,
    authorized_days: Optional[int] = None,
    sit_type: str = "ORIGIN",
    **kwargs,
) -> Dict[str, Any]:
    """Picked-up shipment moved into storage under an authorized storage period."""
    scenario = setup_picked_up_shipment(**kwargs)
    sit = request_sit(
        scenario, entry_date, requested_days=requested_days, sit_type=sit_type
    )
    scenario["sit"] = authorize_sit(
        sit["id"], requested_days if authorized_days is None else authorized_days
    )
    scenario["shipment"] = read_shipment(scenario["shipment"]["id"])
    return scenario


# ---------------------------------------------------------------------------
# Tier 3 — claims
# ---------------------------------------------------------------------------


def open_claim(
    scenario: Dict[str, Any], notice_date: str, shipment_id: Optional[str] = None, **overrides
) -> Dict:
    return get_success_data(
        api_client.create_claim(
            shipment_id or scenario["shipment"]["id"],
            create_claim_payload(notice_date, **overrides),
            scenario["member_headers"],
        )
    )


def add_claim_item(
    scenario: Dict[str, Any], claim_id: str, replacement_cost_usd: float, **overrides
) -> Dict:
    return get_success_data(
        api_client.create_claim_item(
            claim_id,
            create_claim_item_payload(replacement_cost_usd, **overrides),
            scenario["member_headers"],
        )
    )


def submit_claim(scenario: Dict[str, Any], claim_id: str) -> Dict:
    return get_success_data(
        api_client.submit_claim(claim_id, {}, scenario["member_headers"])
    )


def review_claim(claim_id: str, headers: Optional[Dict] = None, **overrides) -> Dict:
    return get_success_data(
        api_client.review_claim(claim_id, review_claim_payload(**overrides), headers or EXAMINER)
    )


def disposition_item(
    item_id: str, disposition: str, headers: Optional[Dict] = None, **overrides
) -> Dict:
    return get_success_data(
        api_client.disposition_claim_item(
            item_id,
            disposition_claim_item_payload(disposition, **overrides),
            headers or EXAMINER,
        )
    )


def settle_claim(claim_id: str, headers: Optional[Dict] = None, **overrides) -> Dict:
    return get_success_data(
        api_client.settle_claim(
            claim_id, settle_claim_payload(**overrides), headers or EXAMINER_ALT
        )
    )


def setup_delivered_shipment_with_claim(
    notice_date: str = "2026-08-21T00:00:00Z",
    items: Optional[List[Dict[str, Any]]] = None,
    claim_overrides: Optional[Dict[str, Any]] = None,
    **kwargs,
) -> Dict[str, Any]:
    """Delivered shipment with a draft claim and its items in place.

    `items` is a list of keyword dictionaries for each claim item, the first
    positional value being `replacement_cost_usd`.
    """
    scenario = setup_delivered_shipment(**kwargs)
    scenario["claim"] = open_claim(scenario, notice_date, **(claim_overrides or {}))
    scenario["claim_items"] = []
    for index, item in enumerate(items or [{"replacement_cost_usd": 4200.00}]):
        spec = dict(item)
        cost = spec.pop("replacement_cost_usd")
        spec.setdefault("inventory_item_number", f"INV-{index + 1:04d}")
        scenario["claim_items"].append(
            add_claim_item(scenario, scenario["claim"]["id"], cost, **spec)
        )
    scenario["claim"] = read_claim(scenario["claim"]["id"])
    return scenario


def setup_claim_under_review(**kwargs) -> Dict[str, Any]:
    """Claim filed and taken under review by the first examiner."""
    scenario = setup_delivered_shipment_with_claim(**kwargs)
    submit_claim(scenario, scenario["claim"]["id"])
    scenario["claim"] = review_claim(scenario["claim"]["id"])
    return scenario


def setup_claim_ready_to_settle(
    dispositions: Optional[List[str]] = None, **kwargs
) -> Dict[str, Any]:
    """Claim under review with every item already allowed or denied."""
    scenario = setup_claim_under_review(**kwargs)
    decisions = dispositions or ["ALLOWED"] * len(scenario["claim_items"])
    for item, decision in zip(scenario["claim_items"], decisions):
        disposition_item(item["id"], decision)
    scenario["claim"] = read_claim(scenario["claim"]["id"])
    return scenario


def setup_settled_claim(**kwargs) -> Dict[str, Any]:
    """Claim settled by a second examiner, so the provider's score has moved."""
    scenario = setup_claim_ready_to_settle(**kwargs)
    scenario["claim"] = settle_claim(scenario["claim"]["id"])
    scenario["tsp"] = read_tsp(scenario["tsp"]["id"])
    return scenario


# ---------------------------------------------------------------------------
# Tier 3 — personally procured moves
# ---------------------------------------------------------------------------


def submit_ppm(
    scenario: Dict[str, Any], trip_tickets: List[Dict[str, Any]], **overrides
) -> Dict:
    return get_success_data(
        api_client.create_ppm_submission(
            scenario["shipment"]["id"],
            create_ppm_payload(trip_tickets=trip_tickets, **overrides),
            scenario["member_headers"],
        )
    )


def setup_ppm_submission(
    trip_tickets: Optional[List[Dict[str, Any]]] = None,
    ppm_overrides: Optional[Dict[str, Any]] = None,
    actual_gross_lbs: int = 6200,
    actual_tare_lbs: int = 1500,
    **kwargs,
) -> Dict[str, Any]:
    """Delivered personally procured shipment carrying a submitted packet."""
    shipment_overrides = kwargs.pop("shipment_overrides", None) or {}
    shipment_overrides.setdefault("shipment_method", "PPM")
    scenario = setup_delivered_shipment(
        shipment_overrides=shipment_overrides,
        actual_gross_lbs=actual_gross_lbs,
        actual_tare_lbs=actual_tare_lbs,
        **kwargs,
    )
    scenario["ppm"] = submit_ppm(
        scenario,
        trip_tickets
        if trip_tickets is not None
        else [trip_ticket(1, 9200, 5400), trip_ticket(2, 8600, 5200)],
        **(ppm_overrides or {}),
    )
    return scenario


# ---------------------------------------------------------------------------
# Tier 4 — accumulation and threshold targeting
# ---------------------------------------------------------------------------


def setup_entitlement_over_cap(
    rank_code: str = "E5",
    dependents_count: int = 0,
    spouse_present: bool = False,
    actual_gross_lbs: int = 12000,
    actual_tare_lbs: int = 2000,
    dod_id: str = "7000000001",
    order_number: str = "ORD-C-01",
    shipment_code: str = "SHP-C01",
    **kwargs,
) -> Dict[str, Any]:
    """A weighed shipment whose billable pounds exceed the entitlement's cap.

    The defaults put an E5 without dependents (a 7,000 pound cap) at 10,000 billable
    pounds, which is 3,000 pounds of excess and enough gross excess cost to suspend
    the entitlement.
    """
    scenario = setup_weighed_shipment(
        dod_id=dod_id,
        order_number=order_number,
        shipment_code=shipment_code,
        member_overrides={
            "rank_code": rank_code,
            "dependents_count": dependents_count,
            "spouse_present": spouse_present,
        },
        actual_gross_lbs=actual_gross_lbs,
        actual_tare_lbs=actual_tare_lbs,
        **kwargs,
    )
    scenario["entitlement"] = read_entitlement(scenario["entitlement"]["id"])
    return scenario


def setup_suspended_entitlement(**kwargs) -> Dict[str, Any]:
    """An entitlement suspended because its excess-weight cost exceeds the threshold."""
    scenario = setup_entitlement_over_cap(**kwargs)
    assert scenario["entitlement"]["status"] == "SUSPENDED", (
        "Setup step failed: the entitlement did not suspend, status is "
        f"{scenario['entitlement']['status']}"
    )
    return scenario


def waive_excess_cost(
    entitlement_id: str,
    waived_amount_usd: float,
    headers: Optional[Dict] = None,
    **overrides,
) -> Dict:
    return get_success_data(
        api_client.create_excess_cost_waiver(
            entitlement_id,
            excess_cost_waiver_payload(waived_amount_usd, **overrides),
            headers or ADMIN_ALT,
        )
    )


def setup_second_shipment(
    scenario: Dict[str, Any], shipment_code: str = "SHP-C02", **overrides
) -> Dict:
    """Book a sibling shipment on the same entitlement with a refreshed version."""
    return book_shipment(scenario, shipment_code=shipment_code, **overrides)


def setup_two_shipment_entitlement(
    first_survey: Optional[Dict[str, Any]] = None,
    second_survey: Optional[Dict[str, Any]] = None,
    **kwargs,
) -> Dict[str, Any]:
    """One entitlement carrying two surveyed shipments and their shared block."""
    scenario = setup_awarded_shipment(survey_overrides=first_survey or {}, **kwargs)
    scenario["shipment_2"] = setup_second_shipment(scenario)
    scenario["shipment_2"] = survey_shipment(
        scenario, shipment_id=scenario["shipment_2"]["id"], **(second_survey or {})
    )
    scenario["entitlement"] = read_entitlement(scenario["entitlement"]["id"])
    return scenario


def setup_second_tsp(markets: Optional[List[str]] = None) -> Dict:
    """Onboard a second, distinct provider for cross-provider scenarios."""
    return create_tsp(scac_code="MTLQ", name="Mountain Transit Lines", markets=markets)


# ---------------------------------------------------------------------------
# Tier 5 — finalization and terminal states
# ---------------------------------------------------------------------------


def setup_reconciled_shipment(**kwargs) -> Dict[str, Any]:
    """Delivered shipment whose weight ledger has been frozen."""
    scenario = setup_delivered_shipment(**kwargs)
    scenario["shipment"] = get_success_data(
        api_client.reconcile_weight(scenario["shipment"]["id"], {}, COUNSELOR)
    )
    scenario["entitlement"] = read_entitlement(scenario["entitlement"]["id"])
    return scenario


def setup_cancelled_shipment(**kwargs) -> Dict[str, Any]:
    """Awarded shipment cancelled before pickup, so every unwind has run."""
    scenario = setup_awarded_shipment(**kwargs)
    scenario["shipment"] = cancel_shipment(scenario)
    scenario["entitlement"] = read_entitlement(scenario["entitlement"]["id"])
    scenario["block"] = read_capacity_block(scenario["block"]["id"])
    return scenario


def setup_provider_after_settlement(
    settlement_items: Optional[List[Dict[str, Any]]] = None, **kwargs
) -> Dict[str, Any]:
    """A provider whose performance score already reflects one settled claim."""
    return setup_settled_claim(items=settlement_items, **kwargs)


# ---------------------------------------------------------------------------
# Notification helpers
# ---------------------------------------------------------------------------


def list_notifications(
    shipment_id: str, headers: Optional[Dict] = None, params: Optional[Dict] = None
) -> List[Dict]:
    return get_success_data(
        api_client.list_shipment_notifications(
            shipment_id, headers or COUNSELOR, params=params
        )
    )


def find_notification(shipment_id: str, notification_type: str) -> Dict:
    """Return the shipment's obligation of the given type."""
    rows = list_notifications(shipment_id)
    matches = [row for row in rows if row["notification_type"] == notification_type]
    assert matches, (
        f"Setup step failed: no {notification_type} obligation exists on the shipment"
    )
    return matches[0]
