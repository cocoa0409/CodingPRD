"""Validation coverage: thresholds that just fail, just pass, and aggregate.

The evidence bar is probed one citation below and exactly on its two-part
threshold; the reviewer capacity bar is breached by a sum rather than by either
addend; and the override-capture bar is shown to depend on a flag the designer
does not fully control.
"""

from test_helpers import (
    ApiErrorId,
    api_client,
    assertions,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)


# ---------------------------------------------------------------------------
# The two-part evidence bar at triage
# ---------------------------------------------------------------------------


CARDIOLOGY_REQUEST = {
    "request_type": "ORDER_SET",
    "clinical_domain": "CARDIOLOGY",
    "urgency": "ROUTINE",
    "evidence_grade": "B",
    "patient_safety_flag": False,
}


def test_a_lone_peer_reviewed_citation_falls_short_of_the_acceptance_bar(committee):
    """One citation fails the count test even though it is peer reviewed.

    "A request must carry at least two citations, of which at least one is peer
    reviewed; and a request whose `patient_safety_flag` is true or whose `urgency`
    is `SAFETY_URGENT` must carry at least two peer-reviewed citations. Evidence
    that falls short of any applicable threshold is rejected with
    `ERR_EVIDENCE_INSUFFICIENT`." "it awards 40 points for evidence grade `A`, 30
    for `B` ... `priority_score_basis` is set to `INTAKE_PROVISIONAL`".

    Design: Corner/validations/validation_triage_accept_with_one_citation_returns_evidence_insufficient
    """
    fixtures.reset_clock()
    request = fixtures.create_request(
        committee,
        title="Single citation request",
        evidence_citations=[factories.build_citation("Local practice memo", True)],
        **CARDIOLOGY_REQUEST,
    )
    assert request["peer_reviewed_citation_count"] == 1

    response = api_client.triage_content_request(
        request["id"],
        factories.build_triage_payload("ACCEPT", triage_note="Looks reasonable"),
        committee["chair_headers"],
    )
    validate_error(response, ApiErrorId.ERR_EVIDENCE_INSUFFICIENT, 422)

    unchanged = fixtures.read_request(committee, request["id"])
    assert unchanged["status"] == "INTAKE_SUBMITTED"
    assert unchanged["version"] == 1
    # still the provisional 30 for grade B, ROUTINE and no safety flag
    assert unchanged["priority_score_basis"] == "INTAKE_PROVISIONAL"
    assertions.assert_numeric_equals(unchanged["priority_score"], 30.00, 2)


def test_two_citations_with_one_peer_reviewed_sit_exactly_on_the_bar(committee):
    """The satisfying side of both thresholds, and the score drops on acceptance.

    "A request must carry at least two citations, of which at least one is peer
    reviewed". "The citation component is 6 points for each peer-reviewed citation,
    capped at 40 points however many there are. The urgency and safety components
    are the same as before — 0, 12 or 25 points for urgency, and 15 points when
    `patient_safety_flag` is true. ... The base is multiplied by one plus that age
    bonus, the product is rounded half-up to two decimal places".

    Design: Corner/validations/validation_triage_accept_passes_with_exactly_two_citations_one_peer_reviewed
    """
    fixtures.reset_clock()
    request = fixtures.create_request(
        committee,
        title="Two citation request",
        evidence_citations=[
            factories.build_citation("Circulation 2021 statin trial", True),
            factories.build_citation("Vendor monograph", False),
        ],
        **CARDIOLOGY_REQUEST,
    )
    assertions.assert_numeric_equals(request["priority_score"], 30.00, 2)
    assert request["peer_reviewed_citation_count"] == 1

    accepted = validate_success(
        api_client.triage_content_request(
            request["id"],
            factories.build_triage_payload(
                "ACCEPT", triage_note="Evidence just sufficient"
            ),
            committee["chair_headers"],
        )
    )

    assert accepted["status"] == "TRIAGE_ACCEPTED"
    assert accepted["priority_score_basis"] == "COMMITTEE_CALIBRATED"
    # 6 for the single peer-reviewed citation, no urgency or safety points, no backlog
    assertions.assert_numeric_equals(accepted["priority_score"], 6.00, 2)
    assert accepted["version"] == 2


