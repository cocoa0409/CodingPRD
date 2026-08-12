"""Office appointment slots: fixed 30-minute half-open windows
(PRD §3.6)."""
from test_helpers import (
    validate_error,
    setup_closed_final_year, list_member_certificates,
    create_redemption_request, submit_request,
    set_clock, make_member_headers,
)


def _two_members_with_certificates():
    """CLOSED_FINAL year with two patrons, each holding ACTIVE certificates,
    clock moved to the redemption era."""
    ctx = setup_closed_final_year(
        [
            {"member_key": "first", "commodity": "CORN", "gross_bushels": 100},
            {"member_key": "second", "commodity": "CORN", "gross_bushels": 100},
        ],
        net_margin_cents=200000, retained_reserve_pct=0.20,
        qualified_payout_pct=0.30,
    )
    first = ctx["members"]["first"]
    second = ctx["members"]["second"]
    cert_first = list_member_certificates(
        first["id"], headers=make_member_headers(first["id"]),
    )[0]
    cert_second = list_member_certificates(
        second["id"], headers=make_member_headers(second["id"]),
    )[0]
    set_clock("2031-09-01T00:00:00Z")
    return first, cert_first, second, cert_second


def test_overlapping_appointment_rejected_at_submission(api):
    """PRD §3.6: "Office appointments use half-open 30-minute windows: a
    request booked at `appointment_at` occupies the interval from that
    instant up to — but not including — 30 minutes later, and two requests at
    the same office conflict only when their intervals overlap. Adjacent
    appointments, where one ends exactly when the other begins, do not
    conflict."
    PRD §3.6: "The conflict check runs at submission and again at
    disbursement against all requests at the same office in `UNDER_REVIEW` or
    `APPROVED` status; a conflict is rejected with `ERR_APPOINTMENT_CONFLICT`
    (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/office_appointment_slot_half_open_no_double_booking
    """
    first, cert_first, second, cert_second = _two_members_with_certificates()
    req_a = create_redemption_request(
        first["id"], "RETIREMENT", [cert_first["id"]], 100,
        "2031-10-01T10:00:00Z",
    )
    submitted_a = submit_request(req_a["id"], first["id"])
    assert submitted_a["status"] == "UNDER_REVIEW"
    # 10:15 lies inside [10:00, 10:30) — overlapping.
    req_b = create_redemption_request(
        second["id"], "RETIREMENT", [cert_second["id"]], 100,
        "2031-10-01T10:15:00Z",
    )
    assert req_b["status"] == "PENDING"
    res = api.submit_for_review(
        req_b["id"], make_member_headers(second["id"]),
    )
    validate_error(res, "ERR_APPOINTMENT_CONFLICT", expected_status=409)


def test_adjacent_appointment_allowed(api):
    """PRD §3.6: "Adjacent appointments, where one ends exactly when the
    other begins, do not conflict."

    Design: Difficulty/resource_temporal_overlap/office_appointment_slot_half_open_no_double_booking
    """
    first, cert_first, second, cert_second = _two_members_with_certificates()
    req_a = create_redemption_request(
        first["id"], "RETIREMENT", [cert_first["id"]], 100,
        "2031-10-01T10:00:00Z",
    )
    submitted_a = submit_request(req_a["id"], first["id"])
    assert submitted_a["status"] == "UNDER_REVIEW"
    # 10:30 begins exactly when [10:00, 10:30) ends — no overlap.
    req_b = create_redemption_request(
        second["id"], "RETIREMENT", [cert_second["id"]], 100,
        "2031-10-01T10:30:00Z",
    )
    submitted_b = submit_request(req_b["id"], second["id"])
    assert submitted_b["status"] == "UNDER_REVIEW", (
        "Back-to-back slots must not conflict; got "
        f"{submitted_b['status']}"
    )
