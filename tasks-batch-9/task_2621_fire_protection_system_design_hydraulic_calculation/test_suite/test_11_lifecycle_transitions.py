"""Declared transitions, refused transitions and the two-dimensional acceptance test."""
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.assertions import (
    assert_calculation_demand_snapshot,
    assert_classification,
    assert_demand_ledger,
    assert_flow,
    assert_margin,
    assert_posture,
    assert_pressure,
    assert_reopened,
    assert_seal_metadata_cleared,
    assert_sheet_counters,
)
from test_helpers.factories import (
    build_as_built_disposition_payload,
    build_as_built_payload,
    build_auxiliary_system_payload,
    build_commission_payload,
    build_qc_review_payload,
    build_reclassify_payload,
    build_record_clearance_payload,
    build_trade_clearance_payload,
)
from test_helpers.fixtures import (
    ADMIN_HEADERS,
    CHAIN_ITERATION_1,
    CHAIN_ITERATION_2,
    CHAIN_SUPPLY_ITERATION,
    CONTRACTOR_HEADERS,
    HC1_REQUIRED_PSI,
    PROJECT_TOTAL_DEMAND_GPM,
    STANDPIPE_DEMAND_GPM,
    append_iteration,
    build_converged_stage,
    build_design_stage,
    build_permitted_stage,
    build_project_stage,
    coordinate_sheet,
    create_auxiliary_system,
    create_calculation,
    create_engineer,
    create_evaluation,
    create_fire_pump,
    create_flow_test,
    create_hazard_area,
    create_project,
    create_reviewer,
    create_shop_drawing,
    lodge_submittal,
    begin_review,
    complete_review,
    open_acceptance_test,
    qc_pass,
    read_acceptance_test,
    read_auxiliary_system,
    read_calculation,
    read_evaluation,
    read_fire_pump,
    read_project,
    read_shop_drawing,
    record_witness,
    schedule_witness,
    seal,
)
from test_helpers.test_users import (
    make_ahj_reviewer_headers,
    make_design_engineer_headers,
    make_qc_reviewer_headers,
)

BANDS = {
    "STRUCTURAL": (96.0, 120.0),
    "MECHANICAL": (120.0, 144.0),
    "LIGHTING": (144.0, 168.0),
}
BLOCKING_NOTE = "Sprinkler main clashes with the beam flange"
CLEARED_NOTE = "Coordinated in the field"


def _sealed_stage(client):
    """FP-2601 with HC-1 sealed by the lead engineer against an adequate supply."""
    ctx = build_converged_stage(client)
    ctx["evaluation"] = create_evaluation(
        client,
        ctx["project_id"],
        ctx["flow_test_id"],
        ctx["calculation_id"],
        ctx["lead_id"],
    )
    ctx["evaluation_id"] = ctx["evaluation"]["id"]
    qc_pass(client, ctx["calculation_id"], ctx["second_id"])
    ctx["calculation"] = seal(client, ctx["calculation_id"], ctx["lead_id"])
    return ctx


def _drafted_sheet(client):
    """A sheet over the sealed HC-1 with all three trade items opened and PENDING."""
    ctx = _sealed_stage(client)
    sheet = create_shop_drawing(client, ctx["project_id"], ctx["calculation_id"])
    ctx["sheet_id"] = sheet["id"]
    assert sheet["state"] == "DRAFT"
    assert sheet["required_trade_count"] == 3
    assert sheet["cleared_trade_count"] == 0

    ctx["items"] = {}
    for trade, (low, high) in BANDS.items():
        payload = build_trade_clearance_payload(
            trade=trade, elevation_low_in=low, elevation_high_in=high
        )
        item = validate_success(
            client.create_trade_clearance(sheet["id"], payload, CONTRACTOR_HEADERS),
            expected_status=201,
        )
        assert item["state"] == "PENDING"
        assert item["conflict_severity"] is None
        ctx["items"][trade] = item
    # Opening the first item on a sheet moves it off DRAFT.
    assert read_shop_drawing(client, sheet["id"])["state"] == "IN_COORDINATION"
    return ctx


def _record(client, ctx, clearance_id, **payload_overrides):
    body = build_record_clearance_payload(**payload_overrides)
    return validate_success(
        client.record_trade_clearance(
            clearance_id, body, make_design_engineer_headers(ctx["lead_id"])
        )
    )


