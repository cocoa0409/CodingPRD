"""Inclusive-versus-strict comparison boundaries.

Each boundary is probed twice: once with the input sitting exactly on the
threshold the PRD names, and once one representable step across it, so an
implementation that swaps `>` for `>=` (or the reverse) cannot pass both.
"""
from typing import Any, Dict

from test_helpers import (
    DIRECTOR_HEADERS,
    PERMIT_OFFICER_HEADERS,
    Builder,
    factories,
    shift,
    validate_error,
    validate_success,
)
from test_helpers.api_errors import ERR_RECEIVER_NOT_ELIGIBLE

# The two conditions the required set always contains for an ACCREDITED
# receiver taking an UNLISTED species with no treatment history (PRD §3.8).
REQUIRED_CONDITIONS = ["WATER_CHEMISTRY_MATCH", "TRANSPORT_OXYGEN_PLAN"]


def _ammonia_reading(build: Builder, plant: Dict[str, Any], ammonia: float) -> Dict[str, Any]:
    """Append a COLD_MARINE reading whose only deviation is its ammonia level.

    Temperature, salinity and pH sit on their targets, dissolved oxygen sits
    above its warn threshold and nitrite sits below 0.1, so five of the six
    deviation ratios of PRD §3.1 are exactly 0.0.
    """
    payload = factories.water_quality_reading_payload(
        build.now,
        temperature_c=12.0,
        salinity_ppt=33.0,
        ph=8.1,
        dissolved_oxygen_mg_l=7.4,
        nitrite_mg_l=0.02,
        ammonia_mg_l=ammonia,
    )
    return build.append_reading(plant["id"], payload)


def _loaded_exhibit(build: Builder) -> Dict[str, Any]:
    """A 19-unit specimen on exhibit, sizing the exhibit to 20 capacity units."""
    return build.specimen_on_exhibit(
        exhibit_overrides={"bioload_capacity_units": 20.0},
        species_overrides={"bioload_units_per_specimen": 19.0},
        entry_overrides={"planned_count": 1},
    )


def _recapacitate(api, build: Builder, exhibit_id: str, capacity: float) -> Dict[str, Any]:
    """Edit `bioload_capacity_units`, which recomputes ledger and posture."""
    payload = factories.exhibit_patch_payload(
        build.exhibit_version(exhibit_id), bioload_capacity_units=capacity
    )
    return validate_success(api.update_exhibit(exhibit_id, payload, DIRECTOR_HEADERS))


# ---------------------------------------------------------------------------
# Ammonia deviation ratio: the critical limit is a breach, its neighbour is not
# ---------------------------------------------------------------------------
def test_ammonia_exactly_on_its_critical_limit_is_a_breach_and_scores_critical(build):
    """Ammonia at 0.05 mg/l gives a ratio of exactly 2.0, which grades CRITICAL.

    PRD §3.1: "Two boundaries follow from the scaling and are deliberate: a parameter sitting exactly on its warn limit has a ratio of 0.0 and is **not** a breach, while a parameter sitting exactly on its critical limit has a ratio of 2.0 and **is** a breach."

    Design: Difficulty/boundary_precision_check/boundary_ammonia_ratio_exactly_two_flips_warning_to_critical
    """
    plant = build.create_plant()
    assert plant["alarm_state"] == "NORMAL", plant["alarm_state"]

    reading = _ammonia_reading(build, plant, 0.05)

    # ratio = (0.05 - 0.02) / (0.05 - 0.02) * 2 = 2.0, and it is the only
    # non-zero ratio, so the index is 100 - (6.0 * 2.0 + 15.0 * 2.0) = 58.00.
    assert reading["severity"] == "CRITICAL", reading["severity"]
    assert reading["breach_parameters"] == ["ammonia_mg_l"], reading["breach_parameters"]
    assert reading["water_quality_index_snapshot"] == 58.00, reading["water_quality_index_snapshot"]

    # §3.1: from NORMAL a CRITICAL reading moves the plant straight to CRITICAL.
    reread = build.get_plant(plant["id"])
    assert reread["alarm_state"] == "CRITICAL", reread["alarm_state"]
    assert reread["consecutive_breach_readings"] == 1, reread["consecutive_breach_readings"]
    assert reread["consecutive_normal_readings"] == 0, reread["consecutive_normal_readings"]
    assert reread["water_quality_index"] == 58.00, reread["water_quality_index"]


