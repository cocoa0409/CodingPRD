"""Window bounds, uniqueness keys, cycle limits and cross-field amount rules.

Each test builds its own world from scratch through the PRD's own endpoints: the
harness empties the database and relaunches the API before every test.
"""

from test_helpers import (
    ApiErrorId,
    assert_employee,
    assert_filing_season,
    assert_form_1095c,
    assert_group_member,
    assert_penalty_notice,
    assert_transmittal,
    factories,
    fixtures,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

# Notice literals shared by the proposed-penalty recipes below.
NOTICE_DATE = "2026-06-01"
NOTICE_RESPONSE_DUE_DATE = "2026-09-30"
NOTICE_PROPOSED_AMOUNT_CENTS = 271700
ASSERTED_A_MONTHS = [1, 2]


def _determined_group(api, reporting_year_ft_count=40):
    """Season -> controlled group -> one MONTHLY member -> twelve prior-year and
    twelve reporting-year headcount rows -> aggregated determination.

    The reporting-year rows are recorded before the determination because the
    determination is what recomputes each member's ``reporting_year_ft_months``,
    the weight both penalty allocations divide by.
    """
    season = fixtures.create_filing_season(api)
    group = fixtures.create_controlled_group(api, season["id"])
    member = fixtures.create_group_member(api, group["id"], measurement_method="MONTHLY")
    fixtures.record_headcounts(api, member["id"], count_year="PRIOR_YEAR")
    fixtures.record_headcounts(
        api,
        member["id"],
        count_year="REPORTING_YEAR",
        full_time_employee_count=reporting_year_ft_count,
        part_time_hours_total=0,
        total_employee_count=reporting_year_ft_count + 5,
    )
    fixtures.run_ale_determination(api, group["id"])
    return {"season": season, "group": group, "member": member}


def _group_with_penalty_notice(
    api,
    notice_number,
    asserted_a_months=None,
    response_due_date=NOTICE_RESPONSE_DUE_DATE,
    reporting_year_ft_count=40,
):
    """The determined group plus one proposed-penalty notice sitting at RECEIVED."""
    ctx = _determined_group(api, reporting_year_ft_count=reporting_year_ft_count)
    ctx["notice"] = fixtures.create_penalty_notice(
        api,
        ctx["group"]["id"],
        notice_number,
        asserted_a_months=list(ASSERTED_A_MONTHS if asserted_a_months is None else asserted_a_months),
        asserted_b_employee_months=[],
        notice_date=NOTICE_DATE,
        response_due_date=response_due_date,
        proposed_amount_cents=NOTICE_PROPOSED_AMOUNT_CENTS,
    )
    return ctx


def _recomputed_notice(api, notice_number):
    """The notice carried through one month-2 offer proof and a recomputation, so
    it sits at RECOMPUTED with the cents allocated to the single active member."""
    ctx = _group_with_penalty_notice(api, notice_number)
    fixtures.file_evidence(
        api, ctx["notice"]["id"], "MEC_OFFER_PROOF", 2, document_ref="OFFER-LOG-FEB"
    )
    ctx["recomputed"] = fixtures.recompute_notice(api, ctx["notice"]["id"])
    return ctx


# ---------------------------------------------------------------------------
# Evidence must answer what the agency asserted
# ---------------------------------------------------------------------------
def test_evidence_month_outside_asserted_a_months_rejected(api, compliance_officer_headers):
    """PRD §3.9: "Evidence must line up with what the agency actually asserted: a
    `MEC_OFFER_PROOF` naming a month absent from `asserted_a_months`, or an
    `FT_STATUS_DISPUTE` or `OFFER_PROOF` naming an employee-month absent from
    `asserted_b_employee_months`, is refused with
    `ERR_EVIDENCE_MONTH_NOT_ASSERTED`."
    PRD §3.9: "A new notice starts at `RECEIVED` with `evidence_count` 0,
    `allocated_total_cents` 0, `unallocated_amount_cents` 0,
    `applied_evidence_count` 0, and nulls in `a_month_penalty_cents`,
    `b_month_penalty_cents`, `recalculated_amount_cents`, `abated_amount_cents`,
    `determination`, `recomputed_at`, `last_evidence_user_id`,
    `response_submitted_by_user_id` and `response_submitted_at`."

    Design: Corner/Errors/evidence_month_outside_asserted_a_months_rejected
    """
    ctx = _group_with_penalty_notice(api, "226J-2026-0003")
    notice_id = ctx["notice"]["id"]

    response = api.create_penalty_evidence(
        notice_id,
        factories.penalty_evidence_payload("MEC_OFFER_PROOF", 3, document_ref="OFFER-LOG-MAR"),
        compliance_officer_headers,
    )

    validate_error(response, ApiErrorId.ERR_EVIDENCE_MONTH_NOT_ASSERTED, 422)

    notice = fixtures.read_notice(api, notice_id)
    assert_penalty_notice(notice, status="RECEIVED", evidence_count=0)

    rows, meta = validate_paginated(
        api.list_penalty_evidence(compliance_officer_headers, params={"penalty_notice_id": notice_id})
    )
    assert meta["total_count"] == 0, (
        f"a refused filing must create no evidence row, got {meta['total_count']}"
    )
    assert rows == [], f"expected no evidence rows, got {rows}"


def test_evidence_month_inside_asserted_a_months_accepted(api, compliance_officer_headers):
    """PRD §3.9: "The officer then files **PenaltyEvidence** against the notice, which
    moves it from `RECEIVED` to `EVIDENCE_GATHERING` (and is also accepted while
    already `EVIDENCE_GATHERING` or `RECOMPUTED`)."
    PRD §3.9: "Each filing increments `evidence_count`, records
    `filed_by_user_id` on the row and `last_evidence_user_id` on the notice, and
    starts life with `applied` false."

    Design: Corner/Errors/evidence_month_outside_asserted_a_months_rejected
    """
    ctx = _group_with_penalty_notice(api, "226J-2026-0003")
    notice_id = ctx["notice"]["id"]

    response = api.create_penalty_evidence(
        notice_id,
        factories.penalty_evidence_payload("MEC_OFFER_PROOF", 2, document_ref="OFFER-LOG-FEB"),
        compliance_officer_headers,
    )

    get_success_data(response)

    notice = fixtures.read_notice(api, notice_id)
    assert_penalty_notice(notice, status="EVIDENCE_GATHERING", evidence_count=1)


def test_evidence_after_response_due_date_rejected(api, compliance_officer_headers):
    """PRD §2.6: "The notice response window is still open —
    `ERR_NOTICE_RESPONSE_WINDOW_CLOSED` (409), on evidence, recompute and
    submit-response."
    PRD §3.9: "It requires a non-null `recalculated_amount_cents`, an
    `unallocated_amount_cents` of exactly zero (otherwise
    `ERR_ALLOCATION_NOT_SETTLED`), a logical clock date no later than the
    `response_due_date` — the due date itself is still inside the window — and an
    acting user who is not the notice's `last_evidence_user_id`."

    Design: Corner/Errors/evidence_after_response_due_date_rejected
    """
    ctx = _group_with_penalty_notice(api, "226J-2026-0004")
    notice_id = ctx["notice"]["id"]
    fixtures.set_clock(api, "2026-10-01T00:00:00Z")

    response = api.create_penalty_evidence(
        notice_id,
        factories.penalty_evidence_payload("MEC_OFFER_PROOF", 1, document_ref="OFFER-LOG-JAN"),
        compliance_officer_headers,
    )

    validate_error(response, ApiErrorId.ERR_NOTICE_RESPONSE_WINDOW_CLOSED, 409)

    notice = fixtures.read_notice(api, notice_id)
    assert_penalty_notice(notice, status="RECEIVED", evidence_count=0)
    assert notice["last_evidence_user_id"] is None, (
        "a refused evidence filing must not stamp last_evidence_user_id, got "
        f"{notice['last_evidence_user_id']!r}"
    )


# ---------------------------------------------------------------------------
# The furnishing window's lower bound
# ---------------------------------------------------------------------------
def test_furnish_before_reporting_year_end_rejected(api, preparer_2_headers):
    """PRD §3.7: "And the calendar must have moved on: furnishing requires the
    logical clock's date to be strictly after the 31st of December of the
    season's `tax_year`, because a statement for a year that has not ended cannot
    be delivered — at the default clock instant this always fails for a season
    whose tax year is 2026."
    PRD §2.6: "The furnishing window has opened —
    `ERR_FURNISHING_WINDOW_NOT_OPEN` (409), on furnish."

    Design: Corner/Errors/furnish_before_reporting_year_end_rejected
    """
    ctx = fixtures.determined_ale_group_with_employee(api)
    form = fixtures.generate_form(api, ctx["employee"]["id"])

    response = api.furnish_form_1095c(
        form["id"], factories.furnish_payload("PAPER"), preparer_2_headers
    )

    validate_error(response, ApiErrorId.ERR_FURNISHING_WINDOW_NOT_OPEN, 409)

    unchanged = fixtures.read_form(api, form["id"])
    assert_form_1095c(unchanged, furnishing_status="NOT_FURNISHED")


def test_furnish_after_reporting_year_end_accepted(api, preparer_2_headers):
    """PRD §3.7: "And the calendar must have moved on: furnishing requires the
    logical clock's date to be strictly after the 31st of December of the
    season's `tax_year`, because a statement for a year that has not ended cannot
    be delivered — at the default clock instant this always fails for a season
    whose tax year is 2026."
    PRD §3.7: "It is accepted only from `NOT_FURNISHED` or
    `REDELIVERY_REQUIRED`, so `furnishing_status` walks `NOT_FURNISHED` →
    `FURNISHED_PAPER` or `NOT_FURNISHED` → `FURNISHED_ELECTRONIC` on first
    delivery and `REDELIVERY_REQUIRED` → `FURNISHED_PAPER` or
    `REDELIVERY_REQUIRED` → `FURNISHED_ELECTRONIC` on redelivery."
    PRD §3.7: "A successful delivery stamps `furnished_at` and
    `furnished_by_user_id`."

    Design: Corner/Errors/furnish_before_reporting_year_end_rejected
    """
    ctx = fixtures.determined_ale_group_with_employee(api)
    form = fixtures.generate_form(api, ctx["employee"]["id"])
    fixtures.set_clock(api, "2027-01-01T00:00:00Z")

    response = api.furnish_form_1095c(
        form["id"], factories.furnish_payload("PAPER"), preparer_2_headers
    )

    furnished = validate_success(response, 200)
    assert_form_1095c(furnished, furnishing_status="FURNISHED_PAPER")
    assert furnished["furnished_at"] is not None, "a successful delivery stamps furnished_at"


# ---------------------------------------------------------------------------
# Declared uniqueness keys
# ---------------------------------------------------------------------------
def test_duplicate_tax_year_filing_season_rejected(api, compliance_officer_headers):
    """PRD §3.1: "A `ComplianceOfficer` opens the reporting year by creating a
    **FilingSeason** for one `tax_year`, which must fall between 2020 and 2035
    inclusive and must not already be taken by another season."
    PRD §2.6: "Declared uniqueness keys are free — `ERR_DUPLICATE_RESOURCE`
    (409), on filing-season, group-member, penalty-notice and furnishing-consent
    creation."

    Design: Corner/Errors/duplicate_tax_year_filing_season_rejected
    """
    fixtures.create_filing_season(api)

    response = api.create_filing_season(
        factories.filing_season_payload(
            tax_year=2026,
            furnishing_deadline_date="2027-03-15",
            filing_deadline_date="2027-04-15",
            tier2_cutoff_date="2027-09-01",
        ),
        compliance_officer_headers,
    )

    validate_error(response, ApiErrorId.ERR_DUPLICATE_RESOURCE, 409)

    rows, meta = validate_paginated(
        api.list_filing_seasons(compliance_officer_headers, params={"tax_year": 2026})
    )
    assert meta["total_count"] == 1, (
        f"tax_year 2026 must be held by exactly one season, got {meta['total_count']}"
    )
    assert_filing_season(rows[0], tax_year=2026, furnishing_deadline_date="2027-03-02")


def test_distinct_tax_year_filing_season_accepted(api, compliance_officer_headers):
    """PRD §3.1: "A `ComplianceOfficer` opens the reporting year by creating a
    **FilingSeason** for one `tax_year`, which must fall between 2020 and 2035
    inclusive and must not already be taken by another season."

    Design: Corner/Errors/duplicate_tax_year_filing_season_rejected
    """
    fixtures.create_filing_season(api)

    response = api.create_filing_season(
        factories.filing_season_payload(
            tax_year=2027,
            furnishing_deadline_date="2028-03-02",
            filing_deadline_date="2028-03-31",
            tier2_cutoff_date="2028-08-01",
        ),
        compliance_officer_headers,
    )

    created = validate_success(response, 201)
    assert_filing_season(created, tax_year=2027, status="OPEN")


def test_second_original_form_for_employee_rejected(api, preparer_headers):
    """PRD §3.6: "The employee must not already have a live original — a
    statement with `form_type` of `ORIGINAL` whose `furnishing_status` is
    anything other than `VOIDED` blocks a second one with `ERR_DUPLICATE_FORM`,
    because corrections are produced by regeneration or error resolution and
    never by generating a second original."
    PRD §3.6: "Generation also requires the employee's controlled group to be in
    `DETERMINED_ALE` or `CORRECTION_OPEN`, and it increments the member's
    `generated_form_count` and `unattached_form_count`."

    Design: Corner/Errors/second_original_form_for_employee_rejected
    """
    ctx = fixtures.determined_ale_group_with_employee(api)
    employee_id = ctx["employee"]["id"]
    first = fixtures.generate_form(api, employee_id)

    response = api.create_form_1095c(
        factories.form_1095c_payload(employee_id, plan_start_month=4, safe_harbor_preference="FPL"),
        preparer_headers,
    )

    validate_error(response, ApiErrorId.ERR_DUPLICATE_FORM, 409)

    rows, meta = validate_paginated(
        api.list_forms_1095c(preparer_headers, params={"employee_id": employee_id})
    )
    assert meta["total_count"] == 1, (
        f"the employee must still hold exactly one statement, got {meta['total_count']}"
    )
    assert_form_1095c(fixtures.read_form(api, first["id"]), plan_start_month=1, form_type="ORIGINAL")
    assert_group_member(fixtures.read_member(api, ctx["member"]["id"]), generated_form_count=1)


# ---------------------------------------------------------------------------
# A transfer must name a different member
# ---------------------------------------------------------------------------
def test_transfer_to_current_member_rejected(api, benefits_admin_headers):
    """PRD §3.4: "The destination must exist, must be `ACTIVE`, must not be the
    employee's current member, and must belong to the same controlled group as
    the employee's current member — a target in another controlled group is
    refused with `ERR_SCOPE_MISMATCH`, while a target that is the current member
    or is `INACTIVE` is refused with `ERR_TRANSFER_TARGET_INVALID`."
    PRD §3.4: "All employment changes flow through an append-only
    **EmploymentEvent** log written by a `BenefitsAdmin`, and this log is the only
    writer of an employee's `employment_status`, `termination_date` and
    `group_member_id`."

    Design: Corner/Errors/transfer_to_current_member_rejected
    """
    ctx = fixtures.determined_ale_group_with_employee(api)
    employee_id = ctx["employee"]["id"]
    member_id = ctx["member"]["id"]

    response = api.create_employment_event(
        factories.employment_event_payload(
            employee_id, "TRANSFER", "2026-06-01", to_group_member_id=member_id
        ),
        benefits_admin_headers,
    )

    validate_error(response, ApiErrorId.ERR_TRANSFER_TARGET_INVALID, 409)

    rows, meta = validate_paginated(
        api.list_employment_events(benefits_admin_headers, params={"employee_id": employee_id})
    )
    assert meta["total_count"] == 0, (
        f"a refused transfer must write no employment event, got {meta['total_count']}"
    )
    assert rows == [], f"expected no employment events, got {rows}"

    assert_employee(
        fixtures.read_employee(api, employee_id),
        group_member_id=member_id,
        employment_status="ACTIVE",
    )


# ---------------------------------------------------------------------------
# The correction-cycle limit on replacement rounds
# ---------------------------------------------------------------------------
def test_fourth_replacement_build_at_cycle_limit_rejected(api, preparer_headers):
    """PRD §3.8: "Building from `REJECTED` or `CORRECTION_REQUIRED` increments
    `cycle_number` by one, and both of those rounds — like starting a correction
    cycle — are refused with `ERR_CORRECTION_CYCLE_LIMIT` once `cycle_number`
    has reached the limit of 3."
    PRD §3.8: "A new transmittal starts at `DRAFT` with `cycle_number` 1, every
    counter at zero and null `channel`, `receipt_id`, `built_at` and
    `transmitted_at`; creating it sets the member's `open_transmittal_id` and
    increments the member's `version`."
    PRD §3.8: "A rejection creates the error rows too but moves every attached
    statement `PENDING_FILING` → `ATTACHED`, so the whole submission can be
    replaced from scratch."

    Design: Corner/Errors/fourth_replacement_build_at_cycle_limit_rejected
    """
    ctx = fixtures.determined_ale_group_with_employee(api)
    form = fixtures.generate_form(api, ctx["employee"]["id"])
    transmittal = fixtures.open_transmittal(api, ctx["member"]["id"])
    transmittal_id = transmittal["id"]
    fixtures.attach_forms(api, transmittal_id, [form["id"]])

    # One build from DRAFT leaves cycle_number 1; each rejection round advances it.
    for round_number in range(1, 4):
        fixtures.build_transmittal(api, transmittal_id)
        fixtures.transmit_transmittal(api, transmittal_id, "ELECTRONIC")
        fixtures.record_agency_response(
            api,
            transmittal_id,
            "REJECTED",
            f"AIR-2026-000{round_number}",
            errors=[
                factories.agency_error_row(
                    form["id"], error_code="AIRSH100", error_field="manifest", severity="FATAL"
                )
            ],
        )

    response = api.build_transmittal(transmittal_id, preparer_headers)

    validate_error(response, ApiErrorId.ERR_CORRECTION_CYCLE_LIMIT, 409)

    unchanged = fixtures.read_transmittal(api, transmittal_id)
    assert_transmittal(unchanged, status="REJECTED", cycle_number=3)
    assert_form_1095c(fixtures.read_form(api, form["id"]), filing_status="ATTACHED")


# ---------------------------------------------------------------------------
# Submitting the response requires a settled allocation
# ---------------------------------------------------------------------------
def test_submit_response_with_unallocated_cents_rejected(api, compliance_officer_2_headers):
    """PRD §3.9: "An officer who wants to redo the split can reset the
    allocation, a compensating action for step 6 alone: it requires the notice to
    be `RECOMPUTED` with `allocated_total_cents` above zero, zeroes every
    `ACTIVE` member's `allocated_penalty_cents`, sets `allocated_total_cents` to
    0 and moves the whole `recalculated_amount_cents` into
    `unallocated_amount_cents`."
    PRD §3.9: "It requires a non-null `recalculated_amount_cents`, an
    `unallocated_amount_cents` of exactly zero (otherwise
    `ERR_ALLOCATION_NOT_SETTLED`), a logical clock date no later than the
    `response_due_date` — the due date itself is still inside the window — and an
    acting user who is not the notice's `last_evidence_user_id`."

    Design: Corner/Errors/submit_response_with_unallocated_cents_rejected
    """
    ctx = _recomputed_notice(api, "226J-2026-0005")
    notice_id = ctx["notice"]["id"]
    fixtures.reset_allocation(api, notice_id)

    response = api.submit_penalty_response(notice_id, compliance_officer_2_headers)

    validate_error(response, ApiErrorId.ERR_ALLOCATION_NOT_SETTLED, 409)

    notice = fixtures.read_notice(api, notice_id)
    assert_penalty_notice(notice, status="RECOMPUTED", allocated_total_cents=0)
    assert notice["recalculated_amount_cents"] > 0, (
        "the recomputation must have priced a surviving asserted month, got "
        f"{notice['recalculated_amount_cents']}"
    )
    assert notice["unallocated_amount_cents"] == notice["recalculated_amount_cents"], (
        "the reset moves the whole recalculated amount into unallocated_amount_cents: "
        f"{notice['unallocated_amount_cents']} vs {notice['recalculated_amount_cents']}"
    )
    assert notice["response_submitted_at"] is None, (
        "a refused submission must not stamp response_submitted_at, got "
        f"{notice['response_submitted_at']!r}"
    )
    assert_group_member(fixtures.read_member(api, ctx["member"]["id"]), allocated_penalty_cents=0)


# ---------------------------------------------------------------------------
# The agency determination's amount must agree with the determination
# ---------------------------------------------------------------------------
def test_abated_full_with_partial_amount_rejected(
    api, compliance_officer_headers, compliance_officer_2_headers
):
    """PRD §3.9: "`ABATED_FULL` requires `abated_amount_cents` to equal
    `proposed_amount_cents` exactly; it records the `determination` and the
    amount, zeroes every `ACTIVE` member's `allocated_penalty_cents` and sets
    `unallocated_amount_cents` to 0."
    PRD §3.9: "Amounts that contradict the determination are refused with
    `ERR_ABATEMENT_AMOUNT_INVALID`."

    Design: Corner/Errors/abated_full_with_partial_amount_rejected
    """
    ctx = _recomputed_notice(api, "226J-2026-0006")
    notice_id = ctx["notice"]["id"]
    fixtures.submit_response(api, notice_id, headers=compliance_officer_2_headers)

    response = api.record_agency_determination(
        notice_id,
        factories.agency_determination_payload("ABATED_FULL", abated_amount_cents=271600),
        compliance_officer_headers,
    )

    validate_error(response, ApiErrorId.ERR_ABATEMENT_AMOUNT_INVALID, 422)

    notice = fixtures.read_notice(api, notice_id)
    assert_penalty_notice(notice, status="RESPONSE_SUBMITTED")
    assert notice["abated_amount_cents"] is None, (
        f"a refused determination must not record an amount, got {notice['abated_amount_cents']!r}"
    )
    assert notice["determination"] is None, (
        f"a refused determination must not be recorded, got {notice['determination']!r}"
    )


def test_abated_partial_with_same_amount_accepted(
    api, compliance_officer_headers, compliance_officer_2_headers
):
    """PRD §3.9: "`ABATED_PARTIAL` requires `abated_amount_cents` to be strictly
    above 0 and strictly below `proposed_amount_cents`; it records the
    `determination` and the amount and leaves the member allocations exactly
    where they are, as the sustained split."

    Design: Corner/Errors/abated_full_with_partial_amount_rejected
    """
    ctx = _recomputed_notice(api, "226J-2026-0006")
    notice_id = ctx["notice"]["id"]
    fixtures.submit_response(api, notice_id, headers=compliance_officer_2_headers)

    response = api.record_agency_determination(
        notice_id,
        factories.agency_determination_payload("ABATED_PARTIAL", abated_amount_cents=271600),
        compliance_officer_headers,
    )

    determined = validate_success(response, 200)
    assert_penalty_notice(
        determined, determination="ABATED_PARTIAL", abated_amount_cents=271600
    )


def test_sustained_with_nonzero_abated_amount_rejected(
    api, compliance_officer_headers, compliance_officer_2_headers
):
    """PRD §3.9: "`SUSTAINED` requires `abated_amount_cents` to be exactly 0; it
    records the determination and that zero, then reallocates the **full**
    `proposed_amount_cents` across the group's `ACTIVE` members by
    `reporting_year_ft_months` under the same largest-remainder rule, so
    `allocated_total_cents` ends up equal to `proposed_amount_cents`."
    PRD §3.9: "Amounts that contradict the determination are refused with
    `ERR_ABATEMENT_AMOUNT_INVALID`."

    Design: Corner/Errors/abated_full_with_partial_amount_rejected
    """
    ctx = _recomputed_notice(api, "226J-2026-0006")
    notice_id = ctx["notice"]["id"]
    fixtures.submit_response(api, notice_id, headers=compliance_officer_2_headers)

    response = api.record_agency_determination(
        notice_id,
        factories.agency_determination_payload("SUSTAINED", abated_amount_cents=1000),
        compliance_officer_headers,
    )

    validate_error(response, ApiErrorId.ERR_ABATEMENT_AMOUNT_INVALID, 422)

    notice = fixtures.read_notice(api, notice_id)
    assert_penalty_notice(notice, status="RESPONSE_SUBMITTED")
    assert notice["determination"] is None, (
        f"a refused determination must not be recorded, got {notice['determination']!r}"
    )
