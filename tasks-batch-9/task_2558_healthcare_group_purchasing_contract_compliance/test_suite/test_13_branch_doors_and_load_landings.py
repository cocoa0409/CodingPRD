"""Branch by branch: which door a row may leave by, and where a load lands.

A local exception cannot take the tier-price shortcut out of `DRAFT`; validation
stamps its two reject reasons in a fixed order; a file with nothing acceptable
in it lands terminally rejected and moves no ledger; and an abandoned
measurement gives its period back.
"""

import pytest

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_DUPLICATE_MEASUREMENT_PERIOD,
    ERR_INVALID_ACTIVATION_STATE,
    ERR_INVALID_FILE_STATE,
)
from test_helpers.constants import FLAT_TIER_LADDER, HOLDBACK_FLAT, TIER_0
from test_helpers.fixtures import (
    build_priced_setup,
    commitment_version,
    create_active_contract,
    create_commitment,
    create_local_exception,
    create_member,
    lines_of_file,
    load_distributor_file,
    measure,
    open_measurement,
    read_activation,
    read_commitment,
    read_distributor_file,
    read_item,
    read_measurement,
    read_member,
    set_clock,
    submit_distributor_file,
)
from test_helpers.test_users import (
    compliance_analyst_headers,
    contract_manager_2_headers,
    contract_manager_headers,
)


@pytest.fixture
def draft_local_exception(api):
    """A DRAFT LOCAL_EXCEPTION asking 9000 against a 10000 tier price and an 8200 floor."""
    setup = build_priced_setup(api, with_activation=False)
    setup["activation"] = create_local_exception(
        api,
        setup["commitment"]["id"],
        setup["member"]["id"],
        setup["item"]["id"],
        9000,
        stage="DRAFT",
    )
    return setup


@pytest.fixture
def validated_three_line_file(api):
    """One VALIDATING statement: an in-period purchase, a stale zero, and an in-period zero."""
    set_clock(api)
    contract = create_active_contract(
        api,
        contract_code="C-VAL",
        requires_clinical_review=False,
        tiers=[dict(row) for row in FLAT_TIER_LADDER],
        holdback_tiers=[dict(row) for row in HOLDBACK_FLAT],
    )
    member = create_member(api, member_code="M-VAL")
    statement = submit_distributor_file(
        api,
        member["id"],
        contract["id"],
        [
            f.purchase_line_row("MI-1", 5, 1000, "2026-08-05"),
            f.purchase_line_row("MI-1", 0, 1000, "2026-07-15"),
            f.purchase_line_row("MI-1", 0, 1000, "2026-08-06"),
        ],
        stage="VALIDATED",
    )
    return {"contract": contract, "member": member, "statement": statement}


@pytest.fixture
def validated_zero_quantity_file(api):
    """A VALIDATING statement whose only line was reported with a quantity of zero."""
    set_clock(api)
    contract = create_active_contract(
        api,
        contract_code="C-ZER",
        requires_clinical_review=False,
        tiers=[dict(row) for row in FLAT_TIER_LADDER],
        holdback_tiers=[dict(row) for row in HOLDBACK_FLAT],
    )
    member = create_member(api, member_code="M-ZER")
    commitment = create_commitment(api, member["id"], contract["id"])
    statement = submit_distributor_file(
        api,
        member["id"],
        contract["id"],
        [f.purchase_line_row("MI-1", 0, 1000, "2026-08-05")],
        stage="VALIDATED",
    )
    return {
        "contract": contract,
        "member": member,
        "commitment": commitment,
        "statement": statement,
    }


@pytest.fixture
def preliminary_measurement(api, active_commitment):
    """A PRELIMINARY measurement over [2026-08-01, 2026-09-01) on an ACTIVE commitment."""
    commitment_id = active_commitment["commitment"]["id"]
    version_before = commitment_version(api, commitment_id)
    measurement = open_measurement(api, commitment_id)
    measured = measure(api, measurement["id"])
    return {
        "commitment": active_commitment["commitment"],
        "version_before": version_before,
        "measurement": measured,
    }


def _measurements_of(api, commitment_id):
    return validate_paginated(
        api.list_measurements(
            f.page(10, 0, commitment_id=commitment_id), headers=compliance_analyst_headers()
        )
    )


