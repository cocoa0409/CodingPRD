"""Rate content loading (terms/escalators) and the amendment lifecycle (PRD §3.2-§3.3)."""
from test_helpers import (
    ApiErrorId,
    activate_contract,
    add_contract_term,
    approve_amendment,
    create_amendment,
    create_draft_contract,
    create_escalator,
    create_rate_amendment_payload,
    create_rate_escalator_payload,
    create_test_payer,
    get_amendment,
    get_contract,
    make_contract_analyst_headers,
    make_contract_manager_headers,
    setup_active_contract,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import api_client as _unused  # noqa: F401  (symmetry)
from test_helpers.fixtures import CA, CM, RIA


class TestTermLoading:
    def test_term_creation_on_active_contract_rejected(self, api):
        """PRD §3.2: "Once the contract has left `DRAFT`, mid-term rate changes
        must flow through the amendment machinery of §3.3; direct creation of
        terms, carve-outs, or stop-loss provisions against a non-draft contract
        is rejected with `ERR_CONTRACT_NOT_DRAFT`."

        Design: Corner/errors/err_contract_not_draft_on_term_creation
        """
        ctx = setup_active_contract()
        resp = api.create_contract_term(
            {
                "contract_id": ctx["contract"]["id"],
                "service_category": "EMERGENCY",
                "rate_model": "CASE_RATE",
                "base_rate_cents": 200000,
            },
            CA,
        )
        validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_DRAFT.value)

    def test_duplicate_service_category_rejected(self, api):
        """PRD §3.2: "at most one term per category per contract, enforced as
        `ERR_DUPLICATE_SERVICE_CATEGORY`".

        Design: Corner/errors/err_duplicate_service_category_rejected
        """
        payer = create_test_payer(name="Payer DS")
        contract = create_draft_contract(payer["id"], contract_code="DS-2026")
        add_contract_term(contract["id"])
        resp = api.create_contract_term(
            {
                "contract_id": contract["id"],
                "service_category": "INPATIENT_MEDICAL",
                "rate_model": "CASE_RATE",
                "base_rate_cents": 200000,
            },
            CA,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_SERVICE_CATEGORY.value)

    def test_invalid_rate_parameters_percent_missing(self, api):
        """PRD §3.2: "`percent_of_charge_bp` carries basis points of billed
        charge and is required exactly when the model is `PERCENT_OF_CHARGE`.
        Mismatched rate-field combinations are rejected with
        `ERR_INVALID_RATE_PARAMETERS`."

        Design: Corner/errors/err_invalid_rate_parameters_percent_missing
        """
        payer = create_test_payer(name="Payer RP")
        contract = create_draft_contract(payer["id"], contract_code="RP-2026")
        resp = api.create_contract_term(
            {
                "contract_id": contract["id"],
                "service_category": "IMAGING",
                "rate_model": "PERCENT_OF_CHARGE",
            },
            CA,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_RATE_PARAMETERS.value)


