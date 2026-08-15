"""Role-based access control and disclosure ownership (PRD §2.1, §3.3)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    NON_EXISTENT_UUID,
    api_client,
    create_carrier,
    create_policy,
    create_producer,
    create_product,
    create_statement,
    deliver_policy_disclosure,
    make_producer_headers,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
ACCOUNTANT = TEST_USERS["accountant_headers"]


class TestRoleDenials:
    def test_producer_cannot_create_policy(self):
        """PRD §2.1: "The `Producer` role represents a licensed writing agent
        or upline producer; it has read access across the API and exactly one
        write capability — acknowledging its own compensation disclosure."
        PRD §2.1: "When the caller is authenticated but the role is not
        authorized for the requested operation, the request is rejected with
        `ERR_FORBIDDEN_FOR_ROLE`."

        Design: Corner/rbac/producer_cannot_create_policy
        """
        producer = create_producer(name="Role R", license_number="LIC-R1R")
        res = api_client.create_policy(
            {
                "policy_number": "P-R1R",
                "product_id": NON_EXISTENT_UUID,
                "producer_id": producer["id"],
                "insured_name": "I",
                "billing_type": "DIRECT_BILL",
                "premium_annual_cents": 2400000,
                "effective_date": "2026-08-01",
            },
            make_producer_headers(producer["id"]),
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE, expected_status=403)

    def test_accountant_cannot_generate_tax_forms(self):
        """PRD §3.9: "Generation is an `AgencyAdmin`-exclusive action taking
        a `tax_year`."
        PRD §2.1: "When the caller is authenticated but the role is not
        authorized for the requested operation, the request is rejected with
        `ERR_FORBIDDEN_FOR_ROLE`."

        Design: Corner/rbac/accountant_cannot_generate_tax_forms
        """
        res = api_client.generate_tax_forms({"tax_year": 2026}, ACCOUNTANT)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE, expected_status=403)

    def test_accountant_cannot_waive_statement_line(self):
        """PRD §3.7: "Separately, an `AgencyAdmin` may waive an `ORPHAN` line
        by naming its `line_ref`, moving the line to `WAIVED`."
        PRD §2.1: "The `AgencyAdmin` is the agency principal and acts as a
        superuser: it may perform every operation in the API and holds
        exclusive control over producer termination, chargeback write-offs,
        trust remittance to carriers, waiving orphan statement lines, 1099
        form generation and finalization, and advancement of the logical
        clock."

        Design: Corner/rbac/accountant_cannot_waive_statement_line
        """
        carrier = create_carrier(name="Carrier RB", carrier_code="CRB")
        statement = create_statement(
            carrier["id"],
            [{"line_ref": "GHOST-9", "reported_amount_cents": 1000}],
        )
        validate_success(api_client.start_reconciliation(statement["id"], ADMIN), 200)
        res = api_client.waive_statement_line(
            statement["id"], {"line_ref": "GHOST-9"}, ACCOUNTANT
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE, expected_status=403)


class TestDisclosureOwnership:
    def _setup_delivered_disclosure(self):
        owner = create_producer(name="Owner A", license_number="LIC-R2A")
        carrier = create_carrier(name="Carrier R2", carrier_code="CR2")
        product = create_product(carrier["id"], product_code="PR2")
        policy = create_policy(
            product["id"],
            owner["id"],
            policy_number="P-R2",
            premium_annual_cents=2400000,
        )
        disclosure = deliver_policy_disclosure(policy["id"])
        return owner, policy, disclosure

    def test_producer_cannot_acknowledge_others_disclosure(self):
        """PRD §2.1: "Concretely, acknowledging a compensation disclosure
        requires the caller's `X-User-ID` to equal the disclosure's
        `producer_id`, and a mismatch is rejected with
        `ERR_NOT_RESOURCE_OWNER`."

        Design: Corner/rbac/producer_cannot_acknowledge_others_disclosure
        """
        owner, _, disclosure = self._setup_delivered_disclosure()
        other = create_producer(name="Other B", license_number="LIC-R2B")
        res = api_client.acknowledge_disclosure(
            disclosure["id"], make_producer_headers(other["id"])
        )
        validate_error(res, ApiErrorId.ERR_NOT_RESOURCE_OWNER, expected_status=403)
        after = validate_success(
            api_client.get_disclosure(disclosure["id"], ADMIN), 200
        )
        assert after["status"] == "DELIVERED"

    def test_acknowledge_is_terminal(self):
        """PRD §3.3: "The producer personally acknowledges it — `DELIVERED`
        to `ACKNOWLEDGED`, stamping `acknowledged_at` — and ownership is
        enforced: the acknowledging caller's `X-User-ID` must equal the
        disclosure's `producer_id`, or the attempt is rejected with
        `ERR_NOT_RESOURCE_OWNER`. `ACKNOWLEDGED` is terminal."
        PRD §2.9: "4. **State admissibility** — the target resource is in a
        state that allows the operation, and the optimistic-concurrency check
        of §2.7 passes, else `ERR_INVALID_STATE` or `ERR_STALE_VERSION`.
        Terminal-state lockdowns, such as paying or reversing an already
        `PAID` invoice, fail here."

        Design: Corner/state_machines/acknowledge_terminal_lockdown
        """
        owner, _, disclosure = self._setup_delivered_disclosure()
        acknowledged = validate_success(
            api_client.acknowledge_disclosure(
                disclosure["id"], make_producer_headers(owner["id"])
            ),
            200,
        )
        assert acknowledged["status"] == "ACKNOWLEDGED"
        assert acknowledged["acknowledged_at"] is not None

        res = api_client.acknowledge_disclosure(
            disclosure["id"], make_producer_headers(owner["id"])
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
