"""Two compensating unwinds, and the ledger each one is required to leave behind.

A rescission is a true inverse: the parcel rollup returns to the value it held before
the signature. A clawback is deliberately not an inverse: the gross side is frozen and
the compensation is booked on a second axis, so the homeowner's obligation survives.
"""

from test_helpers import assertions as A
from test_helpers import factories, fixtures
from test_helpers.api_errors import (
    ERR_AGREEMENT_STATE_INVALID,
    ERR_DISBURSEMENT_STATE_INVALID,
    ERR_NO_RECOURSE_BASIS,
)
from test_helpers.test_users import COMPLIANCE_OFFICER

RESCISSION_CLOCK = "2026-08-14T00:00:00Z"
ESCALATION_CLOCK = "2026-10-01T00:00:00Z"


def _signed_deal_with_live_paperwork(client):
    """SIGNED on the pinned day, with a countersigned certificate and no cash out."""
    world = fixtures.seed_program(client, fixtures.SIGNING_CLOCK)
    A.assert_parcel_exposure(fixtures.read_property(client, world), 0, 0)

    fixtures.draft_with_two_measures(client, world)
    fixtures.submitted_application(client, world)
    fixtures.underwritten_application(client, world)
    fixtures.consented_application(client, world)
    fixtures.approved_application(client, world)
    fixtures.issued_agreement(client, world)
    A.assert_fields(world["agreement"], financed_amount_cents=4314500)
    fixtures.signed_agreement(client, world)
    # "Signature also starts the three-business-day right of rescission, and
    # rescission_expires_at is computed at that moment."
    A.assert_fields(
        world["agreement"],
        status="SIGNED",
        financed_amount_cents=4314500,
        rescission_expires_at="2026-08-18T00:00:00Z",
    )
    A.assert_parcel_exposure(fixtures.read_property(client, world), 0, 4314500)

    fixtures.move_clock(client, "2026-08-13T00:00:00Z")
    fixtures.filed_certificate(client, world, certified_cost_cents=4200000)
    fixtures.countersigned_certificate(client, world)
    fixtures.move_clock(client, RESCISSION_CLOCK)
    return world


def test_rescinding_returns_the_parcel_rollup_to_its_pre_signature_value(client):
    """The subtraction matches the addition exactly, with no residue on either term.

    A valid rescission unwinds four things at once: the agreement moves from `SIGNED` to
    the terminal `RESCINDED` with `rescinded_at` stamped; the application moves from
    `FUNDING_PENDING` to `WITHDRAWN`; every measure standing at `APPROVED` falls to
    `INELIGIBLE`; every completion certificate of the application standing at
    `CONTRACTOR_ATTESTED` or `HOMEOWNER_SIGNED` moves to `REJECTED` with
    `rejection_reason` set to `AGREEMENT_RESCINDED`; and `committed_pace_principal_cents`
    is reduced by exactly the `financed_amount_cents` that signing added, returning the
    parcel rollup to its pre-signature value.

    Design: Difficulty/compensating_invariant/rescission_restores_property_committed_pace_principal
    """
    world = _signed_deal_with_live_paperwork(client)

    rescinded = A.expect_ok(
        client.rescind_agreement(
            world["agreement_id"], factories.rescind_payload(), world["owner_headers"]
        )
    )
    A.assert_fields(
        rescinded, status="RESCINDED", rescinded_at="2026-08-14T00:00:00Z"
    )
    # The two rollup terms are tracked separately: only the agreement term ever moved.
    A.assert_parcel_exposure(fixtures.read_property(client, world), 0, 0)

    A.assert_fields(
        fixtures.read_application(client, world),
        status="WITHDRAWN",
        requested_principal_cents=4200000,
    )
    A.assert_fields(
        fixtures.read_measure(client, world["solar_measure_id"]), status="INELIGIBLE"
    )
    A.assert_fields(
        fixtures.read_measure(client, world["hvac_measure_id"]), status="INELIGIBLE"
    )
    A.assert_fields(
        fixtures.read_certificate(client, world),
        status="REJECTED",
        rejection_reason="AGREEMENT_RESCINDED",
    )
    A.assert_contractor_ledger(fixtures.read_contractor(client, world), 0, 0)


def test_a_second_rescission_cannot_drive_the_parcel_exposure_negative(client):
    """The settled agreement refuses the replay, so the subtraction happens once.

    An attempt to rescind once the window has closed is a conflict with the agreement's
    settled state and is reported as `ERR_AGREEMENT_STATE_INVALID` (409).

    Design: Difficulty/compensating_invariant/rescission_restores_property_committed_pace_principal
    """
    world = _signed_deal_with_live_paperwork(client)

    A.expect_ok(
        client.rescind_agreement(
            world["agreement_id"], factories.rescind_payload(), world["owner_headers"]
        )
    )
    A.expect_error(
        client.rescind_agreement(
            world["agreement_id"],
            factories.rescind_payload(reason="duplicate submit"),
            world["owner_headers"],
        ),
        ERR_AGREEMENT_STATE_INVALID,
    )

    A.assert_fields(fixtures.read_agreement(client, world), status="RESCINDED")
    A.assert_parcel_exposure(fixtures.read_property(client, world), 0, 0)


