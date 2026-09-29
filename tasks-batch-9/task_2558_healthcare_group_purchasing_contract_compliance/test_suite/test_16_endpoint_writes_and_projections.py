"""What one endpoint call writes, and what one read projects out of it.

A wholesale item-master replacement that destroys a list without destroying the
mappings that named it, a logical clock that stamps a load before anybody sets
it and again after, one ladder edit that is ordinary setup on a draft and a
gated category conversion on an active row, a leakage projection whose
denominator counts the spend it could not even match, a junction row that needs
both of its parents and refuses a second link in either direction, and a load
that skips two bad lines instead of rolling four back.
"""

import pytest

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_CLINICAL_REVIEW_NOT_ENDORSED,
    ERR_CONTRACT_ITEM_NOT_FOUND,
    ERR_DUPLICATE_XREF,
    ERR_EFFECTIVE_WINDOW_INVALID,
    ERR_MEMBER_ITEM_NOT_IN_MASTER,
    ERR_MEMBER_NOT_FOUND,
)
from test_helpers.constants import (
    DEFAULT_CLOCK_INSTANT,
    FLAT_TIER_LADDER,
    HOLDBACK_FLAT,
    ROLE_DISTRIBUTOR_AGENT,
    TIER_0,
    TWO_RUNG_TIER_LADDER,
)
from test_helpers.fixtures import (
    activate_contract,
    build_priced_setup,
    create_active_contract,
    create_approved_cross_reference,
    create_contract,
    create_evidence_review,
    create_item,
    create_member,
    lines_of_file,
    load_distributor_file,
    read_commitment,
    read_contract,
    read_distributor_file,
    read_member,
    set_clock,
    submit_distributor_file,
)
from test_helpers.test_users import (
    CLINICAL_REVIEWER_2,
    anonymous_headers,
    clinical_reviewer_2_headers,
    compliance_analyst_headers,
    contract_manager_headers,
    distributor_agent_headers,
    finance_administrator_headers,
    make_member_materials_manager_headers,
)

UNKNOWN_MEMBER_ID = "00000000-0000-4000-8000-0000000000ff"
UNKNOWN_ITEM_ID = "00000000-0000-4000-8000-0000000000ee"

# The converted ladder: a new default rung that already carries a discount, and
# a richer rung above it.
CONVERTED_LADDER = [
    {
        "tier_code": "TIER_A",
        "min_committed_volume_units": 0,
        "min_compliance_pct": 0.00,
        "discount_bps": 100,
    },
    {
        "tier_code": "TIER_B",
        "min_committed_volume_units": 3000,
        "min_compliance_pct": 85.00,
        "discount_bps": 900,
    },
]

# The same conversion asked for twice: once while the gate is shut, once after
# it opens. A single rung is a well-formed ladder because it is the default one.
DEEPER_DEFAULT_LADDER = [
    {
        "tier_code": "TIER_A",
        "min_committed_volume_units": 0,
        "min_compliance_pct": 0.00,
        "discount_bps": 200,
    }
]


def _patch_master(api, member_id, rows, headers):
    return validate_success(
        api.patch_member_item_master(member_id, f.item_master_payload(rows), headers=headers),
        200,
    )


def _read_xref(api, xref_id):
    return validate_success(
        api.get_cross_reference(xref_id, headers=contract_manager_headers()), 200
    )


def _xrefs(api, **filters):
    params = f.page(10, 0, **filters)
    return validate_paginated(
        api.list_cross_references(params, headers=contract_manager_headers())
    )


def _patch_tiers(api, contract_id, tiers):
    return api.patch_contract_tiers(
        contract_id, f.tiers_payload(tiers), headers=contract_manager_headers()
    )


def _validate_file(api, file_id):
    return validate_success(
        api.validate_distributor_file(file_id, {}, headers=distributor_agent_headers()), 200
    )


def _leakage_report(api, commitment_id, from_date, to_date, headers=None):
    return api.get_leakage_report(
        commitment_id,
        f.leakage_window(from_date, to_date),
        headers=headers or compliance_analyst_headers(),
    )


@pytest.fixture
def two_entry_master_and_an_approved_mapping(api):
    """A member whose master is [MI-1, MI-2], with MI-1 already APPROVED onto V-1."""
    setup = build_priced_setup(
        api,
        contract_overrides={
            "contract_code": "C-IM",
            "tiers": [dict(row) for row in FLAT_TIER_LADDER],
            "holdback_tiers": [dict(row) for row in HOLDBACK_FLAT],
        },
        member_overrides={
            "member_code": "M-1",
            "item_master": [
                f.item_master_row("MI-1"),
                f.item_master_row("MI-2", description="Mesh graft"),
            ],
        },
    )
    setup["mesh"] = create_item(
        api,
        setup["contract"]["id"],
        vendor_item_number="V-2",
        item_description="Mesh graft 10x10",
        base_price_cents=5000,
        floor_price_cents=4000,
    )
    return setup


