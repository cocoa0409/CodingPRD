"""Error contract: identity, resource resolution and the creative/production refusals."""

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    api_client,
    assert_instant_equals,
    assert_invoice_figures,
    assert_issue_dimensions,
    assert_issue_unit_ledgers,
    assert_retailer_ledgers,
    assert_statement_money,
    assert_version_unchanged,
    build_user_headers,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.test_users import (
    EDITOR_IN_CHIEF_USER_ID,
    TEST_USERS,
    make_retailer_headers,
)

EIC = TEST_USERS["editor_in_chief_headers"]
ME = TEST_USERS["managing_editor_headers"]
SD = TEST_USERS["sales_director_headers"]
RA = TEST_USERS["royalty_accountant_headers"]

# Well-formed bodies sent with a broken identity pair.
NO_ROLE_HEADERS = {
    "X-User-ID": EDITOR_IN_CHIEF_USER_ID,
    "Content-Type": "application/json",
}
NO_USER_ID_HEADERS = {"X-User-Role": "EditorInChief", "Content-Type": "application/json"}
UNKNOWN_ROLE_HEADERS = build_user_headers("pub-1", "Publisher")

# Five back-to-back craft bookings for one all-craft creator. The shares sum to
# 5000 + 1500 + 800 + 700 + 500 = 8500 bps, exactly the non-cover budget left by
# the title's default 1500 bps cover participation.
CRAFT_TERMS = (
    ("SCRIPT", 12000, 5000, "2026-08-01", "2026-08-05"),
    ("PENCILS", 9000, 1500, "2026-08-05", "2026-08-10"),
    ("INKS", 7000, 800, "2026-08-10", "2026-08-15"),
    ("COLORS", 8000, 700, "2026-08-15", "2026-08-20"),
    ("LETTERS", 5000, 500, "2026-08-20", "2026-08-25"),
)

# Only the standard cover the catalog prints, so an order earns no incentives.
STANDARD_ONLY_COVERS = (fixtures.DEFAULT_COVER_SPECS[0],)


def _build_issue_board(approve_letters: bool = True) -> dict:
    """A greenlit title with one issue carrying all five required-craft stages.

    Every stage lands well inside its planned due date, so no slip is measured.
    With `approve_letters` false the letters stage stops at `DELIVERED`, which
    holds the issue's production dimension at `PREPRESS`.
    """
    fixtures.set_clock()
    creator = fixtures.register_all_craft_creator()
    title = fixtures.pitch_and_greenlight_title()
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
    issue = fixtures.schedule_issue(title["id"], target_on_sale_date="2026-10-14")

    stages = {}
    for craft, _rate, _bps, _start, _end in CRAFT_TERMS:
        if craft == "LETTERS" and not approve_letters:
            stage = fixtures.book_stage(
                issue["id"],
                assignments[craft]["id"],
                craft,
                planned_start_date="2026-08-05",
                planned_due_date="2026-09-20",
            )
            fixtures.start_stage(stage["id"], creator["id"])
            stages[craft] = fixtures.deliver_stage(stage["id"], creator["id"])
        else:
            stages[craft] = fixtures.run_stage_to_approved(
                issue["id"],
                assignments[craft]["id"],
                creator["id"],
                craft=craft,
                planned_start_date="2026-08-05",
                planned_due_date="2026-09-20",
            )

    return {
        "creator": creator,
        "title": fixtures.read_title(title["id"]),
        "assignments": assignments,
        "stages": stages,
        "issue": fixtures.read_issue(issue["id"]),
    }


def _lock_the_order_book(state: dict, standard_qty: int = 100) -> dict:
    """Solicit the issue, submit one order and freeze it at the cut-off.

    The issue's `foc_date` is 2026-09-23, twenty-one days before its 2026-10-14
    on-sale date, and the clock is left standing on it.
    """
    issue_id = state["issue"]["id"]
    state.update(fixtures.solicit_issue(issue_id, cover_specs=STANDARD_ONLY_COVERS))
    retailer = fixtures.open_retailer()
    order = fixtures.draft_and_submit_order(
        retailer["id"], issue_id, standard_qty=standard_qty
    )
    fixtures.set_clock("2026-09-23T00:00:00Z")
    fixtures.foc_lock(issue_id)
    state.update(
        {
            "retailer": fixtures.read_retailer(retailer["id"]),
            "order": fixtures.read_order(order["id"]),
            "issue": fixtures.read_issue(issue_id),
        }
    )
    return state


