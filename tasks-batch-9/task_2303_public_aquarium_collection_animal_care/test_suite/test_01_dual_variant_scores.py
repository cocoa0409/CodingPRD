"""Two-variant scores: the sourcing score (§3.5) and the welfare index (§3.7).

Both calculations exist in two variants that read the same primary records and
must not be collapsed into one stored number: `PROVISIONAL` / `FINAL` for an
acquisition request's `sustainability_score`, and `ROLLING` / `AUDIT_SNAPSHOT`
for a specimen's `welfare_score`.
"""
from typing import Any, Dict

from test_helpers import (
    Builder,
    DIRECTOR_HEADERS,
    VET_HEADERS,
    assertions,
    make_director_headers,
    validate_paginated,
    validate_success,
)


# --------------------------------------------------------------------------
# Bespoke world builders for these two calculations
# --------------------------------------------------------------------------
def _instant_seconds(value: str) -> str:
    """An ISO-8601 UTC instant reduced to whole seconds for comparison."""
    text = value.replace("Z", "")
    if "." in text:
        text = text.split(".")[0]
    return text + "Z"


def _institutional_transfer_line(build: Builder, welfare_audit_score: float) -> Dict[str, Any]:
    """An APPROVED plan line plus a source institution and a fresh request.

    The species is `UNLISTED` and the source is not `WILD_COLLECTION`, so the
    request's `permit_required` is false and submission takes the
    `READY_FOR_CLEARANCE` road of §3.5.
    """
    plant = build.create_plant(redundancy_test_interval_days=90)
    exhibit = build.create_exhibit(plant)
    species = build.create_species(
        taxon_group="TELEOST",
        protection_status="UNLISTED",
        sustainability_rating="GREEN",
        bioload_units_per_specimen=12.0,
        base_quarantine_days=30,
        wild_take_quota_annual=4,
    )
    entry = build.create_plan_entry(
        exhibit, species, planned_count=2, sustainability_requirement="GREEN_ONLY"
    )
    build.plan_action(entry["id"], "APPROVE", headers=make_director_headers("dir-plan-approver"))
    institution = build.create_institution(
        accreditation_status="ACCREDITED",
        welfare_audit_score=welfare_audit_score,
        last_audit_at="2026-05-01T00:00:00Z",
    )
    request = build.create_acquisition(
        entry,
        source_type="INSTITUTIONAL_TRANSFER",
        requested_count=1,
        source_institution_id=institution["id"],
    )
    return {"species": species, "entry": entry, "institution": institution, "request": request}


def _specimen_on_exhibit_with_five_records(build: Builder) -> Dict[str, Any]:
    """One specimen `ON_EXHIBIT` carrying five husbandry records.

    Three `FEEDING` records fall on the three distinct calendar dates
    2026-09-11, 2026-09-12 and 2026-09-13 with appetite scores 4, 5 and 3, and
    two `BEHAVIOR` records carry `NORMAL` and `LETHARGIC`. All five sit inside
    the 14 days ending at 2026-09-15T00:00:00Z (§3.7).
    """
    world = build.specimen_on_exhibit(plant_overrides={"redundancy_test_interval_days": 90})
    specimen_id = world["specimen"]["id"]
    build.advance_to("2026-09-14T12:00:00Z")
    build.log_feeding(specimen_id, appetite_score=4, logged_at="2026-09-11T09:00:00Z", feed_grams=120.0)
    build.log_feeding(specimen_id, appetite_score=5, logged_at="2026-09-12T09:00:00Z", feed_grams=150.0)
    build.log_behavior(specimen_id, "NORMAL", logged_at="2026-09-12T15:00:00Z")
    build.log_feeding(specimen_id, appetite_score=3, logged_at="2026-09-13T09:00:00Z", feed_grams=90.0)
    build.log_behavior(specimen_id, "LETHARGIC", logged_at="2026-09-14T09:00:00Z")
    return world


