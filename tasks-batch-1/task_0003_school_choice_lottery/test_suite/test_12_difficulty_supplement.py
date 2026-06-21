"""Supplemental tests for the harder rules: each rule covered here already
has a primary test in test_01..test_07, and the function below contributes
a second, distinct observable outcome of the same PRD rule. Splitting the
coverage this way keeps each test focused on one observable property of the
PRD contract.
"""
from test_helpers import (
    set_clock,
    create_district,
    create_school,
    create_window,
    open_window,
    register_family,
    create_student,
    create_application,
    submit_application,
    advance_window_to_closed,
    advance_window_to_lottery_run,
    list_offers_for_application,
    list_waitlist_entries_for_application,
    list_waitlist_entries_for_school,
    accept_offer_with_current_version,
    decline_offer,
    finalize_window,
    get_application,
    get_window,
    api_client,
    TEST_USERS,
    make_guardian_headers,
    validate_success,
    validate_error,
    ApiErrorId,
)
from test_helpers.factories import (
    run_lottery_payload,
    accept_offer_payload,
    create_application_payload,
)


# =====================================================================
# Difficulty rule 2 / instance 2 (companion) — IDT app retains its place
# in the global sort order for queue_rank purposes after demotion
# =====================================================================

def test_idt_app_demoted_by_cap_is_recorded_as_waitlisted_entry(api):
    """PRD §3.6: "Cap evaluation is strict and traverses the sorted list
    top-down: an inter-district application whose admission would push the
    running count of inter-district admits above the cap is skipped and
    demoted to the waitlist (retaining its place in the global sort order
    for `queue_rank` purposes), and the next in-district application by
    rank is promoted into the freed seat."

    Companion to the two-seat IDT-cap test: confirm the demoted IDT app
    materializes a WaitlistEntry with status=ACTIVE (the per-PRD outcome
    of "demoted to the waitlist"); the school's WaitlistEntry list under
    status=ACTIVE must contain exactly the IDT-app's entry.

    Design: Difficulty/combinatorial_formula/lottery_seat_assignment_circular_eval_order_mode_c
    """
    set_clock("2026-01-01T00:00:00Z")
    host = create_district(code="DICX", name="Host2", poverty_index_pct=0.00)
    other = create_district(code="DICY", name="Other2", poverty_index_pct=100.00)
    school = create_school(host["id"], code="SIC2", name="Two-seat-2",
                           school_type="MAGNET", grade_min=0, grade_max=12,
                           total_seats=2)
    window = create_window(host["id"], cycle_label="2026-27-ICC")
    fam_in1 = register_family(host["id"], guardian_email="icc-in1@x.com",
                              residence_zone_code="ZI1", poverty_flag=False)
    fam_in2 = register_family(host["id"], guardian_email="icc-in2@x.com",
                              residence_zone_code="ZI1", poverty_flag=False)
    fam_idt = register_family(other["id"], guardian_email="icc-idt@x.com",
                              residence_zone_code="ZI2", poverty_flag=True)
    stu_in1 = create_student(fam_in1["id"], grade_for_cycle=6)
    stu_in2 = create_student(fam_in2["id"], grade_for_cycle=6)
    stu_idt = create_student(fam_idt["id"], grade_for_cycle=6)
    set_clock("2026-01-03T00:00:00Z")
    open_window(window["id"])
    app_idt = create_application(fam_idt["id"], window["id"], stu_idt["id"],
                                 school["id"], choice_rank=1)
    submit_application(fam_idt["id"], app_idt["id"])
    app_in1 = create_application(fam_in1["id"], window["id"], stu_in1["id"],
                                 school["id"], choice_rank=1)
    submit_application(fam_in1["id"], app_in1["id"])
    app_in2 = create_application(fam_in2["id"], window["id"], stu_in2["id"],
                                 school["id"], choice_rank=1)
    submit_application(fam_in2["id"], app_in2["id"])
    advance_window_to_lottery_run(window["id"])
    active_wls = list_waitlist_entries_for_school(school["id"], status="ACTIVE")
    idt_wls = [w for w in active_wls if w["application_id"] == app_idt["id"]]
    assert len(idt_wls) == 1, (
        f"Demoted IDT application must materialize exactly one ACTIVE "
        f"WaitlistEntry; got {idt_wls!r}"
    )


