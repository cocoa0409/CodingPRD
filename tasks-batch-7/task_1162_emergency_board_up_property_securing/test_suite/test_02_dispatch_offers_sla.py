"""Dispatch validation family, offer lifecycle, selector policy, SLA boundary,
capacity invariant, and dispatch-time clock anchoring."""
from test_helpers import (
    TEST_USERS,
    accept_offer,
    assert_same_instant,
    create_market,
    create_tac_market_payload,
    dispatch_job,
    get_assignment,
    get_job,
    get_subcontractor,
    grant_coverage,
    intake_job,
    make_subcontractor_headers,
    onboard_subcontractor,
    register_customer,
    register_property,
    set_clock,
    setup_dispatched_job,
    setup_on_site_job,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_dispatch_validation_error_family(api, admin_headers, dispatcher_headers):
    """PRD §3.2: "a dispatch attempted on a job not currently in `INTAKE` is
    rejected with `ERR_INVALID_STATE` — or `ERR_ALREADY_TERMINAL` for a `CLOSED`
    job — before any coverage pool is consulted."
    PRD §3.2: "the subcontractor must be `ACTIVE` (`ERR_SUBCONTRACTOR_SUSPENDED`),
    it must hold a coverage row in the job's market (`ERR_MARKET_MISMATCH`), and
    its `active_assignment_count` must be below that coverage row's
    `max_concurrent_jobs` (`ERR_CAPACITY_FULL`)."
    PRD §3.2: "An empty pool rejects the dispatch with `ERR_NO_COVERAGE`."

    Design: Corner/endpoints/dispatch_validation_error_family
    """
    sea = create_market()
    tac = validate_success(api.create_market(create_tac_market_payload(), admin_headers), 201)
    sx = onboard_subcontractor("Xray Crew")
    grant_coverage(sx["id"], sea["id"], max_concurrent_jobs=2, rank=1)
    sy = onboard_subcontractor("Yankee Crew")
    grant_coverage(sy["id"], tac["id"], max_concurrent_jobs=1, rank=1)
    customer = register_customer()
    prop = register_property(customer["id"], tac["id"], address_line="3 Tide Flats",
                             wind_zone="HIGH")
    ja = intake_job(prop["id"], incident_type="FIRE", priority="P3")
    jb = intake_job(prop["id"], incident_type="STORM", priority="P3")
    jc = intake_job(prop["id"], incident_type="VANDALISM", priority="P3")
    # Suspend sy before the suspended-pin probe.
    validate_success(api.patch_subcontractor(sy["id"], {"status": "SUSPENDED"}, admin_headers), 200)

    # e1: empty selector pool in TAC (sy suspended -> no ACTIVE candidate).
    res = api.dispatch_job(ja["id"], {}, dispatcher_headers)
    validate_error(res, "ERR_NO_COVERAGE")

    # e2: manual pin of a subcontractor with no coverage in the job's market.
    res = api.dispatch_job(ja["id"], {"subcontractor_id": sx["id"]}, dispatcher_headers)
    validate_error(res, "ERR_MARKET_MISMATCH")

    # e3: manual pin of a SUSPENDED subcontractor.
    res = api.dispatch_job(ja["id"], {"subcontractor_id": sy["id"]}, dispatcher_headers)
    validate_error(res, "ERR_SUBCONTRACTOR_SUSPENDED")

    # Re-instate sy, then saturate its single capacity slot via job jb.
    validate_success(api.patch_subcontractor(sy["id"], {"status": "ACTIVE"}, admin_headers), 200)
    asb = dispatch_job(jb["id"], subcontractor_id=sy["id"])
    accept_offer(asb["id"], sy["id"])

    # e4: manual pin while at max_concurrent_jobs.
    res = api.dispatch_job(jc["id"], {"subcontractor_id": sy["id"]}, dispatcher_headers)
    validate_error(res, "ERR_CAPACITY_FULL")

    # e5: jb is DISPATCHED, not INTAKE — state gate fires before pool checks.
    res = api.dispatch_job(jb["id"], {}, dispatcher_headers)
    validate_error(res, "ERR_INVALID_STATE")

    assert get_job(ja["id"])["work_status"] == "INTAKE", "rejected dispatches leave no residue"


def test_offer_expired_respond_triggers_reoffer(api, admin_headers, dispatcher_headers):
    """PRD §3.2: "Any respond or withdraw that arrives when the clock has passed
    `offer_expires_at` first flips the assignment `OFFERED` → `EXPIRED`, increments
    the subcontractor's `expired_offer_count`, fails the triggering call with
    `ERR_OFFER_EXPIRED`, and runs the same re-offer cascade as a decline."
    PRD §3.2: "on success the next `OFFERED` assignment is created and the job
    stays `DISPATCHED`"

    Design: Corner/state_machines/offer_expired_respond_triggers_reoffer
    """
    ctx = setup_dispatched_job(priority="P3", num_subcontractors=2, covered_count=2)
    sg, sh = ctx["subs"][0], ctx["subs"][1]
    offer = ctx["assignment"]
    assert offer["subcontractor_id"] == sg["id"], "rank 1 wins the initial reliability tie"

    set_clock("2026-05-01T00:31:00Z")  # 31 minutes past the 00:00 offer
    res = api.respond_assignment(offer["id"], {"outcome": "ACCEPT"},
                                 make_subcontractor_headers(sg["id"]))
    validate_error(res, "ERR_OFFER_EXPIRED")
    assert get_assignment(offer["id"])["status"] == "EXPIRED"
    assert get_subcontractor(sg["id"])["expired_offer_count"] == 1

    data, meta = validate_paginated(
        api.list_assignments(dispatcher_headers, params={"job_id": ctx["job"]["id"]}))
    assert meta["total_count"] == 2
    second = next(a for a in data if a["status"] == "OFFERED")
    assert second["subcontractor_id"] == sh["id"], "expired offeree excluded from retry"
    assert second["offer_seq"] == 2
    assert get_job(ctx["job"]["id"])["work_status"] == "DISPATCHED"


def test_selector_rank_tiebreak_and_retry_exclusion(api, dispatcher_headers):
    """PRD §3.2: "candidates are ranked by `reliability_score_lenient` descending,
    ties break toward the lower coverage `rank`, and any remaining tie falls back
    to the earlier `created_at` — an `id` is never used as a tie-break."
    PRD §3.2: "the selector runs again for the job, now additionally excluding
    every subcontractor that already holds a `DECLINED`, `EXPIRED`, or `CANCELLED`
    offer on this job"

    Design: Corner/cross_cutting_complexity_layers/selector_rank_tiebreak_and_retry_exclusion
    """
    ctx = setup_dispatched_job(priority="P3", num_subcontractors=2, covered_count=2)
    sj, sk = ctx["subs"][0], ctx["subs"][1]
    offer = ctx["assignment"]
    assert offer["subcontractor_id"] == sj["id"], "rank 1 breaks the 1.0-vs-1.0 reliability tie"
    assert offer["offer_seq"] == 1

    res = api.respond_assignment(offer["id"], {"outcome": "DECLINE"},
                                 make_subcontractor_headers(sj["id"]))
    declined = validate_success(res, 200)
    assert declined["status"] == "DECLINED"

    data, meta = validate_paginated(
        api.list_assignments(dispatcher_headers, params={"job_id": ctx["job"]["id"]}))
    assert meta["total_count"] == 2
    second = next(a for a in data if a["status"] == "OFFERED")
    assert second["subcontractor_id"] == sk["id"], "decliner excluded from the retry pool"
    assert second["offer_seq"] == 2
    assert get_job(ctx["job"]["id"])["work_status"] == "DISPATCHED"


def test_assignment_capacity_accept_withdraw_restores(api, dispatcher_headers):
    """PRD §3.1: "The platform maintains `active_assignment_count`, the number of
    the subcontractor's own assignments currently in `ACCEPTED` or `ARRIVED`
    status, recomputed as assignments are accepted, completed, or cancelled."
    PRD §3.2: "withdrawal moves it to `CANCELLED`, recomputes the active count
    downward where the assignment had been accepted, excludes the withdrawn
    subcontractor from the retry, and runs the identical cascade"

    Design: Difficulty/compensating_invariant/assignment_capacity_accept_withdraw_restores
    """
    ctx = setup_dispatched_job(priority="P3", num_subcontractors=1, covered_count=1)
    sf = ctx["subs"][0]
    offer = ctx["assignment"]
    assert get_subcontractor(sf["id"])["active_assignment_count"] == 0, (
        "an OFFERED offer does not consume capacity")

    accept_offer(offer["id"], sf["id"])
    assert get_subcontractor(sf["id"])["active_assignment_count"] == 1

    res = api.withdraw_assignment(offer["id"], dispatcher_headers)
    cancelled = validate_success(res, 200)
    assert cancelled["status"] == "CANCELLED"
    assert get_subcontractor(sf["id"])["active_assignment_count"] == 0, (
        "compensating withdraw must restore the counter exactly")
    assert get_job(ctx["job"]["id"])["work_status"] == "INTAKE", (
        "withdrawn subcontractor excluded; empty pool regresses the job")


def test_assignment_capacity_withdraw_unaccepted_offer_no_drift(api, dispatcher_headers):
    """PRD §3.1: "The platform maintains `active_assignment_count`, the number of
    the subcontractor's own assignments currently in `ACCEPTED` or `ARRIVED`
    status, recomputed as assignments are accepted, completed, or cancelled."
    PRD §3.2: "A `Dispatcher` may also withdraw an `OFFERED` or `ACCEPTED`
    assignment; withdrawal moves it to `CANCELLED`, recomputes the active count
    downward where the assignment had been accepted"

    Design: Difficulty/compensating_invariant/assignment_capacity_accept_withdraw_restores
    """
    ctx = setup_dispatched_job(priority="P3", num_subcontractors=1, covered_count=1)
    sf = ctx["subs"][0]
    offer = ctx["assignment"]
    assert offer["status"] == "OFFERED"
    assert get_subcontractor(sf["id"])["active_assignment_count"] == 0

    res = api.withdraw_assignment(offer["id"], dispatcher_headers)
    cancelled = validate_success(res, 200)
    assert cancelled["status"] == "CANCELLED"
    assert get_subcontractor(sf["id"])["active_assignment_count"] == 0, (
        "withdrawing a never-accepted offer must not drive the counter negative")
    assert get_job(ctx["job"]["id"])["work_status"] == "INTAKE"


def test_subcontractor_cannot_dispatch(api, dispatcher_headers):
    """PRD §2.1: "A request whose role is recognized but not permitted for the
    target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §4: dispatch is listed with authorized role "Dispatcher" only.

    Design: Corner/rbac/subcontractor_cannot_dispatch
    """
    from test_helpers import setup_network

    net = setup_network(num_subcontractors=1, covered_count=1)
    job = intake_job(net["property"]["id"], incident_type="FIRE", priority="P3")
    sa = net["subs"][0]

    res = api.dispatch_job(job["id"], {}, make_subcontractor_headers(sa["id"]))
    validate_error(res, "ERR_FORBIDDEN")
    assert get_job(job["id"])["work_status"] == "INTAKE"
    data, meta = validate_paginated(
        api.list_assignments(dispatcher_headers, params={"job_id": job["id"]}))
    assert meta["total_count"] == 0, "no assignment may be created by the rejected dispatch"


def test_check_in_by_non_assignee_rejected(api, dispatcher_headers):
    """PRD §3.3: "The caller must be exactly the `subcontractor_id` of the job's
    currently `ACCEPTED` assignment (`ERR_NOT_ASSIGNEE`)."

    Design: Corner/rbac/check_in_by_non_assignee_rejected
    """
    ctx = setup_dispatched_job(priority="P3", num_subcontractors=2, covered_count=2)
    sa = ctx["subs"][0]
    sb2 = ctx["subs"][1]
    accept_offer(ctx["assignment"]["id"], sa["id"])

    res = api.check_in_job(ctx["job"]["id"], make_subcontractor_headers(sb2["id"]))
    validate_error(res, "ERR_NOT_ASSIGNEE")
    assert get_job(ctx["job"]["id"])["work_status"] == "DISPATCHED"


def test_sla_exact_minute_compliant_at_boundary(api, admin_headers, dispatcher_headers):
    """PRD §3.3: "The flag `sla_breach` is set true only when `response_minutes`
    strictly exceeds the job's snapshotted `sla_minutes`; arriving in exactly the
    allotted minutes is compliant, not a breach."
    PRD §2.5: "Before any administrative intervention, the clock starts at
    exactly `2026-05-01T00:00:00Z` and must not fall back to wall-clock time
    under any circumstance."

    Design: Difficulty/boundary_precision_check/sla_exact_minute_compliant
    """
    ctx = setup_dispatched_job(priority="P1", num_subcontractors=1, covered_count=1)
    sa = ctx["subs"][0]
    assert ctx["job"]["sla_minutes"] == 120, "P1 snapshot of sla_minutes_p1"
    assert_same_instant(ctx["job"]["reported_at"], "2026-05-01T00:00:00Z"), (
        "unset clock default"
    )

    accept_offer(ctx["assignment"]["id"], sa["id"])
    set_clock("2026-05-01T02:00:00Z")  # exactly 120 minutes after the 00:00 dispatch
    res = api.check_in_job(ctx["job"]["id"], make_subcontractor_headers(sa["id"]))
    arrived = validate_success(res, 200)
    assert arrived["response_minutes"] == 120
    assert arrived["sla_breach"] is False, "equality with sla_minutes is compliant"
    assert get_job(ctx["job"]["id"])["work_status"] == "ON_SITE"


def test_sla_one_minute_over_breaches(api, admin_headers, dispatcher_headers):
    """PRD §3.3: "The response time, `response_minutes`, is the elapsed time
    between the job's `dispatched_at` and the assignment's `arrived_at`, expressed
    in whole minutes with partial minutes discarded."
    PRD §3.3: "The flag `sla_breach` is set true only when `response_minutes`
    strictly exceeds the job's snapshotted `sla_minutes`; arriving in exactly the
    allotted minutes is compliant, not a breach."

    Design: Difficulty/boundary_precision_check/sla_exact_minute_compliant
    """
    ctx = setup_dispatched_job(priority="P1", num_subcontractors=1, covered_count=1)
    sa = ctx["subs"][0]
    accept_offer(ctx["assignment"]["id"], sa["id"])
    set_clock("2026-05-01T02:01:00Z")  # 121 minutes after dispatch: one over the 120 SLA
    res = api.check_in_job(ctx["job"]["id"], make_subcontractor_headers(sa["id"]))
    arrived = validate_success(res, 200)
    assert arrived["response_minutes"] == 121
    assert arrived["sla_breach"] is True, "one minute over the SLA must breach"


def test_clock_default_timestamp_on_dispatch(api, dispatcher_headers):
    """PRD §2.5: "Before any administrative intervention, the clock starts at
    exactly `2026-05-01T00:00:00Z` and must not fall back to wall-clock time
    under any circumstance."
    PRD §3.2: "The offer is stamped `offered_at` and given `offer_expires_at`
    exactly 30 minutes later."

    Design: Corner/cross_cutting_complexity_layers/clock_default_timestamp_on_dispatch
    """
    ctx = setup_dispatched_job(priority="P3", num_subcontractors=1, covered_count=1)
    job = get_job(ctx["job"]["id"])
    assert_same_instant(job["reported_at"], "2026-05-01T00:00:00Z")
    offer = get_assignment(ctx["assignment"]["id"])
    assert_same_instant(offer["offered_at"], "2026-05-01T00:00:00Z")
    assert_same_instant(offer["offer_expires_at"], "2026-05-01T00:30:00Z")
