"""State-machine transitions: initial states, guarded edges, side effects and bubbles."""

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_instant_equals,
    assert_issue_dimensions,
    assert_issue_unit_ledgers,
    assert_print_run_quantities,
    assert_retailer_ledgers,
    factories,
    fixtures,
    validate_error,
    validate_success,
)
from test_helpers.test_users import TEST_USERS, make_creator_headers, make_retailer_headers

EIC = TEST_USERS["editor_in_chief_headers"]
ME = TEST_USERS["managing_editor_headers"]
SD = TEST_USERS["sales_director_headers"]

# Five back-to-back craft bookings for one all-craft creator. The half-open
# windows merely touch, so no booking intersects another, and the royalty shares
# sum to 5000 + 1500 + 800 + 700 + 500 = 8500 bps, exactly the non-cover budget
# left by the title's default 1500 bps cover participation.
CRAFT_TERMS = (
    ("SCRIPT", 12000, 5000, "2026-08-01", "2026-08-05"),
    ("PENCILS", 9000, 1500, "2026-08-05", "2026-08-10"),
    ("INKS", 7000, 800, "2026-08-10", "2026-08-15"),
    ("COLORS", 8000, 700, "2026-08-15", "2026-08-20"),
    ("LETTERS", 5000, 500, "2026-08-20", "2026-08-25"),
)

STANDARD_COVER_ONLY = (fixtures.DEFAULT_COVER_SPECS[0],)


def _title_staffed_for_every_craft(**title_overrides) -> dict:
    """A greenlit title whose five required crafts are all `ACCEPTED`."""
    fixtures.set_clock()
    creator = fixtures.register_all_craft_creator()
    title = fixtures.pitch_and_greenlight_title(**title_overrides)
    assignments = {}
    for craft, page_rate, share_bps, booking_start, booking_end in CRAFT_TERMS:
        assignments[craft] = fixtures.offer_and_accept_assignment(
            title["id"],
            creator["id"],
            craft,
            page_rate_cents=page_rate,
            royalty_share_bps=share_bps,
            booking_start_date=booking_start,
            booking_end_date=booking_end,
        )
    return {
        "creator": creator,
        "creator_headers": make_creator_headers(creator["id"]),
        "title": title,
        "assignments": assignments,
    }


def _issue_in_art_with_a_submitted_order_book() -> dict:
    """An issue whose production dimension sits in `ART`, listed with one order.

    All five required-craft stages are booked but only the `SCRIPT` stage is
    `APPROVED`, so the board has crossed into `ART` and stays there. The listing
    has been published, one retailer has submitted 100 standard copies, and the
    logical clock has reached the issue's `foc_date`.
    """
    state = _title_staffed_for_every_craft()
    issue = fixtures.schedule_issue(state["title"]["id"])
    stages = {}
    for craft, _rate, _share, _start, _end in CRAFT_TERMS:
        stages[craft] = fixtures.book_stage(
            issue["id"],
            state["assignments"][craft]["id"],
            craft,
            planned_start_date="2026-08-05",
            planned_due_date="2026-09-20",
        )
    fixtures.start_stage(stages["SCRIPT"]["id"], state["creator"]["id"])
    fixtures.deliver_stage(stages["SCRIPT"]["id"], state["creator"]["id"], 22)
    fixtures.approve_stage(stages["SCRIPT"]["id"])

    state.update(fixtures.solicit_issue(issue["id"], cover_specs=STANDARD_COVER_ONLY))
    retailer = fixtures.open_retailer()
    order = fixtures.draft_and_submit_order(retailer["id"], issue["id"], standard_qty=100)

    fixtures.set_clock("2026-09-23T00:00:00Z")
    state.update(
        {
            "stages": stages,
            "issue": fixtures.read_issue(issue["id"]),
            "retailer": retailer,
            "order": order,
        }
    )
    return state


def _printed_issue_of_a_single_issue_title() -> dict:
    """The one and only planned issue of a title, printed and waiting for release."""
    state = fixtures.setup_camera_ready_issue(
        title_overrides={"planned_issue_count": 1}
    )
    issue_id = state["issue"]["id"]

    state.update(fixtures.solicit_issue(issue_id, cover_specs=STANDARD_COVER_ONLY))
    retailer = fixtures.open_retailer()
    order = fixtures.draft_and_submit_order(retailer["id"], issue_id, standard_qty=100)

    fixtures.set_clock("2026-09-23T00:00:00Z")
    fixtures.foc_lock(issue_id)
    print_run = fixtures.plan_and_complete_print_run(issue_id)

    state.update(
        {
            "issue": fixtures.read_issue(issue_id),
            "retailer": retailer,
            "order": order,
            "print_run": print_run,
        }
    )
    return state


