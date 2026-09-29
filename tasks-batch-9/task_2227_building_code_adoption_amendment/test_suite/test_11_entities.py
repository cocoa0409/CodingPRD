"""Entity creation, read-back, listing and the shapes the PRD declares."""
from test_helpers import (
    ADMIN_OPINION_PUBLISHER_ID,
    NON_EXISTENT_UUID,
    PETITIONER_NINE_ID,
    STAFF_DRAFTER_ID,
    STAFF_INTAKE_ID,
    ApiErrorId,
    factories,
    fixtures,
    get_success_data,
    make_committee_member_headers,
    make_council_admin_headers,
    make_petitioner_headers,
    make_technical_staff_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

MECHANICAL_PROPOSAL = {
    "code_section": "M403.3.1",
    "discipline": "MECHANICAL",
    "title": "Ventilation rate table cleanup",
    "proposed_text": (
        "Restate the outdoor air rate table without changing required rates."
    ),
    "stringency_direction": "NEUTRAL",
    "proposer_sector": "DESIGN_PROFESSIONAL",
}

COMPUTED_FIELD_PROPOSAL = {
    "code_section": "C405.2.1",
    "discipline": "ENERGY",
    "title": "Lighting power density reduction",
    "proposed_text": "Lower interior lighting power allowances.",
    "stringency_direction": "MORE_STRINGENT",
    "proposer_sector": "INDUSTRY",
    "energy_analysis_required": False,
    "review_status": "APPROVED",
    "committee_id": NON_EXISTENT_UUID,
}

SYSTEM_FIELD_HEARING = {
    "status": "CONVENED",
    "convened_at": "2026-08-01T00:00:00Z",
    "version": 9,
}

BAD_ENUM_PROPOSAL = {
    "code_section": "C402.1.9",
    "discipline": "ENERGY",
    "title": "Bad enum probe",
    "proposed_text": "Probe body.",
    "stringency_direction": "SOMEWHAT_STRINGENT",
    "proposer_sector": "INDUSTRY",
}


def test_01_a_new_code_cycle_opens_in_draft_with_a_zeroed_ledger(api):
    """"A new cycle begins in `DRAFT` with every ledger field initialised to
    zero: `proposal_count`, `approved_proposal_count`,
    `approved_incremental_cost_cents` and `approved_permit_backlog_count` all
    start at 0, as does `seated_committee_count`." The two declared intake dates
    come back exactly as supplied, because "the declared intake dates are
    documentation only".

    Design: Corner/entities/create_code_cycle_returns_declared_defaults_and_zero_counters
    """
    fixtures.set_logical_clock(api, fixtures.CLOCK_INTAKE)

    response = api.create_code_cycle(
        factories.create_code_cycle_payload(), make_council_admin_headers()
    )
    cycle = validate_success(response, 201)

    assert cycle["cycle_year"] == 2027
    assert cycle["model_code_edition"] == "IBC-2027"
    assert cycle["intake_opens_at"] == "2026-08-01T00:00:00Z"
    assert cycle["intake_closes_at"] == "2026-10-01T00:00:00Z"
    assert cycle["status"] == "DRAFT"
    assert cycle["proposal_count"] == 0
    assert cycle["approved_proposal_count"] == 0
    assert cycle["approved_incremental_cost_cents"] == 0
    assert cycle["approved_permit_backlog_count"] == 0
    assert cycle["seated_committee_count"] == 0
    assert cycle["version"] == 1


def test_02_a_submitted_proposal_reads_back_exactly_as_stored(api):
    """"The server records the submitter's identifier in `submitted_by_user_id`
    and increments the cycle's `proposal_count` by one", and routing resolves the
    `committee_id` to the live committee "whose own `discipline` equals the
    proposal's `discipline`". The row is readable by a seated `CommitteeMember`
    and still stands at "`SUBMITTED` on the first dimension and `NOT_STARTED` on
    the second".

    Design: Corner/entities/get_amendment_proposal_returns_the_stored_row
    """
    world = fixtures.setup_seated_energy_committee(api)
    fixtures.set_cycle_status(api, world["cycle_id"], "INTAKE_OPEN")
    fixtures.submit_proposal(api, world)

    proposal = validate_success(
        api.get_amendment_proposal(
            world["proposal_id"],
            make_committee_member_headers(world["members"]["public"]["id"]),
        )
    )
    assert proposal["code_cycle_id"] == world["cycle_id"]
    assert proposal["committee_id"] == world["committee_id"]
    assert proposal["code_section"] == "C402.1.4"
    assert proposal["stringency_direction"] == "MORE_STRINGENT"
    assert proposal["submitted_by_user_id"] == STAFF_INTAKE_ID
    assert proposal["review_status"] == "SUBMITTED"
    assert proposal["analysis_status"] == "NOT_STARTED"

    cycle = get_success_data(
        api.get_code_cycle(world["cycle_id"], make_council_admin_headers())
    )
    assert cycle["proposal_count"] == 1


def test_03_the_proposal_list_pages_and_filters_by_discipline(api):
    """"`limit` is the maximum number of rows returned", "`total_count` counts
    every row matching the filters before pagination is applied", and "amendment
    proposals filter on `review_status`, `analysis_status`, `discipline`,
    `code_cycle_id` and `committee_id`". A page of one over two proposals reports
    both in `total_count` with `has_more` true, while the discipline filter
    narrows the same collection to the single mechanical row.

    Design: Corner/entities/list_amendment_proposals_filters_by_discipline_and_paginates
    """
    world = fixtures.setup_seated_energy_committee(api)
    fixtures.add_mechanical_committee(api, world)
    fixtures.set_cycle_status(api, world["cycle_id"], "INTAKE_OPEN")
    fixtures.submit_proposal(api, world)
    mechanical = fixtures.submit_proposal(api, world, **MECHANICAL_PROPOSAL)

    page, meta = validate_paginated(
        api.list_amendment_proposals(
            make_petitioner_headers(), params={"limit": 1, "offset": 0}
        )
    )
    assert len(page) == 1
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert meta["limit"] == 1
    assert meta["offset"] == 0

    filtered, filtered_meta = validate_paginated(
        api.list_amendment_proposals(
            make_petitioner_headers(), params={"discipline": "MECHANICAL"}
        )
    )
    assert filtered_meta["total_count"] == 1
    assert filtered_meta["has_more"] is False
    assert filtered[0]["id"] == mechanical["id"]
    assert filtered[0]["discipline"] == "MECHANICAL"


def test_04_an_unknown_adoption_rule_id_is_reported_as_not_found(api):
    """On the path-existence rung "every identifier in the URL path resolves to a
    live row, else the 404 error for that record family". A rulemaking order
    identifier
    that no row carries therefore yields `ERR_ADOPTION_RULE_NOT_FOUND` (404).

    Design: Corner/entities/get_adoption_rule_with_unknown_id_not_found
    """
    response = api.get_adoption_rule(NON_EXISTENT_UUID, make_council_admin_headers())
    validate_error(response, ApiErrorId.ERR_ADOPTION_RULE_NOT_FOUND, 404)


def test_05_a_jurisdiction_without_a_population_is_rejected_on_shape(api):
    """A `CouncilAdmin` registers a jurisdiction "with a `name` ... a resident
    `population`, a `local_authority_level` ... a `host_seat_capacity` ... and an
    `official_headcount`". A body missing the required `population` fails the
    shape rung — "required fields present, types correct ... else
    `ERR_INVALID_REQUEST` (400)" — and writes nothing.

    Design: Corner/entities/create_jurisdiction_missing_required_population_is_rejected
    """
    response = api.create_jurisdiction(
        {
            "name": "Riverbend",
            "local_authority_level": "FULL",
            "host_seat_capacity": 60,
            "official_headcount": 5,
        },
        make_council_admin_headers(),
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST, 400)

    _, meta = validate_paginated(api.list_jurisdictions(make_council_admin_headers()))
    assert meta["total_count"] == 0


def test_06_a_member_added_without_flags_takes_the_declared_defaults(api):
    """Each member carries "an optional `voting_seat` flag that defaults to true,
    and an optional `is_chair` flag that defaults to false", its own "`status` is
    `ACTIVE` on creation", and `recusal_reason` "is null until one occurs". The
    first such member lifts `active_voting_member_count` to 1 while
    `chair_member_count` stays 0, so the committee is still `FORMING`.

    Design: Corner/entities/create_committee_member_applies_voting_seat_and_chair_defaults
    """
    world = fixtures.setup_cycle(api)
    committee = fixtures.create_committee(
        api, world["cycle_id"], discipline="ENERGY", voting_seat_count=6
    )

    response = api.create_committee_member(
        committee["id"],
        factories.create_committee_member_payload(
            full_name="Uma Verity", sector="PUBLIC"
        ),
        make_council_admin_headers(),
    )
    member = validate_success(response, 201)
    assert member["voting_seat"] is True
    assert member["is_chair"] is False
    assert member["status"] == "ACTIVE"
    assert member["recusal_reason"] is None
    assert member["committee_id"] == committee["id"]

    reread = get_success_data(
        api.get_discipline_committee(committee["id"], make_council_admin_headers())
    )
    assert reread["active_voting_member_count"] == 1
    assert reread["chair_member_count"] == 0
    assert reread["status"] == "FORMING"


def test_07_client_supplied_computed_proposal_fields_are_discarded(api):
    """"A `committee_id` supplied by the client is ignored entirely", and "a new
    proposal starts at `SUBMITTED` on the first dimension and `NOT_STARTED` on
    the second" whatever the body claims. The submitter's own identifier is
    recorded regardless.

    Design: Corner/entities/create_proposal_computed_status_fields_input_ignored
    """
    world = fixtures.setup_seated_energy_committee(api)
    fixtures.set_cycle_status(api, world["cycle_id"], "INTAKE_OPEN")

    response = api.create_amendment_proposal(
        factories.create_amendment_proposal_payload(
            world["cycle_id"], **COMPUTED_FIELD_PROPOSAL
        ),
        make_petitioner_headers(PETITIONER_NINE_ID),
    )
    proposal = validate_success(response, 201)
    assert proposal["review_status"] == "SUBMITTED"
    assert proposal["analysis_status"] == "NOT_STARTED"
    assert proposal["committee_id"] == world["committee_id"]
    assert proposal["submitted_by_user_id"] == PETITIONER_NINE_ID


def test_08_client_supplied_system_hearing_fields_are_discarded(api):
    """"A new hearing starts in `SCHEDULED` with an empty `agenda_proposal_ids`,
    and its `present_member_ids`, `present_voting_count`,
    `quorum_required_at_convene`, `convened_at` and `adjourned_at` all null." A
    body naming a `CONVENED` status, a `convened_at` instant and a `version` of 9
    changes none of that: `version` is "an integer that starts at 1 on creation",
    and `updated_at` is "refreshed on every mutation", of which there has been
    none.

    Design: Corner/entities/create_hearing_system_fields_input_ignored
    """
    world = fixtures.setup_seated_energy_committee(api)

    response = fixtures.schedule_hearing(api, world, **SYSTEM_FIELD_HEARING)
    hearing = validate_success(response, 201)
    assert hearing["status"] == "SCHEDULED"
    assert hearing["version"] == 1
    assert hearing["convened_at"] is None
    assert hearing["adjourned_at"] is None
    assert hearing["quorum_required_at_convene"] is None
    assert hearing["agenda_proposal_ids"] == []
    assert hearing["created_at"] == hearing["updated_at"]


def test_09_an_unknown_stringency_direction_is_rejected_on_shape(api):
    """A proposal carries "a `stringency_direction` of `MORE_STRINGENT`,
    `LESS_STRINGENT`, `NEUTRAL` or `CLARIFYING`", so a value outside that set
    fails the shape rung — "enum members recognized ... else
    `ERR_INVALID_REQUEST` (400)" — and leaves the cycle's `proposal_count` at 0.

    Design: Corner/entities/create_proposal_with_unknown_stringency_direction_is_rejected
    """
    world = fixtures.setup_seated_energy_committee(api)
    fixtures.set_cycle_status(api, world["cycle_id"], "INTAKE_OPEN")

    response = api.create_amendment_proposal(
        factories.create_amendment_proposal_payload(
            world["cycle_id"], **BAD_ENUM_PROPOSAL
        ),
        make_petitioner_headers(PETITIONER_NINE_ID),
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST, 400)

    cycle = get_success_data(
        api.get_code_cycle(world["cycle_id"], make_council_admin_headers())
    )
    assert cycle["proposal_count"] == 0


def test_10_a_committee_under_an_unknown_cycle_is_reported_as_not_found(api):
    """"Outer path segments resolve before inner ones: a cycle before its
    committee, a committee before its member." A committee created beneath a
    cycle identifier that no row carries therefore yields
    `ERR_CODE_CYCLE_NOT_FOUND` (404) and creates nothing.

    Design: Corner/entities/create_committee_under_unknown_code_cycle_not_found
    """
    response = api.create_discipline_committee(
        NON_EXISTENT_UUID,
        factories.create_discipline_committee_payload(
            discipline="ENERGY", voting_seat_count=6
        ),
        make_council_admin_headers(),
    )
    validate_error(response, ApiErrorId.ERR_CODE_CYCLE_NOT_FOUND, 404)

    _, meta = validate_paginated(api.list_code_cycles(make_council_admin_headers()))
    assert meta["total_count"] == 0


def test_11_a_limit_of_one_hundred_and_one_is_rejected(api):
    """A `limit`'s "accepted range is a minimum of 1 and a maximum of 100", and
    "a `limit` outside 1 through 100, or a negative `offset`, is rejected with
    `ERR_PAGINATION_INVALID` (400)".

    Design: Corner/entities/list_jurisdictions_limit_above_maximum_returns_4xx
    """
    response = api.list_jurisdictions(
        make_council_admin_headers(), params={"limit": 101}
    )
    validate_error(response, ApiErrorId.ERR_PAGINATION_INVALID, 400)


def test_12_a_public_comment_exposes_no_updated_at_and_no_version(api):
    """Two record families are append-only: "a `PublicComment` and a
    `VoteRecord` expose only `id` and `created_at`. Both `updated_at` and
    `version` are absent from those two record types entirely." The server still
    "stamps `submitted_by_user_id`, sets `received_at` from the logical clock, and
    snapshots the proposal's current `comment_round` onto the comment".

    Design: Corner/entities/public_comment_is_immutable_and_carries_no_version_field
    """
    world = fixtures.setup_proposal_comment_open(api)
    created = get_success_data(
        fixtures.submit_comment(
            api, world, "INDUSTRY", "SUPPORT", "Aligns with our product roadmap."
        )
    )

    comment = validate_success(
        api.get_public_comment(created["id"], make_council_admin_headers())
    )
    assert "id" in comment
    assert "created_at" in comment
    assert "updated_at" not in comment
    assert "version" not in comment

    assert comment["proposal_id"] == world["proposal_id"]
    assert comment["position"] == "SUPPORT"
    assert comment["commenter_sector"] == "INDUSTRY"
    assert comment["submitted_by_user_id"] == "petitioner-1"
    assert comment["comment_round"] == 1
    assert comment["received_at"] == "2026-08-15T00:00:00Z"


def test_13_the_supersession_edge_reads_from_both_ends(api):
    """Publication "moves that prior request `PUBLISHED` → `SUPERSEDED`", and
    `opinion_number` "is one greater than the highest `opinion_number` ever
    assigned under the same `adoption_rule_id`, starting at 1 for the first
    opinion issued under that order". The successor names its predecessor through
    `supersedes_request_id`, and the predecessor's superseding-requests
    collection returns exactly that successor.

    Design: Corner/entities/interpretation_supersession_edge_is_navigable_from_both_ends
    """
    world = fixtures.setup_published_interpretation(api)
    first_id = world["interpretation_request_id"]

    successor = get_success_data(
        fixtures.file_interpretation_request(
            api,
            world,
            question="Restating the addition threshold after further review.",
            supersedes_request_id=first_id,
        )
    )
    fixtures.act_on_interpretation(
        api,
        world,
        "ASSIGN",
        request_id=successor["id"],
        assigned_committee_id=world["committee_id"],
    )
    fixtures.act_on_interpretation(
        api,
        world,
        "ISSUE_OPINION",
        request_id=successor["id"],
        opinion_text=(
            "The threshold is 500 square feet of conditioned floor area only."
        ),
        binding_scope="STATEWIDE",
        headers=make_technical_staff_headers(STAFF_DRAFTER_ID),
    )

    published = validate_success(
        fixtures.act_on_interpretation(
            api,
            world,
            "PUBLISH",
            request_id=successor["id"],
            headers=make_council_admin_headers(ADMIN_OPINION_PUBLISHER_ID),
        )
    )
    assert published["status"] == "PUBLISHED"
    assert published["supersedes_request_id"] == first_id
    assert published["opinion_number"] == 2

    predecessor = get_success_data(
        api.get_interpretation_request(first_id, make_council_admin_headers())
    )
    assert predecessor["status"] == "SUPERSEDED"
    assert predecessor["opinion_number"] == 1

    superseding, superseding_meta = validate_paginated(
        api.list_superseding_requests(first_id, make_council_admin_headers())
    )
    assert superseding_meta["total_count"] == 1
    assert superseding[0]["id"] == successor["id"]

    _, rule_meta = validate_paginated(
        api.list_rule_interpretation_requests(
            world["rule_id"], make_council_admin_headers()
        )
    )
    assert rule_meta["total_count"] == 2
