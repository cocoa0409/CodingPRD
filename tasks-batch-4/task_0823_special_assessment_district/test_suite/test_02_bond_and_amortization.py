"""Bond authorization, issuance preconditions, level-debt-service amortization, and the
reassessment re-amortization cascade.

Covers difficulty instances bond_level_debt_service_nonlinear_mode_a,
reassessment_reallocate_reamortize_cascade, bond_issue_blocked_without_confirmed_roll,
installment_year_discrete_point_collision, bond_amortization_window_continuous_overlap,
and corner instances bond_issue_computes_reserve_and_par, reissue_issued_bond_terminal_lockdown.
"""
from test_helpers import (
    validate_error, ApiErrorId, TEST_USERS,
    setup_issued_bond, setup_confirmed_roll, setup_formed_district,
    create_roll, confirm_roll, authorize_bond, issue_bond,
    get_bond, get_roll, refresh_parcel, get_parcel_installment,
    create_installment_payload,
)

ADMIN = TEST_USERS["admin_headers"]

_TWO_PARCELS = [
    {"apn": "A-1", "owner_name": "O1", "benefit_units": 60},
    {"apn": "A-2", "owner_name": "O2", "benefit_units": 40},
]


# --- level debt service amortization (non-linear formula) ---

def test_amortization_year1_interest_component(api):
    """PRD §3.4: "the interest_cents is the outstanding balance multiplied by the annual
    rate, rounded half up". PRD §3.4: "The schedule is then walked in strictly ascending
    year order with a running outstanding balance that begins at the starting principal."

    Design: Difficulty/combinatorial_formula/bond_level_debt_service_nonlinear_mode_a
    """
    _, parcels, _, _ = setup_issued_bond(
        api, parcels=_TWO_PARCELS, total_project_cost_cents=10_000_000,
        roll_method="BENEFIT_UNITS",
        bond={"coupon_rate_bps": 500, "term_years": 10, "reserve_fund_pct": 0.10},
    )
    inst = get_parcel_installment(api, parcels[0]["id"], 1)
    assert inst["interest_cents"] == 300000


def test_amortization_year1_principal_and_amount_due(api):
    """PRD §3.4: "The level debt service ... is the starting principal multiplied by the
    annual rate, divided by the quantity one minus the compounding factor, where that
    compounding factor is one plus the annual rate raised to the power of the negative term;
    this level figure is rounded half up to whole cents." PRD §3.4: "For every year before
    the last, the principal_cents is the level debt service minus that year's interest_cents".

    Design: Difficulty/combinatorial_formula/bond_level_debt_service_nonlinear_mode_a
    """
    _, parcels, _, _ = setup_issued_bond(
        api, parcels=_TWO_PARCELS, total_project_cost_cents=10_000_000,
        roll_method="BENEFIT_UNITS",
        bond={"coupon_rate_bps": 500, "term_years": 10, "reserve_fund_pct": 0.10},
    )
    inst = get_parcel_installment(api, parcels[0]["id"], 1)
    assert inst["principal_cents"] == 477027
    assert inst["amount_due_cents"] == 777027


# --- reassessment: confirm a second roll re-apportions and re-amortizes ---

def _setup_reassessed(api):
    district, parcels, roll1, bond = setup_issued_bond(
        api,
        parcels=[
            {"apn": "E-A", "owner_name": "OA", "benefit_units": 50, "land_area_sqft": 8000},
            {"apn": "E-B", "owner_name": "OB", "benefit_units": 50, "land_area_sqft": 2000},
        ],
        formation_method="BENEFIT_UNITS", total_project_cost_cents=10_000_000,
        roll_method="BENEFIT_UNITS", bond={"term_years": 2},
    )
    roll2 = create_roll(api, district["id"], method="LAND_AREA")
    confirm_roll(api, roll2["id"])
    return district, parcels, roll1, bond, roll2


def test_reassessment_supersedes_prior_roll_and_reallocates_principal(api):
    """PRD §3.3: "Any previously CONFIRMED roll of the district is superseded, transitioning
    to the terminal SUPERSEDED state." PRD §3.3: "Each ACTIVE parcel's remaining_principal_cents
    is set to its assessed_principal_cents minus any principal already paid on that parcel
    (zero on the first roll)."

    Design: Difficulty/transitive_cascade/reassessment_reallocate_reamortize_cascade
    """
    district, parcels, roll1, _, _ = _setup_reassessed(api)
    assert get_roll(api, district["id"], roll1["id"])["status"] == "SUPERSEDED"
    pea = refresh_parcel(api, parcels[0]["id"])
    assert pea["assessed_principal_cents"] == 8000000
    assert pea["remaining_principal_cents"] == 8000000


