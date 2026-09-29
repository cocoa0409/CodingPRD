"""Requests that violate two rules at once, where only one error may surface.

Each pair is arranged so both conditions are demonstrably live: the winning error
comes back first, then the losing condition is left alone while the winning one is
repaired, and the second error appears in its place.
"""

from test_helpers import (
    ApiErrorId,
    api_client,
    assertions,
    factories,
    fixtures,
    make_informatics_builder_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


# ---------------------------------------------------------------------------
# The 412 version guard against the parent's own 409 state gate
# ---------------------------------------------------------------------------


HYPERKALAEMIA_REQUEST = {
    "title": "Hyperkalaemia order set",
    "request_type": "ORDER_SET",
    "clinical_domain": "NEPHROLOGY",
    "urgency": "ROUTINE",
    "evidence_grade": "C",
    "patient_safety_flag": False,
    "evidence_citations": [
        factories.build_citation("KDIGO 2025", True),
        factories.build_citation("AJKD 2025;85:12", True),
        factories.build_citation("NEJM 2024;391:77", True),
        factories.build_citation("Unit protocol", False),
        factories.build_citation("Vendor brief", False),
    ],
}


def _returned_request(committee):
    """An activated release plus a request the chair sent back to its sponsor."""
    fixtures.reset_clock()
    release = fixtures.setup_activated_release(committee)
    request = fixtures.create_request(committee, **HYPERKALAEMIA_REQUEST)
    returned = fixtures.triage_request(
        committee,
        request["id"],
        "RETURN",
        triage_note="Dosing table needs a pharmacy source",
    )
    assert returned["status"] == "RETURNED_TO_SPONSOR"
    return release, returned


def test_a_stale_parent_version_outranks_the_parents_own_status_error(committee):
    """Both violations are live and the 412 is the one reported.

    "**Stale parent version** — the 412 guards of §2.6. Concurrency is checked
    after schema and existence but *before* any state precondition, so a stale
    version against an artifact that is also in the wrong state returns 412."
    "If that value does not equal the content request's current `version`, the
    request is rejected with `ERR_STALE_CONTENT_REQUEST_VERSION` and HTTP 412."

    Design: Difficulty/priority_pair_validation_conflict/priority_conflict_stale_parent_version_412_beats_request_not_accepted_409
    """
    release, returned = _returned_request(committee)

    response = api_client.create_order_set(
        returned["id"],
        factories.build_order_set_payload(
            committee["builder"]["id"],
            release["id"],
            returned["version"] - 1,
            name="Hyperkalaemia",
            specialty="NEPHROLOGY",
        ),
        committee["builder_headers"],
    )
    validate_error(response, ApiErrorId.ERR_STALE_CONTENT_REQUEST_VERSION, 412)

    listed, meta = validate_paginated(
        api_client.list_order_sets(
            committee["chair_headers"], {"content_request_id": returned["id"]}
        )
    )
    assert meta["total_count"] == 0
    assert listed == []


def test_satisfying_the_guard_lets_the_lower_priority_state_error_surface(committee):
    """The identical build with the right version reports the 409 instead.

    "A build may only be opened against a request whose `status` is
    `TRIAGE_ACCEPTED` or already `BUILD_IN_PROGRESS`; anything else is
    `ERR_CONTENT_REQUEST_NOT_ACCEPTED`." "**The primary artifact's own state** —
    the 409 family, one code per endpoint".

    Design: Difficulty/priority_pair_validation_conflict/priority_conflict_stale_parent_version_412_beats_request_not_accepted_409
    """
    release, returned = _returned_request(committee)

    response = api_client.create_order_set(
        returned["id"],
        factories.build_order_set_payload(
            committee["builder"]["id"],
            release["id"],
            returned["version"],
            name="Hyperkalaemia",
            specialty="NEPHROLOGY",
        ),
        committee["builder_headers"],
    )
    validate_error(response, ApiErrorId.ERR_CONTENT_REQUEST_NOT_ACCEPTED, 409)

    _listed, meta = validate_paginated(
        api_client.list_order_sets(
            committee["chair_headers"], {"content_request_id": returned["id"]}
        )
    )
    assert meta["total_count"] == 0


# ---------------------------------------------------------------------------
# The downtime freeze against a segregation-of-duties violation
# ---------------------------------------------------------------------------


WITHDRAWAL_REQUEST = {
    "title": "Alcohol withdrawal order set",
    "request_type": "ORDER_SET",
    "clinical_domain": "HOSPITAL_MEDICINE",
    "urgency": "ROUTINE",
    "evidence_grade": "B",
    "patient_safety_flag": False,
}

CIWA_ITEM = {
    "orderable_code": "CIWA",
    "display_name": "CIWA-Ar assessment",
    "item_category": "NURSING",
    "high_alert_medication": False,
}


def _frozen_order_set_built_by_a_reviewer(committee):
    """A build in peer review whose own builder also holds the reviewer role,
    with an ACTIVE read-only freeze over order-set content."""
    fixtures.reset_clock()
    dual_role = fixtures.register_clinician(
        ["InformaticsBuilder", "PeerReviewer"],
        full_name="Dr Bhatt",
        specialty="INFORMATICS",
    )
    committee["builder"] = dual_role
    committee["builder_headers"] = make_informatics_builder_headers(dual_role["id"])

    scenario = fixtures.setup_order_set_in_peer_review(
        committee,
        request_overrides=WITHDRAWAL_REQUEST,
        order_set_overrides={"name": "CIWA protocol", "specialty": "HOSPITAL_MEDICINE"},
        item_payloads=[CIWA_ITEM],
    )
    assertions.assert_order_set_states(scenario["order_set"], "PEER_REVIEW", "UNPUBLISHED")

    fixtures.set_clock("2026-08-05T00:00:00Z")
    event = fixtures.schedule_downtime(
        "2026-08-05T00:00:00Z",
        "2026-08-05T06:00:00Z",
        "ORDER_SETS_ONLY",
        "READ_ONLY",
        planned=True,
        reason="EHR upgrade",
    )
    scenario["downtime"] = fixtures.activate_downtime(
        event["id"], activation_note="Upgrade started"
    )
    assert scenario["downtime"]["state"] == "ACTIVE"
    return scenario


def test_the_content_freeze_outranks_the_segregation_of_duties_check(committee):
    """Nominating the builder as reviewer during a freeze reports the freeze.

    "**Downtime freeze** — `ERR_CDS_CONTENT_FROZEN` or `ERR_CDS_UNAVAILABLE`
    (409), per §2.11." "**Segregation of duties** —
    `ERR_SEGREGATION_OF_DUTIES` (403)." "Each in-scope mutation the freeze
    rejects increments that active event's `blocked_mutation_count` by 1".

    Design: Difficulty/priority_pair_validation_conflict/priority_conflict_content_frozen_409_beats_segregation_of_duties_403
    """
    scenario = _frozen_order_set_built_by_a_reviewer(committee)

    response = api_client.create_review_assignment(
        factories.build_review_assignment_payload(
            committee["builder"]["id"],
            "PEER_REVIEW",
            order_set_id=scenario["order_set"]["id"],
        ),
        committee["chair_headers"],
    )
    validate_error(response, ApiErrorId.ERR_CDS_CONTENT_FROZEN, 409)

    event = fixtures.read_downtime(scenario["downtime"]["id"])
    assert event["blocked_mutation_count"] == 1


def test_closing_the_downtime_lets_the_identity_violation_surface(committee):
    """The same call after the freeze lifts reports the 403 instead.

    "The clinician recorded as an order set's `built_by_clinician_id` may not be
    assigned to review that order set." "Closing, with an optional
    `closure_note`, sets `closed_at` to the current instant and takes an
    `ACTIVE` event to `CLOSED` — which resumes in-scope mutations".

    Design: Difficulty/priority_pair_validation_conflict/priority_conflict_content_frozen_409_beats_segregation_of_duties_403
    """
    scenario = _frozen_order_set_built_by_a_reviewer(committee)
    builder_id = committee["builder"]["id"]

    first = api_client.create_review_assignment(
        factories.build_review_assignment_payload(
            builder_id, "PEER_REVIEW", order_set_id=scenario["order_set"]["id"]
        ),
        committee["chair_headers"],
    )
    validate_error(first, ApiErrorId.ERR_CDS_CONTENT_FROZEN, 409)

    closed = validate_success(
        api_client.close_downtime_event(
            scenario["downtime"]["id"],
            factories.build_downtime_close_payload(closure_note="Upgrade complete"),
            fixtures.ADMIN_HEADERS,
        )
    )
    assert closed["state"] == "CLOSED"

    second = api_client.create_review_assignment(
        factories.build_review_assignment_payload(
            builder_id, "PEER_REVIEW", order_set_id=scenario["order_set"]["id"]
        ),
        committee["chair_headers"],
    )
    validate_error(second, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)

    # neither rejection debited the reviewer's time budget
    clinician = validate_success(
        api_client.get_clinician(builder_id, committee["chair_headers"])
    )
    assertions.assert_workload_ledger(clinician, 0, 480, 0)