def test_ammonia_one_step_below_its_critical_limit_grades_only_warning(build):
    """Ammonia at 0.0499 mg/l stays under a ratio of 2.0, so it grades WARNING.

    PRD §3.1: "`severity` is read off the largest ratio alone: `CRITICAL` when it is at least 2.0, otherwise `WARNING` when it is at least 1.0, otherwise `NORMAL`."

    Design: Difficulty/boundary_precision_check/boundary_ammonia_ratio_exactly_two_flips_warning_to_critical
    """
    plant = build.create_plant()

    reading = _ammonia_reading(build, plant, 0.0499)

    # ratio = (0.0499 - 0.02) / 0.03 * 2 = 1.99333..., still at least 1.0 so it
    # is a breach, and the index is 100 - 21.0 * 1.99333... = 58.14 once
    # rounded half up, the ratio itself never being pre-rounded (§2.7).
    assert reading["severity"] == "WARNING", reading["severity"]
    assert reading["breach_parameters"] == ["ammonia_mg_l"], reading["breach_parameters"]
    assert reading["water_quality_index_snapshot"] == 58.14, reading["water_quality_index_snapshot"]

    # §3.1: from NORMAL a WARNING reading moves the plant to WARNING only.
    reread = build.get_plant(plant["id"])
    assert reread["alarm_state"] == "WARNING", reread["alarm_state"]
    assert reread["consecutive_breach_readings"] == 1, reread["consecutive_breach_readings"]
    assert reread["water_quality_index"] == 58.14, reread["water_quality_index"]


def test_ammonia_exactly_on_its_warn_limit_is_not_a_breach_at_all(build):
    """Ammonia at 0.02 mg/l gives a ratio of exactly 0.0 and costs nothing.

    PRD §3.1: "the ratio for `ammonia_mg_l` is the greater of 0 and (`ammonia_mg_l` minus 0.02), divided by (0.05 minus 0.02), multiplied by 2"

    Design: Difficulty/boundary_precision_check/boundary_ammonia_ratio_exactly_two_flips_warning_to_critical
    """
    plant = build.create_plant()

    reading = _ammonia_reading(build, plant, 0.02)

    # Every ratio is 0.0, so both penalties vanish and the index is a clean 100.
    assert reading["severity"] == "NORMAL", reading["severity"]
    assert reading["breach_parameters"] == [], reading["breach_parameters"]
    assert reading["water_quality_index_snapshot"] == 100.00, reading["water_quality_index_snapshot"]

    reread = build.get_plant(plant["id"])
    assert reread["alarm_state"] == "NORMAL", reread["alarm_state"]
    assert reread["consecutive_normal_readings"] == 1, reread["consecutive_normal_readings"]
    assert reread["consecutive_breach_readings"] == 0, reread["consecutive_breach_readings"]
    assert reread["water_quality_index"] == 100.00, reread["water_quality_index"]


# ---------------------------------------------------------------------------
# Bioload utilisation: 95.00 per cent is OPEN, anything above it is RESTRICTED
# ---------------------------------------------------------------------------
def test_exhibit_at_exactly_ninety_five_percent_utilisation_stays_open(build):
    """Nineteen bioload units in a capacity of twenty leave the exhibit OPEN.

    PRD §3.2: "The bioload comparison is strict: an exhibit sitting at exactly 95.00 per cent utilisation stays `OPEN`, and only 95.01 and above tips it to `RESTRICTED`."

    Design: Difficulty/boundary_precision_check/boundary_bioload_utilisation_exactly_95_stays_open
    """
    world = _loaded_exhibit(build)
    assert world["specimen"]["disposition_status"] == "ON_EXHIBIT", world["specimen"]["disposition_status"]

    exhibit = build.get_exhibit(world["exhibit"]["id"])
    assert exhibit["occupied_bioload_units"] == 19.00, exhibit["occupied_bioload_units"]
    assert exhibit["bioload_capacity_units"] == 20.00, exhibit["bioload_capacity_units"]
    assert exhibit["bioload_utilization_pct"] == 95.00, exhibit["bioload_utilization_pct"]
    assert exhibit["posture"] == "OPEN", exhibit["posture"]
    assert exhibit["last_posture_reason"] is None, exhibit["last_posture_reason"]


def test_exhibit_just_above_ninety_five_percent_utilisation_becomes_restricted(api, build):
    """Shrinking the capacity to 19.99 tips utilisation past 95.00 and restricts.

    PRD §3.2: "`bioload_utilization_pct` is strictly greater than 95.00 — posture `RESTRICTED`, `last_posture_reason` `BIOLOAD_PRESSURE`;"

    Design: Difficulty/boundary_precision_check/boundary_bioload_utilisation_exactly_95_stays_open
    """
    world = _loaded_exhibit(build)
    exhibit_id = world["exhibit"]["id"]

    # 19.00 / 19.99 * 100 = 95.0475..., which rounds half up to 95.05 — one
    # step past the strict threshold, with the plant conditions all quiet.
    edited = _recapacitate(api, build, exhibit_id, 19.99)
    assert edited["occupied_bioload_units"] == 19.00, edited["occupied_bioload_units"]
    assert edited["bioload_utilization_pct"] == 95.05, edited["bioload_utilization_pct"]
    assert edited["posture"] == "RESTRICTED", edited["posture"]
    assert edited["last_posture_reason"] == "BIOLOAD_PRESSURE", edited["last_posture_reason"]

    reread = build.get_exhibit(exhibit_id)
    assert reread["bioload_utilization_pct"] == 95.05, reread["bioload_utilization_pct"]
    assert reread["posture"] == "RESTRICTED", reread["posture"]
    assert reread["last_posture_reason"] == "BIOLOAD_PRESSURE", reread["last_posture_reason"]


