"""Access control: role partition, entity-backed scopes, duty separation and identity."""

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    factories,
    fixtures as fx,
    validate_error,
    validate_success,
)
from test_helpers.test_users import (
    ADMIN_HEADERS,
    ADMIN_USER_ID,
    COORDINATOR_ALT_USER_ID,
    COORDINATOR_HEADERS,
    COORDINATOR_USER_ID,
    MANAGER_HEADERS,
    OFFICER_ALT_HEADERS,
    OFFICER_ALT_USER_ID,
    OFFICER_HEADERS,
    OFFICER_USER_ID,
    make_headers,
    make_laboratory_user_headers,
    make_supplier_user_headers,
)


STARTUP_CLOCK = "2026-08-01T00:00:00Z"
LATE_ATTESTATION = "2027-12-31T00:00:00Z"

OPAQUE_HEADERS = {
    "ComplianceAdministrator": ADMIN_HEADERS,
    "TestCoordinator": COORDINATOR_HEADERS,
    "CertificationOfficer": OFFICER_HEADERS,
    "DistributionManager": MANAGER_HEADERS,
}


def _refuse_every_other_opaque_role(call, allowed_role):
    """Every opaque role except `allowed_role` is refused with the role code."""
    for role, headers in OPAQUE_HEADERS.items():
        if role == allowed_role:
            continue
        validate_error(call(headers), ApiErrorId.ROLE_NOT_PERMITTED.value, 403)


def _only_this_role_succeeds(call, allowed_role, expected_status=200):
    _refuse_every_other_opaque_role(call, allowed_role)
    return validate_success(call(OPAQUE_HEADERS[allowed_role]), expected_status)


