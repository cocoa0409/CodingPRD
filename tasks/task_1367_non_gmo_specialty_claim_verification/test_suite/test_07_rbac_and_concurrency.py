"""RBAC, segregation-of-duties, and optimistic-concurrency tests."""
import pytest

from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS,
    make_brand_rep_headers, build_user_headers,
    create_standard, create_brand, create_product, add_ingredient,
    add_accepted_affidavit, create_product_under_evaluation, create_plan,
    collect_sample, confirm_sample, create_verified_product, open_case,
    get_product,
    create_facility_audit_payload, create_audit_report_payload,
    create_sampling_plan_payload,
)

ADMIN = TEST_USERS["verifier_admin_headers"]
LAB_1 = TEST_USERS["lab_analyst_1_headers"]
LAB_2 = TEST_USERS["lab_analyst_2_headers"]


def _auditor_headers(auditor_id):
    return build_user_headers(auditor_id, "Auditor")


# ─── RBAC: exclusive operations denied to other roles ────────────────────────

class TestRbacExclusiveDenied:
    def test_brandrep_cannot_decide_product(self, api):
        """PRD section 2.1: "A request whose role is recognized but not permitted
        for the targeted operation is rejected with `ERR_FORBIDDEN_ROLE`."
        PRD section 4: "Verification decision; VERIFIED issues or reinstates the
        license, REJECTED requires a reason" — authorized role: VerifierAdmin.

        Design: Corner/rbac/brandrep_cannot_decide_product
        """
        ctx = create_product_under_evaluation(
            name="P1", gtin="G-P1",
            ingredient_specs=({"name": "Salt", "crop_type": "NON_CROP",
                               "declared_weight_pct": 100.00},),
            with_affidavits=False,
        )
        res = api.decide_product(
            ctx["product"]["id"], {"decision": "VERIFIED"},
            make_brand_rep_headers(ctx["brand"]["id"]))
        validate_error(res, ApiErrorId.ERR_FORBIDDEN_ROLE.value)

    def test_brandrep_cannot_touch_other_brand_product(self, api):
        """PRD section 2.1: "This ownership rule guards every
        brand-representative write operation — enrolling a product, submitting it,
        resubmitting it, renewing it, adding an ingredient, and submitting an
        affidavit — and a mismatch is rejected with `ERR_NOT_BRAND_RESOURCE`."

        Design: Corner/rbac/brandrep_cannot_touch_other_brand_product
        """
        std = create_standard()
        b1 = create_brand(name="B1", contact_email="b1@x.com")
        b2 = create_brand(name="B2", contact_email="b2@x.com")
        product = create_product(b1, std, name="P1", gtin="G-P1")
        add_ingredient(product["id"], b1["id"], name="Salt", crop_type="NON_CROP")
        res = api.submit_product(product["id"], make_brand_rep_headers(b2["id"]))
        validate_error(res, ApiErrorId.ERR_NOT_BRAND_RESOURCE.value)

    def test_labanalyst_cannot_create_sampling_plan(self, api):
        """PRD section 2.1: "A request whose role is recognized but not permitted
        for the targeted operation is rejected with `ERR_FORBIDDEN_ROLE`."
        PRD section 4: "Create a PCR sampling plan (optimistic-concurrency
        guarded; supersedes the product's prior plans)" — authorized role:
        VerifierAdmin.

        Design: Corner/rbac/labanalyst_cannot_create_sampling_plan
        """
        ctx = create_product_under_evaluation(
            name="P1", gtin="G-P1",
            ingredient_specs=({"name": "Salt", "crop_type": "NON_CROP",
                               "declared_weight_pct": 100.00},),
            with_affidavits=False,
        )
        version = get_product(ctx["product"]["id"])["version"]
        res = api.create_sampling_plan(
            create_sampling_plan_payload(ctx["product"]["id"], version), LAB_1)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


# ─── Segregation of duties ───────────────────────────────────────────────────

