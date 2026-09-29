"""What each write endpoint actually returns and leaves behind, filters included."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories, fixtures

CLOCK = "2026-08-10T00:00:00Z"


def _bare_well(api, **overrides):
    return validate_success(
        api.create_well(
            factories.create_well_payload(omit_fields=["spud_date"], **overrides),
            fixtures.LAND_ADMIN,
        ),
        201,
    )


def test_a_compliance_update_touches_only_the_posture_fields_it_carries(api):
    """Posting a bond says nothing about the taxpayer identification number.

    A `ComplianceOfficer` — and only a `ComplianceOfficer` — updates that posture afterwards, supplying any subset of `tax_id_on_file`, `bond_posted_cents` and `audit_window_days`. Every such update recomputes the owner's `required_bond_cents` and increments the owner's `version` by 1.

    Design: Corner/endpoints/a_compliance_update_patches_only_the_supplied_owner_fields
    """
    fixtures.set_clock(api, CLOCK)
    owner = validate_success(
        api.create_interest_owner(
            factories.create_interest_owner_payload(
                owner_name="Epsilon Resources Inc",
                contact_email="epsilon@example.com",
                tax_id_on_file=False,
                bond_posted_cents=0,
            ),
            fixtures.LAND_ADMIN,
        ),
        201,
    )

    updated = validate_success(
        api.update_owner_compliance(
            owner["id"],
            factories.compliance_update_payload(bond_posted_cents=25_000_000),
            fixtures.COMPLIANCE_OFFICER,
        ),
        200,
    )

    assert updated["bond_posted_cents"] == 25_000_000
    assert updated["tax_id_on_file"] is False
    assert updated["audit_window_days"] == 730
    assert updated["version"] == 2


def test_paying_a_vendor_moves_the_booked_charge_out_of_the_accrued_pool(api):
    """The accountant books the invoice first and records the cheque afterwards.

    A cost entry booked with a paid date is written with `cost_status` of `PAID`; one booked without a paid date is written `ACCRUED` and its `paid_date` stays null.
    Settling an accrued charge is a separate step: the accountant supplies the `paid_date` on which the vendor was paid, and the entry's `cost_status` becomes `PAID` with its `version` incremented by 1.

    Design: Corner/endpoints/cost_entry_payment_moves_the_entry_from_accrued_to_paid
    """
    fixtures.set_clock(api, CLOCK)
    well = _bare_well(api)
    entry = fixtures.book_cost(
        api, well["id"], "LEASE_OPERATING", "OPERATING", 300_000, "2026-06-09"
    )
    assert entry["cost_status"] == "ACCRUED"
    assert entry["paid_date"] is None

    paid = validate_success(
        api.pay_cost_entry(
            entry["id"],
            factories.cost_entry_payment_payload("2026-06-20"),
            fixtures.JIB_ACCOUNTANT,
        ),
        200,
    )

    assert paid["cost_status"] == "PAID"
    assert paid["paid_date"] == "2026-06-20"

    _, paid_meta = validate_paginated(
        api.list_cost_entries(
            fixtures.JIB_ACCOUNTANT,
            params={"well_id": well["id"], "cost_status": "PAID"},
        )
    )
    assert paid_meta["total_count"] == 1

    _, accrued_meta = validate_paginated(
        api.list_cost_entries(
            fixtures.JIB_ACCOUNTANT,
            params={"well_id": well["id"], "cost_status": "ACCRUED"},
        )
    )
    assert accrued_meta["total_count"] == 0


def test_a_charge_cannot_be_authorized_by_another_wells_authorization(api):
    """An AFE belongs to one wellbore, so it cannot underwrite a charge on a different one.

    When an AFE is named, it must belong to the same well the cost is being booked against; a cost entry referencing an AFE on a different well is rejected with `ERR_COST_AFE_MISMATCH`.

    Design: Corner/endpoints/a_cost_entry_naming_an_afe_of_another_well_is_rejected
    """
    fixtures.set_clock(api, CLOCK)
    well1 = _bare_well(api)
    well2 = _bare_well(
        api, well_name="Sandstone 2H", api_number="42-123-45679", total_depth_ft=9000
    )
    afe = fixtures.raise_afe(
        api,
        well2["id"],
        afe_number="AFE-002",
        operation_type="COMPLETION",
        estimated_cost_cents=2_000_000,
        cost_class="CAPITAL",
        election_deadline_date="2026-08-31",
    )
    body = factories.create_cost_entry_payload(
        cost_category="COMPLETION",
        cost_class="CAPITAL",
        amount_cents=750_000,
        incurred_date="2026-06-15",
        afe_id=afe["id"],
    )

    validate_error(
        api.create_cost_entry(well1["id"], dict(body), fixtures.JIB_ACCOUNTANT),
        "ERR_COST_AFE_MISMATCH",
        422,
    )

    _, meta = validate_paginated(
        api.list_cost_entries(
            fixtures.JIB_ACCOUNTANT, params={"well_id": well1["id"]}
        )
    )
    assert meta["total_count"] == 0

    validate_success(
        api.create_cost_entry(well2["id"], dict(body), fixtures.JIB_ACCOUNTANT), 201
    )


def test_replaying_the_evaluation_pass_at_the_same_instant_changes_nothing(api):
    """The sweep is a function of the clock, so a second call at the same clock is a no-op.

    A periodic obligation evaluation pass, run by a `ComplianceOfficer`, walks every time-gated rule in the system against the logical clock in a single idempotent sweep — running it twice at the same clock value changes nothing the second time.
    The evaluation pass reports what it did: an `evaluated_at` instant, and counters for `leases_expired`, `leases_flagged_obligation_due`, `leases_in_breach`, `disputes_escalated`, `disputes_expired`, `transfers_deemed_waived`, `allocations_withdrawn`, `revenues_suspended` and `disbursements_suspended`.

    Design: Corner/endpoints/a_second_obligation_run_at_the_same_clock_reports_zero_transitions
    """
    fixtures.set_clock(api, CLOCK)
    lease = validate_success(
        api.create_lease(
            factories.minimal_lease_payload(
                lease_number="L-004",
                lessor_name="Zeta Minerals",
                gross_acres=200.0,
                royalty_rate=0.2,
                primary_term_end_date="2026-06-30",
            ),
            fixtures.LAND_ADMIN,
        ),
        201,
    )
    first = fixtures.run_obligation_pass(api)
    assert first["leases_expired"] == 1
    after_first = validate_success(api.get_lease(lease["id"], fixtures.LAND_ADMIN), 200)

    second = validate_success(
        api.run_obligation_pass(fixtures.COMPLIANCE_OFFICER), 200
    )

    for counter in (
        "leases_expired",
        "leases_flagged_obligation_due",
        "leases_in_breach",
        "allocations_withdrawn",
        "revenues_suspended",
        "disbursements_suspended",
        "disputes_escalated",
        "disputes_expired",
        "transfers_deemed_waived",
    ):
        assert second[counter] == 0, counter
    assert second["evaluated_at"] == "2026-08-10T00:00:00.000Z"

    after_second = validate_success(api.get_lease(lease["id"], fixtures.LAND_ADMIN), 200)
    assert after_second["tenure_status"] == "EXPIRED"
    assert after_second["version"] == after_first["version"]


def test_the_charge_rows_of_a_bill_add_up_to_the_bill(api):
    """A joint account bill that does not tie to its own detail is unauditable.

    The identity that closes the arithmetic is exact: the statement's `total_billed_cents` equals `direct_cost_cents` plus `overhead_cents`, and equals the sum of `total_billed_cents` across every line item it produced.

    Design: Corner/endpoints/statement_line_items_sum_to_the_statement_total
    """
    context = fixtures.setup_issued_june_statement(api, clock=CLOCK)

    rows, meta = validate_paginated(
        api.list_jib_statement_line_items(
            context["statement_id"], fixtures.JIB_ACCOUNTANT, params={"limit": 100}
        )
    )

    assert meta["total_count"] == 3
    assert meta["has_more"] is False
    by_owner = {row["owner_id"]: row for row in rows}

    operator = by_owner[context["operator_id"]]
    assert operator["direct_capital_cents"] == 1_250_000
    assert operator["direct_operating_cents"] == 150_000
    assert operator["overhead_cents"] == 67_000
    assert operator["total_billed_cents"] == 1_467_000

    partner_a = by_owner[context["partner_a_id"]]
    assert partner_a["direct_capital_cents"] == 750_000
    assert partner_a["direct_operating_cents"] == 90_000
    assert partner_a["overhead_cents"] == 40_200
    assert partner_a["total_billed_cents"] == 880_200

    partner_b = by_owner[context["partner_b_id"]]
    assert partner_b["direct_capital_cents"] == 500_000
    assert partner_b["direct_operating_cents"] == 60_000
    assert partner_b["overhead_cents"] == 26_800
    assert partner_b["total_billed_cents"] == 586_800

    for row in rows:
        assert row["rounding_residual_cents"] == 0
        assert row["non_consent_withheld_cents"] == 0
        assert row["non_consent_reallocated_cents"] == 0
        assert row["penalty_accrued_cents"] == 0

    assert sum(row["total_billed_cents"] for row in rows) == 2_934_000


def test_cash_cannot_be_applied_to_a_bill_that_is_still_being_contested(api):
    """The contest has to close before the joint account calls the charge paid.

    The statement's `statement_status` must be `ISSUED` and no dispute against it may be `OPEN`, `OPERATOR_RESPONDED` or `ESCALATED`, else `ERR_STATEMENT_NOT_SETTLEABLE` with status 409 — cash may be applied to a contested bill only after the contest closes.

    Design: Corner/endpoints/settling_a_statement_with_an_open_dispute_is_rejected
    """
    context = fixtures.setup_issued_june_statement(api, clock=CLOCK)
    dispute = validate_success(
        api.file_dispute(
            context["statement_id"],
            factories.file_dispute_payload(
                context["partner_a_id"],
                100_000,
                basis_note="Overhead allocation questioned",
            ),
            context["partner_a_headers"],
        ),
        201,
    )

    validate_error(
        api.settle_jib_statement(
            context["statement_id"],
            fixtures.JIB_ACCOUNTANT,
            factories.statement_settlement_payload("2026-07-20"),
        ),
        "ERR_STATEMENT_NOT_SETTLEABLE",
        409,
    )

    statement = validate_success(
        api.get_jib_statement(context["statement_id"], fixtures.JIB_ACCOUNTANT), 200
    )
    assert statement["statement_status"] == "DISPUTED"

    read_dispute = validate_success(
        api.get_dispute(dispute["id"], fixtures.JIB_ACCOUNTANT), 200
    )
    assert read_dispute["dispute_status"] == "OPEN"

    well = validate_success(api.get_well(context["well_id"], fixtures.LAND_ADMIN), 200)
    assert well["billed_to_date_cents"] == 2_934_000
