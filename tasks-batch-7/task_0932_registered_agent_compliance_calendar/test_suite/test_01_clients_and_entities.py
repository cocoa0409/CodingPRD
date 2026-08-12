"""Portfolio owners, legal entities, jurisdiction rules and the leaner resources."""
from test_helpers import (
    ApiErrorId,
    DE_RULE_LISTING,
    DE_RULE_MIN,
    DE_RULE_MIN_DISSOLUTION,
    NY_RULE_LISTING,
    TX_RULE_LISTING,
    TX_RULE_MIN,
    UNKNOWN_UUID,
    UNKNOWN_UUID_ALT,
    UNKNOWN_UUID_THIRD,
    ADMIN,
    OFFICER,
    accept_appointment,
    activate_registration,
    propose_appointment,
    assert_allocation_split,
    assert_client,
    assert_lean_resource,
    assert_legal_entity,
    assert_payment_identity,
    capture,
    create_legal_entity_payload,
    draft_standalone_filing,
    is_valid_uuid,
    new_client,
    new_certificate,
    new_entity,
    new_home_registration,
    new_obligation,
    new_payment,
    publish_rule,
    read_client,
    read_filing,
    setup_pending_home_registration,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_new_client_returns_every_rollup_at_its_declared_starting_value(api):
    """PRD §3.1: "The new client is created with every rollup field at its declared
    starting value: `credit_balance_cents` 0, `portfolio_entity_count` 0,
    `portfolio_open_obligation_count` 0, `portfolio_outstanding_cents` 0,
    `portfolio_delinquency_status` `CURRENT`, `sop_open_escalation_count` 0 and
    `portfolio_risk_flag` false."
    PRD §2.4: "`version` is an integer that starts at 1 when the row is created and
    increases by exactly 1 on every mutation of that row, including mutations the row
    undergoes as a side effect of an operation addressed at some other resource."

    Design: Corner/entities/corner_client_creation_returns_declared_defaults
    """
    created = new_client()
    data = validate_success(api.get_client(created["id"], ADMIN))

    assert_client(data)
    assert data["credit_balance_cents"] == 0
    assert data["portfolio_entity_count"] == 0
    assert data["portfolio_open_obligation_count"] == 0
    assert data["portfolio_outstanding_cents"] == 0
    assert data["portfolio_delinquency_status"] == "CURRENT"
    assert data["sop_open_escalation_count"] == 0
    assert data["portfolio_risk_flag"] is False
    assert data["version"] == 1, "version starts at 1 when the row is created"


def test_unknown_client_id_returns_client_not_found(api):
    """PRD §2.9: "the `{id}` segment under the clients path resolves to an existing
    `Client`. Applies to every path of the form `/clients/{id}...`. Failure returns
    `ERR_CLIENT_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/corner_client_not_found_returns_client_not_found
    """
    new_client()

    response = api.get_client(UNKNOWN_UUID, ADMIN)

    assert response.status_code == 404
    validate_error(response, ApiErrorId.ERR_CLIENT_NOT_FOUND.value)


def test_legal_entity_without_formation_date_is_rejected(api):
    """PRD §3.1: "Creation requires a `legal_name` (non-empty, at most 200 characters),
    an `entity_type` drawn from `LLC`, `CORP`, `LP`, `LLP` and `NONPROFIT`, a
    `home_state_code` of exactly two uppercase letters naming the formation
    jurisdiction, and a `formation_date` as an ISO date."
    PRD §2.9: "all required body fields are present, non-null and of their declared
    type; numeric fields honour their declared ranges; `limit` lies between 1 and 100
    inclusive and `offset` is zero or greater. Applies to every endpoint. Failure
    returns `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/corner_legal_entity_missing_required_field_returns_invalid_request
    """
    client = new_client()

    response = api.create_legal_entity(
        client["id"],
        {
            "legal_name": "Northwind Widgets LLC",
            "entity_type": "LLC",
            "home_state_code": "DE",
        },
        OFFICER,
    )

    assert response.status_code == 400
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)

    rows, meta = validate_paginated(api.list_client_legal_entities(client["id"], ADMIN))
    assert meta["total_count"] == 0, "a rejected creation writes no row"
    assert rows == []


