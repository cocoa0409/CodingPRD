"""Due-diligence outreach: the 30-day notice spacing buffer and owner reactivation.

Translates queue A (resource_temporal_overlap/notice_buffer_window) and queue B
(state_machines/property_reactivates_on_owner_response).
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, factories as f, fixtures,
)
from test_helpers.test_users import make_holder_headers


def _dormant_with_first_notice(api):
    """Holder + DD-required property, DORMANT, first notice sent at clock 2026-05-01."""
    holder = fixtures.create_holder(api)
    hh = make_holder_headers(holder["id"])
    pt = fixtures.create_property_type(api, code="AC01", dormancy_basis="LAST_ACTIVITY",
                                       dormancy_period_years=3, interest_bearing=False,
                                       due_diligence_required=True, due_diligence_min_days=60)
    prop = validate_success(api.create_property(f.create_property_payload(
        holder["id"], pt["id"], owner_last_known_state="CA", amount_cents=50000,
        last_activity_date="2020-01-01T00:00:00Z"), hh), 201)
    fixtures.set_clock(api, "2026-05-01T00:00:00Z")
    validate_success(api.evaluate_dormancy(prop["id"], hh), 200)
    notice = validate_success(api.create_notice(prop["id"], f.notice_payload("MAIL"), hh), 201)
    return holder, hh, prop, notice


# ---------------------------------------------------------------------------
# Difficulty/resource_temporal_overlap/notice_buffer_window
# ---------------------------------------------------------------------------
def test_second_notice_within_buffer_rejected(api):
    """PRD §3.3: "a new notice may not be sent within DUE_DILIGENCE_NOTICE_BUFFER_DAYS —
    that is, within 30 days — of an existing notice on the same property. A notice that
    falls inside that 30-day window is rejected with ERR_NOTICE_TOO_SOON (HTTP 409)."

    First notice at 2026-05-01; a second at 2026-05-20 (19 days later) falls inside the
    30-day window.

    Design: Difficulty/resource_temporal_overlap/notice_buffer_window
    """
    holder, hh, prop, notice = _dormant_with_first_notice(api)
    fixtures.set_clock(api, "2026-05-20T00:00:00Z")
    validate_error(api.create_notice(prop["id"], f.notice_payload("EMAIL"), hh),
                   ApiErrorId.ERR_NOTICE_TOO_SOON.value)


def test_follow_up_notice_outside_buffer_allowed(api):
    """PRD §3.3: "A holder may send follow-up notices. A second notice against a property
    already in DUE_DILIGENCE creates an additional DueDiligenceNotice but leaves the property
    in DUE_DILIGENCE (a self-transition that does not change status)."
    PRD §3.3: "a new notice may not be sent within DUE_DILIGENCE_NOTICE_BUFFER_DAYS — that is,
    within 30 days — of an existing notice on the same property."

    A follow-up sent 2026-06-20 (~50 days after the first) is outside the 30-day window and
    succeeds; the property stays DUE_DILIGENCE.

    Design: Difficulty/resource_temporal_overlap/notice_buffer_window
    """
    holder, hh, prop, notice = _dormant_with_first_notice(api)
    fixtures.set_clock(api, "2026-06-20T00:00:00Z")
    validate_success(api.create_notice(prop["id"], f.notice_payload("EMAIL"), hh), 201)
    after = validate_success(api.get_property(prop["id"], hh), 200)
    assert after["status"] == "DUE_DILIGENCE", \
        f"follow-up notice must leave property DUE_DILIGENCE, got {after['status']}"


# ---------------------------------------------------------------------------
# Corner/state_machines/property_reactivates_on_owner_response
# ---------------------------------------------------------------------------
def test_owner_response_reactivates_property(api):
    """PRD §3.3: "Recording a response sets the notice's responded to true and its
    responded_at to the current logical-clock instant, and it reactivates the property by
    returning it from DUE_DILIGENCE to ACTIVE — the owner has effectively reclaimed the
    property, which leaves the escheat pipeline."

    Design: Corner/state_machines/property_reactivates_on_owner_response
    """
    holder, hh, prop, notice = _dormant_with_first_notice(api)
    data = validate_success(api.record_response(notice["id"], hh), 200)
    assert data["responded"] is True, "record-response must set responded true"
    after = validate_success(api.get_property(prop["id"], hh), 200)
    assert after["status"] == "ACTIVE", f"property must return to ACTIVE, got {after['status']}"