class TestItemMasterReplacementKeepsTheMappingsThatNamedIt:
    """The list is destroyed wholesale; the history hanging off it is not."""

    def test_the_array_is_replaced_wholesale_and_only_the_version_moves(
        self, api, two_entry_master_and_an_approved_mapping
    ):
        """PRD §3.3: "The item master is the member's own catalogue of the things it buys,
        and only the member curates it: a `MemberMaterialsManager` replaces its own
        `item_master` wholesale, which increments that member's `version` by one."
        PRD §3.3: "A new member is `ACTIVE`, with `watchlist_status` `NONE` and
        `fee_credit_balance_cents` zero."

        Design: Corner/endpoints/item_master_replacement_keeps_approved_cross_references_working
        """
        setup = two_entry_master_and_an_approved_mapping
        before = read_member(api, setup["member"]["id"])
        assert [row["member_item_number"] for row in before["item_master"]] == ["MI-1", "MI-2"]

        patched = _patch_master(
            api,
            before["id"],
            [
                f.item_master_row("MI-2", description="Mesh graft"),
                f.item_master_row("MI-3", description="Cautery tip"),
            ],
            setup["member_headers"],
        )

        assert [row["member_item_number"] for row in patched["item_master"]] == ["MI-2", "MI-3"]
        a.assert_version_bump(patched, before["version"])
        a.assert_fields_unchanged(
            before,
            patched,
            "member_code",
            "name",
            "aggregation_group_code",
            "status",
            "watchlist_status",
            "fee_credit_balance_cents",
        )

    def test_the_approved_mapping_survives_the_entry_it_named(
        self, api, two_entry_master_and_an_approved_mapping
    ):
        """PRD §3.3: "Replacement is destructive to the list but not to history —
        cross-references already `APPROVED` against a `member_item_number` that the
        replacement removed keep working and keep classifying purchases, while any **new**
        cross-reference must name an entry that is present in the current list."

        Design: Corner/endpoints/item_master_replacement_keeps_approved_cross_references_working
        """
        setup = two_entry_master_and_an_approved_mapping
        xref_before = setup["xref"]
        assert xref_before["member_item_number"] == "MI-1"

        _patch_master(
            api,
            setup["member"]["id"],
            [
                f.item_master_row("MI-2", description="Mesh graft"),
                f.item_master_row("MI-3", description="Cautery tip"),
            ],
            setup["member_headers"],
        )

        xref_after = _read_xref(api, xref_before["id"])
        assert xref_after["status"] == "APPROVED"
        assert xref_after["member_item_number"] == "MI-1"
        assert xref_after["version"] == xref_before["version"]

    def test_a_new_mapping_must_name_an_entry_of_the_current_list(
        self, api, two_entry_master_and_an_approved_mapping
    ):
        """PRD §3.5: "A proposal's preconditions run in this order: the member must exist and
        the acting `X-User-ID` must equal the body's `member_id`, else
        `ERR_MEMBER_SCOPE_VIOLATION`; the parent contract must be `ACTIVE`, else
        `ERR_CONTRACT_NOT_ACTIVE`; the catalog item must exist and be `ACTIVE` rather than
        `DELISTED`, else `ERR_CONTRACT_ITEM_NOT_ACTIVE`; the `member_item_number` must appear
        among the current `item_master` entries of that member, else
        `ERR_MEMBER_ITEM_NOT_IN_MASTER`; and no cross-reference already in `APPROVED` status
        may exist for the same member and catalog item, nor for the same member and member
        item number, else `ERR_DUPLICATE_XREF`."

        Design: Corner/endpoints/item_master_replacement_keeps_approved_cross_references_working
        """
        setup = two_entry_master_and_an_approved_mapping
        _patch_master(
            api,
            setup["member"]["id"],
            [
                f.item_master_row("MI-2", description="Mesh graft"),
                f.item_master_row("MI-3", description="Cautery tip"),
            ],
            setup["member_headers"],
        )

        refused = api.create_cross_reference(
            f.cross_reference_payload(
                setup["member"]["id"], setup["mesh"]["id"], member_item_number="MI-1"
            ),
            headers=setup["member_headers"],
        )

        validate_error(refused, ERR_MEMBER_ITEM_NOT_IN_MASTER, 409)
        accepted = validate_success(
            api.create_cross_reference(
                f.cross_reference_payload(
                    setup["member"]["id"], setup["mesh"]["id"], member_item_number="MI-2"
                ),
                headers=setup["member_headers"],
            ),
            201,
        )
        assert accepted["status"] == "PROPOSED"
        assert accepted["member_item_number"] == "MI-2"

    def test_a_later_purchase_line_still_classifies_through_the_surviving_mapping(
        self, api, two_entry_master_and_an_approved_mapping
    ):
        """PRD §3.7: "For an accepted line the server looks for the cross-reference in
        `APPROVED` status whose member is the file's member, whose `member_item_number` equals
        the line's `member_item_number`, and whose catalog item belongs to the file's
        contract."
        PRD §3.7: "Otherwise the server takes the catalog item the cross-reference points at,
        copies that item's `vendor_item_number` into the line's `matched_vendor_item_number` —
        deliberately a value copy rather than a foreign key, because distributor data is keyed
        by item numbers rather than by identifiers — and computes `contract_units` as the
        line's `quantity_units` multiplied by the cross-reference's `conversion_factor`,
        rounded half up to a whole number of units."

        Design: Corner/endpoints/item_master_replacement_keeps_approved_cross_references_working
        """
        setup = two_entry_master_and_an_approved_mapping
        _patch_master(
            api,
            setup["member"]["id"],
            [
                f.item_master_row("MI-2", description="Mesh graft"),
                f.item_master_row("MI-3", description="Cautery tip"),
            ],
            setup["member_headers"],
        )

        loaded = submit_distributor_file(
            api,
            setup["member"]["id"],
            setup["contract"]["id"],
            [f.purchase_line_row("MI-1", 2, 9500, "2026-08-05")],
            stage="LOADED",
        )

        assert loaded["status"] == "LOADED"
        on_contract = lines_of_file(api, loaded["id"], classification="ON_CONTRACT")
        assert len(on_contract) == 1
        a.assert_line_classification(
            on_contract[0], "ON_CONTRACT", matched_vendor_item_number="V-1", contract_units=2
        )
        assert on_contract[0]["extended_cost_cents"] == 19000


@pytest.fixture
def one_file_received_on_the_untouched_clock(api):
    """A priceable member and one RECEIVED file, with the clock never set."""
    setup = build_priced_setup(
        api,
        contract_overrides={
            "contract_code": "C-CLK",
            "tiers": [dict(row) for row in FLAT_TIER_LADDER],
            "holdback_tiers": [dict(row) for row in HOLDBACK_FLAT],
        },
        pin_clock=False,
    )
    setup["received"] = submit_distributor_file(
        api,
        setup["member"]["id"],
        setup["contract"]["id"],
        [f.purchase_line_row("MI-1", 1, 9500, "2026-08-05")],
        stage="RECEIVED",
    )
    return setup


