"""Corner queue - section entities, ControlAssessment and NestedRelationship surface."""
from test_helpers import (
    CONTROL_DOMAIN_ORDER,
    ApiErrorId,
    add_control_rows,
    add_nested,
    licensed_respondent,
    new_jurisdiction,
    new_respondent,
    open_questionnaire,
    read_respondent,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import ANALYST, OFFICER


def _de():
    return new_jurisdiction(
        jurisdiction_code="DE", name="Germany", basel_aml_index=4.0, corridor_risk_weight=1.0
    )


def test_create_control_assessment_stamps_domain_weight_and_defaults(api):
    """The domain weight is stamped from the fixed table at creation, and the analyst's
    three overlay fields plus the evidence note all start at their declared blanks.

    Design: Corner/entities/create_control_assessment_stamps_domain_weight_and_defaults
    """
    _de()
    respondent = licensed_respondent(
        "DE", legal_name="Nordbank AG", swift_bic="NORDDEFF",
        expected_monthly_volume_usd=500000.00, expected_monthly_count=100,
    )
    questionnaire = open_questionnaire(respondent["id"])

    row = validate_success(
        api.create_control_assessment(
            questionnaire["id"], {"control_domain": "GOVERNANCE", "self_rating": 4}, ANALYST
        ),
        expected_status=201,
    )

    assert row["domain_weight"] == 0.10
    assert row["assessed_rating"] is None
    assert row["gap_severity"] == "NONE"
    assert row["remediation_required"] is False
    assert row["evidence_note"] == ""
    assert row["self_rating"] == 4


def test_create_nested_relationship_questionnaire_source_starts_disclosed_depth_one(api):
    """A self-declared edge with no downstream respondent is depth 1 in DISCLOSED, whose
    state weight of 1 makes the rollup exactly 1 unit with nothing undisclosed.

    Design: Corner/entities/create_nested_relationship_questionnaire_source_starts_disclosed_depth_one
    """
    _de()
    new_jurisdiction(
        jurisdiction_code="FR", name="France", basel_aml_index=5.0, corridor_risk_weight=1.2
    )
    respondent = new_respondent(
        "DE", legal_name="Nordbank AG", swift_bic="NORDDEFF",
        expected_monthly_volume_usd=500000.00, expected_monthly_count=100,
        nested_activity_permitted=True,
    )
    rid = respondent["id"]

    row = validate_success(
        api.create_nested_relationship(
            rid,
            {"downstream_institution_name": "Petit Banque SA",
             "downstream_jurisdiction_code": "FR",
             "relationship_type": "DOWNSTREAM_CORRESPONDENT",
             "discovery_source": "QUESTIONNAIRE"},
            ANALYST,
        ),
        expected_status=201,
    )

    assert row["state"] == "DISCLOSED"
    assert row["depth"] == 1
    assert row["prohibition_reason"] is None

    parent = read_respondent(rid)
    assert parent["disclosed_nested_count"] == 1
    assert parent["undisclosed_nested_count"] == 0
    assert parent["nested_exposure_units"] == 1
    assert parent["max_nested_depth"] == 1


def test_nested_relationship_visible_from_both_ends_of_the_edge(api):
    """The edge is self-referential, so the same row is reachable by filtering on the
    upstream respondent and by filtering on the downstream respondent it points at.

    Design: Corner/entities/nested_relationship_visible_from_both_ends_of_the_edge
    """
    _de()
    upstream = new_respondent(
        "DE", legal_name="Nordbank AG", swift_bic="NORDDEFF",
        expected_monthly_volume_usd=500000.00, expected_monthly_count=100,
        nested_activity_permitted=True,
    )
    downstream = new_respondent(
        "DE", legal_name="Suedbank AG", swift_bic="SUEDDEFF",
        expected_monthly_volume_usd=200000.00, expected_monthly_count=40,
    )
    row = add_nested(
        upstream["id"], "DE", downstream_institution_name="Suedbank AG",
        downstream_respondent_bank_id=downstream["id"],
    )

    from_downstream, meta = validate_paginated(
        api.list_nested_relationships(
            ANALYST, params={"downstream_respondent_bank_id": downstream["id"]}
        )
    )
    assert meta["total_count"] == 1
    assert from_downstream[0]["id"] == row["id"]
    assert from_downstream[0]["respondent_bank_id"] == upstream["id"]

    from_upstream, upstream_meta = validate_paginated(
        api.list_nested_relationships(
            ANALYST, params={"respondent_bank_id": upstream["id"]}
        )
    )
    assert upstream_meta["total_count"] == 1
    assert from_upstream[0]["id"] == row["id"]


def test_get_nested_relationship_unknown_id_returns_not_found(api):
    """`nestedRelationshipId` maps to its own not-found error, and the read is open to
    every role including the sanctions officer.

    Design: Corner/entities/get_nested_relationship_unknown_id_returns_not_found
    """
    response = api.get_nested_relationship("12121212-3434-4545-8656-767676767676", OFFICER)
    validate_error(response, ApiErrorId.ERR_NESTED_RELATIONSHIP_NOT_FOUND)


def test_list_control_assessments_filter_by_questionnaire_returns_all_eight_domains(api):
    """This child collection declares a non-creation order: the eight rows come back in
    the fixed control-domain weight order regardless of the order they were written in.

    Design: Corner/entities/list_control_assessments_filter_by_questionnaire_returns_all_eight_domains
    """
    _de()
    respondent = licensed_respondent(
        "DE", legal_name="Nordbank AG", swift_bic="NORDDEFF",
        expected_monthly_volume_usd=500000.00, expected_monthly_count=100,
    )
    questionnaire = open_questionnaire(respondent["id"])
    add_control_rows(
        questionnaire["id"], respondent["id"], {d: 4 for d in CONTROL_DOMAIN_ORDER}
    )

    rows, meta = validate_paginated(
        api.list_control_assessments(
            ANALYST, params={"questionnaire_id": questionnaire["id"], "limit": 100}
        )
    )

    assert meta["total_count"] == 8
    assert meta["has_more"] is False
    assert [row["control_domain"] for row in rows] == list(CONTROL_DOMAIN_ORDER)
