"""Row lookups with the owning entity's not-found error, plus docket chains."""

import store
from errors import raise_error

_COLLECTIONS = {
    "product_model": (lambda: store.product_models, "ERR_PRODUCT_MODEL_NOT_FOUND"),
    "incident": (lambda: store.incidents, "ERR_INCIDENT_NOT_FOUND"),
    "hazard_pattern": (lambda: store.hazard_patterns, "ERR_HAZARD_PATTERN_NOT_FOUND"),
    "evaluation": (lambda: store.evaluations, "ERR_EVALUATION_NOT_FOUND"),
    "section_report": (lambda: store.section_reports, "ERR_SECTION_REPORT_NOT_FOUND"),
    "recall": (lambda: store.recalls, "ERR_RECALL_NOT_FOUND"),
    "retailer": (lambda: store.retailers, "ERR_RETAILER_NOT_FOUND"),
    "retailer_notification": (lambda: store.retailer_notifications,
                              "ERR_RETAILER_NOTIFICATION_NOT_FOUND"),
    "audit_visit": (lambda: store.audit_visits, "ERR_AUDIT_VISIT_NOT_FOUND"),
    "consumer_notice": (lambda: store.consumer_notices, "ERR_CONSUMER_NOTICE_NOT_FOUND"),
    "remedy_claim": (lambda: store.remedy_claims, "ERR_REMEDY_CLAIM_NOT_FOUND"),
    "progress_report": (lambda: store.progress_reports, "ERR_PROGRESS_REPORT_NOT_FOUND"),
    "penalty_case": (lambda: store.penalty_cases, "ERR_PENALTY_CASE_NOT_FOUND"),
}


def find(kind, row_id):
    getter, error_id = _COLLECTIONS[kind]
    if not isinstance(row_id, str):
        raise_error(error_id)
    row = getter().get(row_id)
    if row is None:
        raise_error(error_id)
    return row


def maybe(kind, row_id):
    getter, _error_id = _COLLECTIONS[kind]
    if not isinstance(row_id, str):
        return None
    return getter().get(row_id)


# --- docket chains ---------------------------------------------------------
def model_for_evaluation(evaluation):
    return maybe("product_model", evaluation["product_model_id"])


def model_for_report(report):
    evaluation = maybe("evaluation", report["reportability_evaluation_id"])
    if evaluation is None:
        return None
    return model_for_evaluation(evaluation)


def model_for_recall(recall):
    """recall -> section_report -> reportability_evaluation -> product_model."""
    report = maybe("section_report", recall["section_report_id"])
    if report is None:
        return None
    return model_for_report(report)


def pattern_for_report(report):
    evaluation = maybe("evaluation", report["reportability_evaluation_id"])
    if evaluation is None:
        return None
    return evaluation["hazard_pattern_id"]
