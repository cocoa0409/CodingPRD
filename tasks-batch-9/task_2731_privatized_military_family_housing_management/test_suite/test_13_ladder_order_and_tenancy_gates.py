"""Ladder precedence, ownership scoping and the gates on writing a tenancy."""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_success,
)

from test_helpers import assertions as asserts
from test_helpers import constants as const
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import TEST_USERS, make_service_member_headers

STARTUP_CLOCK = const.CLOCK_STARTUP_DEFAULT
BEFORE_ARRIVAL_CLOCK = fx.CLOCK_BEFORE_ARRIVAL
MOVE_IN_CLOCK = fx.CLOCK_AT_MOVE_IN
ANONYMOUS = {"Content-Type": "application/json"}
ADMIN = TEST_USERS["platform_admin_headers"]
MANAGER = TEST_USERS["property_manager_headers"]
TECH = TEST_USERS["maintenance_tech_headers"]
HOUSING_OFFICE = TEST_USERS["installation_housing_office_headers"]

OUT_OF_RANGE_BEDROOM_COUNT = 9
LEGAL_BEDROOM_COUNT = 3
UNKNOWN_INSTALLATION_ID = NON_EXISTENT_UUID
LADDER_UNIT_CODE = "Z-999"


def _out_of_range_unit_payload(installation_id, bedroom_count):
    return {
        "installation_id": installation_id,
        "unit_code": LADDER_UNIT_CODE,
        "bedroom_count": bedroom_count,
        "unit_type": "TOWNHOME",
        "designated_rank_category": "JUNIOR_ENLISTED",
    }


def test_the_ladder_reports_the_highest_broken_rung_not_the_worst_problem(api):
    """One body breaking three rungs answers 401, then 403, then 400, then 404.

    PRD: "The ladder is walked in ascending priority order and **the first violated rung determines the response**; the remaining rungs are not evaluated."

    Design: Corner/validations/the_ladder_reports_the_highest_broken_rung_not_the_worst_problem
    """
    fx.set_clock(api, STARTUP_CLOCK)
    installation = fx.create_installation(api)
    broken = _out_of_range_unit_payload(
        UNKNOWN_INSTALLATION_ID, OUT_OF_RANGE_BEDROOM_COUNT
    )

    # Rung 1 outranks both the shape rung and the existence rung.
    validate_error(
        api.create_housing_unit(broken, ANONYMOUS),
        ApiErrorId.ERR_UNAUTHENTICATED,
        401,
    )
    # Rung 2 answers before the malformed body is ever inspected.
    validate_error(
        api.create_housing_unit(broken, TECH),
        ApiErrorId.ERR_UNAUTHORIZED_ROLE,
        403,
    )
    # Rung 4: nine bedrooms violates the declared range, and it is reported
    # before the missing installation the same body names.
    validate_error(
        api.create_housing_unit(broken, ADMIN),
        ApiErrorId.ERR_INVALID_REQUEST,
        400,
    )
    # Only once the shape is legal does the ladder reach the body reference.
    validate_error(
        api.create_housing_unit(
            _out_of_range_unit_payload(UNKNOWN_INSTALLATION_ID, LEGAL_BEDROOM_COUNT),
            ADMIN,
        ),
        ApiErrorId.ERR_INSTALLATION_NOT_FOUND,
        404,
    )

    created = validate_success(
        api.create_housing_unit(
            _out_of_range_unit_payload(installation["id"], LEGAL_BEDROOM_COUNT), ADMIN
        ),
        201,
    )
    assert created["status"] == "AVAILABLE"
    asserts.assert_housing_unit(created)
    assert created["unit_code"] == LADDER_UNIT_CODE
    assert created["bedroom_count"] == LEGAL_BEDROOM_COUNT


OTHER_SPONSOR = {"dodid": "1000000002", "last_name": "Okafor", "first_name": "Dele"}
DISHWASHER_DESCRIPTION = "Dishwasher will not drain"


