"""Session-cancel cascades and the rainy-day weather dimension.

Covers the difficulty transitive-cascade (session cancel depth-3), the difficulty
non-linear weather-dimension cycle and aggregate-overflow temporal instances, plus the
corner conditional-cascade, rained-out, age-mismatch, and two-level relocation instances.
"""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    create_program_payload,
    create_session_payload,
    create_weather_event_payload,
    create_enrollment_payload,
    make_guardian_headers,
    assert_weather_event,
    # fixtures
    create_guardian,
    setup_eligible_child,
    setup_open_session_with_offering,
    setup_confirmed_enrollment,
    setup_offering_with_rain_alternate,
    get_offering,
    get_invoice,
    get_enrollment,
    enroll_child,
)

DIRECTOR = TEST_USERS["program_director_headers"]
BILLING = TEST_USERS["billing_admin_headers"]


# ---------------------------------------------------------------------------
# Session cancel depth-3 cascade to invoice totals (difficulty transitive cascade)
# ---------------------------------------------------------------------------
def test_session_cancel_cascades_to_invoice_totals(api):
    """PRD §3.2: "Cancellation ... triggers a three-link cascade. First, for every weekly
    offering under the session, every enrollment currently in CONFIRMED or WAITLISTED is
    moved to WITHDRAWN. Second, ... each such offering re-runs its count reconciliation,
    dropping enrolled_count and waitlist_count accordingly. Third, ... each affected DRAFT
    invoice re-runs its totals so that subtotal_cents, sibling_discount_cents, and
    total_due_cents fall to reflect the lost lines."

    Design: Difficulty/transitive_cascade/session_cancel_depth3_cascade_to_invoice_totals
    """
    scene = setup_confirmed_enrollment(
        program_overrides={"name": "Cancel Camp", "program_type": "CAMP"},
        session_overrides={"base_weekly_tuition_cents": 20000},
    )
    invoice_id = scene["invoice_id"]
    validate_success(api.cancel_session(scene["session"]["id"], DIRECTOR), 200)
    e = get_enrollment(scene["enrollment"]["id"])
    assert e["status"] == "WITHDRAWN", f"cancelled-session enrollment must be WITHDRAWN, got {e['status']}"
    offering = get_offering(scene["offering"]["id"])
    assert offering["enrolled_count"] == 0, f"enrolled_count must drop to 0, got {offering['enrolled_count']}"
    inv = get_invoice(invoice_id)
    assert inv["subtotal_cents"] == 0, f"invoice subtotal must drop to 0, got {inv['subtotal_cents']}"
    assert inv["total_due_cents"] == 0, f"invoice total must drop to 0, got {inv['total_due_cents']}"


def test_session_cancel_leaves_already_withdrawn_enrollment_untouched(api):
    """PRD §3.2: "for every weekly offering under the session, every enrollment currently in
    CONFIRMED or WAITLISTED is moved to WITHDRAWN." (An already-WITHDRAWN enrollment is not
    in CONFIRMED/WAITLISTED, so it stays WITHDRAWN; the still-CONFIRMED one is withdrawn.)

    Design: Corner/state_machines/session_cancel_only_withdraws_non_terminal_enrollments
    """
    guardian = create_guardian()
    gid = guardian["id"]
    gh = make_guardian_headers(gid)
    scene = setup_open_session_with_offering(
        program_overrides={"name": "Cond Camp", "program_type": "AFTERSCHOOL"},
        session_overrides={"weekly_capacity": 5, "base_weekly_tuition_cents": 15000},
    )
    offering_id = scene["offering"]["id"]
    child_a = setup_eligible_child(guardian_id=gid, child_overrides={"first_name": "Ax", "birth_date": "2016-01-01"})["child"]
    child_b = setup_eligible_child(guardian_id=gid, child_overrides={"first_name": "Bx", "birth_date": "2016-02-01"})["child"]
    ea = enroll_child(gid, child_a["id"], offering_id, get_offering(offering_id)["version"])
    # Withdraw A first.
    validate_success(api.withdraw_enrollment(ea["id"], gh), 200)
    eb = enroll_child(gid, child_b["id"], offering_id, get_offering(offering_id)["version"])
    # Cancel the session.
    validate_success(api.cancel_session(scene["session"]["id"], DIRECTOR), 200)
    fa = get_enrollment(ea["id"])
    fb = get_enrollment(eb["id"])
    assert fa["status"] == "WITHDRAWN", f"already-withdrawn A stays WITHDRAWN, got {fa['status']}"
    assert fb["status"] == "WITHDRAWN", f"confirmed B is withdrawn by cancel, got {fb['status']}"
    offering = get_offering(offering_id)
    assert offering["enrolled_count"] == 0, f"enrolled_count must be 0 after cancel, got {offering['enrolled_count']}"


