"""Version guards, a two-sided threshold, and state that is visible immediately.

Each guarded write consumes exactly one version, so replaying the version a
successful write already consumed is refused and only a refetch lets the retry
through. The reweigh threshold is a conjunction, probed from both sides. And
nothing here needs a second call or a sweep to become visible.
"""

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_capture_event,
    assert_customer,
    factories,
    make_classification_auditor_headers,
    make_pricing_analyst_headers,
    make_shipper_headers,
    validate_error,
    validate_success,
)
from test_helpers import fixtures as fx

ANALYST = make_pricing_analyst_headers()
AUDITOR = make_classification_auditor_headers("aud-1")

CLOCK = "2026-01-10T08:00:00Z"

FIVE_HUNDRED_POUND_LINE = {
    "line_no": 1,
    "declared_class_code": 100,
    "declared_weight_lb": 500,
    "pieces": 1,
    "declared_length_in": 48.0,
    "declared_width_in": 40.0,
    "declared_height_in": 40.0,
}

TWO_HUNDRED_POUND_LINE = {
    "line_no": 1,
    "declared_class_code": 70,
    "declared_weight_lb": 200,
    "pieces": 2,
    "declared_length_in": 20.0,
    "declared_width_in": 20.0,
    "declared_height_in": 20.0,
}


# ==========================================================================
# The three version-guarded writes
# ==========================================================================


def test_a_second_activation_replaying_the_consumed_version_is_refused():
    """The first activation bumps the shipper's version, so the replay loses.

    PRD: "If the customer's `version` has advanced since the client read it,
    activation is rejected with `ERR_STALE_CUSTOMER_VERSION` at HTTP 412."

    Design: Corner/complexity_layers/activation_with_a_stale_customer_version_is_rejected_then_retried
    """
    fx.set_clock(CLOCK)
    standard = fx.create_published_standard()
    customer = fx.create_customer()
    observed_version = customer["version"]
    incumbent = fx.create_approved_rate_program(
        customer["id"], program_type="CLASS_BASED"
    )
    challenger = fx.create_approved_rate_program(
        customer["id"], program_type="DENSITY_BASED"
    )

    first = validate_success(
        api_client.activate_rate_program(
            incumbent["id"],
            factories.activate_rate_program_payload(observed_version),
            ANALYST,
        )
    )
    assert first["status"] == "ACTIVE"
    assert fx.get_customer(customer["id"])["active_program_type"] == "CLASS_BASED"

    replayed = api_client.activate_rate_program(
        challenger["id"],
        factories.activate_rate_program_payload(observed_version),
        ANALYST,
    )

    validate_error(
        replayed, ApiErrorId.ERR_STALE_CUSTOMER_VERSION.value, expected_status=412
    )
    assert fx.get_rate_program(challenger["id"])["status"] == "APPROVED"
    assert fx.get_rate_program(incumbent["id"])["status"] == "ACTIVE"
    refreshed = fx.get_customer(customer["id"])
    assert refreshed["active_program_type"] == "CLASS_BASED"
    assert refreshed["version"] > observed_version, (
        f"the successful activation consumed the version the replay reused, "
        f"got {refreshed['version']} against {observed_version}"
    )

    retried = validate_success(
        api_client.activate_rate_program(
            challenger["id"],
            factories.activate_rate_program_payload(refreshed["version"]),
            ANALYST,
        )
    )
    assert retried["status"] == "ACTIVE"
    assert retried["pinned_tariff_version_id"] == standard["tariff_version_id"]
    retired = fx.get_rate_program(incumbent["id"])
    assert retired["status"] == "RETIRED"
    assert retired["effective_to"].startswith("2026-01-10T08:00:00")
    assert fx.get_customer(customer["id"])["active_program_type"] == "DENSITY_BASED"


