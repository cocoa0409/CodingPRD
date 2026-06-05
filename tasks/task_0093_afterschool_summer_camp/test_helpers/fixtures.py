"""Composite setup helpers.

Most interesting test claims require the system to be in a specific state that takes
many API calls to reach: a guardian with a fully-authorized, age-eligible child, a
published program, an open session with at least one weekly offering, and often an
enrollment / invoice / scholarship already in place. These helpers encapsulate those
multi-step preambles so tests focus on assertions.

The harness restarts the server (empty DB) before every test, so every fixture builds
its preconditions from scratch using only PRD-declared endpoints. Setup steps use the
lenient get_success_data() validator so failures surface as clear "Setup step failed"
errors. Guardian ownership-gated calls thread the real Guardian.id via
make_guardian_headers(guardian_id) — never the shared fallback constant.
"""
import itertools

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import TEST_USERS, make_guardian_headers
from . import factories as F


_DIRECTOR = TEST_USERS["program_director_headers"]
_BILLING = TEST_USERS["billing_admin_headers"]
_ANON = TEST_USERS["anonymous_headers"]

# Unique-email generator so repeated guardian registrations within one test never collide.
_email_counter = itertools.count(1)


def _unique_email(prefix="g"):
    return f"{prefix}{next(_email_counter)}@example.com"


# ---------------------------------------------------------------------------
# Tier 1 — primitive builders
# ---------------------------------------------------------------------------
def create_guardian(**overrides):
    """Register a guardian. Returns the Guardian dict."""
    payload = F.create_guardian_payload(**overrides)
    if "email" not in overrides:
        payload["email"] = _unique_email()
    return get_success_data(api_client.create_guardian(payload, _ANON))


def create_child(guardian_id, **overrides):
    """Create a child under the acting guardian (ownership-gated)."""
    payload = F.create_child_payload(guardian_id, **overrides)
    return get_success_data(
        api_client.create_child(payload, make_guardian_headers(guardian_id))
    )


def add_emergency_contact(guardian_id, child_id, **overrides):
    payload = F.create_emergency_contact_payload(child_id, **overrides)
    return get_success_data(
        api_client.create_emergency_contact(payload, make_guardian_headers(guardian_id))
    )


def add_approved_form(guardian_id, child_id, form_type, **overrides):
    """Submit an authorization form (guardian) and approve it (director). Returns APPROVED form."""
    gh = make_guardian_headers(guardian_id)
    payload = F.create_authorization_form_payload(child_id, form_type, **overrides)
    form = get_success_data(api_client.create_authorization_form(payload, gh))
    return get_success_data(api_client.approve_authorization_form(form["id"], _DIRECTOR))


def create_program(**overrides):
    return get_success_data(api_client.create_program(F.create_program_payload(**overrides), _DIRECTOR))


def create_session(program_id, **overrides):
    return get_success_data(
        api_client.create_session(F.create_session_payload(program_id, **overrides), _DIRECTOR)
    )


def create_weekly_offering(session_id, **overrides):
    return get_success_data(
        api_client.create_weekly_offering(F.create_weekly_offering_payload(session_id, **overrides), _DIRECTOR)
    )


def publish_program(program_id):
    return get_success_data(api_client.publish_program(program_id, _DIRECTOR))


def open_session(session_id):
    return get_success_data(api_client.open_session(session_id, _DIRECTOR))


def get_offering(offering_id):
    return get_success_data(api_client.get_weekly_offering(offering_id, _DIRECTOR))


def get_invoice(invoice_id):
    return get_success_data(api_client.get_invoice(invoice_id, _BILLING))


def get_enrollment(enrollment_id, guardian_id=None):
    headers = make_guardian_headers(guardian_id) if guardian_id else _BILLING
    return get_success_data(api_client.get_enrollment(enrollment_id, headers))


