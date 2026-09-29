"""The two independent axes of a pledge, and the three-link write-off cascade.

A pledge advances on a designation axis and on a collection axis at the same
time without either constraining the other, and writing one off walks a cascade
that ends on the receiving agency's year-to-date passthrough ledger.
"""

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers.api_client import api_client
from test_helpers.assertions import assert_money, require_by
from test_helpers.factories import (
    amend_payload,
    collection_payload,
    designation_line,
    pledge_payload,
    write_off_payload,
)
from test_helpers.fixtures import (
    create_active_employer,
    create_good_standing_agency,
    create_open_campaign,
    remit,
)
from test_helpers.test_users import make_admin_headers, make_finance_reviewer_headers


def _two_axis_scenario():
    """A CONFIRMED 1000.00 payroll pledge with a 200.00 line and 400.00 remitted."""
    employer = create_active_employer(
        legal_name="Cedar Valley Foods",
        employee_count=900,
        payroll_periods_per_year=26,
        historical_shrinkage_rate_bps=700,
    )
    _, campaign = create_open_campaign(
        employer["id"],
        solicitation_start_date="2026-07-01",
        solicitation_end_date="2026-09-30",
        loss_reserve_amount="0.00",
    )
    agency = create_good_standing_agency(
        legal_name="Northside Food Bank",
        ein="400000001",
        primary_priority_area="BASIC_NEEDS",
    )
    admin = make_admin_headers()
    pledge = validate_success(
        api_client.create_pledge(
            campaign["id"],
            pledge_payload(
                donor_reference="D-300",
                giving_method="PAYROLL_DEDUCTION",
                gross_amount="1000.00",
                designations=[designation_line(agency["id"], "200.00")],
            ),
            admin,
        ),
        201,
    )
    validate_success(api_client.confirm_pledge(pledge["id"], admin))
    remit(pledge["id"], "400.00")
    return campaign, agency, pledge["id"]


def _amend_to_three_hundred(pledge_id, agency_id):
    admin = make_admin_headers()
    current = validate_success(api_client.get_pledge(pledge_id, admin))
    return validate_success(
        api_client.amend_pledge_designations(
            pledge_id,
            amend_payload(
                current["version"], [designation_line(agency_id, "300.00")]
            ),
            admin,
        )
    )


def test_amending_the_line_set_leaves_the_collection_axis_where_it_stood():
    """PRD 3.5: "A pledge's `collection_status` starts at `PENDING` and evolves
    through `PARTIAL` to either `COLLECTED` or `WRITTEN_OFF`, and it does so without
    regard to whether the pledge is `CONFIRMED`, `AMENDED` or `LOCKED` on the
    designation axis — a pledge may perfectly well be `PARTIAL` while `AMENDED`."

    Design: Difficulty/non_linear_state_machine/pledge_designation_and_collection_axes_evolve_independently
    """
    _, agency, pledge_id = _two_axis_scenario()
    admin = make_admin_headers()

    amended = _amend_to_three_hundred(pledge_id, agency["id"])

    assert amended["designation_status"] == "AMENDED", "the designation axis moved"
    assert amended["collection_status"] == "PARTIAL", "the collection axis did not move"
    assert_money(amended["collected_amount"], "400.00", "collected_amount")
    assert amended["amend_count"] == 1
    assert_money(amended["designated_amount_total"], "300.00", "designated_amount_total")
    assert_money(amended["undesignated_amount"], "700.00", "undesignated_amount")
    assert_money(amended["designation_fee_total"], "21.75", "designation_fee_total")
    assert_money(amended["net_designated_total"], "278.25", "net_designated_total")

    lines, meta = validate_paginated(
        api_client.list_pledge_designations(pledge_id, admin)
    )
    assert meta["total_count"] == 2, "one superseded line and one active line"
    superseded = require_by(lines, "status", "SUPERSEDED")
    active = require_by(lines, "status", "ACTIVE")
    assert_money(superseded["processing_fee"], "14.50", "superseded processing_fee")
    assert_money(
        superseded["collected_designated_amount"], "0.00", "superseded collected share"
    )
    assert active["designation_sequence"] == 1
    assert_money(active["designated_amount"], "300.00", "active designated_amount")
    assert_money(active["processing_fee"], "21.75", "active processing_fee")
    assert_money(active["net_designated_amount"], "278.25", "active net_designated_amount")


def test_final_remittance_closes_the_collection_axis_and_leaves_the_pledge_amended():
    """PRD 3.5: "A remittance exactly equal to the outstanding balance closes the
    pledge, advancing either `PENDING → COLLECTED` or `PARTIAL → COLLECTED`, and in
    that case `collected_amount` is set to `gross_amount` and `uncollected_amount`
    to 0.00."

    Design: Difficulty/non_linear_state_machine/pledge_designation_and_collection_axes_evolve_independently
    """
    _, agency, pledge_id = _two_axis_scenario()
    admin = make_admin_headers()
    _amend_to_three_hundred(pledge_id, agency["id"])

    closed = validate_success(
        api_client.create_collection(
            pledge_id,
            collection_payload("600.00", "2026-08-15"),
            make_finance_reviewer_headers(),
        )
    )

    assert closed["collection_status"] == "COLLECTED", "the collection axis closed"
    assert closed["designation_status"] == "AMENDED", "the designation axis did not move"
    assert_money(closed["collected_amount"], "1000.00", "collected_amount")
    assert_money(closed["uncollected_amount"], "0.00", "uncollected_amount")
    assert closed["amend_count"] == 1, "the remittance did not touch amend_count"

    active, meta = validate_paginated(
        api_client.list_pledge_designations(pledge_id, admin, {"status": "ACTIVE"})
    )
    assert meta["total_count"] == 1
    assert_money(
        active[0]["collected_designated_amount"], "278.25", "active collected share"
    )
    reread = validate_success(api_client.get_agency(agency["id"], admin))
    assert_money(reread["designated_passthrough_ytd"], "278.25", "designated_passthrough_ytd")


