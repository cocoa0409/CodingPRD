"""Commercial and fiscal refusals: cover rules, catalog slates, printing gates and statements.

Every case proves the refusal is total — the target row keeps its status, its
derived counters and its `version` — and, where the PRD says the same request
becomes legal once the missing condition is supplied, that the retry succeeds.
"""

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_instant_equals,
    assert_issue_dimensions,
    assert_issue_unit_ledgers,
    assert_print_run_quantities,
    assert_statement_money,
    assert_version_unchanged,
    factories,
    fixtures,
    make_retailer_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.test_users import TEST_USERS

EIC = TEST_USERS["editor_in_chief_headers"]
ME = TEST_USERS["managing_editor_headers"]
SD = TEST_USERS["sales_director_headers"]
RA = TEST_USERS["royalty_accountant_headers"]

STANDARD_ONLY = (fixtures.DEFAULT_COVER_SPECS[0],)


# ─── Reprint blackout ─────────────────────────────────

def test_reprint_inside_the_collected_blackout_is_refused():
    """A `DEMAND_FORECAST` run 55 days ahead of the collected edition is refused.

    PRD: "Reprints also respect the collected edition: planning a `DEMAND_FORECAST` run is refused with `ERR_COLLECTED_EDITION_CONFLICT` when the issue has a `COLLECTED` release window whose `release_date` falls within sixty calendar days after the logical clock."

    Design: Corner/errors/err_collected_edition_conflict_blocks_a_reprint_inside_the_sixty_day_blackout
    """
    state = fixtures.setup_on_sale_issue(cover_specs=STANDARD_ONLY)
    issue_id = state["issue"]["id"]

    # 2026-10-14 plus ninety days is 2027-01-12, so the 13th is the first legal date.
    fixtures.add_release_window(issue_id, "COLLECTED", "2027-01-13")
    fixtures.set_clock("2026-11-20T00:00:00Z")

    before = fixtures.read_issue(issue_id)
    response = api_client.create_print_run(
        issue_id,
        factories.print_run_payload(before["version"], basis="DEMAND_FORECAST"),
        ME,
    )
    validate_error(response, ApiErrorId.ERR_COLLECTED_EDITION_CONFLICT.value)

    runs, meta = validate_paginated(api_client.list_print_runs(issue_id, ME))
    assert meta["total_count"] == 1, "the refused run must not have been written"
    assert runs[0]["status"] == "PRINTED"

    after = fixtures.read_issue(issue_id)
    assert_version_unchanged(before, after)
    assert_issue_dimensions(after, commercial_status="ON_SALE")
    assert_issue_unit_ledgers(after, printed_units=500)


def test_reprint_one_day_outside_the_collected_blackout_prints_from_trailing_velocity():
    """At 61 days out the same reprint is planned, sized from prior print volume alone.

    PRD: "The run's `quantity` is `order_base_units` rounded up to the next whole multiple of 250 copies, but never less than a 250-copy minimum reprint, whichever is larger."

    Design: Corner/errors/err_collected_edition_conflict_blocks_a_reprint_inside_the_sixty_day_blackout
    """
    state = fixtures.setup_on_sale_issue(cover_specs=STANDARD_ONLY)
    issue_id = state["issue"]["id"]

    fixtures.add_release_window(issue_id, "COLLECTED", "2027-01-13")
    fixtures.set_clock("2026-11-13T00:00:00Z")

    reprint = validate_success(
        api_client.create_print_run(
            issue_id,
            factories.print_run_payload(
                fixtures.issue_version(issue_id), basis="DEMAND_FORECAST"
            ),
            ME,
        ),
        expected_status=201,
    )
    assert reprint["basis"] == "DEMAND_FORECAST"
    assert reprint["status"] == "PLANNED"
    # 35% of the 500 printed copies is 175, and no reorder is open.
    assert_print_run_quantities(
        reprint,
        order_base_units=175,
        overprint_units=0,
        quantity=250,
        printing_number=2,
    )
    # A merely planned run contributes nothing to the printed ledger.
    assert_issue_unit_ledgers(fixtures.read_issue(issue_id), printed_units=500)


# ─── Variant cover rules ──────────────────────────────

