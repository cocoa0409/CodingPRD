"""Offer issuance gates, the response-deadline computation, the re-offer loop,
expiry/decline, and the conserved open_offer_count.

Translates difficulty instances rto_offer_deadline_capped_by_cold_ischemia,
bpc_offer_next_empty_pool, and ci_open_offer_count_conserved_on_decline, plus
corner instances for the ABO / organ-type / size / crossmatch / duplicate-open
gates, the expire/accept window checks, terminal decline lockdown, and immediate
visibility.
"""
from test_helpers import (
    validate_success, validate_error,
    set_clock, create_center, create_opo, create_listed_candidate, create_organ,
    run_match, issue_offer,
    setup_matching_organ_with_run, setup_matching_organ_with_offer,
    create_offer_payload, decline_offer_payload, offer_next_payload,
    make_center_headers, make_opo_headers,
)


def _offer_against(api, opo, organ, candidate, match_run):
    """Issue a targeted offer and return the raw response (for error checks)."""
    headers = make_opo_headers(opo["id"])
    return api.create_offer(
        create_offer_payload(organ["id"], candidate["id"], match_run["id"], organ["version"]),
        headers)


def test_abo_incompatible_offer_rejected(api):
    """PRD §3.7: "The blood groups must be ABO-compatible; an incompatible pair is
    rejected with ERR_ABO_INCOMPATIBLE." PRD §3.5: "a donor of type AB is
    compatible only with a recipient of type AB."

    Design: Corner/validations/corner_abo_incompatible_offer_rejected
    """
    scenario = setup_matching_organ_with_run(
        center_overrides=dict(unos_center_code="C005", region_code=5),
        opo_overrides=dict(opo_code="OPO5", region_code=5),
        candidate_overrides=dict(mrn="AB1", blood_type="A",
                                 date_of_birth="1975-01-01T00:00:00Z",
                                 height_cm=178, weight_kg=80),
        organ_overrides=dict(blood_type="AB", donor_weight_kg=85))
    res = _offer_against(api, scenario["opo"], scenario["organ"],
                         scenario["candidate"], scenario["match_run"])
    validate_error(res, "ERR_ABO_INCOMPATIBLE")


def test_organ_type_mismatch_offer_rejected(api):
    """PRD §3.7: "The organ type must match: the offered organ's type must equal
    the candidate's organ_type, else ERR_ORGAN_TYPE_MISMATCH."

    Design: Corner/validations/corner_organ_type_mismatch_offer_rejected
    """
    scenario = setup_matching_organ_with_run(
        center_overrides=dict(unos_center_code="C005", region_code=5),
        opo_overrides=dict(opo_code="OPO5", region_code=5),
        candidate_overrides=dict(mrn="OT1", organ_type="LIVER", blood_type="A",
                                 date_of_birth="1975-01-01T00:00:00Z",
                                 height_cm=178, weight_kg=80),
        organ_overrides=dict(organ_type="KIDNEY", blood_type="O",
                             donor_weight_kg=85, max_cold_ischemia_hours=24))
    res = _offer_against(api, scenario["opo"], scenario["organ"],
                         scenario["candidate"], scenario["match_run"])
    validate_error(res, "ERR_ORGAN_TYPE_MISMATCH")


def test_size_incompatible_heart_offer_rejected(api):
    """PRD §3.7: "The size ratio must fall inside the organ-type band of Section
    3.5; an out-of-band ratio is rejected with ERR_SIZE_INCOMPATIBLE." PRD §3.5:
    "For thoracic organs — HEART or LUNG — the candidate is size-compatible when
    the ratio is at least 0.80 and at most 1.20."

    Design: Corner/calculations/corner_size_incompatible_heart_offer_rejected
    """
    scenario = setup_matching_organ_with_run(
        center_overrides=dict(unos_center_code="C005", region_code=5),
        opo_overrides=dict(opo_code="OPO5", region_code=5),
        candidate_overrides=dict(mrn="SZ1", organ_type="HEART", blood_type="A",
                                 date_of_birth="1975-01-01T00:00:00Z",
                                 height_cm=170, weight_kg=70),
        organ_overrides=dict(organ_type="HEART", blood_type="O",
                             donor_height_cm=185, donor_weight_kg=100,
                             max_cold_ischemia_hours=6))
    # ratio 100/70 = 1.4286, outside [0.80, 1.20].
    res = _offer_against(api, scenario["opo"], scenario["organ"],
                         scenario["candidate"], scenario["match_run"])
    validate_error(res, "ERR_SIZE_INCOMPATIBLE")


