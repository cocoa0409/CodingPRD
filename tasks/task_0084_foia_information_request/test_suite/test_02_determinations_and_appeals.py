"""Determination branching, appeal adjudication, remand/reverse cascades, Reverse FOIA.

Difficulty queue: non_linear_state_machine, transitive_cascade, cross_entity_state_dependency,
compensating_invariant (release count). Corner queue: state_machines transitions for glomar,
withdraw, review, objections, appeals.
"""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_error_is_one_of,
    ApiErrorId, fixtures,
)


# ─────────────────────────────────────────────────────
# Difficulty/non_linear_state_machine/appeal_remand_cycles_request_back_to_processing
# ─────────────────────────────────────────────────────
def test_remand_cycles_denied_request_back_to_processing(api):
    """PRD §3.7: "When an appeal on a request that is in `DENIED` or `PARTIALLY_GRANTED` is
    remanded, the request reopens to `PROCESSING`, every one of its responsive records is
    reset to `PENDING`, the deadline dimension returns to `RUNNING`".
    PRD §3.7: "a remand turns a determination-state request back into a working case."

    Design: Difficulty/non_linear_state_machine/appeal_remand_cycles_request_back_to_processing
    """
    ctx = fixtures.setup_denied_appeal_under_review(num_withheld=1, exemption_code="B5")
    appeal = fixtures.decide_appeal(ctx["authority_headers"], ctx["appeal"]["id"], "REMAND")
    assert appeal["status"] == "REMANDED", appeal

    req = validate_success(api.get_request(ctx["request"]["id"], ctx["officer_headers"]))
    assert req["status"] == "PROCESSING", req
    assert req["deadline_status"] == "RUNNING", req
    rec = validate_success(api.get_record(ctx["records"][0]["id"], ctx["officer_headers"]))
    assert rec["disposition"] == "PENDING", rec


def test_remand_resets_record_disposition(api):
    """PRD §3.7: "every one of its responsive records is reset to `PENDING`".
    PRD §3.3: "Dispositions remain mutable until a determination is issued, and a remand
    resets them all to `PENDING`."

    Design: Difficulty/non_linear_state_machine/appeal_remand_cycles_request_back_to_processing
    """
    ctx = fixtures.setup_denied_appeal_under_review(num_withheld=1, exemption_code="B5")
    fixtures.decide_appeal(ctx["authority_headers"], ctx["appeal"]["id"], "REMAND")
    rec = validate_success(api.get_record(ctx["records"][0]["id"], ctx["officer_headers"]))
    assert rec["disposition"] == "PENDING", rec


# ─────────────────────────────────────────────────────
# Difficulty/non_linear_state_machine/request_determination_branches_three_ways
# ─────────────────────────────────────────────────────
def test_determination_partial_grant_mixed_dispositions(api):
    """PRD §3.6: "It produces a partial grant, transitioning to `PARTIALLY_GRANTED`, when at
    least one record is `REDACTED` or `RELEASABLE` and at least one record is `REDACTED` or
    `WITHHELD` — that is, a genuine mix of disclosure and withholding."

    Design: Difficulty/non_linear_state_machine/request_determination_branches_three_ways
    """
    ctx = fixtures.create_processing_request(fee_category="OTHER")
    off_h = ctx["officer_headers"]
    rid = ctx["request"]["id"]
    rec_rel = fixtures.add_record(off_h, rid, title="Releasable doc", page_count=2)
    rec_wh = fixtures.add_record(off_h, rid, title="Personnel file", page_count=4)
    fixtures.add_record_exemption(off_h, rid, rec_wh["id"], exemption_code="B6", justification="personal privacy")
    fixtures.review_record(off_h, rec_rel["id"], "RELEASABLE")
    fixtures.review_record(off_h, rec_wh["id"], "WITHHELD")
    result = fixtures.issue_determination(off_h, rid)
    assert result["status"] == "PARTIALLY_GRANTED", result


