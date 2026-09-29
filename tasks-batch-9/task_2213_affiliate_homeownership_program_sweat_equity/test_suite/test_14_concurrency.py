"""The four optimistic-concurrency guards, each spent by a write on another aggregate."""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import api_errors as E
from test_helpers import assertions as A
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.test_users import ADMIN, APPROVER, COORDINATOR, CREW_LEAD, OFFICER


def test_origination_is_refused_on_a_household_version_a_credit_already_spent(api):
    """The officer's read goes stale because the coordinator posted hours, not because anybody touched the file.

    "Originating a mortgage application requires `expected_household_version`
    matching the household's current `version`, because a create legitimately
    supersedes a prior draft for the same household; a mismatch means the scores,
    verified income, or readiness the officer underwrote against have since moved,
    and the create is rejected with `ERR_STALE_HOUSEHOLD_VERSION` (HTTP 412)."

    And the refusal itself costs nothing: "`version` is an integer that starts at 1
    when the row is created and increases by exactly 1 on every accepted mutation of
    that row, including mutations that arrive as cascades from another entity's
    transition."

    Design: Corner/cross_cutting_complexity_layers/occ_mortgage_create_rejects_a_household_version_spent_by_a_credit
    """
    program = X.setup_program(api)
    site = X.setup_ready_site(api, program["id"])
    built = X.setup_selected_household(api, program["id"])
    household, member = built["household"], built["members"][0]
    entry = X.claim_hours(api, household["id"], member["id"], hours_claimed=6.0)
    X.verify_hours(api, entry["id"])

    stale_version = X.household_version(api, household["id"], headers=OFFICER)
    X.credit_hours(api, entry["id"])

    validate_error(
        api.create_application(
            F.application_payload(household["id"], site["id"], stale_version), headers=OFFICER
        ),
        E.ERR_STALE_HOUSEHOLD_VERSION,
        412,
    )

    fresh_version = X.household_version(api, household["id"], headers=OFFICER)
    A.assert_version_bumped_by(stale_version, fresh_version, 1)

    application = validate_success(
        api.create_application(
            F.application_payload(household["id"], site["id"], fresh_version), headers=OFFICER
        ),
        201,
    )
    assert application["status"] == C.APP_DRAFT
    assert application["income_basis_annual_cents"] == 3_000_000
    assert application["appraised_value_cents"] == 15_000_000

    reread = validate_success(api.get_household(household["id"], headers=COORDINATOR))
    A.assert_hours_equal(reread["sweat_equity_credited_hours"], 6.0)
    A.assert_hours_equal(reread["sweat_equity_required_hours"], 12.0)
    assert reread["sweat_equity_satisfied"] is False


