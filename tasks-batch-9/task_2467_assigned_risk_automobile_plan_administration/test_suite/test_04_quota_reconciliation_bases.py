"""Quota reconciliation: the headcount basis and the earned-exposure basis diverge."""
from test_helpers import (
    ATLAS,
    BEACON,
    accept_assignment,
    api_client,
    assert_quota_reconciliation,
    assert_targets_sum_to_assignable_total,
    assignment_for_application,
    bootstrap_plan,
    bring_application_to_certified,
    create_quota_reconciliation_payload,
    issue_policy,
    make_plan_administrator_headers,
    read_carrier,
    read_plan_period,
    read_quota_reconciliation,
    run_cycle,
    schedule_cycle,
    set_clock,
    validate_success,
)

ADMIN_HEADERS = make_plan_administrator_headers()

# Two carriers on identical market shares, licensed in disjoint territories, so
# the T02 risks can only go to Atlas and the T01 risk can only go to Beacon.
ATLAS_T02 = dict(ATLAS, voluntary_market_share_bps=5000, licensed_territories=["T02"])
BEACON_T01 = dict(BEACON, voluntary_market_share_bps=5000, licensed_territories=["T01"])


def _period_in_reconciliation_with_late_and_early_exposure():
    """Three certified risks, two placed with Atlas and one with Beacon.

    Atlas issues one policy effective 2026-11-24 — six days of exposure inside the
    period window — and leaves its second assignment accepted but unissued.
    Beacon issues one policy effective 2026-09-01, worth ninety days. The period
    is then closed to reconciliation at a clock of 2026-11-30.
    """
    env = bootstrap_plan(carriers=[ATLAS_T02, BEACON_T01])
    atlas, beacon = env["carriers"]
    late_one = bring_application_to_certified(
        env,
        applicant_overrides={"full_name": "Rosa Vance", "driver_license_number": "D-99001",
                             "territory_code": "T02"},
        vehicle_overrides={"vin": "1HGCM82633A004352"},
        application_overrides={"requested_effective_date": "2026-11-24T00:00:00Z"},
        document_prefix="DEC-30",
    )
    late_two = bring_application_to_certified(
        env,
        applicant_overrides={"full_name": "Dale Ortiz", "driver_license_number": "D-99002",
                             "territory_code": "T02"},
        vehicle_overrides={"vin": "1HGCM82633A004353"},
        application_overrides={"requested_effective_date": "2026-11-24T00:00:00Z"},
        document_prefix="DEC-31",
    )
    early = bring_application_to_certified(
        env,
        applicant_overrides={"full_name": "Iris Chan", "driver_license_number": "D-99003",
                             "territory_code": "T01"},
        vehicle_overrides={"vin": "1HGCM82633A004354"},
        application_overrides={"requested_effective_date": "2026-09-01T00:00:00Z"},
        document_prefix="DEC-32",
    )
    cycle = schedule_cycle(env["plan_period"]["id"])
    run_cycle(cycle["id"])
    late_one_assignment = assignment_for_application(late_one["application"]["id"])
    late_two_assignment = assignment_for_application(late_two["application"]["id"])
    early_assignment = assignment_for_application(early["application"]["id"])
    accept_assignment(late_one_assignment["id"], late_one_assignment["carrier_id"])
    accept_assignment(late_two_assignment["id"], late_two_assignment["carrier_id"])
    accept_assignment(early_assignment["id"], early_assignment["carrier_id"])

    issue_policy(early_assignment["id"], early_assignment["carrier_id"],
                 policy_number="AR-100003",
                 effective_date="2026-09-01T00:00:00Z",
                 expiration_date="2027-09-01T00:00:00Z")
    set_clock("2026-11-24T00:00:00Z")
    issue_policy(late_one_assignment["id"], late_one_assignment["carrier_id"],
                 policy_number="AR-100001",
                 effective_date="2026-11-24T00:00:00Z",
                 expiration_date="2027-11-24T00:00:00Z")
    set_clock("2026-11-30T00:00:00Z")
    validate_success(api_client.close_plan_period(env["plan_period"]["id"], ADMIN_HEADERS))
    return env, atlas, beacon


