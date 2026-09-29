"""Two transitions gated on the state of a capacity determination, not their own row.

Voluntary conversion and surrogate medication consent both read a *different*
entity, and the same request flips from refused to accepted purely because the
capacity determination population changed.
"""

from test_helpers import (
    ApiErrorId,
    COMPLIANCE_OFFICER_HEADERS,
    ConsentBasis,
    ConsentStatus,
    DeterminationStatus,
    HoldStatus,
    LegalStatus,
    PlacementStatus,
    SurrogateAuthorityScope,
    SurrogateRelationship,
    assert_created,
    assert_error,
    assert_ok,
    assert_page,
    conversion_payload,
    determine_capacity,
    involuntary_placed_admission,
    medication_consent_payload,
    read_admission,
    read_capacity_determination,
    read_hold,
    read_patient,
)

GUARDIAN_NAME = "Marta Vance"
SURROGATE_NAME = "Owen Sable"
SCOPED_MEDICATION = "Olanzapine"
UNSCOPED_MEDICATION = "Haloperidol"


def _placed_involuntary_admission(api, roster, ward, mrn, legal_name):
    """A certified hold, a searched admission and a bed in room 401."""
    return involuntary_placed_admission(
        api,
        roster,
        ward,
        mrn=mrn,
        legal_name=legal_name,
        age_years=34,
        gender_care_category="MALE",
        bed_id=ward.beds[0]["id"],
    )


def _incapacity_with_scope(api, roster, admission_id, scope, surrogate_name):
    """Record an incapacity finding carrying all three surrogate fields."""
    return determine_capacity(
        api,
        roster,
        admission_id,
        False,
        surrogate_name=surrogate_name,
        surrogate_relationship=SurrogateRelationship.GUARDIAN.value,
        surrogate_authority_scope=scope,
    )


class TestVoluntaryConversionNeedsCapacity:
    """The legal axis will not move while the active determination says capacity is absent."""

    def test_conversion_is_refused_while_the_active_determination_records_no_capacity(
        self, api, clock, roster, ward
    ):
        """The refusal leaves the admission, the hold and the patient's count untouched.

        PRD 3.5: "Voluntary conversion is the psychiatrist's route off the legal
        axis. It carries a `conversion_note`, requires the admission's
        `placement_status` to be `PENDING_PLACEMENT` or `PLACED`, requires the
        admission to have an `ACTIVE` capacity determination recording
        `capacity_present` as true — otherwise `ERR_CAPACITY_LACKING` — requires
        the hold to be `ACTIVE`, and requires no petition for that hold to be
        open."

        Design: Difficulty/cross_entity_state_dependency/convert_to_voluntary_requires_active_capacity_determination_true
        """
        case = _placed_involuntary_admission(
            api, roster, ward, "MRN-2367-CV", "Cormac Vane"
        )
        _incapacity_with_scope(
            api,
            roster,
            case["admission"]["id"],
            SurrogateAuthorityScope.FULL.value,
            GUARDIAN_NAME,
        )

        refusal = api.convert_admission_to_voluntary(
            roster.psychiatrist_headers, case["admission"]["id"], conversion_payload()
        )

        assert_error(refusal, ApiErrorId.CAPACITY_LACKING)
        assert (
            read_admission(api, case["admission"]["id"])["legal_status"]
            == LegalStatus.INVOLUNTARY.value
        )
        assert read_hold(api, case["hold"]["id"])["status"] == HoldStatus.ACTIVE.value
        assert read_patient(api, case["patient"]["id"])["active_hold_count"] == 1

    def test_a_second_determination_supersedes_the_first_and_drops_the_surrogate_fields(
        self, api, clock, roster, ward
    ):
        """A finding of capacity carries no surrogate at all and retires the earlier row.

        PRD 3.7: "When `capacity_present` is true all three must be absent."

        PRD 3.7: "At most one determination per admission may be `ACTIVE`, so
        creating a new one moves any prior `ACTIVE` determination for that
        admission to `SUPERSEDED`."

        Design: Difficulty/cross_entity_state_dependency/convert_to_voluntary_requires_active_capacity_determination_true
        """
        case = _placed_involuntary_admission(
            api, roster, ward, "MRN-2367-CV", "Cormac Vane"
        )
        first = _incapacity_with_scope(
            api,
            roster,
            case["admission"]["id"],
            SurrogateAuthorityScope.FULL.value,
            GUARDIAN_NAME,
        )

        second = determine_capacity(api, roster, case["admission"]["id"], True)

        assert (
            read_capacity_determination(api, first["id"])["status"]
            == DeterminationStatus.SUPERSEDED.value
        )
        assert second["status"] == DeterminationStatus.ACTIVE.value
        assert second["capacity_present"] is True
        assert second["surrogate_name"] is None
        assert second["surrogate_relationship"] is None
        assert second["surrogate_authority_scope"] is None

    def test_the_same_conversion_request_succeeds_once_capacity_is_recorded(
        self, api, clock, roster, ward
    ):
        """The hold closes as converted and the bed is kept throughout.

        PRD 3.5: "It flips `legal_status` `INVOLUNTARY → VOLUNTARY` and closes the
        hold as described in §3.3, and it never touches the placement axis."

        Design: Difficulty/cross_entity_state_dependency/convert_to_voluntary_requires_active_capacity_determination_true
        """
        case = _placed_involuntary_admission(
            api, roster, ward, "MRN-2367-CV", "Cormac Vane"
        )
        _incapacity_with_scope(
            api,
            roster,
            case["admission"]["id"],
            SurrogateAuthorityScope.FULL.value,
            GUARDIAN_NAME,
        )
        determine_capacity(api, roster, case["admission"]["id"], True)

        converted = assert_ok(
            api.convert_admission_to_voluntary(
                roster.psychiatrist_headers,
                case["admission"]["id"],
                conversion_payload(),
            )
        )

        assert converted["legal_status"] == LegalStatus.VOLUNTARY.value
        assert converted["capacity_present"] is True
        assert converted["placement_status"] == PlacementStatus.PLACED.value
        assert converted["bed_id"] == ward.beds[0]["id"]
        assert (
            read_hold(api, case["hold"]["id"])["status"]
            == HoldStatus.CONVERTED_VOLUNTARY.value
        )
        assert read_patient(api, case["patient"]["id"])["active_hold_count"] == 0