def test_the_second_seat_is_refused_on_the_shift_version_the_first_seat_spent(api):
    """Two volunteers race for two free seats, and staleness — not capacity — decides the loser.

    "Reserving a seat on a shift requires `expected_shift_version` matching the
    parent shift's current `version`; a mismatch means the shift's confirmed counts,
    lock state, or slot inventory changed after the client computed that a seat was
    free, and the reservation is rejected with `ERR_STALE_SHIFT_VERSION` (HTTP 412)."

    Slot two of two is genuinely free throughout, so the retry on the refreshed
    version fills it.

    Design: Corner/cross_cutting_complexity_layers/occ_seat_request_rejects_the_shift_version_spent_by_the_first_seat
    """
    program = X.setup_program(api)
    site = X.setup_ready_site(api, program["id"])
    volunteer_a = X.setup_volunteer(
        api, program["id"], full_name="Dana Reyes", birth_date="1990-04-10T00:00:00.000Z"
    )
    volunteer_b = X.setup_volunteer(
        api, program["id"], full_name="Omar Vance", birth_date="1991-02-02T00:00:00.000Z"
    )
    shift = X.setup_shift(api, site["id"], volunteer_slots=2)
    opened = X.open_shift(api, shift["id"])
    version_at_open = opened["version"]

    first_seat = validate_success(
        api.create_assignment(
            F.assignment_payload(shift["id"], version_at_open, volunteer_id=volunteer_a["id"]),
            headers=CREW_LEAD,
        ),
        201,
    )
    assert first_seat["status"] == C.ASSIGNMENT_RESERVED
    assert first_seat["volunteer_id"] == volunteer_a["id"]

    validate_error(
        api.create_assignment(
            F.assignment_payload(shift["id"], version_at_open, volunteer_id=volunteer_b["id"]),
            headers=CREW_LEAD,
        ),
        E.ERR_STALE_SHIFT_VERSION,
        412,
    )

    next_version = X.shift_version(api, shift["id"])
    A.assert_version_bumped_by(version_at_open, next_version, 1)

    second_seat = validate_success(
        api.create_assignment(
            F.assignment_payload(shift["id"], next_version, volunteer_id=volunteer_b["id"]),
            headers=CREW_LEAD,
        ),
        201,
    )
    assert second_seat["status"] == C.ASSIGNMENT_RESERVED
    assert second_seat["volunteer_id"] == volunteer_b["id"]

    rows, meta = validate_paginated(
        api.list_assignments(
            {"shift_id": shift["id"], "status": C.ASSIGNMENT_RESERVED}, headers=CREW_LEAD
        )
    )
    assert meta["total_count"] == 2
    assert {row["id"] for row in rows} == {first_seat["id"], second_seat["id"]}


def test_approval_is_refused_on_a_program_version_a_pool_top_up_already_spent(api):
    """A donor gift lands between the officer's read and the approve, and the commitment waits.

    "Approving a mortgage commits silent-second subsidy out of the shared program
    pool, so an approval must carry `expected_program_version` matching the governing
    program's current `version`. If an earlier accepted write — another approval, a
    pool adjustment, or a closing — has already moved the pool since the client last
    read the program, the approval is rejected with `ERR_STALE_PROGRAM_VERSION` (HTTP
    412), because the pool arithmetic this request was built on no longer holds."

    The enlarged pool would have covered the silent second easily, which is what makes
    this a staleness refusal and not a subsidy refusal.

    Design: Corner/cross_cutting_complexity_layers/occ_approve_rejects_a_program_version_spent_by_a_pool_top_up
    """
    program = X.setup_program(api)
    site = X.setup_ready_site(api, program["id"])
    built = X.setup_selected_household(api, program["id"])
    application = X.setup_underwritten_application(api, built["household"]["id"], site["id"])
    assert application["silent_second_amount_cents"] == 1_950_000

    stale_version = X.program_version(api, program["id"])
    topped_up = validate_success(
        api.adjust_subsidy_pool(
            program["id"],
            F.pool_adjustment_payload(
                C.POOL_ACTION_TOP_UP,
                stale_version,
                delta_cents=1_000_000,
                memo="Q3 donor gift added to the pool",
            ),
            headers=ADMIN,
        )
    )
    assert topped_up["subsidy_pool_cents"] == 6_000_000

    validate_error(
        api.approve_application(
            application["id"], F.approval_payload(stale_version), headers=APPROVER
        ),
        E.ERR_STALE_PROGRAM_VERSION,
        412,
    )

    fresh_version = X.program_version(api, program["id"])
    A.assert_version_bumped_by(stale_version, fresh_version, 1)
    waiting = validate_success(api.get_application(application["id"], headers=OFFICER))
    assert waiting["status"] == C.APP_UNDERWRITING
    assert (
        validate_success(api.get_program(program["id"], headers=ADMIN))["subsidy_committed_cents"] == 0
    )

    approved = validate_success(
        api.approve_application(
            application["id"], F.approval_payload(fresh_version), headers=APPROVER
        )
    )
    assert approved["status"] == C.APP_APPROVED
    assert approved["silent_second_amount_cents"] == 1_950_000

    A.assert_pool_state(
        validate_success(api.get_program(program["id"], headers=ADMIN)),
        pool_cents=6_000_000,
        committed_cents=1_950_000,
        disbursed_cents=0,
        available_cents=4_050_000,
        posture=C.POSTURE_OPEN,
    )


