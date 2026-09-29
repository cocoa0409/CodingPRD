"""Operations gated on the state of entities the request never names.

Each case runs the identical call twice: once while a sibling, a two-hop parent,
or a whole family of contracts is in the wrong state, and once after that other
entity has been moved. The first attempt must be refused and must leave the
addressed row untouched; the second must succeed.
"""

from __future__ import annotations

from test_helpers import (
    COMPLIANCE_OFFICER_HEADERS,
    OFFICER_PREPARER_HEADERS,
    OFFICER_SIGNER_HEADERS,
    OFFICER_SIGNER_USER_ID,
    SPONSOR_ADMIN_HEADERS,
    ApiClient,
    ApiErrorId,
    AMENDMENT_EXECUTED,
    AMENDMENT_PROPOSED,
    ATTESTATION_DRAFT,
    ATTESTATION_SUBMITTED,
    CYCLE_CERTIFIED,
    CYCLE_PENDING,
    DATA_RIGHTS_PENDING_AMENDMENT,
    DATA_RIGHTS_SECURED,
    FILE_TYPE_ALLOWED_AMOUNTS,
    FILE_TYPE_IN_NETWORK_RATES,
    GAG_COMPLIANT,
    GAG_NOT_REVIEWED,
    MRF_PUBLISHED,
    MRF_REJECTED,
    PACKAGE_EXPECTED,
    PACKAGE_RECEIVED,
    POSTURE_COMPLIANT,
    RX_ASSEMBLING,
    RX_OPEN,
    SECTION_D2_SPENDING,
    VENDOR_TYPE_BROKER,
    assert_instant_equals,
    factories as f,
    fixtures as fx,
    make_vendor_contact_headers,
    validate_error,
    validate_success,
)

CERTIFY_CLOCK = "2027-07-01T09:00:00Z"
DELIVERY_CLOCK = "2028-04-10T09:00:00Z"
ATTESTATION_CLOCK = "2028-01-15T09:00:00Z"
JUNE = "2027-06"
REVISED_ALLOWED_AMOUNTS_URL = (
    "https://transparency.meridian.example/2027-06/allowed-amounts-r2.json"
)
DELIVERY_FIGURES = {
    "record_count": 1200,
    "plan_paid_cents": 4_200_000,
    "member_paid_cents": 800_000,
    "rebate_cents": 900_000,
}


def _cycle_with_one_rejected_file(api: ApiClient) -> dict:
    """June's in-network file is published; its allowed-amounts sibling is rejected."""
    fx.set_clock(api, CERTIFY_CLOCK)
    setup = fx.activated_plan_year(api, covered_lives=6000)
    plan_year_id = setup["plan_year"]["id"]
    published = fx.published_mrf(
        api,
        plan_year_id,
        FILE_TYPE_IN_NETWORK_RATES,
        JUNE,
        public_url="https://transparency.meridian.example/2027-06/in-network-rates.json",
        row_count=812_004,
    )
    rejected = fx.rejected_mrf(
        api,
        plan_year_id,
        FILE_TYPE_ALLOWED_AMOUNTS,
        JUNE,
        validation_error_count=2,
        public_url="https://transparency.meridian.example/2027-06/allowed-amounts.json",
        row_count=204_119,
    )
    cycle = fx.open_refresh_cycle(
        api,
        plan_year_id,
        period_month=JUNE,
        period_start="2027-06-01",
        period_end="2027-06-30",
    )
    return {
        "plan_year_id": plan_year_id,
        "published": published,
        "rejected": rejected,
        "cycle": cycle,
    }


def _republish(api: ApiClient, mrf_id: str) -> dict:
    """Revise a rejected file and validate it clean."""
    validate_success(
        api.revise_mrf(
            mrf_id,
            f.revise_mrf_payload(
                public_url=REVISED_ALLOWED_AMOUNTS_URL, row_count=204_140
            ),
            SPONSOR_ADMIN_HEADERS,
        )
    )
    return validate_success(
        api.validate_mrf(
            mrf_id, f.validate_mrf_payload(validation_error_count=0), SPONSOR_ADMIN_HEADERS
        )
    )


