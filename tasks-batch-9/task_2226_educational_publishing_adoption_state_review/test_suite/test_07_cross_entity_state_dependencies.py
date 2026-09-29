"""Operations on one record that the state of a neighbouring record decides.

Presenting a slot asks the panel, confirming an order asks the edition, and
opening a session asks the cycle — none of them named in the request body.
"""

from test_helpers import (
    CYCLE_STATUS_IN_REVIEW,
    ORDER_STATUS_CONFIRMED,
    ORDER_STATUS_QUOTED,
    PANEL_STATUS_IN_SESSION,
    PANEL_STATUS_SCHEDULED,
    REVIEW_STATUS_PRESENTED,
    REVIEW_STATUS_SCHEDULED,
    SLOT_STATUS_PRESENTED,
    SLOT_STATUS_RESERVED,
    TITLE_STATUS_SUNSET,
    ApiErrorId,
    fixtures,
    validate_error,
    validate_success,
)


def test_a_slot_cannot_be_presented_while_its_panel_has_not_sat_down(api):
    """The hearing is refused on the panel's state, not on the slot's own.

    PRD 3.8: "Three preconditions apply: the panel must be `IN_SESSION`, else
    `ERR_COMMITTEE_PANEL_STATE_INVALID`; the logical clock must have reached the
    slot's `start_at`, else `ERR_SLOT_NOT_STARTED`; and the submission's
    `content_pin_stale` must be false, else `ERR_CONTENT_PIN_STALE` — a submission
    whose edition changed between reservation and hearing cannot be heard."

    Design: Difficulty/cross_entity_state_dependency/slot_present_gated_by_panel_session_state
    """
    world = fixtures.seed_scheduled_submission(api, "MT")
    fixtures.advance_to_in_review(api, world)
    fixtures.set_clock(api, fixtures.CLOCK_AT_PANEL_SESSION_START)

    panel = validate_success(api.get_committee_panel(world.panel_id, world.officer))
    assert panel["status"] == PANEL_STATUS_SCHEDULED

    validate_error(
        api.present_slot(world.slot_id, world.officer),
        ApiErrorId.ERR_COMMITTEE_PANEL_STATE_INVALID,
        409,
    )

    slot = validate_success(api.get_presentation_slot(world.slot_id, world.officer))
    assert slot["status"] == SLOT_STATUS_RESERVED

    submission = validate_success(
        api.get_submission(world.submission_id, fixtures.EDITOR)
    )
    assert submission["review_status"] == REVIEW_STATUS_SCHEDULED


def test_opening_the_session_lets_the_same_slot_be_presented(api):
    """Once the panel sits, the hearing carries the submission along with the slot.

    PRD 3.8: "Presenting a slot moves it from `RESERVED` to `PRESENTED` and
    simultaneously moves its submission's `review_status` from `SCHEDULED` to
    `PRESENTED`."

    Design: Difficulty/cross_entity_state_dependency/slot_present_gated_by_panel_session_state
    """
    world = fixtures.seed_scheduled_submission(api, "MT")
    fixtures.advance_to_in_review(api, world)
    fixtures.set_clock(api, fixtures.CLOCK_AT_PANEL_SESSION_START)

    opened = validate_success(api.open_panel_session(world.panel_id, world.officer))
    assert opened["status"] == PANEL_STATUS_IN_SESSION

    presented = validate_success(api.present_slot(world.slot_id, world.officer))
    assert presented["status"] == SLOT_STATUS_PRESENTED

    submission = validate_success(
        api.get_submission(world.submission_id, fixtures.EDITOR)
    )
    assert submission["review_status"] == REVIEW_STATUS_PRESENTED

    panel = validate_success(api.get_committee_panel(world.panel_id, world.officer))
    assert panel["reserved_minutes"] == 30


def test_a_retired_edition_cannot_have_its_outstanding_quote_confirmed(api):
    """The quote survives the sunset; the confirmation does not.

    PRD 3.9: "The edition must not be `SUNSET`, else `ERR_TITLE_SUNSET`."

    Design: Difficulty/cross_entity_state_dependency/order_confirm_gated_by_title_sunset_state
    """
    world = fixtures.seed_state(api, "NE")
    fixtures.seed_title(
        api,
        world,
        isbn_base="9780000001401",
        list_price_cents=8800,
        receipt_units=200,
    )
    order_id = fixtures.quote_order(api, world, print_units=50, digital_seats=0)

    quoted = validate_success(api.get_district_order(order_id, fixtures.QUOTING_REP))
    # 50 x 8,800 = 440,000 pre-freight, plus 1.5% freight of 6,600.
    assert quoted["quoted_tcv_cents"] == 446600

    fixtures.sunset_title(api, world.title_id, target_year=2029)
    retired = validate_success(api.get_title(world.title_id, fixtures.EDITOR))
    assert retired["status"] == TITLE_STATUS_SUNSET
    assert retired["on_hand_units"] == 0
    assert retired["written_off_units"] == 200

    validate_error(
        api.confirm_district_order(order_id, fixtures.CONFIRMING_REP),
        ApiErrorId.ERR_TITLE_SUNSET,
        409,
    )

    order = validate_success(api.get_district_order(order_id, fixtures.QUOTING_REP))
    assert order["status"] == ORDER_STATUS_QUOTED
    assert order["contracted_tcv_cents"] is None
    assert order["allocated_units"] == 0