# ─── Identity headers ─────────────────────────────────

def test_pitching_a_title_with_an_incomplete_identity_pair_is_unauthenticated():
    """A missing `X-User-Role`, and a missing `X-User-ID`, are both 401 refusals.

    PRD: "If either header is absent, or if `X-User-Role` is not one of the six declared roles, the request is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/errors/err_unauthenticated_missing_or_unknown_role_header_is_rejected
    """
    fixtures.set_clock()
    payload = factories.title_payload(name="Nebula Knights")

    validate_error(
        api_client.create_title(payload, NO_ROLE_HEADERS),
        ApiErrorId.ERR_UNAUTHENTICATED.value,
    )
    validate_error(
        api_client.create_title(payload, NO_USER_ID_HEADERS),
        ApiErrorId.ERR_UNAUTHENTICATED.value,
    )

    rows, meta = validate_paginated(
        api_client.list_titles(EIC, params={"limit": 100, "offset": 0})
    )
    assert meta["total_count"] == 0, "no Title row may survive a 401 refusal"
    assert rows == []


def test_pitching_a_title_under_a_role_outside_the_six_is_unauthenticated():
    """A role name the system does not declare fails authentication, not authorization.

    PRD: "If either header is absent, or if `X-User-Role` is not one of the six declared roles, the request is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/errors/err_unauthenticated_missing_or_unknown_role_header_is_rejected
    """
    fixtures.set_clock()

    response = api_client.create_title(
        factories.title_payload(name="Nebula Knights"), UNKNOWN_ROLE_HEADERS
    )
    error = validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value)
    assert error["message"].strip() != ""
    assert response.json()["response_type"] == "error"

    rows, meta = validate_paginated(
        api_client.list_titles(EIC, params={"limit": 100, "offset": 0})
    )
    assert meta["total_count"] == 0
    assert rows == []


# ─── Resource resolution ──────────────────────────────

def test_each_absent_resource_family_reports_its_own_not_found_code():
    """Eleven unresolvable path identifiers return eleven distinct 404 codes.

    PRD: "Each identifier has its own 404 code — `ERR_TITLE_NOT_FOUND`, `ERR_ISSUE_NOT_FOUND`, `ERR_CREATOR_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_STAGE_NOT_FOUND`, `ERR_CATALOG_NOT_FOUND`, `ERR_SOLICITATION_NOT_FOUND`, `ERR_RETAILER_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_PRINT_RUN_NOT_FOUND` and `ERR_STATEMENT_NOT_FOUND` — and the code reported is the one belonging to the leftmost missing segment."

    Design: Corner/errors/err_not_found_family_returns_the_resource_specific_error_id
    """
    fixtures.set_clock()

    cases = (
        (api_client.get_title(NON_EXISTENT_UUID, EIC), ApiErrorId.ERR_TITLE_NOT_FOUND),
        (api_client.get_issue(NON_EXISTENT_UUID, ME), ApiErrorId.ERR_ISSUE_NOT_FOUND),
        (api_client.get_creator(NON_EXISTENT_UUID, EIC), ApiErrorId.ERR_CREATOR_NOT_FOUND),
        (
            api_client.get_creative_assignment(NON_EXISTENT_UUID, ME),
            ApiErrorId.ERR_ASSIGNMENT_NOT_FOUND,
        ),
        (
            api_client.get_production_stage(NON_EXISTENT_UUID, ME),
            ApiErrorId.ERR_STAGE_NOT_FOUND,
        ),
        (api_client.get_catalog(NON_EXISTENT_UUID, SD), ApiErrorId.ERR_CATALOG_NOT_FOUND),
        (
            api_client.get_solicitation(NON_EXISTENT_UUID, SD),
            ApiErrorId.ERR_SOLICITATION_NOT_FOUND,
        ),
        (api_client.get_retailer(NON_EXISTENT_UUID, SD), ApiErrorId.ERR_RETAILER_NOT_FOUND),
        (
            api_client.get_retailer_order(NON_EXISTENT_UUID, SD),
            ApiErrorId.ERR_ORDER_NOT_FOUND,
        ),
        (
            api_client.get_print_run(NON_EXISTENT_UUID, ME),
            ApiErrorId.ERR_PRINT_RUN_NOT_FOUND,
        ),
        (
            api_client.get_royalty_statement(NON_EXISTENT_UUID, RA),
            ApiErrorId.ERR_STATEMENT_NOT_FOUND,
        ),
    )
    assert len({expected for _response, expected in cases}) == len(cases)
    for response, expected in cases:
        validate_error(response, expected.value)


