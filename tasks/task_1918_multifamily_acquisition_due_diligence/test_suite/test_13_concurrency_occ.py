"""Optimistic concurrency: the three OCC-guarded write endpoints (PRD §2.6)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_approved_price_anchored_projection,
    add_statement_line_payload,
    create_acquisition,
    generate_statement,
    get_acquisition_version,
    get_success_data,
    setup_diligence_complete,
    validate_error,
    validate_success,
)

ANALYST = TEST_USERS["analyst_headers"]
UM1 = TEST_USERS["underwriting_manager_headers"]


class TestTaxProjectionCreateOcc:
    def test_occ_tax_projection_create_stale_version(self, api):
        """PRD §2.6: "Creating a tax reassessment projection must carry
        `expected_acquisition_version` equal to the acquisition's current
        `version`; the creation supersedes the currently approved projection,
        so a create issued with a stale version would silently retire a
        projection the caller never saw, and it is rejected with
        `ERR_STALE_VERSION` (HTTP 412)."
        PRD §3.6: "Creating a projection opens it in `DRAFT`, supersedes
        whichever projection of the same acquisition currently stands
        `APPROVED` (moving it to `SUPERSEDED`), and increments the
        acquisition's `version` by one."

        Design: Corner/cross_cutting_complexity_layers/occ_tax_projection_create_stale_version
        """
        acq = create_acquisition(property_name="OCC One")
        proj1 = validate_success(api.create_tax_projection(
            acq["id"],
            {"method": "PURCHASE_PRICE_ANCHORED",
             "expected_acquisition_version": acq["version"]},
            ANALYST), 201)
        assert proj1["status"] == "DRAFT"
        v2 = get_acquisition_version(acq["id"])
        assert v2 == acq["version"] + 1, "each create bumps the version by 1"

        resp = api.create_tax_projection(
            acq["id"],
            {"method": "INCOME_APPROACH", "cap_rate": 0.055,
             "noi_t12_cents": 16_500_000,
             "expected_acquisition_version": acq["version"]},
            ANALYST)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)

        proj2 = validate_success(api.create_tax_projection(
            acq["id"],
            {"method": "INCOME_APPROACH", "cap_rate": 0.055,
             "noi_t12_cents": 16_500_000,
             "expected_acquisition_version": v2},
            ANALYST), 201)
        assert proj2["status"] == "DRAFT"


class TestStatementGenerateOcc:
    def test_occ_statement_generate_stale_version(self, api):
        """PRD §2.6: "Generating a proration statement likewise must carry
        `expected_acquisition_version` matching the acquisition's current
        `version`, because generation supersedes the approved statement of the
        preceding type and mutates acquisition fields; a mismatch is rejected
        with `ERR_STALE_VERSION` (HTTP 412)."
        PRD §3.8: "Generation computes the statement's generated lines from
        live data per the proration rules below, supersedes the approved
        statement of the preceding type — a new `FINAL_CLOSING` retires the
        approved `DRAFT_CLOSING` to `SUPERSEDED` — stamps `created_by_user_id`
        with the caller, opens the statement in `DRAFT`, and increments the
        acquisition's `version` by one."

        Design: Corner/cross_cutting_complexity_layers/occ_statement_generate_stale_version
        """
        ctx = setup_diligence_complete(property_name="OCC Two")
        acq_id = ctx["acq"]["id"]
        add_approved_price_anchored_projection(acq_id)
        version = get_acquisition_version(acq_id)

        stmt1 = validate_success(api.generate_proration_statement(
            acq_id,
            {"statement_type": "DRAFT_CLOSING", "day_count_method": "ACTUAL_365",
             "expected_acquisition_version": version},
            UM1), 201)
        assert stmt1["status"] == "DRAFT"
        assert get_acquisition_version(acq_id) == version + 1

        resp = api.generate_proration_statement(
            acq_id,
            {"statement_type": "DRAFT_CLOSING", "day_count_method": "ACTUAL_365",
             "expected_acquisition_version": version},
            UM1)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)

        stmts = get_success_data(api.list_proration_statements(
            UM1, params={"acquisition_id": acq_id}))
        assert len(stmts) == 1, "the stale replay created no second statement"


class TestStatementLineAddOcc:
    def test_occ_statement_line_add_stale_version(self, api):
        """PRD §2.6: "Appending a manual line to a proration statement must
        carry `expected_statement_version` equal to the statement's current
        `version`, since the append recomputes the statement's totals; a
        mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412)."
        PRD §3.8: "While a statement is `DRAFT`, an `UnderwritingManager` may
        append a manual line by supplying `expected_statement_version` per §2.6
        together with the `line_type`, `direction`, `amount_cents`, and an
        optional free-text `memo`; the append recomputes the statement's totals
        and increments the statement's `version` by one."

        Design: Corner/cross_cutting_complexity_layers/occ_statement_line_add_stale_version
        """
        ctx = setup_diligence_complete(property_name="OCC Three")
        acq_id = ctx["acq"]["id"]
        add_approved_price_anchored_projection(acq_id)
        stmt = generate_statement(acq_id, "DRAFT_CLOSING", "ACTUAL_365")
        sv1 = stmt["version"]

        line = validate_success(api.add_statement_line(
            stmt["id"],
            add_statement_line_payload(sv1, amount_cents=25_000, memo="first"),
            UM1), 201)
        assert line["source_kind"] == "MANUAL"

        resp = api.add_statement_line(
            stmt["id"],
            add_statement_line_payload(sv1, amount_cents=25_000, memo="stale replay"),
            UM1)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)

        stmt_now = get_success_data(api.get_proration_statement(stmt["id"], UM1))
        assert stmt_now["version"] == sv1 + 1, "exactly one append landed"
        assert stmt_now["total_buyer_credits_cents"] == 93_708 + 1_391_781 + 25_000


class TestExistenceBeatsOcc:
    def test_tax_create_on_missing_acquisition_existence_beats_state_and_occ(self, api):
        """PRD §2.4: "The server applies a fixed validation order to every
        request, from cheapest and most general to most specific: first
        authentication (`ERR_UNAUTHENTICATED`), then role authorization
        (`ERR_FORBIDDEN`), then existence of every identifier referenced by the
        request (the 404 family), then request shape (`ERR_INVALID_REQUEST`,
        `ERR_INVALID_ENUM`, `ERR_INVALID_DATE_RANGE`), then state-machine
        legality (the 409 state family ...), then optimistic-concurrency
        staleness (`ERR_STALE_VERSION`), ..."

        Design: Difficulty/priority_pair_validation_conflict/tax_create_on_missing_acquisition_existence_beats_state_and_occ
        """
        acq = create_acquisition(property_name="Priority Three")
        resp = api.create_tax_projection(
            "00000000-0000-0000-0000-000000000000",
            {"method": "PURCHASE_PRICE_ANCHORED",
             "expected_acquisition_version": acq["version"]},
            ANALYST)
        validate_error(resp, ApiErrorId.ERR_ACQUISITION_NOT_FOUND, 404)

    def test_missing_acquisition_returns_404_never_stale_version(self, api):
        """PRD §2.4: "Existence is validated left-to-right across the request:
        identifiers appearing earlier in the path are checked before later
        ones, and path identifiers are checked before foreign keys supplied in
        the body (`unit_id`, `lease_file_id`, `inspection_id`,
        `acquisition_id`, `supersedes_lease_id`)."
        PRD §2.6: "No other endpoint takes a version field — all other writes
        are serialized purely by state-machine legality."

        Design: Difficulty/priority_pair_validation_conflict/tax_create_on_missing_acquisition_existence_beats_state_and_occ
        """
        acq = create_acquisition(property_name="Priority Three B")
        resp = api.create_tax_projection(
            "00000000-0000-0000-0000-000000000000",
            {"method": "PURCHASE_PRICE_ANCHORED",
             "expected_acquisition_version": acq["version"]},
            ANALYST)
        err = validate_error(resp, ApiErrorId.ERR_ACQUISITION_NOT_FOUND, 404)
        assert err["error_id"] != "ERR_STALE_VERSION", (
            "existence (404) precedes the OCC staleness check (412)"
        )
