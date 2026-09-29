"""Where every machine starts, and the doors that never open again.

Eight state machines are checked on the create responses that mint them, and
then the refusals: a suspended contract that no request can revive or reuse, a
terminal cross-reference, a letter still at `NOT_ISSUED`, a rejected dossier,
and the evidence gate a contract cannot activate without.
"""

import pytest

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_CLINICAL_REVIEW_NOT_ENDORSED,
    ERR_CONTRACT_NOT_ACTIVE,
    ERR_INVALID_LOP_STATE,
    ERR_INVALID_REVIEW_STATE,
    ERR_XREF_NOT_PROPOSED,
)
from test_helpers.constants import FLAT_TIER_LADDER, HOLDBACK_FLAT, TIER_0, TWO_RUNG_TIER_LADDER
from test_helpers.fixtures import (
    activate_contract,
    countersign_commitment,
    create_active_contract,
    create_commitment,
    create_contract,
    create_cross_reference,
    create_distribution,
    create_evidence_review,
    create_item,
    create_member,
    open_measurement,
    read_commitment,
    read_contract,
    read_evidence_review,
    set_clock,
)
from test_helpers.test_users import (
    CLINICAL_REVIEWER_1,
    CLINICAL_REVIEWER_2,
    CONTRACT_MANAGER_1,
    clinical_reviewer_2_headers,
    clinical_reviewer_headers,
    compliance_analyst_headers,
    contract_manager_2_headers,
    contract_manager_headers,
    distributor_agent_headers,
    make_member_materials_manager_headers,
)


@pytest.fixture
def every_machine_at_birth(api):
    """One create call for each of the eight state machines, in dependency order."""
    set_clock(api)
    member = create_member(api, member_code="M-INI")
    contract = create_contract(
        api,
        contract_code="C-INI",
        requires_clinical_review=False,
        tiers=[dict(row) for row in TWO_RUNG_TIER_LADDER],
        holdback_tiers=[dict(row) for row in HOLDBACK_FLAT],
    )
    review = create_evidence_review(
        api, contract["id"], 8.00, 7.00, 6.00, "category conversion dossier"
    )
    activate_contract(api, contract["id"])
    item = create_item(api, contract["id"])
    commitment = create_commitment(api, member["id"], contract["id"])
    xref = create_cross_reference(api, member["id"], item["id"])
    activation = validate_success(
        api.create_price_activation(
            f.price_activation_payload(
                commitment["id"],
                item["id"],
                effective_from="2026-08-01",
                effective_to="2026-08-31",
            ),
            headers=contract_manager_headers(),
        ),
        201,
    )
    statement = validate_success(
        api.create_distributor_file(
            f.distributor_file_payload(
                member["id"],
                contract["id"],
                [f.purchase_line_row("MI-1", 4, 1000, "2026-08-05")],
            ),
            headers=distributor_agent_headers(),
        ),
        201,
    )
    distribution = create_distribution(api, contract["id"])
    countersign_commitment(api, commitment["id"], member["id"])
    measurement = open_measurement(api, commitment["id"])
    return {
        "member": member,
        "contract": contract,
        "review": review,
        "item": item,
        "commitment": commitment,
        "xref": xref,
        "activation": activation,
        "statement": statement,
        "distribution": distribution,
        "measurement": measurement,
    }


@pytest.fixture
def suspended_contract(api):
    """C-SUS suspended by a ComplianceAnalyst, with one item and one elected member."""
    set_clock(api)
    contract = create_active_contract(
        api,
        contract_code="C-SUS",
        requires_clinical_review=False,
        tiers=[dict(row) for row in FLAT_TIER_LADDER],
        holdback_tiers=[dict(row) for row in HOLDBACK_FLAT],
    )
    item = create_item(api, contract["id"])
    member = create_member(api, member_code="M-SUS")
    commitment = create_commitment(api, member["id"], contract["id"])
    suspended = validate_success(
        api.suspend_contract(
            contract["id"],
            f.reason_payload("supplier recall"),
            headers=compliance_analyst_headers(),
        ),
        200,
    )
    return {
        "contract": suspended,
        "item": item,
        "member": member,
        "commitment": commitment,
    }