def test_repeating_a_variant_cover_code_on_one_issue_is_refused():
    """A second cover coded `A` on the same issue is refused as a duplicate code.

    PRD: "Each carries a `code` of 1 to 8 characters as printed in the catalog, unique among that issue's covers (a repeat is `ERR_DUPLICATE_VARIANT_CODE`), a `kind` of `STANDARD`, `RATIO_INCENTIVE` or `RETAILER_EXCLUSIVE`, its own billed `cover_price_cents` of at least 1, and an optional `allocation_cap` of at least 1 capping how many copies of that cover any single order may earn — a null cap means uncapped."

    Design: Corner/errors/err_duplicate_variant_code_and_ratio_rules_reject_malformed_covers
    """
    state = fixtures.setup_greenlit_title_with_script_assignment()
    issue = fixtures.schedule_issue(state["title"]["id"])
    standard = fixtures.add_cover(
        issue["id"], code="A", kind="STANDARD", cover_price_cents=399
    )

    response = api_client.create_variant_cover(
        issue["id"],
        {"code": "A", "kind": "RATIO_INCENTIVE", "incentive_ratio": 25,
         "cover_price_cents": 599},
        SD,
    )
    validate_error(response, ApiErrorId.ERR_DUPLICATE_VARIANT_CODE.value)

    covers, meta = validate_paginated(api_client.list_variant_covers(issue["id"], SD))
    assert meta["total_count"] == 1, "the duplicate code must not have been written"
    assert covers[0]["id"] == standard["id"]
    assert covers[0]["kind"] == "STANDARD"


def test_incentive_ratio_rules_reject_missing_illegal_and_misplaced_ratios():
    """A ratio cover without a ratio, one with 15, and a standard cover with 10 are all refused.

    PRD: "A `RATIO_INCENTIVE` cover must declare an `incentive_ratio` of exactly 10, 25, 50 or 100, naming how many standard copies a retailer must order to earn one of it; every other kind must omit the field entirely, and either mistake is refused with `ERR_VARIANT_RATIO_INVALID`."

    Design: Corner/errors/err_duplicate_variant_code_and_ratio_rules_reject_malformed_covers
    """
    state = fixtures.setup_greenlit_title_with_script_assignment()
    issue = fixtures.schedule_issue(state["title"]["id"])
    fixtures.add_cover(issue["id"], code="A", kind="STANDARD", cover_price_cents=399)

    missing_ratio = api_client.create_variant_cover(
        issue["id"],
        {"code": "B", "kind": "RATIO_INCENTIVE", "cover_price_cents": 599},
        SD,
    )
    validate_error(missing_ratio, ApiErrorId.ERR_VARIANT_RATIO_INVALID.value)

    illegal_ratio = api_client.create_variant_cover(
        issue["id"],
        {"code": "C", "kind": "RATIO_INCENTIVE", "incentive_ratio": 15,
         "cover_price_cents": 599},
        SD,
    )
    validate_error(illegal_ratio, ApiErrorId.ERR_VARIANT_RATIO_INVALID.value)

    standard_with_ratio = api_client.create_variant_cover(
        issue["id"],
        {"code": "D", "kind": "STANDARD", "incentive_ratio": 10,
         "cover_price_cents": 399},
        SD,
    )
    validate_error(standard_with_ratio, ApiErrorId.ERR_VARIANT_RATIO_INVALID.value)

    _, meta = validate_paginated(api_client.list_variant_covers(issue["id"], SD))
    assert meta["total_count"] == 1, "no malformed cover may reach the issue"


# ─── Solicitation uniqueness and cover prerequisite ───

def test_the_same_issue_may_be_listed_once_per_catalog_but_in_two_catalog_months():
    """A repeat listing in the same catalog is refused while a second catalog accepts it.

    PRD: "The same issue may not be listed twice in the same catalog: if that catalog already holds a listing for that issue in `DRAFT`, `SUBMITTED` or `ACCEPTED` status, the draft is refused with `ERR_DUPLICATE_SOLICITATION`."

    Design: Corner/errors/err_duplicate_solicitation_is_scoped_to_the_catalog_and_issue_pair
    """
    state = fixtures.setup_issue_in_scripting()
    issue_id = state["issue"]["id"]
    fixtures.add_cover(issue_id, code="A", kind="STANDARD", cover_price_cents=399)

    august = fixtures.open_catalog()
    fixtures.draft_solicitation(august["id"], issue_id)
    september = fixtures.open_catalog(
        solicitation_month="2026-09",
        submission_deadline="2026-09-25",
        on_sale_month="2026-11",
    )

    duplicate = api_client.create_solicitation(
        august["id"], factories.solicitation_payload(issue_id), ME
    )
    validate_error(duplicate, ApiErrorId.ERR_DUPLICATE_SOLICITATION.value)

    other_month = validate_success(
        api_client.create_solicitation(
            september["id"], factories.solicitation_payload(issue_id), ME
        ),
        expected_status=201,
    )
    assert other_month["status"] == "DRAFT"
    assert other_month["catalog_id"] == september["id"]

    _, august_meta = validate_paginated(
        api_client.list_catalog_solicitations(august["id"], ME)
    )
    assert august_meta["total_count"] == 1, "the August catalog keeps its single listing"
    _, issue_meta = validate_paginated(
        api_client.list_issue_solicitations(issue_id, ME)
    )
    assert issue_meta["total_count"] == 2, "the issue is listed in two catalog months"


