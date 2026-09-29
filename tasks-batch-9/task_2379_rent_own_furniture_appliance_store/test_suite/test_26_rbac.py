"""Who may act, whose rows they may see, and who is disqualified by their own signature.

The authorized-roles column is exhaustive, so a role outside it is refused even
when the request is otherwise perfect. A renter shares the read endpoints with
staff but only ever sees itself. And the officer who approved a file may not be
the hand that takes the goods back.
"""

from __future__ import annotations

from test_helpers import (
    AUSTIN_MAIN,
    CLOCK_EPOCH,
    COLLECTOR,
    DALLAS_NORTH,
    DAY_12,
    DAY_18_1500,
    DUAL_ROLE_USER_ID,
    MANAGER,
    OFFICER,
    SALES,
    TECHNICIAN,
    AccountFlag,
    Channel,
    CollectionsStage,
    Decision,
    ErrorId,
    InspectionStatus,
    Outcome,
    PaymentStatus,
    PossessionStatus,
    ResidualBasis,
    ReturnReason,
    UnitStatus,
    VerificationStatus,
    assert_fields,
    assert_total_count,
    build_tx_floor,
    deliver_on,
    factories,
    failure,
    make_admin_headers,
    make_customer_headers,
    sign_on,
    success,
)

PROVISIONAL_RESIDUAL_CENTS = 96900
EXPECTED_VERIFICATION_SCORE = 95


def test_no_role_can_reach_another_roles_exclusive_operation(world):
    """Seven perfect requests refused purely on the acting role, and nothing written.

    PRD: If the role is well formed but is not among the roles authorized for the operation, the rejection is `ERR_ROLE_FORBIDDEN` (HTTP 403).

    Design: Corner/rbac/each_role_cannot_reach_another_roles_exclusive_write
    """
    world.set_clock(CLOCK_EPOCH)
    world.seed_tx_rule()
    store = world.open_store(AUSTIN_MAIN, "TX", 1)
    customer = world.create_customer(factories.dana_reyes_payload())

    forbidden = (
        world.api.create_customer(factories.mo_klein_payload(), COLLECTOR),
        world.api.verify_customer(
            customer["id"], factories.verify_payload(Decision.APPROVE), SALES
        ),
        world.api.create_store(
            factories.store_payload(DALLAS_NORTH, "TX", 1), MANAGER
        ),
        world.api.create_state_rule(factories.mn_rule_payload(), OFFICER),
        world.api.get_customer(customer["id"], TECHNICIAN),
        world.api.run_day_close(store["id"], SALES),
        world.api.create_inventory_unit(
            store["id"], factories.sofa_payload("SN-TX-0009"), COLLECTOR
        ),
    )
    for response in forbidden:
        failure(response, ErrorId.ROLE_FORBIDDEN)

    # The verification refusal is about the role, not about the thin file: a
    # SalesAssociate never reaches the statutory checks at all.
    assert_total_count(world.api.list_customers(COLLECTOR), 1)
    assert_fields(
        world.get_customer(customer["id"]),
        verification_status=VerificationStatus.PENDING,
        verification_score=0,
    )
    assert_total_count(world.api.list_store_inventory_units(store["id"], MANAGER), 0)


