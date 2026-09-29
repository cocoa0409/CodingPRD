"""Licence risk: the rolling and lifetime variants, and the reopen compensation."""

from test_helpers import (
    OFFICER_A_HEADERS,
    OFFICER_B_HEADERS,
    assert_score_equal,
    factories as f,
    fixtures as fx,
    validate_success,
)

AUGUST_CLOCK = "2026-08-02T00:00:00Z"
NOVEMBER_THIRD_CLOCK = "2026-11-03T00:00:00Z"
NOVEMBER_EIGHTH_CLOCK = "2026-11-08T00:00:00Z"
DECEMBER_CLOCK = "2026-12-01T00:00:00Z"
SUMMER_CLOCK = "2026-08-20T12:00:00Z"


def _decoy_probe(api, partner, courier, customer, jurisdiction, scheduled_at, scenario_type):
    """A staged probe needs a decoy order to hang the secret-shopper test from."""
    decoy = fx.create_order(
        api,
        customer["id"],
        jurisdiction["id"],
        partner["id"],
        scheduled_at,
        0,
    )
    return fx.schedule_shopper_test(
        api,
        courier["id"],
        decoy["id"],
        scenario_type=scenario_type,
        scheduled_at=scheduled_at,
    )


def _three_epoch_case_history(api):
    """One `STANDARD` partner carrying MINOR, CRITICAL and MAJOR substantiated cases.

    The three decisions are stamped at three clock positions so that, once the
    clock reaches 2026-12-01, their ages are 121, 28 and 23 days respectively.
    """
    fx.set_clock(api, AUGUST_CLOCK)
    jurisdiction = fx.create_jurisdiction(
        api, code="US-NY", name="New York", dry_status="WET", utc_offset_minutes=-240
    )
    customer = fx.create_customer(api, jurisdiction["id"], full_name="Decoy Buyer")
    partner = fx.create_partner(
        api, legal_name="Empire Last Mile", contract_tier="STANDARD",
        license_reference="NY-DEL-0001",
    )
    courier = fx.create_courier(api, partner["id"], hired_at="2026-07-01")

    probe_minor = _decoy_probe(
        api, partner, courier, customer, jurisdiction,
        "2026-08-02T12:00:00Z", "NO_ID_PRESENTED",
    )
    case_minor = fx.build_substantiated_case(
        api,
        partner["id"],
        secret_shopper_test_id=probe_minor["id"],
        severity="MINOR",
        assessed_severity="MINOR",
    )

    fx.set_clock(api, NOVEMBER_THIRD_CLOCK)
    probe_critical = _decoy_probe(
        api, partner, courier, customer, jurisdiction,
        "2026-11-03T12:00:00Z", "UNDERAGE_PRESENTER",
    )
    case_critical = fx.build_substantiated_case(
        api,
        partner["id"],
        secret_shopper_test_id=probe_critical["id"],
        severity="CRITICAL",
        assessed_severity="CRITICAL",
    )

    fx.set_clock(api, NOVEMBER_EIGHTH_CLOCK)
    probe_major = _decoy_probe(
        api, partner, courier, customer, jurisdiction,
        "2026-11-08T12:00:00Z", "EXPIRED_DOCUMENT",
    )
    case_major = fx.build_substantiated_case(
        api,
        partner["id"],
        secret_shopper_test_id=probe_major["id"],
        severity="MAJOR",
        assessed_severity="MAJOR",
    )

    fx.set_clock(api, DECEMBER_CLOCK)
    return {
        "jurisdiction": jurisdiction,
        "customer": customer,
        "partner": partner,
        "courier": courier,
        "case_minor": case_minor,
        "case_critical": case_critical,
        "case_major": case_major,
    }


def test_01_the_rolling_variant_drops_a_case_older_than_ninety_days(api):
    """PRD 3.9: "The **rolling** variant, written to `license_risk_score`,
    includes only cases whose age is 90 days or fewer and weights every included
    case at 1.00 — a case older than ninety days vanishes from it entirely."

    Design: Difficulty/dual_variant_calc/partner_risk_rolling_versus_lifetime_weighted
    """
    world = _three_epoch_case_history(api)

    assessment = validate_success(
        api.get_risk_assessment(world["partner"]["id"], OFFICER_B_HEADERS)
    )

    assert_score_equal(assessment["rolling_90d_score"], 55.00, "rolling_90d_score")
    assert_score_equal(assessment["tier_multiplier"], 1.00, "tier_multiplier")
    partner = fx.read_partner(api, world["partner"]["id"])
    assert_score_equal(partner["license_risk_score"], 55.00, "license_risk_score")


