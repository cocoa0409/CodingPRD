"""Allocation runs: priority-point composition, policy variants, ranking order,
the eligibility pool, match-run lifecycle, and donor-organ OCC.

Translates difficulty instances cf_priority_points_per_component_round_then_sum
and dvc_allocation_priority_standard_vs_broader, plus corner instances
corner_match_run_ranks_in_priority_order, corner_initial_state_donor_organ_available,
corner_discard_available_organ_terminal, corner_occ_match_run_stale_version,
corner_occ_offer_issue_stale_version.
"""
from test_helpers import (
    validate_success, validate_error,
    assert_donor_organ,
    set_clock, create_center, create_opo, create_listed_candidate, create_organ,
    create_match_run_payload, create_offer_payload, create_donor_organ_payload,
    make_opo_headers,
)


# Antigen sets that yield a 2-mismatch donor against the [A1,A2]/[B7,B8]/[DR1,DR9] candidate.
HI_CAND_HLA = dict(hla_a=["A1", "A2"], hla_b=["B7", "B8"], hla_dr=["DR1", "DR9"])
DONOR_HLA = dict(hla_a=["A1", "A3"], hla_b=["B7", "B8"], hla_dr=["DR1", "DR2"])


def test_priority_points_per_component_round_then_sum(api):
    """PRD §3.5: "For each eligible candidate the system computes priority_points by
    rounding several components half-up to whole numbers individually and then
    summing them. The medical component is the candidate's current_meld_peld
    multiplied by 2.5, rounded half-up. The waiting component is the candidate's
    waiting_time_days capped at 365 days, divided by 365, multiplied by 10, then
    rounded half-up ... and the HLA component is 6 minus that mismatch count,
    multiplied by 1.5, rounded half-up."

    Design: Difficulty/combinatorial_formula/cf_priority_points_per_component_round_then_sum
    """
    set_clock("2025-11-13T00:00:00Z")
    center = create_center(unos_center_code="C005", region_code=5)
    opo = create_opo(opo_code="OPO5", region_code=5)
    cand = create_listed_candidate(
        center, mrn="R1", blood_type="A", date_of_birth="1975-01-01T00:00:00Z",
        height_cm=178, weight_kg=80, **HI_CAND_HLA)
    set_clock("2026-06-01T00:00:00Z")
    organ = create_organ(opo, blood_type="O", donor_weight_kg=85, **DONOR_HLA,
                         recovered_at="2026-06-01T00:00:00Z", max_cold_ischemia_hours=10)
    headers = make_opo_headers(opo["id"])
    run = validate_success(api.create_match_run(
        create_match_run_payload(organ["id"], organ["version"], "STANDARD"), headers), 201)
    from test_helpers import validate_paginated
    data, _ = validate_paginated(api.list_match_list_entries(
        headers, params={"candidate_id": cand["id"], "match_run_id": run["id"]}))
    entry = data[0]
    assert entry["hla_mismatch_count"] == 2
    assert entry["priority_points"] == 84


def test_broader_sharing_out_of_region_points_scaled(api):
    """PRD §3.5: "Under the BROADER_SHARING policy only, a candidate whose
    listing-center region differs from the donor organ's procuring-organization
    region has its summed priority_points multiplied by 0.9 and then re-rounded
    half-up."

    Design: Difficulty/dual_variant_calc/dvc_allocation_priority_standard_vs_broader
    """
    set_clock("2025-11-13T00:00:00Z")
    oor_center = create_center(unos_center_code="C009", region_code=9,
                              latitude=34.0, longitude=-118.2)
    opo = create_opo(opo_code="OPO5", region_code=5)
    cand = create_listed_candidate(
        oor_center, mrn="O1", blood_type="A", date_of_birth="1975-01-01T00:00:00Z",
        height_cm=178, weight_kg=80, **HI_CAND_HLA)
    set_clock("2026-06-01T00:00:00Z")
    organ = create_organ(opo, blood_type="O", donor_weight_kg=85, **DONOR_HLA,
                         recovered_at="2026-06-01T00:00:00Z", max_cold_ischemia_hours=10)
    headers = make_opo_headers(opo["id"])
    run = validate_success(api.create_match_run(
        create_match_run_payload(organ["id"], organ["version"], "BROADER_SHARING"), headers), 201)
    assert run["ranked_count"] == 1
    from test_helpers import validate_paginated
    data, _ = validate_paginated(api.list_match_list_entries(
        headers, params={"candidate_id": cand["id"], "match_run_id": run["id"]}))
    assert data[0]["priority_points"] == 76