def test_legal_entity_optional_fields_take_their_declared_defaults(api):
    """PRD §3.1: "Seven further fields are optional and take concrete server-side
    defaults when omitted: `fiscal_year_end_month` defaults to 12 and must lie between
    1 and 12; `fiscal_year_end_day` defaults to 31, must lie between 1 and 31, and is
    clamped downward to the length of whatever month it is applied to;
    `authorized_shares` defaults to 0 and may not be negative; `issued_shares` defaults
    to 0, may not be negative, and may not exceed `authorized_shares`;
    `total_gross_assets_cents` defaults to 0 and may not be negative;
    `annual_gross_receipts_cents` defaults to 0 and may not be negative; and
    `boi_exempt_class` defaults to `NONE` and is drawn from `NONE`, `LARGE_OPERATING`,
    `PUBLICLY_TRADED`, `BANK` and `TAX_EXEMPT`."
    PRD §3.1: "`compliance_posture` starts at `CURRENT` and `final_report_required`
    starts at false."

    Design: Corner/entities/corner_legal_entity_optional_fields_take_declared_defaults
    """
    client = new_client()

    data = validate_success(
        api.create_legal_entity(client["id"], create_legal_entity_payload(), OFFICER),
        201,
    )

    assert_legal_entity(data)
    assert data["fiscal_year_end_month"] == 12
    assert data["fiscal_year_end_day"] == 31
    assert data["authorized_shares"] == 0
    assert data["issued_shares"] == 0
    assert data["total_gross_assets_cents"] == 0
    assert data["annual_gross_receipts_cents"] == 0
    assert data["boi_exempt_class"] == "NONE"
    assert data["lifecycle_status"] == "DRAFT"
    assert data["compliance_posture"] == "CURRENT"
    assert data["final_report_required"] is False


def test_entity_creation_derives_its_beneficial_ownership_fields(api):
    """PRD §3.1: "At creation the server also derives `company_applicant_required`,
    which is true exactly when `formation_date` falls on or after the company-applicant
    cutover date of `2024-01-01` and false otherwise, and derives the entity's initial
    beneficial-ownership deadline."
    PRD §3.10: "an entity formed on or after `2025-01-01` gets `formation_date` plus 30
    calendar days."

    Design: Corner/entities/corner_legal_entity_boi_fields_are_computed_at_creation
    """
    client = new_client()

    # formation_date 2026-02-10 sits in the 30-day band: 2026-02-10 + 30 days is
    # 2026-03-12 (18 days left in February 2026, then 12 more into March).
    data = validate_success(
        api.create_legal_entity(
            client["id"],
            create_legal_entity_payload(formation_date="2026-02-10"),
            OFFICER,
        ),
        201,
    )

    assert data["boi_initial_deadline"] == "2026-03-12"
    assert data["company_applicant_required"] is True
    assert data["boi_status"] == "PENDING_INITIAL"
    assert data["boi_update_deadline"] is None


def test_published_rule_is_server_minted_and_left_open(api):
    """PRD §2.6: "The new row is created with `effective_to` null, and the row that was
    previously open for that same `state_code` has its `effective_to` stamped with the
    new row's `effective_from`, closing it."
    PRD §2.4: "Every resource carries a server-minted `id`, which is a UUID string with
    no type prefix of any kind."

    Design: Corner/entities/corner_state_rule_system_fields_are_server_minted
    """
    payload = dict(DE_RULE_MIN)
    payload.update(
        {
            "grace_days": 30,
            "grace_basis": "CALENDAR_DAYS",
            "late_fee_style": "FLAT",
            "late_fee_flat_cents": 20000,
        }
    )

    data = validate_success(api.create_state_rule(payload, ADMIN), 201)

    assert data["effective_to"] is None
    assert data["version"] == 1
    assert data["state_code"] == "DE"
    assert is_valid_uuid(data["id"]), "the id is a bare UUID"
    assert "_" not in data["id"], "the id carries no type prefix of any kind"


