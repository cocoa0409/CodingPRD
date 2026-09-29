"""
Composite setup helpers for the Lender Appraisal Review Desk API.

Each test starts against an empty database, so every precondition a test needs has
to be built from scratch through the public API. The helpers here do exactly that,
in five tiers:

  tier 1  single-entity creators that also refresh the concurrency token a later
          call will need
  tier 2  entity hierarchies -- a management company, an appraiser, the panel
          enrolment that links them, and a loan file
  tier 3  lifecycle shortcuts -- a delivered report with a graded grid, a screened
          report, an open desk review, a submitted review, an escalation order
  tier 4  accumulation and threshold targeting -- ledgers, spend, tallies and
          scores driven to a specific value
  tier 5  finalisation and terminal states -- accepted, revised, quarantined,
          closed and cancelled outcomes

Identity threading is deliberate. An AMCCoordinator's identifier is the management
company's own id and an Appraiser's is the appraiser's own id, so every helper that
performs an ownership-gated write builds its headers from the resource it just
created rather than from a shared constant.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import ApiClient
from .constants import CLOCK_EPOCH
from .test_users import (
    CHIEF_APPRAISER_HEADERS,
    COMPLIANCE_HEADERS,
    DESK_REVIEWER_HEADERS,
    LOAN_OFFICER_HEADERS,
    make_amc_headers,
    make_appraiser_headers,
    make_borrower_headers,
)

# ---------------------------------------------------------------------------
# Benign comparable rows for a report that clears every receipt check.
#
# Three closed sales inside the suburban distance ceiling, each adjusted by one
# percent of its sale price, so the reconciled value lands two basis points from
# the reported value and every adjustment check passes.
# ---------------------------------------------------------------------------
CLEAN_COMPARABLES = [
    {
        "street_address": "1 Alder Street",
        "sale_price_cents": 39000000,
        "gross_adjustment_cents": 390000,
        "net_adjustment_cents": 390000,
        "distance_miles": 1.0,
        "sale_date": "2026-05-01T00:00:00Z",
    },
    {
        "street_address": "2 Alder Street",
        "sale_price_cents": 40000000,
        "gross_adjustment_cents": 400000,
        "net_adjustment_cents": 0,
        "distance_miles": 1.5,
        "sale_date": "2026-06-01T00:00:00Z",
    },
    {
        "street_address": "3 Alder Street",
        "sale_price_cents": 41000000,
        "gross_adjustment_cents": 410000,
        "net_adjustment_cents": -410000,
        "distance_miles": 2.0,
        "sale_date": "2026-06-15T00:00:00Z",
    },
]


# ===========================================================================
# tier 1 -- single entity creators
# ===========================================================================
def set_clock(api: ApiClient, instant: str, headers=None) -> Dict[str, Any]:
    """Move the logical clock; available to every role."""
    return get_success_data(
        api.set_clock(instant, headers or CHIEF_APPRAISER_HEADERS)
    )


def reset_clock(api: ApiClient) -> Dict[str, Any]:
    return set_clock(api, CLOCK_EPOCH)


def create_amc(api: ApiClient, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.create_amc(f.amc_payload(**overrides), CHIEF_APPRAISER_HEADERS), 201
    )


def create_appraiser(api: ApiClient, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.create_appraiser(f.appraiser_payload(**overrides), CHIEF_APPRAISER_HEADERS),
        201,
    )


def read_appraiser(api: ApiClient, appraiser_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_appraiser(appraiser_id, CHIEF_APPRAISER_HEADERS))


def read_amc(api: ApiClient, amc_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_amc(amc_id, CHIEF_APPRAISER_HEADERS))


def read_loan_file(api: ApiClient, loan_file_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_loan_file(loan_file_id, LOAN_OFFICER_HEADERS))


def read_appraisal(api: ApiClient, appraisal_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_appraisal(appraisal_id, DESK_REVIEWER_HEADERS))


def read_desk_review(api: ApiClient, desk_review_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_desk_review(desk_review_id, DESK_REVIEWER_HEADERS))


def read_escalation_order(api: ApiClient, order_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_escalation_order(order_id, CHIEF_APPRAISER_HEADERS))


def read_rov_request(api: ApiClient, rov_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_rov_request(rov_id, DESK_REVIEWER_HEADERS))


def read_dispute_case(api: ApiClient, dispute_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_dispute_case(dispute_id, CHIEF_APPRAISER_HEADERS))


def enroll_on_panel(api: ApiClient, appraiser_id: str, amc_id: str,
                    **overrides) -> Dict[str, Any]:
    """
    Enrol an appraiser on a management company's panel.

    Enrolment bumps the appraiser's version, so the guard token is read fresh from
    the appraiser record immediately before the call rather than cached from an
    earlier response.
    """
    appraiser = read_appraiser(api, appraiser_id)
    payload = f.panel_membership_payload(
        appraiser_id, amc_id, appraiser["version"], **overrides
    )
    return get_success_data(
        api.create_panel_membership(payload, CHIEF_APPRAISER_HEADERS), 201
    )


def create_loan_file(api: ApiClient, purchase: bool = False, **overrides) -> Dict[str, Any]:
    builder = f.purchase_loan_file_payload if purchase else f.loan_file_payload
    return get_success_data(
        api.create_loan_file(builder(**overrides), LOAN_OFFICER_HEADERS), 201
    )


def move_underwriting(api: ApiClient, loan_file_id: str, target_status: str,
                      **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.set_underwriting_status(
            loan_file_id, f.underwriting_status_payload(target_status, **overrides),
            LOAN_OFFICER_HEADERS,
        )
    )


def deliver_appraisal(api: ApiClient, loan_file_id: str, appraiser_id: str,
                      amc_id: str, **overrides) -> Dict[str, Any]:
    """
    Deliver a report against a loan file.

    Delivery is the management company's own write, so the headers carry the
    company's id as the acting identity. The loan file's guard token is read fresh
    because delivery bumps it.
    """
    loan = read_loan_file(api, loan_file_id)
    payload = f.appraisal_payload(
        loan_file_id, appraiser_id, amc_id, loan["version"], **overrides
    )
    return get_success_data(
        api.create_appraisal(payload, make_amc_headers(amc_id)), 201
    )


def add_comparable(api: ApiClient, appraisal_id: str, amc_id: str,
                   street_address: str, **overrides) -> Dict[str, Any]:
    payload = f.comparable_payload(street_address, **overrides)
    return get_success_data(
        api.create_comparable(appraisal_id, payload, make_amc_headers(amc_id)), 201
    )


def add_comparables(api: ApiClient, appraisal_id: str, amc_id: str,
                    rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    created = []
    for row in rows:
        body = dict(row)
        address = body.pop("street_address")
        created.append(add_comparable(api, appraisal_id, amc_id, address, **body))
    return created


def run_rule_checks(api: ApiClient, appraisal_id: str) -> Dict[str, Any]:
    """Run the receipt checks, reading the appraisal's guard token first."""
    appraisal = read_appraisal(api, appraisal_id)
    return get_success_data(
        api.run_rule_checks(
            appraisal_id, f.version_payload(appraisal["version"]), DESK_REVIEWER_HEADERS,
        )
    )


