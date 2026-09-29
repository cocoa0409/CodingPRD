"""State builders that reach every docket stage through the public surface.

Every builder drives the API exactly as a client would, so the state it leaves
behind is state the contract itself can produce. Builders are plain functions
that take the client first; they are not pytest fixtures.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data, validate_success

from . import factories as f
from .api_client import ApiClient
from .test_users import (
    ADMIN_HEADERS,
    AUDITOR_HEADERS,
    COUNSEL_HEADERS,
    DIRECTOR_ALT_HEADERS,
    DIRECTOR_HEADERS,
    INTAKE_HEADERS,
    OFFICER_HEADERS,
    make_retailer_rep_headers,
)

# The canonical incident set used by the docket chain: one medical-examiner
# hospitalisation, one retailer medical-treatment report and one hotline
# first-aid report, all verified and all carrying the BURN hazard code.
CANONICAL_INCIDENTS = (
    {
        "report_channel": "MEDICAL_EXAMINER",
        "incident_date": "2026-01-12T00:00:00Z",
        "narrative": (
            "Base plate weld failed; second-degree burn, consumer hospitalised "
            "overnight."
        ),
        "injury_class": "HOSPITALIZATION",
        "hazard_code": "BURN",
        "injury_verified": True,
    },
    {
        "report_channel": "RETAILER",
        "incident_date": "2026-01-20T00:00:00Z",
        "narrative": (
            "Store return: unit overheated and scorched the counter; consumer "
            "treated at urgent care."
        ),
        "injury_class": "MEDICAL_TREATMENT",
        "hazard_code": "BURN",
        "injury_verified": True,
    },
    {
        "report_channel": "CONSUMER_HOTLINE",
        "incident_date": "2026-02-02T00:00:00Z",
        "narrative": (
            "Hotline report: minor burn to thumb, treated with first aid at home."
        ),
        "injury_class": "FIRST_AID",
        "hazard_code": "BURN",
        "injury_verified": True,
    },
)

CHAIN_START_CLOCK = "2026-03-01T00:00:00Z"
CHAIN_SUBMIT_CLOCK = "2026-03-13T00:00:00Z"
CHAIN_MONITOR_CLOCK = "2026-03-14T00:00:00Z"


# --------------------------------------------------------------- the clock
def set_clock(api: ApiClient, to_iso8601: str) -> Dict[str, Any]:
    """Move the logical UTC clock to a named instant."""
    return get_success_data(api.set_clock(to_iso8601, headers=ADMIN_HEADERS))


# ------------------------------------------------------------- the registry
def create_product_model(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """Register one product model."""
    return validate_success(
        api.create_product_model(
            f.product_model_payload(**overrides), headers=ADMIN_HEADERS
        ),
        201,
    )


def create_retailer(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """Register one retailer."""
    return validate_success(
        api.create_retailer(f.retailer_payload(**overrides), headers=ADMIN_HEADERS),
        201,
    )


def get_product_model(api: ApiClient, model_id: str) -> Dict[str, Any]:
    """Read one product model back."""
    return validate_success(api.get_product_model(model_id, headers=ADMIN_HEADERS))


def get_retailer(api: ApiClient, retailer_id: str) -> Dict[str, Any]:
    """Read one retailer back."""
    return validate_success(api.get_retailer(retailer_id, headers=ADMIN_HEADERS))


# ------------------------------------------------------------- the intake
def create_incident(
    api: ApiClient, product_model_id: str, **overrides: Any
) -> Dict[str, Any]:
    """Record one incident report in INTAKE."""
    return validate_success(
        api.create_incident(
            f.incident_payload(product_model_id, **overrides), headers=INTAKE_HEADERS
        ),
        201,
    )


def classify_incident(
    api: ApiClient, incident_id: str, **overrides: Any
) -> Dict[str, Any]:
    """Classify one incident and recompute its severity weight."""
    return validate_success(
        api.classify_incident(
            incident_id, f.classify_payload(**overrides), headers=INTAKE_HEADERS
        )
    )


def classified_incident(
    api: ApiClient,
    product_model_id: str,
    *,
    report_channel: str = "CONSUMER_HOTLINE",
    incident_date: str = "2026-01-12T00:00:00Z",
    narrative: str = "Consumer reports the unit overheated during normal use.",
    injury_class: str = "HOSPITALIZATION",
    hazard_code: str = "BURN",
    injury_verified: bool = True,
) -> Dict[str, Any]:
    """Record one incident and classify it in a single step."""
    incident = create_incident(
        api,
        product_model_id,
        report_channel=report_channel,
        incident_date=incident_date,
        narrative=narrative,
    )
    return classify_incident(
        api,
        incident["id"],
        injury_class=injury_class,
        hazard_code=hazard_code,
        injury_verified=injury_verified,
    )


def canonical_incident_set(
    api: ApiClient, product_model_id: str
) -> List[Dict[str, Any]]:
    """Record and classify the canonical three-incident burn cluster."""
    rows = []
    for spec in CANONICAL_INCIDENTS:
        rows.append(classified_incident(api, product_model_id, **spec))
    return rows


def get_incident(api: ApiClient, incident_id: str) -> Dict[str, Any]:
    """Read one incident report back."""
    return validate_success(api.get_incident(incident_id, headers=INTAKE_HEADERS))


# ------------------------------------------------------- the hazard analysis
def create_pattern(
    api: ApiClient,
    product_model_id: str,
    expected_product_model_version: int,
    **overrides: Any,
) -> Dict[str, Any]:
    """Open a hazard pattern analysis over one model's incidents."""
    return validate_success(
        api.create_hazard_pattern(
            f.hazard_pattern_payload(
                product_model_id, expected_product_model_version, **overrides
            ),
            headers=OFFICER_HEADERS,
        ),
        201,
    )


