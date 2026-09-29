"""Gates that refuse a request whose shape is otherwise perfectly well formed.

A zero-delta notice, a duplicate open notice, a publication that moves backwards
in effective time, and a commodity basis whose companion field is missing or
forbidden. One gate here is inclusive rather than exclusive: a dispute filed at
the deadline instant itself is inside the window.
"""

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_commodity_profile,
    assert_dispute,
    factories,
    make_pricing_analyst_headers,
    validate_error,
    validate_success,
)
from test_helpers import fixtures as fx

ANALYST = make_pricing_analyst_headers()
AUDITOR = fx.AUDITOR_HEADERS

CLOCK = "2026-01-10T08:00:00Z"

CONFIRMING_LINE = {
    "line_no": 1,
    "declared_class_code": 150,
    "declared_weight_lb": 1000,
    "pieces": 4,
    "declared_length_in": 40.0,
    "declared_width_in": 40.0,
    "declared_height_in": 40.0,
}

FIXED_CLASS_LINE = {
    "line_no": 1,
    "declared_class_code": 70,
    "declared_weight_lb": 600,
    "pieces": 1,
    "declared_length_in": 48.0,
    "declared_width_in": 40.0,
    "declared_height_in": 40.0,
}


# ==========================================================================
# Fiscal and cardinality gates on a correction notice
# ==========================================================================


def test_a_notice_whose_delta_is_exactly_zero_cannot_be_issued():
    """A capture that confirms the bill leaves nothing to correct.

    PRD: "A `ClassificationAuditor` issues a notice that is still `DRAFT`, whose
    `final_delta_cents` is not exactly 0 — a zero-delta notice is rejected with
    `ERR_ZERO_DELTA_NOTICE`"

    Design: Corner/validations/zero_delta_notice_cannot_be_issued
    """
    env = fx.setup_pricing_environment(clock=CLOCK)
    scenario = fx.setup_billed_shipment(
        env=env,
        pro_number="PROV001",
        line_specs=[CONFIRMING_LINE],
        shipment_overrides={"bol_declared_total_weight_lb": 1000},
    )
    assert scenario["shipment"]["original_charge_cents"] == 40950
    capture = fx.record_capture(
        scenario["shipment_id"],
        env["terminal_id"],
        1000,
        fx.single_line_measurement(
            1000, measured_length_in=40.0, measured_width_in=40.0, measured_height_in=40.0
        ),
    )
    assert capture["variance_pct"] == 0.00
    assert capture["triggered_reweigh"] is False
    assert capture["triggered_reclass"] is False
    assert fx.get_shipment(scenario["shipment_id"])["class_status"] == "CAPTURED"

    notice = fx.draft_manual_notice(
        scenario["shipment_id"],
        notice_type="RECLASS",
        basis_capture_event_id=capture["id"],
    )
    assert notice["final_delta_cents"] == 0
    assert notice["evidence_bundle_count"] == 2, (
        f"a COMBINED capture counts two, got {notice['evidence_bundle_count']}"
    )

    response = api_client.issue_correction_notice(notice["id"], {}, AUDITOR)

    validate_error(
        response, ApiErrorId.ERR_ZERO_DELTA_NOTICE.value, expected_status=422
    )
    stored = fx.get_notice(notice["id"])
    shipment = fx.get_shipment(scenario["shipment_id"])
    assert stored["status"] == "DRAFT"
    assert stored["applied_delta_cents"] == 0
    assert stored["inspection_fee_cents"] == 0, (
        "the fee is frozen only at issuance, and issuance was refused"
    )
    assert shipment["assessed_total_cents"] == 40950
    assert shipment["billing_status"] == "BILLED"
    assert shipment["open_notice_count"] == 1


