"""Composite setup helpers for the transcript ordering domain.

Every helper builds its preconditions from scratch using only PRD-declared
endpoints (the server restarts before every test, so no state is shared).
Identity threading: after creating a Student, ownership-gated calls use
make_student_headers(student["id"]) — never the shared Student constant.
"""
import itertools

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    create_fee_schedule_payload,
    create_order_payload,
    create_recipient_payload,
    create_student_payload,
)
from .test_users import TEST_USERS, make_student_headers

_key_counter = itertools.count(1)


def _admin():
    return TEST_USERS["admin_headers"]


def _operator():
    return TEST_USERS["operator_headers"]


def _reviewer():
    return TEST_USERS["reviewer_headers"]


def _bursar():
    return TEST_USERS["bursar_headers"]


def _library():
    return TEST_USERS["library_headers"]


def _requester():
    return TEST_USERS["requester_headers"]


def _unique_key(prefix: str) -> str:
    return f"{prefix}-{next(_key_counter)}"


# ---------------------------------------------------------------------------
# Tier 0: clock + schedule + base entities
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str):
    """Advance the server logical clock."""
    resp = api_client.set_clock({"to_iso8601": to_iso8601}, _admin())
    return get_success_data(resp)


def reset_clock():
    """Return the logical clock to its startup default (PRD §2.4)."""
    return set_clock(TEST_DEFAULTS["CLOCK_DEFAULT"])


def create_fee_schedule(**overrides):
    """Register a fee schedule. Returns the created FeeSchedule."""
    resp = api_client.create_fee_schedule(create_fee_schedule_payload(**overrides), _admin())
    return get_success_data(resp)


def create_student(**overrides):
    """Register a student. Returns the created Student."""
    resp = api_client.create_student(create_student_payload(**overrides), _admin())
    return get_success_data(resp)


def create_recipient(**overrides):
    """Register a recipient. Returns the created Recipient."""
    resp = api_client.create_recipient(create_recipient_payload(**overrides), _admin())
    return get_success_data(resp)


def publish_record(student_id: str, **overrides):
    """Publish a StudentRecord snapshot for a student."""
    payload = {
        "effective_term": overrides.pop("effective_term", "2026-SPR"),
        "earned_credits": overrides.pop("earned_credits", 3),
        "courses": overrides.pop("courses", [{"grade_points": 4.0, "credits": 3}]),
    }
    payload.update(overrides)
    resp = api_client.publish_student_record(student_id, payload, _admin())
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 1/2: order hierarchy — order + line items (+ optional identity verify)
# ---------------------------------------------------------------------------

def create_draft_order(student_id: str, lines=None, **order_overrides):
    """Create a DRAFT order owned by student_id and attach line items.

    lines: list of dicts with keys recipient_id, delivery_kind, quantity.
           Defaults to no lines (caller adds them).
    Returns the order dict refreshed after the last line-item add.
    """
    student_headers = make_student_headers(student_id)
    payload = create_order_payload(student_id=student_id, **order_overrides)
    order = get_success_data(api_client.create_order(payload, student_headers))
    for line in (lines or []):
        added = get_success_data(
            api_client.add_line_item(
                order["id"],
                {
                    "recipient_id": line["recipient_id"],
                    "delivery_kind": line.get("delivery_kind", "EMAIL_PDF"),
                    "quantity": line.get("quantity", 1),
                    "expected_order_version": order["version"],
                },
                student_headers,
            )
        )
        order = get_success_data(api_client.get_order(order["id"], student_headers))
        assert added["id"]
    return order


def create_verified_identity(student_id: str, order_id: str) -> dict:
    """Start + confirm an IdentityVerification for the (student, order) pair."""
    student_headers = make_student_headers(student_id)
    idv = get_success_data(
        api_client.create_identity_verification(
            {"student_id": student_id, "order_id": order_id, "method": "SSN_DOB"},
            student_headers,
        )
    )
    confirmed = get_success_data(
        api_client.confirm_identity_verification(
            idv["id"], {"verification_token": idv["verification_token"]}, student_headers
        )
    )
    assert confirmed["status"] == "VERIFIED"
    return confirmed


# ---------------------------------------------------------------------------
# Tier 3: full lifecycle shortcuts
# ---------------------------------------------------------------------------