# =====================================================================
# Difficulty rule 3 / instance 1 (companion) — branching also produces
# the correct queue_rank on the WAITLISTED side
# =====================================================================

def test_lottery_branching_waitlist_entry_queue_rank_starts_at_one(api):
    """PRD §3.5: "The top `total_seats` applications by `lottery_rank`, after
    the inter-district-transfer cap is applied, become `ACCEPTED`; the
    remainder become `WAITLISTED` with `queue_rank` equal to `lottery_rank
    − total_seats`, so that the first overflow application carries
    `queue_rank` 1."

    Companion to the SUBMITTED→ACCEPTED+WAITLISTED branching test: with
    total_seats=1 and two SUBMITTED apps, the one WAITLISTED application's
    WaitlistEntry must carry queue_rank=1 (lottery_rank 2 − total_seats 1
    = 1).

    Design: Difficulty/non_linear_state_machine/application_branching_lottery_run_produces_two_branches
    """
    set_clock("2026-01-01T00:00:00Z")
    district = create_district(code="DBR1B", name="BranchQR", poverty_index_pct=50.00)
    school = create_school(district["id"], code="SBR1B", name="BQR",
                           school_type="MAGNET", grade_min=0, grade_max=12,
                           total_seats=1)
    window = create_window(district["id"], cycle_label="2026-27-BR1B")
    fam_hi = register_family(district["id"], guardian_email="brb1@x.com",
                             residence_zone_code="ZBR", poverty_flag=True)
    fam_lo = register_family(district["id"], guardian_email="brb2@x.com",
                             residence_zone_code="ZBR", poverty_flag=False)
    stu_hi = create_student(fam_hi["id"], grade_for_cycle=4)
    stu_lo = create_student(fam_lo["id"], grade_for_cycle=4)
    set_clock("2026-01-03T00:00:00Z")
    open_window(window["id"])
    app_hi = create_application(fam_hi["id"], window["id"], stu_hi["id"],
                                school["id"], choice_rank=1)
    submit_application(fam_hi["id"], app_hi["id"])
    app_lo = create_application(fam_lo["id"], window["id"], stu_lo["id"],
                                school["id"], choice_rank=1)
    submit_application(fam_lo["id"], app_lo["id"])
    advance_window_to_lottery_run(window["id"])
    wls = list_waitlist_entries_for_application(app_lo["id"])
    assert len(wls) == 1
    assert wls[0]["queue_rank"] == 1, (
        f"First overflow waitlist entry must carry queue_rank=1; "
        f"got {wls[0]['queue_rank']!r}"
    )


# =====================================================================
# Difficulty rule 3 / instance 2 (companion) — window finalize as the
# alternative branch from LOTTERY_RUN, requires accepted offer; subsequent
# state demonstrates the FINALIZED terminal differently from CLOSED branch
# =====================================================================

def test_window_finalize_branch_produces_finalized_status(api):
    """PRD §3.2: "Finalization transitions the window from `LOTTERY_RUN` to
    `FINALIZED` and may proceed only when no application in this window is
    still in `OFFERED` status — that is, every offer has either been
    accepted, declined, or expired."

    Companion to the close→run branching test (the other side of the
    OPEN-fork on EnrollmentWindow): after a clean lottery run with the
    single offer accepted, the finalize call must succeed and the window's
    `status` becomes `FINALIZED`.

    Design: Difficulty/non_linear_state_machine/window_branching_run_lottery_or_close_to_finalize
    """
    set_clock("2026-01-01T00:00:00Z")
    district = create_district(code="DBR2B", name="Branch2B", poverty_index_pct=0.00)
    school = create_school(district["id"], code="SBR2B", name="S2B",
                           school_type="MAGNET", grade_min=0, grade_max=12,
                           total_seats=5)
    window = create_window(district["id"], cycle_label="2026-27-BR2B")
    family = register_family(district["id"], guardian_email="wbb@x.com",
                             residence_zone_code="ZBR2B", poverty_flag=False)
    student = create_student(family["id"], grade_for_cycle=5)
    set_clock("2026-01-03T00:00:00Z")
    open_window(window["id"])
    app = create_application(family["id"], window["id"], student["id"],
                             school["id"], choice_rank=1)
    submit_application(family["id"], app["id"])
    advance_window_to_lottery_run(window["id"])
    off = list_offers_for_application(app["id"], family_id=family["id"])[0]
    accept_offer_with_current_version(family["id"], off["id"])
    finalize_window(window["id"])
    w = get_window(window["id"])
    assert w["status"] == "FINALIZED", (
        f"Finalize-branch terminal must be FINALIZED; got {w['status']!r}"
    )