def test_solicitation_submission_waits_for_a_standard_cover_on_the_issue():
    """An issue carrying only a ratio-incentive cover cannot be submitted to the catalog.

    PRD: "And the issue must already carry at least one `STANDARD` variant cover, since that is the cover the catalog prints and the one retailers order against; without it the attempt is refused with `ERR_STANDARD_COVER_REQUIRED`."

    Design: Corner/errors/err_standard_cover_required_blocks_submission_until_a_standard_cover_exists
    """
    state = fixtures.setup_issue_in_scripting()
    issue_id = state["issue"]["id"]
    ratio_cover = fixtures.add_cover(
        issue_id,
        code="B",
        kind="RATIO_INCENTIVE",
        incentive_ratio=25,
        cover_price_cents=599,
    )
    catalog = fixtures.open_catalog()
    listing = fixtures.draft_solicitation(
        catalog["id"], issue_id, variant_cover_ids=[ratio_cover["id"]]
    )

    response = api_client.submit_solicitation(listing["id"], ME)
    validate_error(response, ApiErrorId.ERR_STANDARD_COVER_REQUIRED.value)

    refused = fixtures.read_solicitation(listing["id"])
    assert refused["status"] == "DRAFT"
    assert refused["submitted_at"] is None
    assert_version_unchanged(listing, refused)

    fixtures.add_cover(issue_id, code="A", kind="STANDARD", cover_price_cents=399)
    submitted = validate_success(api_client.submit_solicitation(listing["id"], ME))
    assert submitted["status"] == "SUBMITTED"
    assert_instant_equals(submitted["submitted_at"], "2026-08-01T00:00:00Z")
    # The gate reads live cover rows; the listing's advertised covers are untouched.
    assert submitted["variant_cover_ids"] == [ratio_cover["id"]]


# ─── Craft coherence ──────────────────────────────────

def test_offering_a_craft_the_creator_never_declared_is_refused():
    """A `PENCILS` offer to a script-only creator never reaches the royalty pool.

    PRD: "The offered craft must be one of the crafts the creator declared, or the offer is refused with `ERR_CRAFT_NOT_SUPPORTED`."

    Design: Corner/errors/err_craft_not_supported_and_craft_mismatch_are_two_distinct_coherence_failures
    """
    state = fixtures.setup_greenlit_title_with_script_assignment(
        creator_overrides={"full_name": "Wanda Writer", "crafts": ["SCRIPT"]}
    )
    creator_id = state["creator"]["id"]
    title_before = fixtures.read_title(state["title"]["id"])
    assert title_before["committed_share_bps"] == 5000

    response = api_client.create_creative_assignment(
        title_before["id"],
        factories.assignment_payload(
            creator_id,
            title_before["version"],
            craft="PENCILS",
            page_rate_cents=9000,
            royalty_share_bps=1500,
            booking_start_date="2026-09-01",
            booking_end_date="2026-10-01",
        ),
        EIC,
    )
    validate_error(response, ApiErrorId.ERR_CRAFT_NOT_SUPPORTED.value)

    title_after = fixtures.read_title(title_before["id"])
    assert_version_unchanged(title_before, title_after)
    assert title_after["committed_share_bps"] == 5000
    assert fixtures.read_creator(creator_id)["active_assignment_count"] == 1
    _, meta = validate_paginated(
        api_client.list_title_assignments(title_before["id"], EIC)
    )
    assert meta["total_count"] == 1, "the refused offer must not have been written"


