"""Multi-hop cascades and cross-entity state dependencies: the acceptance
allocation cascade, the candidate-removal cascade, the candidate-readiness gate
on acceptance, the offer-accepted gate on transplant creation, and the cyclic
graft lifecycle.

Translates difficulty instances tc_offer_accept_depth4_chain,
tc_candidate_remove_depth2_rescinds_offers, cesd_offer_accept_requires_candidate_active,
cesd_transplant_requires_offer_accepted, and nlsm_transplant_graft_cyclic_functioning_atrisk.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    set_clock, create_center, create_opo, create_listed_candidate, create_organ,
    run_match, issue_offer, accept_offer,
    setup_matching_organ_with_offer, schedule_follow_up,
    accept_offer_payload, create_transplant_payload, remove_candidate_payload,
    make_center_headers, make_opo_headers,
)


def test_accept_cascades_organ_candidate_and_registration(api):
    """PRD §3.8: "The organ cascades from MATCHING to ALLOCATED; that allocation
    rescinds every other still-open offer for the organ (each decrementing
    open_offer_count) and then sets open_offer_count to 0, and it increments the
    organ's version." PRD §3.8: "The candidate cascades from LISTED to
    TRANSPLANTED, which sets the candidate's removal_reason to TRANSPLANTED,
    withdraws the candidate's ACTIVE registration to WITHDRAWN with
    withdrawn_reason of TRANSPLANTED, and stops waiting-time accrual."

    Design: Difficulty/transitive_cascade/tc_offer_accept_depth4_chain
    """
    scenario = setup_matching_organ_with_offer(
        center_overrides=dict(unos_center_code="C005", region_code=5),
        opo_overrides=dict(opo_code="OPO5", region_code=5),
        candidate_overrides=dict(mrn="X1", blood_type="A",
                                 date_of_birth="1975-01-01T00:00:00Z",
                                 height_cm=178, weight_kg=80),
        organ_overrides=dict(blood_type="O", donor_weight_kg=85))
    center = scenario["center"]
    center_headers = make_center_headers(center["id"])
    opo_headers = make_opo_headers(scenario["opo"]["id"])

    accepted = validate_success(api.accept_offer(
        scenario["offer"]["id"], accept_offer_payload(scenario["organ"]["version"]),
        center_headers), 200)
    assert accepted["status"] == "ACCEPTED"

    organ_after = validate_success(api.get_donor_organ(scenario["organ"]["id"], opo_headers), 200)
    assert organ_after["status"] == "ALLOCATED"

    cand_after = validate_success(api.get_candidate(scenario["candidate"]["id"], center_headers), 200)
    assert cand_after["listing_status"] == "TRANSPLANTED"
    assert cand_after["removal_reason"] == "TRANSPLANTED"

    regs, _ = validate_paginated(api.list_registrations(
        scenario["candidate"]["id"], center_headers, params={"status": "WITHDRAWN"}))
    assert len(regs) == 1
    assert regs[0]["status"] == "WITHDRAWN"
    assert regs[0]["withdrawn_reason"] == "TRANSPLANTED"


def test_accept_invalidates_match_run(api):
    """PRD §3.8: "The offer's match run cascades to INVALIDATED." PRD §3.5: "A
    match run is invalidated — moved from COMPLETED to INVALIDATED — by the system
    whenever its organ becomes ALLOCATED or DISCARDED."

    Design: Difficulty/transitive_cascade/tc_offer_accept_depth4_chain
    """
    scenario = setup_matching_organ_with_offer(
        center_overrides=dict(unos_center_code="C005", region_code=5),
        opo_overrides=dict(opo_code="OPO5", region_code=5),
        candidate_overrides=dict(mrn="X1b", blood_type="A",
                                 date_of_birth="1975-01-01T00:00:00Z",
                                 height_cm=178, weight_kg=80),
        organ_overrides=dict(blood_type="O", donor_weight_kg=85))
    center_headers = make_center_headers(scenario["center"]["id"])
    opo_headers = make_opo_headers(scenario["opo"]["id"])
    validate_success(api.accept_offer(
        scenario["offer"]["id"], accept_offer_payload(scenario["organ"]["version"]),
        center_headers), 200)
    run_after = validate_success(api.get_match_run(scenario["match_run"]["id"], opo_headers), 200)
    assert run_after["status"] == "INVALIDATED"


def test_remove_candidate_withdraws_registration_and_rescinds_offer(api):
    """PRD §3.4: "It records the supplied removal_reason, cascades the candidate's
    ACTIVE registration to WITHDRAWN with its withdrawn_reason set to the same
    removal reason, rescinds every still-open offer the candidate holds (each
    rescinded offer decrements its organ's open_offer_count by one ...)."

    Design: Difficulty/transitive_cascade/tc_candidate_remove_depth2_rescinds_offers
    """
    scenario = setup_matching_organ_with_offer(
        center_overrides=dict(unos_center_code="C005", region_code=5),
        opo_overrides=dict(opo_code="OPO5", region_code=5),
        candidate_overrides=dict(mrn="X2", blood_type="A",
                                 date_of_birth="1975-01-01T00:00:00Z",
                                 height_cm=178, weight_kg=80),
        organ_overrides=dict(blood_type="O", donor_weight_kg=85))
    center = scenario["center"]
    center_headers = make_center_headers(center["id"])
    opo_headers = make_opo_headers(scenario["opo"]["id"])

    cand_after = validate_success(api.remove_candidate(
        scenario["candidate"]["id"], remove_candidate_payload("IMPROVED"), center_headers), 200)
    assert cand_after["listing_status"] == "REMOVED"
    assert cand_after["removal_reason"] == "IMPROVED"

    regs, _ = validate_paginated(api.list_registrations(
        scenario["candidate"]["id"], center_headers, params={"status": "WITHDRAWN"}))
    assert len(regs) == 1
    assert regs[0]["withdrawn_reason"] == "IMPROVED"

    offer_after = validate_success(api.get_offer(scenario["offer"]["id"], opo_headers), 200)
    assert offer_after["status"] == "RESCINDED"

    organ_after = validate_success(api.get_donor_organ(scenario["organ"]["id"], opo_headers), 200)
    assert organ_after["open_offer_count"] == 0


def test_accept_blocked_when_candidate_inactive(api):
    """PRD §3.8: "The candidate must be ready: both medical_status equal to ACTIVE
    and listing_status equal to LISTED, else ERR_CANDIDATE_NOT_ACTIVE."

    Design: Difficulty/cross_entity_state_dependency/cesd_offer_accept_requires_candidate_active
    """
    scenario = setup_matching_organ_with_offer(
        center_overrides=dict(unos_center_code="C005", region_code=5),
        opo_overrides=dict(opo_code="OPO5", region_code=5),
        candidate_overrides=dict(mrn="D1", blood_type="A",
                                 date_of_birth="1975-01-01T00:00:00Z",
                                 height_cm=178, weight_kg=80),
        organ_overrides=dict(blood_type="O", donor_weight_kg=85))
    center_headers = make_center_headers(scenario["center"]["id"])
    # Deactivate the candidate after the offer was issued (clock still in window).
    validate_success(api.deactivate_candidate(scenario["candidate"]["id"], center_headers), 200)
    res = api.accept_offer(scenario["offer"]["id"],
                           accept_offer_payload(scenario["organ"]["version"]), center_headers)
    validate_error(res, "ERR_CANDIDATE_NOT_ACTIVE")


def test_transplant_requires_offer_accepted(api):
    """PRD §3.9: "The transplant is created only when the referenced offer is in
    ACCEPTED status and no transplant already exists for it; otherwise the request
    is rejected with ERR_OFFER_NOT_ACCEPTED."

    Design: Difficulty/cross_entity_state_dependency/cesd_transplant_requires_offer_accepted
    """
    scenario = setup_matching_organ_with_offer(
        center_overrides=dict(unos_center_code="C005", region_code=5),
        opo_overrides=dict(opo_code="OPO5", region_code=5),
        candidate_overrides=dict(mrn="D2", blood_type="A",
                                 date_of_birth="1975-01-01T00:00:00Z",
                                 height_cm=178, weight_kg=80),
        organ_overrides=dict(blood_type="O", donor_weight_kg=85))
    center_headers = make_center_headers(scenario["center"]["id"])
    # The offer is still OFFERED (never accepted).
    res = api.create_transplant(
        create_transplant_payload(scenario["offer"]["id"], "2026-06-01T00:30:00Z"),
        center_headers)
    validate_error(res, "ERR_OFFER_NOT_ACCEPTED")


def test_graft_cycles_functioning_atrisk_functioning(api):
    """PRD §3.9: "if the finding is false, the system cascades the transplant from
    FUNCTIONING to AT_RISK; if the finding is true and the transplant is currently
    AT_RISK, the system cascades it back from AT_RISK to FUNCTIONING."

    Design: Difficulty/non_linear_state_machine/nlsm_transplant_graft_cyclic_functioning_atrisk
    """
    set_clock("2026-06-01T00:00:00Z")
    center = create_center(unos_center_code="C005", region_code=5)
    opo = create_opo(opo_code="OPO5", region_code=5)
    cand = create_listed_candidate(center, mrn="T1", blood_type="A",
                                   date_of_birth="1975-01-01T00:00:00Z",
                                   height_cm=178, weight_kg=80)
    organ = create_organ(opo, blood_type="O", donor_weight_kg=85,
                         recovered_at="2026-06-01T00:00:00Z", max_cold_ischemia_hours=10)
    match_run, organ = run_match(opo, organ, "STANDARD")
    offer, organ = issue_offer(opo, organ, cand, match_run)
    center_headers = make_center_headers(center["id"])
    accepted, organ = accept_offer(center, opo, organ, offer)
    transplant = validate_success(api.create_transplant(
        create_transplant_payload(offer["id"], "2026-06-01T06:00:00Z"), center_headers), 201)

    f1 = schedule_follow_up(center, transplant, interval_label="M1",
                            scheduled_for="2026-07-01T00:00:00Z", graft_functioning=False)
    f2 = schedule_follow_up(center, transplant, interval_label="M6",
                            scheduled_for="2026-12-01T00:00:00Z", graft_functioning=True)

    validate_success(api.complete_follow_up(f1["id"], center_headers), 200)
    tx_after_f1 = validate_success(api.get_transplant(transplant["id"], center_headers), 200)
    assert tx_after_f1["graft_status"] == "AT_RISK"

    validate_success(api.complete_follow_up(f2["id"], center_headers), 200)
    tx_after_f2 = validate_success(api.get_transplant(transplant["id"], center_headers), 200)
    assert tx_after_f2["graft_status"] == "FUNCTIONING"
