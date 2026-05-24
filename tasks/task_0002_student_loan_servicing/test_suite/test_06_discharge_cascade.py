"""Discharge applications: branching review paths (approve / deny), the
three-hop PSLF cascade, the veteran-discharge prerequisite, and the role
gating on the approve endpoint.
"""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_error_is_one_of,
    create_discharge_application_payload, approve_discharge_payload,
    TEST_USERS,
    advance_clock, create_borrower, get_loan, get_loan_version,
    setup_veteran_discharge_ready,
    setup_pslf_discharge_ready,
    make_va_officer_headers,
)


# ─── Difficulty Rule 3b: branching review paths ─────


def test_discharge_application_approve_branch_sets_status_and_actor(
    api, servicer_headers,
):
    """PRD §3.7: "On a successful approval, the application's `status`
    becomes `APPROVED` and the acting `X-User-ID` is stamped as
    `approved_by_user_id`."

    With two veteran-discharge applications on the same borrower (and no
    loans, so the approve cascade has nothing to do), approving one sets
    status=APPROVED and stamps approved_by_user_id with the acting
    VADischargeOfficer's X-User-ID.

    Design: Difficulty/non_linear_state_machine/discharge_application_branching_review_paths
    """
    advance_clock("2026-06-01T00:00:00Z")
    borrower = create_borrower(email="branch-approve@example.com", military_status="VETERAN")
    app_a = validate_success(api.create_discharge_application(
        create_discharge_application_payload(
            borrower["id"], "VETERAN_TOTAL_PERMANENT_DISABILITY",
            "2026-06-01", va_certification_doc_id="VA-DOC-A",
        ), servicer_headers,
    ), 201)
    validate_success(api.begin_review_discharge_application(
        app_a["id"], TEST_USERS["va_officer_headers"],
    ), 200)

    # Empty expected_loan_version_by_loan_id — borrower has no non-terminal loans.
    approved_res = api.approve_discharge_application(
        app_a["id"], approve_discharge_payload({}), TEST_USERS["va_officer_headers"],
    )
    approved = validate_success(approved_res, 200)
    assert approved["status"] == "APPROVED"
    # PRD §3.7 stamps approved_by_user_id with the acting X-User-ID.
    assert approved["approved_by_user_id"] == "vad-test-1"


def test_discharge_application_deny_branch_sets_status_denied_only(
    api, servicer_headers,
):
    """PRD §3.7: "The deny path moves the application's `status` to `DENIED`
    and has no further side effects."

    Deny leaves status=DENIED and does NOT stamp the application with the
    acting actor as approved_by_user_id (the field is reserved for the
    approve path).

    Design: Difficulty/non_linear_state_machine/discharge_application_branching_review_paths
    """
    advance_clock("2026-06-01T00:00:00Z")
    borrower = create_borrower(email="branch-deny@example.com", military_status="VETERAN")
    app_b = validate_success(api.create_discharge_application(
        create_discharge_application_payload(
            borrower["id"], "VETERAN_TOTAL_PERMANENT_DISABILITY",
            "2026-06-01", va_certification_doc_id="VA-DOC-B",
        ), servicer_headers,
    ), 201)
    validate_success(api.begin_review_discharge_application(
        app_b["id"], TEST_USERS["va_officer_headers"],
    ), 200)
    denied_res = api.deny_discharge_application(
        app_b["id"], TEST_USERS["va_officer_headers"],
    )
    denied = validate_success(denied_res, 200)
    assert denied["status"] == "DENIED"
    # Approve-only field MUST NOT carry the deny actor's id.
    actor = denied.get("approved_by_user_id")
    assert actor in (None, ""), (
        f"approved_by_user_id should not be stamped on the deny path; got {actor!r}"
    )


# ─── Difficulty Rule 4a: PSLF three-hop cascade ──────


