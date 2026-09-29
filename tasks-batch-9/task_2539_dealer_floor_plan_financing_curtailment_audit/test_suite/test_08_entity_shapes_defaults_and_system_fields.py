"""Entity surface: declared defaults, the response envelope and server-stamped fields."""
from test_helpers import (
    CO,
    CRM,
    FA,
    NON_EXISTENT_UUID,
    ApiErrorId,
    api_client,
    assert_append_only_fields,
    assert_credit_line,
    assert_dealer,
    assert_identifier,
    assert_inventory_unit,
    assert_pagination_meta,
    assert_unit_audit_observation,
    assert_utc_millisecond_timestamp,
    create_credit_line,
    create_credit_line_payload,
    create_dealer,
    create_dealer_payload,
    create_unit_payload,
    credit_line_version,
    fund_advance_payload,
    make_dealer_principal_headers,
    make_vin,
    move_title_custody,
    observation_payload,
    read_credit_line,
    read_dealer,
    read_unit,
    register_unit,
    request_advance,
    schedule_audit,
    set_clock,
    setup_active_line,
    setup_floored_unit,
    start_audit,
    validate_error,
    validate_paginated,
    validate_success,
)

NEW_TIER_1000 = {
    "inventory_class": "NEW",
    "age_days_from": 90,
    "age_days_to": None,
    "cumulative_paydown_bps": 1000,
}


def test_a_new_dealership_is_onboarded_on_a_clean_slate_inside_the_declared_envelope():
    """The only four inputs come back wrapped in the success envelope with every counter at zero.

    PRD: "The new dealership lands in `PROSPECT` with a clean slate: `risk_score` 100, `risk_rating` `A`, `audit_frequency_days` 180, `next_audit_due_at` still null, `last_covenant_result` null, and `open_sot_incident_count`, `open_sot_exposure_cents`, `delinquent_unit_count`, `covenant_breach_count` and `unapplied_credit_cents` all zero, with `audit_in_progress` false."

    PRD: "The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`."

    Design: Corner/entities/dealer_creation_returns_201_with_declared_defaults_and_envelope
    """
    set_clock("2026-08-01T00:00:00Z")
    response = api_client.create_dealer(
        create_dealer_payload(
            legal_name="Corner Creation Motors LLC",
            dba_name="Corner Motors",
            franchise_type="FRANCHISE_NEW_CAR",
            state_code="TX",
        ),
        CO,
    )
    dealer = validate_success(response, 201)
    body = response.json()
    assert body["response_type"] == "object"
    assert str(body["meta"]["api_request_id"]).startswith("req_")
    assert_utc_millisecond_timestamp(
        body["meta"]["api_request_timestamp"], "meta.api_request_timestamp"
    )

    assert_dealer(dealer)
    assert dealer["status"] == "PROSPECT"
    assert dealer["risk_score"] == 100
    assert dealer["risk_rating"] == "A"
    assert dealer["audit_frequency_days"] == 180
    assert dealer["version"] == 1
    assert str(dealer["created_at"]).startswith("2026-08-01T00:00:00")
    assert str(dealer["updated_at"]).startswith("2026-08-01T00:00:00")
    assert dealer["next_audit_due_at"] is None
    assert dealer["last_covenant_result"] is None
    assert dealer["open_sot_incident_count"] == 0
    assert dealer["open_sot_exposure_cents"] == 0
    assert dealer["delinquent_unit_count"] == 0
    assert dealer["covenant_breach_count"] == 0
    assert dealer["unapplied_credit_cents"] == 0
    assert dealer["audit_in_progress"] is False
    assert dealer["legal_name"] == "Corner Creation Motors LLC"
    assert dealer["dba_name"] == "Corner Motors"
    assert dealer["franchise_type"] == "FRANCHISE_NEW_CAR"
    assert dealer["state_code"] == "TX"


