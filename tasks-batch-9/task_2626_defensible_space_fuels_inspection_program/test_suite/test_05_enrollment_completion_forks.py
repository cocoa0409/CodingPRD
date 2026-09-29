"""Closing out an enrollment: the three-way fork on program type and attendance."""

from prd_bench_local_runner.testing import validate_error

from test_helpers import (
    ERR_INVALID_STATE,
    PROGRAM_TYPE_CHIPPER,
    PROGRAM_TYPE_GRANT,
    assert_award,
    assert_cents,
    assert_program_capacity,
    assert_version,
    complete_enrollment,
    create_parcel,
    create_program,
    enroll,
    get_enrollment,
    get_program,
    open_cycle,
)
from test_helpers.factories import complete_enrollment_payload
from test_helpers.test_users import PROGRAM_ADMIN_HEADERS

WINDOW = {
    "service_window_start_utc": "2026-08-01T00:00:00Z",
    "service_window_end_utc": "2026-12-01T00:00:00Z",
}


def _two_program_world(client):
    """One cycle carrying a chipper day and a cost-share grant, three enrollments.

    The chipper programme funds nothing (budget 0) while the grant programme
    carries 500000 cents across three slots.  Parcel B claims a 191667-cent
    invoice and holds a hardship determination; parcel C claims 100000 cents
    and does not.  Both parcels are HIGH risk at intake, so both are matched at
    0.60.
    """
    cycle = open_cycle(client)
    chipper = create_program(
        client,
        cycle["id"],
        PROGRAM_TYPE_CHIPPER,
        budget_total_cents=0,
        capacity_slots=3,
        **WINDOW
    )
    grant = create_program(
        client,
        cycle["id"],
        PROGRAM_TYPE_GRANT,
        budget_total_cents=500000,
        capacity_slots=3,
        **WINDOW
    )
    parcel_a = create_parcel(client)
    parcel_b = create_parcel(client, owner_hardship_flag=True)
    parcel_c = create_parcel(client, owner_hardship_flag=False)

    enrollment_a = enroll(client, chipper["id"], parcel_a["id"], chipper["version"])
    enrollment_b = enroll(
        client,
        grant["id"],
        parcel_b["id"],
        grant["version"],
        vendor_invoice_cents=191667,
    )
    grant_v2 = get_program(client, grant["id"])["version"]
    enrollment_c = enroll(
        client,
        grant["id"],
        parcel_c["id"],
        grant_v2,
        vendor_invoice_cents=100000,
    )
    return {
        "chipper": chipper,
        "grant": grant,
        "a": enrollment_a,
        "b": enrollment_b,
        "c": enrollment_c,
    }


