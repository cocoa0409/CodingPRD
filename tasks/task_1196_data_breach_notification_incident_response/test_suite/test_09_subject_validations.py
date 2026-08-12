"""Affected-subject validations — duplicate refs, scope subset, priority
(difficulty rule priority_pair_validation_conflict; corner errors section)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_affected_subject_payload,
    create_forensic_scope_payload,
    create_incident,
    create_incident_confirmed,
    create_issued_offer,
    get_success_data,
    validate_error,
    validate_success,
)

IC = TEST_USERS["incident_commander_headers"]
FL = TEST_USERS["forensic_lead_headers"]
PC = TEST_USERS["privacy_counsel_headers"]
DA = TEST_USERS["data_analyst_headers"]


class TestDataElementOutOfScopeVsDuplicate:
    def test_out_of_scope_fires_before_duplicate_subject(self, api):
        """PRD §2.7 lists the checks in priority order: step 10
        "Data-element scope consistency" then step 13 "Subject uniqueness",
        and "A request that fails more than one of these checks receives the
        error from the earliest check in the order above."

        Design: Difficulty/priority_pair_validation_conflict/create_subject_business_referential_vs_business_constraint
        """
        # Build incident with BASELINED scope limited to SSN, and one
        # existing subject S1 (created BEFORE baseline so the existing row is
        # admissible).
        inc = create_incident()
        # First subject while scope is DRAFT (no subset check on DRAFT).
        s1_resp = api.create_affected_subject(
            inc["id"],
            create_affected_subject_payload(
                external_subject_ref="S1",
                data_elements_exposed=["SSN"],
            ),
            DA,
        )
        validate_success(s1_resp, expected_status=201)

        # Create + baseline a scope limited to SSN so the subset check engages.
        scope = validate_success(
            api.create_forensic_scope(
                inc["id"],
                create_forensic_scope_payload(data_elements_at_risk=["SSN"]),
                FL,
            ),
            expected_status=201,
        )
        api.baseline_forensic_scope(inc["id"], scope["id"], FL)

        # Second create: duplicate external_subject_ref AND a data element
        # (BIOMETRIC) outside the baselined scope. Priority 10 fires first.
        resp = api.create_affected_subject(
            inc["id"],
            create_affected_subject_payload(
                external_subject_ref="S1",
                full_name="Duplicate",
                data_elements_exposed=["SSN", "BIOMETRIC"],
            ),
            DA,
        )
        validate_error(
            resp,
            ApiErrorId.ERR_DATA_ELEMENT_OUT_OF_SCOPE.value,
            expected_status=422,
        )


class TestDuplicateSubject:
    def test_duplicate_subject_returns_error(self, api):
        """PRD §3.4: "The `external_subject_ref` must be unique per incident
        among non-`EXCLUDED` rows; a duplicate is rejected with
        `ERR_DUPLICATE_SUBJECT` (409)."

        Design: Corner/errors/duplicate_subject_returns_error
        """
        inc = create_incident()
        api.create_affected_subject(
            inc["id"],
            create_affected_subject_payload(external_subject_ref="S1"),
            DA,
        )
        resp = api.create_affected_subject(
            inc["id"],
            create_affected_subject_payload(
                external_subject_ref="S1", full_name="Duplicate"
            ),
            DA,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_SUBJECT.value, expected_status=409)


class TestOfferAlreadyActive:
    def test_second_issued_offer_for_same_subject_rejected(self, api):
        """PRD §3.9: "At most one `ISSUED` offer may exist per
        `affected_subject_id` at any time; a second issuance against a
        subject with an already-`ISSUED` offer is rejected with
        `ERR_OFFER_ALREADY_ACTIVE` (409)."

        Design: Corner/errors/offer_already_active_returns_error
        """
        ctx = create_incident_confirmed(subject_count=1)
        inc = ctx["incident"]
        subj = ctx["subjects"][0]
        create_issued_offer(inc, subj)
        resp = api.create_credit_monitoring_offer(
            inc["id"],
            {
                "affected_subject_id": subj["id"],
                "vendor_code": "CMX",
                "term_months": 12,
                "unit_cost_cents": 999,
            },
            PC,
        )
        validate_error(
            resp, ApiErrorId.ERR_OFFER_ALREADY_ACTIVE.value, expected_status=409
        )
