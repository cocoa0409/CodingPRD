"""Composite setup builders and pytest fixtures.

Every test starts against an empty database, so all state is built through the
public API. The builders below climb the certification chain in the order the PRD
mandates — specification, feature sets, ratification, member onboarding and
funding, laboratory accreditation, submission, review, plan, bench session,
results, the two review axes, credential issuance, listing and publication —
and each stage is reachable on its own so a test can stop exactly where its
scenario begins.

Setup calls go through ``get_success_data``, which names the failing setup step in
its assertion message instead of letting a broken precondition surface as a
mysterious later failure.
"""

import pytest
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_PROGRAMME_START
from .factories import (
    accreditation_payload,
    conformance_decision_payload,
    credit_purchase_payload,
    feature_set_payload,
    ip_commitment_payload,
    issue_credential_payload,
    laboratory_payload,
    listing_payload,
    member_payload,
    participation_payload,
    plugfest_payload,
    record_outcome_payload,
    results_payload,
    security_decision_payload,
    specification_payload,
    submission_payload,
    test_plan_payload,
    test_session_payload,
    tool_access_payload,
)
from .test_users import (
    ADMIN_HEADERS,
    COMPLIANCE_HEADERS,
    CONFORMANCE_HEADERS,
    CONFORMANCE_REVIEWER_1,
    SECURITY_HEADERS,
    SECURITY_REVIEWER_1,
    make_conformance_headers,
    make_laboratory_headers,
    make_member_headers,
    make_security_headers,
)
from .types import feature, result_line


class Ctx(dict):
    """A mutable bag of the ids a scenario has built so far."""

    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError:
            raise AttributeError(name)

    def __setattr__(self, name, value):
        self[name] = value


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------


def set_clock(current_utc=CLOCK_PROGRAMME_START):
    """Reposition the logical clock and return the echoed instant."""
    return get_success_data(api_client.set_clock(current_utc, headers=ADMIN_HEADERS))


# ---------------------------------------------------------------------------
# Primitive writes
# ---------------------------------------------------------------------------


def new_specification(**overrides):
    return get_success_data(
        api_client.create_specification(specification_payload(**overrides), ADMIN_HEADERS),
        201,
    )


def new_feature_set(specification_id, **overrides):
    return get_success_data(
        api_client.create_feature_set(
            feature_set_payload(specification_id, **overrides), ADMIN_HEADERS
        ),
        201,
    )


def ratify_specification(specification_id):
    return get_success_data(
        api_client.ratify_specification(specification_id, headers=ADMIN_HEADERS)
    )


def deprecate_specification(specification_id):
    return get_success_data(
        api_client.deprecate_specification(specification_id, headers=ADMIN_HEADERS)
    )


def new_member(**overrides):
    return get_success_data(
        api_client.create_member(member_payload(**overrides), ADMIN_HEADERS), 201
    )


def execute_ip_commitment(member_id, scope_specification_id, **overrides):
    return get_success_data(
        api_client.execute_ip_commitment(
            member_id,
            ip_commitment_payload(scope_specification_id, **overrides),
            make_member_headers(member_id),
        )
    )


def withdraw_ip_commitment(member_id):
    return get_success_data(
        api_client.withdraw_ip_commitment(
            member_id, headers=make_member_headers(member_id)
        )
    )


def grant_tool_access(member_id):
    return get_success_data(
        api_client.set_tool_access(member_id, tool_access_payload("GRANT"), ADMIN_HEADERS)
    )


def revoke_tool_access(member_id):
    return get_success_data(
        api_client.set_tool_access(member_id, tool_access_payload("REVOKE"), ADMIN_HEADERS)
    )


def purchase_credits(member_id, amount_cents=1000000):
    return get_success_data(
        api_client.purchase_credits(
            member_id, credit_purchase_payload(amount_cents), ADMIN_HEADERS
        )
    )


def new_laboratory(**overrides):
    return get_success_data(
        api_client.create_test_laboratory(laboratory_payload(**overrides), ADMIN_HEADERS),
        201,
    )


def accreditation_decision(laboratory_id, decision):
    return get_success_data(
        api_client.accreditation_decision(
            laboratory_id, accreditation_payload(decision), ADMIN_HEADERS
        )
    )


def new_submission(member_id, specification_id, declared_feature_codes=None, **overrides):
    return get_success_data(
        api_client.create_submission(
            submission_payload(
                member_id, specification_id, declared_feature_codes, **overrides
            ),
            make_member_headers(member_id),
        ),
        201,
    )


