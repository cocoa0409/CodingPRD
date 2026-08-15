"""Strike-confirm cascade chain and the reject-side conservation invariant."""
import pytest

from test_helpers import (
    validate_success,
    set_clock,
    create_species,
    setup_airport_with_biologists,
    create_draft_strike,
    create_under_review_strike,
    create_confirmed_strike,
    confirm_n_strikes,
    confirm_strike,
    submit_strike,
    begin_review_strike,
    get_airport,
    ApiErrorId,
)


class TestStrikeConfirmCascadeChain:
    """confirm -> auto-create carcass -> recompute strike counts ->
    recompute hazard level (depth-3 cascade from one trigger)."""

    def test_tenth_confirm_recomputes_counts_and_hazard(self, api):
        """PRD §3.2: "on success the server stamps `confirmed_by_biologist_id`
        with the acting biologist's `id`, recomputes the airport's
        trailing-twelve-month strike counts, recomputes the airport's
        `current_hazard_level`"
        PRD §3.5: "otherwise if `strikes_trailing_12m` is at least 10, the
        base is `HIGH`"

        Design: Difficulty/transitive_cascade/strike_confirm_cascade_chain_3_hops
        """
        set_clock()
        airport, b1, b2, b1h, b2h = setup_airport_with_biologists(
            icao_code="KGGG", cert_senior="CERT-601", cert_junior="CERT-602",
        )
        sp = create_species(
            common_name="Turkey Vulture", scientific_name="Cathartes aura",
            guild="RAPTOR", risk_tier="HIGH", body_mass_g=2000,
            is_protected_federally=True,
        )
        confirm_n_strikes(airport["id"], b2, b1, sp["id"], count=9,
                          registration_prefix="N4")
        tenth = create_under_review_strike(
            airport["id"], b2, b1, sp["id"], strike_at="2026-07-10T00:00:00Z",
            carcass_present=True, aircraft_registration="N410",
        )
        confirm_strike(tenth["id"], b1, notes="10th strike")

        airport_after = get_airport(airport["id"], b1h)
        assert airport_after["strikes_trailing_12m"] == 10
        assert airport_after["current_hazard_level"] == "HIGH", (
            f"expected HIGH at 10 confirmed strikes, got "
            f"{airport_after['current_hazard_level']}"
        )

    def test_confirm_auto_creates_carcass_with_strike_species(self, api):
        """PRD §3.2: "if `carcass_present` is `true` and no `CarcassRecord`
        yet exists for this strike — auto-creates a `CarcassRecord` in
        `COLLECTED` with `species_id_at_collection` set to the strike's
        `species_id`."

        Design: Difficulty/transitive_cascade/strike_confirm_cascade_chain_3_hops
        """
        set_clock()
        airport, b1, b2, b1h, b2h = setup_airport_with_biologists(
            icao_code="KGGH", cert_senior="CERT-611", cert_junior="CERT-612",
        )
        sp = create_species(
            common_name="Turkey Vulture", scientific_name="Cathartes aura",
            guild="RAPTOR", risk_tier="HIGH", body_mass_g=2000,
            is_protected_federally=True,
        )
        strike = create_confirmed_strike(
            airport["id"], b2, b1, sp["id"], strike_at="2026-07-10T00:00:00Z",
            carcass_present=True, aircraft_registration="N410",
        )
        rows = validate_success(
            api.list_carcass_records_for_strike(strike["id"], b1h), 200,
        )
        assert len(rows) == 1, f"expected 1 auto-created carcass, got {len(rows)}"
        assert rows[0]["identification_status"] == "COLLECTED"
        assert rows[0]["species_id_at_collection"] == sp["id"]


class TestRejectConservationInvariant:
    """Rejecting a strike never alters the CONFIRMED-only trailing counts."""

    def test_reject_leaves_trailing_count_unchanged(self, api):
        """PRD §3.5: "`strikes_trailing_12m` counts every `CONFIRMED` strike
        at the airport with `strike_at` no earlier than three hundred
        sixty-five days before now"
        PRD §3.2: "Rejecting the strike (`UNDER_REVIEW → REJECTED`) requires
        only the segregation-of-duties check."

        Design: Difficulty/compensating_invariant/airport_hazard_level_recompute_invariant_after_strike_reject
        """
        set_clock()
        airport, b1, b2, b1h, b2h = setup_airport_with_biologists(
            icao_code="KRRR", cert_senior="CERT-1701", cert_junior="CERT-1702",
        )
        sp = create_species(
            common_name="Ring-billed Gull", scientific_name="Larus delawarensis",
            guild="GULL", risk_tier="MEDIUM", body_mass_g=550,
            is_protected_federally=True,
        )
        confirm_n_strikes(airport["id"], b2, b1, sp["id"], count=5,
                          registration_prefix="N9")
        baseline = get_airport(airport["id"], b1h)
        assert baseline["strikes_trailing_12m"] == 5
        assert baseline["current_hazard_level"] == "ELEVATED"

        strike = create_under_review_strike(
            airport["id"], b2, b1, sp["id"], strike_at="2026-07-10T00:00:00Z",
            aircraft_registration="N906",
        )
        rejected = validate_success(api.reject_strike_report(strike["id"], b1h), 200)
        assert rejected["status"] == "REJECTED"

        after = get_airport(airport["id"], b1h)
        assert after["strikes_trailing_12m"] == 5, (
            f"reject must not change the CONFIRMED-only count, got "
            f"{after['strikes_trailing_12m']}"
        )
        assert after["current_hazard_level"] == "ELEVATED"

    def test_under_review_strike_not_counted_before_decision(self, api):
        """PRD §3.5: "`strikes_trailing_12m` counts every `CONFIRMED` strike
        at the airport" — a strike still UNDER_REVIEW is not CONFIRMED and is
        excluded from the count.

        Design: Difficulty/compensating_invariant/airport_hazard_level_recompute_invariant_after_strike_reject
        """
        set_clock()
        airport, b1, b2, b1h, b2h = setup_airport_with_biologists(
            icao_code="KRRS", cert_senior="CERT-1711", cert_junior="CERT-1712",
        )
        sp = create_species(
            common_name="Ring-billed Gull", scientific_name="Larus delawarensis",
            guild="GULL", risk_tier="MEDIUM", body_mass_g=550,
            is_protected_federally=True,
        )
        confirm_n_strikes(airport["id"], b2, b1, sp["id"], count=5,
                          registration_prefix="N8")
        create_under_review_strike(
            airport["id"], b2, b1, sp["id"], strike_at="2026-07-10T00:00:00Z",
            aircraft_registration="N907",
        )

        airport_after = get_airport(airport["id"], b1h)
        assert airport_after["strikes_trailing_12m"] == 5, (
            f"UNDER_REVIEW strike must not enter the count, got "
            f"{airport_after['strikes_trailing_12m']}"
        )
        assert airport_after["current_hazard_level"] == "ELEVATED"