def test_overloaded_exhibit_reports_an_unclamped_utilisation_rounded_half_up(api, build):
    """Nineteen units in a capacity of eighteen report 105.56, not 100.00.

    PRD §2.7: "`bioload_utilization_pct` is deliberately **not** clamped: an exhibit whose occupied bioload exceeds its capacity reports a percentage above 100.00, and that is the honest figure the posture rule reads."

    Design: Difficulty/boundary_precision_check/boundary_bioload_utilisation_exactly_95_stays_open
    """
    world = _loaded_exhibit(build)
    exhibit_id = world["exhibit"]["id"]

    # 19.00 / 18 * 100 = 105.5555..., which rounds half up to 105.56 rather
    # than truncating to 105.55.
    edited = _recapacitate(api, build, exhibit_id, 18.0)
    assert edited["occupied_bioload_units"] == 19.00, edited["occupied_bioload_units"]
    assert edited["bioload_utilization_pct"] == 105.56, edited["bioload_utilization_pct"]
    assert edited["posture"] == "RESTRICTED", edited["posture"]
    assert edited["last_posture_reason"] == "BIOLOAD_PRESSURE", edited["last_posture_reason"]

    reread = build.get_exhibit(exhibit_id)
    assert reread["bioload_utilization_pct"] == 105.56, reread["bioload_utilization_pct"]


def test_restoring_capacity_returns_the_exhibit_to_open_at_the_boundary(api, build):
    """Coming back down to exactly 95.00 per cent reopens the exhibit.

    PRD §3.2: "and otherwise posture `OPEN` with `last_posture_reason` null."

    Design: Difficulty/boundary_precision_check/boundary_bioload_utilisation_exactly_95_stays_open
    """
    world = _loaded_exhibit(build)
    exhibit_id = world["exhibit"]["id"]

    restricted = _recapacitate(api, build, exhibit_id, 19.0)
    assert restricted["bioload_utilization_pct"] == 100.00, restricted["bioload_utilization_pct"]
    assert restricted["posture"] == "RESTRICTED", restricted["posture"]

    # §3.2: the posture is recomputed whenever the capacity is edited, so the
    # BIOLOAD_PRESSURE reason cannot be latched once utilisation is back on 95.00.
    restored = _recapacitate(api, build, exhibit_id, 20.0)
    assert restored["occupied_bioload_units"] == 19.00, restored["occupied_bioload_units"]
    assert restored["bioload_utilization_pct"] == 95.00, restored["bioload_utilization_pct"]
    assert restored["posture"] == "OPEN", restored["posture"]
    assert restored["last_posture_reason"] is None, restored["last_posture_reason"]
    # Each guarded edit increments the exhibit's version (§2.6).
    assert restored["version"] == world["exhibit"]["version"] + 2, restored["version"]

    reread = build.get_exhibit(exhibit_id)
    assert reread["posture"] == "OPEN", reread["posture"]
    assert reread["last_posture_reason"] is None, reread["last_posture_reason"]


# ---------------------------------------------------------------------------
# Receiver eligibility: a welfare audit score of exactly 70.0 qualifies
# ---------------------------------------------------------------------------
def test_receiver_scoring_exactly_seventy_is_eligible_and_accepts_a_submission(build):
    """An ACCREDITED receiver on exactly 70.0 clears the eligibility gate.

    PRD §2.9: "An institution is an eligible receiver when its `accreditation_status` is `ACCREDITED` or `PROVISIONAL` **and** its `welfare_audit_score` is at least 70.0 — the boundary is inclusive, so exactly 70.0 qualifies and 69.99 does not"

    Design: Difficulty/boundary_precision_check/boundary_receiver_welfare_exactly_seventy_is_eligible
    """
    world = build.cleared_specimen()
    receiver = build.create_institution(accreditation_status="ACCREDITED", welfare_audit_score=70.0)
    assert receiver["welfare_audit_score"] == 70.00, receiver["welfare_audit_score"]
    assert receiver["is_receiving_eligible"] is True, receiver["is_receiving_eligible"]

    transfer = build.draft_transfer(
        world["specimen"]["id"],
        receiver["id"],
        shift(build.now, days=10),
        welfare_conditions=list(REQUIRED_CONDITIONS),
    )
    assert transfer["status"] == "DRAFT", transfer["status"]

    submitted = build.submit_transfer(transfer["id"])
    assert submitted["status"] == "SUBMITTED", submitted["status"]

    # §3.8: the first submission moves the specimen to TRANSFER_PENDING and
    # records its previous disposition in pre_transfer_disposition.
    specimen = build.get_specimen(world["specimen"]["id"])
    assert specimen["disposition_status"] == "TRANSFER_PENDING", specimen["disposition_status"]
    assert specimen["pre_transfer_disposition"] == "CLEARED", specimen["pre_transfer_disposition"]


