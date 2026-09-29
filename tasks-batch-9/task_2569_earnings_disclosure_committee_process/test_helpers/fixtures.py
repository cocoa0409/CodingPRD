"""Composite scenario builders and pytest fixtures.

The service under test starts with an empty database for every individual test,
so nothing here is shared across tests: each builder drives the public
endpoints from scratch, in the order the business rules allow, and returns the
records it created.

Three conventions matter throughout.

* Every seat-backed call threads the acting member's own identifier, because
  ownership, function and segregation-of-duties checks compare the resource's
  member reference to ``X-User-ID``.
* Creating a draft document reads the owning cycle's ``version`` immediately
  beforehand, and creating a tie-out line reads the owning document's
  ``version`` immediately beforehand, because every write to either parent
  advances the token the create must carry.
* Setup calls go through ``get_success_data``, which accepts any 2xx and
  reports the error identifier when a precondition could not be built.
"""

import pytest
from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import DisclosureApiClient
from .api_errors import register_error_status_map
from .constants import (
    CANON_CLOSE_END,
    CANON_CLOSE_START,
    CANON_FILING_END,
    CANON_FILING_START,
    CANON_REVIEW_END,
    CANON_REVIEW_START,
)
from .test_users import (
    admin_headers,
    make_business_leader_headers,
    make_certifying_officer_headers,
    make_chair_headers,
    make_controller_headers,
    make_investor_relations_headers,
    make_legal_counsel_headers,
)

register_error_status_map()

# A sub-certification deadline that is strictly after the logical clock's
# startup value and at or before the canonical cycle's internal target.
CANON_DUE_UTC = "2026-08-04T17:00:00Z"


# --- the committee -------------------------------------------------------

#: The standard seat roster: one member per function, an officer pair, a
#: second finance seat for reviews that need a second pair of hands, and a
#: non-voting operations leader.
STANDARD_SEATS = [
    ("fin", "Nora Finance", "FINANCE", False, True),
    ("fin2", "Pilar Ledger", "FINANCE", False, True),
    ("legal", "Owen Legal", "LEGAL", False, True),
    ("ir", "Ivy Relations", "INVESTOR_RELATIONS", False, True),
    ("ceo", "Rhea Chief", "FINANCE", True, True),
    ("cfo", "Sam Fiscal", "FINANCE", True, True),
    ("ops", "Bo Ops", "OPERATIONS", False, False),
]

MINIMAL_SEATS = [
    ("fin", "Nora Finance", "FINANCE", False, True),
    ("legal", "Owen Legal", "LEGAL", False, True),
]


class Committee:
    """A charter plus the seats on it, with header helpers per seat."""

    def __init__(self, api, charter):
        self.api = api
        self.charter = charter
        self.id = charter["id"]
        self.members = {}

    # -- seats ------------------------------------------------------------

    def seat(self, key, full_name, function, is_officer=None, voting=None):
        record = get_success_data(
            self.api.create_member(
                self.id,
                f.member_payload(full_name, function, is_officer, voting),
                admin_headers(),
            )
        )
        self.members[key] = record
        return record

    def member(self, key):
        return self.members[key]

    def mid(self, key):
        return self.members[key]["id"]

    def refresh(self, key):
        record = get_success_data(self.api.get_member(self.mid(key), admin_headers()))
        self.members[key] = record
        return record

    def reload(self):
        self.charter = get_success_data(self.api.get_charter(self.id, admin_headers()))
        return self.charter

    # -- header helpers ---------------------------------------------------

    def chair(self, key="legal"):
        return make_chair_headers(self.mid(key))

    def controller(self, key="fin"):
        return make_controller_headers(self.mid(key))

    def counsel(self, key="legal"):
        return make_legal_counsel_headers(self.mid(key))

    def relations(self, key="ir"):
        return make_investor_relations_headers(self.mid(key))

    def officer(self, key="ceo"):
        return make_certifying_officer_headers(self.mid(key))

    def leader(self, key="ops"):
        return make_business_leader_headers(self.mid(key))

    # -- charter transitions ----------------------------------------------

    def adopt(self, chair_key="legal"):
        self.charter = get_success_data(
            self.api.transition_charter(
                self.id, f.action_payload("ADOPT"), self.chair(chair_key)
            )
        )
        return self.charter

    def supersede(self, successor_charter_id, chair_key="legal"):
        self.charter = get_success_data(
            self.api.transition_charter(
                self.id,
                f.action_payload("SUPERSEDE", successor_charter_id=successor_charter_id),
                self.chair(chair_key),
            )
        )
        return self.charter

    def recuse(self, key, chair_key="legal"):
        record = get_success_data(
            self.api.transition_member(
                self.mid(key), f.action_payload("RECUSE"), self.chair(chair_key)
            )
        )
        self.members[key] = record
        return record

    def reinstate(self, key, chair_key="legal"):
        record = get_success_data(
            self.api.transition_member(
                self.mid(key), f.action_payload("REINSTATE"), self.chair(chair_key)
            )
        )
        self.members[key] = record
        return record

    def vacate(self, key, chair_key="legal"):
        record = get_success_data(
            self.api.transition_member(
                self.mid(key), f.action_payload("VACATE"), self.chair(chair_key)
            )
        )
        self.members[key] = record
        return record