class TestTheLogicalClockDefaultsAndThenStampsEveryLoad:
    """The stamp reads the declared default first and the set instant afterwards."""

    def test_loaded_at_is_null_until_the_load_hop_and_then_reads_the_default_instant(
        self, api, one_file_received_on_the_untouched_clock
    ):
        """PRD §3.7: "The file's `line_count` is set to the number of purchase lines created,
        while `accepted_line_count` and `rejected_line_count` remain 0 and `loaded_at` and
        `reverse_note` remain null."
        PRD §3.7: "Every accepted line is classified, the ledger cascade runs in full,
        `status` becomes `LOADED`, and `loaded_at` is stamped from the logical clock."
        PRD §2.4: "Before that capability is called for the first time, the logical clock reads
        exactly `2026-08-01T00:00:00Z`, and it never falls back to real wall-clock time."

        Design: Corner/endpoints/logical_clock_defaults_then_stamps_every_later_load
        """
        setup = one_file_received_on_the_untouched_clock
        received = setup["received"]
        assert received["status"] == "RECEIVED"
        assert received["loaded_at"] is None
        assert received["line_count"] == 1

        validated = _validate_file(api, received["id"])
        assert validated["loaded_at"] is None

        loaded = load_distributor_file(api, received["id"])
        assert loaded["status"] == "LOADED"
        a.assert_instant_equals(loaded["loaded_at"], DEFAULT_CLOCK_INSTANT)

    def test_setting_the_clock_echoes_the_instant_and_modifies_no_entity(
        self, api, one_file_received_on_the_untouched_clock
    ):
        """PRD §2.4: "A test-driving capability sets the clock to an exact instant supplied as
        `current_utc` and echoes the value it stored back as `current_utc`; all six roles may
        invoke it, and it modifies no entity."

        Design: Corner/endpoints/logical_clock_defaults_then_stamps_every_later_load
        """
        setup = one_file_received_on_the_untouched_clock
        _validate_file(api, setup["received"]["id"])
        loaded = load_distributor_file(api, setup["received"]["id"])
        contract_before = read_contract(api, setup["contract"]["id"])
        member_before = read_member(api, setup["member"]["id"])
        commitment_before = read_commitment(api, setup["commitment"]["id"])

        echoed = validate_success(
            api.set_clock("2026-09-15T10:30:00.000Z", headers=distributor_agent_headers()), 200
        )

        a.assert_instant_equals(echoed["current_utc"], "2026-09-15T10:30:00.000Z")
        assert read_contract(api, contract_before["id"])["version"] == contract_before["version"]
        assert read_member(api, member_before["id"])["version"] == member_before["version"]
        assert (
            read_commitment(api, commitment_before["id"])["version"]
            == commitment_before["version"]
        )
        after_file = read_distributor_file(api, loaded["id"])
        assert after_file["version"] == loaded["version"]
        a.assert_instant_equals(after_file["loaded_at"], DEFAULT_CLOCK_INSTANT)

    def test_the_second_load_stamps_the_new_instant_while_the_window_test_is_untouched(
        self, api, one_file_received_on_the_untouched_clock
    ):
        """PRD §2.4: "Every date-window comparison the server performs, the `loaded_at` stamp
        written when a distributor file is loaded, and the `effective_from` of any replacement
        price activation minted by a cascade all read this clock and nothing else."
        PRD §3.7: "Validation stamps a `reject_reason` on each purchase line by a two-test
        cascade in a fixed order: the line takes `DATE_OUT_OF_PERIOD` when its `purchase_date`
        falls outside the file's half-open period; otherwise it takes `ZERO_QUANTITY` when its
        `quantity_units` is exactly 0; otherwise it keeps `NONE`."

        Design: Corner/endpoints/logical_clock_defaults_then_stamps_every_later_load
        """
        setup = one_file_received_on_the_untouched_clock
        _validate_file(api, setup["received"]["id"])
        first = load_distributor_file(api, setup["received"]["id"])
        validate_success(
            api.set_clock("2026-09-15T10:30:00.000Z", headers=distributor_agent_headers()), 200
        )

        second = submit_distributor_file(
            api,
            setup["member"]["id"],
            setup["contract"]["id"],
            [f.purchase_line_row("MI-1", 1, 9500, "2026-08-06")],
            distributor_code="D-B",
            stage="RECEIVED",
        )
        validated = _validate_file(api, second["id"])
        loaded = load_distributor_file(api, second["id"])

        assert validated["accepted_line_count"] == 1
        assert validated["rejected_line_count"] == 0
        assert loaded["status"] == "LOADED"
        a.assert_instant_equals(loaded["loaded_at"], "2026-09-15T10:30:00.000Z")
        a.assert_instant_equals(
            read_distributor_file(api, first["id"])["loaded_at"], DEFAULT_CLOCK_INSTANT
        )

    def test_the_clock_takes_any_role_and_needs_no_acting_identity(
        self, api, one_file_received_on_the_untouched_clock
    ):
        """PRD §2.9: "**Authentication** — `X-User-ID` present and non-empty on every request
        except `POST /gpo/_clock/set_current_utc`; otherwise `ERR_UNAUTHENTICATED` (401)."
        PRD §2.4: "A test-driving capability sets the clock to an exact instant supplied as
        `current_utc` and echoes the value it stored back as `current_utc`; all six roles may
        invoke it, and it modifies no entity."

        Design: Corner/endpoints/logical_clock_defaults_then_stamps_every_later_load
        """
        by_finance = validate_success(
            api.set_clock("2026-09-16T00:00:00.000Z", headers=finance_administrator_headers()),
            200,
        )
        a.assert_instant_equals(by_finance["current_utc"], "2026-09-16T00:00:00.000Z")

        anonymously = validate_success(
            api.set_clock(
                "2026-09-17T00:00:00.000Z", headers=anonymous_headers(ROLE_DISTRIBUTOR_AGENT)
            ),
            200,
        )

        a.assert_instant_equals(anonymously["current_utc"], "2026-09-17T00:00:00.000Z")


@pytest.fixture
def draft_contract_and_a_passing_dossier(api):
    """A DRAFT contract on the two-rung ladder plus a 7.15 dossier left UNDER_REVIEW."""
    set_clock(api)
    # The header declares `requires_clinical_review` false so that the activation
    # step is not itself the evidence gate: the gate under test is the one that
    # guards a tier-ladder replacement on an already ACTIVE contract.
    contract = create_contract(
        api,
        contract_code="C-CNV",
        requires_clinical_review=False,
        tiers=[dict(row) for row in TWO_RUNG_TIER_LADDER],
        holdback_tiers=[dict(row) for row in HOLDBACK_FLAT],
    )
    review = create_evidence_review(api, contract["id"], 8.00, 7.00, 6.00, summary="conversion dossier")
    return {"contract": contract, "review": review}


