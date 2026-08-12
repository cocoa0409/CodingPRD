"""The MATCHING/OFFERED re-match cycle with its counter-based UNFILLED exit, and the
logical-clock deferred sweeps (offer expiry, encounter auto-verify, UNFILLED sweep)."""
from test_helpers import (
    api_client,
    validate_error,
    validate_paginated,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    make_interpreter_headers,
    set_clock,
    create_org,
    create_submitted_request,
    create_draft_request,
    submit_request,
    offer_to,
    get_assignment,
    get_request,
    get_request_version,
    create_offer_payload,
    setup_offered_assignment,
    setup_confirmed_assignment,
    drive_to_checkout,
    get_encounter_of,
    assert_instant_equal,
)

ADMIN = TEST_USERS["platform_admin_headers"]


# ─── Difficulty: non_linear_state_machine / offer cycle ──────────────

def _setup_three_declined_offers():
    """FIXTURE-A request; three consecutive offers, each declined by the interpreter."""
    ctx = setup_offered_assignment()
    req_id = ctx["request"]["id"]
    interp_id = ctx["interpreter"]["id"]
    assignments = [ctx["assignment"]]
    for _ in range(2):
        get_success_data(api_client.decline_assignment(
            assignments[-1]["id"], make_interpreter_headers(interp_id)))
        assignments.append(offer_to(req_id, interp_id))
    get_success_data(api_client.decline_assignment(
        assignments[-1]["id"], make_interpreter_headers(interp_id)))
    return ctx, assignments


def test_offer_cycle_terminates_unfilled_after_third_decline():
    """PRD §3.5: "Both endings cascade identically to the request: back to `MATCHING`
    while `offer_attempt_count` remains below three, or to `UNFILLED` once three
    attempts have been spent."
    PRD §3.4: "Each request tolerates at most three offer attempts; a successful offer
    increments `offer_attempt_count` by one".

    Design: Difficulty/non_linear_state_machine/request_offer_cycle_until_unfilled
    """
    ctx, assignments = _setup_three_declined_offers()
    req_after = get_request(ctx["request"]["id"])
    assert req_after["status"] == "UNFILLED", (
        f"third decline must exit the cycle to UNFILLED, got {req_after['status']}"
    )
    assert req_after["offer_attempt_count"] == 3
    for asg in assignments:
        assert get_assignment(asg["id"])["status"] == "DECLINED"


def test_offer_cycle_unfilled_request_rejects_further_offers():
    """PRD §3.4: "Dispatch is the act of creating an offer against a request in
    `MATCHING` or `OFFERED` — anything else is rejected with
    `ERR_REQUEST_NOT_OFFERABLE`."
    PRD §2.10: "Eighth, resource from-state preconditions per the state machines"
    fires before "Eleventh, structural constraints (offer-attempt cap, ...)".

    Design: Difficulty/non_linear_state_machine/request_offer_cycle_until_unfilled
    """
    ctx, _assignments = _setup_three_declined_offers()
    req_id = ctx["request"]["id"]
    resp = api_client.create_offer(
        req_id,
        create_offer_payload(ctx["interpreter"]["id"], get_request_version(req_id)),
        ADMIN,
    )
    # UNFILLED is terminal and not offerable; the state tier (8th) reports before
    # the exhausted-attempt counter (11th).
    validate_error(resp, ApiErrorId.ERR_REQUEST_NOT_OFFERABLE)


# ─── Deferred sweeps ────────────────────────────────────────────────

def test_offer_expiry_sweep_returns_request_to_matching():
    """PRD §2.4: "Setting the clock runs the deferred sweep, in this fixed order:
    first, outstanding offers whose `response_deadline` has been reached expire
    (their requests fall back to re-matching or go unfilled)" and "The capability
    responds with the new `current_utc` plus three counters: `expired_offer_count`,
    `auto_verified_encounter_count`, and `unfilled_request_count`."
    PRD §3.4: "a `response_deadline` set to the earlier of the scheduled start and
    twenty-four hours after the offer" — an offer made at 2026-05-01T00:00:00Z for a
    June-10 start has deadline 2026-05-02T00:00:00Z.
    PRD §3.5: "Both endings cascade identically to the request: back to `MATCHING`
    while `offer_attempt_count` remains below three".

    Design: Corner/cross_cutting_layers/offer_expiry_sweep_returns_request_to_matching
    """
    ctx = setup_offered_assignment()
    asg = ctx["assignment"]
    assert_instant_equal(asg["response_deadline"], "2026-05-02T00:00:00Z",
                         "response_deadline = min(scheduled_start, offered_at + 24h)")
    sweep = set_clock("2026-05-02T00:00:00Z")
    assert sweep["expired_offer_count"] == 1, "the deadline is reached exactly"
    assert get_assignment(asg["id"])["status"] == "EXPIRED"
    req_after = get_request(ctx["request"]["id"])
    assert req_after["status"] == "MATCHING"
    assert req_after["offer_attempt_count"] == 1


