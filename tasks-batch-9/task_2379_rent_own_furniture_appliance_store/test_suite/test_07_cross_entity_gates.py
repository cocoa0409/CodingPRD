"""Operations whose legality is decided by the state of a different row.

Signing is gated by the customer's verification state, and swap issuance is gated by
the state of a unit that a completely different agreement is holding.
"""

from __future__ import annotations

from test_helpers import (
    W52_RENEWAL_RATE_CENTS,
    W52_TOTAL_OF_PAYMENTS_CENTS,
    ErrorId,
    IssueCode,
    PaymentStatus,
    PossessionStatus,
    TicketStatus,
    UnitStatus,
    VerificationStatus,
    assert_fields,
    build_tx_floor,
    deliver_on,
    factories,
    failure,
    sign_on,
)
from test_helpers.test_users import OFFICER_USER_ID, SALES, TECHNICIAN

TICKET_START = "2026-08-03T09:00:00Z"
TICKET_END = "2026-08-03T11:00:00Z"
LATE_AFTERNOON_START = "2026-08-01T14:00:00Z"
LATE_AFTERNOON_END = "2026-08-01T16:00:00Z"


def _renter_with_references_but_no_decision(world):
    """Both references telephoned and verified, but no officer has decided yet."""
    scenario = build_tx_floor(world, verify_customer=False)
    return scenario


def test_signing_is_refused_while_the_renter_is_still_pending(world):
    """A verified reference count is not a decision; only the officer's approval is.

    PRD: A `SalesAssociate` or `StoreManager` creates one against a `customer_id` whose `verification_status` must be `VERIFIED` (`ERR_CUSTOMER_NOT_VERIFIED` otherwise) and a `unit_id` whose unit must be `AVAILABLE` (`ERR_UNIT_NOT_AVAILABLE` otherwise), choosing a `term_type` of `WEEKLY` or `MONTHLY`, a `renewal_count` of at least 1 that is the number of renewal payments to ownership, and a `disclosure_acknowledged` boolean defaulting to false.

    Design: Difficulty/cross_entity_state_dependency/agreement_creation_gated_by_customer_verification_state
    """
    scenario = _renter_with_references_but_no_decision(world)
    assert_fields(
        scenario.read_customer(),
        verification_status=VerificationStatus.PENDING,
        verified_reference_count=2,
        verification_score=0,
        verified_by_user_id="",
    )

    response = scenario.api.create_agreement(
        factories.agreement_payload(scenario.customer_id, scenario.unit_id), SALES
    )
    failure(response, ErrorId.CUSTOMER_NOT_VERIFIED)

    assert world.agreements(customer_id=scenario.customer_id) == [], (
        "a refused signing must not leave an agreement behind"
    )
    assert scenario.read_unit()["status"] == UnitStatus.AVAILABLE, (
        "a refused signing must not reserve the goods"
    )


def test_the_officers_approval_unblocks_the_identical_signing(world):
    """The same request succeeds once the gating row has moved to VERIFIED.

    PRD: When it succeeds, `verification_status` moves `PENDING` → `VERIFIED` and `verified_by_user_id` is set to the officer's `X-User-ID`.

    Design: Difficulty/cross_entity_state_dependency/agreement_creation_gated_by_customer_verification_state
    """
    scenario = _renter_with_references_but_no_decision(world)
    failure(
        scenario.api.create_agreement(
            factories.agreement_payload(scenario.customer_id, scenario.unit_id), SALES
        ),
        ErrorId.CUSTOMER_NOT_VERIFIED,
    )

    verified = world.verify_customer(scenario.customer_id)
    assert_fields(
        verified,
        verification_status=VerificationStatus.VERIFIED,
        verification_score=95,
        verified_by_user_id=OFFICER_USER_ID,
    )

    agreement = world.sign(scenario.customer_id, scenario.unit_id)
    assert_fields(
        agreement,
        customer_id=scenario.customer_id,
        unit_id=scenario.unit_id,
        renewal_rate_cents=W52_RENEWAL_RATE_CENTS,
        total_of_payments_cents=W52_TOTAL_OF_PAYMENTS_CENTS,
        payment_status=PaymentStatus.CURRENT,
        possession_status=PossessionStatus.PENDING_DELIVERY,
    )
    assert scenario.read_unit()["status"] == UnitStatus.RESERVED


