"""The sealed lottery: creation gates, the SEAL snapshot, seeded base rank,
preference tiers, effective rank, void cascades, and OCC on creation."""
import hashlib

from test_helpers import (
    ApiErrorId, fixtures, get_success_data, make_lottery_administrator_headers,
    validate_error,
)

DEVELOPER = fixtures.DEVELOPER
LOTTERY_ADMIN = fixtures.LOTTERY_ADMIN


def test_lottery_create_requires_closed_campaign(api):
    """PRD §3.5: "a `LotteryAdministrator` creates a lottery run against the
    `CLOSED` campaign". PRD §2.10: "all other state violations yield the
    generic `ERR_INVALID_STATE`."

    Design: Corner/state_machines/lottery_create_requires_closed_campaign
    """
    prop = fixtures.new_property(api)
    campaign = fixtures.new_open_campaign(api, prop["id"])
    version = fixtures.campaign_version(api, campaign["id"])
    resp = api.create_lottery_run(
        fixtures.create_lottery_run_payload(campaign["id"], version,
                                            seed="SEED-EARLY"),
        LOTTERY_ADMIN)
    # The OCC guard passes (version is fresh); the rejection is purely the
    # campaign-state gate — the campaign is OPEN, not CLOSED.
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_seal_snapshot_excludes_late_verified_application(api):
    """PRD §3.5: "recording `sealed_by` and `sealed_at`, and snapshotting
    `eligible_application_count` as the number of the campaign's applications
    in `VERIFIED` status at that exact instant." PRD §3.5: "on success the run
    moves from `SEALED` to `EXECUTED`, stamps `executed_by` and `executed_at`,
    and generates one waitlist entry per snapshotted application"."

    Design: Corner/state_machines/seal_snapshot_excludes_late_verified_application
    """
    prop = fixtures.new_property(api)
    campaign = fixtures.new_open_campaign(api, prop["id"])
    applicant_a, app_a = fixtures.new_verified_application(
        api, campaign["id"], full_name="Uma U", email="u@x.com")
    applicant_b = fixtures.new_applicant(api, full_name="Vic V",
                                         email="v@x.com")
    app_b = fixtures.submit_application(api, campaign["id"], applicant_b["id"],
                                        household_size=1,
                                        self_reported_annual_income_cents=2500000)
    fixtures.review_action(api, app_b["id"], "BEGIN_REVIEW", fixtures.CLERK)

    fixtures.close_campaign_at(api, campaign["id"])
    run = fixtures.new_lottery_run(api, campaign["id"], seed="SEED-SNAP")
    sealed = fixtures.lottery_action(api, run["id"], "SEAL")
    assert sealed["eligible_application_count"] == 1

    # Verified after the seal — outside the frozen snapshot.
    fixtures.review_action(api, app_b["id"], "COMPLETE_VERIFICATION",
                           fixtures.CLERK)
    executed = fixtures.lottery_action(api, run["id"], "EXECUTE")
    assert executed["entries_generated"] == 1
    fixtures.lottery_action(api, run["id"], "PUBLISH")
    entries = fixtures.list_entries(api, lottery_run_id=run["id"])
    assert len(entries) == 1
    assert entries[0]["application_id"] == app_a["id"]
    campaign = fixtures.get_campaign(api, campaign["id"])
    assert campaign["status"] == "LOTTERY_COMPLETED"


def test_void_published_run_cascades_without_refusal_increment(api):
    """PRD §3.5: "Voiding an `EXECUTED` run cascades: every entry of the run
    in `RANKED` or `OFFERED` status is removed with `removal_reason`
    `LOTTERY_VOIDED` and `removed_at` stamped; every `PENDING` offer of those
    entries is voided without incrementing any `refusal_count`, and the units
    those offers held return from `RESERVED` to `AVAILABLE`". PRD §3.5:
    "Voiding a `PUBLISHED` run performs the same cascade and additionally
    flips the campaign from `LOTTERY_COMPLETED` or `LEASING` back to
    `CLOSED`."

    Design: Corner/state_machines/void_published_run_cascades_without_refusal_increment
    """
    world = fixtures.setup_leasing_with_pending_offer(api, seed="SEED-VOID")
    offer = world["offers"][0]
    unit = world["units"][0]

    voided = fixtures.lottery_action(api, world["run"]["id"], "VOID",
                                     void_reason="funding agency audit finding")
    assert voided["status"] == "VOIDED"

    entry = get_success_data(
        api.get_waitlist_entry(offer["entry_id"], LOTTERY_ADMIN))
    assert entry["status"] == "REMOVED"
    assert entry["removal_reason"] == "LOTTERY_VOIDED"
    assert entry["refusal_count"] == 0, "a void is not a refusal"
    offer_after = get_success_data(api.get_offer(offer["id"], LOTTERY_ADMIN))
    assert offer_after["status"] == "VOIDED"
    unit_after = get_success_data(api.get_unit(unit["id"], DEVELOPER))
    assert unit_after["status"] == "AVAILABLE"
    campaign = fixtures.get_campaign(api, world["campaign"]["id"])
    assert campaign["status"] == "CLOSED"