def test_a_second_open_notice_is_refused_unless_it_supersedes_the_first():
    """The same body is refused without `supersedes_notice_id` and accepted with it.

    PRD: "A shipment may carry at most one notice in `DRAFT`, `ISSUED`, `DISPUTED`
    or `EVIDENCE_REQUESTED`; a manual draft that would be the second is rejected
    with `ERR_OPEN_NOTICE_EXISTS` unless it supersedes the open draft."

    Design: Corner/validations/second_notice_blocked_while_an_open_notice_exists_unless_it_supersedes
    """
    scenario = fx.setup_captured_shipment_with_draft_notice(pro_number="PROV004")
    shipment_version = fx.get_shipment(scenario["shipment_id"])["version"]

    refused = api_client.create_correction_notice(
        factories.create_correction_notice_payload(
            scenario["shipment_id"],
            shipment_version,
            notice_type="RECLASS",
            basis_capture_event_id=scenario["capture_event"]["id"],
        ),
        AUDITOR,
    )
    validate_error(
        refused, ApiErrorId.ERR_OPEN_NOTICE_EXISTS.value, expected_status=409
    )

    replacement = fx.draft_manual_notice(
        scenario["shipment_id"],
        notice_type="RECLASS",
        basis_capture_event_id=scenario["capture_event"]["id"],
        supersedes_notice_id=scenario["notice_id"],
    )

    voided = fx.get_notice(scenario["notice_id"])
    shipment = fx.get_shipment(scenario["shipment_id"])
    assert voided["status"] == "VOID"
    assert replacement["status"] == "DRAFT"
    assert replacement["supersedes_notice_id"] == scenario["notice_id"]
    assert replacement["notice_type"] == "RECLASS"
    assert replacement["final_delta_cents"] == 28314
    assert shipment["open_notice_count"] == 1, (
        f"the voided notice was decremented as the replacement was incremented, "
        f"got {shipment['open_notice_count']}"
    )
    assert shipment["assessed_total_cents"] == 12500, (
        "no notice has been issued, so no money has moved"
    )


# ==========================================================================
# The inclusive dispute window
# ==========================================================================


def test_a_dispute_filed_at_the_deadline_instant_itself_is_accepted():
    """The boundary instant counts as inside the window.

    PRD: "A filing is inside the window when the current logical instant is at or
    before `dispute_deadline_at`; the boundary instant itself counts as inside."

    Design: Corner/validations/dispute_filed_at_the_exact_deadline_instant_passes
    """
    scenario = fx.setup_issued_notice_scenario(pro_number="PROV002")
    notice = scenario["notice"]
    assert notice["notice_type"] == "BOTH"
    assert notice["origin"] == "AUTOMATED_CAPTURE"
    assert notice["applied_delta_cents"] == 28314
    assert notice["inspection_fee_cents"] == 4500
    assert notice["dispute_deadline_at"].startswith("2026-02-09T08:00:00"), (
        f"issued_at plus the TIER_0 window of 30 days is 2026-02-09T08:00:00Z, "
        f"got {notice['dispute_deadline_at']}"
    )

    fx.set_clock("2026-02-09T08:00:00Z")
    dispute = fx.file_dispute(scenario["notice_id"], scenario["customer_id"])

    assert_dispute(dispute)
    assert dispute["status"] == "OPEN"
    assert dispute["round_no"] == 1
    assert dispute["filed_at"].startswith("2026-02-09T08:00:00")
    assert dispute["filed_by_customer_id"] == scenario["customer_id"]
    after = fx.get_notice(scenario["notice_id"])
    assert after["status"] == "DISPUTED"
    assert after["dispute_round_count"] == 1
    assert fx.get_shipment(scenario["shipment_id"])["assessed_total_cents"] == 45314


# ==========================================================================
# Companion-field and monotonicity gates
# ==========================================================================