class TestEscalatorCreation:
    def test_escalator_creation_on_active_contract_allowed(self, api):
        """PRD §3.2: "Rate escalators are the one piece of rate content that
        may also be scheduled after activation: creation requires the contract
        to be `DRAFT` or `ACTIVE`, and any other status yields
        `ERR_INVALID_STATE_TRANSITION`."

        Design: Corner/validations/val_escalator_creation_on_active_contract_allowed
        """
        ctx = setup_active_contract()
        resp = api.create_rate_escalator(
            create_rate_escalator_payload(
                ctx["contract"]["id"], effective_date="2026-09-01", escalator_bp=1500
            ),
            CA,
        )
        escalator = validate_success(resp, expected_status=201)
        assert escalator["status"] == "SCHEDULED"

    def test_escalator_creation_on_suspended_contract_rejected(self, api):
        """PRD §3.2: "creation requires the contract to be `DRAFT` or
        `ACTIVE`, and any other status yields `ERR_INVALID_STATE_TRANSITION`."

        Design: Corner/state_machines/sm_escalator_creation_on_suspended_contract_rejected
        """
        ctx = setup_active_contract()
        validate_success(api.suspend_payer_contract(ctx["contract"]["id"], CM))
        resp = api.create_rate_escalator(
            create_rate_escalator_payload(
                ctx["contract"]["id"], effective_date="2026-09-01", escalator_bp=1000
            ),
            CA,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value)
        data, meta = validate_paginated(
            api.list_rate_escalators(CA, params={"contract_id": ctx["contract"]["id"]})
        )
        assert data == [] and meta["total_count"] == 0

    def test_escalator_out_of_term_rejected(self, api):
        """PRD §3.2: an escalator carries "an `effective_date` that must lie
        inside the contract term (`ERR_ESCALATOR_OUT_OF_TERM`)".

        Design: Corner/errors/err_escalator_out_of_term_rejected
        """
        payer = create_test_payer(name="Payer EO")
        contract = create_draft_contract(payer["id"], contract_code="EO-2026")
        resp = api.create_rate_escalator(
            create_rate_escalator_payload(
                contract["id"], effective_date="2025-12-31", escalator_bp=1000
            ),
            CA,
        )
        validate_error(resp, ApiErrorId.ERR_ESCALATOR_OUT_OF_TERM.value)

    def test_escalator_date_collision_rejected(self, api):
        """PRD §3.2: an escalator's effective date "must be unique among the
        contract's escalators (`ERR_ESCALATOR_DATE_COLLISION`)".

        Design: Corner/errors/err_escalator_date_collision_rejected
        """
        payer = create_test_payer(name="Payer EC")
        contract = create_draft_contract(payer["id"], contract_code="EC-2026")
        create_escalator(contract["id"], effective_date="2026-06-01", escalator_bp=1000)
        resp = api.create_rate_escalator(
            create_rate_escalator_payload(
                contract["id"],
                effective_date="2026-06-01",
                escalator_bp=2000,
                compounding=False,
            ),
            CA,
        )
        validate_error(resp, ApiErrorId.ERR_ESCALATOR_DATE_COLLISION.value)
        data, _meta = validate_paginated(
            api.list_rate_escalators(CA, params={"contract_id": contract["id"]})
        )
        assert len(data) == 1


