"""Corner-coverage tests for list/action endpoints, FK not-found errors, RBAC denials,
optimistic concurrency, and immediate consistency.

Design queue B (Corner): sections endpoints, errors, rbac, cross_cutting_complexity_layers,
consistency_model.
"""
import pytest
from test_helpers import (
    api_client, get_success_data, validate_success, validate_error, validate_paginated,
    ApiErrorId, NON_EXISTENT_UUID, build_user_headers, make_member_headers,
    create_appointment_payload,
)
from test_helpers.fixtures import (
    SM, FD, set_clock, create_studio, create_service_type, create_plan, create_tech,
    create_member, create_membership, sanitize_tech, get_membership,
)


# ─── endpoints ────────────────────────────────────────
def test_list_appointments_filtered_by_member():
    """PRD §2.3: "List responses carry the pagination bookkeeping inside the envelope's `meta`
    object: `limit`, `offset`, `total_count`, and `has_more`."
    PRD §2.3: "Unless a specific workflow states otherwise, every list endpoint returns its
    resources sorted by their creation timestamp (`created_at`) in ascending order."

    Design: Corner/endpoints/list_appointments_filtered_by_member
    """
    studio = create_studio(name="Glow")
    tint = create_service_type(studio["id"], code="TINT", name="Tint", duration_minutes=30,
                              base_price_cents=4000, credit_cost=2, category="STANDARD",
                              requires_patch_test=False)
    tech = create_tech(studio["id"], skill_level=1, station_number=1)
    sanitize_tech(tech["id"], "2026-06-10T08:00:00Z")
    member_a = create_member(studio["id"], full_name="Ada", email="ada@x.com")
    member_b = create_member(studio["id"], full_name="Bea", email="bea@x.com")
    set_clock("2026-06-10T09:00:00Z")
    appt_a = get_success_data(api_client.create_appointment(
        create_appointment_payload(member_a["id"], tint["id"], "2026-06-10T13:00:00Z"), FD))
    get_success_data(api_client.create_appointment(
        create_appointment_payload(member_b["id"], tint["id"], "2026-06-10T14:00:00Z"), FD))
    data, meta = validate_paginated(api_client.list_appointments(FD, params={"member_id": member_a["id"]}))
    assert len(data) == 1 and data[0]["id"] == appt_a["id"], \
        f"filter returns only member A's appointment, got {[d['id'] for d in data]}"
    assert meta["total_count"] == 1
    assert meta["has_more"] is False


def test_void_sanitation_log_recomputes_station_window():
    """PRD §3.2: "A technician's `station_sanitized_through_utc` is the latest
    `valid_through_utc` among that technician's `COMPLETED` sanitation logs (voided logs are
    excluded), and is recomputed both when a new log is recorded and when a log is voided."

    Design: Corner/endpoints/void_sanitation_log_recomputes_station_window
    """
    studio = create_studio(name="Glow")
    full_st = create_service_type(studio["id"], code="FULL_SET", name="Full Set",
                                  duration_minutes=120, base_price_cents=12000, credit_cost=4,
                                  category="PREMIUM", requires_patch_test=False)
    tech = create_tech(studio["id"], skill_level=3, station_number=1)
    log = sanitize_tech(tech["id"], "2026-06-10T09:00:00Z")
    member = create_member(studio["id"])
    set_clock("2026-06-10T10:00:00Z")
    voided = validate_success(api_client.void_sanitation_log(log["id"], SM))
    assert voided["status"] == "VOIDED"
    refreshed_tech = get_success_data(api_client.get_lash_tech(tech["id"], SM))
    assert refreshed_tech["station_sanitized_through_utc"] is None, \
        "voiding the only log recomputes window to null"
    resp = api_client.create_appointment(
        create_appointment_payload(member["id"], full_st["id"], "2026-06-10T18:00:00Z"), FD)
    validate_error(resp, ApiErrorId.ERR_STATION_NOT_SANITIZED)


