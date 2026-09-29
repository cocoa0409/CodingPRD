"""Cyclic and forked state machines, parallel lease dimensions, and the
multi-hop cascades that one trigger drives through occupancy, conditions,
remedy posture, estoppel certificates and center posture.
"""
from test_helpers import (
    add_clause,
    add_condition,
    adjudicate_dispute,
    approve_election,
    assert_cents,
    assert_center_quantities,
    assert_lease_dimensions,
    assert_pct,
    create_center,
    create_tenant,
    draft_lease,
    elect_remedy,
    escalate_notice,
    execute_lease,
    fetch_center,
    fetch_certificate,
    fetch_condition,
    fetch_dispute,
    fetch_election,
    fetch_lease,
    fetch_notice,
    file_dispute,
    go_dark,
    issue_notice,
    open_lease,
    request_certificate,
    set_clock,
    sign_certificate,
)

# The instant every scenario in this module starts from (PRD §2.4).
START_CLOCK = "2026-08-01T00:00:00Z"

# One center of 300,000 sqft with two anchor boxes and three inline suites.
# 120000 + 100000 + 2000 + 3000 + 30000 = 255000 sqft, i.e. 85.00 pct open
# occupancy once every suite is open (PRD §2.5).
SUITE_SPECS = (
    ("A1", "Boxmart Retail Inc", "legal@boxmart.example", "DISCOUNT_DEPT", 120000,
     "ANCHOR_BOX", 6000000, True),
    ("A2", "Grocerway Foods LLC", "legal@grocerway.example", "GROCERY", 100000,
     "ANCHOR_BOX", 4000000, True),
    ("I1", "Bean Theory Coffee LLC", "legal@beantheory.example", "COFFEE", 2000,
     "INLINE", 1000000, False),
    ("I2", "Margin Books LLC", "legal@marginbooks.example", "BOOKS", 3000,
     "INLINE", 1200000, False),
    ("I3", "Pulse Fitness Group", "legal@pulsefitness.example", "FITNESS", 30000,
     "INLINE", 1500000, True),
)


def _build_open_center(api):
    """Stand up the five-suite center, every lease drafted, executed and open.

    Returns a dict of ``center_id`` plus the ``leases`` and ``tenants`` ids keyed
    by suite code (PRD §3.1, §3.2, §3.3).
    """
    set_clock(api, START_CLOCK)
    center = create_center(
        api,
        name="Northgate Crossing",
        total_gla_sqft=300000,
        occupancy_grace_days=30,
    )
    leases = {}
    tenants = {}
    for (
        suite_code,
        legal_name,
        notice_email,
        use_code,
        gla_sqft,
        parcel_kind,
        rent_cents,
        national,
    ) in SUITE_SPECS:
        tenant = create_tenant(
            api,
            legal_name=legal_name,
            notice_email=notice_email,
            primary_use_code=use_code,
            is_national_chain=national,
        )
        lease = draft_lease(
            api,
            center["id"],
            tenant["id"],
            suite_code=suite_code,
            gla_sqft=gla_sqft,
            parcel_kind=parcel_kind,
            primary_use_code=use_code,
            base_rent_monthly_cents=rent_cents,
            commencement_date="2026-01-01",
            expiration_date="2036-12-31",
        )
        tenants[suite_code] = tenant["id"]
        leases[suite_code] = lease["id"]
    for suite_code, *_ in SUITE_SPECS:
        execute_lease(api, leases[suite_code])
    for suite_code, *_ in SUITE_SPECS:
        open_lease(api, leases[suite_code])
    return {"center_id": center["id"], "leases": leases, "tenants": tenants}


# --------------------------------------------------------------------------
# A denied dispute re-arms the notice it came from (PRD §3.6)
# --------------------------------------------------------------------------
def _build_disputed_notice(api):
    """A COFFEE exclusive on I1, an I3 notice citing it, and a pending dispute."""
    scenario = _build_open_center(api)
    clause = add_clause(
        api,
        scenario["leases"]["I1"],
        protected_use_codes=["COFFEE"],
        exclusivity_scope="CENTER_WIDE",
        effective_from_date="2026-01-01",
        effective_through_date="2036-12-31",
        gla_carve_out_sqft=0,
        incidental_sales_pct_cap=0.0,
    )
    notice = issue_notice(
        api,
        scenario["leases"]["I3"],
        notice_kind="EXCLUSIVE_USE",
        clause_id=clause["id"],
        narrative="Espresso bar operating inside the fitness premises.",
        cure_period_days=30,
    )
    dispute = file_dispute(
        api,
        notice["id"],
        scenario["tenants"]["I3"],
        grounds_code="CARVE_OUT_APPLIES",
        narrative="Coffee service is ancillary to the member lounge and inside the carve-out.",
        cure_extension_days=15,
    )
    set_clock(api, "2026-08-10T00:00:00Z")
    scenario["clause_id"] = clause["id"]
    scenario["notice_id"] = notice["id"]
    scenario["dispute_id"] = dispute["id"]
    return scenario