def submit_submission(submission_id, member_id):
    return get_success_data(
        api_client.submit_submission(
            submission_id, headers=make_member_headers(member_id)
        )
    )


def withdraw_submission(submission_id, member_id):
    return get_success_data(
        api_client.withdraw_submission(
            submission_id, headers=make_member_headers(member_id)
        )
    )


def start_review(submission_id, reviewer_user_id=CONFORMANCE_REVIEWER_1):
    return get_success_data(
        api_client.start_review(
            submission_id, headers=make_conformance_headers(reviewer_user_id)
        )
    )


def new_test_plan(submission_id, expected_submission_version=None):
    """Create a plan, reading the submission's current version when not given."""
    if expected_submission_version is None:
        expected_submission_version = read_submission(submission_id)["version"]
    return get_success_data(
        api_client.create_test_plan(
            test_plan_payload(submission_id, expected_submission_version), ADMIN_HEADERS
        ),
        201,
    )


def issue_test_plan(test_plan_id):
    return get_success_data(
        api_client.issue_test_plan(test_plan_id, headers=ADMIN_HEADERS)
    )


def new_session(test_plan_id, laboratory_id, **overrides):
    return get_success_data(
        api_client.create_test_session(
            test_session_payload(test_plan_id, laboratory_id, **overrides), ADMIN_HEADERS
        ),
        201,
    )


def start_session(test_session_id, laboratory_id):
    return get_success_data(
        api_client.start_test_session(
            test_session_id, headers=make_laboratory_headers(laboratory_id)
        )
    )


def append_results(test_session_id, laboratory_id, lines):
    return get_success_data(
        api_client.append_results(
            test_session_id,
            results_payload(lines),
            make_laboratory_headers(laboratory_id),
        )
    )


def complete_session(test_session_id, laboratory_id):
    return get_success_data(
        api_client.complete_test_session(
            test_session_id, headers=make_laboratory_headers(laboratory_id)
        )
    )


def cancel_session(test_session_id, headers=None):
    return get_success_data(
        api_client.cancel_test_session(test_session_id, headers=headers or ADMIN_HEADERS)
    )


def security_decision(submission_id, decision="APPROVE", reviewer_user_id=SECURITY_REVIEWER_1, **overrides):
    return get_success_data(
        api_client.security_decision(
            submission_id,
            security_decision_payload(decision, **overrides),
            make_security_headers(reviewer_user_id),
        )
    )


def conformance_decision(submission_id, decision="APPROVE", reviewer_user_id=CONFORMANCE_REVIEWER_1, **overrides):
    return get_success_data(
        api_client.conformance_decision(
            submission_id,
            conformance_decision_payload(decision, **overrides),
            make_conformance_headers(reviewer_user_id),
        )
    )


def issue_credential(submission_id, dac_serial=None):
    return get_success_data(
        api_client.issue_credential(
            submission_id, issue_credential_payload(dac_serial), ADMIN_HEADERS
        )
    )


def new_listing(submission_id):
    return get_success_data(
        api_client.create_listing(listing_payload(submission_id), ADMIN_HEADERS), 201
    )


def publish_listing(listing_id):
    return get_success_data(
        api_client.publish_listing(listing_id, headers=ADMIN_HEADERS)
    )


def new_plugfest(host_laboratory_id, specification_id, **overrides):
    return get_success_data(
        api_client.create_plugfest(
            plugfest_payload(host_laboratory_id, specification_id, **overrides),
            ADMIN_HEADERS,
        ),
        201,
    )


def new_participation(plugfest_id, member_id, submission_id, **overrides):
    return get_success_data(
        api_client.create_participation(
            participation_payload(plugfest_id, member_id, submission_id, **overrides),
            make_member_headers(member_id),
        ),
        201,
    )


def lock_plugfest(plugfest_id):
    return get_success_data(api_client.lock_plugfest(plugfest_id, headers=ADMIN_HEADERS))


def close_plugfest(plugfest_id):
    return get_success_data(api_client.close_plugfest(plugfest_id, headers=ADMIN_HEADERS))


def record_outcome(participation_id, host_laboratory_id, outcome="PASS", interop_pass_count=4):
    return get_success_data(
        api_client.record_outcome(
            participation_id,
            record_outcome_payload(outcome, interop_pass_count),
            make_laboratory_headers(host_laboratory_id),
        )
    )


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


