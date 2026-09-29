"""Row shapes: declared defaults, whole-record reads, page windows and references."""

from typing import Any, Dict

from prd_bench_local_runner.testing import NON_EXISTENT_UUID, validate_error

from test_helpers.api_errors import (
    ERR_CROSS_ENGAGEMENT_REFERENCE,
    ERR_ENGAGEMENT_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_SEGMENT_CYCLE,
)
from test_helpers.assertions import (
    assert_bare_uuid,
    assert_common_fields,
    assert_created,
    assert_error_envelope,
    assert_historical_fields,
    assert_money,
    assert_object_envelope,
    assert_ok,
    assert_pagination_meta,
    assert_same_instant,
    assert_segment_state,
    assert_total_count,
    assert_version_bumped_by,
    assert_version_unchanged,
)
from test_helpers.constants import (
    CLOCK_DEFAULT,
    LEAD_CERT_EXPIRES,
    SECOND_LEAD_EMAIL,
    SECOND_LEAD_NAME,
)
from test_helpers.factories import (
    assessor_payload,
    change_log_payload,
    document_evidence,
    engagement_payload,
    system_component_payload,
)
from test_helpers.fixtures import (
    build_registry,
    declare_segment,
    open_engagement,
    open_requirement,
    read_engagement,
    register_assessor,
    set_clock,
    start_testing,
)
from test_helpers.test_users import (
    admin_headers,
    client_rep_headers,
    make_assessor_headers,
    make_lead_headers,
    make_qa_reviewer_headers,
)

LATER_INSTANT = "2026-09-05T00:00:00Z"
# A scoping engagement with no sample and no accepted worksheet: 160 hours at
# 250.00 with the level-one onsite surcharge and no volume tier.
ZERO_SAMPLE_FEE = 43200.00


def _without(payload: Dict[str, Any], field: str) -> Dict[str, Any]:
    """Drop one declared input so the request arrives incomplete."""
    stripped = dict(payload)
    stripped.pop(field, None)
    return stripped


class TestAssessorRegistryDefaults:
    """A freshly registered assessor carries the defaults the firm declared."""

    def test_registering_an_assessor_applies_the_declared_defaults(self, api):
        """The three captured inputs are enough, and the rest defaults.

        PRD: An optional `qa_qualified` flag records whether the firm has
        authorised this individual to perform internal quality-assurance review;
        when the flag is omitted it defaults to false, which means a freshly
        registered assessor cannot be nominated as a reviewer until somebody
        amends the record.

        Design: Corner/entities/entity_assessor_creation_returns_201_with_declared_defaults
        """
        response = api.create_assessor(
            assessor_payload(
                full_name="Dana Reyes",
                email="dana.reyes@qsa.example",
                certification_expires_at=LEAD_CERT_EXPIRES,
            ),
            admin_headers(),
        )

        assessor = assert_created(response)
        assert_object_envelope(response)
        assert assessor["full_name"] == "Dana Reyes"
        assert assessor["email"] == "dana.reyes@qsa.example"
        assert_same_instant(assessor["certification_expires_at"], LEAD_CERT_EXPIRES)
        # The flag was never supplied, so the registry withholds review duty.
        assert assessor["qa_qualified"] is False
        assert assessor["status"] == "ACTIVE"
        # The clock stands well before the certificate's expiry instant.
        assert assessor["certification_status"] == "ACTIVE"
        assert assessor["lead_engagement_count"] == 0
        assert_common_fields(assessor)
        assert assessor["version"] == 1
        assert_bare_uuid(assessor["id"])