# =====================================================================
# Difficulty rule 4 / instance 1 (companion) — promoted entry's WaitlistEntry
# transitions ACTIVE → PROMOTED on decline cascade
# =====================================================================

def test_offer_decline_marks_promoted_waitlist_entry(api):
    """PRD §3.5: "Declination moves an `OFFERED` offer to `DECLINED`, advances
    the linked application from `ACCEPTED` to `DECLINED`, and triggers the
    waitlist-promotion cascade: the `ACTIVE` waitlist entry on the same
    school with the lowest `queue_rank` is selected, its linked application
    transitions from `WAITLISTED` to `ACCEPTED`, that waitlist entry's
    `status` becomes `PROMOTED`."

    Companion to the depth-3 cascade test: confirm the WaitlistEntry's
    own `status` field flips ACTIVE → PROMOTED.

    Design: Difficulty/transitive_cascade/offer_decline_promotes_waitlist_creates_new_offer_depth3
    """
    set_clock("2026-01-01T00:00:00Z")
    district = create_district(code="DCA1B", name="Cas1B", poverty_index_pct=50.00)
    school = create_school(district["id"], code="SCA1B", name="Cs1B",
                           school_type="MAGNET", grade_min=0, grade_max=12,
                           total_seats=1)
    window = create_window(district["id"], cycle_label="2026-27-CA1B")
    fam_a = register_family(district["id"], guardian_email="ca1b@x.com",
                            residence_zone_code="ZCA", poverty_flag=True)
    fam_b = register_family(district["id"], guardian_email="ca2b@x.com",
                            residence_zone_code="ZCA", poverty_flag=False)
    stu_a = create_student(fam_a["id"], grade_for_cycle=3)
    stu_b = create_student(fam_b["id"], grade_for_cycle=3)
    set_clock("2026-01-03T00:00:00Z")
    open_window(window["id"])
    app_a = create_application(fam_a["id"], window["id"], stu_a["id"],
                               school["id"], choice_rank=1)
    submit_application(fam_a["id"], app_a["id"])
    app_b = create_application(fam_b["id"], window["id"], stu_b["id"],
                               school["id"], choice_rank=1)
    submit_application(fam_b["id"], app_b["id"])
    advance_window_to_lottery_run(window["id"])
    wls_pre = list_waitlist_entries_for_application(app_b["id"])
    assert wls_pre[0]["status"] == "ACTIVE"
    wl_id = wls_pre[0]["id"]
    off = list_offers_for_application(app_a["id"], family_id=fam_a["id"])[0]
    decline_offer(fam_a["id"], off["id"])
    res = api.get_waitlist_entry(wl_id, TEST_USERS["district_admin_headers"])
    data = validate_success(res, 200)
    assert data["status"] == "PROMOTED", (
        f"Top ACTIVE WaitlistEntry must flip to PROMOTED on decline cascade; "
        f"got {data['status']!r}"
    )


# =====================================================================
# Difficulty rule 4 / instance 2 (companion) — finalize bumps window version
# =====================================================================

def test_window_finalize_increments_window_version(api):
    """PRD §2.4: "The `version` field is an integer that begins at 1 on
    creation and increments by exactly one each time the row is mutated;
    it is the parent token consulted by optimistic concurrency control."
    PRD §2.7: "Every cascaded mutation bumps the affected row's `version`
    by one (except `WaitlistEntry`, which has no version field) and
    refreshes its `updated_at`."

    Companion to the finalize→waitlist-cascade test: after finalize, the
    window's version must have advanced.

    Design: Difficulty/transitive_cascade/window_finalize_cascades_waitlist_to_removed_then_apps_to_withdrawn_depth2
    """
    set_clock("2026-01-01T00:00:00Z")
    district = create_district(code="DCA2B", name="Cas2B", poverty_index_pct=25.00)
    school = create_school(district["id"], code="SCA2B", name="Cs2B",
                           school_type="MAGNET", grade_min=0, grade_max=12,
                           total_seats=1)
    window = create_window(district["id"], cycle_label="2026-27-CA2B")
    family = register_family(district["id"], guardian_email="fz1b@x.com",
                             residence_zone_code="ZF", poverty_flag=True)
    student = create_student(family["id"], grade_for_cycle=4)
    set_clock("2026-01-03T00:00:00Z")
    open_window(window["id"])
    app = create_application(family["id"], window["id"], student["id"],
                             school["id"], choice_rank=1)
    submit_application(family["id"], app["id"])
    advance_window_to_lottery_run(window["id"])
    off = list_offers_for_application(app["id"], family_id=family["id"])[0]
    accept_offer_with_current_version(family["id"], off["id"])
    w_pre = get_window(window["id"])
    v_pre = w_pre["version"]
    finalize_window(window["id"])
    w_post = get_window(window["id"])
    assert w_post["version"] > v_pre, (
        f"Finalize must increment window.version; was {v_pre}, "
        f"got {w_post['version']}"
    )
    assert w_post["status"] == "FINALIZED"