def build_committee(
    api,
    seats=None,
    min_quorum_count=2,
    required_functions=None,
    name="Disclosure Committee Charter",
    version_label="2026.1",
    adopt=True,
    chair_key="legal",
):
    """Create a charter, seat its members and optionally adopt it."""
    charter = get_success_data(
        api.create_charter(
            f.charter_payload(
                name=name,
                version_label=version_label,
                min_quorum_count=min_quorum_count,
                required_functions=required_functions or ["FINANCE", "LEGAL"],
            ),
            admin_headers(),
        )
    )
    committee = Committee(api, charter)
    for key, full_name, function, is_officer, voting in (seats or STANDARD_SEATS):
        committee.seat(key, full_name, function, is_officer, voting)
    if adopt:
        committee.adopt(chair_key)
    return committee


def build_standard_committee(api):
    """The seven-seat roster on a charter requiring finance, legal and investor
    relations, adopted with a quorum of three."""
    return build_committee(
        api,
        seats=STANDARD_SEATS,
        min_quorum_count=3,
        required_functions=["FINANCE", "LEGAL", "INVESTOR_RELATIONS"],
    )


# --- the reporting cycle -------------------------------------------------


def build_cycle(api, committee, **overrides):
    """Open a reporting cycle against the committee's charter."""
    return get_success_data(
        api.create_cycle(f.cycle_payload(committee.id, **overrides), admin_headers())
    )


def refresh_cycle(api, cycle_id):
    return get_success_data(api.get_cycle(cycle_id, admin_headers()))


def cycle_version(api, cycle_id):
    """The cycle's current version, read immediately before a document create
    so that the optimistic-concurrency token is fresh."""
    return refresh_cycle(api, cycle_id)["version"]


def readiness(api, cycle_id):
    return get_success_data(api.get_readiness(cycle_id, admin_headers()))


def set_clock(api, to_iso8601):
    return get_success_data(api.set_clock(to_iso8601, admin_headers()))


# --- the calendar --------------------------------------------------------


def add_milestone(api, committee, cycle_id, kind, start, end, controller_key="fin"):
    return get_success_data(
        api.create_milestone(
            cycle_id,
            f.milestone_payload(kind, start, end),
            committee.controller(controller_key),
        )
    )


def start_milestone(api, committee, milestone_id, controller_key="fin"):
    return get_success_data(
        api.transition_milestone(
            milestone_id, f.action_payload("START"), committee.controller(controller_key)
        )
    )


def complete_milestone(api, committee, milestone_id, controller_key="fin"):
    return get_success_data(
        api.transition_milestone(
            milestone_id,
            f.action_payload("COMPLETE"),
            committee.controller(controller_key),
        )
    )


def run_milestone(api, committee, milestone_id, controller_key="fin"):
    """Start then complete a milestone, which is what the workflow unlocks
    require of the predecessor phase."""
    start_milestone(api, committee, milestone_id, controller_key)
    return complete_milestone(api, committee, milestone_id, controller_key)


def cycle_action(api, committee, cycle_id, action, headers=None, **extra):
    return get_success_data(
        api.transition_cycle(
            cycle_id,
            f.action_payload(action, **extra),
            headers if headers is not None else committee.controller(),
        )
    )


