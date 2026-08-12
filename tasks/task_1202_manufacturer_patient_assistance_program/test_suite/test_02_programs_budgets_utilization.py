"""Programs, budget periods, OCC updates, utilization pair, and the conserved
budget ledger (PRD §2.8, §2.11, §3.1)."""
from test_helpers import (
    ApiErrorId,
    api_client,
    assert_program,
    assert_program_budget_conserved,
    create_budget_period_payload,
    create_program_payload,
    fixtures as fx,
    make_case_worker_headers,
    validate_error,
    validate_success,
)


def test_program_creation_computed_defaults():
    """PRD §3.1: "A newly created program starts with `posture` `OPEN`, all
    totals at zero, and `version` 1."

    Design: Corner/entities/program_creation_computed_defaults
    """
    resp = api_client.create_program(create_program_payload(), fx.ADMIN)
    data = validate_success(resp, expected_status=201)
    assert_program(data)
    assert data["posture"] == "OPEN"
    assert data["total_committed_cents"] == 0
    assert data["total_disbursed_cents"] == 0
    assert data["total_allocated_cents"] == 0
    assert data["version"] == 1


def test_program_update_stale_version_rejected():
    """PRD §2.8: "updating a program's configuration requires the request to
    carry `expected_program_version` holding the client's last observed
    `version` of that program. If the value does not match the program's current
    `version` — because another accepted update has advanced it since the client
    last read the record — the update is rejected with `ERR_STALE_VERSION`
    (HTTP 412), preventing the stale writer from applying a configuration delta
    computed against a superseded baseline."

    Design: Corner/complexity_layers/occ_program_config_stale_update_returns_412
    """
    program = fx.create_program_record()
    first = validate_success(api_client.update_program(
        program["id"], {"expected_program_version": program["version"],
                        "max_units_per_shipment": 25}, fx.ADMIN))
    assert first["version"] == program["version"] + 1
    assert first["max_units_per_shipment"] == 25

    stale = api_client.update_program(
        program["id"], {"expected_program_version": program["version"],
                        "max_units_per_shipment": 20}, fx.ADMIN)
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

    current = validate_success(api_client.get_program(program["id"], fx.ADMIN))
    assert current["max_units_per_shipment"] == 25, "stale update must not apply"
    assert current["version"] == program["version"] + 1


def test_shared_single_day_is_overlap():
    """PRD §2.5: "two periods that merely touch at a single shared calendar day
    are an overlap, while periods whose boundary dates are exactly one day apart
    (one ends the day before the other begins) are disjoint and allowed."
    PRD §3.1: "Creating a period whose closed interval intersects any existing
    period of the same program is rejected with `ERR_BUDGET_PERIOD_OVERLAP`"

    Design: Difficulty/resource_temporal_overlap/budget_period_closed_interval_adjacency
    """
    ctx = fx.setup_program_with_period(create_period=True, allocated_cents=500000,
                                       period_start="2026-01-01", period_end="2026-06-30")
    prog_id = ctx["program"]["id"]
    resp = api_client.create_budget_period(
        create_budget_period_payload(prog_id, period_start="2026-06-30",
                                     period_end="2026-12-31", allocated_cents=500000),
        fx.ADMIN)
    validate_error(resp, ApiErrorId.ERR_BUDGET_PERIOD_OVERLAP, expected_status=409)


def test_one_day_adjacency_is_disjoint():
    """PRD §2.5: "two periods that merely touch at a single shared calendar day
    are an overlap, while periods whose boundary dates are exactly one day apart
    (one ends the day before the other begins) are disjoint and allowed."
    PRD §2.11: "Its `total_allocated_cents` is the sum of `allocated_cents` over
    all of its budget periods regardless of period status"

    Design: Difficulty/resource_temporal_overlap/budget_period_closed_interval_adjacency
    """
    ctx = fx.setup_program_with_period(create_period=True, allocated_cents=500000,
                                       period_start="2026-01-01", period_end="2026-06-30")
    prog_id = ctx["program"]["id"]
    created = validate_success(api_client.create_budget_period(
        create_budget_period_payload(prog_id, period_start="2026-07-01",
                                     period_end="2026-12-31", allocated_cents=500000),
        fx.ADMIN), expected_status=201)
    assert created["period_start"] == "2026-07-01"

    program = validate_success(api_client.get_program(prog_id, fx.ADMIN))
    assert program["total_allocated_cents"] == 1000000, (
        "two accepted 500000 periods must sum to 1000000")


def test_committed_basis_jumps_on_approval():
    """PRD §2.11: "The two bases deliberately diverge: immediately after an
    approval with zero shipments, the committed basis jumps while the disbursed
    basis still reads `'0.00'`." and "The program's `posture` is derived from the
    committed basis with inclusive boundaries — a committed basis of exactly
    `'100.00'` or more yields `EXHAUSTED`; a committed basis of exactly `'90.00'`
    or more but under 100 yields `RESTRICTED`; anything lower yields `OPEN`."

    Design: Difficulty/dual_variant_calc/utilization_dual_basis_posture_divergence
    """
    ctx = fx.setup_approved_enrollment()
    utilization = fx.get_utilization(ctx["program"]["id"])
    assert utilization["committed_cents"] == 900000
    assert utilization["utilization_committed_basis_pct"] == "90.00", (
        "committed 900000 + disbursed 0 over allocated 1000000 reads 90.00")
    assert utilization["posture"] == "RESTRICTED", (
        "posture derives from the committed basis only")
    assert_program_budget_conserved(utilization)