def recompute_pattern(
    api: ApiClient, pattern_id: str, **overrides: Any
) -> Dict[str, Any]:
    """Re-run an analysed pattern, optionally over a new basis or window."""
    return validate_success(
        api.recompute_hazard_pattern(pattern_id, overrides, headers=OFFICER_HEADERS)
    )


def adjudicate_pattern(
    api: ApiClient, pattern_id: str, decision: str = "CONFIRMED", **overrides: Any
) -> Dict[str, Any]:
    """Confirm or dismiss an analysed pattern."""
    return validate_success(
        api.adjudicate_hazard_pattern(
            pattern_id,
            f.adjudicate_payload(decision=decision, **overrides),
            headers=OFFICER_HEADERS,
        )
    )


def get_pattern(api: ApiClient, pattern_id: str) -> Dict[str, Any]:
    """Read one hazard pattern back."""
    return validate_success(api.get_hazard_pattern(pattern_id, headers=OFFICER_HEADERS))


# --------------------------------------------------- the reportability docket
def create_evaluation(
    api: ApiClient, hazard_pattern_id: str, **overrides: Any
) -> Dict[str, Any]:
    """Open a reportability evaluation on a confirmed pattern."""
    return validate_success(
        api.create_evaluation(
            f.evaluation_payload(hazard_pattern_id, **overrides),
            headers=OFFICER_HEADERS,
        ),
        201,
    )


def begin_review(api: ApiClient, evaluation_id: str) -> Dict[str, Any]:
    """Begin the internal review of an open evaluation."""
    return validate_success(api.begin_review(evaluation_id, headers=OFFICER_HEADERS))


def determine_evaluation(
    api: ApiClient, evaluation_id: str, **overrides: Any
) -> Dict[str, Any]:
    """Record the reportability determination."""
    return validate_success(
        api.determine_evaluation(
            evaluation_id, f.determination_payload(**overrides), headers=OFFICER_HEADERS
        )
    )