class TestAdministratorOwnsReferenceDataOnly:
    """The reference-data role holds every registration write and no operational write."""

    def test_the_administrator_exclusive_writes_refuse_all_five_other_roles(self, api):
        """PRD 2.1: "A `ComplianceAdministrator` owns the regulatory reference data — rules,
        categories and the mappings between them — together with the party register of
        suppliers, laboratories and accreditation scopes, product registration,
        bill-of-materials entry, product archival, the logical clock, and the immutable
        material-change log."

        Design: Corner/rbac/corner_rbac_compliance_administrator_owns_reference_data_and_nothing_operational
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env = fx.scoped_product_env(api)
        laboratory_id = env["laboratory"]["id"]
        supplier_id = env["supplier"]["id"]
        fresh_rule = fx.create_rule(api)
        fresh_category = fx.create_category(api)
        outsiders = [
            COORDINATOR_HEADERS,
            OFFICER_HEADERS,
            MANAGER_HEADERS,
            make_laboratory_user_headers(laboratory_id),
            make_supplier_user_headers(supplier_id),
        ]
        assert len(outsiders) == 5

        calls = [
            lambda headers: api.create_rule(factories.rule_payload(), headers=headers),
            lambda headers: api.create_category(factories.category_payload(), headers=headers),
            lambda headers: api.create_supplier(factories.supplier_payload(), headers=headers),
            lambda headers: api.create_laboratory(
                factories.laboratory_payload(), headers=headers
            ),
            lambda headers: api.record_attestation(
                laboratory_id, {"attestation_valid_through": LATE_ATTESTATION}, headers=headers
            ),
            lambda headers: api.create_product(
                factories.product_payload(env["category"]["id"]), headers=headers
            ),
            lambda headers: api.create_component_part(
                env["product"]["id"],
                factories.component_part_payload(supplier_id),
                headers=headers,
            ),
            lambda headers: api.record_material_change(
                factories.material_change_payload(env["product"]["id"]), headers=headers
            ),
            lambda headers: api.set_clock(STARTUP_CLOCK, headers=headers),
            lambda headers: api.create_mapping(
                factories.mapping_payload(fresh_category["id"], fresh_rule["id"]),
                headers=headers,
            ),
            lambda headers: api.create_accreditation(
                laboratory_id,
                factories.accreditation_payload(fresh_rule["id"]),
                headers=headers,
            ),
            lambda headers: api.retire_mapping(env["mappings"][0]["id"], headers=headers),
            lambda headers: api.suspend_accreditation(
                env["accreditations"][0]["id"],
                {"suspension_reason": "Proficiency testing lapse"},
                headers=headers,
            ),
            lambda headers: api.set_laboratory_operational_state(
                laboratory_id, {"operational_state": "BARRED"}, headers=headers
            ),
        ]
        assert len(calls) == 14
        for call in calls:
            for headers in outsiders:
                validate_error(call(headers), ApiErrorId.ROLE_NOT_PERMITTED.value, 403)
            response = call(ADMIN_HEADERS)
            assert response.status_code in (200, 201)

    def test_the_administrator_cannot_book_rely_certify_or_move_inventory(self, api):
        """PRD 2.1: "This role deliberately cannot book tests, cannot record reliance
        decisions, cannot issue certificates and cannot move inventory."

        Design: Corner/rbac/corner_rbac_compliance_administrator_owns_reference_data_and_nothing_operational
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env = fx.evidence_complete_env(api)
        product = fx.get_product(api, env["product"]["id"])
        certificate = fx.draft_certificate(api, product["id"], product["version"])
        fx.issue_certificate(api, certificate["id"])
        fx.furnish_certificate(api, certificate["id"])
        batch = fx.create_batch(api, product["id"], certificate["id"])
        part_certificate = fx.submit_part_certificate(
            api,
            env["parts"][0]["id"],
            env["supplier"]["id"],
            env["laboratory"]["id"],
            env["rules"][0]["id"],
        )
        draft_product = fx.create_product(api, env["category"]["id"])

        validate_error(
            api.create_test_order(
                factories.test_order_payload(
                    product["id"],
                    env["plan"]["id"],
                    env["laboratory"]["id"],
                    env["rules"][0]["id"],
                ),
                headers=ADMIN_HEADERS,
            ),
            ApiErrorId.ROLE_NOT_PERMITTED.value,
            403,
        )
        validate_error(
            api.record_reliance_documentation(
                part_certificate["id"],
                {"reliance_decision": "RELY", "reliance_documentation_ref": "PKG-001"},
                headers=ADMIN_HEADERS,
            ),
            ApiErrorId.ROLE_NOT_PERMITTED.value,
            403,
        )
        validate_error(
            api.release_batch(batch["id"], headers=ADMIN_HEADERS),
            ApiErrorId.ROLE_NOT_PERMITTED.value,
            403,
        )
        validate_error(
            api.submit_for_certification(
                draft_product["id"],
                {"evidence_path": "FULL_PRODUCT_TEST"},
                headers=ADMIN_HEADERS,
            ),
            ApiErrorId.ROLE_NOT_PERMITTED.value,
            403,
        )
        assert fx.get_batch(api, batch["id"])["distribution_state"] == "HELD"
        assert fx.get_product(api, draft_product["id"])["certification_state"] == "DRAFT"

    def test_the_role_refusal_is_decided_before_existence_and_before_state(self, api):
        """PRD 2.11 rank 2: "Role authorisation — the caller's role appears among the roles
        authorised for the target operation → `ERR_ROLE_NOT_PERMITTED` (403). Applies to every
        endpoint." — rank 2 sits above rank 6 existence and rank 8 onward state.

        Design: Corner/rbac/corner_rbac_compliance_administrator_owns_reference_data_and_nothing_operational
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env = fx.distributed_env(api)
        released_batch = env["batches"][0]
        assert released_batch["distribution_state"] == "RELEASED"

        validate_error(
            api.issue_certificate(NON_EXISTENT_UUID, headers=ADMIN_HEADERS),
            ApiErrorId.ROLE_NOT_PERMITTED.value,
            403,
        )
        validate_error(
            api.release_batch(NON_EXISTENT_UUID, headers=ADMIN_HEADERS),
            ApiErrorId.ROLE_NOT_PERMITTED.value,
            403,
        )
        validate_error(
            api.release_batch(released_batch["id"], headers=ADMIN_HEADERS),
            ApiErrorId.ROLE_NOT_PERMITTED.value,
            403,
        )
        validate_error(
            api.archive_product(NON_EXISTENT_UUID, headers=COORDINATOR_HEADERS),
            ApiErrorId.ROLE_NOT_PERMITTED.value,
            403,
        )

    def test_the_administrator_may_read_every_collection_including_the_summary(self, api):
        """PRD 4 lists ComplianceAdministrator among the authorised roles of every read,
        including "GET `/compliance/products/{product_id}/compliance-summary`".

        Design: Corner/rbac/corner_rbac_compliance_administrator_owns_reference_data_and_nothing_operational
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env = fx.distributed_env(api)
        product_id = env["product"]["id"]

        reads = [
            api.get_rule(env["rules"][0]["id"], headers=ADMIN_HEADERS),
            api.get_category(env["category"]["id"], headers=ADMIN_HEADERS),
            api.get_supplier(env["supplier"]["id"], headers=ADMIN_HEADERS),
            api.get_laboratory(env["laboratory"]["id"], headers=ADMIN_HEADERS),
            api.get_product(product_id, headers=ADMIN_HEADERS),
            api.get_compliance_summary(product_id, headers=ADMIN_HEADERS),
            api.get_sampling_plan(env["plan"]["id"], headers=ADMIN_HEADERS),
            api.get_test_order(env["orders"][0]["id"], headers=ADMIN_HEADERS),
            api.get_certificate(env["certificate"]["id"], headers=ADMIN_HEADERS),
            api.get_production_batch(env["batches"][0]["id"], headers=ADMIN_HEADERS),
        ]
        for response in reads:
            validate_success(response, 200)


