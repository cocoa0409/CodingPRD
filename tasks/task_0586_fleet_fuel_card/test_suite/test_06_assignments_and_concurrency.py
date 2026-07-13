"""Card assignments: half-open driver intervals, interval well-formedness, and the
optimistic-concurrency guard on the card's version."""
from test_helpers import (
    ApiErrorId,
    assert_card_assignment,
    create_card_assignment_payload,
    make_card_assignment,
    setup_multi_assignment_scenario,
    validate_error,
    validate_success,
)


# --------------------------------------------------------------------------- #
# Half-open [effective_from, effective_to) overlap on the same driver
# --------------------------------------------------------------------------- #

def _driver_booked_scenario(api):
    """Card 1 is bound to driver 1 over [2026-06-01, 2026-06-10)."""
    scenario = setup_multi_assignment_scenario(
        api, account_overrides={"company_name": "Overlap Fleet"}
    )
    make_card_assignment(
        api,
        scenario["account"]["id"],
        scenario["cards"][0]["id"],
        scenario["vehicles"][0]["id"],
        scenario["drivers"][0]["id"],
        scenario["cards"][0]["version"],
        effective_from="2026-06-01T00:00:00Z",
        effective_to="2026-06-10T00:00:00Z",
    )
    return scenario


def test_overlapping_interval_on_same_driver_rejected(api):
    """PRD §3.3: "The new interval must not overlap any other `ACTIVE` assignment
    of the same `driver_id`; two intervals that merely touch at an endpoint do not
    overlap (the half-open convention), but any genuine overlap is rejected with
    `ERR_DRIVER_DOUBLE_BOOKED`."

    [2026-06-05, 2026-06-15) genuinely overlaps the driver's existing
    [2026-06-01, 2026-06-10).

    Design: Difficulty/resource_temporal_overlap/driver_assignment_halfopen_overlap
    """
    scenario = _driver_booked_scenario(api)

    payload = create_card_assignment_payload(
        scenario["cards"][1]["id"],
        scenario["vehicles"][1]["id"],
        scenario["drivers"][0]["id"],
        scenario["cards"][1]["version"],
        effective_from="2026-06-05T00:00:00Z",
        effective_to="2026-06-15T00:00:00Z",
    )
    resp = api.create_card_assignment(payload, scenario["fm"])

    validate_error(resp, ApiErrorId.ERR_DRIVER_DOUBLE_BOOKED.value)


def test_adjacent_interval_on_same_driver_allowed(api):
    """PRD §3.3: "The new interval must not overlap any other `ACTIVE` assignment
    of the same `driver_id`; two intervals that merely touch at an endpoint do not
    overlap (the half-open convention), but any genuine overlap is rejected with
    `ERR_DRIVER_DOUBLE_BOOKED`."
    PRD §3.3: "The interval is half-open: `effective_from` inclusive to
    `effective_to` exclusive, and a null `effective_to` means open-ended."

    [2026-06-10, 2026-06-20) merely touches the existing interval's exclusive end.

    Design: Difficulty/resource_temporal_overlap/driver_assignment_halfopen_overlap
    """
    scenario = _driver_booked_scenario(api)

    payload = create_card_assignment_payload(
        scenario["cards"][1]["id"],
        scenario["vehicles"][1]["id"],
        scenario["drivers"][0]["id"],
        scenario["cards"][1]["version"],
        effective_from="2026-06-10T00:00:00Z",
        effective_to="2026-06-20T00:00:00Z",
    )
    assignment = validate_success(api.create_card_assignment(payload, scenario["fm"]), 201)

    assert_card_assignment(assignment)
    assert assignment["status"] == "ACTIVE", "touching endpoints do not overlap"


# --------------------------------------------------------------------------- #
# Interval well-formedness
# --------------------------------------------------------------------------- #

def test_assignment_with_end_before_start_rejected(api):
    """PRD §3.3: "The interval must be well-formed — either `effective_to` is null,
    or `effective_from` is strictly earlier than `effective_to` — else
    `ERR_INVALID_INTERVAL`."

    Design: Corner/validations/assignment_invalid_interval_rejected
    """
    scenario = setup_multi_assignment_scenario(
        api, account_overrides={"company_name": "Intv Co"}
    )

    payload = create_card_assignment_payload(
        scenario["cards"][0]["id"],
        scenario["vehicles"][0]["id"],
        scenario["drivers"][0]["id"],
        scenario["cards"][0]["version"],
        effective_from="2026-06-10T00:00:00Z",
        effective_to="2026-06-01T00:00:00Z",
    )
    resp = api.create_card_assignment(payload, scenario["fm"])

    validate_error(resp, ApiErrorId.ERR_INVALID_INTERVAL.value)


# --------------------------------------------------------------------------- #
# Optimistic concurrency on the card's version
# --------------------------------------------------------------------------- #

def test_second_assignment_with_stale_card_version_rejected(api):
    """PRD §2.5: "Therefore, if `expected_card_version` does not equal the card's
    current `version`, the create is rejected with `ERR_STALE_CARD_VERSION` (412)."
    PRD §3.3: "Because the create advances the card's `version`, a competing create
    that still carries the pre-supersession `expected_card_version` will be refused:
    the first writer already superseded the prior assignment and bumped the card, so
    the second client's observed card version is stale."

    The second create names a different driver and a different vehicle, so neither
    the driver double-booking guard nor the vehicle guard can fire — the stale
    card version is the only violated check.

    Design: Corner/cross_cutting_complexity_layers/occ_stale_card_version_conflict
    """
    scenario = setup_multi_assignment_scenario(
        api, account_overrides={"company_name": "Occ Co"}
    )
    card = scenario["cards"][0]
    observed_version = card["version"]

    make_card_assignment(
        api, scenario["account"]["id"], card["id"],
        scenario["vehicles"][0]["id"], scenario["drivers"][0]["id"], observed_version,
        effective_from="2026-06-01T00:00:00Z",
    )

    payload = create_card_assignment_payload(
        card["id"],
        scenario["vehicles"][1]["id"],
        scenario["drivers"][1]["id"],
        observed_version,
        effective_from="2026-06-02T00:00:00Z",
    )
    resp = api.create_card_assignment(payload, scenario["fm"])

    validate_error(resp, ApiErrorId.ERR_STALE_CARD_VERSION.value)
