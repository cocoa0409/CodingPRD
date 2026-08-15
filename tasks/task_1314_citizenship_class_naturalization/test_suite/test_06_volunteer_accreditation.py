"""Volunteers, training credits, and the accreditation lifecycle (PRD §3.5)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_same_instant,
    assert_volunteer,
    accredit_volunteer,
    add_training_credit,
    complete_workshop,
    create_general_volunteer,
    create_legal_volunteer,
    create_program,
    create_volunteer,
    create_workshop,
    get_volunteer,
    set_clock,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["program_admin_headers"]


class TestTrainingWindow:
    def test_training_window_730_day_inclusive_boundary(self, api):
        """PRD §3.5: "The volunteer's `training_hours_24mo` is a sliding aggregate:
        the sum of `hours` over credits whose `earned_at` is at or after the instant
        730 days before the current clock reading. The boundary is inclusive — a
        credit earned exactly 730 days ago still counts — and the window slides
        forward whenever the logical clock advances, so hours can age out without any
        new records being written."

        Design: Corner/calculations/training_window_730_day_inclusive_boundary
        """
        create_program()
        volunteer = create_volunteer(full_name="Window Vol")
        # The clock reads 2026-08-01T00:00:00Z; 730 days earlier is 2024-08-01.
        add_training_credit(volunteer["id"], 6, topic="boundary",
                            earned_at="2024-08-01T00:00:00Z")
        add_training_credit(volunteer["id"], 5, topic="expired",
                            earned_at="2024-07-31T00:00:00Z")
        add_training_credit(volunteer["id"], 4, topic="recent",
                            earned_at="2026-01-01T00:00:00Z")

        current = get_volunteer(volunteer["id"])
        assert_volunteer(current)
        assert current["training_hours_24mo"] == 10, (
            "6 boundary-included hours plus 4 recent hours; the 5-hour credit earned "
            "2024-07-31 is 731 days old and must be excluded"
        )


class TestAccreditationGates:
    def test_accredit_general_training_hours_boundary(self, api):
        """PRD §3.5: "Moving `TRAINEE` → `GENERAL` requires
        `background_check_cleared` to be true and `training_hours_24mo` of at least
        `general_training_hours`; any shortfall rejects with
        `ERR_ACCREDITATION_INSUFFICIENT`."
        PRD §3.5: "Both transitions stamp `accredited_at` at the current clock on
        success."

        Design: Corner/calculations/accredit_general_training_hours_boundary
        """
        create_program()
        volunteer_9 = create_volunteer(full_name="W9")
        add_training_credit(volunteer_9["id"], 9)
        volunteer_10 = create_volunteer(full_name="W10")
        add_training_credit(volunteer_10["id"], 10)

        rejected = api.accredit_volunteer(volunteer_9["id"], {"target_level": "GENERAL"},
                                          ADMIN)
        validate_error(rejected, ApiErrorId.ERR_ACCREDITATION_INSUFFICIENT)
        assert get_volunteer(volunteer_9["id"])["accreditation_level"] == "TRAINEE"

        accredited = validate_success(
            api.accredit_volunteer(volunteer_10["id"], {"target_level": "GENERAL"},
                                   ADMIN),
            200,
        )
        assert accredited["accreditation_level"] == "GENERAL", (
            "ten hours meets the default ten-hour requirement inclusively"
        )
        assert_same_instant(accredited["accredited_at"], "2026-08-01T00:00:00Z",
                            "accredited_at stamps the logical clock")

    def test_legal_accreditation_via_supervised_hours_path(self, api):
        """PRD §3.5: "Moving `GENERAL` → `LEGAL` requires either a non-null
        `bar_number` or `supervised_hours` of at least `legal_supervised_hours`; the
        same error covers a shortfall on this path."
        PRD §3.6: "Completion cascades: every `RESERVED` seat of the workshop flips to
        `ATTENDED`, and when an `assisting_volunteer_id` was named, that volunteer's
        `supervised_hours` increases by `duration_hours` — the credit that builds the
        supervised-hours path to `LEGAL`."

        Design: Corner/calculations/legal_accreditation_via_supervised_hours_path
        """
        create_program()
        supervisor = create_legal_volunteer(full_name="Sup Vol", bar_number="BAR111")
        assistant = create_general_volunteer(full_name="Asst Vol")  # no bar number
        workshop_5 = create_workshop(supervisor["id"],
                                     assisting_volunteer_id=assistant["id"],
                                     scheduled_start="2026-08-05T10:00:00Z",
                                     duration_hours=5, capacity=3, title="WS5")
        workshop_3 = create_workshop(supervisor["id"],
                                     assisting_volunteer_id=assistant["id"],
                                     scheduled_start="2026-08-06T10:00:00Z",
                                     duration_hours=3, capacity=3, title="WS3")
        set_clock("2026-08-06T11:00:00Z")
        complete_workshop(workshop_5["id"], supervisor["id"])
        assert get_volunteer(assistant["id"])["supervised_hours"] == 5

        rejected = api.accredit_volunteer(assistant["id"], {"target_level": "LEGAL"},
                                          ADMIN)
        validate_error(rejected, ApiErrorId.ERR_ACCREDITATION_INSUFFICIENT)

        complete_workshop(workshop_3["id"], supervisor["id"])
        assert get_volunteer(assistant["id"])["supervised_hours"] == 8
        accredited = validate_success(
            api.accredit_volunteer(assistant["id"], {"target_level": "LEGAL"}, ADMIN),
            200,
        )
        assert accredited["accreditation_level"] == "LEGAL", (
            "eight supervised hours meets the default eight-hour requirement "
            "inclusively, without a bar number"
        )


class TestLapseAndRenewalCycle:
    def test_volunteer_accreditation_lapse_renewal_cycle(self, api):
        """PRD §2.5: "Volunteers holding `GENERAL` or `LEGAL` accreditation whose
        accreditation anniversary — `accredited_at` plus the Program's
        `accreditation_valid_months` — falls strictly earlier than the new clock
        reading lapse to `LAPSED`. An accreditation whose anniversary lands exactly at
        the clock reading survives."
        PRD §3.5: "a `ProgramAdmin` may renew a `LAPSED` volunteer, and the volunteer
        returns to exactly the level recorded in `lapsed_from_level` — `LAPSED` →
        `GENERAL` when the lapse was from `GENERAL`, `LAPSED` → `LEGAL` when the lapse
        was from `LEGAL` — provided `training_hours_24mo` is at least
        `renewal_training_hours`, else the renewal rejects with
        `ERR_ACCREDITATION_INSUFFICIENT`."

        Design: Difficulty/non_linear_state_machine/volunteer_accreditation_lapse_renewal_cycle
        """
        create_program()
        # Accredited GENERAL at the default clock 2026-08-01 with one 10-hour credit
        # earned 2026-07-01.
        volunteer = create_general_volunteer(full_name="Vic Torres")
        assert volunteer["accreditation_level"] == "GENERAL"

        # Anniversary: 2026-08-01 + 24 months = 2028-08-01, strictly before the new
        # clock reading, so the sweep lapses the accreditation. The 2026-07-01 credit
        # is then more than 730 days old and has aged out of the window.
        set_clock("2028-08-02T00:00:00Z")
        lapsed = get_volunteer(volunteer["id"])
        assert lapsed["accreditation_level"] == "LAPSED"
        assert lapsed["lapsed_from_level"] == "GENERAL"
        assert lapsed["training_hours_24mo"] == 0

        rejected = api.renew_volunteer(volunteer["id"], ADMIN)
        validate_error(rejected, ApiErrorId.ERR_ACCREDITATION_INSUFFICIENT)

        add_training_credit(volunteer["id"], 4, topic="refresher",
                            earned_at="2028-08-01T00:00:00Z")
        renewed = validate_success(api.renew_volunteer(volunteer["id"], ADMIN), 200)
        assert_volunteer(renewed)
        assert renewed["accreditation_level"] == "GENERAL"
        assert renewed["lapsed_from_level"] is None
        assert_same_instant(renewed["accredited_at"], "2028-08-02T00:00:00Z",
                            "renewal stamps accredited_at at the clock")

    def test_volunteer_lapsed_from_legal_renews_to_legal(self, api):
        """PRD §3.5: "Renewal is the way back: a `ProgramAdmin` may renew a `LAPSED`
        volunteer, and the volunteer returns to exactly the level recorded in
        `lapsed_from_level` — `LAPSED` → `GENERAL` when the lapse was from `GENERAL`,
        `LAPSED` → `LEGAL` when the lapse was from `LEGAL` — provided
        `training_hours_24mo` is at least `renewal_training_hours`, else the renewal
        rejects with `ERR_ACCREDITATION_INSUFFICIENT`. Renewal stamps `accredited_at`
        at the clock and clears `lapsed_from_level` to null."

        Design: Difficulty/non_linear_state_machine/volunteer_accreditation_lapse_renewal_cycle
        """
        create_program()
        volunteer = create_legal_volunteer(full_name="Legal Vol", bar_number="BAR333")
        assert volunteer["accreditation_level"] == "LEGAL"

        set_clock("2028-08-02T00:00:00Z")
        lapsed = get_volunteer(volunteer["id"])
        assert lapsed["accreditation_level"] == "LAPSED"
        assert lapsed["lapsed_from_level"] == "LEGAL"

        add_training_credit(volunteer["id"], 4, topic="refresher",
                            earned_at="2028-08-01T00:00:00Z")
        renewed = validate_success(api.renew_volunteer(volunteer["id"], ADMIN), 200)
        assert renewed["accreditation_level"] == "LEGAL", (
            "renewal restores exactly the lapsed-from level"
        )
        assert renewed["lapsed_from_level"] is None
        assert_same_instant(renewed["accredited_at"], "2028-08-02T00:00:00Z")
