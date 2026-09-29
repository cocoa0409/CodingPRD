"""Which rows feed a calculation, in which order, and where the declared constants bite."""
from test_helpers import fixtures
from test_helpers.assertions import (
    assert_cold_chain_excursion,
    assert_instant,
    assert_risk_index,
    assert_temperature,
)
from test_helpers.factories import gulf_grouper_payload
from test_helpers.test_users import OFFICER_SAMPLING_USER_ID


def _two_cased_candidates_and_one_uncased_lot(api) -> dict:
    """A cod lot and a high-risk grouper lot in the case, plus a second cod lot still in receipt."""
    env = fixtures.base_environment(api, "2026-08-01T08:00:00Z")
    counter_id = env["counter"]["id"]
    supplier_id = env["supplier"]["id"]
    grouper = fixtures.register_species(api, gulf_grouper_payload())
    cod_lot = fixtures.receive_lot(
        api, counter_id, supplier_id, env["cod"]["id"], received_weight_kg=10.000
    )
    fixtures.case_lot(api, counter_id, cod_lot["id"], 1)
    grouper_lot = fixtures.receive_lot(
        api,
        counter_id,
        supplier_id,
        grouper["id"],
        lot_code="GRP-0801-A",
        harvest_method="WILD_TRAP",
        origin_country_code="MX",
        fresh_claim=False,
        received_weight_kg=12.000,
        unit_cost_cents_per_kg=2400,
        retail_price_cents_per_kg=3200,
        cooked_retail_price_cents_per_kg=3500,
    )
    fixtures.case_lot(api, counter_id, grouper_lot["id"], 2)
    uncased_lot = fixtures.receive_lot(
        api,
        counter_id,
        supplier_id,
        env["cod"]["id"],
        lot_code="COD-0801-B",
        received_weight_kg=10.000,
    )
    env.update(
        {"grouper": grouper, "cod_lot": cod_lot, "grouper_lot": grouper_lot, "uncased": uncased_lot}
    )
    return env


def _cased_cod_lot_with_the_clock_at_four(api) -> dict:
    """A cod lot in slot 1 and a logical clock late enough to accept afternoon probe times."""
    env = fixtures.base_environment(api, "2026-08-01T08:00:00Z")
    counter_id = env["counter"]["id"]
    lot = fixtures.receive_lot(
        api, counter_id, env["supplier"]["id"], env["cod"]["id"], received_weight_kg=10.000
    )
    fixtures.case_lot(api, counter_id, lot["id"], 1)
    fixtures.set_clock(api, "2026-08-01T16:00:00Z")
    env["lot"] = lot
    return env


def test_01_the_sampling_plan_counts_only_the_two_cased_candidates(api):
    """PRD §3.8: "Otherwise the high-risk count is the number of candidate lots whose species
    has `high_risk_substitution` true, and `last_cycle_max_supplier_risk_index` is the greatest
    `substitution_risk_index_rolling` among the dealers behind those candidate lots, read before
    the index is advanced in step two and before the dealer indices are re-decayed in step
    three."

    Design: Corner/calculations/sampling_plan_counts_only_candidate_lots_and_high_risk_species
    """
    env = _two_cased_candidates_and_one_uncased_lot(api)
    counter_id = env["counter"]["id"]

    counter = fixtures.close_verification_cycle(
        api,
        counter_id,
        fixtures.read_counter(api, counter_id)["version"],
        officer_id=OFFICER_SAMPLING_USER_ID,
    )

    assert counter["last_cycle_required_samples"] == 2
    assert counter["last_cycle_required_samples"] != 3
    assert_risk_index(counter["last_cycle_max_supplier_risk_index"], 0.00)
    assert counter["verification_cycle_index"] == 1
    assert counter["posture"] == "OPEN"
    assert (
        fixtures.read_lot(api, counter_id, env["uncased"]["id"])["intake_status"] == "RECEIVED"
    )


def test_02_a_late_arriving_earlier_breach_still_anchors_the_excursion(api):
    """PRD §3.7: "Every submitted reading re-derives the slot's exposure picture by full
    chronological replay, so that a reading arriving out of order yields the same excursion as if
    it had arrived in time order."

    Design: Corner/calculations/cold_chain_replay_is_chronological_not_arrival_ordered
    """
    env = _cased_cod_lot_with_the_clock_at_four(api)
    counter_id = env["counter"]["id"]

    fixtures.submit_reading(api, counter_id, 1, "2026-08-01T15:30:00Z", 4.8)
    fixtures.submit_reading(api, counter_id, 1, "2026-08-01T13:00:00Z", 5.0)
    compliant = fixtures.submit_reading(api, counter_id, 1, "2026-08-01T15:45:00Z", 4.0)

    assert compliant["breach"] is False
    excursions = fixtures.list_excursions(api, counter_id, {"case_slot": 1})
    assert len(excursions) == 1, f"expected exactly one excursion, got {len(excursions)}"
    excursion = excursions[0]
    assert_cold_chain_excursion(excursion)
    assert_instant(excursion["started_at"], "2026-08-01T13:00:00Z")
    assert_instant(excursion["ended_at"], "2026-08-01T15:30:00Z")
    assert excursion["exposure_minutes"] == 150
    assert excursion["severity"] == "MAJOR"
    assert_temperature(excursion["peak_temperature_c"], 5.0)
    assert excursion["status"] == "OPEN"
    assert fixtures.read_lot(api, counter_id, env["lot"]["id"])["intake_status"] == "HELD"


def test_03_exactly_sixty_minutes_is_still_minor_and_sixty_one_is_major(api):
    """PRD §3.7: "Severity follows from exposure alone: an exposure of at most 60 minutes — one
    hour — is `MINOR`; an exposure above that but at most 180 minutes — three hours — is
    `MAJOR`; anything longer is `CRITICAL`."

    Design: Corner/calculations/severity_bands_apply_the_declared_minute_constants
    """
    fixtures.set_clock(api, "2026-08-01T16:00:00Z")
    counter = fixtures.register_counter(api)
    counter_id = counter["id"]

    fixtures.submit_reading(api, counter_id, 2, "2026-08-01T13:00:00Z", 4.5)
    fixtures.submit_reading(api, counter_id, 2, "2026-08-01T14:00:00Z", 4.6)
    at_boundary = fixtures.list_excursions(api, counter_id, {"case_slot": 2})[0]

    assert at_boundary["exposure_minutes"] == 60
    assert at_boundary["severity"] == "MINOR"
    assert at_boundary["severity"] != "MAJOR"

    fixtures.submit_reading(api, counter_id, 2, "2026-08-01T14:01:00Z", 4.7)
    excursions = fixtures.list_excursions(api, counter_id, {"case_slot": 2})
    assert len(excursions) == 1, f"expected exactly one excursion, got {len(excursions)}"
    past_boundary = excursions[0]

    assert past_boundary["id"] == at_boundary["id"]
    assert past_boundary["exposure_minutes"] == 61
    assert past_boundary["severity"] == "MAJOR"
    assert_temperature(past_boundary["peak_temperature_c"], 4.7)
    assert past_boundary["status"] == "OPEN"

    reread = fixtures.read_counter(api, counter_id)
    assert reread["open_excursion_count"] == 1
    assert reread["posture"] == "RESTRICTED"
