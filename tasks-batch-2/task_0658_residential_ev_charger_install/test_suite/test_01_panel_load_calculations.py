"""Panel-load (NEC dual-method) calculations and the charger-fit boundary.

Translates difficulty rule dual_variant_calc (panel branch) and boundary_precision_check
(panel branch), plus the computed-field corner instance.
"""
from test_helpers import (
    api_client,
    validate_success,
    get_success_data,
    create_homeowner_payload,
    create_property_payload,
    create_charger_product_payload,
    create_install_job_payload,
    create_site_assessment_payload,
    TEST_USERS,
)

COORDINATOR = TEST_USERS["coordinator_headers"]
ANON = TEST_USERS["anonymous_headers"]


def _new_homeowner(email):
    return get_success_data(api_client.create_homeowner(create_homeowner_payload(email=email), ANON))


def _new_charger(sku):
    return get_success_data(api_client.create_charger_product(
        create_charger_product_payload(sku=sku, name=sku, rated_amps=32,
                                       required_circuit_amps=40, msrp_cents=60000), COORDINATOR))


def _new_property(homeowner_id, main_breaker_amps):
    return get_success_data(api_client.create_property(
        create_property_payload(homeowner_id, main_breaker_amps=main_breaker_amps), COORDINATOR))


def test_standard_vs_load_study_diverge_on_same_property():
    """PRD §3.2: "Concretely, `existing_demand_va` equals 8,000 plus the result of
    multiplying 0.40 by the amount of the combined total that exceeds 8,000, with that
    fractional term rounded half up to a whole VA."
    PRD §3.2: "Under `LOAD_STUDY_220_87`, the system takes 125% of the metered peak:
    `existing_demand_va` equals 1.25 multiplied by `max_measured_demand_va`, rounded half
    up to a whole VA."
    PRD §3.2: "The boolean `charger_fits` is true exactly when `spare_capacity_va` is
    greater than or equal to that required continuous VA"

    Design: Difficulty/dual_variant_calc/panel_load_standard_vs_load_study_diverge
    """
    ho = _new_homeowner("dual1@x.com")
    charger = _new_charger("DUAL40")
    prop = _new_property(ho["id"], 100)
    job = get_success_data(api_client.create_install_job(
        create_install_job_payload(prop["id"], charger["sku"]), COORDINATOR))

    sa_std = get_success_data(api_client.create_site_assessment(
        create_site_assessment_payload(prop["id"], job["id"], assessment_method="STANDARD_220_83",
                                       declared_fixed_appliance_va=16000, max_measured_demand_va=0),
        COORDINATOR))
    sa_ls = get_success_data(api_client.create_site_assessment(
        create_site_assessment_payload(prop["id"], job["id"], assessment_method="LOAD_STUDY_220_87",
                                       declared_fixed_appliance_va=0, max_measured_demand_va=7200),
        COORDINATOR))

    std = validate_success(api_client.get_site_assessment(sa_std["id"], COORDINATOR), 200)
    assert std["existing_demand_va"] == 15160
    assert std["spare_capacity_va"] == 8840
    assert std["charger_fits"] is False

    ls = validate_success(api_client.get_site_assessment(sa_ls["id"], COORDINATOR), 200)
    assert ls["existing_demand_va"] == 9000
    assert ls["spare_capacity_va"] == 15000
    assert ls["charger_fits"] is True


def test_standard_method_demand_factor_rounding():
    """PRD §3.2: "the first 8,000 VA of that combined total counts at 100%, and the
    remainder above 8,000 VA counts at 40%."
    PRD §3.2: "The **spare capacity**, stored as `spare_capacity_va`, is the panel
    capacity minus `existing_demand_va`."

    Design: Difficulty/dual_variant_calc/panel_load_standard_vs_load_study_diverge
    """
    ho = _new_homeowner("dual2@x.com")
    charger = _new_charger("DUAL40B")
    prop = _new_property(ho["id"], 100)
    job = get_success_data(api_client.create_install_job(
        create_install_job_payload(prop["id"], charger["sku"]), COORDINATOR))
    sa = get_success_data(api_client.create_site_assessment(
        create_site_assessment_payload(prop["id"], job["id"], assessment_method="STANDARD_220_83",
                                       declared_fixed_appliance_va=16000, max_measured_demand_va=0),
        COORDINATOR))
    std = validate_success(api_client.get_site_assessment(sa["id"], COORDINATOR), 200)
    # 1800*3 + 2*1500 + 1500 + 16000 = 25900; 8000 + round(0.40*17900)=15160; 24000-15160=8840
    assert std["existing_demand_va"] == 15160
    assert std["spare_capacity_va"] == 8840
    assert std["charger_fits"] is False


