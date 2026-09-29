"""The brand-protection cascade: frozen risk points, the posture thresholds, the
claims a confirmation holds, and the posture gate on approval."""

from test_helpers import (
    ApiErrorId,
    api_client,
    approve_claim_payload,
    clear_hold,
    confirm_report,
    create_report,
    make_warranty_administrator_headers,
    read_claim,
    read_claimant,
    read_lot,
    read_program,
    read_sku,
    setup_released_lot,
    setup_sku_with_confirmed_reports,
    setup_warranty_scenario,
    validate_error,
)

WA_2 = make_warranty_administrator_headers("wa-2")
WA_3 = make_warranty_administrator_headers("wa-3")

STRONG_HIGH_VOLUME_SIGHTING = {
    "channel_name": "OpenBazaar",
    "seller_handle": "torque_deals_99",
    "evidence_grade": "STRONG",
    "unit_estimate": 600,
}
PROFESSIONAL_SOCKET = {
    "sku_code": "SK-19-PRO",
    "tool_family": "SOCKET",
    "channel": "PROFESSIONAL",
    "nominal_size_mm": 19,
    "alloy_grade": "CR_V",
    "list_price_cents": 2600,
    "warranty_tier": "LIFETIME",
}
HANDLE_LINE = {"component_code": "HANDLE", "component_list_price_cents": 1099, "quantity": 1}


# ---------------------------------------------------------------------------
# Confirmation cascades onto the SKU, its claims and their claimant
# ---------------------------------------------------------------------------


def _open_claim_and_a_pending_sighting():
    """A BRANDED SKU with one SUBMITTED claim against it and one OPEN
    counterfeit report worth 50 frozen points."""
    ctx = setup_warranty_scenario()
    ctx["report"] = create_report(ctx["sku"]["id"], **STRONG_HIGH_VOLUME_SIGHTING)
    return ctx


def test_confirming_a_sighting_rolls_its_frozen_points_into_the_brand_risk_score():
    """STRONG evidence and an estimate above 500 units give 50 points on a BRANDED
    SKU, which lands the posture in the RESTRICTED band.

    PRD §3.9: "Link three re-derives `warranty_posture` from that score against
    two inclusive thresholds: a score of 85 or more makes the posture
    `SUSPENDED`, a score of 40 or more but below 85 makes it `RESTRICTED`, and
    anything below 40 leaves it `OPEN`."

    Design: Difficulty/transitive_cascade/counterfeit_confirm_cascades_to_claim_fraud_hold
    """
    ctx = _open_claim_and_a_pending_sighting()
    assert ctx["report"]["risk_points"] == 50
    assert ctx["report"]["status"] == "OPEN"
    assert read_sku(ctx["sku"]["id"])["brand_risk_score"] == 0

    confirmed = confirm_report(ctx["report"]["id"])

    assert confirmed["status"] == "CONFIRMED"
    assert confirmed["risk_points"] == 50

    sku = read_sku(ctx["sku"]["id"])
    assert sku["brand_risk_score"] == 50
    assert sku["confirmed_counterfeit_count"] == 1
    assert sku["warranty_posture"] == "RESTRICTED"


def test_the_cascade_holds_every_open_claim_on_the_sku_without_naming_a_holder():
    """The system, not a person, placed the hold, so the literal cascade reason is
    stored and no user identifier is recorded.

    PRD §3.9: "Every warranty claim on that SKU currently in `SUBMITTED` status is
    moved `SUBMITTED → FRAUD_HOLD` with `hold_reason` set to the literal string
    `COUNTERFEIT_POSTURE` and `held_by_user_id` left null — the hold was placed by
    the system, not by a person, so it constrains no future clearer or approver."

    Design: Difficulty/transitive_cascade/counterfeit_confirm_cascades_to_claim_fraud_hold
    """
    ctx = _open_claim_and_a_pending_sighting()
    assert ctx["claim"]["status"] == "SUBMITTED"

    confirm_report(ctx["report"]["id"])

    claim = read_claim(ctx["claim"]["id"])
    assert claim["status"] == "FRAUD_HOLD"
    assert claim["hold_reason"] == "COUNTERFEIT_POSTURE"
    assert claim["held_by_user_id"] is None

    program = read_program(ctx["program"]["id"])
    assert program["open_hold_count"] == 1
    assert program["reserve_balance_cents"] == 5_000_000