class TestShopDrawingCoordinationWalk:
    def test_01_a_blocking_conflict_drives_the_sheet_into_conflicted(self, client):
        """A conflict recorded with `conflict_severity` `BLOCKING` drives the sheet
        `IN_COORDINATION → CONFLICTED`; a conflict recorded as `ADVISORY` leaves the sheet
        in `IN_COORDINATION`, which is the whole point of the distinction.

        Design: Corner/state_machines/shop_drawing_walks_draft_through_conflicted_to_coordinated
        """
        ctx = _drafted_sheet(client)
        item = _record(
            client,
            ctx,
            ctx["items"]["STRUCTURAL"]["id"],
            outcome="CONFLICT_OPEN",
            conflict_severity="BLOCKING",
            note=BLOCKING_NOTE,
        )
        assert item["state"] == "CONFLICT_OPEN"
        assert item["conflict_severity"] == "BLOCKING"
        assert item["note"] == BLOCKING_NOTE
        assert_sheet_counters(read_shop_drawing(client, ctx["sheet_id"]), "CONFLICTED", 0)

    def test_02_clearing_the_conflicted_item_returns_the_sheet_to_coordination(
        self, client
    ):
        """A clearance that leaves `cleared_trade_count` short of `required_trade_count`
        moves the sheet to `IN_COORDINATION`: from `CONFLICTED` this is permitted only once
        no remaining item of the sheet is in `CONFLICT_OPEN` with `conflict_severity`
        `BLOCKING`.

        Design: Corner/state_machines/shop_drawing_walks_draft_through_conflicted_to_coordinated
        """
        ctx = _drafted_sheet(client)
        structural = ctx["items"]["STRUCTURAL"]["id"]
        _record(
            client,
            ctx,
            structural,
            outcome="CONFLICT_OPEN",
            conflict_severity="BLOCKING",
            note=BLOCKING_NOTE,
        )
        cleared = _record(client, ctx, structural, outcome="CLEARED", note=CLEARED_NOTE)
        assert cleared["state"] == "CLEARED"
        assert cleared["conflict_severity"] is None
        assert_sheet_counters(
            read_shop_drawing(client, ctx["sheet_id"]), "IN_COORDINATION", 1
        )

    def test_03_only_the_third_cleared_item_promotes_the_sheet(self, client):
        """A clearance that raises `cleared_trade_count` to `required_trade_count` moves the
        sheet to `COORDINATED`, whether it was in `IN_COORDINATION`, in `CONFLICTED` —
        provided no item of the sheet remains in `CONFLICT_OPEN` — or in `STALE`.

        Design: Corner/state_machines/shop_drawing_walks_draft_through_conflicted_to_coordinated
        """
        ctx = _drafted_sheet(client)
        structural = ctx["items"]["STRUCTURAL"]["id"]
        _record(
            client, ctx, structural, outcome="CONFLICT_OPEN",
            conflict_severity="BLOCKING", note=BLOCKING_NOTE,
        )
        _record(client, ctx, structural, outcome="CLEARED", note=CLEARED_NOTE)

        _record(client, ctx, ctx["items"]["MECHANICAL"]["id"], outcome="CLEARED", note=CLEARED_NOTE)
        assert_sheet_counters(
            read_shop_drawing(client, ctx["sheet_id"]), "IN_COORDINATION", 2
        )

        _record(client, ctx, ctx["items"]["LIGHTING"]["id"], outcome="CLEARED", note=CLEARED_NOTE)
        assert_sheet_counters(read_shop_drawing(client, ctx["sheet_id"]), "COORDINATED", 3)

        rows, meta = validate_paginated(
            client.list_trade_clearances(
                ctx["sheet_id"], ADMIN_HEADERS, params={"state": "CLEARED"}
            )
        )
        assert meta["total_count"] == 3
        assert {row["state"] for row in rows} == {"CLEARED"}


class TestDeclaredInitialStates:
    def test_04_three_fresh_rows_sit_on_their_declared_initial_states(self, client):
        """A new system opens with `status` `PROPOSED`, `interlock_verified` false, and both
        `outage_start_at` and `outage_end_at` null.

        Design: Corner/state_machines/newly_created_rows_start_in_their_declared_initial_states
        """
        ctx = build_project_stage(client)
        area = create_hazard_area(client, ctx["project_id"], ctx["lead_id"])
        calculation = create_calculation(
            client, ctx["project_id"], area["id"], ctx["lead_id"], k_factor=25.2
        )
        assert calculation["state"] == "DRAFT"
        assert calculation["iteration_count"] == 0
        assert calculation["chain_start_index"] == 1
        assert calculation["deficiency_psi"] is None
        assert calculation["stale_reason"] is None

        system = create_auxiliary_system(
            client,
            ctx["project_id"],
            ctx["lead_id"],
            system_type="STANDPIPE_CLASS_II",
            label="Hose station riser",
            riser_count=1,
        )
        assert system["status"] == "PROPOSED"
        assert system["interlock_verified"] is False
        assert system["outage_start_at"] is None
        assert system["outage_end_at"] is None
        assert_flow(system["demand_gpm"], 100.0)

        project = read_project(client, ctx["project_id"])
        assert project["status"] == "DESIGN"
        assert_posture(project, "OPEN")