def test_a_stage_craft_must_equal_the_craft_of_the_assignment_it_is_booked_against():
    """An `INKS` stage on a `SCRIPT` assignment is refused; the matching stage is booked.

    PRD: "Two coherence rules bind the booking: the stage's `craft` must equal the craft on the referenced assignment, or the booking is refused with `ERR_CRAFT_MISMATCH`; and the referenced assignment must belong to the same title as the issue, or it is refused with `ERR_TITLE_SCOPE_MISMATCH`."

    Design: Corner/errors/err_craft_not_supported_and_craft_mismatch_are_two_distinct_coherence_failures
    """
    state = fixtures.setup_greenlit_title_with_script_assignment(
        creator_overrides={"full_name": "Wanda Writer", "crafts": ["SCRIPT"]}
    )
    assignment_id = state["assignment"]["id"]
    issue = fixtures.schedule_issue(state["title"]["id"])

    response = api_client.create_production_stage(
        issue["id"],
        factories.stage_payload(
            assignment_id,
            craft="INKS",
            planned_start_date="2026-08-05",
            planned_due_date="2026-09-20",
        ),
        ME,
    )
    validate_error(response, ApiErrorId.ERR_CRAFT_MISMATCH.value)

    refused_issue = fixtures.read_issue(issue["id"])
    assert_version_unchanged(issue, refused_issue)
    assert_issue_dimensions(refused_issue, production_status="PLANNED")
    _, meta = validate_paginated(api_client.list_issue_stages(issue["id"], ME))
    assert meta["total_count"] == 0, "the mismatched stage must not have been written"

    stage = validate_success(
        api_client.create_production_stage(
            issue["id"],
            factories.stage_payload(
                assignment_id,
                craft="SCRIPT",
                planned_start_date="2026-08-05",
                planned_due_date="2026-09-20",
            ),
            ME,
        ),
        expected_status=201,
    )
    assert stage["craft"] == "SCRIPT"
    assert stage["status"] == "NOT_STARTED"


# ─── Cut-off lock and catalog publication ─────────────

def test_cutoff_lock_needs_a_submitted_order_even_once_the_foc_date_has_arrived():
    """An empty order book refuses the lock; one submission at the cut-off makes it legal.

    PRD: "It moves the issue `SOLICITED → FOC_LOCKED`, requires the logical clock to have reached the issue's `foc_date` (an earlier attempt is `ERR_FOC_NOT_REACHED`), and requires at least one `SUBMITTED` order for the issue (an empty book is `ERR_NO_QUALIFYING_ORDERS`)."

    Design: Corner/errors/err_no_qualifying_orders_blocks_a_lock_with_an_empty_order_book
    """
    state = fixtures.setup_solicited_issue_in_scripting(cover_specs=STANDARD_ONLY)
    issue_id = state["issue"]["id"]
    fixtures.set_clock("2026-09-23T00:00:00Z")

    before = fixtures.read_issue(issue_id)
    assert_instant_equals(before["foc_date"], "2026-09-23T00:00:00Z")

    response = api_client.foc_lock_issue(issue_id, SD)
    validate_error(response, ApiErrorId.ERR_NO_QUALIFYING_ORDERS.value)

    refused = fixtures.read_issue(issue_id)
    assert_version_unchanged(before, refused)
    assert_issue_dimensions(refused, commercial_status="SOLICITED")
    assert_issue_unit_ledgers(refused, total_ordered_units=0)

    retailer = fixtures.open_retailer(credit_limit_cents=5_000_000)
    order = fixtures.draft_order(retailer["id"], issue_id, standard_qty=100)
    # The cut-off instant gates the lock, the adjustment and the release, not submission.
    submitted = validate_success(
        api_client.submit_retailer_order(
            order["id"], make_retailer_headers(retailer["id"])
        )
    )
    assert submitted["status"] == "SUBMITTED"

    locked = validate_success(api_client.foc_lock_issue(issue_id, SD))
    assert_issue_dimensions(locked, commercial_status="FOC_LOCKED")
    assert_issue_unit_ledgers(
        fixtures.read_issue(issue_id), total_ordered_units=100
    )


def _locked_catalog_with_one_submitted_and_one_draft_listing() -> dict:
    """A `LOCKED` catalog whose two listings are `SUBMITTED` and `DRAFT`."""
    state = fixtures.setup_issue_in_scripting()
    title_id = state["title"]["id"]
    issue_one = state["issue"]
    issue_two = fixtures.schedule_issue(
        title_id, issue_number=2, target_on_sale_date="2026-11-11"
    )
    fixtures.add_cover(issue_one["id"], code="A", kind="STANDARD", cover_price_cents=399)
    fixtures.add_cover(issue_two["id"], code="A", kind="STANDARD", cover_price_cents=399)

    catalog = fixtures.open_catalog()
    listing_one = fixtures.draft_solicitation(catalog["id"], issue_one["id"])
    listing_one = fixtures.submit_solicitation(listing_one["id"])
    listing_two = fixtures.draft_solicitation(catalog["id"], issue_two["id"])

    fixtures.set_clock("2026-08-21T12:00:00Z")
    catalog = fixtures.lock_catalog(catalog["id"])
    return {
        "catalog": catalog,
        "issue_one": issue_one,
        "issue_two": issue_two,
        "listing_one": listing_one,
        "listing_two": listing_two,
    }