def test_denied_dispute_reaches_terminal_denied_with_adjudication_stamps(api):
    """Denying a dispute drives it to DENIED and stamps the adjudicating officer and instant.

    PRD: "Either outcome stamps `adjudicated_by_user_id` from `X-User-ID` and `adjudicated_at` from the clock."

    Design: Difficulty/non_linear_state_machine/notice_dispute_denied_returns_to_issued_and_restarts_cure
    """
    scenario = _build_disputed_notice(api)

    adjudicate_dispute(api, scenario["dispute_id"], "DENIED")

    dispute = fetch_dispute(api, scenario["dispute_id"])
    assert dispute["status"] == "DENIED"
    assert dispute["adjudicated_by_user_id"] == "co-adjudicator-2"
    assert dispute["adjudicated_at"].startswith("2026-08-10"), (
        f"adjudicated_at should be the adjudication instant, got {dispute['adjudicated_at']}"
    )


def test_denied_dispute_returns_notice_to_issued_and_restarts_the_cure_clock(api):
    """The notice cycles DISPUTED back to ISSUED, counting the restart and re-basing the deadline.

    PRD: "A **denied** dispute moves to the terminal `DENIED` and re-arms the notice, which is the system's one genuinely cyclic path: the notice returns `DISPUTED → ISSUED`, `cure_restart_count` increments by one, and `cure_deadline_at` is re-armed to the dispute's `adjudicated_at` plus the sum of the notice's `cure_period_days` and the dispute's `cure_extension_days`, expressed in days."

    Design: Difficulty/non_linear_state_machine/notice_dispute_denied_returns_to_issued_and_restarts_cure
    """
    scenario = _build_disputed_notice(api)

    adjudicate_dispute(api, scenario["dispute_id"], "DENIED")

    notice = fetch_notice(api, scenario["notice_id"])
    assert notice["status"] == "ISSUED"
    assert notice["cure_restart_count"] == 1
    # 2026-08-10 adjudication + 30 cure days + 15 granted extension days.
    assert notice["cure_deadline_at"].startswith("2026-09-24"), (
        f"cure_deadline_at should be re-armed to 2026-09-24, got {notice['cure_deadline_at']}"
    )


def test_notice_back_in_issued_still_reads_as_under_notice_on_lease_and_center(api):
    """A re-armed ISSUED notice keeps the lease UNDER_NOTICE and the center on WATCH.

    PRD: "A third derived field, `use_compliance_status`, tracks enforcement rather than either dimension: it reads `CLEAR` when no notice against the lease is `ISSUED`, `DISPUTED`, or `ESCALATED`; `UNDER_NOTICE` when at least one is `ISSUED` or `DISPUTED`; and `IN_VIOLATION` when at least one is `ESCALATED`."

    Design: Difficulty/non_linear_state_machine/notice_dispute_denied_returns_to_issued_and_restarts_cure
    """
    scenario = _build_disputed_notice(api)

    adjudicate_dispute(api, scenario["dispute_id"], "DENIED")

    violating_lease = fetch_lease(api, scenario["leases"]["I3"])
    assert_lease_dimensions(violating_lease, use_compliance_status="UNDER_NOTICE")
    center = fetch_center(api, scenario["center_id"])
    assert_center_quantities(
        center, open_violation_count=1, compliance_posture="WATCH"
    )


