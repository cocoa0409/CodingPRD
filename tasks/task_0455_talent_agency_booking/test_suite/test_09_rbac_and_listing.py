"""RBAC enforcement, date-range validation, and filtered listing."""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    TEST_USERS,
    ApiErrorId,
    build_user_headers,
    create_casting_call_payload,
    create_booking_payload,
    setup_pending_booking,
    setup_rostered_talent,
    make_casting_director_headers,
    make_talent_headers,
    create_casting_director,
    create_agency,
    create_talent,
)

AGENT = TEST_USERS["agent_headers"]


# ─── validations: casting call inverted dates ────────────────────────────────
def test_create_casting_call_inverted_dates_rejected(api):
    """PRD §3.2: "a `shoot_start_date` and a `shoot_end_date` (the latter must be
    on or after the former, else `ERR_INVALID_DATE_RANGE`)"

    Design: Corner/validations/casting_call_inverted_dates_rejected
    """
    cd = create_casting_director()
    cd_headers = make_casting_director_headers(cd["id"])
    resp = api.create_casting_call(
        create_casting_call_payload(
            cd["id"], title="Bad Dates", media_type="PRINT", usage_term_months=6,
            shoot_start_date="2026-05-10T00:00:00Z",
            shoot_end_date="2026-05-01T00:00:00Z",
            offered_day_rate_cents=100000,
        ),
        cd_headers,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_DATE_RANGE.value, 422)


# ─── rbac: talent cannot create casting call ─────────────────────────────────
def test_talent_cannot_create_casting_call(api):
    """PRD §2.1: "A request whose role is well-formed but not permitted for the
    requested operation (per the authorization column of the endpoint table in
    §4) is rejected with `ERR_FORBIDDEN_ROLE`."

    Design: Corner/rbac/talent_cannot_create_casting_call
    """
    agency = create_agency()
    cd = create_casting_director()
    talent = create_talent(agency["id"])
    talent_headers = make_talent_headers(talent["id"])
    resp = api.create_casting_call(
        create_casting_call_payload(
            cd["id"], title="Sneaky", media_type="PRINT", usage_term_months=6,
            shoot_start_date="2026-05-01T00:00:00Z",
            shoot_end_date="2026-05-02T00:00:00Z",
            offered_day_rate_cents=100000,
        ),
        talent_headers,
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)


# ─── rbac: casting director cannot create booking ────────────────────────────
def test_casting_director_cannot_create_booking(api):
    """PRD §2.1: "A request whose role is well-formed but not permitted for the
    requested operation (per the authorization column of the endpoint table in
    §4) is rejected with `ERR_FORBIDDEN_ROLE`."

    Design: Corner/rbac/casting_director_cannot_create_booking
    """
    # POST /bookings is Agent-exclusive. Authorization (priority 2) precedes any
    # body/state check, so a CastingDirector attempt is 403 regardless of payload.
    from test_helpers import (
        create_casting_call, create_submission, create_availability_hold,
        create_deal_memo_payload, offer_payload, talent_version,
        schedule_audition_slot,
    )
    base = setup_rostered_talent(union_status="SAG")
    cd_id, talent_id, cc_id = base["cd"]["id"], base["talent"]["id"], base["comp_card"]["id"]
    cd_headers = make_casting_director_headers(cd_id)
    talent_headers = make_talent_headers(talent_id)
    call = create_casting_call(cd_id, media_type="STREAMING")
    submission = create_submission(call["id"], talent_id, cc_id)
    # Advance submission to AUDITION_SCHEDULED so the deal memo open moves it to
    # OFFER_EXTENDED, making the first offer permitted (PRD §3.5).
    schedule_audition_slot(cd_id, submission["id"])
    dm = get_success_data(
        api.create_deal_memo(
            create_deal_memo_payload(call["id"], talent_id, submission["id"]),
            cd_headers,
        )
    )
    get_success_data(api.offer_deal_memo(dm["id"], offer_payload(200000, 12), cd_headers))
    get_success_data(api.accept_deal_memo(dm["id"], talent_headers))
    hold = create_availability_hold(talent_id)
    tv = talent_version(talent_id)

    resp = api.create_booking(
        create_booking_payload(dm["id"], talent_id, call["id"], hold["id"], tv),
        cd_headers,
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)


# ─── rbac: missing auth headers ──────────────────────────────────────────────
def test_missing_auth_headers_returns_unauthenticated(api):
    """PRD §2.1: "A request that omits either header, or carries a malformed
    value, is rejected with `ERR_UNAUTHENTICATED`."
    PRD §2.9: "a request missing or malformed in its `X-User-ID` or
    `X-User-Role` headers fails with `ERR_UNAUTHENTICATED` (401) before anything
    else."

    Design: Corner/rbac/missing_auth_headers_unauthenticated
    """
    no_auth = {"Content-Type": "application/json"}
    resp = api.create_agency({"name": "NoAuth", "commission_rate_bps": 1000}, no_auth)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)


# ─── endpoints: list bookings filtered by talent ─────────────────────────────
def test_list_bookings_filtered_by_talent(api):
    """PRD §3.6: "Bookings are filterable by `talent_id`, `casting_call_id`,
    `deal_memo_id`, `availability_hold_id`, and `booking_status`."

    Design: Corner/endpoints/list_bookings_filtered_by_talent
    """
    base = setup_pending_booking(union_status="SAG", media_type="STREAMING")
    talent_id = base["talent"]["id"]
    resp = api.list_bookings(AGENT, params={"talent_id": talent_id})
    data, _meta = validate_paginated(resp)
    assert len(data) >= 1
    for booking in data:
        assert booking["talent_id"] == talent_id
