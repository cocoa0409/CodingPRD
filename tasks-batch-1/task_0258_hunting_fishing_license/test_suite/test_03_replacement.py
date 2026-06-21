"""Replacing a lost/damaged/stolen credential: admin-fee calculation, the void revert,
the void→re-link cascade, bag-budget conservation, and immediate consistency.

PRD §3.10 governs replacements.
"""
from test_helpers import (
    validate_success, assert_replacement, assert_license,
    create_resident_applicant, create_nonresident_applicant,
    create_product, create_season, create_tag_product_for_season,
    issue_otc_license, submit_harvest, setup_resident_with_tag_license,
    set_clock, create_replacement_payload, create_harvest_report_payload,
    make_applicant_headers, TEST_USERS,
)

AGENT = TEST_USERS["license_agent_headers"]
OFFICER = TEST_USERS["draw_officer_headers"]


def test_replacement_fee_tag_lost_resident(api):
    """PRD §3.10: "Otherwise the fee starts from a replacement base of 1500 cents; if the
    original product's `product_kind` is `TAG`, a tag-replacement surcharge of 1000 cents is
    added; and if the holder's `residency_status` is `NONRESIDENT`, a non-resident replacement
    surcharge of 500 cents is added."

    Design: Difficulty/combinatorial_formula/replacement_fee_three_input_conditional_branches
    """
    set_clock("2026-02-01T00:00:00Z")
    season = create_season(species="ELK", bag_limit=1, draw_required=False, open_it=True)
    product = create_tag_product_for_season(season["id"], sku="TAG-ELK-OTC",
                                            base_fee_cents=4500)
    applicant = create_resident_applicant(full_name="A Res", declared_state_code="MT")
    license_ = issue_otc_license(applicant["id"], product["id"])

    res = api.create_replacement(
        create_replacement_payload(license_["id"], reason="LOST"), AGENT)
    replacement = validate_success(res, 201)
    assert_replacement(replacement)
    # TAG + LOST + RESIDENT -> 1500 base + 1000 TAG surcharge = 2500.
    assert replacement["admin_fee_cents"] == 2500, (
        f"TAG+LOST+RESIDENT admin fee should be 2500, got {replacement['admin_fee_cents']}")


def test_replacement_fee_stolen_short_circuits_to_zero(api):
    """PRD §3.10: "A stolen-credential replacement is fully waived: when the `reason` is
    `STOLEN`, the `admin_fee_cents` is 0 and no surcharges apply (this short-circuits the rest
    of the calculation)."

    Design: Difficulty/combinatorial_formula/replacement_fee_three_input_conditional_branches
    """
    set_clock("2026-02-01T00:00:00Z")
    season = create_season(species="ELK", bag_limit=1, draw_required=False, open_it=True)
    product = create_tag_product_for_season(season["id"], sku="TAG-ELK-OTC",
                                            base_fee_cents=4500)
    applicant = create_resident_applicant(full_name="A Res", declared_state_code="MT")
    license_ = issue_otc_license(applicant["id"], product["id"])

    res = api.create_replacement(
        create_replacement_payload(license_["id"], reason="STOLEN"), AGENT)
    replacement = validate_success(res, 201)
    # STOLEN on a TAG: surcharge is overridden, fee is 0.
    assert replacement["admin_fee_cents"] == 0, (
        f"STOLEN replacement must be waived to 0 regardless of the TAG surcharge, got "
        f"{replacement['admin_fee_cents']}")


