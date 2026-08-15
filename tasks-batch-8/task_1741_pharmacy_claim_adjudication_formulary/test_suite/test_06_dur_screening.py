"""DUR screening: half-open fill windows, alert types/severities, overrides, hard stop."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    assert_dur_alert,
    make_adjudication_scenario, make_drug, make_formulary_entry,
    submit_claim, create_paid_claim, get_only_rejected_claim, list_dur_alerts,
    make_pharmacist_headers,
)


class TestHighDailyDoseBoundary:
    def _dose_scenario(self):
        return make_adjudication_scenario(
            drug_overrides={"ndc": "00000-9015", "name": "Dosemax",
                            "therapeutic_class": "OPIOID", "unit_cost_cents": 100,
                            "max_daily_dose_units": 3},
            entry_overrides={"quantity_limit_per_fill": 120, "max_days_supply": 90,
                             "copay_flat_cents": 100},
        )

    def test_quantity_equal_to_max_daily_times_days_no_alert(self, api):
        """PRD §3.6: "A `HIGH_DAILY_DOSE` alert fires at `HIGH` severity when the claim's
        `quantity` strictly exceeds the drug's `max_daily_dose_units` multiplied by its
        `days_supply`; a quantity exactly equal to that product raises no alert."

        Design: Corner/calculations/dur_high_daily_dose_boundary_and_hard_stop
        """
        scenario = self._dose_scenario()
        claim = validate_success(
            submit_claim(scenario["member"]["id"], scenario["drug"]["id"],
                         scenario["pharmacy"]["id"], fill_date="2026-03-01",
                         quantity=90, days_supply=30),
            201,
        )
        assert claim["status"] == "PAID", "quantity == 3 x 30 exactly is not an alert"
        alerts = list_dur_alerts(claim["id"], scenario["pharmacist_headers"])
        assert alerts == [], f"Equality raises no alert, got {alerts}"

    def test_quantity_one_above_hard_stops(self, api):
        """PRD §3.6: "A `HIGH_DAILY_DOSE` alert fires at `HIGH` severity when the claim's
        `quantity` strictly exceeds the drug's `max_daily_dose_units` multiplied by its
        `days_supply`; a quantity exactly equal to that product raises no alert."
        PRD §3.4: "Eleventh, the DUR hard stop of §3.6: after this call's override codes
        are applied, no alert raised for this claim may remain `OPEN` at `HIGH`
        severity, else `ERR_DUR_HARD_STOP`."

        Design: Corner/calculations/dur_high_daily_dose_boundary_and_hard_stop
        """
        scenario = self._dose_scenario()
        member_id, drug_id, pharmacy_id = (
            scenario["member"]["id"], scenario["drug"]["id"], scenario["pharmacy"]["id"],
        )
        validate_success(
            submit_claim(member_id, drug_id, pharmacy_id, fill_date="2026-03-01",
                         quantity=90, days_supply=30),
            201,
        )
        res = submit_claim(member_id, drug_id, pharmacy_id, fill_date="2026-05-01",
                           quantity=91, days_supply=30)
        validate_error(res, "ERR_DUR_HARD_STOP", expected_status=422)
        claim = get_only_rejected_claim(member_id)
        assert claim["status"] == "REJECTED"
        assert claim["reject_reasons"] == ["ERR_DUR_HARD_STOP"]
        alerts = list_dur_alerts(claim["id"], scenario["pharmacist_headers"])
        assert len(alerts) == 1
        assert_dur_alert(alerts[0])
        assert alerts[0]["alert_type"] == "HIGH_DAILY_DOSE"
        assert alerts[0]["severity"] == "HIGH"
        assert alerts[0]["status"] == "OPEN"


class TestDurOverride:
    def _override_scenario(self):
        scenario = make_adjudication_scenario(
            drug_overrides={"ndc": "00000-9016", "name": "Overridex",
                            "therapeutic_class": "OPIOID", "unit_cost_cents": 1000,
                            "max_daily_dose_units": 1},
            entry_overrides={"copay_flat_cents": 100},
        )
        res = submit_claim(scenario["member"]["id"], scenario["drug"]["id"],
                           scenario["pharmacy"]["id"], fill_date="2026-03-01",
                           quantity=5, days_supply=1)
        validate_error(res, "ERR_DUR_HARD_STOP", expected_status=422)
        claim = get_only_rejected_claim(scenario["member"]["id"])
        alerts = list_dur_alerts(claim["id"], scenario["pharmacist_headers"])
        assert len(alerts) == 1 and alerts[0]["status"] == "OPEN"
        return scenario, claim, alerts[0]

    def test_dur_override_clears_hard_stop(self, api):
        """PRD §3.6: "Every override naming one of the claim's `OPEN` alerts moves that
        alert to `OVERRIDDEN` and records the code; overrides naming alerts that are no
        longer `OPEN` are simply ignored."
        PRD §3.6: "if any of the claim's alerts is still `OPEN` with `HIGH` severity
        after this call's overrides are applied, adjudication fails with
        `ERR_DUR_HARD_STOP` — `MEDIUM` alerts never block payment on their own."

        Design: Corner/calculations/dur_override_clears_hard_stop
        """
        scenario, claim, alert = self._override_scenario()
        paid = validate_success(
            api.resubmit_claim(
                claim["id"],
                {"dur_overrides": [
                    {"alert_id": alert["id"], "override_code": "PRESCRIBER_CONFIRMED"},
                ]},
                scenario["pharmacist_headers"],
            ),
            200,
        )
        assert paid["status"] == "PAID"
        assert paid["allowed_cents"] == 5000
        assert paid["member_pays_cents"] == 100
        assert paid["plan_paid_cents"] == 4900
        assert paid["resubmit_count"] == 1
        alerts = list_dur_alerts(claim["id"], scenario["pharmacist_headers"])
        assert len(alerts) == 1
        assert alerts[0]["status"] == "OVERRIDDEN"
        assert alerts[0]["override_code"] == "PRESCRIBER_CONFIRMED"

    def test_resubmit_with_invalid_override_code_rejected(self, api):
        """PRD §3.6: "Each named alert must belong to the claim being resubmitted and
        the code must be a valid enumeration value, else the request fails shape
        validation with `ERR_INVALID_REQUEST`."

        Design: Corner/validations/resubmit_with_invalid_override_code_rejected
        """
        scenario, claim, alert = self._override_scenario()
        res = api.resubmit_claim(
            claim["id"],
            {"dur_overrides": [{"alert_id": alert["id"], "override_code": "NOT_A_CODE"}]},
            scenario["pharmacist_headers"],
        )
        validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)
        claim_after = get_only_rejected_claim(scenario["member"]["id"])
        assert claim_after["status"] == "REJECTED"
        alerts = list_dur_alerts(claim["id"], scenario["pharmacist_headers"])
        assert alerts[0]["status"] == "OPEN"
        assert alerts[0]["override_code"] is None


class TestTherapeuticDuplication:
    def _dupe_scenario(self):
        scenario = make_adjudication_scenario(
            drug_overrides={"ndc": "00000-9017", "name": "Statin-A",
                            "therapeutic_class": "STATIN", "unit_cost_cents": 1000,
                            "max_daily_dose_units": 100},
            entry_overrides={"copay_flat_cents": 100},
        )
        drug_b = make_drug(ndc="00000-9018", name="Statin-B",
                           therapeutic_class="STATIN", unit_cost_cents=2000,
                           max_daily_dose_units=100)
        make_formulary_entry(scenario["plan"]["id"], drug_b["id"], tier=1,
                             quantity_limit_per_fill=90, max_days_supply=90,
                             copay_type="FLAT", copay_flat_cents=200)
        scenario["drug_b"] = drug_b
        return scenario

    def test_overlapping_same_class_claim_alerts_but_pays(self, api):
        """PRD §3.6: "A `THERAPEUTIC_DUPLICATION` alert, also `MEDIUM`, uses the
        identical overlap predicate against `PAID` claims of the same member for a
        different drug whose `therapeutic_class` matches the new drug's."
        PRD §3.6: "`MEDIUM` alerts never block payment on their own."

        Design: Corner/calculations/therapeutic_duplication_alert_for_same_class
        """
        scenario = self._dupe_scenario()
        member_id, pharmacy_id = scenario["member"]["id"], scenario["pharmacy"]["id"]
        create_paid_claim(member_id, scenario["drug"]["id"], pharmacy_id,
                          fill_date="2026-03-01", quantity=30, days_supply=30)
        claim = validate_success(
            submit_claim(member_id, scenario["drug_b"]["id"], pharmacy_id,
                         fill_date="2026-03-15", quantity=30, days_supply=30),
            201,
        )
        assert claim["status"] == "PAID"
        alerts = list_dur_alerts(claim["id"], scenario["pharmacist_headers"])
        assert len(alerts) == 1
        assert_dur_alert(alerts[0])
        assert alerts[0]["alert_type"] == "THERAPEUTIC_DUPLICATION"
        assert alerts[0]["severity"] == "MEDIUM"
        assert alerts[0]["status"] == "OPEN"

    def test_disjoint_same_class_claim_raises_no_alert(self, api):
        """PRD §3.6: "A `THERAPEUTIC_DUPLICATION` alert, also `MEDIUM`, uses the
        identical overlap predicate against `PAID` claims of the same member for a
        different drug whose `therapeutic_class` matches the new drug's."
        PRD §3.6: "Fill windows are half-open: a fill covers the interval from its
        `fill_date` up to but not including `fill_date` plus `days_supply`, so a new
        fill dated exactly on the day an earlier fill's supply runs out does not
        overlap it."

        Design: Corner/calculations/therapeutic_duplication_alert_for_same_class
        """
        scenario = self._dupe_scenario()
        member_id, pharmacy_id = scenario["member"]["id"], scenario["pharmacy"]["id"]
        create_paid_claim(member_id, scenario["drug"]["id"], pharmacy_id,
                          fill_date="2026-03-01", quantity=30, days_supply=30)
        claim = validate_success(
            submit_claim(member_id, scenario["drug_b"]["id"], pharmacy_id,
                         fill_date="2026-09-01", quantity=30, days_supply=30),
            201,
        )
        assert claim["status"] == "PAID"
        alerts = list_dur_alerts(claim["id"], scenario["pharmacist_headers"])
        assert alerts == [], "Window [09-01, 10-01) is disjoint from [03-01, 03-31)"


class TestEarlyRefillHalfOpenAdjacency:
    def _refill_scenario(self):
        return make_adjudication_scenario(
            drug_overrides={"ndc": "12121-0001", "name": "Refillex",
                            "therapeutic_class": "ANTIDIABETIC", "unit_cost_cents": 1000,
                            "max_daily_dose_units": 100},
            entry_overrides={"quantity_limit_per_fill": 120, "copay_flat_cents": 100},
        )

    def test_fill_exactly_at_prior_window_end_no_alert(self, api):
        """PRD §3.6: "Fill windows are half-open: a fill covers the interval from its
        `fill_date` up to but not including `fill_date` plus `days_supply`, so a new
        fill dated exactly on the day an earlier fill's supply runs out does not
        overlap it."

        Design: Difficulty/resource_temporal_overlap/early_refill_half_open_adjacency
        """
        scenario = self._refill_scenario()
        member_id, drug_id, pharmacy_id = (
            scenario["member"]["id"], scenario["drug"]["id"], scenario["pharmacy"]["id"],
        )
        create_paid_claim(member_id, drug_id, pharmacy_id, fill_date="2026-03-01",
                          quantity=30, days_supply=30)
        claim = validate_success(
            submit_claim(member_id, drug_id, pharmacy_id, fill_date="2026-03-31",
                         quantity=30, days_supply=30),
            201,
        )
        assert claim["status"] == "PAID"
        alerts = list_dur_alerts(claim["id"], scenario["pharmacist_headers"])
        assert alerts == [], "Half-open adjacency (fill == prior fill + days) is not overlap"

    def test_fill_one_day_before_window_end_alerts(self, api):
        """PRD §3.6: "An `EARLY_REFILL` alert fires at `MEDIUM` severity when another
        `PAID` claim of the same member for the same drug overlaps the new fill —
        overlap meaning the earlier claim's fill date is before the new fill date plus
        the new days supply, and the new fill date is before the earlier fill date plus
        its days supply."
        PRD §3.6: "Screening writes one **DurAlert** row per claim per `alert_type` —
        duplicates of the same type for the same claim are suppressed"

        Design: Difficulty/resource_temporal_overlap/early_refill_half_open_adjacency
        """
        scenario = self._refill_scenario()
        member_id, drug_id, pharmacy_id = (
            scenario["member"]["id"], scenario["drug"]["id"], scenario["pharmacy"]["id"],
        )
        create_paid_claim(member_id, drug_id, pharmacy_id, fill_date="2026-03-01",
                          quantity=30, days_supply=30)
        create_paid_claim(member_id, drug_id, pharmacy_id, fill_date="2026-03-31",
                          quantity=30, days_supply=30)
        # [03-31, 04-30) of the second fill is overlapped by a 2026-04-29 fill.
        claim = validate_success(
            submit_claim(member_id, drug_id, pharmacy_id, fill_date="2026-04-29",
                         quantity=30, days_supply=30),
            201,
        )
        assert claim["status"] == "PAID", "MEDIUM alerts do not block payment"
        alerts = list_dur_alerts(claim["id"], scenario["pharmacist_headers"])
        assert len(alerts) == 1
        assert_dur_alert(alerts[0])
        assert alerts[0]["alert_type"] == "EARLY_REFILL"
        assert alerts[0]["severity"] == "MEDIUM"
        assert alerts[0]["status"] == "OPEN"
