"""Family coverage, the plan allowance, and the family-child risk multiplier (PRD §3.2, §3.5)."""

from test_helpers import (
    ApiErrorId,
    acknowledge_alert,
    assert_family_member,
    create_alert,
    create_alert_payload,
    create_family_member,
    create_family_member_payload,
    create_verified_subscriber,
    get_subscriber,
    make_subscriber_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

CHILD_PLAN = {"child_monitoring_included": True, "max_family_members": 4}
NO_CHILD_PLAN = {
    "tier": "ADVANTAGE",
    "monthly_fee_cents": 1999,
    "child_monitoring_included": False,
    "max_family_members": 4,
}


class TestFamilyMembership:
    def test_family_member_with_unknown_relationship_is_rejected(self, api):
        """PRD §3.2: "A household is more than one person, and a **FamilyMember** is added under a
        subscriber with a `full_name`, a `date_of_birth`, an `ssn_last4` of exactly four decimal
        digits, and a `relationship` of either `ADULT` or `CHILD`."
        PRD §2.5: "Body schema — required fields present, enum members drawn from the declared
        sets, integers non-negative, `ssn_last4` exactly four decimal digits, `expenses` a
        non-empty array of well-formed line items. Any breach is `ERR_INVALID_REQUEST`."

        Design: Corner/entities/family_member_invalid_enum_relationship_rejected
        """
        _, subscriber = create_verified_subscriber(plan_overrides=CHILD_PLAN)
        headers = make_subscriber_headers(subscriber["id"])

        resp = api.create_family_member(
            subscriber["id"],
            create_family_member_payload(
                full_name="Kid Ing", ssn_last4="3333", relationship="SPOUSE"
            ),
            headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

        members, _ = validate_paginated(api.list_family_members(subscriber["id"], headers))
        assert members == [], "the rejected payload created no family member"

    def test_child_is_not_covered_when_the_plan_excludes_child_monitoring(self, api):
        """PRD §3.2: "The member's derived `monitoring_status` is `MONITORED` for every `ADULT`,
        and for a `CHILD` only when the subscriber's plan has `child_monitoring_included` set to
        true; a `CHILD` on a plan without child monitoring gets `NOT_COVERED`."
        PRD §3.2: "Note carefully that the family-member row is still created in that case — the
        platform simply withholds monitoring coverage from it."
        PRD §3.2: "Family members are listable under their subscriber, ordered oldest-first by
        creation."

        Design: Corner/entities/family_member_child_not_covered_when_plan_excludes_children
        """
        _, subscriber = create_verified_subscriber(plan_overrides=NO_CHILD_PLAN)
        headers = make_subscriber_headers(subscriber["id"])

        adult = validate_success(
            api.create_family_member(
                subscriber["id"],
                create_family_member_payload(
                    full_name="Adult Larkin", ssn_last4="5555", relationship="ADULT"
                ),
                headers,
            ),
            201,
        )
        child = validate_success(
            api.create_family_member(
                subscriber["id"],
                create_family_member_payload(
                    full_name="Child Larkin", ssn_last4="6666", relationship="CHILD"
                ),
                headers,
            ),
            201,
        )

        assert_family_member(adult)
        assert_family_member(child)
        assert adult["monitoring_status"] == "MONITORED", "every ADULT is monitored"
        assert child["monitoring_status"] == "NOT_COVERED", (
            "child_monitoring_included is false on this plan"
        )

        members, meta = validate_paginated(api.list_family_members(subscriber["id"], headers))
        assert len(members) == 2 and meta["total_count"] == 2
        assert members[0]["id"] == adult["id"], "listed oldest-first by creation"
        assert members[1]["id"] == child["id"]

    def test_third_family_member_exceeds_a_two_member_allowance(self, api):
        """PRD §3.2: "Before the row is inserted, the count of family members already on this
        subscriber is compared against the plan's `max_family_members`: the insert proceeds only
        when the existing count is strictly less than the allowance, and is otherwise rejected with
        `ERR_FAMILY_LIMIT_EXCEEDED`."

        Design: Corner/validations/family_limit_exceeded_on_third_member
        """
        _, subscriber = create_verified_subscriber(
            plan_overrides={
                "tier": "ADVANTAGE",
                "monthly_fee_cents": 1999,
                "max_family_members": 2,
                "child_monitoring_included": True,
            }
        )
        headers = make_subscriber_headers(subscriber["id"])
        create_family_member(subscriber["id"], full_name="Fam One", ssn_last4="3333",
                             relationship="ADULT")
        create_family_member(subscriber["id"], full_name="Fam Two", ssn_last4="3434",
                             relationship="CHILD")

        resp = api.create_family_member(
            subscriber["id"],
            create_family_member_payload(
                full_name="Fam Three", ssn_last4="3535", relationship="CHILD"
            ),
            headers,
        )
        validate_error(resp, ApiErrorId.ERR_FAMILY_LIMIT_EXCEEDED)

        members, _ = validate_paginated(api.list_family_members(subscriber["id"], headers))
        assert len(members) == 2, "the allowance of two still holds exactly two members"


class TestAlertsAgainstDependents:
    def test_alert_naming_another_households_dependent_is_rejected(self, api, admin_headers):
        """PRD §3.2: "Alerts that name a `family_member_id` must name one that actually belongs to
        the `subscriber_id` given in the same body. A mismatch — a dependent of some other
        household — is rejected with `ERR_FAMILY_MEMBER_MISMATCH`."

        Design: Corner/validations/alert_family_member_mismatch_rejected
        """
        plan, sub_a = create_verified_subscriber(
            plan_overrides=CHILD_PLAN, full_name="Sub A", ssn_last4="3636"
        )
        _, sub_b = create_verified_subscriber(plan=plan, full_name="Sub B", ssn_last4="3737")
        child_of_b = create_family_member(
            sub_b["id"], full_name="B Child", ssn_last4="3838", relationship="CHILD"
        )

        resp = api.create_alert(
            create_alert_payload(
                sub_a["id"],
                family_member_id=child_of_b["id"],
                alert_type="SSN_TRACE",
                severity="HIGH",
                source_detail="cross-linked child SSN",
            ),
            admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FAMILY_MEMBER_MISMATCH)

        alerts, _ = validate_paginated(
            api.list_alerts(admin_headers, params={"subscriber_id": sub_a["id"]})
        )
        assert alerts == [], "the rejected ingestion created no alert"

    def test_alert_against_an_uncovered_child_is_refused_while_the_adult_is_accepted(
        self, api, admin_headers
    ):
        """PRD §3.2: "What the platform will *not* do is raise an alert against an uncovered
        dependent: an alert naming a family member whose `monitoring_status` is `NOT_COVERED` is
        refused with `ERR_CHILD_MONITORING_NOT_INCLUDED`."
        PRD §3.2: "The member's derived `monitoring_status` is `MONITORED` for every `ADULT`, and
        for a `CHILD` only when the subscriber's plan has `child_monitoring_included` set to true;
        a `CHILD` on a plan without child monitoring gets `NOT_COVERED`."

        Design: Corner/validations/alert_against_not_covered_child_rejected
        """
        _, subscriber = create_verified_subscriber(plan_overrides=NO_CHILD_PLAN)
        adult = create_family_member(
            subscriber["id"], full_name="Spouse Only", ssn_last4="4040", relationship="ADULT"
        )
        child = create_family_member(
            subscriber["id"], full_name="The Kid", ssn_last4="4141", relationship="CHILD"
        )
        assert adult["monitoring_status"] == "MONITORED"
        assert child["monitoring_status"] == "NOT_COVERED"

        adult_alert = validate_success(
            api.create_alert(
                create_alert_payload(
                    subscriber["id"],
                    family_member_id=adult["id"],
                    alert_type="DARK_WEB",
                    severity="LOW",
                    source_detail="spouse email in dump",
                ),
                admin_headers,
            ),
            201,
        )
        assert adult_alert["family_member_id"] == adult["id"]

        resp = api.create_alert(
            create_alert_payload(
                subscriber["id"],
                family_member_id=child["id"],
                alert_type="SSN_TRACE",
                severity="HIGH",
                source_detail="child SSN on credit application",
            ),
            admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_CHILD_MONITORING_NOT_INCLUDED)

        alerts, _ = validate_paginated(
            api.list_alerts(admin_headers, params={"subscriber_id": subscriber["id"]})
        )
        assert len(alerts) == 1 and alerts[0]["id"] == adult_alert["id"]


class TestFamilyChildMultiplier:
    def test_confirmed_child_fraud_multiplies_live_but_not_underwriting(self, api):
        """PRD §3.5: "LIVE also applies a **family-child multiplier**: if the subscriber has at
        least one family member whose `relationship` is `CHILD` and whose `monitoring_status` is
        `MONITORED`, and at least one alert naming that child as its `family_member_id` sits in
        `CONFIRMED_FRAUD` or `ESCALATED`, then the entire running total — base, type weights,
        escalation weight, score-drop weight and all — is multiplied by 1.20 before the rounding
        and clamping."
        PRD §3.5: "It counts *only* alerts the subscriber has actually confirmed as fraud —
        `CONFIRMED_FRAUD` or `ESCALATED` — and it applies that rule uniformly to all four alert
        types, so a `NEW` credit inquiry and an `ACKNOWLEDGED` dark-web hit are simply invisible to
        it. It never applies the family-child multiplier."

        Design: Corner/calculations/family_child_multiplier_applies_to_live_variant_only
        """
        _, subscriber = create_verified_subscriber(plan_overrides=CHILD_PLAN)
        child = create_family_member(
            subscriber["id"], full_name="Kid Ent", ssn_last4="2626", relationship="CHILD"
        )
        assert child["monitoring_status"] == "MONITORED"

        alert = create_alert(
            subscriber["id"],
            family_member_id=child["id"],
            alert_type="SSN_TRACE",
            severity="MEDIUM",
            source_detail="child SSN used for credit card",
        )
        acknowledge_alert(alert["id"])

        validate_success(
            api.confirm_fraud_alert(alert["id"], make_subscriber_headers(subscriber["id"]))
        )

        after = get_subscriber(subscriber["id"])
        # LIVE: round_half_up((10 base + 25 SSN_TRACE) * 1.20) == 42
        assert after["risk_score"] == 42, "LIVE applies the 1.20 family-child multiplier"
        # UNDERWRITING: 10 base + 25 SSN_TRACE, no multiplier
        assert after["underwriting_risk_score"] == 35, "UNDERWRITING never multiplies"