def _write_off_scenario():
    """A PARTIAL 1000.00 payroll pledge whose 400.00 line has carried 92.75."""
    employer = create_active_employer(
        legal_name="Ironbridge Logistics",
        employee_count=1500,
        payroll_periods_per_year=26,
        historical_shrinkage_rate_bps=900,
    )
    _, campaign = create_open_campaign(
        employer["id"],
        solicitation_start_date="2026-07-01",
        solicitation_end_date="2026-09-30",
        loss_reserve_amount="0.00",
    )
    agency = create_good_standing_agency(
        legal_name="Hopewell Counseling",
        ein="700000001",
        primary_priority_area="HEALTH",
    )
    admin = make_admin_headers()
    pledge = validate_success(
        api_client.create_pledge(
            campaign["id"],
            pledge_payload(
                donor_reference="D-400",
                giving_method="PAYROLL_DEDUCTION",
                gross_amount="1000.00",
                designations=[designation_line(agency["id"], "400.00")],
            ),
            admin,
        ),
        201,
    )
    validate_success(api_client.confirm_pledge(pledge["id"], admin))
    remit(pledge["id"], "250.00")
    return campaign, agency, pledge["id"]


def test_write_off_fixes_the_uncollected_amount_and_records_the_reason():
    """PRD 3.5: "First, the pledge's `collection_status` advances `PENDING →
    WRITTEN_OFF` or `PARTIAL → WRITTEN_OFF` according to where it stood,
    `write_off_reason_code` records the supplied reason, and `uncollected_amount` is
    fixed at `gross_amount` minus `collected_amount`."

    Design: Difficulty/transitive_cascade/pledge_write_off_cascade_three_links_to_agency_passthrough
    """
    _, agency, pledge_id = _write_off_scenario()

    written_off = validate_success(
        api_client.write_off_pledge(
            pledge_id, write_off_payload("TERMINATION"), make_finance_reviewer_headers()
        )
    )

    assert written_off["collection_status"] == "WRITTEN_OFF"
    assert written_off["write_off_reason_code"] == "TERMINATION"
    assert_money(written_off["uncollected_amount"], "750.00", "uncollected_amount")
    assert_money(written_off["collected_amount"], "250.00", "collected_amount")
    assert written_off["designation_status"] == "CONFIRMED", (
        "the designation axis is untouched by the write-off"
    )


def test_write_off_flips_the_active_line_to_uncollected_and_zeroes_its_share():
    """PRD 3.5: "Second, because of that, every `ACTIVE` designation line of the
    pledge moves `ACTIVE → UNCOLLECTED` and each such line's
    `collected_designated_amount` is re-derived to 0.00."

    Design: Difficulty/transitive_cascade/pledge_write_off_cascade_three_links_to_agency_passthrough
    """
    _, agency, pledge_id = _write_off_scenario()
    admin = make_admin_headers()

    before, before_meta = validate_paginated(
        api_client.list_pledge_designations(pledge_id, admin, {"status": "ACTIVE"})
    )
    assert before_meta["total_count"] == 1, "one line is ACTIVE before the write-off"
    assert_money(
        before[0]["collected_designated_amount"], "92.75", "collected share before"
    )

    validate_success(
        api_client.write_off_pledge(
            pledge_id, write_off_payload("TERMINATION"), make_finance_reviewer_headers()
        )
    )

    remaining_active, active_meta = validate_paginated(
        api_client.list_pledge_designations(pledge_id, admin, {"status": "ACTIVE"})
    )
    assert active_meta["total_count"] == 0, "no line is ACTIVE after the write-off"
    assert remaining_active == [], "no line is ACTIVE after the write-off"
    uncollected, uncollected_meta = validate_paginated(
        api_client.list_pledge_designations(pledge_id, admin, {"status": "UNCOLLECTED"})
    )
    assert uncollected_meta["total_count"] == 1, "the line moved to UNCOLLECTED"
    assert_money(uncollected[0]["designated_amount"], "400.00", "designated_amount")
    assert_money(
        uncollected[0]["collected_designated_amount"], "0.00", "collected share after"
    )


def test_write_off_recomputes_the_agency_passthrough_without_touching_it_directly():
    """PRD 3.5: "Third, because of that, `designated_passthrough_ytd` is re-derived
    for every agency that held one of those lines, with the newly uncollected lines
    dropped out of the sum — an agency's apparent designation income therefore falls
    the moment a donor's pledge is written off, and its future award from the
    undesignated pool rises correspondingly."

    Design: Difficulty/transitive_cascade/pledge_write_off_cascade_three_links_to_agency_passthrough
    """
    _, agency, pledge_id = _write_off_scenario()
    admin = make_admin_headers()

    before = validate_success(api_client.get_agency(agency["id"], admin))
    assert_money(before["designated_passthrough_ytd"], "92.75", "passthrough before")

    validate_success(
        api_client.write_off_pledge(
            pledge_id, write_off_payload("TERMINATION"), make_finance_reviewer_headers()
        )
    )

    after = validate_success(api_client.get_agency(agency["id"], admin))
    assert_money(after["designated_passthrough_ytd"], "0.00", "passthrough after")