def run_bias_screen(api: ApiClient, appraisal_id: str) -> Dict[str, Any]:
    """Run the bias screen, reading the appraisal's guard token first."""
    appraisal = read_appraisal(api, appraisal_id)
    return get_success_data(
        api.run_bias_screen(
            appraisal_id, f.version_payload(appraisal["version"]), COMPLIANCE_HEADERS,
        )
    )


def list_bias_flags(api: ApiClient, appraisal_id: str) -> List[Dict[str, Any]]:
    body = api.list_bias_flags(appraisal_id, COMPLIANCE_HEADERS, {"limit": 100})
    return get_success_data(body)


def list_rule_checks(api: ApiClient, appraisal_id: str) -> List[Dict[str, Any]]:
    return get_success_data(
        api.list_rule_checks(appraisal_id, DESK_REVIEWER_HEADERS, {"limit": 100})
    )


def list_value_revisions(api: ApiClient, appraisal_id: str) -> List[Dict[str, Any]]:
    return get_success_data(
        api.list_value_revisions(appraisal_id, DESK_REVIEWER_HEADERS, {"limit": 100})
    )


def open_desk_review(api: ApiClient, appraisal_id: str, headers=None,
                     **overrides) -> Dict[str, Any]:
    """Open a desk review, reading the appraisal's guard token first."""
    appraisal = read_appraisal(api, appraisal_id)
    payload = f.desk_review_payload(appraisal_id, appraisal["version"], **overrides)
    return get_success_data(
        api.create_desk_review(payload, headers or DESK_REVIEWER_HEADERS), 201
    )


