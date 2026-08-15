"""Damage-charge variants (DEPRECIATED vs ACTUAL_COST), key/fob/lock
conditional branch, carpet end-of-life boundary, and PAINT/OTHER schedules."""
import test_helpers as th
from test_helpers import (
    add_item,
    api_client,
    complete_inspection,
    create_jurisdiction,
    create_property,
    create_tenancy,
    create_unit,
    get_success_data,
    get_tenancy,
    make_manager_admin_headers,
    make_property_manager_headers,
    schedule_inspection,
)

ADMIN = make_manager_admin_headers()
PM = make_property_manager_headers()


def _list_deductions(tenancy_id):
    resp = api_client.list_deductions(PM, params={"tenancy_id": tenancy_id, "limit": 100})
    data = get_success_data(resp)
    return data if isinstance(data, list) else data.get("data", [])


def _damage_pair():
    """Two jurisdictions identical except allow_actual_cost_charge; both
    tenancies carry one CARPET TENANT_DAMAGE item (replacement 182,500c); the
    actual-cost jurisdiction's item carries actual_repair_cents 50,000. Carpet
    installed 2022-08-01, life 5y (1,825d); move-out 2026-08-01 => age 1,461d,
    residual 364/1825."""
    api_client.set_clock({"to_iso8601": "2025-01-10T00:00:00Z"}, ADMIN)
    jur_a = create_jurisdiction(code="CA-DEP", allow_actual_cost_charge=False)
    jur_b = create_jurisdiction(code="TX-ACT", allow_actual_cost_charge=True)
    prop_a = create_property(jur_a["id"], name="Maple Court", address="1 Maple St")
    prop_b = create_property(jur_b["id"], name="Birch Court", address="2 Birch St")
    unit_a = create_unit(prop_a["id"], unit_number="1A")
    unit_b = create_unit(prop_b["id"], unit_number="1B")
    out = []
    for unit, name, with_actual in ((unit_a, "Tanya A", False), (unit_b, "Tanya B", True)):
        ten = create_tenancy(unit["id"], tenant_display_name=name)
        mi = schedule_inspection(ten["id"], "MOVE_IN")
        mi_item = add_item(mi["id"], area_name="living_room_carpet", category="CARPET",
                           condition="GOOD", photo_count=2)
        complete_inspection(mi["id"])
        out.append((ten, mi_item, with_actual))
    api_client.set_clock({"to_iso8601": "2026-08-01T00:00:00Z"}, ADMIN)
    results = []
    for ten, mi_item, with_actual in out:
        get_success_data(api_client.give_notice(ten["id"], PM))
        get_success_data(api_client.record_key_return(
            ten["id"], {"keys_returned": 2, "fobs_returned": 1}, PM))
        mo = schedule_inspection(ten["id"], "MOVE_OUT")
        ov = dict(area_name="living_room_carpet", category="CARPET",
                  condition="DAMAGED", photo_count=3, determination="TENANT_DAMAGE",
                  linked_move_in_item_id=mi_item["id"], replacement_cost_cents=182_500)
        if with_actual:
            ov["actual_repair_cents"] = 50_000
        add_item(mo["id"], **ov)
        complete_inspection(mo["id"])
        results.append(ten)
    return results