def test_02_the_lifetime_variant_keeps_that_case_at_a_decayed_weight(api):
    """PRD 3.9: "The **lifetime** variant, written to `lifetime_risk_score`,
    includes every substantiated case forever and weights each by a decaying
    factor: one full point minus a tenth for each complete 90-day step of age,
    floored at a quarter point, so the weight never decays below 0.25."

    Design: Difficulty/dual_variant_calc/partner_risk_rolling_versus_lifetime_weighted
    """
    world = _three_epoch_case_history(api)

    assessment = validate_success(
        api.get_risk_assessment(world["partner"]["id"], OFFICER_B_HEADERS)
    )

    assert_score_equal(assessment["lifetime_weighted_score"], 59.50, "lifetime_weighted_score")
    partner = fx.read_partner(api, world["partner"]["id"])
    assert_score_equal(partner["lifetime_risk_score"], 59.50, "lifetime_risk_score")
    assert float(assessment["lifetime_weighted_score"]) > float(
        assessment["rolling_90d_score"]
    ), (
        "the 121-day-old MINOR case survives in the lifetime variant at a decayed "
        "weight while the rolling variant drops it, so the lifetime figure is larger"
    )


def test_03_only_the_rolling_variant_drives_posture_and_the_per_case_terms(api):
    """PRD 3.9: "Each case's `risk_contribution` field carries that case's own
    per-case rounded term under the **rolling** variant, and is 0.00 whenever the
    case's `state` is anything other than `SUBSTANTIATED`."

    Design: Difficulty/dual_variant_calc/partner_risk_rolling_versus_lifetime_weighted
    """
    world = _three_epoch_case_history(api)

    critical = fx.read_case(api, world["case_critical"]["id"])
    major = fx.read_case(api, world["case_major"]["id"])
    assert_score_equal(critical["risk_contribution"], 40.00, "CRITICAL risk_contribution")
    assert_score_equal(major["risk_contribution"], 15.00, "MAJOR risk_contribution")

    partner = fx.read_partner(api, world["partner"]["id"])
    assert partner["posture"] == "RESTRICTED", (
        "the rolling score 55.00 sits at or above 25.00 but below 60.00, so the "
        f"posture ladder stops at RESTRICTED; got {partner['posture']}"
    )
    assert partner["open_case_count"] == 0
    assert partner["open_critical_case_count"] == 0


# ===========================================================================
# Substantiate, reopen, dismiss: the score must land back where it started
# ===========================================================================
def _one_minor_and_one_open_case(api):
    """A partner scoring 5.00 from a MINOR case, with a MAJOR case still open."""
    fx.set_clock(api, SUMMER_CLOCK)
    jurisdiction = fx.create_jurisdiction(
        api, code="US-NY", name="New York", dry_status="WET", utc_offset_minutes=-240
    )
    customer = fx.create_customer(api, jurisdiction["id"], full_name="Decoy Buyer")
    partner = fx.create_partner(
        api, legal_name="Empire Last Mile", contract_tier="STANDARD",
        license_reference="NY-DEL-0001",
    )
    courier = fx.create_courier(api, partner["id"])

    probe_minor = _decoy_probe(
        api, partner, courier, customer, jurisdiction,
        "2026-08-22T16:00:00Z", "NO_ID_PRESENTED",
    )
    probe_major = _decoy_probe(
        api, partner, courier, customer, jurisdiction,
        "2026-08-22T17:00:00Z", "EXPIRED_DOCUMENT",
    )
    case_minor = fx.build_substantiated_case(
        api,
        partner["id"],
        secret_shopper_test_id=probe_minor["id"],
        severity="MINOR",
        assessed_severity="MINOR",
    )
    case_major = fx.open_manual_case(
        api,
        partner["id"],
        secret_shopper_test_id=probe_major["id"],
        severity="MAJOR",
        summary="Courier accepted an expired document",
    )
    fx.investigate_case(api, case_major["id"])
    return {
        "partner": partner,
        "case_minor": case_minor,
        "case_major": case_major,
    }


