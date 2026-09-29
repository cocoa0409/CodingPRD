"""Validation precedence: which of two simultaneously broken rules is reported.

Every request here breaks exactly two rungs of the precedence ladder at once.
The winner is fixed by rung number, never by category name, and each pair is
proved twice over: once by the error the doubly-invalid request returns, and
once by repairing only the winning rung so the loser finally surfaces.
"""

import pytest

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_ACTIVATION_PERIOD_OVERLAP,
    ERR_CLINICAL_REVIEW_NOT_ENDORSED,
    ERR_COMMITTED_VOLUME_BELOW_TIER,
    ERR_CONTRACT_NOT_ACTIVE,
    ERR_REQUESTED_PRICE_NOT_ALLOWED,
    ERR_XREF_NOT_APPROVED,
)
from test_helpers.constants import TIER_0, TIER_2
from test_helpers.fixtures import (
    activate_contract,
    approve_cross_reference,
    build_priced_setup,
    create_contract,
    create_cross_reference,
    create_evidence_review,
    create_member,
    create_tier_activation,
    read_activation,
    read_contract,
    read_item,
    set_clock,
)
from test_helpers.test_users import (
    clinical_reviewer_2_headers,
    contract_manager_headers,
    make_member_materials_manager_headers,
)


@pytest.fixture
def draft_contract_and_member(api):
    """A contract still in DRAFT whose ladder already declares TIER_2 at 5000 units."""
    set_clock(api)
    contract = create_contract(api)
    member = create_member(api)
    return {"contract": contract, "member": member}


@pytest.fixture
def evidence_flagged_item_setup(api):
    """A DRAFT tier price on an evidence-flagged item, behind an unendorsed dossier.

    The contract's only clinical evidence review scores 7.00 / 7.00 / 7.60, so it
    is eligible for endorsement, but it is still `UNDER_REVIEW`; and the member's
    cross-reference to the item is still `PROPOSED`.
    """
    setup = build_priced_setup(
        api,
        item_overrides={
            "vendor_item_number": "V-9",
            "item_description": "Bioabsorbable interference screw",
            "requires_evidence": True,
        },
        with_xref=False,
        with_activation=False,
    )
    review = create_evidence_review(api, setup["contract"]["id"], 7.00, 7.00, 7.60)
    xref = create_cross_reference(api, setup["member"]["id"], setup["item"]["id"])
    activation = create_tier_activation(
        api, setup["commitment"]["id"], setup["item"]["id"]
    )
    setup.update({"review": review, "xref": xref, "activation": activation})
    return setup


@pytest.fixture
def closed_window_setup(api):
    """An ACTIVE tier price over the closed window [2026-08-01, 2026-09-30]."""
    return build_priced_setup(api, activation_from="2026-08-01", activation_to="2026-09-30")


def _elect(api, member_id, contract_id, elected_tier_code, committed_volume_units):
    payload = f.commitment_payload(
        member_id,
        contract_id,
        elected_tier_code=elected_tier_code,
        committed_volume_units=committed_volume_units,
    )
    return api.create_commitment(
        payload, headers=make_member_materials_manager_headers(member_id)
    )


def _request_activation(api, commitment_id, contract_item_id, **kwargs):
    payload = f.price_activation_payload(commitment_id, contract_item_id, **kwargs)
    return api.create_price_activation(payload, headers=contract_manager_headers())


def _activations_of(api, commitment_id):
    data, _meta = validate_paginated(
        api.list_price_activations(
            {"commitment_id": commitment_id, "limit": 100},
            headers=contract_manager_headers(),
        )
    )
    return data


def _commitments_of(api, member_id):
    data, _meta = validate_paginated(
        api.list_commitments(
            {"member_id": member_id, "limit": 100}, headers=contract_manager_headers()
        )
    )
    return data