def test_a_sponsor_may_not_reach_another_familys_lease(api):
    """The ownership rung guards the write that carries a lease as well as the read.

    PRD: "A resident acting on another sponsor's resource is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    Design: Corner/validations/a_sponsor_may_not_reach_another_familys_lease
    """
    state = fx.setup_occupied_lease(api)
    lease_id = state["lease"]["id"]
    owner_headers = make_service_member_headers(state["sponsor"]["id"])
    stranger = fx.create_service_member(api, **OTHER_SPONSOR)
    stranger_headers = make_service_member_headers(stranger["id"])

    validate_error(
        api.get_lease(lease_id, stranger_headers),
        ApiErrorId.ERR_NOT_RESOURCE_OWNER,
        403,
    )
    validate_error(
        api.create_work_order(
            f.create_work_order_payload(
                state["unit"]["id"],
                lease_id=lease_id,
                category="APPLIANCE",
                description=DISHWASHER_DESCRIPTION,
            ),
            stranger_headers,
        ),
        ApiErrorId.ERR_NOT_RESOURCE_OWNER,
        403,
    )

    owned = validate_success(api.get_lease(lease_id, owner_headers))
    assert owned["service_member_id"] == state["sponsor"]["id"]
    assert owned["occupancy_status"] == "OCCUPIED"

    # The rung applies only when the acting role is ServiceMember.
    operator_view = validate_success(api.get_lease(lease_id, MANAGER))
    assert operator_view["service_member_id"] == state["sponsor"]["id"]
    asserts.assert_lease(operator_view)


def test_a_lease_may_only_be_written_against_an_accepted_application(api):
    """The same body is refused at PENDING, refused at OFFERED, then taken.

    PRD: "Rung 22 requires, on lease creation, that the referenced application's `status` be `ACCEPTED`, failing with `ERR_APPLICATION_NOT_ACCEPTED` (409)."

    Design: Corner/validations/a_lease_may_only_be_written_against_an_accepted_application
    """
    base = fx.setup_installation_with_unit(api)
    sponsor, _ = fx.setup_sponsor_family(api)
    application = fx.submit_application(api, base["installation"]["id"], sponsor)
    lease_payload = f.create_lease_payload(application["id"], base["unit"]["id"])
    assert application["status"] == "PENDING"

    # A PENDING application has no tenancy to realise.
    validate_error(
        api.create_lease(lease_payload, MANAGER),
        ApiErrorId.ERR_APPLICATION_NOT_ACCEPTED,
        409,
    )

    fx.run_offer_run(api, base["installation"]["id"])
    assert fx.read_application(api, application["id"])["status"] == "OFFERED"

    # OFFERED is still not ACCEPTED.
    validate_error(
        api.create_lease(lease_payload, MANAGER),
        ApiErrorId.ERR_APPLICATION_NOT_ACCEPTED,
        409,
    )

    fx.accept_offer(api, application["id"], sponsor)
    lease = validate_success(api.create_lease(lease_payload, MANAGER), 201)

    assert lease["occupancy_status"] == "PENDING_MOVE_IN"
    assert lease["gross_rent_cents"] == const.BASE_GROSS_RENT_CENTS
    # Accepting satisfied the rung and writing the lease retired the application.
    assert fx.read_application(api, application["id"])["status"] == "HOUSED"


TWIN_UNITS = ({"unit_code": "A-101"}, {"unit_code": "A-103"})


def test_a_lease_may_only_be_written_against_the_unit_the_offer_reserved(api):
    """An identical spare unit sitting in AVAILABLE is still the wrong unit.

    PRD: "Rung 23 requires, on lease creation, that the referenced unit's `status` be `ASSIGNED` and that it be the very unit the application was offered, failing with `ERR_UNIT_NOT_AVAILABLE` (409)."

    Design: Corner/validations/a_lease_may_only_be_written_against_the_unit_the_offer_reserved
    """
    fx.set_clock(api, BEFORE_ARRIVAL_CLOCK)
    installation = fx.create_installation(api)
    fx.create_bah_rate(api, installation["id"])
    offered_unit, spare_unit = [
        fx.create_housing_unit(api, installation["id"], **spec) for spec in TWIN_UNITS
    ]
    sponsor, _ = fx.setup_sponsor_family(api)
    application = fx.submit_application(api, installation["id"], sponsor)
    fx.run_offer_run(api, installation["id"])
    accepted = fx.accept_offer(api, application["id"], sponsor)
    assert accepted["offered_unit_id"] == offered_unit["id"]

    validate_error(
        api.create_lease(
            f.create_lease_payload(application["id"], spare_unit["id"]), MANAGER
        ),
        ApiErrorId.ERR_UNIT_NOT_AVAILABLE,
        409,
    )

    # The refusal was about the assignment, not about the unit being busy.
    assert fx.read_housing_unit(api, spare_unit["id"])["status"] == "AVAILABLE"

    lease = validate_success(
        api.create_lease(
            f.create_lease_payload(application["id"], offered_unit["id"]), MANAGER
        ),
        201,
    )
    assert lease["housing_unit_id"] == offered_unit["id"]
    asserts.assert_lease(lease)


BILL_OF_RIGHTS_VERSION = "2026.1"