def test_a_manual_draft_held_from_before_the_dock_capture_is_refused():
    """The version check answers before the open-notice ceiling gets its turn.

    PRD: "Drafting a correction notice manually requires `expected_shipment_version`
    matching the target `Shipment`'s current `version`."

    Design: Corner/complexity_layers/notice_creation_with_a_stale_shipment_version_is_rejected
    """
    env = fx.setup_pricing_environment(clock=CLOCK)
    scenario = fx.setup_single_line_billed_shipment(env=env, pro_number="PROL010")
    stale_version = fx.get_shipment(scenario["shipment_id"])["version"]
    capture = fx.record_capture(
        scenario["shipment_id"],
        env["terminal_id"],
        520,
        fx.single_line_measurement(520),
    )
    automated = fx.find_draft_notice(scenario["shipment_id"])

    from_a_stale_read = api_client.create_correction_notice(
        factories.create_correction_notice_payload(
            scenario["shipment_id"],
            stale_version,
            notice_type="BOTH",
            basis_capture_event_id=capture["id"],
        ),
        AUDITOR,
    )
    validate_error(
        from_a_stale_read,
        ApiErrorId.ERR_STALE_SHIPMENT_VERSION.value,
        expected_status=412,
    )

    fresh_version = fx.get_shipment(scenario["shipment_id"])["version"]
    assert fresh_version > stale_version, (
        f"the dock capture moved the shipment on, got {fresh_version}"
    )

    without_superseding = api_client.create_correction_notice(
        factories.create_correction_notice_payload(
            scenario["shipment_id"],
            fresh_version,
            notice_type="BOTH",
            basis_capture_event_id=capture["id"],
        ),
        AUDITOR,
    )
    validate_error(
        without_superseding,
        ApiErrorId.ERR_OPEN_NOTICE_EXISTS.value,
        expected_status=409,
    )

    replacement = fx.draft_manual_notice(
        scenario["shipment_id"],
        notice_type="BOTH",
        basis_capture_event_id=capture["id"],
        supersedes_notice_id=automated["id"],
    )

    assert replacement["origin"] == "AUDITOR_MANUAL"
    assert replacement["final_delta_cents"] == 28314
    assert fx.get_notice(automated["id"])["status"] == "VOID"
    shipment = fx.get_shipment(scenario["shipment_id"])
    assert shipment["open_notice_count"] == 1
    assert shipment["assessed_total_cents"] == 12500, (
        "no notice has been issued yet, so no money has moved"
    )
    assert len(fx.list_notices_for(scenario["shipment_id"])) == 2


def test_replaying_the_version_a_posture_write_consumed_is_refused():
    """A posture write consumes exactly one version, and the account stays put.

    PRD: "Changing a shipper's credit posture likewise requires
    `expected_customer_version` matching the customer's current `version`."

    Design: Corner/complexity_layers/posture_change_replaying_a_used_customer_version_is_rejected
    """
    fx.set_clock(CLOCK)
    customer = fx.create_customer()
    observed_version = customer["version"]

    held = fx.change_posture(
        customer["id"], "CREDIT_HOLD", expected_customer_version=observed_version
    )
    assert held["billing_posture"] == "CREDIT_HOLD"

    replayed = api_client.change_customer_posture(
        customer["id"],
        factories.posture_payload("OPEN", observed_version),
        ANALYST,
    )

    validate_error(
        replayed, ApiErrorId.ERR_STALE_CUSTOMER_VERSION.value, expected_status=412
    )
    refreshed = fx.get_customer(customer["id"])
    assert refreshed["billing_posture"] == "CREDIT_HOLD", (
        "the refused release left the account on hold"
    )
    assert refreshed["version"] > observed_version

    released = fx.change_posture(
        customer["id"], "OPEN", expected_customer_version=refreshed["version"]
    )

    assert_customer(released)
    assert released["billing_posture"] == "OPEN"
    assert released["offender_strike_count"] == 0
    assert released["education_status"] == "NONE"