def get_evaluation(api: ApiClient, evaluation_id: str) -> Dict[str, Any]:
    """Read one reportability evaluation back."""
    return validate_success(api.get_evaluation(evaluation_id, headers=OFFICER_HEADERS))


# ------------------------------------------------------ the statutory report
def create_section_report(
    api: ApiClient, evaluation_id: str, **overrides: Any
) -> Dict[str, Any]:
    """Draft the statutory report for a reportable evaluation."""
    return validate_success(
        api.create_section_report(
            f.section_report_payload(evaluation_id, **overrides),
            headers=OFFICER_HEADERS,
        ),
        201,
    )


def submit_section_report(api: ApiClient, report_id: str) -> Dict[str, Any]:
    """File the statutory report and score its lateness."""
    return validate_success(
        api.submit_section_report(report_id, headers=OFFICER_HEADERS)
    )


def review_section_report(
    api: ApiClient, report_id: str, decision: str = "ACCEPTED", **overrides: Any
) -> Dict[str, Any]:
    """Accept a filed report or return it for further information."""
    return validate_success(
        api.review_section_report(
            report_id,
            f.review_payload(decision=decision, **overrides),
            headers=DIRECTOR_HEADERS,
        )
    )


def revise_section_report(
    api: ApiClient, report_id: str, **overrides: Any
) -> Dict[str, Any]:
    """Put a returned report back into draft."""
    return validate_success(
        api.revise_section_report(report_id, overrides, headers=OFFICER_HEADERS)
    )


def get_section_report(api: ApiClient, report_id: str) -> Dict[str, Any]:
    """Read one statutory report back."""
    return validate_success(api.get_section_report(report_id, headers=OFFICER_HEADERS))


# ------------------------------------------------------------- the recall plan
def create_recall(
    api: ApiClient, section_report_id: str, **overrides: Any
) -> Dict[str, Any]:
    """Draft a corrective action plan against an accepted report."""
    return validate_success(
        api.create_recall(
            f.recall_payload(section_report_id, **overrides), headers=OFFICER_HEADERS
        ),
        201,
    )


def submit_plan(api: ApiClient, recall_id: str) -> Dict[str, Any]:
    """Submit a drafted plan for approval as the filing officer."""
    return validate_success(api.submit_plan(recall_id, headers=OFFICER_HEADERS))


def approve_plan(api: ApiClient, recall_id: str) -> Dict[str, Any]:
    """Approve a submitted plan as the signing director."""
    return validate_success(api.approve_plan(recall_id, headers=DIRECTOR_HEADERS))


def begin_monitoring(api: ApiClient, recall_id: str) -> Dict[str, Any]:
    """Move an approved recall into monitoring."""
    return validate_success(api.begin_monitoring(recall_id, headers=DIRECTOR_HEADERS))


def compliance_sweep(api: ApiClient, recall_id: str) -> Dict[str, Any]:
    """Sweep the recall's notifications for expired acknowledgements."""
    return validate_success(api.compliance_sweep(recall_id, headers=DIRECTOR_HEADERS))


def close_recall(api: ApiClient, recall_id: str) -> Dict[str, Any]:
    """Close a monitored recall."""
    return validate_success(api.close_recall(recall_id, headers=DIRECTOR_HEADERS))


def get_recall(api: ApiClient, recall_id: str) -> Dict[str, Any]:
    """Read one recall plan back."""
    return validate_success(api.get_recall(recall_id, headers=OFFICER_HEADERS))


# -------------------------------------------------------- the retailer channel
def create_notification(
    api: ApiClient, recall_id: str, retailer_id: str, **overrides: Any
) -> Dict[str, Any]:
    """Enrol one retailer in a recall's stop-sale list."""
    return validate_success(
        api.create_retailer_notification(
            f.retailer_notification_payload(recall_id, retailer_id, **overrides),
            headers=OFFICER_HEADERS,
        ),
        201,
    )


