"""Guards that read another row's state: the caller's own row is already valid.

In each pair the entity being transitioned is in a perfectly legal state for the
transition attempted, and the refusal comes entirely from a second row — the
commitment behind a measurement, the commitment behind a price activation, the
member behind a distributor file.  Each refusal is then lifted by moving only
that second row and repeating the identical call.
"""

import pytest

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_COMMITMENT_NOT_IN_REQUAL_REVIEW,
    ERR_MEMBER_NOT_ACTIVE,
    ERR_REQUALIFICATION_IN_PROGRESS,
)
from test_helpers.constants import TIER_0, TIER_1
from test_helpers.fixtures import (
    build_priced_setup,
    create_local_exception,
    finalize_measurement,
    load_distributor_file,
    measure,
    open_measurement,
    open_requalification,
    read_activation,
    read_commitment,
    read_distributor_file,
    read_item,
    read_measurement,
    read_member,
    submit_distributor_file,
    suspend_member,
)
from test_helpers.test_users import (
    CONTRACT_MANAGER_1,
    CONTRACT_MANAGER_2,
    compliance_analyst_headers,
    contract_manager_2_headers,
    contract_manager_headers,
    distributor_agent_headers,
    make_member_materials_manager_headers,
)


@pytest.fixture
def preliminary_measurement_on_an_active_commitment(api):
    """A PRELIMINARY measurement whose commitment was never opened for requalification.

    No distributor file exists for the period, so the measurement's basis is
    empty and its percentage is 0.00 under either variant.
    """
    setup = build_priced_setup(api, with_xref=False, with_activation=False)
    measurement = open_measurement(api, setup["commitment"]["id"])
    preliminary = measure(api, measurement["id"])
    setup.update({"measurement": measurement, "preliminary": preliminary})
    return setup


@pytest.fixture
def draft_exception_during_requalification(api):
    """A DRAFT local exception requesting 9000, on a commitment now in REQUAL_REVIEW."""
    setup = build_priced_setup(api, with_activation=False)
    exception = create_local_exception(
        api,
        setup["commitment"]["id"],
        setup["member"]["id"],
        setup["item"]["id"],
        9000,
        stage="DRAFT",
    )
    open_requalification(api, setup["commitment"]["id"], "August requalification opened.")
    setup["exception"] = exception
    return setup


@pytest.fixture
def suspended_member_with_a_file_in_flight(api):
    """A validated but unloaded statement of 200 units at 9500, behind a SUSPENDED member."""
    setup = build_priced_setup(api)
    file_a = submit_distributor_file(
        api,
        setup["member"]["id"],
        setup["contract"]["id"],
        [f.purchase_line_row("MI-1", 200, 9500, "2026-08-05")],
        distributor_code="D-A",
        stage="VALIDATED",
    )
    suspended = suspend_member(api, setup["member"]["id"], "Membership dues delinquent.")
    setup.update({"file_a": file_a, "member_after_suspension": suspended})
    return setup


def _close_the_requalification_window(api, commitment_id, period_start, period_end):
    """Run a measurement over the period to its FINAL state, returning the commitment to ACTIVE."""
    measurement = open_measurement(
        api, commitment_id, period_start=period_start, period_end=period_end
    )
    measure(api, measurement["id"])
    finalize_measurement(api, measurement["id"])
    return measurement


def _files_of_member(api, member_id):
    data, _meta = validate_paginated(
        api.list_distributor_files(
            {"member_id": member_id, "limit": 100}, headers=compliance_analyst_headers()
        )
    )
    return data


