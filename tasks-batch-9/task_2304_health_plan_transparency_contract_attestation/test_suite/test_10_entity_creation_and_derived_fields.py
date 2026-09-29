"""What the server mints, computes and refuses at creation time.

A new row's derived fields are not a formality: an inert plan year that came
back `ACTIVE`, a staged file whose error count came back 0 instead of null, or a
contract whose disclosure flag was taken from the request would each unblock work
the program is supposed to hold. These cases read the freshly created row and
then read it back through its own endpoint.
"""

from __future__ import annotations

from test_helpers import (
    COMPLIANCE_OFFICER_HEADERS,
    EXTERNAL_AUDITOR_HEADERS,
    OFFICER_USER_ID,
    SPONSOR_ADMIN_HEADERS,
    ApiClient,
    ApiErrorId,
    ATTESTATION_MIRROR_NOT_STARTED,
    DEFAULT_SLA_TARGET_UPTIME_PCT,
    DEFICIENCY_GAG_CLAUSE,
    ENTRY_ACCRUAL,
    GAG_NOT_REVIEWED,
    DATA_RIGHTS_NOT_SECURED,
    LIFECYCLE_SETUP,
    MRF_DRAFT,
    NON_EXISTENT_UUID,
    POSTURE_COMPLIANT,
    TOOL_PENDING_LAUNCH,
    VENDOR_TYPE_BROKER,
    VENDOR_TYPE_CONSULTANT,
    VENDOR_TYPE_TPA,
    assert_identity_fields,
    assert_instant_equals,
    assert_no_version_discipline,
    factories as f,
    fixtures as fx,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

SETUP_CLOCK = "2027-01-02T09:00:00Z"
TOOL_CLOCK = "2027-01-05T09:00:00Z"
MRF_CLOCK = "2027-06-01T09:00:00Z"
ROSTER_CLOCK = "2027-02-01T09:00:00Z"
GAG_CLOCK = "2027-05-04T09:00:00Z"

IN_NETWORK_URL = "https://transparency.meridian.example/2027-06/in-network-rates.json"


class TestPlanYearCreation:
    """The registry entry every other obligation hangs from."""

    def test_a_new_plan_year_comes_back_inert_with_every_counter_at_zero(
        self, api: ApiClient
    ) -> None:
        """Creation is a registration, not an activation.

        PRD 3.1: "A newly created plan year is inert. Its `lifecycle_status` is
        `SETUP`, its `compliance_posture` is `COMPLIANT`, its
        `deficiency_points`, `penalty_exposure_cents` and `tool_sla_breach_count`
        are all 0, its `attestation_status` is `NOT_STARTED`, its `freeze_flag`
        is false, and `freeze_reason` and `last_compliance_run_at` are both
        null."

        Design: Corner/entities/create_plan_year_initialises_derived_fields
        """
        fx.set_clock(api, SETUP_CLOCK)

        response = api.create_plan_year(
            f.plan_year_payload(covered_lives=6000), SPONSOR_ADMIN_HEADERS
        )
        created = validate_success(response, expected_status=201)
        assert response.json()["response_type"] == "object"
        meta = response.json()["meta"]
        assert meta["api_request_id"].startswith("req_")
        assert meta["api_request_timestamp"] is not None

        assert created["lifecycle_status"] == LIFECYCLE_SETUP
        assert created["compliance_posture"] == POSTURE_COMPLIANT
        assert created["deficiency_points"] == 0
        assert created["penalty_exposure_cents"] == 0
        assert created["tool_sla_breach_count"] == 0
        assert created["attestation_status"] == ATTESTATION_MIRROR_NOT_STARTED
        assert created["freeze_flag"] is False
        assert created["freeze_reason"] is None
        assert created["last_compliance_run_at"] is None
        assert created["version"] == 1
        assert_identity_fields(created)

        stored = fx.read_plan_year(api, created["id"])
        assert stored["covered_lives"] == 6000
        assert stored["plan_year_label"] == f.DEFAULT_PLAN_YEAR_LABEL
        assert stored["rxdc_deadline_date"] == f.DEFAULT_RXDC_DEADLINE
        assert_instant_equals(stored["created_at"], SETUP_CLOCK)

    def test_a_plan_year_without_an_enrolled_headcount_is_refused(
        self, api: ApiClient
    ) -> None:
        """The headcount has no default, because it prices every later penalty.

        PRD 3.1: "The payload also carries `covered_lives`, the enrolled
        headcount, which must be at least 1 and which later drives every penalty
        amount through the size multiplier."

        Design: Corner/entities/plan_year_create_missing_required_covered_lives_rejected
        """
        fx.set_clock(api, SETUP_CLOCK)
        payload = dict(f.plan_year_payload())
        payload.pop("covered_lives")

        response = api.create_plan_year(payload, SPONSOR_ADMIN_HEADERS)
        body = validate_error(response, ApiErrorId.INVALID_REQUEST, expected_status=400)
        assert body["message"]

        rows, meta = validate_paginated(api.list_plan_years(COMPLIANCE_OFFICER_HEADERS))
        assert rows == []
        assert meta["total_count"] == 0

    def test_a_well_formed_but_unused_identifier_is_a_plan_year_specific_404(
        self, api: ApiClient
    ) -> None:
        """The 404 names the collection that was addressed.

        PRD 2.9: "Every `{id}` path parameter resolves to an existing row of the
        addressed collection, on every endpoint that carries one — otherwise the
        entity-specific 404: `ERR_PLAN_YEAR_NOT_FOUND`, `ERR_VENDOR_NOT_FOUND`,
        `ERR_CONTRACT_NOT_FOUND`, `ERR_AMENDMENT_NOT_FOUND`,
        `ERR_DISCLOSURE_NOT_FOUND`, `ERR_MRF_NOT_FOUND`,
        `ERR_REFRESH_CYCLE_NOT_FOUND`, `ERR_TOOL_NOT_FOUND`,
        `ERR_RX_SUBMISSION_NOT_FOUND`, `ERR_PACKAGE_NOT_FOUND`,
        `ERR_ATTESTATION_NOT_FOUND`, `ERR_LEDGER_ENTRY_NOT_FOUND` or
        `ERR_REMEDIATION_PLAN_NOT_FOUND`."

        Design: Corner/entities/get_plan_year_unknown_id_not_found
        """
        response = api.get_plan_year(NON_EXISTENT_UUID, COMPLIANCE_OFFICER_HEADERS)
        validate_error(response, ApiErrorId.PLAN_YEAR_NOT_FOUND, expected_status=404)
        assert response.json()["response_type"] == "error"


class TestVendorAndContractRoster:
    """Vendors are registered on their own; contracts are what bind them."""

    def test_an_unlisted_vendor_type_is_refused_and_persists_nothing(
        self, api: ApiClient
    ) -> None:
        """The five categories are the whole vocabulary.

        PRD 3.1: "Registration records the service provider's `legal_name`, a
        `vendor_type` drawn from `TPA`, `PBM`, `BROKER`, `CONSULTANT` and
        `NETWORK_VENDOR`, and a `contact_email` mailbox."

        Design: Corner/entities/vendor_create_invalid_enum_rejected
        """
        fx.set_clock(api, SETUP_CLOCK)

        response = api.create_vendor(
            f.vendor_payload(
                legal_name="Northwind Reinsurance",
                vendor_type="REINSURER",
                contact_email="desk@northwind.example",
            ),
            SPONSOR_ADMIN_HEADERS,
        )
        validate_error(response, ApiErrorId.INVALID_REQUEST, expected_status=400)

        rows, meta = validate_paginated(api.list_vendors(COMPLIANCE_OFFICER_HEADERS))
        assert rows == []
        assert meta["total_count"] == 0

    def test_a_contract_naming_no_registered_vendor_is_a_vendor_404(
        self, api: ApiClient
    ) -> None:
        """The parent arrives as a body field, and it must resolve.

        PRD 2.9: "Every foreign key supplied in a request body or as a list
        filter — `plan_year_id`, `vendor_id`, `contract_id`, `rx_submission_id`,
        `reverses_entry_id`, `remediation_plan_id` — resolves to an existing row,
        on every create endpoint and every list endpoint that filters on a
        foreign key."

        Design: Corner/entities/contract_create_unknown_vendor_id_not_found
        """
        fx.set_clock(api, SETUP_CLOCK)
        plan_year = fx.create_plan_year(api)

        response = api.create_contract(
            f.contract_payload(plan_year["id"], NON_EXISTENT_UUID),
            SPONSOR_ADMIN_HEADERS,
        )
        validate_error(response, ApiErrorId.VENDOR_NOT_FOUND, expected_status=404)

        rows, _ = validate_paginated(
            api.list_contracts(
                COMPLIANCE_OFFICER_HEADERS, params={"plan_year_id": plan_year["id"]}
            )
        )
        assert rows == []
        unchanged = fx.read_plan_year(api, plan_year["id"])
        assert unchanged["lifecycle_status"] == LIFECYCLE_SETUP
        assert unchanged["version"] == 1

    def test_the_disclosure_flag_is_computed_from_the_contract_type_alone(
        self, api: ApiClient
    ) -> None:
        """A broker contract carries the flag; the TPA beside it does not.

        PRD 3.1: "One field on the contract is never supplied and never
        editable: `compensation_disclosure_required` is computed to be true
        exactly when `contract_type` is `BROKER` or `CONSULTANT`, and false for
        `TPA`, `PBM` and `NETWORK_VENDOR`."

        Design: Corner/entities/contract_compensation_disclosure_required_computed
        """
        fx.set_clock(api, ROSTER_CLOCK)
        setup = fx.activated_plan_year(api, covered_lives=6000)
        plan_year_id = setup["plan_year"]["id"]
        broker_vendor = fx.create_broker_vendor(api)

        broker_contract = validate_success(
            api.create_contract(
                f.contract_payload(
                    plan_year_id,
                    broker_vendor["id"],
                    contract_type=VENDOR_TYPE_BROKER,
                    annual_fee_cents=2_400_000,
                ),
                SPONSOR_ADMIN_HEADERS,
            ),
            expected_status=201,
        )
        assert broker_contract["compensation_disclosure_required"] is True
        assert broker_contract["gag_review_status"] == GAG_NOT_REVIEWED
        assert broker_contract["data_rights_status"] == DATA_RIGHTS_NOT_SECURED
        assert broker_contract["clause_inventory_count"] == 0
        assert broker_contract["prohibited_clause_count"] == 0
        assert broker_contract["remediation_round"] == 0
        assert broker_contract["gag_non_compliant_since"] is None

        tpa_contract = fx.read_contract(api, setup["tpa_contract"]["id"])
        assert tpa_contract["contract_type"] == VENDOR_TYPE_TPA
        assert tpa_contract["compensation_disclosure_required"] is False

        rows, meta = validate_paginated(
            api.list_contracts(
                COMPLIANCE_OFFICER_HEADERS, params={"plan_year_id": plan_year_id}
            )
        )
        assert meta["total_count"] == 2
        assert len(rows) == 2

    def test_a_contract_type_filter_narrows_the_count_before_the_page_window(
        self, api: ApiClient
    ) -> None:
        """Three rows page two-then-one, and one filter leaves a single row.

        PRD 2.3: "The `meta` block of a list response carries `limit` and
        `offset` echoing the effective values used, `total_count` giving the
        number of rows that match the supplied filters before pagination is
        applied, and `has_more` set true when rows remain beyond the returned
        page."

        Design: Corner/entities/list_contracts_filter_and_pagination_interact
        """
        fx.set_clock(api, ROSTER_CLOCK)
        setup = fx.activated_plan_year(api, covered_lives=6000)
        plan_year_id = setup["plan_year"]["id"]
        fx.add_contract_for_vendor_type(
            api, plan_year_id, VENDOR_TYPE_BROKER, annual_fee_cents=2_400_000
        )
        fx.add_contract_for_vendor_type(
            api,
            plan_year_id,
            VENDOR_TYPE_CONSULTANT,
            annual_fee_cents=1_800_000,
        )

        first_page, first_meta = validate_paginated(
            api.list_contracts(
                COMPLIANCE_OFFICER_HEADERS,
                params={"plan_year_id": plan_year_id, "limit": 2, "offset": 0},
            )
        )
        assert len(first_page) == 2
        assert first_meta["total_count"] == 3
        assert first_meta["has_more"] is True
        assert first_meta["limit"] == 2
        assert first_meta["offset"] == 0

        second_page, second_meta = validate_paginated(
            api.list_contracts(
                COMPLIANCE_OFFICER_HEADERS,
                params={"plan_year_id": plan_year_id, "limit": 2, "offset": 2},
            )
        )
        assert len(second_page) == 1
        assert second_meta["total_count"] == 3
        assert second_meta["has_more"] is False

        brokers, broker_meta = validate_paginated(
            api.list_contracts(
                COMPLIANCE_OFFICER_HEADERS,
                params={
                    "plan_year_id": plan_year_id,
                    "contract_type": VENDOR_TYPE_BROKER,
                },
            )
        )
        assert len(brokers) == 1
        assert brokers[0]["contract_type"] == VENDOR_TYPE_BROKER
        assert broker_meta["total_count"] == 1
        assert broker_meta["has_more"] is False
        assert broker_meta["limit"] == 10
        assert broker_meta["offset"] == 0


class TestServerMintedFields:
    """Defaults, null-versus-zero distinctions, and an immutable row."""

    def test_an_omitted_availability_target_stores_the_declared_default(
        self, api: ApiClient
    ) -> None:
        """99.00 is a stored value, not an absence the scorer has to guess.

        PRD 3.3: "A `PlanSponsorAdmin` registers one with the `plan_year_id` it
        serves, a consumer-facing `tool_name`, the `covered_items_count` of items
        and services it prices — at least 0 at registration — and optionally an
        availability target in `sla_target_uptime_pct`, expressed as a percentage
        carrying two decimal places and defaulting to 99.00 when omitted."

        Design: Corner/entities/tool_sla_target_uptime_default_applied
        """
        fx.set_clock(api, TOOL_CLOCK)
        setup = fx.activated_plan_year(api, covered_lives=6000)
        payload = dict(
            f.price_comparison_tool_payload(
                setup["plan_year"]["id"],
                tool_name="Meridian Care Cost Finder",
                covered_items_count=800,
            )
        )
        assert "sla_target_uptime_pct" not in payload

        created = validate_success(
            api.create_price_comparison_tool(payload, SPONSOR_ADMIN_HEADERS),
            expected_status=201,
        )
        assert created["sla_target_uptime_pct"] == DEFAULT_SLA_TARGET_UPTIME_PCT
        assert created["status"] == TOOL_PENDING_LAUNCH

        stored = validate_success(
            api.get_price_comparison_tool(created["id"], SPONSOR_ADMIN_HEADERS)
        )
        assert stored["sla_target_uptime_pct"] == DEFAULT_SLA_TARGET_UPTIME_PCT
        assert stored["launched_at"] is None
        assert stored["outage_windows"] == []
        assert stored["sla_breach_open"] is False
        assert stored["last_evaluated_month"] is None
        assert stored["last_uptime_pct"] is None
        assert stored["last_downtime_minutes"] is None
        assert stored["breach_onset_date"] is None

    def test_a_staged_file_carries_a_null_error_count_not_a_clean_zero(
        self, api: ApiClient
    ) -> None:
        """Zero errors would mean validated clean, which would publish it.

        PRD 3.2: "A staged file lands in `DRAFT` with `validation_error_count`,
        `published_at` and `superseded_at` all null."

        Design: Corner/entities/mrf_create_system_fields_generated
        """
        fx.set_clock(api, MRF_CLOCK)
        setup = fx.activated_plan_year(api, covered_lives=6000)

        created = validate_success(
            api.create_mrf(
                f.mrf_payload(
                    setup["plan_year"]["id"],
                    posting_month="2027-06",
                    public_url=IN_NETWORK_URL,
                    row_count=812_004,
                    schema_version="1.2.0",
                ),
                SPONSOR_ADMIN_HEADERS,
            ),
            expected_status=201,
        )
        assert created["status"] == MRF_DRAFT
        assert created["validation_error_count"] is None
        assert created["published_at"] is None
        assert created["superseded_at"] is None
        assert created["version"] == 1
        assert is_valid_uuid(created["id"])
        assert len(created["id"]) == 36

        stored = validate_success(api.get_mrf(created["id"], SPONSOR_ADMIN_HEADERS))
        assert stored["row_count"] == 812_004
        assert stored["schema_version"] == "1.2.0"
        assert_instant_equals(stored["created_at"], MRF_CLOCK)

    def test_a_posted_ledger_entry_carries_no_version_and_no_updated_at(
        self, api: ApiClient
    ) -> None:
        """The one resource in the service that is written once and left alone.

        PRD 2.4: "`PenaltyLedgerEntry` is the one exception: a ledger entry
        carries only `id` and `created_at`. It has no `updated_at` and no
        `version`, because it is immutable — it is written once and never updated
        or deleted."

        Design: Corner/entities/penalty_ledger_entry_is_immutable_append_only
        """
        fx.set_clock(api, GAG_CLOCK)
        setup = fx.plan_year_with_gag_accrual(api, covered_lives=6000)

        rows, meta = validate_paginated(
            api.list_ledger_entries(
                EXTERNAL_AUDITOR_HEADERS,
                params={"plan_year_id": setup["plan_year"]["id"]},
            )
        )
        assert meta["total_count"] == 1
        listed = rows[0]
        assert_no_version_discipline(listed)
        assert_instant_equals(listed["created_at"], GAG_CLOCK)

        entry = validate_success(
            api.get_ledger_entry(listed["id"], EXTERNAL_AUDITOR_HEADERS)
        )
        assert entry["entry_type"] == ENTRY_ACCRUAL
        assert entry["deficiency_type"] == DEFICIENCY_GAG_CLAUSE
        assert entry["signed_amount_cents"] == 30_000
        assert entry["posted_by_user_id"] == OFFICER_USER_ID
        assert entry["reverses_entry_id"] is None
        assert entry["remediation_plan_id"] is None
        assert_no_version_discipline(entry)
