"""Heavyweight composite scenarios shared by the depth tests."""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from . import fixtures as fx
from .fixtures import (
    ADMIN, ANALYST, ANALYST2, APPROVER, APPROVER2, COMPLIANCE, CONTRACT,
)
from .test_users import make_manager_headers


def setup_payer_impact_scenario() -> dict:
    """Facility with one ACTIVE item at 128000 cents, a RECONCILED batch holding two
    MATCHED lines inside the 90-day lookback, three ACTIVE payer contracts spanning all
    three reimbursement methods, and one SUBMITTED PRICE_CHANGE request on the item.

    Returns keys: facility, department, revenue_code, price_rule, item, batch,
    line_aetna, line_bcbs, contracts, change_request, manager_headers.
    """
    manager = "u_dm_cardiac"
    base = fx.setup_base(
        facility_overrides={
            "name": "ACME Regional",
            "rounding_mode": "NEAREST_CENT",
            "aggregate_markup_limit_bp": 40000,
            "volume_growth_bp": 10500,
            "impact_lookback_days": 90,
            "duplicate_detection_mode": "STRICT_CODE",
        },
        revenue_code_overrides={
            "description": "Laboratory",
            "requires_hcpcs": False,
            "allowed_code_types": ["CDM_INTERNAL", "REV_ONLY", "CPT", "HCPCS"],
            "pricing_class": "PROCEDURE",
        },
        department_overrides={"name": "Cardiac Cath Lab"},
        price_rule_overrides={
            "pricing_method": "COST_PLUS_MARKUP",
            "markup_tiers": [
                {"min_cost_basis_cents": 0, "markup_bp": 32000},
                {"min_cost_basis_cents": 50000, "markup_bp": 24000},
                {"min_cost_basis_cents": 250000, "markup_bp": 18000},
            ],
            "min_medicare_multiple_bp": 12000,
            "market_cap_multiple_bp": 11000,
        },
        manager_user_id=manager,
    )
    item = fx.create_active_item(
        base,
        cdm_number="CDM-1000",
        description="CARDIAC CATH TRAY STANDARD",
        code_type="CDM_INTERNAL",
        cost_basis_cents=40000,
        medicare_rate_cents=20000,
        market_p75_cents=200000,
    )
    batch = fx.create_batch(
        base,
        window_start_date="2026-06-01T00:00:00Z",
        window_end_date="2026-06-30T00:00:00Z",
    )
    line_aetna = fx.append_line(
        batch["id"], "CDM-1000", base["manager_headers"],
        encounter_id="ENC-1", payer_code="AETNA_COMM",
        service_datetime="2026-06-10T09:00:00Z", quantity=3, posted_charge_cents=384000,
    )
    line_bcbs = fx.append_line(
        batch["id"], "CDM-1000", base["manager_headers"],
        encounter_id="ENC-2", payer_code="BCBS_STATE",
        service_datetime="2026-06-15T09:00:00Z", quantity=2, posted_charge_cents=256000,
    )
    fx.reconcile_batch(batch["id"])
    batch = fx.batch_lifecycle(batch["id"], "FINALIZE", note="clean pass")

    contracts = {
        "aetna": fx.create_payer_contract(
            base["facility"]["id"], payer_code="AETNA_COMM", product_line="COMMERCIAL",
            reimbursement_method="PERCENT_OF_CHARGE",
            term_start_date="2026-01-01T00:00:00Z", term_end_date="2026-12-31T00:00:00Z",
            percent_of_charge_bp=4500, trailing_units=7, renegotiation_notice_days=30,
        ),
        "bcbs": fx.create_payer_contract(
            base["facility"]["id"], payer_code="BCBS_STATE", product_line="COMMERCIAL",
            reimbursement_method="LESSER_OF_FEE_SCHEDULE",
            term_start_date="2026-01-01T00:00:00Z", term_end_date="2026-12-31T00:00:00Z",
            percent_of_charge_bp=6000, fee_schedule_cents=80000, trailing_units=13,
            renegotiation_notice_days=30,
        ),
        "medicaid": fx.create_payer_contract(
            base["facility"]["id"], payer_code="MEDICAID_MCO_A", product_line="MEDICAID_MCO",
            reimbursement_method="CASE_RATE",
            term_start_date="2026-01-01T00:00:00Z", term_end_date="2026-12-31T00:00:00Z",
            case_rate_cents=500000, trailing_units=0, renegotiation_notice_days=30,
        ),
    }
    change_request = fx.create_change_request(
        base, item["id"], "PRICE_CHANGE",
        justification="vendor cost increase on the cath tray",
        proposed_cost_basis_cents=49900,
    )
    base.update({
        "item": item,
        "batch": batch,
        "line_aetna": line_aetna,
        "line_bcbs": line_bcbs,
        "contracts": contracts,
        "change_request": change_request,
    })
    return base


