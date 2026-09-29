"""Requests that break two rules at once.

Each call below violates a pair of documented conditions simultaneously, and the
contract fixes which one the caller is told about.
"""
import pytest
from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.api_errors import (
    ERR_BOND_CEILING_EXCEEDED,
    ERR_INVALID_TRIP_STATE,
    ERR_SEGREGATION_OF_DUTIES,
)
from test_helpers.assertions import (
    assert_error_envelope,
    assert_jurisdiction_line,
    assert_money,
    assert_return_settlement,
    assert_trip_state,
    by_code,
    codes_of,
)
from test_helpers.constants import JURISDICTION_IL, JURISDICTION_IN, JURISDICTION_KY
from test_helpers.factories import leg
from test_helpers.fixtures import (
    accept_trip,
    capture_trip,
    carrier_version,
    create_carrier,
    create_vehicle,
    open_return,
    prepare_return,
    read_carrier,
    read_return,
    read_trip,
    reconstruct_trip,
    record_purchase,
    return_lines,
    seed_reference_data,
    trip_legs,
)
from test_helpers.test_users import (
    ANALYST_1_HEADERS,
    OFFICER_1_HEADERS,
    make_headers,
)

# A compliance officer's role paired with an identity that is already implicated
# in the record being reviewed.
ANALYST_1_AS_OFFICER = make_headers("analyst-1", "ComplianceOfficer")
PREPARER_1_AS_OFFICER = make_headers("preparer-1", "ComplianceOfficer")


@pytest.fixture
def accepted_reconstruction(client):
    """A reconstructed 500.0-mile trip, behind a 100.0-mile gap, already accepted
    by an officer, with `reconstructed_by_user_id` still naming analyst-1."""
    seed_reference_data(client, jurisdictions=[JURISDICTION_IL, JURISDICTION_KY])
    carrier = create_carrier(
        client,
        legal_name="Priority Pair Trucking LLC",
        usdot_number="USDOT-2637080",
        base_jurisdiction_code="IL",
        bond_ceiling_amount=5000.00,
    )
    vehicle = create_vehicle(
        client,
        carrier["id"],
        unit_number="U-801",
        vin="1FUJA6CK21L600801",
        factory_price_amount=155000.00,
        registration_year=2026,
    )
    # The chronological predecessor ends at 600000.0, so the 600100.0 start
    # leaves a 100.0-mile gap and the trip under test is born GAP_FLAGGED —
    # the only status a reconstruction may be attempted from.
    capture_trip(
        client,
        carrier["id"],
        vehicle["id"],
        "2026-06-04T06:00:00Z",
        "2026-06-04T16:00:00Z",
        599800.0,
        600000.0,
        [leg("IL", 200.0)],
    )
    trip = capture_trip(
        client,
        carrier["id"],
        vehicle["id"],
        "2026-06-05T06:00:00Z",
        "2026-06-05T16:00:00Z",
        600100.0,
        600600.0,
        [leg("IL", 300.0), leg("KY", 200.0)],
    )
    reconstruct_trip(
        client,
        trip["id"],
        [leg("IL", 250.0), leg("KY", 350.0)],
        "RECON-W1",
        headers=ANALYST_1_HEADERS,
    )
    accept_trip(client, trip["id"], headers=OFFICER_1_HEADERS)
    return {
        "carrier_id": carrier["id"],
        "vehicle_id": vehicle["id"],
        "trip_id": trip["id"],
    }