# --------------------------------------------------------------------------
# The sourcing score: PROVISIONAL at creation, FINAL at clearance
# --------------------------------------------------------------------------
def test_final_sourcing_score_re_reads_the_downgraded_source_institution_welfare(build, api):
    """Clearance recomputes the institution component from the current welfare audit.

    PRD §3.5: "The `FINAL` variant also re-reads the source institution's
    current `welfare_audit_score`, so an institution whose welfare audit
    deteriorated between drafting and clearance drags the score down."

    Design: Difficulty/dual_variant_calc/dual_variant_sustainability_provisional_then_final_after_receiver_downgrade
    """
    world = _institutional_transfer_line(build, welfare_audit_score=88.00)
    request = world["request"]

    # §3.5 PROVISIONAL: rating GREEN 40.0 + source INSTITUTIONAL_TRANSFER 22.0
    # + institution 0.25 * 88.00 = 22.0 -> min(100, 84.0) - 0.0 (UNLISTED) = 84.00.
    assertions.assert_acquisition_request(request)
    assert request["sustainability_score"] == 84.00
    assert request["sustainability_score_variant"] == "PROVISIONAL"

    submitted = build.submit_acquisition(request["id"])
    # §3.5: permit_required false, so the request takes the permit-free road and
    # `permit_deadline_at` stays null — the branch discriminator.
    assert submitted["status"] == "READY_FOR_CLEARANCE"
    assert submitted["permit_required"] is False
    assert submitted["permit_deadline_at"] is None

    downgraded = validate_success(
        api.update_institution(
            world["institution"]["id"],
            {"welfare_audit_score": 60.00, "last_audit_at": "2026-08-01T00:00:00Z"},
            DIRECTOR_HEADERS,
        )
    )
    # §2.9: eligibility needs a score of at least 70.0, so 60.00 loses it.
    assert downgraded["welfare_audit_score"] == 60.00
    assert downgraded["is_receiving_eligible"] is False

    cleared = build.clear_acquisition(
        request["id"], world["species"]["id"], user_id="dir-clearance-officer"
    )

    # §3.5 FINAL on the READY_FOR_CLEARANCE road: 40.0 + 22.0 + 0.25 * 60.00
    # = 77.0; no permit bonus (no permit was ever consulted) and no quota
    # pressure (the source is not WILD_COLLECTION) -> 77.00. Re-labelling the
    # stored PROVISIONAL number would answer 84.00; the delta is exactly
    # 0.25 * (88.00 - 60.00) = 7.00.
    assert cleared["status"] == "CLEARED"
    assert cleared["sustainability_score"] == 77.00
    assert cleared["sustainability_score_variant"] == "FINAL"
    assert cleared["cleared_by_user_id"] == "dir-clearance-officer"
    assert _instant_seconds(cleared["cleared_at"]) == "2026-08-01T00:00:00Z"

    # §3.5: quota is reserved for a WILD_COLLECTION source only, so this
    # institutional transfer reserves nothing against the species' pool of 4.
    assert cleared["quota_units_reserved"] == 0

    stored = build.get_acquisition(request["id"])
    assert stored["sustainability_score"] == 77.00
    assert stored["sustainability_score_variant"] == "FINAL"

    species = build.get_species(world["species"]["id"])
    assert species["wild_take_quota_reserved"] == 0


def test_final_sourcing_score_rises_when_the_source_institution_is_re_audited_upwards(build, api):
    """The same re-read lifts the score when the welfare audit improves.

    PRD §3.5: "Both add an institution component: a flat 20.0 when
    `source_institution_id` is null, and otherwise 0.25 multiplied by the source
    institution's `welfare_audit_score`."

    Design: Difficulty/dual_variant_calc/dual_variant_sustainability_provisional_then_final_after_receiver_downgrade
    """
    world = _institutional_transfer_line(build, welfare_audit_score=88.00)
    request = world["request"]

    # §3.5 PROVISIONAL: 40.0 + 22.0 + 0.25 * 88.00 = 84.00.
    assert request["sustainability_score"] == 84.00
    assert request["sustainability_score_variant"] == "PROVISIONAL"

    build.submit_acquisition(request["id"])

    upgraded = validate_success(
        api.update_institution(
            world["institution"]["id"],
            {"welfare_audit_score": 96.00, "last_audit_at": "2026-08-01T00:00:00Z"},
            DIRECTOR_HEADERS,
        )
    )
    assert upgraded["welfare_audit_score"] == 96.00
    assert upgraded["is_receiving_eligible"] is True

    cleared = build.clear_acquisition(
        request["id"], world["species"]["id"], user_id="dir-clearance-officer"
    )

    # §3.5 FINAL: 40.0 + 22.0 + 0.25 * 96.00 = 86.0 -> min(100, 86.0) - 0.0
    # = 86.00. An implementation that stored the creation-time institution
    # component would still answer 84.00 here, in the opposite direction to the
    # downgrade case, so only a genuine re-read satisfies both.
    assert cleared["sustainability_score"] == 86.00
    assert cleared["sustainability_score_variant"] == "FINAL"

    stored = build.get_acquisition(request["id"])
    assert stored["sustainability_score"] == 86.00
    assert stored["sustainability_score_variant"] == "FINAL"