def _qc_passed_with(client, **engineer_overrides):
    """The FP-2601 pipeline up to QC_PASSED, with a configurable lead engineer."""
    lead = create_engineer(client, **engineer_overrides)
    qc = create_engineer(
        client, full_name="Priya Nair", license_state="TX", license_number="PE-80455",
        license_status="ACTIVE",
    )
    reviewer = create_reviewer(client)
    project = create_project(client, lead["id"], reviewer["id"])
    ctx = {
        "lead_id": lead["id"],
        "second_id": qc["id"],
        "reviewer_id": reviewer["id"],
        "project_id": project["id"],
    }
    area = create_hazard_area(client, project["id"], lead["id"])
    create_auxiliary_system(client, project["id"], lead["id"])
    calculation = create_calculation(client, project["id"], area["id"], lead["id"])
    ctx["calculation_id"] = calculation["id"]
    append_iteration(client, calculation["id"], lead["id"], **CHAIN_ITERATION_1)
    append_iteration(client, calculation["id"], lead["id"], **CHAIN_ITERATION_2)
    flow_test = create_flow_test(client, project["id"], lead["id"])
    create_evaluation(client, project["id"], flow_test["id"], calculation["id"], lead["id"])
    append_iteration(client, calculation["id"], lead["id"], **CHAIN_SUPPLY_ITERATION)
    ctx["evaluation"] = create_evaluation(
        client, project["id"], flow_test["id"], calculation["id"], lead["id"]
    )
    ctx["calculation"] = qc_pass(client, calculation["id"], qc["id"])
    return ctx


class TestSealLicenceGuards:
    def test_05_an_expired_licence_refuses_the_seal_and_leaves_the_row_qc_passed(
        self, client
    ):
        """First, the sealing engineer's `license_status` must be `ACTIVE`; an `EXPIRED` or
        `SUSPENDED` licence is refused with `ERR_SEAL_LICENSE_INACTIVE`.

        Design: Corner/state_machines/seal_is_refused_when_the_sealing_engineers_license_is_expired
        """
        ctx = _qc_passed_with(client, license_status="EXPIRED")
        assert ctx["calculation"]["state"] == "QC_PASSED"
        assert_margin(ctx["evaluation"], 65.54, 10.00, 15.3, "ADEQUATE")

        refused = client.seal_calculation(
            ctx["calculation_id"], make_design_engineer_headers(ctx["lead_id"])
        )
        validate_error(refused, "ERR_SEAL_LICENSE_INACTIVE", expected_status=409)

        calculation = read_calculation(client, ctx["calculation_id"])
        assert calculation["state"] == "QC_PASSED"
        assert calculation["sealed_by_engineer_id"] is None
        assert calculation["sealed_at"] is None
        assert read_project(client, ctx["project_id"])["sealed_calculation_count"] == 0

    def test_06_an_out_of_state_registration_refuses_the_seal_with_its_own_error(
        self, client
    ):
        """Second, the sealing engineer's `license_state` must equal the project's
        `jurisdiction_state`; a licence registered elsewhere is refused with
        `ERR_SEAL_LICENSE_JURISDICTION_MISMATCH`.

        Design: Corner/state_machines/seal_is_refused_when_the_license_state_differs_from_the_project_jurisdiction
        """
        ctx = _qc_passed_with(client, license_state="NV", license_status="ACTIVE")
        refused = client.seal_calculation(
            ctx["calculation_id"], make_design_engineer_headers(ctx["lead_id"])
        )
        validate_error(
            refused, "ERR_SEAL_LICENSE_JURISDICTION_MISMATCH", expected_status=409
        )

        calculation = read_calculation(client, ctx["calculation_id"])
        assert calculation["state"] == "QC_PASSED"
        assert read_project(client, ctx["project_id"])["sealed_calculation_count"] == 0


