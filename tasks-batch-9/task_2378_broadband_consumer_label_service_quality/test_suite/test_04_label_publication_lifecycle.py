"""Label publication lifecycle: the two independent label dimensions, the
publication preconditions, the disclosure-posture ladder position, and the
half-open geometry of a plan's display timeline.
"""

from datetime import datetime
from typing import Any, Dict, List

import pytest
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import ApiClient, ApiErrorId
from test_helpers.assertions import (
    assert_evidence_sample_total,
    assert_label_dimensions,
    assert_optional_timestamp_absent,
    assert_pinned_typical_figures,
    assert_posture,
)
from test_helpers.constants import (
    PEAK_HOUR_MEDIAN_TYPICAL_DOWNLOAD,
    PEAK_HOUR_MEDIAN_TYPICAL_LATENCY,
    PEAK_HOUR_MEDIAN_TYPICAL_UPLOAD,
    REFERENCE_NOW,
)
from test_helpers.factories import (
    build_attestation_payload,
    build_disclosure_payload,
    build_invalidate_run_payload,
    build_label_version_payload,
    build_test_run_payload,
)
from test_helpers.fixtures import (
    ReferenceEnvironment,
    add_verified_translation,
    create_measured_plan,
    current_plan_version,
    draft_label,
    invalidate_test_run,
    read_label,
    read_service_plan,
    read_subscriber_account,
    set_clock,
)
from test_helpers.test_users import (
    COMPLIANCE_OFFICER_2_HEADERS,
    COMPLIANCE_OFFICER_2_USER_ID,
    COMPLIANCE_OFFICER_HEADERS,
    NETWORK_ENGINEER_HEADERS,
    RETAIL_AGENT_HEADERS,
)
from test_helpers.types import (
    AccessibilityConformance,
    AccessibleFormat,
    AttestationStatus,
    DisclosureChannel,
    LabelPosture,
    MetricVariant,
    PublicationState,
    SubstantiationStatus,
)

# The reason the invalidation cascade records on an attestation whose pinned
# minimum can no longer be met from the plan's remaining evidence pool.
EVIDENCE_BELOW_MINIMUM = "EVIDENCE_BELOW_MINIMUM"

# A replacement measurement window recorded after the August window has been
# withdrawn: the same six observations shifted eight days forward, four of them
# still inside the 19:00-23:00 UTC peak band.
REPLACEMENT_WINDOW_START = "2026-08-11T00:00:00Z"
REPLACEMENT_WINDOW_END = "2026-08-17T23:00:00Z"
REPLACEMENT_SAMPLES: List[Dict[str, Any]] = [
    {
        "observed_at": "2026-08-11T19:10:00Z",
        "download_mbps": 210,
        "upload_mbps": 100,
        "latency_ms": 42,
    },
    {
        "observed_at": "2026-08-12T21:30:00Z",
        "download_mbps": 238,
        "upload_mbps": 112,
        "latency_ms": 24,
    },
    {
        "observed_at": "2026-08-13T20:40:00Z",
        "download_mbps": 242,
        "upload_mbps": 118,
        "latency_ms": 22,
    },
    {
        "observed_at": "2026-08-16T19:45:00Z",
        "download_mbps": 290,
        "upload_mbps": 130,
        "latency_ms": 18,
    },
    {
        "observed_at": "2026-08-13T14:30:00Z",
        "download_mbps": 295,
        "upload_mbps": 145,
        "latency_ms": 14,
    },
    {
        "observed_at": "2026-08-14T02:40:00Z",
        "download_mbps": 306,
        "upload_mbps": 155,
        "latency_ms": 55,
    },
]

REFERENCE_SAMPLE_TOTAL = 6
REFERENCE_METHODOLOGY_URL = "https://isp.example/methodology/v1.0"

# The draft display windows used by the geometry scenarios.
DRAFT_ONE_FROM = "2026-10-01T00:00:00Z"
DRAFT_ONE_UNTIL = "2026-11-01T00:00:00Z"
STRADDLING_FROM = "2026-10-31T00:00:00Z"


