"""Program setup, counseling-case CRUD, input validation, and list filtering.

Translates queue-B corner instances from the `entities` and `endpoints` sections.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    assert_family, assert_case,
    create_family_payload, create_case_payload,
    create_pedigree_member_payload,
    TEST_USERS, make_counselor_headers,
    create_family, create_counselor,
)

ADMIN = TEST_USERS["admin_headers"]


def test_create_family_initializes_outreach_ledger(api):
    """PRD 3.1: "A family is created with a family_name and its outreach_budget_cents;
    on creation the outreach ledger initializes with outreach_reserved_cents and
    outreach_spent_cents at zero and outreach_available_cents equal to the full budget,
    and both cascade counters at zero."

    Design: Corner/entities/create_family_returns_envelope_and_ledger_defaults
    """
    res = api.create_family(
        create_family_payload(family_name="Kindred A", outreach_budget_cents=25000), ADMIN)
    fam = validate_success(res, 201)
    assert_family(fam)
    assert fam["outreach_reserved_cents"] == 0
    assert fam["outreach_spent_cents"] == 0
    assert fam["outreach_available_cents"] == 25000


def test_fresh_family_cascade_uptake_is_zero(api):
    """PRD 2.7: "cascade_uptake_pct is cascade_cases_count divided by
    cascade_invitations_sent_count, rounded half up to four decimal places; when the
    denominator is zero the uptake is exactly 0.0."

    Design: Difficulty/boundary_precision_check/cascade_uptake_empty_denominator_is_zero
    """
    res = api.create_family(
        create_family_payload(family_name="Kindred Z", outreach_budget_cents=10000), ADMIN)
    fam = validate_success(res, 201)
    assert fam["cascade_uptake_pct"] == 0.0


def test_fresh_family_cascade_counters_are_zero(api):
    """PRD 3.1: "on creation the outreach ledger initializes with outreach_reserved_cents
    and outreach_spent_cents at zero and outreach_available_cents equal to the full
    budget, and both cascade counters at zero." PRD 2.7: "cascade_invitations_sent_count
    is the number of the family's invitations whose status is anything other than DRAFT".

    Design: Difficulty/boundary_precision_check/cascade_uptake_empty_denominator_is_zero
    """
    fam = create_family(name="Kindred Z2")
    fetched = validate_success(api.get_family(fam["id"], ADMIN), 200)
    assert fetched["cascade_invitations_sent_count"] == 0
    assert fetched["cascade_cases_count"] == 0


def test_get_unknown_case_returns_not_found(api):
    """PRD 2.5: "the first identifier that does not resolve produces its own not-found
    error (for example ERR_CASE_NOT_FOUND, ERR_ORDER_NOT_FOUND, ERR_RESULT_NOT_FOUND)
    before any deeper resource is consulted."

    Design: Corner/entities/get_case_not_found_returns_404
    """
    res = api.get_case("00000000-0000-4000-8000-000000000000", ADMIN)
    validate_error(res, "ERR_CASE_NOT_FOUND", expected_status=404)


def test_create_case_missing_covered_sessions_rejected(api):
    """PRD 3.2: "The counselor supplies a free-text referral_reason and the case's
    covered_sessions allotment." PRD 2.5: "Sixth is body validation — required fields
    present and well-typed, enum members valid, and numeric ranges respected ... —
    yielding ERR_VALIDATION."

    Design: Corner/entities/create_case_missing_required_covered_sessions_rejected
    """
    fam = create_family(name="Kindred B")
    gc = create_counselor()
    payload = create_case_payload(fam["id"], gc["id"])
    del payload["covered_sessions"]
    res = api.create_case(payload, make_counselor_headers(gc["id"]))
    validate_error(res, "ERR_VALIDATION", expected_status=422)


def test_create_case_applies_optional_field_defaults(api):
    """PRD 3.2: "Two fields are optional: relationship_to_proband defaults to PROBAND
    and otherwise takes FIRST_DEGREE, SECOND_DEGREE, or THIRD_DEGREE; and
    familial_variant_known defaults to false". PRD 3.2: "A newly opened case starts
    with clinical_status at INTAKE, billing_status at UNBILLED, sessions_used at zero,
    and sessions_remaining equal to covered_sessions."

    Design: Corner/entities/create_case_defaults_applied
    """
    fam = create_family(name="Kindred C")
    gc = create_counselor()
    res = api.create_case(
        create_case_payload(fam["id"], gc["id"], covered_sessions=4),
        make_counselor_headers(gc["id"]))
    case = validate_success(res, 201)
    assert case["relationship_to_proband"] == "PROBAND"
    assert case["familial_variant_known"] is False
    assert case["clinical_status"] == "INTAKE"
    assert case["billing_status"] == "UNBILLED"
    assert case["sessions_remaining"] == 4


def test_create_case_invalid_sex_enum_rejected(api):
    """PRD 3.2: patient "sex (MALE, FEMALE, or OTHER)". PRD 2.5: "Sixth is body
    validation — required fields present and well-typed, enum members valid, and
    numeric ranges respected ... — yielding ERR_VALIDATION."

    Design: Corner/entities/create_case_invalid_enum_sex_rejected
    """
    fam = create_family(name="Kindred D")
    gc = create_counselor()
    res = api.create_case(
        create_case_payload(fam["id"], gc["id"], sex="X", covered_sessions=1),
        make_counselor_headers(gc["id"]))
    validate_error(res, "ERR_VALIDATION", expected_status=422)


def test_create_case_unknown_family_returns_not_found(api):
    """PRD 2.5: "Existence of every path- and body-referenced resource is third,
    yielding the appropriate not-found error."

    Design: Corner/entities/create_case_unknown_family_fk_not_found
    """
    gc = create_counselor()
    res = api.create_case(
        create_case_payload("00000000-0000-4000-8000-000000000001", gc["id"],
                            covered_sessions=1),
        make_counselor_headers(gc["id"]))
    validate_error(res, "ERR_FAMILY_NOT_FOUND", expected_status=404)


def test_create_case_ignores_client_supplied_clinical_status(api):
    """PRD 3.2: "A newly opened case starts with clinical_status at INTAKE,
    billing_status at UNBILLED, sessions_used at zero, and sessions_remaining equal to
    covered_sessions."

    Design: Corner/entities/create_case_system_fields_input_ignored
    """
    fam = create_family(name="Kindred E")
    gc = create_counselor()
    payload = create_case_payload(fam["id"], gc["id"], covered_sessions=1)
    payload["clinical_status"] = "SURVEILLANCE"
    res = api.create_case(payload, make_counselor_headers(gc["id"]))
    case = validate_success(res, 201)
    assert case["clinical_status"] == "INTAKE"


def test_list_cases_filtered_by_family_carries_pagination(api):
    """PRD 3.2: "Cases can be listed with optional filters on family_id,
    assigned_counselor_id, and originating_invitation_id." PRD 2.3: "Every list
    response includes limit, offset, total_count, and has_more in the meta object of
    the envelope."

    Design: Corner/entities/list_cases_pagination_envelope
    """
    fam = create_family(name="Kindred F")
    gc = create_counselor()
    hdr = make_counselor_headers(gc["id"])
    api.create_case(create_case_payload(fam["id"], gc["id"], patient_name="P1",
                                        covered_sessions=1), hdr)
    api.create_case(create_case_payload(fam["id"], gc["id"], patient_name="P2",
                                        covered_sessions=1), hdr)
    data, meta = validate_paginated(api.list_cases(ADMIN, params={"family_id": fam["id"]}))
    assert meta["total_count"] == 2
    assert meta["has_more"] is False


def test_pedigree_members_listed_by_case(api):
    """PRD 3.2: "Pedigree members can be listed with optional filters on
    counseling_case_id and related_member_id."

    Design: Corner/endpoints/pedigree_members_reverse_lookup_by_case
    """
    fam = create_family(name="Kindred X")
    gc = create_counselor()
    hdr = make_counselor_headers(gc["id"])
    case = validate_success(
        api.create_case(create_case_payload(fam["id"], gc["id"], covered_sessions=1), hdr), 201)
    api.create_pedigree_member(
        create_pedigree_member_payload(case["id"], relationship="SIBLING", degree=1,
                                       affected=True, age_of_onset=40), hdr)
    api.create_pedigree_member(
        create_pedigree_member_payload(case["id"], relationship="PARENT", degree=1,
                                       affected=False, age_of_onset=None), hdr)
    data, meta = validate_paginated(
        api.list_pedigree_members(hdr, params={"counseling_case_id": case["id"]}))
    assert meta["total_count"] == 2
    assert all(m["counseling_case_id"] == case["id"] for m in data)