class TestQcRejection:
    def test_07_a_reject_returns_the_calculation_to_iterating_and_keeps_the_reviewer(
        self, client
    ):
        """A `REJECT` moves it `CONVERGED → ITERATING`, sets `stale_reason` to `QC_REJECTED`,
        and retains `qc_reviewed_by_engineer_id` for the audit trail rather than clearing it.

        Design: Corner/state_machines/qc_reject_returns_the_calculation_to_iterating_and_empties_the_ledger
        """
        ctx = build_converged_stage(client)
        before = read_project(client, ctx["project_id"])
        assert_demand_ledger(
            before,
            ctx["calculation_id"],
            1380.0,
            STANDPIPE_DEMAND_GPM,
            PROJECT_TOTAL_DEMAND_GPM,
        )

        rejected = validate_success(
            client.qc_review_calculation(
                ctx["calculation_id"],
                build_qc_review_payload(
                    disposition="REJECT", review_note="Remote area is not the corner bay"
                ),
                make_qc_reviewer_headers(ctx["second_id"]),
            ),
            expected_status=200,
        )
        assert rejected["state"] == "ITERATING"
        assert rejected["stale_reason"] == "QC_REJECTED"
        assert rejected["qc_reviewed_by_engineer_id"] == ctx["second_id"]
        assert rejected["iteration_count"] == 3
        assert_pressure(rejected["required_psi_at_base_of_riser"], HC1_REQUIRED_PSI)

    def test_08_the_rejected_calculation_drops_out_of_the_ledger(self, client):
        """Because an `ITERATING` calculation is not eligible for the demand ledger, a
        rejection also causes the ledger to be recomputed without it, which can hand the
        governing role to a different calculation or empty the ledger entirely.

        Design: Corner/state_machines/qc_reject_returns_the_calculation_to_iterating_and_empties_the_ledger
        """
        ctx = build_converged_stage(client)
        validate_success(
            client.qc_review_calculation(
                ctx["calculation_id"],
                build_qc_review_payload(disposition="REJECT"),
                make_qc_reviewer_headers(ctx["second_id"]),
            )
        )
        project = read_project(client, ctx["project_id"])
        assert_demand_ledger(
            project, None, 0.0, STANDPIPE_DEMAND_GPM, STANDPIPE_DEMAND_GPM
        )
        assert project["sealed_calculation_count"] == 0


class TestUndeclaredTransitions:
    def test_09_a_draft_calculation_cannot_be_sealed(self, client):
        """A request whose target is not terminal but whose current state has no declared
        transition for the requested action is refused with `ERR_INVALID_STATE_TRANSITION`.

        Design: Corner/state_machines/sealing_a_draft_calculation_and_qc_reviewing_an_iterating_one_are_invalid_transitions
        """
        ctx = build_design_stage(client)
        calculation = create_calculation(
            client, ctx["project_id"], ctx["hazard_area_id"], ctx["lead_id"]
        )
        assert calculation["state"] == "DRAFT"

        refused = client.seal_calculation(
            calculation["id"], make_design_engineer_headers(ctx["lead_id"])
        )
        validate_error(refused, "ERR_INVALID_STATE_TRANSITION", expected_status=409)
        assert read_calculation(client, calculation["id"])["state"] == "DRAFT"

    def test_10_an_iterating_calculation_cannot_be_qc_reviewed(self, client):
        """A converged calculation is not yet a sealed calculation. A second engineer, acting
        as `QcReviewer`, dispositions it by supplying a `disposition` of either `PASS` or
        `REJECT`.

        Design: Corner/state_machines/sealing_a_draft_calculation_and_qc_reviewing_an_iterating_one_are_invalid_transitions
        """
        ctx = build_design_stage(client)
        calculation = create_calculation(
            client, ctx["project_id"], ctx["hazard_area_id"], ctx["lead_id"]
        )
        validate_error(
            client.seal_calculation(
                calculation["id"], make_design_engineer_headers(ctx["lead_id"])
            ),
            "ERR_INVALID_STATE_TRANSITION",
        )

        moved = append_iteration(
            client, calculation["id"], ctx["lead_id"], **CHAIN_ITERATION_1
        )
        assert moved["iteration_index"] == 1
        assert read_calculation(client, calculation["id"])["state"] == "ITERATING"

        refused = client.qc_review_calculation(
            calculation["id"],
            build_qc_review_payload(disposition="PASS"),
            make_qc_reviewer_headers(ctx["second_id"]),
        )
        validate_error(refused, "ERR_INVALID_STATE_TRANSITION", expected_status=409)

        after = read_calculation(client, calculation["id"])
        assert after["state"] == "ITERATING"
        assert after["qc_reviewed_by_engineer_id"] is None
        assert read_project(client, ctx["project_id"])["sealed_calculation_count"] == 0


FIRST_WINDOW = dict(
    outage_start_at="2026-09-05T08:00:00Z", outage_end_at="2026-09-05T12:00:00Z"
)
SECOND_WINDOW = dict(
    outage_start_at="2026-09-20T08:00:00Z", outage_end_at="2026-09-20T12:00:00Z"
)


