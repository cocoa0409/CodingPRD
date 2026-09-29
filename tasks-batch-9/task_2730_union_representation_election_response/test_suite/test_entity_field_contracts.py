"""Case-record field contracts.

What a docketed representation case, its classification roster, its campaign
drafts and its eligible-voter list carry when they are created, read back,
listed, and when the request that would have written them is refused.
"""
import pytest

from test_helpers import (
    ANALYST,
    BOARD,
    COUNSEL,
    DIRECTOR,
    ApiErrorId,
    add_business_days,
    add_classification,
    add_voter_entry,
    api_client,
    assert_common_fields,
    assert_instant_equals,
    assert_petition,
    assert_success_envelope,
    assert_version_is,
    create_campaign_message,
    create_election_agreement,
    create_petition,
    create_voter_list,
    make_director_headers,
    open_scope_analysis,
    read_petition,
    read_round,
    read_voter_list,
    set_clock,
    setup_draft_voter_list,
    setup_election_set,
    setup_scope_analysis,
    setup_soi_verified,
    stipulate_agreement,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK = "2026-08-03T09:00:00Z"

DOCKETING_PAYLOAD = {
    "case_number": "07-RC-340001",
    "petition_type": "RC",
    "union_name": "United Plant Workers Local 812",
    "filed_date": "2026-08-03",
    "proposed_unit_description": "All production and maintenance employees at Plant 1",
    "claimed_employee_count": 120,
    "payroll_period_end": "2026-08-14",
}

PROD_SPEC = {
    "code": "PROD", "title": "Production Operator", "headcount": 60,
    "avg_hourly_wage_cents": 2400, "shift_code": "A", "work_location": "PLANT_1",
    "supervisory_authority_count": 0, "employer_position": "INCLUDE",
    "union_position": "INCLUDE", "supervision_overlap": 88, "skills_overlap": 90,
    "functional_integration": 92, "interchange_rate": 74, "work_conditions_overlap": 95,
}

MAINT_SPEC = {
    "code": "MAINT", "title": "Maintenance Mechanic", "headcount": 30,
    "avg_hourly_wage_cents": 3200, "shift_code": "A", "work_location": "PLANT_1",
    "supervisory_authority_count": 0, "employer_position": "INCLUDE",
    "union_position": "INCLUDE", "supervision_overlap": 82, "skills_overlap": 78,
    "functional_integration": 86, "interchange_rate": 61, "work_conditions_overlap": 84,
}

QC_SPEC = {
    "code": "QC", "title": "Quality Inspector", "headcount": 12,
    "avg_hourly_wage_cents": 2900, "shift_code": "B", "work_location": "PLANT_1_LAB",
    "supervisory_authority_count": 0, "employer_position": "EXCLUDE",
    "union_position": "INCLUDE", "supervision_overlap": 41, "skills_overlap": 55,
    "functional_integration": 61, "interchange_rate": 21, "work_conditions_overlap": 71,
}

WHSE_SPEC = {
    "code": "WHSE", "title": "Warehouse Selector", "headcount": 40,
    "avg_hourly_wage_cents": 2200, "shift_code": "C", "work_location": "PLANT_3",
    "supervisory_authority_count": 0, "employer_position": "INCLUDE",
    "union_position": "INCLUDE", "supervision_overlap": 70, "skills_overlap": 66,
    "functional_integration": 72, "interchange_rate": 55, "work_conditions_overlap": 80,
}


# ---------------------------------------------------------------------------
# Docketing a case and reading it back
# ---------------------------------------------------------------------------
def test_docketed_petition_echoes_the_docketing_payload_in_the_success_envelope():
    """Docketing answers 201 with the documented object envelope and every
    supplied input value echoed onto the created case.

    PRD: "The docketing payload carries the Board's docket number as `case_number`, the `petition_type` — `RC` for a union-filed certification petition, `RM` for an employer-filed one, `RD` for a decertification petition — the petitioning labor organization as `union_name`, the calendar date the petition was docketed as `filed_date`, the unit description exactly as the petition words it in `proposed_unit_description`, the headcount the petitioner claims is in the unit as `claimed_employee_count`, and the last day of the payroll period that fixes voter eligibility as `payroll_period_end`."
    PRD: "Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field."
    PRD: "The `response_type` is either "object" for a single resource or "array" for a list of resources."

    Design: Corner/entities/petition_create_returns_declared_fields_and_computed_defaults
    """
    set_clock(CLOCK)

    response = api_client.create_petition(dict(DOCKETING_PAYLOAD), DIRECTOR)

    assert_success_envelope(response, "object")
    data = validate_success(response, 201)
    assert data["case_number"] == "07-RC-340001"
    assert data["petition_type"] == "RC"
    assert data["union_name"] == "United Plant Workers Local 812"
    assert data["filed_date"] == "2026-08-03"
    assert data["claimed_employee_count"] == 120
    assert data["payroll_period_end"] == "2026-08-14"
    assert_common_fields(data, "petition")
    assert_version_is(data, 1, "petition")


def test_docketed_petition_starts_with_zeroed_counters_and_its_declared_default_states():
    """A brand-new case is RECEIVED and OPEN, every derived counter is zero, and
    the verdict, outcome and retraining flag hold their declared defaults.

    PRD: "A freshly docketed case begins at `case_status` `RECEIVED` with `case_posture` `OPEN`."
    PRD: "Every derived counter on it starts at zero — `total_classified_headcount`, `included_headcount`, `excluded_headcount` and `pending_headcount`, and the five card counters `submitted_card_count`, `duplicate_card_count`, `undated_card_count`, `stale_card_count` and `nonunit_card_count` — while `showing_verdict` begins at `PENDING`, `certification_outcome` at `NONE`, `retraining_required` at `false`, and `pending_objection_count` and `blocking_charge_count` at 0."

    Design: Corner/entities/petition_create_returns_declared_fields_and_computed_defaults
    """
    set_clock(CLOCK)

    petition = create_petition(**DOCKETING_PAYLOAD)

    assert petition["case_status"] == "RECEIVED"
    assert petition["case_posture"] == "OPEN"
    assert petition["total_classified_headcount"] == 0
    assert petition["included_headcount"] == 0
    assert petition["excluded_headcount"] == 0
    assert petition["pending_headcount"] == 0
    assert petition["showing_verdict"] == "PENDING"
    assert petition["certification_outcome"] == "NONE"
    assert petition["retraining_required"] is False
    assert petition["pending_objection_count"] == 0
    assert petition["blocking_charge_count"] == 0
    assert_petition(petition)


def test_reading_a_docketed_petition_returns_the_stored_row_without_bumping_its_version():
    """A read hands back the persisted row — the same identifier, the same input
    values and the version the docketing call minted, since a read mutates nothing.

    PRD: "`version` is an integer that begins at 1 when the row is created and increases by exactly 1 on every mutation of that row."
    PRD: "The `data` field contains the resource object or an array of resource objects."

    Design: Corner/entities/petition_get_by_id_returns_the_stored_row
    """
    set_clock(CLOCK)
    created = create_petition(
        case_number="07-RC-340002",
        petition_type="RM",
        union_name="United Plant Workers Local 812",
        filed_date="2026-08-03",
        proposed_unit_description="All production employees at Plant 2",
        claimed_employee_count=65,
        payroll_period_end="2026-08-14",
    )

    response = api_client.get_petition(created["id"], COUNSEL)

    assert_success_envelope(response, "object")
    data = validate_success(response)
    assert data["id"] == created["id"]
    assert data["petition_type"] == "RM"
    assert data["claimed_employee_count"] == 65
    assert_version_is(data, 1, "petition")
    assert_petition(data)


# ---------------------------------------------------------------------------
# Listing the classification roster
# ---------------------------------------------------------------------------
def _two_cases_with_rosters():
    """Case A carrying three classifications, case B carrying one."""
    set_clock(CLOCK)
    case_a = create_petition(case_number="07-RC-340003")
    open_scope_analysis(case_a["id"])
    for spec in (PROD_SPEC, MAINT_SPEC, QC_SPEC):
        add_classification(case_a["id"], **spec)
    case_b = create_petition(case_number="07-RC-340004")
    open_scope_analysis(case_b["id"])
    add_classification(case_b["id"], **WHSE_SPEC)
    return case_a, case_b


def test_classification_listing_paginates_within_the_case_it_is_filtered_to():
    """With the roster of one case selected, the row count reported is the count
    of matching rows before the page is cut, and the more-rows flag follows the
    page window rather than the page contents.

    PRD: "When a list endpoint responds, the `meta` object carries the four pagination fields — `limit` and `offset` echoing the values in force for the request, `total_count` giving the number of rows matching the filters before pagination is applied, and `has_more` indicating whether any further rows exist beyond the current page."

    Design: Corner/entities/classification_list_filters_by_petition_and_paginates
    """
    case_a, _case_b = _two_cases_with_rosters()

    first_page = api_client.list_classifications(
        BOARD, {"petition_id": case_a["id"], "limit": 2, "offset": 0}
    )
    assert_success_envelope(first_page, "array")
    rows, meta = validate_paginated(first_page)
    assert len(rows) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True
    assert meta["limit"] == 2
    assert meta["offset"] == 0

    last_page = api_client.list_classifications(
        BOARD, {"petition_id": case_a["id"], "limit": 2, "offset": 2}
    )
    rows, meta = validate_paginated(last_page)
    assert len(rows) == 1
    assert meta["total_count"] == 3
    assert meta["has_more"] is False
    assert meta["offset"] == 2


def test_classification_listing_narrowed_by_case_never_leaks_another_cases_roster():
    """Narrowing the roster by case and by ruling returns only that case's rows;
    the other case's classification is absent from the page and from the count.

    PRD: "Classification listings may be narrowed by `petition_id` or by `scope_ruling`, and case listings by `case_status`, by `case_posture`, or by `certified_round_id` for the narrow question of which case rests on a particular round."

    Design: Corner/entities/classification_list_filters_by_petition_and_paginates
    """
    case_a, _case_b = _two_cases_with_rosters()

    response = api_client.list_classifications(
        BOARD, {"petition_id": case_a["id"], "scope_ruling": "PENDING", "limit": 10, "offset": 0}
    )

    rows, meta = validate_paginated(response)
    assert meta["total_count"] == 3
    assert len(rows) == 3
    assert all(row["petition_id"] == case_a["id"] for row in rows)
    assert {row["code"] for row in rows} == {"PROD", "MAINT", "QC"}
    assert "WHSE" not in {row["code"] for row in rows}


# ---------------------------------------------------------------------------
# Unknown identifiers
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "reader, unknown_id, expected_error",
    [
        ("get_petition", "00000000-0000-4000-8000-000000000001",
         ApiErrorId.ERR_PETITION_NOT_FOUND),
        ("get_classification", "00000000-0000-4000-8000-000000000002",
         ApiErrorId.ERR_CLASSIFICATION_NOT_FOUND),
        ("get_election_agreement", "00000000-0000-4000-8000-000000000003",
         ApiErrorId.ERR_ELECTION_AGREEMENT_NOT_FOUND),
        ("get_voter_list", "00000000-0000-4000-8000-000000000004",
         ApiErrorId.ERR_VOTER_LIST_NOT_FOUND),
        ("get_voter_list_entry", "00000000-0000-4000-8000-000000000005",
         ApiErrorId.ERR_VOTER_LIST_ENTRY_NOT_FOUND),
        ("get_supervisor", "00000000-0000-4000-8000-000000000006",
         ApiErrorId.ERR_SUPERVISOR_NOT_FOUND),
        ("get_campaign_communication", "00000000-0000-4000-8000-000000000007",
         ApiErrorId.ERR_CAMPAIGN_COMMUNICATION_NOT_FOUND),
        ("get_election_round", "00000000-0000-4000-8000-000000000008",
         ApiErrorId.ERR_ELECTION_ROUND_NOT_FOUND),
        ("get_poll_session", "00000000-0000-4000-8000-000000000009",
         ApiErrorId.ERR_POLL_SESSION_NOT_FOUND),
        ("get_challenged_ballot", "00000000-0000-4000-8000-00000000000a",
         ApiErrorId.ERR_CHALLENGED_BALLOT_NOT_FOUND),
        ("get_objection", "00000000-0000-4000-8000-00000000000b",
         ApiErrorId.ERR_OBJECTION_NOT_FOUND),
        ("get_ulp_charge", "00000000-0000-4000-8000-00000000000c",
         ApiErrorId.ERR_ULP_CHARGE_NOT_FOUND),
    ],
)
def test_unknown_identifier_reports_the_addressed_resources_own_not_found_code(
    reader, unknown_id, expected_error
):
    """Addressing a row that does not exist fails with the not-found code that
    belongs to the resource type addressed, never a shared generic code.

    PRD: "The identifier in the path is resolved first: if no such row exists, the request fails with that resource type's own not-found code — `ERR_PETITION_NOT_FOUND`, `ERR_CLASSIFICATION_NOT_FOUND`, `ERR_ELECTION_AGREEMENT_NOT_FOUND`, `ERR_VOTER_LIST_NOT_FOUND`, `ERR_VOTER_LIST_ENTRY_NOT_FOUND`, `ERR_SUPERVISOR_NOT_FOUND`, `ERR_CAMPAIGN_COMMUNICATION_NOT_FOUND`, `ERR_ELECTION_ROUND_NOT_FOUND`, `ERR_POLL_SESSION_NOT_FOUND`, `ERR_CHALLENGED_BALLOT_NOT_FOUND`, `ERR_OBJECTION_NOT_FOUND` or `ERR_ULP_CHARGE_NOT_FOUND` — all with HTTP 404."

    Design: Corner/entities/unknown_ids_return_entity_specific_not_found
    """
    response = getattr(api_client, reader)(unknown_id, BOARD)

    validate_error(response, expected_error)
    assert response.json()["response_type"] == "error"