def test_receiver_scoring_just_below_seventy_is_refused_the_submission(api, build):
    """A receiver on 69.99 fails the inclusive floor and cannot take an animal.

    PRD §2.8: "The receiving institution's `is_receiving_eligible` is `true` — `ERR_RECEIVER_NOT_ELIGIBLE` (409). Applies to transfer submission and transfer decisions."

    Design: Difficulty/boundary_precision_check/boundary_receiver_welfare_exactly_seventy_is_eligible
    """
    world = build.cleared_specimen()
    receiver = build.create_institution(accreditation_status="ACCREDITED", welfare_audit_score=69.99)
    assert receiver["welfare_audit_score"] == 69.99, receiver["welfare_audit_score"]
    assert receiver["is_receiving_eligible"] is False, receiver["is_receiving_eligible"]

    transfer = build.draft_transfer(
        world["specimen"]["id"],
        receiver["id"],
        shift(build.now, days=10),
        welfare_conditions=list(REQUIRED_CONDITIONS),
    )

    response = api.submit_transfer_request(transfer["id"], {}, PERMIT_OFFICER_HEADERS)
    validate_error(response, ERR_RECEIVER_NOT_ELIGIBLE, 409)

    # The refusal leaves both the request and the animal exactly where they were.
    stored = validate_success(api.get_transfer_request(transfer["id"], PERMIT_OFFICER_HEADERS))
    assert stored["status"] == "DRAFT", stored["status"]
    specimen = build.get_specimen(world["specimen"]["id"])
    assert specimen["disposition_status"] == "CLEARED", specimen["disposition_status"]
    assert specimen["pre_transfer_disposition"] is None, specimen["pre_transfer_disposition"]


def test_dropping_the_receiver_score_below_seventy_declines_the_live_transfer(api, build):
    """Editing 70.0 down to 69.99 flips eligibility and declines the transfer.

    PRD §3.8: "When an institution edit flips `is_receiving_eligible` from true to false, three links run: every transfer request whose `receiving_institution_id` is that institution and whose `status` is `SUBMITTED`, `COUNTERED` or `APPROVED` moves to `DECLINED`; each carries `decline_reason` `RECEIVER_INELIGIBLE`; and each affected specimen's `disposition_status` is restored from `pre_transfer_disposition`, which is then nulled."

    Design: Difficulty/boundary_precision_check/boundary_receiver_welfare_exactly_seventy_is_eligible
    """
    world = build.cleared_specimen()
    receiver = build.create_institution(accreditation_status="ACCREDITED", welfare_audit_score=70.0)
    transfer = build.draft_transfer(
        world["specimen"]["id"],
        receiver["id"],
        shift(build.now, days=10),
        welfare_conditions=list(REQUIRED_CONDITIONS),
    )
    submitted = build.submit_transfer(transfer["id"])
    assert submitted["status"] == "SUBMITTED", submitted["status"]

    # One hundredth below the inclusive floor is enough to lose eligibility.
    edited = validate_success(
        api.update_institution(
            receiver["id"], factories.institution_patch_payload(welfare_audit_score=69.99), DIRECTOR_HEADERS
        )
    )
    assert edited["welfare_audit_score"] == 69.99, edited["welfare_audit_score"]
    assert edited["is_receiving_eligible"] is False, edited["is_receiving_eligible"]
    assert edited["version"] == receiver["version"] + 1, edited["version"]

    declined = validate_success(api.get_transfer_request(transfer["id"], PERMIT_OFFICER_HEADERS))
    assert declined["status"] == "DECLINED", declined["status"]
    assert declined["decline_reason"] == "RECEIVER_INELIGIBLE", declined["decline_reason"]

    specimen = build.get_specimen(world["specimen"]["id"])
    assert specimen["disposition_status"] == "CLEARED", specimen["disposition_status"]
    assert specimen["pre_transfer_disposition"] is None, specimen["pre_transfer_disposition"]
