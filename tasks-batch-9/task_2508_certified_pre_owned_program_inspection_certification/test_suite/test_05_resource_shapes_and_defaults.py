"""Resource shapes, declared defaults, and the identifiers a missing row reports.

The certified pre-owned programme is a system of record before it is a workflow
engine: a dealer freshly enrolled into the programme must expose every behaviour
counter the automaker watches it by, the singleton programme rulebook must report
the exact tunables every fee and coverage figure is keyed on, an inspection point
created without a measurement band must come back unmeasured, and the evidence
rows the pipeline appends must never grow a version they could be mutated
against. The other half of a resource's shape is what the service says when a
resource is *not* there: a path segment that names nothing reports the resource
type of that segment, a body foreign key that resolves to nothing reports the
single referenced-entity identifier, and both outrank the state and concurrency
guards that sit lower on the validation ladder. The tests here cover creation
defaults, derived counters, the junction edges of the graph, and that
not-found vocabulary.
"""

from test_helpers import (
    AGE_SURCHARGE_CENTS_PER_YEAR,
    AGE_SURCHARGE_FREE_YEARS,
    BASE_FEE_CENTS,
    CLOCK_EPOCH,
    DEFAULT_LIMIT,
    DEFAULT_PROGRAM_CONFIG,
    DEFAULT_PROGRAM_CONFIG_FRACTIONS,
    INELIGIBLE_PRIOR_USES,
    INELIGIBLE_TITLE_BRANDS,
    LISTING_REQUIRED_DISCLOSURE_FIELDS,
    MAX_LIMIT,
    MILEAGE_SURCHARGE_CENTS_PER_10K,
    MILEAGE_SURCHARGE_FREE_MILES,
    NON_EXISTENT_UUID,
    PROGRAM_CONFIG_TUNABLES,
    REQUIRED_DOC_TYPES,
    SURCHARGE_CAP_PCT,
    VOLUME_DISCOUNT_TIERS,
    ApiErrorId,
    active_certification,
    add_item,
    approve_certification,
    assert_certification,
    assert_certification_number,
    assert_checklist_item,
    assert_checklist_template,
    assert_created_at_ascending,
    assert_dealer,
    assert_dealer_ledger_conservation,
    assert_error_envelope,
    assert_inspection,
    assert_inspection_result,
    assert_instant_equals,
    assert_pagination_meta,
    assert_program_config,
    assert_technician,
    assert_vehicle,
    audit_finding_payload,
    claim_adjudication_payload,
    create_claim_payload,
    create_complaint_payload,
    create_dealer,
    create_draft_template,
    create_inspection_payload,
    create_listing_payload,
    create_technician,
    create_template,
    create_vehicle_payload,
    days_between,
    floor_cents,
    ids_of,
    item_b1_payload,
    item_p1_payload,
    item_s1_payload,
    make_dealer_principal_headers,
    passed_inspection,
    read_certification,
    read_dealer,
    read_inspection,
    read_vehicle,
    record_results,
    result_row,
    submit_certification,
    syndicate_payload,
    unique_franchise_code,
    unique_vin,
    validate_error,
    validate_paginated,
    validate_success,
    vehicle_version,
    waive_reconditioning_payload,
)

#: §3.7: "the number of chargeable mileage blocks is that excess divided by 10000".
MILEAGE_BLOCK_MILES = 10000

#: A body foreign key and a path segment that both resolve to no row at all.
MISSING_ID = NON_EXISTENT_UUID


def _three_point_template(api):
    """A DRAFT template carrying the two CRITICAL points and the measured one."""
    return create_draft_template(
        api, items=[item_p1_payload(), item_s1_payload(), item_b1_payload()]
    )


