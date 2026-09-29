"""State machines that are not simple chains: an admission carrying two independent
status dimensions, and a protective-order case whose refile loop changes where the
same trigger word lands on its third lap.
"""

from test_helpers import (
    ADMIN_HEADERS,
    MODERATE_FACTORS,
    advance_clock,
    api_client,
    assert_bed_ledger_invariant,
    assert_protective_order_case,
    assert_timestamp_with_millis,
    assert_unit_status_derived,
    create_client_payload,
    exit_household,
    file_case,
    get_success_data,
    read_admission,
    read_client,
    read_unit,
    record_outcome,
    report_compromise,
    seed_checked_in_admission,
    seed_legal_advocate,
    seed_protective_order_case,
    seed_shelter_scene,
    validate_success,
)

FAMILY_OF_THREE = {
    "client_code": "C-5001",
    "legal_name": "Alina Ford",
    "household_size": 3,
    "minor_children_count": 2,
    "hmis_disclosure_consent": "DENIED",
}


def _checked_in_family():
    """A family of three checked into a four-bed family suite, clock at the exit date."""
    scene = seed_shelter_scene(unit_overrides={"unit_type": "FAMILY_SUITE", "bed_capacity": 4})
    scene, client, _request, admission = seed_checked_in_admission(
        scene=scene,
        client_overrides=dict(FAMILY_OF_THREE),
        assessment_overrides=dict(MODERATE_FACTORS),
        check_in_overrides={"school_enrollment_confirmed": True},
        entry_clock="2026-08-07T09:00:00Z",
    )
    advance_clock("2026-08-12T09:00:00Z")
    return scene, client, admission


def test_compromise_moves_only_the_security_dimension_and_no_beds():
    """A checked-in household stays checked in, and its beds stay booked, when the address leaks.

    PRD: "A household that is `CHECKED_IN` and whose location is `COMPROMISED` stays
    `CHECKED_IN`; recording a compromise moves no beds and changes no occupancy."

    Design: Difficulty/non_linear_state_machine/admission_occupancy_and_security_dimensions_advance_independently
    """
    scene, client, admission = _checked_in_family()

    response = report_compromise(scene, admission["id"], compromise_source="ABUSER_CONTACT")

    compromised = validate_success(response, 200)
    assert compromised["location_security_status"] == "COMPROMISED"
    assert compromised["occupancy_status"] == "CHECKED_IN"
    assert compromised["compromise_source"] == "ABUSER_CONTACT"
    unit = read_unit(scene.manager, scene.unit["id"])
    assert unit["reserved_beds"] == 0
    assert unit["occupied_beds"] == 3
    assert unit["available_beds"] == 1
    assert unit["status"] == "OCCUPIED"
    assert_bed_ledger_invariant(unit)
    assert_unit_status_derived(unit)
    assert read_client(client["id"])["confidentiality_posture"] == "SEALED"


def test_exit_advances_occupancy_without_resetting_a_compromised_location():
    """The occupancy dimension reaches its terminal state while the security one holds.

    PRD: "`location_security_status` tracks whether the confidential location still
    holds: `SECURE`, then `COMPROMISED`, then `RELOCATED`, with `RELOCATED` terminal."

    Design: Difficulty/non_linear_state_machine/admission_occupancy_and_security_dimensions_advance_independently
    """
    scene, client, admission = _checked_in_family()
    get_success_data(
        report_compromise(scene, admission["id"], compromise_source="ABUSER_CONTACT")
    )

    response = exit_household(
        scene, admission["id"], "2026-08-12", exit_destination="FAMILY_FRIENDS"
    )

    exited = validate_success(response, 200)
    assert exited["occupancy_status"] == "EXITED"
    assert exited["location_security_status"] == "COMPROMISED"
    assert exited["settled_stay_cost_cents"] == 59500
    unit = read_unit(scene.manager, scene.unit["id"])
    assert unit["occupied_beds"] == 0
    assert unit["available_beds"] == 4
    assert unit["status"] == "AVAILABLE"
    assert_bed_ledger_invariant(unit)
    assert read_admission(scene.manager, admission["id"])["location_security_status"] == "COMPROMISED"
    assert read_client(client["id"])["confidentiality_posture"] == "SEALED"


