"""State-machine translations: ruling re-rate cascade, ruling precondition,
claim filing/cancel/review invalid transitions, denial compensation cascade,
audit follow-up cycle, and record destruction gating."""
from test_helpers import ApiErrorId, add_audit_case, add_certified_classification, add_classification, add_claim_line, advance_audit, file_claim, get_records_for_claim, onboard_client, setup_draft_claim_with_line, setup_filed_claim, setup_paid_claim, submit_classification, TEST_USERS, validate_error, validate_paginated, validate_success
from test_helpers.factories import create_binding_ruling_payload

ADMIN = TEST_USERS["firm_admin_headers"]
ANALYST = TEST_USERS["analyst_headers"]
BROKER = TEST_USERS["broker_headers"]
COMPLIANCE = TEST_USERS["compliance_headers"]


def test_ruling_issued_re_rates_classification(api):
    """PRD 3.2: "An `outcome` of `ISSUED` requires both `issued_hts_code` and
    `issued_duty_rate_bps` to be present — their absence is
    `ERR_INVALID_REQUEST` — and does considerably more: the ruling becomes
    `ISSUED`, and the linked classification is re-rated in place, its `hts_code`
    overwritten with `issued_hts_code`, its `duty_rate_bps` overwritten with
    `issued_duty_rate_bps`, and its `version` incremented."

    Design: Corner/state_machines/ruling_issued_re_rates_classification
    """
    client = onboard_client()
    cls = add_certified_classification(client["id"])
    assert cls["duty_rate_bps"] == 1650
    ruling = validate_success(
        api.create_binding_ruling(create_binding_ruling_payload(cls["id"]), BROKER),
        201,
    )
    assert ruling["status"] == "SUBMITTED"

    decided = validate_success(
        api.ruling_outcome(
            ruling["id"],
            {"outcome": "ISSUED", "issued_hts_code": "6203.42.4036",
             "issued_duty_rate_bps": 1200},
            BROKER,
        )
    )
    assert decided["status"] == "ISSUED"

    cls_after = validate_success(api.get_classification(cls["id"], ANALYST))
    assert cls_after["hts_code"] == "6203.42.4036"
    assert cls_after["duty_rate_bps"] == 1200


def test_ruling_create_requires_certified_classification(api):
    """PRD 3.2: "Where classification itself is contested, a `LicensedBroker`
    may file a `BindingRuling` request against a `CERTIFIED` classification —
    referencing a classification in any other status is rejected with
    `ERR_CLASSIFICATION_NOT_CERTIFIED`."

    Design: Corner/state_machines/ruling_create_requires_certified_classification
    """
    client = onboard_client()
    cls = add_classification(client["id"])
    submit_classification(cls["id"])  # IN_REVIEW, not yet decided

    res = api.create_binding_ruling(create_binding_ruling_payload(cls["id"]), BROKER)
    validate_error(res, ApiErrorId.ERR_CLASSIFICATION_NOT_CERTIFIED)


def test_file_from_filed_returns_invalid_state(api):
    """PRD 3.4: "Filing freezes everything. When a `LicensedBroker` files the
    claim, four preconditions hold: the client must still be `ACTIVE`
    (`ERR_CLIENT_NOT_ACTIVE`); the claim must have at least one `ACTIVE` line
    (`ERR_INVALID_REQUEST`); the broker's `X-User-ID` must differ from
    `prepared_by_user_id` (`ERR_SEGREGATION_OF_DUTIES`); and the logical clock
    must not have passed the claim's `filing_deadline`
    (`ERR_FILING_DEADLINE_PASSED`)."
    PRD 2.7: "Stale-version checks come next (`ERR_STALE_VERSION`), then
    state-machine legality (`ERR_INVALID_STATE` for a resource not in a valid
    from-state, `ERR_ALREADY_TERMINAL` for one already terminal), then
    segregation of duties (`ERR_SEGREGATION_OF_DUTIES`), then cross-entity
    referential rules (classification certification, client engagement,
    same-client references), then temporal rules (windows, filing deadlines,
    audit due dates), then uniqueness and overlap rules (entry numbers, measure
    windows, claim periods, deficiency limits), then match compatibility and
    quantity bounds, then frozen-ledger protections, and finally fiscal caps
    such as the export value pool and the various payment equalities."

    Design: Corner/state_machines/file_from_filed_returns_invalid_state
    """
    ctx = setup_filed_claim(matched_quantity=40)

    res = api.file_claim(ctx["claim"]["id"], BROKER)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)

    records = get_records_for_claim(ctx["claim"]["id"])
    assert len(records) == 3, "no duplicate filing side effects may occur"


def test_review_paid_claim_returns_already_terminal(api):
    """PRD 3.5: "`PAID`, `DENIED`, and `CANCELLED` are all terminal; any further
    transition attempt against them is `ERR_ALREADY_TERMINAL`."

    Design: Corner/state_machines/review_paid_claim_returns_already_terminal
    """
    ctx = setup_paid_claim(approved_duty_cents=32670)

    res = api.review_claim(ctx["claim"]["id"], {"outcome": "DENIED"}, BROKER)
    validate_error(res, ApiErrorId.ERR_ALREADY_TERMINAL)

    claim = validate_success(api.get_claim(ctx["claim"]["id"], ANALYST))
    assert claim["status"] == "PAID"