def test_publishing_a_catalog_with_no_accepted_listing_is_refused():
    """A locked catalog holding only a submitted and a draft listing cannot be published.

    PRD: "A `SalesDirector` moves the catalog `LOCKED → PUBLISHED`, which stamps `published_at` from the logical clock and requires at least one accepted listing — a catalog whose `accepted_slot_count` is 0 is refused with `ERR_NO_ACCEPTED_SOLICITATIONS`."

    Design: Corner/errors/err_no_accepted_solicitations_blocks_publishing_an_empty_catalog
    """
    state = _locked_catalog_with_one_submitted_and_one_draft_listing()
    catalog = state["catalog"]

    response = api_client.publish_catalog(catalog["id"], SD)
    validate_error(response, ApiErrorId.ERR_NO_ACCEPTED_SOLICITATIONS.value)

    refused = fixtures.read_catalog(catalog["id"])
    assert_version_unchanged(catalog, refused)
    assert refused["status"] == "LOCKED"
    assert refused["published_at"] is None
    assert refused["accepted_slot_count"] == 0
    assert_issue_dimensions(
        fixtures.read_issue(state["issue_one"]["id"]), commercial_status="UNSOLICITED"
    )


def test_publication_solicits_only_the_issues_of_accepted_listings():
    """Accepting one listing fills one slot; publication solicits that issue alone.

    PRD: "Publication then fans out across that catalog's accepted listings: every issue they reference moves its commercial dimension `UNSOLICITED → SOLICITED`, and each such issue's `version` increments."

    Design: Corner/errors/err_no_accepted_solicitations_blocks_publishing_an_empty_catalog
    """
    state = _locked_catalog_with_one_submitted_and_one_draft_listing()
    catalog_id = state["catalog"]["id"]

    fixtures.accept_solicitation(state["listing_one"]["id"])
    assert fixtures.read_catalog(catalog_id)["accepted_slot_count"] == 1

    published = validate_success(api_client.publish_catalog(catalog_id, SD))
    assert published["status"] == "PUBLISHED"
    assert_instant_equals(published["published_at"], "2026-08-21T12:00:00Z")

    assert_issue_dimensions(
        fixtures.read_issue(state["issue_one"]["id"]), commercial_status="SOLICITED"
    )
    assert_issue_dimensions(
        fixtures.read_issue(state["issue_two"]["id"]), commercial_status="UNSOLICITED"
    )
    assert fixtures.read_solicitation(state["listing_two"]["id"])["status"] == "DRAFT"


# ─── Printing prerequisites ───────────────────────────

def test_print_run_planning_needs_every_required_craft_stage():
    """A locked hundred-copy order book cannot be printed off a script stage alone.

    PRD: "Before any run may be planned, the issue must carry a production stage for every one of the five required crafts; an issue that reached the cut-off carrying, say, only a script stage is refused with `ERR_REQUIRED_CRAFT_STAGES_MISSING`."

    Design: Corner/errors/err_required_craft_stages_missing_blocks_the_print_run_before_any_quantity_is_computed
    """
    state = fixtures.setup_locked_order_book(cover_specs=STANDARD_ONLY)
    issue_id = state["issue"]["id"]

    before = fixtures.read_issue(issue_id)
    # The order book is non-empty, so a refusal here is not about qualifying orders.
    assert_issue_unit_ledgers(before, total_ordered_units=100)
    _, stage_meta = validate_paginated(api_client.list_issue_stages(issue_id, ME))
    assert stage_meta["total_count"] == 1, "only the SCRIPT stage was ever booked"

    response = api_client.create_print_run(
        issue_id, factories.print_run_payload(before["version"]), ME
    )
    validate_error(response, ApiErrorId.ERR_REQUIRED_CRAFT_STAGES_MISSING.value)

    _, run_meta = validate_paginated(api_client.list_print_runs(issue_id, ME))
    assert run_meta["total_count"] == 0, "no run row and no quantity may be produced"

    after = fixtures.read_issue(issue_id)
    assert_version_unchanged(before, after)
    assert_issue_dimensions(after, commercial_status="FOC_LOCKED")
    assert_issue_unit_ledgers(after, printed_units=0)