class TestFinalizeDependsOnTheCommitmentsRequalReview:
    """(ComplianceMeasurement, Commitment): a valid PRELIMINARY row cannot settle alone."""

    def test_finalize_is_refused_while_the_commitment_is_merely_active(
        self, api, preliminary_measurement_on_an_active_commitment
    ):
        """PRD §3.8: "Finalizing requires the measurement to be in `PRELIMINARY` status,
        else `ERR_INVALID_MEASUREMENT_STATE`, and requires the commitment's
        `election_status` to be `REQUAL_REVIEW`, else
        `ERR_COMMITMENT_NOT_IN_REQUAL_REVIEW`."
        PRD §3.8: "When `total_category_spend_cents` comes out at 0, `compliance_pct` is
        0.00 and `basis_empty` is set to true; otherwise `compliance_pct` is
        `on_contract_spend_cents` multiplied by 100, divided by
        `total_category_spend_cents`, rounded half up to two decimal places, and
        `basis_empty` is false."

        Design: Difficulty/cross_entity_state_dependency/measurement_finalize_depends_on_commitment_requal_review
        """
        setup = preliminary_measurement_on_an_active_commitment
        assert setup["preliminary"]["status"] == "PRELIMINARY"
        assert setup["preliminary"]["basis_empty"] is True
        assert read_commitment(api, setup["commitment"]["id"])["election_status"] == "ACTIVE"

        validate_error(
            api.finalize_measurement(
                setup["measurement"]["id"], {}, headers=compliance_analyst_headers()
            ),
            ERR_COMMITMENT_NOT_IN_REQUAL_REVIEW,
            409,
        )

        after = read_measurement(api, setup["measurement"]["id"])
        assert after["status"] == "PRELIMINARY"
        assert after["computed_variant"] == "PRELIMINARY"
        assert read_commitment(api, setup["commitment"]["id"])["requalification_round"] == 0

    def test_opening_the_requalification_window_lets_the_identical_call_through(
        self, api, preliminary_measurement_on_an_active_commitment
    ):
        """PRD §3.4: "Opening a requalification is a `ComplianceAnalyst` action that
        moves `election_status` from `ACTIVE` to `REQUAL_REVIEW`, optionally recording a
        `reason`, and increments the commitment's `version` by one."
        PRD §3.4: "Opening a requalification is the **only** way to make a compliance
        measurement finalizable, and by itself it changes no price: it is a gate, not an
        action."

        Design: Difficulty/cross_entity_state_dependency/measurement_finalize_depends_on_commitment_requal_review
        """
        setup = preliminary_measurement_on_an_active_commitment

        opened = open_requalification(
            api, setup["commitment"]["id"], "Open the window so the period can settle."
        )
        assert opened["election_status"] == "REQUAL_REVIEW"

        finalize_measurement(api, setup["measurement"]["id"])

        final = read_measurement(api, setup["measurement"]["id"])
        assert final["status"] == "FINAL"
        assert final["computed_variant"] == "FINAL"
        assert final["basis_empty"] is True
        assert final["total_category_spend_cents"] == 0
        assert final["qualified_tier_code"] == TIER_0

    def test_a_settlement_that_does_not_move_the_tier_still_closes_the_cycle(
        self, api, preliminary_measurement_on_an_active_commitment
    ):
        """PRD §3.8: "When the derived `qualified_tier_code` equals the tier the
        commitment was already carrying, hops 3, 4 and 5 do not fire at all: no price
        activation is superseded, no replacement is minted, and no catalog item row is
        touched."
        PRD §3.8: "Hops 1 and 2 still run, so `requalification_round` still increments
        and `election_status` still returns to `ACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/measurement_finalize_depends_on_commitment_requal_review
        """
        setup = preliminary_measurement_on_an_active_commitment
        open_requalification(api, setup["commitment"]["id"])

        finalize_measurement(api, setup["measurement"]["id"])

        commitment = read_commitment(api, setup["commitment"]["id"])
        assert commitment["election_status"] == "ACTIVE"
        assert commitment["requalification_round"] == 1
        assert commitment["current_tier_code"] == TIER_0


