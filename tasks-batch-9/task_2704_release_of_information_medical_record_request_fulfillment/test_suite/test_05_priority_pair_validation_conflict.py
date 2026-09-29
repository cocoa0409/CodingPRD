"""Two rules violated at once: the pipeline reports only the earlier one."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import api_errors as e
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import ANALYST_1, REVIEWER_1, REVIEWER_2, REVIEWER_AS_ANALYST_1


# --------------------------------------------------------------------------
# release_state_invalid_beats_invoice_unsettled_rejected
# --------------------------------------------------------------------------
def _unpaid_request_in_sensitive_review(api):
    """62 retrieved pages, compilation declared finished, no invoice ever created, so the
    request sits in SENSITIVE_REVIEW with billing_status PENDING_INVOICE."""
    world = fx.third_party_world(api)
    request = fx.open_third_party_request(api, world, certification_requested=True)
    ids = fx.walk_to_sensitive_review(
        api, request["id"], [{"label": "gen", "category": "GENERAL_MEDICAL", "page_count": 62}]
    )
    return {"world": world, "request_id": request["id"], "segment_ids": ids}


def test_the_state_failure_outranks_the_unsettled_invoice_failure(api):
    """From SENSITIVE_REVIEW with nothing paid, the state rule answers first.

    PRD: "A release attempted from any `fulfillment_status` other than `RELEASE_READY` reports `ERR_REQUEST_STATE_INVALID`, and as §2.8 records, that state failure outranks the unsettled-invoice failure when both are present."

    Design: Difficulty/priority_pair_validation_conflict/release_state_invalid_beats_invoice_unsettled_rejected
    """
    scenario = _unpaid_request_in_sensitive_review(api)
    request_id = scenario["request_id"]
    before = fx.read_request(api, request_id)
    assert before["fulfillment_status"] == "SENSITIVE_REVIEW"
    assert before["billing_status"] == "PENDING_INVOICE"

    response = api.release_request(request_id, f.release_payload("attempt from sensitive review"), REVIEWER_2)
    validate_error(response, e.ERR_REQUEST_STATE_INVALID, 409)

    after = fx.read_request(api, request_id)
    assert after["fulfillment_status"] == "SENSITIVE_REVIEW"
    assert after["released_at"] is None
    assert after["release_reviewer_user_id"] is None


def test_the_same_unpaid_request_reports_the_fiscal_failure_once_release_ready(api):
    """Repairing only the state leg exposes the fiscal rule that was live all along.

    PRD: "The request's `billing_status` must be `PAID`, `WAIVED` or `NOT_BILLABLE`; a `billing_status` of `PENDING_INVOICE` or `INVOICED` means the money is still outstanding and the release is refused with `ERR_INVOICE_UNSETTLED` (HTTP 402), because prepayment is required before records leave the building."

    Design: Difficulty/priority_pair_validation_conflict/release_state_invalid_beats_invoice_unsettled_rejected
    """
    scenario = _unpaid_request_in_sensitive_review(api)
    request_id = scenario["request_id"]
    validate_error(
        api.release_request(request_id, f.release_payload("attempt from sensitive review"), REVIEWER_2),
        e.ERR_REQUEST_STATE_INVALID,
        409,
    )

    fx.run_sensitive_review(api, request_id, [])
    ready = fx.read_request(api, request_id)
    assert ready["fulfillment_status"] == "RELEASE_READY"
    assert ready["billing_status"] == "PENDING_INVOICE"
    assert ready["billable_page_count"] == 62

    response = api.release_request(request_id, f.release_payload("still unpaid"), REVIEWER_2)
    validate_error(response, e.ERR_INVOICE_UNSETTLED, 402)

    after = fx.read_request(api, request_id)
    assert after["fulfillment_status"] == "RELEASE_READY"
    assert after["released_at"] is None


def test_neither_rejected_release_writes_a_compliance_event(api):
    """A refused release leaves no evidentiary trace at all.

    PRD: "Compliance events are the system's evidentiary record and are never updated or deleted."

    Design: Difficulty/priority_pair_validation_conflict/release_state_invalid_beats_invoice_unsettled_rejected
    """
    scenario = _unpaid_request_in_sensitive_review(api)
    request_id = scenario["request_id"]

    validate_error(
        api.release_request(request_id, f.release_payload(), REVIEWER_2), e.ERR_REQUEST_STATE_INVALID, 409
    )
    fx.run_sensitive_review(api, request_id, [])
    validate_error(api.release_request(request_id, f.release_payload(), REVIEWER_2), e.ERR_INVOICE_UNSETTLED, 402)

    assert fx.read_events(api, request_id) == []


# --------------------------------------------------------------------------
# unencrypted_delivery_safety_beats_recipient_mismatch_rejected
#
# Rule 23 fires on a `delivery_format` of UNENCRYPTED_EMAIL regardless of the
# `encryption` value, so on a third-party request that format has no compliant
# repair; the lower-priority rule 25 is therefore shown to be live on a
# SECURE_PORTAL request, which is the PRD-derivable way to isolate it.
# --------------------------------------------------------------------------
def _released_request(api, delivery_format):
    world = fx.third_party_world(api)
    scenario = fx.released_third_party_request(
        api, world, 62, delivery_format=delivery_format, certification_requested=True
    )
    return {"world": world, **scenario}


def test_the_unsecured_channel_rule_answers_before_the_designated_recipient_rule(api):
    """Both rules are violated and both sit in the 422 band; only the error_id separates them.

    PRD: "Two safety rules guard the channel, and they are evaluated before the designated-recipient rule."

    Design: Difficulty/priority_pair_validation_conflict/unencrypted_delivery_safety_beats_recipient_mismatch_rejected
    """
    scenario = _released_request(api, "UNENCRYPTED_EMAIL")

    response = api.create_delivery(
        f.delivery_payload(
            scenario["request_id"],
            delivery_format="UNENCRYPTED_EMAIL",
            recipient_endpoint="paralegal@other.example",
            encryption="NONE",
        ),
        REVIEWER_2,
    )
    validate_error(response, e.ERR_UNENCRYPTED_DELIVERY_NOT_DIRECTED, 422)

    listed, meta = fx.list_deliveries_for(api, scenario["request_id"])
    assert listed == []
    assert meta["total_count"] == 0


def test_the_designated_recipient_rule_is_genuinely_live_on_a_secure_channel(api):
    """With the channel safe, the referential rule refuses any other endpoint.

    PRD: "Then the referential rule: on a `THIRD_PARTY_AUTHORIZATION` request the `recipient_endpoint` must exactly equal the governing authorization's `designated_recipient_endpoint`, and any other endpoint is refused with `ERR_RECIPIENT_NOT_DESIGNATED`."

    Design: Difficulty/priority_pair_validation_conflict/unencrypted_delivery_safety_beats_recipient_mismatch_rejected
    """
    scenario = _released_request(api, "SECURE_PORTAL")
    request_id = scenario["request_id"]

    response = api.create_delivery(
        f.delivery_payload(
            request_id,
            delivery_format="SECURE_PORTAL",
            recipient_endpoint="paralegal@other.example",
            encryption="TLS",
        ),
        REVIEWER_2,
    )
    validate_error(response, e.ERR_RECIPIENT_NOT_DESIGNATED, 422)

    accepted = validate_success(
        api.create_delivery(
            f.delivery_payload(
                request_id,
                delivery_format="SECURE_PORTAL",
                recipient_endpoint="counsel@firm.example",
                encryption="TLS",
            ),
            REVIEWER_2,
        ),
        201,
    )
    assert accepted["status"] == "PENDING"
    assert accepted["attempt_count"] == 0

    listed, meta = fx.list_deliveries_for(api, request_id)
    assert len(listed) == 1
    assert meta["total_count"] == 1


def test_the_unencrypted_email_request_is_priced_as_an_electronic_delivery(api):
    """UNENCRYPTED_EMAIL is electronic: no postage line, and the 6500 cap does not bite.

    PRD: "A request delivers electronically when its `delivery_format` is `SECURE_PORTAL`, `DIRECT_MESSAGE` or `UNENCRYPTED_EMAIL`."

    Design: Difficulty/priority_pair_validation_conflict/unencrypted_delivery_safety_beats_recipient_mismatch_rejected
    """
    scenario = _released_request(api, "UNENCRYPTED_EMAIL")
    invoice = fx.read_invoice(api, scenario["invoice_id"])

    assert invoice["subtotal_cents"] == 3651
    assert invoice["applicable_cap_cents"] == 6500
    assert invoice["cap_adjustment_cents"] == 0
    assert invoice["amount_due_cents"] == 3651
    assert "POSTAGE" not in [line["line_type"] for line in fx.read_lines(api, invoice["id"])]


# --------------------------------------------------------------------------
# redaction_segregation_of_duties_beats_segment_state_rejected
# --------------------------------------------------------------------------
def _approved_redaction_applied_by_analyst_one(api):
    """A behavioural-health segment redacted by u-analyst-1 and approved by u-review-1, so
    the request is RELEASE_READY at 57 billable pages."""
    world = fx.third_party_world(
        api,
        scope_categories=["GENERAL_MEDICAL", "BEHAVIORAL_HEALTH"],
        sensitive_categories_authorized=["BEHAVIORAL_HEALTH"],
    )
    request = fx.open_third_party_request(
        api, world, requested_categories=["GENERAL_MEDICAL", "BEHAVIORAL_HEALTH"]
    )
    ids = fx.walk_to_sensitive_review(
        api,
        request["id"],
        [
            {"label": "gen", "category": "GENERAL_MEDICAL", "page_count": 40},
            {"label": "bh", "category": "BEHAVIORAL_HEALTH", "page_count": 22},
        ],
    )
    fx.run_sensitive_review(api, request["id"], [f.include_decision(ids["bh"], redaction_required=True)])
    fx.apply_redaction(api, ids["bh"], 5, headers=ANALYST_1)
    fx.approve_redaction(api, ids["bh"], headers=REVIEWER_1)
    return {"world": world, "request_id": request["id"], "segment_ids": ids}


def test_segregation_of_duties_answers_before_the_segment_state_rule(api):
    """The applying analyst wearing the reviewer role is refused on identity, not on state.

    PRD: "The segregation check is evaluated early — before the target entity's own state is examined. If the analyst who applied a redaction decides again on a segment whose `redaction_status` has already reached `APPROVED`, both the segregation rule and the segment-state rule are violated; the response is `ERR_SEGREGATION_OF_DUTIES`, not `ERR_SEGMENT_STATE_INVALID`."

    Design: Difficulty/priority_pair_validation_conflict/redaction_segregation_of_duties_beats_segment_state_rejected
    """
    scenario = _approved_redaction_applied_by_analyst_one(api)
    bh = scenario["segment_ids"]["bh"]

    response = api.redaction_decision(
        bh, f.redaction_decision_payload("APPROVE", "signing off on my own work"), REVIEWER_AS_ANALYST_1
    )
    validate_error(response, e.ERR_SEGREGATION_OF_DUTIES, 403)


def test_a_clean_reviewer_reaches_the_segment_state_rule_underneath(api):
    """With the identity rule satisfied, the approved segment refuses a rework on state.

    PRD: "**Deciding a redaction** is a `ReleaseReviewer` capability taking a `decision` of `APPROVE` or `REWORK` plus an optional `note`, permitted only from `redaction_status` `APPLIED`, and in both branches requiring that `X-User-ID` differ from the segment's `redaction_applied_by_user_id`."

    Design: Difficulty/priority_pair_validation_conflict/redaction_segregation_of_duties_beats_segment_state_rejected
    """
    scenario = _approved_redaction_applied_by_analyst_one(api)
    bh = scenario["segment_ids"]["bh"]

    validate_error(
        api.redaction_decision(bh, f.redaction_decision_payload("APPROVE"), REVIEWER_AS_ANALYST_1),
        e.ERR_SEGREGATION_OF_DUTIES,
        403,
    )
    response = api.redaction_decision(
        bh, f.redaction_decision_payload("REWORK", "reopening an approved redaction"), REVIEWER_2
    )
    validate_error(response, e.ERR_SEGMENT_STATE_INVALID, 409)


def test_neither_rejected_decision_moves_the_segment_or_the_request(api):
    """Two refusals, no state change and no version movement anywhere.

    PRD: "Whenever an operation mutates more than one resource, every touched resource's `updated_at` is refreshed and its `version` incremented by 1 — including cascade targets the caller never named."

    Design: Difficulty/priority_pair_validation_conflict/redaction_segregation_of_duties_beats_segment_state_rejected
    """
    scenario = _approved_redaction_applied_by_analyst_one(api)
    bh = scenario["segment_ids"]["bh"]
    request_id = scenario["request_id"]
    segment_before = fx.read_segment(api, bh)
    request_before = fx.read_request(api, request_id)

    validate_error(
        api.redaction_decision(bh, f.redaction_decision_payload("APPROVE"), REVIEWER_AS_ANALYST_1),
        e.ERR_SEGREGATION_OF_DUTIES,
        403,
    )
    validate_error(
        api.redaction_decision(bh, f.redaction_decision_payload("REWORK"), REVIEWER_2),
        e.ERR_SEGMENT_STATE_INVALID,
        409,
    )

    segment = fx.read_segment(api, bh)
    assert segment["redaction_status"] == "APPROVED"
    assert segment["redacted_page_count"] == 5
    assert segment["redaction_applied_by_user_id"] == "u-analyst-1"
    assert segment["redaction_approved_by_user_id"] == "u-review-1"
    assert segment["version"] == segment_before["version"]

    request = fx.read_request(api, request_id)
    assert request["fulfillment_status"] == "RELEASE_READY"
    assert request["billable_page_count"] == 57
    assert request["version"] == request_before["version"]