def test_pslf_discharge_approval_cascades_tracker_loan_and_plan(
    api, servicer_headers,
):
    """PRD §3.7: "On a successful approval, the application's `status`
    becomes `APPROVED` and the acting `X-User-ID` is stamped as
    `approved_by_user_id`."
    PRD §3.7: "Finally, when `discharge_type` is `PSLF_FORGIVENESS`, the
    borrower's `PSLFTracker` advances from `ELIGIBLE_FOR_FORGIVENESS` to
    `FORGIVEN`."
    PRD §3.2: "When a discharge approval cascades into the loan, the
    loan's `status` advances directly to `DISCHARGED` from whichever
    non-terminal state it occupied; the loan's `outstanding_principal_cents`
    and `accrued_interest_cents` are left as historical record (no further
    accrual occurs), any open `DelinquencyRecord` closes with `outcome` of
    `CURED`, and any `ACTIVE` `RepaymentPlan` on the loan transitions to
    `EXPIRED`."

    A single approve POST cascades through four hops:
    DischargeApplication → APPROVED, PSLFTracker → FORGIVEN, Loan →
    DISCHARGED, RepaymentPlan → EXPIRED.

    Design: Difficulty/transitive_cascade/pslf_discharge_approval_three_hop_cascade
    """
    borrower, loan_latest, plan, tracker, app = setup_pslf_discharge_ready(
        adjudicator_user_id="adj-test-1",
    )
    # Refresh loan version right before approve.
    loan_v = get_loan_version(loan_latest["id"])
    h_adj = TEST_USERS["pslf_adjudicator_headers"]
    res = api.approve_discharge_application(
        app["id"],
        approve_discharge_payload({loan_latest["id"]: loan_v}),
        h_adj,
    )
    approved = validate_success(res, 200)
    assert approved["status"] == "APPROVED"

    tracker_after = validate_success(api.get_pslf_tracker(tracker["id"], h_adj), 200)
    assert tracker_after["status"] == "FORGIVEN"

    loan_after = get_loan(loan_latest["id"])
    assert loan_after["status"] == "DISCHARGED"

    plan_after = validate_success(api.get_repayment_plan(
        plan["id"], TEST_USERS["servicer_headers"],
    ), 200)
    assert plan_after["status"] == "EXPIRED"


def test_pslf_discharge_approval_stamps_total_discharged_principal_pre_cascade(
    api, servicer_headers,
):
    """PRD §3.7: "Before the cascade fires, the system snapshots the sum of
    `outstanding_principal_cents` across every non-terminal loan of the
    borrower and stores it on the application as
    `total_discharged_principal_cents` (so that the field reflects the
    pre-cascade balances)."

    Design: Difficulty/transitive_cascade/pslf_discharge_approval_three_hop_cascade
    """
    borrower, loan_latest, plan, tracker, app = setup_pslf_discharge_ready(
        adjudicator_user_id="adj-test-1",
    )
    pre_cascade_principal = get_loan(loan_latest["id"])["outstanding_principal_cents"]
    loan_v = get_loan_version(loan_latest["id"])
    h_adj = TEST_USERS["pslf_adjudicator_headers"]
    res = api.approve_discharge_application(
        app["id"],
        approve_discharge_payload({loan_latest["id"]: loan_v}),
        h_adj,
    )
    approved = validate_success(res, 200)
    assert approved["status"] == "APPROVED"
    assert approved["total_discharged_principal_cents"] == pre_cascade_principal


# ─── Difficulty Rule 7a: cross-entity payment guard ──


