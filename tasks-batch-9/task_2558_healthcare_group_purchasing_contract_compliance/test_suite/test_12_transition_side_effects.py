"""What one accepted transition writes on the rows around it.

Countersigning a letter moves four fields in one request; terminating an
election supersedes a live price without replacing it; a finalize that earns the
tier the member already had stops after two hops; and an endorse and a reject
both run the same `evidence_endorsed` recompute.
"""

import pytest

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers.constants import (
    FLAT_TIER_LADDER,
    HOLDBACK_FLAT,
    TIER_0,
    TIER_1,
    TWO_RUNG_TIER_LADDER,
)
from test_helpers.fixtures import (
    build_priced_setup,
    create_active_contract,
    create_commitment,
    create_contract,
    create_evidence_review,
    create_member,
    finalize_measurement,
    measure,
    open_measurement,
    open_requalification,
    read_activation,
    read_commitment,
    read_contract,
    read_item,
    read_measurement,
    set_clock,
    terminate_commitment,
)
from test_helpers.test_users import (
    CLINICAL_REVIEWER_2,
    clinical_reviewer_2_headers,
    compliance_analyst_headers,
    contract_manager_headers,
    make_member_materials_manager_headers,
)


@pytest.fixture
def signed_letter_on_the_middle_rung(api):
    """A TIER_1 election whose letter is SIGNED, read alongside its contract row."""
    set_clock(api)
    contract = create_active_contract(
        api,
        contract_code="C-CNT",
        requires_clinical_review=False,
        tiers=[dict(row) for row in TWO_RUNG_TIER_LADDER],
        holdback_tiers=[dict(row) for row in HOLDBACK_FLAT],
    )
    member = create_member(api, member_code="M-CNT")
    commitment = create_commitment(
        api,
        member["id"],
        contract["id"],
        elected_tier_code=TIER_1,
        committed_volume_units=2000,
    )
    validate_success(api.issue_lop(commitment["id"], {}, headers=contract_manager_headers()), 200)
    signed = validate_success(
        api.sign_lop(
            commitment["id"],
            f.signer_payload("Dana Whitfield"),
            headers=make_member_materials_manager_headers(member["id"]),
        ),
        200,
    )
    return {
        "contract": read_contract(api, contract["id"]),
        "member": member,
        "commitment": signed,
    }


@pytest.fixture
def requalification_without_a_single_file(api):
    """A REQUAL_REVIEW commitment measured over a period in which nothing was bought."""
    set_clock(api, "2026-09-01T00:00:00Z")
    setup = build_priced_setup(
        api,
        contract_overrides={
            "contract_code": "C-NOP",
            "tiers": [dict(row) for row in TWO_RUNG_TIER_LADDER],
            "holdback_tiers": [dict(row) for row in HOLDBACK_FLAT],
        },
        pin_clock=False,
    )
    setup["activation_before"] = read_activation(api, setup["activation"]["id"])
    setup["item_before"] = read_item(api, setup["item"]["id"])
    open_requalification(api, setup["commitment"]["id"])
    setup["measurement"] = open_measurement(api, setup["commitment"]["id"])
    return setup


@pytest.fixture
def two_dossiers_on_one_contract(api):
    """A DRAFT contract at version 1 carrying a 7.15 dossier and a 6.55 dossier."""
    set_clock(api)
    contract = create_contract(
        api,
        contract_code="C-XE",
        requires_clinical_review=True,
        tiers=[dict(row) for row in FLAT_TIER_LADDER],
        holdback_tiers=[dict(row) for row in HOLDBACK_FLAT],
    )
    review_a = create_evidence_review(api, contract["id"], 8.00, 7.00, 6.00)
    review_b = create_evidence_review(api, contract["id"], 6.50, 7.00, 6.00)
    return {"contract": contract, "review_a": review_a, "review_b": review_b}


def _activations_of(api, commitment_id, **filters):
    params = dict(filters)
    params["commitment_id"] = commitment_id
    params.setdefault("limit", 10)
    params.setdefault("offset", 0)
    return validate_paginated(
        api.list_price_activations(params, headers=contract_manager_headers())
    )