def _proposed_mapping(api, member_item_number="MI-1", match_type="EXACT", conversion_factor=1.0):
    contract = create_active_contract(
        api,
        contract_code="C-XRF",
        requires_clinical_review=False,
        tiers=[dict(row) for row in FLAT_TIER_LADDER],
        holdback_tiers=[dict(row) for row in HOLDBACK_FLAT],
    )
    item = create_item(api, contract["id"])
    member = create_member(api, member_code="M-XRF")
    xref = create_cross_reference(
        api,
        member["id"],
        item["id"],
        member_item_number=member_item_number,
        match_type=match_type,
        conversion_factor=conversion_factor,
    )
    return {"contract": contract, "item": item, "member": member, "xref": xref}


@pytest.fixture
def exact_proposal(api):
    """A PROPOSED EXACT mapping, one unit for one unit."""
    set_clock(api)
    return _proposed_mapping(api)


@pytest.fixture
def manual_proposal(api):
    """A PROPOSED MANUAL mapping claiming two contract units per member unit."""
    set_clock(api)
    return _proposed_mapping(api, match_type="MANUAL", conversion_factor=2.0)


@pytest.fixture
def rejected_dossier(api):
    """A 7.15 dossier submitted by CR-1 and rejected by CR-2 on a DRAFT contract."""
    set_clock(api)
    contract = create_contract(
        api,
        contract_code="C-RVW",
        requires_clinical_review=True,
        tiers=[dict(row) for row in FLAT_TIER_LADDER],
        holdback_tiers=[dict(row) for row in HOLDBACK_FLAT],
    )
    review = create_evidence_review(
        api, contract["id"], 8.00, 7.00, 6.00, "category conversion dossier"
    )
    rejected = validate_success(
        api.reject_review(
            review["id"],
            f.reason_payload("supply resilience insufficient"),
            headers=clinical_reviewer_2_headers(),
        ),
        200,
    )
    return {"contract": contract, "review": rejected}


@pytest.fixture
def gated_draft_contract(api):
    """A DRAFT contract whose `requires_clinical_review` was left to default."""
    set_clock(api)
    payload = f.omit(
        f.contract_payload(
            contract_code="C-ACT",
            tiers=[dict(row) for row in FLAT_TIER_LADDER],
            holdback_tiers=[dict(row) for row in HOLDBACK_FLAT],
        ),
        "requires_clinical_review",
    )
    contract = validate_success(
        api.create_contract(payload, headers=contract_manager_headers()), 201
    )
    return contract