# =====================================================================
# Difficulty rule 5 / instance 1 (companion) — confirm window unchanged
# after the rejected run-lottery (no side effects from the failed call)
# =====================================================================

def test_failed_run_lottery_leaves_window_state_and_version_unchanged(api):
    """PRD §2.4: "If the value does not match (typically because another
    administrator has already advanced the window through close-or-run
    since the client last read it), the request is rejected with
    `ERR_STALE_VERSION` and HTTP 412, and no lottery is run."

    Companion to the state-vs-temporal precedence test: when the priority-4
    state check rejects a run-lottery call, the window's own state and
    version must be unchanged (the rejection is a no-op).

    Design: Difficulty/priority_pair_validation_conflict/state_vs_business_temporal_run_lottery_before_lottery_runs_at
    """
    set_clock("2026-01-01T00:00:00Z")
    district = create_district(code="DPRI1B", name="Prio1B", poverty_index_pct=0.00)
    window = create_window(district["id"], cycle_label="2026-27-PRI1B")
    set_clock("2026-01-03T00:00:00Z")
    open_window(window["id"])
    w_before = get_window(window["id"])
    res = api.run_lottery(
        window["id"],
        run_lottery_payload(w_before["version"]),
        TEST_USERS["district_admin_headers"],
    )
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)
    w_after = get_window(window["id"])
    assert w_after["status"] == "OPEN", (
        f"Rejected run-lottery must leave window status unchanged at OPEN; "
        f"got {w_after['status']!r}"
    )
    assert w_after["version"] == w_before["version"], (
        f"Rejected run-lottery must NOT bump window version; "
        f"was {w_before['version']}, got {w_after['version']}"
    )


# =====================================================================
# Difficulty rule 5 / instance 2 (companion) — confirm no Application
# row was created by the rejected request
# =====================================================================

def test_failed_create_application_for_other_familys_student_creates_no_row(api):
    """PRD §2.1: "a guardian who attempts to submit, withdraw, accept, or
    decline on behalf of another family's student is rejected with
    `ERR_FORBIDDEN_OWNERSHIP` and HTTP 403."

    Companion to the ownership-vs-duplicate-choice precedence test: after
    the rejected POST /lottery/applications, the targeted student must
    have zero applications in this window — the rejection truly did not
    persist.

    Design: Difficulty/priority_pair_validation_conflict/business_referential_vs_business_constraint_apply_for_other_family_with_duplicate
    """
    set_clock("2026-01-01T00:00:00Z")
    district = create_district(code="DPRI2B", name="Prio2B", poverty_index_pct=0.00)
    school = create_school(district["id"], code="SPRI2B", name="P2Bs",
                           school_type="MAGNET", grade_min=0, grade_max=12,
                           total_seats=3)
    window = create_window(district["id"], cycle_label="2026-27-PRI2B")
    fam_a = register_family(district["id"], guardian_email="pab@x.com",
                            residence_zone_code="ZPRIB", poverty_flag=False)
    fam_b = register_family(district["id"], guardian_email="pbb@x.com",
                            residence_zone_code="ZPRIB", poverty_flag=False)
    stu_b = create_student(fam_b["id"], grade_for_cycle=7)
    set_clock("2026-01-03T00:00:00Z")
    open_window(window["id"])
    payload = create_application_payload(window["id"], stu_b["id"], school["id"],
                                         choice_rank=1)
    res = api.create_application(payload, make_guardian_headers(fam_a["id"]))
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP.value)
    # Confirm zero applications exist for stu_b in this window.
    list_res = api.list_applications(
        TEST_USERS["district_admin_headers"],
        params={"window_id": window["id"], "student_id": stu_b["id"]},
    )
    body = list_res.json()
    total = body["meta"].get("total_count")
    if total is None:
        total = len(body.get("data", []))
    assert total == 0, (
        f"Rejected request must not persist any application; "
        f"got total_count={total}"
    )


