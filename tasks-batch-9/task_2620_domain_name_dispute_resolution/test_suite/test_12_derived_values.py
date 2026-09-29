"""Values the server computes for itself: rankings, filters and decayed weights."""
from test_helpers import (
    ApiErrorId,
    CASE_MANAGER,
    PROVIDER_ADMIN,
    admit_panelist,
    api_client,
    appointment_payload,
    case_version,
    cast_seat_vote,
    draft_decision,
    file_complaint,
    fund_case_to_assessment,
    get_success_data,
    ground_payload,
    issue_decision,
    make_complainant_headers,
    nominate_seat,
    precedent_entry_of,
    publish_decision,
    read_appointment,
    read_case,
    read_panelist,
    register_domain,
    screen_seat,
    seat_panelist_cleanly,
    set_availability,
    set_clock,
    setup_responded_case,
    validate_error,
    validate_paginated,
)


class TestProviderSelectorRanking:
    def test_three_provider_picks_walk_the_load_the_roster_date_and_the_created_at_key(self):
        """PRD §3.6: "When `panelist_id` is omitted the provider selects one itself, and
        the resulting row records `selected_by_provider` as true; when the caller names
        one, that flag is false, but the named candidate is still put through the identical
        eligibility filter."
        PRD §3.6: "Otherwise the set is ordered by three keys in strict sequence:
        ascending `active_case_load` first, so the least-burdened neutral is preferred;
        ascending `roster_admitted_at` second, so seniority on the roster breaks a load
        tie; and ascending `created_at` third as the final tiebreak."
        PRD §3.6: "The record identifier is never a ranking key, so identifier order must
        not be relied on to break any tie."
        PRD §3.6: "And the candidate must not already hold a row on this same case in
        `NOMINATED`, `WAIVER_PENDING` or `ACCEPTED` — a neutral cannot occupy two seats on
        one panel, though a neutral whose earlier row on the case ended in `DECLINED`,
        `CONFLICTED` or `REPLACED` may be nominated afresh."

        Design: Corner/calculations/selector_ranking_is_deterministic_down_to_the_created_at_fallback
        """
        set_clock("2026-08-01T00:00:00Z")
        first_admitted = admit_panelist(
            full_name="Bram de Vries", nationality_code="NL",
            roster_admitted_at="2024-01-15T00:00:00Z", max_overlapping_engagements=3,
        )
        set_clock("2026-08-01T00:10:00Z")
        most_senior = admit_panelist(
            full_name="Elena Ruiz", nationality_code="ES",
            roster_admitted_at="2023-03-01T00:00:00Z", max_overlapping_engagements=3,
        )
        set_clock("2026-08-01T00:20:00Z")
        last_admitted = admit_panelist(
            full_name="Marta Kowalska", nationality_code="PL",
            roster_admitted_at="2024-01-15T00:00:00Z", max_overlapping_engagements=3,
        )
        assert first_admitted["created_at"] == "2026-08-01T00:00:00.000Z"
        assert most_senior["created_at"] == "2026-08-01T00:10:00.000Z"
        assert last_admitted["created_at"] == "2026-08-01T00:20:00.000Z"
        assert first_admitted["roster_admitted_at"] == last_admitted["roster_admitted_at"], (
            "the two junior neutrals tie on the second ranking key"
        )

        bundle = setup_responded_case(
            requests_three_member_panel=True, iana_id="IANA-9022",
            domain_name="select.example", country_code="GB", legal_name="Select Ltd",
            registrar_name="Select Registrar",
        )
        case_id = bundle["case"]["id"]
        funded = fund_case_to_assessment(case_id)
        assert funded["required_seat_count"] == 3
        assert funded["assessed_fee_cents"] == 400000
        assert funded["paid_cents"] == 400000

        picks = []
        for seat in ("PRESIDING", "CO_PANELIST_1", "CO_PANELIST_2"):
            appointment = nominate_seat(case_id, seat)
            assert appointment["selected_by_provider"] is True
            assert appointment["seat"] == seat
            accepted = screen_seat(appointment["id"], appointment["panelist_id"])
            assert accepted["status"] == "ACCEPTED"
            picks.append(appointment["panelist_id"])

        assert picks[0] == most_senior["id"], (
            "with every load at zero the earliest roster date takes the first seat"
        )
        assert picks[1] == first_admitted["id"], (
            "the roster tie is broken by the earlier created_at, not by the identifier"
        )
        assert picks[2] == last_admitted["id"]
        assert len(set(picks)) == 3

        assert read_case(case_id)["status"] == "PANEL_CONSTITUTED"
        assert [
            read_panelist(panelist_id)["active_case_load"] for panelist_id in picks
        ] == [1, 1, 1]


