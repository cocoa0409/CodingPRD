"""Case intake, per-arch planning, the exam close-out that prices the case, and
the cancellation cascade."""

from test_helpers import (
    ApiErrorId,
    assert_case_arch,
    assert_money,
    assert_prosthesis_case,
    assert_same_instant,
    create_case_arch_payload,
    fixtures as fx,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestArchPlanning:
    def test_required_milestones_are_computed_from_the_parent_case_type(self, api, prosthodontist_headers):
        """PRD §3.2: "At creation the server also computes the arch's
        `required_milestones` from the parent case's `prosthesis_type`, and that
        list is what the try-in stage will walk:"
        PRD §3.2: "- A `CAST_PARTIAL` requires a framework try-in, then a wax
        try-in, then a finish try-in, in that order."
        PRD §3.2: "- An `IMMEDIATE_DENTURE` requires **no** try-in milestones at
        all — its `required_milestones` is the empty list."
        PRD §3.2: "- An `IMPLANT_RETAINED_OVERDENTURE` requires a framework try-in
        and then a finish try-in."
        PRD §3.2: "A new arch is born in `PLANNED` with `retake_count`,
        `remake_count`, and `remake_request_count` at zero, `remake_eligibility` at
        `ELIGIBLE`, `fee_schedule_amount` at 0.00, and `last_lab_received_at` null."

        Design: Corner/entities/case_arch_required_milestones_computed_per_prosthesis_type
        """
        fx.set_clock("2026-05-01T00:00:00Z")
        patient = fx.register_patient(
            full_name="Dara Egwu", date_of_birth="1944-05-05", phone="555-1002"
        )
        cast_partial = fx.open_case(patient["id"], "CAST_PARTIAL")
        implant = fx.open_case(patient["id"], "IMPLANT_RETAINED_OVERDENTURE")
        immediate = fx.open_case(patient["id"], "IMMEDIATE_DENTURE")

        arch_cp = validate_success(
            api.create_case_arch(
                create_case_arch_payload(cast_partial["id"], "MAXILLARY"), prosthodontist_headers
            ),
            201,
        )
        arch_iro = validate_success(
            api.create_case_arch(
                create_case_arch_payload(implant["id"], "MAXILLARY"), prosthodontist_headers
            ),
            201,
        )
        arch_imm = validate_success(
            api.create_case_arch(
                create_case_arch_payload(immediate["id"], "MAXILLARY"), prosthodontist_headers
            ),
            201,
        )

        assert arch_cp["required_milestones"] == ["FRAMEWORK", "WAX", "FINISH"]
        assert arch_iro["required_milestones"] == ["FRAMEWORK", "FINISH"]
        assert arch_imm["required_milestones"] == []
        for arch in (arch_cp, arch_iro, arch_imm):
            assert_case_arch(arch)
            assert arch["arch_status"] == "PLANNED"
            assert arch["remake_count"] == 0
            assert arch["remake_request_count"] == 0
            assert arch["remake_eligibility"] == "ELIGIBLE"

    def test_second_arch_at_the_same_position_is_a_schema_failure(self, api, prosthodontist_headers):
        """PRD §3.2: "A `Prosthodontist` adds an arch by naming the `case_id` and the
        `arch_position`, which is `MAXILLARY` or `MANDIBULAR`; adding an arch is
        likewise inside the global write gate, at most one arch row may exist per
        case per position, and a duplicate pair is a rung 7 schema failure."
        PRD §2.10: "The other uniqueness pair carries no such ambiguity: a duplicate
        `case_id`-and-`arch_position` belongs to rung 7 and `ERR_VALIDATION` alone."

        Design: Corner/entities/duplicate_arch_position_on_same_case_is_rejected
        """
        fx.set_clock("2026-05-01T00:00:00Z")
        patient = fx.register_patient(
            full_name="Eda Sorensen", date_of_birth="1955-06-06", phone="555-1003"
        )
        case = fx.open_case(patient["id"], "FLEXIBLE_PARTIAL")
        fx.add_arch(case["id"], "MAXILLARY")

        response = api.create_case_arch(
            create_case_arch_payload(case["id"], "MAXILLARY"), prosthodontist_headers
        )
        validate_error(response, ApiErrorId.ERR_VALIDATION.value, 400)

        _, meta = validate_paginated(
            api.list_case_arches(
                prosthodontist_headers, params={"case_id": case["id"], "limit": 10, "offset": 0}
            )
        )
        assert meta["total_count"] == 1, "the case still carries exactly one arch"


class TestExamCloseOut:
    def test_two_flexible_partial_arches_total_2400_and_flip_the_predetermination_flag(self, api, prosthodontist_headers):
        """PRD §3.2: "Closing the exam sets each non-abandoned arch's
        `fee_schedule_amount` to the fee for the case's `prosthesis_type` — 1800.00
        for a complete denture, 2100.00 for an immediate denture, 1650.00 for a cast
        partial, 1200.00 for a flexible partial, 2400.00 for an overdenture, and
        3600.00 for an implant-retained overdenture — then sets the case's
        `fee_schedule_total` to the sum of `fee_schedule_amount` over every arch of
        the case whose `arch_status` is not `ARCH_ABANDONED`, rounded half up to two
        decimal places."
        PRD §3.2: "Finally it sets `predetermination_required` to true exactly when
        `fee_schedule_total` is at or above 1500.00, and increments the case's
        `version` by 1."
        PRD §3.2: "A single-arch complete denture at 1800.00 therefore requires a
        predetermination; a single-arch flexible partial at 1200.00 does not; a
        two-arch flexible partial at 2400.00 does."

        Design: Corner/calculations/fee_schedule_total_sums_two_arches_and_flips_predetermination_required
        """
        fx.set_clock("2026-05-01T00:00:00Z")
        patient = fx.register_patient(
            full_name="Vera Machado", date_of_birth="1950-11-23", phone="555-1020"
        )
        case = fx.open_case(patient["id"], "FLEXIBLE_PARTIAL")
        arch_a = fx.add_arch(case["id"], "MAXILLARY")
        arch_b = fx.add_arch(case["id"], "MANDIBULAR")

        closed = validate_success(api.complete_exam(case["id"], prosthodontist_headers), 200)

        assert_prosthesis_case(closed)
        assert_money(fx.read_arch(arch_a["id"])["fee_schedule_amount"], 1200.00, "arch A fee")
        assert_money(fx.read_arch(arch_b["id"])["fee_schedule_amount"], 1200.00, "arch B fee")
        assert_money(closed["fee_schedule_total"], 2400.00, "fee_schedule_total")
        assert closed["predetermination_required"] is True
        assert closed["case_status"] == "EXAM_COMPLETE"

    def test_second_complete_exam_is_refused_by_the_from_state_check(self, api, prosthodontist_headers):
        """PRD §3.2: "Closing the exam is what prices the case. A `Prosthodontist`
        closes it, moving `case_status` from `INTAKE` to `EXAM_COMPLETE`; the call
        requires that at least one arch already exists on the case, and a case with
        no arches is refused with `ERR_VALIDATION`."
        PRD §2.10: "**Rung 12 — from-state.** The target row's current state is a
        declared origin state of the transition the endpoint drives. Failure:
        `ERR_INVALID_STATE`, HTTP 409. Scope: every state-changing endpoint."

        Design: Corner/state_machines/complete_exam_twice_returns_invalid_state
        """
        ctx = fx.setup_case_past_exam(
            patient_overrides={
                "full_name": "Gaia Lindqvist", "date_of_birth": "1946-08-08", "phone": "555-1005"
            }
        )

        response = api.complete_exam(ctx["case"]["id"], prosthodontist_headers)
        validate_error(response, ApiErrorId.ERR_INVALID_STATE.value, 409)

        after = fx.read_case(ctx["case"]["id"])
        assert after["case_status"] == "EXAM_COMPLETE"
        assert_money(after["fee_schedule_total"], 1200.00, "fee_schedule_total")

    def test_complete_exam_on_a_case_with_no_arch_is_refused(self, api, prosthodontist_headers):
        """PRD §3.2: "the call requires that at least one arch already exists on the
        case, and a case with no arches is refused with `ERR_VALIDATION`."

        Design: Corner/state_machines/complete_exam_with_no_arch_is_rejected
        """
        fx.set_clock("2026-05-01T00:00:00Z")
        patient = fx.register_patient(
            full_name="Hana Oduya", date_of_birth="1959-09-09", phone="555-1006"
        )
        case = fx.open_case(patient["id"], "FLEXIBLE_PARTIAL")

        response = api.complete_exam(case["id"], prosthodontist_headers)
        validate_error(response, ApiErrorId.ERR_VALIDATION.value, 400)

        after = fx.read_case(case["id"])
        assert after["case_status"] == "INTAKE"
        assert_money(after["fee_schedule_total"], 0.00, "fee_schedule_total")


class TestCancellationCascade:
    def test_cancel_abandons_the_arch_and_cancels_the_dispatched_lab_case(self, api, prosthodontist_headers):
        """PRD §3.2: "The case moves to `CANCELLED`. Every arch of the case whose
        `arch_status` is not already `ARCH_CLOSED` or `ARCH_ABANDONED` moves to
        `ARCH_ABANDONED` — and that includes an arch already sitting in `DELIVERED`,
        so a two-arch case can be cancelled after one arch was delivered and the
        delivered arch is abandoned along with its sibling."
        PRD §3.2: "Every lab case belonging to those arches whose `lab_status` is
        not `QC_PASSED`, `EXPIRED`, or `CANCELLED` moves to `CANCELLED`, releasing
        whatever bench-line occupation it held. Every try-in milestone of those
        arches sitting in `PENDING_APPROVAL` or `ADJUST_REQUESTED` moves to
        `CANCELLED`."

        Design: Corner/state_machines/case_cancel_cascades_to_arch_tryin_and_open_lab_case
        """
        fx.set_clock("2026-05-01T00:00:00Z")
        patient = fx.register_patient(
            full_name="Ilan Braga", date_of_birth="1947-10-10", phone="555-1007"
        )
        lab = fx.register_lab()
        case = fx.open_case(patient["id"], "FLEXIBLE_PARTIAL")
        arch = fx.add_arch(case["id"], "MAXILLARY")
        fx.complete_exam(case["id"])
        fx.start_fabrication(arch["id"])
        fx.accepted_impression(arch["id"], "DIGITAL_SCAN", 92)
        try_in = fx.book_try_in(arch["id"], "WAX")
        fx.decide_try_in(try_in["id"], "APPROVE")
        lab_case = fx.draft_lab_case(arch["id"], lab["id"])
        fx.dispatch_lab_case(lab_case["id"])

        cancelled = validate_success(
            api.cancel_case(
                case["id"], prosthodontist_headers,
                {"cancellation_reason": "Patient relocated out of area"},
            ),
            200,
        )

        assert cancelled["case_status"] == "CANCELLED"
        assert fx.read_arch(arch["id"])["arch_status"] == "ARCH_ABANDONED"
        assert fx.read_lab_case(lab_case["id"])["lab_status"] == "CANCELLED"
        assert fx.read_try_in(try_in["id"])["approval_status"] == "APPROVED", (
            "an already-decided milestone is not re-cancelled"
        )

    def test_cancelling_a_cancelled_case_is_stopped_by_the_terminal_gate(self, api, prosthodontist_headers):
        """PRD §3.2: "`CLOSED` and `CANCELLED` are the two terminal states of the
        case axis; `ARCH_CLOSED` and `ARCH_ABANDONED` are the two terminal states of
        the arch axis."
        PRD §2.10: "**Rung 10 — terminal state.** The target row is not already in a
        terminal state of the state axis the operation drives."
        PRD §2.10: "Failure: `ERR_TERMINAL_STATE`, HTTP 409. Scope: every
        state-changing endpoint."

        Design: Corner/state_machines/cancel_a_cancelled_case_returns_terminal_state
        """
        fx.set_clock("2026-05-01T00:00:00Z")
        patient = fx.register_patient(
            full_name="Jonas Weill", date_of_birth="1958-11-11", phone="555-1008"
        )
        case = fx.open_case(patient["id"], "FLEXIBLE_PARTIAL")
        validate_success(
            api.cancel_case(
                case["id"], prosthodontist_headers, {"cancellation_reason": "Duplicate record"}
            ),
            200,
        )

        response = api.cancel_case(
            case["id"], prosthodontist_headers, {"cancellation_reason": "Duplicate record"}
        )
        validate_error(response, ApiErrorId.ERR_TERMINAL_STATE.value, 409)


class TestFabricationStartPreconditions:
    def test_start_fabrication_is_refused_while_the_parent_case_is_still_in_intake(self, api, prosthodontist_headers):
        """PRD §2.10: "- `POST /prosthetics/case-arches/{case_arch_id}/start-fabrication`
        — the parent case's `case_status` must be `EXAM_COMPLETE` when the arch is
        leaving `PLANNED`, and `IN_FABRICATION` when it is leaving `REMAKE_PENDING`."
        PRD §2.10: "    Failure: `ERR_CROSS_ENTITY_STATE`, HTTP 409."

        Design: Difficulty/cross_entity_state_dependency/start_fabrication_requires_parent_case_exam_complete
        """
        fx.set_clock("2026-05-01T00:00:00Z")
        patient = fx.register_patient(
            full_name="Quilla Basani", date_of_birth="1961-08-14", phone="555-0388"
        )
        case = fx.open_case(patient["id"], "FLEXIBLE_PARTIAL")
        arch = fx.add_arch(case["id"], "MAXILLARY")

        response = api.start_fabrication(arch["id"], prosthodontist_headers)
        validate_error(response, ApiErrorId.ERR_CROSS_ENTITY_STATE.value, 409)

        assert fx.read_arch(arch["id"])["arch_status"] == "PLANNED", (
            "the arch's own PLANNED state was legal; only the parent blocked the call"
        )
        after_case = fx.read_case(case["id"])
        assert after_case["case_status"] == "INTAKE"
        assert after_case["fabrication_started_at"] is None

    def test_start_fabrication_succeeds_once_the_exam_is_closed(self, api, prosthodontist_headers):
        """PRD §3.2: "The arch moves `PLANNED → IMPRESSION_PENDING`, its
        `retake_count` is reset to zero, its `required_milestones` is recomputed from
        the case's `prosthesis_type`, and its `version` is incremented by 1. That
        same action bubbles the parent case from `EXAM_COMPLETE` to
        `IN_FABRICATION`, stamps the case's `fabrication_started_at` with the logical
        clock, and increments the case's `version` by 1 — a bubble-up that happens
        only once, on the first arch of the case to leave `PLANNED`."

        Design: Difficulty/cross_entity_state_dependency/start_fabrication_requires_parent_case_exam_complete
        """
        fx.set_clock("2026-05-01T00:00:00Z")
        patient = fx.register_patient(
            full_name="Quilla Basani", date_of_birth="1961-08-14", phone="555-0388"
        )
        case = fx.open_case(patient["id"], "FLEXIBLE_PARTIAL")
        arch = fx.add_arch(case["id"], "MAXILLARY")
        validate_error(
            api.start_fabrication(arch["id"], prosthodontist_headers),
            ApiErrorId.ERR_CROSS_ENTITY_STATE.value,
            409,
        )

        fx.complete_exam(case["id"])
        started = validate_success(api.start_fabrication(arch["id"], prosthodontist_headers), 200)

        assert started["arch_status"] == "IMPRESSION_PENDING"
        assert started["retake_count"] == 0
        after_case = fx.read_case(case["id"])
        assert after_case["case_status"] == "IN_FABRICATION"
        assert_same_instant(
            after_case["fabrication_started_at"],
            "2026-05-01T00:00:00.000Z",
            "ProsthesisCase.fabrication_started_at",
        )

    def test_start_fabrication_without_a_live_determination_is_refused(self, api, prosthodontist_headers):
        """PRD §3.2: "and — when the case's `predetermination_required` is true — a
        live approved or alternate-benefit predetermination must exist for the case,
        failing which the call is refused with `ERR_PREDETERMINATION_REQUIRED`."
        PRD §2.10: "**Rung 30 — predetermination gate.** When the target case's
        `predetermination_required` is true, a predetermination for that case must
        exist whose `determination_status` is `APPROVED` or `ALTERNATE_BENEFIT` and
        whose `expires_at` is strictly after the logical clock."

        Design: Corner/validations/predetermination_required_blocks_start_fabrication_when_absent
        """
        ctx = fx.setup_case_past_exam(
            prosthesis_type="COMPLETE_DENTURE",
            patient_overrides={
                "full_name": "Ciro Estevez", "date_of_birth": "1941-06-30", "phone": "555-1027"
            },
        )
        assert_money(ctx["case"]["fee_schedule_total"], 1800.00, "fee_schedule_total")
        assert ctx["case"]["predetermination_required"] is True

        response = api.start_fabrication(ctx["arch"]["id"], prosthodontist_headers)
        validate_error(response, ApiErrorId.ERR_PREDETERMINATION_REQUIRED.value, 422)

        assert fx.read_arch(ctx["arch"]["id"])["arch_status"] == "PLANNED"
