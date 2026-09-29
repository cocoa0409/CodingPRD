"""Co-tenancy monitoring, rent relief and the kick-out right: the occupancy
monitor's cascade, the two relief variants, the event's branching lifecycle
and the tenant's two escape hatches.
"""
from test_helpers import (
    accept_report, acknowledge_event, activate_lease,
    activate_relief, ApiErrorId, assert_co_tenancy_event,
    assert_kick_out_clause, assert_relief_credit_consistent,
    attach_co_tenancy_clause, attach_kick_out_clause, close_period,
    create_anchor_tenant, create_center, create_lease, create_tenant,
    cure_event, events_for_clause, first_event_for_clause, LEASE_ADMIN,
    make_center_admin_headers, make_tenant_headers, open_lease_year,
    read_center, read_clause, read_event, read_kick_out, read_lease,
    read_lease_year, read_tenant, reconcile, schedule_monthly_report,
    set_clock, set_tenant_status, setup_acknowledged_co_tenancy_event,
    setup_active_lease, setup_center_with_dark_anchor, setup_lease_year,
    setup_relief_active_lease, setup_triggered_kick_out, submit_report,
    TEST_DEFAULTS, validate_error, validate_success,
)

ARTIFICIAL_BREAKPOINT = TEST_DEFAULTS["ARTIFICIAL_BREAKPOINT_CENTS"]
UNREACHABLE_BREAKPOINT = TEST_DEFAULTS["UNREACHABLE_BREAKPOINT_CENTS"]


def _two_leases_differing_only_in_relief_type():
    """Identical rent and identical 9,000,000 sales history under each variant."""
    set_clock(TEST_DEFAULTS["CLOCK_AT_YEAR_START"])
    center = create_center()
    anchor = create_anchor_tenant(center["id"])
    scene = {"center": center, "anchor": anchor}
    for key, relief_type, suite in (("reduction", "RENT_REDUCTION", "201"),
                                    ("alternative", "ALTERNATIVE_SALES_RENT",
                                     "202")):
        tenant = create_tenant(center["id"], legal_name=f"{key.title()} LLC",
                               trade_name=f"{key.title()} Shop")
        lease = activate_lease(
            create_lease(center["id"], tenant["id"], suite_code=suite)["id"])
        lease_year = open_lease_year(lease["id"])
        report = schedule_monthly_report(lease_year["id"], 1)
        submit_report(report["id"], tenant["id"], 9_000_000)
        accept_report(report["id"])
        clause = attach_co_tenancy_clause(
            lease["id"], required_open_anchor_count=1, required_occupancy_bps=0,
            cure_period_days=0, relief_type=relief_type, relief_pct_bps=800,
            termination_right_after_days=180)
        scene[key] = {"tenant": tenant, "lease": lease,
                      "lease_year": lease_year, "clause": clause}

    set_tenant_status(anchor["id"], "DARK")
    for key in ("reduction", "alternative"):
        event = first_event_for_clause(scene[key]["clause"]["id"])
        scene[key]["event"] = acknowledge_event(event["id"])
    return scene