def test_reading_a_dealership_back_returns_the_stored_row_without_bumping_its_version():
    """A GET hands back the same values the POST reported, and the omitted trade name is null.

    PRD: "`version` is an integer that starts at 1 when the resource is created and increases by exactly 1 on each mutation, again including cascaded ones — a dealer whose counters are rewritten by an audit reconciliation has its `version` advanced by that reconciliation just as surely as if it had been written directly."

    PRD: "The onboarding payload carries `legal_name` (the registered legal name of the borrower, between 1 and 200 characters), the optional trade name `dba_name` (absent means the stored value is null), `franchise_type` — one of `FRANCHISE_NEW_CAR`, `INDEPENDENT_USED` or `POWERSPORTS`, which partitions portfolio reporting but drives no computation — and `state_code`, exactly two uppercase letters naming the state where the dealership is licensed."

    Design: Corner/entities/dealer_retrieval_returns_the_stored_row_unchanged
    """
    set_clock("2026-08-01T00:00:00Z")
    created = create_dealer(
        legal_name="Corner Retrieval Motors LLC",
        franchise_type="POWERSPORTS",
        state_code="NV",
    )

    fetched = validate_success(api_client.get_dealer(created["id"], CRM))
    assert_dealer(fetched)
    assert fetched["id"] == created["id"]
    assert fetched["legal_name"] == "Corner Retrieval Motors LLC"
    assert fetched["franchise_type"] == "POWERSPORTS"
    assert fetched["version"] == 1
    assert fetched["dba_name"] is None
    assert fetched["state_code"] == "NV"
    assert fetched["status"] == created["status"]
    assert fetched["created_at"] == created["created_at"]

    again = validate_success(api_client.get_dealer(created["id"], CRM))
    assert again["version"] == 1


def test_the_dealer_listing_filters_by_state_and_pages_in_creation_order():
    """Two Kansas dealerships out of three, read one at a time from the second position.

    PRD: "`limit` controls page size: it defaults to 10, may be no smaller than 1 and no larger than 100."

    PRD: "Unless a specific endpoint says otherwise, collections are sorted by `created_at` ascending."

    Design: Corner/entities/dealer_listing_filters_by_state_code_and_honors_limit_and_offset
    """
    set_clock("2026-08-01T00:00:00Z")
    first_ks = create_dealer(legal_name="Corner List A Motors LLC", state_code="KS")
    other_state = create_dealer(legal_name="Corner List B Motors LLC", state_code="MO")
    second_ks = create_dealer(legal_name="Corner List C Motors LLC", state_code="KS")

    rows, meta = validate_paginated(
        api_client.list_dealers(CO, params={"state_code": "KS", "limit": 1, "offset": 1})
    )
    assert_pagination_meta(meta, limit=1, offset=1, total=2, has_more=False)
    assert len(rows) == 1
    assert rows[0]["id"] == second_ks["id"]
    assert rows[0]["legal_name"] == "Corner List C Motors LLC"
    assert other_state["id"] not in [row["id"] for row in rows]
    assert first_ks["id"] not in [row["id"] for row in rows]

    all_rows, all_meta = validate_paginated(api_client.list_dealers(CO))
    assert_pagination_meta(all_meta, limit=10, offset=0, total=3, has_more=False)
    assert [row["id"] for row in all_rows] == [
        first_ks["id"],
        other_state["id"],
        second_ks["id"],
    ]


def test_a_credit_line_read_for_an_absent_identifier_is_a_not_found_error_envelope():
    """An unknown line id is a 404 with its own code, never an empty success body.

    PRD: "Each missing referent has its own code: `ERR_DEALER_NOT_FOUND`, `ERR_CREDIT_LINE_NOT_FOUND`, `ERR_UNIT_NOT_FOUND`, `ERR_ADVANCE_NOT_FOUND`, `ERR_OBLIGATION_NOT_FOUND`, `ERR_EXCEPTION_NOT_FOUND`, `ERR_AUDIT_NOT_FOUND`, `ERR_INCIDENT_NOT_FOUND`, `ERR_REMEDY_NOT_FOUND` and `ERR_REMITTANCE_NOT_FOUND`, each HTTP 404."

    Design: Corner/entities/credit_line_retrieval_with_unknown_id_returns_not_found
    """
    set_clock("2026-08-01T00:00:00Z")
    dealer = create_dealer(legal_name="Corner Missing Line Motors LLC", state_code="OR")

    response = api_client.get_credit_line(NON_EXISTENT_UUID, CO)
    error = validate_error(response, ApiErrorId.ERR_CREDIT_LINE_NOT_FOUND, 404)
    assert response.json()["response_type"] == "error"
    assert error["message"].strip()

    rows, meta = validate_paginated(
        api_client.list_credit_lines(CO, params={"dealer_id": dealer["id"]})
    )
    assert meta["total_count"] == 0
    assert rows == []


