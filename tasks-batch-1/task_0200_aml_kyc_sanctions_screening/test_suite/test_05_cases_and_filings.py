"""Case investigation (fork-join, linking) and filing lifecycle (four-eyes, deadlines)."""
import pytest
from datetime import datetime, timedelta

from test_helpers import (
    validate_success, validate_error,
    create_customer_payload, create_legal_entity_payload, create_account_payload,
    create_transaction_payload, create_risk_assessment_payload,
    ApiErrorId, NON_EXISTENT_UUID, TEST_USERS, make_headers,
)
from test_helpers import fixtures as fx

CO = TEST_USERS["compliance_officer_headers"]
AN = TEST_USERS["analyst_headers"]
QR = TEST_USERS["quality_reviewer_headers"]
SF = TEST_USERS["system_feed_headers"]


# ==========================================================================
# Queue A — non_linear_state_machine (case fork-join)
# ==========================================================================
def test_case_fork_require_ctr_branch(api):
    """PRD §3.8: "Linking the first alert auto-advances the case from `TRIAGE` to
    `INVESTIGATING`."
    PRD §3.8: "An `Analyst` (or `ComplianceOfficer`) may require a CTR, moving
    the case to `CTR_REQUIRED`, which is valid only when at least one linked alert
    has a `rule_code` of `CTR_THRESHOLD`".

    Design: Difficulty/non_linear_state_machine/case_branching_fork_join_three_branches
    """
    cust, acct, alert, case = fx.setup_case_with_linked_alert(rule="CTR_THRESHOLD")
    assert case["disposition"] == "INVESTIGATING"
    disp = validate_success(api.disposition_case(case["id"], {"decision": "REQUIRE_CTR"}, AN))
    assert disp["disposition"] == "CTR_REQUIRED"


def test_case_fork_recommend_sar_branch(api):
    """PRD §3.8: "Linking the first alert auto-advances the case from `TRIAGE` to
    `INVESTIGATING`."
    PRD §3.8: "An `Analyst` (or `ComplianceOfficer`) may recommend a SAR, moving
    the case to `SAR_RECOMMENDED`, which requires that the case have at least one
    linked alert."

    Design: Difficulty/non_linear_state_machine/case_branching_fork_join_three_branches
    """
    cust, acct, alert, case = fx.setup_case_with_linked_alert(rule="STRUCTURING")
    assert case["disposition"] == "INVESTIGATING"
    disp = validate_success(api.disposition_case(case["id"], {"decision": "RECOMMEND_SAR"}, AN))
    assert disp["disposition"] == "SAR_RECOMMENDED"


# ==========================================================================
# Queue A — priority_pair_validation_conflict (existence beats referential)
# ==========================================================================
def test_existence_beats_referential_on_link_bogus_alert(api):
    """PRD §2.6: "After path identifiers, any foreign-key reference carried in the
    request body is validated for existence the same way, again yielding
    `ERR_NOT_FOUND` when the referenced resource is absent. This existence check
    (priority 3) runs after authentication and authorization but before body
    well-formedness and all business rules."

    Linking a non-existent alert_id returns ERR_NOT_FOUND (existence, priority 3),
    not the customer-mismatch referential error (priority 15).

    Design: Difficulty/priority_pair_validation_conflict/existence_beats_business_referential_on_link_alert
    """
    cust = fx.create_legal_entity(legal_name="Ref Co", incorporation_date="2013-03-03")
    case = fx.open_case(cust["id"])
    validate_error(api.link_alert(
        case["id"], {"alert_id": NON_EXISTENT_UUID, "expected_case_version": case["version"]}, AN),
        ApiErrorId.ERR_NOT_FOUND.value)