def acknowledge_notification(
    api: ApiClient, notification_id: str, units_on_shelf_reported: int = 0
) -> Dict[str, Any]:
    """Acknowledge a stop-sale notification as the compliance officer."""
    return validate_success(
        api.acknowledge_notification(
            notification_id,
            f.acknowledge_payload(units_on_shelf_reported=units_on_shelf_reported),
            headers=OFFICER_HEADERS,
        )
    )


def acknowledge_as_retailer(
    api: ApiClient,
    notification_id: str,
    retailer_id: str,
    units_on_shelf_reported: int = 0,
) -> Dict[str, Any]:
    """Acknowledge a stop-sale notification as that retailer's own rep."""
    return validate_success(
        api.acknowledge_notification(
            notification_id,
            f.acknowledge_payload(units_on_shelf_reported=units_on_shelf_reported),
            headers=make_retailer_rep_headers(retailer_id),
        )
    )


def verify_notification(api: ApiClient, notification_id: str) -> Dict[str, Any]:
    """Verify shelf removal on one notification."""
    return validate_success(
        api.verify_notification(notification_id, headers=DIRECTOR_HEADERS)
    )


def get_notification(api: ApiClient, notification_id: str) -> Dict[str, Any]:
    """Read one retailer notification back."""
    return validate_success(
        api.get_retailer_notification(notification_id, headers=OFFICER_HEADERS)
    )


def list_notifications(api: ApiClient, **params: Any):
    """List retailer notifications under the given filters."""
    return api.list_retailer_notifications(params, headers=OFFICER_HEADERS)


# ------------------------------------------------------------- shelf audits
def create_audit_visit(
    api: ApiClient, notification_id: str, **overrides: Any
) -> Dict[str, Any]:
    """Schedule one shelf audit visit."""
    return validate_success(
        api.create_audit_visit(
            f.audit_visit_payload(notification_id, **overrides),
            headers=AUDITOR_HEADERS,
        ),
        201,
    )


def complete_audit_visit(
    api: ApiClient, visit_id: str, verdict: str = "PASS", shelf_units_found: int = 0
) -> Dict[str, Any]:
    """Record the verdict and the shelf units found on one visit."""
    return validate_success(
        api.complete_audit_visit(
            visit_id,
            f.complete_visit_payload(
                verdict=verdict, shelf_units_found=shelf_units_found
            ),
            headers=AUDITOR_HEADERS,
        )
    )


def get_audit_visit(api: ApiClient, visit_id: str) -> Dict[str, Any]:
    """Read one audit visit back."""
    return validate_success(api.get_audit_visit(visit_id, headers=AUDITOR_HEADERS))


def passing_visit(
    api: ApiClient, notification_id: str, **overrides: Any
) -> Dict[str, Any]:
    """Schedule and complete one passing shelf audit visit."""
    visit = create_audit_visit(api, notification_id, **overrides)
    return complete_audit_visit(api, visit["id"], verdict="PASS", shelf_units_found=0)


# ------------------------------------------------------------ consumer notices
def create_notice(api: ApiClient, recall_id: str, **overrides: Any) -> Dict[str, Any]:
    """Schedule one consumer notice."""
    return validate_success(
        api.create_consumer_notice(
            f.consumer_notice_payload(recall_id, **overrides), headers=OFFICER_HEADERS
        ),
        201,
    )


def release_notice(api: ApiClient, notice_id: str) -> Dict[str, Any]:
    """Release one scheduled notice."""
    return validate_success(
        api.release_consumer_notice(notice_id, headers=OFFICER_HEADERS)
    )


def get_notice(api: ApiClient, notice_id: str) -> Dict[str, Any]:
    """Read one consumer notice back."""
    return validate_success(api.get_consumer_notice(notice_id, headers=OFFICER_HEADERS))


# --------------------------------------------------------------- remedy ledger
def create_claim(api: ApiClient, recall_id: str, **overrides: Any) -> Dict[str, Any]:
    """Register one consumer remedy claim."""
    return validate_success(
        api.create_remedy_claim(
            f.remedy_claim_payload(recall_id, **overrides), headers=OFFICER_HEADERS
        ),
        201,
    )


