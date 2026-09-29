"""Every refusal the contract names: pagination bounds, the lookup codes, the
uniqueness conflicts, the state conflicts, and the business, temporal and fiscal
constraints — each one leaving the world exactly as it found it."""

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
    assert_ledger_stream,
    assert_money,
    assert_movement_state,
    assert_points,
)
from test_helpers.fixtures import (
    LATE_ARRIVAL_ASSESSED,
    M1_DEADLINE,
    M1_OBLIGATION,
    M1_SEAL,
    build_carrier_without_bond,
    build_departed_movement,
    build_empty_world,
    build_filed_movement,
    build_general_order_world,
    build_late_arrival_claim,
    build_registered_world,
    build_supplement_requested_petition,
)

#: Identifiers that resolve to nothing, one per lookup code under test.
MISSING_CARRIER_ID = "00000000-0000-0000-0000-000000000001"
MISSING_HOLD_ID = "00000000-0000-0000-0000-000000000002"
MISSING_AMENDMENT_ID = "00000000-0000-0000-0000-000000000003"
MISSING_REPORT_ID = "00000000-0000-0000-0000-000000000004"
MISSING_CLAIM_ID = "00000000-0000-0000-0000-000000000005"
MISSING_PETITION_ID = "00000000-0000-0000-0000-000000000006"
MISSING_LEDGER_ENTRY_ID = "00000000-0000-0000-0000-000000000007"


class TestPaginationBounds:
    """The window is 1 through 100 inclusive, and the edges are enforced."""

    def test_a_limit_of_zero_and_a_limit_of_101_are_both_refused(self, client):
        """Both ends outside the window are rejected on the movement list, while a
        limit of exactly 100 — the largest the contract allows — is honoured.

        PRD: "A `limit` outside the range 1 through 100 inclusive, or a negative `offset`, is rejected with `ERR_INVALID_PAGINATION` (HTTP 400)."

        PRD: "Every list response carries `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope."

        Design: Corner/errors/pagination_bounds_are_enforced_on_list_reads
        """
        world = build_filed_movement(client)

        validate_error(
            client.list_movements(world.officer, params={"limit": 0, "offset": 0}),
            api_errors.ERR_INVALID_PAGINATION,
            400,
        )
        validate_error(
            client.list_movements(world.officer, params={"limit": 101, "offset": 0}),
            api_errors.ERR_INVALID_PAGINATION,
            400,
        )

        rows, meta = validate_paginated(
            client.list_movements(world.officer, params={"limit": 100, "offset": 0})
        )
        assert len(rows) == 1, (
            f"the one filed movement should come back in a window of a hundred but "
            f"{len(rows)} rows did"
        )
        assert meta["total_count"] == 1, (
            f"total_count should count the single movement but reads "
            f"{meta['total_count']}"
        )
        assert meta["limit"] == 100, (
            f"the accepted limit should be echoed as 100 but reads {meta['limit']}"
        )
        assert meta["offset"] == 0, (
            f"the offset should be echoed as 0 but reads {meta['offset']}"
        )
        assert meta["has_more"] is False, (
            "one row inside a window of a hundred leaves nothing beyond it"
        )


