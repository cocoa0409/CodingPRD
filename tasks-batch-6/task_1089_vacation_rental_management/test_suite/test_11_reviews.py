"""Review lifecycle and review creation gates."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    TEST_USERS, ApiErrorId,
    create_review_payload, fixtures,
)

PM = TEST_USERS["property_manager_headers"]


def _checked_out_booking(api):
    fixtures.set_clock(api, "2026-06-01T00:00:00Z")
    listed = fixtures.create_listed_property(api)
    pid = listed["property"]["id"]
    guest = fixtures.create_guest(api)
    booking = fixtures.create_confirmed_booking(api, pid, guest["id"], "2026-06-05T00:00:00Z", "2026-06-06T00:00:00Z")
    fixtures.set_clock(api, "2026-06-10T00:00:00Z")
    fixtures.check_in_booking(api, booking["id"])
    fixtures.check_out_booking(api, booking["id"])
    return pid, booking["id"]


def test_review_publish_then_suppress(api):
    """PRD §3.9: "A property manager may publish it (`SUBMITTED → PUBLISHED`) or suppress it
    (`SUBMITTED → SUPPRESSED`, or `PUBLISHED → SUPPRESSED`); `SUPPRESSED` is terminal."

    Design: Corner/state_machines/review_publish_then_suppress
    """
    pid, booking_id = _checked_out_booking(api)
    review = get_success_data(api.create_review(create_review_payload(booking_id, pid, rating=5, author_role="GUEST"), PM))
    published = get_success_data(api.publish_review(review["id"], PM))
    assert published["status"] == "PUBLISHED"
    suppressed = get_success_data(api.suppress_review(review["id"], PM))
    assert suppressed["status"] == "SUPPRESSED"


def test_review_on_non_checked_out_booking_rejected(api):
    """PRD §3.9: "The booking must be in `CHECKED_OUT`, else `ERR_BOOKING_NOT_CHECKED_OUT`."

    Design: Corner/validations/review_on_non_checked_out_booking_rejected
    """
    fixtures.set_clock(api, "2026-06-01T00:00:00Z")
    listed = fixtures.create_listed_property(api)
    pid = listed["property"]["id"]
    guest = fixtures.create_guest(api)
    booking = fixtures.create_booking(api, pid, guest["id"], "2026-07-01T00:00:00Z", "2026-07-04T00:00:00Z")  # HOLD
    resp = api.create_review(create_review_payload(booking["id"], pid, rating=5, author_role="GUEST"), PM)
    validate_error(resp, ApiErrorId.ERR_BOOKING_NOT_CHECKED_OUT.value)


def test_review_rating_out_of_range_returns_validation(api):
    """PRD §2.6: "Body well-formedness — required fields present, enum values legal, and
    numeric ranges satisfied (a `rating` between 1 and 5 inclusive ...), else `ERR_VALIDATION`
    (422)." Body checks (priority 4) precede state checks (priority 5).

    Design: Corner/validations/review_rating_out_of_range_returns_validation
    """
    fixtures.set_clock(api, "2026-06-01T00:00:00Z")
    listed = fixtures.create_listed_property(api)
    pid = listed["property"]["id"]
    guest = fixtures.create_guest(api)
    booking = fixtures.create_booking(api, pid, guest["id"], "2026-07-01T00:00:00Z", "2026-07-04T00:00:00Z")  # HOLD
    # rating 6 is out of range (invalid body) even though the booking is also not checked out
    resp = api.create_review(create_review_payload(booking["id"], pid, rating=6, author_role="GUEST"), PM)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)
