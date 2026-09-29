"""
Cascades that propagate several causal levels away from the request that starts
them: a demolition run whose execution ends up parking an unrelated acquisition
packet, and a compliance sweep whose reverter ends up suspending a third party's
application.

Both scenarios are driven from the fixed logical clock start of 2026-08-01.
"""

from test_helpers import (
    CLERK_1,
    DISP_1,
    INTAKE_1,
    INV_1,
    assert_ledger_identity,
    assert_same_instant,
    factories,
    fixtures,
    get_success_data,
    validate_paginated,
    validate_success,
)

CLOCK_START = "2026-08-01T00:00:00Z"

# ─── the demolition-run cascade ──────────────────────────────────────────────
FUND_AUTHORIZED_CENTS = 1600000
RESERVE_FLOOR_CENTS = 80000
ACQUISITION_TITLE_FEE_CENTS = 10000
AVAILABLE_BEFORE_RUN_CENTS = 1590000
RUN_BUDGET_CENTS = 1590000
PROVISIONAL_CAP_CENTS = 1479069
DEMOLITION_ESTIMATE_CENTS = 1427611
ADMIN_FEE_CENTS = 107071
TOTAL_COMMITTED_CENTS = 1534682
AVAILABLE_AFTER_RUN_CENTS = 55318
DEMOLITION_WINDOW_END = "2026-09-15T00:00:00Z"

# ─── the sweep cascade ───────────────────────────────────────────────────────
PARCEL_AREA_SQFT = 8500
ASSESSED_VALUE_CENTS = 1000000
PRE_ACQUISITION_DELINQUENCY_CENTS = 2000000
RFP_QUOTE_CENTS = 900000
PERFORMANCE_DEADLINE = "2026-09-01T00:00:00Z"
CURE_DEADLINE = "2026-11-30T00:00:00Z"
FIRST_SWEEP_AT = "2026-09-02T00:00:00Z"
SECOND_SWEEP_AT = "2026-12-01T00:00:00Z"


def _planned_run_over_one_candidate(api):
    """
    A grant funding one acquired, quiet-titled grade F parcel that qualifies for
    demolition, a second registry parcel whose packet is left in due diligence,
    and a run planned for the whole available balance.
    """
    funding_source = fixtures.create_funding_source(
        api,
        name="Blight Fund",
        source_type="GRANT",
        authorized_cents=FUND_AUTHORIZED_CENTS,
        restriction="ANY",
        expires_on="2029-12-31T00:00:00Z",
    )
    candidate = fixtures.create_property(
        api,
        address="70 Hollis St",
        situs_ward=7,
        lot_area_sqft=3000,
        assessed_value_cents=150000,
        structure_present=True,
        structure_condition_grade="F",
        vacancy_months=12,
    )
    closed_packet = fixtures.acquire_property(
        api,
        candidate["id"],
        funding_source["id"],
        channel="DONATION",
        offer_price_cents=0,
        title_search_fee_cents=ACQUISITION_TITLE_FEE_CENTS,
        donor_name="Hollis Street Trust",
    )
    action = fixtures.open_title_action(
        api, candidate["id"], action_type="TAX_DEED_CONFIRMATION"
    )
    fixtures.adjudicate_title_action(api, action["id"], "CLEARED")

    # A second parcel whose packet never reaches the board, so it commits
    # nothing and simply waits in DUE_DILIGENCE on the same source.
    other = fixtures.create_property(
        api,
        address="71 Hollis St",
        situs_ward=7,
        lot_area_sqft=4000,
        assessed_value_cents=160000,
        structure_present=False,
        structure_condition_grade="C",
        vacancy_months=4,
    )
    open_payload = factories.without(
        factories.acquisition_packet_payload(
            other["id"],
            funding_source["id"],
            channel="NEGOTIATED_PURCHASE",
            offer_price_cents=25000,
            title_search_fee_cents=5000,
        ),
        "donor_name",
    )
    pending_packet = get_success_data(
        api.create_acquisition_packet(open_payload, INTAKE_1)
    )

    before = fixtures.read_funding_source(api, funding_source["id"])
    run = fixtures.plan_demolition_run(
        api, funding_source["id"], RUN_BUDGET_CENTS
    )
    return {
        "funding_source": funding_source,
        "candidate": candidate,
        "closed_packet": closed_packet,
        "other": other,
        "pending_packet": pending_packet,
        "available_before": before["available_cents"],
        "run": run,
    }


