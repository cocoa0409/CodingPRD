"""Erasure-exposure risk scoring, fulfillment-progress percentage, and the two
validation-priority conflict pairs (segregation>undecided, state>processor)."""
import pytest

from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    TEST_USERS,
    make_privacy_officer_headers,
    setup_registry, create_request, create_request_under_review,
    create_request_fulfilling, create_request_in_discovery,
    add_confirmed_finding, complete_discovery, verify_request,
    get_item_for_finding, dispatch_ack_complete_item,
)

_PO = TEST_USERS["privacy_officer_headers"]
_IA = TEST_USERS["intake_agent_headers"]
_FW = TEST_USERS["fulfillment_worker_headers"]


def _deletion_fulfilling_two_findings(specs, intake_user_id, officer_user_id):
    """A DELETION request fanned out to FULFILLING with one ERASE item per
    confirmed finding in `specs`. Returns (request, processor, {key: item})."""
    controller, subject, processor = setup_registry("GDPR", with_processor=True)
    req = create_request(controller["id"], subject["id"], request_type="DELETION")
    verify_request(req["id"], intake_user_id=intake_user_id)
    findings = {}
    for spec in specs:
        findings[spec["key"]] = add_confirmed_finding(
            req["id"], processor["id"],
            data_category=spec["data_category"], record_count=spec["record_count"])
    complete_discovery(req["id"])
    cur = validate_success(_get(req["id"]), 200)
    officer = make_privacy_officer_headers(officer_user_id)
    validate_success(
        _dispatch(req["id"], cur["version"], officer), 200)
    items = {key: get_item_for_finding(f["id"]) for key, f in findings.items()}
    return req, processor, items


_api_ref = None


def _bind(api):
    global _api_ref
    _api_ref = api


def _get(req_id):
    return _api_ref.get_dsar_request(req_id, _PO)


def _dispatch(req_id, version, headers):
    return _api_ref.dispatch_fulfillment(req_id, {"expected_request_version": version}, headers)


def test_erasure_residual_diverges_completed_vs_uncompleted(api):
    """PRD §3.7: "The residual figure sums, over every ERASE item whose state is
    QUEUED, DISPATCHED, BLOCKED, or SKIPPED_EXEMPT, that item's category weight
    multiplied by its record_count; an item that has reached COMPLETED is fully
    remediated and contributes nothing to residual. The total figure sums the same
    weighted product over all ERASE items regardless of state."

    Design: Difficulty/dual_variant_calc/erasure_residual_diverges_completed_vs_uncompleted
    """
    _bind(api)
    # HEALTH x2 (still QUEUED) + FINANCIAL x3 (COMPLETED).
    req, processor, items = _deletion_fulfilling_two_findings(
        [{"key": "health", "data_category": "HEALTH", "record_count": 2},
         {"key": "fin", "data_category": "FINANCIAL", "record_count": 3}],
        intake_user_id="intake-er1", officer_user_id="officer-er1")
    dispatch_ack_complete_item(items["fin"]["id"])  # FINANCIAL completed
    risk = validate_success(api.get_dsar_risk(req["id"], _PO), 200)
    # residual = HEALTH 5*2 = 10 ; total = 10 + FINANCIAL 4*3 = 22 ; 100*10/22 = 45.45
    assert risk["residual_weighted"] == 10
    assert risk["total_weighted"] == 22
    assert risk["erasure_exposure_score"] == pytest.approx(45.45, abs=0.001)


