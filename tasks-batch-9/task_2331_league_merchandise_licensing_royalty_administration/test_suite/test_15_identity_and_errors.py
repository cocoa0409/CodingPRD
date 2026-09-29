"""Who may call, on whose behalf, and the two refusals that precede every business rule."""

from test_helpers import *  # noqa: F401,F403


def test_a_mutation_without_a_user_id_header_is_not_an_authorization_failure(api, ops_headers):
    """PRD §2.8: "`X-User-ID` is present and non-empty on every POST and PATCH endpoint —
    otherwise `ERR_MISSING_USER_ID`."

    Design: Corner/errors/mutation_without_the_x_user_id_header_rejected
    """
    payload = licensee_payload(
        legal_name="Headwater Team Sports",
        contact_email="ops@headwater.example",
        home_country_code="US",
    )
    headers = make_headers_without_user_id("LeagueLicensingManager")
    assert "X-User-ID" not in headers

    response = api.create_licensee(payload, headers)
    # A recognised role with no acting user is its own error, not a role refusal.
    validate_error(response, ApiErrorId.MISSING_USER_ID.value, 400)

    _, meta = validate_paginated(api.list_licensees(ops_headers))
    assert meta["total_count"] == 0


def test_distributing_an_empty_pool_is_an_error_not_a_zero_cent_run(api, finance_headers):
    """PRD §2.8: "Distributing additionally requires a non-empty eligible report set and at
    least one club with `status` `ACTIVE`, otherwise `ERR_EMPTY_DISTRIBUTION_POOL`; an empty pool
    is an error rather than a zero-cent distribution."

    Design: Corner/errors/distributing_a_run_with_no_eligible_reports_rejected
    """
    create_club(club_code="ATL", market_name="Atlanta", revenue_share_units=100)
    run = create_distribution_run("2026Q2")
    locked = lock_run(run["id"])
    assert locked["status"] == "LOCKED"

    response = api.distribute_run(
        run["id"], run_version_payload(locked["version"]), finance_headers
    )
    # No report exists at all, so nothing is pending either.
    validate_error(response, ApiErrorId.EMPTY_DISTRIBUTION_POOL.value, 409)

    unchanged = get_run(run["id"])
    assert unchanged["status"] == "LOCKED"
    assert unchanged["distributed_at"] is None
    assert unchanged["pool_gross_cents"] == 0
    assert unchanged["report_count"] == 0

    _, meta = validate_paginated(list_club_distributions({"run_id": run["id"]}))
    assert meta["total_count"] == 0


def test_a_licensee_may_file_a_report_but_never_accept_it(api):
    """PRD §3.7: "A `FinanceController` reviews a filed report with a `decision` of either
    `RETURN` or `ACCEPT`." And PRD §2.8: "The acting role appears in the target endpoint's
    authorized role list — otherwise `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/licensee_cannot_accept_its_own_royalty_report_unauthorized
    """
    context = setup_filed_report(gross_sales_cents=1000000, units=4000, central_licensing_flag=False)
    licensee_id = context["licensee"]["id"]
    assert context["report"]["status"] == "FILED"

    response = api.create_report_review_decision(
        context["report"]["id"],
        report_review_decision_payload("ACCEPT"),
        make_licensee_headers(licensee_id),
    )
    # The licensee owns the row, so the ownership check would have passed; the role list
    # is what refuses.
    validate_error(response, ApiErrorId.UNAUTHORIZED.value, 403)

    report = get_report(context["report"]["id"])
    assert report["status"] == "FILED"
    assert report["accepted_at"] is None
    assert report["accepted_by_user_id"] is None

    agreement = get_agreement(context["agreement"]["id"])
    assert agreement["recouped_advance_cents"] == 0
    assert agreement["cumulative_royalty_cents"] == 0


def test_a_club_representative_cannot_register_a_product_category(api, ops_headers):
    """PRD §3.1: "A `LeagueLicensingManager` registers a **Product Category** with a
    `category_code` — a stable code that must begin with an uppercase letter, continue with
    uppercase letters, digits or underscores, run between three and forty characters in total,
    and be unique across categories — together with a human-readable `display_name`."

    Design: Corner/rbac/club_representative_cannot_create_a_product_category_unauthorized
    """
    club = create_club(club_code="ATL", market_name="Atlanta", revenue_share_units=5)
    payload = headwear_category_payload()

    refused = api.create_product_category(
        payload, make_club_representative_headers(club["id"])
    )
    validate_error(refused, ApiErrorId.UNAUTHORIZED.value, 403)

    created = validate_success(api.create_product_category(payload, ops_headers), 201)
    assert created["category_code"] == "HEADWEAR"

    rows, meta = validate_paginated(api.list_product_categories(ops_headers))
    assert meta["total_count"] == 1
    assert rows[0]["category_code"] == "HEADWEAR"