def _relief_active_lease_with_triggered_kick_out():
    """One lease carrying both a triggered kick-out right and active relief."""
    set_clock(TEST_DEFAULTS["CLOCK_AT_YEAR_START"])
    center = create_center()
    anchor = create_anchor_tenant(center["id"])
    tenant = create_tenant(center["id"], legal_name="Relief Retail LLC",
                           trade_name="ReliefShop")
    lease = activate_lease(
        create_lease(center["id"], tenant["id"], suite_code="1901",
                     breakpoint_type="ARTIFICIAL",
                     artificial_breakpoint_cents=ARTIFICIAL_BREAKPOINT)["id"])
    kick_out = attach_kick_out_clause(lease["id"],
                                      threshold_sales_cents=100_000_000,
                                      election_window_days=30)
    clause = attach_co_tenancy_clause(lease["id"], required_open_anchor_count=1,
                                      required_occupancy_bps=0,
                                      cure_period_days=0,
                                      relief_type="RENT_REDUCTION",
                                      relief_pct_bps=5000,
                                      termination_right_after_days=180)
    lease_year = open_lease_year(lease["id"])
    report = schedule_monthly_report(lease_year["id"], 1)
    submit_report(report["id"], tenant["id"], 30_000_000)
    accept_report(report["id"])
    close_period(lease_year["id"])
    set_clock("2026-11-01T00:00:00Z")
    lease_year = reconcile(lease_year["id"])

    set_tenant_status(anchor["id"], "DARK")
    event = first_event_for_clause(clause["id"])
    acknowledge_event(event["id"])
    event = activate_relief(event["id"], "ca-relief-1")

    return {"center": center, "anchor": anchor, "tenant": tenant,
            "lease": read_lease(lease["id"]), "kick_out": read_kick_out(kick_out["id"]),
            "clause": clause, "lease_year": lease_year, "event": event}


# ─── The occupancy monitor's cascade ──────────────────────────────────────

def test_anchor_going_dark_drops_the_open_anchor_count_and_occupancy(api):
    """PRD §3.1: "`open_anchor_count` becomes the number of tenants of that
    center whose `is_anchor` is true **and** whose `status` is `OPERATING` —
    dark and vacated anchors do not count, which is precisely why an anchor
    going dark is a co-tenancy event."
    PRD §3.1: "`occupancy_bps` becomes the occupied area multiplied by 10000
    and divided by `total_gla_sqft`, floored to a whole basis point, and is
    defined as 0 when `total_gla_sqft` is zero."

    Design: Difficulty/transitive_cascade/anchor_goes_dark_cascades_to_lease_co_tenancy_status_depth_four
    """
    scene = setup_center_with_dark_anchor(
        clause_overrides={"cure_period_days": 30, "relief_pct_bps": 5000},
        suite_code="901")

    assert read_tenant(scene["anchor"]["id"])["status"] == "DARK"
    center_now = read_center(scene["center"]["id"])
    assert center_now["open_anchor_count"] == 0
    assert center_now["occupied_gla_sqft"] == 4_000, (
        "the anchor never had a lease, so only the inline lease is occupied")
    assert center_now["occupancy_bps"] == 100


def test_anchor_going_dark_opens_an_event_and_moves_the_lease_posture(api):
    """PRD §3.1: "When a clause is violated and it does not already have a
    co-tenancy event in `OPEN`, `CURE_PENDING` or `RELIEF_ACTIVE`, the monitor
    opens one. The new event records `clause_id`, an `event_type` of
    `ANCHOR_WENT_DARK` when the anchor-count leg was the failing test and
    `OCCUPANCY_BELOW_FLOOR` when it was the occupancy leg, a
    `trigger_tenant_id` naming the tenant whose status change caused this run
    when that tenant is an anchor and null otherwise, an `observed_at` set to
    the logical clock's current instant, and a `cure_deadline_at` equal to
    `observed_at` advanced by the clause's `cure_period_days` whole days."
    PRD §3.1: "The fourth, caused by the third, is the lease-side posture
    change: each lease that just received a new co-tenancy event has its
    `co_tenancy_status` moved `COMPLIANT → VIOLATION_OPEN`."

    Design: Difficulty/transitive_cascade/anchor_goes_dark_cascades_to_lease_co_tenancy_status_depth_four
    """
    from test_helpers import assert_instant_equals

    scene = setup_center_with_dark_anchor(
        clause_overrides={"cure_period_days": 30, "relief_pct_bps": 5000},
        suite_code="901")

    assert read_clause(scene["clause"]["id"])["monitoring_status"] == "VIOLATED"

    events = events_for_clause(scene["clause"]["id"])
    assert len(events) == 1
    event = events[0]
    assert_co_tenancy_event(event)
    assert event["status"] == "OPEN"
    assert event["event_type"] == "ANCHOR_WENT_DARK"
    assert event["trigger_tenant_id"] == scene["anchor"]["id"]
    assert_instant_equals(event["cure_deadline_at"], "2026-10-01T00:00:00Z",
                          "cure_deadline_at is observed_at plus 30 whole days")

    lease_now = read_lease(scene["lease"]["id"])
    assert lease_now["co_tenancy_status"] == "VIOLATION_OPEN"
    assert lease_now["status"] == "ACTIVE", (
        "the lease's own status is untouched until relief is activated")
    assert lease_now["effective_monthly_rent_cents"] == 1_000_000


