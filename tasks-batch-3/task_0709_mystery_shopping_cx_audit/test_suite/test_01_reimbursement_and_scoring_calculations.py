"""Reimbursement and scoring calculations: provisional vs final reimbursement,
self-report vs audited score, rounding order, tiered shopper fee, and the
reimbursement cap.

Covers difficulty queue rules dual_variant_calc and combinatorial_formula, plus
the corner calculation instances.
"""
from test_helpers import (
    validate_success,
    api_client as _shared_client,
    fixtures,
)
from test_helpers.test_users import (
    make_shopper_headers,
    make_qa_validator_headers,
    make_client_manager_headers,
)
from test_helpers import factories


# ---------------------------------------------------------------------------
# dual_variant_calc / reimbursement_provisional_vs_final_diverges_on_flagged_receipt
# ---------------------------------------------------------------------------
def _build_flagged_receipt_assignment(api):
    """Catalog with location 40.5/-74.5 and shopper home 40.0/-74.0 (travel 69.94),
    RETAIL script cap 5000, base_fee 2000, IN_FIELD assignment with one APPROVED
    photo, a 3000 APPROVED receipt and a 1000 FLAGGED receipt, plus a scorecard.
    Returns (client, shopper_id, assignment_id)."""
    fixtures.set_clock("2026-06-01T00:00:00Z")
    client = fixtures.register_client(fee_per_completed_shop_cents=15000)
    cid = client["id"]
    location = fixtures.create_location(cid, scenario_family="RETAIL", lat=40.5, lng=-74.5)
    script = fixtures.create_and_publish_script(
        cid, scenario_family="RETAIL",
        weights_json={"greeting": 0.3, "cleanliness": 0.3, "service": 0.4},
        required_photo_count=1, receipt_required=True, reimburse_cap_cents=5000,
        base_fee_cents=2000,
    )
    wave = fixtures.create_and_publish_wave(cid)
    shopper = fixtures.register_shopper(tax_id_on_file=True, home_lat=40.0, home_lng=-74.0)
    fixtures.certify_shopper(shopper["id"], scenario_family="RETAIL")
    asg = fixtures.create_in_field_assignment(
        cid, wave["id"], shopper["id"], location["id"], script["id"],
        "2026-06-10T00:00:00Z",
    )
    aid, sid = asg["id"], shopper["id"]
    fixtures.add_approved_photo(aid, sid)
    fixtures.add_reviewed_evidence(aid, sid, "RECEIPT", "APPROVE",
                                   object_uri="s3://e/r1.jpg", receipt_amount_cents=3000)
    fixtures.add_reviewed_evidence(aid, sid, "RECEIPT", "FLAG",
                                   object_uri="s3://e/r2.jpg", receipt_amount_cents=1000)
    fixtures.create_scorecard(aid, sid, {"greeting": 85, "cleanliness": 82, "service": 78})
    return client, sid, aid


def test_provisional_reimbursement_trusts_claimed_out_of_pocket(api):
    """PRD 3.5: "The provisional out-of-pocket figure is the assignment's
    claimed_out_of_pocket_cents, taken as-is. That out-of-pocket figure is then
    capped at the script's reimburse_cap_cents -- that is, the smaller of the two
    is used. The provisional reimbursable_cents is the capped out-of-pocket plus
    the mileage component, with no further rounding."

    Design: Difficulty/dual_variant_calc/reimbursement_provisional_vs_final_diverges_on_flagged_receipt
    """
    _, shopper_id, asg_id = _build_flagged_receipt_assignment(api)
    submitted = validate_success(api.submit_assignment(asg_id, make_shopper_headers(shopper_id)))
    # PRD 3.5: claimed_out_of_pocket_cents is set at submission to the sum of
    # receipt_amount_cents over the APPROVED RECEIPT items only -- the FLAGGED 1000
    # receipt does not count. claimed = 3000; mileage = round_half_up(69.94 * 35) =
    # 2448; provisional = min(3000, 5000) + 2448 = 5448.
    assert submitted["reimbursable_cents"] == 5448, (
        f"PROVISIONAL reimbursable expected 5448, got {submitted['reimbursable_cents']}"
    )


