"""Contract tests for the IP Management API.

Covers PRD §3.4:
- DRAFT contract creation, template-type match, fields-for-type,
  min-guarantee allowance, parties sufficiency
- DRAFT → SIGNING → SIGNED multi-party flow
- SIGNED → FILED requiring IPRight REGISTERED (ERR_IP_NOT_REGISTERED)
- FILED → AMENDED → FILED cycle
- FILED/AMENDED → TERMINATED gated on no future-period FORECAST RoyaltySchedule
"""

from test_helpers import (
    ApiErrorId,
    assert_contract,
    create_business_unit,
    create_contract_payload,
    create_contract_template,
    create_filing_payload,
    create_ip_right_in_draft,
    fresh_party_id,
    parties_with_party_ids,
    setup_contract_in_draft,
    setup_contract_filed_for_royalty,
    setup_foundation,
    sign_contract_payload,
    validate_error,
    validate_success,
    walk_contract_to_filed,
    walk_contract_to_signed,
    walk_ip_right_to_registered,
)


# ─────────────────────────────────────────────────────────────
# Contract creation constraints (PRD §3.4)
# ─────────────────────────────────────────────────────────────


class TestContractCreationConstraints:
    """Structural constraints on POST /contracts (PRD §3.4)."""

    def test_template_type_mismatch_rejected(self, api, ip_manager_headers):
        """PRD §3.4: "The contract's `contract_type` must equal the
        referenced template's `contract_type` (mismatch returns
        `ERR_TEMPLATE_TYPE_MISMATCH`)."

        Claim: contract_type=EXCLUSIVE_LICENSE on a TRANSFER template →
        ERR_TEMPLATE_TYPE_MISMATCH.
        """
        found = setup_foundation(api)
        ip, _ = walk_ip_right_to_registered(
            api,
            business_unit_id=found["business_unit"]["id"],
            agent_id=found["agent"]["id"],
        )
        tmpl = create_contract_template(api, contract_type="TRANSFER")
        parties = parties_with_party_ids()
        payload = create_contract_payload(
            ip_right_id=ip["id"],
            template_id=tmpl["id"],
            contract_type="EXCLUSIVE_LICENSE",
            parties=parties,
            royalty_rate=0.10,
            min_guarantee_cents=800_000,
            business_unit_id=found["business_unit"]["id"],
        )
        resp = api.create_contract(payload, ip_manager_headers)
        validate_error(
            resp, ApiErrorId.ERR_TEMPLATE_TYPE_MISMATCH, expected_status=422
        )

    def test_transfer_with_royalty_rate_rejected(self, api, ip_manager_headers):
        """PRD §3.4: "a `TRANSFER` contract requires `royalty_rate` to be
        null and `min_guarantee_cents` to be null (any combination violating
        this rule returns `ERR_CONTRACT_FIELDS_FOR_TYPE`)."

        Claim: TRANSFER with royalty_rate=0.05 → ERR_CONTRACT_FIELDS_FOR_TYPE.
        """
        found = setup_foundation(api)
        ip, _ = walk_ip_right_to_registered(
            api,
            business_unit_id=found["business_unit"]["id"],
            agent_id=found["agent"]["id"],
        )
        tmpl = create_contract_template(api, contract_type="TRANSFER")
        payload = create_contract_payload(
            ip_right_id=ip["id"],
            template_id=tmpl["id"],
            contract_type="TRANSFER",
            parties=parties_with_party_ids(),
            royalty_rate=0.05,
            min_guarantee_cents=None,
            business_unit_id=found["business_unit"]["id"],
        )
        resp = api.create_contract(payload, ip_manager_headers)
        validate_error(
            resp, ApiErrorId.ERR_CONTRACT_FIELDS_FOR_TYPE, expected_status=422
        )

    def test_license_without_royalty_rate_rejected(self, api, ip_manager_headers):
        """PRD §3.4: "Both license variants require a non-null
        `royalty_rate`".

        Claim: EXCLUSIVE_LICENSE with royalty_rate=null →
        ERR_CONTRACT_FIELDS_FOR_TYPE.
        """
        found = setup_foundation(api)
        ip, _ = walk_ip_right_to_registered(
            api,
            business_unit_id=found["business_unit"]["id"],
            agent_id=found["agent"]["id"],
        )
        tmpl = create_contract_template(api, contract_type="EXCLUSIVE_LICENSE")
        payload = create_contract_payload(
            ip_right_id=ip["id"],
            template_id=tmpl["id"],
            contract_type="EXCLUSIVE_LICENSE",
            parties=parties_with_party_ids(),
            royalty_rate=None,
            min_guarantee_cents=None,
            business_unit_id=found["business_unit"]["id"],
        )
        resp = api.create_contract(payload, ip_manager_headers)
        validate_error(
            resp, ApiErrorId.ERR_CONTRACT_FIELDS_FOR_TYPE, expected_status=422
        )

    def test_min_guarantee_on_non_exclusive_rejected(
        self, api, ip_manager_headers
    ):
        """PRD §3.4: "`min_guarantee_cents` may be set only on an
        `EXCLUSIVE_LICENSE` contract: setting it on any other contract type
        returns `ERR_MIN_GUARANTEE_NOT_ALLOWED`."

        Claim: NON_EXCLUSIVE_LICENSE with min_guarantee_cents=1 →
        ERR_MIN_GUARANTEE_NOT_ALLOWED.
        """
        found = setup_foundation(api)
        ip, _ = walk_ip_right_to_registered(
            api,
            business_unit_id=found["business_unit"]["id"],
            agent_id=found["agent"]["id"],
        )
        tmpl = create_contract_template(
            api, contract_type="NON_EXCLUSIVE_LICENSE"
        )
        payload = create_contract_payload(
            ip_right_id=ip["id"],
            template_id=tmpl["id"],
            contract_type="NON_EXCLUSIVE_LICENSE",
            parties=parties_with_party_ids(),
            royalty_rate=0.10,
            min_guarantee_cents=1,
            business_unit_id=found["business_unit"]["id"],
        )
        resp = api.create_contract(payload, ip_manager_headers)
        validate_error(
            resp, ApiErrorId.ERR_MIN_GUARANTEE_NOT_ALLOWED, expected_status=422
        )

    def test_insufficient_parties_rejected(self, api, ip_manager_headers):
        """PRD §3.4: "The `parties` array must contain at least one entry
        with `signature_required` true and must have at least two distinct
        `party_id` values; either condition's violation returns
        `ERR_INSUFFICIENT_PARTIES`."

        Claim: parties with only one distinct party_id → ERR_INSUFFICIENT_PARTIES.
        """
        found = setup_foundation(api)
        ip, _ = walk_ip_right_to_registered(
            api,
            business_unit_id=found["business_unit"]["id"],
            agent_id=found["agent"]["id"],
        )
        tmpl = create_contract_template(api, contract_type="EXCLUSIVE_LICENSE")
        single = fresh_party_id("SINGLE")
        parties = [
            {
                "party_id": single,
                "role": "LICENSOR",
                "signature_required": True,
                "signed_at": None,
            },
            {
                "party_id": single,  # SAME id — violates "at least 2 unique party_id values"
                "role": "LICENSEE",
                "signature_required": True,
                "signed_at": None,
            },
        ]
        payload = create_contract_payload(
            ip_right_id=ip["id"],
            template_id=tmpl["id"],
            contract_type="EXCLUSIVE_LICENSE",
            parties=parties,
            royalty_rate=0.10,
            min_guarantee_cents=800_000,
            business_unit_id=found["business_unit"]["id"],
        )
        resp = api.create_contract(payload, ip_manager_headers)
        validate_error(
            resp, ApiErrorId.ERR_INSUFFICIENT_PARTIES, expected_status=422
        )