class TestContractStateBeatsVolumeFloor:
    """Rung 7 (lifecycle) outranks rung 22 (money)."""

    def test_a_draft_contract_masks_the_committed_volume_floor(
        self, api, draft_contract_and_member
    ):
        """PRD §2.9: "Consider a commitment election that names a contract still in
        `DRAFT` **and** elects a rich tier with a committed volume far below that
        tier's floor."
        PRD §2.9: "The response is `ERR_CONTRACT_NOT_ACTIVE` with HTTP 409, because a
        contract that has not been activated has no binding tier ladder to measure a
        commitment against, so the state check fires first and the fiscal floor is
        never reached."
        PRD §2.9: "**Parent contract state** — the parent contract is in the state the
        operation requires; otherwise `ERR_CONTRACT_NOT_ACTIVE` (409)."

        Design: Difficulty/priority_pair_validation_conflict/contract_state_beats_tier_volume_floor
        """
        contract = draft_contract_and_member["contract"]
        member = draft_contract_and_member["member"]
        assert contract["status"] == "DRAFT"

        validate_error(
            _elect(api, member["id"], contract["id"], TIER_2, 100),
            ERR_CONTRACT_NOT_ACTIVE,
        )

        assert _commitments_of(api, member["id"]) == []
        assert read_contract(api, contract["id"])["active_commitment_count"] == 0

    def test_activating_the_contract_exposes_the_committed_volume_floor(
        self, api, draft_contract_and_member
    ):
        """PRD §2.9: "**Committed volume floor** — a commitment's
        `committed_volume_units` is at least the elected tier's minimum committed
        volume; otherwise `ERR_COMMITTED_VOLUME_BELOW_TIER` (409)."
        PRD §2.9: "Rules are evaluated strictly in ascending order and evaluation stops
        at the first violation, so a later rung's error can never mask an earlier
        rung's error."

        Design: Difficulty/priority_pair_validation_conflict/contract_state_beats_tier_volume_floor
        """
        contract = draft_contract_and_member["contract"]
        member = draft_contract_and_member["member"]

        activate_contract(api, contract["id"])

        validate_error(
            _elect(api, member["id"], contract["id"], TIER_2, 100),
            ERR_COMMITTED_VOLUME_BELOW_TIER,
        )

        assert _commitments_of(api, member["id"]) == []
        assert read_contract(api, contract["id"])["active_commitment_count"] == 0


class TestClinicalSafetyBeatsXrefReferential:
    """Rung 10 (clinical safety) outranks rung 13 (catalog hygiene)."""

    def test_the_unendorsed_dossier_masks_the_unapproved_cross_reference(
        self, api, evidence_flagged_item_setup
    ):
        """PRD §2.9: "Consider activating a `DRAFT` tier price on a catalog item that
        requires clinical evidence, where the contract's only evidence review is still
        `UNDER_REVIEW` **and** the member's cross-reference for that item is still
        `PROPOSED`."
        PRD §2.9: "The response is `ERR_CLINICAL_REVIEW_NOT_ENDORSED` with HTTP 409:
        clinical safety outranks catalog hygiene, because an unproven item must not be
        priced for anybody, and the missing evidence is reported even though the
        cross-reference is also unusable."

        Design: Difficulty/priority_pair_validation_conflict/clinical_safety_beats_xref_referential
        """
        setup = evidence_flagged_item_setup
        assert setup["review"]["status"] == "UNDER_REVIEW"
        assert setup["review"]["conversion_recommendation"] == "CONVERT"
        assert setup["xref"]["status"] == "PROPOSED"

        validate_error(
            api.activate_price_activation(
                setup["activation"]["id"], {}, headers=contract_manager_headers()
            ),
            ERR_CLINICAL_REVIEW_NOT_ENDORSED,
        )

        assert read_activation(api, setup["activation"]["id"])["status"] == "DRAFT"
        assert read_item(api, setup["item"]["id"])["active_activation_count"] == 0

    def test_endorsing_the_dossier_exposes_the_unapproved_cross_reference(
        self, api, evidence_flagged_item_setup
    ):
        """PRD §2.9: "**Referential coherence** — the referenced rows belong together:
        a catalog item named by an activation belongs to the commitment's contract
        (`ERR_ITEM_CONTRACT_MISMATCH`), a member item number named by a
        cross-reference exists in that member's item master
        (`ERR_MEMBER_ITEM_NOT_IN_MASTER`), and a price may only be activated once an
        `APPROVED` cross-reference links the member to the item
        (`ERR_XREF_NOT_APPROVED`); all 409."
        PRD §3.6: "The evidence gate is checked before the cross-reference gate, so an
        unproven item with an unapproved mapping reports the missing evidence."

        Design: Difficulty/priority_pair_validation_conflict/clinical_safety_beats_xref_referential
        """
        setup = evidence_flagged_item_setup

        validate_success(
            api.endorse_review(
                setup["review"]["id"], {}, headers=clinical_reviewer_2_headers()
            ),
            200,
        )

        validate_error(
            api.activate_price_activation(
                setup["activation"]["id"], {}, headers=contract_manager_headers()
            ),
            ERR_XREF_NOT_APPROVED,
        )

        assert read_activation(api, setup["activation"]["id"])["status"] == "DRAFT"

    def test_the_price_activates_only_once_both_gates_are_satisfied(
        self, api, evidence_flagged_item_setup
    ):
        """PRD §3.6: "Activation sets `status` to `ACTIVE`, increments the activation's
        own `version` by one, and recomputes the catalog item's
        `active_activation_count`, incrementing that item's `version` by one."
        PRD §2.4: "`version`, an integer that starts at 1 on creation and increments
        by one on every accepted mutation of that row, including mutations the server
        performs on its own initiative as part of a cascade."

        Design: Difficulty/priority_pair_validation_conflict/clinical_safety_beats_xref_referential
        """
        setup = evidence_flagged_item_setup

        validate_success(
            api.endorse_review(
                setup["review"]["id"], {}, headers=clinical_reviewer_2_headers()
            ),
            200,
        )
        approve_cross_reference(api, setup["xref"]["id"])
        activated = validate_success(
            api.activate_price_activation(
                setup["activation"]["id"], {}, headers=contract_manager_headers()
            ),
            200,
        )

        assert activated["status"] == "ACTIVE"
        item = read_item(api, setup["item"]["id"])
        assert item["active_activation_count"] == 1
        assert item["version"] == 2


