"""The error catalogue of PRD section 5, reached one code at a time.

Each test drives the API into exactly the state a single catalogue entry
describes, so the code that comes back is the one the precedence ladder of PRD
2.7 selects rather than an easier failure detected earlier.
"""

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    assert_cents,
    assert_ratio,
    factories as f,
    validate_error,
    validate_success,
)
from test_helpers.api_errors import (
    ERR_BLOCK_NOT_MECHANICALLY_COMPLETE,
    ERR_BLOCK_PILES_INCOMPLETE,
    ERR_BLOCKS_NOT_MC_READY,
    ERR_CIRCUIT_STATE_INVALID,
    ERR_DELIVERY_NOT_FOUND,
    ERR_BLOCK_NOT_FOUND,
    ERR_LABOR_ENTRY_ALREADY_VOIDED,
    ERR_LABOR_ENTRY_NOT_FOUND,
    ERR_MILESTONE_OUT_OF_SEQUENCE,
    ERR_OPEN_CRITICAL_PUNCH_ITEMS,
    ERR_OPEN_PUNCH_ITEMS,
    ERR_OUTAGE_WINDOW_ALREADY_ANSWERED,
    ERR_OUTAGE_WINDOW_NOT_FOUND,
    ERR_PAYROLL_WEEK_NOT_FOUND,
    ERR_PERMIT_NOT_ACTIVE,
    ERR_PILE_NOT_DRIVEABLE,
    ERR_PILE_NOT_FOUND,
    ERR_PILE_NOT_REMEDIABLE,
    ERR_PUNCH_ITEM_NOT_FOUND,
    ERR_REQUIRED_TEST_NOT_PASSED,
    ERR_STRING_CIRCUIT_NOT_FOUND,
    ERR_SUBSTATION_NOT_FOUND,
    ERR_TAX_CREDIT_NOT_QUALIFIED,
    ERR_TEST_STATE_INVALID,
)
from test_helpers.fixtures import (
    append_interval,
    approved_outage_window,
    create_block,
    create_circuit,
    create_grading_area,
    create_payroll_week,
    create_pile,
    create_punch_item,
    create_substation,
    decide_closure,
    piles_complete_block,
    post_labor_entry,
    read_block,
    read_circuit,
    read_commissioning_test,
    read_grading_area,
    read_labor_entry,
    read_payroll_week,
    read_pile,
    read_project,
    read_outage_window,
    record_bmp_inspection,
    record_drive_result,
    run_labor_compliance,
    schedule_commissioning_test,
    submit_closure,
    void_labor_entry,
)


@pytest.mark.parametrize(
    "reader,expected_error",
    [
        ("get_delivery", ERR_DELIVERY_NOT_FOUND),
        ("get_block", ERR_BLOCK_NOT_FOUND),
        ("get_pile", ERR_PILE_NOT_FOUND),
        ("get_string_circuit", ERR_STRING_CIRCUIT_NOT_FOUND),
        ("get_substation", ERR_SUBSTATION_NOT_FOUND),
        ("get_outage_window", ERR_OUTAGE_WINDOW_NOT_FOUND),
        ("get_punch_list_item", ERR_PUNCH_ITEM_NOT_FOUND),
        ("get_payroll_week", ERR_PAYROLL_WEEK_NOT_FOUND),
        ("get_labor_entry", ERR_LABOR_ENTRY_NOT_FOUND),
    ],
)
def test_unknown_id_returns_the_entity_specific_not_found(
    api, epc_headers, reader, expected_error
):
    """A well-formed id that matches nothing yields the not-found code of the entity
    kind the route addresses, never a shared generic one.

    PRD 2.6: "Each entity kind has its own not-found code: `ERR_GRADING_AREA_NOT_FOUND`, `ERR_YARD_ZONE_NOT_FOUND`, `ERR_DELIVERY_NOT_FOUND`, `ERR_BLOCK_NOT_FOUND`, `ERR_PILE_NOT_FOUND`, `ERR_STRING_CIRCUIT_NOT_FOUND`, `ERR_SUBSTATION_NOT_FOUND`, `ERR_OUTAGE_WINDOW_NOT_FOUND`, `ERR_COMMISSIONING_TEST_NOT_FOUND`, `ERR_PUNCH_ITEM_NOT_FOUND`, `ERR_PAYROLL_WEEK_NOT_FOUND` and `ERR_LABOR_ENTRY_NOT_FOUND`, each returning HTTP 404."

    Design: Corner/errors/unknown_ids_return_the_entity_specific_not_found_error
    """
    validate_error(
        getattr(api, reader)(NON_EXISTENT_UUID, epc_headers), expected_error
    )