# --------------------------------------------------------------------------
# The premises dimension moves while the remedy dimension holds (PRD §3.1, §3.3)
# --------------------------------------------------------------------------
def _build_reduction_active_on_i1(api):
    """I1 holds a breached ONGOING condition and an approved 10.01 pct reduction."""
    scenario = _build_open_center(api)
    condition = add_condition(
        api,
        scenario["leases"]["I1"],
        condition_kind="ONGOING",
        measurement_basis="GLA_PCT",
        required_occupancy_pct=81.67,
        required_anchor_count=2,
        grace_period_days=0,
        cure_period_days=30,
        remedy_type="RENT_REDUCTION_THEN_TERMINATION",
        max_reduction_pct=25.0,
    )
    # I3 dark takes the center to 225000/300000 = 75.00 pct, below the 81.67
    # requirement, so the condition breaches and I1 becomes remedy-eligible.
    go_dark(api, scenario["leases"]["I3"])
    election = elect_remedy(
        api,
        scenario["leases"]["I1"],
        scenario["tenants"]["I1"],
        election_kind="RENT_REDUCTION",
        window_from_date="2026-08-01",
        window_through_date="2026-11-01",
        condition_id=condition["id"],
    )
    approve_election(api, election["id"])
    scenario["condition_id"] = condition["id"]
    scenario["election_id"] = election["id"]
    return scenario


def test_going_dark_leaves_the_remedy_dimension_at_remedy_active(api):
    """A lease may sit DARK on the premises dimension and REMEDY_ACTIVE on the remedy one.

    PRD: "A single lease can perfectly legitimately be `DARK` on the premises dimension while sitting at `REMEDY_ACTIVE` on the remedy dimension."

    Design: Difficulty/non_linear_state_machine/lease_dark_dimension_moves_while_remedy_dimension_holds
    """
    scenario = _build_reduction_active_on_i1(api)

    go_dark(api, scenario["leases"]["I1"], as_tenant_id=scenario["tenants"]["I1"])

    lease = fetch_lease(api, scenario["leases"]["I1"])
    assert_lease_dimensions(
        lease, premises_status="DARK", remedy_status="REMEDY_ACTIVE"
    )
    assert lease["dark_since"].startswith("2026-08-01"), (
        f"dark_since should be the current logical instant, got {lease['dark_since']}"
    )
    election = fetch_election(api, scenario["election_id"])
    assert election["status"] == "REDUCTION_ACTIVE"


def test_going_dark_keeps_the_abated_effective_rent_of_the_active_reduction(api):
    """The premises transition recomputes effective rent and the active reduction still applies.

    PRD: "The lease's `effective_rent_monthly_cents` is recomputed on every approval, every rescission, every compliance sweep, every clock reposition, and every premises transition."

    Design: Difficulty/non_linear_state_machine/lease_dark_dimension_moves_while_remedy_dimension_holds
    """
    scenario = _build_reduction_active_on_i1(api)

    go_dark(api, scenario["leases"]["I1"], as_tenant_id=scenario["tenants"]["I1"])

    election = fetch_election(api, scenario["election_id"])
    # 81.67 required - 75.00 controlling = 6.67 shortfall, tier 1.5, 10.005
    # rounded half up to 10.01, floored at 5.00 and capped at 25.00.
    assert_pct(election["reduction_pct"], 10.01, "reduction_pct")
    lease = fetch_lease(api, scenario["leases"]["I1"])
    # 1000000 * (100 - 10.01) / 100, rounded once at the end.
    assert_lease_dimensions(lease, effective_rent_monthly_cents=899900)


def test_going_dark_subtracts_the_lease_area_from_the_center_figures(api):
    """The dark lease drops out of the numerator and out of the operating-store count.

    PRD: "Hop 2, caused by hop 1 because the lease is no longer counted open, subtracts the lease's `gla_sqft` from the center's `occupied_gla_sqft`, recomputes `open_occupancy_pct`, and decrements either `operating_store_count` or `open_anchor_count` according to the lease's `is_anchor`."

    Design: Difficulty/non_linear_state_machine/lease_dark_dimension_moves_while_remedy_dimension_holds
    """
    scenario = _build_reduction_active_on_i1(api)

    go_dark(api, scenario["leases"]["I1"], as_tenant_id=scenario["tenants"]["I1"])

    center = fetch_center(api, scenario["center_id"])
    # 255000 - 30000 (I3) - 2000 (I1) = 223000 of 300000 = 74.3333 -> 74.33.
    assert_center_quantities(
        center,
        occupied_gla_sqft=223000,
        open_occupancy_pct=74.33,
        operating_store_count=1,
        open_anchor_count=2,
    )


