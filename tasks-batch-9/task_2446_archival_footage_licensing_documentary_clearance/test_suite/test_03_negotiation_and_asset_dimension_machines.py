"""Non-linear state machines: the negotiation cycle and the asset's parallel dimensions."""

from typing import Any, Dict, List

from test_helpers import (
    CLEARANCE_SUPERVISOR,
    PRODUCTION_ADMIN,
    assert_asset_dimensions,
    assert_posture,
    assert_production_counters,
    create_archive_with_rate_card,
    create_asset_with_selected_source,
    create_license,
    create_negotiation_round_payload,
    create_production_in_clearance,
    create_subject_release,
    drive_subject_release,
    execute_license,
    get_asset,
    get_license,
    get_production,
    get_success_data,
    make_rights_holder_rep_headers,
    post_licensor_round,
    validate_error,
    validate_paginated,
    validate_success,
)

# The six rounds of the negotiation, alternating LICENSOR and PRODUCER.
_ROUND_SCRIPT = [
    ("LICENSOR", 500000),
    ("PRODUCER", 380000),
    ("LICENSOR", 470000),
    ("PRODUCER", 400000),
    ("LICENSOR", 440000),
    ("PRODUCER", 420000),
]

# The licence status each of those six rounds leaves behind.
_EXPECTED_STATUS_AFTER = [
    "QUOTED",
    "COUNTERED",
    "QUOTED",
    "COUNTERED",
    "QUOTED",
    "COUNTERED",
]


def _post_round(api, license_id: str, archive_id: str, party: str,
                proposed_fee_cents: int, expected_license_version: int):
    """Append one negotiation round, threading the caller's expected licence version.

    A `LICENSOR` round is posted by the licence's own holder, whose `X-User-ID` is
    the acting `Archive.id`; a `PRODUCER` round is posted by the supervisor.
    """
    headers = (make_rights_holder_rep_headers(archive_id) if party == "LICENSOR"
               else CLEARANCE_SUPERVISOR)
    payload = create_negotiation_round_payload(
        proposed_fee_cents, expected_license_version, party=party)
    return api.create_negotiation_round(license_id, payload, headers)


def _setup_draft_license(api) -> Dict[str, Any]:
    """A production in CLEARANCE holding one DRAFT licence on a 45-second footage asset."""
    production = create_production_in_clearance(api, title="Six Rounds",
                                                delivery_deadline_date="2027-11-30")
    archive, rate_card = create_archive_with_rate_card(api)
    asset, candidate = create_asset_with_selected_source(
        api, production["id"], archive["id"], title="Haggling reel")
    license_row = create_license(api, production["id"], asset["id"], archive["id"],
                                term_months=36, term_start_date="2026-08-15",
                                term_end_date="2029-08-15")
    return {
        "production": production,
        "archive": archive,
        "rate_card": rate_card,
        "asset": asset,
        "source_candidate": candidate,
        "license": license_row,
    }