def test_dealer_enrolment_seeds_every_counter_at_its_floor(api, admin_headers):
    """A dealer enrolled with only its three declared inputs starts wholly at zero.

    PRD §3.2: "A newly enrolled dealer begins with `privilege_status` of `ACTIVE`,
    `privilege_reason` null, `claim_ratio_variant` of `LIFETIME_CUMULATIVE`, and every
    counter at zero."
    PRD §2.9: "a dealer with no activations and no claims scores a claim ratio of `0.00`
    rather than failing"
    PRD §3.2: "`fee_balance_cents` is the billed total minus the credited total"
    PRD §2.4: "a monotonically increasing integer that starts at 1 on creation"

    Design: Corner/entities/dealer_creation_returns_declared_and_default_fields
    """
    payload = {
        "name": "Coast Motors",
        "franchise_code": unique_franchise_code(),
        "region_code": "WEST",
    }
    response = api.create_dealer(payload, admin_headers)
    dealer = validate_success(response, expected_status=201)
    assert response.json()["response_type"] == "object"

    assert_dealer(dealer)
    assert dealer["name"] == payload["name"]
    assert dealer["franchise_code"] == payload["franchise_code"]
    assert dealer["region_code"] == payload["region_code"]
    assert dealer["privilege_status"] == "ACTIVE"
    assert dealer["privilege_reason"] is None
    for counter in (
        "lifetime_submitted_count",
        "lifetime_activated_count",
        "window_activated_count",
        "active_certification_count",
        "approved_claim_count_lifetime",
        "approved_claim_count_window",
        "audit_sample_count",
        "audit_fail_count",
    ):
        assert dealer[counter] == 0, f"{counter} starts at zero, got {dealer[counter]}"
    assert dealer["claim_ratio_variant"] == "LIFETIME_CUMULATIVE"
    assert float(dealer["claim_ratio_effective"]) == 0.00
    assert float(dealer["audit_fail_rate"]) == 0.00
    assert dealer["risk_score"] == 0
    assert dealer["fee_billed_cents_total"] == 0
    assert dealer["fee_credited_cents_total"] == 0
    assert dealer["fee_balance_cents"] == 0
    assert dealer["version"] == 1
    assert "-" in dealer["id"] and not dealer["id"].startswith("dealer")

    reread = read_dealer(api, dealer["id"], admin_headers)
    assert reread == dealer, "a read of a freshly enrolled dealer repeats the creation body"


def test_program_configuration_reports_its_seeded_tunables(api, auditor_headers):
    """The single rulebook row is readable and reports the tunables the PRD seeds it to.

    PRD §2.6: "The programme's tunables live in a single **programme configuration** row
    that the server seeds at startup with the documented defaults"
    PRD §2.6: "`max_age_days` is 2190 and must be at least 1; `max_odometer_miles` is 80000
    and must be at least 1"
    PRD §2.6: "`base_fee_cents` is 89900; `age_surcharge_free_years` is 3;
    `age_surcharge_cents_per_year` is 12500"
    PRD §2.6: "`volume_discount_tiers` is the ordered list of `min_count`/`pct` pairs 0 at
    0.0, 10 at 0.05, and 50 at 0.10"
    PRD §2.6: "All five roles may read the live configuration, including its `version`"
    PRD §2.6: "there is exactly one such row and it is never created or deleted through the
    API"
    PRD §2.4: "a monotonically increasing integer that starts at 1 on creation"

    Design: Corner/entities/program_config_retrieval_returns_declared_defaults
    """
    config = validate_success(api.get_program_config(auditor_headers))
    assert_program_config(config)

    for tunable in PROGRAM_CONFIG_TUNABLES:
        assert tunable in config, f"the configuration row must carry {tunable}"
    for tunable, expected in DEFAULT_PROGRAM_CONFIG.items():
        assert config[tunable] == expected, (
            f"{tunable} is seeded to {expected}, got {config[tunable]}"
        )
    for tunable, expected in DEFAULT_PROGRAM_CONFIG_FRACTIONS.items():
        assert float(config[tunable]) == expected, (
            f"{tunable} is seeded to {expected}, got {config[tunable]}"
        )

    tiers = [(tier["min_count"], float(tier["pct"])) for tier in config["volume_discount_tiers"]]
    assert tiers == [
        (tier["min_count"], float(tier["pct"])) for tier in VOLUME_DISCOUNT_TIERS
    ]
    assert set(config["ineligible_title_brands"]) == set(INELIGIBLE_TITLE_BRANDS)
    assert "CLEAN" not in config["ineligible_title_brands"]
    assert set(config["ineligible_prior_uses"]) == set(INELIGIBLE_PRIOR_USES)
    assert list(config["required_doc_types"]) == list(REQUIRED_DOC_TYPES)
    assert list(config["listing_required_disclosure_fields"]) == list(
        LISTING_REQUIRED_DISCLOSURE_FIELDS
    )
    assert config["version"] == 1, "the seeded generation has never been retuned"


