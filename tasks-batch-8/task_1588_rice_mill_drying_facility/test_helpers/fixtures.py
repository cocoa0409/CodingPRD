"""Composite setup helpers.

Each function builds its preconditions from scratch against an empty database,
using only PRD-declared endpoints. Setup calls use the lenient get_success_data
validator so failures surface as clear "Setup step failed" errors.

Identity threading: GrowerRep headers are always built with the actual Grower id
via make_grower_rep_headers; clerk identity is threaded via make_clerk_headers
because settlement approval compares X-User-ID to created_by_user_id.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    ZERO_GRADE_ADJUSTMENTS,
    create_season_payload,
    create_grower_payload,
    create_contract_payload,
    create_bin_payload,
    create_spot_lot_payload,
    create_contract_lot_payload,
    grade_lot_payload,
    create_drying_run_payload,
    create_mill_run_payload,
    create_packaging_run_payload,
    create_byproduct_order_payload,
    create_fumigation_event_payload,
    create_hold_payload,
    create_settlement_payload,
)
from .test_users import TEST_USERS, make_grower_rep_headers, make_clerk_headers

ADMIN = TEST_USERS["mill_admin_headers"]
MERCH = TEST_USERS["merchandiser_headers"]
SCALE = TEST_USERS["scale_operator_headers"]
LAB = TEST_USERS["quality_lab_tech_headers"]
DRYER = TEST_USERS["dryer_operator_headers"]
SUPERVISOR = TEST_USERS["mill_supervisor_headers"]
CLERK1 = TEST_USERS["settlement_clerk_headers"]
CLERK2 = TEST_USERS["settlement_clerk_2_headers"]
SAFETY = TEST_USERS["safety_officer_headers"]
FUMTECH = TEST_USERS["fumigation_tech_headers"]


# ---------------------------------------------------------------------------
# Tier 1: state progression primitives
# ---------------------------------------------------------------------------

def create_season(name="2026 Fall", spot_daily_cap=2,
                  intake_start_date="2026-08-01", intake_end_date="2026-10-31") -> dict:
    """Create a harvest season (born SETUP with the fixed logical clock)."""
    resp = api_client.create_season(
        create_season_payload(
            name=name,
            spot_daily_cap=spot_daily_cap,
            intake_start_date=intake_start_date,
            intake_end_date=intake_end_date,
        ),
        ADMIN,
    )
    return get_success_data(resp)


def create_open_season(**kwargs) -> dict:
    """Create a season and open intake (SETUP -> INTAKE_OPEN)."""
    season = create_season(**kwargs)
    resp = api_client.open_intake(season["id"], ADMIN)
    return get_success_data(resp)


def close_intake(season_id: str) -> dict:
    return get_success_data(api_client.close_intake(season_id, ADMIN))


def set_clock(season_id: str, to_iso8601: str) -> dict:
    return get_success_data(
        api_client.set_clock(season_id, {"to_iso8601": to_iso8601}, ADMIN)
    )


def begin_settlement_review(season_id: str) -> dict:
    return get_success_data(api_client.begin_settlement_review(season_id, ADMIN))


def get_season(season_id: str) -> dict:
    return get_success_data(api_client.get_season(season_id, ADMIN))


# ---------------------------------------------------------------------------
# Tier 2: entity hierarchy primitives
# ---------------------------------------------------------------------------

def create_grower(season_id: str, farm_code="FARM-001", legal_name="Delta Farms",
                  advance_issued_cents=None) -> dict:
    overrides = {}
    if advance_issued_cents is not None:
        overrides["advance_issued_cents"] = advance_issued_cents
    resp = api_client.create_grower(
        create_grower_payload(season_id, farm_code=farm_code, legal_name=legal_name, **overrides),
        MERCH,
    )
    return get_success_data(resp)


def get_grower(grower_id: str) -> dict:
    return get_success_data(api_client.get_grower(grower_id, MERCH))


def create_contract(season_id: str, grower_id: str, contracted_cwt=400.00,
                    base_price_cents_per_cwt=1500, grade_adjustments=None,
                    variety="LONG_GRAIN") -> dict:
    resp = api_client.create_contract(
        create_contract_payload(
            season_id,
            grower_id,
            contracted_cwt=contracted_cwt,
            base_price_cents_per_cwt=base_price_cents_per_cwt,
            grade_adjustments=grade_adjustments or dict(ZERO_GRADE_ADJUSTMENTS),
            variety=variety,
        ),
        MERCH,
    )
    return get_success_data(resp)


def get_contract(contract_id: str) -> dict:
    return get_success_data(api_client.get_contract(contract_id, MERCH))


def create_bin(season_id: str, bin_code="B-01", capacity_cwt=500.00) -> dict:
    resp = api_client.create_bin(
        create_bin_payload(season_id, bin_code=bin_code, capacity_cwt=capacity_cwt),
        ADMIN,
    )
    return get_success_data(resp)


def get_bin(bin_id: str) -> dict:
    return get_success_data(api_client.get_bin(bin_id, ADMIN))


# ---------------------------------------------------------------------------
# Lots: intake, grading, storage
# ---------------------------------------------------------------------------

def create_spot_lot(season_id: str, grower_id: str, gross_weight_lbs=22000,
                    tare_weight_lbs=12000, scheduled_date="2026-08-10",
                    moisture_pct_handheld=13.0, spot_price_cents_per_cwt=1300,
                    variety="LONG_GRAIN") -> dict:
    resp = api_client.create_lot(
        create_spot_lot_payload(
            season_id,
            grower_id,
            gross_weight_lbs=gross_weight_lbs,
            tare_weight_lbs=tare_weight_lbs,
            scheduled_date=scheduled_date,
            moisture_pct_handheld=moisture_pct_handheld,
            spot_price_cents_per_cwt=spot_price_cents_per_cwt,
            variety=variety,
        ),
        SCALE,
    )
    return get_success_data(resp)


def create_contract_lot(season_id: str, grower_id: str, contract_id: str,
                        gross_weight_lbs=22000, tare_weight_lbs=12000,
                        scheduled_date="2026-08-10", moisture_pct_handheld=13.0,
                        variety="LONG_GRAIN") -> dict:
    """Book a contract lot; reads the contract's current version first so the
    OCC token expected_contract_version is always fresh (PRD §2.8)."""
    current = get_contract(contract_id)
    resp = api_client.create_lot(
        create_contract_lot_payload(
            season_id,
            grower_id,
            contract_id,
            current["version"],
            gross_weight_lbs=gross_weight_lbs,
            tare_weight_lbs=tare_weight_lbs,
            scheduled_date=scheduled_date,
            moisture_pct_handheld=moisture_pct_handheld,
            variety=variety,
        ),
        SCALE,
    )
    return get_success_data(resp)


def get_lot(lot_id: str) -> dict:
    return get_success_data(api_client.get_lot(lot_id, SCALE))


def grade_lot(lot_id: str, moisture_pct_official=13.0, foreign_matter_pct=0.2,
              damage_pct=0.2, broken_pct=0.6) -> dict:
    resp = api_client.grade_lot(
        lot_id,
        grade_lot_payload(
            moisture_pct_official=moisture_pct_official,
            foreign_matter_pct=foreign_matter_pct,
            damage_pct=damage_pct,
            broken_pct=broken_pct,
        ),
        LAB,
    )
    return get_success_data(resp)


def store_lot(lot_id: str, bin_id: str) -> dict:
    return get_success_data(api_client.store_lot(lot_id, {"bin_id": bin_id}, SCALE))


def create_binned_spot_lot(season_id: str, grower_id: str, bin_id: str,
                           gross_weight_lbs=22000, tare_weight_lbs=12000,
                           scheduled_date="2026-08-10", moisture_pct_handheld=13.0,
                           moisture_pct_official=13.0, spot_price_cents_per_cwt=1300,
                           variety="LONG_GRAIN", foreign_matter_pct=0.2,
                           damage_pct=0.2, broken_pct=0.6) -> dict:
    """Spot lot taken all the way to BINNED via direct store."""
    lot = create_spot_lot(
        season_id, grower_id, gross_weight_lbs=gross_weight_lbs,
        tare_weight_lbs=tare_weight_lbs, scheduled_date=scheduled_date,
        moisture_pct_handheld=moisture_pct_handheld,
        spot_price_cents_per_cwt=spot_price_cents_per_cwt, variety=variety,
    )
    grade_lot(lot["id"], moisture_pct_official=moisture_pct_official,
              foreign_matter_pct=foreign_matter_pct, damage_pct=damage_pct,
              broken_pct=broken_pct)
    return store_lot(lot["id"], bin_id)


# ---------------------------------------------------------------------------
# Tier 3: drying / milling / packaging / byproduct lifecycle shortcuts
# ---------------------------------------------------------------------------

def create_drying_run(season_id: str, lot_ids: list, destination_bin_id: str,
                      fuel_cost_cents=None) -> dict:
    overrides = {}
    if fuel_cost_cents is not None:
        overrides["fuel_cost_cents"] = fuel_cost_cents
    resp = api_client.create_drying_run(
        create_drying_run_payload(season_id, lot_ids, destination_bin_id, **overrides),
        DRYER,
    )
    return get_success_data(resp)


def get_drying_run(run_id: str) -> dict:
    return get_success_data(api_client.get_drying_run(run_id, DRYER))


def complete_drying_run(run_id: str, actual_output_cwt: float) -> dict:
    return get_success_data(
        api_client.complete_drying_run(run_id, {"actual_output_cwt": actual_output_cwt}, DRYER)
    )


def cancel_drying_run(run_id: str) -> dict:
    return get_success_data(api_client.cancel_drying_run(run_id, DRYER))


def create_mill_run(season_id: str, input_bin_id: str, input_cwt: float) -> dict:
    resp = api_client.create_mill_run(
        create_mill_run_payload(season_id, input_bin_id, input_cwt), SUPERVISOR
    )
    return get_success_data(resp)


def get_mill_run(run_id: str) -> dict:
    return get_success_data(api_client.get_mill_run(run_id, SUPERVISOR))


def start_mill_run(run_id: str) -> dict:
    return get_success_data(api_client.start_mill_run(run_id, SUPERVISOR))


def complete_mill_run(run_id: str) -> dict:
    return get_success_data(api_client.complete_mill_run(run_id, SUPERVISOR))


def verify_mill_run(run_id: str, act_head_cwt: float, act_broken_cwt: float,
                    act_brewers_cwt: float, act_bran_cwt: float, act_hull_cwt: float) -> dict:
    payload = {
        "act_head_cwt": act_head_cwt,
        "act_broken_cwt": act_broken_cwt,
        "act_brewers_cwt": act_brewers_cwt,
        "act_bran_cwt": act_bran_cwt,
        "act_hull_cwt": act_hull_cwt,
    }
    return get_success_data(api_client.verify_mill_run(run_id, payload, SUPERVISOR))


def create_packaging_run(season_id: str, line_id="LINE_1", brand_label="MillHouse",
                         package_size_kg=25, units_planned=100,
                         starts_at="2026-08-20T08:00:00Z", ends_at="2026-08-20T09:00:00Z") -> dict:
    resp = api_client.create_packaging_run(
        create_packaging_run_payload(
            season_id, line_id=line_id, brand_label=brand_label,
            package_size_kg=package_size_kg, units_planned=units_planned,
            starts_at=starts_at, ends_at=ends_at,
        ),
        SUPERVISOR,
    )
    return get_success_data(resp)


def create_byproduct_order(season_id: str, product="BRAN", quantity_cwt=16.00,
                           price_cents_per_cwt=1800, buyer_name="FeedCo") -> dict:
    resp = api_client.create_byproduct_order(
        create_byproduct_order_payload(
            season_id, product=product, quantity_cwt=quantity_cwt,
            price_cents_per_cwt=price_cents_per_cwt, buyer_name=buyer_name,
        ),
        MERCH,
    )
    return get_success_data(resp)


def create_fumigation_event(season_id: str, bin_id: str,
                            started_at="2026-08-01T00:00:00Z",
                            exposure_hours=48, aeration_hours=24,
                            fumigant_code="PH3", applicator_license="LIC-7741") -> dict:
    resp = api_client.create_fumigation_event(
        create_fumigation_event_payload(
            season_id, bin_id, started_at=started_at,
            exposure_hours=exposure_hours, aeration_hours=aeration_hours,
            fumigant_code=fumigant_code, applicator_license=applicator_license,
        ),
        FUMTECH,
    )
    return get_success_data(resp)


def create_hold(season_id: str, target_type: str, target_id: str,
                reason_code="PEST_ACTIVITY") -> dict:
    resp = api_client.create_hold(
        create_hold_payload(season_id, target_type, target_id, reason_code=reason_code),
        SAFETY,
    )
    return get_success_data(resp)


def release_hold(hold_id: str, resolution_note="inspected clean") -> dict:
    return get_success_data(
        api_client.release_hold(hold_id, {"resolution_note": resolution_note}, SAFETY)
    )


def get_inventory(season_id: str) -> dict:
    return get_success_data(api_client.get_byproduct_inventory(season_id, SUPERVISOR))


# ---------------------------------------------------------------------------
# Tier 4: accumulation / threshold targeting composites
# ---------------------------------------------------------------------------

def setup_bin_with_spot_stock(season_id: str, grower_id: str, bin_code="B-01",
                              bin_capacity=500.00, gross_weight_lbs=42000,
                              tare_weight_lbs=12000, moisture_pct_official=13.0,
                              variety="LONG_GRAIN", scheduled_date="2026-08-10",
                              spot_price_cents_per_cwt=1300) -> tuple:
    """Bin + one SPOT lot graded and stored. Returns (bin, lot)."""
    bin_ = create_bin(season_id, bin_code=bin_code, capacity_cwt=bin_capacity)
    lot = create_binned_spot_lot(
        season_id, grower_id, bin_["id"], gross_weight_lbs=gross_weight_lbs,
        tare_weight_lbs=tare_weight_lbs, moisture_pct_handheld=moisture_pct_official,
        moisture_pct_official=moisture_pct_official,
        spot_price_cents_per_cwt=spot_price_cents_per_cwt, variety=variety,
        scheduled_date=scheduled_date,
    )
    return bin_, lot


def setup_completed_mill_run(input_cwt=200.00, variety="LONG_GRAIN",
                             lot_gross=42000, lot_tare=12000, bin_capacity=500.00) -> dict:
    """Full chain: open season, grower, bin with a stored SPOT lot (M 13.0, no
    shrink), then a mill run taken SCHEDULED -> IN_PROCESS -> COMPLETED.
    Returns dict(season, grower, bin, lot, mill_run)."""
    season = create_open_season()
    grower = create_grower(season["id"])
    bin_, lot = setup_bin_with_spot_stock(
        season["id"], grower["id"], bin_capacity=bin_capacity,
        gross_weight_lbs=lot_gross, tare_weight_lbs=lot_tare, variety=variety,
    )
    run = create_mill_run(season["id"], bin_["id"], input_cwt)
    start_mill_run(run["id"])
    run = complete_mill_run(run["id"])
    return {"season": season, "grower": grower, "bin": bin_, "lot": lot, "mill_run": run}


# ---------------------------------------------------------------------------
# Tier 5: settlement finalization / terminal-state composites
# ---------------------------------------------------------------------------

def setup_binned_contract_lots(lot_specs, contracted_cwt=250.00,
                               base_price_cents_per_cwt=1000,
                               grade_adjustments=None,
                               farm_code="FARM-002", legal_name="Bayou Grain",
                               advance_issued_cents=None,
                               bin_code="B-01", bin_capacity=500.00,
                               variety="LONG_GRAIN") -> dict:
    """Open season + grower + contract + bin + N contract lots, each graded and
    stored. Each spec in lot_specs is a dict with keys:
      gross, tare, date, handheld, official, fm, dmg, brk
    Returns dict(season, grower, contract, bin, lots)."""
    season = create_open_season()
    grower = create_grower(season["id"], farm_code=farm_code, legal_name=legal_name,
                           advance_issued_cents=advance_issued_cents)
    contract = create_contract(
        season["id"], grower["id"], contracted_cwt=contracted_cwt,
        base_price_cents_per_cwt=base_price_cents_per_cwt,
        grade_adjustments=grade_adjustments, variety=variety,
    )
    bin_ = create_bin(season["id"], bin_code=bin_code, capacity_cwt=bin_capacity)
    lots = []
    for spec in lot_specs:
        lot = create_contract_lot(
            season["id"], grower["id"], contract["id"],
            gross_weight_lbs=spec["gross"], tare_weight_lbs=spec["tare"],
            scheduled_date=spec.get("date", "2026-08-10"),
            moisture_pct_handheld=spec.get("handheld", 13.0), variety=variety,
        )
        grade_lot(
            lot["id"], moisture_pct_official=spec.get("official", 13.0),
            foreign_matter_pct=spec.get("fm", 0.2), damage_pct=spec.get("dmg", 0.2),
            broken_pct=spec.get("brk", 0.6),
        )
        lots.append(store_lot(lot["id"], bin_["id"]))
    return {"season": season, "grower": grower, "contract": contract,
            "bin": bin_, "lots": lots}


def setup_binned_spot_lots(lot_specs, farm_code="FARM-001", legal_name="Delta Farms",
                           advance_issued_cents=None, bin_code="B-01",
                           bin_capacity=500.00, variety="LONG_GRAIN") -> dict:
    """Open season + grower + bin + N SPOT lots, each graded and stored.
    Spec keys: gross, tare, date, handheld, official, fm, dmg, brk, price.
    Returns dict(season, grower, bin, lots)."""
    season = create_open_season()
    grower = create_grower(season["id"], farm_code=farm_code, legal_name=legal_name,
                           advance_issued_cents=advance_issued_cents)
    bin_ = create_bin(season["id"], bin_code=bin_code, capacity_cwt=bin_capacity)
    lots = []
    for spec in lot_specs:
        lots.append(create_binned_spot_lot(
            season["id"], grower["id"], bin_["id"],
            gross_weight_lbs=spec["gross"], tare_weight_lbs=spec["tare"],
            scheduled_date=spec.get("date", "2026-08-10"),
            moisture_pct_handheld=spec.get("handheld", spec.get("official", 13.0)),
            moisture_pct_official=spec.get("official", 13.0),
            spot_price_cents_per_cwt=spec.get("price", 1300),
            variety=spec.get("variety", variety),
            foreign_matter_pct=spec.get("fm", 0.2), damage_pct=spec.get("dmg", 0.2),
            broken_pct=spec.get("brk", 0.6),
        ))
    return {"season": season, "grower": grower, "bin": bin_, "lots": lots}


def create_draft_settlement(season_id: str, grower_id: str,
                            period_start_date="2026-08-01",
                            period_end_date="2026-08-31",
                            clerk_user_id="clerk-1") -> dict:
    """Draft a settlement; created_by_user_id records the clerk's X-User-ID."""
    resp = api_client.create_settlement(
        create_settlement_payload(
            season_id, grower_id,
            period_start_date=period_start_date, period_end_date=period_end_date,
        ),
        make_clerk_headers(clerk_user_id),
    )
    return get_success_data(resp)