# ---------------------------------------------------------------------------
# Unknown identifiers named in a create body
# ---------------------------------------------------------------------------
UNKNOWN_ID = "00000000-0000-4000-8000-0000000000ff"

STATUTORY_ENTRY_CONTENT = {
    "full_name": "Dev Patel",
    "hire_date": "2024-01-15",
    "home_address": "88 Rolling Mill Road, Springfield",
    "personal_email": "dev.patel@example.com",
    "personal_phone": "+1-555-0177",
    "shift_code": "A",
    "work_location": "PLANT_1",
}


def test_classification_naming_an_unknown_case_reports_the_case_not_found():
    """A roster row whose case identifier resolves to nothing is refused with the
    case's own not-found code, and no classification is written.

    PRD: "Only then are the foreign keys in the body resolved, in the order the endpoint declares its input fields, each producing the referenced type's own not-found code."

    Design: Corner/entities/create_with_unknown_referenced_id_returns_referenced_entity_not_found
    """
    setup_scope_analysis(clock=CLOCK, petition_overrides={"case_number": "07-RC-340005"})

    response = api_client.create_classification(
        {"petition_id": UNKNOWN_ID, **MAINT_SPEC}, DIRECTOR
    )

    validate_error(response, ApiErrorId.ERR_PETITION_NOT_FOUND)
    assert response.json()["response_type"] == "error"
    rows, meta = validate_paginated(
        api_client.list_classifications(BOARD, {"limit": 50, "offset": 0})
    )
    assert meta["total_count"] == 1
    assert all(row["code"] != "MAINT" for row in rows)


