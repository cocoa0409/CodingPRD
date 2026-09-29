"""Boundary bands, notice tiers, cross-entity independence and conditional gates."""

from test_helpers import (
    ERR_CHAPERONE_SHORTFALL,
    ERR_INSPECTOR_NOT_INDEPENDENT,
    ERR_WEIGHT_LIMIT_EXCEEDED,
    assert_instant,
    assert_kg,
    assert_ledger,
    assert_money,
    assert_settlement,
    validate_error,
    validate_success,
)
from test_helpers.constants import (
    CLOCK_TEST_UTC,
    ELEMENT_INSPECTION_DUE_ON,
    ELEMENT_NAME_LOW,
    HEAVY_BIRTH_DATE,
    HEAVY_NAME,
    LOW_WEIGHT_MAX_KG,
)
from test_helpers.factories import professional_inspection_payload
from test_helpers.fixtures import (
    add_blocks,
    add_participant,
    assign_facilitator,
    clear_log,
    confirm_booking,
    create_booking,
    create_contract_inspector,
    create_course,
    create_element,
    create_funded_client,
    quote_booking,
    set_clock,
    staffed_course,
    submit_packet,
)
from test_helpers.test_users import PROGRAM_DIRECTOR, make_group_coordinator_headers

OVER_THE_CEILING_KG = 140.0
PAYMENT_CENTS = 20000
DEPOSIT_CENTS = 341
CANCEL_CLOCK_UTC = "2026-09-09T08:00:00Z"
SIX_DAYS_NOTICE = 6

TWO_BLOCK_PROGRAM = [
    (1, "ICEBREAKER", "2026-09-15T09:00:00Z", "2026-09-15T09:45:00Z"),
    (2, "DEBRIEF", "2026-09-15T10:15:00Z", "2026-09-15T10:45:00Z"),
]


def _confirmed_program_ready_for_the_low_element(api, weight_kg):
    """A confirmed program whose icebreaker is closed and whose low element is next.

    The low element carries today's CLEAR pre-use log and a professional inspection
    date well in the future, so the only open question at block start is the single
    participant's weight against the element's band.
    """
    set_clock(api, CLOCK_TEST_UTC)
    world = staffed_course(api)
    l_id = create_element(
        api, world["course_id"], "LOW_ELEMENT", element_name=ELEMENT_NAME_LOW
    )
    clear_log(api, l_id, world["f1_id"], world["f1_headers"])
    gc_id = create_funded_client(api, amount_cents=PAYMENT_CENTS)
    b_id, _ = create_booking(api, world["course_id"], gc_id, 1)
    p1_id = add_participant(
        api,
        gc_id,
        b_id,
        "ADULT",
        screen=True,
        full_name=HEAVY_NAME,
        birth_date=HEAVY_BIRTH_DATE,
        weight_kg=weight_kg,
    )
    specs = [
        (1, "ICEBREAKER", "2026-09-15T09:00:00Z", "2026-09-15T09:45:00Z", None),
        (2, "LOW_ELEMENT", "2026-09-15T10:15:00Z", "2026-09-15T11:00:00Z", l_id),
        (3, "DEBRIEF", "2026-09-15T11:20:00Z", "2026-09-15T11:50:00Z", None),
    ]
    block_ids = add_blocks(api, b_id, specs)
    quote_booking(api, b_id)
    confirm_booking(api, gc_id, b_id)
    assign_facilitator(api, block_ids[0], world["f1_id"])
    assign_facilitator(api, block_ids[1], world["f1_id"])
    validate_success(api.start_program_block(block_ids[0], world["f1_headers"]))
    validate_success(api.complete_program_block(block_ids[0], {}, world["f1_headers"]))

    world.update(
        {
            "l_id": l_id,
            "gc_id": gc_id,
            "b_id": b_id,
            "p1_id": p1_id,
            "blk1_id": block_ids[0],
            "blk2_id": block_ids[1],
        }
    )
    return world


