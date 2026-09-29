"""Two adjacent pairs on the rejection ladder, checked from the losing side."""
from test_helpers import (
    ANALYST,
    INVESTIGATOR,
    RENEWAL_CLOCK,
    ApiClient,
    ApiErrorId,
    assert_license_dimensions,
    assert_renewal_dimensions,
    change_status,
    reread_complaint,
    reread_license,
    reread_renewal,
    seed_active_license,
    seed_ce_record,
    seed_investigated_complaint,
    seed_renewal,
    validate_error,
    validate_paginated,
)


def _unpaid_filing_on_an_inactive_credential(api: ApiClient):
    """A draft filing with sufficient credit, no payment, and a credential that
    has since been placed on inactive status."""
    ctx = seed_active_license(
        api,
        program_overrides={
            "program_code": "OH-BSN-61",
            "program_name": "Wooster BSN",
            "degree_level": "BSN",
            "nclex_first_time_pass_rate_bp": 8300,
        },
        nurse_overrides={"full_name": "Ines Duarte", "birth_year": 1987,
                         "ssn_last4": "8891"},
    )
    renewal = seed_renewal(api, ctx["license_id"], clock=RENEWAL_CLOCK,
                           attested_practice_hours=1500)
    seed_ce_record(api, renewal["id"], provider_code="OHNA-700",
                   provider_accredited=True, category="LIVE_CONTACT", minutes=1800,
                   completion_date="2027-06-01T00:00:00Z")
    ctx["license"] = change_status(api, ctx["license_id"], "INACTIVE")
    ctx["renewal"] = renewal
    ctx["renewal_id"] = renewal["id"]
    return ctx


def test_submit_on_an_inactive_credential_reports_not_renewable_not_unpaid_fee(
    api: ApiClient,
):
    """PRD §3.4: "Because the renewability check outranks the fiscal check, a
    submit on a credential that is neither `ACTIVE` nor within its grace window
    reports `ERR_LICENSE_NOT_RENEWABLE` even when nothing has been paid."

    PRD §2.11: "And a submit attempt on an unrenewable credential with no fee
    paid reports `ERR_LICENSE_NOT_RENEWABLE`, because check 11 precedes check 35."

    PRD §2.11: "The credential is renewable: its `license_status` is `ACTIVE` or
    `EXPIRED`, and when it is `EXPIRED` the logical clock is at or before its
    `expires_on` plus the board's `renewal_grace_period_days`. Otherwise
    `ERR_LICENSE_NOT_RENEWABLE`. This applies when a renewal is created, when it
    is paid, and when it is submitted."

    Design: Difficulty/priority_pair_validation_conflict/renewal_submit_state_check_beats_unpaid_fee_check
    """
    ctx = _unpaid_filing_on_an_inactive_credential(api)

    response = api.submit_renewal_application(ctx["renewal_id"], ANALYST)

    validate_error(response, ApiErrorId.ERR_LICENSE_NOT_RENEWABLE.value)


def test_rejected_submit_leaves_the_filing_and_the_credential_untouched(
    api: ApiClient,
):
    """PRD §3.4: "The fee must be settled: `fee_applied_cents` must be greater
    than zero and `fee_paid_cents` must be at least `fee_applied_cents`, and an
    unassessed or underpaid filing is refused with `ERR_RENEWAL_FEE_UNPAID`."

    PRD §3.4: "The filing begins with `renewal_status` `DRAFT` and `audit_status`
    `NOT_SELECTED`, with `ce_credit_hours_provisional`, `ce_credit_hours_audited`,
    `verified_practice_hours`, `audit_risk_score`, and `submitted_at` all null,
    `fee_applied_cents`, `fee_paid_cents`, `late_days`, and
    `doc_request_cycle_count` all 0, and `practice_hour_periods` an empty array."

    PRD §2.6: "`version` (integer): a counter that starts at 1 when the record is
    created and increments by exactly 1 on every mutation, including mutations
    that only touch derived fields."

    Design: Difficulty/priority_pair_validation_conflict/renewal_submit_state_check_beats_unpaid_fee_check
    """
    ctx = _unpaid_filing_on_an_inactive_credential(api)
    license_version_before = ctx["license"]["version"]

    validate_error(api.submit_renewal_application(ctx["renewal_id"], ANALYST),
                   ApiErrorId.ERR_LICENSE_NOT_RENEWABLE.value)

    renewal = reread_renewal(api, ctx["renewal_id"])
    assert_renewal_dimensions(renewal, "DRAFT", "NOT_SELECTED")
    assert renewal["fee_applied_cents"] == 0, (
        f"No assessment ran, got {renewal['fee_applied_cents']}"
    )
    assert renewal["fee_paid_cents"] == 0, (
        f"No money was received, got {renewal['fee_paid_cents']}"
    )
    assert renewal["submitted_at"] is None, (
        f"The rejected submit stamped nothing, got {renewal['submitted_at']}"
    )

    credential = reread_license(api, ctx["license_id"])
    assert_license_dimensions(credential, "INACTIVE", "CLEAR")
    assert credential["version"] == license_version_before, (
        f"A rejected request mutates nothing: version moved from "
        f"{license_version_before} to {credential['version']}"
    )