def test_voter_entry_naming_an_unknown_list_reports_the_list_not_found():
    """An entry whose list identifier resolves to nothing is refused with the
    voter list's own not-found code even though its classification exists.

    PRD: "Only then are the foreign keys in the body resolved, in the order the endpoint declares its input fields, each producing the referenced type's own not-found code."

    Design: Corner/entities/create_with_unknown_referenced_id_returns_referenced_entity_not_found
    """
    ctx = setup_scope_analysis(clock=CLOCK, petition_overrides={"case_number": "07-RC-340005"})

    response = api_client.create_voter_list_entry(
        {
            "voter_list_id": UNKNOWN_ID,
            "classification_id": ctx["classifications"][0]["id"],
            **STATUTORY_ENTRY_CONTENT,
        },
        ANALYST,
    )

    validate_error(response, ApiErrorId.ERR_VOTER_LIST_NOT_FOUND)
    assert response.json()["response_type"] == "error"


def test_objection_naming_an_unknown_round_reports_the_round_not_found():
    """An objection whose round identifier resolves to nothing is refused with
    the round's own not-found code, and the case's pending objection count stays
    where it was.

    PRD: "Only then are the foreign keys in the body resolved, in the order the endpoint declares its input fields, each producing the referenced type's own not-found code."

    Design: Corner/entities/create_with_unknown_referenced_id_returns_referenced_entity_not_found
    """
    ctx = setup_scope_analysis(clock=CLOCK, petition_overrides={"case_number": "07-RC-340005"})

    response = api_client.create_objection(
        {
            "election_round_id": UNKNOWN_ID,
            "filed_by_party": "EMPLOYER",
            "ground_code": "POLLING_IRREGULARITY",
            "conduct_occurred_at": "2026-09-01T10:00:00Z",
            "alleged_affected_voter_count": 10,
            "description": "Ballots were handed out away from the designated polling table.",
        },
        DIRECTOR,
    )

    validate_error(response, ApiErrorId.ERR_ELECTION_ROUND_NOT_FOUND)
    assert read_petition(ctx["petition"]["id"])["pending_objection_count"] == 0