# ---------------------------------------------------------------------------
# Tier 1.5 — eligible child (fully authorized + emergency contact)
# ---------------------------------------------------------------------------
def setup_eligible_child(guardian_id=None, child_overrides=None, with_scholarship_tier=None,
                         approve_scholarship=False):
    """Create a guardian (unless one is supplied) and a fully-eligible child:
    one emergency contact, an APPROVED MEDICAL form, and an APPROVED PICKUP form.

    Optionally requests a scholarship of the given tier, and optionally approves it.

    Returns dict with keys: guardian, child, scholarship (or None).
    """
    child_overrides = child_overrides or {}
    if guardian_id is None:
        guardian = create_guardian()
        guardian_id = guardian["id"]
    else:
        guardian = {"id": guardian_id}

    child = create_child(guardian_id, **child_overrides)
    add_emergency_contact(guardian_id, child["id"])
    add_approved_form(guardian_id, child["id"], "MEDICAL")
    add_approved_form(guardian_id, child["id"], "PICKUP")

    scholarship = None
    if with_scholarship_tier is not None:
        gh = make_guardian_headers(guardian_id)
        scholarship = get_success_data(
            api_client.create_scholarship_award(
                F.create_scholarship_award_payload(child["id"], with_scholarship_tier), gh
            )
        )
        if approve_scholarship:
            scholarship = get_success_data(
                api_client.approve_scholarship_award(scholarship["id"], _DIRECTOR)
            )

    return {"guardian": guardian, "child": child, "scholarship": scholarship}


# ---------------------------------------------------------------------------
# Tier 2 — open session with one weekly offering
# ---------------------------------------------------------------------------
def setup_open_session_with_offering(program_overrides=None, session_overrides=None,
                                     offering_overrides=None):
    """Build a PUBLISHED program with one OPEN session and one weekly offering.

    Returns dict: program, session, offering (offering re-fetched so version is current).
    """
    program = create_program(**(program_overrides or {}))
    session = create_session(program["id"], **(session_overrides or {}))
    offering = create_weekly_offering(session["id"], **(offering_overrides or {}))
    publish_program(program["id"])
    open_session(session["id"])
    offering = get_offering(offering["id"])  # refresh version after open/publish
    return {"program": program, "session": session, "offering": offering}


# ---------------------------------------------------------------------------
# Tier 3 — enrollment
# ---------------------------------------------------------------------------
def enroll_child(guardian_id, child_id, offering_id, expected_version=None):
    """Enroll a child into an offering. If expected_version is None, the live offering
    version is fetched first. Returns the Enrollment dict (CONFIRMED or WAITLISTED)."""
    if expected_version is None:
        expected_version = get_offering(offering_id)["version"]
    gh = make_guardian_headers(guardian_id)
    payload = F.create_enrollment_payload(child_id, offering_id, expected_version)
    return get_success_data(api_client.create_enrollment(payload, gh))


def setup_confirmed_enrollment(program_overrides=None, session_overrides=None,
                               with_scholarship_tier=None, approve_scholarship=False):
    """Full preamble to ONE CONFIRMED enrollment on a fresh open offering.

    Steps: eligible child -> published program -> open session -> offering -> enroll.

    Returns dict: guardian, child, scholarship, program, session, offering, enrollment,
    invoice_id. The offering dict reflects pre-enroll version; re-fetch via get_offering
    if a current version is needed.
    """
    eligible = setup_eligible_child(
        with_scholarship_tier=with_scholarship_tier, approve_scholarship=approve_scholarship
    )
    guardian_id = eligible["guardian"]["id"]
    scene = setup_open_session_with_offering(program_overrides, session_overrides)
    enrollment = enroll_child(
        guardian_id, eligible["child"]["id"], scene["offering"]["id"],
        scene["offering"]["version"],
    )
    return {
        "guardian": eligible["guardian"],
        "child": eligible["child"],
        "scholarship": eligible["scholarship"],
        "program": scene["program"],
        "session": scene["session"],
        "offering": scene["offering"],
        "enrollment": enrollment,
        "invoice_id": enrollment.get("invoice_id"),
    }


# ---------------------------------------------------------------------------
# Tier 4 — capacity / waitlist targeting
# ---------------------------------------------------------------------------
def setup_offering_at_capacity(capacity=1, session_overrides=None):
    """Build an OPEN offering whose confirmed count is exactly `capacity` (FULL).

    Creates `capacity` eligible children (all under one guardian) and confirms each on
    the offering, re-reading the offering version between enrolls (OCC). Returns dict:
    guardian, offering, confirmed (list of enrollments), program, session.
    """
    session_overrides = dict(session_overrides or {})
    session_overrides.setdefault("weekly_capacity", capacity)
    scene = setup_open_session_with_offering(session_overrides=session_overrides)
    guardian = create_guardian()
    guardian_id = guardian["id"]

    confirmed = []
    for i in range(capacity):
        eligible = setup_eligible_child(
            guardian_id=guardian_id,
            child_overrides={"first_name": f"Cap{i}", "birth_date": f"2016-0{(i % 9) + 1}-01"},
        )
        ver = get_offering(scene["offering"]["id"])["version"]
        e = enroll_child(guardian_id, eligible["child"]["id"], scene["offering"]["id"], ver)
        confirmed.append(e)

    return {
        "guardian": guardian,
        "offering": get_offering(scene["offering"]["id"]),
        "confirmed": confirmed,
        "program": scene["program"],
        "session": scene["session"],
    }


