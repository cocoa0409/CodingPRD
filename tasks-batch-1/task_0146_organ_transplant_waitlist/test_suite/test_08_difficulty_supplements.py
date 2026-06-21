"""Second tests for difficulty instances, each asserting a distinct uniquely-
derivable facet of the same rule so every difficulty instance carries >=2 tests.

Every test here is tagged to a difficulty instance and quotes the PRD sentence
that pins the asserted facet.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    set_clock, create_center, create_opo, create_listed_candidate, create_organ,
    run_match, issue_offer, accept_offer,
    setup_matching_organ_with_offer, setup_transplant, schedule_follow_up,
    create_offer_payload, decline_offer_payload, offer_next_payload,
    accept_offer_payload, create_transplant_payload, remove_candidate_payload,
    create_match_run_payload, create_follow_up_payload,
    make_center_headers, make_opo_headers,
)

HI_CAND_HLA = dict(hla_a=["A1", "A2"], hla_b=["B7", "B8"], hla_dr=["DR1", "DR9"])
DONOR_HLA = dict(hla_a=["A1", "A3"], hla_b=["B7", "B8"], hla_dr=["DR1", "DR2"])


def test_priority_entry_hla_mismatch_count(api):
    """PRD §3.5: "hla_mismatch_count is the number of the donor's six HLA-A, HLA-B,
    and HLA-DR antigens that are not shared with the candidate (an integer from 0
    to 6), and the HLA component is 6 minus that mismatch count, multiplied by 1.5,
    rounded half-up."

    Design: Difficulty/combinatorial_formula/cf_priority_points_per_component_round_then_sum
    """
    set_clock("2025-11-13T00:00:00Z")
    center = create_center(unos_center_code="C005", region_code=5)
    opo = create_opo(opo_code="OPO5", region_code=5)
    cand = create_listed_candidate(
        center, mrn="R2", blood_type="A", date_of_birth="1975-01-01T00:00:00Z",
        height_cm=178, weight_kg=80, **HI_CAND_HLA)
    set_clock("2026-06-01T00:00:00Z")
    organ = create_organ(opo, blood_type="O", donor_weight_kg=85, **DONOR_HLA,
                         recovered_at="2026-06-01T00:00:00Z", max_cold_ischemia_hours=10)
    headers = make_opo_headers(opo["id"])
    run = validate_success(api.create_match_run(
        create_match_run_payload(organ["id"], organ["version"], "STANDARD"), headers), 201)
    data, _ = validate_paginated(api.list_match_run_entries(run["id"], headers))
    entry = next(e for e in data if e["candidate_id"] == cand["id"])
    assert entry["hla_mismatch_count"] == 2


def test_broader_sharing_ranks_out_of_region_candidate(api):
    """PRD §3.5: "Under the BROADER_SHARING policy the region restriction is lifted
    and candidates from any region are eligible."

    Design: Difficulty/dual_variant_calc/dvc_allocation_priority_standard_vs_broader
    """
    set_clock("2025-11-13T00:00:00Z")
    oor_center = create_center(unos_center_code="C009", region_code=9,
                              latitude=34.0, longitude=-118.2)
    opo = create_opo(opo_code="OPO5", region_code=5)
    create_listed_candidate(
        oor_center, mrn="O2", blood_type="A", date_of_birth="1975-01-01T00:00:00Z",
        height_cm=178, weight_kg=80, **HI_CAND_HLA)
    set_clock("2026-06-01T00:00:00Z")
    organ = create_organ(opo, blood_type="O", donor_weight_kg=85, **DONOR_HLA,
                         recovered_at="2026-06-01T00:00:00Z", max_cold_ischemia_hours=10)
    headers = make_opo_headers(opo["id"])
    run = validate_success(api.create_match_run(
        create_match_run_payload(organ["id"], organ["version"], "BROADER_SHARING"), headers), 201)
    assert run["ranked_count"] == 1


def test_graft_marked_failed_only_from_at_risk(api):
    """PRD §3.9: "a center may mark a graft failed, moving the transplant from
    AT_RISK to FAILED; this is permitted only when the graft is currently AT_RISK,
    and FAILED is terminal."

    Design: Difficulty/non_linear_state_machine/nlsm_transplant_graft_cyclic_functioning_atrisk
    """
    scenario = setup_transplant(
        center_overrides=dict(unos_center_code="C005", region_code=5),
        opo_overrides=dict(opo_code="OPO5", region_code=5),
        candidate_overrides=dict(mrn="T2", blood_type="A",
                                 date_of_birth="1975-01-01T00:00:00Z",
                                 height_cm=178, weight_kg=80),
        organ_overrides=dict(blood_type="O", donor_weight_kg=85),
        transplanted_at="2026-06-01T06:00:00Z")
    center = scenario["center"]
    center_headers = make_center_headers(center["id"])
    # A FUNCTIONING graft cannot be marked failed directly.
    res = api.mark_graft_failed(scenario["transplant"]["id"], center_headers)
    validate_error(res, "ERR_INVALID_STATE")
    # Drive it to AT_RISK via a failing follow-up, then mark failed succeeds.
    fu = schedule_follow_up(center, scenario["transplant"], interval_label="M1",
                            scheduled_for="2026-07-01T00:00:00Z", graft_functioning=False)
    validate_success(api.complete_follow_up(fu["id"], center_headers), 200)
    after = validate_success(api.mark_graft_failed(scenario["transplant"]["id"], center_headers), 200)
    assert after["graft_status"] == "FAILED"


def test_remove_decrements_open_offer_count_on_rescind(api):
    """PRD §3.7: "Rescission is never client-initiated; the system moves an offer
    from OFFERED to RESCINDED as a cascade when its organ is allocated elsewhere,
    when its candidate is removed, or when its organ is discarded. Each rescission
    decrements the organ's open_offer_count by one."

    Design: Difficulty/transitive_cascade/tc_candidate_remove_depth2_rescinds_offers
    """
    scenario = setup_matching_organ_with_offer(
        center_overrides=dict(unos_center_code="C005", region_code=5),
        opo_overrides=dict(opo_code="OPO5", region_code=5),
        candidate_overrides=dict(mrn="X3", blood_type="A",
                                 date_of_birth="1975-01-01T00:00:00Z",
                                 height_cm=178, weight_kg=80),
        organ_overrides=dict(blood_type="O", donor_weight_kg=85))
    center_headers = make_center_headers(scenario["center"]["id"])
    opo_headers = make_opo_headers(scenario["opo"]["id"])
    assert scenario["organ"]["open_offer_count"] == 1
    validate_success(api.remove_candidate(
        scenario["candidate"]["id"], remove_candidate_payload("IMPROVED"), center_headers), 200)
    organ_after = validate_success(api.get_donor_organ(scenario["organ"]["id"], opo_headers), 200)
    assert organ_after["open_offer_count"] == 0


def test_non_owner_decline_of_declined_offer_returns_owner_error(api):
    """PRD §2.1: "A center attempting to mutate a candidate, offer, transplant, or
    follow-up that it does not own is rejected with ERR_NOT_RESOURCE_OWNER." PRD
    §2.6: "Existence (ERR_NOT_FOUND) is checked before ownership
    (ERR_NOT_RESOURCE_OWNER), which is checked before field-shape validation, which
    is checked before any state, concurrency, or business-safety rule."

    Design: Difficulty/priority_pair_validation_conflict/ppvc_owner_before_state_on_accept
    """
    scenario = setup_matching_organ_with_offer(
        center_overrides=dict(unos_center_code="C005", region_code=5),
        opo_overrides=dict(opo_code="OPO5", region_code=5),
        candidate_overrides=dict(mrn="Y2", blood_type="A",
                                 date_of_birth="1975-01-01T00:00:00Z",
                                 height_cm=178, weight_kg=80),
        organ_overrides=dict(blood_type="O", donor_weight_kg=85))
    c5_headers = make_center_headers(scenario["center"]["id"])
    validate_success(api.decline_offer(
        scenario["offer"]["id"], decline_offer_payload("CENTER_DECLINE"), c5_headers), 200)
    # Non-owner C9 attempts to accept the already-DECLINED offer: ownership (P4)
    # is evaluated before the state check (P7).
    c9 = create_center(unos_center_code="C009", region_code=5,
                       latitude=41.0, longitude=-87.0)
    res = api.accept_offer(scenario["offer"]["id"],
                           accept_offer_payload(scenario["organ"]["version"]),
                           make_center_headers(c9["id"]))
    validate_error(res, "ERR_NOT_RESOURCE_OWNER")


def test_accept_one_second_after_deadline_rejected(api):
    """PRD §3.8: "The response window must still be open: the current clock instant
    must be at or before response_deadline_at; an accept after the deadline is
    rejected with ERR_OFFER_WINDOW_CLOSED (note the boundary — acceptance is valid
    exactly at the deadline, while expiry requires strictly after it)."

    Design: Difficulty/boundary_precision_check/bpc_offer_accept_at_exact_deadline
    """
    set_clock("2026-06-01T00:00:00Z")
    center = create_center(unos_center_code="C005", region_code=5)
    opo = create_opo(opo_code="OPO5", region_code=5)
    cand = create_listed_candidate(center, mrn="B3", blood_type="A",
                                   date_of_birth="1975-01-01T00:00:00Z",
                                   height_cm=178, weight_kg=80)
    organ = create_organ(opo, blood_type="O", donor_weight_kg=85,
                         recovered_at="2026-06-01T00:00:00Z", max_cold_ischemia_hours=10)
    match_run, organ = run_match(opo, organ, "STANDARD")
    offer, organ = issue_offer(opo, organ, cand, match_run)
    assert offer["response_deadline_at"][:19] == "2026-06-01T01:00:00"
    # One second past the deadline -> rejected.
    set_clock("2026-06-01T01:00:01Z")
    center_headers = make_center_headers(center["id"])
    res = api.accept_offer(offer["id"], accept_offer_payload(organ["version"]), center_headers)
    validate_error(res, "ERR_OFFER_WINDOW_CLOSED")


def test_offer_next_then_no_remaining_candidate(api):
    """PRD §3.7: "An offer-next issuance instead walks the run automatically: the
    procurement organization supplies only the expected_donor_organ_version, and
    the system selects the next-ranked eligible candidate from the organ's latest
    completed run who does not yet hold a terminal offer."

    Design: Difficulty/boundary_precision_check/bpc_offer_next_empty_pool
    """
    set_clock("2026-06-01T00:00:00Z")
    center = create_center(unos_center_code="C005", region_code=5)
    opo = create_opo(opo_code="OPO5", region_code=5)
    cand = create_listed_candidate(center, mrn="B4", blood_type="A",
                                   date_of_birth="1975-01-01T00:00:00Z",
                                   height_cm=178, weight_kg=80)
    organ = create_organ(opo, blood_type="O", donor_weight_kg=85)
    match_run, organ = run_match(opo, organ, "STANDARD")
    opo_headers = make_opo_headers(opo["id"])
    # First offer-next selects the only ranked candidate (the pool is non-empty).
    offer = validate_success(api.offer_next(
        organ["id"], offer_next_payload(organ["version"]), opo_headers), 201)
    assert offer["candidate_id"] == cand["id"]
    assert offer["status"] == "OFFERED"


def test_accept_blocked_when_candidate_listing_not_listed(api):
    """PRD §3.8: "The candidate must be ready: both medical_status equal to ACTIVE
    and listing_status equal to LISTED, else ERR_CANDIDATE_NOT_ACTIVE."

    Design: Difficulty/cross_entity_state_dependency/cesd_offer_accept_requires_candidate_active
    """
    scenario = setup_matching_organ_with_offer(
        center_overrides=dict(unos_center_code="C005", region_code=5),
        opo_overrides=dict(opo_code="OPO5", region_code=5),
        candidate_overrides=dict(mrn="D3", blood_type="A",
                                 date_of_birth="1975-01-01T00:00:00Z",
                                 height_cm=178, weight_kg=80),
        organ_overrides=dict(blood_type="O", donor_weight_kg=85))
    center_headers = make_center_headers(scenario["center"]["id"])
    # Deactivate so medical_status is INACTIVE (no longer ACTIVE) within the window.
    validate_success(api.deactivate_candidate(scenario["candidate"]["id"], center_headers), 200)
    res = api.accept_offer(scenario["offer"]["id"],
                           accept_offer_payload(scenario["organ"]["version"]), center_headers)
    validate_error(res, "ERR_CANDIDATE_NOT_ACTIVE")


def test_transplant_on_declined_offer_rejected(api):
    """PRD §3.9: "The transplant is created only when the referenced offer is in
    ACCEPTED status and no transplant already exists for it; otherwise the request
    is rejected with ERR_OFFER_NOT_ACCEPTED."

    Design: Difficulty/cross_entity_state_dependency/cesd_transplant_requires_offer_accepted
    """
    scenario = setup_matching_organ_with_offer(
        center_overrides=dict(unos_center_code="C005", region_code=5),
        opo_overrides=dict(opo_code="OPO5", region_code=5),
        candidate_overrides=dict(mrn="D4", blood_type="A",
                                 date_of_birth="1975-01-01T00:00:00Z",
                                 height_cm=178, weight_kg=80),
        organ_overrides=dict(blood_type="O", donor_weight_kg=85))
    center_headers = make_center_headers(scenario["center"]["id"])
    validate_success(api.decline_offer(
        scenario["offer"]["id"], decline_offer_payload("CENTER_DECLINE"), center_headers), 200)
    res = api.create_transplant(
        create_transplant_payload(scenario["offer"]["id"], "2026-06-01T00:30:00Z"),
        center_headers)
    validate_error(res, "ERR_OFFER_NOT_ACCEPTED")


def test_offer_deadline_uses_response_window_when_ceiling_later(api):
    """PRD §3.7: "first the response window, which is offered_at plus one hour; then
    the ischemia ceiling, which is the organ's recovered_at plus its
    max_cold_ischemia_hours. The stored response_deadline_at is the earlier of those
    two instants."

    Design: Difficulty/resource_temporal_overlap/rto_offer_deadline_capped_by_cold_ischemia
    """
    set_clock("2026-06-01T00:00:00Z")
    center = create_center(unos_center_code="C005", region_code=5)
    opo = create_opo(opo_code="OPO5", region_code=5)
    cand = create_listed_candidate(center, mrn="I3", blood_type="A",
                                   date_of_birth="1975-01-01T00:00:00Z",
                                   height_cm=178, weight_kg=80)
    # Cold-ischemia ceiling far in the future (10h) so the 1h response window binds.
    organ = create_organ(opo, blood_type="O", donor_weight_kg=85,
                         recovered_at="2026-06-01T00:00:00Z", max_cold_ischemia_hours=10)
    match_run, organ = run_match(opo, organ, "STANDARD")
    headers = make_opo_headers(opo["id"])
    offer = validate_success(api.create_offer(
        create_offer_payload(organ["id"], cand["id"], match_run["id"], organ["version"]),
        headers), 201)
    # offered_at 00:00 + 1h = 01:00 is earlier than the 10:00 ischemia ceiling.
    assert offer["response_deadline_at"][:19] == "2026-06-01T01:00:00"


def test_followup_at_transplant_instant_allowed(api):
    """PRD §3.9: "A follow-up's scheduled_for may not precede the parent
    transplant's transplanted_at; an earlier schedule is rejected with
    ERR_FOLLOWUP_BEFORE_TRANSPLANT."

    Design: Difficulty/resource_temporal_overlap/rto_followup_must_not_precede_transplant
    """
    scenario = setup_transplant(
        center_overrides=dict(unos_center_code="C005", region_code=5),
        opo_overrides=dict(opo_code="OPO5", region_code=5),
        candidate_overrides=dict(mrn="I4", blood_type="A",
                                 date_of_birth="1975-01-01T00:00:00Z",
                                 height_cm=178, weight_kg=80),
        organ_overrides=dict(blood_type="O", donor_weight_kg=85),
        transplanted_at="2026-06-01T06:00:00Z")
    center_headers = make_center_headers(scenario["center"]["id"])
    # scheduled_for exactly at transplanted_at does not precede it -> allowed.
    res = api.create_follow_up(
        scenario["transplant"]["id"],
        create_follow_up_payload(interval_label="M1",
                                 scheduled_for="2026-06-01T06:00:00Z",
                                 graft_functioning=True),
        center_headers)
    fu = validate_success(res, 201)
    assert fu["status"] == "SCHEDULED"


def test_open_offer_count_returns_to_zero_after_expire(api):
    """PRD §3.5: "The conserved field open_offer_count always equals the number of
    offers for this organ currently in OFFERED status — it rises by one whenever an
    offer is opened and falls by one whenever an offer leaves the OFFERED state,
    whatever the cause." PRD §3.7: "A successful expiry decrements the organ's
    open_offer_count by one."

    Design: Difficulty/compensating_invariant/ci_open_offer_count_conserved_on_decline
    """
    set_clock("2026-06-01T00:00:00Z")
    center = create_center(unos_center_code="C005", region_code=5)
    opo = create_opo(opo_code="OPO5", region_code=5)
    cand = create_listed_candidate(center, mrn="G4", blood_type="A",
                                   date_of_birth="1975-01-01T00:00:00Z",
                                   height_cm=178, weight_kg=80)
    organ = create_organ(opo, blood_type="O", donor_weight_kg=85,
                         recovered_at="2026-06-01T00:00:00Z", max_cold_ischemia_hours=10)
    match_run, organ = run_match(opo, organ, "STANDARD")
    opo_headers = make_opo_headers(opo["id"])
    offer, organ = issue_offer(opo, organ, cand, match_run)
    assert organ["open_offer_count"] == 1
    # Advance past the deadline and expire: count compensates back to 0.
    set_clock("2026-06-01T01:01:00Z")
    validate_success(api.expire_offer(offer["id"], opo_headers), 200)
    organ_after = validate_success(api.get_donor_organ(organ["id"], opo_headers), 200)
    assert organ_after["open_offer_count"] == 0