class TestFourOpaqueRolesPartitionWrites:
    """Every mutating endpoint belongs to exactly one opaque role, cell by cell."""

    def test_one_case_is_worked_by_the_manager_the_coordinator_and_the_officer(self, api):
        """PRD 2.1: "A `DistributionManager` records production batches and their tracking
        labels, furnishes and recalls certificate accompaniment for shipments, releases and
        rescinds releases, and issues the formal stop-distribution instruction" while a
        `TestCoordinator` "orders retest rounds" and a `CertificationOfficer` "files
        corrective action plans and closes noncompliance cases".

        Design: Corner/rbac/corner_rbac_four_opaque_roles_partition_the_write_surface_with_no_overlap
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env = fx.failed_case_env(api, release=False)
        case_id = env["case"]["id"]
        laboratory_id = env["laboratory"]["id"]
        assert env["case"]["case_state"] == "OPEN"

        case = _only_this_role_succeeds(
            lambda headers: api.issue_stop_distribution(
                case_id, {"scope_variant": "BATCH_SCOPED"}, headers=headers
            ),
            "DistributionManager",
        )
        assert case["case_state"] == "STOP_DISTRIBUTION_ISSUED"

        case = _only_this_role_succeeds(
            lambda headers: api.order_retest(
                case_id,
                factories.retest_payload(env["plan"]["id"], laboratory_id),
                headers=headers,
            ),
            "TestCoordinator",
        )
        assert case["case_state"] == "RETEST_ORDERED"

        retest_order_id = case["active_retest_order_id"]
        fx.start_order(api, retest_order_id, laboratory_id)
        fx.report(api, retest_order_id, laboratory_id, 10)
        case = fx.get_case(api, case_id)
        assert case["case_state"] == "RETEST_PASSED"

        case = _only_this_role_succeeds(
            lambda headers: api.file_corrective_action(
                case_id,
                {
                    "expected_case_version": case["version"],
                    "corrective_action_ref": "CAPA-PARTITION-1",
                },
                headers=headers,
            ),
            "CertificationOfficer",
        )
        assert case["case_state"] == "CORRECTIVE_ACTION_APPROVED"

        case = _only_this_role_succeeds(
            lambda headers: api.close_case(case_id, headers=headers),
            "CertificationOfficer",
        )
        assert case["case_state"] == "CLOSED"

    def test_every_plan_and_order_endpoint_belongs_to_the_coordinator_alone(self, api):
        """PRD 2.1: "A `TestCoordinator` scopes products onto an evidence path, builds and
        maintains sampling plans, books third-party testing, cancels orders and orders retest
        rounds".

        Design: Corner/rbac/corner_rbac_four_opaque_roles_partition_the_write_surface_with_no_overlap
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env = fx.scoped_product_env(api, submit=False)
        product_id = env["product"]["id"]

        product = _only_this_role_succeeds(
            lambda headers: api.submit_for_certification(
                product_id, {"evidence_path": "FULL_PRODUCT_TEST"}, headers=headers
            ),
            "TestCoordinator",
        )
        assert product["certification_state"] == "FULL_TEST_PROGRAM"

        plan = _only_this_role_succeeds(
            lambda headers: api.create_sampling_plan(
                product_id, factories.sampling_plan_payload(), headers=headers
            ),
            "TestCoordinator",
            201,
        )
        plan = _only_this_role_succeeds(
            lambda headers: api.activate_sampling_plan(plan["id"], headers=headers),
            "TestCoordinator",
        )
        assert plan["plan_state"] == "ACTIVE"

        order = _only_this_role_succeeds(
            lambda headers: api.create_test_order(
                factories.test_order_payload(
                    product_id,
                    plan["id"],
                    env["laboratory"]["id"],
                    env["rules"][0]["id"],
                ),
                headers=headers,
            ),
            "TestCoordinator",
            201,
        )
        order = _only_this_role_succeeds(
            lambda headers: api.cancel_test_order(order["id"], headers=headers),
            "TestCoordinator",
        )
        assert order["order_state"] == "CANCELLED"

        fx.set_clock(api, "2027-09-01T00:00:00Z")
        reviewed = _only_this_role_succeeds(
            lambda headers: api.periodic_review(plan["id"], headers=headers),
            "TestCoordinator",
        )
        assert reviewed["plan_state"] == "RESAMPLE_DUE"
        fx.set_clock(api, STARTUP_CLOCK)

    def test_reliance_and_certificate_issuance_belong_to_the_officer_alone(self, api):
        """PRD 2.1: "A `CertificationOfficer` decides whether to rely on a supplier's component
        certificate, drafts and issues children's product certificates, voids unissued drafts,
        files corrective action plans and closes noncompliance cases".

        Design: Corner/rbac/corner_rbac_four_opaque_roles_partition_the_write_surface_with_no_overlap
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env = fx.reliance_env(api, rely=False)
        part_certificate_id = env["part_certificates"][0]["id"]

        part_certificate = _only_this_role_succeeds(
            lambda headers: api.record_reliance_documentation(
                part_certificate_id,
                {
                    "reliance_decision": "RELY",
                    "reliance_documentation_ref": "RELIANCE-PKG-PARTITION",
                },
                headers=headers,
            ),
            "CertificationOfficer",
        )
        assert part_certificate["reliance_state"] == "RELIED_UPON"

        product = fx.get_product(api, env["product"]["id"])
        assert product["certification_state"] == "EVIDENCE_COMPLETE"

        certificate = _only_this_role_succeeds(
            lambda headers: api.draft_certificate(
                product["id"],
                factories.certificate_payload(product["version"]),
                headers=headers,
            ),
            "CertificationOfficer",
            201,
        )
        certificate = _only_this_role_succeeds(
            lambda headers: api.issue_certificate(certificate["id"], headers=headers),
            "CertificationOfficer",
        )
        assert certificate["issuance_status"] == "ISSUED"
        assert certificate["issued_by_user_id"] == OFFICER_USER_ID

    def test_only_the_officer_may_void_an_unissued_draft(self, api):
        """PRD 3.7: "A certificate that was never issued may instead be **voided**, moving
        `DRAFT → VOIDED` with its `version` incremented by 1 and no effect whatsoever on the
        product, which stays in `EVIDENCE_COMPLETE`." — PRD 2.1 gives voiding to the officer.

        Design: Corner/rbac/corner_rbac_four_opaque_roles_partition_the_write_surface_with_no_overlap
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env = fx.evidence_complete_env(api)
        product = fx.get_product(api, env["product"]["id"])
        certificate = fx.draft_certificate(api, product["id"], product["version"])

        voided = _only_this_role_succeeds(
            lambda headers: api.void_certificate(certificate["id"], headers=headers),
            "CertificationOfficer",
        )
        assert voided["issuance_status"] == "VOIDED"
        assert fx.get_product(api, product["id"])["certification_state"] == "EVIDENCE_COMPLETE"

    def test_accompaniment_and_inventory_belong_to_the_manager_alone(self, api):
        """PRD 3.8: "Physical goods enter the system as production batches, recorded by a
        `DistributionManager` against the certificate that must accompany their shipments." —
        PRD 2.1 gives the same role furnishing, recall, release and rescission.

        Design: Corner/rbac/corner_rbac_four_opaque_roles_partition_the_write_surface_with_no_overlap
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env = fx.certified_env(api)
        certificate_id = env["certificate"]["id"]
        product_id = env["product"]["id"]

        certificate = _only_this_role_succeeds(
            lambda headers: api.furnish_certificate(certificate_id, headers=headers),
            "DistributionManager",
        )
        assert certificate["accompaniment_status"] == "FURNISHED"

        batch = _only_this_role_succeeds(
            lambda headers: api.create_production_batch(
                product_id, factories.batch_payload(certificate_id), headers=headers
            ),
            "DistributionManager",
            201,
        )
        batch = _only_this_role_succeeds(
            lambda headers: api.update_tracking_label(
                batch["id"], factories.tracking_label_payload(), headers=headers
            ),
            "DistributionManager",
        )
        assert batch["tracking_label_compliant"] is True

        batch = _only_this_role_succeeds(
            lambda headers: api.release_batch(batch["id"], headers=headers),
            "DistributionManager",
        )
        assert batch["distribution_state"] == "RELEASED"
        batch = _only_this_role_succeeds(
            lambda headers: api.rescind_release(batch["id"], headers=headers),
            "DistributionManager",
        )
        assert batch["distribution_state"] == "HELD"

        certificate = _only_this_role_succeeds(
            lambda headers: api.recall_accompaniment(certificate_id, headers=headers),
            "DistributionManager",
        )
        assert certificate["accompaniment_status"] == "RECALLED_FROM_SHIPMENTS"

    def test_the_certificate_lifecycle_is_split_across_two_roles(self, api):
        """PRD 2.1: the officer "drafts and issues children's product certificates, voids
        unissued drafts" while the manager "furnishes and recalls certificate accompaniment for
        shipments" — no single actor can take a certificate from draft to shipped.

        Design: Corner/rbac/corner_rbac_four_opaque_roles_partition_the_write_surface_with_no_overlap
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env = fx.evidence_complete_env(api)
        product = fx.get_product(api, env["product"]["id"])
        certificate = fx.draft_certificate(api, product["id"], product["version"])

        validate_error(
            api.issue_certificate(certificate["id"], headers=MANAGER_HEADERS),
            ApiErrorId.ROLE_NOT_PERMITTED.value,
            403,
        )
        validate_error(
            api.furnish_certificate(certificate["id"], headers=OFFICER_HEADERS),
            ApiErrorId.ROLE_NOT_PERMITTED.value,
            403,
        )
        fx.issue_certificate(api, certificate["id"])
        validate_error(
            api.furnish_certificate(certificate["id"], headers=OFFICER_HEADERS),
            ApiErrorId.ROLE_NOT_PERMITTED.value,
            403,
        )
        fx.furnish_certificate(api, certificate["id"])
        validate_error(
            api.recall_accompaniment(certificate["id"], headers=OFFICER_HEADERS),
            ApiErrorId.ROLE_NOT_PERMITTED.value,
            403,
        )
        final = fx.get_certificate(api, certificate["id"])
        assert final["issued_by_user_id"] == OFFICER_USER_ID
        assert final["accompaniment_status"] == "FURNISHED"


