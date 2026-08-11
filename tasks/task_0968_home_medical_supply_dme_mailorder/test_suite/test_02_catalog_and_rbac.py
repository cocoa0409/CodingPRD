"""Catalog configuration (formulary, stock) and role-based access denials."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    assert_formulary_item,
    create_payer_plan,
    create_formulary_item,
    create_stock_level,
    create_active_patient,
    create_prior_authorization,
    get_hsa_account,
    INTAKE,
    BILLING,
    PA_SPEC,
    ADMIN,
    make_patient_headers,
)


class TestFormularyItems:
    def test_formulary_item_computed_unit_allowance_and_defaults(self, api):
        """PRD §3.1: "On creation the server computes `unit_allowance_cents` as
        the pack fee divided by the pack size, rounded half up to 2 decimal
        places under the pinned order of §2.5". PRD §3.1: "an optional
        `requires_pa` flag defaulting to false". PRD §3.1: "An item's `status`
        is `ACTIVE` by default".

        Design: Corner/entities/formulary_item_computed_unit_allowance_and_defaults
        """
        plan = create_payer_plan()
        payload = {
            "hcpcs_code": "A6250",
            "name": "Wound dressing",
            "category": "WOUND",
            "covered_plan_ids": [plan["id"]],
            "pack_fee_cents": 999,
            "pack_size": 8,
            "retail_price_cents": 650,
            "max_units_per_cycle": 30,
            "size_codes": ["4X4"],
        }
        item = validate_success(api.create_formulary_item(payload, ADMIN), expected_status=201)
        assert_formulary_item(item)
        assert item["unit_allowance_cents"] == pytest.approx(124.88, abs=0.001), (
            f"round_half_up(999/8, 2) must be 124.88, got {item['unit_allowance_cents']}"
        )
        assert item["requires_pa"] is False
        assert item["status"] == "ACTIVE"

    def test_duplicate_stock_level_rejected(self, api):
        """PRD §3.1: "At most one stock row may exist per item — a second
        creation for the same item is rejected with `ERR_DUPLICATE_STOCK_LEVEL`."

        Design: Corner/validations/duplicate_stock_level_rejected
        """
        plan = create_payer_plan()
        item = create_formulary_item([plan["id"]])
        create_stock_level(item["id"], on_hand_qty=50)

        resp = api.create_stock_level(
            {"formulary_item_id": item["id"], "on_hand_qty": 25}, ADMIN
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_STOCK_LEVEL)


class TestRoleBasedAccess:
    def test_patient_role_forbidden_on_formulary_create(self, api):
        """PRD §2.1: "Once authenticated, the caller's role must appear in the
        endpoint's authorized role set, or the request is rejected with
        `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/patient_role_forbidden_on_formulary_create
        """
        plan = create_payer_plan(plan_type="CASH_HSA", coinsurance_pct=1.00, cycle_months=1)
        patient = create_active_patient(plan["id"])

        resp = api.create_formulary_item(
            {
                "hcpcs_code": "A4419",
                "name": "X",
                "category": "OSTOMY",
                "covered_plan_ids": [plan["id"]],
                "pack_fee_cents": 100,
                "pack_size": 1,
                "retail_price_cents": 100,
                "max_units_per_cycle": 10,
                "size_codes": ["45MM"],
            },
            make_patient_headers(patient["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_billing_specialist_cannot_decide_prior_auth(self, api):
        """PRD §2.1: "A `PriorAuthSpecialist` owns the prior authorization
        lifecycle: creating authorizations, recording payer decisions, and
        filing appeals." PRD §2.1: "Once authenticated, the caller's role must
        appear in the endpoint's authorized role set, or the request is rejected
        with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/billing_specialist_cannot_decide_prior_auth
        """
        plan = create_payer_plan()
        patient = create_active_patient(plan["id"])
        pa = create_prior_authorization(patient["id"], hcpcs_code="A6250")
        assert pa["status"] == "SUBMITTED"

        resp = api.decide_prior_authorization(pa["id"], {"outcome": "APPROVED"}, BILLING)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

        after = validate_success(api.get_prior_authorization(pa["id"], PA_SPEC), expected_status=200)
        assert after["status"] == "SUBMITTED", "rejected decision must not mutate the PA"
