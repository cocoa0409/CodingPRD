"""Registration surfaces (patients, accounts) and policy activation windows."""
from test_helpers import (
    BILLING,
    COMPLIANCE,
    COUNSELOR,
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_ledger_invariants,
    assert_patient,
    assert_patient_account,
    create_active_policy,
    create_patient,
    create_policy,
    get_policy,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_success,
)


class TestPatientRegistration:
    def test_patient_created_with_common_fields(self, api):
        """PRD §2.5: "`id` (string): a server-minted UUID with no type prefix."
        PRD §2.5: "`version` (integer): a system-managed integer that
        increments by 1 on every mutation of the resource, including mutations
        caused by cascades from other entities."

        Design: Corner/entities/patient_create_applies_common_fields_and_ignores_system_input
        """
        resp = api.create_patient(
            {
                "full_name": "New Nate",
                "date_of_birth": "1990-01-01",
                "ssn_last4": "0001",
                "mrn": "MRN-NEW-1",
            },
            COUNSELOR,
        )
        data = validate_success(resp, 201)
        assert_patient(data)
        assert is_valid_uuid(data["id"])
        assert is_iso8601_timestamp(data["created_at"])
        assert is_iso8601_timestamp(data["updated_at"])
        assert data["version"] == 1, "freshly created resource starts at version 1"
        assert data["full_name"] == "New Nate"
        assert data["mrn"] == "MRN-NEW-1"

    def test_duplicate_mrn_rejected(self, api):
        """PRD §3.2: "Patient registration, performed by a `FinancialCounselor`
        or `ComplianceOfficer`, captures `full_name`, `date_of_birth` (an ISO
        8601 `YYYY-MM-DD` date), `ssn_last4` (exactly four numeric characters),
        `mrn` (the medical record number, unique across the system with
        duplicates rejected as `ERR_DUPLICATE_MRN`, HTTP 409), and an optional
        `contact_email`."

        Design: Corner/validations/duplicate_mrn_rejected
        """
        create_patient(
            full_name="First MRN", date_of_birth="1990-01-01",
            ssn_last4="0040", mrn="MRN-DUP-M",
        )
        resp = api.create_patient(
            {
                "full_name": "Second MRN",
                "date_of_birth": "1991-01-01",
                "ssn_last4": "0041",
                "mrn": "MRN-DUP-M",
            },
            COUNSELOR,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_MRN)

    def test_get_patient_not_found(self, api):
        """PRD §2.10: "The family of not-found errors is
        `ERR_PATIENT_NOT_FOUND`, `ERR_ACCOUNT_NOT_FOUND`,
        `ERR_APPLICATION_NOT_FOUND`, `ERR_POLICY_NOT_FOUND`,
        `ERR_DETERMINATION_NOT_FOUND`, `ERR_DOCUMENT_NOT_FOUND`,
        `ERR_MEMBER_NOT_FOUND`, `ERR_ACTION_NOT_FOUND`, `ERR_REPORT_NOT_FOUND`,
        and `ERR_PAYMENT_NOT_FOUND`, each carrying HTTP 404."

        Design: Corner/entities/get_patient_not_found_returns_404
        """
        resp = api.get_patient(NON_EXISTENT_UUID, COUNSELOR)
        validate_error(resp, ApiErrorId.ERR_PATIENT_NOT_FOUND)


class TestAccountCreation:
    def test_account_computes_patient_responsibility(self, api):
        """PRD §3.2: "At creation the account fixes
        `patient_responsibility_cents` as total charges minus insurance paid;
        this figure never changes afterward and is the basis for all later
        write-off math."

        Design: Corner/entities/account_create_computes_patient_responsibility
        """
        patient = create_patient(
            full_name="Comp Carla", date_of_birth="1980-02-02",
            ssn_last4="0002", mrn="MRN-COMP-1",
        )
        resp = api.create_account(
            {
                "patient_id": patient["id"],
                "encounter_date": "2026-01-10",
                "total_charges_cents": 500000,
                "insurance_paid_cents": 125000,
            },
            BILLING,
        )
        account = validate_success(resp, 201)
        assert_patient_account(account)
        assert account["patient_responsibility_cents"] == 375000
        assert account["adjusted_balance_cents"] == 375000
        assert account["effective_payments_cents"] == 0
        assert account["collection_posture"] == "NOT_IN_COLLECTIONS"
        assert account["first_statement_at"] is None
        assert_ledger_invariants(account)

    def test_zero_responsibility_resolves_immediately(self, api):
        """PRD §3.2: "If insurance covers the entire charge,
        `amount_outstanding_cents` is zero from birth and the account enters
        `RESOLVED` immediately; otherwise it begins in `NOT_IN_COLLECTIONS`."

        Design: Corner/entities/account_zero_responsibility_resolves_immediately
        """
        patient = create_patient(
            full_name="Zero Zack", date_of_birth="1980-02-03",
            ssn_last4="0003", mrn="MRN-ZERO-1",
        )
        resp = api.create_account(
            {
                "patient_id": patient["id"],
                "encounter_date": "2026-01-10",
                "total_charges_cents": 300000,
                "insurance_paid_cents": 300000,
            },
            BILLING,
        )
        account = validate_success(resp, 201)
        assert account["patient_responsibility_cents"] == 0
        assert account["amount_outstanding_cents"] == 0
        assert account["collection_posture"] == "RESOLVED"

    def test_insurance_exceeds_charges_rejected(self, api):
        """PRD §3.2: "A `BillingAdministrator` opens a patient account for an
        encounter by providing the `patient_id`, the `encounter_date`,
        `total_charges_cents` (strictly positive integer cents), and
        `insurance_paid_cents` (integer cents that must be at least zero and
        must not exceed `total_charges_cents`; a violation is
        `ERR_INSURANCE_EXCEEDS_CHARGES`, HTTP 422)."

        Design: Corner/validations/account_create_insurance_exceeds_charges
        """
        patient = create_patient(
            full_name="Over Ins", date_of_birth="1990-01-01",
            ssn_last4="0027", mrn="MRN-OINS-1",
        )
        resp = api.create_account(
            {
                "patient_id": patient["id"],
                "encounter_date": "2026-01-10",
                "total_charges_cents": 100000,
                "insurance_paid_cents": 100001,
            },
            BILLING,
        )
        validate_error(resp, ApiErrorId.ERR_INSURANCE_EXCEEDS_CHARGES)