class TestTripStateOutranksSegregationOfDuties:
    """A settled trip is refused for being settled, whoever is asking."""

    def test_reviewing_an_accepted_trip_as_its_own_reconstructor_reports_the_state(
        self, client, accepted_reconstruction
    ):
        """The call breaks two conditions at once. "Attempting it on a trip in any
        other status is refused with `ERR_INVALID_TRIP_STATE`" covers the settled
        status, and "the reviewer's `X-User-ID` must differ from the trip's
        `reconstructed_by_user_id`, or the review is refused with
        `ERR_SEGREGATION_OF_DUTIES`" covers the identity. The state complaint is
        the one returned.

        Design: Difficulty/priority_pair_validation_conflict/already_accepted_trip_review_returns_state_error_before_segregation_check
        """
        ctx = accepted_reconstruction
        response = client.review_trip_record(
            ctx["trip_id"], ANALYST_1_AS_OFFICER, decision="ACCEPT"
        )
        validate_error(response, ERR_INVALID_TRIP_STATE)
        assert_error_envelope(response, ERR_INVALID_TRIP_STATE)

    def test_the_refused_review_leaves_the_trip_and_the_carrier_untouched(
        self, client, accepted_reconstruction
    ):
        """"On acceptance, the carrier's `unsubstantiated_mileage_ratio` and
        `audit_flag` are recomputed and the carrier's `version` increments by 1"
        — a rejected review performs none of that, so the accepted trip keeps its
        reconstructed leg split and the carrier's `version` does not move.

        Design: Difficulty/priority_pair_validation_conflict/already_accepted_trip_review_returns_state_error_before_segregation_check
        """
        ctx = accepted_reconstruction
        version_before = carrier_version(client, ctx["carrier_id"])

        client.review_trip_record(ctx["trip_id"], ANALYST_1_AS_OFFICER, decision="ACCEPT")

        assert_trip_state(
            read_trip(client, ctx["trip_id"]),
            trip_status="ACCEPTED",
            mileage_source="MANUAL_RECONSTRUCTION",
            accepted_leg_miles_total=600.0,
            reconstructed_by_user_id="analyst-1",
        )
        active = trip_legs(client, ctx["trip_id"], leg_status="ACTIVE")
        assert codes_of(active) == ["IL", "KY"], codes_of(active)
        assert by_code(active, "IL")["leg_miles"] == pytest.approx(250.0, abs=0.05)
        assert by_code(active, "KY")["leg_miles"] == pytest.approx(350.0, abs=0.05)
        assert carrier_version(client, ctx["carrier_id"]) == version_before

    def test_the_state_rule_alone_refuses_a_caller_with_clean_hands(
        self, client, accepted_reconstruction
    ):
        """"Attempting it on a trip in any other status is refused with
        `ERR_INVALID_TRIP_STATE`." An officer who never touched the
        reconstruction satisfies the segregation rule and is still refused, which
        shows the state condition is independently sufficient.

        Design: Difficulty/priority_pair_validation_conflict/already_accepted_trip_review_returns_state_error_before_segregation_check
        """
        response = client.review_trip_record(
            accepted_reconstruction["trip_id"], OFFICER_1_HEADERS, decision="ACCEPT"
        )
        validate_error(response, ERR_INVALID_TRIP_STATE)

    def test_the_segregation_rule_does_surface_once_the_state_condition_is_clear(
        self, client
    ):
        """"the reviewer's `X-User-ID` must differ from the trip's
        `reconstructed_by_user_id`, or the review is refused with
        `ERR_SEGREGATION_OF_DUTIES`." Left in `RECONSTRUCTED`, the identical call
        reports the identity rather than the state, so the two rules are ordered
        rather than one permanently masking the other.

        Design: Difficulty/priority_pair_validation_conflict/already_accepted_trip_review_returns_state_error_before_segregation_check
        """
        seed_reference_data(client, jurisdictions=[JURISDICTION_IL, JURISDICTION_KY])
        carrier = create_carrier(
            client,
            legal_name="Priority Pair Trucking LLC",
            usdot_number="USDOT-2637081",
            base_jurisdiction_code="IL",
            bond_ceiling_amount=5000.00,
        )
        vehicle = create_vehicle(
            client,
            carrier["id"],
            unit_number="U-802",
            vin="1FUJA6CK21L600802",
            factory_price_amount=155000.00,
            registration_year=2026,
        )
        # The predecessor ends at 600000.0, so the trip under test carries a
        # 100.0-mile gap and is born GAP_FLAGGED, which is the only status
        # reconstruction is reachable from.
        capture_trip(
            client,
            carrier["id"],
            vehicle["id"],
            "2026-06-04T06:00:00Z",
            "2026-06-04T16:00:00Z",
            599800.0,
            600000.0,
            [leg("IL", 200.0)],
        )
        trip = capture_trip(
            client,
            carrier["id"],
            vehicle["id"],
            "2026-06-05T06:00:00Z",
            "2026-06-05T16:00:00Z",
            600100.0,
            600600.0,
            [leg("IL", 300.0), leg("KY", 200.0)],
        )
        reconstruct_trip(
            client,
            trip["id"],
            [leg("IL", 250.0), leg("KY", 350.0)],
            "RECON-W2",
            headers=ANALYST_1_HEADERS,
        )

        response = client.review_trip_record(
            trip["id"], ANALYST_1_AS_OFFICER, decision="ACCEPT"
        )
        validate_error(response, ERR_SEGREGATION_OF_DUTIES)
        assert_trip_state(read_trip(client, trip["id"]), trip_status="RECONSTRUCTED")