def test_determination_full_grant_all_releasable(api):
    """PRD §3.6: "A determination produces a full grant, transitioning the request from
    `PROCESSING` to `GRANTED`, when every responsive record is `RELEASABLE`."

    Design: Difficulty/non_linear_state_machine/request_determination_branches_three_ways
    """
    ctx = fixtures.create_processing_request(fee_category="OTHER")
    off_h = ctx["officer_headers"]
    rid = ctx["request"]["id"]
    rec = fixtures.add_record(off_h, rid, title="Open doc", page_count=1)
    fixtures.review_record(off_h, rec["id"], "RELEASABLE")
    result = fixtures.issue_determination(off_h, rid)
    assert result["status"] == "GRANTED", result


def test_determination_full_denial_all_withheld(api):
    """PRD §3.6: "It produces a full denial, transitioning to `DENIED`, when every record is
    `WITHHELD`."

    Design: Difficulty/non_linear_state_machine/request_determination_branches_three_ways
    """
    ctx = fixtures.create_processing_request(fee_category="OTHER")
    off_h = ctx["officer_headers"]
    rid = ctx["request"]["id"]
    rec = fixtures.add_record(off_h, rid, title="Memo", page_count=1)
    fixtures.add_record_exemption(off_h, rid, rec["id"], exemption_code="B5")
    fixtures.review_record(off_h, rec["id"], "WITHHELD")
    result = fixtures.issue_determination(off_h, rid)
    assert result["status"] == "DENIED", result


# ─────────────────────────────────────────────────────
# Difficulty/transitive_cascade/remand_cascade_appeal_request_records_depth3
# ─────────────────────────────────────────────────────
def test_remand_cascade_depth3_partial_to_processing(api):
    """PRD §3.7: "A `REMAND` decision moves the appeal to `REMANDED` and triggers the
    request's remand reset."
    PRD §3.7: "When an appeal on a request that is in `DENIED` or `PARTIALLY_GRANTED` is
    remanded, the request reopens to `PROCESSING`, every one of its responsive records is
    reset to `PENDING`, the deadline dimension returns to `RUNNING`".

    Design: Difficulty/transitive_cascade/remand_cascade_appeal_request_records_depth3
    """
    ctx = fixtures.setup_partial_appeal_under_review()
    appeal = fixtures.decide_appeal(ctx["authority_headers"], ctx["appeal"]["id"], "REMAND")
    assert appeal["status"] == "REMANDED", appeal

    req = validate_success(api.get_request(ctx["request"]["id"], ctx["officer_headers"]))
    assert req["status"] == "PROCESSING", req
    red = validate_success(api.get_record(ctx["redacted_record"]["id"], ctx["officer_headers"]))
    rel = validate_success(api.get_record(ctx["releasable_record"]["id"], ctx["officer_headers"]))
    assert red["disposition"] == "PENDING", red
    assert rel["disposition"] == "PENDING", rel


def test_remand_cascade_returns_deadline_to_running(api):
    """PRD §3.7: "the deadline dimension returns to `RUNNING`".

    Design: Difficulty/transitive_cascade/remand_cascade_appeal_request_records_depth3
    """
    ctx = fixtures.setup_partial_appeal_under_review()
    fixtures.decide_appeal(ctx["authority_headers"], ctx["appeal"]["id"], "REMAND")
    req = validate_success(api.get_request(ctx["request"]["id"], ctx["officer_headers"]))
    assert req["deadline_status"] == "RUNNING", req


