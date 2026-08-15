"""Wire initiation: request schema, server-applied defaults, computed-field
rejection, role gating on creation, and the creation-time validation order."""
from test_helpers import (
    ApiErrorId,
    assert_wire,
    create_customer,
    create_wire_payload,
    setup_wire_room,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS

ADMIN = TEST_USERS["wire_ops_admin_headers"]
OPERATOR = TEST_USERS["wire_operator_headers"]
APPROVER = TEST_USERS["wire_approver_headers"]


class TestWireCreationSchema:
    def test_create_wire_missing_required_field_returns_invalid_request(self, api):
        """PRD §2.8: "(4) request-body schema conformance — required fields
        present, types correct, enum values in their declared domains, amount
        fields strictly positive, unknown keys rejected —
        `ERR_INVALID_REQUEST`"
        PRD §3.2: "A `WireOperator` initiates a wire by naming the debit
        account through `ordering_account_id`, the payee through
        `beneficiary_id`, the principal `amount_cents` (strictly positive),
        the payment rail `method` — one of `Fedwire`, `SWIFT`, or `CHIPS` —
        and a free-text `purpose`."

        Omitting the required `purpose` is rejected with ERR_INVALID_REQUEST
        and no wire is created.

        Design: Corner/entities/create_wire_missing_required_field_returns_invalid_request
        """
        room = setup_wire_room()
        payload = create_wire_payload(
            room["account"]["id"], room["beneficiary"]["id"], amount_cents=500000)
        del payload["purpose"]

        resp = api.create_wire(payload, OPERATOR)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

        wires, _ = validate_paginated(api.list_wires(
            OPERATOR, params={"ordering_account_id": room["account"]["id"]}))
        assert wires == [], f"no wire may be created, got {len(wires)}"

    def test_wire_create_computed_field_input_rejected(self, api):
        """PRD §2.8: "(4) request-body schema conformance — required fields
        present, types correct, enum values in their declared domains, amount
        fields strictly positive, unknown keys rejected —
        `ERR_INVALID_REQUEST`"
        PRD §3.3: "Every submission runs sanctions screening and computes the
        wire's `risk_score`, an integer from 0 to 100 that is recomputed
        identically at every repair."

        risk_score is computed by the server, so a client-supplied value is an
        unknown key on the creation schema and is rejected.

        Design: Corner/entities/wire_create_computed_field_input_rejected
        """
        room = setup_wire_room()
        payload = create_wire_payload(
            room["account"]["id"], room["beneficiary"]["id"], amount_cents=500000)
        payload["risk_score"] = 99

        resp = api.create_wire(payload, OPERATOR)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestWireCreationDefaults:
    def test_wire_create_defaults_applied(self, api):
        """PRD §3.2: "Three optional knobs refine the instruction: `currency`
        (defaulting to `USD`), `priority` (`NORMAL` by default, or `SAME_DAY`
        for an expedited dispatch that later attracts a surcharge), and
        `charge_mode` (`OUR` by default, or `BENEFICIARY_REMUNERATION`, which
        activates the beneficiary-pays fee share on `SWIFT` wires)."
        PRD §3.2: "A wire below the threshold enters `INITIATED` with
        `callback_status` `NONE` and no case."

        Omitting the optional knobs yields USD / NORMAL / OUR on the created
        wire.

        Design: Corner/entities/wire_create_defaults_applied
        """
        room = setup_wire_room()
        wire = validate_success(api.create_wire(
            {
                "ordering_account_id": room["account"]["id"],
                "beneficiary_id": room["beneficiary"]["id"],
                "amount_cents": 500000,
                "method": "CHIPS",
                "purpose": "defaults probe",
            },
            OPERATOR,
        ), 201)
        assert_wire(wire)
        assert wire["currency"] == "USD"
        assert wire["priority"] == "NORMAL"
        assert wire["charge_mode"] == "OUR"
        assert wire["status"] == "INITIATED"
        assert wire["callback_status"] == "NONE"


class TestWireCreationRoleGate:
    def test_wire_creation_forbidden_for_approver(self, api):
        """PRD §2.1: "A request whose role is not permitted for the target
        endpoint — including disposition-tier mismatches on sanctions hits,
        where the permitted role depends on the hit's current state — is
        rejected with `ERR_FORBIDDEN_ROLE`."
        PRD §4: POST /wire-ops/wires is authorized for `WireOperator` only.

        A WireApprover initiating a wire is rejected with ERR_FORBIDDEN_ROLE.

        Design: Corner/rbac/wire_creation_forbidden_for_approver
        """
        room = setup_wire_room()
        resp = api.create_wire(
            create_wire_payload(
                room["account"]["id"], room["beneficiary"]["id"],
                amount_cents=100000),
            APPROVER,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

        wires, _ = validate_paginated(api.list_wires(
            OPERATOR, params={"ordering_account_id": room["account"]["id"]}))
        assert wires == [], f"no wire may be created, got {len(wires)}"


class TestWireCreationValidationOrder:
    def test_mismatch_beats_frozen_customer(self, api):
        """PRD §2.8: "(5) cross-aggregate beneficiary/account consistency on
        wire creation (`ERR_BENEFICIARY_ACCOUNT_MISMATCH`), (6) account and
        beneficiary active-status gates on wire creation
        (`ERR_ACCOUNT_INACTIVE` / `ERR_BENEFICIARY_INACTIVE`), (7) the
        frozen-customer initiation gate (`ERR_CUSTOMER_FROZEN`)"
        PRD §2.8: "When several checks could reject the same request, the
        server evaluates them in a fixed priority order, and the first failure
        determines the error returned."

        A wire naming another customer's beneficiary while the ordering
        customer is FROZEN violates both (5) and (7); the referential
        mismatch is reported.

        Design: Difficulty/priority_pair_validation_conflict/wire_create_referential_mismatch_beats_customer_frozen_safety
        """
        room = setup_wire_room()
        other_customer = create_customer(legal_name="Other Customer")
        foreign_beneficiary = validate_success(api.create_beneficiary(
            {
                "customer_id": other_customer["id"],
                "name": "Foreign Ben",
                "bank_name": "ForeignBank",
                "account_number": "B-F001",
                "country_code": "US",
            },
            OPERATOR,
        ), 201)
        validate_success(api.freeze_customer(room["customer"]["id"], ADMIN), 200)

        resp = api.create_wire(
            create_wire_payload(
                room["account"]["id"], foreign_beneficiary["id"],
                amount_cents=500000),
            OPERATOR,
        )
        validate_error(resp, ApiErrorId.ERR_BENEFICIARY_ACCOUNT_MISMATCH)

        wires, _ = validate_paginated(api.list_wires(
            OPERATOR, params={"ordering_account_id": room["account"]["id"]}))
        assert wires == [], f"no wire may be created, got {len(wires)}"

    def test_each_creation_gate_fires_in_isolation(self, api):
        """PRD §3.2: "the beneficiary's owning `customer_id` must equal the
        ordering account's `customer_id` — a cross-aggregate consistency rule
        whose violation is `ERR_BENEFICIARY_ACCOUNT_MISMATCH`"
        PRD §3.2: "the ordering customer must be `ACTIVE` — a `FROZEN` or
        `CLOSED` customer cannot initiate new wires, rejected as
        `ERR_CUSTOMER_FROZEN`."

        Each rule fires on its own: a frozen customer with a matching
        beneficiary surfaces ERR_CUSTOMER_FROZEN; an active customer with a
        foreign beneficiary surfaces ERR_BENEFICIARY_ACCOUNT_MISMATCH.

        Design: Difficulty/priority_pair_validation_conflict/wire_create_referential_mismatch_beats_customer_frozen_safety
        """
        frozen_room = setup_wire_room()
        validate_success(
            api.freeze_customer(frozen_room["customer"]["id"], ADMIN), 200)
        resp_frozen = api.create_wire(
            create_wire_payload(
                frozen_room["account"]["id"],
                frozen_room["beneficiary"]["id"], amount_cents=500000),
            OPERATOR,
        )
        validate_error(resp_frozen, ApiErrorId.ERR_CUSTOMER_FROZEN)

        active_room = setup_wire_room()
        other_customer = create_customer(legal_name="Other Customer")
        foreign_beneficiary = validate_success(api.create_beneficiary(
            {
                "customer_id": other_customer["id"],
                "name": "Foreign Ben",
                "bank_name": "ForeignBank",
                "account_number": "B-F002",
                "country_code": "US",
            },
            OPERATOR,
        ), 201)
        resp_mismatch = api.create_wire(
            create_wire_payload(
                active_room["account"]["id"], foreign_beneficiary["id"],
                amount_cents=500000),
            OPERATOR,
        )
        validate_error(resp_mismatch, ApiErrorId.ERR_BENEFICIARY_ACCOUNT_MISMATCH)
