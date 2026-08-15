"""Optimistic-concurrency, referral auto-creation, clock-driven posture
recomputation, and multi-hop cascade tests (PRD §2.5, §2.7, §3.2, §3.8, §3.10)."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS, headers_for,
    assert_instant_equals, assert_regulatory_referral, assert_trend_snapshot,
    setup_reference_data, setup_complaint, intake_complaint,
    intake_portal_complaint, setup_resolved_complaint,
    setup_product_with_substantiated, create_category,
    create_rca, complete_rca, create_and_complete_rca, triage, start_investigation,
    set_clock, get_complaint, get_product, get_referral,
    list_complaint_referrals, list_complaint_decisions,
)

MANAGER = TEST_USERS["complaint_manager_headers"]
HANDLER = TEST_USERS["case_handler_headers"]
INTAKE = TEST_USERS["intake_specialist_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


def test_occ_taxonomy_recode_stale_version_rejected(api):
    """PRD §2.7: "Two write operations guard against stale-client writes using
    optimistic concurrency on the parent `Complaint`:" and "**Taxonomy recoding**
    requires the request to carry `expected_complaint_version`, the complaint
    `version` the client last observed."
    PRD §2.7: "A mismatch means another writer has advanced the complaint since
    the client last read it — a recode, a triage, a referral submission, anything
    that legitimately bumps the version — and the request is rejected with
    `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_taxonomy_recode_stale_version_rejected
    """
    ctx = setup_complaint("P-X1", "WEB", "C.X1A", narrative="occ")
    create_category("C.X1B")
    cid = ctx["complaint"]["id"]
    captured_version = ctx["complaint"]["version"]
    assert captured_version == 1
    triage(cid)  # advances the complaint to version 2

    response = api.recode_taxonomy(
        cid, {"new_category_code": "C.X1B",
              "expected_complaint_version": captured_version}, HANDLER,
    )
    validate_error(response, ApiErrorId.ERR_STALE_VERSION)

    after = get_complaint(cid)
    assert after["category_code"] == "C.X1A", "rejected recode must not recode"
    assert after["version"] == 2

    # The same recode carrying the fresh version succeeds.
    retried = validate_success(api.recode_taxonomy(
        cid, {"new_category_code": "C.X1B", "expected_complaint_version": 2}, HANDLER,
    ))
    assert retried["category_code"] == "C.X1B"


def test_occ_remediation_create_stale_version_rejected(api):
    """PRD §2.7: "**Remediation-decision creation** likewise requires
    `expected_complaint_version` naming the complaint version against which the
    decision was drafted."
    PRD §2.7: "A mismatch means another writer has advanced the complaint since
    the client last read it — a recode, a triage, a referral submission, anything
    that legitimately bumps the version — and the request is rejected with
    `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_remediation_create_stale_version_rejected
    """
    ctx = setup_complaint("P-X2", "WEB", "C.X2", narrative="occ2")
    cid = ctx["complaint"]["id"]
    triage(cid)
    stale_version = get_complaint(cid)["version"]
    assert stale_version == 2
    start_investigation(cid)  # advances the complaint to version 3

    response = api.create_remediation_decision(
        cid, {"decision_type": "CORRECTION", "line_items": [],
              "expected_complaint_version": stale_version}, HANDLER,
    )
    validate_error(response, ApiErrorId.ERR_STALE_VERSION)
    assert list_complaint_decisions(cid) == [], (
        "a stale-version create must not persist a RemediationDecision"
    )


def test_derived_field_reconciliation_referral_list_after_portal_intake(api):
    """PRD §3.2: "When the intake channel has `is_regulator_portal` true, the
    same request atomically creates a `RegulatoryReferral` alongside the
    complaint."
    PRD §3.2: "The referral's `received_via_portal_at` equals the complaint's
    `received_at`; its `portal_ref` is the supplied value, defaulting to `AUTO-`
    followed by the complaint's `id` when omitted; and its `response_due_at` is
    exactly fifteen calendar days after `received_via_portal_at`, computed with
    calendar-day arithmetic that preserves the time of day and applies no
    business-day adjustment."
    PRD §3.2: "The referral opens in `OPEN` status with `timeliness` `PENDING`
    and `submitted_at` null, and a `REFERRAL_FILED` event lands on the
    complaint's audit trail."

    Design: Corner/cross_cutting_complexity_layers/derived_field_reconciliation_referral_list_after_portal_intake
    """
    complaint, referral = intake_portal_complaint(
        "P-X4", "CFPB_PORTAL", "C.X4", narrative="auto referral", portal_ref="R-X4",
    )
    referrals = list_complaint_referrals(complaint["id"])
    assert len(referrals) == 1
    referral = referrals[0]
    assert_regulatory_referral(referral)
    assert referral["status"] == "OPEN"
    assert referral["timeliness"] == "PENDING"
    assert_instant_equals(referral["received_via_portal_at"], "2026-08-01T00:00:00Z",
                          "received_via_portal_at")
    assert_instant_equals(referral["response_due_at"], "2026-08-16T00:00:00Z",
                          "response_due_at")
    assert referral["portal_ref"] == "R-X4"


def test_rate_threshold_posture_drop_when_clock_moves_past_90d(api):
    """PRD §2.5: "Setting the clock is itself a business event: because the
    trailing-90-day substantiation window shifts with the clock, advancing the
    clock recomputes `posture` for every `Product`."
    PRD §3.10: "aggregates are refreshed first — `open_complaint_count` counts the
    product's complaints in `INTAKE`, `TRIAGED`, `INVESTIGATING`,
    `RESPONSE_DRAFTED`, `RESPONSE_QA`, or `REOPENED`, and
    `substantiated_count_90d` counts complaints whose latest RCA verdict is
    `SUBSTANTIATED` and whose `received_at` falls within the trailing ninety
    calendar days of the logical clock — and the posture then derives by
    threshold: `FROZEN` when `substantiated_count_90d` reaches at least 5;
    otherwise `WATCH` when `early_warning_active` is true or
    `substantiated_count_90d` is at least 3; otherwise `OPEN`."

    Design: Corner/cross_cutting_complexity_layers/rate_threshold_posture_drop_when_clock_moves_past_90d
    """
    ctx = setup_product_with_substantiated("P-X5", 3, "WEB", "C.X5")
    pid = ctx["product"]["id"]
    before = get_product(pid)
    assert before["substantiated_count_90d"] == 3
    assert before["posture"] == "WATCH"

    # 2026-11-01 is 92 days after the 2026-08-01 receipts: the trailing 90-day
    # window no longer covers them.
    set_clock("2026-11-01T00:00:00Z")
    after = get_product(pid)
    assert after["substantiated_count_90d"] == 0, (
        f"window membership must expire with the clock, got "
        f"{after['substantiated_count_90d']}"
    )
    assert after["posture"] == "OPEN"


# ---------------------------------------------------------------------------
# Difficulty: transitive_cascade
# ---------------------------------------------------------------------------

def test_regulator_reopen_cascades_referral_to_complaint_to_product(api):
    """PRD §3.8: "The reopen is a three-hop cascade: first the referral's own
    `version` bumps; then, when the parent complaint is `RESOLVED`, it
    transitions to `REOPENED` with `resolved_at` and `retention_purge_at` cleared
    to null and the complaint's `version` bumped; and when that second hop fired,
    the product's `open_complaint_count` increments by 1 and its `posture`
    recomputes."

    Design: Difficulty/transitive_cascade/regulator_reopen_cascades_referral_to_complaint_to_product
    """
    ctx = setup_resolved_complaint(
        "PIR-REV", "CFPB_PORTAL", "LOAN.PAYOFF", portal=True,
        owner_id="user_intake_3", reviewer_id="user_qa_3",
        narrative="Payoff statement delay", portal_ref="CFPB-2026-900",
        window_end_at="2026-08-11T00:00:00Z", resolve_clock="2026-08-12T00:00:00Z",
    )
    pid = ctx["product"]["id"]
    cid = ctx["complaint"]["id"]
    referral = list_complaint_referrals(cid)[0]
    validate_success(api.submit_referral_response(
        referral["id"], {"response_text": "Regulator response."}, HANDLER,
    ))
    # Pre-cascade: the resolved complaint no longer counts as open.
    assert get_complaint(cid)["status"] == "RESOLVED"
    assert get_product(pid)["open_complaint_count"] == 0

    reopened = validate_success(api.regulator_reopen_referral(referral["id"], MANAGER))
    assert reopened["status"] == "REOPENED_BY_REGULATOR"

    complaint = get_complaint(cid)
    assert complaint["status"] == "REOPENED", (
        f"hop 2 must cascade the RESOLVED parent to REOPENED, got {complaint['status']}"
    )
    assert complaint.get("resolved_at") is None
    assert complaint.get("retention_purge_at") is None

    product = get_product(pid)
    assert product["open_complaint_count"] == 1, (
        f"hop 3 must re-increment the product open count, got "
        f"{product['open_complaint_count']}"
    )


def test_regulator_reopen_without_resolved_parent_does_not_cascade(api):
    """PRD §3.8: "The reopen is a three-hop cascade: first the referral's own
    `version` bumps; then, when the parent complaint is `RESOLVED`, it
    transitions to `REOPENED` with `resolved_at` and `retention_purge_at` cleared
    to null and the complaint's `version` bumped; and when that second hop fired,
    the product's `open_complaint_count` increments by 1 and its `posture`
    recomputes."

    Design: Difficulty/transitive_cascade/regulator_reopen_cascades_referral_to_complaint_to_product
    """
    ctx = setup_complaint("NC-REV", "CFPB_PORTAL", "LOAN.NC", portal=True,
                          narrative="no cascade", portal_ref="CFPB-NC-1")
    pid = ctx["product"]["id"]
    cid = ctx["complaint"]["id"]
    referral = list_complaint_referrals(cid)[0]
    validate_success(api.submit_referral_response(
        referral["id"], {"response_text": "First response."}, HANDLER,
    ))
    # Parent complaint is INTAKE (never RESOLVED), so hop 2 must not fire.
    reopened = validate_success(api.regulator_reopen_referral(referral["id"], MANAGER))
    assert reopened["status"] == "REOPENED_BY_REGULATOR"

    after = get_complaint(cid)
    assert after["status"] == "INTAKE", (
        f"the cascade is conditioned on a RESOLVED parent; got {after['status']}"
    )
    assert get_product(pid)["open_complaint_count"] == 1


def test_substantiated_rca_completion_cascades_product_posture_freeze(api):
    """PRD §3.4: "When the completed `verdict` is `SUBSTANTIATED`, the cascade
    continues one hop further: `substantiated_count_90d` is recomputed for the
    product named by `linked_product_code`, and that product's `posture` is
    recomputed against the thresholds in §3.8."
    PRD §3.10: "the posture then derives by threshold: `FROZEN` when
    `substantiated_count_90d` reaches at least 5; otherwise `WATCH` when
    `early_warning_active` is true or `substantiated_count_90d` is at least 3;
    otherwise `OPEN`."
    PRD §3.10: "While a product is `FROZEN`, complaint intake on it is rejected
    with `ERR_PRODUCT_FROZEN`."

    Design: Difficulty/transitive_cascade/substantiated_rca_completion_cascades_product_posture_freeze
    """
    ctx = setup_product_with_substantiated("CCRD-SEC", 4, "WEB", "FEES.ANNUAL")
    pid = ctx["product"]["id"]
    mid = get_product(pid)
    assert mid["substantiated_count_90d"] == 4
    assert mid["posture"] == "WATCH"

    fifth = intake_complaint("CCRD-SEC", "WEB", "FEES.ANNUAL", narrative="n5")
    rca = create_rca(fifth["id"], "SUBSTANTIATED", "CCRD-SEC", "FEE_POST")
    complete_rca(rca["id"])

    product = get_product(pid)
    assert product["substantiated_count_90d"] == 5
    assert product["posture"] == "FROZEN", (
        f"the fifth substantiated completion must freeze the product, got "
        f"{product['posture']}"
    )

    blocked = api.create_complaint(
        {"complainant_ref": "CUST-506", "channel_code": "WEB",
         "product_code": "CCRD-SEC", "category_code": "FEES.ANNUAL",
         "narrative": "gated"},
        INTAKE,
    )
    validate_error(blocked, ApiErrorId.ERR_PRODUCT_FROZEN)


def test_substantiated_rca_completion_four_stays_watch(api):
    """PRD §3.10: "the posture then derives by threshold: `FROZEN` when
    `substantiated_count_90d` reaches at least 5; otherwise `WATCH` when
    `early_warning_active` is true or `substantiated_count_90d` is at least 3;
    otherwise `OPEN`."
    PRD §3.10: "While a product is `FROZEN`, complaint intake on it is rejected
    with `ERR_PRODUCT_FROZEN`."

    Design: Difficulty/transitive_cascade/substantiated_rca_completion_cascades_product_posture_freeze
    """
    ctx = setup_product_with_substantiated("CCRD-PLT", 4, "WEB", "FEES.MONTHLY")
    pid = ctx["product"]["id"]
    product = get_product(pid)
    assert product["substantiated_count_90d"] == 4
    assert product["posture"] == "WATCH", (
        f"4 substantiated is below the inclusive FROZEN boundary of 5, got "
        f"{product['posture']}"
    )
    # Intake gates only on FROZEN, so a WATCH product still accepts complaints.
    complaint = intake_complaint("CCRD-PLT", "WEB", "FEES.MONTHLY", narrative="ok")
    assert complaint["status"] == "INTAKE"
