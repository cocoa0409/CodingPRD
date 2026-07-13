"""Due-date variants and hazard-survey risk tiering (dual-variant / combinatorial calcs)."""
from test_helpers import (
    validate_success, TEST_USERS, factories, fixtures,
)

ADMIN = TEST_USERS["admin_headers"]


# --------------------------------------------------------------------------- #
# Difficulty/dual_variant_calc/device_due_date_from_install_vs_from_last_pass
# --------------------------------------------------------------------------- #
def test_due_date_shifts_to_from_last_pass_after_accepted_pass(api):
    """PRD §3.3: "the device's `last_pass_date` is set to the report's `test_date`, the
    device's `next_test_due_date` is recomputed from that new pass baseline (the
    from-last-pass variant of §3.1), and the connection's posture is recomputed".

    Design: Difficulty/dual_variant_calc/device_due_date_from_install_vs_from_last_pass
    """
    conn = fixtures.create_connection(api, ADMIN)
    dev = fixtures.create_device(conn["id"], api, ADMIN, device_type="RP", hazard_rating="HIGH",
                                 install_date="2025-03-01T00:00:00Z")
    tester = fixtures.create_tester(api, ADMIN)
    report = fixtures.submit_report(dev["id"], tester["id"], api, test_date="2026-02-15T00:00:00Z",
                                    relief_valve_differential_psid=2.5, check_valve_1_psid=1.5)
    fixtures.accept_report(report["id"], api, ADMIN)
    data = validate_success(api.get_device(dev["id"], ADMIN))
    assert data["last_pass_date"][:10] == "2026-02-15", \
        f"expected last_pass_date 2026-02-15, got {data['last_pass_date']}"
    assert data["next_test_due_date"][:10] == "2027-02-15", \
        f"expected from_last_pass due 2027-02-15, got {data['next_test_due_date']}"


def test_due_date_is_from_install_before_any_pass(api):
    """PRD §3.1: "Before the device has any accepted passing test — while `last_pass_date`
    is null — the baseline is the `install_date`."
    PRD §3.1: "Once a passing test is accepted the baseline shifts to `last_pass_date`
    (see §3.3), which produces a strictly later due date than the install-based value."

    Design: Difficulty/dual_variant_calc/device_due_date_from_install_vs_from_last_pass
    """
    conn = fixtures.create_connection(api, ADMIN)
    payload = factories.device_payload(conn["id"], serial_number="SN-DUE-FI", device_type="RP",
                                       hazard_rating="HIGH", test_interval_months=12,
                                       install_date="2025-03-01T00:00:00Z")
    data = validate_success(api.create_device(payload, ADMIN), expected_status=201)
    assert data["last_pass_date"] in (None, ""), \
        f"expected last_pass_date null before any pass, got {data['last_pass_date']}"
    assert data["next_test_due_date"][:10] == "2026-03-01", \
        f"expected from_install due 2026-03-01, got {data['next_test_due_date']}"


# --------------------------------------------------------------------------- #
# Difficulty/dual_variant_calc/risk_tier_assessed_low_vs_effective_high
# --------------------------------------------------------------------------- #
def test_survey_assessed_low_but_effective_high_from_device_floor(api):
    """PRD §3.5: "The `assessed_risk_tier` is the higher of the base tier and the floor,
    ranking the tiers `LOW` below `MODERATE` below `HIGH`."
    PRD §3.5: "if any device on the connection with status `ACTIVE` or `NEEDS_REPAIR` has a
    `hazard_rating` of `HIGH`, the device floor is `HIGH`, otherwise `LOW`; the effective
    tier is the higher of `assessed_risk_tier` and that device floor."

    Design: Difficulty/dual_variant_calc/risk_tier_assessed_low_vs_effective_high
    """
    conn = fixtures.create_connection(api, ADMIN)
    fixtures.create_device(conn["id"], api, ADMIN, device_type="RP", hazard_rating="HIGH",
                           install_date="2026-01-01T00:00:00Z")
    survey = fixtures.create_and_finalize_survey(conn["id"], api, ADMIN, premise_use_score=20,
                                                 chemical_exposure_score=30, auxiliary_supply_score=10)
    assert survey["assessed_risk_tier"] == "LOW", \
        f"weighted 21 with no floor -> assessed LOW, got {survey['assessed_risk_tier']}"
    assert survey["effective_risk_tier"] == "HIGH", \
        f"HIGH device floor -> effective HIGH, got {survey['effective_risk_tier']}"


def test_connection_risk_tier_written_from_effective_tier(api):
    """PRD §3.5: "On finalization the connection's `risk_tier` is set to this
    `effective_risk_tier`, any prior `FINALIZED` survey on the same connection is moved to
    `SUPERSEDED`, the connection's posture is recomputed, and the connection's `version` is
    incremented by one."

    Design: Difficulty/dual_variant_calc/risk_tier_assessed_low_vs_effective_high
    """
    conn = fixtures.create_connection(api, ADMIN)
    fixtures.create_device(conn["id"], api, ADMIN, device_type="RP", hazard_rating="HIGH",
                           install_date="2026-01-01T00:00:00Z")
    fixtures.create_and_finalize_survey(conn["id"], api, ADMIN, premise_use_score=20,
                                        chemical_exposure_score=30, auxiliary_supply_score=10)
    data = validate_success(api.get_connection(conn["id"], ADMIN))
    assert data["risk_tier"] == "HIGH", \
        f"connection risk_tier should equal effective HIGH, got {data['risk_tier']}"


# --------------------------------------------------------------------------- #
# Difficulty/combinatorial_formula/risk_score_weighted_with_chemical_high_floor
# --------------------------------------------------------------------------- #
def test_chemical_high_floor_overrides_low_weighted_tier(api):
    """PRD §3.5: "A conditional floor is then applied from individual inputs: the floor is
    `HIGH` if `chemical_exposure_score` is at least 35; otherwise the floor is `MODERATE`
    if `auxiliary_supply_score` is at least 30; otherwise the floor is `LOW`. The
    `assessed_risk_tier` is the higher of the base tier and the floor, ranking the tiers
    `LOW` below `MODERATE` below `HIGH`."

    Design: Difficulty/combinatorial_formula/risk_score_weighted_with_chemical_high_floor
    """
    conn = fixtures.create_connection(api, ADMIN)
    survey = fixtures.create_and_finalize_survey(conn["id"], api, ADMIN, premise_use_score=20,
                                                 chemical_exposure_score=35, auxiliary_supply_score=10)
    assert survey["assessed_risk_tier"] == "HIGH", \
        f"chemical 35 forces HIGH floor over the LOW weighted (23) tier, got {survey['assessed_risk_tier']}"


def test_chemical_high_floor_propagates_to_connection_risk_tier(api):
    """PRD §3.5: "On finalization the connection's `risk_tier` is set to this
    `effective_risk_tier`".

    Design: Difficulty/combinatorial_formula/risk_score_weighted_with_chemical_high_floor
    """
    conn = fixtures.create_connection(api, ADMIN)
    fixtures.create_and_finalize_survey(conn["id"], api, ADMIN, premise_use_score=20,
                                        chemical_exposure_score=35, auxiliary_supply_score=10)
    data = validate_success(api.get_connection(conn["id"], ADMIN))
    assert data["risk_tier"] == "HIGH", \
        f"no devices -> effective == assessed HIGH -> connection risk_tier HIGH, got {data['risk_tier']}"
