"""Dual-variant calculations: estimate vs final DA accounting; forward vs
cash principal exposure."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId,
    set_clock, create_principal, create_port_call, create_da_for_call,
    add_manual_line, send_da_and_fund, drive_call_to_alongside, sail_call,
    make_agency_ops_headers, make_agency_finance_headers,
    make_port_authority_headers,
)
from test_helpers.factories import create_tariff_payload
from test_helpers.api_client import api_client


# ---------------------------------------------------------------------------
# Queue A: dual_variant_calc / da_estimate_vs_final_tariff_supersede
# ---------------------------------------------------------------------------

def _setup_tariff_supersede_scenario():
    """Call SINGA GT 30000 hazmat, eta 2026-06-10T20:00Z (night), etd
    2026-06-13T01:00Z (53h -> 3 estimated days). Tariff v1 pinned on the DA
    line; tariff v2 published after DA creation. Call driven to ALONGSIDE and
    DA funded via 250000 advance."""
    set_clock("2026-05-01T00:00:00Z")
    principal = create_principal(name="Apex Shipping", credit_limit_cents=0)
    pc = create_port_call(
        principal["id"], vessel_name="MV Meridian", imo_number="9074729",
        vessel_gt=30000, flag_state="PA", port_code="SINGA",
        eta="2026-06-10T20:00:00Z", etd="2026-06-13T01:00:00Z",
        cargo_description="grain containers", hazmat_flag=True)
    tar_v1 = get_success_data(api_client.create_tariff(
        create_tariff_payload(gt_tiers=[
            {"gt_up_to": 20000, "rate_cents": 2.0},
            {"gt_up_to": None, "rate_cents": 1.5},
        ]), make_port_authority_headers()))
    da = create_da_for_call(pc)
    tar_v2 = get_success_data(api_client.create_tariff(
        create_tariff_payload(
            effective_from="2026-05-15T00:00:00Z", night_surcharge_pct=0.30,
            gt_tiers=[
                {"gt_up_to": 20000, "rate_cents": 2.2},
                {"gt_up_to": None, "rate_cents": 1.6},
            ]), make_port_authority_headers()))
    pc, bw = drive_call_to_alongside(pc, berth_code="B1")
    da, adv = send_da_and_fund(da["id"], 250000)
    lines, _ = validate_paginated(api_client.list_da_lines(da["id"], make_agency_ops_headers()))
    pd_line = lines[0]
    return pc, bw, da, tar_v1, tar_v2, pd_line


def test_da_estimate_pinned_final_recomputed_under_superseding_tariff(api):
    """PRD §2.10: "Supersession is not retroactive: disbursement-account lines
    that were estimated against an earlier publication keep their pinned
    `tariff_id` and their computed estimate, and only future estimates and
    final actualizations price against the newly published tariff."
    PRD §3.8: "the final variant, applied at sailing, prices against the
    tariff `PUBLISHED` at sailing time even if it supersedes the pinned one,
    so identical call data can legitimately produce different estimate and
    final figures when a tariff was republished mid-call or the actual
    duration differs from the projection."

    Design: Difficulty/dual_variant_calc/da_estimate_vs_final_tariff_supersede
    """
    pc, bw, da, tar_v1, tar_v2, pd_line = _setup_tariff_supersede_scenario()
    # Estimated under v1: base/day = 20000*2.0 + 10000*1.5 = 55000; 3 days =
    # 165000; night 0.25 -> 41250; hazmat 0.40 -> 66000; total 272250.
    assert pd_line["estimated_cents"] == 272250, (
        f"ESTIMATE variant under pinned v1; got {pd_line['estimated_cents']}")
    assert pd_line["tariff_id"] == tar_v1["id"]
    # Sail at 2026-06-13T23:00 (arrival was 2026-06-10T21:00): actual 74h -> 4 days.
    pc = sail_call(pc, bw)
    assert pc["ops_status"] == "SAILED"
    assert pc["alongside_days_actual"] == 4
    line = [l for l in validate_paginated(
        api_client.list_da_lines(da["id"], make_agency_ops_headers()))[0]
        if l["id"] == pd_line["id"]][0]
    # Final under v2: base/day = 20000*2.2 + 10000*1.6 = 60000; 4 days =
    # 240000; night 0.30 -> 72000; hazmat 0.40 -> 96000; total 408000.
    assert line["actual_cents"] == 408000, (
        f"FINAL variant under superseding v2 with actual days; got {line['actual_cents']}")
    assert line["status"] == "ACTUALIZED"
    # Estimate stays pinned even though v1 is now SUPERSEDED.
    assert line["estimated_cents"] == 272250
    tar_v1_now = validate_success(api_client.get_tariff(tar_v1["id"], make_agency_ops_headers()))
    assert tar_v1_now["status"] == "SUPERSEDED"


def test_da_estimated_totals_and_berth_release_on_sailing(api):
    """PRD §3.3: "A recorded sailing cascades through three links. First, the
    referenced berth window transitions to `RELEASED` with `released_at`
    stamped from the clock. Second, the account's `PORT_DUES` line actualizes
    through the final variant of the port-dues calculation of §3.8 — priced
    from the actual timestamps and from the tariff `PUBLISHED` at sailing
    time — and the line moves to `ACTUALIZED`. Third, the account's totals
    are recomputed."

    Design: Difficulty/dual_variant_calc/da_estimate_vs_final_tariff_supersede
    """
    pc, bw, da, tar_v1, tar_v2, pd_line = _setup_tariff_supersede_scenario()
    da = validate_success(api_client.get_disbursement_account(da["id"], make_agency_ops_headers()))
    # fee on 272250 = round_half_up(6806.25) = 6806; total = 279056
    assert da["total_estimated_cents"] == 279056, (
        f"272250 + per-line fee 6806; got {da['total_estimated_cents']}")
    pc = sail_call(pc, bw)
    bw_now = validate_success(api_client.get_berth_window(bw["id"], make_agency_ops_headers()))
    assert bw_now["status"] == "RELEASED"
    assert bw_now.get("released_at"), "released_at stamped from the clock"


# ---------------------------------------------------------------------------
# Queue A: dual_variant_calc / principal_exposure_forward_vs_cash
# ---------------------------------------------------------------------------

def _setup_exposure_scenario():
    """Principal credit limit 1000000; DA with two SUNDRY lines 60000 + 40000
    (fee 2500; total 102500; advance_required 82000); funded at exactly 82000,
    then 20000 applied."""
    set_clock("2026-05-01T00:00:00Z")
    principal = create_principal(
        name="Borealis Lines", contact_email="fin@borealis.example",
        credit_limit_cents=1000000)
    pc = create_port_call(
        principal["id"], vessel_name="SS Taiga", imo_number="9000002",
        vessel_gt=5000, flag_state="NO", port_code="NODUE",
        eta="2026-06-01T10:00:00Z", etd="2026-06-02T10:00:00Z")
    da = create_da_for_call(pc)
    add_manual_line(da["id"], 60000, description="line a")
    add_manual_line(da["id"], 40000, description="line b")
    da, adv = send_da_and_fund(da["id"], 82000)
    get_success_data(api_client.apply_funding_advance(
        adv["id"], {"amount_cents": 20000}, make_agency_finance_headers()))
    return principal, pc, da, adv


def test_principal_exposure_forward_variant_counts_estimate(api):
    """PRD §3.1: "The **forward-looking** variant counts each account at
    `total_final_cents` when the account is `FINAL`, `DISPUTED`, or `SETTLED`,
    and at `total_estimated_cents` while it is still `PRO_FORMA`,
    `SENT_TO_PRINCIPAL`, or `FUNDED` — money not yet received still counts as
    exposure; the sum is reported as `forward_exposure_cents`."

    Design: Difficulty/dual_variant_calc/principal_exposure_forward_vs_cash
    """
    principal, pc, da, adv = _setup_exposure_scenario()
    da_now = validate_success(api_client.get_disbursement_account(da["id"], make_agency_finance_headers()))
    assert da_now["status"] == "FUNDED", "82000 received >= 82000 required"
    exposure = validate_success(api_client.get_principal_exposure(
        principal["id"], make_agency_finance_headers()))
    assert exposure["forward_exposure_cents"] == 102500, (
        f"pre-final account counts at total_estimated_cents; got {exposure['forward_exposure_cents']}")
    assert exposure["credit_headroom_cents"] == 897500


def test_principal_exposure_cash_basis_counts_applied_only(api):
    """PRD §3.1: "The **cash-basis** variant counts each account at
    `advances_applied_cents` alone while the account is pre-final"; "Consider
    an account estimated at 100000 cents with 20000 cents applied: it
    contributes 100000 to the forward figure but only 20000 to the cash-basis
    figure."

    Design: Difficulty/dual_variant_calc/principal_exposure_forward_vs_cash
    """
    principal, pc, da, adv = _setup_exposure_scenario()
    exposure = validate_success(api_client.get_principal_exposure(
        principal["id"], make_agency_finance_headers()))
    assert exposure["cash_basis_exposure_cents"] == 20000, (
        f"cash-basis counts advances_applied only; got {exposure['cash_basis_exposure_cents']}")