def _prepare_thin_bond_quarter(
    client,
    bond_ceiling_amount,
    usdot_number,
    unit_number,
    vin,
    start_odometer,
    receipt_reference,
):
    """A Q2-2026 quarter settling at 20.24 against the supplied bond ceiling.

    1000.0 accepted miles split IL 200.0 / IN 800.0 against 100.000 tax-paid
    Illinois gallons puts Illinois in credit and Indiana in a surcharge-heavy
    debit, and the quarter carries no reconstruction penalty.
    """
    carrier = create_carrier(
        client,
        legal_name="Thin Bond Transport LLC",
        usdot_number=usdot_number,
        base_jurisdiction_code="IL",
        bond_ceiling_amount=bond_ceiling_amount,
    )
    vehicle = create_vehicle(
        client,
        carrier["id"],
        unit_number=unit_number,
        vin=vin,
        factory_price_amount=151000.00,
        registration_year=2026,
    )
    trip = capture_trip(
        client,
        carrier["id"],
        vehicle["id"],
        "2026-04-20T06:00:00Z",
        "2026-04-20T22:00:00Z",
        start_odometer,
        start_odometer + 1000.0,
        [leg("IL", 200.0), leg("IN", 800.0)],
    )
    accept_trip(client, trip["id"], headers=OFFICER_1_HEADERS)
    record_purchase(
        client,
        carrier["id"],
        vehicle["id"],
        "IL",
        "2026-04-21",
        100.000,
        receipt_reference=receipt_reference,
    )
    opened = open_return(client, carrier["id"], 2026, 2)
    prepared = prepare_return(client, opened["id"], carrier["id"])
    return {
        "carrier_id": carrier["id"],
        "vehicle_id": vehicle["id"],
        "return_id": opened["id"],
        "prepared": prepared,
    }


@pytest.fixture
def prepared_quarter_over_a_five_dollar_ceiling(client):
    """A prepared Q2-2026 quarter owing 20.24 against a 5.00 bond ceiling."""
    seed_reference_data(client, jurisdictions=[JURISDICTION_IL, JURISDICTION_IN])
    return _prepare_thin_bond_quarter(
        client,
        bond_ceiling_amount=5.00,
        usdot_number="USDOT-2637090",
        unit_number="U-901",
        vin="1FUJA6CK21L600901",
        start_odometer=700000.0,
        receipt_reference="RCPT-IL-9-0421",
    )