class TestLookupCodes:
    """Each record type answers a miss with its own code."""

    def test_each_record_type_reports_its_own_not_found_code(self, client):
        """Seven lookups against seven unknown identifiers produce seven distinct 404
        codes, and the ledger read is the one that answers with the generic code.

        PRD: "**Existence.** Each referenced record exists, with a distinct error per record type: `ERR_CARRIER_NOT_FOUND`, `ERR_BOND_NOT_FOUND`, `ERR_PORT_NOT_FOUND`, `ERR_MOVEMENT_NOT_FOUND`, `ERR_HOLD_NOT_FOUND`, `ERR_AMENDMENT_NOT_FOUND`, `ERR_REPORT_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_PETITION_NOT_FOUND`, and `ERR_RESOURCE_NOT_FOUND` for a ledger entry read."

        Design: Corner/errors/every_remaining_lookup_code_is_reachable_and_not_found
        """
        world = build_empty_world(client)

        validate_error(
            client.get_carrier(MISSING_CARRIER_ID, world.officer),
            api_errors.ERR_CARRIER_NOT_FOUND,
            404,
        )
        validate_error(
            client.get_hold(MISSING_HOLD_ID, world.officer),
            api_errors.ERR_HOLD_NOT_FOUND,
            404,
        )
        validate_error(
            client.decide_amendment(
                MISSING_AMENDMENT_ID,
                factories.amendment_denial_payload("NOT_JUSTIFIED"),
                world.officer,
            ),
            api_errors.ERR_AMENDMENT_NOT_FOUND,
            404,
        )
        validate_error(
            client.get_report(MISSING_REPORT_ID, world.officer),
            api_errors.ERR_REPORT_NOT_FOUND,
            404,
        )
        validate_error(
            client.get_claim(MISSING_CLAIM_ID, world.officer),
            api_errors.ERR_CLAIM_NOT_FOUND,
            404,
        )
        validate_error(
            client.decide_petition(
                MISSING_PETITION_ID,
                factories.petition_decision_payload("DENY", "NO_MITIGATION"),
                world.fpf_officer,
            ),
            api_errors.ERR_PETITION_NOT_FOUND,
            404,
        )
        validate_error(
            client.get_ledger_entry(MISSING_LEDGER_ENTRY_ID, world.officer),
            api_errors.ERR_RESOURCE_NOT_FOUND,
            404,
        )


class TestUniqueness:
    """A registry refuses a second row under an identifier already on file."""

    def test_a_repeated_irs_number_and_a_repeated_port_code_both_conflict(self, client):
        """Re-registering the same IRS number under a new trading name, and the same
        port code under a new port name, are both conflicts that leave the original
        rows untouched.

        PRD: "The `irs_number` must be unique across all carriers; re-registering one already on file is refused with `ERR_DUPLICATE_IRS_NUMBER`."

        PRD: "Ports are registered by a `CBPOfficer` with a `port_code` of exactly four digits and unique across all ports — a duplicate is `ERR_DUPLICATE_PORT_CODE` — a `name`, a `region_code` drawn from `NE`, `MW`, `SE`, `PSW`, and `NW`, and an `exam_capacity_slots` count of zero or more concurrent scheduled examination windows the port can host."

        Design: Corner/errors/duplicate_irs_number_and_duplicate_port_code_conflict
        """
        world = build_carrier_without_bond(client, port_aliases=["ny"])

        validate_error(
            client.create_carrier(
                factories.carrier_payload(name="Atlas Bonded Carriage of Delaware"),
                world.officer,
            ),
            api_errors.ERR_DUPLICATE_IRS_NUMBER,
            409,
        )
        validate_error(
            client.create_port(
                factories.port_ny_payload(
                    name="New York Container Terminal", exam_capacity_slots=3
                ),
                world.officer,
            ),
            api_errors.ERR_DUPLICATE_PORT_CODE,
            409,
        )

        port = world.read_port("ny")
        assert_field(port, "name", "Port of New York", "port")
        assert_field(port, "exam_capacity_slots", 1, "port")
        assert_field(world.read_carrier(), "name", factories.CARRIER_NAME, "carrier")


class TestUnlistedStatusTransitions:
    """A transition that is not on the allowed list is refused even when the
    target status is the one the record already holds."""

    def test_setting_a_bond_and_a_carrier_to_the_status_they_already_hold_is_refused(
        self, client
    ):
        """ACTIVE to ACTIVE is on neither allowed edge list, so both PATCHes conflict
        and both records stay at version 1.

        PRD: "The only status edges a surety may drive are `ACTIVE → SUSPENDED`, `SATURATED → SUSPENDED`, and `SUSPENDED → ACTIVE`; requesting anything else — touching an `EXPIRED` bond, or setting `SATURATED` by hand — is `ERR_BOND_INVALID_STATE`."

        PRD: "An officer may drive the carrier by hand along exactly three edges — `ACTIVE → REVOKED`, `SUSPENDED → REVOKED`, and `SUSPENDED → ACTIVE` — by supplying the target `custodial_status` and an optional `reason_code`; any other requested transition, including anything out of `REVOKED`, is refused with `ERR_CARRIER_INVALID_STATE`."

        PRD: "Most resources additionally carry `updated_at`, refreshed on every mutation of the record, and `version`, an integer that starts at 1 on creation and increments by one on each mutation."

        Design: Corner/errors/unlisted_bond_and_carrier_status_transitions_rejected
        """
        world = build_registered_world(client)

        validate_error(
            client.patch_bond(
                world.bond_id, factories.bond_status_payload("ACTIVE"), world.surety
            ),
            api_errors.ERR_BOND_INVALID_STATE,
            409,
        )
        validate_error(
            client.patch_carrier(
                world.carrier_id,
                factories.carrier_status_payload("ACTIVE", "NO_OP"),
                world.officer,
            ),
            api_errors.ERR_CARRIER_INVALID_STATE,
            409,
        )

        bond = world.read_bond()
        assert_field(bond, "status", "ACTIVE", "bond")
        assert_field(bond, "version", 1, "bond")

        carrier = world.read_carrier()
        assert_field(carrier, "custodial_status", "ACTIVE", "carrier")
        assert_field(carrier, "version", 1, "carrier")
        assert_field(carrier, "suspension_reason", None, "carrier")