def _awarded_parcel_with_a_third_party_application(api):
    """
    One parcel carrying a pre-acquisition delinquency, awarded to buyer A under
    an armed reverter, while buyer C's application on the same parcel is still
    sitting in SUBMITTED.
    """
    funding_source = fixtures.create_acquisition_funding_source(api)
    prop = fixtures.create_property(
        api,
        address="80 Ivory Ct",
        situs_ward=1,
        lot_area_sqft=PARCEL_AREA_SQFT,
        assessed_value_cents=ASSESSED_VALUE_CENTS,
        structure_present=True,
        structure_condition_grade="C",
        vacancy_months=8,
    )
    fixtures.post_tax_roll(
        api,
        prop["id"],
        delinquent_tax_balance_cents=PRE_ACQUISITION_DELINQUENCY_CENTS,
        tax_year=2025,
    )
    fixtures.acquire_property(
        api,
        prop["id"],
        funding_source["id"],
        channel="DONATION",
        offer_price_cents=0,
        title_search_fee_cents=20000,
        donor_name="Ivory Court Trust",
    )
    action = fixtures.open_title_action(api, prop["id"])
    fixtures.adjudicate_title_action(api, action["id"], "CLEARED")
    fixtures.list_parcel(api, prop["id"])

    buyer_a = fixtures.create_developer_applicant(
        api,
        legal_name="Anvil Development Group",
        contact_email="rfp@anvil-dev.example",
    )
    buyer_c = fixtures.create_developer_applicant(
        api,
        legal_name="Ivory Court Ventures",
        contact_email="rfp@ivory-ventures.example",
    )

    third_party = fixtures.draft_application(
        api,
        prop["id"],
        buyer_c["id"],
        program="DEVELOPER_RFP",
        proposed_use="Contractor yard and offices",
        offer_price_cents=RFP_QUOTE_CENTS,
    )
    fixtures.submit_application(api, third_party["id"], buyer_c["id"])

    winner = fixtures.draft_application(
        api,
        prop["id"],
        buyer_a["id"],
        program="DEVELOPER_RFP",
        proposed_use="Twelve-unit infill apartment building",
        offer_price_cents=RFP_QUOTE_CENTS,
    )
    fixtures.submit_application(api, winner["id"], buyer_a["id"])
    fixtures.screen_application(api, winner["id"])
    fixtures.recommend_application(api, winner["id"])
    fixtures.board_decide(api, winner["id"], "APPROVE")
    agreement = fixtures.execute_agreement(
        api,
        winner["id"],
        performance_deadline=PERFORMANCE_DEADLINE,
        milestone_count=2,
        reverter_clause_active=True,
        abatement_years=3,
        discharge_mode="STATUTORY",
        projected_improved_value_cents=10000000,
    )
    return {
        "funding_source": funding_source,
        "property": prop,
        "buyer_a": buyer_a,
        "buyer_c": buyer_c,
        "winner": winner,
        "third_party": third_party,
        "agreement": agreement,
    }


