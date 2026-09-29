"""Lifecycles that loop and lifecycles that run on two orthogonal dimensions.

The classify/dispute bargaining loop is bounded by a counter rather than by the
state alphabet, and a brand audit's terminal finding step is gated on the other
dimension entirely.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.api_errors import ERR_DISPUTE_ROUNDS_EXHAUSTED, ERR_REMEDIATION_NOT_VERIFIED
from test_helpers.assertions import assert_departure_ledger_identity, assert_status
from test_helpers.factories import (
    make_agreement_payload,
    make_dispute_payload,
    make_remediation_payload,
)
from test_helpers.fixtures import (
    acknowledge_brand_audit,
    add_leg,
    advance_remediation,
    build_active_agreement,
    build_open_cycle,
    cancel_leg,
    claim_for_leg,
    classify_claim,
    create_brand_audit,
    dispute_claim,
    read_brand_audit,
    read_cycle,
)
from test_helpers.test_users import AUDITOR_HEADERS, OPS_HEADERS


def _build_twice_disputed_claim(api):
    """A claim that has run the bargaining loop to its bound and sits classified."""
    scenario = build_open_cycle(
        api,
        agreement_payload=make_agreement_payload(),
        station_code="MKE",
        pilots_required_per_aircraft=1,
        aircraft_allocation_cap=2,
        line_qualified_pilots=1,
        tail_numbers=["N601RG"],
        cycle_month="2026-09",
        published_departures=10,
    )
    leg = add_leg(
        api,
        scenario,
        flight_number="SM4401",
        origin="MKE",
        destination="ORD",
        scheduled_departure_utc="2026-09-03T08:00:00Z",
        scheduled_arrival_utc="2026-09-03T09:00:00Z",
        planned_block_hours=1.000,
    )
    cancel_leg(api, leg["id"], cause_code="MAINTENANCE")
    claim = claim_for_leg(api, leg["id"])

    classify_claim(api, claim["id"], "CONTROLLABLE")
    dispute_claim(api, claim["id"], "Maintenance was caused by a mainline-supplied part")
    classify_claim(api, claim["id"], "UNCONTROLLABLE")
    dispute_claim(api, claim["id"], "Second review requested with maintenance log attached")
    classify_claim(api, claim["id"], "CONTROLLABLE")
    return scenario, claim


class TestCancellationBargainingLoop:
    """Classification and dispute form a genuine cycle bounded at two rounds."""

    def test_a_third_dispute_is_refused_once_two_rounds_have_been_used(self, api):
        """The loop is closed by the round counter, not by the claim's state.

        PRD 3.5: "Each dispute raises `dispute_round` by 1, and the loop is bounded: a
        claim whose `dispute_round` has already reached two may not be disputed again,
        and the attempt is refused with `ERR_DISPUTE_ROUNDS_EXHAUSTED` (HTTP 409)."

        Design: Difficulty/non_linear_state_machine/cancellation_claim_dispute_reclassify_cycle_bounded_at_two_rounds
        """
        _scenario, claim = _build_twice_disputed_claim(api)

        response = api.dispute_claim(
            claim["id"], make_dispute_payload("Third dispute attempt"), headers=OPS_HEADERS
        )
        validate_error(response, ERR_DISPUTE_ROUNDS_EXHAUSTED, 409)

        standing = validate_success(api.get_cancellation_claim(claim["id"], headers=OPS_HEADERS))
        assert_status(standing, "CLASSIFIED")
        assert standing["dispute_round"] == 2, "the refused dispute should not raise the round"
        assert standing["classification"] == "CONTROLLABLE", (
            "the second pass through classification should have overwritten the earlier verdict"
        )

    def test_the_whole_loop_moves_no_month_counter_because_nothing_was_finalized(self, api):
        """The attribution stays pinned to the regional carrier throughout the loop.

        PRD 3.5: "`effective_classification` is the attribution the settlement actually
        uses, and it equals `classification` only once the claim has reached
        `FINALIZED`; at every earlier point it is pinned to `CONTROLLABLE`, regardless
        of what the mainline has provisionally said."

        Design: Difficulty/non_linear_state_machine/cancellation_claim_dispute_reclassify_cycle_bounded_at_two_rounds
        """
        scenario, claim = _build_twice_disputed_claim(api)

        validate_error(
            api.dispute_claim(
                claim["id"], make_dispute_payload("Third dispute attempt"), headers=OPS_HEADERS
            ),
            ERR_DISPUTE_ROUNDS_EXHAUSTED,
            409,
        )

        standing = validate_success(api.get_cancellation_claim(claim["id"], headers=OPS_HEADERS))
        assert standing["effective_classification"] == "CONTROLLABLE", (
            "an unfinalized claim is attributed to the regional carrier whatever the verdict says"
        )

        cycle = read_cycle(api, scenario.cycle_id)
        assert cycle["cancelled_controllable_count"] == 1
        assert cycle["cancelled_uncontrollable_count"] == 0
        assert cycle["metric_completed_departures"] == 9
        assert cycle["departure_ledger_total"] == 10
        assert_departure_ledger_identity(cycle)


def _build_audit_in_remediation(api):
    """A major finding acknowledged on one dimension and under way on the other."""
    scenario = build_active_agreement(
        api,
        agreement_payload=make_agreement_payload(),
        station_code="IND",
        pilots_required_per_aircraft=1,
        aircraft_allocation_cap=1,
    )
    audit = create_brand_audit(
        api, scenario.crew_base_id, audit_scope="UNIFORM", findings_count=2, severity="MAJOR"
    )
    after_acknowledge = acknowledge_brand_audit(api, audit["id"])
    after_remediation = advance_remediation(api, audit["id"], "IN_PROGRESS")
    return audit, after_acknowledge, after_remediation


class TestBrandAuditTwoDimensions:
    """Two independent status dimensions on one row, interacting at one point only."""

    def test_closing_the_finding_is_refused_until_remediation_is_verified(self, api):
        """The cross-dimension guard blocks the terminal finding step.

        PRD 3.7: "Closing the finding belongs to the `BrandAuditor`: `finding_status`
        moves `ACKNOWLEDGED → CLOSED`, but only if `remediation_status` has already
        reached `VERIFIED`."

        Design: Difficulty/non_linear_state_machine/brand_audit_two_independent_status_dimensions
        """
        audit, _after_acknowledge, _after_remediation = _build_audit_in_remediation(api)

        response = api.close_brand_audit(audit["id"], headers=AUDITOR_HEADERS)
        validate_error(response, ERR_REMEDIATION_NOT_VERIFIED, 409)

        standing = read_brand_audit(api, audit["id"])
        assert_status(standing, "ACKNOWLEDGED", field="finding_status")
        assert_status(standing, "IN_PROGRESS", field="remediation_status")

    def test_each_dimension_advances_without_disturbing_the_other(self, api):
        """Acknowledging and remediating each move one dimension alone, then the
        verified remediation unlocks the close.

        PRD 3.7: "Remediation never touches `finding_status`, so a carrier may complete
        and verify its remediation before it has acknowledged the finding, or the other
        way round."

        Design: Difficulty/non_linear_state_machine/brand_audit_two_independent_status_dimensions
        """
        audit, after_acknowledge, after_remediation = _build_audit_in_remediation(api)

        assert_status(after_acknowledge, "ACKNOWLEDGED", field="finding_status")
        assert_status(after_acknowledge, "NOT_STARTED", field="remediation_status")
        assert_status(after_remediation, "ACKNOWLEDGED", field="finding_status")
        assert_status(after_remediation, "IN_PROGRESS", field="remediation_status")

        validate_error(
            api.close_brand_audit(audit["id"], headers=AUDITOR_HEADERS),
            ERR_REMEDIATION_NOT_VERIFIED,
            409,
        )

        verified = validate_success(
            api.advance_remediation(
                audit["id"],
                make_remediation_payload("VERIFIED", evidence_ref="UNIFORM-FIX-PHOTOS-01"),
                headers=OPS_HEADERS,
            )
        )
        assert_status(verified, "VERIFIED", field="remediation_status")
        assert verified["evidence_ref"] == "UNIFORM-FIX-PHOTOS-01"

        closed = validate_success(api.close_brand_audit(audit["id"], headers=AUDITOR_HEADERS))
        assert_status(closed, "CLOSED", field="finding_status")