class TestDecisionsAreFinal:
    """A hold release and an amendment decision each happen once."""

    def test_neither_a_released_hold_nor_a_decided_amendment_can_be_acted_on_again(
        self, client
    ):
        """The second release of a RELEASED hold and the second decision on an
        APPROVED amendment are both refused, leaving the five granted days and the
        2026-09-10 deadline they produced intact.

        PRD: "Only an `OPEN` hold can be released; releasing one already `RELEASED` is `ERR_HOLD_INVALID_STATE`."

        PRD: "Only a request in `SUBMITTED` can be decided; a request already `APPROVED`, `DENIED`, or `SUPERSEDED` can never be decided again, and the refusal is `ERR_AMENDMENT_INVALID_STATE`."

        Design: Corner/errors/hold_release_and_amendment_decision_cannot_be_repeated
        """
        world = build_departed_movement(client)
        movement_id = world.movements["MAN-0001"]

        hold = world.place_unscheduled_hold(movement_id)
        world.release_hold(hold["id"])
        amendment = world.submit_extension(movement_id, 5, "WEATHER_DELAY")
        world.approve_amendment(amendment["id"], "WEATHER_VERIFIED", granted_days=5)

        validate_error(
            client.release_hold(
                hold["id"],
                factories.hold_release_payload("CLEAR"),
                world.second_officer,
            ),
            api_errors.ERR_HOLD_INVALID_STATE,
            409,
        )
        validate_error(
            client.decide_amendment(
                amendment["id"],
                factories.amendment_denial_payload("RECONSIDERED"),
                world.officer,
            ),
            api_errors.ERR_AMENDMENT_INVALID_STATE,
            409,
        )

        settled_hold = world.read_hold(hold["id"])
        assert_field(settled_hold, "status", "RELEASED", "hold")
        assert_field(settled_hold, "findings_code", "CLEAR", "hold")

        rows, _meta = world.amendments(movement_id)
        decided = rows[0]
        assert_field(decided, "status", "APPROVED", "amendment request")
        assert_field(decided, "granted_days", 5, "amendment request")
        assert_field(
            decided, "decision_reason_code", "WEATHER_VERIFIED", "amendment request"
        )

        movement = world.read_movement(movement_id)
        assert_deadline(
            movement,
            deadline="2026-09-10T00:00:00Z",
            transit_days_allowed=40,
            extension_days_granted=5,
        )
        assert_field(world.read_port("chicago"), "open_hold_count", 0, "port")