def read_specification(specification_id):
    return get_success_data(api_client.get_specification(specification_id, ADMIN_HEADERS))


def read_feature_set(feature_set_id):
    return get_success_data(api_client.get_feature_set(feature_set_id, ADMIN_HEADERS))


def read_member(member_id):
    return get_success_data(api_client.get_member(member_id, ADMIN_HEADERS))


def read_laboratory(laboratory_id):
    return get_success_data(api_client.get_test_laboratory(laboratory_id, ADMIN_HEADERS))


def read_submission(submission_id):
    return get_success_data(api_client.get_submission(submission_id, ADMIN_HEADERS))


def read_test_plan(test_plan_id):
    return get_success_data(api_client.get_test_plan(test_plan_id, ADMIN_HEADERS))


def read_session(test_session_id):
    return get_success_data(api_client.get_test_session(test_session_id, ADMIN_HEADERS))


def read_plugfest(plugfest_id):
    return get_success_data(api_client.get_plugfest(plugfest_id, ADMIN_HEADERS))


def read_participation(participation_id):
    return get_success_data(api_client.get_participation(participation_id, ADMIN_HEADERS))


def read_listing(listing_id):
    return get_success_data(api_client.get_listing(listing_id, ADMIN_HEADERS))


def read_case(case_id):
    return get_success_data(
        api_client.get_noncompliance_case(case_id, COMPLIANCE_HEADERS)
    )


def read_ledger(member_id, variant=None):
    return get_success_data(
        api_client.get_credit_ledger(member_id, ADMIN_HEADERS, variant=variant)
    )


def read_readiness(submission_id, variant=None):
    return get_success_data(
        api_client.get_readiness(submission_id, ADMIN_HEADERS, variant=variant)
    )


def read_competency(laboratory_id, variant=None):
    return get_success_data(
        api_client.get_competency(laboratory_id, ADMIN_HEADERS, variant=variant)
    )


# ---------------------------------------------------------------------------
# Entity-hierarchy builders
# ---------------------------------------------------------------------------

#: The baseline lighting graph every recipe starts from: two mandatory feature
#: sets worth 20 and 10 test cases.
DEFAULT_FEATURES = [
    feature("CORE_ONOFF", "MANDATORY", 20),
    feature("CORE_DIM", "MANDATORY", 10),
]


def build_specification(features=None, ratify=True, **spec_overrides):
    """Open a draft specification, add its feature graph and optionally ratify.

    ``features`` is a list of :func:`test_helpers.types.feature` declarations;
    ``depends_on`` names an earlier declaration's ``feature_code`` of the same
    device class, which is resolved to its stored id here.
    """
    ctx = Ctx()
    specification = new_specification(**spec_overrides)
    ctx.specification = specification
    ctx.specification_id = specification["id"]
    ctx.feature_sets = {}
    ctx.feature_set_ids = {}
    ctx.code_by_feature_set_id = {}

    for declared in features if features is not None else DEFAULT_FEATURES:
        depends_on_id = None
        if declared.depends_on is not None:
            depends_on_id = ctx.feature_set_ids[
                "{}:{}".format(declared.device_type, declared.depends_on)
            ]
        row = new_feature_set(
            ctx.specification_id,
            device_type=declared.device_type,
            feature_code=declared.feature_code,
            obligation=declared.obligation,
            test_case_count=declared.test_case_count,
            security_relevant=declared.security_relevant,
            depends_on_feature_set_id=depends_on_id,
        )
        keyed = "{}:{}".format(declared.device_type, declared.feature_code)
        ctx.feature_sets[keyed] = row
        ctx.feature_set_ids[keyed] = row["id"]
        ctx.feature_sets.setdefault(declared.feature_code, row)
        ctx.feature_set_ids.setdefault(declared.feature_code, row["id"])
        ctx.code_by_feature_set_id[row["id"]] = declared.feature_code

    if ratify:
        ctx.specification = ratify_specification(ctx.specification_id)
    return ctx


