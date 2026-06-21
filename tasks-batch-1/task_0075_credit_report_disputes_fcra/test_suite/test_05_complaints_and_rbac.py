"""Regulatory complaints, authentication, validation ordering, and RBAC.

Translates queue B (Corner) state_machines (complaint), validations, and rbac
instances.
"""
from test_helpers import (
    api_client,
    validate_success, validate_error,
    ApiErrorId,
    make_bureau_headers, make_regulator_headers, make_consumer_headers,
    make_furnisher_headers,
    setup_consumer_furnisher_file, setup_complaint_under_review,
    set_clock, get_file_version, create_tradeline, file_dispute,
    create_consumer, create_furnisher, create_credit_file,
)

BUREAU = make_bureau_headers()
REGULATOR = make_regulator_headers()


# ---------------------------------------------------------------------------
# Corner: state_machines — complaint flow
# ---------------------------------------------------------------------------

def test_complaint_review_from_submitted(api):
    """PRD §3.8: "the regulator moves it from SUBMITTED to UNDER_REVIEW; this
    transition requires the complaint to currently be SUBMITTED, otherwise
    ERR_INVALID_STATE."

    Design: Corner/state_machines/complaint_review_from_submitted_valid
    """
    consumer, furnisher, cfile = setup_consumer_furnisher_file()
    set_clock("2026-01-05T00:00:00.000Z")
    tl = create_tradeline(cfile["id"], furnisher["id"], balance_cents=20000)
    dispute = file_dispute(consumer["id"], cfile["id"], tl["id"], get_file_version(cfile["id"]),
                           dispute_reason="NOT_MINE", clock_mode="CALENDAR")
    complaint = validate_success(
        api.create_complaint({"dispute_id": dispute["id"], "narrative": "Please review."},
                             make_consumer_headers(consumer["id"])),
        201,
    )
    reviewed = validate_success(api.review_complaint(complaint["id"], REGULATOR))
    assert reviewed["status"] == "UNDER_REVIEW"


def test_complaint_premature_uphold_rejected(api):
    """PRD §3.8: "An UPHOLD decision moves it to UPHELD, but only if the referenced
    dispute has itself reached a contestable terminal state — its status must be
    AUTO_DELETED or RESOLVED_VERIFY ... upholding while the dispute is in any other
    state is rejected with ERR_COMPLAINT_PREMATURE."

    Design: Corner/state_machines/complaint_premature_uphold_before_terminal_dispute
    """
    consumer, furnisher, cfile, tl, dispute, complaint = setup_complaint_under_review()
    assert dispute["status"] == "INVESTIGATING"
    resp = api.adjudicate_complaint(complaint["id"], {"decision": "UPHOLD"}, REGULATOR)
    validate_error(resp, ApiErrorId.ERR_COMPLAINT_PREMATURE.value)


def test_complaint_uphold_after_auto_deleted(api):
    """PRD §3.8: "An UPHOLD decision moves it to UPHELD, but only if the referenced
    dispute has itself reached a contestable terminal state — its status must be
    AUTO_DELETED or RESOLVED_VERIFY"

    Design: Corner/state_machines/complaint_adjudicate_uphold_after_auto_deleted
    """
    consumer, furnisher, cfile = setup_consumer_furnisher_file()
    set_clock("2026-01-05T00:00:00.000Z")
    tl = create_tradeline(cfile["id"], furnisher["id"], balance_cents=20000)
    dispute = file_dispute(consumer["id"], cfile["id"], tl["id"], get_file_version(cfile["id"]),
                           dispute_reason="NOT_MINE", clock_mode="CALENDAR")
    complaint = validate_success(
        api.create_complaint({"dispute_id": dispute["id"], "narrative": "Investigate."},
                             make_consumer_headers(consumer["id"])),
        201,
    )
    validate_success(api.review_complaint(complaint["id"], REGULATOR))
    # Advance the clock past the deadline -> dispute AUTO_DELETED.
    api.clock_advance("2026-02-10T00:00:00.000Z", BUREAU)
    upheld = validate_success(api.adjudicate_complaint(complaint["id"], {"decision": "UPHOLD"}, REGULATOR))
    assert upheld["status"] == "UPHELD"
    d_after = validate_success(api.get_dispute(dispute["id"], BUREAU))
    assert d_after["status"] == "AUTO_DELETED"


# ---------------------------------------------------------------------------
# Corner: validations — auth + existence-before-ownership
# ---------------------------------------------------------------------------