def test_replacement_fee_license_lost_nonresident(api):
    """PRD §3.10: "Otherwise the fee starts from a replacement base of 1500 cents; if the
    original product's `product_kind` is `TAG`, a tag-replacement surcharge of 1000 cents is
    added; and if the holder's `residency_status` is `NONRESIDENT`, a non-resident replacement
    surcharge of 500 cents is added."

    Design: Corner/calculations/replacement_fee_license_lost_nonresident
    """
    set_clock("2026-02-01T00:00:00Z")
    product = create_product(sku="LIC-FISH", product_kind="LICENSE",
                             base_fee_cents=4500, residency_restriction="ANY")
    applicant = create_nonresident_applicant(full_name="A NR", declared_state_code="CA")
    license_ = issue_otc_license(applicant["id"], product["id"])

    res = api.create_replacement(
        create_replacement_payload(license_["id"], reason="LOST"), AGENT)
    replacement = validate_success(res, 201)
    # LICENSE (no TAG surcharge) + LOST + NONRESIDENT -> 1500 + 500 = 2000.
    assert replacement["admin_fee_cents"] == 2000, (
        f"LICENSE+LOST+NONRESIDENT admin fee should be 2000, got "
        f"{replacement['admin_fee_cents']}")


def test_replacement_fee_stolen_waived_corner(api):
    """PRD §3.10: "A stolen-credential replacement is fully waived: when the `reason` is
    `STOLEN`, the `admin_fee_cents` is 0 and no surcharges apply (this short-circuits the rest
    of the calculation)."

    Design: Corner/calculations/replacement_fee_stolen_waived_to_zero
    """
    set_clock("2026-02-01T00:00:00Z")
    season = create_season(species="ELK", bag_limit=1, draw_required=False, open_it=True)
    product = create_tag_product_for_season(season["id"], sku="TAG-ELK-OTC",
                                            base_fee_cents=4500)
    applicant = create_resident_applicant(full_name="A Res", declared_state_code="MT")
    license_ = issue_otc_license(applicant["id"], product["id"])

    res = api.create_replacement(
        create_replacement_payload(license_["id"], reason="STOLEN"), AGENT)
    replacement = validate_success(res, 201)
    assert replacement["admin_fee_cents"] == 0


def test_replacement_voids_original_and_supersedes(api):
    """PRD §3.10: "The original license is then voided: its `status` moves `ISSUED → VOIDED` and its `superseded_by_id` is set to the replacement license."

    Design: Difficulty/non_linear_state_machine/license_issued_to_voided_revert_on_replacement
    """
    set_clock("2026-02-01T00:00:00Z")
    product = create_product(sku="STAMP-DUCK", product_kind="STAMP",
                             base_fee_cents=4500, residency_restriction="ANY")
    applicant = create_resident_applicant(full_name="A Res", declared_state_code="MT")
    original = issue_otc_license(applicant["id"], product["id"])

    res = api.create_replacement(
        create_replacement_payload(original["id"], reason="DAMAGED"), AGENT)
    replacement = validate_success(res, 201)
    repl_lic_id = replacement["replacement_license_id"]

    voided = validate_success(api.get_license(original["id"], OFFICER), 200)
    assert voided["status"] == "VOIDED"
    assert voided["superseded_by_id"] == repl_lic_id
    new_license = validate_success(api.get_license(repl_lic_id, OFFICER), 200)
    assert new_license["status"] == "ISSUED"


def test_replacement_new_license_carries_zero_fee(api):
    """PRD §3.10: "A replacement is not a re-purchase: the holder pays only the
    duplicate-issuance administrative fee recorded as `admin_fee_cents`, and the newly minted
    credential carries a `fee_charged_cents` of 0."

    Design: Difficulty/non_linear_state_machine/license_issued_to_voided_revert_on_replacement
    """
    set_clock("2026-02-01T00:00:00Z")
    product = create_product(sku="STAMP-DUCK", product_kind="STAMP",
                             base_fee_cents=4500, residency_restriction="ANY")
    applicant = create_resident_applicant(full_name="A Res", declared_state_code="MT")
    original = issue_otc_license(applicant["id"], product["id"])

    replacement = validate_success(api.create_replacement(
        create_replacement_payload(original["id"], reason="DAMAGED"), AGENT), 201)
    new_license = validate_success(
        api.get_license(replacement["replacement_license_id"], OFFICER), 200)
    assert_license(new_license)
    assert new_license["fee_charged_cents"] == 0


