"""Entity surface: envelopes, seeded fields, defaults, listings and typed 404s."""
from test_helpers import (
    NON_EXISTENT_UUID,
    api_client,
    create_advisor_agreement_payload,
    create_advisor_payload,
    create_booking_payload,
    create_consortium_payload,
    compliance,
    controller,
    eo_policy_credential_payload,
    is_iso8601_timestamp,
    is_valid_uuid,
    list_client_ledger,
    make_advisor_headers,
    new_advisor,
    new_client,
    new_split_schedule,
    new_supplier,
    ops,
    read_advisor,
    read_client,
    read_credential,
    setup_active_advisor,
    trust_ledger_entry_payload,
    training_cert_credential_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

NORTHWIND = {
    "name": "Northwind Tours",
    "accreditation_scheme": "IATA",
    "base_commission_pct": 0.10,
    "preferred_override_commission_pct": 0.12,
    "rate_ceiling_pct": 0.20,
    "max_commission_per_booking_cents": 2_000_000,
    "remit_terms_days": 30,
}


def test_onboarding_an_advisor_seeds_every_accumulator_at_zero():
    """PRD §3.2: "At this point `trust_account_required` is derived from the home state as
    described in §2.12, `status` is `DRAFT`, and every accumulator on the row starts empty:
    `production_ytd_provisional_cents`, `production_ytd_final_cents`,
    `eo_coverage_verified_cents`, `lifetime_settled_share_cents`,
    `lifetime_chargeback_cents` and `carryforward_chargeback_cents` at 0,
    `split_tier_provisional` and `split_tier_final` at 1, and `activated_by_user_id`,
    `departure_effective_date` and `transition_advisor_id` all null."

    Design: Corner/entities/corner_advisor_creation_returns_envelope_and_seeded_fields
    """
    response = api_client.create_advisor(
        create_advisor_payload(
            legal_name="Dana Reyes",
            email="dana.reyes@example.com",
            seller_of_travel_state="NY",
        ),
        ops(),
    )
    advisor = validate_success(response, 201)

    body = response.json()
    assert body["response_type"] == "object"
    assert body["meta"]["api_request_id"].startswith("req_")
    assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])

    assert is_valid_uuid(advisor["id"])
    assert advisor["version"] == 1
    assert advisor["status"] == "DRAFT"
    assert advisor["legal_name"] == "Dana Reyes"
    assert advisor["email"] == "dana.reyes@example.com"
    assert advisor["seller_of_travel_state"] == "NY"
    assert advisor["production_ytd_provisional_cents"] == 0
    assert advisor["production_ytd_final_cents"] == 0
    assert advisor["lifetime_settled_share_cents"] == 0
    assert advisor["lifetime_chargeback_cents"] == 0
    assert advisor["carryforward_chargeback_cents"] == 0
    assert advisor["consortium_id"] is None
    assert advisor["transition_advisor_id"] is None


def test_reading_a_supplier_returns_the_stored_rate_card_and_empty_buckets():
    """PRD §3.1: "A freshly registered supplier has `chargeback_count`, all four aging
    buckets — `aging_0_30_cents`, `aging_31_60_cents`, `aging_61_90_cents` and
    `aging_over_90_cents` — and `total_outstanding_cents` all at 0."

    Design: Corner/entities/corner_supplier_retrieval_returns_stored_row
    """
    created = new_supplier(**NORTHWIND)

    response = api_client.get_supplier(created["id"], ops())
    supplier = validate_success(response)

    assert response.json()["response_type"] == "object"
    assert supplier["id"] == created["id"]
    assert supplier["base_commission_pct"] == 0.10
    assert supplier["rate_ceiling_pct"] == 0.20
    assert supplier["max_commission_per_booking_cents"] == 2_000_000
    assert supplier["aging_0_30_cents"] == 0
    assert supplier["aging_31_60_cents"] == 0
    assert supplier["aging_61_90_cents"] == 0
    assert supplier["aging_over_90_cents"] == 0
    assert supplier["total_outstanding_cents"] == 0
    assert supplier["chargeback_count"] == 0