def _package_awaiting_data_rights(api: ApiClient) -> dict:
    """An EXPECTED package whose vendor contract has an unexecuted amendment."""
    fx.set_clock(api, DELIVERY_CLOCK)
    setup = fx.activated_plan_year(
        api, covered_lives=6000, attestation_deadline_date="2028-12-31"
    )
    plan_year_id = setup["plan_year"]["id"]
    contract_id = setup["tpa_contract"]["id"]
    vendor_id = setup["tpa_vendor"]["id"]
    fx.gag_compliant_contract(api, contract_id)
    submission = fx.open_rx_submission(api, plan_year_id, reference_year=2027)
    package = fx.request_package(
        api,
        submission["id"],
        vendor_id,
        data_section=SECTION_D2_SPENDING,
        expected_record_count=1200,
    )
    amendment = fx.propose_amendment(
        api, contract_id, expires_at="2028-06-30T00:00:00Z"
    )
    return {
        "contract_id": contract_id,
        "vendor_id": vendor_id,
        "submission": submission,
        "package": package,
        "amendment": amendment,
    }


def _draft_with_one_unreviewed_broker(api: ApiClient) -> dict:
    """A submittable-looking draft behind one contract nobody has reviewed."""
    fx.set_clock(api, ATTESTATION_CLOCK)
    setup = fx.activated_plan_year(
        api, covered_lives=6000, attestation_deadline_date="2028-01-31"
    )
    plan_year_id = setup["plan_year"]["id"]
    fx.gag_compliant_contract(api, setup["tpa_contract"]["id"])
    broker = fx.add_contract_for_vendor_type(
        api, plan_year_id, VENDOR_TYPE_BROKER, annual_fee_cents=2_400_000
    )
    draft = fx.attestation_draft(
        api, plan_year_id, preparer_headers=OFFICER_PREPARER_HEADERS,
        contract_terms_doc_count=3,
    )
    return {
        "plan_year_id": plan_year_id,
        "broker_contract_id": broker["contract"]["id"],
        "attestation": draft,
    }


class TestCertificationNeedsBothFileTypesPublished:
    """Both required postings must be live, not merely present."""

    def test_one_published_and_one_rejected_file_blocks_certification(
        self, api: ApiClient
    ) -> None:
        """Half the month's disclosure is not half a certification.

        PRD 3.2: "One of the two present and the other missing is still
        `ERR_MRF_NOT_PUBLISHED`."

        Design: Difficulty/cross_entity_state_dependency/refresh_certify_blocked_until_both_file_types_published
        """
        built = _cycle_with_one_rejected_file(api)
        assert built["published"]["status"] == MRF_PUBLISHED
        assert built["rejected"]["status"] == MRF_REJECTED

        response = api.certify_refresh_cycle(
            built["cycle"]["id"],
            COMPLIANCE_OFFICER_HEADERS,
            f.certify_cycle_payload(
                certification_note="First attempt while allowed-amounts file is rejected."
            ),
        )
        validate_error(response, ApiErrorId.MRF_NOT_PUBLISHED)

        unchanged = validate_success(
            api.get_refresh_cycle(built["cycle"]["id"], COMPLIANCE_OFFICER_HEADERS)
        )
        assert unchanged["status"] == CYCLE_PENDING
        assert unchanged["certified_at"] is None

    def test_republishing_the_second_file_unblocks_the_identical_call(
        self, api: ApiClient
    ) -> None:
        """Nothing about the cycle changes; only its sibling files move.

        PRD 3.2: "Certification requires the cycle to be `PENDING`, the plan year
        to be `ACTIVE` with a posture other than `FROZEN`, and — critically — a
        `PUBLISHED` machine-readable file to exist for that `plan_year_id` and
        that `posting_month` for *each* of the two required `file_type` values."

        Design: Difficulty/cross_entity_state_dependency/refresh_certify_blocked_until_both_file_types_published
        """
        built = _cycle_with_one_rejected_file(api)
        validate_error(
            api.certify_refresh_cycle(
                built["cycle"]["id"], COMPLIANCE_OFFICER_HEADERS, f.certify_cycle_payload()
            ),
            ApiErrorId.MRF_NOT_PUBLISHED,
        )

        republished = _republish(api, built["rejected"]["id"])
        assert republished["status"] == MRF_PUBLISHED
        assert republished["validation_error_count"] == 0
        assert republished["public_url"] == REVISED_ALLOWED_AMOUNTS_URL

        certified = validate_success(
            api.certify_refresh_cycle(
                built["cycle"]["id"],
                COMPLIANCE_OFFICER_HEADERS,
                f.certify_cycle_payload(
                    certification_note="Second attempt after both file types are published."
                ),
            )
        )
        assert certified["status"] == CYCLE_CERTIFIED
        assert certified["on_time"] is True
        assert_instant_equals(certified["certified_at"], CERTIFY_CLOCK)

        plan_year = fx.read_plan_year(api, built["plan_year_id"])
        assert plan_year["deficiency_points"] == 0
        assert plan_year["compliance_posture"] == POSTURE_COMPLIANT


