"""Refusals: authentication, existence, shape, state and business-guard errors.

Every test drives the live API and asserts the single error the validation ladder
selects, together with the state the refused call must have left untouched.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_CONSENT_RECORD_NOT_FOUND,
    ERR_DELETION_REQUEST_NOT_FOUND,
    ERR_DESTINATION_INACTIVE,
    ERR_DESTINATION_NOT_FOUND,
    ERR_DETERMINISTIC_KEY_MISMATCH,
    ERR_DUPLICATE_EXTERNAL_ID,
    ERR_DUPLICATE_IDENTITY_LINK,
    ERR_FUTURE_CAPTURED_AT,
    ERR_GOVERNANCE_JUSTIFICATION_REQUIRED,
    ERR_HOUSEHOLD_CAPACITY_EXCEEDED,
    ERR_HOUSEHOLD_NOT_FOUND,
    ERR_IDENTITY_LINK_NOT_FOUND,
    ERR_INGEST_BATCH_NOT_FOUND,
    ERR_INVALID_HOUSEHOLD_STATE,
    ERR_INVALID_THRESHOLD_ORDER,
    ERR_INVALID_WINDOW,
    ERR_MATCH_REPORT_EXCEEDS_DISPATCH,
    ERR_MATCH_RULE_DISABLED,
    ERR_MATCH_RULE_NOT_FOUND,
    ERR_MISSING_AUTH_HEADERS,
    ERR_OVERLAP_SAME_SEGMENT,
    ERR_PROFILE_DELETED,
    ERR_PROFILE_MERGED_AWAY,
    ERR_SELF_LINK_FORBIDDEN,
    ERR_SEGMENT_NOT_FOUND,
    ERR_SOURCE_SYSTEM_QUARANTINED,
    ERR_SUPPRESSION_ENTRY_NOT_FOUND,
    ERR_VENDOR_TASK_NOT_FOUND,
)
from test_helpers.assertions import (
    approx4,
    assert_instant_equals,
    assert_profile_axes,
    assert_tombstoned_identifiers,
)
from test_helpers.constants import DEFAULT_CLOCK
from test_helpers.test_users import (
    ADMIN,
    ANALYST,
    ENGINEER,
    PRIVACY,
    STEWARD,
    headers_without_auth,
    make_destination_platform_headers,
)


def test_request_missing_x_user_role_header_returns_401_unauthenticated(api):
    """A request that carries neither identity header is refused before anything
    else happens, and the very same read succeeds once the headers are present.

    "Every request to every endpoint must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming the role it is acting under."
    "If either header is absent, or is present but blank after trimming, the request is rejected with `ERR_MISSING_AUTH_HEADERS` (HTTP 401)."
    "This is the very first check the platform performs; nothing else — not path resolution, not body parsing — happens before it."

    Design: Corner/errors/request_missing_x_user_role_header_returns_401_unauthenticated
    """
    validate_error(
        api.list_source_systems(headers_without_auth()), ERR_MISSING_AUTH_HEADERS, 401
    )

    rows, meta = validate_paginated(api.list_source_systems(ENGINEER))
    assert meta["total_count"] == 0
    assert rows == []


def test_get_ingest_batch_unknown_id_not_found(api):
    """Reading an ingest batch id that no call ever minted answers that
    resource's own existence error with a 404.

    "Rungs 5 through 17 are existence, in this fixed order: (5) the retail feed named by `{sourceSystemId}` or by a `source_system_id` body field exists, else `ERR_SOURCE_SYSTEM_NOT_FOUND`; (6) the batch named by `{batchId}` exists, else `ERR_INGEST_BATCH_NOT_FOUND`; (7) every profile named by `{profileId}`, `profile_id`, `left_profile_id` or `right_profile_id` exists, else `ERR_PROFILE_NOT_FOUND`; (8) the household named by `{householdId}` or by the `household_id` body field exists, else `ERR_HOUSEHOLD_NOT_FOUND`; (9) the rule named by `{matchRuleId}` or `match_rule_id` exists, else `ERR_MATCH_RULE_NOT_FOUND`; (10) the link named by `{linkId}` exists, else `ERR_IDENTITY_LINK_NOT_FOUND`; (11) the consent record named by `{consentRecordId}` exists, else `ERR_CONSENT_RECORD_NOT_FOUND`; (12) the suppression entry named by `{suppressionId}` exists, else `ERR_SUPPRESSION_ENTRY_NOT_FOUND`; (13) the segment named by `{segmentId}`, `segment_id` or the `other_segment_id` query parameter exists, else `ERR_SEGMENT_NOT_FOUND`; (14) the destination named by `{destinationId}` or `destination_id` exists, else `ERR_DESTINATION_NOT_FOUND`; (15) the activation named by `{activationId}` exists, else `ERR_ACTIVATION_NOT_FOUND`; (16) the erasure request named by `{deletionRequestId}` exists, else `ERR_DELETION_REQUEST_NOT_FOUND`; (17) the vendor task named by `{taskId}` exists, else `ERR_VENDOR_TASK_NOT_FOUND`."

    Design: Corner/errors/get_ingest_batch_unknown_id_not_found
    """
    validate_error(
        api.get_ingest_batch(NON_EXISTENT_UUID, ADMIN), ERR_INGEST_BATCH_NOT_FOUND, 404
    )


def test_get_household_unknown_id_not_found(api):
    """Reading a household id that no call ever minted answers that
    resource's own existence error with a 404.

    "Rungs 5 through 17 are existence, in this fixed order: (5) the retail feed named by `{sourceSystemId}` or by a `source_system_id` body field exists, else `ERR_SOURCE_SYSTEM_NOT_FOUND`; (6) the batch named by `{batchId}` exists, else `ERR_INGEST_BATCH_NOT_FOUND`; (7) every profile named by `{profileId}`, `profile_id`, `left_profile_id` or `right_profile_id` exists, else `ERR_PROFILE_NOT_FOUND`; (8) the household named by `{householdId}` or by the `household_id` body field exists, else `ERR_HOUSEHOLD_NOT_FOUND`; (9) the rule named by `{matchRuleId}` or `match_rule_id` exists, else `ERR_MATCH_RULE_NOT_FOUND`; (10) the link named by `{linkId}` exists, else `ERR_IDENTITY_LINK_NOT_FOUND`; (11) the consent record named by `{consentRecordId}` exists, else `ERR_CONSENT_RECORD_NOT_FOUND`; (12) the suppression entry named by `{suppressionId}` exists, else `ERR_SUPPRESSION_ENTRY_NOT_FOUND`; (13) the segment named by `{segmentId}`, `segment_id` or the `other_segment_id` query parameter exists, else `ERR_SEGMENT_NOT_FOUND`; (14) the destination named by `{destinationId}` or `destination_id` exists, else `ERR_DESTINATION_NOT_FOUND`; (15) the activation named by `{activationId}` exists, else `ERR_ACTIVATION_NOT_FOUND`; (16) the erasure request named by `{deletionRequestId}` exists, else `ERR_DELETION_REQUEST_NOT_FOUND`; (17) the vendor task named by `{taskId}` exists, else `ERR_VENDOR_TASK_NOT_FOUND`."

    Design: Corner/errors/get_household_unknown_id_not_found
    """
    validate_error(
        api.get_household(NON_EXISTENT_UUID, ADMIN), ERR_HOUSEHOLD_NOT_FOUND, 404
    )


def test_get_match_rule_unknown_id_not_found(api):
    """Reading a match rule id that no call ever minted answers that
    resource's own existence error with a 404.

    "Rungs 5 through 17 are existence, in this fixed order: (5) the retail feed named by `{sourceSystemId}` or by a `source_system_id` body field exists, else `ERR_SOURCE_SYSTEM_NOT_FOUND`; (6) the batch named by `{batchId}` exists, else `ERR_INGEST_BATCH_NOT_FOUND`; (7) every profile named by `{profileId}`, `profile_id`, `left_profile_id` or `right_profile_id` exists, else `ERR_PROFILE_NOT_FOUND`; (8) the household named by `{householdId}` or by the `household_id` body field exists, else `ERR_HOUSEHOLD_NOT_FOUND`; (9) the rule named by `{matchRuleId}` or `match_rule_id` exists, else `ERR_MATCH_RULE_NOT_FOUND`; (10) the link named by `{linkId}` exists, else `ERR_IDENTITY_LINK_NOT_FOUND`; (11) the consent record named by `{consentRecordId}` exists, else `ERR_CONSENT_RECORD_NOT_FOUND`; (12) the suppression entry named by `{suppressionId}` exists, else `ERR_SUPPRESSION_ENTRY_NOT_FOUND`; (13) the segment named by `{segmentId}`, `segment_id` or the `other_segment_id` query parameter exists, else `ERR_SEGMENT_NOT_FOUND`; (14) the destination named by `{destinationId}` or `destination_id` exists, else `ERR_DESTINATION_NOT_FOUND`; (15) the activation named by `{activationId}` exists, else `ERR_ACTIVATION_NOT_FOUND`; (16) the erasure request named by `{deletionRequestId}` exists, else `ERR_DELETION_REQUEST_NOT_FOUND`; (17) the vendor task named by `{taskId}` exists, else `ERR_VENDOR_TASK_NOT_FOUND`."

    Design: Corner/errors/get_match_rule_unknown_id_not_found
    """
    validate_error(
        api.get_match_rule(NON_EXISTENT_UUID, ADMIN), ERR_MATCH_RULE_NOT_FOUND, 404
    )


def test_get_identity_link_unknown_id_not_found(api):
    """Reading an identity link id that no call ever minted answers that
    resource's own existence error with a 404.

    "Rungs 5 through 17 are existence, in this fixed order: (5) the retail feed named by `{sourceSystemId}` or by a `source_system_id` body field exists, else `ERR_SOURCE_SYSTEM_NOT_FOUND`; (6) the batch named by `{batchId}` exists, else `ERR_INGEST_BATCH_NOT_FOUND`; (7) every profile named by `{profileId}`, `profile_id`, `left_profile_id` or `right_profile_id` exists, else `ERR_PROFILE_NOT_FOUND`; (8) the household named by `{householdId}` or by the `household_id` body field exists, else `ERR_HOUSEHOLD_NOT_FOUND`; (9) the rule named by `{matchRuleId}` or `match_rule_id` exists, else `ERR_MATCH_RULE_NOT_FOUND`; (10) the link named by `{linkId}` exists, else `ERR_IDENTITY_LINK_NOT_FOUND`; (11) the consent record named by `{consentRecordId}` exists, else `ERR_CONSENT_RECORD_NOT_FOUND`; (12) the suppression entry named by `{suppressionId}` exists, else `ERR_SUPPRESSION_ENTRY_NOT_FOUND`; (13) the segment named by `{segmentId}`, `segment_id` or the `other_segment_id` query parameter exists, else `ERR_SEGMENT_NOT_FOUND`; (14) the destination named by `{destinationId}` or `destination_id` exists, else `ERR_DESTINATION_NOT_FOUND`; (15) the activation named by `{activationId}` exists, else `ERR_ACTIVATION_NOT_FOUND`; (16) the erasure request named by `{deletionRequestId}` exists, else `ERR_DELETION_REQUEST_NOT_FOUND`; (17) the vendor task named by `{taskId}` exists, else `ERR_VENDOR_TASK_NOT_FOUND`."

    Design: Corner/errors/get_identity_link_unknown_id_not_found
    """
    validate_error(
        api.get_identity_link(NON_EXISTENT_UUID, ADMIN), ERR_IDENTITY_LINK_NOT_FOUND, 404
    )


def test_get_consent_record_unknown_id_not_found(api):
    """Reading a consent election id that no call ever minted answers that
    resource's own existence error with a 404.

    "Rungs 5 through 17 are existence, in this fixed order: (5) the retail feed named by `{sourceSystemId}` or by a `source_system_id` body field exists, else `ERR_SOURCE_SYSTEM_NOT_FOUND`; (6) the batch named by `{batchId}` exists, else `ERR_INGEST_BATCH_NOT_FOUND`; (7) every profile named by `{profileId}`, `profile_id`, `left_profile_id` or `right_profile_id` exists, else `ERR_PROFILE_NOT_FOUND`; (8) the household named by `{householdId}` or by the `household_id` body field exists, else `ERR_HOUSEHOLD_NOT_FOUND`; (9) the rule named by `{matchRuleId}` or `match_rule_id` exists, else `ERR_MATCH_RULE_NOT_FOUND`; (10) the link named by `{linkId}` exists, else `ERR_IDENTITY_LINK_NOT_FOUND`; (11) the consent record named by `{consentRecordId}` exists, else `ERR_CONSENT_RECORD_NOT_FOUND`; (12) the suppression entry named by `{suppressionId}` exists, else `ERR_SUPPRESSION_ENTRY_NOT_FOUND`; (13) the segment named by `{segmentId}`, `segment_id` or the `other_segment_id` query parameter exists, else `ERR_SEGMENT_NOT_FOUND`; (14) the destination named by `{destinationId}` or `destination_id` exists, else `ERR_DESTINATION_NOT_FOUND`; (15) the activation named by `{activationId}` exists, else `ERR_ACTIVATION_NOT_FOUND`; (16) the erasure request named by `{deletionRequestId}` exists, else `ERR_DELETION_REQUEST_NOT_FOUND`; (17) the vendor task named by `{taskId}` exists, else `ERR_VENDOR_TASK_NOT_FOUND`."

    Design: Corner/errors/get_consent_record_unknown_id_not_found
    """
    validate_error(
        api.get_consent_record(NON_EXISTENT_UUID, ADMIN), ERR_CONSENT_RECORD_NOT_FOUND, 404
    )


def test_get_suppression_entry_unknown_id_not_found(api):
    """Reading a suppression entry id that no call ever minted answers that
    resource's own existence error with a 404.

    "Rungs 5 through 17 are existence, in this fixed order: (5) the retail feed named by `{sourceSystemId}` or by a `source_system_id` body field exists, else `ERR_SOURCE_SYSTEM_NOT_FOUND`; (6) the batch named by `{batchId}` exists, else `ERR_INGEST_BATCH_NOT_FOUND`; (7) every profile named by `{profileId}`, `profile_id`, `left_profile_id` or `right_profile_id` exists, else `ERR_PROFILE_NOT_FOUND`; (8) the household named by `{householdId}` or by the `household_id` body field exists, else `ERR_HOUSEHOLD_NOT_FOUND`; (9) the rule named by `{matchRuleId}` or `match_rule_id` exists, else `ERR_MATCH_RULE_NOT_FOUND`; (10) the link named by `{linkId}` exists, else `ERR_IDENTITY_LINK_NOT_FOUND`; (11) the consent record named by `{consentRecordId}` exists, else `ERR_CONSENT_RECORD_NOT_FOUND`; (12) the suppression entry named by `{suppressionId}` exists, else `ERR_SUPPRESSION_ENTRY_NOT_FOUND`; (13) the segment named by `{segmentId}`, `segment_id` or the `other_segment_id` query parameter exists, else `ERR_SEGMENT_NOT_FOUND`; (14) the destination named by `{destinationId}` or `destination_id` exists, else `ERR_DESTINATION_NOT_FOUND`; (15) the activation named by `{activationId}` exists, else `ERR_ACTIVATION_NOT_FOUND`; (16) the erasure request named by `{deletionRequestId}` exists, else `ERR_DELETION_REQUEST_NOT_FOUND`; (17) the vendor task named by `{taskId}` exists, else `ERR_VENDOR_TASK_NOT_FOUND`."

    Design: Corner/errors/get_suppression_entry_unknown_id_not_found
    """
    validate_error(
        api.get_suppression_entry(NON_EXISTENT_UUID, ADMIN), ERR_SUPPRESSION_ENTRY_NOT_FOUND, 404
    )


def test_get_segment_unknown_id_not_found(api):
    """Reading a segment id that no call ever minted answers that
    resource's own existence error with a 404.

    "Rungs 5 through 17 are existence, in this fixed order: (5) the retail feed named by `{sourceSystemId}` or by a `source_system_id` body field exists, else `ERR_SOURCE_SYSTEM_NOT_FOUND`; (6) the batch named by `{batchId}` exists, else `ERR_INGEST_BATCH_NOT_FOUND`; (7) every profile named by `{profileId}`, `profile_id`, `left_profile_id` or `right_profile_id` exists, else `ERR_PROFILE_NOT_FOUND`; (8) the household named by `{householdId}` or by the `household_id` body field exists, else `ERR_HOUSEHOLD_NOT_FOUND`; (9) the rule named by `{matchRuleId}` or `match_rule_id` exists, else `ERR_MATCH_RULE_NOT_FOUND`; (10) the link named by `{linkId}` exists, else `ERR_IDENTITY_LINK_NOT_FOUND`; (11) the consent record named by `{consentRecordId}` exists, else `ERR_CONSENT_RECORD_NOT_FOUND`; (12) the suppression entry named by `{suppressionId}` exists, else `ERR_SUPPRESSION_ENTRY_NOT_FOUND`; (13) the segment named by `{segmentId}`, `segment_id` or the `other_segment_id` query parameter exists, else `ERR_SEGMENT_NOT_FOUND`; (14) the destination named by `{destinationId}` or `destination_id` exists, else `ERR_DESTINATION_NOT_FOUND`; (15) the activation named by `{activationId}` exists, else `ERR_ACTIVATION_NOT_FOUND`; (16) the erasure request named by `{deletionRequestId}` exists, else `ERR_DELETION_REQUEST_NOT_FOUND`; (17) the vendor task named by `{taskId}` exists, else `ERR_VENDOR_TASK_NOT_FOUND`."

    Design: Corner/errors/get_segment_unknown_id_not_found
    """
    validate_error(
        api.get_segment(NON_EXISTENT_UUID, ADMIN), ERR_SEGMENT_NOT_FOUND, 404
    )


def test_get_destination_unknown_id_not_found(api):
    """Reading a destination id that no call ever minted answers that
    resource's own existence error with a 404.

    "Rungs 5 through 17 are existence, in this fixed order: (5) the retail feed named by `{sourceSystemId}` or by a `source_system_id` body field exists, else `ERR_SOURCE_SYSTEM_NOT_FOUND`; (6) the batch named by `{batchId}` exists, else `ERR_INGEST_BATCH_NOT_FOUND`; (7) every profile named by `{profileId}`, `profile_id`, `left_profile_id` or `right_profile_id` exists, else `ERR_PROFILE_NOT_FOUND`; (8) the household named by `{householdId}` or by the `household_id` body field exists, else `ERR_HOUSEHOLD_NOT_FOUND`; (9) the rule named by `{matchRuleId}` or `match_rule_id` exists, else `ERR_MATCH_RULE_NOT_FOUND`; (10) the link named by `{linkId}` exists, else `ERR_IDENTITY_LINK_NOT_FOUND`; (11) the consent record named by `{consentRecordId}` exists, else `ERR_CONSENT_RECORD_NOT_FOUND`; (12) the suppression entry named by `{suppressionId}` exists, else `ERR_SUPPRESSION_ENTRY_NOT_FOUND`; (13) the segment named by `{segmentId}`, `segment_id` or the `other_segment_id` query parameter exists, else `ERR_SEGMENT_NOT_FOUND`; (14) the destination named by `{destinationId}` or `destination_id` exists, else `ERR_DESTINATION_NOT_FOUND`; (15) the activation named by `{activationId}` exists, else `ERR_ACTIVATION_NOT_FOUND`; (16) the erasure request named by `{deletionRequestId}` exists, else `ERR_DELETION_REQUEST_NOT_FOUND`; (17) the vendor task named by `{taskId}` exists, else `ERR_VENDOR_TASK_NOT_FOUND`."

    Design: Corner/errors/get_destination_unknown_id_not_found
    """
    validate_error(
        api.get_destination(NON_EXISTENT_UUID, ADMIN), ERR_DESTINATION_NOT_FOUND, 404
    )


def test_get_deletion_request_unknown_id_not_found(api):
    """Reading an erasure request id that no call ever minted answers that
    resource's own existence error with a 404.

    "Rungs 5 through 17 are existence, in this fixed order: (5) the retail feed named by `{sourceSystemId}` or by a `source_system_id` body field exists, else `ERR_SOURCE_SYSTEM_NOT_FOUND`; (6) the batch named by `{batchId}` exists, else `ERR_INGEST_BATCH_NOT_FOUND`; (7) every profile named by `{profileId}`, `profile_id`, `left_profile_id` or `right_profile_id` exists, else `ERR_PROFILE_NOT_FOUND`; (8) the household named by `{householdId}` or by the `household_id` body field exists, else `ERR_HOUSEHOLD_NOT_FOUND`; (9) the rule named by `{matchRuleId}` or `match_rule_id` exists, else `ERR_MATCH_RULE_NOT_FOUND`; (10) the link named by `{linkId}` exists, else `ERR_IDENTITY_LINK_NOT_FOUND`; (11) the consent record named by `{consentRecordId}` exists, else `ERR_CONSENT_RECORD_NOT_FOUND`; (12) the suppression entry named by `{suppressionId}` exists, else `ERR_SUPPRESSION_ENTRY_NOT_FOUND`; (13) the segment named by `{segmentId}`, `segment_id` or the `other_segment_id` query parameter exists, else `ERR_SEGMENT_NOT_FOUND`; (14) the destination named by `{destinationId}` or `destination_id` exists, else `ERR_DESTINATION_NOT_FOUND`; (15) the activation named by `{activationId}` exists, else `ERR_ACTIVATION_NOT_FOUND`; (16) the erasure request named by `{deletionRequestId}` exists, else `ERR_DELETION_REQUEST_NOT_FOUND`; (17) the vendor task named by `{taskId}` exists, else `ERR_VENDOR_TASK_NOT_FOUND`."

    Design: Corner/errors/get_deletion_request_unknown_id_not_found
    """
    validate_error(
        api.get_deletion_request(NON_EXISTENT_UUID, ADMIN), ERR_DELETION_REQUEST_NOT_FOUND, 404
    )


def test_get_vendor_task_unknown_id_not_found(api):
    """Reading a vendor deletion task id that no call ever minted answers that
    resource's own existence error with a 404.

    "Rungs 5 through 17 are existence, in this fixed order: (5) the retail feed named by `{sourceSystemId}` or by a `source_system_id` body field exists, else `ERR_SOURCE_SYSTEM_NOT_FOUND`; (6) the batch named by `{batchId}` exists, else `ERR_INGEST_BATCH_NOT_FOUND`; (7) every profile named by `{profileId}`, `profile_id`, `left_profile_id` or `right_profile_id` exists, else `ERR_PROFILE_NOT_FOUND`; (8) the household named by `{householdId}` or by the `household_id` body field exists, else `ERR_HOUSEHOLD_NOT_FOUND`; (9) the rule named by `{matchRuleId}` or `match_rule_id` exists, else `ERR_MATCH_RULE_NOT_FOUND`; (10) the link named by `{linkId}` exists, else `ERR_IDENTITY_LINK_NOT_FOUND`; (11) the consent record named by `{consentRecordId}` exists, else `ERR_CONSENT_RECORD_NOT_FOUND`; (12) the suppression entry named by `{suppressionId}` exists, else `ERR_SUPPRESSION_ENTRY_NOT_FOUND`; (13) the segment named by `{segmentId}`, `segment_id` or the `other_segment_id` query parameter exists, else `ERR_SEGMENT_NOT_FOUND`; (14) the destination named by `{destinationId}` or `destination_id` exists, else `ERR_DESTINATION_NOT_FOUND`; (15) the activation named by `{activationId}` exists, else `ERR_ACTIVATION_NOT_FOUND`; (16) the erasure request named by `{deletionRequestId}` exists, else `ERR_DELETION_REQUEST_NOT_FOUND`; (17) the vendor task named by `{taskId}` exists, else `ERR_VENDOR_TASK_NOT_FOUND`."

    Design: Corner/errors/get_vendor_task_unknown_id_not_found
    """
    validate_error(
        api.get_vendor_task(NON_EXISTENT_UUID, ADMIN), ERR_VENDOR_TASK_NOT_FOUND, 404
    )


def test_batch_with_duplicate_external_id_rejected(api):
    """A batch whose two records share one external id is refused outright, so no
    batch is stored and the feed's rolling quality window never moves.

    "Each element of `records` is an object carrying a required `external_id` that must be unique within the batch, a required `event_timestamp` as an ISO 8601 string, and the nullable raw identifier fields `email_raw`, `phone_raw`, `loyalty_number`, `first_name`, `last_name`, `postal_code` and `address_line`, plus a `consent_signals` array that may be empty and whose elements each carry a `channel`, a `purpose` and a `consent_state`."
    "Two records in the same batch sharing an `external_id` are refused with `ERR_DUPLICATE_EXTERNAL_ID`."
    "There is exactly one deliberate exception to the rule that an error response leaves state untouched, and it is described in §3.2: the requeue attempt that exhausts a batch's retry budget both fails and advances the batch to `REJECTED`."
    "Its `dq_window_start_at` is stamped at the logical clock now, opening a rolling data-quality window; `submitted_record_total` and `valid_record_total` start at 0, `dq_pass_rate` starts at 1.0, and `quarantine_count` starts at 0 with `last_reinstated_at` null."

    Design: Corner/errors/batch_with_duplicate_external_id_rejected
    """
    feed = fx.register_feed(api)
    records = [f.raw_record("DUP001"), f.raw_record("DUP001")]

    validate_error(
        api.create_ingest_batch(
            f.ingest_batch_payload(feed["id"], records), ENGINEER
        ),
        ERR_DUPLICATE_EXTERNAL_ID,
        422,
    )

    stored, meta = validate_paginated(
        api.list_ingest_batches(ADMIN, {"source_system_id": feed["id"]})
    )
    assert meta["total_count"] == 0
    assert stored == []

    after = fx.reread_feed(api, feed["id"])
    assert after["status"] == "REGISTERED"
    assert after["submitted_record_total"] == 0
    assert after["valid_record_total"] == 0
    assert after["version"] == feed["version"]


def test_match_rule_with_auto_merge_below_review_floor_rejected(api):
    """A merge threshold at or below the review floor leaves no review band, so
    both the inverted pair and the equal pair are refused while a threshold one
    step above the floor is accepted.

    "`auto_merge_threshold`, defaulting to 0.92, is the confidence at or above which a link is confirmed on the spot without a human ever seeing it, and it must be **strictly greater** than `review_floor` — equality is refused with `ERR_INVALID_THRESHOLD_ORDER`, because a rule whose two thresholds coincide would have no review band at all."
    "A new rule is `ENABLED` with `confirmed_count` and `rejected_count` at 0 and `precision_estimate` at 1.0."
    "There is exactly one deliberate exception to the rule that an error response leaves state untouched, and it is described in §3.2: the requeue attempt that exhausts a batch's retry budget both fails and advances the batch to `REJECTED`."

    Design: Corner/errors/match_rule_with_auto_merge_below_review_floor_rejected
    """
    validate_error(
        api.create_match_rule(
            f.probabilistic_rule_payload(review_floor=0.80, auto_merge_threshold=0.60),
            ADMIN,
        ),
        ERR_INVALID_THRESHOLD_ORDER,
        422,
    )
    validate_error(
        api.create_match_rule(
            f.probabilistic_rule_payload(review_floor=0.80, auto_merge_threshold=0.80),
            ADMIN,
        ),
        ERR_INVALID_THRESHOLD_ORDER,
        422,
    )

    stored, meta = validate_paginated(api.list_match_rules(ADMIN))
    assert meta["total_count"] == 0
    assert stored == []

    accepted = get_success_data(
        api.create_match_rule(
            f.probabilistic_rule_payload(review_floor=0.80, auto_merge_threshold=0.81),
            ADMIN,
        ),
        201,
    )
    assert accepted["review_floor"] == approx4(0.80)
    assert accepted["auto_merge_threshold"] == approx4(0.81)
    assert accepted["status"] == "ENABLED"


def test_deterministic_rule_without_key_rejected(api):
    """The two rule kinds have opposite requirements on the deterministic key, so
    a deterministic rule with a null key and a probabilistic rule that supplies
    one are both refused, while a deterministic rule naming a key is accepted.

    "The two kinds have complementary shape requirements on `deterministic_key`, which must name one of `EMAIL_NORM`, `PHONE_NORM` or `LOYALTY_NUMBER` when the kind is deterministic and must be null when it is probabilistic; either mismatch — a deterministic rule with no key, or a probabilistic rule that supplies one — is refused with `ERR_DETERMINISTIC_KEY_MISMATCH`."
    "There is exactly one deliberate exception to the rule that an error response leaves state untouched, and it is described in §3.2: the requeue attempt that exhausts a batch's retry budget both fails and advances the batch to `REJECTED`."

    Design: Corner/errors/deterministic_rule_without_key_rejected
    """
    validate_error(
        api.create_match_rule(
            f.deterministic_rule_payload(deterministic_key=None), ADMIN
        ),
        ERR_DETERMINISTIC_KEY_MISMATCH,
        422,
    )
    validate_error(
        api.create_match_rule(
            f.probabilistic_rule_payload(deterministic_key="EMAIL_NORM"), ADMIN
        ),
        ERR_DETERMINISTIC_KEY_MISMATCH,
        422,
    )

    stored, meta = validate_paginated(api.list_match_rules(ADMIN))
    assert meta["total_count"] == 0
    assert stored == []

    accepted = get_success_data(
        api.create_match_rule(f.deterministic_rule_payload("PHONE_NORM"), ADMIN), 201
    )
    assert accepted["rule_kind"] == "DETERMINISTIC"
    assert accepted["deterministic_key"] == "PHONE_NORM"


def test_identity_link_with_same_profile_on_both_sides_rejected(api):
    """Naming one profile as both endpoints of a candidate link is refused, and
    neither the profile nor the minting rule is touched.

    "The two endpoints must differ: naming the same profile twice is `ERR_SELF_LINK_FORBIDDEN`."
    "There is exactly one deliberate exception to the rule that an error response leaves state untouched, and it is described in §3.2: the requeue attempt that exhausts a batch's retry budget both fails and advances the batch to `REJECTED`."

    Design: Corner/errors/identity_link_with_same_profile_on_both_sides_rejected
    """
    env = fx.single_profile(api)
    rule = fx.declare_probabilistic_rule(api)
    profile_id = env["profile"]["id"]

    validate_error(
        api.create_identity_link(
            f.identity_link_payload(
                profile_id, profile_id, rule["id"], f.evidence(1.0, 1.0, 1.0, 1.0)
            ),
            STEWARD,
        ),
        ERR_SELF_LINK_FORBIDDEN,
        422,
    )

    stored, meta = validate_paginated(api.list_identity_links(ADMIN))
    assert meta["total_count"] == 0
    assert stored == []

    assert fx.reread_profile(api, profile_id)["version"] == env["profile"]["version"]
    unchanged_rule = fx.reread_rule(api, rule["id"])
    assert unchanged_rule["status"] == "ENABLED"
    assert unchanged_rule["confirmed_count"] == 0
    assert unchanged_rule["rejected_count"] == 0


def test_overlap_with_same_segment_id_rejected(api):
    """Asking for a segment's overlap with itself is refused, while the same read
    against a genuinely different segment answers with all seven figures.

    "Both segments' member sets are computed at read time, and the other segment is named by the `other_segment_id` query parameter, which must differ from the segment being read — naming the same segment twice is `ERR_OVERLAP_SAME_SEGMENT`, since a segment's overlap with itself is trivially total."
    "The read reports `segment_member_count` and `other_segment_member_count` as the two set sizes, `overlap_count` as the number of profiles in both, and `union_count` as the two sizes added together less the overlap."
    "Three ratios follow, each rounded half up to four decimal places: `jaccard_index` is the overlap divided by the union, or exactly 0.0000 where the union is empty; `containment_in_other` is the overlap divided by this segment's own size, or exactly 0.0000 where this segment is empty; and `containment_of_other` is the overlap divided by the other segment's size, or exactly 0.0000 where the other segment is empty."
    "A resource that is only *read* is never mutated: computed reads such as the per-channel consent projection, the segment performance report and the audience overlap report derive their output at read time and increment nothing."

    Design: Corner/errors/overlap_with_same_segment_id_rejected
    """
    segment = fx.draft_segment(api, list(f.POSTAL_10001), name="Postal Audience")

    validate_error(
        api.get_segment_overlap(
            segment["id"], ANALYST, {"other_segment_id": segment["id"]}
        ),
        ERR_OVERLAP_SAME_SEGMENT,
        422,
    )

    other = fx.draft_segment(
        api, [f.criterion("loyalty_tier", "EQ", "GOLD")], name="Gold Audience"
    )
    report = get_success_data(
        api.get_segment_overlap(
            segment["id"], ANALYST, {"other_segment_id": other["id"]}
        ),
        200,
    )
    assert report["segment_id"] == segment["id"]
    assert report["other_segment_id"] == other["id"]
    assert report["segment_member_count"] == 0
    assert report["other_segment_member_count"] == 0
    assert report["overlap_count"] == 0
    assert report["union_count"] == 0
    assert report["jaccard_index"] == approx4(0.0)
    assert report["containment_in_other"] == approx4(0.0)
    assert report["containment_of_other"] == approx4(0.0)

    assert fx.reread_segment(api, segment["id"])["version"] == segment["version"]


def test_suppression_window_end_before_start_rejected(api):
    """A suppression window that ends before it starts, or that ends at the very
    instant it starts, is refused, while a window whose end is strictly later is
    stored.

    "Only a `PrivacyOfficer` may add one, naming the subject with `profile_id`, an `entry_type`, a `reason_code` of one to forty characters after trimming, an `effective_at` that starts the window inclusively, and an optional `expires_at` that ends it exclusively and that must be strictly after `effective_at` when supplied."
    "Rungs 43 through 47 are temporal: (43) `ERR_INVALID_WINDOW`; (44) `ERR_FUTURE_CAPTURED_AT`; (45) `ERR_SUPPRESSION_WINDOW_OVERLAP`; (46) `ERR_ACTIVATION_COOLDOWN_VIOLATION`; (47) `ERR_ACTIVATION_CONCURRENCY_EXCEEDED`."
    "There is exactly one deliberate exception to the rule that an error response leaves state untouched, and it is described in §3.2: the requeue attempt that exhausts a batch's retry budget both fails and advances the batch to `REJECTED`."

    Design: Corner/errors/suppression_window_end_before_start_rejected
    """
    env = fx.single_profile(api)
    profile_id = env["profile"]["id"]

    validate_error(
        api.create_suppression_entry(
            f.suppression_entry_payload(
                profile_id,
                effective_at="2026-08-10T00:00:00Z",
                expires_at="2026-08-05T00:00:00Z",
            ),
            PRIVACY,
        ),
        ERR_INVALID_WINDOW,
        422,
    )
    validate_error(
        api.create_suppression_entry(
            f.suppression_entry_payload(
                profile_id,
                effective_at="2026-08-10T00:00:00Z",
                expires_at="2026-08-10T00:00:00Z",
            ),
            PRIVACY,
        ),
        ERR_INVALID_WINDOW,
        422,
    )

    stored, meta = validate_paginated(
        api.list_suppression_entries(ADMIN, {"profile_id": profile_id})
    )
    assert meta["total_count"] == 0
    assert stored == []
    assert fx.reread_profile(api, profile_id)["version"] == env["profile"]["version"]

    accepted = get_success_data(
        api.create_suppression_entry(
            f.suppression_entry_payload(
                profile_id,
                effective_at="2026-08-10T00:00:00Z",
                expires_at="2026-08-11T00:00:00Z",
            ),
            PRIVACY,
        ),
        201,
    )
    assert accepted["status"] == "ACTIVE"
    assert_instant_equals(
        accepted["effective_at"], "2026-08-10T00:00:00Z", "effective_at"
    )
    assert_instant_equals(accepted["expires_at"], "2026-08-11T00:00:00Z", "expires_at")


def test_consent_captured_in_the_future_rejected(api):
    """An election dated one second past the logical clock is refused, while the
    same election dated exactly at the clock is stored as the group's winner.

    "It also carries `captured_at`, the instant the subject actually decided, which may not lie in the future — a `captured_at` after the logical clock now is refused with `ERR_FUTURE_CAPTURED_AT` — and an optional `expires_at` at which the election lapses, which must be strictly after `captured_at` when supplied (`ERR_INVALID_WINDOW`) and which being null means the election never lapses."
    "Before any operator sets it, the logical clock reads exactly `2026-08-01T00:00:00Z`; the server must not fall back to real time."
    "`precedence_rank` records that position as a one-based index."
    "Rank one is the winner and is the **only** election in its group whose `status` is `ACTIVE`; every lower-ranked sibling carries rank two, three and so on with `status` of `SUPERSEDED`, each such displacement moving that record `ACTIVE` → `SUPERSEDED` and incrementing its `version`."

    Design: Corner/errors/consent_captured_in_the_future_rejected
    """
    env = fx.single_profile(api)
    profile = fx.reread_profile(api, env["profile"]["id"])
    feed_id = env["feed"]["id"]

    validate_error(
        api.create_consent_record(
            f.consent_record_payload(
                profile["id"],
                feed_id,
                profile["version"],
                captured_at="2026-08-01T00:00:01Z",
            ),
            PRIVACY,
        ),
        ERR_FUTURE_CAPTURED_AT,
        422,
    )

    stored, meta = validate_paginated(
        api.list_consent_records(ADMIN, {"profile_id": profile["id"]})
    )
    assert meta["total_count"] == 0
    assert stored == []

    accepted = get_success_data(
        api.create_consent_record(
            f.consent_record_payload(
                profile["id"], feed_id, profile["version"], captured_at=DEFAULT_CLOCK
            ),
            PRIVACY,
        ),
        201,
    )
    assert accepted["status"] == "ACTIVE"
    assert accepted["precedence_rank"] == 1
    assert_instant_equals(accepted["captured_at"], DEFAULT_CLOCK, "captured_at")


def test_sensitive_segment_submit_without_justification_rejected(api):
    """A segment built on a sensitive attribute derives that flag itself, and
    submitting it with no written case is refused, leaving it in DRAFT with no
    submitter recorded.

    "`uses_sensitive_attributes` is **derived, never supplied**: it is true when any criterion's `attribute` is one of the three sensitive attributes `inferred_health_interest`, `inferred_ethnicity_affinity` or `precise_geolocation_grid`, and a client value for it is not accepted."
    "Where `uses_sensitive_attributes` is true, submission additionally requires `governance_justification` to be non-null and at least ten characters after trimming; a missing or too-short justification is refused with `ERR_GOVERNANCE_JUSTIFICATION_REQUIRED`."
    "A new segment is `DRAFT` with `sensitive_use_approved` false, `rejection_count` at 0, and its `member_count` computed immediately."
    "There is exactly one deliberate exception to the rule that an error response leaves state untouched, and it is described in §3.2: the requeue attempt that exhausts a batch's retry budget both fails and advances the batch to `REJECTED`."

    Design: Corner/errors/sensitive_segment_submit_without_justification_rejected
    """
    segment = fx.draft_segment(
        api,
        [f.criterion("inferred_health_interest", "EQ", "DIABETES_CARE")],
        name="Diabetes Care Audience",
    )
    assert segment["uses_sensitive_attributes"] is True
    assert segment["governance_justification"] is None
    assert segment["status"] == "DRAFT"

    validate_error(
        api.submit_segment_for_review(segment["id"], ANALYST),
        ERR_GOVERNANCE_JUSTIFICATION_REQUIRED,
        422,
    )

    after = fx.reread_segment(api, segment["id"])
    assert after["status"] == "DRAFT"
    assert after["submitted_by_user_id"] is None
    assert after["sensitive_use_approved"] is False
    assert after["rejection_count"] == 0
    assert after["version"] == segment["version"]


def test_consent_capture_on_merged_away_profile_rejected(api):
    """Perfect evidence on the two components the pair actually has confirms the
    link on the spot under the renormalising policy, and the profile it merged
    away can no longer be given an election while the survivor still can.

    "Under `RENORMALIZE` the denominator shrinks to the summed weight of the present components only, so a pair that matches perfectly on everything it has scores 1.0000 even with two of the four components missing; where that summed present weight is 0 — every component absent — the confidence is exactly 0.0000 rather than an undefined division."
    "At or above `auto_merge_threshold` the link is created and immediately advanced `PROPOSED` → `CONFIRMED` with `decided_by_user_id` set to the literal string `system` rather than to any header value, `decided_at` stamped at the logical clock now, and the full merge run inside the creating call — the platform's only machine-authored merge."
    "Survivorship is decided by three discriminators applied in order, the first that separates the pair winning outright: the higher `source_record_count`; then the higher `trust_tier` of the feed named by the profile's `primary_source_system_id`; then the earlier `created_at`."
    "The loser is then torn down: its `resolution_status` moves `RESOLVED` → `MERGED_AWAY`, its `merged_into_profile_id` names the survivor, its `household_id` is cleared because household membership follows the surviving identity, its `lifetime_value_cents` is set to 0 because the value moved rather than duplicated, and its `activatable_channels` becomes empty."
    "Capture is guarded by the parent-version check of §2.6 through `expected_profile_version`, refuses a `MERGED_AWAY` subject with `ERR_PROFILE_MERGED_AWAY`, refuses a `DELETED` subject with `ERR_PROFILE_DELETED`, and refuses a capture point whose feed is `QUARANTINED` with `ERR_SOURCE_SYSTEM_QUARANTINED`."

    Design: Corner/errors/consent_capture_on_merged_away_profile_rejected
    """
    feed = fx.register_feed(api, code="ER_MERGED", trust_tier=3)

    earlier_batch = fx.submit_batch(
        api,
        feed["id"],
        [
            f.raw_record(
                "MG1",
                first_name="Ada",
                last_name="Alpha",
                postal_code="10001",
                event_timestamp="2026-07-30T10:00:00Z",
            )
        ],
    )
    fx.validate(api, earlier_batch["id"])
    fx.promote(api, earlier_batch["id"])
    survivor_id = fx.batch_profiles(api, earlier_batch["id"])[0]["id"]

    fx.set_clock(api, "2026-08-01T01:00:00Z")
    later_batch = fx.submit_batch(
        api,
        feed["id"],
        [
            f.raw_record(
                "MG2",
                phone_raw=None,
                first_name="Ada",
                last_name="Alpha",
                postal_code="10001",
                address_line="9 Cedar Court",
                event_timestamp="2026-07-30T11:00:00Z",
            )
        ],
    )
    fx.validate(api, later_batch["id"])
    fx.promote(api, later_batch["id"])
    loser_id = fx.batch_profiles(api, later_batch["id"])[0]["id"]
    assert loser_id != survivor_id

    rule = fx.declare_probabilistic_rule(
        api, missing_identifier_policy="RENORMALIZE", review_floor=0.65, auto_merge_threshold=0.92
    )
    link = fx.proposed_link(
        api, survivor_id, loser_id, rule["id"], f.evidence(1.0, None, 1.0, None)
    )
    assert link["confidence"] == approx4(1.0)
    assert link["status"] == "CONFIRMED"
    assert link["decided_by_user_id"] == "system"
    assert link["survivor_profile_id"] == survivor_id

    loser = fx.reread_profile(api, loser_id)
    assert_profile_axes(loser, "MERGED_AWAY", "NORMAL")
    assert loser["merged_into_profile_id"] == survivor_id

    validate_error(
        api.create_consent_record(
            f.consent_record_payload(
                loser_id,
                feed["id"],
                loser["version"],
                captured_at="2026-08-01T01:00:00Z",
            ),
            PRIVACY,
        ),
        ERR_PROFILE_MERGED_AWAY,
        409,
    )

    refused, refused_meta = validate_paginated(
        api.list_consent_records(ADMIN, {"profile_id": loser_id})
    )
    assert refused_meta["total_count"] == 0
    assert refused == []

    survivor = fx.reread_profile(api, survivor_id)
    accepted = get_success_data(
        api.create_consent_record(
            f.consent_record_payload(
                survivor_id,
                feed["id"],
                survivor["version"],
                captured_at="2026-08-01T01:00:00Z",
            ),
            PRIVACY,
        ),
        201,
    )
    assert accepted["profile_id"] == survivor_id
    assert accepted["status"] == "ACTIVE"
    assert accepted["precedence_rank"] == 1


def test_ingest_batch_against_quarantined_source_rejected(api):
    """Five records, three of them scoring below the record minimum, validate the
    batch itself but drive the feed under its own completeness floor, after which
    the feed accepts no new batch until an admin reinstates it.

    "Under `WEIGHTED_COMPONENTS`, the score is the sum of the weights of the passing components, over a weight base that is always the full 1.00: an email that passes contributes 0.30, a phone 0.20, a loyalty number 0.20, a name pair 0.15 and a postal code 0.15 — the five weights summing to exactly 1.00, so email is worth twice postal code — and failing is again indistinguishable from being absent."
    "Where the computed `dq_score` is at least the feed's `pii_completeness_floor` — inclusive at equality — the batch moves `RECEIVED` → `VALIDATED` and `validated_at` is stamped at the logical clock now."
    "A feed is driven to `QUARANTINED` when, after a recomputation, its `submitted_record_total` has reached at least five records **and** its `dq_pass_rate` is strictly below its own `pii_completeness_floor`."
    "While a feed is `QUARANTINED` it accepts nothing: submitting a new batch against it, validating one of its batches, promoting one of its batches, or capturing a consent election that names it as the capture point all fail with `ERR_SOURCE_SYSTEM_QUARANTINED`."
    "Reinstatement requires the feed to be `QUARANTINED`, moves it `QUARANTINED` → `ACTIVE`, stamps `last_reinstated_at` at the logical clock now, and — critically — **resets the quality baseline** by setting `dq_window_start_at` to the logical clock now as well."
    "Because the window now starts in the present, the in-window batch set is empty, so `submitted_record_total` and `valid_record_total` fall back to 0 and `dq_pass_rate` returns to 1.0."

    Design: Corner/errors/ingest_batch_against_quarantined_source_rejected
    """
    feed = fx.register_feed(api, code="ER_QUARANTINE")

    records = [f.raw_record("QR1"), f.raw_record("QR2")]
    for index in range(3, 6):
        records.append(f.raw_record(f"QR{index}", email_raw=None, postal_code=None))

    batch = fx.submit_batch(api, feed["id"], records)
    validated = fx.validate(api, batch["id"])
    assert validated["status"] == "VALIDATED"
    assert validated["dq_score"] == approx4(0.73)
    assert validated["valid_record_count"] == 2
    assert validated["invalid_record_count"] == 3

    quarantined = fx.reread_feed(api, feed["id"])
    assert quarantined["status"] == "QUARANTINED"
    assert quarantined["submitted_record_total"] == 5
    assert quarantined["valid_record_total"] == 2
    assert quarantined["dq_pass_rate"] == approx4(0.4)
    assert quarantined["quarantine_count"] == 1

    blocked_payload = f.ingest_batch_payload(feed["id"], [f.raw_record("QR6")])
    validate_error(
        api.create_ingest_batch(blocked_payload, ENGINEER),
        ERR_SOURCE_SYSTEM_QUARANTINED,
        409,
    )

    stored, meta = validate_paginated(
        api.list_ingest_batches(ADMIN, {"source_system_id": feed["id"]})
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in stored] == [batch["id"]]

    # The window reset is only observable once the clock has left the instant the
    # counted batch was created at: an in-window batch is one "whose `created_at`
    # is at or after `dq_window_start_at`", so the reset has to land strictly
    # later than the batch for the in-window set to be the empty one the PRD
    # describes.
    reinstate_clock = "2026-08-03T00:00:00Z"
    fx.set_clock(api, reinstate_clock)

    reinstated = get_success_data(api.reinstate_source_system(feed["id"], ADMIN), 200)
    assert reinstated["status"] == "ACTIVE"
    assert reinstated["submitted_record_total"] == 0
    assert reinstated["valid_record_total"] == 0
    assert reinstated["dq_pass_rate"] == approx4(1.0)
    assert reinstated["quarantine_count"] == 1
    assert_instant_equals(
        reinstated["last_reinstated_at"], reinstate_clock, "last_reinstated_at"
    )
    assert_instant_equals(
        reinstated["dq_window_start_at"], reinstate_clock, "dq_window_start_at"
    )

    accepted = get_success_data(api.create_ingest_batch(blocked_payload, ENGINEER), 201)
    assert accepted["source_system_id"] == feed["id"]
    assert accepted["status"] == "RECEIVED"
    assert accepted["record_count"] == 1


def test_identity_link_with_disabled_match_rule_rejected(api):
    """A single rejection drops the rule's precision below its own floor and
    disables it, after which the rule can no longer mint a link at all.

    "Instead the rule's `rejected_count` increases by 1 and `precision_estimate` is recomputed as `confirmed_count` divided by the sum of `confirmed_count` and `rejected_count`, rounded half up to four decimal places, and held at exactly 1.0 while that denominator is 0."
    "Where the recomputed estimate falls strictly below the rule's own `min_precision`, hop two moves the rule `ENABLED` → `DISABLED`, and hop three voids every **other** link minted by that rule whose status is still `PROPOSED`, each with `void_reason` of `RULE_DISABLED`."
    "A rule whose `status` has fallen to `DISABLED` cannot mint anything, which is `ERR_MATCH_RULE_DISABLED`, and neither endpoint may be `MERGED_AWAY` (`ERR_PROFILE_MERGED_AWAY`) or `DELETED` (`ERR_PROFILE_DELETED`)."
    "Under `STRICT_ZERO` the confidence **is** the raw score, measured against the full weight base of 1.00; an absent component therefore contributes nothing and permanently caps what a sparse pair can score, no matter how perfect the evidence it does have."

    Design: Corner/errors/identity_link_with_disabled_match_rule_rejected
    """
    records = [
        f.raw_record("DR1", event_timestamp="2026-07-20T09:00:00Z"),
        f.raw_record(
            "DR2", email_raw="beta@example.com", event_timestamp="2026-07-20T10:00:00Z"
        ),
        f.raw_record(
            "DR3", email_raw="gamma@example.com", event_timestamp="2026-07-20T11:00:00Z"
        ),
    ]
    env = fx.promoted_batch(api, records, feed_overrides={"code": "ER_DISABLED"})
    profiles = env["profiles"]
    assert len(profiles) == 3

    rule = fx.declare_probabilistic_rule(
        api,
        code="ER_DIS_RULE",
        missing_identifier_policy="STRICT_ZERO",
        review_floor=0.65,
        auto_merge_threshold=0.92,
        min_precision=0.80,
    )
    assert rule["status"] == "ENABLED"
    assert rule["precision_estimate"] == approx4(1.0)

    link = fx.proposed_link(
        api,
        profiles[0]["id"],
        profiles[1]["id"],
        rule["id"],
        f.evidence(1.0, 0.5, 1.0, None),
    )
    assert link["status"] == "PROPOSED"
    assert link["confidence"] == approx4(0.725)

    fx.decide_link(api, link["id"], "REJECT")

    disabled = fx.reread_rule(api, rule["id"])
    assert disabled["status"] == "DISABLED"
    assert disabled["confirmed_count"] == 0
    assert disabled["rejected_count"] == 1
    assert disabled["precision_estimate"] == approx4(0.0)

    blocked = api.create_identity_link(
        f.identity_link_payload(
            profiles[0]["id"],
            profiles[2]["id"],
            rule["id"],
            f.evidence(1.0, 1.0, 1.0, 1.0),
        ),
        STEWARD,
    )
    validate_error(blocked, ERR_MATCH_RULE_DISABLED, 409)

    links, meta = validate_paginated(api.list_identity_links(STEWARD))
    assert meta["total_count"] == 1
    assert [row["id"] for row in links] == [link["id"]]


def test_activation_create_on_inactive_destination_rejected(api):
    """An activation may not be created against a destination that is switched off,
    and the refusal leaves the parent segment's version where it was.

    "A destination's `status` is `ACTIVE` or `INACTIVE`, defaulting to active; an inactive destination refuses activation creation, dispatch and resume with `ERR_DESTINATION_INACTIVE` and is skipped entirely by erasure fan-out."
    "Creation also refuses an inactive destination, and refuses a sensitive audience that either the segment or the destination has not cleared, with `ERR_SENSITIVE_ATTRIBUTE_NOT_PERMITTED`."
    "A new activation is `DRAFT` with every audience and match-rate field at its default, and the parent segment's `version` increments by 1."

    Design: Corner/errors/activation_create_on_inactive_destination_rejected
    """
    destination = fx.register_destination(api, code="ER_INACTIVE", status="INACTIVE")
    assert destination["status"] == "INACTIVE"

    segment = fx.approved_segment(api, list(f.POSTAL_10001))
    assert segment["status"] == "APPROVED"
    version_before = segment["version"]

    refused = api.create_activation(
        f.activation_payload(
            segment["id"],
            destination["id"],
            segment["version"],
            "2026-08-05T00:00:00Z",
            "2026-08-05T02:00:00Z",
        ),
        ANALYST,
    )
    validate_error(refused, ERR_DESTINATION_INACTIVE, 409)

    after = fx.reread_segment(api, segment["id"])
    assert after["version"] == version_before
    assert after["active_activation_count"] == 0

    rows, meta = validate_paginated(api.list_activations(ANALYST))
    assert meta["total_count"] == 0
    assert rows == []


def test_consent_capture_on_deleted_profile_rejected(api):
    """An erasure with no downstream platform to notify completes in its own
    propagate call, and the tombstoned subject then refuses a consent election.

    "Where **zero** destinations qualify, there is nothing downstream to verify and the erasure completes inside the propagate call itself: `total_vendor_task_count` stays 0, the request moves `RECEIVED` → `VERIFIED`, `verified_at` is stamped, and the subject is tombstoned immediately."
    "Reaching `VERIFIED` tombstones the subject, moving it `DELETION_PENDING` → `DELETED`."
    "Seven fields are nulled: `email_norm`, `phone_norm`, `first_name`, `last_name`, `inferred_health_interest`, `inferred_ethnicity_affinity` and `precise_geolocation_grid`."
    "Capture is guarded by the parent-version check of §2.6 through `expected_profile_version`, refuses a `MERGED_AWAY` subject with `ERR_PROFILE_MERGED_AWAY`, refuses a `DELETED` subject with `ERR_PROFILE_DELETED`, and refuses a capture point whose feed is `QUARANTINED` with `ERR_SOURCE_SYSTEM_QUARANTINED`."
    "The subject's `resolution_status` is left entirely untouched — the two axes are independent, and a deleted profile remembers whether it was ever resolved."

    Design: Corner/errors/consent_capture_on_deleted_profile_rejected
    """
    env = fx.verified_erasure(api)
    request = env["request"]
    assert request["status"] == "VERIFIED"
    assert request["total_vendor_task_count"] == 0
    assert_instant_equals(request["verified_at"], DEFAULT_CLOCK, "verified_at")

    subject = env["profile"]
    assert_profile_axes(subject, "RESOLVED", "DELETED")
    assert_tombstoned_identifiers(subject)

    payload = f.consent_record_payload(
        subject["id"], env["feed"]["id"], subject["version"]
    )
    validate_error(api.create_consent_record(payload, PRIVACY), ERR_PROFILE_DELETED, 409)

    records, meta = validate_paginated(
        api.list_consent_records(PRIVACY, {"profile_id": subject["id"]})
    )
    for row in records:
        assert row["status"] == "TOMBSTONED"
        assert row["precedence_rank"] == 0
    assert meta["total_count"] == len(records)

    after = fx.reread_profile(api, subject["id"])
    assert after["version"] == subject["version"]
    assert_profile_axes(after, "RESOLVED", "DELETED")


def test_second_link_over_same_profile_pair_rejected(api):
    """The same unordered pair may hold only one live candidate link, in either
    direction, and the pair reopens once the first link has been decided.

    "The pair must be unjoined: where any existing link in `PROPOSED` or `CONFIRMED` status already joins the same unordered pair — in either direction, since the link is symmetric — the proposal is refused with `ERR_DUPLICATE_IDENTITY_LINK`."
    "Under `STRICT_ZERO` the confidence **is** the raw score, measured against the full weight base of 1.00; an absent component therefore contributes nothing and permanently caps what a sparse pair can score, no matter how perfect the evidence it does have."
    "At or above `review_floor` but below `auto_merge_threshold`, the link is created as `PROPOSED` and waits for a steward."
    "No profile is mutated: `survivor_profile_id` stays null and both profiles keep `resolution_status` of `RESOLVED`."

    Design: Corner/errors/second_link_over_same_profile_pair_rejected
    """
    env = fx.two_profiles(
        api,
        feed_overrides={"code": "ER_DUPLINK"},
        right_overrides={"email_raw": "delta@example.com"},
    )
    left, right = env["left"], env["right"]

    rule = fx.declare_probabilistic_rule(
        api,
        code="ER_DUP_RULE",
        missing_identifier_policy="STRICT_ZERO",
        review_floor=0.65,
        auto_merge_threshold=0.92,
        min_precision=0.0,
    )

    first = fx.proposed_link(
        api, left["id"], right["id"], rule["id"], f.evidence(1.0, 0.5, 1.0, None)
    )
    assert first["status"] == "PROPOSED"
    assert first["confidence"] == approx4(0.725)

    swapped = f.identity_link_payload(
        right["id"], left["id"], rule["id"], f.evidence(1.0, 0.5, 1.0, None)
    )
    validate_error(
        api.create_identity_link(swapped, STEWARD), ERR_DUPLICATE_IDENTITY_LINK, 409
    )

    links, meta = validate_paginated(api.list_identity_links(STEWARD))
    assert meta["total_count"] == 1
    assert [row["id"] for row in links] == [first["id"]]

    rejected = fx.decide_link(api, first["id"], "REJECT")
    assert rejected["status"] == "REJECTED"
    assert rejected["survivor_profile_id"] is None

    still_enabled = fx.reread_rule(api, rule["id"])
    assert still_enabled["status"] == "ENABLED"
    assert still_enabled["rejected_count"] == 1
    assert still_enabled["precision_estimate"] == approx4(0.0)

    reopened = get_success_data(
        api.create_identity_link(
            f.identity_link_payload(
                right["id"], left["id"], rule["id"], f.evidence(1.0, 1.0, 1.0, None)
            ),
            STEWARD,
        ),
        201,
    )
    assert reopened["status"] == "PROPOSED"
    assert reopened["confidence"] == approx4(0.85)
    assert reopened["left_profile_id"] == right["id"]
    assert reopened["right_profile_id"] == left["id"]


def test_match_report_exceeding_dispatched_hash_count_rejected(api):
    """A report claiming more matched and unusable hashes together than the
    dispatch ever sent is refused before any rate is derived.

    "Report validity is checked **before** any rate is computed: the sum of `vendor_matched_count` and `unusable_hash_count` may not exceed the `dispatched_hash_count` fixed at dispatch, an inflated report being `ERR_MATCH_REPORT_EXCEEDS_DISPATCH`."
    "`dispatched_hash_count` is the number of audience members whose required identifier, selected by the destination's `hashing_algorithm`, is non-null."
    "On success the activation moves `DRAFT` → `DISPATCHED`, `dispatched_at` is stamped at the logical clock now, the destination's `remaining_daily_hash_quota` decreases by `dispatched_hash_count`, the segment's `active_activation_count` increases by 1, and the activation's, the destination's and the segment's `version` each increment by 1."
    "A new activation is `DRAFT` with every audience and match-rate field at its default, and the parent segment's `version` increments by 1."

    Design: Corner/errors/match_report_exceeding_dispatched_hash_count_rejected
    """
    env = fx.delivering_activation_environment(
        api, 1, destination_overrides={"daily_hash_quota": 300}
    )
    activation = env["activation"]
    destination = env["destination"]
    assert activation["status"] == "DISPATCHED"
    assert activation["dispatched_hash_count"] == 1
    assert destination["remaining_daily_hash_quota"] == 299

    refused = api.report_match(
        activation["id"],
        f.match_report_payload(1, 1),
        make_destination_platform_headers(destination["id"]),
    )
    validate_error(refused, ERR_MATCH_REPORT_EXCEEDS_DISPATCH, 422)

    after = fx.reread_activation(api, activation["id"])
    assert after["status"] == "DISPATCHED"
    assert after["vendor_matched_count"] == 0
    assert after["unusable_hash_count"] == 0
    assert after["gross_match_rate"] is None
    assert after["net_match_rate"] is None
    assert after["effective_match_rate"] is None
    assert after["version"] == activation["version"]

    destination_after = fx.reread_destination(api, destination["id"])
    assert destination_after["remaining_daily_hash_quota"] == 299
    assert destination_after["underperforming_activation_count"] == 0


def test_household_assignment_with_mismatched_address_hash_rejected(api):
    """A steward may not move a profile into a bucket that belongs to a different
    postal address, and the refusal leaves both buckets untouched.

    "The target household's `status` must be `ACTIVE` **and** its `address_hash` must equal the profile's own `address_hash`; either failure — a dissolved bucket, or a bucket at a different address — is `ERR_INVALID_HOUSEHOLD_STATE`."
    "Note the ordering of those two guards: state is judged before capacity, so a dissolved household that is also full reports the state error."
    "Its grouping key is `address_hash`, minted by promotion when the first profile at that address appears, and its `sequence_no` is the overflow index at that address: the first household there is 1, the next 2, and so on."

    Design: Corner/errors/household_assignment_with_mismatched_address_hash_rejected
    """
    records = [
        f.raw_record(
            "HM01", address_line="11 Elm Road", event_timestamp="2026-07-28T10:00:00Z"
        ),
        f.raw_record(
            "HM02", address_line="27 Fir Avenue", event_timestamp="2026-07-28T11:00:00Z"
        ),
    ]
    env = fx.promoted_batch(api, records, feed_overrides={"code": "ER_HH_MISMATCH"})
    profiles = env["profiles"]
    assert len(profiles) == 2

    first, second = profiles[0], profiles[1]
    elm_bucket_id = first["household_id"]
    fir_bucket_id = second["household_id"]
    assert elm_bucket_id is not None
    assert fir_bucket_id is not None
    assert elm_bucket_id != fir_bucket_id

    elm_before = fx.reread_household(api, elm_bucket_id)
    fir_before = fx.reread_household(api, fir_bucket_id)
    assert elm_before["address_hash"] != fir_before["address_hash"]
    assert elm_before["member_count"] == 1
    assert fir_before["member_count"] == 1
    assert elm_before["sequence_no"] == 1
    assert fir_before["sequence_no"] == 1
    assert elm_before["status"] == "ACTIVE"

    refused = api.assign_household(
        second["id"], f.household_assignment_payload(elm_bucket_id), STEWARD
    )
    validate_error(refused, ERR_INVALID_HOUSEHOLD_STATE, 409)

    assert fx.reread_profile(api, second["id"])["household_id"] == fir_bucket_id
    assert fx.reread_profile(api, second["id"])["version"] == second["version"]

    elm_after = fx.reread_household(api, elm_bucket_id)
    fir_after = fx.reread_household(api, fir_bucket_id)
    assert elm_after["member_count"] == 1
    assert elm_after["version"] == elm_before["version"]
    assert fir_after["member_count"] == 1
    assert fir_after["version"] == fir_before["version"]


def test_household_assignment_beyond_capacity_rejected(api):
    """The seventh profile at an address cannot be forced back into the full first
    bucket, whose capacity is judged as it stands before the assignment.

    "A household holds at most six members."
    "The target's `member_count` must be strictly below six **before** the assignment, a full bucket being refused with `ERR_HOUSEHOLD_CAPACITY_EXCEEDED`."
    "The consequence is a strictly ordered overflow: the sixth profile to arrive at an address still joins bucket 1, and the seventh opens bucket 2."
    "Where no bucket has room, a new household is minted at that address whose `sequence_no` is one greater than the highest `sequence_no` among **all** households at that address — including `DISSOLVED` ones, so a dissolved bucket's index is retired and never re-issued — and the profile joins it."

    Design: Corner/errors/household_assignment_beyond_capacity_rejected
    """
    stamps = [
        "2026-07-29T09:00:00Z",
        "2026-07-29T09:10:00Z",
        "2026-07-29T09:20:00Z",
        "2026-07-29T09:30:00Z",
        "2026-07-29T09:40:00Z",
        "2026-07-29T09:50:00Z",
        "2026-07-29T10:00:00Z",
    ]
    records = [
        f.raw_record(
            f"HC{index + 1:02d}",
            address_line="14 Grove Street",
            event_timestamp=stamp,
        )
        for index, stamp in enumerate(stamps)
    ]
    env = fx.promoted_batch(api, records, feed_overrides={"code": "ER_HH_FULL"})
    profiles = env["profiles"]
    assert len(profiles) == 7

    first_bucket_id = profiles[0]["household_id"]
    overflow_bucket_id = profiles[6]["household_id"]
    assert first_bucket_id is not None
    assert overflow_bucket_id is not None
    assert first_bucket_id != overflow_bucket_id

    first_before = fx.reread_household(api, first_bucket_id)
    overflow_before = fx.reread_household(api, overflow_bucket_id)
    assert first_before["status"] == "ACTIVE"
    assert first_before["member_count"] == 6
    assert first_before["sequence_no"] == 1
    assert overflow_before["status"] == "ACTIVE"
    assert overflow_before["member_count"] == 1
    assert overflow_before["sequence_no"] == 2
    assert first_before["address_hash"] == overflow_before["address_hash"]

    seventh = profiles[6]
    refused = api.assign_household(
        seventh["id"], f.household_assignment_payload(first_bucket_id), STEWARD
    )
    validate_error(refused, ERR_HOUSEHOLD_CAPACITY_EXCEEDED, 409)

    after_profile = fx.reread_profile(api, seventh["id"])
    assert after_profile["household_id"] == overflow_bucket_id
    assert after_profile["version"] == seventh["version"]

    first_after = fx.reread_household(api, first_bucket_id)
    overflow_after = fx.reread_household(api, overflow_bucket_id)
    assert first_after["member_count"] == 6
    assert first_after["version"] == first_before["version"]
    assert overflow_after["member_count"] == 1
    assert overflow_after["version"] == overflow_before["version"]