class TestLocalExceptionStepsDependOnTheCommitmentNotRequalifying:
    """(PriceActivation, Commitment): the bar is re-armed for endorse and for approve."""

    def test_endorsement_is_refused_while_the_commitment_is_being_retiered(
        self, api, draft_exception_during_requalification
    ):
        """PRD §3.6: "Endorsement requires the row to be in `DRAFT` with
        `activation_type` `LOCAL_EXCEPTION`, else `ERR_INVALID_ACTIVATION_STATE`, and it
        requires the commitment's `election_status` **not** to be `REQUAL_REVIEW`, else
        `ERR_REQUALIFICATION_IN_PROGRESS` — a member being retiered is not a member whose
        custom prices can be moved."
        PRD §3.6: "Two illustrations of the interaction: a requested 9000 cents against a
        zero-discount tier price of 10000 with a floor of 8200 yields a candidate of 9000,
        which is above the floor, so `computed_price_cents` is 9000 and `price_clamped` is
        false; a requested 8000 cents against a 1500-basis-point tier price of 8500 with a
        floor of 8200 yields a candidate of 8000, which is below the floor, so
        `computed_price_cents` becomes 8200 and `price_clamped` is true."

        Design: Difficulty/cross_entity_state_dependency/local_exception_endorse_and_approve_depend_on_commitment_not_requalifying
        """
        setup = draft_exception_during_requalification
        assert setup["exception"]["status"] == "DRAFT"
        assert setup["exception"]["computed_price_cents"] == 9000

        validate_error(
            api.endorse_price_activation(
                setup["exception"]["id"], {}, headers=contract_manager_headers()
            ),
            ERR_REQUALIFICATION_IN_PROGRESS,
            409,
        )

        after = read_activation(api, setup["exception"]["id"])
        assert after["status"] == "DRAFT"
        assert after["endorsed_by_user_id"] is None

    def test_closing_the_window_lets_the_identical_endorsement_through(
        self, api, draft_exception_during_requalification
    ):
        """PRD §3.6: "A `ContractManager` first endorses the `DRAFT` row, moving `DRAFT →
        ENDORSED` and recording `endorsed_by_user_id` as the endorser's `X-User-ID`."
        PRD §3.8: "**Hop 2**, caused by hop 1. The commitment's
        `last_final_compliance_pct` is set to the final `compliance_pct`, its
        `current_tier_code` is overwritten with the measurement's
        `qualified_tier_code`, its `requalification_round` increments by one, and its
        `election_status` returns from `REQUAL_REVIEW` to `ACTIVE`, closing the
        requalification cycle."

        Design: Difficulty/cross_entity_state_dependency/local_exception_endorse_and_approve_depend_on_commitment_not_requalifying
        """
        setup = draft_exception_during_requalification
        _close_the_requalification_window(
            api, setup["commitment"]["id"], "2026-08-01", "2026-09-01"
        )
        assert read_commitment(api, setup["commitment"]["id"])["election_status"] == "ACTIVE"

        endorsed = validate_success(
            api.endorse_price_activation(
                setup["exception"]["id"], {}, headers=contract_manager_headers()
            ),
            200,
        )

        assert endorsed["status"] == "ENDORSED"
        assert endorsed["endorsed_by_user_id"] == CONTRACT_MANAGER_1

    def test_a_second_requalification_window_blocks_the_approval_that_follows(
        self, api, draft_exception_during_requalification
    ):
        """PRD §3.6: "A **different** `ContractManager` then approves it, moving
        `ENDORSED → APPROVED` and recording `approved_by_user_id`; approval requires the
        row to be in `ENDORSED`, requires the approving `X-User-ID` to differ from
        `endorsed_by_user_id` (else `ERR_SEGREGATION_OF_DUTIES`), and applies the same
        `REQUAL_REVIEW` bar."

        Design: Difficulty/cross_entity_state_dependency/local_exception_endorse_and_approve_depend_on_commitment_not_requalifying
        """
        setup = draft_exception_during_requalification
        commitment_id = setup["commitment"]["id"]
        _close_the_requalification_window(api, commitment_id, "2026-08-01", "2026-09-01")
        validate_success(
            api.endorse_price_activation(
                setup["exception"]["id"], {}, headers=contract_manager_headers()
            ),
            200,
        )

        open_requalification(
            api,
            commitment_id,
            "September requalification opened before the exception was approved.",
        )

        validate_error(
            api.approve_price_activation(
                setup["exception"]["id"], {}, headers=contract_manager_2_headers()
            ),
            ERR_REQUALIFICATION_IN_PROGRESS,
            409,
        )

        after = read_activation(api, setup["exception"]["id"])
        assert after["status"] == "ENDORSED"
        assert after["approved_by_user_id"] is None

    def test_the_exception_reaches_active_once_both_windows_are_closed(
        self, api, draft_exception_during_requalification
    ):
        """PRD §3.6: "Only then may a `ContractManager` activate it, moving `APPROVED →
        ACTIVE` under exactly the same four preconditions as the tier-price activation —
        `APPROVED` status with `activation_type` `LOCAL_EXCEPTION`, an `ACTIVE` contract,
        the evidence gate for an evidence-flagged item, and an `APPROVED`
        cross-reference — with exactly the same effects: `status` becomes `ACTIVE`, the
        activation's `version` increments by one, and the catalog item's
        `active_activation_count` is recomputed with a `version` increment on that item."

        Design: Difficulty/cross_entity_state_dependency/local_exception_endorse_and_approve_depend_on_commitment_not_requalifying
        """
        setup = draft_exception_during_requalification
        commitment_id = setup["commitment"]["id"]
        _close_the_requalification_window(api, commitment_id, "2026-08-01", "2026-09-01")
        validate_success(
            api.endorse_price_activation(
                setup["exception"]["id"], {}, headers=contract_manager_headers()
            ),
            200,
        )
        open_requalification(api, commitment_id, "September requalification opened.")
        _close_the_requalification_window(api, commitment_id, "2026-09-01", "2026-10-01")

        validate_success(
            api.approve_price_activation(
                setup["exception"]["id"], {}, headers=contract_manager_2_headers()
            ),
            200,
        )
        activated = validate_success(
            api.activate_price_activation(
                setup["exception"]["id"], {}, headers=contract_manager_headers()
            ),
            200,
        )

        assert activated["status"] == "ACTIVE"
        assert activated["endorsed_by_user_id"] == CONTRACT_MANAGER_1
        assert activated["approved_by_user_id"] == CONTRACT_MANAGER_2
        assert activated["computed_price_cents"] == 9000
        assert read_item(api, setup["item"]["id"])["active_activation_count"] == 1
        commitment = read_commitment(api, commitment_id)
        assert commitment["requalification_round"] == 2
        assert commitment["election_status"] == "ACTIVE"