class TestEveryMachineStartsWhereItIsDeclaredTo:
    """Eight lifecycles, each read off the response that created its row."""

    def test_a_contract_and_a_dossier_are_born_in_their_own_first_states(
        self, api, every_machine_at_birth
    ):
        """PRD §3.1: "Every new contract is born in `DRAFT` status with `evidence_endorsed`
        false and `active_commitment_count` zero."
        PRD §3.2: "The dossier is created in `UNDER_REVIEW` status with `revision_round` at
        zero, and its `submitted_by_user_id` is set to the submitting reviewer's
        `X-User-ID`."

        Design: Corner/state_machines/entity_initial_states_on_create_across_all_eight_machines
        """
        contract = every_machine_at_birth["contract"]
        review = every_machine_at_birth["review"]

        assert contract["status"] == "DRAFT"
        assert contract["evidence_endorsed"] is False
        assert contract["active_commitment_count"] == 0
        assert review["status"] == "UNDER_REVIEW"
        assert review["revision_round"] == 0
        assert review["submitted_by_user_id"] == CLINICAL_REVIEWER_1

    def test_a_commitment_starts_on_both_of_its_dimensions_at_once(
        self, api, every_machine_at_birth
    ):
        """PRD §3.4: "`election_status` is the commercial lifecycle and runs `ELECTED`,
        `ACTIVE`, `REQUAL_REVIEW`, `TERMINATED`, with a cycle back and forth between
        `ACTIVE` and `REQUAL_REVIEW`."
        PRD §3.4: "`lop_status` is the letter-of-participation document lifecycle and runs
        `NOT_ISSUED`, `ISSUED`, `SIGNED`, `COUNTERSIGNED`, `VOID`, with a cycle from
        `ISSUED` or `SIGNED` out to `VOID` and back to `ISSUED`."
        PRD §3.4: "A newly elected commitment is born with `election_status` `ELECTED`,
        `lop_status` `NOT_ISSUED`, `signer_name` null, `current_tier_code` null,
        `requalification_round` zero, `last_final_compliance_pct` null, all three
        year-to-date ledgers — `ytd_on_contract_spend_cents`,
        `ytd_total_category_spend_cents` and `ytd_measured_volume_units` — at zero,
        `ytd_leakage_pct` at 0.00, and `leakage_flag` false."

        Design: Corner/state_machines/entity_initial_states_on_create_across_all_eight_machines
        """
        commitment = every_machine_at_birth["commitment"]

        assert commitment["election_status"] == "ELECTED"
        assert commitment["lop_status"] == "NOT_ISSUED"
        assert commitment["elected_tier_code"] == TIER_0
        assert commitment["current_tier_code"] is None
        assert commitment["signer_name"] is None
        assert commitment["requalification_round"] == 0
        assert commitment["leakage_flag"] is False

    def test_the_mapping_the_price_and_the_statement_each_open_at_their_own_door(
        self, api, every_machine_at_birth
    ):
        """PRD §3.5: "The mapping is created in `PROPOSED` status."
        PRD §3.6: "An accepted request creates the activation in `DRAFT` status with
        `origin` `REQUEST`, `endorsed_by_user_id`, `approved_by_user_id`, `deny_note`,
        `superseded_by_activation_id` and `replaces_activation_id` all null."
        PRD §3.7: "An accepted submission creates the file in `RECEIVED` status and turns
        each entry of `lines` into exactly one **purchase line**, each carrying the file's
        identifier as `distributor_file_id`, the submitted `member_item_number`,
        `quantity_units`, `unit_price_paid_cents` and `purchase_date`, an
        `extended_cost_cents` computed immediately as `quantity_units` multiplied by
        `unit_price_paid_cents`, a `classification` of `UNCLASSIFIED`, a `reject_reason` of
        `NONE`, `contract_units` of 0, and `matched_vendor_item_number` null."

        Design: Corner/state_machines/entity_initial_states_on_create_across_all_eight_machines
        """
        setup = every_machine_at_birth

        assert setup["xref"]["status"] == "PROPOSED"
        assert setup["activation"]["status"] == "DRAFT"
        assert setup["activation"]["origin"] == "REQUEST"
        assert setup["activation"]["endorsed_by_user_id"] is None
        assert setup["activation"]["approved_by_user_id"] is None
        assert setup["statement"]["status"] == "RECEIVED"
        assert setup["statement"]["line_count"] == 1

    def test_the_settlement_and_the_measurement_start_with_nothing_computed(
        self, api, every_machine_at_birth
    ):
        """PRD §3.9: "The new row is created in `ACCRUED` status with `collected_fee_cents`
        at 0, `basis` null, `holdback_bps_applied`, `holdback_cents`, `gross_pool_cents`,
        `net_pool_cents`, `member_pool_cents`, `member_share_total_cents`,
        `undistributed_cents` and `gpo_retained_cents` all at 0, `member_shares` an empty
        array, and `reverse_note` null."
        PRD §3.8: "The new row is created in `DRAFT` with every money and volume field at
        0, `compliance_pct` at 0.00, `preliminary_compliance_pct` null,
        `qualified_tier_code` null, `basis_empty` false, and `computed_variant` null; the
        parent commitment's `version` increments by one."

        Design: Corner/state_machines/entity_initial_states_on_create_across_all_eight_machines
        """
        distribution = every_machine_at_birth["distribution"]
        measurement = every_machine_at_birth["measurement"]

        assert distribution["status"] == "ACCRUED"
        assert distribution["basis"] is None
        assert distribution["collected_fee_cents"] == 0
        assert distribution["member_shares"] == []
        assert measurement["status"] == "DRAFT"
        assert measurement["computed_variant"] is None
        assert measurement["preliminary_compliance_pct"] is None
        assert measurement["qualified_tier_code"] is None
        assert measurement["basis_empty"] is False