def test_payment_creation_on_fully_discharged_borrower_returns_borrower_discharged(
    api, servicer_headers,
):
    """PRD §3.4: "an attempt against a `PAID_OFF` or `DISCHARGED` loan is
    rejected with `ERR_INVALID_STATE`. The system additionally refuses
    to accept a payment for any borrower whose every loan sits in
    `DISCHARGED` or `PAID_OFF`, returning `ERR_BORROWER_DISCHARGED`;
    this is the cross-entity guard that prevents stray payments from
    arriving on a borrower the system considers closed out."
    PRD §3.7: "The cascade then transitions every non-terminal loan of the
    borrower to `DISCHARGED`..."
    PRD §2.9: "State preconditions for the requested action come next,
    with `ERR_INVALID_STATE` for in-entity violations and a small family
    of cross-entity state errors (`ERR_BORROWER_DISCHARGED` for payment
    attempts on a fully-discharged borrower, ...) following immediately."

    Veteran borrower, single loan, approved VA discharge cascades the
    loan to DISCHARGED. A subsequent POST /v1/payments must trip a
    state-tier rejection (HTTP 409). With a single loan, BOTH the
    in-entity check (the target loan is DISCHARGED → ERR_INVALID_STATE)
    and the cross-entity guard (every loan is DISCHARGED →
    ERR_BORROWER_DISCHARGED) apply; the PRD's "following immediately"
    wording in §2.9 does not uniquely fix which fires first, so the
    assertion accepts either PRD-faithful answer.

    Design: Difficulty/cross_entity_state_dependency/payment_creation_requires_loan_not_paidoff_or_discharged
    """
    advance_clock("2026-06-01T00:00:00Z")
    # Veteran borrower + loan + approved VA discharge.
    borrower = create_borrower(email="cross-discharge@example.com", military_status="VETERAN")
    loan = validate_success(api.create_loan({
        "borrower_id": borrower["id"],
        "loan_type": "DIRECT_UNSUBSIDIZED",
        "original_principal_cents": 2_000_000,
        "interest_rate_bps": 533,
        "disbursement_date": "2025-06-01",
    }, TEST_USERS["servicer_headers"]), 201)
    app = validate_success(api.create_discharge_application(
        create_discharge_application_payload(
            borrower["id"], "VETERAN_TOTAL_PERMANENT_DISABILITY",
            "2026-06-01", va_certification_doc_id="VA-DOC-99",
        ), TEST_USERS["servicer_headers"],
    ), 201)
    validate_success(api.begin_review_discharge_application(
        app["id"], TEST_USERS["va_officer_headers"],
    ), 200)
    loan_v = get_loan_version(loan["id"])
    validate_success(api.approve_discharge_application(
        app["id"],
        approve_discharge_payload({loan["id"]: loan_v}),
        TEST_USERS["va_officer_headers"],
    ), 200)
    loan_after = get_loan(loan["id"])
    assert loan_after["status"] == "DISCHARGED"

    res = api.create_payment(
        {
            "loan_id": loan["id"],
            "amount_cents": 1_000,
            "posted_on": "2026-06-01",
            "source": "ACH",
        },
        TEST_USERS["servicer_headers"],
    )
    assert res.status_code == 409, f"Expected 409, got {res.status_code}: {res.text}"
    validate_error_is_one_of(res, ["ERR_BORROWER_DISCHARGED", "ERR_INVALID_STATE"])


def test_payment_creation_on_fully_discharged_borrower_returns_409(api, servicer_headers):
    """PRD §3.4: "The system additionally refuses to accept a payment for
    any borrower whose every loan sits in `DISCHARGED` or `PAID_OFF`,
    returning `ERR_BORROWER_DISCHARGED`; this is the cross-entity guard
    that prevents stray payments from arriving on a borrower the system
    considers closed out."
    PRD §5 (error table): "`ERR_BORROWER_DISCHARGED` | 409 Conflict".

    The error is HTTP 409 — a conflict, not a 422 unprocessable-entity.

    Design: Difficulty/cross_entity_state_dependency/payment_creation_requires_loan_not_paidoff_or_discharged
    """
    advance_clock("2026-06-01T00:00:00Z")
    borrower = create_borrower(email="cross-discharge-2@example.com", military_status="VETERAN")
    loan = validate_success(api.create_loan({
        "borrower_id": borrower["id"],
        "loan_type": "DIRECT_UNSUBSIDIZED",
        "original_principal_cents": 2_000_000,
        "interest_rate_bps": 533,
        "disbursement_date": "2025-06-01",
    }, TEST_USERS["servicer_headers"]), 201)
    app = validate_success(api.create_discharge_application(
        create_discharge_application_payload(
            borrower["id"], "VETERAN_TOTAL_PERMANENT_DISABILITY",
            "2026-06-01", va_certification_doc_id="VA-DOC-100",
        ), TEST_USERS["servicer_headers"],
    ), 201)
    validate_success(api.begin_review_discharge_application(
        app["id"], TEST_USERS["va_officer_headers"],
    ), 200)
    loan_v = get_loan_version(loan["id"])
    validate_success(api.approve_discharge_application(
        app["id"],
        approve_discharge_payload({loan["id"]: loan_v}),
        TEST_USERS["va_officer_headers"],
    ), 200)
    loan_after = get_loan(loan["id"])
    assert loan_after["status"] == "DISCHARGED"

    res = api.create_payment(
        {
            "loan_id": loan["id"],
            "amount_cents": 1_000,
            "posted_on": "2026-06-01",
            "source": "ACH",
        },
        TEST_USERS["servicer_headers"],
    )
    assert res.status_code == 409, (
        f"ERR_BORROWER_DISCHARGED must be HTTP 409; got {res.status_code}"
    )