def test_occupancy_exactly_at_the_required_floor_is_satisfied(api):
    """PRD §3.1: "A clause is violated when the center's recomputed
    `open_anchor_count` is strictly less than the clause's
    `required_open_anchor_count`, or when the center's recomputed
    `occupancy_bps` is strictly less than the clause's `required_occupancy_bps`.
    Both comparisons are strictly-less-than, so a center whose open anchor
    count exactly equals the required count, or whose occupancy in basis points
    exactly equals the required floor, is satisfied and not violated."
    PRD §3.9: "The clause is created with `monitoring_status` of `SATISFIED`,
    but the center's occupancy monitor of Section 3.1 runs immediately on
    creation — so a clause attached into an already-violating center flips
    straight to `VIOLATED` and opens a co-tenancy event in the same request."

    Design: Corner/calculations/occupancy_bps_equal_to_required_floor_is_satisfied
    """
    scene = setup_active_lease(suite_code="5501", leased_sqft=100_000,
                               tenant_overrides={"legal_name": "Big Box LLC",
                                                 "trade_name": "BigBox",
                                                 "gla_sqft": 100_000})
    assert read_center(scene["center"]["id"])["occupancy_bps"] == 2500

    at_floor = attach_co_tenancy_clause(
        scene["lease"]["id"], required_open_anchor_count=0,
        required_occupancy_bps=2500, cure_period_days=0,
        relief_type="RENT_REDUCTION", relief_pct_bps=1000,
        termination_right_after_days=180)
    above_floor = attach_co_tenancy_clause(
        scene["lease"]["id"], required_open_anchor_count=0,
        required_occupancy_bps=2501, cure_period_days=0,
        relief_type="RENT_REDUCTION", relief_pct_bps=1000,
        termination_right_after_days=180)

    assert read_clause(at_floor["id"])["monitoring_status"] == "SATISFIED"
    assert events_for_clause(at_floor["id"]) == []

    assert read_clause(above_floor["id"])["monitoring_status"] == "VIOLATED"
    breached = events_for_clause(above_floor["id"])
    assert len(breached) == 1
    assert breached[0]["event_type"] == "OCCUPANCY_BELOW_FLOOR"
    assert breached[0]["trigger_tenant_id"] is None
    assert read_lease(scene["lease"]["id"])["co_tenancy_status"] == "VIOLATION_OPEN"


def test_reopening_a_dark_anchor_satisfies_the_clause_without_curing_the_event(api):
    """PRD §3.1: "And when a dark box reopens on `DARK → OPERATING`, clauses
    whose tests now pass flip `VIOLATED → SATISFIED`, but their already-open
    co-tenancy events are **not** auto-cured: a `LeaseAdministrator` must close
    them explicitly, which is the workflow described in Section 3.9."

    Design: Corner/state_machines/dark_anchor_reopening_returns_clause_to_satisfied
    """
    scene = setup_center_with_dark_anchor(suite_code="4401")

    reopened = set_tenant_status(scene["anchor"]["id"], "OPERATING")

    assert reopened["status"] == "OPERATING"
    assert read_center(scene["center"]["id"])["open_anchor_count"] == 1
    assert read_clause(scene["clause"]["id"])["monitoring_status"] == "SATISFIED"

    events = events_for_clause(scene["clause"]["id"])
    assert len(events) == 1
    assert events[0]["status"] == "OPEN", (
        "an open violation event is never auto-cured by the monitor")


