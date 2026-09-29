"""Catalogued refusals, each provoked in isolation from its neighbours in the order.

Authentication before anything else, the entity-specific 404 codes, the allocation cap
reached with staffing deliberately satisfied, the finalized claim that freezes a leg,
the stale scorecard that blocks settlement, and the term that fails to extend.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers.api_errors import (
    ERR_AGREEMENT_NOT_FOUND,
    ERR_BASE_UNDERSTAFFED,
    ERR_BRAND_AUDIT_NOT_FOUND,
    ERR_CANCELLATION_CLAIM_NOT_FOUND,
    ERR_CLAIM_ALREADY_FINALIZED,
    ERR_EXTENSION_TERM_NOT_LATER,
    ERR_FLEET_ALLOCATION_EXCEEDED,
    ERR_FLIGHT_LEG_NOT_FOUND,
    ERR_NEGOTIATION_NOT_FOUND,
    ERR_PASSTHROUGH_CLAIM_NOT_FOUND,
    ERR_PILOT_NOT_FOUND,
    ERR_REFERENCE_NOT_FOUND,
    ERR_SCHEDULE_CYCLE_NOT_FOUND,
    ERR_SCORECARD_NOT_FOUND,
    ERR_SCORECARD_STALE,
    ERR_UNAUTHENTICATED,
)
from test_helpers.assertions import (
    assert_is_null,
    assert_money,
    assert_staffing_picture,
    assert_status,
)
from test_helpers.factories import (
    make_agreement_payload,
    make_extension_offer_payload,
    make_invoice_payload,
)
from test_helpers.fixtures import (
    add_leg,
    agreement_version,
    build_active_agreement,
    build_open_cycle,
    cancel_leg,
    claim_for_leg,
    classify_claim,
    close_cycle,
    create_agreement,
    create_brand_audit,
    create_cycle,
    cycle_version,
    finalize_claim,
    hire_pilot,
    induct_aircraft,
    open_cycle,
    qualify_pilot,
    read_agreement,
    read_aircraft,
    read_crew_base,
    read_cycle,
    read_invoice,
    read_leg,
    register_aircraft,
    scorecard_for_cycle,
)
from test_helpers.test_users import ADMIN_HEADERS, OPS_HEADERS, SCHEDULER_HEADERS


class TestAuthenticationComesFirst:
    """A credential-less read of a populated collection never reaches the data."""

    def test_a_request_with_no_identity_headers_is_rejected_before_anything_else(self, api):
        """The same read with credentials returns the one agreement that exists.

        PRD 2.1: "If either header is absent, or if `X-User-Role` is not one of the five
        declared roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401) before
        anything else is examined."

        Design: Corner/errors/request_without_credentials_rejected_unauthenticated
        """
        create_agreement(api, make_agreement_payload())

        error = validate_error(api.list_agreements(headers={}), ERR_UNAUTHENTICATED, 401)
        assert error["error_id"] == ERR_UNAUTHENTICATED
        assert error["message"], "the error envelope carries a human-readable message"

        _agreements, meta = validate_paginated(api.list_agreements(headers=ADMIN_HEADERS))
        assert meta["total_count"] == 1


class TestEntitySpecificNotFoundCodes:
    """Each collection owns its own 404 code rather than sharing a generic one."""

    def test_the_same_unknown_identifier_yields_a_different_code_per_collection(self, api):
        """The body-reference code is reserved for foreign keys and appears nowhere here.

        PRD 2.10: "Path identifiers are resolved left to right, and the first identifier
        that does not resolve produces its own 404: `ERR_AGREEMENT_NOT_FOUND`,
        `ERR_CREW_BASE_NOT_FOUND`, `ERR_AIRCRAFT_NOT_FOUND`, `ERR_PILOT_NOT_FOUND`,
        `ERR_SCHEDULE_CYCLE_NOT_FOUND`, `ERR_FLIGHT_LEG_NOT_FOUND`,
        `ERR_CANCELLATION_CLAIM_NOT_FOUND`, `ERR_PASSTHROUGH_CLAIM_NOT_FOUND`,
        `ERR_SCORECARD_NOT_FOUND`, `ERR_INVOICE_NOT_FOUND`, `ERR_BRAND_AUDIT_NOT_FOUND`, or
        `ERR_NEGOTIATION_NOT_FOUND` respectively."

        Design: Corner/errors/unknown_path_ids_return_entity_specific_not_found
        """
        probes = (
            (api.get_agreement, "00000000-0000-4000-8000-000000000101", ERR_AGREEMENT_NOT_FOUND),
            (api.get_pilot, "00000000-0000-4000-8000-000000000102", ERR_PILOT_NOT_FOUND),
            (
                api.get_schedule_cycle,
                "00000000-0000-4000-8000-000000000103",
                ERR_SCHEDULE_CYCLE_NOT_FOUND,
            ),
            (api.get_flight_leg, "00000000-0000-4000-8000-000000000104", ERR_FLIGHT_LEG_NOT_FOUND),
            (
                api.get_cancellation_claim,
                "00000000-0000-4000-8000-000000000105",
                ERR_CANCELLATION_CLAIM_NOT_FOUND,
            ),
            (
                api.get_pass_through_claim,
                "00000000-0000-4000-8000-000000000106",
                ERR_PASSTHROUGH_CLAIM_NOT_FOUND,
            ),
            (api.get_scorecard, "00000000-0000-4000-8000-000000000107", ERR_SCORECARD_NOT_FOUND),
            (
                api.get_brand_audit,
                "00000000-0000-4000-8000-000000000108",
                ERR_BRAND_AUDIT_NOT_FOUND,
            ),
            (
                api.get_extension_negotiation,
                "00000000-0000-4000-8000-000000000109",
                ERR_NEGOTIATION_NOT_FOUND,
            ),
        )

        surfaced = []
        for read_one, unknown_id, expected_error_id in probes:
            error = validate_error(
                read_one(unknown_id, headers=ADMIN_HEADERS), expected_error_id, 404
            )
            surfaced.append(error["error_id"])

        assert surfaced == [expected for _reader, _id, expected in probes]
        assert len(set(surfaced)) == 9, "each collection surfaces its own code"
        assert ERR_REFERENCE_NOT_FOUND not in surfaced


class TestFleetAllocationCap:
    """With staffing deliberately satisfied, the contractual cap is the only rule left."""

    def test_a_second_induction_at_a_cap_of_one_is_refused_on_the_allocation_alone(self, api):
        """Two qualified captains for a ratio of one keep the staffing test passing.

        PRD 3.3: "The allocation test asks whether the mainline is entitled to put another
        tail there at all: one more than the current `assigned_aircraft_count` must be no
        greater than `aircraft_allocation_cap`, and failing it is
        `ERR_FLEET_ALLOCATION_EXCEEDED` (HTTP 409)."

        Design: Corner/errors/second_induction_exceeds_fleet_allocation_cap
        """
        scenario = build_active_agreement(
            api,
            agreement_payload=make_agreement_payload(),
            station_code="MKE",
            pilots_required_per_aircraft=1,
            aircraft_allocation_cap=1,
        )
        for employee_ref in ("EMP-5101", "EMP-5102"):
            pilot = hire_pilot(
                api, scenario.crew_base_id, employee_ref, hire_class_date="2026-05-01"
            )
            qualify_pilot(api, pilot["id"], scenario.crew_base_id)

        first = register_aircraft(
            api, scenario.agreement_id, scenario.crew_base_id, tail_number="N5101RG"
        )
        induct_aircraft(api, first["id"])
        second = register_aircraft(
            api, scenario.agreement_id, scenario.crew_base_id, tail_number="N5102RG"
        )

        error = validate_error(
            api.induct_aircraft(second["id"], headers=OPS_HEADERS),
            ERR_FLEET_ALLOCATION_EXCEEDED,
            409,
        )
        assert error["error_id"] != ERR_BASE_UNDERSTAFFED

        pending = read_aircraft(api, second["id"])
        assert_status(pending, "PENDING_INDUCTION")
        assert_is_null(pending, "inducted_at")

        assert_staffing_picture(
            read_crew_base(api, scenario.crew_base_id),
            line_qualified=2,
            assigned_aircraft=1,
            allocatable_aircraft=1,
            posture="STAFFED",
        )


class TestFinalizedClaimFreezesTheLeg:
    """Reinstatement is a compensating action only while attribution is still open."""

    def test_a_leg_whose_claim_has_been_finalized_can_no_longer_be_reinstated(self, api):
        """The refused reinstatement leaves the ledger where the cancellation put it.

        PRD 3.4: "A claim already in `FINALIZED` blocks the reinstatement with
        `ERR_CLAIM_ALREADY_FINALIZED` (HTTP 409), because the two carriers have by then
        agreed on the attribution and the month's penalty basis is settled."

        Design: Corner/errors/reinstate_after_claim_finalized_rejected
        """
        scenario = build_open_cycle(
            api,
            agreement_payload=make_agreement_payload(),
            station_code="MKE",
            pilots_required_per_aircraft=1,
            aircraft_allocation_cap=1,
            line_qualified_pilots=1,
            tail_numbers=["N5201RG"],
            cycle_month="2026-09",
            published_departures=3,
        )
        leg = add_leg(
            api,
            scenario,
            flight_number="SM7801",
            origin="MKE",
            destination="ORD",
            scheduled_departure_utc="2026-09-02T08:00:00Z",
            scheduled_arrival_utc="2026-09-02T09:00:00Z",
            planned_block_hours=1.000,
        )
        cancel_leg(api, leg["id"], cause_code="CREW_UNAVAILABLE")
        claim = claim_for_leg(api, leg["id"])
        classify_claim(api, claim["id"], classification="CONTROLLABLE")
        finalized = finalize_claim(api, claim["id"])
        assert_status(finalized, "FINALIZED")

        validate_error(
            api.reinstate_flight_leg(leg["id"], headers=OPS_HEADERS),
            ERR_CLAIM_ALREADY_FINALIZED,
            409,
        )

        frozen = read_leg(api, leg["id"])
        assert_status(frozen, "CANCELLED")
        assert frozen["cancel_cause_code"] == "CREW_UNAVAILABLE"
        assert frozen["reinstate_count"] == 0

        standing_claim = validate_success(
            api.get_cancellation_claim(claim["id"], headers=ADMIN_HEADERS)
        )
        assert_status(standing_claim, "FINALIZED")
        assert standing_claim["effective_classification"] == "CONTROLLABLE"

        month = read_cycle(api, scenario.cycle_id)
        assert month["cancelled_controllable_count"] == 1
        assert month["metric_completed_departures"] == 2
        assert month["departure_ledger_total"] == 3


class TestStaleScorecardBlocksSettlement:
    """An invoice raised after the staling escapes the void cascade but not the gate."""

    def test_settlement_waits_for_the_republished_scorecard_and_then_pays_the_frozen_total(
        self, api
    ):
        """Republishing changes the scorecard's brand figure but not the bill's.

        PRD 3.7: "A scorecard goes `PUBLISHED → STALE` when the month's
        `cancelled_controllable_count` or `cancelled_uncontrollable_count` changed after the
        close, or when a brand audit entered or left the exposure set through creation or
        finding closure."

        PRD 3.8: "Four further conditions apply, and each has its own rejection: the
        `variant` must be `FINAL`, and issuing a provisional bill is refused with
        `ERR_INVOICE_VARIANT_NOT_FINAL` (HTTP 422); the month must be `CLOSED`; every
        pass-through claim of the month must be terminal, failing which
        `ERR_PASSTHROUGH_UNRECONCILED`; and the month's scorecard must be `PUBLISHED`, a
        scorecard sitting in `STALE` blocking settlement with `ERR_SCORECARD_STALE` (HTTP
        409) until it has been recomputed."

        Design: Corner/errors/stale_scorecard_blocks_issue_final
        """
        scenario = build_active_agreement(
            api,
            agreement_payload=make_agreement_payload(),
            station_code="MKE",
            pilots_required_per_aircraft=1,
            aircraft_allocation_cap=1,
        )
        cycle = create_cycle(
            api, scenario.agreement_id, cycle_month="2026-09", published_departures=0
        )
        cycle = open_cycle(api, cycle["id"])
        close_cycle(api, cycle["id"])
        published = scorecard_for_cycle(api, cycle["id"])
        assert_status(published, "PUBLISHED")

        create_brand_audit(
            api, scenario.crew_base_id, audit_scope="UNIFORM", findings_count=2, severity="MINOR"
        )
        assert_status(scorecard_for_cycle(api, cycle["id"]), "STALE")

        invoice = validate_success(
            api.create_invoice(
                cycle["id"],
                make_invoice_payload("FINAL", cycle_version(api, cycle["id"])),
                headers=ADMIN_HEADERS,
            ),
            201,
        )
        assert_status(invoice, "DRAFT")
        assert_is_null(invoice, "void_reason")
        assert_money(invoice["total_usd"], 262500.00, "the frozen final total")

        validate_error(
            api.issue_final_invoice(invoice["id"], headers=ADMIN_HEADERS),
            ERR_SCORECARD_STALE,
            409,
        )
        assert_money(
            read_agreement(api, scenario.agreement_id)["settled_to_date_usd"],
            0.00,
            "settled to date while the scorecard is stale",
        )

        republished = validate_success(
            api.recompute_scorecard(published["id"], headers=ADMIN_HEADERS)
        )
        assert_status(republished, "PUBLISHED")
        assert republished["recompute_count"] == 1
        assert_money(
            republished["brand_penalty_usd"], 1000.00, "two minor findings at 500.00 apiece"
        )

        issued = validate_success(api.issue_final_invoice(invoice["id"], headers=ADMIN_HEADERS))
        assert_status(issued, "ISSUED")

        settled = read_invoice(api, invoice["id"])
        assert_money(
            settled["brand_penalty_component_usd"], 0.00, "the frozen brand penalty component"
        )
        assert_money(settled["total_usd"], 262500.00, "the frozen final total")
        assert_money(
            read_agreement(api, scenario.agreement_id)["settled_to_date_usd"],
            262500.00,
            "settled to date after issuance",
        )
        assert_status(read_cycle(api, cycle["id"]), "SETTLED")


class TestExtensionMustLengthenTheTerm:
    """An offer equal to the standing term end is not an extension at all."""

    def test_an_offer_that_matches_the_current_term_end_creates_no_round(self, api):
        """The agreement stays ACTIVE with its round counter untouched.

        PRD 3.9: "The proposed term end must be strictly later than the agreement's current
        `term_end_date`; a proposal that is not an extension is refused with
        `ERR_EXTENSION_TERM_NOT_LATER` (HTTP 422)."

        Design: Corner/errors/extension_offer_not_later_than_current_term_rejected
        """
        scenario = build_active_agreement(
            api,
            agreement_payload=make_agreement_payload(term_end_date="2029-12-31"),
            station_code="MKE",
            pilots_required_per_aircraft=1,
            aircraft_allocation_cap=1,
        )

        validate_error(
            api.create_extension_negotiation(
                scenario.agreement_id,
                make_extension_offer_payload(
                    agreement_version(api, scenario.agreement_id),
                    proposed_term_end_date="2029-12-31",
                    proposed_block_hour_rate_usd=1500.00,
                ),
                headers=SCHEDULER_HEADERS,
            ),
            ERR_EXTENSION_TERM_NOT_LATER,
            422,
        )

        agreement = read_agreement(api, scenario.agreement_id)
        assert_status(agreement, "ACTIVE")
        assert agreement["term_end_date"] == "2029-12-31"
        assert agreement["extension_round_count"] == 0

        rounds, meta = validate_paginated(
            api.list_extension_negotiations(
                headers=SCHEDULER_HEADERS, params={"agreement_id": scenario.agreement_id}
            )
        )
        assert rounds == []
        assert meta["total_count"] == 0
