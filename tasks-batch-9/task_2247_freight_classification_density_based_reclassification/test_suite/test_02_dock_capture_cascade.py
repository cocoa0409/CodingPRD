"""The dock capture cascade and the terminal calibration gate.

One capture call writes the capture event, every addressed line, the shipment
header, the terminal's calibration counters and — when the variance gate or a
class delta fires — a new correction notice.
"""

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_capture_event,
    assert_correction_notice,
    assert_shipment,
    assert_terminal,
    factories,
    make_terminal_operator_headers,
    validate_error,
)
from test_helpers import fixtures as fx

CLOCK = "2026-01-10T08:00:00Z"


def _cascade_scenario():
    env = fx.setup_pricing_environment(
        clock=CLOCK,
        terminal_overrides={
            "code": "TRM1",
            "name": "Chicago Dock",
            "calibration_interval_captures": 3,
        },
    )
    scenario = fx.setup_two_line_billed_shipment(
        env=env,
        pro_number="PRO8001",
        shipment_overrides={"bol_declared_total_weight_lb": 1100},
    )
    assert scenario["shipment"]["original_charge_cents"] == 26754
    return scenario


def _cascade_capture(scenario):
    return fx.record_capture(
        scenario["shipment_id"],
        scenario["terminal_id"],
        1300,
        [
            factories.line_measurement(1, 520, 48.0, 40.0, 48.0),
            factories.line_measurement(2, 780, 40.0, 40.0, 40.0),
        ],
    )


def _one_line_spec():
    return [
        {
            "line_no": 1,
            "declared_class_code": 70,
            "declared_weight_lb": 400,
            "pieces": 4,
            "declared_length_in": 48.0,
            "declared_width_in": 40.0,
            "declared_height_in": 48.0,
        }
    ]


def _calibration_env():
    """TRM1 locks out after one capture; TRM2 tolerates five."""
    env = fx.setup_pricing_environment(
        clock=CLOCK,
        terminal_overrides={
            "code": "TRM1",
            "name": "Chicago Dock",
            "calibration_interval_captures": 1,
        },
    )
    second_terminal = fx.create_terminal(
        code="TRM2", name="Memphis Dock", calibration_interval_captures=5
    )
    env["second_terminal"] = second_terminal
    return env


# ==========================================================================
# The four-level capture cascade
# ==========================================================================


def test_capture_writes_the_event_and_every_addressed_line():
    """The capture event and both lines are rewritten by the one call.

    PRD: "An accepted capture writes the measured dimensions and weights onto
    each addressed line and recomputes, for each of them, `measured_cubic_ft` and
    `measured_density_pcf` by the same two-step rounding used for the declared
    figures, then `found_class_code`, `effective_class_code`,
    `classification_source` and `line_charge_cents`."

    Design: Difficulty/transitive_cascade/capture_cascade_terminal_line_shipment_notice
    """
    scenario = _cascade_scenario()

    capture = _cascade_capture(scenario)
    line_one = fx.get_shipment_line(scenario["line_ids"][0])
    line_two = fx.get_shipment_line(scenario["line_ids"][1])

    assert_capture_event(capture)
    assert capture["capture_sequence"] == 1, (
        f"the first capture on a shipment starts at 1, got {capture['capture_sequence']}"
    )
    assert capture["terminal_id"] == scenario["terminal_id"], (
        "terminal_id is taken from the operator's X-User-ID"
    )
    assert capture["variance_pct"] == 18.18, (
        f"a 200-pound delta on 1100 declared pounds is 18.18 percent, "
        f"got {capture['variance_pct']}"
    )
    assert capture["triggered_reweigh"] is True
    assert capture["triggered_reclass"] is True
    assert capture["reclassed_line_count"] == 1

    assert line_one["measured_density_pcf"] == 2.44
    assert line_one["found_class_code"] == 250
    assert line_two["measured_density_pcf"] == 10.53
    assert line_two["found_class_code"] == 100


def test_capture_writes_the_shipment_header_without_touching_billing():
    """The shipment's measured fields, variance, reweigh flag, delta count and
    `class_status` all move, while `assessed_total_cents` stays at the billed figure.

    PRD: "`variance_pct` is that delta divided by `declared_total_weight_lb`,
    multiplied by 100, rounded to two decimal places, and it is recorded both on
    the capture and as the shipment's `weight_variance_pct`."

    Design: Difficulty/transitive_cascade/capture_cascade_terminal_line_shipment_notice
    """
    scenario = _cascade_scenario()

    _cascade_capture(scenario)
    shipment = fx.get_shipment(scenario["shipment_id"])

    assert_shipment(shipment)
    assert shipment["measured_total_weight_lb"] == 1300
    assert shipment["weight_variance_pct"] == 18.18
    assert shipment["reweigh_required"] is True
    assert shipment["declared_vs_found_class_delta_count"] == 1, (
        "only line 1 ends with a found class differing from its declared class"
    )
    assert shipment["class_status"] == "RECLASS_PENDING"
    assert shipment["open_notice_count"] == 1
    assert shipment["assessed_total_cents"] == 26754, (
        "a DRAFT notice contributes nothing to the ledger, so the assessed total holds"
    )