# ─── The co-tenancy event's branching lifecycle ───────────────────────────

def test_relief_branch_reduces_rent_and_moves_the_lease_to_relief_active(api):
    """PRD §3.9: "Activation stamps `relief_started_at` from the logical clock,
    runs the relief computation below, moves the lease `ACTIVE →
    RELIEF_ACTIVE`, sets the lease's `co_tenancy_status` to `RELIEF_ACTIVE`,
    and records the acting administrator's `X-User-ID` in the lease's
    `relief_approved_by_user_id`."
    PRD §3.9: "Under `RENT_REDUCTION`, relief is a fixed share of contract base
    rent and is completely independent of the tenant's sales. The monthly
    abatement is the unreduced monthly figure multiplied by the clause's
    `relief_pct_bps` and divided by 10000, rounded half up to whole cents, and
    the lease's `effective_monthly_rent_cents` becomes the unreduced monthly
    figure less that abatement."

    Design: Difficulty/non_linear_state_machine/co_tenancy_event_branches_to_relief_or_direct_cure
    """
    from test_helpers import assert_instant_equals

    scene = setup_acknowledged_co_tenancy_event(
        clause_overrides={"relief_pct_bps": 800}, suite_code="701")

    event = activate_relief(scene["event"]["id"], "ca-relief-1")

    assert event["status"] == "RELIEF_ACTIVE"
    assert_instant_equals(event["relief_started_at"], "2026-09-01T00:00:00Z",
                          "relief_started_at is stamped from the logical clock")

    lease_now = read_lease(scene["lease"]["id"])
    assert lease_now["status"] == "RELIEF_ACTIVE"
    assert lease_now["co_tenancy_status"] == "RELIEF_ACTIVE"
    assert lease_now["effective_monthly_rent_cents"] == 920_000
    assert lease_now["relief_monthly_credit_cents"] == 80_000
    assert lease_now["relief_approved_by_user_id"] == "ca-relief-1"


def test_direct_cure_branch_closes_the_event_and_leaves_rent_untouched(api):
    """PRD §3.9: "If the landlord fixes the underlying problem — a new anchor
    opens, occupancy recovers — the monitor flips the clause back to
    `SATISFIED` and a `LeaseAdministrator` closes the event `CURE_PENDING →
    CURED`, which sets the lease's `co_tenancy_status` back to `COMPLIANT` and
    leaves the lease's own status entirely untouched, because relief was never
    activated. This is the branch that skips relief altogether."

    Design: Difficulty/non_linear_state_machine/co_tenancy_event_branches_to_relief_or_direct_cure
    """
    scene = setup_acknowledged_co_tenancy_event(
        clause_overrides={"relief_pct_bps": 800}, suite_code="702")
    set_tenant_status(scene["anchor"]["id"], "OPERATING")

    event = cure_event(scene["event"]["id"])

    assert event["status"] == "CURED"
    assert event["relief_started_at"] is None, (
        "the cure branch never activated relief")

    lease_now = read_lease(scene["lease"]["id"])
    assert lease_now["status"] == "ACTIVE"
    assert lease_now["co_tenancy_status"] == "COMPLIANT"
    assert lease_now["effective_monthly_rent_cents"] == 1_000_000
    assert lease_now["relief_monthly_credit_cents"] == 0
    assert read_clause(scene["clause"]["id"])["monitoring_status"] == "SATISFIED"