def _line_dated(lines, purchase_date):
    matches = [line for line in lines if line.get("purchase_date") == purchase_date]
    assert len(matches) == 1, "expected exactly one line dated {0}, found {1}".format(
        purchase_date, len(matches)
    )
    return matches[0]


class TestTheLocalExceptionBranchHasNoShortcut:
    """Three doors refuse the DRAFT row before the two-signature path opens the fourth."""

    def test_the_requested_price_stands_because_it_sits_above_the_floor(
        self, api, draft_local_exception
    ):
        """PRD §3.6: "When `activation_type` is `LOCAL_EXCEPTION`, the candidate price is the
        **lesser** of the activation's `requested_price_cents` and the tier price from step 2
        — a local exception may only ever move *down* from the tier price, and asking for more
        than the tier price is silently ceilinged rather than rejected."
        PRD §3.6: "Two illustrations of the interaction: a requested 9000 cents against a
        zero-discount tier price of 10000 with a floor of 8200 yields a candidate of 9000,
        which is above the floor, so `computed_price_cents` is 9000 and `price_clamped` is
        false; a requested 8000 cents against a 1500-basis-point tier price of 8500 with a
        floor of 8200 yields a candidate of 8000, which is below the floor, so
        `computed_price_cents` becomes 8200 and `price_clamped` is true."
        PRD §3.6: "An accepted request creates the activation in `DRAFT` status with `origin`
        `REQUEST`, `endorsed_by_user_id`, `approved_by_user_id`, `deny_note`,
        `superseded_by_activation_id` and `replaces_activation_id` all null."

        Design: Corner/state_machines/local_exception_branch_cannot_activate_straight_from_draft
        """
        activation = draft_local_exception["activation"]

        assert activation["status"] == "DRAFT"
        assert activation["activation_type"] == "LOCAL_EXCEPTION"
        assert activation["origin"] == "REQUEST"
        assert activation["requested_price_cents"] == 9000
        assert activation["tier_code_at_activation"] == TIER_0
        assert activation["computed_price_cents"] == 9000
        assert activation["price_clamped"] is False
        assert activation["endorsed_by_user_id"] is None
        assert activation["approved_by_user_id"] is None

    def test_neither_activate_nor_approve_may_be_reached_from_draft(
        self, api, draft_local_exception
    ):
        """PRD §3.6: "**The tier-price track is short.** A `ContractManager` activates the
        `DRAFT` row directly, moving `DRAFT → ACTIVE`."
        PRD §3.6: "Four preconditions apply: the row must be in `DRAFT` and its
        `activation_type` must be `TIER_PRICE`, else `ERR_INVALID_ACTIVATION_STATE`; the
        contract must still be `ACTIVE`, else `ERR_CONTRACT_NOT_ACTIVE`; if the catalog item's
        `requires_evidence` flag is true, the parent contract must carry an evidence review in
        `ENDORSED` status whose `conversion_recommendation` is `CONVERT`, else
        `ERR_CLINICAL_REVIEW_NOT_ENDORSED`; and an `APPROVED` cross-reference must already
        link the commitment's member to this catalog item, else `ERR_XREF_NOT_APPROVED`."
        PRD §3.6: "A **different** `ContractManager` then approves it, moving `ENDORSED →
        APPROVED` and recording `approved_by_user_id`; approval requires the row to be in
        `ENDORSED`, requires the approving `X-User-ID` to differ from `endorsed_by_user_id`
        (else `ERR_SEGREGATION_OF_DUTIES`), and applies the same `REQUAL_REVIEW` bar."

        Design: Corner/state_machines/local_exception_branch_cannot_activate_straight_from_draft
        """
        setup = draft_local_exception
        activation_id = setup["activation"]["id"]

        validate_error(
            api.activate_price_activation(
                activation_id, {}, headers=contract_manager_headers()
            ),
            ERR_INVALID_ACTIVATION_STATE,
            409,
        )
        validate_error(
            api.approve_price_activation(
                activation_id, {}, headers=contract_manager_2_headers()
            ),
            ERR_INVALID_ACTIVATION_STATE,
            409,
        )

        still_draft = read_activation(api, activation_id)
        assert still_draft["status"] == "DRAFT"
        assert still_draft["approved_by_user_id"] is None
        assert read_item(api, setup["item"]["id"])["active_activation_count"] == 0

    def test_endorse_then_a_second_manager_then_activate_is_the_only_way_through(
        self, api, draft_local_exception
    ):
        """PRD §3.6: "**The local-exception track is long, and it is where segregation of
        duties bites.** A `ContractManager` first endorses the `DRAFT` row, moving `DRAFT →
        ENDORSED` and recording `endorsed_by_user_id` as the endorser's `X-User-ID`."
        PRD §3.6: "Only then may a `ContractManager` activate it, moving `APPROVED → ACTIVE`
        under exactly the same four preconditions as the tier-price activation — `APPROVED`
        status with `activation_type` `LOCAL_EXCEPTION`, an `ACTIVE` contract, the evidence
        gate for an evidence-flagged item, and an `APPROVED` cross-reference — with exactly
        the same effects: `status` becomes `ACTIVE`, the activation's `version` increments by
        one, and the catalog item's `active_activation_count` is recomputed with a `version`
        increment on that item."

        Design: Corner/state_machines/local_exception_branch_cannot_activate_straight_from_draft
        """
        setup = draft_local_exception
        activation_id = setup["activation"]["id"]

        endorsed = validate_success(
            api.endorse_price_activation(
                activation_id, {}, headers=contract_manager_headers()
            ),
            200,
        )
        assert endorsed["status"] == "ENDORSED"
        validate_error(
            api.activate_price_activation(
                activation_id, {}, headers=contract_manager_headers()
            ),
            ERR_INVALID_ACTIVATION_STATE,
            409,
        )
        assert read_item(api, setup["item"]["id"])["active_activation_count"] == 0

        approved = validate_success(
            api.approve_price_activation(
                activation_id, {}, headers=contract_manager_2_headers()
            ),
            200,
        )
        assert approved["status"] == "APPROVED"
        assert read_item(api, setup["item"]["id"])["active_activation_count"] == 0

        activated = validate_success(
            api.activate_price_activation(
                activation_id, {}, headers=contract_manager_headers()
            ),
            200,
        )
        assert activated["status"] == "ACTIVE"
        assert read_item(api, setup["item"]["id"])["active_activation_count"] == 1


