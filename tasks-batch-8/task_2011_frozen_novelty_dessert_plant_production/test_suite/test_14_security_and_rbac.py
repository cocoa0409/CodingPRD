"""Authentication, RBAC denial, and segregation of duties (PRD §2.1, §2.8)."""
from test_helpers import (
    ApiErrorId,
    create_changeover,
    create_complaint,
    create_contract,
    create_customer,
    create_mix_batch,
    create_product,
    get_success_data,
    make_customer_rep_headers,
    make_line_operator_headers,
    make_production_planner_headers,
    make_qa_manager_headers,
    make_warehouse_lead_headers,
    pasteurize_batch,
    set_clock,
    setup_completed_run,
    setup_plant,
    validate_error,
    validate_success,
)
from test_helpers.factories import create_product_payload, create_customer_payload
from test_helpers.fixtures import PM


class TestAuthentication:
    def test_unauthenticated_missing_auth_headers(self, api):
        """PRD §2.1: "A request missing either header, or carrying a role
        not in the declared set, is rejected with ERR_UNAUTHENTICATED
        (HTTP 401)."

        Design: Corner/validations/unauthenticated_missing_auth_headers
        """
        resp = api.list_products({})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


class TestForbiddenRole:
    def test_forbidden_role_customer_creates_product(self, api):
        """PRD §2.1: "A request whose role is not in the endpoint's
        authorized list is rejected with ERR_FORBIDDEN_ROLE (HTTP 403)."
        POST /products is PlantManager-only (§4), so a CustomerRep is
        forbidden.

        Design: Corner/validations/forbidden_role_customer_creates_product
        """
        customer = create_customer()
        resp = api.create_product(
            create_product_payload(sku_code="X-1", product_name="X"),
            make_customer_rep_headers(customer["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

    def test_planner_cannot_release_mix(self, api):
        """PRD §4: POST /mix-batches/{id}/release is authorized for
        QAManager only. PRD §2.1: "A request whose role is not in the
        endpoint's authorized list is rejected with ERR_FORBIDDEN_ROLE
        (HTTP 403)."

        Design: Corner/rbac/planner_cannot_release_mix
        """
        product = create_product()
        set_clock("2026-08-10T08:00:00Z")
        batch = create_mix_batch(product["id"], batch_code="MB-RB",
                                 litres_produced=100)
        pasteurize_batch(batch["id"], "op_1")
        resp = api.release_mix_batch(
            batch["id"], make_production_planner_headers("planner_1"))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

    def test_operator_cannot_approve_contract(self, api):
        """PRD §4: POST /co-pack-contracts/{id}/approve is authorized for
        PlantManager only. PRD §2.1: "A request whose role is not in the
        endpoint's authorized list is rejected with ERR_FORBIDDEN_ROLE
        (HTTP 403)."

        Design: Corner/rbac/operator_cannot_approve_contract
        """
        product = create_product(**create_product_payload(
            sku_code="CP-BAR", product_name="PL Bar", co_pack_only=True))
        customer = create_customer(**create_customer_payload(
            customer_code="PL-1", display_name="Big Retailer",
            kind="PRIVATE_LABEL"))
        contract = create_contract(customer["id"], product["id"],
                                   contract_code="CT-RB")
        validate_success(api.submit_contract(
            contract["id"], make_customer_rep_headers(customer["id"])))
        resp = api.approve_contract(
            contract["id"], make_line_operator_headers("op_1"))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

    def test_warehouse_cannot_disposition_complaint(self, api):
        """PRD §4: POST /quality-complaints/{id}/disposition is authorized
        for QAManager only. PRD §2.1: "A request whose role is not in the
        endpoint's authorized list is rejected with ERR_FORBIDDEN_ROLE
        (HTTP 403)."

        Design: Corner/rbac/warehouse_cannot_disposition_complaint
        """
        ctx = setup_completed_run(run_code="R-RB")
        qc = create_complaint(ctx["lot"]["id"], complaint_code="QC-RB")
        resp = api.disposition_complaint(qc["id"], {"outcome": "UNFOUNDED"},
                                         make_warehouse_lead_headers("wh_1"))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


class TestSegregationOfDuties:
    def test_sod_mix_release_by_pasteurizer_rejected(self, api):
        """PRD §2.8: "The QAManager releasing a MixBatch must not be the
        same X-User-ID as the LineOperator who pasteurized it. ... A
        violation on any of these is rejected with
        ERR_SEGREGATION_OF_DUTIES (HTTP 403)."

        Design: Corner/validations/sod_mix_release_by_pasteurizer_rejected
        """
        product = create_product()
        set_clock("2026-08-10T08:00:00Z")
        batch = create_mix_batch(product["id"], batch_code="MB-S")
        pasteurize_batch(batch["id"], "op_1")
        # Release attempted under the SAME user id (op_1) with the QA role.
        resp = api.release_mix_batch(batch["id"], make_qa_manager_headers("op_1"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        batch_after = get_success_data(api.get_mix_batch(batch["id"], PM))
        assert batch_after["status"] == "PASTEURIZED"

    def test_sod_changeover_verify_by_completer_rejected(self, api):
        """PRD §2.8: "The QAManager verifying a Changeover must not be the
        same X-User-ID as the LineOperator who completed it. ... A
        violation on any of these is rejected with
        ERR_SEGREGATION_OF_DUTIES (HTTP 403)."

        Design: Corner/validations/sod_changeover_verify_by_completer_rejected
        """
        product, line, _, _ = setup_plant()
        ch = create_changeover(line["id"], product["id"])
        validate_success(api.complete_changeover(
            ch["id"], make_line_operator_headers("op_1")))
        resp = api.verify_changeover(ch["id"], {"outcome": "PASS"},
                                     make_qa_manager_headers("op_1"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        ch_after = get_success_data(api.get_changeover(ch["id"], PM))
        assert ch_after["status"] == "AWAITING_VERIFICATION"
        line_after = get_success_data(api.get_line(line["id"], PM))
        assert line_after["status"] == "CLEANING"