def test_a_facility_without_its_committed_size_is_a_malformed_request():
    """Dropping the one required money field is a 400, and no line row survives the attempt.

    PRD: "**Request schema** — required fields present, enum members declared, `*_cents` and `*_bps` fields non-negative integers, every `*_bps` value no greater than 10,000, `requested_amount_cents` and `amount_cents` strictly positive, `odometer_miles` zero or greater, date fields valid ISO 8601, `limit` within 1 through 100 and `offset` zero or greater (`ERR_INVALID_REQUEST`, HTTP 400)."

    Design: Corner/entities/credit_line_creation_missing_required_credit_limit_returns_invalid_request
    """
    set_clock("2026-08-01T00:00:00Z")
    dealer = create_dealer(legal_name="Corner No Limit Motors LLC", state_code="NM")
    payload = create_credit_line_payload(dealer["id"])
    del payload["credit_limit_cents"]

    validate_error(
        api_client.create_credit_line(payload, CO),
        ApiErrorId.ERR_INVALID_REQUEST,
        400,
    )

    rows, meta = validate_paginated(
        api_client.list_credit_lines(CO, params={"dealer_id": dealer["id"]})
    )
    assert meta["total_count"] == 0
    assert rows == []
    unchanged = read_dealer(dealer["id"])
    assert unchanged["status"] == "PROSPECT"
    assert unchanged["version"] == 1


def test_omitted_optional_inputs_fall_back_to_the_values_the_contract_declares():
    """A facility with no grace period stated gets ten days, and a unit with no odometer gets zero.

    PRD: "`curtailment_grace_days` is optional, must lie between 0 and 30 inclusive, and when the payload omits it the line is created with a grace period of 10 days."

    PRD: "The payload carries `dealer_id`, which must equal the caller's `X-User-ID`, and `credit_line_id`, which must name a line belonging to that dealership; it carries `vin`, exactly 17 uppercase alphanumeric characters; `inventory_class`; `invoice_amount_cents`, strictly positive, being the manufacturer or acquisition invoice amount that forms the advance basis before capping; `invoice_date`, the invoice issue instant that later drives both the aged-invoice rate reduction and the maximum-age gate; the optional `odometer_miles`, which defaults to 0 when omitted and may not be negative; and `title_document_type`, either `MSO` or `TITLE`."

    PRD: "A registered unit starts in `funding_status` `REGISTERED`, `title_custody_status` `NOT_RECEIVED` and `eligibility_status` `ELIGIBLE`, with `ineligibility_reason_code` null, `advance_amount_cents`, `outstanding_principal_cents`, `principal_paid_cents`, `aging_exception_count` and `curtailment_extension_days_total` all zero, `floored_at` and `funded_by_user_id` null, and `version` 1."

    Design: Corner/entities/omitted_optional_inputs_fall_back_to_declared_defaults
    """
    set_clock("2026-08-01T00:00:00Z")
    dealer = create_dealer(legal_name="Corner Defaults Motors LLC", state_code="IA")
    line_payload = create_credit_line_payload(dealer["id"])
    del line_payload["curtailment_grace_days"]
    line = validate_success(api_client.create_credit_line(line_payload, CO), 201)
    assert_credit_line(line)
    assert line["curtailment_grace_days"] == 10

    validate_success(
        api_client.create_curtailment_tier(
            line["id"],
            {
                "inventory_class": "NEW",
                "age_days_from": 90,
                "age_days_to": None,
                "cumulative_paydown_bps": 1000,
            },
            CO,
        ),
        201,
    )
    validate_success(api_client.activate_credit_line(line["id"], CO))

    unit_payload = create_unit_payload(
        dealer["id"], line["id"], make_vin("CRNDEFAULTUNIT01")
    )
    del unit_payload["odometer_miles"]
    unit = validate_success(
        api_client.create_unit(unit_payload, make_dealer_principal_headers(dealer["id"])),
        201,
    )
    assert_inventory_unit(unit)
    assert unit["odometer_miles"] == 0
    assert unit["funding_status"] == "REGISTERED"
    assert unit["title_custody_status"] == "NOT_RECEIVED"
    assert unit["eligibility_status"] == "ELIGIBLE"
    assert unit["advance_amount_cents"] == 0
    assert unit["principal_paid_cents"] == 0
    assert unit["floored_at"] is None
    assert unit["funded_by_user_id"] is None


