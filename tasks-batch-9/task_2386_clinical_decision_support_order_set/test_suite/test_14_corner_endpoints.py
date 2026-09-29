"""Endpoint coverage: a sub-collection, a bulk action, a link rule, a read.

The item collection is written out of order and read back in order; the firing
ingest is driven once and its whole batch inspected; the assignment endpoint is
handed the wrong number of targets twice; and one order-set read is checked
against the assignment rows it summarises.
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
# A sub-collection written out of order
# ---------------------------------------------------------------------------


PAIN_REQUEST = {
    "title": "Post-op pain order set",
    "request_type": "ORDER_SET",
    "clinical_domain": "ORTHOPEDICS",
    "urgency": "ROUTINE",
    "evidence_grade": "B",
    "evidence_citations": [
        factories.build_citation("Anesthesiology 2020 multimodal analgesia", True),
        factories.build_citation("Hospital formulary note", False),
    ],
}


def test_items_come_back_in_sequence_order_and_the_filter_narrows_them(committee):
    """Written 3, 1, 2 and read 1, 2, 3, with one high-alert row selectable.

    "the order set item list is sorted by `sequence_index` ascending". "The
    `sequence_index` controls display order within the order set, must be at least
    1, and must be unique within its `order_set_id`". "Every added line increments
    the order set's `item_count`, and a line whose `high_alert_medication` is true
    also increments `high_alert_item_count`." "`version` is an integer that starts at
    1 on creation and increments by exactly 1 on every mutation of the resource,
    including mutations the server performs on its own initiative when a cascade
    reaches the resource".

    Design: Corner/endpoints/endpoint_order_set_items_create_then_list_in_sequence_order
    """
    fixtures.reset_clock()
    release = fixtures.create_release(committee, content_domain="DOSING")
    content_request = fixtures.setup_accepted_request(committee, **PAIN_REQUEST)
    order_set = fixtures.build_order_set(
        committee,
        content_request,
        release["id"],
        name="Post-op pain v1",
        specialty="ORTHOPEDICS",
    )
    fixtures.add_item(
        committee,
        order_set["id"],
        orderable_code="MED-OXY",
        display_name="Oxycodone PRN",
        item_category="MEDICATION",
        high_alert_medication=True,
        default_dose="5 mg",
        route="PO",
        frequency="Q4H PRN",
        default_selected=False,
        sequence_index=3,
    )
    fixtures.add_item(
        committee,
        order_set["id"],
        orderable_code="MED-APAP",
        display_name="Acetaminophen scheduled",
        item_category="MEDICATION",
        default_dose="1000 mg",
        route="PO",
        frequency="Q6H",
        default_selected=True,
        sequence_index=1,
    )
    fixtures.add_item(
        committee,
        order_set["id"],
        orderable_code="NUR-PAIN-SCORE",
        display_name="Pain score every shift",
        item_category="NURSING",
        default_selected=True,
        sequence_index=2,
    )

    rows, meta = validate_paginated(
        api_client.list_order_set_items(order_set["id"], committee["chair_headers"])
    )
    assertions.assert_pagination_meta(meta, 10, 0, 3, False)
    # display order, not creation order
    assert [row["orderable_code"] for row in rows] == [
        "MED-APAP",
        "NUR-PAIN-SCORE",
        "MED-OXY",
    ]
    assertions.assert_sorted_ascending([row["sequence_index"] for row in rows])

    high_alert, high_alert_meta = validate_paginated(
        api_client.list_order_set_items(
            order_set["id"], committee["chair_headers"], {"high_alert_medication": True}
        )
    )
    assert high_alert_meta["total_count"] == 1
    assert high_alert[0]["orderable_code"] == "MED-OXY"

    reread = fixtures.read_order_set(committee, order_set["id"])
    assert reread["item_count"] == 3
    assert reread["high_alert_item_count"] == 1
    # one mutation per added line on top of the creation version
    assert reread["version"] == 4


# ---------------------------------------------------------------------------
# A bulk action endpoint
# ---------------------------------------------------------------------------


RENAL_REQUEST = {
    "title": "Renal dosing advisory",
    "clinical_domain": "NEPHROLOGY",
    "urgency": "ROUTINE",
    "evidence_grade": "B",
    "evidence_citations": [
        factories.build_citation("KDIGO 2023 dosing", True),
        factories.build_citation("Local nephrology consensus", False),
    ],
}

RENAL_ALERT = {
    "name": "Renal dose adjust advisory",
    "severity_tier": "TIER_2_INTERRUPTIVE",
    "override_reason_codes": ["CLINICAL_JUDGMENT", "DOSE_ALREADY_ADJUSTED"],
    "firing_criteria": {
        "trigger_event": "ORDER_ENTRY",
        "expression": "egfr < 30 and renally_cleared_drug",
    },
}


def test_one_ingest_call_lays_down_a_whole_deterministic_batch(committee):
    """Seven rows, three overridden, two clinician refs alternating back to the first.

    "It creates exactly `fire_count` firing records whose `fired_at` values are
    `fired_at_start` plus the interval multiplied by the record's 0-based index,
    running from 0 up to one less than `fire_count`. The first `override_count` of
    those records are created with `accepted` false and the supplied
    `override_reason_code`; every remaining record is created with `accepted` true
    and a null reason code. Each record's `firing_clinician_ref` is assigned
    round-robin as `SYN-001` through `SYN-` followed by the
    `distinct_clinician_count`, zero-padded to three digits." "The capability
    reports back a `created_event_count`, the `first_fired_at` and `last_fired_at`
    instants, an `override_event_count`, and the `distinct_clinician_count` it
    actually used."

    Design: Corner/endpoints/endpoint_alert_firings_bulk_ingest_returns_per_batch_counts
    """
    fixtures.reset_clock()
    scenario = fixtures.setup_active_alert(
        committee, request_overrides=RENAL_REQUEST, alert_overrides=RENAL_ALERT
    )
    alert_id = scenario["alert"]["id"]

    batch = validate_success(
        api_client.ingest_alert_firings(
            factories.build_firing_ingest_payload(
                alert_id,
                "2026-08-03T08:00:00Z",
                fire_count=7,
                override_count=3,
                distinct_clinician_count=2,
                interval_seconds=600,
                override_reason_code="DOSE_ALREADY_ADJUSTED",
            ),
            fixtures.ADMIN_HEADERS,
        ),
        201,
    )
    assert batch["created_event_count"] == 7
    assert batch["override_event_count"] == 3
    assert batch["distinct_clinician_count"] == 2
    assert batch["first_fired_at"] == "2026-08-03T08:00:00Z"
    # six 600-second steps from the start instant
    assert batch["last_fired_at"] == "2026-08-03T09:00:00Z"

    overridden, overridden_meta = validate_paginated(
        api_client.list_override_events(
            alert_id, committee["chair_headers"], {"accepted": False, "limit": 100}
        )
    )
    assert overridden_meta["total_count"] == 3
    assert all(row["override_reason_code"] == "DOSE_ALREADY_ADJUSTED" for row in overridden)
    assert all(row["accepted"] is False for row in overridden)

    accepted, accepted_meta = validate_paginated(
        api_client.list_override_events(
            alert_id, committee["chair_headers"], {"accepted": True, "limit": 100}
        )
    )
    assert accepted_meta["total_count"] == 4
    assert all(row["override_reason_code"] is None for row in accepted)

    by_sequence = {row["ingest_batch_seq"]: row for row in overridden + accepted}
    assert sorted(by_sequence) == [0, 1, 2, 3, 4, 5, 6]
    assert [by_sequence[index]["firing_clinician_ref"] for index in range(7)] == [
        "SYN-001",
        "SYN-002",
        "SYN-001",
        "SYN-002",
        "SYN-001",
        "SYN-002",
        "SYN-001",
    ]

    alert = fixtures.read_alert(committee, alert_id)
    assertions.assert_firing_ledger(alert, 7, 0, 7)


# ---------------------------------------------------------------------------
# The exactly-one-target link rule
# ---------------------------------------------------------------------------


CONTRAST_REQUEST = {
    "title": "Contrast allergy pathway",
    "request_type": "BOTH",
    "clinical_domain": "EMERGENCY",
    "urgency": "ROUTINE",
    "evidence_grade": "B",
    "evidence_citations": [
        factories.build_citation("ACR contrast manual 2023", True),
        factories.build_citation("Department protocol", False),
    ],
}


def test_an_assignment_needs_exactly_one_target_neither_nor_both(committee):
    """Zero targets and two targets are the same schema failure, and cost nothing.

    "The `CommitteeChair` creates each **review assignment**, naming the
    `reviewer_id`, a `review_kind` of `PEER_REVIEW` or `SPECIALTY_APPROVAL`, exactly
    one of `order_set_id` or `alert_id`, and an optional advisory `due_at` that is
    recorded but never enforced as a gate. Supplying neither target or both is
    `ERR_INVALID_REQUEST`."

    Design: Corner/endpoints/endpoint_review_assignment_without_exactly_one_artifact_reference_returns_invalid_request
    """
    fixtures.reset_clock()
    scenario = fixtures.setup_order_set_in_peer_review(
        committee,
        request_overrides=CONTRAST_REQUEST,
        order_set_overrides={"name": "Contrast premedication v1", "specialty": "EMERGENCY"},
        item_payloads=[
            factories.build_order_set_item_payload(
                orderable_code="MED-PRED",
                display_name="Prednisone premedication",
                item_category="MEDICATION",
                sequence_index=1,
            )
        ],
    )
    alert = fixtures.design_alert(
        committee,
        scenario["content_request"],
        name="Contrast allergy advisory",
        severity_tier="TIER_3_PASSIVE",
        override_reason_codes=[],
        override_reason_required=False,
        firing_criteria={
            "trigger_event": "ORDER_ENTRY",
            "expression": "contrast_order and documented_contrast_allergy",
        },
    )
    reviewer = fixtures.register_clinician(
        ["PeerReviewer", "SpecialtyApprover"],
        full_name="Rita Reviewer",
        specialty="INTERNAL_MEDICINE",
    )

    neither = api_client.create_review_assignment(
        factories.build_review_assignment_payload(reviewer["id"], "PEER_REVIEW"),
        committee["chair_headers"],
    )
    validate_error(neither, ApiErrorId.ERR_INVALID_REQUEST, 400)

    both = api_client.create_review_assignment(
        factories.build_review_assignment_payload(
            reviewer["id"],
            "PEER_REVIEW",
            order_set_id=scenario["order_set"]["id"],
            alert_id=alert["id"],
        ),
        committee["chair_headers"],
    )
    validate_error(both, ApiErrorId.ERR_INVALID_REQUEST, 400)

    _rows, meta = validate_paginated(
        api_client.list_review_assignments(
            committee["chair_headers"], {"reviewer_id": reviewer["id"]}
        )
    )
    assert meta["total_count"] == 0
    assertions.assert_workload_ledger(
        validate_success(
            api_client.get_clinician(reviewer["id"], committee["chair_headers"])
        ),
        0,
        480,
        0,
    )
    # no assignment landed, so the alert's approval stage was never seeded
    assert fixtures.read_alert(committee, alert["id"])["review_state"] == "DRAFT"


# ---------------------------------------------------------------------------
# A read whose fields summarise another collection
# ---------------------------------------------------------------------------


INFLUENZA_REQUEST = {
    "title": "Influenza admission order set",
    "request_type": "ORDER_SET",
    "clinical_domain": "HOSPITAL_MEDICINE",
    "urgency": "ROUTINE",
    "evidence_grade": "B",
    "patient_safety_flag": False,
    "evidence_citations": [
        factories.build_citation("IDSA influenza 2018", True),
        factories.build_citation("CDC seasonal guidance", False),
    ],
}


def test_the_order_set_read_summarises_its_assignment_rows_exactly(committee):
    """Two cast rows, one of them approving, hold the stage short of quorum.

    "Those counters are persisted so the committee can read them:
    `peer_required_votes`, `peer_cast_count` and `peer_approve_ratio` for the peer
    stage ... plus `votes_cast_count` and `votes_voided_count` counting all
    assignments on the order set in state `CAST` and `VOIDED` respectively." "On an
    order set, a `PEER_REVIEW` vote of `REVISE` does **not** revert the stage; it
    merely lowers `peer_approve_ratio` and so may keep quorum out of reach." "the
    approve ratio is at least the required approval ratio for the risk class, which
    is 0.8000 for `HIGH` and 0.6667 for `STANDARD`".

    Design: Corner/endpoints/endpoint_order_set_read_exposes_derived_vote_counters_matching_the_assignment_list
    """
    fixtures.reset_clock()
    scenario = fixtures.setup_order_set_in_peer_review(
        committee,
        request_overrides=INFLUENZA_REQUEST,
        order_set_overrides={
            "name": "Influenza admission v1",
            "specialty": "HOSPITAL_MEDICINE",
        },
        item_payloads=[
            factories.build_order_set_item_payload(
                orderable_code="MED-OSELT",
                display_name="Oseltamivir",
                item_category="MEDICATION",
                default_dose="75 mg",
                sequence_index=1,
            )
        ],
    )
    order_set_id = scenario["order_set"]["id"]
    assert scenario["order_set"]["risk_class"] == "STANDARD"
    assert scenario["order_set"]["peer_required_votes"] == 2

    assignments = [
        fixtures.assign_reviewer(
            committee, reviewer["id"], "PEER_REVIEW", order_set_id=order_set_id
        )
        for reviewer in committee["peers"]
    ]
    fixtures.cast_vote(
        committee,
        assignments[0]["id"],
        committee["peer_headers"][0],
        vote="REVISE",
        comment="Add a dose adjustment note",
    )
    fixtures.cast_vote(
        committee,
        assignments[1]["id"],
        committee["peer_headers"][1],
        vote="APPROVE",
        comment="Content accurate",
    )

    summary = validate_success(
        api_client.get_order_set(order_set_id, committee["chair_headers"])
    )
    assert summary["peer_cast_count"] == 2
    assertions.assert_numeric_equals(summary["peer_approve_ratio"], 0.5000, 4)
    assert summary["votes_cast_count"] == 2
    assert summary["votes_voided_count"] == 0
    # the cast count reached the requirement but the ratio did not
    assertions.assert_order_set_states(summary, "PEER_REVIEW", "UNPUBLISHED")
    assert summary["specialty_required_votes"] is None
    assert summary["revision_round"] == 0

    _cast, cast_meta = validate_paginated(
        api_client.list_review_assignments(
            committee["chair_headers"], {"order_set_id": order_set_id, "state": "CAST"}
        )
    )
    _open, open_meta = validate_paginated(
        api_client.list_review_assignments(
            committee["chair_headers"], {"order_set_id": order_set_id, "state": "ASSIGNED"}
        )
    )
    assert cast_meta["total_count"] == 2
    assert open_meta["total_count"] == 1
