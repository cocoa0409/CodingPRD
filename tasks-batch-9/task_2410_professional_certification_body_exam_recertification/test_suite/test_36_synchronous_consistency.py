"""Every write is readable and every derived counter has already moved when the response
returns — no queue, no lazy counter, no 202."""

import pytest

from test_helpers import assertions as ax
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import validate_success
from test_helpers.test_users import PANELIST_IDS, make_panelist_headers

PANELIST_1 = make_panelist_headers(PANELIST_IDS[0])

POOLED_PRETEST_BATCH = {
    "is_pretest": True,
    "response_count": 40,
    "correct_count": 24,
    "upper_n": 10,
    "upper_correct": 9,
    "lower_n": 10,
    "lower_correct": 3,
}


def _a_deficient_programme_with_one_approved_item(api):
    program = fx.active_program(api)
    assert program["operational_item_count"] == 0
    assert program["deficient_domain_codes"] == ["D1"]
    assert program["blueprint_posture"] == "DEFICIENT"
    item = fx.approved_item(api, program["id"])
    assert item["p_value"] is None
    assert item["pretest_response_count"] == 0
    return program, item


class TestTheWriteResponseAlreadyCarriesTheCascade:
    """One ingest, and the answer is complete before any read happens."""

    def test_the_batch_response_itself_reports_the_statistics_and_the_promotion(self, api):
        """The 200 that acknowledges the ingest already holds the recomputed statistics, the
        basis actually used, the empty flag verdict and the promoted status; the immediate
        re-read returns the very same row, version included.

        PRD §2.9: "Where §3 describes a cascade, the cascade is part of the operation's
        contract and not an eventual background reconciliation: by the time the response is
        emitted, every record the cascade names has already been updated, its `updated_at`
        refreshed and its `version` incremented. Consistency is immediate."

        PRD §2.10: "Operations that modify an existing resource — every action sub-path, the
        logical-clock capability, and the maintenance run — answer with **HTTP 200**."

        Design: Corner/consistency_model/every_write_is_readable_and_every_derived_counter_moves_before_the_response_returns
        """
        _program, item = _a_deficient_programme_with_one_approved_item(api)

        ingested = validate_success(api.ingest_response_batch(
            item["id"], POOLED_PRETEST_BATCH, fx.PSYCHOMETRICIAN), 200)

        assert float(ingested["p_value"]) == pytest.approx(0.6000, abs=0.00001)
        assert float(ingested["discrimination_index"]) == pytest.approx(0.6000, abs=0.00001)
        assert ingested["stat_basis_applied"] == "POOLED"
        assert ingested["flag_reason"] is None
        assert ingested["status"] == "OPERATIONAL"

        read_back = fx.read_item(api, item["id"])
        assert read_back["p_value"] == ingested["p_value"]
        assert read_back["discrimination_index"] == ingested["discrimination_index"]
        assert read_back["status"] == "OPERATIONAL"
        assert read_back["version"] == ingested["version"]
        assert read_back["updated_at"] == ingested["updated_at"]
        ax.assert_item(read_back)

    def test_the_owning_programme_is_already_complete_on_the_very_next_request(self, api):
        """The cascade into a different entity has landed before the ingest answered, so the
        immediately following programme read shows the counter at one with no deficient
        domains, and the promoted item is already admissible in a form built by the request
        after that.

        PRD §2.9: "A program's `operational_item_count`, `deficient_domain_codes`, and
        `blueprint_posture` are recomputed from the current population of that program's items
        whenever an item crosses the `OPERATIONAL` boundary in either direction."

        PRD §3.5: "A new form has `status` `ASSEMBLED`, `panel_status` `OPEN`, an empty
        `panel_ratings` list, a `scored_item_count` equal to the number of entries in
        `item_ids` less the number of entries in `pretest_item_ids`, and a `retired_item_count`
        computed from the current status of the cited items."

        Design: Corner/consistency_model/every_write_is_readable_and_every_derived_counter_moves_before_the_response_returns
        """
        program, item = _a_deficient_programme_with_one_approved_item(api)
        validate_success(api.ingest_response_batch(
            item["id"], POOLED_PRETEST_BATCH, fx.PSYCHOMETRICIAN), 200)

        cascaded = validate_success(api.get_program(program["id"], fx.PROGRAM_ADMIN), 200)
        assert cascaded["operational_item_count"] == 1
        assert cascaded["deficient_domain_codes"] == []
        assert cascaded["blueprint_posture"] == "COMPLETE"
        ax.assert_blueprint_posture_agrees_with_counts(cascaded)

        form = validate_success(api.create_form(
            f.create_form_payload(program["id"], [item["id"]]), fx.PSYCHOMETRICIAN), 201)
        assert form["status"] == "ASSEMBLED"
        assert form["scored_item_count"] == 1
        assert form["retired_item_count"] == 0

    def test_the_version_a_write_echoes_is_immediately_valid_as_the_next_write_s_token(
            self, api):
        """The rating's own response carries the form version, and handing that number
        straight to the adoption succeeds — no stale-version refusal, so the echoed token was
        already current.

        PRD §2.5: "Adopting a cut score — `POST /forms/{id}/adopt-cut-score` — requires
        `expected_form_version` carrying the client's last observed `version` of the
        `ExamForm`. If the form's current `version` differs, the adoption is rejected with
        `ERR_STALE_VERSION` (HTTP 412)."

        PRD §3.5: "Adoption moves the form `ASSEMBLED → CUT_SCORE_SET`, or leaves it in
        `CUT_SCORE_SET` when it is a re-adoption after further ratings, sets `panel_status` to
        `ADOPTED`, and increments the form's `version` by 1."

        Design: Corner/consistency_model/every_write_is_readable_and_every_derived_counter_moves_before_the_response_returns
        """
        program, item = _a_deficient_programme_with_one_approved_item(api)
        validate_success(api.ingest_response_batch(
            item["id"], POOLED_PRETEST_BATCH, fx.PSYCHOMETRICIAN), 200)
        form = validate_success(api.create_form(
            f.create_form_payload(program["id"], [item["id"]]), fx.PSYCHOMETRICIAN), 201)

        rated = validate_success(api.submit_panel_rating(
            form["id"], f.panel_rating_payload(PANELIST_IDS[0], 0.60), PANELIST_1), 200)
        assert rated["panel_status"] == "RATINGS_COMPLETE"
        echoed_version = rated["version"]

        adopted = validate_success(api.adopt_cut_score(
            form["id"], f.adopt_cut_score_payload(echoed_version),
            fx.PSYCHOMETRICIAN), 200)

        assert adopted["status"] == "CUT_SCORE_SET"
        assert adopted["panel_status"] == "ADOPTED"
        assert adopted["version"] == echoed_version + 1
        assert float(adopted["mean_expected_pass_rate"]) == pytest.approx(0.600000,
                                                                         abs=0.000001)
