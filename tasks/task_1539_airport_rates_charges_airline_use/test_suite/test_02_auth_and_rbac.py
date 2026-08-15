"""Authentication and role-based access control."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    adopt_rates_for_year,
    create_airline,
    create_airline_payload,
    create_fiscal_year_payload,
    create_rates_setting,
    make_signatory_airline_headers,
    pay_all_lines,
    publish_rates,
    setup_open_year,
    setup_settlement_in_review,
    validate_error,
    validate_success,
)

FINANCE = TEST_USERS["finance_headers"]
DIRECTOR = TEST_USERS["director_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


class TestAuthentication:
    def test_missing_role_header_rejected(self, api):
        """PRD §2.1: "A request whose role header is missing or names an
        unrecognized role is rejected with `ERR_UNAUTHENTICATED`."

        Design: Corner/validations/unauthenticated_missing_role_header
        """
        resp = api.list_fiscal_years({})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


class TestRbacDenials:
    def test_auditor_cannot_create_fiscal_year(self, api):
        """PRD §2.1: "`AirportAuditor` performs no writes at all."
        PRD §2.1: "A request whose role is recognized but not permitted for the
        target endpoint is rejected with `ERR_FORBIDDEN`."

        Design: Corner/validations/auditor_cannot_create_fiscal_year
        """
        resp = api.create_fiscal_year(
            create_fiscal_year_payload(year_label="FY_FORB",
                                       airfield_opex_cents=1000),
            AUDITOR,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_signatory_airline_cannot_adopt_rates(self, api):
        """PRD §3.2: "Adoption belongs to the `AirportDirector`."
        PRD §2.1: "A request whose role is recognized but not permitted for the
        target endpoint is rejected with `ERR_FORBIDDEN`."

        Design: Corner/validations/signatory_airline_cannot_adopt_rates
        """
        ws = setup_open_year("FY_FORB2")
        rs = create_rates_setting(ws["fy"]["id"])
        publish_rates(rs["id"])
        airline = create_airline("FB", legal_name="Forbidden Air")

        resp = api.adopt_rates_setting(rs["id"],
                                       make_signatory_airline_headers(airline["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_airport_finance_cannot_finalize_settlement(self, api):
        """PRD §3.6: "The `AirportDirector` may finalize a settlement standing
        either `AIRLINE_REVIEW` or `RESOLVED`"
        PRD §2.1: "A request whose role is recognized but not permitted for the
        target endpoint is rejected with `ERR_FORBIDDEN`."

        Design: Corner/rbac/airport_finance_cannot_finalize_settlement
        """
        ws = setup_settlement_in_review(
            "FY_RF",
            airline_specs=[{"iata_code": "RF"}],
            activity_specs=[{"iata_code": "RF", "landed_weight_kg": 1000}],
        )
        pay_all_lines(ws)

        resp = api.finalize_settlement(ws["settlement"]["id"], FINANCE)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

        after = validate_success(api.get_settlement(ws["settlement"]["id"],
                                                    FINANCE))
        assert after["status"] == "AIRLINE_REVIEW", (
            "The forbidden finalize leaves the settlement untouched")

    def test_auditor_reads_but_cannot_write(self, api):
        """PRD §2.1: "Reading is broad — every role may call every read
        endpoint — while writing is tightly partitioned per the endpoint table
        in §4. `AirportAuditor` performs no writes at all."

        Design: Corner/rbac/airport_auditor_can_read_but_not_write
        """
        read = api.list_airlines(AUDITOR)
        assert read.status_code == 200, "Auditor may call read endpoints"

        write = api.create_airline(
            create_airline_payload(iata_code="AU", legal_name="Auditor Test"),
            AUDITOR,
        )
        validate_error(write, ApiErrorId.ERR_FORBIDDEN)