# ---------------------------------------------------------------------------
# Local setup chains unique to this file
# ---------------------------------------------------------------------------


def _instant(value: str) -> datetime:
    """Parse an ISO-8601 UTC instant so two spellings of the same moment compare
    equal regardless of how many fractional digits the server echoes."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _record_replacement_run(api: ApiClient, env: ReferenceEnvironment) -> Dict[str, Any]:
    """Record the replacement measurement window against the reference plan."""
    payload = build_test_run_payload(
        env.probe_id,
        env.plan_id,
        env.methodology_id,
        window_start=REPLACEMENT_WINDOW_START,
        window_end=REPLACEMENT_WINDOW_END,
        samples=REPLACEMENT_SAMPLES,
    )
    return validate_success(api.create_test_run(payload, NETWORK_ENGINEER_HEADERS), 201)


def _draft_attestation(api: ApiClient, env: ReferenceEnvironment) -> Dict[str, Any]:
    """Compute a fresh peak-hour attestation over the plan's current evidence."""
    payload = build_attestation_payload(
        env.plan_id,
        env.methodology_id,
        current_plan_version(env.plan_id),
        metric_variant=MetricVariant.PEAK_HOUR_MEDIAN.value,
    )
    return validate_success(
        api.create_performance_attestation(payload, NETWORK_ENGINEER_HEADERS), 201
    )


def _label_awaiting_certified_attestation() -> Dict[str, Any]:
    """A drafted, fully translated label on a plan whose only attestation is
    still `DRAFT`, so every publication precondition except the attestation one
    is satisfied.
    """
    set_clock(REFERENCE_NOW)
    measured = create_measured_plan(certify=False)
    label = draft_label(
        measured["plan"]["id"],
        effective_from=REFERENCE_NOW,
        accessibility_conformance=AccessibilityConformance.WCAG_AA.value,
    )
    add_verified_translation(label["id"], locale="en-US")
    measured["label"] = read_label(label["id"])
    return measured


def _plan_label_rows(api: ApiClient, plan_id: str) -> List[Dict[str, Any]]:
    rows, _meta = validate_paginated(
        api.list_label_versions(COMPLIANCE_OFFICER_HEADERS, params={"plan_id": plan_id})
    )
    return rows


# ---------------------------------------------------------------------------
# The two label dimensions move independently on one record
# ---------------------------------------------------------------------------