def open_close(api, committee, cycle_id):
    return cycle_action(api, committee, cycle_id, "OPEN_CLOSE")


def open_review(api, committee, cycle_id):
    return cycle_action(api, committee, cycle_id, "OPEN_REVIEW")


def open_certification(api, committee, cycle_id):
    return cycle_action(api, committee, cycle_id, "OPEN_CERTIFICATION")


def declare_filing_ready(api, committee, cycle_id, chair_key="legal"):
    return cycle_action(
        api, committee, cycle_id, "DECLARE_FILING_READY", committee.chair(chair_key)
    )


def abandon_cycle(api, committee, cycle_id):
    return cycle_action(api, committee, cycle_id, "ABANDON")


# --- sub-certifications --------------------------------------------------


def assign_subcert(
    api, committee, cycle_id, member_key, scope_area, due_utc=CANON_DUE_UTC,
    chair_key="legal",
):
    return get_success_data(
        api.create_subcert(
            f.subcert_payload(cycle_id, committee.mid(member_key), scope_area, due_utc),
            committee.chair(chair_key),
        )
    )


def submit_subcert(
    api, committee, subcert_id, member_key, exception_severity=None, exception_note=None
):
    """Submit a sub-certification as the leader who owes it."""
    return get_success_data(
        api.transition_subcert(
            subcert_id,
            f.action_payload(
                "SUBMIT",
                exception_severity=exception_severity,
                exception_note=exception_note,
            ),
            committee.leader(member_key),
        )
    )


def withdraw_subcert(api, committee, subcert_id, chair_key="legal"):
    return get_success_data(
        api.transition_subcert(
            subcert_id, f.action_payload("WITHDRAW"), committee.chair(chair_key)
        )
    )


# --- documents -----------------------------------------------------------


def create_document(
    api,
    committee,
    cycle_id,
    doc_type,
    author_key,
    title=None,
    safe_harbor_present=None,
    role="controller",
):
    """Start a draft document, reading the owning cycle's version first."""
    headers_for = {
        "controller": committee.controller,
        "counsel": committee.counsel,
        "relations": committee.relations,
    }[role]
    headers = headers_for(author_key)
    return get_success_data(
        api.create_document(
            f.document_payload(
                cycle_id,
                doc_type,
                committee.mid(author_key),
                cycle_version(api, cycle_id),
                title=title,
                safe_harbor_present=safe_harbor_present,
            ),
            headers,
        )
    )


def refresh_document(api, committee, document_id, actor_key="fin"):
    return get_success_data(
        api.get_document(document_id, committee.controller(actor_key))
    )


def document_version(api, committee, document_id, actor_key="fin"):
    """The document's current version, read immediately before a tie-out
    create so that the optimistic-concurrency token is fresh."""
    return refresh_document(api, committee, document_id, actor_key)["version"]


def submit_for_review(api, committee, document_id, actor_key="fin"):
    return get_success_data(
        api.transition_document(
            document_id,
            f.action_payload("SUBMIT_REVIEW"),
            committee.controller(actor_key),
        )
    )


def request_changes(api, committee, document_id, change_note, actor_key="legal"):
    return get_success_data(
        api.transition_document(
            document_id,
            f.action_payload("REQUEST_CHANGES", change_note=change_note),
            committee.counsel(actor_key),
        )
    )


def approve_document(api, committee, document_id, actor_key="legal"):
    return get_success_data(
        api.transition_document(
            document_id, f.action_payload("APPROVE"), committee.counsel(actor_key)
        )
    )


# --- tie-out lines -------------------------------------------------------


def add_tie_out(
    api,
    committee,
    document_id,
    line_label,
    reported_value,
    source_record_value,
    tolerance_bp=25,
    preparer_key="fin",
    controller_key="fin",
):
    """Append a tie-out line, reading the owning document's version first."""
    return get_success_data(
        api.create_tie_out_item(
            document_id,
            f.tie_out_item_payload(
                line_label,
                reported_value,
                source_record_value,
                tolerance_bp,
                committee.mid(preparer_key),
                document_version(api, committee, document_id, controller_key),
            ),
            committee.controller(controller_key),
        )
    )