def _slipping_issue_with_an_accepted_and_a_draft_listing() -> dict:
    """One issue listed twice: `ACCEPTED` in a published catalog, `DRAFT` in the next.

    Its only `SCRIPT` stage is `IN_PROGRESS` and due 2026-09-01, so the delivery
    instant alone decides whether the slip cascade runs.
    """
    state = fixtures.setup_issue_in_scripting(
        stage_overrides={"planned_due_date": "2026-09-01"}
    )
    issue_id = state["issue"]["id"]
    covers = fixtures.add_covers(issue_id, STANDARD_COVER_ONLY)

    published_catalog = fixtures.open_catalog()
    accepted = fixtures.draft_solicitation(
        published_catalog["id"], issue_id, variant_cover_ids=[covers["A"]["id"]]
    )
    fixtures.submit_solicitation(accepted["id"])

    later_catalog = fixtures.open_catalog(
        solicitation_month="2026-09",
        submission_deadline="2026-09-25",
        on_sale_month="2026-11",
    )
    drafted = fixtures.draft_solicitation(
        later_catalog["id"], issue_id, variant_cover_ids=[covers["A"]["id"]]
    )

    fixtures.set_clock("2026-08-21T12:00:00Z")
    fixtures.lock_catalog(published_catalog["id"])
    fixtures.accept_solicitation(accepted["id"])
    fixtures.publish_catalog(published_catalog["id"])

    state.update(
        {
            "covers": covers,
            "published_catalog": fixtures.read_catalog(published_catalog["id"]),
            "later_catalog": fixtures.read_catalog(later_catalog["id"]),
            "accepted_solicitation": fixtures.read_solicitation(accepted["id"]),
            "draft_solicitation": fixtures.read_solicitation(drafted["id"]),
            "issue": fixtures.read_issue(issue_id),
        }
    )
    return state


# ═══════════════════════════════════════════════════════
# The greenlight edge out of PITCHED
# ═══════════════════════════════════════════════════════

def test_greenlight_advances_a_pitched_title_and_stamps_the_logical_clock():
    """The `PITCHED → GREENLIT` edge stamps `greenlit_at` and bumps the version once.

    PRD: "Greenlighting the title — available only from `PITCHED`, and reported as `ERR_INVALID_STATE` from anywhere else — advances it to `GREENLIT`, stamps `greenlit_at` with the logical clock and bumps the title's `version`."

    Design: Corner/state_machines/valid_transition_greenlight_moves_the_title_from_pitched_to_greenlit
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    pitched = fixtures.pitch_title()
    assert pitched["status"] == "PITCHED"
    assert pitched["greenlit_at"] is None

    greenlit = validate_success(api_client.greenlight_title(pitched["id"], EIC))

    assert greenlit["status"] == "GREENLIT"
    assert_instant_equals(greenlit["greenlit_at"], "2026-08-01T00:00:00Z")
    assert greenlit["version"] == pitched["version"] + 1
    # The transition touches no ledger of its own.
    assert greenlit["committed_share_bps"] == 0
    assert greenlit["production_cost_cents"] == 0
    assert greenlit["royalty_accrued_cents"] == 0
    assert greenlit["cancel_reason"] is None


def test_a_second_greenlight_is_refused_without_restamping_the_first_instant():
    """Re-sending the greenlight trigger is rejected rather than absorbed.

    PRD: "Greenlighting the title — available only from `PITCHED`, and reported as `ERR_INVALID_STATE` from anywhere else — advances it to `GREENLIT`, stamps `greenlit_at` with the logical clock and bumps the title's `version`."

    Design: Corner/state_machines/idempotency_second_greenlight_on_a_greenlit_title_is_rejected
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    title = fixtures.pitch_title()
    greenlit = fixtures.greenlight(title["id"])

    fixtures.set_clock("2026-08-05T00:00:00Z")
    response = api_client.greenlight_title(title["id"], EIC)
    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value)

    unchanged = fixtures.read_title(title["id"])
    assert unchanged["status"] == "GREENLIT"
    assert_instant_equals(unchanged["greenlit_at"], "2026-08-01T00:00:00Z")
    assert unchanged["version"] == greenlit["version"]