class TestCompletionForksOnProgramType:
    """One attended flag, three destinations, and only one of them pays out."""

    def test_attended_true_forks_to_completed_or_reimbursed_by_program_type(
        self, client
    ):
        """The same true flag lands on COMPLETED for a chipper day and on
        REIMBURSED for a grant, and neither moves the budget.

        PRD: "attended true on a CHIPPER_DAY or CURBSIDE_COLLECTION program
        moves the enrollment APPROVED -> COMPLETED. Nothing financial happens:
        reserved_amount_cents and the program's budget_remaining_cents are both
        left exactly as they were, and only the enrollment's version advances by
        1."

        PRD: "attended true on a COST_SHARE_GRANT program moves the enrollment
        APPROVED -> REIMBURSED. reimbursed_cents is set to award_cents, and
        reserved_amount_cents deliberately stays at award_cents so that
        budget_remaining_cents does not move - the money was always going to be spent,
        and reimbursement merely disburses what was reserved."

        PRD: "For a program that is not a cost-share grant,
        award_before_bonus_cents, bonus_pct and award_cents are all null and no
        money is ever reserved."

        PRD: "COMPLETED, NO_SHOW, REIMBURSED and CANCELLED are all terminal."

        Design: Difficulty/non_linear_state_machine/enrollment_completion_forks_on_program_type
        """
        world = _two_program_world(client)
        chipper_version = get_program(client, world["chipper"]["id"])["version"]
        grant_before = get_program(client, world["grant"]["id"])

        # The chipper enrolment was never sized and never reserved anything.
        assert world["a"]["award_before_bonus_cents"] is None
        assert world["a"]["bonus_pct"] is None
        assert world["a"]["award_cents"] is None

        completed = complete_enrollment(client, world["a"]["id"], attended=True)
        assert completed["status"] == "COMPLETED"
        assert completed["status"] != "REIMBURSED"
        assert_version(completed, world["a"]["version"] + 1)
        assert_program_capacity(
            get_program(client, world["chipper"]["id"]), 0, reserved_slots=1
        )
        assert (
            get_program(client, world["chipper"]["id"])["version"] == chipper_version
        ), "a chipper close-out must not touch the programme row"

        # 191667 capped at 250000, matched at 0.60 -> 115000, bonus tier 0.10.
        assert_award(world["b"], 115000, 0.10, 11500, 126500, reserved=126500)

        reimbursed = complete_enrollment(client, world["b"]["id"], attended=True)
        assert reimbursed["status"] == "REIMBURSED"
        assert reimbursed["status"] != "COMPLETED"
        assert_cents(reimbursed["reimbursed_cents"], 126500)
        assert_cents(reimbursed["reserved_amount_cents"], 126500)
        assert_version(reimbursed, world["b"]["version"] + 1)

        grant_after = get_program(client, world["grant"]["id"])
        assert_program_capacity(
            grant_after,
            grant_before["budget_remaining_cents"],
            reserved_slots=grant_before["reserved_slots"],
        )
        assert_program_capacity(grant_after, 313500, reserved_slots=2)
        assert grant_after["version"] == grant_before["version"], (
            "disbursing money that was already reserved must not move the "
            "programme version"
        )

        validate_error(
            client.complete_enrollment(
                world["b"]["id"],
                complete_enrollment_payload(attended=True),
                headers=PROGRAM_ADMIN_HEADERS,
            ),
            ERR_INVALID_STATE,
        )

    def test_attended_false_lands_on_no_show_and_returns_budget_and_slot(self, client):
        """A no-show is the only branch that gives money and capacity back, and
        the conservation identity survives all three closures.

        PRD: "attended false moves the enrollment APPROVED -> NO_SHOW regardless
        of program type. reserved_amount_cents is zeroed, the program's
        budget_remaining_cents is credited back by the amount that had been
        reserved, and reserved_slots is decremented by 1 so the slot returns to
        the pool. Both the enrollment's and the program's version advance by 1."

        PRD: "hardship_bonus_cents is award_before_bonus_cents multiplied by
        bonus_pct, rounded half up to a whole cent, but only when the parcel's
        owner_hardship_flag is true; where the flag is false the bonus is exactly
        0."

        PRD: "A support program's budget_remaining_cents must always equal
        budget_total_cents minus the sum of reserved_amount_cents over that
        program's enrollments whose status is APPROVED, COMPLETED or REIMBURSED -
        enrollments in WAITLISTED, NO_SHOW or CANCELLED contribute nothing. A
        program's reserved_slots counts enrollments in APPROVED, COMPLETED or
        REIMBURSED."

        Design: Difficulty/non_linear_state_machine/enrollment_completion_forks_on_program_type
        """
        world = _two_program_world(client)

        # 100000 matched at 0.60 -> 60000, tier 0.10, but no hardship flag.
        assert_award(world["c"], 60000, 0.10, 0, 60000, reserved=60000)

        complete_enrollment(client, world["a"]["id"], attended=True)
        complete_enrollment(client, world["b"]["id"], attended=True)

        grant_before = get_program(client, world["grant"]["id"])
        no_show = complete_enrollment(client, world["c"]["id"], attended=False)

        assert no_show["status"] == "NO_SHOW"
        assert_cents(no_show["reserved_amount_cents"], 0)
        assert_version(no_show, world["c"]["version"] + 1)

        grant_after = get_program(client, world["grant"]["id"])
        assert_program_capacity(grant_after, 373500, reserved_slots=1)
        assert_cents(
            grant_after["budget_remaining_cents"],
            grant_before["budget_remaining_cents"] + 60000,
        )
        assert grant_after["version"] == grant_before["version"] + 1

        # The identity: 500000 less the reserved amount of the one grant
        # enrolment still standing in REIMBURSED.
        reserved_live = sum(
            get_enrollment(client, world[key]["id"])["reserved_amount_cents"]
            for key in ("b", "c")
            if get_enrollment(client, world[key]["id"])["status"]
            in ("APPROVED", "COMPLETED", "REIMBURSED")
        )
        assert_cents(reserved_live, 126500)
        assert_cents(grant_after["budget_remaining_cents"], 500000 - reserved_live)