def test_final_reimbursement_counts_only_approved_receipts(api):
    """PRD 3.6: "The final reimbursement differs from the provisional one only in
    its out-of-pocket figure: instead of the shopper's claim, it counts only the
    receipt_amount_cents of RECEIPT evidence items whose review_status is APPROVED.
    Flagged receipts are excluded, so the final out-of-pocket is at most the
    provisional one."

    Design: Difficulty/dual_variant_calc/reimbursement_provisional_vs_final_diverges_on_flagged_receipt
    """
    _, shopper_id, asg_id = _build_flagged_receipt_assignment(api)
    validate_success(api.submit_assignment(asg_id, make_shopper_headers(shopper_id)))
    validated = validate_success(api.validate_assignment(asg_id, make_qa_validator_headers()))
    # FINAL: only APPROVED receipt 3000 counts; min(3000, 5000) + 2448 = 5448.
    assert validated["reimbursable_cents"] == 5448, (
        f"FINAL reimbursable expected 5448, got {validated['reimbursable_cents']}"
    )


# ---------------------------------------------------------------------------
# dual_variant_calc / shop_score_self_report_vs_audited_diverges_on_flagged_section
# ---------------------------------------------------------------------------
def _build_flagged_section_assignment(api):
    """RETAIL script weights {greeting:0.3, cleanliness:0.3, service:0.4}; a PHOTO
    tagged to 'service' is FLAGGED; an APPROVED receipt and an APPROVED untagged
    photo satisfy the requirements; scorecard greeting 85 cleanliness 82 service 78.
    Returns (shopper_id, assignment_id)."""
    fixtures.set_clock("2026-06-01T00:00:00Z")
    client = fixtures.register_client(fee_per_completed_shop_cents=15000)
    cid = client["id"]
    location = fixtures.create_location(cid, scenario_family="RETAIL", lat=40.5, lng=-74.5)
    script = fixtures.create_and_publish_script(
        cid, scenario_family="RETAIL",
        weights_json={"greeting": 0.3, "cleanliness": 0.3, "service": 0.4},
        required_photo_count=1, receipt_required=True, reimburse_cap_cents=5000,
        base_fee_cents=2000,
    )
    wave = fixtures.create_and_publish_wave(cid)
    shopper = fixtures.register_shopper(tax_id_on_file=True, home_lat=40.0, home_lng=-74.0)
    fixtures.certify_shopper(shopper["id"], scenario_family="RETAIL")
    asg = fixtures.create_in_field_assignment(
        cid, wave["id"], shopper["id"], location["id"], script["id"],
        "2026-06-10T00:00:00Z",
    )
    aid, sid = asg["id"], shopper["id"]
    # FLAGGED photo tagged to 'service'.
    fixtures.add_reviewed_evidence(aid, sid, "PHOTO", "FLAG",
                                   object_uri="s3://e/svc.jpg", section_key="service")
    fixtures.add_reviewed_evidence(aid, sid, "RECEIPT", "APPROVE",
                                   object_uri="s3://e/r.jpg", receipt_amount_cents=3000)
    fixtures.add_approved_photo(aid, sid, object_uri="s3://e/ok.jpg")
    fixtures.create_scorecard(aid, sid, {"greeting": 85, "cleanliness": 82, "service": 78})
    return sid, aid


def test_estimated_score_weights_every_section_at_face_value(api):
    """PRD 3.5: "For each section in the script's weights_json, the section's weight
    is multiplied by the shopper's reported score for that section in
    section_scores_json; those products are summed across all sections, and that
    single sum is rounded half up to an integer from 0 to 100. Every section the
    shopper scored counts at face value with no flag adjustment."

    Design: Difficulty/dual_variant_calc/shop_score_self_report_vs_audited_diverges_on_flagged_section
    """
    shopper_id, asg_id = _build_flagged_section_assignment(api)
    validate_success(api.submit_assignment(asg_id, make_shopper_headers(shopper_id)))
    sc = validate_success(api.get_scorecard(asg_id, make_qa_validator_headers()))
    card = sc[0] if isinstance(sc, list) else sc
    # 0.3*85 + 0.3*82 + 0.4*78 = 81.3 -> 81 (sum then round).
    assert card["estimated_score"] == 81, (
        f"estimated_score expected 81, got {card['estimated_score']}"
    )