class TestClaimPayment:
    """Payment is all or nothing, and it happens once."""

    def test_a_partial_payment_is_refused_and_the_exact_one_cannot_be_repeated(
        self, client
    ):
        """500.00 against a 1,234.60 claim is a mismatch; the exact amount pays the
        claim off and nets its ledger entries to zero; a third attempt on the PAID
        claim conflicts.

        PRD: "`PAY` is the carrier's action and requires the claim to be `ISSUED` or `MITIGATED`; the `paid_amount` supplied must equal exactly what is currently owed — `mitigated_amount` when the claim is `MITIGATED`, otherwise `assessed_amount` — because partial payments are not accepted, and a mismatch is `ERR_PAYMENT_AMOUNT_MISMATCH`."

        PRD: "Payment records `paid_amount`, moves the claim to `PAID`, and appends a `RELEASE_LD` ledger entry with `reason_code` `CLAIM_PAID` whose `amount` is the negative of the amount that remained obligated — the full `assessed_amount` when the claim was `ISSUED`, or the `mitigated_amount` when it was `MITIGATED` and a `MITIGATE` entry had already released the difference — so that the claim's entries sum to exactly 0.00."

        PRD: "A paid violation still counts against the carrier: `sanction_points` is unchanged by payment."

        Design: Corner/errors/claim_payment_must_match_and_cannot_be_repeated
        """
        world, claim = build_late_arrival_claim(client)

        validate_error(
            client.dispose_claim(
                claim["id"], factories.claim_payment_payload(500.00), world.carrier
            ),
            api_errors.ERR_PAYMENT_AMOUNT_MISMATCH,
            422,
        )
        assert_field(world.read_claim(claim["id"]), "status", "ISSUED", "claim")

        paid = validate_success(
            client.dispose_claim(
                claim["id"],
                factories.claim_payment_payload(LATE_ARRIVAL_ASSESSED),
                world.carrier,
            ),
            200,
        )
        assert_field(paid, "status", "PAID", "claim")
        assert_money(paid["paid_amount"], LATE_ARRIVAL_ASSESSED, "paid_amount")
        assert_money(paid["assessed_amount"], LATE_ARRIVAL_ASSESSED, "assessed_amount")
        assert_field(paid, "mitigated_amount", None, "claim")

        assert_bond_amounts(
            world.read_bond(), obligated=M1_OBLIGATION, available=49958.25
        )
        assert_ledger_stream(
            world.ledger_entries(claim_id=claim["id"]),
            [
                {
                    "entry_type": "INCREASE_LD",
                    "amount": LATE_ARRIVAL_ASSESSED,
                    "balance_after": 1276.35,
                },
                {
                    "entry_type": "RELEASE_LD",
                    "amount": -LATE_ARRIVAL_ASSESSED,
                    "balance_after": M1_OBLIGATION,
                    "reason_code": "CLAIM_PAID",
                },
            ],
        )

        carrier = world.read_carrier()
        assert_points(carrier["sanction_points"], 2.0)
        assert_field(carrier, "open_claim_count", 0, "carrier")

        validate_error(
            client.dispose_claim(
                claim["id"],
                factories.claim_payment_payload(LATE_ARRIVAL_ASSESSED),
                world.carrier,
            ),
            api_errors.ERR_CLAIM_INVALID_STATE,
            409,
        )


class TestSealAndClockPreconditions:
    """No seal observation before the seal exists, and no clock that runs
    backwards."""

    def test_an_observation_before_departure_and_a_rewound_clock_are_both_refused(
        self, client
    ):
        """A VERIFIED_INTACT observation on a movement that has never departed is
        refused because no seal exists to verify, and rewinding the clock a day is
        refused outright.

        PRD: "Because only `APPLIED` may be recorded while `seal_number` is still null, any other seal event on a movement that has not yet departed is refused with `ERR_SEAL_NOT_APPLIED`; the same refusal applies to a movement report filed before any seal exists."

        PRD: "A test-driving capability sets the clock to a supplied `current_utc` instant; the clock never runs backwards, so a `current_utc` earlier than the clock's current value is rejected with `ERR_CLOCK_NOT_MONOTONIC` (HTTP 422), while a `current_utc` equal to the current value is accepted."

        Design: Corner/errors/seal_event_before_departure_and_a_backwards_clock_rejected
        """
        world = build_filed_movement(client)
        movement_id = world.movements["MAN-0001"]

        validate_error(
            client.record_seal_event(
                factories.seal_event_payload(
                    movement_id, "VERIFIED_INTACT", M1_SEAL, factories.PORT_NY_CODE
                ),
                world.carrier,
            ),
            api_errors.ERR_SEAL_NOT_APPLIED,
            409,
        )

        _rows, meta = validate_paginated(
            client.list_seal_events(movement_id, world.officer)
        )
        assert meta["total_count"] == 0, (
            f"the refused observation must not join the chain of custody but the "
            f"movement carries {meta['total_count']} seal events"
        )

        movement = world.read_movement(movement_id)
        assert_field(movement, "seal_number", None, "movement")
        assert_field(movement, "seal_intact", False, "movement")

        validate_error(
            client.set_clock("2026-07-31T00:00:00Z", world.officer),
            api_errors.ERR_CLOCK_NOT_MONOTONIC,
            422,
        )