class TestEngagementReadSurface:
    """A single engagement read carries its stored inputs and every roll-up."""

    def test_reading_a_scoping_engagement_returns_stored_and_derived_fields(
        self, api, scoping_engagement
    ):
        """Nothing is withheld: the zero-state ledgers and the fee are all present.

        PRD: A new engagement starts in `status` `SCOPING` with `posture` `OPEN`,
        `scope_locked` false, `attested_at` null, `reassessment_due_date` null and
        `next_assessment_start_date` null.

        Design: Corner/entities/entity_engagement_retrieval_returns_stored_and_derived_fields
        """
        engagement_id = scoping_engagement["engagement_id"]

        engagement = assert_ok(api.get_engagement(engagement_id, client_rep_headers()))

        assert engagement["client_legal_name"] == "Northwind Retail Inc"
        assert engagement["merchant_level"] == "L1"
        assert engagement["assessment_year"] == 2026
        assert engagement["acquirer_name"] == "First Coast Bank"
        assert engagement["fieldwork_start_date"] == "2026-08-10"
        assert engagement["fieldwork_end_date"] == "2026-08-28"
        assert engagement["lead_assessor_id"] == scoping_engagement["lead_id"]
        assert engagement["qa_reviewer_id"] == scoping_engagement["qa_id"]
        assert engagement["status"] == "SCOPING"
        assert engagement["posture"] == "OPEN"
        assert engagement["scope_locked"] is False
        assert engagement["attested_at"] is None
        assert engagement["reassessment_due_date"] is None
        assert engagement["next_assessment_start_date"] is None
        assert engagement["cde_component_count"] == 0
        assert engagement["connected_component_count"] == 0
        assert engagement["out_of_scope_component_count"] == 0
        assert engagement["in_scope_component_count"] == 0
        assert engagement["unvalidated_segment_count"] == 0
        assert engagement["open_gap_count"] == 0
        assert engagement["accepted_ccw_count"] == 0
        assert engagement["applicable_requirement_count"] == 0
        # The fee is priced against a sample that does not yet exist.
        assert engagement["estimated_hours"] == 160
        assert_money(engagement["assessment_fee_total"], ZERO_SAMPLE_FEE)
        assert engagement["quarterly_scan_compliant"] is False
        assert engagement["active_sampling_plan_id"] is None
        assert engagement["version"] == 1

    def test_an_unknown_engagement_identifier_answers_the_engagement_code(self, api):
        """A well-formed identifier nobody minted still names its own collection.

        PRD: Each identifier in the URL path is resolved left to right, and the
        first unresolved one answers with that entity's own 404 code:
        `ERR_ASSESSOR_NOT_FOUND`, `ERR_ASV_VENDOR_NOT_FOUND`,
        `ERR_ENGAGEMENT_NOT_FOUND`, `ERR_SEGMENT_NOT_FOUND`,
        `ERR_COMPONENT_NOT_FOUND`, `ERR_SAMPLING_PLAN_NOT_FOUND`,
        `ERR_REQUIREMENT_NOT_FOUND`, `ERR_EVIDENCE_NOT_FOUND`, `ERR_CCW_NOT_FOUND`,
        `ERR_REMEDIATION_ITEM_NOT_FOUND`, `ERR_ROC_NOT_FOUND`,
        `ERR_SCAN_CYCLE_NOT_FOUND`, `ERR_SCAN_FINDING_NOT_FOUND` or
        `ERR_CHANGE_LOG_ENTRY_NOT_FOUND`.

        Design: Corner/entities/entity_engagement_get_with_unknown_uuid_returns_engagement_not_found
        """
        response = api.get_engagement(NON_EXISTENT_UUID, admin_headers())

        validate_error(response, ERR_ENGAGEMENT_NOT_FOUND, 404)
        assert_error_envelope(response, ERR_ENGAGEMENT_NOT_FOUND)
        # The failed lookup persisted nothing.
        assert_total_count(api.list_engagements(admin_headers()), 0)