def test_void_of_an_unknown_line_is_a_not_found_before_any_state_guard(
    api, labor_headers
):
    """An action route on a missing row answers with existence, not with the state
    guard that would otherwise apply to it.

    PRD 2.7: "The server therefore evaluates checks in a fixed global precedence order and returns the **first** failure it encounters, never a later one that happens to be easier to detect."

    Design: Corner/errors/unknown_ids_return_the_entity_specific_not_found_error
    """
    validate_error(
        api.void_labor_entry(NON_EXISTENT_UUID, f.void_payload(), labor_headers),
        ERR_LABOR_ENTRY_NOT_FOUND,
    )


def test_mechanical_completion_needs_the_block_at_piles_complete(
    api, project, accepted_grading_area, foreman_headers
):
    """A block whose piles are not all accepted cannot be declared mechanically
    complete.

    PRD 3.4: "The block must be at `PILES_COMPLETE`; any other mechanical status, including `HOLD`, is refused with `ERR_BLOCK_PILES_INCOMPLETE`."

    Design: Corner/errors/state_guard_errors_fire_from_every_wrong_state
    """
    block = create_block(api, project["id"], accepted_grading_area["id"])
    assert block["mechanical_status"] == "PLANNED"

    validate_error(
        api.declare_mechanical_completion(
            block["id"], f.mechanical_completion_payload(), foreman_headers
        ),
        ERR_BLOCK_PILES_INCOMPLETE,
    )
    assert read_block(api, block["id"])["mechanical_status"] == "PLANNED"


def test_string_test_on_a_planned_circuit_is_refused(
    api, project, accepted_grading_area, foreman_headers
):
    """A circuit that has never been terminated into its combiner box cannot carry a
    string test result.

    PRD 3.5: "A test result may be recorded on a circuit that is `WIRED`, `TESTED` or `FAILED` — retesting is explicitly permitted and unbounded — while a `PLANNED` circuit refuses the operation with `ERR_CIRCUIT_STATE_INVALID`."

    Design: Corner/errors/state_guard_errors_fire_from_every_wrong_state
    """
    block = create_block(api, project["id"], accepted_grading_area["id"])
    circuit = create_circuit(api, block["id"])
    assert circuit["status"] == "PLANNED"

    validate_error(
        api.create_string_test_result(
            circuit["id"], f.string_test_payload(), foreman_headers
        ),
        ERR_CIRCUIT_STATE_INVALID,
    )
    unchanged = read_circuit(api, circuit["id"])
    assert unchanged["status"] == "PLANNED"
    assert unchanged["combiner_position"] is None


def test_second_drive_on_the_same_pile_is_refused(
    api, project, accepted_grading_area, foreman_headers
):
    """A pile leaves `PLANNED` the moment its drive is recorded, so the drive cannot
    be replayed.

    PRD 3.4: "The pile must also still be `PLANNED`; a second drive on the same pile is refused with `ERR_PILE_NOT_DRIVEABLE`."

    Design: Corner/errors/state_guard_errors_fire_from_every_wrong_state
    """
    block = create_block(api, project["id"], accepted_grading_area["id"])
    pile = create_pile(api, block["id"])
    driven = record_drive_result(api, pile["id"])
    assert driven["status"] == "ACCEPTED"

    validate_error(
        api.create_drive_result(
            pile["id"], f.drive_result_payload(actual_embedment_mm=2900), foreman_headers
        ),
        ERR_PILE_NOT_DRIVEABLE,
    )
    kept = read_pile(api, pile["id"])
    assert kept["status"] == "ACCEPTED"
    assert kept["actual_embedment_mm"] == 3000


