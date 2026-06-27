"""Compatibility threshold, validation precedence, and calendar overlap/buffer rules."""
from test_helpers import (
    validate_success,
    validate_error,
    TEST_USERS,
    make_member_headers,
    ApiErrorId,
    fixtures as fx,
)
import test_helpers.factories as f

ADMIN = TEST_USERS["billing_admin_headers"]
SCREENING = TEST_USERS["screening_officer_headers"]
MATCHMAKER = TEST_USERS["matchmaker_headers"]


def test_compatibility_at_threshold_admitted_perfect_pair(api):
    """PRD §3.3: "An introduction may be suggested only when its compatibility score
    is at least 70.00 — the threshold is inclusive, so exactly 70.00 is eligible and
    anything below it is not". A perfect pair (attr=100, pref=100, loc=100, act=100)
    scores 40+35+15+10 = 100.00 and is admitted to SUGGESTED.

    Design: Difficulty/boundary_precision_check/compatibility_at_or_above_threshold_admitted
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    plan = fx.create_plan(tier="PLUS", guaranteed_introductions=8)
    # Same city, identical attribute vectors, both ACTIVE, mutual gender/age satisfaction.
    member_a, _ = fx.create_active_member(
        plan["id"], "a8@x.com", gender="MALE",
        pref_overrides={"seeking_gender": "FEMALE", "min_age": 25, "max_age": 45,
                        "max_distance_band": 0,
                        "attribute_weights": {"education": 80, "lifestyle": 80, "values": 80}},
    )
    member_b, _ = fx.create_active_member(
        plan["id"], "b12@x.com", gender="FEMALE",
        pref_overrides={"seeking_gender": "MALE", "min_age": 28, "max_age": 45,
                        "max_distance_band": 0,
                        "attribute_weights": {"education": 80, "lifestyle": 80, "values": 80}},
    )

    a_ver = fx.current_version(member_a["id"])
    resp = api.create_introduction(
        f.create_introduction_payload(member_a["id"], member_b["id"], a_ver), MATCHMAKER
    )
    intro = validate_success(resp, 201)
    assert intro["compatibility_score"] == 100.00, (
        f"perfect pair scores exactly 100.00, got {intro['compatibility_score']}"
    )
    assert intro["status"] == "SUGGESTED", (
        f"a 100.00 score (>= 70.00) is admitted to SUGGESTED, got {intro['status']}"
    )


def test_compatibility_at_threshold_perfect_pair_starts_pending(api):
    """PRD §3.4: "On success the introduction is created in status `SUGGESTED` with both
    `a_response` and `b_response` at `PENDING`, member A's `guarantee_remaining_forecast`
    is decremented, member A's `version` is incremented by one, and the introduction's
    own `version` starts at 1". A perfect pair scoring 100.00 (>= 70.00) is admitted.

    Design: Difficulty/boundary_precision_check/compatibility_at_or_above_threshold_admitted
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    plan = fx.create_plan(tier="PLUS", guaranteed_introductions=8)
    member_a, _ = fx.create_active_member(
        plan["id"], "a8p@x.com", gender="MALE",
        pref_overrides={"seeking_gender": "FEMALE", "min_age": 25, "max_age": 45,
                        "max_distance_band": 0,
                        "attribute_weights": {"education": 80, "lifestyle": 80, "values": 80}},
    )
    member_b, _ = fx.create_active_member(
        plan["id"], "b12p@x.com", gender="FEMALE",
        pref_overrides={"seeking_gender": "MALE", "min_age": 28, "max_age": 45,
                        "max_distance_band": 0,
                        "attribute_weights": {"education": 80, "lifestyle": 80, "values": 80}},
    )
    a_ver = fx.current_version(member_a["id"])
    intro = validate_success(
        api.create_introduction(
            f.create_introduction_payload(member_a["id"], member_b["id"], a_ver), MATCHMAKER
        ),
        201,
    )
    assert intro["compatibility_score"] == 100.00, f"expected 100.00, got {intro['compatibility_score']}"
    assert intro["status"] == "SUGGESTED", f"admitted intro is SUGGESTED, got {intro['status']}"
    assert intro["a_response"] == "PENDING" and intro["b_response"] == "PENDING", (
        "new introduction starts with both responses PENDING"
    )
    assert intro["version"] == 1, f"introduction version starts at 1, got {intro['version']}"


