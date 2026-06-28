"""Non-linear state machines (section OPEN<->FULL cycle, enrollment parallel
placement/billing dimensions) and transitive cascade chains (drop->promote->recompute,
section-cancel->drop->recompute).

Queue A (Difficulty): non_linear_state_machine, transitive_cascade.
"""
import pytest
from test_helpers import validate_success, TEST_USERS
from test_helpers import fixtures as fx
from test_helpers import factories as f

ADMIN_H = TEST_USERS["admin_headers"]


# =========================================================================
# Rule 3 — non_linear_state_machine
# =========================================================================
def test_section_cycles_open_full_open(api):
    """PRD §3.2: "While `OPEN`, the section accepts confirmations until its `enrolled_count`
    reaches effective capacity, at which point the system flips it to `FULL`."
    PRD §3.2: "Should a confirmed enrollment later drop while no waitlisted enrollment is
    promoted to refill the slot, the section returns from `FULL` to `OPEN`, and the next
    placement may confirm."

    Section cap 1: confirm fills it (FULL); dropping the lone confirmed enrollment with no
    waitlist returns it to OPEN with enrolled_count 0 — a genuine OPEN->FULL->OPEN cycle.

    Design: Difficulty/non_linear_state_machine/section_cyclic_open_full_open
    """
    env = fx.setup_open_term_with_section(section_overrides={"capacity_cap": 1})
    family = fx.create_family()
    student = fx.create_student(family["id"], level="ELITE")
    enr = fx.create_enrollment(student["id"], env["section"]["id"])
    # Section now FULL.
    section_full = validate_success(api.get_section(env["section"]["id"], ADMIN_H))
    assert section_full["status"] == "FULL"

    validate_success(api.drop_enrollment(enr["id"], ADMIN_H))
    section_after = validate_success(api.get_section(env["section"]["id"], ADMIN_H))
    assert section_after["status"] == "OPEN", "section must return FULL->OPEN after drop with no waitlist"
    assert section_after["enrolled_count"] == 0


def test_enrollment_billing_toggles_while_placement_stays_confirmed(api):
    """PRD §3.3: "Pausing requires the enrollment to be `BILLING_ACTIVE` and moves
    `billing_status` to `BILLING_PAUSED`; resuming requires `BILLING_PAUSED` and returns it to
    `BILLING_ACTIVE`."
    PRD §3.3: "Throughout, the enrollment's `placement_status` remains `CONFIRMED`."

    placement_status stays CONFIRMED while billing toggles ACTIVE->PAUSED->ACTIVE — two
    independent state dimensions on the same enrollment.

    Design: Difficulty/non_linear_state_machine/enrollment_parallel_placement_vs_billing
    """
    env = fx.setup_confirmed_enrollment()
    enr_id = env["enrollment"]["id"]
    validate_success(api.pause_billing(enr_id, ADMIN_H))
    paused = validate_success(api.get_enrollment(enr_id, ADMIN_H))
    assert paused["placement_status"] == "CONFIRMED"
    assert paused["billing_status"] == "BILLING_PAUSED"

    resumed = validate_success(api.resume_billing(enr_id, ADMIN_H))
    assert resumed["placement_status"] == "CONFIRMED"
    assert resumed["billing_status"] == "BILLING_ACTIVE"