def test_run_execution_creates_one_demolition_order_at_the_stored_estimate(api):
    """Executing a planned run turns each surviving selection into a SCHEDULED demolition order with no contractor, a 45-day window and the estimate frozen at allocation.

    If at least one selected parcel survives, the run moves `PLANNED → EXECUTED` and, walking the survivors in the stored allocation order, creates one maintenance order per parcel: `work_type` `DEMOLITION`, `contractor_id` left null so the work can be bid out afterwards, `funding_source_id` taken from the run, `demolition_run_id` pointing back at the run, a window opening at the current instant and closing 45 days later, `estimated_cost_cents` equal to the estimate stored during allocation, and status `SCHEDULED`.

    Design: Difficulty/transitive_cascade/demolition_run_execute_depth_four_funding_cascade
    """
    bundle = _planned_run_over_one_candidate(api)
    run = bundle["run"]
    assert bundle["available_before"] == AVAILABLE_BEFORE_RUN_CENTS
    assert run["provisional_cap_cents"] == PROVISIONAL_CAP_CENTS
    assert run["properties_selected_count"] == 1
    assert run["selected_property_ids"] == [bundle["candidate"]["id"]]
    assert run["committed_subtotal_cents"] == DEMOLITION_ESTIMATE_CENTS

    executed = validate_success(api.execute_demolition_run(run["id"], INV_1), 200)
    assert executed["status"] == "EXECUTED"
    assert executed["orders_created_count"] == 1
    assert executed["dropped_property_ids"] == []
    assert_same_instant(executed["executed_at"], CLOCK_START)
    assert executed["total_committed_cents"] == TOTAL_COMMITTED_CENTS

    orders, meta = validate_paginated(
        api.list_maintenance_orders(INV_1, {"demolition_run_id": run["id"]})
    )
    assert meta["total_count"] == 1
    order = orders[0]
    assert order["property_id"] == bundle["candidate"]["id"]
    assert order["work_type"] == "DEMOLITION"
    assert order["status"] == "SCHEDULED"
    assert order["contractor_id"] is None
    assert order["funding_source_id"] == bundle["funding_source"]["id"]
    assert order["demolition_run_id"] == run["id"]
    assert_same_instant(order["window_start"], CLOCK_START)
    assert_same_instant(order["window_end"], DEMOLITION_WINDOW_END)
    assert order["estimated_cost_cents"] == DEMOLITION_ESTIMATE_CENTS
    assert order["actual_cost_cents"] is None


def test_run_execution_commits_order_and_fee_and_constrains_the_source(api):
    """The created order's estimate and the run's administrative fee are both committed against the source, and the resulting available balance below the reserve floor flips it to CONSTRAINED.

    This is the head of a four-link cascade: each created order commits its estimate to the source's `committed_cents`; the run's `admin_fee_cents` is committed against the same source; `available_cents` is recomputed and, if it now sits below `reserve_floor_cents`, the source moves `ACTIVE → CONSTRAINED`; and that transition in turn parks every `DUE_DILIGENCE` packet on the source in `ON_HOLD_FUNDING`.

    Design: Difficulty/transitive_cascade/demolition_run_execute_depth_four_funding_cascade
    """
    bundle = _planned_run_over_one_candidate(api)
    source_id = bundle["funding_source"]["id"]

    before = fixtures.read_funding_source(api, source_id)
    assert before["status"] == "ACTIVE"
    assert before["reserve_floor_cents"] == RESERVE_FLOOR_CENTS
    assert before["committed_cents"] == 0
    assert before["disbursed_cents"] == ACQUISITION_TITLE_FEE_CENTS
    assert before["open_run_count"] == 1

    executed = validate_success(
        api.execute_demolition_run(bundle["run"]["id"], INV_1), 200
    )
    assert executed["admin_fee_cents"] == ADMIN_FEE_CENTS
    assert executed["committed_subtotal_cents"] == DEMOLITION_ESTIMATE_CENTS
    assert executed["total_committed_cents"] == TOTAL_COMMITTED_CENTS

    after = validate_success(api.get_funding_source(source_id, INV_1), 200)
    assert after["committed_cents"] == TOTAL_COMMITTED_CENTS
    assert after["disbursed_cents"] == ACQUISITION_TITLE_FEE_CENTS
    assert after["available_cents"] == AVAILABLE_AFTER_RUN_CENTS
    assert after["available_cents"] < after["reserve_floor_cents"]
    assert after["status"] == "CONSTRAINED"
    assert after["open_run_count"] == 0
    assert_ledger_identity(after)


def test_constrained_source_parks_the_unrelated_due_diligence_packet(api):
    """The source flipping to CONSTRAINED parks every acquisition packet still in due diligence on it, even though the executed run never mentioned that packet.

    Whenever a commitment leaves `available_cents` strictly below `reserve_floor_cents`, the source moves `ACTIVE → CONSTRAINED`, and that transition immediately parks every acquisition packet on the source that is still in `DUE_DILIGENCE`: each moves `DUE_DILIGENCE → ON_HOLD_FUNDING` with `hold_reason` set to `FUNDING_SOURCE_CONSTRAINED`.

    Design: Difficulty/transitive_cascade/demolition_run_execute_depth_four_funding_cascade
    """
    bundle = _planned_run_over_one_candidate(api)
    pending_id = bundle["pending_packet"]["id"]

    before = fixtures.read_packet(api, pending_id)
    assert before["status"] == "DUE_DILIGENCE"
    assert before["hold_reason"] is None

    validate_success(api.execute_demolition_run(bundle["run"]["id"], INV_1), 200)

    parked = validate_success(api.get_acquisition_packet(pending_id, INTAKE_1), 200)
    assert parked["status"] == "ON_HOLD_FUNDING"
    assert parked["hold_reason"] == "FUNDING_SOURCE_CONSTRAINED"
    assert parked["committed_cents"] == 0
    assert parked["version"] == before["version"] + 1

    # The packet that already reached its terminal CLOSED state is untouched:
    # only DUE_DILIGENCE packets are parked.
    closed = validate_success(
        api.get_acquisition_packet(bundle["closed_packet"]["id"], INTAKE_1), 200
    )
    assert closed["status"] == "CLOSED"
    assert closed["hold_reason"] is None