class TestTheTierLadderPatchIsFreeOnDraftAndGatedOnActive:
    """One endpoint, two meanings: ordinary setup, then a category conversion."""

    def test_the_draft_patch_replaces_the_ladder_and_re_derives_the_default(
        self, api, draft_contract_and_a_passing_dossier
    ):
        """PRD §3.1: "On a `DRAFT` contract it is ordinary setup."
        PRD §3.1: "Whichever meaning applies, an accepted replacement overwrites `tiers`
        wholesale, re-derives `default_tier_code` from the new ladder — so the new ladder must
        itself contain exactly one default entry — and increments the contract's `version` by
        one."
        PRD §3.1: "On a well-formed submission the server derives `default_tier_code` as the
        `tier_code` of that single default entry."

        Design: Corner/endpoints/tier_ladder_patch_is_free_on_draft_and_evidence_gated_on_active
        """
        contract = draft_contract_and_a_passing_dossier["contract"]
        assert contract["status"] == "DRAFT"
        assert contract["default_tier_code"] == TIER_0

        patched = validate_success(_patch_tiers(api, contract["id"], CONVERTED_LADDER), 200)

        assert patched["default_tier_code"] == "TIER_A"
        a.assert_tier_ladder_echoed(patched, CONVERTED_LADDER)
        a.assert_version_bump(patched, contract["version"])

    def test_the_active_patch_is_refused_while_the_dossier_is_only_under_review(
        self, api, draft_contract_and_a_passing_dossier
    ):
        """PRD §3.1: "On an `ACTIVE` contract it is a **category conversion**, and it is
        refused with `ERR_CLINICAL_REVIEW_NOT_ENDORSED` unless the contract carries an evidence
        review in `ENDORSED` status whose `conversion_recommendation` is `CONVERT`."
        PRD §3.2: "Worked through: scores of 8.00, 7.00 and 6.00 give 3.20 plus 2.45 plus 1.50,
        a weighted score of 7.15; scores of 6.50, 7.00 and 6.00 give 2.60 plus 2.45 plus 1.50,
        a weighted score of 6.55; and scores of 7.00, 7.00 and 7.02 give an unrounded 7.0050
        that rounds half up to 7.01."
        PRD §3.2: "From the weighted score the server derives `conversion_recommendation`: it
        is `CONVERT` when the weighted score is at least 7.00 — the threshold is **inclusive**,
        so a weighted score of exactly 7.00 recommends conversion — and `DO_NOT_CONVERT`
        otherwise."

        Design: Corner/endpoints/tier_ladder_patch_is_free_on_draft_and_evidence_gated_on_active
        """
        setup = draft_contract_and_a_passing_dossier
        review = setup["review"]
        a.assert_score(review["weighted_score"], 7.15)
        assert review["conversion_recommendation"] == "CONVERT"
        assert review["status"] == "UNDER_REVIEW"
        validate_success(_patch_tiers(api, setup["contract"]["id"], CONVERTED_LADDER), 200)
        activated = activate_contract(api, setup["contract"]["id"])
        assert activated["status"] == "ACTIVE"

        refused = _patch_tiers(api, setup["contract"]["id"], DEEPER_DEFAULT_LADDER)

        validate_error(refused, ERR_CLINICAL_REVIEW_NOT_ENDORSED, 409)
        unchanged = read_contract(api, setup["contract"]["id"])
        a.assert_tier_ladder_echoed(unchanged, CONVERTED_LADDER)
        assert unchanged["version"] == activated["version"]

    def test_the_endorsement_opens_the_gate_and_the_identical_patch_lands(
        self, api, draft_contract_and_a_passing_dossier
    ):
        """PRD §2.9: "**Clinical evidence gate** — an item flagged as requiring evidence may
        only be activated when its contract carries an evidence review in `ENDORSED` status
        whose recommendation is `CONVERT`, and converting an `ACTIVE` contract's tier ladder
        requires the same; otherwise `ERR_CLINICAL_REVIEW_NOT_ENDORSED` (409)."
        PRD §3.2: "An accepted endorsement sets `status` to `ENDORSED`, records
        `endorsed_by_user_id` as the endorsing reviewer's `X-User-ID`, and then reaches across
        to the parent contract: `evidence_endorsed` is recomputed and the contract's `version`
        increments by one."

        Design: Corner/endpoints/tier_ladder_patch_is_free_on_draft_and_evidence_gated_on_active
        """
        setup = draft_contract_and_a_passing_dossier
        after_draft_patch = validate_success(
            _patch_tiers(api, setup["contract"]["id"], CONVERTED_LADDER), 200
        )
        activate_contract(api, setup["contract"]["id"])
        validate_error(
            _patch_tiers(api, setup["contract"]["id"], DEEPER_DEFAULT_LADDER),
            ERR_CLINICAL_REVIEW_NOT_ENDORSED,
            409,
        )

        endorsed = validate_success(
            api.endorse_review(setup["review"]["id"], {}, headers=clinical_reviewer_2_headers()),
            200,
        )
        converted = validate_success(
            _patch_tiers(api, setup["contract"]["id"], DEEPER_DEFAULT_LADDER), 200
        )

        assert endorsed["status"] == "ENDORSED"
        assert endorsed["endorsed_by_user_id"] == CLINICAL_REVIEWER_2
        assert converted["default_tier_code"] == "TIER_A"
        a.assert_tier_ladder_echoed(converted, DEEPER_DEFAULT_LADDER)
        # One bump for the activate, one for the endorse's recompute, one for the patch.
        assert converted["version"] == after_draft_patch["version"] + 3

    def test_evidence_endorsed_turns_true_only_at_the_endorse_call(
        self, api, draft_contract_and_a_passing_dossier
    ):
        """PRD §2.7: "Contracts carry `evidence_endorsed`, true exactly when at least one
        clinical evidence review naming that contract has reached `ENDORSED` status,
        recomputed on every endorse and every reject of an evidence review; and
        `active_commitment_count`, the number of commitments on that contract whose election
        status is `ACTIVE` or `REQUAL_REVIEW`, recomputed when a letter of participation is
        countersigned, when a letter is voided, and when a commitment is terminated."
        PRD §3.1: "Every new contract is born in `DRAFT` status with `evidence_endorsed` false
        and `active_commitment_count` zero."

        Design: Corner/endpoints/tier_ladder_patch_is_free_on_draft_and_evidence_gated_on_active
        """
        setup = draft_contract_and_a_passing_dossier
        assert setup["contract"]["evidence_endorsed"] is False
        activate_contract(api, setup["contract"]["id"])
        assert read_contract(api, setup["contract"]["id"])["evidence_endorsed"] is False

        validate_success(
            api.endorse_review(setup["review"]["id"], {}, headers=clinical_reviewer_2_headers()),
            200,
        )

        assert read_contract(api, setup["contract"]["id"])["evidence_endorsed"] is True