# ─── errors ───────────────────────────────────────────
def test_book_unknown_service_type_not_found():
    """PRD §2.8: "A missing `member_id`, `service_type_id`, `membership_id`, or
    `appointment_id` in a create payload yields the corresponding not-found error
    (`ERR_MEMBER_NOT_FOUND`, `ERR_SERVICE_TYPE_NOT_FOUND`, `ERR_MEMBERSHIP_NOT_FOUND`, or
    `ERR_APPOINTMENT_NOT_FOUND`)."

    Design: Corner/errors/book_unknown_service_type_not_found
    """
    studio = create_studio(name="Glow")
    member = create_member(studio["id"])
    set_clock("2026-06-10T10:00:00Z")
    resp = api_client.create_appointment(
        create_appointment_payload(member["id"], NON_EXISTENT_UUID, "2026-06-10T20:00:00Z"), FD)
    validate_error(resp, ApiErrorId.ERR_SERVICE_TYPE_NOT_FOUND)


# ─── rbac ─────────────────────────────────────────────
def test_front_desk_cannot_create_studio():
    """PRD §3.1: "A `StudioManager` establishes the configuration root by creating a `Studio`
    with a `name`."
    PRD §2.1: "When the headers are well-formed but the role is not permitted to perform the
    requested operation — or an entity-backed role attempts to act on a resource it does not
    own — the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/front_desk_cannot_create_studio
    """
    resp = api_client.create_studio({"name": "Glow"}, FD)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