class TestAmendmentLifecycle:
    def test_amendment_self_approve_rejected(self, api):
        """PRD §2.9: "A rate amendment must be approved by a different operator
        than the one who created it: approval compares `X-User-ID` against the
        amendment's recorded `created_by_user_id` and rejects a match with
        `ERR_SOD_AMENDMENT_SELF_APPROVE`."

        Design: Corner/errors/err_sod_amendment_self_approve_rejected
        """
        ctx = setup_active_contract()
        amendment = create_amendment(
            ctx["contract"]["id"],
            ctx["contract_version"],
            creator_user_id="cm-1",
            creator_role="manager",
            effective_date="2026-09-01",
        )
        resp = api.approve_rate_amendment(
            amendment["id"], make_contract_manager_headers("cm-1")
        )
        validate_error(resp, ApiErrorId.ERR_SOD_AMENDMENT_SELF_APPROVE.value)
        after = get_amendment(amendment["id"])
        assert after["status"] == "DRAFT"
        assert after["approved_by_user_id"] is None

    def test_amendment_effective_out_of_term_rejected(self, api):
        """PRD §3.3: the payload names "an `effective_date` that must lie
        within the contract term (`ERR_AMENDMENT_EFFECTIVE_OUT_OF_TERM`)".

        Design: Corner/errors/err_amendment_effective_out_of_term_rejected
        """
        ctx = setup_active_contract()
        resp = api.create_rate_amendment(
            create_rate_amendment_payload(
                ctx["contract"]["id"],
                ctx["contract_version"],
                effective_date="2027-02-01",
            ),
            make_contract_analyst_headers("ca-1"),
        )
        validate_error(resp, ApiErrorId.ERR_AMENDMENT_EFFECTIVE_OUT_OF_TERM.value)

    def test_amendment_supersede_other_contract_rejected(self, api):
        """PRD §3.3: "An optional `supersedes_amendment_id` chains the
        amendment to the prior amendment it replaces; the referenced amendment
        must belong to the same contract, else
        `ERR_AMENDMENT_SUPERSEDE_MISMATCH`."

        Design: Corner/validations/val_amendment_supersede_other_contract_rejected
        """
        payer = create_test_payer(name="Payer SM")
        # Both contracts must be activatable at the default clock
        # (2026-08-01), i.e. expiration_date after today (PRD §3.1), and their
        # windows must not overlap (PRD §3.1 ERR_CONTRACT_WINDOW_OVERLAP).
        c1 = create_draft_contract(
            payer["id"], contract_code="SM-H1", expiration_date="2026-08-31"
        )
        add_contract_term(c1["id"])
        c1 = activate_contract(c1["id"])
        c2 = create_draft_contract(
            payer["id"],
            contract_code="SM-H2",
            effective_date="2026-09-01",
            expiration_date="2027-06-30",
        )
        add_contract_term(c2["id"])
        c2 = activate_contract(c2["id"])
        m2 = create_amendment(c2["id"], c2["version"], effective_date="2026-10-01")
        resp = api.create_rate_amendment(
            create_rate_amendment_payload(
                c1["id"],
                c1["version"],
                effective_date="2026-03-01",
                term_overrides=[
                    {"service_category": "INPATIENT_MEDICAL", "base_rate_cents": 105000}
                ],
                supersedes_amendment_id=m2["id"],
            ),
            make_contract_analyst_headers("ca-1"),
        )
        validate_error(resp, ApiErrorId.ERR_AMENDMENT_SUPERSEDE_MISMATCH.value)

    def test_voided_amendment_rejects_second_void(self, api):
        """PRD §3.3: "A manager may also void an amendment while it is `DRAFT`
        or `APPROVED`." A `VOIDED` amendment is terminal, so a second void is
        an undefined transition, rejected per PRD §2.8 rung 6: "State
        violations not covered by a more specific identifier are rejected as
        `ERR_INVALID_STATE_TRANSITION`."

        Design: Corner/state_machines/sm_voided_amendment_rejects_second_void
        """
        ctx = setup_active_contract()
        amendment = create_amendment(
            ctx["contract"]["id"], ctx["contract_version"], effective_date="2026-09-01"
        )
        validate_success(api.void_rate_amendment(amendment["id"], CM))
        resp = api.void_rate_amendment(amendment["id"], CM)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value)
        assert get_amendment(amendment["id"])["status"] == "VOIDED"

    def test_new_amendment_voids_prior_pending(self, api):
        """PRD §3.3: "A successful create stamps the amendment `DRAFT`, records
        the caller as `created_by_user_id`, voids the contract's prior pending
        amendment — any prior amendment still `DRAFT` or `APPROVED` moves to
        `VOIDED` with a version bump — and increments the contract's
        `version`."

        Design: Corner/endpoints/ep_new_amendment_voids_prior_pending
        """
        ctx = setup_active_contract()
        a1 = create_amendment(
            ctx["contract"]["id"], ctx["contract_version"], effective_date="2026-09-01"
        )
        cv2 = get_contract(ctx["contract"]["id"])["version"]
        a2 = create_amendment(
            ctx["contract"]["id"],
            cv2,
            effective_date="2026-10-01",
            term_overrides=[
                {"service_category": "INPATIENT_MEDICAL", "base_rate_cents": 115000}
            ],
        )
        assert a2["status"] == "DRAFT"
        a1_after = get_amendment(a1["id"])
        assert a1_after["status"] == "VOIDED"
        assert a1_after["version"] == a1["version"] + 1

    def test_amendment_create_stale_version_rejected(self, api):
        """PRD §2.7: "Both request bodies must carry
        `expected_contract_version`, a non-optional field holding the `version`
        of the target `PayerContract` as the client last observed it. If that
        value does not equal the contract's current `version` — for example
        because another writer advanced the contract since the client last
        read it — the request is rejected with `ERR_STALE_CONTRACT_VERSION`
        (HTTP 412)."

        Design: Corner/cross_cutting_layers/xc_amendment_create_stale_version_rejected
        """
        ctx = setup_active_contract()
        stale_version = ctx["contract_version"]
        a1 = create_amendment(
            ctx["contract"]["id"], stale_version, effective_date="2026-09-01"
        )
        assert a1["status"] == "DRAFT"
        resp = api.create_rate_amendment(
            create_rate_amendment_payload(
                ctx["contract"]["id"],
                stale_version,
                effective_date="2026-10-01",
                term_overrides=[
                    {"service_category": "INPATIENT_MEDICAL", "base_rate_cents": 115000}
                ],
            ),
            make_contract_analyst_headers("ca-1"),
        )
        validate_error(resp, ApiErrorId.ERR_STALE_CONTRACT_VERSION.value)
        # A failed create must not void the still-pending amendment.
        assert get_amendment(a1["id"])["status"] == "DRAFT"

    def test_ria_cannot_approve_amendment(self, api):
        """PRD §2.1: "A request whose role is valid but not among the roles
        authorized for the target endpoint is rejected with
        `ERR_FORBIDDEN_FOR_ROLE`." PRD §4 authorizes only ContractManager for
        `POST /api/rate-amendments/{id}/approve`.

        Design: Corner/rbac/rbac_ria_cannot_approve_amendment
        """
        ctx = setup_active_contract()
        amendment = create_amendment(
            ctx["contract"]["id"], ctx["contract_version"], effective_date="2026-09-01"
        )
        resp = api.approve_rate_amendment(amendment["id"], RIA)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE.value)
        assert get_amendment(amendment["id"])["status"] == "DRAFT"


