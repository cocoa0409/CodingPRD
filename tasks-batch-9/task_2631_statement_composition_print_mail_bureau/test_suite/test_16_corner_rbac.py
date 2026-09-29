"""Authorisation probed where a weaker model would leak.

The six roles are peers rather than a hierarchy, authentication outranks
authorisation, one read is not shared with the client-facing role, and the two
duty separations key on the acting operator identifier rather than on the role.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_client import ApiClient
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import (
    ADMIN_USER_ID,
    ADMIN_USER_ID_2,
    BUREAU_ADMIN,
    CLIENT_LIAISON,
    COMPOSITION_OPERATOR,
    INTEGRITY_AUDITOR,
    NO_AUTH_HEADERS,
    NO_ROLE_HEADERS,
    NO_USER_ID_HEADERS,
    POSTAGE_CONTROLLER,
    POSTAGE_USER_ID,
    POSTAGE_USER_ID_2,
    PRODUCTION_SCHEDULER,
    headers_for,
)
from test_helpers.types import Role


class TestRolesArePeersNotAHierarchy:
    """Five exclusive writes each attempted by a neighbouring role, and one read
    attempted by all of them."""

    def test_every_exclusive_write_refuses_the_neighbour_while_the_read_stays_shared(
        self, api: ApiClient
    ):
        """PRD §2.1: "If both headers are well formed but the named role is not among the
        roles authorised for the endpoint being called, the request is rejected with
        `ERR_UNAUTHORIZED` (HTTP 403)."

        No role inherits another's writes — the administrator is refused the
        liaison's intake exactly as the liaison is refused client registration —
        while the retrieval endpoints remain open to every role and none of the
        refused writes persists anything.

        Design: Corner/rbac/each_exclusive_write_rejects_the_neighbouring_role_while_reads_stay_shared
        """
        fx.set_clock(api)
        client = fx.register_client(
            api,
            client_code="CLR1",
            name="Peer Role Periodicals",
            dr_readiness_required=False,
        )

        liaison_write = api.create_client(
            f.client_payload("CLR1LIA", "Liaison Overreach"), CLIENT_LIAISON
        )
        validate_error(liaison_write, ApiErrorId.UNAUTHORIZED.value, 403)

        admin_write = api.create_data_file(
            f.data_file_payload(
                client["id"],
                file_name="r1-admin.csv",
                declared_record_count=1,
                declared_control_total_cents=4000,
            ),
            BUREAU_ADMIN,
        )
        validate_error(admin_write, ApiErrorId.UNAUTHORIZED.value, 403)

        scheduler_write = api.create_dr_site(
            f.dr_site_payload("DR-R1", 5), PRODUCTION_SCHEDULER
        )
        validate_error(scheduler_write, ApiErrorId.UNAUTHORIZED.value, 403)

        postage_write = api.create_press_line(
            f.press_line_payload(
                "PL-R1",
                capabilities=["DUPLEX"],
                sheets_per_hour=600,
                daily_sheet_capacity=1000,
            ),
            POSTAGE_CONTROLLER,
        )
        validate_error(postage_write, ApiErrorId.UNAUTHORIZED.value, 403)

        auditor_write = api.create_entry_facility(
            f.entry_facility_payload("EF-R1"), INTEGRITY_AUDITOR
        )
        validate_error(auditor_write, ApiErrorId.UNAUTHORIZED.value, 403)

        for headers in (
            BUREAU_ADMIN,
            CLIENT_LIAISON,
            COMPOSITION_OPERATOR,
            PRODUCTION_SCHEDULER,
            POSTAGE_CONTROLLER,
            INTEGRITY_AUDITOR,
        ):
            shared = get_success_data(api.get_client(client["id"], headers))
            assert shared["client_code"] == "CLR1"

        rows, meta = validate_paginated(
            api.list_clients(INTEGRITY_AUDITOR, {"limit": 100})
        )
        assert meta["total_count"] == 1
        assert [row["client_code"] for row in rows] == ["CLR1"]


class TestAuthenticationOutranksAuthorisation:
    """The same registration attempted with each identity header missing in turn,
    then with both present."""

    def test_absent_identity_headers_are_refused_before_the_role_is_considered(
        self, api: ApiClient
    ):
        """PRD §2.1: "If either header is absent, or if `X-User-Role` is not one of the six
        declared role names, the request is rejected with `ERR_MISSING_AUTH_HEADERS`
        (HTTP 401)."

        A request with no role, a request with no user identifier and a read with
        neither are all refused for missing authentication rather than for the
        wrong role, and the identical body succeeds once both headers are supplied.

        Design: Corner/rbac/request_missing_auth_headers_is_rejected_before_any_role_check
        """
        fx.set_clock(api)

        no_role = api.create_client(
            f.client_payload("CLR2", "Headerless Holdings"), NO_ROLE_HEADERS
        )
        validate_error(no_role, ApiErrorId.MISSING_AUTH_HEADERS.value, 401)

        no_user = api.create_client(
            f.client_payload("CLR2B", "Anonymous Anonymous"), NO_USER_ID_HEADERS
        )
        validate_error(no_user, ApiErrorId.MISSING_AUTH_HEADERS.value, 401)

        no_headers = api.list_clients(NO_AUTH_HEADERS, {"limit": 100})
        validate_error(no_headers, ApiErrorId.MISSING_AUTH_HEADERS.value, 401)

        created = get_success_data(
            api.create_client(
                f.client_payload("CLR2", "Headerless Holdings"), BUREAU_ADMIN
            ),
            201,
        )
        assert created["client_code"] == "CLR2"

        _rows, meta = validate_paginated(
            api.list_clients(BUREAU_ADMIN, {"limit": 100})
        )
        assert meta["total_count"] == 1


class TestIntegritySummaryIsNotSharedWithTheLiaison:
    """One composed job read through the summary sub-resource and through the
    plain job endpoint."""

    def test_the_liaison_is_refused_the_summary_but_keeps_the_plain_job_read(
        self, api: ApiClient
    ):
        """PRD §2.1: "The computed integrity summary for a composition job is available to
        `BureauAdmin`, `CompositionOperator`, `ProductionScheduler`, `PostageController`
        and `IntegrityAuditor`, but not to `ClientLiaison` — the bureau does not expose
        its internal integrity failure counters to the client-facing desk."

        The integrity summary is the one read the client-facing role does not
        hold, so the liaison who lodged the file is refused it while the auditor
        reads it and the liaison's ordinary job read still succeeds.

        Design: Corner/rbac/integrity_summary_read_is_withheld_from_the_client_liaison
        """
        fx.set_clock(api)
        client = fx.register_client(
            api,
            client_code="CLR3",
            name="Opaque Accounting Assurance",
            dr_readiness_required=False,
        )
        template = fx.create_active_template(
            api,
            client["id"],
            template_code="T-R3",
            sheets_per_document=1,
            duplex_required=False,
            color_pages_per_document=0,
            mail_class_preference="FIRST_CLASS",
        )
        bundle = fx.accepted_file(
            api,
            client["id"],
            [
                fx.record_spec(
                    "ABC4501",
                    1,
                    4000,
                    address_line1="4500 Opaque Overlook",
                    postal_code_plus4="4501",
                )
            ],
            file_name="r3.csv",
        )
        job = fx.compose_job(api, bundle.id, template["id"])

        denied = api.get_integrity_summary(job["id"], CLIENT_LIAISON)
        validate_error(denied, ApiErrorId.UNAUTHORIZED.value, 403)

        summary = get_success_data(
            api.get_integrity_summary(job["id"], INTEGRITY_AUDITOR)
        )
        assert summary["accountable_piece_count"] == 1
        assert summary["matched_piece_count"] == 0
        assert summary["integrity_status"] == "PENDING"

        shared = get_success_data(api.get_composition_job(job["id"], CLIENT_LIAISON))
        assert shared["status"] == "COMPOSED"


class TestDutySeparationsKeyOnTheOperatorNotTheRole:
    """One job whose composer and sealer then attempt the two acts they are barred
    from, followed by their colleagues in the same roles."""

    def test_the_sealer_cannot_manifest_and_the_composer_cannot_close(
        self, api: ApiClient
    ):
        """PRD §2.8: "When a presort batch is manifested, the acting `X-User-ID` must
        differ from the `sealed_by_user_id` recorded on that batch at seal time; if the
        two are equal the request is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP
        403)."

        Both separations compare user identifiers rather than roles, so the
        controller who sealed is refused the manifest that a second controller
        performs, and the administrator who composed is refused the closure that a
        second administrator performs.

        Design: Corner/rbac/segregation_of_duties_blocks_the_sealer_from_manifesting_and_the_composer_from_closing
        """
        pipeline = fx.sealed_batches(
            api,
            client_code="CLR4",
            client_overrides={
                "name": "Fourfold Duty Financial",
                "dr_readiness_required": False,
            },
            fund_cents=100000,
            template_code="T-R4",
            template_overrides={
                "sheets_per_document": 1,
                "duplex_required": False,
                "color_pages_per_document": 0,
                "mail_class_preference": "FIRST_CLASS",
            },
            press_line_code="PL-R4",
            press_line_overrides={"capabilities": ["DUPLEX"]},
            facility_code="EF-R4",
            facility_overrides={"discount_bp_first_class": 850},
            with_facility=True,
            file_name="r4.csv",
            specs=[
                fx.record_spec(
                    "ABC4601",
                    1,
                    4000,
                    address_line1="4600 Duty Division Drive",
                    postal_code_plus4="4601",
                )
            ],
            compose_user_id=ADMIN_USER_ID,
            seal_user_id=POSTAGE_USER_ID,
        )
        job = fx.read_job(api, pipeline.job["id"])
        assert job["composed_by_user_id"] == ADMIN_USER_ID
        assert job["status"] == "VERIFIED"

        batches = fx.list_batches(api, job["id"])
        assert len(batches) == 1
        batch = batches[0]
        assert batch["status"] == "SEALED"
        assert batch["sealed_by_user_id"] == POSTAGE_USER_ID

        self_manifest = api.manifest_batch(
            batch["id"],
            f.manifest_payload(
                pipeline.facility["id"],
                fx.DEFAULT_INDUCTION_START,
                fx.DEFAULT_INDUCTION_END,
            ),
            headers_for(Role.POSTAGE_CONTROLLER.value, POSTAGE_USER_ID),
        )
        validate_error(self_manifest, ApiErrorId.SEGREGATION_OF_DUTIES.value, 403)
        assert fx.read_batch(api, batch["id"])["status"] == "SEALED"

        manifested = fx.manifest_batch(
            api,
            batch["id"],
            pipeline.facility["id"],
            user_id=POSTAGE_USER_ID_2,
        )
        assert manifested["status"] == "MANIFESTED"
        assert manifested["manifested_by_user_id"] == POSTAGE_USER_ID_2
        assert fx.read_job(api, job["id"])["status"] == "MANIFESTED"

        self_close = api.close_job(
            job["id"], headers_for(Role.BUREAU_ADMIN.value, ADMIN_USER_ID)
        )
        validate_error(self_close, ApiErrorId.SEGREGATION_OF_DUTIES.value, 403)
        assert fx.read_job(api, job["id"])["status"] == "MANIFESTED"

        closed = fx.close_job(api, job["id"], user_id=ADMIN_USER_ID_2)
        assert closed["status"] == "CLOSED"
        assert closed["total_sheet_count"] == 1
        assert closed["composition_charge_cents"] == 9
        assert closed["insert_charge_cents"] == 0
        assert closed["pre_discount_subtotal_cents"] == 9
        assert closed["volume_discount_cents"] == 0
        assert closed["expedite_fee_cents"] == 0
        assert closed["billing_total_cents"] == 9