def test_disbursed_basis_zero_until_delivery():
    """PRD §2.11: "The two bases deliberately diverge: immediately after an
    approval with zero shipments, the committed basis jumps while the disbursed
    basis still reads `'0.00'`." PRD §3.3 pins the cap: "the base cap is the
    smaller of `max_annual_benefit_cents` and that product axis"

    Design: Difficulty/dual_variant_calc/utilization_dual_basis_posture_divergence
    """
    ctx = fx.setup_approved_enrollment()
    utilization = fx.get_utilization(ctx["program"]["id"])
    assert utilization["disbursed_cents"] == 0
    assert utilization["utilization_disbursed_basis_pct"] == "0.00", (
        "no deliveries yet — the chronological basis reads 0.00 on identical data")
    enrollment = fx.refresh_enrollment(ctx["enrollment"]["id"])
    assert enrollment["benefit_cap_cents"] == 900000, (
        "min(900000 annual cap, 100 units x 10000 unit cents) = 900000")


def test_committed_basis_exactly_ninety_is_restricted():
    """PRD §2.11: "The program's `posture` is derived from the committed basis
    with inclusive boundaries — a committed basis of exactly `'100.00'` or more
    yields `EXHAUSTED`; a committed basis of exactly `'90.00'` or more but under
    100 yields `RESTRICTED`; anything lower yields `OPEN`."

    Design: Difficulty/boundary_precision_check/utilization_exactly_90_inclusive_restricted
    """
    ctx = fx.setup_second_patient_application(first_allocated_cents=1000000)
    utilization = fx.get_utilization(ctx["program"]["id"])
    assert utilization["utilization_committed_basis_pct"] == "90.00", (
        "exactly 900000 of 1000000 committed")
    assert utilization["posture"] == "RESTRICTED", (
        "the 90.00 boundary is inclusive for RESTRICTED")


def test_fresh_approval_rejected_at_ninety_boundary():
    """PRD §3.3: "within the fiscal gates the order is pinned: posture
    `EXHAUSTED` blocks every approval with `ERR_PROGRAM_BUDGET_EXHAUSTED`
    (HTTP 402); posture `RESTRICTED` blocks fresh approvals with
    `ERR_PROGRAM_RESTRICTED` (HTTP 403) but renewals are exempt from this gate"

    Design: Difficulty/boundary_precision_check/utilization_exactly_90_inclusive_restricted
    """
    ctx = fx.setup_second_patient_application(first_allocated_cents=1000000)
    resp = api_client.decide_application(
        ctx["application_b"]["id"], {"decision": "APPROVED"},
        make_case_worker_headers(ctx["reviewer"]))
    validate_error(resp, ApiErrorId.ERR_PROGRAM_RESTRICTED, expected_status=403)


def test_approval_commits_full_cap():
    """PRD §3.3: "the containing period's `committed_cents` increases by the
    benefit cap, program totals and posture are recomputed per §2.11"

    Design: Difficulty/compensating_invariant/budget_commit_terminate_conservation
    """
    ctx = fx.setup_approved_enrollment()
    utilization = fx.get_utilization(ctx["program"]["id"])
    assert utilization["committed_cents"] == 900000, (
        "the forward action commits the full 900000 benefit cap")
    assert utilization["disbursed_cents"] == 0
    assert utilization["posture"] == "RESTRICTED"
    assert_program_budget_conserved(utilization)


def test_termination_releases_commitment_exactly():
    """PRD §2.11: "At all times, the allocated total equals committed plus
    disbursed plus unallocated available funds — commitment releases (on
    termination, expiry, or renewal closure) and disbursement confirmations (on
    delivery) move money between those buckets but never create or destroy it."
    PRD §3.5: "the remaining commitment — `benefit_cap_cents` minus
    `disbursed_cents` — is released from the program's `total_committed_cents`
    and the commitment period's `committed_cents`, with posture recomputed."

    Design: Difficulty/compensating_invariant/budget_commit_terminate_conservation
    """
    ctx = fx.setup_approved_enrollment()
    terminated = validate_success(api_client.terminate_enrollment(
        ctx["enrollment"]["id"], {"termination_reason": "patient moved out of state"}, fx.CW))
    assert terminated["status"] == "TERMINATED"

    utilization = fx.get_utilization(ctx["program"]["id"])
    assert utilization["committed_cents"] == 0, "compensating release returns committed to 0"
    assert utilization["disbursed_cents"] == 0
    assert utilization["allocated_cents"] == 1000000
    assert utilization["posture"] == "OPEN", "posture recomputes back to OPEN"
    assert_program_budget_conserved(utilization)


def test_utilization_read_matches_program_fields():
    """PRD §3.7: "the enrollment's `disbursed_cents` increases by the shipment's
    `value_cents`, the commitment budget period's `disbursed_cents` increases by
    the same amount, and program totals and posture are recomputed — because
    committed totals are derived as cap minus disbursed over open enrollments,
    delivery shifts value from committed to disbursed with no separate release
    step." PRD §4: GET /pap/programs/{id} returns the program with "computed
    posture/totals current as of read".

    Design: Corner/endpoints/utilization_computed_read_matches_program_fields
    """
    ctx = fx.setup_delivered_shipment(quantity_units=10, unit_cost="100.0000",
                                      lot_quantity=100, lot_number="LOT-UTIL",
                                      idempotency_key="util-1")

    program = validate_success(api_client.get_program(ctx["program"]["id"], fx.CW))
    assert program["total_committed_cents"] == 800000, (
        "cap 900000 minus delivered 100000 (10 x 100.0000) remains committed")
    assert program["total_disbursed_cents"] == 100000

    utilization = fx.get_utilization(ctx["program"]["id"])
    assert utilization["committed_cents"] == 800000, "utilization read agrees with the program read"
    assert utilization["disbursed_cents"] == 100000
    assert utilization["utilization_committed_basis_pct"] == "90.00"
    assert utilization["posture"] == "RESTRICTED"
    assert program["posture"] == utilization["posture"], "both reads report the same posture"