def test_missing_auth_headers_returns_unauthenticated(api):
    """PRD §2.1: "Every request to a non-public endpoint must be authenticated
    through two mandatory HTTP headers: X-User-ID, which identifies the acting user,
    and X-User-Role ... If either header is missing or malformed on an endpoint that
    requires authentication, the request is rejected with ERR_UNAUTHENTICATED."

    Design: Corner/validations/missing_auth_headers_returns_unauthenticated
    """
    consumer = create_consumer()
    furnisher = create_furnisher()
    resp = api.suspend_furnisher(furnisher["id"], headers={"Content-Type": "application/json"})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


def test_existence_check_before_owner_check(api):
    """PRD §2.7: "then existence of every path and foreign-key-referenced resource,
    left to right (ERR_NOT_FOUND); then resource ownership for entity-backed actors
    (ERR_NOT_RESOURCE_OWNER)"

    Design: Corner/validations/existence_check_before_owner_check
    """
    consumer = create_consumer()
    cfile = create_credit_file(consumer["id"])
    v = get_file_version(cfile["id"])
    resp = api.create_dispute(
        {"credit_file_id": cfile["id"], "tradeline_id": "22222222-2222-4222-8222-222222222222",
         "dispute_reason": "NOT_MINE", "clock_mode": "CALENDAR", "expected_credit_file_version": v},
        make_consumer_headers(consumer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


# ---------------------------------------------------------------------------
# Corner: rbac — peer roles
# ---------------------------------------------------------------------------

def test_consumer_cannot_open_investigation(api):
    """PRD §2.1: "When the acting role is present and well-formed but is not permitted
    to perform the requested operation, the request is rejected with ERR_FORBIDDEN_ROLE."
    PRD Endpoint table: "POST /disputes/{disputeId}/open-investigation | Open the
    reinvestigation | CreditBureau"

    Design: Corner/rbac/consumer_cannot_open_investigation
    """
    consumer, furnisher, cfile = setup_consumer_furnisher_file()
    set_clock("2026-01-05T00:00:00.000Z")
    tl = create_tradeline(cfile["id"], furnisher["id"], balance_cents=20000)
    dispute = file_dispute(consumer["id"], cfile["id"], tl["id"], get_file_version(cfile["id"]),
                           dispute_reason="NOT_MINE", clock_mode="CALENDAR")
    resp = api.open_investigation(dispute["id"], make_consumer_headers(consumer["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_furnisher_cannot_respond_to_other_furnishers_reverification(api):
    """PRD §2.1: "Furnisher is likewise entity-backed: when X-User-Role is Furnisher,
    the X-User-ID is the id of the acting Furnisher, and ownership checks on a
    reverification response compare the target reverification request's furnisher_id
    to X-User-ID."

    Design: Corner/rbac/furnisher_cannot_respond_to_other_furnishers_reverification
    """
    consumer, furnisher_a, cfile = setup_consumer_furnisher_file()
    furnisher_b = create_furnisher()
    set_clock("2026-01-05T00:00:00.000Z")
    tl = create_tradeline(cfile["id"], furnisher_a["id"], balance_cents=20000)
    dispute = file_dispute(consumer["id"], cfile["id"], tl["id"], get_file_version(cfile["id"]),
                           dispute_reason="NOT_MINE", clock_mode="CALENDAR")
    validate_success(api.open_investigation(dispute["id"], BUREAU))
    rv = validate_success(api.create_reverification({"dispute_id": dispute["id"], "furnisher_id": furnisher_a["id"]}, BUREAU), 201)
    resp = api.respond_reverification(rv["id"], {"response_type": "VERIFY"}, make_furnisher_headers(furnisher_b["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)


def test_consumer_cannot_dispute_on_anothers_file(api):
    """PRD §2.1: "Consumer is entity-backed: when X-User-Role is Consumer, the
    X-User-ID is the id of the acting Consumer entity, and ownership checks on any
    resource that references a consumer — a dispute, a security freeze, a regulatory
    complaint, or the credit file underneath them — compare that resource's consumer
    foreign key ... to X-User-ID."

    Design: Corner/rbac/consumer_cannot_dispute_on_anothers_file
    """
    consumer_a, furnisher, cfile = setup_consumer_furnisher_file()
    consumer_b = create_consumer()
    set_clock("2026-01-05T00:00:00.000Z")
    tl = create_tradeline(cfile["id"], furnisher["id"], balance_cents=20000)
    v = get_file_version(cfile["id"])
    resp = api.create_dispute(
        {"credit_file_id": cfile["id"], "tradeline_id": tl["id"], "dispute_reason": "NOT_MINE",
         "clock_mode": "CALENDAR", "expected_credit_file_version": v},
        make_consumer_headers(consumer_b["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)