class TestDamageChargeDualVariant:
    def test_depreciated_variant_yields_36400(self):
        """PRD §3.4: "The default `DEPRECIATED` variant charges the item's
        `replacement_cost_cents` multiplied by that residual fraction, rounded
        half-up to whole cents, so the charge shrinks with age and reaches zero
        at end of life."

        Age 1,461 of 1,825 days => residual 364/1825; 182,500 * 364/1825 =
        36,400c.

        Design: Difficulty/dual_variant_calc/damage_charge_depreciated_vs_actual_cost
        """
        ten_a, _ten_b = _damage_pair()
        deductions = _list_deductions(ten_a["id"])
        damage = [d for d in deductions if d["source"] == "MOVE_OUT_DAMAGE"]
        assert len(damage) == 1 and damage[0]["amount_cents"] == 36_400, (
            f"DEPRECIATED charge: expected one 36400 line, got {damage}"
        )
        assert get_tenancy(ten_a["id"])["pending_deductions_cents"] == 36_400

    def test_actual_cost_variant_yields_50000(self):
        """PRD §3.4: "The `ACTUAL_COST` variant applies only when the
        jurisdiction's `allow_actual_cost_charge` flag is set and the item
        carries a documented `actual_repair_cents`: the charge is then the
        lesser of `actual_repair_cents` and `replacement_cost_cents`, with no
        depreciation for age."

        min(50,000, 182,500) = 50,000c, vs 36,400c under the depreciated
        variant on identical damage.

        Design: Difficulty/dual_variant_calc/damage_charge_depreciated_vs_actual_cost
        """
        ten_a, ten_b = _damage_pair()
        ded_a = [d for d in _list_deductions(ten_a["id"]) if d["source"] == "MOVE_OUT_DAMAGE"]
        ded_b = [d for d in _list_deductions(ten_b["id"]) if d["source"] == "MOVE_OUT_DAMAGE"]
        assert len(ded_b) == 1 and ded_b[0]["amount_cents"] == 50_000, (
            f"ACTUAL_COST charge: expected one 50000 line, got {ded_b}"
        )
        assert get_tenancy(ten_b["id"])["pending_deductions_cents"] == 50_000
        assert ded_a[0]["amount_cents"] != ded_b[0]["amount_cents"]


class TestKeyFobLockConditionalCharge:
    def _three_tenancy_setup(self):
        """A under lock-allowed (1 missing key, 0 missing fobs), B under
        lock-not-allowed (same counts), C under lock-allowed (all returned)."""
        api_client.set_clock({"to_iso8601": "2025-01-10T00:00:00Z"}, ADMIN)
        jur_l = create_jurisdiction(code="CA-LOCK", lock_change_allowed=True)
        jur_n = create_jurisdiction(code="CA-NOLOCK", lock_change_allowed=False)
        prop_l = create_property(jur_l["id"], name="Maple Court", address="1 Maple St")
        prop_n = create_property(jur_n["id"], name="Birch Court", address="2 Birch St")
        unit_a = create_unit(prop_l["id"], unit_number="A1")
        unit_b = create_unit(prop_n["id"], unit_number="B1")
        unit_c = create_unit(prop_l["id"], unit_number="C1")
        plan = [(unit_a, "T A", 1, 1), (unit_b, "T B", 1, 1), (unit_c, "T C", 2, 1)]
        out = []
        for unit, name, keys_back, fobs_back in plan:
            ten = create_tenancy(unit["id"], tenant_display_name=name)
            mi = schedule_inspection(ten["id"], "MOVE_IN")
            complete_inspection(mi["id"])
            out.append((ten, keys_back, fobs_back))
        api_client.set_clock({"to_iso8601": "2026-08-01T00:00:00Z"}, ADMIN)
        result = []
        for ten, keys_back, fobs_back in out:
            get_success_data(api_client.give_notice(ten["id"], PM))
            get_success_data(api_client.record_key_return(
                ten["id"], {"keys_returned": keys_back, "fobs_returned": fobs_back}, PM))
            mo = schedule_inspection(ten["id"], "MOVE_OUT")
            complete_inspection(mo["id"])
            result.append(ten)
        return result

    def test_lock_line_only_when_key_missing_and_allowed(self):
        """PRD §3.4: "The lock-change branch is conditional on both facts: only
        when at least one key is missing and the jurisdiction's
        `lock_change_allowed` is set does a `LOCK_CHANGE` line appear, always
        with `quantity` one and `amount_cents` equal to the property's
        `lock_change_cents`." And: "When at least one key is missing, a line
        with source `KEY_NOT_RETURNED` is created whose `quantity` is the
        missing-key count and whose `amount_cents` is that count multiplied by
        the property's `key_charge_cents`."

        A (allowed, 1 missing key): 5,000 + 12,000 = 17,000c. B (not allowed,
        same counts): 5,000c only, no LOCK_CHANGE line exists.

        Design: Difficulty/combinatorial_formula/key_fob_lock_conditional_charge
        """
        ten_a, ten_b, _ten_c = self._three_tenancy_setup()
        assert get_tenancy(ten_a["id"])["pending_deductions_cents"] == 17_000
        assert get_tenancy(ten_b["id"])["pending_deductions_cents"] == 5_000
        sources_b = {d["source"] for d in _list_deductions(ten_b["id"])}
        assert "LOCK_CHANGE" not in sources_b, (
            f"no LOCK_CHANGE line may exist when lock_change_allowed is false: {sources_b}"
        )

    def test_all_returned_bills_nothing_and_key_quantity_matches_missing(self):
        """PRD §3.4: "When at least one key is missing, a line with source
        `KEY_NOT_RETURNED` is created whose `quantity` is the missing-key count
        and whose `amount_cents` is that count multiplied by the property's
        `key_charge_cents`." and "A determination of `NORMAL_WEAR` never
        creates a deduction, and a computed charge of exactly zero creates no
        line either."

        C (all keys/fobs returned): no deduction lines at all, pending 0.
        A's KEY_NOT_RETURNED line carries quantity 1 (one missing key).

        Design: Difficulty/combinatorial_formula/key_fob_lock_conditional_charge
        """
        ten_a, _ten_b, ten_c = self._three_tenancy_setup()
        assert get_tenancy(ten_c["id"])["pending_deductions_cents"] == 0
        assert _list_deductions(ten_c["id"]) == []
        key_lines = [d for d in _list_deductions(ten_a["id"])
                     if d["source"] == "KEY_NOT_RETURNED"]
        assert len(key_lines) == 1 and key_lines[0]["quantity"] == 1, (
            f"KEY_NOT_RETURNED quantity must equal the missing-key count: {key_lines}"
        )