def approve_claim(api: ApiClient, claim_id: str) -> Dict[str, Any]:
    """Approve one submitted remedy claim."""
    return validate_success(api.approve_claim(claim_id, headers=OFFICER_HEADERS))


def fulfill_claim(api: ApiClient, claim_id: str) -> Dict[str, Any]:
    """Fulfil one approved remedy claim."""
    return validate_success(api.fulfill_claim(claim_id, headers=OFFICER_HEADERS))


def void_claim(api: ApiClient, claim_id: str, **overrides: Any) -> Dict[str, Any]:
    """Void one remedy claim."""
    return validate_success(api.void_claim(claim_id, overrides, headers=OFFICER_HEADERS))


def get_claim(api: ApiClient, claim_id: str) -> Dict[str, Any]:
    """Read one remedy claim back."""
    return validate_success(api.get_remedy_claim(claim_id, headers=OFFICER_HEADERS))


def fulfilled_claim(api: ApiClient, recall_id: str, **overrides: Any) -> Dict[str, Any]:
    """Register, approve and fulfil one remedy claim in a single step."""
    claim = create_claim(api, recall_id, **overrides)
    approve_claim(api, claim["id"])
    return fulfill_claim(api, claim["id"])


# ------------------------------------------------------------ progress reports
def create_progress_report(
    api: ApiClient, recall_id: str, **overrides: Any
) -> Dict[str, Any]:
    """Open one monthly reporting period on a recall."""
    return validate_success(
        api.create_progress_report(
            f.progress_report_payload(recall_id, **overrides), headers=OFFICER_HEADERS
        ),
        201,
    )


def submit_progress_report(api: ApiClient, report_id: str) -> Dict[str, Any]:
    """File one monthly progress report."""
    return validate_success(
        api.submit_progress_report(report_id, headers=OFFICER_HEADERS)
    )


def accept_progress_report(api: ApiClient, report_id: str) -> Dict[str, Any]:
    """Accept one filed progress report as the signing director."""
    return validate_success(
        api.accept_progress_report(report_id, headers=DIRECTOR_HEADERS)
    )


def get_progress_report(api: ApiClient, report_id: str) -> Dict[str, Any]:
    """Read one monthly progress report back."""
    return validate_success(
        api.get_progress_report(report_id, headers=OFFICER_HEADERS)
    )


def submitted_progress_report(
    api: ApiClient, recall_id: str, **overrides: Any
) -> Dict[str, Any]:
    """Open and file one monthly progress report."""
    report = create_progress_report(api, recall_id, **overrides)
    return submit_progress_report(api, report["id"])


def accepted_progress_report(
    api: ApiClient, recall_id: str, **overrides: Any
) -> Dict[str, Any]:
    """Open, file and accept one monthly progress report."""
    report = submitted_progress_report(api, recall_id, **overrides)
    return accept_progress_report(api, report["id"])


# --------------------------------------------------------- the penalty docket
def create_penalty_case(
    api: ApiClient, section_report_id: str, **overrides: Any
) -> Dict[str, Any]:
    """Open one civil penalty docket."""
    return validate_success(
        api.create_penalty_case(
            f.penalty_case_payload(section_report_id, **overrides),
            headers=COUNSEL_HEADERS,
        ),
        201,
    )


def make_offer(
    api: ApiClient,
    case_id: str,
    amount_cents: int,
    offered_by: str,
    expected_case_version: int,
) -> Dict[str, Any]:
    """Table one settlement offer, pinning the case version."""
    return validate_success(
        api.create_offer(
            case_id,
            f.offer_payload(amount_cents, offered_by, expected_case_version),
            headers=COUNSEL_HEADERS,
        )
    )