def test_a_pool_adjustment_is_refused_on_a_spent_version_and_each_accepted_write_bumps_it_once(api):
    """Four accepted adjustments and one refusal move the version by exactly four.

    "A subsidy-pool adjustment carries `expected_program_version` for the same reason
    and is rejected with the same `ERR_STALE_PROGRAM_VERSION` (HTTP 412) when it was
    sized against a balance an earlier write has already changed." Each accepted one
    counts once: "In all four cases `subsidy_available_cents` and `program_posture`
    are recomputed and the program's `version` increments by 1."

    Design: Corner/cross_cutting_complexity_layers/occ_pool_adjustment_rejects_a_spent_version_and_every_write_bumps_it
    """
    program = X.setup_program(api)
    version_0 = program["version"]

    topped_up = validate_success(
        api.adjust_subsidy_pool(
            program["id"],
            F.pool_adjustment_payload(
                C.POOL_ACTION_TOP_UP, version_0, delta_cents=1_000_000, memo="Donor gift one"
            ),
            headers=ADMIN,
        )
    )
    assert topped_up["subsidy_pool_cents"] == 6_000_000
    version_1 = topped_up["version"]
    A.assert_version_bumped_by(version_0, version_1, 1)

    validate_error(
        api.adjust_subsidy_pool(
            program["id"],
            F.pool_adjustment_payload(
                C.POOL_ACTION_REDUCE,
                version_0,
                delta_cents=500_000,
                memo="Replaying the version already spent by the top up",
            ),
            headers=ADMIN,
        ),
        E.ERR_STALE_PROGRAM_VERSION,
        412,
    )
    # The refused delta was applied nowhere.
    assert validate_success(api.get_program(program["id"], headers=ADMIN))["subsidy_pool_cents"] == 6_000_000

    reduced = validate_success(
        api.adjust_subsidy_pool(
            program["id"],
            F.pool_adjustment_payload(
                C.POOL_ACTION_REDUCE,
                version_1,
                delta_cents=500_000,
                memo="Reallocating to the repair program",
            ),
            headers=ADMIN,
        )
    )
    assert reduced["subsidy_pool_cents"] == 5_500_000
    version_2 = reduced["version"]
    A.assert_version_bumped_by(version_1, version_2, 1)

    suspended = validate_success(
        api.adjust_subsidy_pool(
            program["id"],
            F.pool_adjustment_payload(
                C.POOL_ACTION_SUSPEND, version_2, memo="Board pause pending audit"
            ),
            headers=ADMIN,
        )
    )
    assert suspended["status"] == C.PROGRAM_STATUS_SUSPENDED
    assert suspended["program_posture"] == C.POSTURE_FROZEN
    version_3 = suspended["version"]
    A.assert_version_bumped_by(version_2, version_3, 1)

    resumed = validate_success(
        api.adjust_subsidy_pool(
            program["id"],
            F.pool_adjustment_payload(
                C.POOL_ACTION_RESUME, version_3, memo="Audit cleared, program resumed"
            ),
            headers=ADMIN,
        )
    )
    assert resumed["status"] == C.PROGRAM_STATUS_ACTIVE
    assert resumed["program_posture"] == C.POSTURE_OPEN
    version_4 = resumed["version"]
    A.assert_version_bumped_by(version_3, version_4, 1)

    final = validate_success(api.get_program(program["id"], headers=ADMIN))
    assert final["version"] == version_4 == version_0 + 4
    A.assert_pool_state(
        final,
        pool_cents=5_500_000,
        committed_cents=0,
        disbursed_cents=0,
        available_cents=5_500_000,
        posture=C.POSTURE_OPEN,
    )
