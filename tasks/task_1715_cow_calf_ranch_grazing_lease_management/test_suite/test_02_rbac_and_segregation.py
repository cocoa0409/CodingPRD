"""Role-based access control and segregation-of-duties checks."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_breeding_season,
    create_herd_group,
    create_pasture,
    create_pasture_payload,
    create_preg_check_payload,
    create_ranch,
    create_sale_lot,
    get_success_data,
    make_herd_manager_headers,
    make_ranch_manager_headers,
    make_range_manager_headers,
    make_sales_agent_headers,
    setup_delivered_lot,
    setup_issued_statement,
    setup_weaned_crop,
    validate_error,
    validate_success,
)

RANCH_MGR = TEST_USERS["ranch_manager_headers"]
RANGE_MGR = TEST_USERS["range_manager_headers"]
HERD_MGR = TEST_USERS["herd_manager_headers"]
SALES_AGENT = TEST_USERS["sales_agent_headers"]


class TestExclusiveRoleDenied:
    def test_salesagent_cannot_create_pasture(self, api):
        """PRD §2.1: "A request whose role is valid but not listed among the
        roles authorized for the target endpoint is rejected with
        `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD §2.1: "`RangeManager`, the range and lease operator responsible for
        pastures, grazing leases, lease statements, grazing assignments, and
        drought assessments"

        Design: Corner/rbac/rbac_salesagent_cannot_create_pasture
        """
        ranch = create_ranch(name="R")
        resp = api.create_pasture(
            create_pasture_payload(ranch["id"], name="P", base_capacity_aum=100),
            SALES_AGENT)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, expected_status=403)

    def test_herdmanager_cannot_approve_statement(self, api):
        """PRD §2.1: "A request whose role is valid but not listed among the
        roles authorized for the target endpoint is rejected with
        `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD §3.2: "Approval belongs to a `RanchManager`, and per §2.10 the
        approver's `X-User-ID` must differ from `recorded_by_user_id`, with a
        violation rejected as `ERR_SEGREGATION_OF_DUTIES`; approval stamps
        `approved_by_user_id`."

        Design: Corner/rbac/rbac_herdmanager_cannot_approve_statement
        """
        ctx = setup_issued_statement()
        stmt = ctx["statement"]
        assert stmt["statement_status"] == "ISSUED"

        # HerdManager is not the approval role even with a fresh user id.
        resp = api.approve_statement(stmt["id"],
                                     make_herd_manager_headers("u-herd-7"))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, expected_status=403)

        after = get_success_data(api.get_lease_statement(stmt["id"], RANGE_MGR))
        assert after["statement_status"] == "ISSUED", (
            "a rejected approval must not move the statement"
        )

    def test_rangemanager_cannot_settle_lot(self, api):
        """PRD §3.7: "Settlement is the terminal act and belongs to the
        `RanchManager`"
        PRD §2.1: "A request whose role is valid but not listed among the roles
        authorized for the target endpoint is rejected with `ERR_FORBIDDEN_ROLE`
        (HTTP 403)."

        Design: Corner/rbac/rbac_rangemanager_cannot_settle_lot
        """
        ctx = setup_weaned_crop(steer_head=40, heifer_head=0)
        lot = create_sale_lot(ctx["crop"]["id"], ctx["ranch"]["id"],
                              lot_class="STEER", head_count=10)
        assert lot["lot_status"] == "DRAFT"

        # Role check (cascade step 2) precedes the state machine entirely.
        resp = api.settle_lot(lot["id"], make_range_manager_headers("u-range-1"))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, expected_status=403)

    def test_ranchmanager_cannot_record_pregcheck(self, api):
        """PRD §2.1: "`RanchManager`, the ranch owner or manager, who holds
        approval authority over lease statements, sale-lot settlements, drought
        policy, and destock-order waivers, but who may not record field data"
        PRD §2.1: "A request whose role is valid but not listed among the roles
        authorized for the target endpoint is rejected with `ERR_FORBIDDEN_ROLE`
        (HTTP 403)."

        Design: Corner/rbac/rbac_ranchmanager_cannot_record_pregcheck
        """
        ranch = create_ranch(name="R")
        group = create_herd_group(ranch["id"], group_name="G")
        season = create_breeding_season(ranch["id"], group["id"],
                                        exposed_head_count=25)
        resp = api.create_preg_check(
            create_preg_check_payload(season["id"], ranch["id"]), RANCH_MGR)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, expected_status=403)


class TestSegregationOfDuties:
    def test_sale_settle_segregation_same_user(self, api):
        """PRD §2.10: "A sale lot is born with `sold_by_user_id` stamped from
        the `SalesAgent` who created it; settlement requires a `RanchManager`
        whose `X-User-ID` is different from that seller, and the settlement
        stamps `settled_by_user_id`. Either comparison failing rejects the
        request with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

        Design: Corner/rbac/rbac_sale_settle_segregation_same_user
        """
        ctx = setup_delivered_lot(steer_head=10, heifer_head=0, certified=False,
                                  delivered_avg_weight_lbs=500,
                                  seller_user_id="u-sale-1")
        lot = ctx["lot"]
        assert lot["lot_status"] == "DELIVERED"
        assert lot["sold_by_user_id"] == "u-sale-1"

        # The seller wearing the RanchManager hat is still the seller.
        resp = api.settle_lot(lot["id"], make_ranch_manager_headers("u-sale-1"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
                       expected_status=403)

        settled = validate_success(api.settle_lot(
            lot["id"], make_ranch_manager_headers("u-ranch-9")))
        assert settled["lot_status"] == "SETTLED"
        assert settled["settled_by_user_id"] == "u-ranch-9"


class TestSharedReads:
    def test_get_endpoints_shared_all_roles(self, api):
        """PRD §2.1: "Every read endpoint in the system is open to all four
        roles; write capabilities are role-specific as enumerated in §4."

        Design: Corner/rbac/rbac_get_endpoints_shared_all_roles
        """
        ranch = create_ranch(name="R")
        for headers in (RANGE_MGR, HERD_MGR, SALES_AGENT):
            data = validate_success(api.get_ranch(ranch["id"], headers))
            assert data["id"] == ranch["id"]
        # RanchManager read proven by creation-era access.
        data = validate_success(api.get_ranch(ranch["id"], RANCH_MGR))
        assert data["id"] == ranch["id"]
