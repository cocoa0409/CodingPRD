"""An artist's profile written, read back and revised, and the year's tax picture."""

from test_helpers import (
    ADMIN_HEADERS,
    ERR_DUPLICATE_CODE,
    ERR_UNAUTHORIZED,
    FINANCE_SCHEDULER_HEADERS,
    FUNDER_HEADERS,
    SPONSORED_SESSION_START,
    assert_money_equals,
    disbursements_for,
    get_success_data,
    make_applicant_payload,
    pay_disbursement,
    payment_dates,
    read_residency,
    setup_open_cycle,
    setup_residency_ready_for_payment,
    tax_report,
    validate_error,
    validate_paginated,
)

CLOCK = "2026-08-01T00:00:00Z"
PROFILE = {
    "full_name": "Ada Rivet",
    "email": "ada.rivet@example.org",
    "affiliation_org": "North Shore Collective",
    "citizenship_country": "US",
    "treaty_country": False,
    "declared_annual_income_cents": 2000000,
}
MOVE_ABROAD = {
    "affiliation_org": "Harbour Works",
    "citizenship_country": "FR",
    "treaty_country": True,
    "declared_annual_income_cents": 1750000,
}


def _domestic_artist_with_a_residency(api):
    """A US artist holding one invited residency, so the tax picture reads W9."""
    cycle = setup_open_cycle(api, clock=CLOCK)
    payload = make_applicant_payload(**PROFILE)
    row = get_success_data(api.create_applicant(payload, ADMIN_HEADERS), 201)
    residency = get_success_data(
        api.create_residency(
            {
                "cycle_id": cycle.cycle_id,
                "applicant_id": row["id"],
                "discipline_id": cycle.discipline_id("SCULPT"),
            },
            ADMIN_HEADERS,
        ),
        201,
    )
    return payload, row, residency


def _patch(api, applicant_id, changes):
    """A profile edit as program staff records it."""
    return get_success_data(
        api.update_applicant(applicant_id, dict(changes), ADMIN_HEADERS)
    )


def test_the_create_echoes_every_input_and_derives_the_pair(api):
    """Nothing supplied is transformed, and the two computed fields start where stated.

    PRD: "The host country is the United States, written `US`; from
    `citizenship_country` the server derives `is_international`, which is true
    exactly when the applicant's citizenship country is anything other than `US`."

    Design: Corner/endpoints/applicant_crud_round_trip_re_derives_the_tax_and_visa_picture
    """
    payload, row, _residency = _domestic_artist_with_a_residency(api)

    for field, value in payload.items():
        assert row[field] == value, f"{field} was not echoed"
    assert row["is_international"] is False
    assert row["completed_residency_count"] == 0
    assert row["version"] == 1


def test_the_read_and_the_filtered_list_agree_with_the_write(api):
    """The same row comes back by id and by the email it was registered under.

    PRD: "Applicants can be listed filtered by `email` or `citizenship_country`."

    Design: Corner/endpoints/applicant_crud_round_trip_re_derives_the_tax_and_visa_picture
    """
    payload, row, _residency = _domestic_artist_with_a_residency(api)

    fetched = get_success_data(api.get_applicant(row["id"], ADMIN_HEADERS))
    listed, meta = validate_paginated(
        api.list_applicants(ADMIN_HEADERS, {"email": payload["email"]})
    )

    assert fetched == row
    assert meta["total_count"] == 1
    assert [entry["id"] for entry in listed] == [row["id"]]


def test_the_profile_edit_returns_the_new_values_and_one_more_version(api):
    """Four supplied fields land together on a single advance of the version.

    PRD: "Profile edits may change `full_name`, `affiliation_org`,
    `citizenship_country`, `treaty_country` or `declared_annual_income_cents`;
    such an edit re-derives `is_international` and advances the applicant's
    `version` by 1"

    Design: Corner/endpoints/applicant_crud_round_trip_re_derives_the_tax_and_visa_picture
    """
    _payload, row, _residency = _domestic_artist_with_a_residency(api)

    edited = _patch(api, row["id"], MOVE_ABROAD)

    for field, value in MOVE_ABROAD.items():
        assert edited[field] == value, f"{field} did not take the new value"
    assert edited["version"] == row["version"] + 1


def test_the_edit_re_derives_the_computed_flag_on_the_same_row(api):
    """Leaving the host country turns the derived flag over immediately.

    PRD: "from `citizenship_country` the server derives `is_international`, which
    is true exactly when the applicant's citizenship country is anything other
    than `US`"

    Design: Corner/endpoints/applicant_crud_round_trip_re_derives_the_tax_and_visa_picture
    """
    _payload, row, _residency = _domestic_artist_with_a_residency(api)
    assert row["is_international"] is False

    edited = _patch(api, row["id"], MOVE_ABROAD)

    assert edited["is_international"] is True
    assert get_success_data(api.get_applicant(row["id"], ADMIN_HEADERS))[
        "is_international"
    ] is True


