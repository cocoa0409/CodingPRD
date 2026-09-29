"""Role authorisation: exclusive operations, shared reads and paired-step separation.

These cases pin who may call what, and distinguish a role that is absent from an
endpoint (403 at the door) from a role that is present but disqualified by the artifact
it is acting on (a domain refusal further down the ladder).
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_success,
)

from test_helpers import ApiClient, ApiErrorId, assertions, factories, fixtures
from test_helpers import test_users as users


def test_neither_of_the_two_writing_roles_can_stand_in_for_the_other(
    api: ApiClient,
) -> None:
    """The supervisor cannot register the facility and the administrator cannot open the
    menu cycle; each identical body succeeds once its owning role sends it.

    The PRD assigns `POST /cfs/facilities` to `ContractAdministrator` alone —
    "Registers a kitchen facility under a contract with its satellite count, chiller
    capacity and authorized sharps inventory" — and `POST /cfs/menu-cycles` to
    `FoodServiceSupervisor` alone: "A **menu cycle** is a repeating rotation of components
    that a facility cooks to, and a `FoodServiceSupervisor` builds it."

    Design: Corner/rbac/corner_exclusive_operations_are_not_interchangeable
    """
    fixtures.set_clock(api)
    contract = fixtures.create_contract(api, contract_code="CFS-2515-R01")
    facility_payload = factories.facility_payload(
        contract["id"], facility_code="FAC-R01", sharps_authorized_count=12
    )

    validate_error(
        api.create_facility(facility_payload, users.FOOD_SUPERVISOR),
        ApiErrorId.ERR_UNAUTHORIZED.value,
        403,
    )
    facility = validate_success(
        api.create_facility(facility_payload, users.CONTRACT_ADMIN), 201
    )
    assert facility["facility_code"] == "FAC-R01"

    cycle_payload = factories.menu_cycle_payload(
        facility["id"], cycle_code="CYC-R01", cycle_length_days=1
    )
    validate_error(
        api.create_menu_cycle(cycle_payload, users.CONTRACT_ADMIN),
        ApiErrorId.ERR_UNAUTHORIZED.value,
        403,
    )
    cycle = validate_success(
        api.create_menu_cycle(cycle_payload, users.FOOD_SUPERVISOR), 201
    )
    assert cycle["status"] == "DRAFT"
    assert cycle["facility_id"] == facility["id"]


def test_the_grievance_coordinator_may_cite_clinical_records_but_not_write_them(
    api: ApiClient,
) -> None:
    """The coordinator is refused the diet order and the intake, files its own grievance
    without trouble, and still reads the inmate it must cite.

    The PRD assigns `POST /cfs/diet-orders` to `RegisteredDietitian` and `POST
    /cfs/inmates` to `CorrectionalOfficer`, while `POST /cfs/grievances` is the
    `GrievanceCoordinator`'s: "Files a food service grievance and computes its response
    deadline from the category's SLA window." `GET /cfs/inmates/{id}` names the coordinator
    among its authorized roles.

    Design: Corner/rbac/corner_grievance_coordinator_cannot_author_clinical_records
    """
    fixtures.set_clock(api)
    contract = fixtures.create_contract(api, contract_code="CFS-2515-R02")
    facility = fixtures.create_facility(
        api, contract["id"], facility_code="FAC-R02", sharps_authorized_count=12
    )
    inmate = fixtures.create_inmate(api, facility["id"], booking_number="BK-R02")
    assert inmate["version"] == 1

    validate_error(
        api.create_diet_order(
            factories.religious_diet_order_payload(inmate["id"], inmate["version"]),
            users.GRIEVANCE_COORD,
        ),
        ApiErrorId.ERR_UNAUTHORIZED.value,
        403,
    )
    validate_error(
        api.create_inmate(
            factories.inmate_payload(facility["id"], booking_number="BK-R02-B"),
            users.GRIEVANCE_COORD,
        ),
        ApiErrorId.ERR_UNAUTHORIZED.value,
        403,
    )

    grievance = validate_success(
        api.create_grievance(
            factories.grievance_payload(
                inmate["id"],
                facility["id"],
                category="RELIGIOUS_DIET_DENIAL",
                narrative="Kosher tray not provided at lunch.",
            ),
            users.GRIEVANCE_COORD,
        ),
        201,
    )
    assert grievance["status"] == "FILED"

    readable = validate_success(api.get_inmate(inmate["id"], users.GRIEVANCE_COORD))
    assert readable["booking_number"] == "BK-R02"
    assert readable["version"] == 1
    assert readable["active_diet_order_count"] == 0


def test_the_dietitian_who_signed_may_not_activate_even_wearing_the_other_hat(
    api: ApiClient,
) -> None:
    """One operator holding both roles passes each RBAC check yet is refused the
    activation, which a different administrator then completes.

    The PRD states: "A menu cycle's `nutrition_signed_by_user_id` may not equal the
    `X-User-ID` that activates it", and at activation: "The acting `X-User-ID` must differ
    from `nutrition_signed_by_user_id`, per §2.8, otherwise `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/rbac/corner_same_user_cannot_sign_and_activate_a_menu_cycle
    """
    ctx = fixtures.active_contract_with_facility(
        api,
        contract_overrides={"contract_code": "CFS-2515-R03"},
        facility_overrides={
            "facility_code": "FAC-R03",
            "sharps_authorized_count": 12,
        },
    )
    cycle = validate_success(
        api.create_menu_cycle(
            factories.menu_cycle_payload(
                ctx["facility"]["id"], cycle_code="CYC-R03", cycle_length_days=1
            ),
            users.FOOD_SUPERVISOR,
        ),
        201,
    )
    for build_item in factories.STANDARD_DAY_ITEMS:
        validate_success(
            api.add_menu_cycle_item(cycle["id"], build_item(), users.FOOD_SUPERVISOR), 201
        )

    signed = validate_success(
        api.nutrition_sign_menu_cycle(cycle["id"], users.DUAL_HAT_DIETITIAN)
    )
    assert signed["status"] == "NUTRITION_APPROVED"
    assert signed["nutrition_signed_by_user_id"] == users.user_id_of(
        users.DUAL_HAT_DIETITIAN
    )

    # The same operator, now wearing the administrator hat: RBAC lets it through, §2.8
    # does not.
    validate_error(
        api.activate_menu_cycle(cycle["id"], users.DUAL_HAT_CONTRACT_ADMIN),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
        409,
    )
    refused = validate_success(api.get_menu_cycle(cycle["id"], users.FOOD_SUPERVISOR))
    assert refused["status"] == "NUTRITION_APPROVED"
    assert refused["activated_by_user_id"] is None
    assertions.assert_no_version_change(signed, refused)

    activated = validate_success(
        api.activate_menu_cycle(cycle["id"], users.CONTRACT_ADMIN)
    )
    assert activated["status"] == "ACTIVE"
    assert activated["activated_by_user_id"] == users.user_id_of(users.CONTRACT_ADMIN)
    assertions.assert_version_bumped_by(signed, activated)


def test_the_wrong_verifier_gets_through_the_door_and_is_turned_away_inside(
    api: ApiClient,
) -> None:
    """Both verifier roles are authorised on the endpoint, so the provider's attempt on a
    religious order is refused for the order's family rather than for the role's absence.

    The PRD states: "The verifying role must match the order family: a `RELIGIOUS` order is
    verified by a `ChaplainDesignee` and a `MEDICAL` order by a `MedicalProvider`. Crossing
    those wires — a chaplain attesting a renal diet, or a provider attesting a kosher one —
    is rejected with `ERR_VERIFIER_ROLE_MISMATCH` and HTTP 403." Verification raises the
    census: "`Facility.active_special_diet_count` is incremented by 1."

    Design: Corner/rbac/corner_verifier_role_must_match_the_order_type
    """
    fixtures.set_clock(api)
    contract = fixtures.create_contract(api, contract_code="CFS-2515-R04")
    facility = fixtures.create_facility(
        api, contract["id"], facility_code="FAC-R04", sharps_authorized_count=12
    )
    inmate = fixtures.create_inmate(api, facility["id"], booking_number="BK-R04")
    order = validate_success(
        api.create_diet_order(
            factories.religious_diet_order_payload(inmate["id"], inmate["version"]),
            users.DIETITIAN,
        ),
        201,
    )
    assert order["status"] == "PENDING_VERIFICATION"
    assert order["requested_by_user_id"] == users.user_id_of(users.DIETITIAN)

    validate_error(
        api.verify_diet_order(
            order["id"], users.MEDICAL, {"verification_note": "Reviewed chart."}
        ),
        ApiErrorId.ERR_VERIFIER_ROLE_MISMATCH.value,
        403,
    )
    still_pending = fixtures.read_diet_order(api, order["id"])
    assert still_pending["status"] == "PENDING_VERIFICATION"
    assert still_pending["verified_by_user_id"] is None
    assert fixtures.read_facility(api, facility["id"])["active_special_diet_count"] == 0

    verified = validate_success(
        api.verify_diet_order(
            order["id"], users.CHAPLAIN, {"verification_note": "Faith practice confirmed."}
        )
    )
    assert verified["status"] == "ACTIVE"
    assert verified["verified_by_user_id"] == users.user_id_of(users.CHAPLAIN)
    assert fixtures.read_facility(api, facility["id"])["active_special_diet_count"] == 1


def test_the_diet_order_read_is_shared_by_seven_roles_and_denied_to_the_eighth(
    api: ApiClient,
) -> None:
    """The auditor and the officer read the same order body; the contract administrator is
    refused it and sees only the facility's aggregate census instead.

    The PRD authorises `GET /cfs/diet-orders/{id}` for "RegisteredDietitian,
    MedicalProvider, ChaplainDesignee, FoodServiceSupervisor, CorrectionalOfficer,
    GrievanceCoordinator, ComplianceAuditor" — the `ContractAdministrator` is absent — while
    `GET /cfs/facilities/{id}` "Reads one facility including its sharps counters and derived
    kitchen_posture" for the administrator among others.

    Design: Corner/rbac/corner_diet_order_reads_are_shared_but_not_universal
    """
    fixtures.set_clock(api)
    contract = fixtures.create_contract(api, contract_code="CFS-2515-R05")
    facility = fixtures.create_facility(
        api, contract["id"], facility_code="FAC-R05", sharps_authorized_count=12
    )
    inmate = fixtures.create_inmate(api, facility["id"], booking_number="BK-R05")
    order = validate_success(
        api.create_diet_order(
            factories.religious_diet_order_payload(
                inmate["id"], inmate["version"], diet_code="HALAL"
            ),
            users.DIETITIAN,
        ),
        201,
    )
    validate_success(api.verify_diet_order(order["id"], users.CHAPLAIN))

    shared = (
        users.DIETITIAN,
        users.MEDICAL,
        users.CHAPLAIN,
        users.FOOD_SUPERVISOR,
        users.OFFICER,
        users.GRIEVANCE_COORD,
        users.AUDITOR,
    )
    for headers in shared:
        body = validate_success(api.get_diet_order(order["id"], headers))
        assert body["diet_code"] == "HALAL"
        assert body["status"] == "ACTIVE"
        assert body["id"] == order["id"]

    validate_error(
        api.get_diet_order(order["id"], users.CONTRACT_ADMIN),
        ApiErrorId.ERR_UNAUTHORIZED.value,
        403,
    )
    aggregate = validate_success(api.get_facility(facility["id"], users.CONTRACT_ADMIN))
    assert aggregate["active_special_diet_count"] == 1