def test_compatibility_too_low_beats_guarantee_exhausted(api):
    """PRD §2.8: validation order is "... (9) the compatibility threshold
    (ERR_COMPATIBILITY_TOO_LOW); ... (11) the guarantee pool sufficiency
    (ERR_GUARANTEE_EXHAUSTED) ... an earlier class always masks a later one."
    PRD §3.3: "a sub-threshold pair is rejected with `ERR_COMPATIBILITY_TOO_LOW`."

    Design: Difficulty/priority_pair_validation_conflict/compatibility_too_low_beats_guarantee_exhausted
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    plan = fx.create_plan(tier="BASIC", monthly_fee_cents=12000, guaranteed_introductions=0)
    # member_a guarantee already 0 (would exhaust). The pair mutually satisfies the
    # preference gate (gender + age both fit, so ERR_PREFERENCE_MISMATCH does not fire)
    # but divergent attribute vectors plus different cities drag the blended
    # compatibility below 70.00, so ERR_COMPATIBILITY_TOO_LOW (class 9) masks the
    # guarantee exhaustion (class 11).
    member_a, _ = fx.create_active_member(
        plan["id"], "a6@x.com", gender="MALE",
        pref_overrides={"seeking_gender": "FEMALE", "min_age": 25, "max_age": 45,
                        "max_distance_band": 0,
                        "attribute_weights": {"education": 80, "lifestyle": 80, "values": 80}},
    )
    member_b, _ = fx.create_active_member(
        plan["id"], "b10@x.com", gender="FEMALE", city="LA",
        pref_overrides={"seeking_gender": "MALE", "min_age": 25, "max_age": 45,
                        "max_distance_band": 0,
                        "attribute_weights": {"education": 10, "lifestyle": 10, "values": 10}},
    )

    a_ver = fx.current_version(member_a["id"])
    resp = api.create_introduction(
        f.create_introduction_payload(member_a["id"], member_b["id"], a_ver), MATCHMAKER
    )
    validate_error(resp, ApiErrorId.ERR_COMPATIBILITY_TOO_LOW.value, 422)


def test_compatibility_too_low_masks_guarantee_with_consumed_credit(api):
    """PRD §2.8: "(9) the compatibility threshold (ERR_COMPATIBILITY_TOO_LOW); ... (11)
    the guarantee pool sufficiency (ERR_GUARANTEE_EXHAUSTED) ... an earlier class
    always masks a later one." Even with the guarantee pool already drained to 0, a
    sub-threshold compatibility surfaces ERR_COMPATIBILITY_TOO_LOW.

    Design: Difficulty/priority_pair_validation_conflict/compatibility_too_low_beats_guarantee_exhausted
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    plan = fx.create_plan(tier="BASIC", monthly_fee_cents=12000, guaranteed_introductions=0)
    member_a, _ = fx.create_active_member(
        plan["id"], "a6b@x.com", gender="MALE",
        pref_overrides={"seeking_gender": "FEMALE", "min_age": 25, "max_age": 45,
                        "max_distance_band": 0,
                        "attribute_weights": {"education": 90, "lifestyle": 90, "values": 90}},
    )
    member_b, _ = fx.create_active_member(
        plan["id"], "b10b@x.com", gender="FEMALE", city="LA",
        pref_overrides={"seeking_gender": "MALE", "min_age": 25, "max_age": 45,
                        "max_distance_band": 0,
                        "attribute_weights": {"education": 5, "lifestyle": 5, "values": 5}},
    )
    a_ver = fx.current_version(member_a["id"])
    resp = api.create_introduction(
        f.create_introduction_payload(member_a["id"], member_b["id"], a_ver), MATCHMAKER
    )
    validate_error(resp, ApiErrorId.ERR_COMPATIBILITY_TOO_LOW.value, 422)