def test_curing_an_unacknowledged_event_is_refused(api):
    """PRD §3.9: "A co-tenancy event opens in `OPEN` and follows a branching
    lifecycle. A `LeaseAdministrator` acknowledges it, moving `OPEN →
    CURE_PENDING`; acknowledgement changes no rent and does not restart the
    cure clock, which has been running from the `cure_deadline_at` declared
    when the event was created."
    PRD §2.9: "The rejection is the state code matching the entity that
    blocked: `ERR_TENANT_STATE_INVALID`, `ERR_LEASE_STATE_INVALID`,
    `ERR_LEASE_YEAR_STATE_INVALID`, `ERR_REPORT_STATE_INVALID`,
    `ERR_CHARGE_STATE_INVALID`, `ERR_CO_TENANCY_EVENT_STATE_INVALID`,
    `ERR_KICK_OUT_STATE_INVALID` or `ERR_AUDIT_STATE_INVALID`, each HTTP 409."

    Design: Corner/state_machines/cure_co_tenancy_event_from_open_rejected
    """
    scene = setup_center_with_dark_anchor(suite_code="4301")

    validate_error(
        api.cure_co_tenancy_event(scene["event"]["id"], LEASE_ADMIN),
        ApiErrorId.ERR_CO_TENANCY_EVENT_STATE_INVALID.value, 409)

    assert read_event(scene["event"]["id"])["status"] == "OPEN"
    assert read_lease(scene["lease"]["id"])["co_tenancy_status"] == "VIOLATION_OPEN"


def test_activating_relief_before_the_cure_deadline_is_refused(api):
    """PRD §3.9: "If instead the cure period lapses, a `CenterAdmin` activates
    relief `CURE_PENDING → RELIEF_ACTIVE`, which requires the logical clock to
    read at or after the event's `cure_deadline_at` — an earlier attempt is
    refused with `ERR_CURE_PERIOD_NOT_ELAPSED` — requires the clause's
    `monitoring_status` to still be `VIOLATED`, and requires the lease to be
    `ACTIVE`."

    Design: Corner/state_machines/activate_relief_before_cure_deadline_rejected
    """
    from test_helpers import assert_instant_equals

    scene = setup_acknowledged_co_tenancy_event(
        clause_overrides={"cure_period_days": 30, "relief_pct_bps": 5000},
        suite_code="4201")

    validate_error(
        api.activate_relief(scene["event"]["id"],
                            make_center_admin_headers("ca-relief-1")),
        ApiErrorId.ERR_CURE_PERIOD_NOT_ELAPSED.value, 409)

    event_now = read_event(scene["event"]["id"])
    assert event_now["status"] == "CURE_PENDING"
    assert_instant_equals(event_now["cure_deadline_at"], "2026-10-01T00:00:00Z",
                          "the cure deadline is thirty whole days out")

    lease_now = read_lease(scene["lease"]["id"])
    assert lease_now["status"] == "ACTIVE"
    assert lease_now["effective_monthly_rent_cents"] == 1_000_000
    assert lease_now["relief_approved_by_user_id"] is None


def test_electing_termination_before_the_right_ripens_is_refused(api):
    """PRD §3.9: "Alternatively, when relief has run long enough, the tenant
    walks: a `TenantUser` on the lease moves the event `RELIEF_ACTIVE →
    TERMINATION_ELECTED`, which requires the logical clock to read at or after
    `relief_started_at` advanced by the clause's `termination_right_after_days`
    whole days — an earlier attempt is refused with
    `ERR_TERMINATION_RIGHT_NOT_RIPE`."

    Design: Corner/state_machines/elect_termination_before_right_ripens_rejected
    """
    scene = setup_relief_active_lease(suite_code="4801")

    validate_error(
        api.elect_termination(scene["event"]["id"],
                              make_tenant_headers(scene["tenant"]["id"])),
        ApiErrorId.ERR_TERMINATION_RIGHT_NOT_RIPE.value, 409)

    event_now = read_event(scene["event"]["id"])
    assert event_now["status"] == "RELIEF_ACTIVE"
    assert event_now["relief_ended_at"] is None

    lease_now = read_lease(scene["lease"]["id"])
    assert lease_now["status"] == "RELIEF_ACTIVE"
    assert lease_now["effective_monthly_rent_cents"] == 500_000


# ─── The two relief variants ──────────────────────────────────────────────

