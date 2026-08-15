"""Triage routing, response-deadline variants, and optimistic concurrency."""
from test_helpers import (
    ApiErrorId,
    Scenario,
    assert_same_instant,
    determine_billing_payload,
    make_triage_nurse_headers,
    message_in_review_with_minutes,
    provider_pool_practice,
    staff_headers,
    triage_payload,
    validate_error,
    validate_success,
)


class TestResponseDeadlineVariants:
    def _setup_two_pools_two_messages(self):
        """One FROM_RECEIPT pool and one FROM_TRIAGE pool with identical
        targets; two messages received at 10:00 and triaged URGENT at 10:45."""
        scn = Scenario()
        nurse = scn.add_staff("NURSE", "Nurse Nora")
        pool_r = scn.add_pool("PROVIDER_INBOX", "FROM_RECEIPT", name="ProvR")
        pool_t = scn.add_pool("PROVIDER_INBOX", "FROM_TRIAGE", name="ProvT")
        patient = scn.add_patient(full_name="Pat A")
        scn.set_clock("2026-08-03T10:00:00Z")
        m1 = scn.send_message(patient, subject="Rash",
                              body="Itchy rash spreading")
        m2 = scn.send_message(patient, subject="Fever", body="Fever 38.9")
        scn.set_clock("2026-08-03T10:45:00Z")
        return scn, nurse, pool_r, pool_t, m1, m2

    def test_deadline_from_receipt_policy_uses_received_at(self, api):
        """PRD §3.3: "The message's `response_due_at` is computed as a base
        instant plus the target for the newly assigned urgency: the pool's
        `target_minutes_emergent` for an `EMERGENT` message,
        `target_minutes_urgent` for `URGENT`, and `target_minutes_routine` for
        `ROUTINE`."
        PRD §3.3: "Under `FROM_RECEIPT` the base is the message's original
        `received_at`, and it never moves — re-triage does not shift it, and a
        reopened message re-triaged later may legitimately come out already past
        due."

        Received 10:00 + 120 minutes (URGENT target) => due 12:00, even though
        triage happened at 10:45.

        Design: Difficulty/dual_variant_calc/deadline_from_receipt_vs_from_triage_policy
        """
        scn, nurse, pool_r, _pool_t, m1, _m2 = \
            self._setup_two_pools_two_messages()
        resp = api.triage_message(
            m1["id"], triage_payload("URGENT", "CLINICAL", pool_r["id"],
                                     m1["version"]),
            staff_headers(nurse))
        data = validate_success(resp, 200)
        assert data["status"] == "TRIAGED"
        assert_same_instant(data["response_due_at"], "2026-08-03T12:00:00Z",
                            label="FROM_RECEIPT response_due_at")
        assert_same_instant(data["received_at"], "2026-08-03T10:00:00Z",
                            label="received_at")

    def test_deadline_from_triage_policy_uses_triaged_at(self, api):
        """PRD §3.3: "Under `FROM_TRIAGE` the base is the latest `triaged_at`,
        so each re-triage slides the deadline forward."

        Identical urgency and target minutes as the FROM_RECEIPT pool, but the
        base is triaged_at (10:45), so due is 12:45 — the two variants diverge
        on identical inputs.

        Design: Difficulty/dual_variant_calc/deadline_from_receipt_vs_from_triage_policy
        """
        scn, nurse, pool_r, pool_t, m1, m2 = \
            self._setup_two_pools_two_messages()
        due_r = validate_success(api.triage_message(
            m1["id"], triage_payload("URGENT", "CLINICAL", pool_r["id"],
                                     m1["version"]),
            staff_headers(nurse)), 200)["response_due_at"]
        resp_t = api.triage_message(
            m2["id"], triage_payload("URGENT", "CLINICAL", pool_t["id"],
                                     m2["version"]),
            staff_headers(nurse))
        data_t = validate_success(resp_t, 200)
        assert_same_instant(data_t["response_due_at"], "2026-08-03T12:45:00Z",
                            label="FROM_TRIAGE response_due_at")
        assert_same_instant(data_t["triaged_at"], "2026-08-03T10:45:00Z",
                            label="triaged_at")
        assert data_t["response_due_at"] != due_r, (
            "identical urgency and target minutes must still yield different "
            "deadlines across the two deadline policies"
        )

    def test_from_receipt_retriage_keeps_original_base(self, api):
        """PRD §3.3: "Under `FROM_RECEIPT` the base is the message's original
        `received_at`, and it never moves — re-triage does not shift it, and a
        reopened message re-triaged later may legitimately come out already past
        due."

        Received 09:30 with a 120-minute URGENT target: due is 11:30 after the
        first triage at 10:00 and is unchanged by a re-triage at 11:00.

        Design: Corner/calculations/from_receipt_retriage_keeps_original_base
        """
        scn = Scenario()
        nurse = scn.add_staff("NURSE", "Nurse N")
        pool = scn.add_pool("PROVIDER_INBOX", "FROM_RECEIPT", name="ProvInbox")
        patient = scn.add_patient(full_name="Pat")
        scn.set_clock("2026-08-03T09:30:00Z")
        msg = scn.send_message(patient, subject="S", body="B")
        scn.set_clock("2026-08-03T10:00:00Z")
        first = scn.triage(msg["id"], nurse, "URGENT", "CLINICAL", pool["id"])
        assert_same_instant(first["response_due_at"], "2026-08-03T11:30:00Z",
                            label="first triage response_due_at")
        scn.set_clock("2026-08-03T11:00:00Z")
        second = scn.triage(msg["id"], nurse, "URGENT", "CLINICAL", pool["id"])
        assert_same_instant(second["response_due_at"], "2026-08-03T11:30:00Z",
                            label="re-triage response_due_at")
        assert second["response_due_at"] == first["response_due_at"], (
            "FROM_RECEIPT re-triage must keep the original received_at base"
        )


