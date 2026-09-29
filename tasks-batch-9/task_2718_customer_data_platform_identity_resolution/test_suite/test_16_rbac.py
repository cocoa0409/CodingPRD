"""Role-based access control for the customer data platform.

Seven peer roles hold exclusive write operations, share one unrestricted read
surface, and the DestinationPlatform role is additionally bound to a single
destination row by its X-User-ID. Two duties are segregated on the acting user
identifier rather than on the role.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_DESTINATION_ACTOR_MISMATCH,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_UNAUTHORIZED,
)
from test_helpers.assertions import assert_unchanged, assert_version_unchanged
from test_helpers.test_users import (
    ADMIN,
    ANALYST,
    ENGINEER,
    GOVERNANCE,
    GOVERNANCE_USER_ID,
    PRIVACY,
    ROLE_DATA_GOVERNANCE_OFFICER,
    ROLE_SEGMENT_ANALYST,
    STEWARD,
    make_destination_platform_headers,
    make_headers,
)

POSTAL_CRITERION = f.criterion("postal_code", "EQ", "10001")


def test_peer_roles_do_not_overlap_on_segments_and_ingest_batches(api):
    """A DataEngineer cannot create a segment and a SegmentAnalyst cannot submit an
    ingest batch: neither peer role is a superset of the other, and both refusals
    are the role rung rather than any business rule.

    PRD: "If `X-User-Role` is not one of those seven strings, or is one of them but is not listed among the authorized roles for the endpoint being called (see the §4 table), the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD: "`DataEngineer` operates the ingestion pipeline: submitting record batches, running data-quality validation, requeuing quarantined batches, and promoting validated batches into the profile graph."
    PRD: "`SegmentAnalyst` builds audiences and runs deliveries: defining segments, submitting them for governance review, creating activations, dispatching, pausing and resuming them."

    Design: Corner/rbac/data_engineer_cannot_create_segment_unauthorized
    """
    fx.reset_clock(api)
    feed = fx.register_feed(
        api,
        code="RB_PEER",
        display_name="Peer Role Feed",
        channel_type="WEB",
        trust_tier=3,
    )

    segment_payload = f.segment_payload(
        [POSTAL_CRITERION], name="Engineer Segment Attempt"
    )
    batch_payload = f.ingest_batch_payload(
        feed["id"], [f.raw_record("RB1")], batch_label="Analyst Ingest Attempt"
    )

    # The ingestion role reaching for the audience surface.
    validate_error(api.create_segment(segment_payload, ENGINEER), ERR_UNAUTHORIZED)
    # The audience role reaching for the ingestion surface.
    validate_error(
        api.create_ingest_batch(batch_payload, ANALYST), ERR_UNAUTHORIZED
    )

    _, segment_meta = validate_paginated(api.list_segments(ADMIN))
    assert segment_meta["total_count"] == 0, "the refused create must persist nothing"
    _, batch_meta = validate_paginated(api.list_ingest_batches(ADMIN))
    assert batch_meta["total_count"] == 0, "the refused submit must persist nothing"

    # The identical payloads succeed for the roles the endpoints do authorize.
    validate_success(api.create_segment(segment_payload, ANALYST), 201)
    validate_success(api.create_ingest_batch(batch_payload, ENGINEER), 201)


def test_segment_analyst_cannot_record_the_governance_decision(api):
    """The analyst who submitted a segment for review cannot record its governance
    decision; the refusal is the role rung at 403, not the segregation-of-duties
    rung at 409.

    PRD: "`DataGovernanceOfficer` approves or rejects segment governance and holds sole authority over sensitive-attribute usage."
    PRD: "If `X-User-Role` is not one of those seven strings, or is one of them but is not listed among the authorized roles for the endpoint being called (see the §4 table), the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/segment_analyst_cannot_record_governance_decision_unauthorized
    """
    fx.reset_clock(api)
    segment = fx.draft_segment(api, [POSTAL_CRITERION], name="Chain Segment")
    submitted = fx.submit_segment(api, segment["id"])
    assert submitted["status"] == "PENDING_GOVERNANCE_REVIEW"

    decision = f.governance_decision_payload("APPROVE", False)
    validate_error(
        api.decide_segment_governance(segment["id"], decision, ANALYST),
        ERR_UNAUTHORIZED,
    )

    after = fx.reread_segment(api, segment["id"])
    assert after["status"] == "PENDING_GOVERNANCE_REVIEW", (
        "a refused decision leaves the segment awaiting review"
    )
    assert_unchanged(
        submitted,
        after,
        "decided_by_user_id",
        "approved_at",
        "governance_expires_at",
        "rejection_count",
    )
    assert_version_unchanged(submitted, after)

    approved = get_success_data(
        api.decide_segment_governance(segment["id"], decision, GOVERNANCE),
        expected_status=200,
    )
    assert approved["status"] == "APPROVED"


def test_all_seven_roles_receive_the_identical_profile_list(api):
    """The profile list is authorized for every one of the seven roles, including
    the machine DestinationPlatform role, and no role sees a filtered variant.

    PRD: "In the Authorized Role(s) column, **All roles** is shorthand for all seven roles of §2.1: `DataPlatformAdmin`, `DataEngineer`, `IdentitySteward`, `PrivacyOfficer`, `SegmentAnalyst`, `DataGovernanceOfficer` and `DestinationPlatform`."
    PRD: "`DestinationPlatform` is the advertising or messaging platform itself, reporting its own match results and acknowledging its own downstream deletion tasks."

    Design: Corner/rbac/every_role_can_read_profiles_shared_operation
    """
    fx.reset_clock(api)
    env = fx.single_profile(api)
    profile_id = env["profile"]["id"]

    header_sets = [
        ADMIN,
        ENGINEER,
        STEWARD,
        PRIVACY,
        ANALYST,
        GOVERNANCE,
        make_destination_platform_headers("d_platform"),
    ]

    seen = []
    for headers in header_sets:
        data, meta = validate_paginated(api.list_profiles(headers))
        assert meta["total_count"] == 1, (
            f"{headers['X-User-Role']} must see the single profile"
        )
        assert len(data) == 1 and data[0]["id"] == profile_id
        seen.append(
            (
                data,
                meta["total_count"],
                meta["limit"],
                meta["offset"],
                meta["has_more"],
            )
        )

    for observed in seen[1:]:
        assert observed == seen[0], (
            "the shared read surface is not role-scoped: every role must receive "
            "the identical payload and pagination meta"
        )


def test_destination_platform_cannot_report_on_another_destinations_activation(api):
    """A destination platform holding the role but not the activation's
    destination_id is refused: the actor binding is per-row, so the answer is the
    actor-mismatch error rather than an authorization error.

    PRD: "Concretely, when a destination platform reports match results for an activation, `X-User-ID` must equal that activation's `destination_id`; when it acknowledges a downstream deletion task, `X-User-ID` must equal that task's `destination_id`."
    PRD: "A platform reporting on somebody else's delivery is rejected with `ERR_DESTINATION_ACTOR_MISMATCH` (HTTP 403), and this check runs immediately after role authorization, before any resource is looked up by path."

    Design: Corner/rbac/destination_platform_match_report_for_another_destination_forbidden
    """
    fx.reset_clock(api)
    env = fx.delivering_activation_environment(
        api,
        member_count=1,
        destination_overrides={"code": "RB_ACTOR_A", "daily_hash_quota": 300},
    )
    dispatched = env["activation"]
    assert dispatched["status"] == "DISPATCHED"
    assert dispatched["dispatched_hash_count"] == 1

    other = fx.register_destination(
        api,
        code="RB_ACTOR_B",
        platform_kind="MESSAGING",
        daily_hash_quota=300,
    )

    report = f.match_report_payload(1, 0, [])
    validate_error(
        api.report_match(
            dispatched["id"],
            report,
            make_destination_platform_headers(other["id"]),
        ),
        ERR_DESTINATION_ACTOR_MISMATCH,
    )

    after = fx.reread_activation(api, dispatched["id"])
    assert after["status"] == "DISPATCHED", "the refused report changes no state"
    assert_unchanged(
        dispatched, after, "vendor_matched_count", "unusable_hash_count"
    )
    assert_version_unchanged(dispatched, after)

    accepted = get_success_data(
        api.report_match(
            dispatched["id"],
            report,
            make_destination_platform_headers(env["destination"]["id"]),
        ),
        expected_status=200,
    )
    assert accepted["status"] == "ACTIVE", (
        "the owning platform's identical report is accepted and routes the "
        "activation by its effective match rate"
    )


def test_same_user_id_submitting_and_deciding_a_segment_is_refused(api):
    """One operator identifier that submits a segment and then presents as a
    governance officer to decide it is refused on identity, not on role, and the
    segment stays under review.

    PRD: "Two duties are segregated on `X-User-ID`, and both violations answer `ERR_SEGREGATION_OF_DUTIES` (HTTP 409)."
    PRD: "First, the operator recording a segment's governance decision must not be the operator recorded in `submitted_by_user_id`; a `SegmentAnalyst` who submits and a `DataGovernanceOfficer` who decides are peers over the same resource, split by step."

    Design: Corner/rbac/same_user_submitting_and_deciding_segment_rejected
    """
    fx.reset_clock(api)
    dual_analyst = make_headers("u_dual", ROLE_SEGMENT_ANALYST)
    dual_officer = make_headers("u_dual", ROLE_DATA_GOVERNANCE_OFFICER)

    segment = get_success_data(
        api.create_segment(
            f.segment_payload([POSTAL_CRITERION], name="Dual Hat Segment"),
            dual_analyst,
        ),
        expected_status=201,
    )
    submitted = get_success_data(
        api.submit_segment_for_review(segment["id"], dual_analyst),
        expected_status=200,
    )
    assert submitted["submitted_by_user_id"] == "u_dual"
    assert submitted["status"] == "PENDING_GOVERNANCE_REVIEW"

    decision = f.governance_decision_payload("APPROVE", False)
    validate_error(
        api.decide_segment_governance(segment["id"], decision, dual_officer),
        ERR_SEGREGATION_OF_DUTIES,
    )

    after = fx.reread_segment(api, segment["id"])
    assert after["status"] == "PENDING_GOVERNANCE_REVIEW"
    assert after["rejection_count"] == 0, (
        "the refused decision is neither an approval nor a rejection"
    )
    assert_unchanged(submitted, after, "decided_by_user_id", "approved_at")
    assert_version_unchanged(submitted, after)

    approved = get_success_data(
        api.decide_segment_governance(segment["id"], decision, GOVERNANCE),
        expected_status=200,
    )
    assert approved["status"] == "APPROVED"
    assert approved["decided_by_user_id"] == GOVERNANCE_USER_ID, (
        "only the identity collision was refused; a different officer decides"
    )
