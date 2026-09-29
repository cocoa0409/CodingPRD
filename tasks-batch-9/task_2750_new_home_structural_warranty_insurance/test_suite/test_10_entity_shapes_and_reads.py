"""Entity shapes, single-resource reads, listings and intake defaults.

Every test in this file builds its own world from scratch through PRD-declared
endpoints, because each test runs against a freshly restarted server with an
empty database.
"""

from test_helpers import (
    ApiErrorId,
    assert_builder,
    assert_calendar_date,
    assert_claim,
    assert_coverage_term,
    assert_envelope_meta,
    assert_journal_audit_fields,
    assert_money_cents,
    assert_policy,
    assert_transfer,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.constants import (
    CANONICAL_BUILDER_RISK_CLASS,
    CANONICAL_BUILDER_RISK_SCORE,
    CANONICAL_CLOSING_DATE,
    CANONICAL_CLOSING_INSTANT,
    CANONICAL_PURCHASE_PRICE_CENTS,
    TRANSFER_BASE_FEE_CENTS,
)
from test_helpers.factories import (
    create_builder_payload,
    create_claim_payload,
    create_policy_payload,
    create_transfer_payload,
    underwriting_review_payload,
)
from test_helpers.fixtures import (
    add_endorsement_term,
    create_builder_under_review,
    create_homeowner,
    enroll_policy,
    read_builder,
    read_policy,
    read_transfer,
    request_transfer,
    set_clock,
    setup_active_policy,
    setup_approved_builder_and_owner,
)
from test_helpers.test_users import (
    UW_OFFICER_USER_ID,
    make_builder_principal_headers,
    make_homeowner_headers,
)

# The unassigned identifier used for every not-found probe in this file.
UNASSIGNED_UUID = "00000000-0000-4000-8000-000000000000"


def test_builder_creation_returns_declared_fields_and_system_defaults(
    api, underwriting_officer_headers
):
    """PRD 3.1: "The new file lands in `underwriting_status` `DRAFT` with no
    score at all — `risk_score`, `risk_class` and `risk_basis` are all null —
    and with its monitoring counters at rest: `earned_premium_cents` and
    `incurred_loss_cents` are 0, `loss_ratio` is 0.0000, `monitoring_posture`
    is `OPEN`, and `default_declared_at` is null."
    PRD 3.1: "The file also carries `obligation_period_years`, which this
    program fixes at 2 years for every builder; it is never accepted as request
    input and never varies."
    PRD 2.4: "Most resources additionally carry `updated_at` — same ISO 8601
    UTC format with three fractional digits, refreshed on every mutation of the
    row — and `version`, an integer that starts at 1 when the row is created
    and increases by exactly 1 each time the row is mutated."
    PRD 4: "an operation that brings a **new** resource into existence answers
    201 Created"

    Design: Corner/Table 1 Entities/builder_creation_returns_the_declared_fields_and_every_system_default
    """
    payload = create_builder_payload()
    response = api.create_builder(payload, underwriting_officer_headers)
    builder = validate_success(response, 201)
    assert_builder(builder)

    # The six declared underwriting inputs are echoed unchanged.
    assert builder["company_name"] == "Cedar Ridge Homes"
    assert builder["state_code"] == "TX"
    assert builder["years_in_business"] == 5
    assert builder["homes_closed_last_year"] == 25
    assert builder["claims_history_score"] == 94
    assert builder["financial_strength_tier"] == "TIER_3"

    # A fresh file lands in DRAFT with no score at all.
    assert builder["underwriting_status"] == "DRAFT"
    assert builder["risk_score"] is None, "risk_score must be null on a DRAFT file"
    assert builder["risk_class"] is None, "risk_class must be null on a DRAFT file"
    assert builder["risk_basis"] is None, "risk_basis must be null on a DRAFT file"
    assert builder["default_declared_at"] is None

    # The program-fixed obligation period.
    assert builder["obligation_period_years"] == 2

    # Monitoring counters at rest.
    assert builder["earned_premium_cents"] == 0
    assert builder["incurred_loss_cents"] == 0
    assert float(builder["loss_ratio"]) == 0.0
    assert builder["monitoring_posture"] == "OPEN"

    # Audit fields on a mutable row.
    assert builder["version"] == 1, "a newly created row starts at version 1"
    assert is_valid_uuid(builder["id"])
    assert is_iso8601_timestamp(builder["created_at"])
    assert is_iso8601_timestamp(builder["updated_at"])
    assert_envelope_meta(response.json()["meta"])


def test_policy_read_returns_stored_premium_breakdown_and_coverage_anchors(
    api, underwriting_officer_headers
):
    """PRD 3.3: "`premium_component_workmanship_cents` is the purchase price
    multiplied by the workmanship share of 0.18, multiplied by the band's base
    rate in basis points, divided by 10,000, and rounded half up to a whole
    number of cents."
    PRD 3.3: "Finally, `premium_cents` is the sum of the three independently
    rounded component integers plus the surcharge, added as exact integers."
    PRD 3.3: "`coverage_start_date` is set equal to `closing_date` and is the
    anchor for all coverage arithmetic."
    PRD 3.3: "`current_owner_id` is initialised to the supplied
    `initial_owner_id`, `transfer_count` starts at 0, `enrollment_hold` starts
    at false, and `pending_transfer_id` starts as null."
    PRD 3.3: "The policy's two independent state axes begin at
    `coverage_status` `PENDING_ENROLLMENT` and `premium_status` `UNBILLED`."
    PRD 3.3: "Rating happens once, at enrollment, and never again."

    Design: Corner/Table 1 Entities/policy_retrieval_returns_the_stored_premium_breakdown_and_coverage_anchors
    """
    scenario = setup_approved_builder_and_owner()
    enrolled = enroll_policy(
        scenario["builder"]["id"], scenario["homeowner"]["id"],
        purchase_price_cents=CANONICAL_PURCHASE_PRICE_CENTS,
        closing_date=CANONICAL_CLOSING_DATE, state_code="TX",
    )

    response = api.get_policy(enrolled["id"], underwriting_officer_headers)
    policy = validate_success(response, 200)
    assert_policy(policy)

    # The stored premium breakdown is returned as it was computed at enrollment.
    assert policy["premium_component_workmanship_cents"] == 56_871
    assert policy["premium_component_systems_cents"] == 85_307
    assert policy["premium_component_structural_cents"] == 217_216
    assert policy["state_surcharge_cents"] == 4_500
    assert policy["premium_cents"] == 363_894
    for field in ("premium_component_workmanship_cents",
                  "premium_component_systems_cents",
                  "premium_component_structural_cents",
                  "state_surcharge_cents", "premium_cents"):
        assert_money_cents(policy[field], field)

    # The coverage anchors.
    assert policy["coverage_start_date"] == "2026-08-15"
    assert policy["builder_obligation_end_date"] == "2028-08-14"
    assert policy["closing_date"] == "2026-08-15"
    assert_calendar_date(policy["coverage_start_date"])
    assert_calendar_date(policy["builder_obligation_end_date"])

    # The risk band snapshot and the ownership anchors.
    assert policy["risk_class_at_enrollment"] == CANONICAL_BUILDER_RISK_CLASS
    assert policy["current_owner_id"] == scenario["homeowner"]["id"]
    assert policy["initial_owner_id"] == scenario["homeowner"]["id"]
    assert policy["builder_id"] == scenario["builder"]["id"]

    # Both axes and the transfer bookkeeping at their initial values.
    assert policy["coverage_status"] == "PENDING_ENROLLMENT"
    assert policy["premium_status"] == "UNBILLED"
    assert policy["transfer_count"] == 0
    assert policy["enrollment_hold"] is False
    assert policy["pending_transfer_id"] is None
    assert policy["version"] == 1, "a read never mutates the row"


def test_coverage_term_listing_paginates_and_puts_base_terms_before_endorsements(
    api, underwriting_officer_headers
):
    """PRD 2.3: "Three list endpoints override that default because their
    business reading order differs: the review journal of a builder is returned
    newest first, the coverage terms of a home are returned with `BASE` terms
    before `ENDORSEMENT` terms and then by `start_date` ascending, and the
    engineering assessments of a claim and the reserve journal of a claim are
    both returned oldest first."
    PRD 2.3: "List responses populate four pagination fields inside `meta`:
    `limit` and `offset` echo the effective values used for the query,
    `total_count` reports the number of rows that match the filter before
    pagination is applied, and `has_more` is true when rows remain beyond the
    current page."
    PRD 3.3: "The new term is born with `term_kind` `ENDORSEMENT`, `status`
    `OPEN`, `consumed_limit_cents` of 0 and `remaining_limit_cents` equal to its
    `limit_cents`, and the policy's `version` advances by 1."

    Design: Corner/Table 1 Entities/coverage_term_listing_paginates_and_orders_base_terms_before_endorsements
    """
    scenario = setup_active_policy()
    policy_id = scenario["policy"]["id"]
    endorsement = add_endorsement_term(
        policy_id, coverage_type="WORKMANSHIP",
        start_date="2028-09-01", end_date="2029-08-31",
        limit_cents=1_500_000, deductible_cents=100_000,
    )
    assert endorsement["term_kind"] == "ENDORSEMENT"

    first_page, first_meta = validate_paginated(
        api.list_policy_coverage_terms(
            policy_id, underwriting_officer_headers, {"limit": 2, "offset": 0}
        )
    )
    assert len(first_page) == 2, f"limit=2 must return 2 rows, got {len(first_page)}"
    assert first_meta["total_count"] == 4, (
        f"the policy carries three BASE terms plus one endorsement, "
        f"got total_count {first_meta['total_count']}"
    )
    assert first_meta["has_more"] is True
    assert first_meta["limit"] == 2 and first_meta["offset"] == 0

    second_page, second_meta = validate_paginated(
        api.list_policy_coverage_terms(
            policy_id, underwriting_officer_headers, {"limit": 2, "offset": 2}
        )
    )
    assert len(second_page) == 2, f"offset=2 must return the last 2 rows, got {len(second_page)}"
    assert second_meta["total_count"] == 4
    assert second_meta["has_more"] is False
    assert second_meta["limit"] == 2 and second_meta["offset"] == 2

    # BASE rows sort ahead of the ENDORSEMENT row: the three BASE terms occupy
    # the first three positions and the endorsement is last.
    ordered = first_page + second_page
    for term in ordered:
        assert_coverage_term(term)
    kinds = [term["term_kind"] for term in ordered]
    assert kinds == ["BASE", "BASE", "BASE", "ENDORSEMENT"], (
        f"BASE terms must precede ENDORSEMENT terms, got {kinds}"
    )
    assert ordered[3]["id"] == endorsement["id"]
    assert {term["coverage_type"] for term in ordered[:3]} == {
        "WORKMANSHIP", "SYSTEMS", "STRUCTURAL"
    }, "the three BASE terms are one per coverage type"
    assert len({term["id"] for term in ordered}) == 4, "the two pages must not overlap"


def test_reading_an_unassigned_claim_id_returns_claim_not_found(
    api, claims_adjuster_headers
):
    """PRD 2.6: "Path parameters are resolved **strictly left to right**, and
    the first identifier that fails to resolve determines the error. A request
    naming a builder that does not exist yields `ERR_BUILDER_NOT_FOUND`; a
    homeowner, `ERR_HOMEOWNER_NOT_FOUND`; a policy, `ERR_POLICY_NOT_FOUND`; a
    coverage term, `ERR_COVERAGE_TERM_NOT_FOUND`; a claim,
    `ERR_CLAIM_NOT_FOUND`; a transfer request, `ERR_TRANSFER_NOT_FOUND`; an
    escalation case, `ERR_ESCALATION_CASE_NOT_FOUND`; a neutral,
    `ERR_NEUTRAL_NOT_FOUND`; a reserve-journal entry,
    `ERR_RESERVE_ENTRY_NOT_FOUND`. All nine are HTTP 404."
    PRD 2.2: "The `message` provides a human-readable explanation of what went
    wrong."

    Design: Corner/Table 1 Entities/reading_a_claim_id_that_does_not_exist_returns_claim_not_found
    """
    response = api.get_claim(UNASSIGNED_UUID, claims_adjuster_headers)
    error_data = validate_error(
        response, ApiErrorId.ERR_CLAIM_NOT_FOUND.value, 404
    )

    body = response.json()
    assert body["response_type"] == "error", (
        f"an unassigned claim id must not answer with a success envelope: {body}"
    )
    assert error_data["message"].strip(), "data.message must be non-blank"


def test_enrollment_without_purchase_price_is_rejected_as_invalid_request(
    api, underwriting_officer_headers
):
    """PRD 2.8: "**Request shape (422).** `ERR_INVALID_REQUEST` when a required
    body field is missing, is of the wrong type, falls outside its declared
    numeric range, is an enum value that is not a declared member, when an
    amount field is below its declared floor, or when `affected_elements`
    contains duplicate entries."
    PRD 3.3: "A `BuilderPrincipal` supplies the `builder_id` of its own file,
    the `initial_owner_id` of the buyer at closing, the home's `street_address`
    (1 to 200 characters, not blank), the home's `state_code` (again one of
    `TX`, `CO`, `AZ`, `FL`, `NC`), the `purchase_price_cents` at closing — a
    whole number of cents from 5,000,000 to 500,000,000 inclusive, that is, a
    home priced between fifty thousand and five million dollars — and the
    `closing_date` as an ISO 8601 calendar date, which may not be later than
    the logical clock's current date."

    Design: Corner/Table 1 Entities/policy_enrollment_missing_required_purchase_price_returns_invalid_request
    """
    scenario = setup_approved_builder_and_owner()
    builder_id = scenario["builder"]["id"]

    payload = create_policy_payload(builder_id, scenario["homeowner"]["id"])
    payload.pop("purchase_price_cents")
    assert "purchase_price_cents" not in payload

    response = api.create_policy(payload, make_builder_principal_headers(builder_id))
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 422)

    # The premium calculation is never reached: no policy row survives.
    rows, meta = validate_paginated(
        api.list_policies(underwriting_officer_headers, {"builder_id": builder_id})
    )
    assert meta["total_count"] == 0, (
        f"a rejected enrollment must leave no policy row, got {meta['total_count']}"
    )
    assert rows == []