def test_the_cascade_reprices_the_adjudication_score_with_the_counterfeit_term():
    """One claim at nine points plus the 25 point counterfeit term for a SKU whose
    posture is no longer OPEN gives an adjudication score of 34.

    PRD §3.9: "Link five recomputes the adjudication fraud score of every claimant
    touched by link four, and those scores now carry the 25-point counterfeit term
    for each of that claimant's claims sitting on a SKU whose posture is not
    `OPEN` — which is how one confirmed sighting can push an otherwise ordinary
    claimant above a programme's `fraud_score_threshold`."

    Design: Difficulty/transitive_cascade/counterfeit_confirm_cascades_to_claim_fraud_hold
    """
    ctx = _open_claim_and_a_pending_sighting()

    confirm_report(ctx["report"]["id"])

    claimant = read_claimant(ctx["claimant"]["id"])
    assert claimant["fraud_risk_score_adjudication"] == 34


# ---------------------------------------------------------------------------
# The inclusive 40 point threshold
# ---------------------------------------------------------------------------


def _professional_socket_at_thirty_six_points():
    """A PROFESSIONAL socket carrying two confirmed sightings worth 36 points and
    a third still OPEN worth 4."""
    sku, filed = setup_sku_with_confirmed_reports(
        [
            {"evidence_grade": "MODERATE", "unit_estimate": 20, "action": "confirm"},
            {"evidence_grade": "STRONG", "unit_estimate": 30, "action": "confirm"},
            {"evidence_grade": "WEAK", "unit_estimate": 10, "action": "open"},
        ],
        sku_overrides=PROFESSIONAL_SOCKET,
    )
    return sku, filed


def test_report_risk_points_are_frozen_from_the_evidence_and_the_channel_exposure():
    """On a PROFESSIONAL SKU the 0.8 exposure factor turns 15, 30 and 5 raw points
    into 12, 24 and 4.

    PRD §3.9: "Those two contributions are added, then multiplied by the channel
    exposure factor of the SKU — 1.0 for `BRANDED`, since a counterfeit of the
    flagship brand does the most damage, 0.6 for `PRIVATE_LABEL` and 0.8 for
    `PROFESSIONAL` — and the product is rounded half up to a whole number of
    points."

    Design: Difficulty/boundary_precision_check/brand_risk_score_exactly_forty_flips_posture_restricted
    """
    _, filed = _professional_socket_at_thirty_six_points()

    assert [report["risk_points"] for report in filed] == [12, 24, 4]


def test_thirty_six_confirmed_points_leave_the_posture_open():
    """Two confirmations total 36 points, one short of the RESTRICTED band, and the
    third report is still OPEN so it contributes nothing.

    PRD §3.9: "A new report is `OPEN` with `confirmation_note` and
    `dismissal_note` null, and an `OPEN` report contributes **nothing** to the
    SKU: `brand_risk_score` is untouched until an analyst confirms the sighting."

    Design: Difficulty/boundary_precision_check/brand_risk_score_exactly_forty_flips_posture_restricted
    """
    sku, filed = _professional_socket_at_thirty_six_points()

    assert sku["brand_risk_score"] == 36
    assert sku["warranty_posture"] == "OPEN"
    assert sku["confirmed_counterfeit_count"] == 2
    assert filed[2]["status"] == "OPEN"