def test_a_body_referenced_creator_that_does_not_exist_reports_creator_not_found():
    """An offer naming an unknown `creator_id` is refused even though the path resolves.

    PRD: "Identifiers named in a request body must resolve, each reporting its own code: `creator_id` yields `ERR_CREATOR_NOT_FOUND`, `assignment_id` yields `ERR_ASSIGNMENT_NOT_FOUND`, `issue_id` yields `ERR_ISSUE_NOT_FOUND`, `retailer_id` yields `ERR_RETAILER_NOT_FOUND`, `title_id` yields `ERR_TITLE_NOT_FOUND`, and a member of `variant_cover_ids` that does not exist, or that belongs to a different issue than the one being solicited, yields `ERR_VARIANT_COVER_NOT_FOUND`."

    Design: Corner/errors/err_not_found_family_returns_the_resource_specific_error_id
    """
    fixtures.set_clock()
    title = fixtures.pitch_and_greenlight_title()

    response = api_client.create_creative_assignment(
        title["id"],
        factories.assignment_payload(NON_EXISTENT_UUID, title["version"]),
        EIC,
    )
    validate_error(response, ApiErrorId.ERR_CREATOR_NOT_FOUND.value)

    unchanged = fixtures.read_title(title["id"])
    assert_version_unchanged(title, unchanged)
    assert unchanged["committed_share_bps"] == 0
    rows, meta = validate_paginated(
        api_client.list_title_assignments(title["id"], EIC, params={"limit": 100})
    )
    assert meta["total_count"] == 0
    assert rows == []


# ─── Retailer suspension ──────────────────────────────

def test_a_suspended_account_may_not_submit_its_drafted_order():
    """Suspension stops a `DRAFT` order from reaching the market.

    PRD: "A suspended account keeps every ledger figure it had and keeps any orders already locked at cut-off, but it may neither submit new orders nor be invoiced, both refused with `ERR_RETAILER_NOT_ACTIVE`."

    Design: Corner/errors/err_retailer_not_active_blocks_both_order_submission_and_invoicing
    """
    state = fixtures.setup_solicited_issue_in_scripting(
        cover_specs=STANDARD_ONLY_COVERS
    )
    retailer = fixtures.open_retailer()
    order = fixtures.draft_order(retailer["id"], state["issue"]["id"], standard_qty=50)
    suspended = fixtures.suspend_retailer(retailer["id"], reason="under audit")
    assert suspended["status"] == "SUSPENDED"

    response = api_client.submit_retailer_order(
        order["id"], make_retailer_headers(retailer["id"])
    )
    validate_error(response, ApiErrorId.ERR_RETAILER_NOT_ACTIVE.value)

    unchanged = fixtures.read_order(order["id"])
    assert unchanged["status"] == "DRAFT"
    assert_version_unchanged(order, unchanged)
    assert_retailer_ledgers(
        fixtures.read_retailer(retailer["id"]),
        cumulative_units_ytd=0,
        open_balance_cents=0,
    )
    assert_issue_unit_ledgers(
        fixtures.read_issue(state["issue"]["id"]), total_ordered_units=0
    )


def test_a_suspended_account_may_not_be_invoiced_for_its_locked_order():
    """Suspension after the cut-off leaves the locked order uninvoiced.

    PRD: "A suspended account keeps every ledger figure it had and keeps any orders already locked at cut-off, but it may neither submit new orders nor be invoiced, both refused with `ERR_RETAILER_NOT_ACTIVE`."

    Design: Corner/errors/err_retailer_not_active_blocks_both_order_submission_and_invoicing
    """
    state = fixtures.setup_locked_order_book()
    order = state["order"]
    retailer_id = state["retailer"]["id"]
    assert order["status"] == "FOC_LOCKED"
    fixtures.suspend_retailer(retailer_id, reason="aged balance")

    response = api_client.invoice_retailer_order(order["id"], SD)
    validate_error(response, ApiErrorId.ERR_RETAILER_NOT_ACTIVE.value)

    unchanged = fixtures.read_order(order["id"])
    assert unchanged["status"] == "FOC_LOCKED"
    assert unchanged["discount_tier_applied"] is None
    assert_invoice_figures(
        unchanged,
        merchandise_net_cents=0,
        handling_fee_cents=0,
        invoice_total_cents=0,
    )
    assert_retailer_ledgers(
        fixtures.read_retailer(retailer_id),
        cumulative_units_ytd=order["total_units"],
        open_balance_cents=0,
    )
    assert_issue_unit_ledgers(
        fixtures.read_issue(state["issue"]["id"]),
        total_ordered_units=order["total_units"],
    )