# ---------------------------------------------------------------------------
# Missing and out-of-range inputs
# ---------------------------------------------------------------------------
def test_docketing_without_the_payroll_period_end_is_refused():
    """The eligibility payroll date is part of the docketing payload, so a
    petition that omits it is refused as an invalid request and nothing is
    docketed.

    PRD: "**Request schema** — the body parses, every required field is present, every enumerated value is in range, integers are integers, community-of-interest factors lie between 0 and 100 inclusive, pagination is in range, and every datetime is ISO 8601 with a `Z` offset. Otherwise `ERR_INVALID_REQUEST` (422)."

    Design: Corner/entities/petition_create_missing_required_field_rejected
    """
    set_clock(CLOCK)
    payload = {
        key: value for key, value in DOCKETING_PAYLOAD.items() if key != "payroll_period_end"
    }
    payload["case_number"] = "07-RC-340006"

    response = api_client.create_petition(payload, DIRECTOR)

    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST)
    assert response.json()["response_type"] == "error"
    _rows, meta = validate_paginated(
        api_client.list_petitions(DIRECTOR, {"limit": 50, "offset": 0})
    )
    assert meta["total_count"] == 0


def _case_in_scope_analysis_without_a_roster(case_number: str) -> dict:
    set_clock(CLOCK)
    petition = create_petition(case_number=case_number)
    return open_scope_analysis(petition["id"])


