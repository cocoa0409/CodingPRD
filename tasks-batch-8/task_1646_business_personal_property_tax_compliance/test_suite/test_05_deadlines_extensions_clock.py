"""Late-filing penalty tiers and cap, deadline boundaries, extension rules,
OCC on extension creation, clock monotonicity, and the compliance sweeps."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_date_is,
    assert_filing_extension,
    classify,
    create_asset_for,
    create_class_rule_for,
    create_client_account,
    create_extension_payload,
    create_jurisdiction_account,
    create_notice_payload,
    create_payment_schedule_payload,
    create_tax_bill_payload,
    file_it,
    find_installment,
    generate,
    new_analyst,
    open_rendition,
    set_logical_clock,
    setup_abated_asset,
    validate_error,
    validate_success,
)

CLERK = TEST_USERS["assessor_clerk_headers"]


def _setup_unfiled_penalty_rendition(legal_name, tag):
    """A generated (unfiled) 2027 rendition assessing 600000 in a jurisdiction
    with deadline 04-15, 2% per started month, 10% cap, VALUE_BASE."""
    client = create_client_account(legal_name=legal_name,
                                   contact_email=f"{tag.lower()}@x.com")
    analyst = new_analyst()
    jurisdiction = create_jurisdiction_account(county_name="Penalty County")
    create_class_rule_for(jurisdiction["id"], category="MACHINERY", is_taxable=True,
                          depreciation_convention="FULL_YEAR",
                          percent_good_vector=[80, 70, 60],
                          percent_good_floor_pct=30, de_minimis_line_cents=0)
    asset = create_asset_for(client["id"], jurisdiction["id"], analyst["headers"],
                             asset_tag=tag, acquisition_cost_cents=1000000,
                             acquisition_date="2025-03-10",
                             in_service_date="2025-04-01")
    classify(asset["id"], "TAXABLE", analyst["headers"])
    rendition = open_rendition(client["id"], jurisdiction["id"], 2027,
                               analyst["headers"])
    generate(rendition["id"], analyst["headers"])
    return {"client": client, "analyst": analyst, "rendition": rendition}


def test_late_penalty_first_started_month_tier(api):
    """PRD §3.4: "Each started thirty-day month of lateness counts as one penalty
    month, so `late_penalty_months` is `late_days` divided by 30 rounded up: one
    to thirty days late is one month. The penalty percentage is the lesser of the
    months multiplied by the jurisdiction's `late_penalty_pct_per_month` and the
    jurisdiction's `max_late_penalty_pct` cap." and "under `VALUE_BASE` it is the
    rendition's `total_assessed_value_cents`"

    Design: Difficulty/combinatorial_formula/late_penalty_tiered_cap_and_base_modes
    """
    ctx = _setup_unfiled_penalty_rendition("PenOne", "P1")
    set_logical_clock("2027-04-26T00:00:00Z")
    filed = validate_success(api.file_rendition(ctx["rendition"]["id"],
                                                ctx["analyst"]["headers"]), 200)
    assert filed["is_late_filing"] is True
    assert filed["late_days"] == 11, "2027-04-15 -> 2027-04-26"
    assert filed["late_penalty_months"] == 1, "ceil(11 / 30)"
    assert filed["late_penalty_cents"] == 12000, "600000 * 2% (one started month)"


def test_late_penalty_hits_percentage_cap(api):
    """PRD §3.4: "The penalty percentage is the lesser of the months multiplied by
    the jurisdiction's `late_penalty_pct_per_month` and the jurisdiction's
    `max_late_penalty_pct` cap. The penalty base depends on `penalty_base`: under
    `VALUE_BASE` it is the rendition's `total_assessed_value_cents`" and "The
    resulting `late_penalty_cents` is the base multiplied by the penalty
    percentage and divided by 100, rounded half-up to whole cents"

    Design: Difficulty/combinatorial_formula/late_penalty_tiered_cap_and_base_modes
    """
    ctx = _setup_unfiled_penalty_rendition("PenTwo", "P2")
    set_logical_clock("2027-12-01T00:00:00Z")
    filed = validate_success(api.file_rendition(ctx["rendition"]["id"],
                                                ctx["analyst"]["headers"]), 200)
    assert filed["late_days"] == 230, "2027-04-15 -> 2027-12-01"
    assert filed["late_penalty_months"] == 8, "ceil(230 / 30)"
    assert filed["late_penalty_cents"] == 60000, (
        "min(8 * 2, 10) = 10% cap branch of 600000"
    )


def test_filing_exactly_on_deadline_is_on_time(api):
    """PRD §3.4: "The `late_days` figure is the number of whole days between the
    deadline and the filing date, floored at zero — filing exactly on the deadline
    is on time, and only a filing date strictly after the deadline counts."

    Design: Difficulty/boundary_precision_check/filing_deadline_equality_is_on_time
    """
    ctx = _setup_unfiled_penalty_rendition("BoundThree", "B3")
    set_logical_clock("2027-04-15T12:00:00Z")
    filed = validate_success(api.file_rendition(ctx["rendition"]["id"],
                                                ctx["analyst"]["headers"]), 200)
    assert filed["is_late_filing"] is False
    assert filed["late_days"] == 0
    assert filed["late_penalty_cents"] == 0


def test_filing_one_day_after_deadline_is_late(api):
    """PRD §3.4: "filing exactly on the deadline is on time, and only a filing
    date strictly after the deadline counts. Each started thirty-day month of
    lateness counts as one penalty month, so `late_penalty_months` is `late_days`
    divided by 30 rounded up: one to thirty days late is one month."

    Design: Difficulty/boundary_precision_check/filing_deadline_equality_is_on_time
    """
    ctx = _setup_unfiled_penalty_rendition("BoundFour", "B4")
    set_logical_clock("2027-04-16T00:00:00Z")
    filed = validate_success(api.file_rendition(ctx["rendition"]["id"],
                                                ctx["analyst"]["headers"]), 200)
    assert filed["is_late_filing"] is True
    assert filed["late_days"] == 1
    assert filed["late_penalty_months"] == 1
    assert filed["late_penalty_cents"] == 12000


def test_extension_beyond_max_days_rejected(api):
    """PRD §3.4: "the requested date may not lie beyond the base deadline plus the
    jurisdiction's `max_extension_days` (otherwise `ERR_EXTENSION_EXCEEDS_MAX`,
    HTTP 422 — the request is simply rejected and no denied record is persisted,
    because an extension record exists only as `GRANTED`, `SUPERSEDED`, or
    `EXPIRED`). A request within the ceiling is granted immediately"

    Design: Corner/validations/extension_beyond_max_days_rejected
    """
    client = create_client_account(legal_name="ExtCo", contact_email="ext@x.com")
    analyst = new_analyst()
    jurisdiction = create_jurisdiction_account(county_name="Ext County")
    rendition = open_rendition(client["id"], jurisdiction["id"], 2027,
                               analyst["headers"])

    res = api.create_extension(
        rendition["id"],
        create_extension_payload("2027-05-16", rendition["version"]),
        analyst["headers"])
    validate_error(res, ApiErrorId.ERR_EXTENSION_EXCEEDS_MAX, expected_status=422)

    # The boundary date itself (base 2027-04-15 + 30 days = 2027-05-15) is granted.
    granted = validate_success(api.create_extension(
        rendition["id"],
        create_extension_payload("2027-05-15", rendition["version"]),
        analyst["headers"]), 201)
    assert_filing_extension(granted)
    assert granted["extension_status"] == "GRANTED"
    assert granted["granted_days"] == 30


def test_extension_after_deadline_rejected(api):
    """PRD §3.4: "the current clock date must be on or before the rendition's
    effective `deadline_date` (later requests are rejected with
    `ERR_EXTENSION_WINDOW_CLOSED`, HTTP 422)"

    Design: Corner/validations/extension_after_deadline_rejected
    """
    client = create_client_account(legal_name="LateExtCo", contact_email="latext@x.com")
    analyst = new_analyst()
    jurisdiction = create_jurisdiction_account(county_name="LateExt County")
    rendition = open_rendition(client["id"], jurisdiction["id"], 2027,
                               analyst["headers"])
    set_logical_clock("2027-04-16T00:00:00Z")

    res = api.create_extension(
        rendition["id"],
        create_extension_payload("2027-05-10", rendition["version"]),
        analyst["headers"])
    validate_error(res, ApiErrorId.ERR_EXTENSION_WINDOW_CLOSED, expected_status=422)


def test_extension_occ_stale_version_rejected(api):
    """PRD §2.7: "Requesting a filing extension requires the request to carry
    `expected_rendition_version` equal to the rendition's current `version`;
    because a granted extension legitimately supersedes the prior grant and moves
    the rendition's `deadline_date`, a writer holding a stale rendition view must
    not silently overwrite a newer deadline, so a mismatch is rejected with
    `ERR_STALE_VERSION` (HTTP 412)." and PRD §3.4: "the record is created in
    `GRANTED` status with `granted_days` set to the number of days the new
    deadline lies beyond the base deadline, the rendition's `deadline_date` moves
    to the `requested_extend_to_date`, the rendition's `version` increments by one"

    Design: Corner/cross_cutting_complexity_layers/extension_occ_stale_version_rejected
    """
    client = create_client_account(legal_name="OccCo", contact_email="occ@x.com")
    analyst = new_analyst()
    jurisdiction = create_jurisdiction_account(county_name="Occ County")
    rendition = open_rendition(client["id"], jurisdiction["id"], 2027,
                               analyst["headers"])
    observed_version = rendition["version"]

    granted = validate_success(api.create_extension(
        rendition["id"],
        create_extension_payload("2027-05-10", observed_version),
        analyst["headers"]), 201)
    assert_filing_extension(granted)
    assert granted["extension_status"] == "GRANTED"
    assert granted["granted_days"] == 25, "2027-04-15 -> 2027-05-10"

    moved = validate_success(api.get_rendition(rendition["id"],
                                               analyst["headers"]), 200)
    assert_date_is(moved["deadline_date"], "2027-05-10", "deadline_date")
    assert moved["version"] == observed_version + 1, "grant increments version by one"

    stale = api.create_extension(
        rendition["id"],
        create_extension_payload("2027-05-12", observed_version),
        analyst["headers"])
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

    extensions = validate_success(api.list_extensions(rendition["id"],
                                                      analyst["headers"]), 200)
    assert len(extensions) == 1, "the rejected stale request persists no record"
    assert extensions[0]["id"] == granted["id"]


def test_clock_regression_rejected(api, firm_admin_headers):
    """PRD §2.5: "A `FirmAdmin`-only clock-driving capability accepts a target
    instant in the `to_iso8601` field; the target must be strictly after the
    current logical clock value, and a target that is equal to or earlier than the
    current value is rejected with `ERR_CLOCK_MONOTONIC` (HTTP 400)."

    Design: Corner/validations/clock_regression_rejected
    """
    set_logical_clock("2027-01-10T00:00:00Z")
    res = api.set_clock({"to_iso8601": "2027-01-05T00:00:00Z"}, firm_admin_headers)
    validate_error(res, ApiErrorId.ERR_CLOCK_MONOTONIC, expected_status=400)


def test_clock_sweep_expires_extension_lates_installment_flags_abatement(api):
    """PRD §2.5: "Setting the clock runs a deterministic sweep in this pinned
    order: first, granted filing extensions whose granted date has passed on
    renditions still not filed become `EXPIRED`; second, assessment notices whose
    protest deadline has passed without a protest are finalized; third, scheduled
    installments whose due date is strictly before the new clock date become
    `LATE` and each affected bill's payment status is recomputed; fourth,
    abatement agreements entering their next uncovered tax year become
    `RECERTIFICATION_DUE`; fifth, suspended exemptions whose ninety-day cure
    period has elapsed become `REVOKED`." and PRD §3.7: "A `TaxAnalyst` then
    recertifies by passing the `tax_year` being certified, which must equal
    `last_recertified_year` plus one; success moves the agreement back to `ACTIVE`
    and advances `last_recertified_year` to that year."

    Design: Corner/cross_cutting_complexity_layers/clock_sweep_expires_extension_lates_installment_flags_abatement
    """
    # Client 1: abated asset (25% over 2027..2031), filed rendition, ACCEPTED
    # notice 800000, bill billed 15000 at rate 0.025 validated to 15000
    # (20000 gross - 5000 abatement credit), one installment due 2027-06-30.
    ctx = setup_abated_asset(
        rule_overrides={"percent_good_vector": [100, 100]},
        asset_overrides={"asset_tag": "SW1", "acquisition_cost_cents": 800000},
        abatement_overrides={"first_tax_year": 2027, "last_tax_year": 2031,
                             "abatement_pct": 25},
        with_manager=True,
    )
    rendition = open_rendition(ctx["client"]["id"], ctx["jurisdiction"]["id"], 2027,
                               ctx["analyst"]["headers"])
    generate(rendition["id"], ctx["analyst"]["headers"])
    file_it(rendition["id"], ctx["analyst"]["headers"])
    notice = validate_success(api.create_notice(
        rendition["id"],
        create_notice_payload(notice_value_cents=800000,
                              protest_deadline_date="2028-06-01"),
        CLERK), 201)
    validate_success(api.accept_notice(notice["id"], ctx["analyst"]["headers"]), 200)
    bill = validate_success(api.create_tax_bill(
        notice["id"],
        create_tax_bill_payload(billed_amount_cents=15000, tax_rate=0.025,
                                due_date="2027-06-30"),
        ctx["analyst"]["headers"]), 201)
    bill = validate_success(api.validate_bill(bill["id"], ctx["manager"]["headers"]), 200)
    assert bill["validated_amount_cents"] == 15000, "20000 gross - 5000 abatement"
    bill = validate_success(api.create_payment_schedule(
        bill["id"], create_payment_schedule_payload(installment_count=1),
        ctx["analyst"]["headers"]), 200)
    assert bill["payment_status"] == "SCHEDULED"

    # Client 2: DRAFT rendition with a GRANTED extension to 2027-05-10.
    client2 = create_client_account(legal_name="SweepTwo", contact_email="s2@x.com")
    rendition2 = open_rendition(client2["id"], ctx["jurisdiction"]["id"], 2027,
                                ctx["analyst"]["headers"])
    extension = validate_success(api.create_extension(
        rendition2["id"],
        create_extension_payload("2027-05-10", rendition2["version"]),
        ctx["analyst"]["headers"]), 201)
    assert extension["extension_status"] == "GRANTED"

    set_logical_clock("2027-05-20T00:00:00Z")
    extensions = validate_success(api.list_extensions(rendition2["id"],
                                                      ctx["analyst"]["headers"]), 200)
    ext_row = [e for e in extensions if e["id"] == extension["id"]][0]
    assert ext_row["extension_status"] == "EXPIRED", (
        "unfiled rendition past the granted date: first sweep stage expires it"
    )

    set_logical_clock("2028-01-02T00:00:00Z")
    bill_after = validate_success(api.get_tax_bill(bill["id"],
                                                   ctx["analyst"]["headers"]), 200)
    installment = find_installment(bill_after, 1)
    assert installment["installment_status"] == "LATE", (
        "due 2027-06-30 is strictly before the new clock date"
    )
    assert bill_after["payment_status"] == "DELINQUENT"

    abatement_after = validate_success(api.get_abatement(
        ctx["abatement"]["id"], ctx["analyst"]["headers"]), 200)
    assert abatement_after["agreement_status"] == "RECERTIFICATION_DUE", (
        "clock reached Jan 1 of 2028 = last_recertified_year 2027 + 1, within interval"
    )

    recertified = validate_success(api.recertify_abatement(
        ctx["abatement"]["id"], {"tax_year": 2028}, ctx["analyst"]["headers"]), 200)
    assert recertified["agreement_status"] == "ACTIVE"
    assert recertified["last_recertified_year"] == 2028
