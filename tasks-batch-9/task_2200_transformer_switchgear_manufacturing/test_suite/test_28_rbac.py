"""The six authorisation rungs: per-endpoint grants, the absence of an admin
override, sales ownership, segregation of duties and witness identity binding."""

from test_helpers import (
    CONTRACT_ADMIN,
    CUSTOMER_REVIEWER,
    DESIGN_ENGINEER,
    MATERIALS_PLANNER,
    PLANT_ADMIN,
    QUALITY_ENGINEER,
    SALES_ENGINEER,
    SALES_ENGINEER_OTHER,
    USER_DESIGN_1,
    USER_REVIEWER_1,
    USER_SALES_1,
    WITNESS_COORDINATOR,
    begin_review,
    create_drawing,
    create_fat,
    create_witness_party,
    disposition_payload,
    engineered_order_payload,
    make_customer_witness_headers,
    make_headers,
    set_clock,
    submit_drawing,
    supplier_payload,
    witness_assignment_payload,
)
from prd_bench_local_runner.testing import validate_error, validate_success
from test_helpers.api_errors import ApiErrorId

_CLOCK = "2026-03-02T08:00:00Z"


def _order_payload(order_number):
    return engineered_order_payload(
        order_number=order_number,
        customer_name="Riverbend Utility",
        product_family="MV_SWITCHGEAR",
        rated_kv=15,
        contract_value_cents=4000000,
        sold_at="2026-01-05T00:00:00Z",
        promised_ship_at="2026-10-01T00:00:00Z",
        owning_sales_user_id=USER_SALES_1,
    )


def _order(api, order_number):
    return validate_success(
        api.create_engineered_order(_order_payload(order_number), CONTRACT_ADMIN), 201
    )


def _drawing_in_review(api, order, drawing_set_code):
    drawing = create_drawing(
        api,
        order["id"],
        drawing_set_code=drawing_set_code,
        authored_by_user_id=USER_DESIGN_1,
    )
    submit_drawing(api, drawing["id"])
    begin_review(api, drawing["id"])
    return drawing


def test_the_engineering_role_holds_no_grant_on_the_commercial_create(api):
    """PRD 2.1: "Once the role is recognised, the server checks that the role is
    authorised for the endpoint being called; if it is not, the response is
    `ERR_ROLE_NOT_PERMITTED` (HTTP 403)"; PRD 4 grants `POST /engineered-orders` to
    "SalesEngineer, ContractAdmin, PlantAdmin".

    Design: Corner/rbac/design_engineer_cannot_create_an_engineered_order
    """
    set_clock(api, _CLOCK)

    validate_error(
        api.create_engineered_order(_order_payload("ORD-CORNER-RB1"), DESIGN_ENGINEER),
        ApiErrorId.ROLE_NOT_PERMITTED,
        403,
    )
    assert api.list_engineered_orders(PLANT_ADMIN).json()["meta"]["total_count"] == 0

    validate_success(
        api.create_engineered_order(_order_payload("ORD-CORNER-RB1"), CONTRACT_ADMIN),
        201,
    )


def test_the_broadest_role_still_has_no_hierarchical_override(api):
    """PRD 4 grants `POST /engineered-orders/{id}/start-production` to
    "MaterialsPlanner" alone; PRD 2.11 places "authentication and authorisation
    (rungs 1–6)" ahead of "state preconditions (34–41)".

    Design: Corner/rbac/plant_admin_cannot_start_production_despite_being_the_broadest_role
    """
    set_clock(api, _CLOCK)
    order = _order(api, "ORD-CORNER-RB2")

    response = api.start_production(order["id"], {}, PLANT_ADMIN)
    validate_error(response, ApiErrorId.ROLE_NOT_PERMITTED, 403)
    assert (
        response.json()["data"]["error_id"]
        != ApiErrorId.ORDER_FULFILLMENT_STATE_INVALID
    )

    # The permitted role reaches the state rung the admin never got to.
    validate_error(
        api.start_production(order["id"], {}, MATERIALS_PLANNER),
        ApiErrorId.ORDER_FULFILLMENT_STATE_INVALID,
        409,
    )