def submit_desk_review(api: ApiClient, desk_review_id: str, headers=None,
                       **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.submit_desk_review(
            desk_review_id, f.desk_review_submit_payload(**overrides),
            headers or DESK_REVIEWER_HEADERS,
        )
    )


def decide_desk_review(api: ApiClient, desk_review_id: str, decision_action: str,
                       headers=None, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.decide_desk_review(
            desk_review_id, f.desk_review_decide_payload(decision_action, **overrides),
            headers or CHIEF_APPRAISER_HEADERS,
        )
    )


def escalation_order_for(api: ApiClient, desk_review_id: str) -> Dict[str, Any]:
    """Find the single escalation order an ESCALATE decision produced."""
    rows = get_success_data(
        api.list_escalation_orders(
            CHIEF_APPRAISER_HEADERS, {"desk_review_id": desk_review_id, "limit": 100},
        )
    )
    assert len(rows) == 1, (
        f"expected exactly one escalation order for desk review {desk_review_id}, "
        f"got {len(rows)}"
    )
    return rows[0]


def assign_order(api: ApiClient, order_id: str, appraiser_id: str,
                 window_start: str = "2026-08-02T09:00:00Z",
                 window_end: str = "2026-08-02T12:00:00Z", **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.assign_escalation_order(
            order_id, f.assign_payload(appraiser_id, window_start, window_end, **overrides),
            CHIEF_APPRAISER_HEADERS,
        )
    )


def complete_order(api: ApiClient, order_id: str, amc_id: str,
                   resulting_value_cents: int, **overrides) -> Dict[str, Any]:
    """Complete an order as the owning management company."""
    return get_success_data(
        api.complete_escalation_order(
            order_id, f.complete_order_payload(resulting_value_cents, **overrides),
            make_amc_headers(amc_id),
        )
    )


def cancel_order(api: ApiClient, order_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.cancel_escalation_order(
            order_id, f.cancel_order_payload(**overrides), CHIEF_APPRAISER_HEADERS,
        )
    )


def adjudicate_flag(api: ApiClient, flag_id: str, disposition: str,
                    rationale: str = "Compliance adjudication recorded.",
                    **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.adjudicate_bias_flag(
            flag_id, f.adjudicate_payload(disposition, rationale, **overrides),
            COMPLIANCE_HEADERS,
        )
    )


def panel_review(api: ApiClient, appraiser_id: str, panel_action: str,
                 **overrides) -> Dict[str, Any]:
    """Conduct a panel review, reading the appraiser's guard token first."""
    appraiser = read_appraiser(api, appraiser_id)
    payload = f.panel_review_payload(panel_action, appraiser["version"], **overrides)
    return get_success_data(
        api.panel_review(appraiser_id, payload, CHIEF_APPRAISER_HEADERS)
    )


def open_rov(api: ApiClient, loan_file_id: str, appraisal_id: str,
             as_borrower: bool = True, **overrides) -> Dict[str, Any]:
    """
    Open a reconsideration request.

    When the borrower files it, the acting identifier must be the loan file's own
    id, so the headers are built from the loan file rather than from a constant.
    """
    headers = (
        make_borrower_headers(loan_file_id) if as_borrower else DESK_REVIEWER_HEADERS
    )
    payload = f.rov_request_payload(loan_file_id, appraisal_id, **overrides)
    return get_success_data(api.create_rov_request(payload, headers), 201)


def file_evidence(api: ApiClient, rov_id: str, evidence_type: str,
                  **overrides) -> Dict[str, Any]:
    payload = f.evidence_payload(evidence_type, **overrides)
    return get_success_data(
        api.create_rov_evidence(rov_id, payload, DESK_REVIEWER_HEADERS), 201
    )


def file_two_admissible_items(api: ApiClient, rov_id: str,
                              prefix: str = "Evidence") -> List[Dict[str, Any]]:
    """
    File the two admissible items routing requires.

    Both are closed sales inside the suburban distance ceiling with sale dates well
    inside the 365-day staleness window, and neither address collides with the
    benign grid, so both survive every admissibility clause.
    """
    return [
        file_evidence(
            api, rov_id, "CLOSED_SALE",
            street_address=f"{prefix} One Way", sale_price_cents=42000000,
            sale_date="2026-06-01T00:00:00Z", distance_miles=1.0,
        ),
        file_evidence(
            api, rov_id, "CLOSED_SALE",
            street_address=f"{prefix} Two Way", sale_price_cents=42500000,
            sale_date="2026-06-10T00:00:00Z", distance_miles=1.5,
        ),
    ]


