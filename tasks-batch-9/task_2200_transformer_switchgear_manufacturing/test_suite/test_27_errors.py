"""The authorisation rungs, payload typing, pair uniqueness, absent collections
and the existence sweep over both path and body identifiers."""

from test_helpers import (
    CONTRACT_ADMIN,
    PLANT_ADMIN,
    TEST_ENGINEER,
    WITNESS_COORDINATOR,
    attach_escalation_clause,
    commodity_index_point_payload,
    create_fat,
    create_order,
    create_witness_party,
    engineered_order_payload,
    escalation_adjustment_payload,
    make_customer_witness_headers,
    make_headers,
    order_version,
    set_clock,
    witness_assignment_payload,
)
from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_success,
)
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


def test_the_headerless_request_never_reaches_the_row_lookup(api):
    """PRD 2.1: "If either header is absent or present but empty, the request is
    rejected with `ERR_MISSING_AUTH_HEADER` (HTTP 401). This is the very first check
    the server performs, ahead of every other validation in the system."

    Design: Corner/errors/request_without_auth_headers_returns_missing_auth_header
    """
    set_clock(api, _CLOCK)

    response = api.get_engineered_order(NON_EXISTENT_UUID, {})
    validate_error(response, ApiErrorId.MISSING_AUTH_HEADER, 401)
    assert response.json()["data"]["error_id"] != ApiErrorId.ORDER_NOT_FOUND


def test_a_plausible_but_undeclared_role_is_rejected_before_the_grant_check(api):
    """PRD 2.1: "A value that is not one of those thirteen strings is rejected with
    `ERR_UNKNOWN_ROLE` (HTTP 401). Once the role is recognised, the server checks
    that the role is authorised for the endpoint being called; if it is not, the
    response is `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

    Design: Corner/errors/unrecognised_role_header_returns_unknown_role
    """
    set_clock(api, _CLOCK)
    order = _order(api, "ORD-CORNER-ER2")

    validate_error(
        api.get_engineered_order(order["id"], make_headers("u-shop-9", "Machinist")),
        ApiErrorId.UNKNOWN_ROLE,
        401,
    )


def test_an_unbacked_witness_identity_fails_as_hard_as_an_unknown_role(api):
    """PRD 2.1: "Because that role is entity-backed, recognising the role is not
    enough: the `X-User-ID` must additionally resolve to a live witness party row,
    and if it does not, the request fails with `ERR_UNKNOWN_ROLE` (HTTP 401) just as
    an unrecognised role string would."

    Design: Corner/errors/customer_witness_whose_user_id_is_not_a_witness_party_returns_unknown_role
    """
    set_clock(api, _CLOCK)
    order = _order(api, "ORD-CORNER-ER3")
    fat = create_fat(
        api,
        order["id"],
        test_duration_hours=10,
        witness_required=True,
        requires_impulse=False,
    )

    validate_error(
        api.get_factory_acceptance_test(
            fat["id"], make_customer_witness_headers("u-not-a-party")
        ),
        ApiErrorId.UNKNOWN_ROLE,
        401,
    )
    readable = validate_success(
        api.get_factory_acceptance_test(fat["id"], TEST_ENGINEER)
    )
    assert readable["status"] == "REQUESTED"


def test_a_quoted_cent_amount_is_not_quietly_coerced_into_an_integer(api):
    """PRD 2.11: "Field types must match their declared types — cent amounts, basis
    points and unit quantities are integers — or the response is
    `ERR_FIELD_TYPE_INVALID` (HTTP 422)."

    Design: Corner/errors/contract_value_cents_sent_as_string_returns_field_type_invalid
    """
    set_clock(api, _CLOCK)

    validate_error(
        api.create_engineered_order(
            engineered_order_payload(
                order_number="ORD-CORNER-ER4",
                customer_name="Riverbend Utility",
                product_family="MV_SWITCHGEAR",
                rated_kv=15,
                contract_value_cents="4000000",
                sold_at="2026-01-05T00:00:00Z",
                promised_ship_at="2026-10-01T00:00:00Z",
            ),
            CONTRACT_ADMIN,
        ),
        ApiErrorId.FIELD_TYPE_INVALID,
        422,
    )
    assert api.list_engineered_orders(PLANT_ADMIN).json()["meta"]["total_count"] == 0


def test_the_index_key_is_the_commodity_and_month_pair_not_the_month(api):
    """PRD 3.3: "At most one point may exist per commodity-and-month pair, a
    duplicate being rejected with `ERR_DUPLICATE_INDEX_POINT`."

    Design: Corner/errors/second_index_point_for_same_commodity_and_month_returns_duplicate_index_point
    """
    set_clock(api, _CLOCK)
    validate_success(
        api.create_commodity_index_point(
            commodity_index_point_payload(
                commodity="COPPER",
                index_month="2026-01",
                index_value=10000,
                published_at="2026-02-05T00:00:00Z",
                is_provisional=False,
            ),
            CONTRACT_ADMIN,
        ),
        201,
    )

    collision = commodity_index_point_payload(
        commodity="COPPER",
        index_month="2026-01",
        index_value=11500,
        published_at="2026-02-20T00:00:00Z",
        is_provisional=True,
    )
    validate_error(
        api.create_commodity_index_point(collision, CONTRACT_ADMIN),
        ApiErrorId.DUPLICATE_INDEX_POINT,
        409,
    )

    # Same month, different commodity: a different key, therefore accepted.
    validate_success(
        api.create_commodity_index_point(
            commodity_index_point_payload(
                commodity="ALUMINUM",
                index_month="2026-01",
                index_value=11500,
                published_at="2026-02-20T00:00:00Z",
                is_provisional=True,
            ),
            CONTRACT_ADMIN,
        ),
        201,
    )


