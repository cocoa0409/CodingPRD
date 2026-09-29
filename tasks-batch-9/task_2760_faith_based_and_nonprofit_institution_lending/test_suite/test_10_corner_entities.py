"""
Queue B — §1.9 section ``entities``.

Creation shapes, declared defaults, computed-at-create figures, the retrieval
and listing contracts, and the identifier-resolution answers for the eleven
root-level collections of PRD §2.4.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers.api_errors import (
    ERR_COLLATERAL_ASSET_NOT_FOUND,
    ERR_COVENANT_NOT_FOUND,
    ERR_DRAW_REQUEST_NOT_FOUND,
    ERR_GIVING_PERIOD_NOT_FOUND,
    ERR_GOVERNANCE_AUTHORIZATION_NOT_FOUND,
    ERR_INSTITUTION_MISMATCH,
    ERR_INSTITUTION_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_LOAN_APPLICATION_NOT_FOUND,
    ERR_LOAN_NOT_FOUND,
    ERR_PLEDGE_CAMPAIGN_NOT_FOUND,
    ERR_PLEDGE_NOT_FOUND,
    ERR_WORKOUT_PLAN_NOT_FOUND,
)
from test_helpers.assertions import (
    assert_created_fresh,
    assert_envelope,
    assert_fields,
    assert_id_order,
    assert_integer_cents,
    assert_nulls,
    assert_pagination_meta,
    assert_ratio,
)
from test_helpers.factories import (
    collateral_asset_payload,
    draw_request_payload,
    giving_period_payload,
    governance_authorization_payload,
    institution_payload,
    loan_application_payload,
    pledge_campaign_payload,
)
from test_helpers.fixtures import (
    build_institution,
    chain_through_loan,
    reset_clock,
)
from test_helpers.test_users import (
    CREDIT_ANALYST,
    LOAN_SERVICER,
    PLATFORM_ADMIN,
    make_institution_representative_headers,
)

# PRD §2.4: 'it is the bare UUID and nothing else' — well-formed identifiers
# that resolve to nothing, one per collection.
UNKNOWN_IDS = {
    "institution": "00000000-0000-4000-8000-000000000001",
    "giving_period": "00000000-0000-4000-8000-000000000002",
    "governance_authorization": "00000000-0000-4000-8000-000000000003",
    "pledge_campaign": "00000000-0000-4000-8000-000000000004",
    "pledge": "00000000-0000-4000-8000-000000000005",
    "collateral_asset": "00000000-0000-4000-8000-000000000006",
    "loan_application": "00000000-0000-4000-8000-000000000007",
    "loan": "00000000-0000-4000-8000-000000000008",
    "draw_request": "00000000-0000-4000-8000-000000000009",
    "covenant": "00000000-0000-4000-8000-00000000000a",
    "workout_plan": "00000000-0000-4000-8000-00000000000b",
}

SCHOOL = {
    "legal_name": "Hope Lutheran School",
    "institution_type": "SCHOOL",
    "denomination_code": "ELCA",
    "bylaws_borrowing_cap_cents": 300000000,
    "bylaws_quorum_pct": 0.5000,
    "requires_denominational_approval": None,
    "community_program_count": None,
    "endowment_market_value_cents": None,
}

MINISTRY = {
    "legal_name": "Mercy Ministries",
    "institution_type": "NONPROFIT_MINISTRY",
    "denomination_code": "INDEPENDENT",
    "bylaws_borrowing_cap_cents": 100000000,
    "bylaws_quorum_pct": 0.7500,
    "requires_denominational_approval": None,
    "community_program_count": None,
    "endowment_market_value_cents": None,
}

CHURCH_MINIMAL = {
    "requires_denominational_approval": None,
    "community_program_count": None,
    "endowment_market_value_cents": None,
}


def test_institution_create_echoes_every_input_and_zeroes_all_five_aggregates(api):
    """
    Onboarding returns the whole row: inputs echoed, derived figures at 0.

    PRD §3.1: "Onboarding initialises five derived figures to 0:
    `audited_period_count`, `period_count`, `unrestricted_giving_base_cents`,
    `net_available_for_debt_service_dollars` and `cumulative_forgiveness_cents`."

    PRD §2.2: "The `response_type` is either "object" for a single resource or
    "array" for a list of resources."

    PRD §2.2: "The `api_request_id` is a server-generated unique identifier for the
    request that starts with `req_`."

    Design: Corner/entities/institution_create_returns_all_fields_with_zeroed_aggregates
    """
    reset_clock(api)

    response = api.create_institution(institution_payload(), PLATFORM_ADMIN)
    body = assert_envelope(response)
    assert response.status_code == 201, f"expected 201, got {response.status_code}"
    assert body["response_type"] == "object", f"response_type: got {body['response_type']!r}"

    data = body["data"]
    assert_fields(
        data,
        legal_name="Grace Covenant Church",
        institution_type="CONGREGATION",
        denomination_code="PCA",
        requires_denominational_approval=False,
        bylaws_borrowing_cap_cents=500000000,
        community_program_count=3,
        endowment_market_value_cents=800000000,
    )
    assert_ratio(data["bylaws_quorum_pct"], 0.6667, "bylaws_quorum_pct")
    assert_fields(
        data,
        audited_period_count=0,
        period_count=0,
        unrestricted_giving_base_cents=0,
        net_available_for_debt_service_dollars=0,
        cumulative_forgiveness_cents=0,
    )
    assert_integer_cents(
        data,
        "bylaws_borrowing_cap_cents",
        "endowment_market_value_cents",
        "unrestricted_giving_base_cents",
        "cumulative_forgiveness_cents",
    )
    assert_created_fresh(data)


def test_institution_omitted_optional_inputs_take_their_declared_defaults(api):
    """
    The three optional inputs default to false, 0 and 0 — not to null.

    PRD §3.1: "Three inputs are optional: `requires_denominational_approval`, which
    defaults to false when omitted and, when true, forces the governance packet
    through a denominational decision before it can confer authority;
    `community_program_count`, the number of ongoing community programs such as a
    food pantry, tutoring or a shelter, which defaults to 0 and may not be negative;
    and `endowment_market_value_cents`, the donor-restricted endowment's market
    value, which defaults to 0, may not be negative, and — per §2.7 — is disclosure
    only."

    Design: Corner/entities/institution_optional_fields_take_declared_defaults_when_omitted
    """
    reset_clock(api)

    payload = institution_payload(**SCHOOL)
    assert "requires_denominational_approval" not in payload
    assert "community_program_count" not in payload
    assert "endowment_market_value_cents" not in payload

    created = get_success_data(api.create_institution(payload, PLATFORM_ADMIN), 201)
    assert_fields(
        created,
        requires_denominational_approval=False,
        community_program_count=0,
        endowment_market_value_cents=0,
    )

    # Persisted, not merely echoed.
    reread = get_success_data(api.get_institution(created["id"], PLATFORM_ADMIN))
    assert_fields(
        reread,
        requires_denominational_approval=False,
        community_program_count=0,
        endowment_market_value_cents=0,
    )


def test_institution_read_returns_the_stored_row_without_mutating_it(api):
    """
    The single read echoes the stored row, quorum fraction included.

    PRD §3.1: "Two bylaws figures are mandatory and shape everything downstream:
    `bylaws_borrowing_cap_cents`, the strictly positive maximum aggregate borrowing
    the bylaws permit, and `bylaws_quorum_pct`, the fraction of the total board vote
    a borrowing resolution must carry, which must be greater than zero, at most 1,
    and is held to four decimal places."

    PRD §2.4: "`version` (integer): a monotonically increasing counter that starts
    at 1 when the resource is created and increases by exactly 1 on every mutation
    the server applies to that resource."

    Design: Corner/entities/institution_get_by_id_returns_the_stored_row
    """
    created = build_institution(api)

    read = get_success_data(api.get_institution(created["id"], CREDIT_ANALYST))

    assert read["id"] == created["id"], f"id: expected {created['id']}, got {read['id']}"
    assert_ratio(read["bylaws_quorum_pct"], 0.6667, "bylaws_quorum_pct")
    assert_fields(read, bylaws_borrowing_cap_cents=500000000, period_count=0, version=1)


def test_institution_list_windows_newest_first_and_reports_the_filtered_total(api):
    """
    Offset pagination over three institutions, newest first, then a narrowing filter.

    PRD §2.3: "`limit` caps the number of records returned; it defaults to 10 when
    omitted, may not be smaller than 1, and may not exceed 100."

    PRD §2.3: "List responses report `limit`, `offset`, `total_count` and `has_more`
    inside the `meta` object of the envelope, where `total_count` is the size of the
    full filtered result set before the page window is applied and `has_more`
    indicates whether any record remains beyond the current window."

    PRD §2.3: "Five collections invert that default and return the newest record
    first, sorted by `created_at` descending: institutions, governance
    authorizations, pledge campaigns, loan applications and loans."

    PRD §2.3: "Filters combine conjunctively with pagination, and every filter
    narrows `total_count` before the window is cut."

    Design: Corner/entities/institution_list_offset_pagination_reports_total_count_and_has_more
    """
    inst_a = build_institution(api, **CHURCH_MINIMAL)
    inst_b = build_institution(api, **SCHOOL)
    inst_c = build_institution(api, **MINISTRY)

    first_page, first_meta = validate_paginated(
        api.list_institutions(PLATFORM_ADMIN, {"limit": 2, "offset": 0})
    )
    assert len(first_page) == 2, f"expected 2 rows, got {len(first_page)}"
    assert_pagination_meta(first_meta, total_count=3, limit=2, offset=0, has_more=True)
    assert_id_order(first_page, [inst_c["id"], inst_b["id"]])

    second_page, second_meta = validate_paginated(
        api.list_institutions(PLATFORM_ADMIN, {"limit": 2, "offset": 2})
    )
    assert len(second_page) == 1, f"expected 1 row, got {len(second_page)}"
    assert_pagination_meta(second_meta, total_count=3, limit=2, offset=2, has_more=False)
    assert_id_order(second_page, [inst_a["id"]])

    filtered, filtered_meta = validate_paginated(
        api.list_institutions(PLATFORM_ADMIN, {"institution_type": "SCHOOL"})
    )
    assert_id_order(filtered, [inst_b["id"]])
    assert_pagination_meta(filtered_meta, total_count=1, limit=10, offset=0, has_more=False)


def test_institution_create_without_the_mandatory_bylaws_cap_is_rejected(api):
    """
    A required input with no declared default cannot be omitted.

    PRD §2.10: "The request body conforms to the endpoint's input schema —
    `ERR_INVALID_REQUEST` (HTTP 422), on every write endpoint."

    PRD §3.1: "Two bylaws figures are mandatory and shape everything downstream:
    `bylaws_borrowing_cap_cents`, the strictly positive maximum aggregate borrowing
    the bylaws permit, and `bylaws_quorum_pct`, the fraction of the total board vote
    a borrowing resolution must carry, which must be greater than zero, at most 1,
    and is held to four decimal places."

    Design: Corner/entities/institution_create_missing_required_bylaws_cap_returns_invalid_request
    """
    reset_clock(api)

    payload = institution_payload(bylaws_borrowing_cap_cents=None, **CHURCH_MINIMAL)
    assert "bylaws_borrowing_cap_cents" not in payload

    error = validate_error(
        api.create_institution(payload, PLATFORM_ADMIN), ERR_INVALID_REQUEST, 422
    )
    assert isinstance(error["message"], str) and error["message"], (
        f"message must be a non-empty string, got {error.get('message')!r}"
    )

    _, meta = validate_paginated(api.list_institutions(PLATFORM_ADMIN))
    assert_pagination_meta(meta, total_count=0)


def test_institution_type_outside_the_declared_enum_is_rejected(api):
    """
    ``SYNAGOGUE`` is not one of the four declared institution types.

    PRD §3.1: "The payload names the borrower's registered `legal_name`, classifies
    it through `institution_type` as one of `CONGREGATION`, `SCHOOL`,
    `DENOMINATIONAL_AGENCY` or `NONPROFIT_MINISTRY`, and records its
    `denomination_code` — the affiliation code such as PCA, ELCA, SBC or
    INDEPENDENT."

    PRD §2.10: "The request body conforms to the endpoint's input schema —
    `ERR_INVALID_REQUEST` (HTTP 422), on every write endpoint."

    Design: Corner/entities/institution_type_outside_declared_enum_returns_invalid_request
    """
    reset_clock(api)

    payload = institution_payload(
        legal_name="Beth Shalom",
        institution_type="SYNAGOGUE",
        denomination_code="INDEPENDENT",
        bylaws_borrowing_cap_cents=100000000,
        bylaws_quorum_pct=0.5000,
        **CHURCH_MINIMAL,
    )
    validate_error(api.create_institution(payload, PLATFORM_ADMIN), ERR_INVALID_REQUEST, 422)

    _, meta = validate_paginated(api.list_institutions(PLATFORM_ADMIN))
    assert_pagination_meta(meta, total_count=0)


def test_giving_period_create_computes_both_netted_figures_and_reconciles_the_parent(api):
    """
    One audited quarter: the two period figures, and the parent's counts.

    PRD §3.1: "`unrestricted_contributions_cents` is total contributions reduced by
    restricted contributions and reduced again by the donor-restricted endowment
    draw, with the result floored at zero if those two deductions together would
    exceed the total."

    PRD §3.1: "`net_available_for_debt_service_cents` is that unrestricted figure
    reduced by the period's operating expense, again floored at zero, so a period
    that spent more than it took in unrestricted giving contributes nothing rather
    than a negative amount."

    PRD §3.1: "`period_count` rises by 1, and `audited_period_count` rises by 1 as
    well when the new period's `source` is `AUDITED`."

    PRD §3.1: "Both are 0 while `period_count` is below 4."

    Design: Corner/entities/giving_period_computed_unrestricted_and_net_fields_derived_on_create
    """
    institution = build_institution(api)

    period = get_success_data(
        api.create_giving_period(giving_period_payload(institution["id"]), CREDIT_ANALYST), 201
    )
    assert_fields(
        period,
        period_label="2025Q1",
        source="AUDITED",
        total_contributions_cents=60000000,
        unrestricted_contributions_cents=50000000,
        net_available_for_debt_service_cents=10000050,
    )

    parent = get_success_data(api.get_institution(institution["id"], CREDIT_ANALYST))
    assert_fields(
        parent,
        period_count=1,
        audited_period_count=1,
        unrestricted_giving_base_cents=0,
        net_available_for_debt_service_dollars=0,
    )

    rows, meta = validate_paginated(
        api.list_giving_periods(CREDIT_ANALYST, {"institution_id": institution["id"]})
    )
    assert_pagination_meta(meta, total_count=1)
    assert_id_order(rows, [period["id"]])


def test_governance_packet_opens_in_draft_with_its_verification_fields_still_null(api):
    """
    A fresh packet is DRAFT at revision_round 0; verification-time fields are null.

    PRD §3.2: "A new packet opens in `DRAFT` with `revision_round` at 0, and with
    `denominational_decision_note`, `verified_by_user_id` and `board_quorum_pct` all
    null."

    PRD §3.2: "`denominational_body` — the name of the presbytery, synod or
    conference that must approve — is optional and left null where the institution
    needs no denominational approval."

    Design: Corner/entities/governance_authorization_system_fields_initialize_before_any_transition
    """
    institution = build_institution(api, **CHURCH_MINIMAL)

    packet = get_success_data(
        api.create_governance_authorization(
            governance_authorization_payload(institution["id"]),
            make_institution_representative_headers(institution["id"]),
        ),
        201,
    )

    assert_fields(packet, status="DRAFT", revision_round=0, board_votes_for=8, board_votes_total=12)
    assert_nulls(
        packet, "board_quorum_pct", "verified_by_user_id", "denominational_decision_note"
    )
    assert_nulls(packet, "denominational_body")
    assert_created_fresh(packet)


def test_collateral_registration_computes_appraisal_age_and_seasoned_lending_value(api):
    """
    A 426-day-old sanctuary appraisal: 50 percent advance, first-lien factor, seasoned.

    PRD §3.4: "Registration computes `appraisal_age_days` and `lending_value_cents`
    immediately, and leaves `assigned_loan_application_id`, `lien_position`,
    `lien_effective_from` and `lien_effective_to` all null with `lien_history` an
    empty list."

    PRD §3.4: "The alternative-use score proposes a rate — 40 percent at a score of
    1, 50 percent at 2, 60 percent at 3, 70 percent at 4 and 75 percent at 5 — and
    the asset type imposes a ceiling on it: 55 percent for a `SANCTUARY`, 65 percent
    for an `EDUCATION_WING`, 70 percent for a `PARSONAGE`, 50 percent for `LAND`, 60
    percent for a `FELLOWSHIP_HALL` and 0 percent for a `DONOR_RESTRICTED_ENDOWMENT`."

    PRD §3.4: "An asset with no current assignment is valued as though it would take
    a first lien."

    PRD §3.4: "When `appraisal_age_days` is strictly greater than 365 — that is, when
    the appraisal report is more than a year old on the logical clock — the running
    figure is multiplied by 90 percent; at 365 days or fewer no seasoning discount
    applies."

    Design: Corner/entities/collateral_asset_appraisal_age_and_lending_value_computed_at_create
    """
    reset_clock(api)
    institution = build_institution(api, **CHURCH_MINIMAL)

    asset = get_success_data(
        api.create_collateral_asset(
            collateral_asset_payload(institution["id"]), CREDIT_ANALYST
        ),
        201,
    )

    # 2025-06-01 to 2026-08-01 is 426 whole days on the logical clock.
    assert_fields(asset, asset_type="SANCTUARY", appraisal_age_days=426)
    # 500000000 * 0.50 -> 250000000, first-lien factor 1.00, then * 0.90.
    assert_fields(asset, lending_value_cents=225000000)
    assert_integer_cents(asset, "appraised_value_cents", "lending_value_cents")
    assert_nulls(
        asset,
        "assigned_loan_application_id",
        "lien_position",
        "lien_effective_from",
        "lien_effective_to",
    )
    assert asset["lien_history"] == [], (
        f"lien_history must be an empty array, got {asset['lien_history']!r}"
    )


def test_pledge_campaign_opens_with_every_rollup_bucket_and_both_valuations_at_zero(api):
    """
    A campaign with a goal but no pledges values at 0, not at its goal.

    PRD §3.3: "A new campaign opens in `OPEN` with `total_pledged_cents`,
    `active_pledged_cents`, `lapsed_pledged_cents`, `fulfilled_pledged_cents`,
    `collected_to_date_cents`, `attrition_adjusted_value_cents` and
    `sponsor_projected_value_cents` all at 0."

    Design: Corner/entities/pledge_campaign_rollup_buckets_all_zero_at_launch
    """
    institution = build_institution(api, **CHURCH_MINIMAL)

    campaign = get_success_data(
        api.create_pledge_campaign(
            pledge_campaign_payload(
                institution["id"],
                campaign_name="Building For Generations",
                goal_cents=120000000,
                pledge_period_months=36,
                sponsor_collection_rate_bps=9500,
            ),
            make_institution_representative_headers(institution["id"]),
        ),
        201,
    )

    assert_fields(campaign, status="OPEN", goal_cents=120000000)
    assert_fields(
        campaign,
        total_pledged_cents=0,
        active_pledged_cents=0,
        lapsed_pledged_cents=0,
        fulfilled_pledged_cents=0,
        collected_to_date_cents=0,
        attrition_adjusted_value_cents=0,
        sponsor_projected_value_cents=0,
    )
    assert_created_fresh(campaign)


def test_submitted_draw_holds_every_waterfall_figure_null_and_reserves_nothing(api):
    """
    Submission is not approval: no waterfall outputs, no reservation.

    PRD §3.7: "A new request opens in `SUBMITTED` with `approved_amount_cents`,
    `inspector_note`, `void_reason` and every waterfall figure null."

    PRD §2.11: "Approving a draw does not move money between those three buckets; it
    reserves capacity by increasing `reserved_draw_cents`, which is a claim against
    the undrawn balance rather than a fourth bucket of it."

    Design: Corner/entities/draw_request_waterfall_fields_stay_null_until_disbursement
    """
    chain = chain_through_loan(api)

    draw = get_success_data(
        api.create_draw_request(
            draw_request_payload(
                chain.loan_id,
                project_phase="FOUNDATION",
                requested_amount_cents=112500000,
                percent_complete=0.4000,
            ),
            LOAN_SERVICER,
        ),
        201,
    )

    assert_fields(draw, status="SUBMITTED", requested_amount_cents=112500000)
    assert_nulls(
        draw,
        "approved_amount_cents",
        "retainage_cents",
        "interest_reserve_applied_cents",
        "inspection_fee_cents",
        "net_disbursed_cents",
        "completion_pct_at_disbursement",
        "inspector_note",
        "void_reason",
    )

    loan = chain.read_loan()
    assert_fields(
        loan,
        reserved_draw_cents=0,
        undrawn_commitment_cents=225000000,
        disbursed_principal_cents=0,
        servicing_status="PENDING_FIRST_DRAW",
    )


def test_each_of_the_eleven_collections_answers_an_unknown_id_with_its_own_404(api):
    """
    Eleven reads, eleven distinct entity-specific not-found identifiers.

    PRD §2.10: "Each resource kind has its own 404: `ERR_INSTITUTION_NOT_FOUND`,
    `ERR_GIVING_PERIOD_NOT_FOUND`, `ERR_GOVERNANCE_AUTHORIZATION_NOT_FOUND`,
    `ERR_PLEDGE_CAMPAIGN_NOT_FOUND`, `ERR_PLEDGE_NOT_FOUND`,
    `ERR_COLLATERAL_ASSET_NOT_FOUND`, `ERR_LOAN_APPLICATION_NOT_FOUND`,
    `ERR_LOAN_NOT_FOUND`, `ERR_DRAW_REQUEST_NOT_FOUND`, `ERR_COVENANT_NOT_FOUND` and
    `ERR_WORKOUT_PLAN_NOT_FOUND`."

    PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies
    the specific error."

    Design: Corner/entities/unknown_ids_across_all_eleven_collections_return_not_found
    """
    reset_clock(api)

    probes = [
        (api.get_institution(UNKNOWN_IDS["institution"], PLATFORM_ADMIN), ERR_INSTITUTION_NOT_FOUND),
        (
            api.get_giving_period(UNKNOWN_IDS["giving_period"], PLATFORM_ADMIN),
            ERR_GIVING_PERIOD_NOT_FOUND,
        ),
        (
            api.get_governance_authorization(
                UNKNOWN_IDS["governance_authorization"], PLATFORM_ADMIN
            ),
            ERR_GOVERNANCE_AUTHORIZATION_NOT_FOUND,
        ),
        (
            api.get_pledge_campaign(UNKNOWN_IDS["pledge_campaign"], PLATFORM_ADMIN),
            ERR_PLEDGE_CAMPAIGN_NOT_FOUND,
        ),
        (api.get_pledge(UNKNOWN_IDS["pledge"], PLATFORM_ADMIN), ERR_PLEDGE_NOT_FOUND),
        (
            api.get_collateral_asset(UNKNOWN_IDS["collateral_asset"], PLATFORM_ADMIN),
            ERR_COLLATERAL_ASSET_NOT_FOUND,
        ),
        (
            api.get_loan_application(UNKNOWN_IDS["loan_application"], PLATFORM_ADMIN),
            ERR_LOAN_APPLICATION_NOT_FOUND,
        ),
        (api.get_loan(UNKNOWN_IDS["loan"], PLATFORM_ADMIN), ERR_LOAN_NOT_FOUND),
        (
            api.get_draw_request(UNKNOWN_IDS["draw_request"], PLATFORM_ADMIN),
            ERR_DRAW_REQUEST_NOT_FOUND,
        ),
        (api.get_covenant(UNKNOWN_IDS["covenant"], PLATFORM_ADMIN), ERR_COVENANT_NOT_FOUND),
        (
            api.get_workout_plan(UNKNOWN_IDS["workout_plan"], PLATFORM_ADMIN),
            ERR_WORKOUT_PLAN_NOT_FOUND,
        ),
    ]

    for response, expected_error_id in probes:
        validate_error(response, expected_error_id, 404)


def test_loan_application_body_foreign_key_to_an_unknown_packet_is_a_404(api):
    """
    A body-level foreign key resolves as strictly as a path identifier does.

    PRD §2.10: "`governance_authorization_id`, in a path or a body, resolves —
    `ERR_GOVERNANCE_AUTHORIZATION_NOT_FOUND`, on every governance-authorization read
    and action and on loan-application creation."

    PRD §2.10: "Where a request names several resources — a path identifier plus one
    or more foreign keys in the body — the first identifier that fails to resolve
    determines the response, and the request stops there."

    Design: Corner/entities/loan_application_body_fk_to_unknown_packet_returns_not_found
    """
    institution = build_institution(api, **CHURCH_MINIMAL)

    validate_error(
        api.create_loan_application(
            loan_application_payload(
                institution["id"],
                "00000000-0000-4000-8000-0000000000ff",
                requested_amount_cents=100000000,
            ),
            CREDIT_ANALYST,
        ),
        ERR_GOVERNANCE_AUTHORIZATION_NOT_FOUND,
        404,
    )

    _, meta = validate_paginated(
        api.list_loan_applications(CREDIT_ANALYST, {"institution_id": institution["id"]})
    )
    assert_pagination_meta(meta, total_count=0)


def test_loan_application_pairing_one_institution_with_anothers_packet_is_a_mismatch(api):
    """
    Both foreign keys resolve, so the flat topology is enforced by comparison instead.

    PRD §2.10: "Cross-referenced rows belong to the same institution —
    `ERR_INSTITUTION_MISMATCH` (HTTP 409), on loan-application creation, where the
    governance packet's `institution_id` and the campaign's `institution_id` must
    both equal the application's `institution_id`, and on a collateral assignment,
    where the asset's `institution_id` must equal the target application's
    `institution_id`."

    Design: Corner/entities/loan_application_citing_another_institutions_packet_returns_institution_mismatch
    """
    inst_a = build_institution(api, **CHURCH_MINIMAL)
    inst_b = build_institution(api, **SCHOOL)

    packet_b = get_success_data(
        api.create_governance_authorization(
            governance_authorization_payload(
                inst_b["id"],
                bylaws_citation="Article II Section 1",
                board_votes_for=6,
                board_votes_total=8,
                authorized_amount_cents=200000000,
            ),
            make_institution_representative_headers(inst_b["id"]),
        ),
        201,
    )

    validate_error(
        api.create_loan_application(
            loan_application_payload(
                inst_a["id"], packet_b["id"], requested_amount_cents=100000000
            ),
            CREDIT_ANALYST,
        ),
        ERR_INSTITUTION_MISMATCH,
        409,
    )

    # The packet itself is perfectly usable — for its own institution.
    paired = get_success_data(
        api.create_loan_application(
            loan_application_payload(
                inst_b["id"], packet_b["id"], requested_amount_cents=100000000
            ),
            CREDIT_ANALYST,
        ),
        201,
    )
    assert paired["governance_authorization_id"] == packet_b["id"]
    assert paired["institution_id"] == inst_b["id"]