class TestTemporalOverlapBeatsPriceShape:
    """Rung 20 (the temporal ladder) outranks rung 21 (a body-shape complaint)."""

    def test_a_shared_endpoint_date_masks_the_forbidden_requested_price(
        self, api, closed_window_setup
    ):
        """PRD §2.9: "Consider creating a `TIER_PRICE` activation that wrongly carries
        a `requested_price_cents` value **and** whose `effective_from` equals the
        `effective_to` of an existing `ACTIVE` tier-price activation for the same
        commitment and catalog item."
        PRD §2.9: "The response is `ERR_ACTIVATION_PERIOD_OVERLAP` with HTTP 409,
        because the temporal ladder is what makes any price meaningful — two prices
        covering the same day cannot be reconciled at all — so the window conflict is
        reported before the body-shape complaint."
        PRD §2.10: "Because both endpoints are included, two activations sharing
        exactly one endpoint date do overlap, which is the opposite of the half-open
        file rule."

        Design: Difficulty/priority_pair_validation_conflict/temporal_overlap_beats_fiscal_price_shape
        """
        setup = closed_window_setup
        assert setup["activation"]["effective_to"] == "2026-09-30"

        validate_error(
            _request_activation(
                api,
                setup["commitment"]["id"],
                setup["item"]["id"],
                requested_price_cents=9000,
                effective_from="2026-09-30",
                effective_to="2026-12-31",
            ),
            ERR_ACTIVATION_PERIOD_OVERLAP,
        )

        assert len(_activations_of(api, setup["commitment"]["id"])) == 1

    def test_moving_the_window_one_day_clear_exposes_the_price_shape_complaint(
        self, api, closed_window_setup
    ):
        """PRD §2.9: "**Price-shape coherence** — `requested_price_cents` is supplied
        for a `LOCAL_EXCEPTION` activation and omitted for a `TIER_PRICE` activation;
        the errors are `ERR_REQUESTED_PRICE_REQUIRED` and
        `ERR_REQUESTED_PRICE_NOT_ALLOWED`, both 409."
        PRD §2.9: "**Activation overlap** — no existing price activation for the same
        commitment, catalog item and activation type, in status `DRAFT`, `ENDORSED`,
        `APPROVED` or `ACTIVE`, has a fully closed window colliding with the new one;
        sharing a single endpoint date is a collision."

        Design: Difficulty/priority_pair_validation_conflict/temporal_overlap_beats_fiscal_price_shape
        """
        setup = closed_window_setup

        validate_error(
            _request_activation(
                api,
                setup["commitment"]["id"],
                setup["item"]["id"],
                requested_price_cents=9000,
                effective_from="2026-10-01",
                effective_to="2026-12-31",
            ),
            ERR_REQUESTED_PRICE_NOT_ALLOWED,
        )

        assert len(_activations_of(api, setup["commitment"]["id"])) == 1

    def test_a_clean_window_with_no_requested_price_is_accepted(
        self, api, closed_window_setup
    ):
        """PRD §3.6: "An accepted request creates the activation in `DRAFT` status with
        `origin` `REQUEST`, `endorsed_by_user_id`, `approved_by_user_id`, `deny_note`,
        `superseded_by_activation_id` and `replaces_activation_id` all null."
        PRD §3.6: "Worked over a `base_price_cents` of 10000 against a ladder whose
        rungs carry 0, 800 and 1500 basis points of discount, the tier prices are
        10000, 9200 and 8500 cents respectively; over a `base_price_cents` of 10010 at
        1500 basis points the exact result is 8508.5 cents, which rounds half up to
        8509."

        Design: Difficulty/priority_pair_validation_conflict/temporal_overlap_beats_fiscal_price_shape
        """
        setup = closed_window_setup

        created = validate_success(
            _request_activation(
                api,
                setup["commitment"]["id"],
                setup["item"]["id"],
                effective_from="2026-10-01",
                effective_to="2026-12-31",
            ),
            201,
        )

        assert created["status"] == "DRAFT"
        assert created["origin"] == "REQUEST"
        assert created["tier_code_at_activation"] == TIER_0
        assert created["computed_price_cents"] == 10000
        assert created["requested_price_cents"] is None
        assert len(_activations_of(api, setup["commitment"]["id"])) == 2