def resolve_offer(api: ApiClient, case_id: str, resolution: str, **overrides: Any):
    """Withdraw or accept the standing agency offer."""
    return validate_success(
        api.resolve_offer(
            case_id,
            f.offer_resolution_payload(resolution=resolution, **overrides),
            headers=COUNSEL_HEADERS,
        )
    )


def get_penalty_case(api: ApiClient, case_id: str) -> Dict[str, Any]:
    """Read one civil penalty case back."""
    return validate_success(api.get_penalty_case(case_id, headers=COUNSEL_HEADERS))


# ===========================================================================
# Composite environments. Each one drives the docket a stage further and
# returns every row the caller may need to assert against.
# ===========================================================================
def analyzed_pattern_env(
    api: ApiClient,
    *,
    clock: Optional[str] = CHAIN_START_CLOCK,
    model: Optional[Dict[str, Any]] = None,
    incidents: Optional[Any] = None,
    **pattern_overrides: Any,
) -> Dict[str, Any]:
    """A registered model, its classified incident set and one analysed pattern."""
    if clock is not None:
        set_clock(api, clock)
    model_row = create_product_model(api, **(model or {}))
    specs = CANONICAL_INCIDENTS if incidents is None else incidents
    incident_rows = [classified_incident(api, model_row["id"], **spec) for spec in specs]
    model_row = get_product_model(api, model_row["id"])
    pattern = create_pattern(
        api, model_row["id"], model_row["version"], **pattern_overrides
    )
    return {
        "model": get_product_model(api, model_row["id"]),
        "model_id": model_row["id"],
        "incidents": incident_rows,
        "pattern": pattern,
        "pattern_id": pattern["id"],
    }


def confirmed_pattern_env(api: ApiClient, **kwargs: Any) -> Dict[str, Any]:
    """An analysed pattern carried through adjudication to CONFIRMED."""
    env = analyzed_pattern_env(api, **kwargs)
    env["pattern"] = adjudicate_pattern(api, env["pattern_id"], "CONFIRMED")
    return env


def evaluation_env(
    api: ApiClient,
    *,
    standard_basis: str = "DEFECT",
    **kwargs: Any,
) -> Dict[str, Any]:
    """A confirmed pattern with one reportability evaluation opened on it."""
    env = confirmed_pattern_env(api, **kwargs)
    evaluation = create_evaluation(
        api, env["pattern_id"], standard_basis=standard_basis
    )
    env["evaluation"] = evaluation
    env["evaluation_id"] = evaluation["id"]
    return env


