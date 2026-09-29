"""Composable setup builders for the residency match season.

Every test starts against an empty database, so all state here is built by
calling the public endpoints in the order the PRD's own workflow narrative
prescribes: register a program, staff it, register applicants, open review,
review and screen, open interviews, plan a wave, staff panels, release, invite,
answer, run the block, score, close the wave, rank, deliberate, certify, run
match day, then issue and onboard the contract.

:class:`SeasonBuilder` exposes one method per hop so a test can stop anywhere
and vary any payload. The ``setup_*`` helpers below are the named stopping
points the tests actually reuse.
"""

from typing import Any

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    CLOCK_AFTER_INTERVIEW,
    CLOCK_RANKING_DAY,
    CLOCK_SEASON_START,
    CLOCK_WAVE_RELEASE,
    DEFAULT_SALARY_CENTS,
    DIRECTOR_NAME,
    LEAD_INTERVIEWER_NAME,
    MEMBER_INTERVIEWER_NAME,
    SECOND_DIRECTOR_NAME,
)
from .factories import (
    build_accept_invitation_payload,
    build_advance_phase_payload,
    build_applicant_payload,
    build_application_payload,
    build_application_review_payload,
    build_certify_payload,
    build_clock_payload,
    build_committee_vote_payload,
    build_contract_payload,
    build_credential_submit_payload,
    build_faculty_member_payload,
    build_interview_assignment_payload,
    build_interview_slot_payload,
    build_interview_wave_payload,
    build_invitation_payload,
    build_program_payload,
    build_rank_list_entry_payload,
    build_rank_list_payload,
    build_score_card_payload,
    build_screen_payload,
    build_second_applicant_payload,
    build_soap_offer_payload,
    build_third_applicant_payload,
)
from .test_users import (
    COMPLIANCE_OFFICER_HEADERS,
    NRMP_ADMIN_HEADERS,
    PROGRAM_COORDINATOR_HEADERS,
    make_applicant_headers,
    make_committee_member_headers,
    make_interviewer_headers,
    make_program_director_headers,
    make_reviewer_headers,
)
from .types import Ballot, PanelRole, ScreeningDecision, SeasonPhase

#: Canonical rubric score quadruples, one per panel seat.
SCORES_LEAD = (8, 9, 9, 9)
SCORES_MEMBER = (7, 8, 8, 8)
SCORES_THIRD = (7, 7, 8, 8)
SCORES_FOURTH = (6, 7, 7, 7)

#: The three faculty members every season walk staffs.
STANDARD_FACULTY = (
    ("pd", DIRECTOR_NAME, {"is_program_director": True, "is_committee_member": False}),
    (
        "f1",
        LEAD_INTERVIEWER_NAME,
        {"is_program_director": False, "is_committee_member": True},
    ),
    (
        "f2",
        MEMBER_INTERVIEWER_NAME,
        {"is_program_director": False, "is_committee_member": False},
    ),
)