def test_community_of_interest_factor_above_one_hundred_is_refused():
    """A community-of-interest factor outside the nought-to-hundred band is an
    invalid request, and the roster stays empty.

    PRD: "The payload also carries the two parties' asserted positions — `employer_position` and `union_position`, each either `INCLUDE` or `EXCLUDE` — and the five community-of-interest factors that the parties argue over: `supervision_overlap`, `skills_overlap`, `functional_integration`, `interchange_rate` and `work_conditions_overlap`, each an integer from 0 to 100 inclusive."
    PRD: "**Request schema** — the body parses, every required field is present, every enumerated value is in range, integers are integers, community-of-interest factors lie between 0 and 100 inclusive, pagination is in range, and every datetime is ISO 8601 with a `Z` offset. Otherwise `ERR_INVALID_REQUEST` (422)."

    Design: Corner/entities/out_of_range_enum_and_factor_values_rejected
    """
    petition = _case_in_scope_analysis_without_a_roster("07-RC-340009")

    response = api_client.create_classification(
        {"petition_id": petition["id"], **dict(PROD_SPEC, supervision_overlap=101)}, DIRECTOR
    )

    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST)
    _rows, meta = validate_paginated(
        api_client.list_classifications(BOARD, {"petition_id": petition["id"],
                                               "limit": 50, "offset": 0})
    )
    assert meta["total_count"] == 0
    assert read_petition(petition["id"])["total_classified_headcount"] == 0


def test_classification_with_a_zero_headcount_is_refused():
    """A classification claiming no employees at all is an invalid request, and
    no headcount reaches the case.

    PRD: "Both the headcount and the wage must be at least 1."
    PRD: "**Request schema** — the body parses, every required field is present, every enumerated value is in range, integers are integers, community-of-interest factors lie between 0 and 100 inclusive, pagination is in range, and every datetime is ISO 8601 with a `Z` offset. Otherwise `ERR_INVALID_REQUEST` (422)."

    Design: Corner/entities/out_of_range_enum_and_factor_values_rejected
    """
    petition = _case_in_scope_analysis_without_a_roster("07-RC-340009")

    response = api_client.create_classification(
        {"petition_id": petition["id"], **dict(PROD_SPEC, headcount=0)}, DIRECTOR
    )

    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST)
    _rows, meta = validate_paginated(
        api_client.list_classifications(BOARD, {"petition_id": petition["id"],
                                               "limit": 50, "offset": 0})
    )
    assert meta["total_count"] == 0
    assert read_petition(petition["id"])["total_classified_headcount"] == 0


