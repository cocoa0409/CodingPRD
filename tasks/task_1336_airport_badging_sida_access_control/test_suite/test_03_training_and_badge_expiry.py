"""Training-currency computation and the badge expiry horizons."""
from test_helpers import (
    BO,
    ApiErrorId,
    api_client,
    assert_training_completion,
    create_applicant,
    create_sponsor,
    get_application,
    get_badge,
    issue_badge,
    open_application,
    record_chrc_pass,
    record_sta_cleared,
    record_training,
    replace_badge,
    set_clock,
    setup_issued_badge,
    setup_ready_application,
    validate_error,
)


class TestTrainingCompletionExpiry:

    def test_training_completion_expiry_computed_from_course(self):
        """PRD section 3.3: "Four courses exist with four validity periods:
        `SIDA_INITIAL` is valid for twelve months, `AOA_SAFETY` for
        twenty-four months, `AOA_DRIVING` for twelve months, and
        `STERILE_INITIAL` for twelve months."
        PRD section 2.4: "both carry only `id` and `created_at` — the
        `updated_at` and `version` fields are absent from both."

        Design: Corner/entities/training_completion_expiry_computed_from_course
        """
        sponsor = create_sponsor()
        applicant = create_applicant(sponsor["id"])

        c1 = record_training(applicant["id"], "SIDA_INITIAL",
                             completed_at="2026-06-01T00:00:00Z")
        assert_training_completion(c1)
        assert c1["expires_at"] == "2027-06-01T00:00:00Z", \
            "SIDA_INITIAL carries a twelve-month validity"

        c2 = record_training(applicant["id"], "AOA_SAFETY",
                             completed_at="2026-06-01T00:00:00Z")
        assert_training_completion(c2)
        assert c2["expires_at"] == "2028-06-01T00:00:00Z", \
            "AOA_SAFETY carries a twenty-four-month validity"


class TestBadgeExpiryNestedMin:

    def test_sida_badge_expiry_binds_on_earliest_course_horizon(self):
        """PRD section 3.4: "The new badge's `expires_at` is computed as the
        earlier of two horizons: twenty-four calendar months after
        `issued_at`, or the nearest expiry among the completions satisfying
        the required courses."

        Design: Difficulty/combinatorial_formula/badge_expiry_nested_min_inputs
        """
        ctx = setup_issued_badge(
            sponsor_code="NM", sponsor_name="North Maintenance",
            full_name="Eli Finn", government_id_number="G3001",
            date_of_birth="1991-02-02",
            badge_class="SIDA", completed_at="2026-06-01T00:00:00Z",
            badge_number="B301")
        badge = get_badge(ctx["badge"]["id"])
        assert badge["expires_at"] == "2027-06-01T00:00:00Z", (
            "min(2028-08-01 cap, SIDA_INITIAL 2027-06-01, AOA_SAFETY "
            "2028-06-01): the earliest course horizon binds, not the cap")

    def test_sterile_badge_expiry_binds_on_single_course_horizon(self):
        """PRD section 3.4: "The computation combines at least three inputs —
        the issuance instant, the twenty-four-month cap, and one horizon per
        required course — through nested earliest-of comparisons."

        Design: Difficulty/combinatorial_formula/badge_expiry_nested_min_inputs
        """
        ctx = setup_issued_badge(
            sponsor_code="NM", sponsor_name="North Maintenance",
            full_name="Fay Goss", government_id_number="G3002",
            date_of_birth="1993-06-06",
            badge_class="STERILE", completed_at="2026-07-10T00:00:00Z",
            badge_number="B302")
        badge = get_badge(ctx["badge"]["id"])
        assert badge["expires_at"] == "2027-07-10T00:00:00Z", \
            "min(2028-08-01 cap, STERILE_INITIAL 2027-07-10)"