class TestSegregationOfDuties:
    def test_analyst_cannot_confirm_own_recorded_result(self, api):
        """PRD section 2.8: "First, laboratory results are confirmed by a
        different analyst than the one who recorded them: the confirming
        `X-User-ID` must differ from the sample's `recorded_by_user_id`."
        PRD section 2.8: "Violating either rule is rejected with
        `ERR_SEGREGATION_OF_DUTIES`."
        PRD section 3.5: "stamps `confirmed_by_user_id`, and then fans out."

        Design: Corner/rbac/analyst_cannot_confirm_own_recorded_result
        """
        ctx = create_product_under_evaluation(name="P1", gtin="G-P1")
        plan = create_plan(ctx["product"]["id"])
        sample = collect_sample(plan["id"], ctx["ingredients"][0]["id"])
        validate_success(
            api.record_sample_result(sample["id"], {"result_gmo_pct": 0.10}, LAB_1), 200)

        res = api.confirm_sample(sample["id"], LAB_1)
        validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)

        confirmed = validate_success(api.confirm_sample(sample["id"], LAB_2), 200)
        assert confirmed["status"] == "CONFIRMED"
        assert confirmed["confirmed_by_user_id"] == "lab-2"

    def test_officer_cannot_resolve_own_case(self, api):
        """PRD section 2.8: "Second, an enforcement case is resolved by a
        different officer than the one who opened it: the resolving `X-User-ID`
        must differ from the case's `opened_by_user_id`."
        PRD section 3.8: "A `DISMISSED` outcome must carry no `sanction` —
        supplying one is a shape error — and simply stamps `resolved_by_user_id`,
        with no further effects; a dismissed case contributes nothing to any
        counter."

        Design: Corner/rbac/officer_cannot_resolve_own_case
        """
        std = create_standard()
        brand = create_brand(name="B1", contact_email="b1@x.com")
        product = create_product(brand, std, name="P1", gtin="G-P1")
        case = open_case(product["id"], description="d")

        res = api.resolve_enforcement_case(
            case["id"], {"outcome": "DISMISSED"}, TEST_USERS["officer_1_headers"])
        validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)

        resolved = validate_success(
            api.resolve_enforcement_case(
                case["id"], {"outcome": "DISMISSED"}, TEST_USERS["officer_2_headers"]),
            200)
        assert resolved["status"] == "DISMISSED"
        assert resolved["penalty_points"] == 0

    def test_auditor_not_assigned_cannot_submit_report(self, api):
        """PRD section 2.8: "Third, a facility audit's traceability report may be
        submitted only by the auditor named in the audit's `auditor_id`; any other
        caller is rejected with `ERR_NOT_ASSIGNED_AUDITOR`."

        Design: Corner/rbac/auditor_not_assigned_cannot_submit_report
        """
        brand = create_brand(name="B1", contact_email="b1@x.com")
        audit = validate_success(
            api.create_facility_audit(
                create_facility_audit_payload(brand["id"], auditor_id="aud-1"),
                ADMIN), 201)
        res = api.submit_audit_report(
            audit["id"], create_audit_report_payload(), _auditor_headers("aud-2"))
        validate_error(res, ApiErrorId.ERR_NOT_ASSIGNED_AUDITOR.value)


# ─── Optimistic concurrency on sampling-plan creation ────────────────────────

class TestPlanOptimisticConcurrency:
    def test_stale_version_rejected_and_prior_plan_untouched(self, api):
        """PRD section 2.7: "The request must carry `expected_product_version`, a
        non-optional field holding the `version` of the target product as the
        client last observed it. If another writer has advanced the product's
        `version` since that read, the create is rejected with `ERR_STALE_VERSION`
        (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_stale_version_on_plan_create_rejected
        """
        ctx = create_product_under_evaluation(name="P1", gtin="G-P1")
        product_id = ctx["product"]["id"]
        stale_version = get_product(product_id)["version"]

        plan_a = create_plan(product_id, risk_point="INGREDIENT_INTAKE")
        # The first creation bumped Product.version; replaying the stale version
        # must be rejected and must not supersede plan A.
        res = api.create_sampling_plan(
            create_sampling_plan_payload(
                product_id, stale_version, risk_point="IN_PROCESS"), ADMIN)
        validate_error(res, ApiErrorId.ERR_STALE_VERSION.value)

        plan_a_after = validate_success(api.get_sampling_plan(plan_a["id"], ADMIN), 200)
        assert plan_a_after["status"] == "ACTIVE"

    def test_fresh_version_supersedes_and_bumps_version(self, api):
        """PRD section 3.5: "Creation also supersedes: every existing `ACTIVE` or
        `COMPLETED` plan of the same product transitions to `CANCELLED`, with
        `superseded_by_plan_id` set to the new plan's id, and the product's
        `version` advances by one."

        Design: Corner/cross_cutting_layers/plan_supersede_cancels_previous_with_fresh_version
        """
        ctx = create_product_under_evaluation(name="P1", gtin="G-P1")
        product_id = ctx["product"]["id"]
        v1 = get_product(product_id)["version"]

        plan_a = create_plan(product_id, risk_point="INGREDIENT_INTAKE")
        v2 = get_product(product_id)["version"]
        assert v2 == v1 + 1

        res = api.create_sampling_plan(
            create_sampling_plan_payload(
                product_id, v2, risk_point="IN_PROCESS"), ADMIN)
        plan_b = validate_success(res, 201)
        assert plan_b["status"] == "ACTIVE"

        plan_a_after = validate_success(api.get_sampling_plan(plan_a["id"], ADMIN), 200)
        assert plan_a_after["status"] == "CANCELLED"
        assert plan_a_after["superseded_by_plan_id"] == plan_b["id"]

        v3 = get_product(product_id)["version"]
        assert v3 == v2 + 1


# ─── Missing authentication context ──────────────────────────────────────────

class TestMissingAuthContext:
    def test_missing_auth_headers_returns_context_error(self, api):
        """PRD section 2.1: "Every request must carry `X-User-ID` identifying the
        acting user and `X-User-Role` naming their capacity."
        PRD section 2.1: "A request with a missing header, or whose role is not
        one of these five, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT`."

        Design: Corner/cross_cutting_layers/missing_auth_headers_returns_context_error
        """
        brand = create_brand(name="B1", contact_email="b1@x.com")
        res = api.get_brand(brand["id"], headers={})
        validate_error(res, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT.value)