def setup_confirmed_plus_waitlisted(session_overrides=None):
    """Capacity-1 offering with Child A CONFIRMED and Child B WAITLISTED (rank 1).

    Both children belong to one guardian. Returns dict: guardian, offering, child_a,
    child_b, enrollment_a (CONFIRMED), enrollment_b (WAITLISTED), session.
    """
    session_overrides = dict(session_overrides or {})
    session_overrides.setdefault("weekly_capacity", 1)
    scene = setup_open_session_with_offering(session_overrides=session_overrides)
    guardian = create_guardian()
    guardian_id = guardian["id"]

    elig_a = setup_eligible_child(guardian_id=guardian_id,
                                  child_overrides={"first_name": "WaitA", "birth_date": "2016-03-01"})
    ea = enroll_child(guardian_id, elig_a["child"]["id"], scene["offering"]["id"],
                      get_offering(scene["offering"]["id"])["version"])

    elig_b = setup_eligible_child(guardian_id=guardian_id,
                                  child_overrides={"first_name": "WaitB", "birth_date": "2016-04-01"})
    eb = enroll_child(guardian_id, elig_b["child"]["id"], scene["offering"]["id"],
                      get_offering(scene["offering"]["id"])["version"])

    return {
        "guardian": guardian,
        "offering": get_offering(scene["offering"]["id"]),
        "child_a": elig_a["child"],
        "child_b": elig_b["child"],
        "enrollment_a": ea,
        "enrollment_b": eb,
        "session": scene["session"],
    }


# ---------------------------------------------------------------------------
# Tier 5 — finalization / billing
# ---------------------------------------------------------------------------
def setup_finalized_invoice(program_overrides=None, session_overrides=None):
    """A CONFIRMED enrollment whose invoice is FINALIZED.

    Returns dict: guardian, child, enrollment, invoice (finalized), offering, session,
    program.
    """
    scene = setup_confirmed_enrollment(
        program_overrides=program_overrides, session_overrides=session_overrides
    )
    invoice_id = scene["invoice_id"]
    inv = get_invoice(invoice_id)
    finalized = get_success_data(
        api_client.finalize_invoice(invoice_id, F.finalize_invoice_payload(inv["version"]), _BILLING)
    )
    scene["invoice"] = finalized
    return scene


# ---------------------------------------------------------------------------
# Tier 6 — rain / weather
# ---------------------------------------------------------------------------
def setup_offering_with_rain_alternate(out_session_overrides=None, in_session_overrides=None,
                                       same_program=True):
    """Two OPEN offerings W1 (outdoor) and W2 (indoor alternate) with
    W1.rain_alternate_offering_id = W2.

    By default both belong to the same program; W2 is created first so it can be named
    as the alternate. Both offerings share the same week_start. Returns dict:
    program, out_session, in_session, w1 (outdoor, current version), w2 (indoor).
    """
    out_session_overrides = dict(out_session_overrides or {})
    in_session_overrides = dict(in_session_overrides or {})

    program = create_program()
    out_session = create_session(program["id"], title="Outdoor", **out_session_overrides)
    if same_program:
        in_session = create_session(program["id"], title="Indoor", **in_session_overrides)
    else:
        in_program = create_program()
        in_session = create_session(in_program["id"], title="Indoor", **in_session_overrides)

    w2 = create_weekly_offering(in_session["id"])  # indoor alternate
    w1 = create_weekly_offering(out_session["id"])  # outdoor source

    # Configure W1's rain alternate to W2 (mutates W1 -> version++).
    get_success_data(
        api_client.configure_rain_alternate(
            w1["id"], F.configure_rain_alternate_payload(w2["id"], w1["version"]), _DIRECTOR
        )
    )

    publish_program(program["id"])
    if not same_program:
        publish_program(in_session["program_id"])
    open_session(out_session["id"])
    open_session(in_session["id"])

    return {
        "program": program,
        "out_session": out_session,
        "in_session": in_session,
        "w1": get_offering(w1["id"]),
        "w2": get_offering(w2["id"]),
    }