def test_standard_policy_excludes_out_of_region_candidate(api):
    """PRD §3.5: "under the STANDARD policy, the candidate's listing-center
    region_code equals the donor organ's procuring-organization region_code." PRD
    §3.5: "Candidates that are inactive, not listed, of the wrong organ type,
    ABO-incompatible, size-incompatible, or sensitized against the donor are
    excluded."

    Design: Difficulty/dual_variant_calc/dvc_allocation_priority_standard_vs_broader
    """
    set_clock("2025-11-13T00:00:00Z")
    oor_center = create_center(unos_center_code="C009", region_code=9,
                              latitude=34.0, longitude=-118.2)
    opo = create_opo(opo_code="OPO5", region_code=5)
    create_listed_candidate(
        oor_center, mrn="O1", blood_type="A", date_of_birth="1975-01-01T00:00:00Z",
        height_cm=178, weight_kg=80, **HI_CAND_HLA)
    set_clock("2026-06-01T00:00:00Z")
    organ = create_organ(opo, blood_type="O", donor_weight_kg=85, **DONOR_HLA,
                         recovered_at="2026-06-01T00:00:00Z", max_cold_ischemia_hours=10)
    headers = make_opo_headers(opo["id"])
    run = validate_success(api.create_match_run(
        create_match_run_payload(organ["id"], organ["version"], "STANDARD"), headers), 201)
    assert run["ranked_count"] == 0


def test_match_run_ranks_in_priority_order(api):
    """PRD §3.5: "Entries are ranked in descending order of priority_points." PRD
    §3.5: "Each match-list entry is an append-only row carrying its match_run_id,
    the ranked candidate_id, the 1-based rank (rank 1 is highest priority), the
    candidate's priority_points, and the candidate's hla_mismatch_count."

    Design: Corner/endpoints/corner_match_run_ranks_in_priority_order
    """
    set_clock("2024-12-30T00:00:00Z")
    center = create_center(unos_center_code="C005", region_code=5)
    opo = create_opo(opo_code="OPO5", region_code=5)
    hi = create_listed_candidate(
        center, mrn="HI", blood_type="A", date_of_birth="1975-01-01T00:00:00Z",
        height_cm=178, weight_kg=80,
        score_overrides=dict(bilirubin_mg_dl=4.0, inr=2.0, creatinine_mg_dl=2.0,
                             sodium_mmol_l=130, effective_at="2024-06-13T00:00:00Z"),
        **HI_CAND_HLA)
    lo = create_listed_candidate(
        center, mrn="LO", blood_type="A", date_of_birth="1975-01-01T00:00:00Z",
        height_cm=178, weight_kg=80,
        score_overrides=dict(bilirubin_mg_dl=1.5, inr=1.2, creatinine_mg_dl=1.1,
                             sodium_mmol_l=140, effective_at="2024-06-13T00:00:00Z"),
        hla_a=["A1", "A3"], hla_b=["B7", "B8"], hla_dr=["DR1", "DR2"])
    set_clock("2025-07-18T00:00:00Z")
    organ = create_organ(opo, blood_type="O", donor_weight_kg=85, **DONOR_HLA,
                         recovered_at="2025-07-18T00:00:00Z", max_cold_ischemia_hours=10)
    headers = make_opo_headers(opo["id"])
    run = validate_success(api.create_match_run(
        create_match_run_payload(organ["id"], organ["version"], "STANDARD"), headers), 201)
    assert run["ranked_count"] == 2
    from test_helpers import validate_paginated
    data, _ = validate_paginated(api.list_match_run_entries(run["id"], headers))
    by_cand = {e["candidate_id"]: e for e in data}
    assert by_cand[hi["id"]]["rank"] == 1
    assert by_cand[hi["id"]]["priority_points"] == 84
    assert by_cand[lo["id"]]["rank"] == 2
    assert by_cand[lo["id"]]["priority_points"] == 42