# ---------------------------------------------------------------------------
# The aggregate capacity bar
# ---------------------------------------------------------------------------


INSULIN_REQUEST = {
    "title": "Insulin infusion governance",
    "request_type": "BOTH",
    "clinical_domain": "ENDOCRINOLOGY",
    "urgency": "SAFETY_URGENT",
    "evidence_grade": "A",
    "patient_safety_flag": True,
    "evidence_citations": [
        factories.build_citation("Diabetes Care 2022 infusion protocol", True),
        factories.build_citation("ISMP insulin safety 2023", True),
    ],
}

INSULIN_HARD_STOP = {
    "name": "Insulin infusion hard stop",
    "severity_tier": "TIER_1_HARD_STOP",
    "override_reason_codes": ["CLINICAL_JUDGMENT", "PATIENT_SPECIFIC_PLAN"],
    "hard_stop_justification": (
        "Hypoglycaemia deaths reported without paired monitoring"
    ),
    "firing_criteria": {
        "trigger_event": "ORDER_ENTRY",
        "expression": "insulin_infusion without glucose_monitoring",
    },
}


def test_two_individually_affordable_reviews_breach_the_capacity_together(committee):
    """35 fits in 60 and 30 fits in 60, but 65 does not.

    "An assignment that would push `review_workload_assigned_minutes` above
    `review_workload_capacity_minutes` is refused with
    `ERR_REVIEWER_CAPACITY_EXCEEDED`; the test is on the aggregate, so several
    individually modest assignments can collectively breach the cap." "An
    order-set peer review costs 20 minutes on a `STANDARD` build and 35 on a `HIGH`
    one ... An alert review is priced by tier instead: 30 minutes for
    `TIER_1_HARD_STOP`".

    Design: Corner/validations/validation_reviewer_capacity_exceeded_by_the_aggregate_of_two_small_assignments
    """
    fixtures.reset_clock()
    scenario = fixtures.setup_order_set_in_peer_review(
        committee,
        request_overrides=INSULIN_REQUEST,
        order_set_overrides={"name": "Insulin infusion v1", "specialty": "ENDOCRINOLOGY"},
        item_payloads=[
            factories.build_high_alert_item_payload(
                orderable_code="MED-INS-INF",
                display_name="Insulin regular infusion",
                default_dose="1 unit/mL",
                sequence_index=1,
            )
        ],
    )
    order_set = scenario["order_set"]
    assert order_set["risk_class"] == "HIGH"
    alert = fixtures.design_alert(
        committee, scenario["content_request"], **INSULIN_HARD_STOP
    )

    reviewer = fixtures.register_clinician(
        ["PeerReviewer", "SpecialtyApprover"],
        full_name="Tina Tight",
        specialty="CRITICAL_CARE",
        review_workload_capacity_minutes=60,
    )
    peer_assignment = validate_success(
        api_client.create_review_assignment(
            factories.build_review_assignment_payload(
                reviewer["id"], "PEER_REVIEW", order_set_id=order_set["id"]
            ),
            committee["chair_headers"],
        ),
        201,
    )
    assert peer_assignment["estimated_minutes"] == 35
    assertions.assert_workload_ledger(
        validate_success(
            api_client.get_clinician(reviewer["id"], committee["chair_headers"])
        ),
        35,
        25,
        1,
    )

    # the tier prices this one at 30, and 35 + 30 exceeds the 60-minute capacity
    response = api_client.create_review_assignment(
        factories.build_review_assignment_payload(
            reviewer["id"], "SPECIALTY_APPROVAL", alert_id=alert["id"]
        ),
        committee["chair_headers"],
    )
    validate_error(response, ApiErrorId.ERR_REVIEWER_CAPACITY_EXCEEDED, 422)

    assertions.assert_workload_ledger(
        validate_success(
            api_client.get_clinician(reviewer["id"], committee["chair_headers"])
        ),
        35,
        25,
        1,
    )
    _rows, meta = validate_paginated(
        api_client.list_review_assignments(
            committee["chair_headers"], {"alert_id": alert["id"]}
        )
    )
    assert meta["total_count"] == 0
    assert fixtures.read_alert(committee, alert["id"])["review_state"] == "DRAFT"


