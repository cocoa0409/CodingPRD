"""Annuity fee computation: tiers, entity size, surcharge branches (PRD §3.4)."""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    create_rule,
    create_client,
    create_contact,
    create_family,
    create_granted_application,
    list_obligations,
    get_family,
    instruct_obligation,
    setup_world_with_granted_app,
    JP_RULE_PAYLOAD,
)

ANY = TEST_USERS["any_headers"]
FIN = TEST_USERS["finance_headers"]


def _jp_world():
    """JP rule (start 3, term 4; tier1 10001, tier2 20000; small 5000 bps;
    surcharge 2500/5000 bps; fx 10000) with one SMALL and one LARGE granted app."""
    create_rule(JP_RULE_PAYLOAD)
    client = create_client("FeeCo")
    contact = create_contact(client["id"])
    family = create_family(client["id"], budget_cap_cents=1000000)
    app_s = create_granted_application(
        family["id"], grant_date="2026-03-01", jurisdiction="JP",
        application_number="JP-S", entity_size="SMALL")
    app_l = create_granted_application(
        family["id"], grant_date="2026-03-01", jurisdiction="JP",
        application_number="JP-L", entity_size="LARGE")
    return client, contact, family, app_s, app_l


class TestAnnuityFeeTieredSmallEntitySurcharge:
    def test_small_entity_base_rounds_half_up_and_late_surcharge_applies(self):
        """PRD §3.4: "when the application's `entity_size` is `SMALL`, the base
        is multiplied by the rule's `small_entity_multiplier_bps` and divided
        by ten thousand, rounded half up to whole local cents" and "two or more
        months late uses `surcharge_bps_late`."

        Design: Difficulty/combinatorial_formula/annuity_fee_tiered_small_entity_surcharge_branches
        """
        _, contact, _, app_s, _ = _jp_world()
        ob_s3 = list_obligations(app_s["id"])[0]
        # round_half_up(10001 * 5000 / 10000) = 5001.
        assert ob_s3["period_year"] == 3
        assert ob_s3["base_fee_local_cents"] == 5001
        instruct_obligation(ob_s3["id"], 5001, contact["id"])
        # due 2028-09-01, paid 2028-10-15 -> months_late 2 -> +50% on 5001 = 2501.
        resp = api_client.confirm_payment(ob_s3["id"], {"paid_date": "2028-10-15"}, FIN)
        data = validate_success(resp, 200)
        assert data["paid_amount_cents"] == 7502

    def test_large_entity_on_time_and_one_month_late_branches(self):
        """PRD §3.4: "a `LARGE` application pays the tier fee unadjusted";
        "when there is no paid date yet, or the paid date falls on or before
        the `due_date`, the surcharge is zero"; "Exactly one month late uses
        the rule's `surcharge_bps_month_1`; two or more months late uses
        `surcharge_bps_late`."

        Design: Difficulty/combinatorial_formula/annuity_fee_tiered_small_entity_surcharge_branches
        """
        _, contact, _, _, app_l = _jp_world()
        obligations = list_obligations(app_l["id"])
        ob_l3, ob_l4 = obligations[0], obligations[1]
        assert ob_l3["base_fee_local_cents"] == 10001
        assert ob_l4["base_fee_local_cents"] == 20000

        instruct_obligation(ob_l3["id"], 10001, contact["id"])
        # Paid exactly on the due date -> zero surcharge.
        paid_l3 = validate_success(
            api_client.confirm_payment(ob_l3["id"], {"paid_date": "2028-09-01"}, FIN), 200)
        assert paid_l3["paid_amount_cents"] == 10001

        instruct_obligation(ob_l4["id"], 20000, contact["id"])
        # due 2029-09-01, paid 2029-09-21 -> months_late 1 -> +25% of 20000.
        paid_l4 = validate_success(
            api_client.confirm_payment(ob_l4["id"], {"paid_date": "2029-09-21"}, FIN), 200)
        assert paid_l4["paid_amount_cents"] == 25000