def test_the_disbursed_figure_is_computed_and_never_copied_from_the_dealer_request():
    """A dealership asking for five million against a three million invoice is paid three million.

    PRD: "A `DealerPrincipal` opens the request against a unit that is still `REGISTERED`, supplying `requested_amount_cents` (strictly positive — the amount the dealership would like to draw, which is informational only, because the amount actually disbursed is always the computed advance) and `dealer_invoice_reference` (the dealership's own invoice or purchase-order reference)."

    Design: Corner/entities/advance_funding_ignores_the_client_supplied_requested_amount
    """
    ctx = setup_active_line(tiers=[NEW_TIER_1000])
    line_id = ctx["credit_line"]["id"]
    unit = register_unit(
        ctx["dealer"]["id"],
        line_id,
        "CRNIGNOREREQ0001",
        dealer_headers=ctx["dealer_headers"],
        invoice_amount_cents=3000000,
    )
    move_title_custody(unit["id"], "LENDER_HELD", "MSO-C7")
    requested = request_advance(unit["id"], ctx["dealer_headers"], 5000000, "INV-C7")
    assert requested["requested_amount_cents"] == 5000000
    assert requested["approved_advance_amount_cents"] == 0

    funded = validate_success(
        api_client.fund_advance(
            requested["id"],
            fund_advance_payload(credit_line_version(line_id), "WIRE-C7"),
            CO,
        )
    )
    assert funded["approved_advance_amount_cents"] == 3000000
    assert funded["effective_advance_rate_bps"] == 10000
    assert funded["invoice_age_days_at_funding"] == 0
    assert funded["requested_amount_cents"] == 5000000
    assert funded["funded_by_user_id"] == CO["X-User-ID"]
    assert str(funded["funded_at"]).startswith("2026-08-01T00:00:00")

    unit_after = read_unit(unit["id"])
    assert unit_after["advance_amount_cents"] == 3000000
    assert unit_after["outstanding_principal_cents"] == 3000000
    line = read_credit_line(line_id)
    assert line["outstanding_principal_cents"] == 3000000
    assert line["available_credit_cents"] == 497000000


def test_identifiers_and_timestamps_are_minted_by_the_server_on_every_write():
    """Creation stamps created_at once; the later activation moves only updated_at and version.

    PRD: "Every persisted resource exposes a server-minted `id` — a UUID with no type prefix of any kind."

    PRD: "`created_at` is fixed at insertion."

    Design: Corner/entities/system_stamped_ids_and_timestamps_are_server_generated_on_every_write
    """
    set_clock("2026-08-01T00:00:00Z")
    first_dealer = create_dealer(legal_name="Corner System Fields One LLC", state_code="MN")
    second_dealer = create_dealer(legal_name="Corner System Fields Two LLC", state_code="MN")
    first_line = create_credit_line(first_dealer["id"])
    second_line = create_credit_line(second_dealer["id"])
    assert_identifier(first_line["id"], "CreditLine.id")
    assert_identifier(second_line["id"], "CreditLine.id")
    assert first_line["id"] != second_line["id"]
    assert str(first_line["created_at"]).startswith("2026-08-01T00:00:00")
    assert str(first_line["updated_at"]).startswith("2026-08-01T00:00:00")
    assert first_line["version"] == 1

    validate_success(
        api_client.create_curtailment_tier(
            first_line["id"],
            {
                "inventory_class": "NEW",
                "age_days_from": 90,
                "age_days_to": None,
                "cumulative_paydown_bps": 1000,
            },
            CO,
        ),
        201,
    )
    set_clock("2026-08-08T00:00:00Z")
    activated = validate_success(api_client.activate_credit_line(first_line["id"], CO))
    assert str(activated["created_at"]).startswith("2026-08-01T00:00:00")
    assert str(activated["updated_at"]).startswith("2026-08-08T00:00:00")
    assert str(activated["activated_at"]).startswith("2026-08-08T00:00:00")
    assert activated["version"] == 2
    assert read_credit_line(second_line["id"])["version"] == 1