# ---------------------------------------------------------------------------
# A condition the designer does not fully control
# ---------------------------------------------------------------------------


BEERS_REQUEST = {
    "title": "Two tier alert bundle",
    "clinical_domain": "GERIATRICS",
    "urgency": "ROUTINE",
    "evidence_grade": "B",
    "evidence_citations": [
        factories.build_citation("Beers criteria 2023", True),
        factories.build_citation("JAGS deprescribing 2021", True),
    ],
}


def test_the_tier_overrules_the_designers_false_and_then_demands_two_codes(committee):
    """A passive alert activates with no codes; an interruptive one may not.

    "`override_reason_required` is forced to true for `TIER_1_HARD_STOP` and
    `TIER_2_INTERRUPTIVE` regardless of what the designer submitted, and only a
    `TIER_3_PASSIVE` alert may leave it false. When `override_reason_required` is
    true, the alert must declare at least two entries in `override_reason_codes`
    before it can be activated, and a shortfall is `ERR_OVERRIDE_REASON_REQUIRED`."
    "Optionally it carries `override_reason_codes` (the allowed override reason code
    strings, an empty array by default)".

    Design: Corner/validations/validation_override_reason_codes_required_only_when_the_flag_is_true
    """
    fixtures.reset_clock()
    content_request = fixtures.setup_accepted_request(
        committee, request_type="ALERT", **BEERS_REQUEST
    )
    passive = fixtures.design_alert(
        committee,
        content_request,
        name="Passive Beers advisory",
        severity_tier="TIER_3_PASSIVE",
        override_reason_codes=[],
        override_reason_required=False,
        firing_criteria={
            "trigger_event": "ORDER_ENTRY",
            "expression": "beers_medication and age >= 65",
        },
    )
    interruptive = fixtures.design_alert(
        committee,
        content_request,
        name="Interruptive Beers stop",
        severity_tier="TIER_2_INTERRUPTIVE",
        override_reason_codes=["CLINICAL_JUDGMENT"],
        override_reason_required=False,
        firing_criteria={
            "trigger_event": "ORDER_ENTRY",
            "expression": "beers_medication and age >= 80",
        },
    )
    assert passive["override_reason_required"] is False
    # the submitted false does not survive the tier
    assert interruptive["override_reason_required"] is True

    fixtures.run_alert_approval_stage(committee, passive["id"])
    activated = fixtures.activate_alert(
        committee, passive["id"], activation_note="Passive go live"
    )
    # an empty code list is legal precisely because the flag stayed false
    assertions.assert_alert_states(activated, "APPROVED", "ACTIVE")
    assert activated["override_reason_codes"] == []

    fixtures.run_alert_approval_stage(committee, interruptive["id"])
    response = api_client.activate_alert(
        interruptive["id"],
        factories.build_activation_payload(activation_note="Interruptive go live"),
        committee["chair_headers"],
    )
    validate_error(response, ApiErrorId.ERR_OVERRIDE_REASON_REQUIRED, 422)

    blocked = fixtures.read_alert(committee, interruptive["id"])
    assertions.assert_alert_states(blocked, "APPROVED", "UNPUBLISHED")
    assert blocked["review_due_date"] is None
    assert blocked["expiration_at"] is None