class TestDoubleCommissioning:
    def test_11_the_second_commission_is_refused_and_the_booked_window_survives(
        self, client
    ):
        """A successful commissioning records `outage_start_at`, `outage_end_at` and
        `interlock_verified`, and moves the system either `PROPOSED → COMMISSIONED` or
        `DECOMMISSIONED_PENDING_RETEST → COMMISSIONED`, advancing the system's `version`.

        Design: Corner/state_machines/commissioning_an_already_commissioned_system_is_rejected_on_the_second_call
        """
        ctx = build_project_stage(client)
        system = create_auxiliary_system(
            client,
            ctx["project_id"],
            ctx["lead_id"],
            system_type="STANDPIPE_CLASS_I",
            label="Stair 1 and 2 standpipes",
            riser_count=2,
        )
        assert system["interlock_required"] is False
        assert_flow(system["demand_gpm"], STANDPIPE_DEMAND_GPM)

        commissioned = validate_success(
            client.commission_auxiliary_system(
                system["id"], build_commission_payload(**FIRST_WINDOW), CONTRACTOR_HEADERS
            )
        )
        assert commissioned["status"] == "COMMISSIONED"
        assert str(commissioned["outage_start_at"]).startswith("2026-09-05T08:00:00")
        assert str(commissioned["outage_end_at"]).startswith("2026-09-05T12:00:00")

        refused = client.commission_auxiliary_system(
            system["id"], build_commission_payload(**SECOND_WINDOW), CONTRACTOR_HEADERS
        )
        validate_error(refused, "ERR_INVALID_STATE_TRANSITION", expected_status=409)

        after = read_auxiliary_system(client, system["id"])
        assert after["status"] == "COMMISSIONED"
        assert str(after["outage_start_at"]).startswith("2026-09-05T08:00:00")
        assert str(after["outage_end_at"]).startswith("2026-09-05T12:00:00")
        assert_flow(
            read_project(client, ctx["project_id"])["auxiliary_demand_gpm"],
            STANDPIPE_DEMAND_GPM,
        )


AB_R1 = "AB-2601-R1"
AB_R2 = "AB-2601-R2"


def _acceptance_test(client):
    """A permitted FP-2601 with one SYSTEM_FLOW_TEST opened against it."""
    ctx = build_permitted_stage(client)
    ctx["acceptance_test"] = open_acceptance_test(
        client, ctx["project_id"], test_type="SYSTEM_FLOW_TEST"
    )
    ctx["acceptance_test_id"] = ctx["acceptance_test"]["id"]
    return ctx


def _submit(client, ctx, ref):
    return validate_success(
        client.submit_as_built(
            ctx["acceptance_test_id"], build_as_built_payload(ref), CONTRACTOR_HEADERS
        )
    )


class TestAcceptanceDimensionsAdvanceIndependently:
    def test_12_the_thresholds_freeze_at_creation_and_the_first_lodgement_lands(
        self, client
    ):
        """A new test opens with `witness_status` `NOT_SCHEDULED`, `documentation_status`
        `PENDING`, `retest_count` 0, and `witness_reviewer_id`, `measured_flow_gpm`,
        `measured_residual_psi`, `witness_window_start`, `witness_window_end` and
        `as_built_document_ref` all null.

        Design: Corner/state_machines/acceptance_test_documentation_dimension_advances_while_the_witness_dimension_stands_still
        """
        ctx = _acceptance_test(client)
        opened = ctx["acceptance_test"]
        assert opened["witness_status"] == "NOT_SCHEDULED"
        assert opened["documentation_status"] == "PENDING"
        assert opened["retest_count"] == 0
        assert opened["witness_reviewer_id"] is None
        assert opened["as_built_document_ref"] is None
        assert_flow(opened["required_flow_gpm"], 2023.5)
        assert_pressure(opened["required_residual_psi"], HC1_REQUIRED_PSI)
        assert read_project(client, ctx["project_id"])["status"] == "ACCEPTANCE"

        lodged = _submit(client, ctx, AB_R1)
        assert lodged["documentation_status"] == "AS_BUILT_SUBMITTED"
        assert lodged["as_built_document_ref"] == AB_R1
        # Lodging never touches the witness dimension.
        assert lodged["witness_status"] == "NOT_SCHEDULED"
        assert lodged["witness_reviewer_id"] is None
        assert lodged["retest_count"] == 0

    def test_13_a_rejected_package_is_re_lodged_with_the_witness_dimension_untouched(
        self, client
    ):
        """A rejected package may be re-lodged: from `AS_BUILT_REJECTED` a fresh submission
        replaces `as_built_document_ref` and returns the dimension to `AS_BUILT_SUBMITTED`.

        Design: Corner/state_machines/acceptance_test_documentation_dimension_advances_while_the_witness_dimension_stands_still
        """
        ctx = _acceptance_test(client)
        _submit(client, ctx, AB_R1)

        rejected = validate_success(
            client.accept_as_built(
                ctx["acceptance_test_id"],
                build_as_built_disposition_payload(disposition="REJECTED"),
                make_ahj_reviewer_headers(ctx["reviewer_id"]),
            )
        )
        assert rejected["documentation_status"] == "AS_BUILT_REJECTED"
        assert rejected["witness_status"] == "NOT_SCHEDULED"
        assert rejected["as_built_document_ref"] == AB_R1

        relodged = _submit(client, ctx, AB_R2)
        assert relodged["documentation_status"] == "AS_BUILT_SUBMITTED"
        assert relodged["as_built_document_ref"] == AB_R2

        final = read_acceptance_test(client, ctx["acceptance_test_id"])
        assert final["documentation_status"] == "AS_BUILT_SUBMITTED"
        assert final["as_built_document_ref"] == AB_R2
        assert final["witness_status"] == "NOT_SCHEDULED"
        assert final["witness_reviewer_id"] is None
        assert final["retest_count"] == 0
        assert_flow(final["required_flow_gpm"], 2023.5)
        assert_pressure(final["required_residual_psi"], HC1_REQUIRED_PSI)
        assert read_project(client, ctx["project_id"])["status"] == "ACCEPTANCE"