def test_disposition_is_a_customer_side_act_closed_to_the_author_role(api):
    """PRD 4 grants `POST /submittal-drawings/{id}/disposition` to
    "CustomerReviewer"; PRD 2.1: "if it is not, the response is
    `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

    Design: Corner/rbac/design_engineer_cannot_disposition_the_drawing_it_authored
    """
    set_clock(api, _CLOCK)
    order = _order(api, "ORD-CORNER-RB3")
    drawing = _drawing_in_review(api, order, "DS-RB3-A")

    validate_error(
        api.disposition_drawing(
            drawing["id"],
            disposition_payload("APPROVED", USER_REVIEWER_1),
            DESIGN_ENGINEER,
        ),
        ApiErrorId.ROLE_NOT_PERMITTED,
        403,
    )
    assert validate_success(
        api.get_submittal_drawing(drawing["id"], DESIGN_ENGINEER)
    )["status"] == "UNDER_REVIEW"


def test_supplier_suspension_stays_plant_admin_exclusive(api):
    """PRD 4 grants `POST /suppliers/{id}/suspend` to "PlantAdmin"; PRD 2.1: "if it
    is not, the response is `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

    Design: Corner/rbac/quality_engineer_cannot_suspend_a_supplier
    """
    set_clock(api, _CLOCK)
    supplier = validate_success(
        api.create_supplier(
            supplier_payload(
                supplier_code="SUP-RB4",
                legal_name="Northline Copperworks GmbH",
                region="EU",
            ),
            PLANT_ADMIN,
        ),
        201,
    )

    validate_error(
        api.suspend_supplier(
            supplier["id"], {"reason": "quality drift"}, QUALITY_ENGINEER
        ),
        ApiErrorId.ROLE_NOT_PERMITTED,
        403,
    )
    assert validate_success(
        api.get_supplier(supplier["id"], QUALITY_ENGINEER)
    )["status"] == "APPROVED"


def test_the_grant_is_per_endpoint_and_not_per_entity(api):
    """PRD 4 grants `GET /engineered-orders/{id}` to "WitnessCoordinator,
    CustomerWitness, CustomerReviewer, QualityEngineer", and grants
    `GET /engineered-orders` to "PlantAdmin, SalesEngineer, ContractAdmin,
    DesignEngineer, MaterialsPlanner, TestEngineer, WitnessCoordinator,
    CustomerReviewer, QualityEngineer, ComplianceOfficer, LogisticsCoordinator,
    FieldServiceEngineer".

    Design: Corner/rbac/customer_witness_may_read_one_order_but_not_list_all_orders
    """
    set_clock(api, _CLOCK)
    order = _order(api, "ORD-CORNER-RB5")
    party = create_witness_party(
        api,
        party_code="WP-RB5",
        display_name="Riverbend Inspection",
        party_type="CUSTOMER",
        home_region="NA",
        daily_witness_capacity=1,
        credential_expires_at="2027-12-31T00:00:00Z",
    )
    witness = make_customer_witness_headers(party["id"])

    validate_error(
        api.list_engineered_orders(witness), ApiErrorId.ROLE_NOT_PERMITTED, 403
    )
    single = validate_success(api.get_engineered_order(order["id"], witness))
    assert single["id"] == order["id"]


def test_the_money_view_is_closed_to_the_role_that_drives_production(api):
    """PRD 4 grants `GET /engineered-orders/{id}/financial-summary` to
    "ContractAdmin, SalesEngineer, PlantAdmin"; PRD 2.1: "if it is not, the response
    is `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

    Design: Corner/rbac/materials_planner_cannot_read_the_order_financial_summary
    """
    set_clock(api, _CLOCK)
    order = _order(api, "ORD-CORNER-RB6")

    validate_error(
        api.get_order_financial_summary(order["id"], MATERIALS_PLANNER),
        ApiErrorId.ROLE_NOT_PERMITTED,
        403,
    )
    validate_success(api.get_order_financial_summary(order["id"], CONTRACT_ADMIN))