def test_charger_fits_at_exact_equality_boundary():
    """PRD §3.2: "The boolean `charger_fits` is true exactly when `spare_capacity_va` is
    greater than or equal to that required continuous VA — the boundary is inclusive, so a
    spare capacity exactly equal to the required draw counts as fitting."

    Design: Difficulty/boundary_precision_check/panel_fits_at_exact_equality_boundary
    """
    ho = _new_homeowner("bnd1@x.com")
    charger = _new_charger("BND40")
    prop = _new_property(ho["id"], 200)  # 200*240 = 48000 VA panel capacity
    job = get_success_data(api_client.create_install_job(
        create_install_job_payload(prop["id"], charger["sku"]), COORDINATOR))
    # max_measured 30720 -> existing 38400 -> spare 9600 == required(1.25*32*240=9600)
    sa = get_success_data(api_client.create_site_assessment(
        create_site_assessment_payload(prop["id"], job["id"], assessment_method="LOAD_STUDY_220_87",
                                       declared_fixed_appliance_va=0, max_measured_demand_va=30720),
        COORDINATOR))
    res = validate_success(api_client.get_site_assessment(sa["id"], COORDINATOR), 200)
    assert res["existing_demand_va"] == 38400
    assert res["spare_capacity_va"] == 9600
    assert res["charger_fits"] is True


def test_panel_fit_boundary_via_create_response():
    """PRD §3.2: "Upon creation — and again whenever the assessment is re-read — the
    system computes the property's existing electrical demand and the panel's spare
    capacity, recording them on the assessment."

    Design: Difficulty/boundary_precision_check/panel_fits_at_exact_equality_boundary
    """
    ho = _new_homeowner("bnd2@x.com")
    charger = _new_charger("BND40B")
    prop = _new_property(ho["id"], 200)
    job = get_success_data(api_client.create_install_job(
        create_install_job_payload(prop["id"], charger["sku"]), COORDINATOR))
    res = validate_success(api_client.create_site_assessment(
        create_site_assessment_payload(prop["id"], job["id"], assessment_method="LOAD_STUDY_220_87",
                                       declared_fixed_appliance_va=0, max_measured_demand_va=30720),
        COORDINATOR), 201)
    assert res["existing_demand_va"] == 38400
    assert res["spare_capacity_va"] == 9600
    assert res["charger_fits"] is True


def test_computed_fields_come_from_formula_not_input():
    """PRD §3.2: "Under `LOAD_STUDY_220_87`, the system takes 125% of the metered peak:
    `existing_demand_va` equals 1.25 multiplied by `max_measured_demand_va`, rounded half
    up to a whole VA."

    Design: Corner/entities/site_assessment_computed_fields_ignore_client_input
    """
    ho = _new_homeowner("comp1@x.com")
    charger = _new_charger("COMP40")
    prop = _new_property(ho["id"], 200)  # 200*240 = 48000
    job = get_success_data(api_client.create_install_job(
        create_install_job_payload(prop["id"], charger["sku"]), COORDINATOR))
    # max_measured 7200 -> existing 9000 -> spare 48000-9000 = 39000
    res = validate_success(api_client.create_site_assessment(
        create_site_assessment_payload(prop["id"], job["id"], assessment_method="LOAD_STUDY_220_87",
                                       declared_fixed_appliance_va=0, max_measured_demand_va=7200),
        COORDINATOR), 201)
    assert res["existing_demand_va"] == 9000
    assert res["spare_capacity_va"] == 39000