# =========================================================================
# Rule 4 — transitive_cascade
# =========================================================================
def test_drop_promotes_waitlist_and_recomputes_promoted_family_tuition(api):
    """PRD §3.4: "The drop then attempts a waitlist promotion: if any `WAITLISTED` enrollment
    exists for that section, the one with the lowest `waitlist_rank` (the earliest `created_at`)
    is promoted."
    PRD §3.4: "The promoted enrollment moves from `WAITLISTED` to `WAITLIST_PROMOTED`, the
    section's `enrolled_count` increments by one, the enrollment's `billing_status` moves from
    `UNBILLED` to `BILLING_ACTIVE`, the tuition engine recomputes that enrollment and the rest of
    its family's billing-active enrollments."
    PRD §3.3: "the second class is discounted by ten percent."

    Depth-3 chain: drop of F1's confirmed enrollment frees the cap-1 slot -> F2's waitlisted
    studentX is promoted (billing becomes active) -> F2's family tuition recomputes. F2 now has
    two billing-active enrollments under one family (studentX 10000, studentY 8000). With two
    ACTIVE billing students -> family 5%: studentX (1st by tuition DESC) 10000*0.95=9500,
    studentY 8000*0.95=7600.

    Design: Difficulty/transitive_cascade/drop_promote_recompute_chain_depth3
    """
    term = fx.create_term(monthly_billing_day=10)
    room = fx.create_room(capacity=20)
    instructor = fx.create_instructor()
    sec_cap1 = fx.create_section(term["id"], room["id"], instructor["id"],
                                 discipline="JAZZ", monthly_tuition_cents=10000, capacity_cap=1)
    fx.add_session(sec_cap1["id"], day_of_week=0, start_minute=600, end_minute=660)
    sec_other = fx.create_section(term["id"], room["id"], instructor["id"],
                                  discipline="TAP", monthly_tuition_cents=8000, capacity_cap=20)
    fx.add_session(sec_other["id"], day_of_week=0, start_minute=700, end_minute=760)
    validate_success(api.open_term(term["id"], ADMIN_H))

    f1 = fx.create_family(email="f1casc@x.com", family_name="F1")
    f1s = fx.create_student(f1["id"], full_name="F1 Kid", level="ELITE")
    f1enr = fx.create_enrollment(f1s["id"], sec_cap1["id"])  # occupies the single slot

    f2 = fx.create_family(email="f2casc@x.com", family_name="F2")
    f2x = fx.create_student(f2["id"], full_name="F2 X", level="ELITE")
    f2y = fx.create_student(f2["id"], full_name="F2 Y", level="ELITE")
    f2y_enr = fx.create_enrollment(f2y["id"], sec_other["id"])      # confirmed
    f2x_enr = fx.create_enrollment(f2x["id"], sec_cap1["id"])       # waitlisted (section FULL)
    assert f2x_enr["placement_status"] == "WAITLISTED"

    # Trigger: drop F1's confirmed enrollment.
    validate_success(api.drop_enrollment(f1enr["id"], ADMIN_H))

    f2x_after = validate_success(api.get_enrollment(f2x_enr["id"], ADMIN_H))
    f2y_after = validate_success(api.get_enrollment(f2y_enr["id"], ADMIN_H))
    assert f2x_after["placement_status"] == "WAITLIST_PROMOTED"
    assert f2x_after["billing_status"] == "BILLING_ACTIVE"
    assert f2x_after["monthly_charge_cents"] == 9500
    assert f2y_after["monthly_charge_cents"] == 7600


def test_section_cancel_drops_enrollment_and_recomputes_remaining(api):
    """PRD §3.2: "When a populated section is cancelled, every enrollment in `CONFIRMED`,
    `WAITLISTED`, or `WAITLIST_PROMOTED` placement is moved to `DROPPED`."
    PRD §3.2: "the family's remaining billing-active enrollments have their `monthly_charge_cents`
    recomputed, since losing a class can shift the family's discount tier."

    A single-student family is enrolled in classA (10000, 1st) and classB (7000, 2nd, mc10%=6300).
    Cancelling classB drops it and recomputes classA's charge — but cancelling classA (the 1st)
    promotes classB to be the only/1st class at full 7000.

    Design: Difficulty/transitive_cascade/section_cancel_drop_recompute_chain_depth2
    """
    env = fx.setup_open_term_two_sections(
        secA_overrides={"discipline": "BALLET", "monthly_tuition_cents": 10000},
        secB_overrides={"discipline": "TAP", "monthly_tuition_cents": 7000},
    )
    family = fx.create_family()
    student = fx.create_student(family["id"], full_name="Only", level="ELITE")
    enr_a = fx.create_enrollment(student["id"], env["secA"]["id"])
    enr_b = fx.create_enrollment(student["id"], env["secB"]["id"])

    # Trigger: cancel classA (the un-discounted 1st class).
    validate_success(api.cancel_section(env["secA"]["id"], ADMIN_H))

    enr_a_after = validate_success(api.get_enrollment(enr_a["id"], ADMIN_H))
    enr_b_after = validate_success(api.get_enrollment(enr_b["id"], ADMIN_H))
    assert enr_a_after["placement_status"] == "DROPPED"
    assert enr_b_after["placement_status"] == "CONFIRMED"
    # classB is now the sole billing-active class for a single-student family -> 1st class, 0% all.
    assert enr_b_after["monthly_charge_cents"] == 7000