HOOD = dict(
    system_type="COOKING",
    label="Kitchen hood line",
    appliance_count=4,
    water_wash_enabled=True,
    agent_type="WET_CHEMICAL",
)


class TestInterlockGuardOnCommissioning:
    def test_14_the_bare_window_is_refused_and_nothing_is_booked(self, client):
        """A system whose `interlock_required` is true may not be commissioned unless the
        request presents `interlock_verified` true; otherwise the commissioning is refused
        with `ERR_INTERLOCK_NOT_VERIFIED`.

        Design: Corner/state_machines/commissioning_an_interlocked_cooking_system_requires_the_verified_interlock
        """
        ctx = build_project_stage(client)
        hood = create_auxiliary_system(client, ctx["project_id"], ctx["lead_id"], **HOOD)
        assert hood["interlock_required"] is True
        assert hood["interlock_verified"] is False
        assert_flow(hood["demand_gpm"], 160.0)

        refused = client.commission_auxiliary_system(
            hood["id"], build_commission_payload(**FIRST_WINDOW), CONTRACTOR_HEADERS
        )
        validate_error(refused, "ERR_INTERLOCK_NOT_VERIFIED", expected_status=409)

        after = read_auxiliary_system(client, hood["id"])
        assert after["status"] == "PROPOSED"
        assert after["interlock_verified"] is False
        assert after["outage_start_at"] is None
        assert after["outage_end_at"] is None

    def test_15_the_same_window_with_the_verified_interlock_is_accepted(self, client):
        """A successful commissioning records `outage_start_at`, `outage_end_at` and
        `interlock_verified`, and moves the system either `PROPOSED → COMMISSIONED` or
        `DECOMMISSIONED_PENDING_RETEST → COMMISSIONED`, advancing the system's `version`.

        Design: Corner/state_machines/commissioning_an_interlocked_cooking_system_requires_the_verified_interlock
        """
        ctx = build_project_stage(client)
        hood = create_auxiliary_system(client, ctx["project_id"], ctx["lead_id"], **HOOD)
        validate_error(
            client.commission_auxiliary_system(
                hood["id"], build_commission_payload(**FIRST_WINDOW), CONTRACTOR_HEADERS
            ),
            "ERR_INTERLOCK_NOT_VERIFIED",
        )

        commissioned = validate_success(
            client.commission_auxiliary_system(
                hood["id"],
                build_commission_payload(interlock_verified=True, **FIRST_WINDOW),
                CONTRACTOR_HEADERS,
            ),
            expected_status=200,
        )
        assert commissioned["status"] == "COMMISSIONED"
        assert commissioned["interlock_verified"] is True
        assert str(commissioned["outage_start_at"]).startswith("2026-09-05T08:00:00")
        assert str(commissioned["outage_end_at"]).startswith("2026-09-05T12:00:00")
        assert commissioned["version"] > hood["version"]
        assert_flow(
            read_project(client, ctx["project_id"])["auxiliary_demand_gpm"], 160.0
        )


H22 = dict(
    hydrant_tag="H-22",
    static_psi=50.0,
    residual_psi=30.0,
    flow_gpm=4000.0,
    tested_at="2026-06-20T10:00:00.000Z",
)

ORDINARY_1_RESTATEMENT = dict(
    hazard_class="ORDINARY_1",
    commodity_class="CLASS_III",
    storage_height_ft=8.0,
    ceiling_height_ft=12.0,
    area_sqft=24000.0,
    ceiling_slope_pct=4.0,
    room_area_sqft=None,
    enclosure_rating_hours=None,
    room_has_unprotected_opening=None,
)


