"""Transitive cascades, non-linear state machines (release/requeue and the
amendment cycle), and compensating invariants on derived counters."""
import pytest

from test_helpers import (
    TEST_USERS,
    accept_assignment,
    assign_study,
    create_assignment_payload,
    create_draft_report,
    create_routed_study,
    create_study,
    get_success_data,
    make_hospital_user_headers,
    make_radiologist_headers,
    set_clock,
    setup_assignment_ready,
    setup_credentialed_radiologist,
    setup_routing_ready_hospital,
    setup_study_in_progress,
    sign_report,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
DISPATCH = TEST_USERS["dispatch_headers"]
QA = TEST_USERS["qa_headers"]


class TestFinalSignCriticalCascade:
    def _setup(self, api):
        """Drive a STAT CT study to a DRAFT FINAL (critical, grade 2) ready to
        sign by a second radiologist, with a SIGNED prelim in place."""
        ctx = setup_assignment_ready(hospital_name="Hosp Casc", priority="STAT",
                                     prelim_required=True)
        hosp, rad_pre = ctx["hospital"], ctx["radiologist"]
        rad_fin, _g2, _s2 = setup_credentialed_radiologist(
            hosp["id"], full_name="Final R", shift_modalities=("CT",))
        study = create_routed_study(hosp["id"], "ACC-C", priority="STAT")
        asg1 = assign_study(study["id"], rad_pre["id"])
        accept_assignment(asg1)
        rep_pre = create_draft_report(asg1["id"], rad_pre["id"], "PRELIMINARY")
        rep_pre = sign_report(rep_pre["id"], rad_pre["id"])
        asg2 = assign_study(study["id"], rad_fin["id"])
        accept_assignment(asg2)
        rep_fin = create_draft_report(asg2["id"], rad_fin["id"], "FINAL",
                                      critical_finding=True, discrepancy_grade=2)
        return hosp, rad_pre, rad_fin, study, rep_pre, rep_fin, asg2

    def test_final_sign_cascade_report_study_and_prelim_hops(self, api):
        """PRD section 3.6: "On signature the report becomes `SIGNED`, the study
        moves `IN_PROGRESS → FINAL_SIGNED`, and `first_final_signed_at` is
        pinned to this signature's `signed_at` — the billing anchor that later
        addenda never move. ... The study's signed preliminary report, if any,
        transitions `SIGNED → SUPERSEDED` — its provisional credit stands and is
        not clawed back."

        Design: Difficulty/transitive_cascade/final_sign_critical_cascade
        """
        hosp, rad_pre, rad_fin, study, rep_pre, rep_fin, asg2 = self._setup(api)
        signed = sign_report(rep_fin["id"], rad_fin["id"])
        # Hop 1: report SIGNED, credit = 1.5 * (1 - 0.25) = 1.125, rounded
        # half-up to 2 decimal places (PRD section 3.6) -> 1.13 for grade 2.
        assert signed["status"] == "SIGNED"
        assert signed["credited_rvu"] == pytest.approx(1.13)
        # Hop 2: study FINAL_SIGNED.
        st = get_success_data(api.get_study(study["id"], DISPATCH))
        assert st["status"] == "FINAL_SIGNED"
        # Hop 3a: the prelim is superseded.
        pre = get_success_data(api.get_report(rep_pre["id"], QA))
        assert pre["status"] == "SUPERSEDED"
        # Assignment completes.
        asg_after = get_success_data(api.get_assignment(asg2["id"], DISPATCH))
        assert asg_after["status"] == "COMPLETED"

    def test_final_sign_cascade_case_notice_and_counter_hops(self, api):
        """PRD section 3.6: "Finally, a grade of 2 or 3 automatically opens a
        discrepancy case in `OPEN` status with `origin` `AUTO`, seeded from the
        two reports."
        PRD section 3.7: "A report signed with `critical_finding` true spawns,
        in the same request, a **critical-result notice** in `PENDING` status
        referencing the `report_id`, the `study_id`, and the signing
        `radiologist_id`, and raising that radiologist's
        `pending_critical_count` by one."

        Design: Difficulty/transitive_cascade/final_sign_critical_cascade
        """
        hosp, rad_pre, rad_fin, study, rep_pre, rep_fin, asg2 = self._setup(api)
        sign_report(rep_fin["id"], rad_fin["id"])
        # Hop 3b: exactly one AUTO discrepancy case, OPEN, grade 2.
        cases, meta = validate_paginated(
            api.list_discrepancy_cases(QA, params={"study_id": study["id"]}))
        assert meta["total_count"] == 1
        assert cases[0]["status"] == "OPEN"
        assert cases[0]["origin"] == "AUTO"
        assert cases[0]["grade"] == 2
        # Hop 3c: exactly one PENDING notice on the final report.
        notices, nmeta = validate_paginated(
            api.list_critical_notices(DISPATCH, params={"report_id": rep_fin["id"]}))
        assert nmeta["total_count"] == 1
        assert notices[0]["status"] == "PENDING"
        # Hop 4: the signer's pending_critical_count rose by one.
        rad_after = get_success_data(api.get_radiologist(rad_fin["id"], ADMIN))
        assert rad_after["pending_critical_count"] == 1


class TestReleaseRequeueCascade:
    def _setup_assigned(self, api, name):
        ctx = setup_assignment_ready(hospital_name=name)
        hosp, rad = ctx["hospital"], ctx["radiologist"]
        study = create_routed_study(hosp["id"], "ACC-R")
        asg = assign_study(study["id"], rad["id"])
        return hosp, rad, study, asg

    def test_release_returns_study_to_queued_with_exclusion(self, api):
        """PRD section 3.5: "...release moves the assignment to `RELEASED`,
        returns the study to `QUEUED` with `assigned_radiologist_id` cleared,
        appends the releasing radiologist to the study's
        `excluded_radiologist_ids` so they cannot be picked again for this
        study, decrements the radiologist's `reserved_rvu` by the study's base
        RVU, adjusts `stat_active_count` when the study is `STAT`, and
        increments both resources' `version`."

        Design: Difficulty/transitive_cascade/release_requeue_cascade
        """
        hosp, rad, study, asg = self._setup_assigned(api, "Hosp Rel")
        data = validate_success(api.release_assignment(
            asg["id"], make_radiologist_headers(rad["id"])), 200)
        # Hop 1: assignment RELEASED.
        assert data["status"] == "RELEASED"
        # Hop 2: study back to QUEUED, assignee cleared, exclusion appended.
        st = get_success_data(api.get_study(study["id"], DISPATCH))
        assert st["status"] == "QUEUED"
        assert st["assigned_radiologist_id"] is None
        assert rad["id"] in st["excluded_radiologist_ids"]

    def test_release_decrements_reserved_rvu_to_zero(self, api):
        """PRD section 2.9: "Assignment reserves capacity; signature converts
        reservation into completed credit; release or cancellation returns the
        reservation to the pool. All of these cascades land in the same request
        as their trigger — no deferred or eventual settlement exists anywhere in
        the system."

        Design: Difficulty/transitive_cascade/release_requeue_cascade
        """
        hosp, rad, study, asg = self._setup_assigned(api, "Hosp Rel 2")
        validate_success(api.release_assignment(
            asg["id"], make_radiologist_headers(rad["id"])), 200)
        # Hop 3: reservation returned to the pool.
        rad_after = get_success_data(api.get_radiologist(rad["id"], ADMIN))
        assert rad_after["reserved_rvu"] == 0.0


class TestStudyReleaseRequeueAndAmendmentCycle:
    def test_release_requeue_revert_leg(self, api):
        """PRD section 3.5: "...release moves the assignment to `RELEASED`,
        returns the study to `QUEUED` with `assigned_radiologist_id` cleared,
        appends the releasing radiologist to the study's
        `excluded_radiologist_ids` so they cannot be picked again for this
        study..."

        Design: Difficulty/non_linear_state_machine/study_release_requeue_and_amendment_cycle
        """
        hosp = setup_routing_ready_hospital(name="Hosp Loop")
        rad_a, _ga, _sa = setup_credentialed_radiologist(hosp["id"], full_name="Rad A")
        study = create_routed_study(hosp["id"], "ACC-L")
        asg1 = assign_study(study["id"], rad_a["id"])
        validate_success(api.release_assignment(
            asg1["id"], make_radiologist_headers(rad_a["id"])), 200)
        st = get_success_data(api.get_study(study["id"], DISPATCH))
        assert st["status"] == "QUEUED"  # revert ASSIGNED -> QUEUED fired
        assert rad_a["id"] in st["excluded_radiologist_ids"]

    def test_amendment_cycle_closes_back_to_final_signed(self, api):
        """PRD section 3.6: "A study that has reached `FINAL_SIGNED` may be sent
        back for amendment by its owning `ClientHospitalUser`: the
        request-addendum action moves `FINAL_SIGNED → AMENDMENT_PENDING`..." and
        "On signature the study returns to `FINAL_SIGNED`, `addendum_count`
        increases by 1, `first_final_signed_at` is left untouched, and the
        assignment completes with the usual recomputation of the radiologist's
        utilization counters."

        Design: Difficulty/non_linear_state_machine/study_release_requeue_and_amendment_cycle
        """
        ctx = setup_assignment_ready(hospital_name="Hosp Loop 2")
        hosp, rad = ctx["hospital"], ctx["radiologist"]
        study = create_routed_study(hosp["id"], "ACC-L2")
        asg = assign_study(study["id"], rad["id"])
        accept_assignment(asg)
        rep_f = create_draft_report(asg["id"], rad["id"], "FINAL")
        sign_report(rep_f["id"], rad["id"])
        st = get_success_data(api.get_study(study["id"], DISPATCH))
        assert st["status"] == "FINAL_SIGNED"

        # FINAL_SIGNED -> AMENDMENT_PENDING.
        amend = validate_success(api.request_addendum(
            study["id"], make_hospital_user_headers(hosp["id"])), 200)
        assert amend["status"] == "AMENDMENT_PENDING"

        # Re-assign (FINAL phase), sign an ADDENDUM, cycle closes.
        asg3 = assign_study(study["id"], rad["id"])
        assert asg3["phase"] == "FINAL"
        accept_assignment(asg3)
        rep_a = create_draft_report(asg3["id"], rad["id"], "ADDENDUM")
        sign_report(rep_a["id"], rad["id"])
        end = get_success_data(api.get_study(study["id"], DISPATCH))
        assert end["status"] == "FINAL_SIGNED"
        assert end["addendum_count"] == 1


class TestReservedRvuConservation:
    def test_reserved_rvu_tracks_assignment_sum(self, api):
        """PRD section 2.9: "Three derived counters live on every radiologist:
        `reserved_rvu`, the sum of the reserved RVU over that radiologist's
        `ACTIVE` assignments..." and "Assignment reserves capacity; signature
        converts reservation into completed credit; release or cancellation
        returns the reservation to the pool."

        Design: Difficulty/compensating_invariant/reserved_rvu_conserved_across_assign_release
        """
        ctx = setup_assignment_ready(hospital_name="Hosp Inv")
        hosp, rad = ctx["hospital"], ctx["radiologist"]
        before = get_success_data(api.get_radiologist(rad["id"], ADMIN))
        assert before["reserved_rvu"] == 0.0

        study = create_routed_study(hosp["id"], "ACC-INV")
        asg = assign_study(study["id"], rad["id"])
        during = get_success_data(api.get_radiologist(rad["id"], ADMIN))
        # Forward action: CT base 1.5 reserved.
        assert during["reserved_rvu"] == pytest.approx(1.5)
        assert asg["reserved_rvu"] == pytest.approx(1.5)

    def test_reserved_rvu_returns_exactly_after_release(self, api):
        """PRD section 2.9: "...release or cancellation returns the reservation
        to the pool. All of these cascades land in the same request as their
        trigger — no deferred or eventual settlement exists anywhere in the
        system."

        Design: Difficulty/compensating_invariant/reserved_rvu_conserved_across_assign_release
        """
        ctx = setup_assignment_ready(hospital_name="Hosp Inv 2")
        hosp, rad = ctx["hospital"], ctx["radiologist"]
        study = create_routed_study(hosp["id"], "ACC-INV2")
        asg = assign_study(study["id"], rad["id"])
        validate_success(api.release_assignment(
            asg["id"], make_radiologist_headers(rad["id"])), 200)
        after = get_success_data(api.get_radiologist(rad["id"], ADMIN))
        # Compensating action returns the conserved quantity with zero drift.
        assert after["reserved_rvu"] == 0.0
        rows, meta = validate_paginated(api.list_assignments(
            DISPATCH, params={"radiologist_id": rad["id"], "status": "ACTIVE"}))
        assert meta["total_count"] == 0


class TestCompletedRvuWindowRollsWithClock:
    def _sign_final_at_work_clock(self, api):
        ctx = setup_study_in_progress(accession_number="ACC-WR", priority="ROUTINE")
        rad = ctx["radiologist"]
        rep = create_draft_report(ctx["assignment"]["id"], rad["id"], "FINAL")
        sign_report(rep["id"], rad["id"])  # signed at 2026-05-10T10:00:00Z
        return rad

    def test_completed_rvu_counts_inside_window(self, api):
        """PRD section 2.9: "...`completed_rvu_24h`, the sum of `credited_rvu`
        over that radiologist's reports in status `SIGNED` or `SUPERSEDED` whose
        `signed_at` falls strictly inside the trailing twenty-four hours under
        the logical clock — a signature exactly twenty-four hours old is
        excluded..."

        Design: Corner/cross_cutting_layers/completed_rvu_24h_window_rolls_with_clock
        """
        rad = self._sign_final_at_work_clock(api)
        set_clock("2026-05-11T09:59:59Z")  # T + 23:59:59 — inside the window
        data = get_success_data(api.get_radiologist(rad["id"], ADMIN))
        assert data["completed_rvu_24h"] == pytest.approx(1.5)

    def test_completed_rvu_excludes_exactly_twenty_four_hours(self, api):
        """PRD section 2.9: "...whose `signed_at` falls strictly inside the
        trailing twenty-four hours under the logical clock — a signature exactly
        twenty-four hours old is excluded..."

        Design: Corner/cross_cutting_layers/completed_rvu_24h_window_rolls_with_clock
        """
        rad = self._sign_final_at_work_clock(api)
        set_clock("2026-05-11T10:00:00Z")  # exactly T + 24h — excluded
        data = get_success_data(api.get_radiologist(rad["id"], ADMIN))
        assert data["completed_rvu_24h"] == 0.0


class TestImmediateConsistency:
    def test_immediate_visibility_after_assignment(self, api):
        """PRD section 2.9: "Radiologist reading capacity is tracked as a
        utilization ledger that is recomputed, atomically and in the same
        request, on every assignment or report mutation and on read. ... All of
        these cascades land in the same request as their trigger — no deferred
        or eventual settlement exists anywhere in the system."
        PRD section 3.5: "Assignment cascades immediately: the study's
        `assigned_radiologist_id` is set to the chosen reader, the radiologist's
        `reserved_rvu` increases by the study's base RVU, `stat_active_count`
        rises by one when the study is `STAT`, and the study's `version`
        increments."

        Design: Corner/consistency_model/immediate_visibility_after_assignment
        """
        ctx = setup_assignment_ready(hospital_name="Hosp IM")
        hosp, rad = ctx["hospital"], ctx["radiologist"]
        study = create_routed_study(hosp["id"], "ACC-IM")
        fresh = get_success_data(api.get_study(study["id"], DISPATCH))
        resp = api.create_assignment(
            create_assignment_payload(study["id"], fresh["version"],
                                      radiologist_id=rad["id"]), DISPATCH)
        data = validate_success(resp, 201)
        # The mutation response itself carries the derived values.
        assert data["status"] == "ACTIVE"
        assert data["reserved_rvu"] == pytest.approx(1.5)
        # Immediate reads observe the reconciled state.
        st = get_success_data(api.get_study(study["id"], DISPATCH))
        assert st["status"] == "ASSIGNED"
        assert st["assigned_radiologist_id"] == rad["id"]
        rr = get_success_data(api.get_radiologist(rad["id"], ADMIN))
        assert rr["reserved_rvu"] == pytest.approx(1.5)