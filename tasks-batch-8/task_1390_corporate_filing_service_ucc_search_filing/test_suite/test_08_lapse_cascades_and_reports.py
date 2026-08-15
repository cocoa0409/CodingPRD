"""Lapse sweep and its cascade, the termination cascade, lapse/horizon boundary
precision, and the two perfection-report variants over one portfolio."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    accept_attempt,
    approve_preparation,
    create_draft_attempt,
    create_ready_request,
    create_ucc3_request,
    generate_report,
    get_filing,
    get_request,
    list_filing_events,
    order_lien_search,
    record_search_results,
    register_debtor,
    set_clock_to,
    setup_active_initial_filing,
    setup_client_world,
    submit_attempt,
    submit_intake,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
SPECIALIST = TEST_USERS["specialist_headers"]


def test_lapse_boundary_equality_lapses_one_second_survives(api):
    """PRD §3.6: "The lapse sweep — run whenever the logical clock moves and at the
    start of every perfection-report generation, with a lazy single-filing re-check
    whenever one filing is read — transitions every `ACTIVE` filing whose
    `expiration_at` is at or before the current instant from `ACTIVE` to `LAPSED`; the
    boundary lapses, so an expiration exactly equal to now ends effectiveness."

    Design: Corner/calculations/lapse_boundary_equality_lapses_one_second_survives
    """
    world = setup_client_world()
    debtor_b = register_debtor(
        world["client"]["id"], legal_name="Beta Holdings, LLC",
        jurisdiction_of_formation="CA")
    set_clock_to("2021-08-01T00:00:00Z")
    # Filing A expires exactly 2026-08-01T00:00:00Z.
    ctx_a = setup_active_initial_filing(
        world, filed_at="2021-08-01T00:00:00Z", filing_number="CA-2021-0001")
    set_clock_to("2021-08-01T00:00:01Z")
    # Filing B (different debtor, so a different perfection slot) expires one second later.
    ctx_b = setup_active_initial_filing(
        {**world, "debtor": debtor_b}, filed_at="2021-08-01T00:00:01Z",
        filing_number="CA-2021-0002",
        attempt_overrides={"debtor_name_on_filing": "Beta Holdings, LLC"})
    set_clock_to("2026-08-01T00:00:00Z")
    assert get_filing(ctx_a["filing"]["id"])["effectiveness_status"] == "LAPSED", (
        "expiration == now is inclusive: the filing lapses"
    )
    assert get_filing(ctx_b["filing"]["id"])["effectiveness_status"] == "ACTIVE", (
        "expiration one second past now survives the sweep"
    )


def test_horizon_boundary_inclusive_in_report(api):
    """PRD §3.8: "`expiring_within_horizon_count`, the `ACTIVE` attempts whose
    `expiration_at` falls on or before now plus `horizon_days` days — the boundary is
    inclusive, so an expiration exactly at the horizon is counted".

    Design: Corner/calculations/horizon_boundary_inclusive_in_report
    """
    set_clock_to("2021-10-30T00:00:00Z")
    ctx = setup_active_initial_filing(
        filed_at="2021-10-30T00:00:00Z", filing_number="CA-2021-0007",
        secured_amount_cents=100000)
    set_clock_to("2026-08-01T00:00:00Z")
    # Expiration 2026-10-30 == now + 90 days exactly: counted.
    report = generate_report(ctx["client"]["id"], mode="AS_OF_NOW", horizon_days=90)
    assert report["expiring_within_horizon_count"] == 1, (
        "an expiration exactly at the horizon boundary is counted"
    )
    assert report["active_count"] == 1


def test_termination_acceptance_cascades_to_open_requests(api):
    """PRD §3.5: "- **`TERMINATION`.** The root moves `ACTIVE` → `TERMINATED` with a
    `TERMINATED` event and a `version` increment, and the termination cascade fires:
    every other open `AMENDMENT` or `CONTINUATION` request targeting that root — any
    such request in `DRAFT_INTAKE`, `IN_REVIEW`, `READY`, or `CORRECTION_REQUIRED` —
    is cancelled with `cancel_reason` of `TARGET_TERMINATED`, and their `DRAFT`
    attempts are withdrawn."
    PRD §3.5: "In all cases the parent request moves `IN_PROCESS` → `FULFILLED`".

    Design: Difficulty/transitive_cascade/termination_acceptance_cascade_depth3
    """
    ctx = _setup_root_with_open_amendment_and_submitted_termination()
    accept_attempt(ctx["termination_attempt"]["id"], filing_number="CA-2026-0007",
                   filed_at="2026-08-01T00:00:00Z")
    root = get_filing(ctx["root"]["id"])
    assert root["effectiveness_status"] == "TERMINATED", "hop 1: the root terminates"
    amendment_request = get_request(ctx["amendment_request"]["id"])
    assert amendment_request["status"] == "CANCELLED", "hop 2: the open request is cancelled"
    assert amendment_request["cancel_reason"] == "TARGET_TERMINATED"
    assert get_filing(ctx["amendment_attempt"]["id"])["effectiveness_status"] == "WITHDRAWN", (
        "hop 3: the cancelled request's DRAFT attempt is withdrawn"
    )
    assert root["open_ucc3_request_count"] == 0, (
        "the open-request ledger settles back to 0"
    )
    assert get_request(ctx["termination_request"]["id"])["status"] == "FULFILLED"


def test_termination_cascade_appends_events_and_bumps_versions(api):
    """PRD §3.5: "The root moves `ACTIVE` → `TERMINATED` with a `TERMINATED` event and
    a `version` increment".
    PRD §2.5: "Every such cascade is a real mutation on each resource it touches:
    affected resources that carry `updated_at` and `version` have the former refreshed
    and the latter incremented, so downstream readers and concurrency checks always
    observe the ripple."

    Design: Difficulty/transitive_cascade/termination_acceptance_cascade_depth3
    """
    ctx = _setup_root_with_open_amendment_and_submitted_termination()
    root_version_before = get_filing(ctx["root"]["id"])["version"]
    accept_attempt(ctx["termination_attempt"]["id"], filing_number="CA-2026-0007",
                   filed_at="2026-08-01T00:00:00Z")
    root = get_filing(ctx["root"]["id"])
    root_events = [e["event_type"] for e in list_filing_events(root["id"])]
    assert "TERMINATED" in root_events, (
        f"the root must carry a TERMINATED event, got {root_events}"
    )
    withdrawn_events = [e["event_type"]
                        for e in list_filing_events(ctx["amendment_attempt"]["id"])]
    assert "WITHDRAWN" in withdrawn_events, (
        f"the cascade-withdrawn attempt must carry a WITHDRAWN event, got {withdrawn_events}"
    )
    assert root["version"] > root_version_before, (
        "the termination plus its cascade increment the root's version"
    )


def test_lapse_sweep_cancels_open_continuation_requests(api):
    """PRD §3.6: "Each lapse appends a `LAPSED` event and cascades: every open
    `CONTINUATION`-kind request targeting the lapsed filing — any such request in
    `DRAFT_INTAKE`, `IN_REVIEW`, `READY`, or `CORRECTION_REQUIRED` — is cancelled with
    `cancel_reason` of `TARGET_LAPSED`, its `DRAFT` attempts move to `WITHDRAWN`, the
    root's `open_ucc3_request_count` decreases by one per cancelled request, and the
    root's `version` increments accordingly."

    Design: Difficulty/transitive_cascade/lapse_sweep_cascade_depth3
    """
    ctx = _setup_root_with_open_continuation_for_lapse()
    set_clock_to("2026-08-01T00:00:00Z")  # expiration 2026-06-01 <= now: the sweep fires
    root = get_filing(ctx["root"]["id"])
    assert root["effectiveness_status"] == "LAPSED", "hop 1: the root lapses"
    continuation_request = get_request(ctx["continuation_request"]["id"])
    assert continuation_request["status"] == "CANCELLED", "hop 2: the request is cancelled"
    assert continuation_request["cancel_reason"] == "TARGET_LAPSED"
    assert get_filing(ctx["continuation_attempt"]["id"])["effectiveness_status"] == "WITHDRAWN", (
        "hop 3: the DRAFT attempt is withdrawn"
    )
    assert root["open_ucc3_request_count"] == 0


def test_lapse_appends_event_and_lazy_get_reflects_it(api):
    """PRD §3.6: "Each lapse appends a `LAPSED` event and cascades".
    PRD §2.4: "reading a single filing lazily re-applies the lapse rule to that one
    filing before the response is assembled, so an expired filing is never reported as
    still effective."

    Design: Difficulty/transitive_cascade/lapse_sweep_cascade_depth3
    """
    ctx = _setup_root_with_open_continuation_for_lapse()
    version_before = get_filing(ctx["root"]["id"])["version"]
    set_clock_to("2026-08-01T00:00:00Z")
    root = get_filing(ctx["root"]["id"])
    assert root["effectiveness_status"] == "LAPSED"
    root_events = [e["event_type"] for e in list_filing_events(root["id"])]
    assert "LAPSED" in root_events, f"the lapsed root must carry a LAPSED event, got {root_events}"
    assert root["version"] > version_before, (
        "the lapse plus its cascade increment the root's version"
    )


def test_report_as_of_now_buckets(api):
    """PRD §3.8: "Under `AS_OF_NOW`, the buckets are: `active_count`, the attempts
    whose `effectiveness_status` is `ACTIVE`; `perfected_count`, those both `ACTIVE`
    and `REFLECTED`; `unreflected_count`, those `ACTIVE` with reflection `UNVERIFIED`
    or `DISCREPANCY`; `expiring_within_horizon_count`, the `ACTIVE` attempts whose
    `expiration_at` falls on or before now plus `horizon_days` days — the boundary is
    inclusive, so an expiration exactly at the horizon is counted; `lapsed_count` and
    `terminated_count`, the attempts in `LAPSED` and `TERMINATED` respectively; and
    `projected_lapsed_count`, which is always zero in this mode."
    PRD §3.8: "`perfected_exposure_cents` sums `secured_amount_cents` over the initial
    filings counted in `perfected_count`; `unperfected_exposure_cents` sums it over
    the initial filings counted in `unreflected_count`".

    Design: Difficulty/dual_variant_calc/report_as_of_now_vs_forward_projection
    """
    ctx = _setup_report_portfolio()
    report = generate_report(ctx["client"]["id"], mode="AS_OF_NOW", horizon_days=90)
    assert report["active_count"] == 2
    assert report["perfected_count"] == 1
    assert report["unreflected_count"] == 1
    assert report["expiring_within_horizon_count"] == 1
    assert report["lapsed_count"] == 1
    assert report["terminated_count"] == 1
    assert report["projected_lapsed_count"] == 0
    assert report["perfected_exposure_cents"] == 500000
    assert report["unperfected_exposure_cents"] == 300000
    assert report["projected_lapsed_exposure_cents"] == 0


def test_report_forward_projection_reclassifies(api):
    """PRD §3.8: "Under `FORWARD_PROJECTION`, the same population is reclassified
    against the horizon: `projected_lapsed_count` counts the `ACTIVE` attempts whose
    `expiration_at` falls on or before `as_of`; `active_count` counts the `ACTIVE`
    attempts whose `expiration_at` is strictly after `as_of`; `perfected_count` counts
    those still effective at `as_of` that are also `REFLECTED`; `unreflected_count`
    counts those still effective at `as_of` whose reflection is not `REFLECTED`;
    `expiring_within_horizon_count` equals `projected_lapsed_count`".
    PRD §3.8: "The report's `as_of` is the current instant under `AS_OF_NOW` and the
    current instant plus `horizon_days` days under `FORWARD_PROJECTION`."

    Design: Difficulty/dual_variant_calc/report_as_of_now_vs_forward_projection
    """
    ctx = _setup_report_portfolio()
    report = generate_report(ctx["client"]["id"], mode="FORWARD_PROJECTION",
                             horizon_days=90)
    assert report["as_of"] == "2026-10-30T00:00:00Z"
    assert report["projected_lapsed_count"] == 1
    assert report["active_count"] == 1
    assert report["perfected_count"] == 0
    assert report["unreflected_count"] == 1
    assert report["expiring_within_horizon_count"] == 1
    assert report["lapsed_count"] == 1
    assert report["terminated_count"] == 1
    assert report["projected_lapsed_exposure_cents"] == 500000
    assert report["perfected_exposure_cents"] == 0
    assert report["unperfected_exposure_cents"] == 300000


# ---------------------------------------------------------------------------
# Scenario builders local to this file
# ---------------------------------------------------------------------------

def _setup_root_with_open_amendment_and_submitted_termination():
    """Root ACTIVE; an AMENDMENT request open in READY with a DRAFT attempt; a
    TERMINATION request (exempt from the one-open-ucc3 rule) with its attempt
    SUBMITTED."""
    ctx = setup_active_initial_filing(filed_at="2026-08-01T00:00:00Z",
                                      filing_number="CA-2026-0001")
    amendment = create_ucc3_request(
        "AMENDMENT", ctx["client"], ctx["debtor"], ctx["secured_party"],
        ctx["filing"]["id"])
    submit_intake(amendment["id"], user_id="spec-1")
    approve_preparation(amendment["id"])
    amendment_attempt = create_draft_attempt(
        amendment["id"], debtor_name_on_filing="Acme Manufacturing, Inc.",
        amendment_scope="COLLATERAL", collateral_change_op="ADD",
        collateral_text="All inventory stored at 200 Dock Street")
    termination = create_ucc3_request(
        "TERMINATION", ctx["client"], ctx["debtor"], ctx["secured_party"],
        ctx["filing"]["id"])
    submit_intake(termination["id"], user_id="spec-1")
    approve_preparation(termination["id"])
    termination_attempt = create_draft_attempt(
        termination["id"], debtor_name_on_filing="Acme Manufacturing, Inc.",
        collateral_text=None)
    submit_attempt(termination_attempt["id"])
    ctx.update({
        "root": ctx["filing"],
        "amendment_request": amendment,
        "amendment_attempt": amendment_attempt,
        "termination_request": termination,
        "termination_attempt": termination_attempt,
    })
    return ctx


def _setup_root_with_open_continuation_for_lapse():
    """Root filed 2021-06-01 (expiration 2026-06-01), ACTIVE, with a CONTINUATION
    request open in READY and its attempt sitting in DRAFT."""
    set_clock_to("2021-06-01T00:00:00Z")
    ctx = setup_active_initial_filing(filed_at="2021-06-01T00:00:00Z",
                                      filing_number="CA-2021-0001")
    continuation = create_ucc3_request(
        "CONTINUATION", ctx["client"], ctx["debtor"], ctx["secured_party"],
        ctx["filing"]["id"])
    submit_intake(continuation["id"], user_id="spec-1")
    approve_preparation(continuation["id"])
    continuation_attempt = create_draft_attempt(
        continuation["id"], debtor_name_on_filing="Acme Manufacturing, Inc.",
        collateral_text=None)
    ctx.update({
        "root": ctx["filing"],
        "continuation_request": continuation,
        "continuation_attempt": continuation_attempt,
    })
    return ctx


def _file_initial(client, debtor, secured_party, filing_number, filed_at,
                  secured_amount_cents):
    """One full NEW_UCC1 chain ending in an ACTIVE INITIAL filing."""
    request = create_ready_request(client, debtor, secured_party)
    attempt = create_draft_attempt(request["id"],
                                   secured_amount_cents=secured_amount_cents)
    submit_attempt(attempt["id"])
    return accept_attempt(attempt["id"], filing_number=filing_number,
                          filed_at=filed_at)


def _setup_report_portfolio():
    """Portfolio at 2026-08-01: F1 ACTIVE+REFLECTED 500000 expiring 2026-08-31;
    F2 ACTIVE+UNVERIFIED 300000 expiring 2027-03-01; F3 LAPSED 200000 (expired
    2026-06-01); F4 TERMINATED 100000. Each INITIAL filing uses its own debtor so the
    one-ACTIVE-per-(debtor, jurisdiction, office) slot rule is respected."""
    world = setup_client_world()
    client, sp = world["client"], world["secured_party"]
    debtors = [
        register_debtor(client["id"], legal_name="Acme Manufacturing, Inc.",
                        jurisdiction_of_formation="DE")
        for _ in range(4)
    ]
    # F3: filed 2021-06-01, expires 2026-06-01.
    set_clock_to("2021-06-01T00:00:00Z")
    _file_initial(client, debtors[2], sp, "CA-2021-0003", "2021-06-01T00:00:00Z", 200000)
    # F1: filed 2021-08-31, expires 2026-08-31; then verified REFLECTED.
    set_clock_to("2021-08-31T00:00:00Z")
    f1 = _file_initial(client, debtors[0], sp, "CA-2021-0001", "2021-08-31T00:00:00Z",
                       500000)
    search = order_lien_search(client, debtors[0], purpose="POST_FILING_VERIFICATION",
                               subject_filing_id=f1["id"])
    set_clock_to("2021-09-15T00:00:00Z")
    record_search_results(search["id"], "2021-09-15T00:00:00Z", [{
        "found_debtor_name": "Acme Manufacturing, Inc.",
        "found_filing_number": "CA-2021-0001",
        "found_filed_at": "2021-08-31T00:00:00Z",
        "secured_party_name": "Acme Lending",
    }])
    # F4: filed 2022-01-05, terminated 2022-01-20.
    set_clock_to("2022-01-05T00:00:00Z")
    f4 = _file_initial(client, debtors[3], sp, "CA-2022-0004", "2022-01-05T00:00:00Z",
                       100000)
    termination = create_ucc3_request("TERMINATION", client, debtors[3], sp, f4["id"])
    submit_intake(termination["id"], user_id="spec-1")
    approve_preparation(termination["id"])
    term_attempt = create_draft_attempt(
        termination["id"], debtor_name_on_filing="Acme Manufacturing, Inc.",
        collateral_text=None)
    submit_attempt(term_attempt["id"])
    set_clock_to("2022-01-20T00:00:00Z")
    accept_attempt(term_attempt["id"], filing_number="CA-2022-0005",
                   filed_at="2022-01-20T00:00:00Z")
    # F2: filed 2022-03-01, expires 2027-03-01, never verified.
    set_clock_to("2022-03-01T00:00:00Z")
    _file_initial(client, debtors[1], sp, "CA-2022-0002", "2022-03-01T00:00:00Z", 300000)
    # Back to the present; the sweep lapses F3.
    set_clock_to("2026-08-01T00:00:00Z")
    world["debtors"] = debtors
    return world