class SeasonBuilder:
    """Walks the residency match season one declared hop at a time."""

    def __init__(self, api=None, start_clock: str | None = CLOCK_SEASON_START):
        self.api = api or api_client
        self.ids: dict[str, str] = {}
        self.rows: dict[str, dict[str, Any]] = {}
        self.wave_version: int | None = None
        self.rank_list_version: int | None = None
        if start_clock is not None:
            self.clock(start_clock)

    # ------------------------------------------------------------------
    # identity helpers
    # ------------------------------------------------------------------
    admin = NRMP_ADMIN_HEADERS
    coordinator = PROGRAM_COORDINATOR_HEADERS
    officer = COMPLIANCE_OFFICER_HEADERS

    def director(self, key: str = "pd") -> dict:
        return make_program_director_headers(self.ids[key])

    def reviewer(self, key: str) -> dict:
        return make_reviewer_headers(self.ids[key])

    def interviewer(self, key: str) -> dict:
        return make_interviewer_headers(self.ids[key])

    def committee(self, key: str) -> dict:
        return make_committee_member_headers(self.ids[key])

    def applicant(self, key: str) -> dict:
        return make_applicant_headers(self.ids[key])

    # ------------------------------------------------------------------
    # bookkeeping
    # ------------------------------------------------------------------
    def _store(self, key: str, response) -> dict[str, Any]:
        data = get_success_data(response)
        self.ids[key] = data["id"]
        self.rows[key] = data
        return data

    def id(self, key: str) -> str:
        return self.ids[key]

    # ------------------------------------------------------------------
    # logical clock
    # ------------------------------------------------------------------
    def clock(self, instant: str):
        self.api.set_current_utc(build_clock_payload(instant), self.admin)
        return self

    # ------------------------------------------------------------------
    # program, faculty, applicants
    # ------------------------------------------------------------------
    def create_program(self, key: str = "program", **overrides):
        response = self.api.create_program(
            build_program_payload(**overrides), self.admin
        )
        self._store(key, response)
        return self

    def add_faculty(self, key: str, full_name: str, **overrides):
        response = self.api.create_faculty_member(
            build_faculty_member_payload(
                self.ids["program"], full_name=full_name, **overrides
            ),
            self.coordinator,
        )
        self._store(key, response)
        return self

    def add_standard_faculty(self):
        """Staff the director plus the two panel interviewers."""
        for key, name, flags in STANDARD_FACULTY:
            self.add_faculty(key, name, **flags)
        return self

    def add_second_director(self, key: str = "pd2"):
        """A second director, needed whenever the first one is conflicted out."""
        return self.add_faculty(
            key,
            SECOND_DIRECTOR_NAME,
            is_program_director=True,
            is_committee_member=False,
        )

    def add_applicant(self, key: str = "cand1", **overrides):
        builders = {
            "cand1": build_applicant_payload,
            "cand2": build_second_applicant_payload,
            "cand3": build_third_applicant_payload,
        }
        builder = builders.get(key, build_applicant_payload)
        response = self.api.create_applicant(builder(**overrides), self.admin)
        self._store(key, response)
        return self

    def add_applicants(self, count: int = 1):
        for index in range(1, count + 1):
            key = f"cand{index}"
            if index <= 3:
                self.add_applicant(key)
            else:
                self.add_applicant(
                    key,
                    eras_id=f"E-90{index:02d}",
                    full_name=f"Applicant {index:02d}",
                    step2_score=230,
                    pipeline_program_alum=False,
                    self_identified_group=None,
                )
        return self

    # ------------------------------------------------------------------
    # season phase
    # ------------------------------------------------------------------
    def advance_phase(self, to_phase: str):
        self.api.advance_program_phase(
            self.ids["program"], build_advance_phase_payload(to_phase), self.coordinator
        )
        return self

    def open_review(self):
        return self.advance_phase(SeasonPhase.REVIEW_OPEN)

    def open_interviews(self):
        return self.advance_phase(SeasonPhase.INTERVIEWS_OPEN)

    def open_ranking(self):
        return self.advance_phase(SeasonPhase.RANKING)

    def open_soap(self):
        return self.advance_phase(SeasonPhase.SOAP_ACTIVE)

    def close_season(self):
        return self.advance_phase(SeasonPhase.SEASON_CLOSED)

    # ------------------------------------------------------------------
    # applications, reviews, screening
    # ------------------------------------------------------------------
    def add_application(self, key: str = "app1", applicant_key: str = "cand1"):
        response = self.api.create_application(
            build_application_payload(self.ids["program"], self.ids[applicant_key]),
            self.coordinator,
        )
        self._store(key, response)
        return self

    def add_reviews(
        self,
        app_key: str = "app1",
        reviewer_keys=("f1", "f2"),
        points=((30, 20, 20), (30, 20, 20)),
    ):
        for reviewer_key, (academic, experience, holistic) in zip(reviewer_keys, points):
            self.api.create_application_review(
                self.ids[app_key],
                build_application_review_payload(
                    academic_points=academic,
                    experience_points=experience,
                    holistic_points=holistic,
                ),
                self.reviewer(reviewer_key),
            )
        return self

    def screen(self, app_key: str = "app1", decision: str = ScreeningDecision.ADVANCE):
        self.api.screen_application(
            self.ids[app_key], build_screen_payload(decision), self.coordinator
        )
        return self

    def withdraw_application(
        self, app_key: str, reason: str = "Accepted a position elsewhere"
    ):
        self.api.withdraw_application(
            self.ids[app_key], {"withdrawn_reason": reason}, self.applicant(
                self._applicant_key_for(app_key)
            )
        )
        return self

    def _applicant_key_for(self, app_key: str) -> str:
        applicant_id = self.rows[app_key]["applicant_id"]
        for key, value in self.ids.items():
            if value == applicant_id and key.startswith("cand"):
                return key
        raise AssertionError(f"no applicant key recorded for {app_key}")

    # ------------------------------------------------------------------
    # waves, slots, panels
    # ------------------------------------------------------------------
    def create_wave(self, key: str = "wave1", **overrides):
        response = self.api.create_interview_wave(
            build_interview_wave_payload(self.ids["program"], **overrides),
            self.coordinator,
        )
        self._store(key, response)
        return self

    def create_slot(self, key: str = "slot1", wave_key: str = "wave1", **overrides):
        response = self.api.create_interview_slot(
            build_interview_slot_payload(self.ids[wave_key], **overrides),
            self.coordinator,
        )
        self._store(key, response)
        return self

    def assign(
        self,
        key: str,
        slot_key: str = "slot1",
        faculty_key: str = "f1",
        panel_role: str = PanelRole.LEAD,
    ):
        response = self.api.create_interview_assignment(
            build_interview_assignment_payload(
                self.ids[slot_key], self.ids[faculty_key], panel_role
            ),
            self.coordinator,
        )
        self._store(key, response)
        return self

    def staff_standard_panel(self, slot_key: str = "slot1", suffix: str = "1"):
        """Seat ``f1`` as LEAD and ``f2`` as MEMBER on one slot."""
        self.assign(f"asg{suffix}", slot_key, "f1", PanelRole.LEAD)
        self.assign(f"asg{suffix}b", slot_key, "f2", PanelRole.MEMBER)
        return self

    def release_wave(self, wave_key: str = "wave1"):
        response = self.api.release_interview_wave(
            self.ids[wave_key], self.coordinator
        )
        data = get_success_data(response)
        self.rows[wave_key] = data
        self.wave_version = data["version"]
        return self

    def close_wave(self, wave_key: str = "wave1"):
        self.api.close_interview_wave(self.ids[wave_key], self.coordinator)
        return self

    def current_wave_version(self, wave_key: str = "wave1") -> int:
        data = get_success_data(
            self.api.get_interview_wave(self.ids[wave_key], self.coordinator)
        )
        self.wave_version = data["version"]
        return data["version"]

    def issue_invitation(
        self, key: str, app_key: str = "app1", wave_key: str = "wave1"
    ):
        response = self.api.create_interview_invitation(
            self.ids[wave_key],
            build_invitation_payload(
                self.ids[app_key], self.current_wave_version(wave_key)
            ),
            self.coordinator,
        )
        self._store(key, response)
        return self

    def accept_invitation(
        self, inv_key: str, slot_key: str = "slot1", applicant_key: str = "cand1"
    ):
        self.api.accept_interview_invitation(
            self.ids[inv_key],
            build_accept_invitation_payload(self.ids[slot_key]),
            self.applicant(applicant_key),
        )
        return self

    def complete_slot(self, slot_key: str = "slot1", no_show_application_ids=None):
        payload: dict[str, Any] = {}
        if no_show_application_ids is not None:
            payload["no_show_application_ids"] = no_show_application_ids
        self.api.complete_interview_slot(self.ids[slot_key], self.coordinator, payload)
        return self

    # ------------------------------------------------------------------
    # score cards
    # ------------------------------------------------------------------
    def add_score_card(
        self,
        key: str,
        assignment_key: str,
        app_key: str = "app1",
        faculty_key: str = "f1",
        scores=SCORES_LEAD,
        submit: bool = True,
    ):
        response = self.api.create_score_card(
            build_score_card_payload(
                self.ids[assignment_key], self.ids[app_key], scores
            ),
            self.interviewer(faculty_key),
        )
        self._store(key, response)
        if submit:
            self.api.submit_score_card(self.ids[key], self.interviewer(faculty_key))
        return self

    def add_standard_score_cards(
        self, app_key: str = "app1", suffix: str = "1", submit_both: bool = True
    ):
        """Two submitted cards — the minimum a ranked application must carry."""
        self.add_score_card(
            "sc1", f"asg{suffix}", app_key, "f1", SCORES_LEAD, submit=True
        )
        self.add_score_card(
            "sc2", f"asg{suffix}b", app_key, "f2", SCORES_MEMBER, submit=submit_both
        )
        return self

    # ------------------------------------------------------------------
    # rank list, ballots, certification
    # ------------------------------------------------------------------
    def create_rank_list(self, key: str = "rank_list", director_key: str = "pd"):
        response = self.api.create_rank_list(
            build_rank_list_payload(self.ids["program"]), self.director(director_key)
        )
        data = self._store(key, response)
        self.rank_list_version = data["version"]
        return self

    def current_rank_list_version(
        self, key: str = "rank_list", director_key: str = "pd"
    ) -> int:
        data = get_success_data(
            self.api.get_rank_list(self.ids[key], self.director(director_key))
        )
        self.rank_list_version = data["version"]
        return data["version"]

    def add_entry(
        self,
        key: str,
        app_key: str,
        rank_position: int,
        rank_list_key: str = "rank_list",
        director_key: str = "pd",
    ):
        response = self.api.create_rank_list_entry(
            self.ids[rank_list_key],
            build_rank_list_entry_payload(
                self.ids[app_key],
                rank_position,
                self.current_rank_list_version(rank_list_key, director_key),
            ),
            self.director(director_key),
        )
        self._store(key, response)
        return self

    def submit_to_committee(
        self, rank_list_key: str = "rank_list", director_key: str = "pd"
    ):
        self.api.submit_rank_list_to_committee(
            self.ids[rank_list_key], self.director(director_key)
        )
        return self

    def cast_vote(
        self,
        faculty_key: str,
        ballot: str = Ballot.APPROVE,
        rank_list_key: str = "rank_list",
    ):
        self.api.create_committee_vote(
            self.ids[rank_list_key],
            build_committee_vote_payload(self.ids[faculty_key], ballot),
            self.committee(faculty_key),
        )
        return self

    def certify(
        self,
        certifier_key: str = "pd",
        rank_list_key: str = "rank_list",
        director_key: str | None = None,
    ):
        self.api.certify_rank_list(
            self.ids[rank_list_key],
            build_certify_payload(self.ids[certifier_key]),
            self.director(director_key or certifier_key),
        )
        return self

    # ------------------------------------------------------------------
    # match day, SOAP, contracts
    # ------------------------------------------------------------------
    def run_match(self):
        self.api.run_match(self.ids["program"], self.admin)
        return self

    def load_match_result(self, key: str = "match1", app_key: str = "app1"):
        rows = get_success_data(
            self.api.list_match_results(
                self.coordinator, params={"application_id": self.ids[app_key]}
            )
        )
        assert rows, f"no match result was published for {app_key}"
        self.ids[key] = rows[0]["id"]
        self.rows[key] = rows[0]
        return self

    def make_soap_offer(
        self, key: str, app_key: str, soap_round: int = 1, director_key: str = "pd"
    ):
        response = self.api.create_soap_offer(
            build_soap_offer_payload(
                self.ids["program"], self.ids[app_key], soap_round
            ),
            self.director(director_key),
        )
        self._store(key, response)
        return self

    def create_contract(
        self,
        key: str = "contract",
        match_result_key: str = "match1",
        salary_cents: int = DEFAULT_SALARY_CENTS,
    ):
        response = self.api.create_contract(
            build_contract_payload(self.ids[match_result_key], salary_cents),
            self.coordinator,
        )
        self._store(key, response)
        return self

    def sign_contract(self, key: str = "contract", applicant_key: str = "cand1"):
        self.api.sign_contract(self.ids[key], self.applicant(applicant_key))
        return self

    def load_credential_items(self, key: str = "contract"):
        """Record every packet item id under ``cred_<CREDENTIAL_TYPE>``."""
        rows = get_success_data(
            self.api.list_credential_items_of_contract(self.ids[key], self.coordinator)
        )
        for row in rows:
            self.ids[f"cred_{row['credential_type']}"] = row["id"]
            self.rows[f"cred_{row['credential_type']}"] = row
        return self

    def submit_credential(
        self, credential_type: str, reference_number: str, applicant_key: str = "cand1"
    ):
        self.api.submit_credential_item(
            self.ids[f"cred_{credential_type}"],
            build_credential_submit_payload(reference_number),
            self.applicant(applicant_key),
        )
        return self

    def verify_credential(self, credential_type: str):
        self.api.verify_credential_item(
            self.ids[f"cred_{credential_type}"], self.officer
        )
        return self