def test_rent_reduction_relief_is_a_fixed_share_of_contract_rent(api):
    """PRD §3.9: "Both start from the unreduced monthly figure: the lease's
    `annual_base_rent_cents` divided by twelve, rounded half up to whole
    cents."
    PRD §3.9: "Under `RENT_REDUCTION`, relief is a fixed share of contract base
    rent and is completely independent of the tenant's sales. The monthly
    abatement is the unreduced monthly figure multiplied by the clause's
    `relief_pct_bps` and divided by 10000, rounded half up to whole cents, and
    the lease's `effective_monthly_rent_cents` becomes the unreduced monthly
    figure less that abatement."

    Design: Difficulty/dual_variant_calc/co_tenancy_relief_type_divergence_on_lease_rent
    """
    scene = _two_leases_differing_only_in_relief_type()

    activate_relief(scene["reduction"]["event"]["id"], "ca-relief-1")

    lease_now = read_lease(scene["reduction"]["lease"]["id"])
    assert lease_now["natural_breakpoint_cents"] == 200_000_000
    assert lease_now["effective_monthly_rent_cents"] == 920_000, (
        "eight percent of the 1,000,000 unreduced monthly figure is abated")
    assert lease_now["relief_monthly_credit_cents"] == 80_000
    assert_relief_credit_consistent(lease_now, 1_000_000)
    assert lease_now["status"] == "RELIEF_ACTIVE"
    assert lease_now["relief_approved_by_user_id"] == "ca-relief-1"


def test_alternative_sales_rent_relief_follows_trailing_net_sales(api):
    """PRD §3.9: "Under `ALTERNATIVE_SALES_RENT`, relief instead resets rent to
    a share of what the store is actually selling. The service gathers every
    sales report across **all** reporting years of that lease whose status is
    `ACCEPTED` or `ADJUSTED` — estimated and under-audit reports are excluded
    so that a landlord estimate can never inflate an alternative-rent floor —
    sorts them by `period_end` newest first with ties broken by `created_at`
    newest first, and takes the three most recent. The average net is the sum
    of `net_sales_cents` across that window divided by the number of reports in
    it, rounded half up to whole cents. The alternative rent is that average
    multiplied by the clause's `relief_pct_bps` and divided by 10000, rounded
    half up to whole cents. The lease's `effective_monthly_rent_cents` becomes
    the smaller of the unreduced monthly figure and that alternative rent —
    which means a tenant selling strongly enough that its alternative rent
    equals or exceeds contract rent receives no relief at all."
    PRD §3.9: "In both variants the lease's `relief_monthly_credit_cents` is
    set to the unreduced monthly figure less the resulting
    `effective_monthly_rent_cents`, and every named rounding is applied in the
    order written rather than deferred to the end."

    Design: Difficulty/dual_variant_calc/co_tenancy_relief_type_divergence_on_lease_rent
    """
    scene = _two_leases_differing_only_in_relief_type()

    activate_relief(scene["reduction"]["event"]["id"], "ca-relief-1")
    activate_relief(scene["alternative"]["event"]["id"], "ca-relief-1")

    alternative = read_lease(scene["alternative"]["lease"]["id"])
    assert alternative["effective_monthly_rent_cents"] == 720_000, (
        "eight percent of the single 9,000,000 accepted period, which is below "
        "the 1,000,000 contract figure")
    assert alternative["relief_monthly_credit_cents"] == 280_000
    assert_relief_credit_consistent(alternative, 1_000_000)
    assert alternative["status"] == "RELIEF_ACTIVE"

    reduction = read_lease(scene["reduction"]["lease"]["id"])
    assert reduction["status"] == "RELIEF_ACTIVE"
    assert reduction["effective_monthly_rent_cents"] == 920_000, (
        "identical inputs, a different variant, a different answer")


# ─── Kick-out rights ──────────────────────────────────────────────────────

