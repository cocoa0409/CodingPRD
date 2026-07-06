"""Specimen chain of custody and toxicology results / amendment loop."""
from test_helpers import (
    validate_success,
    create_investigator, create_pathologist,
    setup_ordered_tox,
    result_tox_screen,
    make_labtech_headers,
    amend_tox_screen_payload,
    result_tox_screen_payload,
)


def test_tox_screen_reamend_recomputes_negative_and_stays_amended(api):
    """PRD §3.5: "A resulted screen may be corrected. Amending a screen overwrites
    ethanol_mg_dl with a new value and recomputes interpretation against the same 80-threshold
    rule, incrementing the screen's version. A screen may be amended when it is RESULTED,
    moving it `RESULTED → AMENDED`, and an already-`AMENDED` screen may be amended again,
    looping `AMENDED → AMENDED` as many times as needed." PRD §3.5: "The interpretation is
    recomputed at this point: it is POSITIVE if the reported ethanol_mg_dl is at least 80, and
    NEGATIVE otherwise."

    Design: Difficulty/non_linear_state_machine/tox_screen_amend_loop
    """
    inv = create_investigator("Inv E")
    path = create_pathologist("Path E")
    case, body, specimen, tox = setup_ordered_tox(inv, path, panel="BASIC")

    result_tox_screen(tox, 90)  # RESULTED, POSITIVE
    labtech = make_labtech_headers()
    validate_success(api.amend_tox_screen(tox["id"], amend_tox_screen_payload(85), labtech), 200)  # AMENDED, POSITIVE

    reamended = validate_success(
        api.amend_tox_screen(tox["id"], amend_tox_screen_payload(40), labtech), 200
    )
    assert reamended["result_status"] == "AMENDED"
    assert reamended["interpretation"] == "NEGATIVE"
    assert reamended["ethanol_mg_dl"] == 40


def test_tox_result_cascades_specimen_consumed(api):
    """PRD §3.5: "The technician reports the blood ethanol_mg_dl concentration; the screen moves
    ORDERED -> RESULTED, and as a cascade the parent specimen's chain_status advances
    SENT_TO_LAB -> CONSUMED (the assay consumes the specimen), incrementing both the screen's
    and the specimen's version."

    Design: Difficulty/transitive_cascade/tox_result_cascades_specimen_consumed
    """
    inv = create_investigator("Inv H")
    path = create_pathologist("Path H")
    case, body, specimen, tox = setup_ordered_tox(inv, path, panel="BASIC")

    labtech = make_labtech_headers()
    resulted = validate_success(
        api.result_tox_screen(tox["id"], result_tox_screen_payload(10), labtech), 200
    )
    assert resulted["result_status"] == "RESULTED"

    specimen_after = validate_success(api.get_specimen(specimen["id"], labtech), 200)
    assert specimen_after["chain_status"] == "CONSUMED"


def test_tox_interpretation_positive_at_threshold(api):
    """PRD §3.5: "it is POSITIVE if the reported ethanol_mg_dl is at least 80, and NEGATIVE
    otherwise."

    Design: Corner/calculations/tox_interpretation_positive_at_threshold
    """
    inv = create_investigator("Inv CC2")
    path = create_pathologist("Path CC2")
    case, body, specimen, tox = setup_ordered_tox(inv, path, panel="BASIC")

    labtech = make_labtech_headers()
    resulted = validate_success(
        api.result_tox_screen(tox["id"], result_tox_screen_payload(80), labtech), 200
    )
    assert resulted["interpretation"] == "POSITIVE"