def test_remediation_of_an_accepted_pile_is_refused(
    api, project, accepted_grading_area, foreman_headers
):
    """Remediation exists only for out-of-tolerance or refused piles, not for one the
    survey already accepted.

    PRD 3.4: "A pile that is `OUT_OF_TOLERANCE` or `REFUSED` may be remediated by the `InstallationForeman`, again only while the owning block's grading area is `ACCEPTED`; a pile in any other status is refused with `ERR_PILE_NOT_REMEDIABLE`."

    Design: Corner/errors/state_guard_errors_fire_from_every_wrong_state
    """
    block = create_block(api, project["id"], accepted_grading_area["id"])
    pile = create_pile(api, block["id"])
    assert record_drive_result(api, pile["id"])["status"] == "ACCEPTED"

    validate_error(
        api.create_remediation(
            pile["id"], f.remediation_payload("SPLICE", 3000, 4.0), foreman_headers
        ),
        ERR_PILE_NOT_REMEDIABLE,
    )
    assert read_pile(api, pile["id"])["status"] == "ACCEPTED"


def test_second_utility_response_on_a_window_is_refused(
    api, project, utility_headers
):
    """An outage window is answered once; the utility cannot revise its own verdict
    through a second response.

    PRD 3.6: "The window must still be at `REQUESTED`; a second response on the same window is refused with `ERR_OUTAGE_WINDOW_ALREADY_ANSWERED`."

    Design: Corner/errors/state_guard_errors_fire_from_every_wrong_state
    """
    substation = create_substation(api, project["id"])
    window = approved_outage_window(
        api,
        substation["id"],
        start_at="2026-08-12T00:00:00Z",
        end_at="2026-08-12T04:00:00Z",
        purpose="SWITCHING",
    )
    assert window["status"] == "APPROVED"

    validate_error(
        api.create_utility_response(
            window["id"], f.utility_response_payload("DENY"), utility_headers
        ),
        ERR_OUTAGE_WINDOW_ALREADY_ANSWERED,
    )
    kept = read_outage_window(api, window["id"])
    assert kept["status"] == "APPROVED"
    assert kept["utility_reference"] == "SO-4471"


def test_finalizing_a_scheduled_test_is_refused(api, project, commissioning_headers):
    """Finalization belongs to a test that has begun sampling, not to one that is
    merely scheduled.

    PRD 3.7: "The test must be `IN_PROGRESS`, or the request is refused with `ERR_TEST_STATE_INVALID`."

    Design: Corner/errors/state_guard_errors_fire_from_every_wrong_state
    """
    test = schedule_commissioning_test(api, project["id"], test_type="CAPACITY")
    assert test["status"] == "SCHEDULED"

    validate_error(
        api.finalize_commissioning_test(
            test["id"], f.finalization_payload(), commissioning_headers
        ),
        ERR_TEST_STATE_INVALID,
    )
    assert read_commissioning_test(api, test["id"])["status"] == "SCHEDULED"


def test_second_void_of_a_labor_entry_is_refused(api, project, labor_headers):
    """A voided line is already out of the ledger, so the compensating action cannot
    be applied twice.

    PRD 3.8: "A void carries a `void_reason` and requires both that the line still be `POSTED` — an already-voided line is refused with `ERR_LABOR_ENTRY_ALREADY_VOIDED` — and that its owning week still be `OPEN`, failing which it is refused with `ERR_PAYROLL_WEEK_LOCKED`."

    Design: Corner/errors/state_guard_errors_fire_from_every_wrong_state
    """
    week = create_payroll_week(api, project["id"], week_start_date="2026-08-03")
    entry = post_labor_entry(api, week["id"], hours=8.00, work_date="2026-08-03")
    voided = void_labor_entry(api, entry["id"], void_reason="duplicate posting")
    assert voided["status"] == "VOIDED"

    validate_error(
        api.void_labor_entry(
            entry["id"], f.void_payload(void_reason="duplicate posting"), labor_headers
        ),
        ERR_LABOR_ENTRY_ALREADY_VOIDED,
    )
    kept = read_labor_entry(api, entry["id"])
    assert kept["status"] == "VOIDED"
    assert kept["void_reason"] == "duplicate posting"
    ledger = read_payroll_week(api, week["id"])
    assert_ratio(ledger["total_hours"], 0.00, "total_hours")
    assert ledger["entry_count"] == 0