def test_the_residency_picture_shifts_on_its_very_next_read(api):
    """A different entity answers differently, without having been written to.

    PRD: "and because a residency's `visa_required` and `tax_form_type` are
    themselves derived from the applicant, those fields shift on subsequent reads
    too"

    Design: Corner/endpoints/applicant_crud_round_trip_re_derives_the_tax_and_visa_picture
    """
    _payload, row, residency = _domestic_artist_with_a_residency(api)
    assert residency["visa_required"] is False
    assert residency["tax_form_type"] == "W9"

    _patch(api, row["id"], MOVE_ABROAD)

    after = read_residency(api, residency["id"])
    assert after["visa_required"] is True
    assert after["tax_form_type"] == "1042S"


def test_the_fields_left_out_of_the_edit_are_left_alone(api):
    """A partial edit is not a replacement, so the name and the email survive.

    PRD: "Profile edits may change `full_name`, `affiliation_org`,
    `citizenship_country`, `treaty_country` or `declared_annual_income_cents`"

    Design: Corner/endpoints/applicant_crud_round_trip_re_derives_the_tax_and_visa_picture
    """
    payload, row, _residency = _domestic_artist_with_a_residency(api)

    edited = _patch(api, row["id"], MOVE_ABROAD)

    assert edited["full_name"] == payload["full_name"]
    assert edited["email"] == payload["email"]
    assert edited["completed_residency_count"] == 0


def test_the_email_uniqueness_is_enforced_rather_than_deduplicated(api):
    """A second registration under the same address is refused outright.

    PRD: "an `email` that must be unique across all applicants
    (`ERR_DUPLICATE_CODE`, HTTP 409)"

    Design: Corner/endpoints/applicant_crud_round_trip_re_derives_the_tax_and_visa_picture
    """
    payload, _row, _residency = _domestic_artist_with_a_residency(api)

    twin = dict(payload, full_name="Ada Rivet the Second")

    validate_error(
        api.create_applicant(make_applicant_payload(**twin), ADMIN_HEADERS),
        ERR_DUPLICATE_CODE,
    )

    _listed, meta = validate_paginated(
        api.list_applicants(ADMIN_HEADERS, {"email": payload["email"]})
    )
    assert meta["total_count"] == 1


WEEKLY_OVERRIDE = 43751
PERIOD_GROSS = 87502
PAID_PERIODS = 2
ANNUAL_GROSS = PAID_PERIODS * PERIOD_GROSS
EXEMPTION = 60000


def _half_paid_treaty_resident(api):
    """A treaty resident whose first two of four periods have been settled."""
    _cycle, _applicant, residency, rows = setup_residency_ready_for_payment(
        api,
        session_length_weeks=8,
        international=True,
        treaty_country=True,
        weekly_rate_override_cents=WEEKLY_OVERRIDE,
    )
    assert [row["gross_cents"] for row in rows] == [PERIOD_GROSS] * 4
    dates = payment_dates(SPONSORED_SESSION_START, 4)
    paid = [
        pay_disbursement(api, rows[index]["id"], dates[index])
        for index in range(PAID_PERIODS)
    ]
    assert [payment["status"] for payment in paid] == ["PAID"] * PAID_PERIODS
    return residency, rows, paid


def test_the_form_and_the_rate_come_from_the_residents_tax_status(api):
    """The treaty flag picks the rate; no payment amount is consulted.

    PRD: "`tax_form_type` and `withholding_rate` are the residency's form type and
    the rate selected as above."

    Design: Corner/endpoints/tax_report_reconciles_both_withholding_variants_without_writing
    """
    residency, _rows, _paid = _half_paid_treaty_resident(api)

    report = tax_report(api, residency.residency_id)

    assert report["tax_form_type"] == "1042S"
    assert report["withholding_rate"] == 0.15


def test_the_paid_rows_alone_set_the_gross_and_the_taxable_base(api):
    """Two settled periods, and the cumulative exemption taken off once.

    PRD: "`annual_taxable_cents` is the amount by which `annual_gross_cents`
    exceeds the 60,000-cent exemption, or 0 when it does not."

    Design: Corner/endpoints/tax_report_reconciles_both_withholding_variants_without_writing
    """
    residency, _rows, _paid = _half_paid_treaty_resident(api)

    report = tax_report(api, residency.residency_id)

    assert report["paid_period_count"] == PAID_PERIODS
    assert_money_equals(report["annual_gross_cents"], ANNUAL_GROSS, "annual gross")
    assert_money_equals(
        report["annual_taxable_cents"], ANNUAL_GROSS - EXEMPTION, "annual taxable"
    )


