"""Composite setup helpers.

Every helper builds preconditions from scratch using only PRD-declared
endpoints (each test runs against a freshly restarted server with an empty
database). Setup calls use get_success_data so failures surface as clear
"Setup failed" errors. All callers are responsible for their own assertions.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_bid_payload,
    create_gap_payload,
    create_insurance_certificate_payload,
    create_project_payload,
    create_sov_payload,
    create_subcontract_payload,
    create_trade_package_payload,
)
from .test_users import TEST_USERS

ADMIN = TEST_USERS["gc_admin_headers"]
BL = TEST_USERS["buyout_lead_headers"]
OM = TEST_USERS["ops_manager_headers"]
PM = TEST_USERS["project_manager_headers"]
VP = TEST_USERS["vice_president_headers"]


def _fail(step, resp):
    raise AssertionError(
        f"Setup failed at {step}: HTTP {resp.status_code} {resp.text}"
    )


def _ok(step, resp, expected=None):
    data = get_success_data(resp)
    if expected is not None and isinstance(data, dict):
        status = data.get("status")
        assert status == expected, (
            f"Setup failed at {step}: expected status {expected}, got {status}"
        )
    return data


# ---------------------------------------------------------------------------
# Tier 1 — project / package stand-up
# ---------------------------------------------------------------------------

def create_project(name, number, estimated_budget_cents=50_000_000,
                   target_pct=0.05):
    resp = api_client.create_project(
        create_project_payload(
            name=name, project_number=number,
            estimated_budget_cents=estimated_budget_cents,
            buyout_target_savings_pct=target_pct,
        ),
        ADMIN,
    )
    return _ok("create_project", resp)


def create_open_project(name, number, estimated_budget_cents=50_000_000,
                        target_pct=0.05):
    """Create + open a project. Returns (project, project_version)."""
    proj = create_project(name, number, estimated_budget_cents, target_pct)
    resp = api_client.open_project(proj["id"], ADMIN)
    opened = _ok("open_project", resp)
    return opened, opened["version"]


def create_package(project_id, project_version, name="Pkg",
                   trade_code="26-ELEC", budget=10_000_000, contingency=0,
                   bonding_policy="WAIVED", bid_due_at="2026-05-20T16:00:00Z",
                   spec_section="26 00 00", as_headers=None):
    resp = api_client.create_trade_package(
        project_id,
        create_trade_package_payload(
            expected_project_version=project_version,
            trade_code=trade_code, title=name,
            estimated_budget_cents=budget,
            budgeted_contingency_cents=contingency,
            spec_section=spec_section, bid_due_at=bid_due_at,
            bonding_policy=bonding_policy,
        ),
        as_headers or BL,
    )
    return _ok("create_trade_package", resp)


def publish_package(package_id):
    resp = api_client.publish_trade_package(package_id, BL)
    return _ok("publish_trade_package", resp, expected="PUBLISHED")


def place_bid(package_id, bidder_name, base_bid_cents,
              bid_received_at="2026-05-15T12:00:00Z", as_headers=None,
              **overrides):
    resp = api_client.create_bid(
        package_id,
        create_bid_payload(
            bidder_name=bidder_name, base_bid_cents=base_bid_cents,
            bid_received_at=bid_received_at,
            contact_email=overrides.pop("contact_email",
                                        f"{bidder_name.lower().replace(' ', '')}@x.com"),
            **overrides,
        ),
        as_headers or BL,
    )
    return _ok("create_bid", resp, expected="PLACED")


def withdraw_bid(package_id, bid_id):
    resp = api_client.withdraw_bid(package_id, bid_id, BL)
    return _ok("withdraw_bid", resp, expected="WITHDRAWN")


def close_bidding(package_id):
    resp = api_client.close_bidding(package_id, BL)
    return _ok("close_bidding", resp, expected="UNDER_LEVELING")


def setup_leveling_package(project_id, project_version, *, name="Pkg",
                           trade_code, budget=10_000_000, contingency=0,
                           bonding_policy="WAIVED",
                           bid_due_at="2026-05-20T16:00:00Z",
                           bids=((9_000_000, "2026-05-15T12:00:00Z"),
                                 (9_100_000, "2026-05-15T13:00:00Z")),
                           withdraw_last=True):
    """Package published + bids placed + bidding closed (+ last bid withdrawn).

    Returns dict(package=..., bids=[bid,...], withdrawn=bid-or-None).
    The withdrawn-bid pattern satisfies the subcontract-creation precondition
    (at least two bids and at least one WITHDRAWN) used across the suite.
    """
    pkg = create_package(
        project_id, project_version, name=name, trade_code=trade_code,
        budget=budget, contingency=contingency, bonding_policy=bonding_policy,
        bid_due_at=bid_due_at,
    )
    publish_package(pkg["id"])
    placed = []
    for i, (amount, received_at) in enumerate(bids):
        placed.append(place_bid(
            pkg["id"], f"{name} Bidder {i+1}", amount,
            bid_received_at=received_at,
        ))
    close_bidding(pkg["id"])
    withdrawn = None
    if withdraw_last and placed:
        withdrawn = withdraw_bid(pkg["id"], placed[-1]["id"])
    return {"package": pkg, "bids": placed, "withdrawn": withdrawn}


# ---------------------------------------------------------------------------
# Tier 2 — subcontract creation and lifecycle walks
# ---------------------------------------------------------------------------

# Explicit requirements snapshot pinned at draft creation (PRD 3.4: a draft
# may carry "an `insurance_requirements_snapshot` pinning the required
# limits"). PRD 3.7 says "server defaults apply to any requirement omitted
# at draft time" without naming them, so tests pin the requirements the
# compliant-certificate factory is built against rather than relying on
# unstated server defaults.
DEFAULT_INSURANCE_REQUIREMENTS_SNAPSHOT = {
    "gl_occurrence_cents": 1_000_000,
    "gl_aggregate_cents": 2_000_000,
    "auto_cents": 1_000_000,
    "umbrella_cents": 5_000_000,
    "workers_comp": "STATUTORY",
    "ai_required": True,
    "wos_required": True,
    "ptd_required": True,
    "pollution_required": False,
}


def create_draft_subcontract(package_id, source_bid_id, subcontractor_name,
                             payment_terms=None, change_authority_limits=None,
                             insurance_requirements_snapshot=None):
    payload = create_subcontract_payload(
        source_bid_id,
        subcontractor_name=subcontractor_name,
        payment_terms=payment_terms or {"retainage_pct": 0.10,
                                        "pay_if_paid": True},
        change_authority_limits=(
            change_authority_limits
            if change_authority_limits is not None
            else [{"max_value_cents": -1, "max_cumulative_pct": -1,
                   "roles": ["OperationsManager"]}]
        ),
    )
    payload["insurance_requirements_snapshot"] = (
        insurance_requirements_snapshot
        if insurance_requirements_snapshot is not None
        else dict(DEFAULT_INSURANCE_REQUIREMENTS_SNAPSHOT)
    )
    resp = api_client.create_subcontract(package_id, payload, BL)
    return _ok("create_subcontract", resp, expected="DRAFT")


def recommend(subcontract_id, contract_value_cents, as_headers=None,
              **extra):
    payload = {"contract_value_cents": contract_value_cents}
    payload.update(extra)
    resp = api_client.recommend_award(subcontract_id, payload,
                                      as_headers or BL)
    return _ok("recommend_award", resp, expected="PENDING_AWARD")


def award_sub(subcontract_id):
    resp = api_client.award_subcontract(subcontract_id, OM)
    return _ok("award_subcontract", resp, expected="AWARDED")


def register_compliant_cert(subcontract_id, certificate_number="CERT-1",
                            **overrides):
    resp = api_client.create_insurance_certificate(
        subcontract_id,
        create_insurance_certificate_payload(
            certificate_number=certificate_number, **overrides),
        BL,
    )
    return _ok("register_compliant_cert", resp)


def issue_sub(subcontract_id):
    resp = api_client.issue_subcontract(subcontract_id, BL)
    return _ok("issue_subcontract", resp, expected="ISSUED")


def execute_sub(subcontract_id):
    resp = api_client.execute_subcontract(subcontract_id, BL)
    return _ok("execute_subcontract", resp, expected="EXECUTED")


def setup_awarded_subcontract(project_id, project_version, *, name="Pkg",
                              trade_code, budget=10_000_000, contingency=0,
                              bonding_policy="WAIVED",
                              bid_amount=9_000_000,
                              contract_value_cents=None,
                              bid_due_at="2026-05-20T16:00:00Z",
                              bid_received_at="2026-05-15T12:00:00Z",
                              change_authority_limits=None,
                              recommend_extra=None):
    """Leveling package with one AWARDED subcontract (WAIVED bond path).

    Returns dict(package, bid, subcontract).
    """
    ctx = setup_leveling_package(
        project_id, project_version, name=name, trade_code=trade_code,
        budget=budget, contingency=contingency, bonding_policy=bonding_policy,
        bid_due_at=bid_due_at,
        bids=((bid_amount, bid_received_at),
              (bid_amount + 100_000, "2026-05-15T13:00:00Z")),
        withdraw_last=True,
    )
    sub = create_draft_subcontract(
        ctx["package"]["id"], ctx["bids"][0]["id"], f"{name} Sub 1",
        change_authority_limits=change_authority_limits,
    )
    recommend(sub["id"],
              contract_value_cents if contract_value_cents is not None
              else bid_amount,
              **(recommend_extra or {}))
    award_sub(sub["id"])
    return {"package": ctx["package"], "bid": ctx["bids"][0],
            "withdrawn_bid": ctx["withdrawn"], "subcontract": sub}


def setup_issued_subcontract(project_id, project_version, **kwargs):
    """setup_awarded_subcontract + compliant certificate + issue.

    Returns dict with the awarded context plus the certificate.
    """
    ctx = setup_awarded_subcontract(project_id, project_version, **kwargs)
    cert = register_compliant_cert(ctx["subcontract"]["id"])
    issue_sub(ctx["subcontract"]["id"])
    ctx["certificate"] = cert
    return ctx


def setup_executed_subcontract(project_id, project_version, **kwargs):
    """setup_issued_subcontract + execute.

    Note: with a lone subcontract, execution bubbles the package to AWARDED;
    pass keep_in_progress_via to pin the package at BUYOUT_IN_PROGRESS.
    """
    ctx = setup_issued_subcontract(project_id, project_version, **kwargs)
    execute_sub(ctx["subcontract"]["id"])
    return ctx


def setup_executed_with_approved_sov(project_id, project_version,
                                     sov_lines=None, **kwargs):
    """EXECUTED subcontract with an APPROVED schedule of values.

    Returns the executed context plus the SOV record.
    """
    ctx = setup_executed_subcontract(project_id, project_version, **kwargs)
    resp = api_client.create_sov(
        ctx["subcontract"]["id"],
        create_sov_payload(lines=sov_lines) if sov_lines else create_sov_payload(),
        BL,
    )
    sov = _ok("create_sov", resp)
    api_client.approve_sov(sov["id"], OM)
    ctx["sov"] = sov
    return ctx


# ---------------------------------------------------------------------------
# Tier 3 — change-order helpers
# ---------------------------------------------------------------------------

def create_and_submit_co(subcontract_id, amount_cents, creator_headers,
                         description="change order"):
    resp = api_client.create_change_order(
        subcontract_id,
        {"description": description, "amount_cents": amount_cents},
        creator_headers,
    )
    co = _ok("create_change_order", resp, expected="DRAFT")
    resp = api_client.submit_change_order(co["id"], BL)
    _ok("submit_change_order", resp, expected="PENDING_APPROVAL")
    return co