def test_audited_score_zeros_flagged_section_without_renormalizing(api):
    """PRD 3.6: "For each section in the script's weights_json, the contribution is
    the section's weight times the shopper's reported score for that section unless
    that section has a flagged evidence item, in which case the contribution is 0;
    the contributions are summed, and that single sum is rounded half up to an
    integer from 0 to 100, stored as audited_score."

    Design: Difficulty/dual_variant_calc/shop_score_self_report_vs_audited_diverges_on_flagged_section
    """
    shopper_id, asg_id = _build_flagged_section_assignment(api)
    validate_success(api.submit_assignment(asg_id, make_shopper_headers(shopper_id)))
    validate_success(api.validate_assignment(asg_id, make_qa_validator_headers()))
    sc = validate_success(api.get_scorecard(asg_id, make_qa_validator_headers()))
    card = sc[0] if isinstance(sc, list) else sc
    # service section (flagged) drops to 0, no renorm: 0.3*85 + 0.3*82 + 0 = 50.1 -> 50.
    assert card["audited_score"] == 50, (
        f"audited_score expected 50, got {card['audited_score']}"
    )


# ---------------------------------------------------------------------------
# combinatorial_formula / shop_score_sum_then_round_pins_rounding_order
# ---------------------------------------------------------------------------
def test_estimated_score_sums_then_rounds_once(api):
    """PRD 2.5: "Each section-weighted score (estimated or audited) rounds half up
    exactly once, after the full weighted sum is computed -- the system sums first
    and rounds once, never rounding each section and then summing."

    Design: Difficulty/combinatorial_formula/shop_score_sum_then_round_pins_rounding_order
    """
    cat = fixtures.setup_submitted_assignment(
        due_at="2026-06-10T00:00:00Z",
        weights_json={"greeting": 0.3, "cleanliness": 0.3, "service": 0.4},
        section_scores_json={"greeting": 85, "cleanliness": 82, "service": 78},
        required_photo_count=1, receipt_required=False, loc_lat=40.5, loc_lng=-74.5,
    )
    sc = validate_success(api.get_scorecard(cat["assignment"]["id"], make_qa_validator_headers()))
    card = sc[0] if isinstance(sc, list) else sc
    # sum-then-round of 81.3 -> 81, NOT the 82 round-per-section-then-sum trap.
    assert card["estimated_score"] == 81, (
        f"estimated_score expected 81 (sum-then-round), got {card['estimated_score']}"
    )


def test_audited_score_sums_then_rounds_once_with_no_flags(api):
    """PRD 2.5: "Each section-weighted score (estimated or audited) rounds half up
    exactly once, after the full weighted sum is computed -- the system sums first
    and rounds once, never rounding each section and then summing."

    With no flagged sections the audited score uses the same sum-then-round of 81.3
    -> 81 (not the 82 round-per-section trap), confirming the rounding order on the
    AUDITED branch too.

    Design: Difficulty/combinatorial_formula/shop_score_sum_then_round_pins_rounding_order
    """
    cat = fixtures.setup_submitted_assignment(
        due_at="2026-06-10T00:00:00Z",
        weights_json={"greeting": 0.3, "cleanliness": 0.3, "service": 0.4},
        section_scores_json={"greeting": 85, "cleanliness": 82, "service": 78},
        required_photo_count=1, receipt_required=False, loc_lat=40.5, loc_lng=-74.5,
    )
    validate_success(api.validate_assignment(cat["assignment"]["id"], make_qa_validator_headers()))
    sc = validate_success(api.get_scorecard(cat["assignment"]["id"], make_qa_validator_headers()))
    card = sc[0] if isinstance(sc, list) else sc
    assert card["audited_score"] == 81, (
        f"audited_score expected 81 (sum-then-round, no flags), got {card['audited_score']}"
    )


