"""Authority coverage: exclusive acts, a shared read, and duty separation.

Two probes fence off an exclusive act by role, one shows a read that no role
narrows, and one shows the separate question segregation of duties asks — the
right role in the wrong hands.
"""

from test_helpers import (
    ApiErrorId,
    api_client,
    assertions,
    factories,
    fixtures,
    make_committee_chair_headers,
    make_specialty_approver_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

CARDIOLOGY_REQUEST = {
    "title": "Heart failure discharge set",
    "request_type": "ORDER_SET",
    "clinical_domain": "CARDIOLOGY",
    "urgency": "ROUTINE",
    "evidence_grade": "B",
    "patient_safety_flag": False,
    "evidence_citations": [
        factories.build_citation("JACC 2022 GDMT", True),
        factories.build_citation("Clinic pathway", False),
    ],
}

SACUBITRIL_ITEM = {
    "orderable_code": "MED-SACU",
    "display_name": "Sacubitril-valsartan",
    "item_category": "MEDICATION",
    "default_dose": "24-26 mg",
    "sequence_index": 1,
}


# ---------------------------------------------------------------------------
# An exclusive act refused to a neighbouring role
# ---------------------------------------------------------------------------


def test_only_the_chair_may_triage_even_for_the_builder_who_will_build_it(committee):
    """The builder's call is a 403; the chair's identical call is a 200.

    "Once the caller is authenticated, the declared role is checked against the
    roles permitted for the endpoint; a caller whose committee roles contain nothing
    permitted for that endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    "Only a `CommitteeChair` may triage a request, create or withdraw a review
    assignment, publish an order set, activate, suspend, resume or retire an alert,
    or finalize a measurement." "Accepting a request advances `INTAKE_SUBMITTED →
    TRIAGE_ACCEPTED`". "`priority_score_basis` is set to `COMMITTEE_CALIBRATED`."

    Design: Corner/rbac/rbac_committee_chair_exclusive_triage_is_forbidden_to_the_informatics_builder
    """
    fixtures.reset_clock()
    request = fixtures.create_request(
        committee,
        title="Triage authority test",
        request_type="ORDER_SET",
        clinical_domain="CARDIOLOGY",
        urgency="ROUTINE",
        evidence_grade="B",
        evidence_citations=[
            factories.build_citation("Guideline A", True),
            factories.build_citation("Guideline B", True),
        ],
    )
    assert request["status"] == "INTAKE_SUBMITTED"

    refused = api_client.triage_content_request(
        request["id"],
        factories.build_triage_payload("ACCEPT", triage_note="Not my call"),
        committee["builder_headers"],
    )
    validate_error(refused, ApiErrorId.ERR_UNAUTHORIZED, 403)
    untouched = fixtures.read_request(committee, request["id"])
    assert untouched["status"] == "INTAKE_SUBMITTED"
    assert untouched["version"] == 1

    accepted = validate_success(
        api_client.triage_content_request(
            request["id"],
            factories.build_triage_payload("ACCEPT", triage_note="Committee accepts"),
            committee["chair_headers"],
        )
    )
    assert accepted["status"] == "TRIAGE_ACCEPTED"
    assert accepted["priority_score_basis"] == "COMMITTEE_CALIBRATED"
    assert accepted["version"] == 2


# ---------------------------------------------------------------------------
# A read no role narrows
# ---------------------------------------------------------------------------


def test_all_seven_roles_read_the_same_order_set_row(committee):
    """Seven callers, seven 200s, one unchanged version.

    "Where the endpoint table in §4 lists "Any role" it means all seven roles are
    permitted." "The system recognises exactly seven roles: `ClinicalSponsor`,
    `InformaticsBuilder`, `PeerReviewer`, `SpecialtyApprover`, `CommitteeChair`,
    `PharmacyInformaticist`, and `SystemAdmin`." "The new order set starts with
    `review_state` `DRAFT`, `publication_state` `UNPUBLISHED`, `item_count` and
    `high_alert_item_count` at 0". "`version` is an integer that starts at 1 on
    creation and increments by exactly 1 on every mutation of the resource".

    Design: Corner/rbac/rbac_order_set_read_is_shared_by_every_clinical_role
    """
    fixtures.reset_clock()
    scenario = fixtures.setup_draft_order_set(
        committee,
        request_overrides={**CARDIOLOGY_REQUEST, "title": "Shared read target"},
        order_set_overrides={"name": "Shared read v1", "specialty": "CARDIOLOGY"},
        item_payloads=[],
    )
    order_set_id = scenario["order_set"]["id"]

    readers = [
        committee["sponsor_headers"],
        committee["chair_headers"],
        committee["builder_headers"],
        committee["pharmacist_headers"],
        committee["peer_headers"][0],
        committee["specialist_headers"][0],
        committee["admin_headers"],
    ]
    payloads = [
        validate_success(api_client.get_order_set(order_set_id, headers))
        for headers in readers
    ]

    assert len(payloads) == 7
    for payload in payloads:
        assertions.assert_order_set_states(payload, "DRAFT", "UNPUBLISHED")
        assert payload["item_count"] == 0
        assert payload["version"] == 1
        assert payload["id"] == order_set_id
    # reading is not a mutation, however many callers do it
    assert payloads[0] == payloads[-1]
    assert fixtures.read_order_set(committee, order_set_id)["version"] == 1


# ---------------------------------------------------------------------------
# The right role in the wrong hands
# ---------------------------------------------------------------------------


def test_the_deciding_approver_may_not_publish_what_they_just_approved(committee):
    """A chair-and-approver is refused; a different chair is not.

    "And the approver who cast the deciding specialty vote on an artifact may not
    then be the one who publishes that order set or activates that alert." "A
    clinician may hold several roles in `authorized_roles`, so the second question is
    always asked separately, and it is asked by comparing `X-User-ID` and stored
    identity fields on the artifact." "The specialty approver who cast the deciding
    vote may not be the one publishing, per §2.10." "a `STANDARD` artifact is
    reviewed 365 days after its anchor instant".

    Design: Corner/rbac/rbac_deciding_specialty_voter_cannot_publish_the_artifact_they_approved
    """
    fixtures.reset_clock()
    scenario = fixtures.setup_order_set_in_specialty_approval(
        committee,
        request_overrides=CARDIOLOGY_REQUEST,
        order_set_overrides={"name": "HF discharge v1", "specialty": "CARDIOLOGY"},
        item_payloads=[SACUBITRIL_ITEM],
    )
    order_set_id = scenario["order_set"]["id"]
    assert scenario["order_set"]["risk_class"] == "STANDARD"
    dual_role = fixtures.register_clinician(
        ["SpecialtyApprover", "CommitteeChair"],
        full_name="Dana Dual",
        specialty="NEPHROLOGY",
    )

    first = fixtures.assign_reviewer(
        committee,
        committee["specialists"][0]["id"],
        "SPECIALTY_APPROVAL",
        order_set_id=order_set_id,
    )
    deciding = fixtures.assign_reviewer(
        committee, dual_role["id"], "SPECIALTY_APPROVAL", order_set_id=order_set_id
    )
    fixtures.cast_vote(
        committee, first["id"], committee["specialist_headers"][0], "APPROVE"
    )
    closing_vote = validate_success(
        api_client.cast_review_vote(
            deciding["id"],
            factories.build_cast_payload("APPROVE", comment="Deciding specialty vote"),
            make_specialty_approver_headers(dual_role["id"]),
        )
    )
    assert closing_vote["state"] == "CAST"
    approved = fixtures.read_order_set(committee, order_set_id)
    # 2 of 2 approving is 1.0000, clear of the 0.6667 bar for a STANDARD build
    assertions.assert_order_set_states(approved, "APPROVED", "UNPUBLISHED")

    self_release = api_client.publish_order_set(
        order_set_id,
        factories.build_publish_payload("2026-08-15T00:00:00Z"),
        make_committee_chair_headers(dual_role["id"]),
    )
    validate_error(self_release, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)
    held = fixtures.read_order_set(committee, order_set_id)
    assertions.assert_order_set_states(held, "APPROVED", "UNPUBLISHED")
    assert held["go_live_at"] is None

    published = validate_success(
        api_client.publish_order_set(
            order_set_id,
            factories.build_publish_payload("2026-08-15T00:00:00Z"),
            committee["chair_headers"],
        )
    )
    assertions.assert_order_set_states(published, "APPROVED", "PUBLISHED")
    assert published["go_live_at"] == "2026-08-15T00:00:00Z"
    assert published["review_due_date"] == "2027-08-15T00:00:00Z"


# ---------------------------------------------------------------------------
# The author cannot serve themselves the release step
# ---------------------------------------------------------------------------


DIABETES_REQUEST = {
    "title": "Diabetes admission bundle",
    "request_type": "BOTH",
    "clinical_domain": "ENDOCRINOLOGY",
    "urgency": "ROUTINE",
    "evidence_grade": "B",
    "patient_safety_flag": False,
    "evidence_citations": [
        factories.build_citation("ADA standards 2024", True),
        factories.build_citation("Unit protocol", False),
    ],
}


def test_the_builder_owns_the_build_but_not_the_release(committee):
    """Publishing and activating are both refused to the author's role.

    "Only an `InformaticsBuilder` may create an order set build, design an alert, or
    submit an order set for peer review." "Only a `CommitteeChair` may triage a
    request, create or withdraw a review assignment, publish an order set, activate,
    suspend, resume or retire an alert, or finalize a measurement." "a caller whose
    committee roles contain nothing permitted for that endpoint is rejected with
    `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/rbac_approval_chain_release_step_is_forbidden_to_the_builder_role
    """
    fixtures.reset_clock()
    scenario = fixtures.setup_approved_order_set(
        committee,
        request_overrides=DIABETES_REQUEST,
        order_set_overrides={"name": "Diabetes admission v1", "specialty": "ENDOCRINOLOGY"},
        item_payloads=[
            factories.build_order_set_item_payload(
                orderable_code="LAB-A1C",
                display_name="Hemoglobin A1c",
                item_category="LAB",
                sequence_index=1,
            )
        ],
    )
    order_set_id = scenario["order_set"]["id"]
    alert = fixtures.design_alert(
        committee,
        scenario["content_request"],
        name="Hypoglycaemia advisory",
        severity_tier="TIER_3_PASSIVE",
        override_reason_required=False,
        override_reason_codes=[],
        firing_criteria={"trigger_event": "LAB_RESULT", "expression": "glucose < 70"},
    )
    fixtures.run_alert_approval_stage(committee, alert["id"])

    refused_publication = api_client.publish_order_set(
        order_set_id,
        factories.build_publish_payload("2026-08-15T00:00:00Z"),
        committee["builder_headers"],
    )
    validate_error(refused_publication, ApiErrorId.ERR_UNAUTHORIZED, 403)

    refused_activation = api_client.activate_alert(
        alert["id"],
        factories.build_activation_payload(activation_note="Self service"),
        committee["builder_headers"],
    )
    validate_error(refused_activation, ApiErrorId.ERR_UNAUTHORIZED, 403)

    held_order_set = fixtures.read_order_set(committee, order_set_id)
    assertions.assert_order_set_states(held_order_set, "APPROVED", "UNPUBLISHED")
    assert held_order_set["go_live_at"] is None

    held_alert = fixtures.read_alert(committee, alert["id"])
    assertions.assert_alert_states(held_alert, "APPROVED", "UNPUBLISHED")
    # PRD §3.3/§3.5 declare no `activated_at` on an Alert (only on
    # VendorContentRelease and DowntimeEvent), so nothing is asserted about it.
    assert held_alert["review_due_date"] is None
    assert held_alert["expiration_at"] is None

    _tasks, meta = validate_paginated(
        api_client.list_annual_review_tasks(committee["admin_headers"])
    )
    # no release step ran, so no review cycle exists for either artifact
    assert meta["total_count"] == 0
