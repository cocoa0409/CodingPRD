"""
Entity shape: creation echoes, declared defaults, computed fields and graph edges.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_DEAL_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_TAXONOMY_CYCLE,
    ERR_VALUE_OUT_OF_RANGE,
)
from test_helpers.assertions import (
    assert_envelope_meta,
    assert_field,
    assert_fields,
    assert_money,
    assert_null,
    assert_pagination_meta,
    assert_substantiation,
)
from test_helpers.constants import DEFAULT_REQUIRED_QUESTION_KEYS
from test_helpers.fixtures import WinLossWorld


def _completed_chain_with_two_kinds_of_evidence(world: WinLossWorld) -> WinLossWorld:
    """A completed interview holding a positioning answer and a pricing answer."""
    world.set_clock("2026-08-01T00:00:00.000Z")
    world.active_program()
    world.create_competitor()
    world.create_analyst()
    world.create_deal(primary_competitor_id=world.competitor["id"])
    world.consented_contact(incentive_eligibility="ELIGIBLE")
    world.create_frame()
    world.seal_frame()
    world.draw("LOST", requested_count=1)
    world.schedule_interview()
    world.record_response(
        question_key="COMPETITOR_POSITIONING",
        verbatim_text="Northwind demoed deeper analytics",
        recorded_at="2026-08-01T10:00:00.000Z",
        rating=4,
        competitor_name_verbatim="Northwind",
    )
    world.record_response(
        question_key="PRICING_PERCEPTION",
        verbatim_text="List price felt high for the tier",
        recorded_at="2026-08-01T10:10:00.000Z",
    )
    world.record_response(
        question_key="EVALUATION_CRITERIA",
        verbatim_text="Integration depth ranked first",
        recorded_at="2026-08-01T10:20:00.000Z",
    )
    world.set_clock("2026-08-10T15:30:00.000Z")
    world.complete_interview(
        actual_start_at="2026-08-10T14:00:00.000Z",
        actual_end_at="2026-08-10T15:00:00.000Z",
    )
    world.create_battlecard()
    return world


# ---------------------------------------------------------------------------


def test_program_creation_echoes_every_supplied_optional_input(world):
    """Explicit optionals are stored as given while computed fields are minted.

    "A `ProgramAdmin` opens the quarter by creating a program with a human `name`, a
    `fiscal_quarter` label (a non-empty string whose format the server does not
    otherwise validate), an `incentive_budget_usd`, an `interview_incentive_cap_usd`
    that ceilings any single buyer payment, and a `min_deal_value_usd` that sets the
    inclusive revenue floor for sampling eligibility."

    "A newly created program has `status` `DRAFT`, `posture` `OPEN`, `guide_version` 1,
    all three ledger fields at 0, and `version` 1."

    Design: Corner/entities/program_creation_echoes_supplied_optional_inputs
    """
    world.set_clock("2026-08-01T00:00:00.000Z")

    response = world.api.create_program(
        f.program_payload(
            name="Q3 Win-Loss",
            fiscal_quarter="2026-Q3",
            required_question_keys=[
                "EVALUATION_CRITERIA",
                "COMPETITOR_POSITIONING",
                "PRICING_PERCEPTION",
                "LOSS_REASON",
            ],
            max_open_interviews_per_analyst=5,
            independence_mode="ADVISORY",
        ),
        world.admin,
    )
    body = validate_success(response, 201)
    program = body

    assert_fields(
        program,
        {
            "name": "Q3 Win-Loss",
            "fiscal_quarter": "2026-Q3",
            "max_open_interviews_per_analyst": 5,
            "independence_mode": "ADVISORY",
            "status": "DRAFT",
            "posture": "OPEN",
            "guide_version": 1,
            "version": 1,
        },
    )
    assert len(program["required_question_keys"]) == 4, program["required_question_keys"]
    assert_money(program["incentive_budget_usd"], 10000.00, "incentive_budget_usd")
    assert_money(program["interview_incentive_cap_usd"], 500.00, "cap")
    assert_money(program["min_deal_value_usd"], 50000.00, "min_deal_value_usd")
    assert_money(program["incentive_committed_usd"], 0.00, "committed")
    assert_money(program["incentive_paid_usd"], 0.00, "paid")
    assert is_valid_uuid(program["id"]), f"id is not a bare UUID: {program['id']}"
    assert is_iso8601_timestamp(program["created_at"]), program["created_at"]
    assert is_iso8601_timestamp(program["updated_at"]), program["updated_at"]
    assert_envelope_meta(response.json())


def test_omitted_optionals_fall_back_to_the_declared_defaults(world):
    """Three guide keys, three open interviews, STRICT independence, no sales tie.

    "Three further inputs are optional. `required_question_keys` declares the
    interview-guide topics every interview must cover and defaults to the three-topic
    set `EVALUATION_CRITERIA`, `COMPETITOR_POSITIONING` and `PRICING_PERCEPTION`.
    `max_open_interviews_per_analyst` caps how many interviews one analyst may hold
    open at once and defaults to 3. `independence_mode` defaults to `STRICT`, the
    alternative being `ADVISORY`."

    "A new analyst has `status` `ACTIVE`, `open_interview_count` 0 and
    `committed_minutes` 0."

    Design: Corner/entities/program_and_analyst_defaults_applied_when_optionals_omitted
    """
    world.set_clock("2026-08-01T00:00:00.000Z")
    program = world.create_program(name="Defaults Program", fiscal_quarter="2026-Q3")

    body = validate_success(
        world.api.create_analyst(f.analyst_payload(program["id"]), world.admin), 201
    )
    analyst = body

    assert_fields(
        analyst,
        {
            "sales_org_member": False,
            "status": "ACTIVE",
            "open_interview_count": 0,
            "committed_minutes": 0,
        },
    )
    stored = world.refresh_program()
    assert_field(
        stored, "required_question_keys", list(DEFAULT_REQUIRED_QUESTION_KEYS)
    )
    assert_field(stored, "max_open_interviews_per_analyst", 3)
    assert_field(stored, "independence_mode", "STRICT")


def test_reading_a_program_mutates_nothing(world):
    """The persisted row comes back as stored, with its version untouched.

    "Setting the clock mutates no entity; it only changes how subsequent requests
    evaluate temporal predicates."

    Design: Corner/entities/program_retrieval_returns_stored_entity_unchanged
    """
    world.set_clock("2026-08-01T00:00:00.000Z")
    created = world.create_program(name="Q3 Win-Loss", fiscal_quarter="2026-Q3")

    body = validate_success(world.api.get_program(created["id"], world.admin), 200)
    program = body

    assert_fields(
        program,
        {
            "id": created["id"],
            "name": "Q3 Win-Loss",
            "status": "DRAFT",
            "version": 1,
        },
    )


def test_the_deal_listing_counts_the_filtered_set_not_the_page(world):
    """Three deals with a limit of two: two rows, a total of three, more to come.

    "Pagination-related fields in `meta` (`limit`, `offset`, `total_count`,
    `has_more`) are included for list endpoints."

    Design: Corner/entities/deals_listing_paginates_with_total_count_and_has_more
    """
    world.set_clock("2026-08-01T00:00:00.000Z")
    world.create_program(name="Q3 Win-Loss", fiscal_quarter="2026-Q3")
    world.create_deal()
    world.create_deal(
        crm_deal_ref="CRM-1002",
        acr_usd=120000.00,
        close_date="2026-06-16T00:00:00.000Z",
        segment="MIDMARKET",
        sales_rep_user_ref="rep-78",
    )
    world.create_deal(
        crm_deal_ref="CRM-1003",
        outcome="WON",
        acr_usd=90000.00,
        close_date="2026-06-17T00:00:00.000Z",
        segment="SMB",
        sales_rep_user_ref="rep-79",
    )

    response = world.api.list_deals(
        world.admin, {"program_id": world.program_id, "limit": 2, "offset": 0}
    )
    items, meta = validate_paginated(response)

    assert len(items) == 2, f"expected a page of two, got {len(items)}"
    assert_pagination_meta(
        meta, expected_total=3, expected_limit=2, expected_offset=0, expected_has_more=True
    )


def test_an_unknown_deal_id_reports_the_deals_own_not_found_code(world):
    """A well-formed but unknown identifier is a 404 naming the deal.

    "Each unresolvable variable maps to its own not-found code:
    `ERR_PROGRAM_NOT_FOUND`, `ERR_COMPETITOR_NOT_FOUND`, `ERR_DEAL_NOT_FOUND`"

    Design: Corner/entities/deal_retrieval_with_unknown_id_returns_deal_not_found
    """
    world.set_clock("2026-08-01T00:00:00.000Z")

    response = world.api.get_deal(NON_EXISTENT_UUID, world.admin)
    validate_error(response, ERR_DEAL_NOT_FOUND, 404)

    envelope = response.json()
    assert envelope["response_type"] == "error", envelope["response_type"]


def test_omitting_a_required_program_input_is_a_structural_failure(world):
    """A missing required body field is a 400, not a business refusal.

    "Required body fields must be present, JSON types must match, every enum-typed
    value must be a declared member of its enumeration, arrays that must be non-empty
    must be non-empty, and datetimes must be well formed; any failure returns
    `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/program_creation_missing_required_min_deal_value_rejected
    """
    world.set_clock("2026-08-01T00:00:00.000Z")

    validate_error(
        world.api.create_program(
            f.program_payload(
                name="Q3 Win-Loss", fiscal_quarter="2026-Q3", min_deal_value_usd=f.OMIT
            ),
            world.admin,
        ),
        ERR_INVALID_REQUEST,
        400,
    )


def test_an_undeclared_outcome_value_is_rejected_before_any_range_check(world):
    """`PENDING` is not a member of the outcome enumeration.

    "an `outcome` of `WON`, `LOST` or `NO_DECISION`"

    Design: Corner/entities/deal_creation_with_undeclared_outcome_enum_rejected
    """
    world.set_clock("2026-08-01T00:00:00.000Z")
    world.create_program(name="Q3 Win-Loss", fiscal_quarter="2026-Q3")

    validate_error(
        world.api.create_deal(
            f.deal_payload(world.program_id, outcome="PENDING"), world.admin
        ),
        ERR_INVALID_REQUEST,
        400,
    )


def test_a_negative_contract_value_is_a_numeric_domain_failure(world):
    """The type is fine, so only the domain rule fires, at a different status.

    "`acr_usd` must be greater than zero"

    Design: Corner/entities/deal_creation_with_negative_acr_rejected
    """
    world.set_clock("2026-08-01T00:00:00.000Z")
    world.create_program(name="Q3 Win-Loss", fiscal_quarter="2026-Q3")

    validate_error(
        world.api.create_deal(
            f.deal_payload(world.program_id, acr_usd=-5000.00), world.admin
        ),
        ERR_VALUE_OUT_OF_RANGE,
        422,
    )


def test_client_supplied_draw_time_fields_are_discarded_on_import(world):
    """A fresh deal is born unselected no matter what the body claims.

    "A fresh deal has `research_status` `NOT_SELECTED`, `attribution_status`
    `UNATTRIBUTED`, `interview_coverage_count` 0, and null values for
    `sampling_frame_id`, `stratum` and `selection_rank_score`."

    Design: Corner/entities/deal_selection_rank_score_input_ignored
    """
    world.set_clock("2026-08-01T00:00:00.000Z")
    world.create_program(name="Q3 Win-Loss", fiscal_quarter="2026-Q3")

    body = validate_success(
        world.api.create_deal(
            f.deal_payload(world.program_id, selection_rank_score=0.9999, stratum="WON"),
            world.admin,
        ),
        201,
    )
    deal = body

    assert_null(deal["selection_rank_score"], "selection_rank_score")
    assert_null(deal["stratum"], "stratum")
    assert_null(deal["sampling_frame_id"], "sampling_frame_id")
    assert_fields(
        deal,
        {
            "research_status": "NOT_SELECTED",
            "attribution_status": "UNATTRIBUTED",
            "interview_coverage_count": 0,
        },
    )


def test_client_supplied_lifecycle_and_ledger_fields_are_discarded(world):
    """A program can only be born DRAFT, at guide version one, with an empty ledger.

    "Fields the server computes or manages itself are also ignored when a client
    supplies them — never rejected."

    Design: Corner/entities/program_status_and_guide_version_are_system_fields_input_ignored
    """
    world.set_clock("2026-08-01T00:00:00.000Z")

    body = validate_success(
        world.api.create_program(
            f.program_payload(
                name="Q3 Win-Loss",
                fiscal_quarter="2026-Q3",
                status="ACTIVE",
                guide_version=9,
                incentive_paid_usd=4000.00,
                version=7,
            ),
            world.admin,
        ),
        201,
    )
    program = body

    assert_fields(
        program,
        {"status": "DRAFT", "guide_version": 1, "posture": "OPEN", "version": 1},
    )
    assert_money(program["incentive_paid_usd"], 0.00, "incentive_paid_usd")
    assert_money(program["incentive_committed_usd"], 0.00, "incentive_committed_usd")


def test_adding_a_contact_beneath_an_unknown_deal_reports_the_parent(world):
    """The path segment is resolved before the body is looked at.

    "Path variables are resolved strictly left to right, so the outermost missing
    segment is the one reported."

    Design: Corner/entities/buyer_contact_creation_under_unknown_deal_returns_deal_not_found
    """
    world.set_clock("2026-08-01T00:00:00.000Z")
    world.active_program()
    world.create_analyst()

    validate_error(
        world.api.create_buyer_contact(
            NON_EXISTENT_UUID, f.buyer_contact_payload(), world.analyst_headers
        ),
        ERR_DEAL_NOT_FOUND,
        404,
    )


def test_a_recorded_answer_carries_no_version_or_update_stamp(world):
    """Evidence is append-only, so it has nothing to version.

    "Answers are immutable append-only evidence: there is no update path, and as
    noted in §2.4 the row carries neither `updated_at` nor `version`."

    Design: Corner/entities/interview_response_is_immutable_and_carries_no_version_field
    """
    world.set_clock("2026-08-01T00:00:00.000Z")
    world.active_program()
    world.create_competitor()
    world.create_analyst()
    world.create_deal(primary_competitor_id=world.competitor["id"])
    world.consented_contact(incentive_eligibility="ELIGIBLE")
    world.create_frame()
    world.seal_frame()
    world.draw("LOST", requested_count=1)
    world.schedule_interview()
    recorded = world.record_response(
        question_key="EVALUATION_CRITERIA",
        verbatim_text="Ranked security first",
        recorded_at="2026-08-01T10:00:00.000Z",
        rating=3,
    )

    body = validate_success(
        world.api.get_interview_response(recorded["id"], world.admin), 200
    )
    response_row = body

    assert "version" not in response_row, f"unexpected version: {sorted(response_row)}"
    assert "updated_at" not in response_row, (
        f"unexpected updated_at: {sorted(response_row)}"
    )
    assert response_row["id"] == recorded["id"], response_row["id"]
    assert is_iso8601_timestamp(response_row["created_at"]), response_row["created_at"]
    assert_field(response_row, "question_key", "EVALUATION_CRITERIA")
    assert_field(response_row, "rating", 3)
    assert response_row["recorded_at"] == "2026-08-01T10:00:00.000Z", (
        response_row["recorded_at"]
    )


def test_reparenting_a_node_under_its_own_child_is_refused(world):
    """A cycle would make the root-ancestor walk non-terminating.

    "The proposed parent may be neither the node itself nor any of its descendants; a
    cycle would make the root-ancestor walk non-terminating and is refused with
    `ERR_TAXONOMY_CYCLE`."

    Design: Corner/entities/loss_reason_reparent_to_own_descendant_rejected
    """
    world.set_clock("2026-08-01T00:00:00.000Z")
    world.create_program(name="Q3 Win-Loss", fiscal_quarter="2026-Q3")
    root = world.create_reason("PRICE", "Price")
    child = world.create_reason(
        "PRICE_DISCOUNT", "Discount depth", parent_reason_id=root["id"]
    )

    validate_error(
        world.api.patch_loss_reason(
            root["id"], {"parent_reason_id": child["id"]}, world.admin
        ),
        ERR_TAXONOMY_CYCLE,
        409,
    )

    stored_root = world.get_reason(root["id"])
    assert_field(stored_root, "depth", 1)
    assert_null(stored_root["parent_reason_id"], "parent_reason_id")
    assert_field(stored_root, "is_leaf", False)
    stored_child = world.get_reason(child["id"])
    assert_field(stored_child, "depth", 2)
    assert_field(stored_child, "is_leaf", True)


def test_one_claim_cites_two_answers_and_sums_both_source_weights(world):
    """The evidence array is a many-to-many edge, and every item contributes.

    "1.00 for `COMPETITOR_POSITIONING`, 0.90 for `PRICING_PERCEPTION`, 0.70 for
    `EVALUATION_CRITERIA`, 0.50 for `LOSS_REASON` and 0.40 for `PRODUCT_GAP`"

    Design: Corner/entities/battlecard_claim_evidence_array_links_many_responses_to_one_claim
    """
    _completed_chain_with_two_kinds_of_evidence(world)

    body = validate_success(
        world.api.create_claim(
            world.battlecard["id"],
            f.claim_payload(
                [
                    world.response_of("COMPETITOR_POSITIONING")["id"],
                    world.response_of("PRICING_PERCEPTION")["id"],
                ],
                claim_text="Buyers rate our analytics depth against Northwind",
                claim_type="FEATURE",
            ),
            world.analyst_headers,
        ),
        201,
    )
    claim = body

    assert len(claim["evidence_response_ids"]) == 2, claim["evidence_response_ids"]
    assert_substantiation(claim, 1.90, "ANECDOTAL", "MEDIUM")
    assert_field(claim, "legal_status", "PENDING")
    assert_null(claim["conditions_note"], "conditions_note")
    assert_null(claim["decided_at"], "decided_at")
