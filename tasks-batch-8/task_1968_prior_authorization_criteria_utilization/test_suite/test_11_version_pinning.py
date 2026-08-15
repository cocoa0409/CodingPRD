"""Guideline version pinning across supersession (PRD §3.2)."""
from test_helpers import (
    basic_um_environment,
    create_guideline_version,
    get_criteria_set,
    list_request_determinations,
    pended_request,
    publish_guideline_version,
    reviewer_decide,
)


def test_version_pinning_holds_across_supersede(api):
    """PRD §3.2: "The chosen version is stored as the request's `guideline_version_id` and is **never re-pinned**: later supersession or retirement of the version does not disturb the request."
    PRD §3.4: "Segments are joined by pipe characters in this fixed order: the literal `OUTCOME:` followed by the outcome; `|SERVICE:` followed by the request's `service_code`; `|REASON:` followed by the reason code; `|CRITERIA:` followed by the criteria set's `name`, an at-sign, and the pinned version's `version_label`; `|ISSUED:` followed by `issued_at` in ISO 8601 UTC with three fractional digits; `|APPEAL_BY:` followed by the appeal deadline — `issued_at` plus 4,320 hours (the 180-day appeal window) — in the same format; and `|DECIDED_BY:` followed by the deciding role."

    Design: Corner/cross_cutting_layers/guideline_version_pinning_holds_across_supersede
    """
    provider, cs, gv1 = basic_um_environment()
    req = pended_request(provider["id"], cs["id"])
    assert req["guideline_version_id"] == gv1["id"], (
        "intake pinned the version covering received_at"
    )
    gv2 = create_guideline_version(
        cs["id"], version_label="2.0", content="Clinical criteria v2",
        effective_from="2026-09-01T00:00:00Z",
        supersedes_version_id=gv1["id"],
    )
    publish_guideline_version(gv2["id"], get_criteria_set(cs["id"])["version"])
    reviewer_decide(
        req["id"], "DENY", reason_code="MEDICAL_NECESSITY_NOT_MET",
    )
    det = list_request_determinations(req["id"])[0]
    assert det["guideline_version_id"] == gv1["id"], (
        "supersession by v2 did not re-pin the in-flight request"
    )
    assert "CRITERIA:Spine Imaging Criteria@1.0" in det["notice_text"]