def test_replacement_relinks_open_harvest_reports(api):
    """PRD §3.10: "every `HarvestReport` filed under the original license that is still in `SUBMITTED` status is migrated to point at the replacement license, so that quantities already committed against the season continue to count under the new credential."

    Design: Difficulty/transitive_cascade/replacement_depth2_cascade_void_relink_harvest
    """
    set_clock("2026-09-15T00:00:00Z")
    season = create_season(species="ELK", season_open="2026-09-01T00:00:00Z",
                           season_close="2026-10-01T00:00:00Z", bag_limit=2,
                           draw_required=False, open_it=True)
    product = create_tag_product_for_season(season["id"], sku="TAG-ELK-OTC",
                                            base_fee_cents=4500)
    applicant = create_resident_applicant(full_name="A Res", declared_state_code="MT")
    original = issue_otc_license(applicant["id"], product["id"])
    report = submit_harvest(original["id"], applicant["id"],
                            harvest_datetime="2026-09-15T08:00:00Z", quantity=1)

    replacement = validate_success(api.create_replacement(
        create_replacement_payload(original["id"], reason="LOST"), AGENT), 201)
    repl_lic_id = replacement["replacement_license_id"]

    voided = validate_success(api.get_license(original["id"], OFFICER), 200)
    assert voided["status"] == "VOIDED"
    migrated = validate_success(api.get_harvest_report(report["id"], OFFICER), 200)
    assert migrated["license_id"] == repl_lic_id, (
        "the SUBMITTED harvest report must be re-linked to the replacement license")
    assert migrated["status"] == "SUBMITTED"


def test_replacement_conserves_bag_budget(api):
    """PRD §3.10: "the original's open harvest budget is preserved by re-linking: every `HarvestReport` filed under the original license that is still in `SUBMITTED` status is migrated to point at the replacement license, so that quantities already committed against the season continue to count under the new credential."

    Design: Difficulty/compensating_invariant/replacement_conserves_bag_budget_counted_quantity
    """
    set_clock("2026-09-15T00:00:00Z")
    season = create_season(species="ELK", season_open="2026-09-01T00:00:00Z",
                           season_close="2026-10-01T00:00:00Z", bag_limit=2,
                           draw_required=False, open_it=True)
    product = create_tag_product_for_season(season["id"], sku="TAG-ELK-OTC",
                                            base_fee_cents=4500)
    applicant = create_resident_applicant(full_name="A Res", declared_state_code="MT")
    original = issue_otc_license(applicant["id"], product["id"])
    report = submit_harvest(original["id"], applicant["id"],
                            harvest_datetime="2026-09-15T08:00:00Z", quantity=1)

    replacement = validate_success(api.create_replacement(
        create_replacement_payload(original["id"], reason="LOST"), AGENT), 201)
    repl_lic_id = replacement["replacement_license_id"]

    budget = validate_success(api.get_bag_budget(repl_lic_id, OFFICER), 200)
    assert budget["counted"] == 1, (
        f"counted quantity must be conserved at 1 across the replacement, got "
        f"{budget['counted']}")
    assert budget["remaining"] == 1
    migrated = validate_success(api.get_harvest_report(report["id"], OFFICER), 200)
    assert migrated["license_id"] == repl_lic_id