@pytest.fixture
def one_loaded_file_that_leaks_four_ways(api):
    """Four mapped item numbers leak, one unmapped number goes unmatched, one line holds."""
    setup = build_priced_setup(
        api,
        contract_overrides={
            "contract_code": "C-LKR",
            "leakage_alert_threshold_pct": 50.00,
            "tiers": [dict(row) for row in FLAT_TIER_LADDER],
            "holdback_tiers": [dict(row) for row in HOLDBACK_FLAT],
        },
        member_overrides={
            "member_code": "M-LKR",
            "item_master": [
                f.item_master_row("MI-1"),
                f.item_master_row("MI-2", description="Mesh graft"),
                f.item_master_row("MI-3", description="Cautery tip"),
                f.item_master_row("MI-4", description="Trocar"),
                f.item_master_row("MI-9", description="Off-catalog dressing"),
            ],
        },
    )
    contract_id = setup["contract"]["id"]
    member_id = setup["member"]["id"]
    # Only V-1 carries an ACTIVE price, so every other mapped purchase leaks.
    for vendor_number, description, base, floor, member_number in (
        ("V-2", "Mesh graft 10x10", 5000, 4000, "MI-2"),
        ("V-3", "Cautery tip fine", 2500, 2000, "MI-3"),
        ("V-4", "Trocar 5mm", 8000, 6000, "MI-4"),
    ):
        item = create_item(
            api,
            contract_id,
            vendor_item_number=vendor_number,
            item_description=description,
            base_price_cents=base,
            floor_price_cents=floor,
        )
        create_approved_cross_reference(
            api, member_id, item["id"], member_item_number=member_number
        )
    setup["file"] = submit_distributor_file(
        api,
        member_id,
        contract_id,
        [
            f.purchase_line_row("MI-1", 5000, 9500, "2026-08-05"),
            f.purchase_line_row("MI-1", 30, 11000, "2026-08-06"),
            f.purchase_line_row("MI-2", 500, 6000, "2026-08-07"),
            f.purchase_line_row("MI-3", 1000, 3000, "2026-08-08"),
            f.purchase_line_row("MI-4", 100, 9000, "2026-08-09"),
            f.purchase_line_row("MI-9", 300, 9000, "2026-08-10"),
        ],
        stage="LOADED",
    )
    return setup


class TestTheLeakageReportCountsUnmatchedSpendInItsDenominator:
    """A spend view, not a settlement view: what could not be matched still counts."""

    def test_all_six_lines_are_accepted_and_the_file_lands_loaded(
        self, api, one_loaded_file_that_leaks_four_ways
    ):
        """PRD §3.7: "**`VALIDATING → LOADED`** when `rejected_line_count` is 0 and
        `accepted_line_count` is greater than 0."
        PRD §3.7: "A `member_item_number` reported by a distributor need **not** exist in the
        member's item master; an unknown number is not an error at intake, it is simply destined
        to classify as unmatched."

        Design: Corner/endpoints/leakage_report_denominator_includes_unmatched_and_ranks_top_three
        """
        loaded = one_loaded_file_that_leaks_four_ways["file"]
        assert loaded["status"] == "LOADED"
        assert loaded["line_count"] == 6
        assert loaded["accepted_line_count"] == 6
        assert loaded["rejected_line_count"] == 0

    def test_the_denominator_is_on_contract_plus_leakage_plus_unmatched(
        self, api, one_loaded_file_that_leaks_four_ways
    ):
        """PRD §3.7: "It sums `extended_cost_cents` over the `OFF_CONTRACT_LEAKAGE` lines as
        `leakage_spend_cents`, over the `UNMATCHED` lines as `unmatched_spend_cents`, and over
        the `ON_CONTRACT` lines as `on_contract_spend_cents`."
        PRD §3.7: "Its `denominator_cents` is the sum of all three of those figures — note that
        this denominator **always** includes unmatched spend, which is not true of the
        preliminary compliance variant in §3.8, because the report is a spend view rather than a
        settlement view."
        PRD §3.7: "`leakage_pct` is `leakage_spend_cents` multiplied by 100, divided by
        `denominator_cents`, rounded half up to two decimal places, and it is 0.00 when the
        denominator is 0."
        PRD §3.7: "The response also echoes `commitment_id`, `from_date` and `to_date`."

        Design: Corner/endpoints/leakage_report_denominator_includes_unmatched_and_ranks_top_three
        """
        setup = one_loaded_file_that_leaks_four_ways
        commitment_id = setup["commitment"]["id"]

        report = validate_success(
            _leakage_report(api, commitment_id, "2026-08-01", "2026-09-01"), 200
        )

        assert report["on_contract_spend_cents"] == 47500000
        assert report["leakage_spend_cents"] == 7230000
        assert report["unmatched_spend_cents"] == 2700000
        assert report["denominator_cents"] == 57430000
        a.assert_pct(report["leakage_pct"], 12.59)
        assert report["commitment_id"] == commitment_id
        assert report["from_date"] == "2026-08-01"
        assert report["to_date"] == "2026-09-01"

    def test_top_items_keeps_three_groups_ranked_by_spend_then_item_number(
        self, api, one_loaded_file_that_leaks_four_ways
    ):
        """PRD §3.7: "The leakage lines are grouped by `member_item_number`, and each group
        reports that `member_item_number`, a `spend_cents` equal to the summed
        `extended_cost_cents` of the group, and a `quantity_units` equal to the summed
        `quantity_units` of the group."
        PRD §3.7: "Groups are ordered by `spend_cents` descending, ties broken by
        `member_item_number` ascending — never by identifier, since a member item number is
        unique inside a member's item master — and the list is truncated to the top three
        groups."

        Design: Corner/endpoints/leakage_report_denominator_includes_unmatched_and_ranks_top_three
        """
        setup = one_loaded_file_that_leaks_four_ways

        report = validate_success(
            _leakage_report(api, setup["commitment"]["id"], "2026-08-01", "2026-09-01"), 200
        )

        a.assert_top_items(
            report["top_items"],
            [("MI-2", 3000000, 500), ("MI-3", 3000000, 1000), ("MI-4", 900000, 100)],
        )
        assert "MI-1" not in [group["member_item_number"] for group in report["top_items"]]

    def test_a_window_that_does_not_contain_the_period_drops_the_file_whole(
        self, api, one_loaded_file_that_leaks_four_ways
    ):
        """PRD §3.7: "The report considers purchase lines whose `reject_reason` is `NONE`
        belonging to files of this commitment's member-and-contract pair in status `LOADED` or
        `PARTIALLY_LOADED` whose own half-open period is contained in the requested window."
        PRD §2.10: "A measurement includes a distributor file only when the file's half-open
        period lies wholly inside the measurement's half-open period."

        Design: Corner/endpoints/leakage_report_denominator_includes_unmatched_and_ranks_top_three
        """
        setup = one_loaded_file_that_leaks_four_ways

        report = validate_success(
            _leakage_report(
                api,
                setup["commitment"]["id"],
                "2026-08-01",
                "2026-08-15",
                headers=contract_manager_headers(),
            ),
            200,
        )

        assert report["denominator_cents"] == 0
        assert report["on_contract_spend_cents"] == 0
        assert report["leakage_spend_cents"] == 0
        assert report["unmatched_spend_cents"] == 0
        a.assert_pct(report["leakage_pct"], 0.00)
        assert report["top_items"] == []

    def test_the_reported_window_must_be_strictly_oriented(
        self, api, one_loaded_file_that_leaks_four_ways
    ):
        """PRD §3.7: "A `ComplianceAnalyst`, a `ContractManager`, or the owning
        `MemberMaterialsManager` may request a read-only leakage projection for one commitment
        over a half-open window supplied as `from_date` and `to_date`, with `to_date` required
        to be strictly after `from_date`, else `ERR_EFFECTIVE_WINDOW_INVALID`."

        Design: Corner/endpoints/leakage_report_denominator_includes_unmatched_and_ranks_top_three
        """
        setup = one_loaded_file_that_leaks_four_ways

        refused = _leakage_report(api, setup["commitment"]["id"], "2026-09-01", "2026-08-01")

        validate_error(refused, ERR_EFFECTIVE_WINDOW_INVALID, 409)


