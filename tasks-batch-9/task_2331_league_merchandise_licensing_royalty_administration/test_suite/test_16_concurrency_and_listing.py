"""Held versions that went stale, a filtered page pair, and a ledger readable at once."""

from test_helpers import *  # noqa: F401,F403


def test_a_report_create_replaying_a_pre_acceptance_agreement_version_is_refused(
    api, finance_headers
):
    """PRD §2.7: "A request to open a royalty report must carry `expected_agreement_version`
    matching the current `version` of the `LicenseAgreement` named by `agreement_id`." And:
    "When the supplied value does not equal the agreement's current `version`, the create is
    rejected with `ERR_STALE_AGREEMENT_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/stale_expected_agreement_version_on_report_create_rejected
    """
    context = setup_licensed_operation(central_licensing_flag=False)
    agreement_id = context["agreement"]["id"]
    licensee_id = context["licensee"]["id"]
    licensee_headers = make_licensee_headers(licensee_id)

    held_version = agreement_version(agreement_id)
    first_quarter = create_report(
        agreement_id,
        "2026Q1",
        simple_report_lines(context["authorization"]["id"], 1000000, units=5000),
        licensee_id,
        expected_agreement_version=held_version,
    )
    file_report(first_quarter["id"], licensee_id)
    accepted = accept_report(first_quarter["id"])
    assert accepted["status"] == "ACCEPTED"

    later_lines = simple_report_lines(context["authorization"]["id"], 800000, units=2000)
    stale_payload = royalty_report_payload(
        agreement_id, "2026Q2", later_lines, held_version
    )
    response = api.create_royalty_report(stale_payload, licensee_headers)
    validate_error(response, ApiErrorId.STALE_AGREEMENT_VERSION.value, 412)

    _, meta = validate_paginated(
        api.list_royalty_reports(
            finance_headers, {"agreement_id": agreement_id, "period_quarter": "2026Q2"}
        )
    )
    assert meta["total_count"] == 0

    current_version = agreement_version(agreement_id)
    # Posting the accepted report's ledger is what moved the agreement underneath the
    # licensee's held value.
    assert current_version > held_version

    admitted = validate_success(
        api.create_royalty_report(
            royalty_report_payload(agreement_id, "2026Q2", later_lines, current_version),
            licensee_headers,
        ),
        201,
    )
    assert admitted["period_quarter"] == "2026Q2"
    assert admitted["status"] == "DRAFT"


def test_an_authorization_create_replaying_a_prospect_era_licensee_version_is_refused(
    api, ops_headers
):
    """PRD §2.7: "A request to create a retailer authorization under a licensee must carry
    `expected_licensee_version` matching the current `version` of that `Licensee`." And:
    "A mismatch is rejected with `ERR_STALE_LICENSEE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/stale_expected_licensee_version_on_authorization_create_rejected
    """
    licensee = create_prospect_licensee(legal_name="Rushmore Team Goods")
    assert licensee["status"] == "PROSPECT"
    held_version = licensee["version"]

    activated = activate_licensee(licensee["id"])
    assert activated["status"] == "ACTIVE"

    payload = retailer_authorization_payload(
        held_version,
        retailer_name="Metro Sports",
        channel_class="DEPARTMENT",
        sku_classes=["JERSEY"],
        closeout_allowed=False,
    )
    response = api.create_retailer_authorization(licensee["id"], payload, ops_headers)
    # The licensee's own status transition is what invalidated the held value, and the
    # error names the licensee rather than an agreement or a run.
    validate_error(response, ApiErrorId.STALE_LICENSEE_VERSION.value, 412)
    assert (
        response.json()["data"]["error_id"] != ApiErrorId.STALE_AGREEMENT_VERSION.value
    )

    _, meta = validate_paginated(
        api.list_retailer_authorizations(ops_headers, {"licensee_id": licensee["id"]})
    )
    assert meta["total_count"] == 0

    current_version = licensee_version(licensee["id"])
    assert current_version > held_version

    admitted = validate_success(
        api.create_retailer_authorization(
            licensee["id"],
            retailer_authorization_payload(
                current_version,
                retailer_name="Metro Sports",
                channel_class="DEPARTMENT",
                sku_classes=["JERSEY"],
                closeout_allowed=False,
            ),
            ops_headers,
        ),
        201,
    )
    assert admitted["status"] == "PENDING"
    assert admitted["closeout_allowed"] is False


def test_a_lock_replaying_the_version_that_authorised_the_previous_lock_is_refused(
    api, finance_headers
):
    """PRD §2.7: "A request to lock a distribution run must carry `expected_run_version`
    matching the current `version` of that `DistributionRun`." And PRD §2.8: "This rule sits
    deliberately after existence and shape but before state and every business rule, so a stale
    version is reported even when the operation would also have failed a later check."

    Design: Corner/cross_cutting_complexity_layers/stale_expected_run_version_on_lock_rejected
    """
    create_club(club_code="ATL", market_name="Atlanta", revenue_share_units=100)
    context = setup_accepted_report(
        gross_sales_cents=1000000, units=5000, central_licensing_flag=True
    )
    assert context["report"]["royalty_due_cents"] == 120000

    run = create_distribution_run("2026Q2", league_admin_rate_bps=800)
    held_version = run_version(run["id"])
    locked_once = lock_run(run["id"], held_version)
    assert locked_once["status"] == "LOCKED"
    reopened = unlock_run(run["id"])
    assert reopened["status"] == "OPEN"

    response = api.lock_distribution_run(
        run["id"], run_version_payload(held_version), finance_headers
    )
    # The run is OPEN, so the state precondition would have passed; only the version fails.
    validate_error(response, ApiErrorId.STALE_DISTRIBUTION_VERSION.value, 412)
    assert response.status_code != 409

    current = get_run(run["id"])
    assert current["status"] == "OPEN"
    assert current["locked_at"] is None
    # The lock and the unlock are the two writes that moved the row.
    assert current["version"] == held_version + 2

    relocked = validate_success(
        api.lock_distribution_run(
            run["id"], run_version_payload(current["version"]), finance_headers
        ),
        200,
    )
    assert relocked["status"] == "LOCKED"
    assert relocked["locked_at"] is not None
    assert relocked["version"] == current["version"] + 1

    _, meta = validate_paginated(list_club_distributions({"run_id": run["id"]}))
    # Locking freezes a projection; it allocates nothing.
    assert meta["total_count"] == 0


