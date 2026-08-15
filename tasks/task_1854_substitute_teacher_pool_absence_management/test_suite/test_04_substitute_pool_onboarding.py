"""Pool administration: activation gating, clearance expiry terminal rules,
mark lift/recreation semantics, and performance-flag review lockdown."""
from test_helpers import (
    ApiErrorId,
    basic_world,
    create_clearance_payload,
    create_mark_payload,
    create_performance_flag_payload,
    create_substitute_payload,
    get_substitute,
    make_coordinator_headers,
    make_district,
    onboard_substitute,
    review_flag,
    set_logical_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_substitute_activation_gating_and_invalid_state(api, district_admin_headers):
    """PRD 3.2: "Activation moves a substitute from `PENDING_CLEARANCE` — or,
    after discipline, from `SUSPENDED` — to `ACTIVE`, and is a `DistrictAdmin`
    prerogative. Attempting it from `ACTIVE` is rejected with
    `ERR_SUBSTITUTE_INVALID_STATE`; attempting it without both required
    clearances `VERIFIED` and valid through the current clock date is rejected
    with `ERR_CLEARANCE_INVALID`."
    PRD 3.2: "Suspension runs in reverse: a manual suspend of an `ACTIVE`
    substitute, optionally annotated with a `reason`, or the automatic
    triggers of §2.10"

    Design: Corner/validations/substitute_activation_gating_and_invalid_state
    """
    make_district()
    sub_a = validate_success(
        api.create_substitute(
            create_substitute_payload(full_name="Sub A", base_daily_rate_cents=20000),
            district_admin_headers,
        ),
        201,
    )
    res = api.activate_substitute(sub_a["id"], district_admin_headers)
    validate_error(res, ApiErrorId.ERR_CLEARANCE_INVALID, expected_status=409)

    res = api.suspend_substitute(sub_a["id"], {}, district_admin_headers)
    validate_error(res, ApiErrorId.ERR_SUBSTITUTE_INVALID_STATE, expected_status=409)

    sub_b = onboard_substitute(full_name="Sub B", rate_cents=18000)
    assert sub_b["status"] == "ACTIVE"
    res = api.activate_substitute(sub_b["id"], district_admin_headers)
    validate_error(res, ApiErrorId.ERR_SUBSTITUTE_INVALID_STATE, expected_status=409)


def test_clearance_expiry_and_verify_terminal_rules(api, district_admin_headers):
    """PRD 3.2: "When the logical clock's date passes a clearance's
    `expires_on`, the clearance flips `PENDING` or `VERIFIED` to `EXPIRED`."
    PRD 3.2: "The flip is applied eagerly at dispatch batches, at substitute
    activation, and at any validation that reads the clearance, and lazily
    when a substitute's clearances are listed."
    PRD 3.2: "A district admin verifies a pending clearance; verification of a
    clearance in any other status fails with `ERR_CLEARANCE_INVALID_STATE`"

    Design: Corner/state_machines/clearance_expiry_and_verify_terminal_rules
    """
    make_district()
    sub = validate_success(
        api.create_substitute(
            create_substitute_payload(full_name="Sub A", base_daily_rate_cents=20000),
            district_admin_headers,
        ),
        201,
    )
    clearance = validate_success(
        api.create_clearance(
            create_clearance_payload(
                sub["id"], clearance_type="TB_TEST", expires_on="2026-08-02"
            ),
            district_admin_headers,
        ),
        201,
    )
    set_logical_clock("2026-08-03T00:00:00Z")

    data, _ = validate_paginated(
        api.list_clearances(sub["id"], district_admin_headers)
    )
    assert data[0]["status"] == "EXPIRED", "lazy expiry applied on list read"

    res = api.verify_clearance(clearance["id"], district_admin_headers)
    validate_error(res, ApiErrorId.ERR_CLEARANCE_INVALID_STATE, expected_status=409)


def test_mark_lift_terminal_and_recreation_allowed(api):
    """PRD 3.8: "Either a coordinator or an admin may lift an `ACTIVE` mark —
    lifting any other status fails with `ERR_MARK_INVALID_STATE` — restoring
    the substitute's eligibility at that school, since the selector and the
    do-not-return screen both ignore `LIFTED` marks."
    PRD 3.8: "Marks open `ACTIVE`, with `source_flag_id` null for manually
    created ones, and one `ACTIVE` mark per school, substitute, and mark type
    is the ceiling — a duplicate is refused with `ERR_DUPLICATE_MARK`."

    Design: Corner/state_machines/mark_lift_terminal_and_recreation_allowed
    """
    ctx = basic_world(clock=None)
    coord_headers = make_coordinator_headers(ctx["coordinator"]["id"])
    sub = onboard_substitute(activate=False)

    mark = validate_success(
        api.create_mark(
            create_mark_payload(
                ctx["school"]["id"], sub["id"],
                mark_type="DO_NOT_RETURN", reason="repeated tardiness",
            ),
            coord_headers,
        ),
        201,
    )
    lifted = validate_success(api.lift_mark(mark["id"], coord_headers), 200)
    assert lifted["status"] == "LIFTED"

    res = api.lift_mark(mark["id"], coord_headers)
    validate_error(res, ApiErrorId.ERR_MARK_INVALID_STATE, expected_status=409)

    recreated = validate_success(
        api.create_mark(
            create_mark_payload(
                ctx["school"]["id"], sub["id"],
                mark_type="DO_NOT_RETURN", reason="new incident",
            ),
            coord_headers,
        ),
        201,
    )
    assert recreated["status"] == "ACTIVE", "a LIFTED mark does not block re-creation"

    res = api.create_mark(
        create_mark_payload(
            ctx["school"]["id"], sub["id"],
            mark_type="DO_NOT_RETURN", reason="duplicate",
        ),
        coord_headers,
    )
    validate_error(res, ApiErrorId.ERR_DUPLICATE_MARK, expected_status=409)


def test_performance_flag_review_terminal_lockdown(api, district_admin_headers):
    """PRD 3.8: "A `DistrictAdmin` later reviews with a `decision` of
    `RESOLVE` or `ESCALATE` — either way the flag must be `OPEN`, else
    `ERR_PERFORMANCE_FLAG_INVALID_STATE`."
    PRD 3.8: "and, significantly, raising one immediately appends the matching
    reliability event, `FLAG_MINOR` (−3) or `FLAG_MAJOR` (−10), and runs
    suspension evaluation: flags move scores before any human review."

    Design: Corner/endpoints/performance_flag_review_terminal_lockdown
    """
    ctx = basic_world(clock=None)
    coord_headers = make_coordinator_headers(ctx["coordinator"]["id"])
    sub = validate_success(
        api.create_substitute(
            create_substitute_payload(full_name="Sub A", base_daily_rate_cents=20000),
            district_admin_headers,
        ),
        201,
    )
    flag = validate_success(
        api.create_performance_flag(
            create_performance_flag_payload(
                sub["id"], ctx["school"]["id"], flag_type="QUALITY", severity="MINOR"
            ),
            coord_headers,
        ),
        201,
    )
    resolved = review_flag(flag["id"], "RESOLVE")
    assert resolved["status"] == "RESOLVED"

    res = api.review_performance_flag(flag["id"], {"decision": "ESCALATE"}, district_admin_headers)
    validate_error(res, ApiErrorId.ERR_PERFORMANCE_FLAG_INVALID_STATE, expected_status=409)

    _, meta = validate_paginated(
        api.list_substitute_marks(sub["id"], district_admin_headers)
    )
    assert meta["total_count"] == 0, "no do-not-return mark was created"

    refreshed = get_substitute(sub["id"])
    assert refreshed["reliability_trailing_score"] == 97, "single FLAG_MINOR (-3)"
    assert refreshed["reliability_lifetime_score"] == 97
