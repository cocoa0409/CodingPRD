"""Commissioning reports the state failure, not the interoperability shortfall."""
from test_helpers import (
    OPERATOR_HEADERS,
    ApiErrorId,
    api_client,
    read_station,
    setup_station,
    validate_error,
)


def _draft_station_scoring_sixty():
    """A DRAFT station whose only dispenser lacks Plug and Charge, roaming and
    certification, so its interoperability score is 60.00."""
    return setup_station(
        clock="2026-06-02T09:00:00Z",
        site_code="HS-PC-1",
        station_code="ST-PC-1",
        committed_service_capacity_kw=400.00,
        power_class="DCFC_150",
        declared_port_count=1,
        stop_at="DRAFT",
        ports=[
            {
                "dispenser_serial": "DS-PC-1",
                "connector_type": "CCS1",
                "terminal_model": "PT-4",
                "contactless_enabled": True,
                "plug_and_charge_enabled": False,
                "price_display_verified": True,
            }
        ],
    )


def test_the_transition_legality_check_precedes_the_interoperability_threshold():
    """Two rules are violated at once, and the more fundamental one is reported.

    PRD §2.11 evaluates "8. Transition legality ... — `ERR_INVALID_STATE`" before
    "19. The interoperability score threshold, evaluated after the whole ladder
    above — `ERR_INTEROP_SCORE_BELOW_THRESHOLD`."

    Design: Difficulty/priority_pair_validation_conflict/commission_state_check_wins_over_interop_constraint
    """
    scenario = _draft_station_scoring_sixty()

    response = api_client.commission_station(scenario["station"]["id"], OPERATOR_HEADERS)

    body = validate_error(response, ApiErrorId.ERR_INVALID_STATE, 409)
    assert body["error_id"] != "ERR_INTEROP_SCORE_BELOW_THRESHOLD", (
        "the interoperability rule is violated too, but it must not be the one "
        "reported"
    )


def test_the_rejected_commission_leaves_the_station_in_draft_with_the_failing_score():
    """The lower-priority condition really was violated, and nothing moved.

    PRD §3.3: "Commissioning proper is a separate operator action that advances
    `COMMISSIONING → OPERATIONAL`" and, only when all six gates clear, "the
    station stamps `commissioned_at` from the logical clock (this happens the
    first time it reaches `OPERATIONAL`; before that the field is null)."

    Design: Difficulty/priority_pair_validation_conflict/commission_state_check_wins_over_interop_constraint
    """
    scenario = _draft_station_scoring_sixty()
    station_id = scenario["station"]["id"]

    api_client.commission_station(station_id, OPERATOR_HEADERS)

    station = read_station(station_id)
    assert station["status"] == "DRAFT", "the rejected request must not move the station"
    assert station["commissioned_at"] is None
    assert float(station["payment_interop_score"]) == 60.00, (
        "100 * (0.40 * 1 + 0.20 * 0 + 0.20 * 1 + 0.20 * 0) is 60.00, far below the "
        f"90.00 gate; got {station['payment_interop_score']}"
    )