def setup_duplicate_pair_scenario(duplicate_detection_mode="FUZZY_DESCRIPTION") -> dict:
    """Two ACTIVE items in the same department sharing code_type / code_value / revenue
    code, whose descriptions have a Jaccard similarity of exactly 0.2500.

    Returns keys: facility, department, revenue_code, price_rule, subject, survivor.
    """
    base = fx.setup_base(
        facility_overrides={
            "name": "Dupe Memorial",
            "rounding_mode": "NEAREST_CENT",
            "aggregate_markup_limit_bp": 40000,
            "duplicate_detection_mode": duplicate_detection_mode,
        },
        revenue_code_overrides={
            "description": "Emergency Room",
            "requires_hcpcs": True,
            "allowed_code_types": ["CPT", "HCPCS"],
            "pricing_class": "PROCEDURE",
        },
        department_overrides={"name": "Surgery"},
        price_rule_overrides={
            "pricing_method": "COST_PLUS_MARKUP",
            "markup_tiers": [
                {"min_cost_basis_cents": 0, "markup_bp": 32000},
                {"min_cost_basis_cents": 50000, "markup_bp": 24000},
                {"min_cost_basis_cents": 250000, "markup_bp": 18000},
            ],
            "min_medicare_multiple_bp": 12000,
            "market_cap_multiple_bp": 11000,
        },
        manager_user_id="u_dm_surgery",
    )
    common = dict(
        code_type="CPT", code_value="99213", cost_basis_cents=40000,
        medicare_rate_cents=20000, market_p75_cents=200000,
    )
    subject = fx.create_active_item(
        base, cdm_number="CDM-2001", description="CARDIAC TRAY ALPHA", **common
    )
    survivor = fx.create_active_item(
        base, cdm_number="CDM-2002", description="CARDIAC BETA", **common
    )
    base.update({"subject": subject, "survivor": survivor})
    base["facility"] = fx.read_facility(base["facility"]["id"])
    return base


def set_duplicate_detection_mode(facility_id: str, mode: str) -> dict:
    """Flip the facility's duplicate_detection_mode, carrying the live version."""
    live = fx.read_facility(facility_id)
    return get_success_data(
        api_client.update_facility(
            facility_id,
            {"expected_facility_version": live["version"], "duplicate_detection_mode": mode},
            ADMIN,
        )
    )


STANDARD_TIERS = [
    {"min_cost_basis_cents": 0, "markup_bp": 32000},
    {"min_cost_basis_cents": 50000, "markup_bp": 24000},
    {"min_cost_basis_cents": 250000, "markup_bp": 18000},
]


def setup_gross_charge_nesting_scenario() -> dict:
    """Facility CMB at NEAREST_CENT with two revenue codes and two price rules, and three
    DRAFT items that each exercise a different corner of the tier/floor/cap nesting.

    Returns keys: facility, department, rc300, rc636, rule_cost_plus, rule_medicare,
    item_x (tier boundary), item_y (floor above cap), item_w (half-cent tie).
    """
    facility = fx.create_facility(
        name="Combinatorial General",
        cms_certification_number="CCN-2193-C",
        rounding_mode="NEAREST_CENT",
        aggregate_markup_limit_bp=40000,
    )
    department = fx.create_department(
        facility["id"], "u_dm_rx", name="Pharmacy", cost_center_code="CC-636"
    )
    rc300 = fx.create_revenue_code(
        code="0300", description="Laboratory", requires_hcpcs=False,
        allowed_code_types=["CDM_INTERNAL", "REV_ONLY"], pricing_class="PROCEDURE",
        status="ACTIVE",
    )
    rc636 = fx.create_revenue_code(
        code="0636", description="Drugs requiring detailed coding", requires_hcpcs=False,
        allowed_code_types=["CDM_INTERNAL", "REV_ONLY"], pricing_class="PHARMACY",
        status="ACTIVE",
    )
    rule_cost_plus = fx.create_price_rule(
        facility["id"], rc300["id"],
        pricing_method="COST_PLUS_MARKUP",
        effective_from="2026-08-01T00:00:00Z", effective_to=None,
        markup_tiers=STANDARD_TIERS,
        min_medicare_multiple_bp=12000, market_cap_multiple_bp=11000,
    )
    rule_medicare = fx.create_price_rule(
        facility["id"], rc636["id"],
        pricing_method="MEDICARE_MULTIPLE",
        effective_from="2026-08-01T00:00:00Z", effective_to=None,
        min_medicare_multiple_bp=11250, market_cap_multiple_bp=11000,
    )

    def _item(revenue_code_id, cdm_number, description, cost, medicare, market):
        payload = fx.f.create_charge_item_payload(
            facility["id"], department["id"], revenue_code_id,
            cdm_number=cdm_number, description=description, code_type="CDM_INTERNAL",
            cost_basis_cents=cost, medicare_rate_cents=medicare, market_p75_cents=market,
            effective_from="2026-08-01T00:00:00Z",
        )
        return get_success_data(api_client.create_charge_item(payload, ANALYST))

    item_x = _item(rc300["id"], "CDM-X", "TIER BOUNDARY ITEM X", 250000, 100000, 900000)
    item_y = _item(rc300["id"], "CDM-Y", "FLOOR ABOVE CAP ITEM Y", 20000, 100000, 100000)
    item_w = _item(rc636["id"], "CDM-W", "HALF CENT TIE ITEM W", 1, 85396, 200000)
    return {
        "facility": facility, "department": department,
        "rc300": rc300, "rc636": rc636,
        "rule_cost_plus": rule_cost_plus, "rule_medicare": rule_medicare,
        "item_x": item_x, "item_y": item_y, "item_w": item_w,
    }