def add_matching_tie_out(api, committee, document_id, line_label="Total revenue",
                         preparer_key="fin"):
    """A line whose reported figure equals its source record, so the document's
    tie-out passes and approval is not blocked on it."""
    return add_tie_out(
        api,
        committee,
        document_id,
        line_label,
        4120000,
        4120000,
        tolerance_bp=25,
        preparer_key=preparer_key,
    )


def review_tie_out(api, committee, item_id, reviewer_key, decision,
                   controller_key="fin"):
    return get_success_data(
        api.review_tie_out_item(
            item_id,
            f.tie_out_review_payload(committee.mid(reviewer_key), decision),
            committee.controller(controller_key),
        )
    )


# --- adjusted measures and questions ------------------------------------


def add_adjusted_measure(
    api,
    committee,
    document_id,
    measure_label="Adjusted EBITDA",
    adjusted_value=1200.5,
    comparable_gaap_value=1000.0,
    reconciliation_items=None,
    adjusted_prominence_index=2,
    gaap_prominence_index=1,
    controller_key="fin",
):
    return get_success_data(
        api.create_adjusted_measure(
            document_id,
            f.adjusted_measure_payload(
                measure_label,
                adjusted_value,
                comparable_gaap_value,
                reconciliation_items
                if reconciliation_items is not None
                else [
                    {"label": "Restructuring", "amount": 150.25},
                    {"label": "Impairment", "amount": 50.25},
                ],
                adjusted_prominence_index,
                gaap_prominence_index,
            ),
            committee.controller(controller_key),
        )
    )


def reconcile_measure(api, committee, measure_id, controller_key="fin", **overrides):
    return get_success_data(
        api.reconcile_adjusted_measure(
            measure_id, f.reconcile_payload(**overrides), committee.controller(controller_key)
        )
    )


def add_qa_item(
    api,
    committee,
    document_id,
    question_text="How should we frame the warranty accrual change?",
    topic="MARGIN",
    risk_tier="LOW",
    requires_safe_harbor=None,
    relations_key="ir",
):
    return get_success_data(
        api.create_qa_item(
            document_id,
            f.qa_item_payload(question_text, topic, risk_tier, requires_safe_harbor),
            committee.relations(relations_key),
        )
    )


def clear_qa_item(api, committee, qa_item_id, clearance_note="Cleared by counsel.",
                  counsel_key="legal"):
    return get_success_data(
        api.clear_qa_item(
            qa_item_id, {"clearance_note": clearance_note}, committee.counsel(counsel_key)
        )
    )


# --- material events -----------------------------------------------------


def log_material_event(
    api,
    committee,
    cycle_id,
    category="LITIGATION_JUDGMENT",
    occurred_utc="2026-07-20T00:00:00Z",
    discovered_utc="2026-07-28T00:00:00Z",
    magnitude_amount=300000,
    description="Adverse judgment in a supplier dispute",
    counsel_key="legal",
    actor="counsel",
):
    """Log a between-periods event.

    Either `ComplianceAdmin` or `LegalCounsel` may log one, so ``actor`` selects
    which credential is used. ``"counsel"`` acts from the seat named by
    ``counsel_key``, which must therefore be a LEGAL seat to satisfy that role's
    function gate; ``"admin"`` uses the opaque compliance-operations credential
    and needs no seat at all, which is what a roster carrying no LEGAL member
    requires.
    """
    headers = admin_headers() if actor == "admin" else committee.counsel(counsel_key)
    return get_success_data(
        api.create_material_event(
            cycle_id,
            f.material_event_payload(
                category, occurred_utc, discovered_utc, magnitude_amount, description
            ),
            headers,
        )
    )


def assess_event(api, committee, event_id, determination,
                 determination_note="Assessed by counsel.", counsel_key="legal"):
    return get_success_data(
        api.transition_material_event(
            event_id,
            f.action_payload(
                "ASSESS", determination=determination, determination_note=determination_note
            ),
            committee.counsel(counsel_key),
        )
    )


def disclose_event(api, committee, event_id, linked_document_id, counsel_key="legal"):
    return get_success_data(
        api.transition_material_event(
            event_id,
            f.action_payload("DISCLOSE", linked_document_id=linked_document_id),
            committee.counsel(counsel_key),
        )
    )


# --- officer certifications ---------------------------------------------


def register_cert(api, cycle_id, committee, officer_key, cert_type):
    return get_success_data(
        api.create_officer_cert(
            f.officer_cert_payload(cycle_id, committee.mid(officer_key), cert_type),
            admin_headers(),
        )
    )


