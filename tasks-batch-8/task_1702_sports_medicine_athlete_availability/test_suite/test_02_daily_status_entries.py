"""Daily status log: supersede semantics and the is_current invariant."""
from test_helpers import (
    ApiErrorId,
    get_success_data,
    record_status_entry,
    set_clock,
    setup_open_case,
    setup_rehab_case,
    get_athlete,
    validate_error,
    validate_paginated,
    validate_success,
)


def _current_entries(api, case_id, entry_date, headers):
    resp = api.list_daily_status_entries(headers)
    entries, _meta = validate_paginated(resp)
    return [
        e
        for e in entries
        if e["injury_case_id"] == case_id
        and str(e["entry_date"]).startswith(entry_date)
        and e["is_current"] is True
    ]


class TestSupersedeSameDate:
    def test_supersede_replaces_incumbent_current_entry(self, api, medical_staff_headers):
        """PRD §3.2: "When a superseding entry is created, the new entry's
        `is_current` becomes `true` and the old entry's `is_current` becomes
        `false`. Only `is_current` entries feed derivations."

        Design: Difficulty/resource_temporal_overlap/daily_status_entry_supersede_same_date_single_current
        """
        sc = setup_open_case(clock="2026-08-03T00:00:00Z", occurred_on="2026-08-02")
        case_id = sc["case"]["id"]
        e1 = record_status_entry(sc["case"]["id"], "2026-08-03", designation="OUT",
                                 symptom_free=False, functional_test_score=40)
        assert e1["is_current"] is True

        resp = api.create_daily_status_entry(
            {
                "injury_case_id": case_id,
                "entry_date": "2026-08-03",
                "designation": "LIMITED",
                "symptom_free": True,
                "functional_test_score": 70,
                "supersedes_entry_id": e1["id"],
            },
            medical_staff_headers,
        )
        e2 = validate_success(resp, expected_status=201)
        assert e2["is_current"] is True, "superseding entry must become current"

        old = get_success_data(api.get_daily_status_entry(e1["id"], medical_staff_headers))
        assert old["is_current"] is False, "superseded incumbent must flip to not current"

        currents = _current_entries(api, case_id, "2026-08-03", medical_staff_headers)
        assert len(currents) == 1 and currents[0]["id"] == e2["id"], (
            "exactly one is_current entry must exist per (injury_case_id, entry_date)"
        )

    def test_supersede_target_that_is_not_current_rejected(self, api, medical_staff_headers):
        """PRD §3.2: "the supersede target must be an `is_current` entry for
        the same `(injury_case_id, entry_date)`, otherwise the request is
        rejected with `ERR_INVALID_SUPERSEDE_TARGET`."

        Design: Difficulty/resource_temporal_overlap/daily_status_entry_supersede_same_date_single_current
        """
        sc = setup_open_case(clock="2026-08-03T00:00:00Z", occurred_on="2026-08-02")
        case_id = sc["case"]["id"]
        e1 = record_status_entry(case_id, "2026-08-03", designation="OUT")
        e2 = record_status_entry(
            case_id, "2026-08-03", designation="LIMITED", symptom_free=True,
            functional_test_score=60, supersedes_entry_id=e1["id"],
        )
        # e1 is no longer is_current; a second correction pointing at it fails.
        resp = api.create_daily_status_entry(
            {
                "injury_case_id": case_id,
                "entry_date": "2026-08-03",
                "designation": "MODIFIED",
                "symptom_free": True,
                "functional_test_score": 75,
                "supersedes_entry_id": e1["id"],
            },
            medical_staff_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_SUPERSEDE_TARGET)
        currents = _current_entries(api, case_id, "2026-08-03", medical_staff_headers)
        assert [c["id"] for c in currents] == [e2["id"]], (
            "rejected supersede must not disturb the incumbent current entry"
        )


