"""Resource representation: declared defaults, stored reads, listing envelopes,
shape rejections and the immutable record types of the carriage admin API.

Every test builds its own state from an empty database through PRD-declared
endpoints only.
"""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_distributor,
    assert_rate_card_entry,
    assert_subscriber_report,
    create_agreement_payload,
    create_distributor_payload,
    create_rate_card_entry_payload,
    create_rights_window_payload,
    create_subscriber_report_payload,
    draft_agreement,
    execute_agreement,
    fetch_agreement,
    make_affiliate_sales_exec_headers,
    make_audit_manager_headers,
    make_distributor_liaison_headers,
    make_network_admin_headers,
    make_revenue_accountant_headers,
    make_rights_administrator_headers,
    register_distributor,
    register_title,
    setup_draft_agreement,
    setup_executed_agreement,
    validate_error,
    validate_paginated,
    validate_success,
)

# Flat, non-escalating commercial terms whose derived rate is the base fee.
FLAT_TERMS = {
    "term_start_date": "2025-01-01T00:00:00Z",
    "term_end_date": "2028-12-31T00:00:00Z",
    "base_license_fee_cents_per_sub": 40.0000,
    "escalator_pct": 0.00,
    "penetration_floor_pct": 0.50,
    "committed_tier": "BASIC",
}

# A 200,000-home telco: the denominator of every penetration figure below.
CLIFFSIDE = {
    "legal_name": "Cliffside Telco",
    "distributor_type": "TELCO",
    "rate_card_class": "CLASS_B",
    "total_subscribers": 200_000,
}


def test_distributor_create_applies_declared_defaults_and_system_fields(api):
    """PRD §3.1: "A `credit_limit_cents` may be supplied; when it is omitted the
    operator receives the standard ceiling of 100,000,000 cents — one million
    dollars — and it may never be negative."
    PRD §3.1: "A newly registered operator starts `ACTIVE` with
    `credit_hold_reason` of `NONE`, with `receivable_balance_cents`,
    `audit_recovery_balance_cents` and `executed_agreement_count` all at zero,
    and with `version` 1."
    PRD §4: "Creation endpoints return HTTP 201 with the created resource; every
    other successful call returns HTTP 200 with the affected resource, the
    requested resource, or a list."

    Design: Corner/entities/distributor_create_applies_declared_defaults_and_system_fields
    """
    payload = create_distributor_payload(
        legal_name="Meridian Broadband",
        distributor_type="CABLE_MSO",
        rate_card_class="CLASS_A",
        total_subscribers=1_500_000,
    )
    payload.pop("credit_limit_cents")

    response = api.create_distributor(payload, make_network_admin_headers())
    data = validate_success(response, 201)
    body = response.json()

    assert body["response_type"] == "object", "a single resource is returned as an object"
    assert body["meta"]["api_request_id"], "meta.api_request_id must be a non-empty string"

    assert data["credit_limit_cents"] == 100_000_000, (
        "an omitted credit_limit_cents must take the standard ceiling of "
        f"100,000,000 cents, got {data['credit_limit_cents']}"
    )
    assert data["status"] == "ACTIVE", f"a new operator starts ACTIVE, got {data['status']}"
    assert data["credit_hold_reason"] == "NONE", (
        f"a new operator starts with credit_hold_reason NONE, got {data['credit_hold_reason']}"
    )
    assert data["receivable_balance_cents"] == 0, "receivable_balance_cents starts at zero"
    assert data["audit_recovery_balance_cents"] == 0, (
        "audit_recovery_balance_cents starts at zero"
    )
    assert data["executed_agreement_count"] == 0, "executed_agreement_count starts at zero"
    assert data["version"] == 1, f"a created resource carries version 1, got {data['version']}"
    assert_distributor(data)