def test_unknown_entity_type_routes_to_the_enum_rung(api):
    """PRD §2.9: "every enum-valued body field carries a declared member. This rung
    routes exactly these fields and no others: `entity_type` and `boi_exempt_class` on a
    legal entity, `owner_status` on a beneficial owner, `annual_report_basis`,
    `franchise_tax_basis`, `grace_basis` and `late_fee_style` on a jurisdiction rule,
    `obligation_type` on a compliance obligation, `filing_kind` and `expedite_tier` on a
    filing, `sop_class` on a service-of-process document, `report_kind` on a BOI report,
    `result` on a name clearance, and the `outcome` field on the two outcome-recording
    endpoints."
    PRD §2.9: "Failure returns `ERR_INVALID_ENUM` (HTTP 422)."

    Design: Corner/entities/corner_legal_entity_invalid_entity_type_returns_invalid_enum
    """
    client = new_client()

    response = api.create_legal_entity(
        client["id"], create_legal_entity_payload(entity_type="S_CORP"), OFFICER
    )

    assert response.status_code == 422
    validate_error(response, ApiErrorId.ERR_INVALID_ENUM.value)


def test_state_rule_listing_pages_and_reports_its_totals(api):
    """PRD §2.3: "List responses populate four fields inside `meta`: `limit` and
    `offset` echo the effective values actually applied, `total_count` reports how many
    rows matched the filters before the page window was applied, and `has_more` is true
    exactly when the sum of `offset` and the number of rows returned in this page is
    less than `total_count`."

    Design: Corner/entities/corner_state_rules_listing_is_paginated
    """
    publish_rule(DE_RULE_LISTING)
    publish_rule(TX_RULE_LISTING)
    publish_rule(NY_RULE_LISTING)

    rows, meta = validate_paginated(
        api.list_state_rules(ADMIN, params={"limit": 2, "offset": 0})
    )

    assert len(rows) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True
    assert meta["limit"] == 2
    assert meta["offset"] == 0


def test_limit_above_one_hundred_is_a_malformed_request(api):
    """PRD §2.3: "A `limit` below 1 or above 100, or a negative `offset`, is a
    malformed request and is rejected with `ERR_INVALID_REQUEST` and HTTP 400."

    Design: Corner/entities/corner_pagination_limit_out_of_range_returns_invalid_request
    """
    publish_rule(
        {
            "state_code": "DE",
            "effective_from": "2026-01-01",
            "annual_report_basis": "FIXED_CALENDAR_DATE",
            "fixed_due_month": 3,
            "fixed_due_day": 1,
            "franchise_tax_basis": "FLAT",
            "flat_franchise_tax_cents": 0,
        }
    )

    response = api.list_state_rules(ADMIN, params={"limit": 101})

    assert response.status_code == 400
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_owner_under_an_unknown_entity_returns_legal_entity_not_found(api):
    """PRD §2.9: "the `{id}` segment under the legal-entities path resolves to an
    existing `LegalEntity`. Applies to every path of the form `/legal-entities/{id}...`.
    Failure returns `ERR_LEGAL_ENTITY_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/corner_beneficial_owner_requires_existing_parent_entity
    """
    new_client()

    response = api.create_beneficial_owner(
        UNKNOWN_UUID_ALT,
        {
            "full_name": "Ada Mercer",
            "date_of_birth": "1980-04-02",
            "residential_address": "12 Pier Rd",
            "id_document_number": "P4471190",
            "ownership_pct": 40,
        },
        OFFICER,
    )

    assert response.status_code == 404
    validate_error(response, ApiErrorId.ERR_LEGAL_ENTITY_NOT_FOUND.value)