def _open_investigation_with_one_linked_custodian(api: ApiClient):
    """An open investigation whose only linked custodian is the primary employer."""
    ctx = seed_active_license(
        api,
        program_overrides={
            "program_code": "OH-BSN-71",
            "program_name": "Zanesville BSN",
            "degree_level": "BSN",
            "nclex_first_time_pass_rate_bp": 8100,
        },
        nurse_overrides={"full_name": "Grant Ozawa", "birth_year": 1991,
                         "ssn_last4": "3377"},
    )
    complaint = seed_investigated_complaint(
        api, ctx["license_id"],
        complainant_type="PATIENT",
        violation_category="PRACTICE_STANDARD",
        incident_date="2026-07-22T00:00:00Z",
        employer_custodian_codes=["MERCY-GEN"],
    )
    ctx["complaint"] = complaint
    ctx["complaint_id"] = complaint["id"]
    return ctx


_UNAUTHORISED_UNLINKED_DEMAND = {
    "record_class": "PATIENT_CHART",
    "custodian_code": "UNLINKED-CLINIC",
    "hold_start_at": "2026-08-05T00:00:00Z",
    "hold_end_at": "2026-09-05T00:00:00Z",
}


def test_unauthorised_patient_chart_demand_reports_phi_not_unlinked_custodian(
    api: ApiClient,
):
    """PRD §3.6: "Because the authorisation rule is evaluated before the capacity
    rule, a request for a patient chart with no authorisation against a saturated
    custodian reports the authorisation failure."

    PRD §2.11: "A patient-chart demand that is both unauthorised and aimed at a
    custodian not named on the complaint reports
    `ERR_PHI_AUTHORIZATION_REQUIRED`, because check 13 precedes check 14."

    PRD §3.6: "First, protected health information requires authorisation: when
    `record_class` is `PATIENT_CHART` or `PHARMACY_DISPENSING`, a non-empty
    `phi_authorization_id` must be present, and its absence is refused with
    `ERR_PHI_AUTHORIZATION_REQUIRED`."

    Design: Difficulty/priority_pair_validation_conflict/phi_safety_check_beats_custodian_referential_check
    """
    ctx = _open_investigation_with_one_linked_custodian(api)

    response = api.create_evidence_request(ctx["complaint_id"],
                                           dict(_UNAUTHORISED_UNLINKED_DEMAND),
                                           INVESTIGATOR)

    validate_error(response, ApiErrorId.ERR_PHI_AUTHORIZATION_REQUIRED.value)


def test_rejected_demand_creates_no_record_and_leaves_the_complaint_alone(
    api: ApiClient,
):
    """PRD §3.6: "Second, the custodian must be linked to the complaint:
    `custodian_code` must appear in the complaint's `employer_custodian_codes`,
    and a demand served on an unlinked custodian is refused with
    `ERR_CUSTODIAN_NOT_LINKED`."

    PRD §3.6: "**Opening the investigation** moves `status` from `TRIAGED` to
    `INVESTIGATION_OPEN`, records the acting investigator in
    `investigator_user_id`, and cascades onto the credential and the nurse."

    PRD §2.6: "`version` (integer): a counter that starts at 1 when the record is
    created and increments by exactly 1 on every mutation, including mutations
    that only touch derived fields."

    Design: Difficulty/priority_pair_validation_conflict/phi_safety_check_beats_custodian_referential_check
    """
    ctx = _open_investigation_with_one_linked_custodian(api)
    complaint_version_before = ctx["complaint"]["version"]

    validate_error(
        api.create_evidence_request(ctx["complaint_id"],
                                    dict(_UNAUTHORISED_UNLINKED_DEMAND),
                                    INVESTIGATOR),
        ApiErrorId.ERR_PHI_AUTHORIZATION_REQUIRED.value,
    )

    demands, meta = validate_paginated(
        api.list_complaint_evidence_requests(ctx["complaint_id"], INVESTIGATOR)
    )
    assert demands == [], f"The rejected demand must not persist, got {demands}"
    assert meta["total_count"] == 0, (
        f"No records demand exists on this complaint, got {meta['total_count']}"
    )

    complaint = reread_complaint(api, ctx["complaint_id"])
    assert complaint["status"] == "INVESTIGATION_OPEN"
    assert complaint["version"] == complaint_version_before, (
        f"A rejected request mutates nothing: version moved from "
        f"{complaint_version_before} to {complaint['version']}"
    )