# ---------------------------------------------------------------------------
# Rain relocation two-level cascade moves counts (corner cross-cutting)
# ---------------------------------------------------------------------------
def test_rain_declaration_relocates_confirmed_child_and_moves_counts(api):
    """PRD §3.5: "every CONFIRMED enrollment on the source offering is re-pointed to the
    alternate ... both the source and the alternate offerings re-run their count
    reconciliation, moving enrolled_count between them. The system records a Weather Event
    capturing the affected weekly_offering_id, a server-stamped declared_at, and a
    moved_enrollment_count equal to the number of children relocated".

    Design: Corner/cross_cutting_complexity_layers/rain_relocation_two_level_cascade_moves_counts
    """
    rain = setup_offering_with_rain_alternate()
    w1, w2 = rain["w1"], rain["w2"]
    # Enroll one eligible child on W1.
    eligible = setup_eligible_child()
    gid = eligible["guardian"]["id"]
    enroll_child(gid, eligible["child"]["id"], w1["id"], get_offering(w1["id"])["version"])
    # Declare rain on W1.
    resp = api.create_weather_event(create_weather_event_payload(w1["id"]), DIRECTOR)
    wev = validate_success(resp, 201)
    assert_weather_event(wev)
    assert wev["moved_enrollment_count"] == 1, f"expected moved_enrollment_count 1, got {wev['moved_enrollment_count']}"
    w1_after = get_offering(w1["id"])
    w2_after = get_offering(w2["id"])
    assert w1_after["enrolled_count"] == 0, f"source W1 enrolled_count must be 0, got {w1_after['enrolled_count']}"
    assert w2_after["enrolled_count"] == 1, f"alternate W2 enrolled_count must be 1, got {w2_after['enrolled_count']}"


# ---------------------------------------------------------------------------
# Weather dimension cycle: clear-rain returns NORMAL, occupancy stays relocated (difficulty)
# ---------------------------------------------------------------------------
def test_clear_rain_returns_normal_while_relocated_occupancy_persists(api):
    """PRD §3.5: "Clearing rain advances the weather dimension RAIN_ACTIVATED -> NORMAL,
    which only resets the weather posture so a future rain day can fire again ... Children
    moved by the prior rain activation stay on the alternate; there is no automatic return."
    PRD §2.8: an offering is "AVAILABLE while its confirmed count is below its session's
    weekly_capacity". (After clear-rain, W1 has 0 confirmed -> AVAILABLE and NORMAL.)

    Design: Difficulty/non_linear_state_machine/weekly_offering_parallel_weather_dimension_cycle
    """
    rain = setup_offering_with_rain_alternate()
    w1 = rain["w1"]
    eligible = setup_eligible_child()
    gid = eligible["guardian"]["id"]
    enroll_child(gid, eligible["child"]["id"], w1["id"], get_offering(w1["id"])["version"])
    # Declare rain (relocates child to W2), then clear rain on W1.
    validate_success(api.create_weather_event(create_weather_event_payload(w1["id"]), DIRECTOR), 201)
    validate_success(api.clear_rain(w1["id"], DIRECTOR), 200)
    w1_after = get_offering(w1["id"])
    assert w1_after["weather_state"] == "NORMAL", f"weather must reset to NORMAL, got {w1_after['weather_state']}"
    assert w1_after["enrolled_count"] == 0, f"relocated occupancy: W1 enrolled_count must stay 0, got {w1_after['enrolled_count']}"
    assert w1_after["capacity_state"] == "AVAILABLE", f"W1 with 0 confirmed must be AVAILABLE, got {w1_after['capacity_state']}"


