"""Lookups, state gates and the declared cascade routines."""

import calc
from errors import ApiError
from store import (
    INVITATION_RESPONSE_WINDOW_HOURS,
    dt_of,
    find,
    hours,
    iso,
    now,
    touch,
)

ACTIVE_INVITATION_STATUSES = ("ISSUED", "WAITLISTED", "ACCEPTED")


# ------------------------------------------------------------------ gates
def invalid_state(message=None):
    raise ApiError("ERR_INVALID_STATE", message)


def require_state(row, field, allowed):
    if row[field] not in allowed:
        invalid_state(
            "Resource %s is %s; expected one of %s."
            % (field, row[field], ", ".join(allowed))
        )


def require_phase(program, allowed):
    if program["season_phase"] not in allowed:
        invalid_state(
            "Program.season_phase is %s; this operation requires %s."
            % (program["season_phase"], ", ".join(allowed))
        )


# ------------------------------------------------------------------ lookups
def program_of_application(application):
    return find("programs", application["program_id"])


def applicant_of_application(application):
    return find("applicants", application["applicant_id"])


def program_of_wave(wave):
    return find("programs", wave["program_id"])


def wave_of_slot(slot):
    return find("interview_waves", slot["wave_id"])


def program_of_slot(slot):
    wave = wave_of_slot(slot)
    return program_of_wave(wave) if wave else None


def application_of_invitation(invitation):
    return find("applications", invitation["application_id"])


def wave_of_invitation(invitation):
    return find("interview_waves", invitation["wave_id"])


def application_of_result(result):
    return find("applications", result["application_id"])


def result_of_contract(contract):
    return find("match_results", contract["match_result_id"])


def application_of_contract(contract):
    result = result_of_contract(contract)
    return application_of_result(result) if result else None


def contract_of_item(item):
    return find("contracts", item["contract_id"])


def certified_rank_list(program_id):
    for row in calc.program_rank_lists(program_id):
        if row["status"] == "CERTIFIED":
            return row
    return None


def live_rank_list(program_id):
    for row in calc.program_rank_lists(program_id):
        if row["status"] != "WITHDRAWN":
            return row
    return None


def program_has_certified_list(program_id):
    return certified_rank_list(program_id) is not None


# ------------------------------------------------------------------ scores
def refresh_provisional(application):
    application["provisional_screen_score"] = float(calc.provisional_screen_score(application))


def write_final_screen_score(application, applicant):
    application["final_screen_score"] = float(calc.final_screen_score(application, applicant))


def refresh_committee_score(application):
    value = calc.committee_rubric_score(application)
    application["committee_score"] = None if value is None else float(value)
    touch(application)


# ------------------------------------------------------------------ invitations
def expiry_for(wave, issued_at):
    deadline = dt_of(wave, "response_deadline_at")
    window_end = issued_at + hours(INVITATION_RESPONSE_WINDOW_HOURS)
    return deadline if deadline < window_end else window_end


def stamp_issued(invitation, wave):
    issued_at = now()
    invitation["issued_at"] = iso(issued_at)
    invitation["expires_at"] = iso(expiry_for(wave, issued_at))


def application_has_active_invitation(application_id):
    return any(
        row["status"] in ACTIVE_INVITATION_STATUSES
        for row in calc.application_invitations(application_id)
    )


def release_seat(slot):
    """A seat left ACCEPTED: BOOKED -> OPEN once the pool is non-empty again."""
    if slot is None:
        return
    if slot["status"] == "BOOKED" and calc.booked_count(slot) < slot["applicant_capacity"]:
        slot["status"] = "OPEN"
    touch(slot)


def consume_seat(slot):
    if slot["status"] == "OPEN" and calc.booked_count(slot) >= slot["applicant_capacity"]:
        slot["status"] = "BOOKED"
    touch(slot)


def revert_to_not_invited(application):
    """INVITED/SCHEDULED -> NOT_INVITED once no active invitation remains."""
    if application is None:
        return False
    if application["interview_status"] not in ("INVITED", "SCHEDULED"):
        return False
    if application_has_active_invitation(application["id"]):
        return False
    application["interview_status"] = "NOT_INVITED"
    touch(application)
    return True