def test_date_event_half_open_overlap_on_member_calendar(api):
    """PRD §3.6: "A new date must not overlap any existing `SCHEDULED` date or any `BOOKED` coaching session of that member; because intervals are half-open, two intervals that merely touch at an endpoint do not collide, but any true overlap is rejected with `ERR_DATE_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/date_event_half_open_overlap_on_member_calendar
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    plan = fx.create_plan(tier="PLUS", guaranteed_introductions=8)
    member_a, _ = fx.create_active_member(plan["id"], "a11@x.com", gender="MALE",
                                          pref_overrides={"seeking_gender": "FEMALE"})
    a_id = member_a["id"]
    member_b, _ = fx.create_active_member(plan["id"], "b14@x.com", gender="FEMALE",
                                          pref_overrides={"seeking_gender": "MALE"})
    member_c, _ = fx.create_active_member(plan["id"], "b15@x.com", gender="FEMALE",
                                          pref_overrides={"seeking_gender": "MALE"})

    intro1 = fx.suggest_introduction(a_id, member_b["id"])
    intro1 = fx.respond(intro1["id"], a_id, "ACCEPTED", intro1["version"])
    fx.respond(intro1["id"], member_b["id"], "ACCEPTED", intro1["version"])

    intro2 = fx.suggest_introduction(a_id, member_c["id"])
    intro2 = fx.respond(intro2["id"], a_id, "ACCEPTED", intro2["version"])
    fx.respond(intro2["id"], member_c["id"], "ACCEPTED", intro2["version"])

    # First date [18:00, 20:00) for member_a.
    fx.schedule_date(intro1["id"], a_id, "2026-06-10T18:00:00Z", "2026-06-10T20:00:00Z")
    # Overlapping date [19:00, 21:00) -> collides.
    resp = api.create_date_event(
        intro2["id"],
        f.create_date_event_payload(a_id, "2026-06-10T19:00:00Z", "2026-06-10T21:00:00Z"),
        make_member_headers(a_id),
    )
    validate_error(resp, ApiErrorId.ERR_DATE_OVERLAP.value, 409)


def test_date_event_touching_endpoint_allowed(api):
    """PRD §3.6: "because intervals are half-open, two intervals that merely touch at an endpoint do not collide, but any true overlap is rejected with `ERR_DATE_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/date_event_half_open_overlap_on_member_calendar
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    plan = fx.create_plan(tier="PLUS", guaranteed_introductions=8)
    member_a, _ = fx.create_active_member(plan["id"], "a11t@x.com", gender="MALE",
                                          pref_overrides={"seeking_gender": "FEMALE"})
    a_id = member_a["id"]
    member_b, _ = fx.create_active_member(plan["id"], "b14t@x.com", gender="FEMALE",
                                          pref_overrides={"seeking_gender": "MALE"})
    member_c, _ = fx.create_active_member(plan["id"], "b15t@x.com", gender="FEMALE",
                                          pref_overrides={"seeking_gender": "MALE"})

    intro1 = fx.suggest_introduction(a_id, member_b["id"])
    intro1 = fx.respond(intro1["id"], a_id, "ACCEPTED", intro1["version"])
    fx.respond(intro1["id"], member_b["id"], "ACCEPTED", intro1["version"])

    intro2 = fx.suggest_introduction(a_id, member_c["id"])
    intro2 = fx.respond(intro2["id"], a_id, "ACCEPTED", intro2["version"])
    fx.respond(intro2["id"], member_c["id"], "ACCEPTED", intro2["version"])

    fx.schedule_date(intro1["id"], a_id, "2026-06-10T18:00:00Z", "2026-06-10T20:00:00Z")
    # Touching date [20:00, 22:00) does NOT collide.
    resp = api.create_date_event(
        intro2["id"],
        f.create_date_event_payload(a_id, "2026-06-10T20:00:00Z", "2026-06-10T22:00:00Z"),
        make_member_headers(a_id),
    )
    validate_success(resp, 201)


def test_coaching_buffer_closed_gap_against_date(api):
    """PRD §3.7: "a new coaching session must keep a 30-minute buffer from the member's scheduled dates: the gap between the new session and any `SCHEDULED` date of the member must be at least 30 minutes, where the buffer is closed so a gap of exactly 30 minutes is allowed but a 29-minute gap collides, and a violation is rejected with `ERR_COACHING_BUFFER_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/coaching_buffer_closed_gap_against_date
    """
    ctx = fx.setup_mutual_with_date(start_at="2026-06-10T18:00:00Z", end_at="2026-06-10T20:00:00Z",
                                    a_email="a12@x.com", b_email="b16@x.com")
    a_id = ctx["member_a"]["id"]
    # Coaching [20:20, 21:00): gap 20 min < 30 -> buffer conflict.
    resp = api.create_coaching_session(
        a_id, f.create_coaching_session_payload("2026-06-10T20:20:00Z", "2026-06-10T21:00:00Z"),
        MATCHMAKER,
    )
    validate_error(resp, ApiErrorId.ERR_COACHING_BUFFER_CONFLICT.value, 409)


def test_coaching_buffer_exact_30_minutes_allowed(api):
    """PRD §3.7: "the buffer is closed so a gap of exactly 30 minutes is allowed but a
    29-minute gap collides".

    Design: Difficulty/resource_temporal_overlap/coaching_buffer_closed_gap_against_date
    """
    ctx = fx.setup_mutual_with_date(start_at="2026-06-10T18:00:00Z", end_at="2026-06-10T20:00:00Z",
                                    a_email="a12e@x.com", b_email="b16e@x.com")
    a_id = ctx["member_a"]["id"]
    # Coaching [20:30, 21:00): gap exactly 30 min -> allowed.
    resp = api.create_coaching_session(
        a_id, f.create_coaching_session_payload("2026-06-10T20:30:00Z", "2026-06-10T21:00:00Z"),
        MATCHMAKER,
    )
    validate_success(resp, 201)