def test_a_live_edition_confirms_the_order_and_commits_the_stock(api):
    """The same order shape against an ACTIVE edition moves the shelf.

    PRD 3.9: "A confirmation writes `contracted_tcv_cents` and
    `freight_surcharge_cents` from the contracted variant, records
    `confirmed_by_user_id`, sets `allocated_units` to `print_units`, and moves the
    stock: the edition's `on_hand_units` decreases by `print_units` and its
    `committed_units` increases by the same amount."

    Design: Difficulty/cross_entity_state_dependency/order_confirm_gated_by_title_sunset_state
    """
    world = fixtures.seed_state(api, "NE")
    fixtures.seed_title(
        api,
        world,
        isbn_base="9780000001402",
        list_price_cents=9000,
        receipt_units=500,
    )
    order_id = fixtures.quote_order(api, world, print_units=100, digital_seats=10)

    quoted = validate_success(api.get_district_order(order_id, fixtures.QUOTING_REP))
    # 100 x 9,000 plus 10 seats at the default 1,200 is 912,000 pre-freight,
    # and freight is 1.5% of the 900,000 print subtotal.
    assert quoted["quoted_tcv_cents"] == 925500

    confirmed = validate_success(
        api.confirm_district_order(order_id, fixtures.CONFIRMING_REP)
    )
    assert confirmed["status"] == ORDER_STATUS_CONFIRMED
    # No proposal is attached and the state is open territory, so the contracted
    # variant reuses the list price and takes no rebate.
    assert confirmed["contracted_tcv_cents"] == 925500
    assert confirmed["freight_surcharge_cents"] == 13500
    assert confirmed["allocated_units"] == 100

    edition = validate_success(api.get_title(world.title_id, fixtures.EDITOR))
    assert edition["on_hand_units"] == 400
    assert edition["committed_units"] == 100


def test_a_panel_session_cannot_open_before_the_cycle_reaches_review(api):
    """The clock has reached the sitting but the cycle is still taking submissions.

    PRD 3.8: "Opening a panel session moves the panel from `SCHEDULED` to
    `IN_SESSION` and requires three things of the acting officer's state: the cycle
    must be `IN_REVIEW`, else `ERR_ADOPTION_CYCLE_STATE_INVALID`, and the logical
    clock must have reached `session_start_at`, else `ERR_PANEL_SESSION_NOT_DUE`."

    Design: Difficulty/cross_entity_state_dependency/panel_open_session_gated_by_cycle_review_phase
    """
    world = fixtures.seed_scheduled_submission(api, "KS")
    fixtures.set_clock(api, fixtures.CLOCK_AT_PANEL_SESSION_START)

    validate_error(
        api.open_panel_session(world.panel_id, world.officer),
        ApiErrorId.ERR_ADOPTION_CYCLE_STATE_INVALID,
        409,
    )

    panel = validate_success(api.get_committee_panel(world.panel_id, world.officer))
    assert panel["status"] == PANEL_STATUS_SCHEDULED


def test_two_phase_advances_bring_the_cycle_to_review_and_the_panel_may_sit(api):
    """The same request succeeds once the cycle has taken its two further steps.

    PRD 3.8: "From that point the panel's slots become presentable and further
    reservations are refused."

    PRD 3.1: "Every successful run increments `phase_epoch` by 1, so the counter
    records how many advances the cycle has actually taken."

    Design: Difficulty/cross_entity_state_dependency/panel_open_session_gated_by_cycle_review_phase
    """
    world = fixtures.seed_scheduled_submission(api, "KS")
    fixtures.set_clock(api, fixtures.CLOCK_AT_PANEL_SESSION_START)
    fixtures.advance_phase(api, world, times=2)

    cycle = validate_success(api.get_adoption_cycle(world.cycle_id, world.officer))
    assert cycle["status"] == CYCLE_STATUS_IN_REVIEW
    assert cycle["phase_epoch"] == 3

    opened = validate_success(api.open_panel_session(world.panel_id, world.officer))
    assert opened["status"] == PANEL_STATUS_IN_SESSION

    slot = validate_success(api.get_presentation_slot(world.slot_id, world.officer))
    assert slot["status"] == SLOT_STATUS_RESERVED

    submission = validate_success(
        api.get_submission(world.submission_id, fixtures.EDITOR)
    )
    assert submission["review_status"] == REVIEW_STATUS_SCHEDULED