def test_checklist_point_listing_filters_and_paginates_independently(api, auditor_headers):
    """Category, severity and the page window are each computed over the same three points.

    PRD §3.1: "the point listing accepts `category` and `severity` filters alongside the
    usual `limit` and `offset`"
    PRD §2.3: "the `limit` and `offset` actually applied, `total_count` giving the number of
    rows matching the filter before pagination, and `has_more`, which is true when rows
    remain beyond the current page"
    PRD §3.1: "adding a point recomputes the template's `point_count` and its
    `critical_item_count` (the number of its points whose `severity` is `CRITICAL`)"

    Design: Corner/entities/checklist_items_listing_filters_and_paginates
    """
    template = _three_point_template(api)

    response = api.list_checklist_items(template["id"], auditor_headers)
    rows, meta = validate_paginated(response)
    assert response.json()["response_type"] == "array"
    assert len(rows) == 3
    assert_pagination_meta(meta, DEFAULT_LIMIT, 0, 3, False)
    assert_created_at_ascending(rows)
    for row in rows:
        assert_checklist_item(row)
        assert row["template_id"] == template["id"]

    critical_rows, critical_meta = validate_paginated(
        api.list_checklist_items(template["id"], auditor_headers, params={"severity": "CRITICAL"})
    )
    assert [row["item_code"] for row in critical_rows] == ["P1", "S1"]
    assert critical_meta["total_count"] == 2

    brake_rows, brake_meta = validate_paginated(
        api.list_checklist_items(template["id"], auditor_headers, params={"category": "BRAKES"})
    )
    assert [row["item_code"] for row in brake_rows] == ["B1"]
    assert brake_meta["total_count"] == 1
    assert float(brake_rows[0]["min_measure"]) == 4.0
    assert float(brake_rows[0]["max_measure"]) == 12.0

    page_rows, page_meta = validate_paginated(
        api.list_checklist_items(
            template["id"], auditor_headers, params={"limit": 2, "offset": 2}
        )
    )
    assert len(page_rows) == 1
    assert_pagination_meta(page_meta, 2, 2, 3, False)
    assert ids_of(page_rows) == [rows[2]["id"]]

    reread = validate_success(api.get_checklist_template(template["id"], auditor_headers))
    assert_checklist_template(reread)
    assert reread["point_count"] == 3
    assert reread["critical_item_count"] == 2


def test_each_path_segment_reports_its_own_not_found_identifier(
    api, admin_headers, auditor_headers, advocate_headers
):
    """A missing path resource names its own type, and identity resolution outranks it.

    PRD §2.11: "the request is rejected at the first identifier that does not name an
    existing row, with the not-found identifier belonging to that resource type"
    PRD §2.10: "Existence of every resource named by a path segment, checked left to right
    — otherwise the not-found identifier for the first missing segment."
    PRD §2.1: "If an entity-backed principal's `X-User-ID` does not resolve to an existing
    `Dealer` row (for `DealerPrincipal`) or an existing `Technician` row (for
    `InspectionTechnician`), the request is rejected with `ERR_IDENTITY_NOT_RECOGNIZED`
    (HTTP 403)."

    Design: Corner/entities/path_segment_not_found_errors_across_resources
    """
    validate_error(api.get_dealer(MISSING_ID, admin_headers), ApiErrorId.ERR_DEALER_NOT_FOUND)
    validate_error(api.get_vehicle(MISSING_ID, admin_headers), ApiErrorId.ERR_VEHICLE_NOT_FOUND)
    validate_error(
        api.get_checklist_template(MISSING_ID, admin_headers), ApiErrorId.ERR_TEMPLATE_NOT_FOUND
    )
    validate_error(
        api.get_inspection(MISSING_ID, admin_headers), ApiErrorId.ERR_INSPECTION_NOT_FOUND
    )
    validate_error(
        api.complete_reconditioning_item(
            MISSING_ID, waive_reconditioning_payload("cosmetic only"), admin_headers
        ),
        ApiErrorId.ERR_RECONDITIONING_ITEM_NOT_FOUND,
    )
    validate_error(
        api.get_certification(MISSING_ID, admin_headers), ApiErrorId.ERR_CERTIFICATION_NOT_FOUND
    )
    validate_error(
        api.record_audit_finding(MISSING_ID, audit_finding_payload("PASS"), auditor_headers),
        ApiErrorId.ERR_AUDIT_SAMPLE_NOT_FOUND,
    )
    identity = api.syndicate_listing(
        MISSING_ID, syndicate_payload(1), make_dealer_principal_headers(MISSING_ID)
    )
    validate_error(identity, ApiErrorId.ERR_IDENTITY_NOT_RECOGNIZED)
    validate_error(
        api.adjudicate_warranty_claim(
            MISSING_ID,
            claim_adjudication_payload("DENY", "INSUFFICIENT_EVIDENCE"),
            admin_headers,
        ),
        ApiErrorId.ERR_CLAIM_NOT_FOUND,
    )
    missing_complaint = api.get_complaint(MISSING_ID, advocate_headers)
    validate_error(missing_complaint, ApiErrorId.ERR_COMPLAINT_NOT_FOUND)
    assert_error_envelope(missing_complaint.json())

    _, inspection_meta = validate_paginated(api.list_inspections(admin_headers))
    assert inspection_meta["total_count"] == 0
    _, certification_meta = validate_paginated(api.list_certifications(admin_headers))
    assert certification_meta["total_count"] == 0, "no refused call wrote a row"