# ======================================================================
# Tier 1 — program and registry only
# ======================================================================
def setup_program(**overrides) -> SeasonBuilder:
    """A registered program in ``PRE_SEASON`` with no children."""
    return SeasonBuilder().create_program(**overrides)


def setup_staffed_program(applicant_count: int = 1, **overrides) -> SeasonBuilder:
    """A program with its director, two interviewers and its applicants."""
    builder = setup_program(**overrides)
    builder.add_standard_faculty()
    builder.add_applicants(applicant_count)
    return builder


# ======================================================================
# Tier 2 — paper review and screening
# ======================================================================
def setup_reviewed_application(
    applicant_count: int = 1, review_count: int = 2, **overrides
) -> SeasonBuilder:
    """One application per applicant, each holding ``review_count`` reviews."""
    builder = setup_staffed_program(applicant_count, **overrides)
    builder.open_review()
    for index in range(1, applicant_count + 1):
        builder.add_application(f"app{index}", f"cand{index}")
        builder.add_reviews(
            f"app{index}",
            reviewer_keys=("f1", "f2")[:review_count],
            points=((30, 20, 20), (30, 20, 20))[:review_count],
        )
    return builder


def setup_screened_application(
    applicant_count: int = 1, **overrides
) -> SeasonBuilder:
    """Every application reviewed twice and advanced through screening."""
    builder = setup_reviewed_application(applicant_count, **overrides)
    for index in range(1, applicant_count + 1):
        builder.screen(f"app{index}")
    return builder