def sign_cert(api, committee, cert_id, officer_key,
              attestation_text="I certify this report under section 302."):
    return get_success_data(
        api.sign_officer_cert(
            cert_id,
            {"attestation_text": attestation_text},
            committee.officer(officer_key),
        )
    )


# --- filings, corrections and deficiencies ------------------------------


def submit_filing(api, cycle_id, document_id, amends_filing_id=None):
    return get_success_data(
        api.create_filing(
            f.filing_payload(cycle_id, document_id, amends_filing_id), admin_headers()
        )
    )


def open_correction(
    api,
    filing_id,
    description="Revenue cut-off error found after submission",
    error_amount=400000,
    current_period_pretax_income=10000000,
    prior_period_pretax_income=12000000,
    cumulative_prior_uncorrected_amount=300000,
):
    return get_success_data(
        api.create_correction(
            filing_id,
            f.correction_payload(
                description,
                error_amount,
                current_period_pretax_income,
                prior_period_pretax_income,
                cumulative_prior_uncorrected_amount,
            ),
            admin_headers(),
        )
    )


def assess_correction(
    api,
    correction_id,
    method=None,
    likelihood_pct=None,
    magnitude_amount=None,
    compensating_control_present=None,
):
    return get_success_data(
        api.transition_correction(
            correction_id,
            f.assess_correction_payload(
                method, likelihood_pct, magnitude_amount, compensating_control_present
            ),
            admin_headers(),
        )
    )


def rescind_correction(api, correction_id):
    return get_success_data(
        api.transition_correction(
            correction_id, f.action_payload("RESCIND"), admin_headers()
        )
    )


def deficiencies_of(api, correction_id):
    body = get_success_data(api.list_control_deficiencies(correction_id, admin_headers()))
    return body


def mitigate_deficiency(api, deficiency_id, remediation_note="Control redesigned and retested."):
    return get_success_data(
        api.mitigate_control_deficiency(
            deficiency_id, {"remediation_note": remediation_note}, admin_headers()
        )
    )


# --- composite scenarios -------------------------------------------------