class TestDeliveryNeedsExecutedDataRights:
    """A package's gate lives two hops away, on its vendor's amendment."""

    def test_delivery_is_refused_while_the_amendment_is_only_proposed(
        self, api: ApiClient
    ) -> None:
        """An amendment on the table is not an amendment in force.

        PRD 3.6: "Before the delivery is accepted, the service looks for a
        service provider contract joining the submission's `plan_year_id` to the
        package's `vendor_id` whose `data_rights_status` is `SECURED`; if none
        exists the delivery is refused with `ERR_DATA_RIGHTS_NOT_SECURED`, which
        is the concrete reason a sponsor chases amendments in the first place."

        Design: Difficulty/cross_entity_state_dependency/package_delivery_requires_secured_data_rights_on_contract
        """
        built = _package_awaiting_data_rights(api)
        assert built["amendment"]["status"] == AMENDMENT_PROPOSED
        # Proposing advances the dimension only as far as PENDING_AMENDMENT.
        assert (
            fx.read_contract(api, built["contract_id"])["data_rights_status"]
            == DATA_RIGHTS_PENDING_AMENDMENT
        )

        vendor_headers = make_vendor_contact_headers(built["vendor_id"])
        response = api.deliver_package(
            built["package"]["id"],
            f.deliver_package_payload(**DELIVERY_FIGURES),
            vendor_headers,
        )
        validate_error(response, ApiErrorId.DATA_RIGHTS_NOT_SECURED)

        unchanged = validate_success(
            api.get_vendor_data_package(
                built["package"]["id"], COMPLIANCE_OFFICER_HEADERS
            )
        )
        assert unchanged["status"] == PACKAGE_EXPECTED
        assert unchanged["delivery_round"] == 0
        assert unchanged["record_count"] is None

    def test_executing_the_amendment_admits_the_identical_delivery(
        self, api: ApiClient
    ) -> None:
        """Execution flips the contract, and the contract is what the gate reads.

        PRD 3.5: "A `DATA_RIGHTS` execution advances the contract's data-rights
        dimension `PENDING_AMENDMENT → SECURED` and increments the contract's
        `version` by 1, and from that moment the vendor's prescription-drug data
        deliveries for that plan year are permitted."

        Design: Difficulty/cross_entity_state_dependency/package_delivery_requires_secured_data_rights_on_contract
        """
        built = _package_awaiting_data_rights(api)
        vendor_headers = make_vendor_contact_headers(built["vendor_id"])
        validate_error(
            api.deliver_package(
                built["package"]["id"],
                f.deliver_package_payload(**DELIVERY_FIGURES),
                vendor_headers,
            ),
            ApiErrorId.DATA_RIGHTS_NOT_SECURED,
        )

        executed = validate_success(
            api.execute_amendment(
                built["amendment"]["id"],
                SPONSOR_ADMIN_HEADERS,
                f.execute_amendment_payload(
                    executed_terms_note=(
                        "Data rights granted as requested; cooperation clause added."
                    )
                ),
            )
        )
        assert executed["status"] == AMENDMENT_EXECUTED
        assert (
            fx.read_contract(api, built["contract_id"])["data_rights_status"]
            == DATA_RIGHTS_SECURED
        )

        delivered = validate_success(
            api.deliver_package(
                built["package"]["id"],
                f.deliver_package_payload(**DELIVERY_FIGURES),
                vendor_headers,
            )
        )
        assert delivered["status"] == PACKAGE_RECEIVED
        assert delivered["delivery_round"] == 1
        assert delivered["record_count"] == 1200

    def test_the_first_received_package_moves_the_parent_submission(
        self, api: ApiClient
    ) -> None:
        """The unblocked delivery bubbles up without counting any records yet.

        PRD 3.6: "It also bubbles up: if the parent submission is still `OPEN`,
        the first package to reach `RECEIVED` advances it `OPEN → ASSEMBLING` and
        increments the submission's `version` by 1."

        Design: Difficulty/cross_entity_state_dependency/package_delivery_requires_secured_data_rights_on_contract
        """
        built = _package_awaiting_data_rights(api)
        assert built["submission"]["status"] == RX_OPEN

        validate_success(
            api.execute_amendment(
                built["amendment"]["id"],
                SPONSOR_ADMIN_HEADERS,
                f.execute_amendment_payload(),
            )
        )
        validate_success(
            api.deliver_package(
                built["package"]["id"],
                f.deliver_package_payload(**DELIVERY_FIGURES),
                make_vendor_contact_headers(built["vendor_id"]),
            )
        )

        submission = validate_success(
            api.get_rx_submission(built["submission"]["id"], COMPLIANCE_OFFICER_HEADERS)
        )
        assert submission["status"] == RX_ASSEMBLING
        assert submission["assembled_record_count"] == 0