class TestSuspendedIsTheEndOfTheLine:
    """No reinstatement, and nothing new may be hung off the suspended contract."""

    def test_neither_a_second_activation_nor_a_second_suspend_is_available(
        self, api, suspended_contract
    ):
        """PRD §3.1: "A `ComplianceAnalyst` — not the contract's own manager — may suspend
        an `ACTIVE` contract, optionally recording a `reason`, moving `status` to
        `SUSPENDED` and incrementing `version` by one."
        PRD §3.1: "`SUSPENDED` is **terminal**: no reinstatement operation exists anywhere
        in this API."
        PRD §2.4: "Ten of the eleven resource types — contracts, contract items, members,
        clinical evidence reviews, commitments, item cross-references, price activations,
        distributor files, compliance measurements and administrative fee distributions —
        additionally carry `updated_at`, an ISO 8601 UTC timestamp refreshed on every
        mutation, and `version`, an integer that starts at 1 on creation and increments by
        one on every accepted mutation of that row, including mutations the server performs
        on its own initiative as part of a cascade."

        Design: Corner/state_machines/suspended_contract_cannot_be_reactivated_or_reused
        """
        contract = suspended_contract["contract"]
        assert contract["status"] == "SUSPENDED"

        validate_error(
            api.activate_contract(contract["id"], {}, headers=contract_manager_headers()),
            ERR_CONTRACT_NOT_ACTIVE,
            409,
        )
        validate_error(
            api.suspend_contract(
                contract["id"],
                f.reason_payload("again"),
                headers=compliance_analyst_headers(),
            ),
            ERR_CONTRACT_NOT_ACTIVE,
            409,
        )

        after = read_contract(api, contract["id"])
        assert after["status"] == "SUSPENDED"
        assert after["version"] == contract["version"]

    def test_the_suspended_contract_takes_no_new_election_statement_or_price(
        self, api, suspended_contract
    ):
        """PRD §3.1: "While a contract is suspended, no new commitment may be elected on
        it, no new distributor file may be received against it, and no new price activation
        may be created or activated for it — but activations that already reached `ACTIVE`
        keep pricing purchases, because the members who bought under them bought in good
        faith."
        PRD §3.1: "Moving a contract from `DRAFT` to `ACTIVE` is what opens it for
        business: commitment elections, cross-reference proposals, price activations,
        distributor file receipts and fee accruals all require an `ACTIVE` contract."

        Design: Corner/state_machines/suspended_contract_cannot_be_reactivated_or_reused
        """
        setup = suspended_contract
        contract = setup["contract"]
        member_id = setup["member"]["id"]

        validate_error(
            api.create_commitment(
                f.commitment_payload(member_id, contract["id"], effective_from="2026-08-02"),
                headers=make_member_materials_manager_headers(member_id),
            ),
            ERR_CONTRACT_NOT_ACTIVE,
            409,
        )
        validate_error(
            api.create_distributor_file(
                f.distributor_file_payload(
                    member_id,
                    contract["id"],
                    [f.purchase_line_row("MI-1", 4, 1000, "2026-08-05")],
                ),
                headers=distributor_agent_headers(),
            ),
            ERR_CONTRACT_NOT_ACTIVE,
            409,
        )
        validate_error(
            api.create_price_activation(
                f.price_activation_payload(
                    setup["commitment"]["id"],
                    setup["item"]["id"],
                    effective_from="2026-08-01",
                    effective_to="2026-08-31",
                ),
                headers=contract_manager_headers(),
            ),
            ERR_CONTRACT_NOT_ACTIVE,
            409,
        )

        assert read_contract(api, contract["id"])["version"] == contract["version"]
        rows, meta = validate_paginated(
            api.list_commitments(
                f.page(10, 0, contract_id=contract["id"]), headers=compliance_analyst_headers()
            )
        )
        assert meta["total_count"] == 1
        assert len(rows) == 1