def test_reassessment_reamortizes_scheduled_installments(api):
    """PRD §3.3: "if a bond of this district is already ISSUED, confirming a new roll
    re-amortizes every SCHEDULED installment against each parcel's new remaining_principal_cents".
    PRD §3.4: "the interest_cents is the outstanding balance multiplied by the annual rate,
    rounded half up".

    Design: Difficulty/transitive_cascade/reassessment_reallocate_reamortize_cascade
    """
    _, parcels, _, _, _ = _setup_reassessed(api)
    inst = get_parcel_installment(api, parcels[0]["id"], 1)
    assert inst["status"] == "SCHEDULED"
    assert inst["interest_cents"] == 400000


# --- issue blocked without a confirmed roll (cross-entity dependency) ---

def test_bond_issue_blocked_without_confirmed_roll(api):
    """PRD §3.4: "the parent district must have a roll in CONFIRMED status, or
    ERR_NO_CONFIRMED_ROLL (HTTP 409) is returned".

    Design: Difficulty/cross_entity_state_dependency/bond_issue_blocked_without_confirmed_roll
    """
    district, _ = setup_formed_district(
        api, parcels=[{"apn": "XR-1", "owner_name": "OXR", "benefit_units": 100}],
    )
    create_roll(api, district["id"], method="BENEFIT_UNITS")  # left DRAFT, never confirmed
    bond = authorize_bond(api, district["id"], term_years=5)
    validate_error(api.issue_bond(bond["id"], ADMIN), ApiErrorId.ERR_NO_CONFIRMED_ROLL.value)


def test_bond_issue_blocked_leaves_bond_authorized(api):
    """PRD §3.4: "Issuance advances the bond from AUTHORIZED to ISSUED". PRD §3.4: "the
    parent district must have a roll in CONFIRMED status, or ERR_NO_CONFIRMED_ROLL (HTTP 409)
    is returned".

    Design: Difficulty/cross_entity_state_dependency/bond_issue_blocked_without_confirmed_roll
    """
    district, _ = setup_formed_district(
        api, parcels=[{"apn": "XR-1", "owner_name": "OXR", "benefit_units": 100}],
    )
    create_roll(api, district["id"], method="BENEFIT_UNITS")
    bond = authorize_bond(api, district["id"], term_years=5)
    validate_error(api.issue_bond(bond["id"], ADMIN), ApiErrorId.ERR_NO_CONFIRMED_ROLL.value)
    assert get_bond(api, district["id"], bond["id"])["status"] == "AUTHORIZED"


# --- supplemental installment discrete-year collision ---

def test_supplemental_installment_year_collision_rejected(api):
    """PRD §3.5: "no two non-cancelled installments may share the same combination of
    parcel_id, bond_id, and installment_year; a collision with an existing non-CANCELLED
    installment is rejected with ERR_INSTALLMENT_YEAR_CONFLICT (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/installment_year_discrete_point_collision
    """
    _, parcels, _, bond = setup_issued_bond(
        api, parcels=[{"apn": "IY-1", "owner_name": "OIY", "benefit_units": 100}],
        total_project_cost_cents=1_000_000, roll_method="BENEFIT_UNITS", bond={"term_years": 10},
    )
    payload = {"bond_id": bond["id"], "installment_year": 1,
               "due_date": "2027-07-01T00:00:00Z", "principal_cents": 1000}
    validate_error(api.create_installment(parcels[0]["id"], payload, ADMIN),
                   ApiErrorId.ERR_INSTALLMENT_YEAR_CONFLICT.value)


