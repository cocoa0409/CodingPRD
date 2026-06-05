"""Relief from the automatic stay: the secured-target requirement at filing, and
the grant cascade that moves the case posture to LIFTED_PARTIAL.

PRD §3.9 and §2.9 govern these assertions.
"""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error,
    create_stay_relief_motion_payload,
    register_creditor, register_trustee, setup_filed_case, add_debt,
    file_stay_relief_motion,
    make_creditor_headers, make_trustee_headers,
)


def test_stay_relief_motion_target_not_secured_rejected(api):
    """PRD §3.9: "The targeted debt must be secured: its debt_class must be
    SECURED, and a motion against a non-secured debt is rejected with
    ERR_RELIEF_TARGET_NOT_SECURED (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/stay_relief_grant_requires_secured_debt_pair_motion_debt
    """
    debtor, case = setup_filed_case(filed_chapter="CHAPTER_13")
    creditor = register_creditor(name="Cr 7b")
    u_debt = add_debt(debtor, case, creditor, "UNSECURED", 90000)
    res = api.create_stay_relief_motion(create_stay_relief_motion_payload(
        case["id"], creditor["id"], u_debt["id"]), make_creditor_headers(creditor["id"]))
    validate_error(res, "ERR_RELIEF_TARGET_NOT_SECURED")


def test_stay_relief_motion_against_secured_debt_is_accepted(api):
    """PRD §3.9: "The targeted debt must be secured: its debt_class must be
    SECURED ... The motion is created with status of PENDING."

    Design: Difficulty/cross_entity_state_dependency/stay_relief_grant_requires_secured_debt_pair_motion_debt
    """
    debtor, case = setup_filed_case(filed_chapter="CHAPTER_13")
    creditor = register_creditor(name="Cr 7b-ok")
    s_debt = add_debt(debtor, case, creditor, "SECURED", 300000)
    res = api.create_stay_relief_motion(create_stay_relief_motion_payload(
        case["id"], creditor["id"], s_debt["id"]), make_creditor_headers(creditor["id"]))
    motion = validate_success(res, 201)
    assert motion["status"] == "PENDING"


def test_stay_relief_grant_sets_lifted_partial(api):
    """PRD §3.9: "Granting advances the motion from PENDING to GRANTED and, as a
    cascade, moves the case's stay_posture to LIFTED_PARTIAL, partially lifting
    the stay as to the named collateral and incrementing the case's version."

    Design: Corner/state_machines/stay_relief_grant_sets_lifted_partial_compound_posture
    """
    debtor, case = setup_filed_case(filed_chapter="CHAPTER_13")
    creditor = register_creditor(name="Cr grant")
    trustee = register_trustee(name="T-grant")
    s_debt = add_debt(debtor, case, creditor, "SECURED", 300000)
    motion = file_stay_relief_motion(creditor, case, s_debt)

    t_headers = make_trustee_headers(trustee["id"])
    res = api.grant_stay_relief_motion(motion["id"], t_headers)
    granted = validate_success(res, 200)
    assert granted["status"] == "GRANTED"

    case_after = validate_success(api.get_case(case["id"], t_headers), 200)
    assert case_after["stay_posture"] == "LIFTED_PARTIAL"