class TestSupersedeCurrentCountInvariant:
    def test_supersede_chain_preserves_single_current_entry(self, api, medical_staff_headers):
        """PRD §3.2: "When a superseding entry is created, the new entry's
        `is_current` becomes `true` and the old entry's `is_current` becomes
        `false`. Only `is_current` entries feed derivations."

        Design: Difficulty/compensating_invariant/daily_status_supersede_current_count_invariant
        """
        sc = setup_open_case(clock="2026-08-03T00:00:00Z", occurred_on="2026-08-02",
                             sport="BASKETBALL", position="G", surface="COURT",
                             mechanism="NON_CONTACT", season=("2026-08-01", "2027-04-01"))
        case_id = sc["case"]["id"]
        e1 = record_status_entry(case_id, "2026-08-03", designation="OUT",
                                 functional_test_score=40)
        e2 = record_status_entry(case_id, "2026-08-03", designation="LIMITED",
                                 symptom_free=True, functional_test_score=60,
                                 supersedes_entry_id=e1["id"])
        e3 = record_status_entry(case_id, "2026-08-03", designation="MODIFIED",
                                 symptom_free=True, functional_test_score=75,
                                 supersedes_entry_id=e2["id"])

        for old in (e1, e2):
            data = get_success_data(api.get_daily_status_entry(old["id"], medical_staff_headers))
            assert data["is_current"] is False, (
                f"entry {old['id']} must be superseded (is_current false)"
            )
        assert e3["is_current"] is True

        currents = _current_entries(api, case_id, "2026-08-03", medical_staff_headers)
        assert len(currents) == 1 and currents[0]["id"] == e3["id"], (
            "two create+supersede pairs must conserve the singleton is_current invariant"
        )

    def test_supersede_does_not_disturb_other_dates(self, api, medical_staff_headers):
        """PRD §3.2: "An entry may reference a prior entry via
        `supersedes_entry_id` to correct the record for the same case and
        date; the supersede target must be an `is_current` entry for the same
        `(injury_case_id, entry_date)`, otherwise the request is rejected with
        `ERR_INVALID_SUPERSEDE_TARGET`."

        Design: Difficulty/compensating_invariant/daily_status_supersede_current_count_invariant
        """
        sc = setup_open_case(clock="2026-08-03T00:00:00Z", occurred_on="2026-08-02")
        case_id = sc["case"]["id"]
        e_day1 = record_status_entry(case_id, "2026-08-03", designation="OUT")
        set_clock("2026-08-04T00:00:00Z")
        e_day2 = record_status_entry(case_id, "2026-08-04", designation="LIMITED",
                                     symptom_free=True, functional_test_score=70)
        # Correct the 08-03 entry; the 08-04 entry must stay current.
        e_day1_fix = record_status_entry(
            case_id, "2026-08-03", designation="MODIFIED", symptom_free=True,
            functional_test_score=65, supersedes_entry_id=e_day1["id"],
        )
        day2 = get_success_data(api.get_daily_status_entry(e_day2["id"], medical_staff_headers))
        assert day2["is_current"] is True, "entries for other dates must remain current"
        assert e_day1_fix["is_current"] is True
        old = get_success_data(api.get_daily_status_entry(e_day1["id"], medical_staff_headers))
        assert old["is_current"] is False
        assert len(_current_entries(api, case_id, "2026-08-03", medical_staff_headers)) == 1
        assert len(_current_entries(api, case_id, "2026-08-04", medical_staff_headers)) == 1


class TestSupersedeValidation:
    def test_supersede_entry_of_another_case_rejected(self, api, medical_staff_headers):
        """PRD §3.2: "the supersede target must be an `is_current` entry for
        the same `(injury_case_id, entry_date)`, otherwise the request is
        rejected with `ERR_INVALID_SUPERSEDE_TARGET`."

        Design: Corner/validations/supersede_wrong_case_rejected
        """
        sc = setup_open_case(clock="2026-08-03T00:00:00Z", occurred_on="2026-08-02")
        case2 = get_success_data(
            api.create_injury_case(
                {
                    "athlete_id": sc["athlete"]["id"],
                    "diagnosis_code_id": sc["diagnosis_code"]["id"],
                    "occurred_on": "2026-08-02",
                    "surface": "TURF",
                    "mechanism": "NON_CONTACT",
                },
                medical_staff_headers,
            )
        )
        e1 = record_status_entry(sc["case"]["id"], "2026-08-03", designation="OUT")
        resp = api.create_daily_status_entry(
            {
                "injury_case_id": case2["id"],
                "entry_date": "2026-08-03",
                "designation": "LIMITED",
                "symptom_free": True,
                "functional_test_score": 60,
                "supersedes_entry_id": e1["id"],
            },
            medical_staff_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_SUPERSEDE_TARGET)


class TestDerivedTierReconciliation:
    def test_availability_tier_recomputes_on_supersede(self, api, medical_staff_headers):
        """PRD §3.7: "The athlete's `availability_tier` is recomputed eagerly
        on every triggering mutation: injury-case status changes, daily-status
        creation or supersede, clearance grant, RTP regression, athlete
        reactivation, or workload ingest."
        PRD §3.7: "For each candidate case, the effective designation is the
        `designation` of the `is_current` daily status entry whose
        `entry_date` equals the current logical date"

        Design: Corner/cross_cutting_layers/derived_field_reconciles_after_supersede
        """
        sc = setup_rehab_case(
            clock="2026-08-03T00:00:00Z", occurred_on="2026-08-02", entry_date="2026-08-03"
        )
        before = get_athlete(sc["athlete"]["id"])
        assert before["availability_tier"] == "OUT", (
            "REHAB case whose current entry designates OUT must yield tier OUT"
        )
        record_status_entry(
            sc["case"]["id"], "2026-08-03", designation="FULL", symptom_free=True,
            functional_test_score=95, supersedes_entry_id=sc["entry"]["id"],
        )
        after = get_athlete(sc["athlete"]["id"])
        assert after["availability_tier"] == "FULL", (
            f"tier must reconcile to FULL after the supersede, got {after['availability_tier']}"
        )