def test_new_donor_organ_initial_state(api):
    """PRD §3.5: "A new organ begins in AVAILABLE status with open_offer_count at
    0." PRD §2.4: "version — a system-managed integer that begins at its initial
    value."

    Design: Corner/state_machines/corner_initial_state_donor_organ_available
    """
    set_clock("2026-06-01T00:00:00Z")
    opo = create_opo(opo_code="OPO5", region_code=5)
    headers = make_opo_headers(opo["id"])
    res = api.create_donor_organ(create_donor_organ_payload(opo["id"]), headers)
    organ = validate_success(res, 201)
    assert_donor_organ(organ)
    assert organ["status"] == "AVAILABLE"
    assert organ["open_offer_count"] == 0
    assert organ["version"] == 1


def test_discard_available_organ_terminal(api):
    """PRD §3.6: "From AVAILABLE, discard simply moves the organ to DISCARDED and
    increments its version."

    Design: Corner/endpoints/corner_discard_available_organ_terminal
    """
    set_clock("2026-06-01T00:00:00Z")
    opo = create_opo(opo_code="OPO5", region_code=5)
    headers = make_opo_headers(opo["id"])
    organ = create_organ(opo)
    after = validate_success(api.discard_donor_organ(organ["id"], headers), 200)
    assert after["status"] == "DISCARDED"


def test_match_run_with_stale_organ_version_rejected(api):
    """PRD §2.7: "If a prior run or a discard has already advanced the organ's
    version since the caller last read it, the caller's view is stale and the run
    is rejected with ERR_STALE_ORGAN_VERSION (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/corner_occ_match_run_stale_version
    """
    set_clock("2026-06-01T00:00:00Z")
    opo = create_opo(opo_code="OPO5", region_code=5)
    headers = make_opo_headers(opo["id"])
    organ = create_organ(opo)
    stale_version = organ["version"]
    validate_success(api.create_match_run(
        create_match_run_payload(organ["id"], stale_version, "STANDARD"), headers), 201)
    res = api.create_match_run(
        create_match_run_payload(organ["id"], stale_version, "STANDARD"), headers)
    validate_error(res, "ERR_STALE_ORGAN_VERSION")


def test_offer_issue_with_stale_organ_version_rejected(api):
    """PRD §2.7: "Issuing an offer directly to a candidate likewise requires
    expected_donor_organ_version to equal the organ's current version. If another
    writer has advanced the organ's version since the caller last read it — for
    example by ... re-running the match — the issuance is rejected with
    ERR_STALE_ORGAN_VERSION (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/corner_occ_offer_issue_stale_version
    """
    set_clock("2026-06-01T00:00:00Z")
    center = create_center(unos_center_code="C005", region_code=5)
    opo = create_opo(opo_code="OPO5", region_code=5)
    cand = create_listed_candidate(center, mrn="OC1", blood_type="A",
                                   date_of_birth="1975-01-01T00:00:00Z",
                                   height_cm=178, weight_kg=80)
    organ = create_organ(opo)
    pre_run_version = organ["version"]
    headers = make_opo_headers(opo["id"])
    run = validate_success(api.create_match_run(
        create_match_run_payload(organ["id"], pre_run_version, "STANDARD"), headers), 201)
    # Caller still holds pre-run version, now stale after the run bumped it.
    res = api.create_offer(
        create_offer_payload(organ["id"], cand["id"], run["id"], pre_run_version), headers)
    validate_error(res, "ERR_STALE_ORGAN_VERSION")
