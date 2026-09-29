"""Gates whose blocking condition lives on an entity the request never names.

In both pairs the artifact being acted on is faultless: the first refusal comes
from a pinned vendor release that was analysed but never activated, the second
from a linked order set that was approved but never published. Each pair then
moves only the other entity and replays the identical call.
"""

from test_helpers import (
    ApiErrorId,
    api_client,
    assertions,
    factories,
    fixtures,
    validate_error,
    validate_success,
)


# ---------------------------------------------------------------------------
# OrderSet publication gated on VendorContentRelease.review_cycle_state
# ---------------------------------------------------------------------------


SEPSIS_REQUEST = {
    "title": "Sepsis lactate order set",
    "request_type": "ORDER_SET",
    "clinical_domain": "CRITICAL_CARE",
    "urgency": "ROUTINE",
    "evidence_grade": "A",
    "patient_safety_flag": False,
}

LACTATE_ITEM = {
    "orderable_code": "LACTATE",
    "display_name": "Serum lactate",
    "item_category": "LAB",
    "high_alert_medication": False,
}


def _approved_build_pinned_to_an_unactivated_release(committee):
    """An APPROVED order set pinned to a release left in IMPACT_ANALYZED_FAST_TRACK."""
    fixtures.reset_clock()
    release = fixtures.create_release(committee)
    fixtures.add_delta(committee, release["id"])
    analysed = fixtures.run_impact_analysis(committee, release["id"])
    fixtures.disposition_all_deltas(committee, release["id"], "ACCEPT")

    content_request = fixtures.setup_accepted_request(committee, **SEPSIS_REQUEST)
    order_set = fixtures.build_order_set(
        committee,
        content_request,
        release["id"],
        name="Sepsis lactate",
        specialty="CRITICAL_CARE",
    )
    fixtures.add_item(committee, order_set["id"], **LACTATE_ITEM)
    fixtures.submit_for_peer_review(committee, order_set["id"])
    fixtures.run_peer_stage(committee, order_set["id"])
    fixtures.run_specialty_stage(committee, order_set["id"])

    return {
        "release": release,
        "analysed": analysed,
        "content_request": content_request,
        "order_set": fixtures.read_order_set(committee, order_set["id"]),
    }


def test_publication_is_refused_while_the_pinned_release_is_only_analysed(committee):
    """A faultless order set cannot publish because of a release it never names.

    "the release named by `pinned_vendor_release_id` must be in
    `review_cycle_state` `ACTIVATED`, or the request is refused with
    `ERR_VENDOR_RELEASE_NOT_ACTIVATED`." "A score below 25 routes it `RECEIVED →
    IMPACT_ANALYZED_FAST_TRACK`".

    Design: Difficulty/cross_entity_state_dependency/cross_entity_publish_blocked_until_pinned_vendor_release_is_activated
    """
    scenario = _approved_build_pinned_to_an_unactivated_release(committee)
    order_set_id = scenario["order_set"]["id"]
    assert scenario["analysed"]["impact_score"] == 3
    assert scenario["analysed"]["review_cycle_state"] == "IMPACT_ANALYZED_FAST_TRACK"
    # nothing about the order set itself is out of order
    assertions.assert_order_set_states(scenario["order_set"], "APPROVED", "UNPUBLISHED")
    assert scenario["order_set"]["high_alert_item_count"] == 0

    refused = api_client.publish_order_set(
        order_set_id,
        factories.build_publish_payload("2026-08-15T00:00:00Z"),
        committee["chair_headers"],
    )
    validate_error(refused, ApiErrorId.ERR_VENDOR_RELEASE_NOT_ACTIVATED, 409)

    unchanged = fixtures.read_order_set(committee, order_set_id)
    assertions.assert_order_set_states(unchanged, "APPROVED", "UNPUBLISHED")
    assert unchanged["go_live_at"] is None
    assert unchanged["review_due_date"] is None
    # a rejected publish creates no governing task
    assert fixtures.read_tasks(committee, order_set_id=order_set_id) == []


def test_activating_the_release_lets_the_identical_publish_succeed(committee):
    """Only the other entity moves, and the same payload now publishes.

    "Either a `PharmacyInformaticist` or a `CommitteeChair` may take a release
    `IMPACT_ANALYZED_FAST_TRACK → ACTIVATED`". "On success `publication_state`
    advances `UNPUBLISHED → PUBLISHED`, `go_live_at` is stored from the request,
    and the **review schedule** is computed from it." "a `STANDARD` artifact is
    reviewed 365 days after its anchor instant".

    Design: Difficulty/cross_entity_state_dependency/cross_entity_publish_blocked_until_pinned_vendor_release_is_activated
    """
    scenario = _approved_build_pinned_to_an_unactivated_release(committee)
    order_set_id = scenario["order_set"]["id"]

    first = api_client.publish_order_set(
        order_set_id,
        factories.build_publish_payload("2026-08-15T00:00:00Z"),
        committee["chair_headers"],
    )
    validate_error(first, ApiErrorId.ERR_VENDOR_RELEASE_NOT_ACTIVATED, 409)

    activated = validate_success(
        api_client.activate_vendor_release(
            scenario["release"]["id"],
            factories.build_release_activation_payload(activation_note="Now activated"),
            committee["pharmacist_headers"],
        )
    )
    assert activated["review_cycle_state"] == "ACTIVATED"

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

    task = fixtures.task_for_order_set(committee, order_set_id)
    assert task["state"] == "PENDING"
    assert task["cycle_index"] == 1


