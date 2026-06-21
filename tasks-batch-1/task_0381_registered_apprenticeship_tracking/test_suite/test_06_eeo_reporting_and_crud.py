"""EEO reporting (completion-rate dual variant, largest-remainder distribution,
empty cohort) and CRUD / input-validation / read-channel corners.

Covers dual_variant_calc (EEO completion rate), combinatorial_formula (largest
remainder), the entities / endpoints / errors corners, and the empty-cohort
calculation corner.
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    ApiErrorId,
    assert_sponsor,
    assert_apprentice,
    assert_distribution_sums_to_100,
    create_sponsor,
    create_qualified_journeyworker,
    create_apprentice,
    create_active_program,
    create_draft_program,
    create_draft_agreement,
    create_active_agreement,
    register_agreement,
    current_program_version,
    log_and_approve_ojt,
    record_rti,
    complete_agreement,
    NON_EXISTENT_UUID,
    AGENCY,
)
from test_helpers.test_users import make_sponsor_headers


# ===========================================================================
# Difficulty: dual_variant_calc / eeo_completion_rate_registered_vs_active_cohort_diverges
# ===========================================================================
def _build_cohort_4(api):
    """Sponsor + program (ratio 8) with four agreements: 1 COMPLETED, 1 CANCELLED,
    2 ACTIVE. Returns (sponsor_id, program_id)."""
    sponsor = create_sponsor()
    jw = create_qualified_journeyworker(sponsor["id"])
    headers = make_sponsor_headers(sponsor["id"])
    program = create_active_program(
        sponsor["id"], wage_ladder=[(1, 0, 0.50)], journeyman_ratio=8,
        ojt_hours_required=16, rti_hours_required=8,
    )
    aps = [create_apprentice(sponsor["id"], gender=g, race_ethnicity=r)
           for g, r in [("MALE", "WHITE"), ("FEMALE", "BLACK"),
                        ("MALE", "ASIAN"), ("FEMALE", "HISPANIC")]]

    # AGR1 -> COMPLETED (meet requirements first).
    agr1 = create_active_agreement(sponsor["id"], program["id"], aps[0]["id"], jw["id"])
    log_and_approve_ojt(sponsor["id"], agr1["id"], 0, 600, 16)
    record_rti(sponsor["id"], agr1["id"], 8)
    complete_agreement(agr1["id"])

    # AGR2 -> CANCELLED.
    agr2 = create_draft_agreement(sponsor["id"], program["id"], aps[1]["id"], jw["id"])
    register_agreement(sponsor["id"], agr2["id"], current_program_version(sponsor["id"], program["id"]))
    validate_success(api.cancel_agreement(agr2["id"], headers))

    # AGR3, AGR4 -> ACTIVE.
    create_active_agreement(sponsor["id"], program["id"], aps[2]["id"], jw["id"])
    create_active_agreement(sponsor["id"], program["id"], aps[3]["id"], jw["id"])
    return sponsor["id"], program["id"]


def test_eeo_completion_rate_registered_cohort(api):
    """PRD §3.8: "Under `REGISTERED_COHORT` the `total_apprentices` denominator
    counts every agreement of the program whose status is not `DRAFT` - which
    includes `CANCELLED` agreements."
    PRD §3.8: "The `completion_rate_pct` is the completed count divided by the
    denominator, multiplied by 100, rounded half-up to two decimal places; when
    the denominator is zero, the rate is exactly 0."

    1 COMPLETED + 1 CANCELLED + 2 ACTIVE = denominator 4; rate 1/4*100 = 25.0.

    Design: Difficulty/dual_variant_calc/eeo_completion_rate_registered_vs_active_cohort_diverges
    """
    sponsor_id, program_id = _build_cohort_4(api)
    rep = validate_success(
        api.create_eeo_report({"program_id": program_id, "cohort_basis": "REGISTERED_COHORT"}, AGENCY), 201
    )
    assert rep["total_apprentices"] == 4, f"registered denominator expected 4, got {rep['total_apprentices']}"
    assert rep["completion_rate_pct"] == 25.0, f"expected 25.0, got {rep['completion_rate_pct']}"


def test_eeo_completion_rate_active_cohort(api):
    """PRD §3.8: "Under `ACTIVE_COHORT` the denominator counts only agreements in
    `ACTIVE` or `COMPLETED`, excluding `CANCELLED`, `SUSPENDED`, and `REGISTERED`."
    PRD §3.8: "The `completion_rate_pct` is the completed count divided by the
    denominator, multiplied by 100, rounded half-up to two decimal places; when
    the denominator is zero, the rate is exactly 0."

    Same program, ACTIVE_COHORT denominator = 1 COMPLETED + 2 ACTIVE = 3; rate
    1/3*100 = 33.33 -- diverging from the 25.0 registered-cohort result.

    Design: Difficulty/dual_variant_calc/eeo_completion_rate_registered_vs_active_cohort_diverges
    """
    sponsor_id, program_id = _build_cohort_4(api)
    rep = validate_success(
        api.create_eeo_report({"program_id": program_id, "cohort_basis": "ACTIVE_COHORT"}, AGENCY), 201
    )
    assert rep["total_apprentices"] == 3, f"active denominator expected 3, got {rep['total_apprentices']}"
    assert rep["completion_rate_pct"] == 33.33, f"expected 33.33, got {rep['completion_rate_pct']}"


# ===========================================================================
# Difficulty: combinatorial_formula / eeo_largest_remainder_rounding_mode_b
# ===========================================================================
def test_eeo_race_distribution_largest_remainder(api):
    """PRD §3.8: "for each category, first form its exact share as the category's
    count divided by N multiplied by 100, then round that share down to a whole
    number (floor it). Sum those floored values and subtract from 100 to find how
    many leftover percentage points remain. Distribute the leftover points one at
    a time to the categories with the largest fractional remainders (the exact
    share minus its floor), breaking ties by the category's declaration order in
    the enumeration (the `gender` ordering, or the `race_ethnicity` ordering)."

    ACTIVE cohort of 6: race ASIAN=1, BLACK=2, HISPANIC=3 over N=6 -> raw
    16.67/33.33/50.0 -> floors 16/33/50 (sum 99) -> the single leftover point goes
    to ASIAN (largest remainder 0.67): ASIAN=17, BLACK=33, HISPANIC=50, sum 100.

    Design: Difficulty/combinatorial_formula/eeo_largest_remainder_rounding_mode_b
    """
    sponsor = create_sponsor()
    jw = create_qualified_journeyworker(sponsor["id"])
    program = create_active_program(
        sponsor["id"], wage_ladder=[(1, 0, 0.50)], journeyman_ratio=8,
    )
    races = ["ASIAN", "BLACK", "BLACK", "HISPANIC", "HISPANIC", "HISPANIC"]
    for r in races:
        ap = create_apprentice(sponsor["id"], race_ethnicity=r)
        create_active_agreement(sponsor["id"], program["id"], ap["id"], jw["id"])

    rep = validate_success(
        api.create_eeo_report({"program_id": program["id"], "cohort_basis": "ACTIVE_COHORT"}, AGENCY), 201
    )
    dist = rep["race_distribution_pct"]
    assert dist["HISPANIC"] == 50, f"HISPANIC expected 50, got {dist.get('HISPANIC')}"
    assert dist["BLACK"] == 33, f"BLACK expected 33, got {dist.get('BLACK')}"
    assert dist["ASIAN"] == 17, f"ASIAN expected 17 (largest remainder), got {dist.get('ASIAN')}"
    assert_distribution_sums_to_100(dist)


def test_eeo_distribution_sums_to_exactly_100(api):
    """PRD §3.8: "The two demographic distributions are computed over the distinct
    apprentices in the chosen cohort, deduplicated by `apprentice_id`, and each is
    a whole-percent breakdown - by `gender` for one map and by `race_ethnicity`
    for the other - that must sum to exactly 100."

    The largest-remainder race distribution over the 1/2/3 cohort sums to exactly
    100.

    Design: Difficulty/combinatorial_formula/eeo_largest_remainder_rounding_mode_b
    """
    sponsor = create_sponsor()
    jw = create_qualified_journeyworker(sponsor["id"])
    program = create_active_program(
        sponsor["id"], wage_ladder=[(1, 0, 0.50)], journeyman_ratio=8,
    )
    races = ["ASIAN", "BLACK", "BLACK", "HISPANIC", "HISPANIC", "HISPANIC"]
    for r in races:
        ap = create_apprentice(sponsor["id"], race_ethnicity=r)
        create_active_agreement(sponsor["id"], program["id"], ap["id"], jw["id"])
    rep = validate_success(
        api.create_eeo_report({"program_id": program["id"], "cohort_basis": "ACTIVE_COHORT"}, AGENCY), 201
    )
    assert_distribution_sums_to_100(rep["race_distribution_pct"])


# ===========================================================================
# Corner: calculations / eeo_distribution_empty_cohort_zero_percent
# ===========================================================================
def test_eeo_empty_cohort_zero_percent(api):
    """PRD §3.8: "Let N be the number of distinct cohort apprentices; if N is
    zero, every category percent is 0."
    PRD §3.8: "The `completion_rate_pct` is the completed count divided by the
    denominator, multiplied by 100, rounded half-up to two decimal places; when
    the denominator is zero, the rate is exactly 0."

    A program with no agreements yields total_apprentices 0 and
    completion_rate_pct 0 (no divide-by-zero).

    Design: Corner/calculations/eeo_distribution_empty_cohort_zero_percent
    """
    sponsor = create_sponsor()
    program = create_active_program(sponsor["id"], wage_ladder=[(1, 0, 0.50)])
    rep = validate_success(
        api.create_eeo_report({"program_id": program["id"], "cohort_basis": "REGISTERED_COHORT"}, AGENCY), 201
    )
    assert rep["total_apprentices"] == 0
    assert rep["completion_rate_pct"] == 0


# ===========================================================================
# Corner: entities / create_sponsor_returns_201_with_system_fields
# ===========================================================================
def test_create_sponsor_returns_201_with_system_fields(api, sponsor_headers):
    """PRD §3.1: "A sponsor record is created with its `legal_name`, its `ein`
    (an employer identification number in the form of two digits, a hyphen, then
    seven digits), and a `contact_email`."
    PRD §2.4: "`version` (integer): a server-managed integer that begins at its
    initial value and increments by one with every modification to the resource."

    POST /apprenticeship/sponsors returns 201 with a minted id, the echoed
    legal_name, and version 1.

    Design: Corner/entities/create_sponsor_returns_201_with_system_fields
    """
    res = api.create_sponsor(
        {"legal_name": "Acme", "ein": "12-3456789", "contact_email": "a@x.test"},
        sponsor_headers,
    )
    sponsor = validate_success(res, 201)
    assert_sponsor(sponsor)
    assert sponsor["legal_name"] == "Acme"
    assert sponsor["version"] == 1


# ===========================================================================
# Corner: entities / create_program_missing_required_field_rejected
# ===========================================================================
def test_create_program_missing_occupation_code_rejected(api):
    """PRD §2.8: "A malformed body, a missing required field, or a type or enum
    mismatch is rejected with `ERR_INVALID_REQUEST`."

    Omitting the required occupation_code on program create -> ERR_INVALID_REQUEST.

    Design: Corner/entities/create_program_missing_required_field_rejected
    """
    sponsor = create_sponsor()
    res = api.create_program(
        {"sponsor_id": sponsor["id"], "occupation_title": "Electrician",
         "completion_type": "HOURS_BASED", "ojt_hours_required": 16,
         "rti_hours_required": 8, "base_journeyworker_wage_cents": 4000,
         "journeyman_ratio": 4},
        make_sponsor_headers(sponsor["id"]),
    )
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value)


# ===========================================================================
# Corner: entities / create_program_invalid_completion_type_enum_rejected
# ===========================================================================
def test_create_program_invalid_completion_type_rejected(api):
    """PRD §2.8: "A malformed body, a missing required field, or a type or enum
    mismatch is rejected with `ERR_INVALID_REQUEST`."

    A completion_type of "TIME_TRAVEL" (outside the allowed enum) -> ERR_INVALID_REQUEST.

    Design: Corner/entities/create_program_invalid_completion_type_enum_rejected
    """
    sponsor = create_sponsor()
    res = api.create_program(
        {"sponsor_id": sponsor["id"], "occupation_code": "47-2111.00",
         "occupation_title": "Electrician", "completion_type": "TIME_TRAVEL",
         "ojt_hours_required": 16, "rti_hours_required": 8,
         "base_journeyworker_wage_cents": 4000, "journeyman_ratio": 4},
        make_sponsor_headers(sponsor["id"]),
    )
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value)


# ===========================================================================
# Corner: entities / get_agreement_nonexistent_returns_not_found
# ===========================================================================
def test_get_nonexistent_agreement_returns_not_found(api, sponsor_headers):
    """PRD §2.8: "Path identifiers are validated first: if a path identifier does
    not correspond to an existing resource, the request is rejected with that
    resource's not-found error (for example `ERR_PROGRAM_NOT_FOUND`,
    `ERR_AGREEMENT_NOT_FOUND`, ...) before any business rule runs."

    GET of an unknown agreement id -> ERR_AGREEMENT_NOT_FOUND.

    Design: Corner/entities/get_agreement_nonexistent_returns_not_found
    """
    res = api.get_agreement(NON_EXISTENT_UUID, sponsor_headers)
    validate_error(res, ApiErrorId.ERR_AGREEMENT_NOT_FOUND.value)


# ===========================================================================
# Corner: entities / apprentice_default_flags_applied
# ===========================================================================
def test_apprentice_default_flags_false_when_omitted(api):
    """PRD §3.2: "Two affirmative-action flags, `is_veteran` and `has_disability`,
    default to false when omitted."

    Creating an apprentice without is_veteran / has_disability sets both to false.

    Design: Corner/entities/apprentice_default_flags_applied
    """
    sponsor = create_sponsor()
    res = api.create_apprentice(
        {"sponsor_id": sponsor["id"], "full_name": "AP1",
         "gender": "MALE", "race_ethnicity": "WHITE"},
        make_sponsor_headers(sponsor["id"]),
    )
    ap = validate_success(res, 201)
    assert_apprentice(ap)
    assert ap["is_veteran"] is False
    assert ap["has_disability"] is False


# ===========================================================================
# Corner: entities / agreement_computed_fields_input_ignored
# ===========================================================================
def test_agreement_computed_fields_default_on_create(api):
    """PRD §3.3: "On creation the agreement begins in `DRAFT` with
    `current_wage_step` at 1, `ojt_hours_completed` at 0, `rti_hours_completed`
    at 0, and `milestones_attained_count` at 0."
    PRD §2.5: "On an agreement, `ojt_hours_completed`, `rti_hours_completed`,
    `milestones_attained_count`, `current_wage_step`, `current_hourly_wage_cents`,
    and `completion_eligible` are all derived values."

    A new agreement reports ojt_hours_completed 0 and current_wage_step 1
    regardless of any client value; only declared inputs are honored.

    Design: Corner/entities/agreement_computed_fields_input_ignored
    """
    sponsor = create_sponsor()
    jw = create_qualified_journeyworker(sponsor["id"])
    ap = create_apprentice(sponsor["id"])
    program = create_active_program(sponsor["id"])
    res = api.create_agreement(
        {"program_id": program["id"], "apprentice_id": ap["id"],
         "journeyworker_id": jw["id"], "start_date": "2026-01-01",
         "ojt_hours_completed": 99, "current_wage_step": 4},
        make_sponsor_headers(sponsor["id"]),
    )
    agr = validate_success(res, 201)
    assert agr["ojt_hours_completed"] == 0
    assert agr["current_wage_step"] == 1
    assert agr["status"] == "DRAFT"


# ===========================================================================
# Corner: endpoints / list_agreements_filter_by_program_returns_array
# ===========================================================================
def test_list_agreements_filter_by_program(api):
    """PRD §3.3 / §4: "List agreements (filterable)" by `program_id`.
    PRD §2.3: "Paginated list responses include the following fields in the `meta`
    object of the response envelope: `limit`, `offset`, `total_count`, and
    `has_more`."

    GET /apprenticeship/agreements?program_id=<id> returns the program's
    agreement(s) as a paginated array with total_count in meta.

    Design: Corner/endpoints/list_agreements_filter_by_program_returns_array
    """
    sponsor = create_sponsor()
    jw = create_qualified_journeyworker(sponsor["id"])
    ap = create_apprentice(sponsor["id"])
    program = create_active_program(sponsor["id"])
    headers = make_sponsor_headers(sponsor["id"])
    agr = create_draft_agreement(sponsor["id"], program["id"], ap["id"], jw["id"])

    data, meta = validate_paginated(
        api.list_agreements(headers, params={"program_id": program["id"]})
    )
    ids = [row["id"] for row in data]
    assert agr["id"] in ids
    assert meta["total_count"] == 1
    assert meta["has_more"] is False


# ===========================================================================
# Corner: endpoints / fk_reverse_ojt_entries_by_agreement
# ===========================================================================
def test_list_ojt_entries_filter_by_agreement(api, training_coordinator_headers):
    """PRD §4: "List OJT entries (filterable by agreement, status)".
    PRD §3.4: "A newly logged session begins in `PENDING`."

    GET /apprenticeship/ojt-entries?agreement_id=<id> is the reverse-reachability
    channel for the OJT entry's agreement_id FK and returns that agreement's entry.

    Design: Corner/endpoints/fk_reverse_ojt_entries_by_agreement
    """
    from test_helpers import setup_active_agreement, log_ojt_entry
    sc = setup_active_agreement()
    entry = log_ojt_entry(sc.sponsor_id, sc.agreement_id, 480, 600, 2)
    data, _ = validate_paginated(
        api.list_ojt_entries(training_coordinator_headers, params={"agreement_id": sc.agreement_id})
    )
    matches = [row for row in data if row["id"] == entry["id"]]
    assert len(matches) == 1
    assert matches[0]["agreement_id"] == sc.agreement_id


# ===========================================================================
# Corner: errors / program_not_found_on_create_program_for_wage_step
# ===========================================================================
def test_wage_step_unknown_program_not_found(api):
    """PRD §2.8: "On a create that carries foreign-key fields - `program_id`,
    `sponsor_id`, `apprentice_id`, `journeyworker_id`, `agreement_id`, or
    `milestone_id` - each referenced resource must exist; a dangling reference is
    rejected with the corresponding resource's not-found error."

    A wage step whose program_id does not exist -> ERR_PROGRAM_NOT_FOUND.

    Design: Corner/errors/program_not_found_on_create_program_for_wage_step
    """
    sponsor = create_sponsor()
    res = api.create_wage_step(
        {"program_id": NON_EXISTENT_UUID, "step_number": 1,
         "ojt_hours_threshold": 0, "wage_pct": 0.50},
        make_sponsor_headers(sponsor["id"]),
    )
    validate_error(res, ApiErrorId.ERR_PROGRAM_NOT_FOUND.value)


# ===========================================================================
# Corner: errors / missing_user_context_header_rejected
# ===========================================================================
def test_missing_user_context_header_rejected(api):
    """PRD §2.1: "Every request must include `X-User-ID` to identify the acting
    user and `X-User-Role` to declare their operational capacity. If either
    header is missing or malformed, the request is rejected with
    `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."

    A request carrying neither auth header -> ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.

    Design: Corner/errors/missing_user_context_header_rejected
    """
    res = api.create_sponsor(
        {"legal_name": "NoAuth", "ein": "41-4242424", "contact_email": "na@x.test"},
        {},
    )
    validate_error(res, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value)
