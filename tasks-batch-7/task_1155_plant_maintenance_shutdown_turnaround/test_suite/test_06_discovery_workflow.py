"""Discovery work and change authorization: segregation of duties, contingency
fiscal guard, shape-vs-state ordering, the appeal loop and its limit, and the
authorization cascade into committed cost and posture."""
from test_helpers import (
    ApiErrorId,
    validate_error,
    validate_success,
    make_manager_headers,
    make_operations_headers,
    report_discovery,
    setup_execution_turnaround,
    triage_discovery,
)

REPORTER = "tm-100"
DECIDER = "tm-200"


def _report_and_triage(api, turnaround_id, **overrides):
    """Report a discovery as REPORTER and triage it. Returns the TRIAGED dict."""
    discovery = report_discovery(turnaround_id, REPORTER, **overrides)
    return triage_discovery(discovery["id"])


def test_discovery_decide_by_reporter_rejected_as_sod(
    api, manager_headers, operations_headers
):
    """PRD §3.6: "The decision step is where segregation of duties bites: the
    decider's `X-User-ID` must differ from the recorded `reported_by_user_id`,
    and a match is rejected with `ERR_SOD_VIOLATION`."

    Design: Corner/validations/sod_discovery_decide_by_reporter_rejected
    """
    ctx = setup_execution_turnaround()
    t_id = ctx["turnaround"]["id"]
    discovery = _report_and_triage(
        api, t_id, description="Nozzle scarfing needed",
        quoted_cost_cents=50000, quoted_hours=12,
    )

    resp = api.decide_discovery(
        discovery["id"],
        {"outcome": "AUTHORIZED", "authorized_cost_cents": 50000},
        make_manager_headers(REPORTER),
    )
    validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION)

    after = validate_success(api.get_discovery(discovery["id"], manager_headers))
    assert after["status"] == "TRIAGED", "SoD rejection must not move the machine"

    decided = validate_success(
        api.decide_discovery(
            discovery["id"],
            {"outcome": "AUTHORIZED", "authorized_cost_cents": 50000},
            make_manager_headers(DECIDER),
        )
    )
    assert decided["status"] == "AUTHORIZED"


def test_authorize_above_remaining_contingency_rejected(api, manager_headers):
    """PRD §3.6: "An `outcome` of `AUTHORIZED` requires `authorized_cost_cents`
    to be present and strictly positive — its absence or a non-positive value
    draws `ERR_INVALID_REQUEST` — and the authorized amount must not exceed the
    turnaround's `contingency_remaining_cents`, defined as the
    `contingency_budget_cents` minus the sum of `authorized_cost_cents` across
    all discoveries already standing in `AUTHORIZED`; an overdraw is rejected
    with `ERR_CONTINGENCY_EXCEEDED`."

    Design: Corner/validations/contingency_exceeded_on_authorize
    """
    ctx = setup_execution_turnaround(contingency_budget_cents=100000)
    t_id = ctx["turnaround"]["id"]
    discovery = _report_and_triage(
        api, t_id, description="Big discovery",
        quoted_cost_cents=150000, quoted_hours=30,
    )

    resp = api.decide_discovery(
        discovery["id"],
        {"outcome": "AUTHORIZED", "authorized_cost_cents": 150000},
        make_manager_headers(DECIDER),
    )
    validate_error(resp, ApiErrorId.ERR_CONTINGENCY_EXCEEDED)

    addenda = validate_success(
        api.list_discovery_work_items(discovery["id"], manager_headers)
    )
    assert addenda == [], "a rejected authorization must create no addendum"
    after = validate_success(api.get_discovery(discovery["id"], manager_headers))
    assert after["status"] == "TRIAGED"
    assert after["authorized_cost_cents"] is None