class TestLabelDimensionsMoveIndependently:
    def test_invalidating_the_evidence_leaves_the_published_dimension_untouched(
        self, api: ApiClient, reference_environment: ReferenceEnvironment
    ):
        """Losing the evidence unsubstantiates the label without unpublishing it.

        PRD: "Every label whose `attestation_id` names one of the attestations
        just revoked and whose `publication_state` is `PUBLISHED` has its
        `substantiation_status` set to `UNSUBSTANTIATED`."

        Design: Difficulty/non_linear_state_machine/label_publication_and_substantiation_dimensions_move_independently
        """
        env = reference_environment
        assert_label_dimensions(
            env.reload_label(),
            PublicationState.PUBLISHED.value,
            SubstantiationStatus.SUBSTANTIATED.value,
        )
        assert_posture(env.reload_plan(), LabelPosture.OPEN.value)

        response = api.invalidate_test_run(
            env.run_id,
            build_invalidate_run_payload(
                reason="Probe firmware defect invalidates the August window"
            ),
            NETWORK_ENGINEER_HEADERS,
        )
        validate_success(response)

        attestation = env.reload_attestation()
        assert attestation["status"] == AttestationStatus.REVOKED.value, (
            "the pinned attestation must be revoked once the plan's evidence pool "
            f"falls below its minimum, got {attestation['status']}"
        )
        assert attestation["revoked_reason"] == EVIDENCE_BELOW_MINIMUM, (
            f"revoked_reason: expected {EVIDENCE_BELOW_MINIMUM}, "
            f"got {attestation['revoked_reason']}"
        )

        label = env.reload_label()
        assert_label_dimensions(
            label,
            PublicationState.PUBLISHED.value,
            SubstantiationStatus.UNSUBSTANTIATED.value,
        )
        assert_optional_timestamp_absent(label, "withdrawn_at")
        assert_optional_timestamp_absent(label, "archived_at")

        plan = env.reload_plan()
        assert_posture(plan, LabelPosture.FROZEN.value)
        assert_evidence_sample_total(plan, 0)

    def test_recertifying_replacement_evidence_resubstantiates_the_same_label_row(
        self, api: ApiClient, reference_environment: ReferenceEnvironment
    ):
        """The evidence dimension returns to SUBSTANTIATED on the very same row.

        PRD: "When the plan has a published label whose `substantiation_status`
        is `UNSUBSTANTIATED`, certifying a replacement attestation for that same
        plan re-pins the label's `attestation_id` to the newly certified
        attestation, refreshes the label's pinned `typical_download_mbps`,
        `typical_upload_mbps`, `typical_latency_ms` and
        `methodology_url_snapshot` from it, and moves the label's
        `substantiation_status` from `UNSUBSTANTIATED` back to `SUBSTANTIATED`
        without touching its `publication_state`."

        Design: Difficulty/non_linear_state_machine/label_publication_and_substantiation_dimensions_move_independently
        """
        env = reference_environment
        original_version_seq = env.reload_label()["version_seq"]

        invalidate_test_run(
            env.run_id, reason="Probe firmware defect invalidates the August window"
        )
        assert_label_dimensions(
            env.reload_label(),
            PublicationState.PUBLISHED.value,
            SubstantiationStatus.UNSUBSTANTIATED.value,
        )

        _record_replacement_run(api, env)
        replacement = _draft_attestation(api, env)

        response = api.certify_performance_attestation(
            replacement["id"], COMPLIANCE_OFFICER_HEADERS
        )
        certified = validate_success(response)
        assert certified["status"] == AttestationStatus.CERTIFIED.value

        label = env.reload_label()
        assert_label_dimensions(
            label,
            PublicationState.PUBLISHED.value,
            SubstantiationStatus.SUBSTANTIATED.value,
        )
        assert label["attestation_id"] == replacement["id"], (
            "the label must be re-pinned to the replacement attestation"
        )
        assert_pinned_typical_figures(
            label,
            PEAK_HOUR_MEDIAN_TYPICAL_DOWNLOAD,
            PEAK_HOUR_MEDIAN_TYPICAL_UPLOAD,
            PEAK_HOUR_MEDIAN_TYPICAL_LATENCY,
        )
        assert label["version_seq"] == original_version_seq, (
            "re-substantiation must not create a new label row"
        )

        plan = env.reload_plan()
        assert_posture(plan, LabelPosture.OPEN.value)
        assert_evidence_sample_total(plan, REFERENCE_SAMPLE_TOTAL)


# ---------------------------------------------------------------------------
# Disclosure posture outranks translation availability
# ---------------------------------------------------------------------------


