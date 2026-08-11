"""Action items: verification loop, evidence, SLA due dates, overdue semantics."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_evidence_item,
    create_evidence_payload,
    get_action_item,
    get_unit,
    make_auditor_headers,
    make_manager_headers,
    make_requester_headers,
    new_audit,
    drive_audit_to_reported,
    list_audit_findings,
    new_manual_item,
    new_personnel,
    new_unit,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
    verify_item,
    work_item_to_submitted,
)

MANAGER = TEST_USERS["manager_headers"]


def _unit_with_open_item(priority="P1", due_in_days=None):
    unit = new_unit(name="U", unit_code="U1", pha_cycle_months=12)
    req = new_personnel("Req", "E-REQ")
    item = new_manual_item(unit["id"], req["id"], priority=priority, due_in_days=due_in_days)
    return unit, req, item


class TestVerificationRejectionLoop:
    def test_verification_rejection_loop_returns_work(self, api):
        """PRD §3.9: "The manager may instead reject the verification, returning
        the item to `REJECTED` with `completer_id` retained for audit and no count
        changes — the assignee then restarts the loop."
        PRD §3.9: "The assignee — whose `X-User-ID` must match `assignee_id`
        (`ERR_NOT_RESOURCE_OWNER`) and who acts under one of the six entity-backed
        roles — starts work from `OPEN`, and equally restarts from `REJECTED`
        after a verification rejection, landing in `IN_PROGRESS`
        (`ERR_ACTION_ITEM_INVALID_STATE` from any other state)."

        Design: Difficulty/non_linear_state_machine/action_item_verification_reopen_cycle
        """
        unit, req, item = _unit_with_open_item()
        work_item_to_submitted(item["id"], req["id"], file_ref="s3://ev/photo1.jpg")

        validate_success(api.reject_verification(item["id"], MANAGER), 200)
        rejected = get_action_item(item["id"])
        assert rejected["status"] == "REJECTED"
        assert rejected["completer_id"] == req["id"]
        assert get_unit(unit["id"])["open_action_count"] == 1, (
            "rejection changes no counts — the item is still open-class"
        )

        restarted = validate_success(
            api.start_action_item(item["id"], make_requester_headers(req["id"])), 200)
        assert restarted["status"] == "IN_PROGRESS"

    def test_verify_reopen_cycle_accumulates_reopen_count(self, api):
        """PRD §3.9: "Reopening is verification's compensating action: a manager
        moves a `VERIFIED_CLOSED` item back to `IN_PROGRESS` (supplying a
        `reason`), `reopen_count` — which starts at zero — increments by one, the
        open count and index move back up" — the compensating half of verify.

        Design: Difficulty/non_linear_state_machine/action_item_verification_reopen_cycle
        """
        unit, req, item = _unit_with_open_item()
        work_item_to_submitted(item["id"], req["id"])
        validate_success(api.reject_verification(item["id"], MANAGER), 200)
        validate_success(api.start_action_item(item["id"], make_requester_headers(req["id"])), 200)
        validate_success(api.submit_verification(item["id"], make_requester_headers(req["id"])), 200)
        verify_item(item["id"])
        assert get_action_item(item["id"])["status"] == "VERIFIED_CLOSED"
        assert get_unit(unit["id"])["open_action_count"] == 0

        reopened = validate_success(api.reopen_action_item(item["id"], {"reason": "Evidence expired"}, MANAGER), 200)
        assert reopened["status"] == "IN_PROGRESS"
        assert reopened["reopen_count"] == 1
        assert get_unit(unit["id"])["open_action_count"] == 1


class TestVerifyReopenCountInvariant:
    def test_verify_decrements_open_count(self, api):
        """PRD §3.9: "A verified item lands in the terminal `VERIFIED_CLOSED`
        status with `verifier_id` recorded, the unit's `open_action_count`
        decrements, the index is recomputed, and the source bubble-ups fire" —
        PRD §2.11: "verifying then later reopening an action item conserves the
        unit's open-action count across the pair — what verify removes, reopen
        restores."

        Design: Difficulty/compensating_invariant/action_item_verify_reopen_count_invariant
        """
        unit, req, item = _unit_with_open_item()
        assert get_unit(unit["id"])["open_action_count"] == 1
        work_item_to_submitted(item["id"], req["id"])
        verified = verify_item(item["id"])
        assert verified["status"] == "VERIFIED_CLOSED"
        assert get_unit(unit["id"])["open_action_count"] == 0, "verify must remove 1 from the open count"

    def test_reopen_restores_open_count(self, api):
        """PRD §2.11: "verifying then later reopening an action item conserves the
        unit's open-action count across the pair — what verify removes, reopen
        restores." After the pair, the count equals the number of the unit's
        items in open-class states (`OPEN`, `IN_PROGRESS`,
        `SUBMITTED_FOR_VERIFICATION`, or `REJECTED`, PRD §3.9) — here exactly the
        one reopened item, and its `reopen_count` is 1.

        Design: Difficulty/compensating_invariant/action_item_verify_reopen_count_invariant
        """
        unit, req, item = _unit_with_open_item()
        work_item_to_submitted(item["id"], req["id"])
        verify_item(item["id"])
        validate_success(api.reopen_action_item(item["id"], {"reason": "audit query"}, MANAGER), 200)

        unit_after = get_unit(unit["id"])
        assert unit_after["open_action_count"] == 1, "verify+reopen must be net-zero on the open count"
        open_items, meta = validate_paginated(api.list_unit_action_items(unit["id"], MANAGER))
        open_class = [i for i in open_items
                      if i["status"] in ("OPEN", "IN_PROGRESS", "SUBMITTED_FOR_VERIFICATION", "REJECTED")]
        assert len(open_class) == unit_after["open_action_count"] == 1
        assert get_action_item(item["id"])["reopen_count"] == 1


class TestEvidence:
    def test_evidence_item_is_append_only(self, api):
        """PRD §2.5: "Evidence items are the single exception to this contract: an
        `EvidenceItem` is append-only, carries only `id` and `created_at`, has
        neither `updated_at` nor `version`, and exposes no update or delete
        operations."
        PRD §3.9: "each upload increments the item's `evidence_count` from its
        initial zero".

        Design: Corner/entities/evidence_item_is_append_only
        """
        unit, req, item = _unit_with_open_item()
        resp = api.add_evidence(item["id"],
                                create_evidence_payload(file_ref="s3://ev/e1.pdf", description="photo"),
                                make_requester_headers(req["id"]))
        evidence = validate_success(resp, 201)
        assert_evidence_item(evidence)
        assert evidence["action_item_id"] == item["id"]

        rows, meta = validate_paginated(api.list_evidence_items(item["id"], MANAGER))
        assert len(rows) == 1 and meta["total_count"] == 1
        assert get_action_item(item["id"])["evidence_count"] == 1

    def test_submit_verification_without_evidence_rejected(self, api):
        """PRD §3.9: "Submitting for verification requires `IN_PROGRESS` and at
        least one attached piece of evidence — `evidence_count` of zero draws
        `ERR_NO_EVIDENCE_ATTACHED`".

        Design: Corner/validations/submit_verification_without_evidence_rejected
        """
        unit, req, item = _unit_with_open_item()
        validate_success(api.start_action_item(item["id"], make_requester_headers(req["id"])), 200)
        resp = api.submit_verification(item["id"], make_requester_headers(req["id"]))
        validate_error(resp, ApiErrorId.ERR_NO_EVIDENCE_ATTACHED.value)
        assert get_action_item(item["id"])["status"] == "IN_PROGRESS"


class TestVerificationGuards:
    def test_verify_from_open_returns_invalid_state(self, api):
        """PRD §3.9: "Verification belongs to a `PsmManager` acting on a
        `SUBMITTED_FOR_VERIFICATION` item" — from `OPEN` the transition's
        from-state is invalid, yielding the entity's state error (PRD §2.9 step 5:
        "otherwise the entity's state error").

        Design: Corner/validations/verify_from_open_returns_invalid_state
        """
        unit, req, item = _unit_with_open_item()
        resp = api.verify_action_item(item["id"], MANAGER)
        validate_error(resp, ApiErrorId.ERR_ACTION_ITEM_INVALID_STATE.value)
        assert get_action_item(item["id"])["status"] == "OPEN"

    def test_sod_verifier_is_completer_rejected(self, api):
        """PRD §3.9: "the verifier must not be the completer
        (`ERR_SOD_VERIFIER_IS_COMPLETER`)" — a manager presenting the completer's
        X-User-ID cannot verify that completion.

        Design: Corner/validations/sod_verifier_is_completer_rejected
        """
        unit, req, item = _unit_with_open_item()
        work_item_to_submitted(item["id"], req["id"])
        resp = api.verify_action_item(item["id"], make_manager_headers(req["id"]))
        validate_error(resp, ApiErrorId.ERR_SOD_VERIFIER_IS_COMPLETER.value)
        assert get_action_item(item["id"])["status"] == "SUBMITTED_FOR_VERIFICATION"

    def test_auditor_cannot_verify_action_item(self, api):
        """PRD §2.1: "A request whose role is valid but not permitted for the
        target endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS`."
        PRD §4: POST /psm/action-items/{id}/verify is authorized for PsmManager
        only — not for the Auditor whose audit spawned the corrective item.

        Design: Corner/rbac/auditor_cannot_verify_action_item
        """
        unit = new_unit(name="U", unit_code="U1", pha_cycle_months=12)
        aud = new_personnel("Aud", "E-AUD")
        req = new_personnel("Req", "E-REQ")
        audit = new_audit(unit["id"], aud["id"])
        drive_audit_to_reported(audit, [{"title": "f", "severity": "MINOR_NC",
                                         "assignee_id": req["id"]}])
        corrective_id = list_audit_findings(audit["id"])[0]["corrective_action_id"]
        work_item_to_submitted(corrective_id, req["id"])

        resp = api.verify_action_item(corrective_id, make_auditor_headers(aud["id"]))
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)


class TestDueDatesAndOverdue:
    def test_sla_due_date_p1_uses_default_clock(self, api):
        """PRD §2.4: "At startup, before any administrative intervention, the
        logical clock reads exactly 2026-05-01T00:00:00Z, and it never falls back
        to wall-clock time."
        PRD §3.9: "Every item's `due_date` is its creation clock date plus an SLA
        of thirty days for `P1`, ninety for `P2`, or one hundred eighty for `P3` —
        except that a creation path accepting a `due_in_days` override uses that
        many days instead."

        Design: Corner/calculations/sla_due_date_p1_uses_default_clock
        """
        unit = new_unit(name="U", unit_code="U1", pha_cycle_months=12)
        req = new_personnel("Req", "E-REQ")
        p1 = new_manual_item(unit["id"], req["id"], priority="P1", title="a")
        p3_override = new_manual_item(unit["id"], req["id"], priority="P3", due_in_days=7, title="b")
        assert p1["due_date"] == "2026-05-31T00:00:00Z", (
            f"default clock + P1 30d must be 2026-05-31, got {p1['due_date']}"
        )
        assert p3_override["due_date"] == "2026-05-08T00:00:00Z", (
            f"due_in_days 7 override must beat the P3 180d SLA, got {p3_override['due_date']}"
        )

    def test_overdue_uses_strict_less_than(self, api):
        """PRD §3.9: "An item counts as overdue when its `due_date` is strictly
        before the current clock; an item due exactly today is not overdue."

        Design: Corner/calculations/overdue_uses_strict_less_than
        """
        unit, req, item = _unit_with_open_item()  # P1 at default clock → due 2026-05-31
        set_clock("2026-05-31T00:00:00Z")
        assert get_unit(unit["id"])["overdue_action_count"] == 0, (
            "due exactly today is NOT overdue"
        )
        set_clock("2026-06-01T00:00:00Z")
        unit_after = get_unit(unit["id"])
        assert unit_after["overdue_action_count"] == 1, "one day past due_date the item is overdue"
        assert unit_after["open_action_count"] == 1