class TestWeightBandIsInclusiveAtTheCeiling:
    """Four kilograms decide whether the same program may put its participant on the hardware."""

    def test_a_participant_above_the_ceiling_cannot_start_the_low_element(self, api):
        """The block is otherwise perfect, so the weight band is the only thing left to fail.

        PRD 3.8: "When the block carries an element, every eligible participant's
        `weight_kg` must sit inside that element's inclusive band from
        `min_participant_weight_kg` to `max_participant_weight_kg`, or the refusal is
        `ERR_WEIGHT_LIMIT_EXCEEDED`."

        PRD 2.12: "Participant weight limits on the rigged element —
        `ERR_WEIGHT_LIMIT_EXCEEDED`. Applies to block start."

        Design: Corner/validations/start_rejects_participant_over_the_element_weight_ceiling
        """
        world = _confirmed_program_ready_for_the_low_element(api, OVER_THE_CEILING_KG)

        participant = validate_success(api.get_participant(world["p1_id"], PROGRAM_DIRECTOR))
        assert participant["screening_status"] == "ELIGIBLE"
        assert_kg(participant["weight_kg"], OVER_THE_CEILING_KG)

        validate_error(
            api.start_program_block(world["blk2_id"], world["f1_headers"]),
            ERR_WEIGHT_LIMIT_EXCEEDED,
            422,
        )

        block = validate_success(api.get_program_block(world["blk2_id"], PROGRAM_DIRECTOR))
        assert block["status"] == "SCHEDULED"
        assert block["started_at"] is None
        assert block["required_facilitator_count"] == 1
        assert block["assigned_facilitator_count"] == 1

        booking = validate_success(api.get_booking(world["b_id"], PROGRAM_DIRECTOR))
        assert booking["status"] == "CONFIRMED"

    def test_a_participant_exactly_at_the_ceiling_starts_the_low_element(self, api):
        """The band includes its endpoint, so the identical program runs at 136.0 kg.

        PRD 3.8: "When the block carries an element, every eligible participant's
        `weight_kg` must sit inside that element's inclusive band from
        `min_participant_weight_kg` to `max_participant_weight_kg`, or the refusal is
        `ERR_WEIGHT_LIMIT_EXCEEDED`."

        PRD 3.8: "A successful start moves the block `SCHEDULED → IN_PROGRESS`,
        stamps `started_at` with the clock instant, freezes `actual_head_count` as
        the number of participants on the booking whose `screening_status` is
        `ELIGIBLE`, and increments the block's `version`."

        Design: Corner/validations/start_accepts_participant_exactly_at_the_element_weight_ceiling
        """
        world = _confirmed_program_ready_for_the_low_element(api, LOW_WEIGHT_MAX_KG)

        started = validate_success(
            api.start_program_block(world["blk2_id"], world["f1_headers"])
        )

        assert started["status"] == "IN_PROGRESS"
        assert_instant(started["started_at"], CLOCK_TEST_UTC, "started_at")
        assert started["actual_head_count"] == 1

        icebreaker = validate_success(api.get_program_block(world["blk1_id"], PROGRAM_DIRECTOR))
        assert icebreaker["status"] == "COMPLETED"

        booking = validate_success(api.get_booking(world["b_id"], PROGRAM_DIRECTOR))
        assert booking["status"] == "CONFIRMED"