class TestExtensionVolume:
    """Thirty days is the ceiling, and an officer can never grant more than was
    asked for."""

    def test_an_over_long_request_and_an_over_generous_grant_are_both_refused(
        self, client
    ):
        """31 days breaks the cumulative cap outright; on a 10-day request a 15-day
        approval is refused, while 4 days is granted and moves the deadline to
        2026-09-09.

        PRD: "Cumulative volume: the movement's existing `extension_days_granted` plus the `requested_days` on this submission must not exceed 30 total granted days, and exceeding it is `ERR_EXTENSION_LIMIT_EXCEEDED`."

        PRD: "For an **`EXTENSION`**: `granted_days` must be present and must be at least 1 and no more than `requested_days` — an officer may grant fewer days than were asked for but never more, and a violation is `ERR_GRANTED_DAYS_INVALID` — and the movement's `extension_days_granted` is increased by `granted_days`, which must keep the cumulative total at 30 or below or the approval fails with `ERR_EXTENSION_LIMIT_EXCEEDED`."

        PRD: "On an extension approval `deadline_anchor_utc` is **not** touched; it remains `filed_at`, and only `transit_deadline_utc` moves out."

        Design: Corner/errors/extension_days_are_capped_and_never_exceed_the_request
        """
        world = build_departed_movement(client)
        movement_id = world.movements["MAN-0001"]
        departed_version = world.read_movement(movement_id)["version"]

        validate_error(
            client.submit_amendment(
                factories.extension_payload(
                    movement_id, departed_version, 31, "WEATHER_DELAY"
                ),
                world.carrier,
            ),
            api_errors.ERR_EXTENSION_LIMIT_EXCEEDED,
            422,
        )
        _rows, meta = world.amendments(movement_id)
        assert meta["total_count"] == 0, (
            f"the refused request must not be recorded but the movement carries "
            f"{meta['total_count']} amendment requests"
        )

        amendment = validate_success(
            client.submit_amendment(
                factories.extension_payload(
                    movement_id, departed_version, 10, "WEATHER_DELAY"
                ),
                world.carrier,
            ),
            201,
        )
        assert_field(amendment, "status", "SUBMITTED", "amendment request")
        assert_field(amendment, "requested_days", 10, "amendment request")

        validate_error(
            client.decide_amendment(
                amendment["id"],
                factories.amendment_approval_payload("PARTIAL_RELIEF", 15),
                world.officer,
            ),
            api_errors.ERR_GRANTED_DAYS_INVALID,
            422,
        )
        assert_field(
            world.amendments(movement_id)[0][0],
            "status",
            "SUBMITTED",
            "amendment request",
        )

        approved = validate_success(
            client.decide_amendment(
                amendment["id"],
                factories.amendment_approval_payload("PARTIAL_RELIEF", 4),
                world.officer,
            ),
            200,
        )
        assert_field(approved, "status", "APPROVED", "amendment request")
        assert_field(approved, "granted_days", 4, "amendment request")
        assert_field(
            approved,
            "resulting_deadline_utc",
            "2026-09-09T00:00:00Z",
            "amendment request",
        )

        assert_deadline(
            world.read_movement(movement_id),
            anchor="2026-08-01T00:00:00Z",
            deadline="2026-09-09T00:00:00Z",
            transit_days_allowed=39,
            extension_days_granted=4,
        )
        _rows, meta = world.amendments(movement_id)
        assert meta["total_count"] == 1, (
            f"one request survives the exchange but the movement carries "
            f"{meta['total_count']}"
        )