# ---------------------------------------------------------------------------
# combinatorial_formula / shopper_fee_tiered_bonus_nonlinear_on_reliability_tier
# ---------------------------------------------------------------------------
def _reject_once(api, cid, wave_id, shopper_id, location_id, script_id, due_at,
                 section_scores=None):
    """Drive a fresh assignment to REJECTED, dropping reliability by 10.

    section_scores must match the backing script's weights_json keys exactly
    (PRD 3.5 ERR_SECTION_KEYS_MISMATCH); defaults to a single 'greeting' section.
    """
    if section_scores is None:
        section_scores = {"greeting": 60}
    asg = fixtures.create_in_field_assignment(cid, wave_id, shopper_id, location_id, script_id, due_at)
    fixtures.add_approved_photo(asg["id"], shopper_id)
    fixtures.create_scorecard(asg["id"], shopper_id, section_scores)
    validate_success(api.submit_assignment(asg["id"], make_shopper_headers(shopper_id)))
    validate_success(api.reject_assignment(asg["id"], make_qa_validator_headers()))


def test_shopper_fee_high_tier_bonus_at_reliability_90(api):
    """PRD 3.6: "When the reliability_score is at least 90 the bonus is 20 percent
    of the base; otherwise when it is at least 75 the bonus is 10 percent of the
    base; otherwise the bonus is 0. The bonus term is the base times the bonus
    percentage rounded half up, and shopper_fee_cents is the base plus that rounded
    bonus."

    Design: Difficulty/combinatorial_formula/shopper_fee_tiered_bonus_nonlinear_on_reliability_tier
    """
    fixtures.set_clock("2026-06-01T00:00:00Z")
    client = fixtures.register_client(fee_per_completed_shop_cents=15000)
    cid = client["id"]
    location = fixtures.create_location(cid, scenario_family="RETAIL", lat=40.0, lng=-74.0)
    script = fixtures.create_and_publish_script(
        cid, scenario_family="RETAIL", weights_json={"greeting": 0.5, "cleanliness": 0.5},
        required_photo_count=1, receipt_required=False, base_fee_cents=2000,
    )
    wave = fixtures.create_and_publish_wave(cid, rotation_cooldown_days=0)
    shopper = fixtures.register_shopper(tax_id_on_file=True, home_lat=40.0, home_lng=-74.0)
    fixtures.certify_shopper(shopper["id"], scenario_family="RETAIL")
    sid = shopper["id"]
    # One rejection drops reliability 100 -> 90 (HIGH tier boundary). The script
    # has two weight sections, so the scorecard must score both keys exactly.
    _reject_once(api, cid, wave["id"], sid, location["id"], script["id"], "2026-06-05T00:00:00Z",
                 section_scores={"greeting": 60, "cleanliness": 60})
    pre = validate_success(api.get_shopper(sid, make_qa_validator_headers()))
    assert pre["reliability_score"] == 90, (
        f"reliability_score expected 90 before validate, got {pre['reliability_score']}"
    )
    asg = fixtures.create_in_field_assignment(
        cid, wave["id"], sid, location["id"], script["id"], "2026-06-20T00:00:00Z",
    )
    fixtures.add_approved_photo(asg["id"], sid)
    fixtures.create_scorecard(asg["id"], sid, {"greeting": 90, "cleanliness": 90})
    validate_success(api.submit_assignment(asg["id"], make_shopper_headers(sid)))
    validated = validate_success(api.validate_assignment(asg["id"], make_qa_validator_headers()))
    # reliability 90 -> HIGH 0.20: 2000 + round_half_up(2000*0.20=400) = 2400.
    assert validated["shopper_fee_cents"] == 2400, (
        f"shopper_fee_cents expected 2400 (HIGH tier at 90), got {validated['shopper_fee_cents']}"
    )