def test_lottery_base_rank_matches_seeded_hash_order(api):
    """PRD §3.5: "for each snapshotted application, the server computes the
    SHA-256 hex digest of the UTF-8 string formed by the `seed`, a colon, and
    the application's `confirmation_code`; applications are ordered by that
    digest compared lexicographically ascending, with the application's
    `created_at` ascending breaking any theoretical hash tie, and `base_rank`
    is the 1-based position in that order."

    Design: Corner/calculations/lottery_base_rank_matches_seeded_hash_order
    """
    prop = fixtures.new_property(api)
    campaign = fixtures.new_open_campaign(api, prop["id"])
    codes = {}
    for name, hh, income in (("Hana H", 2, 3_000_000), ("Ivan I", 1, 2_500_000),
                             ("Jae J", 3, 3_500_000)):
        applicant = fixtures.new_applicant(api, full_name=name)
        application = fixtures.submit_application(
            api, campaign["id"], applicant["id"], household_size=hh,
            self_reported_annual_income_cents=income)
        codes[application["id"]] = application["confirmation_code"]
        fixtures.verify_application(api, application["id"])
    fixtures.close_campaign_at(api, campaign["id"])
    run = fixtures.new_lottery_run(api, campaign["id"], seed="SEED-HASH")
    fixtures.lottery_action(api, run["id"], "SEAL")
    executed = fixtures.lottery_action(api, run["id"], "EXECUTE")
    assert executed["entries_generated"] == 3

    expected_order = sorted(
        codes,
        key=lambda app_id: hashlib.sha256(
            f"SEED-HASH:{codes[app_id]}".encode("utf-8")).hexdigest(),
    )
    for position, app_id in enumerate(expected_order, start=1):
        entry = fixtures.get_entry_for_application(api, app_id)
        assert entry["preference_tier"] == 4, "no verified claims"
        assert entry["base_rank"] == position, (
            f"base_rank must follow ascending sha256_hex('SEED-HASH:' + "
            f"confirmation_code); entry {entry['id']} expected {position}"
        )
        # All tiers equal, so the effective order is the lottery order.
        assert entry["effective_rank"] == position


def test_preference_tier_branching_local_beats_veteran(api):
    """PRD §3.5: "The preference tier is a combinatorial read of the
    application's verified claims: tier 1 if any claim is currently `VERIFIED`
    in the `LOCAL_RESIDENT` category, otherwise tier 2 for a verified
    `VETERAN` claim, otherwise tier 3 for a verified `ACCESSIBILITY` claim,
    otherwise tier 4".

    Design: Difficulty/combinatorial_formula/preference_tier_branching_local_beats_veteran
    """
    world = fixtures.setup_leasing_pipeline(
        api, seed="SEED-TIER", num_units=0, certify=False,
        applications=[
            {"full_name": "Ann A", "email": "a@x.com",
             "claims": [("LOCAL_RESIDENT", "lease-2025", "VERIFY"),
                        ("VETERAN", "dd214", "VERIFY")]},
            {"full_name": "Bob B", "email": "b@x.com", "household_size": 1,
             "self_reported_annual_income_cents": 2_500_000,
             "claims": [("ACCESSIBILITY", "mobility-cert", "VERIFY")]},
            {"full_name": "Cid C", "email": "c@x.com", "household_size": 3,
             "self_reported_annual_income_cents": 3_500_000},
        ])
    tiers = {}
    for application in world["applications"]:
        entry = fixtures.get_entry_for_application(api, application["id"])
        tiers[application["id"]] = entry["preference_tier"]
    app_a, app_b, app_c = [a["id"] for a in world["applications"]]
    assert tiers[app_a] == 1, "LOCAL_RESIDENT preempts VETERAN"
    assert tiers[app_b] == 3, "ACCESSIBILITY-only branch"
    assert tiers[app_c] == 4, "no verified claims"
    assert world["run"]["entries_generated"] == 3