def test_docketing_a_petition_type_outside_the_declared_set_is_refused():
    """Only the three declared petition types are docketable; anything else is an
    invalid request and no case is created.

    PRD: "The docketing payload carries the Board's docket number as `case_number`, the `petition_type` — `RC` for a union-filed certification petition, `RM` for an employer-filed one, `RD` for a decertification petition — the petitioning labor organization as `union_name`, the calendar date the petition was docketed as `filed_date`, the unit description exactly as the petition words it in `proposed_unit_description`, the headcount the petitioner claims is in the unit as `claimed_employee_count`, and the last day of the payroll period that fixes voter eligibility as `payroll_period_end`."
    PRD: "**Request schema** — the body parses, every required field is present, every enumerated value is in range, integers are integers, community-of-interest factors lie between 0 and 100 inclusive, pagination is in range, and every datetime is ISO 8601 with a `Z` offset. Otherwise `ERR_INVALID_REQUEST` (422)."

    Design: Corner/entities/out_of_range_enum_and_factor_values_rejected
    """
    _case_in_scope_analysis_without_a_roster("07-RC-340009")

    response = api_client.create_petition(
        dict(DOCKETING_PAYLOAD, case_number="07-RC-340010", petition_type="RX"), DIRECTOR
    )

    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST)
    rows, meta = validate_paginated(
        api_client.list_petitions(DIRECTOR, {"limit": 50, "offset": 0})
    )
    assert meta["total_count"] == 1
    assert all(row["case_number"] != "07-RC-340010" for row in rows)


# ---------------------------------------------------------------------------
# Omitted optional inputs
# ---------------------------------------------------------------------------
def test_classification_omitting_the_supervisory_indicia_count_takes_its_default():
    """A roster row that says nothing about supervisory indicia records none, and
    it arrives unruled with no rationale.

    PRD: "An optional `supervisory_authority_count` records how many Section 2(11) indicia of supervisory authority — hiring, firing, discipline, assignment and the rest — the classification exercises; it defaults to 0 and may not be negative."
    PRD: "A new classification starts with `scope_ruling` `PENDING` and no `ruling_rationale`, and its `wage_proximity`, `coi_score`, `scoring_standard` and `coi_recommendation` are all absent until it is scored."

    Design: Corner/entities/omitted_optional_inputs_take_declared_defaults
    """
    petition = _case_in_scope_analysis_without_a_roster("07-RC-340007")
    payload = {
        key: value for key, value in PROD_SPEC.items() if key != "supervisory_authority_count"
    }
    payload["petition_id"] = petition["id"]

    response = api_client.create_classification(payload, DIRECTOR)

    data = validate_success(response, 201)
    assert data["supervisory_authority_count"] == 0
    assert data["scope_ruling"] == "PENDING"
    assert data.get("ruling_rationale") is None


def test_campaign_draft_omitting_its_optional_content_fields_takes_its_defaults():
    """A draft message that declares neither a duration nor any threat statements
    gets the declared hour-long duration and a zeroed, unreviewed draft posture.

    PRD: "The payload names the `petition_id`, the `channel` — one of `EMAIL`, `LETTER`, `DIGITAL_POST`, `SMALL_GROUP_MEETING` or `CAPTIVE_AUDIENCE_MEETING` — the `audience_scope`, which is `UNIT_WIDE`, `CLASSIFICATION` or `INDIVIDUAL`, the `planned_delivery_at` instant at which delivery or presentation begins, an optional `duration_minutes` defaulting to 60 and never below 1, and a `message_summary`."
    PRD: "A draft starts at `status` `DRAFT` with `revision_round` 0, `risk_score` 0, `peerless_plywood_violation` false and `escalation_ack` false, records the drafting user's `X-User-ID` in `authored_by_user_id`, and leaves `reviewed_by_user_id`, `accuracy_reviewed_at`, `delivered_at` and `blocked_reason` absent."

    Design: Corner/entities/omitted_optional_inputs_take_declared_defaults
    """
    petition = _case_in_scope_analysis_without_a_roster("07-RC-340007")

    message = create_campaign_message(
        petition["id"],
        channel="EMAIL",
        audience_scope="UNIT_WIDE",
        planned_delivery_at="2026-08-25T13:00:00Z",
        message_summary="States the employer position on the pending representation petition.",
    )

    assert message["duration_minutes"] == 60
    assert message["threat_statement_count"] == 0
    assert message["status"] == "DRAFT"
    assert message["revision_round"] == 0
    assert message["risk_score"] == 0
    assert message["peerless_plywood_violation"] is False
    assert message["escalation_ack"] is False
    assert message.get("accuracy_reviewed_at") is None


