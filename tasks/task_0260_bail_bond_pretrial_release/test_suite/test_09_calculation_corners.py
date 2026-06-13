"""Corner: required-collateral risk surcharge, surety-premium minimum floor,
cash-bond full collateral / zero premium, and remission credit percentage.
"""
from test_helpers import (
    validate_success, validate_paginated, get_success_data, api_client,
    setup_judgment_ready, enter_judgment_on,
    find_ledger_entries,
    TEST_USERS,
)

AGENT = TEST_USERS["bonds_agent_headers"]
COURT = TEST_USERS["court_headers"]
OFFICER = TEST_USERS["compliance_officer_headers"]


# Corner/calculations/required_collateral_high_risk_surcharge
def test_required_collateral_high_risk_surcharge(api):
    """PRD 3.2: "A surety bond requires a percentage of face value that rises with
    risk: the face value is multiplied by 10 percent for a `LOW`-tier defendant, 25
    percent for a `MEDIUM`-tier defendant, and 50 percent for a `HIGH`-tier
    defendant."

    SURETY 2,000,000c, HIGH tier -> required_collateral_cents == 1,000,000.

    Design: Corner/calculations/required_collateral_high_risk_surcharge
    """
    defendant = get_success_data(api_client.create_defendant(
        {"full_name": "Ni Ml", "date_of_birth": "1985-11-11", "phone_e164": "+15551110013", "risk_tier": "HIGH"}, AGENT))
    order = get_success_data(api_client.create_bail_order(
        defendant["id"], {"case_number": "CR-X9", "bail_amount_cents": 2_000_000, "bond_type_allowed": "SURETY"}, COURT))
    bond = validate_success(api.create_bond(
        defendant["id"], order["id"], {"bond_type": "SURETY", "premium_rate_bps": 1000}, AGENT),
        expected_status=201)
    assert bond["required_collateral_cents"] == 1_000_000, bond["required_collateral_cents"]


# Corner/calculations/surety_premium_minimum_floor
def test_surety_premium_floored_at_minimum(api):
    """PRD 3.2: "The bond's `premium_cents` is then the greater of that rounded
    figure and a non-refundable minimum premium of 10,000 cents."

    Tiny 50,000c bond at 1000 bps computes raw 5,000c but is floored to 10,000.

    Design: Corner/calculations/surety_premium_minimum_floor
    """
    from test_helpers import setup_active_surety_bond
    scen = setup_active_surety_bond(bail_amount_cents=50_000, liability_share_cents=50_000,
                                    collateral_value_cents=12_500)
    assert scen["bond"]["premium_cents"] == 10_000, scen["bond"]["premium_cents"]


# Corner/calculations/cash_bond_full_collateral_zero_premium
def test_cash_bond_full_collateral_zero_premium(api):
    """PRD 3.2: "A cash bond must be fully secured, so `required_collateral_cents`
    equals the bond's full `bail_amount_cents`."
    PRD 3.2: "For cash and PR bonds, `premium_cents` is 0 and no premium is
    charged."

    CASH 800,000c -> required_collateral_cents == 800,000 and premium_cents == 0.

    Design: Corner/calculations/cash_bond_full_collateral_zero_premium
    """
    defendant = get_success_data(api_client.create_defendant(
        {"full_name": "Qr Ji", "date_of_birth": "1987-01-13", "phone_e164": "+15551110016", "risk_tier": "LOW"}, AGENT))
    order = get_success_data(api_client.create_bail_order(
        defendant["id"], {"case_number": "CR-X11", "bail_amount_cents": 800_000, "bond_type_allowed": "CASH"}, COURT))
    bond = validate_success(api.create_bond(
        defendant["id"], order["id"], {"bond_type": "CASH"}, AGENT), expected_status=201)
    assert bond["required_collateral_cents"] == 800_000, bond["required_collateral_cents"]
    assert bond["premium_cents"] == 0, bond["premium_cents"]


# Corner/calculations/remission_credit_percentage
def test_remission_credit_percentage_ledger(api):
    """PRD 3.6: "The remitted amount is the proceeding's recorded
    `judgment_amount_cents` multiplied by `remission_pct` and divided by 100,
    rounded half up to whole cents at the end. Remission appends a ledger entry of
    type `REMISSION_CREDIT` whose `amount_cents` is the negative of that remitted
    amount."

    Judgment 1,500,000c (face 2,000,000 minus 500,000 liquidated, no recovery)
    remitted at 25% -> REMISSION_CREDIT amount_cents == -375,000.

    Design: Corner/calculations/remission_credit_percentage
    """
    scen = setup_judgment_ready(open_recovery=False, bail_amount_cents=2_000_000,
                                liability_share_cents=2_000_000, collateral_value_cents=500_000)
    proc = enter_judgment_on(scen)
    assert proc["judgment_amount_cents"] == 1_500_000, proc["judgment_amount_cents"]
    remitted = validate_success(api.remit(scen["def_id"], scen["proc_id"], {"remission_pct": 25}, OFFICER))
    assert remitted["status"] == "REMITTED", remitted["status"]
    entries, _ = validate_paginated(api.list_ledger(scen["bond_id"], OFFICER))
    credits = find_ledger_entries(entries, "REMISSION_CREDIT")
    assert len(credits) == 1, credits
    assert credits[0]["amount_cents"] == -375_000, credits[0]["amount_cents"]