class TestFrozenPostureOutranksTranslationAvailability:
    def test_unavailable_locale_is_the_complaint_while_the_plan_is_open(
        self, api: ApiClient, reference_environment: ReferenceEnvironment
    ):
        """While the plan is OPEN the referential complaint is the one that surfaces.

        PRD: "Then translation availability: the requested `locale` must have a
        translation on the selected label whose `status` is `VERIFIED`, or the
        request answers `ERR_TRANSLATION_NOT_AVAILABLE`."

        Design: Difficulty/priority_pair_validation_conflict/plan_posture_frozen_outranks_translation_not_available
        """
        env = reference_environment
        assert_posture(env.reload_plan(), LabelPosture.OPEN.value)

        response = api.record_label_disclosure(
            env.account_id,
            build_disclosure_payload(
                channel=DisclosureChannel.ACCOUNT_PORTAL.value,
                locale="es-MX",
                accessible_format=AccessibleFormat.STANDARD_WEB.value,
            ),
            RETAIL_AGENT_HEADERS,
        )
        validate_error(response, ApiErrorId.ERR_TRANSLATION_NOT_AVAILABLE.value)

        assert_posture(read_service_plan(env.plan_id), LabelPosture.OPEN.value)

    @pytest.mark.parametrize("locale", ["es-MX", "en-US"])
    def test_frozen_posture_masks_the_translation_complaint(
        self, api: ApiClient, reference_environment: ReferenceEnvironment, locale: str
    ):
        """A frozen plan refuses the disclosure on safety grounds either way.

        PRD: "A frozen posture surfaces as `ERR_PLAN_POSTURE_FROZEN` rather than
        being masked by the accessibility or translation checks that come later,
        and a stale `expected_plan_version` surfaces as `ERR_STALE_PLAN_VERSION`
        rather than as an interval-geometry conflict, even when the request would
        also have overlapped a sibling draft window."

        Design: Difficulty/priority_pair_validation_conflict/plan_posture_frozen_outranks_translation_not_available
        """
        env = reference_environment
        invalidate_test_run(
            env.run_id, reason="Probe firmware defect invalidates the August window"
        )
        assert_posture(env.reload_plan(), LabelPosture.FROZEN.value)

        response = api.record_label_disclosure(
            env.account_id,
            build_disclosure_payload(
                channel=DisclosureChannel.ACCOUNT_PORTAL.value,
                locale=locale,
                accessible_format=AccessibleFormat.STANDARD_WEB.value,
            ),
            RETAIL_AGENT_HEADERS,
        )
        validate_error(response, ApiErrorId.ERR_PLAN_POSTURE_FROZEN.value)

        rows, _meta = validate_paginated(
            api.list_account_label_disclosures(env.account_id, RETAIL_AGENT_HEADERS)
        )
        assert rows == [], (
            "a rejected disclosure must not leave a partial LabelDisclosure row"
        )
        account = read_subscriber_account(env.account_id)
        assert account["last_disclosed_label_version_id"] is None, (
            "last_disclosed_label_version_id must stay null while every disclosure "
            "attempt is refused"
        )


# ---------------------------------------------------------------------------
# Publication is gated on a sibling evidence entity
# ---------------------------------------------------------------------------