# =====================================================================
# Difficulty rule 6 / instance 2 (companion) — total_seats=10 yields IDT
# cap of 1; one IDT applicant may now be accepted
# =====================================================================

def test_idt_cap_at_total_seats_ten_yields_one_admit(api):
    """PRD §3.6: "the count of accepted applications whose
    `inter_district_transfer` would be true (because the application's
    school district differs from the family's residence district) may not
    exceed the inter-district-transfer cap, computed as the floor of 0.10
    multiplied by the school's `total_seats`."

    Companion to the floor-at-nine-yields-zero test: at total_seats=10,
    floor(0.10*10)=1, so one IDT applicant is allowed in. With one IDT
    and one in-district applicant, both are ACCEPTED.

    Design: Difficulty/boundary_precision_check/idt_cap_floor_boundary_at_total_seats_nine_yields_zero
    """
    set_clock("2026-01-01T00:00:00Z")
    host = create_district(code="D10HOST", name="Host10", poverty_index_pct=0.00)
    src = create_district(code="D10SRC", name="Src10", poverty_index_pct=100.00)
    school = create_school(host["id"], code="SN10", name="Ten",
                           school_type="MAGNET", grade_min=0, grade_max=12,
                           total_seats=10)
    window = create_window(host["id"], cycle_label="2026-27-N10")
    fam_idt = register_family(src["id"], guardian_email="n10-idt@x.com",
                              residence_zone_code="ZIDT10", poverty_flag=True)
    fam_in = register_family(host["id"], guardian_email="n10-in@x.com",
                             residence_zone_code="ZIN10", poverty_flag=False)
    stu_idt = create_student(fam_idt["id"], grade_for_cycle=2)
    stu_in = create_student(fam_in["id"], grade_for_cycle=3)
    set_clock("2026-01-03T00:00:00Z")
    open_window(window["id"])
    app_idt = create_application(fam_idt["id"], window["id"], stu_idt["id"],
                                 school["id"], choice_rank=1)
    submit_application(fam_idt["id"], app_idt["id"])
    app_in = create_application(fam_in["id"], window["id"], stu_in["id"],
                                school["id"], choice_rank=1)
    submit_application(fam_in["id"], app_in["id"])
    advance_window_to_lottery_run(window["id"])
    assert get_application(app_idt["id"])["status"] == "ACCEPTED", (
        "At total_seats=10 the IDT cap is 1, so the one IDT applicant "
        "must be ACCEPTED"
    )
    assert get_application(app_in["id"])["status"] == "ACCEPTED"


# =====================================================================
# Difficulty rule 7 / instance 2 (companion) — accept on an OFFERED offer
# whose linked Application has been driven out of ACCEPTED by withdrawal
# of the linked application is no-op; here we use the simpler case where
# the offer was already accepted once, and the SECOND accept on the same
# now-ACCEPTED offer fails with ERR_INVALID_STATE (Offer no longer OFFERED).
# =====================================================================

