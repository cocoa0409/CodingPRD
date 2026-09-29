"""What the ordered validation bands admit and refuse: role before existence,
route shape before the bond selector, and the cross-entity, temporal, fiscal and
conditional rules in between."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors, factories
from test_helpers.assertions import (
    assert_bond_amounts,
    assert_deadline,
    assert_field,
    assert_money,
    assert_movement_state,
)
from test_helpers.fixtures import (
    M1_DEADLINE,
    M1_OBLIGATION,
    build_carrier_without_bond,
    build_departed_movement,
)
from test_helpers.test_users import CBP_OFFICER_1_ID

UNKNOWN_MOVEMENT_ID = "00000000-0000-0000-0000-000000009999"
TINY_BOND = {"limit_amount": 100.00, "surety_code": "SUR-500"}


class TestBandOrdering:
    """The first failing band decides the answer, whatever else is also wrong."""

    def test_a_carrier_claiming_against_an_unknown_movement_is_unauthorized(
        self, client
    ):
        """Issuing a claim is an officer's act, so the carrier's request fails on
        role authorisation in band 2 and never reaches the band-6 existence check
        that would have called the movement missing.

        PRD: "Validation is strictly ordered. The **first** check that fails determines the response; no later check may mask an earlier one, and no check may be evaluated out of band."

        PRD: "**Role authorisation.** The caller's role appears in the endpoint's authorised list — otherwise `ERR_UNAUTHORIZED`. Evaluated on every request."

        Design: Corner/validations/role_denial_outranks_not_found_returns_unauthorized
        """
        world = build_carrier_without_bond(client)

        response = client.issue_claim(
            factories.claim_payload(UNKNOWN_MOVEMENT_ID, "LATE_ARRIVAL"),
            world.carrier,
        )
        validate_error(response, api_errors.ERR_UNAUTHORIZED, 403)

        _rows, meta = world.claims()
        assert meta["total_count"] == 0, (
            f"the refused request must not create a claim but the ledger of claims "
            f"holds {meta['total_count']}"
        )

    def test_route_shape_is_refused_before_the_bond_selector_is_consulted(self, client):
        """An IE filing between two different ports by a carrier with no bond at all
        breaks the band-13 route rule and the band-14 fiscal rule together, and the
        route rule answers first.

        PRD: "That last distinction constrains the routing: an `IE` filing requires that `destination_port_id` be the same port as `origin_port_id`, while `IT` and `TE` filings require that the two differ."

        PRD: "**Business constraints.** `ERR_ROUTE_TYPE_MISMATCH`, `ERR_STB_WINDOW_CONFLICT`, `ERR_EXAM_CAPACITY_EXCEEDED`, `ERR_EXTENSION_LIMIT_EXCEEDED`, `ERR_GRANTED_DAYS_INVALID`, `ERR_PETITION_ROUND_LIMIT`, `ERR_HOLD_TYPE_NOT_ALLOWED`, `ERR_REPORT_TYPE_NOT_ALLOWED`, `ERR_DUPLICATE_CLAIM`, `ERR_NO_VIOLATION_TO_CLAIM`, `ERR_MITIGATION_FACTOR_INVALID`."

        PRD: "**Fiscal.** `ERR_BOND_INSUFFICIENT`, `ERR_NO_ELIGIBLE_BOND`, `ERR_PAYMENT_AMOUNT_MISMATCH`."

        Design: Corner/validations/route_shape_is_checked_before_bond_eligibility
        """
        world = build_carrier_without_bond(client)

        response = client.file_movement(
            factories.movement_payload(
                world.carrier_id,
                world.ports["ny"],
                world.ports["chicago"],
                "MAN-0031",
                in_bond_type="IE",
            ),
            world.carrier,
        )
        validate_error(response, api_errors.ERR_ROUTE_TYPE_MISMATCH, 422)

        _movements, movement_meta = world.movement_list(carrier_id=world.carrier_id)
        assert movement_meta["total_count"] == 0, (
            f"the refused filing must not create a movement but the carrier has "
            f"{movement_meta['total_count']}"
        )

        _bonds, bond_meta = validate_paginated(
            client.list_bonds(world.officer, params={"carrier_id": world.carrier_id})
        )
        assert bond_meta["total_count"] == 0, (
            f"this carrier was never given a bond but the register holds "
            f"{bond_meta['total_count']}"
        )


class TestOnwardLeg:
    """An onward leg waits for its predecessor to arrive."""

    def test_the_onward_leg_is_refused_until_its_predecessor_arrives(self, client):
        """The identical onward filing is refused while the first leg is only
        IN_TRANSIT and accepted the moment that leg reports arrival, earning 30 days
        because both of its ports sit in the same region.

        PRD: "When `predecessor_movement_id` is supplied, the referenced movement must exist, must belong to the same carrier, and must have reached `transit_status` `ARRIVED`; an onward leg may only be filed against an arrived predecessor, and a predecessor that has not arrived or belongs to another carrier yields `ERR_PREDECESSOR_NOT_ARRIVED`."

        Design: Corner/validations/onward_leg_against_an_unarrived_predecessor_rejected
        """
        world = build_departed_movement(
            client, port_aliases=["ny", "chicago", "detroit"]
        )
        first_leg = world.movements["MAN-0001"]

        def file_onward_leg():
            return client.file_movement(
                factories.movement_payload(
                    world.carrier_id,
                    world.ports["chicago"],
                    world.ports["detroit"],
                    "MAN-0010",
                    bond_id=world.bond_id,
                    predecessor_movement_id=first_leg,
                ),
                world.carrier,
            )

        validate_error(
            file_onward_leg(), api_errors.ERR_PREDECESSOR_NOT_ARRIVED, 409
        )
        assert_bond_amounts(
            world.read_bond(), obligated=M1_OBLIGATION, open_movement_count=1
        )

        world.set_clock("2026-08-10T00:00:00Z")
        world.report_arrival(first_leg)

        onward = validate_success(file_onward_leg(), 201)
        assert_field(
            onward, "predecessor_movement_id", first_leg, "movement"
        )
        assert_movement_state(onward, transit_status="FILED")
        assert_deadline(
            onward,
            anchor="2026-08-10T00:00:00Z",
            deadline="2026-09-09T00:00:00Z",
            transit_days_allowed=30,
        )
        assert_bond_amounts(world.read_bond(), obligated=83.50)


class TestBondCoverageAndSufficiency:
    """A bond must outlive the transit by three days and still have the headroom
    for it."""

    def test_a_bond_lapsing_inside_the_coverage_margin_cannot_underwrite(self, client):
        """The movement's 2026-09-05 deadline needs coverage through 2026-09-08, so
        the bond expiring 2026-09-06 is refused while the one expiring 2026-09-09
        takes the filing.

        PRD: "The bond must also cover the whole transit: its `expiry_date` must fall at or after the movement's computed transit deadline plus a three-day coverage margin, and its `effective_date` must fall at or before the current logical clock."

        Design: Corner/validations/bond_lapsing_before_the_deadline_margin_rejected
        """
        world = build_carrier_without_bond(client)
        short_bond = world.underwrite_bond(
            factories.continuous_bond_payload(
                world.carrier_id,
                expiry_date="2026-09-06T00:00:00Z",
                surety_code="SUR-300",
            )
        )
        covering_bond = world.underwrite_bond(
            factories.continuous_bond_payload(
                world.carrier_id,
                expiry_date="2026-09-09T00:00:00Z",
                surety_code="SUR-400",
            )
        )

        def file_on(bond_id):
            return client.file_movement(
                factories.movement_payload(
                    world.carrier_id,
                    world.ports["ny"],
                    world.ports["chicago"],
                    "MAN-0011",
                    bond_id=bond_id,
                ),
                world.carrier,
            )

        validate_error(file_on(short_bond), api_errors.ERR_BOND_COVERAGE_GAP, 422)
        assert_bond_amounts(
            world.read_bond(short_bond), obligated=0.00, open_movement_count=0
        )

        movement = validate_success(file_on(covering_bond), 201)
        assert movement["bond_id"] == covering_bond, (
            "the filing should be underwritten by the covering bond but names "
            f"{movement['bond_id']}"
        )
        assert_deadline(movement, deadline=M1_DEADLINE)
        assert_bond_amounts(world.read_bond(covering_bond), obligated=M1_OBLIGATION)

    def test_the_third_filing_exhausts_a_hundred_dollar_bond(self, client):
        """Each 41.75 obligation is affordable on its own, but the third one needs
        41.75 against 16.50 of headroom and is refused on the fiscal gate.

        PRD: "**The fiscal gate.** Last of all, the computed `obligation_amount` must be no greater than the bond's `available_amount`."

        PRD: "Exceeding the headroom is `ERR_BOND_INSUFFICIENT`."

        Design: Corner/validations/third_filing_exceeds_the_bond_limit_in_aggregate
        """
        world = build_carrier_without_bond(client)
        bond_id = world.underwrite_bond(
            factories.continuous_bond_payload(world.carrier_id, **TINY_BOND)
        )
        world.file_movement("MAN-0021", bond_id=bond_id)
        world.file_movement("MAN-0022", bond_id=bond_id)

        response = client.file_movement(
            factories.movement_payload(
                world.carrier_id,
                world.ports["ny"],
                world.ports["chicago"],
                "MAN-0023",
                bond_id=bond_id,
            ),
            world.carrier,
        )
        validate_error(response, api_errors.ERR_BOND_INSUFFICIENT, 422)

        assert_bond_amounts(
            world.read_bond(bond_id),
            obligated=83.50,
            available=16.50,
            status="ACTIVE",
            open_movement_count=2,
        )
        _entries, ledger_meta = world.ledger_page(bond_id=bond_id)
        assert ledger_meta["total_count"] == 2, (
            f"only the two accepted filings should have written entries but the "
            f"audit trail holds {ledger_meta['total_count']}"
        )
        _movements, movement_meta = world.movement_list(bond_id=bond_id)
        assert movement_meta["total_count"] == 2, (
            f"the bond should carry two movements but carries "
            f"{movement_meta['total_count']}"
        )


class TestExamWindowShape:
    """Whether a window is required flips on the hold type."""

    def test_the_window_requirement_depends_on_the_hold_type(self, client):
        """A windowless EXAM_PHYSICAL and a windowed DOCUMENT hold are both refused,
        and only the correctly shaped scheduled hold is opened.

        PRD: "`EXAM_NII` (non-intrusive inspection) and `EXAM_PHYSICAL` occupy a scheduled examination window and therefore require both a `scheduled_start`, the inclusive start of the window, and a `scheduled_end`, the exclusive end, with the end strictly after the start."

        PRD: "A missing or inverted window on a scheduled type, or a window supplied on a `DOCUMENT` or `PGA` hold, is `ERR_EXAM_WINDOW_INVALID`."

        Design: Corner/validations/exam_window_requirement_is_conditional_on_hold_type
        """
        world = build_departed_movement(client)
        movement_id = world.movements["MAN-0001"]
        port_id = world.ports["chicago"]

        validate_error(
            client.place_hold(
                factories.unscheduled_hold_payload(
                    movement_id, port_id, "EXAM_PHYSICAL", "TARGETED_EXAM"
                ),
                world.officer,
            ),
            api_errors.ERR_EXAM_WINDOW_INVALID,
            422,
        )
        validate_error(
            client.place_hold(
                factories.scheduled_hold_payload(
                    movement_id,
                    port_id,
                    "2026-08-05T08:00:00Z",
                    "2026-08-05T12:00:00Z",
                    "DOCUMENT",
                    "MANIFEST_REVIEW",
                ),
                world.officer,
            ),
            api_errors.ERR_EXAM_WINDOW_INVALID,
            422,
        )

        hold = validate_success(
            client.place_hold(
                factories.scheduled_hold_payload(
                    movement_id,
                    port_id,
                    "2026-08-05T08:00:00Z",
                    "2026-08-05T12:00:00Z",
                ),
                world.officer,
            ),
            201,
        )
        assert_field(hold, "status", "OPEN", "hold")
        assert_field(hold, "scheduled_start", "2026-08-05T08:00:00Z", "hold")
        assert_field(hold, "scheduled_end", "2026-08-05T12:00:00Z", "hold")
        assert_field(hold, "placed_by_user_id", CBP_OFFICER_1_ID, "hold")

        assert_field(world.read_port("chicago"), "open_hold_count", 1, "port")
        assert_movement_state(
            world.read_movement(movement_id), custody_status="EXAM_HOLD"
        )


class TestArrivalPortRules:
    """An in-region arrival elsewhere is a flagged deviation; an out-of-region one
    is an unauthorized diversion."""

    def test_an_in_region_arrival_elsewhere_is_accepted_and_flagged(self, client):
        """Detroit shares Chicago's region, so the arrival is accepted, flagged as a
        diversion, and leaves the declared destination as it was.

        PRD: "Three situations are accepted: the reporting `port_id` is the movement's `destination_port_id`; the reporting port is a different port but shares the destination port's `region_code`, which the system treats as a minor deviation; or an already-approved `DIVERSION` amendment has previously moved `destination_port_id` to the reporting port."

        Design: Corner/validations/in_region_arrival_at_another_port_passes_as_a_flagged_diversion
        """
        world = build_departed_movement(
            client, port_aliases=["ny", "chicago", "detroit"]
        )
        movement_id = world.movements["MAN-0001"]
        world.set_clock("2026-08-10T00:00:00Z")

        report = validate_success(
            client.file_report(
                factories.arrival_report_payload(
                    movement_id, world.ports["detroit"], factories.PACKAGE_COUNT
                ),
                world.carrier,
            ),
            201,
        )
        assert_field(report, "status", "ACCEPTED", "report")
        assert_field(report, "port_id", world.ports["detroit"], "report")
        assert_field(report, "package_discrepancy", 0, "report")

        movement = world.read_movement(movement_id)
        assert_movement_state(movement, transit_status="ARRIVED")
        assert_field(movement, "arrival_port_id", world.ports["detroit"], "movement")
        assert_field(
            movement, "destination_port_id", world.ports["chicago"], "movement"
        )
        assert_field(movement, "diversion_flag", True, "movement")
        assert_field(movement, "go_deadline_utc", "2026-08-25T00:00:00Z", "movement")

    def test_an_out_of_region_arrival_without_an_approved_diversion_is_refused(
        self, client
    ):
        """Los Angeles is in another region and no diversion was ever approved, so
        the report is refused and the movement is left untouched on the road.

        PRD: "Anything else — an arrival at a port outside the destination's region with no approved diversion on the movement — is not a discrepancy but an unauthorized diversion, refused with `ERR_UNAUTHORIZED_DIVERSION`."

        Design: Corner/validations/out_of_region_arrival_without_an_approved_diversion_rejected
        """
        world = build_departed_movement(client, port_aliases=["ny", "chicago", "la"])
        movement_id = world.movements["MAN-0001"]
        world.set_clock("2026-08-10T00:00:00Z")

        response = client.file_report(
            factories.arrival_report_payload(
                movement_id, world.ports["la"], factories.PACKAGE_COUNT
            ),
            world.carrier,
        )
        validate_error(response, api_errors.ERR_UNAUTHORIZED_DIVERSION, 422)

        movement = world.read_movement(movement_id)
        assert_movement_state(movement, transit_status="IN_TRANSIT")
        assert_field(movement, "arrival_port_id", None, "movement")
        assert_field(movement, "arrival_reported_at", None, "movement")
        assert_field(movement, "diversion_flag", False, "movement")
        assert_money(
            movement["obligation_amount"], M1_OBLIGATION, "obligation_amount"
        )

        _rows, meta = world.reports(movement_id=movement_id)
        assert meta["total_count"] == 0, (
            f"the refused report must not be stored but the movement carries "
            f"{meta['total_count']}"
        )