def test_a_physical_reading_is_frozen_at_creation_and_carries_no_version():
    """The observation exposes id and created_at only, and the odometer it records never re-prices.

    PRD: "Three resources are deliberately immutable and therefore carry only `id` and `created_at`, with **no** `updated_at` and **no** `version` field at all: `CurtailmentTier` (a configuration rung of a ladder), `UnitAuditObservation` (a physical count reading, which by design cannot be corrected — a mistake is superseded by scheduling another audit, never by editing the row) and `CovenantTest` (a filed financial certification)."

    PRD: "The payload names `unit_id`, `observed_condition`, `title_verified`, and optionally `odometer_miles` and `sale_contract_reference` — the odometer reading is kept for the audit trail only and never re-prices an advance, and the sale contract reference is the retail buyer's order the dealership produces for a unit it has sold."

    Design: Corner/entities/unit_audit_observation_is_immutable_and_exposes_no_version_field
    """
    ctx = setup_floored_unit(
        tiers=[NEW_TIER_1000],
        vin_seed="CRNIMMUTABLEUNT1",
        unit_overrides={"invoice_amount_cents": 3000000, "odometer_miles": 12},
    )
    unit_id = ctx["unit"]["id"]
    audit = schedule_audit(
        ctx["dealer"]["id"], "2026-08-01", "2026-08-03", audit_type="UNANNOUNCED"
    )
    start_audit(audit["id"])

    observation = validate_success(
        api_client.record_observation(
            audit["id"],
            observation_payload(unit_id, "PRESENT", True, odometer_miles=14),
            FA,
        ),
        201,
    )
    assert_unit_audit_observation(observation)
    assert_append_only_fields(observation, "UnitAuditObservation")
    assert observation["classification"] == "VERIFIED"
    assert observation["is_out_of_trust"] is False
    assert observation["observed_by_user_id"] == FA["X-User-ID"]
    assert observation["unit_outstanding_principal_cents_at_observation"] == 3000000
    assert_utc_millisecond_timestamp(observation["created_at"], "created_at")
    assert str(observation["created_at"]).startswith("2026-08-01T00:00:00")

    rows, meta = validate_paginated(api_client.list_audit_observations(audit["id"], CO))
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [observation["id"]]
    assert rows[0]["classification"] == "VERIFIED"

    unit_after = read_unit(unit_id)
    assert unit_after["funding_status"] == "FLOORED"
    assert unit_after["odometer_miles"] == 12