class TestOptimisticConcurrency:
    def test_occ_stale_triage_rejected(self, api):
        """PRD §2.7: "Each request must carry `expected_message_version`, a
        non-optional field holding the caller's last observed `version` of the
        target `PortalMessage`. If the presented value does not equal the
        message's current `version` — because another writer has advanced the
        message since the caller last read it — the request is rejected with
        `ERR_STALE_VERSION` (HTTP 412), so a client cannot reclassify or
        re-determine a message whose classification or disposition it has not
        observed."

        Design: Corner/cross_cutting_layers/occ_stale_triage_rejected_412
        """
        scn = Scenario()
        nurse = scn.add_staff("NURSE", "Nurse N")
        pool = scn.add_pool("PROVIDER_INBOX", "FROM_TRIAGE", name="ProvInbox")
        patient = scn.add_patient(full_name="Pat")
        msg = scn.send_message(patient, subject="S", body="B")
        stale_version = msg["version"]
        first = scn.triage(msg["id"], nurse, "ROUTINE", "ADMINISTRATIVE",
                           pool["id"], expected_version=stale_version)
        assert first["version"] == stale_version + 1

        resp = api.triage_message(
            msg["id"], triage_payload("URGENT", "CLINICAL", pool["id"],
                                      stale_version),
            staff_headers(nurse))
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        after = scn.get_message(msg["id"])
        assert after["urgency"] == "ROUTINE", (
            "a stale triage must not overwrite the classification"
        )
        assert after["category"] == "ADMINISTRATIVE"

    def test_occ_retriage_with_fresh_version_succeeds(self, api):
        """PRD §2.7: "Re-triage and re-determination are both legitimate
        sequential operations (§3.3, §3.6), which is precisely why the
        stale-version guard, rather than a state check, is the serialization
        point between writers."
        PRD §3.3: "Either way `triaged_at` is set to the logical now and the
        message's `version` increments by one."

        Design: Corner/cross_cutting_layers/occ_stale_triage_rejected_412
        """
        scn = Scenario()
        nurse = scn.add_staff("NURSE", "Nurse N")
        pool = scn.add_pool("PROVIDER_INBOX", "FROM_TRIAGE", name="ProvInbox")
        patient = scn.add_patient(full_name="Pat")
        msg = scn.send_message(patient, subject="S", body="B")
        v1 = msg["version"]
        first = scn.triage(msg["id"], nurse, "ROUTINE", "ADMINISTRATIVE",
                           pool["id"], expected_version=v1)
        v2 = first["version"]
        assert v2 == v1 + 1, "triage must increment the version by one"

        resp = api.triage_message(
            msg["id"], triage_payload("URGENT", "CLINICAL", pool["id"], v2),
            staff_headers(nurse))
        data = validate_success(resp, 200)
        assert data["version"] == v2 + 1, (
            f"re-triage must increment the version by one: {v2} -> "
            f"{data['version']}"
        )
        assert data["urgency"] == "URGENT"
        assert data["category"] == "CLINICAL"

    def test_occ_stale_determine_billing_rejected(self, api):
        """PRD §2.7: "Two write operations are guarded by optimistic concurrency
        control: `POST /inbox/portal-messages/{id}/triage` and
        `POST /inbox/portal-messages/{id}/determine-billing`."
        PRD §2.7: "If the presented value does not equal the message's current
        `version` — because another writer has advanced the message since the
        caller last read it — the request is rejected with `ERR_STALE_VERSION`
        (HTTP 412)".

        Design: Corner/cross_cutting_layers/occ_stale_determine_billing_rejected_412
        """
        ctx = provider_pool_practice()
        scn = ctx["scn"]
        msg = message_in_review_with_minutes(ctx, minutes=3, urgency="ROUTINE",
                                             category="CLINICAL")
        stale_version = msg["version"]
        first = scn.determine_billing(msg["id"], ctx["provider"], "NOT_BILLABLE",
                                      expected_version=stale_version)
        assert first["version"] == stale_version + 1
        assert first["billing_disposition"] == "NOT_BILLABLE"

        resp = api.determine_billing(
            msg["id"],
            determine_billing_payload("NOT_BILLABLE", stale_version),
            staff_headers(ctx["provider"]))
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        after = scn.get_message(msg["id"])
        assert after["billing_disposition"] == "NOT_BILLABLE"
        assert after["version"] == stale_version + 1, (
            "the rejected replay must not bump the version again"
        )


