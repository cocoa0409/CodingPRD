"""Alarm ingestion, dedup, acknowledgement cascade, and archive paths
(PRD §3.3)."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    create_alarm_payload,
    api_client,
    ingest_alarm,
    register_alarm_code_map,
    setup_acknowledged_alarm,
    setup_station_with_inverters,
    TEST_USERS,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)


class TestAlarmCodeUnmapped:
    """PRD §3.3 ingestion gate."""

    def test_alarm_with_no_code_map_rejected(self, api, admin_headers):
        """PRD §3.3: "If no such mapping exists, ingestion is
        rejected with ERR_ALARM_CODE_UNMAPPED."

        Claim: ingestion before any AlarmCodeMap row exists →
        ERR_ALARM_CODE_UNMAPPED.
        """
        station, _supp, invs = setup_station_with_inverters(inverter_count=1)
        payload = create_alarm_payload(inverter_id=invs[0]["id"])
        resp = api.create_alarm(payload, admin_headers)
        validate_error(resp, ApiErrorId.ERR_ALARM_CODE_UNMAPPED.value)


class TestAlarmDedup:
    """PRD §3.3 deduplication within 5-minute window."""

    def test_dedup_within_window_merges(self, api, admin_headers):
        """PRD §3.3: "If an OPEN AlarmEvent already exists on this
        inverter_id for this canonical_code, and that event's
        last_seen_at is within the deduplication window of five
        minutes ahead or behind the incoming first_seen_at, the new
        payload is merged into the existing row rather than producing
        a new one: the existing row's occurrence_count increments by
        one, its last_seen_at is updated to the incoming first_seen_at..."

        Claim: a second ingestion within 5 minutes returns the same
        alarm with occurrence_count=2 and updated last_seen_at.
        """
        station, _supp, invs = setup_station_with_inverters(inverter_count=1)
        register_alarm_code_map(severity="MAJOR")
        first = ingest_alarm(
            invs[0]["id"], first_seen_at="2026-01-01T00:00:00.000Z",
        )
        resp = api.create_alarm(
            create_alarm_payload(
                inverter_id=invs[0]["id"],
                first_seen_at="2026-01-01T00:03:00.000Z",  # 3 min later
            ),
            admin_headers,
        )
        # The dedup path is documented as a 201/200 success with the
        # merged row. We use validate_success to be tolerant of either.
        body = resp.json()
        assert resp.status_code in (200, 201), (
            f"dedup merge must succeed, got {resp.status_code}: {body}"
        )
        merged = body["data"]
        assert merged["id"] == first["id"], (
            "PRD §3.3: 'the new payload is merged into the existing "
            "row rather than producing a new one'"
        )
        assert merged["occurrence_count"] == 2
        assert merged["last_seen_at"] == "2026-01-01T00:03:00.000Z"


class TestAlarmAcknowledgement:
    """PRD §3.3 acknowledgement cascade."""

    def test_info_alarm_cannot_be_acked(self, api, om_headers):
        """PRD §3.3: "The platform first rejects INFO-severity alarms
        with ERR_ALARM_INFO_NOT_ACKABLE — informational alarms have
        to be archived directly rather than acknowledged."

        Claim: ack on an INFO alarm → ERR_ALARM_INFO_NOT_ACKABLE.
        """
        station, _supp, invs = setup_station_with_inverters(inverter_count=1)
        register_alarm_code_map(severity="INFO")
        alarm = ingest_alarm(invs[0]["id"])
        resp = api.ack_alarm(alarm["id"], om_headers)
        validate_error(resp, ApiErrorId.ERR_ALARM_INFO_NOT_ACKABLE.value)

    def test_ack_open_alarm_moves_to_acknowledged(self, api, om_headers):
        """PRD §3.3: "On success the event moves OPEN → ACKNOWLEDGED,
        the acknowledged_by field is set to the caller's X-User-ID,
        acknowledged_at is set to the current instant..."

        Claim: a successful ack moves state OPEN→ACKNOWLEDGED and
        records acknowledged_by = caller's X-User-ID.
        """
        from test_helpers import OM_ENGINEER_ID
        station, _supp, invs = setup_station_with_inverters(inverter_count=1)
        register_alarm_code_map(severity="MAJOR")
        alarm = ingest_alarm(invs[0]["id"])
        resp = api.ack_alarm(alarm["id"], om_headers)
        data = validate_success(resp)
        assert data["state"] == "ACKNOWLEDGED"
        assert data["acknowledged_by"] == OM_ENGINEER_ID

    def test_ack_creates_defect_for_major(self, api, om_headers):
        """PRD §3.3: "A MAJOR or CRITICAL acknowledgement then mints a
        Defect automatically — the first downstream hop — whose
        source is ALARM, source_ref_id is the alarm's id, subject_type
        is INVERTER, subject_id is the alarm's inverter_id, severity
        is MAJOR if the alarm was MAJOR and CRITICAL if the alarm was
        CRITICAL, and state is OPEN."

        Claim: acking a MAJOR alarm creates a Defect with severity=MAJOR
        and links it back via the alarm's defect_id.
        """
        station, _supp, invs = setup_station_with_inverters(inverter_count=1)
        register_alarm_code_map(severity="MAJOR")
        alarm = ingest_alarm(invs[0]["id"])
        api.ack_alarm(alarm["id"], om_headers)
        # The Defect should be discoverable via /pv-ops/defects filter
        defects_resp = api.list_defects(
            om_headers, params={"station_id": station["id"]},
        )
        body = defects_resp.json()
        rows = body["data"] if isinstance(body["data"], list) else [body["data"]]
        alarm_defects = [
            d for d in rows
            if d.get("source") == "ALARM" and d.get("source_ref_id") == alarm["id"]
        ]
        assert len(alarm_defects) == 1
        d = alarm_defects[0]
        assert d["subject_type"] == "INVERTER"
        assert d["subject_id"] == invs[0]["id"]
        assert d["severity"] == "MAJOR"
        assert d["state"] == "OPEN"

    def test_ack_major_does_not_lock_inverter(self, api, om_headers):
        """PRD §3.3: "a CRITICAL defect on an inverter forces that
        inverter's lifecycle_state from OPERATING to UNDER_REPAIR;
        MAJOR defects and defects on non-inverter subjects do not
        touch the inverter."

        Claim: a MAJOR-acked alarm leaves the inverter in OPERATING.
        """
        station, _supp, invs = setup_station_with_inverters(inverter_count=1)
        register_alarm_code_map(severity="MAJOR")
        alarm = ingest_alarm(invs[0]["id"])
        api.ack_alarm(alarm["id"], om_headers)
        inv_resp = api.get_inverter(invs[0]["id"], om_headers)
        inv = validate_success(inv_resp)
        assert inv["lifecycle_state"] == "OPERATING"

    def test_warn_ack_does_not_create_defect(self, api, om_headers):
        """PRD §3.3: "A WARN acknowledgement, by contrast, only writes
        the audit row and bumps the alarm's own metadata — it does
        not create a defect and does not move any inverter or
        station."

        Claim: acking a WARN alarm leaves the defect list empty for
        the affected inverter.
        """
        station, _supp, invs = setup_station_with_inverters(inverter_count=1)
        register_alarm_code_map(severity="WARN")
        alarm = ingest_alarm(invs[0]["id"])
        api.ack_alarm(alarm["id"], om_headers)
        defects_resp = api.list_defects(
            om_headers, params={"station_id": station["id"]},
        )
        body = defects_resp.json()
        rows = body["data"] if isinstance(body["data"], list) else []
        alarm_defects = [
            d for d in rows
            if d.get("source") == "ALARM" and d.get("source_ref_id") == alarm["id"]
        ]
        assert len(alarm_defects) == 0


class TestAlarmArchive:
    """PRD §3.3 archive paths."""

    def test_info_alarm_archive_from_open(self, api, om_headers):
        """PRD §3.3: "An OPEN INFO-severity event can be archived
        directly with the archival action, moving the event to
        ARCHIVED (this is, in fact, the only way an INFO alarm leaves
        the open state)."

        Claim: archive on an OPEN INFO alarm moves it to ARCHIVED.
        """
        station, _supp, invs = setup_station_with_inverters(inverter_count=1)
        register_alarm_code_map(severity="INFO")
        alarm = ingest_alarm(invs[0]["id"])
        resp = api.archive_alarm(alarm["id"], om_headers)
        data = validate_success(resp)
        assert data["state"] == "ARCHIVED"

    def test_cleared_alarm_can_be_archived(self, api, om_headers):
        """PRD §3.3: "A CLEARED event of any severity can also be
        archived, transitioning CLEARED to ARCHIVED; no further
        precondition applies in that path."

        Claim: archive on a CLEARED MAJOR alarm moves it to ARCHIVED.
        Walk: MAJOR alarm → ack (creates defect) → close defect →
        clear alarm → archive.
        """
        station, _supp, invs = setup_station_with_inverters(inverter_count=1)
        register_alarm_code_map(severity="MAJOR")
        alarm = ingest_alarm(invs[0]["id"])
        acked = validate_success(api.ack_alarm(alarm["id"], om_headers))
        # The linked defect must be RESOLVED or CLOSED before clear.
        defects = api.list_defects(om_headers, params={
            "station_id": station["id"],
        }).json()["data"]
        defect = next(
            d for d in defects
            if d.get("source") == "ALARM"
            and d.get("source_ref_id") == alarm["id"]
        )
        # Walk defect OPEN → DISPATCHED → IN_PROGRESS → RESOLVED →
        # CLOSED via work-order. We need a supplier.
        from test_helpers import (
            create_supplier, dispatch_work_order, start_work_order,
            complete_work_order,
        )
        supplier = create_supplier()
        wo = dispatch_work_order(defect["id"], supplier["id"])
        start_work_order(wo["id"])
        complete_work_order(wo["id"])
        api.close_defect(defect["id"], om_headers)
        cleared = validate_success(api.clear_alarm(acked["id"], om_headers))
        assert cleared["state"] == "CLEARED"
        archived = validate_success(
            api.archive_alarm(acked["id"], om_headers),
        )
        assert archived["state"] == "ARCHIVED"


class TestAlarmAlreadyAcked:
    """PRD §3.3 + concurrency narrative on ack state-from check."""

    def test_double_ack_yields_already_acked(self, api, om_headers):
        """PRD §3.3: "If the event is already past OPEN (because
        another operator beat this caller), the loser receives
        ERR_ALARM_ALREADY_ACKED."

        Claim: a second ack on an already-ACKNOWLEDGED alarm yields
        ERR_ALARM_ALREADY_ACKED.
        """
        station, invs, acked = setup_acknowledged_alarm(severity="MAJOR")
        # Second ack — the alarm is no longer in OPEN.
        resp = api.ack_alarm(acked["id"], om_headers)
        # PRD pins ERR_ALARM_ALREADY_ACKED on this exact path.
        validate_error(resp, ApiErrorId.ERR_ALARM_ALREADY_ACKED.value)