class TestPublicationRequiresCertifiedAttestation:
    def test_publish_is_refused_while_the_sibling_attestation_is_still_draft(
        self, api: ApiClient
    ):
        """A label cannot go live on evidence nobody has certified.

        PRD: "Then the referential prerequisites, in this order: the plan must
        have an attestation whose `status` is `CERTIFIED`, or
        `ERR_ATTESTATION_NOT_CERTIFIED`; every locale in the plan's
        `required_locales` must have a translation on this label whose `status`
        is `VERIFIED`, or `ERR_TRANSLATION_COVERAGE_INCOMPLETE`; and every fee
        line of the plan whose `label_category` is `MONTHLY_RECURRING` must
        appear in the label's `fee_itemization` for at least one phase, or
        `ERR_FEE_ITEMIZATION_INCOMPLETE`."

        Design: Difficulty/cross_entity_state_dependency/label_publication_requires_certified_attestation
        """
        measured = _label_awaiting_certified_attestation()
        assert measured["attestation"]["status"] == AttestationStatus.DRAFT.value, (
            "the scenario needs the sibling attestation to be uncertified"
        )

        response = api.publish_label_version(
            measured["label"]["id"], COMPLIANCE_OFFICER_2_HEADERS
        )
        validate_error(response, ApiErrorId.ERR_ATTESTATION_NOT_CERTIFIED.value)

        label = read_label(measured["label"]["id"])
        assert_label_dimensions(
            label,
            PublicationState.DRAFT.value,
            SubstantiationStatus.PENDING_EVIDENCE.value,
        )
        assert label["attestation_id"] is None, "a refused publish pins nothing"
        assert_optional_timestamp_absent(label, "published_at")

        plan = read_service_plan(measured["plan"]["id"])
        assert plan["active_label_version_id"] is None, (
            "the plan must still have no published label"
        )
        assert_posture(plan, LabelPosture.RESTRICTED.value)

    def test_publish_succeeds_once_certified_and_reaches_into_the_sibling(
        self, api: ApiClient
    ):
        """The publish that finally lands copies the sibling's pinned figures.

        PRD: "It copies `typical_download_mbps`, `typical_upload_mbps`,
        `typical_latency_ms` and `methodology_url_snapshot` from that attestation
        onto the label, so those three previously null figures become non-null
        and the printed claim is frozen against later measurement changes."

        Design: Difficulty/cross_entity_state_dependency/label_publication_requires_certified_attestation
        """
        measured = _label_awaiting_certified_attestation()
        attestation_id = measured["attestation"]["id"]

        refused = api.publish_label_version(
            measured["label"]["id"], COMPLIANCE_OFFICER_2_HEADERS
        )
        validate_error(refused, ApiErrorId.ERR_ATTESTATION_NOT_CERTIFIED.value)

        certified = validate_success(
            api.certify_performance_attestation(attestation_id, COMPLIANCE_OFFICER_HEADERS)
        )
        assert certified["status"] == AttestationStatus.CERTIFIED.value

        response = api.publish_label_version(
            measured["label"]["id"], COMPLIANCE_OFFICER_2_HEADERS
        )
        label = validate_success(response)

        assert_label_dimensions(
            label,
            PublicationState.PUBLISHED.value,
            SubstantiationStatus.SUBSTANTIATED.value,
        )
        assert label["published_by_user_id"] == COMPLIANCE_OFFICER_2_USER_ID, (
            "published_by_user_id records the publishing officer"
        )
        assert label["attestation_id"] == attestation_id, (
            "publication pins the label to the plan's certified attestation"
        )
        assert_pinned_typical_figures(
            label,
            PEAK_HOUR_MEDIAN_TYPICAL_DOWNLOAD,
            PEAK_HOUR_MEDIAN_TYPICAL_UPLOAD,
            PEAK_HOUR_MEDIAN_TYPICAL_LATENCY,
        )
        assert (
            label["methodology_url_snapshot"]
            == measured["methodology"]["methodology_url"]
            == REFERENCE_METHODOLOGY_URL
        ), "methodology_url_snapshot is copied from the certified attestation"

        plan = read_service_plan(measured["plan"]["id"])
        assert plan["active_label_version_id"] == label["id"], (
            "active_label_version_id names the newly published label"
        )
        assert_posture(plan, LabelPosture.OPEN.value)


# ---------------------------------------------------------------------------
# Half-open geometry of a plan's display timeline
# ---------------------------------------------------------------------------


