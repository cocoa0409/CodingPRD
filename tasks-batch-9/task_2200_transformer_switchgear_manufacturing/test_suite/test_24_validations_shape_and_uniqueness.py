"""Pagination shape, global and scoped uniqueness, aggregate cardinality, the
index window and the enum rung that outranks a state rung."""

from test_helpers import (
    CONTRACT_ADMIN,
    CUSTOMER_REVIEWER,
    MATERIALS_PLANNER,
    PLANT_ADMIN,
    USER_REVIEWER_1,
    create_drawing,
    create_order,
    create_supplier,
    disposition_payload,
    engineered_order_payload,
    escalation_clause_payload,
    long_lead_component_payload,
    set_clock,
)
from prd_bench_local_runner.testing import validate_error, validate_success
from test_helpers.api_errors import ApiErrorId

_CLOCK = "2026-03-02T08:00:00Z"


def _order(api, order_number, **overrides):
    payload = dict(
        order_number=order_number,
        customer_name="Riverbend Utility",
        product_family="MV_SWITCHGEAR",
        rated_kv=15,
        contract_value_cents=4000000,
        sold_at="2026-01-05T00:00:00Z",
        promised_ship_at="2026-10-01T00:00:00Z",
    )
    payload.update(overrides)
    return create_order(api, **payload)


def test_a_page_size_of_zero_is_a_four_hundred_not_a_four_twenty_two(api):
    """PRD 2.3: "`limit` controls page size; it defaults to 10 when omitted, must
    be at least 1 and at most 100... A `limit` below 1 or above 100, or a negative
    `offset`, is a pagination-shape violation and is rejected with
    `ERR_INVALID_PAGINATION` (HTTP 400)"; PRD 2.2: "The `meta` object for error
    responses contains only `api_request_id` and `api_request_timestamp`."

    Design: Corner/validations/list_engineered_orders_with_limit_zero_returns_invalid_pagination
    """
    set_clock(api, _CLOCK)
    _order(api, "ORD-CORNER-V1")

    response = api.list_engineered_orders(PLANT_ADMIN, {"limit": 0})
    validate_error(response, ApiErrorId.INVALID_PAGINATION, 400)
    body = response.json()
    assert body["response_type"] == "error"
    assert not isinstance(body["data"], list)
    assert "total_count" not in body["meta"]


def test_the_page_size_ceiling_is_inclusive_at_one_hundred(api):
    """PRD 2.3: `limit` "must be at least 1 and at most 100"; "`limit` and `offset`
    echo the effective values used for the query, `total_count` is the number of
    rows matching the filter before pagination is applied, and `has_more` is true
    when rows remain beyond the current page."

    Design: Corner/validations/list_engineered_orders_accepts_limit_one_hundred_and_rejects_one_hundred_one
    """
    set_clock(api, _CLOCK)
    _order(api, "ORD-CORNER-V2")

    accepted = api.list_engineered_orders(PLANT_ADMIN, {"limit": 100, "offset": 0})
    assert accepted.status_code == 200
    meta = accepted.json()["meta"]
    assert meta["limit"] == 100
    assert meta["offset"] == 0
    assert meta["total_count"] == 1
    assert meta["has_more"] is False

    validate_error(
        api.list_engineered_orders(PLANT_ADMIN, {"limit": 101}),
        ApiErrorId.INVALID_PAGINATION,
        400,
    )


def test_an_order_number_is_unique_across_the_whole_plant(api):
    """PRD 3.1: an order carries an "`order_number` — which must be unique across
    every order and between 6 and 24 characters long, a duplicate being rejected
    with `ERR_DUPLICATE_ORDER_NUMBER`".

    Design: Corner/validations/duplicate_order_number_on_second_create_returns_duplicate_order_number
    """
    set_clock(api, _CLOCK)
    _order(api, "ORD-CORNER-V3")

    validate_error(
        api.create_engineered_order(
            engineered_order_payload(
                order_number="ORD-CORNER-V3",
                customer_name="Northgate Cooperative",
                product_family="POWER_TRANSFORMER",
                rated_kv=69,
                contract_value_cents=9000000,
                sold_at="2026-02-01T00:00:00Z",
                promised_ship_at="2027-01-01T00:00:00Z",
            ),
            PLANT_ADMIN,
        ),
        ApiErrorId.DUPLICATE_ORDER_NUMBER,
        409,
    )
    body = api.list_engineered_orders(PLANT_ADMIN).json()
    assert body["meta"]["total_count"] == 1
    assert body["data"][0]["customer_name"] == "Riverbend Utility"


