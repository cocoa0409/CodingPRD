"""Every resolution failure has its own identifier.

Against an empty store, seven detail reads are issued by roles that are entitled
to perform them, so the only possible reason for each refusal is the missing row.
"""

from prd_bench_local_runner.testing import validate_error

from test_helpers import api_errors as E
from test_helpers.test_users import COMPLIANCE, FINANCE_APPROVER, OFFICER, REGISTRAR


class TestRemainingNotFoundCodes:
    def test_each_resource_family_reports_its_own_not_found_identifier(self, client):
        """Seven distinct identifiers, one per family, all HTTP 404.

        "Path identifiers are resolved strictly left to right, and the first
        identifier that names nothing produces the 404 for the whole request."

        "The nine resolution failures are `ERR_AGENCY_NOT_FOUND`,
        `ERR_CONTRACT_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`,
        `ERR_APPLICATION_NOT_FOUND`, `ERR_DOCUMENT_NOT_FOUND`,
        `ERR_INCIDENT_NOT_FOUND`, `ERR_ENTRY_NOT_FOUND`, `ERR_PROGRAM_NOT_FOUND` and
        `ERR_TRANSITION_NOT_FOUND`, all HTTP 404."

        Design: Corner/errors/remaining_not_found_codes_are_triggerable
        """
        probes = [
            (
                client.get_program("11111111-1111-1111-1111-111111111111", OFFICER),
                E.ERR_PROGRAM_NOT_FOUND,
            ),
            (
                client.get_contract("22222222-2222-2222-2222-222222222222", OFFICER),
                E.ERR_CONTRACT_NOT_FOUND,
            ),
            (
                client.get_application(
                    "33333333-3333-3333-3333-333333333333", REGISTRAR
                ),
                E.ERR_APPLICATION_NOT_FOUND,
            ),
            (
                client.get_document("44444444-4444-4444-4444-444444444444", COMPLIANCE),
                E.ERR_DOCUMENT_NOT_FOUND,
            ),
            (
                client.get_incident("55555555-5555-5555-5555-555555555555", COMPLIANCE),
                E.ERR_INCIDENT_NOT_FOUND,
            ),
            (
                client.get_commission_entry(
                    "66666666-6666-6666-6666-666666666666", FINANCE_APPROVER
                ),
                E.ERR_ENTRY_NOT_FOUND,
            ),
            (
                client.get_file_transition(
                    "77777777-7777-7777-7777-777777777777", COMPLIANCE
                ),
                E.ERR_TRANSITION_NOT_FOUND,
            ),
        ]

        for response, expected in probes:
            validate_error(response, expected, 404)

    def test_the_missing_row_and_not_the_caller_is_the_reason_for_each_refusal(
        self, client
    ):
        """Role screening happens before path resolution, and each role passed it.

        "Role permitted for the endpoint and for the requested action variant —
        `ERR_UNAUTHORIZED`."

        "Path identifier resolution, left to right — the 404 family of §2.7."

        Design: Corner/errors/remaining_not_found_codes_are_triggerable
        """
        responses = [
            client.get_program("11111111-1111-1111-1111-111111111111", OFFICER),
            client.get_contract("22222222-2222-2222-2222-222222222222", OFFICER),
            client.get_application("33333333-3333-3333-3333-333333333333", REGISTRAR),
            client.get_document("44444444-4444-4444-4444-444444444444", COMPLIANCE),
            client.get_incident("55555555-5555-5555-5555-555555555555", COMPLIANCE),
            client.get_commission_entry(
                "66666666-6666-6666-6666-666666666666", FINANCE_APPROVER
            ),
            client.get_file_transition(
                "77777777-7777-7777-7777-777777777777", COMPLIANCE
            ),
        ]

        for response in responses:
            assert response.status_code == 404, response.text
            assert response.json()["data"]["error_id"] != E.ERR_UNAUTHORIZED
