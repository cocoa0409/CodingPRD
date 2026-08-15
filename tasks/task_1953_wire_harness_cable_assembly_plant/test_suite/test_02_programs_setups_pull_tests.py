"""Machine programs, applicator setup windows, and crimp pull tests:
computed pull-force minimums, OCC and state gates on program edits, setup
window overlap geometry, first-article prerequisites, and pull-test records."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_applicator_setup,
    assert_crimp_pull_test,
    assert_machine_program,
    close_setup,
    get_success_data,
    make_applicator,
    make_certified_operator,
    make_machine_program,
    make_operator,
    make_released_drawing,
    open_setup,
    record_pull_test,
    setup_line_ready_for_first_article,
    setup_qualified_line,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS
from test_helpers import make_quality_inspector_headers

ENG = TEST_USERS["harness_engineer_headers"]
PROC = TEST_USERS["process_engineer_headers"]
QM = TEST_USERS["quality_manager_headers"]


class TestPullForceComputation:
    def test_min_pull_force_class3_closed_barrel_tier(self, api):
        """PRD §3.2: "The computation starts from a base force looked up by wire gauge: 15.0 newtons for gauges 26, 25, and 24; 30.0 newtons for gauges 23, 22, 21, and 20; 50.0 newtons for gauges 19, 18, 17, and 16; and 80.0 newtons for gauges 15, 14, 13, and 12."
        PRD §3.2: "The base is multiplied by a terminal derating — 1.0 for `OPEN_BARREL`, 0.9 for `CLOSED_BARREL` — and then by a workmanship-class multiplier taken from the program's linked drawing: 1.0 for `IPC_CLASS_1`, 1.0 for `IPC_CLASS_2`, and 1.1 for `IPC_CLASS_3`."
        PRD §3.2: "The product is rounded half-up to one decimal place."

        Design: Difficulty/combinatorial_formula/pull_force_minimum_tiered_branching
        """
        drawing, _ = make_released_drawing(
            api, tag="CF1A", workmanship_class="IPC_CLASS_3",
            bom=[{"find_number": "T1", "component_type": "TERMINAL", "mpn": "TERM-22",
                  "qty_per_harness": 1, "supply_type": "FACTORY_STOCK", "unit_cost_cents": 30}],
        )
        applicator = make_applicator(api, applicator_code="AP-CF1", compatible_terminal_mpn="TERM-22")
        program = make_machine_program(
            api, drawing_id=drawing["id"], applicator_id=applicator["id"],
            program_code="PG-CF1A", wire_gauge_awg=22, cut_length_mm=300.0,
            strip_length_mm=4.0, terminal_mpn="TERM-22", terminal_type="CLOSED_BARREL",
        )
        assert_machine_program(program)
        # AWG 22 -> base 30.0; CLOSED_BARREL derating 0.9; IPC_CLASS_3 multiplier 1.1
        # round_half_up(30.0 * 0.9 * 1.1, 1) = 29.7 N.
        assert program["min_pull_force_n"] == pytest.approx(29.7, abs=0.001), (
            f"class-3/AWG-22/CLOSED_BARREL minimum must be 29.7 N: {program}"
        )
        assert program["status"] == "DRAFT", f"program is born DRAFT: {program}"

    def test_min_pull_force_class2_open_barrel_tier(self, api):
        """PRD §3.2: "The computation starts from a base force looked up by wire gauge: 15.0 newtons for gauges 26, 25, and 24; 30.0 newtons for gauges 23, 22, 21, and 20; 50.0 newtons for gauges 19, 18, 17, and 16; and 80.0 newtons for gauges 15, 14, 13, and 12."
        PRD §3.2: "The base is multiplied by a terminal derating — 1.0 for `OPEN_BARREL`, 0.9 for `CLOSED_BARREL` — and then by a workmanship-class multiplier taken from the program's linked drawing: 1.0 for `IPC_CLASS_1`, 1.0 for `IPC_CLASS_2`, and 1.1 for `IPC_CLASS_3`."
        PRD §3.2: "A program is born in `DRAFT`. Creation also computes the program's minimum crimp pull force, `min_pull_force_n`."

        Design: Difficulty/combinatorial_formula/pull_force_minimum_tiered_branching
        """
        drawing, _ = make_released_drawing(
            api, tag="CF1B", workmanship_class="IPC_CLASS_2",
            bom=[{"find_number": "T1", "component_type": "TERMINAL", "mpn": "TERM-18",
                  "qty_per_harness": 1, "supply_type": "FACTORY_STOCK", "unit_cost_cents": 30}],
        )
        applicator = make_applicator(api, applicator_code="AP-CF1B", compatible_terminal_mpn="TERM-18")
        program = make_machine_program(
            api, drawing_id=drawing["id"], applicator_id=applicator["id"],
            program_code="PG-CF1B", wire_gauge_awg=18, cut_length_mm=300.0,
            strip_length_mm=4.0, terminal_mpn="TERM-18", terminal_type="OPEN_BARREL",
        )
        # AWG 18 -> base 50.0; OPEN_BARREL derating 1.0; IPC_CLASS_2 multiplier 1.0 -> 50.0 N.
        assert program["min_pull_force_n"] == pytest.approx(50.0, abs=0.001), (
            f"class-2/AWG-18/OPEN_BARREL minimum must be 50.0 N: {program}"
        )
        assert program["status"] == "DRAFT", f"program is born DRAFT: {program}"

    def test_program_create_ignores_computed_field_input(self, api):
        """PRD §2.6: "Undeclared or read-only payload fields are ignored and are not an error."
        PRD §3.2: "Creation also computes the program's minimum crimp pull force, `min_pull_force_n`."

        Design: Corner/entities/c_program_create_computed_field_input_ignored
        """
        drawing, _ = make_released_drawing(
            api, tag="E6", workmanship_class="IPC_CLASS_3",
            bom=[{"find_number": "T1", "component_type": "TERMINAL", "mpn": "TERM-22",
                  "qty_per_harness": 1, "supply_type": "FACTORY_STOCK", "unit_cost_cents": 30}],
        )
        applicator = make_applicator(api, applicator_code="AP-E6", compatible_terminal_mpn="TERM-22")
        resp = api.create_machine_program(
            {
                "program_code": "PG-E6",
                "drawing_id": drawing["id"],
                "applicator_id": applicator["id"],
                "wire_gauge_awg": 22,
                "wire_type": "TXL",
                "cut_length_mm": 300.0,
                "strip_length_mm": 4.0,
                "terminal_mpn": "TERM-22",
                "terminal_type": "CLOSED_BARREL",
                "min_pull_force_n": 999.0,
            },
            PROC,
        )
        data = validate_success(resp, 201)
        assert data["min_pull_force_n"] == pytest.approx(29.7, abs=0.001), (
            f"client-supplied min_pull_force_n must be ignored; computed value is 29.7 N: {data}"
        )

    def test_min_pull_force_recomputed_on_patch(self, api):
        """PRD §3.2: "Every accepted edit recomputes `min_pull_force_n` from the same formula and increments the program's `version`."
        PRD §2.7: "A `PATCH /plant/machine-programs/{id}` request must likewise carry `expected_machine_program_version` matching the target program's current `version`."

        Design: Corner/calculations/c_min_pull_force_recomputed_on_patch
        """
        drawing, _ = make_released_drawing(
            api, tag="C6", workmanship_class="IPC_CLASS_3",
            bom=[{"find_number": "T1", "component_type": "TERMINAL", "mpn": "TERM-22",
                  "qty_per_harness": 1, "supply_type": "FACTORY_STOCK", "unit_cost_cents": 30}],
        )
        applicator = make_applicator(api, applicator_code="AP-C6", compatible_terminal_mpn="TERM-22")
        program = make_machine_program(
            api, drawing_id=drawing["id"], applicator_id=applicator["id"],
            program_code="PG-C6", wire_gauge_awg=22, cut_length_mm=300.0,
            strip_length_mm=4.0, terminal_mpn="TERM-22", terminal_type="CLOSED_BARREL",
        )
        assert program["min_pull_force_n"] == pytest.approx(29.7, abs=0.001)
        created_version = program["version"]
        patched = validate_success(
            api.patch_machine_program(
                program["id"],
                {"expected_machine_program_version": created_version, "wire_gauge_awg": 18},
                PROC,
            ),
            200,
        )
        # AWG 18 -> base 50.0; CLOSED 0.9; IPC_CLASS_3 1.1 -> round(49.5, 1) = 49.5 N.
        assert patched["min_pull_force_n"] == pytest.approx(49.5, abs=0.001), (
            f"recomputed minimum after AWG 22 -> 18 must be 49.5 N: {patched}"
        )
        assert patched["version"] == created_version + 1, (
            f"an accepted edit increments the program version by one: {patched}"
        )


class TestPullForceBoundaryAndRecords:
    def test_pull_force_at_exact_minimum_records_pass(self, api):
        """PRD §3.4: "The record's `result` is `PASS` when the measured force is at least the snapshot minimum, and `FAIL` otherwise."
        PRD §3.4: "At record time the program's current `min_pull_force_n` is copied onto the record as `min_pull_force_n_snapshot`, so later program edits never rewrite history."

        Design: Difficulty/boundary_precision_check/pull_force_equal_to_minimum_passes
        """
        line = setup_line_ready_for_first_article(
            api, tag="BP1", workmanship_class="IPC_CLASS_3",
            wire_gauge_awg=22, terminal_type="CLOSED_BARREL", terminal_mpn="TERM-22",
        )
        assert line["program"]["min_pull_force_n"] == pytest.approx(29.7, abs=0.001)
        record = record_pull_test(
            api, line["applicator"]["id"], line["program"]["id"], line["inspector"]["id"],
            sample_kind="FIRST_ARTICLE", measured_force_n=29.7,
        )
        assert_crimp_pull_test(record)
        assert record["result"] == "PASS", (
            f"29.7 N is at least the 29.7 N minimum — inclusive boundary must PASS: {record}"
        )
        assert record["min_pull_force_n_snapshot"] == pytest.approx(29.7, abs=0.001), (
            f"snapshot copies the program minimum at record time: {record}"
        )

    def test_first_article_pass_at_minimum_qualifies_applicator(self, api):
        """PRD §3.4: "When a first-article test passes, the applicator moves `AVAILABLE → QUALIFIED` with `qualified_at` stamped from the clock, and the program qualifies with it: `DRAFT → QUALIFIED` for a first qualification, or `HELD → QUALIFIED` for a requalification after a quarantine — requalification additionally requiring that at least one `CLOSED` setup for the pair was created after the quarantine occurred."

        Design: Difficulty/boundary_precision_check/pull_force_equal_to_minimum_passes
        """
        line = setup_line_ready_for_first_article(
            api, tag="BP1Q", workmanship_class="IPC_CLASS_3",
            wire_gauge_awg=22, terminal_type="CLOSED_BARREL", terminal_mpn="TERM-22",
        )
        record_pull_test(
            api, line["applicator"]["id"], line["program"]["id"], line["inspector"]["id"],
            sample_kind="FIRST_ARTICLE", measured_force_n=29.7,
        )
        applicator = get_success_data(api.get_applicator(line["applicator"]["id"], PROC))
        program = get_success_data(api.get_machine_program(line["program"]["id"], PROC))
        assert applicator["status"] == "QUALIFIED", (
            f"boundary-passing first article qualifies the applicator: {applicator}"
        )
        assert program["status"] == "QUALIFIED", (
            f"boundary-passing first article qualifies the DRAFT program: {program}"
        )

    def test_pull_force_just_below_minimum_fails(self, api):
        """PRD §3.4: "The record's `result` is `PASS` when the measured force is at least the snapshot minimum, and `FAIL` otherwise."
        PRD §3.4: "When a first-article test passes, the applicator moves `AVAILABLE → QUALIFIED` with `qualified_at` stamped from the clock, and the program qualifies with it: `DRAFT → QUALIFIED` for a first qualification, or `HELD → QUALIFIED` for a requalification after a quarantine — requalification additionally requiring that at least one `CLOSED` setup for the pair was created after the quarantine occurred."

        Design: Corner/calculations/c_pull_force_just_below_min_fails
        """
        line = setup_line_ready_for_first_article(
            api, tag="C7", workmanship_class="IPC_CLASS_3",
            wire_gauge_awg=22, terminal_type="CLOSED_BARREL", terminal_mpn="TERM-22",
        )
        record = record_pull_test(
            api, line["applicator"]["id"], line["program"]["id"], line["inspector"]["id"],
            sample_kind="FIRST_ARTICLE", measured_force_n=29.6,
        )
        assert record["result"] == "FAIL", f"29.6 N is below the 29.7 N minimum: {record}"
        applicator = get_success_data(api.get_applicator(line["applicator"]["id"], PROC))
        program = get_success_data(api.get_machine_program(line["program"]["id"], PROC))
        assert applicator["status"] == "AVAILABLE", f"no qualification side effects on FAIL: {applicator}"
        assert program["status"] == "DRAFT", f"program stays DRAFT on a failed first article: {program}"

    def test_pull_test_record_carries_no_version_or_updated_at(self, api):
        """PRD §2.4: "Two resources are append-only evidence records and break this pattern: a crimp pull-test record and an electrical test record each carry only `id` and `created_at` from the common set."
        PRD §2.4: "Both `updated_at` and `version` are absent on these two resources, because a recorded test result is never modified after creation."
        PRD §2.5: "At server startup, before any clock-setting call, the logical clock reads exactly `2026-08-01T00:00:00Z`."
        PRD §3.4: "The recording operator's `operator_id` is stamped from `X-User-ID`, and `tested_at` is stamped from the logical clock."

        Design: Corner/entities/c_pull_test_record_immutable_common_fields_absent
        """
        line = setup_qualified_line(api, tag="E7", first_article_force=35.0)
        data, _meta = validate_paginated(
            api.list_crimp_pull_tests(
                make_quality_inspector_headers(line["inspector"]["id"]),
                params={"program_id": line["program"]["id"]},
            )
        )
        assert len(data) == 1, f"exactly one pull test recorded by the fixture: {data}"
        record = validate_success(api.get_crimp_pull_test(data[0]["id"], PROC), 200)
        assert_crimp_pull_test(record)
        assert record["result"] == "PASS", f"35.0 N against the 30.0 N minimum passes: {record}"
        assert record["tested_at"].startswith("2026-08-01T00:00:00"), (
            f"tested_at reads the logical clock startup default: {record['tested_at']}"
        )
        assert record["operator_id"] == line["inspector"]["id"], (
            f"operator_id is stamped from X-User-ID: {record}"
        )


class TestSetupWindows:
    def test_second_setup_rejected_while_one_open(self, api):
        """PRD §3.2: "Two guards protect the schedule: an applicator with another `OPEN` setup rejects the new window with `ERR_APPLICATOR_SETUP_ALREADY_OPEN`, and a planned window that overlaps any existing setup window on the same applicator rejects with `ERR_APPLICATOR_SETUP_OVERLAP`."
        PRD §3.2: "opening the window moves it to `IN_SETUP`, points its `current_program_id` at the setup's program, and increments its `version`."

        Design: Corner/validations/c_setup_already_open_rejected
        """
        drawing, _components = make_released_drawing(api, tag="V13")
        applicator = make_applicator(api, applicator_code="AP-V13")
        program = make_machine_program(
            api, drawing_id=drawing["id"], applicator_id=applicator["id"], program_code="PG-V13"
        )
        operator = make_operator(api, name="SE V13", badge="B-SE-V13")
        open_setup(api, applicator["id"], program["id"], operator["id"],
                   start="2026-08-01T08:00:00Z", end="2026-08-01T09:00:00Z")
        # Disjoint window on the next day: the overlap guard cannot fire, only the OPEN-setup guard.
        resp = api.create_applicator_setup(
            {
                "applicator_id": applicator["id"],
                "program_id": program["id"],
                "setup_operator_id": operator["id"],
                "planned_start_at": "2026-08-02T08:00:00Z",
                "planned_end_at": "2026-08-02T09:00:00Z",
            },
            PROC,
        )
        validate_error(resp, ApiErrorId.ERR_APPLICATOR_SETUP_ALREADY_OPEN)
        applicator = get_success_data(api.get_applicator(applicator["id"], PROC))
        assert applicator["status"] == "IN_SETUP", (
            f"the rejected window changes nothing; applicator remains IN_SETUP: {applicator}"
        )

    def test_overlapping_setup_window_rejected(self, api):
        """PRD §3.2: "Overlap uses half-open interval semantics — the new window overlaps an existing one when the new start falls before the existing end and the existing start falls before the new end; windows that merely touch at an endpoint are allowed."
        PRD §3.2: "a planned window that overlaps any existing setup window on the same applicator rejects with `ERR_APPLICATOR_SETUP_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/applicator_setup_half_open_adjacency
        """
        drawing, _components = make_released_drawing(api, tag="TO1")
        applicator = make_applicator(api, applicator_code="AP-TO1")
        program = make_machine_program(
            api, drawing_id=drawing["id"], applicator_id=applicator["id"], program_code="PG-TO1"
        )
        operator = make_operator(api, name="SE TO1", badge="B-SE-TO1")
        setup1 = open_setup(api, applicator["id"], program["id"], operator["id"],
                            start="2026-08-01T08:00:00Z", end="2026-08-01T10:00:00Z")
        close_setup(api, setup1["id"], closed_at="2026-08-01T10:00:00Z")
        # Interior overlap with the existing [08:00, 10:00) window: 09:30 < 10:00.
        resp = api.create_applicator_setup(
            {
                "applicator_id": applicator["id"],
                "program_id": program["id"],
                "setup_operator_id": operator["id"],
                "planned_start_at": "2026-08-01T09:30:00Z",
                "planned_end_at": "2026-08-01T10:30:00Z",
            },
            PROC,
        )
        validate_error(resp, ApiErrorId.ERR_APPLICATOR_SETUP_OVERLAP)

    def test_touching_setup_window_allowed(self, api):
        """PRD §3.2: "Overlap uses half-open interval semantics — the new window overlaps an existing one when the new start falls before the existing end and the existing start falls before the new end; windows that merely touch at an endpoint are allowed."
        PRD §3.2: "opening the window moves it to `IN_SETUP`, points its `current_program_id` at the setup's program, and increments its `version`."

        Design: Difficulty/resource_temporal_overlap/applicator_setup_half_open_adjacency
        """
        drawing, _components = make_released_drawing(api, tag="TO1B")
        applicator = make_applicator(api, applicator_code="AP-TO1B")
        program = make_machine_program(
            api, drawing_id=drawing["id"], applicator_id=applicator["id"], program_code="PG-TO1B"
        )
        operator = make_operator(api, name="SE TO1B", badge="B-SE-TO1B")
        setup1 = open_setup(api, applicator["id"], program["id"], operator["id"],
                            start="2026-08-01T08:00:00Z", end="2026-08-01T10:00:00Z")
        close_setup(api, setup1["id"], closed_at="2026-08-01T10:00:00Z")
        # New start equals the existing end (10:00 == 10:00): touching endpoints are allowed.
        resp = api.create_applicator_setup(
            {
                "applicator_id": applicator["id"],
                "program_id": program["id"],
                "setup_operator_id": operator["id"],
                "planned_start_at": "2026-08-01T10:00:00Z",
                "planned_end_at": "2026-08-01T12:00:00Z",
            },
            PROC,
        )
        data = validate_success(resp, 201)
        assert_applicator_setup(data)
        assert data["status"] == "OPEN", f"adjacent half-open window is accepted OPEN: {data}"
        applicator = get_success_data(api.get_applicator(applicator["id"], PROC))
        assert applicator["status"] == "IN_SETUP", (
            f"the accepted window moves the applicator to IN_SETUP: {applicator}"
        )


class TestPullTestGates:
    def test_pull_test_gate_errors(self, api):
        """PRD §3.4: "Recording a `FIRST_ARTICLE` sample requires the applicator to be `AVAILABLE` with its `current_program_id` equal to the tested program, at least one `CLOSED` setup to exist for that applicator-and-program pair, and the program's status to be `DRAFT` or `HELD`; any shortfall is rejected with `ERR_FIRST_ARTICLE_PREREQUISITE`."
        PRD §3.4: "Recording a `LOT_SAMPLE` requires the applicator to be `QUALIFIED` (otherwise `ERR_APPLICATOR_NOT_QUALIFIED`) and the tested `program_id` to equal the applicator's `current_program_id` (otherwise `ERR_APPLICATOR_PROGRAM_MISMATCH`)."

        Design: Corner/state_machines/c_pull_test_gate_errors
        """
        drawing, _components = make_released_drawing(api, tag="S10")
        applicator = make_applicator(api, applicator_code="AP-S10")
        program = make_machine_program(
            api, drawing_id=drawing["id"], applicator_id=applicator["id"], program_code="PG-S10A"
        )
        inspector, _cert = make_certified_operator(
            api, workmanship_class="IPC_CLASS_2", name="QI S10", badge="B-QI-S10"
        )
        setup = open_setup(api, applicator["id"], program["id"], inspector["id"])

        # Gate 1: FIRST_ARTICLE while the setup is still OPEN (applicator IN_SETUP).
        resp = api.create_crimp_pull_test(
            {
                "applicator_id": applicator["id"],
                "program_id": program["id"],
                "sample_kind": "FIRST_ARTICLE",
                "measured_force_n": 35.0,
            },
            make_quality_inspector_headers(inspector["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FIRST_ARTICLE_PREREQUISITE)

        close_setup(api, setup["id"])

        # Gate 2: LOT_SAMPLE on an applicator that was never QUALIFIED.
        resp = api.create_crimp_pull_test(
            {
                "applicator_id": applicator["id"],
                "program_id": program["id"],
                "sample_kind": "LOT_SAMPLE",
                "measured_force_n": 35.0,
            },
            make_quality_inspector_headers(inspector["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_APPLICATOR_NOT_QUALIFIED)

        # Qualify the pair, then gate 3: LOT_SAMPLE referencing a program that is
        # not the applicator's current program.
        record_pull_test(
            api, applicator["id"], program["id"], inspector["id"],
            sample_kind="FIRST_ARTICLE", measured_force_n=35.0,
        )
        other = make_machine_program(
            api, drawing_id=drawing["id"], applicator_id=applicator["id"], program_code="PG-S10B"
        )
        resp = api.create_crimp_pull_test(
            {
                "applicator_id": applicator["id"],
                "program_id": other["id"],
                "sample_kind": "LOT_SAMPLE",
                "measured_force_n": 35.0,
            },
            make_quality_inspector_headers(inspector["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_APPLICATOR_PROGRAM_MISMATCH)


class TestProgramEditGates:
    def test_program_patch_not_draft_rejected(self, api):
        """PRD §3.2: "Editing a program that is not `DRAFT` is rejected with `ERR_PROGRAM_NOT_DRAFT`."
        PRD §2.6: "5. **Stale-version checks** — the optimistic-concurrency rules of §2.7; otherwise the rule's 412 error."

        Design: Corner/validations/c_program_patch_not_draft_rejected
        """
        line = setup_qualified_line(api, tag="V15", first_article_force=35.0)
        program = get_success_data(api.get_machine_program(line["program"]["id"], PROC))
        assert program["status"] == "QUALIFIED"
        resp = api.patch_machine_program(
            program["id"],
            {
                "expected_machine_program_version": program["version"],
                "cut_length_mm": 600.0,
            },
            PROC,
        )
        # The OCC version is current, so the stale-version check passes and the
        # state gate fires instead.
        validate_error(resp, ApiErrorId.ERR_PROGRAM_NOT_DRAFT)
        reread = get_success_data(api.get_machine_program(program["id"], PROC))
        assert reread["cut_length_mm"] == pytest.approx(500.0), (
            f"rejected edit must not apply: {reread}"
        )

    def test_program_patch_stale_version_rejected(self, api):
        """PRD §2.7: "A `PATCH /plant/machine-programs/{id}` request must likewise carry `expected_machine_program_version` matching the target program's current `version`. Editing cut, strip, or tooling parameters while the program is `DRAFT` is legitimate at any time; a mismatch is rejected with `ERR_STALE_PROGRAM_VERSION` (HTTP 412)."
        PRD §2.4: "The `version` field is a system-managed integer that increments by one on every mutation of the resource, including mutations caused by automatic reconciliations and cascades, and it underpins the optimistic concurrency rules of §2.7."

        Design: Corner/cross_cutting_complexity_layers/c_program_patch_stale_version_rejected
        """
        drawing, _components = make_released_drawing(api, tag="L2")
        applicator = make_applicator(api, applicator_code="AP-L2")
        program = make_machine_program(
            api, drawing_id=drawing["id"], applicator_id=applicator["id"], program_code="PG-L2"
        )
        observed_version = program["version"]
        first = validate_success(
            api.patch_machine_program(
                program["id"],
                {"expected_machine_program_version": observed_version, "cut_length_mm": 600.0},
                PROC,
            ),
            200,
        )
        assert first["version"] == observed_version + 1, (
            f"the accepted edit increments the version by one: {first}"
        )
        stale = api.patch_machine_program(
            program["id"],
            {"expected_machine_program_version": observed_version, "strip_length_mm": 6.0},
            PROC,
        )
        validate_error(stale, ApiErrorId.ERR_STALE_PROGRAM_VERSION)
        reread = get_success_data(api.get_machine_program(program["id"], PROC))
        assert reread["strip_length_mm"] == pytest.approx(5.0), (
            f"the stale edit must not apply: {reread}"
        )