def test_voter_entry_omitting_the_leave_status_takes_its_default():
    """An entry that says nothing about leave records the employee as not on
    leave.

    PRD: "The remainder of the payload is optional and is where the statutory content lives: `home_address`, `personal_email`, `personal_phone`, `shift_code` and `work_location`, plus a `termination_date` for a separated employee and an `on_leave_type` recording leave status on the eligibility date, which is one of `NONE`, `SICK`, `FMLA`, `MILITARY` or `PERMANENT_LAYOFF` and defaults to `NONE`."

    Design: Corner/entities/omitted_optional_inputs_take_declared_defaults
    """
    ctx = setup_draft_voter_list(entry_count=1)

    entry = ctx["entries"][0]

    assert entry["on_leave_type"] == "NONE"


# ---------------------------------------------------------------------------
# Filing the eligible-voter list
# ---------------------------------------------------------------------------
def _draft_list_on_a_stipulation_approved_on_thursday() -> dict:
    """Two ruled classifications, an election stipulated on Thursday 2026-08-20,
    and a draft list carrying one complete entry per classification.
    """
    ctx = setup_soi_verified(
        petition_overrides={"case_number": "07-RC-340008"},
        classification_specs=[PROD_SPEC, MAINT_SPEC],
    )
    agreement = create_election_agreement(ctx["petition"]["id"])
    set_clock("2026-08-20T15:00:00Z")
    ctx["agreement"] = stipulate_agreement(
        agreement["id"],
        approved_election_date="2026-09-01",
        voting_method="MANUAL",
        polls_open_at="2026-09-01T06:00:00Z",
        polls_close_at="2026-09-01T17:00:00Z",
    )
    voter_list = create_voter_list(ctx["petition"]["id"], ctx["agreement"]["id"])
    add_voter_entry(voter_list["id"], ctx["classifications"][0]["id"],
                    full_name="Ana Ruiz", personal_email="ana.ruiz@example.com")
    add_voter_entry(voter_list["id"], ctx["classifications"][1]["id"],
                    full_name="Bo Kim", personal_email="bo.kim@example.com")
    ctx["voter_list"] = read_voter_list(voter_list["id"])
    return ctx


def test_filing_the_voter_list_records_the_attesting_director_and_the_filing_instant():
    """Filing stamps the list with the logical clock, the attesting director's own
    user identity and the attested title, and moves it out of draft.

    PRD: "On success the list moves to `SUBMITTED`, `submitted_at` is stamped with the logical clock, `submitted_by_user_id` records the attesting director's `X-User-ID`, and the title is stored."

    Design: Corner/entities/voter_list_submit_records_system_user_and_clock_fields
    """
    ctx = _draft_list_on_a_stipulation_approved_on_thursday()
    set_clock("2026-08-21T10:00:00Z")

    response = api_client.submit_voter_list(
        ctx["voter_list"]["id"],
        {"attested_by_title": "Director of Labor Relations"},
        make_director_headers("user-director-7"),
    )

    data = validate_success(response)
    assert data["submitted_by_user_id"] == "user-director-7"
    assert_instant_equals(data["submitted_at"], "2026-08-21T10:00:00Z", "voter_list.submitted_at")
    assert data["attested_by_title"] == "Director of Labor Relations"
    assert data["status"] == "SUBMITTED"


