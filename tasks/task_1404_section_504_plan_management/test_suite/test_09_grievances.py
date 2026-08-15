"""Grievance intake, escalation, resolution, and the OCR posture cascade
(PRD §2.1, §2.7, §2.8, §2.10, §3.8, §4)."""
from test_helpers import (
    ApiErrorId,
    create_student_for,
    file_grievance,
    get_school_posture_snapshot,
    get_success_data,
    make_coordinator_headers,
    make_director_headers,
    make_teacher_headers,
    set_clock,
    setup_school_with_staff,
    validate_error,
    validate_success,
)


def _grievance_ctx(api, include_director=True):
    """School + coordinator + director + one student. All staff trained."""
    ctx = setup_school_with_staff(include_director=include_director)
    student = create_student_for(ctx["school"]["id"], ctx["coordinator"]["id"])
    ctx["student"] = student
    return ctx


def _resolve_grievance(api, grievance_id, director_id):
    """Resolve with a fresh OCC read of the grievance version (PRD §2.7)."""
    gv = get_success_data(api.get_grievance(grievance_id, make_director_headers(director_id)))
    return api.resolve_grievance(
        grievance_id, {"expected_grievance_version": gv["version"]},
        make_director_headers(director_id),
    )


class TestGrievanceStateMachine:
    def test_grievance_terminal_lockdown_resolved(self, api):
        """PRD §3.8: "Two further district-only moves handle the OCR path.
        Escalating to OCR requires `FORMAL_INVESTIGATION` (otherwise
        `ERR_GRIEVANCE_NOT_FORMAL`), moves the grievance to `ESCALATED_TO_OCR`,
        emits `GRIEVANCE_ESCALATED`, and recomputes posture — the OCR flag alone
        forces `AUDIT_HOLD`."

        Design: Corner/state_machines/grievance_terminal_lockdown_resolved
        """
        ctx = _grievance_ctx(api)
        co, director = ctx["coordinator"], ctx["director"]
        grievance = file_grievance(ctx["student"]["id"], parent_ref="p")
        validate_success(api.begin_informal_grievance(grievance["id"], make_coordinator_headers(co["id"])))
        resolved = _resolve_grievance(api, grievance["id"], director["id"])
        validate_success(resolved)
        # RESOLVED is terminal — escalate-to-ocr must be rejected.
        resp = api.escalate_grievance_to_ocr(grievance["id"], make_director_headers(director["id"]))
        validate_error(resp, ApiErrorId.ERR_GRIEVANCE_NOT_FORMAL)

    def test_coordinator_cannot_resolve_grievance(self, api):
        """PRD §2.1: "Each operation is restricted to a designated set of roles
        (enumerated per endpoint in §4); an authenticated caller whose role is
        not permitted for the requested operation is rejected with
        `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
        PRD §4: POST `/grievances/{grievanceId}/resolve` — "Resolve a grievance
        (district level, OCC-guarded)" — authorized role: District504Director.

        Design: Corner/roles/coordinator_cannot_resolve_grievance
        """
        ctx = _grievance_ctx(api)
        co = ctx["coordinator"]
        grievance = file_grievance(ctx["student"]["id"], parent_ref="p")
        validate_success(api.begin_informal_grievance(grievance["id"], make_coordinator_headers(co["id"])))
        gv = get_success_data(api.get_grievance(grievance["id"], make_coordinator_headers(co["id"])))
        resp = api.resolve_grievance(
            grievance["id"], {"expected_grievance_version": gv["version"]},
            make_coordinator_headers(co["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


class TestOcrEscalationCascade:
    def _grievance_in_formal_investigation(self, api):
        ctx = _grievance_ctx(api)
        co = ctx["coordinator"]
        grievance = file_grievance(ctx["student"]["id"], parent_ref="parent-O",
                                   grievance_category="DISCRIMINATION",
                                   description="OCR-bound")
        validate_success(api.begin_informal_grievance(grievance["id"], make_coordinator_headers(co["id"])))
        validate_success(api.escalate_grievance_to_formal(grievance["id"], make_coordinator_headers(co["id"])))
        return ctx, grievance

    def test_grievance_ocr_escalation_posture_cascade(self, api):
        """PRD §3.8: "Escalating to OCR requires `FORMAL_INVESTIGATION`
        (otherwise `ERR_GRIEVANCE_NOT_FORMAL`), moves the grievance to
        `ESCALATED_TO_OCR`, emits `GRIEVANCE_ESCALATED`, and recomputes posture
        — the OCR flag alone forces `AUDIT_HOLD`."
        PRD §2.10: "If any grievance at the school has reached
        `ESCALATED_TO_OCR`, a further 50 points are contributed. An OCR
        escalation therefore forces `AUDIT_HOLD` on its own, regardless of
        everything else."

        Design: Difficulty/transitive_cascade/grievance_ocr_escalation_posture_cascade
        """
        ctx, grievance = self._grievance_in_formal_investigation(api)
        director = ctx["director"]
        escalated = validate_success(api.escalate_grievance_to_ocr(
            grievance["id"], make_director_headers(director["id"])
        ))
        assert escalated["grievance_status"] == "ESCALATED_TO_OCR"
        school_after = validate_success(api.get_school(
            ctx["school"]["id"], make_director_headers(director["id"])
        ))
        assert school_after["school_posture"] == "AUDIT_HOLD", (
            "the OCR flag alone must force AUDIT_HOLD regardless of composite score"
        )
        events = get_success_data(api.list_audit_events(
            make_director_headers(director["id"]),
            params={"school_id": ctx["school"]["id"], "event_type": "GRIEVANCE_ESCALATED",
                    "entity_ref": grievance["id"]},
        ))
        assert len(events) == 1, "escalation must emit GRIEVANCE_ESCALATED"

    def test_ocr_escalation_blocks_school_mutations(self, api):
        """PRD §2.8: "4. The school posture gate — a mutation scoped under a
        school whose `school_posture` is `AUDIT_HOLD` is rejected with
        `ERR_SCHOOL_UNDER_AUDIT_HOLD` (HTTP 409) before any deeper rule runs."
        PRD §2.10: "If any grievance at the school has reached
        `ESCALATED_TO_OCR`, a further 50 points are contributed. An OCR
        escalation therefore forces `AUDIT_HOLD` on its own, regardless of
        everything else."

        Design: Difficulty/transitive_cascade/grievance_ocr_escalation_posture_cascade
        """
        ctx, grievance = self._grievance_in_formal_investigation(api)
        director = ctx["director"]
        validate_success(api.escalate_grievance_to_ocr(
            grievance["id"], make_director_headers(director["id"])
        ))
        # A school-scoped mutation (new referral for the student) is gated.
        resp = api.create_referral(
            {"student_id": ctx["student"]["id"], "referral_reason": "r-after-hold",
             "suspected_disability_category": "OTHER"},
            make_teacher_headers(ctx["teacher"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_SCHOOL_UNDER_AUDIT_HOLD)


class TestGrievancePostureInvariant:
    def test_grievance_file_then_resolve_restores_posture_score(self, api):
        """PRD §3.8: "Filing stamps `filed_at`, opens the grievance in `FILED`,
        emits `GRIEVANCE_FILED`, and immediately recomputes the school's
        posture, since the new open grievance adds to the composite score."
        PRD §3.8: "Resolution records `resolved_by_staff_id`, increments the
        grievance's `version` by 1, moves it to `RESOLVED`, and recomputes the
        school's posture as the open-grievance count drops."
        PRD §2.10: "Each open grievance at the school — one whose status is
        `FILED`, `INFORMAL_RESOLUTION`, or `FORMAL_INVESTIGATION` — contributes
        20 points."

        Design: Difficulty/compensating_invariant/grievance_file_then_resolve_restores_posture_score
        """
        set_clock("2026-08-01T00:00:00Z")
        ctx = _grievance_ctx(api)
        co, director = ctx["coordinator"], ctx["director"]
        school_id = ctx["school"]["id"]
        pre = get_school_posture_snapshot(school_id, co["id"])
        assert pre["posture"] == "OPERATIONAL"
        assert pre["composite_score"] == 0, (
            f"fully trained staff and no grievances must yield composite 0, got {pre['composite_score']}"
        )

        # Forward action: file + begin informal (still an open grievance).
        grievance = file_grievance(ctx["student"]["id"], parent_ref="parent-IB")
        validate_success(api.begin_informal_grievance(grievance["id"], make_coordinator_headers(co["id"])))
        mid = get_school_posture_snapshot(school_id, co["id"])
        assert mid["posture"] == "OPERATIONAL"
        assert mid["composite_score"] == 20, (
            f"one open grievance contributes 20 points, got {mid['composite_score']}"
        )

        # Compensating action: resolve (open-grievance count drops to zero).
        validate_success(_resolve_grievance(api, grievance["id"], director["id"]))
        post = get_school_posture_snapshot(school_id, co["id"])
        assert post["posture"] == "OPERATIONAL"
        assert post["composite_score"] == 0, (
            f"resolving must restore the conserved composite score, got {post['composite_score']}"
        )
        grievance_after = validate_success(api.get_grievance(
            grievance["id"], make_director_headers(director["id"])
        ))
        assert grievance_after["grievance_status"] == "RESOLVED"

    def test_two_grievances_flip_posture_and_two_resolves_restore_it(self, api):
        """PRD §2.10: "Each open grievance at the school — one whose status is
        `FILED`, `INFORMAL_RESOLUTION`, or `FORMAL_INVESTIGATION` — contributes
        20 points." and "A composite score of 60 or more, or any nonzero
        OCR-escalation contribution, yields `AUDIT_HOLD`. Otherwise, a composite
        score of 30 or more yields `PROBATION`. Below that, the school is
        `OPERATIONAL`."
        PRD §3.8: "Resolution records `resolved_by_staff_id`, increments the
        grievance's `version` by 1, moves it to `RESOLVED`, and recomputes the
        school's posture as the open-grievance count drops."

        Design: Difficulty/compensating_invariant/grievance_file_then_resolve_restores_posture_score
        """
        set_clock("2026-08-01T00:00:00Z")
        ctx = _grievance_ctx(api)
        co, director = ctx["coordinator"], ctx["director"]
        school_id = ctx["school"]["id"]
        g1 = file_grievance(ctx["student"]["id"], parent_ref="parent-1", description="G1")
        g2 = file_grievance(ctx["student"]["id"], parent_ref="parent-2", description="G2")
        mid = get_school_posture_snapshot(school_id, co["id"])
        assert mid["composite_score"] == 40, f"two open grievances contribute 40, got {mid['composite_score']}"
        assert mid["posture"] == "PROBATION", "a composite of 40 (>= 30, < 60) yields PROBATION"
        for g in (g1, g2):
            validate_success(api.begin_informal_grievance(g["id"], make_coordinator_headers(co["id"])))
            validate_success(_resolve_grievance(api, g["id"], director["id"]))
        post = get_school_posture_snapshot(school_id, co["id"])
        assert post["composite_score"] == 0
        assert post["posture"] == "OPERATIONAL", (
            "resolving both grievances must restore the conserved posture"
        )
