"""Formulas whose step order is pinned: session staffing and the survey provision score."""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import assert_rounded, assert_values


def _mixed_tier_roster(api):
    """A session with three of four mixed-tier residents already enrolled."""
    program = fx.create_program(
        api, name="Chair Exercise", domain="PHYSICAL", staffing_ratio_denominator=4
    )
    room = fx.create_room(api, name="Activity Hall", capacity=10, buffer_minutes=0)
    session = fx.create_session(
        api,
        program["id"],
        room["id"],
        starts_at="2026-08-06T10:00:00Z",
        ends_at="2026-08-06T11:00:00Z",
        assigned_staff_count=2,
    )
    axes = [
        ("Tier One A", "301A", "MILD_IMPAIRMENT", "INDEPENDENT"),
        ("Tier One B", "301B", "INTACT", "ASSIST_1"),
        ("Tier Two C", "302A", "MODERATE_IMPAIRMENT", "ASSIST_1"),
        ("Tier Three D", "302B", "SEVERE_IMPAIRMENT", "ASSIST_2"),
    ]
    residents = []
    for name, room_number, cognition, mobility in axes:
        resident, _ = fx.assessed_resident(
            api,
            resident_kwargs={"full_name": name, "room_number": room_number,
                             "admission_date": "2026-03-01"},
            cognitive_level=cognition,
            functional_mobility=mobility,
            interest_domains=["PHYSICAL"],
            preferred_group_size="LARGE",
            effective_date="2026-07-20",
        )
        residents.append(resident)
    for resident in residents[:3]:
        fx.enroll(api, session["id"], resident["id"])
    return session, residents


def test_session_staffing_sum_then_ceil_pinned(api, aide):
    """The fourth resident joins a roster whose weighted load divides to 1.625 staff, and
    the single closing ceiling keeps the requirement inside the two rostered staff.

    PRD: "round each tier's subtotal, sum the three subtotals, divide once, and apply
    exactly one rounding-up".

    Design: Difficulty/combinatorial_formula/session_staffing_sum_then_ceil_pinned
    """
    session, residents = _mixed_tier_roster(api)

    response = api.create_enrollment(
        session["id"], f.enrollment_payload(residents[3]["id"]), aide
    )
    record = validate_success(response, 201)
    assert_values(record, status="PLANNED")

    stored = fx.read_session(api, session["id"])
    assert_values(stored, enrolled_count=4)


def test_session_staffing_sum_then_ceil_pinned_load_and_requirement(api, aide):
    """The full four-resident roster stores a weighted load of 6.5 and a requirement of
    two staff, not the three that per-tier rounding would invent.

    PRD: "Rounding each tier's own quotient up and adding those three whole numbers
    together gives a different — and wrong — answer, and is explicitly forbidden."

    Design: Difficulty/combinatorial_formula/session_staffing_sum_then_ceil_pinned
    """
    session, residents = _mixed_tier_roster(api)

    validate_success(
        api.create_enrollment(session["id"], f.enrollment_payload(residents[3]["id"]), aide),
        201,
    )

    stored = fx.read_session(api, session["id"])
    assert_rounded(stored["weighted_supervision_load"], 6.5, 2)
    assert_values(stored, required_staff_count=2)


def _compilable_packet(api, compliance):
    """One refused SOCIAL session, a plan in revision, and an OPEN packet over the window."""
    resident, assessment = fx.assessed_resident(
        api,
        resident_kwargs={"full_name": "Hal Whitcomb", "room_number": "210A",
                         "admission_date": "2026-01-05"},
        cognitive_level="MILD_IMPAIRMENT",
        functional_mobility="ASSIST_1",
        interest_domains=["SOCIAL"],
        effective_date="2026-07-20",
    )
    plan = fx.active_plan(
        api, resident["id"], assessment["id"], targets=f.domain_targets(social=2)
    )
    program = fx.create_program(api, name="Reminiscence Circle", domain="SOCIAL")
    room = fx.create_room(api, name="Parlor", capacity=10, buffer_minutes=0)
    session = fx.create_session(
        api,
        program["id"],
        room["id"],
        starts_at="2026-08-04T14:00:00Z",
        ends_at="2026-08-04T15:00:00Z",
    )
    record = fx.enroll(api, session["id"], resident["id"])
    fx.advance_clock(api, "2026-08-04T14:00:00Z")
    fx.start_session(api, session["id"])
    fx.document_refusal(api, record["id"])
    validate_success(
        api.transition_activity_plan(
            plan["id"], {"action": "REVISE", "review_reason": "THERAPIST_REQUEST"},
            fx.THERAPIST_HEADERS,
        ),
        200,
    )
    fx.advance_clock(api, "2026-08-05T12:00:00Z")
    packet = fx.open_packet(
        api, headers=compliance, window_start="2026-08-01", window_end="2026-08-05"
    )
    return packet


def test_survey_provision_score_pinned_five_step_order(api, compliance):
    """Compilation reports the two raw counters and the first three pinned steps: a base
    score of 50.0, no domain penalty, a refusal penalty of 2.0 and a preliminary of 48.0.

    PRD: "Step 3 produces `preliminary_score`: `base_score` minus
    `domain_coverage_penalty` minus `refusal_penalty`, clamped at 0.0 below, rounded half
    up to one decimal place."

    Design: Difficulty/combinatorial_formula/survey_provision_score_pinned_five_step_order
    """
    packet = _compilable_packet(api, compliance)

    compiled = validate_success(
        api.compile_survey_packet(packet["id"], {}, compliance), 200
    )
    assert_values(
        compiled,
        status="COMPILED",
        offered_sessions_targeted=2,
        offered_sessions_delivered=1,
    )
    assert_rounded(compiled["base_score"], 50.0, 1)
    assert_rounded(compiled["domain_coverage_penalty"], 0.0, 1)
    assert_rounded(compiled["refusal_penalty"], 2.0, 1)
    assert_rounded(compiled["preliminary_score"], 48.0, 1)


def test_survey_provision_score_pinned_five_step_order_flags_from_preliminary(api, compliance):
    """The frequency flag is tested against the preliminary score rather than the base
    score, so two flags are raised and the provision score lands on 42.0.

    PRD: "The `F248_INSUFFICIENT_FREQUENCY` test reads `preliminary_score` — never
    `base_score`, and never `provision_score`."

    Design: Difficulty/combinatorial_formula/survey_provision_score_pinned_five_step_order
    """
    packet = _compilable_packet(api, compliance)

    validate_success(api.compile_survey_packet(packet["id"], {}, compliance), 200)

    stored = fx.read_packet(api, packet["id"], compliance)
    assert stored["deficiency_flags"] == [
        "F248_INSUFFICIENT_FREQUENCY",
        "F249_UNADDRESSED_REFUSAL",
    ], f"Expected both flags in ascending code order, got {stored['deficiency_flags']}"
    assert_rounded(stored["provision_score"], 42.0, 1)
