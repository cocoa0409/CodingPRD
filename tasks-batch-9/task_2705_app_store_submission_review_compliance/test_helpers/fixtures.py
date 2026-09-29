"""Composite setup helpers.

Every helper builds its preconditions from scratch through PRD endpoints, because
each test runs against a freshly launched server with an empty database.

The `Ctx` object threads the identifiers and the per-role header dictionaries that
later calls need. Publisher-side roles are tenant scoped, so their headers always
carry the owning publisher account id; platform-side roles are opaque.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client as _default_client
from .constants import DEFAULT_CLOCK, TEST_DEFAULTS
from .factories import (
    CLEAN_AGE_RATING_ANSWERS,
    create_app_record_payload,
    create_commerce_item_payload,
    create_feature_mapping_payload,
    create_guideline_rule_payload,
    create_metadata_locale_payload,
    create_publisher_account_payload,
    create_review_capacity_window_payload,
    create_rollout_plan_payload,
    create_signing_credential_payload,
    create_submission_payload,
    unique_suffix,
)
from .test_users import (
    make_appeal_board_headers,
    make_auditor_headers,
    make_compliance_officer_headers,
    make_policy_admin_headers,
    make_publisher_admin_headers,
    make_release_manager_headers,
    make_reviewer_headers,
)


class Ctx:
    """Mutable bag of identifiers and headers shared by a setup chain."""

    def __init__(self, client, account_id, suffix="1"):
        self.client = client
        self.account_id = account_id
        self.suffix = suffix
        self.publisher_admin = make_publisher_admin_headers(
            account_id, f"u-pubadmin-{suffix}"
        )
        self.release_manager = make_release_manager_headers(
            account_id, f"u-release-{suffix}"
        )
        self.compliance_officer = make_compliance_officer_headers(
            account_id, f"u-compliance-{suffix}"
        )
        self.policy_admin = make_policy_admin_headers()
        self.reviewer = make_reviewer_headers()
        self.appeal_board = make_appeal_board_headers()
        self.auditor = make_auditor_headers()
        self.cert_id = None
        self.profile_id = None
        self.app_record_id = None
        self.submission_id = None
        self.window_id = None
        self.plan_id = None
        self.rules = {}
        self.mappings = {}
        self.submissions = []

    # -- convenience readers -------------------------------------------------
    def account(self):
        return get_success_data(
            self.client.get_publisher_account(self.account_id, self.publisher_admin)
        )

    def account_version(self):
        return self.account()["version"]

    def app(self):
        return get_success_data(
            self.client.get_app_record(self.app_record_id, self.release_manager)
        )

    def app_version(self):
        return self.app()["version"]

    def summary(self):
        return get_success_data(
            self.client.get_compliance_summary(
                self.app_record_id, self.compliance_officer
            )
        )

    def submission(self, submission_id=None):
        return get_success_data(
            self.client.get_submission(
                submission_id or self.submission_id, self.release_manager
            )
        )

    def window(self, window_id=None):
        return get_success_data(
            self.client.get_review_capacity_window(
                window_id or self.window_id, self.policy_admin
            )
        )

    def plan(self, plan_id=None):
        return get_success_data(
            self.client.get_rollout_plan(plan_id or self.plan_id, self.release_manager)
        )

    def mapping(self, mapping_id):
        return get_success_data(
            self.client.get_feature_mapping(mapping_id, self.compliance_officer)
        )

    def standing(self):
        return get_success_data(
            self.client.get_standing(self.account_id, self.policy_admin)
        )


def set_clock(client, current_utc):
    """Pin the logical clock. Any platform role may drive it; use the policy admin."""
    return get_success_data(client.set_clock(current_utc, make_policy_admin_headers()))


def new_account(client=None, suffix="1", **overrides):
    """Create one PublisherAccount and return a Ctx bound to it."""
    client = client or _default_client
    payload = create_publisher_account_payload(**overrides)
    data = get_success_data(
        client.create_publisher_account(payload, make_policy_admin_headers())
    )
    return Ctx(client, data["id"], suffix=suffix)


def add_credentials(ctx, platform="IOS", **cert_overrides):
    """Register and activate a DISTRIBUTION_CERT plus a linked PROVISIONING_PROFILE."""
    cert_payload = create_signing_credential_payload(
        ctx.account_id,
        ctx.account_version(),
        platform=platform,
        **cert_overrides,
    )
    cert = get_success_data(
        ctx.client.create_signing_credential(cert_payload, ctx.publisher_admin)
    )
    get_success_data(
        ctx.client.activate_signing_credential(cert["id"], ctx.publisher_admin)
    )
    profile_payload = create_signing_credential_payload(
        ctx.account_id,
        ctx.account_version(),
        credential_type="PROVISIONING_PROFILE",
        platform=platform,
        key_custody="CLOUD_MANAGED",
        linked_cert_id=cert["id"],
    )
    profile = get_success_data(
        ctx.client.create_signing_credential(profile_payload, ctx.publisher_admin)
    )
    get_success_data(
        ctx.client.activate_signing_credential(profile["id"], ctx.publisher_admin)
    )
    ctx.cert_id = cert["id"]
    ctx.profile_id = profile["id"]
    return ctx


def add_app_record(ctx, **overrides):
    """Create the AppRecord that everything else in the chain hangs from."""
    payload = create_app_record_payload(ctx.account_id, **overrides)
    data = get_success_data(
        ctx.client.create_app_record(payload, ctx.publisher_admin)
    )
    ctx.app_record_id = data["id"]
    return data


def add_effective_rule(ctx, key="privacy", publish=True, **overrides):
    """Create a GuidelineRule and, by default, publish it so it is EFFECTIVE."""
    payload = create_guideline_rule_payload(**overrides)
    data = get_success_data(
        ctx.client.create_guideline_rule(payload, ctx.policy_admin)
    )
    if publish:
        data = get_success_data(
            ctx.client.publish_guideline_rule(data["id"], ctx.policy_admin)
        )
    ctx.rules[key] = data["id"]
    return data


def add_mapping(ctx, rule_id, feature_code="ACCOUNT_DELETION", advance="PASS",
                key=None, evidence_ref=None, **overrides):
    """Create a FeatureMapping and optionally drive its self review.

    advance is None to leave it NOT_STARTED, "START" to leave it IN_PROGRESS,
    or "PASS"/"FAIL" to run START and then that outcome.
    """
    payload = create_feature_mapping_payload(
        ctx.app_record_id, rule_id, feature_code=feature_code, **overrides
    )
    data = get_success_data(
        ctx.client.create_feature_mapping(payload, ctx.compliance_officer)
    )
    mapping_id = data["id"]
    if advance in ("START", "PASS", "FAIL"):
        data = get_success_data(
            ctx.client.self_review_mapping(
                mapping_id, {"outcome": "START"}, ctx.compliance_officer
            )
        )
    if advance in ("PASS", "FAIL"):
        body = {"outcome": advance}
        if advance == "PASS":
            body["evidence_ref"] = evidence_ref or TEST_DEFAULTS["EVIDENCE_REF"]
        data = get_success_data(
            ctx.client.self_review_mapping(mapping_id, body, ctx.compliance_officer)
        )
    # Register under both the caller's nickname and the feature code, so a test may
    # reach the mapping by either handle.
    if key:
        ctx.mappings[key] = mapping_id
    ctx.mappings[feature_code] = mapping_id
    return data


def add_window(ctx, **overrides):
    """Open a ReviewCapacityWindow covering the default clock."""
    payload = create_review_capacity_window_payload(**overrides)
    data = get_success_data(
        ctx.client.create_review_capacity_window(payload, ctx.policy_admin)
    )
    ctx.window_id = data["id"]
    return data


def add_submission(ctx, build_number=10, version_string="1.0.0", **overrides):
    """Create a Submission against the current AppRecord revision."""
    payload = create_submission_payload(
        ctx.app_record_id,
        ctx.profile_id,
        ctx.app_version(),
        build_number=build_number,
        version_string=version_string,
        **overrides,
    )
    data = get_success_data(
        ctx.client.create_submission(payload, ctx.release_manager)
    )
    ctx.submission_id = data["id"]
    ctx.submissions.append(data["id"])
    return data


def add_locale(ctx, submission_id=None, **overrides):
    """Attach a complete primary en-US MetadataLocale to a submission."""
    payload = create_metadata_locale_payload(
        submission_id or ctx.submission_id, **overrides
    )
    return get_success_data(
        ctx.client.create_metadata_locale(payload, ctx.release_manager)
    )


def set_questionnaire(ctx, submission_id=None, answers=None, attested_age_rating=4,
                      **answer_overrides):
    """Set the content questionnaire; defaults to the all-clean answers."""
    body = dict(CLEAN_AGE_RATING_ANSWERS) if answers is None else dict(answers)
    body.update(answer_overrides)
    return get_success_data(
        ctx.client.set_age_rating(
            submission_id or ctx.submission_id,
            {"age_rating_answers": body, "attested_age_rating": attested_age_rating},
            ctx.compliance_officer,
        )
    )


def set_privacy(ctx, submission_id=None, declared_privacy_items=None,
                tracking_consent_prompt_present=False):
    """Set the privacy label; defaults to declaring nothing at all."""
    return get_success_data(
        ctx.client.set_privacy_declaration(
            submission_id or ctx.submission_id,
            {
                "declared_privacy_items": list(declared_privacy_items or []),
                "tracking_consent_prompt_present": tracking_consent_prompt_present,
            },
            ctx.compliance_officer,
        )
    )


def complete_content(ctx, submission_id=None, answers=None, attested_age_rating=4,
                     declared_privacy_items=None,
                     tracking_consent_prompt_present=False, locale_overrides=None):
    """Attach the locale and both content declarations a build needs to pass pre-review."""
    submission_id = submission_id or ctx.submission_id
    add_locale(ctx, submission_id, **(locale_overrides or {}))
    set_questionnaire(
        ctx, submission_id, answers=answers, attested_age_rating=attested_age_rating
    )
    set_privacy(
        ctx,
        submission_id,
        declared_privacy_items=declared_privacy_items,
        tracking_consent_prompt_present=tracking_consent_prompt_present,
    )
    return submission_id


def run_pre_review(ctx, submission_id=None):
    """Run the pre-review check and return the refreshed submission."""
    return get_success_data(
        ctx.client.pre_review_check(
            submission_id or ctx.submission_id, ctx.compliance_officer
        )
    )


def queue(ctx, submission_id=None, payload=None):
    return get_success_data(
        ctx.client.queue_submission(
            submission_id or ctx.submission_id, ctx.release_manager, payload
        )
    )


def claim(ctx, submission_id=None, reviewer_headers=None):
    return get_success_data(
        ctx.client.claim_submission(
            submission_id or ctx.submission_id, reviewer_headers or ctx.reviewer
        )
    )


def decide(ctx, payload, submission_id=None, reviewer_headers=None):
    return get_success_data(
        ctx.client.decide_submission(
            submission_id or ctx.submission_id,
            payload,
            reviewer_headers or ctx.reviewer,
        )
    )


def approve(ctx, submission_id=None, reviewer_headers=None):
    """Queue, claim and APPROVE one build that already passed pre-review."""
    submission_id = submission_id or ctx.submission_id
    queue(ctx, submission_id)
    claim(ctx, submission_id, reviewer_headers)
    return decide(ctx, {"outcome": "APPROVE"}, submission_id, reviewer_headers)


def reject(ctx, rejection_reasons, submission_id=None, reviewer_headers=None,
           outcome="REJECT"):
    """Queue, claim and REJECT (or METADATA_REJECT) one build."""
    submission_id = submission_id or ctx.submission_id
    queue(ctx, submission_id)
    claim(ctx, submission_id, reviewer_headers)
    return decide(
        ctx,
        {"outcome": outcome, "rejection_reasons": list(rejection_reasons)},
        submission_id,
        reviewer_headers,
    )


def add_rollout_plan(ctx, submission_id=None, start=False, **overrides):
    """Create a RolloutPlan against the current AppRecord revision."""
    payload = create_rollout_plan_payload(
        ctx.app_record_id,
        submission_id or ctx.submission_id,
        ctx.app_version(),
        **overrides,
    )
    data = get_success_data(
        ctx.client.create_rollout_plan(payload, ctx.release_manager)
    )
    ctx.plan_id = data["id"]
    if start:
        data = get_success_data(
            ctx.client.start_rollout_plan(data["id"], ctx.release_manager)
        )
    return data


def add_approved_commerce_item(ctx, reviewer_headers=None, **overrides):
    """Create, submit and APPROVE one CommerceItem."""
    payload = create_commerce_item_payload(ctx.app_record_id, **overrides)
    data = get_success_data(
        ctx.client.create_commerce_item(payload, ctx.publisher_admin)
    )
    get_success_data(
        ctx.client.submit_commerce_item(data["id"], ctx.publisher_admin)
    )
    return get_success_data(
        ctx.client.review_commerce_item(
            data["id"],
            {"outcome": "APPROVE"},
            reviewer_headers or make_reviewer_headers("u-reviewer-2"),
        )
    )


def rejection_reasons_for(rule_id, severity="CRITICAL", reason_code="PRIVACY_LABEL_INACCURATE",
                          detail="Undisclosed device-id sharing to an advertising domain"):
    """One rejection-reason entry for the decision payload."""
    return [
        {
            "guideline_rule_id": rule_id,
            "reason_code": reason_code,
            "severity": severity,
            "detail": detail,
        }
    ]


def setup_base_ios(
    client=None,
    suffix="1",
    platform="IOS",
    account_overrides=None,
    cert_overrides=None,
    app_overrides=None,
    rule_overrides=None,
    mapping_advance="PASS",
    risk_weight=None,
    with_app=True,
    with_rule=True,
    with_mapping=True,
    with_submission=True,
    with_content=True,
    with_window=True,
    with_pre_review=True,
    build_number=10,
    version_string="1.0.0",
    submission_overrides=None,
    answers=None,
    attested_age_rating=4,
    declared_privacy_items=None,
    tracking_consent_prompt_present=False,
    locale_overrides=None,
    window_overrides=None,
):
    """The canonical chain: ACTIVE account, activated IOS cert plus linked profile,
    one AppRecord, one EFFECTIVE PRIVACY rule with one PASSED mapping, one build with
    a complete primary locale and both content declarations, one open capacity window
    and a run pre-review check.

    Every stage can be switched off so a test can stop the chain where it needs to.
    """
    ctx = new_account(client, suffix=suffix, **(account_overrides or {}))
    add_credentials(ctx, platform=platform, **(cert_overrides or {}))
    if not with_app:
        return ctx
    add_app_record(ctx, platform=platform, **(app_overrides or {}))
    if with_rule:
        add_effective_rule(ctx, key="privacy", **(rule_overrides or {}))
        if with_mapping:
            mapping_kwargs = {}
            if risk_weight is not None:
                mapping_kwargs["risk_weight"] = risk_weight
            add_mapping(
                ctx,
                ctx.rules["privacy"],
                advance=mapping_advance,
                key="privacy",
                **mapping_kwargs,
            )
    if not with_submission:
        if with_window:
            add_window(ctx, platform=platform, **(window_overrides or {}))
        return ctx
    add_submission(
        ctx,
        build_number=build_number,
        version_string=version_string,
        **(submission_overrides or {}),
    )
    if with_content:
        complete_content(
            ctx,
            answers=answers,
            attested_age_rating=attested_age_rating,
            declared_privacy_items=declared_privacy_items,
            tracking_consent_prompt_present=tracking_consent_prompt_present,
            locale_overrides=locale_overrides,
        )
    if with_window:
        add_window(ctx, platform=platform, **(window_overrides or {}))
    if with_pre_review:
        run_pre_review(ctx)
    return ctx


def setup_approved_ios(**kwargs):
    """setup_base_ios followed by queue, claim and APPROVE on the one build."""
    ctx = setup_base_ios(**kwargs)
    approve(ctx)
    return ctx


def setup_released_ios(client=None, mode="PHASED", scheduled_start_at=None, **kwargs):
    """setup_approved_ios followed by a started RolloutPlan, so the app is distributing.

    `client` is the first positional parameter, matching setup_base_ios, so a caller may
    write setup_released_ios(api).
    """
    ctx = setup_approved_ios(client=client, **kwargs)
    add_rollout_plan(
        ctx,
        mode=mode,
        scheduled_start_at=scheduled_start_at or DEFAULT_CLOCK,
        start=True,
    )
    return ctx


def setup_two_accounts(client=None, **kwargs):
    """Two independent accounts each owning one AppRecord and one DRAFT build.

    Used for the tenancy rung: account A reaching account B's rows.
    """
    a = setup_base_ios(
        client,
        suffix="1",
        with_rule=False,
        with_content=False,
        with_window=False,
        with_pre_review=False,
        app_overrides={"bundle_id": f"com.northwind.wallet{unique_suffix()}"},
        **kwargs,
    )
    b = setup_base_ios(
        a.client,
        suffix="2",
        with_rule=False,
        with_content=False,
        with_window=False,
        with_pre_review=False,
        app_overrides={
            "bundle_id": f"com.eastgate.reader{unique_suffix()}",
            "display_name": "Eastgate Reader",
        },
        **kwargs,
    )
    return a, b