# ─────────────────────────────────────────────────────
# Difficulty/transitive_cascade/sustain_cascade_objection_record_exemption_depth2
# ─────────────────────────────────────────────────────
def test_sustain_cascade_withholds_record_and_creates_b4(api):
    """PRD §3.8: "A `SUSTAIN` resolution moves the objection from `OBJECTED` to `SUSTAINED`,
    sets the linked record's disposition to `WITHHELD`, and creates a record-scoped exemption
    with code `B4` citing that record so the withheld record has the citation it requires".

    Design: Difficulty/transitive_cascade/sustain_cascade_objection_record_exemption_depth2
    """
    ctx = fixtures.setup_objected_record()
    obj = fixtures.resolve_objection(ctx["officer_headers"], ctx["objection"]["id"], "SUSTAIN")
    assert obj["status"] == "SUSTAINED", obj

    rec = validate_success(api.get_record(ctx["record"]["id"], ctx["officer_headers"]))
    assert rec["disposition"] == "WITHHELD", rec

    exemptions, _ = validate_paginated_or_list(
        api.list_exemptions(ctx["officer_headers"], params={"record_id": ctx["record"]["id"]})
    )
    assert any(e["exemption_code"] == "B4" for e in exemptions), exemptions


def test_sustain_sets_objection_status(api):
    """PRD §3.8: "A `SUSTAIN` resolution moves the objection from `OBJECTED` to `SUSTAINED`".

    Design: Difficulty/transitive_cascade/sustain_cascade_objection_record_exemption_depth2
    """
    ctx = fixtures.setup_objected_record()
    obj = fixtures.resolve_objection(ctx["officer_headers"], ctx["objection"]["id"], "SUSTAIN")
    assert obj["status"] == "SUSTAINED", obj


# ─────────────────────────────────────────────────────
# Difficulty/cross_entity_state_dependency/determination_depends_on_record_dispositions
# ─────────────────────────────────────────────────────
def test_determination_blocked_by_pending_record(api):
    """PRD §3.6: "A determination produces a full grant, transitioning the request from
    `PROCESSING` to `GRANTED`, when every responsive record is `RELEASABLE`."
    PRD §3.6: "It produces a partial grant, transitioning to `PARTIALLY_GRANTED`, when at
    least one record is `REDACTED` or `RELEASABLE` and at least one record is `REDACTED` or
    `WITHHELD` — that is, a genuine mix of disclosure and withholding."

    With one RELEASABLE and one still-PENDING record, no determination branch matches, so the
    transition is rejected with ERR_INVALID_STATE.

    Design: Difficulty/cross_entity_state_dependency/determination_depends_on_record_dispositions
    """
    ctx = fixtures.create_processing_request(fee_category="OTHER")
    off_h = ctx["officer_headers"]
    rid = ctx["request"]["id"]
    rec_a = fixtures.add_record(off_h, rid, title="Doc A", page_count=1)
    fixtures.add_record(off_h, rid, title="Doc B", page_count=1)  # left PENDING
    fixtures.review_record(off_h, rec_a["id"], "RELEASABLE")
    v0 = fixtures.current_version(off_h, rid)
    resp = api.issue_determination(rid, {"expected_request_version": v0}, off_h)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_determination_succeeds_when_no_pending(api):
    """PRD §3.6: "A determination produces a full grant, transitioning the request from
    `PROCESSING` to `GRANTED`, when every responsive record is `RELEASABLE`."

    Design: Difficulty/cross_entity_state_dependency/determination_depends_on_record_dispositions
    """
    ctx = fixtures.create_processing_request(fee_category="OTHER")
    off_h = ctx["officer_headers"]
    rid = ctx["request"]["id"]
    rec_a = fixtures.add_record(off_h, rid, title="Doc A", page_count=1)
    rec_b = fixtures.add_record(off_h, rid, title="Doc B", page_count=1)
    fixtures.review_record(off_h, rec_a["id"], "RELEASABLE")
    fixtures.review_record(off_h, rec_b["id"], "RELEASABLE")
    result = fixtures.issue_determination(off_h, rid)
    assert result["status"] == "GRANTED", result