class TestValidationStampsItsTwoReasonsInOrder:
    """The date test runs before the quantity test, and the counters follow the stamps."""

    def test_the_counters_land_at_one_accepted_and_two_rejected(
        self, api, validated_three_line_file
    ):
        """PRD §3.7: "The same `DistributorAgent` then validates the file, driving `RECEIVED →
        VALIDATING`; any other starting status returns `ERR_INVALID_FILE_STATE`."
        PRD §3.7: "Validation then recomputes `accepted_line_count` as the number of lines
        whose `reject_reason` is `NONE` and `rejected_line_count` as the number whose
        `reject_reason` is anything else, and increments the file's `version` by one."
        PRD §3.7: "The file's `line_count` is set to the number of purchase lines created,
        while `accepted_line_count` and `rejected_line_count` remain 0 and `loaded_at` and
        `reverse_note` remain null."

        Design: Corner/state_machines/distributor_file_validate_stamps_reject_reasons_and_counts
        """
        statement = validated_three_line_file["statement"]

        assert statement["status"] == "VALIDATING"
        assert statement["line_count"] == 3
        assert statement["accepted_line_count"] == 1
        assert statement["rejected_line_count"] == 2
        assert statement["loaded_at"] is None
        assert statement["reverse_note"] is None

    def test_the_zero_quantity_line_outside_the_period_records_the_date_reason(
        self, api, validated_three_line_file
    ):
        """PRD §3.7: "Validation stamps a `reject_reason` on each purchase line by a two-test
        cascade in a fixed order: the line takes `DATE_OUT_OF_PERIOD` when its `purchase_date`
        falls outside the file's half-open period; otherwise it takes `ZERO_QUANTITY` when its
        `quantity_units` is exactly 0; otherwise it keeps `NONE`."
        PRD §3.7: "The order matters — a zero-quantity line dated outside the period records
        `DATE_OUT_OF_PERIOD`, not `ZERO_QUANTITY`."
        PRD §3.7: "Purchase lines are immutable append-only records: no request ever creates,
        updates or deletes one directly, and they are discovered only through the purchase-line
        list — filterable by `distributor_file_id`, `classification` and `reject_reason` — or
        through a single-line read."

        Design: Corner/state_machines/distributor_file_validate_stamps_reject_reasons_and_counts
        """
        statement = validated_three_line_file["statement"]

        stale = lines_of_file(api, statement["id"], reject_reason="DATE_OUT_OF_PERIOD")
        empty = lines_of_file(api, statement["id"], reject_reason="ZERO_QUANTITY")
        kept = lines_of_file(api, statement["id"], reject_reason="NONE")

        assert len(stale) == 1
        assert _line_dated(stale, "2026-07-15")["quantity_units"] == 0
        assert len(empty) == 1
        assert _line_dated(empty, "2026-08-06")["quantity_units"] == 0
        assert len(kept) == 1
        assert _line_dated(kept, "2026-08-05")["quantity_units"] == 5
        for line in stale + empty + kept:
            a.assert_line_classification(
                line, "UNCLASSIFIED", matched_vendor_item_number=None, contract_units=0
            )