class TestSystemComponentListing:
    """A page window never changes what the filtered population counts."""

    def test_component_pages_report_the_filtered_population_not_the_page(
        self, api, validated_cde_engagement
    ):
        """Two pages of two cover three hosts, and a filter narrows the count.

        PRD: Four pagination fields appear in the `meta` object of every list
        response: `limit` and `offset` echo the effective values actually applied,
        `total_count` reports the number of rows matching the filters before the
        page window is taken, and `has_more` is true exactly when rows remain
        beyond the current window.

        Design: Corner/entities/entity_system_component_listing_paginates_with_total_count_and_has_more
        """
        engagement_id = validated_cde_engagement["engagement_id"]
        staff_headers = make_assessor_headers(validated_cde_engagement["lead_id"])

        first = api.list_system_components(
            staff_headers, {"engagement_id": engagement_id, "limit": 2, "offset": 0}
        )
        first_rows = assert_pagination_meta(
            first,
            expected_total=3,
            expected_limit=2,
            expected_offset=0,
            expected_has_more=True,
        )
        assert len(first_rows) == 2
        assert first.json()["response_type"] == "array"

        second = api.list_system_components(
            staff_headers, {"engagement_id": engagement_id, "limit": 2, "offset": 2}
        )
        second_rows = assert_pagination_meta(
            second,
            expected_total=3,
            expected_limit=2,
            expected_offset=2,
            expected_has_more=False,
        )
        assert len(second_rows) == 1

        # No host is repeated or dropped at the page boundary.
        hostnames = sorted(row["hostname"] for row in first_rows + second_rows)
        assert hostnames == ["app-01", "pay-01", "pay-02"]

        filtered = api.list_system_components(
            staff_headers,
            {"engagement_id": engagement_id, "component_type": "APPLICATION"},
        )
        filtered_rows = assert_pagination_meta(filtered, expected_total=2)
        assert sorted(row["hostname"] for row in filtered_rows) == ["pay-01", "pay-02"]

        for row in first_rows + second_rows:
            assert row["scope_class"] == "CDE"
            # No plan has been drawn over this inventory yet, so nothing is
            # selected; the stratum still mirrors the type because a CDE host is
            # part of the eligible population.
            assert row["in_sample"] is False
            assert row["sampling_stratum"] == row["component_type"]
            assert_common_fields(row)


class TestEngagementCreationRequestShape:
    """A missing declared input is refused before any named person is resolved."""

    def test_commissioning_without_an_acquirer_name_is_malformed(self, api, registry):
        """The bank that receives the attestation may not be left out.

        PRD: Every required input must be present; enum inputs must fall inside
        their declared domain; numbers must be of the declared type and sign;
        `fieldwork_end_date` must not be earlier than `fieldwork_start_date`;
        `monitoring_interval_days` must be at least 1; `cvss_score` must lie
        between 0.0 and 10.0 inclusive; `control_refs` must be a non-empty array of
        strings; `limit` must lie between 1 and 100 inclusive and `offset` must not
        be negative.

        Design: Corner/entities/entity_engagement_create_missing_acquirer_name_returns_invalid_request
        """
        payload = _without(
            engagement_payload(
                lead_assessor_id=registry["lead_id"],
                qa_reviewer_id=registry["qa_id"],
            ),
            "acquirer_name",
        )

        response = api.create_engagement(
            payload, make_lead_headers(registry["lead_id"])
        )

        validate_error(response, ERR_INVALID_REQUEST, 400)
        assert_error_envelope(response, ERR_INVALID_REQUEST)
        assert_total_count(api.list_engagements(admin_headers()), 0)

        # The named lead was never charged with an engagement.
        lead = assert_ok(api.get_assessor(registry["lead_id"], admin_headers()))
        assert lead["lead_engagement_count"] == 0
        assert lead["version"] == 1