def create_submitted_order(student_id: str, lines, **order_overrides):
    """DRAFT order + line items + VERIFIED identity + submit.

    Returns the order dict as returned by the submit call (post-submit state).
    """
    student_headers = make_student_headers(student_id)
    order = create_draft_order(student_id, lines=lines, **order_overrides)
    create_verified_identity(student_id, order["id"])
    order = get_success_data(api_client.get_order(order["id"], student_headers))
    submitted = get_success_data(
        api_client.submit_order(
            order["id"], {"expected_order_version": order["version"]}, student_headers
        )
    )
    return submitted


def create_authorized_payment(order_id: str, student_id: str, **overrides):
    """Authorize a payment for a submitted order. Returns the Payment."""
    student_headers = make_student_headers(student_id)
    payload = {"order_id": order_id, "idempotency_key": _unique_key("pay")}
    payload.update(overrides)
    return get_success_data(api_client.create_payment(payload, student_headers))


def create_captured_payment(order_id: str, student_id: str, **overrides):
    """Authorize + capture. Returns the CAPTURED Payment."""
    payment = create_authorized_payment(order_id, student_id, **overrides)
    return get_success_data(api_client.capture_payment(payment["id"], _operator()))


def create_delivered_order(student_id: str, lines, **order_overrides):
    """Full lifecycle through DELIVERED: submit, authorize, capture, dispatch,
    mark delivered. Returns (order, payment, line_ids)."""
    order = create_submitted_order(student_id, lines=lines, **order_overrides)
    payment = create_captured_payment(order["id"], student_id)
    line_list, _meta = _list_order_lines(order["id"], student_id)
    for line in line_list:
        get_success_data(api_client.dispatch_line_item(line["id"], _operator()))
        get_success_data(api_client.mark_line_item_delivered(line["id"], _operator()))
    order = get_success_data(
        api_client.get_order(order["id"], make_student_headers(student_id))
    )
    assert order["fulfillment_status"] == "DELIVERED"
    return order, payment, [l["id"] for l in line_list]


def _list_order_lines(order_id: str, student_id: str):
    resp = api_client.list_order_line_items(
        order_id, make_student_headers(student_id), params={"limit": 100}
    )
    body = resp.json()
    return body["data"], body.get("meta", {})


# ---------------------------------------------------------------------------
# Tier 2: holds / consent / verification helpers
# ---------------------------------------------------------------------------

def create_hold(student_id: str, role: str = "bursar", **overrides):
    """Place a hold on a student. role picks the office header."""
    role_headers = {
        "bursar": _bursar(),
        "library": _library(),
        "admin": _admin(),
    }[role]
    payload = {"student_id": student_id, "hold_type": "FINANCIAL", "blocking_scope": "OFFICIAL"}
    payload.update(overrides)
    return get_success_data(api_client.create_hold(payload, role_headers))


def create_consent_grant(student_id: str, **overrides):
    """Student grants consent. Returns the ConsentGrant."""
    student_headers = make_student_headers(student_id)
    payload = {
        "student_id": student_id,
        "grantee_name": "Employer Inc",
        "scope": "DEGREE_ONLY",
        "expires_at": "2027-08-01T00:00:00Z",
    }
    payload.update(overrides)
    return get_success_data(api_client.create_consent_grant(payload, student_headers))


def create_verification_request(subject_student_id: str, **overrides):
    """Third-party verification request. Returns the VerificationRequest."""
    payload = {
        "requester_name": "Employer Inc",
        "subject_student_id": subject_student_id,
        "scope": "ENROLLMENT_ONLY",
    }
    payload.update(overrides)
    return get_success_data(api_client.create_verification_request(payload, _requester()))


def create_verification_in_consent_check(subject_student_id: str, **overrides):
    """VerificationRequest walked RECEIVED -> CONSENT_CHECK."""
    vr = create_verification_request(subject_student_id, **overrides)
    return get_success_data(api_client.begin_review_verification_request(vr["id"], _reviewer()))


# ---------------------------------------------------------------------------
# Tier 5: clearinghouse / reissue terminal setups
# ---------------------------------------------------------------------------

def create_batch(**overrides):
    """Open a clearinghouse batch. Returns the batch."""
    payload = {
        "report_period_start": "2026-08-01T00:00:00Z",
        "report_period_end": "2026-09-01T00:00:00Z",
    }
    payload.update(overrides)
    return get_success_data(api_client.create_clearinghouse_batch(payload, _operator()))


def create_reissue_request(original_order_id: str, student_id: str, **overrides):
    """Open a ReissueRequest against a DELIVERED order. Returns the request."""
    payload = {"reason": "NAME_CORRECTION"}
    payload.update(overrides)
    return get_success_data(
        api_client.create_reissue_request(
            original_order_id, payload, make_student_headers(student_id)
        )
    )
