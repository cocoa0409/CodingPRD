"""Permits: the jurisdiction rule, the fee ladder and the mandated-alternate cascade."""

from test_helpers import (
    ApiErrorId,
    OFFICER_ALPHA,
    TEST_USERS,
    assert_instant_equals,
    assert_money,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
ESTIMATOR = TEST_USERS["estimator_headers"]
OFFICER = TEST_USERS["compliance_officer_headers"]


def _mandated_alternate_world():
    """An approved PRESSURE_TANK quote, a scheduled work order and a second FILED permit."""
    fixtures.set_clock("2026-06-01T09:00:00Z")
    world = fixtures.base_world(
        account_name="Stonefield Farms",
        email="ap@stonefield.example",
        membership_tier="NONE",
        address_line="40 Stonefield Rd",
        distance_miles=14.0,
        household_size=4,
        well_jurisdiction="JUR_CHARLIE",
        depth_feet=320.0,
        drawdown=8.0,
        technician_tier="MASTER",
        technician_name="Noor Haddad",
    )
    part_a = fixtures.new_part(
        "PT-22000", "PRESSURE_TANK", 22000, on_hand_qty=6, rated_drawdown_gallons=10.0
    )
    part_b = fixtures.new_part(
        "PT-26000", "PRESSURE_TANK", 26000, on_hand_qty=6, rated_drawdown_gallons=12.0
    )
    inspection = fixtures.completed_inspection(
        world["well_id"], world["technician_id"], "2026-06-01T10:00:00Z", 18.0, 55.0, 8.0
    )
    quote = fixtures.new_quote(
        world["property_id"],
        world["well_id"],
        inspection["id"],
        "PRESSURE_TANK",
        120,
        "2026-06-03T12:00:00Z",
        "MASTER",
    )
    line_a = fixtures.add_quote_line(quote["id"], part_a["id"], 1)["line_id"]

    permit_1 = fixtures.new_permit(
        world["well_id"], "JUR_CHARLIE", "PRESSURE_TANK", quote_id=quote["id"]
    )
    fixtures.file_permit(permit_1["id"])
    fixtures.approve_permit(permit_1["id"])

    fixtures.price_quote(quote["id"])
    fixtures.send_quote(quote["id"])
    fixtures.approve_quote(quote["id"], world["account_id"])

    # PRD 3.9 satisfies the scheduling permit prerequisite from "the scope needs
    # no permit at all", or an APPROVED permit whose *work_order_id* is this work
    # order.  The second route is closed here: permit_1 is already APPROVED for
    # PRESSURE_TANK on this well, and PRD 3.7 refuses to file any other permit
    # for the same well and the same scope, so no PRESSURE_TANK permit can ever
    # name this work order.  PRD 3.7 lists REPAIR among the scopes that need no
    # permit, and PRD 3.9 lets a work order carry any of the six scopes
    # independently of its quote's, so the work order books on the first route.
    work_order = fixtures.new_work_order(
        world["property_id"],
        world["well_id"],
        world["technician_id"],
        "REPAIR",
        quote_id=quote["id"],
    )
    fixtures.schedule_work_order(
        work_order["id"], "2026-06-03T12:00:00Z", "2026-06-03T16:00:00Z"
    )
    permit_2 = fixtures.new_permit(
        world["well_id"], "JUR_CHARLIE", "TREATMENT_INSTALL", quote_id=quote["id"]
    )
    fixtures.file_permit(permit_2["id"])

    world.update(
        {
            "part_b_id": part_b["id"],
            "quote_id": quote["id"],
            "line_a_id": line_a,
            "permit_2_id": permit_2["id"],
            "work_order_id": work_order["id"],
        }
    )
    return world


def test_approving_a_permit_with_conditions_supersedes_the_named_quote_line(api):
    """PRD 3.7: "Then: the permit stores `condition_text`, `mandated_alternate_part_id`
    and `superseded_quote_line_id` and moves to `APPROVED_WITH_CONDITIONS`; the named
    line moves `ACTIVE → SUPERSEDED` with `superseded_by_line_id` pointing at a
    brand-new line created on the same quote with `origin` `PERMIT_MANDATED_ALTERNATE`,
    `status` `ACTIVE`, the same `quantity`, `part_catalog_item_id` set to the mandated
    part and `unit_cost_cents_pinned` left null"
    PRD 3.7: "The base is multiplied by the scope multiplier and rounded half up to whole
    cents, and only then, when `expedited` is true, is the flat `EXPEDITE_FEE_CENTS` of
    15000 added."

    Design: Difficulty/transitive_cascade/permit_conditions_four_hop_cascade_holds_a_scheduled_work_order
    """
    world = _mandated_alternate_world()
    approved = validate_success(
        api.approve_permit(
            world["permit_2_id"],
            {
                "mandated_alternate_part_id": world["part_b_id"],
                "superseded_quote_line_id": world["line_a_id"],
                "condition_text": "Jurisdiction mandates the 12 gallon drawdown tank on this aquifer.",
            },
            OFFICER,
        )
    )
    assert approved["status"] == "APPROVED_WITH_CONDITIONS"
    assert_money(approved["fee_cents"], 9000, "Permit.fee_cents")

    alternates, _ = validate_paginated(
        api.list_quote_lines(
            ESTIMATOR,
            params={
                "quote_id": world["quote_id"],
                "origin": "PERMIT_MANDATED_ALTERNATE",
            },
        )
    )
    assert len(alternates) == 1
    alternate = alternates[0]
    assert alternate["quantity"] == 1
    assert alternate["origin"] == "PERMIT_MANDATED_ALTERNATE"

    superseded = fixtures.get_quote_line(world["line_a_id"])
    assert superseded["status"] == "SUPERSEDED"
    assert superseded["superseded_by_line_id"] == alternate["id"]


def test_the_mandated_alternate_reprices_the_quote_over_the_surviving_lines(api):
    """PRD 3.7: "and its subtotals, tax and `total_cents` are recomputed over the
    surviving `ACTIVE` lines, treating the un-pinned alternate at the catalog's *current*
    `unit_cost_cents`"
    PRD 3.6: "`permit_fee_cents` is the `fee_cents` of the permit raised from this quote
    whose `status` is `FILED`, `APPROVED` or `APPROVED_WITH_CONDITIONS`, taking the
    earliest such permit by `created_at`, and 0 when there is none."
    PRD 3.6: "On success the quote moves `SENT → APPROVED`, `approved_at` is stamped,
    `approved_total_cents` is latched from `total_cents`, and `version` rises by 1."

    Design: Difficulty/transitive_cascade/permit_conditions_four_hop_cascade_holds_a_scheduled_work_order
    """
    world = _mandated_alternate_world()
    before = fixtures.get_quote(world["quote_id"])
    assert_money(before["approved_total_cents"], 66033, "Quote.approved_total_cents")

    validate_success(
        api.approve_permit(
            world["permit_2_id"],
            {
                "mandated_alternate_part_id": world["part_b_id"],
                "superseded_quote_line_id": world["line_a_id"],
                "condition_text": "Jurisdiction mandates the 12 gallon drawdown tank on this aquifer.",
            },
            OFFICER,
        )
    )
    quote = fixtures.get_quote(world["quote_id"])
    assert_money(quote["parts_subtotal_cents"], 33280, "Quote.parts_subtotal_cents")
    assert_money(quote["permit_fee_cents"], 6000, "Quote.permit_fee_cents")
    assert_money(quote["tax_cents"], 2413, "Quote.tax_cents")
    assert_money(quote["total_cents"], 68693, "Quote.total_cents")
    assert_money(quote["approved_total_cents"], 66033, "Quote.approved_total_cents")

    work_order = fixtures.get_work_order(world["work_order_id"])
    assert work_order["billing_status"] == "NOT_BILLABLE"


def _permit_prerequisite_world():
    fixtures.set_clock("2026-06-01T09:00:00Z")
    world = fixtures.base_world(
        account_name="Kestrel Grove",
        email="ap@kestrel.example",
        membership_tier="NONE",
        account_jurisdiction="JUR_BRAVO",
        property_jurisdiction="JUR_BRAVO",
        well_jurisdiction="JUR_BRAVO",
        address_line="3 Kestrel Grove",
        distance_miles=13.0,
        household_size=4,
        depth_feet=210.0,
        drawdown=8.0,
        technician_name="Ines Duarte",
    )
    part = fixtures.new_part(
        "FIL-CARB-B", "FILTRATION", 20000, on_hand_qty=8, media_kind="CARBON"
    )
    inspection = fixtures.completed_inspection(
        world["well_id"], world["technician_id"], "2026-06-01T10:00:00Z", 13.0, 38.0, 8.0
    )
    staged = fixtures.priced_and_sent_quote(
        world["property_id"], world["well_id"], inspection["id"], part["id"], 1,
        "TREATMENT_INSTALL", 90, "2026-06-03T12:00:00Z", "JOURNEYMAN",
    )
    fixtures.approve_quote(staged["quote_id"], world["account_id"])
    work_order = fixtures.new_work_order(
        world["property_id"],
        world["well_id"],
        world["technician_id"],
        "TREATMENT_INSTALL",
        quote_id=staged["quote_id"],
    )
    permit = fixtures.new_permit(
        world["well_id"],
        "JUR_BRAVO",
        "TREATMENT_INSTALL",
        quote_id=staged["quote_id"],
        work_order_id=work_order["id"],
    )
    fixtures.file_permit(permit["id"])
    world.update({"work_order_id": work_order["id"], "permit_id": permit["id"]})
    return world


def test_scheduling_is_refused_while_the_permit_is_only_filed(api):
    """PRD 3.9: "The permit prerequisite is satisfied when the scope needs no permit at
    all, **or** a permit whose `work_order_id` is this work order is `APPROVED` or
    `APPROVED_WITH_CONDITIONS`, **or** the pipeline is `EMERGENCY` — emergency work is
    permit-exempt and schedules and completes with no permit whatsoever. Failing all
    three is `ERR_PERMIT_REQUIRED_NOT_APPROVED`."

    Design: Difficulty/cross_entity_state_dependency/work_order_schedule_depends_on_permit_status
    """
    world = _permit_prerequisite_world()
    validate_error(
        api.schedule_work_order(
            world["work_order_id"],
            {
                "scheduled_start_at": "2026-06-03T12:00:00Z",
                "scheduled_end_at": "2026-06-03T14:00:00Z",
            },
            DISPATCHER,
        ),
        ApiErrorId.ERR_PERMIT_REQUIRED_NOT_APPROVED.value,
        422,
    )
    work_order = fixtures.get_work_order(world["work_order_id"])
    assert work_order["fulfillment_status"] == "DRAFT"
    assert work_order["scheduled_start_at"] is None


def test_the_same_schedule_request_succeeds_once_the_permit_is_approved(api):
    """PRD 3.7: "With no `mandated_alternate_part_id` in the body, the permit simply moves
    `FILED → APPROVED` and its `version` rises by 1."
    PRD 3.7: "The base fees are 35000 cents for `TIER_A`, 22000 for `TIER_B` and 12000
    for `TIER_C`. The scope multipliers are 3.0 for `NEW_WELL`, 1.0 for
    `PUMP_REPLACEMENT`, 0.5 for `PRESSURE_TANK`, 0.75 for `TREATMENT_INSTALL` and 0.0 for
    `REPAIR`."
    PRD 3.9: "Scheduling stores `scheduled_start_at` and `scheduled_end_at`, clears
    `hold_reason` and raises `version` by 1."

    Design: Difficulty/cross_entity_state_dependency/work_order_schedule_depends_on_permit_status
    """
    world = _permit_prerequisite_world()
    api.schedule_work_order(
        world["work_order_id"],
        {
            "scheduled_start_at": "2026-06-03T12:00:00Z",
            "scheduled_end_at": "2026-06-03T14:00:00Z",
        },
        DISPATCHER,
    )
    approved = validate_success(api.approve_permit(world["permit_id"], {}, OFFICER))
    assert approved["status"] == "APPROVED"
    assert_money(approved["fee_cents"], 16500, "Permit.fee_cents")

    scheduled = validate_success(
        api.schedule_work_order(
            world["work_order_id"],
            {
                "scheduled_start_at": "2026-06-03T12:00:00Z",
                "scheduled_end_at": "2026-06-03T14:00:00Z",
            },
            DISPATCHER,
        )
    )
    assert scheduled["fulfillment_status"] == "SCHEDULED"
    assert_instant_equals(
        scheduled["scheduled_start_at"],
        "2026-06-03T12:00:00Z",
        "WorkOrder.scheduled_start_at",
    )


def test_a_rejected_permit_returns_to_draft_and_can_be_filed_again(api):
    """PRD 3.7: "A `FILED` permit may be **rejected**, which moves it to `REJECTED` with
    `version` up by 1, and a `REJECTED` permit may be returned to `DRAFT` by the refile
    capability, which clears `filed_at` back to null and resets `fee_cents` to 0 with
    `version` up by 1 — closing the draft-file-reject-draft cycle."
    PRD 3.7: "Filing stores `jurisdiction_tier` and `fee_cents`, stamps `filed_at` and
    raises `version` by 1."

    Design: Corner/state_machines/corner_permit_reject_then_refile_draft_completes_the_cycle
    """
    fixtures.set_clock("2026-06-01T09:00:00Z")
    account = fixtures.new_account("Refile Co", "JUR_BRAVO", "rf@corner.example")
    prop = fixtures.new_property(account["id"], "3 Refile", "JUR_BRAVO", 10.0, 2)
    well = fixtures.new_well(prop["id"], "JUR_ALPHA", "DRILLED", 200.0)
    permit = fixtures.new_permit(well["id"], "JUR_ALPHA", "PUMP_REPLACEMENT")
    fixtures.file_permit(permit["id"])
    validate_success(api.reject_permit(permit["id"], OFFICER))

    drafted = validate_success(api.refile_permit_draft(permit["id"], OFFICER))
    assert drafted["status"] == "DRAFT"
    assert drafted["filed_at"] is None
    assert_money(drafted["fee_cents"], 0, "Permit.fee_cents")

    refiled = validate_success(api.file_permit(permit["id"], OFFICER))
    assert refiled["status"] == "FILED"
    assert refiled["jurisdiction_tier"] == "TIER_A"
    assert_money(refiled["fee_cents"], 35000, "Permit.fee_cents")
    assert_instant_equals(
        refiled["filed_at"], "2026-06-01T09:00:00Z", "Permit.filed_at"
    )


def test_a_withdrawn_permit_is_terminal(api):
    """PRD 3.7: "A `FILED` permit may also be **withdrawn**, moving it to `WITHDRAWN` with
    `version` up by 1."
    PRD 3.7: "The lifecycle is `DRAFT`, `FILED`, `APPROVED`, `APPROVED_WITH_CONDITIONS`,
    `REJECTED` and `WITHDRAWN`, with `APPROVED`, `APPROVED_WITH_CONDITIONS` and
    `WITHDRAWN` terminal; a transition from the wrong state is `ERR_PERMIT_INVALID_STATE`."
    PRD 3.7: "A `JUR_ALPHA` new well not expedited is 105000; a `JUR_CHARLIE` treatment
    install, expedited, is 9000 plus 15000 for 24000; a `JUR_BRAVO` pressure tank not
    expedited is 11000."

    Design: Corner/state_machines/corner_permit_withdraw_from_filed_is_terminal
    """
    fixtures.set_clock("2026-06-01T09:00:00Z")
    account = fixtures.new_account("Withdraw Co", "JUR_CHARLIE", "wd@corner.example")
    prop = fixtures.new_property(account["id"], "4 Withdraw", "JUR_CHARLIE", 10.0, 2)
    well = fixtures.new_well(prop["id"], "JUR_CHARLIE", "DRILLED", 200.0)
    permit = fixtures.new_permit(
        well["id"], "JUR_CHARLIE", "PRESSURE_TANK", expedited=True
    )
    fixtures.file_permit(permit["id"])

    withdrawn = validate_success(api.withdraw_permit(permit["id"], OFFICER))
    assert withdrawn["status"] == "WITHDRAWN"
    assert_money(withdrawn["fee_cents"], 21000, "Permit.fee_cents")

    validate_error(
        api.approve_permit(permit["id"], {}, OFFICER),
        ApiErrorId.ERR_PERMIT_INVALID_STATE.value,
        409,
    )


def test_the_permit_fee_reads_the_wells_jurisdiction_not_the_accounts(api):
    """PRD 3.7: "The fee follows the **well's** jurisdiction tier. `JUR_ALPHA` is
    `TIER_A`, `JUR_BRAVO` is `TIER_B`, `JUR_CHARLIE` is `TIER_C` and `JUR_DELTA` is
    `TIER_B`."
    PRD 3.7: "A `JUR_ALPHA` new well not expedited is 105000; a `JUR_CHARLIE` treatment
    install, expedited, is 9000 plus 15000 for 24000; a `JUR_BRAVO` pressure tank not
    expedited is 11000."

    Design: Corner/calculations/corner_calc_permit_fee_follows_the_well_jurisdiction_tier_and_scope_multiplier
    """
    fixtures.set_clock("2026-06-01T09:00:00Z")
    account = fixtures.new_account("Permit Tier Co", "JUR_ALPHA", "pt@corner.example")
    prop = fixtures.new_property(account["id"], "4 Tier", "JUR_ALPHA", 10.0, 3)

    cases = [
        ("JUR_ALPHA", "NEW_WELL", False, "TIER_A", 105000),
        ("JUR_BRAVO", "PRESSURE_TANK", False, "TIER_B", 11000),
        ("JUR_CHARLIE", "TREATMENT_INSTALL", True, "TIER_C", 24000),
        ("JUR_DELTA", "PUMP_REPLACEMENT", False, "TIER_B", 22000),
    ]
    first_filed = None
    for jurisdiction, scope, expedited, tier, fee in cases:
        well = fixtures.new_well(prop["id"], jurisdiction, "DRILLED", 200.0)
        permit = fixtures.new_permit(well["id"], jurisdiction, scope, expedited=expedited)
        filed = validate_success(api.file_permit(permit["id"], OFFICER))
        assert filed["jurisdiction_tier"] == tier
        assert_money(filed["fee_cents"], fee, "Permit.fee_cents")
        if first_filed is None:
            first_filed = filed

    assert first_filed["status"] == "FILED"
    assert_instant_equals(
        first_filed["filed_at"], "2026-06-01T09:00:00Z", "Permit.filed_at"
    )


def test_permit_filing_gates_reject_a_wrong_jurisdiction_and_a_duplicate(api):
    """PRD 3.7: "The permit's `jurisdiction_code` must equal the **well's**
    `jurisdiction_code` — not the property's and emphatically not the account's
    `billing_jurisdiction_code` — or the filing is refused with
    `ERR_PERMIT_JURISDICTION_MISMATCH`."
    PRD 3.7: "And no other permit for the same well and the same scope may already be
    `FILED`, `APPROVED` or `APPROVED_WITH_CONDITIONS`, or the filing is refused with
    `ERR_PERMIT_ALREADY_ON_FILE`."

    Design: Corner/errors/corner_permit_family_gates_rejected
    """
    fixtures.set_clock("2026-06-01T09:00:00Z")
    account = fixtures.new_account("Jurisdiction Co", "JUR_BRAVO", "ju@corner.example")
    prop = fixtures.new_property(account["id"], "5 Jurisdiction", "JUR_BRAVO", 10.0, 3)
    well = fixtures.new_well(prop["id"], "JUR_CHARLIE", "DRILLED", 200.0)

    permit_bad = fixtures.new_permit(well["id"], "JUR_BRAVO", "PUMP_REPLACEMENT")
    permit_ok = fixtures.new_permit(well["id"], "JUR_CHARLIE", "PUMP_REPLACEMENT")
    permit_dup = fixtures.new_permit(well["id"], "JUR_CHARLIE", "PUMP_REPLACEMENT")

    validate_error(
        api.file_permit(permit_bad["id"], OFFICER),
        ApiErrorId.ERR_PERMIT_JURISDICTION_MISMATCH.value,
        422,
    )
    assert fixtures.get_permit(permit_bad["id"])["status"] == "DRAFT"

    filed = validate_success(api.file_permit(permit_ok["id"], OFFICER))
    assert filed["status"] == "FILED"
    assert filed["jurisdiction_tier"] == "TIER_C"
    assert_money(filed["fee_cents"], 12000, "Permit.fee_cents")

    validate_error(
        api.file_permit(permit_dup["id"], OFFICER),
        ApiErrorId.ERR_PERMIT_ALREADY_ON_FILE.value,
        409,
    )
    assert fixtures.get_permit(permit_dup["id"])["status"] == "DRAFT"


def test_a_post_hoc_permit_filed_past_its_window_is_refused(api):
    """PRD 3.7: "When `post_hoc` is true the linked work order must be `COMPLETED` and the
    elapsed time from its `actual_end_at` to the logical clock must be at most
    `POST_HOC_PERMIT_WINDOW_DAYS` (10 days), right-closed, or the filing is refused with
    `ERR_POST_HOC_PERMIT_WINDOW_EXPIRED`."
    PRD 3.7: "`fee_cents` starts 0, `filed_at`, `jurisdiction_tier`,
    `mandated_alternate_part_id`, `superseded_quote_line_id` and `condition_text` all
    start null."

    Design: Corner/errors/corner_post_hoc_permit_window_expired_rejected
    """
    fixtures.set_clock("2026-06-01T09:00:00Z")
    world = fixtures.base_world(
        account_name="Posthoc Co",
        email="ph@corner.example",
        address_line="11 Posthoc",
        technician_tier="MASTER",
        technician_name="Posthoc Tech",
    )
    stage = fixtures.completed_emergency_work_order(
        world,
        part_id=None,
        actual_labor_minutes=60,
        cause_class="PUMP_FAILURE",
        onsite_estimate_cents=20000,
        scope="PUMP_REPLACEMENT",
    )
    permit = fixtures.new_permit(
        world["well_id"],
        "JUR_ALPHA",
        "PUMP_REPLACEMENT",
        work_order_id=stage["work_order_id"],
        post_hoc=True,
    )
    fixtures.set_clock("2026-06-12T12:00:00Z")

    validate_error(
        api.file_permit(permit["id"], OFFICER),
        ApiErrorId.ERR_POST_HOC_PERMIT_WINDOW_EXPIRED.value,
        422,
    )
    stored = fixtures.get_permit(permit["id"])
    assert stored["status"] == "DRAFT"
    assert_money(stored["fee_cents"], 0, "Permit.fee_cents")
    assert_instant_equals(
        fixtures.get_work_order(stage["work_order_id"])["actual_end_at"],
        "2026-06-01T12:00:00Z",
        "WorkOrder.actual_end_at",
    )


def test_a_mandated_alternate_of_the_wrong_category_is_refused(api):
    """PRD 3.7: "the named part must exist, must be `ACTIVE` and must share the superseded
    line's part `category`, or the approval is refused with `ERR_PART_CATEGORY_MISMATCH`."

    Design: Corner/errors/corner_permit_mandated_alternate_category_mismatch_rejected
    """
    fixtures.set_clock("2026-06-01T09:00:00Z")
    world = fixtures.base_world(
        account_name="Mismatch Co",
        email="mm@corner.example",
        account_jurisdiction="JUR_CHARLIE",
        property_jurisdiction="JUR_CHARLIE",
        well_jurisdiction="JUR_CHARLIE",
        address_line="13 Mismatch",
        technician_tier="MASTER",
        technician_name="Mismatch Tech",
    )
    tank = fixtures.new_part(
        "PT-18000", "PRESSURE_TANK", 18000, on_hand_qty=5, rated_drawdown_gallons=10.0
    )
    control = fixtures.new_part("CTL-9500", "CONTROL", 9500, on_hand_qty=5)
    inspection = fixtures.completed_inspection(
        world["well_id"], world["technician_id"], "2026-06-01T10:00:00Z", 15.0, 40.0, 8.0
    )
    quote = fixtures.new_quote(
        world["property_id"],
        world["well_id"],
        inspection["id"],
        "PRESSURE_TANK",
        120,
        "2026-06-03T12:00:00Z",
        "MASTER",
    )
    line_id = fixtures.add_quote_line(quote["id"], tank["id"], 1)["line_id"]
    permit = fixtures.new_permit(
        world["well_id"], "JUR_CHARLIE", "PRESSURE_TANK", quote_id=quote["id"]
    )
    fixtures.file_permit(permit["id"])

    validate_error(
        api.approve_permit(
            permit["id"],
            {
                "mandated_alternate_part_id": control["id"],
                "superseded_quote_line_id": line_id,
                "condition_text": "Wrong category alternate",
            },
            OFFICER,
        ),
        ApiErrorId.ERR_PART_CATEGORY_MISMATCH.value,
        422,
    )
    assert fixtures.get_permit(permit["id"])["status"] == "FILED"
    assert fixtures.get_quote_line(line_id)["status"] == "ACTIVE"
    assert fixtures.get_quote(quote["id"])["status"] == "DRAFT"
