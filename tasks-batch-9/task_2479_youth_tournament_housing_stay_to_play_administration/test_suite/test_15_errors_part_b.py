"""Refusals that must name one exact error identifier, part two.

Manifest occupancy and supersede targets, rebate-parameter and billing-period
rules, exemption eligibility, and the two ways an adjudication or a filing can be
structurally incomplete. Each test breaks one rule and reads the target back to
show nothing moved.
"""

from test_helpers import (
    HOUSING_MANAGER_HEADERS,
    RIGHTS_HOLDER_HEADERS,
    ApiErrorId,
    ComplaintOutcome,
    ComplaintRoute,
    ExceptionReasonCode,
    InvoiceLifecycleAction,
    RemedyType,
    factories as f,
    fixtures as fx,
    validate_error,
    validate_success,
)

HM = HOUSING_MANAGER_HEADERS


def _four_rooms_for_a_thirteen_person_roster_env(api) -> fx.Env:
    """An eleven-player, two-staff roster — four rooms segregated, four pooled —
    holding a four-room `DRAFT` booking."""
    env = fx.executed_contract_env(api)
    fx.add_team(env)
    fx.add_registration(env, roster_player_count=11, roster_staff_count=2)
    fx.add_booking(env, rooms_requested=4)
    return env


def _cancelled_booking_env(api) -> fx.Env:
    """A four-room booking cancelled while still at `DRAFT`, leaving its
    registration free to book again."""
    env = fx.draft_booking_env(api)
    env.booking = validate_success(
        api.cancel_booking(env.booking_id, f.cancel_payload(), HM)
    )
    return env


def _fully_offset_invoice_env(api) -> fx.Env:
    """A draft invoice on a contract whose attrition threshold is the whole block,
    so the penalty swallows the entire rebate."""
    return fx.invoiced_env(api, contract_overrides={"attrition_threshold_pct": 1.0})


def _investigating_complaint_on_a_booking_env(api) -> fx.Env:
    """A complaint naming an affected booking, routed onto the investigate
    branch and awaiting adjudication."""
    env = fx.draft_booking_env(api)
    fx.add_complaint(env, affected_booking_id=env.booking_id)
    fx.triage_complaint(env, ComplaintRoute.INVESTIGATE.value)
    return env


class TestRoomingListAndSupersedeRules:
    """Occupancy totals and the booking a new booking claims to replace."""

    def test_the_manifest_cannot_seat_more_people_than_the_roster_holds(self, api):
        """Four rooms of four adults seats sixteen, but the roster is thirteen
        people, so the manifest is refused and the booking stays at draft.

        PRD §3.4: "Finally the total occupancy is bounded: the sum of
        `occupant_count` across the submitted entries must be at least 1 and no more
        than the registration's `roster_player_count` plus `roster_staff_count`, or
        `ERR_ROOMING_LIST_OCCUPANT_MISMATCH`."

        Design: Corner/errors/rooming_list_occupant_total_above_roster_rejected
        """
        env = _four_rooms_for_a_thirteen_person_roster_env(api)
        registration = env.refresh_registration()
        assert registration["required_rooms_registered"] == 4
        assert registration["minimum_rooms_for_compliance"] == 4

        response = api.submit_rooming_list(
            env.booking_id, f.rooming_list_payload(rooms=4), HM
        )

        validate_error(
            response,
            ApiErrorId.ERR_ROOMING_LIST_OCCUPANT_MISMATCH.value,
            expected_status=422,
        )
        assert env.refresh_booking()["booking_status"] == "DRAFT"

    def test_a_cancelled_booking_cannot_be_superseded(self, api):
        """A replacement booking may take over from a live reservation, but a
        booking that has already been cancelled is not an eligible target.

        PRD §3.4: "A supplied `supersedes_booking_id` must name a booking of the
        **same** `registration_id` whose `booking_status` is `DRAFT`,
        `ROOMING_LIST_SUBMITTED` or `CONFIRMED`; pointing at another registration's
        booking, or at one already `CHECKED_OUT` or `CANCELLED`, is rejected with
        `ERR_SUPERSEDE_TARGET_INVALID`."

        Design: Corner/errors/supersede_of_cancelled_booking_rejected
        """
        env = _cancelled_booking_env(api)
        registration = env.refresh_registration()

        response = api.create_booking(
            f.booking_payload(
                registration["id"],
                env.block_id,
                registration["version"],
                supersedes_booking_id=env.booking_id,
            ),
            HM,
        )

        validate_error(
            response, ApiErrorId.ERR_SUPERSEDE_TARGET_INVALID.value, expected_status=422
        )
        assert env.refresh_booking()["booking_status"] == "CANCELLED"
        assert env.refresh_block()["rooms_committed"] == 0