class TestApprovingTheSameMappingTwice:
    """The second approve is a refusal, not a quiet no-op."""

    def test_the_second_approve_is_refused_and_leaves_the_first_approver_in_place(
        self, api, exact_proposal
    ):
        """PRD §3.5: "Approving it drives `PROPOSED → APPROVED`, records
        `approved_by_user_id` as the approver's `X-User-ID`, and increments the mapping's
        `version` by one; the two-sided uniqueness check is **re-evaluated at approval
        time**, so a second proposal that was legal when it was raised is refused with
        `ERR_DUPLICATE_XREF` if a sibling proposal reached `APPROVED` first."
        PRD §3.5: "Both `APPROVED` and `REJECTED` are terminal, and either operation
        attempted on a mapping that is no longer `PROPOSED` returns
        `ERR_XREF_NOT_PROPOSED`."

        Design: Corner/state_machines/xref_approve_twice_is_rejected_as_not_proposed
        """
        xref = exact_proposal["xref"]

        approved = validate_success(
            api.approve_cross_reference(xref["id"], {}, headers=contract_manager_headers()),
            200,
        )
        assert approved["status"] == "APPROVED"
        assert approved["approved_by_user_id"] == CONTRACT_MANAGER_1

        validate_error(
            api.approve_cross_reference(xref["id"], {}, headers=contract_manager_2_headers()),
            ERR_XREF_NOT_PROPOSED,
            409,
        )

        after = validate_success(
            api.get_cross_reference(xref["id"], headers=contract_manager_headers()), 200
        )
        assert after["status"] == "APPROVED"
        assert after["approved_by_user_id"] == CONTRACT_MANAGER_1
        assert after["version"] == approved["version"]


class TestRejectingAMapping:
    """REJECTED keeps the note, keeps `approved_by_user_id` null, and keeps the door shut."""

    def test_the_rejection_records_its_note_and_names_no_approver(self, api, manual_proposal):
        """PRD §3.5: "Rejecting drives `PROPOSED → REJECTED`, stores the optional `reason`
        as `reject_note` — null when the reason is omitted — and increments `version` by
        one."

        Design: Corner/state_machines/xref_reject_records_note_and_later_transitions_are_rejected
        """
        xref = manual_proposal["xref"]
        assert xref["status"] == "PROPOSED"

        rejected = validate_success(
            api.reject_cross_reference(
                xref["id"],
                f.reason_payload("conversion factor unproven"),
                headers=contract_manager_headers(),
            ),
            200,
        )

        assert rejected["status"] == "REJECTED"
        assert rejected["reject_note"] == "conversion factor unproven"
        assert rejected["approved_by_user_id"] is None
        assert rejected["version"] == xref["version"] + 1

    def test_a_rejected_mapping_can_never_be_approved_afterwards(self, api, manual_proposal):
        """PRD §3.5: "Both `APPROVED` and `REJECTED` are terminal, and either operation
        attempted on a mapping that is no longer `PROPOSED` returns
        `ERR_XREF_NOT_PROPOSED`."
        PRD §3.5: "Only an `APPROVED` cross-reference has effect."

        Design: Corner/state_machines/xref_reject_records_note_and_later_transitions_are_rejected
        """
        xref = manual_proposal["xref"]
        validate_success(
            api.reject_cross_reference(
                xref["id"],
                f.reason_payload("conversion factor unproven"),
                headers=contract_manager_headers(),
            ),
            200,
        )

        validate_error(
            api.approve_cross_reference(xref["id"], {}, headers=contract_manager_headers()),
            ERR_XREF_NOT_PROPOSED,
            409,
        )

        after = validate_success(
            api.get_cross_reference(xref["id"], headers=contract_manager_headers()), 200
        )
        assert after["status"] == "REJECTED"
        assert after["approved_by_user_id"] is None


