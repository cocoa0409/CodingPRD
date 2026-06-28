"""Consignment intake, provenance log, and the suspended-artist gate."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    create_gallery, create_artist, create_artwork,
    setup_gallery_artist_artwork,
    TEST_USERS,
)
from test_helpers import factories as f

ADMIN = TEST_USERS["gallery_admin_headers"]
REGISTRAR = TEST_USERS["registrar_headers"]


class TestSuspendedArtistGate:
    def test_consign_blocked_for_suspended_artist(self, api):
        """PRD §3.2: "If the named artist is `SUSPENDED`, the consignment is refused
        with `ERR_ARTIST_SUSPENDED`."
        PRD §3.1: "The suspension gate is enforced at three points — consigning an
        artwork, creating a sale of the artist's work, and creating a payout — and
        each rejects with `ERR_ARTIST_SUSPENDED` when the relevant artist is
        `SUSPENDED`."

        Design: Difficulty/cross_entity_state_dependency/artwork_consign_blocked_by_suspended_artist
        """
        gallery = create_gallery()
        artist = create_artist(gallery["id"])
        validate_success(api.suspend_artist(artist["id"], ADMIN))
        resp = api.create_artwork(f.create_artwork_payload(
            gallery["id"], artist["id"], title="Blocked",
            list_price_cents=100_000, insured_value_cents=100_000), ADMIN)
        validate_error(resp, ApiErrorId.ERR_ARTIST_SUSPENDED.value)

    def test_consign_allowed_after_reinstate(self, api):
        """PRD §3.1: "Reinstating an artist requires that they are currently
        `SUSPENDED` and moves them `SUSPENDED → ACTIVE` with no further effect."
        PRD §3.2: "If the named artist is `SUSPENDED`, the consignment is refused
        with `ERR_ARTIST_SUSPENDED`."

        Design: Difficulty/cross_entity_state_dependency/artwork_consign_blocked_by_suspended_artist
        """
        gallery = create_gallery()
        artist = create_artist(gallery["id"])
        validate_success(api.suspend_artist(artist["id"], ADMIN))
        validate_success(api.reinstate_artist(artist["id"], ADMIN))
        resp = api.create_artwork(f.create_artwork_payload(
            gallery["id"], artist["id"], title="Now OK",
            list_price_cents=100_000, insured_value_cents=100_000), ADMIN)
        artwork = validate_success(resp, 201)
        assert artwork["status"] == "CONSIGNED", \
            "a reinstated ACTIVE artist can consign again"


class TestProvenance:
    def test_provenance_append_increments_count(self, api):
        """PRD §3.2: "Only a `Registrar` may append a manual provenance entry,
        supplying the `event` text; the entry is stamped with the current clock as
        its `at_utc` and `provenance_count` is incremented."

        Design: Corner/endpoints/provenance_append_increments_log
        """
        gallery, artist, artwork = setup_gallery_artist_artwork(
            artwork_overrides={"list_price_cents": 100_000, "insured_value_cents": 100_000})
        # A freshly consigned artwork already has the consign entry (count 1).
        assert artwork["provenance_count"] == 1
        resp = api.append_provenance(
            artwork["id"], f.provenance_payload("Acquired by Smith Collection"),
            REGISTRAR)
        updated = validate_success(resp, 201)
        assert updated["provenance_count"] == 2, "manual append increments the count"

    def test_provenance_append_empty_event_rejected(self, api):
        """PRD §3.2: "An append whose `event` string is empty or only whitespace is
        rejected with `ERR_DUPLICATE_PROVENANCE_EVENT`."

        Design: Corner/validations/provenance_append_empty_event_rejected
        """
        gallery, artist, artwork = setup_gallery_artist_artwork(
            artwork_overrides={"list_price_cents": 100_000, "insured_value_cents": 100_000})
        resp = api.append_provenance(artwork["id"], {"event": ""}, REGISTRAR)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_PROVENANCE_EVENT.value)


class TestArtworkCreation:
    def test_artwork_system_fields_set_on_consign(self, api):
        """PRD §3.2: "A freshly consigned work enters `status` of `CONSIGNED`, and
        the system appends a first provenance entry recording the consignment
        event."
        PRD §3.2: "a `provenance_count` giving the number of entries appended."

        Design: Corner/entities/artwork_system_fields_generated_input_ignored
        """
        gallery = create_gallery()
        artist = create_artist(gallery["id"])
        resp = api.create_artwork(f.create_artwork_payload(
            gallery["id"], artist["id"], title="Sf W",
            list_price_cents=100_000, insured_value_cents=100_000), ADMIN)
        artwork = validate_success(resp, 201)
        assert artwork["status"] == "CONSIGNED", "status is system-set to CONSIGNED"
        assert artwork["provenance_count"] == 1, "one provenance entry on consign"

    def test_artwork_initial_state_is_consigned(self, api):
        """PRD §3.2: "A freshly consigned work enters `status` of `CONSIGNED`".
        PRD §3.2: "Each artwork holds a `provenance_log`, an ordered array of
        records each shaped `{seq, event, at_utc}` where `seq` starts at 1 and
        increases by one per entry".

        Design: Corner/state_machines/artwork_initial_state_is_consigned
        """
        gallery = create_gallery()
        artist = create_artist(gallery["id"])
        resp = api.create_artwork(f.create_artwork_payload(
            gallery["id"], artist["id"], title="In W",
            list_price_cents=100_000, insured_value_cents=100_000), ADMIN)
        artwork = validate_success(resp, 201)
        assert artwork["status"] == "CONSIGNED"
        assert artwork["provenance_log"][0]["seq"] == 1, "provenance seq starts at 1"

    def test_get_unknown_artwork_returns_not_found(self, api):
        """PRD §2.5: "The first reference that does not resolve within scope yields
        `ERR_NOT_FOUND`, and that check happens before any state, concurrency, or
        business rule is evaluated."

        Design: Corner/entities/get_artwork_not_found_returns_404
        """
        create_gallery()  # gallery exists; the probed artwork does not.
        resp = api.get_artwork("00000000-0000-4000-8000-000000000001", ADMIN)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)