class TestContractRebateParameterRules:
    """The rebate parameter fields must match the declared model exactly."""

    def test_the_rebate_fields_must_match_the_declared_model_both_ways(self, api):
        """A tiered contract that still carries a flat per-room-night figure and a
        flat contract that omits one are refused with the same identifier.

        PRD §3.2: "Under `TIERED_PER_ROOM_NIGHT`, both fields must be omitted,
        because the rate is derived from volume rather than declared."

        PRD §3.2: "Under `PER_ROOM_NIGHT_FLAT`, `rebate_flat_cents_per_room_night`
        is required and must be at least 1, and `rebate_percent` must be omitted."

        PRD §3.2: "Any mismatch between the declared model and the supplied fields
        is rejected with `ERR_REBATE_MODEL_FIELDS_INVALID`."

        Design: Corner/errors/tiered_contract_carrying_flat_rebate_field_rejected
        """
        tournament = fx.create_tournament(api)
        hotel = fx.create_hotel(api)

        validate_error(
            api.create_hotel_contract(
                f.tiered_contract_payload(
                    tournament["id"],
                    hotel["id"],
                    rebate_flat_cents_per_room_night=900,
                ),
                HM,
            ),
            ApiErrorId.ERR_REBATE_MODEL_FIELDS_INVALID.value,
            expected_status=422,
        )
        validate_error(
            api.create_hotel_contract(
                f.hotel_contract_payload(
                    tournament["id"],
                    hotel["id"],
                    rebate_flat_cents_per_room_night=None,
                ),
                HM,
            ),
            ApiErrorId.ERR_REBATE_MODEL_FIELDS_INVALID.value,
            expected_status=422,
        )


class TestInvoicePeriodUniqueness:
    """One billing period per contract."""

    def test_a_second_invoice_for_the_same_period_is_refused_on_the_label(self, api):
        """The contract's September invoice already exists, and although its scope
        is now empty the repeat label is caught first.

        PRD §3.8: "The tournament's `posture` must be `BOOKING_CLOSED` or
        `RECONCILING`, the contract's `status` must be `EXECUTED`, and the
        `period_label` must be unused among the invoices already raised against that
        same contract; a repeat is rejected with `ERR_DUPLICATE_INVOICE_PERIOD`."

        PRD §2.11: "The invoice's `period_label` is unused on that contract —
        otherwise `ERR_DUPLICATE_INVOICE_PERIOD`."

        PRD §2.11: "A new invoice's scope contains at least one booking and at least
        one billable room night — otherwise `ERR_NO_BILLABLE_ROOM_NIGHTS`."

        Design: Corner/errors/duplicate_invoice_period_rejected
        """
        env = fx.invoiced_env(api)
        assert env.invoice["period_label"] == "2026-09"

        response = api.create_rebate_invoice(
            f.rebate_invoice_payload(env.contract_id, period_label="2026-09"), HM
        )

        validate_error(
            response,
            ApiErrorId.ERR_DUPLICATE_INVOICE_PERIOD.value,
            expected_status=409,
        )
        invoice = env.refresh_invoice()
        assert invoice["invoiced_room_nights"] == 12
        assert invoice["status"] == "DRAFT"