class TestClosedWindowAndSystemOnlyHold:
    """The extension window shuts two days after the deadline, and one hold type
    belongs to the system alone."""

    def test_a_late_extension_and_a_hand_written_seal_hold_are_both_refused(
        self, client
    ):
        """At 2026-09-08 — a day past the deadline plus its two-day grace — the
        extension request is out of time, and a SEAL_DISCREPANCY hold placed by hand
        is refused whatever its timing.

        PRD: "Timing: an `EXTENSION` may be submitted only while the logical clock stands at or before the movement's `transit_deadline_utc` advanced by a two-day late grace, so the extension window closes two days after the deadline and a later request is `ERR_TRANSIT_DEADLINE_PASSED`."

        PRD: "`SEAL_DISCREPANCY` is never placed by a caller — it exists only as the system's automatic response to an unauthorized seal break — and requesting it directly is refused with `ERR_HOLD_TYPE_NOT_ALLOWED`."

        Design: Corner/errors/late_extension_window_and_system_only_hold_type_rejected
        """
        world = build_departed_movement(client)
        movement_id = world.movements["MAN-0001"]
        departed_version = world.read_movement(movement_id)["version"]
        world.set_clock("2026-09-08T00:00:00Z")

        validate_error(
            client.submit_amendment(
                factories.extension_payload(
                    movement_id, departed_version, 5, "WEATHER_DELAY"
                ),
                world.carrier,
            ),
            api_errors.ERR_TRANSIT_DEADLINE_PASSED,
            422,
        )
        _rows, amendment_meta = world.amendments(movement_id)
        assert amendment_meta["total_count"] == 0, (
            f"the out-of-time request must not be recorded but the movement carries "
            f"{amendment_meta['total_count']}"
        )
        assert_deadline(
            world.read_movement(movement_id),
            deadline=M1_DEADLINE,
            extension_days_granted=0,
        )

        validate_error(
            client.place_hold(
                factories.unscheduled_hold_payload(
                    movement_id,
                    world.ports["chicago"],
                    "SEAL_DISCREPANCY",
                    "OFFICER_SUSPICION",
                ),
                world.officer,
            ),
            api_errors.ERR_HOLD_TYPE_NOT_ALLOWED,
            422,
        )
        _rows, hold_meta = validate_paginated(
            client.list_holds(world.officer, params={"movement_id": movement_id})
        )
        assert hold_meta["total_count"] == 0, (
            f"the refused hold must not exist but the movement carries "
            f"{hold_meta['total_count']}"
        )
        assert_field(world.read_port("chicago"), "open_hold_count", 0, "port")
        assert_movement_state(
            world.read_movement(movement_id), custody_status="BONDED"
        )


class TestReportTypeAndWitness:
    """An IT movement cannot be exported, and a punctual arrival is no
    violation."""

    def test_an_export_report_on_an_it_movement_and_a_claim_without_a_witness_are_refused(
        self, client
    ):
        """The EXPORT report is refused because the movement is an IT, and the
        LATE_ARRIVAL claim is refused because the movement arrived on 2026-08-10, well
        inside its 2026-09-05 deadline.

        PRD: "An `EXPORT` report on an `IT` movement, or an `ARRIVAL` report on an `IE` movement, is refused with `ERR_REPORT_TYPE_NOT_ALLOWED`."

        PRD: "For `LATE_ARRIVAL`, the movement's `arrival_reported_at` must be non-null and must fall strictly after `transit_deadline_utc`."

        Design: Corner/errors/export_report_on_an_it_movement_and_a_claim_without_a_violation_rejected
        """
        world = build_departed_movement(client)
        movement_id = world.movements["MAN-0001"]
        world.set_clock("2026-08-05T00:00:00Z")

        validate_error(
            client.file_report(
                factories.export_report_payload(
                    movement_id,
                    world.ports["chicago"],
                    proof_of_export_ref="BOL-00001",
                ),
                world.carrier,
            ),
            api_errors.ERR_REPORT_TYPE_NOT_ALLOWED,
            422,
        )
        refused = world.read_movement(movement_id)
        assert_movement_state(refused, transit_status="IN_TRANSIT")
        assert_field(refused, "export_reported_at", None, "movement")

        world.set_clock("2026-08-10T00:00:00Z")
        report = validate_success(
            client.file_report(
                factories.arrival_report_payload(movement_id, world.ports["chicago"]),
                world.carrier,
            ),
            201,
        )
        assert_field(report, "status", "ACCEPTED", "report")
        assert_field(
            world.read_movement(movement_id),
            "arrival_reported_at",
            "2026-08-10T00:00:00Z",
            "movement",
        )

        validate_error(
            client.issue_claim(
                factories.claim_payload(movement_id, "LATE_ARRIVAL", "OVERDUE_ARRIVAL"),
                world.officer,
            ),
            api_errors.ERR_NO_VIOLATION_TO_CLAIM,
            422,
        )
        _rows, meta = world.claims(movement_id=movement_id)
        assert meta["total_count"] == 0, (
            f"a punctual arrival earns no claim but the movement carries "
            f"{meta['total_count']}"
        )
        assert_bond_amounts(world.read_bond(), obligated=M1_OBLIGATION)
        assert_points(world.read_carrier()["sanction_points"], 0.0)