class TestTriageInputAndState:
    def test_invalid_urgency_enum_rejected(self, api):
        """PRD §2.6: "9. **Input shape** — malformed bodies (missing required
        fields, invalid enum members, out-of-range integers, unmet conditional
        fields) are reported as `ERR_INVALID_REQUEST`."

        Design: Corner/validations/invalid_enum_value_rejected
        """
        scn = Scenario()
        nurse = scn.add_staff("NURSE", "Nurse N")
        pool = scn.add_pool("PROVIDER_INBOX", "FROM_TRIAGE", name="ProvInbox")
        patient = scn.add_patient(full_name="Pat")
        msg = scn.send_message(patient, subject="S", body="B")
        resp = api.triage_message(
            msg["id"],
            triage_payload("WHENEVER", "CLINICAL", pool["id"], msg["version"]),
            staff_headers(nurse))
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        after = scn.get_message(msg["id"])
        assert after["status"] == "RECEIVED"
        assert after.get("urgency") is None

    def test_assign_before_triage_rejected(self, api):
        """PRD §3.3: "From `TRIAGED`, the nurse routes work by assigning."
        PRD §2.6: "7. **From-state validity** — the target resource must be in a
        state that permits the action: message-state failures surface
        `ERR_MESSAGE_INVALID_STATE`".

        A message still in RECEIVED cannot be assigned.

        Design: Corner/state_machines/assign_before_triage_rejected
        """
        scn = Scenario()
        nurse = scn.add_staff("NURSE", "Nurse N")
        patient = scn.add_patient(full_name="Pat")
        msg = scn.send_message(patient, subject="S", body="B")
        resp = api.assign_message(msg["id"], {"staff_id": nurse["id"]},
                                  make_triage_nurse_headers(nurse["id"]))
        validate_error(resp, ApiErrorId.ERR_MESSAGE_INVALID_STATE)
        after = scn.get_message(msg["id"])
        assert after["status"] == "RECEIVED"
        assert after.get("assignee_id") is None