# ─── Non-returnable trade terms ───────────────────────

def test_cancelling_a_shipped_order_is_refused_as_a_returns_violation():
    """A `SHIPPED` order reports the trade-terms refusal, not a generic state error.

    PRD: "Once an order has shipped it is final: no cancellation, credit or return is possible, and an attempt is rejected with `ERR_RETURNS_NOT_PERMITTED`."

    Design: Corner/errors/err_returns_not_permitted_a_shipped_order_can_never_be_cancelled
    """
    state = _lock_the_order_book(_build_issue_board())
    order_id = state["order"]["id"]
    fixtures.plan_and_complete_print_run(state["issue"]["id"])
    fixtures.invoice_order(order_id)
    shipped = fixtures.ship_order(order_id)
    assert shipped["status"] == "SHIPPED"
    # 100 standard copies at 399 cents, 40% off at ENTRY, plus 995 handling.
    assert_invoice_figures(
        shipped,
        discount_tier_applied="ENTRY",
        merchandise_net_cents=23940,
        handling_fee_cents=995,
        invoice_total_cents=24935,
    )

    response = api_client.cancel_retailer_order(
        order_id, factories.order_cancel_payload(), SD
    )
    validate_error(response, ApiErrorId.ERR_RETURNS_NOT_PERMITTED.value)

    unchanged = fixtures.read_order(order_id)
    assert unchanged["status"] == "SHIPPED"
    assert unchanged["cancel_reason"] is None
    assert_version_unchanged(shipped, unchanged)
    assert_retailer_ledgers(
        fixtures.read_retailer(state["retailer"]["id"]),
        cumulative_units_ytd=100,
        open_balance_cents=24935,
    )
    assert_issue_unit_ledgers(
        fixtures.read_issue(state["issue"]["id"]),
        total_ordered_units=100,
        printed_units=500,
        shipped_units=100,
    )


# ─── Money-out finality ───────────────────────────────

def test_reversing_a_paid_statement_is_refused_and_leaves_both_ledgers_posted():
    """A `PAID` statement reports the payment-finality refusal and keeps its accrual.

    PRD: "A statement that has already been paid cannot be reversed and the attempt is refused with `ERR_STATEMENT_ALREADY_PAID`."

    Design: Corner/errors/err_statement_already_paid_blocks_the_reversal_of_a_paid_statement
    """
    state = fixtures.setup_royalty_revenue_ledger()
    title_id = state["title"]["id"]
    assignment_id = state["assignments"]["SCRIPT"]["id"]

    statement = fixtures.create_statement(
        title_id, state["creators"]["SCRIPT"]["id"], period="2026-12", basis="ESTIMATED"
    )
    fixtures.issue_statement(statement["id"], RA)
    paid = fixtures.pay_statement(
        statement["id"], headers=EIC, payment_reference="ACH-2026-12-001"
    )
    assert paid["status"] == "PAID"

    response = api_client.reverse_royalty_statement(
        statement["id"], factories.reverse_payload(reason="recomputed the period"), RA
    )
    validate_error(response, ApiErrorId.ERR_STATEMENT_ALREADY_PAID.value)

    unchanged = fixtures.read_statement(statement["id"])
    assert unchanged["status"] == "PAID"
    assert unchanged["payment_reference"] == "ACH-2026-12-001"
    assert unchanged["reversal_reason"] is None
    assert_statement_money(
        unchanged,
        gross_royalty_cents=85432,
        recoupment_applied_cents=25000,
        payable_cents=60432,
    )
    assert fixtures.read_title(title_id)["royalty_accrued_cents"] == 60432
    assert fixtures.read_assignment(assignment_id)["unrecouped_advance_cents"] == 0


# ─── Camera-ready gate on printing ────────────────────