class TestSurrogateConsentNeedsScopedActiveDetermination:
    """One determination read in both directions, then retired by its successor."""

    def test_the_two_consent_bases_read_the_same_determination_in_opposite_directions(
        self, api, clock, roster, ward
    ):
        """A NONE-scope incapacity finding satisfies neither basis.

        PRD 3.7: "`PATIENT_CONSENT` requires the admission to have an `ACTIVE`
        capacity determination whose `capacity_present` is true, and fails with
        `ERR_CAPACITY_LACKING` otherwise. `SURROGATE_CONSENT` requires a
        `capacity_determination_id` naming the determination that authorizes the
        surrogate, and that determination must be `ACTIVE`, must record
        `capacity_present` as false, and must grant a `surrogate_authority_scope`
        of either `MEDICATION_ONLY` or `FULL`; a determination that is
        `SUPERSEDED`, or records capacity as present, or grants a scope of `NONE`,
        is refused with `ERR_SURROGATE_SCOPE_INSUFFICIENT`."

        Design: Difficulty/cross_entity_state_dependency/surrogate_consent_requires_active_determination_with_medication_scope
        """
        case = _placed_involuntary_admission(
            api, roster, ward, "MRN-2367-SC", "Soren Cade"
        )
        unscoped = _incapacity_with_scope(
            api,
            roster,
            case["admission"]["id"],
            SurrogateAuthorityScope.NONE.value,
            SURROGATE_NAME,
        )

        scope_refusal = api.create_medication_consent(
            roster.psychiatrist_headers,
            medication_consent_payload(
                admission_id=case["admission"]["id"],
                medication_name=SCOPED_MEDICATION,
                consent_basis=ConsentBasis.SURROGATE_CONSENT.value,
                capacity_determination_id=unscoped["id"],
            ),
        )
        assert_error(scope_refusal, ApiErrorId.SURROGATE_SCOPE_INSUFFICIENT)

        patient_basis_refusal = api.create_medication_consent(
            roster.psychiatrist_headers,
            medication_consent_payload(
                admission_id=case["admission"]["id"],
                medication_name=SCOPED_MEDICATION,
                consent_basis=ConsentBasis.PATIENT_CONSENT.value,
            ),
        )
        assert_error(patient_basis_refusal, ApiErrorId.CAPACITY_LACKING)

    def test_a_medication_scoped_determination_authorizes_a_never_expiring_consent(
        self, api, clock, roster, ward
    ):
        """The surrogate basis records the determination it relied on and no expiry.

        PRD 3.7: "The `capacity_determination_id` is supplied only for a surrogate
        basis and is null for the other two, and `emergency_justification` is
        supplied only for an emergency override and is null otherwise."

        PRD 3.7: "Consents on the other two bases carry a null `expires_at` and
        never expire."

        Design: Difficulty/cross_entity_state_dependency/surrogate_consent_requires_active_determination_with_medication_scope
        """
        case = _placed_involuntary_admission(
            api, roster, ward, "MRN-2367-SC", "Soren Cade"
        )
        _incapacity_with_scope(
            api,
            roster,
            case["admission"]["id"],
            SurrogateAuthorityScope.NONE.value,
            SURROGATE_NAME,
        )
        scoped = determine_capacity(
            api,
            roster,
            case["admission"]["id"],
            False,
            surrogate_name=SURROGATE_NAME,
            surrogate_relationship=SurrogateRelationship.ADULT_CHILD.value,
            surrogate_authority_scope=SurrogateAuthorityScope.MEDICATION_ONLY.value,
        )

        consent = assert_created(
            api.create_medication_consent(
                roster.psychiatrist_headers,
                medication_consent_payload(
                    admission_id=case["admission"]["id"],
                    medication_name=SCOPED_MEDICATION,
                    consent_basis=ConsentBasis.SURROGATE_CONSENT.value,
                    capacity_determination_id=scoped["id"],
                ),
            )
        )

        assert consent["status"] == ConsentStatus.ACTIVE.value
        assert consent["expires_at"] is None
        assert consent["capacity_determination_id"] == scoped["id"]

    def test_a_determination_that_was_valid_becomes_invalid_once_superseded(
        self, api, clock, roster, ward
    ):
        """A scoped-but-superseded determination no longer authorizes anything.

        PRD 3.7: "`SURROGATE_CONSENT` requires a `capacity_determination_id` naming
        the determination that authorizes the surrogate, and that determination
        must be `ACTIVE`, must record `capacity_present` as false, and must grant a
        `surrogate_authority_scope` of either `MEDICATION_ONLY` or `FULL`; a
        determination that is `SUPERSEDED`, or records capacity as present, or
        grants a scope of `NONE`, is refused with
        `ERR_SURROGATE_SCOPE_INSUFFICIENT`."

        Design: Difficulty/cross_entity_state_dependency/surrogate_consent_requires_active_determination_with_medication_scope
        """
        case = _placed_involuntary_admission(
            api, roster, ward, "MRN-2367-SC", "Soren Cade"
        )
        first = _incapacity_with_scope(
            api,
            roster,
            case["admission"]["id"],
            SurrogateAuthorityScope.MEDICATION_ONLY.value,
            SURROGATE_NAME,
        )
        second = _incapacity_with_scope(
            api,
            roster,
            case["admission"]["id"],
            SurrogateAuthorityScope.MEDICATION_ONLY.value,
            SURROGATE_NAME,
        )
        assert_created(
            api.create_medication_consent(
                roster.psychiatrist_headers,
                medication_consent_payload(
                    admission_id=case["admission"]["id"],
                    medication_name=SCOPED_MEDICATION,
                    consent_basis=ConsentBasis.SURROGATE_CONSENT.value,
                    capacity_determination_id=second["id"],
                ),
            )
        )

        refusal = api.create_medication_consent(
            roster.psychiatrist_headers,
            medication_consent_payload(
                admission_id=case["admission"]["id"],
                medication_name=UNSCOPED_MEDICATION,
                consent_basis=ConsentBasis.SURROGATE_CONSENT.value,
                capacity_determination_id=first["id"],
            ),
        )

        assert_error(refusal, ApiErrorId.SURROGATE_SCOPE_INSUFFICIENT)
        assert_page(
            api.list_medication_consents(
                COMPLIANCE_OFFICER_HEADERS, admission_id=case["admission"]["id"]
            ),
            1,
        )