def test_positive_crossmatch_offer_rejected(api):
    """PRD §3.7: "if any of the donor's antigens appears in the candidate's
    unacceptable_antigens, the issuance is a positive crossmatch and is rejected
    with ERR_POSITIVE_CROSSMATCH."

    Design: Corner/calculations/corner_positive_crossmatch_offer_rejected
    """
    scenario = setup_matching_organ_with_run(
        center_overrides=dict(unos_center_code="C005", region_code=5),
        opo_overrides=dict(opo_code="OPO5", region_code=5),
        candidate_overrides=dict(mrn="XM1", blood_type="A",
                                 date_of_birth="1975-01-01T00:00:00Z",
                                 height_cm=178, weight_kg=80,
                                 hla_a=["A5", "A6"], hla_b=["B7", "B8"],
                                 hla_dr=["DR1", "DR2"], unacceptable_antigens=["A1"]),
        organ_overrides=dict(blood_type="O", donor_weight_kg=85,
                             hla_a=["A1", "A3"], hla_b=["B7", "B8"],
                             hla_dr=["DR1", "DR2"]))
    res = _offer_against(api, scenario["opo"], scenario["organ"],
                         scenario["candidate"], scenario["match_run"])
    validate_error(res, "ERR_POSITIVE_CROSSMATCH")


def test_duplicate_open_offer_rejected(api):
    """PRD §3.7: "an organ may hold at most one open offer to a given candidate at
    a time; a second OFFERED offer to a candidate who already holds one for the
    same organ is rejected with ERR_DUPLICATE_OPEN_OFFER."

    Design: Corner/validations/corner_duplicate_open_offer_rejected
    """
    scenario = setup_matching_organ_with_offer(
        center_overrides=dict(unos_center_code="C005", region_code=5),
        opo_overrides=dict(opo_code="OPO5", region_code=5),
        candidate_overrides=dict(mrn="DO1", blood_type="A",
                                 date_of_birth="1975-01-01T00:00:00Z",
                                 height_cm=178, weight_kg=80),
        organ_overrides=dict(blood_type="O", donor_weight_kg=85))
    # A second targeted offer to the same candidate while the first is OFFERED.
    res = _offer_against(api, scenario["opo"], scenario["organ"],
                         scenario["candidate"], scenario["match_run"])
    validate_error(res, "ERR_DUPLICATE_OPEN_OFFER")


def test_offer_deadline_capped_by_cold_ischemia(api):
    """PRD §3.7: "The response deadline is the earlier of two competing windows,
    computed in a pinned order: first the response window, which is offered_at plus
    one hour; then the ischemia ceiling, which is the organ's recovered_at plus its
    max_cold_ischemia_hours. The stored response_deadline_at is the earlier of those
    two instants."

    Design: Difficulty/resource_temporal_overlap/rto_offer_deadline_capped_by_cold_ischemia
    """
    set_clock("2026-06-01T00:00:00Z")
    center = create_center(unos_center_code="C005", region_code=5)
    opo = create_opo(opo_code="OPO5", region_code=5)
    cand = create_listed_candidate(center, mrn="I1", blood_type="A",
                                   date_of_birth="1975-01-01T00:00:00Z",
                                   height_cm=178, weight_kg=80)
    organ = create_organ(opo, blood_type="O", donor_weight_kg=85,
                         recovered_at="2026-06-01T00:00:00Z",
                         max_cold_ischemia_hours=0.5)
    match_run, organ = run_match(opo, organ, "STANDARD")
    # Offer issued at 00:10: window_end 01:10 but ischemia_end 00:30 -> deadline 00:30.
    set_clock("2026-06-01T00:10:00Z")
    headers = make_opo_headers(opo["id"])
    offer = validate_success(api.create_offer(
        create_offer_payload(organ["id"], cand["id"], match_run["id"], organ["version"]),
        headers), 201)
    assert offer["response_deadline_at"][:19] == "2026-06-01T00:30:00"


