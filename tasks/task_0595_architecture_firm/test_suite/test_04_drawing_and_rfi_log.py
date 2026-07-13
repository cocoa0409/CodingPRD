"""The drawing log, the RFI log, the open-item gate and the logical clock."""
from test_helpers import (
    ApiErrorId, validate_success, validate_error, validate_paginated,
    assert_drawing, assert_rfi, assert_phase, assert_instant_equals, CLOCK_DEFAULT_UTC,
    state_payload, create_drawing_payload, create_rfi_payload, create_phase_payload,
    make_staff_architect_headers,
    setup_project, setup_executed_project,
    activate_phase, create_drawing, create_rfi, answer_rfi,
    read_phase, read_project, read_rfi, PRINCIPAL,
)


class TestOpenItemGateOnPhaseCompletion:

    def test_completion_is_refused_while_one_rfi_is_still_open(self, api):
        """PRD §3.3: "Driving a phase from `ACTIVE` to `COMPLETED` is the milestone event. It is
        barred outright while the project's `ca_posture` is `DEFICIENT` — that is, while
        `open_rfi_count` is greater than zero — with `ERR_OPEN_RFIS_BLOCK_COMPLETION` (§3.4
        explains why)."
        PRD §3.4: "From that count comes the project's construction-administration posture:
        `ca_posture` is `DEFICIENT` whenever `open_rfi_count` is greater than 0, and `CLEAR` only
        when the count is exactly 0."

        Design: Difficulty/boundary_precision_check/phase_completion_requires_exactly_zero_open_rfis
        """
        bundle = setup_executed_project(project_number="EMP-001", name="Empty Set Estate",
                                        with_architect=False)
        activate_phase(bundle, "SD")
        create_rfi(bundle, subject="Confirm curtain wall mullion spacing")

        project = read_project(bundle)
        assert project["open_rfi_count"] == 1
        assert project["ca_posture"] == "DEFICIENT"

        response = api.set_phase_state(
            bundle["phase_ids"]["SD"], state_payload("COMPLETED"), bundle["pm_headers"]
        )
        validate_error(response, ApiErrorId.ERR_OPEN_RFIS_BLOCK_COMPLETION.value)

        assert read_phase(bundle, "SD")["status"] == "ACTIVE"

    def test_completion_succeeds_the_instant_the_open_set_becomes_empty(self, api):
        """PRD §3.4: "The answer is stored, `answered_at` is stamped from the logical clock, and
        the RFI moves to `ANSWERED` — at which point `open_rfi_count` drops by one and `ca_posture`
        is re-derived (returning to `CLEAR` only once the count reaches 0)."
        PRD §3.3: "When it succeeds, the phase's `percent_complete` is forced to 100 and its
        `earned_cents` consequently becomes its full `fee_allocation_cents`."

        Design: Difficulty/boundary_precision_check/phase_completion_requires_exactly_zero_open_rfis
        """
        bundle = setup_executed_project(project_number="EMP-002", name="Empty Set Estate II",
                                        with_architect=False)
        activate_phase(bundle, "SD")
        rfi = create_rfi(bundle, subject="Confirm curtain wall mullion spacing")

        validate_error(
            api.set_phase_state(
                bundle["phase_ids"]["SD"], state_payload("COMPLETED"), bundle["pm_headers"]
            ),
            ApiErrorId.ERR_OPEN_RFIS_BLOCK_COMPLETION.value,
        )

        answer_rfi(rfi["id"], bundle, answer_text="Mullions at 1500 mm on centre.")
        project = read_project(bundle)
        assert project["open_rfi_count"] == 0
        assert project["ca_posture"] == "CLEAR"

        completed = validate_success(
            api.set_phase_state(
                bundle["phase_ids"]["SD"], state_payload("COMPLETED"), bundle["pm_headers"]
            )
        )
        assert_phase(completed)
        assert completed["status"] == "COMPLETED"
        assert completed["percent_complete"] == 100
        assert completed["fee_allocation_cents"] == 2_000_000
        assert completed["earned_cents"] == 2_000_000