def test_distributor_get_returns_stored_representation(api):
    """PRD §3.1: "Registration supplies a `legal_name` of between 1 and 200
    characters that must be unique across all operators, a `distributor_type` of
    `CABLE_MSO`, `DBS`, `TELCO` or `VMVPD`, a `rate_card_class` of `CLASS_A`,
    `CLASS_B` or `CLASS_C` identifying which published card column this operator
    negotiates against, and a `total_subscribers` count of at least 1 covering
    the operator's whole video base across all tiers."
    PRD §3.1: "A `credit_limit_cents` may be supplied; when it is omitted the
    operator receives the standard ceiling of 100,000,000 cents — one million
    dollars — and it may never be negative."
    PRD §2.4: "Mutable resources additionally carry `created_at` and
    `updated_at`, both ISO 8601 UTC timestamps with three fractional digits, and
    `version`, an integer that starts at 1 when the resource is created and
    increments by exactly 1 on every mutation the server applies to that
    resource — including mutations the caller did not directly address, such as a
    counter refreshed by a cascade originating on a different resource."

    Design: Corner/entities/distributor_get_returns_stored_representation
    """
    distributor = register_distributor(
        legal_name="Harbor Satellite",
        distributor_type="DBS",
        rate_card_class="CLASS_B",
        total_subscribers=800_000,
        credit_limit_cents=250_000_000,
    )

    data = validate_success(api.get_distributor(distributor["id"], make_audit_manager_headers()))

    assert data["id"] == distributor["id"], "the read must address the stored operator"
    assert data["legal_name"] == "Harbor Satellite", (
        f"legal_name must round-trip unchanged, got {data['legal_name']!r}"
    )
    assert data["distributor_type"] == "DBS", f"distributor_type stored, got {data['distributor_type']}"
    assert data["rate_card_class"] == "CLASS_B", (
        f"rate_card_class stored, got {data['rate_card_class']}"
    )
    assert data["total_subscribers"] == 800_000, (
        f"total_subscribers stored, got {data['total_subscribers']}"
    )
    assert data["credit_limit_cents"] == 250_000_000, (
        "a supplied credit_limit_cents must be kept rather than replaced by the "
        f"100,000,000 default, got {data['credit_limit_cents']}"
    )
    assert data["version"] == 1, (
        f"a read applies no mutation, so version stays 1, got {data['version']}"
    )
    assert_distributor(data)


def test_agreement_listing_filters_and_paginates_with_total_count(api):
    """PRD §2.3: "`limit` defaults to 10, may not be smaller than 1, and may not
    be larger than 100."
    PRD §2.3: "`offset` defaults to 0 and may not be negative."
    PRD §2.3: "`total_count` is the number of records matching the filter before
    pagination is applied, and `has_more` is true exactly when records remain
    beyond the current page."
    PRD §2.3: "Filter query parameters combine conjunctively: supplying both an
    agreement filter and a status filter returns only records satisfying both."

    Design: Corner/entities/agreement_listing_filters_and_paginates_with_total_count
    """
    admin = make_network_admin_headers()
    distributor = register_distributor(
        legal_name="Meridian Broadband", total_subscribers=1_500_000
    )
    draft_agreement(distributor["id"], contract_code="MB-A", **FLAT_TERMS)
    draft_agreement(distributor["id"], contract_code="MB-B", **FLAT_TERMS)
    third = draft_agreement(distributor["id"], contract_code="MB-C", **FLAT_TERMS)
    execute_agreement(third["id"])

    rows, meta = validate_paginated(
        api.list_agreements(admin, params={"distributor_id": distributor["id"], "limit": 2, "offset": 0})
    )
    assert len(rows) == 2, f"limit=2 must return exactly 2 rows, got {len(rows)}"
    assert meta["total_count"] == 3, (
        f"total_count counts the whole filtered population, got {meta['total_count']}"
    )
    assert meta["limit"] == 2, f"meta.limit echoes the request, got {meta['limit']}"
    assert meta["offset"] == 0, f"meta.offset echoes the request, got {meta['offset']}"
    assert meta["has_more"] is True, "two of three rows returned leaves records beyond this page"

    rows, meta = validate_paginated(
        api.list_agreements(admin, params={"distributor_id": distributor["id"], "limit": 2, "offset": 2})
    )
    assert len(rows) == 1, f"offset=2 leaves exactly 1 row, got {len(rows)}"
    assert meta["total_count"] == 3, "total_count is computed before pagination"
    assert meta["has_more"] is False, "no records remain beyond the last page"

    rows, meta = validate_paginated(
        api.list_agreements(
            admin,
            params={
                "distributor_id": distributor["id"],
                "lifecycle_status": "EXECUTED",
                "limit": 10,
            },
        )
    )
    assert len(rows) == 1, f"exactly one agreement is EXECUTED, got {len(rows)} rows"
    assert rows[0]["id"] == third["id"], "the EXECUTED filter must select the executed agreement"
    assert meta["total_count"] == 1, (
        f"total_count reflects the filtered population, got {meta['total_count']}"
    )
    assert meta["has_more"] is False, "one row of one leaves nothing beyond the page"

    _rows, meta = validate_paginated(api.list_agreements(admin))
    assert meta["limit"] == 10, f"limit defaults to 10, got {meta['limit']}"
    assert meta["offset"] == 0, f"offset defaults to 0, got {meta['offset']}"