class TestCarpetEndOfLifeBoundary:
    def _carpet_boundary_pair(self):
        """Unit A carpet 2021-08-02 (age exactly 1,825d == life at move-out
        2026-08-01); unit B carpet 2021-08-03 (age 1,824d)."""
        api_client.set_clock({"to_iso8601": "2025-01-10T00:00:00Z"}, ADMIN)
        jur = create_jurisdiction()
        prop = create_property(jur["id"])
        unit_a = create_unit(prop["id"], unit_number="1A",
                             carpet_installed_on="2021-08-02")
        unit_b = create_unit(prop["id"], unit_number="1B",
                             carpet_installed_on="2021-08-03")
        out = []
        for unit, name in ((unit_a, "T A"), (unit_b, "T B")):
            ten = create_tenancy(unit["id"], tenant_display_name=name)
            mi = schedule_inspection(ten["id"], "MOVE_IN")
            mi_item = add_item(mi["id"], area_name="carpet", category="CARPET",
                               condition="GOOD", photo_count=2)
            complete_inspection(mi["id"])
            out.append((ten, mi_item))
        api_client.set_clock({"to_iso8601": "2026-08-01T00:00:00Z"}, ADMIN)
        result = []
        for ten, mi_item in out:
            get_success_data(api_client.give_notice(ten["id"], PM))
            get_success_data(api_client.record_key_return(
                ten["id"], {"keys_returned": 2, "fobs_returned": 1}, PM))
            mo = schedule_inspection(ten["id"], "MOVE_OUT")
            add_item(mo["id"], area_name="carpet", category="CARPET",
                     condition="DAMAGED", photo_count=3, determination="TENANT_DAMAGE",
                     linked_move_in_item_id=mi_item["id"], replacement_cost_cents=182_500)
            complete_inspection(mo["id"])
            result.append(ten)
        return result

    def test_age_exactly_life_creates_no_line(self):
        """PRD §3.4: "the residual fraction is the life remaining — the life in
        days minus the age in days, floored at zero so an item at or beyond its
        end of life has no residual — divided by the life in days" and "a
        computed charge of exactly zero creates no line either."

        Age 1,825 == life 1,825 => residual 0 => charge 0 => NO deduction line
        for tenancy A.

        Design: Difficulty/boundary_precision_check/carpet_age_exactly_life_zero_charge
        """
        ten_a, _ten_b = self._carpet_boundary_pair()
        assert get_tenancy(ten_a["id"])["pending_deductions_cents"] == 0
        assert _list_deductions(ten_a["id"]) == [], (
            "a zero computed charge must create no deduction line"
        )

    def test_age_one_day_under_life_yields_100(self):
        """PRD §3.4: "The default `DEPRECIATED` variant charges the item's
        `replacement_cost_cents` multiplied by that residual fraction, rounded
        half-up to whole cents".

        Age 1,824 of 1,825 => residual 1/1825; round(182,500/1825) = 100c and
        exactly one line exists.

        Design: Difficulty/boundary_precision_check/carpet_age_exactly_life_zero_charge
        """
        _ten_a, ten_b = self._carpet_boundary_pair()
        assert get_tenancy(ten_b["id"])["pending_deductions_cents"] == 100
        deductions = _list_deductions(ten_b["id"])
        assert len(deductions) == 1 and deductions[0]["amount_cents"] == 100


