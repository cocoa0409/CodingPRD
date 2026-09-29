"""Mandated windows and the status ladder they drive: calendar arithmetic, the
inclusive end-of-day deadlines, the ninety-day lead time and re-derivation.
"""
from test_helpers import (
    ADMIN,
    COMPLIANCE,
    api_client,
    fixtures,
    get_success_data,
)


def _read_obligation(obligation_id):
    return get_success_data(api_client.get_compliance_obligation(obligation_id, COMPLIANCE))


def test_documentation_deadline_floors_up_to_the_parts_deadline():
    """PRD §3.2: "Otherwise `deadline_basis` is `END_OF_PRODUCTION`;
    `parts_available_until` is the end of production advanced by the region's
    `min_parts_availability_years` whole calendar years, taken at the very end of that
    calendar day, namely 23:59:59.999Z; and `documentation_available_until` is the
    later of `parts_available_until` and the end of production advanced by the region's
    `min_documentation_years` whole calendar years, again at 23:59:59.999Z of that
    day."
    PRD §3.2: "Second: when no catalog part in `PUBLISHED` status holds a compatibility
    row for this model whose window contains the logical clock, the status is
    `BREACHED_PARTS`."

    Design: Corner/calculations/documentation_deadline_floors_at_the_parts_deadline_when_the_region_asks_for_less
    """
    fixtures.create_region(
        region_code="US-WA",
        min_parts_availability_years=7,
        min_documentation_years=5,
    )
    model = fixtures.create_model(
        model_code="CRX-C205",
        product_family="CRX",
        market_release_date="2020-01-01T00:00:00Z",
        repairability_tier="TIER_A_SELF_SERVICE",
    )
    obligation = fixtures.create_obligation(model["id"], "US-WA", COMPLIANCE)
    assert obligation["deadline_basis"] == "PRODUCTION_ACTIVE", (
        f"the clock has not started while the model is in production, got "
        f"{obligation['deadline_basis']}"
    )
    assert obligation["parts_available_until"] is None, (
        obligation["parts_available_until"]
    )

    fixtures.end_production(model["id"], "2024-03-15T00:00:00Z")

    settled = _read_obligation(obligation["id"])
    assert settled["deadline_basis"] == "END_OF_PRODUCTION", settled["deadline_basis"]
    assert settled["parts_available_until"].startswith("2031-03-15T23:59:59.999"), (
        f"Expected seven whole years at end of day, got "
        f"{settled['parts_available_until']}"
    )
    assert settled["documentation_available_until"].startswith("2031-03-15T23:59:59.999"), (
        "the documentation deadline is floored up to the parts deadline rather than "
        f"taking five years literally, got {settled['documentation_available_until']}"
    )
    assert settled["status"] == "BREACHED_PARTS", (
        f"the model holds no published part, got {settled['status']}"
    )
    assert settled["breach_count"] == 2, (
        f"Expected one breached evaluation at create and one on the re-run, got "
        f"{settled['breach_count']}"
    )

    parent = fixtures.read_model(model["id"])
    assert parent["support_state"] == "LEGACY_SUPPORT", parent["support_state"]
    assert parent["compliance_posture"] == "ORDER_RESTRICTED", (
        f"a breached obligation restricts ordering on the model, got "
        f"{parent['compliance_posture']}"
    )


def test_a_leap_day_end_of_production_clamps_to_the_twenty_eighth():
    """PRD §3.2: "Calendar arithmetic adds whole years, and 29 February advanced by a
    number of years clamps to 28 February when the target year is not a leap year."
    PRD §3.2: "On creation the obligation's mandated window is computed, its initial
    `status` is derived, the parent model's posture is rolled up, `breach_count` starts
    at zero, `documentation_verified` starts false, and `last_attested_at` and
    `last_attested_by_user_id` start null."

    Design: Corner/calculations/leap_day_end_of_production_clamps_to_february_28
    """
    fixtures.create_region(
        region_code="US-TX",
        min_parts_availability_years=7,
        min_documentation_years=7,
    )
    model = fixtures.create_model(
        model_code="CRX-C205L",
        product_family="CRX",
        market_release_date="2020-01-01T00:00:00Z",
        repairability_tier="TIER_A_SELF_SERVICE",
        end_of_production_date="2024-02-29T00:00:00Z",
    )
    assert model["support_state"] == "LEGACY_SUPPORT", (
        f"the date was supplied at registration, got {model['support_state']}"
    )

    obligation = fixtures.create_obligation(model["id"], "US-TX", COMPLIANCE)
    assert obligation["deadline_basis"] == "END_OF_PRODUCTION", (
        obligation["deadline_basis"]
    )
    assert obligation["parts_available_until"].startswith("2031-02-28T23:59:59.999"), (
        f"2031 is not a leap year, so the deadline clamps back a day, got "
        f"{obligation['parts_available_until']}"
    )
    assert obligation["documentation_available_until"].startswith(
        "2031-02-28T23:59:59.999"
    ), obligation["documentation_available_until"]
    assert obligation["last_attested_at"] is None, obligation["last_attested_at"]
    assert obligation["documentation_verified"] is False, (
        obligation["documentation_verified"]
    )


