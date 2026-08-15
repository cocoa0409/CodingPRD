"""Programs, academic years, and the block diagram: creation defaults, year
span rule, block generation, activation guard, and OCC-guarded regeneration
(PRD §3.1)."""
from test_helpers import (
    DIO, NON_EXISTENT_UUID, PC, PD, ApiClient, ApiErrorId, assert_program,
    assert_schedule_block, create_year_payload, list_blocks, make_active_year,
    make_program, make_year, validate_error, validate_paginated,
    validate_success,
)


class TestProgramCreationDefaults:
    def test_program_created_with_computed_continued_status(self, api: ApiClient):
        """PRD §3.1: "The program's `accreditation_status` is computed, not
        entered: it starts at `CONTINUED` and thereafter derives from the
        program's unresolved serious citations (§3.9)."
        PRD §2.5: "`version` (integer): starts at 1 at creation and increments
        by exactly 1 on every mutation of the resource".

        Design: Corner/entities/program_creation_computed_defaults
        """
        resp = api.create_program(
            {"name": "Metro IM", "specialty": "INTERNAL_MEDICINE",
             "acgme_program_code": "140-00-1001"}, DIO)
        data = validate_success(resp, expected_status=201)
        assert_program(data)
        assert data["version"] == 1
        assert data["accreditation_status"] == "CONTINUED"
        body = resp.json()
        assert body["response_type"] == "object"
        assert isinstance(body["meta"]["api_request_id"], str)
        assert isinstance(body["meta"]["api_request_timestamp"], str)


class TestYearAndBlockDiagram:
    def test_year_creation_generates_thirteen_blocks(self, api: ApiClient):
        """PRD §3.1: "Creating the year immediately generates thirteen
        `ScheduleBlock` rows for it, each stamped with the owning
        `academic_year_id`, a `block_index` from 1 through 13, and its own
        half-open date range: block i covers the 28 days beginning at
        `start_date` plus (i−1) × 28 days and ending at `start_date` plus
        i × 28 days."
        PRD §2.3: "The single exception is the schedule-block list, which is
        sorted by `block_index` ascending so that block capture by index is
        deterministic."

        Design: Corner/entities/year_creation_generates_thirteen_blocks
        """
        program = make_program()
        year = make_year(program["id"])
        assert year["status"] == "PLANNING"

        resp = api.list_schedule_blocks(
            PC, params={"academic_year_id": year["id"], "limit": 100})
        blocks, meta = validate_paginated(resp)
        assert meta["total_count"] == 13
        assert len(blocks) == 13
        for block in blocks:
            assert_schedule_block(block)
            assert block["status"] == "CURRENT"
            assert block["academic_year_id"] == year["id"]
        assert [b["block_index"] for b in blocks] == list(range(1, 14))
        assert blocks[0]["start_date"].startswith("2026-07-01")
        assert blocks[12]["end_date"].startswith("2027-06-30")

    def test_year_with_363_day_span_rejected(self, api: ApiClient):
        """PRD §3.1: "The span from `start_date` to `end_date` must equal
        exactly 364 days — thirteen 28-day blocks; any other span is rejected
        with `ERR_INVALID_YEAR_SPAN` (HTTP 422)."

        Design: Corner/entities/year_invalid_span_rejected
        """
        program = make_program()
        resp = api.create_academic_year(
            create_year_payload(program["id"], end_date="2027-06-29"), PC)
        validate_error(resp, ApiErrorId.ERR_INVALID_YEAR_SPAN)
        assert resp.status_code == 422
        # No year (and therefore no blocks) was created.
        _, meta = validate_paginated(api.list_academic_years(
            PC, params={"program_id": program["id"]}))
        assert meta["total_count"] == 0

    def test_year_double_activate_rejected(self, api: ApiClient):
        """PRD §3.1: "Activating a year — a `ProgramCoordinator` action —
        requires the year to be in `PLANNING` (otherwise
        `ERR_ACADEMIC_YEAR_NOT_PLANNING`, HTTP 409) and requires exactly
        thirteen `CURRENT` schedule blocks to exist for it, which creation
        guarantees and regeneration restores."

        Design: Corner/state_machines/year_double_activate_rejected
        """
        program = make_program()
        year = make_year(program["id"])
        activated = validate_success(api.activate_academic_year(year["id"], PC))
        assert activated["status"] == "ACTIVE"
        assert activated["version"] == 2

        resp = api.activate_academic_year(year["id"], PC)
        validate_error(resp, ApiErrorId.ERR_ACADEMIC_YEAR_NOT_PLANNING)
        after = validate_success(api.get_academic_year(year["id"], PC))
        assert after["version"] == 2, "failed transition must not mutate the year"
        assert after["status"] == "ACTIVE"