def test_completing_a_print_run_while_the_letters_stage_waits_is_refused():
    """A `PREPRESS` issue cannot go to press, and the planned run is untouched.

    PRD: "Completing a run is a `ManagingEditor` act from `PLANNED`, and it requires the issue's production dimension to be `CAMERA_READY` — a book that is not camera-ready cannot go to press, refused with `ERR_NOT_CAMERA_READY` — as well as the full required-craft stage set."

    Design: Corner/errors/err_not_camera_ready_blocks_print_completion_until_the_last_stage_is_approved
    """
    state = _lock_the_order_book(_build_issue_board(approve_letters=False))
    assert_issue_dimensions(
        state["issue"], production_status="PREPRESS", commercial_status="FOC_LOCKED"
    )
    print_run = fixtures.plan_print_run(state["issue"]["id"])

    response = api_client.complete_print_run(print_run["id"], ME)
    validate_error(response, ApiErrorId.ERR_NOT_CAMERA_READY.value)

    unchanged = fixtures.read_print_run(print_run["id"])
    assert unchanged["status"] == "PLANNED"
    assert unchanged["printed_at"] is None
    assert_version_unchanged(print_run, unchanged)
    issue = fixtures.read_issue(state["issue"]["id"])
    assert_issue_unit_ledgers(issue, printed_units=0)
    assert_issue_dimensions(
        issue, production_status="PREPRESS", commercial_status="FOC_LOCKED"
    )


def test_approving_the_letters_stage_makes_the_same_print_completion_succeed():
    """The last approval flips the issue to `CAMERA_READY` and the press may run.

    PRD: "It advances `PREPRESS → CAMERA_READY` once the issue carries at least one stage for each of the five required crafts **and** every one of its stages is `APPROVED`."

    Design: Corner/errors/err_not_camera_ready_blocks_print_completion_until_the_last_stage_is_approved
    """
    state = _lock_the_order_book(_build_issue_board(approve_letters=False))
    print_run = fixtures.plan_print_run(state["issue"]["id"])
    validate_error(
        api_client.complete_print_run(print_run["id"], ME),
        ApiErrorId.ERR_NOT_CAMERA_READY.value,
    )

    fixtures.approve_stage(state["stages"]["LETTERS"]["id"])
    assert_issue_dimensions(
        fixtures.read_issue(state["issue"]["id"]), production_status="CAMERA_READY"
    )

    printed = validate_success(api_client.complete_print_run(print_run["id"], ME))
    assert printed["status"] == "PRINTED"
    assert_instant_equals(printed["printed_at"], "2026-09-23T00:00:00Z")
    assert printed["quantity"] == 500

    issue = fixtures.read_issue(state["issue"]["id"])
    assert_issue_unit_ledgers(issue, printed_units=500)
    assert_issue_dimensions(
        issue, production_status="CAMERA_READY", commercial_status="PRINTED"
    )


# ─── Cut-off timing ───────────────────────────────────

def test_locking_the_cut_off_one_day_early_is_refused():
    """A lock attempt the day before `foc_date` leaves the order book fluid.

    PRD: "It moves the issue `SOLICITED → FOC_LOCKED`, requires the logical clock to have reached the issue's `foc_date` (an earlier attempt is `ERR_FOC_NOT_REACHED`), and requires at least one `SUBMITTED` order for the issue (an empty book is `ERR_NO_QUALIFYING_ORDERS`)."

    Design: Corner/errors/err_foc_not_reached_blocks_the_lock_one_day_before_the_foc_date
    """
    state = fixtures.setup_solicited_issue_in_scripting(
        cover_specs=STANDARD_ONLY_COVERS
    )
    issue = state["issue"]
    retailer = fixtures.open_retailer()
    order = fixtures.draft_and_submit_order(
        retailer["id"], issue["id"], standard_qty=100
    )
    issue = fixtures.read_issue(issue["id"])

    fixtures.set_clock("2026-09-22T00:00:00Z")
    response = api_client.foc_lock_issue(issue["id"], SD)
    validate_error(response, ApiErrorId.ERR_FOC_NOT_REACHED.value)

    unchanged_issue = fixtures.read_issue(issue["id"])
    assert_issue_dimensions(unchanged_issue, commercial_status="SOLICITED")
    assert_issue_unit_ledgers(unchanged_issue, total_ordered_units=0)
    assert_version_unchanged(issue, unchanged_issue)
    unchanged_order = fixtures.read_order(order["id"])
    assert unchanged_order["status"] == "SUBMITTED"
    assert unchanged_order["total_units"] == 0
    assert_version_unchanged(order, unchanged_order)
    assert_retailer_ledgers(
        fixtures.read_retailer(retailer["id"]), cumulative_units_ytd=0
    )