def test_going_dark_leaves_the_already_breached_condition_breached(api):
    """A condition still failing on the new figures takes its self-transition and stays BREACHED.

    PRD: "A condition that is already breached and still failing takes a self-transition on each later evaluation and on each compliance sweep: `consecutive_breach_days` is set to the number of whole days from `breach_detected_at` to the evaluation instant, `breach_detected_at` itself is left untouched, and the benefited lease moves from `NONE` to `ELIGIBLE` once `consecutive_breach_days` reaches or exceeds `grace_period_days`."

    Design: Difficulty/non_linear_state_machine/lease_dark_dimension_moves_while_remedy_dimension_holds
    """
    scenario = _build_reduction_active_on_i1(api)

    go_dark(api, scenario["leases"]["I1"], as_tenant_id=scenario["tenants"]["I1"])

    condition = fetch_condition(api, scenario["condition_id"])
    assert condition["status"] == "BREACHED"
    assert condition["breach_detected_at"].startswith("2026-08-01"), (
        f"breach_detected_at must be left untouched, got {condition['breach_detected_at']}"
    )
    assert condition["consecutive_breach_days"] == 0


def test_aggregate_rent_counts_the_dark_lease_at_its_abated_rent(api):
    """A DARK lease still contributes its abated effective rent to the center aggregate.

    PRD: "The center's `aggregate_effective_rent_cents` is then the sum of `effective_rent_monthly_cents` over the leases of that center whose `premises_status` is `OPEN` or `DARK`."

    Design: Difficulty/non_linear_state_machine/lease_dark_dimension_moves_while_remedy_dimension_holds
    """
    scenario = _build_reduction_active_on_i1(api)

    go_dark(api, scenario["leases"]["I1"], as_tenant_id=scenario["tenants"]["I1"])

    center = fetch_center(api, scenario["center_id"])
    # 6000000 + 4000000 + 899900 (abated I1) + 1200000 + 1500000.
    assert_cents(
        center["aggregate_effective_rent_cents"],
        13599900,
        "aggregate_effective_rent_cents",
    )


# --------------------------------------------------------------------------
# One approve trigger, two disjoint branches (PRD §3.5)
# --------------------------------------------------------------------------
def _build_two_elected_remedies(api):
    """An ELECTED rent reduction on I1 and an ELECTED termination on I2."""
    scenario = _build_open_center(api)
    condition_reduction = add_condition(
        api,
        scenario["leases"]["I1"],
        condition_kind="ONGOING",
        measurement_basis="GLA_PCT",
        required_occupancy_pct=81.67,
        required_anchor_count=2,
        grace_period_days=0,
        cure_period_days=0,
        remedy_type="RENT_REDUCTION_THEN_TERMINATION",
        max_reduction_pct=25.0,
    )
    condition_termination = add_condition(
        api,
        scenario["leases"]["I2"],
        condition_kind="ONGOING",
        measurement_basis="GLA_PCT",
        required_occupancy_pct=81.67,
        required_anchor_count=2,
        grace_period_days=0,
        cure_period_days=0,
        remedy_type="TERMINATION_ONLY",
        max_reduction_pct=25.0,
    )
    go_dark(api, scenario["leases"]["I3"])
    reduction_election = elect_remedy(
        api,
        scenario["leases"]["I1"],
        scenario["tenants"]["I1"],
        election_kind="RENT_REDUCTION",
        window_from_date="2026-08-01",
        window_through_date="2026-11-01",
        condition_id=condition_reduction["id"],
    )
    termination_election = elect_remedy(
        api,
        scenario["leases"]["I2"],
        scenario["tenants"]["I2"],
        election_kind="TERMINATION",
        window_from_date="2026-08-01",
        window_through_date="2026-11-01",
        condition_id=condition_termination["id"],
    )
    scenario["reduction_election_id"] = reduction_election["id"]
    scenario["termination_election_id"] = termination_election["id"]
    return scenario


def _approve_both_forks(api, scenario):
    approve_election(api, scenario["reduction_election_id"])
    approve_election(api, scenario["termination_election_id"])