def test_first_transfer_request_without_documents_reference_stores_null(
    api, underwriting_officer_headers
):
    """PRD 3.5: "A successful request creates a transfer row in `status`
    `REQUESTED` against the policy named in its `policy_id`, with
    `requested_by_owner_id` copied from the acting `X-User-ID`."
    PRD 3.5: "Its `transfer_fee_cents` is computed at that moment as a base fee
    of 7,500 cents plus 2,500 cents for each transfer already recorded on the
    policy — so the first hand-off costs seventy-five dollars, the second one
    hundred, the third one hundred and twenty-five."
    PRD 3.5: "When no request was open, the new row's `prior_transfer_id` stays
    null."
    PRD 3.5: "it is available **only** when the request's `documents_reference`
    is not null, and an approval on an undocumented request is refused with
    `ERR_MISSING_TRANSFER_DOCUMENTATION`."
    PRD 3.5: "Either way the policy's `pending_transfer_id` is set to the new
    request's `id` and the policy's `version` advances by 1."

    Design: Corner/Table 1 Entities/transfer_request_omitting_documents_reference_defaults_it_to_null
    """
    scenario = setup_active_policy()
    policy = scenario["policy"]
    seller = scenario["homeowner"]
    assert policy["version"] == 4, (
        "enrollment, invoicing, payment and activation each advance the policy "
        f"version by exactly 1, got {policy['version']}"
    )

    transferee = create_homeowner(full_name="Ben Calloway",
                                  email="ben.calloway@example.com")

    payload = create_transfer_payload(
        transferee["id"], policy["version"], transfer_date="2026-09-01"
    )
    payload.pop("documents_reference")
    assert "documents_reference" not in payload

    response = api.create_transfer(
        policy["id"], payload, make_homeowner_headers(seller["id"])
    )
    transfer = validate_success(response, 201)
    assert_transfer(transfer)

    assert transfer["status"] == "REQUESTED"
    assert transfer["documents_reference"] is None, (
        "an omitted deed packet leaves the request undocumented, i.e. null"
    )
    assert transfer["prior_transfer_id"] is None, (
        "no request was open, so prior_transfer_id stays null"
    )
    assert transfer["transfer_fee_cents"] == TRANSFER_BASE_FEE_CENTS == 7_500
    assert_money_cents(transfer["transfer_fee_cents"], "transfer_fee_cents")
    assert transfer["requested_by_owner_id"] == seller["id"]
    assert transfer["new_owner_id"] == transferee["id"]
    assert transfer["policy_id"] == policy["id"]
    assert transfer["version"] == 1

    after = read_policy(policy["id"])
    assert after["pending_transfer_id"] == transfer["id"]
    assert after["version"] == 5, (
        f"the request advances the policy version by 1, got {after['version']}"
    )
    assert after["transfer_count"] == 0, "only a recorded transfer raises the count"