def _twice_refiled_case():
    """Draft a petition, then run the refile loop twice and file it a third time."""
    legal = seed_legal_advocate("Iris Vale", max_caseload=12)
    client = get_success_data(
        api_client.create_client(
            create_client_payload(
                client_code="C-6001",
                legal_name="Priya Nair",
                household_size=1,
                minor_children_count=0,
                hmis_disclosure_consent="DENIED",
            ),
            ADMIN_HEADERS,
        )
    )
    case = seed_protective_order_case(legal, client["id"], order_type="FULL_ORDER")
    get_success_data(
        file_case(legal, case["id"], legal.id, "2026-08-20T09:00:00Z", "2026-08-20T10:00:00Z")
    )
    advance_clock("2026-08-20T12:00:00Z")
    first_denial = get_success_data(record_outcome(legal, case["id"], "DENIED"))
    get_success_data(
        file_case(legal, case["id"], legal.id, "2026-08-21T09:00:00Z", "2026-08-21T10:00:00Z")
    )
    advance_clock("2026-08-21T12:00:00Z")
    second_denial = get_success_data(record_outcome(legal, case["id"], "DENIED"))
    third_filing = get_success_data(
        file_case(legal, case["id"], legal.id, "2026-08-22T09:00:00Z", "2026-08-22T10:00:00Z")
    )
    advance_clock("2026-08-22T12:00:00Z")
    return legal, client, case, first_denial, second_denial, third_filing


def test_refile_loop_returns_a_denied_case_to_petition_drafted_twice():
    """Below the cap, DENIED routes back to PETITION_DRAFTED and clears the hearing window.

    PRD: "While `refile_count` is below 2, the case moves `FILED` → `PETITION_DRAFTED`,
    closing the refile loop `PETITION_DRAFTED` → `FILED` → `PETITION_DRAFTED`, which may
    therefore run at most twice."

    Design: Difficulty/non_linear_state_machine/protective_order_refile_loop_reaches_denied_final
    """
    _legal, _client, _case, first_denial, second_denial, third_filing = _twice_refiled_case()

    assert first_denial["status"] == "PETITION_DRAFTED"
    assert first_denial["refile_count"] == 1
    assert first_denial["hearing_start_utc"] is None
    assert first_denial["hearing_end_utc"] is None
    assert first_denial["filed_court"] is None
    assert first_denial["accompanying_advocate_id"] is None
    assert second_denial["status"] == "PETITION_DRAFTED"
    assert second_denial["refile_count"] == 2
    assert third_filing["status"] == "FILED"
    assert third_filing["refile_count"] == 2
    assert_protective_order_case(third_filing)


def test_third_denial_takes_the_other_branch_out_of_filed_to_denied_final():
    """With refile_count at 2 the identical DENIED outcome lands on a different state.

    PRD: "Once `refile_count` has reached 2, the same `DENIED` outcome instead moves the
    case `FILED` → `DENIED_FINAL`, which is terminal: `outcome_recorded_at` is set,
    `refile_count` stays at 2, and the hearing window and `accompanying_advocate_id` are
    cleared just as they are on the refile path."

    Design: Difficulty/non_linear_state_machine/protective_order_refile_loop_reaches_denied_final
    """
    legal, client, case, _first, _second, third_filing = _twice_refiled_case()
    assert third_filing["status"] == "FILED"

    response = record_outcome(legal, case["id"], "DENIED")

    final = validate_success(response, 200)
    assert final["status"] == "DENIED_FINAL"
    assert final["refile_count"] == 2
    assert final["hearing_start_utc"] is None
    assert final["accompanying_advocate_id"] is None
    assert_timestamp_with_millis(final["outcome_recorded_at"])
    assert final["outcome_recorded_at"].startswith("2026-08-22T12:00:00")
    survivor = read_client(client["id"])
    assert survivor["protective_order_active"] is False
    assert survivor["confidentiality_posture"] == "NORMAL"