def test_report_get_with_unknown_id_returns_report_not_found(api):
    """PRD §2.8: "The path identifiers used across the API are `distributorId`,
    `agreementId`, `rateCardEntryId`, `mfnClauseId`, `reportId`, `engagementId`,
    `findingId`, `titleId`, `windowId`, `blackoutRuleId`, `commitmentId`,
    `invoiceId` and `analysisId`, and each has its own not-found code:
    `ERR_DISTRIBUTOR_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`,
    `ERR_RATE_CARD_ENTRY_NOT_FOUND`, `ERR_MFN_CLAUSE_NOT_FOUND`,
    `ERR_REPORT_NOT_FOUND`, `ERR_ENGAGEMENT_NOT_FOUND`, `ERR_FINDING_NOT_FOUND`,
    `ERR_TITLE_NOT_FOUND`, `ERR_WINDOW_NOT_FOUND`, `ERR_BLACKOUT_NOT_FOUND`,
    `ERR_COMMITMENT_NOT_FOUND`, `ERR_INVOICE_NOT_FOUND` and
    `ERR_ANALYSIS_NOT_FOUND`, all HTTP 404."
    PRD §2.2: "The `error_id` is a unique, machine-readable string that
    identifies the specific error."

    Design: Corner/entities/report_get_with_unknown_id_returns_report_not_found
    """
    response = api.get_subscriber_report(NON_EXISTENT_UUID, make_revenue_accountant_headers())

    validate_error(response, ApiErrorId.ERR_REPORT_NOT_FOUND, 404)
    body = response.json()
    assert body["response_type"] == "error", "a rejection travels in the error envelope"
    assert body["meta"]["api_request_id"], "meta.api_request_id must be present on errors"
    assert body["meta"]["api_request_timestamp"], (
        "meta.api_request_timestamp must be present on errors"
    )


def test_agreement_create_missing_penetration_floor_rejected(api):
    """PRD §2.8: "Every required field of the endpoint must be present and
    non-null; enum fields must carry a declared member; integer fields must be
    integers; monetary and subscriber fields must not be negative; a
    `period_month`, `sample_period_start` or `sample_period_end` must match a
    four-digit year, a hyphen, and a two-digit month between `01` and `12`; a
    `territory_code`, `home_territory_code` or the territory of a blackout must
    be exactly two uppercase letters; a `term_end_date` at or before
    `term_start_date` is malformed; and no unknown field may be present."
    PRD §2.8: "**The first rule that fails decides the response, and no side
    effect of the requested operation fires.**"

    Design: Corner/entities/agreement_create_missing_required_field_rejected
    """
    payload = create_agreement_payload(
        NON_EXISTENT_UUID, contract_code="MB-NOFLOOR", **FLAT_TERMS
    )
    payload.pop("penetration_floor_pct")

    response = api.create_agreement(payload, make_affiliate_sales_exec_headers())
    error = validate_error(response, ApiErrorId.ERR_INVALID_REQUEST, 400)
    assert error["error_id"] != "ERR_DISTRIBUTOR_NOT_FOUND", (
        "request shape is evaluated before body-reference existence, so the "
        "unresolvable distributor_id must not decide the response"
    )

    _rows, meta = validate_paginated(
        api.list_agreements(make_network_admin_headers(), params={"limit": 10})
    )
    assert meta["total_count"] == 0, (
        f"a rejected draft creates nothing, got total_count {meta['total_count']}"
    )