def test_syndicating_a_missing_listing_reports_the_listing_not_found(api, program):
    """With a recognised dealer acting, the missing listing outranks the version guard.

    PRD §2.10: "Existence of every resource named by a path segment, checked left to right
    — otherwise the not-found identifier for the first missing segment."
    PRD §2.10: "The optimistic concurrency guard of §2.8 — otherwise the stale-version
    identifier for the parent entity."
    PRD §2.2: "The `meta` object for error responses contains only `api_request_id` and
    `api_request_timestamp`."

    Design: Corner/entities/listing_syndicate_on_missing_listing_returns_not_found
    """
    dealer = read_dealer(api, program.dealer_id)
    response = api.syndicate_listing(
        MISSING_ID, syndicate_payload(dealer["version"]), program.dealer_headers
    )
    validate_error(response, ApiErrorId.ERR_LISTING_NOT_FOUND)
    body = response.json()
    assert_error_envelope(body)
    assert set(body["data"].keys()) == {"error_id", "message"}, (
        "the rejection carries no version-conflict detail beyond the envelope"
    )


def test_vehicle_registration_without_prior_use_is_a_schema_violation(api, admin_headers):
    """`prior_use` has no declared default, so omitting it is refused before eligibility.

    PRD §3.2: "a `title_brand`, a documented `prior_use`, and an `owner_count` giving the
    number of retail owners on the title history, defaulting to 1"
    PRD §2.10: "Schema validity of the request body and query parameters: required fields
    present, enum members recognised, numbers in range"
    PRD §3.2: "A new vehicle starts with `cpo_state` `NOT_CERTIFIED`, `inventory_state`
    `IN_INVENTORY`"

    Design: Corner/entities/vehicle_creation_missing_prior_use_invalid_request
    """
    rejected = api.create_vehicle(
        create_vehicle_payload(vin=unique_vin(), prior_use=None), admin_headers
    )
    validate_error(rejected, ApiErrorId.ERR_INVALID_REQUEST)
    assert_error_envelope(rejected.json())

    accepted = api.create_vehicle(
        create_vehicle_payload(vin=unique_vin(), prior_use="PERSONAL"), admin_headers
    )
    vehicle = validate_success(accepted, expected_status=201)
    assert_vehicle(vehicle)
    assert vehicle["prior_use"] == "PERSONAL"
    assert vehicle["cpo_state"] == "NOT_CERTIFIED"
    assert vehicle["inventory_state"] == "IN_INVENTORY"


def test_omitted_optional_inputs_take_their_declared_defaults(api, admin_headers):
    """A technician without a credential status and a point without a band come back defaulted.

    PRD §3.2: "an optional `credential_status` of `ACTIVE` or `REVOKED` that defaults to
    `ACTIVE`"
    PRD §3.2: "A technician's `dealer_id` is taken from the path segment naming the employer,
    not from the body."
    PRD §3.2: "Its `completed_inspection_count` starts at 0"
    PRD §3.1: "either may be omitted, in which case it is null and that side of the band is
    unbounded"
    PRD §3.1: "`max_reconditioning_cost_cents`, defaulting to 100000 cents, is the per-item
    ceiling on the reimbursable repair amount for the point"

    Design: Corner/entities/technician_and_checklist_item_defaults_applied
    """
    dealer = create_dealer(api)
    template = create_template(api)

    technician = create_technician(api, dealer["id"], credential_status=None)
    assert_technician(technician)
    assert technician["credential_status"] == "ACTIVE"
    assert technician["completed_inspection_count"] == 0
    assert technician["dealer_id"] == dealer["id"]
    assert technician["version"] == 1

    item = add_item(api, template["id"], item_p1_payload(), admin_headers)
    assert_checklist_item(item)
    assert item["min_measure"] is None
    assert item["max_measure"] is None
    assert item["max_reconditioning_cost_cents"] == 100000
    assert item["reconditioning_allowed"] is False, (
        "the supplied false is honoured rather than overwritten by the default true"
    )


