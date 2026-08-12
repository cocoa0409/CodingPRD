"""Dust sample registration and Kst classification, including band boundaries
and the insurer-conservative variant."""
from test_helpers import (
    assert_dust_sample,
    create_dust_sample,
    create_site,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS

ENGINEER = TEST_USERS["compliance_engineer_headers"]


def test_kst_zero_yields_st0_noncombustible(api):
    """PRD §3.2: "`sample_class`: `ST0` when `kst_bar_m_per_s` is exactly zero;
    `ST1` when `kst_bar_m_per_s` is greater than zero and at most 200; `ST2`
    when `kst_bar_m_per_s` is greater than 200 and at most 300; `ST3` when
    `kst_bar_m_per_s` exceeds 300."
    PRD §3.2: "`combustible`: true exactly when `kst_bar_m_per_s` is greater
    than zero."

    Design: Corner/entities/dust_sample_input_field_kst_zero_yields_st0_noncombustible
    """
    site = create_site(insurer_id="FM-1")
    sample = create_dust_sample(site["id"], material_name="inert",
                                kst_bar_m_per_s=0, pmax_bar_g=0.1,
                                mie_mj=1000, lab_report_ref="L")
    assert_dust_sample(sample)
    assert sample["sample_class"] == "ST0"
    assert sample["combustible"] is False


def test_dust_samples_list_reverse_reachable_via_site(api):
    """PRD §3.1: "DustSample, Collector, DHA, HousekeepingProgram,
    HotWorkPermit, Inspection, RetrofitProject, and Incident each carry a
    `site_id` field set by the server to the owning Site's `id`."

    Design: Corner/entities/site_id_fk_reverse_reachable
    """
    site = create_site(insurer_id="FM-1")
    create_dust_sample(site["id"], material_name="a", kst_bar_m_per_s=10)
    create_dust_sample(site["id"], material_name="b", kst_bar_m_per_s=20)

    data, meta = validate_paginated(api.list_dust_samples(site["id"], ENGINEER))
    assert meta["total_count"] == 2
    assert len(data) == 2
    for row in data:
        assert row["site_id"] == site["id"]


def test_kst_boundary_200_classified_st1(api):
    """PRD §3.2: "`ST1` when `kst_bar_m_per_s` is greater than zero and at most
    200; `ST2` when `kst_bar_m_per_s` is greater than 200 and at most 300".
    PRD §3.2: "Boundary values belong to the lower band (the comparisons are
    inclusive at the upper edge of each band)."

    Design: Difficulty/boundary_precision_check/kst_boundary_200_inclusive_lower_band
    """
    site = create_site()
    sample = create_dust_sample(site["id"], material_name="d200",
                                kst_bar_m_per_s=200, lab_report_ref="L1")
    assert sample["sample_class"] == "ST1"


def test_kst_201_classified_st2(api):
    """PRD §3.2: "`ST2` when `kst_bar_m_per_s` is greater than 200 and at most
    300".
    PRD §3.2: "Boundary values belong to the lower band (the comparisons are
    inclusive at the upper edge of each band)."

    Design: Difficulty/boundary_precision_check/kst_boundary_200_inclusive_lower_band
    """
    site = create_site()
    sample = create_dust_sample(site["id"], material_name="d201",
                                kst_bar_m_per_s=201, lab_report_ref="L2")
    assert sample["sample_class"] == "ST2"


def test_kst_175_default_bands_yield_st1(api):
    """PRD §3.2: "`ST1` when `kst_bar_m_per_s` is greater than zero and at most
    200".
    PRD §3.2: "When the owning Site's `insurer_id` begins with the literal
    prefix `IC-`, the bands tighten" — a site whose insurer_id does not carry
    that prefix keeps the default NFPA bands.

    Design: Difficulty/dual_variant_calc/kst_classify_nfpa_vs_insurer_conservative_on_dust_sample
    """
    site = create_site(name="Site A", insurer_id="FM-001")
    sample = create_dust_sample(site["id"], material_name="wood",
                                kst_bar_m_per_s=175, pmax_bar_g=8.5,
                                mie_mj=10, lab_report_ref="L-A")
    assert sample["sample_class"] == "ST1"


def test_kst_175_insurer_conservative_yields_st2(api):
    """PRD §3.2: "When the owning Site's `insurer_id` begins with the literal
    prefix `IC-`, the bands tighten: `ST1` applies when `kst_bar_m_per_s` is
    greater than zero and at most 150; `ST2` applies when `kst_bar_m_per_s` is
    greater than 150 and at most 250; `ST3` applies when `kst_bar_m_per_s`
    exceeds 250."
    PRD §3.2: "The same dust sample, registered under a conservative-insurer
    site, can therefore be classified one band higher than it would be under
    the default NFPA bands."

    Design: Difficulty/dual_variant_calc/kst_classify_nfpa_vs_insurer_conservative_on_dust_sample
    """
    site_a = create_site(name="Site A", insurer_id="FM-001")
    samp_a = create_dust_sample(site_a["id"], material_name="wood",
                                kst_bar_m_per_s=175, pmax_bar_g=8.5,
                                mie_mj=10, lab_report_ref="L-A")
    site_b = create_site(name="Site B", insurer_id="IC-ACME")
    samp_b = create_dust_sample(site_b["id"], material_name="wood",
                                kst_bar_m_per_s=175, pmax_bar_g=8.5,
                                mie_mj=10, lab_report_ref="L-B")

    read_a = validate_success(
        api.get_dust_sample(site_a["id"], samp_a["id"], ENGINEER), 200)
    read_b = validate_success(
        api.get_dust_sample(site_b["id"], samp_b["id"], ENGINEER), 200)
    assert read_a["sample_class"] == "ST1"
    assert read_b["sample_class"] == "ST2"
    assert read_a["sample_class"] != read_b["sample_class"]
