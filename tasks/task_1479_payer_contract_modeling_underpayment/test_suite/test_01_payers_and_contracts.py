"""Payer onboarding and contract lifecycle: defaults, window rules, renewal cascade."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    activate_contract,
    create_draft_contract,
    create_payer_contract_payload,
    create_payer_payload,
    create_test_payer,
    get_contract,
    validate_error,
    validate_success,
)
from test_helpers import api_client as _api_client
from test_helpers.fixtures import AUD, CA, CM


class TestPayerCreation:
    def test_payer_creation_applies_default_appeal_deadline(self, api):
        """PRD §3.1: "optionally `appeal_deadline_days` — the number of days
        allowed to file each appeal level, measured from the triggering event
        date, defaulting to 45 when omitted. A payer is born `ACTIVE`."

        Design: Corner/entities/ent_payer_creation_applies_default_appeal_deadline
        """
        payload = {"name": "Payer DEF", "payer_type": "COMMERCIAL"}
        payer = validate_success(api.create_payer(payload, CM), expected_status=201)
        assert payer["appeal_deadline_days"] == 45, (
            f"Omitted appeal_deadline_days must default to 45, got {payer['appeal_deadline_days']}"
        )
        assert payer["status"] == "ACTIVE"
        assert payer["version"] == 1

    def test_create_payer_missing_name_rejected(self, api):
        """PRD §2.8: "3. **Request shape** — on every write endpoint: required
        fields present, enum values valid, integers in range (amounts at least
        zero, basis-point fields within their declared bounds), dates
        well-formed, `effective_date` not after `expiration_date`,
        `admission_date` not after `discharge_date`, neither `discharge_date`
        nor `remittance_date` after today, and unknown body fields rejected,
        else `ERR_INVALID_REQUEST`."

        Design: Corner/entities/ent_create_payer_missing_name_rejected
        """
        resp = api.create_payer({"payer_type": "COMMERCIAL"}, CM)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)

    def test_create_payer_invalid_enum_rejected(self, api):
        """PRD §3.1: a payer is onboarded with "a `payer_type` of `COMMERCIAL`,
        `MEDICARE_ADVANTAGE`, `MEDICAID_MCO`, or `WORKERS_COMP`", and PRD §2.8
        rung 3 rejects invalid enum values with `ERR_INVALID_REQUEST`.

        Design: Corner/entities/ent_create_payer_invalid_enum_rejected
        """
        resp = api.create_payer({"name": "Payer X", "payer_type": "LLOYDS"}, CM)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)

    def test_create_contract_unknown_field_rejected(self, api):
        """PRD §2.8: "3. **Request shape** — on every write endpoint: required
        fields present, ... and unknown body fields rejected, else
        `ERR_INVALID_REQUEST`."

        Design: Corner/entities/ent_create_contract_unknown_field_rejected
        """
        payer = create_test_payer(name="Payer UF")
        payload = create_payer_contract_payload(payer["id"], contract_code="UF-2026")
        payload["region"] = "WEST"
        resp = api.create_payer_contract(payload, CA)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)

    def test_get_nonexistent_contract_returns_not_found(self, api):
        """PRD §2.8: "4. **Existence** — every resource id referenced in the
        path or body (payer, contract, term, provision, escalator, amendment,
        agreement, claim, case, appeal, proposal, alert) must exist, else
        `ERR_NOT_FOUND`."

        Design: Corner/entities/ent_get_nonexistent_contract_returns_not_found
        """
        resp = api.get_payer_contract(NON_EXISTENT_UUID, AUD)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


class TestContractLifecycle:
    def test_payer_deactivate_blocks_contract_activation(self, api):
        """PRD §3.1: "Deactivation by a `ContractManager` moves it to
        `INACTIVE`, its only terminal state, and from that moment forward any
        attempt to create a claim, create a contract, or activate a contract
        for that payer is rejected with `ERR_PAYER_INACTIVE`."

        Design: Corner/state_machines/sm_payer_deactivate_blocks_contract_activation
        """
        payer = create_test_payer(name="Payer PI")
        contract = create_draft_contract(payer["id"], contract_code="PI-2026")
        validate_success(api.deactivate_payer(payer["id"], CM))
        resp = api.activate_payer_contract(contract["id"], CM)
        validate_error(resp, ApiErrorId.ERR_PAYER_INACTIVE.value)
        assert get_contract(contract["id"])["status"] == "DRAFT"

    def test_terminated_contract_rejects_suspend(self, api):
        """PRD §3.1: "`EXPIRED`, `TERMINATED`, and `SUPERSEDED` are terminal —
        every further action against a contract in one of those states is
        rejected with `ERR_INVALID_STATE_TRANSITION`."

        Design: Corner/state_machines/sm_terminated_contract_rejects_suspend
        """
        payer = create_test_payer(name="Payer TL")
        contract = create_draft_contract(payer["id"], contract_code="TL-2026")
        activate_contract(contract["id"])
        validate_success(api.terminate_payer_contract(contract["id"], CM))
        resp = api.suspend_payer_contract(contract["id"], CM)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value)
        assert get_contract(contract["id"])["status"] == "TERMINATED"

    def test_contract_window_invalid_on_activate(self, api):
        """PRD §3.1: "Activation by a `ContractManager` requires the payer to
        be `ACTIVE` and the `expiration_date` to lie after today — a window
        that has already closed is rejected with `ERR_CONTRACT_WINDOW_INVALID`."

        Design: Corner/errors/err_contract_window_invalid_on_activate
        """
        payer = create_test_payer(name="Payer WI")
        contract = create_draft_contract(
            payer["id"], contract_code="WI-2026", expiration_date="2026-07-01"
        )
        resp = api.activate_payer_contract(contract["id"], CM)
        validate_error(resp, ApiErrorId.ERR_CONTRACT_WINDOW_INVALID.value)
        assert get_contract(contract["id"])["status"] == "DRAFT"

    def test_duplicate_contract_code_rejected(self, api):
        """PRD §3.1: "a human-readable `contract_code` that must be unique
        across all of that payer's contracts (`ERR_DUPLICATE_CONTRACT_CODE`)".

        Design: Corner/errors/err_duplicate_contract_code_rejected
        """
        payer = create_test_payer(name="Payer DC")
        create_draft_contract(
            payer["id"], contract_code="DUP-1", expiration_date="2026-06-30"
        )
        resp = api.create_payer_contract(
            create_payer_contract_payload(
                payer["id"],
                contract_code="DUP-1",
                effective_date="2026-07-01",
                expiration_date="2026-12-31",
            ),
            CA,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_CONTRACT_CODE.value)

    def test_cross_payer_renewal_link_rejected(self, api):
        """PRD §3.1: "An optional `prior_contract_id` chains the contract to
        its renewal predecessor; the predecessor must belong to the same payer,
        or creation fails with `ERR_PRIOR_CONTRACT_MISMATCH`."

        Design: Corner/validations/val_cross_payer_renewal_link_rejected
        """
        payer_a = create_test_payer(name="Payer PA")
        contract_a = create_draft_contract(payer_a["id"], contract_code="PA-2026")
        payer_b = create_test_payer(
            name="Payer PB", payer_type="MEDICAID_MCO", appeal_deadline_days=30
        )
        resp = api.create_payer_contract(
            create_payer_contract_payload(
                payer_b["id"],
                contract_code="PB-2027",
                effective_date="2027-01-01",
                expiration_date="2027-12-31",
                prior_contract_id=contract_a["id"],
            ),
            CA,
        )
        validate_error(resp, ApiErrorId.ERR_PRIOR_CONTRACT_MISMATCH.value)


class TestRenewalWindowOverlap:
    def test_renewal_linked_pair_may_share_one_boundary_date(self, api):
        """PRD §3.1: "coverage windows of the same payer's contracts may not
        share any calendar date unless the two contracts are renewal-linked
        through `prior_contract_id`, in which case they may share at most one
        boundary date."

        Design: Difficulty/resource_temporal_overlap/renewal_linked_contracts_share_exactly_one_boundary_date
        """
        payer = create_test_payer(name="Payer RT")
        contract_a = create_draft_contract(payer["id"], contract_code="RT-A")
        # Renewal-linked pair sharing exactly the boundary date 2026-12-31.
        contract_b = validate_success(
            api.create_payer_contract(
                create_payer_contract_payload(
                    payer["id"],
                    contract_code="RT-B",
                    effective_date="2026-12-31",
                    expiration_date="2027-12-31",
                    prior_contract_id=contract_a["id"],
                ),
                CA,
            ),
            expected_status=201,
        )
        assert contract_b["status"] == "DRAFT"
        # Unlinked and fully disjoint from both existing windows: also created.
        contract_d = validate_success(
            api.create_payer_contract(
                create_payer_contract_payload(
                    payer["id"],
                    contract_code="RT-D",
                    effective_date="2028-01-01",
                    expiration_date="2028-12-31",
                ),
                CA,
            ),
            expected_status=201,
        )
        assert contract_d["id"]

    def test_renewal_linked_pair_sharing_two_dates_rejected(self, api):
        """PRD §3.1: "coverage windows of the same payer's contracts may not
        share any calendar date unless the two contracts are renewal-linked
        through `prior_contract_id`, in which case they may share at most one
        boundary date. Overlapping windows outside that allowance are rejected
        with `ERR_CONTRACT_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/renewal_linked_contracts_share_exactly_one_boundary_date
        """
        payer = create_test_payer(name="Payer RT")
        contract_a = create_draft_contract(payer["id"], contract_code="RT-A")
        # Renewal-linked but sharing two dates (2026-12-30 and 2026-12-31).
        resp = api.create_payer_contract(
            create_payer_contract_payload(
                payer["id"],
                contract_code="RT-C",
                effective_date="2026-12-30",
                expiration_date="2027-12-31",
                prior_contract_id=contract_a["id"],
            ),
            CA,
        )
        validate_error(resp, ApiErrorId.ERR_CONTRACT_WINDOW_OVERLAP.value)
        # Unlinked overlap is equally forbidden.
        resp2 = api.create_payer_contract(
            create_payer_contract_payload(
                payer["id"],
                contract_code="RT-E",
                effective_date="2026-06-01",
                expiration_date="2027-06-30",
            ),
            CA,
        )
        validate_error(resp2, ApiErrorId.ERR_CONTRACT_WINDOW_OVERLAP.value)

    def test_activation_supersedes_renewal_predecessor(self, api):
        """PRD §3.1: "Successful activation increments the contract's `version`
        and triggers the renewal cascade: if the newly activated contract's
        `prior_contract_id` references a contract currently `ACTIVE` or
        `SUSPENDED`, that predecessor transitions to `SUPERSEDED` with its own
        version increment."

        Design: Corner/endpoints/ep_activation_supersedes_renewal_predecessor
        """
        payer = create_test_payer(name="Payer RN")
        contract_a = create_draft_contract(payer["id"], contract_code="RN-2026")
        contract_a = activate_contract(contract_a["id"])
        a_version_after_activate = contract_a["version"]
        contract_b = create_draft_contract(
            payer["id"],
            contract_code="RN-2027",
            effective_date="2026-12-31",
            expiration_date="2027-12-31",
            prior_contract_id=contract_a["id"],
        )
        activated_b = validate_success(api.activate_payer_contract(contract_b["id"], CM))
        assert activated_b["status"] == "ACTIVE"
        contract_a_after = get_contract(contract_a["id"])
        assert contract_a_after["status"] == "SUPERSEDED"
        assert contract_a_after["version"] == a_version_after_activate + 1