def test_replacement_voids_original_link_to_replacement(api):
    """PRD §3.10: "every `HarvestReport` filed under the original license that is still in `SUBMITTED` status is migrated to point at the replacement license".

    Design: Difficulty/transitive_cascade/replacement_depth2_cascade_void_relink_harvest
    """
    set_clock("2026-09-15T00:00:00Z")
    season = create_season(species="ELK", season_open="2026-09-01T00:00:00Z",
                           season_close="2026-10-01T00:00:00Z", bag_limit=2,
                           draw_required=False, open_it=True)
    product = create_tag_product_for_season(season["id"], sku="TAG-ELK-OTC",
                                            base_fee_cents=4500)
    applicant = create_resident_applicant(full_name="A Res", declared_state_code="MT")
    original = issue_otc_license(applicant["id"], product["id"])
    report = submit_harvest(original["id"], applicant["id"],
                            harvest_datetime="2026-09-15T08:00:00Z", quantity=1)

    replacement = validate_success(api.create_replacement(
        create_replacement_payload(original["id"], reason="LOST"), AGENT), 201)
    # The void cascade migrates the SUBMITTED report away from the now-VOIDED original.
    migrated = validate_success(api.get_harvest_report(report["id"], OFFICER), 200)
    assert migrated["license_id"] != original["id"], (
        "the SUBMITTED report must no longer point at the voided original license")
    assert migrated["license_id"] == replacement["replacement_license_id"]


def test_replacement_conserves_budget_on_original_voided(api):
    """PRD §3.10: "so that quantities already committed against the season continue to count
    under the new credential."

    Design: Difficulty/compensating_invariant/replacement_conserves_bag_budget_counted_quantity
    """
    set_clock("2026-09-15T00:00:00Z")
    season = create_season(species="ELK", season_open="2026-09-01T00:00:00Z",
                           season_close="2026-10-01T00:00:00Z", bag_limit=2,
                           draw_required=False, open_it=True)
    product = create_tag_product_for_season(season["id"], sku="TAG-ELK-OTC",
                                            base_fee_cents=4500)
    applicant = create_resident_applicant(full_name="A Res", declared_state_code="MT")
    original = issue_otc_license(applicant["id"], product["id"])
    submit_harvest(original["id"], applicant["id"],
                   harvest_datetime="2026-09-15T08:00:00Z", quantity=1)

    replacement = validate_success(api.create_replacement(
        create_replacement_payload(original["id"], reason="LOST"), AGENT), 201)
    repl_lic_id = replacement["replacement_license_id"]
    # Budget conserved at exactly 1 (not doubled to 2, not zeroed): one more unit is
    # admissible under the replacement, two more would exceed.
    res_ok = api.create_harvest_report(
        create_harvest_report_payload(repl_lic_id,
                                      harvest_datetime="2026-09-16T08:00:00Z", quantity=1),
        make_applicant_headers(applicant["id"]))
    accepted = validate_success(res_ok, 201)
    assert accepted["status"] == "SUBMITTED"
    budget = validate_success(api.get_bag_budget(repl_lic_id, OFFICER), 200)
    assert budget["counted"] == 2
    assert budget["remaining"] == 0


def test_replacement_changes_visible_same_response(api):
    """PRD §3.10: "The system computes the `admin_fee_cents`, mints a replacement `License` for
    the same product and applicant — copying the original's `draw_application_id`, marking
    `issued_via` as `OVER_THE_COUNTER`, and setting its `fee_charged_cents` to 0 — and records
    that new license as the replacement's `replacement_license_id`."
    PRD §3.10: "The original license is then voided: its `status` moves `ISSUED → VOIDED` and
    its `superseded_by_id` is set to the replacement license."

    Design: Corner/consistency_model/replacement_changes_visible_same_response
    """
    set_clock("2026-02-01T00:00:00Z")
    product = create_product(sku="STAMP-DUCK", product_kind="STAMP",
                             base_fee_cents=4500, residency_restriction="ANY")
    applicant = create_resident_applicant(full_name="A Res", declared_state_code="MT")
    original = issue_otc_license(applicant["id"], product["id"])

    replacement = validate_success(api.create_replacement(
        create_replacement_payload(original["id"], reason="DAMAGED"), AGENT), 201)
    assert replacement["replacement_license_id"] is not None
    # Original already VOIDED in the same atomic request.
    voided = validate_success(api.get_license(original["id"], OFFICER), 200)
    assert voided["status"] == "VOIDED"
