"""Fee-disclosure drafting, approval preconditions, caps, and supersession.

Covers queue-B corner instances from the state_machines (supersede side effect) and validations
(cap boundary, cap exceeded, ack missing, surcharge mismatch) sections.
"""
import pytest

from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    TEST_USERS,
    provision_network, create_atm, draft_fee_disclosure, read_atm,
)

ADMIN = TEST_USERS["platform_admin_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]


def _atm(jurisdiction_code="CA", surcharge_cents=250):
    net = provision_network(jurisdiction_code=jurisdiction_code, surcharge_cents=surcharge_cents)
    return net["atm"]


# ============================================================================
# validations section
# ============================================================================

def test_surcharge_cap_exact_boundary_approves(api):
    """PRD §3.9: "The `disclosed_surcharge_cents` must be less than or equal to the
    `regulatory_cap_cents` for the jurisdiction, or it is rejected with
    `ERR_SURCHARGE_CAP_EXCEEDED`."
    PRD §3.9: "the cap is 300 cents in `CA`, 500 cents in `NY`, 275 cents in `TX`, and 300 cents
    in `FL`."

    Design: Corner/validations/surcharge_cap_exact_boundary_approves
    """
    atm = _atm(jurisdiction_code="CA", surcharge_cents=300)  # CA cap == 300
    fd = draft_fee_disclosure(atm["id"], 300, ack_text_present=True)
    resp = api.approve_fee_disclosure(fd["id"], headers=COMPLIANCE)
    data = validate_success(resp)
    assert data["status"] == "APPROVED"


def test_surcharge_cap_exceeded_rejected(api):
    """PRD §3.9: "The `disclosed_surcharge_cents` must be less than or equal to the
    `regulatory_cap_cents` for the jurisdiction, or it is rejected with
    `ERR_SURCHARGE_CAP_EXCEEDED`."
    PRD §3.9: "the cap is 300 cents in `CA`, 500 cents in `NY`, 275 cents in `TX`, and 300 cents
    in `FL`."

    Design: Corner/validations/surcharge_cap_exceeded_rejected
    """
    atm = _atm(jurisdiction_code="TX", surcharge_cents=276)  # TX cap == 275
    fd = draft_fee_disclosure(atm["id"], 276, ack_text_present=True)
    resp = api.approve_fee_disclosure(fd["id"], headers=COMPLIANCE)
    validate_error(resp, ApiErrorId.ERR_SURCHARGE_CAP_EXCEEDED, expected_status=422)


def test_approve_disclosure_missing_ack_text_rejected(api):
    """PRD §3.9: "And `ack_text_present` must be true, or it is rejected with
    `ERR_ACK_TEXT_MISSING`."

    Design: Corner/validations/approve_disclosure_missing_ack_text_rejected
    """
    atm = _atm(jurisdiction_code="CA", surcharge_cents=200)
    fd = draft_fee_disclosure(atm["id"], 200, ack_text_present=False)
    resp = api.approve_fee_disclosure(fd["id"], headers=COMPLIANCE)
    validate_error(resp, ApiErrorId.ERR_ACK_TEXT_MISSING, expected_status=422)


def test_approve_disclosure_surcharge_mismatch_rejected(api):
    """PRD §3.9: "The `disclosed_surcharge_cents` must equal the machine's current
    `surcharge_cents`, or approval is rejected with `ERR_DISCLOSURE_MISMATCH`."

    Design: Corner/validations/approve_disclosure_surcharge_mismatch_rejected
    """
    atm = _atm(jurisdiction_code="CA", surcharge_cents=200)
    fd = draft_fee_disclosure(atm["id"], 150, ack_text_present=True)  # 150 != ATM 200
    resp = api.approve_fee_disclosure(fd["id"], headers=COMPLIANCE)
    validate_error(resp, ApiErrorId.ERR_DISCLOSURE_MISMATCH, expected_status=422)


# ============================================================================
# state_machines section — supersession side effect
# ============================================================================

def test_approve_fee_disclosure_supersedes_prior_approved(api):
    """PRD §3.9: "When all three hold, the disclosure becomes `APPROVED`, any previously `APPROVED`
    disclosure on the same machine is superseded and moved to `REJECTED`, and the machine's
    `fee_disclosure_id` is set to this disclosure — the act that arms the machine for live revenue."

    Design: Corner/state_machines/approve_fee_disclosure_supersedes_prior_approved
    """
    atm = _atm(jurisdiction_code="CA", surcharge_cents=250)
    fd1 = draft_fee_disclosure(atm["id"], 250, ack_text_present=True)
    fd1 = validate_success(api.approve_fee_disclosure(fd1["id"], headers=COMPLIANCE))
    assert fd1["status"] == "APPROVED"

    fd2 = draft_fee_disclosure(atm["id"], 250, ack_text_present=True)
    fd2 = validate_success(api.approve_fee_disclosure(fd2["id"], headers=COMPLIANCE))
    assert fd2["status"] == "APPROVED"

    # FD1 must now be REJECTED (superseded); ATM repointed to FD2.
    refreshed = validate_success(api.list_fee_disclosures(
        atm["id"], headers=COMPLIANCE, params={"status": "APPROVED"}))
    approved_ids = {d["id"] for d in refreshed}
    assert fd2["id"] in approved_ids
    assert fd1["id"] not in approved_ids

    atm_now = read_atm(atm["id"])
    assert atm_now["fee_disclosure_id"] == fd2["id"]
