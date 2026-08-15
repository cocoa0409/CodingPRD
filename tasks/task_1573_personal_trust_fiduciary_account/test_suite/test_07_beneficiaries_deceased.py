"""Beneficiary death cascade and largest-remainder share reallocation
(PRD §3.2)."""
from test_helpers import (
    ApiErrorId,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    EXEC,
    OFFICER,
    add_beneficiary,
    create_approved_document,
    create_request,
    create_trust,
    post_receipt,
    trust_version,
)


def _stirpes_trust(api, per_stirpes: bool, name: str):
    """Trust with an APPROVED document recording the given per_stirpes."""
    trust = create_trust(trust_name=name, trust_type="TESTAMENTARY",
                         governing_state="TX")
    create_approved_document(trust["id"], per_stirpes=per_stirpes)
    return trust


class TestShareReallocation:
    def test_largest_remainder_reallocation_amounts(self, api):
        """PRD §3.2: "Each survivor's raw increment is the deceased's share
        multiplied by that survivor's own `share_bps` and divided by the sum
        of all survivors' shares. Each survivor first receives the floor of
        that raw increment. The leftover — the deceased's share minus the sum
        of the floors — is then distributed one basis point at a time to the
        survivors with the largest fractional remainders, with ties broken by
        beneficiary `created_at` ascending, never by id."

        Design: Difficulty/compensating_invariant/share_reallocation_conserves_bps
        """
        trust = _stirpes_trust(api, per_stirpes=False, name="Realloc Trust")
        b_a = add_beneficiary(trust["id"], full_name="Ann", share_bps=3333,
                              date_of_birth="1950-01-01")
        b_b = add_beneficiary(trust["id"], full_name="Bob", share_bps=3333,
                              date_of_birth="1951-01-01")
        b_c = add_beneficiary(trust["id"], full_name="Cid", share_bps=3334,
                              date_of_birth="1952-01-01")
        assert api.submit_for_acceptance(trust["id"], OFFICER).status_code == 200
        assert api.accept_trust(trust["id"], EXEC).status_code == 200
        post_receipt(trust["id"], 5000000, value_date="2026-08-06", description="income")
        create_request(trust["id"], b_a["id"], amount_cents=100000,
                       purpose_category="HEALTH")

        assert api.mark_deceased(b_a["id"], {"deceased_at": "2026-09-01"},
                                 OFFICER).status_code == 200
        bb = validate_success(api.get_beneficiary(b_b["id"], OFFICER))
        bc = validate_success(api.get_beneficiary(b_c["id"], OFFICER))
        # D=3333 over survivors 3333/3334: raw 1666.5833 / 1667.0833... floors
        # 1666 / 1666, leftover 1 bp to the largest fractional remainder (C).
        assert bb["share_bps"] == 4999
        assert bc["share_bps"] == 5001

    def test_class_sum_conserved_and_requests_cancelled(self, api):
        """PRD §3.2: "The deceased's share is absorbed in full by the
        survivors, so the class invariant holds both before and after: the
        ACTIVE members' shares sum to exactly 10000 basis points."
        PRD §3.2: "First, every distribution request of that beneficiary in
        SUBMITTED, UNDER_REVIEW, INFORMATION_REQUESTED, VOTING, or APPROVED is
        cancelled with `cancelled_reason` set to BENEFICIARY_DECEASED."

        Design: Difficulty/compensating_invariant/share_reallocation_conserves_bps
        """
        trust = _stirpes_trust(api, per_stirpes=False, name="Realloc Sum")
        b_a = add_beneficiary(trust["id"], full_name="Ann", share_bps=3333,
                              date_of_birth="1950-01-01")
        b_b = add_beneficiary(trust["id"], full_name="Bob", share_bps=3333,
                              date_of_birth="1951-01-01")
        b_c = add_beneficiary(trust["id"], full_name="Cid", share_bps=3334,
                              date_of_birth="1952-01-01")
        assert api.submit_for_acceptance(trust["id"], OFFICER).status_code == 200
        assert api.accept_trust(trust["id"], EXEC).status_code == 200
        post_receipt(trust["id"], 5000000, value_date="2026-08-06", description="income")
        req = create_request(trust["id"], b_a["id"], amount_cents=100000,
                             purpose_category="HEALTH")

        assert api.mark_deceased(b_a["id"], {"deceased_at": "2026-09-01"},
                                 OFFICER).status_code == 200
        bb = validate_success(api.get_beneficiary(b_b["id"], OFFICER))
        bc = validate_success(api.get_beneficiary(b_c["id"], OFFICER))
        assert bb["share_bps"] + bc["share_bps"] == 10000

        req_after = validate_success(api.get_distribution_request(req["id"], OFFICER))
        assert req_after["status"] == "CANCELLED"
        assert req_after["cancelled_reason"] == "BENEFICIARY_DECEASED"


class TestDeceasedBeneficiaryGates:
    def test_deceased_beneficiary_cannot_file_request(self, api):
        """PRD §2.8: "9. **Cross-entity references** — body references belong
        to the same trust (`ERR_CROSS_TRUST_REFERENCE`), the beneficiary is
        ACTIVE (`ERR_BENEFICIARY_NOT_ACTIVE`), and acceptance requires an
        APPROVED instrument (`ERR_DOCUMENT_NOT_APPROVED`)."
        PRD §3.2: "if `per_stirpes` is true, the shares are left unchanged
        because the deceased's share passes to their descendants."

        Design: Corner/state_machines/deceased_beneficiary_cannot_file_request
        """
        trust = _stirpes_trust(api, per_stirpes=True, name="Deceased File")
        ben = add_beneficiary(trust["id"], full_name="Ivy", share_bps=10000,
                              date_of_birth="1955-01-01")
        assert api.submit_for_acceptance(trust["id"], OFFICER).status_code == 200
        assert api.accept_trust(trust["id"], EXEC).status_code == 200
        assert api.mark_deceased(ben["id"], {"deceased_at": "2026-09-01"},
                                 OFFICER).status_code == 200

        resp = api.create_distribution_request(
            {
                "trust_id": trust["id"],
                "beneficiary_id": ben["id"],
                "amount_cents": 100000,
                "allocation_source": "INCOME_ONLY",
                "purpose_category": "OTHER",
                "expected_trust_account_version": trust_version(trust["id"]),
            },
            OFFICER,
        )
        validate_error(resp, ApiErrorId.ERR_BENEFICIARY_NOT_ACTIVE)