class TestCancellationNoticeTiers:
    """Six days' notice is the bottom band, and it forfeits everything held."""

    def test_cancelling_six_days_out_forfeits_the_whole_deposit(self, api):
        """The notice arithmetic lands on 6 days and the deposit converts to retained revenue.

        PRD 3.9: "The settlement first records `notice_days_at_cancel` as the number
        of days from the clock date to the booking's `program_date`, which may be
        negative when the program date has already passed."

        PRD 3.9: "Under `CLIENT_INITIATED`, a notice of 30 days or more forfeits
        nothing; a notice from 14 through 29 days forfeits 25 percent; a notice from
        7 through 13 days forfeits 50 percent; and a notice of 6 days or fewer,
        including a negative notice, forfeits the whole deposit."

        PRD 3.9: "The ledger then moves in one settled step: `retained_cents` takes
        the `cancellation_fee_cents`, `deposit_allocated_cents` returns to zero, and
        `refund_cents` is added back to the group client's `credit_balance_cents` —
        the compensating half of the client-funds identity."

        PRD 3.9: "One reputational counter falls out of all this: a group client's
        `late_cancellation_count` is the number of its bookings that are `CANCELLED`
        with `cancellation_variant` `CLIENT_INITIATED` and a `notice_days_at_cancel`
        below fourteen days."

        Design: Corner/validations/cancel_six_days_before_program_date_retains_the_whole_deposit
        """
        set_clock(api, CLOCK_TEST_UTC)
        world = staffed_course(api)
        gc_id = create_funded_client(api, amount_cents=PAYMENT_CENTS)
        b_id, _ = create_booking(api, world["course_id"], gc_id, 1)
        add_participant(api, gc_id, b_id, "ADULT")
        add_blocks(api, b_id, TWO_BLOCK_PROGRAM)
        quote_booking(api, b_id)
        confirm_booking(api, gc_id, b_id)

        set_clock(api, CANCEL_CLOCK_UTC)

        cancelled = validate_success(
            api.cancel_booking(
                b_id,
                {"reason": "Bus contractor cancelled; group cannot travel"},
                make_group_coordinator_headers(gc_id),
            )
        )

        assert cancelled["status"] == "CANCELLED"
        assert_settlement(
            cancelled,
            variant="CLIENT_INITIATED",
            fee=DEPOSIT_CENTS,
            refund=0,
            retained=DEPOSIT_CENTS,
            notice_days=SIX_DAYS_NOTICE,
        )
        assert_money(cancelled["deposit_allocated_cents"], 0, "deposit_allocated_cents")

        client = validate_success(api.get_group_client(gc_id, PROGRAM_DIRECTOR))
        assert_ledger(client, credit=PAYMENT_CENTS - DEPOSIT_CENTS, payments=PAYMENT_CENTS)
        assert client["late_cancellation_count"] == 1


class TestChaperoneCoverageIsSizedOffMinors:
    """A fully screened minor is still a minor who needs an adult on site."""

    def test_confirming_a_lone_minor_without_a_chaperone_is_refused(self, api):
        """Individual screening and roster readiness both pass and the coverage gate still fails.

        PRD 3.6: "Chaperone coverage is sized off minors only.
        `required_chaperone_count` is the number of participants whose
        `is_chaperone` is false and whose `age_years` is below eighteen, divided by
        ten and rounded **up** to a whole person — a screening-blocked minor still
        needs supervision on site and is still counted."

        PRD 3.5: "the number of participants whose `is_chaperone` is true must be at
        least `required_chaperone_count`, or `ERR_CHAPERONE_SHORTFALL`"

        PRD 3.5: "The quote run also refreshes `required_chaperone_count`, whose
        definition belongs with the roster rules of §3.6."

        Design: Corner/validations/confirm_rejected_when_chaperone_coverage_falls_short_of_the_minor_ratio
        """
        set_clock(api, CLOCK_TEST_UTC)
        world = staffed_course(api)
        gc_id = create_funded_client(api, amount_cents=PAYMENT_CENTS)
        b_id, _ = create_booking(api, world["course_id"], gc_id, 1)
        p_minor_id = add_participant(api, gc_id, b_id, "MINOR", screen=False)
        minor = submit_packet(api, gc_id, p_minor_id, guardian_signature_provided=True)
        assert minor["is_minor"] is True
        assert minor["screening_status"] == "ELIGIBLE"

        add_blocks(api, b_id, TWO_BLOCK_PROGRAM)
        quoted = quote_booking(api, b_id)
        assert quoted["required_chaperone_count"] == 1

        validate_error(
            api.confirm_booking(b_id, make_group_coordinator_headers(gc_id)),
            ERR_CHAPERONE_SHORTFALL,
            422,
        )

        booking = validate_success(api.get_booking(b_id, PROGRAM_DIRECTOR))
        assert booking["status"] == "QUOTED"
        assert booking["roster_status"] == "READY"
        assert_money(booking["deposit_allocated_cents"], 0, "deposit_allocated_cents")

        client = validate_success(api.get_group_client(gc_id, PROGRAM_DIRECTOR))
        assert_ledger(client, credit=PAYMENT_CENTS, payments=PAYMENT_CENTS)