def test_effective_rank_groups_strictly_by_tier(api):
    """PRD §3.5: "The effective rank then orders the snapshot by
    `preference_tier` ascending, then `base_rank` ascending, then the
    application's `created_at` ascending, and `effective_rank` is the 1-based
    position in that final order."

    Design: Difficulty/combinatorial_formula/preference_tier_branching_local_beats_veteran
    """
    world = fixtures.setup_leasing_pipeline(
        api, seed="SEED-TIER", num_units=0, certify=False,
        applications=[
            {"full_name": "Ann A", "email": "a@x.com",
             "claims": [("LOCAL_RESIDENT", "lease-2025", "VERIFY"),
                        ("VETERAN", "dd214", "VERIFY")]},
            {"full_name": "Bob B", "email": "b@x.com", "household_size": 1,
             "self_reported_annual_income_cents": 2_500_000,
             "claims": [("ACCESSIBILITY", "mobility-cert", "VERIFY")]},
            {"full_name": "Cid C", "email": "c@x.com", "household_size": 3,
             "self_reported_annual_income_cents": 3_500_000},
        ])
    ranks = {}
    for application in world["applications"]:
        entry = fixtures.get_entry_for_application(api, application["id"])
        ranks[application["id"]] = entry["effective_rank"]
    app_a, app_b, app_c = [a["id"] for a in world["applications"]]
    # Strict tier grouping, independent of the sha256 base_rank order.
    assert (ranks[app_a], ranks[app_b], ranks[app_c]) == (1, 2, 3)


def test_second_lottery_run_blocked_while_active(api):
    """PRD §3.5: "the campaign must currently be `CLOSED` with no other
    lottery run of the same campaign still alive in `DRAFT`, `SEALED`,
    `EXECUTED`, or `PUBLISHED` status; a live sibling run triggers
    `ERR_ACTIVE_LOTTERY_EXISTS`."

    Design: Corner/endpoints/second_lottery_run_blocked_while_active_returns_active_lottery_exists
    """
    prop = fixtures.new_property(api)
    campaign = fixtures.new_open_campaign(api, prop["id"])
    fixtures.close_campaign_at(api, campaign["id"])
    run1 = fixtures.new_lottery_run(api, campaign["id"], seed="SEED-ONE")
    assert run1["status"] == "DRAFT"
    # Re-read after run1 bumped the campaign version: the OCC guard passes.
    fresh_version = fixtures.campaign_version(api, campaign["id"])
    resp = api.create_lottery_run(
        fixtures.create_lottery_run_payload(campaign["id"], fresh_version,
                                            seed="SEED-TWO"),
        LOTTERY_ADMIN)
    validate_error(resp, ApiErrorId.ERR_ACTIVE_LOTTERY_EXISTS)


def test_occ_lottery_create_stale_version_rejected(api):
    """PRD §2.6: "If that value does not equal the campaign's current
    `version` at the moment the write is attempted, the request is rejected
    with `ERR_STALE_VERSION` (HTTP 412). A prior successful lottery-run
    creation already advances the campaign's `version`, so a second creation
    carrying the older version is stale even where product semantics would
    otherwise let a new run supersede a draft"."

    Design: Corner/cross_cutting_layers/occ_lottery_create_stale_version_rejected
    """
    prop = fixtures.new_property(api)
    campaign = fixtures.new_open_campaign(api, prop["id"])
    fixtures.close_campaign_at(api, campaign["id"])
    stale_version = fixtures.campaign_version(api, campaign["id"])

    run1 = fixtures.new_lottery_run(api, campaign["id"], seed="SEED-A",
                                    expected_campaign_version=stale_version)
    assert run1["status"] == "DRAFT"

    resp = api.create_lottery_run(
        fixtures.create_lottery_run_payload(campaign["id"], stale_version,
                                            seed="SEED-B"),
        make_lottery_administrator_headers("lot-1"))
    # The campaign version advanced at run1's creation; the stale read is
    # rejected at the optimistic-concurrency stage.
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