# ======================================================================
# Tier 3 — interview scheduling
# ======================================================================
def setup_planned_wave(
    applicant_count: int = 1, seat_capacity: int = 1, slot_capacity: int = 1, **overrides
) -> SeasonBuilder:
    """A ``PLANNED`` wave with one slot and the standard two-seat panel."""
    builder = setup_screened_application(applicant_count, **overrides)
    builder.open_interviews()
    builder.create_wave(seat_capacity=seat_capacity)
    builder.create_slot(applicant_capacity=slot_capacity)
    builder.staff_standard_panel()
    return builder


def setup_released_wave(
    applicant_count: int = 1, seat_capacity: int = 1, slot_capacity: int = 1, **overrides
) -> SeasonBuilder:
    """The wave released at its ``invite_release_at`` instant."""
    builder = setup_planned_wave(
        applicant_count, seat_capacity, slot_capacity, **overrides
    )
    builder.clock(CLOCK_WAVE_RELEASE)
    builder.release_wave()
    return builder


def setup_issued_invitations(
    applicant_count: int = 1, seat_capacity: int = 1, slot_capacity: int = 1, **overrides
) -> SeasonBuilder:
    """One invitation per application, issued in applicant order."""
    builder = setup_released_wave(
        applicant_count, seat_capacity, slot_capacity, **overrides
    )
    for index in range(1, applicant_count + 1):
        builder.issue_invitation(f"inv{index}", f"app{index}")
    return builder