def test_supplemental_installment_collision_creates_no_duplicate(api):
    """PRD §3.5: "Because each amortization year is a discrete point, no two non-cancelled
    installments may share the same combination of parcel_id, bond_id, and installment_year".

    Design: Difficulty/resource_temporal_overlap/installment_year_discrete_point_collision
    """
    _, parcels, _, bond = setup_issued_bond(
        api, parcels=[{"apn": "IY-1", "owner_name": "OIY", "benefit_units": 100}],
        total_project_cost_cents=1_000_000, roll_method="BENEFIT_UNITS", bond={"term_years": 10},
    )
    payload = {"bond_id": bond["id"], "installment_year": 1,
               "due_date": "2027-07-01T00:00:00Z", "principal_cents": 1000}
    validate_error(api.create_installment(parcels[0]["id"], payload, ADMIN),
                   ApiErrorId.ERR_INSTALLMENT_YEAR_CONFLICT.value)
    from test_helpers import validate_paginated
    data, _ = validate_paginated(api.list_installments(
        TEST_USERS["auditor_headers"],
        params={"parcel_id": parcels[0]["id"], "installment_year": 1, "limit": 100}))
    assert len(data) == 1


# --- bond amortization window continuous overlap ---

def _setup_two_bonds(api):
    district, parcels, roll = setup_confirmed_roll(
        api, parcels=[{"apn": "BO-1", "owner_name": "OBO", "benefit_units": 100}],
        total_project_cost_cents=1_000_000, roll_method="BENEFIT_UNITS",
    )
    bond1 = authorize_bond(api, district["id"], issuance_date="2026-07-01T00:00:00Z", term_years=10)
    issue_bond(api, bond1["id"])
    bond2 = authorize_bond(api, district["id"], issuance_date="2030-07-01T00:00:00Z", term_years=5)
    return district, bond1, bond2


def test_second_bond_overlapping_window_rejected(api):
    """PRD §3.4: "no other already-ISSUED bond of the district may have an amortization
    window that overlaps this bond's window, or ERR_BOND_TERM_OVERLAP (HTTP 409) is returned.
    A bond's amortization window is the half-open interval that starts at its issuance year
    and runs up to but not including its issuance year plus term_years".

    Design: Difficulty/resource_temporal_overlap/bond_amortization_window_continuous_overlap
    """
    _, _, bond2 = _setup_two_bonds(api)
    validate_error(api.issue_bond(bond2["id"], ADMIN), ApiErrorId.ERR_BOND_TERM_OVERLAP.value)


def test_second_bond_overlap_leaves_it_authorized(api):
    """PRD §3.4: "two windows overlap when they share any year, and merely adjacent windows
    (one ending exactly where the next begins) do not overlap and are allowed." PRD §3.4:
    "the bond must currently be AUTHORIZED".

    Design: Difficulty/resource_temporal_overlap/bond_amortization_window_continuous_overlap
    """
    district, _, bond2 = _setup_two_bonds(api)
    validate_error(api.issue_bond(bond2["id"], ADMIN), ApiErrorId.ERR_BOND_TERM_OVERLAP.value)
    assert get_bond(api, district["id"], bond2["id"])["status"] == "AUTHORIZED"


# --- corner: reserve and par computed on issue ---

def test_bond_issue_computes_reserve_and_par(api):
    """PRD §3.4: "`reserve_fund_cents` is the district's `total_apportioned_principal_cents`
    multiplied by the bond's `reserve_fund_pct`, rounded half up to whole cents; and
    `par_amount_cents` is the district's `total_apportioned_principal_cents` plus
    `reserve_fund_cents` plus `issuance_cost_cents`."

    Design: Corner/calculations/bond_issue_computes_reserve_and_par
    """
    district, _, _, bond = setup_issued_bond(
        api, parcels=[{"apn": "C1-1", "owner_name": "O", "benefit_units": 100}],
        total_project_cost_cents=10_000_000, roll_method="BENEFIT_UNITS",
        bond={"reserve_fund_pct": 0.10, "issuance_cost_cents": 0},
    )
    assert bond["reserve_fund_cents"] == 1000000
    assert bond["par_amount_cents"] == 11000000


# --- corner: re-issue lockdown ---

def test_reissue_issued_bond_rejected(api):
    """PRD §3.4: "the bond must currently be `AUTHORIZED`, or `ERR_INVALID_BOND_STATE` (HTTP 409)
    is returned".

    Design: Corner/state_machines/reissue_issued_bond_terminal_lockdown
    """
    _, _, _, bond = setup_issued_bond(
        api, parcels=[{"apn": "S3-1", "owner_name": "O", "benefit_units": 100}],
        total_project_cost_cents=500_000, roll_method="BENEFIT_UNITS", bond={"term_years": 5},
    )
    validate_error(api.issue_bond(bond["id"], ADMIN), ApiErrorId.ERR_INVALID_BOND_STATE.value)
