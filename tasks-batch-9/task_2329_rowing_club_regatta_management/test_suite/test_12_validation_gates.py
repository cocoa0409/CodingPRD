"""Refusals that fire on well-formed input: lineup shape and crew credentials,
clearance certificates and closed water, the hull-condition floor at submission,
the four fiscal guards on an invoice, and the active-membership gate.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    CLUB_ADMIN_HEADERS,
    api_client,
    assert_dues_invoice,
    assert_member,
    assert_regatta_entry,
    assert_shell,
    assert_water_condition_reading,
    validate_error,
    validate_paginated,
)
from test_helpers.factories import lineup_payload, seat
from test_helpers.fixtures import (
    add_shell,
    add_single,
    book_session,
    declare_lineup,
    enrol_athlete,
    enrol_coach,
    enrol_launch_driver,
    file_damage,
    issue_invoice,
    make_partially_paid_invoice,
    move_member_to,
    open_entry,
    open_regatta,
    pay_invoice,
    post_reading,
    read_entry,
    read_invoice,
    read_member,
    read_session,
    read_shell,
    submit_entry,
    true_up_invoice,
)

RECREATIONAL_SEASON_ASSESSMENT_CENTS = 74000
TRUEUP_ASSESSMENT_CENTS = 29600


def seats_count_of(entry_id, headers):
    _rows, meta = validate_paginated(
        api_client.list_lineup_seats(headers, {"regatta_entry_id": entry_id})
    )
    return meta["total_count"]


@pytest.fixture
def draft_coxed_four(cast):
    """A DRAFT 4+ entry and the four rowers a short lineup would seat."""
    regatta = open_regatta(name="Club Head Race", host_club="Home RC")
    shell = add_shell(
        hull_name="Cormorant", boat_class="4+", hull_weight_kg=51.0, home_bay="BAY-4"
    )
    rowers = [
        enrol_athlete(f"Row {index}", "COMPETITIVE", 81.0 + index) for index in range(1, 5)
    ]
    entry = open_entry(
        regatta["id"],
        shell["id"],
        cast["coach_headers"],
        event_code="M4PLUS_OPEN",
        boat_class="4+",
        seed_time_seconds=400.0,
    )
    return {"entry": entry, "rowers": rowers}


@pytest.fixture
def draft_double(cast):
    """A DRAFT 2X entry and the single rower a duplicated lineup would seat twice."""
    regatta = open_regatta(name="Club Head Race", host_club="Home RC")
    shell = add_shell(hull_name="Grebe", boat_class="2X", hull_weight_kg=27.0, home_bay="BAY-2")
    rower = enrol_athlete("Row One", "COMPETITIVE", 82.0)
    entry = open_entry(
        regatta["id"],
        shell["id"],
        cast["coach_headers"],
        event_code="M2X_OPEN",
        boat_class="2X",
        seed_time_seconds=400.0,
    )
    return {"entry": entry, "rower": rower}


@pytest.fixture
def recreational_season_invoice():
    """One RECREATIONAL member billed the full season with no locker."""
    member = enrol_athlete("Rita Rower", "RECREATIONAL", 70.0)
    invoice = issue_invoice(member["id"])
    return {"member": member, "invoice": invoice}


class TestLineupShape:
    def test_a_coxed_four_declared_without_its_coxswain_is_refused(self, cast, draft_coxed_four):
        """Four rowers is a well-formed payload but the wrong seat count.

        PRD: "The declared seats must fill exactly the seat count implied by the
        entry's `boat_class`: one seat for a `1X`, two for a `2X`, five for a `4+`
        including the coxswain, and nine for an `8+` including the coxswain, with
        `seat_number` 0 carrying the single `COXSWAIN` seat in the `4+` and `8+`
        classes."

        Design: Corner/validations/corner_lineup_four_seats_for_coxed_four_returns_422_seat_count
        """
        entry = draft_coxed_four["entry"]
        seats = [
            seat(rower["id"], index, "ROWER")
            for index, rower in enumerate(draft_coxed_four["rowers"], start=1)
        ]
        response = api_client.declare_lineup(
            entry["id"], lineup_payload(entry["version"], seats), cast["coach_headers"]
        )
        validate_error(response, ApiErrorId.ERR_SEAT_COUNT_MISMATCH.value)

        stored = assert_regatta_entry(read_entry(entry["id"]))
        assert stored["status"] == "DRAFT", (
            f"the refused declaration leaves the entry in DRAFT, got {stored['status']}"
        )
        assert stored["version"] == entry["version"], (
            "a rejected declaration consumes no version, expected "
            f"{entry['version']}, got {stored['version']}"
        )
        assert seats_count_of(entry["id"], cast["coach_headers"]) == 0, (
            "no seat rows were created for the refused lineup"
        )

    def test_the_same_rower_may_not_hold_two_seats_of_one_declaration(self, cast, draft_double):
        """The count is right, so the refusal must come from the duplicate.

        PRD: "A wrong count is `ERR_SEAT_COUNT_MISMATCH` (HTTP 422), and the same
        `member_id` appearing in two seats of one declaration is
        `ERR_DUPLICATE_SEAT_MEMBER`."

        Design: Corner/validations/corner_lineup_same_member_twice_returns_409_duplicate_seat
        """
        entry = draft_double["entry"]
        member_id = draft_double["rower"]["id"]
        seats = [seat(member_id, 1, "ROWER"), seat(member_id, 2, "ROWER")]
        response = api_client.declare_lineup(
            entry["id"], lineup_payload(entry["version"], seats), cast["coach_headers"]
        )
        validate_error(response, ApiErrorId.ERR_DUPLICATE_SEAT_MEMBER.value)

        stored = read_entry(entry["id"])
        assert stored["status"] == "DRAFT", (
            f"the entry is untouched at DRAFT, got {stored['status']}"
        )
        assert stored["version"] == entry["version"], (
            f"the version is unchanged at {entry['version']}, got {stored['version']}"
        )
        assert seats_count_of(entry["id"], cast["coach_headers"]) == 0, (
            "no partial lineup was persisted"
        )

    def test_an_entry_must_be_opened_in_the_hulls_own_class(self, cast):
        """Both the class and the hull are legal; it is their disagreement that fails.

        PRD: "and the declared `boat_class` must equal the `boat_class` of the
        named hull, or it fails with `ERR_BOAT_CLASS_MISMATCH`."

        Design: Corner/validations/corner_entry_boat_class_mismatch_returns_409
        """
        regatta = open_regatta(name="Club Head Race", host_club="Home RC")
        shell = add_single(hull_name="Kingfisher")
        response = api_client.create_regatta_entry(
            {
                "regatta_id": regatta["id"],
                "shell_id": shell["id"],
                "event_code": "M2X_OPEN",
                "boat_class": "2X",
                "seed_time_seconds": 400.0,
            },
            cast["coach_headers"],
        )
        validate_error(response, ApiErrorId.ERR_BOAT_CLASS_MISMATCH.value)

        _rows, meta = validate_paginated(
            api_client.list_regatta_entries(
                cast["coach_headers"], {"regatta_id": regatta["id"]}
            )
        )
        assert meta["total_count"] == 0, (
            f"the refused entry was never created, got {meta['total_count']} rows"
        )


class TestCrewCredentialsAtDeclaration:
    def test_a_competitive_only_hull_refuses_a_recreational_rower(self, cast):
        """The seat count and swim test are both fine; the tier is not.

        PRD: "and when the hull carries `tier_restriction` `COMPETITIVE_ONLY`,
        every seated member must be `COMPETITIVE`
        (`ERR_TIER_NOT_PERMITTED_FOR_HULL`)."

        Design: Corner/validations/corner_competitive_only_hull_rejects_recreational_seat
        """
        regatta = open_regatta(name="Club Head Race", host_club="Home RC")
        shell = add_single(
            hull_name="Peregrine",
            hull_weight_kg=13.5,
            home_bay="BAY-5",
            tier_restriction="COMPETITIVE_ONLY",
        )
        rita = enrol_athlete("Rita Rower", "RECREATIONAL", 70.0)
        entry = open_entry(
            regatta["id"],
            shell["id"],
            cast["coach_headers"],
            event_code="W1X_OPEN",
            seed_time_seconds=420.0,
        )
        response = api_client.declare_lineup(
            entry["id"],
            lineup_payload(entry["version"], [seat(rita["id"], 1, "ROWER")]),
            cast["coach_headers"],
        )
        validate_error(response, ApiErrorId.ERR_TIER_NOT_PERMITTED_FOR_HULL.value)

        hull = assert_shell(read_shell(shell["id"]))
        assert hull["tier_restriction"] == "COMPETITIVE_ONLY", (
            f"the restriction is stored as declared, got {hull['tier_restriction']}"
        )
        assert hull["status"] == "AVAILABLE", (
            f"the refusal does not reserve the hull, got {hull['status']}"
        )
        assert read_entry(entry["id"])["status"] == "DRAFT", (
            "the entry stays in DRAFT"
        )

    def test_a_swim_test_older_than_a_year_blocks_the_seat(self, cast):
        """The field is populated — it is its age against the clock that fails.

        PRD: "Every member in `athlete_member_ids`, plus the `coxswain_member_id`
        when one is named, must have a non-null `swim_test_passed_on` no more than
        365 days before the logical clock; a missing or stale swim test yields
        `ERR_SWIM_TEST_MISSING`."

        Design: Corner/validations/corner_lineup_with_stale_swim_test_returns_409
        """
        regatta = open_regatta(name="Club Head Race", host_club="Home RC")
        shell = add_single(hull_name="Kingfisher")
        lapsed = enrol_athlete(
            "Lapsed Rower", "COMPETITIVE", 82.0, swim_test_passed_on="2025-07-01T00:00:00Z"
        )
        assert lapsed["swim_test_passed_on"] is not None, (
            "the stale swim test is recorded, not absent"
        )
        entry = open_entry(regatta["id"], shell["id"], cast["coach_headers"])
        response = api_client.declare_lineup(
            entry["id"],
            lineup_payload(entry["version"], [seat(lapsed["id"], 1, "ROWER")]),
            cast["coach_headers"],
        )
        validate_error(response, ApiErrorId.ERR_SWIM_TEST_MISSING.value)

        assert read_entry(entry["id"])["status"] == "DRAFT", (
            "the entry is left in DRAFT by the refusal"
        )


class TestClearanceGates:
    def test_a_lapsed_coaching_certificate_blocks_clearance(self, cast, single_shell):
        """Open water and a current swim test are not enough on their own.

        PRD: "When `coach_member_id` is not null, that member must have a non-null
        `coach_cert_expires_at` strictly after the logical clock —
        `ERR_COACH_CERT_EXPIRED`."

        Design: Corner/validations/corner_clearance_with_expired_coach_cert_returns_409
        """
        lapsed_coach = enrol_coach(
            "Expired Coach", coach_cert_expires_at="2026-07-01T00:00:00Z"
        )
        rita = enrol_athlete("Rita Rower", "RECREATIONAL", 70.0)
        reading = post_reading(
            cast["officer_headers"],
            air_temp_c=22.0,
            water_temp_c=19.0,
            wind_speed_kt=5.0,
            visibility_m=3000,
        )
        booked = book_session(
            single_shell["id"],
            cast["officer_headers"],
            coach_member_id=lapsed_coach["id"],
            athlete_member_ids=[rita["id"]],
        )

        response = api_client.clear_water_session(
            booked["id"], {"reading_id": reading["id"]}, cast["officer_headers"]
        )
        validate_error(response, ApiErrorId.ERR_COACH_CERT_EXPIRED.value)

        stored = read_session(booked["id"])
        assert stored["status"] == "PLANNED", (
            f"the outing stays PLANNED, got {stored['status']}"
        )
        assert stored["reading_id"] is None, (
            f"no reading is recorded against a refused clearance, got {stored['reading_id']}"
        )
        assert read_shell(single_shell["id"])["status"] == "AVAILABLE", (
            "the hull is not reserved by a refused clearance"
        )

    def test_clearing_against_closed_water_is_refused(self, cast, single_shell):
        """A closing wind stops the clearance before any credential is read.

        PRD: "Clearance requires the hull to be `AVAILABLE`
        (`ERR_SHELL_NOT_AVAILABLE`) and the named reading's `posture` to be `OPEN`
        or `RESTRICTED` — a `CLOSED` river yields `ERR_WATER_CLOSED`."

        Design: Corner/validations/corner_clearance_against_closed_water_returns_409
        """
        rita = enrol_athlete("Rita Rower", "RECREATIONAL", 70.0)
        booked = book_session(
            single_shell["id"],
            cast["coach_headers"],
            coach_member_id=cast["coach"]["id"],
            athlete_member_ids=[rita["id"]],
        )
        reading = assert_water_condition_reading(
            post_reading(
                cast["officer_headers"],
                air_temp_c=22.0,
                water_temp_c=19.0,
                wind_speed_kt=25.0,
                visibility_m=3000,
            )
        )
        assert reading["posture"] == "CLOSED", (
            f"a sustained 25.0 knots closes the river, got {reading['posture']}"
        )

        response = api_client.clear_water_session(
            booked["id"], {"reading_id": reading["id"]}, cast["officer_headers"]
        )
        validate_error(response, ApiErrorId.ERR_WATER_CLOSED.value)

        stored = read_session(booked["id"])
        assert stored["status"] == "PLANNED", (
            "a merely planned outing is neither reverted nor cancelled by the closing "
            f"reading, got {stored['status']}"
        )
        assert stored["reading_id"] is None, (
            f"no reading is recorded, got {stored['reading_id']}"
        )
        assert stored["required_launch_count"] == 0, (
            "the launch requirement is untouched at 0, got "
            f"{stored['required_launch_count']}"
        )

    def test_a_lapsed_launch_certificate_blocks_clearance(self, cast, single_shell):
        """The one launch the outing needs was supplied, but its driver is uncertified.

        PRD: "Every non-null launch driver must have a non-null
        `safety_launch_cert_expires_at` strictly after the logical clock *and*
        carry `LAUNCH_DRIVER` in their `club_roles`; a failure on either count is
        `ERR_LAUNCH_CERT_EXPIRED`."

        Design: Corner/validations/corner_clearance_with_expired_launch_cert_returns_409
        """
        lapsed_driver = enrol_launch_driver(
            "Lapsed Driver", 2, safety_launch_cert_expires_at="2026-07-01T00:00:00Z"
        )
        novice = enrol_athlete("Novice Rower", "LEARN_TO_ROW", 66.0)
        reading = post_reading(
            cast["officer_headers"],
            air_temp_c=22.0,
            water_temp_c=19.0,
            wind_speed_kt=5.0,
            visibility_m=3000,
        )
        booked = book_session(
            single_shell["id"],
            cast["coach_headers"],
            session_kind="LEARN_TO_ROW",
            coach_member_id=cast["coach"]["id"],
            athlete_member_ids=[novice["id"]],
            primary_launch_driver_member_id=lapsed_driver["id"],
        )
        assert booked["assigned_launch_count"] == 1, (
            "one driver is named on the booking, got "
            f"{booked['assigned_launch_count']}"
        )

        response = api_client.clear_water_session(
            booked["id"], {"reading_id": reading["id"]}, cast["officer_headers"]
        )
        validate_error(response, ApiErrorId.ERR_LAUNCH_CERT_EXPIRED.value)

        stored = read_session(booked["id"])
        assert stored["status"] == "PLANNED", (
            f"the outing stays PLANNED, got {stored['status']}"
        )
        assert stored["required_launch_count"] == 0, (
            "the requirement is only recomputed on a successful clearance, got "
            f"{stored['required_launch_count']}"
        )
        assert read_shell(single_shell["id"])["status"] == "AVAILABLE", (
            "the hull remains available"
        )


class TestHullConditionFloorAtSubmission:
    def test_a_hull_at_twenty_may_not_be_raced(self, cast):
        """Two structural deductions put the hull well under the floor.

        PRD: "the hull's `condition_index_conservative` must be at least 60
        (`ERR_SHELL_CONDITION_TOO_LOW`), and every seat on the entry must be
        `ELIGIBLE`"

        Design: Corner/validations/corner_submit_with_condition_index_below_sixty_returns_409
        """
        regatta = open_regatta(name="Club Head Race", host_club="Home RC")
        shell = add_single(hull_name="Kingfisher")
        rower = enrol_athlete("Row One", "COMPETITIVE", 82.0)
        entry = open_entry(regatta["id"], shell["id"], cast["coach_headers"])
        entry = declare_lineup(
            entry, [seat(rower["id"], 1, "ROWER")], cast["coach_headers"]
        )
        for narrative in ("keel split", "second split at the bow ball"):
            file_damage(
                shell["id"],
                cast["coach"]["id"],
                cast["coach_headers"],
                severity="STRUCTURAL",
                narrative=narrative,
            )

        hull = assert_shell(read_shell(shell["id"]))
        assert hull["condition_index_conservative"] == 20, (
            "two undecayed structural deductions of 40 points leave 20, got "
            f"{hull['condition_index_conservative']}"
        )
        assert hull["status"] == "DAMAGED", (
            f"a structural report takes the hull out of service, got {hull['status']}"
        )

        response = api_client.submit_regatta_entry(entry["id"], {}, cast["coach_headers"])
        validate_error(response, ApiErrorId.ERR_SHELL_CONDITION_TOO_LOW.value)

        stored = read_entry(entry["id"])
        assert stored["status"] == "LINEUP_DECLARED", (
            f"the refused entry stays LINEUP_DECLARED, got {stored['status']}"
        )
        assert stored["total_fee_cents"] == 0, (
            f"no fee was assessed, got {stored['total_fee_cents']}"
        )
        assert stored["submitted_at"] is None, (
            f"nothing was stamped from the clock, got {stored['submitted_at']}"
        )

    def test_a_hull_at_exactly_sixty_may_still_be_raced(self, cast):
        """The floor is inclusive, so one structural deduction is survivable.

        PRD: "Submission stamps `submitted_at` from the logical clock, assesses
        the fee, moves every `COXSWAIN` seat's `weigh_in_status` from
        `NOT_REQUIRED` to `PENDING`, recomputes the regatta's `net_fee_cents`, and
        moves the entry `LINEUP_DECLARED → SUBMITTED`."

        Design: Corner/validations/corner_submit_with_condition_index_exactly_sixty_succeeds
        """
        regatta = open_regatta(name="Club Head Race", host_club="Home RC")
        shell = add_single(hull_name="Kingfisher")
        rower = enrol_athlete("Row One", "COMPETITIVE", 82.0)
        entry = open_entry(regatta["id"], shell["id"], cast["coach_headers"])
        entry = declare_lineup(
            entry, [seat(rower["id"], 1, "ROWER")], cast["coach_headers"]
        )
        file_damage(
            shell["id"],
            cast["coach"]["id"],
            cast["coach_headers"],
            severity="STRUCTURAL",
            narrative="keel split",
        )
        hull = read_shell(shell["id"])
        assert hull["condition_index_conservative"] == 60, (
            "a single undecayed structural deduction of 40 points leaves exactly 60, "
            f"got {hull['condition_index_conservative']}"
        )

        submitted = assert_regatta_entry(submit_entry(entry["id"], cast["coach_headers"]))
        assert submitted["status"] == "SUBMITTED", (
            f"an index of exactly 60 clears the floor, got {submitted['status']}"
        )
        assert submitted["total_fee_cents"] == 4500, (
            f"the 1X class fee is assessed, got {submitted['total_fee_cents']}"
        )


class TestInvoiceFiscalGuards:
    def test_a_payment_one_cent_over_the_balance_is_refused(self, recreational_season_invoice):
        """Overpayment is refused outright rather than clamped to the balance.

        PRD: "The payment must not exceed the invoice's remaining balance — that
        is, `amount_cents` must be no greater than `assessed_cents` less
        `paid_cents` — or the request is rejected with
        `ERR_PAYMENT_EXCEEDS_BALANCE`."

        Design: Corner/validations/corner_payment_above_outstanding_balance_returns_422
        """
        scenario = recreational_season_invoice
        invoice = assert_dues_invoice(scenario["invoice"])
        assert invoice["assessed_cents"] == RECREATIONAL_SEASON_ASSESSMENT_CENTS, (
            "a full-season RECREATIONAL member owes 61500 + 12500 with no locker, "
            f"got {invoice['assessed_cents']}"
        )

        response = api_client.pay_dues_invoice(
            invoice["id"],
            {"amount_cents": RECREATIONAL_SEASON_ASSESSMENT_CENTS + 1},
            CLUB_ADMIN_HEADERS,
        )
        validate_error(response, ApiErrorId.ERR_PAYMENT_EXCEEDS_BALANCE.value)

        stored = read_invoice(invoice["id"])
        assert stored["paid_cents"] == 0, (
            f"nothing was applied, got {stored['paid_cents']}"
        )
        assert stored["status"] == "ISSUED", (
            f"the invoice stays ISSUED, got {stored['status']}"
        )
        member = assert_member(read_member(scenario["member"]["id"]))
        assert member["dues_balance_cents"] == RECREATIONAL_SEASON_ASSESSMENT_CENTS, (
            f"the whole assessment is still outstanding, got {member['dues_balance_cents']}"
        )

    def test_an_invoice_carrying_a_payment_may_not_be_voided(self, recreational_season_invoice):
        """Voiding is only available while nothing has been collected.

        PRD: "A `ClubAdmin` may void an `ISSUED` invoice with a stated `reason`,
        but only while `paid_cents` is exactly 0; otherwise the request fails with
        `ERR_INVOICE_HAS_PAYMENTS`."

        Design: Corner/validations/corner_void_invoice_with_payments_returns_409
        """
        scenario = recreational_season_invoice
        pay_invoice(scenario["invoice"]["id"], 1000)

        response = api_client.void_dues_invoice(
            scenario["invoice"]["id"], {"reason": "billed in error"}, CLUB_ADMIN_HEADERS
        )
        validate_error(response, ApiErrorId.ERR_INVOICE_HAS_PAYMENTS.value)

        stored = assert_dues_invoice(read_invoice(scenario["invoice"]["id"]))
        assert stored["status"] == "PARTIALLY_PAID", (
            f"the part-paid invoice keeps its status, got {stored['status']}"
        )
        assert stored["paid_cents"] == 1000, (
            f"the collected payment stands, got {stored['paid_cents']}"
        )
        member = read_member(scenario["member"]["id"])
        assert member["dues_balance_cents"] == 73000, (
            f"74000 less the 1000 collected is 73000, got {member['dues_balance_cents']}"
        )

    def test_a_second_payment_on_a_settled_invoice_reports_not_payable(
        self, recreational_season_invoice
    ):
        """The payment endpoint is the declared carve-out from the terminal rule.

        PRD: "The invoice must also still be payable: its `status` must be
        `ISSUED`, `PARTIALLY_PAID` or `DELINQUENT`, and a payment against a `PAID`
        or `VOIDED` invoice reports `ERR_INVOICE_NOT_PAYABLE` rather than the
        generic terminal-state error, per the carve-out in §2.9."

        Design: Corner/validations/corner_payment_on_paid_invoice_returns_not_payable_not_already_terminal
        """
        scenario = recreational_season_invoice
        settled = pay_invoice(
            scenario["invoice"]["id"], RECREATIONAL_SEASON_ASSESSMENT_CENTS
        )
        assert settled["status"] == "PAID", (
            f"the full payment settles the invoice, got {settled['status']}"
        )
        assert settled["paid_cents"] == RECREATIONAL_SEASON_ASSESSMENT_CENTS, (
            f"the whole assessment was collected, got {settled['paid_cents']}"
        )

        response = api_client.pay_dues_invoice(
            scenario["invoice"]["id"], {"amount_cents": 1}, CLUB_ADMIN_HEADERS
        )
        error = validate_error(response, ApiErrorId.ERR_INVOICE_NOT_PAYABLE.value)
        assert error["error_id"] != ApiErrorId.ERR_ALREADY_TERMINAL.value, (
            "the carve-out reports the payability code, not the generic terminal code"
        )

        stored = read_invoice(scenario["invoice"]["id"])
        assert stored["paid_cents"] == RECREATIONAL_SEASON_ASSESSMENT_CENTS, (
            f"the refused cent was not collected, got {stored['paid_cents']}"
        )
        member = read_member(scenario["member"]["id"])
        assert member["dues_balance_cents"] == 0, (
            f"the member owes nothing, got {member['dues_balance_cents']}"
        )
        assert member["boathouse_access_level"] == "FULL", (
            f"a settled member has full access, got {member['boathouse_access_level']}"
        )

    def test_the_true_up_may_only_be_applied_once(self):
        """The variant switch is one-way and the second attempt changes nothing.

        PRD: "A true-up against an invoice whose `variant_basis` is already
        `TRUEUP` is rejected with `ERR_TRUEUP_ALREADY_APPLIED`, and a true-up
        against a `PAID` or `VOIDED` invoice reports `ERR_INVOICE_NOT_PAYABLE`."

        Design: Corner/validations/corner_second_true_up_returns_409_already_applied
        """
        member = enrol_athlete("Rita Rower", "RECREATIONAL", 70.0)
        invoice = make_partially_paid_invoice(member["id"], 1000)
        rebilled = assert_dues_invoice(true_up_invoice(invoice["id"], note="reconciliation"))
        assert rebilled["variant_basis"] == "TRUEUP", (
            f"the first call switches the variant, got {rebilled['variant_basis']}"
        )
        assert rebilled["assessed_cents"] == TRUEUP_ASSESSMENT_CENTS, (
            "with no logged sessions the floor of 24600 plus the 5000 admin fee is "
            f"29600, got {rebilled['assessed_cents']}"
        )
        assert rebilled["trueup_cents"] == TRUEUP_ASSESSMENT_CENTS - 74000, (
            f"the signed delta is a credit of 44400, got {rebilled['trueup_cents']}"
        )

        response = api_client.true_up_dues_invoice(
            invoice["id"], {"note": "second attempt"}, CLUB_ADMIN_HEADERS
        )
        validate_error(response, ApiErrorId.ERR_TRUEUP_ALREADY_APPLIED.value)

        stored = read_invoice(invoice["id"])
        assert stored["variant_basis"] == "TRUEUP", (
            f"the variant is unchanged, got {stored['variant_basis']}"
        )
        assert stored["assessed_cents"] == TRUEUP_ASSESSMENT_CENTS, (
            f"the rebilled assessment stands from the first call only, got {stored['assessed_cents']}"
        )
        assert stored["trueup_cents"] == TRUEUP_ASSESSMENT_CENTS - 74000, (
            f"the delta was not recomputed, got {stored['trueup_cents']}"
        )
        assert stored["paid_cents"] == 1000, (
            f"the part payment is untouched, got {stored['paid_cents']}"
        )


class TestActiveMembershipGate:
    def test_a_withdrawn_member_may_not_be_seated_in_an_outing(self, cast, single_shell):
        """Booking checks every member it references, not just the coach.

        PRD: "Every member the booking references must have `membership_status`
        `ACTIVE`, or the booking fails with `ERR_MEMBER_NOT_ACTIVE`."

        Design: Corner/validations/corner_withdrawn_member_cannot_be_seated_or_coached
        """
        gone = enrol_athlete("Gone Rower", "RECREATIONAL", 70.0)
        withdrawn = assert_member(move_member_to(gone["id"], "WITHDRAWN"))
        assert withdrawn["membership_status"] == "WITHDRAWN", (
            f"the member has left the club, got {withdrawn['membership_status']}"
        )

        response = api_client.create_water_session(
            {
                "shell_id": single_shell["id"],
                "session_kind": "PRACTICE",
                "planned_start_at": "2026-08-01T06:00:00Z",
                "planned_end_at": "2026-08-01T07:00:00Z",
                "coach_member_id": cast["coach"]["id"],
                "athlete_member_ids": [gone["id"]],
            },
            cast["coach_headers"],
        )
        validate_error(response, ApiErrorId.ERR_MEMBER_NOT_ACTIVE.value)

        _rows, meta = validate_paginated(
            api_client.list_water_sessions(
                cast["coach_headers"], {"shell_id": single_shell["id"]}
            )
        )
        assert meta["total_count"] == 0, (
            f"no outing was booked, got {meta['total_count']} rows"
        )
        assert read_shell(single_shell["id"])["status"] == "AVAILABLE", (
            "the hull is untouched by the refused booking"
        )