def test_shopper_fee_no_bonus_below_mid_threshold(api):
    """PRD 3.6: "When the reliability_score is at least 90 the bonus is 20 percent
    of the base; otherwise when it is at least 75 the bonus is 10 percent of the
    base; otherwise the bonus is 0. The bonus term is the base times the bonus
    percentage rounded half up, and shopper_fee_cents is the base plus that rounded
    bonus."

    Below 75 the step function selects no bonus, so the fee is exactly the base
    (the other side of the non-linear tier from the 90-boundary HIGH tier).

    Design: Difficulty/combinatorial_formula/shopper_fee_tiered_bonus_nonlinear_on_reliability_tier
    """
    fixtures.set_clock("2026-06-01T00:00:00Z")
    client = fixtures.register_client(fee_per_completed_shop_cents=15000)
    cid = client["id"]
    location = fixtures.create_location(cid, scenario_family="RETAIL", lat=40.0, lng=-74.0)
    script = fixtures.create_and_publish_script(
        cid, scenario_family="RETAIL", weights_json={"greeting": 1.0},
        required_photo_count=1, receipt_required=False, base_fee_cents=2000,
    )
    wave = fixtures.create_and_publish_wave(cid, rotation_cooldown_days=0)
    shopper = fixtures.register_shopper(tax_id_on_file=True, home_lat=40.0, home_lng=-74.0)
    fixtures.certify_shopper(shopper["id"], scenario_family="RETAIL")
    sid = shopper["id"]
    # Three rejections drop reliability 100 -> 70 (below the 75 MID threshold).
    _reject_once(api, cid, wave["id"], sid, location["id"], script["id"], "2026-06-03T00:00:00Z")
    _reject_once(api, cid, wave["id"], sid, location["id"], script["id"], "2026-06-05T00:00:00Z")
    _reject_once(api, cid, wave["id"], sid, location["id"], script["id"], "2026-06-07T00:00:00Z")
    pre = validate_success(api.get_shopper(sid, make_qa_validator_headers()))
    assert pre["reliability_score"] == 70, (
        f"reliability_score expected 70 before validate, got {pre['reliability_score']}"
    )
    asg = fixtures.create_in_field_assignment(
        cid, wave["id"], sid, location["id"], script["id"], "2026-06-20T00:00:00Z",
    )
    fixtures.add_approved_photo(asg["id"], sid)
    fixtures.create_scorecard(asg["id"], sid, {"greeting": 90})
    validate_success(api.submit_assignment(asg["id"], make_shopper_headers(sid)))
    validated = validate_success(api.validate_assignment(asg["id"], make_qa_validator_headers()))
    # reliability 70 (< 75) -> bonus 0: fee == base 2000.
    assert validated["shopper_fee_cents"] == 2000, (
        f"shopper_fee_cents expected 2000 (no bonus below 75), got {validated['shopper_fee_cents']}"
    )