def test_offer_next_empty_pool_rejected(api):
    """PRD §3.7: "the system selects the next-ranked eligible candidate from the
    organ's latest completed run who does not yet hold a terminal offer. If no such
    candidate remains, offer-next is rejected with ERR_NO_NEXT_CANDIDATE."

    Design: Difficulty/boundary_precision_check/bpc_offer_next_empty_pool
    """
    set_clock("2026-06-01T00:00:00Z")
    center = create_center(unos_center_code="C005", region_code=5)
    opo = create_opo(opo_code="OPO5", region_code=5)
    cand = create_listed_candidate(center, mrn="B2", blood_type="A",
                                   date_of_birth="1975-01-01T00:00:00Z",
                                   height_cm=178, weight_kg=80)
    organ = create_organ(opo, blood_type="O", donor_weight_kg=85)
    match_run, organ = run_match(opo, organ, "STANDARD")
    opo_headers = make_opo_headers(opo["id"])
    center_headers = make_center_headers(center["id"])
    # offer-next to the only ranked candidate, then that candidate declines.
    offer = validate_success(api.offer_next(
        organ["id"], offer_next_payload(organ["version"]), opo_headers), 201)
    validate_success(api.decline_offer(
        offer["id"], decline_offer_payload("CENTER_DECLINE"), center_headers), 200)
    organ_after = validate_success(api.get_donor_organ(organ["id"], opo_headers), 200)
    res = api.offer_next(organ_after["id"], offer_next_payload(organ_after["version"]), opo_headers)
    validate_error(res, "ERR_NO_NEXT_CANDIDATE")


def test_open_offer_count_conserved_on_decline(api):
    """PRD §3.5: "The conserved field open_offer_count always equals the number of
    offers for this organ currently in OFFERED status — it rises by one whenever an
    offer is opened and falls by one whenever an offer leaves the OFFERED state."
    PRD §3.7: "the reason is recorded and the organ's open_offer_count is
    decremented by one."

    Design: Difficulty/compensating_invariant/ci_open_offer_count_conserved_on_decline
    """
    set_clock("2026-06-01T00:00:00Z")
    center = create_center(unos_center_code="C005", region_code=5)
    opo = create_opo(opo_code="OPO5", region_code=5)
    cand = create_listed_candidate(center, mrn="G1", blood_type="A",
                                   date_of_birth="1975-01-01T00:00:00Z",
                                   height_cm=178, weight_kg=80)
    organ = create_organ(opo, blood_type="O", donor_weight_kg=85)
    match_run, organ = run_match(opo, organ, "STANDARD")
    opo_headers = make_opo_headers(opo["id"])
    center_headers = make_center_headers(center["id"])
    offer, organ = issue_offer(opo, organ, cand, match_run)
    assert organ["open_offer_count"] == 1
    validate_success(api.decline_offer(
        offer["id"], decline_offer_payload("CENTER_DECLINE"), center_headers), 200)
    organ_after = validate_success(api.get_donor_organ(organ["id"], opo_headers), 200)
    assert organ_after["open_offer_count"] == 0


def test_decline_already_declined_offer_rejected(api):
    """PRD §3.7: "Declining an offer moves it from OFFERED to DECLINED." PRD §2.8:
    "State — the target resource is in a state from which the requested transition
    is defined, else ERR_INVALID_STATE."

    Design: Corner/state_machines/corner_terminal_offer_decline_then_decline_invalid_state
    """
    scenario = setup_matching_organ_with_offer(
        center_overrides=dict(unos_center_code="C005", region_code=5),
        opo_overrides=dict(opo_code="OPO5", region_code=5),
        candidate_overrides=dict(mrn="S4", blood_type="A",
                                 date_of_birth="1975-01-01T00:00:00Z",
                                 height_cm=178, weight_kg=80),
        organ_overrides=dict(blood_type="O", donor_weight_kg=85))
    center_headers = make_center_headers(scenario["center"]["id"])
    opo_headers = make_opo_headers(scenario["opo"]["id"])
    validate_success(api.decline_offer(
        scenario["offer"]["id"], decline_offer_payload("CENTER_DECLINE"), center_headers), 200)
    res = api.decline_offer(scenario["offer"]["id"], decline_offer_payload("OTHER"), center_headers)
    validate_error(res, "ERR_INVALID_STATE")
    organ_after = validate_success(api.get_donor_organ(scenario["organ"]["id"], opo_headers), 200)
    assert organ_after["open_offer_count"] == 0