def test_dealer_counters_follow_submission_and_approval(api, admin_headers, program):
    """Submission moves the submitted and active counters; only approval bills the fee.

    PRD §3.2: "`lifetime_submitted_count` counts every certification the dealer has ever
    submitted in any status; it increments on each submission, is never decremented, and
    doubles as the sequence number inside the certification label."
    PRD §3.2: "`active_certification_count` counts the dealer's certifications currently
    `SUBMITTED`, `ACTIVE`, or `UNDER_AUDIT`."
    PRD §3.6: "A newly submitted certification carries no financial or coverage content
    whatsoever."
    PRD §3.2: "`fee_billed_cents_total` sums the fee charged over every certification of the
    dealer that has been activated at least once"
    PRD §3.7: "`fee_charged_cents` is the subtotal minus `fee_discount_cents`."

    Design: Corner/entities/dealer_counters_recomputed_from_pipeline_activity
    """
    walk = passed_inspection(api, program)
    certification = submit_certification(
        api, program.dealer_headers, walk.vehicle_id, walk.inspection_id
    )
    assert_certification(certification)
    assert certification["status"] == "SUBMITTED"
    assert_certification_number(
        certification["certification_number"], program.dealer["franchise_code"], 1
    )
    assert certification["document_count"] == 3
    assert certification["fee_charged_cents"] == 0

    after_submission = read_dealer(api, program.dealer_id, admin_headers)
    assert after_submission["lifetime_submitted_count"] == 1
    assert after_submission["active_certification_count"] == 1
    assert after_submission["lifetime_activated_count"] == 0
    assert after_submission["fee_billed_cents_total"] == 0
    assert_dealer_ledger_conservation(after_submission)

    approve_certification(api, certification["id"], admin_headers)

    activation_date = CLOCK_EPOCH[:10]
    age_days = days_between(walk.vehicle["in_service_date"], activation_date)
    chargeable_years = max(0, age_days // 365 - AGE_SURCHARGE_FREE_YEARS)
    odometer = walk.inspection["odometer_at_inspection"]
    excess_miles = max(0, odometer - MILEAGE_SURCHARGE_FREE_MILES)
    raw_surcharge = chargeable_years * AGE_SURCHARGE_CENTS_PER_YEAR + (
        excess_miles // MILEAGE_BLOCK_MILES
    ) * MILEAGE_SURCHARGE_CENTS_PER_10K
    surcharge = min(raw_surcharge, floor_cents(BASE_FEE_CENTS * SURCHARGE_CAP_PCT))
    subtotal = BASE_FEE_CENTS + surcharge
    discount = floor_cents(subtotal * VOLUME_DISCOUNT_TIERS[0]["pct"])
    charged = subtotal - discount

    priced = read_certification(api, certification["id"], admin_headers)
    assert priced["status"] == "ACTIVE"
    assert priced["fee_surcharge_cents"] == surcharge
    assert priced["fee_discount_cents"] == discount
    assert priced["fee_charged_cents"] == charged

    after_approval = read_dealer(api, program.dealer_id, admin_headers)
    assert after_approval["lifetime_activated_count"] == 1
    assert after_approval["window_activated_count"] == 1
    assert after_approval["fee_billed_cents_total"] == charged
    assert after_approval["fee_credited_cents_total"] == 0
    assert after_approval["fee_balance_cents"] == charged
    assert after_approval["lifetime_submitted_count"] == 1, (
        "the submitted counter counts submissions, not activations"
    )
    assert_dealer_ledger_conservation(after_approval)


def test_client_supplied_system_fields_are_discarded_on_submission(api, admin_headers, program):
    """Status, label, owner, stamp and fee are all server-sourced whatever the body claims.

    PRD §3.6: "The certification's `dealer_id` is resolved from the acting `X-User-ID`, never
    supplied."
    PRD §3.6: "A successful submission creates the certification in `SUBMITTED` with
    `submitted_at` set to the logical clock and a deterministic `certification_number`."
    PRD §3.6: "That label is built as the literal prefix `CPO-`, then the certifying dealer's
    `franchise_code`, then a hyphen, then the dealer's `lifetime_submitted_count` *after*
    this submission has incremented it, zero-padded to four digits"
    PRD §3.6: "A newly submitted certification carries no financial or coverage content
    whatsoever."
    PRD §3.6: "Its `program_config_version`, `warranty_anchor_variant`, `warranty_start_date`,
    `warranty_end_date`, `warranty_end_miles`, and `retention_expires_at` are all null"

    Design: Corner/entities/certification_system_fields_input_ignored
    """
    other_dealer = create_dealer(api)
    walk = passed_inspection(api, program)

    certification = submit_certification(
        api,
        program.dealer_headers,
        walk.vehicle_id,
        walk.inspection_id,
        status="ACTIVE",
        certification_number="CPO-HACK-9999",
        dealer_id=other_dealer["id"],
        submitted_at="2020-01-01T00:00:00Z",
        fee_charged_cents=1,
    )
    assert_certification(certification)
    assert certification["status"] == "SUBMITTED"
    assert_certification_number(
        certification["certification_number"], program.dealer["franchise_code"], 1
    )
    assert certification["dealer_id"] == program.dealer_id
    assert_instant_equals(certification["submitted_at"], CLOCK_EPOCH, "submitted_at")
    assert certification["fee_charged_cents"] == 0
    assert certification["activated_at"] is None
    assert certification["program_config_version"] is None

    untouched = read_dealer(api, other_dealer["id"], admin_headers)
    assert untouched["lifetime_submitted_count"] == 0
    assert untouched["active_certification_count"] == 0


def test_undeclared_enum_members_and_out_of_range_limit_are_rejected(api, admin_headers):
    """An unrecognised enum member and an oversized page are both schema violations.

    PRD §2.10: "Schema validity of the request body and query parameters: required fields
    present, enum members recognised, numbers in range, `limit` within 1 through 100,
    `offset` at least 0"
    PRD §2.3: "A `limit` outside the range from 1 through 100, or a negative `offset`, is a
    schema violation rejected with `ERR_INVALID_REQUEST` (HTTP 400)"
    PRD §3.1: "A new template is born in `DRAFT` with `published_at` null, `point_count` 0,
    and `critical_item_count` 0."

    Design: Corner/entities/checklist_item_invalid_enum_rejected
    """
    template = create_template(api)

    bad_severity = api.add_checklist_item(
        template["id"],
        item_p1_payload(item_code="X1", severity="SHOWSTOPPER"),
        admin_headers,
    )
    validate_error(bad_severity, ApiErrorId.ERR_INVALID_REQUEST)

    bad_category = api.add_checklist_item(
        template["id"],
        item_p1_payload(item_code="X2", category="SUSPENSION", severity="MAJOR"),
        admin_headers,
    )
    validate_error(bad_category, ApiErrorId.ERR_INVALID_REQUEST)

    oversized = api.list_checklist_items(
        template["id"], admin_headers, params={"limit": MAX_LIMIT + 1}
    )
    validate_error(oversized, ApiErrorId.ERR_INVALID_REQUEST)

    reread = validate_success(api.get_checklist_template(template["id"], admin_headers))
    assert reread["point_count"] == 0
    assert reread["critical_item_count"] == 0
    assert reread["status"] == "DRAFT"


def test_recorded_attempts_are_append_only_and_carry_no_version(api, auditor_headers, open_walk):
    """A second attempt writes fresh rows and leaves the first attempt's evidence intact.

    PRD §3.4: "A recording call never edits the rows a previous call wrote."
    PRD §3.4: "Instead it increments the inspection's `attempt_count` by exactly 1 and then
    writes one result row per supplied entry"
    PRD §3.4: "Earlier attempts remain visible forever."
    PRD §2.4: "Three resource types are configuration or append-only evidence rows and are
    never mutated after creation: checklist items, inspection results, and certification
    documents. These carry only `id` and `created_at`; both `updated_at` and `version` are
    absent from them."
    PRD §3.4: "ignoring every earlier attempt"

    Design: Corner/entities/immutable_child_rows_carry_no_version_field
    """
    program = open_walk.program
    failing_rows = [
        result_row("P1", "PASS"),
        result_row("S1", "PASS"),
        result_row("B1", "FAIL", measured_value=2.0),
    ]
    clean_rows = [
        result_row("P1", "PASS"),
        result_row("S1", "PASS"),
        result_row("B1", "PASS", measured_value=8.0),
    ]
    record_results(api, open_walk.inspection_id, program.technician_headers, failing_rows)
    record_results(api, open_walk.inspection_id, program.technician_headers, clean_rows)

    first, first_meta = validate_paginated(
        api.list_results(open_walk.inspection_id, auditor_headers, params={"attempt_index": 1})
    )
    assert first_meta["total_count"] == 3
    first_by_code = {row["item_code"]: row for row in first}
    assert first_by_code["B1"]["outcome"] == "FAIL"
    assert float(first_by_code["B1"]["measured_value"]) == 2.0

    second, second_meta = validate_paginated(
        api.list_results(open_walk.inspection_id, auditor_headers, params={"attempt_index": 2})
    )
    assert second_meta["total_count"] == 3
    second_by_code = {row["item_code"]: row for row in second}
    assert second_by_code["B1"]["outcome"] == "PASS"
    assert float(second_by_code["B1"]["measured_value"]) == 8.0

    assert not set(ids_of(first)) & set(ids_of(second)), (
        "the second attempt writes new rows rather than editing the first attempt's"
    )
    for row in first + second:
        assert_inspection_result(row)
        assert "version" not in row
        assert "updated_at" not in row
        assert row["recorded_by_technician_id"] == program.technician_id
    assert {row["attempt_index"] for row in first} == {1}
    assert {row["attempt_index"] for row in second} == {2}

    inspection = read_inspection(api, open_walk.inspection_id, auditor_headers)
    assert_inspection(inspection)
    assert inspection["attempt_count"] == 2
    assert inspection["recorded_item_count"] == 3
    assert inspection["failed_recon_count"] == 0
    assert inspection["failed_critical_count"] == 0
    assert inspection["status"] == "IN_PROGRESS"


def test_adding_a_point_under_a_missing_template_reports_the_template(api, admin_headers):
    """A point is created only through its parent's path, so a bogus parent 404s first.

    PRD §2.11: "A request for the items of a template that does not exist therefore reports
    the missing template, never an empty list."
    PRD §2.10: "Existence of every resource named by a path segment, checked left to right
    — otherwise the not-found identifier for the first missing segment."

    Design: Corner/entities/checklist_item_under_missing_template_not_found
    """
    template = create_template(api)

    rejected = api.add_checklist_item(MISSING_ID, item_p1_payload(), admin_headers)
    validate_error(rejected, ApiErrorId.ERR_TEMPLATE_NOT_FOUND)

    item = add_item(api, template["id"], item_p1_payload(), admin_headers)
    assert_checklist_item(item)
    assert item["template_id"] == template["id"]

    reread = validate_success(api.get_checklist_template(template["id"], admin_headers))
    assert reread["point_count"] == 1, "the refused call wrote nothing"


def test_unresolvable_body_foreign_keys_report_the_referenced_entity(
    api, advocate_headers, program, vehicle
):
    """Every body foreign key resolves at one rung, above both state and the version guard.

    PRD §2.10: "Existence of every foreign key supplied in the request body — otherwise
    `ERR_REFERENCED_ENTITY_NOT_FOUND`."
    PRD §3.3: "any body foreign key that does not resolve at all yields
    `ERR_REFERENCED_ENTITY_NOT_FOUND`"
    PRD §2.10: "The optimistic concurrency guard of §2.8 — otherwise the stale-version
    identifier for the parent entity."

    Design: Corner/entities/certification_body_foreign_keys_referenced_entity_not_found
    """
    current_version = vehicle_version(api, vehicle["id"])
    started_at = program.next_start()

    calls = [
        api.create_inspection(
            create_inspection_payload(
                MISSING_ID, program.technician_id, program.template_id, started_at=started_at
            ),
            program.dealer_headers,
        ),
        api.create_inspection(
            create_inspection_payload(
                vehicle["id"], MISSING_ID, program.template_id, started_at=started_at
            ),
            program.dealer_headers,
        ),
        api.create_inspection(
            create_inspection_payload(
                vehicle["id"], program.technician_id, MISSING_ID, started_at=started_at
            ),
            program.dealer_headers,
        ),
        api.create_listing(create_listing_payload(MISSING_ID), program.dealer_headers),
        api.create_warranty_claim(create_claim_payload(MISSING_ID), program.dealer_headers),
        api.create_complaint(create_complaint_payload(MISSING_ID), advocate_headers),
    ]
    for response in calls:
        validate_error(response, ApiErrorId.ERR_REFERENCED_ENTITY_NOT_FOUND)

    guarded = api.create_certification(
        {
            "vehicle_id": vehicle["id"],
            "inspection_id": MISSING_ID,
            "expected_vehicle_version": current_version,
            "documents": [
                {"doc_type": "TITLE_HISTORY_REPORT", "reference": "THR-1"},
                {"doc_type": "INSPECTION_WORKSHEET", "reference": "IW-1"},
                {"doc_type": "CUSTOMER_DISCLOSURE", "reference": "CD-1"},
            ],
        },
        program.dealer_headers,
    )
    validate_error(guarded, ApiErrorId.ERR_REFERENCED_ENTITY_NOT_FOUND)
    assert guarded.status_code == 404, (
        "the referenced-entity rung precedes the concurrency guard, so no 412 is possible"
    )

    reread = read_vehicle(api, vehicle["id"])
    assert reread["version"] == current_version, "no refused call mutated the vehicle"
    assert reread["cpo_state"] == "NOT_CERTIFIED"
    assert reread["active_certification_count"] == 0


def test_a_live_certification_is_discoverable_from_each_of_its_parents(
    api, admin_headers, auditor_headers, program
):
    """The junction rows are reachable from every edge they carry, with identical content.

    PRD §3.6: "accepts filters on `vehicle_id`, `inspection_id`, `dealer_id`, `status`, and
    `audit_sampled`, with `limit` and `offset`"
    PRD §3.3: "The inspection listing is the reverse-discovery channel for every edge an
    inspection carries and accepts filters on `vehicle_id`, `dealer_id`, `technician_id`,
    `template_id`, `parent_inspection_id`, `complaint_id`, `status`, and `purpose`, with
    `limit` and `offset`."
    PRD §3.2: "`certified_certification_id` names the vehicle's certification that is
    `ACTIVE` or `UNDER_AUDIT`, or is null when there is none; it is not a foreign key but a
    derived pointer."
    PRD §3.2: "Its `completed_inspection_count` starts at 0 and counts the technician's
    inspections that have reached `PASSED` or `FAILED`."

    Design: Corner/entities/graph_topology_certification_joins_three_parents
    """
    walk = active_certification(api, program)
    certification_id = walk.certification_id

    for query in (
        {"vehicle_id": walk.vehicle_id},
        {"inspection_id": walk.inspection_id},
        {"dealer_id": program.dealer_id},
    ):
        rows, meta = validate_paginated(api.list_certifications(auditor_headers, params=query))
        assert meta["total_count"] == 1, f"{query} must find exactly the one certification"
        assert ids_of(rows) == [certification_id]

    for query in (
        {"technician_id": program.technician_id},
        {"template_id": program.template_id},
    ):
        rows, meta = validate_paginated(api.list_inspections(auditor_headers, params=query))
        assert meta["total_count"] == 1, f"{query} must find exactly the one inspection"
        assert ids_of(rows) == [walk.inspection_id]

    certification = read_certification(api, certification_id, auditor_headers)
    assert certification["vehicle_id"] == walk.vehicle_id
    assert certification["inspection_id"] == walk.inspection_id
    assert certification["dealer_id"] == program.dealer_id

    inspection = read_inspection(api, walk.inspection_id, auditor_headers)
    assert inspection["vehicle_id"] == walk.vehicle_id
    assert inspection["technician_id"] == program.technician_id
    assert inspection["template_id"] == program.template_id
    assert inspection["dealer_id"] == program.dealer_id

    reread = read_vehicle(api, walk.vehicle_id, auditor_headers)
    assert reread["certified_certification_id"] == certification_id
    assert reread["cpo_state"] == "CERTIFIED"

    roster, _ = validate_paginated(api.list_technicians(program.dealer_id, admin_headers))
    technician = next(row for row in roster if row["id"] == program.technician_id)
    assert technician["completed_inspection_count"] == 1
