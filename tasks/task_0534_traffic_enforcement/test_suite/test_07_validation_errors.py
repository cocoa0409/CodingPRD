"""Business-validation breadth: duplicates, owner lookup, contest window, reduction
range, nothing-owed, payment-exists, calibration date order.

Translates the corner `validations` section instances (excluding the stub
error_calibration_lapsed_isolated, owned by the difficulty index).
"""
import pytest
from test_helpers import (
    get_success_data, validate_error,
    create_program, create_camera, add_calibration, create_owner,
    capture_citation, review_to_cited, set_clock, file_contest,
    schedule_hearing, initiate_payment, settle_to_cleared,
    create_camera_payload, create_owner_payload, create_calibration_payload,
    create_citation_payload, review_payload, create_contest_payload,
    create_payment_payload, rule_payload,
    setup_cited_citation, setup_hearing_scheduled,
    TEST_USERS, make_review_officer_headers, make_registered_owner_headers,
    make_adjudicator_headers,
)

PA = TEST_USERS["program_admin_headers"]
RO = make_review_officer_headers("ro-1")


def test_duplicate_intersection_code_rejected(api):
    """PRD §3.1: "The `intersection_code` must be unique within its program among all
    cameras whose `status` is not `DECOMMISSIONED`; a collision is rejected with
    `ERR_DUPLICATE` (HTTP 409)."

    Design: Corner/validations/duplicate_intersection_code_rejected
    """
    program = create_program()
    create_camera(program["id"], intersection_code="INT-1", camera_type="RED_LIGHT")
    res = api.create_camera(
        create_camera_payload(program["id"], intersection_code="INT-1",
                              camera_type="SPEED", speed_limit_mph=40), PA)
    validate_error(res, "ERR_DUPLICATE")


def test_duplicate_plate_owner_rejected(api):
    """PRD §3.2: "The `plate_number` must be unique within its program; a duplicate
    registration is rejected with `ERR_DUPLICATE`."

    Design: Corner/validations/duplicate_plate_owner_rejected
    """
    program = create_program()
    create_owner(program["id"], plate_number="ABC123", full_name="Pat")
    res = api.create_owner(
        create_owner_payload(program["id"], plate_number="ABC123", full_name="Other",
                             mailing_address="2 St"), PA)
    validate_error(res, "ERR_DUPLICATE")


def test_owner_lookup_failed_on_approve(api):
    """PRD §3.3: "there must be a `RegisteredOwner` in this program whose
    `plate_number` equals the citation's `captured_plate_number`. If no such owner
    exists, the approval is rejected with `ERR_OWNER_LOOKUP_FAILED` (HTTP 422)."

    Design: Corner/validations/owner_lookup_failed_on_approve
    """
    program = create_program()
    camera = create_camera(program["id"], camera_type="RED_LIGHT")
    add_calibration(camera["id"])  # valid coverage, isolates owner lookup
    citation = capture_citation(program["id"], camera["id"],
                                citation_overrides={"captured_plate_number": "GHOST9"})
    res = api.review_citation(citation["id"], review_payload("APPROVE"), RO)
    validate_error(res, "ERR_OWNER_LOOKUP_FAILED")


def test_contest_after_deadline_window_closed(api):
    """PRD §3.5: "the current logical clock must be at or before the citation's
    `due_at_utc`; a filing after the due instant is rejected with
    `ERR_CONTEST_WINDOW_CLOSED` (HTTP 422)."

    Design: Corner/validations/contest_after_deadline_window_closed
    """
    program = create_program()
    camera = create_camera(program["id"], camera_type="RED_LIGHT")
    add_calibration(camera["id"])
    owner = create_owner(program["id"], plate_number="ABC123", full_name="Pat")
    citation = capture_citation(
        program["id"], camera["id"],
        citation_overrides={"event_at_utc": "2026-05-01T00:00:00Z"})
    cited = review_to_cited(citation["id"])
    set_clock("2026-06-01T00:00:00Z")
    res = api.create_contest(
        citation["id"],
        create_contest_payload(owner["id"], owner["portal_access_pin"],
                               cited["version"]),
        make_registered_owner_headers(owner["id"]))
    validate_error(res, "ERR_CONTEST_WINDOW_CLOSED")
    unchanged = get_success_data(api.get_citation(citation["id"], PA))
    assert unchanged["status"] == "CITED"