def test_approving_a_rent_reduction_takes_the_reduction_active_branch(api):
    """A RENT_REDUCTION election approves into REDUCTION_ACTIVE and abates the lease rent.

    PRD: "For `RENT_REDUCTION` and `SUBSTITUTE_RENT`, the election moves `ELECTED → REDUCTION_ACTIVE`, stamping `approved_by_user_id` from `X-User-ID` and `approved_at` from the clock."

    Design: Difficulty/non_linear_state_machine/election_approval_forks_reduction_versus_termination_paths
    """
    scenario = _build_two_elected_remedies(api)

    _approve_both_forks(api, scenario)

    election = fetch_election(api, scenario["reduction_election_id"])
    assert election["status"] == "REDUCTION_ACTIVE"
    assert_pct(election["reduction_pct"], 10.01, "reduction_pct")
    lease = fetch_lease(api, scenario["leases"]["I1"])
    assert_lease_dimensions(
        lease, remedy_status="REMEDY_ACTIVE", effective_rent_monthly_cents=899900
    )


def test_approving_a_termination_takes_the_termination_scheduled_branch(api):
    """A TERMINATION election approves into TERMINATION_SCHEDULED with its effective date pinned.

    PRD: "`termination_effective_date` is pinned at approval as the `window_from_date` plus 90 days, expressed as an ISO date; it stays null for every other kind and for an election that has not been approved."

    Design: Difficulty/non_linear_state_machine/election_approval_forks_reduction_versus_termination_paths
    """
    scenario = _build_two_elected_remedies(api)

    _approve_both_forks(api, scenario)

    termination = fetch_election(api, scenario["termination_election_id"])
    assert termination["status"] == "TERMINATION_SCHEDULED"
    # 2026-08-01 window_from_date plus 90 days.
    assert termination["termination_effective_date"] == "2026-10-30"
    # 1200000 * (100 - 10.01) / 100, the informational per-election snapshot.
    assert_cents(
        termination["reduced_rent_monthly_cents"],
        1079880,
        "reduced_rent_monthly_cents",
    )
    reduction = fetch_election(api, scenario["reduction_election_id"])
    assert reduction["termination_effective_date"] is None


def test_termination_branch_moves_remedy_status_without_touching_rent(api):
    """The termination fork leaves effective rent and the center aggregate exactly where they were.

    PRD: "The lease's `remedy_status` becomes `TERMINATION_PENDING`, and — this is the asymmetry to watch — `effective_rent_monthly_cents` is left completely unchanged and the center's `aggregate_effective_rent_cents` does not move, because no abatement attaches to a termination election."

    Design: Difficulty/non_linear_state_machine/election_approval_forks_reduction_versus_termination_paths
    """
    scenario = _build_two_elected_remedies(api)

    _approve_both_forks(api, scenario)

    lease = fetch_lease(api, scenario["leases"]["I2"])
    assert_lease_dimensions(
        lease,
        remedy_status="TERMINATION_PENDING",
        effective_rent_monthly_cents=1200000,
    )
    center = fetch_center(api, scenario["center_id"])
    # Only the I1 reduction moved the aggregate: 6000000 + 4000000 + 899900
    # + 1200000 + 1500000.
    assert_cents(
        center["aggregate_effective_rent_cents"],
        13599900,
        "aggregate_effective_rent_cents",
    )


def test_two_breached_conditions_freeze_the_center_across_both_forks(api):
    """Two breached conditions hold the center at FROZEN through both approval branches.

    PRD: "The posture is `FROZEN` when the breached-condition count is at least two, or when the center is assessable and its `open_occupancy_pct` is strictly below 50.00."

    Design: Difficulty/non_linear_state_machine/election_approval_forks_reduction_versus_termination_paths
    """
    scenario = _build_two_elected_remedies(api)

    _approve_both_forks(api, scenario)

    center = fetch_center(api, scenario["center_id"])
    assert_center_quantities(center, compliance_posture="FROZEN")


# --------------------------------------------------------------------------
# The five-hop go-dark cascade (PRD §2.10, §3.3, §3.8)
# --------------------------------------------------------------------------
def _build_signed_certificate_on_i1(api):
    """I1 holds a SATISFIED ONGOING condition and a TENANT_SIGNED certificate."""
    scenario = _build_open_center(api)
    condition = add_condition(
        api,
        scenario["leases"]["I1"],
        condition_kind="ONGOING",
        measurement_basis="GLA_PCT",
        required_occupancy_pct=81.67,
        required_anchor_count=2,
        grace_period_days=0,
        cure_period_days=30,
        remedy_type="RENT_REDUCTION_THEN_TERMINATION",
        max_reduction_pct=25.0,
    )
    certificate = request_certificate(
        api, scenario["leases"]["I1"], expedite_requested=False
    )
    sign_certificate(api, certificate["id"], scenario["tenants"]["I1"])
    scenario["condition_id"] = condition["id"]
    scenario["certificate_id"] = certificate["id"]
    return scenario


