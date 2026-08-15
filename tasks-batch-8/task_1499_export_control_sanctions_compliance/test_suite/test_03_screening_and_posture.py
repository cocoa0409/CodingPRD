"""Screening engine variants, scoring thresholds, party posture derivation, resolution (PRD §3.2, §3.3)."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_screening_result,
    create_classified_product,
    create_entry,
    create_order,
    create_party,
    get_party,
    resolve_screening_result,
    submit_order,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestClearResultShape:
    def test_screening_result_clear_shape_when_no_entries(self, api, ops_headers, manager_headers):
        """PRD §3.2: "When the best score reaches or exceeds its threshold, the screening produces a `POTENTIAL_MATCH` result recording `matched_entry_id`, the `score`, and the `threshold_used`; otherwise it produces a `CLEAR` result with `matched_entry_id` null, `score` 0.00, and `threshold_used` null."
        PRD §3.2: "Either role that can register a party may also run an on-demand screening against it, which creates a result with `trigger_context` `MANUAL` under the `FUZZY` variant and returns it as a newly created resource."
        PRD §3.3: "otherwise `CLEAR` when at least one result exists (whether `CLEAR` or `FALSE_POSITIVE`); otherwise `UNSCREENED` when the party has never been screened."

        Design: Corner/entities/screening_result_clear_shape_when_no_entries
        """
        party = create_party(legal_name="Solo Trader KK", country_code="JPN", city="Osaka")
        res = api.screen_party(party["id"], ops_headers)
        result = validate_success(res, 201)
        assert_screening_result(result)
        assert result["status"] == "CLEAR"
        assert result["score"] == pytest.approx(0.00, abs=1e-9)
        assert result["matched_entry_id"] is None
        assert result["threshold_used"] is None
        assert result["trigger_context"] == "MANUAL"
        assert result["algorithm_variant"] == "FUZZY"

        party_after = get_party(party["id"], headers=manager_headers)
        assert party_after["screening_posture"] == "CLEAR"
        assert party_after["last_screened_at"] is not None


class TestInactiveEntries:
    def test_inactive_entry_excluded_from_screening(self, api, ops_headers, director_headers,
                                                    manager_headers):
        """PRD §3.2: "Screening scores a party against the candidate set of all `ACTIVE` list entries."

        Design: Corner/state_machines/inactive_entry_excluded_from_screening
        """
        entry = create_entry(list_source="DENIED_PERSONS", match_name="Dormant Trading Co",
                             country_code="DEU", severity="RESTRICTED")
        deactivated = validate_success(
            api.set_screening_list_entry_status(entry["id"], {"to": "INACTIVE"}, director_headers),
            200,
        )
        assert deactivated["status"] == "INACTIVE"

        party = create_party(legal_name="Dormant Trading Co", country_code="DEU", city="Koln")
        result = validate_success(api.screen_party(party["id"], ops_headers), 201)
        assert result["status"] == "CLEAR", (
            f"INACTIVE entry must be excluded from the candidate set, got {result['status']}"
        )
        party_after = get_party(party["id"], headers=manager_headers)
        assert party_after["screening_posture"] == "CLEAR"


class TestResolveGuards:
    def test_resolve_clear_result_rejected(self, api, ops_headers, manager_headers):
        """PRD §3.3: "Resolution from any state other than `POTENTIAL_MATCH` is `ERR_INVALID_STATE`."

        Design: Corner/state_machines/resolve_clear_result_rejected
        """
        party = create_party(legal_name="Plain Sailing Ltd", country_code="IRL", city="Dublin")
        result = validate_success(api.screen_party(party["id"], ops_headers), 201)
        assert result["status"] == "CLEAR"

        res = api.resolve_screening_result(result["id"], {"resolution": "FALSE_POSITIVE"},
                                           manager_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)

        after = validate_success(api.get_screening_result(result["id"], manager_headers), 200)
        assert after["status"] == "CLEAR", f"CLEAR result never transitions, got {after['status']}"


class TestPostureRecomputation:
    def test_posture_recomputed_on_false_positive_resolution(self, api, ops_headers,
                                                             manager_headers):
        """PRD §3.3: "A party's `screening_posture` is a pure function of its entire history of screening results, regardless of age: `BLOCKED` when any result stands at `CONFIRMED_MATCH`; otherwise `REVIEW_REQUIRED` when any result stands at `POTENTIAL_MATCH`; otherwise `CLEAR` when at least one result exists (whether `CLEAR` or `FALSE_POSITIVE`); otherwise `UNSCREENED` when the party has never been screened."
        PRD §3.3: "A `FALSE_POSITIVE` simply relaxes the posture if no other open matches remain."

        Design: Corner/calculations/posture_recomputed_on_false_positive_resolution
        """
        create_entry(list_source="ENTITY_LIST", match_name="Summit Exports",
                     country_code="CHE", severity="RESTRICTED")
        party = create_party(legal_name="Summit Exports", country_code="CHE", city="Geneva")
        result = validate_success(api.screen_party(party["id"], ops_headers), 201)
        assert result["status"] == "POTENTIAL_MATCH", (
            f"exact-name FUZZY match (score 1.00 >= 0.70) expected, got {result['status']}"
        )
        assert get_party(party["id"], headers=manager_headers)["screening_posture"] == "REVIEW_REQUIRED"

        resolved = resolve_screening_result(result["id"], "FALSE_POSITIVE",
                                            headers=manager_headers)
        assert resolved["status"] == "FALSE_POSITIVE"
        assert resolved["resolved_by_user_id"] == "manager-1"

        party_after = get_party(party["id"], headers=manager_headers)
        assert party_after["screening_posture"] == "CLEAR", (
            f"posture must relax to CLEAR once the only open match is resolved, "
            f"got {party_after['screening_posture']}"
        )


class TestExactVsFuzzyVariants:
    def _setup_exact_then_fuzzy(self, api, ops_headers):
        """Entry 'Global Trade Corp' (DEU, RESTRICTED); party 'Global Trade Corporation' (DEU);
        order submitted (ORDER/EXACT screening), then a manual (FUZZY) screen."""
        entry = create_entry(list_source="DENIED_PERSONS", match_name="Global Trade Corp",
                             country_code="DEU", severity="RESTRICTED")
        product, _ = create_classified_product(sku="P-200", name="Resistor",
                                               controlled_content_pct=0, unit_value_cents=500,
                                               classification_code="EAR99")
        party = create_party(legal_name="Global Trade Corporation", country_code="DEU",
                             city="Hamburg")
        order = create_order(product["id"], party["id"], destination_country="DEU",
                             end_use="CIVILIAN", quantity=1)
        submit_order(order["id"])  # runs the ORDER-context EXACT screening
        fuzzy = validate_success(api.screen_party(party["id"], ops_headers), 201)
        return entry, party, fuzzy

    def test_fuzzy_variant_near_match_scores_at_threshold(self, api, ops_headers, manager_headers):
        """PRD §3.2: "Under `FUZZY`, both strings are tokenized into lowercase alphanumeric token sequences (splitting on every non-alphanumeric character and dropping empty tokens); the name signal is the number of tokens common to both sets divided by the number of tokens in their union, rounded to 2 decimal places round half up, with 0.00 when the union is empty, and an exact normalized equality still yields 1.00."
        PRD §3.2: "Otherwise the score is the weighted sum — 0.60 times the name signal, plus 0.25 times the country signal, plus 0.15 times the city signal — rounded to 2 decimal places round half up. Each candidate is compared against its own `threshold_used`: 0.85 for `PROHIBITED` entries and 0.70 otherwise."

        Design: Difficulty/dual_variant_calc/screening_exact_vs_fuzzy_same_party_entry
        """
        entry, party, fuzzy = self._setup_exact_then_fuzzy(api, ops_headers)
        # FUZZY: |{global,trade,corporation} ∩ {global,trade,corp}| / |union| = 2/4 = 0.50
        # score = 0.60*0.50 + 0.25*1.00 + 0.15*1.00 = 0.70; 0.70 >= 0.70 -> POTENTIAL_MATCH
        assert fuzzy["algorithm_variant"] == "FUZZY"
        assert fuzzy["score"] == pytest.approx(0.70, abs=1e-9), (
            f"expected FUZZY score 0.70, got {fuzzy['score']}"
        )
        assert fuzzy["threshold_used"] == pytest.approx(0.70, abs=1e-9)
        assert fuzzy["status"] == "POTENTIAL_MATCH"
        assert fuzzy["matched_entry_id"] == entry["id"]
        assert fuzzy["trigger_context"] == "MANUAL"

    def test_exact_variant_near_match_clears(self, api, ops_headers, manager_headers):
        """PRD §3.2: "Under `EXACT`, the name signal is 1.00 when the normalized party `legal_name` exactly equals the normalized `match_name`, and 0.00 otherwise — near-miss names earn nothing."
        PRD §3.2: "order-submission screening runs the `EXACT` variant, while shipment, manual, and list-change screening run the `FUZZY` variant."
        PRD §3.3: "otherwise `REVIEW_REQUIRED` when any result stands at `POTENTIAL_MATCH`"

        Design: Difficulty/dual_variant_calc/screening_exact_vs_fuzzy_same_party_entry
        """
        _, party, _ = self._setup_exact_then_fuzzy(api, ops_headers)
        rows, meta = validate_paginated(
            api.list_screening_results(manager_headers,
                                       params={"party_id": party["id"],
                                               "trigger_context": "ORDER"})
        )
        assert meta["total_count"] == 1, f"one ORDER-context result expected, got {meta['total_count']}"
        exact = rows[0]
        # EXACT: near-miss name earns 0.00 -> score 0.25+0.15 = 0.40 < 0.70 -> CLEAR
        assert exact["algorithm_variant"] == "EXACT"
        assert exact["status"] == "CLEAR", (
            f"EXACT near-miss must clear, got {exact['status']}"
        )
        # The later FUZZY POTENTIAL_MATCH drives the derived posture.
        assert get_party(party["id"], headers=manager_headers)["screening_posture"] == "REVIEW_REQUIRED"


class TestSeverityThresholdBranches:
    def _setup_atlas_parties(self):
        """E1 DENIED_PERSONS RESTRICTED (DEU), E2 SDN PROHIBITED (SYR), both
        'Atlas Industrial Group'; Party A 'Atlas Industrial' (DEU), Party B (FRA)."""
        e1 = create_entry(list_source="DENIED_PERSONS", match_name="Atlas Industrial Group",
                          country_code="DEU", severity="RESTRICTED")
        create_entry(list_source="SDN", match_name="Atlas Industrial Group",
                     country_code="SYR", severity="PROHIBITED")
        party_a = create_party(legal_name="Atlas Industrial", country_code="DEU", city="Berlin")
        party_b = create_party(legal_name="Atlas Industrial", country_code="FRA", city="Lyon")
        return e1, party_a, party_b

    def test_score_080_hits_restricted_threshold(self, api, ops_headers):
        """PRD §3.2: "Otherwise the score is the weighted sum — 0.60 times the name signal, plus 0.25 times the country signal, plus 0.15 times the city signal — rounded to 2 decimal places round half up. Each candidate is compared against its own `threshold_used`: 0.85 for `PROHIBITED` entries and 0.70 otherwise."
        PRD §3.2: "When the best score reaches or exceeds its threshold, the screening produces a `POTENTIAL_MATCH` result recording `matched_entry_id`, the `score`, and the `threshold_used`; otherwise it produces a `CLEAR` result with `matched_entry_id` null, `score` 0.00, and `threshold_used` null."

        Design: Difficulty/combinatorial_formula/screening_score_severity_threshold_branch
        """
        e1, party_a, _ = self._setup_atlas_parties()
        # FUZZY name signal = |{atlas,industrial} ∩ {atlas,industrial,group}| / 3 = 0.67
        # score = 0.60*0.67 + 0.25 + 0.15 = 0.802 -> 0.80 >= 0.70 -> POTENTIAL_MATCH
        result = validate_success(api.screen_party(party_a["id"], ops_headers), 201)
        assert result["status"] == "POTENTIAL_MATCH"
        assert result["matched_entry_id"] == e1["id"]
        assert result["score"] == pytest.approx(0.80, abs=1e-9), (
            f"expected score 0.80, got {result['score']}"
        )
        assert result["threshold_used"] == pytest.approx(0.70, abs=1e-9)

    def test_prohibited_hard_gate_zeroes_country_mismatch(self, api, ops_headers):
        """PRD §3.2: "A hard gate then applies: if the entry's severity is `PROHIBITED` and the country signal is below 1.00, the match score for that pair is 0.00 outright."

        Design: Difficulty/combinatorial_formula/screening_score_severity_threshold_branch
        """
        _, _, party_b = self._setup_atlas_parties()
        # Party B (FRA): PROHIBITED entry hard-gated to 0.00 (country mismatch);
        # RESTRICTED entry scores 0.60*0.67 = 0.40 < 0.70 -> overall CLEAR.
        result = validate_success(api.screen_party(party_b["id"], ops_headers), 201)
        assert result["status"] == "CLEAR", (
            f"PROHIBITED hard gate plus sub-threshold RESTRICTED score must clear, "
            f"got {result['status']}"
        )
        assert result["score"] == pytest.approx(0.00, abs=1e-9)
        assert result["matched_entry_id"] is None
        assert result["threshold_used"] is None