def test_existence_path_case_not_found_beats_referential(api):
    """PRD §2.6: "The server validates the existence of every identifier in the
    path from left to right, rejecting the request with `ERR_NOT_FOUND` at the
    first path segment that does not resolve to an existing resource."

    Linking to a non-existent case (path id) returns ERR_NOT_FOUND before any
    body/referential rule — the path-side facet of existence priority 3.

    Design: Difficulty/priority_pair_validation_conflict/existence_beats_business_referential_on_link_alert
    """
    cust = fx.create_legal_entity(legal_name="RefPath Co", incorporation_date="2013-03-03")
    acct = fx.create_account(cust["id"], account_ref="AC-REFPATH-1")
    validate_success(api.post_transaction(
        acct["id"], create_transaction_payload(direction="CASH_IN", amount_cents=950000,
                                               posted_at="2026-06-04T08:00:00Z", counterparty_country="US"), SF), 201)
    alerts, _ = fx._list(api.list_account_alerts(acct["id"], AN))
    validate_error(api.link_alert(
        NON_EXISTENT_UUID, {"alert_id": alerts[0]["id"], "expected_case_version": 1}, AN),
        ApiErrorId.ERR_NOT_FOUND.value)


def test_link_alert_customer_mismatch_rejected(api):
    """PRD §3.8: "an alert whose `customer_id` does not equal the case's
    `customer_id` is rejected with `ERR_ALERT_CUSTOMER_MISMATCH`".

    A real alert belonging to customer B linked to a case for customer A is
    rejected on the referential check (the alert exists, so existence passes).

    Design: Difficulty/cross_entity_state_dependency/case_link_requires_alert_same_customer_pair_case_alert
    """
    cust_a = fx.create_legal_entity(legal_name="Cust A", incorporation_date="2010-10-10")
    cust_b = fx.create_legal_entity(legal_name="Cust B", incorporation_date="2011-11-11")
    acct_b = fx.create_account(cust_b["id"], account_ref="AC-XB-1")
    validate_success(api.post_transaction(
        acct_b["id"], create_transaction_payload(direction="CASH_IN", amount_cents=950000,
                                                 posted_at="2026-06-04T08:00:00Z", counterparty_country="US"), SF), 201)
    alerts_b, _ = fx._list(api.list_alerts(AN, params={"customer_id": cust_b["id"]}))
    alert_b = alerts_b[0]
    case_a = fx.open_case(cust_a["id"])
    validate_error(api.link_alert(
        case_a["id"], {"alert_id": alert_b["id"], "expected_case_version": case_a["version"]}, AN),
        ApiErrorId.ERR_ALERT_CUSTOMER_MISMATCH.value)
    after = validate_success(api.get_case(case_a["id"], AN))
    assert after["disposition"] == "TRIAGE"


def test_link_alert_same_customer_succeeds(api):
    """PRD §3.8: "an alert whose `customer_id` does not equal the case's
    `customer_id` is rejected with `ERR_ALERT_CUSTOMER_MISMATCH`".
    PRD §3.8: "Linking the first alert auto-advances the case from `TRIAGE` to
    `INVESTIGATING`."

    The positive-control facet of the Case<-Alert customer dependency: an alert
    whose customer_id DOES match the case's customer_id links cleanly and the
    case advances — proving the gate is the customer match, not a blanket block.

    Design: Difficulty/cross_entity_state_dependency/case_link_requires_alert_same_customer_pair_case_alert
    """
    cust, acct, alert, case = fx.setup_case_with_linked_alert(rule="STRUCTURING")
    assert case["disposition"] == "INVESTIGATING"
    assert case["linked_alert_count"] == 1


# ==========================================================================
# Queue A — compensating_invariant (account monitoring link/close round trip)
# ==========================================================================
def test_account_monitoring_conserved_link_then_close(api):
    """PRD §3.6: "an account in `ACTIVE` moves to `UNDER_INVESTIGATION` when an
    alert is created against it".
    PRD §3.8: "closing dismisses every linked alert (setting each alert's
    `status` to `DISMISSED` and clearing its `case_id` to null) and, for any
    account whose only linked alerts were on this case, reverts that account's
    `monitoring_status` from `UNDER_INVESTIGATION` back to `ACTIVE`."

    The investigation forward action takes the account out of ACTIVE; the
    compensating CLOSE_NO_ACTION returns it to ACTIVE (net-zero).

    Design: Difficulty/compensating_invariant/account_monitoring_conserved_link_then_close_no_action
    """
    cust, acct, alert, case = fx.setup_case_with_linked_alert(rule="STRUCTURING")
    mon_after_link = validate_success(api.get_account(acct["id"], CO))
    assert mon_after_link["monitoring_status"] == "UNDER_INVESTIGATION"
    closed = validate_success(api.disposition_case(case["id"], {"decision": "CLOSE_NO_ACTION"}, CO))
    assert closed["disposition"] == "CLOSED_NO_ACTION"
    mon_after_close = validate_success(api.get_account(acct["id"], CO))
    assert mon_after_close["monitoring_status"] == "ACTIVE"