def test_advisor_listing_paginates_and_filters_on_the_home_state():
    """PRD §2.3: "The `meta` block of a list response carries `limit` and `offset` as
    applied, `total_count` as the number of rows matching the filters before pagination, and
    `has_more` as a boolean stating whether any further rows exist beyond the returned page."

    Design: Corner/entities/corner_advisor_listing_pagination_and_filter
    """
    new_advisor(
        legal_name="Dana Reyes",
        email="dana.reyes@example.com",
        seller_of_travel_state="NY",
    )
    new_advisor(
        legal_name="Sam Ortiz",
        email="sam.ortiz@example.com",
        seller_of_travel_state="NY",
    )
    third = new_advisor(
        legal_name="Priya Nair",
        email="priya.nair@example.com",
        seller_of_travel_state="CA",
    )

    rows, meta = validate_paginated(
        api_client.list_advisors(ops(), {"limit": 2, "offset": 0})
    )
    assert len(rows) == 2
    assert meta["total_count"] == 3
    assert meta["limit"] == 2
    assert meta["offset"] == 0
    assert meta["has_more"] is True

    rows, meta = validate_paginated(
        api_client.list_advisors(ops(), {"limit": 2, "offset": 2})
    )
    assert [row["id"] for row in rows] == [third["id"]]
    assert meta["total_count"] == 3
    assert meta["offset"] == 2
    assert meta["has_more"] is False

    rows, meta = validate_paginated(
        api_client.list_advisors(ops(), {"seller_of_travel_state": "CA"})
    )
    assert [row["id"] for row in rows] == [third["id"]]
    assert meta["total_count"] == 1

    rows, meta = validate_paginated(api_client.list_advisors(ops()))
    assert len(rows) == 3
    assert meta["limit"] == 10


def test_each_collection_reports_its_own_not_found_identifier():
    """PRD §2.8: "The identifier reported names the missing kind:
    `ERR_ADVISOR_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`, `ERR_CREDENTIAL_NOT_FOUND`,
    `ERR_SUPPLIER_NOT_FOUND`, `ERR_CONSORTIUM_NOT_FOUND`, `ERR_SPLIT_SCHEDULE_NOT_FOUND`,
    `ERR_CLIENT_NOT_FOUND`, `ERR_BOOKING_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`,
    `ERR_SETTLEMENT_RUN_NOT_FOUND` or `ERR_STATEMENT_NOT_FOUND`."

    Design: Corner/entities/corner_not_found_ids_return_typed_404s
    """
    advisor_error = validate_error(
        api_client.get_advisor(NON_EXISTENT_UUID, ops()), "ERR_ADVISOR_NOT_FOUND", 404
    )
    assert advisor_error["message"]

    validate_error(
        api_client.get_supplier(NON_EXISTENT_UUID, ops()), "ERR_SUPPLIER_NOT_FOUND", 404
    )

    response = api_client.get_booking(NON_EXISTENT_UUID, ops())
    validate_error(response, "ERR_BOOKING_NOT_FOUND", 404)
    assert response.json()["response_type"] == "error"


def test_omitting_a_required_input_creates_nothing():
    """PRD §2.8: "The body must be a JSON object, every required input field must be
    present, every field must parse to its declared type, every enum-valued field must carry
    a declared member, and no unknown field may be present."

    Design: Corner/entities/corner_required_input_fields_rejected_when_absent
    """
    validate_error(
        api_client.create_advisor(
            {"legal_name": "Dana Reyes", "seller_of_travel_state": "NY"}, ops()
        ),
        "ERR_INVALID_REQUEST",
        400,
    )
    validate_error(
        api_client.create_supplier(
            {
                "name": "Northwind Tours",
                "accreditation_scheme": "IATA",
                "preferred_override_commission_pct": 0.12,
                "rate_ceiling_pct": 0.20,
                "max_commission_per_booking_cents": 2_000_000,
                "remit_terms_days": 30,
            },
            ops(),
        ),
        "ERR_INVALID_REQUEST",
        400,
    )

    _, advisor_meta = validate_paginated(api_client.list_advisors(ops()))
    assert advisor_meta["total_count"] == 0
    _, supplier_meta = validate_paginated(api_client.list_suppliers(ops()))
    assert supplier_meta["total_count"] == 0


def test_omitted_optional_inputs_take_their_declared_defaults():
    """PRD §3.1: "Three inputs are optional: `consortium_id`, which is null when the
    supplier belongs to no consortium's preferred programme; `program_status`, which defaults
    to `STANDARD` and may also be supplied as `PREFERRED`; and
    `probation_chargeback_threshold`, the chargeback count at or above which the supplier is
    demoted, which defaults to 2 and must be at least 1."

    Design: Corner/entities/corner_optional_inputs_fall_back_to_declared_defaults
    """
    ctx = setup_active_advisor(
        state="NY",
        legal_name="Dana Reyes",
        email="dana.reyes@example.com",
        schedule=new_split_schedule(),
    )

    supplier = new_supplier(**NORTHWIND)
    assert supplier["program_status"] == "STANDARD"
    assert supplier["probation_chargeback_threshold"] == 2
    assert supplier["consortium_id"] is None

    client = new_client(
        ctx["advisor"]["id"], full_name="Nadia Okoye", home_state_code="NY"
    )
    assert client["ownership_mode"] == "HOST_OWNED"
    assert client["max_concurrent_trips"] == 1
    assert client["trust_balance_cents"] == 0
    assert client["portability_status"] == "RETAINED"