def promote_waitlist(wave):
    """Promote the selector's winner into the freed seat, if there is one."""
    if wave is None or wave["status"] != "RELEASED":
        return None
    if calc.issued_count(wave) >= wave["seat_capacity"]:
        return None
    winner = calc.waitlist_winner(wave, lambda app_id: find("applications", app_id))
    if winner is None:
        return None
    winner["status"] = "ISSUED"
    stamp_issued(winner, wave)
    touch(winner)
    application = find("applications", winner["application_id"])
    if application is not None and application["interview_status"] == "NOT_INVITED":
        application["interview_status"] = "INVITED"
        touch(application)
    touch(wave)
    return winner


def recompute_program_counters(program):
    """The counters are derived; writing the row is what the PRD observes."""
    if program is not None:
        touch(program)


# ------------------------------------------------------------------ loads
def refresh_faculty(faculty_ids):
    for faculty_id in faculty_ids:
        faculty = find("faculty_members", faculty_id)
        if faculty is not None:
            touch(faculty)


# ------------------------------------------------------------------ cascades
def withdraw_application_cascade(application):
    """§3.2: the applicant-withdrawal cascade from ADVANCED."""
    program = program_of_application(application)
    freed_waves = []
    for invitation in calc.application_invitations(application["id"]):
        status = invitation["status"]
        if status not in ACTIVE_INVITATION_STATUSES:
            continue
        wave = wave_of_invitation(invitation)
        invitation["status"] = "WITHDRAWN"
        if status == "ACCEPTED":
            slot = find("interview_slots", invitation["slot_id"])
            invitation["slot_id"] = None
            release_seat(slot)
        touch(invitation)
        if status in ("ISSUED", "ACCEPTED") and wave is not None:
            touch(wave)
            freed_waves.append(wave)

    if application["interview_status"] in ("INVITED", "SCHEDULED"):
        application["interview_status"] = "CANCELLED"

    for wave in freed_waves:
        promote_waitlist(wave)

    recompute_program_counters(program)


def close_wave_cascade(wave):
    """§3.4: wholesale lapse of every unanswered and waitlisted invitation."""
    program = program_of_wave(wave)
    touched_applications = []
    for invitation in calc.wave_invitations(wave["id"]):
        if invitation["status"] not in ("ISSUED", "WAITLISTED"):
            continue
        invitation["status"] = "EXPIRED"
        invitation["expires_at"] = invitation["expires_at"] or iso(now())
        touch(invitation)
        application = application_of_invitation(invitation)
        if application is not None:
            touched_applications.append(application)
    for application in touched_applications:
        revert_to_not_invited(application)
    recompute_program_counters(program)


def cancel_slot_cascade(slot):
    """§3.5: cancelling a block releases seats and panel seats."""
    program = program_of_slot(slot)
    was_booked = slot["status"] == "BOOKED"
    affected_applications = []

    for invitation in calc.slot_invitations(slot["id"]):
        if invitation["status"] != "ACCEPTED":
            continue
        invitation["status"] = "WITHDRAWN"
        invitation["slot_id"] = None
        touch(invitation)
        application = application_of_invitation(invitation)
        if application is not None:
            affected_applications.append(application)
        wave = wave_of_invitation(invitation)
        if wave is not None:
            touch(wave)

    for application in affected_applications:
        if application["interview_status"] == "SCHEDULED":
            application["interview_status"] = "NOT_INVITED"
            touch(application)

    faculty_ids = []
    for assignment in calc.slot_assignments(slot["id"]):
        if assignment["status"] == "ASSIGNED":
            assignment["status"] = "RELEASED"
            touch(assignment)
            faculty_ids.append(assignment["faculty_member_id"])
    refresh_faculty(faculty_ids)

    if was_booked:
        recompute_program_counters(program)


def void_packet(contract):
    for item in calc.contract_items(contract["id"]):
        if item["status"] in ("PENDING", "SUBMITTED", "REJECTED"):
            item["status"] = "VOIDED"
            touch(item)


def rescind_cascade(contract):
    """§3.9: the three-hop position-conservation cascade plus the packet void."""
    result = result_of_contract(contract)
    program = None
    if result is not None and result["outcome"] == "MATCHED":
        result["outcome"] = "VACATED"
        result["matched_rank_position"] = None
        touch(result)
        program = find("programs", result["program_id"])
        if program is not None:
            touch(program)
            if (
                program["season_phase"] == "SEASON_CLOSED"
                and program["soap_participating"]
                and calc.unfilled_positions(program) >= 1
            ):
                program["season_phase"] = "SOAP_ACTIVE"
    void_packet(contract)
    return program