def test_close_no_action_dismisses_linked_alert(api):
    """PRD §3.8: "closing dismisses every linked alert (setting each alert's
    `status` to `DISMISSED` and clearing its `case_id` to null) and, for any
    account whose only linked alerts were on this case, reverts that account's
    `monitoring_status` from `UNDER_INVESTIGATION` back to `ACTIVE`."

    The alert-side leg of the same conserved round trip: CLOSE_NO_ACTION dismisses
    the linked alert and clears its case_id, the compensating action that frees
    the account back to ACTIVE.

    Design: Difficulty/compensating_invariant/account_monitoring_conserved_link_then_close_no_action
    """
    cust, acct, alert, case = fx.setup_case_with_linked_alert(rule="STRUCTURING")
    validate_success(api.disposition_case(case["id"], {"decision": "CLOSE_NO_ACTION"}, CO))
    dismissed = validate_success(api.get_alert(alert["id"], AN))
    assert dismissed["status"] == "DISMISSED"
    assert dismissed["case_id"] is None


# ==========================================================================
# Queue B — case & filing corner instances
# ==========================================================================
def test_filing_reject_then_revise_returns_to_draft(api):
    """PRD §3.9: "A `REJECTED` filing is not dead: an `Analyst` may revise it,
    returning it to `DRAFT` and clearing `approved_by_user_id` so that it must be
    approved afresh before it can be resubmitted."

    Design: Corner/state_machines/filing_reject_then_revise_returns_to_draft
    """
    case, submitted = fx.create_submitted_sar_filing()
    rejected = validate_success(api.acknowledge_filing(submitted["id"], {"decision": "REJECT"}, SF))
    assert rejected["status"] == "REJECTED"
    revised = validate_success(api.revise_filing(submitted["id"], AN))
    assert revised["status"] == "DRAFT"
    assert revised["approved_by_user_id"] is None


def test_filing_accepted_bubbles_case_to_filed(api):
    """PRD §3.9: "An `ACCEPT` decision, which must carry an `acknowledgement_code`,
    moves the filing from `SUBMITTED` to the terminal `ACCEPTED` state, stores
    that `acknowledgement_code`, and bubbles the owning case to `FILED`."

    Design: Corner/state_machines/filing_accepted_bubbles_case_to_filed
    """
    case, submitted = fx.create_submitted_sar_filing()
    accepted = validate_success(api.acknowledge_filing(
        submitted["id"], {"decision": "ACCEPT", "acknowledgement_code": "BSA-ACK-123"}, SF))
    assert accepted["status"] == "ACCEPTED"
    assert accepted["acknowledgement_code"] == "BSA-ACK-123"
    case_after = validate_success(api.get_case(case["id"], AN))
    assert case_after["disposition"] == "FILED"


def test_case_priority_critical_from_high_structuring(api):
    """PRD §3.8: "A case's `priority` is recomputed each time an alert is linked,
    from the maximum `severity_score` among all alerts whose `case_id` is this
    case and whose `status` is `LINKED`. The band is `CRITICAL` when that maximum
    is at least 70".

    STRUCTURING(40) * HIGH(2.0) = 80 >= 70 -> CRITICAL.

    Design: Corner/calculations/case_priority_critical_from_structuring_high
    """
    cust, acct, alert, case = fx.setup_case_with_linked_alert(
        rule="STRUCTURING", rate=True,
        factors=dict(geography_factor=5, product_factor=4, pep_factor=4, adverse_media_factor=4))
    assert case["priority"] == "CRITICAL"
    assert case["linked_alert_count"] == 1