class Scenario:
    """A committee, one reporting cycle and the rows built beneath them.

    The named collections let a test reach back for a row it needs without
    re-deriving how it was created: ``milestones`` by kind, ``subcerts`` by
    seat key, ``certs`` by instrument and ``documents`` by document type.
    """

    def __init__(self, api, committee, cycle):
        self.api = api
        self.committee = committee
        self.cycle = cycle
        self.cycle_id = cycle["id"]
        self.milestones = {}
        self.subcerts = {}
        self.certs = {}
        self.documents = {}

    # -- reads ------------------------------------------------------------

    def reload(self):
        self.cycle = refresh_cycle(self.api, self.cycle_id)
        return self.cycle

    def readiness(self):
        return readiness(self.api, self.cycle_id)

    def version(self):
        return cycle_version(self.api, self.cycle_id)

    # -- calendar ---------------------------------------------------------

    def milestone(self, kind, start, end):
        row = add_milestone(self.api, self.committee, self.cycle_id, kind, start, end)
        self.milestones[kind] = row
        return row

    def standard_calendar(self, close=True, review=True, filing=True):
        """The canonical calendar: a close window, a review window two full days
        after it, and a filing window inside the statutory deadline."""
        if close:
            self.milestone("CLOSE", CANON_CLOSE_START, CANON_CLOSE_END)
        if review:
            self.milestone("REVIEW", CANON_REVIEW_START, CANON_REVIEW_END)
        if filing:
            self.milestone("FILING", CANON_FILING_START, CANON_FILING_END)
        return self.milestones

    def run(self, kind):
        row = run_milestone(self.api, self.committee, self.milestones[kind]["id"])
        self.milestones[kind] = row
        return row

    # -- workflow ---------------------------------------------------------

    def open_close(self):
        self.cycle = open_close(self.api, self.committee, self.cycle_id)
        return self.cycle

    def open_review(self):
        self.cycle = open_review(self.api, self.committee, self.cycle_id)
        return self.cycle

    def open_certification(self):
        self.cycle = open_certification(self.api, self.committee, self.cycle_id)
        return self.cycle

    def declare_filing_ready(self, chair_key="legal"):
        self.cycle = declare_filing_ready(
            self.api, self.committee, self.cycle_id, chair_key
        )
        return self.cycle

    def abandon(self):
        self.cycle = abandon_cycle(self.api, self.committee, self.cycle_id)
        return self.cycle

    # -- children ---------------------------------------------------------

    def assign(self, member_key, scope_area, due_utc=CANON_DUE_UTC):
        row = assign_subcert(
            self.api, self.committee, self.cycle_id, member_key, scope_area, due_utc
        )
        self.subcerts[member_key] = row
        return row

    def submit(self, member_key, exception_severity=None, exception_note=None):
        row = submit_subcert(
            self.api,
            self.committee,
            self.subcerts[member_key]["id"],
            member_key,
            exception_severity,
            exception_note,
        )
        self.subcerts[member_key] = row
        return row

    def document(self, doc_type, author_key="fin", title=None, safe_harbor_present=None,
                 role="controller"):
        row = create_document(
            self.api,
            self.committee,
            self.cycle_id,
            doc_type,
            author_key,
            title=title,
            safe_harbor_present=safe_harbor_present,
            role=role,
        )
        self.documents[doc_type] = row
        return row

    def cert(self, officer_key, cert_type):
        row = register_cert(self.api, self.cycle_id, self.committee, officer_key, cert_type)
        self.certs[cert_type] = row
        return row

    def sign(self, cert_type, officer_key):
        row = sign_cert(self.api, self.committee, self.certs[cert_type]["id"], officer_key)
        self.certs[cert_type] = row
        return row

    # -- shortcuts --------------------------------------------------------

    def approved_periodic_filing(self, author_key="fin", approver_key="legal"):
        """A periodic filing document taken all the way to APPROVED: one
        matching tie-out line so the tie-out gate passes, submitted for review
        by the author's own function and approved by a different member."""
        doc = self.document("PERIODIC_FILING", author_key=author_key,
                            title="Form 10-Q FY2026-Q2")
        add_matching_tie_out(self.api, self.committee, doc["id"], preparer_key=author_key)
        submit_for_review(self.api, self.committee, doc["id"], author_key)
        row = approve_document(self.api, self.committee, doc["id"], approver_key)
        self.documents["PERIODIC_FILING"] = row
        return row

    def full_coverage(self, member_key="ops", scope_area="OPERATIONS"):
        """One assigned and submitted sub-certification, which is the smallest
        non-empty scope that reads 100.00 coverage."""
        self.assign(member_key, scope_area)
        return self.submit(member_key)


def build_scenario(api, committee=None, **cycle_overrides):
    """A committee and a freshly opened cycle, which starts in PLANNING."""
    committee = committee or build_standard_committee(api)
    cycle = build_cycle(api, committee, **cycle_overrides)
    return Scenario(api, committee, cycle)


def scenario_close_open(api, committee=None, calendar=("CLOSE",), **cycle_overrides):
    """A cycle whose close is open: the calendar carries the milestones named,
    and the close-opening transition has been driven."""
    scenario = build_scenario(api, committee, **cycle_overrides)
    windows = {
        "CLOSE": (CANON_CLOSE_START, CANON_CLOSE_END),
        "REVIEW": (CANON_REVIEW_START, CANON_REVIEW_END),
        "FILING": (CANON_FILING_START, CANON_FILING_END),
    }
    for kind in calendar:
        scenario.milestone(kind, *windows[kind])
    scenario.open_close()
    return scenario


def scenario_review_open(api, committee=None, calendar=("CLOSE", "REVIEW"),
                         **cycle_overrides):
    """A cycle whose review is open: every close milestone is complete."""
    scenario = scenario_close_open(api, committee, calendar, **cycle_overrides)
    scenario.run("CLOSE")
    scenario.open_review()
    return scenario


def scenario_certification_open(api, committee=None, **cycle_overrides):
    """A cycle whose certification is open, with the full coverage, the two
    quarterly certification slots and the approved periodic filing that the
    transition requires."""
    scenario = scenario_review_open(
        api, committee, calendar=("CLOSE", "REVIEW", "FILING"), **cycle_overrides
    )
    scenario.full_coverage()
    scenario.approved_periodic_filing()
    scenario.run("REVIEW")
    scenario.cert("ceo", "CEO_302")
    scenario.cert("cfo", "CFO_302")
    scenario.open_certification()
    return scenario