def _compliant_model_with_one_obligation(
    region_code, model_code, end_of_production_date, **region_overrides
):
    """A legacy model holding a published part and a current guide, plus one obligation."""
    fixtures.create_region(region_code=region_code, **region_overrides)
    model = fixtures.create_model(
        model_code=model_code,
        product_family="CRX",
        market_release_date="2015-01-01T00:00:00Z",
        repairability_tier="TIER_A_SELF_SERVICE",
        end_of_production_date=end_of_production_date,
    )
    part = fixtures.create_part(sku=f"SKU-{model_code}-FAN", list_price_cents=1200)
    fixtures.create_compatibility(
        part["id"], model["id"], effective_from="2015-02-01T00:00:00Z", install_minutes=20
    )
    fixtures.publish_part(part["id"])
    fixtures.publish_disassembly_guide(
        model["id"], [f"SKU-{model_code}-FAN"], safety_warning_count=2
    )
    obligation = fixtures.create_obligation(model["id"], region_code, COMPLIANCE)
    return {"model": model, "part": part, "obligation": obligation}


def test_the_obligation_turns_at_risk_only_once_the_ninety_day_lead_time_is_reached():
    """PRD §3.2: "Fourth: when `deadline_basis` is `END_OF_PRODUCTION` and the logical
    clock has reached or passed the point ninety days before `parts_available_until`,
    or when the model's `documentation_posture` is `STALE`, the status is `AT_RISK`."
    PRD §3.2: "Both deadlines are inclusive of that whole final day: a logical clock
    reading exactly `parts_available_until` still permits ordering, and the next
    millisecond does not."

    Design: Corner/calculations/obligation_turns_at_risk_exactly_ninety_days_before_the_parts_deadline
    """
    bundle = _compliant_model_with_one_obligation(
        "US-CA",
        "CRX-C210",
        "2019-11-01T00:00:00Z",
        min_parts_availability_years=7,
        min_documentation_years=7,
    )
    obligation = bundle["obligation"]
    assert obligation["parts_available_until"].startswith("2026-11-01T23:59:59.999"), (
        obligation["parts_available_until"]
    )
    assert obligation["status"] == "OPEN", (
        f"the lead time has not been reached at the 2026-08-01 clock, got "
        f"{obligation['status']}"
    )

    fixtures.move_clock("2026-08-03T00:00:00Z")
    fixtures.run_sweep(COMPLIANCE)
    day_before = _read_obligation(obligation["id"])
    assert day_before["status"] == "OPEN", (
        "the trigger instant is the end of 2026-08-03, which a midnight clock has not "
        f"reached, got {day_before['status']}"
    )

    fixtures.move_clock("2026-08-04T00:00:00Z")
    fixtures.run_sweep(COMPLIANCE)
    after = _read_obligation(obligation["id"])
    assert after["status"] == "AT_RISK", (
        f"Expected the lead time to bite the next day, got {after['status']}"
    )
    assert after["breach_count"] == 0, (
        f"an at-risk outcome is not a breach, got {after['breach_count']}"
    )

    model = fixtures.read_model(bundle["model"]["id"])
    assert model["compliance_posture"] == "WATCH", model["compliance_posture"]
    assert model["open_obligation_count"] == 1, model["open_obligation_count"]