def test_wiring_before_mechanical_completion_is_refused(
    api, project, accepted_grading_area, foreman_headers
):
    """A block that has finished its piles but has not been declared mechanically
    complete still refuses string termination.

    PRD 3.5: "Terminating a string into its combiner box requires the mechanical work above it to be finished: the owning block must have `mechanical_status` `MECH_COMPLETE`, and wiring attempted before that is refused with `ERR_BLOCK_NOT_MECHANICALLY_COMPLETE`."

    Design: Corner/errors/readiness_permit_and_sequencing_gates_are_each_reachable
    """
    block = piles_complete_block(api, project["id"], accepted_grading_area["id"])
    assert block["mechanical_status"] == "PILES_COMPLETE"
    circuit = create_circuit(api, block["id"], circuit_code="C1")

    validate_error(
        api.create_wiring(circuit["id"], f.wiring_payload(), foreman_headers),
        ERR_BLOCK_NOT_MECHANICALLY_COMPLETE,
    )
    unchanged = read_circuit(api, circuit["id"])
    assert unchanged["status"] == "PLANNED"
    assert unchanged["combiner_position"] is None
    assert read_block(api, block["id"])["mechanical_status"] == "PILES_COMPLETE"


def test_mechanical_completion_claim_while_readiness_is_blocked_is_refused(
    api, project, accepted_grading_area, epc_headers
):
    """With no block mechanically and electrically finished, and an area still
    unaccepted, the project is not claimable.

    PRD 3.9: "A mechanical-completion claim requires `milestone_state` `PRECONSTRUCTION` and `mc_readiness` `READY`; a claim filed while readiness is `BLOCKED` is refused with `ERR_BLOCKS_NOT_MC_READY`."

    Design: Corner/errors/readiness_permit_and_sequencing_gates_are_each_reachable
    """
    block = piles_complete_block(api, project["id"], accepted_grading_area["id"])
    assert block["mc_ready"] is False
    create_grading_area(
        api, project["id"], area_code="A2", permit_number="CGP-2026-119"
    )
    blocked = read_project(api, project["id"])
    assert blocked["mc_readiness"] == "BLOCKED"

    validate_error(
        api.create_milestone_claim(
            project["id"],
            f.milestone_claim_payload("MECHANICAL_COMPLETION"),
            epc_headers,
        ),
        ERR_BLOCKS_NOT_MC_READY,
    )
    held = read_project(api, project["id"])
    assert held["milestone_state"] == "PRECONSTRUCTION"
    assert held["mc_claimed_by_user_id"] is None


def test_earthwork_under_an_open_bmp_deficiency_is_refused(api, project, civil_headers):
    """An open best-management-practice deficiency stops earthwork even though the
    permit itself is still active and the area is open for work.

    PRD 3.2: "Permit currency comes first: an area whose `permit_status` is anything other than `ACTIVE`, or whose `bmp_deficiency_open` is true, refuses work with `ERR_PERMIT_NOT_ACTIVE`."

    Design: Corner/errors/readiness_permit_and_sequencing_gates_are_each_reachable
    """
    area = create_grading_area(
        api, project["id"], area_code="A2", permit_number="CGP-2026-119"
    )
    deficient = record_bmp_inspection(api, area["id"], "2026-08-01T06:00:00Z", True)
    assert deficient["bmp_deficiency_open"] is True
    assert deficient["permit_status"] == "ACTIVE"
    assert deficient["status"] == "PLANNED"

    validate_error(
        api.create_earthwork_log(
            area["id"],
            f.earthwork_log_payload(
                "CLEARING", "2026-08-03T12:00:00Z", "2026-08-03T20:00:00Z", 5.00
            ),
            civil_headers,
        ),
        ERR_PERMIT_NOT_ACTIVE,
    )
    kept = read_grading_area(api, area["id"])
    assert kept["status"] == "PLANNED"
    assert kept["permit_status"] == "ACTIVE"
    assert_ratio(kept["disturbed_acreage_current"], 0.00, "disturbed_acreage_current")
    assert kept["earthwork_windows"] == []