def _sealed_over_a_pumped_supply(client):
    """HC-1 sealed only because an ACCEPTABLE 2500 gpm pump answers a weak hydrant."""
    ctx = build_converged_stage(client)
    weak_test = create_flow_test(client, ctx["project_id"], ctx["lead_id"], **H22)
    evaluation = create_evaluation(
        client, ctx["project_id"], weak_test["id"], ctx["calculation_id"], ctx["lead_id"]
    )
    ctx["evaluation_id"] = evaluation["id"]
    ctx["pump"] = create_fire_pump(
        client,
        ctx["project_id"],
        evaluation["id"],
        evaluation["version"],
        ctx["lead_id"],
        model_tag="PUMP-A",
    )
    qc_pass(client, ctx["calculation_id"], ctx["second_id"])
    ctx["calculation"] = seal(client, ctx["calculation_id"], ctx["lead_id"])
    return ctx


def _reclassify(client, ctx):
    return validate_success(
        client.reclassify_hazard_area(
            ctx["hazard_area_id"],
            build_reclassify_payload(**ORDINARY_1_RESTATEMENT),
            make_design_engineer_headers(ctx["lead_id"]),
        ),
        expected_status=200,
    )


class TestReclassificationCascade:
    def test_16_the_restatement_reclassifies_the_area_and_reopens_the_sealed_design(
        self, client
    ):
        """Every hydraulic calculation whose `hazard_area_id` names this area and whose state
        is `CONVERGED`, `QC_PASSED` or `SEALED` moves to `REOPENED` with `stale_reason` set to
        `HAZARD_RECLASSIFIED`, and its `design_flow_gpm`, `hose_allowance_gpm`,
        `room_design_penalty_gpm` and `hazard_total_demand_gpm` are re-derived from the new
        density and area.

        Design: Corner/state_machines/reclassifying_the_hazard_area_supersedes_the_evaluation_and_its_pump_in_one_write
        """
        ctx = _sealed_over_a_pumped_supply(client)
        assert ctx["calculation"]["state"] == "SEALED"
        assert ctx["pump"]["sizing_verdict"] == "ACCEPTABLE"

        area = _reclassify(client, ctx)
        assert_classification(area, "ORDINARY_1", 0.150, 1500, 250.0)
        assert area["reclassification_count"] == 1

        calculation = read_calculation(client, ctx["calculation_id"])
        assert_reopened(calculation, "HAZARD_RECLASSIFIED")
        assert_seal_metadata_cleared(calculation)
        assert_calculation_demand_snapshot(calculation, 247.5, 250.0, 497.5)

    def test_17_the_chain_supersedes_the_evaluation_its_pump_and_empties_the_ledger(
        self, client
    ):
        """Every water supply evaluation whose `governing_hydraulic_calculation_id` names one
        of the reopened calculations and whose state is `EVALUATED` moves to `SUPERSEDED`, and
        every fire pump whose `water_supply_evaluation_id` names one of those superseded
        evaluations and whose state is `SIZED` moves to `SUPERSEDED` in turn.

        Design: Corner/state_machines/reclassifying_the_hazard_area_supersedes_the_evaluation_and_its_pump_in_one_write
        """
        ctx = _sealed_over_a_pumped_supply(client)
        before = read_project(client, ctx["project_id"])
        assert before["sealed_calculation_count"] == 1
        assert_demand_ledger(
            before,
            ctx["calculation_id"],
            1380.0,
            STANDPIPE_DEMAND_GPM,
            PROJECT_TOTAL_DEMAND_GPM,
        )

        _reclassify(client, ctx)
        assert read_evaluation(client, ctx["evaluation_id"])["state"] == "SUPERSEDED"
        assert read_fire_pump(client, ctx["pump"]["id"])["state"] == "SUPERSEDED"

        project = read_project(client, ctx["project_id"])
        assert project["sealed_calculation_count"] == 0
        assert_demand_ledger(
            project, None, 0.0, STANDPIPE_DEMAND_GPM, STANDPIPE_DEMAND_GPM
        )


WITNESS_WINDOW = ("2026-09-10T14:00:00Z", "2026-09-10T18:00:00Z")


def _permitted_over_a_pumped_supply(client):
    """The pumped-supply project carried all the way to a scheduled PUMP_FLOW_TEST."""
    ctx = _sealed_over_a_pumped_supply(client)
    coordinated = coordinate_sheet(
        client, ctx["project_id"], ctx["calculation_id"], ctx["lead_id"]
    )
    ctx["sheet_id"] = coordinated["sheet"]["id"]
    submittal = lodge_submittal(
        client, ctx["project_id"], [ctx["calculation_id"]], ctx["lead_id"]
    )
    ctx["submittal_id"] = submittal["id"]
    begin_review(client, ctx["submittal_id"], ctx["reviewer_id"])
    complete_review(client, ctx["submittal_id"], ctx["reviewer_id"])

    test_row = open_acceptance_test(
        client, ctx["project_id"], test_type="PUMP_FLOW_TEST"
    )
    ctx["acceptance_test_id"] = test_row["id"]
    assert_flow(test_row["required_flow_gpm"], 2023.5)
    assert_pressure(test_row["required_residual_psi"], HC1_REQUIRED_PSI)
    ctx["scheduled"] = schedule_witness(
        client, ctx["acceptance_test_id"], ctx["reviewer_id"], *WITNESS_WINDOW
    )
    return ctx


