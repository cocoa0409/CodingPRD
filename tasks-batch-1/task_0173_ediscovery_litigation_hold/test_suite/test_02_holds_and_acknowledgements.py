"""Legal holds, acknowledgements, the ack->hold bubble cascade, on_time boundary,
and ack-rate computation.

Difficulty queue: transitive_cascade (acknowledge bubbles hold), boundary_precision
(on_time inclusive at deadline).
Corner queue: ack-after-deadline complement, ack_rate computed, already-acknowledged
invalid state, issue-zero-custodians, custodian system fields.
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    fixtures as fx,
)


class TestAcknowledgeBubble:
    def test_final_acknowledge_bubbles_hold_to_acknowledged(self, api):
        """PRD §3.2: "It then decrements the hold's pending_ack_count; if that count
        reaches 0, meaning every custodian has acknowledged, the hold auto-transitions
        from ISSUED to ACKNOWLEDGED."

        Design: Difficulty/transitive_cascade/acknowledge_bubbles_hold_to_acknowledged_depth2
        """
        matter = fx.create_matter(caption="Ack Co", bates_prefix="AK")
        custodian = fx.create_custodian(matter["id"], email="a@x.com")
        hold = fx.create_hold(matter["id"])
        fx.issue_hold(hold["id"])
        ack_id = fx.acknowledgement_id_for(custodian["id"])
        ack = fx.acknowledge(ack_id, custodian["id"])
        assert ack["status"] == "ACKNOWLEDGED", f"got {ack['status']}"
        refreshed_hold = get_success_data(api.get_legal_hold(hold["id"], fx.LEGALOPS))
        assert refreshed_hold["pending_ack_count"] == 0, (
            f"pending_ack_count should reach 0, got {refreshed_hold['pending_ack_count']}"
        )
        assert refreshed_hold["status"] == "ACKNOWLEDGED", (
            f"hold should auto-transition to ACKNOWLEDGED, got {refreshed_hold['status']}"
        )

    def test_partial_acknowledge_keeps_hold_issued(self, api):
        """PRD §3.2: "It then decrements the hold's pending_ack_count; if that count
        reaches 0, meaning every custodian has acknowledged, the hold auto-transitions
        from ISSUED to ACKNOWLEDGED."

        Design: Difficulty/transitive_cascade/acknowledge_bubbles_hold_to_acknowledged_depth2
        """
        matter = fx.create_matter(caption="Ack4 Co", bates_prefix="AE")
        c1 = fx.create_custodian(matter["id"], full_name="Al", email="a@x.com")
        fx.create_custodian(matter["id"], full_name="Bo", email="b@x.com")
        hold = fx.create_hold(matter["id"])
        fx.issue_hold(hold["id"])
        ack_id = fx.acknowledgement_id_for(c1["id"])
        fx.acknowledge(ack_id, c1["id"])
        refreshed_hold = get_success_data(api.get_legal_hold(hold["id"], fx.LEGALOPS))
        assert refreshed_hold["pending_ack_count"] == 1, (
            f"one ack still pending, got {refreshed_hold['pending_ack_count']}"
        )
        assert refreshed_hold["status"] == "ISSUED", (
            f"hold stays ISSUED while a custodian remains PENDING, got {refreshed_hold['status']}"
        )


class TestOnTimeBoundary:
    def test_acknowledge_at_exact_deadline_is_on_time(self, api):
        """PRD §3.2: "the server stamps acknowledged_at with the current time and
        sets on_time to true exactly when acknowledged_at is at or before the hold's
        ack_deadline — the deadline instant itself counts as on time."

        Design: Difficulty/boundary_precision_check/ack_on_time_inclusive_at_deadline
        """
        matter = fx.create_matter(caption="Bnd Co", bates_prefix="BN")
        custodian = fx.create_custodian(matter["id"], email="a@x.com")
        hold = fx.create_hold(matter["id"], ack_deadline="2026-06-10T00:00:00Z")
        fx.issue_hold(hold["id"])
        ack_id = fx.acknowledgement_id_for(custodian["id"])
        # Pin clock to exactly the deadline instant.
        fx.set_clock("2026-06-10T00:00:00Z")
        ack = fx.acknowledge(ack_id, custodian["id"])
        assert ack["on_time"] is True, (
            "acknowledgement at exactly ack_deadline must be on_time (inclusive '<=')"
        )

    def test_acknowledge_one_second_before_deadline_is_on_time(self, api):
        """PRD §3.2: "the server stamps acknowledged_at with the current time and
        sets on_time to true exactly when acknowledged_at is at or before the hold's
        ack_deadline — the deadline instant itself counts as on time."

        Design: Difficulty/boundary_precision_check/ack_on_time_inclusive_at_deadline
        """
        matter = fx.create_matter(caption="Early Co", bates_prefix="EY")
        custodian = fx.create_custodian(matter["id"], email="a@x.com")
        hold = fx.create_hold(matter["id"], ack_deadline="2026-06-10T00:00:00Z")
        fx.issue_hold(hold["id"])
        ack_id = fx.acknowledgement_id_for(custodian["id"])
        # One second before the deadline (strictly at-or-before).
        fx.set_clock("2026-06-09T23:59:59Z")
        ack = fx.acknowledge(ack_id, custodian["id"])
        assert ack["on_time"] is True, (
            "acknowledgement strictly before the deadline must be on_time"
        )

    def test_acknowledge_one_second_after_deadline_not_on_time(self, api):
        """PRD §3.2: "the server stamps acknowledged_at with the current time and
        sets on_time to true exactly when acknowledged_at is at or before the hold's
        ack_deadline — the deadline instant itself counts as on time."

        Design: Corner/calculations/ack_after_deadline_not_on_time
        """
        matter = fx.create_matter(caption="Late Co", bates_prefix="LT")
        custodian = fx.create_custodian(matter["id"], email="a@x.com")
        hold = fx.create_hold(matter["id"], ack_deadline="2026-06-10T00:00:00Z")
        fx.issue_hold(hold["id"])
        ack_id = fx.acknowledgement_id_for(custodian["id"])
        fx.set_clock("2026-06-10T00:00:01Z")
        ack = fx.acknowledge(ack_id, custodian["id"])
        assert ack["on_time"] is False, (
            "acknowledgement one second after the deadline must not be on_time"
        )


class TestAckRate:
    def test_ack_rate_half_after_one_of_two_acknowledges(self, api):
        """PRD §3.2: "The matter's ack_rate is the acknowledged_count divided by the
        custodian_count, rounded half-up to two decimal places; when the matter has
        no custodians it is 0.00 rather than an undefined division."

        Design: Corner/entities/matter_ack_rate_computed_after_partial_acknowledge
        """
        matter = fx.create_matter(caption="Rate Co", bates_prefix="RT")
        c1 = fx.create_custodian(matter["id"], full_name="Al", email="a@x.com")
        fx.create_custodian(matter["id"], full_name="Bo", email="b@x.com")
        hold = fx.create_hold(matter["id"])
        fx.issue_hold(hold["id"])
        ack_id = fx.acknowledgement_id_for(c1["id"])
        fx.acknowledge(ack_id, c1["id"])
        refreshed = get_success_data(api.get_matter(matter["id"], fx.LEGALOPS))
        assert refreshed["acknowledged_count"] == 1, (
            f"got {refreshed['acknowledged_count']}"
        )
        assert refreshed["ack_rate"] == 0.5, f"1/2 -> 0.5, got {refreshed['ack_rate']}"


class TestHoldStateGuards:
    def test_issue_hold_with_zero_custodians_rejected(self, api):
        """PRD §3.2: "an attempt to issue a hold on a matter with zero custodians is
        rejected with ERR_HOLD_HAS_NO_CUSTODIANS."

        Design: Corner/state_machines/issue_hold_with_zero_custodians_rejected
        """
        matter = fx.create_matter(caption="Zero Co", bates_prefix="ZC")
        hold = fx.create_hold(matter["id"])
        resp = api.issue_legal_hold(hold["id"], fx.LEGALOPS)
        validate_error(resp, ApiErrorId.ERR_HOLD_HAS_NO_CUSTODIANS.value, 409)
        # Hold stays DRAFT.
        refreshed = get_success_data(api.get_legal_hold(hold["id"], fx.LEGALOPS))
        assert refreshed["status"] == "DRAFT", f"got {refreshed['status']}"

    def test_acknowledge_already_acknowledged_returns_invalid_state(self, api):
        """PRD §3.2: "This is permitted only while the acknowledgement is PENDING and
        its parent hold is ISSUED."

        Design: Corner/state_machines/acknowledge_already_acknowledged_returns_invalid_state
        """
        matter = fx.create_matter(caption="Re Co", bates_prefix="RA")
        custodian = fx.create_custodian(matter["id"], email="a@x.com")
        hold = fx.create_hold(matter["id"])
        fx.issue_hold(hold["id"])
        ack_id = fx.acknowledgement_id_for(custodian["id"])
        fx.acknowledge(ack_id, custodian["id"])
        # Second acknowledge on an already-ACKNOWLEDGED record.
        resp = api.acknowledge(ack_id, fx.make_custodian_headers(custodian["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


class TestCustodianCreation:
    def test_custodian_system_fields_default_on_create(self, api):
        """PRD §3.1: "Each custodian starts with an ack_state of NONE and a
        retention_released flag of false."

        Design: Corner/entities/custodian_system_fields_ignored_on_create
        """
        matter = fx.create_matter(caption="Sys Co", bates_prefix="SY")
        resp = api.create_custodian(
            {"matter_id": matter["id"], "full_name": "Al", "email": "a@x.com"},
            fx.LEGALOPS,
        )
        data = validate_success(resp, 201)
        assert data["ack_state"] == "NONE", f"got {data['ack_state']}"
        assert data["retention_released"] is False, f"got {data['retention_released']}"

    def test_custodian_wrong_matter_parent_not_found(self, api):
        """PRD §2.8: "Existence of all path and foreign-key-referenced resources
        (ERR_NOT_FOUND) is verified next, evaluated left to right so that the first
        identifier in the request that names no existing resource is the one reported."

        Design: Corner/entities/custodian_wrong_matter_parent_not_found
        """
        resp = api.create_custodian(
            {
                "matter_id": "00000000-0000-4000-8000-000000000000",
                "full_name": "Al",
                "email": "a@x.com",
            },
            fx.LEGALOPS,
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value, 404)

    def test_duplicate_custodian_email_within_matter_rejected(self, api):
        """PRD §3.1: "a second custodian on the same matter with an email that
        case-insensitively matches an existing one is rejected with
        ERR_DUPLICATE_CUSTODIAN_EMAIL."

        Design: Corner/entities/duplicate_custodian_email_within_matter_rejected
        """
        matter = fx.create_matter(caption="Dup Co", bates_prefix="DU")
        fx.create_custodian(matter["id"], full_name="Al", email="a@x.com")
        resp = api.create_custodian(
            {"matter_id": matter["id"], "full_name": "Al2", "email": "A@X.com"},
            fx.LEGALOPS,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_CUSTODIAN_EMAIL.value, 409)