def test_exercising_a_still_armed_kick_out_right_is_refused(api):
    """PRD §3.9: "The clause is created `ARMED`, with `triggered_at` and
    `election_deadline_at` both null and `waiver_consideration_cents` at 0."
    PRD §3.9: "`WAIVED`, `EXERCISED` and `EXPIRED` are all terminal; a clause
    in any of them refuses further exercise or waiver with
    `ERR_KICK_OUT_STATE_INVALID`."
    PRD §3.9: "The tenant exercises it — a `TenantUser` on the lease moving the
    clause `TRIGGERED → EXERCISED`, which drives the lease `ACTIVE →
    TERMINATION_PENDING`."

    Design: Corner/state_machines/exercise_kick_out_while_armed_rejected
    """
    scene = setup_lease_year(
        suite_code="4501", breakpoint_type="ARTIFICIAL",
        artificial_breakpoint_cents=ARTIFICIAL_BREAKPOINT)
    kick_out = attach_kick_out_clause(scene["lease"]["id"],
                                      threshold_sales_cents=100_000_000,
                                      election_window_days=30)
    assert_kick_out_clause(kick_out)
    assert kick_out["status"] == "ARMED"

    validate_error(
        api.exercise_kick_out_clause(
            kick_out["id"], make_tenant_headers(scene["tenant"]["id"])),
        ApiErrorId.ERR_KICK_OUT_STATE_INVALID.value, 409)

    clause_now = read_kick_out(kick_out["id"])
    assert clause_now["status"] == "ARMED"
    assert clause_now["triggered_at"] is None
    assert read_lease(scene["lease"]["id"])["status"] == "ACTIVE"


def test_exercising_after_the_election_deadline_is_refused(api):
    """PRD §3.9: "Exercise carries four preconditions beyond the clause being
    `TRIGGERED`: the measurement reporting year, meaning the year of the same
    lease whose `year_index` equals the clause's `measurement_year_index`, must
    be `RECONCILED`, otherwise
    `ERR_KICK_OUT_MEASUREMENT_YEAR_NOT_RECONCILED`; the logical clock must read
    at or before `election_deadline_at`, otherwise
    `ERR_KICK_OUT_ELECTION_WINDOW_CLOSED`; and the lease must be `ACTIVE`,
    because a lease already sitting in `RELIEF_ACTIVE` cannot also be kicked
    out — that attempt is refused with `ERR_RELIEF_ACTIVE_BLOCKS_EXERCISE`."

    Design: Corner/validations/exercise_after_election_window_closed_rejected
    """
    from test_helpers import assert_instant_equals

    scene = setup_triggered_kick_out(suite_code="6701")
    assert scene["kick_out"]["status"] == "TRIGGERED"
    assert_instant_equals(scene["kick_out"]["triggered_at"],
                          "2026-11-01T00:00:00Z", "triggered_at")
    set_clock("2026-12-02T00:00:00Z")

    validate_error(
        api.exercise_kick_out_clause(
            scene["kick_out"]["id"], make_tenant_headers(scene["tenant"]["id"])),
        ApiErrorId.ERR_KICK_OUT_ELECTION_WINDOW_CLOSED.value, 409)

    assert read_kick_out(scene["kick_out"]["id"])["status"] == "TRIGGERED"
    assert read_lease_year(scene["lease_year"]["id"])["status"] == "RECONCILED"
    assert read_lease(scene["lease"]["id"])["status"] == "ACTIVE"


def test_kick_out_exercise_is_blocked_while_the_lease_sits_in_relief(api):
    """PRD §3.9: "and the lease must be `ACTIVE`, because a lease already
    sitting in `RELIEF_ACTIVE` cannot also be kicked out — that attempt is
    refused with `ERR_RELIEF_ACTIVE_BLOCKS_EXERCISE`."
    PRD §3.9: "If the year's `cumulative_net_sales_cents` is strictly less than
    the clause's `threshold_sales_cents`, the clause moves `ARMED →
    TRIGGERED`, `triggered_at` is stamped from the logical clock, and
    `election_deadline_at` is set to `triggered_at` advanced by
    `election_window_days` whole days."

    Design: Difficulty/cross_entity_state_dependency/kick_out_exercise_blocked_by_lease_relief_active
    """
    from test_helpers import assert_instant_equals

    scene = _relief_active_lease_with_triggered_kick_out()

    validate_error(
        api.exercise_kick_out_clause(
            scene["kick_out"]["id"], make_tenant_headers(scene["tenant"]["id"])),
        ApiErrorId.ERR_RELIEF_ACTIVE_BLOCKS_EXERCISE.value, 409)

    clause_now = read_kick_out(scene["kick_out"]["id"])
    assert clause_now["status"] == "TRIGGERED", (
        "the election window is still open; only the lease's posture blocked it")
    assert_instant_equals(clause_now["election_deadline_at"],
                          "2026-12-01T00:00:00Z", "election_deadline_at")