class TestChangeLogEntryFacts:
    """An in-year change is an append-only fact with a derived trigger flag."""

    def test_an_organisational_change_records_with_no_component_link(
        self, api, scoping_engagement
    ):
        """A staffing change names no host and moves no reassessment counter.

        PRD: Recording an in-year change is open to the lead, a staff assessor and
        the client's representative, and carries a `change_type` of
        `COMPONENT_ADDED_TO_CDE`, `SEGMENT_RECLASSIFIED`, `THIRD_PARTY_ADDED`,
        `APPLICATION_UPDATED` or `STAFF_CHANGE`; a non-empty `description`
        narrating what changed; the client's own `affects_scope` assertion of
        whether the change touches the cardholder data environment; and an optional
        `component_id` naming the component concerned, which must belong to the
        same engagement and is left null for purely organisational changes.

        Design: Corner/entities/entity_change_log_entry_component_id_defaults_to_null
        """
        engagement_id = scoping_engagement["engagement_id"]

        entry = assert_created(
            api.create_change_log_entry(
                engagement_id,
                change_log_payload(
                    change_type="STAFF_CHANGE",
                    description="The client replaced its security officer.",
                    affects_scope=True,
                ),
                client_rep_headers(),
            )
        )

        assert entry["component_id"] is None
        assert entry["change_type"] == "STAFF_CHANGE"
        assert entry["affects_scope"] is True
        # A staffing change is outside the triggering set whatever the client asserts.
        assert entry["triggers_reassessment"] is False
        assert entry["engagement_id"] == engagement_id
        assert_historical_fields(entry)

        engagement = read_engagement(
            api, engagement_id, scoping_engagement["lead_id"]
        )
        assert engagement["scope_affecting_change_count"] == 0
        assert engagement["reassessment_required"] is False

    def test_recorded_at_is_stamped_from_the_logical_clock(
        self, api, scoping_engagement
    ):
        """Moving the clock forward re-dates only the entry written afterwards.

        PRD: Timestamps the server stamps onto rows — `collected_at`,
        `recorded_at`, `last_validated_at`, `decided_at`, `closed_at`,
        `superseded_at`, `scan_completed_at` and `attested_at` — are all taken from
        the logical clock, never from wall-clock time.

        Design: Corner/entities/entity_change_log_entry_recorded_at_comes_from_the_logical_clock
        """
        engagement_id = scoping_engagement["engagement_id"]
        lead_headers = make_lead_headers(scoping_engagement["lead_id"])

        early = assert_created(
            api.create_change_log_entry(
                engagement_id,
                change_log_payload(
                    change_type="APPLICATION_UPDATED",
                    description="Payment application patched to 4.2.1.",
                    affects_scope=False,
                ),
                lead_headers,
            )
        )
        assert_same_instant(early["recorded_at"], CLOCK_DEFAULT)

        moved = set_clock(api, LATER_INSTANT)
        assert_same_instant(moved["current_utc"], LATER_INSTANT)

        late = assert_created(
            api.create_change_log_entry(
                engagement_id,
                change_log_payload(
                    change_type="THIRD_PARTY_ADDED",
                    description=(
                        "A new managed hosting provider took over the DC-EAST cage."
                    ),
                    affects_scope=True,
                ),
                lead_headers,
            )
        )
        assert_same_instant(late["recorded_at"], LATER_INSTANT)
        assert_same_instant(late["created_at"], LATER_INSTANT)
        assert late["triggers_reassessment"] is True

        # The earlier fact keeps the instant it was written at.
        held = assert_ok(api.get_change_log_entry(early["id"], lead_headers))
        assert_same_instant(held["recorded_at"], CLOCK_DEFAULT)
        assert held["triggers_reassessment"] is False

        engagement = read_engagement(
            api, engagement_id, scoping_engagement["lead_id"]
        )
        # One triggering entry is short of the inclusive threshold of three.
        assert engagement["scope_affecting_change_count"] == 1
        assert engagement["reassessment_required"] is False
        assert engagement["reassessment_due_date"] is None


class TestEvidenceItemIsAppendOnly:
    """An evidence record is a historical fact with no revision counter."""

    def test_an_evidence_record_carries_no_version_and_no_updated_at(
        self, api, fieldwork_engagement
    ):
        """The artefact is stamped with its collector and never revised.

        PRD: Evidence records are historical facts: they carry `id` and
        `created_at` only, and are never edited, so neither `updated_at` nor
        `version` exists on them.

        Design: Corner/entities/entity_evidence_item_is_immutable_with_no_version_and_no_update_endpoint
        """
        engagement_id = fieldwork_engagement["engagement_id"]
        lead_id = fieldwork_engagement["lead_id"]
        lead_headers = make_lead_headers(lead_id)
        requirement = open_requirement(
            api,
            engagement_id,
            lead_id,
            requirement_ref="1.2.1",
            requirement_family="R1",
            testing_procedure_count=3,
        )
        start_testing(api, requirement["id"], lead_id)

        item = assert_created(
            api.create_evidence_item(
                requirement["id"],
                document_evidence("1.2.1.a"),
                lead_headers,
            )
        )

        assert_historical_fields(item)
        # The collecting caller is stamped from the acting identity header.
        assert item["collector_assessor_id"] == lead_id
        assert_same_instant(item["collected_at"], CLOCK_DEFAULT)
        assert item["requirement_assessment_id"] == requirement["id"]
        assert item["engagement_id"] == engagement_id
        # A document review needs no observed host.
        assert item["component_id"] is None

        read_back = assert_ok(
            api.get_evidence_item(
                item["id"], make_qa_reviewer_headers(fieldwork_engagement["qa_id"])
            )
        )
        assert_historical_fields(read_back)
        assert read_back["id"] == item["id"]

        parent = assert_ok(
            api.get_requirement_assessment(requirement["id"], lead_headers)
        )
        assert parent["evidence_item_count"] == 1
        assert parent["evidence_type_coverage"] == ["DOCUMENT_REVIEW"]
        assert parent["evidence_completeness"] is False