def setup_variance_batch_scenario() -> dict:
    """Facility VAR with one ACTIVE item at 128000 cents and an INGESTED batch holding five
    lines on distinct encounters whose per-line variances are 195, -234, 0 and 5 bp plus one
    unknown-code line.

    Returns keys: facility, department, revenue_code, price_rule, item, batch, l1..l5.
    """
    base = fx.setup_base(
        facility_overrides={
            "name": "Variance Regional",
            "cms_certification_number": "CCN-2193-V",
            "rounding_mode": "NEAREST_CENT",
            "aggregate_markup_limit_bp": 40000,
        },
        revenue_code_overrides={
            "code": "0300", "description": "Laboratory", "requires_hcpcs": False,
            "allowed_code_types": ["CDM_INTERNAL", "REV_ONLY"],
            "pricing_class": "PROCEDURE", "status": "ACTIVE",
        },
        department_overrides={"name": "Clinical Lab", "cost_center_code": "CC-300"},
        price_rule_overrides={
            "pricing_method": "COST_PLUS_MARKUP",
            "markup_tiers": STANDARD_TIERS,
            "min_medicare_multiple_bp": 12000,
            "market_cap_multiple_bp": 11000,
        },
        manager_user_id="u_dm_lab",
    )
    item = fx.create_active_item(
        base, cdm_number="CDM-3000", description="BASIC METABOLIC PANEL",
        code_type="CDM_INTERNAL", cost_basis_cents=40000,
        medicare_rate_cents=20000, market_p75_cents=200000,
    )
    batch = fx.create_batch(
        base,
        window_start_date="2026-06-01T00:00:00Z",
        window_end_date="2026-06-30T00:00:00Z",
    )
    mgr = base["manager_headers"]

    def _line(cdm, encounter, payer, when, quantity, posted):
        return fx.append_line(
            batch["id"], cdm, mgr, encounter_id=encounter, payer_code=payer,
            service_datetime=when, quantity=quantity, posted_charge_cents=posted,
        )

    base.update({
        "item": item,
        "batch": batch,
        "l1": _line("CDM-3000", "ENC-1", "AETNA_COMM", "2026-06-02T08:00:00Z", 1, 130500),
        "l2": _line("CDM-3000", "ENC-2", "AETNA_COMM", "2026-06-03T08:00:00Z", 1, 125000),
        "l3": _line("CDM-3000", "ENC-3", "BCBS_STATE", "2026-06-04T08:00:00Z", 50, 6400000),
        "l4": _line("CDM-3000", "ENC-4", "BCBS_STATE", "2026-06-05T08:00:00Z", 2, 256128),
        "l5": _line("CDM-9999", "ENC-5", "BCBS_STATE", "2026-06-06T08:00:00Z", 2, 77000),
    })
    return base