def test_claim_intake_ignores_supplied_computed_money_and_routing_fields(
    api, underwriting_officer_headers
):
    """PRD 3.6: "Intake resolves two things the claimant does not get to
    choose. First, `reported_date` is stamped from the logical clock's current
    date — never from the request."
    PRD 3.6: "Third, and most consequential, intake assigns the `obligor`. When
    the `reported_date` is on or before the policy's
    `builder_obligation_end_date`, the `obligor` is `BUILDER`; when it falls
    after that date, the `obligor` is `INSURER`."
    PRD 3.6: "A fresh claim lands in `status` `SUBMITTED` with
    `designated_structural` false and with all four money fields —
    `reserve_cents`, `paid_cents`, `released_cents` and
    `incurred_authorized_cents` — at 0."
    PRD 3.6: "Its settlement figures `gross_adjusted_cents`,
    `deductible_applied_cents`, `betterment_cents` and `net_payable_cents`
    likewise all start at 0, while `substantiation_ratio`,
    `adjudicated_by_user_id`, `denial_date` and `escalation_deadline_date` all
    start null and are filled in only by the later steps that own them."
    PRD 3.6: "The acting `X-User-ID` must equal the policy's `current_owner_id`,
    and it is copied onto the claim as `filed_by_owner_id`."

    Design: Corner/Table 1 Entities/claim_intake_computed_money_fields_input_ignored
    """
    scenario = setup_active_policy()
    policy = scenario["policy"]
    owner = scenario["homeowner"]

    payload = create_claim_payload(
        policy["id"],
        coverage_type="STRUCTURAL",
        defect_category="WATER_INTRUSION",
        damage_description="Slab displacement at the north wall",
        claimed_amount_cents=2_187_500,
        # Every field below is server-computed and must be discarded.
        net_payable_cents=9_999_999,
        reserve_cents=5_000_000,
        obligor="INSURER",
        reported_date="2030-01-01",
    )
    response = api.create_claim(payload, make_homeowner_headers(owner["id"]))
    claim = validate_success(response, 201)
    assert_claim(claim)

    # The supplied computed values were ignored, not rejected.
    assert claim["net_payable_cents"] == 0
    assert claim["reserve_cents"] == 0
    assert claim["gross_adjusted_cents"] == 0
    assert claim["deductible_applied_cents"] == 0
    assert claim["betterment_cents"] == 0
    assert claim["paid_cents"] == 0
    assert claim["released_cents"] == 0
    assert claim["incurred_authorized_cents"] == 0

    # The obligor comes from the reported date against the obligation boundary.
    assert claim["obligor"] == "BUILDER", (
        "a claim reported on 2026-08-15, on or before the obligation end date "
        "2028-08-14, belongs to the builder"
    )
    assert claim["reported_date"] == "2026-08-15", (
        f"reported_date is the logical clock's date, got {claim['reported_date']}"
    )

    # Intake bound the claim to the BASE STRUCTURAL term of that policy.
    assert claim["coverage_term_id"] == scenario["structural_term"]["id"]
    rows, meta = validate_paginated(
        api.list_policy_coverage_terms(
            policy["id"], underwriting_officer_headers,
            {"coverage_type": "STRUCTURAL"},
        )
    )
    assert meta["total_count"] == 1, (
        f"only one STRUCTURAL term exists on this policy, got {meta['total_count']}"
    )
    assert rows[0]["id"] == claim["coverage_term_id"]

    # The remaining intake defaults.
    assert claim["status"] == "SUBMITTED"
    assert claim["designated_structural"] is False
    assert claim["filed_by_owner_id"] == owner["id"]
    assert claim["substantiation_ratio"] is None
    assert claim["adjudicated_by_user_id"] is None
    assert claim["denial_date"] is None
    assert claim["escalation_deadline_date"] is None
    assert claim["claimed_amount_cents"] == 2_187_500
    assert claim["version"] == 1