class TestALetterThatWasNeverIssued:
    """From `NOT_ISSUED` only issuance exists, and the election dimension does not care."""

    def test_countersigning_signing_and_voiding_are_all_refused_before_issuance(
        self, api, elected_commitment
    ):
        """PRD §3.4: "A `ContractManager` finally countersigns it, which requires
        `lop_status` to be `SIGNED` — anything else returns `ERR_INVALID_LOP_STATE` —
        requires `election_status` to be `ELECTED`, and requires the contract to still be
        `ACTIVE`, else `ERR_CONTRACT_NOT_ACTIVE`."
        PRD §3.4: "The member's own `MemberMaterialsManager` then signs it, supplying
        `signer_name` in the request, which advances `lop_status` from `ISSUED` to `SIGNED`
        and stores that name; a manager whose `X-User-ID` is not the commitment's
        `member_id` is refused with `ERR_MEMBER_SCOPE_VIOLATION`."
        PRD §3.4: "Voiding is available from `ISSUED` and from `SIGNED`, optionally
        recording a `reason`; it sets `lop_status` to `VOID`, resets `signer_name` to null,
        and leaves `election_status` completely untouched."
        PRD §2.9: "**Path resource state** — the path resource is in a state from which the
        requested transition exists. This rung covers all eight state dimensions and returns
        whichever identifier matches: `ERR_INVALID_ACTIVATION_STATE`,
        `ERR_INVALID_FILE_STATE`, `ERR_INVALID_MEASUREMENT_STATE`,
        `ERR_INVALID_DISTRIBUTION_STATE`, `ERR_INVALID_REVIEW_STATE`,
        `ERR_XREF_NOT_PROPOSED`, `ERR_COMMITMENT_NOT_ACTIVE`, `ERR_INVALID_LOP_STATE`, or
        `ERR_COMMITMENT_NOT_ELECTED` — all with HTTP 409."

        Design: Corner/state_machines/lop_countersign_from_not_issued_is_rejected
        """
        setup = elected_commitment
        commitment_id = setup["commitment"]["id"]
        member_headers = make_member_materials_manager_headers(setup["member"]["id"])
        assert setup["commitment"]["lop_status"] == "NOT_ISSUED"

        validate_error(
            api.countersign_lop(commitment_id, {}, headers=contract_manager_headers()),
            ERR_INVALID_LOP_STATE,
            409,
        )
        validate_error(
            api.sign_lop(
                commitment_id, f.signer_payload("Dana Whitfield"), headers=member_headers
            ),
            ERR_INVALID_LOP_STATE,
            409,
        )
        validate_error(
            api.void_lop(
                commitment_id,
                f.reason_payload("nothing to void"),
                headers=contract_manager_headers(),
            ),
            ERR_INVALID_LOP_STATE,
            409,
        )

    def test_no_failed_letter_transition_leaks_into_the_election_dimension(
        self, api, elected_commitment
    ):
        """PRD §3.4: "The two dimensions move independently, with exactly one point of
        coupling: countersigning the letter is the same request that activates the
        election."
        PRD §3.4: "No other letter transition touches `election_status`, and no election
        transition touches `lop_status`."

        Design: Corner/state_machines/lop_countersign_from_not_issued_is_rejected
        """
        setup = elected_commitment
        commitment_id = setup["commitment"]["id"]
        validate_error(
            api.countersign_lop(commitment_id, {}, headers=contract_manager_headers()),
            ERR_INVALID_LOP_STATE,
            409,
        )

        after = read_commitment(api, commitment_id)

        assert after["lop_status"] == "NOT_ISSUED"
        assert after["signer_name"] is None
        assert after["election_status"] == "ELECTED"
        assert after["current_tier_code"] is None


