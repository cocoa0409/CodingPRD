"""Rooming finalize doc-completeness gate and room-capacity constraint (queue-A rule 7 + corner)."""
from test_helpers import (
    validate_success, validate_error, OPERATOR,
    ApiErrorId,
    setup_open_departure, enroll, make_room, add_member,
)


class TestRoomingFinalizeRequiresDocs:
    """Design: Difficulty/cross_entity_state_dependency/rooming_finalize_requires_member_permission_form_approved"""

    def _room_with_incomplete_member(self, api):
        ctx = setup_open_departure(api, clock="2026-08-18T00:00:00Z")
        # MALE member into a MALE room (gender matches, count 1 <= capacity 2) so only the
        # doc-completeness gate can fail.
        enr = enroll(api, ctx["departure"]["id"], traveler_name="Moe Ka", traveler_gender="MALE")
        room = make_room(api, ctx["departure"]["id"], room_label="R-305", room_type="DOUBLE", room_gender="MALE")
        add_member(api, room["id"], enr["id"])
        return room

    def test_finalize_without_approved_form_returns_docs_incomplete(self, api):
        """PRD §3.8: "finalization requires that the member count be at least 1 and not
        exceed capacity (an over-capacity room is rejected with ERR_ROOM_FULL), that every
        member enrollment be document-complete with an approved permission form (otherwise
        ERR_DOCS_INCOMPLETE), and that every member's gender match the room's gender".

        Design: Difficulty/cross_entity_state_dependency/rooming_finalize_requires_member_permission_form_approved
        """
        room = self._room_with_incomplete_member(api)
        resp = api.finalize_rooming_assignment(room["id"], OPERATOR)
        validate_error(resp, ApiErrorId.ERR_DOCS_INCOMPLETE.value, expected_status=409)

    def test_room_stays_draft_after_rejected_finalize(self, api):
        """PRD §3.8: "Finalizing a room advances it DRAFT → FINALIZED and locks its members".

        Design: Difficulty/cross_entity_state_dependency/rooming_finalize_requires_member_permission_form_approved
        """
        room = self._room_with_incomplete_member(api)
        api.finalize_rooming_assignment(room["id"], OPERATOR)
        fetched = validate_success(api.get_rooming_assignment(room["id"], OPERATOR))
        assert fetched["status"] == "DRAFT", "rejected finalize must leave the room DRAFT"


def test_rooming_member_add_over_capacity_returns_room_full(api):
    """PRD §3.8: "Adding a member appends the given enrollment_id to member_enrollment_ids,
    subject to two checks: the room must not already be full — the current member count must
    be below capacity, else ERR_ROOM_FULL — and the member's traveler_gender must equal the
    room's room_gender, else ERR_ROOMING_GENDER_MISMATCH (HTTP 422)."

    Design: Corner/validations/rooming_member_add_same_gender_over_capacity_returns_room_full
    """
    ctx = setup_open_departure(api, clock="2026-08-18T00:00:00Z")
    m1 = enroll(api, ctx["departure"]["id"], traveler_name="H1", traveler_gender="MALE")
    m2 = enroll(api, ctx["departure"]["id"], traveler_name="H2", traveler_gender="MALE", traveler_dob="2010-05-02T00:00:00Z")
    m3 = enroll(api, ctx["departure"]["id"], traveler_name="H3", traveler_gender="MALE", traveler_dob="2010-05-03T00:00:00Z")
    room = make_room(api, ctx["departure"]["id"], room_label="R-410", room_type="DOUBLE", room_gender="MALE")
    add_member(api, room["id"], m1["id"])
    add_member(api, room["id"], m2["id"])  # room now full (2/2)
    # third member is also MALE, so gender matches and only the capacity check can fail.
    resp = api.add_rooming_member(room["id"], {"enrollment_id": m3["id"]}, OPERATOR)
    validate_error(resp, ApiErrorId.ERR_ROOM_FULL.value, expected_status=409)
