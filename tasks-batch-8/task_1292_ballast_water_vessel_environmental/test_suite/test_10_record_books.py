"""Statutory record books: standing-book creation, entry-kind discipline,
sealed-book immutability, countersignature gating, and voyage-gated sealing."""
import pytest

from test_helpers import (
    ApiErrorId,
    arrive_voyage,
    assert_record_book,
    create_record_book,
    create_vessel,
    find_ballast_book,
    post_book_entry_ok,
    post_treatment_compliant_event_set,
    seal_book_ok,
    setup_voyage_in_progress,
    validate_error,
    validate_success,
)
from test_helpers import api_client


class TestStandingBooks:
    def test_standing_record_book_defaults_open_without_voyage(self, api, vessel_master_headers):
        """PRD section 3.7: "Standing ship-level books of the other three kinds are
        created explicitly by a `ShoreComplianceOfficer` or `VesselMaster` with an
        optional `voyage_id`; a new book starts `OPEN`."
        PRD section 4: "Creating a new resource returns HTTP 201; modifying an
        existing resource returns HTTP 200."

        Design: Corner/entities/standing_record_book_defaults_open_without_voyage
        """
        vessel = create_vessel(imo_number="9100016", vessel_name="MV Gadwall",
                               bwms_type="NONE", gross_tonnage=8000,
                               keel_laid_date="2016-01-01T00:00:00Z",
                               ballast_capacity_m3=4000)
        resp = api.create_record_book(vessel["id"], {"book_kind": "GARBAGE"},
                                      vessel_master_headers)
        book = validate_success(resp, 201)
        assert_record_book(book)
        assert book["status"] == "OPEN"


class TestEntryKindDiscipline:
    def test_entry_kind_mismatch_returns_422(self, api, vessel_master_headers):
        """PRD section 3.7: "An entry kind not allowed for the book's kind is rejected
        with `ERR_ENTRY_KIND_MISMATCH` (HTTP 422)."
        PRD section 3.7: "a `GARBAGE` book accepts `DISCHARGE_SEA`,
        `DISCHARGE_RECEPTION`, and `INCINERATION`"

        Design: Corner/validations/entry_kind_mismatch_returns_422
        """
        vessel = create_vessel(imo_number="9100043", vessel_name="MV Merlin-II",
                               bwms_type="NONE", gross_tonnage=8000,
                               keel_laid_date="2016-01-01T00:00:00Z",
                               ballast_capacity_m3=4000)
        book = create_record_book(vessel["id"], book_kind="GARBAGE")

        resp = api.create_record_book_entry(
            vessel["id"], book["id"],
            {"entry_kind": "UPTAKE", "occurred_at": "2026-07-30T00:00:00Z",
             "quantity": 10, "signed_by": "CREW:A"},
            vessel_master_headers,
        )
        validate_error(resp, ApiErrorId.ERR_ENTRY_KIND_MISMATCH)


class TestSealedBookImmutability:
    def test_sealed_book_rejects_entry_returns_409(self, api, vessel_master_headers):
        """PRD section 3.7: "Sealing by the `VesselMaster` moves a book from `OPEN` to
        `SEALED`, after which it is immutable and archived; the vessel's `version`
        increments."
        PRD section 3.7: "Appending to a sealed book is rejected with
        `ERR_BOOK_SEALED` (HTTP 409)."

        Design: Corner/validations/sealed_book_rejects_entry_returns_409
        """
        vessel = create_vessel(imo_number="9100044", vessel_name="MV Ouzel",
                               bwms_type="NONE", gross_tonnage=8000,
                               keel_laid_date="2016-01-01T00:00:00Z",
                               ballast_capacity_m3=4000)
        book = create_record_book(vessel["id"], book_kind="GARBAGE")
        sealed = seal_book_ok(vessel["id"], book["id"])
        assert sealed["status"] == "SEALED"

        resp = api.create_record_book_entry(
            vessel["id"], book["id"],
            {"entry_kind": "DISCHARGE_RECEPTION", "occurred_at": "2026-07-30T00:00:00Z",
             "quantity": 5, "signed_by": "CREW:A"},
            vessel_master_headers,
        )
        validate_error(resp, ApiErrorId.ERR_BOOK_SEALED)