def test_cancel_filed_claim_returns_invalid_state(api):
    """PRD 3.5: "A claim still in `DRAFT` may instead be abandoned: an `Analyst`
    cancels it, the claim becomes `CANCELLED`, and every `ACTIVE` line is voided
    with the same compensation cascade as a denial."

    Design: Corner/state_machines/cancel_filed_claim_returns_invalid_state
    """
    ctx = setup_filed_claim(matched_quantity=40)

    res = api.cancel_claim(ctx["claim"]["id"], ANALYST)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)

    claim = validate_success(api.get_claim(ctx["claim"]["id"], ANALYST))
    assert claim["status"] == "FILED"


def test_claim_denial_voids_lines_and_restores_pools(api):
    """PRD 3.5: "An `outcome` of `DENIED` transitions the claim to its terminal
    `DENIED` state and voids every `ACTIVE` line with the full pool-and-quantity
    restoration cascade, freeing the merchandise for future claims."
    PRD 2.9: "Whenever a claim line is voided — whether individually while the
    claim is still a draft, or wholesale because the claim was denied or
    cancelled — the system runs a compensation cascade that restores the matched
    pools: the import entry's consumed quantity and unclaimed-duty figure are
    restored, the export shipment's consumed quantity and remaining value pool
    are restored, and every resource the cascade touches has its `updated_at`
    refreshed and its `version` incremented."

    Design: Corner/state_machines/claim_denial_voids_lines_and_restores_pools
    """
    ctx = setup_draft_claim_with_line(matched_quantity=40)
    add_claim_line(
        ctx["claim"]["id"], ctx["entry"]["id"], ctx["export"]["id"],
        matched_quantity=40,
    )
    file_claim(ctx["claim"]["id"])

    denied = validate_success(
        api.review_claim(ctx["claim"]["id"], {"outcome": "DENIED"}, BROKER)
    )
    assert denied["status"] == "DENIED"

    void_lines, meta_void = validate_paginated(
        api.list_claim_lines(
            ANALYST, params={"claim_id": ctx["claim"]["id"], "status": "VOID"}
        )
    )
    assert meta_void["total_count"] == 2
    _, meta_active = validate_paginated(
        api.list_claim_lines(
            ANALYST, params={"claim_id": ctx["claim"]["id"], "status": "ACTIVE"}
        )
    )
    assert meta_active["total_count"] == 0

    entry = validate_success(api.get_import_entry(ctx["entry"]["id"], ANALYST))
    assert entry["unclaimed_duty_cents"] == 82500
    assert entry["matched_quantity"] == 0
    assert entry["status"] == "UNMATCHED"


def test_audit_followup_cycle_request_more(api):
    """PRD 3.8: "Auditors frequently come back with follow-up questions: from
    `RESPONSE_FILED`, `REQUEST_MORE` returns the case to `EVIDENCE_GATHERING`,
    and this follow-up cycle may repeat indefinitely."
    PRD 3.8: "From `OPENED`, `START_EVIDENCE` moves the case to
    `EVIDENCE_GATHERING` and recomputes the client's open-audit count. From
    `EVIDENCE_GATHERING`, `FILE_RESPONSE` moves it to `RESPONSE_FILED` — but
    only if the logical clock has not passed `due_date`; the deadline is
    inclusive, so a response at the exact due second is permitted, and a later
    attempt is `ERR_RESPONSE_PAST_DUE`."

    Design: Corner/state_machines/audit_followup_cycle_request_more
    """
    client = onboard_client()
    case = add_audit_case(client["id"], due_date="2026-06-01T00:00:00Z")
    assert case["status"] == "OPENED"

    case = advance_audit(case["id"], "START_EVIDENCE")
    assert case["status"] == "EVIDENCE_GATHERING"
    case = advance_audit(case["id"], "FILE_RESPONSE")
    assert case["status"] == "RESPONSE_FILED"

    case = advance_audit(case["id"], "REQUEST_MORE")
    assert case["status"] == "EVIDENCE_GATHERING", (
        "the follow-up cycle reopens evidence collection"
    )
    case = advance_audit(case["id"], "FILE_RESPONSE")
    assert case["status"] == "RESPONSE_FILED"


def test_record_destroy_retained_rejected(api):
    """PRD 3.9: "Destruction is a two-step, sweep-mediated process, never an
    immediate one. When the ops sweep of §2.8 finds a `RETAINED` record whose
    `retention_until` is set and has been reached by the logical clock —
    inclusively — it flips the record to `ELIGIBLE_FOR_DESTRUCTION` and
    increments its `version`. Only then may a `ComplianceManager` certify
    destruction, moving the record to its terminal `DESTROYED` state; attempting
    destruction from any other status is rejected with
    `ERR_RECORD_NOT_ELIGIBLE`."

    Design: Corner/state_machines/record_destroy_retained_rejected
    """
    ctx = setup_paid_claim(approved_duty_cents=32670)
    records = get_records_for_claim(ctx["claim"]["id"])
    assert len(records) == 3
    rec = records[0]
    assert rec["status"] == "RETAINED"

    res = api.destroy_record(rec["id"], COMPLIANCE)
    validate_error(res, ApiErrorId.ERR_RECORD_NOT_ELIGIBLE)
