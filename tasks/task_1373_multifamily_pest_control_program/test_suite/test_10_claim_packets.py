"""Habitability claim packets: pinned-reference integrity, completed
inspection requirement, and terminal lockdown."""
from test_helpers import (
    ApiErrorId,
    create_claim_packet_payload,
    get_success_data,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    ADMIN,
    MANAGER,
    complete_inspection,
    create_property,
    schedule_inspection,
    schedule_treatment,
    setup_community,
)
from test_helpers.test_users import TEST_USERS

OFFICER = TEST_USERS["compliance_officer_headers"]


class TestClaimPacketFinalizeTwice:
    def test_finalize_twice_returns_already_terminal(self, api):
        """PRD §3.8: "A passing finalization stamps `finalized_at`, moves the
        packet to `FINALIZED`, and renders it immutable."
        PRD §2.4: "Terminal states reject every further action with
        `ERR_ALREADY_TERMINAL` (HTTP 409); a transition that is simply not
        defined from the entity's current non-terminal state is rejected with
        `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/claim_packet_finalize_twice_returns_already_terminal
        """
        prop = create_property(name="Packet Hall", address="11 Packet Way")
        packet = get_success_data(
            api.create_claim_packet(prop["id"],
                                    create_claim_packet_payload(claim_reference="HC-1"),
                                    OFFICER)
        )
        finalized = validate_success(api.finalize_claim_packet(packet["id"], OFFICER))
        assert finalized["status"] == "FINALIZED"
        resp = api.finalize_claim_packet(packet["id"], OFFICER)
        validate_error(resp, ApiErrorId.ERR_ALREADY_TERMINAL)


class TestPinnedReferenceIntegrity:
    def test_claim_packet_stale_reference_rejected(self, api):
        """PRD §3.8: "At creation the server snapshots every referenced
        entity's current `version` into `pinned_references`, and the packet
        sits in `DRAFT`."
        PRD §3.8: "It requires the packet still in `DRAFT`, every pinned entity
        still in existence, every pinned version still equal to the referenced
        entity's current `version` — a drifted reference returns
        `ERR_CLAIM_PACKET_STALE_REFERENCE` (HTTP 409) — and every referenced
        inspection in `COMPLETED`, else `ERR_INSPECTION_NOT_COMPLETED`
        (HTTP 409)."

        Design: Corner/validations/claim_packet_stale_reference_rejected
        """
        ctx = setup_community(with_lease=False, with_resident=False,
                              contract_overrides={"scope_pest_types": ["ROACHES"]})
        unit, tech = ctx["unit"], ctx["technician"]
        insp = schedule_inspection(unit["id"], tech["id"],
                                   scheduled_for="2026-08-05T09:00:00Z")
        complete_inspection(insp["id"], tech, live_sightings=2, evidence_count=0,
                            bed_bug_positive=False)
        tr = schedule_treatment(unit["id"], tech["id"])
        packet = get_success_data(api.create_claim_packet(
            ctx["property"]["id"],
            create_claim_packet_payload(
                claim_reference="HC-9",
                references=[
                    {"entity_type": "Inspection", "entity_id": insp["id"]},
                    {"entity_type": "Treatment", "entity_id": tr["id"]},
                ],
            ),
            OFFICER,
        ))
        # Mutating the referenced treatment advances its version past the pin.
        validate_success(api.notify_prep(tr["id"], MANAGER))

        resp = api.finalize_claim_packet(packet["id"], OFFICER)
        validate_error(resp, ApiErrorId.ERR_CLAIM_PACKET_STALE_REFERENCE)

    def test_claim_packet_uncompleted_inspection_rejected(self, api):
        """PRD §3.8: "It requires the packet still in `DRAFT`, every pinned
        entity still in existence, every pinned version still equal to the
        referenced entity's current `version` — a drifted reference returns
        `ERR_CLAIM_PACKET_STALE_REFERENCE` (HTTP 409) — and every referenced
        inspection in `COMPLETED`, else `ERR_INSPECTION_NOT_COMPLETED`
        (HTTP 409)."

        Design: Corner/validations/claim_packet_uncompleted_inspection_rejected
        """
        ctx = setup_community(with_lease=False, with_resident=False,
                              contract_overrides={"scope_pest_types": ["ROACHES"]})
        insp = schedule_inspection(ctx["unit"]["id"], ctx["technician"]["id"])
        packet = get_success_data(api.create_claim_packet(
            ctx["property"]["id"],
            create_claim_packet_payload(
                claim_reference="HC-10",
                references=[{"entity_type": "Inspection", "entity_id": insp["id"]}],
            ),
            OFFICER,
        ))
        resp = api.finalize_claim_packet(packet["id"], OFFICER)
        validate_error(resp, ApiErrorId.ERR_INSPECTION_NOT_COMPLETED)