def test_the_cut_off_locks_on_the_foc_date_itself_and_freezes_the_order():
    """On `foc_date` the lock succeeds and the submitted order is frozen at 100 units.

    PRD: "It then walks that issue's `SUBMITTED` orders in ascending `created_at` order and, for each one, computes and freezes the earned incentive allocations and the order's `total_units`, then moves the order `SUBMITTED → FOC_LOCKED`."

    Design: Corner/errors/err_foc_not_reached_blocks_the_lock_one_day_before_the_foc_date
    """
    state = fixtures.setup_solicited_issue_in_scripting(
        cover_specs=STANDARD_ONLY_COVERS
    )
    issue_id = state["issue"]["id"]
    retailer = fixtures.open_retailer()
    order = fixtures.draft_and_submit_order(
        retailer["id"], issue_id, standard_qty=100
    )
    # 2026-10-14 less twenty-one calendar days.
    assert_instant_equals(state["issue"]["foc_date"], "2026-09-23T00:00:00Z")

    fixtures.set_clock("2026-09-23T00:00:00Z")
    locked_issue = validate_success(api_client.foc_lock_issue(issue_id, SD))

    assert_issue_dimensions(locked_issue, commercial_status="FOC_LOCKED")
    assert_issue_unit_ledgers(locked_issue, total_ordered_units=100)
    locked_order = fixtures.read_order(order["id"])
    assert locked_order["status"] == "FOC_LOCKED"
    assert locked_order["total_units"] == 100
    assert locked_order["earned_variant_allocations"] == []
    assert_retailer_ledgers(
        fixtures.read_retailer(retailer["id"]),
        cumulative_units_ytd=100,
        discount_tier="ENTRY",
    )


# ─── On-sale timing ───────────────────────────────────

def test_releasing_the_issue_one_day_early_is_refused():
    """A release before `target_on_sale_date` leaves the issue `PRINTED` and undated.

    PRD: "A `SalesDirector` moves the issue `PRINTED → ON_SALE`, which requires the production dimension to be `CAMERA_READY` and requires the logical clock to have reached the issue's `target_on_sale_date`; an early release is refused with `ERR_ON_SALE_DATE_NOT_REACHED`."

    Design: Corner/errors/err_on_sale_date_not_reached_blocks_release_one_day_early
    """
    state = _lock_the_order_book(_build_issue_board())
    fixtures.plan_and_complete_print_run(state["issue"]["id"])
    issue = fixtures.read_issue(state["issue"]["id"])
    assert_issue_dimensions(
        issue, production_status="CAMERA_READY", commercial_status="PRINTED"
    )

    fixtures.set_clock("2026-10-13T00:00:00Z")
    response = api_client.release_issue(issue["id"], SD)
    validate_error(response, ApiErrorId.ERR_ON_SALE_DATE_NOT_REACHED.value)

    unchanged = fixtures.read_issue(issue["id"])
    assert_issue_dimensions(unchanged, commercial_status="PRINTED")
    assert unchanged["on_sale_date"] is None
    assert_version_unchanged(issue, unchanged)
    assert fixtures.read_title(state["title"]["id"])["status"] == "IN_PRODUCTION"


def test_releasing_the_issue_on_its_target_date_moves_the_title_to_publishing():
    """On the target date the release stamps `on_sale_date` and bubbles up the title.

    PRD: "Release stamps `on_sale_date` from the logical clock and then bubbles up to the title: a title in `IN_PRODUCTION` moves to `PUBLISHING` on its first on-sale issue, and a title already `PUBLISHING` moves to `COMPLETED` at the moment the count of its issues with commercial dimension `ON_SALE` reaches its `planned_issue_count`."

    Design: Corner/errors/err_on_sale_date_not_reached_blocks_release_one_day_early
    """
    state = _lock_the_order_book(_build_issue_board())
    fixtures.plan_and_complete_print_run(state["issue"]["id"])
    issue_id = state["issue"]["id"]

    fixtures.set_clock("2026-10-13T00:00:00Z")
    validate_error(
        api_client.release_issue(issue_id, SD),
        ApiErrorId.ERR_ON_SALE_DATE_NOT_REACHED.value,
    )

    fixtures.set_clock("2026-10-14T00:00:00Z")
    released = validate_success(api_client.release_issue(issue_id, SD))

    assert_issue_dimensions(released, commercial_status="ON_SALE")
    assert_instant_equals(released["on_sale_date"], "2026-10-14T00:00:00Z")
    title = fixtures.read_title(state["title"]["id"])
    assert title["status"] == "PUBLISHING", "one of six planned issues is on sale"
    assert title["planned_issue_count"] == 6
