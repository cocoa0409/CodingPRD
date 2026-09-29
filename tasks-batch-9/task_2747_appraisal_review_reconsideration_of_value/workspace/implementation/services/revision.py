"""Value revision ledger writer and the revision cap guard."""

import db
from validate import bps_of
from services import constants as C
from services import loans


def current_value(appraisal):
    value = appraisal.get("current_value_cents")
    return appraisal["reported_value_cents"] if value is None else value


def exceeds_cap(appraisal, proposed):
    base = current_value(appraisal)
    if base is None or base == 0:
        return False
    return bps_of(abs(proposed - base), base) > C.REVISION_CAP_BPS


def write_revision(appraisal, loan, source_type, source_ref_id, new_value,
                   documentation_note, is_compensating=False):
    prior = current_value(appraisal)
    delta = new_value - prior
    ltv_before = loan.get("ltv_bps") if loan else None
    impact_before = loan.get("decision_impact") if loan else None

    appraisal["current_value_cents"] = new_value
    db.touch(appraisal)

    rec = db.make_record({
        "appraisal_id": appraisal["id"],
        "source_type": source_type,
        "source_ref_id": source_ref_id,
        "prior_value_cents": prior,
        "new_value_cents": new_value,
        "delta_cents": delta,
        "delta_bps": bps_of(abs(delta), prior) if prior else 0,
        "is_compensating": is_compensating,
        "ltv_bps_before": ltv_before,
        "ltv_bps_after": None,
        "decision_impact_before": impact_before,
        "decision_impact_after": None,
        "documentation_note": documentation_note,
    }, versioned=False)
    db.value_revisions[rec["id"]] = rec

    if loan is not None:
        loans.recompute_loan_values(loan)
        rec["ltv_bps_after"] = loan.get("ltv_bps")
        rec["decision_impact_after"] = loan.get("decision_impact")
    return rec