# ─── Statement participants and uniqueness ────────────

def test_a_statement_for_a_creator_unbooked_on_the_title_is_refused():
    """A creator with no assignment on the title has no statement to compute.

    PRD: "If no such assignment exists, statement creation is refused with `ERR_NO_ASSIGNMENT_FOR_CREATOR`."

    Design: Corner/errors/err_no_assignment_for_creator_blocks_a_statement_for_an_unbooked_creator
    """
    state = fixtures.setup_greenlit_title_with_script_assignment()
    title_before = fixtures.read_title(state["title"]["id"])
    fixtures.schedule_issue(title_before["id"])
    outsider = fixtures.register_creator(
        full_name="Ida Inker", crafts=["INKS"], default_page_rate_cents=7000
    )

    response = api_client.create_royalty_statement(
        factories.statement_payload(
            title_before["id"], outsider["id"], period="2026-12", basis="ESTIMATED"
        ),
        RA,
    )
    validate_error(response, ApiErrorId.ERR_NO_ASSIGNMENT_FOR_CREATOR.value)

    _, meta = validate_paginated(
        api_client.list_royalty_statements(RA, {"title_id": title_before["id"]})
    )
    assert meta["total_count"] == 0, "the refused statement must not have been written"
    assert fixtures.read_title(title_before["id"])["royalty_accrued_cents"] == 0


def test_a_booked_creator_with_no_receipts_still_gets_an_empty_draft_statement():
    """With no revenue at all the booked creator's statement is a zero draft, not an error.

    PRD: "For a channel, the raw net is the sum of `net_receipts_cents` over the contributing events of that channel; a channel whose raw net is zero emits no line at all."

    Design: Corner/errors/err_no_assignment_for_creator_blocks_a_statement_for_an_unbooked_creator
    """
    state = fixtures.setup_greenlit_title_with_script_assignment()
    title_id = state["title"]["id"]
    fixtures.schedule_issue(title_id)

    statement = validate_success(
        api_client.create_royalty_statement(
            factories.statement_payload(
                title_id, state["creator"]["id"], period="2026-12", basis="ESTIMATED"
            ),
            RA,
        ),
        expected_status=201,
    )
    assert statement["status"] == "DRAFT"
    assert statement["lines"] == []
    assert_statement_money(
        statement,
        gross_royalty_cents=0,
        recoupment_applied_cents=0,
        payable_cents=0,
    )
    assert fixtures.read_title(title_id)["royalty_accrued_cents"] == 0


def test_statement_uniqueness_is_keyed_on_basis_so_the_settled_twin_is_allowed():
    """Repeating the estimated statement is refused; the settled one for the same period is not.

    PRD: "At most one statement may exist per title, creator, period and basis among rows that are `DRAFT`, `ISSUED` or `PAID`, with a repeat refused as `ERR_DUPLICATE_STATEMENT_PERIOD`."

    Design: Corner/errors/err_duplicate_statement_period_is_keyed_on_the_basis_as_well
    """
    state = fixtures.setup_royalty_revenue_ledger()
    title_id = state["title"]["id"]
    writer_id = state["creators"]["SCRIPT"]["id"]

    estimated = fixtures.create_statement(
        title_id, writer_id, period="2026-12", basis="ESTIMATED"
    )

    duplicate = api_client.create_royalty_statement(
        factories.statement_payload(
            title_id, writer_id, period="2026-12", basis="ESTIMATED"
        ),
        RA,
    )
    validate_error(duplicate, ApiErrorId.ERR_DUPLICATE_STATEMENT_PERIOD.value)
    assert_version_unchanged(estimated, fixtures.read_statement(estimated["id"]))

    settled = validate_success(
        api_client.create_royalty_statement(
            factories.statement_payload(
                title_id, writer_id, period="2026-12", basis="SETTLED"
            ),
            RA,
        ),
        expected_status=201,
    )
    assert settled["basis"] == "SETTLED"
    assert settled["status"] == "DRAFT"
    assert_statement_money(estimated, gross_royalty_cents=85432)
    assert_statement_money(settled, gross_royalty_cents=79082)

    # Both rows are still DRAFT, so neither has reached a ledger.
    assert fixtures.read_title(title_id)["royalty_accrued_cents"] == 0
    assignment = fixtures.read_assignment(state["assignments"]["SCRIPT"]["id"])
    assert assignment["unrecouped_advance_cents"] == 25000