def determined_evaluation_env(
    api: ApiClient,
    *,
    determination: Optional[Dict[str, Any]] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """An evaluation carried through review to a recorded determination."""
    env = evaluation_env(api, **kwargs)
    begin_review(api, env["evaluation_id"])
    env["evaluation"] = determine_evaluation(
        api, env["evaluation_id"], **(determination or {})
    )
    env["model"] = get_product_model(api, env["model_id"])
    return env


def draft_report_env(
    api: ApiClient,
    *,
    report: Optional[Dict[str, Any]] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """A reportable evaluation with its statutory report still in DRAFT."""
    env = determined_evaluation_env(api, **kwargs)
    row = create_section_report(api, env["evaluation_id"], **(report or {}))
    env["report"] = row
    env["report_id"] = row["id"]
    return env


def submitted_report_env(
    api: ApiClient,
    *,
    submit_clock: Optional[str] = CHAIN_SUBMIT_CLOCK,
    **kwargs: Any,
) -> Dict[str, Any]:
    """A statutory report filed against its own report_due_at."""
    env = draft_report_env(api, **kwargs)
    if submit_clock is not None:
        set_clock(api, submit_clock)
    env["report"] = submit_section_report(api, env["report_id"])
    return env


def accepted_report_env(api: ApiClient, **kwargs: Any) -> Dict[str, Any]:
    """A filed statutory report accepted by the signing director."""
    env = submitted_report_env(api, **kwargs)
    env["report"] = review_section_report(api, env["report_id"], "ACCEPTED")
    return env


def draft_recall_env(
    api: ApiClient,
    *,
    recall: Optional[Dict[str, Any]] = None,
    notice: Optional[Dict[str, Any]] = None,
    retailer: Optional[Dict[str, Any]] = None,
    enroll_retailer: bool = True,
    schedule_notice: bool = True,
    **kwargs: Any,
) -> Dict[str, Any]:
    """A drafted recall plan with its direct notice and one enrolled retailer."""
    env = accepted_report_env(api, **kwargs)
    row = create_recall(api, env["report_id"], **(recall or {}))
    env["recall"] = row
    env["recall_id"] = row["id"]
    if schedule_notice:
        notice_row = create_notice(api, row["id"], **(notice or {}))
        env["notice"] = notice_row
        env["notice_id"] = notice_row["id"]
    if enroll_retailer:
        retailer_row = create_retailer(api, **(retailer or {}))
        notification = create_notification(api, row["id"], retailer_row["id"])
        env["retailer"] = retailer_row
        env["retailer_id"] = retailer_row["id"]
        env["notification"] = notification
        env["notification_id"] = notification["id"]
    return env


def submitted_recall_env(api: ApiClient, **kwargs: Any) -> Dict[str, Any]:
    """A drafted plan submitted for approval by the filing officer."""
    env = draft_recall_env(api, **kwargs)
    env["recall"] = submit_plan(api, env["recall_id"])
    return env


def approved_recall_env(api: ApiClient, **kwargs: Any) -> Dict[str, Any]:
    """A submitted plan approved by the signing director, stop-sale cascaded."""
    env = submitted_recall_env(api, **kwargs)
    env["recall"] = approve_plan(api, env["recall_id"])
    if "notification_id" in env:
        env["notification"] = get_notification(api, env["notification_id"])
        env["retailer"] = get_retailer(api, env["retailer_id"])
    return env


def monitoring_recall_env(
    api: ApiClient,
    *,
    monitor_clock: Optional[str] = CHAIN_MONITOR_CLOCK,
    **kwargs: Any,
) -> Dict[str, Any]:
    """An approved recall whose notice is released and which is now monitoring."""
    env = approved_recall_env(api, **kwargs)
    if monitor_clock is not None:
        set_clock(api, monitor_clock)
    if "notice_id" in env:
        env["notice"] = release_notice(api, env["notice_id"])
    env["recall"] = begin_monitoring(api, env["recall_id"])
    return env


def satisfied_notification_env(api: ApiClient, **kwargs: Any) -> Dict[str, Any]:
    """A monitoring recall whose only notification is verified and satisfied."""
    env = monitoring_recall_env(api, **kwargs)
    acknowledge_notification(api, env["notification_id"], units_on_shelf_reported=0)
    passing_visit(api, env["notification_id"])
    env["notification"] = verify_notification(api, env["notification_id"])
    env["retailer"] = get_retailer(api, env["retailer_id"])
    env["recall"] = get_recall(api, env["recall_id"])
    return env


def penalty_case_env(
    api: ApiClient,
    *,
    violation_count: int = 4,
    **kwargs: Any,
) -> Dict[str, Any]:
    """A monitoring recall with a civil penalty docket on the same report."""
    env = monitoring_recall_env(api, **kwargs)
    case = create_penalty_case(
        api, env["report_id"], violation_count=violation_count
    )
    env["case"] = case
    env["case_id"] = case["id"]
    return env


def penalty_case_on_report_env(
    api: ApiClient,
    *,
    violation_count: int = 4,
    **kwargs: Any,
) -> Dict[str, Any]:
    """A filed statutory report with a civil penalty docket and no recall."""
    env = submitted_report_env(api, **kwargs)
    case = create_penalty_case(
        api, env["report_id"], violation_count=violation_count
    )
    env["case"] = case
    env["case_id"] = case["id"]
    return env