def test_identifiers_timestamps_and_signing_instants_are_server_minted():
    """PRD §3.2: "The server stamps `signed_at` from the logical clock, sets the new row's
    `status` to `ACTIVE`, and moves the advisor's previously `ACTIVE` agreement, if one
    exists, from `ACTIVE` to `SUPERSEDED`; the supersession transition is declared only where
    the new agreement's `effective_date` is at or after the prior agreement's
    `effective_date`."

    Design: Corner/entities/corner_system_fields_are_server_minted
    """
    schedule = new_split_schedule()
    advisor = new_advisor()

    consortium = validate_success(
        api_client.create_consortium(
            create_consortium_payload(
                name="Voyager Alliance",
                membership_fee_cents=5_000_000,
                marketing_fund_accrual_pct=0.02,
                consortium_channel_bonus_pct=0.01,
            ),
            ops(),
        ),
        201,
    )
    assert consortium["version"] == 1
    assert is_iso8601_timestamp(consortium["created_at"])
    assert consortium["created_at"] == consortium["updated_at"]

    agreement = validate_success(
        api_client.create_advisor_agreement(
            advisor["id"],
            create_advisor_agreement_payload(
                schedule["id"], advisor["version"], effective_date="2026-01-01"
            ),
            ops(),
        ),
        201,
    )
    assert agreement["signed_at"].startswith("2026-08-01T00:00:00")
    assert agreement["status"] == "ACTIVE"
    assert agreement["version"] == 1
    assert read_advisor(advisor["id"])["version"] == advisor["version"] + 1


def test_the_trust_obligation_is_derived_from_the_home_state_alone():
    """PRD §2.12: "The system encodes this as a derived obligation rather than an operator
    choice: an advisor's `trust_account_required` is true when the advisor's
    `seller_of_travel_state` is one of California, Florida, Hawaii, Iowa or Washington — the
    two-letter codes `CA`, `FL`, `HI`, `IA` and `WA` — and false for every other state."

    Design: Corner/entities/corner_trust_requirement_is_computed_not_supplied
    """
    california = new_advisor(
        legal_name="Priya Nair",
        email="priya.nair@example.com",
        seller_of_travel_state="CA",
    )
    new_york = new_advisor(
        legal_name="Dana Reyes",
        email="dana.reyes@example.com",
        seller_of_travel_state="NY",
    )
    washington = new_advisor(
        legal_name="Ines Duarte",
        email="ines.duarte@example.com",
        seller_of_travel_state="WA",
    )

    assert california["trust_account_required"] is True
    assert washington["trust_account_required"] is True
    assert new_york["trust_account_required"] is False
    for row in (california, new_york, washington):
        assert row["status"] == "DRAFT"
        assert row["version"] == 1