class TestIntakeDependsOnTheMemberBeingActive:
    """(DistributorFile, Member): the member-state bar sits at intake and nowhere else."""

    def test_a_new_statement_cannot_be_submitted_for_a_suspended_member(
        self, api, suspended_member_with_a_file_in_flight
    ):
        """PRD §3.3: "A `ComplianceAnalyst` may suspend a member, optionally recording a
        `reason`, which moves `status` to `SUSPENDED` and increments `version` by one."
        PRD §3.7: "Submission requires the member to exist and be `ACTIVE`, else
        `ERR_MEMBER_NOT_ACTIVE`; the contract to exist and be `ACTIVE`, else
        `ERR_CONTRACT_NOT_ACTIVE`; `period_end` to be strictly after `period_start`, else
        `ERR_EFFECTIVE_WINDOW_INVALID`; at least one entry in `lines`, else
        `ERR_INVALID_REQUEST`; and no existing file for the same member, contract and
        `distributor_code`, in any status other than `REJECTED` or `REVERSED`, to have a
        half-open collision with the new period, else `ERR_FILE_PERIOD_OVERLAP`."

        Design: Difficulty/cross_entity_state_dependency/distributor_file_intake_depends_on_member_not_suspended
        """
        setup = suspended_member_with_a_file_in_flight
        assert read_member(api, setup["member"]["id"])["status"] == "SUSPENDED"

        payload = f.distributor_file_payload(
            setup["member"]["id"],
            setup["contract"]["id"],
            [f.purchase_line_row("MI-1", 10, 9500, "2026-09-05")],
            distributor_code="D-B",
            period_start="2026-09-01",
            period_end="2026-10-01",
        )
        validate_error(
            api.create_distributor_file(payload, headers=distributor_agent_headers()),
            ERR_MEMBER_NOT_ACTIVE,
            409,
        )

        assert len(_files_of_member(api, setup["member"]["id"])) == 1

    def test_the_member_state_bar_outranks_the_duplicate_election_check(
        self, api, suspended_member_with_a_file_in_flight
    ):
        """PRD §3.3: "A suspended member may not be named by a new commitment election
        and may not be named by a new distributor file; both attempts return
        `ERR_MEMBER_NOT_ACTIVE`."
        PRD §3.4: "Its preconditions are evaluated in this order: the member must exist
        and be `ACTIVE`, else `ERR_MEMBER_NOT_ACTIVE`; the acting `X-User-ID` must equal
        the body's `member_id`, else `ERR_MEMBER_SCOPE_VIOLATION`; the contract must
        exist and be `ACTIVE`, else `ERR_CONTRACT_NOT_ACTIVE`; the `elected_tier_code`
        must name an entry of that contract's tier ladder, else `ERR_TIER_CODE_UNKNOWN`;
        no commitment for the same member and contract may already sit in `ELECTED`,
        `ACTIVE` or `REQUAL_REVIEW` — a `TERMINATED` predecessor does not block a fresh
        election — else `ERR_DUPLICATE_COMMITMENT`; the `effective_from` date must fall
        inside the contract's inclusive term, else `ERR_PERIOD_OUTSIDE_CONTRACT_TERM`;
        and `committed_volume_units`, which must itself be strictly greater than zero,
        must be at least the elected tier's `min_committed_volume_units`, else
        `ERR_COMMITTED_VOLUME_BELOW_TIER`."

        Design: Difficulty/cross_entity_state_dependency/distributor_file_intake_depends_on_member_not_suspended
        """
        setup = suspended_member_with_a_file_in_flight
        member_id = setup["member"]["id"]

        payload = f.commitment_payload(
            member_id,
            setup["contract"]["id"],
            elected_tier_code=TIER_1,
            committed_volume_units=2000,
            effective_from="2026-09-01",
        )
        validate_error(
            api.create_commitment(
                payload, headers=make_member_materials_manager_headers(member_id)
            ),
            ERR_MEMBER_NOT_ACTIVE,
            409,
        )

    def test_a_statement_already_in_flight_still_loads_and_moves_the_ledgers(
        self, api, suspended_member_with_a_file_in_flight
    ):
        """PRD §3.7: "Loading is a `ComplianceAnalyst` action available only from
        `VALIDATING` — anything else returns `ERR_INVALID_FILE_STATE` — and it lands the
        file in one of three states according to the counters validation produced:"
        PRD §3.7: "**`VALIDATING → LOADED`** when `rejected_line_count` is 0 and
        `accepted_line_count` is greater than 0. Every accepted line is classified, the
        ledger cascade runs in full, `status` becomes `LOADED`, and `loaded_at` is
        stamped from the logical clock."
        PRD §3.7: "`ytd_on_contract_spend_cents` grows by the total `extended_cost_cents`
        of the file's `ON_CONTRACT` lines; `ytd_total_category_spend_cents` grows by the
        total `extended_cost_cents` of the file's `ON_CONTRACT`, `OFF_CONTRACT_LEAKAGE`
        and `UNMATCHED` lines together; and `ytd_measured_volume_units` grows by the
        total `contract_units` of the file's `ON_CONTRACT` lines."

        Design: Difficulty/cross_entity_state_dependency/distributor_file_intake_depends_on_member_not_suspended
        """
        setup = suspended_member_with_a_file_in_flight
        assert setup["file_a"]["accepted_line_count"] == 1
        assert setup["file_a"]["rejected_line_count"] == 0

        loaded = load_distributor_file(api, setup["file_a"]["id"])

        assert loaded["status"] == "LOADED"
        assert read_distributor_file(api, setup["file_a"]["id"])["status"] == "LOADED"
        commitment = read_commitment(api, setup["commitment"]["id"])
        assert commitment["ytd_on_contract_spend_cents"] == 1900000
        assert commitment["ytd_total_category_spend_cents"] == 1900000
        assert commitment["ytd_measured_volume_units"] == 200
        assert commitment["leakage_flag"] is False
        assert read_member(api, setup["member"]["id"])["watchlist_status"] == "NONE"