def _two_rented_sofas_and_one_spare(world):
    """Two agreements each holding a sofa, one spare on the floor, one open ticket."""
    scenario = build_tx_floor(
        world,
        service_bay_capacity=2,
        serials=("SN-TX-0001", "SN-TX-0002", "SN-TX-0003"),
    )
    deliver_on(sign_on(scenario, unit_index=0))

    second = world.sign(scenario.customer_id, scenario.units[1]["id"])
    world.deliver(
        second["id"], scenario.crew_id, LATE_AFTERNOON_START, LATE_AFTERNOON_END
    )

    ticket = world.open_ticket(
        scenario.agreement_id, IssueCode.MECHANICAL, TICKET_START, TICKET_END
    )
    return scenario, second, ticket


def test_a_swap_onto_a_unit_another_agreement_holds_is_refused(world):
    """Replacement eligibility is owned by one check, which reads the other unit's state.

    PRD: The replacement must be `AVAILABLE`, must sit at the ticket's store and must share the serviced unit's `category`, or the request is refused with `ERR_REPLACEMENT_UNIT_INVALID`; that single check owns replacement eligibility entirely, so a swap onto a unit that is already out on rent yields this error rather than a unit-status error.

    Design: Difficulty/cross_entity_state_dependency/swap_eligibility_gated_by_replacement_unit_state_on_another_agreement
    """
    scenario, second, ticket = _two_rented_sofas_and_one_spare(world)

    response = scenario.api.issue_swap(
        ticket["id"],
        factories.issue_swap_payload(scenario.units[1]["id"]),
        TECHNICIAN,
    )
    failure(response, ErrorId.REPLACEMENT_UNIT_INVALID)

    assert_fields(
        world.get_ticket(ticket["id"]),
        status=TicketStatus.SCHEDULED,
        replacement_unit_id=None,
    )
    assert_fields(
        scenario.read_agreement(),
        possession_status=PossessionStatus.DELIVERED,
        unit_id=scenario.units[0]["id"],
        swap_count=0,
    )
    assert_fields(
        world.get_agreement(second["id"]), unit_id=scenario.units[1]["id"]
    )
    assert scenario.read_unit(1)["status"] == UnitStatus.ON_RENT
    assert_fields(
        scenario.read_store(), units_in_service_count=0, service_intake_open=True
    )


def test_the_swap_succeeds_onto_the_unit_that_is_actually_available(world):
    """Pointed at the spare, the identical call runs the whole four-step cascade.

    PRD: The replacement unit moves `AVAILABLE` → `ON_RENT` with its `replaced_unit_id` set to the serviced unit's identifier — the self-referential link that makes a loaner traceable back to what it stood in for — and the agreement's `unit_id` is re-pointed at the replacement, carrying `accumulated_rent_received_cents` forward onto it.

    Design: Difficulty/cross_entity_state_dependency/swap_eligibility_gated_by_replacement_unit_state_on_another_agreement
    """
    scenario, _second, ticket = _two_rented_sofas_and_one_spare(world)
    failure(
        scenario.api.issue_swap(
            ticket["id"],
            factories.issue_swap_payload(scenario.units[1]["id"]),
            TECHNICIAN,
        ),
        ErrorId.REPLACEMENT_UNIT_INVALID,
    )

    swapped = world.issue_swap(ticket["id"], scenario.units[2]["id"])
    assert_fields(
        swapped,
        status=TicketStatus.SWAP_ISSUED,
        replacement_unit_id=scenario.units[2]["id"],
    )

    assert_fields(
        scenario.read_agreement(),
        possession_status=PossessionStatus.SERVICE_SWAP_PENDING,
        unit_id=scenario.units[2]["id"],
        swap_count=1,
    )
    assert scenario.read_unit(0)["status"] == UnitStatus.IN_SERVICE
    assert_fields(
        scenario.read_unit(2),
        status=UnitStatus.ON_RENT,
        replaced_unit_id=scenario.units[0]["id"],
    )
    assert_fields(
        scenario.read_store(),
        units_in_service_count=1,
        units_on_rent_count=2,
        service_intake_open=True,
    )
