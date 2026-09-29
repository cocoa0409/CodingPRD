"""The money dimension: payout waterfalls, supersession and disbursement."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_payout_statement,
    build_deal,
    build_payout_statement,
    close_booking,
    confirm_booking,
    create_payout_statement_payload,
    engagement_version,
    make_brand_rep_headers,
    place_booking,
    read_engagement,
    review_deliverable_payload,
    schedule_deliverable,
    setup_completed_engagement,
    setup_four_line_engagement,
    submit_deliverable,
    terminate_engagement,
    validate_error,
    validate_paginated,
    validate_success,
)

AGENT = TEST_USERS["talent_agent_headers"]
FINANCE = TEST_USERS["finance_manager_headers"]


def test_payout_rounds_each_line_before_summing_them(api):
    """PRD 3.10: "Each line's `line_value_cents` is then the engagement's
    `binding_fee_cents` multiplied by that line's own `weight` and divided by the
    total weight, rounded half up to whole cents — and the rounding order is pinned:
    **each line is rounded first, and the rounded line values are then summed.**
    `gross_amount_cents` is that sum of rounded line values, and it will generally
    differ slightly from `binding_fee_cents`; that residue is expected and is never
    redistributed across the lines."

    Design: Difficulty/combinatorial_formula/payout_line_rounding_before_sum
    """
    deal = setup_four_line_engagement()
    assert deal["engagement"]["binding_fee_cents"] == 3_001_900

    statement = build_payout_statement(deal["engagement_id"])
    assert_payout_statement(statement)

    assert statement["line_count"] == 4
    assert statement["gross_amount_cents"] == 3_001_901
    assert statement["gross_amount_cents"] != deal["engagement"]["binding_fee_cents"]

    lines = {
        d["id"]: validate_success(api.get_deliverable(d["id"], AGENT))
        for d in deal["deliverables"]
    }
    values = [lines[d["id"]]["line_value_cents"] for d in deal["deliverables"]]
    assert values == [375_238, 375_238, 1_500_950, 750_475]


def test_payout_commission_and_net_follow_the_per_line_rounding(api):
    """PRD 3.10: "`agency_commission_cents` follows the same discipline: each line's
    own rounded `line_value_cents` is multiplied by the athlete's `commission_pct` and
    rounded half up to whole cents, and those per-line commissions are summed."
    PRD 3.10: "`penalty_cents` is the absolute value of the sum of the `amount_cents`
    of every `PENALTY` ledger entry on this engagement, with no time window filter —
    no-show penalties booked at any point in the engagement's life all count.
    `athlete_net_cents` is `gross_amount_cents` less `agency_commission_cents` less
    `penalty_cents`, and `line_count` is the number of lines that entered the
    statement."

    Design: Difficulty/combinatorial_formula/payout_line_rounding_before_sum
    """
    deal = setup_four_line_engagement()

    statement = build_payout_statement(deal["engagement_id"])

    assert statement["agency_commission_cents"] == 450_286
    assert statement["penalty_cents"] == 0
    assert statement["athlete_net_cents"] == 2_551_615

    engagement = read_engagement(deal["engagement_id"])
    assert engagement["settlement_status"] == "INVOICED"


def test_disbursement_settles_the_money_dimension_only(api):
    """PRD 3.10: "Disbursement moves the statement `DRAFT → DISBURSED`, stamps
    `disbursed_at` with the logical clock, appends a `DISBURSEMENT` ledger entry whose
    `amount_cents` is the negative of `athlete_net_cents`, raises the engagement's
    `gross_settled_cents` by the statement's `gross_amount_cents`, and moves the money
    dimension `INVOICED → SETTLED`."
    PRD 3.7: "When the gate passes, the deliverable moves `SUBMITTED → APPROVED` and
    a four-hop cascade runs: because the deliverable became `APPROVED`, the
    engagement's `approved_deliverable_count` increments by 1; if that counter has now
    reached `required_deliverable_count`, the engagement's `contract_status` moves
    `ACTIVE → COMPLETED`; and because `contract_status` became `COMPLETED`, the
    engagement's `settlement_status` moves `UNBILLED → BILLABLE`, opening settlement."

    Design: Difficulty/non_linear_state_machine/engagement_parallel_contract_and_settlement_dimensions
    """
    deal = setup_four_line_engagement()
    statement = build_payout_statement(deal["engagement_id"])

    before = read_engagement(deal["engagement_id"])
    assert before["contract_status"] == "COMPLETED"
    assert before["settlement_status"] == "INVOICED"

    disbursed = validate_success(
        api.disburse_payout_statement(statement["id"], FINANCE), 200
    )
    assert disbursed["status"] == "DISBURSED"

    after = read_engagement(deal["engagement_id"])
    assert after["contract_status"] == "COMPLETED", (
        "the contract dimension does not move when the money dimension does"
    )
    assert after["settlement_status"] == "SETTLED"
    assert after["gross_settled_cents"] == 3_001_901


def test_disbursement_entry_is_excluded_from_the_accrual_sum(api):
    """PRD 2.6: "Disbursement entries are deliberately excluded from that sum;
    disbursed money is tracked separately in `gross_settled_cents`, which is the sum
    of `gross_amount_cents` over that engagement's payout statements whose `status` is
    `DISBURSED`."
    PRD 3.10: "Because disbursement entries are excluded from the accrual sum by
    definition, `accrued_fee_cents` is untouched by it."

    Design: Difficulty/non_linear_state_machine/engagement_parallel_contract_and_settlement_dimensions
    """
    deal = setup_four_line_engagement()
    statement = build_payout_statement(deal["engagement_id"])
    validate_success(api.disburse_payout_statement(statement["id"], FINANCE), 200)

    entries, _meta = validate_paginated(
        api.list_ledger_entries(deal["engagement_id"], FINANCE)
    )
    disbursements = [e for e in entries if e["entry_type"] == "DISBURSEMENT"]
    assert len(disbursements) == 1
    assert disbursements[0]["amount_cents"] == -2_551_615

    engagement = read_engagement(deal["engagement_id"])
    assert engagement["accrued_fee_cents"] == 180_500


def test_payout_with_no_approved_deliverables_is_refused(api):
    """PRD 3.10: "At least one deliverable of the engagement must be `APPROVED`, or
    the request is refused with `ERR_NO_BILLABLE_DELIVERABLES`."
    PRD 3.9: "Settlement is opened fourth. Because the engagement became
    `TERMINATED`, its `settlement_status` moves `UNBILLED → BILLABLE`, so whatever was
    accrued and approved before the termination can still be paid out."

    Design: Difficulty/boundary_precision_check/payout_with_zero_approved_deliverables_empty_set
    """
    deal = build_deal(stage="active", signed_by_reference="CS-2026-0003")
    schedule_deliverable(
        deal["engagement_id"], "SOCIAL_POST", due_date="2026-09-20",
        disclosure_required=False,
    )
    terminate_engagement(deal["engagement_id"], reason_code="BRAND_WITHDRAWAL")

    response = api.create_payout_statement(
        create_payout_statement_payload(
            deal["engagement_id"], engagement_version(deal["engagement_id"])
        ),
        FINANCE,
    )
    validate_error(response, ApiErrorId.ERR_NO_BILLABLE_DELIVERABLES.value, 422)


def test_refused_payout_leaves_the_engagement_billable_with_no_statement(api):
    """PRD 3.9: "Outstanding work is voided third. Every deliverable of this
    engagement whose `status` is `PENDING`, `SUBMITTED` or `REVISION_REQUESTED` is
    voided — the edge fires as `PENDING → VOIDED`, `SUBMITTED → VOIDED` or
    `REVISION_REQUESTED → VOIDED` as appropriate — and for each voided deliverable of
    type `SHOOT` the referenced production slot's `reserved_count` decrements by 1,
    freeing that half-open window for other reservations."
    PRD 3.10: "At least one deliverable of the engagement must be `APPROVED`, or the
    request is refused with `ERR_NO_BILLABLE_DELIVERABLES`."

    Design: Difficulty/boundary_precision_check/payout_with_zero_approved_deliverables_empty_set
    """
    deal = build_deal(stage="active", signed_by_reference="CS-2026-0003")
    deliverable = schedule_deliverable(
        deal["engagement_id"], "SOCIAL_POST", due_date="2026-09-20",
        disclosure_required=False,
    )
    terminate_engagement(deal["engagement_id"], reason_code="BRAND_WITHDRAWAL")

    response = api.create_payout_statement(
        create_payout_statement_payload(
            deal["engagement_id"], engagement_version(deal["engagement_id"])
        ),
        FINANCE,
    )
    validate_error(response, ApiErrorId.ERR_NO_BILLABLE_DELIVERABLES.value, 422)

    engagement = read_engagement(deal["engagement_id"])
    assert engagement["settlement_status"] == "BILLABLE"

    voided = validate_success(api.get_deliverable(deliverable["id"], AGENT))
    assert voided["status"] == "VOIDED"

    rows, _meta = validate_paginated(
        api.list_engagement_payout_statements(deal["engagement_id"], FINANCE)
    )
    assert rows == []


def test_payout_bills_only_the_approved_line(api):
    """PRD 3.10: "The statement's arithmetic is a per-line waterfall over the
    engagement's `APPROVED` deliverables, taken in `created_at` ascending order; the
    deliverable identifier is never consulted for ordering. Deliverables in `PENDING`,
    `SUBMITTED`, `REVISION_REQUESTED` or `VOIDED` are excluded outright."
    PRD 3.10: "Building the statement also writes each line's `line_value_cents` back
    onto the deliverable row itself, so a superseding rebuild overwrites the previous
    figures."

    Design: Corner/calculations/payout_excludes_non_approved_deliverables
    """
    deal = build_deal(
        stage="active",
        opportunity_overrides={"proposed_fee_cents": 200_000, "planned_posts": 2},
        signed_by_reference="CS-C-0002",
    )
    billed = schedule_deliverable(
        deal["engagement_id"], "SOCIAL_POST", due_date="2026-09-20",
        disclosure_required=False,
    )
    dropped = schedule_deliverable(
        deal["engagement_id"], "SOCIAL_POST", due_date="2026-09-21",
        disclosure_required=False,
    )
    submit_deliverable(billed["id"], deal["athlete_id"], "https://cdn.example/f1.jpg")
    submit_deliverable(dropped["id"], deal["athlete_id"], "https://cdn.example/f2.jpg")
    validate_success(
        api.review_deliverable(
            billed["id"], review_deliverable_payload("APPROVE"),
            make_brand_rep_headers(deal["brand_id"]),
        ),
        200,
    )
    terminate_engagement(deal["engagement_id"], reason_code="BRAND_WITHDRAWAL")

    statement = build_payout_statement(deal["engagement_id"])

    assert validate_success(api.get_deliverable(dropped["id"], AGENT))["status"] == "VOIDED"
    assert statement["line_count"] == 1
    assert statement["gross_amount_cents"] == 2_621_400
    assert statement["agency_commission_cents"] == 393_210
    assert statement["athlete_net_cents"] == 2_228_190

    assert validate_success(api.get_deliverable(billed["id"], AGENT))["line_value_cents"] == 2_621_400
    assert validate_success(api.get_deliverable(dropped["id"], AGENT))["line_value_cents"] is None
    assert read_engagement(deal["engagement_id"])["settlement_status"] == "INVOICED"


def test_no_show_penalty_flows_through_to_the_statement(api):
    """PRD 3.10: "`penalty_cents` is the absolute value of the sum of the
    `amount_cents` of every `PENALTY` ledger entry on this engagement, with no time
    window filter — no-show penalties booked at any point in the engagement's life all
    count. `athlete_net_cents` is `gross_amount_cents` less `agency_commission_cents`
    less `penalty_cents`, and `line_count` is the number of lines that entered the
    statement."
    PRD 3.6: "Closing `CONFIRMED → NO_SHOW` writes the `outcome`, increments the
    athlete's `no_show_count` by 1, and appends a `PENALTY` ledger entry whose
    `amount_cents` is the negative of ten percent of the engagement's
    `binding_fee_cents`, rounded half up to whole cents; because that entry was
    appended, the engagement's `accrued_fee_cents` decreases by that amount."

    Design: Corner/calculations/payout_penalty_from_no_show_reduces_athlete_net
    """
    deal = build_deal(stage="active", signed_by_reference="CS-C-0002")
    booking = place_booking(
        deal["engagement_id"], city="Chicago",
        start_at="2026-09-10T14:00:00Z", end_at="2026-09-10T22:00:00Z",
        travel_buffer_hours=12,
    )
    confirm_booking(booking["id"], 100_000)
    close_booking(booking["id"], "NO_SHOW")

    deliverable = schedule_deliverable(
        deal["engagement_id"], "SOCIAL_POST", due_date="2026-09-20",
        disclosure_required=False,
    )
    submit_deliverable(deliverable["id"], deal["athlete_id"], "https://cdn.example/n1.jpg")
    validate_success(
        api.review_deliverable(
            deliverable["id"], review_deliverable_payload("APPROVE"),
            make_brand_rep_headers(deal["brand_id"]),
        ),
        200,
    )

    statement = build_payout_statement(deal["engagement_id"])

    assert statement["gross_amount_cents"] == 2_621_400
    assert statement["agency_commission_cents"] == 393_210
    assert statement["penalty_cents"] == 262_140
    assert statement["athlete_net_cents"] == 1_966_050

    athlete = validate_success(api.get_athlete(deal["athlete_id"], AGENT))
    assert athlete["no_show_count"] == 1
    assert read_engagement(deal["engagement_id"])["accrued_fee_cents"] == -162_140


def test_payout_against_an_unbilled_engagement_reports_the_settlement_state(api):
    """PRD 3.10: "The engagement's `settlement_status` must be `BILLABLE` or
    `INVOICED`; both `UNBILLED` and `SETTLED` are refused with
    `ERR_SETTLEMENT_NOT_BILLABLE`. At least one deliverable of the engagement must be
    `APPROVED`, or the request is refused with `ERR_NO_BILLABLE_DELIVERABLES`."
    PRD 2.8: "Only once all of that passes does the domain layer run, in this order:
    athlete bookability (`ERR_ATHLETE_NOT_BOOKABLE`), opportunity-screened
    (`ERR_OPPORTUNITY_NOT_SCREENED`), term-sheet from-state
    (`ERR_TERM_SHEET_INVALID_STATE`), offer expiry (`ERR_OFFER_EXPIRED`), engagement
    contract-status fitness (`ERR_ENGAGEMENT_NOT_ACTIVE`), engagement terminality for
    countersign and terminate (`ERR_ENGAGEMENT_ALREADY_TERMINAL`), booking from-state
    (`ERR_BOOKING_INVALID_STATE`), deliverable from-state
    (`ERR_DELIVERABLE_INVALID_STATE`), disclosure from-state
    (`ERR_DISCLOSURE_INVALID_STATE`), settlement billability
    (`ERR_SETTLEMENT_NOT_BILLABLE`), payout from-state (`ERR_PAYOUT_INVALID_STATE`),
    renewal window (`ERR_RENEWAL_WINDOW_CLOSED`), segregation of duties
    (`ERR_SEGREGATION_OF_DUTIES`), brand sanction (`ERR_BRAND_SANCTIONED`), disclosure
    compliance (`ERR_DISCLOSURE_NOT_COMPLIANT`), morals-tier downgrade
    (`ERR_MORALS_TIER_DOWNGRADE_FORBIDDEN`), deliverable reference coherence
    (`ERR_BOOKING_ENGAGEMENT_MISMATCH`), shoot-inside-slot-window
    (`ERR_SLOT_WINDOW_VIOLATION`), athlete calendar overlap (`ERR_BOOKING_OVERLAP`),
    slot capacity (`ERR_SLOT_CAPACITY_EXCEEDED`), booking-inside-term
    (`ERR_BOOKING_WINDOW_OUTSIDE_TERM`), exclusivity conflict
    (`ERR_EXCLUSIVITY_CONFLICT`), counter-round limit (`ERR_COUNTER_LIMIT_EXCEEDED`),
    duplicate disclosure (`ERR_DUPLICATE_DISCLOSURE`), fee cap
    (`ERR_FEE_CAP_EXCEEDED`) and finally the billable-set check
    (`ERR_NO_BILLABLE_DELIVERABLES`)."

    Design: Corner/validations/payout_on_unbilled_engagement_returns_settlement_not_billable
    """
    deal = build_deal(stage="active", signed_by_reference="CS-C-0002")

    response = api.create_payout_statement(
        create_payout_statement_payload(
            deal["engagement_id"], engagement_version(deal["engagement_id"])
        ),
        FINANCE,
    )
    validate_error(response, ApiErrorId.ERR_SETTLEMENT_NOT_BILLABLE.value, 409)
    assert response.json()["data"]["error_id"] != ApiErrorId.ERR_NO_BILLABLE_DELIVERABLES.value

    assert read_engagement(deal["engagement_id"])["settlement_status"] == "UNBILLED"
    rows, _meta = validate_paginated(
        api.list_engagement_payout_statements(deal["engagement_id"], FINANCE)
    )
    assert rows == []


def test_disbursing_a_disbursed_statement_is_refused(api):
    """PRD 3.10: "Disbursing a statement requires it to be in `DRAFT`; disbursing one
    already `DISBURSED` or `VOIDED` is refused with `ERR_PAYOUT_INVALID_STATE`."
    PRD 3.10: "Disbursement moves the statement `DRAFT → DISBURSED`, stamps
    `disbursed_at` with the logical clock, appends a `DISBURSEMENT` ledger entry whose
    `amount_cents` is the negative of `athlete_net_cents`, raises the engagement's
    `gross_settled_cents` by the statement's `gross_amount_cents`, and moves the money
    dimension `INVOICED → SETTLED`."

    Design: Corner/errors/disburse_already_disbursed_statement_returns_payout_invalid_state
    """
    deal = setup_completed_engagement(signed_by_reference="CS-C-0002")
    statement = build_payout_statement(deal["engagement_id"])
    validate_success(api.disburse_payout_statement(statement["id"], FINANCE), 200)

    response = api.disburse_payout_statement(statement["id"], FINANCE)
    validate_error(response, ApiErrorId.ERR_PAYOUT_INVALID_STATE.value, 409)

    rows, _meta = validate_paginated(
        api.list_engagement_payout_statements(deal["engagement_id"], FINANCE)
    )
    assert len(rows) == 1
    assert rows[0]["status"] == "DISBURSED"

    engagement = read_engagement(deal["engagement_id"])
    assert engagement["settlement_status"] == "SETTLED"
    assert engagement["gross_settled_cents"] == 2_621_400

    entries, _meta = validate_paginated(
        api.list_ledger_entries(deal["engagement_id"], FINANCE)
    )
    disbursements = [e for e in entries if e["entry_type"] == "DISBURSEMENT"]
    assert len(disbursements) == 1
    assert disbursements[0]["amount_cents"] == -2_228_190


def test_replayed_engagement_version_on_payout_create_is_stale(api):
    """PRD 2.5: "Creating a payout statement (`POST /payout-statements`) likewise
    requires a non-optional `expected_engagement_version` carrying the client's last
    observed engagement `version`. A newer statement legitimately supersedes a
    standing draft statement, so again the guard is not a state check: it forces the
    writer to prove its view of the engagement's settlement figures is current before
    restating them. A mismatch is rejected with `ERR_STALE_ENGAGEMENT_VERSION` (HTTP
    412). A successful create increments the engagement's `version` by 1."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_engagement_version_on_payout_create_returns_412
    """
    deal = setup_completed_engagement(signed_by_reference="CS-C-0002")
    observed_version = engagement_version(deal["engagement_id"])
    first = build_payout_statement(deal["engagement_id"], observed_version)

    response = api.create_payout_statement(
        create_payout_statement_payload(deal["engagement_id"], observed_version), FINANCE
    )
    validate_error(response, ApiErrorId.ERR_STALE_ENGAGEMENT_VERSION.value, 412)

    standing = validate_success(api.get_engagement(deal["engagement_id"], FINANCE))
    assert standing["settlement_status"] == "INVOICED"

    rows, _meta = validate_paginated(
        api.list_engagement_payout_statements(deal["engagement_id"], FINANCE)
    )
    assert len(rows) == 1
    assert rows[0]["id"] == first["id"]
    assert rows[0]["status"] == "DRAFT"


def test_second_payout_with_the_current_version_supersedes_the_draft(api):
    """PRD 3.10: "Building again while already `INVOICED` is a legitimate self-loop
    `INVOICED → INVOICED`: the statement is restated, the standing statement — which
    must be in `DRAFT` — moves `DRAFT → VOIDED`, the replacement is created in
    `DRAFT`, and the money dimension stays at `INVOICED`. A voided statement no longer
    counts toward `gross_settled_cents`. Either way the engagement's `version`
    increments by 1, which is precisely why the next writer's
    `expected_engagement_version` must be refreshed."

    Design: Corner/cross_cutting_complexity_layers/occ_second_payout_with_current_version_supersedes_first_draft
    """
    deal = setup_completed_engagement(signed_by_reference="CS-C-0002")
    first = build_payout_statement(deal["engagement_id"])

    response = api.create_payout_statement(
        create_payout_statement_payload(
            deal["engagement_id"], engagement_version(deal["engagement_id"])
        ),
        FINANCE,
    )
    second = validate_success(response, 201)

    rows, _meta = validate_paginated(
        api.list_engagement_payout_statements(deal["engagement_id"], FINANCE)
    )
    by_id = {row["id"]: row for row in rows}
    assert len(rows) == 2
    assert by_id[first["id"]]["status"] == "VOIDED"
    assert by_id[second["id"]]["status"] == "DRAFT"
    assert second["gross_amount_cents"] == 2_621_400
    assert second["athlete_net_cents"] == 2_228_190

    assert read_engagement(deal["engagement_id"])["settlement_status"] == "INVOICED"