def test_decide_missing_outcome_reports_shape_before_state(api, manager_headers):
    """PRD §2.8: "Every request is evaluated against a fixed cascade of checks,
    and the first failing check in this order determines the error returned."
    PRD §2.8: "5. Request shape: required fields are present, enum members are
    valid, quantities are positive where required, and windows start before
    they end; failure yields `ERR_INVALID_REQUEST`." precedes "7. State
    legality: the target resource is in a legal state for the operation per its
    state machine".

    Design: Corner/validations/decide_shape_error_beats_state_error
    """
    ctx = setup_execution_turnaround()
    discovery = report_discovery(
        ctx["turnaround"]["id"], REPORTER,
        description="Packing leak", quoted_cost_cents=20000, quoted_hours=6,
    )
    assert discovery["status"] == "REPORTED"  # never triaged

    # missing the required `outcome` field: shape (tier 5) beats state (tier 7)
    resp = api.decide_discovery(discovery["id"], {}, make_manager_headers(DECIDER))
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_third_appeal_rejected_at_appeal_limit(api, manager_headers):
    """PRD §3.6: "Rejection is not necessarily final: while `appeal_count`
    remains below two, a `ContractorSupervisor` or `TurnaroundManager` may
    appeal, moving the discovery back from `REJECTED` to `TRIAGED`,
    incrementing `appeal_count` by one, and returning the quote to the pending
    set with a fresh forecast recompute. Once `appeal_count` has reached two,
    further appeals are rejected with `ERR_APPEAL_LIMIT`."

    Design: Corner/errors/appeal_limit_rejected
    """
    ctx = setup_execution_turnaround()
    discovery = _report_and_triage(
        api, ctx["turnaround"]["id"],
        description="Demister pad fouling", quoted_cost_cents=90000,
        quoted_hours=20,
    )
    d_id = discovery["id"]

    for expected_count in (1, 2):
        validate_success(
            api.decide_discovery(
                d_id, {"outcome": "REJECTED"}, make_manager_headers(DECIDER)
            )
        )
        appealed = validate_success(
            api.appeal_discovery(d_id, make_manager_headers(REPORTER))
        )
        assert appealed["status"] == "TRIAGED"
        assert appealed["appeal_count"] == expected_count

    validate_success(
        api.decide_discovery(
            d_id, {"outcome": "REJECTED"}, make_manager_headers(DECIDER)
        )
    )
    resp = api.appeal_discovery(d_id, make_manager_headers(REPORTER))
    validate_error(resp, ApiErrorId.ERR_APPEAL_LIMIT)