def test_a_status_filter_and_a_one_row_page_size_combine_on_the_report_listing(
    api, finance_headers
):
    """PRD §2.3: "Collections also accept exact-match filters, all optional and all combinable
    with pagination." And: "The `meta` object of a list response carries `limit`, `offset`,
    `total_count` and `has_more`." And: "Unless a specific endpoint states otherwise, list
    results are ordered by `created_at` ascending."

    Design: Corner/cross_cutting_complexity_layers/report_listing_combines_status_filter_with_pagination
    """
    context = setup_licensed_operation(
        term_start_date="2026-01-01", term_end_date="2027-12-31", central_licensing_flag=False
    )
    agreement_id = context["agreement"]["id"]
    licensee_id = context["licensee"]["id"]
    authorization_id = context["authorization"]["id"]

    first = create_report(
        agreement_id, "2026Q1", simple_report_lines(authorization_id, 1000000, units=5000),
        licensee_id,
    )
    file_report(first["id"], licensee_id)
    second = create_report(
        agreement_id, "2026Q2", simple_report_lines(authorization_id, 900000, units=5000),
        licensee_id,
    )
    file_report(second["id"], licensee_id)
    # 2026Q3 has not ended, so this one can only be opened, never filed.
    draft = create_report(
        agreement_id, "2026Q3", simple_report_lines(authorization_id, 700000, units=5000),
        licensee_id,
    )
    assert draft["status"] == "DRAFT"

    page_one, meta_one = validate_paginated(
        api.list_royalty_reports(
            finance_headers,
            {"agreement_id": agreement_id, "status": "FILED", "limit": 1, "offset": 0},
        )
    )
    assert len(page_one) == 1
    assert meta_one["total_count"] == 2
    assert meta_one["limit"] == 1
    assert meta_one["offset"] == 0
    assert meta_one["has_more"] is True

    page_two, meta_two = validate_paginated(
        api.list_royalty_reports(
            finance_headers,
            {"agreement_id": agreement_id, "status": "FILED", "limit": 1, "offset": 1},
        )
    )
    assert len(page_two) == 1
    assert meta_two["total_count"] == 2
    assert meta_two["offset"] == 1
    assert meta_two["has_more"] is False

    # The two pages partition the filtered set: no row is repeated and none is lost.
    assert {page_one[0]["id"], page_two[0]["id"]} == {first["id"], second["id"]}
    assert page_one[0]["id"] != page_two[0]["id"]

    drafts, meta_drafts = validate_paginated(
        api.list_royalty_reports(
            finance_headers,
            {"agreement_id": agreement_id, "status": "DRAFT", "limit": 10, "offset": 0},
        )
    )
    assert len(drafts) == 1
    assert meta_drafts["total_count"] == 1
    assert meta_drafts["has_more"] is False
    assert drafts[0]["id"] == draft["id"]
    assert drafts[0]["period_quarter"] == "2026Q3"


def test_the_ledger_written_by_an_acceptance_is_readable_on_the_very_next_get(
    api, finance_headers
):
    """PRD §2.9: "Consistency in this system is immediate: when an operation changes something a
    derived field depends on, that derived field is recomputed inside the same request rather
    than by a later sweep." And PRD §3.7: "`unrecouped_advance_cents` decreases by
    `recoupment_applied_cents`, `recouped_advance_cents` increases by the same amount, and
    `cumulative_royalty_cents` increases by `royalty_due_cents`."

    Design: Corner/consistency_model/accepted_report_ledger_is_visible_in_the_same_response
    """
    context = setup_filed_report(
        gross_sales_cents=1000000,
        units=5000,
        minimum_guarantee_cents=1000000,
        required_advance_cents=250000,
        central_licensing_flag=False,
    )
    agreement_id = context["agreement"]["id"]
    assert context["report"]["royalty_due_cents"] == 120000

    accepted = validate_success(
        api.create_report_review_decision(
            context["report"]["id"], report_review_decision_payload("ACCEPT"), finance_headers
        ),
        200,
    )
    assert accepted["status"] == "ACCEPTED"
    assert accepted["accepted_at"] is not None
    assert_timestamp_format(accepted["accepted_at"])
    assert accepted["recoupment_applied_cents"] == 120000

    # One read, taken immediately, with no retry and no pending intermediate state.
    agreement = get_agreement(agreement_id)
    assert agreement["unrecouped_advance_cents"] == 130000
    assert agreement["recouped_advance_cents"] == 120000
    assert agreement["cumulative_royalty_cents"] == 120000
    assert agreement["advance_paid_cents"] == 250000
    assert_advance_ledger_conserved(agreement)