def _run_six_rounds(api, scenario: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Post the six scripted rounds, each carrying the previous round's
    `license_version_after` as its `expected_license_version`."""
    license_id = scenario["license"]["id"]
    archive_id = scenario["archive"]["id"]
    expected_version = scenario["license"]["version"]
    rounds: List[Dict[str, Any]] = []
    for party, fee in _ROUND_SCRIPT:
        response = _post_round(api, license_id, archive_id, party, fee, expected_version)
        round_row = validate_success(response, 201)
        rounds.append(round_row)
        expected_version = round_row["license_version_after"]
    return rounds


def _setup_cleared_asset_with_pending_depiction(api) -> Dict[str, Any]:
    """A footage asset CLEARED on an executed licence whose depiction is still PENDING.

    The release granted `FINAL_APPROVAL`, so signing it left dimension B at `PENDING`.
    """
    production = create_production_in_clearance(api, title="Two Dimensions",
                                                delivery_deadline_date="2027-10-31")
    archive, rate_card = create_archive_with_rate_card(api)
    asset, candidate = create_asset_with_selected_source(
        api, production["id"], archive["id"], title="Interview outtake",
        depiction_subject_key="subject-halloran")
    license_row = create_license(api, production["id"], asset["id"], archive["id"],
                                term_months=36, term_start_date="2026-08-15",
                                term_end_date="2029-08-15")
    post_licensor_round(api, license_row["id"], archive["id"], 362250)
    license_row = execute_license(api, license_row["id"])
    release = create_subject_release(
        api, production["id"], "subject-halloran",
        release_type="DEPICTION_AGREEMENT", depiction_from_date="1964-03-01",
        depiction_to_date="1964-09-30", asset_id=asset["id"],
        approval_rights="FINAL_APPROVAL")
    drive_subject_release(api, release["id"], "SENT")
    release = drive_subject_release(api, release["id"], "SIGNED")
    return {
        "production": get_production(api, production["id"]),
        "archive": archive,
        "rate_card": rate_card,
        "asset": get_asset(api, asset["id"]),
        "source_candidate": candidate,
        "license": license_row,
        "release": release,
    }


# ─── license_negotiation_cycle_revisits_quoted_and_caps_at_six_rounds ─────────


def test_negotiation_cycle_re_enters_quoted_three_separate_times(api):
    """PRD §3.4: "A `LICENSOR` round posted against a licence in `DRAFT` advances it
    `DRAFT → QUOTED`. A `PRODUCER` round posted against a licence in `QUOTED` advances
    it `QUOTED → COUNTERED`. A `LICENSOR` round posted against a licence in `COUNTERED`
    advances it `COUNTERED → QUOTED` again, and the pair `QUOTED → COUNTERED → QUOTED`
    repeats until one side executes or the round ceiling stops the negotiation."

    Design: Difficulty/non_linear_state_machine/license_negotiation_cycle_revisits_quoted_and_caps_at_six_rounds
    """
    scenario = _setup_draft_license(api)
    assert scenario["license"]["status"] == "DRAFT"
    assert scenario["license"]["round_count"] == 0

    rounds = _run_six_rounds(api, scenario)

    assert [row["license_status_after"] for row in rounds] == _EXPECTED_STATUS_AFTER
    assert [row["license_status_after"] for row in rounds].count("QUOTED") == 3

    license_row = get_license(api, scenario["license"]["id"])
    assert license_row["status"] == "COUNTERED"
    assert license_row["round_count"] == 6


def test_negotiation_rounds_number_and_version_chain_replays_in_order(api):
    """PRD §3.4: "The round is created with `round_number` equal to the licence's
    `round_count` before the round plus one, so the first round is round 1."

    Design: Difficulty/non_linear_state_machine/license_negotiation_cycle_revisits_quoted_and_caps_at_six_rounds
    """
    scenario = _setup_draft_license(api)
    rounds = _run_six_rounds(api, scenario)

    assert [row["round_number"] for row in rounds] == [1, 2, 3, 4, 5, 6]
    # PRD §2.4: license_version_after records the licence's version immediately after
    # the round was applied, and the licence's version starts at 1.
    assert [row["license_version_after"] for row in rounds] == [2, 3, 4, 5, 6, 7]

    history, meta = validate_paginated(
        api.list_negotiation_rounds(scenario["license"]["id"], CLEARANCE_SUPERVISOR,
                                    params={"limit": 100}))
    assert meta["total_count"] == 6
    assert [row["round_number"] for row in history] == [1, 2, 3, 4, 5, 6]
    assert [row["license_status_after"] for row in history] == _EXPECTED_STATUS_AFTER
    assert [row["party"] for row in history] == [party for party, _fee in _ROUND_SCRIPT]

    license_row = get_license(api, scenario["license"]["id"])
    assert license_row["version"] == 7


def test_standing_proposal_is_the_most_recent_round_from_either_side(api):
    """PRD §3.4: "The licence's `round_count` increases by one, its
    `current_proposed_fee_cents` is overwritten with this round's `proposed_fee_cents`
    — the standing proposal is always simply the most recent one, regardless of which
    side made it — and its `version` increments."

    Design: Difficulty/non_linear_state_machine/license_negotiation_cycle_revisits_quoted_and_caps_at_six_rounds
    """
    scenario = _setup_draft_license(api)
    license_id = scenario["license"]["id"]
    # PRD §3.3: current_proposed_fee_cents initialises to the rate-card figure.
    assert scenario["license"]["current_proposed_fee_cents"] == 362250
    assert scenario["license"]["rate_card_fee_cents"] == 362250

    expected_version = scenario["license"]["version"]
    for index, (party, fee) in enumerate(_ROUND_SCRIPT, start=1):
        round_row = validate_success(
            _post_round(api, license_id, scenario["archive"]["id"], party, fee,
                        expected_version), 201)
        expected_version = round_row["license_version_after"]
        license_row = get_license(api, license_id)
        assert license_row["current_proposed_fee_cents"] == fee
        assert license_row["round_count"] == index
        assert license_row["rate_card_fee_cents"] == 362250
        assert license_row["executed_fee_cents"] is None


def test_seventh_negotiation_round_is_refused_at_the_round_ceiling(api):
    """PRD §3.4: "That ceiling is six: a round is accepted only while the licence's
    `round_count` is below 6, and the seventh attempt is refused with
    `ERR_NEGOTIATION_ROUND_LIMIT` (HTTP 409)."

    Design: Difficulty/non_linear_state_machine/license_negotiation_cycle_revisits_quoted_and_caps_at_six_rounds
    """
    scenario = _setup_draft_license(api)
    license_id = scenario["license"]["id"]
    rounds = _run_six_rounds(api, scenario)
    current_version = rounds[-1]["license_version_after"]

    response = _post_round(api, license_id, scenario["archive"]["id"], "LICENSOR",
                           430000, current_version)
    validate_error(response, "ERR_NEGOTIATION_ROUND_LIMIT")

    license_row = get_license(api, license_id)
    assert license_row["round_count"] == 6
    assert license_row["status"] == "COUNTERED"
    assert license_row["current_proposed_fee_cents"] == 420000
    assert license_row["version"] == 7
    assert license_row["executed_fee_cents"] is None

    history, meta = validate_paginated(
        api.list_negotiation_rounds(license_id, CLEARANCE_SUPERVISOR,
                                    params={"limit": 100}))
    assert meta["total_count"] == 6
    assert len(history) == 6


# ─── asset_parallel_dimensions_advance_independently ──────────────────────────


def test_signing_a_final_approval_release_leaves_dimension_b_pending(api):
    """PRD §3.6: "Where the release granted `ROUGH_CUT_APPROVAL` or `FINAL_APPROVAL`,
    signing leaves the asset's `depiction_status` at `PENDING`, because the subject
    still holds a decision over the cut."

    Design: Difficulty/non_linear_state_machine/asset_parallel_dimensions_advance_independently
    """
    scenario = _setup_cleared_asset_with_pending_depiction(api)

    assert scenario["release"]["status"] == "SIGNED"
    assert scenario["release"]["approval_rights"] == "FINAL_APPROVAL"
    assert scenario["release"]["release_type"] == "DEPICTION_AGREEMENT"

    asset = get_asset(api, scenario["asset"]["id"])
    assert_asset_dimensions(asset, "CLEARED", depiction_status="PENDING",
                            rights_basis="LICENSED", lapse_count=0)

    production = get_production(api, scenario["production"]["id"])
    assert_production_counters(production, asset_count=1, cleared_asset_count=1,
                               open_asset_count=0)
    # PRD §2.8 rule 4: zero open assets multiplied by four is at most the total, so a
    # production whose only gap is a PENDING depiction is RESTRICTED, not OPEN.
    assert_posture(production, "RESTRICTED")


def test_withholding_approval_moves_dimension_b_without_disturbing_dimension_a(api):
    """PRD §3.6: "Withholding approval sets the linked asset's `depiction_status` to
    `BLOCKED`, moving dimension B `OBTAINED → BLOCKED` where the asset had already
    reached `OBTAINED`, recomputes the production's posture — where a single asset with
    `depiction_status` of `BLOCKED` forces the posture to `BLOCKED` outright — and flips
    every `PINNED` chart pinning that asset to `STALE`."

    Design: Difficulty/non_linear_state_machine/asset_parallel_dimensions_advance_independently
    """
    scenario = _setup_cleared_asset_with_pending_depiction(api)

    response = api.set_subject_release_state(
        scenario["release"]["id"],
        {"to_status": "APPROVAL_WITHHELD", "cut_reference": "rough-cut-4"},
        PRODUCTION_ADMIN)
    release = validate_success(response, 200)
    assert release["status"] == "APPROVAL_WITHHELD"
    assert release["cut_reference"] == "rough-cut-4"

    asset = get_asset(api, scenario["asset"]["id"])
    # PRD §3.1: dimension A advances on licence and fair-use events; dimension B
    # advances only on subject-release events.
    assert_asset_dimensions(asset, "CLEARED", depiction_status="BLOCKED",
                            rights_basis="LICENSED", lapse_count=0)


def test_blocked_depiction_alone_forces_posture_blocked_with_counters_untouched(api):
    """PRD §2.8: "Otherwise, if at least one asset has `depiction_status` of `BLOCKED`,
    or at least one asset has `licensing_status` of `LAPSED`, posture is `BLOCKED`."

    Design: Difficulty/non_linear_state_machine/asset_parallel_dimensions_advance_independently
    """
    scenario = _setup_cleared_asset_with_pending_depiction(api)

    get_success_data(api.set_subject_release_state(
        scenario["release"]["id"],
        {"to_status": "APPROVAL_WITHHELD", "cut_reference": "rough-cut-4"},
        PRODUCTION_ADMIN))

    production = get_production(api, scenario["production"]["id"])
    assert_posture(production, "BLOCKED")
    # PRD §2.9: cleared_asset_count plus open_asset_count always equals asset_count;
    # the dimension-B move leaves every licensing counter exactly where it was.
    assert_production_counters(production, asset_count=1, cleared_asset_count=1,
                               open_asset_count=0)


def test_approval_withheld_is_terminal_for_the_release(api):
    """PRD §3.6: "`APPROVAL_WITHHELD` is terminal, so a withheld approval cannot be
    walked back on the same release; the remedy is a new paper or a re-cut."

    Design: Difficulty/non_linear_state_machine/asset_parallel_dimensions_advance_independently
    """
    scenario = _setup_cleared_asset_with_pending_depiction(api)
    release_id = scenario["release"]["id"]

    get_success_data(api.set_subject_release_state(
        release_id,
        {"to_status": "APPROVAL_WITHHELD", "cut_reference": "rough-cut-4"},
        PRODUCTION_ADMIN))

    response = api.set_subject_release_state(
        release_id, {"to_status": "APPROVAL_GRANTED", "cut_reference": "rough-cut-5"},
        PRODUCTION_ADMIN)
    validate_error(response, "ERR_INVALID_STATE_TRANSITION")

    release = get_success_data(api.get_subject_release(release_id, PRODUCTION_ADMIN))
    assert release["status"] == "APPROVAL_WITHHELD"
    assert release["cut_reference"] == "rough-cut-4"

    asset = get_asset(api, scenario["asset"]["id"])
    assert_asset_dimensions(asset, "CLEARED", depiction_status="BLOCKED",
                            rights_basis="LICENSED", lapse_count=0)
