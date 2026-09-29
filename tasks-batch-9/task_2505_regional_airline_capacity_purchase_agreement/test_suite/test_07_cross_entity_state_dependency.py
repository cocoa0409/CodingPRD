"""Operations admissible or not according to a wholly different entity's state.

A tail's induction turns on its base's qualified headcount, and an invoice's
issuance turns on a pass-through claim that was opened after the bill was drawn.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.api_errors import ERR_BASE_UNDERSTAFFED, ERR_PASSTHROUGH_UNRECONCILED
from test_helpers.assertions import (
    assert_is_null,
    assert_money,
    assert_staffing_picture,
    assert_status,
)
from test_helpers.factories import make_agreement_payload, make_completion_payload
from test_helpers.fixtures import (
    add_leg,
    advance_pilot_to,
    build_active_agreement,
    build_open_cycle,
    cancel_leg,
    claim_for_leg,
    classify_claim,
    close_cycle,
    complete_leg,
    file_pass_through_actual,
    hire_pilot,
    open_pass_through,
    raise_invoice,
    read_agreement,
    read_aircraft,
    read_crew_base,
    read_cycle,
    read_invoice,
    reconcile_pass_through,
    register_aircraft,
)
from test_helpers.test_users import ADMIN_HEADERS, OPS_HEADERS

FINAL_INVOICE_TOTAL_USD = 334362.99


def _build_half_crewed_base_with_pending_tail(api):
    """A two-for-one base holding one qualified captain, one trainee and one pending tail."""
    scenario = build_active_agreement(
        api,
        agreement_payload=make_agreement_payload(),
        station_code="CVG",
        pilots_required_per_aircraft=2,
        aircraft_allocation_cap=2,
    )
    qualified = hire_pilot(
        api, scenario.crew_base_id, "EMP-1301", seat="CAPTAIN", hire_class_date="2026-05-01"
    )
    advance_pilot_to(api, qualified["id"], scenario.crew_base_id, "IN_TRAINING")
    advance_pilot_to(api, qualified["id"], scenario.crew_base_id, "LINE_QUALIFIED")

    trainee = hire_pilot(
        api,
        scenario.crew_base_id,
        "EMP-1302",
        seat="FIRST_OFFICER",
        hire_class_date="2026-05-01",
    )
    advance_pilot_to(api, trainee["id"], scenario.crew_base_id, "IN_TRAINING")

    tail = register_aircraft(
        api, scenario.agreement_id, scenario.crew_base_id, tail_number="N1101RG"
    )
    return scenario, trainee, tail


class TestInductionGatedOnBaseHeadcount:
    """The identical induct request is refused and then accepted, the tail unchanged."""

    def test_the_induct_is_refused_while_the_base_holds_one_qualified_captain(self, api):
        """Two pilots per tail against one qualified captain fails the staffing test.

        PRD 3.3: "The staffing test asks whether the base would still be crewed after the
        induction: the number of tails it would then hold, one more than the current
        `assigned_aircraft_count`, multiplied by `pilots_required_per_aircraft`, must be
        no greater than `line_qualified_pilot_count`."

        Design: Difficulty/cross_entity_state_dependency/aircraft_induction_gated_on_crewbase_staffing_state
        """
        scenario, _trainee, tail = _build_half_crewed_base_with_pending_tail(api)

        response = api.induct_aircraft(tail["id"], headers=OPS_HEADERS)
        validate_error(response, ERR_BASE_UNDERSTAFFED, 409)

        standing_tail = read_aircraft(api, tail["id"])
        assert_status(standing_tail, "PENDING_INDUCTION")
        assert_is_null(standing_tail, "inducted_at")

        base = read_crew_base(api, scenario.crew_base_id)
        assert_staffing_picture(
            base,
            line_qualified=1,
            in_training=1,
            assigned_aircraft=0,
            allocatable_aircraft=0,
        )

    def test_qualifying_the_second_pilot_admits_the_same_tail(self, api):
        """Nothing about the tail changes; only the base's qualified population moves.

        PRD 3.3: "On success `inducted_at` is stamped from the logical clock, the base's
        `assigned_aircraft_count` rises by 1, all of the base's derived staffing figures
        are recomputed, and both the tail's `version` and the base's `version`
        increment."

        Design: Difficulty/cross_entity_state_dependency/aircraft_induction_gated_on_crewbase_staffing_state
        """
        scenario, trainee, tail = _build_half_crewed_base_with_pending_tail(api)

        validate_error(
            api.induct_aircraft(tail["id"], headers=OPS_HEADERS), ERR_BASE_UNDERSTAFFED, 409
        )

        advance_pilot_to(api, trainee["id"], scenario.crew_base_id, "LINE_QUALIFIED")
        assert_staffing_picture(
            read_crew_base(api, scenario.crew_base_id), line_qualified=2, in_training=0
        )

        inducted = validate_success(api.induct_aircraft(tail["id"], headers=OPS_HEADERS))
        assert_status(inducted, "IN_SERVICE")

        assert_staffing_picture(
            read_crew_base(api, scenario.crew_base_id),
            assigned_aircraft=1,
            required_pilots=2,
            headcount_shortfall=0,
            posture="STAFFED",
        )


def _build_draft_invoice_then_open_a_new_claim(api):
    """A DRAFT final bill drawn on a claim-free month, then a fuel claim filed behind it."""
    scenario = build_open_cycle(
        api,
        agreement_payload=make_agreement_payload(),
        station_code="ORD",
        pilots_required_per_aircraft=1,
        aircraft_allocation_cap=4,
        line_qualified_pilots=1,
        tail_numbers=["N1201RG"],
        cycle_month="2026-09",
        published_departures=100,
    )
    plan = (
        ("SM4901", "DSM", "2026-09-02T08:00:00Z", "2026-09-02T09:12:00Z", 1.200, 1.155, "2026-09-02T09:26:00Z", 120),
        ("SM4902", "MSP", "2026-09-04T08:00:00Z", "2026-09-04T10:00:00Z", 2.000, 2.007, "2026-09-04T10:14:00Z", 100),
        ("SM4903", "SBN", "2026-09-06T08:00:00Z", "2026-09-06T08:42:00Z", 0.700, 0.616, "2026-09-06T08:40:00Z", 80),
    )
    for number, destination, departure, arrival, planned, actual, actual_arrival, bags in plan:
        leg = add_leg(
            api,
            scenario,
            flight_number=number,
            origin="ORD",
            destination=destination,
            scheduled_departure_utc=departure,
            scheduled_arrival_utc=arrival,
            planned_block_hours=planned,
        )
        complete_leg(
            api,
            leg["id"],
            make_completion_payload(
                actual_block_hours=actual,
                actual_arrival_utc=actual_arrival,
                enplaned_bags=bags,
                mishandled_bags=0,
            ),
        )

    dropped = add_leg(
        api,
        scenario,
        flight_number="SM4904",
        origin="ORD",
        destination="GRR",
        scheduled_departure_utc="2026-09-08T08:00:00Z",
        scheduled_arrival_utc="2026-09-08T09:30:00Z",
        planned_block_hours=1.500,
    )
    cancel_leg(api, dropped["id"], cause_code="WEATHER")
    classify_claim(api, claim_for_leg(api, dropped["id"])["id"], "UNCONTROLLABLE")

    close_cycle(api, scenario.cycle_id)
    invoice = raise_invoice(api, scenario.cycle_id, "FINAL")
    claim = open_pass_through(
        api, scenario.cycle_id, category="FUEL", estimated_amount_usd=5000.00
    )
    return scenario, invoice, claim


class TestIssuanceGatedOnPassThroughTerminality:
    """A legally drawn draft becomes un-issuable until a foreign claim goes terminal."""

    def test_a_claim_opened_after_the_draft_was_drawn_blocks_the_issue(self, api):
        """The bill is sound and still refused, because another entity is mid-flight.

        PRD 3.8: "Four further conditions apply, and each has its own rejection: the
        `variant` must be `FINAL`, and issuing a provisional bill is refused with
        `ERR_INVOICE_VARIANT_NOT_FINAL` (HTTP 422); the month must be `CLOSED`; every
        pass-through claim of the month must be terminal, failing which
        `ERR_PASSTHROUGH_UNRECONCILED`; and the month's scorecard must be `PUBLISHED`, a
        scorecard sitting in `STALE` blocking settlement with `ERR_SCORECARD_STALE` (HTTP
        409) until it has been recomputed."

        Design: Difficulty/cross_entity_state_dependency/invoice_issue_gated_on_passthrough_claim_terminality
        """
        scenario, invoice, _claim = _build_draft_invoice_then_open_a_new_claim(api)

        response = api.issue_final_invoice(invoice["id"], headers=ADMIN_HEADERS)
        validate_error(response, ERR_PASSTHROUGH_UNRECONCILED, 409)

        standing = read_invoice(api, invoice["id"])
        assert_status(standing, "DRAFT")
        assert_is_null(standing, "issued_final_at")
        assert_money(
            read_agreement(api, scenario.agreement_id)["settled_to_date_usd"],
            0.00,
            "settled to date while the issue is blocked",
        )

    def test_reconciling_that_claim_releases_the_bill_with_its_components_frozen(self, api):
        """The claim goes terminal, the same bill issues, and its components never moved.

        PRD 3.8: "On success the invoice moves to `ISSUED`, `issued_final_at` is stamped
        from the logical clock, the month moves `CLOSED → SETTLED`, the agreement's
        `settled_to_date_usd` takes on this invoice's `total_usd` in addition to what it
        held, and `open_invoice_count` falls by 1."

        Design: Difficulty/cross_entity_state_dependency/invoice_issue_gated_on_passthrough_claim_terminality
        """
        scenario, invoice, claim = _build_draft_invoice_then_open_a_new_claim(api)

        validate_error(
            api.issue_final_invoice(invoice["id"], headers=ADMIN_HEADERS),
            ERR_PASSTHROUGH_UNRECONCILED,
            409,
        )

        file_pass_through_actual(api, claim["id"], 5000.00, supporting_doc_ref="FUEL-ORD-2609")
        reconciled = reconcile_pass_through(api, claim["id"])
        assert_status(reconciled, "RECONCILED")
        assert_money(reconciled["allowed_amount_usd"], 5000.00, "fuel allowed amount")

        issued = validate_success(api.issue_final_invoice(invoice["id"], headers=ADMIN_HEADERS))
        assert_status(issued, "ISSUED")
        assert_money(issued["total_usd"], FINAL_INVOICE_TOTAL_USD, "issued invoice total")
        assert_money(
            issued["passthrough_component_usd"],
            0.00,
            "the pass-through component frozen at creation",
        )

        settled_month = read_cycle(api, scenario.cycle_id)
        assert_status(settled_month, "SETTLED")
        assert_money(
            settled_month["passthrough_settlement_usd"],
            5150.00,
            "the month's pass-through settlement",
        )
        assert_money(
            read_agreement(api, scenario.agreement_id)["settled_to_date_usd"],
            FINAL_INVOICE_TOTAL_USD,
            "settled to date after the issue",
        )