class TestCountersigningDoesFourThingsAtOnce:
    """One request flips the letter, the election, the tier in force and the parent counter."""

    def test_the_letter_and_the_election_flip_in_the_same_request(
        self, api, signed_letter_on_the_middle_rung
    ):
        """PRD §3.4: "Countersigning is the coupling point and does four things at once."
        PRD §3.4: "It advances `lop_status` from `SIGNED` to `COUNTERSIGNED`."
        PRD §3.4: "In the same request it drives `election_status` from `ELECTED` to
        `ACTIVE`."
        PRD §3.4: "It sets `current_tier_code` to the commitment's `elected_tier_code`,
        which is the first moment the member has a tier actually in force rather than merely
        elected."
        PRD §3.4: "The commitment's own `version` increments by one as well."

        Design: Corner/state_machines/countersign_side_effects_set_current_tier_and_contract_counter
        """
        setup = signed_letter_on_the_middle_rung
        signed = setup["commitment"]
        assert signed["lop_status"] == "SIGNED"
        assert signed["signer_name"] == "Dana Whitfield"
        assert signed["current_tier_code"] is None

        countersigned = validate_success(
            api.countersign_lop(signed["id"], {}, headers=contract_manager_headers()), 200
        )

        assert countersigned["lop_status"] == "COUNTERSIGNED"
        assert countersigned["election_status"] == "ACTIVE"
        assert countersigned["current_tier_code"] == TIER_1
        assert countersigned["elected_tier_code"] == TIER_1
        assert countersigned["version"] == signed["version"] + 1

    def test_the_contract_counter_rises_once_in_that_same_request(
        self, api, signed_letter_on_the_middle_rung
    ):
        """PRD §3.4: "And it recomputes the parent contract's `active_commitment_count` —
        which now genuinely rises, since `ACTIVE` is a counted state — incrementing that
        contract's `version` by one."
        PRD §2.7: "Two discipline rules govern these recomputations."
        PRD §2.7: "First, **every recompute is a mutation of the row it lands on**: it
        refreshes that row's `updated_at` and increments that row's `version` by one, even
        though no client asked for a change to that row."

        Design: Corner/state_machines/countersign_side_effects_set_current_tier_and_contract_counter
        """
        setup = signed_letter_on_the_middle_rung
        before = setup["contract"]
        assert before["active_commitment_count"] == 0

        validate_success(
            api.countersign_lop(
                setup["commitment"]["id"], {}, headers=contract_manager_headers()
            ),
            200,
        )

        after = read_contract(api, before["id"])
        assert after["active_commitment_count"] == 1
        assert after["version"] == before["version"] + 1

    def test_countersigning_leaves_the_requalification_ledger_alone(
        self, api, signed_letter_on_the_middle_rung
    ):
        """PRD §3.4: "Apart from the initial election, countersigning and terminating are
        the only commitment operations that reach the contract row."
        PRD §3.4: "Opening a requalification is the **only** way to make a compliance
        measurement finalizable, and by itself it changes no price: it is a gate, not an
        action."

        Design: Corner/state_machines/countersign_side_effects_set_current_tier_and_contract_counter
        """
        setup = signed_letter_on_the_middle_rung

        countersigned = validate_success(
            api.countersign_lop(
                setup["commitment"]["id"], {}, headers=contract_manager_headers()
            ),
            200,
        )

        assert countersigned["last_final_compliance_pct"] is None
        assert countersigned["requalification_round"] == 0