class TestPaintAndOtherSchedules:
    def test_paint_residual_and_other_full_cost(self):
        """PRD §3.4: "for a `PAINT` item the analogous `paint_applied_on` and
        `paint_life_years` apply" and "Items in the `OTHER` category have no
        schedule and are charged at full `replacement_cost_cents`."

        PAINT: applied 2025-08-01, life 3y (1,095d), age 365d => residual
        730/1095 => 2/3 of 90,000c = 60,000c. OTHER (blinds, 3,000c): full
        replacement. Pending total 63,000c.

        Design: Corner/calculations/paint_residual_and_other_full_cost
        """
        api_client.set_clock({"to_iso8601": "2025-01-10T00:00:00Z"}, ADMIN)
        jur = create_jurisdiction()
        prop = create_property(jur["id"])
        unit = create_unit(prop["id"])
        ten = create_tenancy(unit["id"])
        mi = schedule_inspection(ten["id"], "MOVE_IN")
        mi_paint = add_item(mi["id"], area_name="bedroom_paint", category="PAINT",
                            condition="GOOD", photo_count=2)
        mi_blinds = add_item(mi["id"], area_name="window_blinds", category="OTHER",
                             condition="GOOD", photo_count=1)
        complete_inspection(mi["id"])
        api_client.set_clock({"to_iso8601": "2026-08-01T00:00:00Z"}, ADMIN)
        get_success_data(api_client.give_notice(ten["id"], PM))
        get_success_data(api_client.record_key_return(
            ten["id"], {"keys_returned": 2, "fobs_returned": 1}, PM))
        mo = schedule_inspection(ten["id"], "MOVE_OUT")
        add_item(mo["id"], area_name="bedroom_paint", category="PAINT",
                 condition="DAMAGED", photo_count=4, determination="TENANT_DAMAGE",
                 linked_move_in_item_id=mi_paint["id"], replacement_cost_cents=90_000)
        add_item(mo["id"], area_name="window_blinds", category="OTHER",
                 condition="DAMAGED", photo_count=2, determination="TENANT_DAMAGE",
                 linked_move_in_item_id=mi_blinds["id"], replacement_cost_cents=3_000)
        complete_inspection(mo["id"])

        deductions = _list_deductions(ten["id"])
        damage_lines = [d for d in deductions if d["source"] == "MOVE_OUT_DAMAGE"]
        amounts = sorted(d["amount_cents"] for d in damage_lines)
        assert amounts == [3_000, 60_000], (
            f"PAINT residual 60000 + OTHER full 3000 expected, got {amounts}"
        )
        assert get_tenancy(ten["id"])["pending_deductions_cents"] == 63_000