# ---------------------------------------------------------------------------
# Alert activation gated on OrderSet.publication_state
# ---------------------------------------------------------------------------


BOTH_REQUEST = {
    "title": "Vancomycin order set and renal dosing alert",
    "request_type": "BOTH",
    "clinical_domain": "NEPHROLOGY",
    "urgency": "ROUTINE",
    "evidence_grade": "B",
    "patient_safety_flag": False,
}

VANC_ITEM = {
    "orderable_code": "VANC-TROUGH",
    "display_name": "Vancomycin trough level",
    "item_category": "LAB",
    "high_alert_medication": False,
}

LINKED_ALERT = {
    "name": "Renal dose adjustment required",
    "severity_tier": "TIER_2_INTERRUPTIVE",
    "override_reason_codes": ["CLINICALLY_APPROPRIATE", "DOSE_ALREADY_ADJUSTED"],
    "firing_criteria": {
        "trigger_event": "NEW_MEDICATION_ORDER",
        "expression": "eGFR < 30 AND new_order(renally_cleared_drug)",
    },
}


def _approved_alert_linked_to_an_unpublished_order_set(committee):
    """An APPROVED alert whose linked order set is APPROVED but not published."""
    fixtures.reset_clock()
    scenario = fixtures.setup_approved_order_set(
        committee, request_overrides=BOTH_REQUEST, item_payloads=[VANC_ITEM]
    )
    order_set_id = scenario["order_set"]["id"]

    alert = fixtures.design_alert(
        committee,
        scenario["content_request"],
        linked_order_set_id=order_set_id,
        **LINKED_ALERT,
    )
    fixtures.run_alert_approval_stage(committee, alert["id"])
    scenario["alert"] = fixtures.read_alert(committee, alert["id"])
    return scenario


def test_alert_activation_is_refused_while_its_linked_order_set_is_unpublished(committee):
    """The alert's own review dimension is complete, so only the link explains it.

    "If `linked_order_set_id` is not null, that order set's `publication_state`
    must be `PUBLISHED`, or activation is refused with
    `ERR_LINKED_ORDER_SET_NOT_PUBLISHED`." "An `Alert` has a `review_state`
    (`DRAFT`, `SPECIALTY_APPROVAL`, `APPROVED`) and a `lifecycle_state`
    (`UNPUBLISHED`, `ACTIVE`, `SUSPENDED`, `RETIRED`)".

    Design: Difficulty/cross_entity_state_dependency/cross_entity_alert_activation_blocked_until_linked_order_set_is_published
    """
    scenario = _approved_alert_linked_to_an_unpublished_order_set(committee)
    alert_id = scenario["alert"]["id"]
    # approval is not publication, and the gate reads the publication dimension only
    assertions.assert_order_set_states(scenario["order_set"], "APPROVED", "UNPUBLISHED")
    assertions.assert_alert_states(scenario["alert"], "APPROVED", "UNPUBLISHED")

    refused = api_client.activate_alert(
        alert_id,
        factories.build_activation_payload(
            activation_note="Attempted before publication"
        ),
        committee["chair_headers"],
    )
    validate_error(refused, ApiErrorId.ERR_LINKED_ORDER_SET_NOT_PUBLISHED, 409)

    unchanged = fixtures.read_alert(committee, alert_id)
    assertions.assert_alert_states(unchanged, "APPROVED", "UNPUBLISHED")
    assert unchanged["review_due_date"] is None
    assert unchanged["expiration_at"] is None
    assert fixtures.read_tasks(committee, alert_id=alert_id) == []


def test_publishing_the_order_set_unblocks_an_activation_anchored_on_the_clock(committee):
    """Activation succeeds and dates itself from the clock, not from go_live_at.

    "On success `lifecycle_state` advances `UNPUBLISHED → ACTIVE`;
    `review_due_date` is the current instant plus the review interval for the
    alert's risk class ... `expiration_at` is that date plus the 30-day grace
    period." "the parent request closes as `CLOSED_IMPLEMENTED` if its
    `request_type` is now satisfied."

    Design: Difficulty/cross_entity_state_dependency/cross_entity_alert_activation_blocked_until_linked_order_set_is_published
    """
    scenario = _approved_alert_linked_to_an_unpublished_order_set(committee)
    alert_id = scenario["alert"]["id"]

    published = fixtures.publish(
        committee, scenario["order_set"]["id"], "2026-08-15T00:00:00Z"
    )
    assertions.assert_order_set_states(published, "APPROVED", "PUBLISHED")

    activated = validate_success(
        api_client.activate_alert(
            alert_id,
            factories.build_activation_payload(activation_note="Order set is live"),
            committee["chair_headers"],
        )
    )
    assertions.assert_alert_states(activated, "APPROVED", "ACTIVE")
    # the clock still reads 2026-08-01, two weeks before the order set goes live
    assertions.assert_review_schedule(
        activated, "2027-08-01T00:00:00Z", "2027-08-31T00:00:00Z"
    )

    request = fixtures.read_request(committee, scenario["content_request"]["id"])
    assert request["status"] == "CLOSED_IMPLEMENTED"