def route_rov(api: ApiClient, rov_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.submit_rov_request(rov_id, f.rov_submit_payload(**overrides),
                               DESK_REVIEWER_HEADERS)
    )


def rov_respond(api: ApiClient, rov_id: str, appraiser_id: str, outcome: str,
                **overrides) -> Dict[str, Any]:
    """Answer a routed reconsideration as the authoring appraiser."""
    return get_success_data(
        api.rov_appraiser_response(
            rov_id, f.rov_response_payload(outcome, **overrides),
            make_appraiser_headers(appraiser_id),
        )
    )


def rov_next_round(api: ApiClient, rov_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.rov_next_round(rov_id, f.rov_next_round_payload(**overrides),
                           DESK_REVIEWER_HEADERS)
    )


def rov_finalize(api: ApiClient, rov_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.finalize_rov_request(rov_id, f.rov_finalize_payload(**overrides),
                                 DESK_REVIEWER_HEADERS)
    )


def file_dispute(api: ApiClient, appraisal_id: str, amc_id: str, appraiser_id: str,
                 dispute_basis: str = "COMP_SELECTION",
                 slot_start: str = "2026-08-02T10:00:00Z",
                 slot_end: str = "2026-08-02T11:00:00Z", **overrides) -> Dict[str, Any]:
    payload = f.dispute_payload(
        appraisal_id, amc_id, appraiser_id, dispute_basis, slot_start, slot_end,
        **overrides
    )
    return get_success_data(api.create_dispute_case(payload, CHIEF_APPRAISER_HEADERS), 201)


def dispute_respond(api: ApiClient, dispute_id: str, amc_id: str,
                    appraiser_position: str = "VALUE_SUPPORTED",
                    **overrides) -> Dict[str, Any]:
    """Relay the appraiser's position as the owning management company."""
    return get_success_data(
        api.dispute_amc_response(
            dispute_id, f.amc_response_payload(appraiser_position, **overrides),
            make_amc_headers(amc_id),
        )
    )


def resolve_dispute(api: ApiClient, dispute_id: str, resolution: str,
                    **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.resolve_dispute_case(
            dispute_id, f.resolve_dispute_payload(resolution, **overrides),
            CHIEF_APPRAISER_HEADERS,
        )
    )


def send_communication(api: ApiClient, appraisal_id: str, recipient: str, intent: str,
                       body_text: str, headers=None) -> Dict[str, Any]:
    return get_success_data(
        api.create_communication(
            appraisal_id, f.communication_payload(recipient, intent, body_text),
            headers or DESK_REVIEWER_HEADERS,
        ),
        201,
    )


# ===========================================================================
# tier 2 -- entity hierarchies
# ===========================================================================
def panel_and_loan(api: ApiClient, amc: Optional[Dict] = None,
                   appraiser: Optional[Dict] = None, loan: Optional[Dict] = None,
                   purchase: bool = False, with_reviewer: bool = False,
                   reviewer: Optional[Dict] = None) -> Dict[str, Any]:
    """
    Build the four-entity spine every report needs.

    A management company, an authoring appraiser enrolled on that company's panel,
    optionally a second appraiser who can take escalation work, and a loan file the
    report will be delivered against. Any of the four payload dictionaries may be
    overridden to steer a later calculation.
    """
    amc_row = create_amc(api, **(amc or {}))
    author = create_appraiser(api, **(appraiser or {}))
    author_membership = enroll_on_panel(api, author["id"], amc_row["id"])
    env: Dict[str, Any] = {
        "amc": amc_row,
        "appraiser": author,
        "author_membership": author_membership,
    }
    if with_reviewer:
        second = create_appraiser(api, **(reviewer or {}))
        env["reviewer"] = second
        env["reviewer_membership"] = enroll_on_panel(api, second["id"], amc_row["id"],
                                                     tier="REVIEW_SPECIALIST")
    env["loan"] = create_loan_file(api, purchase=purchase, **(loan or {}))
    return env


# ===========================================================================
# tier 3 -- lifecycle shortcuts
# ===========================================================================
def delivered_report(api: ApiClient, appraisal: Optional[Dict] = None,
                     comparables: Optional[List[Dict]] = None,
                     **spine) -> Dict[str, Any]:
    """A report delivered against a fresh spine, with its comparable grid filled."""
    env = panel_and_loan(api, **spine)
    env["appraisal"] = deliver_appraisal(
        api, env["loan"]["id"], env["appraiser"]["id"], env["amc"]["id"],
        **(appraisal or {}),
    )
    rows = CLEAN_COMPARABLES if comparables is None else comparables
    env["comparables"] = add_comparables(
        api, env["appraisal"]["id"], env["amc"]["id"], rows
    )
    return env


