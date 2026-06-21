"""Onboarding, KYC scoring, and application adjudication (PRD §3.1–§3.3).

Covers queue-A difficulty instances for combinatorial KYC scoring, the approve cascade,
and the state-vs-business validation precedence pair, plus queue-B corner instances for
the application state machine, KYC factors, segregation of duties, and the KYC gate.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    make_teller_headers,
    make_officer_headers,
    set_clock,
    create_apy_tier,
    create_customer,
    create_draft_application,
    create_submitted_application,
    open_account,
    reject_application,
)
from test_helpers.factories import (
    create_customer_payload,
    create_application_payload,
    reject_application_payload,
)


# ===========================================================================
# Queue A — combinatorial_formula / kyc_risk_score_multifactor_nonlinear
# ===========================================================================
def test_kyc_score_non_us_plus_sanctioned_is_ninety(api):
    """PRD §3.2: "If the customer's `country_of_residence` is anything other than
    `US`, forty points are added." and "If the customer's `tax_id_last4` is one of the
    sanctioned values — the strings `6666` or `9999` — fifty points are added."

    A non-US (GB) sanctioned (9999) applicant scores 40 + 50 = 90.

    Design: Difficulty/combinatorial_formula/kyc_risk_score_multifactor_nonlinear
    """
    set_clock("2026-01-01T00:00:00Z")
    create_apy_tier(code="CHK_STD", product_type="CHECKING")
    cust = create_customer(
        legal_name="Risky Applicant", date_of_birth="1985-06-01",
        tax_id_last4="9999", country_of_residence="GB",
    )
    app = create_draft_application(cust["id"], product_type="CHECKING",
                                   requested_apy_tier_code="CHK_STD")
    res = api.submit_application(app["id"], make_teller_headers("teller-1"))
    submitted = validate_success(res, 200)
    assert submitted["kyc_risk_score"] == 90, (
        f"non-US(+40) + sanctioned(+50) must score 90, got {submitted['kyc_risk_score']}"
    )
    assert submitted["status"] == "SUBMITTED"


def test_kyc_score_ceiling_clamps_at_100(api):
    """PRD §3.2: "The four contributions are summed, and the result is clamped to a
    ceiling of 100 — any total above 100 is recorded as 100."

    A non-US (+40) sanctioned (+50) applicant with 3 prior rejections (+30) sums to 120
    and clamps to 100.

    Design: Difficulty/combinatorial_formula/kyc_risk_score_multifactor_nonlinear
    """
    set_clock("2026-01-01T00:00:00Z")
    create_apy_tier(code="CHK_STD", product_type="CHECKING")
    cust = create_customer(
        legal_name="Max Risk", date_of_birth="1985-06-01",
        tax_id_last4="9999", country_of_residence="GB",
    )
    # Three prior REJECTED applications for the same customer (+30, capped).
    for _ in range(3):
        app = create_submitted_application(cust["id"])
        # Rejection is from a SUBMITTED app; submitter is teller-1, rejecter officer-1.
        validate_success(
            api.reject_application(
                app["id"], reject_application_payload(rejection_reason_code="DUPLICATE"),
                make_officer_headers("officer-1"),
            ),
            200,
        )
    app4 = create_draft_application(cust["id"])
    submitted = validate_success(
        api.submit_application(app4["id"], make_teller_headers("teller-1")), 200
    )
    assert submitted["kyc_risk_score"] == 100, (
        f"40+50+30=120 must clamp to 100, got {submitted['kyc_risk_score']}"
    )


# ===========================================================================
# Queue A — transitive_cascade / approve_application_cascades_account_owner
# ===========================================================================
def test_approve_cascades_account_owner_and_cip(api):
    """PRD §3.3: "A new `Account` is created in `ACTIVE` status, with `product_type`
    copied from the application, `apy_tier_code` set to the requested tier code,
    `origin_application_id` pointing back to the approving application's `id`, and
    `ledger_balance_cents` initialized to zero."
    PRD §3.3: "A first `AccountOwner` is created for that account with `ownership_role`
    of `PRIMARY`, `customer_id` taken from the application, and `is_active` true."
    PRD §3.3: "And the customer's `cip_status` is recomputed, which — because this
    approval is now the latest adjudicated application — yields `VERIFIED`."

    Design: Difficulty/transitive_cascade/approve_application_cascades_account_owner
    """
    set_clock("2026-01-01T00:00:00Z")
    create_apy_tier(code="CHK_STD", product_type="CHECKING")
    cust = create_customer(legal_name="Clean Owner", tax_id_last4="1234")
    app = create_submitted_application(cust["id"], submitted_by="teller-1")

    approved = validate_success(
        api.approve_application(app["id"], make_officer_headers("officer-1")), 200
    )
    assert approved["status"] == "APPROVED"
    new_acct_id = approved["opened_account_id"]

    account = validate_success(api.get_account(new_acct_id, make_officer_headers()), 200)
    assert account["origin_application_id"] == app["id"]
    assert account["status"] == "ACTIVE"
    assert account["ledger_balance_cents"] == 0

    owners_resp = api.list_owners(new_acct_id, make_officer_headers())
    owners = validate_success(owners_resp, 200)
    assert len(owners) == 1, f"expected exactly one owner, got {len(owners)}"
    owner = owners[0]
    assert owner["ownership_role"] == "PRIMARY"
    assert owner["customer_id"] == cust["id"]
    assert owner["is_active"] is True

    cust_after = validate_success(api.get_customer(cust["id"], make_officer_headers()), 200)
    assert cust_after["cip_status"] == "VERIFIED"


def test_approve_sets_opened_account_id_on_application(api):
    """PRD §3.3: "The application's `opened_account_id` is set to the new account's `id`."

    Design: Difficulty/transitive_cascade/approve_application_cascades_account_owner
    """
    set_clock("2026-01-01T00:00:00Z")
    create_apy_tier(code="CHK_STD", product_type="CHECKING")
    cust = create_customer(legal_name="Link Owner", tax_id_last4="1235")
    app = create_submitted_application(cust["id"], submitted_by="teller-1")
    approved = validate_success(
        api.approve_application(app["id"], make_officer_headers("officer-1")), 200
    )
    account = validate_success(
        api.get_account(approved["opened_account_id"], make_officer_headers()), 200
    )
    app_after = validate_success(api.get_application(app["id"], make_officer_headers()), 200)
    assert app_after["opened_account_id"] == account["id"]


# ===========================================================================
# Queue A — priority_pair_validation_conflict / invalid_state_beats_kyc_risk_on_approve
# ===========================================================================
def test_invalid_state_beats_kyc_risk_on_draft_approve(api):
    """PRD §2.10: "State legality is fifth: an operation invoked against a resource
    that is not in a state from which the transition is defined yields
    `ERR_INVALID_STATE` (HTTP 409)."
    PRD §3.3: "A `ComplianceOfficer` adjudicates a `SUBMITTED` application, and only a
    `SUBMITTED` one — adjudicating from any other status yields `ERR_INVALID_STATE`."

    A DRAFT (never-submitted, no kyc_risk_score) application approved: the state check
    (5th) fires before the KYC business-rule gate.

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_kyc_risk_on_approve
    """
    set_clock("2026-01-01T00:00:00Z")
    create_apy_tier(code="CHK_STD", product_type="CHECKING")
    cust = create_customer(
        legal_name="Draft Risky", date_of_birth="1985-01-01",
        tax_id_last4="9999", country_of_residence="GB",
    )
    app = create_draft_application(cust["id"])  # never submitted -> still DRAFT
    res = api.approve_application(app["id"], make_officer_headers("officer-1"))
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_invalid_state_precedes_kyc_for_high_risk_draft(api):
    """PRD §2.10: "the earliest failing check in this precedence determines the
    response, so an earlier failure is never masked by a later one."
    PRD §3.3: "adjudicating from any other status yields `ERR_INVALID_STATE`."

    Even with a would-be-90 risk profile, a DRAFT approve returns ERR_INVALID_STATE,
    not ERR_KYC_RISK_TOO_HIGH (which the DRAFT app has no computed score for).

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_kyc_risk_on_approve
    """
    set_clock("2026-01-01T00:00:00Z")
    create_apy_tier(code="CHK_STD", product_type="CHECKING")
    cust = create_customer(
        legal_name="Draft High", date_of_birth="1985-01-01",
        tax_id_last4="6666", country_of_residence="FR",
    )
    app = create_draft_application(cust["id"])
    res = api.approve_application(app["id"], make_officer_headers("officer-2"))
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


# ===========================================================================
# Queue B — calculations / kyc_prior_rejection_weight_accumulates
# ===========================================================================
def test_kyc_prior_rejection_weight_accumulates(api):
    """PRD §3.2: "the system counts how many prior applications this same `customer_id`
    already has in `REJECTED` status; that count is capped at three, and ten points are
    added for each counted rejection (so at most thirty points from this factor)."

    A US adult with 2 prior REJECTED applications scores min(2,3)*10 = 20.

    Design: Corner/calculations/kyc_prior_rejection_weight_accumulates
    """
    set_clock("2026-01-01T00:00:00Z")
    create_apy_tier(code="CHK_STD", product_type="CHECKING")
    cust = create_customer(
        legal_name="Repeat App", date_of_birth="1985-01-01",
        tax_id_last4="1818", country_of_residence="US",
    )
    for _ in range(2):
        app = create_submitted_application(cust["id"])
        validate_success(
            api.reject_application(
                app["id"], reject_application_payload(rejection_reason_code="DUPLICATE"),
                make_officer_headers("officer-1"),
            ),
            200,
        )
    app3 = create_draft_application(cust["id"])
    submitted = validate_success(
        api.submit_application(app3["id"], make_teller_headers("teller-1")), 200
    )
    assert submitted["kyc_risk_score"] == 20, (
        f"2 prior rejections must add 20, got {submitted['kyc_risk_score']}"
    )


# ===========================================================================
# Queue B — validations / segregation_of_duties_same_user_approve
# ===========================================================================
def test_segregation_of_duties_same_user_approve(api):
    """PRD §3.3: "both enforce segregation of duties first: the officer's `X-User-ID`
    must differ from the application's `submitted_by_user_id`, or the request is
    rejected with `ERR_SEGREGATION_OF_DUTIES`."

    The same opaque id (officer-9) that submitted attempts to approve.

    Design: Corner/validations/segregation_of_duties_same_user_approve
    """
    set_clock("2026-01-01T00:00:00Z")
    create_apy_tier(code="CHK_STD", product_type="CHECKING")
    cust = create_customer(legal_name="Sod Owner", tax_id_last4="3030")
    # Submitted by officer-9 acting as Teller.
    app = create_submitted_application(cust["id"], submitted_by="officer-9")
    res = api.approve_application(app["id"], make_officer_headers("officer-9"))
    validate_error(res, "ERR_SEGREGATION_OF_DUTIES", expected_status=409)


# ===========================================================================
# Queue B — validations / kyc_risk_too_high_blocks_approve
# ===========================================================================
def test_kyc_risk_too_high_blocks_approve(api):
    """PRD §3.3: "approval requires that the `kyc_risk_score` be strictly below 70 — a
    score of 70 or higher is rejected with `ERR_KYC_RISK_TOO_HIGH`".

    A SUBMITTED app scoring 90 (non-US + sanctioned) is blocked at approve.

    Design: Corner/validations/kyc_risk_too_high_blocks_approve
    """
    set_clock("2026-01-01T00:00:00Z")
    create_apy_tier(code="CHK_STD", product_type="CHECKING")
    cust = create_customer(
        legal_name="High Risk", date_of_birth="1985-01-01",
        tax_id_last4="9999", country_of_residence="GB",
    )
    app = create_submitted_application(cust["id"], submitted_by="teller-1")
    res = api.approve_application(app["id"], make_officer_headers("officer-1"))
    validate_error(res, "ERR_KYC_RISK_TOO_HIGH", expected_status=409)


# ===========================================================================
# Queue B — state_machines / double_submit_application_returns_invalid_state
# ===========================================================================
def test_double_submit_application_returns_invalid_state(api):
    """PRD §3.1: "A `Teller` submits a `DRAFT` application for adjudication, advancing
    it `DRAFT → SUBMITTED`. Submission is defined only from `DRAFT`; invoking it on any
    other status yields `ERR_INVALID_STATE`."

    Design: Corner/state_machines/double_submit_application_returns_invalid_state
    """
    create_apy_tier(code="CHK_STD", product_type="CHECKING")
    cust = create_customer(legal_name="Resub", tax_id_last4="4141")
    app = create_submitted_application(cust["id"], submitted_by="teller-1")
    res = api.submit_application(app["id"], make_teller_headers("teller-1"))
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


# ===========================================================================
# Queue B — state_machines / terminal_rejected_application_cannot_approve
# ===========================================================================
def test_terminal_rejected_application_cannot_approve(api):
    """PRD §3.3: "Both `APPROVED` and `REJECTED` are terminal; no further transition is
    defined out of either."
    PRD §3.3: "adjudicating from any other status yields `ERR_INVALID_STATE`."

    Design: Corner/state_machines/terminal_rejected_application_cannot_approve
    """
    create_apy_tier(code="CHK_STD", product_type="CHECKING")
    cust = create_customer(legal_name="Rej Owner", tax_id_last4="5151")
    rejected = reject_application(
        cust["id"], reason="DUPLICATE", submitted_by="teller-1", rejected_by="officer-1"
    )
    assert rejected["status"] == "REJECTED"
    res = api.approve_application(rejected["id"], make_officer_headers("officer-2"))
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


# ===========================================================================
# Queue B — state_machines / reject_sets_customer_cip_rejected
# ===========================================================================
def test_reject_sets_reason_and_customer_cip_rejected(api):
    """PRD §3.3: "rejection sets `rejection_reason_code` from the request body — one of
    `CIP_MISMATCH`, `SANCTIONS_HIT`, `UNDERAGE`, or `DUPLICATE` — and recomputes the
    customer's `cip_status`, which now yields `REJECTED`."

    Design: Corner/state_machines/reject_sets_customer_cip_rejected
    """
    create_apy_tier(code="CHK_STD", product_type="CHECKING")
    cust = create_customer(legal_name="CIP Rej", tax_id_last4="6161")
    app = create_submitted_application(cust["id"], submitted_by="teller-1")
    rejected = validate_success(
        api.reject_application(
            app["id"], reject_application_payload(rejection_reason_code="CIP_MISMATCH"),
            make_officer_headers("officer-1"),
        ),
        200,
    )
    assert rejected["status"] == "REJECTED"
    assert rejected["rejection_reason_code"] == "CIP_MISMATCH"
    cust_after = validate_success(api.get_customer(cust["id"], make_officer_headers()), 200)
    assert cust_after["cip_status"] == "REJECTED"


# ===========================================================================
# Queue B — entities / create_customer_returns_201_with_fields
# ===========================================================================
def test_create_customer_returns_201_with_fields(api):
    """PRD §3.1: "A freshly created customer's `cip_status` is `UNVERIFIED`".
    PRD §3.1: "The record captures the person's `legal_name`, their `date_of_birth` as
    an ISO date, and `tax_id_last4`".

    Design: Corner/entities/create_customer_returns_201_with_fields
    """
    res = api.create_customer(
        create_customer_payload(
            legal_name="New Person", date_of_birth="1991-03-03",
            tax_id_last4="2468", country_of_residence="US",
        ),
        make_teller_headers("teller-1"),
    )
    cust = validate_success(res, 201)
    assert cust["legal_name"] == "New Person"
    assert cust["cip_status"] == "UNVERIFIED"


# ===========================================================================
# Queue B — entities / customer_country_default_us_applied
# ===========================================================================
def test_customer_country_defaults_to_us(api):
    """PRD §3.1: "It also captures `country_of_residence`, an ISO 3166 alpha-2 code that
    defaults to `US` when omitted".

    Design: Corner/entities/customer_country_default_us_applied
    """
    payload = create_customer_payload(
        legal_name="Default Country", date_of_birth="1991-03-03", tax_id_last4="2468",
    )
    payload.pop("country_of_residence", None)
    cust = validate_success(api.create_customer(payload, make_teller_headers("teller-1")), 201)
    assert cust["country_of_residence"] == "US"


# ===========================================================================
# Queue B — entities / create_customer_missing_required_field_rejected
# ===========================================================================
def test_create_customer_missing_legal_name_rejected(api):
    """PRD §2.9: "A request missing a required body field, or supplying an enum value
    outside its declared domain, is rejected with `ERR_INVALID_REQUEST` (HTTP 422)."

    Design: Corner/entities/create_customer_missing_required_field_rejected
    """
    res = api.create_customer(
        {"date_of_birth": "1991-03-03", "tax_id_last4": "2468"},
        make_teller_headers("teller-1"),
    )
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=422)


# ===========================================================================
# Queue B — errors / customer_not_found_on_application_create
# ===========================================================================
def test_customer_not_found_on_application_create(api):
    """PRD §2.8: "`ERR_CUSTOMER_NOT_FOUND` when a referenced `customer_id` does not
    resolve".

    Design: Corner/errors/customer_not_found_on_application_create
    """
    create_apy_tier(code="CHK_STD", product_type="CHECKING")
    res = api.create_application(
        create_application_payload(
            "00000000-0000-0000-0000-000000000000",
            product_type="CHECKING", requested_apy_tier_code="CHK_STD",
        ),
        make_teller_headers("teller-1"),
    )
    validate_error(res, "ERR_CUSTOMER_NOT_FOUND", expected_status=404)
