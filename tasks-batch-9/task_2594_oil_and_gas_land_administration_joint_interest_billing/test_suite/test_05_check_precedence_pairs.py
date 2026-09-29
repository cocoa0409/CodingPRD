"""Requests that break two rules at once, and which answer the caller is owed."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories, fixtures, test_users


def test_an_exercised_transfer_reports_its_state_not_the_closed_window(api):
    """A late waiver on an already-exercised notice is refused for the state, not the calendar.

    An `EXERCISE` ends the window at once: `transfer_status` becomes `PPR_EXERCISED` and `ppr_holder_owner_id` is set to the electing owner.
    The transfer's `transfer_status` must be `NOTICED`, else `ERR_TRANSFER_NOT_PENDING` with status 409; the electing owner must not already have an election recorded on this transfer, else `ERR_PPR_ELECTION_ALREADY_SUBMITTED` with status 409; the logical clock's date must be on or before `ppr_deadline_date`, else `ERR_PPR_WINDOW_EXPIRED` with status 422; and the electing `X-User-ID` must hold an `ACTIVE` position on the transfer's well with `preferential_right` true while being neither `assignor_owner_id` nor `assignee_owner_id` — that is, it must be one of the holders the notice was served on — else `ERR_PPR_HOLDER_INVALID` with status 403.

    Design: Difficulty/priority_pair_validation_conflict/transfer_state_check_beats_expired_ppr_window
    """
    context = fixtures.setup_assignment_notice(
        api,
        clock="2026-08-05T00:00:00Z",
        assignor="partner_b_id",
        assignee="partner_c_id",
        transfer_wi_pct=0.1,
        transfer_nri_pct=0.08,
        sale_price_cents=4_000_000,
        notice_date="2026-08-01",
        effective_date="2026-08-05",
    )
    transfer_id = context["transfer_id"]

    assert context["transfer"]["ppr_eligible_count"] == 2
    assert context["transfer"]["ppr_deadline_date"] == "2026-08-31"

    fixtures.submit_ppr(api, transfer_id, context["partner_a_headers"], "EXERCISE")
    exercised = validate_success(
        api.get_assignment_transfer(transfer_id, fixtures.LAND_ADMIN), 200
    )
    assert exercised["transfer_status"] == "PPR_EXERCISED"

    fixtures.set_clock(api, "2026-09-05T00:00:00Z")

    validate_error(
        api.submit_ppr_election(
            transfer_id,
            factories.ppr_election_payload("WAIVE"),
            context["operator_headers"],
        ),
        "ERR_TRANSFER_NOT_PENDING",
        409,
    )

    after = validate_success(
        api.get_assignment_transfer(transfer_id, fixtures.LAND_ADMIN), 200
    )
    assert after["transfer_status"] == "PPR_EXERCISED"
    assert after["ppr_waiver_count"] == 0
    assert after["ppr_holder_owner_id"] == context["partner_a_id"]


def test_a_grantee_without_a_tax_id_is_refused_before_its_bond_is_counted(api):
    """The buyer fails the compliance test, so the operator never reaches the bond arithmetic.

    The grantee must have `tax_id_on_file` true, else `ERR_OWNER_NOT_COMPLIANT` with status 409, because an interest may not be conveyed to an owner the operator cannot report to the taxing authority.
    And last of all, the grantee's `bond_posted_cents` must be at least its `bond_check_required_cents`, else `ERR_INSUFFICIENT_BOND` with status 402; the coverage test is inclusive, so a grantee posted at exactly the required figure closes.

    Design: Difficulty/priority_pair_validation_conflict/grantee_compliance_check_beats_bond_shortfall_on_closing
    """
    context = fixtures.setup_pooled_producing_well(api, clock="2026-08-05T00:00:00Z")
    validate_success(
        api.update_owner_compliance(
            context["partner_b_id"],
            factories.compliance_update_payload(
                tax_id_on_file=False, bond_posted_cents=0
            ),
            fixtures.COMPLIANCE_OFFICER,
        ),
        200,
    )

    context = fixtures.setup_assignment_notice(
        api,
        assignor="operator_id",
        assignee="partner_b_id",
        transfer_wi_pct=0.1,
        transfer_nri_pct=0.08,
        sale_price_cents=4_000_000,
        notice_date="2026-08-01",
        effective_date="2026-08-05",
        context=context,
    )
    transfer_id = context["transfer_id"]
    fixtures.submit_ppr(api, transfer_id, context["partner_a_headers"], "WAIVE")

    before = validate_success(
        api.get_assignment_transfer(transfer_id, fixtures.LAND_ADMIN), 200
    )
    assert before["transfer_status"] == "PPR_WAIVED"
    assert before["bond_check_required_cents"] == 5_587_500

    grantee = validate_success(
        api.get_interest_owner(context["partner_b_id"], fixtures.LAND_ADMIN), 200
    )
    assert grantee["tax_id_on_file"] is False
    assert grantee["bond_posted_cents"] == 0

    validate_error(
        api.close_assignment_transfer(
            transfer_id,
            factories.transfer_closing_payload("2026-08-05"),
            fixtures.LAND_ADMIN,
        ),
        "ERR_OWNER_NOT_COMPLIANT",
        409,
    )

    after = validate_success(
        api.get_assignment_transfer(transfer_id, fixtures.LAND_ADMIN), 200
    )
    assert after["transfer_status"] == "PPR_WAIVED"

    rows = fixtures.active_interests(api, context["well_id"])
    assignor_rows = [r for r in rows if r["owner_id"] == context["operator_id"]]
    assert len(assignor_rows) == 1
    assert assignor_rows[0]["working_interest_pct"] == 0.500000
    assert round(sum(r["working_interest_pct"] for r in rows), 6) == 1.000000


def test_the_bill_preparer_is_turned_away_before_the_closed_dispute_is_mentioned(api):
    """The accountant who prepared the bill learns it is the wrong person, not that the matter is closed.

    Segregation of duties is absolute: the acting `X-User-ID` must differ from the `prepared_by_user_id` recorded on the disputed statement, else `ERR_SEGREGATION_OF_DUTIES` with status 403.
    A lease whose `tenure_status` is `EXPIRED`, a well whose `well_status` is `PLUGGED`, a statement whose `statement_status` is `ADJUSTED`, `SETTLED` or `VOID`, a dispute whose `dispute_status` is `RESOLVED_UPHELD`, `RESOLVED_ADJUSTED` or `EXPIRED`, a transfer whose `transfer_status` is `CLOSED`, a disbursement whose `disbursement_status` is `PAID`, and a working-interest position whose `interest_status` is `TERMINATED` are all terminal and accept no further mutation.

    Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_beats_terminal_state_on_resolution
    """
    context = fixtures.setup_responded_dispute(
        api,
        clock="2026-08-10T00:00:00Z",
        exchange_note="Cost is joint per exhibit C",
    )
    dispute_id = context["dispute_id"]
    statement_id = context["statement_id"]

    validate_success(
        api.resolve_dispute(
            dispute_id,
            factories.dispute_resolution_payload("UPHELD", 0),
            fixtures.AUDIT_REVIEWER,
        ),
        200,
    )

    before = validate_success(api.get_dispute(dispute_id, fixtures.JIB_ACCOUNTANT), 200)
    assert before["dispute_status"] == "RESOLVED_UPHELD"
    assert before["resolved_by_user_id"] == "u-audit-1"
    statement = validate_success(
        api.get_jib_statement(statement_id, fixtures.JIB_ACCOUNTANT), 200
    )
    assert statement["statement_status"] == "ISSUED"
    assert statement["prepared_by_user_id"] == "u-jib-1"

    preparer_as_reviewer = test_users.make_headers("u-jib-1", "AuditReviewer")
    validate_error(
        api.resolve_dispute(
            dispute_id,
            factories.dispute_resolution_payload("ADJUSTED", 100_000),
            preparer_as_reviewer,
        ),
        "ERR_SEGREGATION_OF_DUTIES",
        403,
    )

    after = validate_success(api.get_dispute(dispute_id, fixtures.JIB_ACCOUNTANT), 200)
    assert after["dispute_status"] == "RESOLVED_UPHELD"
    assert after["adjustment_amount_cents"] == 0
    statement = validate_success(
        api.get_jib_statement(statement_id, fixtures.JIB_ACCOUNTANT), 200
    )
    assert statement["statement_status"] == "ISSUED"
    well = validate_success(api.get_well(context["well_id"], fixtures.LAND_ADMIN), 200)
    assert well["billed_to_date_cents"] == 1_153_008