def test_reduced_amount_out_of_range_rejected(api):
    """PRD §3.5: "This value must be present and strictly greater than zero and
    strictly less than the citation's `assessed_amount_cents` minus the program's
    `admin_fee_cents` (that is, strictly less than the statutory fine portion
    excluding the admin fee); a missing or out-of-range value is rejected with
    `ERR_INVALID_REDUCTION` (HTTP 422)."

    Design: Corner/validations/reduced_amount_out_of_range_rejected
    """
    ctx = setup_hearing_scheduled()
    cit = ctx["citation"]
    hearing = ctx["hearing"]
    set_clock("2026-05-15T11:00:00Z")
    # assessed 12500 - admin 2500 = 10000; reduced_amount_cents == 10000 is not < 10000.
    res = api.rule_hearing(
        hearing["id"],
        rule_payload("REDUCED", hearing["version"], reduced_amount_cents=10000),
        make_adjudicator_headers("adj-9"))
    validate_error(res, "ERR_INVALID_REDUCTION")
    unchanged = get_success_data(api.get_citation(cit["id"], PA))
    assert unchanged["status"] == "HEARING_SCHEDULED"


def test_payment_on_zero_owed_rejected(api):
    """PRD §3.7: "a payment may not be initiated against a citation that owes nothing
    — one that is `VOID`, `ADJUDICATED_DISMISSED`, or already `PAID` — with either
    violation rejected as `ERR_NOTHING_OWED` (HTTP 422)."

    Design: Corner/validations/payment_on_zero_owed_rejected
    """
    ctx = setup_cited_citation()
    cit = ctx["citation"]
    get_success_data(api.void_citation(cit["id"], PA))
    res = api.create_payment(cit["id"], create_payment_payload(5000, "CARD"), PA)
    validate_error(res, "ERR_NOTHING_OWED")


def test_void_with_cleared_payment_rejected(api):
    """PRD §3.8: "Additionally, a void is refused if any cleared payment exists
    against the citation, rejected with `ERR_PAYMENT_EXISTS` (HTTP 409)."

    Design: Corner/validations/void_with_cleared_payment_rejected
    """
    ctx = setup_cited_citation()
    cit = ctx["citation"]
    payment = initiate_payment(cit["id"], 5000)  # partial; citation stays CITED
    settle_to_cleared(payment["id"])
    still_cited = get_success_data(api.get_citation(cit["id"], PA))
    assert still_cited["status"] == "CITED"
    res = api.void_citation(cit["id"], PA)
    validate_error(res, "ERR_PAYMENT_EXISTS")
    unchanged = get_success_data(api.get_citation(cit["id"], PA))
    assert unchanged["status"] == "CITED"


def test_calibration_invalid_date_order_rejected(api):
    """PRD §3.1: "The expiry must be strictly after the performance time —
    `valid_until_utc` must be later than `performed_at_utc` — and a record that
    violates this ordering is rejected with `ERR_INVALID_REQUEST`."

    Design: Corner/validations/calibration_invalid_date_order_rejected
    """
    program = create_program()
    camera = create_camera(program["id"], camera_type="RED_LIGHT")
    res = api.create_calibration(
        camera["id"],
        create_calibration_payload(performed_at_utc="2026-04-01T00:00:00Z",
                                   valid_until_utc="2026-04-01T00:00:00Z"), PA)
    validate_error(res, "ERR_INVALID_REQUEST")