class TestALoadWithNothingAcceptableLandsRejected:
    """The third landing of the load branch: terminal, unstamped, and nothing to compensate."""

    def test_the_file_lands_rejected_and_stamps_no_load_time(
        self, api, validated_zero_quantity_file
    ):
        """PRD §3.7: "**`VALIDATING → REJECTED`** when `accepted_line_count` is 0."
        PRD §3.7: "`status` becomes `REJECTED`, no line is classified, and no commitment
        ledger field moves at all."
        PRD §3.7: "Reversal unwinds a load completely."
        PRD §3.7: "A `ComplianceAnalyst` reverses a file from `LOADED` or from
        `PARTIALLY_LOADED` — the two branches behave identically — optionally recording a
        `reason` stored as `reverse_note`; any other starting status returns
        `ERR_INVALID_FILE_STATE`."

        Design: Corner/state_machines/file_load_with_zero_accepted_lines_lands_rejected
        """
        setup = validated_zero_quantity_file
        assert setup["statement"]["accepted_line_count"] == 0
        assert setup["statement"]["rejected_line_count"] == 1

        loaded = load_distributor_file(api, setup["statement"]["id"])

        assert loaded["status"] == "REJECTED"
        assert loaded["loaded_at"] is None
        validate_error(
            api.reverse_distributor_file(
                setup["statement"]["id"],
                f.reason_payload("nothing loaded"),
                headers=compliance_analyst_headers(),
            ),
            ERR_INVALID_FILE_STATE,
            409,
        )
        assert read_distributor_file(api, setup["statement"]["id"])["status"] == "REJECTED"

    def test_no_ledger_no_flag_and_no_watchlist_entry_moved(
        self, api, validated_zero_quantity_file
    ):
        """PRD §3.7: "Each purchase line whose `reject_reason` is `NONE` is classified;
        rejected lines are skipped entirely and keep `classification` `UNCLASSIFIED`,
        `contract_units` 0 and `matched_vendor_item_number` null, and they never enter any sum
        anywhere in this system."
        PRD §3.4: "A newly elected commitment is born with `election_status` `ELECTED`,
        `lop_status` `NOT_ISSUED`, `signer_name` null, `current_tier_code` null,
        `requalification_round` zero, `last_final_compliance_pct` null, all three year-to-date
        ledgers — `ytd_on_contract_spend_cents`, `ytd_total_category_spend_cents` and
        `ytd_measured_volume_units` — at zero, `ytd_leakage_pct` at 0.00, and `leakage_flag`
        false."
        PRD §3.3: "A new member is `ACTIVE`, with `watchlist_status` `NONE` and
        `fee_credit_balance_cents` zero."

        Design: Corner/state_machines/file_load_with_zero_accepted_lines_lands_rejected
        """
        setup = validated_zero_quantity_file

        load_distributor_file(api, setup["statement"]["id"])

        commitment = read_commitment(api, setup["commitment"]["id"])
        assert commitment["ytd_total_category_spend_cents"] == 0
        assert commitment["ytd_on_contract_spend_cents"] == 0
        assert commitment["ytd_measured_volume_units"] == 0
        a.assert_pct(commitment["ytd_leakage_pct"], 0.00)
        assert commitment["leakage_flag"] is False
        assert read_member(api, setup["member"]["id"])["watchlist_status"] == "NONE"
        lines = lines_of_file(api, setup["statement"]["id"])
        assert len(lines) == 1
        a.assert_line_classification(
            lines[0],
            "UNCLASSIFIED",
            matched_vendor_item_number=None,
            contract_units=0,
            reject_reason="ZERO_QUANTITY",
        )


