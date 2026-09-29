"""State machines that are not a single forward chain.

An order set walks two independent dimensions on one row, an alert cycles
between two lifecycle values without the cycle being idempotent, and a vendor
release forks on a numeric threshold into two arms that rejoin at one state with
different permissions on each arm.
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
# Two independent dimensions on one order set row
# ---------------------------------------------------------------------------


CAP_REQUEST_OVERRIDES = {
    "title": "Community acquired pneumonia order set",
    "request_type": "ORDER_SET",
    "clinical_domain": "HOSPITAL_MEDICINE",
    "urgency": "ROUTINE",
    "evidence_grade": "B",
    "patient_safety_flag": False,
}

CAP_ITEM = {
    "orderable_code": "AZITHRO500",
    "display_name": "Azithromycin 500 mg IV",
    "item_category": "MEDICATION",
    "high_alert_medication": False,
}


def test_review_dimension_climbs_while_the_publication_dimension_stands_still(committee):
    """Three review transitions leave publication_state at UNPUBLISHED.

    "Order sets and alerts each carry **two independent state dimensions**, and
    the system never collapses them. An `OrderSet` has a `review_state` covering
    governance (`DRAFT`, `PEER_REVIEW`, `SPECIALTY_APPROVAL`, `APPROVED`) and a
    `publication_state` covering its life in production (`UNPUBLISHED`,
    `PUBLISHED`, `EXPIRING`, `EXPIRED`, `ARCHIVED`, `SUPERSEDED`)".

    Design: Difficulty/non_linear_state_machine/non_linear_order_set_parallel_review_and_publication_dimensions
    """
    fixtures.reset_clock()
    release = fixtures.setup_activated_release(committee)
    content_request = fixtures.setup_accepted_request(committee, **CAP_REQUEST_OVERRIDES)

    created = validate_success(
        api_client.create_order_set(
            content_request["id"],
            factories.build_order_set_payload(
                committee["builder"]["id"],
                release["id"],
                content_request["version"],
                name="CAP admission",
                specialty="HOSPITAL_MEDICINE",
            ),
            committee["builder_headers"],
        ),
        201,
    )
    order_set_id = created["id"]
    assertions.assert_order_set_states(created, "DRAFT", "UNPUBLISHED")

    fixtures.add_item(committee, order_set_id, **CAP_ITEM)
    submitted = validate_success(
        api_client.submit_order_set_for_peer_review(
            order_set_id,
            factories.build_submit_for_peer_review_payload(
                submission_note="Ready for peer review"
            ),
            committee["builder_headers"],
        )
    )
    # the review dimension has now moved twice; the publication dimension not at all
    assertions.assert_order_set_states(submitted, "PEER_REVIEW", "UNPUBLISHED")

    fixtures.run_peer_stage(committee, order_set_id)
    after_peer = fixtures.read_order_set(committee, order_set_id)
    assertions.assert_order_set_states(after_peer, "SPECIALTY_APPROVAL", "UNPUBLISHED")

    assignments = fixtures.run_specialty_stage(committee, order_set_id)
    assert len(assignments) == 2
    approved = fixtures.read_order_set(committee, order_set_id)
    assertions.assert_order_set_states(approved, "APPROVED", "UNPUBLISHED")
    assert approved["go_live_at"] is None


def test_publication_dimension_moves_twice_more_with_review_state_frozen(committee):
    """Publication and then expiry advance while review_state stays APPROVED.

    "On success `publication_state` advances `UNPUBLISHED → PUBLISHED`,
    `go_live_at` is stored from the request, and the **review schedule** is
    computed from it." "A task in state `PENDING` whose `review_due_date` the
    clock has reached moves `PENDING → OVERDUE`, and because that task became
    overdue, the order set it governs moves `publication_state` `PUBLISHED →
    EXPIRING`".

    Design: Difficulty/non_linear_state_machine/non_linear_order_set_parallel_review_and_publication_dimensions
    """
    fixtures.reset_clock()
    scenario = fixtures.setup_approved_order_set(
        committee,
        request_overrides=CAP_REQUEST_OVERRIDES,
        item_payloads=[CAP_ITEM],
    )
    order_set_id = scenario["order_set"]["id"]

    published = validate_success(
        api_client.publish_order_set(
            order_set_id,
            factories.build_publish_payload("2026-08-15T00:00:00Z"),
            committee["chair_headers"],
        )
    )
    assertions.assert_order_set_states(published, "APPROVED", "PUBLISHED")
    assert published["go_live_at"] == "2026-08-15T00:00:00Z"
    # STANDARD risk: anchor plus 365 days, then 30 days of grace, then 90 more
    assertions.assert_review_schedule(
        published,
        "2027-08-15T00:00:00Z",
        "2027-09-14T00:00:00Z",
        "2027-12-13T00:00:00Z",
    )

    fixtures.set_clock("2027-08-15T00:00:00Z")
    sweep = validate_success(
        api_client.run_expiration_sweep(
            factories.build_expiration_sweep_payload(dry_run=False),
            committee["chair_headers"],
        )
    )
    assertions.assert_sweep_counts(
        sweep,
        tasks_marked_overdue=1,
        order_sets_marked_expiring=1,
        order_sets_expired=0,
        tasks_expired=0,
    )

    swept = fixtures.read_order_set(committee, order_set_id)
    # the publication dimension moved a third time; the review dimension never did
    assertions.assert_order_set_states(swept, "APPROVED", "EXPIRING")
    task = fixtures.task_for_order_set(committee, order_set_id)
    assert task["state"] == "OVERDUE"


# ---------------------------------------------------------------------------
# A lifecycle cycle that is not idempotent
# ---------------------------------------------------------------------------


DUPLICATE_ANTICOAGULANT = {
    "name": "Duplicate anticoagulant",
    "severity_tier": "TIER_2_INTERRUPTIVE",
    "override_reason_codes": ["CLINICALLY_APPROPRIATE", "PATIENT_TOLERATES"],
    "firing_criteria": {
        "trigger_event": "NEW_MEDICATION_ORDER",
        "expression": "active_order(anticoagulant) AND new_order(anticoagulant)",
    },
}


def test_first_suspension_stores_a_reason_that_resumption_clears(committee):
    """One suspend-resume pair returns to ACTIVE with the counter at 1.

    "The chair supplies a `suspension_reason`, which is stored, and
    `suspension_count` increments by 1 as `lifecycle_state` moves `ACTIVE →
    SUSPENDED`". "Resuming reverses the pause: with an optional `resume_note`,
    an alert moves `SUSPENDED → ACTIVE` and `suspension_reason` is cleared".

    Design: Difficulty/non_linear_state_machine/non_linear_alert_lifecycle_suspend_resume_cycle_accumulates_count
    """
    fixtures.reset_clock()
    scenario = fixtures.setup_active_alert(
        committee, alert_overrides=DUPLICATE_ANTICOAGULANT
    )
    alert_id = scenario["alert"]["id"]
    assertions.assert_alert_states(scenario["alert"], "APPROVED", "ACTIVE")
    assert scenario["alert"]["suspension_count"] == 0

    suspended = validate_success(
        api_client.suspend_alert(
            alert_id,
            factories.build_suspend_payload(
                suspension_reason="Excess interruption reported by nursing"
            ),
            committee["chair_headers"],
        )
    )
    assertions.assert_alert_states(suspended, "APPROVED", "SUSPENDED")
    assert suspended["suspension_count"] == 1
    assert suspended["suspension_reason"] == "Excess interruption reported by nursing"

    resumed = validate_success(
        api_client.resume_alert(
            alert_id,
            factories.build_resume_payload(resume_note="Criteria narrowed"),
            committee["chair_headers"],
        )
    )
    assertions.assert_alert_states(resumed, "APPROVED", "ACTIVE")
    assert resumed["suspension_reason"] is None
    assert resumed["suspension_count"] == 1


def test_second_cycle_restores_the_state_but_not_the_cycle_counter(committee):
    """Two full cycles end at ACTIVE with suspension_count at 2.

    "An alert may cycle through suspension and resumption any number of times
    and `suspension_count` keeps accumulating." "An `Alert` has a `review_state`
    (`DRAFT`, `SPECIALTY_APPROVAL`, `APPROVED`) and a `lifecycle_state`
    (`UNPUBLISHED`, `ACTIVE`, `SUSPENDED`, `RETIRED`)".

    Design: Difficulty/non_linear_state_machine/non_linear_alert_lifecycle_suspend_resume_cycle_accumulates_count
    """
    fixtures.reset_clock()
    scenario = fixtures.setup_active_alert(
        committee, alert_overrides=DUPLICATE_ANTICOAGULANT
    )
    alert_id = scenario["alert"]["id"]

    validate_success(
        api_client.suspend_alert(
            alert_id,
            factories.build_suspend_payload(suspension_reason="First escalation"),
            committee["chair_headers"],
        )
    )
    validate_success(
        api_client.resume_alert(
            alert_id, factories.build_resume_payload(), committee["chair_headers"]
        )
    )
    second_suspend = validate_success(
        api_client.suspend_alert(
            alert_id,
            factories.build_suspend_payload(suspension_reason="Second burden escalation"),
            committee["chair_headers"],
        )
    )
    assertions.assert_alert_states(second_suspend, "APPROVED", "SUSPENDED")
    assert second_suspend["suspension_count"] == 2

    second_resume = validate_success(
        api_client.resume_alert(
            alert_id,
            factories.build_resume_payload(resume_note="Criteria narrowed again"),
            committee["chair_headers"],
        )
    )
    # the state returned to its starting value; the counter did not
    assertions.assert_alert_states(second_resume, "APPROVED", "ACTIVE")
    assert second_resume["suspension_count"] == 2
    assert second_resume["suspension_reason"] is None


# ---------------------------------------------------------------------------
# A fork on a threshold whose two arms rejoin with different permissions
# ---------------------------------------------------------------------------


FOUR_DELTAS = [
    {
        "rule_code": "DDI-1",
        "change_type": "SEVERITY_INCREASED",
        "description": "Warfarin plus fluconazole raised",
        "prior_severity": "MAJOR",
        "new_severity": "CONTRAINDICATED",
    },
    {
        "rule_code": "DDI-2",
        "change_type": "SEVERITY_INCREASED",
        "description": "Linezolid plus SSRI raised",
        "prior_severity": "MAJOR",
        "new_severity": "CONTRAINDICATED",
    },
    {
        "rule_code": "DDI-3",
        "change_type": "NEW_INTERACTION",
        "description": "New major interaction",
        "new_severity": "MAJOR",
    },
    {
        "rule_code": "DOSE-4",
        "change_type": "DOSING_BOUND_CHANGED",
        "description": "Vancomycin upper bound lowered",
        "new_severity": "MODERATE",
    },
]

FIFTH_DELTA = {
    "rule_code": "DDI-5",
    "change_type": "RETIRED_INTERACTION",
    "description": "Obsolete pair withdrawn",
    "new_severity": None,
}


def _analysed_pair(committee):
    """Two releases differing only by one 2-point delta, both impact-analysed."""
    fixtures.reset_clock()
    release_a = fixtures.create_release(committee, release_label="2026.08-A")
    deltas_a = [
        fixtures.add_delta(committee, release_a["id"], **delta) for delta in FOUR_DELTAS
    ]
    release_b = fixtures.create_release(committee, release_label="2026.08-B")
    deltas_b = [
        fixtures.add_delta(committee, release_b["id"], **delta) for delta in FOUR_DELTAS
    ]
    deltas_b.append(fixtures.add_delta(committee, release_b["id"], **FIFTH_DELTA))
    return {
        "release_a": release_a,
        "release_b": release_b,
        "deltas_a": deltas_a,
        "deltas_b": deltas_b,
        "analysed_a": fixtures.run_impact_analysis(committee, release_a["id"]),
        "analysed_b": fixtures.run_impact_analysis(committee, release_b["id"]),
    }


def test_one_two_point_delta_decides_which_arm_of_the_fork_a_release_takes(committee):
    """24 points forks to fast track and 26 points to clinical review.

    "On creation the server assigns the delta's `weight` from its `change_type`
    — 5 for `SEVERITY_INCREASED`, 3 for `NEW_INTERACTION`, 3 for
    `DOSING_BOUND_CHANGED`, 2 for `RETIRED_INTERACTION`, 1 for
    `SEVERITY_DECREASED` — plus a bonus of 4 when `new_severity` is
    `CONTRAINDICATED`." "A score below 25 routes it `RECEIVED →
    IMPACT_ANALYZED_FAST_TRACK`; a score of 25 or more routes it `RECEIVED →
    IMPACT_ANALYZED_CLINICAL_REVIEW`."

    Design: Difficulty/non_linear_state_machine/non_linear_vendor_release_fork_join_divergent_side_effects
    """
    pair = _analysed_pair(committee)

    # SEVERITY_INCREASED 5 plus the CONTRAINDICATED bonus 4
    assert pair["deltas_a"][0]["weight"] == 9
    assertions.assert_whole_integer(pair["deltas_a"][0]["weight"])
    assert pair["deltas_b"][4]["weight"] == 2

    assert pair["analysed_a"]["impact_score"] == 24
    assert pair["analysed_a"]["review_cycle_state"] == "IMPACT_ANALYZED_FAST_TRACK"
    assert pair["analysed_b"]["impact_score"] == 26
    assert pair["analysed_b"]["review_cycle_state"] == "IMPACT_ANALYZED_CLINICAL_REVIEW"

    assert pair["analysed_a"]["contraindicated_delta_count"] == 2
    assert pair["analysed_b"]["contraindicated_delta_count"] == 2
    assert pair["analysed_a"]["delta_count"] == 4
    assert pair["analysed_b"]["delta_count"] == 5


def test_the_two_arms_rejoin_at_activated_under_different_permissions(committee):
    """The role that activates the fast-track arm is refused on the other.

    "Either a `PharmacyInformaticist` or a `CommitteeChair` may take a release
    `IMPACT_ANALYZED_FAST_TRACK → ACTIVATED`". "The clinical-review branch is
    the chair's alone — a `PharmacyInformaticist` attempting it is refused with
    `ERR_UNAUTHORIZED`". "`restaged_order_set_count` stays at 0: the fast-track
    branch does not mark any pinned order set stale".

    Design: Difficulty/non_linear_state_machine/non_linear_vendor_release_fork_join_divergent_side_effects
    """
    pair = _analysed_pair(committee)
    for delta in pair["deltas_a"][:3]:
        validate_success(
            api_client.disposition_vendor_rule_delta(
                delta["id"],
                factories.build_disposition_payload("ACCEPT"),
                committee["pharmacist_headers"],
            )
        )
    validate_success(
        api_client.disposition_vendor_rule_delta(
            pair["deltas_a"][3]["id"],
            factories.build_disposition_payload(
                "SUPPRESS", suppression_justification="Local dosing service owns this bound"
            ),
            committee["pharmacist_headers"],
        )
    )
    for delta in pair["deltas_b"][:4]:
        validate_success(
            api_client.disposition_vendor_rule_delta(
                delta["id"],
                factories.build_disposition_payload("ACCEPT"),
                committee["chair_headers"],
            )
        )
    validate_success(
        api_client.disposition_vendor_rule_delta(
            pair["deltas_b"][4]["id"],
            factories.build_disposition_payload(
                "SUPPRESS",
                suppression_justification="Pair no longer clinically relevant per P&T minutes",
            ),
            committee["chair_headers"],
        )
    )

    activated_a = validate_success(
        api_client.activate_vendor_release(
            pair["release_a"]["id"],
            factories.build_release_activation_payload(activation_note="Fast track arm"),
            committee["pharmacist_headers"],
        )
    )
    assert activated_a["review_cycle_state"] == "ACTIVATED"
    assert activated_a["restaged_order_set_count"] == 0
    assert activated_a["dispositioned_delta_count"] == 4

    refused = api_client.activate_vendor_release(
        pair["release_b"]["id"],
        factories.build_release_activation_payload(activation_note="Attempted by pharmacy"),
        committee["pharmacist_headers"],
    )
    validate_error(refused, ApiErrorId.ERR_UNAUTHORIZED, 403)

    activated_b = validate_success(
        api_client.activate_vendor_release(
            pair["release_b"]["id"],
            factories.build_release_activation_payload(activation_note="Clinical review arm"),
            committee["chair_headers"],
        )
    )
    assert activated_b["review_cycle_state"] == "ACTIVATED"
    # no published order set is pinned to a predecessor here
    assert activated_b["restaged_order_set_count"] == 0
    assert activated_b["dispositioned_delta_count"] == 5