def setup_markup_snapshot_scenario() -> dict:
    """Facility MKP whose aggregate_markup_limit_bp is 11000, holding a diluting ACTIVE item
    A at 1000000/1000000 and a target ACTIVE item B at 128000/40000, so the live aggregate
    ratio is 10846 bp.

    Returns keys: facility, department, rc250, rc300, rule_flat, rule_cost_plus, item_a,
    item_b, manager_headers, manager_user_id.
    """
    base = fx.setup_base(
        facility_overrides={
            "name": "Markup Memorial",
            "cms_certification_number": "CCN-2193-M",
            "rounding_mode": "NEAREST_CENT",
            "aggregate_markup_limit_bp": 11000,
        },
        revenue_code_overrides={
            "code": "0250", "description": "Pharmacy general", "requires_hcpcs": False,
            "allowed_code_types": ["CDM_INTERNAL", "REV_ONLY"],
            "pricing_class": "SUPPLY", "status": "ACTIVE",
        },
        department_overrides={"name": "Supply Chain", "cost_center_code": "CC-250"},
        price_rule_overrides={
            "pricing_method": "FLAT_FEE",
            "flat_fee_cents": 1000000,
            "min_medicare_multiple_bp": 12000,
            "market_cap_multiple_bp": 11000,
        },
        manager_user_id="u_dm_sc",
    )
    rc300 = fx.create_revenue_code(
        code="0300", description="Laboratory", requires_hcpcs=False,
        allowed_code_types=["CDM_INTERNAL", "REV_ONLY"], pricing_class="PROCEDURE",
        status="ACTIVE",
    )
    rule_cost_plus = fx.create_price_rule(
        base["facility"]["id"], rc300["id"],
        pricing_method="COST_PLUS_MARKUP",
        effective_from="2026-08-01T00:00:00Z", effective_to=None,
        markup_tiers=STANDARD_TIERS,
        min_medicare_multiple_bp=12000, market_cap_multiple_bp=11000,
    )
    item_a = fx.create_active_item(
        base, cdm_number="CDM-4001", description="IMPLANT KIT DILUTER",
        code_type="CDM_INTERNAL", cost_basis_cents=1000000,
        medicare_rate_cents=100, market_p75_cents=10000000,
    )
    base_b = dict(base, revenue_code=rc300)
    item_b = fx.create_active_item(
        base_b, cdm_number="CDM-4002", description="TARGET PANEL B",
        code_type="CDM_INTERNAL", cost_basis_cents=40000,
        medicare_rate_cents=10000, market_p75_cents=900000,
    )
    base.update({
        "rc250": base["revenue_code"],
        "rc300": rc300,
        "rule_flat": base["price_rule"],
        "rule_cost_plus": rule_cost_plus,
        "item_a": item_a,
        "item_b": item_b,
    })
    base["facility"] = fx.read_facility(base["facility"]["id"])
    return base


def setup_northgate_item_scenario(reprice: bool = False) -> dict:
    """Clock at 2026-09-01, facility 'Northgate General', an unrestricted Clinical Lab
    department managed by mgr_lab_01, one ACTIVE cost-plus rule effective from 2026-01-01,
    and CDM-40001 (cost 60000 / medicare 18000 / market_p75 200000) left in DRAFT.

    Returns keys: facility, revenue_code, department, price_rule, item, manager_headers,
    manager_user_id.
    """
    fx.set_clock("2026-09-01T00:00:00Z")
    base = fx.setup_base(
        facility_overrides={
            "name": "Northgate General",
            "cms_certification_number": "CCN-2193-A",
            "rounding_mode": "NEAREST_CENT",
            "aggregate_markup_limit_bp": 40000,
            "duplicate_detection_mode": "STRICT_CODE",
        },
        revenue_code_overrides={
            "code": "0300", "description": "Laboratory - general",
            "requires_hcpcs": False,
            "allowed_code_types": ["CPT", "HCPCS", "REV_ONLY", "CDM_INTERNAL"],
            "pricing_class": "PROCEDURE", "status": "ACTIVE",
        },
        department_overrides={
            "name": "Clinical Lab", "cost_center_code": "CC-7100",
            "allowed_revenue_code_values": [],
        },
        price_rule_overrides={
            "pricing_method": "COST_PLUS_MARKUP",
            "markup_tiers": STANDARD_TIERS,
            "min_medicare_multiple_bp": 12000,
            "market_cap_multiple_bp": 11000,
            "effective_from": "2026-01-01T00:00:00Z",
        },
        manager_user_id="mgr_lab_01",
    )
    item = fx.create_item(
        base, cdm_number="CDM-40001", description="Comprehensive metabolic panel",
        code_type="CPT", code_value="80053",
        cost_basis_cents=60000, medicare_rate_cents=18000, market_p75_cents=200000,
        effective_from="2026-09-01T00:00:00Z",
    )
    if reprice:
        item = fx.reprice_item(item["id"])
    base["item"] = item
    return base


