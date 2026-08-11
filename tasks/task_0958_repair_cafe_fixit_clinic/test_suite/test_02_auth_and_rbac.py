"""Authentication, authorization, and segregation-of-duties rules (PRD §2.1,
§3.1, §3.5)."""
import pytest

from test_helpers import (
    validate_success, validate_error, TEST_USERS, ApiErrorId,
    make_fixer_headers, create_repair_event_payload,
    set_logical_clock, create_event, create_station, register_fixer,
    sign_up_shift, setup_intake_open_event, progress_item_to_outcome_recorded,
)

COORD = TEST_USERS["coordinator_headers"]


def test_missing_auth_headers_unauthenticated(api):
    """PRD §2.1: "A request missing either header, or presenting a role outside
    this set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/errors/missing_auth_headers_unauthenticated
    """
    res = api.list_repair_events(headers={})
    validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED)

    res = api.list_repair_events(headers={"X-User-ID": "someone"})
    validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED)


def test_fixer_cannot_create_event_unauthorized(api):
    """PRD §2.1: "A request whose role is authenticated but not permitted for
    the targeted operation is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
    PRD §4: POST /api/repair-events is authorized for Coordinator only.

    Design: Corner/errors/fixer_cannot_create_event_unauthorized
    """
    set_logical_clock()
    fixer = register_fixer()
    res = api.create_repair_event(
        create_repair_event_payload(name="Nope"),
        make_fixer_headers(fixer["id"]))
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


def test_fixer_self_verification_forbidden_but_peer_verify_ok(api):
    """PRD §3.5: "Verification requires the outcome to be `RECORDED`
    (`ERR_INVALID_OUTCOME_STATE`), requires that a fixer acting as verifier is
    not the outcome's `fixer_id` (`ERR_SELF_VERIFICATION_FORBIDDEN`), and
    requires that no `SafetyIncident` of any severity in status `REPORTED`
    exists for the item (`ERR_SAFETY_HOLD`)."
    PRD §3.5: "The verifier's identity is written to `verified_by_user_id`."

    Design: Corner/rbac/fixer_self_verification_forbidden_but_peer_verify_ok
    """
    ctx = setup_intake_open_event(event_name="Cafe Resh")
    peer = register_fixer(display_name="Fixer B")
    item, outcome_rec = progress_item_to_outcome_recorded(
        ctx, outcome="FIXED", weight_kg_actual=4.4)

    # The performing fixer may not verify their own outcome.
    res = api.verify_outcome(outcome_rec["id"],
                             make_fixer_headers(ctx["fixer"]["id"]))
    validate_error(res, ApiErrorId.ERR_SELF_VERIFICATION_FORBIDDEN)

    # A different fixer may verify.
    verified = validate_success(
        api.verify_outcome(outcome_rec["id"], make_fixer_headers(peer["id"])),
        200)
    assert verified["verification_status"] == "VERIFIED"
    assert verified["verified_by_user_id"] == peer["id"]

    item_after = validate_success(api.get_repair_item(item["id"], COORD), 200)
    assert item_after["status"] == "VERIFIED", (
        "verification moves the item OUTCOME_RECORDED -> VERIFIED")


def test_fixer_cannot_cancel_other_fixers_shift(api):
    """PRD §2.1: "When `X-User-Role` is `Fixer`, `X-User-ID` is the `id` of the
    acting `FixerProfile`; ownership checks on any resource that references a
    fixer — a shift, an assigned repair item, a recorded outcome — compare the
    resource's foreign-key field to `X-User-ID`."
    PRD §3.1: "Shifts may also be cancelled from `SIGNED_UP` or `CONFIRMED` by
    the fixer or a `Coordinator`; a shift transition attempted from a state that
    does not permit it fails with `ERR_INVALID_SHIFT_STATE`."

    Design: Corner/rbac/fixer_cannot_cancel_other_fixers_shift
    """
    set_logical_clock()
    event = create_event(name="Cafe Shin")
    station = create_station(event["id"], category="BIKE", capacity=2)
    fixer_a = register_fixer(display_name="Fixer A")
    fixer_b = register_fixer(display_name="Fixer B")
    shift_b = sign_up_shift(fixer_b["id"], station["id"], event["id"],
                            start_time="2026-06-01T10:00:00Z",
                            end_time="2026-06-01T12:00:00Z")

    # Fixer A cannot cancel fixer B's shift (ownership check on the shift).
    res = api.cancel_shift(shift_b["id"], make_fixer_headers(fixer_a["id"]))
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP)

    # A Coordinator can cancel it.
    cancelled = validate_success(api.cancel_shift(shift_b["id"], COORD), 200)
    assert cancelled["status"] == "CANCELLED"