class TestTerminationSupersedesWithoutReplacing:
    """The one supersede in the system that mints nothing to take the old row's place."""

    def test_the_live_price_is_superseded_and_points_at_no_successor(self, api, priced_setup):
        """PRD §3.4: "Every price activation belonging to this commitment whose status is
        `DRAFT`, `ENDORSED`, `APPROVED` or `ACTIVE` moves to `SUPERSEDED` with its
        `superseded_by_activation_id` left null, because **no replacement is synthesized**
        — the member is leaving, not being repriced."
        PRD §3.6: "`SUPERSEDED` is never reached by a client request; it is written only by
        a commitment termination, as described in §3.4, or by the requalification cascade of
        §3.8."

        Design: Corner/state_machines/terminate_cascades_down_to_live_activations_without_replacement
        """
        setup = priced_setup
        assert read_item(api, setup["item"]["id"])["active_activation_count"] == 1

        terminated = terminate_commitment(api, setup["commitment"]["id"])

        assert terminated["election_status"] == "TERMINATED"
        activation = read_activation(api, setup["activation"]["id"])
        assert activation["status"] == "SUPERSEDED"
        assert activation["superseded_by_activation_id"] is None

    def test_the_activation_list_still_holds_exactly_the_one_row(self, api, priced_setup):
        """PRD §3.6: "Because those replacements are created without a client request, the
        activation list — filterable by `commitment_id`, `contract_item_id`, `status`,
        `activation_type`, `origin`, and by either end of a supersede link through
        `superseded_by_activation_id` or `replaces_activation_id` — is the only channel
        through which a client can find them."

        Design: Corner/state_machines/terminate_cascades_down_to_live_activations_without_replacement
        """
        setup = priced_setup

        terminate_commitment(api, setup["commitment"]["id"])

        rows, meta = _activations_of(api, setup["commitment"]["id"])
        assert meta["total_count"] == 1
        a.assert_exact_ids(rows, [setup["activation"]["id"]])
        assert rows[0]["status"] == "SUPERSEDED"

    def test_the_touched_item_recomputes_once_and_the_contract_counter_falls(
        self, api, priced_setup
    ):
        """PRD §3.4: "For each catalog item touched by that supersede,
        `active_activation_count` is recomputed exactly once, incrementing that item's
        `version` by one."
        PRD §3.4: "And the parent contract's `active_commitment_count` is recomputed,
        incrementing the contract's `version` by one."
        PRD §2.7: "Second, **a recompute fires at most once per triggering request per
        affected row**."

        Design: Corner/state_machines/terminate_cascades_down_to_live_activations_without_replacement
        """
        setup = priced_setup
        item_before = read_item(api, setup["item"]["id"])

        terminate_commitment(api, setup["commitment"]["id"])

        item_after = read_item(api, setup["item"]["id"])
        assert item_after["active_activation_count"] == 0
        assert item_after["version"] == item_before["version"] + 1
        assert read_contract(api, setup["contract"]["id"])["active_commitment_count"] == 0


class TestAFinalizeThatEarnsTheIncumbentTier:
    """Two hops run, three do not: nothing in the price ladder is allowed to move."""

    def test_the_preliminary_reading_has_no_basis_at_all(
        self, api, requalification_without_a_single_file
    ):
        """PRD §3.8: "When `total_category_spend_cents` comes out at 0, `compliance_pct` is
        0.00 and `basis_empty` is set to true; otherwise `compliance_pct` is
        `on_contract_spend_cents` multiplied by 100, divided by
        `total_category_spend_cents`, rounded half up to two decimal places, and
        `basis_empty` is false."
        PRD §3.8: "If no entry is eligible, `qualified_tier_code` falls back to the
        contract's `default_tier_code`."

        Design: Corner/state_machines/finalize_without_tier_change_touches_no_activation
        """
        setup = requalification_without_a_single_file

        preliminary = measure(api, setup["measurement"]["id"])

        assert preliminary["status"] == "PRELIMINARY"
        assert preliminary["basis_empty"] is True
        a.assert_pct(preliminary["compliance_pct"], 0.00)
        a.assert_pct(preliminary["preliminary_compliance_pct"], 0.00)
        assert preliminary["measured_volume_units"] == 0
        assert preliminary["qualified_tier_code"] == TIER_0

    def test_the_two_surviving_hops_still_close_the_requalification_cycle(
        self, api, requalification_without_a_single_file
    ):
        """PRD §3.8: "When the derived `qualified_tier_code` equals the tier the commitment
        was already carrying, hops 3, 4 and 5 do not fire at all: no price activation is
        superseded, no replacement is minted, and no catalog item row is touched."
        PRD §3.8: "Hops 1 and 2 still run, so `requalification_round` still increments and
        `election_status` still returns to `ACTIVE`."

        Design: Corner/state_machines/finalize_without_tier_change_touches_no_activation
        """
        setup = requalification_without_a_single_file
        measure(api, setup["measurement"]["id"])

        finalized = finalize_measurement(api, setup["measurement"]["id"])

        assert finalized["status"] == "FINAL"
        assert finalized["computed_variant"] == "FINAL"
        a.assert_pct(finalized["compliance_pct"], 0.00)
        a.assert_pct(finalized["preliminary_compliance_pct"], 0.00)
        commitment = read_commitment(api, setup["commitment"]["id"])
        assert commitment["election_status"] == "ACTIVE"
        assert commitment["current_tier_code"] == TIER_0
        assert commitment["requalification_round"] == 1
        a.assert_pct(commitment["last_final_compliance_pct"], 0.00)

    def test_no_activation_and_no_catalog_item_is_touched(
        self, api, requalification_without_a_single_file
    ):
        """PRD §3.8: "**Hop 3**, caused by hop 2, and **only when `current_tier_code`
        actually changed**."
        PRD §3.8: "**Hop 5**, caused by the status writes of hops 3 and 4. For each catalog
        item touched anywhere in hops 3 and 4, `active_activation_count` is recomputed
        exactly once — once per item, not once per activation — incrementing that item's
        `version` by one."

        Design: Corner/state_machines/finalize_without_tier_change_touches_no_activation
        """
        setup = requalification_without_a_single_file
        measure(api, setup["measurement"]["id"])

        finalize_measurement(api, setup["measurement"]["id"])

        activation = read_activation(api, setup["activation"]["id"])
        assert activation["status"] == "ACTIVE"
        assert activation["version"] == setup["activation_before"]["version"]
        item = read_item(api, setup["item"]["id"])
        assert item["version"] == setup["item_before"]["version"]
        assert item["active_activation_count"] == 1
        _rows, meta = _activations_of(
            api, setup["commitment"]["id"], origin="REQUALIFICATION_CASCADE"
        )
        assert meta["total_count"] == 0
        assert read_measurement(api, setup["measurement"]["id"])["status"] == "FINAL"