class TestDrawingLog:

    def test_reissue_after_supersession_increments_the_revision(self, api):
        """PRD §3.3: "A superseded sheet may be re-issued — driven back from `SUPERSEDED` to
        `ISSUED` — and each such re-issue increments the sheet's `revision` by exactly 1."
        PRD §3.3: "That loop between `ISSUED` and `SUPERSEDED` may run as many times as the
        project needs; the first release to `ISSUED` does *not* bump `revision`, only re-issues
        after supersession do."

        Design: Corner/state_machines/drawing_reissue_after_supersede_increments_revision
        """
        bundle = setup_executed_project(project_number="DWG-001", name="Drawing Depot",
                                        with_architect=False)
        activate_phase(bundle, "SD")
        drawing = create_drawing(bundle, "SD", sheet_number="A-101", title="Ground floor plan")
        assert drawing["status"] == "IN_PROGRESS"
        assert drawing["revision"] == 0

        pm = bundle["pm_headers"]
        first_issue = validate_success(
            api.set_drawing_state(drawing["id"], state_payload("ISSUED"), pm)
        )
        assert first_issue["revision"] == 0, "the first release must not bump revision"

        superseded = validate_success(
            api.set_drawing_state(drawing["id"], state_payload("SUPERSEDED"), pm)
        )
        assert superseded["status"] == "SUPERSEDED"
        assert superseded["revision"] == 0

        reissued = validate_success(
            api.set_drawing_state(drawing["id"], state_payload("ISSUED"), pm)
        )
        assert_drawing(reissued)
        assert reissued["status"] == "ISSUED"
        assert reissued["revision"] == 1

    def test_duplicate_sheet_number_within_a_phase_is_rejected(self, api):
        """PRD §3.3: "A sheet enters the drawing log against a phase, carrying a `sheet_number`
        that must be unique within that phase — a collision is rejected with
        `ERR_DUPLICATE_SHEET_NUMBER` — and a `title`."

        Design: Corner/validations/duplicate_sheet_number_within_phase_is_rejected
        """
        bundle = setup_project(project_number="SHT-001", name="Sheet Shed",
                               labor_budget_cents=500_000, with_architect=False)
        pm = bundle["pm_headers"]
        sd = validate_success(
            api.create_phase(create_phase_payload(bundle["project_id"], "SD", 2500), pm), 201
        )
        dd = validate_success(
            api.create_phase(create_phase_payload(bundle["project_id"], "DD", 2500), pm), 201
        )
        validate_success(
            api.create_drawing(create_drawing_payload(sd["id"], sheet_number="A-101",
                                                      title="Plan"), pm),
            201,
        )

        response = api.create_drawing(
            create_drawing_payload(sd["id"], sheet_number="A-101", title="Plan copy"), pm
        )
        validate_error(response, ApiErrorId.ERR_DUPLICATE_SHEET_NUMBER.value)

        rows, _ = validate_paginated(api.list_phase_drawings(sd["id"], pm))
        assert len(rows) == 1

        # Uniqueness is scoped to the phase: A-101 in DD is a different sheet.
        sibling = validate_success(
            api.create_drawing(
                create_drawing_payload(dd["id"], sheet_number="A-101", title="Plan in DD"), pm
            ),
            201,
        )
        dd_rows, _ = validate_paginated(api.list_phase_drawings(dd["id"], pm))
        assert len(dd_rows) == 1 and dd_rows[0]["id"] == sibling["id"]