def test_capture_raises_an_automated_notice_and_bumps_the_terminal_counters():
    """The notice cites the capture that produced it and the terminal's calibration
    counters advance in the same call.

    PRD: "the system creates a **correction notice** in `status` `DRAFT` with
    `origin` `AUTOMATED_CAPTURE` and `basis_capture_event_id` pointing at the
    capture that produced it, increments the shipment's `open_notice_count` by
    one, and therefore increments the shipment's `version` by one."

    Design: Difficulty/transitive_cascade/capture_cascade_terminal_line_shipment_notice
    """
    scenario = _cascade_scenario()

    capture = _cascade_capture(scenario)
    notice = fx.find_draft_notice(scenario["shipment_id"])
    terminal = fx.get_terminal(scenario["terminal_id"])

    assert_correction_notice(notice)
    assert notice["origin"] == "AUTOMATED_CAPTURE"
    assert notice["notice_type"] == "BOTH", (
        f"a reweigh condition and a class delta both hold, got {notice['notice_type']}"
    )
    assert notice["basis_capture_event_id"] == capture["id"]
    assert notice["evidence_bundle_count"] == 2, (
        f"a COMBINED device counts as two evidence items, "
        f"got {notice['evidence_bundle_count']}"
    )
    assert notice["final_delta_cents"] == 30030

    assert_terminal(terminal)
    assert terminal["captures_since_calibration"] == 1
    assert terminal["dimensioner_status"] == "CALIBRATED", (
        "one capture is still strictly below the interval of three"
    )
    assert terminal["last_capture_at"] is not None, "last_capture_at is set by the capture"
    assert terminal["last_capture_at"].startswith("2026-01-10T08:00:00"), (
        f"last_capture_at is stamped from the logical clock, got {terminal['last_capture_at']}"
    )


# ==========================================================================
# The calibration gate is terminal state, not shipment state
# ==========================================================================


def test_first_capture_drives_a_one_capture_terminal_out_of_calibration():
    """A terminal whose interval is 1 flips to `OUT_OF_CALIBRATION` after one capture.

    PRD: "`dimensioner_status` is derived rather than set: it reads `CALIBRATED`
    while `captures_since_calibration` is strictly below
    `calibration_interval_captures` and flips to `OUT_OF_CALIBRATION` once the
    count reaches or exceeds the interval."

    Design: Difficulty/cross_entity_state_dependency/capture_blocked_by_out_of_calibration_terminal
    """
    env = _calibration_env()
    first = fx.setup_billed_shipment(
        env=env, pro_number="PROC001", line_specs=_one_line_spec()
    )

    fx.record_capture(
        first["shipment_id"], env["terminal_id"], 520, fx.single_line_measurement(520)
    )
    terminal = fx.get_terminal(env["terminal_id"])
    shipment = fx.get_shipment(first["shipment_id"])

    assert terminal["captures_since_calibration"] == 1
    assert terminal["dimensioner_status"] == "OUT_OF_CALIBRATION"
    assert shipment["class_status"] == "RECLASS_PENDING"


def test_capture_on_a_locked_out_terminal_is_refused_with_no_side_effect():
    """The second shipment is untouched because the refusal is about the terminal.

    PRD: "Capture requires that the shipment carries at least one line —
    otherwise `ERR_NO_SHIPMENT_LINES` — that the shipment's `billing_status` is
    not `CLOSED`, and that the capturing terminal's `dimensioner_status` is
    `CALIBRATED`; an out-of-calibration device is rejected with
    `ERR_DEVICE_OUT_OF_CALIBRATION`."

    Design: Difficulty/cross_entity_state_dependency/capture_blocked_by_out_of_calibration_terminal
    """
    env = _calibration_env()
    first = fx.setup_billed_shipment(
        env=env, pro_number="PROC001", line_specs=_one_line_spec()
    )
    second = fx.setup_billed_shipment(
        env=env, pro_number="PROC002", line_specs=_one_line_spec()
    )
    fx.record_capture(
        first["shipment_id"], env["terminal_id"], 520, fx.single_line_measurement(520)
    )

    response = api_client.create_capture_event(
        factories.create_capture_event_payload(
            second["shipment_id"], 520, fx.single_line_measurement(520)
        ),
        make_terminal_operator_headers(env["terminal_id"]),
    )

    validate_error(response, ApiErrorId.ERR_DEVICE_OUT_OF_CALIBRATION.value)
    blocked = fx.get_shipment(second["shipment_id"])
    assert blocked["class_status"] == "DECLARED"
    assert blocked["measured_total_weight_lb"] is None
    assert blocked["open_notice_count"] == 0
    terminal = fx.get_terminal(env["terminal_id"])
    assert terminal["captures_since_calibration"] == 1, (
        "a refused capture must not advance the calibration counter"
    )


def test_same_capture_succeeds_at_a_still_calibrated_terminal():
    """The identical payload against a shipment tendered at a calibrated terminal
    is accepted, so the block is terminal state alone.

    PRD: "It increments the terminal's `captures_since_calibration` by one and
    sets `last_capture_at`."

    Design: Difficulty/cross_entity_state_dependency/capture_blocked_by_out_of_calibration_terminal
    """
    env = _calibration_env()
    first = fx.setup_billed_shipment(
        env=env, pro_number="PROC001", line_specs=_one_line_spec()
    )
    fx.record_capture(
        first["shipment_id"], env["terminal_id"], 520, fx.single_line_measurement(520)
    )

    other_terminal_id = env["second_terminal"]["id"]
    env_at_second = dict(env)
    env_at_second["terminal_id"] = other_terminal_id
    third = fx.setup_billed_shipment(
        env=env_at_second, pro_number="PROC003", line_specs=_one_line_spec()
    )

    capture = fx.record_capture(
        third["shipment_id"], other_terminal_id, 520, fx.single_line_measurement(520)
    )

    assert capture["capture_sequence"] == 1
    assert capture["terminal_id"] == other_terminal_id
    second_terminal = fx.get_terminal(other_terminal_id)
    assert second_terminal["captures_since_calibration"] == 1
    assert second_terminal["dimensioner_status"] == "CALIBRATED"
    assert fx.get_shipment(third["shipment_id"])["class_status"] == "RECLASS_PENDING"