class TestARejectedDossierIsTerminal:
    """No endorsement, no revision request and no resubmission after a rejection."""

    def test_the_rejection_is_recorded_against_the_weighted_score_it_carried(
        self, api, rejected_dossier
    ):
        """PRD §3.2: "Rejection sets `status` to `REJECTED` and, exactly as endorsement
        does, recomputes the parent contract's `evidence_endorsed` and increments that
        contract's `version` by one."
        PRD §3.2: "Worked through: scores of 8.00, 7.00 and 6.00 give 3.20 plus 2.45 plus
        1.50, a weighted score of 7.15; scores of 6.50, 7.00 and 6.00 give 2.60 plus 2.45
        plus 1.50, a weighted score of 6.55; and scores of 7.00, 7.00 and 7.02 give an
        unrounded 7.0050 that rounds half up to 7.01."

        Design: Corner/state_machines/review_endorse_from_rejected_is_rejected
        """
        review = rejected_dossier["review"]

        assert review["status"] == "REJECTED"
        a.assert_score(review["weighted_score"], 7.15)
        assert review["revision_round"] == 0
        assert review["endorsed_by_user_id"] is None
        assert read_contract(api, rejected_dossier["contract"]["id"])["evidence_endorsed"] is False

    def test_endorse_request_revision_and_resubmit_are_all_refused(self, api, rejected_dossier):
        """PRD §3.2: "Both `ENDORSED` and `REJECTED` are terminal: neither can be revised,
        revisited, or cycled back into review."
        PRD §3.2: "Attempting any of these transitions from a status where it does not exist
        returns `ERR_INVALID_REVIEW_STATE`."
        PRD §3.2: "The dossier must be `UNDER_REVIEW`, so `UNDER_REVIEW → ENDORSED` is the
        only endorsement path."

        Design: Corner/state_machines/review_endorse_from_rejected_is_rejected
        """
        review_id = rejected_dossier["review"]["id"]

        validate_error(
            api.endorse_review(review_id, {}, headers=clinical_reviewer_2_headers()),
            ERR_INVALID_REVIEW_STATE,
            409,
        )
        validate_error(
            api.request_review_revision(
                review_id,
                f.reason_payload("reconsider"),
                headers=clinical_reviewer_2_headers(),
            ),
            ERR_INVALID_REVIEW_STATE,
            409,
        )
        validate_error(
            api.resubmit_review(
                review_id,
                f.resubmit_payload(9.00, 9.00, 9.00),
                headers=clinical_reviewer_headers(),
            ),
            ERR_INVALID_REVIEW_STATE,
            409,
        )

        after = read_evidence_review(api, review_id)
        assert after["status"] == "REJECTED"
        assert after["revision_round"] == 0
        a.assert_score(after["weighted_score"], 7.15)
        assert after["endorsed_by_user_id"] is None