def test_expire_while_window_open_rejected(api):
    """PRD §3.7: "Expiry is permitted only when the current clock instant is
    strictly after the offer's response_deadline_at; an attempt to expire an offer
    whose window is still open (now at or before the deadline) is rejected with
    ERR_OFFER_WINDOW_OPEN."

    Design: Corner/validations/corner_offer_expire_while_window_open
    """
    scenario = setup_matching_organ_with_offer(
        center_overrides=dict(unos_center_code="C005", region_code=5),
        opo_overrides=dict(opo_code="OPO5", region_code=5),
        candidate_overrides=dict(mrn="EX1", blood_type="A",
                                 date_of_birth="1975-01-01T00:00:00Z",
                                 height_cm=178, weight_kg=80),
        organ_overrides=dict(blood_type="O", donor_weight_kg=85))
    # offered_at 00:00, deadline 01:00; advance clock to 00:30 (still open).
    set_clock("2026-06-01T00:30:00Z")
    opo_headers = make_opo_headers(scenario["opo"]["id"])
    res = api.expire_offer(scenario["offer"]["id"], opo_headers)
    validate_error(res, "ERR_OFFER_WINDOW_OPEN")


def test_accept_after_deadline_window_closed(api):
    """PRD §3.8: "The response window must still be open: the current clock instant
    must be at or before response_deadline_at; an accept after the deadline is
    rejected with ERR_OFFER_WINDOW_CLOSED."

    Design: Corner/validations/corner_offer_accept_after_deadline_window_closed
    """
    scenario = setup_matching_organ_with_offer(
        center_overrides=dict(unos_center_code="C005", region_code=5),
        opo_overrides=dict(opo_code="OPO5", region_code=5),
        candidate_overrides=dict(mrn="EX2", blood_type="A",
                                 date_of_birth="1975-01-01T00:00:00Z",
                                 height_cm=178, weight_kg=80),
        organ_overrides=dict(blood_type="O", donor_weight_kg=85))
    # deadline 01:00; advance to 01:01 (past deadline).
    set_clock("2026-06-01T01:01:00Z")
    center_headers = make_center_headers(scenario["center"]["id"])
    from test_helpers import accept_offer_payload
    res = api.accept_offer(scenario["offer"]["id"],
                           accept_offer_payload(scenario["organ"]["version"]), center_headers)
    validate_error(res, "ERR_OFFER_WINDOW_CLOSED")


def test_offer_immediately_visible_with_deadline_and_rank(api):
    """PRD §3.7: "Both forms create an OFFERED offer ... both copy the candidate's
    rank from the match list into rank_at_offer; both stamp offered_at with the
    current clock instant; both compute response_deadline_at."

    Design: Corner/consistency_model/corner_immediate_offer_visible_in_response
    """
    set_clock("2026-06-01T00:00:00Z")
    center = create_center(unos_center_code="C005", region_code=5)
    opo = create_opo(opo_code="OPO5", region_code=5)
    cand = create_listed_candidate(center, mrn="IM1", blood_type="A",
                                   date_of_birth="1975-01-01T00:00:00Z",
                                   height_cm=178, weight_kg=80)
    organ = create_organ(opo, blood_type="O", donor_weight_kg=85,
                         recovered_at="2026-06-01T00:00:00Z", max_cold_ischemia_hours=10)
    match_run, organ = run_match(opo, organ, "STANDARD")
    headers = make_opo_headers(opo["id"])
    offer = validate_success(api.create_offer(
        create_offer_payload(organ["id"], cand["id"], match_run["id"], organ["version"]),
        headers), 201)
    assert offer["status"] == "OFFERED"
    assert offer["response_deadline_at"][:19] == "2026-06-01T01:00:00"
    assert offer["rank_at_offer"] == 1