def test_move_in_is_refused_until_the_tenant_acknowledges_the_walkthrough(api):
    """Scheduling the walkthrough is not signing it; the gate reads the inspection.

    PRD: "Rung 24 requires, on move-in, that the lease have a move-in inspection whose `status` is `TENANT_ACKNOWLEDGED` or `COMPLETED`, failing with `ERR_INSPECTION_NOT_ACKNOWLEDGED` (409)."

    Design: Corner/validations/move_in_is_refused_until_the_tenant_acknowledges_the_walkthrough
    """
    state = fx.setup_lease_pending_move_in(api)
    lease_id = state["lease"]["id"]
    inspection = fx.schedule_inspection(api, lease_id)
    fx.set_clock(api, MOVE_IN_CLOCK)

    validate_error(
        api.move_in(lease_id, MANAGER),
        ApiErrorId.ERR_INSPECTION_NOT_ACKNOWLEDGED,
        409,
    )
    assert fx.read_inspection(api, inspection["id"])["status"] == "SCHEDULED"

    sponsor = state["sponsor"]
    fx.acknowledge_inspection(
        api,
        inspection["id"],
        sponsor,
        f"{sponsor['first_name']} {sponsor['last_name']}",
        BILL_OF_RIGHTS_VERSION,
    )
    moved_in = validate_success(api.move_in(lease_id, MANAGER))

    assert moved_in["occupancy_status"] == "OCCUPIED"
    assert moved_in["allotment_status"] == "ACTIVE"
    assert moved_in["rent_basis"] == "MOVE_IN_FINAL"
    assert moved_in["bill_of_rights_version_ack"] == BILL_OF_RIGHTS_VERSION
    assert fx.read_housing_unit(api, state["unit"]["id"])["status"] == "OCCUPIED"


EARLY_CHARGE_COMPLAINT = "Charged before we moved in"
NOTICE_DATE = "2026-09-01"
LONG_EFFECTIVE_DATE = "2026-11-01"
RESOLUTION_DUE_AT = "2026-10-01T09:00:00Z"


def test_a_dispute_needs_an_occupied_tenancy_while_a_notice_needs_a_declared_edge(api):
    """One fact, two owners: the referenced lease answers 25, the targeted lease 19.

    PRD: "Rung 25 requires the lease's `occupancy_status` to be `OCCUPIED` or `NOTICE_GIVEN` and guards three operations — termination notice, termination, and dispute opening — failing with `ERR_LEASE_NOT_OCCUPIED` (409)."

    Design: Corner/validations/a_dispute_needs_an_occupied_tenancy_while_a_notice_needs_a_declared_edge
    """
    state = fx.setup_acknowledged_inspection(api)
    lease_id = state["lease"]["id"]
    sponsor = state["sponsor"]
    sponsor_headers = make_service_member_headers(sponsor["id"])
    fx.set_clock(api, MOVE_IN_CLOCK)
    dispute_payload = f.create_dispute_case_payload(
        lease_id, sponsor["id"], description=EARLY_CHARGE_COMPLAINT
    )
    assert fx.read_lease(api, lease_id)["occupancy_status"] == "PENDING_MOVE_IN"

    # The lease is only a referenced resource here, so rung 25 owns the answer.
    validate_error(
        api.create_dispute_case(dispute_payload, sponsor_headers),
        ApiErrorId.ERR_LEASE_NOT_OCCUPIED,
        409,
    )
    # The lease is the primary target here, and rung 19 outranks rung 25.
    validate_error(
        api.give_termination_notice(
            lease_id,
            f.termination_notice_payload(
                "CONVENIENCE", NOTICE_DATE, LONG_EFFECTIVE_DATE
            ),
            MANAGER,
        ),
        ApiErrorId.ERR_INVALID_STATE_TRANSITION,
        409,
    )

    validate_success(api.move_in(lease_id, MANAGER))
    dispute = validate_success(
        api.create_dispute_case(dispute_payload, sponsor_headers), 201
    )

    assert dispute["status"] == "UNDER_REVIEW"
    assert dispute["round_count"] == 0
    asserts.assert_instant_equals(dispute["resolution_due_at"], RESOLUTION_DUE_AT)


PCS_ORDERS = {"pcs_orders_ref": "PCS-2026-1188", "pcs_report_date": "2026-11-01"}
TWENTY_NINE_DAYS_OUT = "2026-09-30"
THIRTEEN_DAYS_OUT = "2026-09-14"
FOURTEEN_DAYS_OUT = "2026-09-15"


