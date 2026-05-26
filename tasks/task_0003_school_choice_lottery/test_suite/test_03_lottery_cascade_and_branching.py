"""Tests for the multi-hop cascades fired by lottery-run, offer-decline, and
window-finalize transitions (PRD §2.7, §3.5), plus the branching shape of
applications across the SUBMITTED → ACCEPTED / WAITLISTED fork and of
EnrollmentWindow across OPEN → CLOSED / CLOSED → LOTTERY_RUN.
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
    run_lottery_with_current_version,
    get_application,
    list_offers_for_application,
    list_waitlist_entries_for_application,
    list_waitlist_entries_for_school,
    decline_offer,
    accept_offer_with_current_version,
    finalize_window,
    TEST_USERS,
    make_guardian_headers,
)


# =====================================================================
# Difficulty rule 3 / instance 1 — Application SUBMITTED branches to
# either ACCEPTED+Offer or WAITLISTED+WaitlistEntry under one trigger.
# =====================================================================

def test_lottery_run_branches_application_into_accepted_and_waitlisted(api):
    """PRD §2.7: "each accepted application transitions from `SUBMITTED` to
    `ACCEPTED` with a freshly created `Offer` whose `source` is `LOTTERY`,
    and each overflow application transitions from `SUBMITTED` to
    `WAITLISTED` with a freshly created `WaitlistEntry` whose `status` is
    `ACTIVE`."

    School total_seats=1 with two SUBMITTED apps; the higher-weighted app
    (poverty_flag=true → +0.200) is ACCEPTED with an Offer(source=LOTTERY);
    the lower-weighted app is WAITLISTED with an ACTIVE WaitlistEntry.

    Design: Difficulty/non_linear_state_machine/application_branching_lottery_run_produces_two_branches
    """
    set_clock("2026-01-01T00:00:00Z")
    district = create_district(code="DBR1", name="Branch", poverty_index_pct=50.00)
    school = create_school(district["id"], code="SBR1", name="Branchy",
                           school_type="MAGNET", grade_min=0, grade_max=12,
                           total_seats=1)
    window = create_window(district["id"], cycle_label="2026-27-BR1")
    fam_hi = register_family(district["id"], guardian_email="br1@x.com",
                             residence_zone_code="ZBR", poverty_flag=True)
    fam_lo = register_family(district["id"], guardian_email="br2@x.com",
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
    app_hi = get_application(app_hi["id"])
    app_lo = get_application(app_lo["id"])
    assert app_hi["status"] == "ACCEPTED"
    assert app_lo["status"] == "WAITLISTED"
    offers_hi = list_offers_for_application(app_hi["id"], family_id=fam_hi["id"])
    assert len(offers_hi) == 1, (
        f"ACCEPTED application must have exactly one Offer; got {offers_hi!r}"
    )
    assert offers_hi[0]["source"] == "LOTTERY", (
        f"Offer source must be 'LOTTERY' for accepted lottery branch; "
        f"got {offers_hi[0]['source']!r}"
    )
    assert offers_hi[0]["status"] == "OFFERED"
    wl_lo = list_waitlist_entries_for_application(app_lo["id"])
    assert len(wl_lo) == 1, (
        f"WAITLISTED application must have exactly one WaitlistEntry; got {wl_lo!r}"
    )
    assert wl_lo[0]["status"] == "ACTIVE"


# =====================================================================
# Difficulty rule 3 / instance 2 — EnrollmentWindow branches from OPEN
# into two distinct side-effect sets: close (DRAFT auto-withdraw) vs
# run-lottery (per-school partition).
# =====================================================================

def test_window_close_then_run_lottery_executes_both_branch_cascades(api):
    """PRD §3.2: "On close, every application in `DRAFT` for this window
    cascades to `WITHDRAWN`."
    PRD §2.7: "each accepted application transitions from `SUBMITTED` to
    `ACCEPTED` with a freshly created `Offer` whose `source` is `LOTTERY`,
    and each overflow application transitions from `SUBMITTED` to
    `WAITLISTED` with a freshly created `WaitlistEntry` whose `status` is
    `ACTIVE`."

    OPEN window holding one SUBMITTED app and one DRAFT app. The close
    transition auto-withdraws the DRAFT; the SUBMITTED is untouched. After
    close + clock advance + run-lottery, the SUBMITTED app becomes ACCEPTED.

    Design: Difficulty/non_linear_state_machine/window_branching_run_lottery_or_close_to_finalize
    """
    set_clock("2026-01-01T00:00:00Z")
    district = create_district(code="DBR2", name="Branch2", poverty_index_pct=0.00)
    school = create_school(district["id"], code="SBR2", name="S2",
                           school_type="MAGNET", grade_min=0, grade_max=12,
                           total_seats=5)
    window = create_window(district["id"], cycle_label="2026-27-BR2")
    family = register_family(district["id"], guardian_email="wb@x.com",
                             residence_zone_code="ZBR2", poverty_flag=False)
    stu_sub = create_student(family["id"], full_name="Sub", grade_for_cycle=5)
    stu_draft = create_student(family["id"], full_name="Draft", grade_for_cycle=5)
    set_clock("2026-01-03T00:00:00Z")
    open_window(window["id"])
    app_sub = create_application(family["id"], window["id"], stu_sub["id"],
                                 school["id"], choice_rank=1)
    submit_application(family["id"], app_sub["id"])
    app_draft = create_application(family["id"], window["id"], stu_draft["id"],
                                   school["id"], choice_rank=2)
    # Intentionally NOT submitted — left in DRAFT to be auto-withdrawn on close.
    advance_window_to_closed(window["id"])
    after_close_draft = get_application(app_draft["id"])
    after_close_sub = get_application(app_sub["id"])
    assert after_close_draft["status"] == "WITHDRAWN", (
        f"Close cascade must auto-withdraw DRAFT apps; "
        f"got {after_close_draft['status']!r}"
    )
    assert after_close_sub["status"] == "SUBMITTED", (
        f"SUBMITTED apps must survive the close cascade; "
        f"got {after_close_sub['status']!r}"
    )
    # Window already CLOSED above; do not re-close. Just advance the clock
    # past lottery_runs_at and trigger run-lottery directly.
    set_clock("2026-02-02T00:00:00Z")
    run_lottery_with_current_version(window["id"])
    after_run = get_application(app_sub["id"])
    assert after_run["status"] == "ACCEPTED", (
        f"Surviving SUBMITTED app must move to ACCEPTED via the run-lottery "
        f"branch; got {after_run['status']!r}"
    )


# =====================================================================
# Difficulty rule 4 / instance 1 — offer decline → waitlist promotion →
# new offer creation: depth-3 cascade from a Guardian-initiated trigger
# =====================================================================

def test_offer_decline_promotes_waitlist_and_mints_new_offer(api):
    """PRD §3.5: "Declination moves an `OFFERED` offer to `DECLINED`, advances
    the linked application from `ACCEPTED` to `DECLINED`, and triggers the
    waitlist-promotion cascade: the `ACTIVE` waitlist entry on the same
    school with the lowest `queue_rank` is selected, its linked application
    transitions from `WAITLISTED` to `ACCEPTED`, that waitlist entry's
    `status` becomes `PROMOTED`, a new offer is minted with `source` set to
    `WAITLIST_PROMOTION` and `respond_by` set to seven days after the cascade
    instant, and every remaining `ACTIVE` waitlist entry on the same school
    has its `queue_rank` decremented by one."

    Design: Difficulty/transitive_cascade/offer_decline_promotes_waitlist_creates_new_offer_depth3
    """
    set_clock("2026-01-01T00:00:00Z")
    district = create_district(code="DCA1", name="Cas1", poverty_index_pct=50.00)
    school = create_school(district["id"], code="SCA1", name="Cas1s",
                           school_type="MAGNET", grade_min=0, grade_max=12,
                           total_seats=1)
    window = create_window(district["id"], cycle_label="2026-27-CA1")
    fam_a = register_family(district["id"], guardian_email="ca1@x.com",
                            residence_zone_code="ZCA", poverty_flag=True)
    fam_b = register_family(district["id"], guardian_email="ca2@x.com",
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
    # A is ACCEPTED with an OFFERED lottery offer; B is WAITLISTED.
    offers_a = list_offers_for_application(app_a["id"], family_id=fam_a["id"])
    assert len(offers_a) == 1
    off_a = offers_a[0]
    # Trigger: Guardian declines A's offer → cascade fires.
    decline_offer(fam_a["id"], off_a["id"])
    app_a = get_application(app_a["id"])
    app_b = get_application(app_b["id"])
    assert app_a["status"] == "DECLINED", (
        f"Declined offer must cascade Application A to DECLINED; "
        f"got {app_a['status']!r}"
    )
    assert app_b["status"] == "ACCEPTED", (
        f"Top WAITLISTED application must be promoted to ACCEPTED; "
        f"got {app_b['status']!r}"
    )
    # A new offer for B with source=WAITLIST_PROMOTION must exist.
    promo_offers = list_offers_for_application(
        app_b["id"], family_id=fam_b["id"], source="WAITLIST_PROMOTION"
    )
    assert len(promo_offers) == 1, (
        f"Waitlist promotion must mint exactly one new Offer "
        f"with source=WAITLIST_PROMOTION; got {promo_offers!r}"
    )
    assert promo_offers[0]["status"] == "OFFERED"


# =====================================================================
# Difficulty rule 4 / instance 2 — window finalize cascades waitlist
# entries to REMOVED and their WAITLISTED applications to WITHDRAWN
# =====================================================================

def test_window_finalize_cascades_waitlist_to_removed_and_app_to_withdrawn(api):
    """PRD §3.2: "Finalization transitions the window from `LOTTERY_RUN` to
    `FINALIZED` and may proceed only when no application in this window is
    still in `OFFERED` status — that is, every offer has either been
    accepted, declined, or expired. The transition cascades active waitlist
    entries on this window's schools to `REMOVED`, and any still-`WAITLISTED`
    application linked to one of those removed entries cascades to
    `WITHDRAWN`."

    Setup: window finished lottery, accepted offer is ACCEPTED (so finalize's
    "no OFFERED" precondition holds), and one WAITLISTED app remains. After
    finalize, that WaitlistEntry becomes REMOVED and its app becomes
    WITHDRAWN.

    Design: Difficulty/transitive_cascade/window_finalize_cascades_waitlist_to_removed_then_apps_to_withdrawn_depth2
    """
    set_clock("2026-01-01T00:00:00Z")
    district = create_district(code="DCA2", name="Cas2", poverty_index_pct=25.00)
    school = create_school(district["id"], code="SCA2", name="Cas2s",
                           school_type="MAGNET", grade_min=0, grade_max=12,
                           total_seats=1)
    window = create_window(district["id"], cycle_label="2026-27-CA2")
    fam_acc = register_family(district["id"], guardian_email="fz1@x.com",
                              residence_zone_code="ZF", poverty_flag=True)
    fam_wl = register_family(district["id"], guardian_email="fz2@x.com",
                             residence_zone_code="ZF", poverty_flag=False)
    stu_acc = create_student(fam_acc["id"], grade_for_cycle=4)
    stu_wl = create_student(fam_wl["id"], grade_for_cycle=4)
    set_clock("2026-01-03T00:00:00Z")
    open_window(window["id"])
    app_acc = create_application(fam_acc["id"], window["id"], stu_acc["id"],
                                 school["id"], choice_rank=1)
    submit_application(fam_acc["id"], app_acc["id"])
    app_wl = create_application(fam_wl["id"], window["id"], stu_wl["id"],
                                school["id"], choice_rank=1)
    submit_application(fam_wl["id"], app_wl["id"])
    advance_window_to_lottery_run(window["id"])
    # Accept the OFFERED offer so finalize's precondition (no OFFERED) holds.
    offers_acc = list_offers_for_application(app_acc["id"], family_id=fam_acc["id"])
    accept_offer_with_current_version(fam_acc["id"], offers_acc[0]["id"])
    # Capture the waitlist entry id before finalize.
    wls = list_waitlist_entries_for_application(app_wl["id"])
    assert len(wls) == 1 and wls[0]["status"] == "ACTIVE"
    wl_id = wls[0]["id"]
    finalize_window(window["id"])
    # Re-read the waitlist entry and waitlisted app.
    res_wl = api.get_waitlist_entry(wl_id, TEST_USERS["district_admin_headers"])
    body = res_wl.json()
    wl_after = body["data"]
    assert wl_after["status"] == "REMOVED", (
        f"Finalize cascade must transition ACTIVE waitlist entries to REMOVED; "
        f"got {wl_after['status']!r}"
    )
    after_app_wl = get_application(app_wl["id"])
    assert after_app_wl["status"] == "WITHDRAWN", (
        f"Waitlisted application linked to a removed entry must be WITHDRAWN; "
        f"got {after_app_wl['status']!r}"
    )


# =====================================================================
# Difficulty rule 9 / instance 2 — decline+promote conserves the
# per-school ACCEPTED count (1 out, 1 in).
# =====================================================================

def test_decline_promote_preserves_school_accepted_count(api):
    """PRD §3.5: "Declination moves an `OFFERED` offer to `DECLINED`, advances
    the linked application from `ACCEPTED` to `DECLINED`, and triggers the
    waitlist-promotion cascade: the `ACTIVE` waitlist entry on the same
    school with the lowest `queue_rank` is selected, its linked application
    transitions from `WAITLISTED` to `ACCEPTED`, that waitlist entry's
    `status` becomes `PROMOTED`, a new offer is minted with `source` set to
    `WAITLIST_PROMOTION` and `respond_by` set to seven days after the cascade
    instant, and every remaining `ACTIVE` waitlist entry on the same school
    has its `queue_rank` decremented by one."

    Per-school ACCEPTED count is conserved: 1 ACCEPTED before decline, 1
    ACCEPTED after decline+promote.

    Design: Difficulty/compensating_invariant/offer_count_invariant_after_decline_promote_one_in_one_out
    """
    set_clock("2026-01-01T00:00:00Z")
    district = create_district(code="DCI2", name="Inv2", poverty_index_pct=0.00)
    school = create_school(district["id"], code="SCI2", name="Cis",
                           school_type="MAGNET", grade_min=0, grade_max=12,
                           total_seats=1)
    window = create_window(district["id"], cycle_label="2026-27-CI2")
    fam_a = register_family(district["id"], guardian_email="cia@x.com",
                            residence_zone_code="ZCI", poverty_flag=True)
    fam_b = register_family(district["id"], guardian_email="cib@x.com",
                            residence_zone_code="ZCI", poverty_flag=False)
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
    # Pre-decline: count of ACCEPTED for this school must be 1.
    res_before = api.list_applications(
        TEST_USERS["district_admin_headers"],
        params={"school_id": school["id"], "status": "ACCEPTED"},
    )
    before_count = res_before.json()["meta"].get("total_count")
    if before_count is None:
        before_count = len(res_before.json().get("data", []))
    assert before_count == 1, (
        f"School should have exactly 1 ACCEPTED app before decline; "
        f"got {before_count}"
    )
    offers_a = list_offers_for_application(app_a["id"], family_id=fam_a["id"])
    decline_offer(fam_a["id"], offers_a[0]["id"])
    # Post-decline+promote: ACCEPTED count must still be 1.
    res_after = api.list_applications(
        TEST_USERS["district_admin_headers"],
        params={"school_id": school["id"], "status": "ACCEPTED"},
    )
    after_count = res_after.json()["meta"].get("total_count")
    if after_count is None:
        after_count = len(res_after.json().get("data", []))
    assert after_count == 1, (
        f"Conservation: ACCEPTED count for school must remain 1 after "
        f"decline+promote (1 out, 1 in); got {after_count}"
    )
    assert get_application(app_a["id"])["status"] == "DECLINED"
    assert get_application(app_b["id"])["status"] == "ACCEPTED"