def test_erasure_score_all_residual_when_nothing_completed_is_100(api):
    """PRD §3.7: "an item that has reached COMPLETED is fully remediated and
    contributes nothing to residual. The total figure sums the same weighted
    product over all ERASE items regardless of state."

    Design: Difficulty/combinatorial_formula/erasure_score_three_input_nonlinear_weighting
    """
    _bind(api)
    # IDENTITY x1 (QUEUED) + CONTACT x2 (QUEUED); nothing COMPLETED -> residual==total.
    req, processor, items = _deletion_fulfilling_two_findings(
        [{"key": "ident", "data_category": "IDENTITY", "record_count": 1},
         {"key": "contact", "data_category": "CONTACT", "record_count": 2}],
        intake_user_id="intake-er-full", officer_user_id="officer-er-full")
    risk = validate_success(api.get_dsar_risk(req["id"], _PO), 200)
    # residual = total = IDENTITY 3*1 + CONTACT 2*2 = 7 ; 100*7/7 = 100.00
    assert risk["residual_weighted"] == 7
    assert risk["total_weighted"] == 7
    assert risk["erasure_exposure_score"] == pytest.approx(100.00, abs=0.001)


def test_erasure_score_identity_blocked_contact_completed_42_86(api):
    """PRD §3.7: "Each data category has a sensitivity weight: HEALTH is 5,
    FINANCIAL is 4, IDENTITY is 3, CONTACT is 2, and BEHAVIORAL is 1 ... the
    division performed first, and a single half-up rounding to two decimal places
    applied to the percentage."

    Design: Difficulty/combinatorial_formula/erasure_score_three_input_nonlinear_weighting
    """
    _bind(api)
    controller, subject, processor = setup_registry("GDPR", with_processor=True)
    validate_success(
        api.create_legal_hold(
            {"controller_id": controller["id"], "data_subject_id": subject["id"],
             "matter_reference": "M-er2", "data_categories": ["IDENTITY"]}, _PO), 201)
    req = create_request(controller["id"], subject["id"], request_type="DELETION")
    verify_request(req["id"], intake_user_id="intake-er2b")
    f_id = add_confirmed_finding(req["id"], processor["id"],
                                 data_category="IDENTITY", record_count=1)
    f_ct = add_confirmed_finding(req["id"], processor["id"],
                                 data_category="CONTACT", record_count=2)
    complete_discovery(req["id"])
    cur = validate_success(api.get_dsar_request(req["id"], _PO), 200)
    officer = make_privacy_officer_headers("officer-er2b")
    validate_success(
        api.dispatch_fulfillment(req["id"], {"expected_request_version": cur["version"]}, officer), 200)
    item_id_id = get_item_for_finding(f_id["id"])   # IDENTITY -> BLOCKED
    item_ct = get_item_for_finding(f_ct["id"])      # CONTACT -> QUEUED
    assert item_id_id["state"] == "BLOCKED"
    dispatch_ack_complete_item(item_ct["id"])       # CONTACT completed
    risk = validate_success(api.get_dsar_risk(req["id"], _PO), 200)
    # residual = IDENTITY 3*1 = 3 ; total = 3 + CONTACT 2*2 = 7 ; 100*3/7 = 42.86
    assert risk["residual_weighted"] == 3
    assert risk["total_weighted"] == 7
    assert risk["erasure_exposure_score"] == pytest.approx(42.86, abs=0.001)


def test_fulfillment_progress_sum_then_round_two_thirds(api):
    """PRD §3.7: "it is one hundred multiplied by the number of items in COMPLETED
    or SKIPPED_EXEMPT, divided by the total number of items, with the division
    performed first and the resulting percentage rounded half up to two decimal
    places."

    Design: Difficulty/combinatorial_formula/fulfillment_progress_sum_then_round_two_thirds
    """
    _bind(api)
    ctx = create_request_fulfilling(
        jurisdiction="GDPR", request_type="ACCESS",
        findings=[{"data_category": "IDENTITY", "record_count": 1, "confidence": "EXACT"},
                  {"data_category": "CONTACT", "record_count": 1, "confidence": "EXACT"},
                  {"data_category": "BEHAVIORAL", "record_count": 1, "confidence": "EXACT"}],
        intake_user_id="intake-prog", officer_user_id="officer-prog")
    findings = ctx["findings"]
    item1 = get_item_for_finding(findings[0]["id"])
    item2 = get_item_for_finding(findings[1]["id"])
    dispatch_ack_complete_item(item1["id"])
    dispatch_ack_complete_item(item2["id"])
    data = validate_success(api.get_dsar_request(ctx["request"]["id"], _PO), 200)
    # 2 of 3 terminal -> round(100*2/3, 2) = 66.67
    assert data["fulfillment_progress_pct"] == pytest.approx(66.67, abs=0.001)