def test_distributor_create_rejects_client_supplied_computed_field(api):
    """PRD §3.1: "Three of those numbers are maintained by the server and never
    written by a client."
    PRD §2.8: "Every required field of the endpoint must be present and non-null;
    enum fields must carry a declared member; integer fields must be integers;
    monetary and subscriber fields must not be negative; a `period_month`,
    `sample_period_start` or `sample_period_end` must match a four-digit year, a
    hyphen, and a two-digit month between `01` and `12`; a `territory_code`,
    `home_territory_code` or the territory of a blackout must be exactly two
    uppercase letters; a `term_end_date` at or before `term_start_date` is
    malformed; and no unknown field may be present."

    Design: Corner/entities/distributor_create_rejects_client_supplied_computed_field
    """
    admin = make_network_admin_headers()
    payload = create_distributor_payload(
        legal_name="Meridian Broadband", total_subscribers=1_500_000
    )
    payload["receivable_balance_cents"] = 999

    validate_error(api.create_distributor(payload, admin), ApiErrorId.ERR_INVALID_REQUEST, 400)

    _rows, meta = validate_paginated(api.list_distributors(admin, params={"limit": 10}))
    assert meta["total_count"] == 0, (
        f"a rejected registration creates nothing, got total_count {meta['total_count']}"
    )

    payload.pop("receivable_balance_cents")
    data = validate_success(api.create_distributor(payload, admin), 201)
    assert data["receivable_balance_cents"] == 0, (
        "the server-maintained receivable starts at zero on the legal call, got "
        f"{data['receivable_balance_cents']}"
    )


@pytest.mark.parametrize(
    "case,overrides",
    [
        ("undeclared_platform", {"platform": "MOBILE"}),
        (
            "window_end_equal_to_start",
            {
                "platform": "VOD",
                "window_start": "2026-09-01T00:00:00Z",
                "window_end": "2026-09-01T00:00:00Z",
            },
        ),
        ("territory_code_not_two_uppercase", {"platform": "VOD", "territory_code": "usa"}),
    ],
)
def test_rights_window_enum_and_range_constraints_enforced(api, case, overrides):
    """PRD §3.6: "Planning one names the `agreement_id` granting it, the
    `content_title_id` being licensed, a `platform` of `LINEAR`, `VOD`,
    `STREAMING` or `INTERNATIONAL`, a `territory_code` of exactly two uppercase
    letters, a `window_start` and a `window_end` strictly later than the start,
    and an `exclusivity` of either `EXCLUSIVE` or `NON_EXCLUSIVE`."
    PRD §2.8: "Every required field of the endpoint must be present and non-null;
    enum fields must carry a declared member; integer fields must be integers;
    monetary and subscriber fields must not be negative; a `period_month`,
    `sample_period_start` or `sample_period_end` must match a four-digit year, a
    hyphen, and a two-digit month between `01` and `12`; a `territory_code`,
    `home_territory_code` or the territory of a blackout must be exactly two
    uppercase letters; a `term_end_date` at or before `term_start_date` is
    malformed; and no unknown field may be present."

    Design: Corner/entities/rights_window_enum_and_range_constraints_enforced
    """
    _distributor, agreement = setup_draft_agreement(
        {"legal_name": "Meridian Broadband", "total_subscribers": 1_500_000}, FLAT_TERMS
    )
    title = register_title(
        title="Harbor Nights", linear_premiere_at="2026-08-15T00:00:00Z"
    )

    window_kwargs = {
        "window_start": "2026-09-01T00:00:00Z",
        "window_end": "2026-09-30T00:00:00Z",
        "exclusivity": "EXCLUSIVE",
    }
    window_kwargs.update(overrides)
    payload = create_rights_window_payload(agreement["id"], title["id"], **window_kwargs)

    validate_error(
        api.create_rights_window(payload, make_rights_administrator_headers()),
        ApiErrorId.ERR_INVALID_REQUEST,
        400,
    )

    _rows, meta = validate_paginated(
        api.list_rights_windows(
            make_rights_administrator_headers(),
            params={"content_title_id": title["id"], "limit": 10},
        )
    )
    assert meta["total_count"] == 0, (
        f"the {case} payload must create no window, got total_count {meta['total_count']}"
    )