def test_the_two_variants_disagree_by_exactly_one_cent(api):
    """Rounding every payment lands a cent below rounding the year once.

    PRD: "Because the first variant rounds every payment and the second rounds
    only the total, the two can disagree by a cent or two, and
    `reconciliation_delta_cents` reports the gap as `withheld_actual_cents` minus
    `statutory_liability_cents`, a positive value meaning the programme
    over-withheld."

    Design: Corner/endpoints/tax_report_reconciles_both_withholding_variants_without_writing
    """
    residency, _rows, paid = _half_paid_treaty_resident(api)
    assert [payment["withholding_cents"] for payment in paid] == [4125, 13125]

    report = tax_report(api, residency.residency_id)

    assert_money_equals(report["withheld_actual_cents"], 17250, "withheld actual")
    assert_money_equals(report["statutory_liability_cents"], 17251, "statutory line")
    assert_money_equals(report["reconciliation_delta_cents"], -1, "reconciliation delta")


def test_the_report_agrees_with_the_residency_ledgers_it_summarises(api):
    """The same two figures are readable from the residency itself.

    PRD: "`withheld_actual_cents` is the sum of `withholding_cents` over those same
    paid rows — the money actually held back, with each payment's rounding already
    baked in."

    Design: Corner/endpoints/tax_report_reconciles_both_withholding_variants_without_writing
    """
    residency, _rows, _paid = _half_paid_treaty_resident(api)

    report = tax_report(api, residency.residency_id)

    ledger = read_residency(api, residency.residency_id)
    assert_money_equals(
        ledger["stipend_paid_gross_cents"], report["annual_gross_cents"], "paid gross"
    )
    assert_money_equals(
        ledger["withholding_to_date_cents"],
        report["withheld_actual_cents"],
        "withholding to date",
    )


def test_the_scheduled_rows_are_outside_both_variants(api):
    """Two unpaid periods of the same size are simply not in the sums.

    PRD: "`annual_gross_cents` is the sum of `gross_cents` over the residency's
    `PAID` disbursements and `paid_period_count` is how many such rows there are."

    Design: Corner/endpoints/tax_report_reconciles_both_withholding_variants_without_writing
    """
    residency, _rows, _paid = _half_paid_treaty_resident(api)
    still_owed = [
        row
        for row in disbursements_for(api, residency.residency_id)
        if row["status"] == "SCHEDULED"
    ]
    assert [row["gross_cents"] for row in still_owed] == [PERIOD_GROSS] * 2

    report = tax_report(api, residency.residency_id)

    assert_money_equals(report["annual_gross_cents"], ANNUAL_GROSS, "annual gross")
    assert report["annual_gross_cents"] != 4 * PERIOD_GROSS


def test_the_report_writes_nothing_and_repeats_itself(api):
    """Two identical calls, and no version anywhere has moved.

    PRD: "**The tax report** is a computed read available to a `FinanceOfficer` or
    a `ProgramAdmin` that writes nothing and returns eight fields."

    Design: Corner/endpoints/tax_report_reconciles_both_withholding_variants_without_writing
    """
    residency, _rows, paid = _half_paid_treaty_resident(api)
    before = read_residency(api, residency.residency_id)

    first = tax_report(api, residency.residency_id)
    second = tax_report(api, residency.residency_id)

    assert first == second
    assert read_residency(api, residency.residency_id)["version"] == before["version"]
    for payment in paid:
        current = get_success_data(
            api.get_disbursement(payment["id"], FINANCE_SCHEDULER_HEADERS)
        )
        assert current["version"] == payment["version"]


def test_the_report_is_closed_to_the_funder_and_open_to_the_admin(api):
    """Two roles may read the year's tax picture, and the funder is not one of them.

    PRD: "**The tax report** is a computed read available to a `FinanceOfficer` or
    a `ProgramAdmin` that writes nothing and returns eight fields."

    Design: Corner/endpoints/tax_report_reconciles_both_withholding_variants_without_writing
    """
    residency, _rows, _paid = _half_paid_treaty_resident(api)

    validate_error(
        api.get_tax_report(residency.residency_id, FUNDER_HEADERS), ERR_UNAUTHORIZED
    )

    as_admin = get_success_data(
        api.get_tax_report(residency.residency_id, ADMIN_HEADERS)
    )
    assert as_admin == tax_report(api, residency.residency_id)