def test_the_group_licensing_lever_answers_to_the_agent_and_to_the_league(api, ops_headers):
    """PRD §3.1: "Two player-rights levers exist, and both may be operated by the player's own
    `PlayerAgent` or by a `LeagueLicensingManager`."

    Design: Corner/rbac/group_licensing_opt_in_is_shared_by_player_agent_and_league
    """
    club = create_club(club_code="ATL", market_name="Atlanta", revenue_share_units=5)
    player = create_player(club["id"], full_name="Marcus Vale")
    assert player["group_licensing_opt_in"] is True
    version_before = player["version"]

    opted_out = validate_success(
        api.set_group_licensing(
            player["id"],
            group_licensing_payload(False),
            make_player_agent_headers(player["id"]),
        ),
        200,
    )
    assert opted_out["group_licensing_opt_in"] is False

    opted_back_in = validate_success(
        api.set_group_licensing(player["id"], group_licensing_payload(True), ops_headers), 200
    )
    assert opted_back_in["group_licensing_opt_in"] is True
    # Both writes landed on the same row.
    assert opted_back_in["version"] == version_before + 2


def test_an_agent_cannot_operate_the_lever_of_another_players_row(api):
    """PRD §2.1: "When `X-User-Role` is `PlayerAgent`, `X-User-ID` is the `id` of the acting
    `Player`; ownership checks compare the target player's `id`, or a mark right's `player_id`,
    to `X-User-ID`." And: "A cross-tenant read or write by one of these three roles is refused
    with `ERR_FORBIDDEN_SCOPE` even when the role itself is authorized for the endpoint."

    Design: Corner/rbac/player_agent_cannot_flip_another_players_group_licensing_forbidden_scope
    """
    club = create_club(club_code="ATL", market_name="Atlanta", revenue_share_units=5)
    first = create_player(club["id"], full_name="Marcus Vale")
    second = create_player(club["id"], full_name="Devon Reyes")
    assert second["group_licensing_opt_in"] is True

    response = api.set_group_licensing(
        second["id"],
        group_licensing_payload(False),
        make_player_agent_headers(first["id"]),
    )
    validate_error(response, ApiErrorId.FORBIDDEN_SCOPE.value, 403)

    untouched = get_player(second["id"])
    assert untouched["group_licensing_opt_in"] is True
    assert untouched["version"] == second["version"]


def test_the_auditor_who_issued_findings_cannot_settle_them(api, finance_alt_headers):
    """PRD §2.8: "The user settling an audit engagement is not the user who issued its findings
    — otherwise `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/rbac/settling_an_engagement_as_the_findings_issuer_rejected
    """
    context = setup_accepted_report(
        gross_sales_cents=1000000, units=4000, central_licensing_flag=False
    )
    assert context["report"]["royalty_due_cents"] == 120000

    engagement = create_audit_engagement(context["agreement"]["id"], ["2026Q2"])
    begin_fieldwork(engagement["id"])
    # The restatement reproduces the reported figures, so nothing is owed.
    issued = issue_findings(engagement["id"], [audited_quarter("2026Q2", 1000000)])
    assert issued["findings_issued_by_user_id"] == "u_aud_1"
    assert issued["underreported_royalty_cents"] == 0
    assert issued["underreport_rate_bps"] == 0
    assert issued["cost_shift_applied"] is False
    assert issued["recovery_assessed_cents"] == 0

    response = api.settle_engagement(
        engagement["id"],
        settle_payload("FINDINGS"),
        make_finance_controller_headers("u_aud_1"),
    )
    # The role is right and the money is zero; the identity is what fails.
    validate_error(response, ApiErrorId.SEGREGATION_OF_DUTIES.value, 409)
    assert get_engagement(engagement["id"])["status"] == "FINDINGS_ISSUED"

    settled = validate_success(
        api.settle_engagement(
            engagement["id"], settle_payload("FINDINGS"), finance_alt_headers
        ),
        200,
    )
    assert settled["status"] == "SETTLED"
    assert settled["settled_by_user_id"] == "u_fin_2"


def test_the_controller_who_accepted_a_report_cannot_audit_its_quarter(api, auditor_headers):
    """PRD §2.8: "The user opening an audit engagement is not the user who accepted any report
    whose quarter is in scope — otherwise `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/rbac/opening_an_engagement_over_a_quarter_you_accepted_rejected
    """
    context = setup_accepted_report(
        gross_sales_cents=1000000, units=4000, central_licensing_flag=False
    )
    agreement_id = context["agreement"]["id"]
    assert context["report"]["accepted_by_user_id"] == "u_fin_1"

    payload = audit_engagement_payload(agreement_id, ["2026Q2"])
    response = api.create_audit_engagement(
        payload, make_royalty_auditor_headers("u_fin_1")
    )
    validate_error(response, ApiErrorId.SEGREGATION_OF_DUTIES.value, 409)

    engagement = validate_success(api.create_audit_engagement(payload, auditor_headers), 201)
    assert engagement["status"] == "OPENED"
    assert engagement["scope_quarters"] == ["2026Q2"]

    _, meta = validate_paginated(
        api.list_audit_engagements(auditor_headers, {"agreement_id": agreement_id})
    )
    assert meta["total_count"] == 1


def test_a_role_name_outside_the_declared_seven_is_refused_before_existence(api):
    """PRD §2.8: "`X-User-Role` is present and names one of the seven roles — otherwise
    `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/unknown_role_header_unauthorized
    """
    response = api.get_licensee(
        NON_EXISTENT_UUID, make_headers_with_role("LicensingIntern", "u_intern_1")
    )
    validate_error(response, ApiErrorId.UNAUTHORIZED.value, 403)

    # Authorization precedes existence, so the unknown identifier never surfaces.
    assert response.status_code != 404
    assert response.json()["data"]["error_id"] != ApiErrorId.LICENSEE_NOT_FOUND.value
