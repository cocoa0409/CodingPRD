"""Refusals that depend on a stored row, a calendar bound or a declared value set."""

from test_helpers import *  # noqa: F401,F403


def test_a_quarter_that_has_not_ended_cannot_be_filed(api):
    """PRD §2.8: "Filing requires the reported period to be over: the clock's UTC date is at or
    after the quarter-end date of the report's `period_quarter`." And: "The quarter-end date
    itself is acceptable; the day before it is not."

    Design: Corner/validations/filing_a_report_before_its_quarter_ends_rejected
    """
    context = setup_licensed_operation(central_licensing_flag=False)
    licensee_id = context["licensee"]["id"]
    agreement_id = context["agreement"]["id"]
    licensee_headers = make_licensee_headers(licensee_id)

    payload = royalty_report_payload(
        agreement_id,
        "2026Q3",
        simple_report_lines(context["authorization"]["id"], 1000000, units=4000),
        agreement_version(agreement_id),
    )
    # The clock stands inside 2026Q3, which is still within the term, so opening the
    # report is legitimate; only filing it is premature.
    report = validate_success(api.create_royalty_report(payload, licensee_headers), 201)

    response = api.file_royalty_report(report["id"], None, licensee_headers)
    validate_error(response, ApiErrorId.PERIOD_NOT_ENDED.value, 422)

    unfiled = get_report(report["id"])
    assert unfiled["status"] == "DRAFT"
    assert unfiled["filed_at"] is None
    assert unfiled["royalty_due_cents"] == 0
    assert unfiled["total_payable_cents"] == 0


def test_the_audit_lookback_window_is_inclusive_at_eight_quarters(api, auditor_headers):
    """PRD §3.8: "Audit rights expire: every quarter in `scope_quarters` must satisfy an
    elapsed-quarter count from that quarter to the clock's quarter of at least 0 and at most
    eight, so exactly eight elapsed quarters is still auditable while nine is not, and a future
    quarter — for which the count would be negative — is rejected as well."

    Design: Corner/validations/audit_scope_quarter_older_than_the_lookback_window_rejected
    """
    context = setup_active_agreement(
        term_start_date="2024-01-01", term_end_date="2027-12-31"
    )
    agreement_id = context["agreement"]["id"]

    # The clock stands in 2026Q3, so 2024Q2 is nine quarters back.
    response = api.create_audit_engagement(
        audit_engagement_payload(agreement_id, ["2024Q2"]), auditor_headers
    )
    validate_error(response, ApiErrorId.AUDIT_WINDOW_EXPIRED.value, 422)

    # 2024Q3 is exactly eight quarters back, which is the inclusive bound.
    engagement = validate_success(
        api.create_audit_engagement(
            audit_engagement_payload(agreement_id, ["2024Q3"]), auditor_headers
        ),
        201,
    )
    assert engagement["status"] == "OPENED"
    assert engagement["scope_quarters"] == ["2024Q3"]

    rows, meta = validate_paginated(
        api.list_audit_engagements(auditor_headers, {"agreement_id": agreement_id})
    )
    assert meta["total_count"] == 1
    assert rows[0]["scope_quarters"] == ["2024Q3"]


def test_a_quarter_label_carrying_a_separator_is_a_shape_error(api, finance_headers):
    """PRD §2.8: "Every `_cents` field is an integer of at least 0; every `_bps` field is an
    integer between 0 and 10000 inclusive; every `_units` field is an integer of at least 1;
    every quarter label matches the four-digit-year-Q-digit form; every date is a calendar date
    and every instant an RFC 3339 timestamp with a `Z` offset; `scope_quarters` and
    `audited_quarters` are non-empty arrays of distinct, consecutive quarters in ascending
    order; and `channel_lines` is a non-empty array whose entries have distinct `channel_class`
    values."

    Design: Corner/validations/report_period_quarter_with_a_dash_rejected
    """
    context = setup_licensed_operation(central_licensing_flag=False)
    agreement_id = context["agreement"]["id"]

    payload = royalty_report_payload(
        agreement_id,
        "2026-Q2",
        simple_report_lines(context["authorization"]["id"], 1000000, units=5000),
        agreement_version(agreement_id),
    )
    response = api.create_royalty_report(
        payload, make_licensee_headers(context["licensee"]["id"])
    )
    validate_error(response, ApiErrorId.VALIDATION.value, 422)

    _, meta = validate_paginated(
        api.list_royalty_reports(finance_headers, {"agreement_id": agreement_id})
    )
    assert meta["total_count"] == 0


def test_closeout_volume_needs_an_account_that_allows_it(api, finance_headers):
    """PRD §2.8: "A channel line whose `closeout_sales_cents` is greater than zero must
    reference an authorization whose `closeout_allowed` is true, and a line whose
    `channel_class` is `OFF_PRICE` must carry a `closeout_sales_cents` greater than zero."

    Design: Corner/validations/closeout_sales_on_an_authorization_without_closeout_rights_rejected
    """
    context = setup_licensed_operation(closeout_allowed=False, central_licensing_flag=False)
    agreement_id = context["agreement"]["id"]
    assert context["authorization"]["closeout_allowed"] is False

    payload = royalty_report_payload(
        agreement_id,
        "2026Q2",
        simple_report_lines(
            context["authorization"]["id"], 1000000, units=5000, closeout_sales_cents=200000
        ),
        agreement_version(agreement_id),
    )
    response = api.create_royalty_report(
        payload, make_licensee_headers(context["licensee"]["id"])
    )
    # 200 000 is inside the 4000 bps hard limit, so the numeric caps are not what fails.
    validate_error(response, ApiErrorId.CLOSEOUT_NOT_PERMITTED.value, 409)

    _, meta = validate_paginated(
        api.list_royalty_reports(finance_headers, {"agreement_id": agreement_id})
    )
    assert meta["total_count"] == 0


