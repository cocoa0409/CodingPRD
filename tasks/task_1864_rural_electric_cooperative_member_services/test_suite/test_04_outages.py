"""Outage reporting, duplicate folding, restoration cascades (PRD §3.6)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_outage_report_payload,
    get_success_data,
    make_member_headers,
    setup_cooperative,
    setup_member,
    validate_error,
    validate_success,
)

REP = TEST_USERS["rep"]
FIELD = TEST_USERS["field_ops"]
DISPATCHER = TEST_USERS["dispatcher"]


def _outage_setup():
    setup_cooperative()
    member, location = setup_member(status="ACTIVE")
    return member, location


def _report_outage(api, location_id, member_id, cause="WEATHER"):
    return validate_success(api.create_outage_report(
        create_outage_report_payload(service_location_id=location_id, cause=cause),
        make_member_headers(member_id)), expected_status=201)


class TestOutageCascade:
    def test_restore_cascades_to_duplicates(self, api):
        """PRD §3.6: "Restoration is a field-operations act (`CREW_DISPATCHED →
        RESTORED`) that stamps `restored_at`, cascades every `DUPLICATE` report
        whose `parent_outage_id` points at this one into `RESTORED` as well".

        Design: Difficulty/transitive_cascade/outage_restore_duplicate_cascade
        """
        member, location = _outage_setup()
        parent = _report_outage(api, location["id"], member["id"])
        parent = get_success_data(api.acknowledge_outage(parent["id"], DISPATCHER), 200)
        parent = get_success_data(api.dispatch_outage(parent["id"], DISPATCHER), 200)
        dup = _report_outage(api, location["id"], member["id"])
        dup = get_success_data(api.mark_outage_duplicate(
            dup["id"], {"parent_outage_id": parent["id"]}, DISPATCHER), 200)
        assert dup["status"] == "DUPLICATE"

        restored = validate_success(api.restore_outage(parent["id"], FIELD), 200)
        assert restored["status"] == "RESTORED"
        dup_after = get_success_data(api.get_outage_report(dup["id"], DISPATCHER), 200)
        assert dup_after["status"] == "RESTORED"

    def test_duplicate_fold_increments_parent_notification(self, api):
        """PRD §3.6: "A successful fold moves the report to `DUPLICATE` and
        increments the parent's `notified_member_count`."

        Design: Difficulty/transitive_cascade/outage_restore_duplicate_cascade
        """
        member, location = _outage_setup()
        parent = _report_outage(api, location["id"], member["id"])
        parent = get_success_data(api.acknowledge_outage(parent["id"], DISPATCHER), 200)
        parent = get_success_data(api.dispatch_outage(parent["id"], DISPATCHER), 200)
        before = get_success_data(api.get_outage_report(parent["id"], DISPATCHER), 200)
        dup = _report_outage(api, location["id"], member["id"])
        get_success_data(api.mark_outage_duplicate(
            dup["id"], {"parent_outage_id": parent["id"]}, DISPATCHER), 200)
        after = get_success_data(api.get_outage_report(parent["id"], DISPATCHER), 200)
        assert after["notified_member_count"] == before["notified_member_count"] + 1


class TestOutageStateGuards:
    def test_acknowledge_twice_rejected(self, api):
        """PRD §2.8: "Fifth, state validity: the target resource must be in a
        legitimate from-state for the requested transition, else
        `ERR_INVALID_STATE`." Acknowledgement is defined only as
        `REPORTED → ACKNOWLEDGED` (PRD §3.6).

        Design: Corner/state_machines/outage_acknowledge_twice_idempotency_rejection
        """
        member, location = _outage_setup()
        outage = _report_outage(api, location["id"], member["id"], cause="EQUIPMENT")
        outage = get_success_data(api.acknowledge_outage(outage["id"], DISPATCHER), 200)
        assert outage["status"] == "ACKNOWLEDGED"
        resp = api.acknowledge_outage(outage["id"], DISPATCHER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_mark_duplicate_with_terminal_parent_rejected(self, api):
        """PRD §3.6: "A report in `REPORTED` may be folded into a parent by
        supplying the `parent_outage_id`, but only while the parent is itself
        still open — in `REPORTED`, `ACKNOWLEDGED`, or `CREW_DISPATCHED`;
        folding into a terminal parent is rejected with
        `ERR_PARENT_OUTAGE_TERMINAL`."

        Design: Corner/state_machines/mark_duplicate_with_terminal_parent_rejected
        """
        member, location = _outage_setup()
        parent = _report_outage(api, location["id"], member["id"])
        parent = get_success_data(api.acknowledge_outage(parent["id"], DISPATCHER), 200)
        parent = get_success_data(api.dispatch_outage(parent["id"], DISPATCHER), 200)
        parent = get_success_data(api.restore_outage(parent["id"], FIELD), 200)
        assert parent["status"] == "RESTORED"
        dup = _report_outage(api, location["id"], member["id"])
        resp = api.mark_outage_duplicate(
            dup["id"], {"parent_outage_id": parent["id"]}, DISPATCHER)
        validate_error(resp, ApiErrorId.ERR_PARENT_OUTAGE_TERMINAL)