# --------------------------------------------------------------------------
# The welfare index: ROLLING on append, AUDIT_SNAPSHOT inside an inspection
# --------------------------------------------------------------------------
def test_rolling_welfare_index_averages_appetite_over_the_five_record_window(build, api):
    """Appending husbandry records scores the specimen under the ROLLING variant.

    PRD §3.7: "Its feeding component is the mean `appetite_score` over the
    `FEEDING` records in the window multiplied by 8.0, and 0 when the window
    holds no feeding records."

    Design: Difficulty/dual_variant_calc/dual_variant_welfare_rolling_then_audit_snapshot_on_identical_logs
    """
    world = _specimen_on_exhibit_with_five_records(build)
    specimen = build.get_specimen(world["specimen"]["id"])

    # §3.7 ROLLING over the 5 most recent FEEDING/BEHAVIOR records — all five:
    # feeding mean (4 + 5 + 3) / 3 = 4.0, times 8.0 = 32.0; behaviour mean
    # (NORMAL 10.0 + LETHARGIC 4.0) / 2 = 7.0; base 40.0; no OPEN TREATMENT
    # case, so no 6.0 penalty -> 40.0 + 32.0 + 7.0 = 79.00.
    assertions.assert_specimen(specimen)
    assert specimen["welfare_score"] == 79.00
    assert specimen["welfare_score_variant"] == "ROLLING"

    # §3.7: the penalty is charged per veterinary case whose status is OPEN and
    # whose case_type is TREATMENT; this animal carries none.
    open_cases, open_meta = validate_paginated(
        api.list_specimen_veterinary_cases(specimen["id"], VET_HEADERS, params={"status": "OPEN"})
    )
    assert open_meta["total_count"] == 0
    assert open_cases == []

    logs, logs_meta = validate_paginated(
        api.list_husbandry_logs(specimen["id"], VET_HEADERS)
    )
    assert logs_meta["total_count"] == 5
    assert len(logs) == 5


def test_audit_snapshot_welfare_index_divides_the_same_records_by_the_fourteen_day_window(build, api):
    """An inspection re-scores the identical records under AUDIT_SNAPSHOT.

    PRD §3.7: "Its feeding component is not a mean over records but a mean over
    days: the sum of `appetite_score` across the `FEEDING` records in the
    window, divided by 14, multiplied by 8.0."

    Design: Difficulty/dual_variant_calc/dual_variant_welfare_rolling_then_audit_snapshot_on_identical_logs
    """
    world = _specimen_on_exhibit_with_five_records(build)
    specimen_id = world["specimen"]["id"]

    before = build.get_specimen(specimen_id)
    # §3.7 ROLLING, as stamped by the fifth append: 40.0 + 4.0 * 8.0 + 7.0 = 79.00.
    assert before["welfare_score"] == 79.00
    assert before["welfare_score_variant"] == "ROLLING"

    build.advance_to("2026-09-15T00:00:00Z")
    audit = build.schedule_audit(scheduled_for="2026-09-15T00:00:00Z")
    started = build.progress_audit(
        audit["id"], "START", headers=make_director_headers("dir-audit-opener")
    )

    assert started["status"] == "IN_PROGRESS"
    assert started["opened_by_user_id"] == "dir-audit-opener"

    rescored = build.get_specimen(specimen_id)
    # §3.7 AUDIT_SNAPSHOT over the 14 days ending 2026-09-15T00:00:00Z, which
    # holds all five records: feeding (4 + 5 + 3) / 14 * 8.0 = 6.857142857...;
    # behaviour mean (10.0 + 4.0) / 2 = 7.0; feedings fall on 3 distinct dates,
    # so 14 - 3 = 11 missing days cost 3.0 each = 33.0. Raw
    # 40.0 + 6.857142857... + 7.0 - 33.0 = 20.857142857... -> 20.86. The same
    # five rows scored 79.00 under ROLLING: the two variants disagree by 58.14.
    assert rescored["welfare_score"] == 20.86
    assert rescored["welfare_score_variant"] == "AUDIT_SNAPSHOT"

    # §3.9: step two reads the values step one has just written, so the
    # animal-health domain carries the snapshot figure, never the rolling one.
    assert started["domain_subscores"]["ANIMAL_HEALTH"] == 20.86

    # §3.7: a husbandry record "is never modified after it is written"; the
    # re-score adds nothing to the log.
    logs, logs_meta = validate_paginated(
        api.list_husbandry_logs(specimen_id, VET_HEADERS)
    )
    assert logs_meta["total_count"] == 5
    assert len(logs) == 5

    stored_audit = validate_success(api.get_accreditation_audit(audit["id"], DIRECTOR_HEADERS))
    assert stored_audit["domain_subscores"]["ANIMAL_HEALTH"] == 20.86