def _escalated_recourse_on_a_funded_project(client):
    """A released draw plus a minor defect that has run past its remedy deadline."""
    world = fixtures.funded_project(client)
    A.assert_fields(world["disbursement"], status="RELEASED", amount_cents=4200000)
    A.assert_contractor_ledger(fixtures.read_contractor(client, world), 4200000, 0)

    fixtures.move_clock(client, fixtures.RECORDING_CLOCK)
    fixtures.upheld_complaint(client, world, "2026-09-30", severity="MINOR")
    # A 300-basis-point deduction leaves the contractor clear of both score gates.
    A.assert_fields(
        fixtures.read_contractor(client, world),
        enrollment_status="ENROLLED",
        workmanship_score=9700,
        lifetime_workmanship_score=9700,
        upheld_open_remedy_count=1,
    )
    return world


def test_a_clawback_needs_an_escalated_complaint_and_not_merely_an_upheld_one(client):
    """The premature attempt leaves both sides of the ledger exactly as they were.

    A clawback requires a workmanship complaint of the same application in status
    `ESCALATED_RECOURSE`, otherwise `ERR_NO_RECOURSE_BASIS` (422).

    Design: Difficulty/compensating_invariant/reversal_conserves_contractor_gross_and_clawback_ledger
    """
    world = _escalated_recourse_on_a_funded_project(client)

    A.expect_error(
        client.reverse_disbursement(
            world["disbursement_id"],
            factories.reverse_payload("Attempted clawback before escalation"),
            COMPLIANCE_OFFICER,
        ),
        ERR_NO_RECOURSE_BASIS,
    )
    A.assert_fields(fixtures.read_disbursement(client, world), status="RELEASED")
    A.assert_contractor_ledger(fixtures.read_contractor(client, world), 4200000, 0)
    A.assert_fields(fixtures.read_complaint(client, world), status="REMEDY_ORDERED")

    fixtures.move_clock(client, ESCALATION_CLOCK)
    escalated = A.expect_ok(
        client.adjudicate_complaint(
            world["complaint_id"],
            factories.adjudicate_payload(
                "RECOURSE", note="Remedy deadline lapsed with no repair"
            ),
            COMPLIANCE_OFFICER,
        )
    )
    A.assert_fields(
        escalated, status="ESCALATED_RECOURSE", closed_at="2026-10-01T00:00:00Z"
    )
    # The obligation stopped being a repair, but the deduction is retained.
    A.assert_fields(
        fixtures.read_contractor(client, world),
        upheld_open_remedy_count=0,
        workmanship_score=9700,
    )


def test_the_clawback_freezes_gross_and_books_the_compensation_on_the_second_axis(client):
    """Gross is monotone, so the reversal reconciles through the clawback term alone.

    The draw moves to the terminal `REVERSED` with `reversed_at` stamped,
    `clawed_back_total_cents` grows by `amount_cents`, `net_disbursed_cents` is
    recomputed, and `gross_disbursed_cents` is deliberately *not* rewound.

    Design: Difficulty/compensating_invariant/reversal_conserves_contractor_gross_and_clawback_ledger
    """
    world = _escalated_recourse_on_a_funded_project(client)
    fixtures.move_clock(client, ESCALATION_CLOCK)
    A.expect_ok(
        client.adjudicate_complaint(
            world["complaint_id"],
            factories.adjudicate_payload("RECOURSE"),
            COMPLIANCE_OFFICER,
        )
    )

    reversed_draw = A.expect_ok(
        client.reverse_disbursement(
            world["disbursement_id"], factories.reverse_payload(), COMPLIANCE_OFFICER
        )
    )
    A.assert_fields(
        reversed_draw,
        status="REVERSED",
        reversed_at="2026-10-01T00:00:00Z",
        reversal_reason="Unremedied severe defect escalated to contractor recourse",
    )
    A.assert_contractor_ledger(
        fixtures.read_contractor(client, world), 4200000, 4200000
    )

    # The homeowner side is explicitly not compensated by a contractor clawback.
    A.assert_fields(fixtures.read_application(client, world), status="FUNDED")
    A.assert_fields(fixtures.read_agreement(client, world), status="EFFECTIVE")
    A.assert_fields(fixtures.read_certificate(client, world), status="VERIFIED")
    A.assert_fields(
        fixtures.read_measure(client, world["solar_measure_id"]), status="COMPLETED"
    )
    A.assert_fields(
        fixtures.read_measure(client, world["hvac_measure_id"]), status="COMPLETED"
    )
    A.assert_parcel_exposure(fixtures.read_property(client, world), 0, 4314500)

    A.expect_error(
        client.reverse_disbursement(
            world["disbursement_id"],
            factories.reverse_payload("duplicate clawback"),
            COMPLIANCE_OFFICER,
        ),
        ERR_DISBURSEMENT_STATE_INVALID,
    )
    A.assert_contractor_ledger(
        fixtures.read_contractor(client, world), 4200000, 4200000
    )
