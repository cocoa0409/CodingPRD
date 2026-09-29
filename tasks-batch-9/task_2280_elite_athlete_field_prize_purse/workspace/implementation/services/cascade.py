"""Disqualification, breach and record-ratification cascades (PRD 2.10, 3.6, 3.7)."""
from constants import BREACH_DQ_REASONS
from db import touch
from services import lookup, valuation


def release_fluid_slots(invitation):
    for slot in lookup.invitation_slots(invitation["id"]):
        if slot["status"] == "RESERVED":
            slot["status"] = "RELEASED"
            touch(slot)


def breach_invitation(invitation):
    """ACCEPTED -> BREACHED: a compensating action in its own right."""
    invitation["status"] = "BREACHED"
    invitation["guaranteed_commitment_cents"] = 0
    invitation["bib_number"] = None
    touch(invitation)
    release_fluid_slots(invitation)


def disqualify_result(edition, result, dq_reason, force_cascade=False):
    """Returns True when an edition-level projection moved (so the caller can
    bump the edition's version exactly once for the request)."""
    was_certified = result["certification_status"] == "CERTIFIED"
    run_cascade = was_certified or force_cascade

    result["certification_status"] = "DISQUALIFIED"
    result["dq_reason"] = dq_reason
    if was_certified:
        result["place_overall"] = None
        result["place_division"] = None
        result["place_masters"] = None
        result["tie_group_size"] = 1
    if run_cascade and result["record_claim_status"] in ("CLAIMED", "SUBMITTED"):
        result["record_claim_status"] = "REJECTED"
    touch(result)

    edition_changed = False
    if run_cascade:
        for award in lookup.rows("prize_awards", race_result_id=result["id"]):
            if award["status"] in ("COMPUTED", "APPROVED"):
                award["status"] = "VOID"
                touch(award)
                edition_changed = True
            elif award["status"] == "PAID":
                award["status"] = "CLAWBACK_PENDING"
                touch(award)
                edition_changed = True
        if dq_reason in BREACH_DQ_REASONS:
            invitation = lookup.soft_get("invitations", result["invitation_id"])
            if invitation is not None and invitation["status"] == "ACCEPTED":
                breach_invitation(invitation)
                edition_changed = True
    return edition_changed


def adverse_test_cascade(test):
    """Cascade hops 2..4 of an ADVERSE laboratory outcome."""
    edition = lookup.soft_get("race_editions", test["race_edition_id"])
    if edition is None:
        return False
    edition_changed = False
    for result in lookup.edition_results(edition["id"]):
        if result["athlete_id"] != test["athlete_id"]:
            continue
        if result["certification_status"] not in ("PROVISIONAL", "CERTIFIED"):
            continue
        changed = disqualify_result(
            edition, result, "ADVERSE_ANALYTICAL_FINDING", force_cascade=True
        )
        edition_changed = edition_changed or changed
    return edition_changed


def ratify_record(edition, result):
    """record_claim_status SUBMITTED -> RATIFIED plus cascade hops 2 and 3."""
    result["record_claim_status"] = "RATIFIED"
    touch(result)

    field = valuation.record_field_name(
        result["division"], _gender_of(result)
    )
    edition[field] = result["official_seconds"]
    touch(edition)

    new_record_value = result["official_seconds"]
    for other in lookup.edition_results(edition["id"]):
        if other["id"] == result["id"]:
            continue
        if other["certification_status"] != "CERTIFIED":
            continue
        if other["record_claim_status"] != "CLAIMED":
            continue
        if other["official_seconds"] >= new_record_value:
            other["record_claim_status"] = "REJECTED"
            touch(other)


def _gender_of(result):
    athlete = lookup.soft_get("athletes", result["athlete_id"])
    return athlete["gender"] if athlete else "MALE"