class TestDuplicateClaimAndFactors:
    """One live claim per type per movement, and no factor counted twice."""

    def test_a_second_live_claim_and_a_repeated_mitigation_factor_are_both_refused(
        self, client
    ):
        """A second LATE_ARRIVAL claim on the same movement conflicts and writes no
        second obligation, and a petition naming FIRST_VIOLATION twice is refused
        rather than quietly de-duplicated.

        PRD: "Separately, a claim of the same `claim_type` must not already be live on the same movement — live meaning `status` in `ISSUED`, `PETITIONED`, or `MITIGATED` — and a duplicate is `ERR_DUPLICATE_CLAIM`."

        PRD: "An empty list, or a list containing the same code twice, is rejected with `ERR_MITIGATION_FACTOR_INVALID` rather than silently de-duplicated, so credit can never be double counted."

        Design: Corner/errors/duplicate_claim_and_duplicated_mitigation_factor_rejected
        """
        world, claim = build_late_arrival_claim(client)
        movement_id = world.movements["MAN-0001"]

        validate_error(
            client.issue_claim(
                factories.claim_payload(movement_id, "LATE_ARRIVAL", "OVERDUE_ARRIVAL"),
                world.officer,
            ),
            api_errors.ERR_DUPLICATE_CLAIM,
            409,
        )
        _rows, claim_meta = world.claims(movement_id=movement_id)
        assert claim_meta["total_count"] == 1, (
            f"the movement should carry a single claim but carries "
            f"{claim_meta['total_count']}"
        )
        assert_bond_amounts(world.read_bond(), obligated=1276.35)

        validate_error(
            client.file_petition(
                factories.petition_payload(
                    claim["id"],
                    claim["version"],
                    ["FIRST_VIOLATION", "FIRST_VIOLATION"],
                    "PET-0099",
                ),
                world.carrier,
            ),
            api_errors.ERR_MITIGATION_FACTOR_INVALID,
            422,
        )
        _rows, petition_meta = world.petitions(claim["id"])
        assert petition_meta["total_count"] == 0, (
            f"the refused petition must not exist but the claim carries "
            f"{petition_meta['total_count']}"
        )
        assert_field(world.read_claim(claim["id"]), "status", "ISSUED", "claim")
        assert_field(world.read_carrier(), "open_claim_count", 1, "carrier")


class TestNoEligibleBond:
    """An empty candidate set is an error, not an unbonded movement."""

    def test_a_filing_by_a_carrier_with_no_bond_at_all_is_refused(self, client):
        """The route is valid and the consignment is ordinary, but the carrier has no
        bond for the selector to choose, so the filing fails outright.

        PRD: "If no bond survives the filter, the filing fails with `ERR_NO_ELIGIBLE_BOND` rather than proceeding unbonded."

        Design: Corner/errors/filing_without_any_bond_returns_no_eligible_bond
        """
        world = build_carrier_without_bond(client)

        validate_error(
            client.file_movement(
                factories.movement_payload(
                    world.carrier_id,
                    world.ports["ny"],
                    world.ports["chicago"],
                    "MAN-0070",
                ),
                world.carrier,
            ),
            api_errors.ERR_NO_ELIGIBLE_BOND,
            422,
        )

        _rows, movement_meta = world.movement_list(carrier_id=world.carrier_id)
        assert movement_meta["total_count"] == 0, (
            f"the refused filing must not create a movement but the carrier has "
            f"{movement_meta['total_count']}"
        )
        _rows, ledger_meta = world.ledger_page()
        assert ledger_meta["total_count"] == 0, (
            f"an unbonded filing writes nothing to the ledger but it holds "
            f"{ledger_meta['total_count']} entries"
        )