class TestInspectorIndependenceIsAPropertyOfTheRow:
    """Independence is read off the referenced facilitator, not off the acting role."""

    def test_an_inspector_on_the_operator_payroll_cannot_open_an_inspection(self, api):
        """The staff type and certification are right and the payroll flag alone rejects it.

        PRD 3.3: "The named inspector must genuinely be independent: their
        `staff_type` must be `CONTRACT_INSPECTOR`, their `is_operator_employee` must
        be false, and their `cert_status` must be `ACTIVE`. Any of those failing
        yields `ERR_INSPECTOR_NOT_INDEPENDENT`."

        PRD 2.12: "Inspector independence — `ERR_INSPECTOR_NOT_INDEPENDENT`.
        Applies to professional-inspection creation."

        Design: Corner/validations/professional_inspection_rejected_when_inspector_is_an_operator_employee
        """
        set_clock(api, CLOCK_TEST_UTC)
        course_id = create_course(api)
        insp_id = create_contract_inspector(api, course_id, is_operator_employee=True)
        l_id = create_element(api, course_id, "LOW_ELEMENT", element_name=ELEMENT_NAME_LOW)

        inspector = validate_success(api.get_facilitator(insp_id, PROGRAM_DIRECTOR))
        assert inspector["staff_type"] == "CONTRACT_INSPECTOR"
        assert inspector["is_operator_employee"] is True
        assert inspector["cert_status"] == "ACTIVE"

        validate_error(
            api.create_professional_inspection(
                professional_inspection_payload(l_id, insp_id), PROGRAM_DIRECTOR
            ),
            ERR_INSPECTOR_NOT_INDEPENDENT,
            422,
        )

        element = validate_success(api.get_element(l_id, PROGRAM_DIRECTOR))
        assert element["next_professional_inspection_due_on"] == ELEMENT_INSPECTION_DUE_ON


class TestElementFacingGatesAreConditional:
    """A conversation block has no hardware, so the hardware gates cannot apply to it."""

    def test_an_icebreaker_starts_on_a_site_with_no_inspection_logs_at_all(self, api):
        """No element means no daily pre-use log to look for, and the start succeeds.

        PRD 3.8: "The element-facing gates follow. When the block carries an
        `element_id`, that element's `status` must be `SERVICEABLE`; an element at
        `RESTRICTED` or `OUT_OF_SERVICE` is refused with
        `ERR_ELEMENT_NOT_SERVICEABLE`, and an element at `RETIRED` with the more
        specific `ERR_ELEMENT_RETIRED`."

        PRD 3.8: "The element must carry an operational inspection log whose
        `log_date` equals the clock date and whose `result` is `CLEAR`, with no later
        log for that element recording anything other than `CLEAR`; otherwise the
        start is refused with `ERR_DAILY_INSPECTION_MISSING`."

        PRD 3.7: "`ICEBREAKER` and `DEBRIEF` blocks are conversation, not hardware,
        and must carry a null `element_id`; supplying one is refused."

        Design: Corner/validations/block_without_a_rigged_element_skips_the_daily_inspection_check
        """
        set_clock(api, CLOCK_TEST_UTC)
        world = staffed_course(api)
        gc_id = create_funded_client(api, amount_cents=PAYMENT_CENTS)
        b_id, _ = create_booking(api, world["course_id"], gc_id, 1)
        add_participant(api, gc_id, b_id, "ADULT")
        block_ids = add_blocks(api, b_id, TWO_BLOCK_PROGRAM)
        quote_booking(api, b_id)
        confirm_booking(api, gc_id, b_id)
        assign_facilitator(api, block_ids[0], world["f1_id"])

        started = validate_success(
            api.start_program_block(block_ids[0], world["f1_headers"])
        )

        assert started["status"] == "IN_PROGRESS"
        assert started["element_id"] is None
        assert started["required_facilitator_count"] == 1
        assert_instant(started["started_at"], CLOCK_TEST_UTC, "started_at")
