"""Identity, path-existence and state entries of the error catalogue.

A request carrying no identity headers is unauthenticated before its body is even
parsed, a role name the system does not declare is unauthorized rather than
unauthenticated, every path identifier answers with its own not-found code, and a
certification renewal or a channel decision attempted from a state the resource's
own machine does not permit is refused without a partial write.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_success,
)
from test_helpers import api_errors as E
from test_helpers import constants as c
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import (
    CHANNEL_MANAGER,
    COMPLIANCE_OFFICER,
    PLANT_MANAGER,
    PRODUCT_ENGINEER,
    TRAINING_ADMIN,
    WARRANTY_ANALYST,
    headers_without_identity,
    make_headers,
)


class TestIdentityHeadersRequired:
    """Both identity headers are mandatory on every endpoint."""

    def test_01_registration_without_any_identity_headers_rejected(self, api):
        """A registration sent with no identity headers at all is refused for its
        missing identity, not for the two body faults it also carries.

        PRD: "If either header is absent or present but empty, the request is rejected with `ERR_UNAUTHENTICATED` and HTTP 401 — this check runs before anything else, including body parsing and path resolution."
        Design: Corner/errors/request_without_identity_headers_rejected
        """
        # The body names an undeclared drum alloy and offers a payment module an
        # on-premises machine may not carry, so a body-first implementation would
        # answer with a schema error instead.
        faulty_body = f.machine_model_payload(
            drum_alloy_grade="TITANIUM",
            payment_module_options=["COIN"],
        )

        rejected = api.create_machine_model(faulty_body, headers_without_identity())
        validate_error(rejected, E.ERR_UNAUTHENTICATED, expected_status=401)

        catalogue = validate_success(
            api.list_machine_models(PRODUCT_ENGINEER), expected_status=200
        )
        assert catalogue == [], f"An unauthenticated request stored a row: {catalogue}"

    def test_02_role_header_alone_is_not_an_identity(self, api):
        """Naming a role without naming the acting principal is unauthenticated,
        and so is presenting an empty principal.

        PRD: "Every request must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming the capacity in which that principal is acting."
        Design: Corner/errors/request_without_identity_headers_rejected
        """
        role_only = dict(headers_without_identity())
        role_only["X-User-Role"] = c.ROLE_PRODUCT_ENGINEER
        validate_error(
            api.create_machine_model(f.machine_model_payload(), role_only),
            E.ERR_UNAUTHENTICATED,
            expected_status=401,
        )

        empty_principal = make_headers("", c.ROLE_PRODUCT_ENGINEER)
        validate_error(
            api.create_machine_model(f.machine_model_payload(), empty_principal),
            E.ERR_UNAUTHENTICATED,
            expected_status=401,
        )

        catalogue = validate_success(
            api.list_machine_models(PRODUCT_ENGINEER), expected_status=200
        )
        assert catalogue == [], f"An unauthenticated request stored a row: {catalogue}"


class TestUndeclaredRoleHeader:
    """A role name outside the nine declared roles is an authorization failure."""

    def test_01_role_name_the_system_does_not_declare_rejected(self, api):
        """A plausible but undeclared job title is refused as unauthorized, even
        though the principal is named and the body is also unacceptable.

        PRD: "If `X-User-Role` is not one of the nine role names below, or if it is a valid role name that the addressed endpoint does not list as authorized, the request is rejected with `ERR_UNAUTHORIZED` and HTTP 403."
        Design: Corner/errors/undeclared_role_header_rejected
        """
        invented_role = make_headers("u-xx-01", "PlantSupervisor")

        rejected = api.create_machine_model(
            f.machine_model_payload(drum_alloy_grade="TITANIUM"), invented_role
        )
        validate_error(rejected, E.ERR_UNAUTHORIZED, expected_status=403)

        catalogue = validate_success(
            api.list_machine_models(PRODUCT_ENGINEER), expected_status=200
        )
        assert catalogue == [], f"An unauthorized request stored a row: {catalogue}"

        # A reading endpoint is guarded by exactly the same check.
        validate_error(
            api.list_machine_models(invented_role),
            E.ERR_UNAUTHORIZED,
            expected_status=403,
        )


class TestUnknownPathIdentifiers:
    """Every addressable resource answers an unknown identifier with its own code."""

    def test_01_unknown_machine_model_id(self, api):
        """An unknown model identifier reports the model as missing.

        PRD: "A machine-model identifier in the path resolves to a stored model — otherwise `ERR_MODEL_NOT_FOUND`, HTTP 404."
        Design: Corner/errors/unknown_path_ids_each_return_their_own_not_found_code
        """
        rejected = api.get_machine_model(NON_EXISTENT_UUID, PRODUCT_ENGINEER)
        validate_error(rejected, E.ERR_MODEL_NOT_FOUND, expected_status=404)
        assert rejected.json()["data"]["message"], "A 404 must carry a message"

    def test_02_unknown_rebate_program_id(self, api):
        """An unknown rebate-program identifier reports the program as missing.

        PRD: "A rebate-program identifier in the path resolves to a stored program — otherwise `ERR_PROGRAM_NOT_FOUND`, HTTP 404."
        Design: Corner/errors/unknown_path_ids_each_return_their_own_not_found_code
        """
        validate_error(
            api.get_rebate_program(NON_EXISTENT_UUID, COMPLIANCE_OFFICER),
            E.ERR_PROGRAM_NOT_FOUND,
            expected_status=404,
        )

    def test_03_unknown_certification_dossier_id(self, api):
        """An unknown dossier identifier reports the dossier as missing.

        PRD: "A dossier identifier in the path resolves to a stored dossier — otherwise `ERR_DOSSIER_NOT_FOUND`, HTTP 404."
        Design: Corner/errors/unknown_path_ids_each_return_their_own_not_found_code
        """
        validate_error(
            api.get_certification_dossier(NON_EXISTENT_UUID, COMPLIANCE_OFFICER),
            E.ERR_DOSSIER_NOT_FOUND,
            expected_status=404,
        )

    def test_04_unknown_service_part_id(self, api):
        """An unknown part identifier reports the part as missing.

        PRD: "A service-part identifier in the path resolves to a stored part — otherwise `ERR_PART_NOT_FOUND`, HTTP 404."
        Design: Corner/errors/unknown_path_ids_each_return_their_own_not_found_code
        """
        validate_error(
            api.get_service_part(NON_EXISTENT_UUID, PRODUCT_ENGINEER),
            E.ERR_PART_NOT_FOUND,
            expected_status=404,
        )

    def test_05_unknown_assembly_station_id(self, api):
        """An unknown station identifier reports the station as missing.

        PRD: "An assembly-station identifier in the path resolves to a stored station — otherwise `ERR_STATION_NOT_FOUND`, HTTP 404."
        Design: Corner/errors/unknown_path_ids_each_return_their_own_not_found_code
        """
        validate_error(
            api.get_assembly_station(NON_EXISTENT_UUID, PLANT_MANAGER),
            E.ERR_STATION_NOT_FOUND,
            expected_status=404,
        )

    def test_06_unknown_technician_id(self, api):
        """An unknown technician identifier reports the technician as missing.

        PRD: "A technician identifier in the path resolves to a stored technician — otherwise `ERR_TECHNICIAN_NOT_FOUND`, HTTP 404."
        Design: Corner/errors/unknown_path_ids_each_return_their_own_not_found_code
        """
        validate_error(
            api.get_technician(NON_EXISTENT_UUID, TRAINING_ADMIN),
            E.ERR_TECHNICIAN_NOT_FOUND,
            expected_status=404,
        )

    def test_07_unknown_build_order_id(self, api):
        """An unknown build-order identifier reports the build order as missing.

        PRD: "A build-order identifier in the path resolves to a stored build order — otherwise `ERR_BUILD_NOT_FOUND`, HTTP 404."
        Design: Corner/errors/unknown_path_ids_each_return_their_own_not_found_code
        """
        validate_error(
            api.get_build_order(NON_EXISTENT_UUID, PLANT_MANAGER),
            E.ERR_BUILD_NOT_FOUND,
            expected_status=404,
        )

    def test_08_unknown_station_log_id(self, api):
        """An unknown station-log identifier reports the log as missing.

        PRD: "A station-log identifier in the path resolves to a stored log — otherwise `ERR_LOG_NOT_FOUND`, HTTP 404."
        Design: Corner/errors/unknown_path_ids_each_return_their_own_not_found_code
        """
        validate_error(
            api.get_station_log(NON_EXISTENT_UUID, PLANT_MANAGER),
            E.ERR_LOG_NOT_FOUND,
            expected_status=404,
        )

    def test_09_unknown_distributor_id(self, api):
        """An unknown distributor identifier reports the distributor as missing.

        PRD: "A distributor identifier in the path resolves to a stored distributor — otherwise `ERR_DISTRIBUTOR_NOT_FOUND`, HTTP 404."
        Design: Corner/errors/unknown_path_ids_each_return_their_own_not_found_code
        """
        validate_error(
            api.get_distributor(NON_EXISTENT_UUID, CHANNEL_MANAGER),
            E.ERR_DISTRIBUTOR_NOT_FOUND,
            expected_status=404,
        )

    def test_10_unknown_quote_id(self, api):
        """An unknown quote identifier reports the quote as missing.

        PRD: "A quote identifier in the path resolves to a stored package quote — otherwise `ERR_QUOTE_NOT_FOUND`, HTTP 404."
        Design: Corner/errors/unknown_path_ids_each_return_their_own_not_found_code
        """
        validate_error(
            api.get_quote(NON_EXISTENT_UUID, CHANNEL_MANAGER),
            E.ERR_QUOTE_NOT_FOUND,
            expected_status=404,
        )

    def test_11_unknown_quote_line_id(self, api):
        """An unknown line identifier read directly reports the line as missing.

        PRD: "The `line_id` segment resolves to a quote line whose `quote_id` equals the quote already resolved by the preceding rule — otherwise `ERR_QUOTE_LINE_NOT_FOUND`, HTTP 404."
        Design: Corner/errors/unknown_path_ids_each_return_their_own_not_found_code
        """
        validate_error(
            api.get_quote_line(NON_EXISTENT_UUID, CHANNEL_MANAGER),
            E.ERR_QUOTE_LINE_NOT_FOUND,
            expected_status=404,
        )

    def test_12_unknown_warranty_claim_id(self, api):
        """An unknown claim identifier reports the claim as missing.

        PRD: "A warranty-claim identifier in the path resolves to a stored claim — otherwise `ERR_CLAIM_NOT_FOUND`, HTTP 404."
        Design: Corner/errors/unknown_path_ids_each_return_their_own_not_found_code
        """
        validate_error(
            api.get_warranty_claim(NON_EXISTENT_UUID, WARRANTY_ANALYST),
            E.ERR_CLAIM_NOT_FOUND,
            expected_status=404,
        )


class TestRenewalBeforeAnyGrant:
    """A renewal presupposes a credential that exists."""

    def test_01_renew_on_a_never_certified_technician_rejected(self, api):
        """A freshly badged technician cannot have their certification renewed,
        because a renewal only runs from ACTIVE or EXPIRED, and the refusal leaves
        the record exactly as registration left it.

        PRD: "A grant is legal from `UNCERTIFIED`, from `EXPIRED` and from `REVOKED`; a renewal is legal from `ACTIVE` and from `EXPIRED`; a revocation is legal only from `ACTIVE`."
        Design: Corner/errors/renew_before_any_grant_rejected
        """
        technician = fx.make_technician(api)
        assert technician["cert_state"] == "UNCERTIFIED"

        rejected = api.create_certification_action(
            technician["id"],
            f.renew_payload(scopes=["DRUM_FAB"]),
            TRAINING_ADMIN,
        )
        validate_error(rejected, E.ERR_TECHNICIAN_STATE_INVALID, expected_status=409)

        unchanged = validate_success(
            api.get_technician(technician["id"], TRAINING_ADMIN), expected_status=200
        )
        assert unchanged["cert_state"] == "UNCERTIFIED"
        assert unchanged["cert_scopes"] == []
        assert unchanged["cert_expires_on"] is None
        assert unchanged["last_cert_action_at"] is None
        assert unchanged["revocation_count"] == 0
        assert unchanged["version"] == 1

        # A grant is the transition this state does allow.
        granted = validate_success(
            api.create_certification_action(
                technician["id"], f.grant_payload(scopes=["DRUM_FAB"]), TRAINING_ADMIN
            ),
            expected_status=200,
        )
        assert granted["cert_state"] == "ACTIVE"
        assert granted["cert_scopes"] == ["DRUM_FAB"]
        assert granted["version"] == 2


class TestChannelDecisionStateGuard:
    """A channel decision is only meaningful on a quote awaiting one."""

    def test_01_approval_of_a_draft_quote_rejected(self, api):
        """A quote the distributor has not yet submitted cannot be approved, and
        the refusal records no decision and no verified score.

        PRD: "A `ChannelManager` decides a `SUBMITTED` quote, submitting a `decision` of `APPROVE`, `DECLINE` or `REQUEST_REVISION` with an optional `note`; a decision on a quote in any other state is `ERR_QUOTE_STATE_INVALID`."
        Design: Corner/errors/decision_on_draft_quote_rejected
        """
        channel = fx.make_authorized_distributor(api)
        quote = fx.make_quote(api, channel, financing_program="NONE")
        assert quote["quote_state"] == "DRAFT"

        # The verified score is supplied so the schema check cannot be the reason.
        rejected = api.decide_quote(
            quote["id"],
            f.quote_decision_payload("APPROVE", verified_credit_score=740),
            CHANNEL_MANAGER,
        )
        validate_error(rejected, E.ERR_QUOTE_STATE_INVALID, expected_status=409)

        unchanged = validate_success(
            api.get_quote(quote["id"], channel["headers"]), expected_status=200
        )
        assert unchanged["quote_state"] == "DRAFT"
        assert unchanged["decided_by_user_id"] is None
        assert unchanged["verified_credit_score"] is None
        assert unchanged["final_apr_bp"] is None
        assert unchanged["revision_round"] == 0
        assert unchanged["version"] == 1
