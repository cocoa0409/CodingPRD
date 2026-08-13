"""Attempt submission gates: collateral sufficiency, attempt/ucc3 in-flight
constraints, amendment structural requirements, fiscal gate, name accuracy, and the
expedited daily capacity bucket."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    approve_preparation,
    create_attempt_payload,
    create_draft_attempt,
    create_filing_request,
    create_ready_request,
    create_ucc3_request,
    get_client_account,
    get_filing,
    make_filing_specialist_headers,
    set_clock_to,
    setup_active_initial_filing,
    setup_client_world,
    submit_attempt,
    submit_intake,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
SPECIALIST = TEST_USERS["specialist_headers"]


def test_collateral_supergeneric_rejected(api):
    """PRD §3.4: "For an `INITIAL` attempt and for a `COLLATERAL`-scope amendment,
    `collateral_text` must be at least 20 characters long and must not normalize to
    one of the supergeneric terms `ALL ASSETS`, `ALL PERSONAL PROPERTY`, or `ALL
    ASSETS OF DEBTOR`; failure is rejected with
    `ERR_COLLATERAL_INSUFFICIENTLY_DESCRIBED`."

    Design: Corner/validations/collateral_supergeneric_rejected
    """
    world = setup_client_world()
    request = create_ready_request(world["client"], world["debtor"], world["secured_party"])
    attempt = create_draft_attempt(request["id"], collateral_text="All assets")
    resp = api.submit_filing(attempt["id"], SPECIALIST)
    validate_error(resp, ApiErrorId.ERR_COLLATERAL_INSUFFICIENTLY_DESCRIBED)
    assert get_filing(attempt["id"])["effectiveness_status"] == "DRAFT", (
        "a failed submission must leave the attempt in DRAFT"
    )


def test_attempt_in_flight_conflict(api):
    """PRD §3.4: "A request may have at most one non-terminal attempt — one in `DRAFT`
    or `SUBMITTED` — and creating a second while one is in flight is rejected with
    `ERR_ATTEMPT_IN_FLIGHT`."

    Design: Corner/validations/attempt_in_flight_conflict
    """
    world = setup_client_world()
    request = create_ready_request(world["client"], world["debtor"], world["secured_party"])
    create_draft_attempt(request["id"])
    resp = api.create_attempt(
        request["id"],
        create_attempt_payload(collateral_text="All inventory and equipment of debtor"),
        SPECIALIST,
    )
    validate_error(resp, ApiErrorId.ERR_ATTEMPT_IN_FLIGHT)
    _, meta = validate_paginated(api.list_attempts(request["id"], ADMIN))
    assert meta["total_count"] == 1, "the in-flight attempt must remain the only one"


def test_ucc3_in_flight_conflict(api):
    """PRD §3.2: "One restriction applies at creation: a root filing may have at most
    one open `AMENDMENT` or `CONTINUATION` request — a second open one is rejected
    with `ERR_UCC3_IN_FLIGHT` — while `TERMINATION` requests are exempt from that
    restriction."

    Design: Corner/validations/ucc3_in_flight_conflict
    """
    ctx = setup_active_initial_filing()
    root_id = ctx["filing"]["id"]
    create_ucc3_request("AMENDMENT", ctx["client"], ctx["debtor"],
                        ctx["secured_party"], root_id)
    # The second creation carries the CURRENT (fresh) target version: it passes the
    # OCC guard and must still fail the in-flight constraint.
    resp = api.create_filing_request(
        {
            "client_id": ctx["client"]["id"],
            "kind": "AMENDMENT",
            "debtor_id": ctx["debtor"]["id"],
            "secured_party_id": ctx["secured_party"]["id"],
            "jurisdiction_code": "CA",
            "collateral_class": "GENERAL",
            "fee_authorization_cents": 100000,
            "target_filing_id": root_id,
            "expected_target_filing_version": get_filing(root_id)["version"],
        },
        SPECIALIST,
    )
    validate_error(resp, ApiErrorId.ERR_UCC3_IN_FLIGHT)
    assert get_filing(root_id)["open_ucc3_request_count"] == 1, (
        "the rejected creation must not register against the root's open count"
    )


def test_amendment_attempt_missing_scope_rejected(api):
    """PRD §2.9: "an amendment attempt must carry `amendment_scope`; a collateral-scope
    amendment must carry both `collateral_change_op` and `collateral_text`; an
    initial-filing attempt must carry `collateral_text`. Other structural violations
    surface as `ERR_INVALID_REQUEST` (400)."

    Design: Corner/validations/amendment_attempt_missing_scope_rejected
    """
    ctx = setup_active_initial_filing()
    amendment = create_ucc3_request(
        "AMENDMENT", ctx["client"], ctx["debtor"], ctx["secured_party"],
        ctx["filing"]["id"])
    submit_intake(amendment["id"], user_id="spec-1")
    approve_preparation(amendment["id"])
    payload = {"debtor_name_on_filing": "Acme Manufacturing, Inc."}
    resp = api.create_attempt(amendment["id"], payload, SPECIALIST)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_fee_authorization_exceeded_plain(api):
    """PRD §3.4: "The fee computed from the profile's current values must not exceed
    the request's `fee_authorization_cents`; an excess is rejected with
    `ERR_FEE_AUTHORIZATION_EXCEEDED` (HTTP 402)."
    PRD §2.7: "Submission debits the ledger and rejection refunds it; nothing else
    moves these totals, so the pair always reconciles against the client's filing
    history."

    Design: Corner/validations/fee_authorization_exceeded_plain
    """
    world = setup_client_world()
    request = create_ready_request(world["client"], world["debtor"],
                                   world["secured_party"],
                                   fee_authorization_cents=5000)
    attempt = create_draft_attempt(request["id"])
    resp = api.submit_filing(attempt["id"], SPECIALIST)
    validate_error(resp, ApiErrorId.ERR_FEE_AUTHORIZATION_EXCEEDED)
    filing = get_filing(attempt["id"])
    assert filing["effectiveness_status"] == "DRAFT"
    assert filing.get("charged_fee_cents") is None, "no fee is locked on a failed submit"
    assert get_client_account(world["client"]["id"])["fees_charged_total_cents"] == 0, (
        "a failed submission must not debit the ledger"
    )


def test_safety_error_wins_over_fiscal_on_submit(api):
    """PRD §2.9: "Incoming requests are checked in a fixed order, and the first failing
    check determines the error returned."
    PRD §2.9 item 8: "Segregation of duties
    (`ERR_SEGREGATION_OF_DUTIES`), debtor-name accuracy
    (`ERR_DEBTOR_NAME_SERIOUSLY_MISLEADING`, `ERR_DEBTOR_DL_NAME_MISSING`), collateral
    sufficiency (`ERR_COLLATERAL_INSUFFICIENTLY_DESCRIBED`), county-office consistency
    (`ERR_COUNTY_REQUIRED`, `ERR_COUNTY_NOT_IN_JURISDICTION`), perfection-slot overlap
    (`ERR_OVERLAPPING_ACTIVE_FILING`), and collateral-delete presence
    (`ERR_COLLATERAL_NOT_PRESENT`)."
    PRD §2.9 item 11: "The charged fee may not exceed the client's authorization
    (`ERR_FEE_AUTHORIZATION_EXCEEDED`, 402)."

    Design: Difficulty/priority_pair_validation_conflict/safety_vs_fiscal_on_attempt_submit
    """
    world = setup_client_world()
    request = create_ready_request(world["client"], world["debtor"],
                                   world["secured_party"],
                                   fee_authorization_cents=5000)
    # Misleading debtor name AND a fee (10000) above the 5000 authorization.
    attempt = create_draft_attempt(
        request["id"], debtor_name_on_filing="Acme Mfg, Inc.",
        secured_amount_cents=500000)
    resp = api.submit_filing(attempt["id"], SPECIALIST)
    validate_error(resp, ApiErrorId.ERR_DEBTOR_NAME_SERIOUSLY_MISLEADING)
    filing = get_filing(attempt["id"])
    assert filing["effectiveness_status"] == "DRAFT"
    assert filing.get("charged_fee_cents") is None


def test_misleading_debtor_name_rejected_on_submit(api):
    """PRD §3.4: "The normalized `debtor_name_on_filing` must equal the normalized name
    of record exactly; a mismatch is rejected with
    `ERR_DEBTOR_NAME_SERIOUSLY_MISLEADING`."

    Design: Difficulty/priority_pair_validation_conflict/safety_vs_fiscal_on_attempt_submit
    """
    world = setup_client_world()
    request = create_ready_request(world["client"], world["debtor"],
                                   world["secured_party"])
    attempt = create_draft_attempt(
        request["id"], debtor_name_on_filing="Acme Mfg, Inc.")
    resp = api.submit_filing(attempt["id"], SPECIALIST)
    validate_error(resp, ApiErrorId.ERR_DEBTOR_NAME_SERIOUSLY_MISLEADING)
    assert get_filing(attempt["id"])["effectiveness_status"] == "DRAFT"


def test_expedited_daily_capacity_exceeded(api):
    """PRD §3.4: "When the request's `service_level` is `EXPEDITED`, the number of
    expedited attempt submissions already made for the jurisdiction on the current UTC
    calendar day must not yet have reached the profile's `expedited_daily_capacity`;
    a jurisdiction at capacity rejects further expedited submissions that day with
    `ERR_EXPEDITED_CAPACITY_REACHED`."

    Design: Difficulty/resource_temporal_overlap/expedited_daily_capacity_bucket_reset
    """
    world = setup_client_world()
    attempts = []
    for _ in range(3):
        request = create_ready_request(
            world["client"], world["debtor"], world["secured_party"],
            service_level="EXPEDITED")
        attempts.append(create_draft_attempt(request["id"]))
    submit_attempt(attempts[0]["id"])
    submit_attempt(attempts[1]["id"])
    resp = api.submit_filing(attempts[2]["id"], SPECIALIST)
    validate_error(resp, ApiErrorId.ERR_EXPEDITED_CAPACITY_REACHED)
    assert get_filing(attempts[2]["id"])["effectiveness_status"] == "DRAFT", (
        "the capacity rejection must leave the third attempt in DRAFT"
    )


def test_expedited_capacity_resets_next_utc_day(api):
    """PRD §3.1: "`expedited_daily_capacity` (the maximum number of `EXPEDITED` attempt
    submissions accepted per UTC calendar day for the jurisdiction)".
    PRD §3.4: "On success the fee is locked onto the attempt as `charged_fee_cents`,
    the client's `fees_charged_total_cents` increases by `charged_fee_cents`,
    `submitted_at` is set to the current instant, the attempt moves `DRAFT` →
    `SUBMITTED`, the parent request moves `READY` → `IN_PROCESS`, and a `SUBMITTED`
    event is appended."

    Design: Difficulty/resource_temporal_overlap/expedited_daily_capacity_bucket_reset
    """
    world = setup_client_world()
    attempts = []
    for _ in range(3):
        request = create_ready_request(
            world["client"], world["debtor"], world["secured_party"],
            service_level="EXPEDITED")
        attempts.append(create_draft_attempt(request["id"]))
    first = submit_attempt(attempts[0]["id"])
    second = submit_attempt(attempts[1]["id"])
    resp = api.submit_filing(attempts[2]["id"], SPECIALIST)
    validate_error(resp, ApiErrorId.ERR_EXPEDITED_CAPACITY_REACHED)
    # Moving the logical clock to the next UTC day opens a fresh capacity bucket.
    set_clock_to("2026-08-02T00:00:00Z")
    third = submit_attempt(attempts[2]["id"])
    assert third["effectiveness_status"] == "SUBMITTED"
    assert third["charged_fee_cents"] == 15000, (
        f"10000 * 1.5 locks at 15000 on the successful submit, got "
        f"{third['charged_fee_cents']}"
    )
    assert first["effectiveness_status"] == "SUBMITTED"
    assert second["effectiveness_status"] == "SUBMITTED"