class TestEligibilityFilterReportsTwoWays:
    def _responded_case_over_a_two_name_roster(self):
        available = admit_panelist(
            full_name="Oliver Grant", nationality_code="GB",
            roster_admitted_at="2022-01-01T00:00:00Z", max_overlapping_engagements=3,
        )
        suspended = admit_panelist(
            full_name="Anna Bauer", nationality_code="DE",
            roster_admitted_at="2019-04-01T00:00:00Z", firm_name="Bauer Legal",
            max_overlapping_engagements=3,
        )
        assert available["status"] == "AVAILABLE"
        assert suspended["status"] == "AVAILABLE"
        assert set_availability(suspended["id"], status="SUSPENDED")["status"] == "SUSPENDED"
        bundle = setup_responded_case(
            iana_id="IANA-9023", domain_name="elig.example", country_code="GB",
            legal_name="Elig Ltd", registrar_name="Elig Registrar",
        )
        return bundle, available, suspended

    def test_naming_an_ineligible_neutral_and_emptying_the_roster_fail_with_different_codes(self):
        """PRD §3.6: "The candidate's `nationality_code` must differ from the
        complainant's `country_code`."
        PRD §3.1: "Only a panelist in `AVAILABLE` ever enters the provider's candidate
        set; `UNAVAILABLE` and `SUSPENDED` neutrals are filtered out before any ranking
        happens."
        PRD §3.6: "The non-temporal conditions — roster status, either nationality
        exclusion, and the same-case duplication bar — are refused with
        `ERR_PANELIST_INELIGIBLE`."
        PRD §3.6: "If that set is empty the nomination is refused with
        `ERR_NO_ELIGIBLE_PANELIST`, reported as an unprocessable request."

        Design: Corner/calculations/named_ineligible_panelist_and_an_empty_eligible_set_fail_differently
        """
        bundle, available, suspended = self._responded_case_over_a_two_name_roster()
        case_id = bundle["case"]["id"]
        assert bundle["case"]["status"] == "RESPONSE_RECEIVED"
        assert bundle["case"]["paid_cents"] == 150000
        assert bundle["complainant"]["country_code"] == "GB"
        pinned_version = case_version(case_id)

        by_nationality = appointment_payload("SOLE", pinned_version)
        by_nationality["panelist_id"] = available["id"]
        refused_nationality = api_client.create_appointment(case_id, by_nationality, CASE_MANAGER)
        validate_error(refused_nationality, ApiErrorId.ERR_PANELIST_INELIGIBLE.value, 409)

        by_status = appointment_payload("SOLE", pinned_version)
        by_status["panelist_id"] = suspended["id"]
        refused_status = api_client.create_appointment(case_id, by_status, CASE_MANAGER)
        validate_error(refused_status, ApiErrorId.ERR_PANELIST_INELIGIBLE.value, 409)

        empty_set = api_client.create_appointment(
            case_id, appointment_payload("SOLE", pinned_version), CASE_MANAGER
        )
        validate_error(empty_set, ApiErrorId.ERR_NO_ELIGIBLE_PANELIST.value, 422)

        _, meta = validate_paginated(
            api_client.list_appointments(
                CASE_MANAGER, params={"case_id": case_id, "limit": 10, "offset": 0}
            )
        )
        assert meta["total_count"] == 0
        assert case_version(case_id) == pinned_version, (
            "three refusals left the pinned version untouched"
        )
        assert read_case(case_id)["status"] == "RESPONSE_RECEIVED"

        assert set_availability(suspended["id"], status="AVAILABLE")["status"] == "AVAILABLE"
        seated = get_success_data(
            api_client.create_appointment(
                case_id, appointment_payload("SOLE", pinned_version), CASE_MANAGER
            ),
            201,
        )
        assert seated["panelist_id"] == suspended["id"]
        assert seated["selected_by_provider"] is True
        assert seated["status"] == "NOMINATED"
        assert read_case(case_id)["status"] == "PANEL_APPOINTMENT"
        _, after_meta = validate_paginated(
            api_client.list_appointments(
                CASE_MANAGER, params={"case_id": case_id, "limit": 10, "offset": 0}
            )
        )
        assert after_meta["total_count"] == 1


