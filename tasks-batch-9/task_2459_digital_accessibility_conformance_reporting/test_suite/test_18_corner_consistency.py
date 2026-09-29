"""Consistency breadth: a fulfilment whose effects are already visible in its own
response and in the very next read, with no settle delay."""

from test_helpers import (
    DEFAULT_CLOCK,
    LEAD,
    LIAISON,
    complaint_triage_payload,
    create_component,
    create_product,
    create_standard,
    intake_complaint,
    read_complaint,
    read_product,
    validate_success,
)

APPLICABLE_CRITERIA = 40
NEEDED_BY_DATE = "2026-09-01"


def build_accommodation_routed_complaint():
    standard = create_standard(
        code="WCAG_2_2", title="WCAG 2.2", surface_scope="WEB", max_target_level="AAA"
    )
    product = create_product(
        standard["id"],
        name="Insight Portal",
        version_label="7.0",
        target_level="AA",
        surface_type="WEB",
    )
    component = create_component(
        product["id"],
        name="Web UI",
        component_type="WEB_UI",
        in_scope=True,
        assessment_scope="FULL",
        applicable_criteria_count=APPLICABLE_CRITERIA,
        user_reach_pct=60,
    )
    complaint = intake_complaint(
        product["id"],
        component_id=component["id"],
        channel="PHONE",
        description="I need the report exported in large print",
        disability_category="VISION",
    )
    return {
        "standard": standard,
        "product": product,
        "component": component,
        "complaint": complaint,
    }


class TestFulfilmentIsImmediatelyVisible:
    """The write's own response and the next read agree at once."""

    def test_the_product_counter_reads_one_on_the_very_next_request(self, api):
        """PRD §3.11: "On success the complaint moves `TRIAGED → ACCOMMODATED`,
        `accommodation_fulfilled_at` is stamped from the logical clock, and the
        product's `accommodations_fulfilled_count` is rebuilt."
        PRD §3.1: "`accommodations_fulfilled_count` is the number of the product's
        complaints that carry a recorded accommodation-fulfilment instant"
        PRD §2.4: "The clock begins at `2026-08-01T00:00:00Z` and an
        `AccessibilityLead` may move it to any instant supplied as `to_iso8601`."
        PRD §3.11: "Both branches join at closure, performed by an
        `AccessibilityLead` who supplies the `closure_outcome`."

        Design: Corner/consistency_model/corner_accommodation_fulfilment_is_visible_immediately
        """
        ctx = build_accommodation_routed_complaint()
        validate_success(
            api.triage_complaint(
                ctx["complaint"]["id"],
                complaint_triage_payload(
                    route="ACCOMMODATION",
                    requested_accommodation="Large-print export of the conformance report",
                    needed_by_date=NEEDED_BY_DATE,
                ),
                LEAD,
            )
        )

        assert read_product(ctx["product"]["id"])["accommodations_fulfilled_count"] == 0, (
            "nothing has been fulfilled yet"
        )

        fulfilled = validate_success(
            api.fulfill_accommodation(ctx["complaint"]["id"], {}, LIAISON)
        )

        assert fulfilled["state"] == "ACCOMMODATED", (
            f"the write's own response already carries the new state, got {fulfilled['state']}"
        )
        assert fulfilled["accommodation_fulfilled_at"].startswith(DEFAULT_CLOCK[:19]), (
            "the instant is stamped from the unmoved logical clock, got "
            f"{fulfilled['accommodation_fulfilled_at']}"
        )
        assert read_product(ctx["product"]["id"])["accommodations_fulfilled_count"] == 1, (
            "the rebuilt counter is visible on the next request with no retry"
        )
        assert read_complaint(ctx["complaint"]["id"])["closed_at"] is None, (
            "fulfilment is not closure"
        )