class TestRfiLog:

    def test_rfi_citing_a_drawing_that_is_not_issued_is_rejected(self, api):
        """PRD §3.4: "When a drawing is cited, that drawing must be in status `ISSUED`; citing an
        in-progress or superseded sheet is rejected with `ERR_DRAWING_NOT_ISSUED`."
        PRD §3.4: "Each RFI receives an `rfi_number`, sequential per project starting at 1 and
        assigned in ascending `created_at` order of that project's RFIs. It opens in status `OPEN`
        with `origin` of `CONTRACTOR`, `clarification_rounds` at 0, `answer_text` null,
        `answered_at` null and `field_report_id` null."

        Design: Corner/validations/rfi_citing_a_drawing_that_is_not_issued_is_rejected
        """
        bundle = setup_executed_project(
            project_number="ISS-001", name="Issue Island",
            weights=(2500, 2500, 2500, 2500), with_architect=False,
        )
        activate_phase(bundle, "SD")
        drawing = create_drawing(bundle, "SD", sheet_number="A-101", title="Plan")
        pm = bundle["pm_headers"]

        response = api.create_rfi(
            create_rfi_payload(bundle["project_id"], subject="Dimension conflict on A-101",
                               drawing_id=drawing["id"]),
            pm,
        )
        validate_error(response, ApiErrorId.ERR_DRAWING_NOT_ISSUED.value)

        project = read_project(bundle)
        assert project["open_rfi_count"] == 0
        assert project["ca_posture"] == "CLEAR"

        validate_success(api.set_drawing_state(drawing["id"], state_payload("ISSUED"), pm))
        rfi = validate_success(
            api.create_rfi(
                create_rfi_payload(bundle["project_id"], subject="Dimension conflict on A-101",
                                   drawing_id=drawing["id"]),
                pm,
            ),
            201,
        )
        assert_rfi(rfi)
        assert rfi["rfi_number"] == 1
        assert rfi["origin"] == "CONTRACTOR"

        project = read_project(bundle)
        assert project["open_rfi_count"] == 1
        assert project["ca_posture"] == "DEFICIENT"

    def test_third_return_for_clarification_hits_the_two_round_cap(self, api):
        """PRD §3.4: "That loop is bounded: an RFI may be returned for clarification at most
        **twice**, and a third attempt — one made when `clarification_rounds` already equals 2 — is
        rejected with `ERR_MAX_CLARIFICATION_ROUNDS`."
        PRD §3.4: "Crucially, an RFI sitting in `RETURNED_FOR_CLARIFICATION` still counts as open;
        the round trip does not move `open_rfi_count` at all."

        Design: Corner/state_machines/rfi_third_return_for_clarification_hits_max_rounds_cap
        """
        bundle = setup_project(project_number="RND-002", name="Rounds Retreat",
                               labor_budget_cents=500_000)
        pm = bundle["pm_headers"]
        arch = make_staff_architect_headers(bundle["arch_id"])
        rfi = create_rfi(bundle, subject="Clarify slab edge detail")

        for _ in range(2):
            returned = validate_success(
                api.set_rfi_state(
                    rfi["id"], state_payload("RETURNED_FOR_CLARIFICATION"), pm
                )
            )
            assert returned["status"] == "RETURNED_FOR_CLARIFICATION"
            assert read_project(bundle)["open_rfi_count"] == 1, (
                "RETURNED_FOR_CLARIFICATION still counts as open"
            )
            validate_success(api.set_rfi_state(rfi["id"], state_payload("OPEN"), arch))

        assert read_rfi(bundle, rfi["id"])["clarification_rounds"] == 2

        response = api.set_rfi_state(
            rfi["id"], state_payload("RETURNED_FOR_CLARIFICATION"), pm
        )
        validate_error(response, ApiErrorId.ERR_MAX_CLARIFICATION_ROUNDS.value)

        final = read_rfi(bundle, rfi["id"])
        assert final["status"] == "OPEN"
        assert final["clarification_rounds"] == 2
        assert read_project(bundle)["open_rfi_count"] == 1

    def test_close_after_answer_leaves_the_count_alone_while_void_from_open_decrements_it(self, api):
        """PRD §3.4: "An `ANSWERED` RFI may finally be moved to `CLOSED`, which is terminal and
        has no further effect on the count."
        PRD §3.4: "Alternatively, an `OPEN` RFI may be voided outright, moving it to the terminal
        `VOID` state and likewise decrementing `open_rfi_count` and re-deriving `ca_posture`."
        PRD §3.4: "Each RFI receives an `rfi_number`, sequential per project starting at 1 and
        assigned in ascending `created_at` order of that project's RFIs."

        Design: Corner/endpoints/rfi_close_after_answer_and_void_from_open_both_reachable
        """
        bundle = setup_project(project_number="CLS-001", name="Close Court",
                               labor_budget_cents=500_000, with_architect=False)
        pm = bundle["pm_headers"]
        r1 = create_rfi(bundle, subject="First question")
        r2 = create_rfi(bundle, subject="Second question", impacts_fee=True)

        assert r1["rfi_number"] == 1
        assert r2["rfi_number"] == 2
        assert r2["impacts_fee"] is True
        assert read_project(bundle)["open_rfi_count"] == 2

        validate_success(
            api.set_rfi_state(
                r1["id"], state_payload("ANSWERED", answer_text="See sketch SK-01."), pm
            )
        )
        assert read_project(bundle)["open_rfi_count"] == 1

        closed = validate_success(api.set_rfi_state(r1["id"], state_payload("CLOSED"), pm))
        assert closed["status"] == "CLOSED"
        assert read_project(bundle)["open_rfi_count"] == 1, (
            "the RFI already left the open set when it was ANSWERED"
        )

        voided = validate_success(api.set_rfi_state(r2["id"], state_payload("VOID"), pm))
        assert voided["status"] == "VOID"
        project = read_project(bundle)
        assert project["open_rfi_count"] == 0
        assert project["ca_posture"] == "CLEAR"


class TestLogicalClock:

    def test_clock_defaults_to_2026_05_01_before_it_is_ever_set(self, api):
        """PRD §2.4: "Before the clock has ever been set, it reads exactly `2026-05-01T00:00:00Z`,
        and it never falls back to real time."
        PRD §2.4: "A `PrincipalArchitect` may reposition the clock by supplying a `to_iso8601`
        instant; the response reports the new `current_utc`."
        PRD §3.4: "The answer is stored, `answered_at` is stamped from the logical clock, and the
        RFI moves to `ANSWERED` — at which point `open_rfi_count` drops by one and `ca_posture` is
        re-derived (returning to `CLEAR` only once the count reaches 0)."

        Design: Corner/endpoints/clock_defaults_to_2026_05_01_before_any_set_call
        """
        bundle = setup_project(project_number="CLK-001", name="Clock Close",
                               labor_budget_cents=500_000, with_architect=False)
        rfi = create_rfi(bundle, subject="Confirm datum")

        answered = validate_success(
            api.set_rfi_state(
                rfi["id"],
                state_payload("ANSWERED", answer_text="Datum is 0.00 at finished floor."),
                bundle["pm_headers"],
            )
        )
        assert_rfi(answered)
        assert answered["status"] == "ANSWERED"
        assert answered["answer_text"] == "Datum is 0.00 at finished floor."
        assert_instant_equals(answered["answered_at"], CLOCK_DEFAULT_UTC, "answered_at")

        project = read_project(bundle)
        assert project["open_rfi_count"] == 0
        assert project["ca_posture"] == "CLEAR"

        clock = validate_success(
            api.set_clock({"to_iso8601": "2026-09-09T09:09:09Z"}, PRINCIPAL)
        )
        assert_instant_equals(clock["current_utc"], "2026-09-09T09:09:09Z", "current_utc")