def build_member(scope_specification_id=None, credit_cents=1000000, grant=True, **overrides):
    """Register a member and walk it as far as the scenario needs.

    Passing ``scope_specification_id`` executes the IP commitment against that
    version; ``grant`` then moves testing-tool entitlement, which is what turns
    ``good_standing`` true; ``credit_cents`` funds the account.
    """
    ctx = Ctx()
    member = new_member(**overrides)
    ctx.member_id = member["id"]
    ctx.member_headers = make_member_headers(ctx.member_id)
    if scope_specification_id is not None:
        execute_ip_commitment(ctx.member_id, scope_specification_id)
        if grant:
            grant_tool_access(ctx.member_id)
    if credit_cents:
        purchase_credits(ctx.member_id, credit_cents)
    ctx.member = read_member(ctx.member_id)
    return ctx


def build_laboratory(authorize=True, **overrides):
    """Register a laboratory and optionally authorize its accreditation."""
    ctx = Ctx()
    laboratory = new_laboratory(**overrides)
    ctx.laboratory_id = laboratory["id"]
    ctx.laboratory_headers = make_laboratory_headers(ctx.laboratory_id)
    if authorize:
        laboratory = accreditation_decision(ctx.laboratory_id, "AUTHORIZE")
    ctx.laboratory = laboratory
    return ctx


# ---------------------------------------------------------------------------
# The certification chain, stage by stage
# ---------------------------------------------------------------------------

STAGES = [
    "specification",
    "member",
    "laboratory",
    "draft",
    "submitted",
    "in_review",
    "plan",
    "issued",
    "scheduled",
    "in_progress",
    "results",
    "plan_complete",
    "review_complete",
    "certified",
    "listed",
    "published",
]


def _stage_index(stage):
    assert stage in STAGES, "unknown stage {!r}; expected one of {}".format(stage, STAGES)
    return STAGES.index(stage)


def build_program(
    stage="in_review",
    features=None,
    declared_codes=None,
    device_type="LIGHTING",
    spec_overrides=None,
    member_overrides=None,
    lab_overrides=None,
    submission_overrides=None,
    session_overrides=None,
    credit_cents=1000000,
    clock=CLOCK_PROGRAMME_START,
    session_start_clock="2026-09-02T09:00:00Z",
    session_complete_clock="2026-09-02T12:00:00Z",
    outcomes=None,
    dac_serial=None,
    conformance_reviewer=CONFORMANCE_REVIEWER_1,
    security_reviewer=SECURITY_REVIEWER_1,
):
    """Build the certification chain up to ``stage`` and return every id built.

    The stages follow the PRD's own order: a ratified specification, a funded
    member in good standing, an authorized laboratory, a draft submission with
    its pinned fee, submission, review pick-up, the test plan and its closure,
    issue, a booked bench window, execution, result capture, plan completion,
    both review axes, credential issuance, the listing and publication.
    """
    target = _stage_index(stage)
    ctx = Ctx()
    if clock is not None:
        set_clock(clock)

    spec_ctx = build_specification(features, ratify=True, **(spec_overrides or {}))
    ctx.update(spec_ctx)
    if target == _stage_index("specification"):
        return ctx

    member_ctx = build_member(
        scope_specification_id=ctx.specification_id,
        credit_cents=credit_cents,
        **(member_overrides or {})
    )
    ctx.update(member_ctx)
    if target == _stage_index("member"):
        return ctx

    lab_ctx = build_laboratory(**(lab_overrides or {}))
    ctx.update(lab_ctx)
    if target == _stage_index("laboratory"):
        return ctx

    if declared_codes is None:
        declared_codes = [
            declared.feature_code
            for declared in (features if features is not None else DEFAULT_FEATURES)
            if declared.device_type == device_type
        ]
    submission = new_submission(
        ctx.member_id,
        ctx.specification_id,
        declared_codes,
        device_type=device_type,
        **(submission_overrides or {})
    )
    ctx.submission = submission
    ctx.submission_id = submission["id"]
    ctx.declared_codes = list(declared_codes)
    ctx.certification_fee_cents = submission["certification_fee_cents"]
    if target == _stage_index("draft"):
        return ctx

    ctx.submission = submit_submission(ctx.submission_id, ctx.member_id)
    if target == _stage_index("submitted"):
        return ctx

    ctx.submission = start_review(ctx.submission_id, conformance_reviewer)
    if target == _stage_index("in_review"):
        return ctx

    plan = new_test_plan(ctx.submission_id, ctx.submission["version"])
    ctx.plan = plan
    ctx.plan_id = plan["id"]
    if target == _stage_index("plan"):
        return ctx

    ctx.plan = issue_test_plan(ctx.plan_id)
    if target == _stage_index("issued"):
        return ctx

    session = new_session(ctx.plan_id, ctx.laboratory_id, **(session_overrides or {}))
    ctx.session = session
    ctx.session_id = session["id"]
    if target == _stage_index("scheduled"):
        return ctx

    if session_start_clock is not None:
        set_clock(session_start_clock)
    ctx.session = start_session(ctx.session_id, ctx.laboratory_id)
    if target == _stage_index("in_progress"):
        return ctx

    ctx.session = append_results(
        ctx.session_id,
        ctx.laboratory_id,
        plan_result_lines(ctx, outcomes),
    )
    if target == _stage_index("results"):
        return ctx

    if session_complete_clock is not None:
        set_clock(session_complete_clock)
    ctx.session = complete_session(ctx.session_id, ctx.laboratory_id)
    ctx.plan = read_test_plan(ctx.plan_id)
    if target == _stage_index("plan_complete"):
        return ctx

    security_decision(ctx.submission_id, "APPROVE", security_reviewer)
    ctx.submission = conformance_decision(
        ctx.submission_id, "APPROVE", conformance_reviewer
    )
    if target == _stage_index("review_complete"):
        return ctx

    ctx.submission = issue_credential(ctx.submission_id, dac_serial)
    ctx.dac_serial = ctx.submission["dac_serial"]
    if target == _stage_index("certified"):
        return ctx

    listing = new_listing(ctx.submission_id)
    ctx.listing = listing
    ctx.listing_id = listing["id"]
    if target == _stage_index("listed"):
        return ctx

    ctx.listing = publish_listing(ctx.listing_id)
    return ctx


