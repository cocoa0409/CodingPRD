"""
Entity surfaces: creation echoes, read-back shapes, listing windows and intake refusals.

Every resource in this system is minted by the server, so a creation response is the
first place its declared defaults, its seeded status pair and its still-empty derived
fields become observable. These cases walk that surface for loan files, management
companies, appraisals, comparable sales, recorded communications, rule-check rows and
panel memberships, and pin the refusals that guard it: a well-formed identifier that
names nothing, a missing required field, and an out-of-range enum value.
"""

from test_helpers import (
    CHIEF_APPRAISER_HEADERS,
    DESK_REVIEWER_HEADERS,
    DESK_USER_1,
    LOAN_OFFICER_HEADERS,
    assert_created_at_ascending,
    assert_fields_present,
    assert_instant,
    assert_pagination_meta,
    factories as f,
    fixtures as fx,
    is_valid_uuid,
    make_amc_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

# A well-formed version 4 identifier that names no resource of any type.
UNKNOWN_ID = "00000000-0000-4000-8000-000000000000"

AUTHOR = {
    "full_name": "Alice Author",
    "license_state": "CA",
}


def _author(license_number):
    return dict(AUTHOR, license_number=license_number)


def test_a_registered_loan_file_echoes_its_inputs_and_seeds_its_status_pair(api):
    """Registration returns the submitted terms plus the seeded collateral fields.

    The five loan terms come back exactly as supplied, the omitted contract price
    stays null because a refinance may not carry one, and the two status dimensions
    plus the version are seeded by the server. Every derived collateral figure is
    still absent, since no value is of record yet, and the creation stamp is read
    from the logical clock rather than from the host.

    PRD: "A freshly registered loan file is born with `underwriting_status`
    `SUBMITTED`, `collateral_status` `PENDING_APPRAISAL`, and `version` 1. Its derived
    collateral fields all start empty: `value_of_record_appraisal_id`,
    `current_appraised_value_cents`, `effective_value_cents`, `ltv_bps`, and
    `decision_impact` are all null until a value becomes of record, and
    `rov_request_count` starts at 0 and thereafter simply counts the reconsideration
    requests filed against this loan."

    Design: Corner/entities/creation_loan_file_echoes_inputs_and_seeds_computed_fields
    """
    response = api.create_loan_file(
        f.loan_file_payload(
            loan_number="LN-2747-C001", borrower_display_name="Ada Borrower",
        ),
        LOAN_OFFICER_HEADERS,
    )
    data = validate_success(response, 201)
    assert response.json()["response_type"] == "object"

    assert is_valid_uuid(data["id"])
    assert data["loan_number"] == "LN-2747-C001"
    assert data["loan_purpose"] == "REFINANCE"
    assert data["market_type"] == "SUBURBAN"
    assert data["risk_tier"] == "STANDARD"
    assert data["loan_amount_cents"] == 30000000
    assert data["borrower_display_name"] == "Ada Borrower"
    assert data["contract_price_cents"] is None

    assert data["underwriting_status"] == "SUBMITTED"
    assert data["collateral_status"] == "PENDING_APPRAISAL"
    assert data["value_of_record_appraisal_id"] is None
    assert data["current_appraised_value_cents"] is None
    assert data["effective_value_cents"] is None
    assert data["ltv_bps"] is None
    assert data["decision_impact"] is None
    assert data["rov_request_count"] == 0
    assert data["version"] == 1
    assert_instant(data["created_at"], "2026-08-01T00:00:00Z", "created_at")


def test_a_delivered_report_reads_back_with_every_derived_field_empty(api):
    """The read-back carries the stored intake fields and the untouched roll-ups.

    Intake alone runs neither the receipt battery nor the bias screen, so the report
    sits in RECEIVED and NOT_SCREENED with its scores null and its counters zero, and
    the loan file it was delivered against is still waiting on an appraisal rather
    than under review.

    PRD: "A successful delivery is created with `version` 1, with `review_status`
    `RECEIVED` and `bias_screen_status` `NOT_SCREENED`, and with every derived field
    empty: `completeness_score_bps`, `indicated_value_cents`,
    `variance_vs_reported_bps`, `bias_risk_index`, `current_value_cents`, and
    `quarantine_return_status` are all null, while `eligible_comp_count`,
    `closed_comp_count`, `max_gross_adjustment_bps`, `max_net_adjustment_bps`,
    `rule_check_fail_count`, and `rule_check_warn_count` all start at 0."

    Design: Corner/entities/retrieval_appraisal_returns_stored_and_computed_fields
    """
    env = fx.panel_and_loan(
        api,
        amc={"name": "Corner AMC One"},
        appraiser=_author("CA-AL-C002"),
        loan={"loan_number": "LN-2747-C002", "borrower_display_name": "Ben Borrower"},
    )
    created = fx.deliver_appraisal(
        api, env["loan"]["id"], env["appraiser"]["id"], env["amc"]["id"],
    )

    response = api.get_appraisal(created["id"], DESK_REVIEWER_HEADERS)
    data = validate_success(response, 200)
    assert response.json()["response_type"] == "object"

    assert data["id"] == created["id"]
    assert data["loan_file_id"] == env["loan"]["id"]
    assert data["appraiser_id"] == env["appraiser"]["id"]
    assert data["amc_id"] == env["amc"]["id"]
    assert data["report_form_type"] == "FORM_1004"
    assert data["reported_value_cents"] == 40000000
    assert data["exhibit_count"] == 7

    assert data["review_status"] == "RECEIVED"
    assert data["bias_screen_status"] == "NOT_SCREENED"
    assert data["completeness_score_bps"] is None
    assert data["indicated_value_cents"] is None
    assert data["variance_vs_reported_bps"] is None
    assert data["bias_risk_index"] is None
    assert data["current_value_cents"] is None
    assert data["quarantine_return_status"] is None
    assert data["eligible_comp_count"] == 0
    assert data["closed_comp_count"] == 0
    assert data["max_gross_adjustment_bps"] == 0
    assert data["max_net_adjustment_bps"] == 0
    assert data["rule_check_fail_count"] == 0
    assert data["rule_check_warn_count"] == 0
    assert data["version"] == 1

    assert fx.read_loan_file(api, env["loan"]["id"])["collateral_status"] == (
        "PENDING_APPRAISAL"
    )


# Three closed sales filed in this order, so the listing's ascending creation order
# is observable by street address alone.
ALDER_GRID = [
    {
        "street_address": "1 Alder Street",
        "sale_price_cents": 39000000,
        "gross_adjustment_cents": 390000,
        "net_adjustment_cents": 390000,
        "distance_miles": 1.0,
        "sale_date": "2026-05-01T00:00:00Z",
    },
    {
        "street_address": "2 Alder Street",
        "sale_price_cents": 40000000,
        "gross_adjustment_cents": 400000,
        "net_adjustment_cents": 0,
        "distance_miles": 1.5,
        "sale_date": "2026-06-01T00:00:00Z",
    },
    {
        "street_address": "3 Alder Street",
        "sale_price_cents": 41000000,
        "gross_adjustment_cents": 410000,
        "net_adjustment_cents": -410000,
        "distance_miles": 2.0,
        "sale_date": "2026-06-15T00:00:00Z",
    },
]


def _three_comparable_grid(api, license_number, amc_name, loan_number, borrower):
    """A delivered report carrying exactly three comparable rows."""
    return fx.delivered_report(
        api,
        amc={"name": amc_name},
        appraiser=_author(license_number),
        loan={"loan_number": loan_number, "borrower_display_name": borrower},
        comparables=ALDER_GRID,
    )


def test_the_comparable_listing_reports_the_window_it_actually_applied(api):
    """Two pages of two over three rows, with the tallies describing the whole set.

    The first page carries two of the three rows and still reports a total of three,
    because the count is taken before the window is applied, and it flags that rows
    remain. The second page carries the single remaining row and clears the flag.

    PRD: "For list responses the `meta` object carries `limit` (the effective page size
    actually applied), `offset` (the effective offset actually applied), `total_count`
    (the number of rows matching the filters before the page window is applied), and
    `has_more` (true when rows remain beyond the current window)."

    Design: Corner/entities/listing_comparables_paginates_with_total_count_and_has_more
    """
    env = _three_comparable_grid(
        api, "CA-AL-C003", "Corner AMC Two", "LN-2747-C003", "Cleo Borrower",
    )
    appraisal_id = env["appraisal"]["id"]

    response = api.list_comparables(
        appraisal_id, DESK_REVIEWER_HEADERS, {"limit": 2, "offset": 0},
    )
    rows, meta = validate_paginated(response)
    assert response.json()["response_type"] == "array"
    assert_pagination_meta(meta, total_count=3, limit=2, offset=0, has_more=True)
    assert len(rows) == 2
    assert rows[0]["id"] == env["comparables"][0]["id"]
    assert [row["street_address"] for row in rows] == [
        "1 Alder Street", "2 Alder Street",
    ]

    rows, meta = validate_paginated(
        api.list_comparables(
            appraisal_id, DESK_REVIEWER_HEADERS, {"limit": 2, "offset": 2},
        )
    )
    assert_pagination_meta(meta, total_count=3, limit=2, offset=2, has_more=False)
    assert len(rows) == 1
    assert rows[0]["street_address"] == "3 Alder Street"


def test_omitting_the_page_window_falls_back_to_the_declared_defaults(api):
    """With no query parameters the listing applies a limit of ten from offset zero.

    All three rows fit inside the default window, so the response reports the defaults
    it applied rather than echoing nothing, and the rows arrive oldest first.

    PRD: "`limit` defaults to 10 when omitted, must be an integer, and must fall in the
    inclusive range from a minimum of 1 to a maximum of 100."

    PRD: "List results are always returned in ascending `created_at` order — oldest
    first — and where two rows share a `created_at` value the ordering remains
    `created_at` ascending as the only sanctioned deterministic fallback; resource `id`
    values never participate in ordering, ranking, tie-breaking, or conflict resolution
    anywhere in this system."

    Design: Corner/entities/listing_comparables_paginates_with_total_count_and_has_more
    """
    env = _three_comparable_grid(
        api, "CA-AL-C004", "Corner AMC Two B", "LN-2747-C004", "Cleo Borrower",
    )

    rows, meta = validate_paginated(
        api.list_comparables(env["appraisal"]["id"], DESK_REVIEWER_HEADERS)
    )
    assert_pagination_meta(meta, total_count=3, limit=10, offset=0, has_more=False)
    assert len(rows) == 3
    assert_created_at_ascending(rows)
    assert [row["street_address"] for row in rows] == [
        "1 Alder Street", "2 Alder Street", "3 Alder Street",
    ]


def test_reading_an_appraisal_that_does_not_exist_is_a_not_found(api):
    """A well-formed identifier naming no report answers with the appraisal's own code.

    The path segment is resolved before anything else, and because it names nothing the
    refusal is the appraisal type's own not-found code rather than a generic one.

    PRD: "Every resource named in a path position exists, checked left to right —
    otherwise that type's own not-found code (404)."

    Design: Corner/entities/not_found_get_appraisal_with_unknown_id_returns_404
    """
    response = api.get_appraisal(UNKNOWN_ID, DESK_REVIEWER_HEADERS)
    validate_error(response, "ERR_APPRAISAL_NOT_FOUND", 404)

    body = response.json()
    assert body["response_type"] == "error"
    assert isinstance(body["data"]["message"], str)
    assert body["data"]["message"] != ""


def test_a_delivery_without_its_narrative_text_is_rejected_as_malformed(api):
    """The narrative the bias screen will read is required, so its absence is a 400.

    Nothing is persisted by the refusal: no report exists against the loan file
    afterwards, and the loan file's own version is untouched, because the delivery's
    version bump only happens on a body that got as far as being accepted.

    PRD: "The body is well shaped: required fields present, enum values in range,
    integers non-negative where declared, timestamps ISO 8601 with a `Z` suffix.
    Unknown fields are silently ignored rather than rejected. A malformed body yields
    `ERR_INVALID_REQUEST` (400)."

    Design: Corner/entities/required_fields_appraisal_intake_missing_narrative_text_rejected
    """
    env = fx.panel_and_loan(
        api,
        amc={"name": "Corner AMC Three"},
        appraiser=_author("CA-AL-C005"),
        loan={"loan_number": "LN-2747-C005", "borrower_display_name": "Dev Borrower"},
    )
    loan_version = env["loan"]["version"]

    validate_error(
        api.create_appraisal(
            f.appraisal_payload(
                env["loan"]["id"], env["appraiser"]["id"], env["amc"]["id"],
                loan_version, drop=("narrative_text",),
            ),
            make_amc_headers(env["amc"]["id"]),
        ),
        "ERR_INVALID_REQUEST", 400,
    )

    _, meta = validate_paginated(
        api.list_appraisals(DESK_REVIEWER_HEADERS, {"loan_file_id": env["loan"]["id"]})
    )
    assert meta["total_count"] == 0
    assert fx.read_loan_file(api, env["loan"]["id"])["version"] == loan_version


def test_a_management_company_created_bare_takes_every_declared_default(api):
    """A company registered with only a name carries the four configured defaults.

    None of the operating parameters is supplied, so the turnaround allowance, the
    overlap capacity and the spend ceiling all fall back to their declared values, the
    standing opens ACTIVE, and the three ledger counters and the version start where
    the specification puts them.

    PRD: "`sla_response_hours` is the number of hours the company has to route an
    appraiser's response to a dispute and defaults to 72, and must be at least 1.
    `concurrent_dispute_capacity` is the number of mutually overlapping dispute review
    slots the company can host and defaults to 2, and must be at least 1.
    `escalation_budget_cents` is the ceiling on escalation spend chargeable to the
    company and defaults to 500000 cents — five thousand dollars — and must be zero or
    greater."

    PRD: "The three ledger counters start at zero: `ytd_escalation_spend_cents`,
    `sla_breach_count`, and `open_dispute_count`, and the company's `version` starts at
    1."

    Design: Corner/entities/defaults_amc_created_without_optional_config_uses_declared_defaults
    """
    data = validate_success(
        api.create_amc(
            f.amc_payload(name="Default Config AMC"), CHIEF_APPRAISER_HEADERS,
        ),
        201,
    )

    assert data["name"] == "Default Config AMC"
    assert data["sla_response_hours"] == 72
    assert data["concurrent_dispute_capacity"] == 2
    assert data["escalation_budget_cents"] == 500000
    assert data["panel_status"] == "ACTIVE"
    assert data["ytd_escalation_spend_cents"] == 0
    assert data["sla_breach_count"] == 0
    assert data["open_dispute_count"] == 0
    assert data["version"] == 1


def test_comparable_adjustment_metrics_are_derived_from_the_filed_figures(api):
    """A downward-adjusted row still reports a positive net ratio.

    Forty-one million cents of sale price adjusted down by 410000 gives an adjusted
    price of 40590000, and both ratios come to 100 basis points because the net ratio
    is taken from the magnitude of the adjustment rather than its sign. The row joins
    the grid by default and moves both parent counters, while the completeness score
    stays absent because filing a comparable does not run the receipt battery.

    PRD: "The `adjusted_price_cents` is the sale price plus the signed net adjustment.
    The `gross_adjustment_bps` is the gross adjustment expressed as a share of the sale
    price in basis points: multiply the gross adjustment in cents by 10000, divide by
    the sale price in cents, and round half-up to a whole number of basis points. The
    `net_adjustment_bps` is computed the same way but from the **absolute value** of the
    net adjustment, so a comparable adjusted downward by the same magnitude as one
    adjusted upward carries the same net-adjustment ratio."

    Design: Corner/entities/computed_fields_comparable_adjustment_metrics_derived_not_accepted
    """
    env = fx.panel_and_loan(
        api,
        amc={"name": "Corner AMC Four"},
        appraiser=_author("CA-AL-C007"),
        loan={"loan_number": "LN-2747-C007", "borrower_display_name": "Eve Borrower"},
    )
    appraisal = fx.deliver_appraisal(
        api, env["loan"]["id"], env["appraiser"]["id"], env["amc"]["id"],
    )

    data = validate_success(
        api.create_comparable(
            appraisal["id"],
            f.comparable_payload(
                "9 Hazel Street", sale_price_cents=41000000,
                gross_adjustment_cents=410000, net_adjustment_cents=-410000,
                distance_miles=2.0, sale_date="2026-06-15T00:00:00Z",
            ),
            make_amc_headers(env["amc"]["id"]),
        ),
        201,
    )

    assert data["appraisal_id"] == appraisal["id"]
    assert data["adjusted_price_cents"] == 40590000
    assert data["gross_adjustment_bps"] == 100
    assert data["net_adjustment_bps"] == 100
    assert data["included_in_grid"] is True

    parent = fx.read_appraisal(api, appraisal["id"])
    assert parent["eligible_comp_count"] == 1
    assert parent["closed_comp_count"] == 1
    assert parent["completeness_score_bps"] is None


def test_a_recorded_communication_takes_its_parent_sender_and_stamp_from_the_server(api):
    """The message body is the caller's; everything around it is the server's.

    The parent report comes from the path, the sending role and identity come from the
    request headers, and the sending instant comes from the logical clock, which has
    been moved to a named August morning. The record is an append-only event, so it
    carries no version and no update stamp at all.

    PRD: "Any of `AppraisalDeskReviewer`, `ChiefAppraiser`, `AMCCoordinator`,
    `LoanOfficer`, or `Borrower` may record a message against an appraisal, supplying
    the `recipient`, the `intent`, and the `body`; the server stamps `sent_at` from the
    logical clock and records `sender_role` and `sender_user_id` from the request
    headers. Communication records are append-only events carrying only `id` and
    `created_at`, with no `updated_at` and no `version`."

    Design: Corner/entities/system_fields_comparable_parent_and_timestamps_are_server_owned
    """
    env = fx.panel_and_loan(
        api,
        amc={"name": "Corner AMC Five"},
        appraiser=_author("CA-AL-C008"),
        loan={"loan_number": "LN-2747-C008", "borrower_display_name": "Fritz Borrower"},
    )
    appraisal = fx.deliver_appraisal(
        api, env["loan"]["id"], env["appraiser"]["id"], env["amc"]["id"],
    )
    fx.set_clock(api, "2026-08-03T08:15:00Z")

    data = validate_success(
        api.create_communication(
            appraisal["id"],
            f.communication_payload(
                "APPRAISER", "REPORT_CLARIFICATION",
                "Please confirm the gross living area source for the subject.",
            ),
            DESK_REVIEWER_HEADERS,
        ),
        201,
    )

    assert data["appraisal_id"] == appraisal["id"]
    assert data["recipient"] == "APPRAISER"
    assert data["intent"] == "REPORT_CLARIFICATION"
    assert data["sender_role"] == "AppraisalDeskReviewer"
    assert data["sender_user_id"] == DESK_USER_1
    assert_instant(data["sent_at"], "2026-08-03T08:15:00Z", "sent_at")
    assert_instant(data["created_at"], "2026-08-03T08:15:00Z", "created_at")
    assert is_valid_uuid(data["id"])
    assert "version" not in data
    assert "updated_at" not in data


def test_an_out_of_range_report_form_type_is_refused_before_anything_lands(api):
    """A form type outside the three declared values is a malformed body.

    The delivery names a form the specification does not define, so it is rejected on
    body shape and no report exists against the loan file afterwards. A negative
    exhibit count on the same endpoint is refused the same way, since the field is
    declared as zero or more.

    PRD: "The report itself is described by a `report_form_type` of `FORM_1004`,
    `FORM_1073`, or `FORM_2055`; an `effective_date` of value that must be at or before
    the logical clock at the moment of intake; a `reported_value_cents` greater than
    zero, which is the appraiser's original value opinion; a `sections_present` array
    listing which report sections the delivery contains; an `exhibit_count` of zero or
    more photos, sketches, and maps; the free-text `narrative_text` that the bias screen
    will later read; and a `subject_census_tract_band` of `A`, `B`, `C`, or `D`
    describing the demographic band of the subject property's census tract, used only
    for comparable-selection skew screening."

    PRD: "A malformed body yields `ERR_INVALID_REQUEST` (400)."

    Design: Corner/entities/type_constraints_invalid_report_form_type_enum_rejected
    """
    env = fx.panel_and_loan(
        api,
        amc={"name": "Corner AMC Six"},
        appraiser=_author("CA-AL-C009"),
        loan={"loan_number": "LN-2747-C009", "borrower_display_name": "Gus Borrower"},
    )
    amc_headers = make_amc_headers(env["amc"]["id"])
    loan_version = env["loan"]["version"]

    validate_error(
        api.create_appraisal(
            f.appraisal_payload(
                env["loan"]["id"], env["appraiser"]["id"], env["amc"]["id"],
                loan_version, report_form_type="FORM_9999",
            ),
            amc_headers,
        ),
        "ERR_INVALID_REQUEST", 400,
    )
    validate_error(
        api.create_appraisal(
            f.appraisal_payload(
                env["loan"]["id"], env["appraiser"]["id"], env["amc"]["id"],
                loan_version, exhibit_count=-1,
            ),
            amc_headers,
        ),
        "ERR_INVALID_REQUEST", 400,
    )

    _, meta = validate_paginated(
        api.list_appraisals(DESK_REVIEWER_HEADERS, {"loan_file_id": env["loan"]["id"]})
    )
    assert meta["total_count"] == 0


# The same three closed sales, filed against a report that is taken through the
# receipt battery so that its eight result rows exist to be inspected.
JUNIPER_GRID = [dict(row, street_address=row["street_address"].replace("Alder", "Juniper"))
                for row in ALDER_GRID]


def test_rule_check_rows_carry_no_version_and_no_update_stamp(api):
    """The eight receipt rows are immutable events with a reduced property set.

    A single run writes eight rows, each naming its parent report, its position in the
    fixed sequence, the code it evaluated, the outcome, the observed metric as a string
    and the explanation. None of them carries a version or an update stamp, because
    there is no operation in the system that could move one.

    PRD: "Rule-check rows are append-only events: they carry `id` and `created_at` only,
    with no `updated_at` and no `version`."

    Design: Corner/entities/immutability_rule_check_results_carry_no_version_and_no_write_endpoint
    """
    env = fx.graded_report(
        api,
        amc={"name": "Corner AMC Seven"},
        appraiser=_author("CA-AL-C010"),
        loan={"loan_number": "LN-2747-C010", "borrower_display_name": "Hugo Borrower"},
        comparables=JUNIPER_GRID,
    )

    rows, meta = validate_paginated(
        api.list_rule_checks(env["appraisal"]["id"], DESK_REVIEWER_HEADERS)
    )
    assert meta["total_count"] == 8
    assert len(rows) == 8

    for row in rows:
        assert_fields_present(
            row,
            (
                "id", "created_at", "appraisal_id", "sequence_no", "check_code",
                "outcome", "observed_value", "detail",
            ),
            label="rule-check row",
        )
        assert row["appraisal_id"] == env["appraisal"]["id"]
        assert isinstance(row["observed_value"], str)
        assert "version" not in row
        assert "updated_at" not in row


def test_a_comparable_filed_against_an_unknown_report_is_a_not_found(api):
    """The parent segment is resolved before the body is looked at.

    The comparable payload is perfectly well formed, but the report it names does not
    exist, so the refusal is the appraisal's own not-found code rather than a body
    complaint. Nothing is filed: the listing under the same unknown parent refuses in
    exactly the same way.

    PRD: "When a request carries more than one path segment that names a resource, those
    segments are resolved strictly left to right, and the first one that does not
    resolve produces the 404 for its own resource type before any deeper segment, body
    field, or business rule is examined."

    Design: Corner/entities/parent_relationship_comparable_on_unknown_appraisal_returns_404
    """
    amc = fx.create_amc(api, name="Corner AMC Eight")
    amc_headers = make_amc_headers(amc["id"])

    validate_error(
        api.create_comparable(
            UNKNOWN_ID, f.comparable_payload("4 Orphan Street"), amc_headers,
        ),
        "ERR_APPRAISAL_NOT_FOUND", 404,
    )
    validate_error(
        api.list_comparables(UNKNOWN_ID, amc_headers),
        "ERR_APPRAISAL_NOT_FOUND", 404,
    )


def test_one_appraiser_may_hold_active_memberships_on_two_panels(api):
    """The same appraiser and coverage state on a different company is not a duplicate.

    Uniqueness is over the triple of appraiser, company and coverage state, so enrolling
    the same appraiser in the same state on a second company succeeds and leaves the
    first membership active rather than superseding it. The junction is genuinely
    many-to-many in both directions: this appraiser now counts two memberships, and the
    first company's panel now lists two appraisers.

    PRD: "At most one active membership may exist for any one combination of appraiser,
    company, and coverage state; a second attempt at the same triple is rejected with
    `ERR_DUPLICATE_PANEL_MEMBERSHIP` (HTTP 422)."

    Design: Corner/entities/graph_topology_panel_membership_junction_links_appraiser_and_amc
    """
    first_amc = fx.create_amc(api, name="Junction AMC One")
    second_amc = fx.create_amc(api, name="Junction AMC Two")
    author = fx.create_appraiser(api, **_author("CA-AL-C012"))
    first_membership = fx.enroll_on_panel(api, author["id"], first_amc["id"])

    reviewer = fx.create_appraiser(
        api, full_name="Bob Reviewer", license_number="CA-BR-C012", license_state="CA",
    )
    fx.enroll_on_panel(
        api, reviewer["id"], first_amc["id"], tier="REVIEW_SPECIALIST",
    )

    author_version = fx.read_appraiser(api, author["id"])["version"]
    crossed = validate_success(
        api.create_panel_membership(
            f.panel_membership_payload(author["id"], second_amc["id"], author_version),
            CHIEF_APPRAISER_HEADERS,
        ),
        201,
    )

    assert crossed["appraiser_id"] == author["id"]
    assert crossed["amc_id"] == second_amc["id"]
    assert crossed["status"] == "ACTIVE"
    assert validate_success(
        api.get_panel_membership(first_membership["id"], CHIEF_APPRAISER_HEADERS)
    )["status"] == "ACTIVE"

    assert fx.read_appraiser(api, author["id"])["panel_membership_count"] == 2

    _, meta = validate_paginated(
        api.list_panel_memberships(
            CHIEF_APPRAISER_HEADERS, {"amc_id": first_amc["id"]},
        )
    )
    assert meta["total_count"] == 2