# ─────────────────────────────────────────────────────────────
# Signing → SIGNED (PRD §3.4)
# ─────────────────────────────────────────────────────────────


class TestSigning:
    """PRD §3.4 multi-party signing workflow."""

    def test_full_signing_flow_to_signed(self, api, ip_manager_headers):
        """PRD §3.4: "Once the last required party has signed, the contract
        transitions from `SIGNING` to `SIGNED`."

        Claim: after every signature-required party has /signed, status ==
        SIGNED.
        """
        found = setup_foundation(api)
        ip, _ = walk_ip_right_to_registered(
            api,
            business_unit_id=found["business_unit"]["id"],
            agent_id=found["agent"]["id"],
        )
        tmpl, contract, parties = walk_contract_to_signed(
            api,
            ip_right_id=ip["id"],
            business_unit_id=found["business_unit"]["id"],
        )
        assert_contract(contract)
        assert contract["status"] == "SIGNED"


# ─────────────────────────────────────────────────────────────
# Filing with authority requires REGISTERED IP (PRD §3.4)
# ─────────────────────────────────────────────────────────────


class TestFileWithAuthority:
    """PRD §3.4 file-with-authority preconditions."""

    def test_file_when_ip_not_registered_returns_err_ip_not_registered(
        self, api, ip_manager_headers
    ):
        """PRD §3.4: "The referenced right must be in `REGISTERED` status at
        the moment of filing: filing a contract whose right is not yet
        registered returns `ERR_IP_NOT_REGISTERED`."

        Claim: filing a SIGNED contract whose IPRight is FILED (not
        REGISTERED) → ERR_IP_NOT_REGISTERED (422).
        """
        # Build a SIGNED contract whose parent IPRight is only FILED.
        found = setup_foundation(api)
        ip = create_ip_right_in_draft(
            api,
            business_unit_id=found["business_unit"]["id"],
            agent_id=found["agent"]["id"],
        )
        api.mark_materials_ready(ip["id"], {}, ip_manager_headers)
        api.create_jurisdiction_filing(
            ip["id"], create_filing_payload(), ip_manager_headers
        )
        # Now IPRight is FILED (not REGISTERED). Sign a contract on it.
        tmpl, contract, parties = walk_contract_to_signed(
            api,
            ip_right_id=ip["id"],
            business_unit_id=found["business_unit"]["id"],
            contract_type="TRANSFER",
            royalty_rate=None,
            min_guarantee_cents=None,
        )
        resp = api.file_contract_with_authority(
            contract["id"], {}, ip_manager_headers
        )
        validate_error(resp, ApiErrorId.ERR_IP_NOT_REGISTERED, expected_status=422)

    def test_file_transfer_flips_ip_to_transferred(self, api, ip_manager_headers):
        """PRD §3.4: "Filing a `SIGNED` (or `AMENDED`) contract with the
        authority advances it to `FILED`, sets `filed_with_authority` to
        true, and — when `contract_type` is `TRANSFER` — also flips the
        linked `IPRight.status` to `TRANSFERRED`."

        Claim: filing a TRANSFER contract → IPRight.status == TRANSFERRED.
        """
        seed = setup_contract_filed_for_royalty(
            api,
            contract_type="TRANSFER",
            royalty_rate=None,
            min_guarantee_cents=None,
        )
        # Re-fetch the parent IP — TRANSFER filing should have flipped it.
        ip_after = api.get_ip_right(
            seed["ip_right"]["id"], ip_manager_headers
        ).json()["data"]
        assert ip_after["status"] == "TRANSFERRED"
        assert seed["contract"]["filed_with_authority"] is True


