"""Provider abrasion indices and tier gating, internal-first savings
attribution with vendor duplication avoidance, and vendor edit mapping."""
import pytest

from test_helpers import (
    TEST_USERS,
    approve_version,
    create_edit_rule,
    create_edit_version,
    create_provider,
    create_vendor_edit_payload,
    drive_hit_resolution,
    get_abrasion_profile,
    get_success_data,
    list_claim_hits,
    list_claim_tasks,
    make_analyst_headers,
    map_vendor_edit_payload,
    screen_one_line_claim,
    setup_provider_with_active_edit,
    submit_version,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["plan_admin_headers"]


def _setup_abrasion_4(api, npi="NPI-E1", edit_code="ABR-DENY"):
    """Provider + ACTIVE DENY edit; four 40000 claims: two upheld, one task
    OVERRIDE, one upheld then dispute OVERTURNED (false positive)."""
    provider, rule, version = setup_provider_with_active_edit(
        npi=npi, edit_code=edit_code)
    drive_hit_resolution(provider["id"], 40000, "E1", "M-E1", "uphold")
    drive_hit_resolution(provider["id"], 40000, "E2", "M-E2", "uphold")
    drive_hit_resolution(provider["id"], 40000, "E3", "M-E3", "override")
    drive_hit_resolution(provider["id"], 40000, "E4", "M-E4", "overturn")
    return provider, rule, version


def test_abrasion_standard_vs_regulatory_indices(api):
    """PRD §3.1: "The `standard_index` is count-weighted over the trailing
    90-day resolved population: it blends the overturn rate — the share of
    resolved hits that ended `OVERRIDDEN` or `RELEASED_FALSE_POSITIVE` — at
    sixty percent weight with the false-positive rate — the share that ended
    `RELEASED_FALSE_POSITIVE` — at forty percent weight, and the blend is
    rounded half-up to four decimal places"
    PRD §3.1: "The `regulatory_index` is the dollar-weighted, lifetime
    reporting view: lifetime released cents divided by lifetime denied cents,
    substituting one for the lifetime denied total when that total is zero,
    rounded half-up to four decimal places; it is computed for regulatory
    reporting and never drives the tier."

    Design: Difficulty/dual_variant_calc/abrasion_standard_vs_regulatory
    """
    provider, _rule, _version = _setup_abrasion_4(api)
    profile = get_abrasion_profile(provider["id"])
    # 4 resolved: 2 CONFIRMED, 1 OVERRIDDEN, 1 FP ->
    # standard = 0.6*(2/4) + 0.4*(1/4) = 0.4000
    assert profile["confirmed_count"] == 2
    assert profile["overridden_count"] == 1
    assert profile["fp_count"] == 1
    assert profile["standard_index"] == pytest.approx(0.40, abs=1e-9)
    # lifetime dollars: released 80000 / denied 160000 = 0.5000
    assert profile["released_cents_lifetime"] == 80000
    assert profile["denied_cents_lifetime"] == 160000
    assert profile["regulatory_index"] == pytest.approx(0.50, abs=1e-9)


def test_abrasion_tier_keyed_on_standard_only(api):
    """PRD §3.1: "The `tier` keys on `standard_index` only: `HIGH` when the
    index reaches 0.50, `MEDIUM` when it reaches 0.25 but not 0.50, otherwise
    `LOW`."
    PRD §3.1: "The `monitor_only` flag is true exactly when `tier` is `HIGH`"
    PRD §3.1: "it is computed for regulatory reporting and never drives the
    tier."

    Design: Difficulty/dual_variant_calc/abrasion_standard_vs_regulatory
    """
    provider, _rule, _version = _setup_abrasion_4(
        api, npi="NPI-E1B", edit_code="ABR-DENY-2")
    profile = get_abrasion_profile(provider["id"])
    assert profile["standard_index"] == pytest.approx(0.40, abs=1e-9)
    assert profile["regulatory_index"] == pytest.approx(0.50, abs=1e-9)
    assert profile["tier"] == "MEDIUM", (
        "tier keys on standard_index 0.4000 even though regulatory_index "
        "0.5000 sits at the HIGH threshold"
    )
    assert profile["monitor_only"] is False


def _setup_high_tier_provider(api, npi="NPI-B7", edit_code="MON-DENY"):
    """Provider driven to tier HIGH: 1 uphold, 1 task OVERRIDE, 1 uphold +
    dispute OVERTURNED. resolved 3 -> standard = 0.6*(2/3) + 0.4*(1/3) =
    0.5333 >= 0.50. The edit's own fp sample is 2 (< 4), so the edit itself is
    not auto-suspended."""
    provider, rule, version = setup_provider_with_active_edit(
        npi=npi, edit_code=edit_code)
    drive_hit_resolution(provider["id"], 40000, "B71", "M-B71", "uphold")
    drive_hit_resolution(provider["id"], 40000, "B72", "M-B72", "override")
    drive_hit_resolution(provider["id"], 40000, "B73", "M-B73", "overturn")
    return provider, rule, version


def test_hit_application_gated_by_abrasion_tier_profile(api):
    """PRD §3.1: "The `standard_index` is count-weighted over the trailing
    90-day resolved population: it blends the overturn rate — the share of
    resolved hits that ended `OVERRIDDEN` or `RELEASED_FALSE_POSITIVE` — at
    sixty percent weight with the false-positive rate — the share that ended
    `RELEASED_FALSE_POSITIVE` — at forty percent weight"
    PRD §3.1: "The `tier` keys on `standard_index` only: `HIGH` when the index
    reaches 0.50"
    PRD §3.1: "The `monitor_only` flag is true exactly when `tier` is `HIGH`"

    Design: Difficulty/cross_entity_state_dependency/hit_application_gated_by_abrasion_tier
    """
    provider, _rule, _version = _setup_high_tier_provider(api)
    profile = get_abrasion_profile(provider["id"])
    assert profile["standard_index"] == pytest.approx(0.5333, abs=1e-4)
    assert profile["tier"] == "HIGH"
    assert profile["monitor_only"] is True


def test_hit_application_gated_by_abrasion_tier_monitor_only_claim(api):
    """PRD §3.4: "when the provider's `tier` is `HIGH` at screening time, the
    hit is recorded with `applied` false — monitor-only — meaning no dollars
    move and no review task is created; otherwise `applied` is true."
    PRD §3.4: "Monitor-only hits (those with `applied` false) are attributed
    zero and excluded from the waterfall entirely."
    PRD §3.4: "When the run produced none of those, the claim goes straight to
    `READY_TO_PAY`"

    Design: Difficulty/cross_entity_state_dependency/hit_application_gated_by_abrasion_tier
    """
    provider, _rule, _version = _setup_high_tier_provider(
        api, npi="NPI-B7B", edit_code="MON-DENY-2")
    assert get_abrasion_profile(provider["id"])["monitor_only"] is True

    claim = screen_one_line_claim(provider["id"], billed=40000,
                                  claim_number="B74", member_id="M-B74")
    assert claim["status"] == "READY_TO_PAY"
    assert claim["allowed_amount_cents"] == 40000
    assert claim["denied_amount_cents"] == 0

    hits = list_claim_hits(claim["id"])
    assert len(hits) == 1, "the firing edit is still recorded, monitor-only"
    assert hits[0]["applied"] is False
    assert hits[0]["attributed_savings_cents"] == 0
    assert list_claim_tasks(claim["id"]) == [], (
        "monitor-only hits create no review task"
    )


def test_attribution_internal_first_waterfall_zeroes_vendor_duplication(api):
    """PRD §3.4: "The remaining hits on the line are ordered with hits from
    `INTERNAL` edits before hits from `VENDOR` edits, then by the firing
    version's `effective_from` earliest first, then by the hit's own creation
    timestamp earliest first. Walking that order with a running total starting
    at zero, each hit's `attributed_savings_cents` is the lesser of its
    `expected_savings_cents` and the line's `billed_cents` minus the running
    total, never below zero, and the running total grows by that attribution."
    PRD §3.4: "A vendor hit on a line already fully denied by an internal edit
    is therefore attributed zero — savings are never double-counted, which is
    the `INTERNAL_FIRST` conflict policy in practice."
    PRD §3.4: "when the firing entry is a mirrored vendor edit the hit records
    that `vendor_edit_id` as well (internal hits leave it null)."

    Design: Corner/calculations/attribution_internal_first_waterfall_zeroes_vendor_duplication
    """
    provider = create_provider(npi="NPI-WF", name="Waterfall Prov")
    # Internal DENY edit ACTIVE.
    rule_i = create_edit_rule(edit_code="WF-INT", category="CODING",
                              source="INTERNAL")
    ver_i = create_edit_version(rule_i["id"])
    submit_version(ver_i["id"])
    approve_version(ver_i["id"], rule_i["version"])
    # Vendor DENY edit ACTIVE.
    rule_v = create_edit_rule(edit_code="WF-VEN", category="CODING",
                              source="VENDOR")
    ver_v = create_edit_version(rule_v["id"],
                                logic_expression="vendor deny line")
    submit_version(ver_v["id"])
    approve_version(ver_v["id"], rule_v["version"])
    # Vendor edit record mapped to the vendor rule as a duplicate.
    vendor_edit = get_success_data(api.create_vendor_edit(
        create_vendor_edit_payload(vendor_name="EditCorp",
                                   vendor_edit_key="EC-100"),
        ADMIN), expected_status=201)
    mapped = get_success_data(api.map_vendor_edit(
        vendor_edit["id"],
        map_vendor_edit_payload(rule_v["id"], "DUPLICATE"),
        make_analyst_headers("analyst-1")))
    assert mapped["mapped_edit_rule_id"] == rule_v["id"]

    claim = screen_one_line_claim(provider["id"], billed=50000,
                                  claim_number="WF1", member_id="M-WF1")
    assert claim["denied_amount_cents"] == 50000, (
        "50000 internal + 0 vendor — savings never double-counted"
    )

    hits_i, _m = validate_paginated(
        api.list_edit_hits(ADMIN, params={"edit_version_id": ver_i["id"]}))
    assert len(hits_i) == 1
    assert hits_i[0]["attributed_savings_cents"] == 50000
    assert hits_i[0]["vendor_edit_id"] is None

    hits_v, _m2 = validate_paginated(
        api.list_edit_hits(ADMIN, params={"edit_version_id": ver_v["id"]}))
    assert len(hits_v) == 1
    assert hits_v[0]["attributed_savings_cents"] == 0
    assert hits_v[0]["vendor_edit_id"] == vendor_edit["id"]


def test_vendor_edit_map_cross_reference(api):
    """PRD §3.3: "An ingested vendor edit starts with `comparison_status`
    `UNMAPPED` and `mapped_edit_rule_id` null."
    PRD §3.3: "mapping a vendor edit records the internal rule it relates to
    via `edit_rule_id` — stored as `mapped_edit_rule_id` — together with the
    analyst's verdict as `comparison_status`, either `DUPLICATE` (the vendor
    edit duplicates the internal rule) or `COMPLEMENTARY` (it adds genuinely
    new coverage)."
    PRD §3.3: "Vendor edits can be listed with optional `vendor_name`,
    `comparison_status`, and `mapped_edit_rule_id` filters"

    Design: Corner/endpoints/vendor_edit_map_cross_reference
    """
    rule = create_edit_rule(edit_code="VE-01", category="CODING",
                            source="VENDOR")
    vendor_edit = get_success_data(api.create_vendor_edit(
        create_vendor_edit_payload(vendor_name="EditCorp",
                                   vendor_edit_key="EC-200"),
        ADMIN), expected_status=201)
    assert vendor_edit["comparison_status"] == "UNMAPPED"
    assert vendor_edit["mapped_edit_rule_id"] is None

    mapped = validate_success(api.map_vendor_edit(
        vendor_edit["id"],
        map_vendor_edit_payload(rule["id"], "COMPLEMENTARY"),
        make_analyst_headers("analyst-1")))
    assert mapped["mapped_edit_rule_id"] == rule["id"]
    assert mapped["comparison_status"] == "COMPLEMENTARY"

    rows, meta = validate_paginated(api.list_vendor_edits(
        ADMIN, params={"comparison_status": "COMPLEMENTARY"}))
    assert meta["total_count"] == 1
    assert rows[0]["id"] == vendor_edit["id"]
