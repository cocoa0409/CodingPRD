"""Entity-shape coverage: creation, retrieval, defaults, immutability, topology.

These probes stay close to the record definitions themselves — what the server
mints without being asked, what it defaults, what it refuses to accept, which
records carry no version at all, and how the foreign keys between records are
reachable from the list endpoints.
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

UNKNOWN_ORDER_SET_ID = "00000000-0000-4000-8000-000000000000"
UNKNOWN_PARENT_ORDER_SET_ID = "00000000-0000-4000-8000-0000000000ff"


# ---------------------------------------------------------------------------
# Clinician: creation, retrieval and declared defaults
# ---------------------------------------------------------------------------


def test_registering_a_clinician_returns_a_zeroed_workload_ledger():
    """Every declared input is echoed and the time budget starts wholly unspent.

    "A freshly registered clinician starts with `review_workload_assigned_minutes`
    at 0, `review_workload_remaining_minutes` equal to the full capacity, and
    `open_assignment_count` at 0." "`version` is an integer that starts at 1 on
    creation and increments by exactly 1 on every mutation of the resource".

    Design: Corner/entities/entity_clinician_create_returns_full_row_with_zeroed_workload_ledger
    """
    fixtures.reset_clock()

    clinician = validate_success(
        api_client.create_clinician(
            factories.build_clinician_payload(
                full_name="Ada Sponsor MD",
                npi="1000000001",
                specialty="CARDIOLOGY",
                credential="MD",
                authorized_roles=["ClinicalSponsor", "PeerReviewer"],
                employment_status="ACTIVE",
                review_workload_capacity_minutes=600,
            ),
            fixtures.ADMIN_HEADERS,
        ),
        201,
    )

    assertions.assert_common_fields(clinician)
    assert clinician["full_name"] == "Ada Sponsor MD"
    assert clinician["npi"] == "1000000001"
    assert clinician["specialty"] == "CARDIOLOGY"
    assert clinician["credential"] == "MD"
    assert clinician["authorized_roles"] == ["ClinicalSponsor", "PeerReviewer"]
    assertions.assert_workload_ledger(clinician, 0, 600, 0)
    assert clinician["review_workload_capacity_minutes"] == 600
    assert clinician["version"] == 1
    # the record is stamped from the logical clock, not from wall time
    assert clinician["created_at"].startswith("2026-08-01T00:00:00")


def test_reading_a_clinician_back_shows_no_field_drift():
    """The stored row is returned verbatim, capacity default included.

    "a `review_workload_capacity_minutes` review-time budget, which must be at
    least 0 and defaults to 480 minutes — eight hours of committee reading per
    cycle." "A freshly registered clinician starts with
    `review_workload_assigned_minutes` at 0, `review_workload_remaining_minutes`
    equal to the full capacity, and `open_assignment_count` at 0."

    Design: Corner/entities/entity_clinician_get_by_id_returns_the_stored_row
    """
    fixtures.reset_clock()
    created = fixtures.register_clinician(
        ["PeerReviewer"],
        full_name="Rex Reviewer DO",
        npi="1000000004",
        specialty="EMERGENCY",
        credential="DO",
    )

    stored = validate_success(
        api_client.get_clinician(created["id"], fixtures.ADMIN_HEADERS)
    )

    assert stored["id"] == created["id"]
    assert stored["npi"] == "1000000004"
    assert stored["specialty"] == "EMERGENCY"
    assert stored["review_workload_capacity_minutes"] == 480
    assertions.assert_workload_ledger(stored, 0, 480, 0)
    # a read is not a mutation, so the version has not moved off its initial value
    assert stored["version"] == 1


def test_omitting_the_optional_clinician_fields_applies_the_declared_defaults():
    """Three defaults land at once, and the derived remainder is not left null.

    "Optionally the admin supplies an `npi` national provider identifier (null by
    default), a `credential` of `MD`, `DO`, `PHARMD`, `RN` or `NP`, an
    `employment_status` of `ACTIVE` or `INACTIVE` (defaulting to `ACTIVE`), and a
    `review_workload_capacity_minutes` review-time budget, which must be at least
    0 and defaults to 480 minutes".

    Design: Corner/entities/entity_clinician_create_omitting_optional_fields_applies_declared_defaults
    """
    fixtures.reset_clock()

    clinician = validate_success(
        api_client.create_clinician(
            factories.build_clinician_payload(
                full_name="Dee Default RN",
                specialty="NURSING",
                credential="RN",
                authorized_roles=["PeerReviewer"],
            ),
            fixtures.ADMIN_HEADERS,
        ),
        201,
    )

    assert clinician["employment_status"] == "ACTIVE"
    assert clinician["review_workload_capacity_minutes"] == 480
    assertions.assert_workload_ledger(clinician, 0, 480, 0)
    assert clinician["npi"] is None


# ---------------------------------------------------------------------------
# ContentRequest: server-generated fields, listing and schema refusal
# ---------------------------------------------------------------------------


def test_intake_fills_every_system_field_without_the_sponsor_asking(committee):
    """Status, basis, score, citation count, return count and version are minted.

    "Creation lands the request in `status` `INTAKE_SUBMITTED`. The server derives
    `peer_reviewed_citation_count` as the number of `evidence_citations` entries
    whose `peer_reviewed` is true, sets `return_count` to 0, leaves `triage_note`
    null, and computes the **intake-provisional priority score**." "it awards 40
    points for evidence grade `A`, 30 for `B`, 18 for `C` and 8 for
    `EXPERT_OPINION`; adds 0 points for urgency `ROUTINE` ... `priority_score_basis`
    is set to `INTAKE_PROVISIONAL` to record which variant produced the stored
    number."

    Design: Corner/entities/entity_content_request_system_fields_are_server_generated_at_intake
    """
    fixtures.reset_clock()

    request = fixtures.create_request(
        committee,
        title="Sepsis bundle order set",
        request_type="ORDER_SET",
        clinical_domain="INTERNAL_MEDICINE",
        urgency="ROUTINE",
        evidence_grade="B",
        patient_safety_flag=False,
        evidence_citations=[factories.build_citation("Surviving Sepsis 2021", True)],
    )

    assertions.assert_common_fields(request)
    assert request["status"] == "INTAKE_SUBMITTED"
    assert request["priority_score_basis"] == "INTAKE_PROVISIONAL"
    # grade B 30 + ROUTINE 0 + no safety flag 0, with no multiplier of any kind
    assertions.assert_numeric_equals(request["priority_score"], 30.00, 2)
    assert request["peer_reviewed_citation_count"] == 1
    assert request["return_count"] == 0
    assert request["triage_note"] is None
    assert request["version"] == 1
    assert request["created_at"].startswith("2026-08-01T00:00:00")


def test_the_request_list_reports_total_count_has_more_and_worklist_order(committee):
    """Two pages cover three rows, and the filter narrows the total to one.

    "Every list response carries `limit`, `offset`, `total_count` and `has_more`
    inside the `meta` object of the envelope, where `total_count` is the number of
    records matching the filters before pagination is applied and `has_more`
    indicates whether any matching record remains beyond the current page." "the
    content request list is sorted by `priority_score` descending with
    `created_at` ascending as the tie-break".

    Design: Corner/entities/entity_content_request_list_paginates_with_total_count_and_has_more
    """
    fixtures.reset_clock()
    sepsis = fixtures.create_request(
        committee,
        title="Sepsis bundle order set",
        request_type="ORDER_SET",
        clinical_domain="INTERNAL_MEDICINE",
        urgency="ROUTINE",
        evidence_grade="B",
        evidence_citations=[factories.build_citation("Surviving Sepsis 2021", True)],
    )
    anticoagulation = fixtures.create_request(
        committee,
        title="Anticoagulation dosing alert",
        request_type="ALERT",
        clinical_domain="CARDIOLOGY",
        urgency="EXPEDITED",
        evidence_grade="A",
        evidence_citations=[factories.build_citation("CHEST 2020", True)],
    )
    pediatric = fixtures.create_request(
        committee,
        title="Pediatric fluid order set",
        request_type="BOTH",
        clinical_domain="PEDIATRICS",
        urgency="ROUTINE",
        evidence_grade="C",
        evidence_citations=[factories.build_citation("Local protocol", False)],
    )
    # 40 + 12, 30 + 0 and 18 + 0 respectively, so the worklist order is fixed
    assertions.assert_numeric_equals(anticoagulation["priority_score"], 52.00, 2)
    assertions.assert_numeric_equals(sepsis["priority_score"], 30.00, 2)
    assertions.assert_numeric_equals(pediatric["priority_score"], 18.00, 2)

    first_page, first_meta = validate_paginated(
        api_client.list_content_requests(
            committee["chair_headers"], {"limit": 2, "offset": 0}
        )
    )
    assertions.assert_pagination_meta(first_meta, 2, 0, 3, True)
    assert len(first_page) == 2
    assertions.assert_ids_in_order(
        first_page, [anticoagulation["id"], sepsis["id"]]
    )

    second_page, second_meta = validate_paginated(
        api_client.list_content_requests(
            committee["chair_headers"], {"limit": 2, "offset": 2}
        )
    )
    assertions.assert_pagination_meta(second_meta, 2, 2, 3, False)
    assert len(second_page) == 1
    assert second_page[0]["id"] == pediatric["id"]

    filtered, filtered_meta = validate_paginated(
        api_client.list_content_requests(
            committee["chair_headers"], {"clinical_domain": "PEDIATRICS"}
        )
    )
    # total_count is counted after the filter and before the page window
    assert filtered_meta["total_count"] == 1
    assert [row["id"] for row in filtered] == [pediatric["id"]]


def test_a_request_without_evidence_citations_is_a_schema_failure(committee):
    """The mandatory array cannot be omitted, and nothing is persisted.

    "Each citation object carries a required `citation` string and a required
    `peer_reviewed` boolean, plus an optional `doi` string and an optional
    `publication_year` integer; the array must contain at least one entry, and an
    empty array is an `ERR_INVALID_REQUEST` schema failure." "**Schema** —
    `ERR_INVALID_REQUEST` (400): a missing required field, an unknown enum member,
    a wrong JSON type, an empty array where at least one element is required, or a
    negative count."

    Design: Corner/entities/entity_content_request_missing_evidence_citations_returns_invalid_request
    """
    fixtures.reset_clock()
    payload = factories.build_content_request_payload(
        committee["sponsor"]["id"],
        title="Sepsis bundle order set",
        request_type="ORDER_SET",
        clinical_domain="INTERNAL_MEDICINE",
        urgency="ROUTINE",
        evidence_grade="B",
    )
    del payload["evidence_citations"]

    response = api_client.create_content_request(payload, committee["sponsor_headers"])
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST, 400)

    _rows, meta = validate_paginated(
        api_client.list_content_requests(committee["chair_headers"])
    )
    assert meta["total_count"] == 0


# ---------------------------------------------------------------------------
# Enum and identifier refusals
# ---------------------------------------------------------------------------


def test_a_near_miss_downtime_scope_member_is_rejected():
    """`ORDER_SETS` is not the declared token, so the schema check refuses it.

    "A `DowntimeEvent` declares a `scope` — one of `SYSTEM_WIDE`,
    `ORDER_SETS_ONLY`, `ALERTS_ONLY` — and a `mode`, either `READ_ONLY` or
    `FULL_UNAVAILABLE`." "**Schema** — `ERR_INVALID_REQUEST` (400): a missing
    required field, an unknown enum member, a wrong JSON type, an empty array
    where at least one element is required, or a negative count."

    Design: Corner/entities/entity_downtime_event_unknown_scope_enum_returns_invalid_request
    """
    fixtures.reset_clock()

    response = api_client.create_downtime_event(
        factories.build_downtime_event_payload(
            "2026-08-10T02:00:00Z",
            "2026-08-10T06:00:00Z",
            "ORDER_SETS",
            "READ_ONLY",
            planned=True,
            reason="EHR upgrade",
        ),
        fixtures.ADMIN_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST, 400)


def test_an_unknown_order_set_identifier_is_a_not_found_and_not_an_empty_body():
    """A well-formed UUID that names nothing resolves to the collection's own code.

    "Each collection has its own not-found code: a content request path yields
    `ERR_CONTENT_REQUEST_NOT_FOUND`, an order set path `ERR_ORDER_SET_NOT_FOUND`,
    an alert path `ERR_ALERT_NOT_FOUND`". "**Path existence**, evaluated left to
    right across the path (see §2.8) — the 404 family."

    Design: Corner/entities/entity_order_set_get_with_unknown_id_returns_not_found
    """
    fixtures.reset_clock()

    response = api_client.get_order_set(UNKNOWN_ORDER_SET_ID, fixtures.ADMIN_HEADERS)
    validate_error(response, ApiErrorId.ERR_ORDER_SET_NOT_FOUND, 404)


def test_an_item_posted_under_an_unknown_order_set_is_refused_before_the_body(committee):
    """The path 404 wins over a body that is itself unacceptable.

    "When a path carries more than one identifier, the identifiers are resolved
    strictly left to right and the first one that resolves to nothing determines
    the 404." "**Path existence**, evaluated left to right across the path (see
    §2.8) — the 404 family." "**Schema** — `ERR_INVALID_REQUEST` (400): a missing
    required field, an unknown enum member, a wrong JSON type".

    Design: Corner/entities/entity_order_set_item_under_unknown_order_set_returns_not_found
    """
    fixtures.reset_clock()

    response = api_client.create_order_set_item(
        UNKNOWN_PARENT_ORDER_SET_ID,
        factories.build_order_set_item_payload(
            orderable_code="LAB-LACT", display_name="Lactate, serum", item_category="LAB"
        ),
        committee["builder_headers"],
    )
    validate_error(response, ApiErrorId.ERR_ORDER_SET_NOT_FOUND, 404)

    # the same 404 still comes back when the body would also fail the schema check
    with_bad_body = api_client.create_order_set_item(
        UNKNOWN_PARENT_ORDER_SET_ID,
        factories.build_order_set_item_payload(item_category="LABORATORY"),
        committee["builder_headers"],
    )
    validate_error(with_bad_body, ApiErrorId.ERR_ORDER_SET_NOT_FOUND, 404)


# ---------------------------------------------------------------------------
# Append-only records
# ---------------------------------------------------------------------------


def test_an_order_set_item_carries_no_version_and_no_updated_at(committee):
    """The item line is an append-only observation on both the create and the list.

    "Two record types are append-only observations rather than governed artifacts,
    and they carry only `id` and `created_at`: an `OrderSetItem` line and an
    `OverrideEvent` firing record have no `updated_at` field and no `version`
    field at all." "optionally `default_selected` (whether the line is pre-checked
    when a clinician opens the order set, default `false`), `default_dose` (a
    pre-populated dose string such as 40 mg, meaningful for medication lines and
    null by default) ... `high_alert_medication` (default `false`)".

    Design: Corner/entities/entity_order_set_item_is_immutable_with_no_version_and_no_update_endpoint
    """
    fixtures.reset_clock()
    release = fixtures.create_release(committee)
    content_request = fixtures.setup_accepted_request(
        committee,
        title="Sepsis bundle order set",
        request_type="ORDER_SET",
        clinical_domain="INTERNAL_MEDICINE",
    )
    order_set = fixtures.build_order_set(
        committee,
        content_request,
        release["id"],
        name="Sepsis bundle v1",
        specialty="INTERNAL_MEDICINE",
    )

    item = validate_success(
        api_client.create_order_set_item(
            order_set["id"],
            factories.build_order_set_item_payload(
                orderable_code="LAB-LACT",
                display_name="Lactate, serum",
                item_category="LAB",
                sequence_index=1,
            ),
            committee["builder_headers"],
        ),
        201,
    )

    assertions.assert_append_only_fields(item)
    assert item["order_set_id"] == order_set["id"]
    assert item["sequence_index"] == 1
    assert item["default_selected"] is False
    assert item["high_alert_medication"] is False
    assert item["default_dose"] is None

    listed, meta = validate_paginated(
        api_client.list_order_set_items(order_set["id"], committee["chair_headers"])
    )
    assert meta["total_count"] == 1
    assertions.assert_append_only_fields(listed[0])


def test_override_events_are_append_only_and_only_the_ingest_mints_them(committee):
    """One batch produces three sequenced firing records that carry no version.

    "an `ingest_batch_seq` giving the firing's 0-based index inside its ingest
    batch so that ordering is deterministic." "It creates exactly `fire_count`
    firing records whose `fired_at` values are `fired_at_start` plus the interval
    multiplied by the record's 0-based index ... The first `override_count` of
    those records are created with `accepted` false and the supplied
    `override_reason_code`; every remaining record is created with `accepted` true
    and a null reason code." "an `OrderSetItem` line and an `OverrideEvent` firing
    record have no `updated_at` field and no `version` field at all."

    Design: Corner/entities/entity_override_event_is_immutable_and_only_reachable_through_ingest
    """
    fixtures.reset_clock()
    scenario = fixtures.setup_active_alert(
        committee,
        request_overrides={
            "title": "Lactate follow-up alert",
            "request_type": "ALERT",
            "clinical_domain": "INTERNAL_MEDICINE",
        },
        alert_overrides={
            "name": "Repeat lactate reminder",
            "severity_tier": "TIER_2_INTERRUPTIVE",
            "override_reason_codes": ["CLINICAL_JUDGMENT", "PATIENT_REFUSED"],
        },
    )
    alert_id = scenario["alert"]["id"]

    batch = validate_success(
        api_client.ingest_alert_firings(
            factories.build_firing_ingest_payload(
                alert_id,
                "2026-08-02T00:00:00Z",
                fire_count=3,
                override_count=2,
                distinct_clinician_count=2,
                interval_seconds=3600,
                override_reason_code="CLINICAL_JUDGMENT",
            ),
            fixtures.ADMIN_HEADERS,
        ),
        201,
    )
    assert batch["created_event_count"] == 3
    assert batch["override_event_count"] == 2
    assert batch["distinct_clinician_count"] == 2
    assert batch["first_fired_at"] == "2026-08-02T00:00:00Z"
    assert batch["last_fired_at"] == "2026-08-02T02:00:00Z"

    rows, meta = validate_paginated(
        api_client.list_override_events(alert_id, committee["chair_headers"])
    )
    assert meta["total_count"] == 3
    by_sequence = {row["ingest_batch_seq"]: row for row in rows}
    assert sorted(by_sequence) == [0, 1, 2]

    for sequence, row in by_sequence.items():
        assertions.assert_append_only_fields(row)
        assert row["alert_id"] == alert_id
        assert row["severity_tier_snapshot"] == "TIER_2_INTERRUPTIVE"
        # the first override_count records are the overridden ones, in batch order
        if sequence < 2:
            assert row["accepted"] is False
            assert row["override_reason_code"] == "CLINICAL_JUDGMENT"
        else:
            assert row["accepted"] is True
            assert row["override_reason_code"] is None


# ---------------------------------------------------------------------------
# Computed fields seeded from an enum table
# ---------------------------------------------------------------------------


def test_a_hard_stop_alert_takes_its_vote_requirement_from_the_tier_table(committee):
    """The caller never supplies the number: it is null until the stage opens.

    "A newly designed alert starts with `review_state` `DRAFT` and
    `lifecycle_state` `UNPUBLISHED`, with `required_approval_votes`,
    `latest_burden_index`, `latest_burden_classification`, `review_due_date`,
    `expiration_at`, `retired_at` and `suspension_reason` all null, and with
    `approval_cast_count`, `lifetime_fire_count`, `windowed_fire_count`,
    `unwindowed_fire_count`, `lifetime_override_count`, `suspension_count` and
    `restage_count` all at 0." "The first assignment created against an alert also
    opens that alert's single approval stage, advancing its `review_state` `DRAFT →
    SPECIALTY_APPROVAL` and seeding `required_approval_votes` from the tier: 3
    votes for `TIER_1_HARD_STOP`, 2 for `TIER_2_INTERRUPTIVE`, 1 for
    `TIER_3_PASSIVE`." "`override_reason_required` is forced to true for
    `TIER_1_HARD_STOP` and `TIER_2_INTERRUPTIVE` regardless of what the designer
    submitted".

    Design: Corner/entities/entity_alert_required_approval_votes_computed_from_severity_tier_at_creation
    """
    fixtures.reset_clock()
    content_request = fixtures.setup_accepted_request(
        committee,
        title="Potassium hard stop",
        request_type="ALERT",
        clinical_domain="INTERNAL_MEDICINE",
        urgency="SAFETY_URGENT",
        evidence_grade="A",
        patient_safety_flag=True,
        evidence_citations=[
            factories.build_citation("ISMP high alert list 2024", True),
            factories.build_citation("NEJM hyperkalemia 2019", True),
        ],
    )

    alert = fixtures.design_alert(
        committee,
        content_request,
        name="Potassium hard stop",
        severity_tier="TIER_1_HARD_STOP",
        override_reason_codes=["CLINICAL_JUDGMENT", "PATIENT_SPECIFIC_PLAN"],
        hard_stop_justification="Fatal arrhythmia risk documented in ISMP list",
        firing_criteria={
            "trigger_event": "ORDER_ENTRY",
            "expression": "potassium_iv_rate > 10 mEq/hr",
        },
    )

    assertions.assert_alert_states(alert, "DRAFT", "UNPUBLISHED")
    assert alert["required_approval_votes"] is None
    assert alert["approval_cast_count"] == 0
    # the designer submitted nothing about capture, and the tier forced it anyway
    assert alert["override_reason_required"] is True
    assertions.assert_firing_ledger(alert, 0, 0, 0)

    fixtures.assign_reviewer(
        committee,
        committee["specialists"][0]["id"],
        "SPECIALTY_APPROVAL",
        alert_id=alert["id"],
    )

    staged = fixtures.read_alert(committee, alert["id"])
    assertions.assert_alert_states(staged, "SPECIALTY_APPROVAL", "UNPUBLISHED")
    assert staged["required_approval_votes"] == 3
    assertions.assert_alert_required_votes(staged)
    assert staged["approval_cast_count"] == 0


# ---------------------------------------------------------------------------
# The foreign-key topology
# ---------------------------------------------------------------------------


def test_a_supersession_link_retires_only_the_predecessors_publication_state(committee):
    """The successor's foreign key moves one dimension and leaves the other alone.

    "If `supersedes_order_set_id` was supplied and names an order set whose
    `publication_state` is `UNPUBLISHED`, that predecessor transitions
    `UNPUBLISHED → SUPERSEDED` and every review assignment on it in state
    `ASSIGNED` or `CAST` is voided with `void_reason` `ARTIFACT_SUPERSEDED`".
    "Order sets may be listed filtered by `content_request_id`,
    `built_by_clinician_id`, `pinned_vendor_release_id`,
    `supersedes_order_set_id`, `pharmacy_signoff_by_clinician_id`, `review_state`,
    `publication_state`, `risk_class`, `specialty` and `pinned_content_stale`."

    Design: Corner/entities/entity_topology_graph_supersession_link_retires_the_predecessor_build
    """
    fixtures.reset_clock()
    release = fixtures.create_release(committee)
    content_request = fixtures.setup_accepted_request(
        committee,
        title="Sepsis bundle order set",
        request_type="ORDER_SET",
        clinical_domain="INTERNAL_MEDICINE",
    )

    predecessor = fixtures.build_order_set(
        committee,
        content_request,
        release["id"],
        name="Sepsis bundle v1",
        specialty="INTERNAL_MEDICINE",
    )
    # the first build advanced the request, so the guard needs the fresh version
    advanced = fixtures.read_request(committee, content_request["id"])
    successor = fixtures.build_order_set(
        committee,
        advanced,
        release["id"],
        name="Sepsis bundle v2",
        specialty="INTERNAL_MEDICINE",
        supersedes_order_set_id=predecessor["id"],
    )

    assert successor["supersedes_order_set_id"] == predecessor["id"]
    retired = fixtures.read_order_set(committee, predecessor["id"])
    assertions.assert_order_set_states(retired, "DRAFT", "SUPERSEDED")

    reverse, meta = validate_paginated(
        api_client.list_order_sets(
            committee["chair_headers"], {"supersedes_order_set_id": predecessor["id"]}
        )
    )
    assert meta["total_count"] == 1
    assert reverse[0]["id"] == successor["id"]


def test_one_reviewer_can_junction_to_both_an_order_set_and_an_alert(committee):
    """The two assignment rows name exactly one target each and price separately.

    "The `CommitteeChair` creates each **review assignment**, naming the
    `reviewer_id`, a `review_kind` of `PEER_REVIEW` or `SPECIALTY_APPROVAL`,
    exactly one of `order_set_id` or `alert_id`, and an optional advisory `due_at`
    that is recorded but never enforced as a gate." "An order-set peer review
    costs 20 minutes on a `STANDARD` build and 35 on a `HIGH` one ... An alert
    review is priced by tier instead: 30 minutes for `TIER_1_HARD_STOP`, 18 for
    `TIER_2_INTERRUPTIVE` and 10 for `TIER_3_PASSIVE`." "Assignments may be listed
    filtered by `order_set_id`, `alert_id`, `reviewer_id`, `review_kind`, `state`,
    `vote` and `evidence_concern`."

    Design: Corner/entities/entity_topology_graph_review_assignment_junctions_one_clinician_to_two_artifacts
    """
    fixtures.reset_clock()
    reviewer = fixtures.register_clinician(
        ["SpecialtyApprover", "PeerReviewer"],
        full_name="Sam Specialty MD",
        npi="1000000005",
        specialty="INTERNAL_MEDICINE",
        credential="MD",
    )
    release = fixtures.create_release(committee)
    content_request = fixtures.setup_accepted_request(
        committee,
        title="Sepsis bundle and alert",
        request_type="BOTH",
        clinical_domain="INTERNAL_MEDICINE",
    )
    order_set = fixtures.build_order_set(
        committee,
        content_request,
        release["id"],
        name="Sepsis bundle v1",
        specialty="INTERNAL_MEDICINE",
    )
    fixtures.add_item(
        committee,
        order_set["id"],
        orderable_code="LAB-LACT",
        display_name="Lactate, serum",
        item_category="LAB",
        sequence_index=1,
    )
    submitted = fixtures.submit_for_peer_review(
        committee, order_set["id"], submission_note="Ready for peer review"
    )
    assert submitted["risk_class"] == "STANDARD"

    alert = fixtures.design_alert(
        committee,
        fixtures.read_request(committee, content_request["id"]),
        name="Repeat lactate reminder",
        severity_tier="TIER_3_PASSIVE",
        override_reason_required=False,
    )

    on_order_set = fixtures.assign_reviewer(
        committee, reviewer["id"], "PEER_REVIEW", order_set_id=order_set["id"]
    )
    on_alert = fixtures.assign_reviewer(
        committee, reviewer["id"], "SPECIALTY_APPROVAL", alert_id=alert["id"]
    )

    assert on_order_set["order_set_id"] == order_set["id"]
    assert on_order_set["alert_id"] is None
    assertions.assert_order_set_review_minutes(on_order_set, "PEER_REVIEW", "STANDARD")
    assert on_alert["alert_id"] == alert["id"]
    assert on_alert["order_set_id"] is None
    assertions.assert_alert_review_minutes(on_alert, "TIER_3_PASSIVE")

    _both, both_meta = validate_paginated(
        api_client.list_review_assignments(
            committee["chair_headers"], {"reviewer_id": reviewer["id"]}
        )
    )
    assert both_meta["total_count"] == 2

    on_alert_only, alert_meta = validate_paginated(
        api_client.list_review_assignments(
            committee["chair_headers"], {"alert_id": alert["id"]}
        )
    )
    assert alert_meta["total_count"] == 1
    assert on_alert_only[0]["id"] == on_alert["id"]

    # 20 minutes for the standard peer review plus 10 for the passive alert
    assertions.assert_workload_ledger(
        validate_success(
            api_client.get_clinician(reviewer["id"], committee["chair_headers"])
        ),
        30,
        450,
        2,
    )
