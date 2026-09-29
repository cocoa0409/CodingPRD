"""Campaign shrinkage accounting, the employer gate on opening, and the
half-open solicitation window exclusivity of one employer.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_client import api_client
from test_helpers.api_errors import (
    ERR_CAMPAIGN_WINDOW_OVERLAP,
    ERR_EMPLOYER_NOT_ACTIVE,
)
from test_helpers.assertions import assert_bps, assert_is_null, assert_money
from test_helpers.factories import campaign_payload, pledge_payload, write_off_payload
from test_helpers.fixtures import (
    create_active_employer,
    create_campaign,
    create_employer,
    create_open_campaign,
)
from test_helpers.test_users import make_admin_headers, make_finance_reviewer_headers


def _shrinkage_scenario():
    """Three CONFIRMED payroll pledges of 600.00, 500.00 and 400.00, in that order."""
    employer = create_active_employer(
        legal_name="Northgate Manufacturing",
        employee_count=400,
        payroll_periods_per_year=26,
        historical_shrinkage_rate_bps=800,
    )
    _, campaign = create_open_campaign(
        employer["id"],
        solicitation_start_date="2026-07-01",
        solicitation_end_date="2026-09-30",
        loss_reserve_amount="1000.00",
    )
    admin = make_admin_headers()
    pledge_ids = []
    for reference, gross in (("D-001", "600.00"), ("D-002", "500.00"), ("D-003", "400.00")):
        pledge = validate_success(
            api_client.create_pledge(
                campaign["id"],
                pledge_payload(
                    donor_reference=reference,
                    giving_method="PAYROLL_DEDUCTION",
                    gross_amount=gross,
                ),
                admin,
            ),
            201,
        )
        pledge_ids.append(pledge["id"])
    for pledge_id in pledge_ids:
        validate_success(api_client.confirm_pledge(pledge_id, admin))
    return employer, campaign, pledge_ids


def test_provisional_estimate_uses_the_employer_rate_and_ignores_the_reserve():
    """PRD 3.5: "`provisional_estimated_loss` is then that projected total multiplied
    by the employer's `historical_shrinkage_rate_bps` divided by 10000, rounded half
    up to two decimal places; the campaign's own `loss_reserve_amount` is ignored
    entirely at this stage."

    Design: Difficulty/dual_variant_calc/campaign_shrinkage_provisional_vs_final_loss_divergence
    """
    _, campaign, _ = _shrinkage_scenario()
    admin = make_admin_headers()

    closed = validate_success(api_client.close_campaign_solicitation(campaign["id"], admin))

    assert closed["posture"] == "SOLICITATION_CLOSED"
    assert_money(closed["confirmed_gross_total"], "1500.00", "confirmed_gross_total")
    assert_money(
        closed["projected_payroll_pledge_total"], "1500.00", "projected_payroll_pledge_total"
    )
    assert_money(closed["provisional_estimated_loss"], "120.00", "provisional_estimated_loss")
    assert_money(
        closed["provisional_net_expected_revenue"],
        "1380.00",
        "provisional_net_expected_revenue",
    )
    assert closed["solicitation_closed_at"] is not None, "solicitation_closed_at is stamped"
    assert_is_null(closed["reserve_absorbed_amount"], "reserve_absorbed_amount")
    assert_is_null(closed["final_actual_loss"], "final_actual_loss")
    assert_is_null(closed["final_net_expected_revenue"], "final_net_expected_revenue")
    assert_is_null(closed["realized_shrinkage_rate_bps"], "realized_shrinkage_rate_bps")
    assert_is_null(closed["reconciled_at"], "reconciled_at")


def test_final_loss_absorbs_whole_uncollected_amounts_in_the_pinned_walk_order():
    """PRD 3.5: "Starting with the whole `loss_reserve_amount` available, each
    candidate pledge in that order is tested against the reserve remaining: if the
    pledge's `uncollected_amount` is less than or equal to the reserve remaining, the
    whole amount is absorbed, the reserve remaining is reduced by it, and the running
    absorbed total grows by it; otherwise the pledge is skipped in its entirety — no
    partial draw is ever taken — and the walk continues, so a later and smaller
    pledge may still be absorbed after a larger one was skipped."

    The 600.00 pledge is absorbed, the 500.00 pledge no longer fits the 400.00
    remaining and is skipped whole, and the 400.00 pledge is absorbed exactly.

    Design: Difficulty/dual_variant_calc/campaign_shrinkage_provisional_vs_final_loss_divergence
    """
    _, campaign, pledge_ids = _shrinkage_scenario()
    admin = make_admin_headers()
    finance = make_finance_reviewer_headers()

    validate_success(api_client.close_campaign_solicitation(campaign["id"], admin))
    for pledge_id in pledge_ids:
        validate_success(
            api_client.write_off_pledge(pledge_id, write_off_payload("TERMINATION"), finance)
        )

    reconciled = validate_success(api_client.reconcile_campaign(campaign["id"], admin))

    assert_money(reconciled["reserve_absorbed_amount"], "1000.00", "reserve_absorbed_amount")
    assert_money(reconciled["final_actual_loss"], "500.00", "final_actual_loss")
    assert_money(
        reconciled["final_net_expected_revenue"], "1000.00", "final_net_expected_revenue"
    )
    assert_bps(reconciled["realized_shrinkage_rate_bps"], 3333, "realized_shrinkage_rate_bps")
    assert_money(
        reconciled["provisional_estimated_loss"], "120.00", "provisional_estimated_loss"
    )
    assert reconciled["provisional_estimated_loss"] != reconciled["final_actual_loss"], (
        "the two variants must disagree on identical data: 120.00 against 500.00"
    )
    assert reconciled["reconciled_at"] is not None, "reconciled_at is stamped"
    for pledge_id in pledge_ids:
        pledge = validate_success(api_client.get_pledge(pledge_id, admin))
        assert pledge["designation_status"] == "LOCKED", "reconciliation locks the pledge"


def test_realized_shrinkage_at_or_above_the_threshold_forks_to_escrow_hold():
    """PRD 3.5: "When it is 1500 or more, the boundary value 1500 itself counting as
    severe, the campaign lands in `SOLICITATION_CLOSED → ESCROW_HOLD` and the
    escrow-hold cascade fires: the host employer is forced `ACTIVE → SUSPENDED` with
    `suspended_reason` set to `ESCROW_HOLD_SHRINKAGE`, and every coordinator seated
    at that employer flips `ACTIVE → INACTIVE`."

    Design: Difficulty/dual_variant_calc/campaign_shrinkage_provisional_vs_final_loss_divergence
    """
    employer, campaign, pledge_ids = _shrinkage_scenario()
    admin = make_admin_headers()
    finance = make_finance_reviewer_headers()

    validate_success(api_client.close_campaign_solicitation(campaign["id"], admin))
    for pledge_id in pledge_ids:
        validate_success(
            api_client.write_off_pledge(pledge_id, write_off_payload("TERMINATION"), finance)
        )

    reconciled = validate_success(api_client.reconcile_campaign(campaign["id"], admin))

    assert reconciled["posture"] == "ESCROW_HOLD", "3333 bps is severe"
    reread = validate_success(api_client.get_employer(employer["id"], admin))
    assert reread["status"] == "SUSPENDED"
    assert reread["suspended_reason"] == "ESCROW_HOLD_SHRINKAGE"


def test_opening_a_planned_campaign_of_a_prospect_employer_is_refused():
    """PRD 3.2: "An employer still in `PROSPECT`, or already `SUSPENDED`, blocks the
    opening with `ERR_EMPLOYER_NOT_ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/campaign_open_gated_by_employer_partnership_status
    """
    admin = make_admin_headers()
    employer = create_employer(
        legal_name="Silverpoint Credit Union",
        employee_count=260,
        payroll_periods_per_year=24,
        historical_shrinkage_rate_bps=400,
    )
    campaign = create_campaign(
        employer["id"],
        solicitation_start_date="2026-07-01",
        solicitation_end_date="2026-09-30",
        loss_reserve_amount="0.00",
    )
    assert employer["status"] == "PROSPECT", "the partnership was never countersigned"
    assert campaign["posture"] == "PLANNED", "the campaign is in the only openable posture"

    refused = api_client.open_campaign(campaign["id"], admin)
    validate_error(refused, ERR_EMPLOYER_NOT_ACTIVE, 409)

    reread_campaign = validate_success(api_client.get_campaign(campaign["id"], admin))
    assert reread_campaign["posture"] == "PLANNED", "the refusal left no trace"
    reread_employer = validate_success(api_client.get_employer(employer["id"], admin))
    assert reread_employer["active_campaign_count"] == 0, "nothing has opened yet"


def test_the_identical_open_succeeds_once_the_employer_alone_is_countersigned():
    """PRD 3.2: "Opening re-derives the employer's `active_campaign_count`."

    Nothing about the campaign changes between the refusal and the success: only
    the other entity moves `PROSPECT → ACTIVE`.

    Design: Difficulty/cross_entity_state_dependency/campaign_open_gated_by_employer_partnership_status
    """
    admin = make_admin_headers()
    employer = create_employer(
        legal_name="Silverpoint Credit Union",
        employee_count=260,
        payroll_periods_per_year=24,
        historical_shrinkage_rate_bps=400,
    )
    campaign = create_campaign(
        employer["id"],
        solicitation_start_date="2026-07-01",
        solicitation_end_date="2026-09-30",
        loss_reserve_amount="0.00",
    )
    validate_error(api_client.open_campaign(campaign["id"], admin), ERR_EMPLOYER_NOT_ACTIVE, 409)

    activated = validate_success(api_client.activate_employer(employer["id"], admin))
    assert activated["status"] == "ACTIVE"

    opened = validate_success(api_client.open_campaign(campaign["id"], admin))
    assert opened["posture"] == "OPEN", "the byte-identical call now succeeds"

    reread_employer = validate_success(api_client.get_employer(employer["id"], admin))
    assert reread_employer["active_campaign_count"] == 1, (
        "the counter starts counting only once the campaign actually opened"
    )

    pledge = validate_success(
        api_client.create_pledge(
            campaign["id"],
            pledge_payload(
                donor_reference="D-OPEN-1",
                giving_method="ONE_TIME_CHECK",
                gross_amount="100.00",
            ),
            admin,
        ),
        201,
    )
    assert pledge["designation_status"] == "DRAFT", "pledge recording is now reachable"


def _window_scenario():
    """EMP_A holds an OPEN campaign for [2026-07-01, 2026-09-30); EMP_B holds none."""
    employer_a = create_active_employer(
        legal_name="Granite State Mutual",
        employee_count=500,
        payroll_periods_per_year=26,
        historical_shrinkage_rate_bps=500,
    )
    _, campaign_a = create_open_campaign(
        employer_a["id"],
        solicitation_start_date="2026-07-01",
        solicitation_end_date="2026-09-30",
        loss_reserve_amount="0.00",
    )
    employer_b = create_active_employer(
        legal_name="Northwind Grocers",
        employee_count=310,
        payroll_periods_per_year=24,
        historical_shrinkage_rate_bps=800,
    )
    return employer_a, campaign_a, employer_b


def test_a_one_day_intersection_of_solicitation_windows_is_refused():
    """PRD 3.2: "The solicitation window is half-open — the start date belongs to the
    window and the end date does not — and a new campaign's window must not intersect
    the window of any other campaign of the same employer whose posture is anything
    other than `ESCROW_HOLD`."

    Design: Difficulty/resource_temporal_overlap/employer_campaign_windows_half_open_touching_endpoints_allowed
    """
    employer_a, _, _ = _window_scenario()
    admin = make_admin_headers()

    refused = api_client.create_campaign(
        campaign_payload(
            employer_a["id"],
            campaign_year=2027,
            solicitation_start_date="2026-09-29",
            solicitation_end_date="2026-12-31",
            loss_reserve_amount="0.00",
        ),
        admin,
    )
    validate_error(refused, ERR_CAMPAIGN_WINDOW_OVERLAP, 409)

    reread = validate_success(api_client.get_employer(employer_a["id"], admin))
    assert reread["active_campaign_count"] == 1, "no campaign row was created"
    _, meta = validate_paginated(api_client.list_employer_campaigns(employer_a["id"], admin))
    assert meta["total_count"] == 1, "the refused create left the roster untouched"


def test_touching_endpoints_are_allowed_and_the_window_rule_is_scoped_per_employer():
    """PRD 3.2: "Two half-open windows intersect when the new start falls strictly
    before the existing end **and** the existing start falls strictly before the new
    end; consequently, a new campaign starting on exactly the date an existing
    campaign ends does not intersect it and is accepted."

    Design: Difficulty/resource_temporal_overlap/employer_campaign_windows_half_open_touching_endpoints_allowed
    """
    employer_a, _, employer_b = _window_scenario()
    admin = make_admin_headers()

    touching = validate_success(
        api_client.create_campaign(
            campaign_payload(
                employer_a["id"],
                campaign_year=2027,
                solicitation_start_date="2026-09-30",
                solicitation_end_date="2026-12-31",
                loss_reserve_amount="0.00",
            ),
            admin,
        ),
        201,
    )
    assert touching["posture"] == "PLANNED"

    twin = validate_success(
        api_client.create_campaign(
            campaign_payload(
                employer_b["id"],
                campaign_year=2026,
                solicitation_start_date="2026-07-01",
                solicitation_end_date="2026-09-30",
                loss_reserve_amount="0.00",
            ),
            admin,
        ),
        201,
    )
    assert twin["employer_id"] == employer_b["id"], "the constraint is scoped per employer"

    _, meta_a = validate_paginated(api_client.list_employer_campaigns(employer_a["id"], admin))
    assert meta_a["total_count"] == 2
    _, meta_b = validate_paginated(api_client.list_employer_campaigns(employer_b["id"], admin))
    assert meta_b["total_count"] == 1


def test_fully_disjoint_windows_pass_while_a_single_overlapping_day_fails():
    """PRD 3.2: "An intersection is rejected with `ERR_CAMPAIGN_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/employer_campaign_windows_half_open_touching_endpoints_allowed
    """
    employer_a, _, _ = _window_scenario()
    admin = make_admin_headers()

    validate_success(
        api_client.create_campaign(
            campaign_payload(
                employer_a["id"],
                campaign_year=2027,
                solicitation_start_date="2026-09-30",
                solicitation_end_date="2026-12-31",
                loss_reserve_amount="0.00",
            ),
            admin,
        ),
        201,
    )
    validate_success(
        api_client.create_campaign(
            campaign_payload(
                employer_a["id"],
                campaign_year=2028,
                solicitation_start_date="2026-12-31",
                solicitation_end_date="2027-03-31",
                loss_reserve_amount="0.00",
            ),
            admin,
        ),
        201,
    )
    validate_error(
        api_client.create_campaign(
            campaign_payload(
                employer_a["id"],
                campaign_year=2029,
                solicitation_start_date="2026-12-30",
                solicitation_end_date="2027-03-31",
                loss_reserve_amount="0.00",
            ),
            admin,
        ),
        ERR_CAMPAIGN_WINDOW_OVERLAP,
        409,
    )
    _, meta = validate_paginated(api_client.list_employer_campaigns(employer_a["id"], admin))
    assert meta["total_count"] == 3, "only the three legal windows exist"
