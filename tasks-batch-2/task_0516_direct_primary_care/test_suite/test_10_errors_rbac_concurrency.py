"""Input/validation errors, RBAC denials, optimistic-concurrency stale-version
rejection, the OCC happy path, and the grace-window scheduled action.
PRD §2.1, §2.6, §3.1, §3.3, §3.13, §3.14.
"""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    create_practice, create_provider, create_employer, register_member,
    setup_active_member, allocate_seat, occupy_seat, employer_version,
    assign_pcp_manual, get_membership_for, charge_membership, drive_member_past_due,
    create_slot, book_visit, make_member_headers, make_employer_headers,
    make_provider_headers, occupy_seat_payload, create_visit_payload,
    register_member_payload, set_clock, ApiErrorId, ADMIN, ANON,
)


# ── Errors ──────────────────────────────────────────────────────────────

def test_register_invalid_plan_type_enum_returns_invalid_request(api):
    """PRD §3.3: "A member's `plan_type` is one of `MONTHLY` or `ANNUAL_PREPAID`."
    PRD §3.14: "enum values must lie within their declared domains, failing with
    `ERR_INVALID_REQUEST`."

    Design: Corner/errors/register_invalid_plan_type_enum_returns_invalid_request
    """
    practice = create_practice(name="E1")
    res = api_client.register_member(
        register_member_payload(practice["id"], "e1@x.com", plan_type="WEEKLY"), ANON)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_create_practice_hardcap_below_target_returns_validation(api):
    """PRD §3.1: "`panel_hard_cap` must be at least as large as `panel_target`; a
    `panel_hard_cap` below `panel_target` is rejected with `ERR_VALIDATION`."

    Design: Corner/errors/create_practice_hardcap_below_target_returns_validation
    """
    from test_helpers import create_practice_payload
    res = api_client.create_practice(
        create_practice_payload(name="E2", panel_target=50, panel_hard_cap=10), ADMIN)
    validate_error(res, ApiErrorId.ERR_VALIDATION.value)


def test_stale_slot_version_on_book_returns_stale_version(api):
    """PRD §2.6: "Booking a visit must carry `expected_slot_version`, the `version`
    of the target `VisitSlot` the client last observed."
    PRD §2.6: "If another booking has advanced that slot's `version` since the
    client read it — for example, by consuming the last remaining in-person capacity
    or a virtual seat — the booking is rejected with `ERR_STALE_VERSION` (HTTP 412),
    because the client's view of the slot's `booked_count` is stale."

    Design: Corner/errors/stale_slot_version_on_book_returns_stale_version
    """
    practice = create_practice(name="E3")
    provider = create_provider(practice["id"], full_name="Dr E3", npi="7000000001")
    set_clock("2026-06-01T00:00:00Z")
    slot = create_slot(provider["id"], "VIRTUAL",
                       "2026-06-05T09:00:00Z", "2026-06-05T09:30:00Z", virtual_capacity=5)
    stale_v = slot["version"]

    m1 = register_member(practice["id"], email="e3a@x.com")
    assign_pcp_manual(m1["id"], provider["id"])
    mem1 = get_membership_for(m1["id"])
    charge_membership(m1["id"], mem1["id"], mem1["member_share_cents"], "SUCCEEDED")
    m2 = register_member(practice["id"], email="e3b@x.com")
    assign_pcp_manual(m2["id"], provider["id"])
    mem2 = get_membership_for(m2["id"])
    charge_membership(m2["id"], mem2["id"], mem2["member_share_cents"], "SUCCEEDED")

    book_visit(m1["id"], slot["id"], "VIRTUAL", stale_v)  # bumps slot.version
    res = api_client.create_visit(
        create_visit_payload(m2["id"], slot["id"], "VIRTUAL", stale_v),
        make_member_headers(m2["id"]))
    validate_error(res, ApiErrorId.ERR_STALE_VERSION.value)


def test_stale_employer_version_on_occupy_returns_stale_version(api):
    """PRD §2.6: "Likewise, occupying a sponsored seat must carry
    `expected_employer_version`, the `version` of the target `Employer` the client
    last observed; if another occupy call has advanced the employer's `version`
    since the client read it (for instance, by filling the last open seat), the
    occupy is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/errors/stale_employer_version_on_occupy_returns_stale_version
    """
    practice = create_practice(name="E4")
    employer = create_employer(practice["id"], sponsored_seat_limit=5, sponsorship_pct=1.0)
    m1 = register_member(practice["id"], email="e4a@x.com")
    m2 = register_member(practice["id"], email="e4b@x.com")
    seat1 = allocate_seat(employer["id"])
    seat2 = allocate_seat(employer["id"])
    emp_h = make_employer_headers(employer["id"])
    stale_v = validate_success(api_client.get_employer(employer["id"], emp_h), 200)["version"]
    occupy_seat(employer["id"], seat1["id"], m1["id"], stale_v)  # bumps employer.version

    res = api_client.occupy_seat(
        employer["id"], seat2["id"], occupy_seat_payload(m2["id"], stale_v), emp_h)
    validate_error(res, ApiErrorId.ERR_STALE_VERSION.value)