class TestLaboratoryIdentityIsScopedToItsOwnOrders:
    """A LaboratoryUser holds the right role for testing writes but only on its own orders."""

    @staticmethod
    def _two_lab_env(api):
        """A two-rule product with one order at the home laboratory and one at a rival."""
        env = fx.booking_env(api, rule_specs=[{}, {}])
        rival = fx.create_laboratory(api)
        fx.attest(api, rival["id"], LATE_ATTESTATION)
        for rule in env["rules"]:
            fx.accredit(api, rival["id"], rule["id"])
        home_order = fx.book_order(
            api,
            env["product"]["id"],
            env["plan"]["id"],
            env["laboratory"]["id"],
            env["rules"][0]["id"],
        )
        rival_order = fx.book_order(
            api,
            env["product"]["id"],
            env["plan"]["id"],
            rival["id"],
            env["rules"][1]["id"],
        )
        return env, rival, home_order, rival_order

    def test_a_rival_laboratory_cannot_take_another_labs_order_into_testing(self, api):
        """PRD 2.1: "Concretely, taking an order into testing or filing its report requires that
        the order's `laboratory_id` equal `X-User-ID`; any other order is refused with
        `ERR_LAB_NOT_ASSIGNED` (HTTP 403)."

        Design: Corner/rbac/corner_rbac_laboratory_identity_is_scoped_to_its_own_orders
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env, rival, home_order, _ = self._two_lab_env(api)

        validate_error(
            api.start_testing(
                home_order["id"], headers=make_laboratory_user_headers(rival["id"])
            ),
            ApiErrorId.LAB_NOT_ASSIGNED.value,
            403,
        )
        assert fx.get_order(api, home_order["id"])["order_state"] == "SCHEDULED"
        started = fx.start_order(api, home_order["id"], env["laboratory"]["id"])
        assert started["order_state"] == "IN_TESTING"

    def test_the_scope_is_enforced_on_the_report_as_well_as_on_intake(self, api):
        """PRD 2.1: "Concretely, taking an order into testing or filing its report requires that
        the order's `laboratory_id` equal `X-User-ID`; any other order is refused with
        `ERR_LAB_NOT_ASSIGNED` (HTTP 403)."

        Design: Corner/rbac/corner_rbac_laboratory_identity_is_scoped_to_its_own_orders
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env, rival, home_order, _ = self._two_lab_env(api)
        laboratory_id = env["laboratory"]["id"]
        fx.start_order(api, home_order["id"], laboratory_id)

        validate_error(
            api.report_result(
                home_order["id"],
                {"measured_value": 10},
                headers=make_laboratory_user_headers(rival["id"]),
            ),
            ApiErrorId.LAB_NOT_ASSIGNED.value,
            403,
        )
        reported = fx.report(api, home_order["id"], laboratory_id, 10)
        assert reported["reported_by_user_id"] == laboratory_id
        assert reported["result"] == "PASS"

    def test_the_role_check_is_decided_before_the_assignment_check(self, api):
        """PRD 2.11 rank 2 is "Role authorisation ... → `ERR_ROLE_NOT_PERMITTED` (403)" and rank 3
        is "Laboratory assignment ownership — when the caller is a `LaboratoryUser`, `X-User-ID`
        equals the `laboratory_id` of the test order named in the path → `ERR_LAB_NOT_ASSIGNED`".

        Design: Corner/rbac/corner_rbac_laboratory_identity_is_scoped_to_its_own_orders
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env, rival, _, rival_order = self._two_lab_env(api)

        validate_error(
            api.start_testing(rival_order["id"], headers=COORDINATOR_HEADERS),
            ApiErrorId.ROLE_NOT_PERMITTED.value,
            403,
        )
        validate_error(
            api.start_testing(
                rival_order["id"],
                headers=make_laboratory_user_headers(env["laboratory"]["id"]),
            ),
            ApiErrorId.LAB_NOT_ASSIGNED.value,
            403,
        )

    def test_a_laboratory_may_read_the_order_list_it_is_not_assigned_to(self, api):
        """PRD 4 lists LaboratoryUser among the authorised roles of "GET
        `/compliance/test-orders`" and of "GET `/compliance/test-orders/{order_id}`", so the
        read path answers rather than refusing.

        Design: Corner/rbac/corner_rbac_laboratory_identity_is_scoped_to_its_own_orders
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env, rival, home_order, _ = self._two_lab_env(api)
        rival_headers = make_laboratory_user_headers(rival["id"])

        validate_success(
            api.list_test_orders(
                {"laboratory_id": env["laboratory"]["id"]}, headers=rival_headers
            ),
            200,
        )
        validate_success(api.get_test_order(home_order["id"], headers=rival_headers), 200)


