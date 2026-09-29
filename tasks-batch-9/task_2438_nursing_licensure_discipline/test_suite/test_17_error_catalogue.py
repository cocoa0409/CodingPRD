"""The not-found family per entity, and the identity gate that answers before them."""
from test_helpers import (
    ADMIN,
    ANALYST,
    COORDINATOR,
    INVESTIGATOR,
    PRESIDING,
    UNKNOWN_UUID_ALT,
    ApiClient,
    ApiErrorId,
    make_headers,
    seed_board,
    validate_error,
    validate_success,
)


def test_each_entity_family_answers_a_missing_row_with_its_own_code(api: ApiClient):
    """PRD §2.11: "Every resource identifier in the path exists, validated left to
    right — otherwise that family's not-found code."

    PRD §2.6: "Every resource in this system — board configurations, education
    programs, nurses, licence applications, credentials, renewal filings,
    continuing-education records, complaints, evidence requests, monitoring
    agreements, disciplinary proceedings, and notification reports — carries the
    same four system-managed properties."

    PRD §2.6: "`id` (string): a server-minted UUID. It carries no type prefix of any
    kind."

    Design: Corner/errors/every_entity_not_found_code_is_triggerable_from_its_own_path
    """
    ghost = UNKNOWN_UUID_ALT
    probes = [
        (api.get_board_config(ghost, ADMIN), ApiErrorId.ERR_BOARD_CONFIG_NOT_FOUND),
        (api.get_education_program(ghost, ADMIN), ApiErrorId.ERR_PROGRAM_NOT_FOUND),
        (api.get_nurse(ghost, ANALYST), ApiErrorId.ERR_NURSE_NOT_FOUND),
        (api.get_license_application(ghost, ANALYST),
         ApiErrorId.ERR_APPLICATION_NOT_FOUND),
        (api.get_license(ghost, ANALYST), ApiErrorId.ERR_LICENSE_NOT_FOUND),
        (api.get_renewal_application(ghost, ANALYST), ApiErrorId.ERR_RENEWAL_NOT_FOUND),
        (api.get_ce_record(ghost, ANALYST), ApiErrorId.ERR_CE_RECORD_NOT_FOUND),
        (api.get_complaint(ghost, INVESTIGATOR), ApiErrorId.ERR_COMPLAINT_NOT_FOUND),
        (api.get_evidence_request(ghost, INVESTIGATOR),
         ApiErrorId.ERR_EVIDENCE_REQUEST_NOT_FOUND),
        (api.get_monitoring_agreement(ghost, COORDINATOR),
         ApiErrorId.ERR_MONITORING_AGREEMENT_NOT_FOUND),
        (api.get_disciplinary_proceeding(ghost, PRESIDING),
         ApiErrorId.ERR_PROCEEDING_NOT_FOUND),
        (api.get_notification_report(ghost, ADMIN),
         ApiErrorId.ERR_NOTIFICATION_REPORT_NOT_FOUND),
    ]

    seen = []
    for response, expected in probes:
        error = validate_error(response, expected.value, 404)
        assert response.json()["meta"]["api_request_id"].startswith("req_"), (
            "An error envelope still carries the request identifier"
        )
        seen.append(error["error_id"])
    assert len(set(seen)) == 12, (
        f"Each of the twelve families owns a distinct code, got {sorted(set(seen))}"
    )


def test_an_undeclared_role_is_turned_away_before_the_store_is_consulted(
    api: ApiClient,
):
    """PRD §2.1: "Every request to this API must carry two headers."

    PRD §2.1: "If either header is absent, or if `X-User-Role` does not spell one of
    the six declared roles exactly, the request is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)."

    PRD §2.11: "Both `X-User-ID` and `X-User-Role` are present and `X-User-Role`
    names one of the six declared roles — otherwise `ERR_UNAUTHENTICATED`."

    PRD §2.11: "The caller's role is authorised for the endpoint — otherwise
    `ERR_FORBIDDEN_ROLE`."

    Design: Corner/errors/unrecognised_role_header_value_returns_unauthenticated
    """
    board = seed_board(api)

    refused = api.get_board_config(UNKNOWN_UUID_ALT,
                                   make_headers("ghost-1", "RegistryAuditor"))

    error = validate_error(refused, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)
    assert error["error_id"] != ApiErrorId.ERR_BOARD_CONFIG_NOT_FOUND.value, (
        "The identity gate answers first and leaks nothing about what exists"
    )
    assert error["error_id"] != ApiErrorId.ERR_FORBIDDEN_ROLE.value, (
        "An undeclared role never reaches the authorisation check"
    )
    validate_error(
        api.get_board_config(UNKNOWN_UUID_ALT,
                             {"X-User-Role": "SystemAdmin",
                              "Content-Type": "application/json"}),
        ApiErrorId.ERR_UNAUTHENTICATED.value,
        401,
    )
    accepted = validate_success(api.get_board_config(board["id"], ADMIN))
    assert accepted["id"] == board["id"], (
        "A declared role with both headers reaches the record"
    )