def test_builder_creation_ignores_supplied_system_fields(
    api, underwriting_officer_headers
):
    """PRD 3.1: "The file also carries `obligation_period_years`, which this
    program fixes at 2 years for every builder; it is never accepted as request
    input and never varies."
    PRD 3.1: "The new file lands in `underwriting_status` `DRAFT` with no score
    at all — `risk_score`, `risk_class` and `risk_basis` are all null — and with
    its monitoring counters at rest: `earned_premium_cents` and
    `incurred_loss_cents` are 0, `loss_ratio` is 0.0000, `monitoring_posture` is
    `OPEN`, and `default_declared_at` is null."
    PRD 2.4: "Every resource this API persists carries a server-minted `id` in
    UUID form. The identifier has no type prefix and no embedded meaning:
    clients must not parse it, and the server must not accept a client-supplied
    `id` on any create."
    PRD 2.4: "Most resources additionally carry `updated_at` — same ISO 8601 UTC
    format with three fractional digits, refreshed on every mutation of the row
    — and `version`, an integer that starts at 1 when the row is created and
    increases by exactly 1 each time the row is mutated."

    Design: Corner/Table 1 Entities/builder_creation_system_fields_input_ignored
    """
    payload = create_builder_payload(
        company_name="Kestrel Build Co",
        state_code="CO",
        years_in_business=12,
        homes_closed_last_year=60,
        claims_history_score=88,
        financial_strength_tier="TIER_2",
        # System-owned fields the client must not be able to set.
        underwriting_status="APPROVED",
        obligation_period_years=5,
        id=UNASSIGNED_UUID,
        version=9,
    )
    response = api.create_builder(payload, underwriting_officer_headers)
    builder = validate_success(response, 201)
    assert_builder(builder)

    assert builder["underwriting_status"] == "DRAFT", (
        "the supplied APPROVED is discarded; a new file always lands in DRAFT"
    )
    assert builder["obligation_period_years"] == 2, (
        "the program-fixed obligation period is never accepted as request input"
    )
    assert builder["version"] == 1, "version is server-minted and starts at 1"
    assert builder["id"] != UNASSIGNED_UUID, "the id is server-minted"
    assert is_valid_uuid(builder["id"])
    assert builder["risk_score"] is None
    assert builder["risk_class"] is None
    assert builder["monitoring_posture"] == "OPEN"

    # The declared inputs were still stored.
    assert builder["company_name"] == "Kestrel Build Co"
    assert builder["state_code"] == "CO"
    assert builder["years_in_business"] == 12
    assert builder["homes_closed_last_year"] == 60
    assert builder["claims_history_score"] == 88
    assert builder["financial_strength_tier"] == "TIER_2"

    stored = read_builder(builder["id"])
    assert stored["underwriting_status"] == "DRAFT"
    assert stored["obligation_period_years"] == 2