@pytest.fixture
def two_catalog_items_and_a_two_entry_master(api):
    """An ACTIVE contract carrying V-1 and V-2, and a member whose master is [MI-1, MI-2]."""
    set_clock(api)
    contract = create_active_contract(
        api,
        contract_code="C-LNK",
        tiers=[dict(row) for row in FLAT_TIER_LADDER],
        holdback_tiers=[dict(row) for row in HOLDBACK_FLAT],
    )
    suture = create_item(api, contract["id"])
    mesh = create_item(
        api,
        contract["id"],
        vendor_item_number="V-2",
        item_description="Mesh graft 10x10",
        base_price_cents=5000,
        floor_price_cents=4000,
    )
    member = create_member(
        api,
        member_code="M-1",
        item_master=[
            f.item_master_row("MI-1"),
            f.item_master_row("MI-2", description="Mesh graft"),
        ],
    )
    return {
        "contract": contract,
        "suture": suture,
        "mesh": mesh,
        "member": member,
        "member_headers": make_member_materials_manager_headers(member["id"]),
    }


class TestTheMappingNeedsBothParentsAndIsUniqueEachWay:
    """A junction row resolves its member first, and then refuses a second link either way."""

    def test_both_sides_unknown_reports_the_member_that_is_resolved_first(
        self, api, two_catalog_items_and_a_two_entry_master
    ):
        """PRD §2.8: "Foreign keys named in a request body are resolved after the path
        identifiers, in the order the body declares them — `contract_id`, then `member_id`,
        then `contract_item_id`, then `commitment_id` — and an unresolvable one returns the same
        404 error identifier as its path counterpart."
        PRD §2.9: "**Body foreign-key existence** — every foreign key in the body resolves,
        checked in body-declaration order `contract_id`, `member_id`, `contract_item_id`,
        `commitment_id`; otherwise the matching 404."

        Design: Corner/endpoints/cross_reference_link_requires_both_sides_and_is_unique_each_way
        """
        refused = api.create_cross_reference(
            f.cross_reference_payload(UNKNOWN_MEMBER_ID, UNKNOWN_ITEM_ID),
            headers=make_member_materials_manager_headers(UNKNOWN_MEMBER_ID),
        )

        validate_error(refused, ERR_MEMBER_NOT_FOUND, 404)

    def test_the_catalog_item_is_reported_once_the_member_resolves(
        self, api, two_catalog_items_and_a_two_entry_master
    ):
        """PRD §2.8: "Identifiers appearing in a URL path are resolved **left to right**, and
        the first identifier that resolves to nothing terminates the request with the 404 that
        names that resource type: `ERR_CONTRACT_NOT_FOUND` for an unknown `contract_id`,
        `ERR_CONTRACT_ITEM_NOT_FOUND` for `contract_item_id`, `ERR_MEMBER_NOT_FOUND` for
        `member_id`, `ERR_COMMITMENT_NOT_FOUND` for `commitment_id`, `ERR_XREF_NOT_FOUND` for
        `xref_id`, `ERR_ACTIVATION_NOT_FOUND` for `activation_id`, `ERR_FILE_NOT_FOUND` for
        `file_id`, `ERR_MEASUREMENT_NOT_FOUND` for `measurement_id`,
        `ERR_DISTRIBUTION_NOT_FOUND` for `distribution_id`, `ERR_REVIEW_NOT_FOUND` for
        `review_id`, and `ERR_PURCHASE_LINE_NOT_FOUND` for `purchase_line_id`."

        Design: Corner/endpoints/cross_reference_link_requires_both_sides_and_is_unique_each_way
        """
        setup = two_catalog_items_and_a_two_entry_master

        refused = api.create_cross_reference(
            f.cross_reference_payload(setup["member"]["id"], UNKNOWN_ITEM_ID),
            headers=setup["member_headers"],
        )

        validate_error(refused, ERR_CONTRACT_ITEM_NOT_FOUND, 404)

    def test_the_accepted_proposal_is_queryable_from_either_side(
        self, api, two_catalog_items_and_a_two_entry_master
    ):
        """PRD §3.5: "A `MemberMaterialsManager` proposes one by naming its own `member_id`,
        the `contract_item_id` of the catalog line being mapped to, the `member_item_number` on
        its own side, a `match_type` drawn from `EXACT`, `EQUIVALENT` or `MANUAL` recording how
        good the mapping is, and a `conversion_factor` strictly greater than zero carrying at
        most four decimal places."
        PRD §3.5: "The mapping is created in `PROPOSED` status."
        PRD §3.5: "Approving it drives `PROPOSED → APPROVED`, records `approved_by_user_id` as
        the approver's `X-User-ID`, and increments the mapping's `version` by one; the two-sided
        uniqueness check is **re-evaluated at approval time**, so a second proposal that was
        legal when it was raised is refused with `ERR_DUPLICATE_XREF` if a sibling proposal
        reached `APPROVED` first."
        PRD §3.5: "Cross-references may be listed filtered by `member_id`, `contract_item_id`
        and `status`."

        Design: Corner/endpoints/cross_reference_link_requires_both_sides_and_is_unique_each_way
        """
        setup = two_catalog_items_and_a_two_entry_master

        proposed = validate_success(
            api.create_cross_reference(
                f.cross_reference_payload(
                    setup["member"]["id"], setup["suture"]["id"], conversion_factor=2.5
                ),
                headers=setup["member_headers"],
            ),
            201,
        )

        assert proposed["status"] == "PROPOSED"
        assert float(proposed["conversion_factor"]) == 2.5
        assert proposed["approved_by_user_id"] is None
        approved = validate_success(
            api.approve_cross_reference(proposed["id"], {}, headers=contract_manager_headers()),
            200,
        )
        assert approved["status"] == "APPROVED"
        rows, meta = _xrefs(
            api,
            member_id=setup["member"]["id"],
            contract_item_id=setup["suture"]["id"],
            status="APPROVED",
        )
        assert meta["total_count"] == 1
        a.assert_exact_ids(rows, [proposed["id"]])
        assert rows[0]["member_item_number"] == "MI-1"

    def test_the_uniqueness_guard_bites_in_both_directions(
        self, api, two_catalog_items_and_a_two_entry_master
    ):
        """PRD §3.5: "A proposal's preconditions run in this order: the member must exist and
        the acting `X-User-ID` must equal the body's `member_id`, else
        `ERR_MEMBER_SCOPE_VIOLATION`; the parent contract must be `ACTIVE`, else
        `ERR_CONTRACT_NOT_ACTIVE`; the catalog item must exist and be `ACTIVE` rather than
        `DELISTED`, else `ERR_CONTRACT_ITEM_NOT_ACTIVE`; the `member_item_number` must appear
        among the current `item_master` entries of that member, else
        `ERR_MEMBER_ITEM_NOT_IN_MASTER`; and no cross-reference already in `APPROVED` status
        may exist for the same member and catalog item, nor for the same member and member
        item number, else `ERR_DUPLICATE_XREF`."

        Design: Corner/endpoints/cross_reference_link_requires_both_sides_and_is_unique_each_way
        """
        setup = two_catalog_items_and_a_two_entry_master
        approved = create_approved_cross_reference(
            api, setup["member"]["id"], setup["suture"]["id"], conversion_factor=2.5
        )

        # A second member item number aimed at the same catalog line, then a second
        # catalog line aimed at the same member item number. `MANUAL` is the declared
        # enumeration member for a hand-made mapping.
        same_item = api.create_cross_reference(
            f.cross_reference_payload(
                setup["member"]["id"],
                setup["suture"]["id"],
                member_item_number="MI-2",
                match_type="MANUAL",
            ),
            headers=setup["member_headers"],
        )
        same_number = api.create_cross_reference(
            f.cross_reference_payload(
                setup["member"]["id"],
                setup["mesh"]["id"],
                member_item_number="MI-1",
                match_type="MANUAL",
            ),
            headers=setup["member_headers"],
        )

        validate_error(same_item, ERR_DUPLICATE_XREF, 409)
        validate_error(same_number, ERR_DUPLICATE_XREF, 409)
        _rows, meta = _xrefs(api, member_id=setup["member"]["id"])
        assert meta["total_count"] == 1
        assert _read_xref(api, approved["id"])["status"] == "APPROVED"