def setup_northgate_published_scenario() -> dict:
    """The Northgate scenario driven all the way to a PUBLISHED transparency file: CDM-40001
    is ACTIVE at 144000 cents, one ACTIVE payer contract supplies the single payer column,
    and the facility's transparency_status is CURRENT.

    Adds keys: item (ACTIVE), contract, transparency_file.
    """
    base = setup_northgate_item_scenario()
    item = fx.reprice_item(base["item"]["id"])
    fx.item_lifecycle(item["id"], "SUBMIT_FOR_REVIEW", ANALYST)
    fx.item_lifecycle(item["id"], "APPROVE", APPROVER)
    item = fx.item_lifecycle(item["id"], "ACTIVATE", APPROVER)
    contract = fx.create_payer_contract(
        base["facility"]["id"], payer_code="BCBS_STATE", product_line="COMMERCIAL",
        reimbursement_method="PERCENT_OF_CHARGE", percent_of_charge_bp=4500,
        term_start_date="2026-01-01T00:00:00Z", term_end_date="2026-12-31T00:00:00Z",
        trailing_units=100, renegotiation_notice_days=30,
    )
    facility = fx.read_facility(base["facility"]["id"])
    tfile = fx.build_transparency_file(facility["id"], facility["version"],
                                      file_format="CSV")
    tfile = fx.file_lifecycle(tfile["id"], "VALIDATE")
    tfile = fx.file_lifecycle(tfile["id"], "PUBLISH")
    base.update({
        "item": fx.read_item(item["id"]),
        "contract": contract,
        "transparency_file": tfile,
        "facility": fx.read_facility(facility["id"]),
    })
    return base


def setup_five_active_items_scenario() -> dict:
    """The Northgate scenario with five ACTIVE / PRICED_CURRENT items CDM-40001..CDM-40005,
    each priced at 144000 cents against the same ACTIVE cost-plus rule.

    Adds key: items (a list of five ChargeItem dicts).
    """
    base = setup_northgate_item_scenario()
    items = [fx.read_item(base["item"]["id"])]
    for n in range(2, 6):
        items.append(fx.create_item(
            base, cdm_number=f"CDM-4000{n}", description=f"Assay panel {n}",
            code_type="CDM_INTERNAL",
            cost_basis_cents=60000, medicare_rate_cents=18000, market_p75_cents=200000,
            effective_from="2026-09-01T00:00:00Z",
        ))
    activated = []
    for item in items:
        fx.reprice_item(item["id"])
        fx.item_lifecycle(item["id"], "SUBMIT_FOR_REVIEW", ANALYST)
        fx.item_lifecycle(item["id"], "APPROVE", APPROVER)
        activated.append(fx.item_lifecycle(item["id"], "ACTIVATE", APPROVER))
    base["items"] = activated
    base["item"] = activated[0]
    base["facility"] = fx.read_facility(base["facility"]["id"])
    return base


def setup_frozen_and_ruleless_scenario() -> dict:
    """St Vitus: an ACTIVE item priced at 240000 cents, a VALIDATED transparency file that
    both froze the item and forced the facility FROZEN, and a clock advanced past the only
    price rule's exclusive effective_to so the candidate set is empty as well.

    Returns keys: facility, revenue_code, department, price_rule, contract, item,
    transparency_file, manager_headers, manager_user_id.
    """
    fx.set_clock("2026-08-01T00:00:00Z")
    base = fx.setup_base(
        facility_overrides={
            "name": "St Vitus Medical Center",
            "cms_certification_number": "CCN-2193-FROZEN",
            "rounding_mode": "NEAREST_CENT",
            "aggregate_markup_limit_bp": 40000,
        },
        revenue_code_overrides={
            "code": "0300", "description": "Laboratory - general",
            "requires_hcpcs": False,
            "allowed_code_types": ["CPT", "HCPCS", "REV_ONLY", "CDM_INTERNAL"],
            "pricing_class": "PROCEDURE", "status": "ACTIVE",
        },
        department_overrides={
            "name": "Clinical Laboratory", "cost_center_code": "CC-0300",
            "allowed_revenue_code_values": [],
        },
        price_rule_overrides={
            "pricing_method": "COST_PLUS_MARKUP",
            "markup_tiers": STANDARD_TIERS,
            "min_medicare_multiple_bp": 10000,
            "market_cap_multiple_bp": 50000,
            "effective_from": "2026-08-01T00:00:00Z",
            "effective_to": "2026-09-01T00:00:00Z",
        },
        manager_user_id="dept_mgr_1",
    )
    contract = fx.create_payer_contract(
        base["facility"]["id"], payer_code="BCBS_STATE", product_line="COMMERCIAL",
        reimbursement_method="PERCENT_OF_CHARGE", percent_of_charge_bp=4500,
        term_start_date="2026-08-01T00:00:00Z", term_end_date="2027-08-01T00:00:00Z",
        trailing_units=10, renegotiation_notice_days=30,
    )
    item = fx.create_active_item(
        base, cdm_number="CDM-5001", description="Comprehensive metabolic panel",
        code_type="CDM_INTERNAL", cost_basis_cents=100000,
        medicare_rate_cents=10000, market_p75_cents=5000000,
        effective_from="2026-08-01T00:00:00Z",
    )
    facility = fx.read_facility(base["facility"]["id"])
    tfile = fx.build_transparency_file(facility["id"], facility["version"],
                                      file_format="JSON")
    tfile = fx.file_lifecycle(tfile["id"], "VALIDATE")
    fx.set_clock("2026-09-15T00:00:00Z")
    base.update({
        "contract": contract,
        "item": fx.read_item(item["id"]),
        "transparency_file": tfile,
        "facility": fx.read_facility(facility["id"]),
    })
    return base