def test_rate_card_entry_is_immutable_and_carries_no_version(api):
    """PRD §2.4: "A published rate-card row is addressable by `id` alone: it has
    no `created_at`, no `updated_at` and no `version`, and no endpoint can modify
    or delete it once published."
    PRD §3.1: "A row may also carry `min_subscribers`, defaulting to 0, below
    which an operator's `total_subscribers` is too small for the row to be
    quotable."
    PRD §3.1: "Each row states the `rate_card_class` and `tier` it prices — the
    tier being one of `BASIC`, `EXPANDED_BASIC`, `DIGITAL_TIER` or `PREMIUM` — a
    `published_rate_cents_per_sub` strictly greater than zero, an inclusive
    `effective_from` instant and an optional `effective_to` instant that is
    exclusive and must be strictly later than `effective_from` when supplied; a
    null `effective_to` means the row is open-ended."

    Design: Corner/entities/rate_card_entry_is_immutable_and_carries_no_version
    """
    admin = make_network_admin_headers()
    payload = create_rate_card_entry_payload(
        rate_card_class="CLASS_A",
        tier="EXPANDED_BASIC",
        published_rate_cents_per_sub=44.5000,
        effective_from="2026-01-01T00:00:00Z",
    )
    payload.pop("min_subscribers")
    payload.pop("effective_to")

    data = validate_success(api.create_rate_card_entry(payload, admin), 201)

    assert data["id"], "a published row is addressable by id"
    assert data["published_rate_cents_per_sub"] == pytest.approx(44.5000, abs=0.01), (
        f"published_rate_cents_per_sub must round-trip, got {data['published_rate_cents_per_sub']}"
    )
    assert data["min_subscribers"] == 0, (
        f"an omitted min_subscribers defaults to 0, got {data['min_subscribers']}"
    )
    assert data["effective_to"] is None, (
        f"an omitted effective_to leaves the row open-ended, got {data['effective_to']}"
    )
    for absent in ["version", "created_at", "updated_at"]:
        assert absent not in data, f"a published rate-card row carries no {absent}"
    assert_rate_card_entry(data)

    read_back = validate_success(api.get_rate_card_entry(data["id"], admin))
    assert read_back["id"] == data["id"], "the row reads back under the same id"
    assert read_back["published_rate_cents_per_sub"] == pytest.approx(44.5000, abs=0.01), (
        "the read returns the published rate unchanged"
    )
    for absent in ["version", "created_at", "updated_at"]:
        assert absent not in read_back, f"the read of a published row carries no {absent}"


def test_window_body_foreign_keys_checked_in_declaration_order(api):
    """PRD §2.8: "Body-supplied references are resolved after path parameters, in
    this declaration order: `distributor_id`, `agreement_id`,
    `content_title_id`, `substitute_content_title_id`, `subscriber_report_id`,
    `engagement_id`, `audit_engagement_id`, `restatement_of_report_id`."
    PRD §2.8: "Each unresolved reference produces the not-found code of the
    entity type it points at — a bad `content_title_id` or
    `substitute_content_title_id` yields `ERR_TITLE_NOT_FOUND`, a bad
    `subscriber_report_id` or `restatement_of_report_id` yields
    `ERR_REPORT_NOT_FOUND`, a bad `audit_engagement_id` or `engagement_id` yields
    `ERR_ENGAGEMENT_NOT_FOUND`."

    Design: Corner/entities/window_body_foreign_keys_checked_in_declaration_order
    """
    rights = make_rights_administrator_headers()
    _distributor, agreement = setup_draft_agreement(
        {"legal_name": "Meridian Broadband", "total_subscribers": 1_500_000}, FLAT_TERMS
    )
    bogus_title_id = "00000000-0000-4000-8000-0000000000b2"

    both_bogus = create_rights_window_payload(
        NON_EXISTENT_UUID,
        bogus_title_id,
        platform="VOD",
        window_start="2026-09-01T00:00:00Z",
        window_end="2026-09-30T00:00:00Z",
        exclusivity="NON_EXCLUSIVE",
    )
    validate_error(
        api.create_rights_window(both_bogus, rights),
        ApiErrorId.ERR_AGREEMENT_NOT_FOUND,
        404,
    )

    title_only_bogus = create_rights_window_payload(
        agreement["id"],
        bogus_title_id,
        platform="VOD",
        window_start="2026-09-01T00:00:00Z",
        window_end="2026-09-30T00:00:00Z",
        exclusivity="NON_EXCLUSIVE",
    )
    validate_error(
        api.create_rights_window(title_only_bogus, rights),
        ApiErrorId.ERR_TITLE_NOT_FOUND,
        404,
    )

    _rows, meta = validate_paginated(
        api.list_rights_windows(rights, params={"agreement_id": agreement["id"], "limit": 10})
    )
    assert meta["total_count"] == 0, (
        f"neither rejected plan created a window, got total_count {meta['total_count']}"
    )


