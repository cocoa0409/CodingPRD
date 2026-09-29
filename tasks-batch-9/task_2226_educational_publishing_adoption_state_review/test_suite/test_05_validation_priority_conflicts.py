"""Requests that fail two checks at once, where only the earlier check may answer.

Section 2.6 fixes one evaluation order for the whole API, so a request that
violates a late rule and an early rule reports the early one and nothing else.
"""

from test_helpers import (
    ADOPTION_MODEL_ADOPTION_LIST,
    ORDER_STATUS_QUOTED,
    REVIEW_STATUS_DRAFT,
    REVIEW_STATUS_FILED,
    ApiErrorId,
    factories,
    fixtures,
    get_success_data,
    validate_error,
    validate_success,
)


def test_a_cycle_that_never_opened_answers_before_the_prohibited_tag_does(api):
    """Filing into a SCHEDULED cycle reports the phase, not the forbidden tag.

    PRD 3.5: "The cycle must be `OPEN`, else
    `ERR_CYCLE_NOT_OPEN_FOR_SUBMISSION`."

    Design: Difficulty/priority_pair_validation_conflict/cycle_phase_state_outranks_prohibited_content_on_file
    """
    world = fixtures.seed_state(api, "WA", prohibited_content_tags=["OUTDATED_MAP"])
    fixtures.seed_standard(api, world, "WA.M.5.1")
    fixtures.seed_cycle(api, world)
    fixtures.seed_title(
        api,
        world,
        isbn_base="9780000000901",
        content_tags=["CIVIC_DUTY", "OUTDATED_MAP"],
    )
    fixtures.set_clock(api, fixtures.CLOCK_INSIDE_SUBMISSION_WINDOW)

    submission_id = get_success_data(
        api.create_submission(
            factories.submission_payload(world.cycle_id, world.title_id), fixtures.EDITOR
        )
    )["id"]
    get_success_data(
        api.create_correlation(
            submission_id, factories.correlation_payload("WA.M.5.1"), fixtures.EDITOR
        )
    )

    validate_error(
        api.file_submission(submission_id, fixtures.EDITOR),
        ApiErrorId.ERR_CYCLE_NOT_OPEN_FOR_SUBMISSION,
        409,
    )

    submission = validate_success(api.get_submission(submission_id, fixtures.EDITOR))
    assert submission["review_status"] == REVIEW_STATUS_DRAFT
    assert submission["prohibited_hit_count"] == 1


def test_the_prohibited_tag_answers_only_once_the_cycle_is_open(api):
    """With the cycle OPEN the same filing reaches the content check and fails there.

    PRD 3.5: "The submission's `prohibited_hit_count` must be zero, else
    `ERR_PROHIBITED_CONTENT_PRESENT`."

    Design: Difficulty/priority_pair_validation_conflict/cycle_phase_state_outranks_prohibited_content_on_file
    """
    world = fixtures.seed_state(api, "WA", prohibited_content_tags=["OUTDATED_MAP"])
    fixtures.seed_standard(api, world, "WA.M.5.1")
    fixtures.seed_cycle(api, world)
    fixtures.seed_title(
        api,
        world,
        isbn_base="9780000000901",
        content_tags=["CIVIC_DUTY", "OUTDATED_MAP"],
    )
    fixtures.set_clock(api, fixtures.CLOCK_INSIDE_SUBMISSION_WINDOW)

    submission_id = get_success_data(
        api.create_submission(
            factories.submission_payload(world.cycle_id, world.title_id), fixtures.EDITOR
        )
    )["id"]
    get_success_data(
        api.create_correlation(
            submission_id, factories.correlation_payload("WA.M.5.1"), fixtures.EDITOR
        )
    )
    fixtures.advance_phase(api, world)

    validate_error(
        api.file_submission(submission_id, fixtures.EDITOR),
        ApiErrorId.ERR_PROHIBITED_CONTENT_PRESENT,
        422,
    )

    submission = validate_success(api.get_submission(submission_id, fixtures.EDITOR))
    assert submission["review_status"] == REVIEW_STATUS_DRAFT
    assert submission["prohibited_hit_count"] == 1


def test_a_missing_price_filing_answers_before_the_empty_warehouse_does(api):
    """Confirming in an adopted-list state reports the missing filing, not the stock.

    PRD 3.9: "In an `ADOPTION_LIST` state three further conditions apply: the order
    must carry a `pricing_proposal_id`, else `ERR_PRICING_PROPOSAL_REQUIRED`; that
    proposal's `status` must be `APPROVED`, else
    `ERR_PRICING_PROPOSAL_STATE_INVALID`; and the edition's `adopted_state_codes`
    must contain the district's own `state_code`, else
    `ERR_TITLE_NOT_ON_ADOPTED_LIST`."

    Design: Difficulty/priority_pair_validation_conflict/pricing_proposal_referential_outranks_inventory_fiscal_on_confirm
    """
    world = fixtures.seed_state(
        api, "NY", adoption_model=ADOPTION_MODEL_ADOPTION_LIST
    )
    fixtures.seed_title(api, world, isbn_base="9780000001201", receipt_units=0)
    order_id = fixtures.quote_order(api, world, print_units=100)

    validate_error(
        api.confirm_district_order(order_id, fixtures.CONFIRMING_REP),
        ApiErrorId.ERR_PRICING_PROPOSAL_REQUIRED,
        422,
    )

    order = validate_success(api.get_district_order(order_id, fixtures.QUOTING_REP))
    assert order["status"] == ORDER_STATUS_QUOTED
    assert order["contracted_tcv_cents"] is None
    assert order["allocated_units"] == 0

    edition = validate_success(api.get_title(world.title_id, fixtures.EDITOR))
    assert edition["on_hand_units"] == 0
    assert edition["committed_units"] == 0