# ─────────────────────────────────────────────────────
# Difficulty/cross_entity_state_dependency/record_release_depends_on_objection_state
# ─────────────────────────────────────────────────────
def test_record_release_blocked_by_objected_objection(api):
    """PRD §3.8: "the Reverse-FOIA gate means a submitter-info record cannot be made
    releasable, and cannot be released by a determination, while its objection is still
    `NOTICED` or `OBJECTED`; such an attempt is rejected with `ERR_REVERSE_FOIA_PENDING`."

    Design: Difficulty/cross_entity_state_dependency/record_release_depends_on_objection_state
    """
    ctx = fixtures.setup_objected_record()
    resp = api.review_record(ctx["record"]["id"], {"disposition": "RELEASABLE"}, ctx["officer_headers"])
    validate_error(resp, ApiErrorId.ERR_REVERSE_FOIA_PENDING.value)


def test_record_release_blocked_while_noticed(api):
    """PRD §3.8: "the Reverse-FOIA gate means a submitter-info record cannot be made
    releasable, and cannot be released by a determination, while its objection is still
    `NOTICED` or `OBJECTED`; such an attempt is rejected with `ERR_REVERSE_FOIA_PENDING`."

    Design: Difficulty/cross_entity_state_dependency/record_release_depends_on_objection_state
    """
    ctx = fixtures.create_processing_request(fee_category="OTHER")
    off_h = ctx["officer_headers"]
    submitter, _ = fixtures.create_submitter(off_h)
    record = fixtures.add_submitter_record(off_h, ctx["request"]["id"], submitter["id"])
    fixtures.open_objection(off_h, record["id"], submitter["id"])  # status NOTICED
    resp = api.review_record(record["id"], {"disposition": "RELEASABLE"}, off_h)
    validate_error(resp, ApiErrorId.ERR_REVERSE_FOIA_PENDING.value)


# ─────────────────────────────────────────────────────
# Difficulty/compensating_invariant/remand_reverse_conserves_release_count_invariant
# ─────────────────────────────────────────────────────
def test_reverse_releases_all_records_and_grants(api):
    """PRD §3.7: "A `REVERSE` decision moves the appeal to `REVERSED` and cascades to the
    underlying case: every responsive record on the request is set to `RELEASABLE` and the
    request's status is set to `GRANTED` to reflect the ordered full release."

    Design: Difficulty/compensating_invariant/remand_reverse_conserves_release_count_invariant
    """
    ctx = fixtures.setup_denied_appeal_under_review(num_withheld=2, exemption_code="B5")
    appeal = fixtures.decide_appeal(ctx["authority_headers"], ctx["appeal"]["id"], "REVERSE")
    assert appeal["status"] == "REVERSED", appeal

    req = validate_success(api.get_request(ctx["request"]["id"], ctx["officer_headers"]))
    assert req["status"] == "GRANTED", req

    records, _ = validate_paginated_or_list(
        api.list_request_records(ctx["request"]["id"], ctx["officer_headers"])
    )
    assert len(records) == 2, records  # count unchanged
    assert all(r["disposition"] == "RELEASABLE" for r in records), records  # unreleased 2 -> 0


def test_reverse_record_count_unchanged(api):
    """PRD §3.7: "every responsive record on the request is set to `RELEASABLE` and the
    request's status is set to `GRANTED` to reflect the ordered full release."

    Design: Difficulty/compensating_invariant/remand_reverse_conserves_release_count_invariant
    """
    ctx = fixtures.setup_denied_appeal_under_review(num_withheld=2, exemption_code="B5")
    fixtures.decide_appeal(ctx["authority_headers"], ctx["appeal"]["id"], "REVERSE")
    records, _ = validate_paginated_or_list(
        api.list_request_records(ctx["request"]["id"], ctx["officer_headers"])
    )
    assert len(records) == 2, records


