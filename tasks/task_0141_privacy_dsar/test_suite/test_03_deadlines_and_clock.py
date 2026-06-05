"""Statutory deadlines (GDPR vs CCPA), the single extension, business-days
countdown, deadline-instant boundary, and the clock-driven expiry sweep."""
from datetime import timedelta
from test_helpers.assertions import _to_instant
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    assert_instant_equals,
    TEST_USERS,
    make_intake_agent_headers,
    setup_registry, create_request,
    create_request_under_review,
    verify_request,
    set_clock,
)

_PO = TEST_USERS["privacy_officer_headers"]
_IA = TEST_USERS["intake_agent_headers"]


def test_deadline_gdpr_30_days(api):
    """PRD §3.3: "30 calendar days under GDPR ... The deadline is anchored to the
    received_at instant supplied at intake and is recorded on the request as
    deadline_at."

    Design: Difficulty/dual_variant_calc/deadline_gdpr_vs_ccpa_diverge_for_identical_received_at
    """
    controller, subject, _ = setup_registry("GDPR", with_processor=False)
    req = create_request(controller["id"], subject["id"], "ACCESS",
                         received_at="2026-01-05T09:00:00Z")
    data = validate_success(api.get_dsar_request(req["id"], _PO), 200)
    assert_instant_equals(data["deadline_at"], "2026-02-04T09:00:00Z", "GDPR deadline")


def test_deadline_ccpa_45_days_diverges_from_gdpr(api):
    """PRD §3.3: "45 calendar days under CCPA ... The deadline is anchored to the
    received_at instant supplied at intake and is recorded on the request as
    deadline_at."

    Design: Difficulty/dual_variant_calc/deadline_gdpr_vs_ccpa_diverge_for_identical_received_at
    """
    ctrl_gdpr, sub_gdpr, _ = setup_registry("GDPR", with_processor=False)
    ctrl_ccpa, sub_ccpa, _ = setup_registry("CCPA", with_processor=False)
    req_gdpr = create_request(ctrl_gdpr["id"], sub_gdpr["id"], "ACCESS",
                              received_at="2026-01-05T09:00:00Z")
    req_ccpa = create_request(ctrl_ccpa["id"], sub_ccpa["id"], "ACCESS",
                              received_at="2026-01-05T09:00:00Z")
    g = validate_success(api.get_dsar_request(req_gdpr["id"], _PO), 200)
    c = validate_success(api.get_dsar_request(req_ccpa["id"], _PO), 200)
    assert_instant_equals(g["deadline_at"], "2026-02-04T09:00:00Z", "GDPR deadline")
    assert_instant_equals(c["deadline_at"], "2026-02-19T09:00:00Z", "CCPA deadline")
    # Same received_at, different jurisdiction -> different deadline.
    assert g["deadline_at"] != c["deadline_at"]


def test_extended_deadline_recomputed_gdpr_plus_sixty(api):
    """PRD §3.3: "a GDPR controller adds a further 60 calendar days (yielding 30
    plus 60) ... Granting raises extension_count to 1, recomputes deadline_at."

    Design: Corner/calculations/extended_deadline_recomputed_gdpr_plus_sixty
    """
    ctx = create_request_under_review(jurisdiction="GDPR", request_type="ACCESS",
                                      intake_user_id="intake-ext")
    # PRD §3.3: extended GDPR deadline = received_at + 30 base + 60 extension = 90
    # calendar days, preserving time-of-day. Anchor the expectation to the actual
    # received_at the fixture used so the assertion stays exact regardless of the
    # fixture's wall-clock-relative received_at.
    received_at = _to_instant(ctx["request"]["received_at"])
    expected = (received_at + timedelta(days=90)).isoformat().replace("+00:00", "Z")
    resp = api.extend_deadline(ctx["request"]["id"],
                              {"reason": "complex cross-system search"}, _PO)
    data = validate_success(resp, 200)
    assert_instant_equals(data["deadline_at"], expected, "extended deadline")
    assert data["extension_count"] == 1