def test_an_open_territory_confirmation_reaches_the_inventory_check(api):
    """Without the adopted-list conditions the empty warehouse is what refuses.

    PRD 3.9: "Finally, the edition's `on_hand_units` must be at least the order's
    `print_units`, else `ERR_INSUFFICIENT_PRINT_INVENTORY`."

    Design: Difficulty/priority_pair_validation_conflict/pricing_proposal_referential_outranks_inventory_fiscal_on_confirm
    """
    world = fixtures.seed_state(api, "NY")
    fixtures.seed_title(api, world, isbn_base="9780000001201", receipt_units=0)
    order_id = fixtures.quote_order(api, world, print_units=100)

    validate_error(
        api.confirm_district_order(order_id, fixtures.CONFIRMING_REP),
        ApiErrorId.ERR_INSUFFICIENT_PRINT_INVENTORY,
        409,
    )

    order = validate_success(api.get_district_order(order_id, fixtures.QUOTING_REP))
    assert order["status"] == ORDER_STATUS_QUOTED
    assert order["contracted_tcv_cents"] is None


def test_a_slot_running_past_the_session_answers_before_the_minute_budget(api):
    """A two-hour window on a one-hour sitting reports the session, not the budget.

    PRD 3.8: "The requested window must lie inside the panel's session, at or after
    `session_start_at` and at or before `session_end_at`, else
    `ERR_SLOT_OUTSIDE_SESSION`."

    Design: Difficulty/priority_pair_validation_conflict/slot_session_window_temporal_outranks_capacity_constraint
    """
    world = fixtures.seed_filed_submission(api, "NM")
    panel_id = fixtures.seed_panel(
        api,
        world,
        session_start_at="2026-10-20T14:00:00Z",
        session_end_at="2026-10-20T15:00:00Z",
    )
    version = api.read_panel_version(panel_id, world.officer)

    validate_error(
        api.reserve_slot(
            panel_id,
            factories.slot_payload(
                world.submission_id,
                version,
                start_at="2026-10-20T14:30:00Z",
                end_at="2026-10-20T16:30:00Z",
            ),
            world.officer,
        ),
        ApiErrorId.ERR_SLOT_OUTSIDE_SESSION,
        422,
    )

    panel = validate_success(api.get_committee_panel(panel_id, world.officer))
    assert panel["slot_minutes_capacity"] == 60
    assert panel["reserved_minutes"] == 0

    submission = validate_success(
        api.get_submission(world.submission_id, fixtures.EDITOR)
    )
    assert submission["review_status"] == REVIEW_STATUS_FILED


def test_a_slot_inside_the_session_still_faces_the_minute_budget(api):
    """A window that fits the sitting but not the policy cap is refused on budget.

    PRD 3.8: "Finally, the panel's minute budget must accommodate the slot: the
    panel's current `reserved_minutes` plus the new slot's `duration_minutes` must
    be at most `slot_minutes_capacity`, else `ERR_PANEL_CAPACITY_EXCEEDED` — and
    because `slot_minutes_capacity` may sit well below the wall-clock session
    length, a window that comfortably fits inside the session can still be refused
    on budget."

    Design: Difficulty/priority_pair_validation_conflict/slot_session_window_temporal_outranks_capacity_constraint
    """
    world = fixtures.seed_filed_submission(api, "NM")
    panel_id = fixtures.seed_panel(
        api,
        world,
        session_start_at="2026-10-20T14:00:00Z",
        session_end_at="2026-10-20T15:00:00Z",
        slot_minutes_capacity=30,
    )
    version = api.read_panel_version(panel_id, world.officer)

    validate_error(
        api.reserve_slot(
            panel_id,
            factories.slot_payload(
                world.submission_id,
                version,
                start_at="2026-10-20T14:00:00Z",
                end_at="2026-10-20T15:00:00Z",
            ),
            world.officer,
        ),
        ApiErrorId.ERR_PANEL_CAPACITY_EXCEEDED,
        409,
    )

    panel = validate_success(api.get_committee_panel(panel_id, world.officer))
    assert panel["slot_minutes_capacity"] == 30
    assert panel["reserved_minutes"] == 0