def test_a_part_number_is_unique_only_within_its_own_supplier(api):
    """PRD 3.4: "A `MaterialsPlanner` or `PlantAdmin` registers a
    `LongLeadComponent` with a `part_number` unique within that supplier."

    Design: Corner/validations/duplicate_part_number_within_same_supplier_returns_duplicate_code
    """
    set_clock(api, _CLOCK)
    supplier_a = create_supplier(
        api,
        supplier_code="SUP-V4-A",
        legal_name="Copperline Windings AG",
        region="NA",
    )
    supplier_b = create_supplier(
        api,
        supplier_code="SUP-V4-B",
        legal_name="Meridian Interrupters SA",
        region="EU",
    )
    shared = long_lead_component_payload(
        part_number="PN-SHARED-01",
        category="CT_VT",
        lead_time_days=45,
        quantity_on_hand=6,
        allocation_policy="PREEMPTIBLE",
    )
    validate_success(
        api.create_long_lead_component(supplier_a["id"], shared, MATERIALS_PLANNER), 201
    )
    # The same part number under a different vendor is a different part.
    validate_success(
        api.create_long_lead_component(supplier_b["id"], shared, MATERIALS_PLANNER), 201
    )

    validate_error(
        api.create_long_lead_component(
            supplier_a["id"],
            long_lead_component_payload(
                part_number="PN-SHARED-01",
                category="BREAKER_FRAME",
                lead_time_days=300,
                quantity_on_hand=2,
                allocation_policy="PROTECTED",
            ),
            MATERIALS_PLANNER,
        ),
        ApiErrorId.DUPLICATE_CODE,
        409,
    )
    body = api.list_supplier_long_lead_components(
        supplier_a["id"], MATERIALS_PLANNER
    ).json()
    assert body["meta"]["total_count"] == 1


def test_an_order_may_carry_at_most_one_escalation_clause(api):
    """PRD 3.3: a `ContractAdmin` attaches "one **escalation clause** to an order;
    a second attempt is rejected with `ERR_CLAUSE_ALREADY_EXISTS`."

    Design: Corner/validations/second_escalation_clause_on_same_order_returns_clause_already_exists
    """
    set_clock(api, _CLOCK)
    order = _order(
        api,
        "ORD-CORNER-V5",
        product_family="POWER_TRANSFORMER",
        rated_kv=69,
        contract_value_cents=9000000,
        promised_ship_at="2027-01-01T00:00:00Z",
    )
    validate_success(
        api.create_escalation_clause(
            order["id"],
            escalation_clause_payload(
                copper_weight_bp=6000,
                aluminum_weight_bp=2000,
                core_steel_weight_bp=2000,
                escalatable_base_cents=3000000,
                base_index_month="2026-01",
                cap_bp=1000,
                collar_bp=200,
                de_escalation_enabled=False,
                final_window_end_month="2026-06",
            ),
            CONTRACT_ADMIN,
        ),
        201,
    )

    validate_error(
        api.create_escalation_clause(
            order["id"],
            escalation_clause_payload(
                copper_weight_bp=4000,
                aluminum_weight_bp=4000,
                core_steel_weight_bp=2000,
                escalatable_base_cents=1000000,
                base_index_month="2026-02",
                cap_bp=500,
                collar_bp=100,
                de_escalation_enabled=True,
                final_window_end_month="2026-08",
            ),
            CONTRACT_ADMIN,
        ),
        ApiErrorId.CLAUSE_ALREADY_EXISTS,
        409,
    )
    body = api.list_order_escalation_clauses(order["id"], CONTRACT_ADMIN).json()
    assert body["meta"]["total_count"] == 1
    assert body["data"][0]["copper_weight_bp"] == 6000


def test_an_inverted_index_window_is_refused_without_consulting_any_index(api):
    """PRD 3.3: "`base_index_month` must be strictly earlier than
    `final_window_end_month`, or the create fails with `ERR_INDEX_WINDOW_INVALID`."

    Design: Corner/validations/escalation_clause_with_base_month_after_final_month_returns_index_window_invalid
    """
    set_clock(api, _CLOCK)
    order = _order(
        api,
        "ORD-CORNER-V6",
        product_family="POWER_TRANSFORMER",
        rated_kv=69,
        contract_value_cents=9000000,
        promised_ship_at="2027-01-01T00:00:00Z",
    )

    validate_error(
        api.create_escalation_clause(
            order["id"],
            escalation_clause_payload(
                copper_weight_bp=6000,
                aluminum_weight_bp=2000,
                core_steel_weight_bp=2000,
                escalatable_base_cents=3000000,
                base_index_month="2026-06",
                cap_bp=1000,
                collar_bp=200,
                de_escalation_enabled=False,
                final_window_end_month="2026-01",
            ),
            CONTRACT_ADMIN,
        ),
        ApiErrorId.INDEX_WINDOW_INVALID,
        422,
    )
    body = api.list_order_escalation_clauses(order["id"], CONTRACT_ADMIN).json()
    assert body["data"] == []
    assert body["meta"]["total_count"] == 0


def test_an_unknown_disposition_verdict_is_read_before_the_drawing_state(api):
    """PRD 2.11: the band order runs "payload shape and enum domains (27–31),
    optimistic concurrency (32–33), state preconditions (34–41)"; an enum
    violation is `ERR_ENUM_VALUE_INVALID` (HTTP 422).

    Design: Corner/validations/invalid_disposition_enum_beats_wrong_drawing_state_in_priority_ladder
    """
    set_clock(api, _CLOCK)
    order = _order(api, "ORD-CORNER-V7")
    drawing = create_drawing(api, order["id"], drawing_set_code="DS-100")

    validate_error(
        api.disposition_drawing(
            drawing["id"],
            disposition_payload("REJECTED", USER_REVIEWER_1),
            CUSTOMER_REVIEWER,
        ),
        ApiErrorId.ENUM_VALUE_INVALID,
        422,
    )
    untouched = validate_success(api.get_submittal_drawing(drawing["id"], PLANT_ADMIN))
    assert untouched["status"] == "DRAFT"
    assert untouched["reviewed_by_user_id"] is None