def test_the_notice_period_floor_is_thirty_days_but_fourteen_under_orders(api):
    """Both floors probed one day inside: the exemption shortens, it does not remove.

    PRD: "Rung 42 requires `termination_effective_date` to be at least 30 whole days after `termination_notice_date`, except for reasons `PCS` and `DEPLOYMENT`, which permit 14; it guards termination notice, failing with `ERR_NOTICE_PERIOD_TOO_SHORT` (422)."

    Design: Corner/validations/the_notice_period_floor_is_thirty_days_but_fourteen_under_orders
    """
    state = fx.setup_occupied_lease(api)
    lease_id = state["lease"]["id"]
    sponsor_headers = make_service_member_headers(state["sponsor"]["id"])
    orders = validate_success(
        api.record_orders(
            state["sponsor"]["id"], f.record_orders_payload(**PCS_ORDERS), HOUSING_OFFICE
        )
    )
    assert orders["pcs_orders_ref"] == PCS_ORDERS["pcs_orders_ref"]

    # 2026-09-01 to 2026-09-30 is 29 whole days, one short of the general floor.
    validate_error(
        api.give_termination_notice(
            lease_id,
            f.termination_notice_payload(
                "CONVENIENCE", NOTICE_DATE, TWENTY_NINE_DAYS_OUT
            ),
            sponsor_headers,
        ),
        ApiErrorId.ERR_NOTICE_PERIOD_TOO_SHORT,
        422,
    )
    # Thirteen whole days is one short of the shortened floor.
    validate_error(
        api.give_termination_notice(
            lease_id,
            f.termination_notice_payload("PCS", NOTICE_DATE, THIRTEEN_DAYS_OUT),
            sponsor_headers,
        ),
        ApiErrorId.ERR_NOTICE_PERIOD_TOO_SHORT,
        422,
    )

    noticed = validate_success(
        api.give_termination_notice(
            lease_id,
            f.termination_notice_payload("PCS", NOTICE_DATE, FOURTEEN_DAYS_OUT),
            sponsor_headers,
        )
    )

    assert noticed["occupancy_status"] == "NOTICE_GIVEN"
    assert noticed["termination_reason"] == "PCS"
    assert noticed["termination_notice_date"] == NOTICE_DATE
    assert noticed["termination_effective_date"] == FOURTEEN_DAYS_OUT


DEPLOYMENT_REFERENCE = {
    "deployment_orders_ref": "DEP-2026-4471",
    "expected_return_date": "2027-06-01",
}
DEPLOYED_STATUS = {"deployment_status": "DEPLOYED"}


def test_a_deployment_notice_needs_both_the_orders_reference_and_the_deployed_status(
    api,
):
    """The reference alone does not satisfy a conjunction of two conditions.

    PRD: "Rung 34 requires that a `termination_reason` of `PCS` be backed by `pcs_orders_ref` on the sponsor's record, and that a `termination_reason` of `DEPLOYMENT` be backed by `deployment_orders_ref` together with a `deployment_status` of `DEPLOYED`; it guards termination notice, failing with `ERR_ORDERS_NOT_ON_FILE` (422)."

    Design: Corner/validations/a_deployment_notice_needs_both_the_orders_reference_and_the_deployed_status
    """
    state = fx.setup_occupied_lease(api)
    lease_id = state["lease"]["id"]
    sponsor_id = state["sponsor"]["id"]

    def _notice(reason):
        return api.give_termination_notice(
            lease_id,
            f.termination_notice_payload(reason, NOTICE_DATE, LONG_EFFECTIVE_DATE),
            MANAGER,
        )

    # Every notice below spans two months, well past both notice-period floors.
    validate_error(_notice("PCS"), ApiErrorId.ERR_ORDERS_NOT_ON_FILE, 422)
    validate_error(_notice("DEPLOYMENT"), ApiErrorId.ERR_ORDERS_NOT_ON_FILE, 422)

    referenced = validate_success(
        api.record_orders(
            sponsor_id, f.record_orders_payload(**DEPLOYMENT_REFERENCE), HOUSING_OFFICE
        )
    )
    # Recording the reference does not change the status.
    assert referenced["deployment_orders_ref"] == (
        DEPLOYMENT_REFERENCE["deployment_orders_ref"]
    )
    assert referenced["deployment_status"] == "NOT_DEPLOYED"

    validate_error(_notice("DEPLOYMENT"), ApiErrorId.ERR_ORDERS_NOT_ON_FILE, 422)

    deployed = validate_success(
        api.record_orders(
            sponsor_id, f.record_orders_payload(**DEPLOYED_STATUS), HOUSING_OFFICE
        )
    )
    assert deployed["deployment_status"] == "DEPLOYED"

    noticed = validate_success(_notice("DEPLOYMENT"))
    assert noticed["occupancy_status"] == "NOTICE_GIVEN"
    assert noticed["termination_reason"] == "DEPLOYMENT"