def setup_stale_item_over_markup_limit_scenario() -> dict:
    """A facility whose aggregate_markup_limit_bp is a tight 20000, holding one
    PENDING_REVIEW item priced at 240000 cents (ratio 24000 bp) whose price rule has been
    superseded, so both the price-state constraint and the markup limit are violated at once.

    Returns keys: facility, revenue_code, department, price_rule (PR1), price_rule_2 (PR2),
    item, manager_headers, manager_user_id.
    """
    fx.set_clock("2026-08-01T00:00:00Z")
    base = fx.setup_base(
        facility_overrides={
            "name": "Tightlimit Community Hospital",
            "cms_certification_number": "CCN-2193-TIGHT",
            "rounding_mode": "NEAREST_CENT",
            "aggregate_markup_limit_bp": 20000,
        },
        revenue_code_overrides={
            "code": "0300", "description": "Laboratory - general",
            "requires_hcpcs": False,
            "allowed_code_types": ["CPT", "HCPCS", "REV_ONLY", "CDM_INTERNAL"],
            "pricing_class": "PROCEDURE", "status": "ACTIVE",
        },
        department_overrides={
            "name": "Clinical Laboratory", "cost_center_code": "CC-0300",
            "allowed_revenue_code_values": [],
        },
        price_rule_overrides={
            "pricing_method": "COST_PLUS_MARKUP",
            "markup_tiers": STANDARD_TIERS,
            "min_medicare_multiple_bp": 10000,
            "market_cap_multiple_bp": 50000,
            "effective_from": "2026-08-01T00:00:00Z",
        },
        manager_user_id="dept_mgr_1",
    )
    item = fx.create_item(
        base, cdm_number="CDM-6001", description="Comprehensive metabolic panel",
        code_type="CDM_INTERNAL", cost_basis_cents=100000,
        medicare_rate_cents=10000, market_p75_cents=5000000,
        effective_from="2026-08-01T00:00:00Z",
    )
    fx.reprice_item(item["id"])
    fx.set_clock("2026-08-05T00:00:00Z")
    rule2 = fx.create_price_rule(
        base["facility"]["id"], base["revenue_code"]["id"],
        pricing_method="COST_PLUS_MARKUP",
        markup_tiers=STANDARD_TIERS,
        min_medicare_multiple_bp=10000, market_cap_multiple_bp=50000,
        effective_from="2026-08-05T00:00:00Z",
        supersede_rule_id=base["price_rule"]["id"],
    )
    item = fx.item_lifecycle(item["id"], "SUBMIT_FOR_REVIEW", ANALYST,
                             note="submit for committee")
    base["price_rule_2"] = rule2
    base["item"] = item
    return base


def setup_variance_tolerance_scenario() -> dict:
    """Facility BND holding one ACTIVE item priced at exactly 1000000 cents and an INGESTED
    batch of five quantity-1 lines posted at 1010000, 1010049, 1010050, 990000 and 989950,
    which straddle the +/-100 bp tolerance from both sides.

    Returns keys: facility, department, revenue_code, price_rule, item, batch,
    on_pos, eps_below, eps_above, on_neg, eps_below_neg.
    """
    base = fx.setup_base(
        facility_overrides={
            "name": "Boundary General",
            "cms_certification_number": "CCN-2193-B",
            "rounding_mode": "NEAREST_CENT",
            "aggregate_markup_limit_bp": 40000,
        },
        revenue_code_overrides={
            "code": "0320", "description": "Radiology diagnostic", "requires_hcpcs": False,
            "allowed_code_types": ["CDM_INTERNAL", "REV_ONLY"],
            "pricing_class": "PROCEDURE", "status": "ACTIVE",
        },
        department_overrides={"name": "Imaging", "cost_center_code": "CC-320"},
        price_rule_overrides={
            "pricing_method": "FLAT_FEE",
            "flat_fee_cents": 1000000,
            "min_medicare_multiple_bp": 12000,
            "market_cap_multiple_bp": 11000,
        },
        manager_user_id="u_dm_img",
    )
    item = fx.create_active_item(
        base, cdm_number="CDM-5000", description="CT ABDOMEN WITH CONTRAST",
        code_type="CDM_INTERNAL", cost_basis_cents=1000000,
        medicare_rate_cents=100, market_p75_cents=10000000,
    )
    batch = fx.create_batch(
        base,
        window_start_date="2026-06-01T00:00:00Z",
        window_end_date="2026-06-30T00:00:00Z",
    )
    mgr = base["manager_headers"]

    def _line(encounter, when, posted):
        return fx.append_line(
            batch["id"], "CDM-5000", mgr, encounter_id=encounter, payer_code="AETNA_COMM",
            service_datetime=when, quantity=1, posted_charge_cents=posted,
        )

    base.update({
        "item": item,
        "batch": batch,
        "on_pos": _line("ENC-1", "2026-06-02T08:00:00Z", 1010000),
        "eps_below": _line("ENC-2", "2026-06-03T08:00:00Z", 1010049),
        "eps_above": _line("ENC-3", "2026-06-04T08:00:00Z", 1010050),
        "on_neg": _line("ENC-4", "2026-06-05T08:00:00Z", 990000),
        "eps_below_neg": _line("ENC-5", "2026-06-06T08:00:00Z", 989950),
    })
    return base


