"""Visitor passes: flat/free fee, the half-open overlap rule, the guest-daily
limit, and the ACTIVE-permit precondition.

Translates Difficulty instances (resource_temporal_overlap visitor pass,
boundary_precision_check guest-daily, cross_entity_state_dependency permit-not-
active) and Corner calculation instances.
"""
from test_helpers import (
    validate_success, validate_error,
    create_visitor_pass_payload, refund_payload,
    make_resident_headers,
)
from test_helpers.fixtures import setup_active_permit, issue_visitor_pass, SUP


def _resident(hh_id):
    return make_resident_headers(hh_id)


# --------------------------------------------------------------------------
# Corner/calculations/temporary_pass_charges_flat_fee
# --------------------------------------------------------------------------
def test_temporary_pass_charges_flat_fee(api):
    """PRD §3.7: "its `fee_charged_cents` is the zone's `visitor_pass_fee_cents` for a
    `TEMPORARY` pass and zero for a `GUEST_DAILY` pass."

    Design: Corner/calculations/temporary_pass_charges_flat_fee
    """
    s = setup_active_permit(api, zone_overrides={"guest_pass_daily_limit": 5, "visitor_pass_fee_cents": 500})
    vp = issue_visitor_pass(api, s["household"]["id"], s["permit"]["id"],
                            "2026-05-03T08:00:00.000Z", "2026-05-04T08:00:00.000Z",
                            pass_type="TEMPORARY", guest_plate="GT1")
    assert vp["fee_charged_cents"] == 500
    assert vp["status"] == "ACTIVE"


# --------------------------------------------------------------------------
# Corner/calculations/guest_daily_pass_is_free
# --------------------------------------------------------------------------
def test_guest_daily_pass_is_free(api):
    """PRD §3.7: "its `fee_charged_cents` is the zone's `visitor_pass_fee_cents` for a
    `TEMPORARY` pass and zero for a `GUEST_DAILY` pass."

    Design: Corner/calculations/guest_daily_pass_is_free
    """
    s = setup_active_permit(api, zone_overrides={"guest_pass_daily_limit": 5, "visitor_pass_fee_cents": 500})
    vp = issue_visitor_pass(api, s["household"]["id"], s["permit"]["id"],
                            "2026-05-03T08:00:00.000Z", "2026-05-03T20:00:00.000Z",
                            pass_type="GUEST_DAILY", guest_plate="GD1")
    assert vp["fee_charged_cents"] == 0


# --------------------------------------------------------------------------
# boundary_precision_check / guest_pass_daily_limit_empty_vs_full_day
# --------------------------------------------------------------------------
def test_first_guest_daily_pass_within_limit_succeeds(api):
    """PRD §3.7: "count the household's existing `GUEST_DAILY` passes whose status is
    `ACTIVE` or `EXPIRED` and whose `valid_from` calendar date equals that day; if that
    count is already at or above the limit — so the new pass would be the one past the
    limit — it fails with `ERR_GUEST_PASS_LIMIT` (HTTP 409)."

    Design: Difficulty/boundary_precision_check/guest_pass_daily_limit_empty_vs_full_day
    """
    s = setup_active_permit(api, zone_overrides={"guest_pass_daily_limit": 1})
    vp1 = issue_visitor_pass(api, s["household"]["id"], s["permit"]["id"],
                             "2026-05-02T08:00:00.000Z", "2026-05-02T20:00:00.000Z",
                             pass_type="GUEST_DAILY", guest_plate="GA")
    assert vp1["status"] == "ACTIVE"


def test_second_guest_daily_pass_over_limit_rejected(api):
    """PRD §3.7: "if that count is already at or above the limit — so the new pass
    would be the one past the limit — it fails with `ERR_GUEST_PASS_LIMIT` (HTTP 409)."

    Design: Difficulty/boundary_precision_check/guest_pass_daily_limit_empty_vs_full_day
    """
    s = setup_active_permit(api, zone_overrides={"guest_pass_daily_limit": 1})
    hh_id, permit_id = s["household"]["id"], s["permit"]["id"]
    issue_visitor_pass(api, hh_id, permit_id, "2026-05-02T08:00:00.000Z",
                       "2026-05-02T20:00:00.000Z", pass_type="GUEST_DAILY", guest_plate="GA")
    resp = api.create_visitor_pass(
        create_visitor_pass_payload(hh_id, permit_id, "2026-05-02T09:00:00.000Z",
                                    "2026-05-02T21:00:00.000Z", pass_type="GUEST_DAILY", guest_plate="GB"),
        _resident(hh_id),
    )
    validate_error(resp, "ERR_GUEST_PASS_LIMIT", expected_status=409)


