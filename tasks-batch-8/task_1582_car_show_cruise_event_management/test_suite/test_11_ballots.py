"""People's-choice ballot rules: duplicate, class eligibility, and window."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, make_participant_headers, create_ballot_payload,
    create_event_with_class_and_zone, create_open_event,
    create_registrant_with_vehicle, create_paid_registration,
    sign_waiver, check_in, create_voter, cast_ballot, setup_judging_event,
)

ORG = TEST_USERS["organizer_headers"]
DESK = TEST_USERS["desk_headers"]

WINDOW = {"arrival_window_start": "2026-08-15T08:00:00Z",
          "arrival_window_end": "2026-08-15T10:00:00Z"}


def _pc_event_judging(api):
    """PC-only event in JUDGING with two checked-in entries R1/R2."""
    ev, cls, zone = create_open_event(
        class_overrides={"judging_mode": "PEOPLES_CHOICE", "award_depth": 1},
        zone_overrides=WINDOW)
    regs = []
    for i, (yr, make, model) in enumerate([(1970, "Ford", "Mustang"),
                                           (1971, "Chevrolet", "Chevelle")]):
        reg, veh = create_registrant_with_vehicle(
            name=f"D{i}", email=f"d{i}@example.com",
            vehicle_overrides={"year": yr, "make": make, "model": model})
        sign_waiver(ev["id"], reg["id"], signature_name=reg["full_name"])
        regs.append(create_paid_registration(ev["id"], reg["id"], veh["id"], cls["id"]))
    get_success_data(api.set_clock({"to_iso8601": "2026-08-15T08:30:00Z"}, ORG))
    regs = [check_in(r["id"], zone["id"]) for r in regs]
    get_success_data(api.set_clock({"to_iso8601": "2026-08-15T12:30:00Z"}, ORG))
    get_success_data(api.lock_registration(ev["id"], ORG))
    get_success_data(api.start_judging(ev["id"], ORG))
    return ev, cls, zone, regs


class TestBallotRules:
    def test_duplicate_ballot_rejected(self, api):
        """PRD §3.6: "one voter gets exactly one ballot per event — a second
        attempt is rejected with `ERR_DUPLICATE_BALLOT`."

        Design: Corner/validations/duplicate_ballot_rejected
        """
        ev, cls, zone, regs = _pc_event_judging(api)
        voter = create_voter("Voter", "vt@example.com")
        first = cast_ballot(ev["id"], regs[0]["id"], voter["id"])
        resp = api.create_ballot(create_ballot_payload(ev["id"], regs[1]["id"]),
                                 make_participant_headers(voter["id"]))
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_BALLOT)
        after = validate_success(api.get_ballot(first["id"], ORG))
        assert after["status"] == "VALID"
        listed = get_success_data(api.list_ballots(
            ORG, params={"event_id": ev["id"], "voter_registrant_id": voter["id"]}))
        assert len(listed) == 1

    def test_vote_ineligible_judged_class_rejected(self, api):
        """PRD §3.6: "The target entry's class must actually be a people's-choice
        class — `judging_mode` `PEOPLES_CHOICE` or `BOTH` — and a ballot aimed at
        a `JUDGED`-only class is rejected with `ERR_VOTE_INELIGIBLE_CLASS`."

        Design: Corner/validations/vote_ineligible_judged_class_rejected
        """
        s = setup_judging_event(num_registrations=1, judged=True, award_depth=1,
                                num_judges=1)
        voter = create_voter("Voter", "vt2@example.com")
        resp = api.create_ballot(
            create_ballot_payload(s["event"]["id"], s["registrations"][0]["id"]),
            make_participant_headers(voter["id"]))
        validate_error(resp, ApiErrorId.ERR_VOTE_INELIGIBLE_CLASS)
        listed = get_success_data(api.list_ballots(
            ORG, params={"event_id": s["event"]["id"], "voter_registrant_id": voter["id"]}))
        assert listed == []

    def test_ballot_window_closed_rejected(self, api):
        """PRD §3.6: "Ballots are accepted only while the event is in `JUDGING`
        and the logical clock sits inside the ballot window, the half-open
        interval from `gates_open_at` to `ballot_close_at`; a ballot cast outside
        that window or while the event is not in `JUDGING` is rejected with
        `ERR_BALLOT_WINDOW_CLOSED`."

        Design: Corner/validations/ballot_window_closed_rejected
        """
        # Event stays in JUDGING because a judged class has an outstanding pair.
        # PRD §3.1 restricts class creation to DRAFT/PUBLISHED: create both
        # classes before opening registration.
        ev, cls_p, zone = create_event_with_class_and_zone(
            class_overrides={"code": "PCLS", "judging_mode": "PEOPLES_CHOICE",
                             "award_depth": 1},
            zone_overrides=WINDOW)
        cls_j = get_success_data(api.create_class(ev["id"], {
            "code": "JCLS", "name": "Judged", "min_year": 1950, "max_year": 1975,
            "prereg_fee_cents": 3000, "day_of_fee_cents": 4500, "capacity": 40,
            "judging_mode": "JUDGED", "award_depth": 1}, ORG))
        get_success_data(api.publish_event(ev["id"], ORG))
        ev = get_success_data(api.open_registration(ev["id"], ORG))
        regs = {}
        for key, cls_id, yr in [("r1", cls_j["id"], 1970), ("r2", cls_p["id"], 1972)]:
            reg, veh = create_registrant_with_vehicle(
                name=key.upper(), email=f"{key}@example.com",
                vehicle_overrides={"year": yr})
            sign_waiver(ev["id"], reg["id"], signature_name=reg["full_name"])
            regs[key] = create_paid_registration(ev["id"], reg["id"], veh["id"], cls_id)
        get_success_data(api.set_clock({"to_iso8601": "2026-08-15T08:30:00Z"}, ORG))
        for r in regs.values():
            check_in(r["id"], zone["id"])
        get_success_data(api.set_clock({"to_iso8601": "2026-08-15T12:30:00Z"}, ORG))
        get_success_data(api.create_judge(ev["id"], {
            "name": "J1", "email": "j1@example.com",
            "assigned_class_ids": [cls_j["id"]]}, ORG))
        get_success_data(api.lock_registration(ev["id"], ORG))
        get_success_data(api.start_judging(ev["id"], ORG))
        # Past ballot_close_at (14:30) but the event is still JUDGING.
        get_success_data(api.set_clock({"to_iso8601": "2026-08-15T15:00:00Z"}, ORG))
        voter = create_voter("Voter", "vt3@example.com")
        resp = api.create_ballot(create_ballot_payload(ev["id"], regs["r2"]["id"]),
                                 make_participant_headers(voter["id"]))
        validate_error(resp, ApiErrorId.ERR_BALLOT_WINDOW_CLOSED)