class TestBlockRegenerationOCC:
    def test_regenerate_supersedes_blocks_and_stale_replay_fails(self, api: ApiClient):
        """PRD §3.1: "While a year is still `PLANNING`, the coordinator may
        regenerate its block diagram: this optimistic-concurrency-protected
        action (§2.7) marks every existing `CURRENT` block `SUPERSEDED`,
        creates thirteen fresh `CURRENT` blocks with `block_index` 1 through 13
        laid out from the year's `start_date` by the same 28-day rule, and
        increments the year's `version` by 1."
        PRD §2.7: "Regenerating the block diagram of an academic year requires
        `expected_academic_year_version` carrying the year's last observed
        `version`; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/occ_regenerate_blocks_stale_and_supersede
        """
        program = make_program()
        year = make_year(program["id"])
        assert year["version"] == 1
        old_blocks = list_blocks(year["id"], status="CURRENT")
        old_block1 = old_blocks[0]["id"]

        regenerated = validate_success(api.regenerate_blocks(
            year["id"], {"expected_academic_year_version": year["version"]}, PC))
        assert regenerated["version"] == 2

        superseded, meta_s = validate_paginated(api.list_schedule_blocks(
            PC, params={"academic_year_id": year["id"], "status": "SUPERSEDED",
                        "limit": 100}))
        current, meta_c = validate_paginated(api.list_schedule_blocks(
            PC, params={"academic_year_id": year["id"], "status": "CURRENT",
                        "limit": 100}))
        assert meta_s["total_count"] == 13
        assert meta_c["total_count"] == 13
        assert all(b["status"] == "SUPERSEDED" for b in superseded)
        assert old_block1 in {b["id"] for b in superseded}
        assert current[0]["id"] != old_block1

        stale = api.regenerate_blocks(
            year["id"], {"expected_academic_year_version": year["version"]}, PC)
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)
        assert stale.status_code == 412

    def test_regenerate_after_activation_rejected(self, api: ApiClient):
        """PRD §3.1: "Attempting regeneration on a year that is no longer
        `PLANNING` fails with `ERR_ACADEMIC_YEAR_NOT_PLANNING`."

        Design: Corner/cross_cutting_complexity_layers/occ_regenerate_blocks_stale_and_supersede
        """
        program = make_program()
        year = make_active_year(program["id"])
        assert year["version"] == 2
        # OCC passes (correct current version); the state rule fires.
        resp = api.regenerate_blocks(
            year["id"], {"expected_academic_year_version": year["version"]}, PC)
        validate_error(resp, ApiErrorId.ERR_ACADEMIC_YEAR_NOT_PLANNING)
        assert resp.status_code == 409


class TestNotFoundAndAuth:
    def test_get_resident_not_found_returns_404(self, api: ApiClient):
        """PRD §2.9: "When a request references multiple resources, the system
        validates existence in a strict left-to-right order: path identifiers
        first, then body identifiers in their declared input order, rejecting
        with `ERR_NOT_FOUND` at the first missing reference."

        Design: Corner/entities/get_resident_not_found_returns_404
        """
        make_program()
        resp = api.get_resident(NON_EXISTENT_UUID, PD)
        err = validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
        assert resp.status_code == 404
        body = resp.json()
        assert body["response_type"] == "error"
        assert isinstance(err["message"], str) and err["message"].strip()