def test_second_accept_on_already_accepted_offer_returns_invalid_state(api):
    """PRD §3.5: "Acceptance moves an `OFFERED` offer to `ACCEPTED` and, in
    the same atomic mutation, advances the linked application from
    `ACCEPTED` to `ENROLLED`; the request must carry `expected_offer_version`
    matching the offer's current `version` (rejected with `ERR_STALE_VERSION`
    if not) and may not proceed once the clock has reached `respond_by`
    (rejected with `ERR_INVALID_STATE`)."
    PRD §2.6: "the resource state for state-transition endpoints" is
    checked before "optimistic-concurrency version checks".

    Once an offer is ACCEPTED, its status is no longer OFFERED. A second
    accept call — even with the fresh expected_offer_version — must be
    rejected with ERR_INVALID_STATE.

    Design: Difficulty/cross_entity_state_dependency/offer_accept_requires_application_accepted_and_offer_offered
    """
    set_clock("2026-01-01T00:00:00Z")
    district = create_district(code="DXE2B", name="Xe2B", poverty_index_pct=0.00)
    school = create_school(district["id"], code="SXE2B", name="X2B",
                           school_type="MAGNET", grade_min=0, grade_max=12,
                           total_seats=5)
    window = create_window(district["id"], cycle_label="2026-27-XE2B")
    family = register_family(district["id"], guardian_email="xe2b@x.com",
                             residence_zone_code="ZXE2B", poverty_flag=False)
    student = create_student(family["id"], grade_for_cycle=5)
    set_clock("2026-01-03T00:00:00Z")
    open_window(window["id"])
    app = create_application(family["id"], window["id"], student["id"],
                             school["id"], choice_rank=1)
    submit_application(family["id"], app["id"])
    advance_window_to_lottery_run(window["id"])
    off = list_offers_for_application(app["id"], family_id=family["id"])[0]
    accept_offer_with_current_version(family["id"], off["id"])
    # Read post-accept version and attempt second accept.
    res_off = api.get_offer(off["id"], make_guardian_headers(family["id"]))
    post = validate_success(res_off, 200)
    res = api.accept_offer(
        off["id"],
        accept_offer_payload(post["version"]),
        make_guardian_headers(family["id"]),
    )
    err = validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)
    assert err["error_id"] == ApiErrorId.ERR_INVALID_STATE.value


# =====================================================================
# Difficulty rule 8 / instance 2 (companion) — Offer.accept BEFORE
# respond_by succeeds (the boundary's accept-side)
# =====================================================================

def test_accept_offer_before_respond_by_succeeds(api):
    """PRD §3.5: "Acceptance moves an `OFFERED` offer to `ACCEPTED` and, in
    the same atomic mutation, advances the linked application from
    `ACCEPTED` to `ENROLLED`; the request must carry `expected_offer_version`
    matching the offer's current `version` (rejected with `ERR_STALE_VERSION`
    if not) and may not proceed once the clock has reached `respond_by`
    (rejected with `ERR_INVALID_STATE`)."

    Companion to the at-respond_by rejection test: when the clock is well
    BEFORE respond_by, the accept call succeeds and the application
    transitions from ACCEPTED to ENROLLED.

    Design: Difficulty/resource_temporal_overlap/offer_accept_after_respond_by_deadline_strict_less_than
    """
    set_clock("2026-01-01T00:00:00Z")
    district = create_district(code="DTO2B", name="Ov2B", poverty_index_pct=0.00)
    school = create_school(district["id"], code="STO2B", name="Ov2Bs",
                           school_type="MAGNET", grade_min=0, grade_max=12,
                           total_seats=5)
    window = create_window(district["id"], cycle_label="2026-27-TO2B")
    family = register_family(district["id"], guardian_email="to2b@x.com",
                             residence_zone_code="ZTO2B", poverty_flag=False)
    student = create_student(family["id"], grade_for_cycle=5)
    set_clock("2026-01-03T00:00:00Z")
    open_window(window["id"])
    app = create_application(family["id"], window["id"], student["id"],
                             school["id"], choice_rank=1)
    submit_application(family["id"], app["id"])
    advance_window_to_lottery_run(window["id"])
    off = list_offers_for_application(app["id"], family_id=family["id"])[0]
    # Stay before respond_by (= 2026-02-09); clock is 2026-02-02 after run.
    accept_offer_with_current_version(family["id"], off["id"])
    after = get_application(app["id"])
    assert after["status"] == "ENROLLED", (
        f"Accept before respond_by must move Application to ENROLLED; "
        f"got {after['status']!r}"
    )


# =====================================================================
# Difficulty rule 9 / instance 1 (companion) — assignment is total: no
# application remains in SUBMITTED after the partition fires
# =====================================================================