class TestPrecedentWeightDecay:
    def _issued_but_unpublished_transfer(self):
        set_clock("2026-08-01T00:00:00Z")
        bundle = setup_responded_case(
            iana_id="IANA-9024", domain_name="prec.example", country_code="GB",
            legal_name="Prec Ltd", registrar_name="Prec Registrar",
        )
        case_id = bundle["case"]["id"]
        panelist = admit_panelist(
            full_name="Anna Bauer", nationality_code="DE",
            roster_admitted_at="2019-04-01T00:00:00Z", firm_name="Bauer Legal",
        )
        bundle["appointments"] = [seat_panelist_cleanly(case_id, "SOLE", panelist)]
        decision = draft_decision(
            case_id, panelist["id"],
            draft_summary=(
                "The name is identical to the mark and was registered to sell it back; "
                "transfer is ordered."
            ),
        )
        cast_seat_vote(
            decision["id"], panelist["id"], "SOLE", "TRANSFER",
            rationale="All three elements made out.",
        )
        set_clock("2026-08-10T09:00:00Z")
        bundle["panelists"] = [panelist]
        bundle["decision"] = issue_decision(decision["id"])
        bundle["case"] = read_case(case_id)
        return bundle

    def test_two_grounds_of_one_case_count_twice_and_the_weight_decays_onto_its_floor(self):
        """PRD §3.2: "A citation of a decision that is still unpublished, or one that was
        published under a full redaction, is refused with
        `ERR_CITED_PRECEDENT_NOT_PUBLISHED`."
        PRD §3.9: "Exactly one precedent entry exists per decision, created with
        `published_at` stamped from the clock, the supplied `redaction_level` and
        `precedent_tags`, `superseded` false, and `citable` true unless the redaction level
        was `FULL`."
        PRD §3.9: "An entry's `citation_count` is the number of asserted ground rows
        anywhere in the system whose `cited_decision_ids` contains this decision — the
        count is over grounds, not over cases, so a single case that cites the same
        decision from two of its three mandatory elements contributes two, and citations
        from cases that were later withdrawn or administratively closed still count."
        PRD §3.9: "`precedent_weight` then decays that count by age: the whole months
        elapsed from the decision's `issued_at` to the current logical clock are truncated
        toward zero, the age weight is one minus those months divided by the 60-month
        horizon with a floor of 0.20, and `precedent_weight` is the citation count
        multiplied by that age weight, rounded half up to two decimals."
        PRD §3.9: "Both figures are re-evaluated on every read of the entry and on every
        precedent search, against the clock as it reads at that moment — advancing the
        clock alone changes the reported weight with no write anywhere."

        Design: Corner/calculations/precedent_weight_decays_by_whole_months_and_lands_on_the_floor
        """
        bundle = self._issued_but_unpublished_transfer()
        cited_id = bundle["decision"]["id"]
        assert bundle["decision"]["issued_at"] == "2026-08-10T09:00:00.000Z"
        assert bundle["decision"]["publication_status"] == "UNPUBLISHED"

        complainant = bundle["complainant"]
        headers = make_complainant_headers(complainant["id"])
        second_domain = register_domain(bundle["registrar"]["id"], "precb.example")
        later_case = file_complaint(complainant, second_domain)

        citing_payload = ground_payload(
            "TRADEMARK_RIGHTS", evidence_count=2,
            assertion_text=(
                "PRECB is confusingly similar to the same mark, as held in the cited case."
            ),
            similarity_claim="CONFUSINGLY_SIMILAR", cited_decision_ids=[cited_id],
        )
        too_early = api_client.create_ground(later_case["id"], citing_payload, headers)
        validate_error(too_early, ApiErrorId.ERR_CITED_PRECEDENT_NOT_PUBLISHED.value, 422)
        _, empty_meta = validate_paginated(
            api_client.list_grounds(later_case["id"], CASE_MANAGER, params={"limit": 10, "offset": 0})
        )
        assert empty_meta["total_count"] == 0, "the refused citation wrote no ground row"

        entry = publish_decision(
            cited_id, "NONE",
            precedent_tags=["identical_mark", "offer_for_sale"],
            digest_text="Transfer ordered where the name was registered to resell it.",
        )
        assert entry["citable"] is True
        assert entry["superseded"] is False
        assert entry["citation_count"] == 0
        assert float(entry["precedent_weight"]) == 0.00
        assert entry["published_at"] == "2026-08-10T09:00:00.000Z"
        assert entry["redaction_level"] == "NONE"
        assert entry["precedent_tags"] == ["identical_mark", "offer_for_sale"]

        first_citation = get_success_data(
            api_client.create_ground(later_case["id"], citing_payload, headers), 201
        )
        assert first_citation["cited_decision_ids"] == [cited_id]
        second_citation = get_success_data(
            api_client.create_ground(
                later_case["id"],
                ground_payload(
                    "BAD_FAITH", evidence_count=1,
                    assertion_text=(
                        "The same resale pattern found in the cited case is present here."
                    ),
                    cited_decision_ids=[cited_id],
                ),
                headers,
            ),
            201,
        )
        assert second_citation["cited_decision_ids"] == [cited_id]

        at_issue = precedent_entry_of(cited_id)
        assert at_issue["citation_count"] == 2, "two grounds of one case count twice"
        assert float(at_issue["precedent_weight"]) == 2.00
        rows, meta = validate_paginated(
            api_client.search_precedents(
                CASE_MANAGER, params={"citable": True, "limit": 10, "offset": 0}
            )
        )
        assert meta["total_count"] == 1
        assert float(rows[0]["precedent_weight"]) == 2.00

        set_clock("2027-02-10T09:00:00Z")
        after_six_months = precedent_entry_of(cited_id)
        assert after_six_months["citation_count"] == 2
        assert float(after_six_months["precedent_weight"]) == 1.80

        set_clock("2031-08-10T09:00:00Z")
        on_the_floor = precedent_entry_of(cited_id)
        assert on_the_floor["citation_count"] == 2
        assert float(on_the_floor["precedent_weight"]) == 0.40, (
            "sixty whole months would decay to zero linearly, so the floor applies"
        )
        assert on_the_floor["citable"] is True
        assert on_the_floor["superseded"] is False
        assert on_the_floor["published_at"] == "2026-08-10T09:00:00.000Z"