def test_the_fortieth_point_flips_the_posture_to_restricted_and_not_suspended():
    """Confirming the four-point sighting brings the total to exactly 40, which is
    inclusive of the RESTRICTED threshold and well below the SUSPENDED one.

    PRD §3.9: "A professional-channel SKU whose confirmed reports total exactly 40
    points is `RESTRICTED`; at 39 it is still `OPEN`."

    Design: Difficulty/boundary_precision_check/brand_risk_score_exactly_forty_flips_posture_restricted
    """
    sku, filed = _professional_socket_at_thirty_six_points()

    confirm_report(filed[2]["id"])

    sku = read_sku(sku["id"])
    assert sku["brand_risk_score"] == 40
    assert sku["warranty_posture"] == "RESTRICTED"
    assert sku["warranty_posture"] != "SUSPENDED"
    assert sku["confirmed_counterfeit_count"] == 3


# ---------------------------------------------------------------------------
# The posture gate on approval
# ---------------------------------------------------------------------------


def _cleared_claim_on_a_restricted_sku():
    """A claim on a released, certified SKU that a confirmed counterfeit pushed to
    RESTRICTED, then cleared off hold by a second administrator."""
    lot_ctx = setup_released_lot()
    ctx = setup_warranty_scenario(sku_id=lot_ctx["sku"]["id"], lines=(HANDLE_LINE,))
    ctx["lot"] = lot_ctx["lot"]
    ctx["report"] = confirm_report(
        create_report(ctx["sku"]["id"], **STRONG_HIGH_VOLUME_SIGHTING)["id"]
    )
    ctx["claim"] = clear_hold(
        ctx["claim"]["id"], WA_2, clearance_note="Independent review complete"
    )
    return ctx


def test_approval_is_refused_while_the_sku_posture_is_restricted():
    """The claim is back at SUBMITTED with a matching programme version, but a
    RESTRICTED posture blocks approval outright.

    PRD §3.8: "The SKU's `warranty_posture` must be `OPEN`, with both `RESTRICTED`
    and `SUSPENDED` blocking (`ERR_SKU_WARRANTY_RESTRICTED`)."

    Design: Difficulty/cross_entity_state_dependency/claim_approve_requires_sku_posture_open
    """
    ctx = _cleared_claim_on_a_restricted_sku()
    program = read_program(ctx["program"]["id"])

    validate_error(
        api_client.approve_warranty_claim(
            ctx["claim"]["id"], approve_claim_payload(program["version"]), WA_3
        ),
        ApiErrorId.ERR_SKU_WARRANTY_RESTRICTED,
        409,
    )

    sku = read_sku(ctx["sku"]["id"])
    assert sku["warranty_posture"] == "RESTRICTED"
    assert sku["brand_risk_score"] == 50


def test_a_manual_clearance_does_not_waive_the_posture_gate():
    """fraud_cleared is true, which waives only the score gate; the refusal leaves
    both ledgers and the released lot untouched.

    PRD §3.8: "The claimant's `fraud_risk_score_adjudication` must be strictly
    below the programme's `fraud_score_threshold`, **unless** `fraud_cleared` is
    true, in which case a manual clearance waives this gate — but note that
    clearance waives only the score gate and never the posture gate
    (`ERR_FRAUD_SCORE_TOO_HIGH`)."

    Design: Difficulty/cross_entity_state_dependency/claim_approve_requires_sku_posture_open
    """
    ctx = _cleared_claim_on_a_restricted_sku()
    program = read_program(ctx["program"]["id"])
    validate_error(
        api_client.approve_warranty_claim(
            ctx["claim"]["id"], approve_claim_payload(program["version"]), WA_3
        ),
        ApiErrorId.ERR_SKU_WARRANTY_RESTRICTED,
    )

    claim = read_claim(ctx["claim"]["id"])
    assert claim["status"] == "SUBMITTED"
    assert claim["fraud_cleared"] is True

    assert read_program(ctx["program"]["id"])["reserve_balance_cents"] == 5_000_000

    sku = read_sku(ctx["sku"]["id"])
    assert sku["units_on_hand"] == 500
    assert sku["units_reserved"] == 0

    lot = read_lot(ctx["lot"]["id"])
    assert lot["disposition"] == "RELEASED"
    assert lot["cert_status"] == "CERTIFIED"