def test_no_application_remains_in_submitted_after_lottery_run(api):
    """PRD §2.7: "the lottery-weight calculation runs over every `SUBMITTED`
    application in the window, the seat-assignment calculation partitions
    per-school applications into accepted and waitlisted sets, each accepted
    application transitions from `SUBMITTED` to `ACCEPTED` with a freshly
    created `Offer` whose `source` is `LOTTERY`, and each overflow
    application transitions from `SUBMITTED` to `WAITLISTED` with a freshly
    created `WaitlistEntry` whose `status` is `ACTIVE`."

    Companion to the 2+2 conservation test: the partition is total in a
    stronger sense — after lottery-run, the count of Applications in this
    window still in SUBMITTED status is zero.

    Design: Difficulty/compensating_invariant/seat_conservation_total_accepted_plus_waitlisted_equals_submitted
    """
    set_clock("2026-01-01T00:00:00Z")
    district = create_district(code="DSCB", name="ConsB", poverty_index_pct=50.00)
    school = create_school(district["id"], code="SSCB", name="CsB",
                           school_type="MAGNET", grade_min=0, grade_max=12,
                           total_seats=2)
    window = create_window(district["id"], cycle_label="2026-27-SCB")
    family = register_family(district["id"], guardian_email="scb@x.com",
                             residence_zone_code="ZSCB", poverty_flag=False)
    set_clock("2026-01-03T00:00:00Z")
    open_window(window["id"])
    for i in range(4):
        stu = create_student(family["id"], full_name=f"SB{i}",
                             grade_for_cycle=i + 1)
        a = create_application(family["id"], window["id"], stu["id"],
                               school["id"], choice_rank=i + 1)
        submit_application(family["id"], a["id"])
    advance_window_to_lottery_run(window["id"])
    res = api.list_applications(
        TEST_USERS["district_admin_headers"],
        params={"window_id": window["id"], "status": "SUBMITTED"},
    )
    body = res.json()
    total = body["meta"].get("total_count")
    if total is None:
        total = len(body.get("data", []))
    assert total == 0, (
        f"No application may remain in SUBMITTED after lottery-run; "
        f"got total_count={total}"
    )


# =====================================================================
# Difficulty rule 9 / instance 2 (companion) — the new promotion offer
# carries source=WAITLIST_PROMOTION (offer-side of the conservation step)
# =====================================================================

def test_promotion_offer_after_decline_has_source_waitlist_promotion(api):
    """PRD §3.5: "a new offer is minted with `source` set to
    `WAITLIST_PROMOTION` and `respond_by` set to seven days after the
    cascade instant."

    Companion to the school-ACCEPTED-count conservation test: focus on the
    offer side — after the decline+promote step, the promoted application
    must have exactly one new Offer with source='WAITLIST_PROMOTION'.

    Design: Difficulty/compensating_invariant/offer_count_invariant_after_decline_promote_one_in_one_out
    """
    set_clock("2026-01-01T00:00:00Z")
    district = create_district(code="DCI2B", name="Inv2B", poverty_index_pct=0.00)
    school = create_school(district["id"], code="SCI2B", name="CsB",
                           school_type="MAGNET", grade_min=0, grade_max=12,
                           total_seats=1)
    window = create_window(district["id"], cycle_label="2026-27-CI2B")
    fam_a = register_family(district["id"], guardian_email="ciab@x.com",
                            residence_zone_code="ZCIB", poverty_flag=True)
    fam_b = register_family(district["id"], guardian_email="cibb@x.com",
                            residence_zone_code="ZCIB", poverty_flag=False)
    stu_a = create_student(fam_a["id"], grade_for_cycle=3)
    stu_b = create_student(fam_b["id"], grade_for_cycle=3)
    set_clock("2026-01-03T00:00:00Z")
    open_window(window["id"])
    app_a = create_application(fam_a["id"], window["id"], stu_a["id"],
                               school["id"], choice_rank=1)
    submit_application(fam_a["id"], app_a["id"])
    app_b = create_application(fam_b["id"], window["id"], stu_b["id"],
                               school["id"], choice_rank=1)
    submit_application(fam_b["id"], app_b["id"])
    advance_window_to_lottery_run(window["id"])
    off_a = list_offers_for_application(app_a["id"], family_id=fam_a["id"])[0]
    decline_offer(fam_a["id"], off_a["id"])
    promo = list_offers_for_application(app_b["id"], family_id=fam_b["id"],
                                        source="WAITLIST_PROMOTION")
    assert len(promo) == 1, (
        f"Decline cascade must mint exactly one source=WAITLIST_PROMOTION "
        f"Offer for the promoted application; got {promo!r}"
    )
    assert promo[0]["status"] == "OFFERED"