class TestComponentInventoryReferences:
    """A host is refused when its type or its zone does not belong."""

    def test_a_component_type_outside_the_declared_domain_is_malformed(
        self, api, scoping_engagement
    ):
        """A plausible-sounding stratum the methodology never declared is refused.

        PRD: Each component is recorded with a `hostname` that must be unique
        within the engagement — a repeat is refused with `ERR_DUPLICATE_HOSTNAME` —
        a `component_type` naming the sampling stratum it belongs to (`SERVER`,
        `NETWORK_DEVICE`, `POS_TERMINAL`, `APPLICATION` or `DATABASE`), a
        `function_class` naming its functional role for requirement mapping
        (`PAYMENT_APPLICATION`, `DATA_STORE`, `SECURITY_SERVICE`,
        `CONNECTED_SUPPORT` or `SEGMENTATION_CONTROL`), a boolean `stores_chd`
        asserting whether the component stores cardholder data, a `facility_name`
        grouping it with everything else at the same physical location, a
        `facility_type` categorising that location (`DATA_CENTER`, `CALL_CENTER`,
        `RETAIL_STORE` or `OFFICE`) and a `segment_id` placing it in one of the
        engagement's declared zones.

        Design: Corner/entities/entity_component_invalid_component_type_enum_returns_invalid_request
        """
        engagement_id = scoping_engagement["engagement_id"]
        lead_id = scoping_engagement["lead_id"]
        lead_headers = make_lead_headers(lead_id)
        segment = declare_segment(
            api, engagement_id, lead_id, "CDE-CORE", segment_class="CDE"
        )

        response = api.create_system_component(
            engagement_id,
            system_component_payload(
                segment_id=segment["id"],
                hostname="fw-01",
                component_type="FIREWALL",
                function_class="SECURITY_SERVICE",
            ),
            lead_headers,
        )

        validate_error(response, ERR_INVALID_REQUEST, 400)
        assert_error_envelope(response, ERR_INVALID_REQUEST)
        assert_total_count(
            api.list_system_components(
                lead_headers, {"engagement_id": engagement_id}
            ),
            0,
        )

        engagement = read_engagement(api, engagement_id, lead_id)
        assert engagement["cde_component_count"] == 0
        # A refused inventory write re-prices nothing.
        assert_money(engagement["assessment_fee_total"], ZERO_SAMPLE_FEE)

    def test_a_zone_from_another_engagement_cannot_hold_a_component(self, api):
        """The zone resolves, but it belongs to somebody else's assessment.

        PRD: The zone must belong to the same engagement, or the request answers
        `ERR_CROSS_ENGAGEMENT_REFERENCE`.

        Design: Corner/entities/entity_component_segment_from_another_engagement_returns_cross_engagement_reference
        """
        scenario = build_registry(api)
        first_lead_id = scenario["lead_id"]
        second_lead = register_assessor(
            api, SECOND_LEAD_NAME, SECOND_LEAD_EMAIL, LEAD_CERT_EXPIRES
        )
        first = open_engagement(
            api, first_lead_id, qa_reviewer_id=scenario["qa_id"]
        )
        second = open_engagement(
            api,
            second_lead["id"],
            qa_reviewer_id=scenario["qa_id"],
            client_legal_name="Harbor Fuel Stops LLC",
            acquirer_name="Second Harbor Bank",
        )
        other_zone = declare_segment(
            api, second["id"], second_lead["id"], "OTHER-CDE", segment_class="CDE"
        )

        response = api.create_system_component(
            first["id"],
            system_component_payload(
                segment_id=other_zone["id"],
                hostname="app-01",
                component_type="SERVER",
            ),
            make_lead_headers(first_lead_id),
        )

        validate_error(response, ERR_CROSS_ENGAGEMENT_REFERENCE, 422)
        assert_error_envelope(response, ERR_CROSS_ENGAGEMENT_REFERENCE)
        for engagement_id, lead_id in (
            (first["id"], first_lead_id),
            (second["id"], second_lead["id"]),
        ):
            assert_total_count(
                api.list_system_components(
                    make_lead_headers(lead_id), {"engagement_id": engagement_id}
                ),
                0,
            )

        held = assert_ok(
            api.get_network_segment(
                other_zone["id"], make_lead_headers(second_lead["id"])
            )
        )
        assert held["engagement_id"] == second["id"]
        assert_version_unchanged(other_zone["version"], held["version"])