# ==========================================================================
# A threshold that is a conjunction
# ==========================================================================


def test_the_reweigh_gate_needs_the_percentage_and_the_pound_floor_together():
    """1.80 percent on 9 pounds is quiet, 2.00 on exactly 10 fires, 2.50 on 5 is quiet.

    PRD: "`reweigh_required` becomes true only when both conditions hold together:
    the variance is at least 2.00 percent and the absolute delta is at least 10
    pounds."

    Design: Corner/complexity_layers/reweigh_gate_needs_both_the_percentage_and_the_absolute_floor
    """
    env = fx.setup_pricing_environment(clock=CLOCK)
    heavy = fx.setup_billed_shipment(
        env=env,
        pro_number="PROT010",
        line_specs=[FIVE_HUNDRED_POUND_LINE],
        shipment_overrides={"bol_declared_total_weight_lb": 500},
    )
    light = fx.setup_billed_shipment(
        env=env,
        pro_number="PROT011",
        line_specs=[TWO_HUNDRED_POUND_LINE],
        shipment_overrides={"bol_declared_total_weight_lb": 200},
    )
    assert heavy["shipment"]["original_charge_cents"] == 15698
    assert light["shipment"]["original_charge_cents"] == 12500

    def _measure(weight, length_in, width_in, height_in):
        return fx.single_line_measurement(
            weight,
            measured_length_in=length_in,
            measured_width_in=width_in,
            measured_height_in=height_in,
        )

    under_the_pound_floor = fx.record_capture(
        heavy["shipment_id"], env["terminal_id"], 509, _measure(509, 48.0, 40.0, 40.0)
    )
    assert_capture_event(under_the_pound_floor)
    assert under_the_pound_floor["variance_pct"] == 1.80
    assert under_the_pound_floor["triggered_reweigh"] is False
    assert under_the_pound_floor["triggered_reclass"] is False
    assert fx.get_shipment_line(heavy["line_ids"][0])["measured_density_pcf"] == 11.45
    mid = fx.get_shipment(heavy["shipment_id"])
    assert mid["class_status"] == "CAPTURED"
    assert mid["open_notice_count"] == 0

    on_both_boundaries = fx.record_capture(
        heavy["shipment_id"], env["terminal_id"], 510, _measure(510, 48.0, 40.0, 40.0)
    )
    assert on_both_boundaries["variance_pct"] == 2.00
    assert on_both_boundaries["triggered_reweigh"] is True, (
        "exactly 2.00 percent on exactly 10 pounds satisfies both halves"
    )
    assert on_both_boundaries["triggered_reclass"] is False
    assert on_both_boundaries["capture_sequence"] == 2
    measured_line = fx.get_shipment_line(heavy["line_ids"][0])
    assert measured_line["measured_density_pcf"] == 11.48
    assert measured_line["effective_class_code"] == 100, (
        "11.48 pcf is still inside the 10.5 bracket, so nothing is reclassified"
    )
    notices = fx.list_notices_for(heavy["shipment_id"])
    assert len(notices) == 1
    assert notices[0]["notice_type"] == "REWEIGH"
    assert notices[0]["status"] == "DRAFT"
    assert notices[0]["provisional_delta_cents"] == 313
    assert notices[0]["final_delta_cents"] == 313

    under_the_percentage = fx.record_capture(
        light["shipment_id"], env["terminal_id"], 205, _measure(205, 20.0, 20.0, 20.0)
    )

    assert under_the_percentage["variance_pct"] == 2.50
    assert under_the_percentage["triggered_reweigh"] is False, (
        "a 5-pound gap misses the absolute floor however large the percentage"
    )
    assert under_the_percentage["triggered_reclass"] is False
    assert fx.list_notices_for(light["shipment_id"]) == []
    light_line = fx.get_shipment_line(light["line_ids"][0])
    assert light_line["measured_density_pcf"] == 22.14
    assert light_line["effective_class_code"] == 70
    assert fx.get_shipment(heavy["shipment_id"])["assessed_total_cents"] == 15698
    assert fx.get_shipment(light["shipment_id"])["assessed_total_cents"] == 12500
    assert fx.get_terminal(env["terminal_id"])["captures_since_calibration"] == 3


