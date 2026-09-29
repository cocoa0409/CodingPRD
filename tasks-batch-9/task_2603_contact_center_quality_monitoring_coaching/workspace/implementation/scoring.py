"""Shared item_scores validation (PRD 3.5 submit, 3.6 uphold, 3.7 calibration).

Ladder stage 11 sub-order: 11.1 ERR_FORM_VERSION_MISMATCH (unknown key),
11.7 ERR_ITEM_SCORE_INCOMPLETE, 11.8 ERR_ITEM_SCORE_OUT_OF_RANGE,
11.9 ERR_NA_NOT_ALLOWED.
"""
from common import fail


def validate_item_scores(behaviors, scores, check_complete=True):
    """`behaviors` must already be ordered by code ASC."""
    by_code = {b["code"]: b for b in behaviors}

    for key in scores:
        if key not in by_code:
            fail("ERR_FORM_VERSION_MISMATCH",
                 "'%s' is not a behaviour code of the referenced form" % key)

    if check_complete:
        for b in behaviors:
            if b["code"] not in scores:
                fail("ERR_ITEM_SCORE_INCOMPLETE",
                     "no score supplied for behaviour '%s'" % b["code"])

    for b in behaviors:
        if b["code"] not in scores:
            continue
        value = scores[b["code"]]
        if value == "NA":
            continue
        if value < 0 or value > int(b["max_points"]):
            fail("ERR_ITEM_SCORE_OUT_OF_RANGE",
                 "the score for '%s' must be an integer from 0 through %s"
                 % (b["code"], b["max_points"]))

    for b in behaviors:
        if scores.get(b["code"]) != "NA":
            continue
        if not b.get("allows_not_applicable"):
            fail("ERR_NA_NOT_ALLOWED",
                 "behaviour '%s' does not allow \"NA\"" % b["code"])
        if b.get("compliance_critical"):
            fail("ERR_NA_NOT_ALLOWED",
                 "a compliance-critical behaviour such as '%s' may never be \"NA\""
                 % b["code"])
