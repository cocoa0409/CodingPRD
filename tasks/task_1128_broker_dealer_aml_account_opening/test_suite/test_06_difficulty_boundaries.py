"""Difficulty queue: boundary precision (price 5.00, ownership 25.00, velocity limit)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_owner,
    api_client,
    certify,
    create_certification,
    create_customer,
    create_rep,
    get_account,
    post_security_txn,
    post_transaction_payload,
    post_wire,
    set_clock,
    setup_open_account,
    validate_error,
)
from test_helpers.test_users import make_rep_headers


class TestLowPricedPriceBoundary5Dollars:
    def test_price_exactly_5_is_not_low_priced(self, api):
        """PRD §3.5: "A transaction's `is_low_priced` flag is true exactly when the
        transaction is a security type and its `unit_price` is below 5.00 — a price of
        exactly 5.00 is not low-priced — and is always false for `WIRE_OUT` and
        `JOURNAL`."

        Design: Difficulty/boundary_precision_check/low_priced_price_boundary_5_dollars
        """
        ctx = setup_open_account()
        txn = post_security_txn(ctx["account"]["id"], ctx["rep"], "BUY", "EDGE5", 10, 5.00)
        assert txn["is_low_priced"] is False, (
            "unit_price exactly 5.00 must NOT be low-priced"
        )

    def test_price_4_99_is_low_priced(self, api):
        """PRD §3.5: "A transaction's `is_low_priced` flag is true exactly when the
        transaction is a security type and its `unit_price` is below 5.00 — a price of
        exactly 5.00 is not low-priced" — 4.99 is below 5.00 and therefore low-priced.

        Design: Difficulty/boundary_precision_check/low_priced_price_boundary_5_dollars
        """
        ctx = setup_open_account()
        txn = post_security_txn(
            ctx["account"]["id"], ctx["rep"], "BUY", "EDGE499", 10, 4.99
        )
        assert txn["is_low_priced"] is True, "unit_price 4.99 < 5.00 must be low-priced"


class TestBeneficialOwnership25PctInclusiveBoundary:
    def _setup_two_legal_entity_certs(self):
        set_clock("2026-05-01T00:00:00Z")
        rep = create_rep(full_name="Rep N", crd_number="CRD-BP2")
        cust_a = create_customer(
            rep, customer_type="LEGAL_ENTITY", full_name="N Corp A",
            tax_id="EIN-BP2a", country_risk_tier="LOW",
        )
        cert_a = create_certification(
            cust_a["id"], rep, no_25pct_owner_attested=False
        )
        add_owner(cert_a["id"], rep, full_name="Owner 25", ownership_pct=25.00,
                  is_control_person=False, tax_id=None, date_of_birth=None,
                  address=None)
        add_owner(cert_a["id"], rep, full_name="Ctrl A", ownership_pct=10.00,
                  is_control_person=True, tax_id="TIN-CTRL-A",
                  date_of_birth="1970-01-01", address="1 Main St")
        cust_b = create_customer(
            rep, customer_type="LEGAL_ENTITY", full_name="N Corp B",
            tax_id="EIN-BP2b", country_risk_tier="LOW",
        )
        cert_b = create_certification(cust_b["id"], rep, no_25pct_owner_attested=True)
        add_owner(cert_b["id"], rep, full_name="Owner 2499", ownership_pct=24.99,
                  is_control_person=False, tax_id=None, date_of_birth=None,
                  address=None)
        add_owner(cert_b["id"], rep, full_name="Ctrl B", ownership_pct=10.00,
                  is_control_person=True, tax_id="TIN-CTRL-B",
                  date_of_birth="1970-01-01", address="2 Main St")
        return cert_a, cert_b

    def test_exactly_25pct_is_covered_and_requires_kyc(self, api):
        """PRD §3.2: "Every covered owner — one whose `ownership_pct` is at least
        25.00, with exactly 25.00 counting as covered — must present `tax_id`,
        `date_of_birth`, and `address` in full, else `ERR_OWNER_KYC_REQUIRED`."

        Design: Difficulty/boundary_precision_check/beneficial_ownership_25pct_inclusive_boundary
        """
        cert_a, _cert_b = self._setup_two_legal_entity_certs()
        resp = api_client.certify(cert_a["id"], TEST_USERS["officer_headers"])
        error = validate_error(resp, ApiErrorId.ERR_OWNER_KYC_REQUIRED)
        assert error["error_id"] == "ERR_OWNER_KYC_REQUIRED"
        assert resp.status_code == 422

    def test_24_99pct_is_not_covered_and_attestation_certifies(self, api):
        """PRD §3.2: "Every covered owner — one whose `ownership_pct` is at least
        25.00, with exactly 25.00 counting as covered" — 24.99 is below the inclusive
        threshold and is not covered.
        PRD §3.2: "Finally, either at least one covered owner must exist or
        `no_25pct_owner_attested` must be true; failing both draws
        `ERR_OWNER_KYC_REQUIRED` as well." — the attestation satisfies the coverage
        requirement and certification succeeds.

        Design: Difficulty/boundary_precision_check/beneficial_ownership_25pct_inclusive_boundary
        """
        _cert_a, cert_b = self._setup_two_legal_entity_certs()
        certified = certify(cert_b["id"])
        assert certified["status"] == "CERTIFIED", (
            "24.99 is not covered and the attestation carries the coverage requirement"
        )


class TestWireVelocityEqualityAtLimit:
    def test_projected_equal_to_limit_passes(self, api):
        """PRD §3.5: "Posting a new wire is checked by projection: the new wire's
        amount is added to the current total, and only a projected total strictly
        greater than the tier limit in effect at posting time (250000 for `LOW`,
        100000 for `MEDIUM`, 25000 for `HIGH`) is rejected with
        `ERR_VELOCITY_LIMIT_EXCEEDED` — a projection exactly equal to the limit
        passes."
        200000.00 + 50000.00 projects exactly 250000.00 on a LOW account: both post.

        Design: Difficulty/boundary_precision_check/wire_velocity_equality_at_limit
        """
        ctx = setup_open_account()
        account_id = ctx["account"]["id"]
        rep = ctx["rep"]
        wire1 = post_wire(account_id, rep, 200000.00)
        wire2 = post_wire(account_id, rep, 50000.00)
        assert wire1["status"] == "POSTED"
        assert wire2["status"] == "POSTED", (
            "a projection exactly equal to the limit passes"
        )
        account = get_account(account_id)
        assert account["wire_velocity_30d_amount"] == pytest.approx(250000.00, abs=0.01)

    def test_one_cent_over_limit_rejected(self, api):
        """PRD §3.5: "only a projected total strictly greater than the tier limit in
        effect at posting time (250000 for `LOW`, 100000 for `MEDIUM`, 25000 for
        `HIGH`) is rejected with `ERR_VELOCITY_LIMIT_EXCEEDED`".
        After 250000.00 of wires, a further 0.01 projects 250000.01 > 250000.00 and is
        rejected with 422.

        Design: Difficulty/boundary_precision_check/wire_velocity_equality_at_limit
        """
        ctx = setup_open_account()
        account_id = ctx["account"]["id"]
        rep = ctx["rep"]
        post_wire(account_id, rep, 200000.00)
        post_wire(account_id, rep, 50000.00)
        resp = api_client.post_transaction(
            account_id,
            post_transaction_payload(txn_type="WIRE_OUT", amount=0.01),
            make_rep_headers(rep["id"]),
        )
        error = validate_error(resp, ApiErrorId.ERR_VELOCITY_LIMIT_EXCEEDED)
        assert error["error_id"] == "ERR_VELOCITY_LIMIT_EXCEEDED"
        assert resp.status_code == 422