def plan_result_lines(ctx, outcomes=None):
    """One result line per feature set of the plan's closure.

    ``outcomes`` maps a ``feature_code`` to the outcome to record for it;
    anything unnamed is recorded as ``PASS``.
    """
    outcomes = outcomes or {}
    plan = read_test_plan(ctx.plan_id)
    lines = []
    for feature_set_id in plan["included_feature_set_ids"]:
        code = ctx.code_by_feature_set_id.get(feature_set_id)
        lines.append(result_line(feature_set_id, outcomes.get(code, "PASS")))
    return lines


# ---------------------------------------------------------------------------
# Noncompliance and firmware primitives
# ---------------------------------------------------------------------------


def new_case(listing_id, officer_user_id="CO1", **overrides):
    from .factories import noncompliance_case_payload
    from .test_users import make_compliance_headers

    return get_success_data(
        api_client.create_noncompliance_case(
            noncompliance_case_payload(listing_id, **overrides),
            make_compliance_headers(officer_user_id),
        ),
        201,
    )


def advance_case(case_id, disposition, officer_user_id="CO1", **extra):
    from .factories import case_advance_payload
    from .test_users import make_compliance_headers

    return get_success_data(
        api_client.advance_case(
            case_id,
            case_advance_payload(disposition, **extra),
            make_compliance_headers(officer_user_id),
        )
    )


def close_case(case_id, officer_user_id="CO2"):
    from .test_users import make_compliance_headers

    return get_success_data(
        api_client.close_case(case_id, headers=make_compliance_headers(officer_user_id))
    )


def withdraw_listing(listing_id, officer_user_id="CO1", reason="Consumer safety report"):
    from .factories import listing_withdraw_payload
    from .test_users import make_compliance_headers

    return get_success_data(
        api_client.withdraw_listing(
            listing_id,
            listing_withdraw_payload(reason),
            make_compliance_headers(officer_user_id),
        )
    )


def report_firmware_revision(listing_id, expected_listing_version=None, **overrides):
    from .factories import firmware_revision_payload

    if expected_listing_version is None:
        expected_listing_version = read_listing(listing_id)["version"]
    return get_success_data(
        api_client.report_firmware_revision(
            listing_id,
            firmware_revision_payload(expected_listing_version, **overrides),
            ADMIN_HEADERS,
        )
    )


# ---------------------------------------------------------------------------
# Accumulation helpers
# ---------------------------------------------------------------------------


