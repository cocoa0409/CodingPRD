"""Subject registration and referral intake/triage."""
from test_helpers import (
    validate_success,
    create_subject_payload,
    create_referral_payload,
    TEST_USERS,
    assert_subject,
    assert_referral,
)

INTAKE = TEST_USERS["intake_headers"]


def test_subject_creation_defaults(api):
    """PRD 3.1: "At creation the subject's `prior_ipv_count` is 0 and its
    `disqualification_status` is `NONE`."

    Design: Corner/entities/subject_creation_defaults
    """
    resp = api.create_subject(
        create_subject_payload(name="Fresh Subj", ssn_last4="3838", primary_program="MEDICAID"),
        INTAKE,
    )
    data = validate_success(resp, expected_status=201)
    assert_subject(data)
    assert data["prior_ipv_count"] == 0, f"expected prior_ipv_count 0, got {data['prior_ipv_count']}"
    assert data["disqualification_status"] == "NONE", (
        f"expected disqualification_status NONE, got {data['disqualification_status']}"
    )


def test_referral_priority_score_medicaid_data_match(api):
    """PRD 3.1: "the program contributes 30 for `SNAP`, 20 for `TANF`, and 40 for
    `MEDICAID`; the source contributes 10 for `HOTLINE`, 25 for `DATA_MATCH`, 15 for
    `CASEWORKER`, and 5 for `PUBLIC`. The `priority_score` is the plain integer sum of
    those two weights — for example, a `MEDICAID` referral from a `DATA_MATCH` scores 65."

    Design: Corner/entities/referral_priority_score_computed
    """
    subj = validate_success(
        api.create_subject(create_subject_payload(primary_program="MEDICAID"), INTAKE),
        expected_status=201,
    )
    resp = api.create_referral(
        create_referral_payload(subj["id"], program="MEDICAID", source="DATA_MATCH",
                                allegation_summary="Score case"),
        INTAKE,
    )
    data = validate_success(resp, expected_status=201)
    assert_referral(data)
    assert data["priority_score"] == 65, f"expected 65, got {data['priority_score']}"


def test_referral_priority_score_snap_public(api):
    """PRD 3.1: "the program contributes 30 for `SNAP`, 20 for `TANF`, and 40 for
    `MEDICAID`; the source contributes 10 for `HOTLINE`, 25 for `DATA_MATCH`, 15 for
    `CASEWORKER`, and 5 for `PUBLIC`. The `priority_score` is the plain integer sum of
    those two weights — for example, a `MEDICAID` referral from a `DATA_MATCH` scores 65."

    Design: Corner/entities/referral_priority_score_computed
    """
    subj = validate_success(
        api.create_subject(create_subject_payload(primary_program="SNAP"), INTAKE),
        expected_status=201,
    )
    resp = api.create_referral(
        create_referral_payload(subj["id"], program="SNAP", source="PUBLIC",
                                allegation_summary="Tip"),
        INTAKE,
    )
    data = validate_success(resp, expected_status=201)
    # SNAP(30) + PUBLIC(5) = 35
    assert data["priority_score"] == 35, f"expected 35, got {data['priority_score']}"
