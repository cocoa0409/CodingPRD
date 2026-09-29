"""Record-level shape: what a create returns, what a read returns, and what the
server refuses to take from the client.

These exercises stay close to the persisted rows themselves — the field set a
fresh reporting cycle already carries, the two membership roll-ups a charter
recomputes, the defaults an omitted optional input falls back to, and the
identity and status fields a create ignores when a client supplies them.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.assertions import (
    assert_fresh_record,
    assert_instant_equals,
    assert_money,
)
from test_helpers.factories import (
    action_payload,
    charter_payload,
    cycle_payload,
    document_payload,
    member_payload,
    milestone_payload,
    subcert_payload,
)
from test_helpers.fixtures import (
    add_milestone,
    add_tie_out,
    assign_subcert,
    build_committee,
    build_cycle,
    cycle_version,
    open_close,
    refresh_cycle,
)
from test_helpers.test_users import admin_headers

SOLE_FINANCE_SEAT = [("fin", "Nora Finance", "FINANCE", False, True)]
ROLLUP_SEATS = [
    ("fin", "Nora Finance", "FINANCE", False, True),
    ("legal", "Owen Legal", "LEGAL", False, True),
    ("ops", "Pia Ops", "OPERATIONS", False, False),
]
CHARTER_NAME = "Q2 Disclosure Committee Charter"


def _finance_committee(api, name=CHARTER_NAME, version_label="2026.1", adopt=True):
    """One ADOPTED charter carrying a single ACTIVE voting FINANCE seat."""
    return build_committee(
        api,
        seats=SOLE_FINANCE_SEAT,
        min_quorum_count=1,
        required_functions=["FINANCE"],
        name=name,
        version_label=version_label,
        adopt=adopt,
        chair_key="fin",
    )


def test_a_fresh_reporting_cycle_returns_its_whole_computed_field_set_at_once(api):
    """A single create returns 201 with both calendar anchors already resolved,
    both slack figures at the empty-set sentinel 9999, the three aggregates at
    zero and the workflow and remediation axes at their initial states, so no
    second read is needed to observe any of them.

    PRD 3.2: "Beyond the two computed instants, a new cycle is initialised with `status` `PLANNING`, `restatement_stage` `NONE`, `min_slack_days_calendar` and `min_slack_days_business` both 9999, `total_assigned_scope_weight` 0.00, `certification_coverage_pct` 0.00, `open_material_event_count` 0 and `unresolved_deficiency_weight` 0.00."

    Design: Corner/entities/reporting_cycle_creation_returns_the_full_computed_and_system_field_set
    """
    committee = _finance_committee(api)

    created = validate_success(
        api.create_cycle(cycle_payload(committee.id), admin_headers()), 201
    )
    assert_fresh_record(created)
    assert created["fiscal_period_label"] == "FY2026-Q2"
    assert created["form_type"] == "FORM_10Q"
    assert created["filer_status"] == "LARGE_ACCELERATED"
    assert created["charter_id"] == committee.id
    assert_instant_equals(created["statutory_deadline_utc"], "2026-08-10T17:30:00Z")
    assert_instant_equals(created["internal_target_utc"], "2026-08-05T17:30:00Z")
    assert created["status"] == "PLANNING"
    assert created["restatement_stage"] == "NONE"
    assert created["min_slack_days_calendar"] == 9999
    assert created["min_slack_days_business"] == 9999
    assert_money(created["total_assigned_scope_weight"], 0.00)
    assert_money(created["certification_coverage_pct"], 0.00)
    assert created["open_material_event_count"] == 0
    assert_money(created["unresolved_deficiency_weight"], 0.00)


def test_a_charter_read_returns_stored_input_beside_its_recomputed_rollups(api):
    """The charter read hands back name, version label, quorum count and required
    functions exactly as supplied, and beside them the two roll-ups derived from
    the seats: the non-voting operations seat is left out of the voting count but
    still contributes its function to the alphabetically sorted covered list, and
    adoption stamped the charter from the logical clock.

    PRD 3.1: "`active_voting_member_count` is the number of committee members on this charter whose `status` is `ACTIVE` and whose `voting` flag is true."

    Design: Corner/entities/charter_retrieval_returns_stored_input_plus_recomputed_membership_rollups
    """
    committee = build_committee(
        api,
        seats=ROLLUP_SEATS,
        min_quorum_count=2,
        required_functions=["FINANCE", "LEGAL"],
        name=CHARTER_NAME,
        version_label="2026.1",
    )

    read = validate_success(api.get_charter(committee.id, admin_headers()))
    assert read["name"] == CHARTER_NAME
    assert read["version_label"] == "2026.1"
    assert read["min_quorum_count"] == 2
    assert read["required_functions"] == ["FINANCE", "LEGAL"]
    assert read["status"] == "ADOPTED"
    assert_instant_equals(read["adopted_at_utc"], "2026-08-01T00:00:00Z")
    assert read["active_voting_member_count"] == 2
    assert read["covered_functions"] == ["FINANCE", "LEGAL", "OPERATIONS"]
    assert read["superseded_by_charter_id"] is None


LISTING_SEATS_A = [
    ("fin", "Nora Finance", "FINANCE", False, True),
    ("legal", "Owen Legal", "LEGAL", False, True),
    ("ops", "Pia Ops", "OPERATIONS", False, True),
]
LISTING_SEATS_B = [("fin", "Quin Finance", "FINANCE", False, True)]


def test_the_member_listing_composes_its_charter_filter_with_the_page_window(api):
    """Three seats sit on one charter and a fourth on another; the filtered first
    page returns two rows out of a total of three with more remaining, the second
    page returns the single leftover with nothing remaining, and the stranger seat
    appears under neither page — so the filter is applied before the window and
    the count reports the filtered population rather than the table.

    PRD 2.3: "`total_count` is the number of rows matching the filters before the page window is applied, and `has_more` is true exactly when rows remain after the current window."

    Design: Corner/entities/committee_member_listing_paginates_and_filters_by_charter_id
    """
    committee_a = build_committee(
        api,
        seats=LISTING_SEATS_A,
        min_quorum_count=1,
        required_functions=["FINANCE"],
        name="Charter A",
        version_label="A-1",
        adopt=False,
    )
    committee_b = build_committee(
        api,
        seats=LISTING_SEATS_B,
        min_quorum_count=1,
        required_functions=["FINANCE"],
        name="Charter B",
        version_label="B-1",
        adopt=False,
    )
    stranger_id = committee_b.mid("fin")

    first_rows, first_meta = validate_paginated(
        api.list_members(admin_headers(), charter_id=committee_a.id, limit=2, offset=0)
    )
    assert len(first_rows) == 2
    assert first_meta["limit"] == 2
    assert first_meta["offset"] == 0
    assert first_meta["total_count"] == 3
    assert first_meta["has_more"] is True

    second_rows, second_meta = validate_paginated(
        api.list_members(admin_headers(), charter_id=committee_a.id, limit=2, offset=2)
    )
    assert len(second_rows) == 1
    assert second_meta["limit"] == 2
    assert second_meta["offset"] == 2
    assert second_meta["total_count"] == 3
    assert second_meta["has_more"] is False

    seen = [row["id"] for row in first_rows + second_rows]
    assert stranger_id not in seen
    assert len(set(seen)) == 3
    for row in first_rows + second_rows:
        assert row["charter_id"] == committee_a.id


UNKNOWN_CHARTER = "00000000-0000-4000-8000-000000000001"
UNKNOWN_MEMBER = "00000000-0000-4000-8000-000000000002"
UNKNOWN_CYCLE = "00000000-0000-4000-8000-000000000003"
UNKNOWN_SUBCERT = "00000000-0000-4000-8000-000000000004"
UNKNOWN_DOCUMENT = "00000000-0000-4000-8000-000000000005"
UNKNOWN_FILING = "00000000-0000-4000-8000-000000000006"


def test_each_unknown_path_id_reports_the_code_belonging_to_its_own_segment(api):
    """Six reads against syntactically valid but unknown identifiers against an
    empty database return six different codes rather than one generic one, each
    naming the entity that owns the path segment that failed to resolve.

    PRD 2.7: "The code emitted is the not-found variant belonging to the failing segment: `ERR_CHARTER_NOT_FOUND`, `ERR_MEMBER_NOT_FOUND`, `ERR_CYCLE_NOT_FOUND`, `ERR_MILESTONE_NOT_FOUND`, `ERR_SUBCERT_NOT_FOUND`, `ERR_OFFICER_CERT_NOT_FOUND`, `ERR_DOCUMENT_NOT_FOUND`, `ERR_TIE_OUT_ITEM_NOT_FOUND`, `ERR_MEASURE_NOT_FOUND`, `ERR_QA_ITEM_NOT_FOUND`, `ERR_EVENT_NOT_FOUND`, `ERR_FILING_NOT_FOUND`, `ERR_CORRECTION_NOT_FOUND` or `ERR_DEFICIENCY_NOT_FOUND` — all HTTP 404."

    Design: Corner/entities/path_ids_that_match_no_row_return_the_entity_specific_not_found_code
    """
    empty_rows, empty_meta = validate_paginated(
        api.list_charters(admin_headers(), limit=1, offset=0)
    )
    assert empty_rows == []
    assert empty_meta["total_count"] == 0

    validate_error(
        api.get_charter(UNKNOWN_CHARTER, admin_headers()), "ERR_CHARTER_NOT_FOUND", 404
    )
    validate_error(
        api.get_member(UNKNOWN_MEMBER, admin_headers()), "ERR_MEMBER_NOT_FOUND", 404
    )
    validate_error(
        api.get_cycle(UNKNOWN_CYCLE, admin_headers()), "ERR_CYCLE_NOT_FOUND", 404
    )
    validate_error(
        api.get_subcert(UNKNOWN_SUBCERT, admin_headers()), "ERR_SUBCERT_NOT_FOUND", 404
    )
    validate_error(
        api.get_document(UNKNOWN_DOCUMENT, admin_headers()), "ERR_DOCUMENT_NOT_FOUND", 404
    )
    missing_filing = api.get_filing(UNKNOWN_FILING, admin_headers())
    validate_error(missing_filing, "ERR_FILING_NOT_FOUND", 404)
    body = missing_filing.json()
    assert body["response_type"] == "error"
    assert body["data"]["message"]


def test_a_dropped_required_field_and_a_zero_base_share_the_request_shape_code(api):
    """An otherwise complete cycle payload missing its form type is rejected, and
    so is the complete payload whose materiality base sits at zero rather than
    strictly above it; both come back as request-shape failures, both persist
    nothing, and neither touches the pinned charter.

    PRD 2.7: "Request-shape validation follows: the body must parse, every required input field must be present, every enum-typed value must be a member of its declared domain, numeric fields must be numbers and must respect the non-negativity their descriptions state, ISO 8601 instants must parse, and `reconciliation_items` must be a list of objects each carrying a `label` string and an `amount` number."

    Design: Corner/entities/cycle_create_missing_required_form_type_returns_invalid_request
    """
    committee = _finance_committee(api)
    before = validate_success(api.get_charter(committee.id, admin_headers()))

    without_form_type = dict(cycle_payload(committee.id))
    without_form_type.pop("form_type")
    validate_error(
        api.create_cycle(without_form_type, admin_headers()), "ERR_INVALID_REQUEST", 422
    )

    validate_error(
        api.create_cycle(
            cycle_payload(committee.id, materiality_base_amount=0), admin_headers()
        ),
        "ERR_INVALID_REQUEST",
        422,
    )

    rows, meta = validate_paginated(
        api.list_cycles(admin_headers(), charter_id=committee.id, limit=10, offset=0)
    )
    assert rows == []
    assert meta["total_count"] == 0

    after = validate_success(api.get_charter(committee.id, admin_headers()))
    assert after["version"] == before["version"]


DEFAULTED_SEAT = [("fin", "Nora Finance", "FINANCE", None, None)]


def test_four_omitted_optional_inputs_fall_back_to_their_declared_defaults(api):
    """A seat created with nothing but a name and a function reads as a
    non-officer voting seat and therefore satisfies quorum on its own; a cycle
    created without a buffer uses five calendar days, which puts its internal
    target five days before the statutory deadline; and a freshly assigned
    request carries the pending trio of defaults with its base weight.

    PRD 3.1: "Two optional flags shape what the seat can do: `is_officer`, which defaults to false and marks a corporate officer eligible to sign officer certifications, and `voting`, which defaults to true and determines whether the seat counts toward charter quorum."

    PRD 3.4: "A new request is persisted with `status` `PENDING`, `exception_severity` `NONE`, a null `exception_note` and a null `submitted_utc`, so its initial weight is simply its base possibly lifted by the officer factor."

    Design: Corner/entities/omitted_optional_inputs_fall_back_to_their_declared_defaults
    """
    committee = build_committee(
        api,
        seats=DEFAULTED_SEAT,
        min_quorum_count=1,
        required_functions=["FINANCE"],
        name="Defaults Charter",
        version_label="2026.1",
        chair_key="fin",
    )
    seat = committee.member("fin")
    assert seat["is_officer"] is False
    assert seat["voting"] is True
    assert seat["status"] == "ACTIVE"
    assert committee.charter["status"] == "ADOPTED"

    cycle = validate_success(
        api.create_cycle(
            cycle_payload(committee.id, internal_buffer_days=None), admin_headers()
        ),
        201,
    )
    assert cycle["internal_buffer_days"] == 5
    assert_instant_equals(cycle["internal_target_utc"], "2026-08-05T17:30:00Z")

    add_milestone(
        api, committee, cycle["id"], "CLOSE",
        "2026-08-01T00:00:00Z", "2026-08-03T00:00:00Z",
    )
    open_close(api, committee, cycle["id"])

    row = assign_subcert(
        api, committee, cycle["id"], "fin", "REVENUE",
        due_utc="2026-08-04T17:00:00Z", chair_key="fin",
    )
    assert row["status"] == "PENDING"
    assert row["exception_severity"] == "NONE"
    assert row["exception_note"] is None
    assert row["submitted_utc"] is None
    assert_money(row["scope_weight"], 30.00)
    assert_instant_equals(row["prep_window_start_utc"], "2026-08-01T17:00:00Z")


def _close_open_cycle(api, name):
    """An ADOPTED single-seat charter whose cycle carries one CLOSE window and
    has been driven to CLOSE_OPEN."""
    committee = _finance_committee(api, name=name)
    cycle = build_cycle(api, committee)
    add_milestone(
        api, committee, cycle["id"], "CLOSE",
        "2026-08-01T00:00:00Z", "2026-08-03T00:00:00Z",
    )
    open_close(api, committee, cycle["id"])
    return committee, cycle


def test_the_five_document_gate_fields_ignore_the_values_the_client_supplies(api):
    """The create carries a passed tie-out schedule, a cleared measure gate and a
    zero variance total in its body, yet the persisted row reads the server's own
    initial values instead; a single exact-match tie-out line then moves the
    tie-out gate to passed on its own while the measure gate stays at its
    no-measures reading.

    PRD 3.5: "A new document is persisted with `status` `DRAFT`, `revision_round` 0, a null `change_note`, `tie_out_status` `NOT_STARTED`, `tie_out_total_variance_bp` 0, `tie_out_tier_multiplier` 1.00, `measure_gate_status` `NO_MEASURES` and `qa_gate_status` `CLEARED`."

    Design: Corner/entities/document_gate_fields_are_computed_at_create_and_client_values_are_input_ignored
    """
    committee, cycle = _close_open_cycle(api, "Gate Field Charter")

    payload = dict(
        document_payload(
            cycle["id"], "PERIODIC_FILING", committee.mid("fin"),
            cycle_version(api, cycle["id"]),
            title="Form 10-Q FY2026-Q2",
            safe_harbor_present=False,
        )
    )
    payload.update(
        {
            "tie_out_status": "PASSED",
            "tie_out_total_variance_bp": 0,
            "measure_gate_status": "CLEARED",
            "qa_gate_status": "CLEARED",
        }
    )
    document = validate_success(
        api.create_document(payload, committee.controller("fin")), 201
    )
    assert document["status"] == "DRAFT"
    assert document["revision_round"] == 0
    assert document["change_note"] is None
    assert document["tie_out_status"] == "NOT_STARTED"
    assert document["tie_out_total_variance_bp"] == 0
    assert_money(document["tie_out_tier_multiplier"], 1.00)
    assert document["measure_gate_status"] == "NO_MEASURES"
    assert document["qa_gate_status"] == "CLEARED"

    item = add_tie_out(
        api, committee, document["id"], "Total revenue", 4120000, 4120000,
        tolerance_bp=25,
    )
    assert item["raw_variance_bp"] == 0
    assert item["effective_tolerance_bp"] == 25
    assert item["status"] == "MATCHED"

    after = validate_success(api.get_document(document["id"], admin_headers()))
    assert after["tie_out_status"] == "PASSED"
    assert after["tie_out_total_variance_bp"] == 0
    assert after["measure_gate_status"] == "NO_MEASURES"


SUPPLIED_CHARTER_ID = "11111111-1111-4111-8111-111111111111"
SUPPLIED_CREATED_AT = "2020-01-01T00:00:00Z"


def test_supplied_identity_and_status_fields_are_ignored_by_both_creates(api):
    """A charter create that supplies its own identifier, version, creation stamp,
    adopted status and adoption stamp still lands as a version-one draft under a
    server-minted identifier, and a member create that supplies a recused status
    still lands active — the system-sourced fields are write-protected on the
    create path.

    PRD 2.4: "`id` is a server-minted UUID string with no type prefix; clients never supply it."

    PRD 3.1: "A freshly created charter has `status` `DRAFT`, a null `superseded_by_charter_id`, a null `adopted_at_utc`, an `active_voting_member_count` of 0 and an empty `covered_functions` list."

    Design: Corner/entities/server_minted_identity_and_status_fields_are_input_ignored_on_create
    """
    rows, meta = validate_paginated(api.list_charters(admin_headers(), limit=10, offset=0))
    assert rows == []
    assert meta["total_count"] == 0

    charter_body = dict(charter_payload(CHARTER_NAME, "2026.1", 1, ["FINANCE"]))
    charter_body.update(
        {
            "id": SUPPLIED_CHARTER_ID,
            "version": 9,
            "created_at": SUPPLIED_CREATED_AT,
            "status": "ADOPTED",
            "adopted_at_utc": SUPPLIED_CREATED_AT,
        }
    )
    charter = validate_success(api.create_charter(charter_body, admin_headers()), 201)
    assert_fresh_record(charter)
    assert charter["id"] != SUPPLIED_CHARTER_ID
    assert charter["version"] == 1
    assert charter["status"] == "DRAFT"
    assert charter["adopted_at_utc"] is None
    assert charter["superseded_by_charter_id"] is None
    assert charter["created_at"] != SUPPLIED_CREATED_AT

    member_body = dict(member_payload("Nora Finance", "FINANCE", False, True))
    member_body["status"] = "RECUSED"
    member = validate_success(
        api.create_member(charter["id"], member_body, admin_headers()), 201
    )
    assert member["status"] == "ACTIVE"
    assert member["version"] == 1

    reread = validate_success(api.get_charter(charter["id"], admin_headers()))
    assert reread["active_voting_member_count"] == 1
    assert reread["status"] == "DRAFT"


def test_out_of_range_numerics_and_out_of_domain_enums_split_across_two_codes(api):
    """A quorum count above twelve, a function outside the declared set and an
    unknown form type are all generic request-shape failures, while a milestone
    window whose start is not strictly before its end is refused by the calendar's
    own containment rule with its domain-specific code; nothing is persisted and
    the cycle's slack figures stay at the empty-set sentinel.

    PRD 3.1: "The payload carries a `name` — non-empty, at most 160 characters — a human-readable `version_label` such as "v3.1", non-empty and at most 40 characters, a `min_quorum_count` that must be an integer of at least 1 and at most 12, and a `required_functions` list that must be non-empty and must contain distinct values drawn from `FINANCE`, `LEGAL`, `OPERATIONS` and `INVESTOR_RELATIONS`."

    PRD 3.3: "Either failing yields `ERR_MILESTONE_PAST_DEADLINE`, which — unlike the first two rules — is reported as HTTP 422 rather than 409."

    Design: Corner/entities/out_of_domain_enums_and_out_of_range_numerics_are_rejected_on_create
    """
    committee = _finance_committee(api)
    cycle = build_cycle(api, committee)
    assert cycle["status"] == "PLANNING"
    assert_instant_equals(cycle["statutory_deadline_utc"], "2026-08-10T17:30:00Z")

    validate_error(
        api.create_charter(
            charter_payload("Oversized quorum", "2026.2", 13, ["FINANCE"]),
            admin_headers(),
        ),
        "ERR_INVALID_REQUEST",
        422,
    )
    validate_error(
        api.create_charter(
            charter_payload("Unknown function", "2026.3", 1, ["MARKETING"]),
            admin_headers(),
        ),
        "ERR_INVALID_REQUEST",
        422,
    )
    validate_error(
        api.create_cycle(
            cycle_payload(
                committee.id,
                fiscal_period_label="FY2026-Q3",
                form_type="FORM_20F",
                period_end_date="2026-09-30",
            ),
            admin_headers(),
        ),
        "ERR_INVALID_REQUEST",
        422,
    )
    validate_error(
        api.create_milestone(
            cycle["id"],
            milestone_payload("CLOSE", "2026-08-03T00:00:00Z", "2026-08-03T00:00:00Z"),
            committee.controller("fin"),
        ),
        "ERR_MILESTONE_PAST_DEADLINE",
        422,
    )

    rows, meta = validate_paginated(
        api.list_cycle_milestones(cycle["id"], admin_headers(), limit=10, offset=0)
    )
    assert rows == []
    assert meta["total_count"] == 0

    after = refresh_cycle(api, cycle["id"])
    assert after["min_slack_days_calendar"] == 9999
    assert after["min_slack_days_business"] == 9999


STRANGER_SEAT = [("fin", "Quin Stranger", "FINANCE", False, True)]
UNKNOWN_BODY_CYCLE = "00000000-0000-4000-8000-0000000000aa"
UNKNOWN_BODY_MEMBER = "00000000-0000-4000-8000-0000000000bb"


def test_the_two_body_foreign_keys_resolve_in_declaration_order_then_by_ownership(api):
    """The assignment names its cycle before its member, so a request whose both
    keys are unknown reports the cycle rather than the member; with a real cycle
    the unknown member is reported next; and a member who exists but sits on a
    different charter than the cycle is an ownership failure rather than a
    missing row, so it comes back as a conflict rather than a not-found.

    PRD 2.7: "References supplied inside a request body are resolved after every path segment has resolved, and among themselves they are checked in the order in which the endpoint declares its input fields."

    PRD 2.11: "Every committee member named in the request — through `member_id`, `officer_member_id`, `author_member_id`, `preparer_member_id` or `reviewer_member_id` — belongs to the same charter as the reporting cycle the write targets. Applies to sub-certification creation, officer-certification registration, document creation, tie-out item creation and tie-out review — `ERR_MEMBER_CHARTER_MISMATCH`."

    Design: Corner/entities/body_foreign_keys_must_exist_and_belong_to_the_cycles_own_charter_or_are_rejected
    """
    committee, cycle = _close_open_cycle(api, "Charter A")
    other = build_committee(
        api,
        seats=STRANGER_SEAT,
        min_quorum_count=1,
        required_functions=["FINANCE"],
        name="Charter B",
        version_label="B-1",
        adopt=False,
    )
    chair = committee.chair("fin")

    validate_error(
        api.create_subcert(
            subcert_payload(
                UNKNOWN_BODY_CYCLE, UNKNOWN_BODY_MEMBER, "REVENUE",
                "2026-08-04T17:00:00Z",
            ),
            chair,
        ),
        "ERR_CYCLE_NOT_FOUND",
        404,
    )
    validate_error(
        api.create_subcert(
            subcert_payload(
                cycle["id"], UNKNOWN_BODY_MEMBER, "REVENUE", "2026-08-04T17:00:00Z"
            ),
            chair,
        ),
        "ERR_MEMBER_NOT_FOUND",
        404,
    )
    validate_error(
        api.create_subcert(
            subcert_payload(
                cycle["id"], other.mid("fin"), "REVENUE", "2026-08-04T17:00:00Z"
            ),
            chair,
        ),
        "ERR_MEMBER_CHARTER_MISMATCH",
        409,
    )

    rows, meta = validate_paginated(
        api.list_subcerts(admin_headers(), cycle_id=cycle["id"], limit=10, offset=0)
    )
    assert rows == []
    assert meta["total_count"] == 0

    after = refresh_cycle(api, cycle["id"])
    assert_money(after["total_assigned_scope_weight"], 0.00)
    assert_money(after["certification_coverage_pct"], 0.00)


def test_the_successor_edge_refuses_a_self_loop_and_an_unadopted_target(api):
    """Supersession refuses to close a one-node loop and refuses a still-draft
    target, both with the same successor code; only a distinct adopted charter
    writes the edge, after which the outgoing charter carries the successor's
    identifier while the successor itself stays adopted with a null pointer, so
    the edge can be walked from either end.

    PRD 3.1: "The successor must exist, must itself be in `ADOPTED` status, and must not be the charter being superseded; any of those failing is `ERR_SUCCESSOR_CHARTER_INVALID`."

    Design: Corner/entities/charter_self_succession_and_unadopted_successor_are_rejected_before_the_graph_edge_links
    """
    predecessor = _finance_committee(api, name="Charter A", version_label="A-1")
    successor = build_committee(
        api,
        seats=[("fin", "Owen Successor", "FINANCE", False, True)],
        min_quorum_count=1,
        required_functions=["FINANCE"],
        name="Charter B",
        version_label="B-1",
        chair_key="fin",
    )
    draft = validate_success(
        api.create_charter(
            charter_payload("Charter C", "C-1", 1, ["FINANCE"]), admin_headers()
        ),
        201,
    )
    assert draft["status"] == "DRAFT"
    chair = predecessor.chair("fin")

    validate_error(
        api.transition_charter(
            predecessor.id,
            action_payload("SUPERSEDE", successor_charter_id=predecessor.id),
            chair,
        ),
        "ERR_SUCCESSOR_CHARTER_INVALID",
        409,
    )
    validate_error(
        api.transition_charter(
            predecessor.id,
            action_payload("SUPERSEDE", successor_charter_id=draft["id"]),
            chair,
        ),
        "ERR_SUCCESSOR_CHARTER_INVALID",
        409,
    )

    superseded = validate_success(
        api.transition_charter(
            predecessor.id,
            action_payload("SUPERSEDE", successor_charter_id=successor.id),
            chair,
        )
    )
    assert superseded["status"] == "SUPERSEDED"
    assert superseded["superseded_by_charter_id"] == successor.id

    from_the_successor_end = validate_success(
        api.get_charter(successor.id, admin_headers())
    )
    assert from_the_successor_end["status"] == "ADOPTED"
    assert from_the_successor_end["superseded_by_charter_id"] is None

    reread = validate_success(api.get_charter(predecessor.id, admin_headers()))
    assert reread["status"] == "SUPERSEDED"
    assert reread["superseded_by_charter_id"] == successor.id