def test_milestone_ladder_reaches_every_acceptance_gate_in_turn(
    api, energized_plant, epc_headers, owner_headers, commissioning_headers
):
    """Walking one project from preconstruction to final acceptance surfaces each
    acceptance gate exactly where the ladder places it, and clearing that gate lets
    the next rung be filed.

    PRD 3.9: "Milestone administration runs as a two-party protocol across the project's `milestone_state`, which advances `PRECONSTRUCTION → MC_CLAIMED → MC_CERTIFIED → SC_CLAIMED → SC_CERTIFIED → FA_CLAIMED → FINAL_ACCEPTED`."

    Design: Corner/errors/milestone_ladder_reaches_every_acceptance_gate_error_in_turn
    """
    project_id = energized_plant["project"]["id"]
    assert energized_plant["project"]["mc_readiness"] == "READY"
    assert energized_plant["substation"]["status"] == "ENERGIZED"

    validate_error(
        api.create_milestone_claim(
            project_id,
            f.milestone_claim_payload("SUBSTANTIAL_COMPLETION"),
            epc_headers,
        ),
        ERR_MILESTONE_OUT_OF_SEQUENCE,
    )

    claimed = validate_success(
        api.create_milestone_claim(
            project_id,
            f.milestone_claim_payload("MECHANICAL_COMPLETION"),
            epc_headers,
        )
    )
    assert claimed["milestone_state"] == "MC_CLAIMED"
    assert claimed["mc_claimed_by_user_id"] == epc_headers["X-User-ID"]

    certified = validate_success(
        api.create_milestone_decision(
            project_id,
            f.milestone_decision_payload("MECHANICAL_COMPLETION", "CERTIFY"),
            owner_headers,
        )
    )
    assert certified["milestone_state"] == "MC_CERTIFIED"
    assert certified["mc_claimed_by_user_id"] is None

    validate_error(
        api.create_milestone_claim(
            project_id,
            f.milestone_claim_payload("SUBSTANTIAL_COMPLETION"),
            epc_headers,
        ),
        ERR_REQUIRED_TEST_NOT_PASSED,
    )

    capacity = schedule_commissioning_test(
        api,
        project_id,
        test_type="CAPACITY",
        scheduled_at="2026-08-10T02:30:00Z",
        correction_variant="AS_MEASURED",
    )
    append_interval(api, capacity["id"], "2026-08-10T02:35:00Z", 800, 99.00)
    append_interval(api, capacity["id"], "2026-08-10T02:40:00Z", 900, 99.00)
    capacity_result = validate_success(
        api.finalize_commissioning_test(
            capacity["id"], f.finalization_payload(), commissioning_headers
        )
    )
    assert capacity_result["valid_interval_count"] == 2
    assert_ratio(capacity_result["pass_threshold_kw_ac"], 98.00, "pass_threshold_kw_ac")
    assert_ratio(capacity_result["reported_kw_ac"], 99.00, "reported_kw_ac")
    assert capacity_result["status"] == "PASSED"

    critical = create_punch_item(
        api,
        project_id,
        title="Feeder termination torque unverified",
        category="ELECTRICAL",
        severity="CRITICAL",
        estimated_cost_cents=200000,
    )
    validate_error(
        api.create_milestone_claim(
            project_id,
            f.milestone_claim_payload("SUBSTANTIAL_COMPLETION"),
            epc_headers,
        ),
        ERR_OPEN_CRITICAL_PUNCH_ITEMS,
    )
    submit_closure(api, critical["id"])
    assert decide_closure(api, critical["id"], "APPROVE")["status"] == "CLOSED"

    sc_claimed = validate_success(
        api.create_milestone_claim(
            project_id,
            f.milestone_claim_payload("SUBSTANTIAL_COMPLETION"),
            epc_headers,
        )
    )
    assert sc_claimed["milestone_state"] == "SC_CLAIMED"

    settled = validate_success(
        api.create_milestone_decision(
            project_id,
            f.milestone_decision_payload("SUBSTANTIAL_COMPLETION", "CERTIFY"),
            owner_headers,
        )
    )
    assert settled["milestone_state"] == "SC_CERTIFIED"
    assert settled["delay_days"] == 9
    assert_cents(settled["ld_assessed_cents"], 450000, "ld_assessed_cents")
    assert_cents(settled["retainage_held_cents"], 500000, "retainage_held_cents")
    assert_cents(settled["punchlist_holdback_cents"], 0, "punchlist_holdback_cents")
    assert_cents(settled["sc_payment_due_cents"], 9050000, "sc_payment_due_cents")

    ratio_test = schedule_commissioning_test(
        api,
        project_id,
        test_type="PERFORMANCE_RATIO",
        scheduled_at="2026-08-10T03:00:00Z",
    )
    append_interval(api, ratio_test["id"], "2026-08-10T03:05:00Z", 800, 76.00)
    append_interval(api, ratio_test["id"], "2026-08-10T03:10:00Z", 900, 85.00)
    ratio_result = validate_success(
        api.finalize_commissioning_test(
            ratio_test["id"], f.finalization_payload(), commissioning_headers
        )
    )
    assert ratio_result["reported_performance_ratio"] == pytest.approx(0.7285, abs=0.0001)
    assert ratio_result["status"] == "PASSED"
    assert read_commissioning_test(api, capacity["id"])["status"] == "PASSED"

    minor = create_punch_item(
        api,
        project_id,
        title="Spare-parts inventory not handed over",
        category="DOCUMENTATION",
        severity="MINOR",
        estimated_cost_cents=50000,
    )
    validate_error(
        api.create_milestone_claim(
            project_id, f.milestone_claim_payload("FINAL_ACCEPTANCE"), epc_headers
        ),
        ERR_OPEN_PUNCH_ITEMS,
    )
    submit_closure(api, minor["id"], closure_evidence_ref="PHOTO-3003")
    assert decide_closure(api, minor["id"], "APPROVE")["status"] == "CLOSED"

    validate_error(
        api.create_milestone_claim(
            project_id, f.milestone_claim_payload("FINAL_ACCEPTANCE"), epc_headers
        ),
        ERR_TAX_CREDIT_NOT_QUALIFIED,
    )

    week = create_payroll_week(api, project_id, week_start_date="2026-08-03")
    post_labor_entry(
        api,
        week["id"],
        worker_ref="W-900",
        is_apprentice=True,
        hours=20.00,
        paid_rate_cents=4500,
        fringe_rate_cents=500,
        prevailing_rate_cents=5000,
        work_date="2026-08-03",
    )
    compliance = run_labor_compliance(api, project_id)
    assert_ratio(compliance["apprentice_hours_pct"], 100.00, "apprentice_hours_pct")
    assert_cents(
        compliance["wage_restitution_owed_cents"], 0, "wage_restitution_owed_cents"
    )
    assert compliance["tax_credit_status"] == "QUALIFIED"

    fa_claimed = validate_success(
        api.create_milestone_claim(
            project_id, f.milestone_claim_payload("FINAL_ACCEPTANCE"), epc_headers
        )
    )
    assert fa_claimed["milestone_state"] == "FA_CLAIMED"

    accepted = validate_success(
        api.create_milestone_decision(
            project_id,
            f.milestone_decision_payload("FINAL_ACCEPTANCE", "CERTIFY"),
            owner_headers,
        )
    )
    assert accepted["milestone_state"] == "FINAL_ACCEPTED"
    assert_cents(accepted["final_payment_cents"], 500000, "final_payment_cents")
    assert (
        accepted["sc_payment_due_cents"] + accepted["final_payment_cents"]
        == 10000000 - accepted["ld_assessed_cents"]
    )