def scenario_filing_ready(api, committee=None, **cycle_overrides):
    """A cycle declared filing-ready: both quarterly instruments are signed and
    the filing milestone leaves a business day of slack."""
    scenario = scenario_certification_open(api, committee, **cycle_overrides)
    scenario.sign("CEO_302", "ceo")
    scenario.sign("CFO_302", "cfo")
    scenario.declare_filing_ready()
    return scenario


def scenario_filed(api, committee=None, **cycle_overrides):
    """A cycle whose original filing has gone out."""
    scenario = scenario_filing_ready(api, committee, **cycle_overrides)
    scenario.filing = submit_filing(
        api, scenario.cycle_id, scenario.documents["PERIODIC_FILING"]["id"]
    )
    scenario.reload()
    return scenario


def scenario_with_draft_correction(api, committee=None, **correction_overrides):
    """A filed cycle carrying one post-filing correction still in DRAFT, which
    nudges the remediation axis to UNDER_EVALUATION."""
    scenario = scenario_filed(api, committee)
    scenario.correction = open_correction(
        api, scenario.filing["id"], **correction_overrides
    )
    scenario.reload()
    return scenario


# --- pytest fixtures -----------------------------------------------------


@pytest.fixture
def api():
    """The HTTP client for the service under test."""
    return DisclosureApiClient()


@pytest.fixture
def committee(api):
    """An adopted charter with the standard seat roster."""
    return build_standard_committee(api)


@pytest.fixture
def draft_committee(api):
    """A charter still in DRAFT, with its seats already filled."""
    return build_committee(
        api,
        seats=STANDARD_SEATS,
        min_quorum_count=3,
        required_functions=["FINANCE", "LEGAL", "INVESTOR_RELATIONS"],
        adopt=False,
    )


@pytest.fixture
def planning_cycle(api, committee):
    """A reporting cycle in PLANNING against an adopted charter."""
    return build_scenario(api, committee)


@pytest.fixture
def close_open_cycle(api, committee):
    """A reporting cycle in CLOSE_OPEN with one close milestone."""
    return scenario_close_open(api, committee)


@pytest.fixture
def review_open_cycle(api, committee):
    """A reporting cycle in REVIEW_OPEN with its close milestone complete."""
    return scenario_review_open(api, committee)


@pytest.fixture
def certification_open_cycle(api, committee):
    """A reporting cycle in CERTIFICATION_OPEN with complete coverage and two
    eligible certification slots."""
    return scenario_certification_open(api, committee)


@pytest.fixture
def filing_ready_cycle(api, committee):
    """A reporting cycle in FILING_READY with both instruments signed."""
    return scenario_filing_ready(api, committee)


@pytest.fixture
def filed_cycle(api, committee):
    """A reporting cycle whose original filing has been submitted."""
    return scenario_filed(api, committee)


@pytest.fixture
def draft_correction_cycle(api, committee):
    """A filed cycle carrying one correction in DRAFT."""
    return scenario_with_draft_correction(api, committee)


@pytest.fixture
def draft_periodic_filing(api, committee):
    """A close-open cycle carrying one draft periodic filing document."""
    scenario = scenario_close_open(api, committee)
    scenario.document("PERIODIC_FILING", title="Form 10-Q FY2026-Q2")
    return scenario


@pytest.fixture
def draft_call_script(api, committee):
    """A close-open cycle carrying one draft call script authored by investor
    relations, with the safe-harbor legend present."""
    scenario = scenario_close_open(api, committee)
    scenario.document(
        "CALL_SCRIPT",
        author_key="ir",
        title="Q2 Earnings Call Script",
        safe_harbor_present=True,
        role="relations",
    )
    return scenario


@pytest.fixture
def abandoned_cycle(api, committee):
    """A close-open cycle that has been abandoned, so every non-terminal child
    has been cascaded into its void or superseded state."""
    scenario = scenario_close_open(api, committee)
    scenario.assign("ops", "OPERATIONS")
    scenario.document("PERIODIC_FILING", title="Form 10-Q FY2026-Q2")
    scenario.cert("ceo", "CEO_302")
    scenario.abandon()
    return scenario
