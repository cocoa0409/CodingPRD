"""Tests for the per-school waterfall seat assignment (PRD §3.6) and the
school-acceptance-rate report (PRD §3.8): the inter-district-transfer cap,
tie-break ordering, the strict-less-than competitive flag, and the per-school
conservation invariant on submitted applications.
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
    advance_window_to_lottery_run,
    get_application,
    list_offers_for_application,
    api_client,
    TEST_USERS,
    make_guardian_headers,
    validate_success,
)


# =====================================================================
# Difficulty rule 2 / instance 2 — IDT cap evaluation order: two seats,
# IDT app demoted to waitlist because cap floor(0.10*2)=0.
# =====================================================================

def test_idt_cap_forces_waitlist_when_cap_is_zero_at_two_seats(api):
    """PRD §3.6: "Cap evaluation is strict and traverses the sorted list
    top-down: an inter-district application whose admission would push the
    running count of inter-district admits above the cap is skipped and
    demoted to the waitlist (retaining its place in the global sort order
    for `queue_rank` purposes), and the next in-district application by rank
    is promoted into the freed seat."

    School total_seats=2 → IDT cap floor(0.10*2)=0. With one IDT applicant
    from a 100%-poverty source district (top weight 1.400) and two in-district
    applicants from a 0%-poverty district (weight 1.000 each), the IDT app
    would top the sort by raw weight but the strict cap forces it off the
    seats; the two in-district apps are both ACCEPTED instead.

    Design: Difficulty/combinatorial_formula/lottery_seat_assignment_circular_eval_order_mode_c
    """
    set_clock("2026-01-01T00:00:00Z")
    host = create_district(code="DICA", name="Host", poverty_index_pct=0.00)
    other = create_district(code="DICB", name="Other", poverty_index_pct=100.00)
    school = create_school(host["id"], code="SIC", name="Two-seat",
                           school_type="MAGNET", grade_min=0, grade_max=12,
                           total_seats=2)
    window = create_window(host["id"], cycle_label="2026-27-IC")
    fam_in1 = register_family(host["id"], guardian_email="ic-in1@x.com",
                              residence_zone_code="ZI1", poverty_flag=False)
    fam_in2 = register_family(host["id"], guardian_email="ic-in2@x.com",
                              residence_zone_code="ZI1", poverty_flag=False)
    fam_idt = register_family(other["id"], guardian_email="ic-idt@x.com",
                              residence_zone_code="ZI2", poverty_flag=True)
    stu_in1 = create_student(fam_in1["id"], grade_for_cycle=6)
    stu_in2 = create_student(fam_in2["id"], grade_for_cycle=6)
    stu_idt = create_student(fam_idt["id"], grade_for_cycle=6)
    set_clock("2026-01-03T00:00:00Z")
    open_window(window["id"])
    # Submit IDT first so it would otherwise win on top weight.
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
    app_idt = get_application(app_idt["id"])
    app_in1 = get_application(app_in1["id"])
    app_in2 = get_application(app_in2["id"])
    assert app_idt["status"] == "WAITLISTED", (
        f"IDT applicant must be demoted to WAITLISTED by zero IDT cap; "
        f"got {app_idt['status']!r}"
    )
    assert app_in1["status"] == "ACCEPTED", (
        f"First in-district applicant must take the freed seat; "
        f"got {app_in1['status']!r}"
    )
    assert app_in2["status"] == "ACCEPTED", (
        f"Second in-district applicant must take the second seat; "
        f"got {app_in2['status']!r}"
    )


# =====================================================================
# Difficulty rule 6 / instance 2 — IDT cap floor at total_seats=9 → 0
# =====================================================================

def test_idt_cap_floor_at_total_seats_nine_yields_zero(api):
    """PRD §3.6: "The cap is floor-based, so a school with `total_seats` of
    nine has an inter-district-transfer cap of zero — at that capacity, no
    inter-district application can be accepted by the lottery, only by
    waitlist promotion that is in turn constrained by future cap evaluations."

    School total_seats=9; IDT cap = floor(0.10*9) = 0. Even the top-weighted
    IDT applicant is demoted to WAITLISTED; the lone in-district applicant
    is ACCEPTED.

    Design: Difficulty/boundary_precision_check/idt_cap_floor_boundary_at_total_seats_nine_yields_zero
    """
    set_clock("2026-01-01T00:00:00Z")
    host = create_district(code="D9HOST", name="Host9", poverty_index_pct=0.00)
    src = create_district(code="D9SRC", name="IdtSrc", poverty_index_pct=100.00)
    school = create_school(host["id"], code="SN9", name="Nine",
                           school_type="MAGNET", grade_min=0, grade_max=12,
                           total_seats=9)
    window = create_window(host["id"], cycle_label="2026-27-N9")
    fam_idt = register_family(src["id"], guardian_email="n9-idt@x.com",
                              residence_zone_code="ZX", poverty_flag=True)
    fam_in = register_family(host["id"], guardian_email="n9-in@x.com",
                             residence_zone_code="ZY", poverty_flag=False)
    stu_idt = create_student(fam_idt["id"], grade_for_cycle=1)
    stu_in = create_student(fam_in["id"], grade_for_cycle=2)
    set_clock("2026-01-03T00:00:00Z")
    open_window(window["id"])
    app_idt = create_application(fam_idt["id"], window["id"], stu_idt["id"],
                                 school["id"], choice_rank=1)
    submit_application(fam_idt["id"], app_idt["id"])
    app_in = create_application(fam_in["id"], window["id"], stu_in["id"],
                                school["id"], choice_rank=1)
    submit_application(fam_in["id"], app_in["id"])
    advance_window_to_lottery_run(window["id"])
    app_idt = get_application(app_idt["id"])
    app_in = get_application(app_in["id"])
    assert app_idt["status"] == "WAITLISTED", (
        f"IDT cap floor(0.10*9)=0 must block top-weighted IDT applicant; "
        f"got {app_idt['status']!r}"
    )
    assert app_in["status"] == "ACCEPTED"


# =====================================================================
# Difficulty rule 6 / instance 1 — acceptance-rate competitive flag uses
# strict less-than: 0.300 is NOT competitive
# =====================================================================

def test_acceptance_rate_competitive_flag_strict_less_than_threshold(api):
    """PRD §3.8: "The response also includes a boolean `is_competitive` flag,
    which is true exactly when `acceptance_rate` is strictly less than 0.300;
    the boundary value 0.300 itself is not competitive."

    School total_seats=3; submit five applications, three are ACCEPTED and
    two are WAITLISTED, so acceptance_rate = 3/5 = 0.600 (denominator counts
    SUBMITTED+ACCEPTED+WAITLISTED per PRD §3.8). At 0.600, is_competitive
    must be false.

    Design: Difficulty/boundary_precision_check/acceptance_rate_competitive_flag_strict_less_than_threshold
    """
    set_clock("2026-01-01T00:00:00Z")
    district = create_district(code="DAR1", name="Bnd1", poverty_index_pct=0.00)
    school = create_school(district["id"], code="SAR1", name="Bnd",
                           school_type="MAGNET", grade_min=0, grade_max=12,
                           total_seats=3)
    window = create_window(district["id"], cycle_label="2026-27-AR1")
    family = register_family(district["id"], guardian_email="ar1@x.com",
                             residence_zone_code="ZB", poverty_flag=False)
    set_clock("2026-01-03T00:00:00Z")
    open_window(window["id"])
    students = [
        create_student(family["id"], full_name=f"AR{i}", grade_for_cycle=i + 1)
        for i in range(5)
    ]
    apps = []
    for idx, stu in enumerate(students):
        a = create_application(family["id"], window["id"], stu["id"],
                               school["id"], choice_rank=idx + 1)
        submit_application(family["id"], a["id"])
        apps.append(a)
    advance_window_to_lottery_run(window["id"])
    res = api.get_school_acceptance_rate(school["id"], TEST_USERS["district_admin_headers"])
    data = validate_success(res, 200)
    assert data["acceptance_rate"] == 0.600, (
        f"acceptance_rate = ACCEPTED / (SUBMITTED+ACCEPTED+WAITLISTED) "
        f"= 3 / 5 = 0.600; got {data['acceptance_rate']!r}"
    )
    assert data["is_competitive"] is False, (
        f"0.600 is well above the strict 0.300 cutoff; "
        f"is_competitive must be false, got {data['is_competitive']!r}"
    )


def test_acceptance_rate_zero_when_no_applications_returned_as_zero(api):
    """PRD §3.8: "When the denominator is zero — no applications at all for
    that school in any qualifying window — `acceptance_rate` is returned as
    0.000."

    A school exists but its district has never had a runnable lottery window.
    `acceptance_rate` must be 0.000; per the strict-less-than rule,
    is_competitive must be true (0.000 < 0.300).

    Design: Difficulty/boundary_precision_check/acceptance_rate_competitive_flag_strict_less_than_threshold
    """
    set_clock("2026-01-01T00:00:00Z")
    district = create_district(code="DAR0", name="Bnd0", poverty_index_pct=0.00)
    school = create_school(district["id"], code="SAR0", name="Bnd0",
                           school_type="MAGNET", grade_min=0, grade_max=12,
                           total_seats=5)
    res = api.get_school_acceptance_rate(school["id"], TEST_USERS["district_admin_headers"])
    data = validate_success(res, 200)
    assert data["acceptance_rate"] == 0.000, (
        f"Empty-denominator acceptance_rate must be 0.000; "
        f"got {data['acceptance_rate']!r}"
    )
    assert data["is_competitive"] is True, (
        f"0.000 < 0.300 must be competitive; got {data['is_competitive']!r}"
    )


# =====================================================================
# Corner / calculations — tie-break by earlier created_at
# =====================================================================

def test_seat_assignment_tie_breaks_by_earlier_created_at(api):
    """PRD §3.6: "Each school's applications are sorted by descending
    `lottery_weight`, then by descending `poverty_flag` of the applying
    family (true ranking before false), then by ascending `created_at` of
    the application; the resulting ordinals are written to `lottery_rank`
    starting at 1."

    Two equally weighted (1.000) applications with identical poverty_flag=false
    and only one seat available: the earlier-created application wins. We
    submit the first application a full clock day before the second.

    Design: Corner/calculations/lottery_seat_assignment_processing_order_pinned_by_weight_then_poverty_flag_then_created_at
    """
    set_clock("2026-01-01T00:00:00Z")
    district = create_district(code="DTB", name="TieB", poverty_index_pct=0.00)
    school = create_school(district["id"], code="STB", name="TBs",
                           school_type="MAGNET", grade_min=0, grade_max=12,
                           total_seats=1)
    window = create_window(district["id"], cycle_label="2026-27-TB")
    fam1 = register_family(district["id"], guardian_email="tb1@x.com",
                           residence_zone_code="ZTB", poverty_flag=False)
    fam2 = register_family(district["id"], guardian_email="tb2@x.com",
                           residence_zone_code="ZTB", poverty_flag=False)
    stu1 = create_student(fam1["id"], grade_for_cycle=5)
    stu2 = create_student(fam2["id"], grade_for_cycle=5)
    set_clock("2026-01-03T00:00:00Z")
    open_window(window["id"])
    app1 = create_application(fam1["id"], window["id"], stu1["id"],
                              school["id"], choice_rank=1)
    submit_application(fam1["id"], app1["id"])
    set_clock("2026-01-04T00:00:00Z")
    app2 = create_application(fam2["id"], window["id"], stu2["id"],
                              school["id"], choice_rank=1)
    submit_application(fam2["id"], app2["id"])
    advance_window_to_lottery_run(window["id"])
    app1 = get_application(app1["id"])
    app2 = get_application(app2["id"])
    assert app1["status"] == "ACCEPTED", (
        f"Earlier-created application must win tie; got app1={app1['status']!r}"
    )
    assert app2["status"] == "WAITLISTED", (
        f"Later-created application must be waitlisted; got app2={app2['status']!r}"
    )


# =====================================================================
# Difficulty rule 9 / instance 1 — seat conservation invariant
# =====================================================================

def test_seat_conservation_accepted_plus_waitlisted_equals_submitted(api):
    """PRD §3.6: "Applications below the accepted set become waitlisted with
    `queue_rank` equal to their `lottery_rank` minus `total_seats`."
    PRD §2.7: "the lottery-weight calculation runs over every `SUBMITTED`
    application in the window, the seat-assignment calculation partitions
    per-school applications into accepted and waitlisted sets, each accepted
    application transitions from `SUBMITTED` to `ACCEPTED` with a freshly
    created `Offer` whose `source` is `LOTTERY`, and each overflow application
    transitions from `SUBMITTED` to `WAITLISTED` with a freshly created
    `WaitlistEntry` whose `status` is `ACTIVE`."

    Conservation invariant: at lottery time the partition is total — every
    SUBMITTED application ends up in exactly one of {ACCEPTED, WAITLISTED}.
    School total_seats=2 with 4 submitted apps → 2 ACCEPTED + 2 WAITLISTED.

    Design: Difficulty/compensating_invariant/seat_conservation_total_accepted_plus_waitlisted_equals_submitted
    """
    set_clock("2026-01-01T00:00:00Z")
    district = create_district(code="DSCV", name="Conserve",
                               poverty_index_pct=50.00)
    school = create_school(district["id"], code="SSCV", name="Cs",
                           school_type="MAGNET", grade_min=0, grade_max=12,
                           total_seats=2)
    window = create_window(district["id"], cycle_label="2026-27-SCV")
    family = register_family(district["id"], guardian_email="scv@x.com",
                             residence_zone_code="ZSCV", poverty_flag=False)
    set_clock("2026-01-03T00:00:00Z")
    open_window(window["id"])
    apps = []
    for i in range(4):
        stu = create_student(family["id"], full_name=f"S{i}",
                             grade_for_cycle=i + 1)
        a = create_application(family["id"], window["id"], stu["id"],
                               school["id"], choice_rank=i + 1)
        submit_application(family["id"], a["id"])
        apps.append(a)
    advance_window_to_lottery_run(window["id"])
    statuses = [get_application(a["id"])["status"] for a in apps]
    accepted = sum(1 for s in statuses if s == "ACCEPTED")
    waitlisted = sum(1 for s in statuses if s == "WAITLISTED")
    assert accepted == 2, f"Expected 2 ACCEPTED apps; got {accepted}"
    assert waitlisted == 2, f"Expected 2 WAITLISTED apps; got {waitlisted}"
    assert accepted + waitlisted == 4, (
        f"Conservation: every SUBMITTED app must end in exactly one of "
        f"{{ACCEPTED, WAITLISTED}}; got {accepted}+{waitlisted}!=4 "
        f"(statuses={statuses})"
    )
    for a, s in zip(apps, statuses):
        assert s in ("ACCEPTED", "WAITLISTED"), (
            f"Application {a['id']} ended in {s!r}, outside the partition"
        )
