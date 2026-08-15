"""Green tariff programs and subscriptions: holding-account gating on open,
archive referential guard, the program-OPEN state gate, capacity branch
(ACTIVE vs WAITLISTED) and join via the promotion scan, exact-fit boundary,
capacity conservation across terminate/promote rounds, skip-and-continue
ordering, creation-time guards, and OCC on program writes."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    activate_subscription,
    assert_program,
    assert_subscription,
    create_account,
    create_program,
    create_program_payload,
    create_subscription,
    create_subscription_payload,
    get_program,
    get_subscription,
    patch_program,
    set_clock,
    setup_open_program,
    terminate_subscription,
    validate_error,
    validate_success,
    wire_and_open_program,
)

ADMIN = TEST_USERS["registry_admin_headers"]
PM = TEST_USERS["program_manager_headers"]


# ---------------------------------------------------------------------------
# Program open/archive guards
# ---------------------------------------------------------------------------

def test_program_open_without_holding_account_rejected(api):
    """PRD §3.5: "Opening a program moves it from `DRAFT` to `OPEN` and is
    only possible once `holding_account_id` references an existing account of
    `account_type` `PROGRAM` that is wired back to this program through its
    own `program_id`; opening without such a wired holding account is
    rejected with `ERR_PROGRAM_HOLDING_ACCOUNT_MISSING`."

    Design: Corner/errors/program_open_without_holding_account_rejected
    """
    program = create_program()
    resp = api.open_program(program["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_PROGRAM_HOLDING_ACCOUNT_MISSING, expected_status=422)
    assert get_program(program["id"])["status"] == "DRAFT"

    wired = wire_and_open_program(program["id"])
    assert wired["program"]["status"] == "OPEN"
    assert wired["program"]["holding_account_id"] == wired["holding_account"]["id"]


def test_program_archive_blocked_with_live_subscriptions(api):
    """PRD §3.5: "Archiving moves an `OPEN` program to the terminal
    `ARCHIVED` state and is refused with
    `ERR_PROGRAM_HAS_ACTIVE_SUBSCRIPTIONS` while any subscription of the
    program remains in `PENDING`, `ACTIVE`, `WAITLISTED`, or `SUSPENDED`."

    Design: Corner/state_machines/program_archive_blocked_with_live_subscriptions
    """
    setup = setup_open_program()
    program = setup["program"]
    sub = create_subscription(program["id"], allocation_kw=100)
    activate_subscription(sub["id"])

    resp = api.archive_program(program["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_PROGRAM_HAS_ACTIVE_SUBSCRIPTIONS, expected_status=409)
    assert get_program(program["id"])["status"] == "OPEN"

    terminate_subscription(sub["id"])
    archived = validate_success(api.archive_program(program["id"], ADMIN))
    assert archived["status"] == "ARCHIVED"


# ---------------------------------------------------------------------------
# Subscription creation requires an OPEN program
# ---------------------------------------------------------------------------

def test_subscription_create_on_draft_program_rejected(api):
    """PRD §3.5: "The program must be `OPEN`, else `ERR_PROGRAM_NOT_OPEN`".

    Design: Difficulty/cross_entity_state_dependency/subscription_create_requires_program_open
    """
    program = create_program()  # DRAFT, never opened
    resp = api.create_subscription(
        create_subscription_payload(
            program_id=program["id"],
            allocation_kw=600,
            expected_program_version=program["version"],
        ),
        PM,
    )
    validate_error(resp, ApiErrorId.ERR_PROGRAM_NOT_OPEN, expected_status=409)


def test_subscription_create_on_archived_program_rejected(api):
    """PRD §3.5: "The program must be `OPEN`, else `ERR_PROGRAM_NOT_OPEN`" —
    an ARCHIVED program is not OPEN, so enrollment fails there too.

    Design: Difficulty/cross_entity_state_dependency/subscription_create_requires_program_open
    """
    setup = setup_open_program()
    program = setup["program"]
    archived = validate_success(api.archive_program(program["id"], ADMIN))
    assert archived["status"] == "ARCHIVED"

    resp = api.create_subscription(
        create_subscription_payload(
            program_id=program["id"],
            allocation_kw=100,
            expected_program_version=get_program(program["id"])["version"],
        ),
        PM,
    )
    validate_error(resp, ApiErrorId.ERR_PROGRAM_NOT_OPEN, expected_status=409)


# ---------------------------------------------------------------------------
# Activation capacity branch and join
# ---------------------------------------------------------------------------

def test_activate_with_insufficient_capacity_parks_in_waitlist(api):
    """PRD §3.5: "If capacity is insufficient, the outcome is not an error:
    the subscription parks, moving from `PENDING` to `WAITLISTED` with
    `waitlisted_at` stamped, and only the subscription's `version`
    increments."

    Design: Difficulty/non_linear_state_machine/subscription_capacity_branch_and_join
    """
    setup = setup_open_program(capacity_cap_kw=1000)
    program = setup["program"]
    sa = create_subscription(program["id"], allocation_kw=600, utility_account_no="U-A")
    activate_subscription(sa["id"])

    sc = create_subscription(program["id"], allocation_kw=500, utility_account_no="U-C")
    parked = activate_subscription(sc["id"])  # 600 + 500 > 1000
    assert parked["status"] == "WAITLISTED", "overflow parks rather than erroring"
    assert parked["waitlisted_at"] is not None
    assert parked["activated_at"] is None

    assert get_program(program["id"])["committed_capacity_kw"] == 600, (
        "a parked subscription does not consume capacity"
    )


def test_termination_releases_capacity_and_promotes_waitlisted(api):
    """PRD §3.5: "a subscription terminating from `ACTIVE` or `SUSPENDED`
    releases its allocation — `committed_capacity_kw` falls by the
    `allocation_kw` — which in turn triggers the waitlist promotion scan on
    the program" and "A candidate whose `allocation_kw` fits within the
    remaining capacity at its turn moves to `ACTIVE`, with `activated_at`
    stamped, `waitlisted_at` cleared".

    Design: Difficulty/non_linear_state_machine/subscription_capacity_branch_and_join
    """
    setup = setup_open_program(capacity_cap_kw=1000)
    program = setup["program"]
    sa = create_subscription(program["id"], allocation_kw=600, utility_account_no="U-A")
    activate_subscription(sa["id"])
    sc = create_subscription(program["id"], allocation_kw=500, utility_account_no="U-C")
    activate_subscription(sc["id"])
    assert get_subscription(sc["id"])["status"] == "WAITLISTED"

    terminate_subscription(sa["id"])

    promoted = get_subscription(sc["id"])
    assert promoted["status"] == "ACTIVE", "the promotion scan joins the waitlist branch"
    assert promoted["activated_at"] is not None
    assert promoted["waitlisted_at"] is None
    assert get_program(program["id"])["committed_capacity_kw"] == 500


# ---------------------------------------------------------------------------
# Exact-fit capacity boundary
# ---------------------------------------------------------------------------

def test_activate_exact_capacity_fit_admitted(api):
    """PRD §3.5: "If the program's `committed_capacity_kw` — the summed
    `allocation_kw` over its `ACTIVE` subscriptions — plus the new
    `allocation_kw` fits within `capacity_cap_kw`, the subscription moves to
    `ACTIVE`" — 600 + 400 == 1000 fits exactly (the boundary is inclusive).

    Design: Difficulty/boundary_precision_check/capacity_exact_fit_boundary
    """
    setup = setup_open_program(capacity_cap_kw=1000)
    program = setup["program"]
    sa = create_subscription(program["id"], allocation_kw=600, utility_account_no="U-A")
    activate_subscription(sa["id"])

    sb = create_subscription(program["id"], allocation_kw=400, utility_account_no="U-B")
    activated = activate_subscription(sb["id"])
    assert activated["status"] == "ACTIVE", "600 + 400 == 1000 fits within the cap"
    assert get_program(program["id"])["committed_capacity_kw"] == 1000


def test_activate_one_kw_over_capacity_parks_waitlist(api):
    """PRD §3.5: "If capacity is insufficient, the outcome is not an error:
    the subscription parks, moving from `PENDING` to `WAITLISTED`" — with
    1000 committed of 1000, even a 1-kW request overflows.

    Design: Difficulty/boundary_precision_check/capacity_exact_fit_boundary
    """
    setup = setup_open_program(capacity_cap_kw=1000)
    program = setup["program"]
    sa = create_subscription(program["id"], allocation_kw=600, utility_account_no="U-A")
    activate_subscription(sa["id"])
    sb = create_subscription(program["id"], allocation_kw=400, utility_account_no="U-B")
    activate_subscription(sb["id"])
    assert get_program(program["id"])["committed_capacity_kw"] == 1000

    sc = create_subscription(program["id"], allocation_kw=1, utility_account_no="U-C")
    parked = activate_subscription(sc["id"])
    assert parked["status"] == "WAITLISTED", "1000 + 1 > 1000 parks, not errors"
    assert parked["waitlisted_at"] is not None


# ---------------------------------------------------------------------------
# Capacity conservation across terminate/promote rounds
# ---------------------------------------------------------------------------

def _three_sub_setup_600_400_500():
    """Cap 1000: A 600 ACTIVE, B 400 ACTIVE (committed 1000), C 500
    WAITLISTED."""
    setup = setup_open_program(capacity_cap_kw=1000)
    program = setup["program"]
    sa = create_subscription(program["id"], allocation_kw=600, utility_account_no="U-A")
    activate_subscription(sa["id"])
    sb = create_subscription(program["id"], allocation_kw=400, utility_account_no="U-B")
    activate_subscription(sb["id"])
    sc = create_subscription(program["id"], allocation_kw=500, utility_account_no="U-C")
    activate_subscription(sc["id"])  # 1000 + 500 > 1000 -> WAITLISTED
    return program, sa, sb, sc


def test_capacity_released_by_termination_promotes_and_recomputes(api):
    """PRD §3.5: "The scan computes the remaining capacity as
    `capacity_cap_kw` minus the summed `allocation_kw` of `ACTIVE`
    subscriptions" — terminating A (600) frees room for C (500): committed
    goes 1000 -> 900 (B 400 + C 500).

    Design: Difficulty/compensating_invariant/capacity_conservation_round_trip
    """
    program, sa, sb, sc = _three_sub_setup_600_400_500()
    assert get_program(program["id"])["committed_capacity_kw"] == 1000
    assert get_subscription(sc["id"])["status"] == "WAITLISTED"

    terminate_subscription(sa["id"])

    assert get_subscription(sc["id"])["status"] == "ACTIVE", "500 fits the released 600"
    committed = get_program(program["id"])["committed_capacity_kw"]
    assert committed == 900, f"400 (B) + 500 (promoted C) == 900, got {committed}"


def test_committed_capacity_tracks_active_allocations_each_round(api):
    """PRD §3.5: "`committed_capacity_kw` — the summed `allocation_kw` over
    its `ACTIVE` subscriptions" — after every terminate/promotion round it
    equals exactly the ACTIVE allocations and never exceeds the cap.

    Design: Difficulty/compensating_invariant/capacity_conservation_round_trip
    """
    program, sa, sb, sc = _three_sub_setup_600_400_500()
    terminate_subscription(sa["id"])
    terminate_subscription(sb["id"])

    final = get_program(program["id"])
    assert final["committed_capacity_kw"] == 500, "C alone remains ACTIVE"
    assert final["committed_capacity_kw"] <= final["capacity_cap_kw"], (
        "the capacity invariant holds at every step"
    )


# ---------------------------------------------------------------------------
# Terminate -> release -> promotion-scan cascade with skip-and-continue
# ---------------------------------------------------------------------------

def test_terminate_promotes_fitting_waitlisted_subscription(api):
    """PRD §3.5: "Parked subscriptions are promoted by the waitlist promotion
    scan, which runs automatically after any capacity release — a
    subscription terminating from `ACTIVE` or `SUSPENDED`" and "walks the
    program's `WAITLISTED` subscriptions ordered by `waitlisted_at`
    ascending".

    Design: Difficulty/transitive_cascade/subscription_terminate_promotion_cascade
    """
    setup = setup_open_program(capacity_cap_kw=1000)
    program = setup["program"]
    sa = create_subscription(program["id"], allocation_kw=600, utility_account_no="U-A")
    activate_subscription(sa["id"])
    sc = create_subscription(program["id"], allocation_kw=500, utility_account_no="U-C")
    activate_subscription(sc["id"])  # WAITLISTED (1100 > 1000)
    set_clock("2026-08-01T01:00:00Z")
    sd = create_subscription(program["id"], allocation_kw=900, utility_account_no="U-D")
    activate_subscription(sd["id"])  # WAITLISTED (1500 > 1000)
    assert get_subscription(sc["id"])["status"] == "WAITLISTED"
    assert get_subscription(sd["id"])["status"] == "WAITLISTED"

    terminate_subscription(sa["id"])  # releases 600: remaining 1000

    promoted = get_subscription(sc["id"])
    assert promoted["status"] == "ACTIVE", "C (500) fits at its turn"
    assert promoted["activated_at"] is not None
    assert get_program(program["id"])["committed_capacity_kw"] == 500


def test_terminate_skips_oversized_waitlist_entry_without_blocking(api):
    """PRD §3.5: "A candidate that does not fit stays `WAITLISTED` and the
    scan continues past it — skip-and-continue, with no head-of-line
    blocking".

    Design: Difficulty/transitive_cascade/subscription_terminate_promotion_cascade
    """
    setup = setup_open_program(capacity_cap_kw=1000)
    program = setup["program"]
    sa = create_subscription(program["id"], allocation_kw=600, utility_account_no="U-A")
    activate_subscription(sa["id"])
    sc = create_subscription(program["id"], allocation_kw=500, utility_account_no="U-C")
    activate_subscription(sc["id"])
    set_clock("2026-08-01T01:00:00Z")
    sd = create_subscription(program["id"], allocation_kw=900, utility_account_no="U-D")
    activate_subscription(sd["id"])

    terminate_subscription(sa["id"])

    # After C's promotion 500 kW remain; D (900) does not fit and is skipped
    # without erroring — the cascade terminates with D still parked.
    assert get_subscription(sd["id"])["status"] == "WAITLISTED", (
        "900 > 500 remaining after C's promotion: D is skipped"
    )
    assert get_subscription(sc["id"])["status"] == "ACTIVE"
    assert get_program(program["id"])["committed_capacity_kw"] == 500


def test_waitlist_skip_and_continue_selector(api):
    """PRD §3.5: "walks the program's `WAITLISTED` subscriptions ordered by
    `waitlisted_at` ascending with `created_at` ascending as tie-break. A
    candidate whose `allocation_kw` fits within the remaining capacity at its
    turn moves to `ACTIVE` ... A candidate that does not fit stays
    `WAITLISTED` and the scan continues past it — skip-and-continue, with no
    head-of-line blocking".

    Setup note: an extra always-active 40-kW subscription keeps the program
    full so both candidates genuinely park (a lone 60-kW active subscription
    would let the 40-kW candidate activate outright at 60+40=100 <= 100).

    Design: Corner/state_machines/waitlist_skip_and_continue_selector
    """
    setup = setup_open_program(capacity_cap_kw=100)
    program = setup["program"]
    sa = create_subscription(program["id"], allocation_kw=60, utility_account_no="U-A")
    activate_subscription(sa["id"])
    sb = create_subscription(program["id"], allocation_kw=40, utility_account_no="U-B")
    activate_subscription(sb["id"])  # 60 + 40 == 100: exact fit, program full
    assert get_program(program["id"])["committed_capacity_kw"] == 100

    w1 = create_subscription(program["id"], allocation_kw=70, utility_account_no="U-W1")
    activate_subscription(w1["id"])  # 100 + 70 > 100 -> WAITLISTED (earlier)
    set_clock("2026-08-01T01:00:00Z")
    w2 = create_subscription(program["id"], allocation_kw=40, utility_account_no="U-W2")
    activate_subscription(w2["id"])  # 100 + 40 > 100 -> WAITLISTED (later)
    assert get_subscription(w1["id"])["status"] == "WAITLISTED"
    assert get_subscription(w2["id"])["status"] == "WAITLISTED"

    terminate_subscription(sa["id"])  # releases 60: remaining = 100 - 40 = 60

    assert get_subscription(w1["id"])["status"] == "WAITLISTED", (
        "70 > 60 at its turn: the head entry is skipped"
    )
    promoted = get_subscription(w2["id"])
    assert promoted["status"] == "ACTIVE", "40 <= 60: the later fitting entry promotes"
    assert promoted["activated_at"] is not None
    assert promoted["waitlisted_at"] is None
    assert get_program(program["id"])["committed_capacity_kw"] == 80, (
        "B (40) + promoted W2 (40)"
    )


# ---------------------------------------------------------------------------
# Creation-time guards and uniqueness
# ---------------------------------------------------------------------------

def test_allocation_above_cap_and_market_class_mismatch(api):
    """PRD §3.5: "an `allocation_kw` larger than the program's entire
    `capacity_cap_kw` can never fit and is rejected outright with
    `ERR_ALLOCATION_EXCEEDS_CAP`."
    PRD §3.5: "its `market_class` must be `VOLUNTARY` — subscriptions into a
    `COMPLIANCE`-class program are rejected with `ERR_MARKET_CLASS_MISMATCH`."

    Design: Corner/validations/allocation_above_cap_and_market_class_mismatch
    """
    p1 = setup_open_program(capacity_cap_kw=1000)["program"]
    p2 = setup_open_program(
        name="RPS Pool", market_class="COMPLIANCE", capacity_cap_kw=5000,
        annual_claim_cap_mwh=100000,
    )["program"]

    resp_cap = api.create_subscription(
        create_subscription_payload(
            program_id=p1["id"], allocation_kw=1001, utility_account_no="U-BIG",
            expected_program_version=get_program(p1["id"])["version"],
        ),
        PM,
    )
    validate_error(resp_cap, ApiErrorId.ERR_ALLOCATION_EXCEEDS_CAP, expected_status=422)

    resp_class = api.create_subscription(
        create_subscription_payload(
            program_id=p2["id"], allocation_kw=100, utility_account_no="U-WC",
            expected_program_version=get_program(p2["id"])["version"],
        ),
        PM,
    )
    validate_error(resp_class, ApiErrorId.ERR_MARKET_CLASS_MISMATCH, expected_status=422)


def test_duplicate_utility_account_blocked_until_terminated(api):
    """PRD §3.5: "The `utility_account_no` must be unique among the program's
    non-`TERMINATED` subscriptions, else `ERR_DUPLICATE_UTILITY_ACCOUNT`."

    Design: Corner/validations/duplicate_utility_account_blocked_until_terminated
    """
    setup = setup_open_program()
    program = setup["program"]
    s1 = create_subscription(program["id"], allocation_kw=100, utility_account_no="U-1")
    activate_subscription(s1["id"])

    resp = api.create_subscription(
        create_subscription_payload(
            program_id=program["id"], allocation_kw=50, utility_account_no="U-1",
            customer_name="Customer B",
            expected_program_version=get_program(program["id"])["version"],
        ),
        PM,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_UTILITY_ACCOUNT, expected_status=409)

    terminate_subscription(s1["id"])

    s2 = create_subscription(
        program["id"], allocation_kw=50, utility_account_no="U-1",
        customer_name="Customer B",
    )
    assert_subscription(s2)
    assert s2["utility_account_no"] == "U-1", (
        "a TERMINATED subscription no longer blocks its utility account number"
    )
    assert s2["status"] == "PENDING"


# ---------------------------------------------------------------------------
# Optimistic concurrency on program writes
# ---------------------------------------------------------------------------

def test_occ_subscription_create_stale_version(api):
    """PRD §2.7: "Enrolling a customer subscription requires
    `expected_program_version`, matched against the target program's current
    `version`. Because enrolling a subscription, activating one, terminating
    one, or amending the program all advance the program's `version`, this
    guard prevents a writer from enrolling against a capacity view it has not
    observed." and "a value that does not equal the parent entity's current
    `version` is rejected with `ERR_STALE_VERSION` (HTTP 412), and no part of
    the write is applied."

    Design: Corner/cross_cutting_complexity_layers/occ_subscription_create_stale_version
    """
    setup = setup_open_program()
    observed = get_program(setup["program"]["id"])["version"]

    first = create_subscription(
        setup["program"]["id"], allocation_kw=100, utility_account_no="U-A",
        expected_program_version=observed,
    )
    assert first["status"] == "PENDING"
    assert get_program(setup["program"]["id"])["version"] == observed + 1, (
        "enrollment itself advances the program version (PRD §3.5)"
    )

    stale = api.create_subscription(
        create_subscription_payload(
            program_id=setup["program"]["id"], allocation_kw=100,
            utility_account_no="U-B", expected_program_version=observed,
        ),
        PM,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION, expected_status=412)


def test_occ_program_patch_stale_version(api):
    """PRD §2.7: "Amending a program's configuration requires
    `expected_program_version`, matched against that program's current
    `version`."
    PRD §3.5: "the write is guarded by `expected_program_version` per §2.7
    and increments the program's `version` by one".

    Design: Corner/cross_cutting_complexity_layers/occ_program_patch_stale_version
    """
    program = create_program()
    observed = program["version"]
    holding = create_account(
        account_type="PROGRAM", owner_name="SunTariff Holding", program_id=program["id"]
    )

    first = patch_program(
        program["id"], expected_program_version=observed,
        holding_account_id=holding["id"],
    )
    assert first["holding_account_id"] == holding["id"]
    assert first["version"] == observed + 1

    stale = api.patch_program(
        program["id"],
        {"expected_program_version": observed, "capacity_cap_kw": 2000},
        ADMIN,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION, expected_status=412)
    assert get_program(program["id"])["capacity_cap_kw"] == 1000


# ---------------------------------------------------------------------------
# Role boundaries
# ---------------------------------------------------------------------------

def test_auditor_is_read_only_outside_report_decisions(api, auditor_headers):
    """PRD §2.1: "A request whose role is not permitted for the target
    endpoint — or that fails an ownership, purpose, or scope match described
    below — is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §2.1: "`Auditor` — independent claims auditor who may never decide a
    report submitted by the same user" — the endpoint table (§4) grants
    program creation to RegistryAdmin only.

    Design: Corner/rbac/auditor_is_read_only_outside_report_decisions
    """
    resp = api.create_program(create_program_payload(), auditor_headers)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, expected_status=403)