class TestPolicyActivationWindows:
    def _policy_pair_setup(self):
        """P1 ACTIVE [2026,2027); P2 DRAFT adjacent [2027,2028); P3 DRAFT
        overlapping P1's interior by one day."""
        p1 = create_active_policy()
        p2 = create_policy(
            policy_code="FAP-2027",
            fpl_base_cents=1600000,
            fpl_increment_cents=550000,
            effective_from="2027-01-01T00:00:00Z",
            effective_to="2028-01-01T00:00:00Z",
        )
        p3 = create_policy(
            policy_code="FAP-BAD",
            fpl_base_cents=1600000,
            fpl_increment_cents=550000,
            effective_from="2026-12-31T00:00:00Z",
            effective_to="2027-06-01T00:00:00Z",
        )
        return p1, p2, p3

    def test_overlapping_window_activation_rejected(self, api):
        """PRD §2.7: "At activation time the candidate window is also checked
        against the window of every other policy whose status is `ACTIVE` or
        `SUPERSEDED`: a conflict exists when the candidate's `effective_from`
        is strictly earlier than the existing policy's `effective_to` and the
        existing policy's `effective_from` is strictly earlier than the
        candidate's `effective_to`."

        Design: Difficulty/resource_temporal_overlap/policy_window_half_open_overlap_adjacency_allowed
        """
        p1, _p2, p3 = self._policy_pair_setup()
        resp = api.activate_policy(p3["id"], COMPLIANCE)
        validate_error(resp, ApiErrorId.ERR_POLICY_WINDOW_OVERLAP)
        incumbent = get_policy(p1["id"])
        assert incumbent["status"] == "ACTIVE", (
            "rejected activation must not disturb the incumbent ACTIVE policy"
        )

    def test_adjacent_window_activation_allowed(self, api):
        """PRD §2.7: "Two windows that merely touch — the candidate's
        `effective_from` equal to the existing window's `effective_to` — do not
        conflict. A detected conflict is rejected with
        `ERR_POLICY_WINDOW_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/policy_window_half_open_overlap_adjacency_allowed
        """
        p1, p2, _p3 = self._policy_pair_setup()
        activated = validate_success(api.activate_policy(p2["id"], COMPLIANCE))
        assert activated["status"] == "ACTIVE", (
            "window adjacent at the incumbent's exclusive end is allowed"
        )
        incumbent = get_policy(p1["id"])
        assert incumbent["status"] == "SUPERSEDED"

    def test_activation_supersedes_incumbent(self, api):
        """PRD §3.1: "On success the policy moves `DRAFT → ACTIVE`, and any
        other policy that was `ACTIVE` is transitioned to `SUPERSEDED` by the
        same operation; both the activated policy's `version` and the
        superseded policy's `version` increment by 1, and both records refresh
        `updated_at`."

        Design: Corner/state_machines/policy_activate_supersedes_incumbent
        """
        p1 = create_active_policy()
        p2 = create_policy(
            policy_code="FAP-2027",
            fpl_base_cents=1600000,
            fpl_increment_cents=550000,
            effective_from="2027-01-01T00:00:00Z",
            effective_to="2028-01-01T00:00:00Z",
        )
        activated = validate_success(api.activate_policy(p2["id"], COMPLIANCE))
        assert activated["status"] == "ACTIVE"
        old = get_policy(p1["id"])
        assert old["status"] == "SUPERSEDED", (
            "exactly one policy is ACTIVE at a time; the incumbent is superseded"
        )