class TestSegregationOfDutiesOutranksTheBondCeiling:
    """The caller is told who may not file before being told how much is too much
    to file."""

    def test_both_filing_conditions_really_are_violated(
        self, client, prepared_quarter_over_a_five_dollar_ceiling
    ):
        """"The return's `total_amount_due` must be no greater than the carrier's
        `bond_ceiling_amount`; a return whose amount due exceeds the ceiling is
        not covered by the carrier's bond and is refused with
        `ERR_BOND_CEILING_EXCEEDED` (HTTP 402)." The quarter settles at 20.24 against
        a 5.00 ceiling, and the filer named below is also the preparer, so both
        the fiscal condition and the identity condition fail.

        Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_beats_bond_ceiling_on_return_filing
        """
        ctx = prepared_quarter_over_a_five_dollar_ceiling
        assert_return_settlement(
            ctx["prepared"],
            return_status="PREPARED",
            fleet_mpg=10.00,
            total_net_tax_due=20.24,
            reconstruction_penalty_amount=0.00,
            total_amount_due=20.24,
        )
        lines = return_lines(client, ctx["return_id"], line_status="ACTIVE")
        assert_jurisdiction_line(by_code(lines, "IL"), net_tax_amount=-50.16)
        assert_jurisdiction_line(by_code(lines, "IN"), net_tax_amount=70.40)
        assert_money(
            read_carrier(client, ctx["carrier_id"])["bond_ceiling_amount"],
            5.00,
            "bond_ceiling_amount",
        )

    def test_filing_as_the_preparer_reports_the_identity_and_not_the_money(
        self, client, prepared_quarter_over_a_five_dollar_ceiling
    ):
        """"Both decisions require that the reviewer's `X-User-ID` differ from the
        return's `prepared_by_user_id`, failing which the review is refused with
        `ERR_SEGREGATION_OF_DUTIES`. ... Filing carries one additional, fiscal
        condition." The additional condition never runs.

        Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_beats_bond_ceiling_on_return_filing
        """
        ctx = prepared_quarter_over_a_five_dollar_ceiling
        response = client.review_fuel_tax_return(
            ctx["return_id"], PREPARER_1_AS_OFFICER, decision="FILE"
        )
        validate_error(response, ERR_SEGREGATION_OF_DUTIES)
        assert_error_envelope(response, ERR_SEGREGATION_OF_DUTIES)

        unfiled = read_return(client, ctx["return_id"])
        assert_return_settlement(unfiled, return_status="PREPARED")
        assert unfiled["filed_by_user_id"] is None, unfiled["filed_by_user_id"]
        assert unfiled["filed_at"] is None, unfiled["filed_at"]

    def test_clearing_the_identity_condition_surfaces_the_bond_ceiling(
        self, client, prepared_quarter_over_a_five_dollar_ceiling
    ):
        """"a return whose amount due exceeds the ceiling is not covered by the
        carrier's bond and is refused with `ERR_BOND_CEILING_EXCEEDED` (HTTP
        402)." An
        officer who did not prepare the return clears the identity condition, and
        the money condition then reports itself — so the pair is ordered rather
        than one rule hiding the other.

        Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_beats_bond_ceiling_on_return_filing
        """
        ctx = prepared_quarter_over_a_five_dollar_ceiling
        response = client.review_fuel_tax_return(
            ctx["return_id"], OFFICER_1_HEADERS, decision="FILE"
        )
        validate_error(response, ERR_BOND_CEILING_EXCEEDED)
        assert_return_settlement(
            read_return(client, ctx["return_id"]), return_status="PREPARED"
        )

    def test_neither_rule_is_a_permanent_blocker(self, client):
        """"An amount exactly equal to the ceiling is covered and files
        successfully. On a successful filing the return moves `PREPARED → FILED`,
        `filed_by_user_id` is stamped with the filing officer's `X-User-ID` —
        necessarily a different identity from `prepared_by_user_id` — and
        `filed_at` is stamped with the logical clock." The same
        20.24 quarter behind a 5000.00 ceiling, filed by an officer who did not
        prepare it, goes through.

        Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_beats_bond_ceiling_on_return_filing
        """
        seed_reference_data(client, jurisdictions=[JURISDICTION_IL, JURISDICTION_IN])
        ctx = _prepare_thin_bond_quarter(
            client,
            bond_ceiling_amount=5000.00,
            usdot_number="USDOT-2637091",
            unit_number="U-902",
            vin="1FUJA6CK21L600902",
            start_odometer=800000.0,
            receipt_reference="RCPT-IL-9-0421-B",
        )
        assert_return_settlement(ctx["prepared"], total_amount_due=20.24)

        response = client.review_fuel_tax_return(
            ctx["return_id"], OFFICER_1_HEADERS, decision="FILE"
        )
        filed = validate_success(response)
        assert_return_settlement(filed, return_status="FILED", total_amount_due=20.24)
        assert filed["filed_by_user_id"] == "officer-1", filed["filed_by_user_id"]
        assert filed["filed_at"] is not None