def test_a_value_outside_a_declared_enum_is_refused_before_any_business_rule():
    """PRD §2.8: "The body must be a JSON object, every required input field must be
    present, every field must parse to its declared type, every enum-valued field must carry
    a declared member, and no unknown field may be present."

    Design: Corner/entities/corner_enum_and_range_type_constraints_rejected
    """
    advisor = new_advisor(
        legal_name="Dana Reyes",
        email="dana.reyes@example.com",
        seller_of_travel_state="NY",
    )
    training = validate_success(
        api_client.create_compliance_credential(
            advisor["id"],
            training_cert_credential_payload(
                credential_number="TRN-2026-A",
                effective_on="2026-01-01",
                expires_on="2027-01-01",
            ),
            ops(),
        ),
        201,
    )

    validate_error(
        api_client.create_compliance_credential(
            advisor["id"],
            {
                "credential_type": "NOTARY",
                "credential_number": "NOT-1",
                "effective_on": "2026-01-01",
                "expires_on": "2027-01-01",
            },
            ops(),
        ),
        "ERR_INVALID_REQUEST",
        400,
    )
    validate_error(
        api_client.decide_compliance_credential(
            training["id"], {"decision": "MAYBE"}, compliance()
        ),
        "ERR_INVALID_REQUEST",
        400,
    )

    assert read_credential(training["id"])["status"] == "PENDING_REVIEW"
    rows, meta = validate_paginated(
        api_client.list_compliance_credentials(ops(), {"advisor_id": advisor["id"]})
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [training["id"]]


def test_trust_ledger_lines_are_append_only_and_carry_no_version():
    """PRD §2.4: "Trust ledger lines are immutable financial records: once appended they
    are never rewritten, there is no update or delete operation for them, and consequently
    the entity carries neither `updated_at` nor `version` — a trust ledger row exposes only
    `id` and `created_at` alongside its own fields."

    Design: Corner/entities/corner_trust_ledger_entry_is_immutable_and_versionless
    """
    ctx = setup_active_advisor(
        state="CA",
        legal_name="Priya Nair",
        email="priya.nair@example.com",
        schedule=new_split_schedule(),
    )
    advisor = ctx["advisor"]
    client = new_client(
        advisor["id"],
        full_name="Marco Vidal",
        home_state_code="CA",
        ownership_mode="ADVISOR_OWNED",
        max_concurrent_trips=2,
    )
    opening_version = read_client(client["id"])["version"]

    deposit = validate_success(
        api_client.create_trust_ledger_entry(
            client["id"],
            trust_ledger_entry_payload(
                "DEPOSIT", 250_000, opening_version, memo="Initial client wire"
            ),
            make_advisor_headers(advisor["id"]),
        ),
        201,
    )
    assert deposit["balance_after_cents"] == 250_000
    assert "version" not in deposit
    assert "updated_at" not in deposit
    assert is_iso8601_timestamp(deposit["created_at"])

    disbursement = validate_success(
        api_client.create_trust_ledger_entry(
            client["id"],
            trust_ledger_entry_payload(
                "DISBURSEMENT",
                40_000,
                read_client(client["id"])["version"],
                memo="Air deposit paid to supplier",
            ),
            controller("ctrl-1"),
        ),
        201,
    )
    assert disbursement["balance_after_cents"] == 210_000
    assert "version" not in disbursement
    assert "updated_at" not in disbursement

    lines = list_client_ledger(client["id"])
    assert [line["id"] for line in lines] == [deposit["id"], disbursement["id"]]
    assert lines[0]["balance_after_cents"] == 250_000
    assert read_client(client["id"])["trust_balance_cents"] == 210_000
    assert read_client(client["id"])["version"] == opening_version + 2


def test_a_credential_filed_under_an_unknown_advisor_resolves_the_parent_first():
    """PRD §3.3: "Credentials are filed against a specific advisor, either by the advisor
    personally or by the operations desk."

    Design: Corner/entities/corner_credential_parent_must_exist
    """
    error = validate_error(
        api_client.create_compliance_credential(
            NON_EXISTENT_UUID,
            eo_policy_credential_payload(
                credential_number="EO-99881",
                effective_on="2026-01-01",
                expires_on="2027-01-01",
                coverage_amount_cents=100_000_000,
            ),
            ops(),
        ),
        "ERR_ADVISOR_NOT_FOUND",
        404,
    )
    assert error["error_id"] != "ERR_CREDENTIAL_FIELDS_INCOHERENT"

    _, meta = validate_paginated(api_client.list_compliance_credentials(ops()))
    assert meta["total_count"] == 0


def test_each_booking_foreign_key_is_resolved_on_its_own():
    """PRD §2.8: "Resources named in the URL path are resolved strictly left to right, so
    a nested address reports the outermost missing segment first; only afterwards are foreign
    keys supplied in the body resolved, in the order the fields are listed for that
    endpoint."

    Design: Corner/entities/corner_flat_topology_foreign_keys_validated_on_booking
    """
    supplier = new_supplier(**NORTHWIND)
    ctx = setup_active_advisor(
        state="NY",
        legal_name="Dana Reyes",
        email="dana.reyes@example.com",
        schedule=new_split_schedule(),
        suppliers=[supplier],
    )
    advisor = ctx["advisor"]
    client = new_client(
        advisor["id"],
        full_name="Nadia Okoye",
        home_state_code="NY",
        ownership_mode="ADVISOR_OWNED",
        max_concurrent_trips=4,
    )
    headers = make_advisor_headers(advisor["id"])

    validate_error(
        api_client.create_booking(
            create_booking_payload(
                advisor["id"],
                NON_EXISTENT_UUID,
                client["id"],
                channel="SUPPLIER_DIRECT",
                payment_method="MERCHANT_DIRECT",
                gross_sale_cents=1_000_000,
                travel_start_date="2026-10-01",
                travel_end_date="2026-10-10",
            ),
            headers,
        ),
        "ERR_SUPPLIER_NOT_FOUND",
        404,
    )
    validate_error(
        api_client.create_booking(
            create_booking_payload(
                advisor["id"],
                supplier["id"],
                NON_EXISTENT_UUID,
                channel="SUPPLIER_DIRECT",
                payment_method="MERCHANT_DIRECT",
                gross_sale_cents=1_000_000,
                travel_start_date="2026-10-01",
                travel_end_date="2026-10-10",
            ),
            headers,
        ),
        "ERR_CLIENT_NOT_FOUND",
        404,
    )

    _, meta = validate_paginated(api_client.list_bookings(ops()))
    assert meta["total_count"] == 0
    assert read_advisor(advisor["id"])["production_ytd_provisional_cents"] == 0