def test_go_dark_hop_one_darkens_the_premises_and_stamps_dark_since(api):
    """Hop 1 of the go-dark cascade moves the premises to DARK and stamps dark_since.

    PRD: "Hop 1 sets `premises_status` to `DARK`, stamps `dark_since` with the current logical instant, and increments the lease's `version`."

    Design: Difficulty/transitive_cascade/go_dark_cascades_through_occupancy_condition_remedy_and_estoppel
    """
    scenario = _build_signed_certificate_on_i1(api)

    go_dark(api, scenario["leases"]["I3"])

    lease = fetch_lease(api, scenario["leases"]["I3"])
    assert_lease_dimensions(lease, premises_status="DARK")
    assert lease["dark_since"].startswith("2026-08-01"), (
        f"dark_since should be the current logical instant, got {lease['dark_since']}"
    )


def test_go_dark_hop_two_rewrites_the_center_occupancy_figures(api):
    """Hop 2 subtracts the dark suite from the numerator and the operating-store count.

    PRD: "Hop 2, caused by hop 1 because the lease is no longer counted open, subtracts the lease's `gla_sqft` from the center's `occupied_gla_sqft`, recomputes `open_occupancy_pct`, and decrements either `operating_store_count` or `open_anchor_count` according to the lease's `is_anchor`."

    Design: Difficulty/transitive_cascade/go_dark_cascades_through_occupancy_condition_remedy_and_estoppel
    """
    scenario = _build_signed_certificate_on_i1(api)

    go_dark(api, scenario["leases"]["I3"])

    center = fetch_center(api, scenario["center_id"])
    # 255000 - 30000 = 225000 of 300000 = 75.00 pct; I3 is not an anchor.
    assert_center_quantities(
        center,
        occupied_gla_sqft=225000,
        open_occupancy_pct=75.00,
        operating_store_count=2,
        open_anchor_count=2,
    )


def test_go_dark_hop_three_breaches_the_ongoing_condition(api):
    """Hop 3 flips the SATISFIED condition to BREACHED with a fresh breach episode.

    PRD: "Hop 3, caused by hop 2 because the center's occupancy figures moved, re-evaluates every `ONGOING` condition of the center under the live strict engine; a condition that now fails flips from `SATISFIED` or `CURED` to `BREACHED` with `breach_detected_at` stamped at the current instant and `consecutive_breach_days` reset to 0."

    Design: Difficulty/transitive_cascade/go_dark_cascades_through_occupancy_condition_remedy_and_estoppel
    """
    scenario = _build_signed_certificate_on_i1(api)

    go_dark(api, scenario["leases"]["I3"])

    condition = fetch_condition(api, scenario["condition_id"])
    assert condition["status"] == "BREACHED"
    assert condition["breach_detected_at"].startswith("2026-08-01"), (
        f"breach_detected_at should be the current instant, got {condition['breach_detected_at']}"
    )
    assert condition["consecutive_breach_days"] == 0


def test_go_dark_hop_four_lifts_the_benefited_lease_to_eligible(api):
    """Hop 4 moves the benefited lease NONE to ELIGIBLE because the grace period is zero.

    PRD: "Hop 4, caused by hop 3 because a condition flipped, moves the benefited lease of each newly breached condition from `remedy_status` `NONE` to `ELIGIBLE` with `remedy_eligible_at` stamped — but only when that condition's `grace_period_days` is 0; a condition with a non-zero grace window waits for the sweep — and bumps that benefited lease's `version`, while the center's posture is re-derived to `BREACH` or `FROZEN`."

    Design: Difficulty/transitive_cascade/go_dark_cascades_through_occupancy_condition_remedy_and_estoppel
    """
    scenario = _build_signed_certificate_on_i1(api)

    go_dark(api, scenario["leases"]["I3"])

    benefited = fetch_lease(api, scenario["leases"]["I1"])
    assert_lease_dimensions(benefited, remedy_status="ELIGIBLE")
    assert benefited["remedy_eligible_at"].startswith("2026-08-01"), (
        f"remedy_eligible_at should be stamped, got {benefited['remedy_eligible_at']}"
    )