def test_filing_deadline_sar_30_days(api):
    """PRD §3.9: "For a SAR, the deadline is the case's `created_at` advanced by
    30 days."

    Design: Corner/calculations/filing_deadline_sar_30_days_from_case_open
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    cust, acct, alert, case = fx.setup_sar_recommended_case()
    case_full = validate_success(api.get_case(case["id"], AN))
    filing = validate_success(api.create_filing(case["id"], {"filing_type": "SAR"}, AN), 201)
    assert filing["filing_type"] == "SAR"
    c = datetime.fromisoformat(case_full["created_at"].replace("Z", "+00:00"))
    d = datetime.fromisoformat(filing["deadline_at"].replace("Z", "+00:00"))
    assert (d - c) == timedelta(days=30), f"expected +30d, got {d - c}"


def test_filing_type_mismatch_sar_on_ctr_case(api):
    """PRD §3.9: "The filing type must match the case's disposition: a `SAR`
    filing may be created only for a case in `SAR_RECOMMENDED`, and a `CTR` filing
    only for a case in `CTR_REQUIRED`; a mismatch is rejected with
    `ERR_FILING_TYPE_MISMATCH`."

    Design: Corner/endpoints/filing_type_mismatch_sar_on_ctr_required_case
    """
    cust, acct, alert, case = fx.setup_ctr_required_case()
    assert case["disposition"] == "CTR_REQUIRED"
    validate_error(api.create_filing(case["id"], {"filing_type": "SAR"}, AN),
                   ApiErrorId.ERR_FILING_TYPE_MISMATCH.value)


def test_no_ctr_alert_blocks_require_ctr(api):
    """PRD §3.8: "An `Analyst` (or `ComplianceOfficer`) may require a CTR, moving
    the case to `CTR_REQUIRED`, which is valid only when at least one linked alert
    has a `rule_code` of `CTR_THRESHOLD`; absent such an alert the request is
    rejected with `ERR_NO_CTR_ALERT`."

    Design: Corner/validations/no_ctr_alert_blocks_require_ctr
    """
    cust, acct, alert, case = fx.setup_case_with_linked_alert(rule="STRUCTURING")
    validate_error(api.disposition_case(case["id"], {"decision": "REQUIRE_CTR"}, AN),
                   ApiErrorId.ERR_NO_CTR_ALERT.value)


def test_alert_already_linked_rejected(api):
    """PRD §3.8: "an alert already in `LINKED` status cannot be linked again and
    is rejected with `ERR_ALERT_ALREADY_LINKED`".

    Design: Corner/endpoints/alert_already_linked_rejected
    """
    cust, acct, alert, case1 = fx.setup_case_with_linked_alert(rule="STRUCTURING")
    case2 = fx.open_case(cust["id"])
    validate_error(api.link_alert(
        case2["id"], {"alert_id": alert["id"], "expected_case_version": case2["version"]}, AN),
        ApiErrorId.ERR_ALERT_ALREADY_LINKED.value)


def test_filing_not_approvable_from_submitted(api):
    """PRD §3.9: "A `QualityReviewer` approves a `DRAFT` filing, which captures the
    reviewer into `approved_by_user_id`; approval requires the filing to be in
    `DRAFT`, and any other status is rejected with `ERR_NOT_APPROVABLE`."

    Design: Corner/errors/filing_not_approvable_from_submitted
    """
    case, submitted = fx.create_submitted_sar_filing()
    assert submitted["status"] == "SUBMITTED"
    validate_error(api.approve_filing(submitted["id"], make_headers("qr-2", "QualityReviewer")),
                   ApiErrorId.ERR_NOT_APPROVABLE.value)


def test_account_blocked_for_case_when_frozen(api):
    """PRD §3.8: "an alert whose originating account is `FROZEN` cannot be linked —
    the account is locked from further investigation routing — and is rejected
    with `ERR_ACCOUNT_BLOCKED_FOR_CASE`."

    Design: Corner/errors/account_blocked_for_case_when_frozen
    """
    cust = fx.create_legal_entity(legal_name="Abc Co", incorporation_date="1989-09-09")
    acct = fx.create_account(cust["id"], account_ref="AC-ABC-1")
    # First txn fires STRUCTURING (moves to UNDER_INVESTIGATION); second fires
    # HIGH_RISK_GEO -> a second OPEN alert that we will try to link after freezing.
    validate_success(api.post_transaction(
        acct["id"], create_transaction_payload(direction="CASH_IN", amount_cents=950000,
                                               posted_at="2026-06-24T08:00:00Z", counterparty_country="US"), SF), 201)
    validate_success(api.post_transaction(
        acct["id"], create_transaction_payload(direction="CASH_IN", amount_cents=5000,
                                               posted_at="2026-06-24T09:00:00Z", counterparty_country="IR"), SF), 201)
    frozen = validate_success(api.freeze_account(acct["id"], CO))
    assert frozen["monitoring_status"] == "FROZEN"
    open_alerts, _ = fx._list(api.list_account_alerts(acct["id"], AN, params={"status": "OPEN"}))
    alert_id = open_alerts[0]["id"]
    case = fx.open_case(cust["id"])
    validate_error(api.link_alert(
        case["id"], {"alert_id": alert_id, "expected_case_version": case["version"]}, AN),
        ApiErrorId.ERR_ACCOUNT_BLOCKED_FOR_CASE.value)


def test_immediate_consistency_priority_in_link_response(api):
    """PRD §3.8: "The link sets the alert's `status` to `LINKED` and its `case_id`
    to this case, recomputes `linked_alert_count` and `priority`".
    PRD §3.8: "A case's `priority` is recomputed each time an alert is linked,
    from the maximum `severity_score` among all alerts whose `case_id` is this
    case and whose `status` is `LINKED`. The band is `CRITICAL` when that maximum
    is at least 70".

    The link response itself carries the recomputed priority/count/disposition.

    Design: Corner/consistency_model/immediate_consistency_priority_visible_in_link_response
    """
    cust, acct, alert, case = fx.setup_case_with_linked_alert(
        rule="STRUCTURING", rate=True,
        factors=dict(geography_factor=5, product_factor=4, pep_factor=4, adverse_media_factor=4))
    assert case["priority"] == "CRITICAL"
    assert case["linked_alert_count"] == 1
    assert case["disposition"] == "INVESTIGATING"


# ==========================================================================
# Queue B — RBAC / segregation / OCC
# ==========================================================================
def test_segregation_same_user_prepare_and_approve(api):
    """PRD §3.9: "The four-eyes principle is non-negotiable: the
    `approved_by_user_id` must differ from the `prepared_by_user_id`, so the same
    user can never both prepare and approve a filing — a violation is rejected
    with `ERR_SEGREGATION_VIOLATION`."

    Design: Corner/rbac/segregation_same_user_prepare_and_approve_filing
    """
    case, filing = fx.create_draft_sar_filing(analyst_user_id="dual-1")
    assert filing["prepared_by_user_id"] == "dual-1"
    validate_error(api.approve_filing(filing["id"], make_headers("dual-1", "QualityReviewer")),
                   ApiErrorId.ERR_SEGREGATION_VIOLATION.value)


def test_analyst_cannot_apply_rating_forbidden(api):
    """PRD §2.1: "A request whose authenticated role is not permitted to perform
    the requested operation is rejected with `ERR_FORBIDDEN`."
    PRD §4: apply-rating is authorized for `ComplianceOfficer` only.

    Design: Corner/rbac/analyst_cannot_apply_rating_forbidden
    """
    customer = validate_success(api.create_customer(
        create_customer_payload(legal_name="Rbac Co", date_of_birth="1988-08-08"), CO), 201)
    cid = customer["id"]
    ra = validate_success(api.create_risk_assessment(
        cid, create_risk_assessment_payload(variant="PROVISIONAL", geography_factor=1,
                                            product_factor=1, pep_factor=1, adverse_media_factor=1), CO), 201)
    validate_error(api.apply_rating(
        cid, {"risk_assessment_id": ra["id"], "expected_customer_version": customer["version"]}, AN),
        ApiErrorId.ERR_FORBIDDEN.value)


def test_quality_reviewer_cannot_open_case_forbidden(api):
    """PRD §2.1: "A request whose authenticated role is not permitted to perform
    the requested operation is rejected with `ERR_FORBIDDEN`."
    PRD §4: POST /cases is authorized for `Analyst` only.

    Design: Corner/rbac/quality_reviewer_cannot_open_case_forbidden
    """
    cust = fx.create_legal_entity(legal_name="Qr Co", incorporation_date="1987-07-07")
    validate_error(api.create_case({"customer_id": cust["id"]}, QR), ApiErrorId.ERR_FORBIDDEN.value)


def test_occ_version_increments_and_stale_link_rejected(api):
    """PRD §2.11: "The link request must carry `expected_case_version`, which must
    equal the target case's current `version`."
    PRD §2.11: "When `expected_case_version` does not match the case's current
    `version`, the request is rejected with `ERR_STALE_VERSION` and HTTP status
    412".

    Design: Corner/cross_cutting_complexity_layers/occ_version_increments_on_each_case_link
    """
    cust = fx.create_legal_entity(legal_name="Occ Co", incorporation_date="1985-05-05")
    acct = fx.create_account(cust["id"], account_ref="AC-OCC-1")
    validate_success(api.post_transaction(
        acct["id"], create_transaction_payload(direction="CASH_IN", amount_cents=950000,
                                               posted_at="2026-06-26T08:00:00Z", counterparty_country="US"), SF), 201)
    validate_success(api.post_transaction(
        acct["id"], create_transaction_payload(direction="CASH_IN", amount_cents=5000,
                                               posted_at="2026-06-26T09:00:00Z", counterparty_country="IR"), SF), 201)
    open_alerts, _ = fx._list(api.list_account_alerts(acct["id"], AN, params={"status": "OPEN"}))
    a1, a2 = open_alerts[0], open_alerts[1]
    case = fx.open_case(cust["id"])
    v0 = case["version"]
    linked = validate_success(api.link_alert(
        case["id"], {"alert_id": a1["id"], "expected_case_version": v0}, AN))
    assert linked["version"] == v0 + 1
    validate_error(api.link_alert(
        case["id"], {"alert_id": a2["id"], "expected_case_version": v0}, AN),
        ApiErrorId.ERR_STALE_VERSION.value)


def test_occ_apply_rating_correct_version_succeeds(api):
    """PRD §2.11: "The apply request must carry `expected_customer_version`, which
    must equal the target customer's current `version`."
    PRD §2.4: "`version` — a system-managed integer that begins at its initial
    value on creation and increments by exactly one on every mutation of the
    resource."

    Design: Corner/cross_cutting_complexity_layers/occ_apply_rating_correct_version_succeeds
    """
    customer = validate_success(api.create_customer(
        create_customer_payload(legal_name="OccOk Co", date_of_birth="1984-04-04"), CO), 201)
    cid = customer["id"]
    v0 = customer["version"]
    ra = validate_success(api.create_risk_assessment(
        cid, create_risk_assessment_payload(variant="PROVISIONAL", geography_factor=1,
                                            product_factor=1, pep_factor=1, adverse_media_factor=1), CO), 201)
    rated = validate_success(api.apply_rating(
        cid, {"risk_assessment_id": ra["id"], "expected_customer_version": v0}, CO))
    assert rated["cdd_status"] == "RISK_RATED"
    assert rated["version"] == v0 + 1


def test_apply_rating_no_unapplied_assessment(api):
    """PRD §3.1: "The matching assessment must be a `RiskAssessment` row for this
    customer identified by `risk_assessment_id` whose `applied` flag is still
    false; if none matches, the request is rejected with
    `ERR_NO_UNAPPLIED_ASSESSMENT`."

    A `risk_assessment_id` that resolves to a RiskAssessment belonging to a
    *different* customer is no match for this (still-NEW) customer, so the apply
    is rejected with ERR_NO_UNAPPLIED_ASSESSMENT. The target customer stays in
    NEW and the version matches, so the higher-precedence state and stale-version
    checks (PRD §2.7) both pass and this business rule is the one that fires.

    Design: Corner/endpoints/apply_rating_no_unapplied_assessment
    """
    customer = validate_success(api.create_customer(
        create_customer_payload(legal_name="App Co", date_of_birth="1998-08-08"), CO), 201)
    cid = customer["id"]
    # An unapplied assessment that belongs to a different customer is not a match
    # for `cid`, while `cid` itself remains in NEW with an unchanged version.
    other = validate_success(api.create_customer(
        create_customer_payload(legal_name="Other Co", date_of_birth="1997-07-07"), CO), 201)
    other_ra = validate_success(api.create_risk_assessment(
        other["id"], create_risk_assessment_payload(variant="PROVISIONAL", geography_factor=1,
                                                     product_factor=1, pep_factor=1, adverse_media_factor=1), CO), 201)
    validate_error(api.apply_rating(
        cid, {"risk_assessment_id": other_ra["id"], "expected_customer_version": customer["version"]}, CO),
        ApiErrorId.ERR_NO_UNAPPLIED_ASSESSMENT.value)