class TestSurchargeBoundary:
    def test_paid_exactly_on_due_date_has_zero_surcharge(self):
        """PRD §3.4: "when there is no paid date yet, or the paid date falls on
        or before the `due_date`, the surcharge is zero."

        Design: Difficulty/boundary_precision_check/surcharge_boundary_paid_exactly_on_due_date
        """
        world = setup_world_with_granted_app(client_name="BndCo")
        ob3 = world["obligations"][0]
        instruct_obligation(ob3["id"], 10000, world["contact"]["id"])
        # y3 due 2028-09-01; paid on the same day.
        data = validate_success(
            api_client.confirm_payment(ob3["id"], {"paid_date": "2028-09-01"}, FIN), 200)
        assert data["paid_amount_cents"] == 10000
        assert data["status"] == "PAID_CONFIRMED"

    def test_paid_one_day_late_triggers_month_one_surcharge_and_rollup_delta(self):
        """PRD §3.4: "any paid date strictly after the due date yields at least
        one month late"; PRD §3.5: "the family's `committed_forecast_cents`
        adjusts by the difference between `paid_amount_cents` and the
        previously committed `authorized_amount_cents`; and
        `authorized_amount_cents` clears to null."

        Design: Difficulty/boundary_precision_check/surcharge_boundary_paid_exactly_on_due_date
        """
        world = setup_world_with_granted_app(client_name="BndCo")
        ob4 = world["obligations"][1]
        instruct_obligation(ob4["id"], 20000, world["contact"]["id"])
        # y4 due 2029-09-01; paid 2029-09-02 -> months_late 1 -> +25% of 20000.
        data = validate_success(
            api_client.confirm_payment(ob4["id"], {"paid_date": "2029-09-02"}, FIN), 200)
        assert data["paid_amount_cents"] == 25000
        # Rollup replaces the authorized 20000 with the paid 25000.
        assert get_family(world["family"]["id"])["committed_forecast_cents"] == 25000


class TestSurchargeWindowClosed:
    def test_paid_beyond_surcharge_window_rejected(self):
        """PRD §3.5: "a `FinanceOfficer` supplies the `paid_date`, which must
        fall on or before the obligation's `surcharge_window_end`
        (`ERR_SURCHARGE_WINDOW_CLOSED`)."

        Design: Corner/validations/surcharge_window_closed_on_confirm_payment
        """
        world = setup_world_with_granted_app(client_name="SwCo")
        obligation = world["obligations"][0]
        # y3 due 2028-09-01, surcharge window end 2029-03-01.
        instruct_obligation(obligation["id"], 10000, world["contact"]["id"])
        validate_error(
            api_client.confirm_payment(obligation["id"], {"paid_date": "2029-03-02"}, FIN),
            ApiErrorId.ERR_SURCHARGE_WINDOW_CLOSED)

    def test_paid_exactly_on_window_end_uses_late_surcharge_tier(self):
        """PRD §3.5: "a `FinanceOfficer` supplies the `paid_date`, which must
        fall on or before the obligation's `surcharge_window_end`
        (`ERR_SURCHARGE_WINDOW_CLOSED`)"; PRD §3.4: "two or more months late
        uses `surcharge_bps_late`."

        Design: Corner/validations/surcharge_window_closed_on_confirm_payment
        """
        world = setup_world_with_granted_app(client_name="SwCo")
        obligation = world["obligations"][0]
        instruct_obligation(obligation["id"], 10000, world["contact"]["id"])
        validate_error(
            api_client.confirm_payment(obligation["id"], {"paid_date": "2029-03-02"}, FIN),
            ApiErrorId.ERR_SURCHARGE_WINDOW_CLOSED)
        # The window end is inclusive: 2029-03-01 is exactly six months after
        # the 2028-09-01 due date -> months_late 6 -> +50% of 10000.
        data = validate_success(
            api_client.confirm_payment(obligation["id"], {"paid_date": "2029-03-01"}, FIN), 200)
        assert data["paid_amount_cents"] == 15000


class TestAnnuityScheduleGeneration:
    def test_grant_generates_schedule_with_pinned_dates(self):
        """PRD §3.4: "The system generates one **AnnuityObligation** per
        `period_year`, from the rule's `annuity_start_year` through its
        `term_years` inclusive, produced in ascending period-year order and
        each starting in `SCHEDULED` status" and "Each obligation's
        `surcharge_window_end` is its `due_date` shifted forward by the rule's
        `surcharge_window_months`."

        Design: Corner/calculations/annuity_schedule_generation_dates
        """
        world = setup_world_with_granted_app(client_name="SchCo")
        obligations = world["obligations"]
        assert [o["period_year"] for o in obligations] == [3, 4, 5]
        assert all(o["status"] == "SCHEDULED" for o in obligations)
        # due_date = grant 2026-03-01 + (12y - 6m): 2028-09-01 / 2029-09-01 / 2030-09-01.
        assert obligations[0]["due_date"] == "2028-09-01"
        assert obligations[1]["due_date"] == "2029-09-01"
        assert obligations[2]["due_date"] == "2030-09-01"
        # surcharge_window_end = due + 6 months.
        assert obligations[0]["surcharge_window_end"] == "2029-03-01"
        # Tier 1 (years 1-3) 10000 vs tier 2 (years 4-7) 20000, fx 10000 bps = 1.0.
        assert obligations[0]["estimated_amount_usd_cents"] == 10000
        assert obligations[1]["estimated_amount_usd_cents"] == 20000