class TestAmendmentApprovalContractGate:
    def _setup_suspended_with_draft_amendment(self, api):
        ctx = setup_active_contract()
        amendment = create_amendment(
            ctx["contract"]["id"],
            ctx["contract_version"],
            creator_user_id="ca-1",
            effective_date="2026-09-01",
        )
        validate_success(api.suspend_payer_contract(ctx["contract"]["id"], CM))
        return ctx, amendment

    def test_approve_rejected_while_contract_suspended(self, api):
        """PRD §3.3: "Approval is a `ContractManager` act with two fences,
        evaluated in ladder order: the contract must be `ACTIVE`
        (`ERR_CONTRACT_NOT_ACTIVE`), and segregation of duties forbids the
        creator from approving their own work
        (`ERR_SOD_AMENDMENT_SELF_APPROVE`)."

        Design: Difficulty/cross_entity_state_dependency/amendment_approval_gated_on_contract_active
        """
        ctx, amendment = self._setup_suspended_with_draft_amendment(api)
        resp = api.approve_rate_amendment(
            amendment["id"], make_contract_manager_headers("cm-2")
        )
        validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_ACTIVE.value)
        assert get_amendment(amendment["id"])["status"] == "DRAFT"

    def test_approve_succeeds_after_resume(self, api):
        """PRD §3.1: "Resuming a `SUSPENDED` contract re-applies the
        expiration-window check before returning it to `ACTIVE`." PRD §3.3:
        "Approval records `approved_by_user_id` and moves the amendment to
        `APPROVED`."

        Design: Difficulty/cross_entity_state_dependency/amendment_approval_gated_on_contract_active
        """
        ctx, amendment = self._setup_suspended_with_draft_amendment(api)
        # Sanity: the SUSPENDED contract rejects the approval.
        validate_error(
            api.approve_rate_amendment(
                amendment["id"], make_contract_manager_headers("cm-2")
            ),
            ApiErrorId.ERR_CONTRACT_NOT_ACTIVE.value,
        )
        validate_success(api.resume_payer_contract(ctx["contract"]["id"], CM))
        approved = validate_success(
            api.approve_rate_amendment(
                amendment["id"], make_contract_manager_headers("cm-2")
            )
        )
        assert approved["status"] == "APPROVED"
        assert approved["approved_by_user_id"] == "cm-2"