def graded_report(api: ApiClient, **kwargs) -> Dict[str, Any]:
    """A delivered report whose receipt checks have run."""
    env = delivered_report(api, **kwargs)
    env["appraisal"] = run_rule_checks(api, env["appraisal"]["id"])
    return env


def screened_report(api: ApiClient, **kwargs) -> Dict[str, Any]:
    """A graded report whose bias screen has also run."""
    env = graded_report(api, **kwargs)
    env["appraisal"] = run_bias_screen(api, env["appraisal"]["id"])
    env["bias_flags"] = list_bias_flags(api, env["appraisal"]["id"])
    return env


def open_review(api: ApiClient, review_headers=None, **kwargs) -> Dict[str, Any]:
    """A screened report with a desk review taken into DRAFT."""
    env = screened_report(api, **kwargs)
    env["desk_review"] = open_desk_review(
        api, env["appraisal"]["id"], headers=review_headers
    )
    env["appraisal"] = read_appraisal(api, env["appraisal"]["id"])
    return env


def submitted_review(api: ApiClient, submit_headers=None, **kwargs) -> Dict[str, Any]:
    """A desk review carried through to SUBMITTED, so the matrix has resolved."""
    env = open_review(api, **kwargs)
    env["desk_review"] = submit_desk_review(
        api, env["desk_review"]["id"], headers=submit_headers
    )
    return env


def accepted_report(api: ApiClient, **kwargs) -> Dict[str, Any]:
    """
    A submitted review accepted by the panel authority.

    Acceptance is only available when the resolved requirement is NONE, so this
    helper is meant for the benign grid and narrative, where the final score is a
    perfect 10000 and the matrix asks for nothing.
    """
    env = submitted_review(api, **kwargs)
    env["desk_review"] = decide_desk_review(api, env["desk_review"]["id"], "ACCEPT")
    env["appraisal"] = read_appraisal(api, env["appraisal"]["id"])
    env["loan"] = read_loan_file(api, env["loan"]["id"])
    return env


def escalated_report(api: ApiClient, **kwargs) -> Dict[str, Any]:
    """
    A submitted review escalated by the panel authority, with its order captured.

    Escalation is only available when the resolved requirement is something other
    than NONE, so the caller must steer the grid, the narrative or the risk tier so
    that the matrix asks for a field review or a second appraisal.
    """
    env = submitted_review(api, **kwargs)
    env["desk_review"] = decide_desk_review(api, env["desk_review"]["id"], "ESCALATE")
    env["order"] = escalation_order_for(api, env["desk_review"]["id"])
    env["appraisal"] = read_appraisal(api, env["appraisal"]["id"])
    return env


# ===========================================================================
# tier 4 -- accumulation and threshold targeting
# ===========================================================================
def escalated_and_assigned(api: ApiClient, window_start: str = "2026-08-02T09:00:00Z",
                           window_end: str = "2026-08-02T12:00:00Z",
                           **kwargs) -> Dict[str, Any]:
    """
    An escalation order staffed with the second appraiser.

    Assignment is what charges the company's ledger, so this is the cheapest way to
    put a known figure into ``ytd_escalation_spend_cents``.
    """
    kwargs.setdefault("with_reviewer", True)
    env = escalated_report(api, **kwargs)
    env["order"] = assign_order(
        api, env["order"]["id"], env["reviewer"]["id"], window_start, window_end
    )
    env["amc"] = read_amc(api, env["amc"]["id"])
    return env


def escalation_completed(api: ApiClient, resulting_value_cents: int,
                         **kwargs) -> Dict[str, Any]:
    """
    An escalation order completed at a chosen value.

    Completion writes the first value revision, repoints the loan's value of record
    and drives the loan-to-value ratio, so the resulting value is the lever a test
    uses to land the ratio on a chosen band boundary.
    """
    env = escalated_and_assigned(api, **kwargs)
    env["order"] = complete_order(
        api, env["order"]["id"], env["amc"]["id"], resulting_value_cents
    )
    env["appraisal"] = read_appraisal(api, env["appraisal"]["id"])
    env["loan"] = read_loan_file(api, env["loan"]["id"])
    env["amc"] = read_amc(api, env["amc"]["id"])
    env["appraiser"] = read_appraiser(api, env["appraiser"]["id"])
    return env


