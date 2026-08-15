"""Optimistic concurrency, the filing audit trail, reverse-FK filtered listings, and
the two conserved ledgers: client fee exposure and the root's open UCC-3 count."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    accept_attempt,
    approve_preparation,
    assert_filing_event,
    create_draft_attempt,
    create_filing_request,
    create_ready_request,
    create_ucc3_request,
    get_client_account,
    get_filing,
    get_request,
    list_filing_events,
    reject_attempt,
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


def test_occ_patch_stale_version(api):
    """PRD §2.8: "Updating a filing request's preparation fields requires
    `expected_request_version`, carrying the request's `version` as the client last
    observed it; if the request's version has advanced since that read, the update is
    rejected with `ERR_STALE_VERSION` (HTTP 412) rather than silently overwriting
    changes the client never saw."

    Design: Corner/cross_cutting_layers/occ_patch_stale_version
    """
    world = setup_client_world()
    request = create_filing_request(world["client"], world["debtor"],
                                    world["secured_party"])
    observed = request["version"]
    first = validate_success(
        api.patch_filing_request(
            request["id"],
            {"fee_authorization_cents": 90000, "expected_request_version": observed},
            SPECIALIST),
        expected_status=200)
    assert first["version"] == observed + 1, "the first PATCH bumps the version by one"
    resp = api.patch_filing_request(
        request["id"],
        {"fee_authorization_cents": 80000, "expected_request_version": observed},
        SPECIALIST,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
    assert get_request(request["id"])["fee_authorization_cents"] == 90000, (
        "the stale write must not land"
    )


def test_occ_ucc3_create_stale_target_version(api):
    """PRD §2.8: "Creating a filing request whose `kind` is `AMENDMENT`,
    `CONTINUATION`, or `TERMINATION` requires `expected_target_filing_version`,
    carrying the target root filing's current `version` as last observed; a mismatch
    with the root's actual `version` is likewise rejected with `ERR_STALE_VERSION`
    (HTTP 412)."
    PRD §3.2: "For the UCC-3 kinds, creation also adjusts the target root filing: its
    `open_ucc3_request_count` increases by one and its `version` increments by one."

    Design: Corner/cross_cutting_layers/occ_ucc3_create_stale_target_version
    """
    ctx = setup_active_initial_filing()
    root_id = ctx["filing"]["id"]
    v0 = get_filing(root_id)["version"]
    # The first UCC-3 creation succeeds and itself bumps the root's version.
    create_ucc3_request("AMENDMENT", ctx["client"], ctx["debtor"],
                        ctx["secured_party"], root_id,
                        expected_target_filing_version=v0)
    # A second creation still carrying the pre-bump version is stale.
    resp = api.create_filing_request(
        {
            "client_id": ctx["client"]["id"],
            "kind": "CONTINUATION",
            "debtor_id": ctx["debtor"]["id"],
            "secured_party_id": ctx["secured_party"]["id"],
            "jurisdiction_code": "CA",
            "collateral_class": "GENERAL",
            "fee_authorization_cents": 100000,
            "target_filing_id": root_id,
            "expected_target_filing_version": v0,
        },
        SPECIALIST,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
    assert get_filing(root_id)["open_ucc3_request_count"] == 1, (
        "the stale creation did not register against the root"
    )


def test_filing_event_log_order(api):
    """PRD §2.10: "Every UCC filing accumulates an immutable audit trail of filing
    events. Each event carries an `event_type` drawn from exactly this vocabulary —
    `CREATED`, `SUBMITTED`, `ACCEPTED`, `REJECTED`, `WITHDRAWN`, `CONTINUED`,
    `AMENDED`, `TERMINATED`, `LAPSED`, `REVIVED`, `REFLECTED`, and
    `DISCREPANCY_FLAGGED` — plus a structured `event_detail` payload appropriate to
    the event (for example the `rejection_reason_code` on a rejection, the `filed_at`
    on an acceptance, or the `prior_expiration_at` on a continuation) and an
    `occurred_at` timestamp read from the logical clock. Each event references its
    filing through `ucc_filing_id`, and the trail is listed in chronological order."

    Design: Corner/endpoints/filing_event_log_order
    """
    world = setup_client_world()
    request = create_ready_request(world["client"], world["debtor"], world["secured_party"])
    attempt = create_draft_attempt(request["id"])
    submit_attempt(attempt["id"])
    accept_attempt(attempt["id"], filing_number="CA-2026-0001",
                   filed_at="2026-08-01T00:00:00Z")
    events, meta = validate_paginated(api.list_filing_events(attempt["id"], ADMIN))
    assert meta["total_count"] == 3, f"create+submit+accept append 3 events, got {meta}"
    assert [e["event_type"] for e in events] == ["CREATED", "SUBMITTED", "ACCEPTED"]
    for event in events:
        assert_filing_event(event)
        assert event["ucc_filing_id"] == attempt["id"]
    assert events[2]["event_detail"].get("filed_at") == "2026-08-01T00:00:00Z", (
        "the acceptance event's detail carries the filed_at instant"
    )


def test_filtered_list_reverse_fk_lookup(api):
    """PRD §2.3: "The filing-request list filters by `client_id`, `debtor_id`,
    `secured_party_id`, `target_filing_id`, `supporting_search_id`, `status`, or
    `kind`. The filing list filters by `debtor_id`, `secured_party_id`,
    `root_filing_id`, `supersedes_attempt_id`, `effectiveness_status`,
    `reflection_status`, or `jurisdiction_code`, and thereby serves every reverse
    lookup from those foreign keys."

    Design: Corner/endpoints/filtered_list_reverse_fk_lookup
    """
    ctx = setup_active_initial_filing()
    root_id = ctx["filing"]["id"]
    amendment = create_ucc3_request(
        "AMENDMENT", ctx["client"], ctx["debtor"], ctx["secured_party"], root_id)
    submit_intake(amendment["id"], user_id="spec-1")
    approve_preparation(amendment["id"])
    attempt = create_draft_attempt(
        amendment["id"], debtor_name_on_filing="Acme Manufacturing, Inc.",
        amendment_scope="COLLATERAL", collateral_change_op="ADD",
        collateral_text="All inventory stored at 200 Dock Street")
    requests, meta_r = validate_paginated(
        api.list_filing_requests(ADMIN, params={"target_filing_id": root_id}))
    assert meta_r["total_count"] == 1 and requests[0]["id"] == amendment["id"]
    filings, meta_f = validate_paginated(
        api.list_filings(ADMIN, params={"root_filing_id": root_id}))
    assert meta_f["total_count"] == 1 and filings[0]["id"] == attempt["id"]


def test_fee_charge_refund_net_exposure_returns_to_zero(api):
    """PRD §2.7: "`fees_charged_total_cents` accumulates the `charged_fee_cents`
    debited across all attempt submissions for the client; `fees_refunded_total_cents`
    accumulates the `charged_fee_cents` credited back across all attempt rejections."
    PRD §3.5: "The rejection stores the code, the note, and `rejected_at`; credits the
    client's `fees_refunded_total_cents` by the attempt's `charged_fee_cents`; moves
    the attempt `SUBMITTED` → `REJECTED`; moves the parent request `IN_PROCESS` →
    `CORRECTION_REQUIRED`; and appends a `REJECTED` event."

    Design: Difficulty/compensating_invariant/fee_charge_refund_net_exposure_conserved
    """
    world = setup_client_world()
    client_id = world["client"]["id"]
    assert get_client_account(client_id)["fees_charged_total_cents"] == 0
    request = create_ready_request(world["client"], world["debtor"],
                                   world["secured_party"])
    attempt = create_draft_attempt(request["id"])
    submit_attempt(attempt["id"])
    mid = get_client_account(client_id)
    assert mid["fees_charged_total_cents"] == 10000, (
        "submission debits the locked fee (net exposure 10000)"
    )
    assert mid["fees_refunded_total_cents"] == 0
    reject_attempt(attempt["id"], reason="FEE_INCORRECT")
    end = get_client_account(client_id)
    assert end["fees_charged_total_cents"] == 10000
    assert end["fees_refunded_total_cents"] == 10000, (
        "the rejection refund returns net exposure to its pre-submit value"
    )
    assert end["fees_charged_total_cents"] - end["fees_refunded_total_cents"] == 0
    assert get_filing(attempt["id"])["effectiveness_status"] == "REJECTED"


def test_fee_ledger_reconciles_across_submissions_and_rejections(api):
    """PRD §2.7: "Submission debits the ledger and rejection refunds it; nothing else
    moves these totals, so the pair always reconciles against the client's filing
    history."

    Design: Difficulty/compensating_invariant/fee_charge_refund_net_exposure_conserved
    """
    world = setup_client_world()
    client_id = world["client"]["id"]
    # Two attempts submit (2 x 10000 debited); one is later rejected (10000 credited).
    req1 = create_ready_request(world["client"], world["debtor"], world["secured_party"])
    att1 = create_draft_attempt(req1["id"])
    submit_attempt(att1["id"])
    req2 = create_ready_request(world["client"], world["debtor"], world["secured_party"])
    att2 = create_draft_attempt(req2["id"])
    submit_attempt(att2["id"])
    reject_attempt(att1["id"], reason="WRONG_OFFICE")
    client = get_client_account(client_id)
    assert client["fees_charged_total_cents"] == 20000
    assert client["fees_refunded_total_cents"] == 10000
    live = client["fees_charged_total_cents"] - client["fees_refunded_total_cents"]
    assert live == 10000, (
        "net exposure equals the fee locked on the one attempt still SUBMITTED"
    )


def test_open_ucc3_count_create_cancel_pair_conserved(api):
    """PRD §3.2: "For the UCC-3 kinds, creation also adjusts the target root filing:
    its `open_ucc3_request_count` increases by one and its `version` increments by
    one."
    PRD §3.6: "Cancellation sets the request to `CANCELLED` with `cancel_reason` of
    `CLIENT_REQUEST`, withdraws any `DRAFT` attempt under it (with a `WITHDRAWN`
    event), and — for the UCC-3 kinds — decreases the target root's
    `open_ucc3_request_count` by one and increments the root's `version` by one."

    Design: Difficulty/compensating_invariant/open_ucc3_request_count_conserved
    """
    ctx = setup_active_initial_filing()
    root_id = ctx["filing"]["id"]
    before = get_filing(root_id)
    assert before["open_ucc3_request_count"] == 0
    amendment = create_ucc3_request(
        "AMENDMENT", ctx["client"], ctx["debtor"], ctx["secured_party"], root_id)
    after_create = get_filing(root_id)
    assert after_create["open_ucc3_request_count"] == 1
    assert after_create["version"] == before["version"] + 1
    validate_success(api.cancel_filing_request(amendment["id"], SPECIALIST),
                     expected_status=200)
    after_cancel = get_filing(root_id)
    assert after_cancel["open_ucc3_request_count"] == 0, "the ledger is conserved"
    assert after_cancel["version"] == before["version"] + 2
    cancelled = get_request(amendment["id"])
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["cancel_reason"] == "CLIENT_REQUEST"


def test_open_ucc3_count_decremented_on_fulfillment(api):
    """PRD §3.5: "In all cases the parent request moves `IN_PROCESS` → `FULFILLED`;
    when the request kind is not `NEW_UCC1`, fulfillment also decreases the target
    root's `open_ucc3_request_count` by one and increments the root's `version` by
    one."

    Design: Difficulty/compensating_invariant/open_ucc3_request_count_conserved
    """
    ctx = setup_active_initial_filing()
    root_id = ctx["filing"]["id"]
    amendment = create_ucc3_request(
        "AMENDMENT", ctx["client"], ctx["debtor"], ctx["secured_party"], root_id)
    submit_intake(amendment["id"], user_id="spec-1")
    approve_preparation(amendment["id"])
    assert get_filing(root_id)["open_ucc3_request_count"] == 1
    attempt = create_draft_attempt(
        amendment["id"], debtor_name_on_filing="Acme Manufacturing, Inc.",
        amendment_scope="SECURED_PARTY")
    submit_attempt(attempt["id"])
    accept_attempt(attempt["id"], filing_number="CA-2026-0011",
                   filed_at="2026-08-01T00:00:00Z")
    assert get_request(amendment["id"])["status"] == "FULFILLED"
    assert get_filing(root_id)["open_ucc3_request_count"] == 0, (
        "fulfillment decrements the root's open UCC-3 count back to 0"
    )