def test_go_dark_hop_five_stales_the_signed_certificate_of_the_benefited_lease(api):
    """Hop 5 drives the TENANT_SIGNED certificate to STALE with lender conditions false.

    PRD: "Hop 5, caused by hop 4 because the benefited lease's version advanced, flips every estoppel certificate of that benefited lease whose `status` is `REQUESTED` or `TENANT_SIGNED` to `STALE` and recomputes its `lender_conditions_met` to false."

    Design: Difficulty/transitive_cascade/go_dark_cascades_through_occupancy_condition_remedy_and_estoppel
    """
    scenario = _build_signed_certificate_on_i1(api)

    go_dark(api, scenario["leases"]["I3"])

    certificate = fetch_certificate(api, scenario["certificate_id"])
    assert certificate["status"] == "STALE"
    assert certificate["lender_conditions_met"] is False


def test_go_dark_cascade_leaves_the_certificate_fee_exactly_as_assessed(api):
    """The fee pinned when the certificate was requested is untouched by the cascade.

    PRD: "First, the pre-surcharge subtotal is 25,000 cents of base fee, plus 5,000 cents for each disclosed exclusive-use clause, plus a further 15,000 cents when `disclosed_cotenancy_breach` is true."

    Design: Difficulty/transitive_cascade/go_dark_cascades_through_occupancy_condition_remedy_and_estoppel
    """
    scenario = _build_signed_certificate_on_i1(api)

    go_dark(api, scenario["leases"]["I3"])

    certificate = fetch_certificate(api, scenario["certificate_id"])
    # No exclusive-use clause benefits I1 and no breach was disclosed at request
    # time, and expedite was not requested, so the surcharge is zero.
    assert_cents(certificate["base_fee_cents"], 25000, "base_fee_cents")
    assert_cents(certificate["total_fee_cents"], 25000, "total_fee_cents")


def test_go_dark_cascade_ends_with_the_center_at_breach(api):
    """One breached condition and 75.00 pct occupancy settle the center at BREACH.

    PRD: "Otherwise the posture is `BREACH` when the breached-condition count is at least one."

    Design: Difficulty/transitive_cascade/go_dark_cascades_through_occupancy_condition_remedy_and_estoppel
    """
    scenario = _build_signed_certificate_on_i1(api)

    go_dark(api, scenario["leases"]["I3"])

    center = fetch_center(api, scenario["center_id"])
    assert_center_quantities(center, compliance_posture="BREACH")


# --------------------------------------------------------------------------
# The four-hop escalation cascade plus its clause fan-out (PRD §3.6)
# --------------------------------------------------------------------------
def _build_escalatable_notice_with_signed_certificate(api):
    """An I3 notice past its cure deadline, plus a signed certificate on I3."""
    scenario = _build_open_center(api)
    clause = add_clause(
        api,
        scenario["leases"]["I1"],
        protected_use_codes=["COFFEE"],
        exclusivity_scope="CENTER_WIDE",
        effective_from_date="2026-01-01",
        effective_through_date="2036-12-31",
        gla_carve_out_sqft=0,
        incidental_sales_pct_cap=0.0,
    )
    notice = issue_notice(
        api,
        scenario["leases"]["I3"],
        notice_kind="EXCLUSIVE_USE",
        clause_id=clause["id"],
        narrative="Espresso bar operating inside the fitness premises.",
        cure_period_days=30,
    )
    certificate = request_certificate(
        api, scenario["leases"]["I3"], expedite_requested=False
    )
    sign_certificate(api, certificate["id"], scenario["tenants"]["I3"])
    # Past the 2026-08-31 cure deadline, so escalation is available.
    set_clock(api, "2026-09-01T00:00:00Z")
    scenario["clause_id"] = clause["id"]
    scenario["notice_id"] = notice["id"]
    scenario["certificate_id"] = certificate["id"]
    return scenario


def test_escalation_hop_one_escalates_the_notice_and_stamps_the_instant(api):
    """Hop 1 of the escalation cascade moves the notice to ESCALATED and stamps escalated_at.

    PRD: "Hop 1 sets the notice `status` to `ESCALATED` and stamps `escalated_at` with the sweep instant."

    Design: Difficulty/transitive_cascade/notice_escalation_cascades_to_lease_certificate_and_remedy_eligibility
    """
    scenario = _build_escalatable_notice_with_signed_certificate(api)

    escalate_notice(api, scenario["notice_id"])

    notice = fetch_notice(api, scenario["notice_id"])
    assert notice["status"] == "ESCALATED"
    assert notice["escalated_at"].startswith("2026-09-01"), (
        f"escalated_at should be the escalation instant, got {notice['escalated_at']}"
    )