class TestCountersignatureGate:
    def test_seal_with_missing_countersignature_returns_409(self, api, vessel_master_headers):
        """PRD section 3.7: "A countersignature is required for `OILY_WATER` and
        `SEWAGE` entries."
        PRD section 3.7: "Sealing requires the book to be `OPEN`; for a
        `BALLAST_WATER` book, the voyage's `compliance_status` must be `COMPLIANT`,
        `NONCOMPLIANT`, or `EXEMPT`; and every entry in the book must carry its
        required countersignature."
        PRD section 2.5: "An attempt to invoke a state transition that the target
        entity's current state does not permit is rejected with `ERR_INVALID_STATE`
        (HTTP 409)"

        Design: Corner/validations/seal_with_missing_countersignature_returns_409
        """
        vessel = create_vessel(imo_number="9100045", vessel_name="MV Puffin",
                               bwms_type="NONE", gross_tonnage=8000,
                               keel_laid_date="2016-01-01T00:00:00Z",
                               ballast_capacity_m3=4000)
        book = create_record_book(vessel["id"], book_kind="OILY_WATER")
        # countersigned_by is optional at append time (PRD: "optionally
        # `countersigned_by`"); the requirement bites at sealing.
        entry = post_book_entry_ok(
            vessel["id"], book["id"], entry_kind="BILGE_DISCHARGE",
            occurred_at="2026-07-30T00:00:00Z", quantity=10, position_lat=40.5,
            position_lon=-70.0, distance_from_shore_nm=15, signed_by="CREW:Chief",
        )
        assert entry["id"]

        resp = api.seal_record_book(vessel["id"], book["id"], vessel_master_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestBallastBookVoyageGate:
    def _setup_departed_voyage_with_book(self):
        vessel, plan, voyage = setup_voyage_in_progress(
            imo_number="9000020", vessel_name="MV Tern", voyage_number="V8002",
            arrived_at="2026-08-10T00:00:00Z",
        )
        post_treatment_compliant_event_set(vessel["id"], voyage["id"], tank_id="T1",
                                           volume_m3=500)
        book = find_ballast_book(vessel["id"], voyage["id"])
        return vessel, voyage, book

    def test_seal_ballast_book_rejected_while_voyage_in_progress(self, api,
                                                                 vessel_master_headers):
        """PRD section 3.7: "Sealing requires the book to be `OPEN`; for a
        `BALLAST_WATER` book, the voyage's `compliance_status` must be `COMPLIANT`,
        `NONCOMPLIANT`, or `EXEMPT`; and every entry in the book must carry its
        required countersignature."
        PRD section 3.2: "creates a voyage-scoped record book of kind `BALLAST_WATER`
        in `OPEN` status"
        PRD section 2.5: "An attempt to invoke a state transition that the target
        entity's current state does not permit is rejected with `ERR_INVALID_STATE`
        (HTTP 409)"

        Design: Difficulty/cross_entity_state_dependency/ballast_book_seal_requires_voyage_terminal
        """
        vessel, voyage, book = self._setup_departed_voyage_with_book()
        assert book["status"] == "OPEN", "book auto-created OPEN at depart"

        resp = api.seal_record_book(vessel["id"], book["id"], vessel_master_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_seal_ballast_book_succeeds_after_voyage_compliant(self, api,
                                                               vessel_master_headers):
        """PRD section 3.7: "Sealing by the `VesselMaster` moves a book from `OPEN` to
        `SEALED`, after which it is immutable and archived; the vessel's `version`
        increments. Sealing requires the book to be `OPEN`; for a `BALLAST_WATER`
        book, the voyage's `compliance_status` must be `COMPLIANT`, `NONCOMPLIANT`,
        or `EXEMPT`; and every entry in the book must carry its required
        countersignature."

        Design: Difficulty/cross_entity_state_dependency/ballast_book_seal_requires_voyage_terminal
        """
        vessel, voyage, book = self._setup_departed_voyage_with_book()

        blocked = api.seal_record_book(vessel["id"], book["id"], vessel_master_headers)
        validate_error(blocked, ApiErrorId.ERR_INVALID_STATE)

        arrive_voyage(vessel["id"], voyage["id"])  # commits COMPLIANT
        resp = api.seal_record_book(vessel["id"], book["id"], vessel_master_headers)
        sealed = validate_success(resp, 200)
        assert sealed["status"] == "SEALED"