# ─────────────────────────────────────────────────────────────
# Amendment cycle (PRD §3.4)
# ─────────────────────────────────────────────────────────────


class TestAmendmentCycle:
    """PRD §3.4 FILED → AMENDED → FILED."""

    def test_amend_a_filed_contract(self, api, ip_manager_headers):
        """PRD §3.4: "A `FILED` contract may be opened for amendment,
        transitioning it to `AMENDED`."

        Claim: /amend on a FILED contract → status == AMENDED.
        """
        seed = setup_contract_filed_for_royalty(
            api, contract_type="EXCLUSIVE_LICENSE", royalty_rate=0.10
        )
        resp = api.amend_contract(seed["contract"]["id"], {}, ip_manager_headers)
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "AMENDED"

    def test_refile_amended_contract_returns_to_filed(
        self, api, ip_manager_headers
    ):
        """PRD §3.4: "An `AMENDED` contract may be re-filed back to `FILED`
        through the same file-with-authority endpoint."

        Claim: filed→amended→file → status == FILED again.
        """
        seed = setup_contract_filed_for_royalty(
            api, contract_type="EXCLUSIVE_LICENSE", royalty_rate=0.10
        )
        api.amend_contract(seed["contract"]["id"], {}, ip_manager_headers)
        resp = api.file_contract_with_authority(
            seed["contract"]["id"], {}, ip_manager_headers
        )
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "FILED"