@pytest.fixture
def a_four_line_file_validated_with_two_bad_lines(api):
    """Two clean lines, one dated before the period and one of zero quantity."""
    setup = build_priced_setup(
        api,
        contract_overrides={
            "contract_code": "C-BLK",
            "leakage_alert_threshold_pct": 50.00,
            "tiers": [dict(row) for row in FLAT_TIER_LADDER],
            "holdback_tiers": [dict(row) for row in HOLDBACK_FLAT],
        },
    )
    setup["received"] = submit_distributor_file(
        api,
        setup["member"]["id"],
        setup["contract"]["id"],
        [
            f.purchase_line_row("MI-1", 2, 9500, "2026-08-05"),
            f.purchase_line_row("MI-1", 1, 12000, "2026-08-06"),
            f.purchase_line_row("MI-1", 3, 9500, "2026-07-15"),
            f.purchase_line_row("MI-1", 0, 9500, "2026-08-07"),
        ],
        stage="RECEIVED",
    )
    setup["validated"] = _validate_file(api, setup["received"]["id"])
    return setup


class TestAPartialLoadSkipsTheRejectedLinesRatherThanRollingBack:
    """Two of four lines are refused and the other two are applied in full."""

    def test_validation_counts_two_good_lines_and_the_load_lands_partial(
        self, api, a_four_line_file_validated_with_two_bad_lines
    ):
        """PRD §3.7: "Validation then recomputes `accepted_line_count` as the number of lines
        whose `reject_reason` is `NONE` and `rejected_line_count` as the number whose
        `reject_reason` is anything else, and increments the file's `version` by one."
        PRD §3.7: "**`VALIDATING → PARTIALLY_LOADED`** when `rejected_line_count` is greater
        than 0 and `accepted_line_count` is also greater than 0."
        PRD §3.7: "Everything is identical to the `LOADED` landing — the same classification
        pass, the same four ledger hops, the same `loaded_at` stamp — and only the resulting
        `status` differs."

        Design: Corner/endpoints/file_load_applies_accepted_lines_and_skips_rejected_ones
        """
        setup = a_four_line_file_validated_with_two_bad_lines
        received = setup["received"]
        validated = setup["validated"]
        assert received["line_count"] == 4
        assert received["accepted_line_count"] == 0
        assert received["rejected_line_count"] == 0
        assert validated["accepted_line_count"] == 2
        assert validated["rejected_line_count"] == 2
        a.assert_version_bump(validated, received["version"])

        loaded = load_distributor_file(api, received["id"])

        assert loaded["status"] == "PARTIALLY_LOADED"
        assert loaded["line_count"] == 4
        a.assert_instant_equals(loaded["loaded_at"], DEFAULT_CLOCK_INSTANT)

    def test_only_the_accepted_lines_move_the_ledgers(
        self, api, a_four_line_file_validated_with_two_bad_lines
    ):
        """PRD §3.7: "A partially loaded file is a real load: its accepted lines are real
        purchases and they move the member's ledgers."
        PRD §3.7: "The server finds the commitment for this file's member-and-contract pair
        whose `election_status` is `ELECTED`, `ACTIVE` or `REQUAL_REVIEW`, and posts three
        running sums onto it: `ytd_on_contract_spend_cents` grows by the total
        `extended_cost_cents` of the file's `ON_CONTRACT` lines; `ytd_total_category_spend_cents`
        grows by the total `extended_cost_cents` of the file's `ON_CONTRACT`,
        `OFF_CONTRACT_LEAKAGE` and `UNMATCHED` lines together; and `ytd_measured_volume_units`
        grows by the total `contract_units` of the file's `ON_CONTRACT` lines."

        Design: Corner/endpoints/file_load_applies_accepted_lines_and_skips_rejected_ones
        """
        setup = a_four_line_file_validated_with_two_bad_lines

        load_distributor_file(api, setup["received"]["id"])

        commitment = read_commitment(api, setup["commitment"]["id"])
        assert commitment["ytd_on_contract_spend_cents"] == 19000
        assert commitment["ytd_total_category_spend_cents"] == 31000
        assert commitment["ytd_measured_volume_units"] == 2
        # 59500 is what counting the two refused lines would have produced.
        assert commitment["ytd_total_category_spend_cents"] != 59500

    def test_the_rejected_lines_keep_their_receipt_cost_and_classify_nothing(
        self, api, a_four_line_file_validated_with_two_bad_lines
    ):
        """PRD §3.7: "An accepted submission creates the file in `RECEIVED` status and turns
        each entry of `lines` into exactly one **purchase line**, each carrying the file's
        identifier as `distributor_file_id`, the submitted `member_item_number`,
        `quantity_units`, `unit_price_paid_cents` and `purchase_date`, an `extended_cost_cents`
        computed immediately as `quantity_units` multiplied by `unit_price_paid_cents`, a
        `classification` of `UNCLASSIFIED`, a `reject_reason` of `NONE`, `contract_units` of 0,
        and `matched_vendor_item_number` null."
        PRD §3.7: "Each purchase line whose `reject_reason` is `NONE` is classified; rejected
        lines are skipped entirely and keep `classification` `UNCLASSIFIED`, `contract_units` 0
        and `matched_vendor_item_number` null, and they never enter any sum anywhere in this
        system."

        Design: Corner/endpoints/file_load_applies_accepted_lines_and_skips_rejected_ones
        """
        setup = a_four_line_file_validated_with_two_bad_lines

        load_distributor_file(api, setup["received"]["id"])

        skipped = lines_of_file(api, setup["received"]["id"], classification="UNCLASSIFIED")
        assert len(skipped) == 2
        out_of_period = a.line_by_item_and_quantity(skipped, "MI-1", 3)
        a.assert_line_classification(
            out_of_period,
            "UNCLASSIFIED",
            matched_vendor_item_number=None,
            contract_units=0,
            reject_reason="DATE_OUT_OF_PERIOD",
        )
        assert out_of_period["extended_cost_cents"] == 28500
        zero_quantity = a.line_by_item_and_quantity(skipped, "MI-1", 0)
        a.assert_line_classification(
            zero_quantity,
            "UNCLASSIFIED",
            matched_vendor_item_number=None,
            contract_units=0,
            reject_reason="ZERO_QUANTITY",
        )
        assert zero_quantity["extended_cost_cents"] == 0

    def test_the_leakage_rate_lands_below_this_contracts_own_threshold(
        self, api, a_four_line_file_validated_with_two_bad_lines
    ):
        """PRD §3.7: "`ytd_leakage_pct` is recomputed as follows: subtract
        `ytd_on_contract_spend_cents` from `ytd_total_category_spend_cents`, multiply the
        difference by 100, divide by `ytd_total_category_spend_cents`, and round half up to two
        decimal places."
        PRD §3.7: "If the recomputed `ytd_leakage_pct` is **strictly greater than** the
        contract's `leakage_alert_threshold_pct`, `leakage_flag` is set to true; a rate landing
        exactly on the threshold does not raise the flag."
        PRD §3.3: "`watchlist_status` takes the value `WATCHLIST` when the leakage cascade of
        §3.7 raises the leakage flag on any of that member's commitments, and returns to `NONE`
        only when no commitment of that member carries a raised flag."

        Design: Corner/endpoints/file_load_applies_accepted_lines_and_skips_rejected_ones
        """
        setup = a_four_line_file_validated_with_two_bad_lines
        a.assert_pct(setup["contract"]["leakage_alert_threshold_pct"], 50.00)

        load_distributor_file(api, setup["received"]["id"])

        commitment = read_commitment(api, setup["commitment"]["id"])
        a.assert_pct(commitment["ytd_leakage_pct"], 38.71)
        assert commitment["leakage_flag"] is False
        assert read_member(api, setup["member"]["id"])["watchlist_status"] == "NONE"

    def test_the_leakage_line_is_still_converted_into_contract_units(
        self, api, a_four_line_file_validated_with_two_bad_lines
    ):
        """PRD §3.7: "Against the governing row's `computed_price_cents`, the line classifies as
        `ON_CONTRACT` when its `unit_price_paid_cents` is less than or equal to that price, and
        as `OFF_CONTRACT_LEAKAGE` when it is greater."
        PRD §3.7: "Otherwise the server takes the catalog item the cross-reference points at,
        copies that item's `vendor_item_number` into the line's `matched_vendor_item_number` —
        deliberately a value copy rather than a foreign key, because distributor data is keyed
        by item numbers rather than by identifiers — and computes `contract_units` as the
        line's `quantity_units` multiplied by the cross-reference's `conversion_factor`,
        rounded half up to a whole number of units."

        Design: Corner/endpoints/file_load_applies_accepted_lines_and_skips_rejected_ones
        """
        setup = a_four_line_file_validated_with_two_bad_lines

        load_distributor_file(api, setup["received"]["id"])

        on_contract = lines_of_file(api, setup["received"]["id"], classification="ON_CONTRACT")
        assert len(on_contract) == 1
        a.assert_line_classification(
            on_contract[0], "ON_CONTRACT", matched_vendor_item_number="V-1", contract_units=2
        )
        assert on_contract[0]["extended_cost_cents"] == 19000
        leaking = lines_of_file(
            api, setup["received"]["id"], classification="OFF_CONTRACT_LEAKAGE"
        )
        assert len(leaking) == 1
        a.assert_line_classification(
            leaking[0],
            "OFF_CONTRACT_LEAKAGE",
            matched_vendor_item_number="V-1",
            contract_units=1,
            reject_reason="NONE",
        )
        assert leaking[0]["extended_cost_cents"] == 12000