def test_a_fully_complete_list_filed_before_its_deadline_grades_compliant_and_on_time():
    """The list inherits the two-business-day deadline from the stipulation, is
    not late when filed inside it, and grades compliant when every entry carries
    its statutory content.

    PRD: "A stipulated approval landing on Thursday 2026-08-20 counts Friday the 21st and Monday the 24th, so the list is due at `2026-08-24T23:59:59Z`."
    PRD: "`is_late` is true exactly when `submitted_at` falls after `due_at`; equality is on time, and one second later is late."
    PRD: "The base tier follows from the rounded percentage: exactly 100.00 is `COMPLIANT`, at least 90.00 is `MINOR_DEFECT`, at least 75.00 is `MATERIAL_DEFECT`, and anything below 75.00 is `GROSSLY_DEFICIENT`."

    Design: Corner/entities/voter_list_submit_records_system_user_and_clock_fields
    """
    ctx = _draft_list_on_a_stipulation_approved_on_thursday()
    set_clock("2026-08-21T10:00:00Z")

    response = api_client.submit_voter_list(
        ctx["voter_list"]["id"],
        {"attested_by_title": "Director of Labor Relations"},
        make_director_headers("user-director-7"),
    )

    data = validate_success(response)
    assert_instant_equals(data["due_at"], add_business_days("2026-08-20", 2), "voter_list.due_at")
    assert data["is_late"] is False
    assert data["total_entry_count"] == 2
    assert data["complete_entry_count"] == 2
    assert float(data["completeness_pct"]) == pytest.approx(100.00, abs=0.005)
    assert data["list_grade"] == "COMPLIANT"


# ---------------------------------------------------------------------------
# Polling windows and cross-case references
# ---------------------------------------------------------------------------
def test_poll_session_ending_exactly_when_it_starts_is_refused():
    """A polling session must cover a real interval, so an end instant equal to
    its start is refused and the round gains no session.

    PRD: "Wherever a request supplies a pair of instants bounding an interval, the later instant must be strictly after the earlier one: a poll session's `session_end_at` must be strictly after its `session_start_at`, and an election arrangement's `polls_close_at` must be strictly after its `polls_open_at`."
    PRD: "A violation is reported as `ERR_INVALID_TIME_WINDOW` (HTTP 422)."

    Design: Corner/entities/poll_session_end_not_after_start_rejected
    """
    ctx = setup_election_set(
        petition_overrides={"case_number": "07-RC-340011"},
        fix_overrides={
            "polls_open_at": "2026-09-01T06:00:00Z",
            "polls_close_at": "2026-09-01T17:00:00Z",
        },
    )
    election_round = ctx["round"]
    version_before = election_round["version"]

    response = api_client.create_poll_session(
        {
            "election_round_id": election_round["id"],
            "location_code": "GATE_A",
            "session_start_at": "2026-09-01T06:00:00Z",
            "session_end_at": "2026-09-01T06:00:00Z",
            "method": "MANUAL",
            "expected_election_round_version": version_before,
        },
        BOARD,
    )

    validate_error(response, ApiErrorId.ERR_INVALID_TIME_WINDOW)
    assert response.json()["response_type"] == "error"
    after = read_round(election_round["id"])
    assert after["scheduled_session_count"] == 0
    assert after["version"] == version_before


def test_voter_entry_naming_another_cases_classification_is_refused():
    """An entry must draw its classification from the same case as the list it
    joins; naming another case's classification is a cross-case reference and the
    list stays empty.

    PRD: "Every entity named in a request must belong to the same petition as the request's target, and a mismatch is reported as `ERR_CROSS_PETITION_REFERENCE` (HTTP 409)."
    PRD: "Concretely, a voter entry's classification must sit on the same petition as the list it joins; a voter list's election agreement must belong to the list's petition; a campaign message's presenting supervisor must be registered on the message's petition, as must a supervisor named as an observer; and a charge consolidated with an objection must name an objection whose round belongs to the charge's petition."

    Design: Corner/entities/voter_list_entry_naming_another_petitions_classification_rejected
    """
    ctx = setup_draft_voter_list(
        entry_count=0, petition_overrides={"case_number": "07-RC-340012"}
    )
    other_case = create_petition(case_number="07-RC-340013")
    open_scope_analysis(other_case["id"])
    other_classification = add_classification(other_case["id"], **WHSE_SPEC)

    response = api_client.create_voter_list_entry(
        {
            "voter_list_id": ctx["voter_list"]["id"],
            "classification_id": other_classification["id"],
            **STATUTORY_ENTRY_CONTENT,
        },
        ANALYST,
    )

    validate_error(response, ApiErrorId.ERR_CROSS_PETITION_REFERENCE)
    assert response.json()["response_type"] == "error"
    after = read_voter_list(ctx["voter_list"]["id"])
    assert after["total_entry_count"] == 0
    assert after["complete_entry_count"] == 0
