"""Corner (breadth) tests for calculations and endpoint behaviors.

Queue (B) corner-design instances from the `calculations` and `endpoints`
sections (PRD §2.5, §3.5, §3.6, §3.7).
"""
from test_helpers import (
    advance_clock,
    create_unit,
    generate_reserve_report,
    get_community,
    get_residency,
    list_refund_disbursements,
    setup_active_residency,
    setup_community_and_plan,
    setup_residency_in_skilled_with_occupied_bed,
    terminate_residency,
    AD,
    FO,
    NON_EXISTENT_UUID,
)
from test_helpers.api_client import api_client
from test_helpers import (
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_errors import ApiErrorId
from test_helpers.factories import create_bed_reservation_payload


def _AD():
    from test_helpers import make_admissions_director_headers
    return make_admissions_director_headers()


def _CC():
    from test_helpers import make_care_coordinator_headers
    return make_care_coordinator_headers()


# ─── calculations / invoice_type_b_discounted_days_partial_exhaustion ────────

def test_invoice_type_b_partial_discounted_day_exhaustion(api):
    """PRD §3.6: "under `TYPE_B`, the modified contract, the residency's first
    `typeb_discounted_days` skilled days across its whole life are free, so the
    number of still-free days is the larger of 0 and `typeb_discounted_days` minus
    the residency's already-accumulated `skilled_days_used`, the billable days are
    the larger of 0 and this period's skilled days minus those still-free days, and
    the surcharge is the billable days multiplied by the plan's `skilled_per_diem_cents`".

    typeb_discounted_days=10, skilled_days_used=0, 15 skilled days: 5 billable,
    care=5*40_000=200_000, total=300_000+200_000=500_000.

    Design: Corner/calculations/invoice_type_b_discounted_days_partial_exhaustion
    """
    _community, _plan, _ind, _sk, residency = (
        setup_residency_in_skilled_with_occupied_bed(
            community_name="TypeB",
            plan_overrides={
                "name": "Bp", "contract_type": "TYPE_B",
                "entrance_fee_cents": 5_000_000, "refund_plan": "DECLINING",
                "monthly_service_fee_cents": 300_000, "second_person_fee_cents": 0,
                "skilled_per_diem_cents": 40_000, "typeb_discounted_days": 10,
            },
        )
    )
    invoice = validate_success(api_client.issue_invoice(
        residency["id"], {"skilled_days_in_period": 15}, FO,
    ), expected_status=201)
    assert invoice["care_surcharge_cents"] == 200_000, (
        f"TYPE_B 5 billable days care must be 200_000, got {invoice['care_surcharge_cents']}"
    )
    assert invoice["total_cents"] == 500_000, (
        f"TYPE_B total must be 500_000, got {invoice['total_cents']}"
    )


# ─── calculations / occupancy_accrual_increments_months_by_advance ──────────

def test_occupancy_accrual_increments_months_by_advance(api):
    """PRD §2.5: "for every residency in that community whose status is `ACTIVE` at the
    moment of the advance, the residency's `occupied_months` counter is increased by
    exactly N. Because activation sets `occupied_months` to 0 at the activation
    period, a subsequent advance of N steps adds precisely N".

    An ACTIVE residency at occupied_months 0; advancing by 7 sets occupied_months 7.

    Design: Corner/calculations/occupancy_accrual_increments_months_by_advance
    """
    community, _plan, _unit, active = setup_active_residency(
        community_name="Accr", plan_overrides={"name": "Acp", "second_person_fee_cents": 0},
    )
    advance_clock(community["id"], 7)
    fresh = get_residency(active["id"])
    assert fresh["occupied_months"] == 7, (
        f"occupied_months must be 7 after a 7-period advance, got {fresh['occupied_months']}"
    )


# ─── calculations / reserve_report_deficient_but_not_frozen_boundary ────────

def test_reserve_report_deficient_but_not_frozen(api):
    """PRD §3.6: "The report's `is_deficient` flag is true exactly when
    `funded_ratio_bps` is strictly less than the community's `target_funded_ratio_bps`."
    PRD §3.6: "when `funded_ratio_bps` falls strictly below the floor of the
    community's `target_funded_ratio_bps` divided by 2 — that is, below half the
    target — the community's `is_admissions_frozen` is set to true".

    One ACTIVE residency (msf 1000, m 0, DECLINING entrance 100000 nonref 400bps),
    reserve_assets 100000+entrance 100000=200000: future 240000, refund_liability
    96000, funded_ratio 5952. is_deficient true (5952<10000), NOT frozen
    (5952 not < floor(10000/2)=5000).

    Design: Corner/calculations/reserve_report_deficient_but_not_frozen_boundary
    """
    community, plan, _unit, active = setup_active_residency(
        community_name="Defc",
        actuarial_discount_rate_bps=0,
        reserve_assets_cents=100_000,
        target_funded_ratio_bps=10000,
        plan_overrides={
            "name": "Dcp", "contract_type": "TYPE_C",
            "entrance_fee_cents": 100_000, "refund_plan": "DECLINING",
            "monthly_service_fee_cents": 1000, "second_person_fee_cents": 0,
            "declining_nonrefundable_bps": 400,
        },
    )
    report = generate_reserve_report(community["id"])
    assert report["future_obligation_cents"] == 240_000, (
        f"future_obligation must be 240_000, got {report['future_obligation_cents']}"
    )
    assert report["refund_liability_cents"] == 96_000, (
        f"refund_liability must be 96_000, got {report['refund_liability_cents']}"
    )
    assert report["funded_ratio_bps"] == 5952, (
        f"funded_ratio_bps must be 5952, got {report['funded_ratio_bps']}"
    )
    assert report["is_deficient"] is True, "report must be deficient (5952 < 10000)"
    fresh = get_community(community["id"])
    assert fresh["is_admissions_frozen"] is False, (
        "community must NOT be frozen (5952 not below the freeze divisor threshold 5000)"
    )


# ─── endpoints / refund_disbursement_settle_moves_to_settled ────────────────

def test_settle_pending_refund_moves_to_settled(api):
    """PRD §3.7: "After a refund disbursement has been created, a `FinanceOfficer`
    settles it, driving it from `PENDING` to `SETTLED` and stamping
    `settlement_period_index` with the community's current `current_period_index`."

    Design: Corner/endpoints/refund_disbursement_settle_moves_to_settled
    """
    _community, _plan, _unit, active = setup_active_residency(
        community_name="Settle", plan_overrides={"name": "Sp", "second_person_fee_cents": 0},
    )
    fresh = get_residency(active["id"])
    terminate_residency(fresh["id"], "VOLUNTARY", fresh["version"])
    refund = list_refund_disbursements(fresh["id"])[0]
    settled = validate_success(api_client.settle_refund(refund["id"], FO))
    assert settled["status"] == "SETTLED", (
        f"refund must become SETTLED, got {settled['status']}"
    )


# ─── endpoints / bed_reservation_invalid_hold_window_returns_error ──────────

def test_bed_reservation_invalid_hold_window_rejected(api):
    """PRD §3.5: "The `hold_expiry_period` must be strictly greater than the
    community's current period at hold time, else `ERR_INVALID_HOLD_WINDOW`."

    At period 0, hold_expiry_period 0 is not strictly greater → ERR_INVALID_HOLD_WINDOW.

    Design: Corner/endpoints/bed_reservation_invalid_hold_window_returns_error
    """
    community, plan = setup_community_and_plan(
        community_name="Hold",
        plan_overrides={"name": "Hp", "contract_type": "TYPE_A", "second_person_fee_cents": 0},
    )
    from test_helpers import activate_residency, reserve_residency_via_assign
    ind = create_unit(community["id"], unit_number="HI", care_level="INDEPENDENT")
    skilled = create_unit(community["id"], unit_number="HS", care_level="SKILLED", bed_capacity=1)
    active = activate_residency(reserve_residency_via_assign(community, plan, ind))
    resp = api_client.create_bed_reservation(
        create_bed_reservation_payload(active["id"], skilled["id"], 0), _CC(),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_HOLD_WINDOW.value)


# ─── endpoints / filtered_list_residencies_by_status ────────────────────────

def test_filtered_list_residencies_by_status(api):
    """PRD §4 (GET /ccrc/residencies): "List residencies (filter by community_id,
    status, unit_id, contract_plan_id, primary_resident_id)".
    PRD §3.2: "A freshly opened residency starts in `DEPOSIT_HELD` status"; assign-unit
    drives it to `RESERVED`.

    Filtering by status=DEPOSIT_HELD returns the DEPOSIT_HELD residency and not the
    RESERVED one.

    Design: Corner/endpoints/filtered_list_residencies_by_status
    """
    from test_helpers import open_residency
    community, plan = setup_community_and_plan(
        community_name="Filt", plan_overrides={"name": "Fp", "second_person_fee_cents": 0},
    )
    unit = create_unit(community["id"], unit_number="FU", care_level="INDEPENDENT")
    r1 = open_residency(community, plan, resident_name="Fa F", dob="1930-01-01")
    r2 = open_residency(community, plan, resident_name="Fb F", dob="1929-01-01")
    validate_success(api_client.assign_unit(r2["id"], {"unit_id": unit["id"]}, _AD()))
    data, _meta = validate_paginated(api_client.list_residencies(
        _AD(), params={"status": "DEPOSIT_HELD", "community_id": community["id"]},
    ))
    ids = {row["id"] for row in data}
    assert r1["id"] in ids, "DEPOSIT_HELD residency must appear in the filtered list"
    assert r2["id"] not in ids, "RESERVED residency must NOT appear in DEPOSIT_HELD filter"


# ─── endpoints / bed_reservation_on_independent_unit_returns_not_skilled ─────

def test_bed_reservation_on_independent_unit_rejected(api):
    """PRD §3.5: "The target unit must have `care_level` `SKILLED`, else
    `ERR_UNIT_NOT_SKILLED`."

    Design: Corner/endpoints/bed_reservation_on_independent_unit_returns_not_skilled
    """
    community, plan = setup_community_and_plan(
        community_name="NotSk",
        plan_overrides={"name": "Nsp", "contract_type": "TYPE_A", "second_person_fee_cents": 0},
    )
    from test_helpers import activate_residency, reserve_residency_via_assign
    ind = create_unit(community["id"], unit_number="NSI", care_level="INDEPENDENT")
    active = activate_residency(reserve_residency_via_assign(community, plan, ind))
    resp = api_client.create_bed_reservation(
        create_bed_reservation_payload(active["id"], ind["id"], 5), _CC(),
    )
    validate_error(resp, ApiErrorId.ERR_UNIT_NOT_SKILLED.value)


# ─── endpoints / clock_advance_zero_periods_returns_invalid_clock_advance ────

def test_clock_advance_zero_periods_rejected(api):
    """PRD §2.5: "Advancing the clock takes a single input, `by_periods`, which must
    be an integer of at least 1; any value below 1 or of the wrong type is rejected
    with `ERR_INVALID_CLOCK_ADVANCE`."

    Design: Corner/endpoints/clock_advance_zero_periods_returns_invalid_clock_advance
    """
    from test_helpers import create_community
    community = create_community(name="ClkZero")
    resp = api_client.advance_clock(community["id"], {"by_periods": 0}, FO)
    validate_error(resp, ApiErrorId.ERR_INVALID_CLOCK_ADVANCE.value)
