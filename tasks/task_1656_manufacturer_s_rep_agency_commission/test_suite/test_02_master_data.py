"""Master data: principals, reps, customers, sample serials, and the logical clock.

Covers creation defaults, required-field and uniqueness rejections from PRD
§3.1-§3.2, §3.8, and the clock's default reading of PRD §2.5.
"""
from test_helpers import (
    CLOCK_DEFAULT,
    ApiErrorId,
    api_client,
    assert_customer,
    assert_principal,
    assert_rep,
    create_customer,
    create_principal,
    create_rep,
    create_rep_payload,
    create_sample_unit,
    is_valid_uuid,
    make_principal_ops_headers,
    parse_instant,
    submit_registration,
    validate_error,
    validate_success,
)


class TestPrincipalCreation:
    def test_principal_creation_applies_defaults(self, api, agency_admin_headers):
        """PRD §3.1: "plus an optional `notice_period_days` that defaults to ninety
        days. A new principal is born `ACTIVE` with `credited_ytd_sales_cents` at zero
        and `ytd_year` set to the year of the current logical clock."
        PRD §3.9: "until a notice exists, both timestamps are null."

        Design: Corner/entities/principal_creation_applies_defaults
        """
        resp = api.create_principal(
            {"name": "P1", "annual_quota_cents": 10_000_000}, agency_admin_headers,
        )
        data = validate_success(resp, expected_status=201)
        assert_principal(data)
        assert data["notice_period_days"] == 90, "default notice period is 90 days"
        assert data["status"] == "ACTIVE"
        assert data["credited_ytd_sales_cents"] == 0
        assert data["ytd_year"] == 2026, "clock default year is 2026 (PRD §2.5)"
        assert data["termination_notice_issued_at"] is None
        assert data["termination_effective_at"] is None

    def test_principal_missing_required_field_rejected(self, api, agency_admin_headers):
        """PRD §3.1: "Everything begins when an `AgencyAdmin` onboards a principal by
        supplying its `name` and the `annual_quota_cents` the agency is expected to
        sell on that line over a calendar year, plus an optional `notice_period_days`
        that defaults to ninety days."
        PRD §2.9: "Payload shape, duplicate identifiers, uniqueness scopes, and split
        sums — otherwise one of `ERR_SPLIT_SUM_INVALID`, `ERR_DUPLICATE_EXTERNAL_REF`,
        `ERR_DUPLICATE_PERIOD_LABEL`, `ERR_DUPLICATE_SERIAL`,
        `ERR_TERRITORY_COVERAGE_CONFLICT`, `ERR_AGREEMENT_CONFLICT`, or
        `ERR_INVALID_REQUEST`."

        Design: Corner/entities/principal_missing_required_field_rejected
        """
        resp = api.create_principal({"name": "P1"}, agency_admin_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


class TestRepTerritoryCoverage:
    def test_rep_territory_overlap_rejected(self, api, agency_admin_headers):
        """PRD §3.2: "Coverage is exclusive: a new rep's territories must be disjoint
        from the `territory_codes` of every other `ACTIVE` rep, or creation fails with
        `ERR_TERRITORY_COVERAGE_CONFLICT`."
        PRD §3.2: "every rep starts `ACTIVE` with a `commission_balance_cents` of zero."

        Design: Corner/entities/rep_territory_overlap_rejected
        """
        create_rep("R1", ["CA", "OR"])
        resp = api.create_rep(
            create_rep_payload(display_name="R2", territory_codes=["CA", "NV"]),
            agency_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_TERRITORY_COVERAGE_CONFLICT)

        ok = api.create_rep(
            create_rep_payload(display_name="R3", territory_codes=["NV"]),
            agency_admin_headers,
        )
        data = validate_success(ok, expected_status=201)
        assert_rep(data)
        assert data["status"] == "ACTIVE"


class TestCustomerCreation:
    def test_customer_creation_persists_territory_pair(self, api, agency_admin_headers):
        """PRD §3.2: "An `AgencyAdmin` creates a customer with a `name`, a
        `spec_territory_code` — the territory where the customer's design and
        engineering organization sits — and a `ship_to_territory_code`, the default
        delivery territory."
        PRD §2.4: "`id` — a server-minted UUID with no type prefix, unique across the
        installation."

        Design: Corner/entities/customer_creation_persists_territory_pair
        """
        customer = create_customer(
            name="C1", spec_territory_code="CA", ship_to_territory_code="WA",
        )
        assert_customer(customer)
        assert customer["spec_territory_code"] == "CA"
        assert customer["ship_to_territory_code"] == "WA"
        assert is_valid_uuid(customer["id"])


class TestSampleSerialUniqueness:
    def test_duplicate_serial_rejected(self, api):
        """PRD §3.8: "A `PrincipalOps` operator registers a unit with its
        `principal_id`, a `serial_number` that must be unique per principal
        (`ERR_DUPLICATE_SERIAL`), the `family_code`, and the list `value_cents` that
        depreciation later keys on; a `TERMINATED` principal consigns nothing new
        (`ERR_LINE_TERMINATED`)."

        Design: Corner/validations/duplicate_serial_rejected
        """
        principal = create_principal()
        create_sample_unit(principal["id"], serial_number="S-1", value_cents=80_000)
        resp = api_client.create_sample_unit(
            {
                "principal_id": principal["id"],
                "serial_number": "S-1",
                "family_code": "CABLES",
                "value_cents": 5000,
            },
            make_principal_ops_headers(principal["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_SERIAL)


class TestLogicalClock:
    def test_clock_default_time_untouched(self, api):
        """PRD §2.5: "Before the clock has ever been advanced, it reads exactly
        2026-08-01T00:00:00Z."
        PRD §3.3: "the system records the acting rep as the registration's `rep_id`
        and stamps `submitted_at` with the clock."

        Design: Corner/endpoints/clock_default_time_untouched
        """
        principal = create_principal()
        customer = create_customer(spec_territory_code="CA", ship_to_territory_code="CA")
        rep = create_rep("R1", ["CA"])
        reg = submit_registration(principal["id"], customer["id"], rep["id"],
                                  project_name="Project T0")
        assert parse_instant(reg["submitted_at"]) == parse_instant(CLOCK_DEFAULT), (
            f"submitted_at must equal the default logical clock reading, "
            f"got {reg['submitted_at']!r}"
        )