def test_the_fixed_class_code_is_required_for_one_basis_and_forbidden_for_the_other():
    """Once set it short-circuits the density bracket entirely.

    PRD: "A `DENSITY_BASED` profile derives its class from measured or declared
    density; a `FIXED_CLASS` profile always rates at its `fixed_class_code`, which
    must be supplied for that basis and must be null for a density-based profile."

    Design: Corner/validations/fixed_class_profile_requires_fixed_class_code_and_ignores_density
    """
    fx.set_clock(CLOCK)
    terminal = fx.create_terminal()
    customer = fx.create_customer()
    draft = fx.create_draft_tariff_version()
    fx.create_commodity_profile(draft["id"])

    missing = api_client.create_commodity_profile(
        factories.create_commodity_profile_payload(
            draft["id"],
            nmfc_item="049522",
            description="Chemicals, NOI",
            classification_basis="FIXED_CLASS",
        ),
        ANALYST,
    )
    validate_error(missing, ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=400)

    forbidden = api_client.create_commodity_profile(
        factories.create_commodity_profile_payload(
            draft["id"],
            nmfc_item="049523",
            description="Chemicals, NOI",
            classification_basis="DENSITY_BASED",
            fixed_class_code=92.5,
        ),
        ANALYST,
    )
    validate_error(forbidden, ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=400)

    accepted = validate_success(
        api_client.create_commodity_profile(
            factories.create_commodity_profile_payload(
                draft["id"],
                nmfc_item="049522",
                description="Chemicals, NOI",
                classification_basis="FIXED_CLASS",
                fixed_class_code=92.5,
            ),
            ANALYST,
        ),
        expected_status=201,
    )
    assert_commodity_profile(accepted)
    assert accepted["fixed_class_code"] == 92.5
    assert accepted["min_class_floor"] == 0

    fx.publish_tariff_version(draft["id"])
    fx.create_active_rate_program(customer["id"])
    env = {
        "customer_id": customer["id"],
        "terminal_id": terminal["id"],
        "commodity_profile_id": accepted["id"],
    }
    scenario = fx.setup_billed_shipment(
        env=env,
        pro_number="PROV003",
        line_specs=[FIXED_CLASS_LINE],
        shipment_overrides={"bol_declared_total_weight_lb": 600},
    )
    line = fx.get_shipment_line(scenario["line_ids"][0])
    shipment = fx.get_shipment(scenario["shipment_id"])

    assert line["declared_density_pcf"] == 13.50, (
        "the density is still recorded even though the bracket is never consulted"
    )
    assert line["effective_class_code"] == 92.5
    assert line["classification_source"] == "FIXED_CLASS"
    assert shipment["original_charge_cents"] == 17424


def test_publication_must_move_strictly_forward_in_effective_time():
    """An earlier release and one tying the incumbent are both refused.

    PRD: "Publication requires that at least one commodity profile already exists
    for the release and that its `effective_at` is strictly after the `effective_at`
    of the release that is currently the newest published one; a release whose
    effective instant does not clear that bar is rejected with
    `ERR_TARIFF_EFFECTIVE_CONFLICT`."

    Design: Corner/validations/publishing_a_standard_with_an_earlier_effective_date_conflicts
    """
    fx.set_clock(CLOCK)
    incumbent = fx.create_published_standard(
        code="NMFC-2026A", effective_at="2026-01-01T00:00:00Z"
    )
    earlier = fx.create_draft_tariff_version(
        code="NMFC-2025Z", effective_at="2025-12-01T00:00:00Z"
    )
    fx.create_commodity_profile(earlier["id"])
    tying = fx.create_draft_tariff_version(
        code="NMFC-2026A2", effective_at="2026-01-01T00:00:00Z"
    )
    fx.create_commodity_profile(tying["id"])

    earlier_response = api_client.publish_tariff_version(earlier["id"], {}, ANALYST)
    tying_response = api_client.publish_tariff_version(tying["id"], {}, ANALYST)

    validate_error(
        earlier_response,
        ApiErrorId.ERR_TARIFF_EFFECTIVE_CONFLICT.value,
        expected_status=409,
    )
    validate_error(
        tying_response,
        ApiErrorId.ERR_TARIFF_EFFECTIVE_CONFLICT.value,
        expected_status=409,
    )
    earlier_after = fx.get_tariff_version(earlier["id"])
    tying_after = fx.get_tariff_version(tying["id"])
    incumbent_after = fx.get_tariff_version(incumbent["tariff_version_id"])
    assert earlier_after["status"] == "DRAFT"
    assert earlier_after["published_at"] is None
    assert tying_after["status"] == "DRAFT", (
        "the comparison is strict, so an identical effective instant does not clear it"
    )
    assert tying_after["published_at"] is None
    assert incumbent_after["status"] == "PUBLISHED"
    assert incumbent_after["superseded_by_tariff_version_id"] is None
