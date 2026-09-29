"""Entity-shape compliance tests: creation echoes, server-computed fields, defaults,
immutable snapshots, enum and foreign-key admission.

Each test builds every precondition it needs through the API, because the harness
restarts the server and empties the registry before every individual test.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_create_only_common_fields,
    assert_decimal_equals,
    assert_field,
    assert_full_common_fields,
    assert_money_equals,
    assert_null,
    find_by_id,
)
from test_helpers.test_users import (
    PLATFORM_ADMIN,
    TRUST_COUNSEL,
    make_board_secretary_headers,
    make_strategy_officer_headers,
)


def test_organization_create_echoes_inputs_and_computes_monthly_expense(api):
    """Registering an organization echoes every supplied field, mints the common fields,
    applies the declared defaults and computes monthly_expense_cents by dividing the
    annual figure by twelve with half-up rounding.

    PRD 3.1 states that registration "derives one figure immediately and initialises
    four others": monthly_expense_cents "is the organization's annual operating expense
    divided by twelve and rounded half up to a whole cent", while
    restricted_corpus_cents and governance_seats "both start at 0", affiliation_role
    "starts at INDEPENDENT" and parent_org_id "starts as null". PRD 2.4 fixes version at
    1 when the row is created. 100000002 / 12 is 8333333.5, which rounds half up to
    8333334 rather than truncating to 8333333.

    Design: Corner/entities/organization_create_returns_declared_fields_and_computed_monthly_expense
    """
    payload = {
        "legal_name": "Riverside Youth Alliance",
        "ein": "11-1111111",
        "state_code": "CA",
        "mission_code": "YM-YOUTH_MENTORING",
        "annual_expense_cents": 100000002,
        "unrestricted_net_assets_cents": 59916670,
    }
    org = validate_success(api.create_organization(payload, PLATFORM_ADMIN), 201)

    assert_full_common_fields(org, "Organization")
    for field, expected in payload.items():
        assert_field(org, field, expected)
    assert_money_equals(org["monthly_expense_cents"], 8333334, "monthly_expense_cents")
    assert_money_equals(org["restricted_corpus_cents"], 0, "restricted_corpus_cents")
    assert_field(org, "governance_seats", 0)
    assert_field(org, "affiliation_role", "INDEPENDENT")
    assert_null(org, "parent_org_id")
    assert_field(org, "version", 1)


def test_organization_read_returns_the_stored_computed_monthly_expense(api):
    """Reading one organization returns the persisted row, including the monthly expense
    figure computed and stored at registration.

    PRD 4 describes GET /organizations/{id} as fetching one organization "including its
    computed monthly expense, restricted corpus, governance seats, structural role and
    parent organization", and PRD 3.1 fixes monthly_expense_cents as "a per-organization
    figure that is deliberately computed and stored before any deal ever sums it", so the
    read must answer 8333334 for an annual expense of 100000002 and report the untouched
    affiliation_role INDEPENDENT.

    Design: Corner/entities/organization_retrieval_returns_the_stored_row
    """
    org = fx.create_organization(api, fx.ORG_A)

    fetched = validate_success(api.get_organization(org["id"], make_strategy_officer_headers(org["id"])))

    assert_field(fetched, "id", org["id"])
    assert_money_equals(fetched["monthly_expense_cents"], 8333334, "monthly_expense_cents")
    assert_field(fetched, "affiliation_role", "INDEPENDENT")


def test_restructuring_list_filters_by_initiator_and_reports_pagination(api):
    """Listing restructurings filtered by initiator_org_id returns only that party's own
    deals and reports total_count over the filtered set rather than the whole table.

    PRD 3.2 states that "Deals may be listed filtered by initiator_org_id, by
    target_org_id, by status and by structure_type", and PRD 2.3 requires the meta block
    to carry "total_count giving the number of rows matching the filters before
    pagination, and has_more set to true when rows remain beyond the current page". With
    three deals on file of which two were opened by the same initiator, the filtered page
    holds exactly those two, total_count is 2 and has_more is false.

    Design: Corner/entities/restructuring_listing_filters_by_initiator_and_reports_pagination
    """
    ctx = fx.setup_two_orgs(api)
    org_c = fx.create_organization(api, fx.ORG_C)
    org_a, org_b, org_c_id = ctx["org_a"]["id"], ctx["org_b"]["id"], org_c["id"]

    deal_ab = validate_success(
        api.create_restructuring(
            f.restructuring_payload(org_a, org_b, confidentiality_tier="STANDARD"),
            make_strategy_officer_headers(org_a),
        ),
        201,
    )
    deal_ac = validate_success(
        api.create_restructuring(
            f.restructuring_payload(org_a, org_c_id, confidentiality_tier="STANDARD"),
            make_strategy_officer_headers(org_a),
        ),
        201,
    )
    deal_bc = validate_success(
        api.create_restructuring(
            f.restructuring_payload(org_b, org_c_id, confidentiality_tier="STANDARD"),
            make_strategy_officer_headers(org_b),
        ),
        201,
    )

    rows, meta = validate_paginated(
        api.list_restructurings(PLATFORM_ADMIN, {"initiator_org_id": org_a, "limit": 10, "offset": 0})
    )

    assert len(rows) == 2, f"expected exactly the two deals initiated by org A, got {len(rows)}"
    assert meta["total_count"] == 2, f"total_count expected 2, got {meta['total_count']}"
    assert meta["has_more"] is False, f"has_more expected False, got {meta['has_more']!r}"
    returned = {row["id"] for row in rows}
    assert returned == {deal_ab["id"], deal_ac["id"]}, f"unexpected filtered ids: {returned}"
    assert deal_bc["id"] not in returned, "a deal initiated by the other party leaked into the page"


def test_restricted_fund_read_with_unknown_id_returns_not_found(api):
    """Reading a restricted fund by an id that names no fund answers
    ERR_RESTRICTED_FUND_NOT_FOUND with HTTP 404 and the standard error envelope.

    PRD 2.7 rule 9 requires that "The RestrictedFund named by a path segment exists —
    otherwise ERR_RESTRICTED_FUND_NOT_FOUND", and names the single-fund read among the
    operations that rule guards. PRD 2.2 fixes the error envelope: response_type "error"
    and a data object carrying error_id and a human-readable message.

    Design: Corner/entities/restricted_fund_get_with_unknown_id_returns_not_found
    """
    response = api.get_restricted_fund(NON_EXISTENT_UUID, TRUST_COUNSEL)

    validate_error(response, "ERR_RESTRICTED_FUND_NOT_FOUND", 404)
    body = response.json()
    assert body["response_type"] == "error", f"response_type expected 'error', got {body.get('response_type')!r}"
    message = body["data"].get("message")
    assert isinstance(message, str) and message.strip(), f"message must be present and non-blank, got {message!r}"


def test_letter_of_intent_create_without_exclusivity_days_is_a_malformed_request(api):
    """Omitting the non-optional exclusivity_days on a letter of intent is refused with
    ERR_INVALID_REQUEST at HTTP 400 and leaves the parent deal untouched.

    PRD 3.3 lists "an exclusivity_days length between 1 and 365 inclusive" among the
    fields the request "must carry", and PRD 2.7 rule 3 places the required-field check
    above every business rule, so the answer is the 400 rather than a state or seat-split
    error. PRD 2.5 adds that "A request refused by any validation increments nothing and
    mutates nothing", so the deal stays in RATIONALE_BUILT at the same version.

    Design: Corner/entities/letter_of_intent_create_missing_required_exclusivity_days_returns_invalid_request
    """
    ctx = fx.setup_deal_rationale_built(api)
    deal_id = ctx["deal"]["id"]
    org_a = ctx["org_a"]["id"]
    before = fx.read_deal(api, deal_id)

    payload = f.letter_of_intent_payload(deal_id, before["version"])
    payload.pop("exclusivity_days")
    validate_error(
        api.create_letter_of_intent(payload, make_strategy_officer_headers(org_a)),
        "ERR_INVALID_REQUEST",
        400,
    )

    after = fx.read_deal(api, deal_id)
    assert_field(after, "status", "RATIONALE_BUILT")
    assert_field(after, "version", before["version"])


def test_restructuring_confidentiality_tier_defaults_to_standard(api):
    """Opening a deal without a confidentiality_tier persists STANDARD and applies every
    other creation default the specification declares.

    PRD 3.2 says the initiator "may optionally set a confidentiality_tier of STANDARD,
    RESTRICTED or BOARD_ONLY; when the field is omitted the tier defaults to STANDARD",
    and that "A newly opened deal is EXPLORATORY, with round_no at 1, combined_board_seats
    and reserved_seat_pool at 0, unrestricted_transfer_value_cents at 0,
    unresolved_restricted_fund_count at 0, restricted_asset_posture at NOT_ASSESSED,
    structure_type null ... and version at 1". Both parties are incorporated in CA, one of
    the five attorney-general review states, so ag_review_required is derived true.

    Design: Corner/entities/restructuring_confidentiality_tier_defaults_to_standard_when_omitted
    """
    ctx = fx.setup_two_orgs(api)
    org_a, org_b = ctx["org_a"]["id"], ctx["org_b"]["id"]

    deal = validate_success(
        api.create_restructuring(
            {"initiator_org_id": org_a, "target_org_id": org_b},
            make_strategy_officer_headers(org_a),
        ),
        201,
    )

    assert_field(deal, "confidentiality_tier", "STANDARD")
    assert_field(deal, "status", "EXPLORATORY")
    assert_field(deal, "round_no", 1)
    assert_field(deal, "combined_board_seats", 0)
    assert_field(deal, "reserved_seat_pool", 0)
    assert_money_equals(deal["unrestricted_transfer_value_cents"], 0, "unrestricted_transfer_value_cents")
    assert_field(deal, "unresolved_restricted_fund_count", 0)
    assert_field(deal, "restricted_asset_posture", "NOT_ASSESSED")
    assert_field(deal, "ag_review_required", True)
    assert_null(deal, "structure_type")
    assert_field(deal, "version", 1)


def test_alignment_assessment_derives_every_scored_field_from_stored_data(api):
    """Every field of an alignment snapshot except restructuring_id and variant is derived
    by the server, and total program overlap sits at the far side of the non-linear peak
    and therefore scores zero overlap points.

    PRD 3.2 fixes the whole tuple: sequence_no is "one plus the count of prior snapshots of
    the same deal and the same variant"; combined_monthly_expense_cents adds the two
    already-rounded monthly figures (8333334 + 8333334 = 16666668);
    open_diligence_exposure_cents "is always 0 for a SCREENING snapshot";
    available_unrestricted_cents is the two parties' unrestricted net assets less that
    exposure (59916670 + 40000000 = 99916670); reserve_months is that quotient rounded half
    up to two places (5.99), which lands in the "at least three but under six earns 20.00"
    sustainability tier; identical mission codes "earn 40.00 points"; one admitted program
    per party sharing service_category and county_code gives overlap_pair_count 1 over a
    denominator of 1, so program_overlap_index is 1.0000 and "an index of 0.0000 or 1.0000
    yields 0.00" overlap points; composite_score 60.00 bands as MODERATE.

    Design: Corner/entities/alignment_assessment_computed_fields_are_derived_from_stored_data
    """
    ctx = fx.setup_two_orgs(api)
    org_a, org_b = ctx["org_a"]["id"], ctx["org_b"]["id"]
    fx.create_program(
        api,
        org_a,
        name="Peer Mentoring East",
        service_category="YOUTH_MENTORING",
        county_code="CA-ALAMEDA",
        annual_expense_cents=40000000,
        clients_served=900,
    )
    fx.create_program(
        api,
        org_b,
        name="Peer Mentoring West",
        service_category="YOUTH_MENTORING",
        county_code="CA-ALAMEDA",
        annual_expense_cents=35000000,
        clients_served=700,
    )
    ctx = fx.setup_deal_exploratory(api, ctx)

    snapshot = validate_success(
        api.create_alignment_assessment(
            f.alignment_assessment_payload(ctx["deal"]["id"], "SCREENING"),
            make_strategy_officer_headers(org_a),
        ),
        201,
    )

    assert_field(snapshot, "sequence_no", 1)
    assert_field(snapshot, "included_program_count", 2)
    assert_field(snapshot, "overlap_pair_count", 1)
    assert_decimal_equals(snapshot["program_overlap_index"], 1.0000, 4, "program_overlap_index")
    assert_decimal_equals(snapshot["program_overlap_points"], 0.00, 2, "program_overlap_points")
    assert_decimal_equals(snapshot["mission_alignment_points"], 40.00, 2, "mission_alignment_points")
    assert_money_equals(snapshot["open_diligence_exposure_cents"], 0, "open_diligence_exposure_cents")
    assert_money_equals(snapshot["available_unrestricted_cents"], 99916670, "available_unrestricted_cents")
    assert_money_equals(
        snapshot["combined_monthly_expense_cents"], 16666668, "combined_monthly_expense_cents"
    )
    assert_decimal_equals(snapshot["reserve_months"], 5.99, 2, "reserve_months")
    assert_decimal_equals(snapshot["sustainability_points"], 20.00, 2, "sustainability_points")
    assert_decimal_equals(snapshot["composite_score"], 60.00, 2, "composite_score")
    assert_field(snapshot, "composite_rating", "MODERATE")

    programs, _ = validate_paginated(api.list_organization_programs(org_a, PLATFORM_ADMIN))
    for program in programs:
        assert_field(program, "continuity_status", "ACTIVE")


def test_board_approval_tally_fields_are_server_minted(api):
    """Recording a board vote mints the common fields at version 1 and derives the whole
    tally outcome from the supplied raw counts rather than accepting any of it.

    PRD 3.5 says "From those inputs the server derives the whole outcome and accepts none
    of it from the client": eligible_seats is seats_total less recusals (15 - 1 = 14),
    quorum_required is "eligible_seats divided by two and rounded up to the next whole
    seat" (7), votes_cast is votes_for plus votes_against (14), approval_ratio is
    "votes_for divided by votes_cast, rounded half up to four decimal places" (10/14 =
    0.7143), required_ratio "is 0.6667 for a MERGER", the decision is APPROVED because the
    inclusive comparison passes, and "The resolution's initial status is ... RECORDED when
    decision is APPROVED" with allocated_seats at 0 and certifying_secretary_ref null.
    PRD 3.5 also has the first resolution advance the deal STRUCTURE_SELECTED to
    BOARD_APPROVAL.

    Design: Corner/entities/board_approval_system_fields_are_server_minted
    """
    ctx = fx.setup_deal_structure_selected(api)
    deal_id = ctx["deal"]["id"]
    org_a = ctx["org_a"]["id"]
    secretary = make_board_secretary_headers(org_a)

    approval = validate_success(
        api.create_board_approval(
            f.board_approval_payload(deal_id, fx.deal_version(api, deal_id, secretary), "INITIATOR"),
            secretary,
        ),
        201,
    )

    assert_full_common_fields(approval, "BoardApproval")
    assert_field(approval, "version", 1)
    assert_field(approval, "status", "RECORDED")
    assert_field(approval, "eligible_seats", 14)
    assert_field(approval, "quorum_required", 7)
    assert_field(approval, "votes_cast", 14)
    assert_decimal_equals(approval["approval_ratio"], 0.7143, 4, "approval_ratio")
    assert_decimal_equals(approval["required_ratio"], 0.6667, 4, "required_ratio")
    assert_field(approval, "decision", "APPROVED")
    assert_field(approval, "allocated_seats", 0)
    assert_null(approval, "certifying_secretary_ref")

    assert_field(fx.read_deal(api, deal_id), "status", "BOARD_APPROVAL")


def test_program_service_category_outside_the_enum_is_rejected(api):
    """A program whose service_category is not one of the six declared values is refused
    with ERR_INVALID_REQUEST and no program row is stored.

    PRD 3.1 requires "a service_category drawn from YOUTH_MENTORING, FOOD_SECURITY,
    HOUSING, WORKFORCE_TRAINING, BEHAVIORAL_HEALTH and ARTS_EDUCATION", and PRD 2.7 rule 3
    rejects a body whose "enum values are members of their declared set" check fails with
    ERR_INVALID_REQUEST at HTTP 400 — so a plausible-but-undeclared category is never
    stored and can never silently drop out of a later overlap pairing.

    Design: Corner/entities/program_service_category_outside_the_enum_returns_invalid_request
    """
    org = fx.create_organization(api, fx.ORG_A)

    validate_error(
        api.create_program(
            f.program_payload(org["id"], name="Tenant Legal Clinic", service_category="LEGAL_AID"),
            PLATFORM_ADMIN,
        ),
        "ERR_INVALID_REQUEST",
        400,
    )

    programs, meta = validate_paginated(api.list_organization_programs(org["id"], PLATFORM_ADMIN))
    assert programs == [], f"no Program row may exist, got {programs}"
    assert meta["total_count"] == 0, f"total_count expected 0, got {meta['total_count']}"


def test_alignment_assessment_is_immutable_across_a_financial_restatement(api):
    """An alignment snapshot carries no version and no updated_at, and a later financial
    restatement changes only what a subsequent snapshot computes.

    PRD 2.4 states that AlignmentAssessment "is an immutable snapshot: it carries only id
    and created_at, and both updated_at and version are absent from its representation.
    There is no endpoint that mutates an assessment, and a later financial restatement or
    program continuity decision never retroactively edits one — it only changes what a
    subsequent assessment would compute." PRD 3.1 has the restatement recompute
    monthly_expense_cents by the same divide-by-twelve, round-half-up step: 600000000 / 12
    is 50000000, so the second snapshot sums 50000000 + 8333334 = 58333334 and reports
    50000000 / 58333334 = 0.86 reserve months, which falls in the "below one and a half
    months of reserve earns 0.00" tier of PRD 3.2, while the first snapshot keeps 16666668
    and 5.99.

    Design: Corner/entities/alignment_assessment_is_immutable_with_no_version_field
    """
    ctx = fx.setup_deal_rationale_built(api)
    deal_id = ctx["deal"]["id"]
    org_a = ctx["org_a"]["id"]
    first = ctx["screening"]
    assert_create_only_common_fields(first, "AlignmentAssessment")

    validate_success(
        api.financial_restatement(
            org_a,
            f.financial_restatement_payload(
                annual_expense_cents=600000000,
                unrestricted_net_assets_cents=10000000,
                restatement_reason="Audited figures superseded the draft",
            ),
            PLATFORM_ADMIN,
        )
    )
    second = validate_success(
        api.create_alignment_assessment(
            f.alignment_assessment_payload(deal_id, "SCREENING"),
            make_strategy_officer_headers(org_a),
        ),
        201,
    )

    rows, _ = validate_paginated(api.list_deal_alignment_assessments(deal_id, PLATFORM_ADMIN))
    stored_first = find_by_id(rows, first["id"])
    assert stored_first is not None, "the earlier snapshot must still be readable"
    assert_field(stored_first, "sequence_no", 1)
    assert_money_equals(
        stored_first["combined_monthly_expense_cents"], 16666668, "combined_monthly_expense_cents"
    )
    assert_decimal_equals(stored_first["reserve_months"], 5.99, 2, "reserve_months")
    assert_create_only_common_fields(stored_first, "AlignmentAssessment")

    assert_field(second, "sequence_no", 2)
    assert_money_equals(
        second["combined_monthly_expense_cents"], 58333334, "combined_monthly_expense_cents"
    )
    assert_decimal_equals(second["reserve_months"], 0.86, 2, "reserve_months")
    assert_decimal_equals(second["sustainability_points"], 0.00, 2, "sustainability_points")
    assert_create_only_common_fields(second, "AlignmentAssessment")

    restated = validate_success(api.get_organization(org_a, PLATFORM_ADMIN))
    assert_money_equals(restated["monthly_expense_cents"], 50000000, "monthly_expense_cents")


def test_restricted_fund_create_with_unknown_org_id_returns_organization_not_found(api):
    """Registering a restricted fund against an org_id that names no organization answers
    ERR_ORGANIZATION_NOT_FOUND at HTTP 404 and stores no fund.

    PRD 2.7 rule 4 requires that "Every Organization referenced by a path segment or by a
    body reference field — org_id, initiator_org_id, target_org_id, transferred_to_org_id —
    exists, otherwise ERR_ORGANIZATION_NOT_FOUND", and names restricted-fund registration
    among the operations the rule guards, so a body foreign key is checked exactly as a
    path segment would be and no orphan fund row is created.

    Design: Corner/entities/restricted_fund_create_with_unknown_org_id_returns_organization_not_found
    """
    payload = f.restricted_fund_payload(
        NON_EXISTENT_UUID,
        fund_name="Orphan Endowment",
        fund_type="PERM_ENDOWMENT",
        historic_dollar_value_cents=45000000,
        restriction_purpose_code="SC-SCHOLARSHIP",
    )

    validate_error(api.create_restricted_fund(payload, TRUST_COUNSEL), "ERR_ORGANIZATION_NOT_FOUND", 404)

    funds, meta = validate_paginated(api.list_restricted_funds(TRUST_COUNSEL))
    assert funds == [], f"no RestrictedFund row may be created, got {funds}"
    assert meta["total_count"] == 0, f"total_count expected 0, got {meta['total_count']}"


def test_restructuring_create_validates_both_party_foreign_keys(api):
    """Both party references on a deal create are validated independently: an unknown
    target answers ERR_ORGANIZATION_NOT_FOUND, while naming one organization on both sides
    answers ERR_SELF_RESTRUCTURING.

    PRD 2.7 rule 4 places the existence of every referenced organization — including
    target_org_id — above the substantive deal rules, and rule 23 states that
    "initiator_org_id and target_org_id name different organizations — otherwise
    ERR_SELF_RESTRUCTURING". PRD 3.2 repeats that "naming the same organization twice is
    refused with ERR_SELF_RESTRUCTURING". Because the two rules sit at different rungs, an
    unknown target fails at 404 even though the initiator resolves, and a self-deal whose
    references both resolve fails at 422; neither request creates a deal.

    Design: Corner/entities/restructuring_create_validates_both_organization_foreign_keys
    """
    org = fx.create_organization(api, fx.ORG_A)
    org_a = org["id"]
    officer = make_strategy_officer_headers(org_a)

    validate_error(
        api.create_restructuring(
            f.restructuring_payload(org_a, NON_EXISTENT_UUID, confidentiality_tier="STANDARD"), officer
        ),
        "ERR_ORGANIZATION_NOT_FOUND",
        404,
    )
    validate_error(
        api.create_restructuring(
            f.restructuring_payload(org_a, org_a, confidentiality_tier="STANDARD"), officer
        ),
        "ERR_SELF_RESTRUCTURING",
        422,
    )

    deals, meta = validate_paginated(api.list_restructurings(PLATFORM_ADMIN))
    assert deals == [], f"no Restructuring row may exist, got {deals}"
    assert meta["total_count"] == 0, f"total_count expected 0, got {meta['total_count']}"