class TestSupersedingAMeasurementGivesThePeriodBack:
    """The duplicate-period guard reads three statuses, and `SUPERSEDED` is not one of them."""

    def test_a_second_measurement_over_the_live_period_is_refused(
        self, api, preliminary_measurement
    ):
        """PRD §3.8: "No measurement for the same commitment in `DRAFT`, `PRELIMINARY` or
        `FINAL` status may already cover the identical `period_start` and `period_end` pair,
        else `ERR_DUPLICATE_MEASUREMENT_PERIOD`; a measurement that has been abandoned into
        `SUPERSEDED` does not block a fresh one for the same period."
        PRD §3.8: "The new row is created in `DRAFT` with every money and volume field at 0,
        `compliance_pct` at 0.00, `preliminary_compliance_pct` null, `qualified_tier_code`
        null, `basis_empty` false, and `computed_variant` null; the parent commitment's
        `version` increments by one."

        Design: Corner/state_machines/measurement_supersede_frees_the_period_for_a_new_measurement
        """
        setup = preliminary_measurement
        commitment_id = setup["commitment"]["id"]
        assert setup["measurement"]["status"] == "PRELIMINARY"
        live_version = commitment_version(api, commitment_id)
        assert live_version == setup["version_before"] + 1

        validate_error(
            api.create_measurement(
                f.measurement_payload(commitment_id, live_version),
                headers=compliance_analyst_headers(),
            ),
            ERR_DUPLICATE_MEASUREMENT_PERIOD,
            409,
        )

        assert read_measurement(api, setup["measurement"]["id"])["status"] == "PRELIMINARY"

    def test_the_abandoned_row_keeps_its_own_preliminary_figures(
        self, api, preliminary_measurement
    ):
        """PRD §3.8: "A measurement can be abandoned instead of finalized."
        PRD §3.8: "Superseding is available from `DRAFT` and from `PRELIMINARY`, optionally
        recording a `reason`, and it sets `status` to `SUPERSEDED` and increments the
        measurement's `version` by one while changing no commitment field whatsoever."

        Design: Corner/state_machines/measurement_supersede_frees_the_period_for_a_new_measurement
        """
        setup = preliminary_measurement
        before = setup["measurement"]

        superseded = validate_success(
            api.supersede_measurement(
                before["id"],
                f.reason_payload("late distributor file arrived"),
                headers=compliance_analyst_headers(),
            ),
            200,
        )

        assert superseded["status"] == "SUPERSEDED"
        assert superseded["computed_variant"] == "PRELIMINARY"
        a.assert_pct(
            superseded["preliminary_compliance_pct"], float(before["preliminary_compliance_pct"])
        )
        a.assert_version_bump(superseded, before["version"])

    def test_the_freed_period_may_be_measured_again_and_no_tier_ever_moved(
        self, api, preliminary_measurement
    ):
        """PRD §3.8: "Measurements may be listed filtered by `commitment_id` and `status`."
        PRD §3.8: "Crucially, **no commitment field moves**: a preliminary measurement never
        retiers anybody."

        Design: Corner/state_machines/measurement_supersede_frees_the_period_for_a_new_measurement
        """
        setup = preliminary_measurement
        commitment_id = setup["commitment"]["id"]
        validate_success(
            api.supersede_measurement(
                setup["measurement"]["id"],
                f.reason_payload("late distributor file arrived"),
                headers=compliance_analyst_headers(),
            ),
            200,
        )

        replacement = open_measurement(api, commitment_id)

        assert replacement["status"] == "DRAFT"
        assert replacement["id"] != setup["measurement"]["id"]
        assert replacement["computed_variant"] is None
        rows, meta = _measurements_of(api, commitment_id)
        assert meta["total_count"] == 2
        a.assert_exact_ids(rows, [setup["measurement"]["id"], replacement["id"]])
        commitment = read_commitment(api, commitment_id)
        assert commitment["current_tier_code"] == TIER_0
        assert commitment["requalification_round"] == 0
        assert commitment["election_status"] == "ACTIVE"