def test_builder_creation_rejects_out_of_range_numbers_and_unknown_enums(
    api, underwriting_officer_headers
):
    """PRD 3.1: "An `UnderwritingOfficer` opens a builder file by supplying six
    declared underwriting inputs: the builder's legal `company_name` (between 1
    and 120 characters, and not blank), the `state_code` in which it is licensed
    (one of `TX`, `CO`, `AZ`, `FL` or `NC`), its `years_in_business` as a whole
    number from 0 to 100 inclusive, its `homes_closed_last_year` as a whole
    number from 0 to 5000 inclusive, a third-party `claims_history_score` from 0
    to 100 inclusive where 100 means a spotless record, and a declared
    `financial_strength_tier` of `TIER_1`, `TIER_2` or `TIER_3` describing its
    balance sheet."
    PRD 2.8 rung 8: "`ERR_INVALID_REQUEST` when a required body field is
    missing, is of the wrong type, falls outside its declared numeric range, is
    an enum value that is not a declared member, when an amount field is below
    its declared floor, or when `affected_elements` contains duplicate entries."

    Design: Corner/Table 1 Entities/builder_creation_rejects_out_of_range_numbers_and_unknown_enum_members
    """
    # Above the declared 0..100 ceiling.
    response = api.create_builder(
        create_builder_payload(claims_history_score=101),
        underwriting_officer_headers,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 422)

    # Below the declared 0..100 floor.
    response = api.create_builder(
        create_builder_payload(years_in_business=-1), underwriting_officer_headers
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 422)

    # Above the declared 0..5000 ceiling.
    response = api.create_builder(
        create_builder_payload(homes_closed_last_year=5001),
        underwriting_officer_headers,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 422)

    # Not a declared member of the tier enum.
    response = api.create_builder(
        create_builder_payload(financial_strength_tier="TIER_9"),
        underwriting_officer_headers,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 422)

    # Not a declared member of the state enum.
    response = api.create_builder(
        create_builder_payload(state_code="CA"), underwriting_officer_headers
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 422)

    # A rejected create must not have persisted a row.
    rows, meta = validate_paginated(api.list_builders(underwriting_officer_headers))
    assert meta["total_count"] == 0, (
        f"no builder file may exist after five rejected creates, got {rows}"
    )