class TestTheConversionGateOnContractActivation:
    """`requires_clinical_review` demands an ENDORSED CONVERT dossier, not merely a CONVERT one."""

    def test_activation_is_refused_while_no_dossier_exists_at_all(
        self, api, gated_draft_contract
    ):
        """PRD §3.1: "Three optional switches round out the header:
        `requires_clinical_review`, a boolean defaulting to true; `share_basis`, an
        enumeration of `ACCRUAL` or `COLLECTED` defaulting to `COLLECTED`; and
        `leakage_alert_threshold_pct`, a percentage between 0.00 and 100.00 carrying two
        decimal places and defaulting to 15.00."
        PRD §3.1: "The transition is available only from `DRAFT`, and when
        `requires_clinical_review` is true it additionally demands that `evidence_endorsed`
        be true and that at least one evidence review naming this contract be in `ENDORSED`
        status with a `conversion_recommendation` of `CONVERT`; failing that, the attempt
        returns `ERR_CLINICAL_REVIEW_NOT_ENDORSED`."

        Design: Corner/state_machines/contract_activate_requires_endorsed_convert_review
        """
        assert gated_draft_contract["requires_clinical_review"] is True
        assert gated_draft_contract["evidence_endorsed"] is False

        validate_error(
            api.activate_contract(
                gated_draft_contract["id"], {}, headers=contract_manager_headers()
            ),
            ERR_CLINICAL_REVIEW_NOT_ENDORSED,
            409,
        )

        assert read_contract(api, gated_draft_contract["id"])["status"] == "DRAFT"

    def test_a_convert_recommendation_that_is_not_yet_endorsed_does_not_unlock_it(
        self, api, gated_draft_contract
    ):
        """PRD §3.2: "From the weighted score the server derives
        `conversion_recommendation`: it is `CONVERT` when the weighted score is at least
        7.00 — the threshold is **inclusive**, so a weighted score of exactly 7.00
        recommends conversion — and `DO_NOT_CONVERT` otherwise."
        PRD §3.1: "The transition is available only from `DRAFT`, and when
        `requires_clinical_review` is true it additionally demands that `evidence_endorsed`
        be true and that at least one evidence review naming this contract be in `ENDORSED`
        status with a `conversion_recommendation` of `CONVERT`; failing that, the attempt
        returns `ERR_CLINICAL_REVIEW_NOT_ENDORSED`."

        Design: Corner/state_machines/contract_activate_requires_endorsed_convert_review
        """
        review = create_evidence_review(api, gated_draft_contract["id"], 8.00, 7.00, 6.00)
        assert review["status"] == "UNDER_REVIEW"
        assert review["conversion_recommendation"] == "CONVERT"

        validate_error(
            api.activate_contract(
                gated_draft_contract["id"], {}, headers=contract_manager_headers()
            ),
            ERR_CLINICAL_REVIEW_NOT_ENDORSED,
            409,
        )

        assert read_contract(api, gated_draft_contract["id"])["status"] == "DRAFT"

    def test_the_same_call_succeeds_once_the_dossier_is_endorsed(self, api, gated_draft_contract):
        """PRD §3.2: "An accepted endorsement sets `status` to `ENDORSED`, records
        `endorsed_by_user_id` as the endorsing reviewer's `X-User-ID`, and then reaches
        across to the parent contract: `evidence_endorsed` is recomputed and the contract's
        `version` increments by one."
        PRD §3.1: "Activation sets `status` to `ACTIVE` and increments `version` by one."

        Design: Corner/state_machines/contract_activate_requires_endorsed_convert_review
        """
        review = create_evidence_review(api, gated_draft_contract["id"], 8.00, 7.00, 6.00)
        validate_error(
            api.activate_contract(
                gated_draft_contract["id"], {}, headers=contract_manager_headers()
            ),
            ERR_CLINICAL_REVIEW_NOT_ENDORSED,
            409,
        )

        endorsed = validate_success(
            api.endorse_review(review["id"], {}, headers=clinical_reviewer_2_headers()), 200
        )
        activated = activate_contract(api, gated_draft_contract["id"])

        assert endorsed["status"] == "ENDORSED"
        assert endorsed["endorsed_by_user_id"] == CLINICAL_REVIEWER_2
        assert activated["status"] == "ACTIVE"