def test_qualification_naming_an_unknown_clearance_returns_record_not_found(api):
    """PRD §2.9: "a body-supplied `name_clearance_id`, `good_standing_certificate_id`,
    `reinstatement_case_id` or `target_filing_id` resolves to an existing row."
    PRD §2.9: "Failure returns `ERR_RECORD_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/corner_foreign_qualification_with_unknown_name_clearance_returns_record_not_found
    """
    publish_rule(DE_RULE_MIN)
    publish_rule(TX_RULE_MIN)
    client = new_client()
    entity = new_entity(client["id"])
    registration = new_home_registration(entity["id"])
    appointment = propose_appointment(registration)
    accept_appointment(appointment["id"])
    activate_registration(registration["id"])
    certificate = new_certificate(registration["id"])

    response = api.create_foreign_qualification(
        entity["id"],
        {
            "state_code": "TX",
            "name_clearance_id": UNKNOWN_UUID_THIRD,
            "good_standing_certificate_id": certificate["id"],
        },
        OFFICER,
    )

    assert response.status_code == 404
    validate_error(response, ApiErrorId.ERR_RECORD_NOT_FOUND.value)

    rows, meta = validate_paginated(
        api.list_registrations(ADMIN, params={"legal_entity_id": entity["id"]})
    )
    assert meta["total_count"] == 1, "no registration row is written by the rejection"
    assert len(rows) == 1


def test_allocation_rows_are_append_only_and_carry_no_version(api):
    """PRD §3.8: "Allocation rows carry `id` and `created_at` only — they have no
    `updated_at` and no `version`, because an allocation is never edited; a compensation
    is expressed by writing a new row with `is_reversal` true, never by amending an old
    one."
    PRD §3.8: "Otherwise a `PaymentAllocation` row is created recording `payment_id`,
    `filing_id`, `amount_cents` equal to the amount placed, a `sequence_index` equal to
    the current counter value, and `is_reversal` false."

    Design: Corner/entities/corner_payment_allocation_is_append_only_with_no_update_endpoint
    """
    scene = setup_pending_home_registration(DE_RULE_MIN_DISSOLUTION)
    filing = draft_standalone_filing(scene["registration"]["id"], "DISSOLUTION")
    payment = new_payment(scene["client"]["id"], 9800)

    capture(payment["id"], 9800)

    rows, meta = validate_paginated(api.list_payment_allocations(payment["id"], ADMIN))
    assert meta["total_count"] == 1
    row = rows[0]
    assert_lean_resource(row, "PaymentAllocation")
    # state_portion_cents is 9800 * 4900 / 9800 = 4900; the service half is the
    # remainder 9800 - 4900 = 4900.
    assert row["amount_cents"] == 9800
    assert row["state_portion_cents"] == 4900
    assert row["service_portion_cents"] == 4900
    assert row["sequence_index"] == 0
    assert row["is_reversal"] is False
    assert_allocation_split(row)

    filing_rows, filing_meta = validate_paginated(
        api.list_filing_allocations(filing["id"], ADMIN)
    )
    assert filing_meta["total_count"] == 1
    assert filing_rows[0]["id"] == row["id"]
    assert read_filing(filing["id"])["paid_amount_cents"] == 9800


def test_client_rollup_is_visible_on_the_very_next_read(api):
    """PRD §2.11: "Every one of these rollups is recomputed at the end of every mutation
    that touches an obligation, a registration or a legal entity — not lazily on read,
    and not only on the ops-run."
    PRD §2.11: "`portfolio_open_obligation_count` is the number of obligations in one of
    the four open statuses across every registration of every legal entity of the
    client; `portfolio_outstanding_cents` is the sum of `total_due_cents` over exactly
    those same rows; and `portfolio_entity_count` is the number of the client's legal
    entities whose `lifecycle_status` is anything other than `DISSOLVED`."

    Design: Corner/consistency_model/corner_rollup_is_immediately_visible_in_the_creating_response
    """
    scene = setup_pending_home_registration(DE_RULE_MIN)

    obligation = new_obligation(scene["registration"]["id"], "ANNUAL_REPORT", 2027)

    # state_fee_cents 5000 + franchise_tax_cents 0 + late_fee_cents 0 +
    # service_fee_cents 4900 = 9900, with no ops-run in between.
    assert obligation["total_due_cents"] == 9900

    data = read_client(scene["client"]["id"])
    assert data["portfolio_open_obligation_count"] == 1
    assert data["portfolio_outstanding_cents"] == 9900
    assert data["portfolio_entity_count"] == 1
    assert data["portfolio_delinquency_status"] == "CURRENT"