def rov_awaiting_appraiser(api: ApiClient, env: Dict[str, Any],
                           requested_value_cents: int = 42000000,
                           prefix: str = "Evidence") -> Dict[str, Any]:
    """
    Take a reconsideration request from intake to the appraiser's desk.

    Routing needs two admissible items in the current round, so the helper files
    exactly two closed sales and then routes.
    """
    rov = open_rov(
        api, env["loan"]["id"], env["appraisal"]["id"],
        requested_value_cents=requested_value_cents,
    )
    file_two_admissible_items(api, rov["id"], prefix=prefix)
    env["rov"] = route_rov(api, rov["id"])
    return env


def rov_responded(api: ApiClient, env: Dict[str, Any], outcome: str,
                  revised_value_cents: Optional[int] = None,
                  **kwargs) -> Dict[str, Any]:
    """Answer a routed reconsideration, optionally revising the value."""
    env = rov_awaiting_appraiser(api, env, **kwargs)
    extra = {}
    if revised_value_cents is not None:
        extra["revised_value_cents"] = revised_value_cents
    env["rov"] = rov_respond(
        api, env["rov"]["id"], env["appraiser"]["id"], outcome, **extra
    )
    env["appraisal"] = read_appraisal(api, env["appraisal"]["id"])
    env["loan"] = read_loan_file(api, env["loan"]["id"])
    return env


def dispute_open(api: ApiClient, env: Dict[str, Any], **kwargs) -> Dict[str, Any]:
    """File a dispute against the report's authoring appraiser and company."""
    env["dispute"] = file_dispute(
        api, env["appraisal"]["id"], env["amc"]["id"], env["appraiser"]["id"], **kwargs
    )
    return env


# ===========================================================================
# tier 5 -- finalisation and terminal states
# ===========================================================================
def quarantined_report(api: ApiClient, **kwargs) -> Dict[str, Any]:
    """
    A report whose first bias flag has been substantiated.

    Substantiation snapshots the review status, quarantines the report and the
    loan's collateral dimension, and drives the authoring appraiser's panel
    standing, so it is the entry point for every quarantine-blocked operation.
    """
    env = kwargs.pop("env", None)
    if env is None:
        env = screened_report(api, **kwargs)
    flags = env.get("bias_flags") or list_bias_flags(api, env["appraisal"]["id"])
    open_flags = [row for row in flags if row["status"] == "OPEN"]
    assert open_flags, "the bias screen produced no open flag to substantiate"
    env["adjudicated_flag"] = adjudicate_flag(api, open_flags[0]["id"], "SUBSTANTIATE")
    env["appraisal"] = read_appraisal(api, env["appraisal"]["id"])
    env["loan"] = read_loan_file(api, env["loan"]["id"])
    env["appraiser"] = read_appraiser(api, env["appraiser"]["id"])
    return env


def superseded_report(api: ApiClient, **kwargs) -> Dict[str, Any]:
    """
    A report returned to the company and then replaced by a fresh delivery.

    Only a report in RETURNED_TO_AMC may be superseded, so the first report is
    carried through review and returned before the replacement is delivered.
    """
    env = submitted_review(api, **kwargs)
    env["desk_review"] = decide_desk_review(api, env["desk_review"]["id"], "RETURN")
    env["original_appraisal"] = read_appraisal(api, env["appraisal"]["id"])
    replacement = deliver_appraisal(
        api, env["loan"]["id"], env["appraiser"]["id"], env["amc"]["id"],
        supersedes_appraisal_id=env["appraisal"]["id"],
    )
    env["replacement_appraisal"] = replacement
    env["appraisal"] = read_appraisal(api, env["appraisal"]["id"])
    return env


def cancelled_order(api: ApiClient, **kwargs) -> Dict[str, Any]:
    """An assigned escalation order cancelled, which reverses the money ledger."""
    env = escalated_and_assigned(api, **kwargs)
    env["order"] = cancel_order(api, env["order"]["id"])
    env["amc"] = read_amc(api, env["amc"]["id"])
    env["desk_review"] = read_desk_review(api, env["desk_review"]["id"])
    env["appraisal"] = read_appraisal(api, env["appraisal"]["id"])
    env["loan"] = read_loan_file(api, env["loan"]["id"])
    return env