def test_operations_rep_cannot_decide_discovery(api, manager_headers):
    """PRD §4: "| POST | `/discoveries/{id}/decide` | Authorize against
    contingency or reject a `TRIAGED` discovery; segregation of duties
    enforced | TurnaroundManager |"
    PRD §2.1: "A request whose role is not permitted for the endpoint, or that
    fails an entity-backed ownership check, is rejected with `ERR_FORBIDDEN`."

    Design: Corner/rbac/operations_rep_cannot_decide_discovery
    """
    ctx = setup_execution_turnaround(contingency_budget_cents=1000000)
    discovery = _report_and_triage(
        api, ctx["turnaround"]["id"],
        description="Packing leak", quoted_cost_cents=20000, quoted_hours=6,
    )

    resp = api.decide_discovery(
        discovery["id"],
        {"outcome": "AUTHORIZED", "authorized_cost_cents": 20000},
        make_operations_headers("ops-1"),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    after = validate_success(api.get_discovery(discovery["id"], manager_headers))
    assert after["status"] == "TRIAGED"


def _setup_reject_appeal_cycle(api):
    """EXECUTION turnaround (contingency 1000000); discovery REPORTED by
    tm-100 (quoted 90000 / 20h, origin W1) and TRIAGED."""
    ctx = setup_execution_turnaround()
    t_id = ctx["turnaround"]["id"]
    w1 = ctx["items"][0]
    discovery = _report_and_triage(
        api, t_id,
        origin_work_item_id=w1["id"],
        description="Tray damage beyond inspection scope",
        quoted_cost_cents=90000, quoted_hours=20,
    )
    return ctx, w1, discovery


def test_reject_appeal_cycle_returns_discovery_to_triaged(api):
    """PRD §3.6: "An `outcome` of `REJECTED` removes the quote from the
    forecast's pending set and recomputes the forecast — which can itself relax
    the turnaround's `cost_posture`. Rejection is not necessarily final: while
    `appeal_count` remains below two, a `ContractorSupervisor` or
    `TurnaroundManager` may appeal, moving the discovery back from `REJECTED`
    to `TRIAGED`, incrementing `appeal_count` by one, and returning the quote
    to the pending set with a fresh forecast recompute."

    Design: Difficulty/non_linear_state_machine/discovery_reject_appeal_cycle
    """
    _ctx, _w1, discovery = _setup_reject_appeal_cycle(api)
    d_id = discovery["id"]

    rejected = validate_success(
        api.decide_discovery(d_id, {"outcome": "REJECTED"}, make_manager_headers(DECIDER))
    )
    assert rejected["status"] == "REJECTED"

    appealed = validate_success(
        api.appeal_discovery(d_id, make_manager_headers(REPORTER))
    )
    assert appealed["status"] == "TRIAGED"
    assert appealed["appeal_count"] == 1

    authorized = validate_success(
        api.decide_discovery(
            d_id,
            {"outcome": "AUTHORIZED", "authorized_cost_cents": 90000},
            make_manager_headers(DECIDER),
        )
    )
    assert authorized["status"] == "AUTHORIZED"
    assert authorized["authorized_by_user_id"] == DECIDER


def test_authorize_after_appeal_creates_addendum_work_item(api, manager_headers):
    """PRD §3.6: "First, an addendum work item is created on the same
    turnaround with `work_type` of `DISCOVERY_ADDENDUM`, `risk_class` of `C`,
    `requires_permit` false, `status` of `FROZEN`, `estimated_cost_cents` equal
    to the authorized amount, `estimated_hours` equal to the discovery's
    `quoted_hours`, and a `discovery_id` back-reference to the discovery that
    spawned it; the turnaround's `committed_cost_cents` is then recomputed with
    the addendum's estimate included."

    Design: Difficulty/non_linear_state_machine/discovery_reject_appeal_cycle
    """
    _ctx, _w1, discovery = _setup_reject_appeal_cycle(api)
    d_id = discovery["id"]
    validate_success(
        api.decide_discovery(d_id, {"outcome": "REJECTED"}, make_manager_headers(DECIDER))
    )
    validate_success(api.appeal_discovery(d_id, make_manager_headers(REPORTER)))
    validate_success(
        api.decide_discovery(
            d_id,
            {"outcome": "AUTHORIZED", "authorized_cost_cents": 90000},
            make_manager_headers(DECIDER),
        )
    )

    addenda = validate_success(api.list_discovery_work_items(d_id, manager_headers))
    assert len(addenda) == 1, f"expected exactly one addendum, got {len(addenda)}"
    addendum = addenda[0]
    assert addendum["status"] == "FROZEN"
    assert addendum["work_type"] == "DISCOVERY_ADDENDUM"
    assert addendum["estimated_cost_cents"] == 90000
    assert addendum["estimated_hours"] == 20
    assert addendum["discovery_id"] == d_id


def _setup_authorize_cascade(api):
    """EXECUTION turnaround (budget 300000, contingency 1000000) with one
    FROZEN item estimated at 200000; discovery quoted 150000/40h TRIAGED."""
    ctx = setup_execution_turnaround(
        authorized_budget_cents=300000,
        contingency_budget_cents=1000000,
        work_item_overrides={
            "title": "Drum inspection", "system_area": "CRU-2-D",
            "work_type": "INSPECTION", "risk_class": "B",
            "estimated_hours": 30, "estimated_cost_cents": 200000,
        },
    )
    t_id = ctx["turnaround"]["id"]
    discovery = _report_and_triage(
        api, t_id,
        origin_work_item_id=ctx["items"][0]["id"],
        description="Internal corrosion found",
        quoted_cost_cents=150000, quoted_hours=40,
    )
    return ctx, discovery


def test_authorize_creates_frozen_addendum_and_bumps_committed(api, manager_headers):
    """PRD §3.6: "First, an addendum work item is created on the same
    turnaround with `work_type` of `DISCOVERY_ADDENDUM`, `risk_class` of `C`,
    `requires_permit` false, `status` of `FROZEN`, `estimated_cost_cents` equal
    to the authorized amount, `estimated_hours` equal to the discovery's
    `quoted_hours`, and a `discovery_id` back-reference to the discovery that
    spawned it; the turnaround's `committed_cost_cents` is then recomputed with
    the addendum's estimate included."

    Design: Difficulty/transitive_cascade/discovery_authorize_committed_posture_cascade
    """
    ctx, discovery = _setup_authorize_cascade(api)
    decided = validate_success(
        api.decide_discovery(
            discovery["id"],
            {"outcome": "AUTHORIZED", "authorized_cost_cents": 150000},
            make_manager_headers(DECIDER),
        )
    )
    assert decided["status"] == "AUTHORIZED"

    addenda = validate_success(
        api.list_discovery_work_items(discovery["id"], manager_headers)
    )
    assert len(addenda) == 1
    assert addenda[0]["status"] == "FROZEN"
    assert addenda[0]["estimated_cost_cents"] == 150000

    turnaround = validate_success(api.get_turnaround(ctx["turnaround"]["id"], manager_headers))
    assert turnaround["committed_cost_cents"] == 350000, (
        "200000 frozen scope + 150000 authorized addendum: "
        f"{turnaround['committed_cost_cents']} != 350000"
    )


def test_authorize_flips_cost_posture_to_overrun(api, manager_headers):
    """PRD §3.8: "`cost_posture` is `OVERRUN` when `committed_cost_cents`
    exceeds `authorized_budget_cents`, otherwise `AT_RISK` when
    `forecast_provisional_cents` exceeds `authorized_budget_cents`, otherwise
    `WITHIN_BUDGET`."
    PRD §3.6: "Second, the cost forecast is recomputed and the turnaround's
    `cost_posture` flips per its own machine."

    Design: Difficulty/transitive_cascade/discovery_authorize_committed_posture_cascade
    """
    ctx, discovery = _setup_authorize_cascade(api)
    validate_success(
        api.decide_discovery(
            discovery["id"],
            {"outcome": "AUTHORIZED", "authorized_cost_cents": 150000},
            make_manager_headers(DECIDER),
        )
    )

    turnaround = validate_success(api.get_turnaround(ctx["turnaround"]["id"], manager_headers))
    assert turnaround["cost_posture"] == "OVERRUN", (
        "committed 350000 > authorized budget 300000 must force OVERRUN: "
        f"{turnaround['cost_posture']}"
    )


def _setup_rejected_discovery_small_contingency(api):
    """EXECUTION turnaround with contingency 100000; discovery reported by
    tm-100, triaged, then decided REJECTED by tm-200."""
    ctx = setup_execution_turnaround(contingency_budget_cents=100000)
    discovery = _report_and_triage(
        api, ctx["turnaround"]["id"],
        description="Flange face damage", quoted_cost_cents=90000,
        quoted_hours=20,
    )
    validate_success(
        api.decide_discovery(
            discovery["id"], {"outcome": "REJECTED"}, make_manager_headers(DECIDER)
        )
    )
    return ctx, discovery


def test_decide_on_rejected_discovery_reports_state_not_contingency(api):
    """PRD §2.8: "Every request is evaluated against a fixed cascade of checks,
    and the first failing check in this order determines the error returned."
    PRD §2.8: "7. State legality: the target resource is in a legal state for
    the operation per its state machine — this tier also covers scope-frozen
    edits, since work-item creation, re-estimation, and dependency edits are
    only legal while the turnaround is `PLANNING`; failure yields
    `ERR_INVALID_STATE`." precedes "12. Fiscal guard: a discovery authorization
    fits within the remaining contingency; failure yields
    `ERR_CONTINGENCY_EXCEEDED`."

    Design: Difficulty/priority_pair_validation_conflict/decide_rejected_state_error_beats_contingency_fiscal
    """
    _ctx, discovery = _setup_rejected_discovery_small_contingency(api)

    # 150000 also overdraws the 100000 contingency, but the REJECTED state gate
    # (tier 7) must surface before the fiscal guard (tier 12)
    resp = api.decide_discovery(
        discovery["id"],
        {"outcome": "AUTHORIZED", "authorized_cost_cents": 150000},
        make_manager_headers(DECIDER),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_failed_decide_leaves_rejected_discovery_unchanged(api, manager_headers):
    """PRD §2.8: "7. State legality: the target resource is in a legal state
    for the operation per its state machine — this tier also covers
    scope-frozen edits, since work-item creation, re-estimation, and dependency
    edits are only legal while the turnaround is `PLANNING`; failure yields
    `ERR_INVALID_STATE`."
    PRD §3.6: "The decision records `authorized_by_user_id` and the authorized
    amount, and the cascade increments both the discovery's `version` and the
    turnaround's `version` by one."

    Design: Difficulty/priority_pair_validation_conflict/decide_rejected_state_error_beats_contingency_fiscal
    """
    _ctx, discovery = _setup_rejected_discovery_small_contingency(api)
    resp = api.decide_discovery(
        discovery["id"],
        {"outcome": "AUTHORIZED", "authorized_cost_cents": 150000},
        make_manager_headers(DECIDER),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    after = validate_success(api.get_discovery(discovery["id"], manager_headers))
    assert after["status"] == "REJECTED"
    assert after["authorized_cost_cents"] is None