class TestExemptionEligibility:
    """The three filing rules that police what an exemption may ask for."""

    def test_a_family_medical_exemption_may_not_ask_for_two_rooms(self, api):
        """The family-medical ground covers one household, so a two-room request is
        refused even though the pooled minimum would have allowed four.

        PRD §3.6: "A `FAMILY_MEDICAL` request may ask for at most one room, because
        it is meant to cover a single household circumstance; asking for more is
        rejected with `ERR_EXEMPTION_SCOPE_TOO_BROAD`."

        Design: Corner/errors/family_medical_request_above_one_room_rejected
        """
        env = fx.registered_team_env(api)
        assert env.refresh_registration()["minimum_rooms_for_compliance"] == 4

        response = api.create_exception_request(
            f.exception_request_payload(
                env.registration_id,
                reason_code=ExceptionReasonCode.FAMILY_MEDICAL.value,
                requested_rooms_exempt=2,
            ),
            HM,
        )

        validate_error(
            response,
            ApiErrorId.ERR_EXEMPTION_SCOPE_TOO_BROAD.value,
            expected_status=422,
        )
        registration = env.refresh_registration()
        assert registration["exempt_rooms_granted"] == 0

    def test_no_team_may_be_excused_from_more_rooms_than_policy_required(self, api):
        """A thirteen-player, three-staff roster owes six rooms segregated but only
        four pooled, and it is the pooled four that caps the request, so a
        five-room hardship filing is refused.

        PRD §3.6: "In every case, `requested_rooms_exempt` may not exceed the
        registration's `minimum_rooms_for_compliance` — a team cannot be excused
        from more rooms than the policy ever required of it — or the request is
        rejected with `ERR_EXEMPTION_EXCEEDS_REQUIREMENT`."

        Design: Corner/errors/exemption_above_compliance_minimum_rejected
        """
        env = fx.registered_team_env(api)
        registration = env.refresh_registration()
        assert registration["required_rooms_registered"] == 6
        assert registration["minimum_rooms_for_compliance"] == 4

        response = api.create_exception_request(
            f.exception_request_payload(
                env.registration_id,
                reason_code=ExceptionReasonCode.FINANCIAL_HARDSHIP.value,
                requested_rooms_exempt=5,
            ),
            HM,
        )

        validate_error(
            response,
            ApiErrorId.ERR_EXEMPTION_EXCEEDS_REQUIREMENT.value,
            expected_status=422,
        )
        assert env.refresh_registration()["exempt_rooms_granted"] == 0

    def test_a_registration_may_keep_only_one_request_live_at_a_time(self, api):
        """A second filing arrives while the first is still sitting at `SUBMITTED`,
        so it is refused and the first request is untouched.

        PRD §3.6: "And a registration may have only one live request at a time: if
        any other request on the same registration sits at `SUBMITTED`,
        `UNDER_REVIEW`, `INFO_REQUESTED` or `APPROVED`, the new filing is rejected
        with `ERR_DUPLICATE_OPEN_EXCEPTION`."

        Design: Corner/errors/second_open_exception_request_rejected
        """
        env = fx.exception_request_env(api)
        assert env.exception_request["status"] == "SUBMITTED"

        response = api.create_exception_request(
            f.exception_request_payload(
                env.registration_id,
                reason_code=ExceptionReasonCode.FINANCIAL_HARDSHIP.value,
                requested_rooms_exempt=4,
            ),
            HM,
        )

        validate_error(
            response,
            ApiErrorId.ERR_DUPLICATE_OPEN_EXCEPTION.value,
            expected_status=409,
        )
        request = env.refresh_exception_request()
        assert request["status"] == "SUBMITTED"
        assert request["reason_code"] == "FAMILY_MEDICAL"


