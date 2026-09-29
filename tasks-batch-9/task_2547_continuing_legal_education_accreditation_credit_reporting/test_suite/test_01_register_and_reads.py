"""Registration defaults, single-resource reads, listing and reference errors.

Every test builds its own register from scratch through the endpoints the PRD
declares, because each test starts against an empty store with the board's
logical clock reading its startup default.
"""
from test_helpers import (
    CLOCK_DEFAULT_UTC,
    DEFAULT_PROVIDER_ANNUAL_FEE_CENTS,
    accreditation_action_payload,
    assert_append_only_identity,
    assert_attendance_code_shape,
    assert_credit_allocation,
    assert_fee_assessment,
    assert_no_uuid_prefix,
    assert_ordered_desc_by,
    assert_provider,
    assert_reporting_sweep,
    assert_utc_millisecond_timestamp,
    create_accredited_provider,
    assert_attorney,
    create_attorney_payload,
    create_compliance_cycle_payload,
    create_course_payload,
    create_credit_record_payload,
    create_provider_payload,
    create_self_certified_course,
    credit_allocation_entry,
    determination_payload,
    make_attorney_headers,
    make_provider_admin_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import fixtures

# An identifier that no row in the register ever carries.
MISSING_ID = "00000000-0000-4000-8000-00000000dead"

PROVIDER_COUNTERS = (
    "courses_total_count",
    "courses_self_certified_count",
    "attendance_reports_total_count",
    "attendance_reports_late_count",
    "substantiated_complaint_count",
    "audit_findings_count",
    "courses_sampled_lifetime",
)


def _canonical_instant(value: str) -> str:
    """Renders a wire timestamp in one comparable form so an expected instant
    written without fractional digits still compares equal."""
    assert type(value) is str and value.endswith("Z"), (
        f"a timestamp must be a UTC string ending in Z, got {value!r}"
    )
    body = value[:-1]
    if "." in body:
        head, fraction = body.split(".", 1)
        fraction = (fraction + "000")[:3]
    else:
        head, fraction = body, "000"
    return head + "." + fraction + "Z"


def assert_same_instant(actual, expected, label="instant"):
    assert _canonical_instant(actual) == _canonical_instant(expected), (
        f"{label} must be {expected}, got {actual}"
    )


def test_new_sponsor_defaults_survive_creation_and_the_read_back(api, board_headers):
    """PRD §3.1: "A new sponsor begins in `APPLIED` with `self_certification_enabled` false, a `risk_score` of 0.0, a `risk_score_variant` of `REVIEWED_WEIGHTING`, `accreditation_term_start` and `accreditation_term_end` both null, `probation_reason` null, and every counter at zero."
    PRD §3.1: "An `annual_fee_cents` figure may be supplied and must be zero or greater; when it is omitted the board's standard annual accreditation fee of 120000 cents — twelve hundred dollars — is used."
    PRD §2.5: "Every persisted resource carries a server-minted `id` that is a UUID string with no type prefix, and a `created_at` timestamp recorded at insertion."
    PRD §2.5: "Most resources also carry an `updated_at` timestamp, refreshed on every mutation of that row, and an integer `version` that starts at 1 on creation and increases by exactly 1 on every mutation of that row — including mutations the row did not ask for, such as a counter bump driven by a cascade from another entity."

    Design: Corner/entities/provider_creation_and_retrieval_return_the_applied_defaults_and_zero_risk
    """
    payload = create_provider_payload(
        name="Harborview Bar Academy",
        provider_type="COMMERCIAL",
        annual_fee_cents=90000,
    )
    created = validate_success(api.create_provider(payload, board_headers), expected_status=201)
    assert_provider(created)
    assert_no_uuid_prefix(created["id"])

    assert created["accreditation_status"] == "APPLIED", (
        f"a new sponsor begins in APPLIED, got {created['accreditation_status']}"
    )
    assert created["self_certification_enabled"] is False, (
        "a new sponsor begins with self_certification_enabled false, got "
        f"{created['self_certification_enabled']!r}"
    )
    assert created["version"] == 1, f"version starts at 1, got {created['version']}"
    assert created["annual_fee_cents"] == 90000, (
        f"the supplied annual_fee_cents must stand, got {created['annual_fee_cents']}"
    )
    assert float(created["risk_score"]) == 0.0, (
        f"a new sponsor begins with a risk_score of 0.0, got {created['risk_score']}"
    )
    assert created["risk_score_variant"] == "REVIEWED_WEIGHTING", (
        f"a new sponsor begins under REVIEWED_WEIGHTING, got {created['risk_score_variant']}"
    )
    assert created.get("accreditation_term_start") is None, (
        f"accreditation_term_start begins null, got {created.get('accreditation_term_start')!r}"
    )
    assert created.get("accreditation_term_end") is None, (
        f"accreditation_term_end begins null, got {created.get('accreditation_term_end')!r}"
    )
    assert created.get("probation_reason") is None, (
        f"probation_reason begins null, got {created.get('probation_reason')!r}"
    )
    for counter in PROVIDER_COUNTERS:
        assert created[counter] == 0, f"{counter} begins at zero, got {created[counter]}"
    assert created.get("last_audit_closed_at") is None, (
        "last_audit_closed_at is null on a sponsor that has never had an audit closed, got "
        f"{created.get('last_audit_closed_at')!r}"
    )

    read_back = validate_success(
        api.get_provider(created["id"], make_provider_admin_headers(created["id"])),
        expected_status=200,
    )
    assert read_back["version"] == 1, (
        f"a read never mutates the row, so version stays 1, got {read_back['version']}"
    )
    for field in (
        "id", "name", "provider_type", "accreditation_status",
        "self_certification_enabled", "annual_fee_cents", "risk_score_variant",
        "created_at",
    ) + PROVIDER_COUNTERS:
        assert read_back[field] == created[field], (
            f"the read must return the created value of {field}: "
            f"{read_back[field]!r} vs {created[field]!r}"
        )
    assert float(read_back["risk_score"]) == 0.0


def test_course_list_is_newest_first_filtered_and_paginated(api, board_headers):
    """PRD §2.3: "Four collections declare otherwise because their natural reading order is not their insertion order: the course list is returned newest first, ordered by `created_at` descending; the compliance-cycle list is ordered by `period_start` ascending and then `created_at` ascending; the credit-record list is ordered by `completion_date` ascending and then `created_at` ascending, which is exactly the order the credit-application algorithm consumes records in; and the provider-audit list is ordered by `audit_period_start` ascending and then `created_at` ascending."
    PRD §2.3: "For every list response, the `meta` object carries `limit`, `offset`, `total_count` and `has_more`."
    PRD §2.3: "`total_count` is the number of rows matching the filters before pagination is applied, and `has_more` is true exactly when rows remain beyond the returned page."
    PRD §2.9: "The course list accepts `provider_id`, `status`, `delivery_format` and `approval_pathway` filters and is the reverse-reachability channel for a course's sponsoring provider."
    PRD §2.9: "Filters combine conjunctively: supplying two filters returns only rows matching both."
    PRD §2.2: "The `response_type` is either "object" for a single resource or "array" for a list of resources."
    PRD §2.2: "The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`."

    Design: Corner/entities/course_listing_is_filtered_and_paginated_with_total_count_and_has_more
    """
    provider = create_accredited_provider(
        name="Statewide Bar CLE Institute", provider_type="BAR_ASSOCIATION"
    )
    sponsor_headers = make_provider_admin_headers(provider["id"])
    first_webcast = create_self_certified_course(
        provider,
        title="Civil Motion Practice",
        delivery_format="LIVE_WEBCAST",
        total_minutes=120,
        presented_at="2026-02-02T09:00:00Z",
        attendance_verification_method="ATTENDANCE_CODE",
        credit_allocations=[credit_allocation_entry("GENERAL", 120)],
    )
    second_webcast = create_self_certified_course(
        provider,
        title="Appellate Brief Workshop",
        delivery_format="LIVE_WEBCAST",
        total_minutes=180,
        presented_at="2026-03-03T09:00:00Z",
        attendance_verification_method="ATTENDANCE_CODE",
        credit_allocations=[credit_allocation_entry("GENERAL", 180)],
    )
    self_study = create_self_certified_course(
        provider,
        title="Trust Accounting Basics",
        delivery_format="SELF_STUDY",
        total_minutes=240,
        presented_at="2026-04-04T09:00:00Z",
        attendance_verification_method="AFFIRMATION_ONLY",
        credit_allocations=[credit_allocation_entry("GENERAL", 240)],
    )
    all_ids = {first_webcast["id"], second_webcast["id"], self_study["id"]}

    first_response = api.list_courses(
        sponsor_headers,
        params={"provider_id": provider["id"], "status": "APPROVED", "limit": 2, "offset": 0},
    )
    first_page, first_meta = validate_paginated(first_response)
    assert first_meta["total_count"] == 3, (
        "total_count counts the rows matching the filters before pagination, expected 3, got "
        f"{first_meta['total_count']}"
    )
    assert first_meta["has_more"] is True, (
        "has_more must be true while a third row remains beyond the page"
    )
    assert first_meta["limit"] == 2 and first_meta["offset"] == 0
    assert len(first_page) == 2, f"a limit of 2 returns 2 rows, got {len(first_page)}"
    assert_ordered_desc_by(first_page, "created_at")
    first_body = first_response.json()
    assert first_body["response_type"] == "array", (
        f"a list read is an array response, got {first_body['response_type']!r}"
    )
    assert first_body["meta"]["api_request_id"].startswith("req_"), (
        f"api_request_id must start with req_, got {first_body['meta']['api_request_id']!r}"
    )

    second_page, second_meta = validate_paginated(
        api.list_courses(
            sponsor_headers,
            params={"provider_id": provider["id"], "status": "APPROVED", "limit": 2, "offset": 2},
        )
    )
    assert second_meta["total_count"] == 3, (
        f"total_count ignores the page window, expected 3, got {second_meta['total_count']}"
    )
    assert second_meta["has_more"] is False, (
        "has_more must be false once no row remains beyond the returned page"
    )
    assert len(second_page) == 1, f"one row remains on the second page, got {len(second_page)}"
    assert {row["id"] for row in first_page} | {row["id"] for row in second_page} == all_ids, (
        "the two pages together must cover exactly the sponsor's three approved courses"
    )
    assert {row["id"] for row in first_page} & {row["id"] for row in second_page} == set(), (
        "an offset of 2 must not repeat a row already returned on the first page"
    )

    filtered, filtered_meta = validate_paginated(
        api.list_courses(
            sponsor_headers,
            params={"provider_id": provider["id"], "delivery_format": "SELF_STUDY"},
        )
    )
    assert filtered_meta["total_count"] == 1, (
        "two conjunctive filters return only the one self-study course, got total_count "
        f"{filtered_meta['total_count']}"
    )
    assert filtered_meta["has_more"] is False
    assert len(filtered) == 1 and filtered[0]["id"] == self_study["id"], (
        "the delivery_format filter must return the self-study course alone"
    )


def test_each_unknown_path_identifier_returns_its_own_not_found_code(api, board_headers):
    """PRD §2.8: "a provider identifier that resolves to nothing yields `ERR_PROVIDER_NOT_FOUND`, a course `ERR_COURSE_NOT_FOUND`, a course application `ERR_APPLICATION_NOT_FOUND`, an attorney `ERR_ATTORNEY_NOT_FOUND`, a compliance cycle `ERR_CYCLE_NOT_FOUND`, a credit record `ERR_CREDIT_RECORD_NOT_FOUND`, a reciprocity claim `ERR_RECIPROCITY_CLAIM_NOT_FOUND`, an audit `ERR_AUDIT_NOT_FOUND`, a complaint `ERR_COMPLAINT_NOT_FOUND`, a fee assessment `ERR_FEE_ASSESSMENT_NOT_FOUND` — all HTTP 404. Applies to every endpoint whose path carries an identifier segment."

    Design: Corner/entities/unknown_ids_on_every_single_resource_read_return_their_own_not_found_error
    """
    provider = validate_success(
        api.create_provider(
            create_provider_payload(name="Northgate CLE Group", provider_type="LAW_SCHOOL"),
            board_headers,
        ),
        expected_status=201,
    )

    validate_error(api.get_provider(MISSING_ID, board_headers), "ERR_PROVIDER_NOT_FOUND")
    validate_error(api.get_course(MISSING_ID, board_headers), "ERR_COURSE_NOT_FOUND")
    validate_error(
        api.get_course_application(MISSING_ID, board_headers), "ERR_APPLICATION_NOT_FOUND"
    )
    validate_error(api.get_attorney(MISSING_ID, board_headers), "ERR_ATTORNEY_NOT_FOUND")
    validate_error(api.get_compliance_cycle(MISSING_ID, board_headers), "ERR_CYCLE_NOT_FOUND")
    validate_error(
        api.get_credit_record(MISSING_ID, board_headers), "ERR_CREDIT_RECORD_NOT_FOUND"
    )
    validate_error(
        api.reciprocity_claim_determination(
            MISSING_ID,
            determination_payload("DENY", determination_reason="Probe of an unknown claim id."),
            board_headers,
        ),
        "ERR_RECIPROCITY_CLAIM_NOT_FOUND",
    )
    validate_error(api.get_provider_audit(MISSING_ID, board_headers), "ERR_AUDIT_NOT_FOUND")
    validate_error(api.get_complaint(MISSING_ID, board_headers), "ERR_COMPLAINT_NOT_FOUND")
    validate_error(
        api.get_fee_assessment(MISSING_ID, board_headers), "ERR_FEE_ASSESSMENT_NOT_FOUND"
    )

    reread = validate_success(
        api.get_provider(provider["id"], make_provider_admin_headers(provider["id"])),
        expected_status=200,
    )
    assert reread["id"] == provider["id"], (
        "the ten missing-identifier probes must leave the one real sponsor readable"
    )


def test_attorney_registration_without_a_compliance_group_is_invalid_request(api, board_headers):
    """PRD §3.4: "Board staff register an attorney with a `bar_number` (1 to 20 characters, required, and unique across the whole register — a collision is `ERR_DUPLICATE_BAR_NUMBER`), a `full_name` (1 to 200 characters), an `admission_date`, a `compliance_group`, and a `principal_office_jurisdiction` given as exactly two uppercase letters."
    PRD §3.4: "`compliance_group` is `GROUP_1`, `GROUP_2` or `GROUP_3`, and it selects nothing except the filing-deadline offset described below."
    PRD §2.8: "Every required input present and well formed: enums take a declared value, minute counts are non-negative integers, `origin_credit_hours` is a positive number with at most one decimal place, `period_start` is strictly earlier than `period_end`, `session_date` is a date, `action` names an action the endpoint declares, and `credit_allocations` is a non-empty array whose `category` values are all distinct — otherwise `ERR_INVALID_REQUEST` (422). Applies to every write endpoint."

    Design: Corner/entities/attorney_creation_without_compliance_group_returns_invalid_request
    """
    well_formed = validate_success(
        api.create_attorney(
            create_attorney_payload(
                bar_number="BAR-1001",
                full_name="Priya Raman",
                admission_date="2011-09-01T00:00:00Z",
                compliance_group="GROUP_1",
                principal_office_jurisdiction="ST",
            ),
            board_headers,
        ),
        expected_status=201,
    )
    assert_attorney(well_formed)
    assert well_formed["compliance_group"] == "GROUP_1", (
        "the well-formed sibling registration must keep the supplied compliance group, got "
        f"{well_formed['compliance_group']!r}"
    )

    incomplete = create_attorney_payload(
        bar_number="BAR-1002",
        full_name="Owen Marsh",
        admission_date="2013-09-01T00:00:00Z",
        principal_office_jurisdiction="ST",
    )
    incomplete.pop("compliance_group", None)
    validate_error(api.create_attorney(incomplete, board_headers), "ERR_INVALID_REQUEST")

    retry = validate_success(
        api.create_attorney(
            create_attorney_payload(
                bar_number="BAR-1002",
                full_name="Owen Marsh",
                admission_date="2013-09-01T00:00:00Z",
                compliance_group="GROUP_2",
                principal_office_jurisdiction="ST",
            ),
            board_headers,
        ),
        expected_status=201,
    )
    assert retry["bar_number"] == "BAR-1002", (
        "the rejected registration must have written no attorney row: re-registering BAR-1002 "
        "would otherwise collide as ERR_DUPLICATE_BAR_NUMBER"
    )
    assert retry["compliance_group"] == "GROUP_2"


def test_omitted_annual_fee_defaults_to_the_standard_amount_and_is_billed(api, board_headers):
    """PRD §3.1: "An `annual_fee_cents` figure may be supplied and must be zero or greater; when it is omitted the board's standard annual accreditation fee of 120000 cents — twelve hundred dollars — is used."
    PRD §3.1: "It stamps the same two-year term into `accreditation_term_start` and `accreditation_term_end`, leaves `self_certification_enabled` false, raises the same `PROVIDER_ANNUAL` assessment for `annual_fee_cents`, and re-scores the sponsor under `REVIEWED_WEIGHTING`."
    PRD §2.11: "An assessment carries `amount_cents`, an `assessed_at` instant, a `status` of `ASSESSED`, `PAID`, `WAIVED` or `VOIDED` starting at `ASSESSED`, a `settled_at` instant recorded when it leaves `ASSESSED`, and a `waiver_reason` recorded only when it is waived."
    PRD §2.11: "Attorney-side assessments carry `attorney_id` and, where a specific compliance period produced them, `cycle_id`; provider-side assessments carry `provider_id` instead and leave the attorney fields null."

    Design: Corner/entities/omitted_optional_inputs_take_their_declared_defaults
    """
    payload = create_provider_payload(
        name="Meridian CLE Partners", provider_type="GOVERNMENT"
    )
    payload.pop("annual_fee_cents", None)
    provider = validate_success(api.create_provider(payload, board_headers), expected_status=201)
    assert provider["annual_fee_cents"] == DEFAULT_PROVIDER_ANNUAL_FEE_CENTS, (
        "an omitted annual_fee_cents must take the board's standard 120000-cent fee, got "
        f"{provider['annual_fee_cents']}"
    )
    assert provider["annual_fee_cents"] == 120000

    granted = validate_success(
        api.provider_accreditation_action(
            provider["id"],
            accreditation_action_payload(
                "GRANT_PROBATIONARY", expected_provider_version=provider["version"]
            ),
            board_headers,
        ),
        expected_status=200,
    )
    assert granted["accreditation_status"] == "PROBATIONARY"
    assert granted["self_certification_enabled"] is False
    assert granted["risk_score_variant"] == "REVIEWED_WEIGHTING"

    assessments, meta = validate_paginated(
        api.list_fee_assessments(board_headers, params={"provider_id": provider["id"]})
    )
    assert meta["total_count"] == 1, (
        "the probationary grant raises exactly one PROVIDER_ANNUAL assessment against the "
        f"sponsor, got total_count {meta['total_count']}"
    )
    assessment = assessments[0]
    assert_fee_assessment(assessment)
    assert assessment["fee_type"] == "PROVIDER_ANNUAL", (
        f"the grant fee is a PROVIDER_ANNUAL charge, got {assessment['fee_type']!r}"
    )
    assert assessment["amount_cents"] == 120000, (
        "the assessment must be raised for exactly the sponsor's annual_fee_cents, got "
        f"{assessment['amount_cents']}"
    )
    assert assessment["status"] == "ASSESSED", (
        f"a new assessment starts at ASSESSED, got {assessment['status']!r}"
    )
    assert assessment["provider_id"] == provider["id"], (
        "a provider-side assessment carries provider_id"
    )
    assert assessment["attorney_id"] is None, (
        f"a provider-side assessment leaves attorney_id null, got {assessment['attorney_id']!r}"
    )
    assert assessment["cycle_id"] is None, (
        f"a provider-side assessment leaves cycle_id null, got {assessment['cycle_id']!r}"
    )


def test_cycle_without_election_or_predecessor_takes_its_declared_defaults(api, board_headers):
    """PRD §3.4: "`carryover_election` is either `CARRY_FORWARD` or `WAIVE_CARRYOVER` and defaults to `CARRY_FORWARD`."
    PRD §3.4: "Where it is omitted, both carried-in figures are zero."
    PRD §2.10: "`credit_status` tracks the credit picture and takes `OPEN`, `SATISFIED`, `DEFICIENT` or `CLOSED_COMITY`, starting at `OPEN`."
    PRD §2.10: "`administrative_status` tracks the filing picture and takes `GOOD_STANDING`, `DELINQUENT`, `ADMIN_SUSPENDED` or `REINSTATED`, starting at `GOOD_STANDING`."

    Design: Corner/entities/omitted_optional_inputs_take_their_declared_defaults
    """
    attorney = validate_success(
        api.create_attorney(
            create_attorney_payload(
                bar_number="BAR-1010",
                full_name="Dana Whitlock",
                admission_date="2008-04-01T00:00:00Z",
                compliance_group="GROUP_1",
                principal_office_jurisdiction="ST",
            ),
            board_headers,
        ),
        expected_status=201,
    )

    cycle_payload = create_compliance_cycle_payload(
        period_start="2026-01-01T00:00:00Z", period_end="2028-01-01T00:00:00Z"
    )
    cycle_payload.pop("carryover_election", None)
    cycle_payload.pop("previous_cycle_id", None)
    cycle = validate_success(
        api.create_compliance_cycle(attorney["id"], cycle_payload, board_headers),
        expected_status=201,
    )

    assert cycle["carryover_election"] == "CARRY_FORWARD", (
        "an omitted carryover_election defaults to CARRY_FORWARD, got "
        f"{cycle['carryover_election']!r}"
    )
    assert cycle["previous_cycle_id"] is None, (
        f"no predecessor was named, so previous_cycle_id is null, got {cycle['previous_cycle_id']!r}"
    )
    assert cycle["carryover_in_general_minutes"] == 0, (
        "with no predecessor the carried-in general minutes are zero, got "
        f"{cycle['carryover_in_general_minutes']}"
    )
    assert cycle["carryover_in_ethics_minutes"] == 0, (
        "with no predecessor the carried-in ethics minutes are zero, got "
        f"{cycle['carryover_in_ethics_minutes']}"
    )
    assert cycle["credit_status"] == "OPEN", (
        f"a new period starts at OPEN in the credit dimension, got {cycle['credit_status']!r}"
    )
    assert cycle["administrative_status"] == "GOOD_STANDING", (
        "a new period starts at GOOD_STANDING in the filing dimension, got "
        f"{cycle['administrative_status']!r}"
    )


def test_course_expiry_follows_the_formula_for_its_delivery_format(api, board_headers):
    """PRD §3.2: "`expires_at` is computed at creation from the delivery format."
    PRD §3.2: "For `LIVE_IN_PERSON` and `LIVE_WEBCAST` it is `presented_at` plus the course's own `total_minutes` — a live session's approval covers the session and nothing more."
    PRD §3.2: "For `ON_DEMAND` and `SELF_STUDY` it is `presented_at` plus 36 months, three years of shelf life for recorded material."
    PRD §3.2: "The accepted sum is stored on the course as `credited_minutes_total`, which is therefore always equal to `total_minutes`."
    PRD §3.2: "It is `PROVIDER_ACCREDITED` when `provider_id` is supplied *and* that sponsor's `self_certification_enabled` is true at the moment of creation; in every other case — no sponsor at all, or a sponsor that is not fully accredited — it is `INDIVIDUAL_APPROVAL`."
    PRD §3.2: "A course on the self-certification pathway is presumptively approved: it is created and immediately transitions `PENDING_APPROVAL → APPROVED` in the same request, its sponsor's `courses_self_certified_count` and `courses_total_count` each rise by one, and the sponsor's `risk_score` is recomputed because the denominator behind its findings rate has changed."

    Design: Corner/entities/course_expires_at_is_computed_per_delivery_format_and_never_supplied
    """
    provider = create_accredited_provider(
        name="Lakeshore Legal Education", provider_type="BAR_ASSOCIATION"
    )
    sponsor_headers = make_provider_admin_headers(provider["id"])

    live = validate_success(
        api.create_course(
            create_course_payload(
                title="Deposition Skills Live",
                delivery_format="LIVE_WEBCAST",
                total_minutes=120,
                presented_at="2026-02-02T09:00:00Z",
                attendance_verification_method="ATTENDANCE_CODE",
                credit_allocations=[credit_allocation_entry("GENERAL", 120)],
                provider_id=provider["id"],
            ),
            sponsor_headers,
        ),
        expected_status=201,
    )
    on_demand = validate_success(
        api.create_course(
            create_course_payload(
                title="Recorded Evidence Series",
                delivery_format="ON_DEMAND",
                total_minutes=300,
                presented_at="2026-03-03T09:00:00Z",
                attendance_verification_method="CERTIFICATE",
                credit_allocations=[
                    credit_allocation_entry("GENERAL", 180),
                    credit_allocation_entry("ETHICS", 120),
                ],
                provider_id=provider["id"],
            ),
            sponsor_headers,
        ),
        expected_status=201,
    )
    self_study = validate_success(
        api.create_course(
            create_course_payload(
                title="Written Materials Study",
                delivery_format="SELF_STUDY",
                total_minutes=240,
                presented_at="2026-04-04T09:00:00Z",
                attendance_verification_method="AFFIRMATION_ONLY",
                credit_allocations=[credit_allocation_entry("GENERAL", 240)],
                provider_id=provider["id"],
            ),
            sponsor_headers,
        ),
        expected_status=201,
    )

    assert_same_instant(
        live["expires_at"], "2026-02-02T11:00:00Z", "live webcast expires_at"
    )
    assert_same_instant(
        on_demand["expires_at"], "2029-03-03T09:00:00Z", "on-demand expires_at"
    )
    assert_same_instant(
        self_study["expires_at"], "2029-04-04T09:00:00Z", "self-study expires_at"
    )

    assert on_demand["credited_minutes_total"] == 300, (
        "credited_minutes_total is the accepted allocation sum, expected 300, got "
        f"{on_demand['credited_minutes_total']}"
    )
    assert live["credited_minutes_total"] == 120, (
        "credited_minutes_total is the accepted allocation sum, expected 120, got "
        f"{live['credited_minutes_total']}"
    )

    for course in (live, on_demand, self_study):
        assert course["approval_pathway"] == "PROVIDER_ACCREDITED", (
            "a course sponsored by a self-certifying sponsor takes the PROVIDER_ACCREDITED "
            f"pathway, got {course['approval_pathway']!r} for {course['title']!r}"
        )
        assert course["status"] == "APPROVED", (
            "a self-certified course is presumptively approved in the same request, got "
            f"{course['status']!r} for {course['title']!r}"
        )

    sponsor = validate_success(api.get_provider(provider["id"], sponsor_headers))
    assert sponsor["courses_total_count"] == 3, (
        f"three registrations must leave courses_total_count at 3, got "
        f"{sponsor['courses_total_count']}"
    )
    assert sponsor["courses_self_certified_count"] == 3, (
        "all three took the self-certification pathway, so courses_self_certified_count is 3, "
        f"got {sponsor['courses_self_certified_count']}"
    )


def test_attendance_code_is_minted_only_for_the_code_commitment(api, board_headers):
    """PRD §3.2: "Where and only where the sponsor commits to `ATTENDANCE_CODE`, the system mints a six-character `attendance_code` at creation; for the other three methods `attendance_code` is null."
    PRD §3.2: "For `LIVE_IN_PERSON` and `LIVE_WEBCAST` it is `presented_at` plus the course's own `total_minutes` — a live session's approval covers the session and nothing more."
    PRD §2.5: "Every persisted resource carries a server-minted `id` that is a UUID string with no type prefix, and a `created_at` timestamp recorded at insertion."
    PRD §2.4: "Before the clock is ever set it reads exactly `2026-08-01T00:00:00Z`."
    PRD §2.4: "All timestamps on the wire are ISO 8601 UTC with three fractional digits, for example `2026-08-01T00:00:00.000Z`."

    Design: Corner/entities/course_status_and_attendance_code_are_system_written_so_client_input_is_input_ignored
    """
    provider = create_accredited_provider(
        name="Riverbend Bar Center", provider_type="BAR_ASSOCIATION"
    )
    sponsor_headers = make_provider_admin_headers(provider["id"])

    coded = validate_success(
        api.create_course(
            create_course_payload(
                title="Coded Attendance Seminar",
                delivery_format="LIVE_WEBCAST",
                total_minutes=90,
                presented_at="2026-05-05T09:00:00Z",
                attendance_verification_method="ATTENDANCE_CODE",
                credit_allocations=[credit_allocation_entry("GENERAL", 90)],
                provider_id=provider["id"],
            ),
            sponsor_headers,
        ),
        expected_status=201,
    )
    plain = validate_success(
        api.create_course(
            create_course_payload(
                title="Affirmation Only Study",
                delivery_format="SELF_STUDY",
                total_minutes=60,
                presented_at="2026-05-05T09:00:00Z",
                attendance_verification_method="AFFIRMATION_ONLY",
                credit_allocations=[credit_allocation_entry("GENERAL", 60)],
                provider_id=provider["id"],
            ),
            sponsor_headers,
        ),
        expected_status=201,
    )

    assert_attendance_code_shape(coded)
    assert plain["attendance_code"] is None, (
        "a course verified by affirmation alone carries no minted code, got "
        f"{plain['attendance_code']!r}"
    )
    assert coded["status"] == "APPROVED", (
        f"the sponsor self-certifies, so the course is APPROVED, got {coded['status']!r}"
    )
    assert_no_uuid_prefix(coded["id"])
    assert_same_instant(
        coded["expires_at"], "2026-05-05T10:30:00Z", "coded course expires_at"
    )
    assert_utc_millisecond_timestamp(coded["created_at"])
    assert_same_instant(coded["created_at"], CLOCK_DEFAULT_UTC, "coded course created_at")


def test_an_unknown_provider_type_is_an_invalid_request(api, board_headers):
    """PRD §3.1: "A sponsor enters the register when board staff file an accreditation application on its behalf, supplying the sponsor's legal `name` (between 1 and 200 characters, required) and its `provider_type`, which is one of `BAR_ASSOCIATION`, `LAW_SCHOOL`, `GOVERNMENT`, `COMMERCIAL` or `LAW_FIRM`."
    PRD §2.8: "Every required input present and well formed: enums take a declared value, minute counts are non-negative integers, `origin_credit_hours` is a positive number with at most one decimal place, `period_start` is strictly earlier than `period_end`, `session_date` is a date, `action` names an action the endpoint declares, and `credit_allocations` is a non-empty array whose `category` values are all distinct — otherwise `ERR_INVALID_REQUEST` (422). Applies to every write endpoint."

    Design: Corner/entities/an_unknown_provider_type_and_an_inverted_cycle_period_both_return_invalid_request
    """
    validate_error(
        api.create_provider(
            create_provider_payload(name="Unclassified Trainer", provider_type="NONPROFIT"),
            board_headers,
        ),
        "ERR_INVALID_REQUEST",
    )

    accepted = validate_success(
        api.create_provider(
            create_provider_payload(name="Unclassified Trainer", provider_type="COMMERCIAL"),
            board_headers,
        ),
        expected_status=201,
    )
    assert accepted["provider_type"] == "COMMERCIAL", (
        "only a declared provider_type may be registered, and it must be stored as supplied"
    )


def test_a_cycle_period_must_be_strictly_ordered(api, board_headers):
    """PRD §3.4: "The period is the half-open interval running from `period_start` inclusive to `period_end` exclusive, and `period_start` must be strictly earlier than `period_end`."
    PRD §2.8: "Every required input present and well formed: enums take a declared value, minute counts are non-negative integers, `origin_credit_hours` is a positive number with at most one decimal place, `period_start` is strictly earlier than `period_end`, `session_date` is a date, `action` names an action the endpoint declares, and `credit_allocations` is a non-empty array whose `category` values are all distinct — otherwise `ERR_INVALID_REQUEST` (422). Applies to every write endpoint."

    Design: Corner/entities/an_unknown_provider_type_and_an_inverted_cycle_period_both_return_invalid_request
    """
    attorney = validate_success(
        api.create_attorney(
            create_attorney_payload(
                bar_number="BAR-1020",
                full_name="Karim Aziz",
                admission_date="2010-01-01T00:00:00Z",
                compliance_group="GROUP_2",
                principal_office_jurisdiction="ST",
            ),
            board_headers,
        ),
        expected_status=201,
    )

    validate_error(
        api.create_compliance_cycle(
            attorney["id"],
            create_compliance_cycle_payload(
                period_start="2028-01-01T00:00:00Z", period_end="2026-01-01T00:00:00Z"
            ),
            board_headers,
        ),
        "ERR_INVALID_REQUEST",
    )
    validate_error(
        api.create_compliance_cycle(
            attorney["id"],
            create_compliance_cycle_payload(
                period_start="2026-01-01T00:00:00Z", period_end="2026-01-01T00:00:00Z"
            ),
            board_headers,
        ),
        "ERR_INVALID_REQUEST",
    )

    cycles, meta = validate_paginated(
        api.list_compliance_cycles(board_headers, params={"attorney_id": attorney["id"]})
    )
    assert meta["total_count"] == 0, (
        "neither the inverted nor the zero-length period may be stored, got total_count "
        f"{meta['total_count']}"
    )
    assert cycles == [], f"no period may exist for this attorney, got {cycles}"


def test_a_course_naming_an_unknown_sponsor_returns_provider_not_found(api, board_headers):
    """PRD §2.8: "**Body foreign-key existence**, validated in the order the fields appear in the endpoint's input: `provider_id`, `course_id`, `attorney_id`, `cycle_id`, `attendance_report_id`, `reciprocity_claim_id`, `affirmation_id`, `previous_cycle_id`, `originating_complaint_id`."
    PRD §2.8: "Each unresolved reference yields its own not-found code from the list above (HTTP 404). This step applies to course creation, credit-record creation, roster filing, reciprocity-claim filing, audit opening, complaint filing, compliance-cycle creation and reciprocity determination."
    PRD §2.8: "a provider identifier that resolves to nothing yields `ERR_PROVIDER_NOT_FOUND`, a course `ERR_COURSE_NOT_FOUND`, a course application `ERR_APPLICATION_NOT_FOUND`, an attorney `ERR_ATTORNEY_NOT_FOUND`, a compliance cycle `ERR_CYCLE_NOT_FOUND`, a credit record `ERR_CREDIT_RECORD_NOT_FOUND`, a reciprocity claim `ERR_RECIPROCITY_CLAIM_NOT_FOUND`, an audit `ERR_AUDIT_NOT_FOUND`, a complaint `ERR_COMPLAINT_NOT_FOUND`, a fee assessment `ERR_FEE_ASSESSMENT_NOT_FOUND` — all HTTP 404. Applies to every endpoint whose path carries an identifier segment."

    Design: Corner/entities/a_course_naming_an_unknown_provider_id_returns_provider_not_found
    """
    provider = create_accredited_provider(
        name="Summit CLE Alliance", provider_type="BAR_ASSOCIATION"
    )

    validate_error(
        api.create_course(
            create_course_payload(
                title="Orphan Course",
                delivery_format="LIVE_WEBCAST",
                total_minutes=90,
                presented_at="2026-06-06T09:00:00Z",
                attendance_verification_method="ATTENDANCE_CODE",
                credit_allocations=[credit_allocation_entry("GENERAL", 90)],
                provider_id=MISSING_ID,
            ),
            board_headers,
        ),
        "ERR_PROVIDER_NOT_FOUND",
    )

    courses, meta = validate_paginated(
        api.list_courses(board_headers, params={"provider_id": provider["id"]})
    )
    assert meta["total_count"] == 0, (
        "the rejected registration must have written no course, got total_count "
        f"{meta['total_count']}"
    )
    assert [row["title"] for row in courses] == [], (
        f"no course row may survive the unresolved sponsor reference, got {courses}"
    )

    sponsor = validate_success(
        api.get_provider(provider["id"], make_provider_admin_headers(provider["id"]))
    )
    assert sponsor["courses_total_count"] == 0, (
        "a rejected registration bumps no sponsor counter, got courses_total_count "
        f"{sponsor['courses_total_count']}"
    )


def test_immutable_rows_carry_no_version_and_no_updated_at(api, board_headers):
    """PRD §2.5: "Three resources are exceptions and carry only `id` and `created_at`: a credit allocation, an affirmation and a reporting sweep."
    PRD §2.5: "All three are immutable once written — an allocation is fixed by the course that created it, an affirmation is a sworn statement that is never edited, and a sweep is a historical run record — so for these three `updated_at` and `version` are absent from the payload entirely, not merely null."
    PRD §2.5: "Most resources also carry an `updated_at` timestamp, refreshed on every mutation of that row, and an integer `version` that starts at 1 on creation and increases by exactly 1 on every mutation of that row — including mutations the row did not ask for, such as a counter bump driven by a cascade from another entity."
    PRD §3.2: "Each element becomes an immutable allocation row bound to the new course by its `course_id`, and those rows are never editable afterwards."

    Design: Corner/entities/common_fields_false_entities_expose_no_version_or_updated_at
    """
    provider = create_accredited_provider(name="Cedar Hill CLE", provider_type="LAW_SCHOOL")
    course = create_self_certified_course(
        provider,
        title="Ethics And Technology Update",
        delivery_format="LIVE_WEBCAST",
        total_minutes=180,
        presented_at="2026-02-02T09:00:00Z",
        attendance_verification_method="ATTENDANCE_CODE",
        credit_allocations=[
            credit_allocation_entry("ETHICS", 120),
            credit_allocation_entry("TECHNOLOGY", 60),
        ],
    )
    attorney = validate_success(
        api.create_attorney(
            create_attorney_payload(
                bar_number="BAR-1030",
                full_name="Lena Osei",
                admission_date="2009-06-01T00:00:00Z",
                compliance_group="GROUP_1",
                principal_office_jurisdiction="ST",
            ),
            board_headers,
        ),
        expected_status=201,
    )
    cycle = validate_success(
        api.create_compliance_cycle(
            attorney["id"],
            create_compliance_cycle_payload(
                period_start="2026-01-01T00:00:00Z", period_end="2028-01-01T00:00:00Z"
            ),
            board_headers,
        ),
        expected_status=201,
    )
    affirmation = fixtures.file_final_affirmation(
        cycle["id"],
        attorney["id"],
        statement="I affirm the credits reported for this compliance period are accurate.",
    )

    allocations, allocation_meta = validate_paginated(
        api.list_course_credit_allocations(course["id"], board_headers)
    )
    assert allocation_meta["total_count"] == 2, (
        "the course was filed with two allocation rows, got total_count "
        f"{allocation_meta['total_count']}"
    )
    for allocation in allocations:
        assert_credit_allocation(allocation)
        assert allocation["course_id"] == course["id"], (
            "an allocation row is bound to the course that created it, got "
            f"{allocation['course_id']!r}"
        )
        assert "version" not in allocation, (
            f"an allocation carries no version key at all, got {sorted(allocation)}"
        )
        assert "updated_at" not in allocation, (
            f"an allocation carries no updated_at key at all, got {sorted(allocation)}"
        )
    assert {row["category"] for row in allocations} == {"ETHICS", "TECHNOLOGY"}

    affirmations, affirmation_meta = validate_paginated(
        api.list_affirmations(cycle["id"], board_headers)
    )
    assert affirmation_meta["total_count"] == 1, (
        f"one affirmation was filed, got total_count {affirmation_meta['total_count']}"
    )
    assert affirmations[0]["id"] == affirmation["id"]
    assert_append_only_identity(affirmations[0])
    assert "version" not in affirmations[0], (
        f"an affirmation carries no version key at all, got {sorted(affirmations[0])}"
    )
    assert "updated_at" not in affirmations[0], (
        f"an affirmation carries no updated_at key at all, got {sorted(affirmations[0])}"
    )

    course_before_sweep = validate_success(
        api.get_course(course["id"], make_provider_admin_headers(provider["id"]))
    )
    assert type(course_before_sweep["version"]) is int, (
        "a course is not one of the three exceptions and does carry version, got "
        f"{course_before_sweep.get('version')!r}"
    )
    assert "updated_at" in course_before_sweep, (
        "a course is not one of the three exceptions and does carry updated_at"
    )
    cycle_read = validate_success(api.get_compliance_cycle(cycle["id"], board_headers))
    assert type(cycle_read["version"]) is int and "updated_at" in cycle_read, (
        "a compliance cycle carries both version and updated_at"
    )

    sweep = fixtures.run_sweep()
    assert_reporting_sweep(sweep)
    assert "version" not in sweep, (
        f"a sweep carries no version key at all, got {sorted(sweep)}"
    )
    assert "updated_at" not in sweep, (
        f"a sweep carries no updated_at key at all, got {sorted(sweep)}"
    )


def test_credit_record_body_references_report_their_own_not_found_codes(api, board_headers):
    """PRD §2.8: "**Body foreign-key existence**, validated in the order the fields appear in the endpoint's input: `provider_id`, `course_id`, `attorney_id`, `cycle_id`, `attendance_report_id`, `reciprocity_claim_id`, `affirmation_id`, `previous_cycle_id`, `originating_complaint_id`."
    PRD §2.8: "Each unresolved reference yields its own not-found code from the list above (HTTP 404). This step applies to course creation, credit-record creation, roster filing, reciprocity-claim filing, audit opening, complaint filing, compliance-cycle creation and reciprocity determination."
    PRD §2.8: "a provider identifier that resolves to nothing yields `ERR_PROVIDER_NOT_FOUND`, a course `ERR_COURSE_NOT_FOUND`, a course application `ERR_APPLICATION_NOT_FOUND`, an attorney `ERR_ATTORNEY_NOT_FOUND`, a compliance cycle `ERR_CYCLE_NOT_FOUND`, a credit record `ERR_CREDIT_RECORD_NOT_FOUND`, a reciprocity claim `ERR_RECIPROCITY_CLAIM_NOT_FOUND`, an audit `ERR_AUDIT_NOT_FOUND`, a complaint `ERR_COMPLAINT_NOT_FOUND`, a fee assessment `ERR_FEE_ASSESSMENT_NOT_FOUND` — all HTTP 404. Applies to every endpoint whose path carries an identifier segment."

    Design: Corner/entities/credit_record_body_foreign_keys_are_validated_in_declared_order_not_found
    """
    provider = create_accredited_provider(
        name="Fairhaven Bar Institute", provider_type="GOVERNMENT"
    )
    course = create_self_certified_course(
        provider,
        title="Records Retention Practicum",
        delivery_format="ON_DEMAND",
        total_minutes=60,
        presented_at="2026-02-02T09:00:00Z",
        attendance_verification_method="CERTIFICATE",
        credit_allocations=[credit_allocation_entry("GENERAL", 60)],
    )
    attorney = validate_success(
        api.create_attorney(
            create_attorney_payload(
                bar_number="BAR-1040",
                full_name="Tomas Ferreira",
                admission_date="2007-02-01T00:00:00Z",
                compliance_group="GROUP_1",
                principal_office_jurisdiction="ST",
            ),
            board_headers,
        ),
        expected_status=201,
    )
    cycle = validate_success(
        api.create_compliance_cycle(
            attorney["id"],
            create_compliance_cycle_payload(
                period_start="2026-01-01T00:00:00Z", period_end="2028-01-01T00:00:00Z"
            ),
            board_headers,
        ),
        expected_status=201,
    )

    validate_error(
        api.create_credit_record(
            create_credit_record_payload(
                MISSING_ID,
                course["id"],
                verification_method="CERTIFICATE",
                attended_minutes=60,
                completion_date="2026-03-03T12:00:00Z",
                certificate_reference="CERT-9001",
            ),
            make_attorney_headers(MISSING_ID),
        ),
        "ERR_ATTORNEY_NOT_FOUND",
    )

    validate_error(
        api.create_credit_record(
            create_credit_record_payload(
                attorney["id"],
                MISSING_ID,
                verification_method="CERTIFICATE",
                attended_minutes=60,
                completion_date="2026-03-03T12:00:00Z",
                certificate_reference="CERT-9001",
            ),
            make_attorney_headers(attorney["id"]),
        ),
        "ERR_COURSE_NOT_FOUND",
    )

    records, meta = validate_paginated(
        api.list_credit_records(board_headers, params={"cycle_id": cycle["id"]})
    )
    assert meta["total_count"] == 0, (
        "neither rejected claim may be stored against the period, got total_count "
        f"{meta['total_count']}"
    )
    assert records == [], f"the period must hold no credit record, got {records}"