class TestGeneralOrderBlocksRelease:
    """Merchandise in the general-order warehouse is beyond an ordinary
    release."""

    def test_cargo_in_general_order_cannot_be_released_and_stays_on_the_bond(
        self, client
    ):
        """Once the sweep has sent the arrived movement to GENERAL_ORDER, the release
        an officer could have granted the day before is refused and the 41.75 stays
        obligated.

        PRD: "Release requires that the movement's `transit_status` be `ARRIVED` or `EXPORTED`, that no examination hold on the movement remain `OPEN` — otherwise `ERR_HOLD_OPEN` — that `seal_intact` be true, and that `custody_status` not already be `GENERAL_ORDER`."

        PRD: "**Other records' state.** `ERR_CARRIER_NOT_ACTIVE`, `ERR_BOND_NOT_ACTIVE`, `ERR_PREDECESSOR_NOT_ARRIVED`, `ERR_MOVEMENT_IN_GENERAL_ORDER`."

        PRD: "Going to general order does **not** release the bond obligation: the merchandise remains under bond in the general-order warehouse."

        Design: Corner/errors/cargo_in_general_order_cannot_be_released
        """
        world = build_general_order_world(client)
        movement_id = world.movements["MAN-0001"]

        validate_error(
            client.release_cargo(
                movement_id, factories.cargo_release_payload(), world.officer
            ),
            api_errors.ERR_MOVEMENT_IN_GENERAL_ORDER,
            409,
        )

        movement = world.read_movement(movement_id)
        assert_movement_state(
            movement, transit_status="ARRIVED", custody_status="GENERAL_ORDER"
        )
        assert_bond_amounts(
            world.read_bond(), obligated=M1_OBLIGATION, open_movement_count=1
        )
        entries = world.ledger_entries(movement_id=movement_id)
        assert len(entries) == 1, (
            f"nothing has released the obligation, so the movement should carry its "
            f"single OBLIGATE entry but carries {len(entries)}"
        )


class TestPetitionRoundLimit:
    """The supplement cycle is capped at round two."""

    def test_a_petition_already_at_round_two_cannot_be_sent_back_again(self, client):
        """The officer asked once and the carrier answered, so the petition sits at
        round 2 SUBMITTED; a second request for more evidence is refused and nothing
        about the claim moves.

        PRD: "`REQUEST_SUPPLEMENT` moves the petition `SUBMITTED → SUPPLEMENT_REQUESTED` and leaves the claim at `PETITIONED`. It is permitted only while the petition's `round` is still below 2; once round 2 has been reached, the request is refused with `ERR_PETITION_ROUND_LIMIT`."

        PRD: "An accepted supplement increases `round` by one, replaces `mitigation_factors` and `narrative_reference` with the supplied values, moves the petition `SUPPLEMENT_REQUESTED → SUBMITTED`, and recomputes `mitigation_pct`, `net_before_fee`, `processing_fee`, and `offer_amount` under the round-2 cap of seventy-five hundredths."

        Design: Corner/errors/supplemented_petition_cannot_be_sent_back_a_second_time
        """
        world, claim, petition = build_supplement_requested_petition(
            client, "PET-0100", "MORE_EVIDENCE"
        )
        supplemented = world.supplement_petition(
            petition["id"], factories.FOUR_FACTOR_MITIGATION, "PET-0100-B"
        )
        assert_field(supplemented, "round", 2, "petition")

        validate_error(
            client.decide_petition(
                petition["id"],
                factories.petition_decision_payload(
                    "REQUEST_SUPPLEMENT", "STILL_MORE_EVIDENCE"
                ),
                world.fpf_officer,
            ),
            api_errors.ERR_PETITION_ROUND_LIMIT,
            422,
        )

        rows, _meta = world.petitions(claim["id"])
        settled = rows[0]
        assert_field(settled, "round", 2, "petition")
        assert_field(settled, "status", "SUBMITTED", "petition")
        assert_field(settled, "narrative_reference", "PET-0100-B", "petition")

        petitioned = world.read_claim(claim["id"])
        assert_field(petitioned, "status", "PETITIONED", "claim")
        assert_field(petitioned, "mitigated_amount", None, "claim")
        assert_bond_amounts(world.read_bond(), obligated=1276.35)