def test_04_substantiating_a_major_case_lifts_the_score_and_writes_its_term(api):
    """PRD 3.9: "It then takes the severity points for the case's
    `assessed_severity` — 5 for `MINOR`, 15 for `MAJOR`, 40 for `CRITICAL` —
    multiplies them by the variant's age weight, halves the product when the case
    has reached `CLOSED_VERIFIED` (the verified-remediation credit factor of 0.50),
    rounds that per-case term half up to two decimal places, and accumulates it."

    Design: Difficulty/compensating_invariant/reopen_and_dismiss_restores_the_partner_license_risk_score_exactly
    """
    world = _one_minor_and_one_open_case(api)
    before = validate_success(
        api.get_risk_assessment(world["partner"]["id"], OFFICER_A_HEADERS)
    )
    assert_score_equal(before["rolling_90d_score"], 5.00, "rolling_90d_score before")

    fx.decide_case(api, world["case_major"]["id"], "SUBSTANTIATED", "MAJOR")

    partner = fx.read_partner(api, world["partner"]["id"])
    assert_score_equal(partner["license_risk_score"], 20.00, "license_risk_score")
    major = fx.read_case(api, world["case_major"]["id"])
    assert_score_equal(major["risk_contribution"], 15.00, "risk_contribution")


def test_05_reopening_withdraws_the_contribution_it_had_written(api):
    """PRD 3.9: "It clears `decided_at`, clears `assessed_severity`, clears
    `substantiated_by_user_id` and resets `risk_contribution` to 0.00; it
    increments `investigation_rounds` and advances the case's `version` by one; it
    recomputes both partner risk-score variants with this case removed from the
    substantiated set and re-derives the posture; and it marks every corrective action
    plan of this case whose `state` is `SUBMITTED`, `ACCEPTED`, `REVISION_REQUESTED` or
    `FAILED_VERIFICATION` as `SUPERSEDED` — `SUBMITTED → SUPERSEDED` and likewise from
    each of the other three non-terminal plan states."

    Design: Difficulty/compensating_invariant/reopen_and_dismiss_restores_the_partner_license_risk_score_exactly
    """
    world = _one_minor_and_one_open_case(api)
    case_id = world["case_major"]["id"]

    fx.decide_case(api, case_id, "SUBSTANTIATED", "MAJOR")
    validate_success(api.reopen_case(case_id, f.case_reopen_payload(), OFFICER_A_HEADERS))

    partner = fx.read_partner(api, world["partner"]["id"])
    assert_score_equal(partner["license_risk_score"], 5.00, "license_risk_score")
    major = fx.read_case(api, case_id)
    assert_score_equal(major["risk_contribution"], 0.00, "risk_contribution")
    assert major["state"] == "UNDER_INVESTIGATION"
    assert major["assessed_severity"] is None
    assert major["decided_at"] is None
    assert major["substantiated_by_user_id"] is None
    assert major["investigation_rounds"] == 2


def test_06_substantiate_reopen_dismiss_returns_the_score_to_its_prior_value(api):
    """PRD 3.9: "The invariant this preserves is exact and is worth stating as an
    acceptance criterion: substantiating a case, reopening it, and then dismissing
    it must return the partner's `license_risk_score` to precisely the value it
    held before the first decision."

    Design: Difficulty/compensating_invariant/reopen_and_dismiss_restores_the_partner_license_risk_score_exactly
    """
    world = _one_minor_and_one_open_case(api)
    case_id = world["case_major"]["id"]
    before = validate_success(
        api.get_risk_assessment(world["partner"]["id"], OFFICER_A_HEADERS)
    )
    rolling_before = float(before["rolling_90d_score"])

    fx.decide_case(api, case_id, "SUBSTANTIATED", "MAJOR")
    validate_success(api.reopen_case(case_id, f.case_reopen_payload(), OFFICER_A_HEADERS))
    fx.decide_case(api, case_id, "DISMISSED", None)

    partner = fx.read_partner(api, world["partner"]["id"])
    assert_score_equal(partner["license_risk_score"], rolling_before, "license_risk_score")
    assert_score_equal(partner["license_risk_score"], 5.00, "license_risk_score")
    assert_score_equal(partner["lifetime_risk_score"], 5.00, "lifetime_risk_score")
    assert partner["open_case_count"] == 0
    assert partner["posture"] == "OPEN"

    major = fx.read_case(api, case_id)
    assert major["state"] == "DISMISSED"
    assert major["assessed_severity"] is None
    assert_score_equal(major["risk_contribution"], 0.00, "risk_contribution")

    minor = fx.read_case(api, world["case_minor"]["id"])
    assert minor["state"] == "SUBSTANTIATED"
    assert_score_equal(minor["risk_contribution"], 5.00, "untouched risk_contribution")