def test_second_sweep_reverts_the_agreement_after_the_cure_deadline_lapses(api):
    """The sweep that runs after a lapsed cure deadline reverts the agreement and stamps reverted_at at that instant.

    **Step three** enforces the reverter: every agreement in `CURE_PENDING` whose `cure_deadline` has passed while milestones remain outstanding, and whose `reverter_clause_active` is true, moves `CURE_PENDING → REVERTED` and stamps `reverted_at`; where `reverter_clause_active` is false the agreement is left in `CURE_PENDING` and the sweep merely counts it as waived.

    Design: Difficulty/transitive_cascade/compliance_sweep_reverter_depth_three_cascade
    """
    bundle = _awarded_parcel_with_a_third_party_application(api)
    agreement_id = bundle["agreement"]["id"]
    assert bundle["agreement"]["discharged_tax_cents"] == PRE_ACQUISITION_DELINQUENCY_CENTS
    assert bundle["agreement"]["status"] == "EXECUTED"

    fixtures.set_clock(api, FIRST_SWEEP_AT)
    first_sweep = validate_success(api.run_compliance_sweep(INV_1), 200)
    assert first_sweep["cure_pending_count"] == 1
    assert first_sweep["reverted_count"] == 0
    in_cure = fixtures.read_agreement(api, agreement_id)
    assert in_cure["status"] == "CURE_PENDING"
    assert_same_instant(in_cure["cure_deadline"], CURE_DEADLINE)

    fixtures.set_clock(api, SECOND_SWEEP_AT)
    second_sweep = validate_success(api.run_compliance_sweep(INV_1), 200)
    assert_same_instant(second_sweep["swept_at"], SECOND_SWEEP_AT)
    assert second_sweep["reverted_count"] == 1
    assert second_sweep["waived_count"] == 0
    assert second_sweep["funding_expired_count"] == 0

    reverted = validate_success(
        api.get_development_agreement(agreement_id, CLERK_1), 200
    )
    assert reverted["status"] == "REVERTED"
    assert_same_instant(reverted["reverted_at"], SECOND_SWEEP_AT)
    assert reverted["milestones_completed"] == 0


