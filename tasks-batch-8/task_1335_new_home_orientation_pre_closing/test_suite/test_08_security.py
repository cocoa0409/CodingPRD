"""Authentication, role authorization, and entity-backed ownership."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    get_success_data,
    make_buyer_headers,
    make_rep_headers,
    validate_error,
    validate_success,
)
from test_helpers import fixtures as fx


class TestAuthentication:
    def test_undeclared_role_rejected(self, api):
        """PRD §2.1: "A request whose role header is missing or does not name
        one of the declared roles is rejected with `ERR_UNAUTHENTICATED`
        (HTTP 401)."

        Design: Corner/validations/missing_auth_header_returns_unauthenticated
        """
        headers = {
            "X-User-ID": "test-anon-1",
            "X-User-Role": "Anonymous",
            "Content-Type": "application/json",
        }
        # Authentication outranks even path existence.
        resp = api.get_home(NON_EXISTENT_UUID, headers)
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


class TestValidationOrdering:
    def test_schema_validation_beats_existence(self, api):
        """PRD §2.8: "a request with a malformed payload aimed at a non-existent
        home is rejected with `ERR_VALIDATION`, not `ERR_NOT_FOUND`, because
        schema validation sits earlier in the order"

        Design: Corner/validations/schema_validation_beats_existence
        """
        _community, _buyer, rep = fx.setup_base()
        resp = api.classify_deficiency_item(
            NON_EXISTENT_UUID,
            {"classification": "BOGUS", "estimated_repair_cost_cents": 100},
            make_rep_headers(rep["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION)


class TestRolePermissions:
    def test_confirm_as_rep_forbidden(self, api, manager_headers):
        """PRD §4: the routing summary lists `POST /api/appointments/{id}/confirm`
        — "Confirm a `REQUESTED` appointment; home moves to
        `ORIENTATION_SCHEDULED`" — as authorized for CustomerCareManager only.
        PRD §2.1: "A request whose role is recognized but not permitted for the
        target operation is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/confirm_as_rep_forbidden
        """
        community, buyer, rep = fx.setup_base()
        home = fx.setup_home(community["id"], buyer["id"])
        appt = fx.create_appointment(home["id"], rep["id"], "2026-08-25T14:00:00Z")
        resp = api.confirm_appointment(appt["id"], make_rep_headers(rep["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        appt = get_success_data(api.get_appointment(appt["id"], manager_headers))
        assert appt["status"] == "REQUESTED", (
            f"forbidden confirm must not move the appointment, got {appt['status']}"
        )

    def test_classify_as_homebuyer_forbidden(self, api):
        """PRD §3.4: "Classification, also by the representative, moves the item
        `IDENTIFIED` → `CLASSIFIED`"
        PRD §2.1: "A request whose role is recognized but not permitted for the
        target operation is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/classify_as_homebuyer_forbidden
        """
        community, buyer, rep = fx.setup_base()
        home = fx.setup_home(community["id"], buyer["id"])
        appt = fx.setup_orientation_in_progress(
            home["id"], rep["id"], "2026-08-25T14:00:00Z"
        )
        item = fx.create_deficiency(home["id"], appt["id"], rep["id"],
                                    title="Paint scuff")
        resp = api.classify_deficiency_item(
            item["id"],
            {"classification": "WARRANTABLE", "estimated_repair_cost_cents": 100},
            make_buyer_headers(buyer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_signoff_as_manager_forbidden(self, api, manager_headers):
        """PRD §3.5: "Sign-off belongs to the buyer alone, checked against the
        home's `primary_buyer_id` with mismatches rejected as `ERR_FORBIDDEN`."
        PRD §2.1: "A request whose role is recognized but not permitted for the
        target operation is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/signoff_as_manager_forbidden
        """
        community, buyer, rep = fx.setup_base()
        home = fx.setup_home(community["id"], buyer["id"])
        appt = fx.setup_orientation_in_progress(
            home["id"], rep["id"], "2026-08-25T14:00:00Z"
        )
        item = fx.create_deficiency(home["id"], appt["id"], rep["id"],
                                    title="Trap leak")
        fx.classify_deficiency(item["id"], rep["id"], estimated_repair_cost_cents=20_000)
        fx.decide_deficiency(item["id"], "COMPLETE_BEFORE_CLOSING")
        fx.move_item_to_ready_for_reinspection(item["id"], rep["id"])
        fx.verify_item_via_reinspection(item["id"], home["id"], rep["id"],
                                        "2026-08-26T10:00:00Z")
        resp = api.sign_off_deficiency_item(item["id"], manager_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_release_as_rep_forbidden(self, api):
        """PRD §3.7: "Releases come after closing and are manager-only,
        OCC-guarded writes"
        PRD §2.1: "A request whose role is recognized but not permitted for the
        target operation is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/release_as_rep_forbidden
        """
        community, buyer, rep = fx.setup_base(
            community_overrides={"holdback_cost_multiplier": 2.0,
                                 "holdback_min_cents": 1_000,
                                 "holdback_max_cents": 10_000_000}
        )
        home = fx.setup_home(community["id"], buyer["id"])
        appt = fx.create_appointment(home["id"], rep["id"], "2026-08-25T14:00:00Z")
        fx.confirm_appointment(appt["id"])
        fx.set_clock("2026-08-25T14:00:00Z")
        fx.start_appointment(appt["id"], rep["id"])
        item = fx.create_deficiency(home["id"], appt["id"], rep["id"],
                                    title="Furnace fault")
        fx.classify_deficiency(item["id"], rep["id"], estimated_repair_cost_cents=20_000)
        fx.decide_deficiency(item["id"], "COMPLETE_AFTER_CLOSING")
        fx.add_verified_buyer_attendee(appt["id"], buyer["id"], acting_rep_id=rep["id"])
        fx.mark_checklist(appt["id"], rep["id"])
        fx.complete_appointment(appt["id"], rep["id"])
        escrow = fx.get_escrow_for_home(home["id"])
        resp = api.release_escrow_holdback(
            escrow["id"], {"expected_escrow_version": escrow["version"]},
            make_rep_headers(rep["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_survey_submit_as_rep_forbidden(self, api):
        """PRD §3.8: "The buyer — and only the buyer, with ownership checked
        against `primary_buyer_id` and mismatches rejected as `ERR_FORBIDDEN`
        — submits `overall_rating`, `systems_demo_rating`, and
        `timeliness_rating`"
        PRD §2.1: "A request whose role is recognized but not permitted for the
        target operation is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/survey_submit_as_rep_forbidden
        """
        community, buyer, rep = fx.setup_base()
        home = fx.setup_home(community["id"], buyer["id"],
                             closing_date="2026-09-20T17:00:00Z")
        fx.setup_completed_orientation(
            home["id"], rep["id"], buyer["id"], "2026-08-25T14:00:00Z"
        )
        survey = fx.get_survey_for_home(home["id"])
        resp = api.submit_feedback_survey(
            survey["id"],
            {"overall_rating": 5, "systems_demo_rating": 5,
             "timeliness_rating": 5, "would_recommend": True},
            make_rep_headers(rep["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


class TestBuyerOwnership:
    def test_signoff_by_other_buyer_forbidden(self, api):
        """PRD §2.1: "When `X-User-Role` is `Homebuyer`, `X-User-ID` is the `id`
        of the acting `Homebuyer`; every buyer-scoped write compares the target
        home's `primary_buyer_id` to `X-User-ID` and rejects a mismatch with
        `ERR_FORBIDDEN` (HTTP 403)."
        PRD §3.5: "Sign-off belongs to the buyer alone, checked against the
        home's `primary_buyer_id` with mismatches rejected as `ERR_FORBIDDEN`."

        Design: Corner/validations/ownership_enforced_for_signoff
        """
        community, buyer, rep = fx.setup_base()
        other_buyer = fx.setup_buyer(full_name="Bob Baxter")
        home = fx.setup_home(community["id"], buyer["id"])
        appt = fx.setup_orientation_in_progress(
            home["id"], rep["id"], "2026-08-25T14:00:00Z"
        )
        item = fx.create_deficiency(home["id"], appt["id"], rep["id"],
                                    title="Trap leak")
        fx.classify_deficiency(item["id"], rep["id"], estimated_repair_cost_cents=20_000)
        fx.decide_deficiency(item["id"], "COMPLETE_BEFORE_CLOSING")
        fx.move_item_to_ready_for_reinspection(item["id"], rep["id"])
        fx.verify_item_via_reinspection(item["id"], home["id"], rep["id"],
                                        "2026-08-26T10:00:00Z")
        resp = api.sign_off_deficiency_item(
            item["id"], make_buyer_headers(other_buyer["id"])
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