def test_member_cannot_book_for_another_member():
    """PRD §2.1: "a `Member` may only book an appointment for themselves — the `member_id` in
    the booking payload must equal `X-User-ID`". PRD §2.1: "an entity-backed role attempts to
    act on a resource it does not own — the request is rejected with `ERR_FORBIDDEN_ROLE`
    (HTTP 403)."

    Design: Corner/rbac/member_cannot_book_for_another_member
    """
    studio = create_studio(name="Glow")
    tint = create_service_type(studio["id"], code="TINT", name="Tint", duration_minutes=30,
                              base_price_cents=4000, credit_cost=2, category="STANDARD",
                              requires_patch_test=False)
    tech = create_tech(studio["id"], skill_level=1, station_number=1)
    sanitize_tech(tech["id"], "2026-06-10T08:00:00Z")
    member_a = create_member(studio["id"], full_name="Ada", email="ada@x.com")
    member_b = create_member(studio["id"], full_name="Bea", email="bea@x.com")
    set_clock("2026-06-10T09:00:00Z")
    # Member A (X-User-ID = A.id) books for member B.
    resp = api_client.create_appointment(
        create_appointment_payload(member_b["id"], tint["id"], "2026-06-10T13:00:00Z"),
        make_member_headers(member_a["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


def test_missing_user_context_header_rejected():
    """PRD §2.1: "If either header is absent, or if `X-User-Role` is not one of the recognized
    role names, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT` (HTTP 401)."

    Design: Corner/rbac/missing_user_context_header_rejected
    """
    resp = api_client.list_studios(build_user_headers("ghost-1", "Ghost"))
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT)


# ─── cross_cutting_complexity_layers ──────────────────
def _setup_active_credit_membership_with_tech():
    """ACTIVE PREMIER membership balance 8; FULL_SET; one sanitized master tech; clock 10:00."""
    studio = create_studio(name="Glow")
    plan = create_plan(studio["id"], tier="PREMIER", monthly_credit_allotment=8, monthly_fee_cents=9900)
    full_st = create_service_type(studio["id"], code="FULL_SET", name="Full Set",
                                  duration_minutes=120, base_price_cents=12000, credit_cost=4,
                                  category="PREMIUM", requires_patch_test=False)
    tech = create_tech(studio["id"], skill_level=3, station_number=1)
    sanitize_tech(tech["id"], "2026-06-10T09:00:00Z")
    member = create_member(studio["id"])
    ms = create_membership(member["id"], plan["id"], initial_credits=8)
    set_clock("2026-06-10T10:00:00Z")
    return studio, full_st, member, ms


def test_occ_correct_version_books_increments_version():
    """PRD §2.9: "When booking a credit-paid appointment, the request must supply
    `expected_membership_version` equal to the current `version` of the target `Membership`. A
    credit booking debits the membership — appending a consumption ledger entry and
    incrementing `Membership.version`".

    Design: Corner/cross_cutting_complexity_layers/occ_correct_version_books_increments_version
    """
    studio, full_st, member, ms = _setup_active_credit_membership_with_tech()
    appt = validate_success(api_client.create_appointment(
        create_appointment_payload(member["id"], full_st["id"], "2026-06-10T20:00:00Z",
                                   pay_with_credits=True, membership_id=ms["id"],
                                   expected_membership_version=ms["version"]), FD),
        expected_status=201)
    assert appt["status"] == "BOOKED"
    after = get_membership(ms["id"])
    assert after["version"] == ms["version"] + 1, \
        f"credit booking increments version by 1, got {after['version']} vs {ms['version']}"


def test_occ_stale_version_credit_book_rejected():
    """PRD §2.9: "If `expected_membership_version` does not match the membership's current
    `version`, the booking is rejected with `ERR_STALE_MEMBERSHIP_VERSION` (HTTP 412),
    preventing the client from acting on a balance it has not observed."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_version_credit_book_rejected
    """
    studio = create_studio(name="Glow")
    plan = create_plan(studio["id"], tier="PREMIER", monthly_credit_allotment=8, monthly_fee_cents=9900)
    full_st = create_service_type(studio["id"], code="FULL_SET", name="Full Set",
                                  duration_minutes=60, base_price_cents=12000, credit_cost=4,
                                  category="PREMIUM", requires_patch_test=False)
    tech1 = create_tech(studio["id"], full_name="Mara", skill_level=3, station_number=1)
    tech2 = create_tech(studio["id"], full_name="Nia", skill_level=3, station_number=2)
    sanitize_tech(tech1["id"], "2026-06-10T09:00:00Z")
    sanitize_tech(tech2["id"], "2026-06-10T09:00:00Z")
    member = create_member(studio["id"])
    ms = create_membership(member["id"], plan["id"], initial_credits=8)
    set_clock("2026-06-10T10:00:00Z")
    stale_v = ms["version"]
    first = validate_success(api_client.create_appointment(
        create_appointment_payload(member["id"], full_st["id"], "2026-06-10T11:00:00Z",
                                   pay_with_credits=True, membership_id=ms["id"],
                                   expected_membership_version=stale_v), FD), expected_status=201)
    assert first["status"] == "BOOKED"
    # Second booking still carries the now-stale version.
    resp = api_client.create_appointment(
        create_appointment_payload(member["id"], full_st["id"], "2026-06-10T13:00:00Z",
                                   pay_with_credits=True, membership_id=ms["id"],
                                   expected_membership_version=stale_v), FD)
    validate_error(resp, ApiErrorId.ERR_STALE_MEMBERSHIP_VERSION)


# ─── consistency_model ────────────────────────────────
def test_immediate_visibility_of_credit_balance_on_booking():
    """PRD §3.5: "only when the gate passes does the system append a `CONSUME` ledger entry
    with a `delta` of the negative of the required amount, set `credits_charged` to the
    required amount". PRD §3.4: "A membership's `credit_balance` is always the sum of all
    `delta` values in its ledger and is never negative."

    Design: Corner/consistency_model/immediate_visibility_of_credit_balance_on_booking_response
    """
    studio, full_st, member, ms = _setup_active_credit_membership_with_tech()
    get_success_data(api_client.create_appointment(
        create_appointment_payload(member["id"], full_st["id"], "2026-06-10T20:00:00Z",
                                   pay_with_credits=True, membership_id=ms["id"],
                                   expected_membership_version=ms["version"]), FD))
    after = get_membership(ms["id"])
    assert after["credit_balance"] == 4, \
        f"8 - 4 = 4 visible immediately, got {after['credit_balance']}"