def test_underwriting_review_rows_are_immutable_and_carry_no_version(
    api, underwriting_officer_headers
):
    """PRD 2.4: "Four resources are deliberately immutable-once-written journal
    or reference rows and carry **only** `id` and `created_at`: an underwriting
    review, a homeowner record, an engineering assessment and a reserve-journal
    entry each expose neither `updated_at` nor `version`, and no request ever
    mutates one after creation."
    PRD 3.1: "Recording a verdict creates a permanent review row that captures
    who decided and what they were looking at: `builder_id` names the file,
    `reviewer_user_id` is copied from the acting `X-User-ID`,
    `risk_score_snapshot` and `risk_class_snapshot` freeze the builder's
    `risk_score` and `risk_class` as they stood at that moment, and
    `resulting_underwriting_status` records the state the builder landed in —
    `APPROVED`, `DECLINED` or `REFERRED` respectively."
    PRD 2.3: "Three list endpoints override that default because their business
    reading order differs: the review journal of a builder is returned newest
    first, the coverage terms of a home are returned with `BASE` terms before
    `ENDORSEMENT` terms and then by `start_date` ascending, and the engineering
    assessments of a claim and the reserve journal of a claim are both returned
    oldest first."
    PRD 3.1: "The same operation also serves the referral loop: a file sitting
    in `REFERRED` — sent back for revision by an earlier decision — is taken
    into review again by the same operation, so `REFERRED → UNDER_REVIEW` is a
    legal transition alongside `SUBMITTED → UNDER_REVIEW`."

    Design: Corner/Table 1 Entities/underwriting_review_rows_are_immutable_and_carry_no_version_field
    """
    builder = create_builder_under_review()
    scored_at_review = builder["risk_score"]
    assert scored_at_review == CANONICAL_BUILDER_RISK_SCORE
    assert builder["risk_class"] == CANONICAL_BUILDER_RISK_CLASS

    referral = validate_success(
        api.create_underwriting_review(
            builder["id"], underwriting_review_payload(decision="REFER"),
            underwriting_officer_headers,
        ),
        201,
    )
    validate_success(
        api.take_builder_into_review(builder["id"], {}, underwriting_officer_headers)
    )
    approval = validate_success(
        api.create_underwriting_review(
            builder["id"], underwriting_review_payload(decision="APPROVE"),
            underwriting_officer_headers,
        ),
        201,
    )

    rows, meta = validate_paginated(
        api.list_underwriting_reviews(
            builder["id"], underwriting_officer_headers,
            {"limit": 10, "offset": 0},
        )
    )
    assert meta["total_count"] == 2, (
        f"two decisions were recorded, journal reports {meta['total_count']}"
    )
    assert meta["has_more"] is False
    assert [row["id"] for row in rows] == [approval["id"], referral["id"]], (
        "the review journal is returned newest first"
    )

    for row in rows + [referral, approval]:
        # id + created_at only: no updated_at, no version.
        assert_journal_audit_fields(row)
        assert row["builder_id"] == builder["id"]
        assert row["reviewer_user_id"] == UW_OFFICER_USER_ID
        assert row["risk_score_snapshot"] == CANONICAL_BUILDER_RISK_SCORE
        assert row["risk_class_snapshot"] == CANONICAL_BUILDER_RISK_CLASS
        assert is_iso8601_timestamp(row["created_at"])

    assert rows[0]["decision"] == "APPROVE"
    assert rows[0]["resulting_underwriting_status"] == "APPROVED"
    assert rows[1]["decision"] == "REFER"
    assert rows[1]["resulting_underwriting_status"] == "REFERRED"