def test_a_second_report_for_the_same_quarter_is_refused_even_against_a_draft(
    api, finance_headers
):
    """PRD §2.8: "At most one report exists for a given agreement and `period_quarter` in any
    status other than `RETURNED`."

    Design: Corner/validations/second_live_report_for_the_same_quarter_rejected
    """
    context = setup_licensed_operation(central_licensing_flag=False)
    agreement_id = context["agreement"]["id"]
    licensee_id = context["licensee"]["id"]

    first = create_report(
        agreement_id,
        "2026Q2",
        simple_report_lines(context["authorization"]["id"], 1000000, units=5000),
        licensee_id,
    )
    assert first["status"] == "DRAFT"

    payload = royalty_report_payload(
        agreement_id,
        "2026Q2",
        simple_report_lines(context["authorization"]["id"], 400000, units=900),
        agreement_version(agreement_id),
    )
    response = api.create_royalty_report(payload, make_licensee_headers(licensee_id))
    validate_error(response, ApiErrorId.DUPLICATE_REPORT_PERIOD.value, 409)

    untouched = get_report(first["id"])
    assert untouched["status"] == "DRAFT"
    assert untouched["channel_lines"][0]["gross_sales_cents"] == 1000000

    _, meta = validate_paginated(
        api.list_royalty_reports(finance_headers, {"agreement_id": agreement_id})
    )
    assert meta["total_count"] == 1


def test_an_overlapping_second_agreement_is_admitted_once_the_first_is_terminated(
    api, ops_headers
):
    """PRD §2.8: "No other agreement for the same `licensee_id` and `category_id` whose
    `contract_status` is neither `EXPIRED` nor `TERMINATED` has a term overlapping the requested
    one, where a term is treated as the half-open interval beginning on `term_start_date` and
    ending one day after `term_end_date`."

    Design: Corner/validations/overlapping_second_agreement_for_the_same_licensee_and_category_rejected
    """
    category = create_jersey_category()
    licensee = create_active_licensee(legal_name="Halloway Sportswear")
    first = create_draft_agreement(
        licensee["id"],
        category["id"],
        term_start_date="2026-01-01",
        term_end_date="2027-12-31",
        central_licensing_flag=False,
    )

    renewal = agreement_payload(
        licensee["id"],
        category["id"],
        term_start_date="2027-01-01",
        term_end_date="2028-12-31",
        central_licensing_flag=False,
    )
    # The requested term overlaps the DRAFT row, which is neither EXPIRED nor TERMINATED.
    validate_error(
        api.create_agreement(renewal, ops_headers), ApiErrorId.DUPLICATE_AGREEMENT.value, 409
    )

    terminated = terminate_agreement(first["id"], reason="Replaced by a renewal")
    assert terminated["contract_status"] == "TERMINATED"

    admitted = validate_success(api.create_agreement(renewal, ops_headers), 201)
    assert admitted["contract_status"] == "DRAFT"
    assert admitted["term_start_date"] == "2027-01-01"
    assert admitted["id"] != first["id"]


def test_a_club_owned_mark_cannot_appear_on_a_league_only_category(api):
    """PRD §3.1: "`mark_usage_class` is the outer envelope for every mark a design in that
    category may carry, and takes one of exactly three values: `LEAGUE_ONLY`, which permits only
    marks whose `owner_type` is `LEAGUE`; `LEAGUE_AND_CLUB`, which permits `LEAGUE` and `CLUB`;
    and `LEAGUE_CLUB_AND_PLAYER`, which permits `LEAGUE`, `CLUB`, `PLAYER_GROUP` and
    `PLAYER_INDIVIDUAL`."

    Design: Corner/validations/club_owned_mark_on_a_league_only_category_rejected
    """
    category = create_category(
        minimal_category_payload(
            category_code="PIN",
            display_name="Collectible Pins",
            mark_usage_class="LEAGUE_ONLY",
        )
    )
    club = create_club(club_code="ATL", market_name="Atlanta", revenue_share_units=5)
    league_mark = create_league_mark()
    club_mark = create_club_mark(club["id"])
    assert club_mark["status"] == "ACTIVE"
    assert club_mark["owner_type"] == "CLUB"

    context = setup_active_agreement(category=category)
    agreement_id = context["agreement"]["id"]
    licensee_headers = make_licensee_headers(context["licensee"]["id"])

    refused = api.create_product_submission(
        agreement_id,
        product_submission_payload(
            [club_mark["id"]],
            sku_class="NOVELTY",
            product_name="Club Lapel Pin",
            retail_price_cents=999,
        ),
        licensee_headers,
    )
    validate_error(refused, ApiErrorId.MARK_CLASS_NOT_PERMITTED.value, 422)

    accepted = validate_success(
        api.create_product_submission(
            agreement_id,
            product_submission_payload(
                [league_mark["id"]],
                sku_class="NOVELTY",
                product_name="League Lapel Pin",
                retail_price_cents=999,
            ),
            licensee_headers,
        ),
        201,
    )
    assert accepted["status"] == "DRAFT"
    assert accepted["mark_ids"] == [league_mark["id"]]

    _, meta = validate_paginated(
        api.list_product_submissions(licensee_headers, {"agreement_id": agreement_id})
    )
    assert meta["total_count"] == 1
