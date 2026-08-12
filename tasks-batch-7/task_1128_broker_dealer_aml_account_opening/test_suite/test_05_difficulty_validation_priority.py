"""Difficulty queue: validation priority pairs (state>fiscal, safety>constraint)."""
import pytest

from test_helpers import (
    TEST_USERS,
    api_client,
    approve_account,
    create_account,
    create_customer,
    create_deposit,
    create_rep,
    get_account,
    post_transaction_payload,
    post_wire,
    report_lost_stolen,
    set_clock,
    submit_and_verify_document,
    validate_error,
    validate_paginated,
    validate_success,
    ApiErrorId,
)
from test_helpers.test_users import make_rep_headers


def _setup_restricted_low_account():
    set_clock("2026-05-01T00:00:00Z")
    rep = create_rep(full_name="Rep K", crd_number="CRD-PP1")
    customer = create_customer(
        rep,
        customer_type="INDIVIDUAL",
        full_name="K Low",
        tax_id="TIN-PP1",
        country_risk_tier="LOW",
        is_pep=False,
    )
    submit_and_verify_document(customer["id"], rep, document_number="P-PP1")
    account = create_account(customer["id"], rep, product_set=["CASH"])
    approve_account(account["id"])
    post_wire(account["id"], rep, 1000.00)
    resp = api_client.restrict_account(
        account["id"], {"reason": "review"}, TEST_USERS["officer_headers"]
    )
    validate_success(resp)
    return rep, account


class TestStateBeatsFiscalOnRestrictedAccountWire:
    def test_restricted_wire_rejected_with_state_error_not_fiscal(self, api):
        """PRD §2.9: "When several checks could reject the same request, the server
        evaluates them in a fixed priority order" — "6. Target lifecycle and
        actionability — the target resource must be in a state that permits the
        operation" precedes "17. Wire velocity — a projected thirty-day wire total
        strictly above the account's tier limit yields `ERR_VELOCITY_LIMIT_EXCEEDED`
        (422)."
        PRD §3.5: "Posting against an account in `RESTRICTED` is refused with
        `ERR_ACCOUNT_RESTRICTED`" — the 300000.00 wire is over the LOW 250000 limit
        AND the account is RESTRICTED; the state error wins with 409.

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_restricted_account_wire
        """
        rep, account = _setup_restricted_low_account()
        resp = api_client.post_transaction(
            account["id"],
            post_transaction_payload(txn_type="WIRE_OUT", amount=300000.00),
            make_rep_headers(rep["id"]),
        )
        error = validate_error(resp, ApiErrorId.ERR_ACCOUNT_RESTRICTED)
        assert error["error_id"] == "ERR_ACCOUNT_RESTRICTED"
        assert resp.status_code == 409, (
            f"state rejection must be 409, not the fiscal 422; got {resp.status_code}"
        )

    def test_rejected_wire_leaves_velocity_aggregate_unchanged(self, api):
        """PRD §2.11: "every such cascade is atomic within the request: the primary
        mutation, every secondary transition, every recomputed aggregate, and every
        version increment all succeed or fail together."
        PRD §3.5: "The `wire_velocity_30d_amount` is the same window restricted to
        wires" — the rejected 300000.00 wire must not enter the aggregate, which stays
        at the pre-rejection 1000.00.

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_restricted_account_wire
        """
        rep, account = _setup_restricted_low_account()
        resp = api_client.post_transaction(
            account["id"],
            post_transaction_payload(txn_type="WIRE_OUT", amount=300000.00),
            make_rep_headers(rep["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_ACCOUNT_RESTRICTED)
        after = get_account(account["id"])
        assert after["wire_velocity_30d_amount"] == pytest.approx(1000.00, abs=0.01), (
            f"no partial posting may leak into the aggregate, "
            f"got {after['wire_velocity_30d_amount']}"
        )


class TestSafetyBeatsConstraintOnLostStolenDuplicateCert:
    def _setup_double_violation(self):
        """Account with in-flight deposit CN-PP2 AND an ACTIVE lost/stolen entry for
        the same certificate number."""
        set_clock("2026-05-01T00:00:00Z")
        rep = create_rep(full_name="Rep L", crd_number="CRD-PP2")
        customer = create_customer(
            rep,
            customer_type="INDIVIDUAL",
            full_name="L Low",
            tax_id="TIN-PP2",
            country_risk_tier="LOW",
            is_pep=False,
        )
        submit_and_verify_document(customer["id"], rep, document_number="P-PP2")
        account = create_account(customer["id"], rep, product_set=["CASH"])
        approve_account(account["id"])
        create_deposit(
            account["id"],
            certificate_number="CN-PP2",
            cusip="CUSIPPP2",
            security_name="PP2 Corp",
            quantity=5,
            unit_price=10.00,
        )
        report_lost_stolen(certificate_number="CN-PP2", cusip="CUSIPPP2")
        return account

    def test_safety_error_wins_over_duplicate_constraint(self, api):
        """PRD §2.9: "8. Lost/stolen registry — certificate numbers on the `ACTIVE`
        registry are refused with `ERR_CERT_REPORTED_LOST_STOLEN` (403), checked both
        at deposit intake and when advancing into authenticity review." precedes
        "11. Uniqueness — duplicate `crd_number`, duplicate `request_reference`, and
        duplicate certificate numbers (against non-rejected deposits and the `ACTIVE`
        registry) are rejected with `ERR_DUPLICATE_CRD_NUMBER`,
        `ERR_DUPLICATE_314A_REQUEST`, or `ERR_DUPLICATE_CERTIFICATE_NUMBER` (409)."
        The deposit is BOTH lost/stolen AND duplicate; the safety error wins with 403.

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_constraint_on_lost_stolen_duplicate_cert
        """
        account = self._setup_double_violation()
        resp = api_client.create_deposit(
            account["id"],
            {
                "certificate_number": "CN-PP2",
                "cusip": "CUSIPPP2",
                "security_name": "PP2 Corp",
                "quantity": 7,
                "unit_price": 10.00,
            },
            TEST_USERS["ops_headers"],
        )
        error = validate_error(resp, ApiErrorId.ERR_CERT_REPORTED_LOST_STOLEN)
        assert error["error_id"] == "ERR_CERT_REPORTED_LOST_STOLEN"
        assert resp.status_code == 403, (
            f"safety rejection must be 403, not the constraint 409; got {resp.status_code}"
        )

    def test_rejected_intake_persists_no_second_deposit(self, api):
        """PRD §2.11: "every such cascade is atomic within the request: the primary
        mutation, every secondary transition, every recomputed aggregate, and every
        version increment all succeed or fail together."
        PRD §3.8: "the certificate number must not appear on an `ACTIVE` lost/stolen
        entry, else `ERR_CERT_REPORTED_LOST_STOLEN`" — the refused intake leaves only
        the original in-flight deposit behind.

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_constraint_on_lost_stolen_duplicate_cert
        """
        account = self._setup_double_violation()
        resp = api_client.create_deposit(
            account["id"],
            {
                "certificate_number": "CN-PP2",
                "cusip": "CUSIPPP2",
                "security_name": "PP2 Corp",
                "quantity": 7,
                "unit_price": 10.00,
            },
            TEST_USERS["ops_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_CERT_REPORTED_LOST_STOLEN)
        resp = api_client.list_deposits(
            TEST_USERS["ops_headers"], params={"account_id": account["id"]}
        )
        deposits, meta = validate_paginated(resp)
        assert len(deposits) == 1 and meta["total_count"] == 1, (
            f"rejected intake must persist nothing; found {meta['total_count']} deposits"
        )