def run_session_cycle(
    ctx,
    window_start,
    window_end,
    bench_index=1,
    outcomes=None,
    lines=None,
    start_clock=None,
    complete_clock=None,
    session_type="INTEROP",
    laboratory_id=None,
):
    """Book, start, populate and complete one bench window.

    Used where a scenario needs several completed sessions to accumulate — the
    laboratory competency window, the readiness input set, or the compensating
    bench-minute totals.
    """
    laboratory_id = laboratory_id or ctx.laboratory_id
    session = new_session(
        ctx.plan_id,
        laboratory_id,
        window_start=window_start,
        window_end=window_end,
        bench_index=bench_index,
        session_type=session_type,
    )
    set_clock(start_clock or window_start)
    start_session(session["id"], laboratory_id)
    append_results(
        session["id"], laboratory_id, lines or plan_result_lines(ctx, outcomes)
    )
    set_clock(complete_clock or window_end)
    return complete_session(session["id"], laboratory_id)


def earn_plugfest_credit(
    ctx,
    window_start="2026-10-05T09:00:00Z",
    window_end="2026-10-06T18:00:00Z",
    registration_deadline="2026-10-01T00:00:00Z",
    interop_pass_count=4,
):
    """Take the submission through one plugfest to a PASS, granting one credit.

    A lock needs two distinct vendors, so a co-vendor member with its own
    submission against the same specification is registered alongside.
    """
    plugfest = new_plugfest(
        ctx.laboratory_id,
        ctx.specification_id,
        window_start=window_start,
        window_end=window_end,
        registration_deadline=registration_deadline,
    )
    own = new_participation(plugfest["id"], ctx.member_id, ctx.submission_id)

    co_vendor = build_member(scope_specification_id=ctx.specification_id)
    co_submission = new_submission(
        co_vendor.member_id, ctx.specification_id, ctx.declared_codes
    )
    new_participation(plugfest["id"], co_vendor.member_id, co_submission["id"])

    lock_plugfest(plugfest["id"])
    record_outcome(own["id"], ctx.laboratory_id, "PASS", interop_pass_count)
    ctx.plugfest_id = plugfest["id"]
    ctx.participation_id = own["id"]
    return read_submission(ctx.submission_id)


# ---------------------------------------------------------------------------
# pytest fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def api():
    """The shared HTTP client."""
    return api_client


@pytest.fixture
def clock_at_programme_start():
    """Position the logical clock at the programme's reference instant."""
    set_clock(CLOCK_PROGRAMME_START)
    return CLOCK_PROGRAMME_START


@pytest.fixture
def ratified_specification(clock_at_programme_start):
    """A ratified specification carrying the baseline lighting feature graph."""
    return build_specification()


@pytest.fixture
def funded_member(ratified_specification):
    """A member in good standing with a million cents of credit."""
    ctx = Ctx(ratified_specification)
    ctx.update(build_member(scope_specification_id=ctx.specification_id))
    return ctx


@pytest.fixture
def authorized_laboratory(clock_at_programme_start):
    """An authorized laboratory with two lighting benches."""
    return build_laboratory()


@pytest.fixture
def program_draft_submission():
    """A DRAFT submission with its fee already pinned."""
    return build_program(stage="draft")


@pytest.fixture
def program_submitted():
    """A SUBMITTED submission with its fee escrowed."""
    return build_program(stage="submitted")


@pytest.fixture
def program_in_review():
    """An IN_REVIEW submission ready for a test plan."""
    return build_program(stage="in_review")


@pytest.fixture
def program_with_draft_plan():
    """An IN_REVIEW submission whose plan has been created but not issued."""
    return build_program(stage="plan")


@pytest.fixture
def program_with_issued_plan():
    """An ISSUED plan ready for a bench booking."""
    return build_program(stage="issued")


@pytest.fixture
def program_with_scheduled_session():
    """A SCHEDULED bench window holding the laboratory's minutes."""
    return build_program(stage="scheduled")


@pytest.fixture
def program_in_execution():
    """An IN_PROGRESS session on an IN_EXECUTION plan."""
    return build_program(stage="in_progress")


@pytest.fixture
def program_with_completed_plan():
    """A COMPLETE plan whose mandatory coverage is satisfied."""
    return build_program(stage="plan_complete")


@pytest.fixture
def program_review_complete():
    """A REVIEW_COMPLETE submission with both axes APPROVED."""
    return build_program(stage="review_complete")


@pytest.fixture
def program_certified():
    """A CERTIFIED submission holding an ISSUED credential."""
    return build_program(stage="certified")


@pytest.fixture
def program_listed():
    """An UNPUBLISHED listing over a certified submission."""
    return build_program(stage="listed")


@pytest.fixture
def program_published():
    """A PUBLISHED listing in the consumer directory."""
    return build_program(stage="published")