def test_escalation_hop_two_puts_the_violating_lease_in_violation(api):
    """Hop 2 drives the violating lease's use_compliance_status to IN_VIOLATION.

    PRD: "Hop 2, caused by hop 1 because an escalated notice now stands against the premises, sets the violating lease's `use_compliance_status` to `IN_VIOLATION` and advances that lease's `version`."

    Design: Difficulty/transitive_cascade/notice_escalation_cascades_to_lease_certificate_and_remedy_eligibility
    """
    scenario = _build_escalatable_notice_with_signed_certificate(api)

    escalate_notice(api, scenario["notice_id"])

    violating_lease = fetch_lease(api, scenario["leases"]["I3"])
    assert_lease_dimensions(violating_lease, use_compliance_status="IN_VIOLATION")


def test_escalation_hop_three_stales_the_certificate_pinned_to_that_lease(api):
    """Hop 3 flips the TENANT_SIGNED certificate of the violating lease to STALE.

    PRD: "Hop 3, caused by hop 2 because the violating lease's version has moved past the pinned value, flips every estoppel certificate of that lease whose `status` is `REQUESTED` or `TENANT_SIGNED` to `STALE`."

    Design: Difficulty/transitive_cascade/notice_escalation_cascades_to_lease_certificate_and_remedy_eligibility
    """
    scenario = _build_escalatable_notice_with_signed_certificate(api)

    escalate_notice(api, scenario["notice_id"])

    certificate = fetch_certificate(api, scenario["certificate_id"])
    assert certificate["status"] == "STALE"


def test_escalation_hop_four_clears_lender_conditions_on_the_stale_certificate(api):
    """Hop 4 recomputes the stale certificate's lender_conditions_met to false.

    PRD: "Hop 4, caused by hop 3 because the certificate is no longer current, recomputes each stale certificate's `lender_conditions_met` to false."

    Design: Difficulty/transitive_cascade/notice_escalation_cascades_to_lease_certificate_and_remedy_eligibility
    """
    scenario = _build_escalatable_notice_with_signed_certificate(api)

    escalate_notice(api, scenario["notice_id"])

    certificate = fetch_certificate(api, scenario["certificate_id"])
    assert certificate["lender_conditions_met"] is False


def test_escalation_fans_out_to_the_benefited_lease_of_the_cited_clause(api):
    """Escalating an EXCLUSIVE_USE notice lifts the clause holder to remedy ELIGIBLE.

    PRD: "Separately from that hop chain, an `EXCLUSIVE_USE` notice fans out to the benefited lease of its `clause_id`, moving that lease's `remedy_status` from `NONE` to `ELIGIBLE` with `remedy_eligible_at` stamped at the sweep instant — opening the door to a substitute-rent election — and the center's posture is re-derived."

    Design: Difficulty/transitive_cascade/notice_escalation_cascades_to_lease_certificate_and_remedy_eligibility
    """
    scenario = _build_escalatable_notice_with_signed_certificate(api)

    escalate_notice(api, scenario["notice_id"])

    benefited = fetch_lease(api, scenario["leases"]["I1"])
    assert_lease_dimensions(benefited, remedy_status="ELIGIBLE")
    assert benefited["remedy_eligible_at"].startswith("2026-09-01"), (
        f"remedy_eligible_at should be the escalation instant, got {benefited['remedy_eligible_at']}"
    )


def test_escalation_leaves_the_center_on_watch_from_the_open_violation(api):
    """The open violation alone holds the center at WATCH while occupancy stays at 85.00 pct.

    PRD: "Otherwise the posture is `WATCH` when `open_violation_count` is at least one, or when the center is assessable and its `open_occupancy_pct` is strictly below 70.00."

    Design: Difficulty/transitive_cascade/notice_escalation_cascades_to_lease_certificate_and_remedy_eligibility
    """
    scenario = _build_escalatable_notice_with_signed_certificate(api)

    escalate_notice(api, scenario["notice_id"])

    center = fetch_center(api, scenario["center_id"])
    assert_center_quantities(
        center,
        open_violation_count=1,
        open_occupancy_pct=85.00,
        compliance_posture="WATCH",
    )