def test_subscriber_report_create_stamps_provisional_fee_and_defaults(api):
    """PRD §3.4: "A new report opens in `SUBMITTED` with `license_fee_due_cents`
    0, `audit_adjustment_cents` 0, `invoice_id` null, `accepted_at` null and
    `version` 1, and it increments the agreement's `version` by one."
    PRD §3.4: "A filing that replaces an earlier one additionally carries
    `restatement_of_report_id`; an original filing leaves that field null."
    PRD §3.4: "`penetration_pct` is `reported_subscribers` divided by the
    operator's `total_subscribers`, rounded half up to four decimal places."
    PRD §3.4: "Under the **provisional** variant, stamped at submission into
    `provisional_fee_cents`, the billable count is `reported_subscribers`
    verbatim; the penetration floor is ignored entirely."
    PRD §3.4: "The fee is the billable subscriber count multiplied by
    `rate_applied_cents_per_sub` multiplied by that tier multiplier, rounded half
    up to a whole number of cents."

    Design: Corner/entities/subscriber_report_create_stamps_provisional_fee_and_defaults
    """
    distributor, agreement = setup_executed_agreement(CLIFFSIDE, FLAT_TERMS)

    payload = create_subscriber_report_payload(
        agreement["id"],
        agreement["version"],
        period_month="2026-06",
        reported_subscribers=130_000,
        reported_tier="BASIC",
    )
    data = validate_success(
        api.create_subscriber_report(
            payload, make_distributor_liaison_headers(distributor["id"])
        ),
        201,
    )

    assert data["status"] == "SUBMITTED", f"a new report opens SUBMITTED, got {data['status']}"
    assert data["version"] == 1, f"a new report carries version 1, got {data['version']}"
    assert data["penetration_pct"] == pytest.approx(0.6500, abs=0.01), (
        f"130,000 of 200,000 homes is a penetration of 0.6500, got {data['penetration_pct']}"
    )
    assert data["provisional_fee_cents"] == 5_200_000, (
        "the provisional fee is 130,000 reported subscribers at 40.0000 cents on a "
        f"1.00 tier multiplier, got {data['provisional_fee_cents']}"
    )
    assert data["license_fee_due_cents"] == 0, (
        f"license_fee_due_cents opens at 0, got {data['license_fee_due_cents']}"
    )
    assert data["audit_adjustment_cents"] == 0, (
        f"audit_adjustment_cents opens at 0, got {data['audit_adjustment_cents']}"
    )
    assert data["invoice_id"] is None, f"invoice_id opens null, got {data['invoice_id']}"
    assert data["accepted_at"] is None, f"accepted_at opens null, got {data['accepted_at']}"
    assert data["restatement_of_report_id"] is None, (
        f"an original filing leaves restatement_of_report_id null, got "
        f"{data['restatement_of_report_id']}"
    )
    assert_subscriber_report(data)

    after = fetch_agreement(agreement["id"])
    assert after["recognized_revenue_cents"] == 0, (
        "filing alone recognises no revenue, got "
        f"{after['recognized_revenue_cents']}"
    )