def test_reverter_returns_the_parcel_reclouds_title_and_suspends_the_third_party(api):
    """Reverting the agreement takes the parcel back, restores the delinquency the agreement discharged, re-clouds the title and parks the other buyer's submitted application.

    The agreement's `reverted_at` is stamped; the parcel moves `CONVEYED → REVERTED`, has its `owner_of_record_applicant_id` cleared to null, has its `delinquent_tax_balance_cents` restored by the `discharged_tax_cents` the agreement had forgiven, and has its `current_blight_score` recomputed with the live variant, while its `lot_area_sqft` returns to the conserved inventory area; the reverter deed re-clouds the title, driving `CLEAR → CLOUDED`; and that re-clouding suspends the parcel's live disposition pipeline — every application on that parcel in `SUBMITTED`, `SCREENED` or `RECOMMENDED` records its current status in `suspended_from_status` and moves to `SUSPENDED_TITLE` — the three routes `SUBMITTED → SUSPENDED_TITLE`, `SCREENED → SUSPENDED_TITLE` and `RECOMMENDED → SUSPENDED_TITLE` — to be restored only by a fresh title clearing, which drives `SUSPENDED_TITLE → SUBMITTED`, `SUSPENDED_TITLE → SCREENED` or `SUSPENDED_TITLE → RECOMMENDED` as described in §3.4.

    Design: Difficulty/transitive_cascade/compliance_sweep_reverter_depth_three_cascade
    """
    bundle = _awarded_parcel_with_a_third_party_application(api)
    property_id = bundle["property"]["id"]

    conveyed = fixtures.read_property(api, property_id)
    assert conveyed["custody_status"] == "CONVEYED"
    assert conveyed["title_status"] == "CLEAR"
    assert conveyed["owner_of_record_applicant_id"] == bundle["buyer_a"]["id"]
    assert conveyed["delinquent_tax_balance_cents"] == 0
    assert (
        conveyed["pre_acquisition_delinquency_cents"]
        == PRE_ACQUISITION_DELINQUENCY_CENTS
    )

    fixtures.set_clock(api, FIRST_SWEEP_AT)
    fixtures.run_compliance_sweep(api)
    fixtures.set_clock(api, SECOND_SWEEP_AT)
    sweep = validate_success(api.run_compliance_sweep(INV_1), 200)
    assert sweep["reverted_count"] == 1
    assert sweep["restored_inventory_sqft"] == PARCEL_AREA_SQFT

    parcel = validate_success(api.get_property(property_id, INV_1), 200)
    assert parcel["custody_status"] == "REVERTED"
    assert parcel["owner_of_record_applicant_id"] is None
    assert parcel["title_status"] == "CLOUDED"
    assert (
        parcel["delinquent_tax_balance_cents"] == PRE_ACQUISITION_DELINQUENCY_CENTS
    )

    summary = fixtures.inventory_summary(api)
    assert summary["inventory_area_sqft"] == PARCEL_AREA_SQFT
    assert summary["conveyed_area_sqft"] == 0
    assert summary["inventory_property_count"] == 1

    third_party = validate_success(
        api.get_disposition_application(bundle["third_party"]["id"], DISP_1), 200
    )
    assert third_party["status"] == "SUSPENDED_TITLE"
    assert third_party["suspended_from_status"] == "SUBMITTED"
    assert third_party["screening_count"] == 0


def test_reverter_bars_the_awarded_buyer_and_leaves_the_award_terminal(api):
    """The reverter counts against the buyer that lost the deed and turns its eligibility standing to BARRED, while its awarded application stays terminal.

    The former buyer pays for it too: its `reverter_count` grows by one, `last_reverter_at` is stamped at the current instant, `recent_reverter_count` is recomputed and its `eligibility_status` becomes `BARRED`, which keeps it out of the market for the whole five-year lookback.

    Design: Difficulty/transitive_cascade/compliance_sweep_reverter_depth_three_cascade
    """
    bundle = _awarded_parcel_with_a_third_party_application(api)
    buyer_a_id = bundle["buyer_a"]["id"]

    before = fixtures.read_applicant(api, buyer_a_id)
    assert before["reverter_count"] == 0
    assert before["recent_reverter_count"] == 0
    assert before["last_reverter_at"] is None
    assert before["eligibility_status"] == "ELIGIBLE"

    fixtures.set_clock(api, FIRST_SWEEP_AT)
    fixtures.run_compliance_sweep(api)
    fixtures.set_clock(api, SECOND_SWEEP_AT)
    sweep = validate_success(api.run_compliance_sweep(INV_1), 200)
    assert sweep["reverted_count"] == 1

    after = validate_success(api.get_applicant(buyer_a_id, DISP_1), 200)
    assert after["reverter_count"] == 1
    assert after["recent_reverter_count"] == 1
    assert_same_instant(after["last_reverter_at"], SECOND_SWEEP_AT)
    assert after["eligibility_status"] == "BARRED"
    assert after["good_standing_count"] == 0

    # The award itself is a terminal application status, so the reverter leaves
    # it alone; only live applications are suspended.
    awarded = validate_success(
        api.get_disposition_application(bundle["winner"]["id"], DISP_1), 200
    )
    assert awarded["status"] == "AWARDED"
    assert awarded["suspended_from_status"] is None

    # The buyer that never won anything is untouched by the other's default.
    other_buyer = fixtures.read_applicant(api, bundle["buyer_c"]["id"])
    assert other_buyer["reverter_count"] == 0
    assert other_buyer["eligibility_status"] == "ELIGIBLE"
