"""Identities that must hold exactly, checked across the operations most likely to drift."""

from test_helpers import *  # noqa: F401,F403


# ---------------------------------------------------------------------------
# The advance ledger survives an audit reversal, with the cap read at the start
# ---------------------------------------------------------------------------


def _accepted_quarter_restated_upward():
    """One accepted quarter worth 500 000 of royalty, restated to 525 000 by audit.

    The advance is 1 000 000 against a 4 000 000 guarantee, so nothing is ever fully
    recouped and every posting is visible in the ledger.
    """
    context = setup_licensed_operation(
        minimum_guarantee_cents=4000000,
        required_advance_cents=1000000,
        central_licensing_flag=False,
    )
    licensee_id = context["licensee"]["id"]

    lines = simple_report_lines(context["authorization"]["id"], 6250000, units=12500)
    report = create_report(context["agreement"]["id"], "2026Q2", lines, licensee_id)
    file_report(report["id"], licensee_id)
    context["report"] = accept_report(report["id"])

    posted = get_agreement(context["agreement"]["id"])
    assert posted["unrecouped_advance_cents"] == 500000
    assert posted["recouped_advance_cents"] == 500000
    assert posted["cumulative_royalty_cents"] == 500000
    assert_advance_ledger_conserved(posted)

    # One seizure is on file, which is 15 points on its own — below every band.
    create_seizure_factor(licensee_id)

    engagement = create_audit_engagement(context["agreement"]["id"], ["2026Q2"])
    begin_fieldwork(engagement["id"])
    context["engagement"] = issue_findings(
        engagement["id"], [audited_quarter("2026Q2", 6562500)]
    )
    return context


def test_the_settlement_reversal_recoups_on_the_cap_in_force_at_the_start(api):
    """PRD §3.8: "then steps two through six of the payable waterfall re-run with the
    adjusted royalty in place of the original, using the `compliance_posture` in force at the
    start of the settle transition to choose the recoupment cap, and the resulting posting is
    applied."

    Design: Difficulty/compensating_invariant/advance_ledger_conserved_across_audit_reversal_with_cap_read_at_start
    """
    context = _accepted_quarter_restated_upward()
    agreement_id = context["agreement"]["id"]

    assert get_agreement(agreement_id)["compliance_posture"] == "CLEAR"

    settled = settle_engagement(context["engagement"]["id"])
    assert settled["status"] == "SETTLED"

    adjusted = get_report(context["report"]["id"])
    assert adjusted["status"] == "ADJUSTED"
    assert adjusted["adjusted_royalty_due_cents"] == 525000
    # The posture reached PROBATION inside this very request, but the cap stayed at
    # 10000 bps, so the whole adjusted royalty is recouped instead of half of it.
    assert adjusted["recoupment_applied_cents"] == 525000
    assert adjusted["cash_due_pre_fee_cents"] == 0

    agreement = get_agreement(agreement_id)
    assert agreement["compliance_posture"] == "PROBATION"
    assert agreement["advance_paid_cents"] == 1000000
    assert agreement["unrecouped_advance_cents"] == 475000
    assert agreement["recouped_advance_cents"] == 525000
    assert agreement["cumulative_royalty_cents"] == 525000
    assert_advance_ledger_conserved(agreement)
    assert get_licensee(context["licensee"]["id"])["compliance_risk_index"] == 35


def test_the_next_acceptance_uses_the_probation_cap_and_still_conserves_the_ledger(api):
    """PRD §3.7: "Step two determines the recoupment cap from the agreement's
    `compliance_posture` as it stands at the start of the triggering transition — a posture
    change cascaded by the very same request does not retroactively alter the cap: the cap is
    5000 basis points of the royalty when that posture is `PROBATION` or `FROZEN` and 10000
    basis points otherwise."

    Design: Difficulty/compensating_invariant/advance_ledger_conserved_across_audit_reversal_with_cap_read_at_start
    """
    context = _accepted_quarter_restated_upward()
    agreement_id = context["agreement"]["id"]
    licensee_id = context["licensee"]["id"]

    settle_engagement(context["engagement"]["id"])
    assert get_agreement(agreement_id)["compliance_posture"] == "PROBATION"

    lines = simple_report_lines(context["authorization"]["id"], 6250000, units=12500)
    late = create_report(agreement_id, "2026Q1", lines, licensee_id)
    filed = file_report(late["id"], licensee_id)

    assert filed["royalty_due_cents"] == 500000
    # Half the royalty is the most that may be recouped under probation.
    assert filed["recoupment_applied_cents"] == 250000
    assert filed["cash_due_pre_fee_cents"] == 250000
    # 2026-03-31 plus forty-five days is 2026-05-15, and the clock stands at 2026-08-01.
    assert filed["late_days"] == 78
    assert filed["late_filing_interest_cents"] == 9750
    assert filed["admin_fee_cents"] == 0
    assert filed["total_payable_cents"] == 259750

    unmoved = get_agreement(agreement_id)
    assert unmoved["unrecouped_advance_cents"] == 475000
    assert unmoved["recouped_advance_cents"] == 525000
    assert unmoved["cumulative_royalty_cents"] == 525000
    assert_advance_ledger_conserved(unmoved)

    accept_report(late["id"])

    agreement = get_agreement(agreement_id)
    assert agreement["unrecouped_advance_cents"] == 225000
    assert agreement["recouped_advance_cents"] == 775000
    assert agreement["cumulative_royalty_cents"] == 1025000
    assert agreement["advance_paid_cents"] == 1000000
    assert_advance_ledger_conserved(agreement)