def setup_transparency_empty_chargemaster_scenario() -> dict:
    """Facility TRN with a department, an ACTIVE revenue code, an ACTIVE cost-plus rule and
    one ACTIVE payer contract, but *no* charge item at all — every prerequisite is created
    before any build, because a BUILDING file freezes the facility and POST /price-rules is
    posture-gated.

    Returns keys: facility, department, revenue_code, price_rule, contract, manager_headers.
    """
    base = fx.setup_base(
        facility_overrides={
            "name": "Transparency Regional",
            "cms_certification_number": "CCN-2193-T",
            "rounding_mode": "NEAREST_CENT",
            "aggregate_markup_limit_bp": 40000,
        },
        revenue_code_overrides={
            "code": "0300", "description": "Laboratory", "requires_hcpcs": False,
            "allowed_code_types": ["CDM_INTERNAL", "REV_ONLY"],
            "pricing_class": "PROCEDURE", "status": "ACTIVE",
        },
        department_overrides={"name": "Outpatient Clinic", "cost_center_code": "CC-OP"},
        price_rule_overrides={
            "pricing_method": "COST_PLUS_MARKUP",
            "markup_tiers": STANDARD_TIERS,
            "min_medicare_multiple_bp": 12000,
            "market_cap_multiple_bp": 11000,
        },
        manager_user_id="u_dm_op",
    )
    base["contract"] = fx.create_payer_contract(
        base["facility"]["id"],
        payer_code="AETNA_COMM",
        product_line="COMMERCIAL",
        reimbursement_method="PERCENT_OF_CHARGE",
        percent_of_charge_bp=4500,
        term_start_date="2026-01-01T00:00:00Z",
        term_end_date="2026-12-31T00:00:00Z",
        trailing_units=5,
        renegotiation_notice_days=30,
    )
    base["facility"] = fx.read_facility(base["facility"]["id"])
    return base


def setup_similarity_boundary_scenario() -> dict:
    """Facility SIM in FUZZY_DESCRIPTION mode with six ACTIVE items, all CPT/99213 and all
    priced at 128000 cents, arranged into three pairs whose weighted similarity lands just
    below, exactly on, and exactly on (by a different composition) the 0.8000 threshold.

    Returns keys: facility, department, revenue_code (0300), revenue_code_301, price_rule,
    price_rule_301, s1, t1, s2, t2, s3, t3.
    """
    base = fx.setup_base(
        facility_overrides={
            "name": "Similarity Memorial",
            "cms_certification_number": "CCN-2193-S",
            "rounding_mode": "NEAREST_CENT",
            "aggregate_markup_limit_bp": 40000,
            "duplicate_detection_mode": "FUZZY_DESCRIPTION",
        },
        revenue_code_overrides={
            "code": "0300", "description": "Laboratory", "requires_hcpcs": False,
            "allowed_code_types": ["CPT", "HCPCS", "CDM_INTERNAL"],
            "pricing_class": "PROCEDURE", "status": "ACTIVE",
        },
        department_overrides={"name": "General", "cost_center_code": "CC-GEN"},
        price_rule_overrides={
            "pricing_method": "COST_PLUS_MARKUP",
            "markup_tiers": STANDARD_TIERS,
            "min_medicare_multiple_bp": 12000,
            "market_cap_multiple_bp": 11000,
        },
        manager_user_id="u_dm_gen",
    )
    rc301 = fx.create_revenue_code(
        code="0301", description="Laboratory chemistry", requires_hcpcs=False,
        allowed_code_types=["CPT", "HCPCS", "CDM_INTERNAL"],
        pricing_class="PROCEDURE", status="ACTIVE",
    )
    rule301 = fx.create_price_rule(
        base["facility"]["id"], rc301["id"],
        pricing_method="COST_PLUS_MARKUP", markup_tiers=STANDARD_TIERS,
        min_medicare_multiple_bp=12000, market_cap_multiple_bp=11000,
    )
    common = dict(
        code_type="CPT", code_value="99213", cost_basis_cents=40000,
        medicare_rate_cents=20000, market_p75_cents=200000,
    )

    def _item(cdm, description, revenue_code_id=None):
        scoped = dict(base)
        if revenue_code_id is not None:
            scoped["revenue_code"] = {"id": revenue_code_id}
        return fx.create_active_item(
            scoped, cdm_number=cdm, description=description, **common
        )

    base.update({
        "revenue_code_301": rc301,
        "price_rule_301": rule301,
        "s1": _item("CDM-7001", "ALPHA BETA"),
        "t1": _item("CDM-7002", "ALPHA GAMMA"),
        "s2": _item("CDM-7003", "RED GREEN BLUE ONE TWO THREE"),
        "t2": _item("CDM-7004", "RED GREEN BLUE FOUR FIVE SIX SEVEN"),
        "s3": _item("CDM-7005", "OMEGA SIGMA DELTA"),
        "t3": _item("CDM-7006", "OMEGA SIGMA DELTA", rc301["id"]),
    })
    base["facility"] = fx.read_facility(base["facility"]["id"])
    return base


