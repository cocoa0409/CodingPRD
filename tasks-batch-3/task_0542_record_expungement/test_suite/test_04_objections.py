"""Objections: filing cascade, the OBJECTION_REVIEW revert loop, and window checks."""
from test_helpers import fixtures, validate_success, validate_error, ApiErrorId
from test_helpers.constants import CLOCK_START, CLOCK_FAR_FUTURE

CLERK = fixtures.CLERK
AGENCY = fixtures.AGENCY


# ---- objection_filed_notification_petition_review (Difficulty) ------------
def test_filing_objection_moves_notification_to_objected(api):
    """PRD §3.6: "A successfully filed objection cascades: the parent notification
    moves from `SERVED` to `OBJECTED`, and that in turn drives the petition from
    `FILED` to `OBJECTION_REVIEW`."

    Design: Difficulty/transitive_cascade/objection_filed_notification_petition_review
    """
    ctx = fixtures.setup_filed_petition_one_served(api)
    n0 = ctx["served_notification"]
    validate_success(api.create_objection(n0["id"], {"grounds": "active case"}, AGENCY),
                     expected_status=201)
    notif = validate_success(api.get_agency_notification(n0["id"], CLERK))
    assert notif["status"] == "OBJECTED"


def test_filing_objection_drives_petition_to_objection_review(api):
    """PRD §3.6: "A successfully filed objection cascades: the parent notification
    moves from `SERVED` to `OBJECTED`, and that in turn drives the petition from
    `FILED` to `OBJECTION_REVIEW`."

    Design: Difficulty/transitive_cascade/objection_filed_notification_petition_review
    """
    ctx = fixtures.setup_filed_petition_one_served(api)
    validate_success(api.create_objection(ctx["served_notification"]["id"],
                                          {"grounds": "active case"}, AGENCY),
                     expected_status=201)
    petition = validate_success(api.get_petition(ctx["petition"]["id"], CLERK))
    assert petition["status"] == "OBJECTION_REVIEW"


# ---- petition_objection_review_revert_cycle (Difficulty) ------------------
def test_overruling_objection_reverts_petition_to_filed(api):
    """PRD §3.6: "A successfully filed objection cascades: the parent notification
    moves from `SERVED` to `OBJECTED`, and that in turn drives the petition from
    `FILED` to `OBJECTION_REVIEW`."
    PRD §3.6: "Overruling it clears the path back: the parent notification moves from
    `OBJECTED` to `CLEARED`, and then, provided no other notification of the same
    petition is still `OBJECTED`, the petition reverts from `OBJECTION_REVIEW` back
    to `FILED`."

    Design: Difficulty/non_linear_state_machine/petition_objection_review_revert_cycle
    """
    ctx = fixtures.setup_filed_petition_one_served(api)
    obj = validate_success(api.create_objection(ctx["served_notification"]["id"],
                                                {"grounds": "related open matter"}, AGENCY),
                           expected_status=201)
    after_file = validate_success(api.get_petition(ctx["petition"]["id"], CLERK))
    assert after_file["status"] == "OBJECTION_REVIEW"
    validate_success(api.transition_objection(obj["id"], {"to_status": "OVERRULED"}, CLERK))
    after_overrule = validate_success(api.get_petition(ctx["petition"]["id"], CLERK))
    assert after_overrule["status"] == "FILED", "OVERRULED loops the petition back to FILED, not forward"


def test_overruling_objection_clears_parent_notification(api):
    """PRD §3.6: "Overruling it clears the path back: the parent notification moves
    from `OBJECTED` to `CLEARED`, and then, provided no other notification of the
    same petition is still `OBJECTED`, the petition reverts from `OBJECTION_REVIEW`
    back to `FILED`."

    Design: Difficulty/non_linear_state_machine/petition_objection_review_revert_cycle
    """
    ctx = fixtures.setup_filed_petition_one_served(api)
    n0 = ctx["served_notification"]
    obj = validate_success(api.create_objection(n0["id"], {"grounds": "related open matter"}, AGENCY),
                           expected_status=201)
    validate_success(api.transition_objection(obj["id"], {"to_status": "OVERRULED"}, CLERK))
    notif = validate_success(api.get_agency_notification(n0["id"], CLERK))
    assert notif["status"] == "CLEARED"


# ---- Corner: objection windows --------------------------------------------
def test_objection_after_deadline_rejected_window_closed(api):
    """PRD §3.6: "The objection may be filed only if the current time is at or before
    the notification's `objection_deadline`; an objection filed after the deadline is
    rejected with `ERR_OBJECTION_WINDOW_CLOSED` (409)."

    Design: Corner/state_machines/objection_after_deadline_window_closed
    """
    ctx = fixtures.setup_filed_petition_one_served(api)  # served at CLOCK_START
    # Advance far past any day-scale objection_deadline, so the window is closed for
    # any positive window length.
    fixtures.set_clock(api, CLOCK_FAR_FUTURE)
    resp = api.create_objection(ctx["served_notification"]["id"], {"grounds": "late"}, AGENCY)
    validate_error(resp, ApiErrorId.ERR_OBJECTION_WINDOW_CLOSED.value)


def test_clear_before_deadline_rejected_window_open(api):
    """PRD §3.5: "clearing is permitted only when the current time is at or after
    `objection_deadline` (attempting to clear before the deadline is rejected with
    `ERR_OBJECTION_WINDOW_OPEN`, 409) and only when no objection is still outstanding
    (`REQUESTED`) on that notification."

    Design: Corner/state_machines/notification_clear_before_deadline_window_open
    """
    ctx = fixtures.setup_filed_petition_one_served(api)  # served at CLOCK_START, clock unchanged
    # At the serve instant the deadline (served_at + window) is strictly in the future
    # for any positive window, so clearing now is before the deadline.
    resp = api.transition_agency_notification(
        ctx["served_notification"]["id"], {"to_status": "CLEARED"}, CLERK)
    validate_error(resp, ApiErrorId.ERR_OBJECTION_WINDOW_OPEN.value)