class TestStrictVersusRenewalGrace:

    def _setup_lapsed_training(self):
        """Applicant a1 holds a STERILE badge issued against a completion
        expiring 2027-07-10; clock at 2027-07-20 (badge swept EXPIRED).
        Applicant a2's STERILE application rests at PENDING_REQUIREMENTS with
        the same lapsed completion."""
        sponsor = create_sponsor(sponsor_code="SC", name="SkyChefs")
        a1 = create_applicant(sponsor["id"], full_name="Cara Dunn",
                              date_of_birth="1992-03-04",
                              government_id_number="G2001")
        app1, _ = setup_ready_application(
            sponsor["id"], a1["id"], badge_class="STERILE",
            completed_at="2026-07-10T00:00:00Z")
        b1 = issue_badge(app1["id"], "B201")
        assert b1["expires_at"] == "2027-07-10T00:00:00Z"

        set_clock("2027-07-20T00:00:00Z")

        a2 = create_applicant(sponsor["id"], full_name="Dan Eells",
                              date_of_birth="1995-07-08",
                              government_id_number="G2002")
        app2 = open_application(a2["id"], sponsor["id"], badge_class="STERILE")
        record_chrc_pass(app2["id"],
                         fingerprint_submitted_at="2027-07-20T00:00:00Z")
        record_sta_cleared(app2["id"])
        record_training(a2["id"], "STERILE_INITIAL",
                        completed_at="2026-07-10T00:00:00Z")
        return sponsor, b1, app2

    def test_renewal_grace_variant_allows_replace_with_lapsed_training(self):
        """PRD section 3.3: "A completion is **grace-current** when its
        `expires_at` plus thirty days lies strictly in the future, so
        coursework lapsed by at most thirty days still counts."
        PRD section 3.3: "Badge replacement uses the grace regime: every
        required course must hold a grace-current completion, which means
        identical training data can pass the replacement gate while failing
        the readiness gate."

        Design: Difficulty/dual_variant_calc/training_currency_strict_vs_renewal_grace
        """
        _, b1, app2 = self._setup_lapsed_training()

        new_badge = replace_badge(b1["id"], "B201R")
        assert new_badge["status"] == "ACTIVE"
        assert new_badge["expires_at"] == "2027-08-09T00:00:00Z", \
            "min(issued 2027-07-20 + 24 months, 2027-07-10 + 30-day grace)"

        old = get_badge(b1["id"])
        assert old["status"] == "VOIDED"
        assert old["superseded_by_badge_id"] == new_badge["id"]

        assert get_application(app2["id"])["status"] == "PENDING_REQUIREMENTS", \
            "the same lapsed completion fails the strict readiness regime"

    def test_strict_variant_blocks_initial_issuance_with_lapsed_training(self):
        """PRD section 3.3: "Initial issuance uses the strict regime:
        readiness evaluation, and therefore the `READY` gate on issuance,
        demands a strictly current completion for every required course."
        PRD section 3.4: "The application itself must be `READY`, else
        `ERR_APPLICATION_NOT_READY`."

        Design: Difficulty/dual_variant_calc/training_currency_strict_vs_renewal_grace
        """
        _, _, app2 = self._setup_lapsed_training()

        resp = api_client.issue_badge(app2["id"], {"badge_number": "B202"}, BO)
        validate_error(resp, ApiErrorId.ERR_APPLICATION_NOT_READY)
        assert get_application(app2["id"])["status"] == "PENDING_REQUIREMENTS"


class TestBadgeExpirySweep:

    def test_badge_expiry_sweep_at_exact_expiry(self):
        """PRD section 2.5: "Badges in `ACTIVE` or `SUSPENDED` whose
        `expires_at` has been reached or passed transition to `EXPIRED`".
        PRD section 3.5: "Badges that age out under the clock sweep land in
        `EXPIRED` with `deactivated_at` set to the badge's own `expires_at`
        and `return_deadline` thirty days after that, again revoking any
        granted escort privilege as `BADGE_DEACTIVATED`."

        Design: Corner/calculations/badge_expiry_sweep_at_exact_expiry
        """
        ctx = setup_issued_badge(badge_class="STERILE", badge_number="B801",
                                 completed_at="2026-06-01T00:00:00Z")
        badge_id = ctx["badge"]["id"]
        assert ctx["badge"]["expires_at"] == "2027-06-01T00:00:00Z"

        set_clock("2027-05-31T00:00:00Z")
        assert get_badge(badge_id)["status"] == "ACTIVE", \
            "one day before expires_at the badge is still ACTIVE"

        set_clock("2027-06-01T00:00:00Z")
        swept = get_badge(badge_id)
        assert swept["status"] == "EXPIRED", \
            "at exactly expires_at the sweep is inclusive"
        assert swept["deactivated_at"] == "2027-06-01T00:00:00Z"
        assert swept["return_deadline"] == "2027-07-01T00:00:00Z"