def test_a_renter_shares_the_read_endpoints_but_only_ever_sees_itself(world):
    """The same two reads succeed for the owner, are refused for the neighbour.

    PRD: Ownership enforcement produces `ERR_NOT_RESOURCE_OWNER` (HTTP 403) and covers exactly seven operations: reading a single customer record, reading a single agreement, reading an agreement's total-of-payments disclosure, requesting an early-purchase quote on an agreement, accepting an early-purchase quote, initiating a voluntary return, and opening a service ticket on an agreement.

    Design: Corner/rbac/customer_role_reads_are_shared_but_scoped_to_its_own_rows
    """
    scenario = sign_on(build_tx_floor(world))
    owner = scenario.customer_id
    neighbour = world.create_customer(factories.mo_klein_payload())["id"]

    own_row = success(world.api.get_customer(owner, make_customer_headers(owner)))
    assert_fields(
        own_row,
        id=owner,
        verification_status=VerificationStatus.VERIFIED,
        verification_score=EXPECTED_VERIFICATION_SCORE,
    )
    failure(
        world.api.get_customer(neighbour, make_customer_headers(owner)),
        ErrorId.NOT_RESOURCE_OWNER,
    )

    own_agreement = success(
        world.api.get_agreement(scenario.agreement_id, make_customer_headers(owner))
    )
    assert_fields(
        own_agreement,
        customer_id=owner,
        possession_status=PossessionStatus.PENDING_DELIVERY,
    )
    failure(
        world.api.get_agreement(
            scenario.agreement_id, make_customer_headers(neighbour)
        ),
        ErrorId.NOT_RESOURCE_OWNER,
    )

    for headers in (COLLECTOR, OFFICER):
        assert success(world.api.get_customer(owner, headers)) == own_row, (
            "staff reads of the same customer row must agree with the renter's own read"
        )
        assert (
            success(world.api.get_agreement(scenario.agreement_id, headers))
            == own_agreement
        ), "staff reads of the same agreement must agree with the renter's own read"


def test_the_officer_who_approved_the_file_may_not_take_the_goods_back(world):
    """The acting operator identifier is compared against the approval on record.

    PRD: Whenever a repossession is authorized, the acting `X-User-ID` is compared against the customer's `verified_by_user_id` — the opaque operator identifier recorded when the approval decision set `verification_status` to `VERIFIED` — and an equal value is refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).

    Design: Corner/rbac/repossession_is_barred_for_the_officer_who_approved_the_verification
    """
    scenario = build_tx_floor(world, verify_customer=False)
    approved = world.verify_customer(
        scenario.customer_id, Decision.APPROVE, as_user_id=DUAL_ROLE_USER_ID
    )
    assert_fields(approved, verified_by_user_id=DUAL_ROLE_USER_ID)
    deliver_on(sign_on(scenario))

    world.set_clock(DAY_12)
    world.day_close(scenario.store_id)
    world.set_clock(DAY_18_1500)
    expiry = world.day_close(scenario.store_id)
    assert_fields(
        expiry,
        agreements_scanned=1,
        late_fees_assessed=0,
        windows_expired=1,
        agreements_defaulted=1,
        agreements_marked_adverse=0,
    )
    world.log_contact(scenario.agreement_id, Channel.PHONE, Outcome.LEFT_MESSAGE)

    failure(
        world.api.repossess_agreement(
            scenario.agreement_id,
            factories.repossess_payload(True),
            make_admin_headers(DUAL_ROLE_USER_ID),
        ),
        ErrorId.SEGREGATION_OF_DUTIES,
    )
    assert_fields(
        scenario.read_agreement(),
        possession_status=PossessionStatus.DELIVERED,
        payment_status=PaymentStatus.DEFAULTED,
    )
    assert scenario.read_unit()["status"] == UnitStatus.ON_RENT

    repossessed = world.repossess(scenario.agreement_id)
    assert_fields(
        repossessed,
        possession_status=PossessionStatus.REPOSSESSED,
        payment_status=PaymentStatus.CLOSED,
        collections_stage=CollectionsStage.ADVERSE,
    )
    assert_fields(
        scenario.read_customer(),
        adverse_agreement_count=1,
        account_flag=AccountFlag.ADVERSE,
    )
    assert_fields(
        scenario.read_unit(),
        status=UnitStatus.RETURNED_PENDING_GRADE,
        residual_value_cents=PROVISIONAL_RESIDUAL_CENTS,
        residual_valuation_basis=ResidualBasis.PROVISIONAL,
    )
    assert scenario.read_store()["units_on_rent_count"] == 0

    inspections = assert_total_count(
        world.api.list_return_inspections(
            MANAGER, {"agreement_id": scenario.agreement_id}
        ),
        1,
    )
    assert_fields(
        inspections[0],
        status=InspectionStatus.PENDING,
        return_reason=ReturnReason.REPOSSESSION_RECOVERY,
    )