# ─────────────────────────────────────────────────────
# Corner/state_machines: glomar, withdraw, review, objection, appeal
# ─────────────────────────────────────────────────────
def test_glomar_happy_path_sets_basis(api):
    """PRD §3.6: "A successful Glomar transitions the request from `PROCESSING` to
    `GLOMAR_INVOKED`, sets `glomar_exemption_basis` to the request-level exemption's code".

    Design: Corner/state_machines/glomar_happy_path_sets_basis
    """
    ctx = fixtures.create_processing_request(fee_category="OTHER", officer_can_invoke_glomar=True)
    off_h = ctx["officer_headers"]
    rid = ctx["request"]["id"]
    fixtures.add_request_exemption(off_h, rid, exemption_code="B1", justification="classified")
    v0 = fixtures.current_version(off_h, rid)
    result = validate_success(api.invoke_glomar(rid, {"expected_request_version": v0}, off_h))
    assert result["status"] == "GLOMAR_INVOKED", result
    assert result["glomar_exemption_basis"] == "B1", result


def test_glomar_requires_authorized_officer(api):
    """PRD §3.6: "The acting officer must be cleared to invoke Glomar — that is, their
    `can_invoke_glomar` must be true — or the attempt is rejected with
    `ERR_GLOMAR_NOT_AUTHORIZED`."

    Design: Corner/state_machines/glomar_requires_authorized_officer
    """
    # Cleared officer perfects/assigns and asserts the request-level exemption; an
    # un-cleared officer then attempts the Glomar.
    ctx = fixtures.create_processing_request(fee_category="OTHER", officer_can_invoke_glomar=True)
    off_h = ctx["officer_headers"]
    rid = ctx["request"]["id"]
    fixtures.add_request_exemption(off_h, rid, exemption_code="B1", justification="national security")
    no_glo, no_glo_h = fixtures.create_officer(can_invoke_glomar=False)
    v0 = fixtures.current_version(off_h, rid)
    resp = api.invoke_glomar(rid, {"expected_request_version": v0}, no_glo_h)
    validate_error(resp, ApiErrorId.ERR_GLOMAR_NOT_AUTHORIZED.value)


def test_glomar_with_records_logged_rejected(api):
    """PRD §3.6: "Because the agency is neither confirming nor denying existence, no
    responsive record may have been logged for the request ... if records have been logged
    or that single request-level B1/B7 exemption is not present, the attempt is rejected with
    `ERR_GLOMAR_PRECONDITION`."

    Design: Corner/state_machines/glomar_with_records_logged_rejected
    """
    ctx = fixtures.create_processing_request(fee_category="OTHER", officer_can_invoke_glomar=True)
    off_h = ctx["officer_headers"]
    rid = ctx["request"]["id"]
    fixtures.add_record(off_h, rid, title="doc", page_count=1)
    fixtures.add_request_exemption(off_h, rid, exemption_code="B7", justification="law enforcement existence")
    v0 = fixtures.current_version(off_h, rid)
    resp = api.invoke_glomar(rid, {"expected_request_version": v0}, off_h)
    validate_error(resp, ApiErrorId.ERR_GLOMAR_PRECONDITION.value)


def test_withdraw_from_processing_terminal(api):
    """PRD §3.2: "Withdrawal moves the request to the terminal `WITHDRAWN` state, sets the
    deadline dimension to `MET` to reflect that no further obligation remains".

    Design: Corner/state_machines/withdraw_from_processing_terminal
    """
    ctx = fixtures.create_processing_request(fee_category="OTHER")
    result = fixtures.withdraw_request(ctx["requester_headers"], ctx["request"]["id"])
    assert result["status"] == "WITHDRAWN", result
    assert result["deadline_status"] == "MET", result