class TestSegmentForestIntegrity:
    """Re-parenting walks the proposed parent's chain before it moves anything."""

    def test_reparenting_a_zone_beneath_its_own_child_closes_a_loop(
        self, api, scoping_engagement
    ):
        """The loop is refused while an unrelated root is accepted.

        PRD: When a zone is re-parented, the server walks upward from the *proposed
        parent* through `parent_segment_id` links; if that walk ever reaches the
        zone being re-parented, the request is refused with `ERR_SEGMENT_CYCLE`
        (HTTP 422).

        Design: Corner/entities/entity_segment_reparent_into_own_subtree_returns_segment_cycle
        """
        engagement_id = scoping_engagement["engagement_id"]
        lead_id = scoping_engagement["lead_id"]
        lead_headers = make_lead_headers(lead_id)
        zone_a = declare_segment(
            api, engagement_id, lead_id, "ZONE-A", segment_class="CDE"
        )
        zone_b = declare_segment(
            api,
            engagement_id,
            lead_id,
            "ZONE-B",
            segment_class="CONNECTED",
            parent_segment_id=zone_a["id"],
        )
        zone_c = declare_segment(
            api, engagement_id, lead_id, "ZONE-C", segment_class="CONNECTED"
        )

        refused = api.update_network_segment(
            zone_a["id"], {"parent_segment_id": zone_b["id"]}, lead_headers
        )
        validate_error(refused, ERR_SEGMENT_CYCLE, 422)
        assert_error_envelope(refused, ERR_SEGMENT_CYCLE)

        held = assert_ok(api.get_network_segment(zone_a["id"], lead_headers))
        assert held["parent_segment_id"] is None
        assert_version_unchanged(zone_a["version"], held["version"])
        before = read_engagement(api, engagement_id, lead_id)
        assert before["unvalidated_segment_count"] == 3
        assert before["posture"] == "RESTRICTED"

        # An unrelated root is a legitimate new parent: the walk never reaches A.
        moved = assert_ok(
            api.update_network_segment(
                zone_a["id"], {"parent_segment_id": zone_c["id"]}, lead_headers
            )
        )
        assert moved["parent_segment_id"] == zone_c["id"]
        assert_version_bumped_by(zone_a["version"], moved["version"])

        child = assert_ok(api.get_network_segment(zone_b["id"], lead_headers))
        assert child["parent_segment_id"] == zone_a["id"]
        for zone, segment_class in (
            (zone_a, "CDE"),
            (zone_b, "CONNECTED"),
            (zone_c, "CONNECTED"),
        ):
            row = assert_ok(api.get_network_segment(zone["id"], lead_headers))
            assert_segment_state(
                row,
                segmentation_status="DECLARED",
                segment_class=segment_class,
                effective_class=segment_class,
            )

        after = read_engagement(api, engagement_id, lead_id)
        assert after["cde_component_count"] == 0
        assert after["unvalidated_segment_count"] == 3
        assert after["posture"] == "RESTRICTED"