class TestSubmissionNeedsEveryMaterialContractCleared:
    """One unreviewed material contract is enough to hold the attestation back."""

    def test_an_unreviewed_broker_contract_blocks_submission(
        self, api: ApiClient
    ) -> None:
        """The gate reads the whole roster, not the contracts anyone looked at.

        PRD 3.8: "a single material contract still `NOT_REVIEWED`, `IN_REVIEW`,
        `REMEDIATION_REQUESTED` or `NON_COMPLIANT` is enough to refuse the
        submission with `ERR_GAG_CLAUSES_OUTSTANDING`."

        Design: Difficulty/cross_entity_state_dependency/attestation_submit_requires_every_material_contract_gag_cleared
        """
        built = _draft_with_one_unreviewed_broker(api)
        assert (
            fx.read_contract(api, built["broker_contract_id"])["gag_review_status"]
            == GAG_NOT_REVIEWED
        )
        plan_year = fx.read_plan_year(api, built["plan_year_id"])
        assert plan_year["deficiency_points"] == 0
        assert plan_year["compliance_posture"] == POSTURE_COMPLIANT

        response = api.submit_attestation(
            built["attestation"]["id"],
            f.submit_attestation_payload(
                signature_statement="Submitting before the broker contract review."
            ),
            OFFICER_SIGNER_HEADERS,
        )
        validate_error(response, ApiErrorId.GAG_CLAUSES_OUTSTANDING)

        unchanged = validate_success(
            api.get_attestation(
                built["attestation"]["id"], COMPLIANCE_OFFICER_HEADERS
            )
        )
        assert unchanged["status"] == ATTESTATION_DRAFT
        assert unchanged["submitted_at"] is None

    def test_clearing_the_last_material_contract_admits_the_submission(
        self, api: ApiClient
    ) -> None:
        """Reviewing and clearing the broker contract is the only change made.

        PRD 3.8: "Every service provider contract of the plan year whose
        `contract_type` is `TPA`, `PBM`, `BROKER` or `CONSULTANT` must have a
        `gag_review_status` of exactly `COMPLIANT`; a single material contract
        still `NOT_REVIEWED`, `IN_REVIEW`, `REMEDIATION_REQUESTED` or
        `NON_COMPLIANT` is enough to refuse the submission with
        `ERR_GAG_CLAUSES_OUTSTANDING`."

        Design: Difficulty/cross_entity_state_dependency/attestation_submit_requires_every_material_contract_gag_cleared
        """
        built = _draft_with_one_unreviewed_broker(api)
        validate_error(
            api.submit_attestation(
                built["attestation"]["id"],
                f.submit_attestation_payload(),
                OFFICER_SIGNER_HEADERS,
            ),
            ApiErrorId.GAG_CLAUSES_OUTSTANDING,
        )

        fx.open_gag_review(
            api,
            built["broker_contract_id"],
            clause_inventory_count=12,
            prohibited_clause_count=0,
        )
        cleared = validate_success(
            api.clear_gag(
                built["broker_contract_id"],
                COMPLIANCE_OFFICER_HEADERS,
                f.clear_gag_payload(
                    clearance_note="No cost-or-quality restrictions found."
                ),
            )
        )
        assert cleared["gag_review_status"] == GAG_COMPLIANT

        submitted = validate_success(
            api.submit_attestation(
                built["attestation"]["id"],
                f.submit_attestation_payload(
                    signature_statement=(
                        "Submitting after all material contracts are cleared."
                    )
                ),
                OFFICER_SIGNER_HEADERS,
            )
        )
        assert submitted["status"] == ATTESTATION_SUBMITTED
        assert submitted["submitted_by_user_id"] == OFFICER_SIGNER_USER_ID
        assert_instant_equals(submitted["submitted_at"], ATTESTATION_CLOCK)

        plan_year = fx.read_plan_year(api, built["plan_year_id"])
        assert plan_year["attestation_status"] == ATTESTATION_SUBMITTED
        assert plan_year["deficiency_points"] == 0
