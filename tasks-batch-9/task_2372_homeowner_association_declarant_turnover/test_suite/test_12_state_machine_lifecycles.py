"""Declared initial states, and the terminal states every further action bounces off."""

from typing import Any, Dict

import pytest
from test_helpers import (
    ADEQUACY_ADEQUATE,
    AUDITOR_HEADERS,
    CLAIM_ACTION_NOTICE,
    CLAIM_ACTION_REJECT,
    CLAIM_ACTION_RESERVE,
    CLAIM_ACTION_WITHDRAW,
    DECLARANT_HEADERS,
    DECLARANT_USER_ID,
    DEFAULT_CLOCK_UTC,
    ERR_AUDIT_NOT_ISSUABLE,
    ERR_CLAIM_STATE_INVALID,
    ERR_COMPONENT_MILESTONE_INVALID,
    ERR_DIRECTOR_STATE_INVALID,
    ERR_LOT_STATE_INVALID,
    ERR_NOT_IN_DRAFT,
    ERR_RECORDS_ITEM_STATE_INVALID,
    ERR_SUBSIDY_ENTRY_ALREADY_REVERSED,
    FINDING_CLEAN,
    FINDING_EXCEPTION_NOTED,
    FORECAST_CURRENT,
    FUNDING_METHOD_CASH_FLOW,
    FUNDING_METHOD_COMPONENT_FULL_FUNDING,
    INSPECTOR_HEADERS,
    MILESTONE_BUILD_COMPLETE,
    MILESTONE_CONVEYANCE_ACCEPTED,
    MILESTONE_DEED_TENDERED,
    POSTURE_DECLARANT_CONTROL_OPEN,
    RECORDS_ACTION_ACCEPT,
    SEAT_TYPE_DECLARANT_APPOINTED,
    STUDY_ACTION_ADOPT,
    STUDY_ACTION_RECOMPUTE,
    TRIGGER_BASIS_FIXED_DATE,
    VALUATION_BASIS_REPAIR_COST,
    ApiClient,
    assert_claim_pool_conserved,
    assert_instant,
    assert_pct,
    assert_seat_ledger,
    assert_study_evaluation,
    assert_unevaluated_study,
    claim_action_payload,
    close_sale_payload,
    do_adopt_study,
    do_build_complete,
    do_certify_trigger,
    do_claim_withdraw,
    do_close_sale,
    do_deed_tendered,
    do_deliver_item,
    do_issue_engagement,
    do_recompute_study,
    do_reject_item,
    do_rescind_director,
    do_reverse_entry,
    make_transition_committee_headers,
    milestone_payload,
    read_association,
    read_turnover_case,
    records_transition_payload,
    reversal_payload,
    seed_association,
    seed_audit_engagement,
    seed_component,
    seed_declarant_appointed_director,
    seed_defect_claim,
    seed_lot,
    seed_owner_elected_director,
    seed_records_item,
    seed_reserve_study,
    seed_subsidy_entry,
    seed_turnover_case,
    seed_vendor_contract,
    study_action_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

# ─── Marram Dunes: one row of every kind, freshly created ──────────────


@pytest.fixture
def marram_dunes(api: ApiClient) -> Dict[str, Any]:
    """A community with exactly one untouched row of each entity."""
    association = seed_association(
        api,
        name="Marram Dunes",
        total_planned_lots=10,
        turnover_threshold_pct=66.67,
        fixed_turnover_date="2027-01-01T00:00:00Z",
        statute_of_repose_years=8,
        reserve_pool_cents=200000,
        reserve_claim_pool_cents=500000,
        declarant_monthly_subsidy_cents=25000,
    )
    case = seed_turnover_case(api, association["id"], total_seats=5)
    component = seed_component(
        api,
        association["id"],
        name="Seawall",
        category="STRUCTURE",
        replacement_cost_cents=900000,
        useful_life_years=30,
        effective_age_years=1,
        promised_completion_date="2026-09-01T00:00:00Z",
    )
    contract = seed_vendor_contract(
        api,
        association["id"],
        component["id"],
        vendor_name="Dune Care",
        developer_affiliated=True,
        annual_cost_cents=90000,
        service_window_start="2026-01-01T00:00:00Z",
        service_window_end="2026-12-01T00:00:00Z",
    )
    item = seed_records_item(api, case["id"], "PLANS_AND_SPECS", required=True)
    engagement = seed_audit_engagement(
        api, association["id"], "2026-01-01T00:00:00Z", "2026-06-30T00:00:00Z"
    )
    study = seed_reserve_study(
        api,
        association["id"],
        FUNDING_METHOD_CASH_FLOW,
        planned_annual_contribution_cents=300000,
        projected_annual_expenditure_cents=100000,
    )
    director = seed_declarant_appointed_director(
        api, case["id"], full_name="Nils Aberg"
    )
    entry = seed_subsidy_entry(api, association["id"], "ACCRUAL", 25000, "2026-07")
    return {
        "association": association,
        "case": case,
        "component": component,
        "contract": contract,
        "item": item,
        "engagement": engagement,
        "study": study,
        "director": director,
        "entry": entry,
        "committee_headers": make_transition_committee_headers(association["id"]),
    }


class TestDeclaredInitialStates:
    """Every state machine in the system is asserted at its origin."""

    def test_a_fresh_case_starts_under_declarant_control_with_every_seat_vacant(
        self, api: ApiClient, marram_dunes: Dict[str, Any]
    ) -> None:
        """The board is empty, the trigger unrecorded and the records set vacuously complete.

        "A fresh case begins with `governance_status` at `DECLARANT_CONTROL` and
        `financial_status` at `SUBSIDY_ACTIVE`, hence a `turnover_posture` of
        `DECLARANT_CONTROL_OPEN`, with `vacant_seats` equal to `total_seats`,
        `owner_elected_seats_required` at 0, `declarant_appointed_seats` and
        `owner_elected_seats` at 0, `records_transfer_completeness_pct` at 100.00,
        `settlement_blocked` false, and `trigger_basis`, `trigger_certified_at`
        and `trigger_certified_by_user_id` all null."

        Design: Corner/state_machines/newly_created_rows_start_in_their_declared_initial_states
        """
        case = marram_dunes["case"]
        assert case["governance_status"] == "DECLARANT_CONTROL"
        assert case["financial_status"] == "SUBSIDY_ACTIVE"
        assert case["turnover_posture"] == POSTURE_DECLARANT_CONTROL_OPEN
        assert case["owner_elected_seats_required"] == 0
        assert case["settlement_blocked"] is False
        assert case["trigger_basis"] is None
        assert case["trigger_certified_at"] is None
        assert case["trigger_certified_by_user_id"] is None
        assert_seat_ledger(
            case,
            declarant_appointed=0,
            owner_elected=0,
            vacant=5,
            total_seats=5,
        )
        assert_pct(
            case["records_transfer_completeness_pct"],
            100.00,
            "records_transfer_completeness_pct",
        )

    def test_a_new_component_starts_unbuilt_under_an_active_contract(
        self, api: ApiClient, marram_dunes: Dict[str, Any]
    ) -> None:
        """Neither dimension of the component has moved, and nobody has asked to assign.

        "A new component always starts with `conveyance_status` at
        `NOT_CONVEYED`, `substantial_completion_date` null and `conveyed_at`
        null."

        Design: Corner/state_machines/newly_created_rows_start_in_their_declared_initial_states
        """
        component = marram_dunes["component"]
        assert component["build_status"] == "UNBUILT"
        assert component["conveyance_status"] == "NOT_CONVEYED"
        assert component["substantial_completion_date"] is None
        assert component["conveyed_at"] is None

        contract = marram_dunes["contract"]
        assert contract["status"] == "ACTIVE"
        assert contract["assignment_status"] == "NOT_REQUESTED"
        assert contract["cancellation_window_end"] is None

    def test_a_new_engagement_item_and_study_all_start_unevaluated(
        self, api: ApiClient, marram_dunes: Dict[str, Any]
    ) -> None:
        """Three rows that only later carry a finding, a delivery or a verdict.

        "A new engagement starts `ENGAGED`, with `finding_status` `CLEAN`,
        `unreconciled_delta_cents` 0, `audited_receivable_snapshot_cents` 0 and
        `issued_by_user_id` null."

        Design: Corner/state_machines/newly_created_rows_start_in_their_declared_initial_states
        """
        engagement = marram_dunes["engagement"]
        assert engagement["status"] == "ENGAGED"
        assert engagement["finding_status"] == FINDING_CLEAN
        assert engagement["unreconciled_delta_cents"] == 0
        assert engagement["audited_receivable_snapshot_cents"] == 0
        assert engagement["issued_by_user_id"] is None

        item = marram_dunes["item"]
        assert item["status"] == "OUTSTANDING"
        assert item["delivered_at"] is None
        assert item["rejection_reason"] is None

        assert_unevaluated_study(marram_dunes["study"])

    def test_a_seated_director_and_a_posted_entry_record_their_acting_user(
        self, api: ApiClient, marram_dunes: Dict[str, Any]
    ) -> None:
        """The two rows that carry an actor stamp both take it from the caller.

        "Each entry is stored with `status` `POSTED` and `posted_by_user_id` set
        from the acting `X-User-ID`, and with `reverses_entry_id` null."

        Design: Corner/state_machines/newly_created_rows_start_in_their_declared_initial_states
        """
        entry = marram_dunes["entry"]
        assert entry["status"] == "POSTED"
        assert entry["direction"] == "ACCRUAL"
        assert entry["reverses_entry_id"] is None
        assert entry["posted_by_user_id"] == DECLARANT_USER_ID

        director = marram_dunes["director"]
        assert director["status"] == "SEATED"
        assert director["seat_type"] == SEAT_TYPE_DECLARANT_APPOINTED
        assert director["seated_by_user_id"] == DECLARANT_USER_ID
        assert director["vacated_at"] is None

        association = read_association(api, marram_dunes["association"]["id"])
        assert association["subsidy_receivable_cents"] == 25000
        assert association["budget_forecast_status"] == FORECAST_CURRENT


# ─── Nettlebed: the records review cycle and its terminal ──────────────


@pytest.fixture
def nettlebed(api: ApiClient) -> Dict[str, Any]:
    """Two required items, one of them already delivered once."""
    association = seed_association(
        api,
        name="Nettlebed",
        total_planned_lots=9,
        turnover_threshold_pct=66.67,
        fixed_turnover_date="2027-05-01T00:00:00Z",
        statute_of_repose_years=8,
        reserve_pool_cents=150000,
        reserve_claim_pool_cents=400000,
        declarant_monthly_subsidy_cents=20000,
    )
    case = seed_turnover_case(api, association["id"], total_seats=3)
    warranties = seed_records_item(api, case["id"], "WARRANTIES", required=True)
    permits = seed_records_item(api, case["id"], "PERMITS", required=True)
    return {
        "association": association,
        "case": case,
        "warranties": warranties,
        "permits": permits,
        "committee_headers": make_transition_committee_headers(association["id"]),
    }


class TestRecordsItemCycleAndTerminal:
    """REJECTED is a way station; ACCEPTED is the end of the line."""

    def test_a_rejected_item_may_be_redelivered_and_the_reason_clears(
        self, api: ApiClient, nettlebed: Dict[str, Any]
    ) -> None:
        """The reason recorded on rejection is wiped by the re-delivery.

        "Rejection is not terminal — the declarant may re-deliver, closing the
        cycle `DELIVERED → REJECTED → DELIVERED`."

        Design: Corner/state_machines/records_item_reject_redeliver_cycle_then_accepted_is_terminal
        """
        association_id = nettlebed["association"]["id"]
        item_id = nettlebed["warranties"]["id"]

        delivered = do_deliver_item(api, item_id)
        assert delivered["status"] == "DELIVERED"
        assert_instant(delivered["delivered_at"], DEFAULT_CLOCK_UTC, "delivered_at")

        rejected = do_reject_item(
            api,
            item_id,
            association_id,
            rejection_reason="warranty assignments unsigned",
        )
        assert rejected["status"] == "REJECTED"
        assert rejected["rejection_reason"] == "warranty assignments unsigned"

        redelivered = do_deliver_item(api, item_id)
        assert redelivered["status"] == "DELIVERED"
        assert redelivered["rejection_reason"] is None, (
            "Re-delivery clears any rejection_reason back to null"
        )

    def test_acceptance_is_terminal_and_a_second_accept_is_rejected(
        self, api: ApiClient, nettlebed: Dict[str, Any]
    ) -> None:
        """One of two required items accepted puts completeness at exactly 50.00.

        "The `TransitionCommittee` then either sends `ACCEPT`, legal only from
        `DELIVERED`, which moves the item `DELIVERED → ACCEPTED` and recomputes
        the case's completeness"

        Design: Corner/state_machines/records_item_reject_redeliver_cycle_then_accepted_is_terminal
        """
        association_id = nettlebed["association"]["id"]
        committee = nettlebed["committee_headers"]
        item_id = nettlebed["warranties"]["id"]

        do_deliver_item(api, item_id)
        do_reject_item(
            api,
            item_id,
            association_id,
            rejection_reason="warranty assignments unsigned",
        )
        do_deliver_item(api, item_id)

        accepted = validate_success(
            api.records_item_transition(
                item_id, records_transition_payload(RECORDS_ACTION_ACCEPT), committee
            )
        )
        assert accepted["status"] == "ACCEPTED"

        validate_error(
            api.records_item_transition(
                item_id, records_transition_payload(RECORDS_ACTION_ACCEPT), committee
            ),
            ERR_RECORDS_ITEM_STATE_INVALID,
        )

        case = read_turnover_case(api, nettlebed["case"]["id"])
        assert_pct(
            case["records_transfer_completeness_pct"],
            50.00,
            "records_transfer_completeness_pct",
        )
        rows, _meta = validate_paginated(
            api.list_records_items(nettlebed["case"]["id"], committee)
        )
        permits = next(row for row in rows if row["id"] == nettlebed["permits"]["id"])
        assert permits["status"] == "OUTSTANDING", "The untouched item never moved"


# ─── Oxbow Landing: milestones out of their declared order ─────────────


@pytest.fixture
def oxbow_landing(api: ApiClient) -> Dict[str, Any]:
    """One unbuilt boat ramp and nothing else."""
    association = seed_association(
        api,
        name="Oxbow Landing",
        total_planned_lots=12,
        turnover_threshold_pct=66.67,
        fixed_turnover_date="2027-01-01T00:00:00Z",
        statute_of_repose_years=8,
        reserve_pool_cents=100000,
        reserve_claim_pool_cents=200000,
        declarant_monthly_subsidy_cents=15000,
    )
    component = seed_component(
        api,
        association["id"],
        name="Boat Ramp",
        category="INFRASTRUCTURE",
        replacement_cost_cents=300000,
        useful_life_years=20,
        effective_age_years=0,
        promised_completion_date="2027-01-01T00:00:00Z",
    )
    return {
        "association": association,
        "component": component,
        "committee_headers": make_transition_committee_headers(association["id"]),
    }


class TestMilestoneOrdering:
    """The three milestones form a chain, and skipping a link is refused."""

    def test_tendering_a_deed_on_an_unfinished_component_is_rejected(
        self, api: ApiClient, oxbow_landing: Dict[str, Any]
    ) -> None:
        """DEED_TENDERED demands a build that has already completed.

        "The `Declarant` then records `DEED_TENDERED`, which requires
        `conveyance_status` to be `NOT_CONVEYED` and `build_status` to already be
        `COMPLETE` — tendering a deed on an unfinished component is
        `ERR_COMPONENT_MILESTONE_INVALID`"

        Design: Corner/state_machines/component_milestones_out_of_declared_order_are_rejected
        """
        component_id = oxbow_landing["component"]["id"]

        validate_error(
            api.record_milestone(
                component_id,
                milestone_payload(MILESTONE_DEED_TENDERED),
                DECLARANT_HEADERS,
            ),
            ERR_COMPONENT_MILESTONE_INVALID,
        )

        component = validate_success(
            api.record_milestone(
                component_id,
                milestone_payload(
                    MILESTONE_BUILD_COMPLETE, effective_date="2026-05-05T00:00:00Z"
                ),
                DECLARANT_HEADERS,
            )
        )
        assert component["build_status"] == "COMPLETE"
        assert_instant(
            component["substantial_completion_date"],
            "2026-05-05T00:00:00Z",
            "substantial_completion_date",
        )

    def test_accepting_before_tender_and_rebuilding_are_both_rejected(
        self, api: ApiClient, oxbow_landing: Dict[str, Any]
    ) -> None:
        """The refused second BUILD_COMPLETE cannot overwrite the completion date.

        "A milestone that is not legal from the component's current posture is
        `ERR_COMPONENT_MILESTONE_INVALID`."

        Design: Corner/state_machines/component_milestones_out_of_declared_order_are_rejected
        """
        component_id = oxbow_landing["component"]["id"]
        committee = oxbow_landing["committee_headers"]

        do_build_complete(api, component_id, "2026-05-05T00:00:00Z")

        validate_error(
            api.record_milestone(
                component_id,
                milestone_payload(MILESTONE_CONVEYANCE_ACCEPTED),
                committee,
            ),
            ERR_COMPONENT_MILESTONE_INVALID,
        )
        validate_error(
            api.record_milestone(
                component_id,
                milestone_payload(
                    MILESTONE_BUILD_COMPLETE, effective_date="2026-06-06T00:00:00Z"
                ),
                DECLARANT_HEADERS,
            ),
            ERR_COMPONENT_MILESTONE_INVALID,
        )

        rows, _meta = validate_paginated(
            api.list_components(oxbow_landing["association"]["id"], committee)
        )
        component = rows[0]
        assert_instant(
            component["substantial_completion_date"],
            "2026-05-05T00:00:00Z",
            "substantial_completion_date",
        )
        assert component["conveyance_status"] == "NOT_CONVEYED"
        assert component["conveyed_at"] is None


# ─── Pemberly Row: closing the same sale twice ─────────────────────────


@pytest.fixture
def pemberly_row(api: ApiClient) -> Dict[str, Any]:
    """A four-lot declaration with one platted lot still unsold."""
    association = seed_association(
        api,
        name="Pemberly Row",
        total_planned_lots=4,
        turnover_threshold_pct=66.67,
        fixed_turnover_date="2027-01-01T00:00:00Z",
        statute_of_repose_years=8,
        reserve_pool_cents=100000,
        reserve_claim_pool_cents=200000,
        declarant_monthly_subsidy_cents=10000,
    )
    lot = seed_lot(api, association["id"], "P-001")
    return {
        "association": association,
        "lot": lot,
        "committee_headers": make_transition_committee_headers(association["id"]),
    }


class TestClosingASaleIsNotIdempotent:
    """The second closing is a state error, not a silent no-op."""

    def test_the_second_close_is_refused_and_moves_no_arithmetic(
        self, api: ApiClient, pemberly_row: Dict[str, Any]
    ) -> None:
        """A later closing_date cannot overwrite the recorded one.

        "Closing a sale moves a lot into `CLOSED` from either `UNSOLD` or
        `UNDER_CONTRACT` — both edges behave identically and take the same
        `closing_date` from the payload — and is refused with
        `ERR_LOT_STATE_INVALID` when the lot is already `CLOSED`."

        Design: Corner/state_machines/lot_close_sale_is_not_idempotent_and_the_second_call_is_rejected
        """
        association_id = pemberly_row["association"]["id"]
        committee = pemberly_row["committee_headers"]
        lot_id = pemberly_row["lot"]["id"]

        closed = do_close_sale(api, lot_id, "2026-04-10T00:00:00Z")
        assert closed["sale_status"] == "CLOSED"

        association = read_association(api, association_id)
        assert association["sold_lot_count"] == 1
        assert_pct(association["sold_lot_pct"], 25.00, "sold_lot_pct")
        version_after_close = association["version"]

        validate_error(
            api.close_lot_sale(
                lot_id, close_sale_payload("2026-05-11T00:00:00Z"), DECLARANT_HEADERS
            ),
            ERR_LOT_STATE_INVALID,
        )

        rows, _meta = validate_paginated(api.list_lots(association_id, committee))
        assert_instant(rows[0]["closing_date"], "2026-04-10T00:00:00Z", "closing_date")

        unchanged = read_association(api, association_id)
        assert unchanged["sold_lot_count"] == 1
        assert_pct(unchanged["sold_lot_pct"], 25.00, "sold_lot_pct")
        assert unchanged["version"] == version_after_close, (
            "A refused closing advances no version"
        )


# ─── Quillon Ridge: rescission preconditions ──────────────────────────


@pytest.fixture
def quillon_ridge(api: ApiClient) -> Dict[str, Any]:
    """A certified case holding one appointed and one owner-elected seat."""
    association = seed_association(
        api,
        name="Quillon Ridge",
        total_planned_lots=6,
        turnover_threshold_pct=66.67,
        fixed_turnover_date="2026-07-01T00:00:00Z",
        statute_of_repose_years=8,
        reserve_pool_cents=100000,
        reserve_claim_pool_cents=200000,
        declarant_monthly_subsidy_cents=12000,
    )
    case = seed_turnover_case(api, association["id"], total_seats=3)
    do_certify_trigger(api, case["id"], association["id"], TRIGGER_BASIS_FIXED_DATE)
    appointed = seed_declarant_appointed_director(
        api, case["id"], full_name="Rae Villalobos"
    )
    elected = seed_owner_elected_director(api, case["id"], full_name="Sami Okonkwo")
    return {
        "association": association,
        "case": case,
        "appointed": appointed,
        "elected": elected,
        "committee_headers": make_transition_committee_headers(association["id"]),
    }


class TestRescissionPreconditions:
    """Only a SEATED owner-elected director can be rescinded, and only once."""

    def test_rescission_vacates_the_seat_and_keeps_the_ledger_balanced(
        self, api: ApiClient, quillon_ridge: Dict[str, Any]
    ) -> None:
        """One of three seats returns to the vacant pool with a stamped vacated_at.

        "Rescission sets `status` to `RESCINDED`, stamps `vacated_at`, decrements
        `owner_elected_seats` by one and increments `vacant_seats` by one so the
        seat ledger still balances"

        Design: Corner/state_machines/rescinding_a_rescinded_or_declarant_appointed_seat_is_rejected
        """
        rescinded = do_rescind_director(api, quillon_ridge["elected"]["id"])
        assert rescinded["status"] == "RESCINDED"
        assert_instant(rescinded["vacated_at"], DEFAULT_CLOCK_UTC, "vacated_at")

        case = read_turnover_case(api, quillon_ridge["case"]["id"])
        assert_seat_ledger(
            case,
            declarant_appointed=1,
            owner_elected=0,
            vacant=2,
            total_seats=3,
        )
        assert case["owner_elected_seats_required"] == 2, (
            "Two thirds of a three-seat board, rounded up, is two seats"
        )
        assert case["governance_status"] == "ELECTION_CALLED"

    def test_a_rescinded_seat_and_an_appointed_seat_both_refuse_rescission(
        self, api: ApiClient, quillon_ridge: Dict[str, Any]
    ) -> None:
        """The same error covers the vacated seat and the declarant's own seat.

        "The `ElectionInspector` may rescind a director, which is legal only when
        that director's `status` is `SEATED` and only when the `seat_type` is
        `OWNER_ELECTED` — rescinding a resigned director, or an appointed one, is
        `ERR_DIRECTOR_STATE_INVALID`."

        Design: Corner/state_machines/rescinding_a_rescinded_or_declarant_appointed_seat_is_rejected
        """
        elected_id = quillon_ridge["elected"]["id"]
        appointed_id = quillon_ridge["appointed"]["id"]

        do_rescind_director(api, elected_id)

        validate_error(
            api.rescind_director(elected_id, INSPECTOR_HEADERS),
            ERR_DIRECTOR_STATE_INVALID,
        )
        validate_error(
            api.rescind_director(appointed_id, INSPECTOR_HEADERS),
            ERR_DIRECTOR_STATE_INVALID,
        )

        rows, _meta = validate_paginated(
            api.list_directors(
                quillon_ridge["case"]["id"], quillon_ridge["committee_headers"]
            )
        )
        appointed = next(row for row in rows if row["id"] == appointed_id)
        assert appointed["status"] == "SEATED", "The refused rescission moved nothing"
        assert appointed["vacated_at"] is None

        case = read_turnover_case(api, quillon_ridge["case"]["id"])
        assert_seat_ledger(
            case,
            declarant_appointed=1,
            owner_elected=0,
            vacant=2,
            total_seats=3,
        )


# ─── Wychwood: issuing an audit report twice ──────────────────────────


@pytest.fixture
def wychwood(api: ApiClient) -> Dict[str, Any]:
    """One in-window accrual and a first-quarter engagement over it."""
    association = seed_association(
        api,
        name="Wychwood",
        total_planned_lots=15,
        turnover_threshold_pct=66.67,
        fixed_turnover_date="2027-01-01T00:00:00Z",
        statute_of_repose_years=8,
        reserve_pool_cents=100000,
        reserve_claim_pool_cents=200000,
        declarant_monthly_subsidy_cents=30000,
    )
    seed_subsidy_entry(api, association["id"], "ACCRUAL", 30000, "2026-02")
    engagement = seed_audit_engagement(
        api, association["id"], "2026-01-01T00:00:00Z", "2026-03-31T00:00:00Z"
    )
    return {
        "association": association,
        "engagement": engagement,
        "committee_headers": make_transition_committee_headers(association["id"]),
    }


class TestAuditIssuanceIsOnce:
    """ISSUED is terminal, and the snapshot it froze stays frozen."""

    def test_reissuing_an_issued_engagement_is_rejected_and_the_snapshot_holds(
        self, api: ApiClient, wychwood: Dict[str, Any]
    ) -> None:
        """A later in-window accrual drifts the delta but cannot reopen the report.

        "Issuing the report — legal only from `ENGAGED`, otherwise
        `ERR_AUDIT_NOT_ISSUABLE` — moves the engagement `ENGAGED → ISSUED`,
        records `issued_by_user_id`, and freezes the in-window balance."

        Design: Corner/state_machines/issuing_an_already_issued_audit_engagement_is_rejected
        """
        association_id = wychwood["association"]["id"]
        engagement_id = wychwood["engagement"]["id"]

        issued = do_issue_engagement(api, engagement_id)
        assert issued["status"] == "ISSUED"
        assert issued["audited_receivable_snapshot_cents"] == 30000
        assert issued["unreconciled_delta_cents"] == 0
        assert issued["finding_status"] == FINDING_CLEAN

        seed_subsidy_entry(api, association_id, "ACCRUAL", 25000, "2026-03")

        association = read_association(api, association_id)
        assert association["subsidy_receivable_cents"] == 55000

        validate_error(
            api.issue_audit_engagement(engagement_id, AUDITOR_HEADERS),
            ERR_AUDIT_NOT_ISSUABLE,
        )

        rows, _meta = validate_paginated(
            api.list_audit_engagements(association_id, wychwood["committee_headers"])
        )
        engagement = next(row for row in rows if row["id"] == engagement_id)
        assert engagement["status"] == "ISSUED"
        assert engagement["audited_receivable_snapshot_cents"] == 30000, (
            "That snapshot is frozen once and never recomputed"
        )
        assert engagement["unreconciled_delta_cents"] == 25000
        assert engagement["finding_status"] == FINDING_EXCEPTION_NOTED


# ─── Yarrow Fields: an adopted study is closed for business ───────────


@pytest.fixture
def yarrow_fields(api: ApiClient) -> Dict[str, Any]:
    """A cash-flow study evaluated and adopted against a funded pool."""
    association = seed_association(
        api,
        name="Yarrow Fields",
        total_planned_lots=18,
        turnover_threshold_pct=66.67,
        fixed_turnover_date="2027-01-01T00:00:00Z",
        statute_of_repose_years=8,
        reserve_pool_cents=1200000,
        reserve_claim_pool_cents=400000,
        declarant_monthly_subsidy_cents=20000,
    )
    study = seed_reserve_study(
        api,
        association["id"],
        FUNDING_METHOD_CASH_FLOW,
        planned_annual_contribution_cents=700000,
        projected_annual_expenditure_cents=500000,
    )
    do_recompute_study(api, study["id"], association["id"], FUNDING_METHOD_CASH_FLOW)
    adopted = do_adopt_study(api, study["id"], association["id"])
    return {
        "association": association,
        "study": adopted,
        "committee_headers": make_transition_committee_headers(association["id"]),
    }


class TestAdoptedStudyIsFrozen:
    """Both study actions are DRAFT-only, so adoption closes the entity."""

    def test_recomputing_an_adopted_study_under_another_method_is_rejected(
        self, api: ApiClient, yarrow_fields: Dict[str, Any]
    ) -> None:
        """The adopted verdict survives an attempt to re-evaluate it.

        "the committee sends `RECOMPUTE` with a `method`, legal only while the
        study is `DRAFT` (otherwise `ERR_NOT_IN_DRAFT`) and requiring the
        `method` in the payload (otherwise `ERR_INVALID_REQUEST`)"

        Design: Corner/state_machines/reserve_study_recompute_and_adopt_after_adoption_are_rejected
        """
        committee = yarrow_fields["committee_headers"]
        study_id = yarrow_fields["study"]["id"]
        assert yarrow_fields["study"]["status"] == "ADOPTED"

        validate_error(
            api.reserve_study_action(
                study_id,
                study_action_payload(
                    STUDY_ACTION_RECOMPUTE,
                    method=FUNDING_METHOD_COMPONENT_FULL_FUNDING,
                ),
                committee,
            ),
            ERR_NOT_IN_DRAFT,
        )

        rows, meta = validate_paginated(
            api.list_reserve_studies(
                yarrow_fields["association"]["id"], committee, {"status": "ADOPTED"}
            )
        )
        assert meta["total_count"] == 1
        assert_study_evaluation(
            rows[0],
            evaluated_method=FUNDING_METHOD_CASH_FLOW,
            verdict=ADEQUACY_ADEQUATE,
            recommendation=700000,
            component_count=0,
            fully_funded_balance=0,
            percent_funded=0.00,
            min_projected_balance=1200000,
        )

    def test_adopting_an_adopted_study_a_second_time_is_rejected(
        self, api: ApiClient, yarrow_fields: Dict[str, Any]
    ) -> None:
        """The baseline cannot be re-adopted to supersede itself.

        "`ADOPT` is legal only while the study is `DRAFT`, else
        `ERR_NOT_IN_DRAFT`, and only once an evaluation has actually run"

        Design: Corner/state_machines/reserve_study_recompute_and_adopt_after_adoption_are_rejected
        """
        committee = yarrow_fields["committee_headers"]
        study_id = yarrow_fields["study"]["id"]

        validate_error(
            api.reserve_study_action(
                study_id, study_action_payload(STUDY_ACTION_ADOPT, method=None), committee
            ),
            ERR_NOT_IN_DRAFT,
        )

        rows, meta = validate_paginated(
            api.list_reserve_studies(yarrow_fields["association"]["id"], committee)
        )
        assert meta["total_count"] == 1, "No second study was ever opened"
        assert rows[0]["status"] == "ADOPTED"
        assert rows[0]["funding_method"] == FUNDING_METHOD_CASH_FLOW


# ─── Zephyr Glen: reversal is available exactly once ──────────────────


@pytest.fixture
def zephyr_glen(api: ApiClient) -> Dict[str, Any]:
    """Three posted entries across two periods."""
    association = seed_association(
        api,
        name="Zephyr Glen",
        total_planned_lots=14,
        turnover_threshold_pct=66.67,
        fixed_turnover_date="2027-01-01T00:00:00Z",
        statute_of_repose_years=8,
        reserve_pool_cents=100000,
        reserve_claim_pool_cents=200000,
        declarant_monthly_subsidy_cents=50000,
    )
    january_accrual = seed_subsidy_entry(
        api, association["id"], "ACCRUAL", 50000, "2026-01"
    )
    january_payment = seed_subsidy_entry(
        api, association["id"], "PAYMENT", 30000, "2026-01"
    )
    february_accrual = seed_subsidy_entry(
        api, association["id"], "ACCRUAL", 40000, "2026-02"
    )
    return {
        "association": association,
        "january_accrual": january_accrual,
        "january_payment": january_payment,
        "february_accrual": february_accrual,
        "committee_headers": make_transition_committee_headers(association["id"]),
    }


class TestReversalIsAvailableOnce:
    """Neither the reversed target nor its mirror can be reversed again."""

    def test_a_reversed_entry_and_its_mirror_both_refuse_a_second_reversal(
        self, api: ApiClient, zephyr_glen: Dict[str, Any]
    ) -> None:
        """One reversal returns the balance to 20,000 and leaves four rows behind.

        "the target must have `status` `POSTED`, a `direction` of `ACCRUAL` or
        `PAYMENT`, and a null `reverses_entry_id` — a mirror is never itself
        reversible, and any of those three failures is
        `ERR_SUBSIDY_ENTRY_ALREADY_REVERSED`."

        Design: Corner/state_machines/reversing_a_reversed_entry_or_a_reversal_mirror_is_rejected
        """
        association_id = zephyr_glen["association"]["id"]
        committee = zephyr_glen["committee_headers"]
        target_id = zephyr_glen["february_accrual"]["id"]

        before = read_association(api, association_id)
        assert before["subsidy_receivable_cents"] == 60000

        reversed_target = do_reverse_entry(
            api, target_id, reason="posted against the wrong period"
        )
        assert reversed_target["id"] == target_id
        assert reversed_target["status"] == "REVERSED"

        mirrors, mirror_meta = validate_paginated(
            api.list_subsidy_entries(committee, {"reverses_entry_id": target_id})
        )
        assert mirror_meta["total_count"] == 1
        mirror = mirrors[0]
        assert mirror["direction"] == "REVERSAL"
        assert mirror["amount_cents"] == 40000
        assert mirror["period_month"] == "2026-02"
        assert mirror["status"] == "POSTED"

        after = read_association(api, association_id)
        assert after["subsidy_receivable_cents"] == 20000

        validate_error(
            api.reverse_subsidy_entry(
                target_id,
                reversal_payload("posted against the wrong period"),
                DECLARANT_HEADERS,
            ),
            ERR_SUBSIDY_ENTRY_ALREADY_REVERSED,
        )
        validate_error(
            api.reverse_subsidy_entry(
                mirror["id"],
                reversal_payload("the mirror itself looks wrong"),
                DECLARANT_HEADERS,
            ),
            ERR_SUBSIDY_ENTRY_ALREADY_REVERSED,
        )

        rows, meta = validate_paginated(
            api.list_subsidy_entries(committee, {"association_id": association_id})
        )
        assert meta["total_count"] == 4, "The two refusals created no further mirror"
        by_id = {row["id"]: row for row in rows}
        assert by_id[zephyr_glen["january_accrual"]["id"]]["status"] == "POSTED"
        assert by_id[zephyr_glen["january_payment"]["id"]]["status"] == "POSTED"

        unchanged = read_association(api, association_id)
        assert unchanged["subsidy_receivable_cents"] == 20000


# ─── Bracken Hollow: a withdrawn claim is closed forever ──────────────


@pytest.fixture
def bracken_hollow(api: ApiClient) -> Dict[str, Any]:
    """A conveyed component with one claim still under investigation."""
    association = seed_association(
        api,
        name="Bracken Hollow",
        total_planned_lots=13,
        turnover_threshold_pct=66.67,
        fixed_turnover_date="2027-01-01T00:00:00Z",
        statute_of_repose_years=8,
        reserve_pool_cents=100000,
        reserve_claim_pool_cents=500000,
        declarant_monthly_subsidy_cents=20000,
    )
    component = seed_component(
        api,
        association["id"],
        name="Retention Pond Liner",
        category="INFRASTRUCTURE",
        replacement_cost_cents=600000,
        useful_life_years=20,
        effective_age_years=2,
        promised_completion_date="2024-01-01T00:00:00Z",
    )
    do_build_complete(api, component["id"], "2024-01-01T00:00:00Z")
    do_deed_tendered(api, component["id"])
    validate_success(
        api.record_milestone(
            component["id"],
            milestone_payload(MILESTONE_CONVEYANCE_ACCEPTED),
            make_transition_committee_headers(association["id"]),
        )
    )
    claim = seed_defect_claim(
        api,
        association["id"],
        component["id"],
        defect_summary="Pond liner seams separating along the north bank",
        repair_cost_estimate_cents=150000,
        diminution_value_cents=90000,
    )
    return {
        "association": association,
        "component": component,
        "claim": claim,
        "committee_headers": make_transition_committee_headers(association["id"]),
    }


class TestWithdrawnClaimIsTerminal:
    """Withdrawal from INVESTIGATING releases nothing and admits nothing after."""

    def test_withdrawing_an_unreserved_claim_moves_no_money(
        self, api: ApiClient, bracken_hollow: Dict[str, Any]
    ) -> None:
        """The eight-year deadline was computed, but no reserve was ever committed.

        "The committee may abandon a claim with `WITHDRAW`, legal from
        `INVESTIGATING`, `NOTICED`, `REJECTED_BY_DEVELOPER` or `RESERVED`; the
        claim moves to `WITHDRAWN`, and the same compensating release runs when
        the claim was `RESERVED` while a withdrawal from `INVESTIGATING` (or any
        other unreserved status) moves no money at all."

        Design: Corner/state_machines/withdrawn_claim_is_terminal_and_rejects_every_further_action
        """
        association_id = bracken_hollow["association"]["id"]
        claim = bracken_hollow["claim"]
        assert claim["status"] == "INVESTIGATING"
        assert_instant(
            claim["repose_deadline"], "2032-01-01T00:00:00Z", "repose_deadline"
        )

        withdrawn = do_claim_withdraw(api, claim["id"], association_id)
        assert withdrawn["status"] == "WITHDRAWN"
        assert withdrawn["reserved_amount_cents"] == 0
        assert withdrawn["valuation_basis"] is None

        association = read_association(api, association_id)
        assert association["reserve_claim_committed_cents"] == 0
        assert association["reserve_claim_available_cents"] == 500000
        assert_claim_pool_conserved(association)

    def test_every_further_action_on_a_withdrawn_claim_is_rejected(
        self, api: ApiClient, bracken_hollow: Dict[str, Any]
    ) -> None:
        """Notice, reserve, a second withdrawal and the declarant's rejection all bounce.

        "Any claim action attempted from a status its edge does not allow is
        `ERR_CLAIM_STATE_INVALID`."

        Design: Corner/state_machines/withdrawn_claim_is_terminal_and_rejects_every_further_action
        """
        association_id = bracken_hollow["association"]["id"]
        committee = bracken_hollow["committee_headers"]
        claim_id = bracken_hollow["claim"]["id"]

        do_claim_withdraw(api, claim_id, association_id)

        for payload, headers in (
            (claim_action_payload(CLAIM_ACTION_NOTICE), committee),
            (
                claim_action_payload(
                    CLAIM_ACTION_RESERVE, valuation_basis=VALUATION_BASIS_REPAIR_COST
                ),
                committee,
            ),
            (claim_action_payload(CLAIM_ACTION_WITHDRAW), committee),
            (claim_action_payload(CLAIM_ACTION_REJECT), DECLARANT_HEADERS),
        ):
            validate_error(
                api.defect_claim_action(claim_id, payload, headers),
                ERR_CLAIM_STATE_INVALID,
            )

        claim = validate_success(api.get_defect_claim(claim_id, committee))
        assert claim["status"] == "WITHDRAWN"
        assert claim["reserved_amount_cents"] == 0
        assert claim["valuation_basis"] is None

        association = read_association(api, association_id)
        assert association["reserve_claim_committed_cents"] == 0
        assert association["reserve_claim_available_cents"] == 500000