def test_fulfillment_progress_zero_when_no_items(api):
    """PRD §3.7: "When the request has no fulfillment items, this figure is 0.00."

    Design: Corner/calculations/fulfillment_progress_zero_when_no_items
    """
    ctx = create_request_in_discovery(intake_user_id="intake-prog0")
    data = validate_success(api.get_dsar_request(ctx["request"]["id"], _PO), 200)
    assert data["fulfillment_progress_pct"] == pytest.approx(0.00, abs=0.001)


# --------------------------------------------------------------------------
# Priority-pair validation conflicts
# --------------------------------------------------------------------------
def test_segregation_beats_undecided_exemption_on_dispatch(api):
    """PRD §3.9: "Only after these structural checks do the domain rules apply — the
    deadline check (ERR_DEADLINE_PASSED), segregation of duties
    (ERR_SEGREGATION_OF_DUTIES), attempt exhaustion ... the undecided-exemption,
    unresolved-findings, no-findings ... guards".
    PRD §3.5: "dispatching with the same X-User-ID that verified identity is refused
    with ERR_SEGREGATION_OF_DUTIES."

    Design: Difficulty/priority_pair_validation_conflict/segregation_beats_undecided_exemption_on_dispatch
    """
    # Same user verifies AND dispatches (segregation violation) while an exemption
    # remains ASSERTED (undecided). Segregation (priority 6) outranks
    # undecided-exemption (priority 10).
    shared = "shared-seg"
    ctx = create_request_under_review(
        jurisdiction="GDPR", request_type="ACCESS",
        findings=[{"data_category": "IDENTITY", "record_count": 1, "confidence": "EXACT"}],
        intake_user_id=shared)
    req = ctx["request"]
    validate_success(
        api.create_exemption(req["id"], {"data_category": "IDENTITY", "basis": "TRADE_SECRET"}, _PO), 201)
    cur = validate_success(api.get_dsar_request(req["id"], _PO), 200)
    officer = make_privacy_officer_headers(shared)
    resp = api.dispatch_fulfillment(req["id"], {"expected_request_version": cur["version"]}, officer)
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)
    after = validate_success(api.get_dsar_request(req["id"], _PO), 200)
    assert after["status"] == "UNDER_REVIEW"


def test_invalid_state_beats_processor_suspended_on_dispatch_item(api):
    """PRD §3.9: "State validity is then checked: a target not in a valid state for
    the requested transition yields ERR_INVALID_STATE. Only after these structural
    checks do the domain rules apply — ... the ... processor-suspended ... guards".

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_processor_suspended_on_dispatch_item
    """
    ctx = create_request_fulfilling(intake_user_id="intake-isp",
                                    officer_user_id="officer-isp")
    item = ctx["items"][0]
    # Drive the item to COMPLETED, then suspend its processor.
    completed = dispatch_ack_complete_item(item["id"])
    assert completed["state"] == "COMPLETED"
    validate_success(api.suspend_processor(ctx["processor"]["id"], _PO), 200)
    cur = validate_success(api.get_fulfillment_item(item["id"], _PO), 200)
    # A redundant dispatch on a COMPLETED item whose processor is SUSPENDED:
    # state-validity (priority 4) outranks processor-suspended (priority 12).
    resp = api.dispatch_item(item["id"], {"expected_item_version": cur["version"]}, _FW)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)
    after = validate_success(api.get_fulfillment_item(item["id"], _PO), 200)
    assert after["state"] == "COMPLETED"