def test_request_unfilled_sweep_at_scheduled_start():
    """PRD §2.4: "third, requests still `MATCHING` or `OFFERED` at or past their
    `scheduled_start` are marked `UNFILLED` (an outstanding offer becoming
    `EXPIRED`)."

    Design: Corner/cross_cutting_layers/request_unfilled_sweep_at_scheduled_start
    """
    set_clock("2026-05-01T00:00:00Z")
    org = create_org()
    req = create_submitted_request(
        org["id"], consumer_name="Dee Af", modality="VRI", ada_context="GENERAL",
        scheduled_start="2026-06-10T14:00:00Z", scheduled_end="2026-06-10T15:00:00Z",
        onsite_address=None, estimated_mileage=0)
    sweep = set_clock("2026-06-10T14:00:00Z")  # exactly at scheduled_start
    assert sweep["unfilled_request_count"] == 1
    assert get_request(req["id"])["status"] == "UNFILLED"


def test_encounter_auto_verify_at_deadline():
    """PRD §3.7: "When the requester stays silent, the clock sweep auto-verifies at
    or after the `verify_deadline` with `verified_by` `SYSTEM`, producing the same
    bubble."
    PRD §2.4: "second, encounters whose `verify_deadline` has been reached are
    auto-verified by the system (which may bubble a request from `IN_PROGRESS` to
    `COMPLETED`)".

    Design: Corner/cross_cutting_layers/encounter_auto_verify_at_deadline
    """
    ctx = setup_confirmed_assignment()
    drive_to_checkout(ctx)  # actual_end 2026-06-10T16:10 -> deadline 2026-06-13T16:10

    sweep_before = set_clock("2026-06-13T16:09:00Z")
    assert sweep_before["auto_verified_encounter_count"] == 0, (
        "one minute before the deadline nothing is auto-verified"
    )
    enc_before = get_encounter_of(ctx["assignment"]["id"])
    assert enc_before["verified"] is False

    sweep_at = set_clock("2026-06-13T16:10:00Z")
    assert sweep_at["auto_verified_encounter_count"] == 1, (
        "at exactly the deadline the encounter auto-verifies"
    )
    enc_after = get_encounter_of(ctx["assignment"]["id"])
    assert enc_after["verified"] is True
    assert enc_after["verified_by"] == "SYSTEM"
    assert get_request(ctx["request"]["id"])["status"] == "COMPLETED"


def test_list_requests_filter_sort_pagination():
    """PRD §2.3: "The `limit` parameter caps the number of items returned; it
    defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter
    skips that many items from the front of the result set and defaults to 0." and
    "The `meta` object of a list response always carries the pagination fields
    `limit`, `offset`, `total_count`, and `has_more`."
    PRD §3.3: "Coordinators browse their pipeline through the request listing, which
    filters by `org_id`, `status`, `modality`, and `ada_context` in addition to the
    standard pagination parameters."

    Design: Corner/cross_cutting_layers/list_requests_filter_sort_pagination
    """
    set_clock("2026-05-01T00:00:00Z")
    org = create_org()
    first = None
    for i in range(12):
        req = create_draft_request(
            org["id"],
            consumer_name=f"C{i + 1:02d}",
            modality="VRI",
            ada_context="GENERAL",
            scheduled_start=f"2026-06-{10 + i:02d}T14:00:00Z",
            scheduled_end=f"2026-06-{10 + i:02d}T15:00:00Z",
            onsite_address=None,
            estimated_mileage=0,
        )
        if first is None:
            first = req
    submit_request(first)  # the only MATCHING request

    page1_resp = api_client.list_requests(ADMIN, params={"org_id": org["id"]})
    assert page1_resp.json()["response_type"] == "array"
    page1, meta1 = validate_paginated(page1_resp)
    assert len(page1) == 10, f"default page caps at 10, got {len(page1)}"
    assert meta1["total_count"] == 12
    assert meta1["has_more"] is True
    assert meta1["limit"] == 10 and meta1["offset"] == 0

    page2, meta2 = validate_paginated(api_client.list_requests(
        ADMIN, params={"org_id": org["id"], "limit": 5, "offset": 10}))
    assert len(page2) == 2, "last page holds the remaining two"
    assert meta2["total_count"] == 12
    assert meta2["has_more"] is False

    filtered, meta3 = validate_paginated(api_client.list_requests(
        ADMIN, params={"org_id": org["id"], "status": "MATCHING"}))
    assert len(filtered) == 1 and filtered[0]["id"] == first["id"]
    assert meta3["total_count"] == 1
