"""Depth-3 cascades, conserved-quantity invariants, OCC guards, and
derived-field reconciliation (difficulty: transitive_cascade,
compensating_invariant; corner: cross_cutting)."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, TEST_USERS, make_registrar_headers,
    create_district, create_student, create_plan, create_cost_share,
    make_student_eligible, setup_completed_trip, setup_active_plan_with_vehicle,
    setup_approved_plan,
)

SC = TEST_USERS["state_coordinator_headers"]


# ---------------------------------------------------------------------------
# Difficulty: transitive_cascade — finalize determination depth-3
# ---------------------------------------------------------------------------
def test_finalize_sets_eligibility_and_creates_benefit_link(api):
    """PRD §3.3: "First, the student's `eligibility_status` is set to the determination's `decision`, and the student's `priority_score` is recomputed to its final variant with `priority_basis` set to `FINAL`."
    PRD §3.3: "Second, if the decision was `ELIGIBLE` and the student currently has no `ACTIVE` benefit link, a new `BenefitLink` is created with `source` `AUTO_ELIGIBILITY`, `status` `ACTIVE`, and `district_id` equal to the student's `enrolled_district_id`."

    Design: Difficulty/transitive_cascade/finalize_determination_cascade_depth3
    """
    d = create_district()
    s = create_student(d["id"])
    make_student_eligible(s["id"], s["version"])
    student = validate_success(api.get_student(s["id"], SC))
    assert student["eligibility_status"] == "ELIGIBLE"
    links, meta = validate_paginated(api.list_benefit_links(SC, params={"student_id": s["id"]}))
    active = [l for l in links if l["status"] == "ACTIVE"]
    assert len(active) == 1, "exactly one ACTIVE benefit link after finalize"


def test_finalize_increments_district_categorical_count(api):
    """PRD §3.3: "Third, that new benefit link increments the district's
    `categorical_eligible_count`."

    Design: Difficulty/transitive_cascade/finalize_determination_cascade_depth3
    """
    d = create_district()
    s = create_student(d["id"])
    make_student_eligible(s["id"], s["version"])
    district = validate_success(api.get_district(d["id"], SC))
    assert district["categorical_eligible_count"] == 1


# ---------------------------------------------------------------------------
# Difficulty: transitive_cascade — trip completion ledger depth-3
# ---------------------------------------------------------------------------
def test_completion_updates_agreement_and_appends_ledger(api):
    """PRD §3.7: "the agreement's `actual_cost_cents` increases by the serving
    delta. Third, a `CostLedgerEntry` of `entry_type` `TRIP_CHARGE` is appended with
    `amount_cents` equal to the round-half-up of `trip_cost_cents` multiplied by the
    agreement's `serving_pct`, its `district_id` set to the serving district".

    Design: Difficulty/transitive_cascade/trip_complete_ledger_cascade_depth3
    """
    ctx = setup_completed_trip(route_miles=20, actual_miles=20)  # serving_pct 0.6, trip_cost 3600
    agreement = validate_success(api.get_agreement(ctx["agreement"]["id"], SC))
    assert agreement["actual_cost_cents"] == 2160
    entries, meta = validate_paginated(
        api.list_ledger_entries(SC, params={"cost_share_agreement_id": ctx["agreement"]["id"]}))
    assert len(entries) == 1
    assert entries[0]["entry_type"] == "TRIP_CHARGE"
    assert entries[0]["amount_cents"] == 2160


def test_completion_increments_district_transport_balance(api):
    """PRD §3.7: "Finally, that entry increments the serving district's
    `transport_balance_cents` by its `amount_cents`."

    Design: Difficulty/transitive_cascade/trip_complete_ledger_cascade_depth3
    """
    ctx = setup_completed_trip(route_miles=20, actual_miles=20)
    district = validate_success(api.get_district(ctx["district"]["id"], SC))
    assert district["transport_balance_cents"] == 2160


# ---------------------------------------------------------------------------
# Difficulty: compensating_invariant — void restores transport balance
# ---------------------------------------------------------------------------
def test_void_restores_balance_and_agreement_actual(api):
    """PRD §3.7: "The plan's `actual_cost_cents` and the agreement's `actual_cost_cents` each decrease by the same serving delta the completion added; a `CostLedgerEntry` of `entry_type` `REVERSAL` is appended whose `amount_cents` is the negative of the round-half-up of `trip_cost_cents` times `serving_pct` (with `district_id` again the serving district); and the serving district's `transport_balance_cents` decreases by that magnitude"

    Design: Difficulty/compensating_invariant/trip_void_restores_district_transport_balance
    """
    ctx = setup_completed_trip(route_miles=20, actual_miles=20)
    api.void_trip(ctx["trip"]["id"], SC)
    district = validate_success(api.get_district(ctx["district"]["id"], SC))
    assert district["transport_balance_cents"] == 0
    agreement = validate_success(api.get_agreement(ctx["agreement"]["id"], SC))
    assert agreement["actual_cost_cents"] == 0


def test_void_appends_reversal_ledger_summing_zero(api):
    """PRD §3.7: "a `CostLedgerEntry` of `entry_type` `REVERSAL` is appended whose
    `amount_cents` is the negative of the round-half-up of `trip_cost_cents` times
    `serving_pct`".

    Design: Difficulty/compensating_invariant/trip_void_restores_district_transport_balance
    """
    ctx = setup_completed_trip(route_miles=20, actual_miles=20)
    api.void_trip(ctx["trip"]["id"], SC)
    entries, meta = validate_paginated(
        api.list_ledger_entries(SC, params={"cost_share_agreement_id": ctx["agreement"]["id"]}))
    assert len(entries) == 2, "one TRIP_CHARGE and one REVERSAL"
    assert sum(e["amount_cents"] for e in entries) == 0
    types = sorted(e["entry_type"] for e in entries)
    assert types == ["REVERSAL", "TRIP_CHARGE"]


# ---------------------------------------------------------------------------
# Difficulty: compensating_invariant — benefit revoke restores count
# ---------------------------------------------------------------------------
def test_revoke_sets_benefit_link_revoked(api):
    """PRD §3.8: "A `Liaison` or `StateCoordinator` may revoke an `ACTIVE` link,
    moving it to the terminal `REVOKED` and decrementing that district's
    `categorical_eligible_count` by one".

    Design: Difficulty/compensating_invariant/benefit_revoke_restores_categorical_eligible_count
    """
    d = create_district()
    s = create_student(d["id"])
    make_student_eligible(s["id"], s["version"])
    links, _ = validate_paginated(api.list_benefit_links(SC, params={"student_id": s["id"]}))
    bl = links[0]
    data = validate_success(api.revoke_benefit_link(bl["id"], SC))
    assert data["status"] == "REVOKED"


def test_revoke_decrements_categorical_count(api):
    """PRD §3.8: "decrementing that district's `categorical_eligible_count` by one —
    the compensating counterpart to the increment at grant time."

    Design: Difficulty/compensating_invariant/benefit_revoke_restores_categorical_eligible_count
    """
    d = create_district()
    s = create_student(d["id"])
    make_student_eligible(s["id"], s["version"])
    links, _ = validate_paginated(api.list_benefit_links(SC, params={"student_id": s["id"]}))
    api.revoke_benefit_link(links[0]["id"], SC)
    district = validate_success(api.get_district(d["id"], SC))
    assert district["categorical_eligible_count"] == 0


# ---------------------------------------------------------------------------
# Corner: cross_cutting — OCC guards
# ---------------------------------------------------------------------------
def test_occ_cost_share_stale_plan_version_rejected(api):
    """PRD §2.5: "If that value does not equal the plan's current `version` — meaning another writer advanced the plan since the client last read it — the create is rejected with `ERR_STALE_VERSION` (HTTP 412)."
    PRD §2.5: "A successful create increments the plan's `version` by one."

    Design: Corner/cross_cutting/occ_cost_share_stale_plan_version_rejected
    """
    d = create_district()
    s = create_student(d["id"])
    plan = create_plan(s["id"], d["id"], route_miles=20)
    v0 = plan["version"]
    create_cost_share(plan["id"], v0)  # succeeds, bumps plan version
    resp = api.create_cost_share(
        {"transportation_plan_id": plan["id"], "expected_transportation_plan_version": v0}, SC)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value, 412)


def test_occ_determination_stale_student_version_rejected(api):
    """PRD §2.5: "If it does not equal the student's current `version`, the create is rejected with `ERR_STALE_VERSION` (HTTP 412), because a newly created determination supersedes any prior `DRAFT` for that student."
    PRD §2.5: "A successful create increments the student's `version` by one."

    Design: Corner/cross_cutting/occ_determination_stale_student_version_rejected
    """
    d = create_district()
    s = create_student(d["id"])
    v0 = s["version"]
    get_success_data(api.create_determination(
        s["id"], {"category": "HOMELESS", "basis": "SHELTER", "decision": "ELIGIBLE",
                  "effective_date": "2026-05-01", "expected_student_version": v0}, SC))
    resp = api.create_determination(
        s["id"], {"category": "HOMELESS", "basis": "SHELTER", "decision": "ELIGIBLE",
                  "effective_date": "2026-05-01", "expected_student_version": v0}, SC)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value, 412)


# ---------------------------------------------------------------------------
# Corner: cross_cutting — withdraw cascade
# ---------------------------------------------------------------------------
def test_withdraw_cascade_terminates_plan_and_revokes_benefit(api):
    """PRD §3.2: "every transportation plan for this student that is currently `APPROVED`, `ACTIVE`, or `SUSPENDED` is driven to `TERMINATED`, which in turn cancels that plan's `SCHEDULED` trips and, for any plan that had committed budget, releases the serving district's committed cost (see §3.5)."
    PRD §3.2: "Second, every `ACTIVE` benefit link for the student is driven to `REVOKED`, each revocation decrementing the enrolled district's `categorical_eligible_count`."

    Design: Corner/cross_cutting/withdraw_cascade_terminates_plan_and_revokes_benefit
    """
    d = create_district()
    reg = make_registrar_headers(d["id"])
    s = create_student(d["id"], headers=reg)
    enrolled = validate_success(api.enroll_student(s["id"], reg))
    make_student_eligible(s["id"], enrolled["version"])
    plan = create_plan(s["id"], d["id"], route_miles=20)
    create_cost_share(plan["id"], plan["version"])
    api.submit_plan(plan["id"], SC)
    api.approve_plan(plan["id"], SC)
    api.activate_plan(plan["id"], SC)

    withdrawn = validate_success(api.withdraw_student(s["id"], reg))
    assert withdrawn["status"] == "WITHDRAWN"
    plan_after = validate_success(api.get_plan(plan["id"], SC))
    assert plan_after["status"] == "TERMINATED"
    district = validate_success(api.get_district(d["id"], SC))
    assert district["categorical_eligible_count"] == 0


# ---------------------------------------------------------------------------
# Corner: cross_cutting — activation reconciles committed cost
# ---------------------------------------------------------------------------
def test_activation_reconciles_committed_cost(api):
    """PRD §3.5: "When both gates pass, activation commits budget by adding the
    agreement's `serving_share_cents` to the serving district's `committed_cost_cents`."

    Design: Corner/cross_cutting/activate_reconciles_committed_cost_derived_field
    """
    ctx = setup_approved_plan(route_miles=20, budget=100_000_000)  # serving_share 43200
    activated = validate_success(api.activate_plan(ctx["plan"]["id"], SC))
    assert activated["status"] == "ACTIVE"
    district = validate_success(api.get_district(ctx["district"]["id"], SC))
    assert district["committed_cost_cents"] == 43200
