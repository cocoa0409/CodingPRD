"""Committees and fundraising: activation gate, pledges, tiers, dissolution."""
from test_helpers import (
    ApiErrorId,
    activate_member,
    create_committee,
    create_member,
    create_open_season_with_section,
    create_pledge,
    create_pledge_payload,
    make_treasurer_headers,
    setup_active_committee_with_pledges,
    validate_error,
    validate_success,
)


class TestCommitteeActivation:
    def test_committee_activate_with_non_active_chair_rejected(
            self, api, president_headers):
        """PRD §3.9: "A committee starts `FORMING` with `raised_cents` at zero,
        and activation — `FORMING` to `ACTIVE` — requires the chair to be an
        `ACTIVE` member at that moment, else `ERR_CHAIR_NOT_ACTIVE`."

        Design: Corner/validations/committee_activate_with_non_active_chair_rejected
        """
        season, _section = create_open_season_with_section()
        chair = create_member(season["id"])  # APPLICANT, not ACTIVE
        committee = create_committee(season["id"], chair["id"])

        resp = api.transition_committee(committee["id"], "ACTIVATE",
                                        president_headers)
        validate_error(resp, ApiErrorId.ERR_CHAIR_NOT_ACTIVE)

        data = validate_success(api.get_committee(committee["id"],
                                                  president_headers))
        assert data["status"] == "FORMING", "rejected activation leaves FORMING"

    def test_pledge_on_forming_committee_rejected(self, api, treasurer_headers):
        """PRD §3.9: "Recording one takes `committee_id`, `donor_name`, and
        `amount_cents`; the committee must be `ACTIVE`, else
        `ERR_COMMITTEE_NOT_ACTIVE`."

        Design: Corner/validations/pledge_on_forming_committee_rejected
        """
        season, section = create_open_season_with_section()
        chair = activate_member(season["id"], section["id"])
        committee = create_committee(season["id"], chair["id"])  # FORMING

        resp = api.create_pledge(
            create_pledge_payload(committee["id"], "D1", 5000),
            treasurer_headers)
        validate_error(resp, ApiErrorId.ERR_COMMITTEE_NOT_ACTIVE)


class TestRecognitionTier:
    def test_recognition_tier_silver_boundary(self, api, treasurer_headers):
        """PRD §3.9: "computes the donor's `recognition_tier`: `GOLD` for a
        pledge of at least 50000 cents, `SILVER` for at least 10000 cents, and
        `BRONZE` below that, with the boundaries inclusive — exactly 10000
        cents earns `SILVER` and exactly 50000 earns `GOLD`."

        Design: Corner/calculations/recognition_tier_silver_boundary
        """
        _season, _section, _chair, committee = (
            setup_active_committee_with_pledges())
        p1 = create_pledge(committee["id"], "D1", 10000,
                           recorder_headers=make_treasurer_headers("treas-1"))
        p2 = create_pledge(committee["id"], "D2", 9999,
                           recorder_headers=make_treasurer_headers("treas-1"))

        f1 = validate_success(api.fulfill_pledge(
            p1["id"], make_treasurer_headers("treas-2")))
        assert f1["status"] == "FULFILLED"
        assert f1["recognition_tier"] == "SILVER", \
            "exactly 10000 is the inclusive SILVER boundary"

        f2 = validate_success(api.fulfill_pledge(
            p2["id"], make_treasurer_headers("treas-2")))
        assert f2["recognition_tier"] == "BRONZE", \
            "9999 is one cent below the SILVER boundary"


class TestCommitteeDissolution:
    def test_committee_dissolve_cancels_open_pledges(self, api,
                                                     president_headers,
                                                     treasurer_headers):
        """PRD §3.9: "Cancelling a `PLEDGED` pledge moves it to the terminal
        `CANCELLED`, and the same happens automatically to every
        still-`PLEDGED` pledge when its committee is dissolved; `FULFILLED`
        pledges survive dissolution untouched, and dissolution — `ACTIVE` to
        `DISSOLVED`, terminal — is the President's call."
        PRD §3.9: "recomputes the committee's `raised_cents` (the sum of its
        `FULFILLED` pledge amounts)"

        Design: Corner/state_machines/committee_dissolve_cancels_open_pledges
        """
        _season, _section, _chair, committee = (
            setup_active_committee_with_pledges(goal_cents=100000))
        pa = create_pledge(committee["id"], "Donor A", 5000,
                           recorder_headers=make_treasurer_headers("treas-1"))
        pb = create_pledge(committee["id"], "Donor B", 10000,
                           recorder_headers=make_treasurer_headers("treas-1"))
        fulfilled = validate_success(api.fulfill_pledge(
            pb["id"], make_treasurer_headers("treas-2")))
        assert fulfilled["status"] == "FULFILLED"

        dissolved = validate_success(api.transition_committee(
            committee["id"], "DISSOLVE", president_headers))
        assert dissolved["status"] == "DISSOLVED"

        pa_data = validate_success(api.get_pledge(pa["id"], treasurer_headers))
        assert pa_data["status"] == "CANCELLED", \
            "the conditional cascade cancels only still-PLEDGED pledges"
        pb_data = validate_success(api.get_pledge(pb["id"], treasurer_headers))
        assert pb_data["status"] == "FULFILLED", \
            "FULFILLED pledges survive dissolution untouched"

        committee_data = validate_success(api.get_committee(
            committee["id"], president_headers))
        assert committee_data["raised_cents"] == 10000