def setup_capture_hold_scenario() -> dict:
    """Clock at 2026-09-10. A Clinical Lab department whose RECONCILED batch holds two MATCHED
    lines at 600000 cents each on one encounter, the companion posted 72 hours after the
    trigger and therefore outside the 24-hour window, so exactly one OPEN
    MissingChargeFinding of 600000 cents is waiting to be dispositioned.

    Returns keys: facility, department, revenue_code, price_rule, trigger_item,
    companion_item, batch, trigger_line, recovery_line, finding, manager_headers.
    """
    fx.set_clock("2026-09-10T00:00:00Z")
    base = fx.setup_base(
        facility_overrides={
            "name": "Capture Hold Community",
            "cms_certification_number": "CCN-2193-H",
            "rounding_mode": "NEAREST_CENT",
            "aggregate_markup_limit_bp": 40000,
        },
        revenue_code_overrides={
            "code": "0300", "description": "Laboratory", "requires_hcpcs": False,
            "allowed_code_types": ["CDM_INTERNAL", "REV_ONLY"],
            "pricing_class": "PROCEDURE", "status": "ACTIVE",
        },
        department_overrides={"name": "Clinical Lab", "cost_center_code": "CC-0300"},
        price_rule_overrides={
            "pricing_method": "FLAT_FEE",
            "flat_fee_cents": 300000,
            "min_medicare_multiple_bp": 12000,
            "market_cap_multiple_bp": 11000,
            "effective_from": "2026-09-01T00:00:00Z",
        },
        manager_user_id="mgr_lab_01",
    )
    economics = dict(
        code_type="CDM_INTERNAL", cost_basis_cents=100000,
        medicare_rate_cents=10000, market_p75_cents=5000000,
        effective_from="2026-09-10T00:00:00Z",
    )
    companion = fx.create_active_item(
        base, cdm_number="CDM-50002", description="RADIOLOGY INTERPRETATION",
        **economics
    )
    trigger = fx.create_active_item(
        base, cdm_number="CDM-50001", description="CT ABDOMEN TECHNICAL COMPONENT",
        companion_required_item_id=companion["id"], companion_window_hours=24,
        **economics
    )
    batch = fx.create_batch(
        base,
        window_start_date="2026-09-01T00:00:00Z",
        window_end_date="2026-09-30T00:00:00Z",
    )
    mgr = base["manager_headers"]
    trigger_line = fx.append_line(
        batch["id"], "CDM-50001", mgr, encounter_id="ENC-9001", payer_code="AETNA_COMM",
        service_datetime="2026-09-05T08:00:00Z", quantity=2, posted_charge_cents=600000,
    )
    recovery_line = fx.append_line(
        batch["id"], "CDM-50002", mgr, encounter_id="ENC-9001", payer_code="AETNA_COMM",
        service_datetime="2026-09-08T08:00:00Z", quantity=2, posted_charge_cents=600000,
    )
    fx.reconcile_batch(batch["id"])
    findings = fx.list_findings(batch_id=batch["id"])
    base.update({
        "trigger_item": trigger,
        "companion_item": companion,
        "batch": fx.batch_lifecycle(batch["id"], "FINALIZE"),
        "trigger_line": trigger_line,
        "recovery_line": recovery_line,
        "findings": findings,
        "finding": findings[0] if findings else None,
    })
    return base


def row_references(row: dict, entity_id: str) -> bool:
    """True when a report row points at the given entity through any of its string fields."""
    return any(v == entity_id for v in row.values() if isinstance(v, str))
