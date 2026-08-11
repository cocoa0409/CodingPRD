"""Written consent: snapshot evaluation order, deadline enforcement, and
checkpoint lapse."""
from test_helpers import (
    ApiErrorId,
    add_directors,
    create_consent_resolution,
    file_disclosure,
    get_success_data,
    set_clock,
    setup_circulating_consent,
    setup_corporation_with_directors,
    sign_consent,
    validate_error,
    validate_success,
    SECRETARY,
)
from test_helpers import api_client


class TestConsentSnapshotEvaluationOrder:
    """Difficulty instance: consent_required_count_snapshot_evaluation_order.

    4 ACTIVE directors; D4 has OPEN disclosure for 'Acme'. Resolution related_party
    'Acme' circulates with unanimity required -> required = 4 - 1 = 3. D4's
    disclosure is cleared AFTER circulation; the snapshot must not move.
    """

    def _setup(self, api):
        corp, _bylaws, directors = setup_corporation_with_directors(4, name="Corp C")
        d1, d2, d3, d4 = directors
        cd = file_disclosure(d4["id"], corp["id"], related_party="Acme")
        r = create_consent_resolution(
            corp["id"], title="Acme contract", text="Approve Acme contract", related_party="Acme"
        )
        r_circulating = get_success_data(api.circulate_consent(r["id"], SECRETARY))
        # Clear the disclosure AFTER circulation; snapshot must stay.
        api.clear_conflict_disclosure(cd["id"], SECRETARY)
        return corp, directors, cd, r_circulating

    def test_snapshot_immune_to_post_circulation_clearance(self, api):
        """PRD §3.7: "the count is stored on the resolution and never changes
        afterward: disclosures filed later, clearances, and resignations leave
        the stored requirement untouched."

        Design: Difficulty/combinatorial_formula/consent_required_count_snapshot_evaluation_order
        """
        _corp, _directors, _cd, r = self._setup(api)
        after = get_success_data(api.get_resolution(r["id"], SECRETARY))
        assert after["consent_required_count"] == 3, (
            f"expected snapshot 3, got {after['consent_required_count']}"
        )
        assert after["consent_deadline_at"].startswith("2026-05-11T00:00:00"), (
            f"expected deadline 2026-05-11T00:00:00Z, got {after['consent_deadline_at']}"
        )

    def test_consent_adopts_on_exactly_required_signatures(self, api):
        """PRD §3.7: "When the count of `ACTIVE` consent records voting `FOR`
        has reached the stored `consent_required_count`, the resolution moves
        `CIRCULATING` → `CONSENT_ADOPTED` with `closed_at` stamped."

        Design: Difficulty/combinatorial_formula/consent_required_count_snapshot_evaluation_order
        """
        _corp, directors, cd, r = self._setup(api)
        d1, d2, d3, _d4 = directors
        sign_consent(r["id"], d1["id"], "FOR")
        sign_consent(r["id"], d2["id"], "FOR")
        sign_consent(r["id"], d3["id"], "FOR")
        resp = api.finalize_consent(r["id"], SECRETARY)
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "CONSENT_ADOPTED"
        cd_after = get_success_data(api.get_conflict_disclosure(cd["id"], SECRETARY))
        assert cd_after["status"] == "CLEARED"


class TestConsentDeadline:
    def test_consent_sign_after_deadline_rejected(self, api):
        """PRD §3.7: "Signing after `consent_deadline_at` is refused with
        `ERR_CONSENT_DEADLINE_PASSED` (HTTP 422)."

        Design: Corner/validations/consent_sign_after_deadline_rejected
        """
        corp, _bylaws, directors = setup_corporation_with_directors(1, name="Corp V2")
        d1 = directors[0]
        r = setup_circulating_consent(corp["id"], title="R", text="t")
        # circulated at default clock 2026-05-01T00:00:00Z, deadline +10d = 2026-05-11T00:00:00Z
        set_clock("2026-05-11T00:00:01Z")
        from test_helpers import make_director_headers

        resp = api.create_vote_record(
            {"resolution_id": r["id"], "channel": "WRITTEN_CONSENT", "vote": "FOR"},
            make_director_headers(d1["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CONSENT_DEADLINE_PASSED)
        after = get_success_data(api.get_resolution(r["id"], SECRETARY))
        assert after["status"] == "CIRCULATING"


class TestCheckpointLapsesUnderSignedConsent:
    def test_checkpoint_lapses_under_signed_consent(self, api):
        """PRD §3.9 (checkpoint): "It evaluates every `CIRCULATING` written
        consent: any whose `FOR` signatures have reached the stored requirement
        is adopted, and any whose deadline has passed while still short of the
        requirement is lapsed."

        Design: Corner/cross_cutting_layers/checkpoint_lapses_under_signed_consent
        """
        corp, _bylaws, directors = setup_corporation_with_directors(3, name="Corp OPS2")
        d1 = directors[0]
        r = setup_circulating_consent(corp["id"], title="R", text="t")
        # unanimity required, 3 active directors -> required 3
        sign_consent(r["id"], d1["id"], "FOR")
        # move clock past deadline 2026-05-11T00:00:00Z
        set_clock("2026-05-12T00:00:00Z")
        resp = api.run_checkpoint(corp["id"], SECRETARY)
        data = validate_success(resp, expected_status=200)
        assert r["id"] in data.get("lapsed_resolution_ids", []), (
            f"expected {r['id']} in lapsed roster, got {data.get('lapsed_resolution_ids')}"
        )
        after = get_success_data(api.get_resolution(r["id"], SECRETARY))
        assert after["status"] == "CONSENT_LAPSED"