def test_a_second_cancellation_of_a_cancelled_title_is_refused():
    """`CANCELLED` is terminal, so the first `cancel_reason` survives the retry.

    PRD: "`COMPLETED` and `CANCELLED` are terminal for a title, and a second cancellation is refused as `ERR_INVALID_STATE`."

    Design: Corner/state_machines/terminal_state_lockdown_cancel_on_a_cancelled_title_is_rejected
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    title = fixtures.pitch_and_greenlight_title()

    cancelled = validate_success(
        api_client.cancel_title(
            title["id"],
            factories.title_cancel_payload(reason="line editor departed"),
            EIC,
        )
    )
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["cancel_reason"] == "line editor departed"

    response = api_client.cancel_title(
        title["id"], factories.title_cancel_payload(reason="second attempt"), EIC
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value)

    unchanged = fixtures.read_title(title["id"])
    assert unchanged["status"] == "CANCELLED"
    assert unchanged["cancel_reason"] == "line editor departed"
    assert unchanged["version"] == cancelled["version"]


# ═══════════════════════════════════════════════════════
# Declared initial states
# ═══════════════════════════════════════════════════════

def test_a_fresh_offer_starts_proposed_in_the_first_negotiation_round():
    """The offer arrives `PROPOSED` at round 1 with its advance wholly unrecouped.

    PRD: "A successful offer creates the assignment in status `PROPOSED` with `negotiation_round` at 1, `unrecouped_advance_cents` initialised to the same value as `advance_cents`, `counter_page_rate_cents`, `counter_royalty_share_bps` and `terminated_reason` all null, and it refreshes the creator's `active_assignment_count` as well as the title's `version`."

    Design: Corner/state_machines/initial_state_children_start_in_their_declared_initial_states
    """
    fixtures.set_clock()
    creator = fixtures.register_creator()
    title = fixtures.pitch_and_greenlight_title()

    assignment = validate_success(
        api_client.create_creative_assignment(
            title["id"],
            factories.assignment_payload(
                creator["id"],
                fixtures.title_version(title["id"]),
                craft="SCRIPT",
                advance_cents=25000,
            ),
            EIC,
        ),
        expected_status=201,
    )

    assert assignment["status"] == "PROPOSED"
    assert assignment["negotiation_round"] == 1
    assert assignment["advance_cents"] == 25000
    assert assignment["unrecouped_advance_cents"] == 25000
    assert assignment["counter_page_rate_cents"] is None
    assert assignment["counter_royalty_share_bps"] is None
    assert assignment["terminated_reason"] is None
    assert fixtures.read_creator(creator["id"])["active_assignment_count"] == 1


def test_a_newly_scheduled_issue_starts_planned_and_unsolicited():
    """Both dimensions and every derived counter of a new issue start at their floor.

    PRD: "A new issue starts with `production_status` `PLANNED`, `commercial_status` `UNSOLICITED`, `schedule_health` `ON_TRACK`, `total_slip_days`, `total_ordered_units`, `printed_units` and `shipped_units` all 0, and `on_sale_date` null."

    Design: Corner/state_machines/initial_state_children_start_in_their_declared_initial_states
    """
    fixtures.set_clock()
    title = fixtures.pitch_and_greenlight_title()

    issue = validate_success(
        api_client.create_issue(title["id"], factories.issue_payload(), ME),
        expected_status=201,
    )

    assert_issue_dimensions(
        issue,
        production_status="PLANNED",
        commercial_status="UNSOLICITED",
        schedule_health="ON_TRACK",
    )
    assert issue["total_slip_days"] == 0
    assert_issue_unit_ledgers(
        issue, total_ordered_units=0, printed_units=0, shipped_units=0
    )
    assert issue["on_sale_date"] is None


def test_a_booked_stage_starts_not_started_with_no_delivery_recorded():
    """A booking alone records no delivery, no slip, no kick-back and no page fee.

    PRD: "A booked stage arrives in status `NOT_STARTED` with `slip_days` 0, `kickback_count` 0, `page_fee_cents` 0, and `actual_delivered_at` and `delivered_pages` both null."

    Design: Corner/state_machines/initial_state_children_start_in_their_declared_initial_states
    """
    state = fixtures.setup_greenlit_title_with_script_assignment()
    issue = fixtures.schedule_issue(state["title"]["id"])

    stage = validate_success(
        api_client.create_production_stage(
            issue["id"],
            factories.stage_payload(state["assignment"]["id"], craft="SCRIPT"),
            ME,
        ),
        expected_status=201,
    )

    assert stage["status"] == "NOT_STARTED"
    assert stage["slip_days"] == 0
    assert stage["kickback_count"] == 0
    assert stage["page_fee_cents"] == 0
    assert stage["actual_delivered_at"] is None
    assert stage["delivered_pages"] is None
    assert fixtures.read_title(state["title"]["id"])["production_cost_cents"] == 0


def test_a_new_catalog_starts_open_with_no_slot_taken():
    """A catalog opens with an empty slate and no publication instant.

    PRD: "A new catalog is `OPEN` with `accepted_slot_count` 0 and `published_at` null."

    Design: Corner/state_machines/initial_state_children_start_in_their_declared_initial_states
    """
    fixtures.set_clock()

    catalog = validate_success(
        api_client.create_catalog(factories.catalog_payload(max_slots=5), SD),
        expected_status=201,
    )

    assert catalog["status"] == "OPEN"
    assert catalog["accepted_slot_count"] == 0
    assert catalog["published_at"] is None
    assert catalog["max_slots"] == 5


def test_a_new_retailer_account_starts_active_on_its_opening_units():
    """The account opens `ACTIVE`, unsuspended, with its tier read off its opening units.

    PRD: "A new account is `ACTIVE` with `suspension_reason` null, its `cumulative_units_ytd` equal to its `opening_units_ytd`, its `open_balance_cents` 0, and its `discount_tier` derived immediately from those opening units."

    Design: Corner/state_machines/initial_state_children_start_in_their_declared_initial_states
    """
    fixtures.set_clock()

    retailer = validate_success(
        api_client.create_retailer(
            factories.retailer_payload(opening_units_ytd=2500), SD
        ),
        expected_status=201,
    )

    assert retailer["status"] == "ACTIVE"
    assert retailer["suspension_reason"] is None
    assert_retailer_ledgers(
        retailer,
        cumulative_units_ytd=2500,
        open_balance_cents=0,
        discount_tier="BASIC",
    )


def test_a_drafted_order_starts_with_no_units_and_no_invoice_figures():
    """A drafted order has earned nothing and been billed nothing.

    PRD: "The draft arrives `DRAFT` with `total_units` 0, `earned_variant_allocations` empty, `discount_tier_applied` null, `merchandise_net_cents`, `handling_fee_cents` and `invoice_total_cents` all 0, and `cancel_reason` null."

    Design: Corner/state_machines/initial_state_children_start_in_their_declared_initial_states
    """
    fixtures.set_clock()
    title = fixtures.pitch_and_greenlight_title()
    issue = fixtures.schedule_issue(title["id"])
    retailer = fixtures.open_retailer()

    order = validate_success(
        api_client.create_retailer_order(
            factories.order_payload(retailer["id"], issue["id"], standard_qty=100),
            make_retailer_headers(retailer["id"]),
        ),
        expected_status=201,
    )

    assert order["status"] == "DRAFT"
    assert order["total_units"] == 0
    assert order["earned_variant_allocations"] == []
    assert order["discount_tier_applied"] is None
    assert order["merchandise_net_cents"] == 0
    assert order["handling_fee_cents"] == 0
    assert order["invoice_total_cents"] == 0
    assert order["cancel_reason"] is None


# ═══════════════════════════════════════════════════════
# Edges that do not exist, and preconditions on the ones that do
# ═══════════════════════════════════════════════════════

def test_approving_a_stage_that_was_never_delivered_is_refused():
    """`APPROVED` is reachable only from `DELIVERED`, so no page fee is ever frozen.

    PRD: "Editorial review of a delivery has two outcomes, both reserved to a `ManagingEditor` and both legal only from `DELIVERED`."

    Design: Corner/state_machines/invalid_transitions_approve_on_a_not_started_stage_is_rejected
    """
    state = fixtures.setup_issue_in_scripting(start_stage_work=False)
    assert state["stage"]["status"] == "NOT_STARTED"

    response = api_client.approve_production_stage(state["stage"]["id"], ME)
    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value)

    stage = fixtures.read_stage(state["stage"]["id"])
    assert stage["status"] == "NOT_STARTED"
    assert stage["page_fee_cents"] == 0
    assert fixtures.read_title(state["title"]["id"])["production_cost_cents"] == 0


def test_kicking_back_a_stage_that_was_never_delivered_is_refused():
    """A kick-back needs a delivery to reject, so the counter stays at zero.

    PRD: "Editorial review of a delivery has two outcomes, both reserved to a `ManagingEditor` and both legal only from `DELIVERED`."

    Design: Corner/state_machines/invalid_transitions_approve_on_a_not_started_stage_is_rejected
    """
    state = fixtures.setup_issue_in_scripting(start_stage_work=False)

    response = api_client.kick_back_production_stage(
        state["stage"]["id"], factories.kick_back_payload(note="too early"), ME
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value)

    stage = fixtures.read_stage(state["stage"]["id"])
    assert stage["status"] == "NOT_STARTED"
    assert stage["kickback_count"] == 0
    assert stage["actual_delivered_at"] is None


def test_delivering_more_pages_than_the_issue_carries_is_rejected():
    """Twenty-three pages against a twenty-two page issue is a malformed delivery.

    PRD: "The assigned creator delivers from `IN_PROGRESS`, reporting `delivered_pages`, which must be at least 1 and no greater than the issue's `page_count`; anything outside that range is `ERR_INVALID_REQUEST`."

    Design: Corner/state_machines/precondition_enforcement_delivered_pages_above_the_issue_page_count_is_rejected
    """
    state = fixtures.setup_issue_in_scripting()
    assert state["issue"]["page_count"] == 22

    response = api_client.deliver_production_stage(
        state["stage"]["id"],
        factories.deliver_payload(delivered_pages=23),
        state["creator_headers"],
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)

    stage = fixtures.read_stage(state["stage"]["id"])
    assert stage["status"] == "IN_PROGRESS"
    assert stage["delivered_pages"] is None
    assert stage["actual_delivered_at"] is None
    assert stage["slip_days"] == 0
    issue = fixtures.read_issue(state["issue"]["id"])
    assert issue["total_slip_days"] == 0
    assert_issue_dimensions(issue, schedule_health="ON_TRACK")


def test_delivering_zero_pages_is_rejected():
    """The lower bound of the delivery range is one page, not none.

    PRD: "The assigned creator delivers from `IN_PROGRESS`, reporting `delivered_pages`, which must be at least 1 and no greater than the issue's `page_count`; anything outside that range is `ERR_INVALID_REQUEST`."

    Design: Corner/state_machines/precondition_enforcement_delivered_pages_above_the_issue_page_count_is_rejected
    """
    state = fixtures.setup_issue_in_scripting()

    response = api_client.deliver_production_stage(
        state["stage"]["id"],
        factories.deliver_payload(delivered_pages=0),
        state["creator_headers"],
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)

    stage = fixtures.read_stage(state["stage"]["id"])
    assert stage["status"] == "IN_PROGRESS"
    assert stage["delivered_pages"] is None
    assert fixtures.read_issue(state["issue"]["id"])["total_slip_days"] == 0


# ═══════════════════════════════════════════════════════
# Approval's side effects
# ═══════════════════════════════════════════════════════

def test_stage_approval_freezes_the_page_fee_at_the_delivered_pages():
    """The fee is the assignment's page rate times the pages actually delivered.

    PRD: "An approval moves the stage `DELIVERED → APPROVED` and freezes its page fee: `page_fee_cents` becomes the referenced assignment's `page_rate_cents` at the moment of approval multiplied by the stage's `delivered_pages`, an exact integer product in cents."

    Design: Corner/state_machines/side_effect_execution_stage_approval_freezes_the_page_fee_and_completes_the_assignment
    """
    state = fixtures.setup_issue_in_scripting()
    fixtures.deliver_stage(state["stage"]["id"], state["creator"]["id"], 22)

    approved = validate_success(
        api_client.approve_production_stage(state["stage"]["id"], ME)
    )

    assert approved["status"] == "APPROVED"
    # 12000 cents per page across 22 delivered pages.
    assert approved["page_fee_cents"] == 264000
    assert approved["delivered_pages"] == 22
    # The delivery landed before its 2026-08-20 due date, so nothing slipped.
    assert approved["slip_days"] == 0
    assert_issue_dimensions(
        fixtures.read_issue(state["issue"]["id"]), schedule_health="ON_TRACK"
    )


def test_stage_approval_refreshes_the_title_production_cost_ledger():
    """The approved fee is the whole of the title's production cost.

    PRD: "The title's `production_cost_cents` is then refreshed as the sum of `page_fee_cents` over the approved stages of all that title's issues."

    Design: Corner/state_machines/side_effect_execution_stage_approval_freezes_the_page_fee_and_completes_the_assignment
    """
    state = fixtures.setup_issue_in_scripting()
    assert fixtures.read_title(state["title"]["id"])["production_cost_cents"] == 0

    fixtures.deliver_stage(state["stage"]["id"], state["creator"]["id"], 22)
    validate_success(api_client.approve_production_stage(state["stage"]["id"], ME))

    assert fixtures.read_title(state["title"]["id"])["production_cost_cents"] == 264000


def test_approving_the_last_stage_of_an_assignment_completes_the_engagement():
    """With every booked stage approved the assignment leaves the open set.

    PRD: "Approval also completes engagements: when every stage booked against the referenced assignment has reached `APPROVED`, that assignment moves `ACTIVE → COMPLETED` and the creator's `active_assignment_count` is recomputed."

    Design: Corner/state_machines/side_effect_execution_stage_approval_freezes_the_page_fee_and_completes_the_assignment
    """
    state = fixtures.setup_issue_in_scripting()
    assignment_id = state["assignment"]["id"]
    assert fixtures.read_assignment(assignment_id)["status"] == "ACTIVE"
    assert fixtures.read_creator(state["creator"]["id"])["active_assignment_count"] == 1

    fixtures.deliver_stage(state["stage"]["id"], state["creator"]["id"], 22)
    validate_success(api_client.approve_production_stage(state["stage"]["id"], ME))

    assert fixtures.read_assignment(assignment_id)["status"] == "COMPLETED"
    assert fixtures.read_creator(state["creator"]["id"])["active_assignment_count"] == 0


# ═══════════════════════════════════════════════════════
# Derived and cross-entity movement on the production board
# ═══════════════════════════════════════════════════════

def test_booking_the_first_stage_rederives_the_issue_production_dimension():
    """The compound dimension is recomputed from the stage set the booking created.

    PRD: "The issue advances `PLANNED → SCRIPTING` once it has at least one stage row and none of its `SCRIPT` stages has reached `APPROVED`."

    Design: Corner/state_machines/compound_issue_production_status_is_rederived_when_a_child_stage_starts
    """
    state = fixtures.setup_greenlit_title_with_script_assignment()
    issue = fixtures.schedule_issue(state["title"]["id"])
    before = fixtures.read_issue(issue["id"])
    assert_issue_dimensions(
        before, production_status="PLANNED", commercial_status="UNSOLICITED"
    )

    stage = validate_success(
        api_client.create_production_stage(
            issue["id"],
            factories.stage_payload(state["assignment"]["id"], craft="SCRIPT"),
            ME,
        ),
        expected_status=201,
    )
    assert stage["status"] == "NOT_STARTED"

    after = fixtures.read_issue(issue["id"])
    assert_issue_dimensions(
        after, production_status="SCRIPTING", commercial_status="UNSOLICITED"
    )
    assert after["version"] == before["version"] + 1

    # Starting the child leaves the derived value exactly where it already was.
    fixtures.start_stage(stage["id"], state["creator"]["id"])
    assert_issue_dimensions(
        fixtures.read_issue(issue["id"]),
        production_status="SCRIPTING",
        commercial_status="UNSOLICITED",
    )


def test_starting_a_stage_promotes_its_assignment_from_accepted_to_active():
    """One start mutates two rows: the stage and the assignment it was booked under.

    PRD: "A start moves the stage to `IN_PROGRESS`, promotes the assignment `ACCEPTED → ACTIVE` where applicable, and re-derives the issue's production dimension."

    Design: Corner/state_machines/cross_entity_stage_start_flips_the_assignment_from_accepted_to_active
    """
    state = fixtures.setup_issue_in_scripting(start_stage_work=False)
    before = fixtures.read_assignment(state["assignment"]["id"])
    assert before["status"] == "ACCEPTED"

    started = validate_success(
        api_client.start_production_stage(
            state["stage"]["id"], state["creator_headers"]
        )
    )
    assert started["status"] == "IN_PROGRESS"

    after = fixtures.read_assignment(state["assignment"]["id"])
    assert after["status"] == "ACTIVE"
    assert after["version"] == before["version"] + 1
    # Both `ACCEPTED` and `ACTIVE` are open states, so the derived count holds.
    assert fixtures.read_creator(state["creator"]["id"])["active_assignment_count"] == 1
    assert after["negotiation_round"] == 1


def test_the_cut_off_lock_moves_only_the_commercial_dimension():
    """The commercial edge fires while the production dimension stays in `ART`.

    PRD: "The two run independently, and exactly one operation in the entire system reads both dimensions of the same row: putting the issue on sale."

    Design: Corner/state_machines/parallel_production_and_commercial_dimensions_advance_independently
    """
    state = _issue_in_art_with_a_submitted_order_book()
    assert_issue_dimensions(
        state["issue"], production_status="ART", commercial_status="SOLICITED"
    )

    locked = validate_success(api_client.foc_lock_issue(state["issue"]["id"], SD))

    assert_issue_dimensions(
        locked,
        production_status="ART",
        commercial_status="FOC_LOCKED",
        schedule_health="ON_TRACK",
    )
    assert locked["total_slip_days"] == 0
    assert_issue_unit_ledgers(locked, total_ordered_units=100)

    order = fixtures.read_order(state["order"]["id"])
    assert order["status"] == "FOC_LOCKED"
    # Only a `STANDARD` cover is on the issue, and standard copies earn nothing.
    assert order["earned_variant_allocations"] == []
    assert order["total_units"] == 100


# ═══════════════════════════════════════════════════════
# Release, and the bubble up into the title
# ═══════════════════════════════════════════════════════

def test_release_moves_the_printed_issue_on_sale_and_stamps_the_clock():
    """The `PRINTED → ON_SALE` edge reads the production dimension and the clock.

    PRD: "A `SalesDirector` moves the issue `PRINTED → ON_SALE`, which requires the production dimension to be `CAMERA_READY` and requires the logical clock to have reached the issue's `target_on_sale_date`; an early release is refused with `ERR_ON_SALE_DATE_NOT_REACHED`."

    Design: Corner/state_machines/bubble_up_release_of_the_last_planned_issue_completes_the_title
    """
    state = _printed_issue_of_a_single_issue_title()
    assert_issue_dimensions(
        state["issue"], production_status="CAMERA_READY", commercial_status="PRINTED"
    )
    # 100 ordered copies plus eight percent overprint plus 150 reserve, rounded
    # up to a carton and then held at the 500-copy first-printing minimum.
    assert_print_run_quantities(
        state["print_run"], order_base_units=100, overprint_units=8, quantity=500
    )
    assert_issue_unit_ledgers(state["issue"], printed_units=500)

    fixtures.set_clock("2026-10-14T00:00:00Z")
    on_sale = validate_success(api_client.release_issue(state["issue"]["id"], SD))

    assert_issue_dimensions(
        on_sale, production_status="CAMERA_READY", commercial_status="ON_SALE"
    )
    assert_instant_equals(on_sale["on_sale_date"], "2026-10-14T00:00:00Z")


# ═══════════════════════════════════════════════════════
# The conditional slip cascade
# ═══════════════════════════════════════════════════════

def test_the_slip_cascade_withdraws_the_accepted_listing_and_spares_the_draft_one():
    """Thirty days of slip withdraws the `ACCEPTED` row while the `DRAFT` row stands.

    PRD: "Hop two, caused by the posture becoming `SLIPPED`, withdraws the book from the catalog: every solicitation of that issue whose status is `SUBMITTED` or `ACCEPTED` moves to `WITHDRAWN` with `withdrawn_reason` set to the literal string `AUTO_SLIP`, and the issue's commercial dimension returns to `UNSOLICITED` if it was `SOLICITED` or `FOC_LOCKED`."

    Design: Corner/state_machines/conditional_cascade_slip_withdrawal_skips_the_draft_solicitation
    """
    state = _slipping_issue_with_an_accepted_and_a_draft_listing()
    assert state["accepted_solicitation"]["status"] == "ACCEPTED"
    assert state["draft_solicitation"]["status"] == "DRAFT"
    assert_issue_dimensions(state["issue"], commercial_status="SOLICITED")

    # Due 2026-09-01 and delivered 2026-10-01 is thirty whole calendar days late.
    fixtures.set_clock("2026-10-01T00:00:00Z")
    validate_success(
        api_client.deliver_production_stage(
            state["stage"]["id"],
            factories.deliver_payload(delivered_pages=22),
            state["creator_headers"],
        )
    )

    stage = fixtures.read_stage(state["stage"]["id"])
    assert stage["slip_days"] == 30
    issue = fixtures.read_issue(state["issue"]["id"])
    assert issue["total_slip_days"] == 30
    assert_issue_dimensions(
        issue,
        production_status="SCRIPTING",
        commercial_status="UNSOLICITED",
        schedule_health="SLIPPED",
    )

    withdrawn = fixtures.read_solicitation(state["accepted_solicitation"]["id"])
    assert withdrawn["status"] == "WITHDRAWN"
    assert withdrawn["withdrawn_reason"] == "AUTO_SLIP"

    spared = fixtures.read_solicitation(state["draft_solicitation"]["id"])
    assert spared["status"] == "DRAFT"
    assert spared["withdrawn_reason"] is None


def test_the_slip_withdrawal_frees_the_slot_of_the_already_published_catalog():
    """The published catalog's slot count is recounted while the later one never moves.

    PRD: "A catalog's `accepted_slot_count` equals the count of that catalog's solicitations whose status is `ACCEPTED`; `DRAFT`, `SUBMITTED` and `WITHDRAWN` rows never occupy a slot."

    Design: Corner/state_machines/conditional_cascade_slip_withdrawal_skips_the_draft_solicitation
    """
    state = _slipping_issue_with_an_accepted_and_a_draft_listing()
    assert state["published_catalog"]["accepted_slot_count"] == 1
    assert state["published_catalog"]["status"] == "PUBLISHED"
    assert state["later_catalog"]["accepted_slot_count"] == 0

    fixtures.set_clock("2026-10-01T00:00:00Z")
    validate_success(
        api_client.deliver_production_stage(
            state["stage"]["id"],
            factories.deliver_payload(delivered_pages=22),
            state["creator_headers"],
        )
    )

    published = fixtures.read_catalog(state["published_catalog"]["id"])
    assert published["accepted_slot_count"] == 0
    # The cascade acts as the system, so publication is no shield.
    assert published["status"] == "PUBLISHED"

    later = fixtures.read_catalog(state["later_catalog"]["id"])
    assert later["accepted_slot_count"] == 0
    assert later["status"] == "OPEN"


# ═══════════════════════════════════════════════════════
# The retailer suspension round trip
# ═══════════════════════════════════════════════════════

def test_suspending_and_reinstating_a_retailer_round_trips_the_status():
    """Suspension captures its reason and reinstatement clears it back to null.

    PRD: "A `SalesDirector` may suspend an `ACTIVE` account, capturing the supplied `reason` into `suspension_reason`, and may reinstate a `SUSPENDED` one, which clears `suspension_reason` back to null."

    Design: Corner/state_machines/retailer_suspend_then_reinstate_round_trip_restores_the_active_state
    """
    fixtures.set_clock()
    retailer = fixtures.open_retailer(opening_units_ytd=2500)
    assert retailer["status"] == "ACTIVE"

    suspended = validate_success(
        api_client.suspend_retailer(
            retailer["id"],
            factories.suspend_payload(reason="aged balance under review"),
            SD,
        )
    )
    assert suspended["status"] == "SUSPENDED"
    assert suspended["suspension_reason"] == "aged balance under review"
    assert suspended["version"] == retailer["version"] + 1

    reinstated = validate_success(api_client.reinstate_retailer(retailer["id"], SD))
    assert reinstated["status"] == "ACTIVE"
    assert reinstated["suspension_reason"] is None
    assert reinstated["version"] == suspended["version"] + 1


def test_the_suspension_round_trip_leaves_every_retailer_ledger_untouched():
    """Neither hop of the round trip moves the units, the balance or the tier.

    PRD: "A suspended account keeps every ledger figure it had and keeps any orders already locked at cut-off, but it may neither submit new orders nor be invoiced, both refused with `ERR_RETAILER_NOT_ACTIVE`."

    Design: Corner/state_machines/retailer_suspend_then_reinstate_round_trip_restores_the_active_state
    """
    fixtures.set_clock()
    retailer = fixtures.open_retailer(opening_units_ytd=2500)
    assert_retailer_ledgers(
        retailer,
        cumulative_units_ytd=2500,
        open_balance_cents=0,
        discount_tier="BASIC",
    )

    suspended = fixtures.suspend_retailer(
        retailer["id"], reason="aged balance under review"
    )
    assert_retailer_ledgers(
        suspended,
        cumulative_units_ytd=2500,
        open_balance_cents=0,
        discount_tier="BASIC",
    )

    reinstated = fixtures.reinstate_retailer(retailer["id"])
    assert_retailer_ledgers(
        reinstated,
        cumulative_units_ytd=2500,
        open_balance_cents=0,
        discount_tier="BASIC",
    )
    assert reinstated["opening_units_ytd"] == 2500
