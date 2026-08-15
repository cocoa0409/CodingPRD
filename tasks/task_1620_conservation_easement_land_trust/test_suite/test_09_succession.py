"""Landowner succession: notice window, acknowledgement, OCC-guarded record,
expiry sweep, and the single-active-landowner invariant (PRD §3.7, §2.8)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    create_recorded_easement,
    create_submitted_amendment,
    create_succession_notice,
    easement_version,
    get_easement,
    make_landowner_headers,
    record_succession_notice_payload,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


def _active_landowners(api, easement_id, headers):
    resp = api.list_landowners(headers)
    landowners, _meta = validate_paginated(resp)
    return [
        lo for lo in landowners
        if lo.get("easement_id") == easement_id and lo.get("status") == "ACTIVE"
    ]


class TestNoticeWindow:
    def test_succession_notice_minimum_30_day_window(self, api):
        """PRD §3.7: "`transfer_on` must fall at least thirty days after the
        clock date — a shorter runway is rejected with
        `ERR_NOTICE_WINDOW_VIOLATION` (422), while exactly thirty days out is
        acceptable."

        Design: Corner/validations/succession_notice_minimum_30_day_window
        """
        ctx = create_recorded_easement(name="E-NW", parcel_acreage=100,
                                       matrix={"AGRICULTURE": "PERMITTED",
                                               "SUBDIVISION": "PROHIBITED"})
        landowner_headers = make_landowner_headers(ctx["landowner"]["id"])

        # Default clock is 2026-08-01: 2026-08-30 is 29 days out.
        resp = api.create_succession_notice(
            {
                "easement_id": ctx["easement"]["id"],
                "successor_owner_name": "B",
                "successor_contact_email": "b@x.com",
                "transfer_on": "2026-08-30",
            },
            landowner_headers,
        )
        validate_error(resp, ApiErrorId.ERR_NOTICE_WINDOW_VIOLATION)

        # 2026-08-31 is exactly 30 days out: acceptable.
        notice = validate_success(
            api.create_succession_notice(
                {
                    "easement_id": ctx["easement"]["id"],
                    "successor_owner_name": "B",
                    "successor_contact_email": "b@x.com",
                    "transfer_on": "2026-08-31",
                },
                landowner_headers,
            ),
            201,
        )
        assert notice["status"] == "NOTICE_GIVEN"


class TestSuccessionIdentity:
    def test_succession_by_non_current_landowner_rejected(self, api):
        """PRD §3.7: "The easement must be `RECORDED`, the caller's `X-User-ID`
        must equal the easement's `current_landowner_id` (else
        `ERR_NOT_CURRENT_LANDOWNER`)"
        PRD §2.11: "Separately, landowner-actor operations require the caller to
        be the easement's current landowner — `X-User-ID` must equal the
        easement's `current_landowner_id` — enforced on use-authorization
        requests, succession notices, and the start of cure, with violations
        reported as `ERR_NOT_CURRENT_LANDOWNER` (403)."

        Design: Corner/errors/succession_by_non_current_landowner_rejected
        """
        ctx = create_recorded_easement(name="E-NC", parcel_acreage=100,
                                       matrix={"AGRICULTURE": "PERMITTED",
                                               "SUBDIVISION": "PROHIBITED"})
        resp = api.create_succession_notice(
            {
                "easement_id": ctx["easement"]["id"],
                "successor_owner_name": "B",
                "successor_contact_email": "b@x.com",
                "transfer_on": "2026-09-15",
            },
            make_landowner_headers(NON_EXISTENT_UUID),
        )
        validate_error(resp, ApiErrorId.ERR_NOT_CURRENT_LANDOWNER)


class TestSuccessionOcc:
    def test_occ_stale_easement_version_on_succession_record(self, api,
                                                             trust_admin_headers):
        """PRD §2.8: "Recording an acknowledged succession notice requires
        `expected_easement_version` equal to the easement's current `version`. A
        previously recorded succession legitimately transfers ownership again —
        a second notice can remain `ACKNOWLEDGED` and would otherwise record
        cleanly — so the only sound basis for rejection is a stale easement
        version, reported as `ERR_STALE_EASEMENT_VERSION` (HTTP 412)."

        Design: Corner/validations/occ_stale_easement_version_on_succession_record
        """
        ctx = create_recorded_easement(name="E-OC3", parcel_acreage=100,
                                       matrix={"AGRICULTURE": "PERMITTED",
                                               "SUBDIVISION": "PROHIBITED"})
        easement_id = ctx["easement"]["id"]
        version_at_record = ctx["version"]
        notice = create_succession_notice(
            easement_id, ctx["landowner"]["id"], transfer_on="2026-09-15"
        )
        validate_success(
            api.acknowledge_succession_notice(notice["id"], trust_admin_headers), 200
        )

        # An amendment create advances the easement version behind the caller.
        create_submitted_amendment(
            easement_id, version_at_record,
            requested_changes=[{"use_type": "SUBDIVISION",
                                "new_level": "DISCRETIONARY"}],
            affected_acreage=10,
        )

        resp = api.record_succession_notice(
            notice["id"], record_succession_notice_payload(version_at_record),
            trust_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_EASEMENT_VERSION)
        after = validate_success(
            api.get_succession_notice(notice["id"], trust_admin_headers), 200
        )
        assert after["status"] == "ACKNOWLEDGED", "the rejected record leaves the notice recordable"


class TestSuccessionExpiry:
    def test_succession_acknowledge_after_clock_expiry_rejected(self, api,
                                                                trust_admin_headers):
        """PRD §3.7: "Creation stamps `notice_given_on` with the clock date, sets
        `ack_deadline_on` to forty-five days after the notice date, and creates
        the successor landowner row in `PENDING_SUCCESSION`"
        PRD §3.7: "When the clock sweep finds a notice still `NOTICE_GIVEN` with
        the clock date later than `ack_deadline_on`, the notice moves to
        `EXPIRED`, and its successor row is stranded in `PENDING_SUCCESSION`,
        never activating."
        PRD §3.7: "acknowledging from any other state — including after the
        clock sweep has expired the notice — is rejected with
        `ERR_INVALID_NOTICE_STATE`."

        Design: Corner/state_machines/succession_acknowledge_after_clock_expiry_rejected
        """
        ctx = create_recorded_easement(name="E-SX", parcel_acreage=100,
                                       matrix={"AGRICULTURE": "PERMITTED",
                                               "SUBDIVISION": "PROHIBITED"})
        notice = create_succession_notice(
            ctx["easement"]["id"], ctx["landowner"]["id"], transfer_on="2026-10-01"
        )
        assert notice["notice_given_on"] == "2026-08-01"
        assert notice["ack_deadline_on"] == "2026-09-15", "notice date + 45 days"

        set_clock("2026-09-16T00:00:00Z")
        expired = validate_success(
            api.get_succession_notice(notice["id"], trust_admin_headers), 200
        )
        assert expired["status"] == "EXPIRED"

        resp = api.acknowledge_succession_notice(notice["id"], trust_admin_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_NOTICE_STATE)


class TestSingleActiveLandownerInvariant:
    def test_succession_record_flips_single_active_landowner(self, api,
                                                             trust_admin_headers):
        """PRD §3.7: "Recording stamps the notice's `recorded_on` with the clock
        date, activates the successor from `PENDING_SUCCESSION` to `ACTIVE` with
        `acquired_on` set, retires the predecessor from `ACTIVE` to
        `SUPERSEDED`, flips the easement's `current_landowner_id` to the
        successor, and advances the easement's `version` by one — all as one
        mutation."

        Design: Difficulty/compensating_invariant/single_active_landowner_conserved_across_succession
        """
        ctx = create_recorded_easement(name="E-CI2", parcel_acreage=500,
                                       matrix={"AGRICULTURE": "PERMITTED",
                                               "SUBDIVISION": "PROHIBITED"})
        easement_id = ctx["easement"]["id"]
        predecessor = ctx["landowner"]
        notice = create_succession_notice(
            easement_id, predecessor["id"],
            successor_owner_name="Owner B",
            successor_contact_email="b@x.com",
            transfer_on="2026-09-15",
        )
        successor_id = notice["successor_landowner_id"]
        validate_success(
            api.acknowledge_succession_notice(notice["id"], trust_admin_headers), 200
        )

        recorded = validate_success(
            api.record_succession_notice(
                notice["id"],
                record_succession_notice_payload(easement_version(easement_id)),
                trust_admin_headers,
            ),
            200,
        )
        assert recorded["status"] == "RECORDED"

        active = _active_landowners(api, easement_id, trust_admin_headers)
        assert len(active) == 1, "exactly one ACTIVE landowner survives the mutation"
        assert active[0]["id"] == successor_id

        predecessor_after = validate_success(
            api.get_landowner(predecessor["id"], trust_admin_headers), 200
        )
        assert predecessor_after["status"] == "SUPERSEDED"

        easement = get_easement(easement_id)
        assert easement["current_landowner_id"] == successor_id

    def test_succession_notice_keeps_single_active_landowner_midflight(self, api,
                                                                       trust_admin_headers):
        """PRD §3.7: "Creation stamps `notice_given_on` with the clock date, sets
        `ack_deadline_on` to forty-five days after the notice date, and creates
        the successor landowner row in `PENDING_SUCCESSION` — its `owner_name`
        and `contact_email` taken from the successor fields, its
        `predecessor_landowner_id` set to the current landowner."
        PRD §3.7: "Recording stamps the notice's `recorded_on` with the clock
        date, activates the successor from `PENDING_SUCCESSION` to `ACTIVE` with
        `acquired_on` set, retires the predecessor from `ACTIVE` to
        `SUPERSEDED`, flips the easement's `current_landowner_id` to the
        successor, and advances the easement's `version` by one — all as one
        mutation."

        Design: Difficulty/compensating_invariant/single_active_landowner_conserved_across_succession
        """
        ctx = create_recorded_easement(name="E-CI2B", parcel_acreage=500,
                                       matrix={"AGRICULTURE": "PERMITTED",
                                               "SUBDIVISION": "PROHIBITED"})
        easement_id = ctx["easement"]["id"]
        predecessor = ctx["landowner"]

        notice = create_succession_notice(
            easement_id, predecessor["id"], transfer_on="2026-09-15"
        )
        successor_id = notice["successor_landowner_id"]

        # Mid-flight: the successor is pending and the predecessor is still the
        # single ACTIVE landowner — the invariant never dips to zero or doubles.
        successor_mid = validate_success(
            api.get_landowner(successor_id, trust_admin_headers), 200
        )
        assert successor_mid["status"] == "PENDING_SUCCESSION"
        assert successor_mid["predecessor_landowner_id"] == predecessor["id"]
        active_mid = _active_landowners(api, easement_id, trust_admin_headers)
        assert [lo["id"] for lo in active_mid] == [predecessor["id"]]

        validate_success(
            api.acknowledge_succession_notice(notice["id"], trust_admin_headers), 200
        )
        validate_success(
            api.record_succession_notice(
                notice["id"],
                record_succession_notice_payload(easement_version(easement_id)),
                trust_admin_headers,
            ),
            200,
        )
        active_end = _active_landowners(api, easement_id, trust_admin_headers)
        assert [lo["id"] for lo in active_end] == [successor_id]