# ---------------------------------------------------------------------------
# Enroll into rained-out offering rejected (corner validation)
# ---------------------------------------------------------------------------
def test_enroll_into_rained_out_offering_rejected(api):
    """PRD §3.4: "The week's weather_state must be NORMAL — a week that has been rained out
    cannot accept new enrollments — or the request fails with ERR_OFFERING_RAINED_OUT."

    Design: Corner/validations/enroll_into_rained_out_offering_rejected
    """
    rain = setup_offering_with_rain_alternate()
    w1 = rain["w1"]
    # Declare rain on W1 (no one enrolled yet, so nothing relocates but weather flips).
    validate_success(api.create_weather_event(create_weather_event_payload(w1["id"]), DIRECTOR), 201)
    # A fresh eligible child attempts to enroll into the rained-out W1.
    eligible = setup_eligible_child()
    gid = eligible["guardian"]["id"]
    gh = make_guardian_headers(gid)
    ver = get_offering(w1["id"])["version"]
    resp = api.create_enrollment(create_enrollment_payload(eligible["child"]["id"], w1["id"], ver), gh)
    validate_error(resp, ApiErrorId.ERR_OFFERING_RAINED_OUT.value)


# ---------------------------------------------------------------------------
# Rain alternate age mismatch rejected (corner validation)
# ---------------------------------------------------------------------------
def test_rain_declaration_rejected_when_child_age_outside_alternate_group(api):
    """PRD §3.5: "Every relocating child's age must fit the alternate offering's age group;
    if any confirmed child's age falls outside the alternate's group, the entire
    declaration is rejected with ERR_ALTERNATE_AGE_MISMATCH before a single relocation
    occurs."

    Design: Corner/validations/rain_alternate_age_mismatch_rejected
    """
    # Outdoor group [8,12], indoor alternate group [5,7]; child age 10 fits outdoor, not indoor.
    rain = setup_offering_with_rain_alternate(
        out_session_overrides={"age_group_min": 8, "age_group_max": 12},
        in_session_overrides={"age_group_min": 5, "age_group_max": 7},
    )
    w1 = rain["w1"]
    eligible = setup_eligible_child(child_overrides={"birth_date": "2016-01-01"})  # age 10 as of 2026-06-01
    gid = eligible["guardian"]["id"]
    enroll_child(gid, eligible["child"]["id"], w1["id"], get_offering(w1["id"])["version"])
    resp = api.create_weather_event(create_weather_event_payload(w1["id"]), DIRECTOR)
    validate_error(resp, ApiErrorId.ERR_ALTERNATE_AGE_MISMATCH.value)


# ---------------------------------------------------------------------------
# Rain alternate aggregate over-capacity rejected (difficulty temporal)
# ---------------------------------------------------------------------------
def test_rain_declaration_rejected_when_relocation_exceeds_alternate_capacity_plus_tolerance(api):
    """PRD §3.5: "The number of confirmed children to relocate may exceed the alternate
    offering's weekly_capacity by at most one — a hard overflow tolerance that protects the
    indoor room — so if the relocate count is greater than the alternate's capacity plus
    one, the declaration is rejected with ERR_ALTERNATE_OVER_CAPACITY before any relocation
    occurs." (3 confirmed to relocate; alternate capacity 1 + tolerance 1 = 2 < 3.)

    Design: Difficulty/resource_temporal_overlap/rain_alternate_aggregate_capacity_overflow_rejected
    """
    # Outdoor capacity 5 (so all 3 confirm), indoor alternate capacity 1.
    rain = setup_offering_with_rain_alternate(
        out_session_overrides={"weekly_capacity": 5, "age_group_min": 8, "age_group_max": 12},
        in_session_overrides={"weekly_capacity": 1, "age_group_min": 8, "age_group_max": 12},
    )
    w1 = rain["w1"]
    guardian = create_guardian()
    gid = guardian["id"]
    for i in range(3):
        child = setup_eligible_child(
            guardian_id=gid, child_overrides={"first_name": f"R{i}", "birth_date": f"2016-0{i + 1}-01"}
        )["child"]
        enroll_child(gid, child["id"], w1["id"], get_offering(w1["id"])["version"])
    resp = api.create_weather_event(create_weather_event_payload(w1["id"]), DIRECTOR)
    validate_error(resp, ApiErrorId.ERR_ALTERNATE_OVER_CAPACITY.value)
