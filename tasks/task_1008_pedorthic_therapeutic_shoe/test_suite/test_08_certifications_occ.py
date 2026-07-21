"""Certifications: optimistic-concurrency version guard, supersession, version bump, and
the in-person visit window."""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId, TEST_USERS,
)
from test_helpers import fixtures as fx

SM = TEST_USERS["store_manager_headers"]
BS = TEST_USERS["billing_specialist_headers"]


def test_stale_customer_version_on_second_certification_rejected(api):
    """PRD §2.7: "If `expected_customer_version` does not equal the customer's current
    `version`, the create is rejected with `ERR_STALE_VERSION` (HTTP 412). This matters
    because creating a newer certification supersedes the customer's prior `COMPLETE`
    certification and bumps the customer's `version`."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_customer_version_on_second_certification
    """
    fx.set_clock()
    cust = fx.create_customer(full_name="Occ Cust", date_of_birth="1946-06-06",
                              medicare_beneficiary_id="5EF6GH7IJ88")
    v1 = cust["version"]
    fx.create_certification(cust["id"], v1, statement_date="2026-06-01",
                            in_person_visit_date="2026-05-01",
                            certifying_physician_npi="5050505050",
                            prescribing_practitioner_npi="6060606060")
    # Second create still carrying the pre-supersede version v1.
    resp = api.create_certification(cust["id"], {
        "certifying_physician_npi": "5050505050", "prescribing_practitioner_npi": "6060606060",
        "statement_date": "2026-06-05", "in_person_visit_date": "2026-05-05",
        "expected_customer_version": v1}, BS)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


def test_correct_version_second_certification_supersedes_prior(api):
    """PRD §2.7: "creating a newer certification supersedes the customer's prior
    `COMPLETE` certification and bumps the customer's `version`."
    PRD §3.6: "A certification begins `COMPLETE`; creating a newer certification for the
    same customer supersedes the prior one, moving it from `COMPLETE` to `SUPERSEDED`."

    Design: Corner/cross_cutting_complexity_layers/occ_correct_version_second_certification_succeeds
    """
    fx.set_clock()
    cust = fx.create_customer(full_name="Occ2 Cust", date_of_birth="1947-07-07",
                              medicare_beneficiary_id="6GH7IJ8KL99")
    cert1 = fx.create_certification(cust["id"], cust["version"],
                                    certifying_physician_npi="7070707070",
                                    prescribing_practitioner_npi="8080808080",
                                    statement_date="2026-06-01", in_person_visit_date="2026-05-01")
    v_after = get_success_data(api.get_customer(cust["id"], BS))["version"]
    cert2 = validate_success(api.create_certification(cust["id"], {
        "certifying_physician_npi": "7070707070", "prescribing_practitioner_npi": "8080808080",
        "statement_date": "2026-06-10", "in_person_visit_date": "2026-05-10",
        "expected_customer_version": v_after}, BS), expected_status=201)
    assert fx.get_certification(cust["id"], cert1["id"])["status"] == "SUPERSEDED"
    assert fx.get_certification(cust["id"], cert2["id"])["status"] == "COMPLETE"


def test_version_increments_on_certification_create(api):
    """PRD §2.4: "`version` is an integer that starts at 1 and increments by one on every
    mutation of the resource."
    PRD §2.7: "creating a newer certification supersedes the customer's prior `COMPLETE`
    certification and bumps the customer's `version`."

    Design: Corner/cross_cutting_complexity_layers/version_increments_on_certification_create
    """
    fx.set_clock()
    cust = fx.create_customer(full_name="Ver Cust", date_of_birth="1948-08-08",
                              medicare_beneficiary_id="7IJ8KL9MN00")
    assert cust["version"] == 1
    fx.create_certification(cust["id"], cust["version"],
                            certifying_physician_npi="9090909090",
                            prescribing_practitioner_npi="1212121212",
                            statement_date="2026-06-01", in_person_visit_date="2026-05-01")
    after = get_success_data(api.get_customer(cust["id"], BS))
    assert after["version"] == 2


def test_certification_visit_expired_rejected(api):
    """PRD §3.6: "That visit date must fall within 6 calendar months before the current
    clock date; a staler visit is rejected with `ERR_CERTIFICATION_VISIT_EXPIRED`."

    Design: Corner/state_machines/certification_visit_expired_returns_422
    """
    fx.set_clock()
    cust = fx.create_customer(full_name="Exp Cust", date_of_birth="1945-05-05",
                              medicare_beneficiary_id="8OP1AN2TR40")
    resp = api.create_certification(cust["id"], {
        "certifying_physician_npi": "1010101010", "prescribing_practitioner_npi": "2020202020",
        "statement_date": "2026-06-01", "in_person_visit_date": "2025-11-15",
        "expected_customer_version": cust["version"]}, BS)
    validate_error(resp, ApiErrorId.ERR_CERTIFICATION_VISIT_EXPIRED.value)
