"""Cosign state gate, the education intake gate, and list pagination."""
from test_helpers import (
    ApiErrorId,
    Scenario,
    cosign_payload,
    create_portal_message_payload,
    message_in_review,
    nurse_pool_practice,
    patient_headers,
    provider_pool_practice,
    staff_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestCosignStateGate:
    def _setup_in_review_message(self):
        """Message IN_REVIEW assigned to provider P1 (never sent to
        PENDING_COSIGN); P2 is another provider."""
        ctx = provider_pool_practice(with_biller=False)
        scn = ctx["scn"]
        p1 = ctx["provider"]
        p2 = scn.add_staff("PROVIDER", "Dr P2")
        msg = message_in_review(ctx, urgency="URGENT", category="CLINICAL",
                                assignee_key="provider")
        return ctx, msg, p1, p2

    def test_cosign_on_in_review_rejected_not_awaiting_cosign(self, api):
        """PRD §3.4: "The cosign decision itself belongs to a `Provider` acting
        on a `PENDING_COSIGN` message — any other state is
        `ERR_NOT_AWAITING_COSIGN` — and when `pending_cosign_by_id` names a
        specific provider, only that provider may act
        (`ERR_NOT_AUTHORIZED_COSIGNER`)."
        PRD §2.6: "the server evaluates them in a fixed priority order and
        reports the first failure." — from-state validity (tier 7) precedes the
        business rules (tier 8).

        Design: Difficulty/priority_pair_validation_conflict/cosign_state_before_cosigner_identity
        """
        ctx, msg, _p1, p2 = self._setup_in_review_message()
        resp = api.cosign_message(msg["id"], cosign_payload("COSIGN"),
                                  staff_headers(p2))
        validate_error(resp, ApiErrorId.ERR_NOT_AWAITING_COSIGN)

    def test_failed_cosign_leaves_message_in_review(self, api):
        """PRD §3.4: "The cosign decision itself belongs to a `Provider` acting
        on a `PENDING_COSIGN` message — any other state is
        `ERR_NOT_AWAITING_COSIGN`".

        The rejected cosign fires no side effects: the message stays IN_REVIEW
        with its assignee and the assignee's open count unchanged.

        Design: Difficulty/priority_pair_validation_conflict/cosign_state_before_cosigner_identity
        """
        ctx, msg, p1, p2 = self._setup_in_review_message()
        resp = api.cosign_message(msg["id"], cosign_payload("COSIGN"),
                                  staff_headers(p2))
        validate_error(resp, ApiErrorId.ERR_NOT_AWAITING_COSIGN)
        after = ctx["scn"].get_message(msg["id"])
        assert after["status"] == "IN_REVIEW"
        assert after["assignee_id"] == p1["id"]
        assert ctx["scn"].get_staff(p1["id"])["open_inbox_count"] == 1


class TestEducationGate:
    def _setup_gate_open(self):
        """Patient with one delivered message and a blocking EMERGENT_MISUSE
        notice issued on it."""
        scn = Scenario()
        nurse = scn.add_staff("NURSE", "Nurse N")
        patient = scn.add_patient(full_name="Pat O")
        scn.set_clock("2026-08-03T10:00:00Z")
        m1 = scn.send_message(patient, subject="Chest pain",
                              body="crushing chest pain now")
        notice = scn.issue_notice(
            m1["id"], nurse, notice_kind="EMERGENT_MISUSE",
            body="Portal is not for emergencies; call 911.")
        return scn, nurse, patient, notice

    def test_message_create_blocked_while_gate_open(self, api):
        """PRD §3.7: "a patient's `education_gate_open` is true exactly when at
        least one of their notices has `blocking` true and `status` `ISSUED`,
        and it is recomputed whenever a notice is created or acknowledged."
        PRD §3.3: "Intake is gated by the education protocol of §3.7: while the
        patient's education gate is open, message creation is rejected with
        `ERR_EDUCATION_ACK_REQUIRED`."
        PRD §3.7: "optionally setting `blocking` — which defaults to true when
        omitted."

        Design: Difficulty/cross_entity_state_dependency/message_create_blocked_by_education_gate
        """
        scn, _nurse, patient, notice = self._setup_gate_open()
        assert notice["status"] == "ISSUED"
        assert notice["blocking"] is True, "blocking defaults to true"
        gate = scn.get_patient(patient["id"])["education_gate_open"]
        assert gate is True

        resp = api.create_portal_message(
            create_portal_message_payload(subject="Second",
                                          body="another message"),
            patient_headers(patient))
        validate_error(resp, ApiErrorId.ERR_EDUCATION_ACK_REQUIRED)

    def test_message_create_succeeds_after_notice_acknowledged(self, api):
        """PRD §3.7: "Acknowledgement is the patient's act, on their own notice
        (`ERR_PATIENT_OWNERSHIP_MISMATCH`), and only from `ISSUED`
        (`ERR_NOTICE_ALREADY_ACKNOWLEDGED`). It moves the notice to
        `ACKNOWLEDGED`, stamps `acknowledged_at`, and recomputes the gate, which
        closes as soon as no blocking `ISSUED` notices remain."

        Design: Difficulty/cross_entity_state_dependency/message_create_blocked_by_education_gate
        """
        scn, _nurse, patient, notice = self._setup_gate_open()
        acked = scn.acknowledge_notice(notice["id"], patient)
        assert acked["status"] == "ACKNOWLEDGED"
        gate = scn.get_patient(patient["id"])["education_gate_open"]
        assert gate is False, "the gate closes once no blocking ISSUED notice remains"

        resp = api.create_portal_message(
            create_portal_message_payload(subject="Second",
                                          body="another message"),
            patient_headers(patient))
        data = validate_success(resp, 201)
        assert data["status"] == "RECEIVED"


class TestTimeEntryRange:
    def test_time_entry_minutes_range_enforced(self, api):
        """PRD §3.4: "a whole-number `minutes` value of at least 1 and at most
        480 (violations are `ERR_INVALID_REQUEST`)".

        Zero and 481 minutes are rejected; one minute is accepted.

        Design: Corner/validations/time_entry_minutes_range_enforced
        """
        ctx = nurse_pool_practice()
        msg = message_in_review(ctx, urgency="ROUTINE",
                                category="ADMINISTRATIVE",
                                assignee_key="nurse")

        resp_zero = api.create_time_entry(
            {"message_id": msg["id"], "entry_kind": "ADMINISTRATIVE",
             "minutes": 0},
            staff_headers(ctx["nurse"]))
        validate_error(resp_zero, ApiErrorId.ERR_INVALID_REQUEST)

        resp_over = api.create_time_entry(
            {"message_id": msg["id"], "entry_kind": "ADMINISTRATIVE",
             "minutes": 481},
            staff_headers(ctx["nurse"]))
        validate_error(resp_over, ApiErrorId.ERR_INVALID_REQUEST)

        resp_ok = api.create_time_entry(
            {"message_id": msg["id"], "entry_kind": "ADMINISTRATIVE",
             "minutes": 1},
            staff_headers(ctx["nurse"]))
        entry = validate_success(resp_ok, 201)
        assert entry["minutes"] == 1
        assert entry["staff_id"] == ctx["nurse"]["id"]


class TestListPagination:
    def test_list_pagination_defaults_and_filter(self, api):
        """PRD §2.3: "`limit` sets the maximum number of items returned; it
        defaults to 10, with a minimum of 1 and a maximum of 100. `offset` sets
        the number of items skipped and defaults to 0."
        PRD §2.3: "List responses carry the fields `limit`, `offset`,
        `total_count`, and `has_more` in the `meta` object of the envelope."
        PRD §3.3: "The message list endpoint supports filtering by `patient_id`,
        `assigned_pool_id`, `assignee_id`, `pending_cosign_by_id`,
        `resolved_by_id`, and `status`".

        Twelve RECEIVED messages: the default page returns 10 of 12 with
        has_more true; limit=5&offset=10 returns the final 2 with has_more
        false; a status filter that matches nothing reports total_count 0.

        Design: Corner/endpoints/list_pagination_defaults_and_filter
        """
        scn = Scenario()
        nurse = scn.add_staff("NURSE", "Nurse N")
        patient = scn.add_patient(full_name="Pat")
        for i in range(1, 13):
            scn.send_message(patient, subject=f"M{i:02d}", body="b")

        nurse_h = staff_headers(nurse)

        data, meta = validate_paginated(api.list_portal_messages(nurse_h))
        assert len(data) == 10, f"default page size is 10, got {len(data)}"
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert meta["total_count"] == 12
        assert meta["has_more"] is True

        data2, meta2 = validate_paginated(
            api.list_portal_messages(nurse_h, params={"limit": 5,
                                                      "offset": 10}))
        assert len(data2) == 2, (
            f"offset 10 of 12 leaves 2 items, got {len(data2)}"
        )
        assert meta2["total_count"] == 12
        assert meta2["has_more"] is False

        _data3, meta3 = validate_paginated(
            api.list_portal_messages(nurse_h, params={"status": "TRIAGED"}))
        assert meta3["total_count"] == 0, "all twelve messages are RECEIVED"

        _data4, meta4 = validate_paginated(
            api.list_portal_messages(nurse_h,
                                     params={"patient_id": patient["id"]}))
        assert meta4["total_count"] == 12