def issue_provisional(settlement_id: str, clerk_user_id="clerk-1") -> dict:
    return get_success_data(
        api_client.issue_provisional(settlement_id, make_clerk_headers(clerk_user_id))
    )


def approve_settlement(settlement_id: str, clerk_user_id="clerk-2") -> dict:
    return get_success_data(
        api_client.approve_settlement(settlement_id, make_clerk_headers(clerk_user_id))
    )


def pay_settlement(settlement_id: str, clerk_user_id="clerk-1") -> dict:
    return get_success_data(
        api_client.pay_settlement(settlement_id, make_clerk_headers(clerk_user_id))
    )


def get_settlement(settlement_id: str) -> dict:
    return get_success_data(api_client.get_settlement(settlement_id, CLERK1))


def settlement_reaching(scenario: dict, stage: str,
                        period=("2026-08-01", "2026-08-31"),
                        creator="clerk-1", approver="clerk-2") -> dict:
    """Close intake, draft a settlement over the scenario's grower, then walk it
    to the requested stage: 'draft' | 'issued' | 'approved' | 'paid'.
    Returns the settlement (in the requested stage)."""
    season = scenario["season"]
    close_intake(season["id"])
    settlement = create_draft_settlement(
        season["id"], scenario["grower"]["id"],
        period_start_date=period[0], period_end_date=period[1],
        clerk_user_id=creator,
    )
    if stage == "draft":
        return settlement
    settlement = issue_provisional(settlement["id"], creator)
    if stage == "issued":
        return settlement
    begin_settlement_review(season["id"])
    settlement = approve_settlement(settlement["id"], approver)
    if stage == "approved":
        return settlement
    settlement = pay_settlement(settlement["id"], creator)
    return settlement


def dispute_settlement_by_grower(settlement_id: str, grower_id: str,
                                 dispute_reason="grade dispute on lot") -> dict:
    """Dispute as the GrowerRep whose grower the settlement pays (entity-backed
    identity: X-User-ID is the Grower id)."""
    return get_success_data(
        api_client.dispute_settlement(
            settlement_id, {"dispute_reason": dispute_reason},
            make_grower_rep_headers(grower_id),
        )
    )


def revise_settlement(settlement_id: str, clerk_user_id="clerk-1") -> dict:
    return get_success_data(
        api_client.revise_settlement(settlement_id, make_clerk_headers(clerk_user_id))
    )


def reopen_intake(season_id: str) -> dict:
    return get_success_data(api_client.reopen_intake(season_id, ADMIN))
