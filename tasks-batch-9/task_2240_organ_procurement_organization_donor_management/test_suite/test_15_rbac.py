"""The role gates, the two segregation-of-duties limbs and the clerk's hospital scope."""

from test_helpers import (
    AUTH_USER_2,
    COORDINATOR_USER,
    COORDINATOR_USER_2,
    ERR_FORBIDDEN_ROLE,
    ERR_HOSPITAL_SCOPE_VIOLATION,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_UNAUTHENTICATED,
    assert_error_envelope,
    assert_two_decimal_value,
    create_case,
    create_hospital,
    create_referral,
    death_referral_payload,
    finalize_authorization,
    get_success_data,
    make_authorization_specialist_headers,
    make_donor_coordinator_headers,
    make_medical_director_headers,
    open_nok_authorization,
    open_registry_authorization,
    open_screening,
    organ_payload,
    read_authorization,
    read_case,
    read_hospital,
    read_referral,
    read_screening,
    record_nok_contact,
    rule_screening,
    screening_decision_payload,
    submit_assessment,
    upload_document,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK = "2026-09-09T08:00:00Z"
TRIGGER = "2026-09-09T07:30:00Z"
UNKNOWN_REFERRAL = "00000000-0000-0000-0000-000000000001"
UNKNOWN_AUTHORIZATION = "00000000-0000-0000-0000-000000000002"
UNKNOWN_ORGAN = "00000000-0000-0000-0000-000000000003"


# ---------------------------------------------------------------------------
# The two header gates sit above every existence and shape gate
# ---------------------------------------------------------------------------
def test_other_roles_cannot_reach_an_exclusive_operation(env):
    """The role gate answers first, so unknown ids never surface their 404s.

    PRD 2.1: "Every request must carry two headers: `X-User-ID`, identifying the
    acting user, and `X-User-Role`, declaring the capacity in which they act. If
    either header is absent, or if the value of `X-User-Role` is not one of the
    nine declared role names, the request is rejected with `ERR_UNAUTHENTICATED`
    (401 Unauthorized). If the headers are well formed but the acting role is not
    among the roles authorized for the requested operation in the §4 table, the
    request is rejected with `ERR_FORBIDDEN_ROLE` (403 Forbidden)."
    PRD 2.10: "**Header presence and role validity** — `ERR_UNAUTHENTICATED`, on
    every endpoint."
    PRD 2.10: "**Role authorization for the endpoint** — `ERR_FORBIDDEN_ROLE`, on
    every endpoint."
    PRD 2.10: "**Path identifier existence, left to right** — the nine 404 codes
    of §2.5, on every path-templated endpoint."
    PRD 2.10: "**Body foreign-key existence** — the five 404 codes of §2.5, on
    `POST /opo/death-referrals`, `POST /opo/donor-cases`"
    PRD 2.5: "Uniqueness is enforced on `hospital_code`, `team_code`,
    `asset_code`, `donor_code`, and on the pair of a donor case together with an
    `organ_type`; a collision on any of these yields `ERR_DUPLICATE_KEY` (409
    Conflict)."

    Design: Corner/rbac/other_roles_cannot_reach_an_exclusive_operation
    """
    env.set_clock(CLOCK)

    wrong_role_on_body_ids = env.api.create_donor_case(
        {
            "referral_id": UNKNOWN_REFERRAL,
            "authorization_id": UNKNOWN_AUTHORIZATION,
            "donor_code": "D-BAD",
        },
        env.lab,
    )
    validate_error(wrong_role_on_body_ids, ERR_FORBIDDEN_ROLE, 403)
    assert_error_envelope(wrong_role_on_body_ids.json())

    wrong_role_on_path_id = env.api.submit_organ_evaluation(
        UNKNOWN_ORGAN,
        {"decision": "ALLOCATABLE"},
        make_donor_coordinator_headers(COORDINATOR_USER),
    )
    validate_error(wrong_role_on_path_id, ERR_FORBIDDEN_ROLE, 403)
    assert_error_envelope(wrong_role_on_path_id.json())

    no_headers_at_all = env.api.create_recovery_team(
        {"team_code": "ABD-9", "specialty": "ABDOMINAL"}, env.anonymous
    )
    validate_error(no_headers_at_all, ERR_UNAUTHENTICATED, 401)
    assert_error_envelope(no_headers_at_all.json())

    cases, case_meta = validate_paginated(env.api.list_donor_cases(env.admin))
    assert cases == []
    assert case_meta["total_count"] == 0

    organs, organ_meta = validate_paginated(env.api.list_organs(env.admin))
    assert organs == []
    assert organ_meta["total_count"] == 0

    # The refused team never persisted: its code is still free for the admin.
    team = validate_success(
        env.api.create_recovery_team(
            {"team_code": "ABD-9", "specialty": "ABDOMINAL"}, env.admin
        ),
        201,
    )
    assert team["specialty"] == "ABDOMINAL"


def test_admin_role_holds_no_clinical_override(env):
    """Neither the admin nor the coordinator inherits the other's write endpoint.

    PRD 2.1: "If the headers are well formed but the acting role is not among the
    roles authorized for the requested operation in the §4 table, the request is
    rejected with `ERR_FORBIDDEN_ROLE` (403 Forbidden)."
    PRD 2.1: "`OpoAdmin` registers hospitals, recovery teams and transport
    assets, reads the performance report, and sets the logical clock."
    PRD 2.1: "`ReferralCoordinator` takes the referral, opens the eligibility
    screening and submits the behavioral risk assessment."
    PRD 3.5: "The `DonorCoordinator` registers each recoverable organ on the case
    by naming its `organ_type`, one of `HEART`, `LUNG_LEFT`, `LUNG_RIGHT`,
    `LIVER`, `KIDNEY_LEFT`, `KIDNEY_RIGHT`, `PANCREAS` or `INTESTINE`, and a case
    may carry each type at most once."
    PRD 3.5: "starts it in status `PENDING_EVAL` with `viability_hold` false"
    PRD 4: "Read one hospital partner including its lifetime timeliness counters
    and posture"
    PRD 3.1: "a short operating `hospital_code` of between 2 and 12 characters
    that must be unique across all hospitals"

    Design: Corner/rbac/admin_role_holds_no_clinical_override
    """
    env.set_clock(CLOCK)
    hospital = create_hospital(
        env,
        name="Mercy General",
        hospital_code="MERCY",
        timely_referral_window_minutes=60,
    )
    referral = create_referral(env, hospital["id"], TRIGGER, patient_mrn="MRN-7701")
    screening = open_screening(env, referral["id"])
    submit_assessment(env, screening["id"], screening["version"], risk_factors=[])
    rule_screening(env, screening["id"], "CLEARED")
    packet = open_registry_authorization(
        env, referral["id"], registry_document_ref="REG-7701"
    )
    finalize_authorization(env, packet["id"], as_user=AUTH_USER_2)
    case = create_case(env, referral["id"], packet["id"], donor_code="D-7701")
    assert case["organ_count"] == 0

    refused_admin = env.api.create_organ(
        case["id"], organ_payload("LIVER"), env.admin
    )
    validate_error(refused_admin, ERR_FORBIDDEN_ROLE, 403)
    assert_error_envelope(refused_admin.json())
    assert read_case(env, case["id"])["organ_count"] == 0

    refused_coordinator = env.api.create_hospital_partner(
        {"name": "Second General", "hospital_code": "SECOND"}, env.coordinator
    )
    validate_error(refused_coordinator, ERR_FORBIDDEN_ROLE, 403)
    assert_error_envelope(refused_coordinator.json())

    organ = validate_success(
        env.api.create_organ(
            case["id"],
            organ_payload("LIVER"),
            make_donor_coordinator_headers(COORDINATOR_USER_2),
        ),
        201,
    )
    assert organ["status"] == "PENDING_EVAL"
    assert organ["viability_hold"] is False
    assert read_case(env, case["id"])["organ_count"] == 1

    # Reads stay shared where writes are exclusive.
    assert read_hospital(env, hospital["id"])["hospital_code"] == "MERCY"

    # The refused registration never persisted: the code is still free.
    second = validate_success(
        env.api.create_hospital_partner(
            {
                "name": "Second General",
                "hospital_code": "SECOND",
                "timely_referral_window_minutes": 60,
            },
            env.admin,
        ),
        201,
    )
    assert second["hospital_code"] == "SECOND"


# ---------------------------------------------------------------------------
# Segregation of duties, both limbs
# ---------------------------------------------------------------------------
def test_risk_assessor_cannot_also_rule_on_eligibility(env):
    """The bar falls on the stamped user id, not on the role: u-1 out, u-2 in.

    PRD 2.9: "The `MedicalDirector` who issues a screening decision must not be
    the user whose `X-User-ID` is recorded in `risk_assessed_by_user_id` on that
    screening."
    PRD 2.9: "Either violation is rejected with `ERR_SEGREGATION_OF_DUTIES` (403
    Forbidden)."
    PRD 3.2: "`BLOOD_TRANSFUSION_12MO` at 2.00 and `TATTOO_UNREGULATED_12MO` at
    1.50. That listing order is the **canonical order** in which factors are
    scored"
    PRD 3.2: "The informant's reliability supplies a multiplier: 1.00 for
    `PRIMARY_NEXT_OF_KIN`, 1.15 for `SECONDARY_CONTACT` and 1.30 for
    `MEDICAL_RECORD_ONLY`."
    PRD 3.2: "Submitting the assessment also records the submitting operator in
    `risk_assessed_by_user_id`"
    PRD 3.2: "Finally `risk_tier` becomes `INCREASED_RISK` when `risk_score` is
    at least 12.00 and `STANDARD` otherwise."
    PRD 3.2: "On success the ruling operator is recorded in `decided_by_user_id`.
    A clearance moves the screening `PENDING → CLEARED` and propagates the
    referral `SCREENING → SCREEN_CLEARED`"

    Design: Corner/rbac/risk_assessor_cannot_also_rule_on_eligibility
    """
    env.set_clock(CLOCK)
    hospital = create_hospital(
        env,
        name="Mercy General",
        hospital_code="MERCY",
        timely_referral_window_minutes=60,
    )
    referral = create_referral(env, hospital["id"], TRIGGER, patient_mrn="MRN-7801")
    screening = open_screening(env, referral["id"])

    assessed = submit_assessment(
        env,
        screening["id"],
        screening["version"],
        risk_factors=["TATTOO_UNREGULATED_12MO"],
        as_user="u-1",
    )
    assert assessed["risk_assessed_by_user_id"] == "u-1"
    assert_two_decimal_value(assessed["risk_score"], 1.50)
    assert assessed["risk_tier"] == "STANDARD"
    assert assessed["status"] == "PENDING"

    refused = env.api.submit_screening_decision(
        screening["id"],
        screening_decision_payload("CLEARED"),
        make_medical_director_headers("u-1"),
    )
    validate_error(refused, ERR_SEGREGATION_OF_DUTIES, 403)
    assert_error_envelope(refused.json())

    untouched = read_screening(env, screening["id"])
    assert untouched["status"] == "PENDING"
    assert untouched["decided_by_user_id"] is None

    ruled = rule_screening(env, screening["id"], "CLEARED", as_user="u-2")
    assert ruled["status"] == "CLEARED"
    assert ruled["decided_by_user_id"] == "u-2"
    assert read_referral(env, referral["id"])["status"] == "SCREEN_CLEARED"


def test_consent_recorder_cannot_also_finalize_the_packet(env):
    """A complete packet still refuses the consent-taker's own finalization.

    PRD 2.9: "The `AuthorizationSpecialist` who finalizes an authorization packet
    must not be the user whose `X-User-ID` is recorded in
    `consent_recorded_by_user_id` on that packet. Either violation is rejected
    with `ERR_SEGREGATION_OF_DUTIES` (403 Forbidden)."
    PRD 3.3: "its `required_document_types` becomes the two-member list
    containing `SIGNED_CONSENT_FORM` and `WITNESS_ATTESTATION`, and
    `documentation_complete` becomes false"
    PRD 3.3: "A `CONSENT` moves the packet `NOK_REQUIRED → NOK_CONSENTED`, sets
    `consenting_rank` to the consenting relative's rank, and records the acting
    specialist in `consent_recorded_by_user_id`."
    PRD 3.3: "on the `LEGAL_NEXT_OF_KIN` basis, it is true exactly when both
    `SIGNED_CONSENT_FORM` and `WITNESS_ATTESTATION` appear in
    `document_types_present` **and** `witness_name` is non-null"
    PRD 3.3: "an upload onto a packet already in `NOK_CONSENTED` leaves the
    status unchanged"

    Design: Corner/rbac/consent_recorder_cannot_also_finalize_the_packet
    """
    env.set_clock(CLOCK)
    hospital = create_hospital(
        env,
        name="Mercy General",
        hospital_code="MERCY",
        timely_referral_window_minutes=60,
    )
    referral = create_referral(env, hospital["id"], TRIGGER, patient_mrn="MRN-7901")
    screening = open_screening(env, referral["id"])
    submit_assessment(env, screening["id"], screening["version"], risk_factors=[])
    rule_screening(env, screening["id"], "CLEARED")

    packet = open_nok_authorization(env, referral["id"], as_user="a-1")
    assert packet["status"] == "NOK_REQUIRED"
    assert packet["required_document_types"] == [
        "SIGNED_CONSENT_FORM",
        "WITNESS_ATTESTATION",
    ]

    record_nok_contact(
        env,
        packet["id"],
        "SPOUSE",
        "CONSENT",
        as_user="a-1",
        contact_note="Consent by phone",
    )
    upload_document(env, packet["id"], "SIGNED_CONSENT_FORM", as_user="a-1")
    filed = upload_document(
        env,
        packet["id"],
        "WITNESS_ATTESTATION",
        as_user="a-1",
        witness_name="Jane Roe",
    )
    assert filed["consent_recorded_by_user_id"] == "a-1"
    assert filed["documentation_complete"] is True
    assert filed["status"] == "NOK_CONSENTED"

    refused = env.api.finalize_authorization(
        packet["id"], make_authorization_specialist_headers("a-1")
    )
    validate_error(refused, ERR_SEGREGATION_OF_DUTIES, 403)
    assert_error_envelope(refused.json())

    untouched = read_authorization(env, packet["id"])
    assert untouched["status"] == "NOK_CONSENTED"
    assert untouched["finalized_by_user_id"] is None

    finalized = finalize_authorization(env, packet["id"], as_user="a-2")
    assert finalized["status"] == "AUTHORIZED"
    assert finalized["finalized_by_user_id"] == "a-2"
    assert finalized["consenting_rank"] == 1


# ---------------------------------------------------------------------------
# The clerk's identity is its hospital
# ---------------------------------------------------------------------------
def test_hospital_clerk_is_scoped_to_its_own_hospital(env):
    """One declared role, admitted or refused purely on the hospital it names.

    PRD 2.1: "When `X-User-Role` is `HospitalReferralClerk`, `X-User-ID` is the
    `id` of the acting `HospitalPartner`; ownership checks on any resource that
    references a `HospitalPartner` compare the resource's hospital foreign-key
    field to `X-User-ID`. Concretely, a clerk creating a death referral must
    supply a `hospital_partner_id` equal to its own `X-User-ID`, and a clerk
    reading a hospital partner may read only the hospital whose `id` equals its
    own `X-User-ID`; either violation is rejected with
    `ERR_HOSPITAL_SCOPE_VIOLATION` (403 Forbidden)."
    PRD 2.10: "**Hospital scoping for a clerk** — `ERR_HOSPITAL_SCOPE_VIOLATION`,
    on `POST /opo/death-referrals` and `GET /opo/hospital-partners/{id}`."
    PRD 3.1: "Either a `HospitalReferralClerk` acting for its own hospital or an
    OPO-side `ReferralCoordinator` submits the `hospital_partner_id`"
    PRD 3.1: "it is `TIMELY` when `referral_lag_minutes` is less than or equal to
    the hospital's `timely_referral_window_minutes`, with equality counting as
    timely, and `UNTIMELY` otherwise."
    PRD 3.1: "**The hospital's lifetime standing is then updated in place.** Its
    `referral_count` increases by one."
    PRD 3.1: "A freshly registered hospital starts with `referral_count`,
    `timely_referral_count`, `untimely_referral_count` and
    `converted_donor_count` all at zero"

    Design: Corner/rbac/hospital_clerk_is_scoped_to_its_own_hospital
    """
    env.set_clock(CLOCK)
    hospital_a = create_hospital(
        env,
        name="Mercy General",
        hospital_code="MERCY",
        timely_referral_window_minutes=60,
    )
    hospital_b = create_hospital(
        env,
        name="Second General",
        hospital_code="SECOND",
        timely_referral_window_minutes=60,
    )
    clerk = env.clerk_for(hospital_a["id"])

    refused_write = env.api.create_death_referral(
        death_referral_payload(hospital_b["id"], TRIGGER, patient_mrn="MRN-8001"),
        clerk,
    )
    validate_error(refused_write, ERR_HOSPITAL_SCOPE_VIOLATION, 403)
    assert_error_envelope(refused_write.json())
    assert read_hospital(env, hospital_b["id"])["referral_count"] == 0

    refused_read = env.api.get_hospital_partner(hospital_b["id"], clerk)
    validate_error(refused_read, ERR_HOSPITAL_SCOPE_VIOLATION, 403)
    assert_error_envelope(refused_read.json())

    placed = validate_success(
        env.api.create_death_referral(
            death_referral_payload(
                hospital_a["id"], TRIGGER, patient_mrn="MRN-8002"
            ),
            clerk,
        ),
        201,
    )
    assert placed["hospital_partner_id"] == hospital_a["id"]
    assert placed["referral_lag_minutes"] == 30
    assert placed["timeliness_flag"] == "TIMELY"

    own = get_success_data(env.api.get_hospital_partner(hospital_a["id"], clerk))
    assert own["hospital_code"] == "MERCY"
    assert own["referral_count"] == 1