class TestLabelDisplayWindowGeometry:
    def test_a_draft_starting_where_a_sibling_ends_is_not_an_overlap(
        self, api: ApiClient, reference_environment: ReferenceEnvironment
    ):
        """Exact adjacency at a shared instant is legal on the display timeline.

        PRD: "Two windows overlap when the new `effective_from` is strictly
        before the other's `effective_until` and the other's `effective_from` is
        strictly before the new `effective_until`, which makes exact adjacency
        legal — a new window starting precisely where a sibling draft's window
        ends does not overlap."

        Design: Difficulty/resource_temporal_overlap/label_display_window_half_open_adjacency_allowed
        """
        env = reference_environment

        first_payload = build_label_version_payload(
            env.plan_id,
            DRAFT_ONE_FROM,
            current_plan_version(env.plan_id),
            effective_until=DRAFT_ONE_UNTIL,
        )
        first = validate_success(
            api.create_label_version(first_payload, COMPLIANCE_OFFICER_HEADERS), 201
        )
        assert first["version_seq"] == 2, "the plan's second label takes version_seq 2"
        assert first["publication_state"] == PublicationState.DRAFT.value
        assert _instant(first["effective_from"]) == _instant(DRAFT_ONE_FROM)
        assert _instant(first["effective_until"]) == _instant(DRAFT_ONE_UNTIL)

        adjacent_payload = build_label_version_payload(
            env.plan_id, DRAFT_ONE_UNTIL, current_plan_version(env.plan_id)
        )
        adjacent = validate_success(
            api.create_label_version(adjacent_payload, COMPLIANCE_OFFICER_HEADERS), 201
        )
        assert adjacent["version_seq"] == 3, "the plan's third label takes version_seq 3"
        assert _instant(adjacent["effective_from"]) == _instant(
            first["effective_until"]
        ), (
            "the adjacent draft starts precisely where its sibling's window ends"
        )

        rows = _plan_label_rows(api, env.plan_id)
        assert len(rows) == 3, f"expected exactly three labels on the plan, got {len(rows)}"
        states = {row["version_seq"]: row["publication_state"] for row in rows}
        assert states == {
            1: PublicationState.PUBLISHED.value,
            2: PublicationState.DRAFT.value,
            3: PublicationState.DRAFT.value,
        }, f"unexpected publication states across the plan's labels: {states}"

        published = next(row for row in rows if row["version_seq"] == 1)
        assert published["effective_until"] is None, (
            "the overlap rule compares draft windows only; the published label is "
            "not truncated before a successor is published"
        )

    def test_a_draft_straddling_a_sibling_window_is_refused(
        self, api: ApiClient, reference_environment: ReferenceEnvironment
    ):
        """An open-ended draft that starts inside a sibling window overlaps it.

        PRD: "And the requested half-open window from `effective_from` up to but
        excluding `effective_until` must not overlap the window of any other
        label of the same plan whose `publication_state` is `DRAFT`; a null
        `effective_until` is treated as extending to positive infinity."

        Design: Difficulty/resource_temporal_overlap/label_display_window_half_open_adjacency_allowed
        """
        env = reference_environment

        draft_label(
            env.plan_id, effective_from=DRAFT_ONE_FROM, effective_until=DRAFT_ONE_UNTIL
        )

        straddling_payload = build_label_version_payload(
            env.plan_id, STRADDLING_FROM, current_plan_version(env.plan_id)
        )
        response = api.create_label_version(
            straddling_payload, COMPLIANCE_OFFICER_HEADERS
        )
        validate_error(response, ApiErrorId.ERR_LABEL_WINDOW_OVERLAP.value)

        rows = _plan_label_rows(api, env.plan_id)
        assert len(rows) == 2, (
            f"the refused draft must not have been written, got {len(rows)} labels"
        )

    def test_temporal_admissibility_is_decided_before_interval_geometry(
        self, api: ApiClient, reference_environment: ReferenceEnvironment
    ):
        """The temporal rule refuses the draft before interval geometry is reached.

        The rejection ladder decides temporal admissibility — the source of
        `ERR_LABEL_EFFECTIVE_NOT_AFTER_PUBLISHED` — at step 11, and interval
        geometry — the source of `ERR_LABEL_WINDOW_OVERLAP` — only at step 13, so
        a draft that violates both rules surfaces the temporal one.

        PRD: "When several rules could reject the same request, the system
        evaluates them in the fixed order below and returns the first failure it
        finds."

        Design: Difficulty/resource_temporal_overlap/label_display_window_half_open_adjacency_allowed
        """
        env = reference_environment
        published = env.reload_label()
        assert _instant(published["effective_from"]) == _instant(REFERENCE_NOW), (
            "the scenario needs the published label to start at the clock instant "
            "the refused draft also claims"
        )

        draft_label(
            env.plan_id, effective_from=DRAFT_ONE_FROM, effective_until=DRAFT_ONE_UNTIL
        )
        draft_label(env.plan_id, effective_from=DRAFT_ONE_UNTIL)

        plan_version = current_plan_version(env.plan_id)
        payload = build_label_version_payload(env.plan_id, REFERENCE_NOW, plan_version)
        response = api.create_label_version(payload, COMPLIANCE_OFFICER_HEADERS)
        validate_error(
            response, ApiErrorId.ERR_LABEL_EFFECTIVE_NOT_AFTER_PUBLISHED.value
        )

        rows = _plan_label_rows(api, env.plan_id)
        assert len(rows) == 3, (
            f"the refused draft must not have been written, got {len(rows)} labels"
        )
