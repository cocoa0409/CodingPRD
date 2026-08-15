"""Hazard-posture engine: promotion order, strike-count boundaries,
CRITICAL gating of strike submission, and the non-persisting preview."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    set_clock,
    create_airport,
    create_species,
    setup_airport_with_biologists,
    setup_overdue_mitigation_scenario,
    create_draft_advisory,
    activate_advisory,
    create_draft_strike,
    create_under_review_strike,
    confirm_n_strikes,
    confirm_strike,
    force_airport_hazard,
    get_airport,
    make_biologist_headers,
    ApiErrorId,
)


class TestHazardPromotionOrder:
    """Bottom-up recompute: strikes base -> advisory bump -> overdue bump."""

    def test_advisory_high_promotes_airport_to_high_with_overdue_mitigation(self, api):
        """PRD §3.5: "Second, any `ACTIVE` advisory on the airport can only
        raise the level: if any active advisory declares a hazard level more
        severe than the current base, the level is promoted to that advisory's
        level, with `CRITICAL` outranking `HIGH` outranking `ELEVATED`
        outranking `LOW`."

        Design: Difficulty/combinatorial_formula/airport_hazard_level_threshold_promotion_order
        """
        ctx = setup_overdue_mitigation_scenario(icao_code="KCCC")
        airport = ctx["airport"]
        # Sanity: the mitigation is IN_PROGRESS and overdue (target 2026-07-01
        # precedes the logical clock 2026-08-01).
        assert ctx["action"]["status"] == "IN_PROGRESS"

        advisory = create_draft_advisory(
            airport["id"], ctx["b1"], hazard_level="HIGH",
            effective_from="2026-07-30T00:00:00Z",
            effective_to="2026-09-30T00:00:00Z",
            issued_at="2026-07-30T00:00:00Z",
        )
        activate_advisory(advisory["id"], ctx["b1"], airport["id"])

        airport_after = get_airport(airport["id"], ctx["b1_headers"])
        assert airport_after["current_hazard_level"] == "HIGH", (
            f"expected HIGH (advisory bump over LOW strike base), got "
            f"{airport_after['current_hazard_level']}"
        )

    def test_advisory_elevated_promotes_only_to_elevated(self, api):
        """PRD §3.5: "if any active advisory declares a hazard level more
        severe than the current base, the level is promoted to that advisory's
        level"
        PRD §3.5: "otherwise the base is `LOW`." (zero confirmed strikes)

        Design: Difficulty/combinatorial_formula/airport_hazard_level_threshold_promotion_order
        """
        ctx = setup_overdue_mitigation_scenario(icao_code="KCCD")
        airport = ctx["airport"]
        advisory = create_draft_advisory(
            airport["id"], ctx["b1"], hazard_level="ELEVATED",
            effective_from="2026-07-30T00:00:00Z",
            effective_to="2026-09-30T00:00:00Z",
            reason_code="MIGRATION",
            issued_at="2026-07-30T01:00:00Z",
        )
        activated = activate_advisory(advisory["id"], ctx["b1"], airport["id"])
        assert activated["status"] == "ACTIVE"

        airport_after = get_airport(airport["id"], ctx["b1_headers"])
        assert airport_after["current_hazard_level"] == "ELEVATED", (
            f"expected promotion to exactly the advisory's level (ELEVATED), "
            f"got {airport_after['current_hazard_level']}"
        )


class TestStrikesCountThresholdBoundary:
    """strikes_trailing_12m >= 10 promotes the base level to HIGH."""

    def test_nine_confirmed_strikes_yield_elevated(self, api):
        """PRD §3.5: "otherwise if `strikes_trailing_12m` is at least 10, the
        base is `HIGH`; otherwise if it is at least 5, the base is `ELEVATED`;
        otherwise the base is `LOW`."

        Design: Difficulty/boundary_precision_check/strikes_count_threshold_at_exact_boundary
        """
        set_clock()
        airport, b1, b2, b1h, b2h = setup_airport_with_biologists(
            icao_code="KKKK", cert_senior="CERT-1001", cert_junior="CERT-1002",
        )
        sp = create_species(
            common_name="Ring-billed Gull", scientific_name="Larus delawarensis",
            guild="GULL", risk_tier="MEDIUM", body_mass_g=550,
            is_protected_federally=True,
        )
        confirm_n_strikes(airport["id"], b2, b1, sp["id"], count=9)

        airport_after = get_airport(airport["id"], b1h)
        assert airport_after["strikes_trailing_12m"] == 9
        assert airport_after["current_hazard_level"] == "ELEVATED", (
            f"9 strikes (>= 5 but < 10) must yield ELEVATED, got "
            f"{airport_after['current_hazard_level']}"
        )

    def test_tenth_confirmed_strike_yields_high(self, api):
        """PRD §3.5: "otherwise if `strikes_trailing_12m` is at least 10, the
        base is `HIGH`" — the boundary is inclusive (at least 10, not more
        than 10).

        Design: Difficulty/boundary_precision_check/strikes_count_threshold_at_exact_boundary
        """
        set_clock()
        airport, b1, b2, b1h, b2h = setup_airport_with_biologists(
            icao_code="KKKL", cert_senior="CERT-1011", cert_junior="CERT-1012",
        )
        sp = create_species(
            common_name="Herring Gull", scientific_name="Larus argentatus",
            guild="GULL", risk_tier="MEDIUM", body_mass_g=1000,
            is_protected_federally=True,
        )
        confirm_n_strikes(airport["id"], b2, b1, sp["id"], count=9,
                          registration_prefix="N6")
        tenth = create_under_review_strike(
            airport["id"], b2, b1, sp["id"], strike_at="2026-07-10T00:00:00Z",
            aircraft_registration="N610",
        )
        confirm_strike(tenth["id"], b1, notes="10")

        airport_after = get_airport(airport["id"], b1h)
        assert airport_after["strikes_trailing_12m"] == 10
        assert airport_after["current_hazard_level"] == "HIGH", (
            f"10 strikes (>= 10) must yield HIGH, got "
            f"{airport_after['current_hazard_level']}"
        )


class TestStrikeSubmitHazardGate:
    """CRITICAL posture blocks DRAFT -> SUBMITTED; lesser postures do not."""

    def test_submit_blocked_when_airport_critical(self, api):
        """PRD §2.8: "A `CRITICAL` posture is a hard stop on four operations
        across the system: submitting a new strike report from `DRAFT` to
        `SUBMITTED`, starting work on an approved mitigation action,
        publishing an approved annual plan, and releasing an active runway
        closure back to operations. All four reject with
        `ERR_HAZARD_CRITICAL_BLOCK` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/strike_submit_blocked_by_airport_hazard_critical
        """
        set_clock()
        airport, b1, b2, b1h, b2h = setup_airport_with_biologists(
            icao_code="KMMM", cert_senior="CERT-1201", cert_junior="CERT-1202",
        )
        sp = create_species(
            common_name="Ring-billed Gull", scientific_name="Larus delawarensis",
            guild="GULL", risk_tier="MEDIUM", body_mass_g=550,
            is_protected_federally=True,
        )
        airport = force_airport_hazard(airport["id"], b2, b1, sp["id"], "CRITICAL")
        assert airport["current_hazard_level"] == "CRITICAL"

        strike = create_draft_strike(
            airport["id"], b2, sp["id"], aircraft_registration="N703",
        )
        res = api.submit_strike_report(strike["id"], b2h)
        validate_error(res, ApiErrorId.ERR_HAZARD_CRITICAL_BLOCK.value, expected_status=409)

        strike_after = validate_success(api.get_strike_report(strike["id"], b1h), 200)
        assert strike_after["status"] == "DRAFT"

    def test_submit_allowed_when_airport_high(self, api):
        """PRD §2.8: "A `CRITICAL` posture is a hard stop on four operations
        across the system" — HIGH is not CRITICAL, so submission proceeds.
        PRD §3.2: "Submitting a draft transitions it `DRAFT → SUBMITTED` and
        bumps the report's `version`."

        Design: Difficulty/cross_entity_state_dependency/strike_submit_blocked_by_airport_hazard_critical
        """
        set_clock()
        airport, b1, b2, b1h, b2h = setup_airport_with_biologists(
            icao_code="KMMN", cert_senior="CERT-1211", cert_junior="CERT-1212",
        )
        sp = create_species(
            common_name="American Crow", scientific_name="Corvus brachyrhynchos",
            guild="SONGBIRD", risk_tier="MEDIUM", body_mass_g=500,
            is_protected_federally=False,
        )
        airport = force_airport_hazard(airport["id"], b2, b1, sp["id"], "HIGH")
        assert airport["current_hazard_level"] == "HIGH"

        strike = create_draft_strike(
            airport["id"], b2, sp["id"], aircraft_registration="N704",
        )
        submitted = validate_success(api.submit_strike_report(strike["id"], b2h), 200)
        assert submitted["status"] == "SUBMITTED"


def test_hazard_preview_computed_read(api, admin_headers):
    """PRD §3.5: "A separate what-if projection endpoint evaluates the same
    algorithm against a caller-supplied `as_of` timestamp without persisting
    anything, returning the projected level alongside the projected
    trailing-window counts."

    Design: Corner/endpoints/hazard_preview_computed_read
    """
    set_clock()
    airport = create_airport(icao_code="KPPP", name="Papa Airport")

    preview = validate_success(
        api.get_hazard_preview(airport["id"], "2026-08-01T00:00:00Z", admin_headers),
        200,
    )
    assert preview["projected_hazard_level"] == "LOW", (
        f"zero strikes must project LOW, got {preview['projected_hazard_level']}"
    )

    airport_after = validate_success(api.get_airport(airport["id"], admin_headers), 200)
    assert airport_after["current_hazard_level"] == "LOW"
    assert airport_after["strikes_trailing_12m"] == 0
    assert airport_after["version"] == 1, (
        "preview must not persist anything; airport version stays at 1"
    )