class TestSupplierIdentityIsScopedToItsOwnParts:
    """A SupplierUser may file evidence only for the parts it supplies."""

    @staticmethod
    def _two_supplier_env(api):
        """A component-reliance product whose two parts come from two different suppliers."""
        rival = fx.create_supplier(api, reliance_agreement_state="ON_FILE")
        env = fx.scoped_product_env(
            api,
            evidence_path="COMPONENT_RELIANCE",
            supplier={"reliance_agreement_state": "ON_FILE"},
            part_specs=[{}, {"supplier_id": rival["id"]}],
        )
        return env, rival

    def test_a_rival_supplier_cannot_file_a_certificate_for_another_suppliers_part(self, api):
        """PRD 2.1: "Submitting a component part certificate requires that the part's
        `supplier_id` equal `X-User-ID`; any other part is refused with
        `ERR_SUPPLIER_NOT_PART_OWNER` (HTTP 403)."

        Design: Corner/rbac/corner_rbac_supplier_identity_is_scoped_to_the_parts_it_supplies
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env, rival = self._two_supplier_env(api)
        owned_part = env["parts"][0]
        assert owned_part["supplier_id"] == env["supplier"]["id"]

        validate_error(
            api.submit_part_certificate(
                owned_part["id"],
                factories.part_certificate_payload(
                    env["laboratory"]["id"], env["rules"][0]["id"]
                ),
                headers=make_supplier_user_headers(rival["id"]),
            ),
            ApiErrorId.SUPPLIER_NOT_PART_OWNER.value,
            403,
        )
        certificate = fx.submit_part_certificate(
            api,
            owned_part["id"],
            env["supplier"]["id"],
            env["laboratory"]["id"],
            env["rules"][0]["id"],
        )
        assert certificate["supplier_id"] == env["supplier"]["id"]
        assert certificate["reliance_state"] == "SUBMITTED"

    def test_filing_is_the_suppliers_exclusive_write_and_reliance_is_not_the_suppliers(self, api):
        """PRD 3.4: "**Component part certificates** are what a supplier submits, and only a
        `SupplierUser` acting for the owning supplier may submit one." and "The reliance decision
        belongs to the `CertificationOfficer`".

        Design: Corner/rbac/corner_rbac_supplier_identity_is_scoped_to_the_parts_it_supplies
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env, _ = self._two_supplier_env(api)
        owned_part = env["parts"][0]
        payload = factories.part_certificate_payload(
            env["laboratory"]["id"], env["rules"][0]["id"]
        )

        for headers in (ADMIN_HEADERS, COORDINATOR_HEADERS, OFFICER_HEADERS, MANAGER_HEADERS):
            validate_error(
                api.submit_part_certificate(owned_part["id"], payload, headers=headers),
                ApiErrorId.ROLE_NOT_PERMITTED.value,
                403,
            )
        certificate = fx.submit_part_certificate(
            api,
            owned_part["id"],
            env["supplier"]["id"],
            env["laboratory"]["id"],
            env["rules"][0]["id"],
        )
        validate_error(
            api.record_reliance_documentation(
                certificate["id"],
                {"reliance_decision": "RELY", "reliance_documentation_ref": "PKG-SELF"},
                headers=make_supplier_user_headers(env["supplier"]["id"]),
            ),
            ApiErrorId.ROLE_NOT_PERMITTED.value,
            403,
        )
        assert fx.get_part_certificate(api, certificate["id"])["reliance_state"] == "SUBMITTED"

    def test_the_supplier_scope_restricts_the_write_path_only(self, api):
        """PRD 4 lists SupplierUser among the authorised roles of "GET
        `/compliance/component-parts/{part_id}`" without qualification, so a supplier may read a
        part it does not supply.

        Design: Corner/rbac/corner_rbac_supplier_identity_is_scoped_to_the_parts_it_supplies
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env, rival = self._two_supplier_env(api)
        rival_headers = make_supplier_user_headers(rival["id"])

        part = validate_success(
            api.get_component_part(env["parts"][0]["id"], headers=rival_headers), 200
        )
        assert part["supplier_id"] == env["supplier"]["id"]
        validate_success(api.list_component_parts({}, headers=rival_headers), 200)


class TestSegregationOfDutiesComparesUserIds:
    """Two callers holding the same role are treated differently by their user id."""

    def test_the_coordinator_who_booked_the_evidence_cannot_issue_the_certificate(self, api):
        """PRD 2.1: "At certificate issuance, the issuing `X-User-ID` must differ from the
        `ordered_by_user_id` of every test order counted as evidence for the certificate's cited
        rules."

        Design: Corner/rbac/corner_rbac_segregation_of_duties_compares_user_ids_not_roles
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env = fx.evidence_complete_env(api)
        assert env["orders"][0]["ordered_by_user_id"] == COORDINATOR_USER_ID
        product = fx.get_product(api, env["product"]["id"])
        certificate = fx.draft_certificate(api, product["id"], product["version"])
        assert certificate["content_completeness_pct"] == 100

        validate_error(
            api.issue_certificate(
                certificate["id"],
                headers=make_headers(COORDINATOR_USER_ID, "CertificationOfficer"),
            ),
            ApiErrorId.SEGREGATION_OF_DUTIES.value,
            403,
        )
        issued = fx.issue_certificate(api, certificate["id"])
        assert issued["issuance_status"] == "ISSUED"
        assert issued["issued_by_user_id"] == OFFICER_USER_ID

    def test_the_check_covers_every_cited_evidence_row_not_only_the_first(self, api):
        """PRD 2.1: "the issuing `X-User-ID` must differ from the `ordered_by_user_id` of every
        test order counted as evidence for the certificate's cited rules."

        Design: Corner/rbac/corner_rbac_segregation_of_duties_compares_user_ids_not_roles
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env = fx.booking_env(api, rule_specs=[{}, {}])
        product_id = env["product"]["id"]
        laboratory_id = env["laboratory"]["id"]
        fx.run_order_to_pass(
            api, product_id, env["plan"]["id"], laboratory_id, env["rules"][0]["id"]
        )
        alt_order = validate_success(
            api.create_test_order(
                factories.test_order_payload(
                    product_id, env["plan"]["id"], laboratory_id, env["rules"][1]["id"]
                ),
                headers=make_headers(COORDINATOR_ALT_USER_ID, "TestCoordinator"),
            ),
            201,
        )
        assert alt_order["ordered_by_user_id"] == COORDINATOR_ALT_USER_ID
        fx.start_order(api, alt_order["id"], laboratory_id)
        fx.report(api, alt_order["id"], laboratory_id, 10)

        product = fx.get_product(api, product_id)
        assert product["certification_state"] == "EVIDENCE_COMPLETE"
        certificate = fx.draft_certificate(api, product_id, product["version"])
        assert certificate["cited_evidence_count"] == 2

        for booking_user in (COORDINATOR_USER_ID, COORDINATOR_ALT_USER_ID):
            validate_error(
                api.issue_certificate(
                    certificate["id"],
                    headers=make_headers(booking_user, "CertificationOfficer"),
                ),
                ApiErrorId.SEGREGATION_OF_DUTIES.value,
                403,
            )
        issued = validate_success(
            api.issue_certificate(certificate["id"], headers=OFFICER_HEADERS), 200
        )
        assert issued["issued_by_user_id"] == OFFICER_USER_ID

    def test_the_user_who_opened_the_case_cannot_close_it(self, api):
        """PRD 2.1: "At case closure, the closing `X-User-ID` must differ from the case's
        `opened_by_user_id`."

        Design: Corner/rbac/corner_rbac_segregation_of_duties_compares_user_ids_not_roles
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env = fx.corrective_action_env(api)
        case = env["case"]
        assert case["case_state"] == "CORRECTIVE_ACTION_APPROVED"
        assert case["opened_by_user_id"] == env["laboratory"]["id"]

        validate_error(
            api.close_case(
                case["id"],
                headers=make_headers(case["opened_by_user_id"], "CertificationOfficer"),
            ),
            ApiErrorId.SEGREGATION_OF_DUTIES.value,
            403,
        )
        closed = validate_success(
            api.close_case(case["id"], headers=OFFICER_ALT_HEADERS), 200
        )
        assert closed["case_state"] == "CLOSED"
        assert closed["closed_by_user_id"] == OFFICER_ALT_USER_ID

    def test_the_two_audit_ids_are_stored_separately_on_their_own_rows(self, api):
        """PRD 2.1: the opaque identifier is recorded "as `issued_by_user_id` on a certificate,
        as `closed_by_user_id` on a closed case" — one code guards two different stored ids.

        Design: Corner/rbac/corner_rbac_segregation_of_duties_compares_user_ids_not_roles
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env = fx.corrective_action_env(api)
        closed = fx.close_case(api, env["case"]["id"], headers=OFFICER_ALT_HEADERS)
        certificate = fx.get_certificate(api, env["certificate"]["id"])

        assert certificate["issued_by_user_id"] == OFFICER_USER_ID
        assert closed["closed_by_user_id"] == OFFICER_ALT_USER_ID
        assert closed["opened_by_user_id"] == env["laboratory"]["id"]
        assert closed["closed_by_user_id"] != closed["opened_by_user_id"]


class TestUnauthenticatedRequestsAreRefusedFirst:
    """No endpoint in the domain is public, and both identity headers are required."""

    @staticmethod
    def _five_calls(api, product_id, headers):
        """The same five endpoints — two reads, a summary, a write and the clock."""
        return [
            api.list_rules({}, headers=headers),
            api.get_product(product_id, headers=headers),
            api.get_compliance_summary(product_id, headers=headers),
            api.create_product(factories.product_payload(NON_EXISTENT_UUID), headers=headers),
            api.set_clock(STARTUP_CLOCK, headers=headers),
        ]

    def test_headerless_requests_are_refused_on_reads_as_well_as_writes(self, api):
        """PRD 2.1: "A request that omits either header, supplies an empty value, or names a role
        outside the recognised set is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/rbac/corner_rbac_unauthenticated_requests_are_refused_before_any_role_lookup
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env = fx.scoped_product_env(api)

        responses = self._five_calls(api, env["product"]["id"], None)
        assert len(responses) == 5
        for response in responses:
            validate_error(response, ApiErrorId.UNAUTHENTICATED.value, 401)

    def test_a_half_identity_is_as_unauthenticated_as_none_at_all(self, api):
        """PRD 2.1: "Every request to the API carries two headers: `X-User-ID`, identifying the
        acting principal, and `X-User-Role`, naming the role that principal is acting in. Both
        must be present and non-empty, and `X-User-Role` must name one of the six roles the
        system recognises."

        Design: Corner/rbac/corner_rbac_unauthenticated_requests_are_refused_before_any_role_lookup
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env = fx.scoped_product_env(api)
        product_id = env["product"]["id"]

        partials = [
            {"X-User-Role": "ComplianceAdministrator"},
            {"X-User-ID": ADMIN_USER_ID},
            {"X-User-ID": "", "X-User-Role": "ComplianceAdministrator"},
            {"X-User-ID": ADMIN_USER_ID, "X-User-Role": ""},
            {"X-User-ID": ADMIN_USER_ID, "X-User-Role": "RegulatoryInspector"},
        ]
        assert len(partials) == 5
        for headers in partials:
            for response in self._five_calls(api, product_id, headers):
                validate_error(response, ApiErrorId.UNAUTHENTICATED.value, 401)

    def test_the_401_reveals_nothing_about_existence(self, api):
        """PRD 2.11 rank 1: "Authentication — both headers present and non-empty, and
        `X-User-Role` naming one of the six roles → `ERR_UNAUTHENTICATED` (401). Applies to every
        endpoint." — rank 1 sits above rank 6 path existence.

        Design: Corner/rbac/corner_rbac_unauthenticated_requests_are_refused_before_any_role_lookup
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env = fx.scoped_product_env(api)

        for product_id in (env["product"]["id"], NON_EXISTENT_UUID):
            validate_error(
                api.get_product(product_id, headers=None),
                ApiErrorId.UNAUTHENTICATED.value,
                401,
            )
            validate_error(
                api.get_compliance_summary(product_id, headers=None),
                ApiErrorId.UNAUTHENTICATED.value,
                401,
            )

    def test_supplying_both_headers_turns_the_same_five_calls_into_successes(self, api):
        """PRD 2.1: "A request whose role is recognised but is not among the roles authorised for
        the target operation is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)." — the
        administrator is authorised for all five, so the identity is the only thing that was
        missing.

        Design: Corner/rbac/corner_rbac_unauthenticated_requests_are_refused_before_any_role_lookup
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env = fx.scoped_product_env(api)
        product_id = env["product"]["id"]

        responses = [
            api.list_rules({}, headers=ADMIN_HEADERS),
            api.get_product(product_id, headers=ADMIN_HEADERS),
            api.get_compliance_summary(product_id, headers=ADMIN_HEADERS),
            api.create_product(
                factories.product_payload(env["category"]["id"]), headers=ADMIN_HEADERS
            ),
            api.set_clock(STARTUP_CLOCK, headers=ADMIN_HEADERS),
        ]
        assert [response.status_code for response in responses] == [200, 200, 200, 201, 200]
