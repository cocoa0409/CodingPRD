"""Label approval review loop, claim substantiation, version pinning."""
from test_helpers import (
    INSPECTOR_1,
    TEST_USERS,
    ApiErrorId,
    create_finished_lot_payload,
    create_label_approval_payload,
    validate_error,
    validate_success,
)
from test_helpers import fixtures

QA = TEST_USERS["qa_manager_headers"]
PROD = TEST_USERS["production_manager_headers"]


class TestLabelLifecycle:
    def test_approve_from_draft_returns_label_invalid_state(self, api):
        """PRD §3.7: "An `Inspector` then approves or rejects from `SUBMITTED`."
        PRD §3.7: "The from-state check (`ERR_LABEL_INVALID_STATE`) runs before the substantiation check."

        Design: Corner/state_machines/label_approve_from_draft_returns_label_invalid_state
        """
        plant = fixtures.create_plant(establishment_number="EST-1645-15")
        label = fixtures.get_success_data(
            api.create_label_approval(
                plant["id"], create_label_approval_payload(), QA
            )
        )
        assert label["status"] == "DRAFT"

        resp = api.approve_label_approval(
            label["id"], fixtures.make_inspector_headers(INSPECTOR_1)
        )
        validate_error(resp, ApiErrorId.ERR_LABEL_INVALID_STATE)
        assert resp.status_code == 409

    def test_label_reject_resubmit_cycle(self, api):
        """PRD §3.7: "Submitting — from `DRAFT`, or from `REJECTED` as a resubmission — requires the substantiation file to cover every claim: at least one document reference per member of `claims`, otherwise `ERR_CLAIM_SUBSTANTIATION_MISSING`."
        PRD §3.7: "Resubmission additionally clears any recorded `rejection_reason` to null."
        PRD §3.7: "Approval stamps `approved_by` and pins `approved_formulation_version` to whatever `formulation_version` the application carried at the moment of approval — this pinning is what lets packaging refer to an immutable, approved formulation even if later drafts change the declared version."

        Design: Corner/state_machines/label_reject_resubmit_cycle
        """
        plant = fixtures.create_plant(establishment_number="EST-1645-16")
        label = fixtures.get_success_data(
            api.create_label_approval(
                plant["id"],
                create_label_approval_payload(
                    product_name="Ribeye Steak",
                    claims=["GRASS_FED"],
                    substantiation_doc_refs=["doc-gf-1"],
                    formulation_version=3,
                ),
                QA,
            )
        )
        assert label["status"] == "DRAFT"

        st1 = validate_success(api.submit_label_approval(label["id"], QA), 200)
        assert st1["status"] == "SUBMITTED"

        st2 = validate_success(
            api.reject_label_approval(
                label["id"], {"rejection_reason": "Claim font too small"},
                fixtures.make_inspector_headers(INSPECTOR_1),
            ),
            200,
        )
        assert st2["status"] == "REJECTED"
        assert st2["rejection_reason"] == "Claim font too small"

        st3 = validate_success(api.submit_label_approval(label["id"], QA), 200)
        assert st3["status"] == "SUBMITTED", "resubmission from REJECTED"
        assert st3.get("rejection_reason") is None, (
            "resubmission clears the recorded rejection_reason"
        )

        st4 = validate_success(
            api.approve_label_approval(
                label["id"], fixtures.make_inspector_headers(INSPECTOR_1)
            ),
            200,
        )
        assert st4["status"] == "APPROVED"
        assert st4["approved_formulation_version"] == 3, (
            "approval pins the formulation_version carried at approval time"
        )
        assert st4["approved_by"] == INSPECTOR_1


class TestClaimSubstantiation:
    def test_submit_without_substantiation_returns_claim_error(self, api):
        """PRD §3.7: "Submitting — from `DRAFT`, or from `REJECTED` as a resubmission — requires the substantiation file to cover every claim: at least one document reference per member of `claims`, otherwise `ERR_CLAIM_SUBSTANTIATION_MISSING`."

        Design: Corner/validations/label_submit_without_substantiation_returns_claim_error
        """
        plant = fixtures.create_plant(establishment_number="EST-1645-24")
        label = fixtures.get_success_data(
            api.create_label_approval(
                plant["id"],
                create_label_approval_payload(
                    product_name="Organic Ground Beef",
                    claims=["ORGANIC"],
                    substantiation_doc_refs=[],
                ),
                QA,
            )
        )

        resp = api.submit_label_approval(label["id"], QA)
        validate_error(resp, ApiErrorId.ERR_CLAIM_SUBSTANTIATION_MISSING)
        assert resp.status_code == 422

        after = validate_success(api.get_label_approval(label["id"], QA), 200)
        assert after["status"] == "DRAFT"


class TestLatestApprovedLabelPinning:
    def test_latest_label_approval_version_pinning(self, api):
        """PRD §3.8: "the label must be the latest-approved application for its plant and `product_name`, meaning no other `APPROVED` label for the same product name exists whose approval executed later (`ERR_LABEL_VERSION_STALE`)"
        PRD §3.7: "Approval stamps `approved_by` and pins `approved_formulation_version` to whatever `formulation_version` the application carried at the moment of approval — this pinning is what lets packaging refer to an immutable, approved formulation even if later drafts change the declared version."

        Design: Corner/complexity_layers/latest_label_approval_version_pinning
        """
        env, lot = fixtures.setup_fabricated_lot(
            establishment_number="EST-1645-43"
        )
        label1 = fixtures.create_approved_label(
            env["plant"]["id"], formulation_version=1
        )
        assert label1["approved_formulation_version"] == 1

        # A second application for the same product is approved later.
        fixtures.set_clock("2026-08-01T08:00:00Z")
        label2 = fixtures.create_approved_label(
            env["plant"]["id"], formulation_version=2,
            substantiation_doc_refs=["doc-nat-2"],
        )
        assert label2["approved_formulation_version"] == 2

        # The earlier approval is now stale for packaging.
        stale = api.create_finished_lot(
            env["day"]["id"],
            create_finished_lot_payload(
                source_lot_id=lot["id"], label_approval_id=label1["id"],
                units_produced=10, unit_weight_lbs=5.0, shelf_life_days=10,
            ),
            PROD,
        )
        validate_error(stale, ApiErrorId.ERR_LABEL_VERSION_STALE)
        assert stale.status_code == 422

        ok = validate_success(
            api.create_finished_lot(
                env["day"]["id"],
                create_finished_lot_payload(
                    source_lot_id=lot["id"], label_approval_id=label2["id"],
                    units_produced=10, unit_weight_lbs=5.0, shelf_life_days=10,
                ),
                PROD,
            ),
            201,
        )
        assert ok["label_approval_id"] == label2["id"]