def test_relief_active_lease_keeps_its_reduced_rent_after_the_refused_exercise(api):
    """PRD §3.9: "Activation stamps `relief_started_at` from the logical clock,
    runs the relief computation below, moves the lease `ACTIVE →
    RELIEF_ACTIVE`, sets the lease's `co_tenancy_status` to `RELIEF_ACTIVE`,
    and records the acting administrator's `X-User-ID` in the lease's
    `relief_approved_by_user_id`."
    PRD §3.9: "and the lease must be `ACTIVE`, because a lease already sitting
    in `RELIEF_ACTIVE` cannot also be kicked out — that attempt is refused with
    `ERR_RELIEF_ACTIVE_BLOCKS_EXERCISE`."

    Design: Difficulty/cross_entity_state_dependency/kick_out_exercise_blocked_by_lease_relief_active
    """
    scene = _relief_active_lease_with_triggered_kick_out()

    validate_error(
        api.exercise_kick_out_clause(
            scene["kick_out"]["id"], make_tenant_headers(scene["tenant"]["id"])),
        ApiErrorId.ERR_RELIEF_ACTIVE_BLOCKS_EXERCISE.value, 409)

    assert read_lease_year(scene["lease_year"]["id"])["status"] == "RECONCILED"
    lease_now = read_lease(scene["lease"]["id"])
    assert lease_now["status"] == "RELIEF_ACTIVE"
    assert lease_now["effective_monthly_rent_cents"] == 500_000, (
        "a fifty-percent reduction of the 1,000,000 unreduced monthly figure")


def test_relief_approver_may_not_also_waive_the_kick_out_right(api):
    """PRD §2.1: "The `CenterAdmin` who waives a kick-out right on a lease must
    not be the same `CenterAdmin` whose `X-User-ID` was recorded in that
    lease's `relief_approved_by_user_id` when co-tenancy relief was activated.
    When they are the same identifier, the waiver is refused with
    `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
    PRD §3.9: "Or the landlord buys the right out. A `CenterAdmin` moves the
    clause `TRIGGERED → WAIVED`, optionally recording a
    `waiver_consideration_cents` amount of at least zero as the cash paid for
    the waiver, and the acting administrator's `X-User-ID` is written to the
    lease's `waiver_approved_by_user_id`."

    Design: Corner/rbac/waive_kick_out_by_relief_approver_returns_segregation_of_duties
    """
    scene = _relief_active_lease_with_triggered_kick_out()

    validate_error(
        api.waive_kick_out_clause(scene["kick_out"]["id"],
                                  {"waiver_consideration_cents": 2_500_000},
                                  make_center_admin_headers("ca-relief-1")),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)
    assert read_kick_out(scene["kick_out"]["id"])["status"] == "TRIGGERED"

    waived = validate_success(
        api.waive_kick_out_clause(scene["kick_out"]["id"],
                                  {"waiver_consideration_cents": 2_500_000},
                                  make_center_admin_headers("ca-waiver-2")))

    assert waived["status"] == "WAIVED"
    assert waived["waiver_consideration_cents"] == 2_500_000

    lease_now = read_lease(scene["lease"]["id"])
    assert lease_now["waiver_approved_by_user_id"] == "ca-waiver-2"
    assert lease_now["relief_approved_by_user_id"] == "ca-relief-1"