# ---------------------------------------------------------------------------
# The central pool is split exactly, with the lost cents handed back
# ---------------------------------------------------------------------------


def _locked_run_over_two_central_reports():
    """A 2026Q2 pool of 1 000 003 cents facing three clubs weighted 5 / 3 / 2.

    The odd total is deliberate: every stage of the waterfall loses fractions of a cent.
    """
    clubs = create_clubs(
        [
            {"club_code": "ATL", "market_name": "Atlanta", "revenue_share_units": 5},
            {"club_code": "BOS", "market_name": "Boston", "revenue_share_units": 3},
            {"club_code": "CHI", "market_name": "Chicago", "revenue_share_units": 2},
        ]
    )
    category = create_jersey_category()
    # The run is opened first so that each acceptance is pooled into it.
    run = create_distribution_run("2026Q2", league_admin_rate_bps=800)

    reports = []
    specs = (("Lakeside Apparel", 6250000, 500000), ("Ridgeway Athletic", 6250037, 500003))
    for index, spec in enumerate(specs):
        legal_name, gross_sales_cents, expected_royalty = spec
        licensee = create_active_licensee(
            legal_name=legal_name, contact_email="royalties%d@central.example" % index
        )
        agreement_context = setup_active_agreement(
            category=category,
            licensee=licensee,
            minimum_guarantee_cents=1000000,
            required_advance_cents=250000,
            central_licensing_flag=True,
        )
        authorization = create_authorized_retailer_authorization(
            licensee["id"], retailer_name="Metro Sports %d" % index
        )
        lines = simple_report_lines(authorization["id"], gross_sales_cents, units=12500)
        report = create_report(
            agreement_context["agreement"]["id"], "2026Q2", lines, licensee["id"]
        )
        file_report(report["id"], licensee["id"])
        accepted = accept_report(report["id"])
        assert accepted["royalty_due_cents"] == expected_royalty
        reports.append(accepted)

    locked = lock_run(run["id"])
    assert locked["status"] == "LOCKED"
    assert locked["projected_pool_cents"] == 1000003
    assert locked["report_count"] == 2
    return {"clubs": clubs, "reports": reports, "run": locked}


def test_the_waterfall_splits_the_pool_without_losing_a_cent(api):
    """PRD §2.10: "On a completed `DistributionRun`, the sum of `amount_cents` over its club
    distribution rows, plus `player_pool_cents`, plus `league_admin_cents`, exactly equals
    `pool_gross_cents`."

    Design: Difficulty/compensating_invariant/central_pool_conserved_exactly_by_largest_remainder_split
    """
    context = _locked_run_over_two_central_reports()

    distributed = distribute_run(context["run"]["id"])
    assert distributed["status"] == "DISTRIBUTED"
    assert distributed["report_count"] == 2
    assert distributed["pool_gross_cents"] == 1000003
    # 1 000 003 * 800 / 10000 is 80 000.24, which rounds half up to 80 000.
    assert distributed["league_admin_cents"] == 80000
    # Both categories carry player marks, so the whole pool is the player basis:
    # 1 000 003 * 2500 / 10000 is 250 000.75, which rounds half up to 250 001.
    assert distributed["player_pool_cents"] == 250001
    assert distributed["club_pool_cents"] == 670002

    rows, meta = validate_paginated(
        list_club_distributions({"run_id": context["run"]["id"]})
    )
    assert meta["total_count"] == 3
    assert_distribution_pool_conserved(distributed, rows)


def test_the_largest_remainder_method_hands_the_lost_cents_to_the_top_fractions(api):
    """PRD §3.9: "Clubs are ranked by the fractional part of their exact raw share,
    descending, with ties broken by ascending `club_code` and never by identifier; the first
    as many clubs as there are remainder cents each receive `remainder_cent_applied` of 1 and
    every other club 0."

    Design: Difficulty/compensating_invariant/central_pool_conserved_exactly_by_largest_remainder_split
    """
    context = _locked_run_over_two_central_reports()

    distributed = distribute_run(context["run"]["id"])
    rows, _ = validate_paginated(
        list_club_distributions({"run_id": context["run"]["id"]})
    )
    by_code = {row["club_code"]: row for row in rows}
    assert set(by_code) == {"ATL", "BOS", "CHI"}

    # Equal total floor(670 002 * 7500 / 10000) is 502 501, leaving 167 501 to weight,
    # and each club's exact equal share is 502 501 / 3 = 167 500.333...
    for code in ("ATL", "BOS", "CHI"):
        assert by_code[code]["equal_component_cents"] == 167500
    assert by_code["ATL"]["weighted_component_cents"] == 83750
    assert by_code["BOS"]["weighted_component_cents"] == 50250
    assert by_code["CHI"]["weighted_component_cents"] == 33500

    # Raw fractions are .8333 for ATL, .6333 for BOS and .5333 for CHI, and exactly two
    # cents were lost to flooring.
    assert by_code["ATL"]["remainder_cent_applied"] == 1
    assert by_code["BOS"]["remainder_cent_applied"] == 1
    assert by_code["CHI"]["remainder_cent_applied"] == 0

    assert by_code["ATL"]["amount_cents"] == 251251
    assert by_code["BOS"]["amount_cents"] == 217751
    assert by_code["CHI"]["amount_cents"] == 201000
    assert sum(row["amount_cents"] for row in rows) == distributed["club_pool_cents"]

    assert by_code["ATL"]["revenue_share_units_snapshot"] == 5
    for code in ("ATL", "BOS", "CHI"):
        assert_club_distribution_components(by_code[code])