def test_the_headcount_basis_reconciles_a_carrier_that_took_its_whole_target_to_zero():
    """On POLICY_COUNT the obligation is the target and the credit is the live headcount.

    Atlas holds a target of two assigned risks and is servicing exactly two, with
    no voluntary credit, so the headcount measure produces an obligation of 2, a
    credit of 2, a variance of 0 and no penalty at all.

    PRD: "On the `POLICY_COUNT` basis — the plan's headcount measure —
    `obligation_units` is simply the carrier's `quota_target_units`, a whole
    number, and `credited_units` is the carrier's live `assigned_risk_count` plus
    its `voluntary_credit_units`, carried to 1 decimal place because voluntary
    credit is granted in halves."
    Design: Difficulty/dual_variant_calc/quota_variance_policy_count_versus_car_year_basis_divergence
    """
    env, atlas, _ = _period_in_reconciliation_with_late_and_early_exposure()
    period = read_plan_period(env["plan_period"]["id"])
    atlas_before = read_carrier(atlas["id"])
    assert period["total_assignable_units"] == 3
    assert atlas_before["quota_target_units"] == 2
    assert atlas_before["assigned_risk_count"] == 2
    assert_targets_sum_to_assignable_total(
        [read_carrier(c["id"]) for c in env["carriers"]], period)

    filing = validate_success(api_client.create_quota_reconciliation(
        create_quota_reconciliation_payload(atlas["id"], env["plan_period"]["id"],
                                            "POLICY_COUNT", atlas_before["version"]),
        ADMIN_HEADERS), 201)

    assert_quota_reconciliation(filing)
    assert filing["obligation_units"] == 2
    assert filing["credited_units"] == 2
    assert filing["variance_units"] == 0
    assert filing["penalty_cents"] == 0
    assert filing["status"] == "FINAL"
    assert read_carrier(atlas["id"])["penalty_balance_cents"] == 0


def test_the_car_year_basis_finds_the_same_carrier_deficient_and_supersedes_the_headcount_row():
    """On CAR_YEAR_EXPOSURE the same carrier and period reconcile to a penalty.

    Atlas wrote its second risk only six days before the window closed, so its
    earned exposure is 0.0164 car-years against an obligation of 0.2630 multiplied
    by its half share, which is 0.1315. The shortfall of 0.1151 units costs 25000
    cents per unit and rounds half up to a penalty of 2878 cents. Filing the second
    basis supersedes the headcount row, which stops counting toward the balance.

    PRD: "Because exposure is earned over time, a carrier that took its full
    headcount late in the period is still deficient on this basis: on the same
    figures a carrier can reconcile to a variance of 0 and no penalty on
    `POLICY_COUNT` while showing a variance of -0.1151 and a penalty of 2878 cents
    on `CAR_YEAR_EXPOSURE`."
    Design: Difficulty/dual_variant_calc/quota_variance_policy_count_versus_car_year_basis_divergence
    """
    env, atlas, _ = _period_in_reconciliation_with_late_and_early_exposure()
    period = read_plan_period(env["plan_period"]["id"])
    assert period["total_assignable_car_years"] == 0.2630

    headcount_filing = validate_success(api_client.create_quota_reconciliation(
        create_quota_reconciliation_payload(atlas["id"], env["plan_period"]["id"],
                                            "POLICY_COUNT",
                                            read_carrier(atlas["id"])["version"]),
        ADMIN_HEADERS), 201)
    exposure_filing = validate_success(api_client.create_quota_reconciliation(
        create_quota_reconciliation_payload(atlas["id"], env["plan_period"]["id"],
                                            "CAR_YEAR_EXPOSURE",
                                            read_carrier(atlas["id"])["version"]),
        ADMIN_HEADERS), 201)

    assert exposure_filing["obligation_units"] == 0.1315
    assert exposure_filing["credited_units"] == 0.0164
    assert exposure_filing["variance_units"] == -0.1151
    assert exposure_filing["penalty_cents"] == 2878
    assert read_quota_reconciliation(headcount_filing["id"])["status"] == "SUPERSEDED"
    assert read_quota_reconciliation(exposure_filing["id"])["status"] == "FINAL"
    assert read_carrier(atlas["id"])["penalty_balance_cents"] == 2878
    assert read_plan_period(env["plan_period"]["id"])["status"] == "RECONCILING"