def test_an_empty_index_table_is_a_missing_point_not_a_zero_escalation(api):
    """PRD 3.3: "The **base level** for a commodity is the `index_value` of the
    usable row whose `index_month` equals the clause's `base_index_month`; if no such
    row exists for any commodity carrying a non-zero weighting, the request fails
    with `ERR_INDEX_POINT_MISSING`."

    Design: Corner/errors/escalation_adjustment_with_no_index_points_at_all_returns_index_point_missing
    """
    set_clock(api, _CLOCK)
    order = _order(
        api,
        "ORD-CORNER-ER6",
        product_family="POWER_TRANSFORMER",
        rated_kv=69,
        contract_value_cents=9000000,
    )
    clause = attach_escalation_clause(
        api,
        order["id"],
        copper_weight_bp=6000,
        aluminum_weight_bp=2000,
        core_steel_weight_bp=2000,
        escalatable_base_cents=5000000,
        base_index_month="2026-01",
        cap_bp=1000,
        collar_bp=200,
        de_escalation_enabled=True,
        final_window_end_month="2026-06",
    )

    validate_error(
        api.create_escalation_adjustment(
            order["id"],
            escalation_adjustment_payload(
                clause["id"], order_version(api, order["id"]), variant="PROVISIONAL"
            ),
            CONTRACT_ADMIN,
        ),
        ApiErrorId.INDEX_POINT_MISSING,
        422,
    )
    body = api.list_escalation_adjustments(CONTRACT_ADMIN).json()
    assert body["meta"]["total_count"] == 0


def test_the_same_party_cannot_be_invited_twice_to_one_test(api):
    """PRD 3.5: "At most one non-terminal assignment may pair a given test with a
    given party, a second attempt failing with `ERR_WITNESS_ALREADY_ASSIGNED`."

    Design: Corner/errors/second_assignment_of_the_same_witness_party_returns_witness_already_assigned
    """
    set_clock(api, _CLOCK)
    order = _order(api, "ORD-CORNER-ER8")
    fat = create_fat(
        api,
        order["id"],
        test_duration_hours=8,
        witness_required=True,
        requires_impulse=False,
    )
    party_a = create_witness_party(
        api,
        party_code="WP-ER8-A",
        display_name="Riverbend Inspection",
        party_type="CUSTOMER",
        home_region="NA",
        daily_witness_capacity=2,
        credential_expires_at="2027-12-31T00:00:00Z",
    )
    party_b = create_witness_party(
        api,
        party_code="WP-ER8-B",
        display_name="Northline Lab",
        party_type="THIRD_PARTY_LAB",
        home_region="NA",
        daily_witness_capacity=2,
        credential_expires_at="2027-12-31T00:00:00Z",
    )
    validate_success(
        api.create_witness_assignment(
            fat["id"],
            witness_assignment_payload(party_a["id"], travel_region="NA"),
            WITNESS_COORDINATOR,
        ),
        201,
    )

    validate_error(
        api.create_witness_assignment(
            fat["id"],
            witness_assignment_payload(party_a["id"], travel_region="NA"),
            WITNESS_COORDINATOR,
        ),
        ApiErrorId.WITNESS_ALREADY_ASSIGNED,
        409,
    )

    validate_success(
        api.create_witness_assignment(
            fat["id"],
            witness_assignment_payload(party_b["id"], travel_region="NA"),
            WITNESS_COORDINATOR,
        ),
        201,
    )
    body = api.list_fat_witness_assignments(fat["id"], WITNESS_COORDINATOR).json()
    assert len(body["data"]) == 2
    assert body["meta"]["total_count"] == 2


def test_an_unknown_adjustment_id_answers_with_its_own_family_code(api):
    """PRD 2.5: "An unresolvable engineered order yields `ERR_ORDER_NOT_FOUND`...
    an escalation adjustment, `ERR_ADJUSTMENT_NOT_FOUND`... All twenty are HTTP 404."

    Design: Corner/errors/submit_action_on_unknown_adjustment_id_returns_adjustment_not_found
    """
    set_clock(api, _CLOCK)

    validate_error(
        api.submit_escalation_adjustment(NON_EXISTENT_UUID, {}, CONTRACT_ADMIN),
        ApiErrorId.ADJUSTMENT_NOT_FOUND,
        404,
    )


def test_a_body_borne_foreign_key_is_swept_for_existence_like_a_path_id(api):
    """PRD 2.11: "Body-borne references are resolved on the same rung as their
    family: an order named by `engineered_order_id`... a clause named by
    `escalation_clause_id`"; and the band order puts "existence resolution (7–26)"
    ahead of "optimistic concurrency (32–33)".

    Design: Corner/errors/adjustment_creation_naming_an_unknown_clause_returns_clause_not_found
    """
    set_clock(api, _CLOCK)
    order = _order(
        api,
        "ORD-CORNER-E10",
        product_family="POWER_TRANSFORMER",
        rated_kv=69,
        contract_value_cents=9000000,
    )

    validate_error(
        api.create_escalation_adjustment(
            order["id"],
            escalation_adjustment_payload(
                NON_EXISTENT_UUID, order["version"], variant="PROVISIONAL"
            ),
            CONTRACT_ADMIN,
        ),
        ApiErrorId.CLAUSE_NOT_FOUND,
        404,
    )
    body = api.list_order_escalation_clauses(order["id"], CONTRACT_ADMIN).json()
    assert body["data"] == []