def test_the_obligation_closes_only_after_both_mandated_windows_elapse():
    """PRD §3.2: "First: when `deadline_basis` is `END_OF_PRODUCTION` and the logical
    clock is strictly after both `parts_available_until` and
    `documentation_available_until`, the status is `CLOSED`."
    PRD §3.2: "Every obligation of the model participates regardless of region;
    `CLOSED` obligations contribute to neither branch, and a model with no obligations
    at all keeps its posture at `OPEN`."

    Design: Corner/calculations/obligation_closes_only_after_both_mandated_windows_elapse
    """
    bundle = _compliant_model_with_one_obligation(
        "US-OR",
        "CRX-C211",
        "2019-11-01T00:00:00Z",
        min_parts_availability_years=7,
        min_documentation_years=10,
    )
    obligation = bundle["obligation"]
    assert obligation["parts_available_until"].startswith("2026-11-01T23:59:59.999"), (
        obligation["parts_available_until"]
    )
    assert obligation["documentation_available_until"].startswith(
        "2029-11-01T23:59:59.999"
    ), obligation["documentation_available_until"]

    fixtures.move_clock("2026-12-01T00:00:00Z")
    fixtures.run_sweep(COMPLIANCE, model_id=bundle["model"]["id"])
    midway = _read_obligation(obligation["id"])
    assert midway["status"] == "AT_RISK", (
        "past the parts deadline but still inside the documentation window, so the "
        f"closing branch cannot fire; got {midway['status']}"
    )

    fixtures.move_clock("2029-12-01T00:00:00Z")
    fixtures.run_sweep(COMPLIANCE, model_id=bundle["model"]["id"])
    closed = _read_obligation(obligation["id"])
    assert closed["status"] == "CLOSED", (
        f"both deadlines are now behind the clock, got {closed['status']}"
    )

    model = fixtures.read_model(bundle["model"]["id"])
    assert model["compliance_posture"] == "OPEN", (
        f"a closed obligation feeds neither posture branch, got "
        f"{model['compliance_posture']}"
    )
    assert model["open_obligation_count"] == 0, (
        f"a closed obligation is not counted as open, got "
        f"{model['open_obligation_count']}"
    )


def test_an_attested_obligation_is_re_derived_by_the_next_sweep():
    """PRD §3.2: "A successful attestation stores `last_attested_at` from the logical
    clock, `last_attested_by_user_id` from the caller's `X-User-ID`, and the
    `documentation_verified` flag, then rolls the model's posture up again; an
    `ATTESTED` row counts as open, never as breached, so the posture drops back to
    `OPEN` or `WATCH` when no sibling obligation is breached."
    PRD §3.2: "An obligation's `status` is never set by a client. It is re-derived by
    evaluating the following branches in order and taking the first that matches."

    Design: Corner/calculations/attested_obligation_is_re_derived_by_the_next_sweep
    """
    bundle = _compliant_model_with_one_obligation(
        "US-CA",
        "CRX-C212",
        "2024-06-01T00:00:00Z",
        min_parts_availability_years=7,
        min_documentation_years=7,
    )
    obligation = bundle["obligation"]
    assert obligation["status"] == "OPEN", obligation["status"]

    attested = fixtures.attest_obligation(
        obligation["id"],
        COMPLIANCE,
        attestation_note="parts and manuals verified for the quarter",
        documentation_verified=True,
    )
    assert attested["status"] == "ATTESTED", attested["status"]
    assert attested["last_attested_at"].startswith("2026-08-01T00:00:00"), (
        f"the stamp comes from the logical clock, got {attested['last_attested_at']}"
    )
    assert fixtures.read_model(bundle["model"]["id"])["open_obligation_count"] == 1, (
        "an attested obligation still counts as open"
    )

    fixtures.move_clock("2026-08-15T00:00:00Z")
    fixtures.run_sweep(COMPLIANCE, model_id=bundle["model"]["id"])

    swept = _read_obligation(obligation["id"])
    assert swept["status"] == "OPEN", (
        f"the sweep re-derives the status instead of preserving the annotation, got "
        f"{swept['status']}"
    )
    assert swept["last_attested_at"] == attested["last_attested_at"], (
        f"the audit stamp survives the re-derivation, got {swept['last_attested_at']}"
    )
    assert swept["breach_count"] == 0, swept["breach_count"]

    model = fixtures.read_model(bundle["model"]["id"], ADMIN)
    assert model["open_obligation_count"] == 1, (
        f"Expected the single open obligation still counted, got "
        f"{model['open_obligation_count']}"
    )
