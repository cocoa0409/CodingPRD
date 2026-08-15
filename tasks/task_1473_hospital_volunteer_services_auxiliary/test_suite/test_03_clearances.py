"""Clearance intake, adjudication constants, duplicate prevention, FK reverse
lookup, and the resubmit/renewal cycles."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    api_client, ApiErrorId,
    create_clearance_payload,
    set_clock, approve_application, submit_clearance, adjudicate_clearance,
    get_summary,
    make_screener_headers,
)
from test_helpers import TEST_USERS

DIRECTOR = TEST_USERS["director_headers"]
COORDINATOR = TEST_USERS["coordinator_headers"]
SCREENER_1 = TEST_USERS["screener_headers"]
SCREENER_2 = TEST_USERS["screener2_headers"]


class TestClearanceValidation:
    def test_clearance_invalid_enum_rejected(self, api):
        """PRD §3.2: "Three clearance types gate every volunteer's service:
        `BACKGROUND`, valid for 24 calendar months once cleared, and `HEALTH_TB` and
        `HEALTH_FLU`, each valid for 12 calendar months."
        PRD §2.8: "Required fields present, types valid, enum members valid,
        quantities at least 1, amounts non-negative" — reported as
        `ERR_INVALID_REQUEST`.

        Design: Corner/entities/clearance_invalid_enum_rejected
        """
        set_clock("2026-08-01T00:00:00Z")
        _, vol_id = approve_application(full_name="Enum Test", email="et@x.org")
        resp = api.create_clearance(
            create_clearance_payload(volunteer_id=vol_id, clearance_type="DENTAL",
                                     document_ref="doc-1"), SCREENER_1)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        rows = get_success_data(api.list_clearances(SCREENER_1, params={"volunteer_id": vol_id}))
        assert rows == [], f"no clearance row may be created, got {rows}"

    def test_clearance_fk_reverse_lookup_filtered_list(self, api):
        """PRD §4: "List clearances; filter by `volunteer_id`, `clearance_type`,
        `status`".
        PRD §2.3: "List endpoints accept two query parameters." (a filter that matches
        nothing yields an empty list, not an existence error)

        Design: Corner/entities/clearance_fk_reverse_lookup_filtered_list
        """
        set_clock("2026-08-01T00:00:00Z")
        _, vol_id = approve_application(full_name="FK Fred", email="ff@x.org")
        submit_clearance(vol_id, "BACKGROUND", "bg-1")
        submit_clearance(vol_id, "HEALTH_TB", "tb-1")

        mine = get_success_data(api.list_clearances(SCREENER_1, params={"volunteer_id": vol_id}))
        assert len(mine) == 2, f"expected exactly 2 clearance rows, got {len(mine)}"
        assert all(r["status"] == "SUBMITTED" for r in mine)
        assert all(r["volunteer_id"] == vol_id for r in mine)

        none = get_success_data(api.list_clearances(
            SCREENER_1, params={"volunteer_id": "11111111-2222-4333-8444-555555555555"}))
        assert none == [], f"unknown volunteer_id filter must return an empty list, got {none}"


class TestClearanceValidityConstants:
    def test_validity_months_per_type(self, api):
        """PRD §3.2: "A `CLEARED` decision additionally sets `expires_at` to
        `adjudicated_at` plus the type's validity in calendar months — 24 for
        `BACKGROUND`, 12 for `HEALTH_TB`, 12 for `HEALTH_FLU`."

        Design: Corner/calculations/clearance_validity_months_constants
        """
        set_clock("2026-08-01T00:00:00Z")
        _, vol_id = approve_application(full_name="Const Ken", email="ck@x.org")
        bg = submit_clearance(vol_id, "BACKGROUND", "bg-1")
        tb = submit_clearance(vol_id, "HEALTH_TB", "tb-1")
        fl = submit_clearance(vol_id, "HEALTH_FLU", "fl-1")

        bg_done = validate_success(api.adjudicate_clearance(bg["id"], {"decision": "CLEARED"}, SCREENER_2))
        tb_done = validate_success(api.adjudicate_clearance(tb["id"], {"decision": "CLEARED"}, SCREENER_2))
        fl_done = validate_success(api.adjudicate_clearance(fl["id"], {"decision": "CLEARED"}, SCREENER_2))

        assert str(bg_done["expires_at"]).startswith("2028-08-01T00:00:00"), (
            f"BACKGROUND 24 calendar months from 2026-08-01, got {bg_done['expires_at']}")
        assert str(tb_done["expires_at"]).startswith("2027-08-01T00:00:00"), (
            f"HEALTH_TB 12 calendar months from 2026-08-01, got {tb_done['expires_at']}")
        assert str(fl_done["expires_at"]).startswith("2027-08-01T00:00:00"), (
            f"HEALTH_FLU 12 calendar months from 2026-08-01, got {fl_done['expires_at']}")


class TestDuplicateClearance:
    def test_duplicate_clearance_rejected(self, api):
        """PRD §3.2: "At most one clearance per volunteer-and-type pair may exist
        outside the terminal `REVOKED` state: creating a second record while one
        stands `SUBMITTED`, `CLEARED`, `REJECTED`, or `EXPIRED` is rejected with
        `ERR_DUPLICATE_ACTIVE_CLEARANCE`."

        Design: Corner/validations/duplicate_clearance_rejected
        """
        set_clock("2026-08-01T00:00:00Z")
        _, vol_id = approve_application(full_name="Dup Deb", email="dd@x.org")
        first = submit_clearance(vol_id, "BACKGROUND", "bg-1")

        resp = api.create_clearance(
            create_clearance_payload(volunteer_id=vol_id, clearance_type="BACKGROUND",
                                     document_ref="bg-2"), SCREENER_1)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_ACTIVE_CLEARANCE)

        adjudicate_clearance(first["id"], "CLEARED")
        resp = api.create_clearance(
            create_clearance_payload(volunteer_id=vol_id, clearance_type="BACKGROUND",
                                     document_ref="bg-3"), SCREENER_1)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_ACTIVE_CLEARANCE)


class TestClearanceRenewalCycle:
    def _setup(self):
        set_clock("2026-08-01T00:00:00Z")
        _, vol_id = approve_application(full_name="V Renew", date_of_birth="1985-07-07",
                                        email="vr@x.org", phone="555-1201")
        return vol_id, submit_clearance(vol_id, "HEALTH_TB", "tb-v1")

    def test_reject_resubmit_expire_renew_cycle(self, api):
        """PRD §3.2: "The cycle `SUBMITTED` → `CLEARED` → `EXPIRED` → `SUBMITTED` (and
        the detour through `REJECTED`) is how a volunteer stays compliant across years
        of service."
        PRD §3.2: "the annual-review sweep of §3.6 flips a `CLEARED` record whose
        `expires_at` is at or before now to `EXPIRED`."

        Design: Difficulty/non_linear_state_machine/clearance_resubmit_renewal_cycle
        """
        vol_id, clearance = self._setup()
        cid = clearance["id"]

        rejected = validate_success(api.adjudicate_clearance(
            cid, {"decision": "REJECTED", "adjudication_notes": "illegible TB read"},
            SCREENER_2))
        assert rejected["status"] == "REJECTED"

        resubmitted = validate_success(api.resubmit_clearance(
            cid, {"document_ref": "tb-v2"}, SCREENER_2))
        assert resubmitted["status"] == "SUBMITTED", "cycle 1: REJECTED -> SUBMITTED"

        cleared = validate_success(api.adjudicate_clearance(
            cid, {"decision": "CLEARED"}, SCREENER_1))
        assert cleared["status"] == "CLEARED"
        assert str(cleared["expires_at"]).startswith("2027-08-01T00:00:00"), (
            f"HEALTH_TB expires 12 calendar months after 2026-08-01 adjudication, "
            f"got {cleared['expires_at']}")

        set_clock("2027-08-02T00:00:00Z")
        report = validate_success(api.run_annual_review(DIRECTOR))
        assert report["clearances_expired"] == 1, (
            f"exactly one CLEARED clearance is past expiry, got {report}")
        row = get_success_data(api.get_clearance(cid, SCREENER_1))
        assert row["status"] == "EXPIRED", "the sweep flips CLEARED -> EXPIRED"

        resubmitted2 = validate_success(api.resubmit_clearance(
            cid, {"document_ref": "tb-v3"}, SCREENER_1))
        assert resubmitted2["status"] == "SUBMITTED", "cycle 2: EXPIRED -> SUBMITTED"
        cleared2 = validate_success(api.adjudicate_clearance(
            cid, {"decision": "CLEARED"}, SCREENER_2))
        assert cleared2["status"] == "CLEARED"
        assert str(cleared2["expires_at"]).startswith("2028-08-02T00:00:00"), (
            f"second adjudication 2027-08-02 + 12 months, got {cleared2['expires_at']}")

    def test_resubmit_resets_submitter_and_clears_adjudication(self, api):
        """PRD §3.2: "Resubmission with a fresh `document_ref` returns the same record
        to `SUBMITTED`, resets `submitted_by_user_id` to the resubmitting caller's
        `X-User-ID`, and clears `adjudicated_by_user_id`, `adjudicated_at`, and
        `expires_at`."

        Design: Difficulty/non_linear_state_machine/clearance_resubmit_renewal_cycle
        """
        vol_id, clearance = self._setup()
        cid = clearance["id"]
        assert clearance["submitted_by_user_id"] == "screener-1"

        validate_success(api.adjudicate_clearance(
            cid, {"decision": "REJECTED", "adjudication_notes": "illegible"}, SCREENER_2))
        resubmitted = validate_success(api.resubmit_clearance(
            cid, {"document_ref": "tb-v2"}, SCREENER_2))

        assert resubmitted["id"] == cid, "renewal reuses the same record"
        assert resubmitted["status"] == "SUBMITTED"
        assert resubmitted["document_ref"] == "tb-v2"
        assert resubmitted["submitted_by_user_id"] == "screener-2", (
            "submitted_by_user_id resets to the resubmitting caller")
        assert resubmitted.get("adjudicated_by_user_id") is None
        assert resubmitted.get("adjudicated_at") is None
        assert resubmitted.get("expires_at") is None
