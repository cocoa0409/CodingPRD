"""Catalog registration, share-total and share-lock constraints, foreign-key and
field validation, and basic listing/pagination (PRD §3.1, §2.3, §2.8).
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    create_rightsholder_payload,
    create_work_payload,
    create_composition_share_payload,
    create_recording_payload,
    create_recording_share_payload,
    create_statement_payload,
    next_iswc,
    next_isrc,
    assert_rightsholder,
    create_rightsholder,
    create_registered_work,
)

ADMIN = TEST_USERS["administrator_headers"]
OPERATOR = TEST_USERS["operator_headers"]


# =============================================================================
# Corner queue B — entities
# =============================================================================

class TestRightsholderCreation:
    def test_create_rightsholder_returns_201_with_defaults(self, api):
        """PRD §3.1: "A newly created rightsholder starts with status of ACTIVE,
        lifetime_earned_cents of 0, and unrecouped_balance_cents of 0."
        PRD §3.1: "minimum_payout_cents, which defaults to 5000 ... and withholding_pct,
        which defaults to 0"

        Design: Corner/entities/create_rightsholder_returns_201_with_defaults
        """
        rh = validate_success(api.create_rightsholder(
            create_rightsholder_payload(legal_name="Acme Pub", party_type="PUBLISHER",
                                        payee_country="GB"), ADMIN), expected_status=201)
        assert_rightsholder(rh)
        assert rh["status"] == "ACTIVE"
        assert rh["minimum_payout_cents"] == 5000
        assert rh["withholding_pct"] == 0
        assert rh["lifetime_earned_cents"] == 0
        assert rh["unrecouped_balance_cents"] == 0
        assert rh["version"] == 1

    def test_get_rightsholder_not_found(self, api):
        """PRD §2.8: "every resource named in the URL path must exist; identifiers are
        checked left to right, and the first one that does not resolve yields
        ERR_NOT_FOUND."

        Design: Corner/entities/get_rightsholder_not_found
        """
        resp = api.get_rightsholder(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestWorkValidation:
    def test_create_work_missing_required_field(self, api):
        """PRD §2.8: "the body must be well-formed: required fields present ...; a
        violation yields ERR_INVALID_REQUEST."

        Design: Corner/entities/create_work_missing_required_field
        """
        # Omit the required iswc.
        resp = api.create_work(
            {"title": "No ISWC", "pro_affiliation": "ASCAP", "duration_seconds": 180}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_create_work_invalid_enum_pro_affiliation(self, api):
        """PRD §2.8: "the body must be well-formed: required fields present, enum values
        in range ...; a violation yields ERR_INVALID_REQUEST."

        Design: Corner/entities/create_work_invalid_enum_pro_affiliation
        """
        resp = api.create_work(
            create_work_payload(pro_affiliation="SESAC"), ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_duplicate_iswc_rejected(self, api):
        """PRD §3.1: "Attempting to register a work whose iswc already exists is rejected
        with ERR_DUPLICATE_CODE."

        Design: Corner/entities/duplicate_iswc_rejected
        """
        iswc = next_iswc()
        validate_success(api.create_work(create_work_payload(iswc=iswc, pro_affiliation="BMI"), ADMIN),
                         expected_status=201)
        resp = api.create_work(create_work_payload(iswc=iswc, pro_affiliation="ASCAP"), ADMIN)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_CODE)


class TestComputedSplitTotal:
    def test_recording_split_total_bps_computed_from_shares(self, api):
        """PRD §2.5: "On a Recording, split_total_bps is the analogous sum across that
        recording's master shares."

        Design: Corner/entities/recording_computed_split_total_bps
        """
        holder = create_rightsholder(legal_name="LblX", party_type="LABEL")
        work = create_registered_work(holder["id"], pro_affiliation="NONE",
                                       duration_seconds=200, role="PUBLISHER")
        rec = validate_success(api.create_recording(
            create_recording_payload(work_id=work["id"], release_type="PHYSICAL",
                                    duration_seconds=200), ADMIN), expected_status=201)
        validate_success(api.create_recording_share(
            create_recording_share_payload(recording_id=rec["id"], rightsholder_id=holder["id"],
                                           split_bps=4000), ADMIN), expected_status=201)
        validate_success(api.create_recording_share(
            create_recording_share_payload(recording_id=rec["id"], rightsholder_id=holder["id"],
                                           split_bps=6000), ADMIN), expected_status=201)
        fetched = get_success_data(api.get_recording(rec["id"], ADMIN))
        assert fetched["split_total_bps"] == 10000, "sum of 4000 + 6000, computed"


class TestListingPagination:
    def test_list_statements_paginated_envelope(self, api):
        """PRD §2.3: "List responses carry the pagination fields limit, offset,
        total_count, and has_more inside the meta object of the envelope."

        Design: Corner/entities/list_rightsholders_via_statements_pagination
        """
        holder = create_rightsholder(legal_name="RPaging", party_type="WRITER")
        validate_success(api.create_statement(
            create_statement_payload(rightsholder_id=holder["id"],
                                     period_start="2026-01-01T00:00:00.000Z",
                                     period_end="2026-02-01T00:00:00.000Z"), OPERATOR), expected_status=201)
        validate_success(api.create_statement(
            create_statement_payload(rightsholder_id=holder["id"],
                                     period_start="2026-02-01T00:00:00.000Z",
                                     period_end="2026-03-01T00:00:00.000Z"), OPERATOR), expected_status=201)
        data, meta = validate_paginated(
            api.list_statements(OPERATOR, params={"rightsholder_id": holder["id"], "limit": 1, "offset": 0}))
        assert meta["total_count"] == 2
        assert meta["has_more"] is True
        assert len(data) == 1


# =============================================================================
# Corner queue B — validations (share totals, locks, FK)
# =============================================================================

class TestShareConstraints:
    def test_split_total_exceeding_10000_rejected(self, api):
        """PRD §3.1: "If the new share would push that total above 10000 basis points, it
        is rejected with ERR_SPLIT_TOTAL_INVALID."

        Design: Corner/validations/split_total_exceeds_10000_rejected
        """
        w1 = create_rightsholder(legal_name="RW1", party_type="WRITER")
        w2 = create_rightsholder(legal_name="RW2", party_type="WRITER")
        work = validate_success(api.create_work(create_work_payload(pro_affiliation="ASCAP"), ADMIN),
                                expected_status=201)
        validate_success(api.create_composition_share(
            create_composition_share_payload(work_id=work["id"], rightsholder_id=w1["id"],
                                             role="WRITER", split_bps=7000), ADMIN), expected_status=201)
        # 7000 + 4000 > 10000
        resp = api.create_composition_share(
            create_composition_share_payload(work_id=work["id"], rightsholder_id=w2["id"],
                                             role="WRITER", split_bps=4000), ADMIN)
        validate_error(resp, ApiErrorId.ERR_SPLIT_TOTAL_INVALID)

    def test_register_requires_exactly_10000(self, api):
        """PRD §3.1: "an Administrator registers a work to lock its splits, which is
        permitted only when split_total_bps equals exactly 10000 (and otherwise rejected
        with ERR_SPLIT_TOTAL_INVALID)."

        Design: Corner/validations/register_requires_exactly_10000
        """
        holder = create_rightsholder(legal_name="RReg", party_type="WRITER")
        work = validate_success(api.create_work(create_work_payload(pro_affiliation="ASCAP"), ADMIN),
                                expected_status=201)
        validate_success(api.create_composition_share(
            create_composition_share_payload(work_id=work["id"], rightsholder_id=holder["id"],
                                             role="WRITER", split_bps=6000), ADMIN), expected_status=201)
        resp = api.register_work(work["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_SPLIT_TOTAL_INVALID)

    def test_shares_locked_blocks_new_share(self, api):
        """PRD §3.1: "Once a work's shares are locked, no further composition share may be
        added; such an attempt is rejected with ERR_SHARES_LOCKED."

        Design: Corner/validations/shares_locked_blocks_new_share
        """
        holder = create_rightsholder(legal_name="RLk", party_type="WRITER")
        work = create_registered_work(holder["id"], pro_affiliation="ASCAP", duration_seconds=180,
                                       role="WRITER")
        resp = api.create_composition_share(
            create_composition_share_payload(work_id=work["id"], rightsholder_id=holder["id"],
                                             role="PUBLISHER", split_bps=1), ADMIN)
        validate_error(resp, ApiErrorId.ERR_SHARES_LOCKED)

    def test_fk_not_found_on_recording_create(self, api):
        """PRD §3.1: "a missing work_id with ERR_FK_NOT_FOUND."

        Design: Corner/validations/fk_not_found_on_recording_create
        """
        resp = api.create_recording(
            create_recording_payload(work_id=NON_EXISTENT_UUID, release_type="PHYSICAL",
                                    duration_seconds=200, isrc=next_isrc()), ADMIN)
        validate_error(resp, ApiErrorId.ERR_FK_NOT_FOUND)


# =============================================================================
# Corner queue B — state_machines (advance write-off, window revoke-from-revoked)
# =============================================================================

class TestAdvanceAndWindowState:
    def test_advance_write_off_recomputes_unrecouped(self, api):
        """PRD §3.5: "An Administrator may instead write off an ACTIVE advance, forgiving
        the remaining unrecouped principal: this moves it from ACTIVE to WRITTEN_OFF and
        recomputes the recipient's unrecouped_balance_cents, which excludes written-off
        advances."

        Design: Corner/state_machines/advance_write_off_recomputes_unrecouped
        """
        holder = create_rightsholder(legal_name="RWoff", party_type="WRITER")
        adv = validate_success(api.create_advance(
            {"rightsholder_id": holder["id"], "principal_cents": 50000, "recoupment_pct": 1.0}, ADMIN),
            expected_status=201)
        written = validate_success(api.write_off_advance(adv["id"], ADMIN))
        assert written["status"] == "WRITTEN_OFF"
        holder_after = get_success_data(api.get_rightsholder(holder["id"], ADMIN))
        assert holder_after["unrecouped_balance_cents"] == 0, "write-off excluded from balance"

    def test_revoke_already_revoked_window_rejected(self, api):
        """PRD §3.2: "an Administrator may later revoke it, moving status to REVOKED and
        incrementing its version."
        PRD §2.8: "for an action endpoint, the target resource must currently be in a
        state from which the requested transition is defined, or the request fails with
        ERR_INVALID_STATE."

        Design: Corner/state_machines/rights_window_revoke_from_revoked_invalid_state
        """
        holder = create_rightsholder(legal_name="LblRev", party_type="LABEL")
        work = create_registered_work(holder["id"], pro_affiliation="NONE",
                                       duration_seconds=200, role="PUBLISHER")
        rec = validate_success(api.create_recording(
            create_recording_payload(work_id=work["id"], release_type="PHYSICAL",
                                    duration_seconds=200), ADMIN), expected_status=201)
        window = validate_success(api.create_rights_window(
            {"recording_id": rec["id"], "territory": "US", "rights_type": "MECHANICAL",
             "term_start": "2026-01-01T00:00:00.000Z", "term_end": "2026-02-01T00:00:00.000Z"}, ADMIN),
            expected_status=201)
        validate_success(api.revoke_rights_window(window["id"], ADMIN))
        resp = api.revoke_rights_window(window["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