class TestEvidenceEndorsedIsRecomputedNotToggled:
    """A reject runs the same recompute an endorse does, and finds the endorsement still there."""

    def test_endorsing_the_first_dossier_flips_the_flag_and_bumps_the_contract_once(
        self, api, two_dossiers_on_one_contract
    ):
        """PRD §2.7: "Contracts carry `evidence_endorsed`, true exactly when at least one
        clinical evidence review naming that contract has reached `ENDORSED` status,
        recomputed on every endorse and every reject of an evidence review; and
        `active_commitment_count`, the number of commitments on that contract whose election
        status is `ACTIVE` or `REQUAL_REVIEW`, recomputed when a letter of participation is
        countersigned, when a letter is voided, and when a commitment is terminated."
        PRD §3.2: "An accepted endorsement sets `status` to `ENDORSED`, records
        `endorsed_by_user_id` as the endorsing reviewer's `X-User-ID`, and then reaches
        across to the parent contract: `evidence_endorsed` is recomputed and the contract's
        `version` increments by one."

        Design: Corner/state_machines/review_endorse_and_reject_recompute_contract_evidence_endorsed
        """
        setup = two_dossiers_on_one_contract
        contract = setup["contract"]
        assert contract["evidence_endorsed"] is False
        a.assert_score(setup["review_b"]["weighted_score"], 6.55)
        assert setup["review_b"]["conversion_recommendation"] == "DO_NOT_CONVERT"

        endorsed = validate_success(
            api.endorse_review(
                setup["review_a"]["id"], {}, headers=clinical_reviewer_2_headers()
            ),
            200,
        )

        assert endorsed["status"] == "ENDORSED"
        assert endorsed["endorsed_by_user_id"] == CLINICAL_REVIEWER_2
        after = read_contract(api, contract["id"])
        assert after["evidence_endorsed"] is True
        assert after["version"] == contract["version"] + 1

    def test_rejecting_the_second_dossier_recomputes_the_flag_to_true_again(
        self, api, two_dossiers_on_one_contract
    ):
        """PRD §3.2: "Rejection sets `status` to `REJECTED` and, exactly as endorsement
        does, recomputes the parent contract's `evidence_endorsed` and increments that
        contract's `version` by one."
        PRD §3.2: "Dossiers may be listed filtered by `contract_id` and `status`."

        Design: Corner/state_machines/review_endorse_and_reject_recompute_contract_evidence_endorsed
        """
        setup = two_dossiers_on_one_contract
        validate_success(
            api.endorse_review(
                setup["review_a"]["id"], {}, headers=clinical_reviewer_2_headers()
            ),
            200,
        )
        middle = read_contract(api, setup["contract"]["id"])

        rejected = validate_success(
            api.reject_review(
                setup["review_b"]["id"],
                f.reason_payload("efficacy below the comparator"),
                headers=clinical_reviewer_2_headers(),
            ),
            200,
        )

        assert rejected["status"] == "REJECTED"
        after = read_contract(api, setup["contract"]["id"])
        assert after["evidence_endorsed"] is True
        assert after["version"] == middle["version"] + 1
        rows, meta = validate_paginated(
            api.list_contract_evidence_reviews(
                setup["contract"]["id"], f.page(10, 0), headers=compliance_analyst_headers()
            )
        )
        assert meta["total_count"] == 2
        assert sorted(row["status"] for row in rows) == ["ENDORSED", "REJECTED"]