def setup_accepted_invitation(
    applicant_count: int = 1, seat_capacity: int = 1, slot_capacity: int = 1, **overrides
) -> SeasonBuilder:
    """The first applicant has booked the slot."""
    builder = setup_issued_invitations(
        applicant_count, seat_capacity, slot_capacity, **overrides
    )
    builder.accept_invitation("inv1", "slot1", "cand1")
    return builder


def setup_completed_interview(
    applicant_count: int = 1, seat_capacity: int = 1, slot_capacity: int = 1, **overrides
) -> SeasonBuilder:
    """The block has run, so the booked application is ``COMPLETED``."""
    builder = setup_accepted_invitation(
        applicant_count, seat_capacity, slot_capacity, **overrides
    )
    builder.clock(CLOCK_AFTER_INTERVIEW)
    builder.complete_slot()
    return builder


# ======================================================================
# Tier 4 — scoring and ranking
# ======================================================================
def setup_scored_application(
    submit_both: bool = True, **overrides
) -> SeasonBuilder:
    """Two rubric cards on the interviewed application."""
    builder = setup_completed_interview(**overrides)
    builder.add_standard_score_cards("app1", "1", submit_both=submit_both)
    return builder


def setup_ranking_phase(submit_both: bool = True, **overrides) -> SeasonBuilder:
    """Wave closed and the program advanced to ``RANKING``."""
    builder = setup_scored_application(submit_both=submit_both, **overrides)
    builder.clock(CLOCK_RANKING_DAY)
    builder.close_wave()
    builder.open_ranking()
    return builder


