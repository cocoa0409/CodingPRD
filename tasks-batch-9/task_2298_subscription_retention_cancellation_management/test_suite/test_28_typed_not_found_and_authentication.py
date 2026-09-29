"""The two bands that run before any business rule: path existence and identification.

Every resource family owns its own not-found code rather than sharing a generic one, and a
request that cannot be identified at all is refused as unauthenticated even on a read that
every declared role may perform.
"""

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    build_user_headers,
    new_core_plan,
    set_clock,
    validate_error,
)

ADMIN = TEST_USERS["platform_admin_headers"]
BILLING = TEST_USERS["billing_operator_headers"]
RETENTION = TEST_USERS["retention_specialist_headers"]


class TestTypedNotFoundPerFamily:

    def test_eleven_unknown_ids_return_eleven_different_not_found_codes(self):
        """A well-formed but unminted id names the family that failed to resolve.

        PRD §2.5: "Path identifiers for the remaining resource types resolve to
        `ERR_CANCELLATION_SESSION_NOT_FOUND`, `ERR_SAVE_OFFER_GRANT_NOT_FOUND`,
        `ERR_SAVE_OFFER_TEMPLATE_NOT_FOUND`, `ERR_MODIFICATION_NOT_FOUND`,
        `ERR_COMPLIANCE_NOTICE_NOT_FOUND`, `ERR_WINBACK_CAMPAIGN_NOT_FOUND`,
        `ERR_DUNNING_ATTEMPT_NOT_FOUND` and `ERR_COHORT_SNAPSHOT_NOT_FOUND`
        respectively. All of these carry HTTP 404."

        Design: Corner/errors/unknown_path_ids_return_the_typed_not_found_error_of_each_family
        """
        set_clock("2026-01-10")
        unknown = "00000000-0000-4000-8000-0000000000%02d"

        validate_error(api_client.get_payment_method(unknown % 1, BILLING),
                       ApiErrorId.ERR_PAYMENT_METHOD_NOT_FOUND, 404)
        validate_error(api_client.get_invoice(unknown % 2, BILLING),
                       ApiErrorId.ERR_INVOICE_NOT_FOUND, 404)
        validate_error(api_client.get_dunning_attempt(unknown % 3, BILLING),
                       ApiErrorId.ERR_DUNNING_ATTEMPT_NOT_FOUND, 404)
        validate_error(api_client.get_cancellation_session(unknown % 4, RETENTION),
                       ApiErrorId.ERR_CANCELLATION_SESSION_NOT_FOUND, 404)
        validate_error(api_client.get_save_offer_grant(unknown % 5, RETENTION),
                       ApiErrorId.ERR_SAVE_OFFER_GRANT_NOT_FOUND, 404)
        validate_error(api_client.get_save_offer_template(unknown % 6, ADMIN),
                       ApiErrorId.ERR_SAVE_OFFER_TEMPLATE_NOT_FOUND, 404)
        validate_error(api_client.get_modification(unknown % 7, RETENTION),
                       ApiErrorId.ERR_MODIFICATION_NOT_FOUND, 404)
        validate_error(api_client.send_compliance_notice(unknown % 8, BILLING),
                       ApiErrorId.ERR_COMPLIANCE_NOTICE_NOT_FOUND, 404)
        validate_error(api_client.get_winback_campaign(unknown % 9, RETENTION),
                       ApiErrorId.ERR_WINBACK_CAMPAIGN_NOT_FOUND, 404)
        validate_error(api_client.get_winback_target(unknown % 10, RETENTION),
                       ApiErrorId.ERR_WINBACK_TARGET_NOT_FOUND, 404)
        validate_error(api_client.get_cohort_snapshot(unknown % 11, RETENTION),
                       ApiErrorId.ERR_COHORT_SNAPSHOT_NOT_FOUND, 404)


class TestIdentificationBeforePermission:

    def test_a_missing_header_and_an_undeclared_role_are_both_unauthenticated(self):
        """Neither request can be identified, so neither reaches the role list.

        PRD §2.1: "If either header is absent, or if `X-User-Role` is not one of the five
        role names below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/errors/missing_x_user_id_header_or_unknown_role_returns_unauthenticated
        """
        set_clock("2026-01-10")
        plan = new_core_plan()

        validate_error(api_client.get_plan(plan["id"], {}),
                       ApiErrorId.ERR_UNAUTHENTICATED, 401)
        validate_error(
            api_client.get_plan(plan["id"], build_user_headers("rm_1", "RetentionManager")),
            ApiErrorId.ERR_UNAUTHENTICATED, 401)
