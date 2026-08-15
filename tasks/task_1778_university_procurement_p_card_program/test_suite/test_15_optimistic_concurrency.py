"""Optimistic concurrency control on requisition, contract, and P-card writes."""
from test_helpers import (
    ApiErrorId,
    assert_version_incremented,
    create_and_submit_requisition,
    create_department,
    create_executed_contract,
    create_pcard,
    create_vendor,
    get_success_data,
    make_requester_headers,
    requisition_line,
    validate_error,
)
from test_helpers.fixtures import ADMIN, CONTRACT_OFFICER, DEPT_APPROVER

ADMIN_H = ADMIN
CO = CONTRACT_OFFICER
DEPT_H = DEPT_APPROVER


class TestRequisitionPatchOcc:
    def test_occ_stale_version_requisition_patch(self, api):
        """PRD §2.7: "Editing a requisition requires
        `expected_requisition_version`, carrying the client's last observed
        `version` of that requisition. If the requisition's current `version` has
        advanced — for example because an approver acted on it — the edit is
        rejected with `ERR_STALE_VERSION` (HTTP 412), and the client must re-read
        the requisition before resubmitting."

        Design: Corner/cross_cutting_layers/occ_stale_version_requisition_patch
        """
        dept = create_department(name="OCC1")
        vendor = create_vendor(legal_name="OccCo")
        req = create_and_submit_requisition(
            department_id=dept["id"], vendor_id=vendor["id"],
            lines=[requisition_line(
                commodity_code="OCC", description="widget",
                unit_price_cents=600000, cost_category="SUPPLIES",
            )],
        )
        returned = get_success_data(
            api.return_requisition_step(
                req["id"], {"reason": "revise"}, DEPT_H
            )
        )
        current_version = returned["version"]

        stale = api.patch_requisition(
            req["id"],
            {
                "expected_requisition_version": current_version - 1,
                "sole_source_justification": "stale write",
            },
            make_requester_headers("req-user-1"),
        )
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION, 412)

        fresh = get_success_data(
            api.patch_requisition(
                req["id"],
                {
                    "expected_requisition_version": current_version,
                    "sole_source_justification": "fresh write",
                },
                make_requester_headers("req-user-1"),
            )
        )
        assert_version_incremented(fresh["version"], current_version)


class TestContractAmendAndCardLimitsOcc:
    def test_occ_stale_version_contract_amend_and_pcard_limits(self, api):
        """PRD §2.7: "Creating a contract amendment requires
        `expected_contract_version`, carrying the client's last observed
        `version` of the contract being amended. Because a prior amendment
        created against the same contract legitimately supersedes the client's
        view, a mismatch is refused with `ERR_STALE_VERSION` (HTTP 412) rather
        than producing two competing amendment drafts."
        PRD §2.7: "Changing a P-card's limits requires `expected_pcard_version`,
        carrying the client's last observed `version` of the card. A mismatch —
        for instance because a close-cycle or another limits change bumped the
        version — is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_stale_version_contract_amend_and_pcard_limits
        """
        dept = create_department(name="OCC2")
        vendor = create_vendor(legal_name="OccContractCo")
        contract = create_executed_contract(vendor["id"], commodity_code="OCC")
        cid = contract["id"]
        c_version = contract["version"]

        amendment = get_success_data(
            api.amend_contract(
                cid,
                {
                    "expected_contract_version": c_version,
                    "effective_start": "2026-01-01T00:00:00Z",
                    "effective_end": "2028-06-01T00:00:00Z",
                },
                CO,
            )
        )
        assert amendment["status"] == "DRAFT"
        assert amendment["supersedes_contract_id"] == cid
        bumped = get_success_data(api.get_contract(cid, ADMIN_H))
        assert_version_incremented(bumped["version"], c_version)

        second = api.amend_contract(
            cid,
            {
                "expected_contract_version": c_version,
                "effective_start": "2026-01-01T00:00:00Z",
                "effective_end": "2029-01-01T00:00:00Z",
            },
            CO,
        )
        validate_error(second, ApiErrorId.ERR_STALE_VERSION, 412)

        card = create_pcard(department_id=dept["id"], cardholder_name="Pax")
        pc_version = card["version"]
        updated = get_success_data(
            api.patch_pcard_limits(
                card["id"],
                {
                    "expected_pcard_version": pc_version,
                    "single_txn_limit_cents": 150000,
                },
                ADMIN_H,
            )
        )
        assert_version_incremented(updated["version"], pc_version)
        assert updated["single_txn_limit_cents"] == 150000

        replayed = api.patch_pcard_limits(
            card["id"],
            {
                "expected_pcard_version": pc_version,
                "single_txn_limit_cents": 175000,
            },
            ADMIN_H,
        )
        validate_error(replayed, ApiErrorId.ERR_STALE_VERSION, 412)