class TestInvoiceMoneyGates:
    """What the hotel may pay, and what the organizer may bill."""

    def test_a_hotel_may_not_remit_more_than_the_invoice_still_shows_outstanding(
        self, api
    ):
        """One cent above the outstanding balance is refused, and the ledger is
        left exactly as the issue left it.

        PRD §3.8: "The acting `HotelRepresentative` must be scoped to the contract,
        and `amount_cents` must be at least 1 and no more than the invoice's current
        `outstanding_cents`; a zero, negative or oversized amount is rejected with
        `ERR_REMITTANCE_EXCEEDS_OUTSTANDING`."

        Design: Corner/errors/remittance_above_outstanding_rejected
        """
        env = fx.issued_invoice_env(api)
        assert env.invoice["outstanding_cents"] == 10800

        response = api.remit_invoice(
            env.invoice_id, f.remit_payload(10801), env.hotel_headers
        )

        validate_error(
            response,
            ApiErrorId.ERR_REMITTANCE_EXCEEDS_OUTSTANDING.value,
            expected_status=422,
        )
        invoice = env.refresh_invoice()
        assert invoice["status"] == "ISSUED"
        assert invoice["total_due_cents"] == 10800
        assert invoice["collected_cents"] == 0
        assert invoice["outstanding_cents"] == 10800

    def test_an_invoice_whose_penalty_ate_the_whole_rebate_cannot_be_issued(self, api):
        """A threshold of the entire block leaves a 43,200-cent penalty against a
        10,800-cent rebate, so the amount due floors at zero and there is nothing to
        issue.

        PRD §3.8: "`attrition_penalty_cents` is
        `attrition_shortfall_room_nights_per_block` multiplied by the contract's
        `attrition_penalty_rate_cents_per_room_night`."

        PRD §3.8: "`total_due_cents` is `invoiced_rebate_cents` less
        `attrition_penalty_cents`, floored at 0 — a penalty larger than the rebate
        zeroes the claim rather than turning it into a debt owed by the event."

        PRD §3.8: "`ISSUE`, a housing-manager action, moves the invoice `DRAFT →
        ISSUED` and requires `total_due_cents` to be at least 1; issuing a
        zero-value invoice is rejected with `ERR_INVOICE_TOTAL_NOT_POSITIVE`."

        Design: Corner/errors/issue_of_fully_offset_invoice_rejected
        """
        env = _fully_offset_invoice_env(api)
        assert env.invoice["invoiced_room_nights"] == 12
        assert env.invoice["invoiced_rebate_cents"] == 10800
        assert env.invoice["attrition_penalty_cents"] == 43200
        assert env.invoice["total_due_cents"] == 0

        response = api.invoice_lifecycle(
            env.invoice_id,
            f.lifecycle_payload(InvoiceLifecycleAction.ISSUE.value),
            HM,
        )

        validate_error(
            response,
            ApiErrorId.ERR_INVOICE_TOTAL_NOT_POSITIVE.value,
            expected_status=422,
        )
        assert env.refresh_invoice()["status"] == "DRAFT"
        assert env.refresh_tournament()["posture"] == "BOOKING_CLOSED"


class TestComplaintFilingAndRemedies:
    """A remedy that omits its amount, and a filing that cites no subject."""

    def test_a_fee_waiver_must_state_the_amount_it_waives(self, api):
        """The complaint names an affected booking and the investigate branch does
        allow a fee waiver, but no amount is supplied, so the remedy is structurally
        incomplete and no credit reaches the booking.

        PRD §3.9: "Structurally, `FEE_WAIVER` requires a `remedy_amount_cents` of at
        least 1 **and** a non-null `affected_booking_id` on the complaint, while
        `NONE`, `RATE_ADJUSTMENT` and `POLICY_EXEMPTION` forbid `remedy_amount_cents`
        entirely; a mismatch is rejected with `ERR_REMEDY_FIELDS_INVALID`."

        PRD §3.9: "A complaint routed `INVESTIGATE` may only be resolved with `NONE`
        or `FEE_WAIVER` — the narrow, money-only vocabulary."

        Design: Corner/errors/fee_waiver_without_amount_rejected
        """
        env = _investigating_complaint_on_a_booking_env(api)
        assert env.complaint["status"] == "INVESTIGATING"

        response = api.adjudicate_complaint(
            env.complaint["id"],
            f.adjudicate_payload(
                ComplaintOutcome.UPHOLD.value, RemedyType.FEE_WAIVER.value
            ),
            RIGHTS_HOLDER_HEADERS,
        )

        validate_error(
            response, ApiErrorId.ERR_REMEDY_FIELDS_INVALID.value, expected_status=422
        )
        complaint = env.refresh_complaint()
        assert complaint["status"] == "INVESTIGATING"
        assert complaint["remedy_credit_cents"] == 0
        assert env.refresh_booking()["penalty_credit_cents"] == 0

    def test_a_complaint_that_names_no_subject_at_all_is_refused(self, api):
        """A category and a narrative are not enough: without a registration, a
        cited exception request or an affected booking there is nothing for the
        complaint to be about.

        PRD §3.9: "At least one of those three must be supplied, or the filing is
        rejected with `ERR_COMPLAINT_SUBJECT_MISSING`."

        Design: Corner/errors/complaint_without_any_subject_rejected
        """
        tournament = fx.create_tournament(api)

        response = api.create_complaint(f.complaint_payload(tournament["id"]), HM)

        validate_error(
            response,
            ApiErrorId.ERR_COMPLAINT_SUBJECT_MISSING.value,
            expected_status=422,
        )