def test_withdraw_from_terminal_rejected(api):
    """PRD §3.2: "A request may be withdrawn by its owning requester at any point before a
    determination is reached — that is, while it is in `SUBMITTED`, `PERFECTED`, `PROCESSING`,
    or `AWAITING_PAYMENT`."

    A second withdraw on an already-WITHDRAWN request is no longer in a withdrawable state, so
    it is rejected with ERR_INVALID_STATE.

    Design: Corner/state_machines/withdraw_from_terminal_withdrawn_rejected
    """
    officer, off_h, requester, req_h, request = fixtures.create_submitted_request()
    validate_success(api.withdraw_request(request["id"], req_h))
    resp = api.withdraw_request(request["id"], req_h)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_review_to_redacted_requires_exemption(api):
    """PRD §3.3: "A record moves from `PENDING` to `REDACTED` or to `WITHHELD` only when at
    least one exemption with `applies_to_kind` `RECORD` cites it; an attempt to redact or
    withhold a record that no exemption cites is rejected with `ERR_EXEMPTION_REQUIRED`."

    Design: Corner/state_machines/review_record_to_redacted_requires_exemption
    """
    ctx = fixtures.create_processing_request(fee_category="OTHER")
    off_h = ctx["officer_headers"]
    rec = fixtures.add_record(off_h, ctx["request"]["id"], title="doc", page_count=2)
    resp = api.review_record(rec["id"], {"disposition": "REDACTED"}, off_h)
    validate_error(resp, ApiErrorId.ERR_EXEMPTION_REQUIRED.value)


def test_objection_overrule_permits_release(api):
    """PRD §3.8: "An `OVERRULE` resolution moves the objection from `OBJECTED` to `OVERRULED`,
    which lifts the Reverse-FOIA gate so the linked record becomes eligible to be made
    releasable".

    Design: Corner/state_machines/objection_overrule_permits_release
    """
    ctx = fixtures.setup_objected_record()
    obj = fixtures.resolve_objection(ctx["officer_headers"], ctx["objection"]["id"], "OVERRULE")
    assert obj["status"] == "OVERRULED", obj
    rec = fixtures.review_record(ctx["officer_headers"], ctx["record"]["id"], "RELEASABLE")
    assert rec["disposition"] == "RELEASABLE", rec


def test_objection_lapse_after_window(api):
    """PRD §3.8: "Lapsing requires the objection to still be `NOTICED` and requires that the
    present moment be at or after the notice instant plus 10 calendar days (the reverse-notice
    window). Lapsing moves the objection from `NOTICED` to `NO_RESPONSE`".

    Design: Corner/state_machines/objection_lapse_after_window
    """
    officer, off_h = fixtures.create_officer()
    fixtures.set_clock(off_h, "2026-03-01T00:00:00.000Z")
    submitter, _ = fixtures.create_submitter(off_h)
    requester, _ = fixtures.create_requester(off_h, declared_category="OTHER")
    request = fixtures.submit_request(off_h, requester, received_at="2026-01-05T00:00:00.000Z")
    fixtures.perfect_request(off_h, request["id"], fee_category="OTHER")
    fixtures.assign_request(off_h, request["id"])
    record = fixtures.add_submitter_record(off_h, request["id"], submitter["id"], title="pricing", page_count=1)
    objection = fixtures.open_objection(off_h, record["id"], submitter["id"])
    fixtures.set_clock(off_h, "2026-03-12T00:00:00.000Z")  # 11 days after notice
    obj = validate_success(api.lapse_objection(objection["id"], off_h))
    assert obj["status"] == "NO_RESPONSE", obj


def test_appeal_affirm_keeps_determination(api):
    """PRD §3.7: "An `AFFIRM` decision moves the appeal to `AFFIRMED`; the original
    determination stands and the request remains in its determination state."

    Design: Corner/state_machines/appeal_affirm_keeps_determination
    """
    ctx = fixtures.setup_denied_appeal_under_review(num_withheld=1, exemption_code="B5")
    appeal = fixtures.decide_appeal(ctx["authority_headers"], ctx["appeal"]["id"], "AFFIRM")
    assert appeal["status"] == "AFFIRMED", appeal
    req = validate_success(api.get_request(ctx["request"]["id"], ctx["officer_headers"]))
    assert req["status"] == "DENIED", req


# ─── local helper: GET list endpoints return the standard paginated array envelope ───
def validate_paginated_or_list(resp):
    assert resp.status_code == 200, resp.text
    body = resp.json()
    data = body.get("data", [])
    meta = body.get("meta", {})
    return data, meta