# ── RBAC ────────────────────────────────────────────────────────────────

def test_member_cannot_create_provider_forbidden(api):
    """PRD §2.1: "When a caller presents a valid role but that role is not permitted
    to perform the requested operation — or presents an identity that does not own
    the targeted resource — the request is rejected with `ERR_FORBIDDEN`."
    PRD §3.1: "The administrator then registers each `Provider` under a practice,
    supplying the parent `practice_id`, the provider's `full_name`, and an `npi`
    (National Provider Identifier) that must be unique within the practice."

    Design: Corner/rbac/member_cannot_create_provider_forbidden
    """
    practice = create_practice(name="R1")
    member = register_member(practice["id"], email="r1@x.com")
    res = api_client.create_provider(
        {"practice_id": practice["id"], "full_name": "Sneaky", "npi": "8000000001"},
        make_member_headers(member["id"]))
    validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)


def test_member_cannot_cancel_other_members_membership_forbidden(api):
    """PRD §2.1: "When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the
    acting `Member`; ownership of a visit, membership, message thread, invoice,
    payment, referral, or care plan is established by comparing that resource's
    `member_id` to `X-User-ID`."
    PRD §2.1: "or presents an identity that does not own the targeted resource —
    the request is rejected with `ERR_FORBIDDEN`."

    Design: Corner/rbac/member_cannot_cancel_other_members_membership_forbidden
    """
    ctx = setup_active_member()  # mA active
    m_b = register_member(ctx["practice"]["id"], email="r2b@x.com")
    # mB attempts to cancel mA's membership.
    res = api_client.cancel_member(ctx["member"]["id"], make_member_headers(m_b["id"]))
    validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)


def test_missing_headers_returns_unauthenticated(api):
    """PRD §2.1: "When either header is missing, or `X-User-Role` is not one of the
    recognized roles, the request is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_headers_returns_unauthenticated
    """
    practice = create_practice(name="R3")
    res = api_client._request("GET", "/members", payload={"practice_id": practice["id"]}, headers={})
    validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED.value)


# ── Cross-cutting OCC / scheduled actions ──────────────────────────────

def test_occupy_seat_correct_version_succeeds_and_bumps_count(api):
    """PRD §3.2: "On success the seat's `seat_status` becomes `OCCUPIED` and its
    `member_id` is set, the member's `Membership` records the `employer_seat_id`,
    and the member's monthly share is recomputed (per §3.7) to reflect the
    employer's sponsorship."
    PRD §3.2: "The employer's `occupied_seat_count` is incremented and the
    employer's `version` is incremented by one."

    Design: Corner/cross_cutting_complexity_layers/occ_correct_version_succeeds_and_bumps
    """
    practice = create_practice(name="L1")
    employer = create_employer(practice["id"], sponsored_seat_limit=5, sponsorship_pct=1.0)
    member = register_member(practice["id"], email="l1@x.com")
    seat = allocate_seat(employer["id"])
    emp_h = make_employer_headers(employer["id"])
    emp_v = validate_success(api_client.get_employer(employer["id"], emp_h), 200)["version"]
    occupied = validate_success(api_client.occupy_seat(
        employer["id"], seat["id"], occupy_seat_payload(member["id"], emp_v), emp_h), 200)
    assert occupied["seat_status"] == "OCCUPIED"
    employer_after = validate_success(api_client.get_employer(employer["id"], emp_h), 200)
    assert employer_after["occupied_seat_count"] == 1


def test_scheduled_suspension_only_fires_after_grace(api):
    """PRD §3.3: "If the grace window has instead elapsed — the clock has reached or
    passed `past_due_since` plus `grace_period_days` days — the periodic sweep moves
    the membership from `PAST_DUE` to `SUSPENDED`."

    Design: Corner/cross_cutting_complexity_layers/scheduled_suspension_only_fires_after_grace
    """
    # PAST_DUE since 2026-07-01, grace 14d; sweep at 2026-07-10 (9 days < 14):
    # the membership stays PAST_DUE.
    ctx = setup_active_member(practice_overrides={"grace_period_days": 14})
    drive_member_past_due(ctx, rollover_clock="2026-07-01T00:00:00Z",
                          fail_clock="2026-07-10T00:00:00Z")
    get_success_data(api_client.run_suspension_sweep(ADMIN))
    member = validate_success(api_client.get_member(ctx["member"]["id"], ADMIN), 200)
    assert member["membership_status"] == "PAST_DUE"