# ==========================================================================
# Derived state in the writing response
# ==========================================================================


def test_the_writing_response_already_carries_the_derived_geometry_and_money():
    """No follow-up read is needed to see cube, density or the floored charge.

    PRD: "Cube and density are computed on the line the moment it is created."

    Design: Corner/consistency_model/derived_line_and_charge_fields_are_present_in_the_writing_response
    """
    env = fx.setup_pricing_environment(clock=CLOCK)
    tendered = fx.tender_shipment(env["customer_id"], env["terminal_id"], "PROI001")

    created = validate_success(
        api_client.create_shipment_line(
            tendered["id"],
            factories.create_shipment_line_payload(env["commodity_profile_id"]),
            make_shipper_headers(env["customer_id"]),
        ),
        expected_status=201,
    )

    assert created["declared_cubic_ft"] == 213.33
    assert created["declared_density_pcf"] == 1.88
    assert created["effective_class_code"] == 70
    assert created["classification_source"] == "BOL_DECLARED"
    assert created["measured_cubic_ft"] is None
    assert created["measured_density_pcf"] is None
    assert created["measured_weight_lb"] is None

    billed = validate_success(api_client.bill_shipment(tendered["id"], {}, ANALYST))

    assert billed["original_charge_cents"] == 12500
    assert billed["assessed_total_cents"] == 12500
    assert billed["billing_status"] == "BILLED"

    read_back = fx.get_shipment_line(created["id"])
    assert read_back["line_charge_cents"] == 9937, (
        "the per-line amount is the one the shipment minimum never floors"
    )
    assert read_back["declared_cubic_ft"] == created["declared_cubic_ft"]
    assert read_back["declared_density_pcf"] == created["declared_density_pcf"]


def test_the_issuance_cascade_is_already_visible_to_the_very_next_read():
    """Three aggregates move inside the issuing call, with no reconciliation step.

    PRD: "On the shipment, `class_status` advances `RECLASS_PENDING → RECLASSED`,
    `billing_status` advances `BILLED → REBILLED`, and `assessed_total_cents` is
    recomputed from the ledger identity of §2.9."

    Design: Corner/consistency_model/issuance_cascade_is_visible_to_the_next_read_with_no_sweep
    """
    scenario = fx.setup_captured_shipment_with_draft_notice(pro_number="PROI010")

    issued = validate_success(
        api_client.issue_correction_notice(scenario["notice_id"], {}, AUDITOR)
    )

    assert issued["status"] == "ISSUED"
    assert issued["issued_at"].startswith("2026-01-10T08:00:00")
    assert issued["applied_delta_cents"] == 28314
    assert issued["inspection_fee_cents"] == 4500
    assert issued["dispute_deadline_at"].startswith("2026-02-09T08:00:00")

    shipment = fx.get_shipment(scenario["shipment_id"])
    customer = fx.get_customer(scenario["customer_id"])

    assert shipment["assessed_total_cents"] == 45314, (
        f"the first read after issuance already shows the rebilled total, "
        f"got {shipment['assessed_total_cents']}"
    )
    assert shipment["billing_status"] == "REBILLED"
    assert shipment["open_notice_count"] == 1
    assert shipment["class_status"] == "RECLASSED"
    assert shipment["original_charge_cents"] == 12500, (
        "the original bill is history and never moves"
    )
    assert customer["offender_strike_count"] == 1
    assert customer["liability_index_rolling"] == 0.00
    assert customer["dispute_window_days"] == 30
    assert fx.list_credit_memos_for(scenario["customer_id"]) == []
