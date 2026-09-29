"""Per-line designation fee rounding, and the gross decomposition of a pledge
that survives a full designation amendment round trip.

Both groups of tests here exercise the donor-designation fee allocation of
PRD 3.3, one from the rounding-order angle and one from the conserved-quantity
angle.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_client import api_client
from test_helpers.api_errors import ERR_STALE_VERSION
from test_helpers.assertions import (
    assert_gross_decomposition,
    assert_money,
    require_by,
)
from test_helpers.factories import (
    amend_payload,
    designation_line,
    pledge_payload,
)
from test_helpers.fixtures import (
    create_active_employer,
    create_good_standing_agency,
    create_open_campaign,
    remit,
)
from test_helpers.test_users import make_admin_headers


def _fee_scenario(payroll_periods_per_year=24):
    """One ACTIVE employer with an OPEN campaign and two GOOD_STANDING agencies."""
    employer = create_active_employer(
        legal_name="Lakeside Utilities",
        employee_count=220,
        payroll_periods_per_year=payroll_periods_per_year,
        historical_shrinkage_rate_bps=500,
    )
    _, campaign = create_open_campaign(
        employer["id"],
        solicitation_start_date="2026-07-01",
        solicitation_end_date="2026-09-30",
        loss_reserve_amount="0.00",
    )
    agency_a = create_good_standing_agency(
        legal_name="Harbor Literacy Council",
        ein="200000001",
        primary_priority_area="EDUCATION",
    )
    agency_b = create_good_standing_agency(
        legal_name="Eastside Health Clinic",
        ein="200000002",
        primary_priority_area="HEALTH",
    )
    return employer, campaign, agency_a, agency_b


def test_two_twenty_five_dollar_lines_each_round_before_the_fee_total_is_summed():
    """PRD 3.3: "Consider a 150.00 pledge split into two lines of 25.00 each. Each
    line's raw fee is 1.8125, which rounds half up to 1.81, and neither line is
    lifted by the 1.50 floor, so `designation_fee_total` is 3.62 and
    `undesignated_amount` is 100.00."

    Design: Difficulty/combinatorial_formula/designation_fee_per_line_rounding_before_summation
    """
    _, campaign, agency_a, agency_b = _fee_scenario()
    admin = make_admin_headers()

    response = api_client.create_pledge(
        campaign["id"],
        pledge_payload(
            donor_reference="D-100",
            giving_method="ONE_TIME_CHECK",
            gross_amount="150.00",
            designations=[
                designation_line(agency_a["id"], "25.00"),
                designation_line(agency_b["id"], "25.00"),
            ],
        ),
        admin,
    )
    pledge = validate_success(response, 201)

    assert_money(pledge["designated_amount_total"], "50.00", "designated_amount_total")
    assert_money(pledge["undesignated_amount"], "100.00", "undesignated_amount")
    assert_money(pledge["designation_fee_total"], "3.62", "designation_fee_total")
    assert pledge["designation_fee_total"] not in ("3.63", 3.63), (
        "designation_fee_total is 3.63, the sum-then-round answer the PRD calls wrong"
    )
    assert_money(pledge["net_designated_total"], "46.38", "net_designated_total")
    assert pledge["designation_status"] == "DRAFT"
    assert pledge["collection_status"] == "PENDING"
    assert_gross_decomposition(pledge)

    lines, meta = validate_paginated(
        api_client.list_pledge_designations(pledge["id"], admin)
    )
    assert meta["total_count"] == 2, "the pledge holds exactly two designation lines"
    first = require_by(lines, "designation_sequence", 1)
    second = require_by(lines, "designation_sequence", 2)
    assert first["agency_id"] == agency_a["id"]
    assert second["agency_id"] == agency_b["id"]
    assert_money(first["processing_fee"], "1.81", "line 1 processing_fee")
    assert_money(first["net_designated_amount"], "23.19", "line 1 net_designated_amount")
    assert_money(second["processing_fee"], "1.81", "line 2 processing_fee")
    assert_money(second["net_designated_amount"], "23.19", "line 2 net_designated_amount")


def test_three_twenty_five_dollar_lines_sum_already_rounded_fees_without_re_rounding():
    """PRD 2.5: "First, when a calculation rounds a per-line or per-score value and
    then aggregates, the aggregate is the sum of the already-rounded values and is
    never re-rounded — summing raw products and rounding the total once at the end
    produces a different answer and is wrong."

    Three 25.00 lines each round to 1.81, so the total is 5.43; rounding the raw
    75.00 at 7.25 percent once would give 5.44.

    Design: Difficulty/combinatorial_formula/designation_fee_per_line_rounding_before_summation
    """
    _, campaign, agency_a, agency_b = _fee_scenario()
    admin = make_admin_headers()

    pledge = validate_success(
        api_client.create_pledge(
            campaign["id"],
            pledge_payload(
                donor_reference="D-101",
                giving_method="ONE_TIME_CHECK",
                gross_amount="150.00",
                designations=[
                    designation_line(agency_a["id"], "25.00"),
                    designation_line(agency_b["id"], "25.00"),
                    designation_line(agency_a["id"], "25.00"),
                ],
            ),
            admin,
        ),
        201,
    )

    assert_money(pledge["designated_amount_total"], "75.00", "designated_amount_total")
    assert_money(pledge["designation_fee_total"], "5.43", "designation_fee_total")
    assert pledge["designation_fee_total"] not in ("5.44", 5.44), (
        "designation_fee_total is 5.44, which re-rounds the aggregate"
    )
    assert_money(pledge["net_designated_total"], "69.57", "net_designated_total")
    assert_money(pledge["undesignated_amount"], "75.00", "undesignated_amount")
    assert_gross_decomposition(pledge)

    lines, meta = validate_paginated(
        api_client.list_pledge_designations(pledge["id"], admin)
    )
    assert meta["total_count"] == 3, "the pledge holds exactly three designation lines"
    for sequence in (1, 2, 3):
        line = require_by(lines, "designation_sequence", sequence)
        assert_money(line["processing_fee"], "1.81", f"line {sequence} processing_fee")


def _round_trip_scenario():
    """A CONFIRMED 1000.00 payroll pledge, one 400.00 line to AG_A, 250.00 remitted."""
    employer = create_active_employer(
        legal_name="Meridian Steel Works",
        employee_count=1100,
        payroll_periods_per_year=26,
        historical_shrinkage_rate_bps=850,
    )
    _, campaign = create_open_campaign(
        employer["id"],
        solicitation_start_date="2026-07-01",
        solicitation_end_date="2026-09-30",
        loss_reserve_amount="0.00",
    )
    agency_a = create_good_standing_agency(
        legal_name="Ridgeway Family Center",
        ein="160000001",
        primary_priority_area="BASIC_NEEDS",
    )
    agency_b = create_good_standing_agency(
        legal_name="Sunfield Adult Day Health",
        ein="160000002",
        primary_priority_area="HEALTH",
    )
    admin = make_admin_headers()
    pledge = validate_success(
        api_client.create_pledge(
            campaign["id"],
            pledge_payload(
                donor_reference="D-INV-1",
                giving_method="PAYROLL_DEDUCTION",
                gross_amount="1000.00",
                designations=[designation_line(agency_a["id"], "400.00")],
            ),
            admin,
        ),
        201,
    )
    validate_success(api_client.confirm_pledge(pledge["id"], admin))
    remit(pledge["id"], "250.00")
    return campaign, agency_a, agency_b, pledge["id"]


def _passthrough(agency_id):
    agency = validate_success(api_client.get_agency(agency_id, make_admin_headers()))
    return agency["designated_passthrough_ytd"]


def _active_lines(pledge_id):
    lines, meta = validate_paginated(
        api_client.list_pledge_designations(
            pledge_id, make_admin_headers(), {"status": "ACTIVE"}
        )
    )
    return lines, meta


def test_single_line_pledge_decomposes_and_scales_its_line_by_the_collection_ratio():
    """PRD 3.5: "Processing the pledge's `ACTIVE` lines in ascending
    `designation_sequence`, each line's `collected_designated_amount` becomes its
    `net_designated_amount` multiplied by the pledge's collection ratio —
    `collected_amount` divided by `gross_amount` — rounded half up to two decimal
    places."

    Design: Difficulty/compensating_invariant/pledge_gross_decomposition_survives_designation_amend_round_trip
    """
    _, agency_a, agency_b, pledge_id = _round_trip_scenario()
    admin = make_admin_headers()

    pledge = validate_success(api_client.get_pledge(pledge_id, admin))
    assert_money(pledge["designated_amount_total"], "400.00", "designated_amount_total")
    assert_money(pledge["undesignated_amount"], "600.00", "undesignated_amount")
    assert_money(pledge["designation_fee_total"], "29.00", "designation_fee_total")
    assert_money(pledge["net_designated_total"], "371.00", "net_designated_total")
    assert_gross_decomposition(pledge)
    assert pledge["collection_status"] == "PARTIAL"
    assert_money(pledge["collected_amount"], "250.00", "collected_amount")
    assert pledge["amend_count"] == 0, "no amendment has run yet"

    lines, meta = _active_lines(pledge_id)
    assert meta["total_count"] == 1, "exactly one line is ACTIVE"
    assert_money(lines[0]["collected_designated_amount"], "92.75", "collected_designated_amount")
    assert_money(_passthrough(agency_a["id"]), "92.75", "AG_A designated_passthrough_ytd")
    assert_money(_passthrough(agency_b["id"]), "0.00", "AG_B designated_passthrough_ytd")


def test_amending_to_two_lines_conserves_gross_and_moves_the_passthrough_ledger():
    """PRD 3.4: "Every currently `ACTIVE` designation line of the pledge moves
    `ACTIVE → SUPERSEDED`, which drops it out of `designated_amount_total` and out
    of the receiving agency's `designated_passthrough_ytd` permanently — a
    superseded line is frozen with `collected_designated_amount` at 0.00 and never
    re-enters any total."

    Design: Difficulty/compensating_invariant/pledge_gross_decomposition_survives_designation_amend_round_trip
    """
    _, agency_a, agency_b, pledge_id = _round_trip_scenario()
    admin = make_admin_headers()

    before = validate_success(api_client.get_pledge(pledge_id, admin))
    amended = validate_success(
        api_client.amend_pledge_designations(
            pledge_id,
            amend_payload(
                before["version"],
                [
                    designation_line(agency_a["id"], "300.00"),
                    designation_line(agency_b["id"], "150.00"),
                ],
            ),
            admin,
        )
    )

    assert_money(amended["designated_amount_total"], "450.00", "designated_amount_total")
    assert_money(amended["undesignated_amount"], "550.00", "undesignated_amount")
    assert_money(amended["designation_fee_total"], "32.63", "designation_fee_total")
    assert_money(amended["net_designated_total"], "417.37", "net_designated_total")
    assert_gross_decomposition(amended)
    assert amended["designation_status"] == "AMENDED"
    assert amended["amend_count"] == 1, "one successful amendment has run"
    assert amended["version"] == before["version"] + 1, "the amendment is one mutation"
    assert amended["collection_status"] == "PARTIAL", "the collection axis is untouched"
    assert_money(amended["collected_amount"], "250.00", "collected_amount")

    lines, meta = _active_lines(pledge_id)
    assert meta["total_count"] == 2, "the new line set holds two ACTIVE lines"
    first = require_by(lines, "designation_sequence", 1)
    second = require_by(lines, "designation_sequence", 2)
    assert first["agency_id"] == agency_a["id"], "array order pins designation_sequence"
    assert second["agency_id"] == agency_b["id"]
    assert_money(first["processing_fee"], "21.75", "line 1 processing_fee")
    assert_money(first["net_designated_amount"], "278.25", "line 1 net_designated_amount")
    assert_money(second["processing_fee"], "10.88", "line 2 processing_fee")
    assert_money(second["net_designated_amount"], "139.12", "line 2 net_designated_amount")

    superseded, superseded_meta = validate_paginated(
        api_client.list_pledge_designations(pledge_id, admin, {"status": "SUPERSEDED"})
    )
    assert superseded_meta["total_count"] == 1, "the original 400.00 line was superseded"
    assert_money(
        superseded[0]["collected_designated_amount"], "0.00", "superseded line collected"
    )


def test_round_trip_back_to_one_line_restores_every_conserved_quantity():
    """PRD 3.4: "The fee allocation is re-run over the new active set, rewriting
    `designated_amount_total`, `undesignated_amount`, `designation_fee_total` and
    `net_designated_total`."

    The pledge laps `CONFIRMED → AMENDED → CONFIRMED` and is amended back to the
    original single 400.00 line, so every conserved figure returns to its
    starting value and the second agency's ledger falls back to 0.00.

    Design: Difficulty/compensating_invariant/pledge_gross_decomposition_survives_designation_amend_round_trip
    """
    campaign, agency_a, agency_b, pledge_id = _round_trip_scenario()
    admin = make_admin_headers()

    state_zero = validate_success(api_client.get_pledge(pledge_id, admin))
    validate_success(
        api_client.amend_pledge_designations(
            pledge_id,
            amend_payload(
                state_zero["version"],
                [
                    designation_line(agency_a["id"], "300.00"),
                    designation_line(agency_b["id"], "150.00"),
                ],
            ),
            admin,
        )
    )
    reconfirmed = validate_success(api_client.confirm_pledge(pledge_id, admin))
    assert reconfirmed["designation_status"] == "CONFIRMED"

    state_two = validate_success(
        api_client.amend_pledge_designations(
            pledge_id,
            amend_payload(
                reconfirmed["version"],
                [designation_line(agency_a["id"], "400.00")],
            ),
            admin,
        )
    )

    assert_money(
        state_two["designated_amount_total"],
        state_zero["designated_amount_total"],
        "designated_amount_total",
    )
    assert_money(state_two["designated_amount_total"], "400.00", "designated_amount_total")
    assert_money(state_two["undesignated_amount"], "600.00", "undesignated_amount")
    assert_money(state_two["designation_fee_total"], "29.00", "designation_fee_total")
    assert_money(state_two["net_designated_total"], "371.00", "net_designated_total")
    assert_gross_decomposition(state_two)
    assert state_two["amend_count"] == 2, "two successful amendments have run"
    assert state_two["designation_status"] == "AMENDED"
    assert state_two["version"] == reconfirmed["version"] + 1, "the amendment is one mutation"
    assert state_two["collection_status"] == "PARTIAL", "the collection axis is untouched"
    assert_money(state_two["collected_amount"], "250.00", "collected_amount")

    active, active_meta = _active_lines(pledge_id)
    assert active_meta["total_count"] == 1, "exactly one line is ACTIVE again"
    assert active[0]["designation_sequence"] == 1
    assert_money(active[0]["designated_amount"], "400.00", "ACTIVE line designated_amount")

    superseded, superseded_meta = validate_paginated(
        api_client.list_pledge_designations(pledge_id, admin, {"status": "SUPERSEDED"})
    )
    assert superseded_meta["total_count"] == 3, "three lines have been superseded"
    for line in superseded:
        assert_money(line["collected_designated_amount"], "0.00", "superseded line collected")

    _, all_meta = validate_paginated(
        api_client.list_pledge_designations(pledge_id, admin)
    )
    assert all_meta["total_count"] == 4, "superseded lines stay on the record"

    assert_money(_passthrough(agency_b["id"]), "0.00", "AG_B designated_passthrough_ytd")

    reread = validate_success(api_client.get_campaign(campaign["id"], admin))
    assert_money(reread["confirmed_gross_total"], "1000.00", "confirmed_gross_total")
    assert_money(reread["designated_gross_total"], "400.00", "designated_gross_total")
    assert_money(reread["undesignated_gross_total"], "600.00", "undesignated_gross_total")
    assert_money(reread["designation_fee_total"], "29.00", "campaign designation_fee_total")


def test_replaying_the_first_amendment_from_a_stale_version_is_refused():
    """PRD 2.6: "If that value does not equal the pledge's current `version`, the
    amendment is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Difficulty/compensating_invariant/pledge_gross_decomposition_survives_designation_amend_round_trip
    """
    _, agency_a, agency_b, pledge_id = _round_trip_scenario()
    admin = make_admin_headers()

    state_zero = validate_success(api_client.get_pledge(pledge_id, admin))
    new_lines = [
        designation_line(agency_a["id"], "300.00"),
        designation_line(agency_b["id"], "150.00"),
    ]
    validate_success(
        api_client.amend_pledge_designations(
            pledge_id, amend_payload(state_zero["version"], new_lines), admin
        )
    )

    replay = api_client.amend_pledge_designations(
        pledge_id, amend_payload(state_zero["version"], new_lines), admin
    )
    validate_error(replay, ERR_STALE_VERSION, 412)

    unchanged = validate_success(api_client.get_pledge(pledge_id, admin))
    assert unchanged["version"] == state_zero["version"] + 1, "the refused replay changed nothing"
    assert unchanged["amend_count"] == 1, "only the first amendment counted"
    assert_money(unchanged["designated_amount_total"], "450.00", "designated_amount_total")