def test_a_granted_sales_engineer_is_still_bound_to_the_order_it_owns(api):
    """PRD 2.1: "On every order-scoped write a `SalesEngineer` performs, the header
    `X-User-ID` must equal the `owning_sales_user_id` recorded on the order in scope;
    otherwise the request is rejected with `ERR_NOT_ORDER_OWNER` (HTTP 403)."

    Design: Corner/rbac/sales_engineer_cannot_create_an_order_owned_by_another_sales_user
    """
    set_clock(api, _CLOCK)

    response = api.create_engineered_order(
        _order_payload("ORD-CORNER-RB7"), SALES_ENGINEER_OTHER
    )
    validate_error(response, ApiErrorId.NOT_ORDER_OWNER, 403)
    assert response.json()["data"]["error_id"] != ApiErrorId.ROLE_NOT_PERMITTED

    owned = validate_success(
        api.create_engineered_order(_order_payload("ORD-CORNER-RB7"), SALES_ENGINEER),
        201,
    )
    assert owned["owning_sales_user_id"] == USER_SALES_1


def test_the_reviewer_may_not_wear_the_authors_identity(api):
    """PRD 2.1: "Four operations enforce **segregation of duties** by comparing the
    acting `X-User-ID` against the user id that performed the paired upstream step,
    and reject a match with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). Recording a
    drawing disposition requires that the acting reviewer differ from the revision's
    author."

    Design: Corner/rbac/customer_reviewer_reusing_the_author_user_id_returns_segregation_of_duties
    """
    set_clock(api, _CLOCK)
    order = _order(api, "ORD-CORNER-RB8")
    drawing = _drawing_in_review(api, order, "DS-RB8-A")

    validate_error(
        api.disposition_drawing(
            drawing["id"],
            disposition_payload("APPROVED", USER_DESIGN_1),
            make_headers(USER_DESIGN_1, "CustomerReviewer"),
        ),
        ApiErrorId.SEGREGATION_OF_DUTIES,
        403,
    )
    assert validate_success(
        api.get_submittal_drawing(drawing["id"], CUSTOMER_REVIEWER)
    )["status"] == "UNDER_REVIEW"

    approved = validate_success(
        api.disposition_drawing(
            drawing["id"],
            disposition_payload("APPROVED", USER_REVIEWER_1),
            make_headers(USER_REVIEWER_1, "CustomerReviewer"),
        )
    )
    assert approved["status"] == "APPROVED"


def test_a_witness_identity_reaches_only_its_own_invitation(api):
    """PRD 2.1: "On the confirm and decline operations for a witness assignment, a
    `CustomerWitness` whose `X-User-ID` does not equal the assignment's
    `witness_party_id` is rejected with `ERR_WITNESS_IDENTITY_MISMATCH` (HTTP 403)."

    Design: Corner/rbac/customer_witness_cannot_decline_another_parties_assignment
    """
    set_clock(api, _CLOCK)
    order = _order(api, "ORD-CORNER-RB9")
    fat = create_fat(
        api,
        order["id"],
        test_duration_hours=8,
        witness_required=True,
        requires_impulse=False,
    )
    party_a = create_witness_party(
        api,
        party_code="WP-RB9-A",
        display_name="Riverbend Inspection",
        party_type="CUSTOMER",
        home_region="NA",
        daily_witness_capacity=2,
        credential_expires_at="2027-12-31T00:00:00Z",
    )
    party_b = create_witness_party(
        api,
        party_code="WP-RB9-B",
        display_name="Northline Lab",
        party_type="THIRD_PARTY_LAB",
        home_region="NA",
        daily_witness_capacity=2,
        credential_expires_at="2027-12-31T00:00:00Z",
    )
    assignment = validate_success(
        api.create_witness_assignment(
            fat["id"],
            witness_assignment_payload(party_a["id"], travel_region="NA"),
            WITNESS_COORDINATOR,
        ),
        201,
    )

    validate_error(
        api.decline_witness_assignment(
            assignment["id"],
            {"decline_reason": "not our scope"},
            make_customer_witness_headers(party_b["id"]),
        ),
        ApiErrorId.WITNESS_IDENTITY_MISMATCH,
        403,
    )
    assert validate_success(
        api.get_witness_assignment(assignment["id"], WITNESS_COORDINATOR)
    )["status"] == "INVITED"

    declined = validate_success(
        api.decline_witness_assignment(
            assignment["id"],
            {"decline_reason": "not our scope"},
            make_customer_witness_headers(party_a["id"]),
        )
    )
    assert declined["status"] == "DECLINED"