class TestCloseOutJoinsBothDimensions:
    def test_18_the_pump_flow_test_passes_and_promotes_the_sized_pump(self, client):
        """A pass moves the witness dimension `SCHEDULED → WITNESSED_PASS`, and when
        `test_type` is `PUMP_FLOW_TEST` every fire pump of the project in state `SIZED` moves
        to `ACCEPTED`.

        Design: Corner/state_machines/accepting_the_last_as_built_bubbles_the_project_to_closed_out_and_archives_the_seal
        """
        ctx = _permitted_over_a_pumped_supply(client)
        assert ctx["scheduled"]["witness_status"] == "SCHEDULED"

        witnessed = record_witness(
            client, ctx["acceptance_test_id"], ctx["reviewer_id"], 2100.0, 55.0
        )
        assert witnessed["witness_status"] == "WITNESSED_PASS"
        assert_flow(witnessed["measured_flow_gpm"], 2100.0)
        assert_pressure(witnessed["measured_residual_psi"], 55.00)
        assert read_fire_pump(client, ctx["pump"]["id"])["state"] == "ACCEPTED"

        project = read_project(client, ctx["project_id"])
        assert project["status"] == "ACCEPTANCE"
        assert_posture(project, "OPEN")

    def test_19_accepting_the_last_package_closes_the_job_and_archives_the_seal(
        self, client
    ):
        """When, after the write, every acceptance test of the project is `WITNESSED_PASS` on
        the witness dimension **and** `AS_BUILT_ACCEPTED` on the documentation dimension, the
        project moves `ACCEPTANCE → CLOSED_OUT`, every hydraulic calculation of the project
        still in `SEALED` moves to `ARCHIVED`, and the project's `design_posture` becomes
        `FROZEN` permanently.

        Design: Corner/state_machines/accepting_the_last_as_built_bubbles_the_project_to_closed_out_and_archives_the_seal
        """
        ctx = _permitted_over_a_pumped_supply(client)
        record_witness(client, ctx["acceptance_test_id"], ctx["reviewer_id"], 2100.0, 55.0)

        lodged = _submit(client, ctx, AB_R1)
        assert lodged["documentation_status"] == "AS_BUILT_SUBMITTED"

        accepted = validate_success(
            client.accept_as_built(
                ctx["acceptance_test_id"],
                build_as_built_disposition_payload(disposition="ACCEPTED"),
                make_ahj_reviewer_headers(ctx["reviewer_id"]),
            )
        )
        assert accepted["documentation_status"] == "AS_BUILT_ACCEPTED"
        assert accepted["witness_status"] == "WITNESSED_PASS"

        assert read_calculation(client, ctx["calculation_id"])["state"] == "ARCHIVED"
        project = read_project(client, ctx["project_id"])
        assert project["status"] == "CLOSED_OUT"
        assert_posture(project, "FROZEN")

    def test_20_the_closed_out_project_refuses_the_next_design_write(self, client):
        """A `FROZEN` posture refuses every design mutation on the project with
        `ERR_PROJECT_POSTURE_FROZEN` (HTTP 409). The refused set is exactly: ... adding an
        auxiliary system, commissioning one, withdrawing one ...

        Design: Corner/state_machines/accepting_the_last_as_built_bubbles_the_project_to_closed_out_and_archives_the_seal
        """
        ctx = _permitted_over_a_pumped_supply(client)
        record_witness(client, ctx["acceptance_test_id"], ctx["reviewer_id"], 2100.0, 55.0)
        _submit(client, ctx, AB_R1)
        validate_success(
            client.accept_as_built(
                ctx["acceptance_test_id"],
                build_as_built_disposition_payload(disposition="ACCEPTED"),
                make_ahj_reviewer_headers(ctx["reviewer_id"]),
            )
        )

        refused = client.create_auxiliary_system(
            build_auxiliary_system_payload(
                project_id=ctx["project_id"],
                system_type="STANDPIPE_CLASS_II",
                label="Late hose station",
                riser_count=1,
            ),
            make_design_engineer_headers(ctx["lead_id"]),
        )
        validate_error(refused, "ERR_PROJECT_POSTURE_FROZEN", expected_status=409)

        project = read_project(client, ctx["project_id"])
        assert_flow(project["auxiliary_demand_gpm"], STANDPIPE_DEMAND_GPM)
        assert project["status"] == "CLOSED_OUT"
