"""Prerequisite-gate and validation-precedence tests: cross-entity state dependencies,
priority-pair conflicts, and corner validation/error claims.

Difficulty queue (A): cross_entity_state_dependency, priority_pair_validation_conflict.
Corner queue (B): validations + errors instances.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, validate_error_is_one_of,
    create_agency, set_clock, create_case, create_family, create_birth_parent,
    create_under_review_home_study, create_approved_home_study, current_case_version,
    create_irrevocable_consent, create_signed_consent, create_logged_expense,
    setup_case_with_accepted_match,
    create_match_payload, create_consent_payload, create_icpc_payload,
    create_placement_payload, create_expense_payload,
    TEST_USERS, make_caseworker_headers, make_finance_officer_headers,
    make_supervisor_headers,
)

CW = TEST_USERS["caseworker_headers"]
SUP = TEST_USERS["supervisor_headers"]
FO = TEST_USERS["finance_officer_headers"]
CA = TEST_USERS["compact_admin_headers"]
ADMIN = TEST_USERS["agency_admin_headers"]


# ─── cross_entity_state_dependency / match_accept_requires_approved_home_study ──
class TestMatchAcceptRequiresApprovedHomeStudy:
    def _under_review_with_proposed_match(self):
        agency = create_agency()
        case = create_case(agency["id"], child_state="CA", family_state="CA")
        family = create_family(case["id"], annual_income_cents=8_000_000)
        create_under_review_home_study(case["id"], family["id"])  # UNDER_REVIEW, not APPROVED
        bp = create_birth_parent(agency["id"], birth_state="CA")
        match = validate_success(api_client.create_match(
            create_match_payload(case["id"], family["id"], bp["id"]), CW), 201)
        return match["id"]

    def test_accept_rejected_when_home_study_not_approved(self):
        """PRD §3.3: "If the case's home study is not in the APPROVED state, acceptance is
        rejected with ERR_PREREQUISITE_NOT_MET".

        Design: Difficulty/cross_entity_state_dependency/match_accept_requires_approved_home_study
        """
        match_id = self._under_review_with_proposed_match()
        res = api_client.accept_match(match_id, SUP)
        validate_error(res, "ERR_PREREQUISITE_NOT_MET")

    def test_accept_succeeds_when_home_study_approved(self):
        """PRD §3.3: "Acceptance requires the match to be PROPOSED, requires the case's
        home study to be APPROVED, and requires that home study to be non-expired ... on
        success the match moves to ACCEPTED".

        Design: Difficulty/cross_entity_state_dependency/match_accept_requires_approved_home_study
        """
        agency = create_agency()
        set_clock(agency["id"], "2026-06-04T08:00:00.000Z")
        case = create_case(agency["id"], child_state="CA", family_state="CA")
        family = create_family(case["id"], annual_income_cents=8_000_000)
        create_approved_home_study(case["id"], family["id"])
        bp = create_birth_parent(agency["id"], birth_state="CA")
        match = validate_success(api_client.create_match(
            create_match_payload(case["id"], family["id"], bp["id"]), CW), 201)
        accepted = validate_success(api_client.accept_match(match["id"], SUP), 200)
        assert accepted["status"] == "ACCEPTED"


# ─── cross_entity_state_dependency / placement_activate_requires_icpc_receiving_approved ──
class TestPlacementActivateRequiresIcpcReceivingApproved:
    def _interstate_pending_placement_icpc_sending_only(self):
        base = setup_case_with_accepted_match(child_state="NV", family_state="CA",
                                              to_iso8601="2026-06-04T08:00:00.000Z",
                                              birth_state="NV")
        cv = current_case_version(base["case_id"])
        create_irrevocable_consent(base["agency_id"], base["case_id"], base["bp_id"], cv,
                                   revocation_basis="BUSINESS_DAYS",
                                   child_dob="2026-06-01T08:00:00.000Z")
        icpc = validate_success(api_client.create_icpc_clearance(
            create_icpc_payload(base["case_id"]), CW), 201)
        api_client.submit_icpc(icpc["id"], CW)
        api_client.approve_sending_icpc(icpc["id"], CA)  # SENDING_APPROVED only
        placement = validate_success(api_client.create_placement(
            create_placement_payload(base["case_id"], base["family_id"]), SUP), 201)
        return placement["id"]

    def test_activate_rejected_when_icpc_only_sending_approved(self):
        """PRD §3.6: "if the case is interstate, its ICPC clearance must be
        RECEIVING_APPROVED ... A missing or wrong-state prerequisite — consent not
        IRREVOCABLE, ICPC not RECEIVING_APPROVED on an interstate case, or home study not
        APPROVED — is rejected with ERR_PREREQUISITE_NOT_MET".

        Design: Difficulty/cross_entity_state_dependency/placement_activate_requires_icpc_receiving_approved
        """
        placement_id = self._interstate_pending_placement_icpc_sending_only()
        res = api_client.activate_placement(placement_id, SUP)
        validate_error(res, "ERR_PREREQUISITE_NOT_MET")

    def test_activate_succeeds_when_icpc_receiving_approved(self):
        """PRD §3.6: "Activation requires the placement to be PENDING and imposes three
        cross-entity gates: the case must have a consent record in IRREVOCABLE status for
        the birth parent; if the case is interstate, its ICPC clearance must be
        RECEIVING_APPROVED; and the case's home study must be APPROVED with the agency
        clock strictly before its expires_at."

        Design: Difficulty/cross_entity_state_dependency/placement_activate_requires_icpc_receiving_approved
        """
        base = setup_case_with_accepted_match(child_state="NV", family_state="CA",
                                              to_iso8601="2026-06-04T08:00:00.000Z",
                                              birth_state="NV")
        cv = current_case_version(base["case_id"])
        create_irrevocable_consent(base["agency_id"], base["case_id"], base["bp_id"], cv,
                                   revocation_basis="BUSINESS_DAYS",
                                   child_dob="2026-06-01T08:00:00.000Z")
        from test_helpers import create_icpc_receiving_approved
        create_icpc_receiving_approved(base["case_id"])
        placement = validate_success(api_client.create_placement(
            create_placement_payload(base["case_id"], base["family_id"]), SUP), 201)
        activated = validate_success(api_client.activate_placement(placement["id"], SUP), 200)
        assert activated["status"] == "ACTIVE"


# ─── priority_pair_validation_conflict / prerequisite_beats_temporal_on_consent_sign ──
def test_prerequisite_beats_temporal_on_consent_sign():
    """PRD §3.9: "then cross-entity sibling-state prerequisites (ERR_PREREQUISITE_NOT_MET),
    then the home-study expiry check ..., then consent-timing (ERR_CONSENT_TOO_EARLY)".
    PRD §3.4: "a signing attempt when the case lacks an ACCEPTED match is rejected with
    ERR_PREREQUISITE_NOT_MET."

    Design: Difficulty/priority_pair_validation_conflict/prerequisite_beats_temporal_on_consent_sign
    """
    agency = create_agency()
    set_clock(agency["id"], "2026-06-01T08:00:00.000Z")
    case = create_case(agency["id"], child_state="CA", family_state="CA")
    family = create_family(case["id"], annual_income_cents=8_000_000)
    bp = create_birth_parent(agency["id"], birth_state="CA")
    # Match left PROPOSED (no ACCEPTED match) -> prerequisite fails.
    validate_success(api_client.create_match(
        create_match_payload(case["id"], family["id"], bp["id"]), CW), 201)
    cv = current_case_version(case["id"])
    consent = validate_success(api_client.create_consent_record(
        create_consent_payload(case["id"], bp["id"], cv, revocation_basis="CALENDAR_DAYS",
                               child_dob="2026-06-01T08:00:00.000Z"), CW), 201)
    # Clock before dob+72h -> consent-timing also fails; higher-priority prereq wins.
    set_clock(agency["id"], "2026-06-02T00:00:00.000Z")
    res = api_client.sign_consent(consent["id"], CW)
    validate_error(res, "ERR_PREREQUISITE_NOT_MET")


def test_consent_timing_fires_when_only_temporal_violated():
    """PRD §3.4: "A signing attempt before that instant is rejected with
    ERR_CONSENT_TOO_EARLY". With the ACCEPTED-match prerequisite satisfied (only the
    consent-timing rule violated), the lower-priority temporal error is the one observed,
    confirming the pinned precedence in the conflict scenario.

    Design: Difficulty/priority_pair_validation_conflict/prerequisite_beats_temporal_on_consent_sign
    """
    base = setup_case_with_accepted_match(child_state="CA", family_state="CA",
                                          to_iso8601="2026-06-04T08:00:00.000Z",
                                          birth_state="CA")
    cv = current_case_version(base["case_id"])
    consent = validate_success(api_client.create_consent_record(
        create_consent_payload(base["case_id"], base["bp_id"], cv,
                               revocation_basis="CALENDAR_DAYS",
                               child_dob="2026-06-01T08:00:00.000Z"), CW), 201)
    set_clock(base["agency_id"], "2026-06-04T07:59:59.999Z")  # before dob+72h
    res = api_client.sign_consent(consent["id"], CW)
    validate_error(res, "ERR_CONSENT_TOO_EARLY")


# ─── priority_pair_validation_conflict / state_beats_fiscal_on_disburse ───
def test_state_beats_fiscal_on_disburse():
    """PRD §3.9: "then whether the target resource is in a state from which the requested
    transition is defined (ERR_INVALID_STATE). Only after those structural checks pass
    does the system evaluate business rules ... then the fiscal escrow-sufficiency check
    (ERR_INSUFFICIENT_ESCROW)".
    PRD §3.7: "disbursement requires the expense to be APPROVED".

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_disburse
    """
    agency = create_agency()
    case = create_case(agency["id"], child_state="CA", family_state="CA")  # escrow 0
    exp = create_logged_expense(case["id"], amount_cents=500_000, category="MEDICAL")  # LOGGED
    res = api_client.disburse_expense(exp["id"], FO)
    validate_error(res, "ERR_INVALID_STATE")


def test_fiscal_fires_when_only_escrow_insufficient():
    """PRD §3.7: "disbursement requires the expense to be APPROVED and requires the case's
    escrow_balance_cents to be at least the expense's amount_cents. If the balance is
    short, the disbursement is rejected with ERR_INSUFFICIENT_ESCROW." With the state
    precondition satisfied (expense APPROVED) and only the fiscal rule violated, the
    lower-priority fiscal error is observed.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_disburse
    """
    from test_helpers import create_approved_expense
    agency = create_agency()
    case = create_case(agency["id"], child_state="CA", family_state="CA")  # escrow 0
    exp = create_approved_expense(case["id"], amount_cents=500_000, category="MEDICAL")
    res = api_client.disburse_expense(exp["id"], FO)
    validate_error(res, "ERR_INSUFFICIENT_ESCROW")


# ─── Corner (B): validations / sod_expense_approver_same_as_logger ────────
def test_sod_expense_approver_same_as_logger():
    """PRD §2.5: "an expense's approving FinanceOfficer must not be the same operator who
    logged it: when a FinanceOfficer approves an expense, the acting X-User-ID is compared
    to the expense's logged_by_caseworker_id, and equality is again rejected with
    ERR_SEGREGATION_OF_DUTIES."

    Design: Corner/validations/sod_expense_approver_same_as_logger
    """
    agency = create_agency()
    case = create_case(agency["id"], child_state="CA", family_state="CA")
    cw = make_caseworker_headers("uid-9")
    exp = validate_success(api_client.create_expense(
        create_expense_payload(case["id"], amount_cents=100_000, category="MEDICAL"), cw), 201)
    fo_same = make_finance_officer_headers("uid-9")  # same operator id as logger
    res = api_client.approve_expense(exp["id"], fo_same)
    validate_error(res, "ERR_SEGREGATION_OF_DUTIES")


# ─── Corner (B): validations / consent_sign_too_early_temporal ────────────
def test_consent_sign_too_early_temporal():
    """PRD §3.4: "the earliest permissible signing instant is the child's child_dob
    advanced by seventy-two hours, and signing is permitted only when the agency clock is
    at or after that instant ... A signing attempt before that instant is rejected with
    ERR_CONSENT_TOO_EARLY".

    Design: Corner/validations/consent_sign_too_early_temporal
    """
    base = setup_case_with_accepted_match(child_state="CA", family_state="CA",
                                          to_iso8601="2026-06-04T08:00:00.000Z",
                                          birth_state="CA")
    cv = current_case_version(base["case_id"])
    consent = validate_success(api_client.create_consent_record(
        create_consent_payload(base["case_id"], base["bp_id"], cv,
                               revocation_basis="CALENDAR_DAYS",
                               child_dob="2026-06-01T08:00:00.000Z"), CW), 201)
    # One millisecond before dob+72h (2026-06-04T08:00:00Z).
    set_clock(base["agency_id"], "2026-06-04T07:59:59.999Z")
    res = api_client.sign_consent(consent["id"], CW)
    validate_error(res, "ERR_CONSENT_TOO_EARLY")


# ─── Corner (B): validations / icpc_submit_in_state_not_applicable ────────
def test_icpc_submit_in_state_not_applicable():
    """PRD §3.5: "Submitting on an in-state case (where the interstate flag is false) is
    rejected with ERR_ICPC_NOT_APPLICABLE". Per §3.5 the clearance for an in-state case
    opens in NOT_REQUIRED (not DRAFT), and §3.9 evaluates the state-transition check
    (ERR_INVALID_STATE) before the ICPC-applicability check (ERR_ICPC_NOT_APPLICABLE).
    Both readings are PRD-faithful for an in-state submit, so either error is accepted.

    Design: Corner/validations/icpc_submit_in_state_not_applicable
    """
    base = setup_case_with_accepted_match(child_state="CA", family_state="CA",
                                          to_iso8601="2026-06-04T08:00:00.000Z",
                                          birth_state="CA")
    icpc = validate_success(api_client.create_icpc_clearance(
        create_icpc_payload(base["case_id"]), CW), 201)
    assert icpc["status"] == "NOT_REQUIRED"
    res = api_client.submit_icpc(icpc["id"], CW)
    validate_error_is_one_of(res, ["ERR_ICPC_NOT_APPLICABLE", "ERR_INVALID_STATE"])


# ─── Corner (B): errors / home_study_expired_blocks_match_accept ──────────
def test_home_study_expired_blocks_match_accept():
    """PRD §3.3: "if it is APPROVED but the agency clock has reached or passed its
    expires_at, acceptance is rejected with ERR_HOME_STUDY_EXPIRED."

    Design: Corner/errors/home_study_expired_blocks_match_accept
    """
    agency = create_agency()
    set_clock(agency["id"], "2026-06-04T08:00:00.000Z")
    case = create_case(agency["id"], child_state="CA", family_state="CA")
    family = create_family(case["id"], annual_income_cents=8_000_000)
    hs = create_approved_home_study(case["id"], family["id"])  # expires 2027-06-04
    bp = create_birth_parent(agency["id"], birth_state="CA")
    match = validate_success(api_client.create_match(
        create_match_payload(case["id"], family["id"], bp["id"]), CW), 201)
    # Advance the clock past the study's expires_at but leave the study in APPROVED.
    # Per PRD §3.3 the ERR_HOME_STUDY_EXPIRED path fires only when the study is still
    # APPROVED yet the clock has reached/passed expires_at; transitioning it to EXPIRED
    # (via check-expiry) would instead yield ERR_PREREQUISITE_NOT_MET (not APPROVED).
    set_clock(agency["id"], "2027-06-05T00:00:00.000Z")  # past expiry
    res = api_client.accept_match(match["id"], SUP)
    validate_error(res, "ERR_HOME_STUDY_EXPIRED")