def test_extend_deadline_second_time_returns_extension_limit_reached(api):
    """PRD §3.3: "Exactly one extension is permitted per request ... a second
    attempt, when extension_count is already 1, is refused with
    ERR_EXTENSION_LIMIT_REACHED."

    Design: Corner/validations/extend_deadline_second_time_returns_extension_limit_reached
    """
    ctx = create_request_under_review(jurisdiction="GDPR", request_type="ACCESS",
                                      intake_user_id="intake-ext2")
    first = validate_success(
        api.extend_deadline(ctx["request"]["id"], {"reason": "first extension"}, _PO), 200)
    assert first["extension_count"] == 1
    resp = api.extend_deadline(ctx["request"]["id"], {"reason": "second extension"}, _PO)
    validate_error(resp, ApiErrorId.ERR_EXTENSION_LIMIT_REACHED.value, 409)
    after = validate_success(api.get_dsar_request(ctx["request"]["id"], _PO), 200)
    assert after["extension_count"] == 1


def test_business_days_remaining_excludes_weekends(api):
    """PRD §3.3: "the start day — the calendar date of current_utc — is excluded,
    and the deadline date is included if it is itself a weekday; the count walks
    each date from the day after the current date through the deadline date
    inclusive, adding one for every date that falls on a weekday and treating
    Saturday and Sunday as non-counting."

    Design: Corner/calculations/business_days_remaining_excludes_weekends
    """
    controller, subject, _ = setup_registry("GDPR", with_processor=False)
    set_clock("2026-01-05T09:00:00Z")
    req = create_request(controller["id"], subject["id"], "ACCESS",
                         received_at="2026-01-05T09:00:00Z")
    verify_request(req["id"], intake_user_id="intake-bdr")
    set_clock("2026-02-02T12:00:00Z")  # Monday; deadline 2026-02-04 (Wed)
    data = validate_success(api.get_dsar_request(req["id"], _PO), 200)
    # Tue 2026-02-03 + Wed 2026-02-04 = 2.
    assert data["business_days_remaining"] == 2


def test_business_days_remaining_floors_at_zero_past_deadline(api):
    """PRD §3.3: "If the deadline lies before the current moment, the result is 0
    rather than a negative number."

    Design: Corner/calculations/business_days_remaining_floors_at_zero_past_deadline_on_read
    """
    controller, subject, _ = setup_registry("GDPR", with_processor=False)
    set_clock("2026-01-05T09:00:00Z")
    req = create_request(controller["id"], subject["id"], "ACCESS",
                         received_at="2026-01-05T09:00:00Z")
    set_clock("2026-02-05T09:00:00Z")  # one day past deadline -> sweep expires it
    data = validate_success(api.get_dsar_request(req["id"], _PO), 200)
    assert data["status"] == "CLOSED_EXPIRED"
    assert data["business_days_remaining"] == 0


def test_deadline_exact_instant_is_not_past(api):
    """PRD §3.2: "and that the request not be past its deadline (if the clock has
    passed deadline_at, the action is refused with ERR_DEADLINE_PASSED)".

    Design: Difficulty/boundary_precision_check/deadline_exact_instant_is_not_past
    """
    controller, subject, _ = setup_registry("GDPR", with_processor=False)
    set_clock("2026-01-05T09:00:00Z")
    req = create_request(controller["id"], subject["id"], "ACCESS",
                         received_at="2026-01-05T09:00:00Z")
    # Clock exactly at the deadline instant — not past, so verify still succeeds.
    set_clock("2026-02-04T09:00:00Z")
    data = validate_success(
        api.verify_identity(req["id"], {"evidence_reference": "ev"},
                            make_intake_agent_headers("intake-exact")), 200)
    assert data["status"] == "DISCOVERY"


def test_deadline_window_inclusive_then_expires_one_second_past(api):
    """PRD §3.8: "every non-terminal request — one whose status is any of
    PENDING_VERIFICATION ... whose deadline_at now lies in the past is expired to
    CLOSED_EXPIRED; each such expiry appends a REQUEST_CLOSED audit entry,
    recomputes the owning controller's open_request_count, and bumps the request's
    version."

    Design: Difficulty/resource_temporal_overlap/deadline_window_inclusive_endpoint_request_clock
    """
    controller, subject, _ = setup_registry("GDPR", with_processor=False)
    set_clock("2026-01-05T09:00:00Z")
    req = create_request(controller["id"], subject["id"], "ACCESS",
                         received_at="2026-01-05T09:00:00Z")
    # One second past deadline_at (2026-02-04T09:00:00Z) -> window closed, swept.
    set_clock("2026-02-04T09:00:01Z")
    data = validate_success(api.get_dsar_request(req["id"], _PO), 200)
    assert data["status"] == "CLOSED_EXPIRED"