def test_shopper_fee_mid_tier_bonus_at_reliability_80(api):
    """PRD 3.6: "When the reliability_score is at least 90 the bonus is 20 percent
    of the base; otherwise when it is at least 75 the bonus is 10 percent of the
    base; otherwise the bonus is 0. The bonus term is the base times the bonus
    percentage rounded half up, and shopper_fee_cents is the base plus that rounded
    bonus."

    Design: Corner/calculations/shopper_fee_mid_tier_at_reliability_80
    """
    fixtures.set_clock("2026-06-01T00:00:00Z")
    client = fixtures.register_client(fee_per_completed_shop_cents=15000)
    cid = client["id"]
    location = fixtures.create_location(cid, scenario_family="RETAIL", lat=40.0, lng=-74.0)
    script = fixtures.create_and_publish_script(
        cid, scenario_family="RETAIL", weights_json={"greeting": 1.0},
        required_photo_count=1, receipt_required=False, base_fee_cents=2000,
    )
    wave = fixtures.create_and_publish_wave(cid, rotation_cooldown_days=0)
    shopper = fixtures.register_shopper(tax_id_on_file=True, home_lat=40.0, home_lng=-74.0)
    fixtures.certify_shopper(shopper["id"], scenario_family="RETAIL")
    sid = shopper["id"]
    # Two rejections drop reliability 100 -> 80 (MID tier between 75 and 90).
    _reject_once(api, cid, wave["id"], sid, location["id"], script["id"], "2026-06-05T00:00:00Z")
    _reject_once(api, cid, wave["id"], sid, location["id"], script["id"], "2026-06-08T00:00:00Z")
    pre = validate_success(api.get_shopper(sid, make_qa_validator_headers()))
    assert pre["reliability_score"] == 80, (
        f"reliability_score expected 80 before validate, got {pre['reliability_score']}"
    )
    asg = fixtures.create_in_field_assignment(
        cid, wave["id"], sid, location["id"], script["id"], "2026-06-20T00:00:00Z",
    )
    fixtures.add_approved_photo(asg["id"], sid)
    fixtures.create_scorecard(asg["id"], sid, {"greeting": 90})
    validate_success(api.submit_assignment(asg["id"], make_shopper_headers(sid)))
    validated = validate_success(api.validate_assignment(asg["id"], make_qa_validator_headers()))
    # reliability 80 -> MID 0.10: 2000 + round_half_up(2000*0.10=200) = 2200.
    assert validated["shopper_fee_cents"] == 2200, (
        f"shopper_fee_cents expected 2200 (MID tier at 80), got {validated['shopper_fee_cents']}"
    )


# ---------------------------------------------------------------------------
# calculations / reimbursement_cap_clamps_oversized_receipt
# ---------------------------------------------------------------------------
def test_reimbursement_cap_clamps_oversized_receipt(api):
    """PRD 3.6: "That final out-of-pocket figure is capped at the script's
    reimburse_cap_cents (the smaller of the two), and the final reimbursable_cents
    is the capped out-of-pocket plus the same mileage component (frozen
    travel_distance_km times 35 cents per kilometer, rounded half up at that single
    multiply), with no further rounding."

    Design: Corner/calculations/reimbursement_cap_clamps_oversized_receipt
    """
    fixtures.set_clock("2026-06-01T00:00:00Z")
    client = fixtures.register_client(fee_per_completed_shop_cents=15000)
    cid = client["id"]
    # Location at shopper home -> travel 0, mileage 0.
    location = fixtures.create_location(cid, scenario_family="RETAIL", lat=40.0, lng=-74.0)
    script = fixtures.create_and_publish_script(
        cid, scenario_family="RETAIL", weights_json={"greeting": 1.0},
        required_photo_count=0, receipt_required=True, reimburse_cap_cents=5000,
        base_fee_cents=2000,
    )
    wave = fixtures.create_and_publish_wave(cid)
    shopper = fixtures.register_shopper(tax_id_on_file=True, home_lat=40.0, home_lng=-74.0)
    fixtures.certify_shopper(shopper["id"], scenario_family="RETAIL")
    asg = fixtures.create_in_field_assignment(
        cid, wave["id"], shopper["id"], location["id"], script["id"],
        "2026-06-20T00:00:00Z",
    )
    aid, sid = asg["id"], shopper["id"]
    fixtures.add_reviewed_evidence(aid, sid, "RECEIPT", "APPROVE",
                                   object_uri="s3://e/r.jpg", receipt_amount_cents=9000)
    fixtures.create_scorecard(aid, sid, {"greeting": 88})
    validate_success(api.submit_assignment(aid, make_shopper_headers(sid)))
    validated = validate_success(api.validate_assignment(aid, make_qa_validator_headers()))
    # min(9000, 5000) + mileage 0 = 5000.
    assert validated["reimbursable_cents"] == 5000, (
        f"reimbursable_cents expected 5000 (cap clamp), got {validated['reimbursable_cents']}"
    )
