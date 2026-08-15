"""Activation gates: disclosure, deployment, and date — their individual
rules, boundaries, and relative order (PRD §2.9, §2.10, §3.2)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_draft_sheet,
    create_product,
    deploy_all,
    list_sheet_deployments,
    list_sheet_notices,
    promote_sheet_to_scheduled,
    send_all_notices,
    set_clock,
    single_tier,
    validate_error,
    validate_success,
    waive_all_notices,
)

TEST_CHANNEL = TEST_USERS["channel_headers"]
TEST_COMPLIANCE = TEST_USERS["compliance_headers"]


def _scheduled_sheet(product_code: str, effective_date: str, lead_days: int = 7):
    """APPROVED->SCHEDULED sheet with its deployment/notice rows listed."""
    product = create_product(product_code=product_code)
    sheet = create_draft_sheet(product["id"], effective_date=effective_date,
                               disclosure_lead_days=lead_days,
                               tiers=single_tier(100))
    promote_sheet_to_scheduled(sheet["id"])
    deployments = list_sheet_deployments(sheet["id"])
    notices = list_sheet_notices(sheet["id"])
    assert len(deployments) == 4 and len(notices) == 4
    return sheet, deployments, notices


def test_activate_gate_order_disclosure_before_deployment(api, analyst_headers):
    """PRD §3.2: "Three gates guard it, evaluated in this order: the
    disclosure gate requires every `PRE_CHANGE` notice for the sheet to be
    `SENT` and not late, or `WAIVED` (else `ERR_DISCLOSURE_LEAD_TIME_UNMET`);
    the deployment gate requires all four channel deployments to be `DEPLOYED`
    (else `ERR_DEPLOYMENT_INCOMPLETE`); and the date gate requires logical
    today to be on or after the sheet's `effective_date` (else
    `ERR_FUTURE_EFFECTIVE_DATE`)."

    Design: Difficulty/cross_entity_state_dependency/activate_gated_by_notice_and_deployment_states
    """
    sheet, deployments, notices = _scheduled_sheet("GATE", "2026-08-10")
    # Deploy three of four; send three of four (sent well before the
    # 2026-08-03 required date, so on time).
    for row in deployments[:3]:
        validate_success(api.execute_rate_deployment(row["id"], {"action": "DEPLOY"},
                                                     TEST_CHANNEL))
    for row in notices[:3]:
        validate_success(api.resolve_disclosure_notice(row["id"], {"action": "SEND"},
                                                       TEST_COMPLIANCE))
    set_clock("2026-08-03")  # the required_by date: the last notice is still on time

    # One PENDING notice blocks first, even though a deployment is also down.
    resp = api.activate_rate_sheet(sheet["id"], analyst_headers)
    validate_error(resp, ApiErrorId.ERR_DISCLOSURE_LEAD_TIME_UNMET, 409)

    # Notices fixed; the lone PENDING deployment now surfaces its own gate.
    validate_success(api.resolve_disclosure_notice(notices[3]["id"], {"action": "SEND"},
                                                   TEST_COMPLIANCE))
    resp = api.activate_rate_sheet(sheet["id"], analyst_headers)
    validate_error(resp, ApiErrorId.ERR_DEPLOYMENT_INCOMPLETE, 409)


def test_activate_succeeds_when_all_gates_green(api, analyst_headers):
    """PRD §3.2: "Activation by a `PricingAnalyst` moves `SCHEDULED` to
    `EFFECTIVE` and is the system's serialization point — the moment pricing
    truth changes for an entire product–market pair."
    PRD §3.2: "and the date gate requires logical today to be on or after the
    sheet's `effective_date` (else `ERR_FUTURE_EFFECTIVE_DATE`)."

    Design: Difficulty/cross_entity_state_dependency/activate_gated_by_notice_and_deployment_states
    """
    sheet, deployments, notices = _scheduled_sheet("GATE", "2026-08-10")
    for row in deployments[:3]:
        validate_success(api.execute_rate_deployment(row["id"], {"action": "DEPLOY"},
                                                     TEST_CHANNEL))
    for row in notices[:3]:
        validate_success(api.resolve_disclosure_notice(row["id"], {"action": "SEND"},
                                                       TEST_COMPLIANCE))
    set_clock("2026-08-03")
    validate_success(api.resolve_disclosure_notice(notices[3]["id"], {"action": "SEND"},
                                                   TEST_COMPLIANCE))
    validate_success(api.execute_rate_deployment(deployments[3]["id"], {"action": "DEPLOY"},
                                                 TEST_CHANNEL))
    set_clock("2026-08-10")  # on the effective date itself
    activated = validate_success(api.activate_rate_sheet(sheet["id"], analyst_headers))
    assert activated["status"] == "EFFECTIVE"


def test_activate_disclosure_safety_beats_future_date(api, analyst_headers):
    """PRD §2.10: "Sheet activation: the disclosure gate
    (`ERR_DISCLOSURE_LEAD_TIME_UNMET`) first — so a late or unsent disclosure
    surfaces rather than being masked by a later gate — then deployment
    completeness (`ERR_DEPLOYMENT_INCOMPLETE`), then the future-effective-date
    check (`ERR_FUTURE_EFFECTIVE_DATE`)."

    Design: Difficulty/priority_pair_validation_conflict/activate_disclosure_safety_beats_future_date_temporal
    """
    sheet, deployments, _ = _scheduled_sheet("PRIO", "2026-08-10")
    deploy_all(sheet["id"])
    set_clock("2026-08-05")  # before effective_date AND past required_by 2026-08-03

    # Both the disclosure gate (all notices still PENDING, already late) and
    # the date gate fail; the earlier gate's error surfaces.
    resp = api.activate_rate_sheet(sheet["id"], analyst_headers)
    validate_error(resp, ApiErrorId.ERR_DISCLOSURE_LEAD_TIME_UNMET, 409)

    sheet_now = validate_success(api.get_rate_sheet(sheet["id"], analyst_headers))
    assert sheet_now["status"] == "SCHEDULED"


def test_activate_after_waiving_disclosures_exposes_date_gate(api, analyst_headers):
    """PRD §3.2: "the disclosure gate requires every `PRE_CHANGE` notice for
    the sheet to be `SENT` and not late, or `WAIVED` (else
    `ERR_DISCLOSURE_LEAD_TIME_UNMET`); the deployment gate requires all four
    channel deployments to be `DEPLOYED` (else `ERR_DEPLOYMENT_INCOMPLETE`);
    and the date gate requires logical today to be on or after the sheet's
    `effective_date` (else `ERR_FUTURE_EFFECTIVE_DATE`)."

    Design: Difficulty/priority_pair_validation_conflict/activate_disclosure_safety_beats_future_date_temporal
    """
    sheet, _, _ = _scheduled_sheet("PRIO", "2026-08-10")
    deploy_all(sheet["id"])
    set_clock("2026-08-05")
    # Waiving satisfies the disclosure gate even past the required date; the
    # next failing gate is the future effective date.
    waive_all_notices(sheet["id"])
    resp = api.activate_rate_sheet(sheet["id"], analyst_headers)
    validate_error(resp, ApiErrorId.ERR_FUTURE_EFFECTIVE_DATE, 409)


def test_notice_sent_on_required_date_is_not_late(api, compliance_headers):
    """PRD §2.9: "The `is_late` flag is true when the notice was sent on a
    date after its `required_by_date`, and also — read as a computed property
    — when the notice is still `PENDING` and logical today has already passed
    the required date."
    PRD §3.2: "Upon scheduling, the server creates four RateDeployment rows —
    one per channel in the fixed order `BRANCH`, `ONLINE`, `MOBILE`,
    `CALL_CENTER`, all in `PENDING` — and four sheet-level `PRE_CHANGE`
    DisclosureNotice rows in the same channel order, each with a
    `required_by_date` of `effective_date` minus `disclosure_lead_days`."

    Design: Difficulty/boundary_precision_check/disclosure_required_by_exact_equality_not_late
    """
    sheet, _, notices = _scheduled_sheet("DLD", "2026-09-10", lead_days=7)
    deploy_all(sheet["id"])
    assert all(n["required_by_date"] == "2026-09-03" for n in notices)

    set_clock("2026-09-03")  # exactly the required date
    sent = validate_success(api.resolve_disclosure_notice(
        notices[0]["id"], {"action": "SEND"}, compliance_headers))
    assert sent["status"] == "SENT"
    assert sent["is_late"] is False


def test_activate_succeeds_when_notices_sent_on_required_date(api, analyst_headers):
    """PRD §3.2: "the disclosure gate requires every `PRE_CHANGE` notice for
    the sheet to be `SENT` and not late, or `WAIVED` (else
    `ERR_DISCLOSURE_LEAD_TIME_UNMET`); the deployment gate requires all four
    channel deployments to be `DEPLOYED` (else `ERR_DEPLOYMENT_INCOMPLETE`);
    and the date gate requires logical today to be on or after the sheet's
    `effective_date` (else `ERR_FUTURE_EFFECTIVE_DATE`)."

    Design: Difficulty/boundary_precision_check/disclosure_required_by_exact_equality_not_late
    """
    sheet, _, notices = _scheduled_sheet("DLD", "2026-09-10", lead_days=7)
    deploy_all(sheet["id"])
    set_clock("2026-09-03")
    for row in notices:
        validate_success(api.resolve_disclosure_notice(row["id"], {"action": "SEND"},
                                                       TEST_COMPLIANCE))
    set_clock("2026-09-10")
    activated = validate_success(api.activate_rate_sheet(sheet["id"], analyst_headers))
    assert activated["status"] == "EFFECTIVE"


def test_activate_before_effective_date_returns_future_date(api, analyst_headers):
    """PRD §3.2: "and the date gate requires logical today to be on or after
    the sheet's `effective_date` (else `ERR_FUTURE_EFFECTIVE_DATE`)."

    Design: Corner/validations/activate_before_effective_date_returns_future_date
    """
    sheet, _, _ = _scheduled_sheet("FD", "2026-08-10")
    deploy_all(sheet["id"])
    send_all_notices(sheet["id"])  # sent 2026-08-01, required 2026-08-03: on time
    set_clock("2026-08-09")
    resp = api.activate_rate_sheet(sheet["id"], analyst_headers)
    validate_error(resp, ApiErrorId.ERR_FUTURE_EFFECTIVE_DATE, 409)

    sheet_now = validate_success(api.get_rate_sheet(sheet["id"], analyst_headers))
    assert sheet_now["status"] == "SCHEDULED"


def test_deployment_mark_failed_on_deployed_and_retry_path(api, channel_headers):
    """PRD §3.2: "A deployment execution with action `DEPLOY` moves a
    deployment from `PENDING` or `FAILED` to `DEPLOYED` and stamps
    `deployed_at`; action `MARK_FAILED` moves `PENDING` to `FAILED`. Marking a
    `DEPLOYED` row failed, or deploying a `RETIRED` row, is rejected with
    `ERR_DEPLOYMENT_INVALID_STATE`."

    Design: Corner/state_machines/deployment_mark_failed_on_deployed_and_retry_path
    """
    sheet, deployments, _ = _scheduled_sheet("IV7", "2026-08-10")
    d0 = deployments[0]

    failed = validate_success(api.execute_rate_deployment(d0["id"], {"action": "MARK_FAILED"},
                                                          channel_headers))
    assert failed["status"] == "FAILED"

    retried = validate_success(api.execute_rate_deployment(d0["id"], {"action": "DEPLOY"},
                                                           channel_headers))
    assert retried["status"] == "DEPLOYED"
    assert retried["deployed_at"] is not None

    resp = api.execute_rate_deployment(d0["id"], {"action": "MARK_FAILED"}, channel_headers)
    validate_error(resp, ApiErrorId.ERR_DEPLOYMENT_INVALID_STATE, 409)


def test_notice_double_resolution_returns_already_resolved(api, compliance_headers):
    """PRD §2.9: "Resolving a notice that is already `SENT` or `WAIVED` is
    rejected with `ERR_NOTICE_ALREADY_RESOLVED`."

    Design: Corner/state_machines/notice_double_resolution_returns_already_resolved
    """
    _, _, notices = _scheduled_sheet("IV8", "2026-08-10")
    n0 = notices[0]
    sent = validate_success(api.resolve_disclosure_notice(n0["id"], {"action": "SEND"},
                                                          compliance_headers))
    assert sent["status"] == "SENT"
    resp = api.resolve_disclosure_notice(n0["id"], {"action": "SEND"}, compliance_headers)
    validate_error(resp, ApiErrorId.ERR_NOTICE_ALREADY_RESOLVED, 409)
