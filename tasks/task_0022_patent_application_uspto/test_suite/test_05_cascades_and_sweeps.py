"""Transitive cascades: pay-issue-fee transitions Application to ISSUED and
generates the three MaintenanceFee rows for UTILITY (a depth-3 cascade); the
deadline sweeper expires an OUTSTANDING OA past its maximum_due_date and
cascades the parent Application to ABANDONED.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS, make_applicant_headers,
    set_clock, run_sweep,
    setup_application_in_allowed, setup_application_with_outstanding_oa,
    get_application, pay_issue_fee, list_maintenance_fees,
    issue_fee_cents,
)


# =============================================================================
# Difficulty / transitive_cascade / pay_issue_fee_cascades_to_maintenance_generation
# =============================================================================

def test_pay_issue_fee_transitions_to_issued_and_generates_three_maintenance_rows(api):
    """One pay-issue-fee call must produce: (1) Application.status=ISSUED;
    (2) total_fees_paid_cents recomputed to FILING+ISSUE; (3) exactly three
    PENDING MaintenanceFee rows minted for the UTILITY.

    PRD §3.7: "For a `UTILITY` patent only, issuance generates three
    `MaintenanceFee` rows in `PENDING`, one per maintenance window."
    PRD §3.7: "When the request succeeds, a `FeePayment` is appended to the
    ledger with `payment_category` set to `ISSUE` and `payment_status` set
    to `POSTED`; the application advances from `ALLOWED` to `ISSUED`;
    `issued_patent_number` is minted as a server-generated string of the
    form `US{seq}` where `seq` is a monotonically increasing sequence;
    `issue_date` is stamped to the server's current UTC instant; and
    `term_expiration_date` is computed by application type."

    Design: Difficulty/transitive_cascade/pay_issue_fee_cascades_to_maintenance_generation
    """
    set_clock("2026-01-01T00:00:00.000Z")
    applicant, application = setup_application_in_allowed(
        entity_size="SMALL", application_type="UTILITY",
    )
    issued = pay_issue_fee(applicant, application)

    assert issued["status"] == "ISSUED", (
        f"Application must transition to ISSUED, got {issued['status']}"
    )
    # FILING (SMALL UTILITY 16000) + ISSUE (SMALL UTILITY 60000) = 76000
    expected_total = 16000 + issue_fee_cents("UTILITY", "SMALL")
    assert expected_total == 76000
    assert issued["total_fees_paid_cents"] == 76000

    fees = list_maintenance_fees(issued["id"], applicant)
    assert len(fees) == 3, (
        f"Issued UTILITY must have exactly 3 MaintenanceFee rows, got {len(fees)}"
    )
    windows = sorted([f["window_number"] for f in fees])
    assert windows == [1, 2, 3]
    for f in fees:
        assert f["fee_status"] == "PENDING"


def test_pay_issue_fee_mints_issued_patent_number_and_issue_date(api):
    """The same pay-issue-fee call also mints issued_patent_number and
    stamps issue_date — both null until issuance.

    PRD §3.7: "When the request succeeds, a `FeePayment` is appended to the
    ledger with `payment_category` set to `ISSUE` and `payment_status` set
    to `POSTED`; the application advances from `ALLOWED` to `ISSUED`;
    `issued_patent_number` is minted as a server-generated string of the
    form `US{seq}` where `seq` is a monotonically increasing sequence;
    `issue_date` is stamped to the server's current UTC instant..."

    Design: Difficulty/transitive_cascade/pay_issue_fee_cascades_to_maintenance_generation
    """
    set_clock("2026-01-01T00:00:00.000Z")
    applicant, application = setup_application_in_allowed(
        entity_size="SMALL", application_type="UTILITY",
    )
    # PRD §3.2: issued_patent_number and issue_date are null until issuance.
    # (Field may either be absent or explicitly null pre-issuance.)
    assert not application.get("issued_patent_number"), (
        f"issued_patent_number must be null/absent pre-issuance, got "
        f"{application.get('issued_patent_number')!r}"
    )
    assert not application.get("issue_date"), (
        f"issue_date must be null/absent pre-issuance, got "
        f"{application.get('issue_date')!r}"
    )

    issued = pay_issue_fee(applicant, application)
    assert issued.get("issued_patent_number"), (
        "issued_patent_number must be minted on issuance, got "
        f"{issued.get('issued_patent_number')!r}"
    )
    assert isinstance(issued["issued_patent_number"], str)
    assert issued["issued_patent_number"].startswith("US"), (
        f"issued_patent_number must be of form 'US{{seq}}', got "
        f"{issued['issued_patent_number']!r}"
    )
    assert issued.get("issue_date") == "2026-01-01T00:00:00.000Z", (
        f"issue_date must be stamped to current UTC, got {issued.get('issue_date')!r}"
    )


# =============================================================================
# Difficulty / transitive_cascade / deadline_sweep_cascades_oa_expiry_to_application_abandonment
# =============================================================================

def test_deadline_sweep_expires_oa_and_abandons_application(api):
    """Sweep with current_utc past an OUTSTANDING OA's maximum_due_date:
    hop1 the OA flips to EXPIRED; hop2 the parent Application flips to
    ABANDONED.

    PRD §3.6: "Abandonment happens when the deadline sweeper observes that
    an `OUTSTANDING` office action's `maximum_due_date` has passed without
    an `ACCEPTED` response. When the sweep runs and finds at least one such
    office action attached to an application still in
    `OFFICE_ACTION_OUTSTANDING`, the cascade fires: every `OUTSTANDING`
    office action on that application flips to `EXPIRED` (each bumping its
    own version), and the application's status flips to `ABANDONED` with a
    version bump."

    Design: Difficulty/transitive_cascade/deadline_sweep_cascades_oa_expiry_to_application_abandonment
    """
    set_clock("2026-01-01T00:00:00.000Z")
    applicant, application, oa = setup_application_with_outstanding_oa(
        entity_size="LARGE", action_type="NON_FINAL",
    )
    # Advance past max_due (issue_date + 6mo).
    set_clock("2026-07-02T00:00:00.000Z")
    run_sweep()

    oa_after = validate_success(
        api.get_office_action(oa["id"], TEST_USERS["examiner_headers"]),
        200,
    )
    app_after = get_application(application["id"], applicant)
    assert oa_after["status"] == "EXPIRED", (
        f"OA past max_due must be EXPIRED after sweep, got {oa_after['status']}"
    )
    assert app_after["status"] == "ABANDONED", (
        f"Parent Application must cascade to ABANDONED, got {app_after['status']}"
    )


def test_deadline_sweep_reports_counters_for_this_sweep(api, admin_headers):
    """The sweep response surfaces per-cascade counters describing only that
    single sweep's effects.

    PRD §3.11: "The sweep response surfaces five integer counters —
    `applications_abandoned`, `applications_expired`, `provisionals_expired`,
    `maintenance_fees_lapsed`, and `office_actions_expired` — each counting
    only the rows that this particular sweep call mutated."

    Design: Difficulty/transitive_cascade/deadline_sweep_cascades_oa_expiry_to_application_abandonment
    """
    set_clock("2026-01-01T00:00:00.000Z")
    applicant, application, oa = setup_application_with_outstanding_oa(
        entity_size="LARGE", action_type="NON_FINAL",
    )
    set_clock("2026-07-02T00:00:00.000Z")
    sweep_res = api.sweep_deadlines(admin_headers)
    counters = validate_success(sweep_res, 200)

    assert counters.get("applications_abandoned") == 1, (
        f"Expected 1 application abandoned this sweep, got "
        f"{counters.get('applications_abandoned')}"
    )
    assert counters.get("office_actions_expired") == 1, (
        f"Expected 1 OA expired this sweep, got "
        f"{counters.get('office_actions_expired')}"
    )