def setup_draft_rank_list(submit_both: bool = True, **overrides) -> SeasonBuilder:
    """An empty ``DRAFT`` rank list."""
    builder = setup_ranking_phase(submit_both=submit_both, **overrides)
    builder.create_rank_list()
    return builder


def setup_rank_list_with_entry(**overrides) -> SeasonBuilder:
    """A ``DRAFT`` rank list holding the interviewed application at position 1."""
    builder = setup_draft_rank_list(**overrides)
    builder.add_entry("entry1", "app1", 1)
    return builder


def setup_rank_list_in_committee(**overrides) -> SeasonBuilder:
    """The list sent to committee, awaiting ballots."""
    builder = setup_rank_list_with_entry(**overrides)
    builder.submit_to_committee()
    return builder


def setup_approved_rank_list(**overrides) -> SeasonBuilder:
    """The list approved by the single-member committee electorate."""
    builder = setup_rank_list_in_committee(**overrides)
    builder.cast_vote("f1", Ballot.APPROVE)
    return builder


def setup_certified_rank_list(certifier_key: str = "pd", **overrides) -> SeasonBuilder:
    """The list certified, which drives the program to ``LIST_CERTIFIED``."""
    builder = setup_approved_rank_list(**overrides)
    builder.certify(certifier_key)
    return builder


# ======================================================================
# Tier 5 — match day, SOAP and onboarding
# ======================================================================
def setup_matched_program(**overrides) -> SeasonBuilder:
    """Match day run and the winning result loaded as ``match1``."""
    builder = setup_certified_rank_list(**overrides)
    builder.run_match()
    builder.load_match_result("match1", "app1")
    return builder


def setup_issued_contract(**overrides) -> SeasonBuilder:
    """The PGY-1 agreement issued with its credential packet loaded."""
    builder = setup_matched_program(**overrides)
    builder.create_contract()
    builder.load_credential_items()
    return builder


def setup_signed_contract(**overrides) -> SeasonBuilder:
    """The agreement signed by the applicant."""
    builder = setup_issued_contract(**overrides)
    builder.sign_contract()
    return builder