def test_enrollment_naming_an_unknown_builder_returns_builder_not_found(
    api, underwriting_officer_headers
):
    """PRD 2.6: "The same catalogue applies to foreign keys supplied in a
    request body rather than in the path. A `builder_id` that does not resolve
    yields `ERR_BUILDER_NOT_FOUND`; an `initial_owner_id` or `new_owner_id`,
    `ERR_HOMEOWNER_NOT_FOUND`; a `policy_id`, `ERR_POLICY_NOT_FOUND`; a
    `neutral_id`, `ERR_NEUTRAL_NOT_FOUND`; a `prior_case_id`,
    `ERR_ESCALATION_CASE_NOT_FOUND`; a `reserve_entry_id`,
    `ERR_RESERVE_ENTRY_NOT_FOUND`. Body-level foreign-key resolution is checked
    on home enrollment, on transfer request creation, on claim filing, on the
    opening of an escalation rung, and on a payment reversal."
    PRD 2.1: "Concretely, the addressed builder is either the builder named in
    the URL path, or the `builder_id` of the addressed policy, or the
    `builder_id` of the policy behind the addressed claim, and a mismatch is
    refused with `ERR_NOT_BUILDER_PRINCIPAL` and HTTP 403."

    Design: Corner/Table 1 Entities/policy_enrollment_with_an_unknown_builder_id_returns_builder_not_found
    """
    owner = create_homeowner()
    set_clock(CANONICAL_CLOSING_INSTANT)

    payload = create_policy_payload(UNASSIGNED_UUID, owner["id"])
    # Acting as the principal of the very builder named in the body, so the
    # ownership rung is satisfied and only the body foreign key can fail.
    response = api.create_policy(
        payload, make_builder_principal_headers(UNASSIGNED_UUID)
    )
    error_data = validate_error(response, ApiErrorId.ERR_BUILDER_NOT_FOUND.value, 404)
    # PRD 2.2: response_type sits on the envelope, error_id/message inside data.
    assert response.json()["response_type"] == "error"
    assert error_data["message"].strip()

    rows, meta = validate_paginated(
        api.list_policies(
            underwriting_officer_headers, {"initial_owner_id": owner["id"]}
        )
    )
    assert meta["total_count"] == 0, (
        f"the rejected enrollment must not have created a policy, got {rows}"
    )