# --------------------------------------------------------------------------
# resource_temporal_overlap / visitor_pass_half_open_adjacent_ok_overlap_rejected
# --------------------------------------------------------------------------
def _two_adjacent_passes(api):
    s = setup_active_permit(api, zone_overrides={"guest_pass_daily_limit": 9})
    hh_id, permit_id = s["household"]["id"], s["permit"]["id"]
    p1 = issue_visitor_pass(api, hh_id, permit_id, "2026-05-02T08:00:00.000Z",
                            "2026-05-02T12:00:00.000Z", pass_type="TEMPORARY", guest_plate="GX")
    p2 = issue_visitor_pass(api, hh_id, permit_id, "2026-05-02T12:00:00.000Z",
                            "2026-05-02T16:00:00.000Z", pass_type="TEMPORARY", guest_plate="GX")
    return hh_id, permit_id, p1, p2


def test_adjacent_visitor_passes_allowed(api):
    """PRD §3.7: "validity intervals are half-open `[valid_from, valid_until)`, so exact
    adjacency where one pass's `valid_until` equals the next pass's `valid_from` is
    allowed, but any true overlap fails with `ERR_VISITOR_PASS_OVERLAP` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/visitor_pass_half_open_adjacent_ok_overlap_rejected
    """
    hh_id, permit_id, p1, p2 = _two_adjacent_passes(api)
    assert p1["status"] == "ACTIVE"
    assert p2["status"] == "ACTIVE"


def test_overlapping_visitor_pass_rejected(api):
    """PRD §3.7: "a new pass may not overlap an existing `ACTIVE` pass for the same
    household and the same `guest_plate`; validity intervals are half-open `[valid_from,
    valid_until)`, so exact adjacency where one pass's `valid_until` equals the next
    pass's `valid_from` is allowed, but any true overlap fails with
    `ERR_VISITOR_PASS_OVERLAP` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/visitor_pass_half_open_adjacent_ok_overlap_rejected
    """
    hh_id, permit_id, p1, p2 = _two_adjacent_passes(api)
    resp = api.create_visitor_pass(
        create_visitor_pass_payload(hh_id, permit_id, "2026-05-02T11:00:00.000Z",
                                    "2026-05-02T13:00:00.000Z", pass_type="TEMPORARY", guest_plate="GX"),
        _resident(hh_id),
    )
    validate_error(resp, "ERR_VISITOR_PASS_OVERLAP", expected_status=409)


# --------------------------------------------------------------------------
# cross_entity_state_dependency / visitor_pass_blocked_when_permit_not_active
# --------------------------------------------------------------------------
def test_visitor_pass_under_refunded_permit_rejected(api):
    """PRD §3.7: "The referenced permit must be an `ACTIVE` permit owned by the same
    household, or the request fails with `ERR_PERMIT_HOUSEHOLD_MISMATCH` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/visitor_pass_blocked_when_permit_not_active
    """
    s = setup_active_permit(api)
    hh_id, permit_id = s["household"]["id"], s["permit"]["id"]
    api.refund_permit(permit_id, refund_payload("ADMINISTRATIVE"), SUP)
    resp = api.create_visitor_pass(
        create_visitor_pass_payload(hh_id, permit_id, "2026-05-05T08:00:00.000Z",
                                    "2026-05-06T08:00:00.000Z", pass_type="TEMPORARY", guest_plate="GCE2"),
        _resident(hh_id),
    )
    validate_error(resp, "ERR_PERMIT_HOUSEHOLD_MISMATCH", expected_status=409)


def test_permit_refunded_before_visitor_pass_attempt(api):
    """PRD §3.7: "The referenced permit must be an `ACTIVE` permit owned by the same
    household, or the request fails with `ERR_PERMIT_HOUSEHOLD_MISMATCH` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/visitor_pass_blocked_when_permit_not_active
    """
    s = setup_active_permit(api)
    hh_id, permit_id = s["household"]["id"], s["permit"]["id"]
    refunded = validate_success(api.refund_permit(permit_id, refund_payload("ADMINISTRATIVE"), SUP), 200)
    assert refunded["status"] == "REFUNDED"
    resp = api.create_visitor_pass(
        create_visitor_pass_payload(hh_id, permit_id, "2026-05-05T08:00:00.000Z",
                                    "2026-05-06T08:00:00.000Z", pass_type="TEMPORARY", guest_plate="GCE3"),
        _resident(hh_id),
    )
    assert resp.status_code == 409