def test_an_inventory_class_outside_the_declared_enumeration_is_refused():
    """CERTIFIED_PREOWNED is not a member, and the same payload with USED is accepted.

    PRD: "`NEW` inventory must present a manufacturer statement of origin, so `title_document_type` must be `MSO`; `USED` inventory must present a certificate of title, so it must be `TITLE`; `DEMONSTRATOR` inventory accepts either."

    PRD: "**Request schema** — required fields present, enum members declared, `*_cents` and `*_bps` fields non-negative integers, every `*_bps` value no greater than 10,000, `requested_amount_cents` and `amount_cents` strictly positive, `odometer_miles` zero or greater, date fields valid ISO 8601, `limit` within 1 through 100 and `offset` zero or greater (`ERR_INVALID_REQUEST`, HTTP 400)."

    Design: Corner/entities/unit_creation_with_an_undeclared_inventory_class_returns_invalid_request
    """
    ctx = setup_active_line(
        tiers=[NEW_TIER_1000],
        dealer_overrides={
            "legal_name": "Corner Enum Motors LLC",
            "franchise_type": "INDEPENDENT_USED",
            "state_code": "NE",
        },
    )
    dealer_id = ctx["dealer"]["id"]
    line_id = ctx["credit_line"]["id"]
    vin = make_vin("CRNBADENUMUNIT01")

    validate_error(
        api_client.create_unit(
            create_unit_payload(
                dealer_id,
                line_id,
                vin,
                inventory_class="CERTIFIED_PREOWNED",
                invoice_amount_cents=2000000,
                title_document_type="TITLE",
            ),
            ctx["dealer_headers"],
        ),
        ApiErrorId.ERR_INVALID_REQUEST,
        400,
    )

    rows, meta = validate_paginated(
        api_client.list_units(CO, params={"dealer_id": dealer_id})
    )
    assert meta["total_count"] == 0
    assert rows == []

    accepted = validate_success(
        api_client.create_unit(
            create_unit_payload(
                dealer_id,
                line_id,
                vin,
                inventory_class="USED",
                invoice_amount_cents=2000000,
                title_document_type="TITLE",
            ),
            ctx["dealer_headers"],
        ),
        201,
    )
    assert_inventory_unit(accepted)
    assert accepted["inventory_class"] == "USED"
    assert accepted["vin"] == vin


def test_registering_against_a_facility_that_does_not_exist_is_a_not_found():
    """The dealership resolves but the named line does not, so the write is refused as 404.

    PRD: "The payload carries `dealer_id`, which must equal the caller's `X-User-ID`, and `credit_line_id`, which must name a line belonging to that dealership; it carries `vin`, exactly 17 uppercase alphanumeric characters; `inventory_class`; `invoice_amount_cents`, strictly positive, being the manufacturer or acquisition invoice amount that forms the advance basis before capping; `invoice_date`, the invoice issue instant that later drives both the aged-invoice rate reduction and the maximum-age gate; the optional `odometer_miles`, which defaults to 0 when omitted and may not be negative; and `title_document_type`, either `MSO` or `TITLE`."

    PRD: "**Existence** — path segments and body references are resolved strictly left to right along the URL, and then left to right through the body in the order the endpoint declares its inputs. Each missing referent has its own code: `ERR_DEALER_NOT_FOUND`, `ERR_CREDIT_LINE_NOT_FOUND`, `ERR_UNIT_NOT_FOUND`, `ERR_ADVANCE_NOT_FOUND`, `ERR_OBLIGATION_NOT_FOUND`, `ERR_EXCEPTION_NOT_FOUND`, `ERR_AUDIT_NOT_FOUND`, `ERR_INCIDENT_NOT_FOUND`, `ERR_REMEDY_NOT_FOUND` and `ERR_REMITTANCE_NOT_FOUND`, each HTTP 404."

    Design: Corner/entities/unit_creation_naming_an_unknown_credit_line_returns_not_found
    """
    ctx = setup_active_line(
        tiers=[NEW_TIER_1000],
        dealer_overrides={
            "legal_name": "Corner Parent Motors LLC",
            "franchise_type": "FRANCHISE_NEW_CAR",
            "state_code": "SD",
        },
    )
    dealer_id = ctx["dealer"]["id"]
    line_id = ctx["credit_line"]["id"]

    validate_error(
        api_client.create_unit(
            create_unit_payload(
                dealer_id,
                NON_EXISTENT_UUID,
                make_vin("CRNPARENTUNIT001"),
                invoice_amount_cents=3000000,
            ),
            ctx["dealer_headers"],
        ),
        ApiErrorId.ERR_CREDIT_LINE_NOT_FOUND,
        404,
    )

    rows, meta = validate_paginated(
        api_client.list_units(CO, params={"credit_line_id": line_id})
    )
    assert meta["total_count"] == 0
    assert rows == []
    assert read_credit_line(line_id)["outstanding_principal_cents"] == 0