def test_second_transfer_request_supersedes_the_first_and_links_back_to_it(
    api, underwriting_officer_headers
):
    """PRD 3.5: "Requests supersede rather than queue. If the policy already has
    an open request — the row named by the policy's `pending_transfer_id`, in
    `status` `REQUESTED` or `NEEDS_DOCUMENTATION` — that row transitions to the
    terminal `SUPERSEDED` and its `version` advances by 1, and the new row's
    `prior_transfer_id` is set to the superseded row's `id`, forming an
    auditable chain of attempts. When no request was open, the new row's
    `prior_transfer_id` stays null. Either way the policy's
    `pending_transfer_id` is set to the new request's `id` and the policy's
    `version` advances by 1."
    PRD 3.5: "Its `transfer_fee_cents` is computed at that moment as a base fee
    of 7,500 cents plus 2,500 cents for each transfer already recorded on the
    policy — so the first hand-off costs seventy-five dollars, the second one
    hundred, the third one hundred and twenty-five."
    PRD 3.5: "The multiplier is the policy's `transfer_count`, which counts only
    transfers that reached `RECORDED`; superseded and rejected requests never
    raise it and never raise the fee."
    PRD 2.6: "Transfers are filterable by `policy_id`, `new_owner_id`,
    `prior_transfer_id` and `status`."

    Design: Corner/Table 1 Entities/graph_topology_second_transfer_request_supersedes_the_first_and_links_back_to_it
    """
    scenario = setup_active_policy()
    policy = scenario["policy"]
    seller = scenario["homeowner"]
    seller_headers = make_homeowner_headers(seller["id"])

    first_buyer = create_homeowner(
        full_name="Ben Calloway", email="ben.calloway@example.com"
    )
    second_buyer = create_homeowner(
        full_name="Cara Devlin", email="cara.devlin@example.com"
    )

    first = request_transfer(
        policy["id"], seller["id"], first_buyer["id"],
        expected_policy_version=policy["version"],
        transfer_date="2026-09-01", documents_reference="DEED-2026-0901",
    )
    assert first["status"] == "REQUESTED"
    assert first["prior_transfer_id"] is None, (
        "with no request open, the first attempt links back to nothing"
    )
    after_first = read_policy(policy["id"])
    assert after_first["pending_transfer_id"] == first["id"]

    second = validate_success(
        api.create_transfer(
            policy["id"],
            create_transfer_payload(
                second_buyer["id"], after_first["version"],
                transfer_date="2026-09-10",
                documents_reference="DEED-2026-0910",
            ),
            seller_headers,
        ),
        201,
    )
    assert_transfer(second)
    assert second["status"] == "REQUESTED"
    assert second["new_owner_id"] == second_buyer["id"]
    assert second["prior_transfer_id"] == first["id"], (
        "the new row links back to the row it superseded"
    )
    assert second["version"] == 1

    superseded = read_transfer(first["id"])
    assert superseded["status"] == "SUPERSEDED", (
        f"the open request must be superseded, found {superseded['status']}"
    )
    assert superseded["version"] == first["version"] + 1

    # No transfer was recorded, so neither fee moved off the base.
    assert second["transfer_fee_cents"] == TRANSFER_BASE_FEE_CENTS
    assert superseded["transfer_fee_cents"] == TRANSFER_BASE_FEE_CENTS

    after_second = read_policy(policy["id"])
    assert after_second["pending_transfer_id"] == second["id"]
    assert after_second["version"] == after_first["version"] + 1
    assert after_second["transfer_count"] == 0
    assert after_second["current_owner_id"] == seller["id"], (
        "only recording rewrites ownership"
    )

    # The reverse-reachability channel exposes the chain.
    rows, meta = validate_paginated(
        api.list_transfers(
            underwriting_officer_headers, {"prior_transfer_id": first["id"]}
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == second["id"]

    rows, meta = validate_paginated(
        api.list_transfers(underwriting_officer_headers, {"policy_id": policy["id"]})
    )
    assert meta["total_count"] == 2
    assert {row["id"] for row in rows} == {first["id"], second["id"]}