def test_discharge_application_filing_against_civilian_returns_not_veteran(
    api, servicer_headers,
):
    """PRD §3.7: "Filing a veteran discharge additionally requires that the
    borrower's `military_status` already be either `VETERAN` or
    `DISABLED_VETERAN`; if not, the filing itself is rejected with
    `ERR_NOT_VETERAN`."

    Design: Difficulty/cross_entity_state_dependency/discharge_application_requires_borrower_veteran_status
    """
    advance_clock("2026-06-01T00:00:00Z")
    borrower = create_borrower(email="not-vet@example.com", military_status="NONE")
    res = api.create_discharge_application(
        create_discharge_application_payload(
            borrower["id"], "VETERAN_TOTAL_PERMANENT_DISABILITY",
            "2026-06-01", va_certification_doc_id="VA-DOC-X",
        ),
        servicer_headers,
    )
    validate_error(res, "ERR_NOT_VETERAN", expected_status=422)


# ─── VA-doc rule (corner) ───────────────────────────


def test_discharge_application_against_active_duty_borrower_returns_not_veteran(
    api, servicer_headers,
):
    """PRD §3.7: "Filing a veteran discharge additionally requires that the
    borrower's `military_status` already be either `VETERAN` or
    `DISABLED_VETERAN`; if not, the filing itself is rejected with
    `ERR_NOT_VETERAN`."

    ACTIVE_DUTY is a non-{VETERAN, DISABLED_VETERAN} military_status, so
    the filing must still be rejected with ERR_NOT_VETERAN.

    Design: Difficulty/cross_entity_state_dependency/discharge_application_requires_borrower_veteran_status
    """
    advance_clock("2026-06-01T00:00:00Z")
    borrower = create_borrower(email="active-duty@example.com", military_status="ACTIVE_DUTY")
    res = api.create_discharge_application(
        create_discharge_application_payload(
            borrower["id"], "VETERAN_TOTAL_PERMANENT_DISABILITY",
            "2026-06-01", va_certification_doc_id="VA-DOC-Y",
        ),
        servicer_headers,
    )
    validate_error(res, "ERR_NOT_VETERAN", expected_status=422)


def test_va_doc_supplied_for_non_veteran_discharge_returns_invalid(
    api, servicer_headers,
):
    """PRD §3.7: "The application carries an optional
    `va_certification_doc_id` whose presence is tightly coupled to
    `discharge_type`: it is required and must be non-null when
    `discharge_type` is `VETERAN_TOTAL_PERMANENT_DISABILITY`, and it must
    be null for every other `discharge_type`. A violation of either
    branch — missing on a VA application, or supplied on a non-VA
    application — is rejected with `ERR_VA_DOC_REQUIRED_OR_FORBIDDEN`."

    Design: Corner/validations/va_doc_supplied_for_non_veteran_discharge_returns_invalid
    """
    advance_clock("2026-06-01T00:00:00Z")
    borrower = create_borrower(email="va-doc-forbidden@example.com")
    res = api.create_discharge_application(
        {
            "borrower_id": borrower["id"],
            "discharge_type": "DEATH",
            "va_certification_doc_id": "VA-DOC-X",
            "filed_on": "2026-06-01",
        },
        servicer_headers,
    )
    validate_error(res, "ERR_VA_DOC_REQUIRED_OR_FORBIDDEN", expected_status=422)


# ─── Role-gated approve (corner) ────────────────────


def test_va_officer_cannot_approve_pslf_discharge(api, servicer_headers):
    """PRD §3.7: "For a `PSLF_FORGIVENESS` application, the acting role must
    be `PSLFAdjudicator`, the borrower's `PSLFTracker` must already be in
    `ELIGIBLE_FOR_FORGIVENESS`..."
    PRD §3.7: "Review proceeds in two stages. First, the adjudicator moves
    the application from `SUBMITTED` to `UNDER_REVIEW` via the
    begin-review capability; the application must be in `SUBMITTED`, and
    the acting role must match the `discharge_type` — a
    `VADischargeOfficer` may begin review only on a
    `VETERAN_TOTAL_PERMANENT_DISABILITY` application, and a
    `PSLFAdjudicator` may begin review only on a `PSLF_FORGIVENESS`
    application."

    A VADischargeOfficer trying to approve a PSLF_FORGIVENESS application
    fails the role gate.

    Design: Corner/roles/va_officer_cannot_approve_pslf_discharge
    """
    borrower, loan_latest, plan, tracker, app = setup_pslf_discharge_ready(
        adjudicator_user_id="adj-test-1",
    )
    loan_v = get_loan_version(loan_latest["id"])
    res = api.approve_discharge_application(
        app["id"],
        approve_discharge_payload({loan_latest["id"]: loan_v}),
        TEST_USERS["va_officer_headers"],
    )
    validate_error(res, "ERR_FORBIDDEN_ROLE", expected_status=403)
