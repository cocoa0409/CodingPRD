"""Composite setup builders (the named setup macros the design indices cite).

The server is restarted with an empty database before every individual test, so
each test runs its own full setup chain. These builders are the chains the design
recipes name: TEMPLATE A, ACCEPT_INTAKE and TEMPLATE B.

Every setup call goes through the lenient ``get_success_data`` validator so a
broken setup step fails loudly with the server's own error id rather than
surfacing later as a confusing assertion failure inside the trigger.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories
from .api_client import ApiClient
from .constants import CLOCK_BASE_UTC
from .test_users import (
    grant_analyst_headers,
    make_case_representative_headers,
    make_client_portal_headers,
    make_intake_screener_headers,
    make_supervising_attorney_headers,
    program_director_headers,
)


class Env:
    """Mutable holder for the ids a setup chain produced.

    Attribute access is the same as key access, so a test can read
    ``env.matter_id`` or ``env["matter_id"]`` interchangeably.
    """

    def __init__(self, api: ApiClient):
        self.api = api
        self._ids: Dict[str, Any] = {}

    # -- id bag ------------------------------------------------------------
    def __getitem__(self, key: str) -> Any:
        return self._ids[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self._ids[key] = value

    def __contains__(self, key: str) -> bool:
        return key in self._ids

    def __getattr__(self, key: str) -> Any:
        try:
            return self.__dict__["_ids"][key]
        except KeyError:
            raise AttributeError(key)

    def set(self, **kwargs: Any) -> None:
        self._ids.update(kwargs)

    # -- identity shortcuts ------------------------------------------------
    @property
    def director(self) -> Dict[str, str]:
        return program_director_headers()

    @property
    def analyst(self) -> Dict[str, str]:
        return grant_analyst_headers()

    @property
    def screener(self) -> Dict[str, str]:
        return make_intake_screener_headers(self["screener_id"])

    @property
    def supervisor(self) -> Dict[str, str]:
        """SupervisingAttorney acting as Ben Cole (${atty_b_id})."""
        return make_supervising_attorney_headers(self["atty_b_id"])

    @property
    def lead_rep(self) -> Dict[str, str]:
        """CaseRepresentative acting as Ada Ortiz (${atty_a_id}), the ACTIVE LEAD."""
        return make_case_representative_headers(self["atty_a_id"])

    @property
    def portal(self) -> Dict[str, str]:
        return make_client_portal_headers(self["client_id"])

    def rep_headers(self, representative_id: str) -> Dict[str, str]:
        return make_case_representative_headers(representative_id)

    def attorney_headers(self, representative_id: str) -> Dict[str, str]:
        return make_supervising_attorney_headers(representative_id)

    # -- convenience reads -------------------------------------------------
    def matter(self, matter_id: Optional[str] = None) -> Dict[str, Any]:
        target = matter_id or self["matter_id"]
        return get_success_data(self.api.get_matter(target, headers=self.director))

    def matter_version(self, matter_id: Optional[str] = None) -> int:
        return self.matter(matter_id)["version"]

    def cycle(self, cycle_id: Optional[str] = None) -> Dict[str, Any]:
        target = cycle_id or self["cycle_id"]
        return get_success_data(
            self.api.get_capacity_cycle(target, headers=self.director)
        )

    def representative(self, representative_id: str) -> Dict[str, Any]:
        return get_success_data(
            self.api.get_representative(representative_id, headers=self.director)
        )

    def intake(self, intake_id: Optional[str] = None) -> Dict[str, Any]:
        target = intake_id or self["intake_id"]
        return get_success_data(self.api.get_intake(target, headers=self.director))

    def assignment(self, assignment_id: str) -> Dict[str, Any]:
        return get_success_data(
            self.api.get_assignment(assignment_id, headers=self.director)
        )

    def declaration(self, declaration_id: str) -> Dict[str, Any]:
        rowset = get_success_data(self.api.list_declarations(headers=self.director))
        for row in rowset:
            if row["id"] == declaration_id:
                return row
        raise AssertionError("declaration {0} not listed".format(declaration_id))

    def evidence_item(self, item_id: str, matter_id: Optional[str] = None) -> Dict[str, Any]:
        params = {"matter_id": matter_id or self["matter_id"], "limit": 100}
        rowset = get_success_data(
            self.api.list_evidence(params=params, headers=self.director)
        )
        for row in rowset:
            if row["id"] == item_id:
                return row
        raise AssertionError("evidence item {0} not listed".format(item_id))

    def session(self, session_id: str) -> Dict[str, Any]:
        rowset = get_success_data(
            self.api.list_sessions(params={"limit": 100}, headers=self.director)
        )
        for row in rowset:
            if row["id"] == session_id:
                return row
        raise AssertionError("interpretation session {0} not listed".format(session_id))

    def event(self, event_id: str) -> Dict[str, Any]:
        rowset = get_success_data(
            self.api.list_events(params={"limit": 100}, headers=self.director)
        )
        for row in rowset:
            if row["id"] == event_id:
                return row
        raise AssertionError("calendar event {0} not listed".format(event_id))

    def informed_decision(self, decision_id: str) -> Dict[str, Any]:
        rowset = get_success_data(
            self.api.list_informed_decisions(
                params={"limit": 100}, headers=self.director
            )
        )
        for row in rowset:
            if row["id"] == decision_id:
                return row
        raise AssertionError("informed decision {0} not listed".format(decision_id))

    def accreditation(self, accreditation_id: str) -> Dict[str, Any]:
        return get_success_data(
            self.api.get_accreditation(accreditation_id, headers=self.director)
        )

    def recognition(self, recognition_id: str) -> Dict[str, Any]:
        return get_success_data(
            self.api.get_recognition(recognition_id, headers=self.director)
        )

    def client_row(self, client_id: Optional[str] = None) -> Dict[str, Any]:
        target = client_id or self["client_id"]
        return get_success_data(self.api.get_client(target, headers=self.director))


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------


def set_clock(api: ApiClient, to_iso8601: str = CLOCK_BASE_UTC) -> None:
    get_success_data(api.set_clock(to_iso8601, headers=program_director_headers()))


# ---------------------------------------------------------------------------
# ACCEPT_INTAKE(client, case_type, detained)
# ---------------------------------------------------------------------------


def accept_intake(
    env: Env,
    client_id: str,
    case_type: str = "U_VISA",
    detained: bool = False,
    decision_reason_code: str = "ACCEPTED_ON_MERIT",
    **intake_fields: Any
) -> Dict[str, Any]:
    """Open, screen and ACCEPT a screening, returning the minted matter.

    Four calls: create as IntakeScreener, /screen as the same screener, /decide
    ACCEPT as SupervisingAttorney (a different human, so segregation of duties
    is satisfied), then discover the matter through the list endpoint -- the
    only discovery channel a matter minted by acceptance has.
    """
    api = env.api
    payload = factories.intake_payload(
        client_id, env["cycle_id"], case_type=case_type, detained=detained
    )
    payload.update(intake_fields)
    intake = get_success_data(api.create_intake(payload, headers=env.screener))
    get_success_data(api.screen_intake(intake["id"], headers=env.screener))
    get_success_data(
        api.decide_intake(
            intake["id"],
            {"decision": "ACCEPT", "decision_reason_code": decision_reason_code},
            headers=env.supervisor,
        )
    )
    rowset = get_success_data(
        api.list_matters(params={"intake_id": intake["id"]}, headers=env.director)
    )
    assert rowset, "acceptance minted no CaseMatter discoverable by intake_id"
    matter = rowset[0]
    matter["intake_id_used"] = intake["id"]
    return matter


def create_client(env: Env, **overrides: Any) -> Dict[str, Any]:
    """Register a client as IntakeScreener."""
    return get_success_data(
        env.api.create_client(
            factories.client_payload(**overrides), headers=env.screener
        )
    )


# ---------------------------------------------------------------------------
# TEMPLATE A -- clock, cycle, three representatives, one accepted U_VISA matter
# with an ACTIVE LEAD.
# ---------------------------------------------------------------------------


def template_a(
    api: ApiClient,
    clock: str = CLOCK_BASE_UTC,
    total_case_slots: int = 10,
    reserved_detained_slots: int = 2,
    case_type: str = "U_VISA",
    detained: bool = False,
    facility_id: Optional[str] = None,
    intake_fields: Optional[Dict[str, Any]] = None,
    client_overrides: Optional[Dict[str, Any]] = None,
    activate_lead: bool = True,
) -> Env:
    """Twelve calls producing the baseline world every recipe starts from.

    Resulting state: CaseMatter.representation_status STAFFED,
    filing_status PRE_FILING, Representative(Ada Ortiz).active_case_load 1.
    """
    env = Env(api)
    director = program_director_headers()

    # 1. logical clock
    get_success_data(api.set_clock(clock, headers=director))

    # 2. capacity cycle
    cycle = get_success_data(
        api.create_capacity_cycle(
            factories.cycle_payload(
                cycle_label="FY26-H2",
                total_case_slots=total_case_slots,
                reserved_detained_slots=reserved_detained_slots,
            ),
            headers=director,
        )
    )
    env["cycle_id"] = cycle["id"]

    # 3-5. three staff attorneys: the lead, the supervising attorney, the screener
    atty_a = get_success_data(
        api.create_representative(
            factories.staff_attorney_payload(
                full_name="Ada Ortiz", bar_number="BAR-1001"
            ),
            headers=director,
        )
    )
    atty_b = get_success_data(
        api.create_representative(
            factories.staff_attorney_payload(
                full_name="Ben Cole", bar_number="BAR-2002"
            ),
            headers=director,
        )
    )
    screener = get_success_data(
        api.create_representative(
            factories.staff_attorney_payload(
                full_name="Sara Ruiz", bar_number="BAR-3003"
            ),
            headers=director,
        )
    )
    env.set(
        atty_a_id=atty_a["id"], atty_b_id=atty_b["id"], screener_id=screener["id"]
    )

    # 6. the client, registered by the screener
    client = get_success_data(
        api.create_client(
            factories.client_payload(**(client_overrides or {})),
            headers=env.screener,
        )
    )
    env["client_id"] = client["id"]

    # 7-10. intake -> screen -> accept -> discover the matter
    fields: Dict[str, Any] = dict(intake_fields or {})
    if facility_id is not None:
        fields["facility_id"] = facility_id
    matter = accept_intake(
        env,
        client["id"],
        case_type=case_type,
        detained=detained,
        decision_reason_code=(
            "ACCEPTED_DETAINED_PRIORITY" if detained else "ACCEPTED_ON_MERIT"
        ),
        **fields
    )
    env.set(
        matter_id=matter["id"],
        matter_v1=matter["version"],
        intake_id=matter["intake_id_used"],
    )

    # 11-12. Ada Ortiz becomes the LEAD and is activated
    lead = get_success_data(
        api.create_assignment(
            factories.assignment_payload(
                matter["id"], atty_a["id"], matter["version"], role_on_case="LEAD"
            ),
            headers=env.supervisor,
        )
    )
    env["lead_id"] = lead["id"]
    if activate_lead:
        get_success_data(
            api.transition_assignment(
                lead["id"], {"action": "ACTIVATE"}, headers=env.supervisor
            )
        )
    return env


# ---------------------------------------------------------------------------
# TEMPLATE B -- TEMPLATE A plus a CO_COUNSEL, a CERTIFIED declaration and the
# completed read-back session that unblocked it.
# ---------------------------------------------------------------------------


def template_b(
    api: Optional[ApiClient] = None,
    env: Optional[Env] = None,
    declaration_language: str = "es",
    session_language: Optional[str] = None,
    actual_minutes: int = 45,
    **template_a_kwargs: Any
) -> Env:
    """TEMPLATE A steps 1-12 followed by steps 13-20.

    Resulting state: representation_status STAFFED, filing_status PRE_FILING,
    Declaration.status CERTIFIED, readback_completed true and
    CaseMatter.interpretation_cost_cents 7125 for a 45-minute 'es' session.
    """
    if env is None:
        assert api is not None, "template_b needs either an api client or an Env"
        env = template_a(api, **template_a_kwargs)
    api = env.api
    lang = session_language or declaration_language

    # 13-15. Ben Cole joins as CO_COUNSEL against a refreshed matter token
    matter_v2 = env.matter_version()
    cocounsel = get_success_data(
        api.create_assignment(
            factories.assignment_payload(
                env["matter_id"],
                env["atty_b_id"],
                matter_v2,
                role_on_case="CO_COUNSEL",
            ),
            headers=env.supervisor,
        )
    )
    env["cocounsel_id"] = cocounsel["id"]
    get_success_data(
        api.transition_assignment(
            cocounsel["id"], {"action": "ACTIVATE"}, headers=env.supervisor
        )
    )

    # 16. the declaration, prepared by the LEAD
    declaration = get_success_data(
        api.create_declaration(
            factories.declaration_payload(
                env["matter_id"], env["lead_id"], language_code=declaration_language
            ),
            headers=env.lead_rep,
        )
    )
    env["decl_id"] = declaration["id"]

    # 17-18. the read-back session, booked then completed
    session = get_success_data(
        api.create_session(
            factories.session_payload(env["matter_id"], language_code=lang),
            headers=env.supervisor,
        )
    )
    env["sess_id"] = session["id"]
    get_success_data(
        api.transition_session(
            session["id"],
            {"action": "COMPLETE", "actual_minutes": actual_minutes},
            headers=env.supervisor,
        )
    )

    # 19-20. submit then certify, the certifier being a different human
    get_success_data(
        api.transition_declaration(
            declaration["id"],
            {"action": "SUBMIT_FOR_REVIEW"},
            headers=env.lead_rep,
        )
    )
    get_success_data(
        api.transition_declaration(
            declaration["id"],
            {"action": "CERTIFY", "reviewer_assignment_id": env["cocounsel_id"]},
            headers=env.supervisor,
        )
    )
    return env


# ---------------------------------------------------------------------------
# Smaller shared chains
# ---------------------------------------------------------------------------


def recognition_with_accredited_rep(
    env: Env,
    full_name: str = "Nadia Rey",
    accreditation_type: str = "FULL",
    requested_forums: Optional[List[str]] = None,
    recognition_id: Optional[str] = None,
    approve: bool = True,
) -> Dict[str, Any]:
    """Create (or reuse) a recognition, then an accredited representative under it.

    Returns a dict with ``recognition_id``, ``representative_id`` and
    ``accreditation_id``. Approval is performed by the SupervisingAttorney, who
    is never the accreditation's own subject, so no self-approval occurs.
    """
    api = env.api
    director = program_director_headers()
    if recognition_id is None:
        recognition = get_success_data(
            api.create_recognition(factories.recognition_payload(), headers=director)
        )
        recognition_id = recognition["id"]
    rep = get_success_data(
        api.create_representative(
            factories.accredited_rep_payload(full_name=full_name), headers=director
        )
    )
    accreditation = get_success_data(
        api.create_accreditation(
            factories.accreditation_payload(
                rep["id"],
                recognition_id,
                accreditation_type=accreditation_type,
                requested_forums=requested_forums,
            ),
            headers=director,
        )
    )
    if approve:
        get_success_data(
            api.transition_accreditation(
                accreditation["id"],
                {"action": "APPROVE", "decision_reason_code": "CREDENTIALS_VERIFIED"},
                headers=env.supervisor,
            )
        )
    return {
        "recognition_id": recognition_id,
        "representative_id": rep["id"],
        "accreditation_id": accreditation["id"],
    }


def add_evidence(
    env: Env,
    weights: List[int],
    tier: str = "REQUIRED",
    matter_id: Optional[str] = None,
    **overrides: Any
) -> List[str]:
    """Create one evidence item per weight, returning their ids in order."""
    target = matter_id or env["matter_id"]
    ids: List[str] = []
    for weight in weights:
        item = get_success_data(
            env.api.create_evidence(
                factories.evidence_payload(
                    target, tier=tier, weight_points=weight, **overrides
                ),
                headers=env.lead_rep,
            )
        )
        ids.append(item["id"])
    return ids


def drive_evidence(env: Env, item_id: str, *actions: str, **payload: Any) -> None:
    """Apply a sequence of evidence transitions with one shared payload."""
    for action in actions:
        body: Dict[str, Any] = {"action": action}
        body.update(payload)
        get_success_data(
            env.api.transition_evidence(item_id, body, headers=env.lead_rep)
        )


def add_supervisor_assignment(env: Env, representative_id: str) -> str:
    """Create and ACTIVATE a SUPERVISOR assignment on the baseline matter."""
    api = env.api
    supervisor = get_success_data(
        api.create_assignment(
            factories.assignment_payload(
                env["matter_id"],
                representative_id,
                env.matter_version(),
                role_on_case="SUPERVISOR",
            ),
            headers=env.supervisor,
        )
    )
    get_success_data(
        api.transition_assignment(
            supervisor["id"], {"action": "ACTIVATE"}, headers=env.supervisor
        )
    )
    return supervisor["id"]


# ---------------------------------------------------------------------------
# minimal_world -- clock, one cycle, one screener and one deciding attorney.
# ---------------------------------------------------------------------------


def minimal_world(
    api: ApiClient,
    clock: str = "2026-09-01T00:00:00.000Z",
    cycle_label: str = "FY27-Q1",
    period_start_date: str = "2026-08-01",
    period_end_date: str = "2026-12-31",
    total_case_slots: int = 20,
    reserved_detained_slots: int = 4,
    languages: Optional[List[str]] = None,
    decider_max_case_load: int = 10,
) -> Env:
    """The smallest world in which an intake can be screened and decided.

    Two distinct staff attorneys are created so that the screener and the
    decision maker are never the same person: the screening act stamps
    ``screener_representative_id`` and the decision act compares against it.

    ``atty_b_id`` is aliased to the decider so the shared ``Env.supervisor``
    property and :func:`accept_intake` work unchanged.
    """
    env = Env(api)
    director = program_director_headers()
    langs = list(languages or ["en"])

    get_success_data(api.set_clock(clock, headers=director))
    cycle = get_success_data(
        api.create_capacity_cycle(
            factories.cycle_payload(
                cycle_label=cycle_label,
                period_start_date=period_start_date,
                period_end_date=period_end_date,
                total_case_slots=total_case_slots,
                reserved_detained_slots=reserved_detained_slots,
            ),
            headers=director,
        )
    )
    env["cycle_id"] = cycle["id"]

    screener = get_success_data(
        api.create_representative(
            factories.staff_attorney_payload(
                full_name="Nadia Okonjo",
                languages=langs,
                max_case_load=25,
                max_supervisees=6,
            ),
            headers=director,
        )
    )
    decider = get_success_data(
        api.create_representative(
            factories.staff_attorney_payload(
                full_name="Dov Halberstam",
                languages=langs,
                max_case_load=decider_max_case_load,
                max_supervisees=5,
            ),
            headers=director,
        )
    )
    env.set(
        screener_id=screener["id"],
        atty_a_id=decider["id"],
        atty_b_id=decider["id"],
    )
    return env


def new_client(env: Env, **overrides: Any) -> str:
    """Register a client through the ProgramDirector and return its id."""
    row = get_success_data(
        env.api.create_client(
            factories.client_payload(**overrides), headers=program_director_headers()
        )
    )
    return row["id"]
